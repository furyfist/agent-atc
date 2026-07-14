"""tools-fs: real MCP server for fs__read, fs__write, fs__delete on a
dedicated, sandboxed volume. See PROJECT_PLAN.md S4.

`structured_output=False` on every tool - FastMCP otherwise derives an
outputSchema from a bare `-> str` return annotation and then rejects plain
text results against it (found the hard way in spike S1).
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from tools_fs.sandbox import PathEscapesSandboxError, resolve_safe_path

DEFAULT_VOLUME = Path(__file__).resolve().parents[2] / "volume"


def build_server(root: Path | None = None, *, host: str | None = None, port: int | None = None) -> FastMCP:
    volume_root = root or Path(os.environ.get("ATC_FS_ROOT", DEFAULT_VOLUME))
    volume_root.mkdir(parents=True, exist_ok=True)

    resolved_host = host or os.environ.get("ATC_FS_HOST", "127.0.0.1")
    resolved_port = port if port is not None else int(os.environ.get("ATC_FS_PORT", "9002"))
    mcp = FastMCP("tools-fs", host=resolved_host, port=resolved_port)

    @mcp.tool(structured_output=False)
    async def read(path: str) -> str:
        try:
            target = resolve_safe_path(volume_root, path)
        except PathEscapesSandboxError as exc:
            return f"error: {exc}"
        if not target.is_file():
            return f"error: no such file: {path!r}"
        return target.read_text(encoding="utf-8")

    @mcp.tool(structured_output=False)
    async def write(path: str, content: str) -> str:
        try:
            target = resolve_safe_path(volume_root, path)
        except PathEscapesSandboxError as exc:
            return f"error: {exc}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"wrote {len(content)} bytes to {path!r}"

    @mcp.tool(structured_output=False)
    async def delete(path: str) -> str:
        try:
            target = resolve_safe_path(volume_root, path)
        except PathEscapesSandboxError as exc:
            return f"error: {exc}"
        if not target.is_file():
            return f"error: no such file: {path!r}"
        target.unlink()
        return f"deleted {path!r}"

    return mcp


if __name__ == "__main__":
    build_server().run(transport="streamable-http")
