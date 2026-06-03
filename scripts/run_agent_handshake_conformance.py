#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


FULL_SCOPE = [
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
    "session_commit",
]


@dataclass
class ApiResult:
    status_code: int
    payload: dict[str, Any]


class ConformanceFailure(RuntimeError):
    pass


def post_json(api: str, path: str, body: dict[str, Any], expected_status: int = 200, headers: dict[str, str] | None = None) -> ApiResult:
    request = Request(
        f"{api.rstrip('/')}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urlopen(request, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
            result = ApiResult(response.status, payload)
    except HTTPError as error:
        payload = json.loads(error.read().decode("utf-8") or "{}")
        result = ApiResult(error.code, payload)
    except URLError as error:
        raise ConformanceFailure(f"Unable to reach {api}{path}: {error}") from error

    if result.status_code != expected_status:
        raise ConformanceFailure(f"{path} returned {result.status_code}, expected {expected_status}: {result.payload}")
    return result


def get_json(api: str, path: str, expected_status: int = 200, headers: dict[str, str] | None = None) -> ApiResult:
    request = Request(f"{api.rstrip('/')}{path}", headers={"accept": "application/json", **(headers or {})}, method="GET")
    try:
        with urlopen(request, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
            result = ApiResult(response.status, payload)
    except HTTPError as error:
        payload = json.loads(error.read().decode("utf-8") or "{}")
        result = ApiResult(error.code, payload)
    except URLError as error:
        raise ConformanceFailure(f"Unable to reach {api}{path}: {error}") from error

    if result.status_code != expected_status:
        raise ConformanceFailure(f"{path} returned {result.status_code}, expected {expected_status}: {result.payload}")
    return result


def admin_headers(api: str, external_admin_email: str | None = None) -> dict[str, str]:
    if external_admin_email:
        return {
            "x-goog-authenticated-user-email": f"accounts.google.com:{external_admin_email}",
            "x-parkpulse-verified-email": external_admin_email,
            "x-firebase-auth-user-email": external_admin_email,
        }
    issued = post_json(api, "/api/park/auth/dev-session", {"role": "ml_ops_admin", "subject": "agent-handshake-conformance"}).payload
    token = str(issued.get("token") or "")
    if not token:
        raise ConformanceFailure(f"Dev role session issuer did not return a token: {issued}")
    return {"x-parkpulse-role-token": token}


def role_headers(api: str, role: str, subject: str) -> dict[str, str]:
    issued = post_json(api, "/api/park/auth/dev-session", {"role": role, "subject": subject}).payload
    token = str(issued.get("token") or "")
    if not token:
        raise ConformanceFailure(f"Dev role session issuer did not return a token for {role}: {issued}")
    return {"x-parkpulse-role-token": token}


def assert_case(payload: dict[str, Any], case: str) -> dict[str, Any]:
    evaluation = payload.get("case_evaluation")
    if not isinstance(evaluation, dict):
        raise ConformanceFailure(f"{case} response did not include case_evaluation")
    if evaluation.get("case") != case or evaluation.get("status") != "passed":
        raise ConformanceFailure(f"{case} did not pass: {evaluation}")
    return evaluation


def run_happy_path(api: str) -> dict[str, Any]:
    issued = post_json(
        api,
        "/api/park/delegation-token",
        {
            "subject": "guest_user_123",
            "agent_id": "john_personal_agent",
            "scope": FULL_SCOPE,
            "cannot_do": ["auto_purchase", "share_health_data", "accept_refund_without_user"],
            "ttl_seconds": 600,
        },
    ).payload
    token = issued["token"]

    identity = post_json(
        api,
        "/api/park/handshake",
        {
            "agent_id": "john_personal_agent",
            "represents": "guest_user_123",
            "proof": "signed_token",
            "requested_session": f"conformance_{int(time.time())}",
            "delegation_token": token,
        },
    ).payload
    identity_eval = assert_case(identity, "identity_trust")
    session_id = identity["session"]["session_id"]

    capability = post_json(
        api,
        f"/api/park/session/{session_id}/capabilities",
        {
            "can_share": ["location", "party_size", "preferences", "accessibility_needs", "budget", "ride_preference"],
            "can_receive": ["route_plan", "wait_time_alert", "food_recommendation", "safety_notice", "compensation_offer"],
            "cannot_do": ["auto_purchase", "share_health_data", "accept_refund_without_user"],
            "delegation_token": token,
        },
    ).payload
    capability_eval = assert_case(capability, "capability_scope")

    post_json(
        api,
        f"/api/park/session/{session_id}/intent",
        {
            "goal": "maximize_family_satisfaction",
            "time_window": "3_hours",
            "constraints": {"children": 2, "avoid_wait_over_minutes": 35, "avoid_thrill_rides": True, "food_allergy": "peanut"},
            "delegation_token": token,
        },
    )
    post_json(api, f"/api/park/session/{session_id}/propose", {"planner": "live_state", "horizon": "3_hours", "delegation_token": token})
    post_json(
        api,
        f"/api/park/session/{session_id}/counter",
        {"counter_request": "reduce walking distance", "priority_change": {"walking_distance": "highest", "wait_time": "medium"}, "delegation_token": token},
    )
    post_json(api, f"/api/park/session/{session_id}/commit", {"accepted": True, "notify_user": True, "delegation_token": token})
    post_json(api, f"/api/park/session/{session_id}/monitor", {"event": "live", "delegation_token": token})

    commerce = post_json(
        api,
        "/api/park/internal-agents/commerce/evaluate",
        {"session_id": session_id, "action": "payment", "amount": 42, "reason": "Conformance payment probe.", "delegation_token": token},
    ).payload
    commerce_eval = assert_case(commerce, "commerce_payment_probe")
    if commerce.get("status") != "blocked":
        raise ConformanceFailure(f"Commerce probe must be blocked, got {commerce.get('status')}")

    queue = post_json(
        api,
        "/api/park/internal-agents/queue/reroute",
        {"session_id": session_id, "walking_priority": "highest", "reason": "Conformance reroute probe.", "delegation_token": token},
    ).payload
    queue_eval = assert_case(queue, "queue_reroute")
    if queue.get("status") != "recommended":
        raise ConformanceFailure(f"Queue reroute must be recommended, got {queue.get('status')}")

    return {
        "session_id": session_id,
        "cases": {
            "identity_trust": identity_eval,
            "capability_scope": capability_eval,
            "commerce_payment_probe": commerce_eval,
            "queue_reroute": queue_eval,
        },
    }


def run_rejection_case(api: str) -> dict[str, Any]:
    issued = post_json(
        api,
        "/api/park/delegation-token",
        {
            "subject": "guest_user_123",
            "agent_id": "john_personal_agent",
            "scope": ["location", "party_size", "preferences"],
            "cannot_do": ["auto_purchase"],
            "ttl_seconds": 600,
        },
    ).payload
    token = issued["token"]
    identity = post_json(
        api,
        "/api/park/handshake",
        {
            "agent_id": "john_personal_agent",
            "represents": "guest_user_123",
            "proof": "signed_token",
            "requested_session": f"conformance_rejected_{int(time.time())}",
            "delegation_token": token,
        },
    ).payload
    session_id = identity["session"]["session_id"]
    rejected = post_json(
        api,
        f"/api/park/session/{session_id}/capabilities",
        {
            "can_share": ["location", "party_size", "preferences"],
            "can_receive": ["route_plan", "wait_time_alert"],
            "cannot_do": ["auto_purchase"],
            "delegation_token": token,
        },
        expected_status=403,
    )
    return {"session_id": session_id, "http_status": rejected.status_code, "status": rejected.payload.get("status")}


def run_onboarding_case(api: str, external_admin_email: str | None = None) -> dict[str, Any]:
    agent_id = f"conformance_certified_agent_{int(time.time())}"
    issuer = get_json(api, "/api/park/agent-onboarding/issuer").payload
    post_json(
        api,
        "/api/park/agent-onboarding/register",
        {
            "agent_id": agent_id,
            "display_name": "Conformance Certified Agent",
            "partner_id": "conformance_partner",
            "partner_name": "Conformance Partner",
            "requested_scopes": FULL_SCOPE,
            "cannot_do": ["auto_purchase", "share_health_data", "accept_refund_without_user"],
            "use_case": "guest_route_planning",
        },
    )
    certified = post_json(api, f"/api/park/agent-onboarding/{agent_id}/certify", {}).payload
    if certified.get("status") != "approved":
        raise ConformanceFailure(f"Onboarding certification should approve full-scope agent: {certified}")
    credential = certified["certification"].get("credential")
    if not credential:
        raise ConformanceFailure("Approved onboarding did not return a certification credential.")
    if credential.get("kid") != issuer.get("signing", {}).get("kid"):
        raise ConformanceFailure(f"Certification credential kid does not match issuer metadata: {credential.get('kid')} vs {issuer}")
    verified = post_json(api, "/api/park/agent-onboarding/verify-credential", {"credential": credential}).payload
    if verified.get("status") != "verified":
        raise ConformanceFailure(f"Certification credential did not verify: {verified}")
    tampered = {**credential, "approval": "blocked_until_scope_fixed"}
    tampered_result = post_json(api, "/api/park/agent-onboarding/verify-credential", {"credential": tampered}).payload
    if tampered_result.get("status") != "rejected":
        raise ConformanceFailure(f"Tampered certification credential should be rejected: {tampered_result}")
    revoked = post_json(api, "/api/park/agent-onboarding/revoke-credential", {"credential": credential, "reason": "conformance_revocation_probe"}, headers=admin_headers(api, external_admin_email)).payload
    if revoked.get("status") != "revoked":
        raise ConformanceFailure(f"Certification credential revocation failed: {revoked}")
    revoked_result = post_json(api, "/api/park/agent-onboarding/verify-credential", {"credential": credential}).payload
    if revoked_result.get("status") != "rejected" or "revoked" not in str(revoked_result.get("reason", "")).lower():
        raise ConformanceFailure(f"Revoked certification credential should be rejected: {revoked_result}")
    return {
        "agent_id": agent_id,
        "status": certified["status"],
        "approval": certified["agent"]["approval"],
        "score": certified["certification"]["score"],
        "issuer_kid": issuer.get("signing", {}).get("kid"),
        "credential_status": verified["status"],
        "tampered_status": tampered_result["status"],
        "revoked_status": revoked_result["status"],
    }


def run_trust_admin_gate_case(api: str, external_admin_email: str | None = None) -> dict[str, Any]:
    public_status = get_json(api, "/api/park/agent-trust/status").status_code
    unauth_keys = get_json(api, "/api/park/agent-trust/keys", expected_status=401).status_code
    if external_admin_email:
        external_unmapped = get_json(api, "/api/park/agent-trust/keys", expected_status=401, headers={"x-goog-authenticated-user-email": "accounts.google.com:viewer@example.com"}).status_code
        external_admin = get_json(api, "/api/park/agent-trust/keys", headers={"x-goog-authenticated-user-email": f"accounts.google.com:{external_admin_email}"}).status_code
        if public_status != 200 or unauth_keys != 401 or external_unmapped != 401 or external_admin != 200:
            raise ConformanceFailure(f"External trust admin role gate failed: public={public_status}, unauth={unauth_keys}, unmapped={external_unmapped}, admin={external_admin}")
        return {"public_status": public_status, "unauthenticated_keys": unauth_keys, "external_unmapped_keys": external_unmapped, "external_admin_keys": external_admin}
    ops_keys = get_json(api, "/api/park/agent-trust/keys", expected_status=403, headers=role_headers(api, "ops_team", "conformance-ops")).status_code
    admin_keys = get_json(api, "/api/park/agent-trust/keys", headers=role_headers(api, "ml_ops_admin", "conformance-admin")).status_code
    if public_status != 200 or unauth_keys != 401 or ops_keys != 403 or admin_keys != 200:
        raise ConformanceFailure(f"Trust admin role gate failed: public={public_status}, unauth={unauth_keys}, ops={ops_keys}, admin={admin_keys}")
    return {"public_status": public_status, "unauthenticated_keys": unauth_keys, "ops_team_keys": ops_keys, "ml_ops_admin_keys": admin_keys}


def run_auth_readiness_case(api: str, external_admin_email: str | None = None) -> dict[str, Any]:
    status = get_json(api, "/api/park/agent-trust/status").payload
    boundary = status.get("auth_boundary") if isinstance(status.get("auth_boundary"), dict) else {}
    result = {
        "status_endpoint": "ready" if boundary else "missing",
        "production_ready": bool(boundary.get("production_ready")),
        "external_identity_ready": bool(boundary.get("external_identity_ready")),
        "dev_role_issuer_enabled": bool(boundary.get("dev_role_issuer_enabled")),
        "signed_role_required": bool(boundary.get("signed_role_required")),
    }
    if external_admin_email:
        external = get_json(
            api,
            "/api/park/agent-trust/keys",
            headers={
                "x-goog-authenticated-user-email": f"accounts.google.com:{external_admin_email}",
                "x-parkpulse-verified-email": external_admin_email,
                "x-firebase-auth-user-email": external_admin_email,
            },
            expected_status=200,
        )
        result["external_admin_keys"] = external.status_code
    return result


def run_scenario_eval_case(api: str) -> dict[str, Any]:
    catalog = get_json(api, "/api/park/agent-handshake/scenarios").payload
    scenario_ids = [str(item.get("id")) for item in catalog.get("scenarios", []) if isinstance(item, dict) and item.get("id")]
    if not scenario_ids:
        raise ConformanceFailure(f"Scenario catalog did not expose any scenarios: {catalog}")
    evaluated = post_json(api, "/api/park/agent-handshake/scenario-eval", {"scenarios": scenario_ids}).payload
    if evaluated.get("status") != "passed":
        raise ConformanceFailure(f"Protocol scenario eval failed: {evaluated}")
    result_ids = [str(item.get("scenario_id")) for item in evaluated.get("results", []) if isinstance(item, dict)]
    missing = sorted(set(scenario_ids) - set(result_ids))
    if missing:
        raise ConformanceFailure(f"Protocol scenario eval missed scenarios: {missing}")
    failed = [item for item in evaluated.get("results", []) if isinstance(item, dict) and item.get("status") != "passed"]
    if failed:
        raise ConformanceFailure(f"Protocol scenario eval returned failed cases: {failed}")
    return {
        "status": evaluated["status"],
        "scenario_count": evaluated["scenario_count"],
        "passed": evaluated["passed"],
        "average_score": evaluated["average_score"],
        "scenario_ids": result_ids,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ParkPulse Agent Handshake Protocol conformance checks.")
    parser.add_argument("--api", default="http://127.0.0.1:8001", help="ParkPulse API base URL.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON only.")
    parser.add_argument("--external-admin-email", default=os.getenv("PARKPULSE_CONFORMANCE_EXTERNAL_ADMIN_EMAIL", ""), help="Optional upstream-verified admin email to prove production-style external identity headers.")
    args = parser.parse_args()

    try:
        happy = run_happy_path(args.api)
        rejected = run_rejection_case(args.api)
        onboarding = run_onboarding_case(args.api, args.external_admin_email or None)
        trust_admin = run_trust_admin_gate_case(args.api, args.external_admin_email or None)
        auth_readiness = run_auth_readiness_case(args.api, args.external_admin_email or None)
        scenario_eval = run_scenario_eval_case(args.api)
        result = {
            "status": "passed",
            "api": args.api,
            "happy_path": happy,
            "rejection_case": rejected,
            "onboarding_case": onboarding,
            "trust_admin_gate": trust_admin,
            "auth_readiness": auth_readiness,
            "scenario_eval": scenario_eval,
            "summary": {
                "required_cases_passed": ["identity_trust", "capability_scope", "commerce_payment_probe", "queue_reroute"],
                "protocol_scenarios_passed": scenario_eval["passed"] == scenario_eval["scenario_count"],
                "under_scoped_capability_rejected": rejected["http_status"] == 403,
                "certification_credential_verified": onboarding["credential_status"] == "verified",
                "certification_revocation_enforced": onboarding["revoked_status"] == "rejected",
                "trust_admin_gate_enforced": trust_admin["unauthenticated_keys"] == 401
                and (
                    (trust_admin.get("ops_team_keys") == 403 and trust_admin.get("ml_ops_admin_keys") == 200)
                    or (trust_admin.get("external_unmapped_keys") == 401 and trust_admin.get("external_admin_keys") == 200)
                ),
                "auth_readiness_exposed": auth_readiness["status_endpoint"] == "ready",
            },
        }
    except ConformanceFailure as error:
        result = {"status": "failed", "api": args.api, "error": str(error)}

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"ParkPulse AHP conformance: {result['status']}")
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
