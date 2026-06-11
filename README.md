# ParkPulse

ParkPulse is an amusement-park operating intelligence platform built for the Google Hackathon Y26 project. It combines live park-state simulation, agentic operations workflows, guest triage, staff training, policy-gated dispatch, venue-profile grounding, and reliability QA into one reviewable platform.

The current branch is a production-reliability checkpoint. The app is designed to demonstrate how scan, react, and proact agents can reason over park conditions while staying inside explicit policy, identity, memory, and human-approval boundaries.

## What It Does

- Tracks simulated and live-ready park state: ride waits, zone density, staff readiness, weather, event waves, accessibility constraints, and operating incidents.
- Runs role-scoped agents for scan-only observation, reactive incident response, and proactive bottleneck forecasting.
- Supports guest-message triage with deterministic fallbacks, optional LLM drafting, ticket creation, memory receipts, and staff-training feedback loops.
- Provides an Experience Studio for grounded guest-experience packages, event-team PDFs, visual prompts, and review gates.
- Exposes agent handshake, delegation token, onboarding, certification, trust registry, and protocol receipt surfaces.
- Includes a Spring backend migration layer for selected platform services.
- Adds production QA coverage for latency, policy gates, MongoDB memory fallbacks, GCP trace setup, frontend build quality, and wrapper contracts.

## Repository Layout

```text
backend/         FastAPI platform API, simulation, agents, memory, QA tests
frontend/        Vite/React frontend surfaces and Playwright checks
spring-backend/  Java 21 Spring backend migration and service tests
scripts/         QA, deployment, GCP, MongoDB, live-feed, and evaluation tools
docs/            Architecture, operations, MongoDB, budget, and policy notes
infra/           Dataflow and workflow infrastructure sketches
artifacts/       Demo assets that are safe to publish
output/          Generated local reports and screenshots, ignored by git
```

## Prerequisites

- Python 3.13
- Node.js 22
- Java 21
- Maven wrapper from `spring-backend/mvnw`
- Optional: Google Cloud CLI for private Cloud Run/GCP workflows
- Optional: MongoDB Atlas or local MongoDB for operational memory

## Local Setup

Create the backend environment:

```bash
python3 -m venv backend/venv
backend/venv/bin/python -m pip install --upgrade pip
backend/venv/bin/python -m pip install -r backend/requirements.txt
```

Install frontend dependencies:

```bash
cd frontend
npm ci
cd ..
```

Run the Spring tests once to resolve Maven dependencies:

```bash
cd spring-backend
./mvnw test
cd ..
```

## Environment Files

Real secrets must stay in local `.env` files or a secret manager. The repository tracks only example files:

- `backend/.env.mongodb.example`
- `backend/.env.gcp.example`
- `backend/.env.gemini-enterprise.example`
- `backend/.env.arize.example`

Copy only what you need into `backend/.env` and replace placeholders locally:

```bash
cp backend/.env.mongodb.example backend/.env
```

Do not commit `backend/.env`, root `.env`, frontend `.env`, service-account JSON, private keys, API keys, or raw MongoDB connection strings.

## Running Locally

Start the backend:

```bash
PYTHONPATH=backend backend/venv/bin/python -m uvicorn parkpulse_api:app --app-dir backend --reload --port 8000
```

Start the frontend:

```bash
cd frontend
npm run dev
```

Open the frontend at the local URL printed by Vite. The frontend API helper defaults to the local backend unless runtime scripts override it.

## Useful Commands

Fast QA:

```bash
make qa-fast
```

Release QA:

```bash
make qa-release
```

Backend tests:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=backend backend/venv/bin/python -m pytest -q backend
```

Frontend checks:

```bash
cd frontend
npm run lint
npm run typecheck
npm run build
```

Spring tests:

```bash
cd spring-backend
./mvnw test
```

Backend coverage:

```bash
make coverage-backend
```

Current known coverage status from the latest local report is about `87.6%`, below the configured `98%` backend gate. Functional test suites pass, but the coverage policy still needs focused expansion or a recalibrated threshold.

## Security

GitHub native secret scanning and push protection are enabled for the repository. Non-provider pattern scanning was not enabled by GitHub for this repo, so the repository also includes a `gitleaks` GitHub Actions workflow that runs on pull requests and pushes to `main` and `codex/**` branches.

Local credential hygiene:

- Keep real credentials in ignored `.env` files or Secret Manager.
- Use placeholders in documentation and example env files.
- Run a local high-confidence scan before pushing when touching env, deployment, or credential-handling code.
- Rotate any key immediately if it is ever committed, even if later removed.

## Deployment Notes

Private GCP and Cloud Run helpers live in `scripts/` and `Makefile`:

```bash
make gcp-bootstrap
make gcp-deploy-private
make gcp-validate-private
make gcp-verify-agent-roles
```

Deployment scripts expect project-specific GCP configuration and secrets to be supplied by environment variables or Secret Manager. Do not hard-code deployment credentials in this repository.

## License

This project is licensed under the MIT License. See `LICENSE` for details.

## Latest QA Checkpoint

The pushed checkpoint branch is:

```text
codex/parkpulse-qa-reliability-checkpoint
```

Recent verified gates:

- Full backend suite: `612 passed, 1 skipped`
- Spring suite: `34 passed`
- Frontend: lint, typecheck, and production build pass
- Targeted wrapper/product-learning additions pass

Remaining release-readiness gap:

- Backend coverage policy remains below the `98%` target.
- The branch is broad and should be reviewed as a checkpoint PR rather than a narrow patch.

## Contributing

1. Work on a branch, preferably with the `codex/` prefix for Codex-generated changes.
2. Keep generated reports in `output/` unless a report is intentionally promoted to `docs/` or `artifacts/`.
3. Run the relevant QA gate before pushing.
4. Confirm `git status --short` is clean before opening a PR.
5. Do not include secrets, raw production data, or private customer data in commits.
