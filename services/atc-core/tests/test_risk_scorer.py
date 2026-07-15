"""Unit tests for the EWMA fleet risk score. See PROJECT_PLAN.md S6:
weights LOW=1 MEDIUM=5 HIGH=25 denied-HIGH=50, +20/novel resource, ~10-min
decay half-life."""

from __future__ import annotations

import pytest

from atc_core.risk.models import RiskLevel
from atc_core.risk.scorer import DECAY_HALF_LIFE_SECONDS, RiskScorer
from atc_core.store import Action, ActionStatus, Agent, Store


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


def _action(
    action_id: str,
    *,
    risk_level: RiskLevel,
    status: ActionStatus,
    requested_at: float,
    resolved_at: float | None,
) -> Action:
    return Action(
        action_id=action_id,
        trace_id="trace-1",
        span_id="span-1",
        agent_id="coder-01",
        tool="db__execute",
        resource_class="table",
        resource_name="customers",
        args_summary="DELETE FROM customers",
        risk_level=risk_level,
        risk_reason="test",
        rule_id="TEST-RULE",
        status=status,
        decided_by=None,
        requested_at=requested_at,
        resolved_at=resolved_at,
    )


async def test_no_actions_scores_zero(store: Store) -> None:
    scorer = RiskScorer(store)
    assert await scorer.compute_score("coder-01") == 0.0


async def test_low_medium_high_weights_at_zero_age(store: Store) -> None:
    now = 2000.0
    await store.insert_action(
        _action("a1", risk_level=RiskLevel.LOW, status=ActionStatus.AUTO_ALLOWED, requested_at=now, resolved_at=now)
    )
    await store.insert_action(
        _action("a2", risk_level=RiskLevel.MEDIUM, status=ActionStatus.AUTO_ALLOWED, requested_at=now, resolved_at=now)
    )
    await store.insert_action(
        _action("a3", risk_level=RiskLevel.HIGH, status=ActionStatus.APPROVED, requested_at=now, resolved_at=now)
    )
    scorer = RiskScorer(store)
    score = await scorer.compute_score("coder-01", now=now)
    assert score == pytest.approx(1.0 + 5.0 + 25.0)


async def test_denied_high_uses_heavier_weight(store: Store) -> None:
    now = 2000.0
    await store.insert_action(
        _action("a1", risk_level=RiskLevel.HIGH, status=ActionStatus.DENIED, requested_at=now, resolved_at=now)
    )
    scorer = RiskScorer(store)
    score = await scorer.compute_score("coder-01", now=now)
    assert score == pytest.approx(50.0)


async def test_pending_actions_do_not_contribute(store: Store) -> None:
    now = 2000.0
    await store.insert_action(
        _action("a1", risk_level=RiskLevel.HIGH, status=ActionStatus.PENDING, requested_at=now, resolved_at=None)
    )
    scorer = RiskScorer(store)
    assert await scorer.compute_score("coder-01", now=now) == 0.0


async def test_score_decays_by_half_at_one_half_life(store: Store) -> None:
    requested_at = 1000.0
    now = requested_at + DECAY_HALF_LIFE_SECONDS
    await store.insert_action(
        _action(
            "a1", risk_level=RiskLevel.HIGH, status=ActionStatus.APPROVED, requested_at=requested_at, resolved_at=requested_at
        )
    )
    scorer = RiskScorer(store)
    score = await scorer.compute_score("coder-01", now=now)
    assert score == pytest.approx(12.5, rel=1e-6)


async def test_other_agents_actions_are_excluded(store: Store) -> None:
    now = 2000.0
    await store.upsert_agent(
        Agent(
            id="assist-01",
            persona="assist",
            scope=["email", "fs"],
            owner="team",
            quarantined=False,
            last_heartbeat_ts=None,
            created_at=1000.0,
        )
    )
    other = _action("a1", risk_level=RiskLevel.HIGH, status=ActionStatus.APPROVED, requested_at=now, resolved_at=now)
    other = Action(**{**other.__dict__, "agent_id": "assist-01"})
    await store.insert_action(other)
    scorer = RiskScorer(store)
    assert await scorer.compute_score("coder-01", now=now) == 0.0
