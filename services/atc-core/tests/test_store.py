"""Unit tests for the SQLite store (agents/actions/narrations/settings)."""

from __future__ import annotations

import pytest

from atc_core.risk.models import RiskLevel
from atc_core.store import Action, ActionStatus, Agent, Store


@pytest.fixture
async def store():
    s = await Store.connect(":memory:")
    yield s
    await s.close()


def _agent(agent_id: str = "coder-01", quarantined: bool = False) -> Agent:
    return Agent(
        id=agent_id,
        persona="coder",
        scope=["db", "fs", "git"],
        owner="team",
        quarantined=quarantined,
        last_heartbeat_ts=None,
        created_at=1000.0,
    )


def _action(action_id: str = "a1", agent_id: str = "coder-01", status: ActionStatus = ActionStatus.PENDING) -> Action:
    return Action(
        action_id=action_id,
        trace_id="trace-1",
        span_id="span-1",
        agent_id=agent_id,
        tool="db__execute",
        resource_class="table",
        resource_name="customers",
        args_summary="DELETE FROM customers",
        risk_level=RiskLevel.HIGH,
        risk_reason="Statement touches a table tagged as production",
        rule_id="SQL-PROD-TABLE-HIGH",
        status=status,
        decided_by=None,
        requested_at=1000.0,
        resolved_at=None,
    )


# --- agents ------------------------------------------------------------------


async def test_upsert_and_get_agent(store: Store) -> None:
    await store.upsert_agent(_agent())
    fetched = await store.get_agent("coder-01")
    assert fetched is not None
    assert fetched.persona == "coder"
    assert fetched.scope == ["db", "fs", "git"]
    assert fetched.quarantined is False


async def test_get_unknown_agent_returns_none(store: Store) -> None:
    assert await store.get_agent("nope") is None


async def test_upsert_agent_is_idempotent_update(store: Store) -> None:
    await store.upsert_agent(_agent())
    await store.upsert_agent(_agent())  # same id, should update not duplicate
    agents = await store.list_agents()
    assert len(agents) == 1


async def test_list_agents_returns_all(store: Store) -> None:
    await store.upsert_agent(_agent("coder-01"))
    await store.upsert_agent(_agent("assist-01"))
    agents = await store.list_agents()
    assert {a.id for a in agents} == {"coder-01", "assist-01"}


async def test_set_quarantined(store: Store) -> None:
    await store.upsert_agent(_agent())
    await store.set_quarantined("coder-01", True)
    fetched = await store.get_agent("coder-01")
    assert fetched is not None
    assert fetched.quarantined is True


async def test_record_heartbeat(store: Store) -> None:
    await store.upsert_agent(_agent())
    await store.record_heartbeat("coder-01", 12345.0)
    fetched = await store.get_agent("coder-01")
    assert fetched is not None
    assert fetched.last_heartbeat_ts == 12345.0


# --- actions -------------------------------------------------------------


async def test_insert_and_get_action(store: Store) -> None:
    await store.upsert_agent(_agent())
    await store.insert_action(_action())
    fetched = await store.get_action("a1")
    assert fetched is not None
    assert fetched.risk_level == RiskLevel.HIGH
    assert fetched.status == ActionStatus.PENDING


async def test_get_unknown_action_returns_none(store: Store) -> None:
    assert await store.get_action("nope") is None


async def test_list_actions_filters_by_status(store: Store) -> None:
    await store.upsert_agent(_agent())
    await store.insert_action(_action("a1", status=ActionStatus.PENDING))
    await store.insert_action(_action("a2", status=ActionStatus.AUTO_ALLOWED))
    pending = await store.list_actions(status=ActionStatus.PENDING)
    assert [a.action_id for a in pending] == ["a1"]
    all_actions = await store.list_actions()
    assert {a.action_id for a in all_actions} == {"a1", "a2"}


async def test_resolve_action_updates_status(store: Store) -> None:
    await store.upsert_agent(_agent())
    await store.insert_action(_action())
    resolved = await store.resolve_action(
        "a1", status=ActionStatus.APPROVED, decided_by="alice", resolved_at=2000.0
    )
    assert resolved is True
    fetched = await store.get_action("a1")
    assert fetched is not None
    assert fetched.status == ActionStatus.APPROVED
    assert fetched.decided_by == "alice"
    assert fetched.resolved_at == 2000.0


async def test_resolve_action_guards_against_double_resolution(store: Store) -> None:
    """The WHERE status=PENDING guard: only the first resolve wins."""
    await store.upsert_agent(_agent())
    await store.insert_action(_action())
    first = await store.resolve_action("a1", status=ActionStatus.APPROVED, decided_by="alice", resolved_at=2000.0)
    second = await store.resolve_action("a1", status=ActionStatus.EXPIRED, decided_by=None, resolved_at=2001.0)
    assert first is True
    assert second is False
    fetched = await store.get_action("a1")
    assert fetched is not None
    assert fetched.status == ActionStatus.APPROVED  # not clobbered by the loser


# --- narrations ----------------------------------------------------------


async def test_upsert_and_get_narration(store: Store) -> None:
    await store.upsert_narration("trace-1", "The agent tried X and was denied.", 1000.0)
    assert await store.get_narration("trace-1") == "The agent tried X and was denied."


async def test_upsert_narration_overwrites(store: Store) -> None:
    await store.upsert_narration("trace-1", "first version", 1000.0)
    await store.upsert_narration("trace-1", "second version", 1001.0)
    assert await store.get_narration("trace-1") == "second version"


async def test_get_unknown_narration_returns_none(store: Store) -> None:
    assert await store.get_narration("nope") is None


# --- settings --------------------------------------------------------------


async def test_set_and_get_setting(store: Store) -> None:
    await store.set_setting("demo_mode", "true")
    assert await store.get_setting("demo_mode") == "true"


async def test_set_setting_overwrites(store: Store) -> None:
    await store.set_setting("k", "v1")
    await store.set_setting("k", "v2")
    assert await store.get_setting("k") == "v2"


async def test_get_unknown_setting_returns_none(store: Store) -> None:
    assert await store.get_setting("nope") is None
