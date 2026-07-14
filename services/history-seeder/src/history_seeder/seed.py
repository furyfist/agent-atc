"""Generates plausible historical Action rows + backdated OTel spans so
dashboards and permission-creep queries have a baseline before the first
live demo run. See PROJECT_PLAN.md S4 (history-seeder), S6 (creep baseline).

Two outputs from one generated action list:
  - SQLite `actions` rows (always backdated - the "creep baseline + lived-in
    dashboards" story only needs believable `requested_at` timestamps, no
    SigNoz dependency).
  - One `atc.gate.{tool}` span per action, attributed like the real
    gateway's gate span but NOT the full agent.mission/atc.execution nested
    tree - there's no real mission behind a seeded row. Just enough for
    dashboard aggregations and creep queries (agent.id + atc.resource.name
    co-occurrence) to see a believable history. Backdating spans via
    explicit start_time/end_time is exactly what spike S2 exists to
    validate against a live SigNoz (PROJECT_PLAN.md S12) - if S2 finds
    backdating doesn't survive ingestion/retention, fall back to the
    plan's own documented fallback: run this seeder for real over 2-3 days
    pre-recording (ATC_HISTORY_BACKDATE_SPANS=false, invoked on a cron/loop
    instead of once).
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from atc_core.gateway import AgentIdentity
from atc_core.risk.models import RiskLevel
from atc_core.store import Action, ActionStatus
from atc_telemetry.attributes import (
    AGENT_ID,
    ATC_ACTION_ID,
    ATC_DECISION,
    ATC_DECISION_BY,
    ATC_RESOURCE_CLASS,
    ATC_RESOURCE_NAME,
    ATC_RISK_LEVEL,
    ATC_RISK_REASONS,
    SPAN_ATC_GATE_PREFIX,
)

SECONDS_PER_DAY = 86_400
DECIDED_BY_OPERATOR = "operator"
ACTIONS_PER_AGENT_PER_DAY = 8


@dataclass(frozen=True)
class ToolProfile:
    """One kind of historical action a persona plausibly performs, and its
    weight relative to the persona's other profiles."""

    tool: str
    resource_class: str
    resource_names: tuple[str, ...]
    risk_level: RiskLevel
    rule_id: str
    reason: str
    weight: int


# Mirrors policies/risk_rules.yaml's ordered rules and the resource names
# actually seeded by services/tools-db/src/tools_db/seed.py, so a seeded
# history references the same tables/paths the live demo touches.
PERSONA_PROFILES: dict[str, tuple[ToolProfile, ...]] = {
    "coder": (
        ToolProfile(
            "db__query", "db", ("staging_old", "orders", "customers"), RiskLevel.LOW, "SQL-READ-LOW",
            "Read-only query", 6,
        ),
        ToolProfile(
            "db__execute", "db", ("staging_old",), RiskLevel.MEDIUM, "SQL-WRITE-MEDIUM",
            "Bounded write statement on a non-production table", 2,
        ),
        ToolProfile(
            "db__execute", "db", ("customers",), RiskLevel.HIGH, "SQL-PROD-TABLE-HIGH",
            "Statement touches a table tagged as production", 1,
        ),
        ToolProfile(
            "fs__read", "fs", ("README.md", "services/tools-db/src/tools_db/seed.py"), RiskLevel.LOW,
            "FS-READ-LOW", "File read", 3,
        ),
        ToolProfile("git__push", "git", ("origin/main",), RiskLevel.MEDIUM, "GIT-PUSH-MEDIUM", "Push to remote", 2),
    ),
    "assistant": (
        ToolProfile(
            "email__send", "email", ("team-standup@example.com", "daily-digest@example.com"), RiskLevel.LOW,
            "EMAIL-SEND-LOW", "Email send", 5,
        ),
        ToolProfile("fs__read", "fs", ("notes/daily-summary.md",), RiskLevel.LOW, "FS-READ-LOW", "File read", 3),
        ToolProfile(
            "fs__write", "fs", ("notes/daily-summary.md",), RiskLevel.MEDIUM, "FS-WRITE-MEDIUM", "File write", 2,
        ),
    ),
    "compliance": (
        ToolProfile(
            "fs__read", "fs", ("policies/risk_rules.yaml", "policies/agents.yaml"), RiskLevel.LOW,
            "FS-READ-LOW", "File read", 6,
        ),
    ),
}


