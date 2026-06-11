from __future__ import annotations

from copy import deepcopy
from typing import Any


ROLE_UNDERSTANDING_CONTRACTS: dict[str, dict[str, Any]] = {
    "scan": {
        "must_understand": ["live state uncertainty", "affected zones", "weak-signal confidence", "why not dispatch"],
        "required_tool_sequence": ["get_noisy_observation", "get_park_state", "retrieve_similar_incidents"],
        "minimum_tool_coverage": 3,
        "forbidden_tools": ["dispatch_guest_message", "dispatch_worker_task", "dispatch_equipment_command", "write_decision_memory"],
        "dispatch_allowed": False,
    },
    "react": {
        "must_understand": ["operator incident", "live affected asset", "candidate alternatives", "policy boundary", "receiver payload scope"],
        "required_tool_sequence": ["get_park_state", "retrieve_similar_incidents", "compare_action_candidates", "simulate_action", "validate_policy"],
        "minimum_tool_coverage": 5,
        "forbidden_tools": [],
        "dispatch_allowed": "bounded",
    },
    "proact": {
        "must_understand": ["weak signal cluster", "forecast delta", "baseline versus preventive action", "policy boundary", "observed response learning"],
        "required_tool_sequence": ["get_noisy_observation", "retrieve_similar_incidents", "simulate_action", "validate_policy", "score_outcome", "write_decision_memory"],
        "minimum_tool_coverage": 5,
        "forbidden_tools": [],
        "dispatch_allowed": "bounded_preventive",
    },
    "customer": {
        "must_understand": ["public-only facts", "guest segment", "wait-aware route", "privacy boundary", "customer action scope"],
        "required_tool_sequence": ["get_park_state", "get_public_wait_times", "get_public_route_options"],
        "minimum_tool_coverage": 3,
        "forbidden_tools": ["dispatch_guest_message", "dispatch_worker_task", "dispatch_equipment_command", "write_decision_memory"],
        "dispatch_allowed": False,
    },
    "qa": {
        "must_understand": ["runtime readiness", "failure modes", "policy gate evidence", "delivery idempotency", "observability and fallback coverage"],
        "required_tool_sequence": ["get_park_state", "inspect_runtime_status", "simulate_action", "validate_policy", "inspect_delivery_receipts", "inspect_observability_contract"],
        "minimum_tool_coverage": 5,
        "forbidden_tools": ["dispatch_guest_message", "dispatch_worker_task", "dispatch_equipment_command", "write_decision_memory"],
        "dispatch_allowed": False,
    },
}

ROLE_PRODUCT_READY_CHECKS: dict[str, tuple[str, ...]] = {
    "scan": (
        "role_setup_complete",
        "role_work_depth_passed",
        "trace_eval_passed",
        "output_eval_passed",
        "read_only_no_dispatch",
        "has_scan_output",
        "has_signal_evidence",
        "no_dispatch_tools_called",
        "negative_fixture_covered",
        "adversarial_fixture_covered",
    ),
    "react": (
        "role_setup_complete",
        "role_work_depth_passed",
        "trace_eval_passed",
        "output_eval_passed",
        "has_receiver_payloads",
        "policy_gate_present",
        "dispatch_receipts_present",
        "receipt_has_dispatch_ids",
        "negative_fixture_covered",
        "adversarial_fixture_covered",
    ),
    "proact": (
        "role_setup_complete",
        "role_work_depth_passed",
        "trace_eval_passed",
        "output_eval_passed",
        "has_receiver_payloads",
        "learning_observed",
        "policy_gate_present",
        "dispatch_receipts_present",
        "negative_fixture_covered",
        "adversarial_fixture_covered",
    ),
    "customer": (
        "role_setup_complete",
        "role_work_depth_passed",
        "trace_eval_passed",
        "output_eval_passed",
        "customer_read_only",
        "has_customer_answer",
        "no_operator_dispatch",
        "public_actions_only",
        "negative_fixture_covered",
        "adversarial_fixture_covered",
    ),
    "qa": (
        "role_setup_complete",
        "role_work_depth_passed",
        "trace_eval_passed",
        "output_eval_passed",
        "read_only_no_dispatch",
        "has_go_no_go",
        "qa_receipt_read_only",
        "inspection_evidence_present",
        "has_failure_mode_matrix",
        "negative_fixture_covered",
        "adversarial_fixture_covered",
    ),
}


