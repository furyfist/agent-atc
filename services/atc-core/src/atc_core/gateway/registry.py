"""Static agent registry: identity, scope, and bearer-token auth.
See PROJECT_PLAN.md S5, S11.

Tokens are never stored in the registry file - only the name of the env var
that holds them (S5: "Per-agent static bearer tokens... identity asserted
server-side from token, never from client _meta").
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class AgentIdentity:
    id: str
    persona: str
    scope: frozenset[str]
    owner: str | None


class AgentRegistry:
    def __init__(self, agents: list[AgentIdentity], tokens: dict[str, str]) -> None:
        self._agents_by_id = {a.id: a for a in agents}
        self._agent_id_by_token = tokens  # token value -> agent_id

    @classmethod
    def from_yaml(cls, path: str | Path) -> AgentRegistry:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        agents: list[AgentIdentity] = []
        tokens: dict[str, str] = {}

        for entry in data["agents"]:
            agent = AgentIdentity(
                id=entry["id"],
                persona=entry["persona"],
                scope=frozenset(entry["scope"]),
                owner=entry.get("owner"),
            )
            agents.append(agent)

            token_env = entry.get("token_env")
            if not token_env:
                continue
            token_value = os.environ.get(token_env)
            if not token_value:
                continue  # unconfigured token -> fails closed, agent just can't authenticate
            if token_value in tokens:
                raise ValueError(
                    f"duplicate bearer token: {token_env} collides with an "
                    f"already-registered token (agent {tokens[token_value]!r})"
                )
            tokens[token_value] = agent.id

        return cls(agents, tokens)

    def authenticate(self, bearer_token: str | None) -> AgentIdentity | None:
        if not bearer_token:
            return None
        agent_id = self._agent_id_by_token.get(bearer_token)
        return self._agents_by_id.get(agent_id) if agent_id else None

    def get(self, agent_id: str) -> AgentIdentity | None:
        return self._agents_by_id.get(agent_id)

    def all_agents(self) -> list[AgentIdentity]:
        return list(self._agents_by_id.values())

    @staticmethod
    def tool_namespace(tool_name: str) -> str:
        """'db__execute' -> 'db'."""
        return tool_name.split("__", 1)[0]

    def in_scope(self, agent: AgentIdentity, tool_name: str) -> bool:
        return self.tool_namespace(tool_name) in agent.scope
