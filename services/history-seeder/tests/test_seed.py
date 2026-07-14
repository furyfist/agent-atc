"""See PROJECT_PLAN.md S4 (history-seeder), S6 (creep baseline)."""

from __future__ import annotations

import random
import time

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from atc_core.gateway import AgentIdentity
from atc_core.store import ActionStatus
from history_seeder.seed import emit_backdated_spans, generate_history

AGENTS = [
    AgentIdentity(id="coder-01", persona="coder", scope=frozenset({"db", "fs", "git"}), owner="team"),
    AgentIdentity(id="assist-01", persona="assistant", scope=frozenset({"email", "fs"}), owner="team"),
    AgentIdentity(id="comply-01", persona="compliance", scope=frozenset({"fs"}), owner="team"),
]

SCOPE_BY_AGENT = {a.id: a.scope for a in AGENTS}


def test_generate_history_stays_within_window():
    now = 1_000_000.0
    days = 3
    actions = generate_history(AGENTS, days=days, now=now, rng=random.Random(7))

    assert actions
    for action in actions:
        assert now - days * 86_400 <= action.requested_at <= now - 3600
        if action.resolved_at is not None:
            assert action.resolved_at >= action.requested_at


def test_generate_history_only_uses_in_scope_tools():
    actions = generate_history(AGENTS, days=2, now=2_000_000.0, rng=random.Random(1))
    assert actions
    for action in actions:
        namespace = action.tool.split("__", 1)[0]
        assert namespace in SCOPE_BY_AGENT[action.agent_id]


def test_generate_history_never_produces_pending():
    """A seeded row must never be PENDING - there's no real asyncio.Event
    behind it, and the approval UI would show a phantom hold (PROJECT_PLAN.md
    S5's interception state machine assumes PENDING == a live hold)."""
    actions = generate_history(AGENTS, days=4, now=3_000_000.0, rng=random.Random(9))
    assert all(a.status != ActionStatus.PENDING for a in actions)


def _comparable(action):
    # action_id/trace_id/span_id are always-fresh uuid4s by design - everything
    # else should be bit-for-bit identical for the same seed.
    return (
        action.agent_id, action.tool, action.resource_name, action.risk_level,
        action.status, action.requested_at, action.resolved_at,
    )


def test_generate_history_is_reproducible_for_a_fixed_seed():
    first = generate_history(AGENTS, days=2, now=5_000_000.0, rng=random.Random(42))
    second = generate_history(AGENTS, days=2, now=5_000_000.0, rng=random.Random(42))
    assert [_comparable(a) for a in first] == [_comparable(a) for a in second]


def test_emit_backdated_spans_sets_explicit_past_timestamps():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test-history-seeder")

    now = time.time()
    actions = generate_history(AGENTS, days=2, now=now, rng=random.Random(5))
    emit_backdated_spans(tracer, actions)

    finished = exporter.get_finished_spans()
    assert len(finished) == len(actions)

    by_action_id = {a.action_id: a for a in actions}
    now_ns = int(now * 1_000_000_000)
    for span in finished:
        attrs = dict(span.attributes)
        action = by_action_id[attrs["atc.action_id"]]
        assert span.name == f"atc.gate.{action.tool}"
        assert attrs["agent.id"] == action.agent_id
        assert attrs["atc.risk.level"] == action.risk_level.value
        assert attrs["atc.decision"] == action.status.value
        # The whole point: these timestamps are in the past, not "now".
        assert span.start_time < now_ns
        assert span.end_time <= now_ns
        assert span.start_time <= span.end_time