ROLE_SKILLS: list[dict[str, Any]] = [
    {
        "id": "parkpulse.scan",
        "name": "Scan Agent",
        "skill": "parkpulse-scan-agent",
        "mode": "scan",
        "purpose": "Read live state, noisy observations, vague text signals, and memory without dispatching actions.",
        "trigger_examples": ["what is happening", "scan the park", "weak signal", "guest complaint", "medical note", "crowd anomaly"],
        "mcp_tools": [
            "get_noisy_observation",
            "get_park_state",
            "get_zone_density",
            "get_ride_status",
            "get_staff_constraints",
            "get_food_capacity",
            "retrieve_similar_incidents",
            "score_decision_quality",
        ],
        "api_surfaces": [
            "GET /api/park/state",
            "GET /api/park/proactive-insights",
            "GET /api/park/digital-twin/tools",
            "POST /api/park/digital-twin/run",
            "GET /api/park/memory",
        ],
        "output_artifacts": ["signal_cluster", "risk_summary", "evidence_list", "recommended_next_role"],
        "permissions": {"read": True, "simulate": True, "dispatch": False, "memory_write": False},
        "policy_gates": ["privacy_no_pii", "medical_no_diagnosis", "uncertainty_disclosure"],
    },
    {
        "id": "parkpulse.react",
        "name": "React Agent",
        "skill": "parkpulse-react-agent",
        "mode": "react",
        "purpose": "Respond to confirmed incidents or operator commands with custom, policy-gated receiver payloads.",
        "trigger_examples": ["ride is down", "food court is down", "guest fainted", "medical team needed", "worker shortage", "evacuation support"],
        "mcp_tools": [
            "get_park_state",
            "get_ride_status",
            "get_food_capacity",
            "get_staff_constraints",
            "get_zone_density",
            "retrieve_similar_incidents",
            "compare_action_candidates",
            "simulate_action",
            "validate_policy",
            "dispatch_guest_message",
            "dispatch_worker_task",
            "dispatch_equipment_command",
            "write_decision_memory",
        ],
        "api_surfaces": [
            "POST /api/park/operator-command",
            "GET /api/park/operator-command/stream",
            "POST /api/park/digital-twin/run",
            "POST /api/park/delivery/acknowledge",
        ],
        "output_artifacts": ["interpreted_incident", "candidate_actions", "policy_gate", "receiver_payloads", "run_receipt"],
        "permissions": {"read": True, "simulate": True, "dispatch": "bounded", "memory_write": True},
        "policy_gates": ["ride_safety_authority", "labor_break_protection", "medical_no_diagnosis", "equipment_bounds"],
    },
    {
        "id": "parkpulse.proact",
        "name": "Proact Agent",
        "skill": "parkpulse-proact-agent",
        "mode": "proact",
        "purpose": "Detect weak signals before failure, ask Gemini for a compact brief, emit bounded actions, observe take rate, and update memory.",
        "trigger_examples": ["proact", "prevent issue", "early detection", "take rate", "learn over time", "future planning"],
        "mcp_tools": [
            "get_noisy_observation",
            "retrieve_similar_incidents",
            "tick_simulation",
            "simulate_action",
            "validate_policy",
            "dispatch_guest_message",
            "dispatch_worker_task",
            "dispatch_equipment_command",
            "score_outcome",
            "write_decision_memory",
        ],
        "api_surfaces": [
            "GET /api/park/proactive-insights",
            "GET /api/park/proactive-run/stream",
            "POST /api/park/proactive-run",
            "POST /api/park/digital-twin/run",
            "GET /api/park/digital-twin/benchmark/report/latest",
        ],
        "output_artifacts": ["early_detection", "forecast_delta", "gemini_brief", "receiver_payloads", "observed_response", "learning_update"],
        "permissions": {"read": True, "simulate": True, "dispatch": "bounded_preventive", "memory_write": True},
        "policy_gates": ["false_alarm_risk", "medical_no_diagnosis", "equipment_bounds", "learning_requires_observed_response"],
    },
    {
        "id": "parkpulse.customer_support",
        "name": "Customer Support Agent",
        "skill": "parkpulse-customer-support-agent",
        "mode": "customer",
        "purpose": "Answer customer kiosk questions with public park state, wait-aware recommendations, route notes, and guest-app handoff actions.",
        "trigger_examples": [
            "customer support station",
            "ask the station",
            "guest recommendation",
            "where should my family go",
            "send route to phone",
            "customer kiosk",
        ],
        "mcp_tools": [
            "get_park_state",
            "get_public_wait_times",
            "get_public_route_options",
            "get_food_capacity",
            "customer_show_route",
            "customer_send_to_phone",
        ],
        "api_surfaces": [
            "POST /api/park/customer-support-agent",
            "GET /api/gcp/agent-builder/registry",
            "GET /api/park/state",
        ],
        "output_artifacts": ["customer_answer", "public_recommendation", "route_note", "customer_action_receipt", "agent_boundary_receipt"],
        "permissions": {"read": True, "simulate": False, "dispatch": False, "memory_write": False, "customer_actions": ["show_route", "send_to_phone"]},
        "policy_gates": [
            "customer_read_only",
            "privacy_no_pii",
            "medical_no_diagnosis",
            "no_operator_dispatch",
            "no_internal_policy_disclosure",
            "no_compensation_promise",
        ],
    },
    {
        "id": "parkpulse.production_reliability_qa",
        "name": "Production Reliability QA Engineer",
        "skill": "parkpulse-production-reliability-qa-agent",
        "mode": "qa",
        "purpose": "Audit whether ParkPulse is production-reliable across operational completeness, policy compliance, action safety, hallucination risk, reasoning quality, scenario coverage, coordination, regulatory exposure, traceability, fallbacks, dispatch receipts, observability, and load behavior.",
        "trigger_examples": [
            "production reliability qa",
            "reliability review",
            "failure mode matrix",
            "go no-go",
            "pre-deploy qa",
            "test production readiness",
            "scenario coverage evaluation",
            "policy compliance audit",
            "drift detection",
        ],
        "mcp_tools": [
            "get_park_state",
            "inspect_runtime_status",
            "get_noisy_observation",
            "retrieve_similar_incidents",
            "simulate_action",
            "validate_policy",
            "score_decision_quality",
            "inspect_delivery_receipts",
            "inspect_observability_contract",
        ],
        "api_surfaces": [
            "POST /api/park/reliability-qa-run",
            "POST /api/park/agent-role-run",
            "GET /api/park/agent-role-skills",
            "GET /api/park/integration-status",
            "POST /api/park/operator-command",
            "GET /api/park/operator-command/stream",
            "POST /api/park/proactive-run",
            "GET /api/park/proactive-run/stream",
            "POST /api/park/digital-twin/run",
            "POST /api/park/delivery/acknowledge",
        ],
        "output_artifacts": [
            "reliability_risk_summary",
            "failure_mode_matrix",
            "scenario_test_plan",
            "scenario_coverage_evaluation",
            "evaluation_scores",
            "drift_analysis",
            "deployment_recommendation",
            "acceptance_criteria",
            "observability_checklist",
            "go_no_go_recommendation",
        ],
        "permissions": {"read": True, "simulate": True, "dispatch": False, "memory_write": False},
        "policy_gates": [
            "qa_read_only",
            "policy_gate_pre_dispatch",
            "fallback_reason_required",
            "human_approval_boundary",
            "observability_contract_complete",
        ],
    },
]


def _role_with_contract(role: dict[str, Any]) -> dict[str, Any]:
    copied = deepcopy(role)
    mode = str(copied.get("mode") or "")
    contract = deepcopy(ROLE_UNDERSTANDING_CONTRACTS.get(mode, {}))
    copied["understanding_contract"] = {
        "mode": "role_understanding_contract",
        "must_understand": contract.get("must_understand", []),
        "evidence_required": [
            "concrete tool output",
            "role-specific boundary",
            "scenario or guest segment grounding",
            "next action or escalation condition",
        ],
    }
    copied["deliberate_tool_use"] = {
        "mode": "deliberate_tool_sequence",
        "required_sequence": contract.get("required_tool_sequence", copied.get("mcp_tools", [])[:3]),
        "minimum_tool_coverage": contract.get("minimum_tool_coverage", 2),
        "forbidden_tools": contract.get("forbidden_tools", []),
        "dispatch_allowed": contract.get("dispatch_allowed", copied.get("permissions", {}).get("dispatch")),
        "rule": "Tools must be traceable, ordered by evidence need, and marked needed instead of claimed when output is unavailable.",
    }
    copied["evaluation_contract"] = {
        "mode": "deliberate_role_eval_contract",
        "score_threshold": 88,
        "critical_checks": [
            "tool_coverage",
            "tool_order",
            "meaningful_tool_outputs",
            "role_boundary",
            "policy_gate_evidence_when_dispatching",
            "dispatch_receipt_evidence",
            "qa_inspection_evidence",
        ],
        "trace_field": "digital_twin_tools.deliberate_eval",
    }
    return copied


