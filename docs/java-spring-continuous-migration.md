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
- `POST /api/park/delegation-token`
- `GET /api/park/agent-onboarding/issuer`
- `POST /api/park/agent-onboarding/register`
- `POST /api/park/agent-onboarding/{agent_id}/certify`
- `POST /api/park/agent-onboarding/verify-credential`
- `GET /api/park/agent-onboarding/{agent_id}`
- `POST /api/park/agent-onboarding/revoke-credential`
- `GET /api/park/agent-trust/status`
- `GET /api/park/agent-trust/partners`
- `POST /api/park/agent-trust/partners`
- `GET /api/park/agent-trust/keys`
- `POST /api/park/agent-trust/keys/rotate`
- `GET /api/park/agent-trust/revocations`
- `GET /api/park/agent-trust/audit`
- `POST /api/park/handshake`
- `GET /api/park/session/{session_id}`
- `POST /api/park/session/{session_id}/capabilities`
- `POST /api/park/session/{session_id}/intent`
- `POST /api/park/session/{session_id}/propose`
- `POST /api/park/session/{session_id}/counter`
- `POST /api/park/session/{session_id}/commit`
- `GET /api/park/session/{session_id}/monitor`
- `POST /api/park/session/{session_id}/monitor`
- `GET /api/park/session/{session_id}/receipt`
- `POST /api/park/session/{session_id}/receipt`
- `POST /api/park/internal-agents/commerce/evaluate`
- `POST /api/park/internal-agents/queue/reroute`
- `GET /api/park/platform-store`
- `POST /api/park/platform-store/migrate`
- `GET /api/park/migration/java-spring/status`
- `GET /api/park/backend-gateway/status`

Spring also forwards unmigrated traffic while route groups are migrated:

- `/api/**`
- `/readyz/deep`

The fallback gateway enforces a method-aware owned-route gate. Routes listed as Spring-owned are blocked from Python fallback with a controlled `spring_owned_route_fallback_gate` response if they ever reach the catch-all proxy.

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

Spring owns the delivery REST port for durable JSONL outbox reads, dispatch creation, receiver acknowledgement, approval-decision receipts, and the delivery GCP adapter contract. Dispatch creation requires the `dispatch_live_action` role capability, enforces the tool-executor/policy-gate boundary, writes idempotency-keyed durable rows, and blocks fallback to Python for these routes:

- `POST /api/park/delivery/guest-promotion`
- `POST /api/park/delivery/worker-notification`
- `POST /api/park/delivery/equipment-command`
- `GET /api/park/delivery/gcp-adapters/status`

Spring now emits component-level delivery adapter receipts for Pub/Sub, FCM or pseudo-Firebase, Firestore mirror/write, Dataflow mirror/export readiness, and operator workflow handoff. The safe default remains local mirror mode. Live Pub/Sub REST publish, FCM HTTP v1 send, Firestore REST document write, and Workflows execution start are only called when their explicit environment gates, project config, and access token or ADC credentials are present. The remaining delivery work is partner receiver retry workers plus a real Dataflow job launcher if the platform needs to start or update Beam jobs from Spring.

Agent-trust and handshake migration is also split. Spring owns the durable registry tables for partners, key metadata, onboarding registration records, delegation-token issuance, certification scoring and issuance, credential verification, revocation lists, issuer metadata, revocation writes, audit events, and the visit-planning handshake lifecycle: identity, session readback, capability, intent, proposal, counterproposal, commit, monitor, receipt, commerce-agent policy evaluation, and queue-agent reroute recommendations.

Spring service boundaries are now split so the route services do less hidden work:

- `AgentTrustService` owns durable trust/onboarding SQLite registry operations.
- `AgentTrustCredentialCodec` owns delegation-token signing, certification credential signing and verification, key material derivation, and JWK projection.
- `AgentHandshakeService` owns handshake session lifecycle orchestration and SQLite session persistence.
- `AgentHandshakeLedgerService` owns handshake events, handoffs, policy decisions, case evaluations, receipt summaries, and receipt digests.
