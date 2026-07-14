"""Shared tracing setup for the S1 spike processes (agent, gateway, upstream).

Not the real atc_telemetry package - this is throwaway spike plumbing to prove
W3C traceparent propagation across process boundaries. Prints one greppable
line per finished span so run_spike.py can verify trace_id equality across
the three process logs without a real OTel collector.
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult


class PrintingExporter(SpanExporter):
    def __init__(self, process_name: str) -> None:
        self._process_name = process_name

    def export(self, spans: list[ReadableSpan]) -> SpanExportResult:
        for span in spans:
            ctx = span.get_span_context()
            parent_id = format(span.parent.span_id, "016x") if span.parent else "-" * 16
            print(
                f"[{self._process_name}] SPAN name={span.name} "
                f"trace_id={format(ctx.trace_id, '032x')} "
                f"span_id={format(ctx.span_id, '016x')} "
                f"parent_span_id={parent_id}",
                flush=True,
            )
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass


def setup_tracing(process_name: str) -> trace.Tracer:
    provider = TracerProvider(resource=Resource.create({"service.name": process_name}))
    provider.add_span_processor(SimpleSpanProcessor(PrintingExporter(process_name)))
    trace.set_tracer_provider(provider)
    return trace.get_tracer(process_name)
