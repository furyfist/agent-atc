# ATC Product Strategy: V1 -> V2

Status: product-vision document. Does NOT modify PROJECT_PLAN.md (frozen v1.0)
or the hackathon implementation roadmap. Grounded in the July 2026 ecosystem
research pass (incidents, competitive landscape, compliance timelines).

## Part 1 - Micro-additions V1 absorbs now

Filter: nothing that adds a service, a workflow, or makes ATC resemble a
content firewall. Each item is a field, a rule, a panel, or one endpoint's
worth of change.

| # | Addition | Effort | Risk | Demo value | Judging impact |
|---|---|---|---|---|---|
| 1 | `policy.version` span attribute - content-hash of risk_rules.yaml stamped on every atc.gate span | ~1 hour | Near-zero | Low alone, high in narration | High - every trace becomes an EU-AI-Act-Article-12-shaped decision record |
| 2 | Reversibility class on the approval card - map DROP/TRUNCATE/unbounded-DELETE facts (already computed by sqlglot) to `atc.reversibility: IRREVERSIBLE`; red "cannot be undone" chip on the pending card + span attribute | Small | Low | Very high - the most legible thing a judge sees during Act 2's hold | Very high - reframes ATC from permission checker to consequence checker |
| 3 | Rubber-stamp panel on Governance dashboard - approval-latency trend + "% of HIGH-risk approvals decided in <3s" | Dashboard-only | Zero code | Medium-high | High - measures the human; no competitor does |
| 4 | Token-budget circuit breaker - agent-runner includes token usage in its existing heartbeat POST; gateway denies with [ATC-BUDGET] past threshold via the existing quarantine check path | Small-medium | Low-medium | High | Medium-high |
| 5 | Loop-suspicion event - creep-detector sibling (async, non-gating): N near-identical calls in M minutes -> atc.loop_suspected event + risk-score bump | Small-medium | Low | Medium (needs staged loop) | Medium-high |

Recommendation: #1-#3 unconditional before freeze. #4 if the freeze date
allows. #5 first thing post-freeze.

Explicitly rejected for V1: result-side injection scanning (makes ATC look
like another MCP firewall - Pipelock's territory), anything identity-shaped
(a standards war to consume, not fight), memory-provenance work beyond the
attributes that already exist in the schema.

## Part 2 - ATC V2 product vision

### Thesis

ATC is the system of record for agent behavior. Every governance product on
the market evaluates each action against static rules and forgets it. ATC's
bet: the history is the product - every gate decision informed by everything
the fleet has ever done, every approved action recoverable, every decision
exportable as evidence. V1 is the control tower (see and intervene in real
time). V2 adds what aviation built around the tower: the safety board that
learns from every flight, and the recovery systems that make failure
survivable.

### Customer problems (ranked by evidence strength)

1. Approved-but-wrong is unrecoverable. Every headline incident (PocketOS,
   Replit, the 1.9M-row Terraform deletion) passed the rules that existed.
   Median detection lag: days. Agent write-rates: thousands/hour. Nobody can
   undo.
2. Oversight doesn't scale. HITL collapses into rubber-stamping within a
   session. The answer is fewer, better-targeted holds, calibrated per agent
   by track record - not more approvals.
3. "Prove it" is becoming law. EU AI Act Article 12: tamper-evident records
   of what the governance system decided, under which policy version. Fines:
   7% of worldwide turnover.
4. Behavioral failure is invisible until the incident. Creep, drift, loops,
   ping-pong all have unmistakable signatures in action history; no
   enforcement product reads that history.

### Core differentiator

The telemetry backend is the policy engine's memory. Competitors' policy =
f(rules, this_call). ATC's policy = f(rules, this_call, everything_before).
Already real in V1's creep detection; every V2 capability compounds on it.

### Three pillars

1. **Recoverability ("the ejection seat")** - reversibility classification
   (V1 seed: item #2) -> pre-execution journaling at the gateway (pre-image
   capture for db/fs mutations) -> one-click compensating actions from the
   trace, days later -> blast-radius preview before approval ("this UPDATE
   touches 1.9M rows"). The gateway is the only component in any stack that
   sees every mutation before it happens.

2. **Behavioral intelligence ("the adaptive tower")** - creep, drift, loop,
   and rubber-stamp detection unify into one primitive: continuous queries
   over the behavioral record feeding the risk score. End state: earned
   autonomy - an agent with 400 clean staging queries stops generating holds
   for staging queries; one anomaly re-tightens it. The honest solution to
   approval fatigue.

3. **Evidence ("the flight recorder, certified")** - policy-version stamping
   -> hash-chained tamper-evident decision records -> exportable audit
   bundles per trace/period/agent, mapped to EU AI Act Article 12 and SOC 2.
   Pillars 1-2 sell to engineers; pillar 3 sells to compliance officers with
   deadlines.

### Roadmap

- V1 (hackathon, frozen): intercept, hold, explain. MCP-only, single-tenant,
  SigNoz-coupled.
- V1.5 (weeks after): missed micro-additions + hardening - PostgresBackend,
  loop detection, policy hot-reload, consuming real agent identity
  (OAuth/SPIFFE) instead of static tokens.
- V2 (~6 months): the three pillars + two strategic widenings:
  framework-agnostic ingestion (LangChain / OpenAI SDK / A2A emitting the
  same atc.* span schema; MCP becomes one of several front doors) and
  bring-your-own-backend (any OTLP store; SigNoz as reference
  implementation).
- V3: prediction and certification - pre-approval dry-run simulation against
  shadow state, autonomy certification per agent/task class, fleet
  benchmarking across deployments.

### Competitive map

| Camp | Players | Have | Can't do |
|---|---|---|---|
| Gateways/firewalls | Microsoft Agent Governance Toolkit, Pipelock, mcp-firewall, MCPX, MintMCP, Bifrost | Interception, static policy, RBAC, audit logs | Stateless per call - no memory, no recovery, no behavioral signal |
| Observability | LangSmith, Langfuse, Datadog LLM Obs | Rich traces, evals | Watch, can't act - no enforcement point |
| Identity | Okta, CrowdStrike, SPIFFE efforts | Who the agent is | Nothing about what it does |
| GRC dashboards | Credo, Fiddler | Compliance reporting | Out-of-band; not the system that decided |

Everyone sits in enforcement-without-memory or memory-without-enforcement.
ATC is alone in the intersection; pillar 1 adds a third axis (recovery)
where the field is empty.

Long-term moat: (a) the accumulated behavioral baseline per deployment -
switching cost grows daily; (b) the atc.* span schema, pushed toward the
OTel GenAI SIG as the governance-decision semantic convention, with ATC as
reference implementation; (c) the compensating-action journal - genuinely
hard engineering nobody else's architecture positions them to attempt.

### Self-challenge

Weakest recommendation: the budget gate - the most commoditized gateway
feature; survives only because it reuses V1's quarantine machinery and demos
well. First to cut. Deliberately absent from V2: injection scanning (arms
race, crowded), agent discovery/inventory (different tech, separate
product), eBPF egress enforcement (real, but V3-hard).

### The six-month answer

"Approve, regret, undo." A live demo where an agent's approved action - one
that passed every rule - is reversed four days later with one click: the
gateway's pre-image journal reconstructs the state, the compensating action
executes through the same governed path (itself risk-assessed and held), and
the Narrator explains what was undone, why, and under which policy version.
Every other product's story ends at "we blocked it" or "we logged it." Ours
ends at "we took it back."
