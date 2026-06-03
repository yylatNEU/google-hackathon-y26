# Java Spring Continuous Migration

ParkPulse now has a side-by-side Spring Boot backend under `spring-backend/`.
Spring is the intended backend entrypoint during migration: native Spring routes are served directly, and unmigrated routes are forwarded to Python through a controlled fallback gateway.

## Current Slice

Spring owns only the first safe migration slice:

- `GET /`
- `GET /healthz`
- `GET /readyz`
- `GET /api/park/auth/dev-session`
- `POST /api/park/auth/dev-session`
- `GET /api/park/auth/status`
- `GET /api/park/role-access-contracts`
- `GET /api/park/reliability`
- `GET /api/park/latency-diagnostics`
- `GET /api/park/authorization-audit`
- `GET /api/park/delivery/contract`
- `GET /api/park/delivery/outbox`
- `POST /api/park/delivery/acknowledge`
- `POST /api/park/delivery/approval-decision`
- `GET /api/park/platform-store`
- `POST /api/park/platform-store/migrate`
- `GET /api/park/migration/java-spring/status`
- `GET /api/park/backend-gateway/status`

Spring also forwards unmigrated traffic while route groups are migrated:

- `/api/**`
- `/readyz/deep`

Python remains the implementation backend for agent orchestration, Gemini/Vertex calls, Mongo operational memory, live feeds, delivery, simulation, and all unmigrated `/api/*` routes. Clients should call Spring first so the handoff can happen one route group at a time.

## Data Authority

Both runtimes use the same SQLite platform registry by default:

- `PARKPULSE_PLATFORM_DB`, default `/tmp/parkpulse/park_data.db`
- `PARKPULSE_RUNTIME_DIR`, default `/tmp/parkpulse`

The migration is non-destructive. It creates registry tables if missing, records observed local stores, and preserves any legacy `backend/park_data.db` without copying or deleting it.

## Auth Boundary

Spring verifies the same `pprole` signed role session token format as Python.
Spring also issues local development role-session tokens at `/api/park/auth/dev-session` when the dev issuer is enabled.

Admin-only Spring routes require `ml_ops_admin`:

- `GET /api/park/platform-store`
- `POST /api/park/platform-store/migrate`
- `GET /api/park/migration/java-spring/status`

## Run

```bash
scripts/run_spring_backend.sh
```

The default port is `8010`; override with `PARKPULSE_SPRING_PORT`.

The fallback gateway forwards to Python at `http://127.0.0.1:8000` by default. Override with `PARKPULSE_PYTHON_BACKEND_URL`.
Gateway safeguards:

- `PARKPULSE_PYTHON_BACKEND_TIMEOUT_MS`, default `25000`
- `PARKPULSE_PYTHON_BACKEND_MAX_BODY_BYTES`, default `2097152`
- inbound `x-parkpulse-spring-gateway` is stripped and re-issued by Spring
- only `http` and `https` Python upstream URLs are accepted

## Migration Rule

Move one route group at a time only after:

- route response parity is tested against Python,
- SQLite authority is preserved,
- rollback is simply stopping Spring and routing traffic back to Python,
- no Mongo/GCP dependency is introduced on the hot readiness path.

## Gating Rule

Spring verifies signed role sessions with issuer and audience checks:

- `PARKPULSE_ROLE_TOKEN_ISSUER`, default `parkpulse-local-dev`
- `PARKPULSE_ROLE_TOKEN_AUDIENCE`, default `parkpulse-role-access`

In `PARKPULSE_ENV=production` or `ENVIRONMENT=production`, Spring rejects the default local role-session secret and disables the local dev-session issuer unless `PARKPULSE_ALLOW_PRODUCTION_DEV_ROLE_ISSUER=true` is set intentionally.

Spring records protected-route authorization decisions to SQLite in `spring_authorization_audit_events`. Audit persistence is best-effort: an audit write failure does not allow a blocked request or block an otherwise valid request.

Delivery migration is split deliberately. Spring owns durable JSONL outbox reads plus receiver acknowledgement and approval-decision receipts. New dispatch creation routes still fall back to Python until the agent-boundary executor is migrated:

- `POST /api/park/delivery/guest-promotion`
- `POST /api/park/delivery/worker-notification`
- `POST /api/park/delivery/equipment-command`
