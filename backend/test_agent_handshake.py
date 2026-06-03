from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_handshake as ah  # noqa: E402
from park_role_access import authorize_role_action, identity_provider_readiness, verify_external_role_identity  # noqa: E402
from agent_handshake import (  # noqa: E402
    _agent_onboardings,
    _credential_revocations,
    _partner_registry,
    _sessions,
    agent_handshake_scenario_catalog,
    capability_handshake,
    certify_agent_onboarding,
    certification_issuer_metadata,
    commerce_agent_evaluate,
    commit_plan,
    counter_proposal,
    get_session,
    identity_handshake,
    intent_handshake,
    issue_delegation_token,
    monitor_session,
    propose_plan,
    queue_agent_reroute,
    register_agent_onboarding,
    revoke_agent_certification_credential,
    rotate_agent_certification_key,
    run_agent_handshake_scenario_evaluations,
    agent_trust_registry_status,
    list_agent_trust_audit_events,
    list_agent_trust_keys,
    list_agent_trust_partners,
    list_agent_credential_revocations,
    upsert_agent_trust_partner,
    verify_agent_certification_credential,
)


def _full_delegation_token():
    return issue_delegation_token(
        {
            "subject": "guest_user_123",
            "agent_id": "john_personal_agent",
            "scope": [
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
            ],
            "cannot_do": ["auto_purchase", "share_health_data", "accept_refund_without_user"],
            "ttl_seconds": 600,
        }
    )["token"]


def test_external_agent_contract_conformance_happy_path():
    token = _full_delegation_token()
    identity = identity_handshake(
        {
            "agent_id": "john_personal_agent",
            "represents": "guest_user_123",
            "proof": "signed_token",
            "requested_session": "conformance_happy_path",
            "delegation_token": token,
        }
    )
    session_id = identity["session"]["session_id"]
    assert identity["case_evaluation"]["case"] == "identity_trust"
    assert identity["case_evaluation"]["status"] == "passed"

    scoped = capability_handshake(
        session_id,
        {
            "can_share": ["location", "party_size", "preferences", "accessibility_needs", "budget", "ride_preference"],
            "can_receive": ["route_plan", "wait_time_alert", "food_recommendation", "safety_notice", "compensation_offer"],
            "cannot_do": ["auto_purchase", "share_health_data", "accept_refund_without_user"],
            "delegation_token": token,
        },
    )
    assert scoped["session"]["state"] == "scoped"
    assert scoped["case_evaluation"]["case"] == "capability_scope"
    assert scoped["case_evaluation"]["status"] == "passed"

    intent = intent_handshake(
        session_id,
        {
            "goal": "maximize_family_satisfaction",
            "time_window": "3_hours",
            "constraints": {"children": 2, "avoid_wait_over_minutes": 35, "avoid_thrill_rides": True, "food_allergy": "peanut"},
            "delegation_token": token,
        },
    )
    assert intent["session"]["state"] == "intent_accepted"

    proposed = propose_plan(session_id, {"planner": "contract_conformance", "delegation_token": token})
    revised = counter_proposal(
        session_id,
        {
            "counter_request": "reduce walking distance",
            "priority_change": {"walking_distance": "highest", "wait_time": "medium"},
            "delegation_token": token,
        },
    )
    assert proposed["proposal"]["proposal_id"] != revised["proposal"]["proposal_id"]

    committed = commit_plan(session_id, {"accepted": True, "delegation_token": token})
    assert committed["session"]["state"] == "committed"

    monitored = monitor_session(session_id, "wave_pool_safety_delay")
    assert monitored["session"]["state"] == "monitoring"

    commerce = commerce_agent_evaluate(
        session_id,
        {"action": "payment", "amount": 42, "reason": "Conformance payment probe.", "delegation_token": token},
    )
    assert commerce["status"] == "blocked"
    assert commerce["case_evaluation"]["case"] == "commerce_payment_probe"
    assert commerce["case_evaluation"]["status"] == "passed"
    assert commerce["internal_agent"]["executed_by"] == "commerce_agent"

    queue = queue_agent_reroute(
        session_id,
        {"walking_priority": "highest", "reason": "Conformance reroute probe.", "delegation_token": token},
    )
    assert queue["status"] == "recommended"
    assert queue["case_evaluation"]["case"] == "queue_reroute"
    assert queue["case_evaluation"]["status"] == "passed"
    assert queue["internal_agent"]["executed_by"] == "queue_agent"

    final_session = get_session(session_id)["session"]
    proven_cases = {evaluation["case"] for evaluation in final_session["case_evaluations"] if evaluation["status"] == "passed"}
    assert {"identity_trust", "capability_scope", "commerce_payment_probe", "queue_reroute"}.issubset(proven_cases)
    assert {handoff["internal_agent_id"] for handoff in final_session["internal_handoffs"]} >= {"commerce_agent", "queue_agent"}
    _sessions.pop(session_id, None)


