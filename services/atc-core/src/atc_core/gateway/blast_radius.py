"""Pre-approval blast-radius estimation: how many rows would this statement
touch if approved?

Runs BEFORE the hold, deliberately - unlike the creep/loop detectors this is
gate-path information (its whole purpose is to be on the approval card while
the human decides), so it trades a little latency for it. The trade is
bounded: only mutating db__execute statements are estimated (reads and
non-db tools skip instantly) and every failure mode - unparseable SQL,
upstream error, unexpected result shape - degrades to None rather than ever
failing or delaying the underlying call.

The estimate is a read (SELECT COUNT(*)) issued through the same upstream
pool as real calls, so it observes exactly the state the mutation would hit.
"""

from __future__ import annotations

import json
from typing import Protocol

import mcp.types as types
import sqlglot
from sqlglot import exp


class _UpstreamCaller(Protocol):
    async def call_tool(
        self, namespaced_name: str, arguments: dict, *, meta: dict[str, str] | None = None
    ) -> types.CallToolResult: ...


def build_count_sql(sql: str, dialect: str = "postgres") -> str | None:
    """UPDATE/DELETE (bounded or not) and DROP TABLE map to a COUNT over the
    rows they would affect; anything else returns None."""
    try:
        parsed = sqlglot.parse_one(sql, read=dialect)
    except Exception:  # noqa: BLE001 - estimation is best-effort by contract
        return None

    if isinstance(parsed, (exp.Update, exp.Delete)):
        table = parsed.find(exp.Table)
        if table is None:
            return None
        where = parsed.args.get("where")
        count = f"SELECT COUNT(*) AS n FROM {table.sql(dialect=dialect)}"
        if where is not None:
            count += f" WHERE {where.this.sql(dialect=dialect)}"
        return count

    if isinstance(parsed, exp.Drop) and parsed.kind == "TABLE":
        table = parsed.find(exp.Table)
        if table is None:
            return None
        return f"SELECT COUNT(*) AS n FROM {table.sql(dialect=dialect)}"

    return None


async def estimate_blast_radius(
    upstream: _UpstreamCaller, tool: str, arguments: dict
) -> str | None:
    if tool != "db__execute":
        return None
    sql = arguments.get("sql")
    if not isinstance(sql, str) or not sql.strip():
        return None

    count_sql = build_count_sql(sql)
    if count_sql is None:
        return None

    try:
        result = await upstream.call_tool("db__query", {"sql": count_sql})
        first = result.content[0]
        assert isinstance(first, types.TextContent)
        rows = json.loads(first.text)
        n = rows[0]["n"]
        return f"~{int(n)} rows affected"
    except Exception:  # noqa: BLE001 - never let estimation break the gate path
        return None
