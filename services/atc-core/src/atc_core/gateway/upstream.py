"""Upstream MCP client pool: one persistent connection per tool namespace
(e.g. "db" -> tools-db), aggregated into the gateway's namespaced tool union
and routed back on call. See PROJECT_PLAN.md S5.

Generalizes the pattern proven in spikes/s1_gateway_proxy/gateway.py to
multiple upstream servers instead of one.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass

import mcp.types as types
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client


@dataclass(frozen=True)
class NamespacedTool:
    namespaced_name: str
    namespace: str
    upstream_name: str
    tool: types.Tool


class UpstreamPool:
    def __init__(self) -> None:
        self._exit_stack = AsyncExitStack()
        self._sessions: dict[str, ClientSession] = {}  # namespace -> session
        self._tools: dict[str, NamespacedTool] = {}  # namespaced_name -> entry

    async def connect(
        self,
        upstream_urls: dict[str, str],
        *,
        connect_retries: int = 20,
        retry_delay: float = 0.5,
    ) -> None:
        """`upstream_urls` maps namespace -> MCP Streamable HTTP URL, e.g.
        {"db": "http://tools-db:9001/mcp"}. Retries each connection - an
        upstream tool server may not have bound its port yet."""
        for namespace, url in upstream_urls.items():
            session = await self._connect_one(url, connect_retries, retry_delay)
            self._sessions[namespace] = session

            tools_result = await session.list_tools()
            for tool in tools_result.tools:
                namespaced_name = f"{namespace}__{tool.name}"
                self._tools[namespaced_name] = NamespacedTool(
                    namespaced_name=namespaced_name,
                    namespace=namespace,
                    upstream_name=tool.name,
                    tool=tool.model_copy(update={"name": namespaced_name}),
                )

    async def _connect_one(self, url: str, retries: int, delay: float) -> ClientSession:
        last_error: Exception | None = None
        for _ in range(retries):
            try:
                read, write, _ = await self._exit_stack.enter_async_context(
                    streamablehttp_client(url, sse_read_timeout=300)
                )
                session = await self._exit_stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                return session
            except Exception as exc:  # noqa: BLE001 - readiness retry loop
                last_error = exc
                await asyncio.sleep(delay)
        raise RuntimeError(f"could not connect to upstream {url}: {last_error}")

    def list_tools(self) -> list[types.Tool]:
        return [entry.tool for entry in self._tools.values()]

    def resolve(self, namespaced_name: str) -> NamespacedTool | None:
        return self._tools.get(namespaced_name)

    async def call_tool(
        self, namespaced_name: str, arguments: dict, *, meta: dict[str, str] | None = None
    ) -> types.CallToolResult:
        entry = self._tools.get(namespaced_name)
        if entry is None:
            raise KeyError(namespaced_name)
        session = self._sessions[entry.namespace]
        return await session.call_tool(entry.upstream_name, arguments, meta=meta)

    async def close(self) -> None:
        await self._exit_stack.aclose()
