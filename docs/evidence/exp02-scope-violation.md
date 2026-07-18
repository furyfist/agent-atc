# Experiment #2 — Scope violation / permission escalation attempt

Ran 2026-07-17, live gateway, synthetic script (zero Groq/LLM calls) via
`scripts/trigger_scope_violation.py`, as `assist-01` (scope: `[email, fs]`
per `policies/agents.yaml` - no `db`).

## Layer 1: tools/list scope enforcement

```
assist-01 sees these tools (tools/list scope check): ['fs__delete', 'fs__read', 'fs__write']
```

`db__query`/`db__execute` are never even listed - the agent can't see the
out-of-scope tool exists.

## Layer 2: tools/call scope enforcement

Called `db__query` directly anyway (simulating a hallucinated tool name
or a compromised agent trying it regardless):

```
db__query call result: "[ATC-DENIED] reason=scope_violation
policy_rule=SCOPE-ENFORCEMENT. Blocked by governance. This tool is
outside your agent's registered scope."
```

## Zero downstream footprint

```sql
SELECT count(*) FROM actions WHERE agent_id='assist-01' AND tool='db__query'
-- 0
```

Denied before any `actions` row exists - the trace shows a single
`atc.gate.db__query` span with no `atc.risk_assessment` / `atc.execution`
spans following it, unlike an in-scope call which shows the full
`gate -> risk_assessment -> execution` chain.

## Contrast with experiment #6 (permission creep)

Same "the UI flags something about this call" surface, different
mechanism worth calling out explicitly in the blog:

- **Scope violation (this experiment)**: the tool is *never in scope* -
  a static, registry-level check (`AgentRegistry.in_scope`), denied
  before risk assessment even runs.
- **Permission creep (#6)**: the tool/resource *is* in scope, but the
  agent has never touched this specific resource before - a behavioral,
  history-based check (`CreepDetector`), non-gating, feeds the risk
  score instead of denying outright.

"Out-of-scope" vs "in-scope but never-touched" - one is a hard boundary,
the other is a soft behavioral signal.
