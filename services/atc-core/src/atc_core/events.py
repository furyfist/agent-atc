"""Lightweight async pub-sub. Domain code (ApprovalManager, and later the
heartbeat/risk-score recompute loop) publishes named events without knowing
who's listening; the WebSocket layer subscribes and broadcasts. Keeps the
approval state machine decoupled from any particular transport.

See PROJECT_PLAN.md S8: action.pending, action.resolved, agent.heartbeat,
risk.updated. Only action.pending/action.resolved have a real publisher today
(ApprovalManager) - the other two are documented here as the fixed contract,
wired in once agent-runner's heartbeat loop and the risk-score recompute
exist.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Event:
    type: str
    payload: dict[str, Any]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[Event]] = []

    def subscribe(self) -> asyncio.Queue[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Event]) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        event = Event(type=event_type, payload=payload)
        for queue in list(self._subscribers):
            await queue.put(event)
