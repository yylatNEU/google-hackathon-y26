from __future__ import annotations

import os
from copy import deepcopy
from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Any, Callable

from policy_engine import get_policy_engine


class _NoopSpan:
    def set_attribute(self, *_args, **_kwargs) -> None:
        return None


class _NoopTracer:
    def start_as_current_span(self, *_args, **_kwargs):
        return nullcontext(_NoopSpan())


def _get_tracer(name: str):
    if str(os.getenv("PARKPULSE_ENABLE_OTEL_SPANS", "")).strip().lower() not in {"1", "true", "yes", "on"}:
        return _NoopTracer()
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except Exception:
        return _NoopTracer()


_tracer = _get_tracer("parkpulse.multi_agent")


DEPARTMENT_AGENT_LOOP: list[str] = ["observe", "interpret", "predict", "recommend", "justify", "trace"]


DEPARTMENT_TOOL_CONTRACT_FIELDS: list[str] = [
    "department",
    "tool",
    "intent",
    "evidence",
    "risk_level",
    "policy_check",
    "expected_outcome",
    "rollback",
]


REAL_ACTION_TOOLS: set[str] = {
    "dispatch_guest_message",
    "dispatch_worker_task",
    "dispatch_equipment_command",
    "dispatch_receiver_payload",
    "execute_approved_action",
}


JUDGE_TRACE_EVAL_CONTRACT: dict[str, Any] = {
    "owner_agent": "gcp_eval_judge_agent",
    "owner_department": "qa_judge",
    "owner_department_agent": "Eval Agent",
    "trace_read_tools": ["get_full_trace", "get_tool_calls", "get_outcomes", "get_policy_references"],
    "eval_write_tools": ["score_decision", "flag_failure", "create_regression_test"],
    "inspection_tools": ["score_decision_quality", "inspect_observability_contract", "inspect_delivery_receipts"],
    "runtime_status_tools": [
        "gcp_trace_eval.get_gcp_trace_eval_status",
        "gcp_trace_eval.build_gcp_eval_trace",
        "gcp_trace_eval.verify_gcp_trace_export",
        "evaluator_loop.evaluator_loop_status",
        "evaluator_loop.build_hosted_evaluator_loop",
    ],
    "api_surfaces": [
        "GET /api/gcp/trace-eval-status",
        "GET /api/gcp/trace-export-verify",
        "GET /api/gcp/evaluator-loop",
        "POST /api/gcp/evaluator-loop/verify",
        "GET /api/park/agent-role-eval",
        "GET /api/park/agent-role-eval?real=1",
    ],
    "required_regression_tests": [
        "backend/test_trace_context.py",
        "backend/test_gcp_operations.py::test_gcp_trace_eval_public_dict_configured_uninitialized_sink",
        "backend/test_coverage_low_hanging.py::test_evaluator_loop_vertex_metric_and_transport_branches",
        "backend/test_coverage_low_hanging.py::test_evaluator_loop_rest_success_http_error_and_summary",
        "backend/test_coverage_low_hanging.py::test_multi_agent_boundary_helpers_and_conflict_branches",
        "backend/test_production_reliability_qa_agent.py",
    ],
    "routing_rule": "Trace/eval evidence is read by the QA/Eval Judge, scored or flagged by the QA/Eval Judge, then returned to Decision Bridge and Tool Executor as a gate result.",
}


JUDGE_TRACE_EVAL_EXCLUSIVE_TOOLS: set[str] = set(JUDGE_TRACE_EVAL_CONTRACT["trace_read_tools"]) | set(
    JUDGE_TRACE_EVAL_CONTRACT["eval_write_tools"]
)


DEPARTMENT_TOOL_ACCESS_MAP: dict[str, dict[str, list[str]]] = {
    "operations": {
        "read_tools": ["ride_status", "queue_length", "park_map", "weather", "event_schedule"],
        "write_action_tools": ["create_ops_alert", "recommend_route_change", "request_staffing_move"],
    },
    "safety": {
        "read_tools": ["incident_reports", "ride_inspection_status", "crowd_density", "weather", "policy_book"],
        "write_action_tools": ["safety_alert", "close_reopen_recommendation", "require_human_approval"],
    },
    "maintenance": {
        "read_tools": ["asset_history", "sensor_health", "inspection_logs", "spare_parts_inventory"],
        "write_action_tools": ["create_work_order", "assign_technician", "update_repair_status"],
    },
    "guest_experience": {
        "read_tools": ["guest_complaints", "app_feedback", "sentiment", "notification_history"],
        "write_action_tools": ["draft_guest_message", "issue_recovery_offer", "create_support_ticket"],
    },
    "food_retail": {
        "read_tools": ["pos_sales", "inventory", "queue_near_shops", "event_schedule", "weather"],
        "write_action_tools": ["inventory_alert", "restock_request", "pause_launch_promo"],
    },
    "finance": {
        "read_tools": ["ticket_sales", "refund_data", "labor_cost", "pos_revenue", "outage_impact"],
        "write_action_tools": ["revenue_impact_report", "refund_recommendation", "budget_alert"],
    },
    "hr_labor": {
        "read_tools": ["staff_schedule", "attendance", "overtime", "fatigue_risk", "skill_matrix"],
        "write_action_tools": ["shift_adjustment_recommendation", "overtime_warning", "break_reminder"],
    },
    "marketing": {
        "read_tools": ["campaign_calendar", "guest_segments", "demand_forecast", "weather_events", "crowd_density"],
        "write_action_tools": ["draft_campaign", "launch_pause_promo", "redirect_offer"],
    },
    "security": {
        "read_tools": ["crowd_density", "incident_reports", "access_logs", "lost_child_reports"],
        "write_action_tools": ["dispatch_alert", "escalation_request", "zone_control_recommendation"],
    },
    "compliance": {
        "read_tools": ["policy_books", "privacy_rules", "safety_rules", "labor_rules", "audit_logs"],
        "write_action_tools": ["block_action", "require_approval", "generate_compliance_note"],
    },
    "executive": {
        "read_tools": ["department_summaries", "risk_scores", "financial_impact", "guest_impact"],
        "write_action_tools": ["approve_action", "reject_action", "set_priority", "choose_tradeoff"],
    },
    "qa_judge": {
        "read_tools": ["full_trace", "tool_calls", "outcomes", "policy_references"],
        "write_action_tools": ["score_decision", "flag_failure", "create_regression_test"],
    },
}


DEPARTMENT_AGENT_MAP: list[dict[str, Any]] = [
    {
        "department": "operations",
        "label": "Operations",
        "canonical_agent": "Ops Agent",
        "implementation_agents": ["ride_ops_agent", "guest_flow_agent", "traffic_flow_agent", "planning_agent"],
        "main_job": "ride flow, queues, downtime, and staffing pressure",
        "tool_families": ["queue tools", "ride status tools", "simulation tools"],
    },
    {
        "department": "safety",
        "label": "Safety",
        "canonical_agent": "Safety Agent",
        "implementation_agents": ["safety_policy_agent"],
        "main_job": "incident risk, ride reopening constraints, and crowd hazard",
        "tool_families": ["policy tools", "runtime inspection tools", "approval-gate tools"],
    },
    {
        "department": "maintenance",
        "label": "Maintenance",
        "canonical_agent": "Maintenance Agent",
        "implementation_agents": ["facilities_energy_agent", "memory_ops_agent"],
        "main_job": "work orders, asset health, energy posture, and inspection history",
        "tool_families": ["asset status tools", "equipment command tools", "memory inspection tools"],
    },
    {
        "department": "guest_experience",
        "label": "Guest Experience",
        "canonical_agent": "Guest Agent",
        "implementation_agents": ["guest_flow_agent", "customer_support_agent"],
        "main_job": "complaints, sentiment, notifications, routing, and recovery offers",
        "tool_families": ["guest messaging tools", "CRM/customer tools", "public route tools"],
    },
    {
        "department": "food_retail",
        "label": "Food & Retail",
        "canonical_agent": "Commerce Agent",
        "implementation_agents": ["food_demand_agent"],
        "main_job": "demand forecast, inventory, staffing, and promotions",
        "tool_families": ["POS tools", "inventory tools", "menu/promo tools"],
    },
    {
        "department": "finance",
        "label": "Finance",
        "canonical_agent": "Finance Agent",
        "implementation_agents": ["finance_agent"],
        "main_job": "revenue impact, labor cost, refunds, and compensation decisions",
        "tool_families": ["revenue tools", "refund/comp tools", "scorecard tools"],
    },
    {
        "department": "hr_labor",
        "label": "HR / Labor",
        "canonical_agent": "Labor Agent",
        "implementation_agents": ["staffing_agent"],
        "main_job": "shift coverage, overtime, fatigue, and labor rules",
        "tool_families": ["schedule tools", "overtime tools", "worker-task tools"],
    },
    {
        "department": "marketing",
        "label": "Marketing",
        "canonical_agent": "Marketing Agent",
        "implementation_agents": ["event_creative_agent"],
        "main_job": "campaigns, event demand, offers, and guest segmentation",
        "tool_families": ["campaign tools", "segment tools", "offer tools"],
    },
    {
        "department": "security",
        "label": "Security",
        "canonical_agent": "Security Agent",
        "implementation_agents": ["security_agent", "safety_policy_agent", "staffing_agent"],
        "main_job": "crowd control, lost child, access control, and escalation",
        "tool_families": ["incident tools", "access-control tools", "escalation tools"],
    },
    {
        "department": "compliance",
        "label": "Compliance",
        "canonical_agent": "Compliance Agent",
        "implementation_agents": ["safety_policy_agent", "logic_audit_agent"],
        "main_job": "privacy, safety regulation, and policy constraints",
        "tool_families": ["privacy tools", "policy/risk tools", "audit tools"],
    },
    {
        "department": "executive",
        "label": "Executive",
        "canonical_agent": "Executive Agent",
        "implementation_agents": ["decision_bridge_agent"],
        "main_job": "cross-department tradeoff and final recommendation",
        "tool_families": ["approval tools", "routing tools", "candidate-comparison tools"],
    },
    {
        "department": "qa_judge",
        "label": "QA Judge",
        "canonical_agent": "Eval Agent",
        "implementation_agents": ["gcp_eval_judge_agent", "logic_audit_agent", "delivery_proof_agent"],
        "main_job": "trace quality, tool use, delivery proof, and failure-mode review",
        "tool_families": ["eval tools", "trace tools", "delivery-proof tools"],
    },
]


AGENT_DEPARTMENT_OVERRIDES: dict[str, str] = {
    "park_understanding_agent": "executive",
    "ride_ops_agent": "operations",
    "guest_flow_agent": "guest_experience",
    "customer_support_agent": "guest_experience",
    "staffing_agent": "hr_labor",
    "food_demand_agent": "food_retail",
    "facilities_energy_agent": "maintenance",
    "event_setup_agent": "operations",
    "event_creative_agent": "marketing",
    "traffic_flow_agent": "operations",
    "planning_agent": "operations",
    "placement_agent": "operations",
    "safety_policy_agent": "safety",
    "finance_agent": "finance",
    "security_agent": "security",
    "decision_bridge_agent": "executive",
    "logic_audit_agent": "compliance",
    "memory_ops_agent": "maintenance",
    "delivery_proof_agent": "qa_judge",
    "autodream_agent": "qa_judge",
    "gcp_eval_judge_agent": "qa_judge",
    "tool_executor_agent": "tool_executor",
}


AGENT_REGISTRY: list[dict[str, Any]] = [
    {
        "agent_id": "park_understanding_agent",
        "name": "Park Understanding Agent",
        "role": "Builds a source-grounded operating picture from live park state and MongoDB memory.",
        "mode": ["reactive", "proactive", "event_planning"],
        "owns": ["park model", "source signal summary", "memory grounding"],
        "blocked": ["inventing capacity", "inventing equipment", "inventing staff"],
        "policy_refs": ["PARK-OPS-001", "PARK-OPS-002"],
    },
    {
        "agent_id": "ride_ops_agent",
        "name": "Ride Ops Agent",
        "role": "Reasons over ride status, queue intake, capacity, dispatch pressure, and maintenance holds.",
        "mode": ["reactive", "event_planning"],
        "owns": ["ride wait pressure", "queue intake recommendation", "throughput tradeoff"],
        "blocked": ["reopening rides", "bypassing maintenance", "automated safety control"],
        "policy_refs": ["PARK-SAFE-001", "PARK-SAFE-002"],
    },
    {
        "agent_id": "guest_flow_agent",
        "name": "Guest Flow Agent",
        "role": "Balances crowd density, paths, routing targets, guest nudges, and take-rate assumptions.",
        "mode": ["reactive", "proactive", "event_planning"],
        "owns": ["routing mix", "crowd redistribution", "bottleneck risk", "guest-app nudges"],
        "blocked": ["routing all guests to one place", "misleading queue promises"],
        "policy_refs": ["PARK-EXP-001", "PARK-MSG-001"],
    },
    {
        "agent_id": "customer_support_agent",
        "name": "Customer Support Agent",
        "role": "Answers guest kiosk questions with public park state, wait-aware recommendations, route notes, and customer app handoff actions.",
        "mode": ["customer_self_service"],
        "owns": ["guest-facing answers", "public wait recommendations", "route hints", "customer app handoff"],
        "blocked": [
            "operator console redirects",
            "worker dispatch",
            "equipment commands",
            "internal policy disclosure",
            "private guest data",
            "medical diagnosis",
            "individual compensation promises",
        ],
        "policy_refs": ["PARK-CARE-001", "PARK-EXP-001", "PARK-MSG-001"],
    },
    {
        "agent_id": "staffing_agent",
        "name": "Staffing Agent",
        "role": "Checks labor shortages, role compatibility, break protection, and worker stress.",
        "mode": ["reactive", "proactive", "event_planning"],
        "owns": ["redeployment feasibility", "break protection", "role-compatible tasking"],
        "blocked": ["moving uncertified workers", "delaying protected breaks"],
        "policy_refs": ["PARK-LABOR-001", "PARK-LABOR-002", "PARK-LABOR-003"],
    },
    {
        "agent_id": "food_demand_agent",
        "name": "Food Demand Agent",
        "role": "Reasons over food demand, mobile orders, inventory pressure, kitchen load, and menu changes.",
        "mode": ["reactive", "proactive", "event_planning"],
        "owns": ["menu suppression", "food demand routing", "pickup ETA pressure"],
        "blocked": ["promoting unavailable items", "over-promising pickup times"],
        "policy_refs": ["PARK-OPS-003", "PARK-EXP-001"],
    },
    {
        "agent_id": "facilities_energy_agent",
        "name": "Facilities/Energy Agent",
        "role": "Balances HVAC comfort, noncritical load control, temporary power, and equipment commands.",
        "mode": ["reactive", "proactive", "event_planning"],
        "owns": ["HVAC comfort protection", "noncritical load shedding", "equipment feasibility"],
        "blocked": ["reducing comfort in shelter zones", "safety-critical hardware changes"],
        "policy_refs": ["PARK-EQUIP-001", "PARK-EQUIP-002"],
    },
    {
        "agent_id": "event_setup_agent",
        "name": "Event Setup Agent",
        "role": "Plans temporary event readiness, setup windows, dependencies, and pre-stage actions.",
        "mode": ["proactive", "event_planning"],
        "owns": ["setup timing", "temporary equipment staging", "dependency checklist"],
        "blocked": ["late setup without dependencies", "blocking emergency access"],
        "policy_refs": ["PARK-EVENT-001", "PARK-EVENT-003"],
    },
    {
        "agent_id": "event_creative_agent",
        "name": "Event Creative Agent",
        "role": "Turns the operator brief into themed event concepts while staying inside park and policy constraints.",
        "mode": ["event_planning"],
        "owns": ["event concepts", "guest segment fit", "experience intent"],
        "blocked": ["creative ideas that ignore capacity", "themes that conflict with family-safe windows"],
        "policy_refs": ["PARK-EVENT-004", "PARK-EXP-001"],
    },
    {
        "agent_id": "traffic_flow_agent",
        "name": "Traffic Flow Agent",
        "role": "Models time-block movement, queue spillback, path pressure, and before/after congestion risk.",
        "mode": ["proactive", "event_planning"],
        "owns": ["temporal flow", "path capacity", "spillback forecast"],
        "blocked": ["static one-time routing plans", "creating a new bottleneck while solving another"],
        "policy_refs": ["PARK-OPS-002", "PARK-EVENT-001"],
    },
    {
        "agent_id": "planning_agent",
        "name": "Park Planning Agent",
        "role": "Turns the learned digital twin, showtime waves, map constraints, memory, and policy into an executable multi-wave operating plan.",
        "mode": ["proactive", "event_planning"],
        "owns": ["multi-wave plan", "planner horizon", "scenario rehearsal", "lesson carryover", "owner deadlines"],
        "blocked": ["dispatching without Decision Bridge", "ignoring measured outcome carryover", "creating plans without policy gates"],
        "policy_refs": ["PARK-OPS-001", "PARK-OPS-002", "PARK-EVENT-001", "PARK-EVAL-006"],
    },
    {
        "agent_id": "placement_agent",
        "name": "Placement Agent",
        "role": "Checks whether temporary attractions, queues, food, merch, and signs fit park geography.",
        "mode": ["proactive", "event_planning"],
        "owns": ["temporary placement", "no-static-queue corridors", "spatial conflict detection"],
        "blocked": ["blocking narrow paths", "blocking emergency exits"],
        "policy_refs": ["PARK-EVENT-001", "PARK-EVENT-002"],
    },
    {
        "agent_id": "safety_policy_agent",
        "name": "Safety/Policy Agent",
        "role": "Applies safety, privacy, labor, customer-care, and event policy before execution.",
        "mode": ["reactive", "proactive", "event_planning", "judge"],
        "owns": ["policy refs", "human approval triggers", "blocked-scope checks"],
        "blocked": ["unsafe execution", "guest PII exposure", "individual compensation promises"],
        "policy_refs": ["PARK-SAFE-001", "PARK-CARE-001", "PARK-LABOR-002"],
    },
    {
        "agent_id": "finance_agent",
        "name": "Finance Agent",
        "role": "Checks whether labor, energy, food, merchandise, and compensation choices preserve business value.",
        "mode": ["event_planning", "judge"],
        "owns": ["cost/revenue tradeoff", "premium product protection", "voucher budget"],
        "blocked": ["cost-only optimization", "destroying guest trust for short-term savings"],
        "policy_refs": ["PARK-FIN-001", "PARK-EVAL-004"],
    },
    {
        "agent_id": "security_agent",
        "name": "Security Agent",
        "role": "Checks crowd-control, access-control, incident escalation, lost-child, and perimeter pressure signals.",
        "mode": ["reactive", "proactive", "event_planning"],
        "owns": ["zone control recommendation", "security escalation", "lost-child and access-control risk"],
        "blocked": ["public guest messaging", "equipment commands", "staff redeployment outside security scope"],
        "policy_refs": ["PARK-SEC-001", "PARK-SAFE-001", "PARK-CARE-001"],
    },
    {
        "agent_id": "decision_bridge_agent",
        "name": "Decision Bridge Agent",
        "role": "Resolves specialist disagreement into one executable plan with owners and tradeoffs.",
        "mode": ["reactive", "proactive", "event_planning"],
        "owns": ["final recommendation", "tradeoff explanation", "REST action selection"],
        "blocked": ["hiding conflicts", "executing without required approval"],
        "policy_refs": ["PARK-OPS-001", "PARK-EVAL-003", "PARK-EVAL-004"],
    },
    {
        "agent_id": "logic_audit_agent",
        "name": "Logic Audit Agent",
        "role": "Checks the layered decision graph for missing evidence, unsafe jumps, stale assumptions, and required node updates.",
        "mode": ["reactive", "proactive", "event_planning", "judge"],
        "owns": ["decision logic graph", "node audit trail", "edge consistency", "animation state markers"],
        "blocked": ["unexplained action jumps", "stale graph nodes", "post-decision results without audit"],
        "policy_refs": ["PARK-EVAL-001", "PARK-EVAL-003", "PARK-EVAL-006"],
    },
    {
        "agent_id": "memory_ops_agent",
        "name": "MongoDB MemoryOps Agent",
        "role": "Audits MongoDB operational memory quality, retrieval depth, embedding coverage, stale state, and vector-search readiness.",
        "mode": ["maintenance", "judge"],
        "owns": ["memory health report", "embedding coverage", "retrieval depth score", "MongoDB readiness findings"],
        "blocked": ["runtime action execution", "unsafe automatic repair", "editing operational history without operator approval"],
        "policy_refs": ["PARK-EVAL-001", "PARK-OPS-001"],
    },
    {
        "agent_id": "delivery_proof_agent",
        "name": "Delivery Proof Agent",
        "role": "Verifies Pub/Sub, Firestore, FCM, Dataflow, and receiver-state evidence.",
        "mode": ["reactive", "proactive", "event_planning", "judge"],
        "owns": ["delivery receipts", "receiver acknowledgement", "Dataflow stream evidence"],
        "blocked": ["dispatching without policy gate", "inventing delivery success", "editing agent reasoning"],
        "policy_refs": ["PARK-EVAL-001", "PARK-EVAL-003", "PARK-EVAL-006"],
    },
    {
        "agent_id": "autodream_agent",
        "name": "AutoDream Off-Hours Agent",
        "role": "Replays historical outcomes offline, generates counterfactual lessons, and writes review-required dream learnings.",
        "mode": ["offline_learning", "maintenance"],
        "owns": ["dream runs", "counterfactual learning", "historical incident synthesis", "promotion candidates"],
        "blocked": ["live action execution", "live park_state writes", "automatic playbook promotion without human review"],
        "policy_refs": ["PARK-EVAL-001", "PARK-EVAL-006", "PARK-OPS-001"],
    },
    {
        "agent_id": "gcp_eval_judge_agent",
        "name": "GCP Trace/Eval Judge",
        "role": "Scores groundedness, safety, staff stress, guest response, actionability, and revision quality.",
        "mode": ["judge"],
        "owns": ["eval scorecard", "traceability", "failure visibility", "learning signal"],
        "blocked": ["silent failures", "unscored decisions"],
        "policy_refs": ["PARK-EVAL-001", "PARK-EVAL-002", "PARK-EVAL-003", "PARK-EVAL-004", "PARK-EVAL-005", "PARK-EVAL-006"],
    },
    {
        "agent_id": "tool_executor_agent",
        "name": "Tool Executor Agent",
        "role": "Executes approved receiver actions after department proposal, compliance/judge checks, and executive approval when required.",
        "mode": ["reactive", "proactive", "event_planning"],
        "owns": ["receiver action execution", "idempotency key", "delivery receipt", "rollback handoff"],
        "blocked": ["executing unapproved proposals", "changing recommendation rationale", "skipping trace outcome recording"],
        "policy_refs": ["PARK-OPS-001", "PARK-EVAL-003", "PARK-EVAL-006"],
    },
]


