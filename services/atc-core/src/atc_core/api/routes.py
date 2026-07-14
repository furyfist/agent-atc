"""REST API. See PROJECT_PLAN.md S8.

    GET  /api/agents
    GET  /api/actions?status=pending
    POST /api/actions/{action_id}/approve
    POST /api/actions/{action_id}/deny
    POST /api/agents/{agent_id}/quarantine

/api/narrate is added alongside the Narrator itself, not here.

Store/ApprovalManager are read off `request.app.state` - the app assembly
(atc_core.app) is responsible for setting them there once at construction.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from atc_core.api.schemas import ActionOut, AgentOut, DecideRequest, QuarantineRequest
from atc_core.approval import ApprovalManager
from atc_core.store import Action, ActionStatus, Agent, Store

router = APIRouter(prefix="/api")


def _store(request: Request) -> Store:
    return request.app.state.store


def _approval_manager(request: Request) -> ApprovalManager:
    return request.app.state.approval_manager


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
