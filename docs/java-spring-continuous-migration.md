# Java Spring Continuous Migration

ParkPulse now has a side-by-side Spring Boot backend under `spring-backend/`.

## Current Slice

Spring owns only the first safe migration slice:

- `GET /`
- `GET /healthz`
- `GET /readyz`
- `GET /api/park/platform-store`
- `POST /api/park/platform-store/migrate`
- `GET /api/park/migration/java-spring/status`

Python remains authoritative for agent orchestration, Gemini/Vertex calls, Mongo operational memory, live feeds, delivery, simulation, and all unmigrated `/api/park/*` routes.

## Data Authority

Both runtimes use the same SQLite platform registry by default:

- `PARKPULSE_PLATFORM_DB`, default `/tmp/parkpulse/park_data.db`
- `PARKPULSE_RUNTIME_DIR`, default `/tmp/parkpulse`

The migration is non-destructive. It creates registry tables if missing, records observed local stores, and preserves any legacy `backend/park_data.db` without copying or deleting it.

## Auth Boundary

Spring verifies the same `pprole` signed role session token format as Python.

Admin-only Spring routes require `ml_ops_admin`:

- `GET /api/park/platform-store`
- `POST /api/park/platform-store/migrate`
- `GET /api/park/migration/java-spring/status`

## Run

```bash
scripts/run_spring_backend.sh
```

The default port is `8010`; override with `PARKPULSE_SPRING_PORT`.

## Migration Rule

Move one route group at a time only after:

- route response parity is tested against Python,
- SQLite authority is preserved,
- rollback is simply stopping Spring and routing traffic back to Python,
- no Mongo/GCP dependency is introduced on the hot readiness path.
