# ParkPulse Dataflow Template

This scaffold is the production path behind the local Dataflow mirror in `backend/gcp_operations.py`.

It consumes ParkPulse Pub/Sub envelopes, normalizes them into a stable event schema, and appends them to BigQuery for agent outcome analytics, dashboards, and evaluator backtests.

## Local syntax check

```bash
python -m py_compile infra/dataflow/parkpulse_stream.py
```

## Flex Template shape

Required runtime parameters:

- `input_subscription`: full Pub/Sub subscription path.
- `output_table`: BigQuery table in `PROJECT:DATASET.TABLE` format.

Recommended environment mapping for the app:

- `ENABLE_PARKPULSE_DATAFLOW=true`
- `PARKPULSE_DATAFLOW_TEMPLATE=gs://YOUR_BUCKET/templates/parkpulse-telemetry-stream.json`
- `PARKPULSE_DATAFLOW_BIGQUERY_TABLE=PROJECT:DATASET.agent_action_outcomes`
- `PARKPULSE_PUBSUB_TOPIC=parkpulse-ops-events`

