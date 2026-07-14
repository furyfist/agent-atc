"""Shared test infrastructure for gateway integration tests: an in-process
mock upstream tool server, and helpers to run a Starlette app on a background
asyncio task without spawning a subprocess (S1's spike used subprocesses;
these are permanent tests, so an in-process uvicorn.Server is faster and
avoids Windows subprocess flakiness)."""

from __future__ import annotations

import asyncio
import socket
from contextlib import asynccontextmanager

import httpx
import uvicorn
from mcp.server.fastmcp import Context, FastMCP


def free_port() -> int:
    """Allocates an OS-assigned free TCP port. Tests bind fresh ports per
    run rather than reusing fixed ones - a just-closed uvicorn socket isn't
    guaranteed to be immediately rebindable (TIME_WAIT et al), and fixed
    ports made back-to-back tests hang waiting to bind a still-held port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def build_mock_db_server(port: int) -> FastMCP:
    """Stands in for tools-db: query (safe) and execute (destructive-shaped)."""
    mcp = FastMCP("mock-tools-db", host="127.0.0.1", port=port)

    @mcp.tool(structured_output=False)
    async def query(sql: str, ctx: Context) -> str:  # noqa: ARG001 - ctx required for meta access
        return f"query executed: {sql!r} -> 3 rows"

    @mcp.tool(structured_output=False)
    async def execute(sql: str, ctx: Context) -> str:  # noqa: ARG001
        return f"execute ran: {sql!r} -> ok"

    return mcp


def build_mock_fs_server(port: int) -> FastMCP:
    """Stands in for tools-fs: read/write/delete."""
    mcp = FastMCP("mock-tools-fs", host="127.0.0.1", port=port)

    @mcp.tool(structured_output=False)
    async def read(path: str, ctx: Context) -> str:  # noqa: ARG001
        return f"read {path!r} -> file contents"

    @mcp.tool(structured_output=False)
    async def write(path: str, content: str, ctx: Context) -> str:  # noqa: ARG001
        return f"wrote {len(content)} bytes to {path!r}"

    @mcp.tool(structured_output=False)
    async def delete(path: str, ctx: Context) -> str:  # noqa: ARG001
        return f"deleted {path!r}"

    return mcp


@asynccontextmanager
async def run_asgi_app(app, host: str, port: int):
    """Runs a Starlette/FastMCP ASGI app on a background asyncio task and
    waits until it accepts connections before yielding.

    Teardown must be `server.shutdown()` (not just `should_exit = True`) plus
    cancelling the serve task plus a brief settle delay - anything looser
    leaves the mcp SDK's StreamableHTTPSessionManager in a state where the
    *next* session manager instantiated in this process silently fails to
    complete its SSE response ("ASGI callable returned without completing
    response"), reproducible with zero pytest involvement in a bare
    asyncio.run() with 2+ sequential servers. Root cause is upstream (mcp
    SDK / anyio / uvicorn interaction), not application code; this ordering
    was found empirically to make repeated instantiation in one process
    reliable."""
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
