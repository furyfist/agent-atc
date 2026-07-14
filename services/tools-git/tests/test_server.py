"""Integration tests: a real MCP client against a real tools-git server."""

from __future__ import annotations

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from server_helpers import free_port, run_asgi_app
from tools_git.repo import InMemoryRepo
from tools_git.server import build_server


async def _connect(port: int):
    return streamablehttp_client(f"http://127.0.0.1:{port}/mcp", sse_read_timeout=30)


async def test_tools_list_shows_push_and_force_push() -> None:
    port = free_port()
    app = build_server(port=port).streamable_http_app()

    async with run_asgi_app(app, "127.0.0.1", port):
        async with await _connect(port) as (read, write, _), ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {"push", "force_push"} <= {t.name for t in tools.tools}


async def test_push_via_mcp_call() -> None:
    port = free_port()
    repo = InMemoryRepo()
    app = build_server(repo=repo, port=port).streamable_http_app()

    async with run_asgi_app(app, "127.0.0.1", port):
        async with await _connect(port) as (read, write, _), ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("push", {"branch": "main", "message": "add feature"})
            assert "pushed to 'main'" in result.content[0].text

    assert repo.branches["main"] == ["add feature"]


async def test_force_push_via_mcp_call_rewrites_history() -> None:
    port = free_port()
    repo = InMemoryRepo()
    repo.push("main", "old commit 1")
    repo.push("main", "old commit 2")
    app = build_server(repo=repo, port=port).streamable_http_app()

    async with run_asgi_app(app, "127.0.0.1", port):
        async with await _connect(port) as (read, write, _), ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "force_push", {"branch": "main", "message": "rewritten"}
            )
            assert "history rewritten" in result.content[0].text

    assert repo.branches["main"] == ["rewritten"]
