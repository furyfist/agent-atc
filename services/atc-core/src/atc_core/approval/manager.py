"""Approval manager: the interception state machine from PROJECT_PLAN.md S5.

Pure state/concurrency logic - no OTel, no tool-argument parsing. The gateway
(not built yet) is responsible for: risk-assessing a call via the risk engine,
calling `submit()` with the result, emitting the two-phase spans (S6) around
the HELD path, calling `wait_for_decision()`, and then executing or denying
the tool call based on the terminal Action it gets back.

Held-and-timeout semantics (S5): a HIGH-risk action is held for up to
`hold_timeout_seconds` (120s default) via an in-memory `asyncio.Event` keyed
by action_id, with the PENDING row persisted to SQLite for crash-safety. If
the process restarts while an action is PENDING, its Event is gone forever -
`resume_stale_holds()` must be called once at startup to expire those rows
(S5: "stale HELD -> EXPIRED on restart").
"""

from __future__ import annotations

import asyncio
import dataclasses
import time

from atc_core.events import EventBus
from atc_core.risk.models import RiskDecision, RiskLevel
from atc_core.store import Action, ActionStatus, Store

DEFAULT_HOLD_TIMEOUT_SECONDS = 120.0
DEFAULT_HELD_RISK_LEVELS = frozenset({RiskLevel.HIGH})


class ApprovalManager:
    def __init__(
        self,
        store: Store,
        *,
        hold_timeout_seconds: float = DEFAULT_HOLD_TIMEOUT_SECONDS,
        held_risk_levels: frozenset[RiskLevel] = DEFAULT_HELD_RISK_LEVELS,
        event_bus: EventBus | None = None,
    ) -> None:
        self._store = store
        self._hold_timeout_seconds = hold_timeout_seconds
        self._held_risk_levels = held_risk_levels
        self._pending_events: dict[str, asyncio.Event] = {}
        self._event_bus = event_bus

    async def _publish(self, event_type: str, action: Action) -> None:
        if self._event_bus is not None:
            await self._event_bus.publish(event_type, dataclasses.asdict(action))

    async def submit(
        self,
        *,
        action_id: str,
        trace_id: str,
        span_id: str | None,
        agent_id: str,
        tool: str,
        resource_class: str | None,
        resource_name: str | None,
        args_summary: str | None,
        risk: RiskDecision,
        blast_radius: str | None = None,
    ) -> Action:
        """Creates the action row. Returns immediately with status
        AUTO_ALLOWED (risk not in held_risk_levels) or PENDING (held - the
        caller must then await `wait_for_decision`)."""
        now = time.time()
        held = risk.risk_level in self._held_risk_levels
        action = Action(
            action_id=action_id,
            trace_id=trace_id,
            span_id=span_id,
            agent_id=agent_id,
            tool=tool,
            resource_class=resource_class,
            resource_name=resource_name,
            args_summary=args_summary,
            risk_level=risk.risk_level,
            risk_reason=risk.reason,
            rule_id=risk.rule_id,
            status=ActionStatus.PENDING if held else ActionStatus.AUTO_ALLOWED,
            decided_by=None,
            requested_at=now,
            resolved_at=None if held else now,
            reversibility=risk.reversibility.value,
            blast_radius=blast_radius,
        )
        await self._store.insert_action(action)
        if held:
            self._pending_events[action_id] = asyncio.Event()
            await self._publish("action.pending", action)
        return action

    async def wait_for_decision(self, action_id: str) -> Action:
        """Blocks until a HELD action resolves (approved/denied by a human,
        or the hold timeout expires). Returns immediately for an action that
        was never held (already terminal)."""
        event = self._pending_events.get(action_id)
        if event is None:
            action = await self._store.get_action(action_id)
            if action is None:
                raise ValueError(f"unknown action_id: {action_id}")
            return action

        expired = False
        try:
            await asyncio.wait_for(event.wait(), timeout=self._hold_timeout_seconds)
        except TimeoutError:
            await self._store.resolve_action(
                action_id, status=ActionStatus.EXPIRED, decided_by=None, resolved_at=time.time()
            )
            expired = True
        finally:
            self._pending_events.pop(action_id, None)

        action = await self._store.get_action(action_id)
        if action is None:
            raise ValueError(f"unknown action_id: {action_id}")
        if expired:
            # The decide() path publishes its own action.resolved; only the
            # timeout path resolves here and needs to announce it itself.
            await self._publish("action.resolved", action)
        return action

    async def decide(self, action_id: str, *, approved: bool, decided_by: str) -> Action:
        """Called by the approve/deny REST endpoint. If the action already
        resolved (e.g. it expired a moment earlier), this is a no-op and the
        true terminal state is returned rather than silently overwritten -
        the trace is the audit log, so it must stay honest."""
        existing = await self._store.get_action(action_id)
        if existing is None:
            raise ValueError(f"unknown action_id: {action_id}")

        status = ActionStatus.APPROVED if approved else ActionStatus.DENIED
        await self._store.resolve_action(
            action_id, status=status, decided_by=decided_by, resolved_at=time.time()
        )

        # Pop (not just read) so the entry can't leak if wait_for_decision()
        # is never called for this action_id (e.g. the coroutine that would
        # have awaited it was cancelled). set() first so any waiter still
        # blocked on it wakes up before the reference is dropped.
        event = self._pending_events.pop(action_id, None)
        if event is not None:
            event.set()

        updated = await self._store.get_action(action_id)
        if updated is None:
            raise ValueError(f"unknown action_id: {action_id}")
        await self._publish("action.resolved", updated)
        return updated

    async def resume_stale_holds(self) -> list[Action]:
        """Call once at gateway startup. A row still PENDING means the
        process that was holding it - and its in-memory Event - is gone, so
        it can never be legitimately resolved. Expire it (S5)."""
        pending = await self._store.list_actions(status=ActionStatus.PENDING)
        expired: list[Action] = []
        now = time.time()
        for action in pending:
            await self._store.resolve_action(
                action.action_id, status=ActionStatus.EXPIRED, decided_by=None, resolved_at=now
            )
            updated = await self._store.get_action(action.action_id)
            if updated is not None:
                expired.append(updated)
                await self._publish("action.resolved", updated)
        return expired
