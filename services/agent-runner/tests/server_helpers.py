"""Test-only ASGI runner + a minimal MCP server double. Not the real gateway
- run_mission's own job (connect, loop, record results, recognize denial
text) is what these tests exercise. The risk engine's SQL classification is
already covered by atc-core's own test suite; re-testing it here would just
duplicate that coverage while adding a heavy atc-core test dependency.
"""

from __future__ import annotations

import asyncio
import socket
from contextlib import asynccontextmanager

import httpx
import uvicorn
from mcp.server.fastmcp import FastMCP


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def build_minimal_server(port: int) -> FastMCP:
    """ping always succeeds; flaky_write denies its first call (per input
    value) and succeeds on any retry - enough to exercise denial+recovery
    loop mechanics without needing the real risk engine."""
    mcp = FastMCP("test-minimal", host="127.0.0.1", port=port)
    denied_once: set[str] = set()

    @mcp.tool(structured_output=False)
    async def ping() -> str:
        return "pong"

    @mcp.tool(structured_output=False)
    async def flaky_write(value: str) -> str:
        if value not in denied_once:
            denied_once.add(value)
            return "[ATC-DENIED] reason=test_policy policy_rule=TEST-RULE. Blocked by governance."
        return f"ok: wrote {value!r}"

    return mcp


@asynccontextmanager
async def run_asgi_app(app, host: str, port: int):
    config = uvicorn.Config(app, host=host, port=port, log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        await _wait_until_up(host, port)
        yield server
    finally:
        await server.shutdown()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0.3)


async def _wait_until_up(host: str, port: int, attempts: int = 40, delay: float = 0.05) -> None:
    url = f"http://{host}:{port}/"
    async with httpx.AsyncClient() as client:
        for _ in range(attempts):
            try:
                await client.get(url, timeout=1)
                return
            except httpx.TransportError:
                await asyncio.sleep(delay)
    raise RuntimeError(f"server on {host}:{port} did not come up in time")
