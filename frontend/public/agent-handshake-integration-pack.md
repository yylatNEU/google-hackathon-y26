# ParkPulse Agent Handshake Integration Pack

This pack is for an external personal agent that wants to negotiate with ParkPulse as a counterparty agent, not call a one-off tool.

## What Is Included

- `docs/agent-handshake-openapi.yaml`: OpenAPI contract for onboarding, certification, handshake, negotiation, monitoring, and internal-agent gates.
- `examples/parkpulse_agent_client.py`: dependency-free Python client SDK for external agents.
- `examples/certified_agent_demo.py`: executable demo for register -> certify -> present credential -> negotiate route.
- `examples/personal-agent-client.ts`: TypeScript reference flow for app teams.
- `scripts/run_agent_handshake_conformance.py`: conformance runner for certification and protocol gates.

## Run The Full External-Agent Proof

Start the ParkPulse API and frontend, then run:

```bash
python3 examples/certified_agent_demo.py --api http://127.0.0.1:8001
```

Expected result:

- the external agent registers requested scopes
- ParkPulse certifies the agent for guest route planning
- ParkPulse issues a signed certification credential
- the credential verifies through `/api/park/agent-onboarding/verify-credential`
- the agent starts a guest session with a signed delegation token
- identity and capability cases pass
- ParkPulse proposes a route, accepts a counter request, commits, and monitors
- Commerce Agent blocks a payment probe
- Queue Agent returns a delegated reroute

## Run Conformance

```bash
python3 scripts/run_agent_handshake_conformance.py --api http://127.0.0.1:8001
```

For a production-style auth check with the dev issuer disabled and an upstream-verified admin identity:

```bash
python3 scripts/run_agent_handshake_conformance.py --api http://127.0.0.1:8011 --external-admin-email admin@example.com
```

The conformance runner proves:

- identity trust
- capability scope filtering
- under-scoped delegation rejection
- payment boundary enforcement
- queue reroute delegation
- certification credential verification
- tampered credential rejection
- issuer key-id discovery
- certification credential revocation
- post-revocation credential rejection
- partner scope allowlist enforcement
- durable trust registry status, audit history, and signing-key rotation
- trust-admin authorization gates for unauthenticated, ops, and ml_ops_admin callers
- production-style external admin identity headers when `--external-admin-email` is supplied

## External-Agent Flow

```text
External personal agent
  -> register requested scopes
  -> pass certification cases
  -> receive signed certification credential
  -> verify/present certification credential
  -> request guest delegation token
  -> start handshake
  -> declare capabilities
  -> submit intent
  -> negotiate/commit plan
  -> monitor outcome
  -> use internal-agent endpoints only inside delegated authority
```

## Protocol Extension Modes

ParkPulse is the first vertical demo of a broader agent handshake pattern. The same protocol phases apply across multiple park scenarios:

```text
identity -> capability -> intent -> proposal -> counterproposal -> commit -> monitor -> escalate/close
```

Current extension modes:

- `visit_planning`: low-wait family route, safe food, low walking
- `incident_response`: ride closure, weather, crowd spike, safety delay
- `commerce_resolution`: credit, refund offer, priority access, settlement gate
- `accessibility_support`: low-walking, sensory-safe, mobility-aware routing
- `group_coordination`: multiple personal agents negotiating a shared plan

Reusable negotiation primitives:

- proposal
- counterproposal
- priority change
- tradeoff explanation
- confidence
- accepted commitment
- live revision
- escalation request

The same contract can generalize beyond parks: airlines, hotels, hospitals, conferences, and retail all need external personal agents to negotiate with an internal operating layer under identity, permission, policy, and outcome constraints.

## Credential Contract

Approved agents receive a signed credential with stable JSON claims:

```json
{
  "agent_id": "external_family_agent",
  "certification_id": "cert_...",
  "jti": "cert_...",
  "approval": "approved_for_guest_route_planning",
  "scope": ["route_plan", "wait_time_alert", "policy_check"],
  "score_basis_points": 10000,
  "required_cases": ["capability_scope", "commerce_payment_probe", "identity_trust", "queue_reroute"],
  "iat": 1780458596,
  "exp": 1781063396,
  "alg": "EdDSA",
  "issuer": "parkpulse_agent_onboarding_authority",
  "iss": "parkpulse_agent_onboarding_authority",
  "kid": "parkpulse-ahp-ed25519-...",
  "token_type": "parkpulse_agent_certification",
  "sig": "..."
}
```

