#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SUPPLIER_SCOPES = [
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

SUPPLIER_CANNOT_DO = [
    "auto_accept_price_change",
    "bypass_food_safety",
    "release_vendor_payment_without_approval",
    "auto_purchase",
]


@dataclass
class ApiResult:
    status_code: int
    payload: dict[str, Any]


class SupplierAgentFailure(RuntimeError):
    pass


def post_json(api: str, path: str, body: dict[str, Any], expected_status: int = 200) -> ApiResult:
    request = Request(
        f"{api.rstrip('/')}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=90) as response:
            return ApiResult(response.status, json.loads(response.read().decode("utf-8")))
    except HTTPError as error:
        payload = json.loads(error.read().decode("utf-8") or "{}")
        if error.code != expected_status:
            raise SupplierAgentFailure(f"{path} returned {error.code}, expected {expected_status}: {payload}") from error
        return ApiResult(error.code, payload)
    except URLError as error:
        raise SupplierAgentFailure(f"Unable to reach {api}{path}: {error}") from error


def get_json(api: str, path: str, expected_status: int = 200) -> ApiResult:
    request = Request(f"{api.rstrip('/')}{path}", headers={"accept": "application/json"}, method="GET")
    try:
        with urlopen(request, timeout=90) as response:
            return ApiResult(response.status, json.loads(response.read().decode("utf-8")))
    except HTTPError as error:
        payload = json.loads(error.read().decode("utf-8") or "{}")
        if error.code != expected_status:
            raise SupplierAgentFailure(f"{path} returned {error.code}, expected {expected_status}: {payload}") from error
        return ApiResult(error.code, payload)
    except URLError as error:
        raise SupplierAgentFailure(f"Unable to reach {api}{path}: {error}") from error


def certify_supplier_agent(api: str, agent_id: str, supplier_id: str, scenario_mode: str) -> dict[str, Any]:
    post_json(
        api,
        "/api/park/agent-onboarding/register",
        {
            "agent_id": agent_id,
            "display_name": "External Supplier Agent",
            "partner_id": "external_supplier_os",
            "partner_name": "External Supplier OS",
            "represents": supplier_id,
            "use_case": "supply_chain_coordination",
            "requested_scopes": SUPPLIER_SCOPES,
            "cannot_do": SUPPLIER_CANNOT_DO,
        },
    )
    certified = post_json(api, f"/api/park/agent-onboarding/{agent_id}/certify", {"scenario_mode": scenario_mode}).payload
    certification = certified.get("certification") if isinstance(certified.get("certification"), dict) else {}
    credential = certification.get("credential") if isinstance(certification.get("credential"), dict) else {}
    if certified.get("status") != "approved" or certification.get("approval") != "approved_for_supply_chain_coordination" or not credential:
        raise SupplierAgentFailure(f"Supplier certification failed: {certified}")
    verified = post_json(api, "/api/park/agent-onboarding/verify-credential", {"credential": credential}).payload
    if verified.get("status") != "verified":
        raise SupplierAgentFailure(f"Supplier certification credential did not verify: {verified}")
    return {"certified": certified, "credential_verification": verified}


def run_supply_chain_handshake(api: str, scenario_mode: str) -> dict[str, Any]:
    demo = post_json(api, "/api/park/agent-handshake/supply-chain/demo", {"scenario_mode": scenario_mode}).payload
    receipt = demo.get("receipt") if isinstance(demo.get("receipt"), dict) else {}
    if demo.get("status") != "demo_complete" or not receipt:
        raise SupplierAgentFailure(f"Supply-chain handshake did not complete: {demo}")
    verification = post_json(
        api,
        "/api/park/agent-handshake/verify-artifact",
        {"artifact": receipt, "expected_artifact_type": "agent_handshake_session_receipt"},
    ).payload
    if verification.get("status") != "verified":
        raise SupplierAgentFailure(f"Signed receipt did not verify: {verification}")
    return {"demo": demo, "receipt_verification": verification}


def summarize(certification: dict[str, Any], handshake: dict[str, Any]) -> dict[str, Any]:
    certified = certification["certified"]
    cert = certified["certification"]
    demo = handshake["demo"]
    session = demo.get("session") if isinstance(demo.get("session"), dict) else {}
    handoffs = sorted(
        {
            str(handoff.get("internal_agent_id"))
            for handoff in session.get("internal_handoffs", [])
            if isinstance(handoff, dict) and handoff.get("internal_agent_id")
        }
    )
    policy_gates = [
        {"action": decision.get("action"), "status": decision.get("status"), "requires_user_approval": decision.get("requires_user_approval")}
        for decision in session.get("policy_decisions", [])
        if isinstance(decision, dict) and decision.get("action") in {"purchase_order", "vendor_payment_release", "price_change_acceptance", "bypass_food_safety"}
    ]
    return {
        "status": "passed",
        "mode": "external_supplier_agent_client",
        "agent_id": certified["agent"]["agent_id"],
        "supplier_id": certified["agent"]["represents"],
        "certification": {
            "approval": cert.get("approval"),
            "score": cert.get("score"),
            "credential_status": certification["credential_verification"].get("status"),
            "passed_cases": cert.get("passed_cases"),
        },
        "handshake": {
            "scenario_mode": demo.get("scenario_mode"),
            "session_id": demo.get("session_id"),
            "receipt_id": demo.get("receipt", {}).get("receipt_id"),
            "receipt_verification_status": handshake["receipt_verification"].get("status"),
            "internal_handoffs": handoffs,
            "policy_gates": policy_gates,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an external supplier-agent interoperability proof against ParkPulse AHP.")
    parser.add_argument("--api", default="http://127.0.0.1:8001", help="ParkPulse API base URL.")
    parser.add_argument("--scenario-mode", default="cold_chain_incident", choices=["supply_replenishment", "cold_chain_incident", "maintenance_parts_shortage"])
    parser.add_argument("--agent-id", default="", help="External supplier agent id. Defaults to a timestamped id.")
    parser.add_argument("--supplier-id", default="supplier_vendor_external_demo")
    parser.add_argument("--json", action="store_true", help="Print JSON only.")
    args = parser.parse_args()

    agent_id = args.agent_id or f"external_supplier_agent_{int(time.time())}"
    try:
        certification = certify_supplier_agent(args.api, agent_id, args.supplier_id, args.scenario_mode)
        handshake = run_supply_chain_handshake(args.api, args.scenario_mode)
        result = summarize(certification, handshake)
    except SupplierAgentFailure as error:
        result = {"status": "failed", "mode": "external_supplier_agent_client", "readiness_issues": [str(error)]}
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print("External supplier agent client: failed")
            print(json.dumps(result, indent=2, sort_keys=True))
        return 1

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("External supplier agent client: passed")
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
