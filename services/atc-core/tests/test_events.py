"""Unit tests for EventBus and its wiring into ApprovalManager (S8)."""

from __future__ import annotations

import pytest

from atc_core.approval import ApprovalManager
from atc_core.events import EventBus
from atc_core.risk.models import RiskDecision, RiskLevel
from atc_core.store import Agent, Store

FAST_HOLD_TIMEOUT = 0.15


@pytest.fixture
async def store():
    s = await Store.connect(":memory:")
    await s.upsert_agent(
        Agent(
            id="coder-01",
            persona="coder",
            scope=["db"],
            owner=None,
            quarantined=False,
            last_heartbeat_ts=None,
            created_at=1000.0,
        )
    )
    yield s
    await s.close()


def _risk(level: RiskLevel) -> RiskDecision:
    return RiskDecision(risk_level=level, reason="test", rule_id="TEST-RULE")


# --- EventBus in isolation ---------------------------------------------------


async def test_subscriber_receives_published_event() -> None:
    bus = EventBus()
    queue = bus.subscribe()
    await bus.publish("action.pending", {"action_id": "a1"})
    event = queue.get_nowait()
    assert event.type == "action.pending"
    assert event.payload == {"action_id": "a1"}


async def test_multiple_subscribers_all_receive() -> None:
    bus = EventBus()
    q1, q2 = bus.subscribe(), bus.subscribe()
    await bus.publish("action.resolved", {"action_id": "a1"})
    assert q1.get_nowait().type == "action.resolved"
    assert q2.get_nowait().type == "action.resolved"


async def test_unsubscribe_stops_delivery() -> None:
    bus = EventBus()
    queue = bus.subscribe()
    bus.unsubscribe(queue)
    await bus.publish("action.pending", {"action_id": "a1"})
    assert queue.empty()


async def test_publish_with_no_subscribers_does_not_raise() -> None:
    bus = EventBus()
    await bus.publish("action.pending", {"action_id": "a1"})  # just must not raise


# --- wired into ApprovalManager ---------------------------------------------


async def test_held_submit_publishes_action_pending(store: Store) -> None:
    bus = EventBus()
    queue = bus.subscribe()
    manager = ApprovalManager(store, hold_timeout_seconds=FAST_HOLD_TIMEOUT, event_bus=bus)

    await manager.submit(
        action_id="a1",
        trace_id="t1",
        span_id=None,
        agent_id="coder-01",
        tool="db__execute",
        resource_class="db",
        resource_name=None,
        args_summary=None,
        risk=_risk(RiskLevel.HIGH),
    )

    event = queue.get_nowait()
    assert event.type == "action.pending"
    assert event.payload["action_id"] == "a1"
    assert event.payload["status"] == "PENDING"


async def test_auto_allowed_submit_does_not_publish(store: Store) -> None:
    bus = EventBus()
    queue = bus.subscribe()
    manager = ApprovalManager(store, hold_timeout_seconds=FAST_HOLD_TIMEOUT, event_bus=bus)

    await manager.submit(
        action_id="a1",
        trace_id="t1",
        span_id=None,
        agent_id="coder-01",
        tool="db__query",
        resource_class="db",
        resource_name=None,
        args_summary=None,
        risk=_risk(RiskLevel.LOW),
    )

    assert queue.empty()


async def test_decide_publishes_action_resolved(store: Store) -> None:
    bus = EventBus()
    manager = ApprovalManager(store, hold_timeout_seconds=FAST_HOLD_TIMEOUT, event_bus=bus)
    await manager.submit(
        action_id="a1",
        trace_id="t1",
        span_id=None,
        agent_id="coder-01",
        tool="db__execute",
        resource_class="db",
        resource_name=None,
        args_summary=None,
        risk=_risk(RiskLevel.HIGH),
    )
    queue = bus.subscribe()  # subscribe after the pending event so we isolate the resolved one

    await manager.decide("a1", approved=True, decided_by="alice")

    event = queue.get_nowait()
    assert event.type == "action.resolved"
    assert event.payload["status"] == "APPROVED"
    assert event.payload["decided_by"] == "alice"


async def test_timeout_expiry_publishes_action_resolved(store: Store) -> None:
    bus = EventBus()
    manager = ApprovalManager(store, hold_timeout_seconds=FAST_HOLD_TIMEOUT, event_bus=bus)
    await manager.submit(
        action_id="a1",
        trace_id="t1",
        span_id=None,
        agent_id="coder-01",
        tool="db__execute",
        resource_class="db",
        resource_name=None,
        args_summary=None,
        risk=_risk(RiskLevel.HIGH),
    )
    queue = bus.subscribe()

    resolved = await manager.wait_for_decision("a1")

    assert resolved.status.value == "EXPIRED"
    event = queue.get_nowait()
    assert event.type == "action.resolved"
    assert event.payload["status"] == "EXPIRED"


async def test_resume_stale_holds_publishes_action_resolved(store: Store) -> None:
    orphan_manager = ApprovalManager(store, hold_timeout_seconds=999)
    await orphan_manager.submit(
        action_id="orphan-1",
        trace_id="t1",
        span_id=None,
        agent_id="coder-01",
        tool="db__execute",
        resource_class="db",
        resource_name=None,
        args_summary=None,
        risk=_risk(RiskLevel.HIGH),
    )

    bus = EventBus()
    queue = bus.subscribe()
    fresh_manager = ApprovalManager(store, hold_timeout_seconds=999, event_bus=bus)
    await fresh_manager.resume_stale_holds()

    event = queue.get_nowait()
    assert event.type == "action.resolved"
    assert event.payload["action_id"] == "orphan-1"
    assert event.payload["status"] == "EXPIRED"


async def test_manager_without_event_bus_works_unaffected(store: Store) -> None:
    """No event_bus passed - must behave exactly as before (default None)."""
    manager = ApprovalManager(store, hold_timeout_seconds=FAST_HOLD_TIMEOUT)
    action = await manager.submit(
        action_id="a1",
        trace_id="t1",
        span_id=None,
        agent_id="coder-01",
        tool="db__query",
        resource_class="db",
        resource_name=None,
        args_summary=None,
        risk=_risk(RiskLevel.LOW),
    )
    assert action.status.value == "AUTO_ALLOWED"
