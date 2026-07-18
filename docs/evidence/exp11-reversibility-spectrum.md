# Experiment #11 — Reversibility spectrum

Assembled 2026-07-18 from three real, independently-occurring action rows
(no staged/synthetic reversibility call needed — all three tiers already
existed in today's evidence, from `coder-01`'s live Groq-driven missions).
`reversibility` is a second, orthogonal dimension to risk level
(`services/atc-core/src/atc_core/risk/reversibility.py`): risk asks "how
bad could this be", reversibility asks "can we recover if it was".

## REVERSIBLE — pure read, nothing to undo

```json
{
  "action_id": "da5fa812-5e34-47aa-9065-9ce337ae4794",
  "trace_id": "48cfe041909c67b1b18e46843ecbd806",
  "tool": "db__query",
  "resource_name": "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'staging_old%'",
  "risk_level": "LOW",
  "reversibility": "REVERSIBLE",
  "status": "AUTO_ALLOWED"
}
```

Trace slice (`atc.gate.db__query -> atc.risk_assessment -> atc.execution`,
no interception/approval_wait — LOW risk skips the hold entirely):

```
atc.gate.db__query      17:00:18.9102   140.2ms
  atc.risk_assessment   17:00:18.9128    16.5ms
  atc.execution          17:00:18.9773    73.0ms
```

## COMPENSABLE — mutation, but a pre-image journal can restore prior state

Experiment #7's bounded UPDATE (see `exp07-blast-radius.md`) — reused here
rather than re-run, since it's already a clean, real example:

```json
{
  "action_id": "136cd135-d5b0-4217-b746-57a10ca3a680",
  "tool": "db__execute",
  "resource_name": "UPDATE orders SET total = total * 1.1 WHERE id >= 1000",
  "risk_level": "HIGH",
  "rule_id": "SQL-PROD-TABLE-HIGH",
  "reversibility": "COMPENSABLE",
  "status": "APPROVED"
}
```

The COMPENSABLE label isn't just a static tag on the tool — the journal
actually captured the 200-row pre-image (`table: orders`, exact prior
`total` values) that would let a future undo restore this state. See
`exp12-journal-capture.md` for the raw stored payload.

## IRREVERSIBLE — no compensation exists once executed

`git__push` — one of three tools hardcoded IRREVERSIBLE regardless of SQL
facts (`git__push`, `git__force_push`, `email__send`), because a push
publishes to a remote the journal doesn't capture:

```json
{
  "action_id": "7fcf56a4-d0ba-41bf-9797-98b4ab70e524",
  "trace_id": "2272694070437c6deaf253d74f92fe3e",
  "tool": "git__push",
  "risk_level": "MEDIUM",
  "reversibility": "IRREVERSIBLE",
  "status": "AUTO_ALLOWED"
}
```

Trace slice — clean, single, isolated call within a longer mission:

```
mcp.tool.call git__push   16:02:20.9617   505.3ms
  atc.gate.git__push      16:02:20.9682   496.5ms
    atc.risk_assessment   16:02:20.9693     0.15ms
    atc.execution         16:02:20.9818   482.9ms
```

## Why the MEDIUM/IRREVERSIBLE combination is worth calling out

This row is the clearest illustration of why reversibility is a genuinely
*separate* axis from risk, not just a relabeling of it: `git__push` is
only MEDIUM risk (a routine push, not a force-push) and was auto-allowed
with zero human involvement — but it's still IRREVERSIBLE. A risk-only
system would never flag this action as needing any special handling; ATC
tags it as unrecoverable anyway, because "how likely is this to be a
problem" and "can we undo it if it is" are different questions with
different answers here.

## Spectrum, side by side

| Tier | Tool | Risk | Decision | What "undo" means |
|---|---|---|---|---|
| REVERSIBLE | `db__query` | LOW | AUTO_ALLOWED | Nothing to undo — it's a read |
| COMPENSABLE | `db__execute` UPDATE | HIGH | APPROVED | Pre-image journaled; a future compensating UPDATE could restore it (executor not built — see `exp12-journal-capture.md`) |
| IRREVERSIBLE | `git__push` | MEDIUM | AUTO_ALLOWED | Published to a remote; no journal captures this; nothing to restore |
