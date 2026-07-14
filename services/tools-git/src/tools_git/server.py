"""tools-git: mock MCP server for git__push, git__force_push. See
PROJECT_PLAN.md S4. Nice-to-Have class - first to cut under pressure per S10's
descope ladder.
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from tools_git.repo import InMemoryRepo


def build_server(repo: InMemoryRepo | None = None, *, host: str | None = None, port: int | None = None) -> FastMCP:
    state = repo or InMemoryRepo()

    resolved_host = host or os.environ.get("ATC_GIT_HOST", "127.0.0.1")
    resolved_port = port if port is not None else int(os.environ.get("ATC_GIT_PORT", "9003"))
    mcp = FastMCP("tools-git", host=resolved_host, port=resolved_port)

    @mcp.tool(structured_output=False)
    async def push(branch: str, message: str) -> str:
        return state.push(branch, message)

    @mcp.tool(structured_output=False)
    async def force_push(branch: str, message: str) -> str:
        return state.force_push(branch, message)

    return mcp


if __name__ == "__main__":
    build_server().run(transport="streamable-http")
