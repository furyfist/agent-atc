"""agent-runner entrypoint: runs coder-01, assist-01, comply-01 as concurrent
asyncio tasks (S4: "One container, 3 asyncio agent loops"), each against the
real gateway with its own bearer token.
"""

from __future__ import annotations

import asyncio
import functools
import os
from pathlib import Path

from dotenv import load_dotenv
from groq import AsyncGroq

from agent_runner.groq_client import chat_with_backoff
from agent_runner.mission import MissionLog, run_mission
from agent_runner.personas import ALL_PERSONAS, Persona
from atc_telemetry import configure_metrics, configure_tracing

# Matches the env var names in .env.example / policies/agents.yaml's
# token_env fields - agent-runner is a separate service from atc-core (talks
# to it only over MCP), so it names these directly rather than importing
# atc-core's AgentRegistry just to read a mapping.
TOKEN_ENV_VARS = {
    "coder-01": "ATC_TOKEN_CODER_01",
    "assist-01": "ATC_TOKEN_ASSIST_01",
    "comply-01": "ATC_TOKEN_COMPLY_01",
}

DEFAULT_GATEWAY_URL = "http://127.0.0.1:9000/mcp"


def _print_result(log: MissionLog) -> None:
    status = "ERROR" if log.error else ("DENIED (unresolved)" if log.denied and not log.final_message else "OK")
    print(f"[{log.agent_id}] {status} turns={log.turns} tool_calls={len(log.tool_calls)}")
    for tc in log.tool_calls:
        print(f"  {tc.tool}({tc.arguments}) -> {tc.result_text[:120]}")
    if log.final_message:
        print(f"  final: {log.final_message}")
    if log.error:
        print(f"  error: {log.error}")


async def main() -> int:
    repo_root = Path(__file__).resolve().parents[4]
    load_dotenv(repo_root / ".env")

    groq_key = os.environ.get("GROQ_API_KEY")
    if not groq_key:
        print("GROQ_API_KEY not set. Add it to the repo-root .env and re-run.")
        return 2

    gateway_url = os.environ.get("ATC_GATEWAY_URL", DEFAULT_GATEWAY_URL)
    client = AsyncGroq(api_key=groq_key)
    tracer = configure_tracing("agent-runner")
    instruments = configure_metrics("agent-runner")

    async def run_one(persona: Persona) -> MissionLog:
        token_env = TOKEN_ENV_VARS[persona.agent_id]
        token = os.environ.get(token_env)
        if not token:
            log = MissionLog(agent_id=persona.agent_id)
            log.error = f"{token_env} not set"
            return log

        chat_fn = functools.partial(chat_with_backoff, client)
        return await run_mission(
            agent_id=persona.agent_id,
            persona=persona.agent_id.split("-")[0],
            gateway_url=gateway_url,
            bearer_token=token,
            system_prompt=persona.system_prompt,
            user_task=persona.user_task,
            chat_fn=chat_fn,
            tracer=tracer,
            instruments=instruments,
        )

    results = await asyncio.gather(*(run_one(p) for p in ALL_PERSONAS))
    for log in results:
        _print_result(log)

    return 1 if any(log.error for log in results) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
