# Experiment #5 — Loop-suspicion trigger (synthetic, zero Groq)

Ran 2026-07-17, fresh stack (`docker compose up -d --build` after `down -v`).

## Trigger

`scripts/trigger_loop_suspicion.py` called `fs__read` with identical args
(`{"path": "loop-bait.txt"}`) 4x in ~1.2s as `coder-01`, directly against the
gateway's MCP endpoint — no Groq/LLM call involved.

```
call 1: "error: no such file: 'loop-bait.txt'"
call 2: "error: no such file: 'loop-bait.txt'"
call 3: "error: no such file: 'loop-bait.txt'"
call 4: "error: no such file: 'loop-bait.txt'"
```

The tool-level error is irrelevant to the detector — it keys on
`(agent_id, tool, args_summary)`, not on success/failure.

## Actions table (4 identical rows, ~1.2s apart)

```
fs__read {"path": "loop-bait.txt"} AUTO_ALLOWED 1784315140.2317514
fs__read {"path": "loop-bait.txt"} AUTO_ALLOWED 1784315141.3456814
fs__read {"path": "loop-bait.txt"} AUTO_ALLOWED 1784315141.437264
fs__read {"path": "loop-bait.txt"} AUTO_ALLOWED 1784315141.5136862
```

## Evidence the detector fired

- ClickHouse span: `atc.loop_check` at `2026-07-17 19:05:41.532443978`
  (fired right after the 4th call, once repeats crossed
  `DEFAULT_REPEAT_THRESHOLD = 3`).
- Metric `atc_loops_suspected_total` confirmed present in
  `signoz_metrics.distributed_samples_v4`.

## Honesty note

Non-gating by design: all 4 calls were `AUTO_ALLOWED`, none were held or
denied. The loop detector observes and emits; the token-budget breaker
(experiment #4) is the hard backstop against a runaway loop burning real
money.
