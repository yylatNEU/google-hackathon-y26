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
    _verify_certification_claims,
    agent_handshake_scenario_catalog,
    agent_contract,
    capability_handshake,
    certify_agent_onboarding,
    certification_issuer_metadata,
    commerce_agent_evaluate,
    commit_plan,
    counter_proposal,
    demo_supply_chain_handshake,
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
    run_agent_handshake_policy_challenges,
    session_protocol_receipt,
    agent_trust_registry_status,
    list_agent_trust_audit_events,
    list_agent_trust_keys,
    list_agent_trust_partners,
    list_agent_credential_revocations,
    upsert_agent_trust_partner,
    verify_agent_certification_credential,
    verify_protocol_artifact,
)


def _assert_valid_protocol_signature(artifact: dict, artifact_type: str):
    signature = artifact.get("signature") or {}
    assert signature["artifact_type"] == artifact_type
    assert signature["protocol_version"] == "parkpulse-ahp-0.1"
    assert signature["alg"] == certification_issuer_metadata()["signing"]["alg"]
    assert _verify_certification_claims({key: value for key, value in signature.items() if key != "sig"}, signature["sig"])


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
            "inventory_position",
            "delivery_eta",
            "supplier_compliance",
            "cold_chain_status",
            "parts_availability",
            "demand_forecast",
            "restock_request",
            "dock_slot",
            "substitution_request",
            "purchase_order_notice",
            "maintenance_parts_request",
        ],
            "cannot_do": [
                "auto_purchase",
                "share_health_data",
                "accept_refund_without_user",
                "auto_accept_price_change",
                "bypass_food_safety",
                "release_vendor_payment_without_approval",
            ],
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
    _assert_valid_protocol_signature(catalog, "agent_handshake_scenario_catalog")
    scenario_ids = {item["id"] for item in catalog["scenarios"]}
    assert {
        "visit_planning",
        "incident_response",
        "accessibility_support",
        "commerce_resolution",
        "group_coordination",
        "supply_replenishment",
        "cold_chain_incident",
        "maintenance_parts_shortage",
    }.issubset(scenario_ids)
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


def test_supply_chain_protocol_extension_negotiates_inventory_and_blocks_procurement():
    token = _full_delegation_token()
    identity = identity_handshake(
        {
            "agent_id": "beverage_supplier_agent",
            "represents": "supplier_vendor_42",
            "proof": "signed_token",
            "requested_session": "supply_replenishment_case",
            "delegation_token": issue_delegation_token(
                {
                    "subject": "supplier_vendor_42",
                    "agent_id": "beverage_supplier_agent",
                    "scope": token["scope"],
                    "cannot_do": token["cannot_do"],
                    "ttl_seconds": 600,
                }
            )["token"],
        }
    )
    session_id = identity["session"]["session_id"]
    supplier_token = identity["delegation"]["token"]
    capability_handshake(
        session_id,
        {
            "can_share": ["inventory_position", "delivery_eta", "supplier_compliance", "cold_chain_status"],
            "can_receive": ["demand_forecast", "restock_request", "dock_slot", "substitution_request", "purchase_order_notice"],
            "cannot_do": ["auto_accept_price_change", "bypass_food_safety", "release_vendor_payment_without_approval"],
            "delegation_token": supplier_token,
        },
    )
    intent_handshake(
        session_id,
        {
            "goal": "prevent_inventory_stockout",
            "scenario_mode": "supply_replenishment",
            "time_window": "3_hours",
            "constraints": {"sku": "lemonade", "zone": "Parade Zone", "scenario_mode": "supply_replenishment"},
            "delegation_token": supplier_token,
        },
    )

    proposed = propose_plan(session_id, {"scenario_mode": "supply_replenishment", "planner": "supply_chain_extension", "delegation_token": supplier_token})
    assert proposed["proposal"]["scenario_mode"] == "supply_replenishment"
    assert "Reserve Dock B 14:20 window" in proposed["proposal"]["plan"]

    monitored = monitor_session(session_id, {"scenario_mode": "supply_replenishment", "event": "parade_zone_stockout_risk", "delegation_token": supplier_token})
    assert monitored["monitoring"]["policy_gate"]["price_change_acceptance"] == "approval_required"

    procurement = commerce_agent_evaluate(
        session_id,
        {"action": "purchase_order", "amount": 4200, "reason": "Supplier purchase-order probe.", "delegation_token": supplier_token},
    )
    assert procurement["status"] == "requires_user_approval"
    assert procurement["decision"]["allowed"] is False
    assert procurement["decision"]["requires_user_approval"] is True

    final_session = get_session(session_id)["session"]
    assert {handoff["internal_agent_id"] for handoff in final_session["internal_handoffs"]} >= {"supply_chain_agent", "procurement_agent", "food_agent"}
    assert any(decision["action"] == "restock_request" and decision["allowed"] is True for decision in final_session["policy_decisions"])
    assert any(decision["action"] == "purchase_order" and decision["requires_user_approval"] is True for decision in final_session["policy_decisions"])
    _sessions.pop(session_id, None)


