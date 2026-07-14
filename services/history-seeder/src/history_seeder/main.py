"""history-seeder entrypoint: one-shot compose-profile job (PROJECT_PLAN.md
S4's service table) that backfills baseline history before the first live
demo run. Idempotent - safe to include in every `docker compose up`;
`make reset-demo` re-runs it with ATC_HISTORY_FORCE=1 after clearing the
SQLite file.

Same config-via-env-vars, one-asyncio.run-call shape as atc-core/agent-
runner's own main.py (see atc_core/main.py's docstring for why the async
setup can't be split across separate asyncio.run calls).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

from atc_core.gateway import AgentRegistry
from atc_core.store import Store
from atc_telemetry import configure_tracing
from history_seeder.runner import run

REPO_ROOT = Path(__file__).resolve().parents[4]
PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def _env_bool(var: str, default: bool) -> bool:
    value = os.environ.get(var)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes")


async def _real_main() -> None:
    load_dotenv(REPO_ROOT / ".env")

    agents_policy_path = os.environ.get(
        "ATC_AGENTS_POLICY_PATH", str(REPO_ROOT / "policies" / "agents.yaml")
    )
    sqlite_path = os.environ.get("ATC_SQLITE_PATH", str(PACKAGE_ROOT / "volume" / "atc.sqlite3"))
    days = int(os.environ.get("ATC_HISTORY_DAYS", "5"))
    force = _env_bool("ATC_HISTORY_FORCE", False)
    backdate_spans = _env_bool("ATC_HISTORY_BACKDATE_SPANS", True)

    Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)

    store = await Store.connect(sqlite_path)
    registry = AgentRegistry.from_yaml(agents_policy_path)
    tracer = configure_tracing("history-seeder") if backdate_spans else None

    try:
        seeded = await run(store, registry, days=days, tracer=tracer, force=force)
        print(f"history-seeder: seeded {seeded} actions across {len(registry.all_agents())} agents")
    finally:
        await store.close()


def main() -> None:
    asyncio.run(_real_main())


if __name__ == "__main__":
    main()
