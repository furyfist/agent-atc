"""Blast-radius estimation - the count rewrite and its fail-open contract."""

from __future__ import annotations

import json

import mcp.types as types

from atc_core.gateway.blast_radius import build_count_sql, estimate_blast_radius


class FakeUpstream:
    def __init__(self, rows=None, error: Exception | None = None) -> None:
        self._rows = rows if rows is not None else [{"n": 2}]
        self._error = error
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, namespaced_name, arguments, *, meta=None):
        self.calls.append((namespaced_name, arguments))
        if self._error is not None:
            raise self._error
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(self._rows))]
        )


# --- count rewrite -------------------------------------------------------------


def test_bounded_delete_keeps_its_where_clause() -> None:
    sql = build_count_sql("DELETE FROM staging_old WHERE id = 1")
    assert sql == "SELECT COUNT(*) AS n FROM staging_old WHERE id = 1"


def test_unbounded_update_counts_the_whole_table() -> None:
    sql = build_count_sql("UPDATE customers SET email = 'x'")
    assert sql == "SELECT COUNT(*) AS n FROM customers"


def test_drop_table_counts_rows_it_would_take_down() -> None:
    sql = build_count_sql("DROP TABLE staging_old")
    assert sql == "SELECT COUNT(*) AS n FROM staging_old"


def test_non_mutating_and_unsupported_statements_return_none() -> None:
    assert build_count_sql("SELECT * FROM t") is None
    assert build_count_sql("INSERT INTO t (id) VALUES (1)") is None
    assert build_count_sql("CREATE TABLE t (id INTEGER)") is None
    assert build_count_sql("garbage ((( not sql") is None


# --- estimation flow ------------------------------------------------------------


async def test_estimates_via_a_db_query_readback() -> None:
    upstream = FakeUpstream(rows=[{"n": 1200}])
    result = await estimate_blast_radius(
        upstream, "db__execute", {"sql": "DELETE FROM customers WHERE id < 9999"}
    )
    assert result == "~1200 rows affected"
    assert upstream.calls[0][0] == "db__query"


async def test_non_db_tools_and_reads_skip_without_upstream_calls() -> None:
    upstream = FakeUpstream()
    assert await estimate_blast_radius(upstream, "fs__write", {"path": "x"}) is None
    assert await estimate_blast_radius(upstream, "db__execute", {"sql": "SELECT 1"}) is None
    assert upstream.calls == []


async def test_upstream_failure_degrades_to_none() -> None:
    upstream = FakeUpstream(error=RuntimeError("db down"))
    result = await estimate_blast_radius(upstream, "db__execute", {"sql": "DELETE FROM t WHERE 1=1"})
    assert result is None


async def test_malformed_result_degrades_to_none() -> None:
    upstream = FakeUpstream(rows=[])
    result = await estimate_blast_radius(upstream, "db__execute", {"sql": "DELETE FROM t WHERE 1=1"})
    assert result is None
