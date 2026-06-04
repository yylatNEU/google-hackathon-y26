from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any


ROLE_ORDER = ["customer", "onsite_worker", "ops_team", "ml_ops_admin"]

ROLE_ALIASES = {
    "guest": "customer",
    "worker": "onsite_worker",
    "onsite": "onsite_worker",
    "ops": "ops_team",
    "admin": "ml_ops_admin",
    "ml_admin": "ml_ops_admin",
}

CAPABILITY_MATRIX = {
    "read_identity_status": {"ops_team", "ml_ops_admin"},
    "read_platform_status": {"ml_ops_admin"},
    "read_role_contracts": set(ROLE_ORDER),
    "read_guest_guidance": {"customer", "onsite_worker", "ops_team"},
    "read_worker_tasks": {"onsite_worker", "ops_team"},
    "read_staff_training": {"onsite_worker", "ops_team", "ml_ops_admin"},
    "use_staff_training": {"onsite_worker", "ops_team", "ml_ops_admin"},
    "read_staff_training_analytics": {"ops_team", "ml_ops_admin"},
    "read_ops_evidence": {"ops_team", "ml_ops_admin"},
    "read_executive_intelligence": {"ml_ops_admin"},
    "review_executive_artifact": {"ml_ops_admin"},
    "read_ml_training": {"ml_ops_admin"},
    "use_ops_chat": {"ops_team", "ml_ops_admin"},
    "use_guest_chat": {"customer"},
    "use_worker_chat": {"onsite_worker", "ops_team"},
    "dispatch_live_action": {"ops_team"},
    "acknowledge_dispatch": {"onsite_worker", "ops_team"},
    "run_live_outcome_cycle": {"ops_team", "ml_ops_admin"},
    "record_supervised_label": {"ml_ops_admin"},
    "review_learning": {"ml_ops_admin"},
    "promote_learning": {"ml_ops_admin"},
    "start_offline_training": {"ml_ops_admin"},
    "manage_platform_store": {"ml_ops_admin"},
    "refresh_policy_snapshot": {"ops_team", "ml_ops_admin"},
    "manage_agent_trust": {"ml_ops_admin"},
}

ROLE_FORBIDDEN_REASONS = {
    "customer": "Customer surfaces can ask for help and read guest-safe guidance only.",
    "onsite_worker": "Onsite worker surfaces can act on assigned tasks but cannot inspect model, BigQuery, or promotion internals.",
    "ops_team": "Ops surfaces can review live evidence and action receipts but cannot mutate learning authority.",
    "ml_ops_admin": "ML/admin surfaces can inspect and start offline learning jobs but cannot dispatch live park actions.",
}


def _role(
    role_id: str,
    label: str,
    surface: str,
    primary_users: list[str],
    can_read: list[str],
    can_do: list[str],
    cannot_read: list[str],
    cannot_do: list[str],
    evidence_products: list[str],
    ui_contract: str,
    llm_contract: str,
) -> dict[str, Any]:
    return {
        "id": role_id,
        "label": label,
        "surface": surface,
        "primary_users": primary_users,
        "can_read": can_read,
        "can_do": can_do,
        "cannot_read": cannot_read,
        "cannot_do": cannot_do,
        "evidence_products": evidence_products,
        "ui_contract": ui_contract,
        "llm_contract": llm_contract,
    }


def normalize_role(role: str | None, default: str = "ops_team") -> str:
    value = str(role or default or "ops_team").strip().lower().replace("-", "_")
    return ROLE_ALIASES.get(value, value)


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _csv_set(name: str) -> set[str]:
    return {item.strip().lower() for item in os.getenv(name, "").split(",") if item.strip()}


def _strip_identity_prefix(value: str) -> str:
    raw = str(value or "").strip()
    if ":" in raw:
        raw = raw.rsplit(":", 1)[-1]
    return raw.strip().lower()


