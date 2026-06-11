#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time

from parkpulse_agent_client import DEFAULT_CANNOT_DO, FULL_SCOPE, ParkPulseAgentClient


def assert_passed(payload: dict, case_id: str) -> dict:
    evaluation = payload.get("case_evaluation")
    if not isinstance(evaluation, dict) or evaluation.get("case") != case_id or evaluation.get("status") != "passed":
        raise RuntimeError(f"{case_id} did not pass: {evaluation}")
    return evaluation


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an external personal-agent ParkPulse handshake demo.")
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="ParkPulse API base URL.")
    parser.add_argument("--agent-id", default=f"external_family_agent_{int(time.time())}", help="External agent id.")
    parser.add_argument("--guest-id", default="guest_user_123", help="Guest subject represented by the external agent.")
    args = parser.parse_args()

    client = ParkPulseAgentClient(args.api)
    agent_id = args.agent_id

    issuer = client.issuer_metadata()
    registered = client.register_agent(agent_id, "External Family Planning Agent", FULL_SCOPE, DEFAULT_CANNOT_DO, partner_id="external_family_os", partner_name="External Family OS")
    certified = client.certify_agent(agent_id)
    credential = certified["certification"]["credential"]
    verified = client.verify_certification_credential(credential)
    if verified.get("status") != "verified":
        raise RuntimeError(f"Certification credential was not accepted: {verified}")
    if credential.get("kid") != issuer.get("signing", {}).get("kid"):
        raise RuntimeError(f"Credential kid does not match issuer metadata: {credential.get('kid')} vs {issuer.get('signing')}")

    delegation_token = client.issue_delegation_token(args.guest_id, agent_id, FULL_SCOPE, DEFAULT_CANNOT_DO)
    identity = client.start_handshake(agent_id, args.guest_id, delegation_token)
    session_id = identity["session"]["session_id"]
    scope = client.declare_capabilities(session_id, delegation_token)
    intent = client.submit_intent(session_id, delegation_token)
    proposal = client.request_plan(session_id, delegation_token)
    counter = client.request_counter_plan(session_id, delegation_token)
    committed = client.commit_plan(session_id, delegation_token)
    monitored = client.monitor_session(session_id, delegation_token)
    commerce = client.probe_payment_gate(session_id, delegation_token)
    queue = client.request_queue_reroute(session_id, delegation_token)
    commerce_gate = commerce.get("internal_agent") if isinstance(commerce.get("internal_agent"), dict) else commerce
    intent_response = intent.get("session", {}).get("intent", {}).get("park_agent", {}) if isinstance(intent.get("session"), dict) else {}

    result = {
        "status": "passed",
        "api": args.api,
        "agent": {
            "agent_id": agent_id,
            "registration_status": registered["agent"]["status"],
            "approval": certified["agent"]["approval"],
            "credential_status": verified["status"],
            "certification_id": credential["certification_id"],
            "issuer_kid": issuer["signing"]["kid"],
            "partner": registered["agent"]["partner"],
        },
        "session": {
            "session_id": session_id,
            "state": monitored["session"]["state"],
            "credential_presented": True,
            "delegation_subject": args.guest_id,
        },
        "plan": {
            "initial_plan": proposal["proposal"]["plan"],
            "initial_wait_saved": proposal["proposal"]["expected_wait_saved"],
            "counter_plan": counter["proposal"]["plan"],
            "commit_status": committed["status"],
            "commitment_id": committed["commitment"]["commitment_id"],
            "reroute_plan": queue["proposal"]["plan"],
            "reroute_wait_saved": queue["proposal"]["expected_wait_saved"],
        },
        "gates": {
            "payment_probe_status": commerce["status"],
            "payment_requires_user_approval": commerce_gate.get("requires_user_approval"),
            "queue_reroute_status": queue["status"],
        },
        "case_evaluations": {
            "identity_trust": assert_passed(identity, "identity_trust"),
            "capability_scope": assert_passed(scope, "capability_scope"),
            "commerce_payment_probe": assert_passed(commerce, "commerce_payment_probe"),
            "queue_reroute": assert_passed(queue, "queue_reroute"),
        },
        "intent_acceptance": intent_response.get("accepted_goal", intent.get("status") == "intent_accepted"),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
