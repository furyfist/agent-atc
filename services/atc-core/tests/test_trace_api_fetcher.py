"""Unit tests for the Trace API span fetcher (S8's fallback Narrator path).

The exact SigNoz v5 query_range response shape is spike S3's open item (see
trace_api_fetcher.py's module docstring) - these tests pin the fetcher's own
contract (fire-and-forget on any HTTP/parse failure, correct auth header,
tolerant row parsing) against a mocked transport rather than asserting a
live SigNoz response shape that hasn't been independently verified yet.
"""

from __future__ import annotations

import httpx

from atc_core.narrator.trace_api_fetcher import TraceApiSpanFetcher


async def test_sends_api_key_header_and_trace_id_filter() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = request.headers
        captured["body"] = request.content
        return httpx.Response(200, json={"data": {"result": []}})

    fetcher = TraceApiSpanFetcher(
        base_url="http://signoz.test", api_key="test-key", transport=httpx.MockTransport(handler)
    )

    await fetcher.fetch_spans("abc123")

    assert captured["headers"]["SIGNOZ-API-KEY"] == "test-key"
    assert b"abc123" in captured["body"]


async def test_parses_spans_from_result_rows() -> None:
    response_body = {
        "data": {
            "result": [
                {
                    "list": [
                        {
                            "data": {
                                "name": "atc.gate.db__execute",
                                "timestamp": 1_700_000_000_000_000_000,
                                "agent.id": "coder-01",
                            }
                        },
                        {
                            "data": {
                                "name": "atc.execution",
                                "timestamp": 1_700_000_001_000_000_000,
                            }
                        },
                    ]
                }
            ]
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return httpx.Response(200, json=response_body)

    fetcher = TraceApiSpanFetcher(
        base_url="http://signoz.test", api_key="k", transport=httpx.MockTransport(handler)
    )

    spans = await fetcher.fetch_spans("abc123")

    assert [s.name for s in spans] == ["atc.gate.db__execute", "atc.execution"]
    assert spans[0].attributes["agent.id"] == "coder-01"
    assert spans[0].timestamp < spans[1].timestamp


async def test_returns_empty_list_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return httpx.Response(401, json={"status": "error"})

    fetcher = TraceApiSpanFetcher(
        base_url="http://signoz.test", api_key="bad-key", transport=httpx.MockTransport(handler)
    )

    spans = await fetcher.fetch_spans("abc123")
    assert spans == []


async def test_returns_empty_list_on_malformed_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return httpx.Response(200, content=b"not json")

    fetcher = TraceApiSpanFetcher(
        base_url="http://signoz.test", api_key="k", transport=httpx.MockTransport(handler)
    )

    spans = await fetcher.fetch_spans("abc123")
    assert spans == []


async def test_returns_empty_list_on_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        raise httpx.ConnectError("connection refused")

    fetcher = TraceApiSpanFetcher(
        base_url="http://signoz.test", api_key="k", transport=httpx.MockTransport(handler)
    )

    spans = await fetcher.fetch_spans("abc123")
    assert spans == []
