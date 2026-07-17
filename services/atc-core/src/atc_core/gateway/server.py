"""The ATC MCP gateway. MCP server to agents, MCP client to upstream tool
servers (via UpstreamPool). See PROJECT_PLAN.md S5.

Denials are returned as normal MCP tool *results* (isError left False, plain
text content), never as protocol errors - S5: "enables on-camera agent
recovery" by letting the agent read the denial and reason about it instead
of choking on a transport-level error.
"""

from __future__ import annotations

import json
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from opentelemetry import propagate, trace
from starlette.applications import Starlette
from starlette.requests import Request as StarletteRequest
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send

from atc_core.approval import ApprovalManager
from atc_core.gateway.blast_radius import estimate_blast_radius
from atc_core.gateway.creep import CreepDetector
from atc_core.gateway.loops import LoopDetector
from atc_core.gateway.registry import AgentIdentity, AgentRegistry
from atc_core.gateway.upstream import UpstreamPool
from atc_core.risk import RiskEngine, RiskLevel
from atc_core.store import ActionStatus, Agent, Store
from atc_telemetry import AtcInstruments

DENY_UNAUTHENTICATED = (
    "[ATC-DENIED] reason=unauthenticated policy_rule=AUTH-REQUIRED. "
    "Missing or invalid bearer token."
)
DENY_QUARANTINED = (
    "[ATC-QUARANTINED] This agent has been quarantined by an operator. "
    "All tool calls are blocked until the quarantine is lifted."
)
DENY_SCOPE_VIOLATION = (
    "[ATC-DENIED] reason=scope_violation policy_rule=SCOPE-ENFORCEMENT. "
    "Blocked by governance. This tool is outside your agent's registered scope."
)
DENY_UNKNOWN_TOOL = "[ATC-ERROR] unknown tool {name}"
DENY_BUDGET = (
    "[ATC-BUDGET] reason=token_budget_exhausted used={used:.0f} budget={budget:.0f}. "
    "Blocked by governance. This agent's token budget is spent; an operator "
    "must raise it before further tool calls are allowed."
)


