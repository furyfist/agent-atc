"""Unit tests for SQLiteBackend."""

from __future__ import annotations

import pytest

from tools_db.backend import SQLiteBackend
from tools_db.seed import seed


@pytest.fixture
async def backend():
    b = await SQLiteBackend.connect(":memory:")
    yield b
    await b.close()


async def test_execute_ddl_and_query_roundtrip(backend: SQLiteBackend) -> None:
    await backend.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    await backend.execute("INSERT INTO t (id, name) VALUES (1, 'alice')")

    rows = await backend.fetch_all("SELECT * FROM t")
    assert rows == [{"id": 1, "name": "alice"}]


async def test_execute_reports_rowcount(backend: SQLiteBackend) -> None:
    await backend.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    await backend.execute("INSERT INTO t (id) VALUES (1)")
    await backend.execute("INSERT INTO t (id) VALUES (2)")
    result = await backend.execute("DELETE FROM t")
    assert "2 row(s) affected" in result


async def test_seed_creates_expected_tables_and_rows(backend: SQLiteBackend) -> None:
    await seed(backend)
    tables = {
        row["name"]
        for row in await backend.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {"staging_old", "customers", "orders", "payments", "users", "invoices"} <= tables

    customers = await backend.fetch_all("SELECT * FROM customers")
    assert len(customers) == 2
