# Ops Agent Conversation Release - 2026-06-05

This file defines the deployable release scope for the ParkPulse ops-agent conversation pipeline. Use it to keep production deploys isolated from unrelated dirty workspace changes.

## Production Revisions

- Backend service: `parkpulse-private-api`
- Active backend revision verified during this release: `parkpulse-private-api-00129-xwq`
- Frontend service: `parkpulse-frontend`
- Active frontend revision verified during this release: `parkpulse-frontend-00009-5px`
- Frontend URL: `https://parkpulse-frontend-xtqfwzeoga-uc.a.run.app`

## Release Scope

Backend conversation hot path:

- `backend/main.py`
- `backend/test_main_lightweight_copilot.py`

Frontend conversation surface and proxy:

- `frontend/server.mjs`
- `frontend/src/app/ops-agent/page.tsx`
- `frontend/src/hooks/useParkPulseState.ts`
- `frontend/src/lib/api.ts`

Deployment and verification:

- `scripts/build_ops_agent_backend_release_source.sh`
- `scripts/cloud_run_private_curl.sh`
- `scripts/deploy_private_cloud_run.sh`
- `scripts/deploy_frontend_cloud_run.sh`
- `scripts/verify_private_cloud_run_deploy.sh`
- `scripts/verify_frontend_smoke.py`
- `Makefile`

## Confirmed Behavior

- The `/ops-agent` page remains the dedicated conversation page for department/operator interaction.
- The frontend proxy keeps the deployed app on same-origin API calls and reduces repeated identity-token fetches.
- The copilot endpoint can return through the lightweight local hot path after the full runtime is loaded.
- Direct production smoke after runtime load returned HTTP 200 with `latency_diagnostics.wrapper.path=lightweight_hot_path_local_only`.
- Focused backend regression test for the lightweight wrapper passed.
- Frontend lint, typecheck, build, and deployed smoke passed during this release.

## Deploy Guard

`scripts/deploy_private_cloud_run.sh` now refuses to shift traffic for the production service unless one of these is set:

```bash
PARKPULSE_DEPLOY_NO_TRAFFIC=true
```

or:

```bash
PARKPULSE_ALLOW_PRODUCTION_TRAFFIC_UPDATE=true
```

The script records Cloud Run service JSON before and after deploys in `output/deploy/` by default. `output/` is ignored by git.

## Isolated Backend Release

Build a clean backend release source tree from `HEAD` plus only the approved ops-agent overlays:

```bash
make gcp-build-ops-agent-release
```

The builder writes `output/release/ops-agent-backend-release-manifest.json` inside the generated source tree. Use that generated directory for no-traffic backend canaries:

```bash
cd /tmp/parkpulse-ops-agent-backend-release.xxxxxx
PARKPULSE_DEPLOY_NO_TRAFFIC=true \
PARKPULSE_DEPLOY_TAG=ops-agent-canary \
PARKPULSE_COPILOT_SEMANTIC_MEMORY=true \
PARKPULSE_MONGO_MODEL_EMBEDDINGS=true \
scripts/deploy_private_cloud_run.sh crypto-song-496607-d7 us-central1
```

Verify the tagged no-traffic revision URL with traffic assertions disabled:

```bash
PARKPULSE_PRIVATE_VERIFY_URL=https://ops-agent-canary---parkpulse-private-api-xtqfwzeoga-uc.a.run.app \
PARKPULSE_SKIP_TRAFFIC_CHECK=true \
scripts/verify_private_cloud_run_deploy.sh crypto-song-496607-d7 us-central1 parkpulse-private-api
```

Only after the no-traffic revision passes verification should production traffic be shifted with:

```bash
PARKPULSE_ALLOW_PRODUCTION_TRAFFIC_UPDATE=true scripts/deploy_private_cloud_run.sh crypto-song-496607-d7 us-central1
```

## Open Gap

The workspace still contains unrelated dirty files outside this release scope. Do not bulk deploy or bulk commit from the workspace. For backend production deploys, use the isolated source tree or a scoped commit until the unrelated work is reviewed separately.