class Gateway:
    def __init__(
        self,
        *,
        registry: AgentRegistry,
        risk_engine: RiskEngine,
        approval_manager: ApprovalManager,
        store: Store,
        upstream: UpstreamPool,
        tracer: trace.Tracer,
        instruments: AtcInstruments | None = None,
        token_budget: float | None = None,
    ) -> None:
        self._registry = registry
        self._risk_engine = risk_engine
        self._approval_manager = approval_manager
        self._store = store
        self._upstream = upstream
        self._tracer = tracer
        self._instruments = instruments
        # Per-agent cumulative token ceiling (None = disabled). Spend is
        # reported by the agents' own heartbeats; enforcement happens here at
        # the gate because alerts are too slow for a runaway loop - by the
        # time a human reads one, a tight loop has burned multiples of the
        # budget. Blocking pre-execution is the only cadence that works.
        self._token_budget = token_budget
        self._creep_detector = CreepDetector(store, tracer=tracer, instruments=instruments)
        self._loop_detector = LoopDetector(store, tracer=tracer, instruments=instruments)
        self.server: Server = Server("atc-gateway")
        self._register_handlers()

    async def startup(self) -> None:
        """Call once before serving traffic: seeds the store with the
        registry's agents and expires any PENDING rows orphaned by a
        previous process crash (S5: "stale HELD -> EXPIRED on restart")."""
        now = time.time()
        for identity in self._registry.all_agents():
            existing = await self._store.get_agent(identity.id)
            if existing is None:
                await self._store.upsert_agent(
                    Agent(
                        id=identity.id,
                        persona=identity.persona,
                        scope=sorted(identity.scope),
                        owner=identity.owner,
                        quarantined=False,
                        last_heartbeat_ts=None,
                        created_at=now,
                    )
                )
        await self._approval_manager.resume_stale_holds()

    def _register_handlers(self) -> None:
        @self.server.list_tools()
        async def handle_list_tools() -> list[types.Tool]:
            agent = self._current_agent()
            if agent is None:
                return []
            return [t for t in self._upstream.list_tools() if self._registry.in_scope(agent, t.name)]

        @self.server.call_tool()
        async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
            return await self._handle_call_tool(name, arguments or {})

    def _current_agent(self) -> AgentIdentity | None:
        http_request: StarletteRequest | None = self.server.request_context.request
        token = _extract_bearer_token(http_request)
        return self._registry.authenticate(token)

    def _extract_traceparent_context(self) -> Any:
        meta = self.server.request_context.meta
        traceparent = getattr(meta, "traceparent", None) if meta else None
        carrier = {"traceparent": traceparent} if traceparent else {}
        return propagate.extract(carrier)

    async def _handle_call_tool(self, name: str, arguments: dict) -> list[types.TextContent]:
        parent_ctx = self._extract_traceparent_context()

        with self._tracer.start_as_current_span(f"atc.gate.{name}", context=parent_ctx) as gate_span:
            gate_span.set_attribute("atc.resource.name", name)

            agent = self._current_agent()
            if agent is None:
                return _deny(DENY_UNAUTHENTICATED)
            gate_span.set_attribute("agent.id", agent.id)

            stored_agent = await self._store.get_agent(agent.id)
            if stored_agent is not None and stored_agent.quarantined:
                return _deny(DENY_QUARANTINED)

            if (
                self._token_budget is not None
                and stored_agent is not None
                and stored_agent.tokens_used >= self._token_budget
            ):
                gate_span.add_event(
                    "BUDGET_EXHAUSTED",
                    {"agent.id": agent.id, "tokens.used": stored_agent.tokens_used},
                )
                return _deny(
                    DENY_BUDGET.format(used=stored_agent.tokens_used, budget=self._token_budget)
                )

            if not self._registry.in_scope(agent, name):
                gate_span.add_event("SCOPE_VIOLATION", {"tool": name, "agent.id": agent.id})
                return _deny(DENY_SCOPE_VIOLATION)

            entry = self._upstream.resolve(name)
            if entry is None:
                return _deny(DENY_UNKNOWN_TOOL.format(name=name))

            with self._tracer.start_as_current_span("atc.risk_assessment") as risk_span:
                risk = self._risk_engine.evaluate(name, arguments)
                risk_span.set_attribute("atc.risk.level", risk.risk_level.value)
                risk_span.set_attribute("atc.risk.reasons", risk.reason)
                risk_span.set_attribute("policy.rule_id", risk.rule_id)
                # Pins the exact rule set in force at decision time - the
                # attribute that turns this span into a defensible decision
                # record (see RiskEngine.from_yaml).
                risk_span.set_attribute("policy.version", self._risk_engine.policy_version)
                risk_span.set_attribute("atc.reversibility", risk.reversibility.value)

            # Estimated pre-hold so it's on the approval card while the human
            # decides. Only for calls risky enough to plausibly be held -
            # LOW-risk reads never pay the extra upstream round-trip.
            blast_radius = None
            if risk.risk_level != RiskLevel.LOW:
                blast_radius = await estimate_blast_radius(self._upstream, name, arguments)
                if blast_radius is not None:
                    gate_span.set_attribute("atc.blast_radius", blast_radius)

            span_ctx = gate_span.get_span_context()
            resource_name = _resource_name(arguments)
            action = await self._approval_manager.submit(
                action_id=str(uuid.uuid4()),
                trace_id=format(span_ctx.trace_id, "032x"),
                span_id=format(span_ctx.span_id, "016x"),
                agent_id=agent.id,
                tool=name,
                resource_class=entry.namespace,
                resource_name=resource_name,
                args_summary=_args_summary(arguments),
                risk=risk,
                blast_radius=blast_radius,
            )

            # S6's non-gating creep law: scheduled, never awaited, so it can
            # never add latency to (or fail) the tool-call path below. The
            # loop detector rides the same contract.
            self._creep_detector.check_async(
                agent_id=agent.id, resource_name=resource_name, action_id=action.action_id
            )
            self._loop_detector.check_async(
                agent_id=agent.id,
                tool=name,
                args_summary=action.args_summary,
                action_id=action.action_id,
            )

            if action.status == ActionStatus.PENDING:
                if self._instruments is not None:
                    self._instruments.interceptions_total.add(1, {"agent_id": agent.id})

                with self._tracer.start_as_current_span("atc.interception") as hold_span:
                    hold_span.set_attribute("atc.action_id", action.action_id)

                with self._tracer.start_as_current_span("atc.approval_wait") as wait_span:
                    wait_span.set_attribute("atc.action_id", action.action_id)
                    action = await self._approval_manager.wait_for_decision(action.action_id)
                    wait_span.set_attribute("atc.decision", action.status.value)

                if self._instruments is not None and action.resolved_at is not None:
                    self._instruments.approval_latency_seconds.record(
                        action.resolved_at - action.requested_at, {"agent_id": agent.id}
                    )

                if action.status in (ActionStatus.DENIED, ActionStatus.EXPIRED):
                    if self._instruments is not None:
                        self._instruments.actions_total.add(
                            1, {"agent_id": agent.id, "risk": risk.risk_level.value, "decision": action.status.value}
                        )
                    reason = "denied_by_human" if action.status == ActionStatus.DENIED else "hold_timeout"
                    return _deny(
                        f"[ATC-DENIED] reason={reason} policy_rule={risk.rule_id} "
                        f"action_id={action.action_id}. Blocked by governance. "
                        "You may propose a safer alternative."
                    )

            if self._instruments is not None:
                self._instruments.actions_total.add(
                    1, {"agent_id": agent.id, "risk": risk.risk_level.value, "decision": action.status.value}
                )

            with self._tracer.start_as_current_span("atc.execution"):
                outgoing_carrier: dict[str, str] = {}
                propagate.inject(outgoing_carrier)
                result = await self._upstream.call_tool(name, arguments, meta=outgoing_carrier)
                return list(result.content)