def test_protocol_extension_scenario_changes_backend_agent_outputs():
    token = _full_delegation_token()
    identity = identity_handshake(
        {
            "agent_id": "john_personal_agent",
            "represents": "guest_user_123",
            "proof": "signed_token",
            "requested_session": "incident_extension_case",
            "delegation_token": token,
        }
    )
    session_id = identity["session"]["session_id"]
    capability_handshake(
        session_id,
        {
            "can_share": ["location", "party_size", "preferences", "accessibility_needs", "budget", "ride_preference"],
            "can_receive": ["route_plan", "wait_time_alert", "food_recommendation", "safety_notice", "compensation_offer"],
            "cannot_do": ["auto_purchase", "share_health_data", "accept_refund_without_user"],
            "delegation_token": token,
        },
    )
    intent_handshake(
        session_id,
        {
            "goal": "protect_family_time_during_incident",
            "scenario_mode": "incident_response",
            "time_window": "3_hours",
            "constraints": {
                "scenario_mode": "incident_response",
                "children": 2,
                "avoid_wait_over_minutes": 35,
                "avoid_thrill_rides": True,
                "food_allergy": "peanut",
            },
            "delegation_token": token,
        },
    )

    proposed = propose_plan(session_id, {"scenario_mode": "incident_response", "planner": "protocol_extension", "delegation_token": token})
    assert proposed["proposal"]["scenario_mode"] == "incident_response"
    assert "Indoor Surf Simulator" in proposed["proposal"]["plan"]
    assert proposed["proposal"]["state_evidence"]["source"] == "scenario_static_plan"

    revised = counter_proposal(
        session_id,
        {
            "scenario_mode": "incident_response",
            "counter_request": "Prioritize time over compensation.",
            "priority_change": {"walking_distance": "medium", "wait_time": "highest"},
            "delegation_token": token,
        },
    )
    assert "incident response" in revised["proposal"]["rationale"]

    monitored = monitor_session(session_id, {"scenario_mode": "incident_response", "event": "wave_pool_safety_delay", "delegation_token": token})
    assert monitored["monitoring"]["state_evidence"]["scenario_mode"] == "incident_response"
    assert monitored["monitoring"]["park_agent_revision"] == "Priority access to Lazy River in 25 minutes."

    queue = queue_agent_reroute(
        session_id,
        {
            "scenario_mode": "incident_response",
            "walking_priority": "highest",
            "reason": "Incident-response route proof.",
            "delegation_token": token,
        },
    )
    assert queue["proposal"]["scenario_mode"] == "incident_response"
    assert "Lazy River priority return" in queue["proposal"]["plan"]

    final_session = get_session(session_id)["session"]
    assert {handoff["internal_agent_id"] for handoff in final_session["internal_handoffs"]} >= {"safety_agent", "queue_agent", "commerce_agent"}
    assert any(decision["action"] == "priority_access" and decision["payload"].get("scenario_mode") == "incident_response" for decision in final_session["policy_decisions"])
    _sessions.pop(session_id, None)


def test_protocol_scenario_catalog_and_all_mode_eval_pass():
    catalog = agent_handshake_scenario_catalog()
    scenario_ids = {item["id"] for item in catalog["scenarios"]}
    assert {"visit_planning", "incident_response", "accessibility_support", "commerce_resolution", "group_coordination"}.issubset(scenario_ids)
    assert catalog["configurable"] is True

    evaluated = run_agent_handshake_scenario_evaluations()
    assert evaluated["status"] == "passed"
    assert evaluated["scenario_count"] == len(scenario_ids)
    assert evaluated["passed"] == evaluated["scenario_count"]
    assert evaluated["average_score"] == 1
    assert {item["scenario_id"] for item in evaluated["results"]} == scenario_ids
    assert all(item["evaluation"]["case"].startswith("protocol_scenario_") for item in evaluated["results"])
    for item in evaluated["results"]:
        _sessions.pop(item["session_id"], None)


