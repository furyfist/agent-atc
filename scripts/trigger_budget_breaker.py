#!/usr/bin/env python3
"""Experiment #4 (token budget breaker) from BLOG_EVIDENCE_PLAN.md.

ATC_TOKEN_BUDGET was set to 1300 on atc-core (below assist-01's real,
heartbeat-reported cumulative usage of 1366 tokens from its normal
persona missions) - this call is synthetic (zero additional Groq spend),
just confirming the gate denies BEFORE dispatching to the upstream tool
once the ceiling is already crossed.

Usage:
  docker exec atc-atc-core-1 //app/.venv/bin/python3 /tmp/trigger_budget_breaker.py
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
            result = await session.call_tool("fs__read", {"path": "daily-summary.txt"})
            text = result.content[0].text if result.content else ""
            print(f"fs__read call result: {text!r}")


if __name__ == "__main__":
    asyncio.run(main())
