# Context: what's left on ATC

Paste this whole file as the first message in the new chat.

## Project

`c:\Users\himan\OneDrive\Desktop\agent-atc` — ATC (Air Traffic Control for
Autonomous Agents), a SigNoz Hackathon project. Full spec is
`PROJECT_PLAN.md` in the repo root (frozen v1.0, single source of truth) —
read it for architecture/context. This doc is a snapshot of what's actually
left, verified against a **live** stack, not just a code read.

## Where things stand right now

Docker Desktop is fixed and the full stack is up and working:

- SigNoz cast via `foundryctl` (see `signoz/casting.yaml`), `signoz-network`
  created.
- `docker compose up -d --build` brings up all 7 core services
  (`atc-core`, `agent-runner`, `tools-db`, `tools-fs`, `tools-git`,
  `victim-postgres`, `otel-collector`) — confirmed via `docker compose ps`.
- `http://localhost:8000` (approval UI) returns 200.
- REST API confirmed live: `GET /api/agents` returns the 3 real agents,
  `GET /api/actions` returns real recorded actions.
- `agent-runner` has been run once for real against the live gateway (see
  gaps below — it is **one-shot**, not continuous, so it's currently
  `Exited (0)`, not running).

167+ unit tests pass across all 8 packages
(atc-core, atc_telemetry, tools-fs, tools-git, tools-db, agent-runner,
history-seeder). Three real bugs were found and fixed by actually running
Docker for the first time (all committed, pushed to `main`):

