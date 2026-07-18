#!/usr/bin/env python3
"""Experiment #9b (concurrent multi-agent hold queue, synthetic variant).

The Groq-driven version (scripts/concurrent_hold_queue.py) hit the daily
TPD cap twice in a row before two holds ever coexisted (see
docs/evidence/exp09-concurrent-queue.md) - the fleet's own background
loop had already spent the day's budget. This variant proves the same
"Fleet Tower shows multiple simultaneous red pending cards" moment using
direct MCP calls (zero Groq cost) from two different agents fired via
asyncio.gather, so the actual approval-queue/UI/dashboard behavior under
concurrency is still real and unscripted - only the reasoning-under-
pressure angle (which experiment #1 already covers) is out of scope here.

Usage:
  docker exec atc-atc-core-1 //app/.venv/bin/python3 /tmp/trigger_concurrent_holds_synthetic.py
"""

from __future__ import annotations

import asyncio
import os
import time

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

GATEWAY_URL = os.environ.get("ATC_GATEWAY_URL", "http://localhost:8000/mcp/")
API_BASE_URL = os.environ.get("ATC_HEARTBEAT_URL", "http://localhost:8000")
POLL_INTERVAL = 0.2


async def fire(agent_label: str, token: str, tool: str, arguments: dict) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    async with streamablehttp_client(GATEWAY_URL, headers=headers, sse_read_timeout=150) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, arguments)
            text = result.content[0].text if result.content else ""
            print(f"[{agent_label}] {tool}({arguments}) -> {text!r}")


class QueueWatcher:
    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._http = http_client
        self._last_ids: set[str] = set()
        self.max_concurrent_pending = 0
        self.snapshots: list[tuple[float, list[dict]]] = []

    async def run(self, stop_event: asyncio.Event) -> None:
        start = time.monotonic()
        while not stop_event.is_set():
            try:
                resp = await self._http.get("/api/actions", params={"status": "pending"})
                resp.raise_for_status()
                pending = resp.json()
            except httpx.HTTPError:
                await asyncio.sleep(POLL_INTERVAL)
                continue
            ids = {a["action_id"] for a in pending}
            if ids != self._last_ids:
                elapsed = time.monotonic() - start
                self.snapshots.append((elapsed, pending))
                self.max_concurrent_pending = max(self.max_concurrent_pending, len(pending))
                print(
                    f"[t={elapsed:5.1f}s] pending={len(pending)}: "
                    + ", ".join(f"{a['agent_id']}:{a['tool']}:{a['risk_level']}" for a in pending)
                )
                self._last_ids = ids
            await asyncio.sleep(POLL_INTERVAL)


async def decide_all_after(http_client: httpx.AsyncClient, delay: float) -> None:
    """Give both holds a moment to coexist on the board before deciding,
    so the simultaneous-pending moment is real and observable, not
    instantaneous."""
    await asyncio.sleep(delay)
    resp = await http_client.get("/api/actions", params={"status": "pending"})
    for action in resp.json():
        await http_client.post(
            f"/api/actions/{action['action_id']}/deny", json={"decided_by": "operator-queue-watch"}
        )
        print(f"  denied {action['action_id']} ({action['agent_id']}:{action['tool']})")


async def main() -> None:
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=10.0) as http_client:
        watcher = QueueWatcher(http_client)
        stop_event = asyncio.Event()
        watcher_task = asyncio.create_task(watcher.run(stop_event))

        print("=== Synthetic concurrent hold queue (zero Groq cost) ===\n")

        await asyncio.gather(
            fire(
                "coder-01",
                os.environ["ATC_TOKEN_CODER_01"],
                "db__execute",
                {"sql": "DROP TABLE orders"},
            ),
            fire(
                "comply-01",
                os.environ["ATC_TOKEN_COMPLY_01"],
                "fs__write",
                {"path": "credentials/rotation-log.txt", "content": "rotation complete"},
            ),
            decide_all_after(http_client, delay=3.0),
        )

        await asyncio.sleep(1.0)
        stop_event.set()
        watcher_task.cancel()
        try:
            await watcher_task
        except asyncio.CancelledError:
            pass

        print(f"\nmax concurrent pending holds observed: {watcher.max_concurrent_pending}")


if __name__ == "__main__":
    asyncio.run(main())
