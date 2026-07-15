# ATC SigNoz Dashboards

`fleet-tower.json` and `governance.json` - authored against the metrics
confirmed live in this session (`atc_actions_total`, `atc_interceptions_total`,
`atc_approval_latency_seconds`, `atc_agent_risk_score`, `atc_agent_heartbeat`,
`atc_novel_resource_total`, `agent_tokens_total` - all verified landing in
ClickHouse via `docker exec signoz-telemetrystore-clickhouse-0-0
clickhouse-client --query "SELECT DISTINCT metric_name FROM
signoz_metrics.distributed_samples_v4"`).

**Status: authored, not yet import-verified.** `POST /api/v1/dashboards`
requires the same authenticated session (`SIGNOZ-API-KEY` or a browser
session) that spike S3's Trace API integration is also blocked on - see
`signoz/README.md` for the first-run account already created this session
(`admin@atc.local`, password in `.env`'s commented `SIGNOZ_UI_ADMIN_*`
fields). The widget JSON shape (`query.builder.queryData[]` with
`aggregateOperator`/`aggregateAttribute`/`groupBy`) matches SigNoz's
documented dashboard export format, but this exact file has not been
round-tripped through a real import on this SigNoz version (v0.133.0) yet.

## To finish verifying

1. Log into `http://localhost:8080` as `admin@atc.local`.
2. New Dashboard -> Import JSON -> paste `fleet-tower.json`, then
   `governance.json`.
3. Confirm each panel renders (not empty/erroring) against the live
   metrics - agent-runner + the gateway need to be running so the
   `atc_*` series have recent data points.
4. If any panel is empty or the import rejects the JSON, the query shape
   needs adjusting to match what this SigNoz version actually expects -
   check the panel's own "Edit query" UI, which will show the working
   shape, and patch the corresponding widget here to match.
