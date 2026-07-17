"""Pre-image capture at the gateway (recoverability pillar, V2 seed)."""

from __future__ import annotations

import json

import mcp.types as types
import pytest

from atc_core.gateway.journal import KIND_DB_ROWS, KIND_DB_TABLE, KIND_FS, JournalRecorder
from atc_core.store import Store


class FakeUpstream:
    """Maps (tool, canned-response) - responses keyed by substring match on
    the sql/path so one fake serves several capture shapes."""

    def __init__(self, responses: dict[str, str]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, tool, arguments, *, meta=None):
        self.calls.append((tool, arguments))
        probe = arguments.get("sql") or arguments.get("path") or ""
        for key, text in self._responses.items():
            if key in probe:
                return types.CallToolResult(content=[types.TextContent(type="text", text=text)])
        raise AssertionError(f"no canned response for {tool} {arguments}")


@pytest.fixture
async def store():
    s = await Store.connect(":memory:")
    await s.upsert_agent(
        Agent(
            id="coder-01", persona="coder", scope=["db", "fs"], owner="team",
            quarantined=False, last_heartbeat_ts=None, created_at=1000.0,
        )
    )
    # The journal FK requires the action row to exist - in production the
    # gateway always inserts the action before capture runs.
    for action_id in ("a1", "a2", "a3"):
        await s.insert_action(
            Action(
                action_id=action_id, trace_id="t", span_id=None, agent_id="coder-01",
                tool="db__execute", resource_class="db", resource_name="staging_old",
                args_summary="{}", risk_level=RiskLevel.HIGH, risk_reason="r",
                rule_id="R", status=ActionStatus.APPROVED, decided_by="operator",
                requested_at=1000.0, resolved_at=1001.0,
            )
        )
    yield s
    await s.close()


async def test_fs_write_captures_prior_content(store: Store) -> None:
    upstream = FakeUpstream({"notes.txt": "old content"})
    recorder = JournalRecorder(store, upstream)

    ok = await recorder.capture(action_id="a1", tool="fs__write", arguments={"path": "notes.txt"})
    assert ok is True

    entry = await store.get_journal("a1")
    assert entry is not None and entry.kind == KIND_FS
    assert entry.payload == {"path": "notes.txt", "content": "old content"}


async def test_fs_write_to_absent_file_records_none(store: Store) -> None:
    upstream = FakeUpstream({"new.txt": "error: no such file: 'new.txt'"})
    recorder = JournalRecorder(store, upstream)

    ok = await recorder.capture(action_id="a1", tool="fs__write", arguments={"path": "new.txt"})
    assert ok is True
    entry = await store.get_journal("a1")
    assert entry is not None and entry.payload["content"] is None


async def test_bounded_delete_captures_matching_rows(store: Store) -> None:
    rows = [{"id": 1, "note": "keep me"}]
    upstream = FakeUpstream({"SELECT * FROM staging_old WHERE id = 1": json.dumps(rows)})
    recorder = JournalRecorder(store, upstream)

    ok = await recorder.capture(
        action_id="a1", tool="db__execute", arguments={"sql": "DELETE FROM staging_old WHERE id = 1"}
    )
    assert ok is True
    entry = await store.get_journal("a1")
    assert entry is not None and entry.kind == KIND_DB_ROWS
    assert entry.payload == {"table": "staging_old", "rows": rows}


async def test_drop_table_captures_schema_and_rows(store: Store) -> None:
    upstream = FakeUpstream(
        {
            "sqlite_master": json.dumps([{"sql": "CREATE TABLE staging_old (id INTEGER PRIMARY KEY, note TEXT)"}]),
            "SELECT * FROM staging_old": json.dumps([{"id": 1, "note": "x"}, {"id": 2, "note": "y"}]),
        }
    )
    recorder = JournalRecorder(store, upstream)

    ok = await recorder.capture(
        action_id="a1", tool="db__execute", arguments={"sql": "DROP TABLE staging_old"}
    )
    assert ok is True
    entry = await store.get_journal("a1")
    assert entry is not None and entry.kind == KIND_DB_TABLE
    assert entry.payload["create_sql"].startswith("CREATE TABLE staging_old")
    assert len(entry.payload["rows"]) == 2


async def test_insert_and_reads_are_not_journaled(store: Store) -> None:
    upstream = FakeUpstream({})
    recorder = JournalRecorder(store, upstream)

    assert await recorder.capture(action_id="a1", tool="db__execute", arguments={"sql": "INSERT INTO t (id) VALUES (1)"}) is False
    assert await recorder.capture(action_id="a2", tool="db__query", arguments={"sql": "SELECT 1"}) is False
    assert await recorder.capture(action_id="a3", tool="git__push", arguments={}) is False
    assert upstream.calls == []


async def test_capture_fails_open_on_upstream_error(store: Store) -> None:
    class ExplodingUpstream:
        async def call_tool(self, tool, arguments, *, meta=None):
            raise RuntimeError("upstream is down")

    recorder = JournalRecorder(store, ExplodingUpstream())
    ok = await recorder.capture(
        action_id="a1", tool="db__execute", arguments={"sql": "DELETE FROM t WHERE id = 1"}
    )
    assert ok is False
    assert await store.get_journal("a1") is None
