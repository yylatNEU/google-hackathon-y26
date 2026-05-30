from __future__ import annotations

from copy import deepcopy
from typing import Any

from synthetic_park_knowledge import get_synthetic_park_knowledge, retrieve_synthetic_park_context


INJECTION_BY_DOMAIN: dict[str, dict[str, Any]] = {
    "guest_care_security": {"kind": "lost_child", "target_id": "foodCourt1", "intensity": 88},
    "medical_access": {"kind": "medical_response", "target_id": "careLagoon", "intensity": 92},
    "ride_safety": {"kind": "ride_failure", "target_id": "dragonCoaster", "intensity": 90},
    "facilities_equipment": {"kind": "energy_spike", "target_id": "coasterPlaza", "intensity": 84},
    "crowd_flow": {"kind": "demand_spike", "target_id": "coasterPlaza", "intensity": 86},
    "food_ops": {"kind": "food_spike", "target_id": "foodCourt1", "intensity": 82},
    "labor_staffing": {"kind": "staff_callout", "target_id": "coasterPlaza", "intensity": 78},
    "weather_shelter": {"kind": "storm_risk", "target_id": "coveredPlaza", "intensity": 86},
    "conflict_priority": {"kind": "lost_child", "target_id": "foodCourt1", "intensity": 90},
}

INJECTION_BY_CASE: dict[str, dict[str, Any]] = {
    "CASE-SECURITY-UNATTENDED-BAG-001": {"kind": "unattended_bag", "target_id": "coasterPlaza", "intensity": 88},
    "CASE-POWER-OUTAGE-RIDES-001": {"kind": "energy_spike", "target_id": "coasterPlaza", "intensity": 90},
    "CASE-MEDICAL-CHEST-PAIN-001": {"kind": "medical_response", "target_id": "careLagoon", "intensity": 94},
    "CASE-RIDE-EVAC-001": {"kind": "ride_failure", "target_id": "dragonCoaster", "intensity": 95},
    "CASE-CROWD-CRUSH-PINCHPOINT-001": {"kind": "demand_spike", "target_id": "coasterPlaza", "intensity": 94},
}


def synthetic_examples() -> list[dict[str, Any]]:
    dataset = get_synthetic_park_knowledge()
    return [deepcopy(item) for item in dataset.get("operator_examples", []) or [] if isinstance(item, dict)]


def find_synthetic_example(selector: str) -> dict[str, Any] | None:
    text = (selector or "").strip().lower()
    if not text:
        return None
    for example in synthetic_examples():
        if str(example.get("id", "")).lower() == text:
            return example
        if str(example.get("expected_case_id", "")).lower() == text:
            return example
        if any(isinstance(utterance, str) and utterance.lower() == text for utterance in example.get("utterances", []) or []):
            return example
    context = retrieve_synthetic_park_context(selector, {}, limit=1)
    primary = context.get("primary_example") if isinstance(context.get("primary_example"), dict) else None
    if primary:
        return next((example for example in synthetic_examples() if example.get("id") == primary.get("id")), primary)
    return None


def injection_plan_for_example(example: dict[str, Any]) -> dict[str, Any]:
    case_id = str(example.get("expected_case_id") or "")
    domain = str(example.get("domain") or "")
    base = INJECTION_BY_CASE.get(case_id) or INJECTION_BY_DOMAIN.get(domain) or {"kind": "demand_spike", "target_id": "coasterPlaza", "intensity": 72}
    return {
        **base,
        "synthetic_example_id": example.get("id"),
        "domain": domain,
        "expected_owner": example.get("expected_owner"),
        "expected_case_id": example.get("expected_case_id"),
        "expected_action": example.get("expected_action"),
        "hard_constraints": example.get("hard_constraints", []),
        "evaluation_assertions": example.get("evaluation_assertions", []),
        "utterance": (example.get("utterances") or [""])[0],
    }


def synthetic_eval_cases(limit_examples: int = 12, utterances_per_example: int = 2) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for example in synthetic_examples()[: max(1, limit_examples)]:
        for utterance in (example.get("utterances", []) or [])[: max(1, utterances_per_example)]:
            if not isinstance(utterance, str) or not utterance.strip():
                continue
            rows.append(
                {
                    "example_id": example.get("id"),
                    "utterance": utterance,
                    "domain": example.get("domain"),
                    "expected_owner": example.get("expected_owner"),
                    "expected_case_id": example.get("expected_case_id"),
                    "expected_gate": example.get("expected_gate"),
                    "evaluation_assertions": example.get("evaluation_assertions", []),
                }
            )
    return rows


def score_synthetic_copilot_response(eval_case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    expected_owner = eval_case.get("expected_owner")
    expected_case = eval_case.get("expected_case_id")
    expected_gate = eval_case.get("expected_gate")
    recommended = response.get("recommended_action", {}) if isinstance(response.get("recommended_action"), dict) else {}
    deliberation = response.get("multi_agent_deliberation", {}) if isinstance(response.get("multi_agent_deliberation"), dict) else {}
    supervisor = deliberation.get("supervisor", {}) if isinstance(deliberation.get("supervisor"), dict) else {}
    synthetic = response.get("synthetic_park_context", {}) if isinstance(response.get("synthetic_park_context"), dict) else {}
    primary_synthetic = synthetic.get("primary_example", {}) if isinstance(synthetic.get("primary_example"), dict) else {}

    owner_actual = supervisor.get("selected_agent") or primary_synthetic.get("expected_owner") or "Scan Agent"
    case_actual = recommended.get("matched_case_id")
    gate_actual = recommended.get("gate")
    checks = [
        {"name": "synthetic_retrieved", "passed": bool(primary_synthetic.get("id"))},
        {"name": "owner_match", "passed": not expected_owner or owner_actual == expected_owner, "expected": expected_owner, "actual": owner_actual},
        {"name": "case_match", "passed": not expected_case or case_actual == expected_case, "expected": expected_case, "actual": case_actual},
        {"name": "gate_match", "passed": not expected_gate or gate_actual == expected_gate or (expected_gate == "prepared" and gate_actual in {"prepared", "approval_required"}), "expected": expected_gate, "actual": gate_actual},
        {"name": "answered", "passed": bool(str(response.get("answer") or "").strip())},
    ]
    passed = sum(1 for check in checks if check["passed"])
    return {
        "example_id": eval_case.get("example_id"),
        "utterance": eval_case.get("utterance"),
        "score": round((passed / max(1, len(checks))) * 100),
        "passed": passed == len(checks),
        "checks": checks,
        "actual": {
            "mode": response.get("mode"),
            "owner": owner_actual,
            "case_id": case_actual,
            "gate": gate_actual,
            "synthetic_example_id": primary_synthetic.get("id"),
        },
    }
