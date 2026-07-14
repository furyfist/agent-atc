"""Integration tests: a real MCP client against a real tools-fs server
writing to a real (temp, sandboxed) directory. See PROJECT_PLAN.md S4.
"""

from __future__ import annotations

from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from server_helpers import free_port, run_asgi_app
from tools_fs.server import build_server


async def _connect(port: int):
    return streamablehttp_client(f"http://127.0.0.1:{port}/mcp", sse_read_timeout=30)


async def test_write_then_read_roundtrip(tmp_path: Path) -> None:
    port = free_port()
    app = build_server(root=tmp_path, port=port).streamable_http_app()

    async with run_asgi_app(app, "127.0.0.1", port):
        async with await _connect(port) as (read, write, _), ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            assert {"read", "write", "delete"} <= {t.name for t in tools.tools}

            write_result = await session.call_tool("write", {"path": "notes.txt", "content": "hello"})
            assert "wrote" in write_result.content[0].text

            read_result = await session.call_tool("read", {"path": "notes.txt"})
            assert read_result.content[0].text == "hello"

            assert (tmp_path / "notes.txt").read_text() == "hello"


async def test_write_creates_nested_directories(tmp_path: Path) -> None:
    port = free_port()
    app = build_server(root=tmp_path, port=port).streamable_http_app()

    async with run_asgi_app(app, "127.0.0.1", port):
        async with await _connect(port) as (read, write, _), ClientSession(read, write) as session:
            await session.initialize()
            await session.call_tool("write", {"path": "a/b/c/notes.txt", "content": "nested"})
            assert (tmp_path / "a" / "b" / "c" / "notes.txt").read_text() == "nested"


async def test_read_missing_file_returns_error_text(tmp_path: Path) -> None:
    port = free_port()
    app = build_server(root=tmp_path, port=port).streamable_http_app()

    async with run_asgi_app(app, "127.0.0.1", port):
        async with await _connect(port) as (read, write, _), ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("read", {"path": "nope.txt"})
            assert "error" in result.content[0].text.lower()


async def test_delete_then_read_returns_error(tmp_path: Path) -> None:
    port = free_port()
    app = build_server(root=tmp_path, port=port).streamable_http_app()

    async with run_asgi_app(app, "127.0.0.1", port):
        async with await _connect(port) as (read, write, _), ClientSession(read, write) as session:
            await session.initialize()
            await session.call_tool("write", {"path": "temp.txt", "content": "x"})
            delete_result = await session.call_tool("delete", {"path": "temp.txt"})
            assert "deleted" in delete_result.content[0].text

            read_result = await session.call_tool("read", {"path": "temp.txt"})
            assert "error" in read_result.content[0].text.lower()


async def test_path_traversal_via_mcp_call_is_blocked(tmp_path: Path) -> None:
    port = free_port()
    app = build_server(root=tmp_path, port=port).streamable_http_app()

    async with run_asgi_app(app, "127.0.0.1", port):
        async with await _connect(port) as (read, write, _), ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("read", {"path": "../../../../etc/passwd"})
            assert "error" in result.content[0].text.lower()
            assert "escapes sandboxed root" in result.content[0].text
