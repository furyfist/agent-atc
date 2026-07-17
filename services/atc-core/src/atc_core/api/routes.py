"""REST API. See PROJECT_PLAN.md S8.

    GET  /api/agents
    GET  /api/actions?status=pending
    POST /api/actions/{action_id}/approve
    POST /api/actions/{action_id}/deny
    POST /api/agents/{agent_id}/quarantine
    POST /api/agents/{agent_id}/heartbeat
    POST /api/narrate

Store/ApprovalManager/Narrator are read off `request.app.state` - the app
assembly (atc_core.app) is responsible for setting them there once at
construction. `narrator` is optional there (no Groq key configured yet is a
valid state) - the endpoint below returns 503 rather than crashing if unset.
"""

from __future__ import annotations

import dataclasses
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from atc_core.api.schemas import (
    ActionOut,
    AgentOut,
    DecideRequest,
    HeartbeatRequest,
    NarrateRequest,
    NarrateResponse,
    QuarantineRequest,
)
from atc_core.approval import ApprovalManager
from atc_core.events import EventBus
from atc_core.narrator import Narrator
from atc_core.risk.scorer import RiskScorer
from atc_core.store import Action, ActionStatus, Agent, Store

router = APIRouter(prefix="/api")


def _store(request: Request) -> Store:
    return request.app.state.store


def _approval_manager(request: Request) -> ApprovalManager:
    return request.app.state.approval_manager


def _narrator(request: Request) -> Narrator | None:
    return getattr(request.app.state, "narrator", None)


def _event_bus(request: Request) -> EventBus | None:
    return getattr(request.app.state, "event_bus", None)


def _instruments(request: Request) -> Any:
    return getattr(request.app.state, "instruments", None)


def _agent_dict(agent: Agent) -> dict[str, Any]:
    return dataclasses.asdict(agent)


def _action_dict(action: Action) -> dict[str, Any]:
    d = dataclasses.asdict(action)
    d["risk_level"] = action.risk_level.value
    d["status"] = action.status.value
    return d


@router.get("/agents", response_model=list[AgentOut])
async def list_agents(request: Request) -> list[AgentOut]:
    agents = await _store(request).list_agents()
    return [AgentOut(**_agent_dict(a)) for a in agents]


@router.get("/actions", response_model=list[ActionOut])
async def list_actions(request: Request, status: str | None = None) -> list[ActionOut]:
    status_enum: ActionStatus | None = None
    if status is not None:
        try:
            status_enum = ActionStatus(status.upper())
        except ValueError:
            raise HTTPException(status_code=422, detail=f"unknown status: {status}") from None
    actions = await _store(request).list_actions(status=status_enum)
    return [ActionOut(**_action_dict(a)) for a in actions]


@router.post("/actions/{action_id}/approve", response_model=ActionOut)
async def approve_action(action_id: str, body: DecideRequest, request: Request) -> ActionOut:
    return await _decide(request, action_id, approved=True, decided_by=body.decided_by)


@router.post("/actions/{action_id}/deny", response_model=ActionOut)
async def deny_action(action_id: str, body: DecideRequest, request: Request) -> ActionOut:
    return await _decide(request, action_id, approved=False, decided_by=body.decided_by)


async def _decide(request: Request, action_id: str, *, approved: bool, decided_by: str) -> ActionOut:
    try:
        action = await _approval_manager(request).decide(
            action_id, approved=approved, decided_by=decided_by
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ActionOut(**_action_dict(action))


@router.post("/agents/{agent_id}/quarantine", response_model=AgentOut)
async def quarantine_agent(
    agent_id: str, request: Request, body: QuarantineRequest | None = None
) -> AgentOut:
    quarantined = body.quarantined if body is not None else True
    store = _store(request)
    agent = await store.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"unknown agent_id: {agent_id}")
    await store.set_quarantined(agent_id, quarantined)
    updated = await store.get_agent(agent_id)
    assert updated is not None
    return AgentOut(**_agent_dict(updated))


@router.post("/agents/{agent_id}/heartbeat", response_model=AgentOut)
async def heartbeat(
    agent_id: str, request: Request, body: HeartbeatRequest | None = None
) -> AgentOut:
    """Called by agent-runner on its heartbeat cadence. Records the
    liveness timestamp and recomputes this agent's EWMA risk score (S6:
    "recomputed on the heartbeat cadence, not continuously") - both the
    gauge metrics and the agent.heartbeat/risk.updated WS events fire from
    here so Fleet Tower has one single source for "this agent is alive"."""
    store = _store(request)
    agent = await store.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"unknown agent_id: {agent_id}")

    now = time.time()
    await store.record_heartbeat(agent_id, now)
    if body is not None and body.tokens_used is not None:
        await store.set_tokens_used(agent_id, body.tokens_used)
    score = await RiskScorer(store).compute_score(agent_id, now=now)

    instruments = _instruments(request)
    if instruments is not None:
        instruments.agent_heartbeat.set(now, {"agent_id": agent_id})
        instruments.agent_risk_score.set(score, {"agent_id": agent_id})

    updated = await store.get_agent(agent_id)
    assert updated is not None

    event_bus = _event_bus(request)
    if event_bus is not None:
        await event_bus.publish("agent.heartbeat", _agent_dict(updated))
        await event_bus.publish("risk.updated", {"agent_id": agent_id, "risk_score": score})

    return AgentOut(**_agent_dict(updated))


@router.post("/narrate", response_model=NarrateResponse)
async def narrate(body: NarrateRequest, request: Request) -> NarrateResponse:
    narrator = _narrator(request)
    if narrator is None:
        raise HTTPException(status_code=503, detail="Narrator is not configured on this instance")
    text = await narrator.narrate(body.trace_id)
    return NarrateResponse(trace_id=body.trace_id, text=text)
