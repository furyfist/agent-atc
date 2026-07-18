# ATC — Air Traffic Control for Autonomous Agents

Governance signals are observability signals. ATC intercepts risky MCP tool
calls from autonomous agents, holds them for human approval, and records the
full intent → decision → action trace as OpenTelemetry spans in SigNoz.

Built for the [SigNoz Hackathon](https://www.wemakedevs.org/hackathons/signoz)
(WeMakeDevs × SigNoz, Jul 20-26 2026).

See [PROJECT_PLAN.md](./PROJECT_PLAN.md) for the full architecture, stack, and
milestone plan (frozen v1.0, single source of truth).

## Status

Core services (gateway, risk engine, approval manager, REST/WS API, approval
UI, tools-db/fs/git, agent-runner, Narrator, history-seeder) are implemented,
unit-tested, and verified against a live Docker/SigNoz stack.

## V2 foundations (branch `v2-foundations`)

Consequence-aware governance seeds from [docs/PRODUCT_STRATEGY.md](docs/PRODUCT_STRATEGY.md):

- **Policy versioning** — every risk-assessment span carries `policy.version`
  (content hash of `risk_rules.yaml`), pinning the exact rule set in force at
  decision time.
- **Reversibility classification** — every decision is also classified
  `REVERSIBLE | COMPENSABLE | IRREVERSIBLE` (fail-closed); the approval card
  shows "CANNOT BE UNDONE" where it's true.
- **Blast radius** — mutating SQL gets a pre-approval `~N rows affected`
  estimate via a COUNT readback through the same upstream pool.
- **Pre-image journal + undo** — COMPENSABLE mutations are journaled at the
  gateway (prior file content / affected rows / dropped-table snapshots)
  before executing; `POST /api/actions/{id}/undo` replays the compensation
  through the same governed path as a linked, audited action. "Approve,
  regret, undo."
- **Token-budget circuit breaker** — agents report cumulative spend via
  heartbeats; past `ATC_TOKEN_BUDGET` the gateway denies with `[ATC-BUDGET]`.
- **Loop suspicion** — repeated near-identical calls inside a short window
  emit `atc.loop_suspected` events + `atc_loops_suspected_total` (non-gating,
  same contract as creep detection).
- **Rubber-stamp watch** — a Governance dashboard panel tracks approval
  decision latency; a median trending toward zero means the human stopped
  reading.
- **Novel-resource weighting** — creep detections persist on the action row
  and add +20 to the EWMA risk score, completing the §6 formula.

## Development

Dependency management via [uv](https://docs.astral.sh/uv/). This is a uv
workspace (`packages/*`, `services/*`); to install everything:

```
uv sync --all-packages
```

**Known gotcha:** on Windows, `uv sync`/`uv sync --all-packages` sometimes
registers a workspace member as installed without writing its editable `.pth`
loader, so `import atc_core` (etc.) fails even though `uv pip list` shows it
installed. If that happens:

```
uv sync --all-packages --reinstall-package <package-name>
```

Run tests **per service/package with an explicit path**, from repo root:

```
uv run --package atc-core pytest services/atc-core/tests/
uv run --package tools-fs pytest services/tools-fs/tests/
```

**Known gotcha:** several services have same-named test files (e.g.
`test_server.py` in tools-fs, tools-git, and tools-db). Running pytest across
*multiple* packages in one invocation (`pytest services/ packages/`, or
omitting the explicit path so it discovers from repo root) hits a pytest
basename-collision error, and `--import-mode=importlib` doesn't fix it
cleanly either (it breaks the `from server_helpers import ...`-style local
test-helper imports every service's test suite uses). Always pass the
explicit per-service test path as shown above - that's also how every
service's tests were actually developed and verified.

## Demo reset

`make reset-demo` restores Postgres/fs/SQLite state and force-reseeds
baseline action history between recording takes (PROJECT_PLAN.md §9). Not
yet run against a live daemon, same caveat as the compose file - see the
Makefile's own header comment. Agent memory files / Act 3 staging restore
is intentionally not included yet since that feature isn't built.
