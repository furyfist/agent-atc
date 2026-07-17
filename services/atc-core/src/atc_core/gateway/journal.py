"""Pre-image capture: record what a COMPENSABLE mutation is about to destroy,
before it runs, so it can be undone later (docs/PRODUCT_STRATEGY.md pillar 1).

Design choice: capture happens AT THE GATEWAY, using the same read tools
(fs__read, db__query) the mutation flows through - not inside the tool
servers. That keeps every tool server untouched, guarantees the journal sees
exactly the state the mutation will hit (same connection pool, same instant),
and means undo can later be synthesized as ordinary tool calls through the
same governed path.

Runs post-approval, pre-execution - the one point where the mutation is
certain to happen but hasn't yet. It IS awaited on the execute path (recovery
data must exist before the mutation, so it can't be fire-and-forget like the
creep/loop detectors), but it fails open: a capture error emits an
atc.journal_failed span event and the approved call still executes.
Availability of the approved action wins over completeness of the journal;
the trade is recorded on the trace either way.
"""

from __future__ import annotations

import json
import time

import mcp.types as types
import sqlglot
from sqlglot import exp

from atc_core.store import Store

KIND_FS = "fs"
KIND_DB_ROWS = "db_rows"
KIND_DB_TABLE = "db_table"

_FS_MUTATING_TOOLS = frozenset({"fs__write", "fs__delete"})


class JournalRecorder:
    def __init__(self, store: Store, upstream) -> None:
        self._store = store
        self._upstream = upstream

    async def capture(self, *, action_id: str, tool: str, arguments: dict) -> bool:
        """Returns True if a pre-image was journaled, False if there was
        nothing to capture or capture failed (the caller records the failure
        as a span event; execution proceeds regardless)."""
        try:
            if tool in _FS_MUTATING_TOOLS:
                return await self._capture_fs(action_id, arguments)
            if tool == "db__execute":
                return await self._capture_db(action_id, arguments)
            return False
        except Exception:  # noqa: BLE001 - fail open by contract
            return False

    async def _capture_fs(self, action_id: str, arguments: dict) -> bool:
        path = arguments.get("path")
        if not isinstance(path, str) or not path:
            return False
        text = await self._call_text("fs__read", {"path": path})
        # tools-fs returns "error: no such file..." for absent files - that
        # IS the pre-image: undo of a write that created the file is a delete.
        content = None if text.startswith("error:") else text
        await self._store.insert_journal(
            action_id,
            kind=KIND_FS,
            payload={"path": path, "content": content},
            created_at=time.time(),
        )
        return True

    async def _capture_db(self, action_id: str, arguments: dict) -> bool:
        sql = arguments.get("sql")
        if not isinstance(sql, str) or not sql.strip():
            return False
        parsed = sqlglot.parse_one(sql, read="postgres")

        if isinstance(parsed, (exp.Update, exp.Delete)):
            table = parsed.find(exp.Table)
            if table is None:
                return False
            table_name = table.sql(dialect="postgres")
            where = parsed.args.get("where")
            select = f"SELECT * FROM {table_name}"
            if where is not None:
                select += f" WHERE {where.this.sql(dialect='postgres')}"
            rows = json.loads(await self._call_text("db__query", {"sql": select}))
            await self._store.insert_journal(
                action_id,
                kind=KIND_DB_ROWS,
                payload={"table": table_name, "rows": rows},
                created_at=time.time(),
            )
            return True

        if isinstance(parsed, exp.Drop) and parsed.kind == "TABLE":
            table = parsed.find(exp.Table)
            if table is None:
                return False
            table_name = table.sql(dialect="postgres")
            schema_rows = json.loads(
                await self._call_text(
                    "db__query",
                    {"sql": f"SELECT sql FROM sqlite_master WHERE name = '{table_name}'"},
                )
            )
            if not schema_rows:
                return False
            rows = json.loads(await self._call_text("db__query", {"sql": f"SELECT * FROM {table_name}"}))
            await self._store.insert_journal(
                action_id,
                kind=KIND_DB_TABLE,
                payload={"table": table_name, "create_sql": schema_rows[0]["sql"], "rows": rows},
                created_at=time.time(),
            )
            return True

        return False  # INSERT/CREATE/etc: intrinsically compensable, not journaled in V2-seed

    async def _call_text(self, tool: str, arguments: dict) -> str:
        result = await self._upstream.call_tool(tool, arguments)
        first = result.content[0]
        assert isinstance(first, types.TextContent)
        if first.text.startswith("error:") and tool == "db__query":
            raise RuntimeError(first.text)
        return first.text
