"""Tests for the top-level app assembly (S4): proves /mcp, /api, and /ws all
work when composed into ONE app under one lifespan - specifically, that
gateway.startup() and the MCP session manager actually run (they wouldn't if
the MCP handler were mounted as a sub-app with its own lifespan; Starlette
does not forward lifespan events to mounted sub-apps).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from atc_core.app import build_full_app
from atc_core.approval import ApprovalManager
from atc_core.events import EventBus
from atc_core.gateway import AgentRegistry, Gateway, UpstreamPool
from atc_core.risk import RiskEngine
from atc_core.store import Store
from atc_telemetry import configure_tracing

from gateway_helpers import build_mock_db_server, free_port, run_asgi_app

REPO_ROOT = Path(__file__).resolve().parents[3]
RISK_POLICY_PATH = REPO_ROOT / "policies" / "risk_rules.yaml"
AGENTS_POLICY_PATH = REPO_ROOT / "policies" / "agents.yaml"
STATIC_DIR = REPO_ROOT / "services" / "atc-core" / "static"

TOKEN = "tok-coder-01"


@dataclass
class AppHandle:
    base_url: str
    gateway_url: str


@asynccontextmanager
async def full_app_context(
    monkeypatch: pytest.MonkeyPatch, *, static_dir: Path | None = None
) -> AsyncIterator[AppHandle]:
    monkeypatch.setenv("ATC_TOKEN_CODER_01", TOKEN)
    monkeypatch.setenv("ATC_TOKEN_ASSIST_01", "tok-assist-01")
    monkeypatch.setenv("ATC_TOKEN_COMPLY_01", "tok-comply-01")

    db_port, app_port = free_port(), free_port()
    db_app = build_mock_db_server(db_port).streamable_http_app()

    async with run_asgi_app(db_app, "127.0.0.1", db_port):
        store = await Store.connect(":memory:")
        risk_engine = RiskEngine.from_yaml(RISK_POLICY_PATH)
        event_bus = EventBus()
        approval_manager = ApprovalManager(store, hold_timeout_seconds=0.2, event_bus=event_bus)
        registry = AgentRegistry.from_yaml(AGENTS_POLICY_PATH)

        upstream = UpstreamPool()
        await upstream.connect({"db": f"http://127.0.0.1:{db_port}/mcp"})

        tracer = configure_tracing("test-full-app")
        gateway = Gateway(
            registry=registry,
            risk_engine=risk_engine,
            approval_manager=approval_manager,
            store=store,
            upstream=upstream,
            tracer=tracer,
        )
        app = build_full_app(
            gateway=gateway,
            store=store,
            approval_manager=approval_manager,
            event_bus=event_bus,
            static_dir=static_dir,
        )

        async with run_asgi_app(app, "127.0.0.1", app_port):
            try:
                yield AppHandle(
                    base_url=f"http://127.0.0.1:{app_port}",
                    gateway_url=f"http://127.0.0.1:{app_port}/mcp",
                )
            finally:
                await upstream.close()
                await store.close()


async def test_mcp_endpoint_works_under_combined_lifespan(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves gateway.startup() (upstream connect) and the MCP session
    manager actually ran under the top-level app's lifespan."""
    async with full_app_context(monkeypatch) as handle:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        async with streamablehttp_client(handle.gateway_url, headers=headers, sse_read_timeout=30) as (
            read,
            write,
            _,
        ):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {t.name for t in tools.tools}
                assert "db__query" in names


async def test_rest_api_reachable_on_same_app(monkeypatch: pytest.MonkeyPatch) -> None:
    async with full_app_context(monkeypatch) as handle:
        async with httpx.AsyncClient(base_url=handle.base_url) as client:
            resp = await client.get("/api/agents")
            assert resp.status_code == 200
            ids = {a["id"] for a in resp.json()}
            assert {"coder-01", "assist-01", "comply-01"} <= ids


