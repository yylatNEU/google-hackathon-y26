# ParkPulse Weekly Budget Profile

This profile keeps the timelapse demo inside a target budget of 25 USD per week and records one week of simulated park time.

## Runtime Profile

`scripts/deploy_private_cloud_run.sh` now defaults to:

```text
PARKPULSE_COST_PROFILE=weekly_25
PARKPULSE_WEEKLY_BUDGET_USD=25
PARKPULSE_TIMELAPSE_SIM_DAYS=7
PARKPULSE_TIMELAPSE_MAX_SIM_MINUTES=10080
PARKPULSE_TIMELAPSE_STORAGE_MODE=compact
PARKPULSE_TIMELAPSE_STORAGE_BUDGET_GB_PER_WEEK=5
PARKPULSE_TIMELAPSE_LLM_INTERVAL_MINUTES=15
PARKPULSE_TIMELAPSE_FULL_SNAPSHOT_INTERVAL_MINUTES=15
PARKPULSE_VERBOSE_ARTIFACT_RETENTION_DAYS=2
```

The deployment profile also lowers always-on cost:

```text
PARKPULSE_CLOUD_RUN_MIN_INSTANCES=0
PARKPULSE_CLOUD_RUN_MAX_INSTANCES=2
PARKPULSE_CLOUD_RUN_CONCURRENCY=8
PARKPULSE_CLOUD_RUN_TIMEOUT=120
```

And it disables the expensive proof/training paths unless explicitly re-enabled:

```text
ENABLE_GCP_CLOUD_TRACE_EXPORT=false
PARKPULSE_ENABLE_OTEL_SPANS=false
ENABLE_VERTEX_GENAI_EVAL=false
PARKPULSE_ENABLE_HOSTED_EVAL_TRIGGER=false
PARKPULSE_ENABLE_GCP_ML_TRAINING=false
PARKPULSE_ENABLE_REAL_BQML_START=false
PARKPULSE_READINESS_LOAD_BQ_ROWS=false
```

## Data Policy

Use one source of truth per episode:

- Record at most 10,080 one-minute sim ticks per timelapse run.
- Keep raw event rows for audit during the 7 simulated days.
- Keep compact episode/timelapse rows for analysis.
- Keep full snapshots every 15 park minutes.
- Store full LLM prompt/output only for decision moments, not every tick.
- Keep verbose QA/debug artifacts for 2 days.

This is a simulated-time window, not a requirement to delete useful data seven real days after generation. Wall-clock cleanup is a separate local housekeeping tool for old QA artifacts.

## Local Prune

Dry-run:

```sh
make weekly-budget-prune
```

Apply:

```sh
python3 scripts/prune_parkpulse_weekly_data.py --apply
```

The prune script rewrites the local compact case bank by wall-clock row timestamp and deletes local `output/qa` artifacts older than the requested retention window. It does not delete Cloud Storage, BigQuery, Cloud Logging, or MongoDB data, and it is separate from the one-week simulated-time run length.

## Cloud Retention

For GCP, apply provider-side lifecycle controls only if you want wall-clock cleanup in addition to the one-week simulated-time run length:

- Cloud Storage bucket lifecycle: delete objects after 7 days.
- BigQuery partition expiration: 7 days on timelapse/event tables.
- Cloud Logging sink retention: keep default short retention or route only compact logs.
- MongoDB TTL index: 7 days for timelapse/raw-event collections, no TTL for explicitly promoted reusable rules.

## Cost Boundary

The weekly profile is designed for this workload:

```text
1-minute deterministic ticks
15-minute LLM decisions/summaries
event-triggered LLM only for incidents
compact snapshots and episode index
10,080 maximum simulated minutes per run
5 GB/week target storage
```

Do not enable per-minute LLM calls, hosted eval, BQML starts, or verbose full-report generation under this budget profile.
