"""Span sources for the Narrator. See PROJECT_PLAN.md S8's fallback chain:
primary SigNoz MCP server, fallback Trace API, emergency cached text.

Neither SigNoz fetcher is implemented yet - Docker isn't available in this
environment, so there's no live SigNoz to fetch from or test against. Rather
than skip the Narrator entirely, ActionStoreSpanFetcher below provides a
fourth, genuinely-working source using data the gateway already writes to
its own actions table (agent_id, tool, risk_level, decision, timestamps).
It's a real, useful narration source today, but a materially smaller one
than real SigNoz spans (no agent.mission/gen_ai.chat/tool.{name} detail) -
document this as what it is, not a stand-in that pretends to be SigNoz.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from atc_core.store import Store


@dataclass(frozen=True)
class SpanRecord:
    name: str
    timestamp: float
    attributes: dict[str, Any]


class SpanFetcher(Protocol):
    async def fetch_spans(self, trace_id: str) -> list[SpanRecord]: ...


class ActionStoreSpanFetcher:
    """Synthesizes a timeline from the actions table instead of real spans."""

    def __init__(self, store: Store) -> None:
        self._store = store

    async def fetch_spans(self, trace_id: str) -> list[SpanRecord]:
        actions = await self._store.list_actions()
        matching = [a for a in actions if a.trace_id == trace_id]

        spans: list[SpanRecord] = []
        for action in matching:
            spans.append(
                SpanRecord(
                    name=f"tool_call.{action.tool}",
                    timestamp=action.requested_at,
                    attributes={
                        "agent.id": action.agent_id,
                        "atc.resource.class": action.resource_class,
                        "atc.resource.name": action.resource_name,
                        "atc.args_summary": action.args_summary,
                        "atc.risk.level": action.risk_level.value,
                        "atc.risk.reasons": action.risk_reason,
                        "policy.rule_id": action.rule_id,
                    },
                )
            )
            if action.resolved_at is not None:
                spans.append(
                    SpanRecord(
                        name=f"decision.{action.tool}",
                        timestamp=action.resolved_at,
                        attributes={
                            "atc.decision": action.status.value,
                            "atc.decision.by": action.decided_by,
                        },
                    )
                )

        spans.sort(key=lambda s: s.timestamp)
        return spans


class FallbackSpanFetcher:
    """Tries `primary` first, falls back to `secondary` if it yields no
    spans. `TraceApiSpanFetcher` already returns [] on any network/auth/parse
    failure (S9's fire-and-forget contract), so "empty" is the correct signal
    to fall back on here - no exception handling needed at this layer."""

    def __init__(self, primary: SpanFetcher, secondary: SpanFetcher) -> None:
        self._primary = primary
        self._secondary = secondary

    async def fetch_spans(self, trace_id: str) -> list[SpanRecord]:
        spans = await self._primary.fetch_spans(trace_id)
        if spans:
            return spans
        return await self._secondary.fetch_spans(trace_id)
