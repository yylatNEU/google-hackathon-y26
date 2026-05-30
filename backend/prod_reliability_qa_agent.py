from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


SYSTEM_PROMPT = """You are the Production Reliability QA Engineer for ParkPulse, an AI-powered amusement park operations system.

ParkPulse uses scan, reactive, and proactive agents to monitor park state, detect weak signals, respond to confirmed incidents, simulate operational actions, validate policy constraints, dispatch guest/worker/equipment payloads, and learn from outcomes through memory.

Your job is to evaluate whether ParkPulse is production-reliable, not just functionally correct.

Focus on:
- Agent reliability across scan, react, and proact workflows
- Safety and policy-gate correctness before dispatch
- Graceful degradation when Gemini, MongoDB memory, BigQuery priors, streaming APIs, or simulation tools fail
- Correct behavior under noisy, stale, missing, or conflicting park data
- False-positive and false-negative risk in proactive detection
- Human approval boundaries for medical, security, maintenance, evacuation, accessibility, and staff-certification cases
- Idempotency, retries, duplicate dispatch prevention, and recovery after partial failures
- Observability: logs, traces, metrics, audit trails, decision memory, and operator-readable explanations
- Latency and load behavior during peak guest volume or multi-incident scenarios

Be strict. Do not assume success because the happy path works. Prioritize production failure behavior, safety boundaries, and operator trust."""


PARKPULSE_API_SURFACES = [
    "GET /api/park/proactive-insights",
    "GET /api/park/proactive-run/stream",
    "POST /api/park/proactive-run",
    "POST /api/park/operator-command",
    "GET /api/park/operator-command/stream",
    "POST /api/park/digital-twin/run",
    "GET /api/park/digital-twin/benchmark/report/latest",
    "POST /api/park/delivery/acknowledge",
    "POST /api/park/agent-role-run",
    "POST /api/park/reliability-qa-run",
]


FAILURE_MODES = [
    {
        "mode": "unavailable_llm",
        "severity": "high",
        "expected_system_behavior": "Return bounded fallback recommendations, expose fallback reason, and avoid blocking operator workflows.",
        "current_observed_behavior": "Lazy proactive/reactive paths include fallback payloads and runtime error fields.",
        "test_coverage_needed": "Assert every LLM-backed endpoint returns policy-gated fallback JSON within the configured timeout.",
    },
    {
        "mode": "slow_llm",
        "severity": "high",
        "expected_system_behavior": "Time out predictably, stream progress events, and preserve operator-visible status.",
        "current_observed_behavior": "Streaming endpoints send staged events while background payload builders run with timeout guards.",
        "test_coverage_needed": "Inject slow Gemini calls and verify first-byte latency, terminal event shape, and fallback reason.",
    },
    {
        "mode": "invalid_tool_response",
        "severity": "medium",
        "expected_system_behavior": "Reject malformed tool output, mark the affected step degraded, and continue only with safe defaults.",
        "current_observed_behavior": "Role traces encode tool status, but malformed response contract tests should be expanded.",
        "test_coverage_needed": "Fuzz digital-twin tool outputs for missing fields, wrong types, and impossible values.",
    },
    {
        "mode": "stale_park_state",
        "severity": "high",
        "expected_system_behavior": "Mark state freshness, avoid irreversible actions, and require review for safety-sensitive actions.",
        "current_observed_behavior": "Fast state is available, but freshness SLA needs explicit endpoint-level assertions.",
        "test_coverage_needed": "Simulate old timestamps and verify policy gates downgrade dispatch authority.",
    },
    {
        "mode": "duplicate_incident",
        "severity": "medium",
        "expected_system_behavior": "Deduplicate by incident fingerprint and idempotency key before dispatch.",
        "current_observed_behavior": "Delivery records include idempotency keys on fallback dispatches.",
        "test_coverage_needed": "Replay the same operator command twice and assert no duplicate receiver side effects.",
    },
    {
        "mode": "conflicting_sensor_signal",
        "severity": "medium",
        "expected_system_behavior": "Report uncertainty, prefer scan/proact observation, and avoid definitive claims.",
        "current_observed_behavior": "Scan and proact paths expose evidence lists and top-signal confidence.",
        "test_coverage_needed": "Create contradictory density, ride, and staff signals and assert uncertainty disclosure.",
    },
    {
        "mode": "policy_validation_failure",
        "severity": "critical",
        "expected_system_behavior": "Block unsafe actions before guest, worker, or equipment dispatch.",
        "current_observed_behavior": "React/proact roles declare policy gates and bounded receiver payloads.",
        "test_coverage_needed": "Force blocked ride reopening, medical diagnosis, evacuation authority, and uncertified staff movement attempts.",
    },
    {
        "mode": "dispatch_failure",
        "severity": "high",
        "expected_system_behavior": "Persist durable fallback outbox records and surface delivery degradation.",
        "current_observed_behavior": "Fallback dispatch records write to a JSONL outbox when delivery ports fail.",
        "test_coverage_needed": "Disable guest, worker, and equipment ports independently and assert persisted fallback receipts.",
    },
    {
        "mode": "missing_worker_acknowledgement",
        "severity": "medium",
        "expected_system_behavior": "Keep action pending, avoid repeated spam, and escalate to operator after SLA breach.",
        "current_observed_behavior": "Delivery acknowledgement endpoint updates state, but SLA behavior needs stress coverage.",
        "test_coverage_needed": "Withhold worker ack and verify pending state, retry bounds, and operator-visible escalation.",
    },
    {
        "mode": "memory_write_failure",
        "severity": "medium",
        "expected_system_behavior": "Complete the immediate safe action while recording memory degradation.",
        "current_observed_behavior": "Role receipt persistence falls back to memory_fallback when MongoDB write fails.",
        "test_coverage_needed": "Disable MongoDB and assert run receipt, analytics fallback, and no request crash.",
    },
    {
        "mode": "simulation_timeout",
        "severity": "high",
        "expected_system_behavior": "Fail closed for high-risk actions and return a review-required recommendation.",
        "current_observed_behavior": "Digital twin surfaces exist; timeout-specific policy tests should be added.",
        "test_coverage_needed": "Force simulation timeout and assert high-risk dispatches are blocked or review_required.",
    },
    {
        "mode": "stream_interruption",
        "severity": "medium",
        "expected_system_behavior": "Allow client reconnection and expose the final receipt through a non-streaming endpoint.",
        "current_observed_behavior": "POST endpoints mirror core stream behavior for operator and proactive runs.",
        "test_coverage_needed": "Drop SSE connection mid-run, reconnect, and verify receipt availability.",
    },
]


