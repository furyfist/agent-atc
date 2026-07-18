#!/usr/bin/env python3
"""Experiment #2 (scope violation) from BLOG_EVIDENCE_PLAN.md.

assist-01's scope is [email, fs] (policies/agents.yaml) - no db. Calls
db__query directly against the gateway, synthetically (no LLM/Groq
involved), to trigger a SCOPE_VIOLATION denial before any risk assessment
or `actions` row is ever created - contrast against experiment #6 (creep),
which is an in-scope-but-never-touched resource, a different mechanism
with a similar-looking UI signal.

Usage:
  docker exec atc-atc-core-1 //app/.venv/bin/python3 /tmp/trigger_scope_violation.py
"""

import asyncio
import os

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

GATEWAY_URL = os.environ.get("ATC_GATEWAY_URL", "http://localhost:8000/mcp/")
TOKEN = os.environ["ATC_TOKEN_ASSIST_01"]


async def main() -> None:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with streamablehttp_client(GATEWAY_URL, headers=headers, sse_read_timeout=30) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = sorted(t.name for t in tools.tools)
            print(f"assist-01 sees these tools (tools/list scope check): {names}")

            try:
                result = await session.call_tool("db__query", {"sql": "SELECT 1"})
                text = result.content[0].text if result.content else ""
                print(f"db__query call result: {text!r}")
            except Exception as exc:  # noqa: BLE001 - want to see the raw MCP error shape
                print(f"db__query call raised: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
