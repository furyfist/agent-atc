# Screenshots

4 screenshots for `docs/BLOG_DRAFT.md` (down from 5 — the "denials by
policy rule" dashboard panel turned out to be broken: `atc_actions_total`
never carries a `rule_id` label, only `agent_id`/`risk`/`decision`, so
that panel can't show what its own title promises. Replaced with a real
table pulled from the SQLite action log directly in the post instead).

| # | Filename | Status |
|---|---|---|
| 1 | `01-architecture.png` | **done**, wired into the post |
| 2 | `02-flagship-trace.png` | **done**, wired into the post |
| 3 | `03-chaos-trace-gap.png` | **needs retake** — see below |
| 4 | `04-governance-token-burn.png` | **done**, wired into the post |

## #3 needs a retake

The first attempt (`03.png`, now deleted) used the default 3-day time
range, at which scale the ~28-second collector outage is invisible.
Retake it:

1. SigNoz → Traces Explorer → Time Series view
2. Set the time range to **17/07/2026 19:00:00 – 17/07/2026 19:15:00**
   (the outage itself was 19:06:43–19:07:11 UTC — this window gives
   padding on both sides)
3. Screenshot the trace-count-over-time graph — should show a clean dip
4. Save as `03-chaos-trace-gap.png` in this folder

Once that's in, ping to get it wired into `docs/BLOG_DRAFT.md` and this
folder is done.
