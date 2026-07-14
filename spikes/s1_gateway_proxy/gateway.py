"""Spike S1: minimal MCP gateway proxy (stand-in for atc-core's gateway).

Proves three things in one process pair, per PROJECT_PLAN.md S1:
  1. Dynamic tools/list aggregation from an upstream MCP server at startup,
     served under a namespaced union (db__query, db__execute).
  2. W3C traceparent carried in MCP _meta, extracted on the way in and
     re-injected on the way out, so the gateway's own span is a real child
     of the agent's mission span and the upstream's span is a child of the
     gateway's.
  3. db__execute is held for the full 120s and survives every timeout in
     the chain (this process's own asyncio wait, uvicorn's keep-alive, and
     the upstream httpx client) before auto-denying.

MCP server to the agent, MCP client to upstream - matches PROJECT_PLAN.md S5.
Built on the lowlevel Server (not FastMCP) because dynamic tool aggregation
and per-call _meta access don't fit the decorator-based high-level API.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta

import mcp.types as types
import uvicorn
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from opentelemetry import propagate, trace
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send

from common import setup_tracing

UPSTREAM_URL = "http://127.0.0.1:9001/mcp"
NAMESPACE = "db"
HELD_TOOLS = {f"{NAMESPACE}__execute"}
HOLD_TIMEOUT_SECONDS = 120

tracer = setup_tracing("gateway")
server = Server("atc-spike-gateway")

# Populated at startup from the upstream tools/list response.
namespaced_tools: list[types.Tool] = []
upstream_name_of: dict[str, str] = {}
upstream_session: ClientSession | None = None


async def _connect_upstream() -> tuple[ClientSession, object]:
    """Connect to upstream with retries - it may not have bound its port yet."""
    last_error: Exception | None = None
    for attempt in range(20):
        try:
            client_cm = streamablehttp_client(UPSTREAM_URL, sse_read_timeout=300)
            read, write, _ = await client_cm.__aenter__()
            session = ClientSession(read, write)
            await session.__aenter__()
            await session.initialize()
            return session, client_cm
        except Exception as exc:  # noqa: BLE001 - retry loop, log and back off
            last_error = exc
            await asyncio.sleep(0.5)
    raise RuntimeError(f"could not connect to upstream after retries: {last_error}")


@asynccontextmanager
async def lifespan(_app: Starlette):
    global upstream_session, namespaced_tools, upstream_name_of

    session, client_cm = await _connect_upstream()
    upstream_session = session

    tools_result = await session.list_tools()
    for tool in tools_result.tools:
        namespaced_name = f"{NAMESPACE}__{tool.name}"
        upstream_name_of[namespaced_name] = tool.name
        namespaced_tools.append(tool.model_copy(update={"name": namespaced_name}))
    print(f"[gateway] aggregated tools from upstream: {list(upstream_name_of)}", flush=True)

    # Stateful: agents hold one long-lived MCP session per mission in the real
    # gateway too, so the spike should exercise the same session lifecycle.
    session_manager = StreamableHTTPSessionManager(app=server, stateless=False)
    async with session_manager.run():
        _app.state.session_manager = session_manager
        yield

    await session.__aexit__(None, None, None)
    await client_cm.__aexit__(None, None, None)


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return namespaced_tools


def _extract_traceparent_context() -> object:
    meta = server.request_context.meta
    traceparent = getattr(meta, "traceparent", None) if meta else None
    carrier = {"traceparent": traceparent} if traceparent else {}
    return propagate.extract(carrier)


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    parent_ctx = _extract_traceparent_context()

    with tracer.start_as_current_span(f"atc.gate.{name}", context=parent_ctx) as gate_span:
        if name not in upstream_name_of:
            return [types.TextContent(type="text", text=f"[ATC-ERROR] unknown tool {name}")]

        gate_span.set_attribute("atc.resource.name", name)

        if name in HELD_TOOLS:
            action_id = str(uuid.uuid4())
            with tracer.start_as_current_span("atc.interception") as hold_span:
                hold_span.set_attribute("atc.action_id", action_id)

            print(f"[gateway] HELD action_id={action_id} tool={name} - waiting up to {HOLD_TIMEOUT_SECONDS}s", flush=True)
            event = asyncio.Event()  # never set in this spike - proves the full-duration timeout path
            start = time.monotonic()
            with tracer.start_as_current_span("atc.approval_wait") as wait_span:
                wait_span.set_attribute("atc.action_id", action_id)
                try:
                    await asyncio.wait_for(event.wait(), timeout=HOLD_TIMEOUT_SECONDS)
                    approved = True
                except TimeoutError:
                    approved = False
                wait_span.set_attribute("atc.decision", "approved" if approved else "denied")
            elapsed = time.monotonic() - start
            print(f"[gateway] HOLD_RESOLVED action_id={action_id} approved={approved} elapsed={elapsed:.1f}s", flush=True)

            if not approved:
                return [
                    types.TextContent(
                        type="text",
                        text=(
                            f"[ATC-DENIED] reason=hold_timeout policy_rule=SPIKE-S1-HOLD action_id={action_id}. "
                            "Blocked by governance. You may propose a safer alternative."
                        ),
                    )
                ]

        with tracer.start_as_current_span("atc.execution"):
            outgoing_carrier: dict[str, str] = {}
            propagate.inject(outgoing_carrier)
            assert upstream_session is not None
            result = await upstream_session.call_tool(
                upstream_name_of[name], arguments, meta=outgoing_carrier
            )
            return list(result.content)


async def handle_streamable_http(scope: Scope, receive: Receive, send: Send) -> None:
    session_manager: StreamableHTTPSessionManager = scope["app"].state.session_manager
    await session_manager.handle_request(scope, receive, send)


app = Starlette(routes=[Mount("/mcp", app=handle_streamable_http)], lifespan=lifespan)


if __name__ == "__main__":
    # timeout_keep_alive generous per the timeout-chain law (S5): a 120s hold
    # only survives if every hop in the chain tolerates it.
    uvicorn.run(app, host="127.0.0.1", port=9000, timeout_keep_alive=170, log_level="warning")