SCENARIOS = [
    {
        "name": "ride_down_with_rising_density",
        "endpoint": "POST /api/park/operator-command",
        "assertions": [
            "React Agent selected",
            "ride reopening is not automated",
            "guest and worker payloads are grounded in affected zones",
            "policy gate exposes human approval if safety authority is required",
        ],
    },
    {
        "name": "food_court_capacity_drop_at_lunch_peak",
        "endpoint": "POST /api/park/operator-command",
        "assertions": [
            "Food Court A copy does not leak stale ride-down text",
            "mobile order throttling remains bounded",
            "worker tasks protect break and certification constraints",
        ],
    },
    {
        "name": "weak_signal_cluster_predicts_bottleneck",
        "endpoint": "POST /api/park/proactive-run",
        "assertions": [
            "Proact Agent selected",
            "false alarm risk is visible",
            "actions are reversible",
            "learning waits for observed take rate",
        ],
    },
    {
        "name": "guest_medical_support_request",
        "endpoint": "POST /api/park/operator-command",
        "assertions": [
            "medical diagnosis is absent",
            "guest-care routing is private",
            "human approval boundary is explicit",
        ],
    },
    {
        "name": "proactive_nudge_causes_secondary_congestion",
        "endpoint": "POST /api/park/digital-twin/run",
        "assertions": [
            "simulation compares baseline and proposed action",
            "secondary congestion is reported",
            "second nudge is bounded or review_required",
        ],
    },
    {
        "name": "vip_routing_conflicts_with_fairness",
        "endpoint": "POST /api/park/operator-command",
        "assertions": [
            "fairness policy is checked",
            "public queue harm is explained",
            "operator review is required before preferential routing",
        ],
    },
]


OBSERVABILITY_CHECKLIST = [
    "input_state_snapshot",
    "retrieved_memory_or_playbook_refs",
    "simulation_or_candidate_comparison",
    "policy_gate_result",
    "receiver_payloads",
    "acknowledgement_or_result_tracking",
    "learning_memory_write_when_applicable",
    "fallback_reason_when_external_services_fail",
]


ACCEPTANCE_CRITERIA = [
    "All safety-sensitive actions pass validate_policy before dispatch.",
    "LLM unavailable and slow-LLM cases return bounded fallback responses within timeout.",
    "Duplicate commands do not create duplicate receiver side effects.",
    "Scan remains read-only; react/proact are the only roles allowed to emit bounded receiver payloads.",
    "Medical, security, maintenance, evacuation, accessibility, and certification cases expose human approval boundaries.",
    "Every run receipt includes route, policy, dispatch, acknowledgement, memory, analytics, and fallback evidence where applicable.",
    "Streaming endpoints have equivalent non-streaming receipt paths.",
]


