"""Compensation synthesis: turn a journaled pre-image into the ordinary tool
calls that restore it (docs/PRODUCT_STRATEGY.md pillar 1, "approve, regret,
undo").

Compensations are deliberately expressed as the SAME tool calls agents make
(fs__write, db__execute) rather than a privileged side channel - they execute
through the same upstream pool, appear in the same trace schema, and land in
the same action history as everything else. The undo is itself a governed,
auditable action.

Honest limits (V2 seed): row restoration uses INSERT OR REPLACE keyed on the
table's primary key - columns added/removed between capture and undo, or
tables without a primary key, can produce imperfect restores. A compensation
is recovery data applied best-effort, not a time machine; the journal entry
records exactly what was restored either way.
"""

from __future__ import annotations

from atc_core.gateway.journal import KIND_DB_ROWS, KIND_DB_TABLE, KIND_FS
from atc_core.store import JournalEntry

ToolCall = tuple[str, dict]


def build_compensation(entry: JournalEntry) -> list[ToolCall]:
    if entry.kind == KIND_FS:
        return _fs_compensation(entry.payload)
    if entry.kind == KIND_DB_ROWS:
        return _db_rows_compensation(entry.payload)
    if entry.kind == KIND_DB_TABLE:
        return _db_table_compensation(entry.payload)
    raise ValueError(f"unknown journal kind: {entry.kind!r}")


def _fs_compensation(payload: dict) -> list[ToolCall]:
    path = payload["path"]
    content = payload.get("content")
    if content is None:
        # The file didn't exist before the action - undo of its creation is
        # deletion.
        return [("fs__delete", {"path": path})]
    return [("fs__write", {"path": path, "content": content})]


def _db_rows_compensation(payload: dict) -> list[ToolCall]:
    table = payload["table"]
    rows = payload.get("rows") or []
    return [("db__execute", {"sql": _insert_or_replace(table, row)}) for row in rows]


def _db_table_compensation(payload: dict) -> list[ToolCall]:
    calls: list[ToolCall] = [("db__execute", {"sql": payload["create_sql"]})]
    table = payload["table"]
    calls += [("db__execute", {"sql": _insert_or_replace(table, row)}) for row in payload.get("rows") or []]
    return calls


def _insert_or_replace(table: str, row: dict) -> str:
    columns = ", ".join(row.keys())
    values = ", ".join(_sql_literal(v) for v in row.values())
    return f"INSERT OR REPLACE INTO {table} ({columns}) VALUES ({values})"


def _sql_literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    # Journaled values only ever come from our own db__query readbacks, but
    # quote-escape anyway - a note containing a ' must round-trip intact.
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"
