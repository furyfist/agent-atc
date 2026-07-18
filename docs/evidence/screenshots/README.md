# Screenshots

5 screenshots for `docs/BLOG_DRAFT.md`, trimmed down to the most
load-bearing ones — chosen to avoid anything depending on a live pending
approval card (those resolve within seconds and can't be recreated
without re-running an experiment).

| # | Filename | Status | What it is |
|---|---|---|---|
| 1 | `01-architecture.png` | **done** (`1.png` in this folder — rename it) | Architecture diagram |
| 2 | `02-flagship-trace.png` | needed | Trace waterfall, SigNoz Traces Explorer, search `trace_id=438439cf3a4a1d2fac4ffcbe950a2e08`, full span tree expanded |
| 3 | `03-chaos-trace-gap.png` | needed | SigNoz Traces Explorer, time range 2026-07-17 19:05–19:10 UTC — visible dip in trace volume during the collector outage (19:06:43–19:07:11) |
| 4 | `04-governance-token-burn.png` | needed | Governance dashboard → "Token burn by agent and model" panel — `coder-01` should visibly dominate |
| 5 | `05-governance-denials-by-rule.png` | needed | Governance dashboard → "Denials by policy rule" panel — `FS-SENSITIVE-PATH-HIGH` should be the 100% standout bar |

Dashboards live at http://localhost:8080 (log in as `admin@atc.local`).
If "ATC - Governance" isn't listed under Dashboards yet, import it first:
New Dashboard → Import JSON → `dashboards/governance.json`.

Once all 5 are in place, swap each `[SCREENSHOT: ...]` marker in
`docs/BLOG_DRAFT.md` for a real Markdown image reference, e.g.:

```markdown
![Trace waterfall for the flagship near-miss](screenshots/02-flagship-trace.png)
```

Substack needs images uploaded into its own editor, not linked by
relative path — drag them in directly when pasting the post there.
