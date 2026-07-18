# Screenshot checklist

Everything below is real data already sitting in this SigNoz instance
(http://localhost:8080, admin@atc.local). Each row names the exact
trace_id/action_id already written up in the matching evidence file, so
there's no guessing which trace to pull up.

## Trace waterfalls (Traces -> search by trace_id)

| Trace ID | What it shows | Evidence file |
|---|---|---|
| `e93edeb7...` (search: `trace_id=` from exp01) | The flagship DROP -> denied -> recovery, full `atc.gate -> risk_assessment -> interception -> approval_wait -> execution` chain, twice | exp01-flagship-near-miss.md |
| `cc5585a87c4cbd052632aaed2dc59785` | Blast-radius UPDATE, `~200 rows affected` on the approval card | exp07-blast-radius.md |
| `2272694070437c6deaf253d74f92fe3e` | IRREVERSIBLE `git__push`, clean isolated span | exp11-reversibility-spectrum.md |
| `48cfe041909c67b1b18e46843ecbd806` | REVERSIBLE `db__query` slice (same trace also contains exp07's UPDATE later in the mission) | exp11-reversibility-spectrum.md |
| `e9306dfafca15f2a2f0684c6b7acb199` | coder-01's DROP TABLE orders, one of two concurrent holds | exp09-concurrent-queue.md (attempt 3) |
| `46c99c365c89b35344ee28355cc14426` | comply-01's sensitive-path write, the other concurrent hold — screenshot both side by side if the UI allows, or two separate captures with timestamps visible | exp09-concurrent-queue.md (attempt 3) |

For each: capture the full span tree expanded, not just the summary row —
the nested `atc.gate.* -> atc.risk_assessment -> atc.interception ->
atc.approval_wait -> atc.execution` shape is the actual story.

## Dashboards (Dashboards -> "ATC - Fleet Tower" / "ATC - Governance")

These have never been screenshotted before (per the original evidence
plan, dashboard JSON import itself was unverified) — this is the first
real capture opportunity.

| Panel | What to look for |
|---|---|
| Fleet Tower: Agent risk score (EWMA) | Should show a visible bump from exp06's novel-resource +20 weight and exp01/#7/#9's HIGH-risk activity |
| Fleet Tower: Interceptions (HELD calls) | A spike aligned with the experiment window (~19:00-17:10 across both sessions) |
| Fleet Tower: Actions by risk level and decision | Should roughly match the benchmark-table.md counts: 4 APPROVED / 7 DENIED / 37 EXPIRED at HIGH |
| Fleet Tower: Permission-creep events | At least one event from exp06 |
| Governance: Denials by policy rule | FS-SENSITIVE-PATH-HIGH should show 100% (3/3) — the standout bar |
| Governance: Token burn by agent and model | coder-01 should visibly dominate (52,655 of ~96,327 tokens per exp09's attribution) — this is the single most important panel for the "idle loop burns the daily budget" story |
| Governance: Rubber-stamp watch (approval latency p50) | Will show the p50 shift documented in benchmark-table.md's honesty note (19.25s -> 0.955s) — worth screenshotting with a caption explaining why, not silently |

**Missing entirely, worth adding if there's time (10 min, JSON-only per
the original plan §7):** neither dashboard has an
`atc_loops_suspected_total` panel yet, even though exp05 already proved
the metric fires. Low-effort, real gap.

## Terminal output (already captured as text — no screenshot needed)

Every experiment's raw terminal output is already verbatim in its
`docs/evidence/expNN-*.md` file — these are legitimate blog artifacts as
code blocks, not screenshots. Don't re-screenshot a terminal that already
has clean copy-pasted text.

## SQL/data artifacts worth a clean screenshot or formatted code block

- `policies/risk_rules.yaml` itself (mentioned in PROJECT_PLAN.md as "a
  demo/blog artifact") — especially the two new rules from exp10's fix
  (`SQL-UNBOUNDED-WRITE-HIGH`'s tautological-WHERE check,
  `SQL-UNRECOGNIZED-STATEMENT-HIGH`)
- The journal payload dump from exp12 (already captured as JSON in the
  evidence file — fine as a code block, no screenshot needed)

## What NOT to screenshot

Don't chase a Trace-API-key screenshot or a `/api/narrate` response — the
Narrator's Trace API path is wired but blocked on a role-permission issue
on the current key (see this session's earlier finding); it's not blog
evidence and isn't worth the detour right now.