def _header(headers: dict[str, str], key: str) -> str:
    return str(headers.get(key.lower()) or headers.get(key) or "").strip()


def _split_claim_values(value: str) -> set[str]:
    return {item.strip().lower() for item in str(value or "").replace(";", ",").split(",") if item.strip()}


def _role_from_external_claims(email: str, groups: set[str], trusted_role: str | None = None) -> str | None:
    normalized_email = _strip_identity_prefix(email)
    if normalized_email and normalized_email in _csv_set("PARKPULSE_ADMIN_EMAILS"):
        return "ml_ops_admin"
    if groups & _csv_set("PARKPULSE_ADMIN_GROUPS"):
        return "ml_ops_admin"
    if normalized_email and normalized_email in _csv_set("PARKPULSE_OPS_EMAILS"):
        return "ops_team"
    if groups & _csv_set("PARKPULSE_OPS_GROUPS"):
        return "ops_team"
    if _truthy(os.getenv("PARKPULSE_ALLOW_TRUSTED_ROLE_HEADER"), False) and trusted_role:
        role = normalize_role(trusted_role)
        if role in ROLE_ORDER:
            return role
    return None


def verify_external_role_identity(headers: dict[str, str], default_role: str = "ops_team") -> dict[str, Any]:
    """Map server-verified identity provider headers to a ParkPulse role.

    These headers are trusted only when their provider flag is enabled. Production
    should set the flag only behind Google IAP, an OIDC-aware reverse proxy, or
    Firebase/Auth middleware that has already verified the user token.
    """
    normalized_headers = {str(key).lower(): str(value) for key, value in (headers or {}).items()}
    providers: list[dict[str, str]] = []
    if _truthy(os.getenv("PARKPULSE_TRUST_GOOGLE_IAP") or os.getenv("GOOGLE_IAP_AUDIENCE"), False):
        providers.append(
            {
                "provider": "google_iap",
                "email": _header(normalized_headers, "x-goog-authenticated-user-email"),
                "subject": _header(normalized_headers, "x-goog-authenticated-user-id"),
                "groups": _header(normalized_headers, "x-goog-authenticated-user-groups"),
                "role": "",
            }
        )
    if _truthy(os.getenv("PARKPULSE_TRUST_OIDC_HEADERS"), False) or (os.getenv("PARKPULSE_OIDC_ISSUER") and os.getenv("PARKPULSE_OIDC_AUDIENCE")):
        providers.append(
            {
                "provider": "oidc_proxy",
                "email": _header(normalized_headers, "x-parkpulse-verified-email"),
                "subject": _header(normalized_headers, "x-parkpulse-verified-subject"),
                "groups": _header(normalized_headers, "x-parkpulse-verified-groups"),
                "role": _header(normalized_headers, "x-parkpulse-verified-role"),
            }
        )
    if _truthy(os.getenv("PARKPULSE_TRUST_FIREBASE_HEADERS"), False) or os.getenv("FIREBASE_PROJECT_ID") or os.getenv("PARKPULSE_FIREBASE_PROJECT_ID"):
        providers.append(
            {
                "provider": "firebase_auth",
                "email": _header(normalized_headers, "x-firebase-auth-user-email"),
                "subject": _header(normalized_headers, "x-firebase-auth-user-id"),
                "groups": _header(normalized_headers, "x-firebase-auth-user-groups"),
                "role": _header(normalized_headers, "x-firebase-auth-role"),
            }
        )
    for provider in providers:
        email = _strip_identity_prefix(provider.get("email") or "")
        groups = _split_claim_values(provider.get("groups") or "")
        role = _role_from_external_claims(email, groups, provider.get("role") or None)
        if role:
            return {
                "status": "authenticated",
                "authenticated": True,
                "auth_method": f"external_{provider['provider']}",
                "role": normalize_role(role, default=default_role),
                "subject": provider.get("subject") or email,
                "email": email,
                "groups": sorted(groups),
                "issuer": provider["provider"],
                "token_status": "server_verified_external_identity",
            }
        if email or groups:
            return {
                "status": "role_unmapped",
                "authenticated": False,
                "auth_method": f"external_{provider['provider']}",
                "role": normalize_role(None, default=default_role),
                "subject": provider.get("subject") or email,
                "email": email,
                "groups": sorted(groups),
                "issuer": provider["provider"],
                "reason": "External identity was verified by the upstream provider but is not mapped to a ParkPulse role.",
            }
    return {"status": "missing", "authenticated": False, "reason": "No trusted external identity headers were present."}


