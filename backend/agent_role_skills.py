from __future__ import annotations

from copy import deepcopy
from typing import Any


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
        "purpose": "Evaluate whether ParkPulse is production-reliable across scan, react, proact, policy gates, fallbacks, dispatch receipts, observability, and load behavior.",
        "trigger_examples": [
            "production reliability qa",
            "reliability review",
            "failure mode matrix",
            "go no-go",
            "pre-deploy qa",
            "test production readiness",
        ],
        "mcp_tools": [
            "get_park_state",
            "get_noisy_observation",
            "retrieve_similar_incidents",
            "simulate_action",
            "validate_policy",
            "score_decision_quality",
            "inspect_delivery_receipts",
            "inspect_runtime_status",
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


def list_agent_role_skills() -> dict[str, Any]:
    return {
        "server": "parkpulse.agent_roles",
        "style": "mcp_skill_registry",
        "principle": "Route work by role: customer support answers guests, scan reads and explains, react handles confirmed incidents, proact prevents failures and learns from response.",
        "roles": deepcopy(ROLE_SKILLS),
        "routing_order": ["qa", "customer", "scan", "react", "proact"],
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
    )
    if explicit in {"scan", "react", "proact", "qa", "customer"}:
        selected = explicit
    elif any(term in text for term in qa_terms):
        selected = "qa"
    elif any(term in text for term in customer_terms) and not any(term in text for term in direct_action_terms):
        selected = "customer"
    elif any(term in text for term in ("proact", "prevent", "early", "before", "learn", "take rate", "future")):
        selected = "proact"
    elif any(term in text for term in weak_signal_terms) and not any(term in text for term in direct_action_terms):
        selected = "proact"
    elif any(term in text for term in direct_action_terms) or "medical" in text:
        selected = "react"
    else:
        selected = "scan"
    role = next(item for item in ROLE_SKILLS if item["mode"] == selected)
    return {
        "selected_role": selected,
        "skill": role["skill"],
        "why": _route_reason(selected),
        "required_tools": role["mcp_tools"],
        "policy_gates": role["policy_gates"],
        "expected_receipt": role["output_artifacts"],
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
