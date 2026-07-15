# Local SigNoz (Foundry-managed)

Brought up via `foundryctl` casting this directory's `casting.yaml`
(`deployment.flavor: compose`, `mode: docker`) - not a raw `docker compose`
file maintained in this repo. Creates the external `signoz-network` that
this repo's own `docker-compose.yml` attaches to.

## First-run setup (required once per fresh SigNoz volume)

SigNoz's OTLP ingester (`signoz-ingester`) only receives its real pipeline
config (OTLP receivers on 4317/4318, ClickHouse exporters, etc.) from the
control plane (`signoz-signoz-0`) over OpAMP *after* an org/admin account
exists. Before that, `signoz-ingester`'s logs show a repeating
`"cannot create agent without orgId"` error from the control plane and the
ingester's OTLP ports never actually bind (`docker compose logs
otel-collector` shows `connection refused` to `signoz-ingester:4317`) -
this looks like a networking problem but isn't; every span and metric this
repo's `otel-collector` sends is silently dropped until it's fixed.

Fix: open `http://localhost:8080` and complete the signup wizard (or POST
to `/api/v1/register` directly - see `.env`'s commented-out
`SIGNOZ_UI_ADMIN_*` fields for the account created this way). After the
account exists, `signoz-ingester` picks up the real config within ~1
minute (`"Config has changed, reloading"` in its logs) and starts
accepting OTLP. Restart `otel-collector` afterwards
(`docker compose restart otel-collector`) so it reconnects instead of
waiting out its retry backoff.

Verify ingestion landed by querying ClickHouse directly rather than
guessing from collector logs alone:

```
docker exec signoz-telemetrystore-clickhouse-0-0 clickhouse-client \
  --query "SELECT serviceName, count(), max(timestamp) FROM signoz_traces.distributed_signoz_index_v3 GROUP BY serviceName"
```
