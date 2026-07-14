"""Unit tests for the interception state machine (PROJECT_PLAN.md S5)."""

from __future__ import annotations

import asyncio

import pytest

from atc_core.approval import ApprovalManager
from atc_core.risk.models import RiskDecision, RiskLevel
from atc_core.store import ActionStatus, Agent, Store

# Tiny hold timeout so EXPIRED-path tests don't take the real 120s.
FAST_HOLD_TIMEOUT = 0.15


@pytest.fixture
async def store():
    s = await Store.connect(":memory:")
    await s.upsert_agent(
        Agent(
            id="coder-01",
            persona="coder",
            scope=["db", "fs", "git"],
            owner="team",
            quarantined=False,
            last_heartbeat_ts=None,
            created_at=1000.0,
        )
    )
    yield s
    await s.close()


@pytest.fixture
def manager(store: Store) -> ApprovalManager:
    return ApprovalManager(store, hold_timeout_seconds=FAST_HOLD_TIMEOUT)


def _risk(level: RiskLevel, rule_id: str = "SOME-RULE") -> RiskDecision:
    return RiskDecision(risk_level=level, reason="test reason", rule_id=rule_id)


async def _submit(manager: ApprovalManager, action_id: str, risk: RiskDecision):
    return await manager.submit(
        action_id=action_id,
        trace_id="trace-1",
        span_id="span-1",
        agent_id="coder-01",
        tool="db__execute",
        resource_class="table",
        resource_name="customers",
        args_summary="DELETE FROM customers",
        risk=risk,
    )


# --- AUTO_ALLOW path -----------------------------------------------------


async def test_low_risk_is_auto_allowed(manager: ApprovalManager) -> None:
    action = await _submit(manager, "a1", _risk(RiskLevel.LOW))
    assert action.status == ActionStatus.AUTO_ALLOWED
    assert action.resolved_at is not None


async def test_medium_risk_is_auto_allowed_by_default(manager: ApprovalManager) -> None:
    action = await _submit(manager, "a1", _risk(RiskLevel.MEDIUM))
    assert action.status == ActionStatus.AUTO_ALLOWED


async def test_wait_for_decision_on_auto_allowed_returns_immediately(manager: ApprovalManager) -> None:
    await _submit(manager, "a1", _risk(RiskLevel.LOW))
    action = await manager.wait_for_decision("a1")
    assert action.status == ActionStatus.AUTO_ALLOWED


async def test_held_risk_levels_are_configurable(store: Store) -> None:
    manager = ApprovalManager(
        store, hold_timeout_seconds=FAST_HOLD_TIMEOUT, held_risk_levels=frozenset({RiskLevel.MEDIUM})
    )
    action = await _submit(manager, "a1", _risk(RiskLevel.MEDIUM))
    assert action.status == ActionStatus.PENDING  # MEDIUM is held under this config


# --- HELD path -------------------------------------------------------------


async def test_high_risk_is_pending(manager: ApprovalManager) -> None:
    action = await _submit(manager, "a1", _risk(RiskLevel.HIGH))
    assert action.status == ActionStatus.PENDING
    assert action.resolved_at is None


async def test_held_action_approved_resolves_wait_for_decision(manager: ApprovalManager) -> None:
    await _submit(manager, "a1", _risk(RiskLevel.HIGH))
    wait_task = asyncio.create_task(manager.wait_for_decision("a1"))
    await asyncio.sleep(0.02)  # let the wait actually start blocking
    decided = await manager.decide("a1", approved=True, decided_by="alice")
    assert decided.status == ActionStatus.APPROVED

    resolved = await wait_task
    assert resolved.status == ActionStatus.APPROVED
    assert resolved.decided_by == "alice"


async def test_held_action_denied_resolves_wait_for_decision(manager: ApprovalManager) -> None:
    await _submit(manager, "a1", _risk(RiskLevel.HIGH))
    wait_task = asyncio.create_task(manager.wait_for_decision("a1"))
    await asyncio.sleep(0.02)
    await manager.decide("a1", approved=False, decided_by="bob")

    resolved = await wait_task
    assert resolved.status == ActionStatus.DENIED
    assert resolved.decided_by == "bob"


async def test_held_action_expires_after_timeout_with_no_decision(manager: ApprovalManager) -> None:
    await _submit(manager, "a1", _risk(RiskLevel.HIGH))
    resolved = await manager.wait_for_decision("a1")
    assert resolved.status == ActionStatus.EXPIRED
    assert resolved.decided_by is None


async def test_expired_action_is_not_overwritten_by_a_late_decision(manager: ApprovalManager) -> None:
    """Simulates a human clicking approve a moment after the 120s hold
    already expired: the response must honestly reflect EXPIRED, not lie
    that it was approved."""
    await _submit(manager, "a1", _risk(RiskLevel.HIGH))
    expired = await manager.wait_for_decision("a1")
    assert expired.status == ActionStatus.EXPIRED

    late_decision = await manager.decide("a1", approved=True, decided_by="alice")
    assert late_decision.status == ActionStatus.EXPIRED  # not clobbered to APPROVED


async def test_pending_event_is_cleaned_up_after_resolution(manager: ApprovalManager) -> None:
    await _submit(manager, "a1", _risk(RiskLevel.HIGH))
    await manager.decide("a1", approved=True, decided_by="alice")
    assert "a1" not in manager._pending_events  # noqa: SLF001 - internal state check


# --- crash-safety: resume_stale_holds ---------------------------------------


async def test_resume_stale_holds_expires_orphaned_pending_rows(store: Store) -> None:
    """Simulates a restart: a PENDING row exists with no in-memory Event
    (the process that created it is gone) - it must be expired."""
    first_manager = ApprovalManager(store, hold_timeout_seconds=999)
    await _submit(first_manager, "orphan-1", _risk(RiskLevel.HIGH))
    # first_manager is discarded here without resolving - simulates a crash.

    fresh_manager = ApprovalManager(store, hold_timeout_seconds=999)
    expired = await fresh_manager.resume_stale_holds()

    assert [a.action_id for a in expired] == ["orphan-1"]
    assert expired[0].status == ActionStatus.EXPIRED

    fetched = await store.get_action("orphan-1")
    assert fetched is not None
    assert fetched.status == ActionStatus.EXPIRED


async def test_resume_stale_holds_is_a_noop_when_nothing_pending(manager: ApprovalManager) -> None:
    await _submit(manager, "a1", _risk(RiskLevel.LOW))  # AUTO_ALLOWED, not PENDING
    expired = await manager.resume_stale_holds()
    assert expired == []


# --- error handling ----------------------------------------------------------


async def test_decide_on_unknown_action_raises(manager: ApprovalManager) -> None:
    with pytest.raises(ValueError, match="unknown action_id"):
        await manager.decide("nope", approved=True, decided_by="alice")


async def test_wait_for_decision_on_unknown_action_raises(manager: ApprovalManager) -> None:
    with pytest.raises(ValueError, match="unknown action_id"):
        await manager.wait_for_decision("nope")
