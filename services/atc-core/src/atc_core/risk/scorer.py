"""EWMA fleet risk score. See PROJECT_PLAN.md S6:

    weights LOW=1 MEDIUM=5 HIGH=25 denied-HIGH=50, +20 per novel resource,
    ~10-min decay half-life, recomputed on the heartbeat cadence (not
    continuously) - decay applies at recompute time, deterministic and cheap.

Reads straight from the actions table rather than keeping running state in
memory - the SQLite rows are already the durable source of truth (S9), and
recomputing from them means a restarted atc-core process picks the score
back up correctly instead of resetting every agent to zero.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from atc_core.risk.models import RiskLevel
from atc_core.store import ActionStatus, Store

DECAY_HALF_LIFE_SECONDS = 10 * 60

_BASE_WEIGHTS: dict[RiskLevel, float] = {
    RiskLevel.LOW: 1.0,
    RiskLevel.MEDIUM: 5.0,
    RiskLevel.HIGH: 25.0,
}
DENIED_HIGH_WEIGHT = 50.0
NOVEL_RESOURCE_WEIGHT = 20.0


def _event_weight(risk_level: RiskLevel, status: ActionStatus) -> float:
    if risk_level == RiskLevel.HIGH and status == ActionStatus.DENIED:
        return DENIED_HIGH_WEIGHT
    return _BASE_WEIGHTS[risk_level]


def _decay_factor(age_seconds: float) -> float:
    if age_seconds <= 0:
        return 1.0
    return math.pow(0.5, age_seconds / DECAY_HALF_LIFE_SECONDS)


@dataclass(frozen=True)
class RiskScorer:
    store: Store

    async def compute_score(self, agent_id: str, *, now: float | None = None) -> float:
        """EWMA over this agent's resolved actions: each action contributes
        its base weight decayed by age-at-recompute. Actions still PENDING
        don't contribute yet (no terminal outcome to score)."""
        now = now if now is not None else time.time()
        actions = await self.store.list_actions()
        score = 0.0
        for action in actions:
            if action.agent_id != agent_id or action.status == ActionStatus.PENDING:
                continue
            age = now - (action.resolved_at or action.requested_at)
            score += _event_weight(action.risk_level, action.status) * _decay_factor(age)
        return score
