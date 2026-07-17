#!/usr/bin/env python3
"""Red-team risk_rules.yaml (experiment #10 from BLOG_EVIDENCE_PLAN.md).

Fires two already-discovered, unpatched policy gaps through the live
gateway as coder-01 (scope includes db) and prints how each was classified:

  1. DELETE ... WHERE 1=1 - syntactically has a WHERE clause, so the
     SQL-UNBOUNDED-WRITE-HIGH rule's `no_where` check misses it even
     though the effect is an unbounded delete. Falls through to
     SQL-WRITE-MEDIUM.
  2. RENAME TABLE x TO y - sqlglot parses this as a generic `Command`,
     not Drop/TruncateTable/Alter/Create, so no DDL rule matches. Falls
     through to the code-level fail-closed MEDIUM default.

Both statements target a non-existent table on purpose - the point is to
observe risk classification, not to actually mutate tools-db's SQLite file.
"""

import asyncio
import os

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

GATEWAY_URL = os.environ.get("ATC_GATEWAY_URL", "http://localhost:8000/mcp/")
TOKEN = os.environ["ATC_TOKEN_CODER_01"]

STATEMENTS = [
    ("DELETE-WHERE-1-EQUALS-1", "DELETE FROM redteam_probe_table WHERE 1=1"),
    ("RENAME-TABLE", "RENAME TABLE redteam_probe_table TO redteam_probe_table_bak"),
]


async def main() -> None:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with streamablehttp_client(GATEWAY_URL, headers=headers, sse_read_timeout=30) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for label, sql in STATEMENTS:
                result = await session.call_tool("db__execute", {"sql": sql})
                text = result.content[0].text if result.content else ""
                print(f"{label}: sql={sql!r}")
                print(f"  -> {text!r}")


if __name__ == "__main__":
    asyncio.run(main())
