"""Sanity tests for configure_tracing/configure_metrics: no otlp_endpoint set
must never raise or block (S9 fire-and-forget law) - it just drops telemetry.
"""

from __future__ import annotations

from atc_telemetry import configure_metrics, configure_tracing


def test_configure_tracing_without_endpoint_does_not_raise() -> None:
    tracer = configure_tracing("test-service")
    with tracer.start_as_current_span("test.span") as span:
        span.set_attribute("k", "v")
    # No exporter attached (no endpoint, no console_fallback) - just must not raise.


def test_configure_tracing_with_console_fallback() -> None:
    tracer = configure_tracing("test-service", console_fallback=True)
    with tracer.start_as_current_span("test.span"):
        pass


def test_configure_metrics_without_endpoint_returns_working_instruments() -> None:
    instruments = configure_metrics("test-service")
    instruments.actions_total.add(1, {"agent_id": "coder-01", "risk": "LOW", "decision": "AUTO_ALLOWED"})
    instruments.interceptions_total.add(1, {"agent_id": "coder-01"})
    instruments.approval_latency_seconds.record(1.5, {"agent_id": "coder-01"})
    instruments.agent_risk_score.set(12.0, {"agent_id": "coder-01"})
    instruments.agent_heartbeat.set(1000.0, {"agent_id": "coder-01"})
    instruments.agent_tokens_total.add(500, {"agent_id": "coder-01", "model": "llama-3.3-70b-versatile"})
    # No reader/exporter attached - just must not raise.


def test_configure_metrics_instrument_names() -> None:
    instruments = configure_metrics("test-service")
    assert instruments.actions_total.name == "atc_actions_total"
    assert instruments.interceptions_total.name == "atc_interceptions_total"
    assert instruments.approval_latency_seconds.name == "atc_approval_latency_seconds"
    assert instruments.agent_risk_score.name == "atc_agent_risk_score"
    assert instruments.agent_heartbeat.name == "atc_agent_heartbeat"
    assert instruments.agent_tokens_total.name == "agent_tokens_total"
