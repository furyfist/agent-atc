"""REST response/request shapes. See PROJECT_PLAN.md S8."""

from __future__ import annotations

from pydantic import BaseModel


class AgentOut(BaseModel):
    id: str
    persona: str
    scope: list[str]
    owner: str | None
    quarantined: bool
    last_heartbeat_ts: float | None
    created_at: float


class ActionOut(BaseModel):
    action_id: str
    trace_id: str
    span_id: str | None
    agent_id: str
    tool: str
    resource_class: str | None
    resource_name: str | None
    args_summary: str | None
    risk_level: str
    risk_reason: str | None
    rule_id: str
    status: str
    decided_by: str | None
    requested_at: float
    resolved_at: float | None


class DecideRequest(BaseModel):
    decided_by: str


class QuarantineRequest(BaseModel):
    # Defaults to True so a bare POST with no body is the classic kill-switch
    # trip; False is accepted too so an operator can lift it without a full
    # `make reset-demo` (S9's reset-demo remains the between-takes reset).
    quarantined: bool = True
