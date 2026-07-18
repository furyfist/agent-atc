"""agent-runner entrypoint: runs coder-01, assist-01, comply-01 as concurrent
asyncio tasks (S4: "One container, 3 asyncio agent loops"), each against the
real gateway with its own bearer token.

Two independent cadences run concurrently for the life of the process:
  - a heartbeat loop (fast, no LLM call - just a REST POST) so Fleet Tower's
    "agent is alive" signal (agent_heartbeat gauge, S6) stays current even
    between missions.
  - a mission loop (slow - each mission burns real Groq tokens/RPM against
    S3's tight free-tier budget) that re-runs each persona's task on
    ATC_MISSION_INTERVAL_SECONDS. This is what makes the fleet "live" for
    the demo (S11) instead of one-shot-and-exit.
Both loops keep running (logging and continuing) past a single mission's
error so one persona's failure never takes down the others' heartbeats.
"""

from __future__ import annotations

import asyncio
import functools
import os
from pathlib import Path

import httpx
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
DEFAULT_HEARTBEAT_URL = "http://127.0.0.1:9000"

# S6: "recomputed on the heartbeat cadence (~30s)".
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 30.0
# Generous default so 3 personas x repeated missions stay well inside Groq's
# free-tier RPM/RPD ceiling (S3) even if a mission takes several turns.
DEFAULT_MISSION_INTERVAL_SECONDS = 300.0


def _print_result(log: MissionLog) -> None:
    status = "ERROR" if log.error else ("DENIED (unresolved)" if log.denied and not log.final_message else "OK")
    print(f"[{log.agent_id}] {status} turns={log.turns} tool_calls={len(log.tool_calls)}")
    for tc in log.tool_calls:
        print(f"  {tc.tool}({tc.arguments}) -> {tc.result_text[:120]}")
    if log.final_message:
        print(f"  final: {log.final_message}")
    if log.error:
        print(f"  error: {log.error}")


async def _heartbeat_loop(
    http_client: httpx.AsyncClient,
    agent_ids: list[str],
    interval_seconds: float,
    usage_totals: dict[str, int],
) -> None:
    """Runs forever. A failed POST (atc-core briefly unreachable, etc.) is
    logged and skipped, never raised - S9's fire-and-forget telemetry law
    applies to liveness reporting too: it must never crash the runner.

    Each beat carries the agent's cumulative token usage (fed by the mission
    loop after each mission) so atc-core's budget breaker sees spend on the
    heartbeat cadence, not just at process exit."""
    while True:
        for agent_id in agent_ids:
            try:
                resp = await http_client.post(
                    f"/api/agents/{agent_id}/heartbeat",
                    json={"tokens_used": usage_totals.get(agent_id, 0)},
                )
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                print(f"[{agent_id}] heartbeat failed: {exc}")
        await asyncio.sleep(interval_seconds)


async def _mission_loop(
    persona: Persona,
    *,
    gateway_url: str,
    token: str,
    chat_fn,
    tracer,
    instruments,
    interval_seconds: float,
    usage_totals: dict[str, int],
) -> None:
    """Runs forever, re-running this persona's mission every
    interval_seconds. A mission that errors is logged and retried next
    cycle rather than ending the loop - one bad run must not permanently
    kill this agent's presence in the fleet."""
    while True:
        log = await run_mission(
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
        usage_totals[persona.agent_id] = usage_totals.get(persona.agent_id, 0) + log.tokens_used
        _print_result(log)
        await asyncio.sleep(interval_seconds)


async def main() -> int:
    repo_root = Path(__file__).resolve().parents[4]
    load_dotenv(repo_root / ".env")

    groq_key = os.environ.get("GROQ_API_KEY")
    if not groq_key:
        print("GROQ_API_KEY not set. Add it to the repo-root .env and re-run.")
        return 2

    gateway_url = os.environ.get("ATC_GATEWAY_URL", DEFAULT_GATEWAY_URL)
    heartbeat_base_url = os.environ.get("ATC_HEARTBEAT_URL", DEFAULT_HEARTBEAT_URL)
    heartbeat_interval = float(
        os.environ.get("ATC_HEARTBEAT_INTERVAL_SECONDS", DEFAULT_HEARTBEAT_INTERVAL_SECONDS)
    )
    mission_interval = float(
        os.environ.get("ATC_MISSION_INTERVAL_SECONDS", DEFAULT_MISSION_INTERVAL_SECONDS)
    )

    groq_client = AsyncGroq(api_key=groq_key)
    tracer = configure_tracing("agent-runner")
    instruments = configure_metrics("agent-runner")
    chat_fn = functools.partial(chat_with_backoff, groq_client)

    runnable_personas: list[tuple[Persona, str]] = []
    for persona in ALL_PERSONAS:
        token_env = TOKEN_ENV_VARS[persona.agent_id]
        token = os.environ.get(token_env)
        if not token:
            print(f"[{persona.agent_id}] {token_env} not set - this agent will not run")
            continue
        runnable_personas.append((persona, token))

    if not runnable_personas:
        print("No agent tokens set. Add them to the repo-root .env and re-run.")
        return 2

    usage_totals: dict[str, int] = {}

    async with httpx.AsyncClient(base_url=heartbeat_base_url, timeout=10.0) as http_client:
        tasks = [
            asyncio.create_task(
                _heartbeat_loop(
                    http_client,
                    [p.agent_id for p, _ in runnable_personas],
                    heartbeat_interval,
                    usage_totals,
                )
            )
        ]
        tasks += [
            asyncio.create_task(
                _mission_loop(
                    persona,
                    gateway_url=gateway_url,
                    token=token,
                    chat_fn=chat_fn,
                    tracer=tracer,
                    instruments=instruments,
                    interval_seconds=mission_interval,
                    usage_totals=usage_totals,
                )
            )
            for persona, token in runnable_personas
        ]
        await asyncio.gather(*tasks)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
