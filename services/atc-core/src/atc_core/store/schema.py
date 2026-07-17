"""SQLite schema. See PROJECT_PLAN.md S9.

Additive columns land twice: in CREATE TABLE for fresh databases AND in
MIGRATION_SQL for databases created before the column existed. Migrations
must stay individually idempotent-on-error (duplicate-column failures are
swallowed by Store._init_schema) - SQLite has no ADD COLUMN IF NOT EXISTS.
"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    persona TEXT NOT NULL,
    scope_json TEXT NOT NULL,
    owner TEXT,
    quarantined INTEGER NOT NULL DEFAULT 0,
    last_heartbeat_ts REAL,
    created_at REAL NOT NULL,
    tokens_used REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS actions (
    action_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    span_id TEXT,
    agent_id TEXT NOT NULL,
    tool TEXT NOT NULL,
    resource_class TEXT,
    resource_name TEXT,
    args_summary TEXT,
    risk_level TEXT NOT NULL,
    risk_reason TEXT,
    rule_id TEXT NOT NULL,
    status TEXT NOT NULL,
    decided_by TEXT,
    requested_at REAL NOT NULL,
    resolved_at REAL,
    reversibility TEXT,
    blast_radius TEXT,
    novel INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (agent_id) REFERENCES agents (id)
);

CREATE INDEX IF NOT EXISTS idx_actions_status ON actions (status);
CREATE INDEX IF NOT EXISTS idx_actions_agent_id ON actions (agent_id);

CREATE TABLE IF NOT EXISTS narrations (
    trace_id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    k TEXT PRIMARY KEY,
    v TEXT
);
"""

MIGRATION_SQL = [
    "ALTER TABLE agents ADD COLUMN tokens_used REAL NOT NULL DEFAULT 0",
    "ALTER TABLE actions ADD COLUMN reversibility TEXT",
    "ALTER TABLE actions ADD COLUMN blast_radius TEXT",
    "ALTER TABLE actions ADD COLUMN novel INTEGER NOT NULL DEFAULT 0",
]
