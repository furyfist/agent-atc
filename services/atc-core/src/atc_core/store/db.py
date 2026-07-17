"""Async SQLite persistence for agents/actions/narrations/settings.

Thin CRUD layer only - no business logic (see atc_core.approval.manager for
the interception state machine). One Store wraps one long-lived connection;
callers are expected to serialize access via the single asyncio event loop
(no internal locking - aiosqlite serializes writes on its own connection).
"""

from __future__ import annotations

import json
from pathlib import Path

import aiosqlite

from atc_core.risk.models import RiskLevel
from atc_core.store.models import Action, ActionStatus, Agent
from atc_core.store.schema import MIGRATION_SQL, SCHEMA_SQL


class Store:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    @classmethod
    async def connect(cls, path: str | Path = ":memory:") -> Store:
        conn = await aiosqlite.connect(path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        store = cls(conn)
        await store._init_schema()
        return store

    async def close(self) -> None:
        await self._conn.close()

    async def _init_schema(self) -> None:
        await self._conn.executescript(SCHEMA_SQL)
        for statement in MIGRATION_SQL:
            # Fresh DBs already have these columns from SCHEMA_SQL; existing
            # DBs gain them here. SQLite has no ADD COLUMN IF NOT EXISTS, so
            # "duplicate column name" is the expected no-op signal.
            try:
                await self._conn.execute(statement)
            except aiosqlite.OperationalError as exc:
                if "duplicate column name" not in str(exc):
                    raise
        await self._conn.commit()

    # --- agents --------------------------------------------------------

    async def upsert_agent(self, agent: Agent) -> None:
        await self._conn.execute(
            """
            INSERT INTO agents (id, persona, scope_json, owner, quarantined, last_heartbeat_ts, created_at)
            VALUES (:id, :persona, :scope_json, :owner, :quarantined, :last_heartbeat_ts, :created_at)
            ON CONFLICT (id) DO UPDATE SET
                persona = excluded.persona,
                scope_json = excluded.scope_json,
                owner = excluded.owner
            """,
            {
                "id": agent.id,
                "persona": agent.persona,
                "scope_json": json.dumps(agent.scope),
                "owner": agent.owner,
                "quarantined": int(agent.quarantined),
                "last_heartbeat_ts": agent.last_heartbeat_ts,
                "created_at": agent.created_at,
            },
        )
        await self._conn.commit()

    async def get_agent(self, agent_id: str) -> Agent | None:
        cur = await self._conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
        row = await cur.fetchone()
        return _agent_from_row(row) if row else None

    async def list_agents(self) -> list[Agent]:
        cur = await self._conn.execute("SELECT * FROM agents ORDER BY id")
        rows = await cur.fetchall()
        return [_agent_from_row(row) for row in rows]

    async def set_quarantined(self, agent_id: str, quarantined: bool) -> None:
        await self._conn.execute(
            "UPDATE agents SET quarantined = ? WHERE id = ?", (int(quarantined), agent_id)
        )
        await self._conn.commit()

    async def record_heartbeat(self, agent_id: str, ts: float) -> None:
        await self._conn.execute(
            "UPDATE agents SET last_heartbeat_ts = ? WHERE id = ?", (ts, agent_id)
        )
        await self._conn.commit()

    async def set_tokens_used(self, agent_id: str, tokens_used: float) -> None:
        """Cumulative total as reported by the agent's own heartbeat - a
        plain overwrite, not an increment, so a redelivered heartbeat can't
        double-count."""
        await self._conn.execute(
            "UPDATE agents SET tokens_used = ? WHERE id = ?", (tokens_used, agent_id)
        )
        await self._conn.commit()

    # --- actions ---------------------------------------------------------

    async def insert_action(self, action: Action) -> None:
        await self._conn.execute(
            """
            INSERT INTO actions (
                action_id, trace_id, span_id, agent_id, tool, resource_class,
                resource_name, args_summary, risk_level, risk_reason, rule_id,
                status, decided_by, requested_at, resolved_at, reversibility,
                blast_radius, novel
            ) VALUES (
                :action_id, :trace_id, :span_id, :agent_id, :tool, :resource_class,
                :resource_name, :args_summary, :risk_level, :risk_reason, :rule_id,
                :status, :decided_by, :requested_at, :resolved_at, :reversibility,
                :blast_radius, :novel
            )
            """,
            _action_to_params(action),
        )
        await self._conn.commit()

    async def mark_novel(self, action_id: str) -> None:
        await self._conn.execute("UPDATE actions SET novel = 1 WHERE action_id = ?", (action_id,))
        await self._conn.commit()

    async def get_action(self, action_id: str) -> Action | None:
        cur = await self._conn.execute("SELECT * FROM actions WHERE action_id = ?", (action_id,))
        row = await cur.fetchone()
        return _action_from_row(row) if row else None

    async def list_actions(self, status: ActionStatus | None = None) -> list[Action]:
        if status is None:
            cur = await self._conn.execute("SELECT * FROM actions ORDER BY requested_at DESC")
        else:
            cur = await self._conn.execute(
                "SELECT * FROM actions WHERE status = ? ORDER BY requested_at DESC", (status.value,)
            )
        rows = await cur.fetchall()
        return [_action_from_row(row) for row in rows]

    async def resolve_action(
        self, action_id: str, *, status: ActionStatus, decided_by: str | None, resolved_at: float
    ) -> bool:
        """Resolves a PENDING action. Guarded by `WHERE status = PENDING` so a
        human decision and a hold-timeout expiry racing at the 120s boundary
        can't double-resolve or clobber each other - whichever commits first
        wins, the loser's update affects zero rows. Returns whether this call
        was the one that resolved it."""
        cur = await self._conn.execute(
            "UPDATE actions SET status = ?, decided_by = ?, resolved_at = ? WHERE action_id = ? AND status = ?",
            (status.value, decided_by, resolved_at, action_id, ActionStatus.PENDING.value),
        )
        await self._conn.commit()
        return cur.rowcount > 0

    # --- narrations --------------------------------------------------------

    async def upsert_narration(self, trace_id: str, text: str, created_at: float) -> None:
        await self._conn.execute(
            """
            INSERT INTO narrations (trace_id, text, created_at) VALUES (?, ?, ?)
            ON CONFLICT (trace_id) DO UPDATE SET text = excluded.text, created_at = excluded.created_at
            """,
            (trace_id, text, created_at),
        )
        await self._conn.commit()

    async def get_narration(self, trace_id: str) -> str | None:
        cur = await self._conn.execute("SELECT text FROM narrations WHERE trace_id = ?", (trace_id,))
        row = await cur.fetchone()
        return row["text"] if row else None

    # --- settings ------------------------------------------------------

    async def get_setting(self, key: str) -> str | None:
        cur = await self._conn.execute("SELECT v FROM settings WHERE k = ?", (key,))
        row = await cur.fetchone()
        return row["v"] if row else None

    async def set_setting(self, key: str, value: str) -> None:
        await self._conn.execute(
            "INSERT INTO settings (k, v) VALUES (?, ?) ON CONFLICT (k) DO UPDATE SET v = excluded.v",
            (key, value),
        )
        await self._conn.commit()


def _agent_from_row(row: aiosqlite.Row) -> Agent:
    return Agent(
        id=row["id"],
        persona=row["persona"],
        scope=json.loads(row["scope_json"]),
        owner=row["owner"],
        quarantined=bool(row["quarantined"]),
        last_heartbeat_ts=row["last_heartbeat_ts"],
        created_at=row["created_at"],
        tokens_used=row["tokens_used"],
    )


def _action_to_params(action: Action) -> dict:
    return {
        "action_id": action.action_id,
        "trace_id": action.trace_id,
        "span_id": action.span_id,
        "agent_id": action.agent_id,
        "tool": action.tool,
        "resource_class": action.resource_class,
        "resource_name": action.resource_name,
        "args_summary": action.args_summary,
        "risk_level": action.risk_level.value,
        "risk_reason": action.risk_reason,
        "rule_id": action.rule_id,
        "status": action.status.value,
        "decided_by": action.decided_by,
        "requested_at": action.requested_at,
        "resolved_at": action.resolved_at,
        "reversibility": action.reversibility,
        "blast_radius": action.blast_radius,
        "novel": int(action.novel),
    }


def _action_from_row(row: aiosqlite.Row) -> Action:
    return Action(
        action_id=row["action_id"],
        trace_id=row["trace_id"],
        span_id=row["span_id"],
        agent_id=row["agent_id"],
        tool=row["tool"],
        resource_class=row["resource_class"],
        resource_name=row["resource_name"],
        args_summary=row["args_summary"],
        risk_level=RiskLevel(row["risk_level"]),
        risk_reason=row["risk_reason"],
        rule_id=row["rule_id"],
        status=ActionStatus(row["status"]),
        decided_by=row["decided_by"],
        requested_at=row["requested_at"],
        resolved_at=row["resolved_at"],
        reversibility=row["reversibility"],
        blast_radius=row["blast_radius"],
        novel=bool(row["novel"]),
    )
