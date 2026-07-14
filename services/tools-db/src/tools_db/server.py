"""tools-db: MCP server for db__query (read-only) and db__execute
(write/DDL). See PROJECT_PLAN.md S4. Pluggable backend - SQLite for
Docker-free local dev (default, see backend.py), Postgres (victim-postgres)
once Docker is available.

The async backend connection is made inside FastMCP's own `lifespan` (not
before calling `.run()`) so it's bound to the same event loop `.run()`
actually serves on - aiosqlite connections don't survive a loop handoff.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import sqlglot
from mcp.server.fastmcp import Context, FastMCP
from sqlglot import exp

from tools_db.backend import SQLiteBackend, SqlBackend
from tools_db.seed import seed

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "volume" / "dev.sqlite3"


@dataclass
class AppState:
    backend: SqlBackend


def _is_select(sql: str) -> bool:
    try:
        parsed = sqlglot.parse_one(sql, read="postgres")
    except Exception:  # noqa: BLE001 - any parse failure means "not a clean SELECT"
        return False
    return isinstance(parsed, exp.Select)


def build_server(
    *,
    db_path: str | None = None,
    backend: SqlBackend | None = None,
    host: str | None = None,
    port: int | None = None,
) -> FastMCP:
    if backend is not None:
        # Caller (tests) owns the backend's connection lifecycle already -
        # just hand it through, don't connect/seed/close it ourselves.
        @asynccontextmanager
        async def lifespan(_server: FastMCP) -> AsyncIterator[AppState]:
            yield AppState(backend=backend)
    else:
        resolved_path = db_path or str(DEFAULT_DB_PATH)
        Path(resolved_path).parent.mkdir(parents=True, exist_ok=True)

        @asynccontextmanager
        async def lifespan(_server: FastMCP) -> AsyncIterator[AppState]:
            sqlite_backend = await SQLiteBackend.connect(resolved_path)
            await seed(sqlite_backend)
            try:
                yield AppState(backend=sqlite_backend)
            finally:
                await sqlite_backend.close()

    resolved_host = host or os.environ.get("ATC_DB_HOST", "127.0.0.1")
    resolved_port = port if port is not None else int(os.environ.get("ATC_DB_PORT", "9001"))
    mcp = FastMCP("tools-db", host=resolved_host, port=resolved_port, lifespan=lifespan)

    @mcp.tool(structured_output=False)
    async def query(sql: str, ctx: Context) -> str:
        if not _is_select(sql):
            return "error: query only accepts read-only SELECT statements - use execute for writes/DDL"
        state: AppState = ctx.request_context.lifespan_context
        try:
            rows = await state.backend.fetch_all(sql)
        except Exception as exc:  # noqa: BLE001 - surface the real DB error to the caller
            return f"error: {exc}"
        return json.dumps(rows, default=str)

    @mcp.tool(structured_output=False)
    async def execute(sql: str, ctx: Context) -> str:
        state: AppState = ctx.request_context.lifespan_context
        try:
            return await state.backend.execute(sql)
        except Exception as exc:  # noqa: BLE001
            return f"error: {exc}"

    return mcp


if __name__ == "__main__":
    build_server().run(transport="streamable-http")