def identity_provider_readiness() -> dict[str, Any]:
    providers = {
        "google_iap": _truthy(os.getenv("PARKPULSE_TRUST_GOOGLE_IAP") or os.getenv("GOOGLE_IAP_AUDIENCE"), False),
        "oidc_proxy": _truthy(os.getenv("PARKPULSE_TRUST_OIDC_HEADERS"), False) or bool(os.getenv("PARKPULSE_OIDC_ISSUER") and os.getenv("PARKPULSE_OIDC_AUDIENCE")),
        "firebase_auth": _truthy(os.getenv("PARKPULSE_TRUST_FIREBASE_HEADERS"), False) or bool(os.getenv("FIREBASE_PROJECT_ID") or os.getenv("PARKPULSE_FIREBASE_PROJECT_ID")),
    }
    role_mapping = {
        "admin_emails": len(_csv_set("PARKPULSE_ADMIN_EMAILS")),
        "admin_groups": len(_csv_set("PARKPULSE_ADMIN_GROUPS")),
        "ops_emails": len(_csv_set("PARKPULSE_OPS_EMAILS")),
        "ops_groups": len(_csv_set("PARKPULSE_OPS_GROUPS")),
        "trusted_role_header_enabled": _truthy(os.getenv("PARKPULSE_ALLOW_TRUSTED_ROLE_HEADER"), False),
    }
    external_ready = any(providers.values()) and any(value for key, value in role_mapping.items() if key != "trusted_role_header_enabled")
    return {
        "external_identity_providers": providers,
        "role_mapping": role_mapping,
        "external_identity_ready": external_ready,
        "required_headers": {
            "google_iap": ["x-goog-authenticated-user-email"],
            "oidc_proxy": ["x-parkpulse-verified-email", "x-parkpulse-verified-groups"],
            "firebase_auth": ["x-firebase-auth-user-email"],
        },
        "boundary": "External identity headers are trusted only when the corresponding provider flag is enabled behind a verifying proxy or middleware.",
    }


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + ("=" * (-len(value) % 4)))


def sign_role_session(
    subject: str,
    role: str,
    secret: str,
    ttl_seconds: int = 3600,
    issuer: str = "parkpulse-local-dev",
    now: int | None = None,
) -> str:
    issued_at = int(now if now is not None else time.time())
    payload = {
        "sub": str(subject or "parkpulse-operator"),
        "role": normalize_role(role),
        "iat": issued_at,
        "exp": issued_at + max(60, int(ttl_seconds or 3600)),
        "iss": issuer,
        "aud": "parkpulse-role-access",
    }
    payload_part = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = hmac.new(str(secret or "").encode("utf-8"), payload_part.encode("ascii"), hashlib.sha256).digest()
    return f"pprole.{payload_part}.{_b64encode(signature)}"


