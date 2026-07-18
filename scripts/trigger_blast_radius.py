#!/usr/bin/env python3
"""Experiment #7 (blast radius) from BLOG_EVIDENCE_PLAN.md.

Seed data is intentionally tiny (2 rows in `orders`) - not enough to
demonstrate a real, non-trivial blast-radius count. This script first
seeds ~200 extra rows into `orders` (a real, prod-tagged table per
policies/risk_rules.yaml - so the seeding INSERT is itself HIGH risk via
SQL-PROD-TABLE-HIGH and must be approved), then issues a bounded UPDATE
matching most of those rows to get a genuine large-N "~N rows affected"
estimate on the approval card before deciding it.

Synthetic (zero Groq/LLM cost) - direct MCP calls against the gateway as
coder-01, decided live via a polling LiveApprover (approves every hold,
since the point here is the blast-radius number, not a denial story).

Usage:
  docker exec atc-atc-core-1 //app/.venv/bin/python3 /tmp/trigger_blast_radius.py
"""

from __future__ import annotations

import asyncio
import os

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

GATEWAY_URL = os.environ.get("ATC_GATEWAY_URL", "http://localhost:8000/mcp/")
API_BASE_URL = os.environ.get("ATC_HEARTBEAT_URL", "http://localhost:8000")
TOKEN = os.environ["ATC_TOKEN_CODER_01"]
POLL_INTERVAL = 0.5
SEED_ROW_COUNT = 200
SEED_ID_START = 1000


class LiveApprover:
    """Approves every HIGH-risk hold for this agent, live, printing the
    blast-radius estimate captured on each pending card before deciding."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._http = http_client
        self._decided: set[str] = set()

    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                resp = await self._http.get("/api/actions", params={"status": "pending"})
                resp.raise_for_status()
                pending = resp.json()
            except httpx.HTTPError:
                await asyncio.sleep(POLL_INTERVAL)
                continue

            for action in pending:
                if action["action_id"] in self._decided:
                    continue
                await self._decide(action)

            await asyncio.sleep(POLL_INTERVAL)

    async def _decide(self, action: dict) -> None:
        action_id = action["action_id"]
        self._decided.add(action_id)
        print(
            f"\n[LIVE DECISION] pending {action_id}: {action['tool']} "
            f"risk={action['risk_level']} blast_radius={action.get('blast_radius')!r} "
            f"resource={action.get('resource_name')!r}"
        )
        resp = await self._http.post(
            f"/api/actions/{action_id}/approve", json={"decided_by": "operator-live-watch"}
        )
        print(f"  -> APPROVING  <- {resp.status_code} {resp.json().get('status')}")


async def main() -> None:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=10.0) as http_client:
        approver = LiveApprover(http_client)
        stop_event = asyncio.Event()
        approver_task = asyncio.create_task(approver.run(stop_event))

        try:
            async with streamablehttp_client(GATEWAY_URL, headers=headers, sse_read_timeout=150) as (
                read,
                write,
                _,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    values = ", ".join(
                        f"({i}, {(i % 2) + 1}, {10.0 + (i % 50)})"
                        for i in range(SEED_ID_START, SEED_ID_START + SEED_ROW_COUNT)
                    )
                    seed_sql = f"INSERT INTO orders (id, customer_id, total) VALUES {values}"
                    print(f"=== Seeding {SEED_ROW_COUNT} rows into orders (prod-tagged, HIGH, held) ===")
                    result = await session.call_tool("db__execute", {"sql": seed_sql})
                    text = result.content[0].text if result.content else ""
                    print(f"seed insert -> {text!r}")

                    print("\n=== Bounded UPDATE matching most seeded rows (real blast radius) ===")
                    update_sql = f"UPDATE orders SET total = total * 1.1 WHERE id >= {SEED_ID_START}"
                    result = await session.call_tool("db__execute", {"sql": update_sql})
                    text = result.content[0].text if result.content else ""
                    print(f"update -> {text!r}")
        finally:
            stop_event.set()
            approver_task.cancel()
            try:
                await approver_task
            except asyncio.CancelledError:
                pass


if __name__ == "__main__":
    asyncio.run(main())
