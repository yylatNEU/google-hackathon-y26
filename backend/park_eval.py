from __future__ import annotations

from copy import deepcopy
from typing import Any

from park_scenarios import PARK_SCENARIOS
from trace_helpers import finish_span, traced_span


def _bounded(score: int) -> int:
    return max(0, min(100, score))


def _scenario_from_state(park_state: dict[str, Any]) -> dict[str, Any]:
    flow = park_state.get("guestFlow", {})
    return flow.get("activeScenario", {}) if isinstance(flow, dict) else {}


def get_latest_memory_documents(collection_name: str, limit: int = 5) -> list[dict[str, Any]]:
    from mongo_memory import get_latest_memory_documents

    return get_latest_memory_documents(collection_name, limit)


def _latest_decision() -> dict[str, Any] | None:
    rows = get_latest_memory_documents("agent_decisions", 1)
    return rows[0] if rows else None


def _latest_eval() -> dict[str, Any] | None:
    rows = get_latest_memory_documents("eval_results", 1)
    return rows[0] if rows else None


def evaluate_park_decision(
    scenario_key: str,
    park_state: dict[str, Any],
    dispatches: list[dict[str, Any]] | None = None,
    governance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from arize_config import get_arize_status
    from bigquery_analytics import online_improvement_status
    from evaluator_loop import build_hosted_evaluator_loop
    from gcp_trace_eval import build_gcp_eval_trace, get_gcp_trace_eval_status
    from park_delivery import latest_dispatches, response_summary

    scenario = deepcopy(PARK_SCENARIOS.get(scenario_key, PARK_SCENARIOS["ride_down"]))
    state_scenario = _scenario_from_state(park_state)
    latest_decision = _latest_decision()
    latest_eval = _latest_eval()
    guest_flow = park_state.get("guestFlow", {})
    rides = guest_flow.get("rides", []) if isinstance(guest_flow, dict) else []
    alerts = park_state.get("alerts", [])

    down_ride_count = sum(1 for ride in rides if isinstance(ride, dict) and ride.get("status") == "down")
    overloaded_ride_count = sum(1 for ride in rides if isinstance(ride, dict) and float(ride.get("waitMins", 0) or 0) >= 50)
    has_retrieved_context = bool((latest_decision or {}).get("retrievedPlaybooks") or (latest_decision or {}).get("retrievedIncidents"))
    has_state_scenario = bool((latest_decision or {}).get("stateScenario", {}).get("key"))
    safety_score = int((latest_eval or {}).get("scores", {}).get("safety", 0) or 0)
    worker_score = int((latest_eval or {}).get("scores", {}).get("workerStress", 0) or 0)

    groundedness = 86 + (6 if has_state_scenario else 0) + (4 if alerts else 0)
    context_score = 78 + (12 if has_retrieved_context else 0)
    capacity_score = 91 - (5 * overloaded_ride_count) + (3 if down_ride_count else 0)
    staff_score = worker_score or 78
    safety = safety_score or 96
    actionability = 82 + (6 if latest_decision else 0) + (4 if (latest_decision or {}).get("selectedAction") else 0)
    response_metrics = response_summary(dispatches if dispatches is not None else latest_dispatches(10))
    take_rate_score = round(float(response_metrics.get("takeRate", 0) or 0) * 100)
    positive_response_score = round(float(response_metrics.get("positiveResponseRate", 0) or 0) * 100)
    reactive_score = round(float(response_metrics.get("reactiveFollowThroughRate", 0) or 0) * 100)
    selected_action = (latest_decision or {}).get("selectedAction") or (latest_decision or {}).get("selected_action") or {}
    selected_target = str(selected_action.get("target") or "").strip().lower() if isinstance(selected_action, dict) else ""
    selected_action_name = str(selected_action.get("action") or "").strip().lower() if isinstance(selected_action, dict) else ""
    dispatch_rows = dispatches if dispatches is not None else latest_dispatches(10)
    incident_scores = _incident_response_scores(selected_target, selected_action_name, dispatch_rows, response_metrics)
    gate_status = str((governance or {}).get("gate_status") or "")
    policy_findings = (governance or {}).get("findings", [])
    policy_score = _policy_guidance_score(governance)

    evals = [
        {
            "label": "Groundedness",
            "score": _bounded(groundedness),
            "detail": "Checks whether the recommendation is linked to live park state, active scenario, and current alerts.",
        },
        {
            "label": "Playbook retrieval",
            "score": _bounded(context_score),
            "detail": "Checks whether MongoDB memory supplied matching playbooks or incidents for the decision.",
        },
        {
            "label": "Capacity awareness",
            "score": _bounded(capacity_score),
            "detail": "Penalizes plans that could push guests toward already-overloaded rides.",
        },
        {
            "label": "Staff stress",
            "score": _bounded(staff_score),
            "detail": "Uses the latest internal worker-stress score written with the agent decision.",
        },
        {
            "label": "Safety",
            "score": _bounded(safety),
            "detail": "Safety is treated as the hard guardrail for ride, queue, and incident decisions.",
        },
        {
            "label": "Actionability",
            "score": _bounded(actionability),
            "detail": "Looks for a specific selected action, owner, and executable operational target.",
        },
        {
            "label": "Policy guidance compliance",
            "score": _bounded(policy_score),
            "detail": "Grades whether the selected response honored safety, labor, guest-care, equipment, and human-approval guidance before dispatch.",
        },
        {
            "label": "Take rate",
            "score": _bounded(take_rate_score),
            "detail": "Measures whether guests, workers, or equipment actually accepted the delivered action in the response window.",
        },
        {
            "label": "Positive response",
            "score": _bounded(positive_response_score),
            "detail": "Checks guest sentiment, worker acknowledgment quality, and command acceptance after the action is delivered.",
        },
        {
            "label": "Reactive follow-through",
            "score": _bounded(reactive_score),
            "detail": "Checks whether the park response changed behavior, such as guest movement, staff relocation, or HVAC state application.",
        },
    ]
    evals.extend(incident_scores)
    score_summary = _score_summary(evals, response_metrics)
    average_score = score_summary["overall"]
    arize_status = get_arize_status().public_dict()
    improvement_status = online_improvement_status()
    gcp_trace_eval = get_gcp_trace_eval_status().public_dict()
    if gcp_trace_eval.get("ready"):
        judge_mode = "gcp_bigquery_improvement_loop_with_local_eval_judge"
    elif arize_status.get("ready"):
        judge_mode = "optional_arize_trace_with_local_eval_judge"
    else:
        judge_mode = "local_eval_judge_with_gcp_export_preview"
    dimensions = [item["label"] for item in evals]
    dimension_scores = {item["label"]: item["score"] for item in evals}
    dimension_explanations = {item["label"]: item["detail"] for item in evals}
    failure_reasons = _failure_reasons(evals, gate_status, scenario["humanApproval"])
    with traced_span(
        f"parkpulse.eval.local_scorecard.{scenario['key']}",
        span_kind="EVALUATOR",
        attributes={
            "parkpulse.scenario": scenario["key"],
            "parkpulse.eval.judge_mode": judge_mode,
            "parkpulse.eval.dimension_count": len(evals),
        },
        input_value={
            "scenario_key": scenario_key,
            "decision_id": (latest_decision or {}).get("_id"),
            "dispatch_count": len(dispatch_rows),
            "governance": governance or {},
        },
    ) as span:
        trace_artifact = build_gcp_eval_trace(
            span=f"parkpulse.decision_bridge.{scenario['key']}",
            eval_subject="park_operations_action_plan",
            dimensions=dimensions,
            decision_id=(latest_decision or {}).get("_id"),
        )
        scorecard = {
            "overall": average_score,
            "plan_quality_score": score_summary["plan_quality_score"],
            "outcome_effectiveness_score": score_summary["outcome_effectiveness_score"],
            "score_method": score_summary["method"],
            "status": "passed" if average_score >= 80 and not failure_reasons else "review",
            "policy_violation": _bounded(safety) < 90 or _bounded(policy_score) < 75 or gate_status == "blocked",
            "needs_human_approval": scenario["humanApproval"] or _bounded(safety) < 95 or gate_status in {"review", "blocked", "pending_operator_approval"},
            "policy_guidance_score": _bounded(policy_score),
            "policy_gate_status": gate_status or None,
            "policy_findings": policy_findings if isinstance(policy_findings, list) else [],
            "decision_id": (latest_decision or {}).get("_id"),
            "eval_id": (latest_eval or {}).get("_id"),
            "response_status": response_metrics.get("status"),
            "response_score": response_metrics.get("score"),
            "failure_reasons": failure_reasons,
        }
        hosted_eval = build_hosted_evaluator_loop(
            scenario_key=scenario["key"],
            scorecard=scorecard,
            dimension_scores=dimension_scores,
            dimension_explanations=dimension_explanations,
            failure_reasons=failure_reasons,
            response_metrics=response_metrics,
            trace_artifact=trace_artifact,
            decision_id=(latest_decision or {}).get("_id"),
            selected_action=selected_action if isinstance(selected_action, dict) else {},
            governance=governance or {},
            dispatches=dispatch_rows,
            state_digest=_state_digest(park_state),
        )
        result = {
            "source": "parkpulse_gcp_internal_eval_loop",
            "judge": {
                "mode": judge_mode,
                "gcp_trace_eval_ready": bool(gcp_trace_eval.get("ready")),
                "arize_ready": bool(arize_status.get("ready")),
                "online_improvement_provider": improvement_status.get("provider", "gcp"),
                "online_improvement_ready": bool(improvement_status.get("ready")),
                "external_arize_optional": True,
                "fallback_reason": None
                if gcp_trace_eval.get("ready") or arize_status.get("ready")
                else "; ".join(improvement_status.get("readiness_issues", []))
                or "GCP online improvement export is not configured; local scorecards are active.",
            },
            "scenario": {
                "key": scenario["key"],
                "title": scenario["title"],
                "riskLevel": scenario["riskLevel"],
                "confidence": scenario["confidence"],
                "humanApproval": scenario["humanApproval"],
                "liveStateScenario": state_scenario.get("key", scenario["key"]),
            },
            "evals": evals,
            "dimension_scores": dimension_scores,
            "dimension_explanations": dimension_explanations,
            "failure_reasons": failure_reasons,
            "hosted_eval": hosted_eval,
            "scorecard": scorecard,
            "response_metrics": response_metrics,
            "gcp_trace_eval": trace_artifact,
            "arize_trace": trace_artifact,
            "online_improvement": {
                "provider": improvement_status.get("provider", "gcp"),
                "primary_path": improvement_status.get("primary_path", "gcp_bigquery"),
                "ready": bool(improvement_status.get("ready")),
                "mode": improvement_status.get("mode", "local_scorecard_with_gcp_export_preview"),
            },
        }
        finish_span(
            span,
            {
                "overall": average_score,
                "status": scorecard["status"],
                "dimension_scores": dimension_scores,
                "failure_reasons": failure_reasons,
            },
            {
                "parkpulse.eval.overall": average_score,
                "parkpulse.eval.status": scorecard["status"],
                "parkpulse.eval.failure_count": len(failure_reasons),
                "parkpulse.trace.id": trace_artifact.get("trace_id", ""),
            },
        )
        return result


def _incident_response_scores(
    selected_target: str,
    selected_action: str,
    dispatches: list[dict[str, Any]] | None,
    response_metrics: dict[str, Any],
) -> list[dict[str, Any]]:
    care_targets = {"medical", "accessibility", "security"}
    if selected_target not in care_targets:
        return []
    dispatch_rows = dispatches or []
    worker_dispatches = [
        item
        for item in dispatch_rows
        if isinstance(item, dict) and item.get("channel") == "worker_device"
    ]
    guest_dispatches = [
        item
        for item in dispatch_rows
        if isinstance(item, dict) and item.get("channel") == "guest_app"
    ]
    equipment_dispatches = [
        item
        for item in dispatch_rows
        if isinstance(item, dict) and item.get("channel") == "equipment_controller"
    ]
    qualified_worker = any(
        str((dispatch.get("payload") or {}).get("role") or "").lower() in {selected_target, "medical", "accessibility_support", "security"}
        for dispatch in worker_dispatches
    )
    privacy_safe = all(
        not any(term in str((dispatch.get("payload") or {}).get("message") or (dispatch.get("payload") or {}).get("task") or "").lower() for term in ("diagnosis", "patient name", "child name", "medical details"))
        for dispatch in dispatch_rows
        if isinstance(dispatch, dict)
    )
    ack_rate = float(response_metrics.get("positiveResponseRate", 0) or 0)
    follow_rate = float(response_metrics.get("reactiveFollowThroughRate", 0) or 0)
    has_wayfinding = bool(guest_dispatches or equipment_dispatches)
    action_label = f"{selected_target}/{selected_action}".strip("/")
    return [
        {
            "label": "Incident response fit",
            "score": _bounded(88 + (6 if qualified_worker else -18) + (4 if has_wayfinding else -6)),
            "detail": f"Checks whether the {action_label} plan sent the right responder and nearby support actions instead of falling back to a generic reroute.",
        },
        {
            "label": "Sensitive-care privacy",
            "score": _bounded(96 if privacy_safe else 48),
            "detail": "Checks that guest-facing and worker-facing payloads avoid names, diagnoses, child details, and public medical/security specifics.",
        },
        {
            "label": "Responder acknowledgement",
            "score": _bounded(round(ack_rate * 72 + follow_rate * 28)),
            "detail": "Measures whether the responsible worker channel acknowledged and showed follow-through for a care or security incident.",
        },
    ]


def _score_summary(evals: list[dict[str, Any]], response_metrics: dict[str, Any]) -> dict[str, Any]:
    outcome_labels = {"Take rate", "Positive response", "Reactive follow-through", "Responder acknowledgement"}
    outcome_scores = [int(item.get("score", 0) or 0) for item in evals if item.get("label") in outcome_labels]
    quality_scores = [int(item.get("score", 0) or 0) for item in evals if item.get("label") not in outcome_labels]
    plan_quality = round(sum(quality_scores) / len(quality_scores)) if quality_scores else 0
    response_score = response_metrics.get("score")
    if response_score is None:
        outcome_effectiveness = round(sum(outcome_scores) / len(outcome_scores)) if outcome_scores else plan_quality
    else:
        outcome_effectiveness = _bounded(round(float(response_score or 0)))
    overall = _bounded(round(outcome_effectiveness * 0.7 + plan_quality * 0.3))
    return {
        "overall": overall,
        "plan_quality_score": plan_quality,
        "outcome_effectiveness_score": outcome_effectiveness,
        "method": "70pct_receiver_outcome_30pct_plan_quality",
    }


def _state_digest(park_state: dict[str, Any]) -> dict[str, Any]:
    guest_flow = park_state.get("guestFlow", {}) if isinstance(park_state.get("guestFlow"), dict) else {}
    rides = guest_flow.get("rides", []) if isinstance(guest_flow.get("rides"), list) else []
    zones = guest_flow.get("zones", []) if isinstance(guest_flow.get("zones"), list) else []
    alerts = park_state.get("alerts", []) if isinstance(park_state.get("alerts"), list) else []
    down_rides = [ride.get("name") or ride.get("id") for ride in rides if isinstance(ride, dict) and ride.get("status") == "down"]
    overloaded_rides = [
        {
            "name": ride.get("name") or ride.get("id"),
            "waitMins": ride.get("waitMins"),
            "queueGuests": ride.get("queueGuests"),
        }
        for ride in rides
        if isinstance(ride, dict) and float(ride.get("waitMins", 0) or 0) >= 50
    ]
    busiest_zones = sorted(
        [
            {
                "name": zone.get("name") or zone.get("id"),
                "density": zone.get("density"),
                "currentGuests": zone.get("currentGuests"),
            }
            for zone in zones
            if isinstance(zone, dict)
        ],
        key=lambda item: float(item.get("density", 0) or 0),
        reverse=True,
    )[:3]
    return {
        "active_scenario": guest_flow.get("activeScenario", {}),
        "alert_count": len(alerts),
        "alerts": alerts[:5],
        "down_rides": down_rides[:5],
        "overloaded_rides": overloaded_rides[:5],
        "busiest_zones": busiest_zones,
    }


def _policy_guidance_score(governance: dict[str, Any] | None) -> int:
    if not governance:
        return 84
    gate_status = str(governance.get("gate_status") or "")
    findings = governance.get("findings", [])
    finding_count = len(findings) if isinstance(findings, list) else 0
    if gate_status == "blocked":
        return max(35, 62 - finding_count * 4)
    if gate_status in {"review", "pending_operator_approval"}:
        return max(76, 90 - finding_count * 2)
    if gate_status == "clear":
        return max(88, 98 - finding_count)
    return 84


def _failure_reasons(evals: list[dict[str, Any]], gate_status: str, scenario_requires_human: bool) -> list[dict[str, Any]]:
    reasons = [
        {
            "dimension": item["label"],
            "score": item["score"],
            "reason": item["detail"],
        }
        for item in evals
        if int(item.get("score", 0) or 0) < 75
    ]
    if gate_status in {"blocked", "review", "pending_operator_approval"}:
        reasons.append(
            {
                "dimension": "Policy gate",
                "score": 0 if gate_status == "blocked" else 75,
                "reason": f"Runtime policy gate returned {gate_status}.",
            }
        )
    if scenario_requires_human:
        reasons.append(
            {
                "dimension": "Human approval",
                "score": 75,
                "reason": "Scenario requires operator review before treating the recommendation as autonomous.",
            }
        )
    return reasons
