"""Test-only ASGI runner. Duplicated from atc-core's gateway_helpers.py - see
that file's docstring for why teardown must be shutdown+cancel+settle-delay,
not just should_exit."""

from __future__ import annotations

import asyncio
import socket
from contextlib import asynccontextmanager

import httpx
import uvicorn


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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
