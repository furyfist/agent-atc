"""Spike S1: minimal agent MCP client (stand-in for agent-runner).

Starts the mission root span, calls tools/list through the gateway to check
namespaced aggregation, makes one normal (AUTO_ALLOW) call and one held call,
and times the held call to confirm it actually ran the full ~120s rather than
being cut short by a client-side timeout.

Per the timeout-chain law (S5), the agent-side MCP client request timeout
must be >= 150s or the hold will fail before the gateway even gets to
auto-deny at 120s.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import AsyncExitStack
from datetime import timedelta

from opentelemetry import propagate

from common import setup_tracing
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

GATEWAY_URL = "http://127.0.0.1:9000/mcp"
AGENT_CLIENT_TIMEOUT = timedelta(seconds=170)  # >= 150s per the timeout-chain law


async def main() -> None:
    tracer = setup_tracing("agent")

    # AsyncExitStack (not manual __aenter__/__aexit__) so cleanup always runs
    # in this same task on any exit path - splitting entry/exit across code
    # paths corrupts anyio's cancel-scope tracking on the exception path.
    async with AsyncExitStack() as stack:
        read = write = None
        for attempt in range(20):
            try:
                read, write, _ = await stack.enter_async_context(
                    streamablehttp_client(GATEWAY_URL, sse_read_timeout=300)
                )
                break
            except Exception:  # noqa: BLE001 - gateway may still be starting
                if attempt == 19:
                    raise
                await asyncio.sleep(0.5)

        session = await stack.enter_async_context(
            ClientSession(read, write, read_timeout_seconds=AGENT_CLIENT_TIMEOUT)
        )
        await session.initialize()

        with tracer.start_as_current_span("agent.mission") as mission_span:
            trace_id_hex = format(mission_span.get_span_context().trace_id, "032x")
            print(f"[agent] mission trace_id={trace_id_hex}", flush=True)

            tools_result = await session.list_tools()
            tool_names = sorted(t.name for t in tools_result.tools)
            print(f"[agent] aggregated tools: {tool_names}", flush=True)
            assert "db__query" in tool_names, "dynamic tools/list aggregation failed"
            assert "db__execute" in tool_names, "dynamic tools/list aggregation failed"

            with tracer.start_as_current_span("mcp.tool.call db__query"):
                carrier: dict[str, str] = {}
                propagate.inject(carrier)
                result = await session.call_tool("db__query", {"sql": "SELECT * FROM staging"}, meta=carrier)
                text = result.content[0].text if result.content else ""
                print(f"[agent] db__query -> {text}", flush=True)
                assert "upstream query executed" in text

            with tracer.start_as_current_span("mcp.tool.call db__execute"):
                carrier = {}
                propagate.inject(carrier)
                start = time.monotonic()
                result = await session.call_tool(
                    "db__execute", {"sql": "DROP TABLE staging"}, meta=carrier
                )
                elapsed = time.monotonic() - start
                text = result.content[0].text if result.content else ""
                print(f"[agent] db__execute elapsed={elapsed:.1f}s -> {text}", flush=True)
                assert "[ATC-DENIED]" in text, "expected auto-deny after hold timeout"
                assert 115 <= elapsed <= 135, f"hold did not run the full ~120s (got {elapsed:.1f}s)"

    print("[agent] SPIKE_RESULT=PASS", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
