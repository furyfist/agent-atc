"""Row models for the four SQLite tables. See PROJECT_PLAN.md S9."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from atc_core.risk.models import RiskLevel


class ActionStatus(str, Enum):
    """Persisted status of an action row. This is coarser than the full
    span-event lifecycle in S5 (RECEIVED -> SCOPE_CHECK -> RISK_ASSESSED ->
    ...) - that fine-grained sequence is emitted as OTel span events by the
    gateway. SQLite only needs to answer "is this pending, and how did it
    resolve", which is what the REST API and UI query against."""

    PENDING = "PENDING"  # HELD, awaiting a human decision (or timeout)
    AUTO_ALLOWED = "AUTO_ALLOWED"  # never held - LOW/MEDIUM risk
    APPROVED = "APPROVED"  # HELD, human approved
    DENIED = "DENIED"  # HELD, human denied
    EXPIRED = "EXPIRED"  # HELD, 120s timeout elapsed with no decision


@dataclass(frozen=True)
class Agent:
    id: str
    persona: str
    scope: list[str]
    owner: str | None
    quarantined: bool
    last_heartbeat_ts: float | None
    created_at: float
    tokens_used: float = 0.0  # cumulative LLM tokens, reported via heartbeat


@dataclass(frozen=True)
class Action:
    action_id: str
    trace_id: str
    span_id: str | None
    agent_id: str
    tool: str
    resource_class: str | None
    resource_name: str | None
    args_summary: str | None
    risk_level: RiskLevel
    risk_reason: str | None
    rule_id: str
    status: ActionStatus
    decided_by: str | None
    requested_at: float
    resolved_at: float | None
    # Consequence signals (defaults keep pre-existing constructor calls valid).
    reversibility: str | None = None  # Reversibility enum value at decision time
    blast_radius: str | None = None  # human-readable pre-approval impact estimate
    novel: bool = False  # set by the creep detector after the fact


@dataclass(frozen=True)
class JournalEntry:
    """Pre-image captured by the gateway before executing a COMPENSABLE
    mutation - the recovery data an undo is synthesized from. kind is 'fs'
    (path + prior content, None = file was absent), 'db_rows' (rows a
    bounded/unbounded UPDATE/DELETE would touch), or 'db_table' (full table
    snapshot ahead of a DROP)."""

    action_id: str
    kind: str
    payload: dict
    created_at: float
    undone_at: float | None = None
    undo_action_id: str | None = None