AGENT_TOPOLOGY: dict[str, Any] = {
    "name": "Park enterprise nervous system",
    "pattern": "department_systematic_enterprise_nervous_system",
    "lifecycle_pattern": "pre_event_during_event_post_event_agent_groups",
    "department_system": {
        "loop": DEPARTMENT_AGENT_LOOP,
        "layers": [
            "department_agents",
            "shared_context_memory_trace",
            "risk_policy_judge",
            "action_router_tool_executor",
        ],
        "tool_contract_required_fields": DEPARTMENT_TOOL_CONTRACT_FIELDS,
        "departments": DEPARTMENT_AGENT_MAP,
        "conflict_resolution": [
            "Department agents detect local problems.",
            "Shared trace stores observations, evidence, confidence, policy refs, and proposed actions.",
            "Cross-agent coordinator detects conflicts between department recommendations.",
            "Policy judge checks safety, privacy, labor, and compliance constraints.",
            "Executive agent selects the tradeoff or rejects unsafe actions.",
            "Tool executor acts only with policy and delivery receipts.",
            "Eval judge reviews outcome quality and writes learning memory.",
        ],
    },
    "agent_groups": [
        {
            "id": "pre_event",
            "label": "Pre-event agent group",
            "purpose": "Simulate policy impact, pressure-test the operating plan, and commit prevention work before the crowd or failure peaks.",
            "operating_question": "What can we prevent before operators are forced into a reactive move?",
            "modes": ["event_planning", "proactive"],
            "agents": [
                "park_understanding_agent",
                "event_creative_agent",
                "event_setup_agent",
                "traffic_flow_agent",
                "planning_agent",
                "placement_agent",
                "guest_flow_agent",
                "staffing_agent",
                "facilities_energy_agent",
                "safety_policy_agent",
                "finance_agent",
                "decision_bridge_agent",
            ],
            "primary_outputs": [
                "policy impact simulation",
                "pre-stage checklist",
                "risk forecast",
                "preventive action candidates",
            ],
            "activation": "Before scheduled events, expected weather windows, demand spikes, or planned park overlays.",
            "success_metrics": ["risk reduced before peak", "false alarm bounded", "operator-ready prevention work"],
        },
        {
            "id": "during_event",
            "label": "During-event agent group",
            "purpose": "Supervise live conditions, react to signals, gate unsafe actions, and emit guest, worker, or equipment actions.",
            "operating_question": "What changed right now, and what action can safely stabilize it?",
            "modes": ["reactive"],
            "agents": [
                "park_understanding_agent",
                "ride_ops_agent",
                "guest_flow_agent",
                "staffing_agent",
                "food_demand_agent",
                "facilities_energy_agent",
                "safety_policy_agent",
                "decision_bridge_agent",
                "tool_executor_agent",
                "logic_audit_agent",
            ],
            "primary_outputs": [
                "supervised action plan",
                "policy-gated dispatch payloads",
                "operator approval flags",
                "live response telemetry",
            ],
            "activation": "While the event or disruption is active and new signals are arriving.",
            "success_metrics": ["time to safe action", "policy violations avoided", "guest and worker follow-through"],
        },
        {
            "id": "post_event",
            "label": "Post-event agent group",
            "purpose": "Analyze outcomes, judge decision quality, learn from measured response, and improve the next policy or plan.",
            "operating_question": "Did the action work, what did we learn, and what should change next time?",
            "modes": ["judge"],
            "agents": [
                "park_understanding_agent",
                "decision_bridge_agent",
                "logic_audit_agent",
                "gcp_eval_judge_agent",
                "safety_policy_agent",
                "finance_agent",
            ],
            "primary_outputs": [
                "outcome analysis",
                "eval scorecard",
                "MongoDB learning rule",
                "revised plan version",
            ],
            "activation": "After dispatch response, event close, or any measured outcome interval.",
            "success_metrics": ["revision quality", "learning retrieved on next run", "weak assumptions corrected"],
        },
    ],
    "lifecycle_artifact": [
        {
            "group_id": "pre_event",
            "label": "Pre-event forecast",
            "inputs": ["event brief", "park state", "policy book", "MongoDB memory"],
            "decision": "Simulate policy impact and commit low-risk prevention work before pressure peaks.",
            "output": "Risk forecast, pre-stage checklist, and preventive action candidates.",
            "measured_result": "Waiting for live response telemetry.",
            "status": "ready",
        },
        {
            "group_id": "during_event",
            "label": "During-event action",
            "inputs": ["live signals", "specialist findings", "policy gates", "operator context"],
            "decision": "Supervise the active event, resolve specialist conflicts, and emit safe actions.",
            "output": "Guest messages, worker tasks, equipment payloads, and approval flags.",
            "measured_result": "Waiting for action bus dispatch and follow-through.",
            "status": "ready",
        },
        {
            "group_id": "post_event",
            "label": "Post-event learning",
            "inputs": ["dispatch response", "outcome telemetry", "eval scorecard", "trace spans"],
            "decision": "Judge what worked, store the learning, and revise the next plan or policy threshold.",
            "output": "Learning rule, revised plan version, and next-run retrieval signal.",
            "measured_result": "Waiting for outcome scoring.",
            "status": "ready",
        },
    ],
    "phases": [
        {
            "id": "sense",
            "label": "Sense",
            "purpose": "Convert live park state, map, memory, and operator request into a grounded operating picture.",
            "agents": ["park_understanding_agent"],
            "outputs": ["park model", "source-grounded assumptions", "memory retrieval"],
        },
        {
            "id": "design",
            "label": "Design",
            "purpose": "Generate event concepts and convert them into time, place, labor, equipment, and guest-flow hypotheses.",
            "agents": ["event_creative_agent", "event_setup_agent", "traffic_flow_agent", "planning_agent", "placement_agent"],
            "outputs": ["concept options", "temporal flow plan", "multi-wave operating plan", "placement map", "setup checklist"],
        },
        {
            "id": "specialist_review",
            "label": "Specialist Review",
            "purpose": "Stress-test the plan against ride operations, staffing, food, energy, safety, and business value.",
            "agents": ["ride_ops_agent", "guest_flow_agent", "staffing_agent", "food_demand_agent", "facilities_energy_agent", "finance_agent", "safety_policy_agent"],
            "outputs": ["constraints", "tradeoffs", "blocked actions", "escalation flags"],
        },
        {
            "id": "logic_graph",
            "label": "Logic Graph",
            "purpose": "Expose the layered decision structure from detection through constraints, tradeoffs, action selection, audit, and measured outcome.",
            "agents": ["decision_bridge_agent", "logic_audit_agent", "gcp_eval_judge_agent"],
            "outputs": ["decision graph nodes", "audit updates", "animation state markers"],
        },
        {
            "id": "bridge",
            "label": "Bridge",
            "purpose": "Resolve conflicts into one executable plan with owners, deadlines, and REST action payloads.",
            "agents": ["decision_bridge_agent"],
            "outputs": ["selected plan", "action bus payloads", "human approval flags"],
        },
        {
            "id": "judge",
            "label": "Judge",
            "purpose": "Score whether the plan is grounded, safe, complete, balanced, and responsive to outcome telemetry.",
            "agents": ["gcp_eval_judge_agent", "safety_policy_agent", "finance_agent"],
            "outputs": ["eval scorecard", "failure reasons", "revision prompt"],
        },
        {
            "id": "learn",
            "label": "Learn",
            "purpose": "Persist decisions, actions, response metrics, and revised plans into MongoDB memory.",
            "agents": ["park_understanding_agent", "decision_bridge_agent", "gcp_eval_judge_agent"],
            "outputs": ["agent_decisions", "eval_results", "outcome_events", "plan_versions"],
        },
    ],
    "handoffs": [
        {"from": "park_understanding_agent", "to": "event_creative_agent", "artifact": "grounded park model"},
        {"from": "event_creative_agent", "to": "traffic_flow_agent", "artifact": "concept options and guest segments"},
        {"from": "traffic_flow_agent", "to": "planning_agent", "artifact": "time-block demand and spillback forecast"},
        {"from": "planning_agent", "to": "placement_agent", "artifact": "multi-wave operating plan and scenario rehearsal"},
        {"from": "placement_agent", "to": "staffing_agent", "artifact": "queue, maze, food, merch, and path placements"},
        {"from": "staffing_agent", "to": "decision_bridge_agent", "artifact": "role-compatible staffing constraints"},
        {"from": "facilities_energy_agent", "to": "decision_bridge_agent", "artifact": "HVAC, lighting, power, and equipment constraints"},
        {"from": "safety_policy_agent", "to": "decision_bridge_agent", "artifact": "blocked actions and approval requirements"},
        {"from": "decision_bridge_agent", "to": "logic_audit_agent", "artifact": "layered decision graph and selected action path"},
        {"from": "logic_audit_agent", "to": "decision_bridge_agent", "artifact": "graph audit, missing-node updates, and animation markers"},
        {"from": "decision_bridge_agent", "to": "tool_executor_agent", "artifact": "approved action envelope and idempotency key"},
        {"from": "tool_executor_agent", "to": "delivery_proof_agent", "artifact": "receiver dispatch receipt and rollback handle"},
        {"from": "decision_bridge_agent", "to": "gcp_eval_judge_agent", "artifact": "final recommendation and dispatch payloads"},
        {"from": "gcp_eval_judge_agent", "to": "decision_bridge_agent", "artifact": "judge critique and revision prompt"},
        {"from": "decision_bridge_agent", "to": "park_understanding_agent", "artifact": "observed outcome and learned take-rate signal"},
    ],
    "logic_graph": {
        "id": "decision_logic_graph",
        "label": "Layered Decision Logic",
        "purpose": "Demonstrates how a recommendation moves through structured decision layers before and after execution.",
        "decision_layers": [
            {
                "id": "start_detection",
                "label": "Start detection",
                "question": "What changed in the park?",
                "agents": ["park_understanding_agent", "traffic_flow_agent", "guest_flow_agent"],
                "evidence": ["live park state", "early warning signal", "memory retrieval"],
                "updates": ["risk source", "affected zone", "deadline"],
            },
            {
                "id": "constraints",
                "label": "Constraint layer",
                "question": "What cannot be violated?",
                "agents": ["safety_policy_agent", "staffing_agent", "facilities_energy_agent"],
                "evidence": ["safety policy", "labor capacity", "equipment limits"],
                "updates": ["blocked actions", "approval flags", "safe operating envelope"],
            },
            {
                "id": "tradeoffs",
                "label": "Tradeoff layer",
                "question": "Which option balances flow, stress, cost, and guest response?",
                "agents": ["guest_flow_agent", "food_demand_agent", "finance_agent"],
                "evidence": ["queue pressure", "food demand", "business value"],
                "updates": ["candidate actions", "expected impact", "known downside"],
            },
            {
                "id": "action_commit",
                "label": "Action commit",
                "question": "What gets emitted, by whom, and by when?",
                "agents": ["decision_bridge_agent"],
                "evidence": ["selected action", "owner", "REST action payload"],
                "updates": ["dispatch channel", "deadline", "human review status"],
            },
            {
                "id": "logic_audit",
                "label": "Logic audit",
                "question": "Does the graph explain the decision without gaps?",
                "agents": ["logic_audit_agent", "gcp_eval_judge_agent"],
                "evidence": ["trace spans", "eval scorecard", "policy refs"],
                "updates": ["missing edge fix", "stale-node refresh", "revision trigger"],
            },
            {
                "id": "post_decision_result",
                "label": "Post-decision result",
                "question": "Did the action work, and should the graph change?",
                "agents": ["gcp_eval_judge_agent", "park_understanding_agent", "logic_audit_agent"],
                "evidence": ["take rate", "follow-through", "outcome memory"],
                "updates": ["node score", "learned rule", "next-run threshold"],
            },
        ],
        "audit_agent": {
            "agent_id": "logic_audit_agent",
            "checks": ["evidence coverage", "edge consistency", "policy gate coverage", "outcome-to-revision link"],
            "update_rule": "When evidence, evals, or outcome telemetry changes, refresh the affected graph node before the next recommendation.",
        },
        "animation_path": [
            {"from": "start_detection", "to": "constraints", "reaction": "risk signal enters guardrail checks"},
            {"from": "constraints", "to": "tradeoffs", "reaction": "blocked actions narrow the option set"},
            {"from": "tradeoffs", "to": "action_commit", "reaction": "best balanced action is selected"},
            {"from": "action_commit", "to": "logic_audit", "reaction": "audit checks traceability before/after execution"},
            {"from": "logic_audit", "to": "post_decision_result", "reaction": "measured response updates the graph"},
        ],
    },
    "eval_dimensions": [
        "groundedness",
        "constraint_following",
        "crowd_flow",
        "staff_feasibility",
        "equipment_feasibility",
        "guest_response",
        "cost_balance",
        "revision_quality",
    ],
}


AGENT_POLICY_SCOPES: dict[str, list[dict[str, str]]] = {
    "park_understanding_agent": [{"target": "scenario", "action": ""}],
    "ride_ops_agent": [{"target": "ride", "action": "reroute"}],
    "guest_flow_agent": [{"target": "traffic", "action": "redirect_food"}],
    "customer_support_agent": [{"target": "guest", "action": "customer_self_service"}],
    "staffing_agent": [{"target": "staff", "action": "redeploy"}],
    "food_demand_agent": [{"target": "food", "action": "suppress_item", "scenario": "food_spike"}],
    "facilities_energy_agent": [{"target": "energy", "action": "protect_hvac", "scenario": "storm_response"}],
    "event_setup_agent": [{"target": "event", "action": "proactive_commit"}],
    "event_creative_agent": [{"target": "event", "action": "plan_overlay"}],
    "traffic_flow_agent": [{"target": "traffic", "action": "plan_overlay"}],
    "planning_agent": [{"target": "scenario", "action": "proactive_commit"}, {"target": "event", "action": "plan_overlay"}],
    "placement_agent": [{"target": "event", "action": "plan_overlay"}],
    "safety_policy_agent": [
        {"target": "ride", "action": "reroute"},
        {"target": "staff", "action": "redeploy"},
        {"target": "guest", "action": "message"},
    ],
    "finance_agent": [{"target": "guest", "action": "promotion"}, {"target": "food", "action": "suppress_item"}],
    "security_agent": [{"target": "security", "action": "zone_control"}, {"target": "security", "action": "escalation"}],
    "decision_bridge_agent": [{"target": "scenario", "action": "proactive_commit"}],
    "logic_audit_agent": [{"target": "scenario", "action": ""}],
    "memory_ops_agent": [{"target": "scenario", "action": ""}],
    "autodream_agent": [{"target": "scenario", "action": "revise_overlay_after_outcome"}],
    "tool_executor_agent": [{"target": "scenario", "action": "proactive_commit"}],
}


AGENT_BUILDER_TOOL_ALLOWLIST: dict[str, list[str]] = {
    "park_understanding_agent": ["get_park_state", "retrieve_similar_incidents", "get_noisy_observation"],
    "ride_ops_agent": ["get_ride_status", "get_queue_length", "get_park_map", "get_weather", "get_event_schedule", "simulate_action", "validate_policy", "create_ops_alert", "recommend_route_change", "request_staffing_move"],
    "guest_flow_agent": ["get_zone_density", "get_guest_complaints", "get_app_feedback", "get_sentiment", "get_notification_history", "simulate_action", "draft_guest_message", "issue_recovery_offer", "create_support_ticket", "score_outcome"],
    "customer_support_agent": [
        "get_park_state",
        "get_public_wait_times",
        "get_public_route_options",
        "get_food_capacity",
        "customer_show_route",
        "customer_send_to_phone",
    ],
    "staffing_agent": ["get_staff_constraints", "get_staff_schedule", "get_attendance", "get_overtime", "get_fatigue_risk", "get_skill_matrix", "validate_policy", "shift_adjustment_recommendation", "overtime_warning", "break_reminder"],
    "food_demand_agent": ["get_food_capacity", "get_pos_sales", "get_inventory", "get_queue_near_shops", "get_event_schedule", "get_weather", "validate_policy", "inventory_alert", "restock_request", "pause_launch_promo"],
    "facilities_energy_agent": ["get_park_state", "get_asset_history", "get_sensor_health", "get_inspection_logs", "get_spare_parts_inventory", "validate_policy", "create_work_order", "assign_technician", "update_repair_status"],
    "event_setup_agent": ["get_park_state", "simulate_action", "write_decision_memory"],
    "event_creative_agent": ["get_park_state", "retrieve_similar_incidents", "get_campaign_calendar", "get_guest_segments", "get_demand_forecast", "get_weather_events", "get_zone_density", "draft_campaign", "launch_pause_promo", "redirect_offer"],
    "traffic_flow_agent": ["get_zone_density", "simulate_action", "score_outcome"],
    "planning_agent": ["get_park_state", "retrieve_similar_incidents", "simulate_action", "score_outcome", "validate_policy", "write_decision_memory"],
    "placement_agent": ["get_park_state", "simulate_action", "validate_policy"],
    "safety_policy_agent": ["get_incident_reports", "get_ride_inspection_status", "get_zone_density", "get_weather", "get_policy_book", "policy_gate", "validate_policy", "inspect_runtime_status", "inspect_delivery_receipts", "safety_alert", "close_reopen_recommendation", "require_human_approval"],
    "finance_agent": ["get_ticket_sales", "get_refund_data", "get_labor_cost", "get_pos_revenue", "get_outage_impact", "score_decision_quality", "score_outcome", "revenue_impact_report", "refund_recommendation", "budget_alert"],
    "security_agent": ["get_zone_density", "get_incident_reports", "get_access_logs", "get_lost_child_reports", "validate_policy", "dispatch_alert", "escalation_request", "zone_control_recommendation"],
    "decision_bridge_agent": ["get_department_summaries", "get_risk_scores", "get_financial_impact", "get_guest_impact", "compare_action_candidates", "policy_gate", "validate_policy", "write_decision_memory", "approve_action", "reject_action", "set_priority", "choose_tradeoff"],
    "logic_audit_agent": ["get_policy_books", "get_privacy_rules", "get_safety_rules", "get_labor_rules", "get_audit_logs", "inspect_runtime_status", "inspect_observability_contract", "score_decision_quality", "block_action", "require_approval", "generate_compliance_note"],
    "memory_ops_agent": ["retrieve_similar_incidents", "inspect_runtime_status"],
    "delivery_proof_agent": ["inspect_delivery_receipts", "inspect_runtime_status", "inspect_observability_contract"],
    "autodream_agent": ["retrieve_similar_incidents", "tick_simulation", "simulate_action", "score_outcome", "write_decision_memory"],
    "gcp_eval_judge_agent": ["get_full_trace", "get_tool_calls", "get_outcomes", "get_policy_references", "score_decision_quality", "inspect_observability_contract", "inspect_delivery_receipts", "score_decision", "flag_failure", "create_regression_test"],
    "tool_executor_agent": ["dispatch_guest_message", "dispatch_worker_task", "dispatch_equipment_command", "dispatch_receiver_payload", "execute_approved_action"],
}


AGENT_BUILDER_BLOCKED_TOOLS: dict[str, list[str]] = {
    "park_understanding_agent": ["dispatch_guest_message", "dispatch_worker_task", "dispatch_equipment_command", "write_decision_memory"],
    "ride_ops_agent": ["dispatch_guest_message", "dispatch_worker_task", "dispatch_equipment_command", "draft_guest_message"],
    "guest_flow_agent": ["dispatch_guest_message", "dispatch_worker_task", "dispatch_equipment_command", "recommend_route_change"],
    "staffing_agent": ["dispatch_guest_message", "dispatch_worker_task", "dispatch_equipment_command"],
    "food_demand_agent": ["dispatch_guest_message", "dispatch_worker_task", "dispatch_equipment_command", "recommend_route_change"],
    "facilities_energy_agent": ["dispatch_guest_message", "dispatch_worker_task", "dispatch_equipment_command"],
    "customer_support_agent": [
        "dispatch_guest_message",
        "dispatch_worker_task",
        "dispatch_equipment_command",
        "write_decision_memory",
        "operator_command",
        "operator_console_redirect",
        "internal_policy_lookup",
    ],
    "event_creative_agent": ["dispatch_guest_message", "dispatch_worker_task", "dispatch_equipment_command"],
    "safety_policy_agent": ["dispatch_guest_message", "dispatch_worker_task", "dispatch_equipment_command"],
    "finance_agent": ["dispatch_guest_message", "dispatch_worker_task", "dispatch_equipment_command"],
    "security_agent": ["dispatch_guest_message", "dispatch_worker_task", "dispatch_equipment_command", "draft_guest_message"],
    "logic_audit_agent": ["dispatch_guest_message", "dispatch_worker_task", "dispatch_equipment_command", "write_decision_memory"],
    "memory_ops_agent": ["dispatch_guest_message", "dispatch_worker_task", "dispatch_equipment_command"],
    "delivery_proof_agent": ["dispatch_guest_message", "dispatch_worker_task", "dispatch_equipment_command", "write_decision_memory"],
    "autodream_agent": ["dispatch_guest_message", "dispatch_worker_task", "dispatch_equipment_command"],
    "gcp_eval_judge_agent": ["dispatch_guest_message", "dispatch_worker_task", "dispatch_equipment_command"],
    "tool_executor_agent": ["policy_gate", "validate_policy", "score_decision_quality"],
}


def get_department_agent_map() -> list[dict[str, Any]]:
    departments = []
    for department in DEPARTMENT_AGENT_MAP:
        item = deepcopy(department)
        item.update(deepcopy(DEPARTMENT_TOOL_ACCESS_MAP.get(str(department["department"]), {})))
        item["loop"] = [step.title() for step in DEPARTMENT_AGENT_LOOP]
        item["tool_contract_required_fields"] = list(DEPARTMENT_TOOL_CONTRACT_FIELDS)
        departments.append(item)
    return departments


def get_judge_trace_eval_contract() -> dict[str, Any]:
    contract = deepcopy(JUDGE_TRACE_EVAL_CONTRACT)
    contract["owned_tools"] = sorted(
        set(contract["trace_read_tools"])
        | set(contract["eval_write_tools"])
        | set(contract["inspection_tools"])
    )
    contract["exclusive_tools"] = sorted(JUDGE_TRACE_EVAL_EXCLUSIVE_TOOLS)
    return contract


def active_departments_for_agents(agent_ids: list[str] | tuple[str, ...] | set[str]) -> list[str]:
    return sorted(
        {
            _department_for_agent(str(agent_id))["department"]
            for agent_id in agent_ids
            if str(agent_id or "").strip()
        }
    )


def _department_record(department_id: str | None) -> dict[str, Any]:
    wanted = str(department_id or "").strip()
    for department in DEPARTMENT_AGENT_MAP:
        if department["department"] == wanted:
            item = deepcopy(department)
            item.update(deepcopy(DEPARTMENT_TOOL_ACCESS_MAP.get(wanted, {})))
            return item
    if wanted == "tool_executor":
        return {
            "department": "tool_executor",
            "label": "Tool Executor",
            "canonical_agent": "Tool Executor Agent",
            "implementation_agents": ["tool_executor_agent"],
            "main_job": "execute approved receiver actions and record delivery outcomes",
            "tool_families": ["receiver dispatch tools", "idempotency tools", "rollback tools"],
            "read_tools": ["approved_action_envelope", "policy_gate_receipt", "executive_approval", "delivery_target"],
            "write_action_tools": sorted(REAL_ACTION_TOOLS),
        }
    return {
        "department": wanted or "executive",
        "label": wanted.replace("_", " ").title() if wanted else "Executive",
        "canonical_agent": "Executive Agent",
        "implementation_agents": ["decision_bridge_agent"],
        "main_job": "cross-department tradeoff and final recommendation",
        "tool_families": ["approval tools", "routing tools"],
    }


def _department_for_agent(agent_id: str) -> dict[str, Any]:
    return _department_record(AGENT_DEPARTMENT_OVERRIDES.get(agent_id, "executive"))


def _tool_contract_status(agent_id: str, tool_name: str, action_context: dict[str, Any]) -> dict[str, Any]:
    department = _department_for_agent(agent_id)
    normalized = {
        "department": action_context.get("department") or department["department"],
        "tool": action_context.get("tool") or tool_name,
        "intent": action_context.get("intent") or action_context.get("reason") or action_context.get("action") or "",
        "evidence": action_context.get("evidence") or action_context.get("input_signals") or action_context.get("signals") or [],
        "risk_level": action_context.get("risk_level") or action_context.get("riskLevel") or "",
        "policy_check": action_context.get("policy_check") or action_context.get("policyCheck") or action_context.get("policyGateStatus") or action_context.get("policyGate") or "",
        "expected_outcome": action_context.get("expected_outcome") or action_context.get("expectedOutcome") or action_context.get("expectedImpact") or "",
        "rollback": action_context.get("rollback") or action_context.get("rollbackPlan") or "",
    }
    if action_context.get("proposed_by") or action_context.get("proposedBy"):
        normalized["proposed_by"] = action_context.get("proposed_by") or action_context.get("proposedBy")
    missing = [
        field
        for field in DEPARTMENT_TOOL_CONTRACT_FIELDS
        if normalized.get(field) in (None, "", []) or normalized.get(field) == {}
    ]
    return {
        "status": "complete" if not missing else "incomplete",
        "required_fields": list(DEPARTMENT_TOOL_CONTRACT_FIELDS),
        "missing_fields": missing,
        "normalized": normalized,
        "loop": [step.title() for step in DEPARTMENT_AGENT_LOOP],
    }


def _judge_trace_eval_tool_status(agent_id: str, tool_name: str) -> dict[str, Any] | None:
    contract = get_judge_trace_eval_contract()
    if tool_name not in set(contract["owned_tools"]):
        return None
    owner = str(contract["owner_agent"])
    is_owner = agent_id == owner
    return {
        "owner_agent": owner,
        "owner_department": contract["owner_department"],
        "owned_by_judge": True,
        "requesting_agent_is_owner": is_owner,
        "exclusive": tool_name in set(contract["exclusive_tools"]),
        "status": "judge_owned" if is_owner else "shared_inspection" if tool_name in set(contract["inspection_tools"]) else "requires_judge_handoff",
        "routing_rule": contract["routing_rule"],
    }


