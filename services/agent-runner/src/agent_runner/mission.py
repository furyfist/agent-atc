"""The tool-calling mission loop. See PROJECT_PLAN.md S6 span tree:

    agent.mission (root)
    |-- agent.turn (per LLM round)
    |   |-- gen_ai.chat            <- OTel GenAI semconv
    |   `-- mcp.tool.call {tool}   (client span; traceparent -> MCP _meta)

The actual LLM call is injected as `chat_fn` rather than hardwired to Groq -
this is what makes the loop testable without spending real API budget: tests
inject a scripted fake, main.py wires in the real AsyncGroq-backed
groq_client.chat_with_backoff.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from opentelemetry import propagate, trace

from atc_telemetry import AtcInstruments
from atc_telemetry.attributes import (
    AGENT_ID,
    AGENT_PERSONA,
    GEN_AI_REQUEST_MODEL,
    GEN_AI_SYSTEM,
    GEN_AI_USAGE_INPUT_TOKENS,
    GEN_AI_USAGE_OUTPUT_TOKENS,
    SPAN_AGENT_MISSION,
    SPAN_AGENT_TURN,
    SPAN_GEN_AI_CHAT,
    SPAN_MCP_TOOL_CALL_PREFIX,
)

ChatFn = Callable[[list[dict[str, Any]], list[dict[str, Any]]], Awaitable[Any]]

# Agent-side MCP client timeout must be >= 150s per the timeout-chain law
# (S5): a 120s hold only survives if every hop in the chain tolerates it.
AGENT_CLIENT_TIMEOUT = timedelta(seconds=170)
MAX_TURNS = 8


@dataclass
class ToolCallRecord:
    tool: str
    arguments: dict[str, Any]
    result_text: str


@dataclass
class MissionLog:
    agent_id: str
    turns: int = 0
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    final_message: str | None = None
    error: str | None = None

    @property
    def denied(self) -> bool:
        return any("[ATC-DENIED]" in tc.result_text for tc in self.tool_calls)


def _describe_exception(exc: BaseException) -> str:
    """anyio wraps exceptions raised inside the MCP client's context
    managers (they use anyio.create_task_group() internally) in a
    BaseExceptionGroup, so `str(exc)` on the caught exception is just
    "unhandled errors in a TaskGroup" - unwrap to the first real underlying
    exception so the logged error is actually useful."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return f"{type(exc).__name__}: {exc}"


def _mcp_tool_to_chat_schema(tool: Any) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.inputSchema,
        },
    }


async def run_mission(
    *,
    agent_id: str,
    persona: str,
    gateway_url: str,
    bearer_token: str,
    system_prompt: str,
    user_task: str,
    chat_fn: ChatFn,
    tracer: trace.Tracer,
    instruments: AtcInstruments | None = None,
    max_turns: int = MAX_TURNS,
) -> MissionLog:
    log = MissionLog(agent_id=agent_id)
    headers = {"Authorization": f"Bearer {bearer_token}"}

    try:
        with tracer.start_as_current_span(SPAN_AGENT_MISSION) as mission_span:
            mission_span.set_attribute(AGENT_ID, agent_id)
            mission_span.set_attribute(AGENT_PERSONA, persona)

            async with streamablehttp_client(gateway_url, headers=headers, sse_read_timeout=300) as (
                read,
                write,
                _,
            ):
                async with ClientSession(read, write, read_timeout_seconds=AGENT_CLIENT_TIMEOUT) as session:
                    await session.initialize()
                    tools_result = await session.list_tools()
                    chat_tools = [_mcp_tool_to_chat_schema(t) for t in tools_result.tools]

                    messages: list[dict[str, Any]] = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_task},
                    ]

                    for _turn in range(max_turns):
                        log.turns += 1
                        with tracer.start_as_current_span(SPAN_AGENT_TURN):
                            resp = await _traced_chat(tracer, chat_fn, messages, chat_tools, agent_id, instruments)
                            msg = resp.choices[0].message

                            if not msg.tool_calls:
                                log.final_message = msg.content
                                return log

                            messages.append(
                                {
                                    "role": "assistant",
                                    "content": msg.content or "",
                                    "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
                                }
                            )

                            for tc in msg.tool_calls:
                                name = tc.function.name
                                try:
                                    args = json.loads(tc.function.arguments or "{}")
                                except json.JSONDecodeError:
                                    args = {}

                                with tracer.start_as_current_span(f"{SPAN_MCP_TOOL_CALL_PREFIX} {name}"):
                                    carrier: dict[str, str] = {}
                                    propagate.inject(carrier)
                                    result = await session.call_tool(name, args, meta=carrier)
                                    text = result.content[0].text if result.content else ""

                                log.tool_calls.append(ToolCallRecord(tool=name, arguments=args, result_text=text))
                                messages.append({"role": "tool", "tool_call_id": tc.id, "content": text})
    except Exception as exc:  # noqa: BLE001 - one agent's failure must not crash the runner
        log.error = _describe_exception(exc)

    return log


async def _traced_chat(
    tracer: trace.Tracer,
    chat_fn: ChatFn,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    agent_id: str,
    instruments: AtcInstruments | None,
) -> Any:
    with tracer.start_as_current_span(SPAN_GEN_AI_CHAT) as span:
        span.set_attribute(GEN_AI_SYSTEM, "groq")
        start = time.monotonic()
        resp = await chat_fn(messages, tools)
        span.set_attribute("gen_ai.latency_seconds", time.monotonic() - start)
        model = getattr(resp, "model", None)
        if model:
            span.set_attribute(GEN_AI_REQUEST_MODEL, model)
        usage = getattr(resp, "usage", None)
        if usage:
            span.set_attribute(GEN_AI_USAGE_INPUT_TOKENS, usage.prompt_tokens)
            span.set_attribute(GEN_AI_USAGE_OUTPUT_TOKENS, usage.completion_tokens)
            if instruments is not None and model:
                total_tokens = usage.prompt_tokens + usage.completion_tokens
                instruments.agent_tokens_total.add(total_tokens, {"agent_id": agent_id, "model": model})
        return resp
