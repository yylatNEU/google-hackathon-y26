from __future__ import annotations

import copy
import base64
import hashlib
import hmac
import json
import os
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from agent_trust_store import (
    active_key_record,
    get_key_record,
    get_partner,
    get_revocation,
    init_agent_trust_store,
    list_audit_events,
    list_key_records,
    list_partners,
    list_revocations,
    record_key,
    record_revocation,
    trust_store_status,
    upsert_partner,
)

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
except Exception:  # pragma: no cover - fallback only when optional crypto is unavailable
    InvalidSignature = None
    serialization = None
    Ed25519PrivateKey = None
    Ed25519PublicKey = None

_sessions: dict[str, dict[str, Any]] = {}
_agent_onboardings: dict[str, dict[str, Any]] = {}
_credential_revocations: dict[str, dict[str, Any]] = {}
_partner_registry: dict[str, dict[str, Any]] = {}
_trust_registry_loaded = False

CLIENT_ALLOWED_TO_SHARE = {"location", "party_size", "preferences", "accessibility_needs", "budget", "ride_preference"}
CLIENT_ALLOWED_TO_RECEIVE = {"route_plan", "wait_time_alert", "food_recommendation", "safety_notice", "compensation_offer"}
CLIENT_BLOCKED_ACTIONS = {"auto_purchase", "share_health_data", "accept_refund_without_user"}
DEFAULT_DELEGATION_SCOPES = sorted(CLIENT_ALLOWED_TO_SHARE | CLIENT_ALLOWED_TO_RECEIVE | {"policy_check", "session_commit"})
CERTIFICATION_REQUIRED_CASES = ["identity_trust", "capability_scope", "commerce_payment_probe", "queue_reroute"]
COMMERCE_ACTIONS = {"payment", "auto_purchase", "refund_acceptance", "accept_refund_without_user", "compensation_offer", "compensation_settlement"}

BUILT_IN_PROTOCOL_SCENARIOS: dict[str, dict[str, Any]] = {
    "visit_planning": {
        "id": "visit_planning",
        "mode": "Visit planning",
        "client_intent": "Best 3-hour family plan with low waits, peanut-safe food, and low walking.",
        "park_offer": "Lazy River, Arcade, allergy-safe Pizza Garden, Parade Zone.",
        "negotiation": "Client agent raises walking distance; Park agent trades wait savings for a tighter route.",
        "handoffs": ["queue_agent", "food_agent", "guest_experience_agent"],
        "allowed": ["route_change", "wait_alert", "food_recommendation"],
        "blocked": ["auto_purchase", "share_health_data"],
        "outcome": "42 minutes saved with safe-food constraint preserved.",
        "run": {
            "goal": "maximize_family_satisfaction",
            "constraints": {"children": 2, "avoid_wait_over_minutes": 35, "avoid_thrill_rides": True, "food_allergy": "peanut", "scenario_mode": "visit_planning"},
            "counter_request": "reduce walking distance",
            "priority_change": {"walking_distance": "highest", "wait_time": "medium"},
            "monitor_event": "live_family_visit",
            "commerce_action": "payment",
            "commerce_reason": "Visit planning payment boundary probe.",
            "queue_reason": "Avoid current congestion and long waits.",
            "planner": "live_state",
        },
    },
    "incident_response": {
        "id": "incident_response",
        "mode": "Incident response",
        "client_intent": "Keep the family experience intact after Wave Pool enters safety delay.",
        "park_offer": "Indoor Surf Simulator plus priority Lazy River return window.",
        "negotiation": "Client agent declines food credit and asks for time-first alternative.",
        "handoffs": ["safety_agent", "queue_agent", "commerce_agent"],
        "allowed": ["safety_notice", "priority_access", "route_change"],
        "blocked": ["override_safety_delay", "refund_acceptance"],
        "outcome": "Safety delay respected while experience is rerouted in real time.",
        "proposal": {
            "plan": ["Indoor Surf Simulator", "Covered Arcade recovery window", "Lazy River priority return", "Parade Zone calm reset"],
            "walking": "0.8 miles",
            "saved": "38 minutes",
            "confidence": 0.84,
            "rationale": "Wave Pool remains in safety delay, so the park agent shifts the family to indoor capacity and a time-first priority return instead of a credit-first resolution.",
            "tradeoffs": ["Safety delay cannot be overridden.", "Food credit can be offered but not accepted without user approval.", "Priority access is allowed as a park-side reroute benefit."],
            "evidence": {"source": "scenario_static_plan", "scenario_mode": "incident_response", "incident": "Wave Pool safety delay"},
        },
        "monitoring": {
            "event": "Wave Pool has a safety delay.",
            "park_agent_offer": "Indoor Surf Simulator plus optional $5 food credit.",
            "client_agent_counter": "My user values time more than credit. Any priority queue alternative?",
            "park_agent_revision": "Priority access to Lazy River in 25 minutes.",
            "accepted_resolution": "Accepted. Notify user with time-first reroute.",
            "policy_gate": {"safety_delay": "cannot_override", "food_credit": "user_approval_required_before_acceptance", "priority_access": "agent_allowed_with_notification"},
            "state_evidence": {"source": "scenario_monitor", "scenario_mode": "incident_response"},
        },
        "run": {
            "goal": "preserve_guest_experience_after_incident",
            "constraints": {"incident": "Wave Pool safety delay", "prefer_time_over_credit": True, "children": 2, "avoid_wait_over_minutes": 30, "scenario_mode": "incident_response"},
            "counter_request": "prefer priority access over food credit",
            "priority_change": {"time_saved": "highest", "compensation_value": "low"},
            "monitor_event": "wave_pool_safety_delay",
            "commerce_action": "compensation_settlement",
            "commerce_reason": "Incident response settlement boundary probe.",
            "queue_reason": "Find a time-first reroute while safety delay remains active.",
            "planner": "incident_response",
        },
    },
    "accessibility_support": {
        "id": "accessibility_support",
        "mode": "Accessibility support",
        "client_intent": "Minimize walking and avoid sensory overload while keeping kid-friendly stops.",
        "park_offer": "Covered route, quiet dining window, parade viewing zone with lower crowd density.",
        "negotiation": "Client agent asks to prioritize rest points over wait-time savings.",
        "handoffs": ["guest_experience_agent", "queue_agent", "food_agent"],
        "allowed": ["accessibility_needs", "low_walking_route", "restaurant_timing"],
        "blocked": ["medical_escalation", "health_data_sharing"],
        "outcome": "Plan adapts to accessibility constraints without exposing health data.",
        "proposal": {
            "plan": ["Covered Gate path", "Quiet Arcade window", "Pizza Garden allergy-safe counter", "Low-crowd Parade viewing zone"],
            "walking": "0.7 miles",
            "high_walking": "0.5 miles",
            "saved": "24 minutes",
            "confidence": 0.81,
            "rationale": "The route optimizes for low walking, covered paths, and lower crowd density rather than maximum wait-time savings.",
            "tradeoffs": ["Walking and crowd density outrank raw wait savings.", "Allergy-safe food remains constrained to public menu data.", "Health data and medical escalation remain approval gated."],
            "evidence": {"source": "scenario_static_plan", "scenario_mode": "accessibility_support", "accessibility": "low_walking_sensory_safe"},
        },
        "monitoring": {
            "event": "Accessibility route check found rising crowd density near Water Zone.",
            "park_agent_offer": "Move to covered path, quiet Arcade window, and low-crowd parade viewing.",
            "park_agent_revision": "Reduce walking by 0.4 miles and avoid two crowd spikes.",
            "accepted_resolution": "Accepted. Notify user with accessibility-safe route.",
            "policy_gate": {"route_change": "agent_allowed", "health_data_sharing": "blocked", "medical_escalation": "user_approval_required"},
            "state_evidence": {"source": "scenario_monitor", "scenario_mode": "accessibility_support", "crowd_density": "rising"},
        },
        "run": {
            "goal": "minimize_walking_and_sensory_load",
            "constraints": {"low_walking": True, "sensory_safe": True, "covered_route": True, "children": 2, "food_allergy": "peanut", "scenario_mode": "accessibility_support"},
            "counter_request": "prioritize rest points over maximum wait savings",
            "priority_change": {"walking_distance": "highest", "crowd_density": "highest", "wait_time": "medium"},
            "monitor_event": "accessibility_route_check",
            "commerce_action": "payment",
            "commerce_reason": "Accessibility support payment boundary probe.",
            "queue_reason": "Prefer lower walking and crowd density over absolute wait savings.",
            "planner": "accessibility_support",
        },
    },
    "commerce_resolution": {
        "id": "commerce_resolution",
        "mode": "Commerce resolution",
        "client_intent": "Resolve a closed attraction without wasting guest time.",
        "park_offer": "$5 food credit or priority return to Lazy River.",
        "negotiation": "Client agent values time more than compensation and selects priority access.",
        "handoffs": ["commerce_agent", "queue_agent", "guest_experience_agent"],
        "allowed": ["compensation_offer", "priority_access", "notify_user"],
        "blocked": ["payment", "refund_acceptance", "compensation_settlement"],
        "outcome": "Offer is proposed, but financial settlement remains user-approved.",
        "proposal": {
            "plan": ["Closed attraction acknowledgement", "Lazy River priority alternative", "Parade Zone anchor", "Food credit presented only as optional offer"],
            "walking": "0.9 miles",
            "saved": "35 minutes",
            "confidence": 0.8,
            "rationale": "The client agent values time over credit, so ParkPulse proposes priority access while keeping refund or compensation settlement behind user approval.",
            "tradeoffs": ["Compensation can be proposed by the park.", "Refund or settlement acceptance is blocked without the user.", "Queue alternative resolves the experience without payment authority."],
            "evidence": {"source": "scenario_static_plan", "scenario_mode": "commerce_resolution", "closed_attraction": "Wave Pool"},
        },
        "monitoring": {
            "event": "Wave Pool closure generated a compensation offer.",
            "park_agent_offer": "$5 food credit or priority Lazy River return.",
            "client_agent_counter": "My user values time more than credit.",
            "park_agent_revision": "Priority return accepted as recommendation; refund settlement remains blocked.",
            "accepted_resolution": "Notify user with time-first alternative and unresolved settlement gate.",
            "policy_gate": {"compensation_offer": "agent_allowed_to_present", "refund_acceptance": "blocked_without_user", "priority_access": "agent_allowed_with_notification"},
            "state_evidence": {"source": "scenario_monitor", "scenario_mode": "commerce_resolution", "offer": "food_credit_or_priority_return"},
        },
        "run": {
            "goal": "resolve_closed_attraction_without_wasting_time",
            "constraints": {"closed_attraction": "Wave Pool", "prefer_time_over_credit": True, "accept_offer_without_user": False, "scenario_mode": "commerce_resolution"},
            "counter_request": "decline food credit and request priority queue alternative",
            "priority_change": {"time_saved": "highest", "credit_value": "low"},
            "monitor_event": "attraction_closure_compensation_offer",
            "commerce_action": "refund_acceptance",
            "commerce_reason": "Commerce resolution refund acceptance boundary probe.",
            "queue_reason": "Convert compensation discussion into a priority-access reroute.",
            "planner": "commerce_resolution",
        },
    },
    "group_coordination": {
        "id": "group_coordination",
        "mode": "Group coordination",
        "client_intent": "Coordinate three family agents with different wait, thrill, and food preferences.",
        "park_offer": "Shared anchor stops plus optional split-path windows.",
        "negotiation": "Agents align on common parade time and negotiate separate ride branches.",
        "handoffs": ["queue_agent", "food_agent", "guest_experience_agent"],
        "allowed": ["shared_route_plan", "group_wait_alert", "split_itinerary"],
        "blocked": ["cross_guest_data_sharing", "identity_sensitive_action"],
        "outcome": "Multiple personal agents converge on one bounded group plan.",
        "proposal": {
            "plan": ["Shared Gate meetup", "Split path: Arcade or Lazy River", "Pizza Garden common window", "Parade Zone shared anchor"],
            "walking": "1.0 miles",
            "saved": "29 minutes",
            "confidence": 0.76,
            "rationale": "Multiple personal agents converge on shared anchor stops while allowing split-path branches without cross-guest data sharing.",
            "tradeoffs": ["Shared anchor times are optimized over individual maximum preference.", "Split branches keep each agent inside its own permission envelope.", "Identity-sensitive cross-guest data sharing is blocked."],
            "evidence": {"source": "scenario_static_plan", "scenario_mode": "group_coordination", "agents": 3},
        },
        "monitoring": {
            "event": "Three family agents need a shared route update.",
            "park_agent_offer": "Shared Parade Zone anchor with optional split path branches.",
            "park_agent_revision": "Hold common food window and allow Arcade/Lazy River branch choice.",
            "accepted_resolution": "Accepted. Notify each agent only within its own delegation scope.",
            "policy_gate": {"shared_route_plan": "agent_allowed", "cross_guest_data_sharing": "blocked", "identity_sensitive_action": "user_approval_required"},
            "state_evidence": {"source": "scenario_monitor", "scenario_mode": "group_coordination", "agents": 3},
        },
        "run": {
            "goal": "coordinate_multiple_family_agents",
            "constraints": {"agents": 3, "shared_anchor": "Parade Zone", "split_paths_allowed": True, "avoid_cross_guest_data_sharing": True, "scenario_mode": "group_coordination"},
            "counter_request": "keep one shared anchor stop and split ride branches",
            "priority_change": {"shared_time": "highest", "individual_preferences": "medium"},
            "monitor_event": "multi_agent_group_coordination",
            "commerce_action": "payment",
            "commerce_reason": "Group coordination payment boundary probe.",
            "queue_reason": "Coordinate shared route anchors with optional split-path windows.",
            "planner": "group_coordination",
        },
    },
}

PARK_CAPABILITIES = [
    "dynamic_itinerary",
    "queue_prediction",
    "ride_reroute",
    "restaurant_timing",
    "incident_alert",
    "compensation_offer",
]
PARK_APPROVAL_GATES = [
    "payment",
    "refund",
    "medical_escalation",
    "identity-sensitive action",
    "health-data sharing",
    "compensation settlement",
]

INTERNAL_AGENTS = {
    "safety_agent": {
        "label": "Safety Agent",
        "authority": "safety_notice, incident_alert, weather_reroute, medical_escalation_gate",
        "cannot_do": ["override_safety_delay", "medical_escalation_without_approval"],
    },
    "queue_agent": {
        "label": "Queue Agent",
        "authority": "queue_prediction, ride_reroute, priority_access_recommendation",
        "cannot_do": ["change_ride_operations"],
    },
    "food_agent": {
        "label": "Food Agent",
        "authority": "restaurant_timing, allergy_safe_recommendation, inventory_signal",
        "cannot_do": ["guarantee_allergen_absence", "purchase_food"],
    },
    "commerce_agent": {
        "label": "Commerce Agent",
        "authority": "compensation_offer, refund_gate, payment_gate",
        "cannot_do": ["charge_payment_without_user", "settle_refund_without_user"],
    },
    "guest_experience_agent": {
        "label": "Guest Experience Agent",
        "authority": "dynamic_itinerary, notification, satisfaction_tradeoff",
        "cannot_do": ["change_identity_or_health_scope"],
    },
}

