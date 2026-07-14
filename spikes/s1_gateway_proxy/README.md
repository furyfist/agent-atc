# Spike S1 - gateway proxy, traceparent propagation, 120s hold

Validates PROJECT_PLAN.md §12 S1 before the real `atc-core` gateway gets built:

1. Dynamic `tools/list` aggregation from an upstream MCP server at startup,
   served under a namespaced union (`db__query`, `db__execute`).
2. W3C `traceparent` carried in MCP `_meta`, propagated across three real OS
   processes (agent -> gateway -> upstream) so all three see the same
   `trace_id`.
3. One call (`db__execute`) held for the full 120s, surviving every timeout
   in the chain (agent MCP client, gateway/uvicorn, upstream httpx client),
   before auto-denying with the `[ATC-DENIED]` shape from PROJECT_PLAN.md §5.

This is throwaway spike code, not the real gateway - no risk engine, no
SQLite pending-row persistence, no scope enforcement. It only proves the
plumbing works before those pieces get built for real.

## Run it

```
uv sync
uv run python run_spike.py
```

Takes ~2 minutes (the held call runs the full 120s on purpose). Prints a
PASS/FAIL line per check and writes per-process logs to `logs/`.

## Result (last run)

All 6 checks pass, including the 120s hold running to completion
(elapsed=120.0s) and a shared trace_id across all three process logs.

## Gotcha found and fixed

FastMCP auto-derives an `outputSchema` from a `-> str` return-type hint and
then rejects plain-text tool results against it ("Output validation error:
outputSchema defined but no structured output returned"). Fixed by passing
`structured_output=False` to `@mcp.tool()` in `upstream_server.py` - worth
remembering when the real `tools-db`/`tools-fs` servers get built.
