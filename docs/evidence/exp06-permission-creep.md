# Experiment #6 — Permission creep

Ran 2026-07-17 20:07 UTC, live gateway, synthetic script (zero Groq) via
`scripts/trigger_permission_creep.py`, as `coder-01` (in-scope for `fs`).

## Trigger

`fs__write` against a brand-new file path `coder-01` has never touched
before (`creep-probe-<unix-timestamp>.txt`, confirmed against its full
action history first - no prior resource_name matched):

```
fs__write('creep-probe-1784318853.txt') -> "wrote 11 bytes to 'creep-probe-1784318853.txt'"
```

Non-gating by design: the write succeeded immediately, no hold, no
denial.

## Evidence the detector fired

```sql
SELECT action_id, tool, resource_name, novel FROM actions
WHERE resource_name LIKE '%creep-probe%'
-- ('9b252d5e...', 'fs__write', 'creep-probe-1784318853.txt', 1)
```

`novel=1` persisted on the action row (feeds the EWMA scorer's +20
novel-resource weight on its next heartbeat recompute).

- ClickHouse span: `atc.creep_check` at `2026-07-17 20:07:37`.
- Metric `atc_novel_resource_total` confirmed present in
  `signoz_metrics.distributed_samples_v4`.

## Contrast with experiment #2 (scope violation)

Same UI surface (something gets flagged about this call), different
mechanism, worth one paragraph in the blog:

- **Scope violation (#2)**: the tool is never in scope - static,
  registry-level check, denied before any `actions` row exists.
- **Permission creep (this experiment)**: the tool/resource is in scope,
  the agent has simply never touched this specific resource before - a
  behavioral, history-based check (`CreepDetector` queries the `actions`
  table directly, no SigNoz round-trip needed), runs async *after* the
  gate decision, and never blocks or delays the call.
