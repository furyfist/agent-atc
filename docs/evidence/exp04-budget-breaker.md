# Experiment #4 — Token budget breaker

Ran 2026-07-17 20:03 UTC, live gateway. `assist-01`'s real, heartbeat-
reported cumulative usage from its normal persona missions was already
**1,366 tokens** (`agents.tokens_used` in SQLite, fed by
`agent-runner`'s heartbeat loop after each real mission). Restarted
`atc-core` once with `ATC_TOKEN_BUDGET=1300` (below that usage) to
observe the breaker trip, then restarted again with the default (`0` =
disabled) to restore normal operation - this was a temporary,
experiment-scoped override, not a permanent config change.

## Trigger

A single synthetic (zero additional Groq cost) `fs__read` call via
`scripts/trigger_budget_breaker.py` - deliberately harmless and in-scope,
to prove the breaker denies purely on cumulative spend, independent of
the call's own risk level:

```
fs__read({'path': 'daily-summary.txt'})
-> "[ATC-BUDGET] reason=token_budget_exhausted used=1366 budget=1300.
    Blocked by governance. This agent's token budget is spent; an
    operator must raise it before further tool calls are allowed."
```

## Evidence

- Gate span `atc.gate.fs__read` at 20:03:36, duration ~426ms - the
  budget check short-circuits before risk assessment or upstream
  dispatch (compare to a normal gated call's full
  `gate -> risk_assessment -> execution` chain).
- `agent_tokens_total` metric confirmed present in
  `signoz_metrics.distributed_samples_v4` - this is the graph that
  flatlines against the ceiling once an agent crosses it.
- Denial happened even though `fs__read` on this path/agent would
  normally be `LOW` risk, auto-allowed - the budget breaker gates on
  cumulative economic spend, not per-call risk.

## Why this is gate-side, not alert-side

Ties directly to spike S4's finding that alert latency (~1 min) is too
slow for a runaway loop: by the time an operator reads an alert, a tight
loop has already burned multiples of the budget. The breaker checks
`stored_agent.tokens_used >= self._token_budget` synchronously in the
gate path itself (`services/atc-core/src/atc_core/gateway/server.py`),
before dispatching to the upstream tool - the only cadence fast enough
to actually stop spend, not just report it after the fact.
