"""Reversibility classification - the consequence signal orthogonal to risk."""

from __future__ import annotations

from pathlib import Path

import pytest

from atc_core.risk import Reversibility, RiskEngine
from atc_core.risk.reversibility import classify
from atc_core.risk.sql_facts import extract_sql_facts

POLICY_PATH = Path(__file__).resolve().parents[3] / "policies" / "risk_rules.yaml"


def _facts(sql: str):
    return extract_sql_facts(sql, prod_tables={"customers"})


@pytest.mark.parametrize(
    ("tool", "sql", "expected"),
    [
        ("fs__read", None, Reversibility.REVERSIBLE),
        ("db__query", None, Reversibility.REVERSIBLE),
        ("fs__write", None, Reversibility.COMPENSABLE),
        ("fs__delete", None, Reversibility.COMPENSABLE),
        ("email__send", None, Reversibility.IRREVERSIBLE),
        ("git__push", None, Reversibility.IRREVERSIBLE),
        ("git__force_push", None, Reversibility.IRREVERSIBLE),
        ("some__unknown_tool", None, Reversibility.IRREVERSIBLE),
        ("db__execute", "SELECT * FROM orders", Reversibility.REVERSIBLE),
        ("db__execute", "INSERT INTO t (id) VALUES (1)", Reversibility.COMPENSABLE),
        ("db__execute", "UPDATE t SET x = 1 WHERE id = 1", Reversibility.COMPENSABLE),
        ("db__execute", "DELETE FROM t", Reversibility.COMPENSABLE),
        ("db__execute", "DROP TABLE t", Reversibility.COMPENSABLE),
        ("db__execute", "CREATE TABLE t (id INTEGER)", Reversibility.COMPENSABLE),
        ("db__execute", "ALTER TABLE t RENAME TO u", Reversibility.IRREVERSIBLE),
        ("db__execute", "TRUNCATE TABLE t", Reversibility.IRREVERSIBLE),
    ],
)
def test_classification(tool: str, sql: str | None, expected: Reversibility) -> None:
    facts = _facts(sql) if sql else None
    assert classify(tool, facts) == expected


def test_unparseable_sql_fails_closed_to_irreversible() -> None:
    assert classify("db__execute", None) == Reversibility.IRREVERSIBLE


def test_engine_decisions_carry_reversibility() -> None:
    engine = RiskEngine.from_yaml(POLICY_PATH)

    drop = engine.evaluate("db__execute", {"sql": "DROP TABLE staging_old"})
    assert drop.reversibility == Reversibility.COMPENSABLE

    push = engine.evaluate("git__force_push", {"remote": "origin"})
    assert push.reversibility == Reversibility.IRREVERSIBLE

    read = engine.evaluate("db__query", {"sql": "SELECT 1"})
    assert read.reversibility == Reversibility.REVERSIBLE

    garbage = engine.evaluate("db__execute", {"sql": "NOT SQL AT ALL ((("})
    assert garbage.reversibility == Reversibility.IRREVERSIBLE