def build_agent_builder_boundary_contract() -> dict[str, Any]:
    """Return the Agent Builder contract used by UI and GCP proof endpoints."""

    agents = []
    for agent in get_agent_registry():
        agent_id = str(agent["agent_id"])
        can_dispatch = any(tool.startswith("dispatch_") for tool in AGENT_BUILDER_TOOL_ALLOWLIST.get(agent_id, []))
        department = _department_for_agent(agent_id)
        agents.append(
            {
                "id": agent_id,
                "name": agent["name"],
                "department": department["department"],
                "department_label": department["label"],
                "department_agent": department["canonical_agent"],
                "department_loop": [step.title() for step in DEPARTMENT_AGENT_LOOP],
                "read_tools": department.get("read_tools", []),
                "write_action_tools": department.get("write_action_tools", []),
                "mode": agent.get("mode", []),
                "role": agent["role"],
                "responsibilities": agent.get("owns", []),
                "decision_rights": _agent_builder_decision_rights(agent_id, can_dispatch),
                "tools": AGENT_BUILDER_TOOL_ALLOWLIST.get(agent_id, []),
                "allowed_tools": AGENT_BUILDER_TOOL_ALLOWLIST.get(agent_id, []),
                "blocked_tools": AGENT_BUILDER_BLOCKED_TOOLS.get(agent_id, []) + [f"blocked_scope:{item}" for item in agent.get("blocked", [])],
                "policy_refs": agent.get("policy_refs", []),
                "handoff_to": _agent_builder_handoff(agent_id),
                "execution_boundary": _agent_builder_execution_boundary(agent_id, can_dispatch),
                "requires_human_approval_when": _agent_builder_human_approval_rules(agent_id),
                "agent_builder_fit": _agent_builder_fit(agent_id),
                **({"judge_trace_eval_contract": get_judge_trace_eval_contract()} if agent_id == JUDGE_TRACE_EVAL_CONTRACT["owner_agent"] else {}),
            }
        )
    return {
        "platform": "Vertex AI Agent Builder / Agent Engine",
        "contract_version": "parkpulse-department-agent-boundaries-v2",
        "principle": "Each department agent gets explicit tools, responsibilities, blocked scopes, policy refs, handoff targets, and a traceable tool-call contract before it can affect receivers.",
        "department_system": {
            "loop": [step.title() for step in DEPARTMENT_AGENT_LOOP],
            "departments": get_department_agent_map(),
            "tool_contract_required_fields": list(DEPARTMENT_TOOL_CONTRACT_FIELDS),
            "judge_trace_eval_contract": get_judge_trace_eval_contract(),
        },
        "agents": agents,
        "tool_registry": sorted({tool for agent in agents for tool in agent["allowed_tools"]}),
        "blocked_tool_registry": sorted({tool for agent in agents for tool in agent["blocked_tools"]}),
        "handoff_rules": [
            "Read-only agents can gather evidence and recommend next roles but cannot dispatch.",
            "Specialist agents hand proposals to Decision Bridge before final action selection.",
            "Safety/Policy and Logic Audit can block or require approval but cannot silently execute.",
            "Trace/eval reads and score/flag/regression-test writes are owned by GCP Trace/Eval Judge.",
            "Receiver dispatch tools require a policy gate receipt and delivery proof receipt.",
            "Offline learning agents cannot affect live park state without human promotion.",
        ],
        "runtime_enforcement": {
            "pre_tool_call": "Check requested tool against allowed_tools, blocked_tools, and judge-exclusive trace/eval ownership.",
            "pre_dispatch": "Require validate_policy plus approval when the agent boundary says review is needed.",
            "post_eval": "GCP Trace/Eval Judge records score, failure flags, and regression-test recommendations from full trace evidence.",
            "post_dispatch": "Delivery Proof records Pub/Sub, Firestore, Dataflow, and receiver acknowledgement receipts.",
        },
    }


