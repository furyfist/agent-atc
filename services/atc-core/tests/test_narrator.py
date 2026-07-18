"""Unit tests for the Narrator: condense_timeline, ActionStoreSpanFetcher,
and Narrator.narrate's caching orchestration. chat_fn is injected/faked -
see narrator.py's docstring for why (same reasoning as agent_runner's
injectable chat_fn: testable without spending real Groq budget).
"""

from __future__ import annotations

import pytest

from atc_core.narrator import (
    ActionStoreSpanFetcher,
    FallbackSpanFetcher,
    Narrator,
    SpanRecord,
    condense_timeline,
)
from atc_core.narrator.narrator import NO_ACTIVITY_TEXT
from atc_core.risk.models import RiskLevel
from atc_core.store import Action, ActionStatus, Agent, Store


@pytest.fixture
async def store():
    s = await Store.connect(":memory:")
    await s.upsert_agent(
        Agent(
            id="coder-01", persona="coder", scope=["db"], owner=None,
            quarantined=False, last_heartbeat_ts=None, created_at=1000.0,
        )
    )
    yield s
    await s.close()


def _action(
    action_id: str, trace_id: str, *, status: ActionStatus = ActionStatus.DENIED, resolved_at: float | None = 1010.0
) -> Action:
    return Action(
        action_id=action_id,
        trace_id=trace_id,
        span_id=None,
        agent_id="coder-01",
        tool="db__execute",
        resource_class="db",
        resource_name="customers",
        args_summary='{"sql": "DELETE FROM customers"}',
        risk_level=RiskLevel.HIGH,
        risk_reason="Statement touches a table tagged as production",
        rule_id="SQL-PROD-TABLE-HIGH",
        status=status,
        decided_by="alice" if status != ActionStatus.PENDING else None,
        requested_at=1000.0,
        resolved_at=resolved_at,
    )


# --- condense_timeline -------------------------------------------------------


def test_condense_timeline_formats_spans_in_order() -> None:
    spans = [
        SpanRecord(name="tool_call.db__execute", timestamp=1000.0, attributes={"agent.id": "coder-01"}),
        SpanRecord(name="decision.db__execute", timestamp=1010.0, attributes={"atc.decision": "DENIED"}),
    ]
    text = condense_timeline(spans)
    assert "tool_call.db__execute" in text
    assert "decision.db__execute" in text
    assert text.index("tool_call.db__execute") < text.index("decision.db__execute")


def test_condense_timeline_drops_none_valued_attributes() -> None:
    spans = [SpanRecord(name="x", timestamp=1.0, attributes={"a": "1", "b": None})]
    text = condense_timeline(spans)
    assert "a=1" in text
    assert "b=" not in text


def test_condense_timeline_truncates_to_max_chars() -> None:
    spans = [SpanRecord(name="x" * 100, timestamp=float(i), attributes={}) for i in range(50)]
    text = condense_timeline(spans, max_chars=200)
    assert len(text) == 200
    assert text.endswith("...")


# --- ActionStoreSpanFetcher --------------------------------------------------


async def test_fetcher_returns_request_and_decision_spans(store: Store) -> None:
    await store.insert_action(_action("a1", "trace-1"))
    fetcher = ActionStoreSpanFetcher(store)

    spans = await fetcher.fetch_spans("trace-1")

    assert len(spans) == 2
    assert spans[0].name == "tool_call.db__execute"
    assert spans[0].attributes["atc.risk.level"] == "HIGH"
    assert spans[1].name == "decision.db__execute"
    assert spans[1].attributes["atc.decision"] == "DENIED"
    assert spans[1].attributes["atc.decision.by"] == "alice"


async def test_fetcher_only_returns_a_request_span_for_unresolved_actions(store: Store) -> None:
    await store.insert_action(_action("a1", "trace-1", status=ActionStatus.PENDING, resolved_at=None))
    fetcher = ActionStoreSpanFetcher(store)

    spans = await fetcher.fetch_spans("trace-1")

    assert len(spans) == 1
    assert spans[0].name == "tool_call.db__execute"


