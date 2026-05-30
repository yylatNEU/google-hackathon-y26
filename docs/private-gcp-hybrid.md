# Private GCP Hybrid Workflow

This project can run locally while using real GCP services, then deploy a private Cloud Run backend when you want production-like pressure without making the idea public.

## Local app, real GCP

```bash
scripts/run_local_gcp.sh crypto-song-496607-d7 us-central1
```

This configures `backend/.env`, enables Vertex AI Gemini and BigQuery analytics, keeps Arize disabled, then starts FastAPI on `127.0.0.1:8000`.

Run the frontend separately:

```bash
cd frontend
npm run dev
```

## Private Cloud Run

```bash
scripts/deploy_private_cloud_run.sh crypto-song-496607-d7 us-central1
```

Then deploy the optional operations layer:

```bash
scripts/deploy_gcp_operations.sh crypto-song-496607-d7 us-central1 parkpulse-private-api
```

The deploy script uses:

- `--no-allow-unauthenticated`
- a dedicated `parkpulse-private-run` service account
- least-practical hackathon IAM for Vertex AI, BigQuery, Pub/Sub publishing, Workflows invocation, logging, and Secret Manager
- `.dockerignore` rules that keep `.env`, local DB files, virtualenvs, and tests out of the image

Cloud Run will still have a URL, but unauthenticated visitors cannot call it.

Smoke test the private service:

```bash
scripts/cloud_run_private_curl.sh crypto-song-496607-d7 us-central1 parkpulse-private-api /readyz
scripts/cloud_run_private_curl.sh crypto-song-496607-d7 us-central1 parkpulse-private-api /api/gcp-gemini/status
```

## Local frontend, private cloud backend

Use the one-command private dev launcher:

```bash
scripts/dev_private_gcp.sh crypto-song-496607-d7 us-central1 parkpulse-private-api
```

It starts:

- local frontend on `http://localhost:3000`
- authenticated private API proxy on `http://127.0.0.1:8001`
- real private Cloud Run backend behind the proxy

Or run the proxy by itself:

```bash
scripts/proxy_private_cloud_run.sh crypto-song-496607-d7 us-central1 parkpulse-private-api 8001
```

## Demo validation

Run this before a hackathon demo:

```bash
scripts/validate_private_gcp_demo.sh crypto-song-496607-d7 us-central1 parkpulse-private-api
```

It checks:

- Cloud Run is not public
- unauthenticated calls are blocked
- authenticated readiness works
- Gemini, BigQuery, and online improvement report ready
- GCP operations adapters report their Pub/Sub, FCM, and Workflows readiness
- one agent scenario completes through private Cloud Run
- BigQuery row counts increase

Optional live-ops additions are documented in [gcp-operations-additions.md](gcp-operations-additions.md).

Recovery commands:

```bash
scripts/deploy_private_cloud_run.sh crypto-song-496607-d7 us-central1
scripts/deploy_gcp_operations.sh crypto-song-496607-d7 us-central1 parkpulse-private-api
scripts/validate_private_gcp_demo.sh crypto-song-496607-d7 us-central1 parkpulse-private-api
```

## Privacy defaults

- Backend CORS defaults to local frontend origins only.
- `PARKPULSE_ALLOWED_ORIGINS` must be set before any hosted frontend can call the API.
- Cloud Run is deployed as authenticated-only.
- Secrets should go in Secret Manager or local `.env`, never into source files.
- Keep the frontend local until demo day unless you intentionally deploy a protected preview.
