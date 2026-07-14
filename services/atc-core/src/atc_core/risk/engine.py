"""Deterministic risk engine. Ordered YAML rules, first match wins, no LLM
ever runs in this path. See PROJECT_PLAN.md S7.

Two fail-closed behaviors are enforced here in code, not via YAML, so they
can't be silently disabled by editing the policy file:
  - unparseable SQL          -> HIGH  (SQL-PARSE-ERROR-FAIL-CLOSED)
  - no rule matches the call -> MEDIUM (UNMATCHED-FAIL-CLOSED)
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from atc_core.risk.models import RiskDecision, RiskLevel, RiskRule
from atc_core.risk.sql_facts import ParseError, SqlFacts, extract_sql_facts

SQL_PARSE_ERROR_RULE_ID = "SQL-PARSE-ERROR-FAIL-CLOSED"
UNMATCHED_RULE_ID = "UNMATCHED-FAIL-CLOSED"


class RiskEngine:
    def __init__(self, rules: list[RiskRule], prod_tables: set[str]) -> None:
        self._rules = rules
        self._prod_tables = prod_tables

    @classmethod
    def from_yaml(cls, path: str | Path) -> RiskEngine:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        prod_tables = set(data.get("prod_tables") or [])
        rules = [_rule_from_dict(entry) for entry in data["rules"]]
        return cls(rules, prod_tables)

    def evaluate(self, tool: str, arguments: dict) -> RiskDecision:
        sql_facts: SqlFacts | None = None
        sql_text = arguments.get("sql")
        if isinstance(sql_text, str) and sql_text.strip():
            try:
                sql_facts = extract_sql_facts(sql_text, self._prod_tables)
            except ParseError:
                return RiskDecision(
                    risk_level=RiskLevel.HIGH,
                    reason="Unparseable SQL statement - failing closed",
                    rule_id=SQL_PARSE_ERROR_RULE_ID,
                )

        for rule in self._rules:
            if _matches(rule, tool, arguments, sql_facts):
                return RiskDecision(risk_level=rule.risk_level, reason=rule.reason, rule_id=rule.id)

        return RiskDecision(
            risk_level=RiskLevel.MEDIUM,
            reason="No policy rule matched this tool call - failing closed to MEDIUM",
            rule_id=UNMATCHED_RULE_ID,
        )


def _rule_from_dict(d: dict) -> RiskRule:
    return RiskRule(
        id=d["id"],
        risk_level=RiskLevel(d["risk_level"]),
        reason=d["reason"],
        tools=d.get("tool"),
        arg_regex=d.get("arg_regex"),
        sql=d.get("sql"),
        recipient_count=d.get("recipient_count"),
    )


def _matches(rule: RiskRule, tool: str, arguments: dict, sql_facts: SqlFacts | None) -> bool:
    if rule.tools is not None and tool not in rule.tools:
        return False

    if rule.arg_regex:
        for arg_name, pattern in rule.arg_regex.items():
            if not re.search(pattern, str(arguments.get(arg_name, ""))):
                return False

    if rule.sql:
        if sql_facts is None:
            return False
        if "ddl_kind" in rule.sql and sql_facts.ddl_kind not in rule.sql["ddl_kind"]:
            return False
        if "dml_kind" in rule.sql and sql_facts.dml_kind not in rule.sql["dml_kind"]:
            return False
        if rule.sql.get("no_where") and not sql_facts.no_where:
            return False
        if rule.sql.get("touches_prod_table") and not sql_facts.touches_prod_table:
            return False

    if rule.recipient_count:
        arg_name = rule.recipient_count["arg"]
        gte = rule.recipient_count["gte"]
        recipients = arguments.get(arg_name) or []
        if not (isinstance(recipients, list) and len(recipients) >= gte):
            return False

    return True
