"""Spike S1: upstream MCP tool server (stand-in for tools-db).

Exposes two raw tools - query (safe) and execute (destructive-shaped) - that
the gateway will discover via tools/list and namespace as db__query /
db__execute. Streamable HTTP transport, its own OS process on port 9001.

Execution here happens *after* the gateway's hold decision, so this
process's own timeouts are sized normally - it never has to survive the
120s approval wait, only the gateway does.
"""

from __future__ import annotations

from opentelemetry import propagate

from common import setup_tracing
from mcp.server.fastmcp import Context, FastMCP

tracer = setup_tracing("upstream")
mcp = FastMCP("atc-spike-tools-db", host="127.0.0.1", port=9001)


def _extract_traceparent(ctx: Context) -> dict[str, str]:
    meta = ctx.request_context.meta
    traceparent = getattr(meta, "traceparent", None) if meta else None
    return {"traceparent": traceparent} if traceparent else {}


@mcp.tool(structured_output=False)
async def query(sql: str, ctx: Context) -> str:
    parent = propagate.extract(_extract_traceparent(ctx))
    with tracer.start_as_current_span("tool.query", context=parent) as span:
        span.set_attribute("db.statement", sql)
        return f"upstream query executed: {sql!r} -> 3 rows"


@mcp.tool(structured_output=False)
async def execute(sql: str, ctx: Context) -> str:
    parent = propagate.extract(_extract_traceparent(ctx))
    with tracer.start_as_current_span("tool.execute", context=parent) as span:
        span.set_attribute("db.statement", sql)
        return f"upstream execute ran: {sql!r} -> ok"


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