def test_external_agent_contract_rejects_under_scoped_client_before_capability_scope():
    token = issue_delegation_token(
        {
            "subject": "guest_user_123",
            "agent_id": "john_personal_agent",
            "scope": ["location", "party_size", "preferences"],
            "cannot_do": ["auto_purchase"],
            "ttl_seconds": 600,
        }
    )["token"]
    identity = identity_handshake(
        {
            "agent_id": "john_personal_agent",
            "represents": "guest_user_123",
            "proof": "signed_token",
            "requested_session": "conformance_rejected_scope",
            "delegation_token": token,
        }
    )
    session_id = identity["session"]["session_id"]

    try:
        capability_handshake(
            session_id,
            {
                "can_share": ["location", "party_size", "preferences"],
                "can_receive": ["route_plan", "wait_time_alert"],
                "cannot_do": ["auto_purchase"],
                "delegation_token": token,
            },
        )
    except PermissionError as error:
        assert "missing required scope" in str(error)
    else:
        raise AssertionError("Under-scoped client agent should not reach capability scope.")

    rejected_session = get_session(session_id)["session"]
    assert rejected_session["state"] == "verified"
    assert rejected_session["delegation"]["last_verification"]["status"] == "rejected"
    assert {"route_plan", "wait_time_alert"}.issubset(set(rejected_session["delegation"]["last_verification"]["missing_scope"]))
    assert any(evaluation["case"] == "delegation_scope_rejection" and evaluation["status"] == "passed" for evaluation in rejected_session["case_evaluations"])
    _sessions.pop(session_id, None)


def test_agent_onboarding_certifies_full_scope_agent_for_guest_route_planning():
    registered = register_agent_onboarding(
        {
            "agent_id": "certified_family_agent",
            "display_name": "Certified Family Agent",
            "partner_id": "partner_family_os",
            "partner_name": "Family OS",
            "requested_scopes": [
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
            ],
            "cannot_do": ["auto_purchase", "share_health_data", "accept_refund_without_user"],
        }
    )
    assert registered["agent"]["status"] == "registered"
    assert registered["agent"]["partner"]["partner_id"] == "partner_family_os"

    certified = certify_agent_onboarding("certified_family_agent")
    assert certified["status"] == "approved"
    assert certified["agent"]["approval"] == "approved_for_guest_route_planning"
    assert certified["certification"]["score"] == 1
    assert set(certified["certification"]["passed_cases"]) >= {"identity_trust", "capability_scope", "commerce_payment_probe", "queue_reroute"}
    assert {"route_plan", "wait_time_alert", "policy_check"}.issubset(set(certified["agent"]["allowed_scopes"]))
    credential = certified["certification"]["credential"]
    assert credential["token_type"] == "parkpulse_agent_certification"
    assert credential["alg"] == "EdDSA"
    assert credential["score_basis_points"] == 10000
    assert credential["kid"] == certification_issuer_metadata()["signing"]["kid"]
    assert credential["jti"] == credential["certification_id"]
    verified = verify_agent_certification_credential({"credential": credential})
    assert verified["status"] == "verified"
    assert verified["agent_id"] == "certified_family_agent"
    assert verified["approval"] == "approved_for_guest_route_planning"
    tampered = {**credential, "approval": "blocked_until_scope_fixed"}
    assert verify_agent_certification_credential({"credential": tampered})["status"] == "rejected"
    revoked = revoke_agent_certification_credential({"credential": credential, "reason": "test_revocation"})
    assert revoked["status"] == "revoked"
    rejected_after_revocation = verify_agent_certification_credential({"credential": credential})
    assert rejected_after_revocation["status"] == "rejected"
    assert rejected_after_revocation["reason"] == "Certification credential has been revoked."
    _credential_revocations.pop(credential["certification_id"], None)
    _agent_onboardings.pop("certified_family_agent", None)


def test_agent_onboarding_blocks_under_scoped_agent_until_scope_fixed():
    register_agent_onboarding(
        {
            "agent_id": "under_scoped_family_agent",
            "display_name": "Under Scoped Family Agent",
            "requested_scopes": ["location", "party_size", "preferences"],
            "cannot_do": ["auto_purchase"],
        }
    )

    certified = certify_agent_onboarding("under_scoped_family_agent")
    assert certified["status"] == "blocked"
    assert certified["agent"]["approval"] == "blocked_until_scope_fixed"
    assert certified["agent"]["allowed_scopes"] == []
    assert certified["certification"]["score"] < 1
    assert certified["certification"]["credential"] is None
    assert certified["certification"]["required_cases"]["capability_scope"]["status"] == "missing"
    assert certified["certification"]["readiness_issues"]
    _agent_onboardings.pop("under_scoped_family_agent", None)


