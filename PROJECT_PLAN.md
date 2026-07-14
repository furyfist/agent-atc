# PROJECT_PLAN.md — ATC: Air Traffic Control for Autonomous Agents

> **STATUS: v1.0 — FROZEN.** Single source of truth for the "Agents of SigNoz" hackathon project (WeMakeDevs × SigNoz, July 20–26 2026, Track 3 "Build Your Own"). Moves to the dedicated `agent-atc` repository on creation. Changes after freeze require explicit team agreement. Sections marked **OPEN** are the only undecided items.
>
> **Product name: ATC** · **Repo: `agent-atc`**
>
> **Priority stack (tie-breaker for every decision):** 1) working end-to-end demo → 2) reliable recording → 3) strong SigNoz integration → 4) additional features.

---

## 1. Positioning

**One-liner:** Every AI-agent horror story of 2026 — the coding agent that wiped a production database in 9 seconds, the personal assistant that resurrected a 36-day-dead task from a memory-compaction summary, the agent that tried to rewrite another agent's compliance rules — has the same root cause: nobody has a control tower. ATC is one, built on SigNoz.

**Critical framing rule:** We are NOT "another MCP approval gateway" (that category already exists in 2026). Our pitch: **governance signals ARE observability signals.** The trace is the audit log; SigNoz is the control tower; drift/creep detection queries history already in SigNoz.

**Three fused pillars:**
1. **Flight Recorder** — full causal trace of intent → decision → action for every agent tool call.
2. **Fleet Tower** — live SigNoz dashboard of every agent: scope, risk score, heartbeat, drift flags.
3. **Circuit Breaker + Narrator** — high-risk tool calls held before execution pending human approval; an LLM reads the trace back from SigNoz and explains "why the agent did that" in plain English.