- `fc866cf` — `atc-telemetry` wasn't a declared dependency of `atc-core`
  despite being imported (worked locally by accident via a shared `.venv`;
  broke in the container's isolated install).
- `06b23ea` — tools-db's seed INSERTs weren't idempotent, crashed on
  container restart against a persisted volume.
- `a2c10bc` — `/mcp` was mounted in a way that 404/405'd depending on
  method; also fixed `agent-runner`'s gateway URL to use the trailing
  slash that actually resolves.

## Gaps found by actually running the live stack (not visible from code review alone)

These are real, currently-true gaps, discovered by checking live container
status, live logs, and live API responses — not assumptions:

1. **`agent-runner` is one-shot, not continuous.** `services/agent-runner/src/agent_runner/main.py`'s
   `main()` runs each of the 3 personas exactly once via `asyncio.gather`
   and exits. `docker compose ps -a` shows `atc-agent-runner-1` as
   `Exited (0)`. Fleet Tower's "risk score, heartbeat, drift flags" story
   (PROJECT_PLAN.md §3) needs agents alive and heartbeating continuously —
   this doesn't exist yet.

2. **Only 1 of 6 planned metrics is wired.** `packages/atc_telemetry/src/atc_telemetry/metrics.py`
   defines `AtcInstruments` with `actions_total`, `interceptions_total`,
   `approval_latency_seconds`, `agent_risk_score`, `agent_heartbeat`,
   `agent_tokens_total`. Only `agent_tokens_total` is ever recorded
   (`services/agent-runner/src/agent_runner/mission.py:188`).
   **`atc-core` never even calls `configure_metrics()`** — grep confirms
   zero matches in `services/atc-core/src/`. Fleet Tower and Governance
   dashboards cannot be built until this is wired, since the data they'd
   query doesn't exist.

3. **`Store.record_heartbeat()` is defined but never called anywhere**
   in production code (`services/atc-core/src/atc_core/store/db.py:81`).
   Confirmed live: `GET /api/agents` shows `last_heartbeat_ts: null` for
   all 3 agents.

4. **Denial-recovery isn't converging in practice.** Live log from the one
   real run: `coder-01` tried `DROP TABLE staging_old`, then
   `ALTER TABLE ... RENAME`, then `DELETE FROM staging_old` — all three
   HIGH-risk-denied via `hold_timeout` (nobody was watching the approval
   UI) — and ran out of its 8-turn budget: `[coder-01] DENIED (unresolved)
   turns=8 tool_calls=8`. This is the same reliability gap spike S4 flagged
   (system prompt v2 is committed but never got its full 10-mission
   ≥8/10 re-verification — Groq quota ran out mid-run last time).

5. **Permission-creep detection (`atc.novel_resource`) has zero
   implementation.** Only mentioned in comments/docstrings
   (`services/history-seeder/src/history_seeder/seed.py`). The gateway
   never runs the "has this agent ever touched this resource before"
   check PROJECT_PLAN.md §6 describes (the "Non-gating creep law": must
   run async, after the gate decision, never block the tool-call path).
   Act 3's compliance-agent subplot has no backing code.

6. **No scenario-runner artifact exists anywhere in the repo** (checked:
   `find . -iname "*scenario*"` returns nothing). PROJECT_PLAN.md §11's
   "live-vs-replay gate" requires a scenario-runner to show ≥8/10 passes
   before an act can be recorded live — this tool doesn't exist, only
   S4's one-off spike script did something adjacent.

7. **`history-seeder` and `make reset-demo` have never been run against
   the live stack.** Both are built and unit-tested (`services/history-seeder/`,
   root `Makefile`), but confirmed via `GET /api/actions`: only 12 actions
   exist, all from the last ~40 minutes (the one live agent-runner run) —
   none backdated. Nobody has run
   `docker compose --profile seed run --rm history-seeder` yet.

## MVP scope (PROJECT_PLAN.md §10 "never cut") — status table

| Item | Status |
|---|---|
| Gateway + interception + risk engine + two-phase spans | Done, live-verified |
| Approval UI (countdown + quarantine) | Built, returns 200; not yet clicked through visually |
| 3 Groq agents with denial-recovery | Runs live; recovery does not reliably converge (gap 4) |
| tools-db + tools-fs + victim-postgres | Running, but tools-db is still SQLite-backed — victim-postgres is seeded and unused, no `PostgresBackend` exists |
| otel-collector | Running; whether spans actually land correctly in SigNoz is unverified |
| **Fleet Tower + Governance dashboards** | **0% — blocked by gaps 1-3 (no metrics, no heartbeat)** |
| Narrator (with fallback chain) | Only the emergency/local-SQLite path (`ActionStoreSpanFetcher`) works; primary SigNoz-MCP path (spike S3) and secondary Trace-API path are unbuilt |
| history-seeder | Built, tested, never run live (gap 7) |
| reset-demo | Authored, never run live (gap 7) |
| risk-engine tests + scenario runner | Risk-engine unit tests exist; scenario runner does not exist (gap 6) |
| Act 1 + Act 2 (actual recorded demo) | Not built at all |

## Priority-ordered punch list

1. **Wire the missing metrics + heartbeat loop** (gaps 1-3) — highest
   leverage, since Fleet Tower is dead in the water without this.
   - Add `configure_metrics("atc-core")` to `services/atc-core/src/atc_core/main.py`,
     thread the returned `AtcInstruments` into `Gateway`, record
     `actions_total`/`interceptions_total`/`approval_latency_seconds` at
     the right points in `services/atc-core/src/atc_core/gateway/server.py`.
   - Decide how agents heartbeat: agent-runner is one-shot today, so
     either (a) make it loop (matches "live fleet" demo framing) with a
     periodic `record_heartbeat` call + `atc_agent_heartbeat` gauge, or
     (b) add a lightweight separate heartbeat task. Needs a decision, not
     just code — affects how Act 1's "background agents" are meant to work
     per §11.
   - Implement the EWMA `atc_agent_risk_score` per the exact formula in
     PROJECT_PLAN.md §6 (LOW=1 MEDIUM=5 HIGH=25 denied-HIGH=50, +20/novel
     resource, ~10-min decay half-life), recomputed on heartbeat cadence.

2. **Run spikes S2 and S3 for real now that Docker/SigNoz are up.**
   - S2: confirm SigNoz accepts OTLP spans with backdated timestamps —
     directly validates `services/history-seeder/src/history_seeder/seed.py`'s
     `emit_backdated_spans` (unit-tested against `InMemorySpanExporter`,
     never checked against real SigNoz ingest).
   - S3: confirm `signoz-mcp-server` trace-fetch works well enough for the
     Narrator; if not, the plan's own fallback is to make the Trace API
     the primary path instead (`services/atc-core/src/atc_core/narrator/`).

3. **Run `history-seeder` and `make reset-demo` against the live stack**
   for the first time. `docker compose --profile seed run --rm
   history-seeder`, then check SigNoz actually shows the backdated spans
   (ties into S2). Then try a full `make reset-demo` cycle and confirm
   Postgres/fs/SQLite genuinely come back clean.

4. **Fix Act 2 reliability** (the task tracker called this #12). Prompt
   v2 is committed (`services/agent-runner/src/agent_runner/personas.py`)
   but never got its full 10-mission ≥8/10 reliability re-verification —
   and the one live run just reproduced the same failure mode S4 flagged.
   Needs fresh Groq quota (daily cap) and likely another prompt iteration.

5. **Build permission-creep detection** (gap 5) — the async, non-gating
   "has this agent touched this resource before" check + `atc.novel_resource`
   span event/metric, queried from SigNoz history per §6.

6. **Build Fleet Tower + Governance dashboards** — blocked on #1. Once
   metrics exist, author the dashboard JSON (SigNoz supports JSON
   import/export) for both.

7. **Build a real scenario-runner** (gap 6) — needed to gate live-vs-replay
   recording decisions per §11's "≥8/10 passes" rule. Probably a small
   CLI that runs Act 2's mission N times against the real stack and
   reports a pass rate.

8. **Act 1 + Act 2 actual demo scripts and recording** — the final
   integration step, depends on everything above being solid.

## Nice-to-Have (PROJECT_PLAN.md §10 — first to cut under pressure, in order)

1. `tools-git` — **already done** (mock, in-memory, real MCP server, tested)
2. logs→OTLP pipeline — not built (structured logs → OTLP, trace-correlated)
3. token-burn metrics — **already done** (`agent_tokens_total` is the one
   metric that IS wired, in agent-runner)
4. extra UI polish (incl. decision-log panel) — not built
5. `mailpit` + `tools-email` — not built at all; the `tools-email` MCP
   server itself could be built mock/in-memory like `tools-git` without
   Docker, only `mailpit`'s web UI needs a container
6. Narrator MCP path — see gap in the Narrator row above (S3-dependent)
7. Act 3 permission-creep subplot — depends on gap 5 above
8. Act 3 entirely (fallback: 2-act demo) — depends on everything

## Stretch (only if ahead of schedule — PROJECT_PLAN.md §10)

None of these are started, and per the plan that's correct/expected this
early: LLM advisory risk annotation (non-gating), policy hot-reload, token
budget alerts, Narrator streaming output.

## Also still open, not code-shaped

- **SigNoz Cloud trial account** — plan calls for creating this early
  (§3) to validate hosted MCP server access before betting the Narrator's
  primary path on it. Unclear if this has been done — check before
  spending time on S3 against self-hosted SigNoz only.
- **Pre-event blog** (was due Jul 19, non-coding deliverable) — outside
  what a coding session can do; flagging so it isn't forgotten.
- **`services/agent-runner`'s "agent memory files" / Act 3 staging
  fixture** — `make reset-demo` (root `Makefile`) explicitly documents
  this as unimplemented: the "36-day-stale zombie task" subplot
  (PROJECT_PLAN.md §11 Act 3) needs a real staged-JSON memory-compaction
  mechanism that doesn't exist in code yet.

## How to work with me in the new chat

- The stack is live now — prefer checking real behavior (logs, API calls,
  SigNoz UI) over reasoning from code alone; that's how gaps 1-7 above
  were actually found this session.
- Platform: Windows 11, PowerShell primary shell, Docker Desktop, Bash
  tool (Git Bash) also available.
- Commit convention: single-line commit messages, no Co-Authored-By /
  AI-attribution, no decorative dashes — see the repo's `CLAUDE.md`.
