"""Metric instrument setup. See PROJECT_PLAN.md S6.

Defines the exact named instruments so every service reports under the same
names/units instead of drifting. Only the gateway consumes atc_actions_total /
atc_interceptions_total / atc_approval_latency_seconds today; the rest
(atc_agent_risk_score, atc_agent_heartbeat, agent_tokens_total) are agent-
runner's, defined here now so the contract is fixed in one place.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import Counter, Histogram, MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

# The synchronous Gauge instrument has no stable public type exported by the
# SDK yet (only Meter.create_gauge() is public) - typed loosely rather than
# reaching into opentelemetry.sdk.metrics._internal.


@dataclass(frozen=True)
class AtcInstruments:
    actions_total: Counter
    interceptions_total: Counter
    approval_latency_seconds: Histogram
    agent_risk_score: Any
    agent_heartbeat: Any
    agent_tokens_total: Counter
    novel_resource_total: Counter


def configure_metrics(
    service_name: str, otlp_endpoint: str | None = None, *, export_interval_millis: int = 15000
) -> AtcInstruments:
    """Configures the global MeterProvider and returns the fixed set of named
    instruments from S6. `otlp_endpoint` defaults to OTEL_EXPORTER_OTLP_ENDPOINT
    if not passed. If neither is set, metrics are recorded but never exported
    (no reader attached) - harmless for local dev without a collector."""
    endpoint = otlp_endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    readers = []
    if endpoint:
        exporter = OTLPMetricExporter(endpoint=f"{endpoint.rstrip('/')}/v1/metrics")
        readers.append(PeriodicExportingMetricReader(exporter, export_interval_millis=export_interval_millis))

    provider = MeterProvider(resource=Resource.create({"service.name": service_name}), metric_readers=readers)
    metrics.set_meter_provider(provider)
    meter = metrics.get_meter(service_name)

    return AtcInstruments(
        actions_total=meter.create_counter(
            "atc_actions_total", unit="1", description="Tool calls by agent_id, risk, decision"
        ),
        interceptions_total=meter.create_counter(
            "atc_interceptions_total", unit="1", description="Held tool calls by agent_id"
        ),
        approval_latency_seconds=meter.create_histogram(
            "atc_approval_latency_seconds", unit="s", description="Human decision latency for held actions"
        ),
        agent_risk_score=meter.create_gauge(
            "atc_agent_risk_score", unit="1", description="EWMA risk score by agent_id"
        ),
        agent_heartbeat=meter.create_gauge(
            "atc_agent_heartbeat", unit="s", description="Last heartbeat unix timestamp by agent_id"
        ),
        agent_tokens_total=meter.create_counter(
            "agent_tokens_total", unit="1", description="LLM tokens burned by agent_id, model"
        ),
        novel_resource_total=meter.create_counter(
            "atc_novel_resource_total",
            unit="1",
            description="Permission-creep events: agent touched an in-scope resource for the first time",
        ),
    )
