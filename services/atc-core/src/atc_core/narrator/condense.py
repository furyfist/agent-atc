"""Condenses a span timeline into a compact text block for the Narrator's
Groq prompt. See PROJECT_PLAN.md S8: "code condenses span tree to a compact
timeline (TPM budget)".
"""

from __future__ import annotations

from atc_core.narrator.span_fetcher import SpanRecord


def condense_timeline(spans: list[SpanRecord], max_chars: int = 2000) -> str:
    lines = []
    for span in spans:
        attrs = ", ".join(f"{k}={v}" for k, v in span.attributes.items() if v is not None)
        lines.append(f"[t={span.timestamp:.0f}] {span.name}: {attrs}")
    text = "\n".join(lines)
    return text if len(text) <= max_chars else text[: max_chars - 3] + "..."
