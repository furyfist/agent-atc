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


def extract_sql_facts(sql: str, prod_tables: set[str], dialect: str = "postgres") -> SqlFacts:
    """Raises sqlglot.errors.ParseError on unparseable SQL - the engine must
    fail closed (HIGH) on that, per PROJECT_PLAN.md S7."""
    parsed = sqlglot.parse_one(sql, read=dialect)

    ddl_kind = next((label for cls, label in _DDL_KINDS.items() if isinstance(parsed, cls)), None)
    dml_kind = next((label for cls, label in _DML_KINDS.items() if isinstance(parsed, cls)), None)

    # DELETE/UPDATE without WHERE is unbounded-impact regardless of intent.
    no_where = isinstance(parsed, (exp.Delete, exp.Update)) and parsed.args.get("where") is None

    tables = frozenset(t.name.lower() for t in parsed.find_all(exp.Table))
    touches_prod_table = bool(tables & {t.lower() for t in prod_tables})

    return SqlFacts(
        ddl_kind=ddl_kind,
        dml_kind=dml_kind,
        no_where=no_where,
        tables=tables,
        touches_prod_table=touches_prod_table,
    )
