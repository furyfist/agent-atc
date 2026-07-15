"""Permission-creep detection. See PROJECT_PLAN.md S6:

    novel resource <=> zero prior spans for (agent.id, resource) ... results
    cached in SQLite to bound API calls.

    Non-gating creep law: the creep check runs asynchronously AFTER the gate
    decision - it emits the atc.novel_resource event span + metric but NEVER
    blocks or delays the tool-call path.

The plan's version of this queries SigNoz history via the Trace API/MCP
server, caching results in SQLite. This implementation queries SQLite
directly instead: the actions table already *is* that durable history (every
gated call is written there before this check ever runs), so it satisfies
the same "has this agent ever touched this resource before" question without
a network round-trip to SigNoz on the hot path - which also trivially
satisfies the non-gating law, since there's no way for this to add gate-path
latency if the gate never awaits it.

Distinction from scope violations (S6): a scope violation is an out-of-scope
*tool* call, rejected at list/call time, before an action row is even
written. Creep is about an in-scope *resource* the agent has simply never
touched before - by definition it can only be detected after the row
exists, hence "after the gate decision, not gating it."
"""

from __future__ import annotations

import asyncio

from opentelemetry import trace

from atc_core.store import Store
from atc_telemetry import AtcInstruments
from atc_telemetry.attributes import AGENT_ID, ATC_NOVEL_RESOURCE, ATC_RESOURCE_NAME


class CreepDetector:
    def __init__(
        self,
        store: Store,
        *,
        tracer: trace.Tracer,
        instruments: AtcInstruments | None = None,
    ) -> None:
        self._store = store
        self._tracer = tracer
        self._instruments = instruments

    def check_async(self, *, agent_id: str, resource_name: str | None, action_id: str) -> None:
        """Fire-and-forget entry point: schedules the actual check as a
        background task and returns immediately, so callers on the gate
        path never await this (S6's non-gating law). Exceptions inside the
        task are swallowed - a broken creep check must never surface as an
        error anywhere near the tool-call path."""
        if not resource_name:
            return
        asyncio.create_task(self._check(agent_id=agent_id, resource_name=resource_name, action_id=action_id))

    async def _check(self, *, agent_id: str, resource_name: str, action_id: str) -> None:
        try:
            is_novel = await self._is_novel(agent_id=agent_id, resource_name=resource_name, action_id=action_id)
        except Exception:  # noqa: BLE001 - background task, must never raise into the caller
            return

        if not is_novel:
            return

        with self._tracer.start_as_current_span("atc.creep_check") as span:
            span.set_attribute(AGENT_ID, agent_id)
            span.set_attribute(ATC_RESOURCE_NAME, resource_name)
            span.set_attribute(ATC_NOVEL_RESOURCE, True)
            span.add_event(
                "atc.novel_resource", {AGENT_ID: agent_id, ATC_RESOURCE_NAME: resource_name}
            )

        if self._instruments is not None:
            self._instruments.novel_resource_total.add(1, {"agent_id": agent_id})

    async def _is_novel(self, *, agent_id: str, resource_name: str, action_id: str) -> bool:
        """Novel iff no *other* action row for this (agent_id, resource_name)
        pair exists that isn't this action itself - the row for the current
        call is already written (S5: RISK_ASSESSED happens before this is
        invoked), so it must be excluded or every first-ever call would
        trivially "find" itself and never register as novel."""
        actions = await self._store.list_actions()
        return not any(
            a.agent_id == agent_id and a.resource_name == resource_name and a.action_id != action_id
            for a in actions
        )
