"""Loop-suspicion detection: is this agent stuck repeating itself?

The $47k failure shape: two agents (or one) ping-ponging near-identical calls
for days because nothing watched the *pattern*, only the individual calls -
each of which was individually allowed. The signature is unmistakable in the
action history ATC already keeps: same agent, same tool, same argument
summary, tight cadence.

Same non-gating contract as the creep detector (S6's law generalized): runs
async after the gate decision, emits an atc.loop_suspected span event + the
atc_loops_suspected_total counter, and never blocks, delays, or fails the
tool-call path. Detection-not-prevention is deliberate for now - a loop is a
pattern judgment, not a policy violation, so it feeds the risk score and the
operator's screen rather than auto-denying (the budget breaker is the hard
backstop if a loop burns real money).
"""

from __future__ import annotations

import asyncio
import time

from opentelemetry import trace

from atc_core.store import Store
from atc_telemetry import AtcInstruments
from atc_telemetry.attributes import AGENT_ID

# N prior near-identical calls inside the window (plus the current one) reads
# as a loop. Human-shaped retries (2-3 attempts) stay under it; a real loop
# blows past it within a couple of cycles.
DEFAULT_REPEAT_THRESHOLD = 3
DEFAULT_WINDOW_SECONDS = 180.0


class LoopDetector:
    def __init__(
        self,
        store: Store,
        *,
        tracer: trace.Tracer,
        instruments: AtcInstruments | None = None,
        repeat_threshold: int = DEFAULT_REPEAT_THRESHOLD,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
    ) -> None:
        self._store = store
        self._tracer = tracer
        self._instruments = instruments
        self._repeat_threshold = repeat_threshold
        self._window_seconds = window_seconds
        # Strong references so CPython can't GC fire-and-forget tasks
        # mid-flight (same bug class the creep detector hit - see creep.py).
        self._background_tasks: set[asyncio.Task] = set()

    def check_async(
        self, *, agent_id: str, tool: str, args_summary: str | None, action_id: str
    ) -> None:
        task = asyncio.create_task(
            self._check(agent_id=agent_id, tool=tool, args_summary=args_summary, action_id=action_id)
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _check(
        self, *, agent_id: str, tool: str, args_summary: str | None, action_id: str
    ) -> None:
        try:
            repeats = await self._count_recent_repeats(
                agent_id=agent_id, tool=tool, args_summary=args_summary, action_id=action_id
            )
        except Exception:  # noqa: BLE001 - background task, must never raise into the caller
            return

        if repeats < self._repeat_threshold:
            return

        with self._tracer.start_as_current_span("atc.loop_check") as span:
            span.set_attribute(AGENT_ID, agent_id)
            span.set_attribute("atc.loop.tool", tool)
            span.set_attribute("atc.loop.repeats", repeats)
            span.add_event(
                "atc.loop_suspected",
                {AGENT_ID: agent_id, "tool": tool, "repeats": repeats},
            )

        if self._instruments is not None:
            self._instruments.loops_suspected_total.add(1, {"agent_id": agent_id})

    async def _count_recent_repeats(
        self, *, agent_id: str, tool: str, args_summary: str | None, action_id: str
    ) -> int:
        since = time.time() - self._window_seconds
        actions = await self._store.list_actions()
        return sum(
            1
            for a in actions
            if a.agent_id == agent_id
            and a.tool == tool
            and a.args_summary == args_summary
            and a.action_id != action_id
            and a.requested_at >= since
        )
