"""sqlglot-derived facts used by SQL-aware risk rules. See PROJECT_PLAN.md S7."""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

__all__ = ["ParseError", "SqlFacts", "extract_sql_facts"]

_DDL_KINDS: dict[type[exp.Expression], str] = {
    exp.Drop: "DROP",
    exp.TruncateTable: "TRUNCATE",
    exp.Alter: "ALTER",
    exp.Create: "CREATE",
}
_DML_KINDS: dict[type[exp.Expression], str] = {
    exp.Insert: "INSERT",
    exp.Update: "UPDATE",
    exp.Delete: "DELETE",
    exp.Select: "SELECT",
}


@dataclass(frozen=True)
class SqlFacts:
    ddl_kind: str | None
    dml_kind: str | None
    no_where: bool
    tables: frozenset[str]
    touches_prod_table: bool
    unrecognized_statement: bool


def _is_tautological(where: exp.Where) -> bool:
    """Catches WHERE clauses that are unbounded in effect even though a
    WHERE node is syntactically present - found in the wild via
    docs/evidence/exp10-policy-redteam.md: `WHERE 1=1` parses with a real
    `where` arg, so a naive `where is None` check misses it entirely."""
    condition = where.this
    if isinstance(condition, exp.Boolean):
        return bool(condition.this)
    if isinstance(condition, exp.EQ) and isinstance(condition.this, exp.Literal) and isinstance(condition.expression, exp.Literal):
        return condition.this.this == condition.expression.this
    return False


def extract_sql_facts(sql: str, prod_tables: set[str], dialect: str = "postgres") -> SqlFacts:
    """Raises sqlglot.errors.ParseError on unparseable SQL - the engine must
    fail closed (HIGH) on that, per PROJECT_PLAN.md S7."""
    parsed = sqlglot.parse_one(sql, read=dialect)

    ddl_kind = next((label for cls, label in _DDL_KINDS.items() if isinstance(parsed, cls)), None)
    dml_kind = next((label for cls, label in _DML_KINDS.items() if isinstance(parsed, cls)), None)

    # DELETE/UPDATE without a WHERE clause, or with one that's always true
    # (`WHERE 1=1`, `WHERE TRUE`) is unbounded-impact regardless of intent.
    where = None
    if isinstance(parsed, (exp.Delete, exp.Update)):
        where = parsed.args.get("where")
    no_where = isinstance(parsed, (exp.Delete, exp.Update)) and (where is None or _is_tautological(where))

    # sqlglot falls back to a generic `Command` node for DDL-shaped syntax it
    # doesn't recognize (e.g. `RENAME TABLE ... TO ...`) instead of raising a
    # ParseError - same "we don't actually understand this statement" risk
    # category as an unparseable statement, so it must fail closed the same
    # way rather than silently landing in dml_kind/ddl_kind=None and matching
    # only the generic MEDIUM default.
    unrecognized_statement = isinstance(parsed, exp.Command)

    tables = frozenset(t.name.lower() for t in parsed.find_all(exp.Table))
    touches_prod_table = bool(tables & {t.lower() for t in prod_tables})

    return SqlFacts(
        ddl_kind=ddl_kind,
        dml_kind=dml_kind,
        no_where=no_where,
        tables=tables,
        touches_prod_table=touches_prod_table,
        unrecognized_statement=unrecognized_statement,
    )
