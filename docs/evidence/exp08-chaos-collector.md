# Experiment #8 — Chaos test: kill the collector mid-run

Ran 2026-07-17, live stack, agent-runner actively running its 3 personas.

## Baseline

`actions` table row count before outage: **12**.

## Outage

```
docker stop atc-otel-collector-1
```

Collector down at 19:06:43 (`"Received signal from OS", "signal": "terminated"`).

Fired 4 more gated MCP calls (`fs__read`) directly against the gateway while
the collector was down. All 4 returned normal `200 OK` gateway responses —
none blocked, none errored at the gate layer.

`actions` table row count after: **16** (4 new rows recorded during the
outage).

`atc-core` logs during the outage show gate traffic continuing normally
(`200 OK` / `202 Accepted` on `/mcp/`, heartbeats still accepted) alongside
the OTel exporter's own retry noise:

```
INFO:     ... "POST /mcp/ HTTP/1.1" 200 OK
INFO:     ... "POST /mcp/ HTTP/1.1" 200 OK
...
Transient error HTTPConnectionPool(host='otel-collector', port=4318):
Max retries exceeded ... Failed to resolve 'otel-collector' ...
encountered while exporting metrics batch, retrying in 1.04s.
```

## Recovery

```
docker start atc-otel-collector-1
```

Collector restart logged "Everything is ready" at 19:07:11. Fresh spans
confirmed landing in ClickHouse shortly after:

```
agent-runner   31   2026-07-17 19:07:51.611212176
atc-core       57   2026-07-17 19:08:12.227605356
```

## Verdict

Falsifiable claim confirmed live: **OTLP export is fire-and-forget — a dead
SigNoz/collector never blocks the gate path.** Gate decisions kept
happening (SQLite actions row count grew 12 -> 16) throughout the outage;
telemetry resumed on its own within ~30-70s of the collector coming back,
no manual intervention beyond the restart itself.
