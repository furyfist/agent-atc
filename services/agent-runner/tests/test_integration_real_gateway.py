"""One true end-to-end test: agent-runner's run_mission against the REAL
atc-core gateway (real auth, real scope enforcement, real risk engine) and a
REAL tools-fs server - not the minimal test double in server_helpers.py.
chat_fn is still scripted (no Groq calls, no API budget spent); this proves
the *plumbing* between agent-runner and the real system works, which the
minimal-double tests in test_mission.py can't (that double doesn't check
auth at all).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from opentelemetry import trace

from agent_runner.mission import run_mission
from atc_core.app import build_full_app
from atc_core.approval import ApprovalManager
from atc_core.events import EventBus
from atc_core.gateway import AgentRegistry, Gateway, UpstreamPool
from atc_core.risk import RiskEngine
from atc_core.store import Store
from atc_telemetry import configure_tracing
from tools_db.backend import SQLiteBackend
from tools_db.server import build_server as build_db_server
from tools_fs.server import build_server as build_fs_server

from server_helpers import free_port, run_asgi_app

REPO_ROOT = Path(__file__).resolve().parents[3]
RISK_POLICY_PATH = REPO_ROOT / "policies" / "risk_rules.yaml"
AGENTS_POLICY_PATH = REPO_ROOT / "policies" / "agents.yaml"

TOKEN = "tok-comply-01"


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


@asynccontextmanager
async def real_stack(monkeypatch: pytest.MonkeyPatch, fs_root: Path) -> AsyncIterator[str]:
    monkeypatch.setenv("ATC_TOKEN_CODER_01", "tok-coder-01")
    monkeypatch.setenv("ATC_TOKEN_ASSIST_01", "tok-assist-01")
    monkeypatch.setenv("ATC_TOKEN_COMPLY_01", TOKEN)

    fs_port, db_port, gateway_port = free_port(), free_port(), free_port()
    fs_app = build_fs_server(root=fs_root, port=fs_port).streamable_http_app()
    db_backend = await SQLiteBackend.connect(":memory:")
    db_app = build_db_server(backend=db_backend, port=db_port).streamable_http_app()

    async with run_asgi_app(fs_app, "127.0.0.1", fs_port), run_asgi_app(db_app, "127.0.0.1", db_port):
        store = await Store.connect(":memory:")
        risk_engine = RiskEngine.from_yaml(RISK_POLICY_PATH)
        approval_manager = ApprovalManager(store, hold_timeout_seconds=5, event_bus=EventBus())
        registry = AgentRegistry.from_yaml(AGENTS_POLICY_PATH)

        # Both connected (matching what coder-01 would see) so comply-01's
        # scope violation below is a *real* scope violation - the tool
        # exists upstream, comply-01 just isn't allowed to reach it - not a
        # false "unknown tool" result from db never being connected at all.
        upstream = UpstreamPool()
        await upstream.connect(
            {"fs": f"http://127.0.0.1:{fs_port}/mcp", "db": f"http://127.0.0.1:{db_port}/mcp"}
        )

        tracer = configure_tracing("test-integration")
        gateway = Gateway(
            registry=registry,
            risk_engine=risk_engine,
            approval_manager=approval_manager,
            store=store,
            upstream=upstream,
            tracer=tracer,
        )
        app = build_full_app(
            gateway=gateway, store=store, approval_manager=approval_manager, event_bus=EventBus()
        )

        async with run_asgi_app(app, "127.0.0.1", gateway_port):
            try:
                yield f"http://127.0.0.1:{gateway_port}/mcp"
            finally:
                await upstream.close()
                await store.close()
                await db_backend.close()


async def test_comply_01_reads_a_real_file_through_the_real_gateway(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "compliance-policy.txt").write_text("Retain records for 7 years.")

    async with real_stack(monkeypatch, tmp_path) as gateway_url:
        calls = {"n": 0}

        async def chat_fn(messages, tools):
            calls["n"] += 1
            if calls["n"] == 1:
                tc = FakeToolCall(
                    id="c1",
                    function=FakeFunction(
                        name="fs__read", arguments=json.dumps({"path": "compliance-policy.txt"})
                    ),
                )
                return FakeResponse(choices=[FakeChoice(message=FakeMessage(content=None, tool_calls=[tc]))])
            return FakeResponse(
                choices=[FakeChoice(message=FakeMessage(content="Retain records 7 years.", tool_calls=None))]
            )

        log = await run_mission(
            agent_id="comply-01",
            persona="compliance",
            gateway_url=gateway_url,
            bearer_token=TOKEN,
            system_prompt="be a compliance agent",
            user_task="Read compliance-policy.txt and summarize it.",
            chat_fn=chat_fn,
            tracer=trace.get_tracer("test"),
        )

    assert log.error is None
    assert len(log.tool_calls) == 1
    assert log.tool_calls[0].tool == "fs__read"
    assert "Retain records for 7 years." == log.tool_calls[0].result_text
    assert log.final_message == "Retain records 7 years."


async def test_wrong_scope_call_is_denied_by_the_real_gateway(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """comply-01's scope is fs-only (S11) - a db__query attempt must be
    denied by the real gateway's scope enforcement, proving agent-runner
    correctly surfaces that denial rather than erroring out."""
    async with real_stack(monkeypatch, tmp_path) as gateway_url:
        async def chat_fn(messages, tools):
            tc = FakeToolCall(
                id="c1", function=FakeFunction(name="db__query", arguments=json.dumps({"sql": "SELECT 1"}))
            )
            return FakeResponse(choices=[FakeChoice(message=FakeMessage(content=None, tool_calls=[tc]))])

        log = await run_mission(
            agent_id="comply-01",
            persona="compliance",
            gateway_url=gateway_url,
            bearer_token=TOKEN,
            system_prompt="be a compliance agent",
            user_task="try to query the database (out of scope)",
            chat_fn=chat_fn,
            tracer=trace.get_tracer("test"),
            max_turns=1,
        )

    assert log.error is None
    assert len(log.tool_calls) == 1
    assert "[ATC-DENIED] reason=scope_violation" in log.tool_calls[0].result_text
