# Screenshot checklist

Trimmed to the 5 most load-bearing screenshots (down from an original
11) — see `docs/evidence/screenshots/README.md` for filenames. Cut
everything that depended on a live pending-approval card, since those
resolve within seconds and can't be recreated without re-running an
experiment live.

## 1. Architecture diagram — done

Already in `docs/evidence/screenshots/` (`1.png`, rename to
`01-architecture.png`).

## 2. Flagship near-miss trace waterfall

SigNoz → Traces Explorer → search `trace_id=438439cf3a4a1d2fac4ffcbe950a2e08`
→ expand the full span tree. Shows the DROP TABLE denial and the
recovered RENAME, both gate-side chains
(`atc.gate → atc.risk_assessment → atc.interception → atc.approval_wait
→ atc.execution`). See `exp01-flagship-near-miss.md`.

## 3. Chaos test — trace volume gap

SigNoz → Traces Explorer → time range **2026-07-17 19:05–19:10 UTC**
(outage ran 19:06:43–19:07:11) → the trace-volume/count-over-time graph
should show a visible dip and recovery. See `exp08-chaos-collector.md`.

## 4. Governance dashboard — token burn by agent

If "ATC - Governance" isn't imported yet: Dashboards → New Dashboard →
Import JSON → `dashboards/governance.json`. Panel: "Token burn by agent
and model" — `coder-01` should visibly dominate (52,655 of ~96,327
tokens per `exp09-concurrent-queue.md`'s attribution). This is the
single most important panel — it backs the strongest claim in the post
(an idle 3-agent fleet exhausts a day's free-tier Groq budget in under
two hours).

## 5. Governance dashboard — denials by policy rule

Same dashboard. Panel: "Denials by policy rule" — `FS-SENSITIVE-PATH-HIGH`
should be the 100% (3/3) standout bar. See `benchmark-table.md`.

## Everything else — kept as text, not screenshots

- The red-team before/after (exp10) is already exact terminal text in
  the blog draft's code block — no screenshot needed.
- Blast radius, reversibility spectrum, journal capture, and the
  concurrent-hold-queue timing are all backed by real trace_ids and
  JSON already quoted directly in the post and in `docs/evidence/`.
- `policies/risk_rules.yaml` is linked directly via GitHub permalink,
  not screenshotted.

## What NOT to screenshot

Don't chase a Trace-API-key screenshot or a `/api/narrate` response — the
Narrator's Trace API path is wired but blocked on a role-permission issue
on the current key; it's not blog evidence.
