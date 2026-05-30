# Optional Arize Pipeline Policy

ParkPulse now treats GCP/BigQuery as the default online improvement loop. Arize AX is optional and should be used only as an external trace sink when outbound hosted tracing is intentional.

## Default Online Improvement Path

Use these values for the GCP-backed loop:

```bash
PARKPULSE_ONLINE_IMPROVEMENT_PROVIDER=gcp
ENABLE_BIGQUERY_ANALYTICS=true
BIGQUERY_DATASET=parkpulse_analytics
BIGQUERY_AUTO_CREATE_TABLES=true
ENABLE_ARIZE_TRACING=false
```

With this setup:

- Agent runs continue even if hosted tracing providers are unavailable.
- Local scorecards remain the request-time quality gate.
- Decisions, dispatches, outcomes, and eval summaries are mirrored to BigQuery when GCP auth and table permissions are available.
- BigQuery export failures return a preview/error payload instead of blocking the agent run.

## Optional Arize Export Policy

Set these in `backend/.env` when outbound tracing is intentional:

```bash
ENABLE_ARIZE_TRACING=true
PARKPULSE_ENABLE_OPTIONAL_ARIZE=true
ARIZE_EXPORT_POLICY=useful
ARIZE_EXPORT_BACKGROUND_SPANS=false
```

With the default `useful` policy:

- API, user-triggered, demo, eval, ledger, and operator spans are exported.
- Background-loop `park_mediator.react_to_park_state` spans are exported only when they create new signals.
- Routine no-op background ticks are dropped before the OTLP exporter sends them.

Use `ARIZE_EXPORT_POLICY=all` or `ARIZE_EXPORT_BACKGROUND_SPANS=true` only for short debugging sessions.
