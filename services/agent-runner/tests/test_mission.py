"""Tests for the mission loop: connect, discover tools, run the chat_fn
loop, call real MCP tools, record results. chat_fn is scripted (no Groq
calls) - see server_helpers.py's docstring for why the MCP server side is a
minimal double rather than the real gateway.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest
from opentelemetry import trace

from agent_runner.mission import run_mission
from atc_telemetry import configure_tracing

from server_helpers import build_minimal_server, free_port, run_asgi_app

TOKEN = "unused-by-the-minimal-test-server"


@dataclass
class FakeFunction:
    name: str
    arguments: str


@dataclass
class FakeToolCall:
    id: str
    function: FakeFunction

    def model_dump(self) -> dict:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.function.name, "arguments": self.function.arguments},
        }


@dataclass
class FakeMessage:
    content: str | None
    tool_calls: list[FakeToolCall] | None


@dataclass
class FakeChoice:
    message: FakeMessage


@dataclass
class FakeUsage:
    prompt_tokens: int = 100
    completion_tokens: int = 20


@dataclass
class FakeResponse:
    choices: list[FakeChoice]
    model: str = "test-model"
    usage: FakeUsage = field(default_factory=FakeUsage)


def _final_response(text: str) -> FakeResponse:
    return FakeResponse(choices=[FakeChoice(message=FakeMessage(content=text, tool_calls=None))])


def _tool_call_response(tool_name: str, arguments: dict) -> FakeResponse:
    tc = FakeToolCall(id="call-1", function=FakeFunction(name=tool_name, arguments=json.dumps(arguments)))
    return FakeResponse(choices=[FakeChoice(message=FakeMessage(content=None, tool_calls=[tc]))])


@pytest.fixture
def tracer() -> trace.Tracer:
    return configure_tracing("test-agent-runner")


async def test_mission_with_no_tool_calls_returns_final_message(tracer: trace.Tracer) -> None:
    port = free_port()
    app = build_minimal_server(port).streamable_http_app()

    async def chat_fn(messages, tools):
        return _final_response("nothing to do here")

    async with run_asgi_app(app, "127.0.0.1", port):
        log = await run_mission(
            agent_id="test-agent",
            persona="test",
            gateway_url=f"http://127.0.0.1:{port}/mcp",
            bearer_token=TOKEN,
            system_prompt="be helpful",
            user_task="do nothing",
            chat_fn=chat_fn,
            tracer=tracer,
        )

    assert log.error is None
    assert log.turns == 1
    assert log.tool_calls == []
    assert log.final_message == "nothing to do here"


async def test_mission_calls_a_tool_then_finishes(tracer: trace.Tracer) -> None:
    port = free_port()
    app = build_minimal_server(port).streamable_http_app()

    calls = {"n": 0}

    async def chat_fn(messages, tools):
        calls["n"] += 1
        if calls["n"] == 1:
            return _tool_call_response("ping", {})
        return _final_response("done")

    async with run_asgi_app(app, "127.0.0.1", port):
        log = await run_mission(
            agent_id="test-agent",
            persona="test",
            gateway_url=f"http://127.0.0.1:{port}/mcp",
            bearer_token=TOKEN,
            system_prompt="be helpful",
            user_task="ping the server",
            chat_fn=chat_fn,
            tracer=tracer,
        )

    assert log.error is None
    assert log.turns == 2
    assert len(log.tool_calls) == 1
    assert log.tool_calls[0].tool == "ping"
    assert log.tool_calls[0].result_text == "pong"
    assert log.final_message == "done"


async def test_mission_records_denial_and_recovers(tracer: trace.Tracer) -> None:
    port = free_port()
    app = build_minimal_server(port).streamable_http_app()

    calls = {"n": 0}

    async def chat_fn(messages, tools):
        calls["n"] += 1
        if calls["n"] <= 2:
            return _tool_call_response("flaky_write", {"value": "x"})
        return _final_response("recovered")

    async with run_asgi_app(app, "127.0.0.1", port):
        log = await run_mission(
            agent_id="test-agent",
            persona="test",
            gateway_url=f"http://127.0.0.1:{port}/mcp",
            bearer_token=TOKEN,
            system_prompt="be helpful",
            user_task="write something",
            chat_fn=chat_fn,
            tracer=tracer,
        )

    assert log.error is None
    assert len(log.tool_calls) == 2
    assert "[ATC-DENIED]" in log.tool_calls[0].result_text
    assert "ok: wrote" in log.tool_calls[1].result_text
    assert log.denied is True
    assert log.final_message == "recovered"


async def test_mission_stops_at_max_turns_if_agent_never_finishes(tracer: trace.Tracer) -> None:
    port = free_port()
    app = build_minimal_server(port).streamable_http_app()

    async def chat_fn(messages, tools):
        return _tool_call_response("ping", {})

    async with run_asgi_app(app, "127.0.0.1", port):
        log = await run_mission(
            agent_id="test-agent",
            persona="test",
            gateway_url=f"http://127.0.0.1:{port}/mcp",
            bearer_token=TOKEN,
            system_prompt="be helpful",
            user_task="ping forever",
            chat_fn=chat_fn,
            tracer=tracer,
            max_turns=3,
        )

    assert log.error is None
    assert log.turns == 3
    assert len(log.tool_calls) == 3
    assert log.final_message is None


async def test_mission_records_chat_fn_error_without_raising(tracer: trace.Tracer) -> None:
    port = free_port()
    app = build_minimal_server(port).streamable_http_app()

    async def chat_fn(messages, tools):
        raise RuntimeError("exhausted retries")

    async with run_asgi_app(app, "127.0.0.1", port):
        log = await run_mission(
            agent_id="test-agent",
            persona="test",
            gateway_url=f"http://127.0.0.1:{port}/mcp",
            bearer_token=TOKEN,
            system_prompt="be helpful",
            user_task="do something",
            chat_fn=chat_fn,
            tracer=tracer,
        )

    assert log.error is not None
    assert "exhausted retries" in log.error


async def test_mission_accumulates_token_usage_across_turns(tracer: trace.Tracer) -> None:
    port = free_port()
    app = build_minimal_server(port).streamable_http_app()

    calls = {"n": 0}

    async def chat_fn(messages, tools):
        calls["n"] += 1
        if calls["n"] == 1:
            return _tool_call_response("ping", {})
        return _final_response("done")

    async with run_asgi_app(app, "127.0.0.1", port):
        log = await run_mission(
            agent_id="test-agent",
            persona="test",
            gateway_url=f"http://127.0.0.1:{port}/mcp",
            bearer_token=TOKEN,
            system_prompt="be helpful",
            user_task="ping once",
            chat_fn=chat_fn,
            tracer=tracer,
        )

    assert log.error is None
    # FakeUsage is 100 prompt + 20 completion per chat turn; two turns ran.
    assert log.tokens_used == 240