def _deny(text: str) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=text)]


def _extract_bearer_token(request: StarletteRequest | None) -> str | None:
    if request is None:
        return None
    auth = request.headers.get("authorization")
    if not auth:
        return None
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


def _args_summary(arguments: dict, max_len: int = 200) -> str:
    text = json.dumps(arguments, default=str)
    return text if len(text) <= max_len else text[: max_len - 3] + "..."


def _resource_name(arguments: dict) -> str | None:
    for key in ("sql", "path", "to"):
        value = arguments.get(key)
        if value is not None:
            return str(value)[:200]
    return None


def create_mcp_asgi_handler(gateway: Gateway) -> tuple[Any, StreamableHTTPSessionManager]:
    """Returns the raw ASGI callable for the MCP endpoint plus its session
    manager. A *plain callable* (not a Starlette app with its own lifespan) so
    it composes safely into a bigger app via Mount: Starlette does NOT forward
    ASGI lifespan events to mounted sub-apps (verified empirically - a
    sub-app's own @asynccontextmanager lifespan never fires when mounted),
    so the session manager's `.run()` context and `gateway.startup()` must be
    driven by whichever app owns the top-level lifespan, not by this one."""
    session_manager = StreamableHTTPSessionManager(app=gateway.server, stateless=False)

    async def handle_streamable_http(scope: Scope, receive: Receive, send: Send) -> None:
        await session_manager.handle_request(scope, receive, send)

    return handle_streamable_http, session_manager


def build_asgi_app(gateway: Gateway) -> Starlette:
    """Standalone MCP-only ASGI app (used by the gateway's own tests). Owns
    its own lifespan - fine as long as nothing mounts this *as a sub-app* of
    a bigger one (see create_mcp_asgi_handler's docstring for why)."""
    handle_streamable_http, session_manager = create_mcp_asgi_handler(gateway)

    @asynccontextmanager
    async def lifespan(_app: Starlette):
        await gateway.startup()
        async with session_manager.run():
            yield

    return Starlette(routes=[Mount("/mcp", app=handle_streamable_http)], lifespan=lifespan)
