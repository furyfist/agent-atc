# Context: fixing Docker Desktop for the ATC project

Paste this whole file as the first message in the new chat.

## Project

`c:\Users\himan\OneDrive\Desktop\agent-atc` — ATC (Air Traffic Control for
Autonomous Agents), a SigNoz Hackathon project. Full spec is
`PROJECT_PLAN.md` in the repo root (frozen v1.0, single source of truth) —
read it for architecture/context if needed, but this session's job is
narrower: **get Docker Desktop working again**, step by step, guided.

All application code is done and unit-tested (167 tests passing across 7
packages). `docker-compose.yml`, 6 Dockerfiles, `otel-collector/config.yaml`,
and `Makefile` (`make reset-demo`) are authored but have never been run
against a live daemon, because Docker Desktop has been broken this whole
build. Nothing else is blocked technically except Docker.

## The problem

Docker Desktop's engine is unreachable:

```
docker version
...
failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine;
check if the path is correct and if the daemon is running: open
//./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.
```

Client reports fine (`Docker Desktop 4.68.0 (223695)`, client v29.3.1), but
the Linux engine pipe never comes up — `docker ps` / `docker network ls`
hang or fail identically.

Diagnosed earlier (same session, different chat) via
`%LOCALAPPDATA%\Docker\log.txt` / `backend.error.json` as matching a known
Docker Desktop upstream bug: **Inference Manager crash-loop** — this is
`docker/desktop-feedback#342`, not something specific to this repo or this
machine's config. Already tried and did NOT fix it:

- Killing all Docker-related processes and restarting Docker Desktop
- `wsl --shutdown` then relaunching Docker Desktop
- Clearing Docker Desktop's run directory
- Disabling `EnableDockerAI` / `enableInference` in Docker Desktop settings

So the easy remediation ladder is already exhausted. Whatever gets tried in
the new chat should assume those steps won't work again and look for
something further upstream (WSL2 distro health, a corrupt Docker Desktop
data dir needing a real reset, a version rollback/reinstall, disk space,
Windows/WSL kernel update, etc.) — check GitHub issue
`docker/desktop-feedback#342` for what actually worked for other people
hitting this, since this environment matched that report closely.

Separately: mid-way through the last session, this machine also had a
transient full DNS outage (github.com and google.com both unresolvable
against the router) that resolved on its own after a while — possibly a
side effect of some Docker/WSL2 network troubleshooting. Worth keeping an
eye on network health while poking at WSL2, but don't chase it unless it
recurs.

## What "fixed" looks like (verification steps for the new chat)

Once Docker Desktop seems to come up, verify with, in order:

1. `docker version` — both Client and Server sections populate, no npipe error.
2. `docker ps` — returns (even if empty), doesn't hang.
3. `docker run hello-world` — pulls and runs cleanly.
4. Bring up local SigNoz via Foundry (`foundryctl`) — this repo's compose
   file expects an **external** Docker network called `signoz-network`,
   created by SigNoz's own Foundry-based compose stack (not part of this
   repo). Check `signoz/README.md` if it exists, or re-derive the Foundry
   casting command — SigNoz replaced its old raw-docker-compose setup with
   this Foundry mechanism (`foundryctl`) at some point during this build;
   that migration was already done once successfully earlier in the
   project, so it should be a known-working path, not new territory.
5. `docker network ls | grep signoz-network` confirms the network exists.
6. From this repo root: `docker compose up -d --build` — brings up
   `atc-core`, `agent-runner`, `tools-db`, `tools-fs`, `tools-git`,
   `victim-postgres`, `otel-collector`.
7. `docker compose ps` — all services healthy/running.
8. Hit `http://localhost:8000` — the approval UI should load.

## What happens after Docker is confirmed working

Once steps above pass, the next chat (or this one, if continued) has clear
follow-up work already scoped from the previous session:

- **Spike S2** — verify SigNoz accepts OTLP spans with backdated
  timestamps (directly validates `services/history-seeder`, which emits
  spans with explicit past `start_time`/`end_time` — the mechanism itself
  is unit-tested against `InMemorySpanExporter`, but never verified against
  a real SigNoz ingest path).
- **Spike S3** — verify `signoz-mcp-server` trace-fetch works for the
  Narrator (`services/atc-core/src/atc_core/narrator/`).
- Full end-to-end smoke test of the 8-service compose stack.
- `make reset-demo` — also never run against a live daemon; validate it
  actually resets Postgres/fs/SQLite state correctly.
- SigNoz dashboards (Fleet Tower, Governance) — need the live UI to build.

None of that is today's job, though — today is just: **get Docker running,
verified, guided step by step.**

## How to work with me in the new chat

- Go step by step, waiting for me to run each command and paste back the
  actual output before suggesting the next step — don't dump a long list of
  things to try all at once.
- I'm doing the fixing manually with your guidance, not delegating it to
  you to run autonomously.
- Platform: Windows 11, PowerShell primary shell, Docker Desktop (not
  Docker-in-WSL-only), repo also has a Bash tool available (Git Bash).
