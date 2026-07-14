"""Pluggable SQL backend. Only SQLiteBackend is implemented today - Docker
(and victim-postgres) aren't available yet, so a PostgresBackend implementing
the same Protocol is the natural next addition once they are, per
PROJECT_PLAN.md S4 ("tools-db ... -> victim-postgres"). Keeping this as a
narrow Protocol now means that addition won't touch server.py at all.
"""

from __future__ import annotations

from typing import Any, Protocol

import aiosqlite


class SqlBackend(Protocol):
    async def fetch_all(self, sql: str) -> list[dict[str, Any]]: ...
    async def execute(self, sql: str) -> str: ...
    async def close(self) -> None: ...


class SQLiteBackend:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    @classmethod
    async def connect(cls, path: str) -> SQLiteBackend:
        conn = await aiosqlite.connect(path)
        conn.row_factory = aiosqlite.Row
        return cls(conn)

    async def fetch_all(self, sql: str) -> list[dict[str, Any]]:
        cursor = await self._conn.execute(sql)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def execute(self, sql: str) -> str:
        cursor = await self._conn.execute(sql)
        await self._conn.commit()
        return f"OK, {cursor.rowcount} row(s) affected"

    async def close(self) -> None:
        await self._conn.close()
