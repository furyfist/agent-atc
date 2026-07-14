"""Integration tests: a real MCP client against a real tools-db server."""

from __future__ import annotations

import json

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from server_helpers import free_port, run_asgi_app
from tools_db.backend import SQLiteBackend
from tools_db.server import build_server


async def _connect(port: int):
    return streamablehttp_client(f"http://127.0.0.1:{port}/mcp", sse_read_timeout=30)


async def test_tools_list_shows_query_and_execute() -> None:
    port = free_port()
    backend = await SQLiteBackend.connect(":memory:")
    app = build_server(backend=backend, port=port).streamable_http_app()

    async with run_asgi_app(app, "127.0.0.1", port):
        async with await _connect(port) as (read, write, _), ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {"query", "execute"} <= {t.name for t in tools.tools}
    await backend.close()


async def test_execute_then_query_roundtrip() -> None:
    port = free_port()
    backend = await SQLiteBackend.connect(":memory:")
    app = build_server(backend=backend, port=port).streamable_http_app()

    async with run_asgi_app(app, "127.0.0.1", port):
        async with await _connect(port) as (read, write, _), ClientSession(read, write) as session:
            await session.initialize()
            await session.call_tool("execute", {"sql": "CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)"})
            await session.call_tool("execute", {"sql": "INSERT INTO t (id, name) VALUES (1, 'alice')"})

            result = await session.call_tool("query", {"sql": "SELECT * FROM t"})
            rows = json.loads(result.content[0].text)
            assert rows == [{"id": 1, "name": "alice"}]
    await backend.close()


async def test_query_rejects_non_select_statements() -> None:
    port = free_port()
    backend = await SQLiteBackend.connect(":memory:")
    app = build_server(backend=backend, port=port).streamable_http_app()

    async with run_asgi_app(app, "127.0.0.1", port):
        async with await _connect(port) as (read, write, _), ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("query", {"sql": "DROP TABLE staging_old"})
            assert "error" in result.content[0].text.lower()
            assert "read-only" in result.content[0].text.lower()
    await backend.close()


async def test_execute_reports_a_real_sql_error() -> None:
    port = free_port()
    backend = await SQLiteBackend.connect(":memory:")
    app = build_server(backend=backend, port=port).streamable_http_app()

    async with run_asgi_app(app, "127.0.0.1", port):
        async with await _connect(port) as (read, write, _), ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("execute", {"sql": "INSERT INTO nonexistent_table VALUES (1)"})
            assert "error" in result.content[0].text.lower()
    await backend.close()


async def test_server_seeds_data_when_no_backend_injected(tmp_path) -> None:
    """The __main__ / real-usage path: no backend given -> connects its own
    SQLite file and seeds it, via the lifespan (not before .run())."""
    port = free_port()
    db_path = str(tmp_path / "dev.sqlite3")
    app = build_server(db_path=db_path, port=port).streamable_http_app()

    async with run_asgi_app(app, "127.0.0.1", port):
        async with await _connect(port) as (read, write, _), ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("query", {"sql": "SELECT * FROM customers"})
            rows = json.loads(result.content[0].text)
            assert len(rows) == 2