def test_agent_onboarding_blocks_partner_scope_outside_allowlist():
    register_agent_onboarding(
        {
            "agent_id": "restricted_partner_agent",
            "display_name": "Restricted Partner Agent",
            "partner_id": "restricted_partner",
            "partner_name": "Restricted Partner",
            "partner_allowed_scopes": ["location", "party_size", "preferences"],
            "requested_scopes": [
                "location",
                "party_size",
                "preferences",
                "route_plan",
                "wait_time_alert",
                "policy_check",
            ],
            "cannot_do": ["auto_purchase", "share_health_data", "accept_refund_without_user"],
        }
    )

    certified = certify_agent_onboarding("restricted_partner_agent")
    assert certified["status"] == "blocked"
    assert certified["agent"]["scope_request_status"] == "rejected"
    assert "route_plan" in certified["certification"]["partner_disallowed_scopes"]
    assert any("Partner allowlist" in issue for issue in certified["certification"]["readiness_issues"])
    assert certified["certification"]["credential"] is None
    _agent_onboardings.pop("restricted_partner_agent", None)
    _partner_registry.pop("restricted_partner", None)


def test_agent_trust_registry_admin_persists_partner_revocation_and_key_rotation(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_AGENT_TRUST_DB", str(tmp_path / "agent_trust.db"))
    ah._trust_registry_loaded = False
    _partner_registry.clear()
    _credential_revocations.clear()


def test_agent_trust_management_requires_ml_ops_admin_role():
    admin = authorize_role_action("ml_ops_admin", "manage_agent_trust", resource="agent_trust_key_rotation", default_role="ml_ops_admin")
    ops = authorize_role_action("ops_team", "manage_agent_trust", resource="agent_trust_key_rotation", default_role="ml_ops_admin")
    customer = authorize_role_action("customer", "manage_agent_trust", resource="agent_trust_key_rotation", default_role="ml_ops_admin")
    assert admin["allowed"] is True
    assert ops["allowed"] is False
    assert customer["allowed"] is False


def test_external_identity_headers_map_to_admin_role(monkeypatch):
    monkeypatch.setenv("PARKPULSE_TRUST_GOOGLE_IAP", "1")
    monkeypatch.setenv("PARKPULSE_ADMIN_EMAILS", "admin@example.com")
    identity = verify_external_role_identity({"x-goog-authenticated-user-email": "accounts.google.com:admin@example.com"}, default_role="ops_team")
    assert identity["authenticated"] is True
    assert identity["auth_method"] == "external_google_iap"
    assert identity["role"] == "ml_ops_admin"
    assert identity_provider_readiness()["external_identity_ready"] is True


def test_external_identity_headers_block_unmapped_identity(monkeypatch):
    monkeypatch.setenv("PARKPULSE_TRUST_OIDC_HEADERS", "1")
    monkeypatch.setenv("PARKPULSE_ADMIN_GROUPS", "parkpulse-admins")
    identity = verify_external_role_identity({"x-parkpulse-verified-email": "viewer@example.com", "x-parkpulse-verified-groups": "parkpulse-viewers"}, default_role="ml_ops_admin")
    assert identity["authenticated"] is False
    assert identity["status"] == "role_unmapped"
    assert identity["role"] == "ml_ops_admin"

    status = agent_trust_registry_status()
    assert status["store"]["mode"] == "sqlite_wal"
    assert status["active_key"]["kid"] == certification_issuer_metadata()["signing"]["kid"]

    partner = upsert_agent_trust_partner(
        {
            "partner_id": "admin_approved_partner",
            "partner_name": "Admin Approved Partner",
            "allowed_scopes": ["location", "party_size", "route_plan", "wait_time_alert", "policy_check"],
            "actor": "test_admin",
        }
    )
    assert partner["status"] == "upserted"
    assert any(item["partner_id"] == "admin_approved_partner" for item in list_agent_trust_partners()["partners"])

    original_kid = certification_issuer_metadata()["signing"]["kid"]
    rotated = rotate_agent_certification_key({"version": "v_test_rotation", "actor": "test_admin"})
    assert rotated["status"] == "rotated"
    assert rotated["active_key"]["kid"] != original_kid
    assert certification_issuer_metadata()["signing"]["kid"] == rotated["active_key"]["kid"]
    assert any(key["kid"] == original_kid and key["status"] == "retired" for key in list_agent_trust_keys()["keys"])

    revoked = revoke_agent_certification_credential({"certification_id": "cert_test_admin", "agent_id": "admin_agent", "reason": "admin_test", "revoked_by": "test_admin"})
    assert revoked["status"] == "revoked"
    assert any(item["certification_id"] == "cert_test_admin" for item in list_agent_credential_revocations()["revocations"])
    assert any(event["actor"] == "test_admin" for event in list_agent_trust_audit_events()["events"])

    ah._trust_registry_loaded = False
    _partner_registry.clear()
    _credential_revocations.clear()