def test_dedicated_supply_chain_handshake_demo_uses_supplier_scopes_and_signed_receipt():
    demo = demo_supply_chain_handshake("cold_chain_incident")
    assert demo["status"] == "demo_complete"
    assert demo["mode"] == "supply_chain_agent_handshake"
    assert demo["scenario_mode"] == "cold_chain_incident"
    receipt = demo["receipt"]
    _assert_valid_protocol_signature(receipt, "agent_handshake_session_receipt")
    assert receipt["accepted_plan"]["proposal_id"]
    assert "cold_chain_status" in set(receipt["delegation_scope"])
    assert "route_plan" not in set(receipt["delegation_scope"])
    session = demo["session"]
    assert session["client_agent"]["agent_id"] == "cold_chain_supplier_agent"
    assert {handoff["internal_agent_id"] for handoff in session["internal_handoffs"]} >= {"supply_chain_agent", "procurement_agent", "safety_agent", "food_agent"}
    assert any(decision["action"] == "bypass_food_safety" and decision["allowed"] is False for decision in session["policy_decisions"])
    assert any(decision["action"] == "vendor_payment_release" and decision["requires_user_approval"] is True for decision in session["policy_decisions"])
    _sessions.pop(demo["session_id"], None)


def test_agent_contract_policy_challenges_and_receipt_are_signed():
    contract = agent_contract()
    _assert_valid_protocol_signature(contract, "agent_contract")
    _assert_valid_protocol_signature(contract["scenario_catalog"], "agent_handshake_scenario_catalog")
    assert "POST /api/park/agent-handshake/policy-challenges" in contract["routes"]
    assert "POST /api/park/agent-handshake/verify-artifact" in contract["routes"]
    assert "GET /api/park/session/{session_id}/receipt" in contract["routes"]
    verified_contract = verify_protocol_artifact({"artifact": contract, "expected_artifact_type": "agent_contract"})
    assert verified_contract["status"] == "verified"
    assert verified_contract["digest_status"] == "valid"
    assert verified_contract["signature_status"] == "valid"

    challenges = run_agent_handshake_policy_challenges({"actions": ["payment", "health_data_sharing", "override_safety_delay"]})
    _assert_valid_protocol_signature(challenges, "agent_handshake_policy_challenges")
    assert challenges["status"] == "passed"
    assert challenges["passed"] == 3
    assert all(result["allowed"] is False and result["requires_user_approval"] is True for result in challenges["results"])
    signed_challenges = {key: value for key, value in challenges.items() if key != "session"}
    assert verify_protocol_artifact({"artifact": signed_challenges, "expected_artifact_type": "agent_handshake_policy_challenges"})["status"] == "verified"
    _sessions.pop(challenges["session_id"], None)

    token = _full_delegation_token()
    identity = identity_handshake(
        {
            "agent_id": "john_personal_agent",
            "represents": "guest_user_123",
            "proof": "signed_token",
            "requested_session": "signed_receipt_case",
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
    intent_handshake(session_id, {"goal": "signed_receipt", "time_window": "3_hours", "constraints": {"children": 2}, "delegation_token": token})
    propose_plan(session_id, {"planner": "receipt_test", "delegation_token": token})
    commit_plan(session_id, {"accepted": True, "delegation_token": token})
    commerce_agent_evaluate(session_id, {"action": "payment", "amount": 42, "reason": "Receipt proof.", "delegation_token": token})

    receipt_payload = session_protocol_receipt(session_id, {"delegation_token": token})
    receipt = receipt_payload["receipt"]
    _assert_valid_protocol_signature(receipt, "agent_handshake_session_receipt")
    assert receipt["session_id"] == session_id
    assert receipt["policy_gates_triggered"]
    assert receipt["conversation_digest"]
    assert verify_protocol_artifact({"artifact": receipt, "expected_artifact_type": "agent_handshake_session_receipt"})["status"] == "verified"
    wrong_type = verify_protocol_artifact({"artifact": receipt, "expected_artifact_type": "agent_contract"})
    assert wrong_type["status"] == "rejected"
    assert "artifact_type_mismatch" in wrong_type["failures"]
    tampered = {**receipt, "final_status": "tampered"}
    rejected_tampered = verify_protocol_artifact({"artifact": tampered, "expected_artifact_type": "agent_handshake_session_receipt"})
    assert rejected_tampered["status"] == "rejected"
    assert "sha256_mismatch" in rejected_tampered["failures"]
    _sessions.pop(session_id, None)


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


def test_agent_onboarding_certifies_supplier_agent_for_supply_chain_coordination():
    supplier_scopes = [
        "inventory_position",
        "delivery_eta",
        "supplier_compliance",
        "cold_chain_status",
        "parts_availability",
        "demand_forecast",
        "restock_request",
        "dock_slot",
        "substitution_request",
        "purchase_order_notice",
        "maintenance_parts_request",
        "safety_notice",
        "policy_check",
        "session_commit",
    ]
    registered = register_agent_onboarding(
        {
            "agent_id": "certified_supplier_agent",
            "display_name": "Certified Supplier Agent",
            "partner_id": "partner_supplier_os",
            "partner_name": "Supplier OS",
            "represents": "supplier_vendor_42",
            "use_case": "supply_chain_coordination",
            "requested_scopes": supplier_scopes,
            "cannot_do": ["auto_accept_price_change", "bypass_food_safety", "release_vendor_payment_without_approval", "auto_purchase"],
        }
    )
    assert registered["agent"]["use_case"] == "supply_chain_coordination"

    certified = certify_agent_onboarding("certified_supplier_agent", {"scenario_mode": "cold_chain_incident"})
    assert certified["status"] == "approved"
    assert certified["agent"]["approval"] == "approved_for_supply_chain_coordination"
    assert certified["certification"]["use_case"] == "supply_chain_coordination"
    assert certified["certification"]["score"] == 1
    assert set(certified["certification"]["passed_cases"]) >= {"identity_trust", "capability_scope", "supply_chain_negotiation", "procurement_gate", "artifact_verification"}
    assert {"cold_chain_status", "substitution_request", "policy_check", "session_commit"}.issubset(set(certified["agent"]["allowed_scopes"]))

    credential = certified["certification"]["credential"]
    assert credential["approval"] == "approved_for_supply_chain_coordination"
    assert credential["use_case"] == "supply_chain_coordination"
    assert set(credential["required_cases"]) >= {"supply_chain_negotiation", "procurement_gate", "artifact_verification"}
    verified = verify_agent_certification_credential({"credential": credential})
    assert verified["status"] == "verified"
    assert verified["approval"] == "approved_for_supply_chain_coordination"
    assert verified["agent_id"] == "certified_supplier_agent"
    tampered = {**credential, "approval": "approved_for_guest_route_planning"}
    assert verify_agent_certification_credential({"credential": tampered})["status"] == "rejected"

    session = certified["session"]
    assert session["client_agent"]["represents"] == "supplier_vendor_42"
    assert {handoff["internal_agent_id"] for handoff in session["internal_handoffs"]} >= {"supply_chain_agent", "procurement_agent", "safety_agent", "food_agent"}
    _credential_revocations.pop(credential["certification_id"], None)
    _agent_onboardings.pop("certified_supplier_agent", None)


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
    assert certified["certification"]["required_cases"]["capability_scope"]["status"] in {"failed", "missing"}
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
