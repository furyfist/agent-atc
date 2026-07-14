"""atc-core entrypoint: wires the gateway, REST/WS API, static UI, and
Narrator into one running process. See PROJECT_PLAN.md S4.

Config is entirely via environment variables so the same image works
unmodified across local dev and docker-compose - the plan's own "local <->
Cloud migration mechanism" principle (S4) applied to service wiring, not
just the OTel collector.

Everything async (Store, UpstreamPool, the uvicorn server itself) is built
and run inside ONE `asyncio.run()` call, not split across a separate
pre-build step and `uvicorn.run()`'s own internal loop - aiosqlite
connections and the MCP client's anyio task groups don't survive a loop
handoff (found the hard way building tools-db's server.py).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from groq import AsyncGroq

from atc_core.app import build_full_app
from atc_core.approval import ApprovalManager
from atc_core.events import EventBus
from atc_core.gateway import AgentRegistry, Gateway, UpstreamPool
from atc_core.narrator import ActionStoreSpanFetcher, Narrator, make_groq_chat_fn
from atc_core.risk import RiskEngine
from atc_core.store import Store
from atc_telemetry import configure_tracing

REPO_ROOT = Path(__file__).resolve().parents[4]
PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def _env_path(var: str, default: Path) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else default


async def _real_main() -> None:
    load_dotenv(REPO_ROOT / ".env")

    risk_policy_path = _env_path("ATC_RISK_POLICY_PATH", REPO_ROOT / "policies" / "risk_rules.yaml")
    agents_policy_path = _env_path("ATC_AGENTS_POLICY_PATH", REPO_ROOT / "policies" / "agents.yaml")
    sqlite_path = os.environ.get(
        "ATC_SQLITE_PATH", str(PACKAGE_ROOT / "volume" / "atc.sqlite3")
    )
    static_dir = _env_path("ATC_STATIC_DIR", PACKAGE_ROOT / "static")
    hold_timeout = float(os.environ.get("ATC_HOLD_TIMEOUT_SECONDS", "120"))
    host = os.environ.get("ATC_HOST", "0.0.0.0")
    port = int(os.environ.get("ATC_PORT", "8000"))

    Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)

    store = await Store.connect(sqlite_path)
    risk_engine = RiskEngine.from_yaml(risk_policy_path)
    event_bus = EventBus()
    approval_manager = ApprovalManager(store, hold_timeout_seconds=hold_timeout, event_bus=event_bus)
    registry = AgentRegistry.from_yaml(agents_policy_path)

    upstream = UpstreamPool()
    # Container DNS names in docker-compose (S4's service topology); plain
    # localhost ports for `uv run atc-core` in local dev without Docker.
    upstream_urls = {
        "db": os.environ.get("ATC_TOOLS_DB_URL", "http://127.0.0.1:9001/mcp"),
        "fs": os.environ.get("ATC_TOOLS_FS_URL", "http://127.0.0.1:9002/mcp"),
        "git": os.environ.get("ATC_TOOLS_GIT_URL", "http://127.0.0.1:9003/mcp"),
    }
    await upstream.connect(upstream_urls)

    tracer = configure_tracing("atc-core")
    gateway = Gateway(
        registry=registry,
        risk_engine=risk_engine,
        approval_manager=approval_manager,
        store=store,
        upstream=upstream,
        tracer=tracer,
    )

    narrator = None
    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key:
        narrator = Narrator(
            store=store,
            span_fetcher=ActionStoreSpanFetcher(store),
            chat_fn=make_groq_chat_fn(AsyncGroq(api_key=groq_key)),
        )

    app = build_full_app(
        gateway=gateway,
        store=store,
        approval_manager=approval_manager,
        event_bus=event_bus,
        narrator=narrator,
        static_dir=static_dir,
    )

    config = uvicorn.Config(app, host=host, port=port)
    server = uvicorn.Server(config)
    try:
        await server.serve()
    finally:
        await upstream.close()
        await store.close()


def main() -> None:
    asyncio.run(_real_main())


if __name__ == "__main__":
    main()