def _roles_with_contracts() -> list[dict[str, Any]]:
    return [_role_with_contract(role) for role in ROLE_SKILLS]


def list_agent_role_skills() -> dict[str, Any]:
    return {
        "server": "parkpulse.agent_roles",
        "style": "mcp_skill_registry",
        "principle": "Route work by role: customer support answers guests, scan reads and explains, react handles confirmed incidents, proact prevents failures and learns from response.",
        "roles": _roles_with_contracts(),
        "routing_order": ["qa", "customer", "scan", "react", "proact"],
        "deliberate_eval": {
            "mode": "registry_level_deliberate_eval",
            "applies_to": ["scan", "react", "proact", "customer", "qa"],
            "checks": ["understanding_contract_present", "required_tool_sequence_present", "tool_trace_eval_present"],
        },
        "proof": {
            "skill_paths": [
                ".agents/skills/parkpulse-scan-agent/SKILL.md",
                ".agents/skills/parkpulse-react-agent/SKILL.md",
                ".agents/skills/parkpulse-proact-agent/SKILL.md",
                ".agents/skills/parkpulse-customer-support-agent/SKILL.md",
                ".agents/skills/parkpulse-production-reliability-qa-agent/SKILL.md",
                ".agents/skills/parkpulse-role-orchestrator/SKILL.md",
            ],
            "digital_twin_tool_registry": "GET /api/park/digital-twin/tools",
        },
    }


def route_agent_role(message: str, mode: str = "auto") -> dict[str, Any]:
    text = (message or "").lower()
    explicit = (mode or "auto").lower()
    direct_action_terms = (
        "down",
        "broken",
        "faint",
        "fainted",
        "passed out",
        "first aid",
        "medic",
        "handicapped",
        "wheelchair",
        "accessibility",
        "wheelchair needed",
        "medical team needed",
        "send medical",
        "evacuation",
        "evacuate",
        "move worker",
        "move help",
        "move staff",
        "called out",
        "workers called out",
        "staff called out",
        "certified coverage",
        "staff breaks",
        "staff shortage",
        "shortage",
        "understaffed",
        "overwhelmed",
        "crowd congestion",
        "bottleneck",
        "panic",
        "pushing",
        "stuck",
        "blocked",
        "fight",
        "security",
        "lost child",
        "separated",
        "smoke",
        "fire",
        "sparking",
        "electrical",
        "gas",
        "controller",
        "missed heartbeat",
        "fog",
        "technician",
        "hvac",
        "temperature",
        "too hot",
        "too cold",
        "adjust",
        "adjustment",
        "send message",
        "help needed",
        "assistance needed",
        "is needed",
        "dispatch",
    )
    weak_signal_terms = (
        "complaint",
        "guest app",
        "guest note",
        "staff note",
        "worker app",
        "worker tap",
        "quick tap",
        "support station",
        "station chat",
        "crying",
        "confused",
        "unusual",
        "crowd stopped",
        "crowd not moving",
        "panic",
        "kids need extra care",
        "extra care",
        "dizzy",
        "faintness",
        "heat",
        "accessibility request",
        "wheelchair request",
        "vague",
        "weak signal",
    )
    qa_terms = (
        "qa",
        "quality assurance",
        "production reliability",
        "reliability qa",
        "go/no-go",
        "go no-go",
        "failure mode",
        "test plan",
        "production readiness",
        "pre-deploy",
        "predeploy",
    )
    customer_terms = (
        "customer support station",
        "customer station",
        "support kiosk",
        "customer kiosk",
        "station chat",
        "ask station",
        "guest recommendation",
        "send route to phone",
        "where should my family go",
        "family is asking",
        "family asking",
        "a family is asking",
        "guest is asking",
        "guest asking",
        "with a wheelchair",
        "wheelchair and a long wait",
        "accessible route",
        "accessibility route",
    )
    scan_terms = (
        "scan",
        "read",
        "watch",
        "monitor",
        "observe",
        "what is happening",
        "what's happening",
        "current situation",
        "current park state",
        "status right now",
        "biggest park risk right now",
    )
    operational_action_terms = (
        "what should operations do",
        "what should we do",
        "queue is too long",
        "line is too long",
        "long queue",
        "long line",
        "coaster queue",
        "near the parade",
        "families are stuck",
        "guests are stuck",
    )
    if explicit in {"scan", "react", "proact", "qa", "customer"}:
        selected = explicit
    elif any(term in text for term in qa_terms):
        selected = "qa"
    elif any(term in text for term in customer_terms):
        selected = "customer"
    elif any(term in text for term in scan_terms) and not any(term in text for term in ("prevent", "before", "reroute", "dispatch", "send", "move", "fix")):
        selected = "scan"
    elif any(term in text for term in operational_action_terms):
        selected = "react"
    elif any(term in text for term in ("proact", "prevent", "early", "before", "learn", "take rate", "future")):
        selected = "proact"
    elif any(term in text for term in weak_signal_terms) and not any(term in text for term in direct_action_terms):
        selected = "proact"
    elif any(term in text for term in direct_action_terms) or "medical" in text:
        selected = "react"
    else:
        selected = "scan"
    role = _role_with_contract(next(item for item in ROLE_SKILLS if item["mode"] == selected))
    return {
        "selected_role": selected,
        "skill": role["skill"],
        "why": _route_reason(selected),
        "required_tools": role["mcp_tools"],
        "policy_gates": role["policy_gates"],
        "expected_receipt": role["output_artifacts"],
        "understanding_contract": role["understanding_contract"],
        "deliberate_tool_use": role["deliberate_tool_use"],
        "evaluation_contract": role["evaluation_contract"],
    }