**Sourced real-world evidence (for blog/pitch):**
- Cursor + Claude Opus 4.6 deleted PocketOS's production DB and backups in one API call (9 s) — [The Register, Apr 2026](https://www.theregister.com/2026/04/27/cursoropus_agent_snuffs_out_pocketos/)
- Personal assistant resurrected a 36-day-stale task after memory auto-compaction, took down production — [HackerNoon, Jul 2026](https://hackernoon.com/i-asked-my-ai-assistant-to-add-a-calendar-event-it-took-down-production-instead)
- Solo founder's "Improver" agent tried to rewrite the "Lawyer" agent's compliance rules — [DEV Community](https://dev.to/setas/i-run-a-solo-company-with-ai-agent-departments-50nf)
- Agent kill-switch silently broken after IAM key rotation — [Indie Hackers, Apr 2026](https://www.indiehackers.com/post/5-fields-i-wish-i-had-on-agent-1-i-shipped-01dd5bcad7)
- One-person company whose agents hid activity from the owner — [Rest of World, 2026](https://restofworld.org/2026/ai-agent-china-one-person-company/)

---

## 2. Submission & Process (final)

- **Recorded demo video**, not live judging. Optimize for polished, deterministic recording.
- **Blog post required** (Medium / Dev.to / Substack; LinkedIn doesn't qualify). Also targeting the **pre-event blog prize, deadline July 19 2026**.
- Scaffolding starts immediately; main implementation July 20–26. **Feature freeze July 24 EOD**; July 25–26 = recording, bugfix, blog, docs, polish.
- Submission artifacts: demo video, README, write-up, blog, Google Form.
- **Fresh dedicated repository `agent-atc`** (this file moves there). Team↔workstream mapping is the last open item; shared ownership assumed until then.
- **SigNoz Cloud trial account created now** (30-day window covers submission) to validate the hosted MCP server early. When creating it, explicitly verify the trial tier includes: OTLP ingest keys, hosted MCP server access, dashboard JSON import, Trace API keys.
- **Video spec (final):** 4–5 minutes, OBS screen recording, English voiceover, captions for accessibility.
- **Pre-event blog (final):** architecture/vision angle — "Governance signals are observability signals: why we're building an air-traffic controller for AI agents on OpenTelemetry + SigNoz." Problem-first, anchored on the §1 sourced incidents, architecture-focused not implementation-focused. Owner: W4. Due Jul 19.
- **MVP discipline:** every proposed feature is classified MVP / Nice-to-Have / Stretch. Smaller-and-polished beats bigger-and-unfinished. See §10 descope ladder.

---

## 3. Stack (final)

| Layer | Choice |
|---|---|
| Language | Python everywhere (single language locked) |
| Web/API | FastAPI |
| MCP | Official Python MCP SDK, **Streamable HTTP transport everywhere** (stdio impossible across containers) |
| Telemetry | OpenTelemetry Python SDK → OTel Collector → SigNoz (OTLP) |
| LLM | **Groq only — project must be free to run.** Default model `llama-3.3-70b-versatile` for agents and Narrator (revisit only if Groq ships a better free model) |
| UI | One vanilla HTML/CSS/JS dark page served by `atc-core` |
| ATC state | SQLite |
| SQL risk parsing | sqlglot |
| Python deps | uv |
| Dev telemetry backend | Self-hosted SigNoz (Docker, upstream compose unmodified) |
| Recording backend | SigNoz Cloud (dashboards migrated via JSON export/import) |

**Groq free-tier constraints (verified July 2026, re-verify at build):** ~30 RPM / 6,000 TPM / 1,000 RPD per org (standard models); cached prompt tokens don't count toward TPM; limits are org-level → each dev on their own key/org, dedicated untouched key for recording day. Design laws: one reasoning agent at a time; terse prompts + lean tool schemas; stable system-prompt prefix (prompt cache); condensed Narrator inputs; 429 → exponential backoff.

---

## 4. Service Topology (final)

Docker Compose project `atc`, attached to SigNoz's compose network (SigNoz stack from upstream compose, unmodified).

| Service | Role | Class |
|---|---|---|
| `atc-core` | Single process: MCP gateway (`/mcp`), REST (`/api`), WebSocket (`/ws`), static approval UI, risk engine, approval manager, Narrator, SQLite | MVP |
| `agent-runner` | One container, 3 asyncio agent loops (logical agents, not container-per-agent) | MVP |
| `tools-db` | MCP server: `db__query`, `db__execute` → victim-postgres | MVP |
| `tools-fs` | MCP server: `fs__read`, `fs__write`, `fs__delete` on dedicated volume | MVP |
| `tools-git` | Mock MCP server (in-memory repo; `git__push`, `git__force_push`) | Nice-to-Have |
| `tools-email` | MCP server → SMTP → mailpit | Nice-to-Have |
| `mailpit` | Real SMTP catcher + web UI (visual proof of agent email activity) | Nice-to-Have |
| `victim-postgres` | Seeded fake production data | MVP |
| `otel-collector` | Single OTLP pipeline; **the local↔Cloud migration mechanism** (one env file re-points it; services never know which SigNoz they talk to) | MVP |
| `history-seeder` | One-shot (compose profile): backfills days of baseline spans | MVP (creep baseline + lived-in dashboards) |

Networks: `control-plane` (agents ↔ gateway ↔ tools ↔ collector) and `victim-net` (`tools-db` ↔ `victim-postgres` only). Agents physically cannot reach Postgres except through the gateway — a security-model talking point.

Repo layout: `services/{atc-core,agent-runner,tools-db,tools-fs,tools-git,tools-email}/`, `packages/atc_telemetry/` (shared span/metric emission helpers used by core, tools, seeder, runner — guarantees schema consistency), `dashboards/`, `policies/`, `scripts/`, compose at root.

---

## 5. MCP Gateway Internals (final)

- Gateway = MCP **server** to agents, MCP **client** to upstream tool servers. Aggregates `tools/list` at startup; serves namespaced union (`db__execute`, `fs__write` — double-underscore, Groq-function-name-safe).
- **Scope enforced twice:** at `tools/list` (agent only *sees* in-scope tools) and at `tools/call` (violations emit a `SCOPE_VIOLATION` span — itself a demo-able governance event).
- **Trace propagation:** agent starts the trace (mission root span); W3C `traceparent` carried in MCP `_meta` on every request; gateway and tool servers continue the same trace. ⚠️ Spike-test S1 before feature work.
- **Interception semantics:** block-and-hold; 120 s timeout; auto-deny on timeout. `asyncio.Event` per `action_id` + SQLite pending row (crash-safe; stale HELD → EXPIRED on restart).
- **⚠️ Timeout chain law (final-review finding):** a 120 s hold only works if every hop tolerates it. Agent-side MCP client request timeout ≥ 150 s; uvicorn/proxy timeouts ≥ 150 s; upstream tool-server client timeouts sized normally (execution happens *after* approval). Spike S1 must include holding one call for the full 120 s through the whole chain — this class of bug eats a day if found late.
- **Denial shape:** normal MCP tool *result* (not protocol error): `[ATC-DENIED] reason=<...> policy_rule=<id>. Blocked by governance. You may propose a safer alternative.` → enables on-camera agent recovery.
- **Per-agent static bearer tokens** in MCP headers; identity asserted server-side from token, never from client `_meta`. Lightweight by design, no obvious holes.

**Tool execution lifecycle:** `RECEIVED → SCOPE_CHECK → RISK_ASSESSED → {AUTO_ALLOW | HELD} → HELD:{APPROVED | DENIED | EXPIRED} → {EXECUTED | REJECTED} → RESPONDED`. Every transition = span event; terminal state = span attributes + metrics.

---

## 6. Telemetry Schema (final)

**Two-phase interception law:** at interception emit an instantaneous, immediately-closed `atc.interception` span (+ counter) so SigNoz sees the event in near-real-time; the real tool-call span closes later with the outcome, span-linked to the interception. (OTel spans export only on end; a held call would otherwise be invisible during the demo's biggest moment.)

**Alert-latency law:** no demo beat depends on SigNoz alert evaluation (~1 min default). Instant "red" = approval UI + dashboard threshold panels; the SigNoz alert notification is a choreographed delayed second beat.

One trace per agent **mission**:

```
agent.mission (root — agent-runner)
├── agent.turn (per LLM round)
│   ├── gen_ai.chat            ← OTel GenAI semconv (gen_ai.system=groq, model, token usage)
│   └── mcp.tool.call {tool}   (client span)
│       └── atc.gate {tool}    (gateway server span)
│           ├── atc.risk_assessment  (risk.level, risk.reasons[], policy.rule_id)
│           ├── atc.interception     (HELD only — instant; LINKS to atc.execution)
│           ├── atc.approval_wait    (duration = human latency; decision, decided_by)
│           └── atc.execution        (upstream client span)
│               └── tool.{name}      (tool-server span; db.statement, file.path, …)
```

Attributes (`atc.*` / `agent.*`): `agent.id`, `agent.persona`, `agent.task.origin_ts`, `agent.memory.compaction_id`, `agent.memory.summary_excerpt`, `atc.action_id`, `atc.risk.level`, `atc.risk.score`, `atc.risk.reasons`, `atc.decision`, `atc.decision.by`, `atc.resource.class`, `atc.resource.name`, `atc.novel_resource`. Human-readable memory attributes, never opaque hashes.

**Metrics:** `atc_actions_total{agent_id,risk,decision}` · `atc_interceptions_total{agent_id}` (drives the red threshold panel) · `atc_approval_latency_seconds` (histogram) · `atc_agent_risk_score{agent_id}` (gauge; **EWMA approved:** weights LOW=1 MEDIUM=5 HIGH=25 denied-HIGH=50, +20 per novel resource, ~10-min decay half-life) · `atc_agent_heartbeat{agent_id}` · `agent_tokens_total{agent_id,model}` (token-burn story — approved, Nice-to-Have class).

**Logs:** structured → OTLP → SigNoz, trace-correlated (gateway decisions, one-line agent thought summaries, tool executions). Nice-to-Have class.

**Permission creep = SigNoz history:** novel resource ⇔ zero prior spans for (agent.id, resource) via SigNoz query (Trace API / MCP server); results cached in SQLite to bound API calls. SigNoz stays a core dependency, not just visualization.

**⚠️ Non-gating creep law (final-review finding):** the creep check runs **asynchronously after the gate decision** — it emits the `atc.novel_resource` event span + metric but NEVER blocks or delays the tool-call path. A slow/down SigNoz query API must not add latency to agent actions. Gate decisions come from the deterministic risk engine alone.

**Risk-score implementation note:** the EWMA gauge is recomputed on the heartbeat cadence (~30 s), not continuously — decay applies at recompute time. Deterministic and cheap.

---

## 7. Risk Engine (final)

Policy-as-code YAML, ordered rules, first match wins, **deterministic — no LLM in the gate path, ever**. Matchers: tool name, argument regexes, sqlglot-derived SQL facts (DDL/DML kind, DELETE-without-WHERE, table names vs prod tags), fs path patterns, email recipient count, git force flags. Each rule → `risk_level` + `reason` + `rule_id`. **Fail closed:** unparseable SQL → HIGH; unmatched tool call → MEDIUM. The YAML file is itself a demo/blog artifact.

---

## 8. Approval Workflow, UI, Narrator (final)

REST: `GET /api/agents` · `GET /api/actions?status=pending` · `POST /api/actions/{id}/approve|deny` · `POST /api/agents/{id}/quarantine` · `POST /api/narrate {trace_id}`. WS events: `action.pending`, `action.resolved`, `agent.heartbeat`, `risk.updated`.

UI (one dark page): pending-approval cards **with live 120 s countdown** (approved), fleet cards (risk score, heartbeat, **quarantine/kill-switch button** — approved MVP), narrator panel. Decision-log panel downgraded to Nice-to-Have (SigNoz trace/span history already shows decisions; a UI duplicate is polish). Kill switch = SQLite flag → gateway denies everything from that agent with `[ATC-QUARANTINED]`.

**Narrator:** `POST /api/narrate {trace_id}` → fetch spans (**primary: SigNoz MCP server**; fallback: Trace API `POST /api/v5/query_range` with `SIGNOZ-API-KEY`; emergency: cached text) → code condenses span tree to a compact timeline (TPM budget) → Groq → 3–5 sentence causal narrative → cached in SQLite. Local dev runs the open-source signoz-mcp-server container against self-hosted SigNoz (hosted MCP server is Cloud-only). ⚠️ Spike S3.

---

## 9. Victim Systems, State, Failure Recovery (final)

- Real PostgreSQL, seeded fake prod data; real filesystem in Docker volumes; git + email mocked. Destructive actions technically real, safely isolated.
- SQLite tables: `agents` (id, persona, scope_json, owner, quarantined, last_heartbeat_ts, created_at) · `actions` (action_id, trace_id, span_id, agent_id, tool, resource_class, resource_name, args_summary, risk_level, risk_reasons, rule_id, status, decided_by, requested_at, resolved_at) · `narrations` (trace_id, text, created_at) · `settings` (k, v).
- OTLP export fire-and-forget — telemetry failure never blocks the gate path. SigNoz down → demo continues. Groq 429 → backoff. WS drop → UI auto-reconnect.
- **`make reset-demo`** (MVP): one command restoring Postgres seed, fs volume, agent memory files, SQLite, Act 3 staging. Mandatory for multi-take recording.

---

## 10. MVP Classification & Descope Ladder

**MVP (never cut):** atc-core gateway + interception + risk engine + two-phase spans; approval UI with countdown + quarantine; 3 agents on Groq with denial-recovery; tools-db + tools-fs + victim-postgres; otel-collector; Fleet Tower + Governance dashboards; Narrator (with fallback chain); history-seeder; reset-demo; risk-engine unit tests + scenario runner; Act 1 + Act 2.

**Nice-to-Have (approved, first to cut under pressure):** token-burn metrics; mailpit + tools-email; tools-git; logs→OTLP pipeline; SigNoz alert as delayed second beat.

**Stretch (only if ahead of schedule):** LLM advisory risk annotation (non-gating); policy hot-reload; token budget alerts; Narrator streaming output.

**Descope ladder (CONFIRMED — cut in this order if behind):** 1) tools-git → 2) logs pipeline → 3) token-burn metrics → 4) extra UI polish (incl. decision-log panel) → 5) mailpit+tools-email (email becomes log-only mock) → 6) Narrator MCP path (Trace API direct) → 7) Act 3 permission-creep subplot (keep zombie task) → 8) Act 3 entirely (2-act demo). **Non-negotiable core: the end-to-end demo, Circuit Breaker, Narrator, Fleet Tower, Flight Recorder.** Act 2 and the gateway are the identity of the project and are never cut.

