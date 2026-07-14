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

Dependency management via [uv](https://docs.astral.sh/uv/):

```
uv sync
```