def _route_reason(role: str) -> str:
    if role == "customer":
        return "The request is a customer support kiosk question or customer-only self-service action."
    if role == "react":
        return "The request describes a confirmed incident or direct operator action."
    if role == "proact":
        return "The request asks the agent to detect early, prevent failure, or learn from response."
    if role == "qa":
        return "The request asks for production reliability QA, failure-mode coverage, or a go/no-go readiness review."
    return "The request needs sensing and evidence before any operating action."


def _tool_output(call: dict[str, Any]) -> dict[str, Any]:
    output = call.get("output") if isinstance(call, dict) else {}
    return output if isinstance(output, dict) else {}


def _has_any_key(output: dict[str, Any], keys: set[str]) -> bool:
    return any(key in output and output.get(key) not in (None, "", [], {}) for key in keys)


def _meaningful_tool_output(tool: str, output: dict[str, Any]) -> bool:
    if not isinstance(output, dict) or not output:
        return False
    generic_keys = {"status", "role", "selected_role", "scenario_key", "source", "policy_gate"}
    has_specific_payload = any(value not in (None, "", [], {}) for key, value in output.items() if key not in generic_keys)
    if tool == "get_park_state":
        return _has_any_key(output, {"state", "summary", "activeScenario", "snapshot", "digest", "zones", "waits", "signals"})
    if tool == "get_noisy_observation":
        return _has_any_key(output, {"observed", "observation", "signals", "noise", "confidence", "top_signal", "evidence"})
    if tool.startswith("get_") and tool not in {"get_park_state", "get_noisy_observation"}:
        return has_specific_payload
    if tool == "retrieve_similar_incidents":
        return _has_any_key(output, {"incidents", "learnings", "memory", "memory_ids", "retrieved", "playbooks"})
    if tool == "compare_action_candidates":
        return _has_any_key(output, {"candidates", "ranked", "selected", "rejected", "tradeoffs"})
    if tool in {"simulate_action", "tick_simulation"}:
        return _has_any_key(output, {"projected_impact", "simulation", "forecast_delta", "impact", "state_impact", "response", "learning_validity"})
    if tool == "validate_policy":
        gate = str(output.get("gate_status") or output.get("policy_gate") or "").lower()
        return bool(gate) and gate not in {"none", "null"} and _has_any_key(output, {"gate_status", "policy_gate", "allowed", "findings", "gates"})
    if tool.startswith("dispatch_"):
        return _has_any_key(output, {"dispatch_ids", "idempotencyKey", "idempotency_key", "targetSystem", "target_system", "payload", "receipt_id"})
    if tool == "write_decision_memory":
        return _has_any_key(output, {"decision_id", "outcome_id", "learning_id", "memory_write", "memory", "analytics"})
    if tool in {"score_outcome", "score_decision_quality"}:
        return _has_any_key(output, {"score", "scorecard", "overall", "metrics", "response"})
    if tool.startswith("inspect_"):
        return has_specific_payload and _has_any_key(output, {"runtime", "readiness", "receipts", "observability", "checklist", "required_fields", "dispatch_allowed", "status"})
    return has_specific_payload


def _synthetic_tool_output(tool: str, role: str) -> dict[str, Any]:
    if tool == "get_park_state":
        return {"status": "ok", "summary": f"{role} synthetic park-state snapshot", "activeScenario": {"key": f"{role}_eval"}, "signals": ["queue pressure"]}
    if tool == "get_noisy_observation":
        return {"status": "ok", "signals": [{"kind": "weak_signal", "confidence": 0.82}], "confidence": 0.82, "evidence": ["synthetic sensor drift"]}
    if tool.startswith("get_"):
        return {"status": "ok", "summary": f"{tool} returned bounded operational context", "constraint": "role-compatible"}
    if tool == "retrieve_similar_incidents":
        return {"status": "ok", "incidents": [{"id": f"{role}_incident_eval"}], "learnings": [{"id": f"{role}_learning_eval"}]}
    if tool == "compare_action_candidates":
        return {"status": "ok", "candidates": [{"id": "hold"}, {"id": "act"}], "selected": "act", "rejected": ["hold"]}
    if tool in {"simulate_action", "tick_simulation"}:
        return {"status": "ok", "simulation": {"horizon_minutes": 15}, "projected_impact": {"queue_delta": -8}}
    if tool == "validate_policy":
        return {"status": "ok", "gate_status": "checked", "policy_gate": "checked", "findings": ["bounded authority", "reversible action"]}
    if tool.startswith("dispatch_"):
        return {"status": "prepared", "dispatch_ids": [f"{tool}_{role}_eval"], "idempotencyKey": f"{tool}:{role}:eval", "targetSystem": "synthetic_receiver", "payload": {"role": role}}
    if tool == "write_decision_memory":
        return {"status": "ok", "decision_id": f"{role}_decision_eval", "outcome_id": f"{role}_outcome_eval", "memory_write": {"validity": "observed_response"}}
    if tool == "score_outcome":
        return {"status": "ok", "score": 0.91, "metrics": {"guest_flow": "improved"}}
    if tool == "inspect_runtime_status":
        return {"status": "ok", "readiness": {"api": "ready"}, "runtime": {"llm": "available"}}
    if tool == "inspect_delivery_receipts":
        return {"status": "ok", "receipts": [{"id": f"{role}_receipt_eval"}], "dispatch_allowed": False}
    if tool == "inspect_observability_contract":
        return {"status": "ok", "observability": {"trace": True, "tool_outputs": True}, "checklist": ["role", "tool", "output"]}
    if tool == "score_decision_quality":
        return {"status": "ok", "scorecard": {"overall": 0.9}, "overall": 0.9}
    return {"status": "ok", "summary": f"{tool} produced role-specific evidence"}


