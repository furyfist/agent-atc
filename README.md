# ATC — Air Traffic Control for Autonomous Agents

Governance signals are observability signals. ATC intercepts risky MCP tool
calls from autonomous agents, holds them for human approval, and records the
full intent → decision → action trace as OpenTelemetry spans in SigNoz.

Built for the [SigNoz Hackathon](https://www.wemakedevs.org/hackathons/signoz)
(WeMakeDevs × SigNoz, Jul 20-26 2026).

See [PROJECT_PLAN.md](./PROJECT_PLAN.md) for the full architecture, stack, and
milestone plan (frozen v1.0, single source of truth).

## Status

Early scaffolding — see PROJECT_PLAN.md §13 for the timeline and §12 for the
spike tests currently in progress.

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