def enforce_agent_tool_boundary(agent_id: str | None, tool_name: str, action_context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate one tool call against the Agent Builder boundary contract."""

    requested_agent_id = str(agent_id or "").strip() or "decision_bridge_agent"
    requested_tool = str(tool_name or "").strip()
    context = action_context or {}
    registry = {str(agent["agent_id"]): agent for agent in AGENT_REGISTRY}
    known_agent = requested_agent_id in registry
    agent = registry.get(requested_agent_id, registry["decision_bridge_agent"])
    normalized_agent_id = str(agent["agent_id"])
    allowed_tools = set(AGENT_BUILDER_TOOL_ALLOWLIST.get(normalized_agent_id, []))
    blocked_tools = set(AGENT_BUILDER_BLOCKED_TOOLS.get(normalized_agent_id, []))
    blocked_scopes = [str(item) for item in agent.get("blocked", [])]
    policy_gate_checked = bool(
        context.get("policy_gate_checked")
        or context.get("policyGateChecked")
        or context.get("decisionId")
        or context.get("decision_id")
        or context.get("policyGate")
        or context.get("policyGateStatus")
        or requested_tool == "validate_policy"
        or requested_tool == "policy_gate"
    )
    blocked_scope_hit = next(
        (
            scope
            for scope in blocked_scopes
            if scope and scope.lower() in jsonish_context(context).lower()
        ),
        None,
    )

    allowed = known_agent and requested_tool in allowed_tools and requested_tool not in blocked_tools and not blocked_scope_hit
    reasons: list[str] = []
    if not known_agent:
        reasons.append(f"unknown agent {requested_agent_id}")
    if requested_tool not in allowed_tools:
        reasons.append(f"{requested_tool} is not in allowed_tools for {normalized_agent_id}")
    if requested_tool in blocked_tools:
        reasons.append(f"{requested_tool} is blocked for {normalized_agent_id}")
    if blocked_scope_hit:
        reasons.append(f"action context matched blocked scope: {blocked_scope_hit}")
    if requested_tool.startswith("dispatch_") and not policy_gate_checked:
        allowed = False
        reasons.append("dispatch tools require policy_gate_checked, a decision receipt, or pending operator approval")
    if requested_tool in REAL_ACTION_TOOLS and normalized_agent_id != "tool_executor_agent":
        allowed = False
        reasons.append("real action tools can only be executed by tool_executor_agent")
    if requested_tool in JUDGE_TRACE_EVAL_EXCLUSIVE_TOOLS and normalized_agent_id != JUDGE_TRACE_EVAL_CONTRACT["owner_agent"]:
        allowed = False
        reasons.append("trace/eval read and score/flag/regression tools require gcp_eval_judge_agent")
    tool_contract = _tool_contract_status(normalized_agent_id, requested_tool, context)
    judge_contract = _judge_trace_eval_tool_status(normalized_agent_id, requested_tool)

    result = {
        "status": "allowed" if allowed else "blocked",
        "allowed": allowed,
        "agent_id": normalized_agent_id,
        "agent_name": agent["name"],
        "department": _department_for_agent(normalized_agent_id)["department"],
        "department_label": _department_for_agent(normalized_agent_id)["label"],
        "department_agent": _department_for_agent(normalized_agent_id)["canonical_agent"],
        "tool": requested_tool,
        "tool_contract": tool_contract,
        "allowed_tools_checked": requested_tool in allowed_tools,
        "blocked_tools_checked": requested_tool not in blocked_tools,
        "policy_gate_checked": policy_gate_checked,
        "handoff_to": _agent_builder_handoff(normalized_agent_id),
        "execution_boundary": _agent_builder_execution_boundary(normalized_agent_id, any(tool.startswith("dispatch_") for tool in allowed_tools)),
        "decision_rights": _agent_builder_decision_rights(normalized_agent_id, any(tool.startswith("dispatch_") for tool in allowed_tools)),
        "requires_human_approval_when": _agent_builder_human_approval_rules(normalized_agent_id),
        "reason": "; ".join(reasons) if reasons else "Tool is allowed by Agent Builder boundary contract.",
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    if judge_contract:
        result["judge_contract"] = judge_contract
    return result


def build_department_tool_proposal(
    agent_id: str,
    requested_tool: str,
    *,
    intent: str,
    evidence: list[str] | None = None,
    risk_level: str = "medium",
    expected_outcome: str = "department recommendation reviewed",
    rollback: str = "withdraw proposal before execution",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the auditable envelope department agents submit before execution."""

    payload = payload or {}
    department = _department_for_agent(agent_id)
    normalized_risk = str(risk_level or "medium").strip().lower()
    compliance_required = _proposal_requires_compliance(requested_tool, normalized_risk, payload)
    executive_required = _proposal_requires_executive(requested_tool, normalized_risk, payload, compliance_required)
    context = {
        "department": department["department"],
        "tool": requested_tool,
        "intent": intent,
        "evidence": evidence or [],
        "risk_level": normalized_risk,
        "policy_check": "pending_compliance" if compliance_required else "not_required_before_proposal",
        "expected_outcome": expected_outcome,
        "rollback": rollback,
        "proposal_payload": payload,
    }
    boundary = enforce_agent_tool_boundary(agent_id, requested_tool, context)
    proposal_status = "proposed" if boundary["allowed"] else "blocked"
    approval_status = (
        "blocked"
        if not boundary["allowed"]
        else "requires_executive"
        if executive_required
        else "requires_compliance"
        if compliance_required
        else "department_approved"
    )
    executor_status = (
        "blocked"
        if not boundary["allowed"]
        else "executor_only"
        if requested_tool in REAL_ACTION_TOOLS
        else "awaiting_executive"
        if executive_required
        else "awaiting_compliance"
        if compliance_required
        else "ready_for_executor"
    )
    return {
        "proposal_status": proposal_status,
        "proposed_by": agent_id,
        "department": department["department"],
        "department_label": department["label"],
        "department_agent": department["canonical_agent"],
        "requested_tool": requested_tool,
        "intent": intent,
        "evidence": (evidence or [])[:5],
        "risk_level": normalized_risk,
        "requires_compliance": compliance_required,
        "requires_executive": executive_required,
        "approval_status": approval_status,
        "executor_agent": "tool_executor_agent",
        "executor_status": executor_status,
        "expected_outcome": expected_outcome,
        "rollback": rollback,
        "boundary": boundary,
    }


def run_agent_tool(
    agent_id: str | None,
    tool_name: str,
    action_context: dict[str, Any] | None,
    executor: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Run a tool only after Agent Builder boundary enforcement."""

    boundary = enforce_agent_tool_boundary(agent_id, tool_name, action_context)
    if not boundary["allowed"]:
        return {
            "status": "blocked_by_agent_boundary",
            "reason": boundary["reason"],
            "agentBoundary": boundary,
        }
    try:
        output = executor()
        if isinstance(output, dict):
            return {**output, "agentBoundary": boundary}
        return {"status": "ok", "output": output, "agentBoundary": boundary}
    except Exception as error:
        return {
            "status": "failed",
            "reason": str(error)[:300],
            "agentBoundary": boundary,
        }


def jsonish_context(context: dict[str, Any]) -> str:
    try:
        return str(context).lower()
    except Exception:
        return ""


def _proposal_requires_compliance(requested_tool: str, risk_level: str, payload: dict[str, Any]) -> bool:
    tool = str(requested_tool or "").lower()
    context = jsonish_context(payload)
    if risk_level in {"high", "critical"}:
        return True
    if tool in REAL_ACTION_TOOLS:
        return True
    sensitive_terms = [
        "guest_message",
        "recovery_offer",
        "refund",
        "safety",
        "close_reopen",
        "human_approval",
        "zone_control",
        "dispatch_alert",
        "escalation",
        "overtime",
        "break_reminder",
        "promo",
    ]
    return any(term in tool or term in context for term in sensitive_terms)


def _proposal_requires_executive(requested_tool: str, risk_level: str, payload: dict[str, Any], compliance_required: bool) -> bool:
    tool = str(requested_tool or "").lower()
    context = jsonish_context(payload)
    if risk_level in {"high", "critical"}:
        return True
    if tool in REAL_ACTION_TOOLS:
        return True
    executive_terms = ["refund", "recovery_offer", "close_reopen", "launch_pause_promo", "redirect_offer", "budget", "revenue", "zone_control"]
    return compliance_required and any(term in tool or term in context for term in executive_terms)


def _proposal_tool_for_action(agent_id: str, proposed_action: dict[str, Any]) -> str:
    department = _department_for_agent(agent_id)
    target = str(proposed_action.get("target", "")).lower()
    action = str(proposed_action.get("action", "")).lower()
    if agent_id == "park_understanding_agent":
        return "get_park_state"
    if agent_id == "ride_ops_agent" or target == "ride":
        if "route" in action or "reroute" in action or "traffic" in target:
            return "recommend_route_change"
        return "recommend_route_change" if "reroute" in action or "hold" in action else "create_ops_alert"
    if agent_id == "guest_flow_agent" or target == "guest":
        return "draft_guest_message" if "message" in action or "routing" in proposed_action else "create_support_ticket"
    if agent_id == "staffing_agent" or target == "staff":
        return "shift_adjustment_recommendation"
    if agent_id == "food_demand_agent" or target == "food":
        return "pause_launch_promo" if "promo" in action or "redirect" in action else "inventory_alert"
    if agent_id == "facilities_energy_agent" or target == "energy":
        return "create_work_order"
    if agent_id == "event_creative_agent":
        if "redirect" in action:
            return "redirect_offer"
        if "promo" in action or "launch" in action or "pause" in action:
            return "launch_pause_promo"
        return "draft_campaign"
    if agent_id == "safety_policy_agent":
        return "require_human_approval" if proposed_action.get("requires_human_review") else "safety_alert"
    if agent_id == "finance_agent":
        return "revenue_impact_report"
    if agent_id == "security_agent" or target == "security":
        if "escalation" in action or "escalate" in action:
            return "escalation_request"
        if "dispatch" in action or "alert" in action:
            return "dispatch_alert"
        return "zone_control_recommendation"
    if agent_id == "logic_audit_agent":
        return "generate_compliance_note"
    if agent_id == "gcp_eval_judge_agent":
        return "score_decision"
    if agent_id == "decision_bridge_agent":
        return "choose_tradeoff"
    tools = department.get("write_action_tools") or []
    return str(tools[0]) if tools else "choose_tradeoff"


def _risk_for_proposal(proposal_type: str, proposed_action: dict[str, Any], constraints: list[str]) -> str:
    context = jsonish_context({"proposal_type": proposal_type, "proposed_action": proposed_action, "constraints": constraints})
    if any(term in context for term in ["safety", "emergency", "medical", "lost child", "evacuation", "close", "reopen"]):
        return "high"
    if proposal_type in {"gate", "constraint"}:
        return "medium"
    return "low" if proposal_type in {"context", "tradeoff"} else "medium"


def _agent_builder_decision_rights(agent_id: str, can_dispatch: bool) -> list[str]:
    if agent_id == "tool_executor_agent":
        return ["execute_approved_action", "record_delivery_receipt", "emit_rollback_handle"]
    if agent_id == "customer_support_agent":
        return ["answer_customer", "recommend_public_next_stop", "show_route", "send_to_customer_phone"]
    if agent_id in {"safety_policy_agent", "logic_audit_agent", "gcp_eval_judge_agent"}:
        return ["review", "block", "require_human_approval"]
    if agent_id == "decision_bridge_agent":
        return ["rank_options", "select_candidate", "request_dispatch"]
    if agent_id == "planning_agent":
        return ["rehearse_scenarios", "draft_multi_wave_plan", "recommend_precommit"]
    if agent_id == "delivery_proof_agent":
        return ["verify_delivery", "mark_unproven", "request_retry"]
    if agent_id in {"memory_ops_agent", "autodream_agent"}:
        return ["offline_analysis", "recommend_learning"]
    if can_dispatch:
        return ["propose_action", "bounded_dispatch_after_policy_gate"]
    return ["read", "analyze", "recommend"]


def _agent_builder_handoff(agent_id: str) -> str:
    if agent_id == "tool_executor_agent":
        return "delivery_proof_agent"
    if agent_id == "customer_support_agent":
        return "customer_kiosk_ui"
    if agent_id in {"safety_policy_agent", "logic_audit_agent", "gcp_eval_judge_agent"}:
        return "decision_bridge_agent"
    if agent_id == "decision_bridge_agent":
        return "delivery_proof_agent"
    if agent_id == "planning_agent":
        return "decision_bridge_agent"
    if agent_id == "delivery_proof_agent":
        return "operator_evidence_dock"
    if agent_id in {"memory_ops_agent", "autodream_agent"}:
        return "operator_review"
    return "decision_bridge_agent"


def _agent_builder_execution_boundary(agent_id: str, can_dispatch: bool) -> str:
    if agent_id == "tool_executor_agent":
        return "executes real receiver actions only from approved action envelopes; cannot create recommendations or skip trace outcome recording"
    if agent_id == "customer_support_agent":
        return "customer self-service only; no operator dispatch, staff tasking, equipment control, policy disclosure, or private data access"
    if agent_id in {"memory_ops_agent", "autodream_agent"}:
        return "offline only; no live dispatch"
    if agent_id in {"safety_policy_agent", "logic_audit_agent", "gcp_eval_judge_agent"}:
        return "review only; can block or score but cannot dispatch"
    if agent_id == "delivery_proof_agent":
        return "proof only; cannot invent delivery success or dispatch receiver actions"
    if agent_id == "decision_bridge_agent":
        return "selects final candidate; dispatch still needs policy and delivery receipts"
    if agent_id == "planning_agent":
        return "planning only; can rehearse and recommend but cannot dispatch without Decision Bridge and policy gate"
    if can_dispatch:
        return "bounded receiver dispatch only after policy gate"
    return "read-only analysis"


def _agent_builder_human_approval_rules(agent_id: str) -> list[str]:
    rules = ["policy gate returns requires_human_review"]
    if agent_id == "tool_executor_agent":
        return [
            "approved action envelope is missing",
            "compliance block, policy failure, or judge failure is present",
            "executive approval is required but missing",
            "payload affects safety, security, labor, customer-care commitments, equipment, refunds, or public messaging",
        ]
    if agent_id == "customer_support_agent":
        return [
            "guest reports medical, security, missing child, accessibility emergency, harassment, or evacuation concern",
            "request asks for refund, compensation promise, private guest data, staff identity, or internal operator detail",
            "customer asks the station to dispatch workers, alter equipment, override ride status, or bypass safety restrictions",
        ]
    if agent_id in {"ride_ops_agent", "facilities_energy_agent", "staffing_agent", "safety_policy_agent"}:
        rules.extend(["ride safety, equipment, labor, medical, weather, or evacuation boundary is active"])
    if agent_id in {"memory_ops_agent", "autodream_agent"}:
        rules.append("learning would be promoted into live playbooks")
    if agent_id == "delivery_proof_agent":
        rules.append("receipt is missing for an action that affected equipment, staffing, safety, or customer-care commitments")
    if agent_id == "decision_bridge_agent":
        rules.append("selected action touches equipment, staffing, safety, or customer-care commitments")
    if agent_id == "planning_agent":
        rules.append("plan would pre-commit staff, equipment, guest messaging, queue gates, or public-facing offers")
    return rules


def _agent_builder_fit(agent_id: str) -> str:
    if agent_id == "tool_executor_agent":
        return "Dedicated action runner that receives approved envelopes from Decision Bridge and emits idempotent delivery receipts."
    if agent_id == "customer_support_agent":
        return "Customer-facing Agent Builder kiosk agent with read-only public context and two customer-only UI actions."
    if agent_id in {"safety_policy_agent", "logic_audit_agent", "gcp_eval_judge_agent"}:
        return "Governed reviewer agent with registry-approved tools, trace spans, and no direct receiver dispatch."
    if agent_id in {"memory_ops_agent", "autodream_agent"}:
        return "Offline Agent Engine task with memory tools and human promotion gate."
    if agent_id == "delivery_proof_agent":
        return "Observable proof agent that verifies Pub/Sub, Firestore, FCM, Dataflow, and receiver acknowledgement receipts."
    if agent_id == "decision_bridge_agent":
        return "Coordinator agent that resolves specialist proposals into a single policy-gated candidate."
    if agent_id == "planning_agent":
        return "Online planner agent that uses digital-twin rehearsal, schedule waves, map constraints, memory, and policy gates before Decision Bridge."
    return "Specialist ADK-style agent with narrow tools, explicit handoff, and policy-gated execution."


def get_agent_registry() -> list[dict[str, Any]]:
    registry = []
    for agent in AGENT_REGISTRY:
        item = deepcopy(agent)
        department = _department_for_agent(str(agent["agent_id"]))
        item["department"] = department["department"]
        item["department_label"] = department["label"]
        item["department_agent"] = department["canonical_agent"]
        item["department_loop"] = [step.title() for step in DEPARTMENT_AGENT_LOOP]
        item["policy_refs"] = _policy_refs_for_agent(agent)
        registry.append(item)
    return registry


def get_agent_topology() -> dict[str, Any]:
    return deepcopy(AGENT_TOPOLOGY)


def role_alignment_report() -> dict[str, Any]:
    modes = ["reactive", "proactive", "event_planning", "judge"]
    coverage = {
        mode: [agent["agent_id"] for agent in AGENT_REGISTRY if mode in agent.get("mode", [])]
        for mode in modes
    }
    group_coverage = {
        group["id"]: [agent_id for agent_id in group.get("agents", []) if any(agent["agent_id"] == agent_id for agent in AGENT_REGISTRY)]
        for group in AGENT_TOPOLOGY["agent_groups"]
    }
    return {
        "status": "aligned",
        "agent_count": len(AGENT_REGISTRY),
        "department_count": len(DEPARTMENT_AGENT_MAP),
        "agent_group_count": len(AGENT_TOPOLOGY["agent_groups"]),
        "phase_count": len(AGENT_TOPOLOGY["phases"]),
        "handoff_count": len(AGENT_TOPOLOGY["handoffs"]),
        "runtime_contract": "Every active ParkPulse run can emit per-department findings with input signals, recommendation, confidence, policy refs, trace span, and department tool contract.",
        "coverage": coverage,
        "group_coverage": group_coverage,
        "department_coverage": {
            department["department"]: department["implementation_agents"]
            for department in DEPARTMENT_AGENT_MAP
        },
        "topology": {
            "pattern": AGENT_TOPOLOGY["pattern"],
            "lifecycle_pattern": AGENT_TOPOLOGY["lifecycle_pattern"],
            "department_system": AGENT_TOPOLOGY["department_system"],
            "agent_groups": [group["id"] for group in AGENT_TOPOLOGY["agent_groups"]],
            "phases": [phase["id"] for phase in AGENT_TOPOLOGY["phases"]],
            "eval_dimensions": AGENT_TOPOLOGY["eval_dimensions"],
        },
        "remaining_limitations": [
            "GCP internal trace/eval is the primary judge path; external Arize export remains optional.",
            "Specialists emit deterministic runtime artifacts; Gemini is used by the Decision Bridge/EventOps planner for synthesis and revision.",
        ],
    }


def _live_feed_proposal_evidence_rows(live_feed_case: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(live_feed_case, dict):
        return []
    rows = live_feed_case.get("evidence", [])
    return [row for row in rows if isinstance(row, dict) and row.get("source")]


def _live_feed_proposal_evidence_label(row: dict[str, Any]) -> str:
    source = row.get("source") or "live_feed"
    signal_type = row.get("signal_type") or "signal"
    event_id = row.get("event_id") or "unpersisted"
    confidence = row.get("confidence")
    age_seconds = row.get("age_seconds")
    summary = str(row.get("summary") or "").strip()
    label = f"live_feed:{source}:{signal_type}:event={event_id}"
    if confidence is not None:
        label += f":confidence={confidence}"
    if age_seconds is not None:
        label += f":age_seconds={age_seconds}"
    return f"{label}:summary={summary[:96]}" if summary else label


def _live_feed_rows_for_sources(rows: list[dict[str, Any]], sources: set[str], fallback_count: int = 3) -> list[dict[str, Any]]:
    matched = [row for row in rows if str(row.get("source") or "") in sources]
    if not matched:
        matched = rows[:fallback_count]
    return matched[:fallback_count]


def _live_feed_grounded_evidence(rows: list[dict[str, Any]]) -> list[str]:
    return [_live_feed_proposal_evidence_label(row) for row in rows]


def _compact_live_feed_evidence_snapshot(rows: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    snapshot: list[dict[str, Any]] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        snapshot.append(
            {
                "event_id": row.get("event_id"),
                "source": row.get("source"),
                "signal_type": row.get("signal_type"),
                "confidence": row.get("confidence"),
                "age_seconds": row.get("age_seconds"),
                "summary": str(row.get("summary") or row.get("label") or "").strip(),
            }
        )
    return snapshot


def _evidence_argument_from_rows(department: str, rows: list[dict[str, Any]], policy_status: str = "") -> str:
    snapshot = _compact_live_feed_evidence_snapshot(rows, 2)
    if not snapshot:
        return f"{department or 'department'} had no department-specific live event rows, so the action stays review-only until fresh evidence is attached."
    parts = []
    for row in snapshot:
        event = row.get("event_id") or "unpersisted"
        source = row.get("source") or "live_feed"
        signal = row.get("signal_type") or "signal"
        confidence = row.get("confidence")
        age = row.get("age_seconds")
        summary = row.get("summary") or signal
        freshness = f", age {age}s" if age is not None else ""
        conf = f", confidence {confidence}" if confidence is not None else ""
        parts.append(f"event {event} from {source}/{signal}{conf}{freshness}: {summary}")
    policy_clause = f" Policy status is {policy_status}." if policy_status else ""
    return f"{department or 'department'} decision is grounded in {' | '.join(parts)}.{policy_clause}"


def _evidence_argument_from_proposal(proposal: dict[str, Any]) -> str:
    reasoning = proposal.get("department_reasoning", {}) if isinstance(proposal.get("department_reasoning"), dict) else {}
    evidence_snapshot = reasoning.get("evidence_snapshot", []) if isinstance(reasoning.get("evidence_snapshot"), list) else []
    department = str(proposal.get("department") or "")
    policy = proposal.get("policy_judge", {}) if isinstance(proposal.get("policy_judge"), dict) else {}
    policy_status = str(policy.get("status") or "")
    if evidence_snapshot:
        rows = [
            {
                "event_id": row.get("event_id"),
                "source": row.get("source"),
                "signal_type": row.get("signal_type"),
                "confidence": row.get("confidence"),
                "age_seconds": row.get("age_seconds"),
                "summary": row.get("summary"),
            }
            for row in evidence_snapshot
            if isinstance(row, dict)
        ]
        return _evidence_argument_from_rows(department, rows, policy_status)
    grounding = proposal.get("live_feed_grounding", {}) if isinstance(proposal.get("live_feed_grounding"), dict) else {}
    event_ids = grounding.get("event_ids", []) if isinstance(grounding.get("event_ids"), list) else []
    sources = grounding.get("sources", []) if isinstance(grounding.get("sources"), list) else []
    return f"{department or 'department'} decision cites events {', '.join(str(item) for item in event_ids[:4]) or 'none'} from {', '.join(str(item) for item in sources[:4]) or 'no live source'} with policy status {policy_status or 'pending'}."


def _attach_native_live_feed_grounding(proposal: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    event_ids = [row.get("event_id") for row in rows if row.get("event_id")]
    sources = list(dict.fromkeys(str(row.get("source")) for row in rows if row.get("source")))
    confidence_values = [float(row.get("confidence") or 0) for row in rows]
    proposal["generated_from"] = "live_feed_case"
    proposal["live_feed_grounding"] = {
        "source": "live_feed_health",
        "event_ids": event_ids,
        "sources": sources,
        "source_count": len(sources),
        "max_confidence": round(max(confidence_values), 3) if confidence_values else None,
        "evidence_count": len(rows),
    }
    proposal["input_signals"] = {
        "orchestration_source": "live_feed",
        "live_feed_event_ids": event_ids,
        "live_feed_sources": sources,
    }
    envelope = proposal.get("proposal_envelope", {}) if isinstance(proposal.get("proposal_envelope"), dict) else {}
    if envelope:
        envelope["live_feed_event_ids"] = event_ids
        envelope["live_feed_sources"] = sources
        proposal["proposal_envelope"] = envelope
    return proposal


def _native_live_feed_policy_check(proposal: dict[str, Any]) -> dict[str, Any]:
    envelope = proposal.get("proposal_envelope", {}) if isinstance(proposal.get("proposal_envelope"), dict) else {}
    department = str(proposal.get("department") or envelope.get("department") or "")
    agent_id = str(proposal.get("agent_id") or envelope.get("proposed_by") or "")
    tool = str(envelope.get("requested_tool") or proposal.get("requested_tool") or "")
    risk = str(envelope.get("risk_level") or proposal.get("risk_level") or "medium").lower()
    boundary = envelope.get("boundary", {}) if isinstance(envelope.get("boundary"), dict) else {}
    if agent_id == "park_understanding_agent":
        return {
            "policy_check": "passed_context_grounding_read_only",
            "status": "trace_only",
            "reason": "Park Understanding reads live context and writes trace evidence only; no receiver action is executable.",
            "human_approval_required": False,
        }
    if boundary and not boundary.get("allowed", True):
        return {
            "policy_check": "blocked_agent_tool_boundary",
            "status": "blocked",
            "reason": boundary.get("reason") or "Agent tool boundary blocked proposal.",
            "human_approval_required": True,
        }
    if department == "operations" and risk == "high":
        return {
            "policy_check": "requires_executive_approval_ops_reroute",
            "status": "requires_executive",
            "reason": "High-risk routing or ride-flow proposal needs Executive tradeoff approval.",
            "human_approval_required": False,
        }
    if department == "operations" and tool == "create_ops_alert":
        return {
            "policy_check": "passed_internal_ops_alert_no_routing_execution",
            "status": "passed",
            "reason": "Operations alert is an internal receiver handoff only; it does not change guest routing or dispatch public instructions.",
            "human_approval_required": False,
        }
    if department in {"safety", "security"}:
        return {
            "policy_check": f"requires_human_approval_{department}",
            "status": "requires_human_approval",
            "reason": "Safety or security-sensitive action must be reviewed by an authorized park lead.",
            "human_approval_required": True,
        }
    if department == "guest_experience" or tool in {"draft_guest_message", "issue_recovery_offer"}:
        return {
            "policy_check": "requires_compliance_guest_message_privacy",
            "status": "requires_compliance",
            "reason": "Guest-facing message must avoid private data, medical detail, and compensation promises.",
            "human_approval_required": False,
        }
    if department == "hr_labor":
        return {
            "policy_check": "passed_labor_rules_role_compatible_only",
            "status": "passed",
            "reason": "Proposal is recommendation-only and constrained to certified staff, fatigue, overtime, and break rules.",
            "human_approval_required": False,
        }
    if department == "food_retail":
        return {
            "policy_check": "passed_food_inventory_no_unavailable_promo",
            "status": "passed",
            "reason": "Food/Retail action is alert or promo pause, not a promise of unavailable capacity.",
            "human_approval_required": False,
        }
    if department == "marketing":
        return {
            "policy_check": "passed_marketing_redirect_only_no_crowd_creation",
            "status": "passed",
            "reason": "Marketing may redirect or pause offers but cannot change crowd routing or increase pressure in constrained zones.",
            "human_approval_required": False,
        }
    if department == "finance":
        return {
            "policy_check": "passed_finance_no_refund_commitment",
            "status": "passed",
            "reason": "Finance output is an impact report or recommendation, not an automatic refund or compensation commitment.",
            "human_approval_required": False,
        }
    if department == "maintenance":
        proposed_action = proposal.get("proposed_action", {}) if isinstance(proposal.get("proposed_action"), dict) else {}
        if tool == "create_work_order" and proposed_action.get("work_order_only") is True:
            return {
                "policy_check": "passed_internal_maintenance_work_order_no_reopen",
                "status": "passed",
                "reason": "Maintenance work-order candidate is an internal receiver handoff only; reopen and safety clearance remain blocked.",
                "human_approval_required": False,
            }
        return {
            "policy_check": "requires_maintenance_clearance_before_reopen",
            "status": "requires_compliance",
            "reason": "Maintenance may open work orders and update repair status, but ride reopen remains blocked until inspection clearance.",
            "human_approval_required": False,
        }
    if department == "compliance":
        return {
            "policy_check": "passed_compliance_note_generated",
            "status": "passed",
            "reason": "Compliance proposal records policy constraints and approval requirements for downstream executor gating.",
            "human_approval_required": False,
        }
    if department == "qa_judge" or agent_id == JUDGE_TRACE_EVAL_CONTRACT["owner_agent"]:
        return {
            "policy_check": "passed_trace_eval_contract",
            "status": "passed",
            "reason": "QA Judge owns trace/eval scoring and regression-test recommendations; no receiver action is dispatched.",
            "human_approval_required": False,
        }
    if department == "executive":
        return {
            "policy_check": "approved_safe_low_risk_only_requires_blocks_respected",
            "status": "approved_with_exclusions",
            "reason": "Executive may select only proposals with passed policy checks and must leave safety/security/guest-message actions gated.",
            "human_approval_required": False,
        }
    return {
        "policy_check": "requires_policy_review",
        "status": "requires_compliance",
        "reason": "Proposal requires generic policy review before Tool Executor can act.",
        "human_approval_required": False,
    }


def _apply_native_live_feed_policy(proposal: dict[str, Any]) -> dict[str, Any]:
    policy = _native_live_feed_policy_check(proposal)
    proposal["policy_check"] = policy["policy_check"]
    proposal["policy_judge"] = policy
    envelope = proposal.get("proposal_envelope", {}) if isinstance(proposal.get("proposal_envelope"), dict) else {}
    if envelope:
        envelope["policy_check"] = policy["policy_check"]
        envelope["policy_judge"] = policy
        if (
            policy["status"] in {"passed", "approved_with_exclusions"}
            and (
                envelope.get("executor_status") == "awaiting_compliance"
                or str(policy.get("policy_check") or "").startswith("passed_internal_")
            )
        ):
            envelope["executor_status"] = "ready_for_executor"
            proposal["executor_status"] = "ready_for_executor"
        if policy["status"] in {"requires_human_approval", "blocked"}:
            envelope["executor_status"] = "blocked" if policy["status"] == "blocked" else "awaiting_human_approval"
            proposal["executor_status"] = envelope["executor_status"]
        if policy["status"] == "trace_only":
            envelope["executor_status"] = "trace_only"
            proposal["executor_status"] = "trace_only"
        proposal["proposal_envelope"] = envelope
    return proposal


def _live_feed_reasoning_alternative_tools(department: str, requested_tool: str, action_name: str) -> list[str]:
    fallback_by_department = {
        "operations": ["recommend_route_change", "monitor_ride_flow", "hold_for_executive_tradeoff"],
        "safety": ["require_human_approval", "safety_alert", "monitor_only"],
        "maintenance": ["create_work_order", "inspect_only", "hold_reopen_until_clearance"],
        "guest_experience": ["draft_guest_message", "create_support_ticket", "hold_public_message"],
        "food_retail": ["inventory_alert", "restock_request", "pause_promo"],
        "finance": ["revenue_impact_report", "refund_recommendation_hold", "budget_alert"],
        "hr_labor": ["shift_adjustment_recommendation", "overtime_warning", "break_reminder"],
        "marketing": ["redirect_offer", "pause_promo", "hold_campaign"],
        "security": ["zone_control_recommendation", "escalation_request", "monitor_only"],
        "compliance": ["generate_compliance_note", "block_action", "require_approval"],
        "executive": ["choose_tradeoff", "set_priority", "reject_or_hold_sensitive_action"],
        "qa_judge": ["score_decision", "flag_failure", "create_regression_test"],
    }
    candidates = [requested_tool, action_name]
    candidates.extend(fallback_by_department.get(department, ["monitor_only", "require_review"]))
    result: list[str] = []
    for item in candidates:
        normalized = str(item or "").strip()
        if normalized and normalized not in result:
            result.append(normalized)
    while len(result) < 3:
        result.append(f"review_option_{len(result) + 1}")
    return result[:3]


def _live_feed_reasoning_failure_modes(department: str, policy_status: str, constraints: list[str]) -> list[str]:
    common = [
        "Live feed changes after proposal and invalidates the selected action.",
        "Receiver executes outside the approved department boundary.",
    ]
    department_modes = {
        "operations": ["Routing relief moves too much demand into another constrained zone.", "Ride status changes before the route recommendation is withdrawn."],
        "safety": ["Approval is inferred from weak signals instead of confirmed safety clearance.", "Weather or crowd risk worsens before a human lead reviews the hold."],
        "maintenance": ["Work-order creation is mistaken for ride reopen clearance.", "Inspection history is stale relative to the current asset signal."],
        "guest_experience": ["Draft message implies compensation, private detail, or reopening certainty.", "Guest communication increases demand in a constrained area."],
        "food_retail": ["Promo pause reduces demand but restock still arrives too late.", "Inventory signal lags the actual pickup queue."],
        "finance": ["Revenue estimate is treated as permission to override safety or guest-care gates.", "Refund exposure changes after updated outage duration data arrives."],
        "hr_labor": ["Staff move violates certification, break, fatigue, or overtime rules.", "Coverage improves one zone while exposing another needed role."],
        "marketing": ["Offer redirect creates unintended crowd pressure in the destination zone.", "Campaign action conflicts with Operations or Safety constraints."],
        "security": ["Zone-control recommendation is dispatched without authorized security review.", "Crowd condition changes faster than the escalation path."],
        "compliance": ["Policy note misses a privacy, labor, or safety approval dependency.", "Blocked scope is reintroduced downstream by another department."],
        "executive": ["Tradeoff approves an action whose policy status changed after review.", "Financial or guest-impact pressure masks a safety hold."],
        "qa_judge": ["Trace score misses a missing evidence row or unsupported tool call.", "Regression material is too shallow to catch the same failure later."],
    }
    modes = list(department_modes.get(department, common))
    if policy_status not in {"passed", "approved_with_exclusions", "trace_only"}:
        modes.append("Approval-gated proposal is accidentally routed to execution.")
    for constraint in constraints[:2]:
        modes.append(f"Constraint not enforced: {constraint}")
    modes.extend(common)
    deduped: list[str] = []
    for mode in modes:
        if mode and mode not in deduped:
            deduped.append(mode)
    return deduped[:4]


def _ride_down_recovery_decision_board(
    *,
    proposed_action: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
    event_ids: list[Any],
    policy_status: str,
    evidence_argument: str,
) -> dict[str, Any]:
    affected_ride = proposed_action.get("ride") or proposed_action.get("asset") or "affected_ride"
    summaries = [str(row.get("summary") or row.get("signal_type") or row.get("source") or "live signal") for row in evidence_rows[:5]]
    sources = list(dict.fromkeys(str(row.get("source")) for row in evidence_rows if row.get("source")))
    branches = [
        {
            "branch_id": "split_route_hold_reopen",
            "decision": "preferred_pending_executive",
            "owner": "operations_lead_with_executive",
            "why": "Reduces queue spillback while preserving the safety and maintenance hold on reopening.",
            "required_checks": ["destination density below threshold", "safety does not object", "guest message remains compliance-held"],
            "expected_effect": "Lower queue pressure without promising reopen or moving guests into a constrained destination.",
            "measurement": ["queue spillback", "destination density", "routing take rate", "guest care complaints"],
        },
        {
            "branch_id": "maintenance_reopen_request",
            "decision": "rejected_until_clearance",
            "owner": "maintenance_lead_and_safety",
            "why": "A ride-flow problem cannot become a reopening action until inspection and safety clearance exist.",
            "required_checks": ["inspection log clears asset", "safety removes reopen hold"],
            "expected_effect": "Protects safety boundary even if queue pressure creates revenue or guest-pressure incentives.",
            "measurement": ["inspection status", "safety hold status", "downtime duration"],
        },
        {
            "branch_id": "public_guest_message",
            "decision": "held_for_compliance_and_executive",
            "owner": "compliance_agent_then_executive",
            "why": "Public wording can create demand movement, compensation expectations, or reopening certainty.",
            "required_checks": ["privacy review", "no compensation promise", "destination capacity review"],
            "expected_effect": "Avoids guest confusion without making unsafe or unsupported claims.",
            "measurement": ["complaint rate", "message take rate", "destination density"],
        },
        {
            "branch_id": "monitor_only",
            "decision": "fallback_if_destination_capacity_unclear",
            "owner": "operations_lead",
            "why": "Safer than bad routing when destination capacity or feed confidence is insufficient, but leaves queue pressure unresolved.",
            "required_checks": ["feed freshness", "destination capacity unknown or unsafe"],
            "expected_effect": "Avoids secondary crowding at the cost of slower recovery.",
            "measurement": ["wait time", "queue guests", "operator open cases"],
        },
        {
            "branch_id": "labor_metering_support",
            "decision": "supporting_branch_only",
            "owner": "hr_labor_agent",
            "why": "Staff can meter flow and answer questions, but labor support does not authorize routing, reopening, or public messaging.",
            "required_checks": ["skill match", "break protection", "fatigue and overtime limits"],
            "expected_effect": "Improves follow-through quality without crossing department write authority.",
            "measurement": ["staff coverage", "break exceptions", "queue edge incidents"],
        },
    ]
    return {
        "mode": "ride_down_recovery_decision_board",
        "affected_ride": affected_ride,
        "selected_branch_id": "split_route_hold_reopen",
        "policy_status": policy_status,
        "live_feed_sources": sources,
        "live_feed_event_ids": event_ids[:8],
        "live_evidence_summary": summaries,
        "evidence_argument": evidence_argument,
        "tradeoff_vector": {
            "safety": "reopen and security-sensitive actions stay held until authorized checks clear",
            "guest": "split routing can reduce queue frustration but must not overload destination zones",
            "labor": "staffing support is bounded by skill, fatigue, break, and overtime limits",
            "finance": "revenue and refund exposure inform priority but cannot override safety gates",
            "communications": "guest message is useful but remains compliance/executive gated",
        },
        "branch_count": len(branches),
        "branches": branches,
        "explicit_rejections": [
            "No ride reopening from an operations recommendation.",
            "No public guest message from the Operations Agent.",
            "No route execution until Executive selects a destination and Safety accepts the destination crowd risk.",
        ],
        "learning_carry_forward": {
            "scenario_slice": "ride_down",
            "label": "ride_down_branch_tradeoff",
            "selected_branch": "split_route_hold_reopen",
            "rejected_branches": [branch["branch_id"] for branch in branches if branch["decision"].startswith("rejected")],
            "next_eval_question": "Did split routing reduce queue pressure without increasing destination density or guest complaints?",
        },
    }


def _live_feed_department_reasoning(proposal: dict[str, Any], evidence_rows: list[dict[str, Any]], constraints: list[str], confidence: float) -> dict[str, Any]:
    envelope = proposal.get("proposal_envelope", {}) if isinstance(proposal.get("proposal_envelope"), dict) else {}
    proposed_action = proposal.get("proposed_action", {}) if isinstance(proposal.get("proposed_action"), dict) else {}
    grounding = proposal.get("live_feed_grounding", {}) if isinstance(proposal.get("live_feed_grounding"), dict) else {}
    policy = proposal.get("policy_judge", {}) if isinstance(proposal.get("policy_judge"), dict) else {}
    department = str(proposal.get("department") or envelope.get("department") or "")
    requested_tool = str(envelope.get("requested_tool") or proposal.get("requested_tool") or proposed_action.get("action") or "")
    action_name = str(proposed_action.get("action") or requested_tool or "review")
    sources = grounding.get("sources", []) if isinstance(grounding.get("sources"), list) else []
    event_ids = grounding.get("event_ids", []) if isinstance(grounding.get("event_ids"), list) else []
    evidence_summaries = [str(row.get("summary") or row.get("signal_type") or row.get("source") or "live signal") for row in evidence_rows[:3]]
    evidence_snapshot = _compact_live_feed_evidence_snapshot(evidence_rows, 4)
    max_age = max([float(row.get("age_seconds") or 0) for row in evidence_rows] or [0])
    confidence_values = [float(row.get("confidence") or 0) for row in evidence_rows]
    evidence_confidence = round(sum(confidence_values) / len(confidence_values), 3) if confidence_values else None
    policy_status = str(policy.get("status") or envelope.get("executor_status") or "pending")
    evidence_argument = _evidence_argument_from_rows(department, evidence_rows, policy_status)
    alternatives = _live_feed_reasoning_alternative_tools(department, requested_tool, action_name)
    candidate_actions = []
    for index, option in enumerate(alternatives):
        selected = option in {requested_tool, action_name}
        candidate_actions.append(
            {
                "rank": index + 1,
                "action": option,
                "selected": selected and index == 0,
                "expected_effect": str(proposed_action.get("expected_outcome") or envelope.get("expected_outcome") or proposal.get("recommendation")) if selected else "lower-risk fallback or hold path if live evidence or policy changes",
                "evidence_basis": evidence_argument,
                "risk": envelope.get("risk_level") if selected else "lower" if "hold" in option or "monitor" in option else "medium",
                "score": round(max(0.1, min(0.99, float(confidence) - (index * 0.08))), 2),
            }
        )
    event_clause = f"events {', '.join(str(item) for item in event_ids[:4])}" if event_ids else "no persisted event ids"
    observe = f"Read {len(evidence_rows)} live feed rows from {', '.join(sources) if sources else 'available sources'} with {event_clause}."
    interpret = f"{department or 'department'} pressure is tied to {evidence_summaries[0] if evidence_summaries else 'the live feed case'}; evidence argument: {evidence_argument}"
    predict = str(proposed_action.get("expected_outcome") or envelope.get("expected_outcome") or proposal.get("recommendation"))
    recommend = f"Select {requested_tool or action_name} and keep execution behind policy and Tool Executor gates."
    justify = f"Uses event ids {', '.join(str(item) for item in event_ids[:4]) if event_ids else 'none'} with policy status {policy_status}; top live evidence says {evidence_summaries[0] if evidence_summaries else 'no summary'}."
    trace = "Record diagnosis, candidate comparison, forecast, failure modes, policy result, and executor outcome for memory."
    reasoning = {
        "contract": "observe_interpret_predict_recommend_justify_trace",
        "diagnosis": {
            "department": department,
            "live_sources": sources,
            "event_ids": event_ids[:8],
            "evidence_count": len(evidence_rows),
            "evidence_confidence": evidence_confidence,
            "max_evidence_age_seconds": max_age,
            "primary_signal": evidence_summaries[0] if evidence_summaries else None,
            "evidence_snapshot": evidence_snapshot,
            "evidence_argument": evidence_argument,
            "constraints_considered": constraints[:5],
        },
        "evidence_snapshot": evidence_snapshot,
        "evidence_argument": evidence_argument,
        "agent_loop": {
            "observe": observe,
            "interpret": interpret,
            "predict": predict,
            "recommend": recommend,
            "justify": justify,
            "trace": trace,
        },
        "candidate_actions": candidate_actions,
        "forecast": {
            "horizon_minutes": 45 if department in {"food_retail", "operations", "guest_experience"} else 30,
            "expected_outcome": predict,
            "confidence": round(max(0.0, min(1.0, confidence)), 2),
            "measurement_signals": sources,
            "rollback_trigger": envelope.get("rollback") or proposed_action.get("rollback"),
        },
        "failure_modes": _live_feed_reasoning_failure_modes(department, policy_status, constraints),
        "selected_rationale": f"{requested_tool or action_name} best matches {department or 'the department'} write authority while preserving policy status {policy_status}; live basis: {evidence_argument}",
        "memory_carry_forward": {
            "carry": ["evidence_source_relevance", "policy_outcome", "executor_result", "measured_outcome"],
            "do_better_next_time": ["compare fallback action outcomes", "tighten failure-mode detection", "adjust memory priors only for policy-eligible departments"],
        },
        "depth_score": round(min(0.98, 0.58 + min(len(candidate_actions), 3) * 0.08 + min(len(evidence_rows), 4) * 0.04 + min(len(constraints), 3) * 0.03), 2),
    }
    if department == "operations" and ("ride" in str(proposed_action.get("target") or "").lower() or "route" in requested_tool.lower()):
        recovery_board = _ride_down_recovery_decision_board(
            proposed_action=proposed_action,
            evidence_rows=evidence_rows,
            event_ids=event_ids,
            policy_status=policy_status,
            evidence_argument=evidence_argument,
        )
        reasoning["ride_down_recovery_board"] = recovery_board
        reasoning["forecast"]["ride_down_selected_branch"] = recovery_board["selected_branch_id"]
        reasoning["memory_carry_forward"]["carry"].extend(["ride_down_selected_branch", "ride_down_rejected_branches", "destination_density_outcome"])
        reasoning["memory_carry_forward"]["do_better_next_time"].insert(0, recovery_board["learning_carry_forward"]["next_eval_question"])
    return reasoning


def _proposal_has_deep_department_reasoning(proposal: dict[str, Any]) -> bool:
    reasoning = proposal.get("department_reasoning", {}) if isinstance(proposal.get("department_reasoning"), dict) else {}
    loop = proposal.get("agent_loop", {}) if isinstance(proposal.get("agent_loop"), dict) else {}
    return (
        bool(reasoning.get("diagnosis"))
        and isinstance(reasoning.get("candidate_actions"), list)
        and len(reasoning.get("candidate_actions", [])) >= 2
        and bool(reasoning.get("forecast"))
        and isinstance(reasoning.get("failure_modes"), list)
        and len(reasoning.get("failure_modes", [])) >= 2
        and bool(reasoning.get("selected_rationale"))
        and all(step in loop and loop.get(step) for step in DEPARTMENT_AGENT_LOOP)
    )


def _live_feed_action_disposition(proposal: dict[str, Any]) -> dict[str, Any]:
    envelope = proposal.get("proposal_envelope", {}) if isinstance(proposal.get("proposal_envelope"), dict) else {}
    policy = proposal.get("policy_judge", {}) if isinstance(proposal.get("policy_judge"), dict) else {}
    department = str(proposal.get("department") or envelope.get("department") or "")
    tool = str(envelope.get("requested_tool") or proposal.get("requested_tool") or "")
    policy_status = str(policy.get("status") or "")
    executor_status = str(envelope.get("executor_status") or proposal.get("executor_status") or "")
    evidence_argument = _evidence_argument_from_proposal(proposal)
    grounding = proposal.get("live_feed_grounding", {}) if isinstance(proposal.get("live_feed_grounding"), dict) else {}
    event_ids = grounding.get("event_ids", []) if isinstance(grounding.get("event_ids"), list) else []
    if department in {"food_retail", "hr_labor", "marketing", "operations", "maintenance"} and policy_status == "passed" and executor_status == "ready_for_executor":
        return {
            "decision": "execute_controlled_internal",
            "next_owner": "tool_executor_agent",
            "evidence_argument": evidence_argument,
            "live_feed_event_ids": event_ids,
            "why_not_undecided": f"Low-risk bounded internal action passed policy and has a configured controlled receiver. Live basis: {evidence_argument}",
            "exit_condition": "Receiver acknowledges the controlled internal handoff or live feed normalizes and rollback supersedes it.",
            "fallback": "Withdraw controlled action if post-action feed measurement worsens.",
        }
    if department == "operations":
        return {
            "decision": "reject_execution_hold_recommendation",
            "next_owner": "operations_lead_with_executive",
            "evidence_argument": evidence_argument,
            "live_feed_event_ids": event_ids,
            "why_not_undecided": f"Routing can change crowd safety, so execution is rejected until Executive selects a safe route. Live basis: {evidence_argument}",
            "exit_condition": f"Executive approves a specific route after Safety confirms destination density stays below threshold for events {', '.join(str(item) for item in event_ids[:4]) or 'attached live-feed evidence'}.",
            "fallback": "Keep monitoring ride and guest-flow pressure; do not send guest routing directly.",
        }
    if department == "guest_experience":
        return {
            "decision": "hold_message_for_compliance",
            "next_owner": "compliance_agent_then_executive",
            "evidence_argument": evidence_argument,
            "live_feed_event_ids": event_ids,
            "why_not_undecided": f"The draft is useful, but public communication is rejected until privacy, promise, and crowd-pressure checks pass. Live basis: {evidence_argument}",
            "exit_condition": "Compliance approves wording and Executive approves the destination demand effect.",
            "fallback": "Keep internal support ticket context only; send no public message.",
        }
    if department == "maintenance":
        return {
            "decision": "open_review_do_not_reopen",
            "next_owner": "maintenance_lead_and_safety",
            "evidence_argument": evidence_argument,
            "live_feed_event_ids": event_ids,
            "why_not_undecided": f"Work-order review can proceed, but reopen authority is denied without inspection clearance. Live basis: {evidence_argument}",
            "exit_condition": f"Inspection log clears the asset and Safety removes the hold for events {', '.join(str(item) for item in event_ids[:4]) or 'attached live-feed evidence'}.",
            "fallback": "Keep ride reopen blocked and continue capacity mitigation.",
        }
    if department in {"safety", "security"}:
        return {
            "decision": "require_authorized_human_approval",
            "next_owner": f"{department}_lead",
            "evidence_argument": evidence_argument,
            "live_feed_event_ids": event_ids,
            "why_not_undecided": f"{department.title()} action is not left open; execution is denied until an authorized lead approves it. Live basis: {evidence_argument}",
            "exit_condition": f"Authorized lead approves the specific action with current live-feed evidence attached: {', '.join(str(item) for item in event_ids[:4]) or 'event ids pending'}.",
            "fallback": "Maintain monitoring and escalation note; Tool Executor dispatch remains blocked.",
        }
    if department == "finance":
        return {
            "decision": "report_only_no_comp_commitment",
            "next_owner": "executive_agent",
            "evidence_argument": evidence_argument,
            "live_feed_event_ids": event_ids,
            "why_not_undecided": f"Finance impact can inform the tradeoff, but compensation or refund commitment is rejected for automatic execution. Live basis: {evidence_argument}",
            "exit_condition": "Executive chooses a guest-recovery policy inside budget and compliance constraints.",
            "fallback": "Use impact report as context only.",
        }
    if department == "compliance":
        return {
            "decision": "policy_note_committed",
            "next_owner": "executive_agent",
            "evidence_argument": evidence_argument,
            "live_feed_event_ids": event_ids,
            "why_not_undecided": f"Compliance writes the approval requirements that narrow the remaining choices. Live basis: {evidence_argument}",
            "exit_condition": "All downstream actions cite the compliance note and satisfy its required approvals.",
            "fallback": "Block any action that lacks the named approval chain.",
        }
    if department == "qa_judge":
        return {
            "decision": "score_trace_and_flag_regression",
            "next_owner": "qa_judge_agent",
            "evidence_argument": evidence_argument,
            "live_feed_event_ids": event_ids,
            "why_not_undecided": f"QA does not execute park actions; it scores trace quality and creates regression material for failures. Live basis: {evidence_argument}",
            "exit_condition": "Trace, policy, executor, delivery, measurement, and memory artifacts are complete.",
            "fallback": "Flag failed contract and create a regression case.",
        }
    return {
        "decision": "tradeoff_review_only",
        "next_owner": "decision_bridge_agent",
        "evidence_argument": evidence_argument,
        "live_feed_event_ids": event_ids,
        "why_not_undecided": f"Proposal remains a bounded tradeoff input, not an executable action. Live basis: {evidence_argument}",
        "exit_condition": "Executive records approve, reject, or hold with policy evidence.",
        "fallback": "Keep proposal in trace only.",
    }


def _live_feed_native_proposal(
    agent_id: str,
    recommendation: str,
    proposed_action: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
    constraints: list[str],
    confidence: float,
    proposal_type: str,
) -> dict[str, Any]:
    proposal = _role_proposal(
        agent_id,
        recommendation,
        proposed_action,
        _live_feed_grounded_evidence(evidence_rows),
        constraints,
        confidence,
        proposal_type,
    )
    proposal = _attach_native_live_feed_grounding(proposal, evidence_rows)
    proposal = _apply_native_live_feed_policy(proposal)
    reasoning = _live_feed_department_reasoning(proposal, evidence_rows, constraints, confidence)
    proposal["department_reasoning"] = reasoning
    proposal["agent_loop"] = reasoning["agent_loop"]
    disposition = _live_feed_action_disposition(proposal)
    proposal["action_disposition"] = disposition
    envelope = proposal.get("proposal_envelope", {}) if isinstance(proposal.get("proposal_envelope"), dict) else {}
    if envelope:
        envelope["department_reasoning_summary"] = {
            "contract": reasoning["contract"],
            "candidate_action_count": len(reasoning["candidate_actions"]),
            "failure_mode_count": len(reasoning["failure_modes"]),
            "depth_score": reasoning["depth_score"],
        }
        envelope["action_disposition"] = disposition
        proposal["proposal_envelope"] = envelope
    return proposal


def _generated_issue_from_live_case(live_feed_case: dict[str, Any]) -> dict[str, Any]:
    issue = live_feed_case.get("generated_issue", {}) if isinstance(live_feed_case.get("generated_issue"), dict) else {}
    return {
        "kind": str(issue.get("kind") or live_feed_case.get("issue_kind") or ""),
        "target_id": str(issue.get("target_id") or issue.get("targetId") or live_feed_case.get("issue_target_id") or ""),
        "intensity": issue.get("intensity"),
        "selection_mode": issue.get("selection_mode"),
    }


def _issue_specific_live_feed_proposals(
    live_feed_case: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issue = _generated_issue_from_live_case(live_feed_case)
    kind = issue["kind"]
    target_id = issue["target_id"] or "affected_area"
    ops_rows = _live_feed_rows_for_sources(evidence_rows, {"ride_ops", "guest_flow", "operator_signal"})
    maintenance_rows = _live_feed_rows_for_sources(evidence_rows, {"operator_signal", "ride_ops", "weather", "food_ops"})
    safety_rows = _live_feed_rows_for_sources(evidence_rows, {"weather", "operator_signal", "ride_ops", "guest_flow"})
    security_rows = _live_feed_rows_for_sources(evidence_rows, {"operator_signal", "guest_flow", "ride_ops"})
    guest_rows = _live_feed_rows_for_sources(evidence_rows, {"guest_flow", "operator_signal", "ride_ops"})
    proposals: list[dict[str, Any]] = []

    def add(agent_id: str, recommendation: str, action: dict[str, Any], rows: list[dict[str, Any]], constraints: list[str], confidence: float, proposal_type: str = "action") -> None:
        payload = {
            **action,
            "issue_kind": kind,
            "issue_target_id": target_id,
            "issue_specific": True,
        }
        proposal = _live_feed_native_proposal(agent_id, recommendation, payload, rows, constraints, confidence, proposal_type)
        proposal["issue_specific"] = True
        proposal["generated_issue_context"] = issue
        proposals.append(proposal)

    if kind in {"energy_spike", "sensor_anomaly", "water_leak"}:
        add(
            "facilities_energy_agent",
            f"Open a bounded maintenance work-order candidate for {kind} at {target_id}; do not imply ride reopen or safety clearance",
            {
                "target": "maintenance",
                "action": "create_work_order",
                "asset": target_id,
                "work_order_only": True,
                "expected_outcome": "maintenance receiver gets an internal work-order candidate tied to live feed evidence",
                "rollback": "close the candidate if sensor/operator evidence normalizes or inspection rejects the fault",
            },
            maintenance_rows,
            ["Work-order handoff is internal only.", "No reopen, dispatch, or public instruction is authorized."],
            0.86,
            "action",
        )
        add(
            "safety_policy_agent",
            f"Hold safety-sensitive execution for {kind} until authorized review clears {target_id}",
            {
                "target": "safety",
                "action": "require_human_approval",
                "requires_human_review": True,
                "expected_outcome": "safety owner receives the approval boundary and live-feed evidence",
                "rollback": "remove hold only after inspection and safety lead clearance",
            },
            safety_rows,
            ["Safety hold cannot be converted into Tool Executor action.", "Maintenance work order is not clearance."],
            0.92,
            "gate",
        )
    if kind in {"ticketing_gate_surge", "parking_arrival_wave", "parade_route_conflict", "access_lane_block"}:
        add(
            "ride_ops_agent",
            f"Create an internal operations alert for {kind} at {target_id}; keep actual routing changes under Executive/Safety approval",
            {
                "target": "operations",
                "action": "ops_alert",
                "zone": target_id,
                "expected_outcome": "operations receiver sees an arrival/access flow alert without executing guest routing",
                "rollback": "close the alert if guest-flow and operator-signal feeds normalize",
            },
            ops_rows,
            ["Ops alert is internal only.", "No route change or public guest message is executed."],
            0.84,
            "action",
        )
        add(
            "security_agent",
            f"Review security/access-control implications for {kind} at {target_id} before any zone-control action",
            {
                "target": "security",
                "action": "zone_control",
                "zone": target_id,
                "expected_outcome": "security lead receives a zone-control recommendation with live feed evidence",
                "rollback": "stand down if access and density signals normalize",
            },
            security_rows,
            ["Security zone control requires authorized human approval.", "Ops alert cannot substitute for security approval."],
            0.83,
            "gate",
        )
    if kind in {"restroom_closure"}:
        add(
            "facilities_energy_agent",
            f"Open a facilities work-order candidate for restroom closure at {target_id}",
            {
                "target": "maintenance",
                "action": "create_work_order",
                "asset": target_id,
                "work_order_only": True,
                "expected_outcome": "facilities receiver gets an internal service-restoration work-order candidate",
                "rollback": "close the work-order candidate if operator signal marks the closure resolved",
            },
            maintenance_rows,
            ["Work-order handoff does not send guest messaging.", "Accessibility and service recovery remain separate approvals."],
            0.85,
            "action",
        )
        add(
            "guest_flow_agent",
            f"Draft restroom-closure service guidance for {target_id}, but hold all public messaging for Compliance",
            {
                "target": "guest",
                "action": "message",
                "routing": "nearest_accessible_restroom_alternatives",
                "expected_outcome": "guest-experience draft exists for review without public dispatch",
                "rollback": "withdraw draft if facilities resolves the closure",
            },
            guest_rows,
            ["Public guest messaging remains compliance-gated.", "Do not promise reopening time."],
            0.82,
            "tradeoff",
        )
    return proposals


def _issue_specific_live_feed_conflicts(issue_proposals: list[dict[str, Any]], issue: dict[str, Any]) -> list[dict[str, Any]]:
    if not issue_proposals:
        return []
    kind = str(issue.get("kind") or "issue")
    agents = [str(row.get("agent_id")) for row in issue_proposals if row.get("agent_id")]
    return [
        {
            "conflict": f"{kind} needs direct issue handling, but safety/security/public-routing authority must remain gated.",
            "agents": agents[:5],
            "resolution": "Execute only bounded internal ops/work-order alerts; keep route changes, safety clearance, security control, and public messaging held with owners.",
            "status": "resolved_with_bounded_execution",
        }
    ]


def _live_feed_deep_reasoning_summary(proposals: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "deep_reasoning_proposal_count": sum(1 for proposal in proposals if _proposal_has_deep_department_reasoning(proposal)),
        "candidate_action_count": sum(len((proposal.get("department_reasoning", {}) if isinstance(proposal.get("department_reasoning"), dict) else {}).get("candidate_actions", [])) for proposal in proposals),
        "failure_mode_count": sum(len((proposal.get("department_reasoning", {}) if isinstance(proposal.get("department_reasoning"), dict) else {}).get("failure_modes", [])) for proposal in proposals),
    }


def _park_profile_from_context(retrieved_context: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(retrieved_context, dict):
        return {}
    for key in ("park_profile", "venue_profile", "venueProfile", "venueExperienceData"):
        value = retrieved_context.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _profile_real_inputs(profile: dict[str, Any]) -> dict[str, Any]:
    return profile.get("realInputs", {}) if isinstance(profile.get("realInputs"), dict) else {}


def _profile_intelligence(profile: dict[str, Any]) -> dict[str, Any]:
    real_inputs = _profile_real_inputs(profile)
    return real_inputs.get("profileIntelligence", {}) if isinstance(real_inputs.get("profileIntelligence"), dict) else {}


def _profile_version(profile: dict[str, Any]) -> str:
    identity = profile.get("venueIdentity", {}) if isinstance(profile.get("venueIdentity"), dict) else {}
    readiness = profile.get("readiness", {}) if isinstance(profile.get("readiness"), dict) else {}
    source = profile.get("sourceIntegrity", {}) if isinstance(profile.get("sourceIntegrity"), dict) else {}
    return ":".join(
        str(item or "unknown")
        for item in [
            identity.get("venueId"),
            identity.get("profileType") or source.get("profileType"),
            readiness.get("loadedFrom"),
        ]
    )


def _profile_zone_role_index(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    real_inputs = _profile_real_inputs(profile)
    zones = real_inputs.get("zoneDetails", {}) if isinstance(real_inputs.get("zoneDetails"), dict) else {}
    capacity_rows = ((_profile_intelligence(profile).get("capacityModel", {}) if isinstance(_profile_intelligence(profile).get("capacityModel"), dict) else {}).get("zoneComfort", []))
    capacity_by_zone = {
        str(row.get("zoneId")): row
        for row in capacity_rows
        if isinstance(row, dict) and row.get("zoneId")
    }
    result: dict[str, dict[str, Any]] = {}
    for zone_id, zone in zones.items():
        if not isinstance(zone, dict):
            continue
        merged = deepcopy(zone)
        if str(zone_id) in capacity_by_zone:
            merged["capacity"] = capacity_by_zone[str(zone_id)]
        result[str(zone_id)] = merged
    return result


def _profile_locations_for_department(profile: dict[str, Any], department: str) -> list[dict[str, Any]]:
    details = _profile_real_inputs(profile).get("locationDetails", {})
    if not isinstance(details, dict):
        return []
    allowed_kinds = {
        "operations": {"attraction", "show", "quiet_or_cooling", "food", "family_service"},
        "safety": {"first_aid", "guest_services", "family_service", "quiet_or_cooling"},
        "security": {"guest_services", "family_service", "restrooms", "first_aid"},
        "maintenance": {"attraction", "show"},
        "guest_experience": {"guest_services", "family_service", "quiet_or_cooling", "show", "food"},
        "food_retail": {"food"},
        "finance": {"food", "attraction", "show"},
        "hr_labor": {"food", "attraction", "show", "guest_services"},
        "marketing": {"food", "show", "attraction", "quiet_or_cooling"},
        "compliance": {"guest_services", "first_aid", "food", "attraction"},
        "executive": {"food", "show", "attraction", "guest_services", "quiet_or_cooling"},
        "qa_judge": {"food", "show", "attraction", "guest_services", "quiet_or_cooling"},
    }.get(department, set())
    rows = []
    for name, item in details.items():
        if not isinstance(item, dict):
            continue
        if allowed_kinds and str(item.get("kind") or "") not in allowed_kinds:
            continue
        rows.append(
            {
                "name": item.get("name") or name,
                "kind": item.get("kind"),
                "zoneId": item.get("zoneId"),
                "covered": item.get("covered"),
                "indoor": item.get("indoor"),
                "accessibilityNote": item.get("accessibilityNote"),
                "sensoryNote": item.get("sensoryNote"),
            }
        )
    return rows[:6]


def _profile_module_policy_for_department(profile: dict[str, Any], department: str) -> dict[str, Any]:
    intelligence = _profile_intelligence(profile)
    module_policy = intelligence.get("modulePolicy", {}) if isinstance(intelligence.get("modulePolicy"), dict) else {}
    if department in {"operations", "safety", "security", "maintenance", "hr_labor", "executive", "compliance", "qa_judge"}:
        return module_policy.get("command_center_review", {}) if isinstance(module_policy.get("command_center_review"), dict) else {}
    if department == "guest_experience":
        return module_policy.get("accessibility_journey", {}) if isinstance(module_policy.get("accessibility_journey"), dict) else {}
    if department in {"marketing", "food_retail", "finance"}:
        return module_policy.get("experience_studio", {}) if isinstance(module_policy.get("experience_studio"), dict) else {}
    return {}


def _profile_slice_for_department(profile: dict[str, Any], department: str, proposal: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(profile, dict) or not profile:
        return {
            "status": "missing",
            "profile_version": None,
            "profile_fields_used": [],
            "profile_constraints": ["No active park profile was attached; use live feed and policy only."],
            "reasoning_effect": "No profile effect.",
            "precedence": "live_feed_over_profile_policy_over_both",
        }
    real_inputs = _profile_real_inputs(profile)
    intelligence = _profile_intelligence(profile)
    readiness = profile.get("readiness", {}) if isinstance(profile.get("readiness"), dict) else {}
    identity = profile.get("venueIdentity", {}) if isinstance(profile.get("venueIdentity"), dict) else {}
    agent_context = real_inputs.get("agentContext", {}) if isinstance(real_inputs.get("agentContext"), dict) else {}
    operating_priors = real_inputs.get("operatingPriors", {}) if isinstance(real_inputs.get("operatingPriors"), dict) else {}
    learning_context = real_inputs.get("learningContext", {}) if isinstance(real_inputs.get("learningContext"), dict) else {}
    zone_index = _profile_zone_role_index(profile)
    locations = _profile_locations_for_department(profile, department)
    policy = _profile_module_policy_for_department(profile, department)
    capacity_model = intelligence.get("capacityModel", {}) if isinstance(intelligence.get("capacityModel"), dict) else {}
    live_bindings = intelligence.get("liveFeedBindings", {}) if isinstance(intelligence.get("liveFeedBindings"), dict) else {}
    relevant_zone_ids = list(
        dict.fromkeys(
            [
                str(item.get("zoneId"))
                for item in locations
                if item.get("zoneId")
            ]
        )
    )[:5]
    relevant_zones = [zone_index[zone_id] for zone_id in relevant_zone_ids if zone_id in zone_index]
    fields_used = [
        "venueIdentity",
        "realInputs.locationDetails",
        "realInputs.zoneDetails",
        "realInputs.spatialModel.paths",
        "realInputs.operatingPriors.zoneDemandPriors",
        "realInputs.profileIntelligence.capacityModel",
        "realInputs.profileIntelligence.modulePolicy",
        "realInputs.profileIntelligence.liveFeedBindings",
        "realInputs.learningContext",
    ]
    constraints = [
        *(policy.get("mustReview", []) if isinstance(policy.get("mustReview"), list) else []),
        *(policy.get("neverClaim", []) if isinstance(policy.get("neverClaim"), list) else []),
        *(capacity_model.get("blockedClaims", []) if isinstance(capacity_model.get("blockedClaims"), list) else []),
        *(agent_context.get("humanReviewTriggers", [])[:3] if isinstance(agent_context.get("humanReviewTriggers"), list) else []),
    ]
    reasoning_effect = (
        f"{department} uses profile zones, locations, path/capacity priors, and module policy to narrow candidates; "
        "live feed still decides current pressure and policy still controls authority."
    )
    return {
        "status": "attached",
        "profile_version": _profile_version(profile),
        "venue_name": identity.get("name"),
        "readiness_status": readiness.get("status"),
        "source_integrity": profile.get("sourceIntegrity", {}),
        "profile_fields_used": fields_used,
        "profile_constraints": list(dict.fromkeys(str(item) for item in constraints if str(item or "").strip()))[:10],
        "relevant_locations": locations,
        "relevant_zones": [
            {
                "id": zone.get("id"),
                "name": zone.get("name"),
                "role": zone.get("role"),
                "indoorOrSheltered": zone.get("indoorOrSheltered"),
                "quietOrCooling": zone.get("quietOrCooling"),
                "spillbackRisk": (zone.get("capacity", {}) if isinstance(zone.get("capacity"), dict) else {}).get("spillbackRisk"),
                "comfortCapacityEstimate": (zone.get("capacity", {}) if isinstance(zone.get("capacity"), dict) else {}).get("comfortCapacityEstimate"),
                "agentReasoningHints": zone.get("agentReasoningHints", []),
            }
            for zone in relevant_zones[:5]
        ],
        "operating_priors": (operating_priors.get("zoneDemandPriors", []) if isinstance(operating_priors.get("zoneDemandPriors"), list) else [])[:5],
        "live_feed_bindings": live_bindings,
        "learning_schema": {
            "observationKeys": (learning_context.get("observationKeys", []) if isinstance(learning_context.get("observationKeys"), list) else [])[:8],
            "feedbackLabels": (learning_context.get("feedbackLabels", []) if isinstance(learning_context.get("feedbackLabels"), list) else [])[:8],
        },
        "reasoning_effect": reasoning_effect,
        "precedence": "live_feed_over_profile_policy_over_both",
        "live_state_override_rule": "When live feed contradicts profile priors, use live feed for current operating state and retain profile only as context.",
    }


def _attach_park_profile_context(proposals: list[dict[str, Any]], profile: dict[str, Any]) -> dict[str, Any]:
    attached = 0
    fields: set[str] = set()
    scored_candidates = 0
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        department = str(proposal.get("department") or "")
        profile_context = _profile_slice_for_department(profile, department, proposal)
        proposal["park_profile_context"] = profile_context
        proposal["profile_precedence"] = profile_context.get("precedence")
        if profile_context.get("status") == "attached":
            attached += 1
        fields.update(str(item) for item in profile_context.get("profile_fields_used", []) if item)
        reasoning = proposal.get("department_reasoning", {}) if isinstance(proposal.get("department_reasoning"), dict) else {}
        if reasoning:
            scored_candidates += _attach_profile_counterfactuals_to_reasoning(reasoning, profile_context, department)
            reasoning["park_profile_context"] = {
                "status": profile_context.get("status"),
                "profile_version": profile_context.get("profile_version"),
                "profile_fields_used": profile_context.get("profile_fields_used", []),
                "profile_constraints": profile_context.get("profile_constraints", []),
                "profile_counterfactual_summary": reasoning.get("profile_counterfactual_summary", {}),
                "reasoning_effect": profile_context.get("reasoning_effect"),
                "precedence": profile_context.get("precedence"),
            }
            forecast = reasoning.get("forecast", {}) if isinstance(reasoning.get("forecast"), dict) else {}
            if forecast:
                forecast["profile_adjustment"] = profile_context.get("reasoning_effect")
            proposal["department_reasoning"] = reasoning
        envelope = proposal.get("proposal_envelope", {}) if isinstance(proposal.get("proposal_envelope"), dict) else {}
        if envelope:
            envelope["park_profile_context_summary"] = {
                "status": profile_context.get("status"),
                "profile_version": profile_context.get("profile_version"),
                "field_count": len(profile_context.get("profile_fields_used", [])),
                "constraint_count": len(profile_context.get("profile_constraints", [])),
                "precedence": profile_context.get("precedence"),
            }
            proposal["proposal_envelope"] = envelope
    return {
        "park_profile_context_status": "attached" if attached else "missing",
        "profile_context_proposal_count": attached,
        "profile_counterfactual_candidate_count": scored_candidates,
        "profile_field_count": len(fields),
        "profile_version": _profile_version(profile) if profile else None,
        "precedence": "live_feed_over_profile_policy_over_both",
    }


def _profile_counterfactual_for_action(action: str, profile_context: dict[str, Any], department: str) -> dict[str, Any]:
    action_text = str(action or "").lower()
    relevant_zones = profile_context.get("relevant_zones", []) if isinstance(profile_context.get("relevant_zones"), list) else []
    constraints = profile_context.get("profile_constraints", []) if isinstance(profile_context.get("profile_constraints"), list) else []
    sheltered_count = sum(1 for zone in relevant_zones if isinstance(zone, dict) and zone.get("indoorOrSheltered"))
    quiet_count = sum(1 for zone in relevant_zones if isinstance(zone, dict) and zone.get("quietOrCooling"))
    high_spillback_count = sum(1 for zone in relevant_zones if isinstance(zone, dict) and str(zone.get("spillbackRisk") or "").lower() == "high")
    capacity_values = [
        float(zone.get("comfortCapacityEstimate"))
        for zone in relevant_zones
        if isinstance(zone, dict) and isinstance(zone.get("comfortCapacityEstimate"), (int, float))
    ]
    avg_capacity = round(sum(capacity_values) / len(capacity_values), 1) if capacity_values else None
    score = 0.5
    reasons: list[str] = []
    if profile_context.get("status") == "attached":
        score += 0.08
        reasons.append("profile attached")
    if "redirect" in action_text or "route" in action_text or "message" in action_text:
        if high_spillback_count:
            score -= 0.12
            reasons.append("profile shows high spillback risk in relevant zones")
        if sheltered_count or quiet_count:
            score += 0.08
            reasons.append("profile has sheltered or reset zones for safer demand shaping")
    if "hold" in action_text or "monitor" in action_text or "approval" in action_text:
        score += 0.1
        reasons.append("profile policy favors review/hold for sensitive actions")
    if "promo" in action_text or "inventory" in action_text or "restock" in action_text:
        if department == "food_retail":
            score += 0.1
            reasons.append("profile identifies food locations and dining zones")
        if high_spillback_count:
            score -= 0.05
            reasons.append("food/dwell zones have spillback sensitivity")
    if "staff" in action_text or "shift" in action_text or "break" in action_text:
        score -= 0.04
        reasons.append("profile excludes live staffing truth; live feed and labor policy must decide")
    if "safety" in action_text or "security" in action_text or "reopen" in action_text:
        score -= 0.1
        reasons.append("profile cannot authorize safety/security/reopen decisions")
    if constraints:
        score -= min(0.12, len(constraints) * 0.01)
        reasons.append(f"{len(constraints)} profile policy constraints apply")
    return {
        "score": round(max(0.05, min(0.95, score)), 2),
        "relevant_zone_count": len(relevant_zones),
        "sheltered_zone_count": sheltered_count,
        "quiet_zone_count": quiet_count,
        "high_spillback_zone_count": high_spillback_count,
        "avg_comfort_capacity": avg_capacity,
        "constraint_count": len(constraints),
        "profile_effect": "supports_candidate" if score >= 0.62 else "penalizes_candidate" if score <= 0.42 else "context_only",
        "reasons": reasons[:5] or ["profile provides neutral context"],
        "precedence": profile_context.get("precedence"),
    }


def _attach_profile_counterfactuals_to_reasoning(reasoning: dict[str, Any], profile_context: dict[str, Any], department: str) -> int:
    candidates = reasoning.get("candidate_actions", []) if isinstance(reasoning.get("candidate_actions"), list) else []
    scored = 0
    best_action = None
    best_score = -1.0
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        counterfactual = _profile_counterfactual_for_action(str(candidate.get("action") or ""), profile_context, department)
        base_score = float(candidate.get("score") or 0)
        combined = round(max(0.05, min(0.99, (base_score * 0.7) + (float(counterfactual["score"]) * 0.3))), 2)
        candidate["profile_counterfactual"] = counterfactual
        candidate["profile_adjusted_score"] = combined
        candidate["profile_score_delta"] = round(combined - base_score, 2)
        scored += 1
        if combined > best_score:
            best_score = combined
            best_action = candidate.get("action")
    reasoning["profile_counterfactual_summary"] = {
        "candidate_count": scored,
        "best_profile_adjusted_action": best_action,
        "best_profile_adjusted_score": round(best_score, 2) if scored else None,
        "precedence": profile_context.get("precedence"),
        "rule": "Profile adjusts candidate ranking as context; live feed remains current-state authority and policy remains execution authority.",
    }
    return scored


def _live_feed_tradeoff_score(proposal: dict[str, Any]) -> dict[str, Any]:
    department = str(proposal.get("department") or "")
    policy = proposal.get("policy_judge", {}) if isinstance(proposal.get("policy_judge"), dict) else {}
    policy_status = str(policy.get("status") or "")
    confidence = float(proposal.get("confidence") or 0)
    safety_weight = {
        "safety": 5,
        "security": 5,
        "maintenance": 4,
        "operations": 4,
        "guest_experience": 3,
        "hr_labor": 3,
        "food_retail": 2,
        "marketing": 2,
        "finance": 1,
        "compliance": 5,
        "qa_judge": 4,
        "executive": 5,
    }.get(department, 3)
    guest_value = {
        "guest_experience": 5,
        "operations": 4,
        "food_retail": 3,
        "marketing": 3,
        "hr_labor": 2,
        "finance": 2,
    }.get(department, 1)
    revenue_value = {"finance": 5, "food_retail": 4, "marketing": 4, "operations": 2}.get(department, 1)
    labor_value = {"hr_labor": 5, "operations": 3, "food_retail": 2, "safety": 2, "security": 2}.get(department, 1)
    blocked = policy_status not in {"passed", "approved_with_exclusions", "trace_only"}
    decision = (proposal.get("action_disposition", {}) if isinstance(proposal.get("action_disposition"), dict) else {}).get("decision")
    profile_context = proposal.get("park_profile_context", {}) if isinstance(proposal.get("park_profile_context"), dict) else {}
    profile_constraints = profile_context.get("profile_constraints", []) if isinstance(profile_context.get("profile_constraints"), list) else []
    reasoning = proposal.get("department_reasoning", {}) if isinstance(proposal.get("department_reasoning"), dict) else {}
    profile_counterfactual = reasoning.get("profile_counterfactual_summary", {}) if isinstance(reasoning.get("profile_counterfactual_summary"), dict) else {}
    ride_down_board = reasoning.get("ride_down_recovery_board", {}) if isinstance(reasoning.get("ride_down_recovery_board"), dict) else {}
    evidence_argument = reasoning.get("evidence_argument") or _evidence_argument_from_proposal(proposal)
    disposition = proposal.get("action_disposition", {}) if isinstance(proposal.get("action_disposition"), dict) else {}
    return {
        "agent": proposal.get("agent_id"),
        "department": department,
        "requested_tool": (proposal.get("proposal_envelope", {}) if isinstance(proposal.get("proposal_envelope"), dict) else {}).get("requested_tool") or proposal.get("requested_tool"),
        "policy_status": policy_status,
        "safety_risk_weight": safety_weight,
        "guest_value": guest_value,
        "revenue_value": revenue_value,
        "labor_value": labor_value,
        "confidence": round(confidence, 2),
        "profile_constraint_count": len(profile_constraints),
        "profile_counterfactual_action": profile_counterfactual.get("best_profile_adjusted_action"),
        "profile_counterfactual_score": profile_counterfactual.get("best_profile_adjusted_score"),
        "profile_precedence": profile_context.get("precedence"),
        "ride_down_selected_branch": ride_down_board.get("selected_branch_id"),
        "ride_down_branch_count": ride_down_board.get("branch_count") or len(ride_down_board.get("branches", []) if isinstance(ride_down_board.get("branches"), list) else []),
        "ride_down_explicit_rejections": ride_down_board.get("explicit_rejections", []),
        "evidence_argument": evidence_argument,
        "live_feed_event_ids": disposition.get("live_feed_event_ids") or (proposal.get("live_feed_grounding", {}) if isinstance(proposal.get("live_feed_grounding"), dict) else {}).get("event_ids", []),
        "decision": decision,
        "verdict": "approved_for_controlled_execution" if decision == "execute_controlled_internal" else "trace_or_review_only" if policy_status in {"passed", "approved_with_exclusions", "trace_only"} else "blocked_until_exit_condition",
        "rationale": (
            f"Approved because it is low-risk, bounded, and policy-passed. {evidence_argument}"
            if decision == "execute_controlled_internal"
            else f"Held with an owner and exit condition because policy or safety boundary outranks utility. {evidence_argument}"
            if blocked
            else f"Kept as tradeoff context or trace evidence; not a receiver action. {evidence_argument}"
        ),
    }


def _build_live_feed_negotiation_rounds(proposals: list[dict[str, Any]], conflicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_agent = {str(proposal.get("agent_id")): proposal for proposal in proposals if isinstance(proposal, dict)}
    rounds: list[dict[str, Any]] = [
        {
            "round": 1,
            "name": "local_department_positions",
            "claims": [
                {
                    "agent": proposal.get("agent_id"),
                    "department": proposal.get("department"),
                    "wants": proposal.get("recommendation"),
                    "tool": (proposal.get("proposal_envelope", {}) if isinstance(proposal.get("proposal_envelope"), dict) else {}).get("requested_tool") or proposal.get("requested_tool"),
                    "disposition": (proposal.get("action_disposition", {}) if isinstance(proposal.get("action_disposition"), dict) else {}).get("decision"),
                }
                for proposal in proposals
            ],
        }
    ]
    challenge_rows = []
    for conflict in conflicts:
        agents = conflict.get("agents", []) if isinstance(conflict.get("agents"), list) else []
        challenge_rows.append(
            {
                "conflict": conflict.get("conflict"),
                "challengers": agents,
                "objections": [
                    {
                        "agent": agent,
                        "department": by_agent.get(str(agent), {}).get("department"),
                        "position": by_agent.get(str(agent), {}).get("recommendation"),
                    }
                    for agent in agents
                    if by_agent.get(str(agent))
                ],
                "concession": conflict.get("resolution"),
                "status": conflict.get("status"),
            }
        )
    rounds.append({"round": 2, "name": "cross_department_challenges", "challenges": challenge_rows})
    rounds.append(
        {
            "round": 3,
            "name": "policy_and_eval_judge",
            "decisions": [
                {
                    "agent": proposal.get("agent_id"),
                    "department": proposal.get("department"),
                    "policy_status": (proposal.get("policy_judge", {}) if isinstance(proposal.get("policy_judge"), dict) else {}).get("status"),
                    "policy_reason": (proposal.get("policy_judge", {}) if isinstance(proposal.get("policy_judge"), dict) else {}).get("reason"),
                    "next_owner": (proposal.get("action_disposition", {}) if isinstance(proposal.get("action_disposition"), dict) else {}).get("next_owner"),
                    "exit_condition": (proposal.get("action_disposition", {}) if isinstance(proposal.get("action_disposition"), dict) else {}).get("exit_condition"),
                }
                for proposal in proposals
            ],
        }
    )
    score_rows = [_live_feed_tradeoff_score(proposal) for proposal in proposals]
    rounds.append(
        {
            "round": 4,
            "name": "executive_tradeoff_resolution",
            "tradeoff_matrix": score_rows,
            "selected": [row for row in score_rows if row.get("verdict") == "approved_for_controlled_execution"],
            "rejected_or_held": [row for row in score_rows if row.get("verdict") != "approved_for_controlled_execution"],
        }
    )
    return rounds


def _build_live_feed_native_role_agent_proposals(
    park_state: dict[str, Any],
    route: dict[str, Any],
    operator_constraints: dict[str, Any] | None,
    retrieved_context: dict[str, Any] | None,
    scenario_key: str,
    live_feed_case: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    flow = park_state.get("guestFlow", {}) if isinstance(park_state, dict) else {}
    rides = flow.get("rides", []) if isinstance(flow, dict) else []
    zones = flow.get("zones", []) if isinstance(flow, dict) else []
    staffing = park_state.get("staffing", {}) if isinstance(park_state, dict) else {}
    disrupted_ride = _top_ride(rides)
    crowded_zone = _top_zone(zones)
    food_zone = _top_zone([zone for zone in zones if zone.get("processType") == "food"] or zones)
    open_callouts = int(staffing.get("openCallouts", 0) or 0)
    all_sources = {str(row.get("source")) for row in evidence_rows if row.get("source")}
    context_rows = _live_feed_rows_for_sources(evidence_rows, all_sources, 4)
    ride_rows = _live_feed_rows_for_sources(evidence_rows, {"ride_ops", "guest_flow", "weather"})
    guest_rows = _live_feed_rows_for_sources(evidence_rows, {"guest_flow", "operator_signal", "ride_ops"})
    food_rows = _live_feed_rows_for_sources(evidence_rows, {"food_ops", "guest_flow", "weather"})
    staffing_rows = _live_feed_rows_for_sources(evidence_rows, {"staffing", "ride_ops", "food_ops"})
    safety_rows = _live_feed_rows_for_sources(evidence_rows, {"ride_ops", "guest_flow", "weather", "operator_signal"})
    maintenance_rows = _live_feed_rows_for_sources(evidence_rows, {"ride_ops", "weather"})
    finance_rows = _live_feed_rows_for_sources(evidence_rows, {"ride_ops", "food_ops", "staffing", "guest_flow"})
    marketing_rows = _live_feed_rows_for_sources(evidence_rows, {"guest_flow", "food_ops", "weather", "operator_signal"})
    security_rows = _live_feed_rows_for_sources(evidence_rows, {"guest_flow", "operator_signal", "ride_ops"})
    generated_issue = _generated_issue_from_live_case(live_feed_case)
    issue_specific_proposals = _issue_specific_live_feed_proposals(live_feed_case, evidence_rows)
    proposals = [
        *issue_specific_proposals,
        _live_feed_native_proposal(
            "park_understanding_agent",
            f"Build the live-feed operating picture for {generated_issue.get('kind') or 'current operating issue'} before any department acts",
            {"target": "live_feed", "action": "ground_context", "lead_source": live_feed_case.get("lead_source"), "lead_signal_type": live_feed_case.get("lead_signal_type"), "generated_issue": generated_issue, "expected_outcome": "shared context contains generated issue, live feed event IDs, source confidence, and stale-feed issues"},
            context_rows,
            ["No seeded scenario facts can override current live-feed evidence."],
            0.9,
            "context",
        ),
        _live_feed_native_proposal(
            "ride_ops_agent",
            "Hold or meter the affected ride-flow pressure while directing guests to lower-pressure options",
            {"target": "ride", "action": "recommend_route_change", "ride": disrupted_ride.get("id") or disrupted_ride.get("name"), "expected_outcome": "reduce queue spillback and avoid reopening promises before clearance", "rollback": "cancel routing recommendation if ride_ops and guest_flow feeds normalize"},
            ride_rows,
            ["Ops can recommend routing, but cannot send public guest messages or execute receiver changes."],
            0.9,
            "action",
        ),
        _live_feed_native_proposal(
            "facilities_energy_agent",
            "Open a maintenance work-order review for the ride/capacity signal before any reopen recommendation",
            {"target": "maintenance", "action": "create_work_order", "asset": disrupted_ride.get("id") or disrupted_ride.get("name") or "ride_capacity_signal", "expected_outcome": "inspection owner receives a bounded work-order candidate tied to live feed event IDs", "rollback": "close candidate work order if inspection logs show no asset fault"},
            maintenance_rows,
            ["Maintenance may create work-order candidates; reopening remains blocked until inspection and safety clearance."],
            0.82,
            "constraint",
        ),
        _live_feed_native_proposal(
            "guest_flow_agent",
            "Draft a non-promissory guest message that splits demand across lower-pressure destinations",
            {"target": "guest", "action": "message", "routing": "split_lower_pressure_destinations", "expected_outcome": "guests receive clear routing without private data, compensation promises, or reopen guarantees", "rollback": "withdraw draft if compliance rejects wording or route pressure increases"},
            guest_rows,
            ["Guest Experience can draft messages; Compliance and Executive must approve high-risk public messaging."],
            0.84,
            "tradeoff",
        ),
        _live_feed_native_proposal(
            "food_demand_agent",
            "Watch food court demand created by ride-flow migration and pause constrained promos if pressure rises",
            {"target": "food", "action": "pause_promo_if_constrained", "primary_zone": food_zone.get("id") or food_zone.get("name"), "expected_outcome": "avoid stockout or pickup ETA over-promising while preserving available alternatives", "rollback": "resume promo if POS and queue-near-shop feeds normalize"},
            food_rows,
            ["Food/Retail can pause or request restock; it cannot change crowd routing or promise unavailable inventory."],
            0.81,
            "action",
        ),
        _live_feed_native_proposal(
            "finance_agent",
            "Quantify revenue, refund, labor, and POS exposure before Executive selects tradeoff",
            {"target": "finance", "action": "revenue_impact_report", "expected_outcome": "Executive sees revenue and refund exposure without auto-issuing compensation", "rollback": "void estimate if outage impact or POS feed is superseded"},
            finance_rows,
            ["Finance can recommend and report impact, but cannot auto-commit refunds or override safety."],
            0.8,
            "tradeoff",
        ),
        _live_feed_native_proposal(
            "staffing_agent",
            "Recommend only role-compatible staffing moves that preserve breaks, fatigue limits, and certifications",
            {"target": "staff", "action": "shift_adjustment_recommendation", "role": "crowd_support", "expected_outcome": "staffing pressure is reduced without overtime, fatigue, or certification violations", "rollback": "cancel recommendation if attendance or fatigue feed changes"},
            staffing_rows,
            [f"open_callouts={open_callouts}", "No uncertified moves; protected breaks remain protected."],
            0.79 if open_callouts < 20 else 0.69,
            "constraint",
        ),
        _live_feed_native_proposal(
            "event_creative_agent",
            "Pause or redirect marketing offers away from constrained zones instead of creating new crowd pressure",
            {"target": "marketing", "action": "redirect_offer", "from_zone": crowded_zone.get("id") or crowded_zone.get("name"), "to_zone": "lower_pressure_zone", "expected_outcome": "demand generation avoids the constrained ride/food/crowd area", "rollback": "restore campaign when guest_flow and food_ops pressure return to normal"},
            marketing_rows,
            ["Marketing can read crowd data and redirect offers, but cannot alter guest routing directly."],
            0.78,
            "tradeoff",
        ),
        _live_feed_native_proposal(
            "security_agent",
            "Recommend zone-control monitoring for density, access, or lost-child escalation risk",
            {"target": "security", "action": "zone_control", "zone": crowded_zone.get("id") or crowded_zone.get("name"), "expected_outcome": "security lead has a clear zone-control recommendation without public messaging or equipment control", "rollback": "stand down if density and operator_signal feeds normalize"},
            security_rows,
            ["Security can recommend zone control or escalation; public messaging and staffing changes remain with other departments."],
            0.76,
            "gate",
        ),
        _live_feed_native_proposal(
            "safety_policy_agent",
            "Gate all department proposals against safety, weather, crowd, privacy, and labor constraints",
            {"target": "safety", "action": "require_human_approval", "requires_human_review": True, "expected_outcome": "unsafe or sensitive proposals are blocked before Tool Executor can act", "rollback": "release approval hold only when policy findings are cleared"},
            safety_rows,
            ["Safety can block or require approval but cannot execute receiver actions."],
            0.93,
            "gate",
        ),
        _live_feed_native_proposal(
            "logic_audit_agent",
            "Generate a compliance note that names blocked scopes, required approvals, and trace evidence",
            {"target": "compliance", "action": "generate_compliance_note", "expected_outcome": "Compliance records policy refs and approval requirements for the executive decision", "rollback": "supersede note if live feed evidence changes materially"},
            context_rows,
            ["Compliance can block, require approval, or write notes; it cannot execute operations changes."],
            0.88,
            "gate",
        ),
        _live_feed_native_proposal(
            "gcp_eval_judge_agent",
            "Score trace quality, evidence grounding, tool boundaries, and failure modes for this live-feed case",
            {"target": "qa_judge", "action": "score_decision", "expected_outcome": "Eval Judge returns a trace-quality score and regression-test recommendation if grounding is weak", "rollback": "flag failure and create regression test if any proposal lacks live event evidence"},
            context_rows,
            ["QA Judge can score and flag failures; it cannot dispatch or alter recommendations."],
            0.9,
            "gate",
        ),
    ]
    passed_departments = [
        proposal.get("department")
        for proposal in proposals
        if (proposal.get("policy_judge", {}) if isinstance(proposal.get("policy_judge"), dict) else {}).get("status") in {"passed", "approved_with_exclusions"}
    ]
    held_departments = [
        proposal.get("department")
        for proposal in proposals
        if (proposal.get("policy_judge", {}) if isinstance(proposal.get("policy_judge"), dict) else {}).get("status") not in {"passed", "approved_with_exclusions"}
    ]
    proposals.append(
        _live_feed_native_proposal(
            "decision_bridge_agent",
            "Approve only low-risk passed proposals and hold safety, security, guest-message, and reopen-sensitive actions",
            {"target": "executive", "action": "choose_tradeoff", "approved_departments": passed_departments, "held_departments": held_departments, "expected_outcome": "Tool Executor receives only approved low-risk envelopes; held actions require named approval", "rollback": "withdraw executive selection if policy or live feed evidence changes"},
            context_rows,
            ["Executive must compare safety, guest impact, finance, labor, operations, and compliance before Tool Executor acts."],
            0.9,
            "bridge",
        )
    )
    park_profile = _park_profile_from_context(retrieved_context)
    profile_summary = _attach_park_profile_context(proposals, park_profile)
    active_roles = list(dict.fromkeys(item["agent_id"] for item in proposals))
    active_departments = active_departments_for_agents(active_roles)
    envelope_summary = _proposal_envelope_summary(proposals)
    depth_summary = _live_feed_deep_reasoning_summary(proposals)
    conflicts = [
        *_issue_specific_live_feed_conflicts(issue_specific_proposals, generated_issue),
        {"conflict": "Operations wants demand relief, but Guest Experience and Marketing could accidentally move too much demand into a constrained zone.", "agents": ["ride_ops_agent", "guest_flow_agent", "event_creative_agent", "decision_bridge_agent"], "resolution": "Use split routing and redirect/pause offers; public messaging remains compliance-gated.", "status": "resolved"},
        {"conflict": "Finance may prefer revenue preservation, while Safety/Security hold sensitive actions for approval.", "agents": ["finance_agent", "safety_policy_agent", "security_agent", "decision_bridge_agent"], "resolution": "Executive keeps impact reporting active but holds safety/security actions until approval.", "status": "resolved"},
        {"conflict": "Labor support is useful, but staffing moves can violate role, fatigue, overtime, or break rules.", "agents": ["staffing_agent", "logic_audit_agent", "decision_bridge_agent"], "resolution": "Only recommendation-only, role-compatible staffing moves can advance to Tool Executor preview.", "status": "watch" if open_callouts >= 20 else "resolved"},
    ]
    negotiation_rounds = _build_live_feed_negotiation_rounds(proposals, conflicts)
    tradeoff_matrix = negotiation_rounds[-1]["tradeoff_matrix"] if negotiation_rounds else []
    negotiation_turns = [
        {"turn": 1, "agent": "park_understanding_agent", "decision": "accepted", "reason": "Grounding is based on persisted live feed rows."},
        {"turn": 2, "agent": "ride_ops_agent", "decision": "held_for_executive", "reason": "High-risk route changes affect guest flow and safety."},
        {"turn": 3, "agent": "guest_flow_agent", "decision": "held_for_compliance", "reason": "Guest-facing messages need privacy and promise review."},
        {"turn": 4, "agent": "staffing_agent", "decision": "accepted_for_executor_preview", "reason": "Recommendation-only labor action passed role/break/overtime limits."},
        {"turn": 5, "agent": "food_demand_agent", "decision": "accepted_for_executor_preview", "reason": "Food action is a low-risk inventory/promo hold, not guest routing."},
        {"turn": 6, "agent": "event_creative_agent", "decision": "accepted_for_executor_preview", "reason": "Marketing action redirects demand away from constrained zones only."},
        {"turn": 7, "agent": "security_agent", "decision": "held_for_human_approval", "reason": "Zone-control recommendations are security-sensitive."},
        {"turn": 8, "agent": "logic_audit_agent", "decision": "accepted", "reason": "Compliance note names policy constraints and approval requirements."},
        {"turn": 9, "agent": "gcp_eval_judge_agent", "decision": "accepted", "reason": "Trace/eval judge owns score and failure flag writes."},
        {"turn": 10, "agent": "decision_bridge_agent", "decision": "approved_with_exclusions", "reason": "Executive approves only passed low-risk envelopes and keeps blocked/held items out of execution."},
    ]
    event_ids = [row.get("event_id") for row in evidence_rows if row.get("event_id")]
    return {
        "mode": "live_feed_native_department_proposals",
        "route": route or {"route": "live_feed_department_cooperation", "scenario_key": scenario_key},
        "scenario_key": scenario_key,
        "orchestration_source": "live_feed",
        "generated_from": "live_feed_case",
        "generated_issue": generated_issue,
        "issue_specific_proposal_count": len(issue_specific_proposals),
        "execution_model": "department_agents_read_widely_write_narrowly_policy_judge_then_tool_executor",
        "active_roles": active_roles,
        "active_departments": active_departments,
        "active_department_count": len(active_departments),
        "proposal_count": len(proposals),
        "department_reasoning_contract": "Each department proposal diagnoses local state, compares candidate actions, forecasts the selected outcome, names failure modes, and traces carry-forward learning material before Tool Executor receives anything.",
        "park_profile_context_contract": "Department agents may use venue-approved profile facts, path/capacity priors, source integrity, and profile policy as context; live feed overrides profile for current state and policy gates override both.",
        **profile_summary,
        **depth_summary,
        "proposal_envelope_summary": envelope_summary,
        "live_feed_evidence_count": len(evidence_rows),
        "live_feed_event_ids": event_ids[:12],
        "live_feed_grounded_proposal_count": len(proposals),
        "proposals": proposals,
        "conflicts": conflicts,
        "negotiation_rounds": negotiation_rounds,
        "tradeoff_matrix": tradeoff_matrix,
        "negotiation_turns": negotiation_turns,
        "executive_tradeoff": {
            "decision": "approved_with_exclusions",
            "approved_departments": passed_departments,
            "held_departments": held_departments,
            "tradeoff_matrix": tradeoff_matrix,
            "reason": "Executive compared safety risk, guest value, revenue value, labor impact, confidence, policy status, and disposition. Low-risk food, labor, and marketing actions proceed; operations, maintenance, guest-message, safety, and security remain held with owners and exit conditions.",
        },
        "mediator_summary": (
            "Live-feed-native department agents generated proposals directly from persisted feed event IDs. "
            "Compliance, QA Judge, and Executive made explicit pass/hold decisions before Tool Executor receives any envelope."
        ),
    }


def build_role_agent_proposals(
    park_state: dict[str, Any],
    route: dict[str, Any] | None = None,
    operator_constraints: dict[str, Any] | None = None,
    retrieved_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    route = route or {}
    flow = park_state.get("guestFlow", {}) if isinstance(park_state, dict) else {}
    scenario_key = str(route.get("scenario_key") or flow.get("activeScenario", {}).get("key") or "ride_down")
    live_feed_case = retrieved_context.get("live_feed_case") if isinstance(retrieved_context, dict) else None
    live_feed_rows = _live_feed_proposal_evidence_rows(live_feed_case)
    orchestration_source = route.get("orchestration_source")
    if not orchestration_source and isinstance(retrieved_context, dict):
        orchestration_source = retrieved_context.get("orchestration_source")
    if live_feed_rows and str(orchestration_source or "").lower() == "live_feed":
        return _build_live_feed_native_role_agent_proposals(
            park_state,
            route,
            operator_constraints,
            retrieved_context,
            scenario_key,
            live_feed_case if isinstance(live_feed_case, dict) else {},
            live_feed_rows,
        )
    rides = flow.get("rides", []) if isinstance(flow, dict) else []
    zones = flow.get("zones", []) if isinstance(flow, dict) else []
    paths = flow.get("paths", []) if isinstance(flow, dict) else []
    weather = park_state.get("weather", {}) if isinstance(park_state, dict) else {}
    staffing = park_state.get("staffing", {}) if isinstance(park_state, dict) else {}
    energy = park_state.get("energy", {}) if isinstance(park_state, dict) else {}
    disrupted_ride = _top_ride(rides)
    crowded_zone = _top_zone(zones)
    congested_path = _top_path(paths)
    food_zone = _top_zone([zone for zone in zones if zone.get("processType") == "food"] or zones)
    open_callouts = int(staffing.get("openCallouts", 0) or 0)
    storm_risk = int(weather.get("stormRisk", 0) or 0)
    grid_load = int(energy.get("gridLoadPercent", 0) or 0)
    constraint_rules = (operator_constraints or {}).get("decision_rules", []) if isinstance(operator_constraints, dict) else []
    proposals: list[dict[str, Any]] = [
        _role_proposal(
            "park_understanding_agent",
            "Build operating picture before optimization",
            {"target": "scenario", "action": "ground_context", "scenario_key": scenario_key},
            [
                f"scenario={scenario_key}",
                f"memory_items={_memory_count(retrieved_context)}",
                f"operator_rules={len(constraint_rules)}",
            ],
            ["Use live state and retrieved memory as inputs; do not invent unavailable capacity."],
            0.88 if _memory_count(retrieved_context) else 0.78,
            "context",
        )
    ]
    if scenario_key == "marketing_promo_conflict":
        proposals.extend(
            [
                _role_proposal(
                    "event_creative_agent",
                    "Push the offer, but redirect it away from the overcrowded indoor food court",
                    {"target": "marketing", "action": "redirect_offer", "from_zone": "zone_b", "to_zone": "zone_c", "offer": "indoor_food_discount"},
                    [
                        "campaign=indoor_food_discount",
                        f"crowded_zone={crowded_zone.get('name', 'Zone B')} {crowded_zone.get('density', 0)}%",
                        f"weather={weather.get('condition', 'active')}",
                    ],
                    ["Marketing can read crowd pressure but cannot change guest routing."],
                    0.82,
                    "tradeoff",
                ),
                _role_proposal(
                    "ride_ops_agent",
                    "Do not increase traffic into the already constrained indoor court",
                    {"target": "traffic", "action": "recommend_route_change", "blocked_zone": "zone_b", "preferred_zone": "zone_c"},
                    [
                        f"zone_b_density={crowded_zone.get('density', 0)}%",
                        f"path_pressure={congested_path.get('congestionLevel', 0)}%",
                        "queue_migration=ride_outage_to_food",
                    ],
                    ["Ops may recommend routing changes, but Tool Executor must perform real receiver actions."],
                    0.88,
                    "constraint",
                ),
                _role_proposal(
                    "safety_policy_agent",
                    "Block any promotion that increases Zone B crowd density",
                    {"target": "safety", "action": "require_human_approval", "blocked_zone": "zone_b", "reason": "crowd_density"},
                    [
                        f"zone_b_density={crowded_zone.get('density', 0)}%",
                        "policy=PARK-SAFE crowd hazard",
                        "promotion_increases_traffic=true",
                    ],
                    ["Safety can block unsafe demand creation even when revenue impact is positive."],
                    0.94,
                    "gate",
                ),
                _role_proposal(
                    "finance_agent",
                    "Keep the revenue upside by moving the discount to Zone C instead of cancelling it",
                    {"target": "finance", "action": "revenue_impact_report", "blocked_offer": "zone_b_discount", "replacement_offer": "zone_c_discount"},
                    [
                        "discount_revenue_upside=positive",
                        "refund_exposure=lower_if_crowding_avoided",
                        "zone_c_capacity=available",
                    ],
                    ["Revenue upside does not override safety or crowd-flow constraints."],
                    0.8,
                    "tradeoff",
                ),
                _role_proposal(
                    "decision_bridge_agent",
                    "Reject the Zone B promotion and choose the Zone C redirected offer",
                    {"target": "scenario", "action": "choose_tradeoff", "decision": "reject_zone_b_redirect_to_zone_c"},
                    [
                        "marketing_offer=redirectable",
                        "ops_zone_b_block=active",
                        "safety_zone_b_block=active",
                        "finance_zone_c_upside=positive",
                    ],
                    ["Executive tradeoff chooses the safe alternative; Tool Executor runs only the approved Zone C action."],
                    0.91,
                    "bridge",
                ),
            ]
        )
    elif scenario_key == "food_spike":
        proposals.extend(
            [
                _role_proposal(
                    "food_demand_agent",
                    "Pause constrained intake and split demand to available food capacity",
                    {"target": "food", "action": "redirect_food_demand", "primary_zone": food_zone.get("id") or food_zone.get("name")},
                    [
                        f"food_zone={food_zone.get('name', 'unknown')}",
                        f"food_wait={food_zone.get('waitMins', 0)}m",
                        f"density={food_zone.get('density', 0)}%",
                    ],
                    ["Keep existing pickup ETAs visible; do not promote unavailable items."],
                    0.88,
                    "action",
                ),
                _role_proposal(
                    "guest_flow_agent",
                    "Use a mixed nudge instead of routing every guest to one replacement venue",
                    {"target": "guest", "action": "message", "routing": "split_alternates"},
                    [
                        f"crowded_zone={crowded_zone.get('name', 'unknown')} {crowded_zone.get('density', 0)}%",
                        f"path_pressure={congested_path.get('congestionLevel', 0)}%",
                    ],
                    ["Protect alternate destinations from becoming the next bottleneck."],
                    0.84,
                    "tradeoff",
                ),
                _role_proposal(
                    "staffing_agent",
                    "Move role-compatible food support only if break and certification constraints allow it",
                    {"target": "staff", "action": "redeploy", "role": "food_service"},
                    [f"scheduled={staffing.get('scheduled', 0)}", f"checked_in={staffing.get('checkedIn', 0)}", f"callouts={open_callouts}"],
                    ["No uncertified moves; protected breaks remain protected."],
                    0.8 if open_callouts < 20 else 0.69,
                    "constraint",
                ),
            ]
        )
    elif scenario_key == "staff_shortage":
        proposals.extend(
            [
                _role_proposal(
                    "staffing_agent",
                    "Cover the highest-pressure area with cross-trained staff and keep fatigue limits visible",
                    {"target": "staff", "action": "redeploy", "scope": "cross_trained_only"},
                    [f"scheduled={staffing.get('scheduled', 0)}", f"checked_in={staffing.get('checkedIn', 0)}", f"callouts={open_callouts}"],
                    ["Do not delay protected breaks; do not move workers into roles they are not cleared for."],
                    0.86,
                    "action",
                ),
                _role_proposal(
                    "guest_flow_agent",
                    "Reduce demand at understaffed locations before asking for more labor",
                    {"target": "guest", "action": "message", "routing": "soft_demand_shift"},
                    [f"crowded_zone={crowded_zone.get('name', 'unknown')} {crowded_zone.get('density', 0)}%"],
                    ["Prefer soft nudges over hard reroutes when staff coverage is thin."],
                    0.81,
                    "tradeoff",
                ),
            ]
        )
    elif scenario_key == "storm_response":
        proposals.extend(
            [
                _role_proposal(
                    "facilities_energy_agent",
                    "Protect shelter-zone comfort and shed only noncritical loads",
                    {"target": "energy", "action": "protect_hvac", "zones": ["indoorHub", "coveredPlaza"]},
                    [f"storm_risk={storm_risk}%", f"grid_load={grid_load}%", f"heat_index={weather.get('heatIndexF', 0)}F"],
                    ["Do not reduce HVAC comfort where guests are sheltering."],
                    0.87,
                    "constraint",
                ),
                _role_proposal(
                    "guest_flow_agent",
                    "Split shelter routing across covered capacity instead of one indoor destination",
                    {"target": "guest", "action": "message", "routing": "shelter_split"},
                    [
                        f"crowded_zone={crowded_zone.get('name', 'unknown')} {crowded_zone.get('density', 0)}%",
                        f"path_pressure={congested_path.get('congestionLevel', 0)}%",
                    ],
                    ["Keep emergency and accessible routes clear."],
                    0.84,
                    "action",
                ),
                _role_proposal(
                    "staffing_agent",
                    "Stage supervisors at shelter edges rather than pulling critical ride operators first",
                    {"target": "staff", "action": "redeploy", "role": "supervisor"},
                    [f"callouts={open_callouts}", f"checked_in={staffing.get('checkedIn', 0)}"],
                    ["Avoid removing minimum staffing from active safety posts."],
                    0.78,
                    "constraint",
                ),
            ]
        )
    else:
        proposals.extend(
            [
                _role_proposal(
                    "ride_ops_agent",
                    "Hold affected queue intake and avoid any promise of reopening before clearance",
                    {"target": "ride", "action": "hold_and_reroute", "ride": disrupted_ride.get("id") or disrupted_ride.get("name")},
                    [
                        f"ride={disrupted_ride.get('name', 'unknown')}",
                        f"status={disrupted_ride.get('status', 'normal')}",
                        f"wait={disrupted_ride.get('waitMins', 0)}m",
                    ],
                    ["Maintenance and safety clearance override throughput pressure."],
                    0.9,
                    "action",
                ),
                _role_proposal(
                    "guest_flow_agent",
                    "Distribute displaced guests across multiple lower-pressure options",
                    {"target": "guest", "action": "message", "routing": "multi_destination"},
                    [
                        f"crowded_zone={crowded_zone.get('name', 'unknown')} {crowded_zone.get('density', 0)}%",
                        f"path_pressure={congested_path.get('congestionLevel', 0)}%",
                    ],
                    ["Do not push all displaced guests into food or one nearby ride."],
                    0.85,
                    "tradeoff",
                ),
                _role_proposal(
                    "staffing_agent",
                    "Assign crowd-control support only where role-compatible staff are available",
                    {"target": "staff", "action": "redeploy", "role": "crowd_control"},
                    [f"scheduled={staffing.get('scheduled', 0)}", f"checked_in={staffing.get('checkedIn', 0)}", f"callouts={open_callouts}"],
                    ["Preserve break protection and ride-operator minimums."],
                    0.78 if open_callouts < 20 else 0.68,
                    "constraint",
                ),
            ]
        )
    proposals.extend(
        [
            _role_proposal(
                "safety_policy_agent",
                "Gate specialist proposals against safety, labor, privacy, and operator-approval rules",
                {"target": "scenario", "action": "policy_gate", "requires_human_review": bool(route.get("requires_human_review"))},
                [
                    f"urgency={route.get('urgency', 'normal')}",
                    f"requires_human_review={bool(route.get('requires_human_review'))}",
                    f"operator_rules={len(constraint_rules)}",
                ],
                ["Blocked scope remains blocked even when the optimizer prefers speed."],
                0.93,
                "gate",
            ),
            _role_proposal(
                "decision_bridge_agent",
                "Resolve role conflicts into one policy-gated plan for the central optimizer and action bus",
                {"target": "scenario", "action": "synthesize_role_proposals", "proposal_count": len(proposals) + 1},
                [
                    f"active_specialists={len({item['agent_id'] for item in proposals})}",
                    f"scenario={scenario_key}",
                    f"route={route.get('route', 'scenario_run')}",
                ],
                ["Specialists recommend; the optimizer and policy gate still decide what executes."],
                0.87,
                "bridge",
            ),
        ]
    )
    conflicts = _role_proposal_conflicts(proposals, scenario_key, open_callouts, crowded_zone, route)
    active_roles = list(dict.fromkeys(item["agent_id"] for item in proposals))
    active_departments = active_departments_for_agents(active_roles)
    envelope_summary = _proposal_envelope_summary(proposals)
    return {
        "mode": "hybrid_role_proposals",
        "route": route or {"route": "scenario_run", "scenario_key": scenario_key},
        "scenario_key": scenario_key,
        "execution_model": "specialist_role_agents_propose_central_optimizer_disposes",
        "active_roles": active_roles,
        "active_departments": active_departments,
        "active_department_count": len(active_departments),
        "proposal_count": len(proposals),
        "proposal_envelope_summary": envelope_summary,
        "proposals": proposals,
        "conflicts": conflicts,
        "mediator_summary": (
            "Role agents collaborate by emitting bounded, inspectable proposals from their owned slice of the park state. "
            "Decision Bridge resolves conflicts, then the optimizer and policy gate choose the executable action."
        ),
    }


def build_orchestration_run(
    findings: list[dict[str, Any]],
    mode: str,
    response_metrics: dict[str, Any] | None = None,
    event_revision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    finding_ids = {item.get("agent_id") for item in findings if isinstance(item, dict)}
    active_groups = []
    for group in AGENT_TOPOLOGY["agent_groups"]:
        group_agents = group.get("agents", [])
        active_agents = [agent_id for agent_id in group_agents if agent_id in finding_ids]
        mode_match = mode in group.get("modes", [])
        if group["id"] == "post_event" and (response_metrics or event_revision):
            mode_match = True
        active_groups.append(
            {
                **group,
                "active_agents": active_agents,
                "active_agent_count": len(active_agents),
                "status": "active" if mode_match or active_agents else "ready",
            }
        )
    active_handoffs = [
        {
            **handoff,
            "status": "observed" if handoff["from"] in finding_ids or handoff["to"] in finding_ids else "available",
        }
        for handoff in AGENT_TOPOLOGY["handoffs"]
    ]
    phases = []
    for phase in AGENT_TOPOLOGY["phases"]:
        phase_agents = phase.get("agents", [])
        active_agents = [agent_id for agent_id in phase_agents if agent_id in finding_ids]
        phases.append(
            {
                **phase,
                "active_agents": active_agents,
                "status": "active" if active_agents else "ready",
                "evidence_count": len(active_agents),
            }
        )
    conflicts = _orchestration_conflicts(findings, response_metrics or {}, bool(event_revision))
    lifecycle_artifact = _build_lifecycle_artifact(mode, findings, response_metrics or {}, event_revision, active_groups)
    active_departments = active_departments_for_agents({str(agent_id) for agent_id in finding_ids if isinstance(agent_id, str)})
    return {
        "mode": mode,
        "pattern": AGENT_TOPOLOGY["pattern"],
        "lifecycle_pattern": AGENT_TOPOLOGY["lifecycle_pattern"],
        "supervisor": "decision_bridge_agent",
        "department_system": {
            "loop": [step.title() for step in DEPARTMENT_AGENT_LOOP],
            "active_departments": active_departments,
            "active_department_count": len(active_departments),
            "conflict_resolver": "decision_bridge_agent",
            "policy_judge": "safety_policy_agent",
            "eval_judge": "gcp_eval_judge_agent",
            "tool_contract_required_fields": list(DEPARTMENT_TOOL_CONTRACT_FIELDS),
        },
        "agent_groups": active_groups,
        "lifecycle_artifact": lifecycle_artifact,
        "phase_count": len(phases),
        "active_agent_count": len(finding_ids),
        "phases": phases,
        "handoffs": active_handoffs,
        "conflicts": conflicts,
        "gates": [
            {
                "gate": "Safety and policy",
                "owner": "safety_policy_agent",
                "status": "review" if any(item.get("urgency") == "risk" for item in findings) else "clear",
                "rule": "Safety, emergency access, labor protection, and privacy can override optimization.",
            },
            {
                "gate": "Observed response",
                "owner": "gcp_eval_judge_agent",
                "status": "revise" if (response_metrics or {}).get("score", 100) < 75 else "learn",
                "rule": "Take rate, sentiment, and follow-through decide whether the next plan changes.",
            },
            {
                "gate": "Plan versioning",
                "owner": "park_understanding_agent",
                "status": "v2_stored" if event_revision else "waiting_for_outcome",
                "rule": "MongoDB stores plan versions, decisions, evals, dispatches, and outcome events.",
            },
        ],
        "logic_graph": _build_logic_graph_run(finding_ids, response_metrics or {}, bool(event_revision)),
        "eval_dimensions": AGENT_TOPOLOGY["eval_dimensions"],
    }


def _build_lifecycle_artifact(
    mode: str,
    findings: list[dict[str, Any]],
    response_metrics: dict[str, Any],
    event_revision: dict[str, Any] | None,
    active_groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    finding_ids = {item.get("agent_id") for item in findings if isinstance(item, dict)}
    by_group = {group.get("id"): group for group in active_groups}
    has_pre_event = mode in {"event_planning", "proactive"} or any(
        agent_id in finding_ids for agent_id in {"event_setup_agent", "traffic_flow_agent", "placement_agent"}
    )
    has_during_event = mode == "reactive" or any(
        agent_id in finding_ids for agent_id in {"ride_ops_agent", "food_demand_agent", "guest_flow_agent", "staffing_agent"}
    )
    has_outcome = bool(response_metrics)
    needs_revision = bool(event_revision) or response_metrics.get("score", 100) < 75 or response_metrics.get("takeRate", 1) < 0.45
    response_summary = (
        f"Take rate {round(float(response_metrics.get('takeRate', 0) or 0) * 100)}%, "
        f"follow-through {round(float(response_metrics.get('reactiveFollowThroughRate', 0) or 0) * 100)}%, "
        f"response score {response_metrics.get('score', '--')}."
        if has_outcome
        else "No response telemetry measured yet."
    )
    revision_id = (event_revision or {}).get("event_plan_id") or (event_revision or {}).get("decision_id") or "next plan"
    rows = deepcopy(AGENT_TOPOLOGY["lifecycle_artifact"])
    updates = {
        "pre_event": {
            "status": "complete" if has_pre_event else by_group.get("pre_event", {}).get("status", "ready"),
            "measured_result": (
                "Forecast and prevention work are active inputs to the current run."
                if has_pre_event
                else "Ready to forecast risk before the next event window."
            ),
        },
        "during_event": {
            "status": "complete" if has_during_event and has_outcome else "active" if has_during_event else by_group.get("during_event", {}).get("status", "ready"),
            "measured_result": response_summary if has_during_event else "Ready to supervise live signals when the event starts.",
        },
        "post_event": {
            "status": "revise" if needs_revision else "complete" if has_outcome else by_group.get("post_event", {}).get("status", "ready"),
            "measured_result": (
                f"Outcome requires revision; stored or proposed {revision_id}."
                if needs_revision
                else response_summary if has_outcome
                else "Ready to judge outcomes and write learning memory."
            ),
        },
    }
    for row in rows:
        row.update(updates.get(row["group_id"], {}))
        row["active_agent_count"] = by_group.get(row["group_id"], {}).get("active_agent_count", 0)
    return rows


def _build_logic_graph_run(
    finding_ids: set[str],
    response_metrics: dict[str, Any],
    revision_created: bool,
) -> dict[str, Any]:
    graph = deepcopy(AGENT_TOPOLOGY["logic_graph"])
    has_outcome = bool(response_metrics)
    needs_revision = revision_created or response_metrics.get("score", 100) < 75 or response_metrics.get("takeRate", 1) < 0.45
    for node in graph["decision_layers"]:
        agents = node.get("agents", [])
        evidence_count = len([agent_id for agent_id in agents if agent_id in finding_ids])
        status = "observed" if evidence_count else "ready"
        if node["id"] == "logic_audit":
            status = "updating" if "logic_audit_agent" in finding_ids or needs_revision else "ready"
        elif node["id"] == "post_decision_result":
            if needs_revision:
                status = "revise"
            elif has_outcome:
                status = "measured"
            else:
                status = "pending"
        node["status"] = status
        node["evidence_count"] = evidence_count
    graph["audit_agent"]["status"] = "updating" if needs_revision else "watching"
    graph["audit_agent"]["last_update"] = "revision_required" if needs_revision else "no_blocking_gap"
    return graph


def _orchestration_conflicts(
    findings: list[dict[str, Any]],
    response_metrics: dict[str, Any],
    revision_created: bool,
) -> list[dict[str, Any]]:
    by_agent = {item.get("agent_id"): item for item in findings if isinstance(item, dict)}
    conflicts: list[dict[str, Any]] = []
    if "guest_flow_agent" in by_agent and "staffing_agent" in by_agent:
        conflicts.append(
            {
                "conflict": "Guest diversion needs more crowd-control staff, but labor is constrained.",
                "agents": ["guest_flow_agent", "staffing_agent", "decision_bridge_agent"],
                "resolution": "Use soft guest nudges and targeted worker notifications instead of a broad hard reroute.",
                "status": "resolved",
            }
        )
    if "facilities_energy_agent" in by_agent:
        conflicts.append(
            {
                "conflict": "Energy cost reduction competes with indoor comfort and shelter demand.",
                "agents": ["facilities_energy_agent", "guest_flow_agent", "safety_policy_agent"],
                "resolution": "Protect HVAC in shelter zones and shed only noncritical lighting or loads.",
                "status": "resolved",
            }
        )
    if "placement_agent" in by_agent or "traffic_flow_agent" in by_agent:
        conflicts.append(
            {
                "conflict": "The visually attractive scare-zone corridor can become a static queue bottleneck.",
                "agents": ["placement_agent", "traffic_flow_agent", "event_creative_agent"],
                "resolution": "Mark congested corridors as flow-through only and move queues, food, and merchandise to wider zones.",
                "status": "resolved" if revision_created else "watch",
            }
        )
    if response_metrics.get("takeRate", 1) < 0.45 or response_metrics.get("score", 100) < 75:
        conflicts.append(
            {
                "conflict": "Policy-compliant action is not valuable unless guests and workers actually respond.",
                "agents": ["gcp_eval_judge_agent", "decision_bridge_agent", "guest_flow_agent"],
                "resolution": "Use take-rate and follow-through telemetry as the revision trigger, not just ideal policy scores.",
                "status": "learning",
            }
        )
    return conflicts[:4]


def build_reactive_agent_findings(
    park_state: dict[str, Any],
    scenario_key: str,
    retrieved_context: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
    optimization: dict[str, Any] | None = None,
    eval_result: dict[str, Any] | None = None,
    delivery: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    flow = park_state.get("guestFlow", {}) if isinstance(park_state, dict) else {}
    rides = flow.get("rides", []) if isinstance(flow, dict) else []
    zones = flow.get("zones", []) if isinstance(flow, dict) else []
    paths = flow.get("paths", []) if isinstance(flow, dict) else []
    weather = park_state.get("weather", {}) if isinstance(park_state, dict) else {}
    energy = park_state.get("energy", {}) if isinstance(park_state, dict) else {}
    staffing = park_state.get("staffing", {}) if isinstance(park_state, dict) else {}
    retrieved = (retrieved_context or {}).get("retrieved", {}) if isinstance(retrieved_context, dict) else {}
    selected = (optimization or {}).get("selected_plan", {}).get("selected_action") or (plan or {}).get("selected_action", {})
    response = (delivery or {}).get("response", {}) if isinstance(delivery, dict) else {}
    evals = {item.get("label"): item.get("score") for item in (eval_result or {}).get("evals", []) if isinstance(item, dict)}

    disrupted_ride = _top_ride(rides)
    crowded_zone = _top_zone(zones)
    congested_path = _top_path(paths)
    food_zone = _top_zone([zone for zone in zones if zone.get("processType") == "food"] or zones)
    open_callouts = int(staffing.get("openCallouts", 0) or 0)
    grid_load = int(energy.get("gridLoadPercent", 0) or 0)
    storm_risk = int(weather.get("stormRisk", 0) or 0)

    findings = [
        _finding(
            "park_understanding_agent",
            "reactive",
            [
                f"scenario={scenario_key}",
                f"playbooks={len(retrieved.get('playbooks', []) or [])}",
                f"incidents={len(retrieved.get('incidents', []) or [])}",
            ],
            f"Live state shows {disrupted_ride.get('name', 'primary ride')} pressure, {crowded_zone.get('name', 'primary zone')} density at {crowded_zone.get('density', 0)}%, and {open_callouts} open staff callouts.",
            "Use current park state plus MongoDB playbooks before selecting an action.",
            _urgency(max(int(crowded_zone.get("density", 0) or 0), int(disrupted_ride.get("waitMins", 0) or 0))),
            0.9 if retrieved.get("playbooks") else 0.78,
        ),
        _finding(
            "ride_ops_agent",
            "reactive",
            [
                f"ride={disrupted_ride.get('name', 'unknown')}",
                f"status={disrupted_ride.get('status', 'normal')}",
                f"wait={disrupted_ride.get('waitMins', 0)}m",
            ],
            "Ride pressure requires queue-intake control and capacity-aware alternatives; maintenance or safety status remains non-negotiable.",
            "Pause or taper affected queue intake and avoid any action that implies reopening before clearance.",
            "risk" if disrupted_ride.get("status") == "down" else "watch",
            0.91,
        ),
        _finding(
            "guest_flow_agent",
            "reactive",
            [
                f"zone={crowded_zone.get('name', 'unknown')} {crowded_zone.get('density', 0)}%",
                f"path={congested_path.get('fromName', congested_path.get('from', 'path'))}->{congested_path.get('toName', congested_path.get('to', 'zone'))} {congested_path.get('congestionLevel', 0)}%",
                f"take_rate={response.get('takeRate', 0)}",
            ],
            "Guest routing has to split demand across multiple destinations because one hard redirect can create a new bottleneck.",
            "Use a mixed guest-app nudge with hold share, nearby alternatives, and response telemetry.",
            _urgency(max(int(crowded_zone.get("density", 0) or 0), int(congested_path.get("congestionLevel", 0) or 0))),
            0.86,
        ),
        _finding(
            "staffing_agent",
            "reactive",
            [f"scheduled={staffing.get('scheduled', 0)}", f"checked_in={staffing.get('checkedIn', 0)}", f"callouts={open_callouts}"],
            "Worker moves are feasible only when role-compatible and break windows remain protected.",
            "Send supervisor-visible worker tasks with destination, role, deadline, and break constraints.",
            "risk" if open_callouts >= 20 else "watch" if open_callouts >= 10 else "ok",
            0.84,
        ),
        _finding(
            "food_demand_agent",
            "reactive",
            [f"food_zone={food_zone.get('name', 'unknown')}", f"food_wait={food_zone.get('waitMins', 0)}m", f"density={food_zone.get('density', 0)}%"],
            "Food demand can absorb or worsen a disruption depending on kitchen load and inventory.",
            "Suppress constrained items and route offers only where capacity exists.",
            "risk" if int(food_zone.get("waitMins", 0) or 0) >= 30 else "watch",
            0.8,
        ),
        _finding(
            "facilities_energy_agent",
            "reactive",
            [f"grid_load={grid_load}%", f"heat_index={weather.get('heatIndexF', 0)}F", f"storm_risk={storm_risk}%"],
            "Energy savings are secondary when guests are sheltering or heat comfort risk is high.",
            "Protect shelter-zone HVAC and shed only noncritical loads.",
            "risk" if grid_load >= 95 or storm_risk >= 70 else "watch",
            0.82,
        ),
        _finding(
            "safety_policy_agent",
            "reactive",
            [f"safety_eval={evals.get('Safety', 0)}", f"policy_violation={(eval_result or {}).get('scorecard', {}).get('policy_violation', False)}"],
            "The plan needs operator review whenever safety, maintenance, labor, weather, or privacy thresholds are active.",
            "Keep human approval attached to safety-sensitive ride, staffing, and storm actions.",
            "risk" if (eval_result or {}).get("scorecard", {}).get("needs_human_approval") else "ok",
            0.93,
        ),
        _finding(
            "decision_bridge_agent",
            "reactive",
            [
                f"selected={selected.get('target', '')}/{selected.get('action', '')}",
                f"optimizer={(optimization or {}).get('mode', 'not_run')}",
                f"confidence={(plan or {}).get('confidence_score', 0)}",
            ],
            f"Selected {selected.get('label') or selected.get('target', 'operator action')} because it can be delivered through the action bus and evaluated after response.",
            str((optimization or {}).get("decision_summary") or (plan or {}).get("recommended_action") or "Execute the highest-scoring balanced action."),
            "risk" if scenario_key in {"ride_down", "storm_response"} else "watch",
            min(0.96, max(0.62, float((plan or {}).get("confidence_score", 82) or 82) / 100)),
        ),
        _finding(
            "logic_audit_agent",
            "judge",
            [
                f"selected={selected.get('target', '')}/{selected.get('action', '')}",
                f"policy_score={evals.get('Safety', 0)}",
                f"take_rate={response.get('takeRate', 0)}",
            ],
            "Layered decision graph checks detection evidence, hard constraints, tradeoffs, selected action, and post-decision response.",
            "Refresh the graph node when telemetry exposes a missing edge, stale assumption, or revision trigger.",
            "watch" if float(response.get("takeRate", 1) or 1) < 0.45 else "ok",
            0.86,
        ),
        _finding(
            "gcp_eval_judge_agent",
            "judge",
            [
                f"overall={(eval_result or {}).get('scorecard', {}).get('overall', 0)}",
                f"take_rate={response.get('takeRate', 0)}",
                f"follow_through={response.get('reactiveFollowThroughRate', 0)}",
            ],
            "Decision quality is judged on groundedness, safety, capacity, worker stress, response, and follow-through.",
            "Use eval deltas and outcome memory to revise the next recommendation.",
            "watch" if int((eval_result or {}).get("scorecard", {}).get("overall", 0) or 0) < 75 else "ok",
            0.88,
        ),
    ]
    return _trace_findings(findings, "reactive")


def build_event_agent_findings(plan: dict[str, Any], park_state: dict[str, Any], retrieved_context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    quality = plan.get("quality", {}) if isinstance(plan, dict) else {}
    eval_scores = quality.get("gcp_eval", {}) if isinstance(quality.get("gcp_eval"), dict) else {}
    if not eval_scores:
        eval_scores = quality.get("arize_eval", {}) if isinstance(quality.get("arize_eval"), dict) else {}
    score = int(quality.get("overall", plan.get("judge_scorecard", {}).get("overall", 0)) or 0)
    findings = [
        _finding("park_understanding_agent", "event_planning", ["park_model=zones/rides/paths", f"memory={_memory_count(retrieved_context)}"], "Park model converted into placement and congestion constraints.", "Keep the plan grounded in named zones, rides, paths, and known capacity.", "ok", 0.88),
        _finding("event_creative_agent", "event_planning", [f"concepts={len(plan.get('concepts', []) or [])}", f"selected={plan.get('selected_concept', 'pending')}"], "Creative concepts are constrained by guest segments, family-safe windows, operations, and revenue potential.", "Select the concept that gives the best operating tradeoff rather than the most dramatic theme.", "ok", 0.84),
        _finding("event_setup_agent", "event_planning", [f"event={plan.get('event_name', 'temporary event')}", f"equipment_moves={len(plan.get('equipment_moves', []) or [])}"], "Setup dependencies are visible and time-bounded.", "Pre-stage equipment before guest waves build.", "watch", 0.84),
        _finding("traffic_flow_agent", "event_planning", [f"time_blocks={len(plan.get('temporal_flow_plan', []) or [])}", f"risks={len(plan.get('risk_findings', []) or [])}"], "Temporal movement is modeled across arrival, family period, peak scare demand, and exit wave.", "Use time-blocked routing and avoid static queues on corridors with spillback risk.", "watch", 0.86),
        _finding("planning_agent", "event_planning", [f"score={score}", f"plan_version={plan.get('plan_version', 'draft')}", f"risk_findings={len(plan.get('risk_findings', []) or [])}"], "The learned park model is online as a planner: it rehearses the event against map, staffing, traffic, showtime, and policy constraints before asking Decision Bridge to commit.", "Promote only the multi-wave plan whose forecast, controls, and measured learning can be traced to evidence.", "ok" if score >= 82 else "watch", 0.87),
        _finding("placement_agent", "event_planning", [f"placements={len(plan.get('temporary_experiences', []) or [])}"], "Temporary experiences were placed against crowd-flow and path-risk constraints.", "Keep static queues away from narrow or emergency corridors.", "watch", 0.86),
        _finding("guest_flow_agent", "event_planning", [f"time_blocks={len(plan.get('temporal_flow_plan', []) or [])}"], "Guest routing separates segments and demand waves instead of pushing everyone to one place.", "Use segmented nudges and demand shaping instead of one static layout.", "ok", 0.85),
        _finding("staffing_agent", "event_planning", [f"staff_roles={len(plan.get('staffing_plan', []) or [])}"], "Staffing plan estimates role counts and placements but still requires operator scheduling review.", "Protect ride-operator minimums and break policy while staffing event roles.", "watch", 0.82),
        _finding("facilities_energy_agent", "event_planning", [f"equipment_feasibility={eval_scores.get('equipment_feasibility', score)}"], "Equipment and temporary power are treated as physical dependencies, not decoration.", "Verify power, lighting, fog, POS, and trash-bin moves before opening.", "watch", 0.83),
        _finding("finance_agent", "event_planning", [f"guest_experience={eval_scores.get('guest_experience', score)}", f"staff_feasibility={eval_scores.get('staff_feasibility', score)}"], "Business value is checked against labor, energy, food, merchandise, and guest trust tradeoffs.", "Preserve revenue opportunities without sacrificing safety, comfort, or fairness.", "ok" if score >= 82 else "watch", 0.79),
        _finding("safety_policy_agent", "event_planning", [f"constraint_score={eval_scores.get('constraint_following', score)}"], "Safety critique checks exits, narrow paths, ride operations, and human approval boundaries.", "Revise any placement that conflicts with emergency access or normal ride operations.", "risk" if score < 75 else "ok", 0.9),
        _finding("logic_audit_agent", "judge", [f"overall={score}", f"risk_findings={len(plan.get('risk_findings', []) or [])}", f"placements={len(plan.get('temporary_experiences', []) or [])}"], "Decision graph audit ties each event-planning layer to evidence, constraints, selected placements, and revision hooks.", "Update the graph if the scorecard or risk findings reveal an unsupported decision edge.", "watch" if score < 85 else "ok", 0.85),
        _finding("gcp_eval_judge_agent", "judge", [f"overall={score}", f"status={quality.get('status', 'unknown')}"], "Judge scorecard makes plan quality visible across constraints, grounding, completeness, and feasibility.", "Use critique to produce a revised plan when score or response telemetry is weak.", "watch" if score < 85 else "ok", 0.87),
    ]
    return _trace_findings(findings, "event_planning")


def build_proactive_agent_findings(proactive: dict[str, Any], brief: dict[str, Any] | None = None, eval_result: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    rows = proactive.get("insights", []) if isinstance(proactive, dict) else []
    findings = []
    for item in rows:
        agent_id = _agent_id_from_name(str(item.get("agent", "")))
        findings.append(
            _finding(
                agent_id,
                "proactive",
                [str(signal) for signal in item.get("evidence", [])[:4]],
                str(item.get("trigger", "")),
                str(item.get("recommendation", "")),
                str(item.get("urgency", "watch")),
                float(item.get("confidence", 0.78) or 0.78),
                extra={
                    "why_now": item.get("why_now", ""),
                    "deadline_minutes": item.get("deadline_minutes"),
                    "proactive_not_reactive": item.get("proactive_not_reactive", ""),
                },
            )
        )
    if brief or eval_result:
        findings.append(
            _finding(
                "decision_bridge_agent",
                "proactive",
                [f"commitments={len((brief or {}).get('recommended_commitments', []) or [])}", f"eval={(eval_result or {}).get('overall', 0)}"],
                str((brief or {}).get("why_now", "Proactive scan found early operating signals.")),
                str((brief or {}).get("operator_brief", "Commit low-risk pre-stage actions for operator review.")),
                "watch",
                0.84,
            )
        )
        findings.append(
            _finding(
                "gcp_eval_judge_agent",
                "judge",
                [f"overall={(eval_result or {}).get('overall', 0)}", f"false_alarm_risk={(eval_result or {}).get('false_alarm_risk', 0)}"],
                "Proactive action is scored for timeliness, actionability, prevention value, and false-alarm risk.",
                "Use observed response and follow-through to tune future pre-stage thresholds.",
                "ok" if int((eval_result or {}).get("overall", 0) or 0) >= 78 else "watch",
                0.86,
            )
        )
        findings.append(
            _finding(
                "logic_audit_agent",
                "judge",
                [f"insights={len(rows)}", f"commitments={len((brief or {}).get('recommended_commitments', []) or [])}", f"eval={(eval_result or {}).get('overall', 0)}"],
                "Proactive graph audit connects early detection to constraint checks, committed actions, and post-decision learning markers.",
                "Keep animation state markers aligned with the latest detection, audit, and outcome nodes.",
                "ok" if int((eval_result or {}).get("overall", 0) or 0) >= 78 else "watch",
                0.84,
            )
        )
    return _trace_findings(findings, "proactive")


def _role_proposal(
    agent_id: str,
    recommendation: str,
    proposed_action: dict[str, Any],
    evidence: list[str],
    constraints: list[str],
    confidence: float,
    proposal_type: str,
) -> dict[str, Any]:
    registry = {agent["agent_id"]: agent for agent in AGENT_REGISTRY}
    agent = registry.get(agent_id, registry["decision_bridge_agent"])
    department = _department_for_agent(str(agent["agent_id"]))
    normalized_agent_id = str(agent["agent_id"])
    requested_tool = _proposal_tool_for_action(normalized_agent_id, proposed_action)
    proposal_envelope = build_department_tool_proposal(
        normalized_agent_id,
        requested_tool,
        intent=recommendation,
        evidence=evidence,
        risk_level=_risk_for_proposal(proposal_type, proposed_action, constraints),
        expected_outcome=str(proposed_action.get("expected_outcome") or recommendation),
        rollback=str(proposed_action.get("rollback") or "withdraw proposal before Tool Executor receives it"),
        payload=proposed_action,
    )
    return {
        "agent_id": agent["agent_id"],
        "role": agent["name"],
        "department": department["department"],
        "department_label": department["label"],
        "department_agent": department["canonical_agent"],
        "loop": [step.title() for step in DEPARTMENT_AGENT_LOOP],
        "proposal_type": proposal_type,
        "proposal_envelope": proposal_envelope,
        "requested_tool": requested_tool,
        "requires_compliance": proposal_envelope["requires_compliance"],
        "requires_executive": proposal_envelope["requires_executive"],
        "executor_status": proposal_envelope["executor_status"],
        "recommendation": recommendation,
        "proposed_action": proposed_action,
        "evidence": evidence[:5],
        "constraints": constraints[:5],
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "policy_refs": _policy_refs_for_agent(agent),
        "handoff_to": "decision_bridge_agent" if agent_id != "decision_bridge_agent" else "central_optimizer",
    }


def _proposal_envelope_summary(proposals: list[dict[str, Any]]) -> dict[str, Any]:
    envelopes = [item.get("proposal_envelope", {}) for item in proposals if isinstance(item.get("proposal_envelope"), dict)]
    return {
        "total": len(envelopes),
        "proposed": sum(1 for envelope in envelopes if envelope.get("proposal_status") == "proposed"),
        "blocked": sum(1 for envelope in envelopes if envelope.get("proposal_status") == "blocked"),
        "requires_compliance": sum(1 for envelope in envelopes if envelope.get("requires_compliance")),
        "requires_executive": sum(1 for envelope in envelopes if envelope.get("requires_executive")),
        "ready_for_executor": sum(1 for envelope in envelopes if envelope.get("executor_status") == "ready_for_executor"),
        "awaiting_compliance": sum(1 for envelope in envelopes if envelope.get("executor_status") == "awaiting_compliance"),
        "awaiting_executive": sum(1 for envelope in envelopes if envelope.get("executor_status") == "awaiting_executive"),
    }


def _role_proposal_conflicts(
    proposals: list[dict[str, Any]],
    scenario_key: str,
    open_callouts: int,
    crowded_zone: dict[str, Any],
    route: dict[str, Any],
) -> list[dict[str, Any]]:
    agent_ids = {item.get("agent_id") for item in proposals}
    conflicts: list[dict[str, Any]] = []
    density = int(crowded_zone.get("density", 0) or 0)
    if {"guest_flow_agent", "staffing_agent"} <= agent_ids:
        conflicts.append(
            {
                "conflict": "Guest redistribution needs workers at edges, but staffing capacity may be thin.",
                "agents": ["guest_flow_agent", "staffing_agent", "decision_bridge_agent"],
                "resolution": "Prefer split soft nudges and small role-compatible staff moves before broad hard reroutes.",
                "status": "resolved" if open_callouts < 20 else "watch",
            }
        )
    if scenario_key == "food_spike" and "food_demand_agent" in agent_ids:
        conflicts.append(
            {
                "conflict": "Food demand diversion can overload the alternate venue.",
                "agents": ["food_demand_agent", "guest_flow_agent", "decision_bridge_agent"],
                "resolution": "Cap the alternate share and keep a hold/current-pickup lane for constrained-zone guests.",
                "status": "resolved",
            }
        )
    if scenario_key == "storm_response" and "facilities_energy_agent" in agent_ids:
        conflicts.append(
            {
                "conflict": "Energy/load control competes with shelter comfort during weather response.",
                "agents": ["facilities_energy_agent", "guest_flow_agent", "safety_policy_agent"],
                "resolution": "Protect shelter HVAC first; shed only noncritical lighting or comfort-neutral loads.",
                "status": "resolved",
            }
        )
    if scenario_key == "marketing_promo_conflict" and {"event_creative_agent", "ride_ops_agent", "safety_policy_agent", "finance_agent", "decision_bridge_agent"} <= agent_ids:
        conflicts.append(
            {
                "conflict": "Marketing wants to push a discount to Zone B, but Ops and Safety show Zone B is already overcrowded.",
                "agents": ["event_creative_agent", "ride_ops_agent", "safety_policy_agent", "finance_agent", "decision_bridge_agent"],
                "resolution": "Executive rejects the Zone B action and chooses a redirected Zone C offer that preserves revenue without increasing the crowd hazard.",
                "status": "resolved",
            }
        )
    if bool(route.get("requires_human_review")):
        conflicts.append(
            {
                "conflict": "Urgent operator command may require human approval before automation.",
                "agents": ["safety_policy_agent", "decision_bridge_agent"],
                "resolution": "Emit receiver-ready drafts while keeping safety-sensitive execution behind approval.",
                "status": "review",
            }
        )
    if density >= 85:
        conflicts.append(
            {
                "conflict": "The highest-density zone cannot safely absorb more demand.",
                "agents": ["guest_flow_agent", "safety_policy_agent", "decision_bridge_agent"],
                "resolution": "Exclude the crowded zone from positive promotion until density falls.",
                "status": "watch",
            }
        )
    return conflicts[:4]


def _finding(
    agent_id: str,
    mode: str,
    input_signals: list[str],
    finding: str,
    recommendation: str,
    urgency: str,
    confidence: float,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    registry = {agent["agent_id"]: agent for agent in AGENT_REGISTRY}
    agent = registry.get(agent_id, registry["decision_bridge_agent"])
    department = _department_for_agent(str(agent["agent_id"]))
    return {
        "agent_id": agent["agent_id"],
        "name": agent["name"],
        "department": department["department"],
        "department_label": department["label"],
        "department_agent": department["canonical_agent"],
        "loop": [step.title() for step in DEPARTMENT_AGENT_LOOP],
        "role": agent["role"],
        "mode": mode,
        "input_signals": input_signals,
        "finding": finding,
        "recommendation": recommendation,
        "urgency": urgency if urgency in {"risk", "watch", "ok"} else "watch",
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "policy_refs": _policy_refs_for_agent(agent),
        "trace_span": f"parkpulse.agent.{agent['agent_id']}.{mode}",
        "created_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        **(extra or {}),
    }


def _policy_refs_for_agent(agent: dict[str, Any]) -> list[str]:
    scopes = AGENT_POLICY_SCOPES.get(str(agent.get("agent_id", "")), [])
    if not scopes:
        return list(agent.get("policy_refs", []))
    engine = get_policy_engine()
    refs: set[str] = set()
    for scope in scopes:
        refs.update(engine.refs_for_action(scope.get("target", ""), scope.get("action", ""), scope.get("scenario")))
    for ref in agent.get("policy_refs", []):
        if str(ref).startswith("PARK-EVAL-"):
            refs.add(str(ref))
    return sorted(refs)


def _trace_findings(findings: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    with _tracer.start_as_current_span(f"parkpulse.multi_agent.{mode}") as parent:
        parent.set_attribute("parkpulse.agent.mode", mode)
        parent.set_attribute("parkpulse.agent.count", len(findings))
        for item in findings:
            with _tracer.start_as_current_span(item["trace_span"]) as span:
                span.set_attribute("parkpulse.agent.id", item["agent_id"])
                span.set_attribute("parkpulse.agent.name", item["name"])
                span.set_attribute("parkpulse.agent.department", item.get("department", ""))
                span.set_attribute("parkpulse.agent.mode", item["mode"])
                span.set_attribute("parkpulse.agent.urgency", item["urgency"])
                span.set_attribute("parkpulse.agent.confidence", item["confidence"])
                span.set_attribute("parkpulse.agent.policy_refs", ",".join(item.get("policy_refs", [])))
        return findings


def _top_ride(rides: list[dict[str, Any]]) -> dict[str, Any]:
    return max(
        rides or [{}],
        key=lambda ride: (
            100 if ride.get("status") == "down" else 35 if ride.get("status") == "constrained" else 0,
            int(ride.get("downtimeRisk", 0) or 0),
            int(ride.get("waitMins", 0) or 0),
            int(ride.get("queueGuests", 0) or 0),
        ),
    )


def _top_zone(zones: list[dict[str, Any]]) -> dict[str, Any]:
    return max(zones or [{}], key=lambda zone: int(zone.get("density", 0) or 0))


def _top_path(paths: list[dict[str, Any]]) -> dict[str, Any]:
    return max(paths or [{}], key=lambda path: int(path.get("congestionLevel", 0) or 0))


def _urgency(score: int) -> str:
    if score >= 85:
        return "risk"
    if score >= 65:
        return "watch"
    return "ok"


def _memory_count(context: dict[str, Any] | None) -> int:
    retrieved = (context or {}).get("retrieved", {}) if isinstance(context, dict) else {}
    return len(retrieved.get("playbooks", []) or []) + len(retrieved.get("incidents", []) or []) + len(retrieved.get("learnings", []) or [])


def _agent_id_from_name(name: str) -> str:
    normalized = name.lower()
    if "placement" in normalized:
        return "placement_agent"
    if "traffic" in normalized or "flow" in normalized and "guest" not in normalized:
        return "traffic_flow_agent"
    if "creative" in normalized or "concept" in normalized:
        return "event_creative_agent"
    if "finance" in normalized or "revenue" in normalized or "cost" in normalized:
        return "finance_agent"
    if "guest flow" in normalized:
        return "guest_flow_agent"
    if "facilities" in normalized or "energy" in normalized:
        return "facilities_energy_agent"
    if "food" in normalized:
        return "food_demand_agent"
    if "staff" in normalized or "labor" in normalized:
        return "staffing_agent"
    if "setup" in normalized or "event" in normalized:
        return "event_setup_agent"
    if "ride" in normalized:
        return "ride_ops_agent"
    return "decision_bridge_agent"