def evaluate_agent_role_trace(route: dict[str, Any], tool_trace: dict[str, Any], role_output: dict[str, Any] | None = None) -> dict[str, Any]:
    selected_role = str(route.get("selected_role") or (tool_trace.get("summary", {}) if isinstance(tool_trace, dict) else {}).get("selected_role") or "")
    contract = route.get("deliberate_tool_use") if isinstance(route.get("deliberate_tool_use"), dict) else ROLE_UNDERSTANDING_CONTRACTS.get(selected_role, {})
    required_sequence = [str(tool) for tool in (contract.get("required_sequence") or contract.get("required_tool_sequence") or []) if tool]
    forbidden_tools = {str(tool) for tool in contract.get("forbidden_tools", []) if tool}
    calls = tool_trace.get("tool_calls", []) if isinstance(tool_trace, dict) else []
    called_tools = [str(call.get("tool")) for call in calls if isinstance(call, dict) and call.get("tool")]
    called_set = set(called_tools)
    required_present = [tool for tool in required_sequence if tool in called_set]
    missing_required = [tool for tool in required_sequence if tool not in called_set]
    forbidden_present = sorted(forbidden_tools.intersection(called_set))
    first_call_by_tool = {str(call.get("tool")): call for call in calls if isinstance(call, dict) and call.get("tool")}
    required_without_output = [
        tool for tool in required_present if not _meaningful_tool_output(tool, _tool_output(first_call_by_tool.get(tool, {})))
    ]
    called_without_output = [
        tool for tool in called_tools if not _meaningful_tool_output(tool, _tool_output(first_call_by_tool.get(tool, {})))
    ]
    ordered = True
    last_index = -1
    for tool in required_present:
        index = called_tools.index(tool)
        if index < last_index:
            ordered = False
            break
        last_index = index
    dispatch_tools = [tool for tool in called_tools if tool.startswith("dispatch_")]
    dispatch_allowed = contract.get("dispatch_allowed")
    boundary_ok = bool(dispatch_allowed) or not dispatch_tools
    policy_required = bool(dispatch_tools) or dispatch_allowed in {"bounded", "bounded_preventive", True}
    policy_ok = not policy_required or "validate_policy" in called_set
    policy_evidence_ok = not policy_required or ("validate_policy" in called_set and "validate_policy" not in required_without_output and "validate_policy" not in called_without_output)
    dispatch_receipts_ok = not dispatch_tools or all(tool not in called_without_output for tool in dispatch_tools)
    inspect_tools = [tool for tool in required_sequence if tool.startswith("inspect_")]
    inspect_evidence_ok = all(tool in called_set and tool not in required_without_output for tool in inspect_tools)
    minimum_tool_coverage = int(contract.get("minimum_tool_coverage", 2) or 2)
    coverage_ratio = len(required_present) / max(1, len(required_sequence))
    score = 100
    score -= max(0, minimum_tool_coverage - len(required_present)) * 15
    score -= len(missing_required) * 10
    score -= len(required_without_output) * 8
    score -= 18 if not ordered else 0
    score -= 35 if forbidden_present else 0
    score -= 30 if not boundary_ok else 0
    score -= 18 if not policy_ok else 0
    score -= 25 if not policy_evidence_ok else 0
    score -= 20 if not dispatch_receipts_ok else 0
    score -= 15 if not inspect_evidence_ok else 0
    score = max(0, min(100, round(score)))
    critical_failures = [
        *([f"missing_required:{tool}" for tool in missing_required]),
        *([f"missing_output:{tool}" for tool in required_without_output]),
        *([f"forbidden:{tool}" for tool in forbidden_present]),
        *(["order_violation"] if not ordered else []),
        *(["dispatch_boundary_violation"] if not boundary_ok else []),
        *(["policy_tool_missing"] if not policy_ok else []),
        *(["policy_evidence_missing"] if not policy_evidence_ok else []),
        *(["dispatch_receipt_missing"] if not dispatch_receipts_ok else []),
        *(["inspection_evidence_missing"] if not inspect_evidence_ok else []),
    ]
    status = "passed" if score >= 88 and not critical_failures else "failed" if score < 70 or critical_failures else "warning"
    return {
        "mode": "deliberate_role_tool_use_eval",
        "role": selected_role,
        "status": status,
        "score": score,
        "coverage_ratio": round(coverage_ratio, 3),
        "required_sequence": required_sequence,
        "called_tools": called_tools,
        "required_present": required_present,
        "missing_required": missing_required,
        "forbidden_present": forbidden_present,
        "required_without_output": required_without_output,
        "called_without_output": called_without_output,
        "ordered": ordered,
        "boundary_ok": boundary_ok,
        "policy_ok": policy_ok,
        "policy_evidence_ok": policy_evidence_ok,
        "dispatch_receipts_ok": dispatch_receipts_ok,
        "inspect_evidence_ok": inspect_evidence_ok,
        "dispatch_tools": dispatch_tools,
        "critical_failures": critical_failures,
        "understanding_contract": route.get("understanding_contract") or {},
        "traceable": bool(calls),
        "readiness_issues": [
            *([f"Missing required tools: {', '.join(missing_required)}"] if missing_required else []),
            *([f"Required tools lack meaningful output: {', '.join(required_without_output)}"] if required_without_output else []),
            *([f"Forbidden tools present: {', '.join(forbidden_present)}"] if forbidden_present else []),
            *(["Required tools were not called in contract order."] if not ordered else []),
            *(["Dispatch tool used outside role boundary."] if not boundary_ok else []),
            *(["Dispatch-capable role did not include validate_policy."] if not policy_ok else []),
            *(["Policy gate lacks concrete gate evidence."] if not policy_evidence_ok else []),
            *(["Dispatch tool lacks receiver receipt evidence."] if not dispatch_receipts_ok else []),
            *(["QA inspection tools lack concrete inspection evidence."] if not inspect_evidence_ok else []),
        ],
    }


def _synthetic_role_trace(route: dict[str, Any]) -> dict[str, Any]:
    role = str(route.get("selected_role") or "agent")
    calls = [
        {
            "tool": str(tool),
            "server": "parkpulse.agent_roles",
            "status": "ok",
            "output": {**_synthetic_tool_output(str(tool), role), "role": role, "source": "deliberate_role_eval_synthetic_trace"},
        }
        for tool in route.get("required_tools", [])
    ]
    return {
        "mode": "deliberate_role_eval_trace",
        "server": "parkpulse.agent_roles",
        "tool_count": len(calls),
        "tool_calls": calls,
        "summary": {
            "selected_role": route.get("selected_role"),
            "selected_skill": route.get("skill"),
            "policy_gates": route.get("policy_gates", []),
        },
    }