async def test_fetcher_filters_by_trace_id(store: Store) -> None:
    await store.insert_action(_action("a1", "trace-1"))
    await store.insert_action(_action("a2", "trace-2"))
    fetcher = ActionStoreSpanFetcher(store)

    spans = await fetcher.fetch_spans("trace-1")

    assert all("a1" not in "" for _ in spans)  # sanity: no crash
    assert len(spans) == 2  # only trace-1's request+decision, not trace-2's


async def test_fetcher_returns_empty_for_unknown_trace(store: Store) -> None:
    fetcher = ActionStoreSpanFetcher(store)
    assert await fetcher.fetch_spans("nope") == []


# --- FallbackSpanFetcher ------------------------------------------------------


async def test_fallback_uses_primary_when_it_returns_spans() -> None:
    primary_spans = [SpanRecord(name="from_primary", timestamp=1.0, attributes={})]
    fetcher = FallbackSpanFetcher(_FakeFetcher(primary_spans), _FakeFetcher([SpanRecord(name="from_secondary", timestamp=1.0, attributes={})]))

    spans = await fetcher.fetch_spans("trace-1")

    assert [s.name for s in spans] == ["from_primary"]


async def test_fallback_uses_secondary_when_primary_is_empty() -> None:
    secondary_spans = [SpanRecord(name="from_secondary", timestamp=1.0, attributes={})]
    fetcher = FallbackSpanFetcher(_FakeFetcher([]), _FakeFetcher(secondary_spans))

    spans = await fetcher.fetch_spans("trace-1")

    assert [s.name for s in spans] == ["from_secondary"]


# --- Narrator.narrate ---------------------------------------------------------


class _FakeFetcher:
    def __init__(self, spans: list[SpanRecord]) -> None:
        self._spans = spans

    async def fetch_spans(self, trace_id: str) -> list[SpanRecord]:
        return self._spans


async def test_narrate_calls_chat_fn_and_caches_result(store: Store) -> None:
    spans = [SpanRecord(name="tool_call.db__execute", timestamp=1000.0, attributes={"agent.id": "coder-01"})]
    calls: list[tuple[str, str]] = []

    async def chat_fn(system_prompt: str, user_content: str) -> str:
        calls.append((system_prompt, user_content))
        return "The agent tried a risky delete and was denied."

    narrator = Narrator(store=store, span_fetcher=_FakeFetcher(spans), chat_fn=chat_fn)
    text = await narrator.narrate("trace-1")

    assert text == "The agent tried a risky delete and was denied."
    assert len(calls) == 1
    assert "tool_call.db__execute" in calls[0][1]

    cached = await store.get_narration("trace-1")
    assert cached == text


async def test_narrate_returns_cached_result_without_calling_chat_fn_again(store: Store) -> None:
    await store.upsert_narration("trace-1", "already narrated", 1000.0)
    calls = {"n": 0}

    async def chat_fn(system_prompt: str, user_content: str) -> str:
        calls["n"] += 1
        return "should not be called"

    narrator = Narrator(store=store, span_fetcher=_FakeFetcher([]), chat_fn=chat_fn)
    text = await narrator.narrate("trace-1")

    assert text == "already narrated"
    assert calls["n"] == 0


async def test_narrate_with_no_spans_returns_no_activity_text_and_caches_it(store: Store) -> None:
    calls = {"n": 0}

    async def chat_fn(system_prompt: str, user_content: str) -> str:
        calls["n"] += 1
        return "unused"

    narrator = Narrator(store=store, span_fetcher=_FakeFetcher([]), chat_fn=chat_fn)
    text = await narrator.narrate("trace-empty")

    assert text == NO_ACTIVITY_TEXT
    assert calls["n"] == 0
    assert await store.get_narration("trace-empty") == NO_ACTIVITY_TEXT
