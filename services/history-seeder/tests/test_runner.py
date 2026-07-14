"""See PROJECT_PLAN.md S4 (history-seeder)."""

from __future__ import annotations

import random

import pytest

from atc_core.gateway import AgentIdentity, AgentRegistry
from atc_core.store import Agent, ActionStatus, Store
from history_seeder.runner import SEEDED_SETTING_KEY, run

AGENTS = [
    AgentIdentity(id="coder-01", persona="coder", scope=frozenset({"db", "fs", "git"}), owner="team"),
    AgentIdentity(id="assist-01", persona="assistant", scope=frozenset({"email", "fs"}), owner="team"),
    AgentIdentity(id="comply-01", persona="compliance", scope=frozenset({"fs"}), owner="team"),
]


@pytest.fixture
def registry() -> AgentRegistry:
    return AgentRegistry(AGENTS, tokens={})


async def test_run_seeds_actions_and_registers_agents(registry: AgentRegistry):
    store = await Store.connect(":memory:")
    try:
        seeded = await run(store, registry, days=2, now=10_000_000.0, rng=random.Random(3))

        assert seeded > 0
        for identity in AGENTS:
            assert await store.get_agent(identity.id) is not None
        actions = await store.list_actions()
        assert len(actions) == seeded
        assert await store.get_setting(SEEDED_SETTING_KEY) is not None
    finally:
        await store.close()


async def test_run_does_not_clobber_an_already_registered_agent(registry: AgentRegistry):
    """Gateway.startup() may have already registered agents (with a real
    created_at/owner) before the seeder runs - the seeder must not overwrite
    that, only fill in agents that don't exist yet."""
    store = await Store.connect(":memory:")
    try:
        await store.upsert_agent(
            Agent(
                id="coder-01", persona="coder", scope=["db", "fs", "git"], owner="team",
                quarantined=True, last_heartbeat_ts=123.0, created_at=1.0,
            )
        )
        await run(store, registry, days=1, now=10_000_000.0, rng=random.Random(3))

        coder = await store.get_agent("coder-01")
        assert coder is not None
        assert coder.quarantined is True
        assert coder.created_at == 1.0
    finally:
        await store.close()


async def test_run_is_idempotent_unless_forced(registry: AgentRegistry):
    store = await Store.connect(":memory:")
    try:
        first = await run(store, registry, days=1, now=20_000_000.0, rng=random.Random(3))
        second = await run(store, registry, days=1, now=20_000_000.0, rng=random.Random(3))
        assert first > 0
        assert second == 0

        forced = await run(store, registry, days=1, now=20_000_000.0, rng=random.Random(3), force=True)
        assert forced > 0

        actions = await store.list_actions()
        assert len(actions) == first + forced
    finally:
        await store.close()


async def test_run_leaves_no_pending_actions(registry: AgentRegistry):
    store = await Store.connect(":memory:")
    try:
        await run(store, registry, days=5, now=30_000_000.0, rng=random.Random(11))
        actions = await store.list_actions()
        assert actions
        assert all(a.status != ActionStatus.PENDING for a in actions)
    finally:
        await store.close()


async def test_run_without_tracer_still_seeds(registry: AgentRegistry):
    """tracer=None (ATC_HISTORY_BACKDATE_SPANS=false path) must not raise -
    SQLite seeding and span emission are independent outputs."""
    store = await Store.connect(":memory:")
    try:
        seeded = await run(store, registry, days=1, now=40_000_000.0, tracer=None, rng=random.Random(2))
        assert seeded > 0
    finally:
        await store.close()
