#!/usr/bin/env python3
"""Synthetic loop-suspicion trigger (experiment #5 from BLOG_EVIDENCE_PLAN.md).

Fires the same fs__read call 4x in quick succession as coder-01, directly
against the gateway's MCP endpoint - no LLM involved. LoopDetector's
DEFAULT_REPEAT_THRESHOLD is 3 within a 180s window, so the 4th identical
call should push atc_loops_suspected_total and emit an atc.loop_suspected
span event.

Usage (inside the atc-core container, which has the `mcp` package and
network access to the gateway):
  docker exec atc-atc-core-1 python3 /tmp/trigger_loop_suspicion.py
"""

import asyncio
import os

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

GATEWAY_URL = os.environ.get("ATC_GATEWAY_URL", "http://localhost:8000/mcp/")
TOKEN = os.environ["ATC_TOKEN_CODER_01"]


async def main() -> None:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with streamablehttp_client(GATEWAY_URL, headers=headers, sse_read_timeout=30) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for i in range(4):
                result = await session.call_tool("fs__read", {"path": "loop-bait.txt"})
                text = result.content[0].text if result.content else ""
                print(f"call {i + 1}: {text!r}")


if __name__ == "__main__":
    asyncio.run(main())
