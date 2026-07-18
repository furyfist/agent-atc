#!/usr/bin/env python3
"""Experiment #6 (permission creep) from BLOG_EVIDENCE_PLAN.md.

coder-01 is in-scope for fs, but has never touched this exact resource
name before - CreepDetector flags it as novel (non-gating, async-after-
the-gate-decision) and bumps the EWMA risk score +20 on the next
heartbeat recompute. Contrast with experiment #2 (scope violation): same
"the UI flags something" surface, different mechanism - creep is
in-scope-but-never-touched, a behavioral/history check, not a static
registry check.

Usage:
  docker exec atc-atc-core-1 //app/.venv/bin/python3 /tmp/trigger_permission_creep.py
"""

import asyncio
import os
import time

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

GATEWAY_URL = os.environ.get("ATC_GATEWAY_URL", "http://localhost:8000/mcp/")
TOKEN = os.environ["ATC_TOKEN_CODER_01"]
NOVEL_PATH = f"creep-probe-{int(time.time())}.txt"


async def main() -> None:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with streamablehttp_client(GATEWAY_URL, headers=headers, sse_read_timeout=30) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("fs__write", {"path": NOVEL_PATH, "content": "creep probe"})
            text = result.content[0].text if result.content else ""
            print(f"fs__write({NOVEL_PATH!r}) -> {text!r}")


if __name__ == "__main__":
    asyncio.run(main())
