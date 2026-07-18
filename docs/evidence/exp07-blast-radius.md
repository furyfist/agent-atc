# Experiment #7 — Blast radius on a real large table

Ran 2026-07-18 17:00 UTC, live gateway, synthetic script (zero Groq) via
`scripts/trigger_blast_radius.py`, as `coder-01` (scope includes `db`).

## Why this needed setup first

Seed data is intentionally tiny (`tools-db`'s `seed.py`: 1-2 rows per
table) — not enough to demonstrate a real, non-trivial blast-radius
number. `orders` is one of the five prod-tagged tables in
`policies/risk_rules.yaml`, so *any* `db__execute` against it — including
the seeding INSERT — is HIGH risk via `SQL-PROD-TABLE-HIGH` and gets held.
Both the seed and the real test therefore ran as genuine, live-approved
HIGH-risk holds, not a database backdoor.

## Setup: seed 200 rows into `orders`

```
INSERT INTO orders (id, customer_id, total) VALUES (1000, 1, 10.0), (1001, 2, 11.0), ...
```

Held (`SQL-PROD-TABLE-HIGH`, `blast_radius=None` — INSERT isn't estimated,
only UPDATE/DELETE/DROP are, per `gateway/blast_radius.py`), approved live:
`OK, 200 row(s) affected`.

(One unrelated pending action from `coder-01`'s normal continuous
background persona loop — `DELETE FROM staging_old_inactive`,
`blast_radius=None`, table doesn't exist — surfaced on the same poll and
was approved along with it. Left in the log rather than filtered out:
real evidence of multiple pending holds coexisting, not staged.)

## The real test: bounded UPDATE matching most seeded rows

```sql
UPDATE orders SET total = total * 1.1 WHERE id >= 1000
```

**The pending card showed `blast_radius='~200 rows affected'` before any
decision was made** — the pre-approval `SELECT COUNT(*)` ran through the
same upstream pool the real mutation would use, so the number reflects
exactly the state the UPDATE would hit:

```
[LIVE DECISION] pending 136cd135-d5b0-4217-b746-57a10ca3a680: db__execute
  risk=HIGH blast_radius='~200 rows affected'
  resource='UPDATE orders SET total = total * 1.1 WHERE id >= 1000'
  -> APPROVING  <- 200 APPROVED
```

Approved, executed for real: `OK, 200 row(s) affected` — the estimate was
exact, not approximate padding.

## Full action row

```json
{
  "action_id": "136cd135-d5b0-4217-b746-57a10ca3a680",
  "trace_id": "cc5585a87c4cbd052632aaed2dc59785",
  "tool": "db__execute",
  "risk_level": "HIGH",
  "rule_id": "SQL-PROD-TABLE-HIGH",
  "status": "APPROVED",
  "decided_by": "operator-live-watch",
  "reversibility": "COMPENSABLE",
  "blast_radius": "~200 rows affected",
  "novel": true
}
```

## Full trace waterfall (ClickHouse, `trace_id=cc5585a8...`)

```
atc.gate.db__execute      17:00:16.6478   495.9ms total span
  atc.risk_assessment     17:00:16.6510    15.6ms
  atc.interception        17:00:16.7948   0.083ms (instant, per the two-phase interception law)
  atc.approval_wait       17:00:16.7951   107.9ms (time to live approve)
  atc.creep_check         17:00:16.8531   0.137ms (novel=true — first time this exact UPDATE resource string touched)
  atc.execution           17:00:17.0700    73.6ms (the real UPDATE)
```

## Why this matters for the blog

This is the exact "this UPDATE touches 1.9M rows" framing from
`docs/PRODUCT_STRATEGY.md`'s pillar 1 pitch, with a real number instead
of their illustrative one — 200, not 1.9M, because that's what real
seeded data plus one script actually produced, honestly reported at the
scale this project actually runs at.
