"""Unit tests for the agent registry, run against the real shipped
policies/agents.yaml - this is the demo/blog artifact for the agent roster
(PROJECT_PLAN.md S11), so tests exercise what's actually deployed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atc_core.gateway import AgentRegistry

POLICY_PATH = Path(__file__).resolve().parents[3] / "policies" / "agents.yaml"


@pytest.fixture
def env_tokens(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    tokens = {
        "ATC_TOKEN_CODER_01": "tok-coder-01",
        "ATC_TOKEN_ASSIST_01": "tok-assist-01",
        "ATC_TOKEN_COMPLY_01": "tok-comply-01",
    }
    for env_var, value in tokens.items():
        monkeypatch.setenv(env_var, value)
    return tokens


def test_registry_loads_real_policy_file(env_tokens: dict[str, str]) -> None:
    registry = AgentRegistry.from_yaml(POLICY_PATH)
    ids = {a.id for a in registry.all_agents()}
    assert ids == {"coder-01", "assist-01", "comply-01"}


def test_coder_scope(env_tokens: dict[str, str]) -> None:
    registry = AgentRegistry.from_yaml(POLICY_PATH)
    coder = registry.get("coder-01")
    assert coder is not None
    assert coder.scope == frozenset({"db", "fs", "git"})


def test_assist_scope(env_tokens: dict[str, str]) -> None:
    registry = AgentRegistry.from_yaml(POLICY_PATH)
    assist = registry.get("assist-01")
    assert assist is not None
    assert assist.scope == frozenset({"email", "fs"})


def test_comply_scope(env_tokens: dict[str, str]) -> None:
    registry = AgentRegistry.from_yaml(POLICY_PATH)
    comply = registry.get("comply-01")
    assert comply is not None
    assert comply.scope == frozenset({"fs"})


def test_authenticate_with_valid_token(env_tokens: dict[str, str]) -> None:
    registry = AgentRegistry.from_yaml(POLICY_PATH)
    agent = registry.authenticate("tok-coder-01")
    assert agent is not None
    assert agent.id == "coder-01"


def test_authenticate_with_unknown_token_returns_none(env_tokens: dict[str, str]) -> None:
    registry = AgentRegistry.from_yaml(POLICY_PATH)
    assert registry.authenticate("not-a-real-token") is None


def test_authenticate_with_no_token_returns_none(env_tokens: dict[str, str]) -> None:
    registry = AgentRegistry.from_yaml(POLICY_PATH)
    assert registry.authenticate(None) is None
    assert registry.authenticate("") is None


def test_unconfigured_token_env_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """No env vars set at all -> no agent can authenticate as anything."""
    monkeypatch.delenv("ATC_TOKEN_CODER_01", raising=False)
    monkeypatch.delenv("ATC_TOKEN_ASSIST_01", raising=False)
    monkeypatch.delenv("ATC_TOKEN_COMPLY_01", raising=False)
    registry = AgentRegistry.from_yaml(POLICY_PATH)
    assert registry.authenticate("anything") is None
    # But the agents still exist for scope/quarantine bookkeeping.
    assert registry.get("coder-01") is not None


def test_in_scope_checks_tool_namespace(env_tokens: dict[str, str]) -> None:
    registry = AgentRegistry.from_yaml(POLICY_PATH)
    coder = registry.get("coder-01")
    comply = registry.get("comply-01")
    assert coder is not None
    assert comply is not None

    assert registry.in_scope(coder, "db__execute") is True
    assert registry.in_scope(coder, "fs__read") is True
    assert registry.in_scope(coder, "email__send") is False

    assert registry.in_scope(comply, "fs__read") is True
    assert registry.in_scope(comply, "db__query") is False


def test_tool_namespace_extraction() -> None:
    assert AgentRegistry.tool_namespace("db__execute") == "db"
    assert AgentRegistry.tool_namespace("fs__write") == "fs"
    assert AgentRegistry.tool_namespace("git__force_push") == "git"


def test_duplicate_token_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TOK_A", "same-value")
    monkeypatch.setenv("TOK_B", "same-value")
    policy = tmp_path / "agents.yaml"
    policy.write_text(
        """
agents:
  - id: agent-a
    persona: a
    scope: [fs]
    token_env: TOK_A
  - id: agent-b
    persona: b
    scope: [fs]
    token_env: TOK_B
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate bearer token"):
        AgentRegistry.from_yaml(policy)
