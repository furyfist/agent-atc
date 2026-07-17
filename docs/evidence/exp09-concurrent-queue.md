# Experiment #9 — Concurrent multi-agent hold queue

Attempted 2026-07-17 20:15 UTC, live gateway, via
`scripts/concurrent_hold_queue.py` (coder-01 targeting a real prod table
`orders`, comply-01 targeting a sensitive-path write, run concurrently
via `asyncio.gather`).

## Status: blocked by the real daily Groq token cap, honestly reported

This is the exact constraint the blog evidence plan's §0 already
documented from spike S4 - "a 100,000-token/day hard cap ... roughly 15
full missions per key per day" - and today's key hit it mid-experiment:

```
RateLimitError: Error code: 429 - Rate limit reached for model
`llama-3.3-70b-versatile` ... on tokens per day (TPD): Limit 100000,
Used 99818, Requested 793. Please try again in 8m47.904s.
```

Confirmed via a follow-up minimal request: the per-minute RPM/TPM buckets
still had headroom (888/1000 requests, ~12K/12K tokens per minute), but
the separate daily TPD bucket had only ~180 tokens left after the day's
prior experiments (#1 flagship: 4,494 tokens; #3 injection: 2,377 tokens;
plus `agent-runner`'s own continuous persona-loop missions running in
the background throughout this session).

## What did run before the cap hit

```
[t= 2.6s] pending=1: coder-01:db__execute:HIGH
[t= 3.5s] pending=0:
max concurrent pending holds observed: 1
```

`coder-01` got exactly one turn in (a `db__query` against
`information_schema.tables`, which errored - SQLite, not Postgres - same
pattern seen in every other coder-01 run this session) before its second
LLM call 429'd. `comply-01` never got a single successful call. Only one
hold ever queued, not the 2-3 simultaneous holds the experiment needs.

## Honesty note

Per the blog's own §0 ground rule ("no invented numbers, no assumed
results... if we run out of time to fill a blank, the blog says so -
that's evidence too"): this experiment did not complete today. The
blocker itself is real, on-camera evidence of the plan's own documented
Groq constraint - worth citing directly rather than papering over. Retry
this experiment on a fresh daily quota window (or a second Groq
key/org, per §5's "parallelize expensive items across keys" guidance)
before writing the blog's benchmark section.
