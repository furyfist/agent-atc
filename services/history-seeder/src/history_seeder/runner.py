"""Orchestrates one seeding run: registers agents if not already present
(mirroring atc_core.gateway.server.Gateway.startup's own idempotent
upsert, so this works whether or not atc-core has booted first), generates
history, writes it to the store, and optionally emits backdated spans.

Idempotent via the `settings` table so a re-run (e.g. every `docker compose
up`) doesn't duplicate history; `make reset-demo` passes force=True after
clearing the SQLite file anyway, but force exists so the seeder can also be
re-run standalone without a full reset.
"""

from __future__ import annotations

import random
import time

from opentelemetry import trace

from atc_core.gateway import AgentRegistry
from atc_core.store import Agent, Store
from history_seeder.seed import emit_backdated_spans, generate_history

SEEDED_SETTING_KEY = "history_seeded_at"


async def run(
    store: Store,
    registry: AgentRegistry,
    *,
    days: int,
    tracer: trace.Tracer | None = None,
    force: bool = False,
    now: float | None = None,
    rng: random.Random | None = None,
) -> int:
    """Returns the number of actions seeded (0 if skipped as already-seeded)."""
    if not force:
        existing = await store.get_setting(SEEDED_SETTING_KEY)
        if existing is not None:
            return 0

    resolved_now = now if now is not None else time.time()
    resolved_rng = rng if rng is not None else random.Random()

    agents = registry.all_agents()
    for identity in agents:
        stored = await store.get_agent(identity.id)
        if stored is None:
            await store.upsert_agent(
                Agent(
                    id=identity.id,
                    persona=identity.persona,
                    scope=sorted(identity.scope),
                    owner=identity.owner,
                    quarantined=False,
                    last_heartbeat_ts=None,
                    created_at=resolved_now,
                )
            )

    actions = generate_history(agents, days=days, now=resolved_now, rng=resolved_rng)
    for action in actions:
        await store.insert_action(action)

    if tracer is not None:
        emit_backdated_spans(tracer, actions)

    await store.set_setting(SEEDED_SETTING_KEY, str(resolved_now))
    return len(actions)