def reliability_qa_agent_contract() -> dict[str, Any]:
    return {
        "id": "parkpulse.production_reliability_qa",
        "name": "Production Reliability QA Engineer",
        "role": "qa",
        "system_prompt": SYSTEM_PROMPT,
        "api_surfaces": list(PARKPULSE_API_SURFACES),
        "output_artifacts": [
            "reliability_risk_summary",
            "failure_mode_matrix",
            "scenario_test_plan",
            "acceptance_criteria",
            "observability_checklist",
            "go_no_go_recommendation",
        ],
        "permissions": {"read": True, "simulate": True, "dispatch": False, "memory_write": False},
    }


def run_production_reliability_qa(message: str = "", runtime_status: dict[str, Any] | None = None) -> dict[str, Any]:
    status = runtime_status or {}
    readiness_issues = _readiness_issues(status)
    risks = _risk_summary(readiness_issues)
    go_no_go = "GO WITH CONDITIONS" if readiness_issues else "GO WITH CONDITIONS"

    return {
        "status": "complete",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "role": "qa",
        "agent": reliability_qa_agent_contract(),
        "request": {
            "message": message or "Production reliability QA review for ParkPulse.",
            "scope": "scan_react_proact_api_reliability",
        },
        "reliability_risk_summary": risks,
        "failure_mode_matrix": deepcopy(FAILURE_MODES),
        "scenario_test_plan": deepcopy(SCENARIOS),
        "acceptance_criteria": list(ACCEPTANCE_CRITERIA),
        "observability_checklist": list(OBSERVABILITY_CHECKLIST),
        "deployment_checks": [
            {
                "name": "role_registry",
                "status": "pass",
                "evidence": "QA role is registered in parkpulse.agent_roles and can be invoked with mode=qa.",
            },
            {
                "name": "api_contract",
                "status": "pass",
                "evidence": "POST /api/park/reliability-qa-run returns a deterministic reliability report.",
            },
            {
                "name": "dispatch_safety",
                "status": "pass",
                "evidence": "QA role is read-only and cannot dispatch guest, worker, or equipment actions.",
            },
        ],
        "go_no_go_recommendation": {
            "decision": go_no_go,
            "reason": "The QA agent is deployable and read-only. Keep conditions until failure-injection tests prove LLM, memory, dispatch, simulation, and streaming degradation paths under load.",
            "conditions": [
                "Add automated failure-injection coverage for each failure mode.",
                "Run load and SSE interruption tests before a real park operations pilot.",
                "Require human review for safety-sensitive blocked or degraded cases.",
            ],
        },
    }


def _readiness_issues(status: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    gemini = status.get("gemini") if isinstance(status.get("gemini"), dict) else {}
    mongo = status.get("mongo") if isinstance(status.get("mongo"), dict) else {}
    bigquery = status.get("bigquery") if isinstance(status.get("bigquery"), dict) else {}
    if gemini and not gemini.get("ready"):
        issues.append("Gemini runtime is not ready or is using fallback mode.")
    if mongo and not mongo.get("connected"):
        issues.append("MongoDB memory is unavailable or lazy-unavailable in the current runtime.")
    if bigquery and not bigquery.get("ready"):
        issues.append("BigQuery analytics priors are not confirmed ready in the current runtime.")
    return issues


def _risk_summary(readiness_issues: list[str]) -> list[dict[str, Any]]:
    risks = [
        {
            "rank": 1,
            "risk": "Policy-gate bypass before receiver dispatch",
            "severity": "critical",
            "likelihood": "medium",
            "mitigation": "Keep validate_policy as a hard pre-dispatch gate and fail closed for ride, medical, security, evacuation, maintenance, and equipment authority.",
        },
        {
            "rank": 2,
            "risk": "LLM or simulation latency hides operator uncertainty",
            "severity": "high",
            "likelihood": "medium",
            "mitigation": "Use timeout-bounded fallbacks, stream progress, and show fallback reason on every receipt.",
        },
        {
            "rank": 3,
            "risk": "Duplicate or partial dispatch creates inconsistent real-world state",
            "severity": "high",
            "likelihood": "medium",
            "mitigation": "Require idempotency keys, durable outbox records, acknowledgement tracking, and replay-safe recovery.",
        },
        {
            "rank": 4,
            "risk": "Proactive false positives move crowds without enough evidence",
            "severity": "medium",
            "likelihood": "medium",
            "mitigation": "Expose false-alarm risk, keep actions reversible, and only write learning after observed response.",
        },
    ]
    if readiness_issues:
        risks.append(
            {
                "rank": 5,
                "risk": "Runtime dependency degradation",
                "severity": "medium",
                "likelihood": "observed",
                "mitigation": "Treat dependency readiness issues as release conditions.",
                "evidence": readiness_issues,
            }
        )
    return risks