def build_deliberate_role_eval_report() -> dict[str, Any]:
    role_modes = ["scan", "react", "proact", "customer", "qa"]
    role_results = []
    for mode in role_modes:
        route = route_agent_role("deliberate role eval", mode)
        trace = _synthetic_role_trace(route)
        deliberate_eval = evaluate_agent_role_trace(route, trace)
        trace["deliberate_eval"] = deliberate_eval
        role_results.append(
            {
                "role": mode,
                "skill": route.get("skill"),
                "status": deliberate_eval["status"],
                "score": deliberate_eval["score"],
                "understanding_contract": route.get("understanding_contract"),
                "deliberate_tool_use": route.get("deliberate_tool_use"),
                "evaluation_contract": route.get("evaluation_contract"),
                "trace": trace,
                "readiness_issues": deliberate_eval.get("readiness_issues", []),
            }
        )
    failed = [row for row in role_results if row["status"] != "passed"]
    average = round(sum(float(row["score"]) for row in role_results) / max(1, len(role_results)), 2)
    return {
        "status": "passed" if not failed and average >= 88 else "failed",
        "mode": "deliberate_role_eval_report",
        "role_count": len(role_results),
        "passed_role_count": len(role_results) - len(failed),
        "failed_role_count": len(failed),
        "average_score": average,
        "roles": role_results,
        "readiness_issues": sorted({issue for row in role_results for issue in row.get("readiness_issues", [])}),
        "decision": "allow_role_agent_deliberate_tool_use_claim" if not failed and average >= 88 else "block_until_role_tool_eval_passes",
    }