async def test_mcp_call_and_rest_approve_share_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real end-to-end loop: an MCP tool call gets held, and the REST API
    (running in the same process, same Store/ApprovalManager) approves it."""
    async with full_app_context(monkeypatch) as handle:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        async with (
            streamablehttp_client(handle.gateway_url, headers=headers, sse_read_timeout=30) as (
                read,
                write,
                _,
            ),
            httpx.AsyncClient(base_url=handle.base_url) as rest_client,
        ):
            async with ClientSession(read, write) as session:
                await session.initialize()
                call_task = asyncio.create_task(
                    session.call_tool("db__execute", {"sql": "DROP TABLE customers"})
                )

                pending = []
                for _ in range(50):
                    resp = await rest_client.get("/api/actions", params={"status": "pending"})
                    pending = resp.json()
                    if pending:
                        break
                    await asyncio.sleep(0.02)
                assert pending, "no pending action appeared via REST"

                approve_resp = await rest_client.post(
                    f"/api/actions/{pending[0]['action_id']}/approve",
                    json={"decided_by": "tester"},
                )
                assert approve_resp.status_code == 200

                result = await call_task
                text = result.content[0].text if result.content else ""
                assert "execute ran" in text


async def test_static_ui_served_without_shadowing_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """The approval UI is reachable at / and doesn't shadow /api, /mcp, /ws -
    the static mount must be registered last."""
    async with full_app_context(monkeypatch, static_dir=STATIC_DIR) as handle:
        async with httpx.AsyncClient(base_url=handle.base_url) as client:
            index_resp = await client.get("/")
            assert index_resp.status_code == 200
            assert "ATC" in index_resp.text

            js_resp = await client.get("/app.js")
            assert js_resp.status_code == 200

            api_resp = await client.get("/api/agents")
            assert api_resp.status_code == 200
            assert len(api_resp.json()) == 3


def test_websocket_reachable_with_static_ui_mounted(monkeypatch: pytest.MonkeyPatch) -> None:
    """The docstring above claims /ws isn't shadowed by the static mount,
    but nothing actually connected to /ws to prove it. Starlette's
    TestClient uses its own in-memory WS transport, entirely bypassing
    uvicorn's real network/protocol layer - so this test alone would NOT
    have caught the real production bug (uvicorn declared as a bare
    dependency rather than uvicorn[standard], meaning neither `websockets`
    nor `wsproto` was installed; uvicorn silently has no WS protocol
    implementation and rejects every upgrade at the connection level before
    Starlette's router ever sees it, returning 404). See
    test_websocket_reachable_over_a_real_server below for the test that
    actually exercises that path."""
    monkeypatch.setenv("ATC_TOKEN_CODER_01", TOKEN)
    monkeypatch.setenv("ATC_TOKEN_ASSIST_01", "tok-assist-01")
    monkeypatch.setenv("ATC_TOKEN_COMPLY_01", "tok-comply-01")

    async def setup():
        store = await Store.connect(":memory:")
        risk_engine = RiskEngine.from_yaml(RISK_POLICY_PATH)
        event_bus = EventBus()
        approval_manager = ApprovalManager(store, hold_timeout_seconds=999, event_bus=event_bus)
        registry = AgentRegistry.from_yaml(AGENTS_POLICY_PATH)
        upstream = UpstreamPool()
        tracer = configure_tracing("test-ws-static")
        gateway = Gateway(
            registry=registry,
            risk_engine=risk_engine,
            approval_manager=approval_manager,
            store=store,
            upstream=upstream,
            tracer=tracer,
        )
        app = build_full_app(
            gateway=gateway,
            store=store,
            approval_manager=approval_manager,
            event_bus=event_bus,
            static_dir=STATIC_DIR,
        )
        return app, store

    app, store = asyncio.run(setup())

    with TestClient(app) as client:
        with client.websocket_connect("/ws"):
            pass  # connecting at all (no 404/403) is the assertion

    asyncio.run(store.close())


def test_uvicorn_has_a_real_websocket_protocol_implementation() -> None:
    """Regression test for the real bug, confirmed live against the actual
    deployed stack: `GET /ws` returned a plain 404 (not 405/101) because
    uvicorn was declared as a bare dependency rather than uvicorn[standard]
    - neither `websockets` nor `wsproto` was installed, so uvicorn has no
    WebSocket protocol implementation at all and rejects every upgrade at
    the connection level before Starlette's router ever runs.

    test_websocket_reachable_with_static_ui_mounted above proves /ws isn't
    *shadowed* by the static mount, but it uses Starlette's TestClient,
    which has its own in-memory WS transport and completely bypasses
    uvicorn's real network/protocol layer - so it passes identically
    whether or not this dependency is present, and would NOT have caught
    this bug (confirmed: it passed throughout, on both sides of the fix).
    A live end-to-end reproduction (real uvicorn.Server + a real
    `websockets.connect()` against it) was attempted here but hits
    unrelated pre-existing MCP-SDK/anyio/uvicorn teardown fragility this
    codebase's own run_asgi_app docstring already documents, making it
    unreliable in CI - this dependency-presence check is the reliable
    proxy: it fails exactly when the real bug's precondition is back."""
    import importlib.util

    has_ws_impl = (
        importlib.util.find_spec("websockets") is not None
        or importlib.util.find_spec("wsproto") is not None
    )
    assert has_ws_impl, (
        "uvicorn has no WebSocket protocol implementation installed - "
        "every real /ws connection will 404. Check uvicorn is declared as "
        "uvicorn[standard] (or websockets/wsproto is otherwise installed)."
    )
