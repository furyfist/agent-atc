"""Data shapes for the risk engine. See PROJECT_PLAN.md S7."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass(frozen=True)
class RiskDecision:
    """The engine's verdict for one tool call. Maps directly onto the
    atc.risk.level / atc.risk.reasons / policy.rule_id span attributes."""

    risk_level: RiskLevel
    reason: str
    rule_id: str


@dataclass(frozen=True)
class RiskRule:
    """One entry from policies/risk_rules.yaml. All specified matchers must
    hold (AND); values within a matcher (e.g. tool names, ddl_kind) are OR."""

    id: str
    risk_level: RiskLevel
    reason: str
    tools: list[str] | None = None
    arg_regex: dict[str, str] | None = None
    sql: dict | None = None
    recipient_count: dict | None = None