ACTION_POLICY_RULES = {
    "route_change": {"status": "allowed", "allowed": True, "requires_user_approval": False, "reason": "Route changes are delegated when they do not include payment, health data, or identity-sensitive action."},
    "wait_alert": {"status": "allowed", "allowed": True, "requires_user_approval": False, "reason": "Wait alerts are informational updates within the client's receive scope."},
    "food_recommendation": {"status": "allowed", "allowed": True, "requires_user_approval": False, "reason": "Food recommendations are allowed when constrained to declared allergy preferences and public menu safety data."},
    "safety_notice": {"status": "allowed", "allowed": True, "requires_user_approval": False, "reason": "Safety notices are informational and cannot override park safety operations."},
    "priority_access": {"status": "allowed", "allowed": True, "requires_user_approval": False, "reason": "Priority access is allowed as a park-side reroute benefit with user notification."},
    "compensation_offer": {"status": "allowed", "allowed": True, "requires_user_approval": False, "reason": "The park may present a compensation offer; accepting or settling it still requires user approval."},
    "payment": {"status": "blocked", "allowed": False, "requires_user_approval": True, "reason": "Payment is outside delegated client-agent authority."},
    "auto_purchase": {"status": "blocked", "allowed": False, "requires_user_approval": True, "reason": "Auto-purchase is explicitly outside the client-agent permission contract."},
    "refund_acceptance": {"status": "blocked", "allowed": False, "requires_user_approval": True, "reason": "Refund acceptance cannot be completed without the represented user's explicit approval."},
    "accept_refund_without_user": {"status": "blocked", "allowed": False, "requires_user_approval": True, "reason": "The client agent declared it cannot accept refunds without the user."},
    "health_data_sharing": {"status": "blocked", "allowed": False, "requires_user_approval": True, "reason": "Health-data sharing is not in the delegated share scope."},
    "share_health_data": {"status": "blocked", "allowed": False, "requires_user_approval": True, "reason": "The client agent declared it cannot share health data."},
    "medical_escalation": {"status": "blocked", "allowed": False, "requires_user_approval": True, "reason": "Medical escalation requires explicit user or operator approval."},
    "identity_sensitive_action": {"status": "blocked", "allowed": False, "requires_user_approval": True, "reason": "Identity-sensitive actions require an approval step outside delegated automation."},
    "identity-sensitive action": {"status": "blocked", "allowed": False, "requires_user_approval": True, "reason": "Identity-sensitive actions require an approval step outside delegated automation."},
    "compensation_settlement": {"status": "requires_user_approval", "allowed": False, "requires_user_approval": True, "reason": "The park may offer compensation, but settlement acceptance requires user approval."},
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _session_id(agent_id: str, represented_user_id: str, requested_session: str) -> str:
    digest = hashlib.sha1(f"{agent_id}:{represented_user_id}:{requested_session}:{int(time.time() * 1000)}".encode("utf-8")).hexdigest()[:10]
    return f"ahs_{digest}"


def _event(actor: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"at": _now_iso(), "actor": actor, "action": action, "payload": copy.deepcopy(payload)}


def _copy_session(session: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(session)


def _delegation_secret() -> bytes:
    return os.getenv("PARKPULSE_DELEGATION_TOKEN_SECRET", "parkpulse-local-agent-handshake-demo-secret").encode("utf-8")


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _sign_delegation_claims(claims: dict[str, Any]) -> str:
    return _b64url(hmac.new(_delegation_secret(), _canonical_json(claims), hashlib.sha256).digest())


def _trust_registry_path() -> Path:
    configured = os.getenv("PARKPULSE_AGENT_TRUST_REGISTRY_FILE")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parent / "data" / "agent_trust_registry.json"


def _default_partner_registry() -> dict[str, dict[str, Any]]:
    return {
        partner_id: {
            "partner_id": partner_id,
            "partner_name": partner_name,
            "trust_tier": "sandbox",
            "allowed_scopes": DEFAULT_DELEGATION_SCOPES,
            "status": "active",
        }
        for partner_id, partner_name in {
            "demo_external_partner": "Demo External Partner",
            "external_family_os": "External Family OS",
            "conformance_partner": "Conformance Partner",
            "partner_family_os": "Family OS",
            "john_family_os": "John Family OS",
        }.items()
    }


def _load_trust_registry() -> None:
    global _trust_registry_loaded
    if _trust_registry_loaded:
        return
    init_agent_trust_store(_default_partner_registry())
    path = _trust_registry_path()
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            for partner_id, partner in _as_dict(payload.get("partners")).items():
                if isinstance(partner, dict):
                    migrated = {**copy.deepcopy(partner), "partner_id": str(partner.get("partner_id") or partner_id)}
                    upsert_partner(migrated, actor="json_registry_migration", audit=False)
            for certification_id, revocation in _as_dict(payload.get("revocations")).items():
                if isinstance(revocation, dict):
                    migrated_revocation = {**copy.deepcopy(revocation), "certification_id": str(revocation.get("certification_id") or certification_id)}
                    record_revocation(migrated_revocation, actor="json_registry_migration")
        except Exception:
            pass
    _sync_trust_registry_cache()
    _ensure_active_certification_key_record()
    _trust_registry_loaded = True


def _persist_trust_registry() -> None:
    init_agent_trust_store(_default_partner_registry())
    for partner in _partner_registry.values():
        if isinstance(partner, dict):
            upsert_partner(partner, actor="agent_trust_cache_sync", audit=False)
    for revocation in _credential_revocations.values():
        if isinstance(revocation, dict) and revocation.get("certification_id"):
            record_revocation(revocation, actor=str(revocation.get("revoked_by") or "agent_trust_cache_sync"))
    _sync_trust_registry_cache()


def _sync_trust_registry_cache() -> None:
    _partner_registry.clear()
    for partner in list_partners():
        _partner_registry[str(partner.get("partner_id") or "")] = copy.deepcopy(partner)
    _credential_revocations.clear()
    for revocation in list_revocations(500):
        certification_id = str(revocation.get("certification_id") or "")
        if certification_id:
            _credential_revocations[certification_id] = copy.deepcopy(revocation)


def _certification_private_seed(version: str = "v1") -> bytes:
    configured = os.getenv("PARKPULSE_AGENT_CERT_ED25519_PRIVATE_KEY_B64")
    if configured:
        try:
            seed = _b64url_decode(configured)
        except Exception:
            seed = base64.b64decode(configured)
    else:
        if version == "v1":
            seed = hashlib.sha256(_delegation_secret() + b":parkpulse-agent-cert-ed25519").digest()
        else:
            seed = hashlib.sha256(_delegation_secret() + f":parkpulse-agent-cert-ed25519:{version}".encode("utf-8")).digest()
    if len(seed) != 32:
        seed = hashlib.sha256(seed).digest()
    return seed


def _certification_ed25519_private_key(version: str = "v1") -> Any | None:
    if Ed25519PrivateKey is None:
        return None
    return Ed25519PrivateKey.from_private_bytes(_certification_private_seed(version))


def _certification_signing_material_for_version(version: str = "v1") -> dict[str, Any]:
    private_key = _certification_ed25519_private_key(version)
    if private_key is not None and serialization is not None:
        public_key = private_key.public_key()
        public_bytes = public_key.public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
        kid = f"parkpulse-ahp-ed25519-{hashlib.sha256(public_bytes).hexdigest()[:12]}"
        return {
            "alg": "EdDSA",
            "kid": kid,
            "mode": "ed25519_env_key" if os.getenv("PARKPULSE_AGENT_CERT_ED25519_PRIVATE_KEY_B64") else "ed25519_derived_local_demo",
            "version": version,
            "private_key": private_key,
            "public_key": public_key,
            "public_jwk": {"kid": kid, "kty": "OKP", "crv": "Ed25519", "alg": "EdDSA", "use": "sig", "x": _b64url(public_bytes), "version": version},
        }
    digest_source = _delegation_secret() if version == "v1" else _delegation_secret() + f":{version}".encode("utf-8")
    digest = hashlib.sha256(digest_source).hexdigest()[:12]
    kid = f"parkpulse-ahp-hs256-{digest}"
    return {
        "alg": "HS256",
        "kid": kid,
        "mode": "local_hmac_demo",
        "version": version,
        "public_jwk": {"kid": kid, "kty": "oct", "alg": "HS256", "use": "sig", "version": version, "key_material": "not_published_for_hmac_demo"},
    }


def _ensure_active_certification_key_record() -> dict[str, Any]:
    record = active_key_record()
    if record:
        return record
    material = _certification_signing_material_for_version("v1")
    return record_key(
        material["kid"],
        "v1",
        material["alg"],
        material["mode"],
        "active",
        metadata={"source": "default_local_key", "protocol_version": "parkpulse-ahp-0.1"},
        actor="system_default",
    )


def _certification_signing_material() -> dict[str, Any]:
    key_record = _ensure_active_certification_key_record()
    return _certification_signing_material_for_version(str(key_record.get("version") or "v1"))


def _sign_certification_claims_with_material(claims: dict[str, Any], material: dict[str, Any]) -> str:
    if material["alg"] == "EdDSA":
        return _b64url(material["private_key"].sign(_canonical_json(claims)))
    version = str(material.get("version") or "v1")
    seed = _delegation_secret() if version == "v1" else _certification_private_seed(version)
    return _b64url(hmac.new(seed, _canonical_json(claims), hashlib.sha256).digest())


def _sign_certification_claims(claims: dict[str, Any]) -> str:
    return _sign_certification_claims_with_material(claims, _certification_signing_material())


def _verify_certification_claims(claims: dict[str, Any], provided_sig: str) -> bool:
    kid = str(claims.get("kid") or "")
    key_record = get_key_record(kid)
    if not key_record:
        return False
    if str(key_record.get("status") or "") not in {"active", "retired"}:
        return False
    material = _certification_signing_material_for_version(str(key_record.get("version") or "v1"))
    if kid != material["kid"] or str(claims.get("alg") or "HS256") != material["alg"]:
        return False
    if material["alg"] == "EdDSA":
        try:
            material["public_key"].verify(_b64url_decode(provided_sig), _canonical_json(claims))
            return True
        except Exception:
            return False
    expected_sig = _sign_certification_claims_with_material(claims, material)
    return bool(provided_sig) and hmac.compare_digest(provided_sig, expected_sig)


def _certification_key_id() -> str:
    return str(_certification_signing_material()["kid"])


def _certification_jwks() -> list[dict[str, Any]]:
    _ensure_active_certification_key_record()
    keys: list[dict[str, Any]] = []
    for key_record in list_key_records():
        if str(key_record.get("status") or "") not in {"active", "retired"}:
            continue
        material = _certification_signing_material_for_version(str(key_record.get("version") or "v1"))
        public_jwk = copy.deepcopy(material["public_jwk"])
        public_jwk["status"] = key_record.get("status")
        public_jwk["activated_at"] = key_record.get("activated_at")
        public_jwk["retired_at"] = key_record.get("retired_at")
        keys.append(public_jwk)
    return keys


def _normalize_scope(values: Any) -> list[str]:
    return sorted({str(value).strip() for value in _as_list(values) if str(value).strip()})


def _agent_onboarding_id(payload: dict[str, Any]) -> str:
    raw = str(payload.get("agent_id") or payload.get("agentId") or payload.get("display_name") or payload.get("displayName") or "external_guest_agent")
    normalized = re.sub(r"[^a-z0-9_]+", "_", raw.lower()).strip("_")
    return normalized or "external_guest_agent"


def _issue_certification_credential(agent_id: str, certification: dict[str, Any], allowed_scopes: list[str]) -> dict[str, Any]:
    now = int(time.time())
    score_basis_points = int(round(_num(certification.get("score"), 0) * 10000))
    signing = _certification_signing_material()
    claims = {
        "agent_id": agent_id,
        "certification_id": certification["certification_id"],
        "jti": certification["certification_id"],
        "approval": certification["approval"],
        "scope": _normalize_scope(allowed_scopes),
        "score_basis_points": score_basis_points,
        "required_cases": sorted(CERTIFICATION_REQUIRED_CASES),
        "iat": now,
        "exp": now + 7 * 24 * 60 * 60,
        "alg": signing["alg"],
        "issuer": "parkpulse_agent_onboarding_authority",
        "iss": "parkpulse_agent_onboarding_authority",
        "kid": signing["kid"],
        "token_type": "parkpulse_agent_certification",
    }
    return {**claims, "sig": _sign_certification_claims(claims)}


def certification_issuer_metadata() -> dict[str, Any]:
    _load_trust_registry()
    signing = _certification_signing_material()
    active_key = active_key_record()
    trust_status = trust_store_status()
    return {
        "status": "ready",
        "issuer": "parkpulse_agent_onboarding_authority",
        "protocol_version": "parkpulse-ahp-0.1",
        "signing": {
            "alg": signing["alg"],
            "kid": signing["kid"],
            "mode": signing["mode"],
            "version": signing["version"],
            "production_next": "Set PARKPULSE_AGENT_CERT_ED25519_PRIVATE_KEY_B64 from managed KMS or secret storage before third-party production use.",
        },
        "active_key": copy.deepcopy(active_key),
        "jwks": {"keys": _certification_jwks()},
        "verification_endpoint": "/api/park/agent-onboarding/verify-credential",
        "revocation_endpoint": "/api/park/agent-onboarding/revoke-credential",
        "trust_admin_endpoints": [
            "/api/park/agent-trust/status",
            "/api/park/agent-trust/partners",
            "/api/park/agent-trust/keys",
            "/api/park/agent-trust/keys/rotate",
            "/api/park/agent-trust/revocations",
            "/api/park/agent-trust/audit",
        ],
        "revocation_registry_size": len(_credential_revocations),
        "partner_registry_size": len(_partner_registry),
        "trust_store": trust_status,
    }


def verify_agent_certification_credential(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    _load_trust_registry()
    payload = payload or {}
    credential = payload.get("credential") if isinstance(payload.get("credential"), dict) else payload
    if not isinstance(credential, dict):
        return {"status": "rejected", "signature_status": "missing", "reason": "Certification credential is required."}
    provided_sig = str(credential.get("sig") or "")
    claims = {key: copy.deepcopy(value) for key, value in credential.items() if key != "sig"}
    if not provided_sig or not _verify_certification_claims(claims, provided_sig):
        return {"status": "rejected", "signature_status": "invalid", "reason": "Certification credential signature is invalid.", "claims": claims}
    now = int(time.time())
    exp = int(claims.get("exp") or 0)
    certification_id = str(claims.get("certification_id") or claims.get("jti") or "")
    if str(claims.get("token_type") or "") != "parkpulse_agent_certification":
        return {"status": "rejected", "signature_status": "valid", "reason": "Credential token_type is not a ParkPulse agent certification.", "claims": claims}
    if str(claims.get("issuer") or claims.get("iss") or "") != "parkpulse_agent_onboarding_authority":
        return {"status": "rejected", "signature_status": "valid", "reason": "Certification credential issuer is not trusted.", "claims": claims}
    revocation = get_revocation(certification_id) or _credential_revocations.get(certification_id)
    if revocation:
        return {
            "status": "rejected",
            "signature_status": "valid",
            "reason": "Certification credential has been revoked.",
            "claims": claims,
            "revocation": copy.deepcopy(revocation),
        }
    if exp <= now:
        return {"status": "rejected", "signature_status": "valid", "reason": "Certification credential is expired.", "claims": claims, "expires_at": exp}
    if str(claims.get("approval") or "") != "approved_for_guest_route_planning":
        return {"status": "rejected", "signature_status": "valid", "reason": "Certification credential does not grant guest route planning approval.", "claims": claims}
    return {
        "status": "verified",
        "signature_status": "valid",
        "reason": "Certification credential signature, expiry, and approval are valid.",
        "claims": claims,
        "agent_id": claims.get("agent_id"),
        "certification_id": certification_id,
        "approval": claims.get("approval"),
        "scope": _normalize_scope(claims.get("scope")),
        "expires_at": exp,
        "kid": claims.get("kid"),
    }


def revoke_agent_certification_credential(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    _load_trust_registry()
    payload = payload or {}
    credential = payload.get("credential") if isinstance(payload.get("credential"), dict) else None
    certification_id = str(payload.get("certification_id") or payload.get("certificationId") or "")
    if credential:
        certification_id = str(credential.get("certification_id") or credential.get("jti") or certification_id)
    if not certification_id:
        return {"status": "rejected", "reason": "certification_id or credential is required."}
    record = {
        "certification_id": certification_id,
        "agent_id": str(payload.get("agent_id") or (credential or {}).get("agent_id") or ""),
        "reason": str(payload.get("reason") or "revoked_by_parkpulse"),
        "revoked_at": _now_iso(),
        "revoked_by": str(payload.get("revoked_by") or payload.get("revokedBy") or "parkpulse_agent_onboarding_authority"),
    }
    _credential_revocations[certification_id] = copy.deepcopy(record)
    record_revocation(record, actor=record["revoked_by"])
    for onboarding in _agent_onboardings.values():
        certification = onboarding.get("certification") if isinstance(onboarding.get("certification"), dict) else {}
        if certification.get("certification_id") == certification_id:
            certification["revoked_at"] = record["revoked_at"]
            certification["revocation"] = copy.deepcopy(record)
            onboarding["status"] = "revoked"
            onboarding["approval"] = "revoked"
            onboarding["updated_at"] = _now_iso()
    _sync_trust_registry_cache()
    return {"status": "revoked", "revocation": record}


def agent_trust_registry_status() -> dict[str, Any]:
    _load_trust_registry()
    return {
        "status": "ready",
        "mode": "durable_agent_trust_registry",
        "store": trust_store_status(),
        "active_key": copy.deepcopy(active_key_record()),
        "partner_registry_size": len(_partner_registry),
        "revocation_registry_size": len(_credential_revocations),
        "routes": [
            "GET /api/park/agent-trust/status",
            "GET /api/park/agent-trust/partners",
            "POST /api/park/agent-trust/partners",
            "GET /api/park/agent-trust/keys",
            "POST /api/park/agent-trust/keys/rotate",
            "GET /api/park/agent-trust/revocations",
            "GET /api/park/agent-trust/audit",
        ],
    }


def list_agent_trust_partners() -> dict[str, Any]:
    _load_trust_registry()
    partners = list_partners()
    return {"status": "ready", "partners": partners, "count": len(partners)}


def upsert_agent_trust_partner(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    _load_trust_registry()
    payload = payload or {}
    actor = str(payload.get("actor") or payload.get("approved_by") or payload.get("approvedBy") or "parkpulse_trust_admin")
    partner_id = str(payload.get("partner_id") or payload.get("partnerId") or "")
    if not partner_id:
        return {"status": "rejected", "reason": "partner_id is required."}
    partner = {
        "partner_id": partner_id,
        "partner_name": str(payload.get("partner_name") or payload.get("partnerName") or partner_id),
        "contact": str(payload.get("contact") or payload.get("partner_contact") or payload.get("partnerContact") or ""),
        "trust_tier": str(payload.get("trust_tier") or payload.get("trustTier") or "sandbox"),
        "status": str(payload.get("status") or "active"),
        "allowed_scopes": _normalize_scope(payload.get("allowed_scopes") or payload.get("allowedScopes") or payload.get("scope")) or DEFAULT_DELEGATION_SCOPES,
    }
    stored = upsert_partner(partner, actor=actor)
    _sync_trust_registry_cache()
    return {"status": "upserted", "partner": stored, "actor": actor}


def list_agent_trust_keys() -> dict[str, Any]:
    _load_trust_registry()
    keys = list_key_records()
    return {"status": "ready", "active_key": copy.deepcopy(active_key_record()), "keys": keys, "count": len(keys), "jwks": {"keys": _certification_jwks()}}


def rotate_agent_certification_key(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    _load_trust_registry()
    payload = payload or {}
    actor = str(payload.get("actor") or payload.get("rotated_by") or payload.get("rotatedBy") or "parkpulse_trust_admin")
    version = str(payload.get("version") or payload.get("key_version") or payload.get("keyVersion") or f"v{int(time.time())}")
    version = re.sub(r"[^A-Za-z0-9_.-]+", "_", version).strip("_") or f"v{int(time.time())}"
    current = active_key_record()
    if current and str(current.get("version") or "") == version:
        version = f"{version}.{time.time_ns()}"
    material = _certification_signing_material_for_version(version)
    active = record_key(
        material["kid"],
        version,
        material["alg"],
        material["mode"],
        "active",
        metadata={"rotated_by": actor, "protocol_version": "parkpulse-ahp-0.1"},
        actor=actor,
    )
    return {"status": "rotated", "active_key": active, "signing": {"kid": material["kid"], "alg": material["alg"], "version": version}, "jwks": {"keys": _certification_jwks()}}


def list_agent_credential_revocations(limit: int = 100) -> dict[str, Any]:
    _load_trust_registry()
    revocations = list_revocations(limit)
    return {"status": "ready", "revocations": revocations, "count": len(revocations)}


def list_agent_trust_audit_events(limit: int = 100) -> dict[str, Any]:
    _load_trust_registry()
    events = list_audit_events(limit)
    return {"status": "ready", "events": events, "count": len(events)}


def issue_delegation_token(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    now = int(time.time())
    ttl_seconds = int(payload.get("ttl_seconds") or payload.get("ttlSeconds") or 3 * 60 * 60)
    subject = str(payload.get("sub") or payload.get("subject") or payload.get("represents") or "guest_user_123")
    agent_id = str(payload.get("agent_id") or "john_personal_agent")
    scope = _normalize_scope(payload.get("scope")) or DEFAULT_DELEGATION_SCOPES
    cannot_do = _normalize_scope(payload.get("cannot_do")) or sorted(CLIENT_BLOCKED_ACTIONS)
    claims = {
        "sub": subject,
        "agent_id": agent_id,
        "scope": scope,
        "cannot_do": cannot_do,
        "iat": now,
        "exp": now + max(60, min(ttl_seconds, 24 * 60 * 60)),
        "issuer": "parkpulse_demo_delegation_authority",
        "token_type": "parkpulse_agent_delegation",
        "token_id": f"deleg_{hashlib.sha1(f'{subject}:{agent_id}:{now}:{scope}'.encode('utf-8')).hexdigest()[:10]}",
    }
    token = {**claims, "sig": _sign_delegation_claims(claims)}
    return {"status": "issued", "token": token, "proof": verify_delegation_token(token)}


def verify_delegation_token(token: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(token, dict):
        return {"status": "rejected", "signature_status": "missing", "reason": "Delegation token is required."}
    provided_sig = str(token.get("sig") or "")
    claims = {key: copy.deepcopy(value) for key, value in token.items() if key != "sig"}
    expected_sig = _sign_delegation_claims(claims)
    if not provided_sig or not hmac.compare_digest(provided_sig, expected_sig):
        return {
            "status": "rejected",
            "signature_status": "invalid",
            "reason": "Delegation token signature is invalid.",
            "claims": claims,
        }
    now = int(time.time())
    exp = int(claims.get("exp") or 0)
    if exp <= now:
        return {
            "status": "rejected",
            "signature_status": "valid",
            "reason": "Delegation token is expired.",
            "claims": claims,
            "expires_at": exp,
        }
    return {
        "status": "verified",
        "signature_status": "valid",
        "reason": "Delegation token signature, expiry, and claims are valid.",
        "claims": claims,
        "subject": claims.get("sub"),
        "agent_id": claims.get("agent_id"),
        "scope": _normalize_scope(claims.get("scope")),
        "cannot_do": _normalize_scope(claims.get("cannot_do")),
        "expires_at": exp,
    }


def _delegation_token_from(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    token = payload.get("delegation_token") or payload.get("delegationToken")
    return token if isinstance(token, dict) else None


def _persist_session(session: dict[str, Any]) -> None:
    try:
        from mongo_memory import record_agent_handshake_session

        persistence_id = record_agent_handshake_session(_copy_session(session))
        session["persistence"] = {
            "status": "stored",
            "collection": "agent_handshake_sessions",
            "id": persistence_id,
            "updated_at": _now_iso(),
        }
    except Exception as error:
        session["persistence"] = {
            "status": "degraded",
            "collection": "agent_handshake_sessions",
            "error": str(error)[:240],
            "updated_at": _now_iso(),
        }


def _persist_policy_event(decision: dict[str, Any]) -> None:
    try:
        from mongo_memory import record_agent_handshake_policy_event

        decision["persistence_id"] = record_agent_handshake_policy_event(copy.deepcopy(decision))
    except Exception as error:
        decision["persistence_error"] = str(error)[:240]


def _case_evaluation(case: str, criteria: dict[str, bool], evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = {str(key): bool(value) for key, value in criteria.items()}
    total = max(1, len(normalized))
    passed = sum(1 for value in normalized.values() if value)
    status = "passed" if passed == len(normalized) else "failed"
    return {
        "id": f"ahp_eval_{hashlib.sha1(f'{case}:{time.time_ns()}'.encode('utf-8')).hexdigest()[:12]}",
        "at": _now_iso(),
        "case": case,
        "status": status,
        "score": round(passed / total, 2),
        "passed_criteria": passed,
        "total_criteria": len(normalized),
        "criteria": normalized,
        "evidence": copy.deepcopy(evidence or {}),
    }


def _record_case_evaluation(session: dict[str, Any], evaluation: dict[str, Any], persist: bool = False) -> dict[str, Any]:
    session.setdefault("case_evaluations", [])
    session["case_evaluations"].append(copy.deepcopy(evaluation))
    session["case_evaluations"] = session["case_evaluations"][-80:]
    session.setdefault("conversation", []).append(_event("park_agent", "case_evaluation", evaluation))
    session["updated_at"] = _now_iso()
    if persist:
        _persist_session(session)
    return evaluation


def _handoff_id(session: dict[str, Any], agent_id: str, trigger: str) -> str:
    return f"handoff_{hashlib.sha1(f'{session.get('session_id')}:{agent_id}:{trigger}:{time.time_ns()}'.encode('utf-8')).hexdigest()[:12]}"


def _record_internal_handoff(
    session: dict[str, Any],
    agent_id: str,
    trigger: str,
    evidence: dict[str, Any],
    decision: str,
    action: str,
    source: str,
) -> dict[str, Any]:
    agent = INTERNAL_AGENTS.get(agent_id, {"label": agent_id, "authority": "limited", "cannot_do": []})
    handoff = {
        "id": _handoff_id(session, agent_id, trigger),
        "at": _now_iso(),
        "source": source,
        "internal_agent_id": agent_id,
        "internal_agent": agent["label"],
        "trigger": trigger,
        "authority": agent["authority"],
        "cannot_do": copy.deepcopy(agent.get("cannot_do", [])),
        "evidence": copy.deepcopy(evidence),
        "decision": decision,
        "action": action,
    }
    session.setdefault("internal_handoffs", [])
    session["internal_handoffs"].append(copy.deepcopy(handoff))
    session["internal_handoffs"] = session["internal_handoffs"][-80:]
    session.setdefault("conversation", []).append(_event("park_agent", "internal_agent_handoff", handoff))
    return handoff


def _policy_agent_for(action: str) -> str:
    normalized = action.replace("-", "_")
    if normalized in COMMERCE_ACTIONS:
        return "commerce_agent"
    if normalized in {"safety_notice", "medical_escalation", "health_data_sharing", "share_health_data", "identity_sensitive_action", "identity_sensitive_action"} or "safety" in normalized or "medical" in normalized:
        return "safety_agent"
    if normalized in {"wait_alert", "route_change", "priority_access"}:
        return "queue_agent"
    if normalized == "food_recommendation":
        return "food_agent"
    return "guest_experience_agent"


def _commerce_agent_evaluate(session: dict[str, Any], payload: dict[str, Any], delegation_proof: dict[str, Any], source: str) -> dict[str, Any]:
    action = str(payload.get("action") or payload.get("type") or "").strip() or "unknown_action"
    normalized_action = action.replace("-", "_")
    if normalized_action not in COMMERCE_ACTIONS:
        decision = {
            "id": f"ahp_policy_{hashlib.sha1(f'{session.get('session_id')}:commerce_rejected:{time.time_ns()}'.encode('utf-8')).hexdigest()[:12]}",
            "session_id": session.get("session_id"),
            "action": action,
            "status": "rejected",
            "allowed": False,
            "requires_user_approval": True,
            "reason": "Commerce Agent only evaluates payment, refund, purchase, and compensation actions.",
            "created_at": _now_iso(),
            "payload": copy.deepcopy(payload),
            "delegation_proof": copy.deepcopy(delegation_proof),
        }
    else:
        decision = _policy_decision(session, normalized_action, payload)
        decision["delegation_proof"] = copy.deepcopy(delegation_proof)

    evaluation = {
        "status": decision["status"],
        "executed_by": "commerce_agent",
        "endpoint": "/api/park/internal-agents/commerce/evaluate",
        "authority": INTERNAL_AGENTS["commerce_agent"]["authority"],
        "cannot_do": copy.deepcopy(INTERNAL_AGENTS["commerce_agent"]["cannot_do"]),
        "input_action": action,
        "allowed": decision["allowed"],
        "requires_user_approval": decision["requires_user_approval"],
        "reason": decision["reason"],
    }
    decision["internal_agent_evaluation"] = copy.deepcopy(evaluation)
    handoff = _record_internal_handoff(
        session,
        "commerce_agent",
        f"execute commerce evaluation for {action}",
        {
            "amount": payload.get("amount"),
            "reason": payload.get("reason"),
            "delegation_scope_status": delegation_proof.get("scope_status"),
            "token_subject": delegation_proof.get("subject"),
        },
        decision["status"],
        decision["reason"],
        source,
    )
    evaluation["handoff_id"] = handoff["id"]
    decision["internal_agent_evaluation"] = copy.deepcopy(evaluation)
    _record_policy_decision(session, decision)
    case_evaluation = _record_case_evaluation(
        session,
        _case_evaluation(
            "commerce_payment_probe",
            {
                "valid_delegation": delegation_proof.get("scope_status") == "accepted",
                "commerce_agent_called": bool(handoff.get("id")) and handoff.get("internal_agent_id") == "commerce_agent",
                "payment_blocked": normalized_action in COMMERCE_ACTIONS and decision.get("allowed") is False,
                "user_approval_required": decision.get("requires_user_approval") is True,
                "audit_recorded": any(item.get("id") == decision["id"] for item in session.get("policy_decisions", [])),
            },
            {
                "action": action,
                "decision_id": decision["id"],
                "handoff_id": handoff["id"],
                "endpoint": evaluation["endpoint"],
            },
        ),
        persist=True,
    )
    return {"status": decision["status"], "decision": copy.deepcopy(decision), "internal_agent": copy.deepcopy(evaluation), "case_evaluation": copy.deepcopy(case_evaluation)}


def _queue_agent_reroute(session: dict[str, Any], payload: dict[str, Any], delegation_proof: dict[str, Any], park_state: dict[str, Any] | None, source: str) -> dict[str, Any]:
    walking_priority = str(payload.get("walking_priority") or payload.get("walkingPriority") or "highest")
    mode = _scenario_mode_for_session(session, payload)
    proposal = _plan_for(session, walking_priority="highest" if walking_priority == "highest" else "medium", park_state=park_state, payload=payload)
    proposal["proposal_id"] = f"{proposal['proposal_id']}_queue"
    proposal["rationale"] = (
        f"Queue Agent reroute for {mode.replace('_', ' ')} based on selected scenario constraints, delegated route scope, and live wait tradeoffs."
        if mode != "visit_planning"
        else "Queue Agent reroute based on live waits, downtime risk, walking cost, and delegated family constraints."
    )
    proposal["queue_agent_decision"] = {
        "status": "recommended",
        "authority": INTERNAL_AGENTS["queue_agent"]["authority"],
        "cannot_do": copy.deepcopy(INTERNAL_AGENTS["queue_agent"]["cannot_do"]),
        "delegation_scope_status": delegation_proof.get("scope_status"),
    }
    evidence = {
        "requested_priority": walking_priority,
        "proposal_id": proposal["proposal_id"],
        "plan": proposal.get("plan"),
        "expected_wait_saved": proposal.get("expected_wait_saved"),
        "estimated_walking_distance": proposal.get("estimated_walking_distance"),
        "state_evidence": proposal.get("state_evidence"),
    }
    handoff = _record_internal_handoff(
        session,
        "queue_agent",
        "execute delegated reroute recommendation",
        evidence,
        "recommended",
        "Apply reroute recommendation to the active session proposal.",
        source,
    )
    evaluation = {
        "status": "recommended",
        "executed_by": "queue_agent",
        "endpoint": "/api/park/internal-agents/queue/reroute",
        "authority": INTERNAL_AGENTS["queue_agent"]["authority"],
        "cannot_do": copy.deepcopy(INTERNAL_AGENTS["queue_agent"]["cannot_do"]),
        "allowed": True,
        "requires_user_approval": False,
        "reason": "Queue Agent can recommend route changes within delegated route and wait-alert scope.",
        "handoff_id": handoff["id"],
    }
    session["proposal"] = proposal
    session["state"] = "negotiating"
    session["updated_at"] = _now_iso()
    session["conversation"].append(_event("queue_agent", "reroute_recommendation", {"internal_agent": evaluation, "proposal": proposal}))
    for action in ("route_change", "wait_alert"):
        decision = _policy_decision(session, action, {"source": source, "proposal_id": proposal["proposal_id"]})
        decision["internal_agent_evaluation"] = copy.deepcopy(evaluation)
        _record_policy_decision(session, decision)
    case_evaluation = _record_case_evaluation(
        session,
        _case_evaluation(
            "queue_reroute",
            {
                "valid_delegation": delegation_proof.get("scope_status") == "accepted",
                "queue_agent_called": bool(handoff.get("id")) and handoff.get("internal_agent_id") == "queue_agent",
                "route_plan_scope": "route_plan" in set(_as_list(delegation_proof.get("required_scope"))),
                "recommendation_returned": proposal.get("proposal_id", "").endswith("_queue") and bool(proposal.get("plan")),
                "proposal_updated": _as_dict(session.get("proposal")).get("proposal_id") == proposal["proposal_id"],
                "audit_recorded": any(item.get("payload", {}).get("proposal_id") == proposal["proposal_id"] for item in session.get("policy_decisions", [])),
            },
            {
                "proposal_id": proposal["proposal_id"],
                "handoff_id": handoff["id"],
                "endpoint": evaluation["endpoint"],
                "expected_wait_saved": proposal.get("expected_wait_saved"),
            },
        ),
    )
    _persist_session(session)
    return {"status": "recommended", "proposal": copy.deepcopy(proposal), "internal_agent": copy.deepcopy(evaluation), "case_evaluation": copy.deepcopy(case_evaluation)}


def _record_proposal_handoffs(session: dict[str, Any], proposal: dict[str, Any], source: str) -> None:
    evidence = _as_dict(proposal.get("state_evidence"))
    selected_rides = _as_list(evidence.get("selected_rides"))
    selected_food = _as_dict(evidence.get("selected_food"))
    alerts = _as_list(evidence.get("active_alerts"))
    _record_internal_handoff(
        session,
        "queue_agent",
        "rank route by waits, downtime risk, and walking cost",
        {
            "selected_rides": selected_rides[:2],
            "expected_wait_saved": proposal.get("expected_wait_saved"),
            "estimated_walking_distance": proposal.get("estimated_walking_distance"),
        },
        "recommended",
        "Use selected low-wait route candidates.",
        source,
    )
    _record_internal_handoff(
        session,
        "food_agent",
        "validate food timing and allergy-safe stop",
        {
            "selected_food": selected_food,
            "constraint": _as_dict(_as_dict(session.get("intent")).get("client_agent")).get("constraints", {}),
        },
        "recommended",
        "Use allergy-aware food stop without purchase authority.",
        source,
    )
    _record_internal_handoff(
        session,
        "guest_experience_agent",
        "assemble family itinerary tradeoff",
        {
            "plan": proposal.get("plan"),
            "confidence": proposal.get("confidence"),
            "tradeoffs": proposal.get("tradeoffs"),
        },
        "recommended",
        "Present itinerary to the personal agent.",
        source,
    )
    if alerts:
        _record_internal_handoff(
            session,
            "safety_agent",
            "screen active alerts before route proposal",
            {"active_alerts": alerts[:3]},
            "recommended",
            "Exclude unsafe or delayed attractions.",
            source,
        )


def _record_monitoring_handoffs(session: dict[str, Any], monitoring: dict[str, Any], source: str) -> None:
    policy_gate = _as_dict(monitoring.get("policy_gate"))
    evidence = _as_dict(monitoring.get("state_evidence"))
    if "safety_delay" in policy_gate or "safety_notice" in policy_gate or evidence.get("weather") or evidence.get("alert"):
        _record_internal_handoff(session, "safety_agent", "monitor incident or weather signal", evidence or {"event": monitoring.get("event")}, "recommended", str(monitoring.get("park_agent_offer") or "Issue safety-aware update."), source)
    if "route_change" in policy_gate or "priority_access" in policy_gate or "shared_route_plan" in policy_gate or evidence.get("ride"):
        _record_internal_handoff(session, "queue_agent", "find reroute or wait reduction", evidence or {"event": monitoring.get("event")}, "recommended", str(monitoring.get("park_agent_revision") or monitoring.get("accepted_resolution") or "Reroute guest flow."), source)
    if "food_recommendation" in policy_gate or "food_credit" in policy_gate or evidence.get("food"):
        _record_internal_handoff(session, "food_agent", "adjust food timing", evidence or {"event": monitoring.get("event")}, "recommended", str(monitoring.get("park_agent_offer") or "Move food stop."), source)
    if any(key in policy_gate for key in ("payment", "compensation_settlement", "compensation_offer", "refund_acceptance", "food_credit")):
        _record_internal_handoff(session, "commerce_agent", "check commerce boundary", {"policy_gate": policy_gate}, "requires_user_approval", "Offer may be presented; settlement or payment is gated.", source)


def _scenario_mode_from_payload(payload: dict[str, Any] | None) -> str:
    payload = payload or {}
    return str(payload.get("scenario_mode") or payload.get("scenarioMode") or "").strip()


def _scenario_mode_for_session(session: dict[str, Any], fallback_payload: dict[str, Any] | None = None) -> str:
    direct = _scenario_mode_from_payload(fallback_payload)
    if direct:
        return direct
    intent = _as_dict(_as_dict(session.get("intent")).get("client_agent"))
    constraints = _as_dict(intent.get("constraints"))
    mode = str(intent.get("scenario_mode") or intent.get("scenarioMode") or constraints.get("scenario_mode") or constraints.get("scenarioMode") or "").strip()
    return mode or "visit_planning"


def _scenario_static_plan(mode: str, walking_priority: str, avoid_wait: int) -> dict[str, Any] | None:
    high_walking = walking_priority == "highest"
    scenario = _as_dict(_protocol_scenario(mode).get("proposal"))
    if not scenario:
        return None
    plan = _as_list(scenario["plan"])
    walking = scenario.get("high_walking") if high_walking and scenario.get("high_walking") else scenario.get("walking")
    expected_handoffs = _as_list(_protocol_scenario(mode).get("handoffs"))
    return {
        "proposal_id": f"plan_{mode}_{hashlib.sha1(':'.join(str(item) for item in plan).encode('utf-8')).hexdigest()[:6]}",
        "plan": plan,
        "expected_wait_saved": scenario["saved"],
        "estimated_walking_distance": walking,
        "confidence": scenario["confidence"],
        "rationale": scenario["rationale"],
        "tradeoffs": [f"No planned stop exceeds the delegated {avoid_wait}-minute wait threshold.", *_as_list(scenario["tradeoffs"])],
        "requires_user_approval": False,
        "scenario_mode": mode,
        "expected_internal_handoffs": expected_handoffs,
        "state_evidence": scenario["evidence"],
    }


def _scenario_monitoring(mode: str, event: str) -> dict[str, Any] | None:
    monitoring = copy.deepcopy(_as_dict(_protocol_scenario(mode).get("monitoring")))
    if not monitoring:
        return None
    state_evidence = _as_dict(monitoring.get("state_evidence"))
    state_evidence["event"] = event
    monitoring["state_evidence"] = state_evidence
    return monitoring


def _get_session(session_id: str) -> dict[str, Any]:
    session = _sessions.get(session_id)
    if not session:
        try:
            from mongo_memory import get_agent_handshake_session

            persisted = get_agent_handshake_session(session_id)
        except Exception:
            persisted = None
        if not persisted:
            raise KeyError(f"Unknown agent handshake session: {session_id}")
        session = copy.deepcopy(persisted)
        session["session_id"] = str(session.get("session_id") or session.get("sessionId") or session.get("id") or session_id)
        session.setdefault("conversation", [])
        session.setdefault("policy_decisions", [])
        session.setdefault("internal_handoffs", [])
        session.setdefault("case_evaluations", [])
        _sessions[session["session_id"]] = session
    return session


def _record_delegation_failure(session: dict[str, Any], proof: dict[str, Any]) -> None:
    decision = {
        "id": f"ahp_policy_{hashlib.sha1(f'{session.get('session_id')}:delegation:{time.time_ns()}'.encode('utf-8')).hexdigest()[:12]}",
        "session_id": session.get("session_id"),
        "action": f"delegation_{proof.get('operation') or 'session'}",
        "status": "blocked",
        "allowed": False,
        "requires_user_approval": True,
        "reason": str(proof.get("reason") or "Delegation token check failed."),
        "created_at": _now_iso(),
        "payload": {"delegation_proof": copy.deepcopy(proof)},
    }
    _record_policy_decision(session, decision)
    _record_case_evaluation(
        session,
        _case_evaluation(
            "delegation_scope_rejection",
            {
                "token_checked": proof.get("signature_status") in {"valid", "invalid"} or proof.get("status") == "rejected",
                "missing_scope_detected": bool(proof.get("missing_scope")) or proof.get("status") == "rejected",
                "delegation_rejected": proof.get("status") == "rejected",
                "policy_decision_recorded": any(item.get("id") == decision["id"] for item in session.get("policy_decisions", [])),
                "session_not_advanced": session.get("state") in {"initiated", "verified"},
            },
            {"operation": proof.get("operation"), "missing_scope": proof.get("missing_scope"), "reason": proof.get("reason")},
        ),
        persist=True,
    )


def _enforce_delegation(session: dict[str, Any], payload: dict[str, Any] | None, operation: str, required_scopes: list[str] | None = None) -> dict[str, Any]:
    stored_delegation = _as_dict(session.get("delegation"))
    token = _delegation_token_from(payload) or _as_dict(stored_delegation.get("token"))
    proof = verify_delegation_token(token)
    claims = _as_dict(proof.get("claims"))
    required = sorted({scope for scope in (required_scopes or []) if scope})
    proof.update({"operation": operation, "required_scope": required})
    session.setdefault("delegation", {})
    session["delegation"]["last_verification"] = copy.deepcopy(proof)
    if proof.get("status") != "verified":
        _record_delegation_failure(session, proof)
        raise PermissionError(str(proof.get("reason") or "Delegation token rejected."))
    if str(claims.get("agent_id") or "") != str(_as_dict(session.get("client_agent")).get("agent_id") or ""):
        proof.update({"status": "rejected", "reason": "Delegation token agent does not match the handshaken client agent."})
        session["delegation"]["last_verification"] = copy.deepcopy(proof)
        _record_delegation_failure(session, proof)
        raise PermissionError(proof["reason"])
    if str(claims.get("sub") or "") != str(_as_dict(session.get("client_agent")).get("represents") or ""):
        proof.update({"status": "rejected", "reason": "Delegation token subject does not match the represented guest."})
        session["delegation"]["last_verification"] = copy.deepcopy(proof)
        _record_delegation_failure(session, proof)
        raise PermissionError(proof["reason"])
    token_scope = set(_normalize_scope(claims.get("scope")))
    missing = sorted(set(required) - token_scope)
    if missing:
        proof.update({"status": "rejected", "scope_status": "insufficient", "missing_scope": missing, "reason": f"Delegation token is missing required scope: {', '.join(missing)}."})
        session["delegation"]["last_verification"] = copy.deepcopy(proof)
        _record_delegation_failure(session, proof)
        raise PermissionError(proof["reason"])
    proof.update({"scope_status": "accepted", "reason": "Delegation token accepted for this operation."})
    session["delegation"]["last_verification"] = copy.deepcopy(proof)
    session["delegation"]["proof"] = copy.deepcopy(proof)
    session["delegation"]["token"] = copy.deepcopy(token)
    return proof


def _verification_for(proof: str, requested_session: str) -> dict[str, Any]:
    verified = bool(str(proof or "").strip()) and str(requested_session or "").strip()
    return {
        "status": "verified" if verified else "rejected",
        "guest_role": "ticket_holder" if verified else "unknown",
        "trust_level": "standard_guest" if verified else "untrusted",
        "proof_type": "signed_token",
    }


def evaluate_policy_action(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    session = _get_session(session_id)
    delegation_proof = _enforce_delegation(session, payload, "policy_check", ["policy_check"])
    action = str(payload.get("action") or payload.get("type") or "").strip()
    if not action:
        action = "unknown_action"
    if _policy_agent_for(action) == "commerce_agent":
        commerce_result = _commerce_agent_evaluate(session, payload, delegation_proof, "park_agent_policy_check")
        return {**commerce_result, "session": _copy_session(session)}
    decision = _policy_decision(session, action, payload)
    decision["delegation_proof"] = copy.deepcopy(delegation_proof)
    _record_policy_decision(session, decision)
    return {"status": decision["status"], "decision": copy.deepcopy(decision), "session": _copy_session(session)}


def commerce_agent_evaluate(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    session = _get_session(session_id)
    delegation_proof = _enforce_delegation(session, payload, "commerce_agent_evaluate", ["policy_check"])
    commerce_result = _commerce_agent_evaluate(session, payload, delegation_proof, "commerce_agent_endpoint")
    return {**commerce_result, "session": _copy_session(session)}


def queue_agent_reroute(session_id: str, payload: dict[str, Any], park_state: dict[str, Any] | None = None) -> dict[str, Any]:
    session = _get_session(session_id)
    delegation_proof = _enforce_delegation(session, payload, "queue_agent_reroute", ["route_plan", "wait_time_alert"])
    queue_result = _queue_agent_reroute(session, payload, delegation_proof, park_state, "queue_agent_endpoint")
    return {**queue_result, "session": _copy_session(session)}


def register_agent_onboarding(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    _load_trust_registry()
    payload = payload or {}
    agent_id = _agent_onboarding_id(payload)
    requested_scopes = _normalize_scope(payload.get("requested_scopes") or payload.get("requestedScopes") or payload.get("scope")) or DEFAULT_DELEGATION_SCOPES
    cannot_do = _normalize_scope(payload.get("cannot_do") or payload.get("cannotDo")) or sorted(CLIENT_BLOCKED_ACTIONS)
    partner_id = str(payload.get("partner_id") or payload.get("partnerId") or "demo_external_partner")
    existing_partner = _as_dict(get_partner(partner_id) or _partner_registry.get(partner_id))
    partner_allowed_scopes = _normalize_scope(payload.get("partner_allowed_scopes") or payload.get("partnerAllowedScopes") or existing_partner.get("allowed_scopes")) or DEFAULT_DELEGATION_SCOPES
    disallowed_scopes = sorted(set(requested_scopes) - set(partner_allowed_scopes))
    record = {
        "agent_id": agent_id,
        "display_name": str(payload.get("display_name") or payload.get("displayName") or agent_id),
        "partner": {
            "partner_id": partner_id,
            "partner_name": str(payload.get("partner_name") or payload.get("partnerName") or existing_partner.get("partner_name") or "Demo External Partner"),
            "contact": str(payload.get("partner_contact") or payload.get("partnerContact") or existing_partner.get("contact") or ""),
            "trust_tier": str(payload.get("trust_tier") or payload.get("trustTier") or existing_partner.get("trust_tier") or "sandbox"),
            "status": str(payload.get("partner_status") or payload.get("partnerStatus") or existing_partner.get("status") or "active"),
            "allowed_scopes": partner_allowed_scopes,
        },
        "status": "registered",
        "approval": "pending_certification",
        "scope_request_status": "rejected" if disallowed_scopes else "accepted",
        "disallowed_scopes": disallowed_scopes,
        "requested_scopes": requested_scopes,
        "allowed_scopes": [],
        "cannot_do": cannot_do,
        "represents": str(payload.get("represents") or "guest_user_123"),
        "use_case": str(payload.get("use_case") or payload.get("useCase") or "guest_route_planning"),
        "registered_at": _now_iso(),
        "updated_at": _now_iso(),
        "certification": None,
    }
    _agent_onboardings[agent_id] = copy.deepcopy(record)
    stored_partner = upsert_partner(record["partner"], actor="agent_onboarding_register")
    _partner_registry[partner_id] = copy.deepcopy(stored_partner)
    return {"status": "registered", "agent": copy.deepcopy(record), "next": f"/api/park/agent-onboarding/{agent_id}/certify"}


def get_agent_onboarding(agent_id: str) -> dict[str, Any]:
    record = _agent_onboardings.get(agent_id)
    if not record:
        raise KeyError(f"Unknown onboarded agent: {agent_id}")
    return {"status": "found", "agent": copy.deepcopy(record)}


def _certification_summary(session: dict[str, Any]) -> dict[str, Any]:
    evaluations = _as_list(session.get("case_evaluations"))
    latest_by_case: dict[str, dict[str, Any]] = {}
    for evaluation in evaluations:
        if isinstance(evaluation, dict):
            latest_by_case[str(evaluation.get("case") or "")] = evaluation
    required = {
        case: {
            "status": _as_dict(latest_by_case.get(case)).get("status") or "missing",
            "score": _as_dict(latest_by_case.get(case)).get("score") or 0,
            "criteria": _as_dict(latest_by_case.get(case)).get("criteria"),
        }
        for case in CERTIFICATION_REQUIRED_CASES
    }
    passed_cases = [case for case, evaluation in required.items() if evaluation["status"] == "passed"]
    return {
        "required_cases": required,
        "passed_cases": passed_cases,
        "score": round(len(passed_cases) / max(1, len(CERTIFICATION_REQUIRED_CASES)), 2),
        "status": "passed" if len(passed_cases) == len(CERTIFICATION_REQUIRED_CASES) else "failed",
    }


def certify_agent_onboarding(agent_id: str, payload: dict[str, Any] | None = None, park_state: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    record = _agent_onboardings.get(agent_id)
    if not record:
        raise KeyError(f"Unknown onboarded agent: {agent_id}")

    requested_scopes = _normalize_scope(payload.get("requested_scopes") or payload.get("requestedScopes") or payload.get("scope")) or _normalize_scope(record.get("requested_scopes"))
    cannot_do = _normalize_scope(payload.get("cannot_do") or payload.get("cannotDo")) or _normalize_scope(record.get("cannot_do")) or sorted(CLIENT_BLOCKED_ACTIONS)
    represented_guest = str(payload.get("represents") or record.get("represents") or "guest_user_123")
    partner = _as_dict(record.get("partner"))
    partner_allowed_scopes = _normalize_scope(partner.get("allowed_scopes")) or DEFAULT_DELEGATION_SCOPES
    partner_disallowed_scopes = sorted(set(requested_scopes) - set(partner_allowed_scopes))
    token = issue_delegation_token(
        {
            "subject": represented_guest,
            "agent_id": agent_id,
            "scope": requested_scopes,
            "cannot_do": cannot_do,
            "ttl_seconds": int(payload.get("ttl_seconds") or payload.get("ttlSeconds") or 600),
        }
    )["token"]
    certification_id = f"cert_{hashlib.sha1(f'{agent_id}:{time.time_ns()}'.encode('utf-8')).hexdigest()[:12]}"
    readiness_issues: list[str] = []
    session: dict[str, Any] | None = None

    try:
        if partner_disallowed_scopes:
            raise PermissionError(f"Partner allowlist does not permit requested scope: {', '.join(partner_disallowed_scopes)}.")
        identity = identity_handshake(
            {
                "agent_id": agent_id,
                "represents": represented_guest,
                "proof": "signed_token",
                "requested_session": certification_id,
                "delegation_token": token,
            }
        )
        session_id = identity["session"]["session_id"]
        capability_handshake(
            session_id,
            {
                "can_share": sorted(CLIENT_ALLOWED_TO_SHARE),
                "can_receive": sorted(CLIENT_ALLOWED_TO_RECEIVE),
                "cannot_do": cannot_do,
                "delegation_token": token,
            },
        )
        intent_handshake(
            session_id,
            {
                "goal": "maximize_family_satisfaction",
                "time_window": "3_hours",
                "constraints": {"children": 2, "avoid_wait_over_minutes": 35, "avoid_thrill_rides": True, "food_allergy": "peanut"},
                "delegation_token": token,
            },
        )
        propose_plan(session_id, {"planner": "agent_onboarding_certification", "delegation_token": token}, park_state=park_state)
        queue_agent_reroute(session_id, {"walking_priority": "highest", "reason": "Certification reroute proof.", "delegation_token": token}, park_state=park_state)
        commerce_agent_evaluate(session_id, {"action": "payment", "amount": 1, "reason": "Certification payment boundary proof.", "delegation_token": token})
        session = get_session(session_id)["session"]
    except PermissionError as error:
        readiness_issues.append(str(error))
        if session is None:
            for candidate in reversed(list(_sessions.values())):
                if _as_dict(candidate.get("client_agent")).get("agent_id") == agent_id and _as_dict(candidate.get("client_agent")).get("requested_session") == certification_id:
                    session = _copy_session(candidate)
                    break
    except Exception as error:
        readiness_issues.append(str(error)[:240])

    if session is None:
        summary = {"required_cases": {case: {"status": "missing", "score": 0} for case in CERTIFICATION_REQUIRED_CASES}, "passed_cases": [], "score": 0, "status": "failed"}
    else:
        summary = _certification_summary(session)

    approved = summary["status"] == "passed"
    certification = {
        "certification_id": certification_id,
        "status": "approved" if approved else "blocked",
        "approval": "approved_for_guest_route_planning" if approved else "blocked_until_scope_fixed",
        "score": summary["score"],
        "required_cases": summary["required_cases"],
        "passed_cases": summary["passed_cases"],
            "allowed_scopes": requested_scopes if approved else [],
            "partner_allowed_scopes": partner_allowed_scopes,
            "partner_disallowed_scopes": partner_disallowed_scopes,
            "readiness_issues": readiness_issues,
        "session_id": session.get("session_id") if session else None,
        "certified_at": _now_iso(),
    }
    certification["credential"] = _issue_certification_credential(agent_id, certification, requested_scopes) if approved else None
    record.update(
        {
            "status": certification["status"],
            "approval": certification["approval"],
            "requested_scopes": requested_scopes,
            "allowed_scopes": certification["allowed_scopes"],
            "cannot_do": cannot_do,
            "certification": certification,
            "updated_at": _now_iso(),
        }
    )
    _agent_onboardings[agent_id] = copy.deepcopy(record)
    return {"status": certification["status"], "agent": copy.deepcopy(record), "certification": copy.deepcopy(certification), "session": copy.deepcopy(session) if session else None}


def _policy_decision(session: dict[str, Any], action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_action = str(action or "").strip()
    rule = ACTION_POLICY_RULES.get(normalized_action) or ACTION_POLICY_RULES.get(normalized_action.replace("-", "_"))
    if rule is None:
        rule = {
            "status": "requires_user_approval",
            "allowed": False,
            "requires_user_approval": True,
            "reason": "Unknown agent action is not in the delegated handshake contract.",
        }
    decision = {
        "id": f"ahp_policy_{hashlib.sha1(f'{session.get('session_id')}:{normalized_action}:{time.time_ns()}'.encode('utf-8')).hexdigest()[:12]}",
        "session_id": session.get("session_id"),
        "action": normalized_action,
        "status": rule["status"],
        "allowed": bool(rule["allowed"]),
        "requires_user_approval": bool(rule["requires_user_approval"]),
        "reason": rule["reason"],
        "created_at": _now_iso(),
        "payload": copy.deepcopy(payload or {}),
    }
    return decision


def _record_policy_decision(session: dict[str, Any], decision: dict[str, Any]) -> None:
    session.setdefault("policy_decisions", [])
    session["policy_decisions"].append(copy.deepcopy(decision))
    session["policy_decisions"] = session["policy_decisions"][-80:]
    agent_id = _policy_agent_for(str(decision.get("action") or ""))
    _record_internal_handoff(
        session,
        agent_id,
        f"policy check for {decision.get('action')}",
        {"policy_status": decision.get("status"), "requires_user_approval": decision.get("requires_user_approval"), "payload": decision.get("payload")},
        str(decision.get("status") or "reviewed"),
        str(decision.get("reason") or "Policy decision recorded."),
        "policy",
    )
    session["conversation"].append(_event("park_agent", "policy_enforcement", decision))
    _persist_policy_event(decision)
    session["updated_at"] = _now_iso()
    _persist_session(session)


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _deep_merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _protocol_scenario_catalog_raw() -> dict[str, dict[str, Any]]:
    catalog = copy.deepcopy(BUILT_IN_PROTOCOL_SCENARIOS)
    config_path = os.getenv("PARKPULSE_AHP_SCENARIO_CATALOG", "").strip()
    if not config_path:
        return catalog
    try:
        configured = json.loads(Path(config_path).read_text(encoding="utf-8"))
        configured_scenarios = configured.get("scenarios") if isinstance(configured, dict) else configured
        if isinstance(configured_scenarios, list):
            configured_scenarios = {str(item.get("id") or ""): item for item in configured_scenarios if isinstance(item, dict) and item.get("id")}
        if isinstance(configured_scenarios, dict):
            for scenario_id, scenario in configured_scenarios.items():
                if not isinstance(scenario, dict):
                    continue
                scenario_id = str(scenario.get("id") or scenario_id)
                base = catalog.get(scenario_id, {"id": scenario_id})
                catalog[scenario_id] = _deep_merge_dict(base, scenario)
    except Exception:
        return catalog
    return catalog


def _protocol_scenario(mode: str) -> dict[str, Any]:
    return _as_dict(_protocol_scenario_catalog_raw().get(mode))


def agent_handshake_scenario_catalog() -> dict[str, Any]:
    config_path = os.getenv("PARKPULSE_AHP_SCENARIO_CATALOG", "").strip()
    catalog = _protocol_scenario_catalog_raw()
    return {
        "status": "ready",
        "mode": "agent_handshake_scenario_catalog",
        "protocol_version": "parkpulse-ahp-0.1",
        "config_source": config_path or "built_in",
        "configurable": True,
        "override_env": "PARKPULSE_AHP_SCENARIO_CATALOG",
        "scenario_count": len(catalog),
        "scenarios": [copy.deepcopy(catalog[key]) for key in sorted(catalog.keys())],
    }


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _family_start_zone(park_state: dict[str, Any]) -> str:
    for segment in _as_list(park_state.get("guestSegments")):
        if "famil" in str(segment.get("id") or segment.get("label") or "").lower():
            return str(segment.get("currentZoneId") or "entrancePlaza")
    return "entrancePlaza"


def _zone_lookup(park_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(zone.get("id")): zone for zone in _as_list(_as_dict(park_state.get("guestFlow")).get("zones")) if zone.get("id")}


def _path_minutes(park_state: dict[str, Any], from_zone: str, to_zone: str) -> float:
    if not from_zone or not to_zone or from_zone == to_zone:
        return 0.0
    graph: dict[str, list[tuple[str, float]]] = {}
    for path in _as_list(_as_dict(park_state.get("guestFlow")).get("paths")):
        start = str(path.get("from") or "")
        end = str(path.get("to") or "")
        if not start or not end:
            continue
        penalty = 2.5 if str(path.get("status") or "").lower() in {"busy", "congested"} else 0.0
        minutes = max(1.0, _num(path.get("walkMinutes"), 8.0) + penalty)
        graph.setdefault(start, []).append((end, minutes))
        graph.setdefault(end, []).append((start, minutes))
    queue: list[tuple[float, str]] = [(0.0, from_zone)]
    best: dict[str, float] = {from_zone: 0.0}
    while queue:
        queue.sort(key=lambda item: item[0])
        minutes, zone = queue.pop(0)
        if zone == to_zone:
            return minutes
        if minutes > best.get(zone, 9999):
            continue
        for next_zone, extra in graph.get(zone, []):
            candidate = minutes + extra
            if candidate < best.get(next_zone, 9999):
                best[next_zone] = candidate
                queue.append((candidate, next_zone))
    return 12.0


def _kid_friendly_score(ride: dict[str, Any]) -> float:
    name = str(ride.get("name") or ride.get("id") or "").lower()
    thrill_terms = {"coaster", "drop", "launch", "thrill"}
    calm_terms = {"arcade", "theater", "river", "carousel", "family", "show"}
    score = 0.0
    if any(term in name for term in calm_terms):
        score -= 20
    if any(term in name for term in thrill_terms):
        score += 35
    return score


def _rank_live_rides(session: dict[str, Any], park_state: dict[str, Any], walking_priority: str) -> list[dict[str, Any]]:
    intent = _as_dict(_as_dict(session.get("intent")).get("client_agent"))
    constraints = _as_dict(intent.get("constraints"))
    avoid_wait = _num(constraints.get("avoid_wait_over_minutes") or constraints.get("avoidWaitOverMinutes"), 35)
    avoid_thrill = bool(constraints.get("avoid_thrill_rides") or constraints.get("avoidThrillRides"))
    start_zone = _family_start_zone(park_state)
    ranked: list[dict[str, Any]] = []
    for ride in _as_list(_as_dict(park_state.get("guestFlow")).get("rides")):
        status = str(ride.get("status") or "unknown").lower()
        wait = _num(ride.get("waitMins"), 999)
        downtime = _num(ride.get("downtimeRisk"), 100)
        if status in {"down", "closed"} or downtime >= 95:
            continue
        zone = str(ride.get("zone") or "")
        walk = _path_minutes(park_state, start_zone, zone)
        score = wait + downtime * 0.25 + _kid_friendly_score(ride)
        if avoid_thrill:
            score += _kid_friendly_score(ride)
        if wait > avoid_wait:
            score += (wait - avoid_wait) * 2
        score += walk * (2.4 if walking_priority == "highest" else 1.0)
        zone_info = _zone_lookup(park_state).get(zone, {})
        score += max(0.0, _num(zone_info.get("density"), 0) - 85) * 0.45
        ranked.append({**ride, "walkMinutesFromFamily": round(walk, 1), "plannerScore": round(score, 2)})
    return sorted(ranked, key=lambda ride: _num(ride.get("plannerScore"), 999))


def _rank_live_food(park_state: dict[str, Any], start_zone: str, walking_priority: str) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for food in _as_list(_as_dict(park_state.get("foodInventory")).get("locations")):
        zone = str(food.get("id") or "")
        walk = _path_minutes(park_state, start_zone, zone)
        eta = _num(food.get("pickupEtaMinutes"), 999)
        backlog = _num(food.get("mobileOrderBacklog"), 999)
        low_inventory = len(_as_list(food.get("lowInventoryItems")))
        score = eta + backlog * 0.08 + low_inventory * 8 + walk * (2.0 if walking_priority == "highest" else 0.8)
        ranked.append({**food, "walkMinutesFromFamily": round(walk, 1), "plannerScore": round(score, 2)})
    return sorted(ranked, key=lambda food: _num(food.get("plannerScore"), 999))


def _live_plan_for(session: dict[str, Any], park_state: dict[str, Any], walking_priority: str = "medium") -> dict[str, Any]:
    ranked_rides = _rank_live_rides(session, park_state, walking_priority)
    start_zone = _family_start_zone(park_state)
    ranked_food = _rank_live_food(park_state, start_zone, walking_priority)
    selected_rides = ranked_rides[:2] or [{"name": "Indoor Arcade", "zone": "arcadeZone", "waitMins": 12, "walkMinutesFromFamily": 8}]
    selected_food = ranked_food[0] if ranked_food else {"name": "Pizza Garden allergy-safe counter", "pickupEtaMinutes": 15, "availableItems": ["pizza_combo"]}
    plan = [str(ride.get("name") or ride.get("id")) for ride in selected_rides]
    plan.append(str(selected_food.get("name") or selected_food.get("id") or "Allergy-safe food stop"))
    next_event = None
    for event in _as_list(_as_dict(_as_dict(park_state.get("operatingClock")).get("eventSchedule")).get("showtimes")):
        if _num(event.get("minutesUntilStart"), 9999) <= 180:
            next_event = event
            break
    plan.append(str(next_event.get("name")) if isinstance(next_event, dict) else "Flexible low-crowd reset window")
    total_walk = sum(_num(ride.get("walkMinutesFromFamily"), 0) for ride in selected_rides[:1]) + _num(selected_food.get("walkMinutesFromFamily"), 0)
    avg_wait = sum(_num(ride.get("waitMins"), 0) for ride in selected_rides) / max(1, len(selected_rides))
    baseline_wait = max([_num(ride.get("waitMins"), 0) for ride in _as_list(_as_dict(park_state.get("guestFlow")).get("rides"))] or [avg_wait])
    wait_saved = max(0, int(round(baseline_wait - avg_wait)))
    alerts = _as_list(park_state.get("alerts"))
    state_evidence = {
        "source": "live_park_state",
        "sim_time": park_state.get("simTime"),
        "family_start_zone": start_zone,
        "weather": park_state.get("weather"),
        "active_alerts": alerts[:3],
        "selected_rides": [
            {
                "id": ride.get("id"),
                "name": ride.get("name"),
                "status": ride.get("status"),
                "waitMins": ride.get("waitMins"),
                "zone": ride.get("zone"),
                "walkMinutesFromFamily": ride.get("walkMinutesFromFamily"),
                "plannerScore": ride.get("plannerScore"),
            }
            for ride in selected_rides
        ],
        "selected_food": {
            "id": selected_food.get("id"),
            "name": selected_food.get("name"),
            "pickupEtaMinutes": selected_food.get("pickupEtaMinutes"),
            "mobileOrderBacklog": selected_food.get("mobileOrderBacklog"),
            "availableItems": selected_food.get("availableItems"),
            "walkMinutesFromFamily": selected_food.get("walkMinutesFromFamily"),
        },
        "rejected_rides": [
            {"id": ride.get("id"), "name": ride.get("name"), "status": ride.get("status"), "waitMins": ride.get("waitMins"), "reason": "higher wait, downtime, thrill intensity, or walking cost"}
            for ride in ranked_rides[2:5]
        ],
    }
    confidence = 0.74
    if ranked_rides and ranked_food:
        confidence += 0.08
    if alerts:
        confidence -= 0.04
    if walking_priority == "highest":
        confidence -= 0.02
    return {
        "proposal_id": f"live_plan_{hashlib.sha1(_stable_plan_key(plan, park_state).encode('utf-8')).hexdigest()[:6]}",
        "plan": plan,
        "expected_wait_saved": f"{wait_saved} minutes",
        "estimated_walking_distance": f"{max(0.2, total_walk * 0.08):.1f} miles",
        "confidence": round(max(0.55, min(0.9, confidence)), 2),
        "rationale": "Live-state proposal based on current ride status, wait times, food pickup pressure, walking paths, weather, and active alerts.",
        "tradeoffs": [
            "Down or high-risk attractions are excluded from the plan.",
            "Food timing uses live pickup ETA and low-inventory signals.",
            "Walking priority increases the cost of cross-zone moves.",
        ],
        "requires_user_approval": False,
        "state_evidence": state_evidence,
    }


def _stable_plan_key(plan: list[str], park_state: dict[str, Any]) -> str:
    clock = _as_dict(park_state.get("simTime"))
    return ":".join([*plan, str(clock.get("hour")), str(clock.get("minute"))])


def _live_monitoring_event(park_state: dict[str, Any]) -> dict[str, Any] | None:
    alerts = _as_list(park_state.get("alerts"))
    rides = _as_list(_as_dict(park_state.get("guestFlow")).get("rides"))
    foods = _as_list(_as_dict(park_state.get("foodInventory")).get("locations"))
    weather = _as_dict(park_state.get("weather"))
    down_ride = next((ride for ride in rides if str(ride.get("status") or "").lower() in {"down", "closed"}), None)
    high_wait = next((ride for ride in sorted(rides, key=lambda item: _num(item.get("waitMins"), 0), reverse=True) if _num(ride.get("waitMins"), 0) >= 60), None)
    food_backlog = next((food for food in sorted(foods, key=lambda item: _num(item.get("pickupEtaMinutes"), 0), reverse=True) if _num(food.get("pickupEtaMinutes"), 0) >= 18), None)
    storm_risk = _num(weather.get("stormRisk"), 0)
    if down_ride:
        return {
            "event": f"{down_ride.get('name', 'A ride')} is unavailable.",
            "park_agent_offer": f"Reroute away from {down_ride.get('name')} and avoid overloading the next highest-wait attraction.",
            "client_agent_counter": "My user values time and low walking. Find a nearby lower-wait alternative.",
            "park_agent_revision": "Use the current live proposal route and continue monitoring wait spikes.",
            "accepted_resolution": "Accepted with user notification.",
            "policy_gate": {"safety_delay": "cannot_override", "route_change": "agent_allowed", "compensation_settlement": "user_approval_required"},
            "state_evidence": {"source": "live_park_state", "alert": alerts[0] if alerts else None, "ride": down_ride},
        }
    if high_wait:
        return {
            "event": f"{high_wait.get('name', 'An attraction')} wait is {int(_num(high_wait.get('waitMins'), 0))} minutes.",
            "park_agent_offer": "Suppress this attraction from the route and shift the family to lower-wait indoor options.",
            "accepted_resolution": "Accepted. Notify user with a lower-wait route update.",
            "policy_gate": {"wait_alert": "agent_allowed", "route_change": "agent_allowed"},
            "state_evidence": {"source": "live_park_state", "ride": high_wait},
        }
    if food_backlog:
        return {
            "event": f"{food_backlog.get('name', 'A food location')} pickup ETA is {int(_num(food_backlog.get('pickupEtaMinutes'), 0))} minutes.",
            "park_agent_offer": "Move the food stop to the lowest-ETA allergy-compatible location.",
            "accepted_resolution": "Accepted. Update route timing without purchase.",
            "policy_gate": {"food_recommendation": "agent_allowed", "payment": "blocked"},
            "state_evidence": {"source": "live_park_state", "food": food_backlog},
        }
    if storm_risk >= 55:
        return {
            "event": f"Storm risk is {int(storm_risk)}%.",
            "park_agent_offer": "Shift route toward covered and indoor zones.",
            "accepted_resolution": "Accepted. Notify user with covered-route update.",
            "policy_gate": {"safety_notice": "agent_allowed", "route_change": "agent_allowed"},
            "state_evidence": {"source": "live_park_state", "weather": weather},
        }
    return None


def agent_contract() -> dict[str, Any]:
    return {
        "status": "ready",
        "mode": "agent_native_handshake_contract",
        "protocol_version": "parkpulse-ahp-0.1",
        "counterparty": {
            "agent_id": "parkpulse_park_agent",
            "represents": "park_operations",
            "accountability": "park-side operating layer for safety, commerce, guest experience, and operations agents",
        },
        "routes": [
            "POST /api/park/delegation-token",
            "GET /api/park/agent-onboarding/issuer",
            "POST /api/park/agent-onboarding/register",
            "POST /api/park/agent-onboarding/verify-credential",
            "POST /api/park/agent-onboarding/revoke-credential",
            "POST /api/park/agent-onboarding/{agent_id}/certify",
            "GET /api/park/agent-onboarding/{agent_id}",
            "GET /api/park/agent-trust/status",
            "GET /api/park/agent-trust/partners",
            "POST /api/park/agent-trust/partners",
            "GET /api/park/agent-trust/keys",
            "POST /api/park/agent-trust/keys/rotate",
            "GET /api/park/agent-trust/revocations",
            "GET /api/park/agent-trust/audit",
            "GET /api/park/agent-handshake/scenarios",
            "POST /api/park/agent-handshake/scenario-eval",
            "POST /api/park/handshake",
            "POST /api/park/session/{session_id}/capabilities",
            "POST /api/park/session/{session_id}/intent",
            "POST /api/park/session/{session_id}/propose",
            "POST /api/park/session/{session_id}/counter",
            "POST /api/park/session/{session_id}/commit",
            "POST /api/park/session/{session_id}/policy-check",
            "POST /api/park/internal-agents/commerce/evaluate",
            "POST /api/park/internal-agents/queue/reroute",
            "GET /api/park/session/{session_id}/monitor",
            "POST /api/park/session/{session_id}/escalate",
            "POST /api/park/session/{session_id}/close",
        ],
        "state_machine": ["initiated", "verified", "scoped", "intent_accepted", "negotiating", "committed", "monitoring", "escalated", "closed"],
        "can_offer": PARK_CAPABILITIES,
        "requires_approval_for": PARK_APPROVAL_GATES,
        "scenario_catalog": agent_handshake_scenario_catalog(),
        "trust_issuer": certification_issuer_metadata(),
        "internal_agents": [
            {"agent_id": agent_id, **copy.deepcopy(agent)}
            for agent_id, agent in INTERNAL_AGENTS.items()
        ],
        "policy_actions": ACTION_POLICY_RULES,
        "policy_gates": [
            {"action": "route_change", "approval": "agent_allowed", "reason": "No payment, health-data sharing, or identity-sensitive action."},
            {"action": "wait_alert", "approval": "agent_allowed", "reason": "Informational guest experience update."},
            {"action": "food_recommendation", "approval": "agent_allowed", "reason": "Constrained to declared allergy and public menu safety data."},
            {"action": "payment", "approval": "user_required", "reason": "Outside delegated client-agent authority."},
            {"action": "refund_acceptance", "approval": "user_required", "reason": "Compensation settlement cannot be accepted silently."},
            {"action": "medical_escalation", "approval": "user_required", "reason": "Sensitive care workflow."},
        ],
    }


def identity_handshake(payload: dict[str, Any]) -> dict[str, Any]:
    agent_id = str(payload.get("agent_id") or "unknown_client_agent")
    represented_user_id = str(payload.get("represents") or payload.get("represented_user_id") or "unknown_guest")
    requested_session = str(payload.get("requested_session") or f"park_visit_{datetime.now(UTC).strftime('%Y_%m_%d')}")
    proof = str(payload.get("proof") or "")
    provided_delegation_token = _delegation_token_from(payload)
    issued_delegation = None
    if provided_delegation_token is None:
        issued_delegation = issue_delegation_token(
            {
                "subject": represented_user_id,
                "agent_id": agent_id,
                "scope": payload.get("scope") or DEFAULT_DELEGATION_SCOPES,
                "cannot_do": payload.get("cannot_do") or sorted(CLIENT_BLOCKED_ACTIONS),
                "ttl_seconds": payload.get("ttl_seconds") or 3 * 60 * 60,
            }
        )
        provided_delegation_token = issued_delegation["token"]
    delegation_proof = verify_delegation_token(provided_delegation_token)
    verification = _verification_for(proof or "delegation_token", requested_session)
    if delegation_proof.get("status") != "verified":
        verification = {
            **verification,
            "status": "rejected",
            "guest_role": "unknown",
            "trust_level": "untrusted",
            "reason": delegation_proof.get("reason") or "Delegation token rejected.",
        }
    elif str(delegation_proof.get("agent_id") or "") != agent_id or str(delegation_proof.get("subject") or "") != represented_user_id:
        delegation_proof = {
            **delegation_proof,
            "status": "rejected",
            "reason": "Delegation token claims do not match the identity handshake.",
        }
        verification = {
            **verification,
            "status": "rejected",
            "guest_role": "unknown",
            "trust_level": "untrusted",
            "reason": delegation_proof["reason"],
        }
    session_id = _session_id(agent_id, represented_user_id, requested_session)
    session = {
        "session_id": session_id,
        "protocol_version": "parkpulse-ahp-0.1",
        "state": "verified" if verification["status"] == "verified" else "initiated",
        "client_agent": {"agent_id": agent_id, "represents": represented_user_id, "requested_session": requested_session},
        "park_agent": {"agent_id": "parkpulse_park_agent", "represents": "park_operations"},
        "identity": verification,
        "delegation": {
            "token": copy.deepcopy(provided_delegation_token),
            "proof": copy.deepcopy(delegation_proof),
            "last_verification": copy.deepcopy(delegation_proof),
            "issuer_mode": "demo_auto" if issued_delegation else "provided",
        },
        "permissions": None,
        "intent": None,
        "proposal": None,
        "commitment": None,
        "monitoring": None,
        "policy_decisions": [],
        "internal_handoffs": [],
        "case_evaluations": [],
        "policy_gates": agent_contract()["policy_gates"],
        "conversation": [
            _event(
                "client_agent",
                "identity_handshake",
                {
                    "agent_id": agent_id,
                    "represents": represented_user_id,
                    "requested_session": requested_session,
                    "delegation_token": "provided" if payload.get("delegation_token") else "demo_auto_issued",
                },
            ),
            _event("park_agent", "identity_verification", verification),
            _event("park_agent", "delegation_token_verification", delegation_proof),
        ],
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    _sessions[session_id] = session
    case_evaluation = _record_case_evaluation(
        session,
        _case_evaluation(
            "identity_trust",
            {
                "signature_valid": delegation_proof.get("signature_status") == "valid",
                "token_verified": delegation_proof.get("status") == "verified",
                "subject_matches": str(delegation_proof.get("subject") or "") == represented_user_id,
                "agent_matches": str(delegation_proof.get("agent_id") or "") == agent_id,
                "identity_verified": verification.get("status") == "verified",
            },
            {
                "agent_id": agent_id,
                "represents": represented_user_id,
                "requested_session": requested_session,
                "issuer_mode": session["delegation"]["issuer_mode"],
            },
        ),
    )
    _persist_session(session)
    return {"status": verification["status"], "session": _copy_session(session), "delegation": copy.deepcopy(session["delegation"]), "case_evaluation": copy.deepcopy(case_evaluation), "next": "capability_handshake"}


def capability_handshake(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    session = _get_session(session_id)
    _enforce_delegation(
        session,
        payload,
        "capability_handshake",
        [scope for scope in _normalize_scope(payload.get("can_share")) if scope in CLIENT_ALLOWED_TO_SHARE]
        + [scope for scope in _normalize_scope(payload.get("can_receive")) if scope in CLIENT_ALLOWED_TO_RECEIVE],
    )
    can_share = [str(value) for value in payload.get("can_share", []) if str(value) in CLIENT_ALLOWED_TO_SHARE]
    can_receive = [str(value) for value in payload.get("can_receive", []) if str(value) in CLIENT_ALLOWED_TO_RECEIVE]
    cannot_do = sorted(set([str(value) for value in payload.get("cannot_do", [])]) | CLIENT_BLOCKED_ACTIONS)
    permissions = {
        "can_share": can_share,
        "can_receive": can_receive,
        "cannot_do": cannot_do,
        "expires_at": (datetime.now(UTC) + timedelta(hours=3)).isoformat().replace("+00:00", "Z"),
    }
    park_offer = {"can_offer": PARK_CAPABILITIES, "requires_approval_for": PARK_APPROVAL_GATES}
    session["permissions"] = {"client_agent": permissions, "park_agent": park_offer}
    session["state"] = "scoped"
    session["updated_at"] = _now_iso()
    session["conversation"].append(_event("client_agent", "capability_handshake", permissions))
    session["conversation"].append(_event("park_agent", "capability_response", park_offer))
    requested_shares = {str(value) for value in payload.get("can_share", [])}
    for blocked_share in sorted(requested_shares - set(can_share)):
        if blocked_share in ACTION_POLICY_RULES:
            _record_policy_decision(session, _policy_decision(session, blocked_share, {"source": "capability_handshake"}))
    delegation_proof = _as_dict(session.get("delegation")).get("last_verification", {})
    case_evaluation = _record_case_evaluation(
        session,
        _case_evaluation(
            "capability_scope",
            {
                "delegation_accepted": _as_dict(delegation_proof).get("scope_status") == "accepted",
                "share_scope_filtered": set(can_share).issubset(CLIENT_ALLOWED_TO_SHARE),
                "receive_scope_filtered": set(can_receive).issubset(CLIENT_ALLOWED_TO_RECEIVE),
                "client_permissions_nonempty": bool(can_share) and bool(can_receive),
                "blocked_actions_retained": CLIENT_BLOCKED_ACTIONS.issubset(set(cannot_do)),
            },
            {
                "can_share": can_share,
                "can_receive": can_receive,
                "cannot_do": cannot_do,
            },
        ),
    )
    _persist_session(session)
    return {"status": "scoped", "session": _copy_session(session), "case_evaluation": copy.deepcopy(case_evaluation), "next": "intent_handshake"}


def intent_handshake(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    session = _get_session(session_id)
    _enforce_delegation(session, payload, "intent_handshake", ["preferences"])
    constraints = payload.get("constraints") if isinstance(payload.get("constraints"), dict) else {}
    avoid_wait = int(constraints.get("avoid_wait_over_minutes") or constraints.get("avoidWaitOverMinutes") or 35)
    food_allergy = str(constraints.get("food_allergy") or constraints.get("foodAllergy") or "").strip()
    optimization_targets = ["low_wait", "low_walking", "kid_friendly"]
    if food_allergy:
        optimization_targets.append("safe_food")
    accepted = {
        "accepted_goal": True,
        "optimization_targets": optimization_targets,
        "conflict_notice": "Food options may be limited near Water Zone." if food_allergy else "No major constraint conflict detected.",
        "bounded_by": {
            "avoid_wait_over_minutes": avoid_wait,
            "requires_user_approval_for": PARK_APPROVAL_GATES,
        },
    }
    session["intent"] = {"client_agent": copy.deepcopy(payload), "park_agent": accepted}
    session["state"] = "intent_accepted"
    session["updated_at"] = _now_iso()
    session["conversation"].append(_event("client_agent", "intent_handshake", payload))
    session["conversation"].append(_event("park_agent", "intent_response", accepted))
    _persist_session(session)
    return {"status": "intent_accepted", "session": _copy_session(session), "next": "proposal"}


def _plan_for(session: dict[str, Any], walking_priority: str = "medium", park_state: dict[str, Any] | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(park_state, dict) and park_state:
        return _live_plan_for(session, park_state, walking_priority)
    intent = session.get("intent", {}).get("client_agent", {}) if isinstance(session.get("intent"), dict) else {}
    constraints = intent.get("constraints", {}) if isinstance(intent.get("constraints"), dict) else {}
    avoid_wait = int(constraints.get("avoid_wait_over_minutes") or constraints.get("avoidWaitOverMinutes") or 35)
    scenario_mode = _scenario_mode_for_session(session, payload)
    scenario_plan = _scenario_static_plan(scenario_mode, walking_priority, avoid_wait)
    if scenario_plan:
        return scenario_plan
    if walking_priority == "highest":
        plan = ["Indoor Arcade", "Pizza Garden allergy-safe counter", "Parade Zone", "Lazy River priority return"]
        walking = "0.7 miles"
        saved = "31 minutes"
        rationale = "Clustered indoor and central-zone stops reduce walking while keeping waits inside the delegated threshold."
        confidence = 0.78
    else:
        plan = ["Lazy River", "Indoor Arcade", "Pizza Garden allergy-safe counter", "Parade Zone"]
        walking = "1.1 miles"
        saved = "42 minutes"
        rationale = "Starts with the lowest projected family attraction wait, then times food before the lunch queue spike."
        confidence = 0.82
    return {
        "proposal_id": f"plan_{hashlib.sha1(':'.join(plan).encode('utf-8')).hexdigest()[:6]}",
        "plan": plan,
        "expected_wait_saved": saved,
        "estimated_walking_distance": walking,
        "confidence": confidence,
        "rationale": rationale,
        "tradeoffs": [
            f"No attraction wait is planned above {avoid_wait} minutes.",
            "Food recommendation is constrained to peanut-allergy-safe options.",
            "Compensation, purchases, and medical actions remain user-approval gated.",
        ],
        "requires_user_approval": False,
        "scenario_mode": "visit_planning",
        "state_evidence": {"source": "static_fallback", "scenario_mode": "visit_planning", "reason": "Live park state was not supplied to the handshake planner."},
    }


def propose_plan(session_id: str, payload: dict[str, Any] | None = None, park_state: dict[str, Any] | None = None) -> dict[str, Any]:
    session = _get_session(session_id)
    _enforce_delegation(session, payload or {}, "propose_plan", ["preferences", "route_plan"])
    proposal = _plan_for(session, park_state=park_state, payload=payload)
    session["proposal"] = proposal
    session["state"] = "negotiating"
    session["updated_at"] = _now_iso()
    _record_proposal_handoffs(session, proposal, "proposal")
    session["conversation"].append(_event("park_agent", "proposal", proposal))
    for action in ("route_change", "wait_alert", "food_recommendation"):
        _record_policy_decision(session, _policy_decision(session, action, {"source": "proposal", "proposal_id": proposal["proposal_id"]}))
    _persist_session(session)
    return {"status": "proposal_ready", "session": _copy_session(session), "proposal": copy.deepcopy(proposal)}


def counter_proposal(session_id: str, payload: dict[str, Any], park_state: dict[str, Any] | None = None) -> dict[str, Any]:
    session = _get_session(session_id)
    _enforce_delegation(session, payload, "counter_proposal", ["preferences", "route_plan"])
    priority_change = payload.get("priority_change") if isinstance(payload.get("priority_change"), dict) else {}
    walking_priority = str(priority_change.get("walking_distance") or priority_change.get("walkingDistance") or "medium")
    revised = _plan_for(session, walking_priority="highest" if walking_priority == "highest" else "medium", park_state=park_state, payload=payload)
    revised["proposal_id"] = f"{revised['proposal_id']}_r1"
    revised["countered_from"] = session.get("proposal", {}).get("proposal_id") if isinstance(session.get("proposal"), dict) else None
    mode = _scenario_mode_for_session(session, payload)
    revised["rationale"] = (
        f"Revised after client-agent counter for {mode.replace('_', ' ')}: the requested priority change is now the top optimization target."
        if mode != "visit_planning"
        else "Revised after client-agent counter: walking distance is now the top optimization target."
    )
    session["proposal"] = revised
    session["state"] = "negotiating"
    session["updated_at"] = _now_iso()
    session["conversation"].append(_event("client_agent", "counter_request", payload))
    _record_proposal_handoffs(session, revised, "counter")
    session["conversation"].append(_event("park_agent", "revised_proposal", revised))
    _record_policy_decision(session, _policy_decision(session, "route_change", {"source": "counter", "proposal_id": revised["proposal_id"]}))
    _persist_session(session)
    return {"status": "proposal_revised", "session": _copy_session(session), "proposal": copy.deepcopy(revised)}


def commit_plan(session_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    session = _get_session(session_id)
    _enforce_delegation(session, payload or {}, "commit_plan", ["route_plan", "session_commit"])
    proposal = session.get("proposal") if isinstance(session.get("proposal"), dict) else _plan_for(session)
    commitment = {
        "commitment_id": f"commit_{hashlib.sha1(str(proposal.get('proposal_id')).encode('utf-8')).hexdigest()[:8]}",
        "accepted_proposal_id": proposal.get("proposal_id"),
        "monitoring_scope": ["wait_time_alert", "ride_reroute", "food_safety_notice", "compensation_offer_gate"],
        "requires_user_approval_for": PARK_APPROVAL_GATES,
        "notification": "Notify John with the committed 3-hour family route.",
    }
    session["commitment"] = commitment
    session["state"] = "committed"
    session["updated_at"] = _now_iso()
    session["conversation"].append(_event("client_agent", "commit_request", payload or {"accepted": True}))
    _record_internal_handoff(
        session,
        "guest_experience_agent",
        "commit accepted route and notification",
        {"accepted_proposal_id": commitment["accepted_proposal_id"], "monitoring_scope": commitment["monitoring_scope"]},
        "recommended",
        commitment["notification"],
        "commit",
    )
    session["conversation"].append(_event("park_agent", "commitment", commitment))
    _record_policy_decision(session, _policy_decision(session, "route_change", {"source": "commit", "commitment_id": commitment["commitment_id"]}))
    _persist_session(session)
    return {"status": "committed", "session": _copy_session(session), "commitment": copy.deepcopy(commitment)}


def monitor_session(session_id: str, event: str | dict[str, Any] | None = None, park_state: dict[str, Any] | None = None) -> dict[str, Any]:
    session = _get_session(session_id)
    payload = event if isinstance(event, dict) else {"event": event}
    _enforce_delegation(session, payload, "monitor_session", ["wait_time_alert", "safety_notice"])
    event_name = str(payload.get("event") or "wave_pool_safety_delay")
    mode = _scenario_mode_for_session(session, payload)
    event = event_name
    scenario_monitoring = _scenario_monitoring(mode, event) if mode != "visit_planning" else None
    live_monitoring = (
        _live_monitoring_event(park_state)
        if not scenario_monitoring and isinstance(park_state, dict) and park_state and event in {"live", "wave_pool_safety_delay"}
        else None
    )
    if scenario_monitoring:
        monitoring = scenario_monitoring
    elif live_monitoring:
        monitoring = live_monitoring
    elif event == "wave_pool_safety_delay":
        monitoring = {
            "event": "Wave Pool has a safety delay.",
            "park_agent_offer": "Indoor Surf Simulator plus $5 food credit.",
            "client_agent_counter": "My user values time more than credit. Any VIP queue alternative?",
            "park_agent_revision": "Priority access to Lazy River in 25 minutes.",
            "accepted_resolution": "Accepted. Notify user.",
            "policy_gate": {
                "food_credit": "user_approval_required_before_acceptance",
                "priority_access": "agent_allowed_with_notification",
                "safety_delay": "cannot_override",
            },
        }
    else:
        monitoring = {
            "event": event,
            "park_agent_offer": "Continue monitoring; no reroute required.",
            "accepted_resolution": "No change.",
            "policy_gate": {"status": "informational"},
        }
    session["monitoring"] = monitoring
    session["state"] = "monitoring"
    session["updated_at"] = _now_iso()
    _record_monitoring_handoffs(session, monitoring, "monitor")
    session["conversation"].append(_event("park_agent", "monitoring_event", monitoring))
    policy_actions = {
        "food_credit": "compensation_offer",
        "shared_route_plan": "route_change",
        "safety_delay": "safety_notice",
    }
    policy_gate = _as_dict(monitoring.get("policy_gate"))
    scenario_actions = {policy_actions.get(action, action) for action in policy_gate}
    known_actions = {"compensation_offer", "compensation_settlement", "food_recommendation", "health_data_sharing", "identity_sensitive_action", "medical_escalation", "priority_access", "refund_acceptance", "route_change", "safety_notice"}
    if event in {"wave_pool_safety_delay", "live"} or mode != "visit_planning":
        for action in sorted((scenario_actions & known_actions) | {"safety_notice"}):
            _record_policy_decision(session, _policy_decision(session, action, {"source": "monitor", "event": event, "scenario_mode": mode}))
    else:
        _record_policy_decision(session, _policy_decision(session, "safety_notice", {"source": "monitor", "event": event, "scenario_mode": mode}))
    _persist_session(session)
    return {"status": "monitoring", "session": _copy_session(session), "monitoring": copy.deepcopy(monitoring)}


def escalate_session(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    session = _get_session(session_id)
    _enforce_delegation(session, payload, "escalate_session", ["safety_notice"])
    escalation = {
        "status": "escalated",
        "reason": str(payload.get("reason") or "User approval or park operator review required."),
        "approval_required_for": str(payload.get("approval_required_for") or payload.get("approvalRequiredFor") or "identity-sensitive action"),
        "handoff": "operator_review_queue",
    }
    session["state"] = "escalated"
    session["updated_at"] = _now_iso()
    session["conversation"].append(_event("park_agent", "escalation", escalation))
    _record_policy_decision(session, _policy_decision(session, escalation["approval_required_for"], {"source": "escalation"}))
    _persist_session(session)
    return {"status": "escalated", "session": _copy_session(session), "escalation": escalation}


def close_session(session_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    session = _get_session(session_id)
    _enforce_delegation(session, payload or {}, "close_session", ["route_plan"])
    closing = {
        "status": "closed",
        "outcome": (payload or {}).get("outcome") or "family route committed and monitored",
        "memory_policy": "Store only delegated session preferences, proposal tradeoffs, and aggregate outcome signals.",
    }
    session["state"] = "closed"
    session["updated_at"] = _now_iso()
    session["conversation"].append(_event("park_agent", "session_closed", closing))
    _persist_session(session)
    return {"status": "closed", "session": _copy_session(session), "closing": closing}


def get_session(session_id: str) -> dict[str, Any]:
    return {"status": "found", "session": _copy_session(_get_session(session_id))}


def _scenario_eval_token() -> dict[str, Any]:
    return issue_delegation_token(
        {
            "subject": "guest_user_123",
            "agent_id": "john_personal_agent",
            "scope": DEFAULT_DELEGATION_SCOPES,
            "cannot_do": ["auto_purchase", "share_health_data", "accept_refund_without_user"],
            "ttl_seconds": 600,
        }
    )["token"]


def _scenario_eval_capability_payload(token: dict[str, Any]) -> dict[str, Any]:
    return {
        "can_share": ["location", "party_size", "preferences", "accessibility_needs", "budget", "ride_preference"],
        "can_receive": ["route_plan", "wait_time_alert", "food_recommendation", "safety_notice", "compensation_offer"],
        "cannot_do": ["auto_purchase", "share_health_data", "accept_refund_without_user"],
        "delegation_token": token,
    }


def _evaluate_protocol_scenario(mode: str) -> dict[str, Any]:
    scenario = _protocol_scenario(mode)
    if not scenario:
        raise KeyError(f"Unknown protocol scenario: {mode}")
    run = _as_dict(scenario.get("run"))
    token = _scenario_eval_token()
    identity = identity_handshake(
        {
            "agent_id": "john_personal_agent",
            "represents": "guest_user_123",
            "proof": "signed_token",
            "requested_session": f"scenario_eval_{mode}_{time.time_ns()}",
            "delegation_token": token,
        }
    )
    session_id = identity["session"]["session_id"]
    capability = capability_handshake(session_id, _scenario_eval_capability_payload(token))
    intent_handshake(
        session_id,
        {
            "goal": run.get("goal") or "evaluate_protocol_scenario",
            "time_window": "3_hours",
            "constraints": run.get("constraints") or {"scenario_mode": mode},
            "scenario_mode": mode,
            "delegation_token": token,
        },
    )
    proposed = propose_plan(session_id, {"planner": run.get("planner") or mode, "horizon": "3_hours", "scenario_mode": mode, "delegation_token": token})
    revised = counter_proposal(
        session_id,
        {
            "counter_request": run.get("counter_request") or "scenario eval counterproposal",
            "priority_change": run.get("priority_change") or {},
            "scenario_mode": mode,
            "delegation_token": token,
        },
    )
    commit_plan(session_id, {"accepted": True, "notify_user": True, "delegation_token": token})
    monitored = monitor_session(session_id, {"event": run.get("monitor_event") or "live", "scenario_mode": mode, "delegation_token": token})
    commerce = commerce_agent_evaluate(
        session_id,
        {
            "action": run.get("commerce_action") or "payment",
            "amount": 42,
            "reason": run.get("commerce_reason") or f"{mode} commerce boundary probe.",
            "scenario_mode": mode,
            "delegation_token": token,
        },
    )
    queue = queue_agent_reroute(
        session_id,
        {
            "walking_priority": _as_dict(run.get("priority_change")).get("walking_distance") or "highest",
            "reason": run.get("queue_reason") or f"{mode} queue reroute probe.",
            "scenario_mode": mode,
            "delegation_token": token,
        },
    )
    session = _get_session(session_id)
    expected_handoffs = set(_as_list(scenario.get("handoffs")))
    observed_handoffs = {str(handoff.get("internal_agent_id") or "") for handoff in _as_list(session.get("internal_handoffs")) if isinstance(handoff, dict)}
    proposal = _as_dict(proposed.get("proposal"))
    revised_proposal = _as_dict(revised.get("proposal"))
    monitoring = _as_dict(monitored.get("monitoring"))
    monitoring_evidence = _as_dict(monitoring.get("state_evidence"))
    commerce_decision = _as_dict(commerce.get("decision"))
    queue_proposal = _as_dict(queue.get("proposal"))
    commerce_action = str(run.get("commerce_action") or "payment")
    criteria = {
        "identity_trust_passed": _as_dict(identity.get("case_evaluation")).get("status") == "passed",
        "capability_scope_passed": _as_dict(capability.get("case_evaluation")).get("status") == "passed",
        "proposal_mode_matches": proposal.get("scenario_mode") == mode,
        "proposal_has_plan": bool(_as_list(proposal.get("plan"))),
        "counter_mode_matches": revised_proposal.get("scenario_mode") == mode,
        "monitor_recorded": bool(monitoring.get("event")),
        "monitor_mode_matches": mode == "visit_planning" or monitoring_evidence.get("scenario_mode") == mode,
        "commerce_boundary_checked": commerce_decision.get("action") == commerce_action and commerce_decision.get("allowed") is False,
        "queue_recommended": queue.get("status") == "recommended" and queue_proposal.get("scenario_mode") == mode,
        "expected_handoffs_seen": expected_handoffs.issubset(observed_handoffs),
    }
    evaluation = _record_case_evaluation(
        session,
        _case_evaluation(
            f"protocol_scenario_{mode}",
            criteria,
            {
                "scenario_mode": mode,
                "session_id": session_id,
                "proposal_id": proposal.get("proposal_id"),
                "queue_proposal_id": queue_proposal.get("proposal_id"),
                "monitor_event": monitoring.get("event"),
                "commerce_action": commerce_action,
                "observed_handoffs": sorted(observed_handoffs),
                "expected_handoffs": sorted(expected_handoffs),
            },
        ),
        persist=True,
    )
    return {
        "scenario_id": mode,
        "mode": scenario.get("mode") or mode,
        "session_id": session_id,
        "status": evaluation["status"],
        "score": evaluation["score"],
        "evaluation": copy.deepcopy(evaluation),
        "proposal": copy.deepcopy(proposal),
        "monitoring": copy.deepcopy(monitoring),
        "commerce_decision": copy.deepcopy(commerce_decision),
        "queue_proposal": copy.deepcopy(queue_proposal),
        "expected_handoffs": sorted(expected_handoffs),
        "observed_handoffs": sorted(observed_handoffs),
    }


def run_agent_handshake_scenario_evaluations(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    catalog = _protocol_scenario_catalog_raw()
    requested = _as_list(payload.get("scenarios") or payload.get("scenario_ids") or payload.get("scenarioIds"))
    scenario_ids = [str(item) for item in requested if str(item) in catalog] if requested else sorted(catalog.keys())
    results = [_evaluate_protocol_scenario(scenario_id) for scenario_id in scenario_ids]
    passed = [result for result in results if result["status"] == "passed"]
    average = sum(float(result["score"]) for result in results) / len(results) if results else 0
    return {
        "status": "passed" if results and len(passed) == len(results) else "failed",
        "mode": "agent_handshake_protocol_scenario_eval",
        "protocol_version": "parkpulse-ahp-0.1",
        "scenario_count": len(results),
        "passed": len(passed),
        "average_score": average,
        "catalog_source": os.getenv("PARKPULSE_AHP_SCENARIO_CATALOG", "").strip() or "built_in",
        "results": results,
    }


def demo_handshake(park_state: dict[str, Any] | None = None) -> dict[str, Any]:
    identity = identity_handshake(
        {
            "agent_id": "john_personal_agent",
            "represents": "guest_user_123",
            "proof": "signed_token",
            "requested_session": "park_visit_2026_06_01",
        }
    )
    session_id = identity["session"]["session_id"]
    capability = capability_handshake(
        session_id,
        {
            "can_share": ["location", "party_size", "preferences", "accessibility_needs", "budget", "ride_preference"],
            "can_receive": ["route_plan", "wait_time_alert", "food_recommendation", "safety_notice", "compensation_offer"],
            "cannot_do": ["auto_purchase", "share_health_data", "accept_refund_without_user"],
        },
    )
    intent = intent_handshake(
        session_id,
        {
            "goal": "maximize_family_satisfaction",
            "time_window": "3_hours",
            "constraints": {"children": 2, "avoid_wait_over_minutes": 35, "avoid_thrill_rides": True, "food_allergy": "peanut"},
        },
    )
    proposal = propose_plan(session_id, park_state=park_state)
    counter = counter_proposal(
        session_id,
        {"counter_request": "reduce walking distance", "priority_change": {"walking_distance": "highest", "wait_time": "medium"}},
        park_state=park_state,
    )
    commitment = commit_plan(session_id, {"accepted": True, "notify_user": True})
    monitoring = monitor_session(session_id, "live" if park_state else None, park_state=park_state)
    return {
        "status": "demo_complete",
        "mode": "agent_to_agent_negotiation",
        "session_id": session_id,
        "steps": [identity, capability, intent, proposal, counter, commitment, monitoring],
        "session": get_session(session_id)["session"],
    }
