"""Compensation synthesis from journal payloads."""

from __future__ import annotations

import pytest

from atc_core.gateway.undo import build_compensation
from atc_core.store import JournalEntry


def _entry(kind: str, payload: dict) -> JournalEntry:
    return JournalEntry(action_id="a1", kind=kind, payload=payload, created_at=1000.0)


def test_fs_prior_content_restores_via_write() -> None:
    calls = build_compensation(_entry("fs", {"path": "notes.txt", "content": "old text"}))
    assert calls == [("fs__write", {"path": "notes.txt", "content": "old text"})]


def test_fs_absent_before_means_undo_is_delete() -> None:
    calls = build_compensation(_entry("fs", {"path": "new.txt", "content": None}))
    assert calls == [("fs__delete", {"path": "new.txt"})]


def test_deleted_rows_are_reinserted() -> None:
    calls = build_compensation(
        _entry("db_rows", {"table": "staging_old", "rows": [{"id": 1, "note": "leftover"}, {"id": 2, "note": None}]})
    )
    assert calls == [
        ("db__execute", {"sql": "INSERT OR REPLACE INTO staging_old (id, note) VALUES (1, 'leftover')"}),
        ("db__execute", {"sql": "INSERT OR REPLACE INTO staging_old (id, note) VALUES (2, NULL)"}),
    ]


def test_dropped_table_is_recreated_then_refilled() -> None:
    calls = build_compensation(
        _entry(
            "db_table",
            {
                "table": "staging_old",
                "create_sql": "CREATE TABLE staging_old (id INTEGER PRIMARY KEY, note TEXT)",
                "rows": [{"id": 1, "note": "x"}],
            },
        )
    )
    assert calls[0] == ("db__execute", {"sql": "CREATE TABLE staging_old (id INTEGER PRIMARY KEY, note TEXT)"})
    assert calls[1] == ("db__execute", {"sql": "INSERT OR REPLACE INTO staging_old (id, note) VALUES (1, 'x')"})


def test_string_values_are_quote_escaped() -> None:
    calls = build_compensation(
        _entry("db_rows", {"table": "t", "rows": [{"id": 1, "note": "it's quoted"}]})
    )
    assert calls == [("db__execute", {"sql": "INSERT OR REPLACE INTO t (id, note) VALUES (1, 'it''s quoted')"})]


def test_zero_captured_rows_means_nothing_to_restore() -> None:
    assert build_compensation(_entry("db_rows", {"table": "t", "rows": []})) == []


def test_unknown_kind_raises() -> None:
    with pytest.raises(ValueError, match="unknown journal kind"):
        build_compensation(_entry("email", {}))