def verify_role_session(token: str | None, secret: str, now: int | None = None) -> dict[str, Any]:
    if not token:
        return {"status": "missing", "authenticated": False, "reason": "Missing signed role session token."}
    parts = str(token).strip().split(".")
    if len(parts) != 3 or parts[0] != "pprole":
        return {"status": "invalid", "authenticated": False, "reason": "Role session token has an invalid format."}
    expected = hmac.new(str(secret or "").encode("utf-8"), parts[1].encode("ascii"), hashlib.sha256).digest()
    try:
        supplied = _b64decode(parts[2])
    except Exception:
        return {"status": "invalid", "authenticated": False, "reason": "Role session signature is not decodable."}
    if not hmac.compare_digest(expected, supplied):
        return {"status": "invalid", "authenticated": False, "reason": "Role session signature does not match."}
    try:
        claims = json.loads(_b64decode(parts[1]).decode("utf-8"))
    except Exception:
        return {"status": "invalid", "authenticated": False, "reason": "Role session payload is not decodable."}
    current = int(now if now is not None else time.time())
    role = normalize_role(str(claims.get("role") or ""))
    if role not in ROLE_ORDER:
        return {"status": "invalid", "authenticated": False, "reason": "Role session contains an unknown role.", "claims": claims}
    if int(claims.get("exp") or 0) <= current:
        return {"status": "expired", "authenticated": False, "reason": "Role session token is expired.", "role": role, "claims": claims}
    return {
        "status": "authenticated",
        "authenticated": True,
        "role": role,
        "subject": str(claims.get("sub") or ""),
        "issuer": str(claims.get("iss") or ""),
        "expires_at": int(claims.get("exp") or 0),
        "claims": claims,
    }


def authorize_role_action(
    role: str | None,
    capability: str,
    resource: str | None = None,
    detail: str | None = None,
    default_role: str = "ops_team",
) -> dict[str, Any]:
    normalized = normalize_role(role, default=default_role)
    allowed_roles = CAPABILITY_MATRIX.get(capability, set())
    known_role = normalized in ROLE_ORDER
    allowed = known_role and normalized in allowed_roles
    return {
        "status": "allowed" if allowed else "blocked",
        "allowed": allowed,
        "role": normalized,
        "capability": capability,
        "resource": resource,
        "detail": detail,
        "allowed_roles": sorted(allowed_roles, key=lambda item: ROLE_ORDER.index(item) if item in ROLE_ORDER else 99),
        "reason": "Role is allowed for this capability."
        if allowed
        else (
            "Unknown role."
            if not known_role
            else f"{ROLE_FORBIDDEN_REASONS.get(normalized, 'Role is not allowed for this capability')} Required capability: {capability}."
        ),
        "uses_seed_data": False,
        "loads_bigquery_per_tick": False,
        "llm_control_authority": False,
    }


def capability_for_mcp_tool(tool_name: str) -> str:
    tool = str(tool_name or "").strip()
    if tool == "get_role_access_contracts":
        return "read_role_contracts"
    if tool in {"get_training_status", "get_bigquery_training_status", "get_park_understanding_score"}:
        return "read_ml_training"
    return "read_ops_evidence"