---

## 11. Demo Acts — Technical Spec (final shape; fine detail OPEN in Round 3)

- **Act 1 "A normal Tuesday":** assistant sends daily-summary email (mailpit on screen), compliance reads policy files, coder queries staging DB — all LOW, fleet green. Background agents = scripted non-LLM low-risk actions + heartbeats; only the active agent reasons (Groq TPM law, approved).
- **Act 2 "The near-miss" (centerpiece):** coder mission "clean up the old staging table" → enumerates tables (LOW, allowed) → issues destructive SQL that policy classifies HIGH (agent can't see infra tags; reasonable-looking action, catastrophic target — the PocketOS shape) → held, UI red, countdown running → human denies → agent receives `[ATC-DENIED]` and **genuinely recovers via its own reasoning** (recovery policy CONFIRMED: guide with the denial text, never hard-code the second step; any reasonable safe alternative is accepted on camera; if reliability suffers, tighten the prompt — not the script) → safe alternative approved → executes.
- **Act 3 "Ask the Black Box" + drift:** Narrator explains Act 2's trace in plain English. Fleet Tower reveals two **pre-staged** subplots: assistant's compacted memory file (staged JSON with `origin_ts` ≈ 36 days, disclosed as staged in the blog — the failure execution is genuine) resurrects a stale task → HIGH intercept; compliance agent touches an in-scope-but-never-touched resource → `novel_resource` flag. Distinction documented: **creep = novel in-scope resource; scope violation = out-of-scope tool (blocked at list/call).**
- **Live-vs-replay gate (approved):** scenario-runner must show **≥ 8/10** passes for an act to be recorded live; otherwise that portion uses deterministic replay, disclosed without shame.

**Agent registry:** `coder-01` (scope: db, fs, git) · `assist-01` (scope: email, fs) · `comply-01` (scope: fs).

---

## 12. Spike Tests — highest-priority technical milestones (before feature work)

- **S1 (expanded):** minimal gateway proxy end-to-end — dynamic `tools/list` aggregation from an upstream MCP server, W3C `traceparent` through MCP `_meta` across three processes, AND one call held for the full 120 s surviving every timeout in the chain (agent MCP client, uvicorn, upstream). All three in one spike harness.
- **S2:** OTLP backfill with explicit past timestamps accepted by SigNoz (self-hosted + Cloud) within retention. Fallback: run seeder in real time for 2–3 days pre-recording.
- **S3:** signoz-mcp-server trace-fetch capability against self-hosted SigNoz adequate for Narrator. Fallback: Trace API becomes primary; MCP server stays in the story as dev tooling.
- **S4 (added in final review):** Groq budget rehearsal — run an Act-2-shaped tool-calling loop on `llama-3.3-70b-versatile`; measure real tokens/min for a full mission (rough estimate: ~7–8K fresh tokens across 4 turns, which brushes the 6K TPM ceiling if turns come fast); **confirm prompt caching actually discounts our repeated system-prompt prefix on the free tier**, and confirm tool-calling reliability is in the ≥8/10 zone before we bet Act 2 on it.

---

## 13. Timeline

| Window | Focus |
|---|---|
| Now – Jul 19 | Repo scaffold, compose skeleton, local SigNoz up, `atc_telemetry` package, span schema doc, MCP proxy hello-world, **spikes S1–S3**, SigNoz Cloud account, **pre-event blog (due Jul 19)** |
| Jul 20–21 | Gateway interception + risk engine + OTel end-to-end with scripted no-LLM agent; approval API/UI functional |
| Jul 22 | Real Groq agents (3 personas); denial-recovery loop; victim systems seeded; dashboard export dry-run |
| Jul 23 | Narrator; dashboards; permission-creep query; Act 3 staging; scenario-runner pass rates |
| Jul 24 | **Feature freeze EOD.** Full 3-act run-throughs; migrate dashboards to Cloud |
| Jul 25–26 | Record video (multi-take, reset-demo between takes), blog, README, submit |

---

## 14. References

- Hackathon: https://www.wemakedevs.org/hackathons/signoz · Registration: https://forms.gle/uxaLXAXmtKwz8uYh9 · Blog form: https://forms.gle/wf9tFYcksrk6P4Zy8
- SigNoz Cloud: https://signoz.io/teams/ · Pricing: https://signoz.io/pricing/ · Self-hosted: https://github.com/signoz/signoz
- Trace API: https://signoz.io/docs/traces-management/trace-api/overview/ · API ref: https://signoz.io/api-reference/
- SigNoz MCP Server: https://github.com/SigNoz/signoz-mcp-server · Docs: https://signoz.io/docs/ai/signoz-mcp-server/
- Agent-native observability: https://signoz.io/blog/introducing-agent-native-observability/
- Alert evaluation: https://signoz.io/docs/alerts-management/user-guides/understanding-alert-evaluation-patterns/
- Groq rate limits: https://console.groq.com/docs/rate-limits

---

## 15. Workstreams (final; person-mapping OPEN)

- **W1 — Gateway & Core:** atc-core (MCP proxy, risk engine, approval manager, SQLite, REST/WS). Week-1: spike S1.
- **W2 — Agents & Scenarios:** agent-runner (Groq loops, personas, prompts, denial-recovery, memory staging, scenario-runner). Week-1: Groq harness + spike S4, Act 2 prompt draft, team registration.
- **W3 — Telemetry & SigNoz:** `atc_telemetry` package, collector config, dashboards, history-seeder, creep query, Cloud migration. Week-1: spikes S2 + S3, local SigNoz, Cloud account.
- **W4 — Product & Narrative:** approval UI, Narrator, reset-demo, blog, video script/recording, README. Week-1: pre-event blog (due Jul 19), UI skeleton, repo scaffold + compose.

Full milestone matrix, risk register (R1–R10 with drills), and frozen contracts (policy YAML schema, WS payloads, seeder distribution) live in the Round 3 planning record; contracts get committed into `agent-atc` as `docs/contracts/` on repo creation.

## 16. OPEN Items (the only ones left)

- Map the four team members onto W1–W4 (then: Cloud account + recording-day Groq key owner = whoever babysits the Cloud env Jul 25–26)
- Verify pre-event blog topic constraints when registering
- Create `agent-atc` repo and move this file + contracts into it
