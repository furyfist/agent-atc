"""Tracer setup. See PROJECT_PLAN.md S6, S9.

OTLP export is fire-and-forget by construction: BatchSpanProcessor exports on
a background thread and swallows exporter failures internally, so a down or
unreachable SigNoz never blocks or raises into application code (S9: "SigNoz
down -> demo continues").
"""

from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SpanExporter


def configure_tracing(
    service_name: str,
    otlp_endpoint: str | None = None,
    *,
    console_fallback: bool = False,
) -> trace.Tracer:
    """Configures the global TracerProvider for this process and returns its
    tracer. `otlp_endpoint` defaults to the OTEL_EXPORTER_OTLP_ENDPOINT env
    var (the standard OTel convention) if not passed explicitly. If neither
    is set, spans are dropped unless `console_fallback` is set (useful for
    local debugging without a collector running)."""
    endpoint = otlp_endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))

    exporter: SpanExporter | None = None
    if endpoint:
        exporter = OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")
    elif console_fallback:
        exporter = ConsoleSpanExporter()

    if exporter is not None:
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name)
