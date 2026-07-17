"""Integration tests for the ATC gateway: scope enforcement (twice), bearer-
token identity, risk-based AUTO_ALLOW/HELD, approve/deny/expire, quarantine,
and W3C trace propagation end-to-end through a real upstream MCP server.
See PROJECT_PLAN.md S5.

Gateway setup/teardown is a plain `async with gateway_context(...)` used
inside each test rather than a yield-based pytest fixture. anyio's cancel
scopes (used internally by the MCP SDK's streamable_http client) are bound to
the exact asyncio.Task that entered them; pytest-asyncio drives a yield
fixture's pre- and post-yield halves via separate `run_until_complete` calls,
which can land on different Tasks and trips "Attempted to exit cancel scope
in a different task than it was entered in" on teardown even though the
resource itself is used correctly. Keeping setup-through-teardown inside one
`async with` block in the test body keeps it all on one Task.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from opentelemetry import propagate, trace

from atc_core.approval import ApprovalManager
from atc_core.gateway import AgentRegistry, Gateway, UpstreamPool, build_asgi_app
from atc_core.risk import RiskEngine
from atc_core.store import ActionStatus, Store
from atc_telemetry import configure_tracing

from gateway_helpers import build_mock_db_server, build_mock_fs_server, free_port, run_asgi_app

REPO_ROOT = Path(__file__).resolve().parents[3]
RISK_POLICY_PATH = REPO_ROOT / "policies" / "risk_rules.yaml"
AGENTS_POLICY_PATH = REPO_ROOT / "policies" / "agents.yaml"

FAST_HOLD_TIMEOUT = 0.2

TOKENS = {
    "coder-01": "tok-coder-01",
    "assist-01": "tok-assist-01",
    "comply-01": "tok-comply-01",
}


@dataclass
class GatewayHandle:
    store: Store
    approval_manager: ApprovalManager
    gateway_url: str


@asynccontextmanager
async def gateway_context(
    monkeypatch: pytest.MonkeyPatch, *, token_budget: float | None = None
) -> AsyncIterator[GatewayHandle]:
    monkeypatch.setenv("ATC_TOKEN_CODER_01", TOKENS["coder-01"])
    monkeypatch.setenv("ATC_TOKEN_ASSIST_01", TOKENS["assist-01"])
    monkeypatch.setenv("ATC_TOKEN_COMPLY_01", TOKENS["comply-01"])

    db_port, fs_port, gateway_port = free_port(), free_port(), free_port()
    db_app = build_mock_db_server(db_port).streamable_http_app()
    fs_app = build_mock_fs_server(fs_port).streamable_http_app()

    async with run_asgi_app(db_app, "127.0.0.1", db_port), run_asgi_app(fs_app, "127.0.0.1", fs_port):
        store = await Store.connect(":memory:")
        risk_engine = RiskEngine.from_yaml(RISK_POLICY_PATH)
        approval_manager = ApprovalManager(store, hold_timeout_seconds=FAST_HOLD_TIMEOUT)
        registry = AgentRegistry.from_yaml(AGENTS_POLICY_PATH)

        upstream = UpstreamPool()
        await upstream.connect(
            {"db": f"http://127.0.0.1:{db_port}/mcp", "fs": f"http://127.0.0.1:{fs_port}/mcp"}
        )

        tracer = configure_tracing("test-gateway")
        gateway = Gateway(
            registry=registry,
            risk_engine=risk_engine,
            approval_manager=approval_manager,
            store=store,
            upstream=upstream,
            tracer=tracer,
            token_budget=token_budget,
        )
        app = build_asgi_app(gateway)

        async with run_asgi_app(app, "127.0.0.1", gateway_port):
            try:
                yield GatewayHandle(
                    store=store,
                    approval_manager=approval_manager,
                    gateway_url=f"http://127.0.0.1:{gateway_port}/mcp",
                )
            finally:
                await upstream.close()
                await store.close()


@asynccontextmanager
async def connect_as(gateway_url: str, agent_id: str | None):
    token = TOKENS.get(agent_id) if agent_id else None
    headers = {"Authorization": f"Bearer {token}"} if token else None
    async with streamablehttp_client(gateway_url, headers=headers, sse_read_timeout=30) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def _text(result) -> str:
    return result.content[0].text if result.content else ""


async def _wait_for_pending_action(store: Store, timeout: float = 2.0, poll_interval: float = 0.01):
    """Polls instead of a single fixed sleep - a blind sleep just short of
    the real round-trip time (client -> gateway -> risk engine -> SQLite
    insert) is flaky under load; polling is both faster on the common path
    and robust against slower runs."""
    elapsed = 0.0
    while elapsed < timeout:
        pending = await store.list_actions(status=ActionStatus.PENDING)
        if pending:
            return pending
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
    raise AssertionError(f"no PENDING action appeared within {timeout}s")


# --- tools/list scope enforcement -------------------------------------------


async def test_coder_sees_its_in_scope_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    async with gateway_context(monkeypatch) as gw, connect_as(gw.gateway_url, "coder-01") as session:
        tools = await session.list_tools()
        names = {t.name for t in tools.tools}
        assert {"db__query", "db__execute", "fs__read", "fs__write", "fs__delete"} <= names


async def test_comply_sees_only_fs_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    async with gateway_context(monkeypatch) as gw, connect_as(gw.gateway_url, "comply-01") as session:
        tools = await session.list_tools()
        names = {t.name for t in tools.tools}
        assert names == {"fs__read", "fs__write", "fs__delete"}
        assert "db__query" not in names


async def test_unauthenticated_client_sees_no_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    async with gateway_context(monkeypatch) as gw, connect_as(gw.gateway_url, None) as session:
        tools = await session.list_tools()
        assert tools.tools == []


# --- tools/call: identity and scope ------------------------------------------


async def test_unauthenticated_call_is_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    async with gateway_context(monkeypatch) as gw, connect_as(gw.gateway_url, None) as session:
        result = await session.call_tool("db__query", {"sql": "SELECT 1"})
        assert "[ATC-DENIED] reason=unauthenticated" in _text(result)


async def test_out_of_scope_call_is_denied_even_if_not_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    """S5: scope is enforced *twice* - at list and at call. comply-01 never
    sees db__query in tools/list, but a client could still send the raw
    call; the server must independently reject it."""
    async with gateway_context(monkeypatch) as gw, connect_as(gw.gateway_url, "comply-01") as session:
        result = await session.call_tool("db__query", {"sql": "SELECT 1"})
        assert "[ATC-DENIED] reason=scope_violation" in _text(result)


# --- risk-based AUTO_ALLOW / HELD --------------------------------------------


async def test_low_risk_call_auto_allowed_and_executes(monkeypatch: pytest.MonkeyPatch) -> None:
    async with gateway_context(monkeypatch) as gw, connect_as(gw.gateway_url, "coder-01") as session:
        result = await session.call_tool("db__query", {"sql": "SELECT * FROM staging_old"})
        text = _text(result)
        assert "query executed" in text
        assert "[ATC-DENIED]" not in text


async def test_high_risk_call_is_held_then_approved(monkeypatch: pytest.MonkeyPatch) -> None:
    async with gateway_context(monkeypatch) as gw, connect_as(gw.gateway_url, "coder-01") as session:
        call_task = asyncio.create_task(
            session.call_tool("db__execute", {"sql": "DROP TABLE customers"})
        )
        pending = await _wait_for_pending_action(gw.store)
        assert len(pending) == 1
        action_id = pending[0].action_id

        await gw.approval_manager.decide(action_id, approved=True, decided_by="tester")
        result = await call_task
        text = _text(result)
        assert "execute ran" in text
        assert "[ATC-DENIED]" not in text


async def test_high_risk_call_is_held_then_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    async with gateway_context(monkeypatch) as gw, connect_as(gw.gateway_url, "coder-01") as session:
        call_task = asyncio.create_task(
            session.call_tool("db__execute", {"sql": "DROP TABLE customers"})
        )
        pending = await _wait_for_pending_action(gw.store)
        action_id = pending[0].action_id
        await gw.approval_manager.decide(action_id, approved=False, decided_by="tester")

        result = await call_task
        text = _text(result)
        assert "[ATC-DENIED] reason=denied_by_human" in text
        assert "policy_rule=SQL-PROD-TABLE-HIGH" in text
        assert "You may propose a safer alternative" in text


async def test_high_risk_call_expires_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    async with gateway_context(monkeypatch) as gw, connect_as(gw.gateway_url, "coder-01") as session:
        result = await session.call_tool("db__execute", {"sql": "DROP TABLE customers"})
        assert "[ATC-DENIED] reason=hold_timeout" in _text(result)


# --- quarantine --------------------------------------------------------------


async def test_quarantined_agent_is_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    async with gateway_context(monkeypatch) as gw:
        await gw.store.set_quarantined("coder-01", True)
        async with connect_as(gw.gateway_url, "coder-01") as session:
            result = await session.call_tool("db__query", {"sql": "SELECT 1"})
            assert "[ATC-QUARANTINED]" in _text(result)


# --- trace propagation --------------------------------------------------------


async def test_traceparent_propagates_from_client_into_the_stored_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with gateway_context(monkeypatch) as gw:
        tracer = trace.get_tracer("test-client")
        with tracer.start_as_current_span("test.mission") as span:
            expected_trace_id = format(span.get_span_context().trace_id, "032x")
            carrier: dict[str, str] = {}
            propagate.inject(carrier)

            async with connect_as(gw.gateway_url, "coder-01") as session:
                await session.call_tool("db__query", {"sql": "SELECT 1"}, meta=carrier)

        actions = await gw.store.list_actions()
        matching = [a for a in actions if a.tool == "db__query"]
        assert matching
        assert matching[0].trace_id == expected_trace_id


# --- token-budget circuit breaker ----------------------------------------------


async def test_budget_exhausted_agent_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    async with gateway_context(monkeypatch, token_budget=1000) as gw:
        await gw.store.set_tokens_used("coder-01", 1500)
        async with connect_as(gw.gateway_url, "coder-01") as session:
            result = await session.call_tool("db__query", {"sql": "SELECT 1"})
            text = _text(result)
            assert "[ATC-BUDGET]" in text
            assert "used=1500" in text and "budget=1000" in text


async def test_agent_under_budget_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    async with gateway_context(monkeypatch, token_budget=1000) as gw:
        await gw.store.set_tokens_used("coder-01", 999)
        async with connect_as(gw.gateway_url, "coder-01") as session:
            result = await session.call_tool("db__query", {"sql": "SELECT 1"})
            assert "[ATC-BUDGET]" not in _text(result)


async def test_no_budget_configured_means_no_breaker(monkeypatch: pytest.MonkeyPatch) -> None:
    async with gateway_context(monkeypatch) as gw:
        await gw.store.set_tokens_used("coder-01", 10_000_000)
        async with connect_as(gw.gateway_url, "coder-01") as session:
            result = await session.call_tool("db__query", {"sql": "SELECT 1"})
            assert "[ATC-BUDGET]" not in _text(result)
