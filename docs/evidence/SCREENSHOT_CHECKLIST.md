# Screenshot checklist

Down to 4 screenshots (from an original 11, then 5, now 4 — the
"denials by policy rule" dashboard panel turned out to be broken and was
replaced with a real table in the post text instead. See
`docs/evidence/screenshots/README.md` for the reason).

## 1. Architecture diagram — done

Wired into `docs/BLOG_DRAFT.md`.

## 2. Flagship near-miss trace waterfall — done

Wired into `docs/BLOG_DRAFT.md`. Verified: shows trace
`438439cf3a4a1d2fac4ffcbe950a2e08`, service `flagship-near-miss`, the
real `agent.mission → agent.turn → gen_ai.chat / mcp.tool.call →
atc.gate.db_query → atc.risk_assessment` span tree.

## 3. Chaos test — trace volume gap — needs retake

First attempt used the default 3-day time range; the outage (28 seconds,
19:06:43–19:07:11 UTC on 2026-07-17) is invisible at that scale. Retake
with the time range narrowed to **19:00:00–19:15:00 UTC** on 2026-07-17.
See `docs/evidence/screenshots/README.md` for exact steps.

## 4. Governance dashboard — token burn by agent — done

Wired into `docs/BLOG_DRAFT.md`. Verified: `coder-01` (orange) visibly
dominates over `assist-01` and `comply-01` for most of the session —
matches the claim in the post.

## Dropped: denials by policy rule

The dashboard panel groups by `risk`, not `rule_id` — checked
`services/atc-core/src/atc_core/gateway/server.py`'s
`actions_total.add()` calls directly: the metric only carries
`agent_id`, `risk`, `decision`. `rule_id` only exists as a span
attribute (`policy.rule_id`) and a SQLite column, never as a metric
dimension. The panel's title/description promise something the
telemetry contract doesn't support. Replaced with the real per-rule
table (already in `benchmark-table.md`) inlined directly into the blog
post's "By the numbers" section — more accurate than a broken graph
would have been.

## Everything else — kept as text, not screenshots

- The red-team before/after (exp10) is exact terminal text in a code
  block already.
- Blast radius, reversibility spectrum, journal capture, and the
  concurrent-hold-queue timing are all backed by real trace_ids and JSON
  quoted directly in the post and in `docs/evidence/`.
- `policies/risk_rules.yaml` is linked via GitHub permalink, not
  screenshotted.

## What NOT to screenshot

Don't chase a Trace-API-key screenshot or a `/api/narrate` response — the
Narrator's Trace API path is wired but blocked on a role-permission issue
on the current key; it's not blog evidence.