def generate_history(
    agents: list[AgentIdentity], *, days: int, now: float, rng: random.Random
) -> list[Action]:
    """Pure function: no I/O, no OTel - trivially unit testable. Spreads
    ~ACTIONS_PER_AGENT_PER_DAY actions per agent uniformly over the window,
    always at least an hour before `now` so the live demo's first real
    action is unambiguously the newest thing in the trace list."""
    actions: list[Action] = []
    window_start = now - days * SECONDS_PER_DAY
    window_end = now - 3600

    for agent in agents:
        profiles = PERSONA_PROFILES.get(agent.persona, ())
        if not profiles:
            continue
        weights = [p.weight for p in profiles]
        count = max(1, days * ACTIONS_PER_AGENT_PER_DAY)

        for _ in range(count):
            profile = rng.choices(profiles, weights=weights, k=1)[0]
            requested_at = rng.uniform(window_start, window_end)
            resource_name = rng.choice(profile.resource_names)
            status, decided_by, resolved_at = _resolve_outcome(profile.risk_level, requested_at, rng)

            actions.append(
                Action(
                    action_id=str(uuid.uuid4()),
                    trace_id=uuid.uuid4().hex,
                    span_id=uuid.uuid4().hex[:16],
                    agent_id=agent.id,
                    tool=profile.tool,
                    resource_class=profile.resource_class,
                    resource_name=resource_name,
                    args_summary=f'{{"seeded": true, "resource": "{resource_name}"}}',
                    risk_level=profile.risk_level,
                    risk_reason=profile.reason,
                    rule_id=profile.rule_id,
                    status=status,
                    decided_by=decided_by,
                    requested_at=requested_at,
                    resolved_at=resolved_at,
                )
            )

    actions.sort(key=lambda a: a.requested_at)
    return actions


def _resolve_outcome(
    risk_level: RiskLevel, requested_at: float, rng: random.Random
) -> tuple[ActionStatus, str | None, float | None]:
    if risk_level in (RiskLevel.LOW, RiskLevel.MEDIUM):
        return ActionStatus.AUTO_ALLOWED, None, requested_at

    # HIGH: held, then mostly approved - a lived-in fleet is mostly-trusted;
    # occasional denials/expiries keep the history honest, not all-green.
    roll = rng.random()
    if roll < 0.7:
        return ActionStatus.APPROVED, DECIDED_BY_OPERATOR, requested_at + rng.uniform(5, 40)
    if roll < 0.9:
        return ActionStatus.DENIED, DECIDED_BY_OPERATOR, requested_at + rng.uniform(5, 40)
    return ActionStatus.EXPIRED, None, requested_at + 120


def emit_backdated_spans(tracer: trace.Tracer, actions: list[Action]) -> None:
    """UNVALIDATED against a live SigNoz ingest/retention window - see the
    module docstring and spike S2 (PROJECT_PLAN.md S12). The explicit
    start_time/end_time mechanism itself (epoch nanoseconds) is confirmed
    against the installed opentelemetry-sdk via InMemorySpanExporter in
    tests/test_seed.py; what's unverified is whether SigNoz's ingest path
    accepts/displays spans timestamped in the past."""
    for action in actions:
        start_ns = int(action.requested_at * 1_000_000_000)
        end_ns = int((action.resolved_at or action.requested_at) * 1_000_000_000)
        span = tracer.start_span(f"{SPAN_ATC_GATE_PREFIX}.{action.tool}", start_time=start_ns)
        span.set_attribute(AGENT_ID, action.agent_id)
        span.set_attribute(ATC_ACTION_ID, action.action_id)
        span.set_attribute(ATC_RESOURCE_CLASS, action.resource_class or "")
        span.set_attribute(ATC_RESOURCE_NAME, action.resource_name or "")
        span.set_attribute(ATC_RISK_LEVEL, action.risk_level.value)
        span.set_attribute(ATC_RISK_REASONS, action.risk_reason or "")
        span.set_attribute(ATC_DECISION, action.status.value)
        if action.decided_by:
            span.set_attribute(ATC_DECISION_BY, action.decided_by)
        span.set_status(Status(StatusCode.OK))
        span.end(end_time=end_ns)
