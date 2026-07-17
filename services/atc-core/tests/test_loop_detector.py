"""Loop-suspicion detection - repeated near-identical calls in a window."""

from __future__ import annotations

import asyncio
import time

import pytest

from atc_core.gateway.loops import LoopDetector
from atc_core.risk.models import RiskLevel
from atc_core.store import Action, ActionStatus, Agent, Store
from atc_telemetry import configure_tracing


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


def _action(action_id: str, *, requested_at: float, args_summary: str = '{"sql": "SELECT 1"}') -> Action:
    return Action(
        action_id=action_id, trace_id="t", span_id=None, agent_id="coder-01",
        tool="db__query", resource_class="db", resource_name="staging_old",
        args_summary=args_summary, risk_level=RiskLevel.LOW, risk_reason="r",
        rule_id="R", status=ActionStatus.AUTO_ALLOWED, decided_by=None,
        requested_at=requested_at, resolved_at=requested_at,
    )


def _detector(store: Store) -> LoopDetector:
    return LoopDetector(store, tracer=configure_tracing("test-loops"), instruments=None)


async def _drain(detector: LoopDetector, timeout: float = 2.0) -> None:
    pending = list(detector._background_tasks)  # noqa: SLF001
    if pending:
        await asyncio.wait(pending, timeout=timeout)


async def test_repeats_inside_window_are_counted(store: Store) -> None:
    now = time.time()
    for i in range(4):
        await store.insert_action(_action(f"a{i}", requested_at=now - 10 * i))
    detector = _detector(store)
    repeats = await detector._count_recent_repeats(  # noqa: SLF001
        agent_id="coder-01", tool="db__query", args_summary='{"sql": "SELECT 1"}', action_id="a0"
    )
    assert repeats == 3  # the other three; the current action is excluded


async def test_old_calls_fall_out_of_the_window(store: Store) -> None:
    now = time.time()
    await store.insert_action(_action("recent", requested_at=now - 5))
    await store.insert_action(_action("stale", requested_at=now - 3600))
    detector = _detector(store)
    repeats = await detector._count_recent_repeats(  # noqa: SLF001
        agent_id="coder-01", tool="db__query", args_summary='{"sql": "SELECT 1"}', action_id="current"
    )
    assert repeats == 1


async def test_different_arguments_are_not_a_loop(store: Store) -> None:
    now = time.time()
    for i in range(5):
        await store.insert_action(
            _action(f"a{i}", requested_at=now - i, args_summary=f'{{"sql": "SELECT {i}"}}')
        )
    detector = _detector(store)
    repeats = await detector._count_recent_repeats(  # noqa: SLF001
        agent_id="coder-01", tool="db__query", args_summary='{"sql": "SELECT 1"}', action_id="x"
    )
    assert repeats == 1  # only the exact-match row counts


async def test_check_async_never_raises_even_on_store_failure(store: Store) -> None:
    detector = _detector(store)

    async def broken_list_actions(*args, **kwargs):
        raise RuntimeError("store is down")

    detector._store = type("BrokenStore", (), {"list_actions": staticmethod(broken_list_actions)})()  # noqa: SLF001
    detector.check_async(agent_id="coder-01", tool="db__query", args_summary="{}", action_id="a1")
    await _drain(detector)  # must complete without the exception surfacing anywhere


async def test_scheduled_task_is_strongly_referenced_until_done(store: Store) -> None:
    detector = _detector(store)
    detector.check_async(agent_id="coder-01", tool="db__query", args_summary="{}", action_id="a1")
    assert detector._background_tasks  # noqa: SLF001 - held, not GC-bait
    await _drain(detector)
    assert not detector._background_tasks  # noqa: SLF001 - and released after
