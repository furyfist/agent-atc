"""Tests for the REST API and WebSocket endpoint (S8).

REST tests use httpx.AsyncClient + ASGITransport (async-native, matches the
async test functions here). The WS test uses Starlette's TestClient in a
plain sync test function instead - TestClient's blocking wrapper can deadlock
if invoked from a test function that's already running inside an asyncio
event loop (as every async def test here is, under pytest-asyncio), so it
gets a lane of its own with a manually-driven event loop for setup.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atc_core.api import api_router, ws_router
from atc_core.approval import ApprovalManager
from atc_core.events import EventBus
from atc_core.narrator import ActionStoreSpanFetcher, Narrator
from atc_core.risk.models import RiskDecision, RiskLevel
from atc_core.store import Action, ActionStatus, Agent, Store

FAST_HOLD_TIMEOUT = 0.15


def _build_app(
    store: Store, approval_manager: ApprovalManager, event_bus: EventBus, narrator: Narrator | None = None
) -> FastAPI:
    app = FastAPI()
    app.state.store = store
    app.state.approval_manager = approval_manager
    app.state.event_bus = event_bus
    app.state.narrator = narrator
    app.include_router(api_router)
    app.include_router(ws_router)
    return app


def _risk(level: RiskLevel) -> RiskDecision:
    return RiskDecision(risk_level=level, reason="test reason", rule_id="TEST-RULE")


@pytest.fixture
async def store():
    s = await Store.connect(":memory:")
    await s.upsert_agent(
        Agent(
            id="coder-01",
            persona="coder",
            scope=["db"],
            owner="team",
            quarantined=False,
            last_heartbeat_ts=None,
            created_at=1000.0,
        )
    )
    yield s
    await s.close()


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def manager(store: Store, event_bus: EventBus) -> ApprovalManager:
    return ApprovalManager(store, hold_timeout_seconds=FAST_HOLD_TIMEOUT, event_bus=event_bus)


@pytest.fixture
async def client(store: Store, manager: ApprovalManager, event_bus: EventBus):
    app = _build_app(store, manager, event_bus)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# --- GET /api/agents -----------------------------------------------------


async def test_list_agents(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/agents")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == "coder-01"
    assert body[0]["scope"] == ["db"]
    assert body[0]["quarantined"] is False


# --- GET /api/actions ------------------------------------------------------


async def test_list_actions_empty(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/actions")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_actions_filters_by_status(client: httpx.AsyncClient, manager: ApprovalManager) -> None:
    await manager.submit(
        action_id="a1", trace_id="t1", span_id=None, agent_id="coder-01", tool="db__execute",
        resource_class="db", resource_name=None, args_summary=None, risk=_risk(RiskLevel.HIGH),
    )
    await manager.submit(
        action_id="a2", trace_id="t1", span_id=None, agent_id="coder-01", tool="db__query",
        resource_class="db", resource_name=None, args_summary=None, risk=_risk(RiskLevel.LOW),
    )

    resp = await client.get("/api/actions", params={"status": "pending"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["action_id"] == "a1"
    assert body[0]["status"] == "PENDING"
    assert body[0]["risk_level"] == "HIGH"


async def test_list_actions_unknown_status_is_422(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/actions", params={"status": "not-a-real-status"})
    assert resp.status_code == 422


# --- approve/deny ------------------------------------------------------------


async def test_approve_action(client: httpx.AsyncClient, manager: ApprovalManager) -> None:
    await manager.submit(
        action_id="a1", trace_id="t1", span_id=None, agent_id="coder-01", tool="db__execute",
        resource_class="db", resource_name=None, args_summary=None, risk=_risk(RiskLevel.HIGH),
    )

    resp = await client.post("/api/actions/a1/approve", json={"decided_by": "alice"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "APPROVED"
    assert body["decided_by"] == "alice"


async def test_deny_action(client: httpx.AsyncClient, manager: ApprovalManager) -> None:
    await manager.submit(
        action_id="a1", trace_id="t1", span_id=None, agent_id="coder-01", tool="db__execute",
        resource_class="db", resource_name=None, args_summary=None, risk=_risk(RiskLevel.HIGH),
    )

    resp = await client.post("/api/actions/a1/deny", json={"decided_by": "bob"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "DENIED"


async def test_approve_unknown_action_is_404(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/actions/nope/approve", json={"decided_by": "alice"})
    assert resp.status_code == 404


async def test_decide_requires_decided_by(client: httpx.AsyncClient, manager: ApprovalManager) -> None:
    await manager.submit(
        action_id="a1", trace_id="t1", span_id=None, agent_id="coder-01", tool="db__execute",
        resource_class="db", resource_name=None, args_summary=None, risk=_risk(RiskLevel.HIGH),
    )
    resp = await client.post("/api/actions/a1/approve", json={})
    assert resp.status_code == 422


# --- quarantine --------------------------------------------------------------


async def test_quarantine_agent_bare_post_defaults_to_true(client: httpx.AsyncClient, store: Store) -> None:
    resp = await client.post("/api/agents/coder-01/quarantine")
    assert resp.status_code == 200
    assert resp.json()["quarantined"] is True
    fetched = await store.get_agent("coder-01")
    assert fetched is not None
    assert fetched.quarantined is True


async def test_unquarantine_agent_explicit_false(client: httpx.AsyncClient, store: Store) -> None:
    await store.set_quarantined("coder-01", True)
    resp = await client.post("/api/agents/coder-01/quarantine", json={"quarantined": False})
    assert resp.status_code == 200
    assert resp.json()["quarantined"] is False


async def test_quarantine_unknown_agent_is_404(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/agents/nope/quarantine")
    assert resp.status_code == 404


# --- heartbeat -----------------------------------------------------------


async def test_heartbeat_records_timestamp(client: httpx.AsyncClient, store: Store) -> None:
    resp = await client.post("/api/agents/coder-01/heartbeat")
    assert resp.status_code == 200
    body = resp.json()
    assert body["last_heartbeat_ts"] is not None

    fetched = await store.get_agent("coder-01")
    assert fetched is not None
    assert fetched.last_heartbeat_ts == pytest.approx(body["last_heartbeat_ts"])


async def test_heartbeat_unknown_agent_is_404(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/agents/nope/heartbeat")
    assert resp.status_code == 404


async def test_heartbeat_publishes_events(store: Store, manager: ApprovalManager, event_bus: EventBus) -> None:
    app = _build_app(store, manager, event_bus)

    with TestClient(app) as client, client.websocket_connect("/ws") as websocket:
        client.post("/api/agents/coder-01/heartbeat")
        first = websocket.receive_json()
        second = websocket.receive_json()

    assert {first["type"], second["type"]} == {"agent.heartbeat", "risk.updated"}


# --- websocket (sync TestClient - see module docstring) ----------------------


def test_websocket_receives_action_pending_event() -> None:
    async def setup() -> Store:
        s = await Store.connect(":memory:")
        await s.upsert_agent(
            Agent(
                id="coder-01", persona="coder", scope=["db"], owner=None,
                quarantined=False, last_heartbeat_ts=None, created_at=1000.0,
            )
        )
        return s

    store = asyncio.run(setup())
    event_bus = EventBus()
    manager = ApprovalManager(store, hold_timeout_seconds=999, event_bus=event_bus)
    app = _build_app(store, manager, event_bus)

    with TestClient(app) as client, client.websocket_connect("/ws") as websocket:
        asyncio.run(
            manager.submit(
                action_id="a1", trace_id="t1", span_id=None, agent_id="coder-01",
                tool="db__execute", resource_class="db", resource_name=None,
                args_summary=None, risk=_risk(RiskLevel.HIGH),
            )
        )
        message = websocket.receive_json()
        assert message["type"] == "action.pending"
        assert message["payload"]["action_id"] == "a1"

    asyncio.run(store.close())


# --- POST /api/narrate --------------------------------------------------------


async def test_narrate_returns_503_when_not_configured(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/narrate", json={"trace_id": "trace-1"})
    assert resp.status_code == 503


async def test_narrate_returns_text_when_configured(store: Store, manager: ApprovalManager, event_bus: EventBus) -> None:
    await store.insert_action(
        Action(
            action_id="a1", trace_id="trace-1", span_id=None, agent_id="coder-01",
            tool="db__query", resource_class="db", resource_name=None, args_summary=None,
            risk_level=_risk(RiskLevel.LOW).risk_level, risk_reason="Read-only query",
            rule_id="SQL-READ-LOW", status=ActionStatus.AUTO_ALLOWED, decided_by=None,
            requested_at=1000.0, resolved_at=1000.0,
        )
    )

    async def chat_fn(system_prompt: str, user_content: str) -> str:
        return "narrated text"

    narrator = Narrator(store=store, span_fetcher=ActionStoreSpanFetcher(store), chat_fn=chat_fn)
    app = _build_app(store, manager, event_bus, narrator)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/narrate", json={"trace_id": "trace-1"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["trace_id"] == "trace-1"
    assert body["text"] == "narrated text"