def _list_len(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _role_work_depth_checks(role: str, payload: dict[str, Any], trace_eval: dict[str, Any]) -> dict[str, bool]:
    route = payload.get("role_route") if isinstance(payload.get("role_route"), dict) else payload.get("route", {})
    route = route if isinstance(route, dict) else {}
    work = payload.get("role_work_contract") if isinstance(payload.get("role_work_contract"), dict) else {}
    role_specific = work.get("role_specific_work") if isinstance(work.get("role_specific_work"), dict) else {}
    required_tools = trace_eval.get("required_sequence", []) if isinstance(trace_eval.get("required_sequence"), list) else []
    tool_rationale = work.get("tool_rationale", []) if isinstance(work.get("tool_rationale"), list) else []
    tool_rationale_tools = {str(item.get("tool")) for item in tool_rationale if isinstance(item, dict) and item.get("tool")}
    checks: dict[str, bool] = {
        "has_role_description": bool(work.get("role_description")),
        "has_mission": bool(work.get("mission")),
        "has_boundary": bool(work.get("boundary")),
        "has_input_evidence": _list_len(work.get("input_evidence")) >= 2,
        "has_reasoning_steps": _list_len(work.get("reasoning_steps")) >= 4,
        "has_tool_rationale": len(tool_rationale_tools.intersection({str(tool) for tool in required_tools})) >= min(len(required_tools), max(2, int(route.get("deliberate_tool_use", {}).get("minimum_tool_coverage", 2) or 2))),
        "has_output_evidence": _list_len(work.get("output_evidence")) >= 2,
        "has_success_criteria": _list_len(work.get("success_criteria")) >= 2,
        "has_escalation_or_stop": _list_len(work.get("escalation_or_stop_conditions")) >= 2,
        "route_has_understanding": _list_len((route.get("understanding_contract", {}) if isinstance(route.get("understanding_contract"), dict) else {}).get("must_understand")) >= 4,
        "route_has_tool_sequence": _list_len((route.get("deliberate_tool_use", {}) if isinstance(route.get("deliberate_tool_use"), dict) else {}).get("required_sequence")) >= 3,
    }
    if role == "scan":
        checks["scan_uncertainty_explained"] = bool(role_specific.get("uncertainty_disclosure"))
        checks["scan_next_role_condition"] = bool(role_specific.get("recommended_next_role_condition"))
    elif role == "react":
        checks["react_alternatives_considered"] = _list_len(role_specific.get("alternatives_considered")) >= 2
        checks["react_rejected_actions_named"] = _list_len(role_specific.get("rejected_actions")) >= 1
        checks["react_receivers_named"] = _list_len(role_specific.get("receiver_channels")) >= 1
    elif role == "proact":
        checks["proact_baseline_compared"] = bool(role_specific.get("baseline_vs_action"))
        checks["proact_observed_response_used"] = bool(role_specific.get("observed_response"))
        checks["proact_learning_rule_present"] = bool(role_specific.get("learning_rule"))
    elif role == "customer":
        checks["customer_public_sources_named"] = _list_len(role_specific.get("public_data_sources")) >= 2
        checks["customer_privacy_boundary_named"] = bool(role_specific.get("privacy_boundary"))
        checks["customer_actions_bounded"] = _list_len(role_specific.get("allowed_customer_actions")) >= 1
    elif role == "qa":
        checks["qa_failure_modes_named"] = _list_len(role_specific.get("failure_modes_checked")) >= 4
        checks["qa_observability_named"] = _list_len(role_specific.get("observability_checks")) >= 3
        checks["qa_idempotency_named"] = bool(role_specific.get("idempotency_check"))
    return checks


def _role_output_checks(role: str, payload: dict[str, Any], trace_eval: dict[str, Any]) -> dict[str, Any]:
    telemetry = payload.get("run_telemetry", {}) if isinstance(payload.get("run_telemetry"), dict) else {}
    delivery = telemetry.get("delivery", {}) if isinstance(telemetry.get("delivery"), dict) else payload.get("delivery", {})
    delivery = delivery if isinstance(delivery, dict) else {}
    summary = delivery.get("summary", {}) if isinstance(delivery.get("summary"), dict) else {}
    dispatch_count = int(summary.get("total") or payload.get("role_run", {}).get("dispatch_count") or 0)
    receipt = payload.get("role_receipt", {}) if isinstance(payload.get("role_receipt"), dict) else {}
    called_tools = [str(tool) for tool in trace_eval.get("called_tools", [])]
    dispatch_tools = [tool for tool in called_tools if tool.startswith("dispatch_")]
    issues: list[str] = []
    checks: dict[str, bool] = {
        "trace_eval_passed": trace_eval.get("status") == "passed",
        "trace_has_no_critical_failures": not trace_eval.get("critical_failures"),
        "required_tools_have_outputs": not trace_eval.get("required_without_output"),
        "selected_role_matches": str(payload.get("selected_role") or receipt.get("role") or role) == role,
    }
    depth_checks = _role_work_depth_checks(role, payload, trace_eval)
    checks["role_setup_complete"] = all(
        depth_checks.get(name) is True
        for name in (
            "has_role_description",
            "has_mission",
            "has_boundary",
            "route_has_understanding",
            "route_has_tool_sequence",
        )
    )
    checks["role_work_depth_passed"] = all(depth_checks.values())
    if role == "scan":
        checks["read_only_no_dispatch"] = dispatch_count == 0
        checks["has_scan_output"] = bool(payload.get("scan") or payload.get("operator_response"))
        checks["has_signal_evidence"] = bool((payload.get("scan", {}) if isinstance(payload.get("scan"), dict) else {}).get("signals") or (payload.get("scan", {}) if isinstance(payload.get("scan"), dict) else {}).get("evidence"))
        checks["no_dispatch_tools_called"] = not dispatch_tools
    elif role == "react":
        checks["has_receiver_payloads"] = dispatch_count > 0
        checks["policy_gate_present"] = bool(trace_eval.get("policy_ok") and trace_eval.get("policy_evidence_ok"))
        checks["dispatch_receipts_present"] = bool(trace_eval.get("dispatch_receipts_ok"))
        checks["has_role_receipt"] = bool(receipt)
        receipt_dispatch_ids = receipt.get("dispatch_ids")
        if not receipt_dispatch_ids:
            receipt_dispatch_ids = (payload.get("unified_receipt", {}).get("dispatches", {}) if isinstance(payload.get("unified_receipt"), dict) else {}).get("ids")
        checks["receipt_has_dispatch_ids"] = bool(receipt_dispatch_ids)
    elif role == "proact":
        checks["has_receiver_payloads"] = dispatch_count > 0
        checks["learning_observed"] = str(receipt.get("learning_update", {}).get("validity") or "") == "observed_response"
        checks["policy_gate_present"] = bool(trace_eval.get("policy_ok") and trace_eval.get("policy_evidence_ok"))
        checks["dispatch_receipts_present"] = bool(trace_eval.get("dispatch_receipts_ok"))
    elif role == "customer":
        checks["customer_read_only"] = dispatch_count == 0
        checks["has_customer_answer"] = bool(payload.get("answer") or payload.get("operator_response"))
        checks["no_operator_dispatch"] = not any(str(tool).startswith("dispatch_") for tool in trace_eval.get("called_tools", []))
        actions = payload.get("actions", []) if isinstance(payload.get("actions"), list) else []
        action_ids = {str(action.get("id")) for action in actions if isinstance(action, dict)}
        checks["public_actions_only"] = not action_ids or action_ids.issubset({"show_route", "send_to_phone"})
    elif role == "qa":
        checks["read_only_no_dispatch"] = dispatch_count == 0
        checks["has_go_no_go"] = bool(payload.get("go_no_go_recommendation") or receipt.get("go_no_go"))
        checks["qa_receipt_read_only"] = bool(receipt.get("read_only", True))
        checks["inspection_evidence_present"] = bool(trace_eval.get("inspect_evidence_ok"))
        checks["has_failure_mode_matrix"] = bool(payload.get("failure_mode_matrix"))
    for name, passed in checks.items():
        if not passed:
            issues.append(name)
    score = max(0, min(100, int(trace_eval.get("score") or 0) - len(issues) * 10))
    return {
        "mode": "real_role_output_eval",
        "role": role,
        "status": "passed" if score >= 88 and not issues else "failed" if score < 70 or issues else "warning",
        "score": score,
        "checks": checks,
        "role_work_depth_checks": depth_checks,
        "dispatch_count": dispatch_count,
        "readiness_issues": issues,
    }


def build_real_deliberate_role_eval_report(role_payloads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    role_modes = ["scan", "react", "proact", "customer", "qa"]
    results = []
    for mode in role_modes:
        payload = role_payloads.get(mode, {}) if isinstance(role_payloads.get(mode), dict) else {}
        route = payload.get("role_route") if isinstance(payload.get("role_route"), dict) else route_agent_role("real role trace eval", mode)
        trace = payload.get("digital_twin_tools", {}) if isinstance(payload.get("digital_twin_tools"), dict) else _synthetic_role_trace(route)
        trace_eval = trace.get("deliberate_eval") if isinstance(trace.get("deliberate_eval"), dict) else evaluate_agent_role_trace(route, trace, payload)
        trace["deliberate_eval"] = trace_eval
        output_eval = _role_output_checks(mode, payload, trace_eval)
        combined_score = round((float(trace_eval.get("score") or 0) + float(output_eval.get("score") or 0)) / 2, 2)
        status = "passed" if trace_eval.get("status") == "passed" and output_eval.get("status") == "passed" and combined_score >= 88 else "failed"
        results.append(
            {
                "role": mode,
                "status": status,
                "score": combined_score,
                "trace_eval": trace_eval,
                "output_eval": output_eval,
                "trace": trace,
                "readiness_issues": [*trace_eval.get("readiness_issues", []), *output_eval.get("readiness_issues", [])],
            }
        )
    failed = [row for row in results if row["status"] != "passed"]
    average = round(sum(float(row["score"]) for row in results) / max(1, len(results)), 2)
    return {
        "status": "passed" if not failed and average >= 88 else "failed",
        "mode": "real_trace_deliberate_role_eval_report",
        "role_count": len(results),
        "passed_role_count": len(results) - len(failed),
        "failed_role_count": len(failed),
        "average_score": average,
        "roles": results,
        "readiness_issues": sorted({issue for row in results for issue in row.get("readiness_issues", [])}),
        "decision": "allow_real_trace_role_agent_tool_use_claim" if not failed and average >= 88 else "block_until_real_role_traces_pass",
    }


def _fixture_roles(report: dict[str, Any]) -> set[str]:
    fixtures = report.get("fixtures", []) if isinstance(report.get("fixtures"), list) else []
    return {
        str(row.get("role"))
        for row in fixtures
        if isinstance(row, dict)
        and row.get("role")
        and row.get("expected_failures_met") is True
        and (row.get("eval", {}) if isinstance(row.get("eval"), dict) else row).get("status") != "passed"
    }


def _sample_status_by_role(sampled_report: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(sampled_report, dict) or not isinstance(sampled_report.get("samples"), list):
        return {}
    by_role: dict[str, dict[str, Any]] = {}
    for row in sampled_report.get("samples", []):
        if not isinstance(row, dict):
            continue
        role = str(row.get("role") or "")
        if not role:
            continue
        current = by_role.setdefault(role, {"count": 0, "failed_count": 0, "scores": []})
        current["count"] += 1
        current["failed_count"] += 0 if row.get("status") == "passed" else 1
        current["scores"].append(float(row.get("score") or 0))
    for role, summary in by_role.items():
        scores = summary.get("scores", [])
        summary["average_score"] = round(sum(scores) / max(1, len(scores)), 2)
        summary["status"] = "passed" if summary.get("count", 0) > 0 and summary.get("failed_count", 0) == 0 and summary["average_score"] >= 88 else "failed"
    return by_role


def build_agent_role_product_readiness_report(
    real_report: dict[str, Any],
    *,
    synthetic_report: dict[str, Any] | None = None,
    sampled_report: dict[str, Any] | None = None,
    adversarial_report: dict[str, Any] | None = None,
    negative_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    synthetic_roles = {
        str(row.get("role")): row
        for row in (synthetic_report or {}).get("roles", [])
        if isinstance(row, dict) and row.get("role")
    }
    real_roles = {
        str(row.get("role")): row
        for row in real_report.get("roles", [])
        if isinstance(row, dict) and row.get("role")
    }
    negative_roles = _fixture_roles(negative_report or {})
    adversarial_roles = _fixture_roles(adversarial_report or {})
    sample_by_role = _sample_status_by_role(sampled_report)
    sample_report_status = (sampled_report or {}).get("status")

    role_results = []
    for role in ("scan", "react", "proact", "customer", "qa"):
        real = real_roles.get(role, {})
        trace_eval = real.get("trace_eval", {}) if isinstance(real.get("trace_eval"), dict) else {}
        output_eval = real.get("output_eval", {}) if isinstance(real.get("output_eval"), dict) else {}
        output_checks = output_eval.get("checks", {}) if isinstance(output_eval.get("checks"), dict) else {}
        synthetic = synthetic_roles.get(role, {})
        sample = sample_by_role.get(role)
        checks: dict[str, bool] = {
            "synthetic_eval_passed": synthetic.get("status") == "passed" if synthetic_report else True,
            "real_eval_passed": real.get("status") == "passed",
            "trace_eval_passed": trace_eval.get("status") == "passed",
            "trace_no_critical_failures": not trace_eval.get("critical_failures"),
            "trace_required_outputs_present": not trace_eval.get("required_without_output"),
            "output_eval_passed": output_eval.get("status") == "passed",
            "negative_fixture_covered": role in negative_roles,
            "adversarial_fixture_covered": role in adversarial_roles,
            "sampled_evidence_passed": sample is None if sample_report_status in {None, "skipped"} else bool(sample and sample.get("status") == "passed"),
        }
        for name in ROLE_PRODUCT_READY_CHECKS[role]:
            if name in output_checks:
                checks[name] = output_checks[name] is True
            elif name not in checks:
                checks[name] = False
        failed_checks = [name for name, passed in checks.items() if not passed]
        score = max(0, min(100, int(round(float(real.get("score") or 0))) - len(failed_checks) * 8))
        role_results.append(
            {
                "role": role,
                "status": "product_ready" if not failed_checks and score >= 88 else "not_ready",
                "score": score,
                "required_checks": list(ROLE_PRODUCT_READY_CHECKS[role]),
                "checks": checks,
                "failed_checks": failed_checks,
                "sample_evidence": sample or {"status": "skipped" if sample_report_status in {None, "skipped"} else "missing"},
                "readiness_issues": [f"{role}:{check}" for check in failed_checks],
            }
        )
    not_ready = [row for row in role_results if row["status"] != "product_ready"]
    return {
        "status": "passed" if not not_ready else "failed",
        "mode": "agent_role_product_readiness_report",
        "role_count": len(role_results),
        "product_ready_role_count": len(role_results) - len(not_ready),
        "not_ready_role_count": len(not_ready),
        "roles": role_results,
        "readiness_issues": sorted({issue for row in role_results for issue in row.get("readiness_issues", [])}),
        "decision": "all_agent_roles_product_ready" if not not_ready else "block_until_each_agent_role_is_product_ready",
    }


def build_deliberate_role_negative_fixtures() -> dict[str, Any]:
    fixtures = [
        ("scan_dispatch_violation", "scan", ["get_park_state", "dispatch_guest_message"], {"forbidden:dispatch_guest_message", "dispatch_boundary_violation"}),
        ("react_missing_policy", "react", ["get_park_state", "retrieve_similar_incidents", "simulate_action", "dispatch_guest_message"], {"missing_required:validate_policy", "policy_tool_missing"}),
        ("proact_learning_without_outcome", "proact", ["get_noisy_observation", "retrieve_similar_incidents", "simulate_action", "write_decision_memory"], {"missing_required:validate_policy", "missing_required:score_outcome", "policy_tool_missing"}),
        ("customer_internal_dispatch", "customer", ["get_park_state", "dispatch_worker_task"], {"forbidden:dispatch_worker_task", "dispatch_boundary_violation"}),
        ("qa_missing_observability", "qa", ["get_park_state", "simulate_action", "validate_policy"], {"missing_required:inspect_delivery_receipts", "missing_required:inspect_observability_contract", "inspection_evidence_missing"}),
    ]
    results = []
    for fixture_id, role, tools, expected_failures in fixtures:
        route = route_agent_role(fixture_id, role)
        trace = {
            "mode": "negative_deliberate_role_fixture",
            "tool_calls": [{"tool": tool, "status": "ok", "output": _synthetic_tool_output(tool, role)} for tool in tools],
            "summary": {"selected_role": role, "fixture_id": fixture_id},
        }
        eval_result = evaluate_agent_role_trace(route, trace)
        critical_failures = set(eval_result.get("critical_failures", []))
        expected_failures_met = expected_failures.issubset(critical_failures)
        results.append(
            {
                "id": fixture_id,
                "role": role,
                "expected": "failed_with_expected_critical_failures",
                "expected_failures": sorted(expected_failures),
                "expected_failures_met": expected_failures_met,
                "eval": eval_result,
            }
        )
    passed_as_bad = [row for row in results if row["eval"]["status"] == "passed"]
    wrong_reason = [row for row in results if not row["expected_failures_met"]]
    return {
        "status": "passed" if not passed_as_bad and not wrong_reason else "failed",
        "mode": "deliberate_role_negative_fixture_eval",
        "fixture_count": len(results),
        "caught_count": len(results) - len(passed_as_bad),
        "missed_count": len(passed_as_bad),
        "wrong_reason_count": len(wrong_reason),
        "fixtures": results,
        "decision": "negative_fixtures_caught" if not passed_as_bad and not wrong_reason else "fix_deliberate_eval_negative_fixture_gap",
    }
