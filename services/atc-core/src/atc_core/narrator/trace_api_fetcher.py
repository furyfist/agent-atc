"""Trace API span source for the Narrator. See PROJECT_PLAN.md S8's fallback
chain: primary SigNoz MCP server, fallback Trace API
(`POST /api/v5/query_range` with `SIGNOZ-API-KEY`), emergency cached text.

Spike S3 confirmed the endpoint and auth header are live and correctly wired
(a bad key returns a clean 401 `unauthenticated`, not a 404/routing
fallback) - self-hosted SigNoz's `/api/v1/register` first-run flow was
completed to unblock OTLP ingestion, but minting a real API key requires
the browser UI (Settings -> API Keys), which no automated agent in this
environment can drive. This fetcher is the code-complete fallback path
described in S8; wiring a real `SIGNOZ_API_KEY` into `.env` is what remains.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

from atc_core.narrator.span_fetcher import SpanRecord

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_LOOKBACK_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True)
class TraceApiSpanFetcher:
    """Fetches a trace's spans from SigNoz's Trace API. Fire-and-forget by
    construction (S9): any failure (network, auth, malformed response)
    returns an empty list rather than raising, so a down/misconfigured
    SigNoz degrades the Narrator to its next fallback instead of crashing
    the /api/narrate request.

    `transport` is injectable (defaults to a real httpx transport) so tests
    can pin this class's own contract - auth header, request shape,
    fire-and-forget on failure - against an httpx.MockTransport without
    needing a live SigNoz to assert against.
    """

    base_url: str
    api_key: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    lookback_seconds: float = DEFAULT_LOOKBACK_SECONDS
    transport: httpx.AsyncBaseTransport | None = field(default=None)

    async def fetch_spans(self, trace_id: str) -> list[SpanRecord]:
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - int(self.lookback_seconds * 1000)
        body = {
            "start": start_ms,
            "end": now_ms,
            "requestType": "raw",
            "compositeQuery": {
                "queryType": "builder",
                "panelType": "trace",
                "builderQueries": {
                    "A": {
                        "queryName": "A",
                        "dataSource": "traces",
                        "expression": "A",
                        "filter": {
                            "expression": f'trace_id = "{trace_id}"',
                        },
                    }
                },
            },
        }
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout_seconds, transport=self.transport
            ) as client:
                resp = await client.post(
                    "/api/v5/query_range",
                    json=body,
                    headers={"SIGNOZ-API-KEY": self.api_key},
                )
                resp.raise_for_status()
                payload = resp.json()
        except (httpx.HTTPError, ValueError):
            return []

        return _spans_from_response(payload)


def _spans_from_response(payload: dict) -> list[SpanRecord]:
    """SigNoz's raw trace query response shape: data.result[*].list[*].data,
    each with span-level fields (name, timestamp, and *_ tag attributes).
    Tolerant of missing/renamed keys - a partial parse (a subset of spans,
    or none) degrades the narration rather than raising into the caller."""
    spans: list[SpanRecord] = []
    results = (payload.get("data") or {}).get("result") or []
    for result in results:
        for row in result.get("list") or []:
            data = row.get("data") or {}
            name = data.get("name") or data.get("spanName") or "unknown_span"
            timestamp = _parse_timestamp(data.get("timestamp") or row.get("timestamp"))
            attributes = {
                k: v
                for k, v in data.items()
                if k not in ("name", "spanName", "timestamp") and v is not None
            }
            spans.append(SpanRecord(name=name, timestamp=timestamp, attributes=attributes))

    spans.sort(key=lambda s: s.timestamp)
    return spans


def _parse_timestamp(value: object) -> float:
    if isinstance(value, (int, float)):
        # SigNoz timestamps are nanoseconds since epoch for trace data.
        return float(value) / 1e9 if value > 1e12 else float(value)
    return 0.0