def role_access_contracts(role: str | None = None) -> dict[str, Any]:
    roles = [
        _role(
            "customer",
            "Customer / Guest",
            "guest_assistance",
            ["park guest", "family group", "accessibility requester"],
            [
                "guest-facing guidance",
                "route and venue status",
                "safety notices",
                "help request receipt",
            ],
            [
                "ask for help",
                "view reroute guidance",
                "submit guest note",
                "acknowledge guest message",
            ],
            [
                "worker staffing details",
                "internal policy gate evidence",
                "model reward or training metrics",
                "BigQuery readiness or warehouse identity",
            ],
            [
                "dispatch worker",
                "approve action",
                "set reward or label",
                "promote or roll back model",
            ],
            ["public notice", "guest help receipt", "route confidence"],
            "Simple guest help and status. No internal control or model language.",
            "The LLM may explain guest-safe guidance only from approved public evidence.",
        ),
        _role(
            "onsite_worker",
            "Onsite Worker",
            "task_execution",
            ["ride operator", "food lead", "custodial lead", "guest services"],
            [
                "assigned task",
                "target zone",
                "priority",
                "policy constraints",
                "acknowledgement state",
                "staff training scenario",
            ],
            [
                "acknowledge task",
                "mark blocked",
                "mark done",
                "submit field observation",
                "practice guest-service roleplay",
            ],
            [
                "model promotion gate internals",
                "raw BigQuery tables",
                "other teams' private notes unless assigned",
            ],
            [
                "override policy gate",
                "query BigQuery",
                "change reward or labels",
                "promote or roll back model",
            ],
            ["task receipt", "field observation", "delivery acknowledgement", "staff training transcript"],
            "Operational task and training surface with tight action verbs, receipt states, and simulated roleplay only.",
            "The LLM may summarize why a task exists or play a training guest, but cannot create or approve live work.",
        ),
        _role(
            "ops_team",
            "Ops Team",
            "command_center",
            ["duty manager", "park ops", "guest recovery lead"],
            [
                "live park state",
                "active incidents",
                "candidate actions",
                "policy gate status",
                "action log",
                "outcome ledger",
                "memory retrieval summary",
            ],
            [
                "review action",
                "hold for human review",
                "acknowledge dispatch receipt",
                "request offline evidence refresh",
                "review staff training analytics",
            ],
            [
                "raw BigQuery table rows from chat",
                "private guest identifiers",
                "unscoped worker history",
            ],
            [
                "bypass policy gate",
                "set reward or labels from chat",
                "promote model from chat",
                "load BigQuery per tick",
            ],
            ["policy receipt", "action trace", "outcome ledger", "uncertainty list", "staff training score summary"],
            "Primary decision-review surface: readable evidence, explicit uncertainty, no hidden control.",
            "The LLM is an evidence assistant for status, why, uncertainty, and next checks.",
        ),
        _role(
            "ml_ops_admin",
            "ML / Ops Admin",
            "learning_governance",
            ["ML engineer", "platform owner", "safety reviewer"],
            [
                "training status",
                "fitness curve",
                "promotion blockers",
                "rollback ledger",
                "BigQuery governed summary",
                "Park Understanding Score",
            ],
            [
                "start offline training job",
                "inspect promotion readiness",
                "review rollback evidence",
                "export observed outcome rows",
            ],
            [
                "customer private identifiers",
                "raw BigQuery tables through chat",
                "live equipment control panel",
            ],
            [
                "promote deteriorating slice",
                "change reward or label through LLM",
                "run arbitrary SQL from chat",
                "dispatch live action",
            ],
            ["training receipt", "BQML readiness", "promotion gate", "rollback ledger"],
            "Learning-governance surface for offline training and release evidence.",
            "The LLM may audit learning evidence; promotion, reward, labels, rollback, and SQL stay governed outside chat.",
        ),
    ]
    if role:
        wanted = normalize_role(role, default="")
        roles = [item for item in roles if item["id"] == wanted]

    return {
        "status": "ready" if roles else "not_found",
        "mode": "role_access_contracts",
        "principle": "Rigid authority boundaries with natural role-specific experiences.",
        "roles": roles,
        "role_count": len(roles),
        "global_boundaries": [
            "No role can bypass policy gates.",
            "Chat/LLM cannot dispatch, set rewards, write labels, promote models, roll back policies, or run arbitrary BigQuery SQL.",
            "BigQuery is batch/offline evidence; it is not loaded every heartbeat tick.",
            "Guest and worker surfaces receive scoped summaries, not internal model or warehouse details.",
        ],
        "route_matrix": {
            "/customer-emergency": "customer",
            "/human": "onsite_worker",
            "/staff-training": "onsite_worker",
            "/": "ops_team",
            "/monitor": "ops_team",
            "/executive": "ml_ops_admin",
            "/labs": "ml_ops_admin",
        },
        "data_products": [
            "live_state",
            "policy_receipt",
            "dispatch_receipt",
            "outcome_ledger",
            "memory_summary",
            "training_summary",
            "bigquery_governed_summary",
        ],
        "uses_seed_data": False,
        "loads_bigquery_per_tick": False,
        "llm_control_authority": False,
    }
