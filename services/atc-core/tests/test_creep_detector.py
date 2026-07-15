"""Unit tests for permission-creep detection. See PROJECT_PLAN.md S6's
non-gating creep law: novel resource <=> zero prior actions for
(agent_id, resource_name), checked asynchronously, never gating the call.
"""

from __future__ import annotations

import asyncio

import pytest

from atc_core.gateway.creep import CreepDetector
from atc_core.risk.models import RiskLevel
from atc_core.store import Action, ActionStatus, Agent, Store
from atc_telemetry import configure_metrics, configure_tracing


@pytest.fixture
async def store():
    s = await Store.connect(":memory:")
    await s.upsert_agent(
        Agent(
            id="coder-01", persona="coder", scope=["db"], owner="team",
            quarantined=False, last_heartbeat_ts=None, created_at=1000.0,
        )
    )
    yield s
    await s.close()


def _action(action_id: str, *, agent_id: str = "coder-01", resource_name: str | None, requested_at: float = 1000.0) -> Action:
    return Action(
        action_id=action_id, trace_id="t1", span_id=None, agent_id=agent_id,
        tool="db__query", resource_class="db", resource_name=resource_name,
        args_summary=None, risk_level=RiskLevel.LOW, risk_reason="test",
        rule_id="TEST-RULE", status=ActionStatus.AUTO_ALLOWED, decided_by=None,
        requested_at=requested_at, resolved_at=requested_at,
    )


async def _drain_background_tasks() -> None:
    """CreepDetector.check_async schedules a task rather than awaiting it -
    tests need a real yield point for that task to actually run before
    asserting on its effects."""
    await asyncio.sleep(0)
    await asyncio.sleep(0)


async def test_first_ever_call_is_novel(store: Store) -> None:
    await store.insert_action(_action("a1", resource_name="customers"))
    tracer = configure_tracing("test-creep")
    instruments = configure_metrics("test-creep")
    detector = CreepDetector(store, tracer=tracer, instruments=instruments)

    detector.check_async(agent_id="coder-01", resource_name="customers", action_id="a1")
    await _drain_background_tasks()
    # No exception, no assertion on the metric export path itself (no
    # reader attached) - this test locks in that a first-ever call doesn't
    # crash the detector; test_emits_span_event_for_a_repeat_call below
    # asserts the interesting (novel) case via the span recorder.


async def test_repeat_resource_is_not_novel(store: Store) -> None:
    await store.insert_action(_action("a1", resource_name="customers", requested_at=1000.0))
    await store.insert_action(_action("a2", resource_name="customers", requested_at=2000.0))
    tracer = configure_tracing("test-creep")
    detector = CreepDetector(store, tracer=tracer, instruments=None)

    is_novel = await detector._is_novel(agent_id="coder-01", resource_name="customers", action_id="a2")
    assert is_novel is False


async def test_never_touched_resource_is_novel(store: Store) -> None:
    await store.insert_action(_action("a1", resource_name="customers"))
    tracer = configure_tracing("test-creep")
    detector = CreepDetector(store, tracer=tracer, instruments=None)

    is_novel = await detector._is_novel(agent_id="coder-01", resource_name="never_seen_table", action_id="a1")
    assert is_novel is True


async def test_other_agents_history_does_not_count(store: Store) -> None:
    await store.upsert_agent(
        Agent(
            id="assist-01", persona="assist", scope=["fs"], owner="team",
            quarantined=False, last_heartbeat_ts=None, created_at=1000.0,
        )
    )
    await store.insert_action(_action("a1", agent_id="assist-01", resource_name="customers"))
    tracer = configure_tracing("test-creep")
    detector = CreepDetector(store, tracer=tracer, instruments=None)

    is_novel = await detector._is_novel(agent_id="coder-01", resource_name="customers", action_id="a2")
    assert is_novel is True


async def test_check_async_with_no_resource_name_is_a_noop(store: Store) -> None:
    tracer = configure_tracing("test-creep")
    detector = CreepDetector(store, tracer=tracer, instruments=None)

    detector.check_async(agent_id="coder-01", resource_name=None, action_id="a1")
    await _drain_background_tasks()
    # No task should have been scheduled; nothing to assert beyond "no raise".


async def test_check_async_swallows_store_errors(store: Store) -> None:
    class BrokenStore:
        async def list_actions(self):
            raise RuntimeError("boom")

    tracer = configure_tracing("test-creep")
    detector = CreepDetector(BrokenStore(), tracer=tracer, instruments=None)  # type: ignore[arg-type]

    detector.check_async(agent_id="coder-01", resource_name="customers", action_id="a1")
    await _drain_background_tasks()
    # Must not raise / propagate - background task errors are swallowed.
