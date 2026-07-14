"""Unit tests for the risk engine, run against the real shipped policy at
policies/risk_rules.yaml - this IS the demo/blog artifact (PROJECT_PLAN.md S7),
so tests exercise what's actually deployed, not a synthetic fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atc_core.risk import RiskEngine, RiskLevel
from atc_core.risk.engine import SQL_PARSE_ERROR_RULE_ID, UNMATCHED_RULE_ID
from atc_core.risk.models import RiskRule

POLICY_PATH = Path(__file__).resolve().parents[3] / "policies" / "risk_rules.yaml"


@pytest.fixture(scope="module")
def engine() -> RiskEngine:
    return RiskEngine.from_yaml(POLICY_PATH)


def test_policy_file_loads_and_is_non_empty(engine: RiskEngine) -> None:
    assert engine._rules  # noqa: SLF001 - sanity check on the loaded policy
    assert engine._prod_tables  # noqa: SLF001


# --- db__query / db__execute ------------------------------------------------


def test_sql_read_is_low(engine: RiskEngine) -> None:
    d = engine.evaluate("db__query", {"sql": "SELECT * FROM staging_old"})
    assert d.risk_level == RiskLevel.LOW
    assert d.rule_id == "SQL-READ-LOW"


def test_sql_bounded_write_on_non_prod_table_is_medium(engine: RiskEngine) -> None:
    d = engine.evaluate("db__execute", {"sql": "DELETE FROM staging_old WHERE id = 1"})
    assert d.risk_level == RiskLevel.MEDIUM
    assert d.rule_id == "SQL-WRITE-MEDIUM"


@pytest.mark.parametrize("sql", ["DELETE FROM staging_old", "UPDATE staging_old SET x = 1"])
def test_sql_unbounded_write_is_high(engine: RiskEngine, sql: str) -> None:
    d = engine.evaluate("db__execute", {"sql": sql})
    assert d.risk_level == RiskLevel.HIGH
    assert d.rule_id == "SQL-UNBOUNDED-WRITE-HIGH"


@pytest.mark.parametrize(
    "sql",
    ["DROP TABLE staging_old", "TRUNCATE TABLE staging_old", "ALTER TABLE staging_old ADD COLUMN x int"],
)
def test_sql_destructive_ddl_is_high(engine: RiskEngine, sql: str) -> None:
    d = engine.evaluate("db__execute", {"sql": sql})
    assert d.risk_level == RiskLevel.HIGH
    assert d.rule_id == "SQL-DESTRUCTIVE-DDL-HIGH"


def test_act2_scenario_prod_table_touch_overrides_bounded_looking_write(engine: RiskEngine) -> None:
    """The Act 2 shape (S11): a bounded, WHERE-clause-having statement that
    *looks* reasonable still gets HIGH because it targets a table tagged
    production - infra tags the agent has no visibility into."""
    d = engine.evaluate("db__execute", {"sql": "DELETE FROM customers WHERE created_at < '2020-01-01'"})
    assert d.risk_level == RiskLevel.HIGH
    assert d.rule_id == "SQL-PROD-TABLE-HIGH"


def test_sql_prod_table_beats_destructive_ddl_ordering(engine: RiskEngine) -> None:
    d = engine.evaluate("db__execute", {"sql": "DROP TABLE customers"})
    assert d.rule_id == "SQL-PROD-TABLE-HIGH"  # first match wins, prod-table rule is listed first


def test_sql_unparseable_fails_closed_to_high(engine: RiskEngine) -> None:
    d = engine.evaluate("db__execute", {"sql": "DELETE FROM WHERE garbage ;;; not sql"})
    assert d.risk_level == RiskLevel.HIGH
    assert d.rule_id == SQL_PARSE_ERROR_RULE_ID


# --- fs__read / fs__write / fs__delete --------------------------------------


def test_fs_read_is_low(engine: RiskEngine) -> None:
    d = engine.evaluate("fs__read", {"path": "/data/notes.txt"})
    assert d.risk_level == RiskLevel.LOW


def test_fs_write_is_medium(engine: RiskEngine) -> None:
    d = engine.evaluate("fs__write", {"path": "/data/notes.txt", "content": "hi"})
    assert d.risk_level == RiskLevel.MEDIUM
    assert d.rule_id == "FS-WRITE-MEDIUM"


def test_fs_delete_is_high(engine: RiskEngine) -> None:
    d = engine.evaluate("fs__delete", {"path": "/data/notes.txt"})
    assert d.risk_level == RiskLevel.HIGH
    assert d.rule_id == "FS-DELETE-HIGH"


@pytest.mark.parametrize(
    "path",
    ["/app/.env", "/app/.env.production", "/app/secrets/api_key.txt", "/home/user/.ssh/id_rsa", "/app/credentials.json"],
)
def test_fs_write_sensitive_path_is_high(engine: RiskEngine, path: str) -> None:
    d = engine.evaluate("fs__write", {"path": path, "content": "x"})
    assert d.risk_level == RiskLevel.HIGH
    assert d.rule_id == "FS-SENSITIVE-PATH-HIGH"


def test_fs_delete_sensitive_path_beats_generic_delete(engine: RiskEngine) -> None:
    d = engine.evaluate("fs__delete", {"path": "/app/secrets/api_key.txt"})
    assert d.rule_id == "FS-SENSITIVE-PATH-HIGH"


# --- git__push / git__force_push --------------------------------------------


def test_git_push_is_medium(engine: RiskEngine) -> None:
    d = engine.evaluate("git__push", {})
    assert d.risk_level == RiskLevel.MEDIUM


def test_git_force_push_is_high(engine: RiskEngine) -> None:
    d = engine.evaluate("git__force_push", {})
    assert d.risk_level == RiskLevel.HIGH


# --- email__send -------------------------------------------------------------


def test_email_send_small_recipient_list_is_low(engine: RiskEngine) -> None:
    d = engine.evaluate("email__send", {"to": ["a@example.com", "b@example.com"]})
    assert d.risk_level == RiskLevel.LOW


def test_email_send_broad_recipient_list_is_high(engine: RiskEngine) -> None:
    d = engine.evaluate("email__send", {"to": [f"user{i}@example.com" for i in range(12)]})
    assert d.risk_level == RiskLevel.HIGH
    assert d.rule_id == "EMAIL-BROAD-RECIPIENTS-HIGH"


# --- fail-closed defaults ----------------------------------------------------


def test_unmatched_tool_call_fails_closed_to_medium(engine: RiskEngine) -> None:
    d = engine.evaluate("some__unknown_tool", {"anything": "goes"})
    assert d.risk_level == RiskLevel.MEDIUM
    assert d.rule_id == UNMATCHED_RULE_ID


# --- engine mechanics (ordering), independent of the shipped policy --------


def test_first_match_wins_regardless_of_rule_specificity() -> None:
    rules = [
        RiskRule(id="GENERIC-FIRST", risk_level=RiskLevel.LOW, reason="generic", tools=["db__execute"]),
        RiskRule(
            id="SPECIFIC-SECOND",
            risk_level=RiskLevel.HIGH,
            reason="specific",
            tools=["db__execute"],
            sql={"ddl_kind": ["DROP"]},
        ),
    ]
    engine = RiskEngine(rules, prod_tables=set())
    d = engine.evaluate("db__execute", {"sql": "DROP TABLE anything"})
    assert d.rule_id == "GENERIC-FIRST"  # earlier rule wins even though the later one is more specific