`score_basis_points` is an integer so browser and server JSON serialization produce the same signature input.

Issuer metadata is available at:

```http
GET /api/park/agent-onboarding/issuer
```

Credential revocation is available at:

```http
POST /api/park/agent-onboarding/revoke-credential
```

Revocation is a trust-admin operation. Calls must include a signed `ml_ops_admin` role session token in either `x-parkpulse-role-token` or `Authorization: Bearer ...`. Local development can issue one through:

```http
POST /api/park/auth/dev-session
```

The current MVP signs certification credentials with Ed25519 and publishes the public key through JWKS metadata. Set `PARKPULSE_AGENT_CERT_ED25519_PRIVATE_KEY_B64` from managed KMS or secret storage before third-party production use; otherwise the local dev server derives a demo key from the local delegation secret.

## Trust Registry Admin

Partner allowlists, credential revocations, signing-key records, and audit events are now stored in a SQLite WAL registry. The default path is `/tmp/parkpulse/agent_trust.db`; override it with `PARKPULSE_AGENT_TRUST_DB`.

```http
GET /api/park/agent-trust/status
GET /api/park/agent-trust/partners
POST /api/park/agent-trust/partners
GET /api/park/agent-trust/keys
POST /api/park/agent-trust/keys/rotate
GET /api/park/agent-trust/revocations
GET /api/park/agent-trust/audit
```

Use `POST /api/park/agent-trust/partners` to approve a partner and set the exact scopes its agents may request:

```json
{
  "partner_id": "external_family_os",
  "partner_name": "External Family OS",
  "status": "active",
  "trust_tier": "sandbox",
  "allowed_scopes": ["location", "party_size", "preferences", "route_plan", "wait_time_alert", "policy_check"],
  "actor": "parkpulse_trust_admin"
}
```

Use `POST /api/park/agent-trust/keys/rotate` to create a new active signing key. Old keys are retained as retired records so previously issued, unexpired credentials remain verifiable unless their certification ID is revoked.

Except for `GET /api/park/agent-trust/status`, these trust-admin routes require the `manage_agent_trust` role capability, currently granted only to `ml_ops_admin`.

## Production Identity Boundary

Local development can use `POST /api/park/auth/dev-session`, but production should disable the dev issuer and map a server-verified external identity into ParkPulse roles.

Supported upstream identity adapters:

```text
Google IAP      PARKPULSE_TRUST_GOOGLE_IAP=1
OIDC proxy      PARKPULSE_TRUST_OIDC_HEADERS=1
Firebase/Auth   PARKPULSE_TRUST_FIREBASE_HEADERS=1
```

Role mapping is explicit:

```text
PARKPULSE_ADMIN_EMAILS=admin@example.com
PARKPULSE_ADMIN_GROUPS=parkpulse-admins
PARKPULSE_OPS_EMAILS=ops@example.com
PARKPULSE_OPS_GROUPS=parkpulse-ops
```

Trusted headers:

```text
Google IAP:    x-goog-authenticated-user-email
OIDC proxy:    x-parkpulse-verified-email, x-parkpulse-verified-groups
Firebase/Auth: x-firebase-auth-user-email
```

`GET /api/park/agent-trust/status` returns `auth_boundary` so integrations can verify whether the deployment is still in local-dev mode or has an external identity provider configured.

## Minimum Passing Agent

An external agent must request these scopes for the current MVP route-planning certification:

```json
[
  "location",
  "party_size",
  "preferences",
  "accessibility_needs",
  "budget",
  "ride_preference",
  "route_plan",
  "wait_time_alert",
  "food_recommendation",
  "safety_notice",
  "compensation_offer",
  "policy_check",
  "session_commit"
]
```

It must also retain these blocked actions:

```json
[
  "auto_purchase",
  "share_health_data",
  "accept_refund_without_user"
]
```

Partners can be constrained with a narrower allowlist:

```json
{
  "partner_id": "external_family_os",
  "partner_name": "External Family OS",
  "partner_allowed_scopes": ["location", "party_size", "preferences", "route_plan"]
}
```

If the requested scopes exceed the partner allowlist, certification is blocked and no credential is issued.

## Policy Boundary

Certification does not give the external agent blanket authority. It only proves the agent can participate in guest route planning. The live delegation token still controls session-level authority, and ParkPulse still blocks or escalates:

- payment
- refund
- medical escalation
- identity-sensitive action
- health-data sharing
- any action outside the declared receive/share scope
