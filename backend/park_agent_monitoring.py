from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace

from arize_config import get_arize_status
from bigquery_analytics import online_improvement_status
from gcp_trace_eval import get_gcp_trace_eval_status
from gemini_provider import get_gemini_agent_properties
from policy_engine import PolicyEngine
from policy_loader import get_policy_books, policy_reference_index, validate_policy_books


_tracer = trace.get_tracer("parkpulse.agent_monitoring")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _policy_books_by_id() -> dict[str, dict[str, Any]]:
    books: dict[str, dict[str, Any]] = {}
    for envelope in get_policy_books().get("policy_books", []) or []:
        content = envelope.get("content", {}) or {}
        book_id = content.get("policy_book_id") or envelope.get("source", "")
        books[book_id] = {
            "source": envelope.get("source", ""),
            "content": content,
        }
    return books


def _park_policy_index(books_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    park_book = books_by_id.get("parkpulse_governance_index", {}).get("content", {}) or {}
    boundary = park_book.get("system_boundary", {}) or {}
    return {
        "policy_book_id": park_book.get("policy_book_id", "parkpulse_governance_index"),
        "version": park_book.get("version", ""),
        "product_thesis": park_book.get("product_thesis", ""),
        "active_policy_books": park_book.get("active_policy_books", []),
        "decision_order": park_book.get("default_decision_order", []),
        "parkpulse_owns": boundary.get("parkpulse_owns", []),
        "human_operators_own": boundary.get("human_operators_own", []),
        "absolute_prohibitions": boundary.get("absolute_prohibitions_for_parkpulse", []),
    }


def _rules_by_ref(books_by_id: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    rules: dict[str, dict[str, Any]] = {}
    for book_id, envelope in books_by_id.items():
        content = envelope.get("content", {}) or {}
        for rule in content.get("decision_rules", []) or []:
            if isinstance(rule, dict) and rule.get("id"):
                rules[str(rule["id"])] = {
                    **rule,
                    "policy_book_id": book_id,
                    "source": envelope.get("source", ""),
                }
    return rules


def _monitoring_lanes(books_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    park_book = books_by_id.get("parkpulse_governance_index", {}).get("content", {}) or {}
    configured_lanes = park_book.get("monitoring_lanes", []) if isinstance(park_book, dict) else []
    rules_by_ref = _rules_by_ref(books_by_id)
    lanes: list[dict[str, Any]] = []

    for lane in configured_lanes:
        if not isinstance(lane, dict):
            continue
        ref = str(lane.get("primary_policy_ref", ""))
        rule = rules_by_ref.get(ref, {})
        book_id = str(lane.get("policy_book_id") or rule.get("policy_book_id") or "")
        lanes.append(
            {
                "area": str(lane.get("area", ref or book_id or "Policy")),
                "policy_book_id": book_id,
                "primary_policy_ref": ref,
                "policy_refs": [value for value in [ref, book_id] if value],
                "rule": rule.get("allowed_action") or rule.get("name") or lane.get("rule", "Policy rule is not resolved."),
                "condition": rule.get("condition", ""),
                "blocked_action": rule.get("blocked_action", ""),
                "required_evidence": rule.get("required_evidence", []),
                "human_review_if": rule.get("human_review_if", []),
                "eval_threshold": lane.get("eval_threshold", {}),
            }
        )

    if lanes:
        return lanes

    fallback_refs = [
        ("Safety", "ride_safety_policy_book", "PARK-SAFE-001"),
        ("Operations", "parkpulse_operations_policy_book", "PARK-OPS-001"),
        ("Experience", "guest_privacy_policy_book", "PARK-EXP-001"),
        ("Customer Care", "guest_privacy_policy_book", "PARK-CARE-001"),
    ]
    for area, book_id, ref in fallback_refs:
        rule = rules_by_ref.get(ref, {})
        lanes.append(
            {
                "area": area,
                "policy_book_id": book_id,
                "primary_policy_ref": ref,
                "policy_refs": [ref, book_id],
                "rule": rule.get("allowed_action") or rule.get("name") or "Fallback policy rule is not resolved.",
                "condition": rule.get("condition", ""),
                "blocked_action": rule.get("blocked_action", ""),
                "required_evidence": rule.get("required_evidence", []),
                "human_review_if": rule.get("human_review_if", []),
                "eval_threshold": {},
            }
        )
    return lanes


def _text_for_action(action: dict[str, Any]) -> str:
    values = [
        action.get("title", ""),
        action.get("expected_impact", ""),
        action.get("owner", ""),
        (action.get("park_action", {}) or {}).get("target", ""),
        (action.get("park_action", {}) or {}).get("action", ""),
    ]
    return " ".join(str(value).lower() for value in values)


def _engine_findings_for_lane(lane: dict[str, Any], engine_result: dict[str, Any], severity: str) -> list[str]:
    lane_refs = set(lane["policy_refs"])
    messages: list[str] = []
    for finding in engine_result.get("findings", []) or []:
        if finding.get("severity") != severity:
            continue
        finding_refs = set(finding.get("policy_refs", []) or [])
        if not finding_refs or finding_refs & lane_refs:
            message = str(finding.get("message", ""))
            if message and message not in messages:
                messages.append(message)
    return messages


def _lane_decision(lane: dict[str, Any], action: dict[str, Any], eval_result: dict[str, Any], known_refs: set[str], engine_result: dict[str, Any]) -> dict[str, Any]:
    action_policy = action.get("policy_compliance", {}) or {}
    action_refs = set(action_policy.get("policy_refs", []) or [])
    lane_refs = set(lane["policy_refs"])
    matched_refs = sorted(action_refs & lane_refs)
    unknown_refs = sorted(ref for ref in action_refs if ref not in known_refs)
    violations: list[str] = []
    warnings: list[str] = []

    for message in _engine_findings_for_lane(lane, engine_result, "block"):
        if message not in violations:
            violations.append(message)
    for message in _engine_findings_for_lane(lane, engine_result, "review"):
        if message not in warnings:
            warnings.append(message)

    if not action_refs:
        warnings.append("Action has no policy references attached.")
    elif not matched_refs and lane["area"] in {"Safety", "Operations"}:
        warnings.append("Action cites policy refs, but not this lane's preferred refs.")
    if unknown_refs:
        message = f"Unknown policy refs: {', '.join(unknown_refs)}"
        if message not in violations:
            violations.append(message)

    if violations:
        decision = "block"
    elif warnings:
        decision = "review"
    else:
        decision = "clear"

    return {
        "area": lane["area"],
        "decision": decision,
        "rule": lane["rule"],
        "condition": lane.get("condition", ""),
        "blocked_action": lane.get("blocked_action", ""),
        "required_evidence": lane.get("required_evidence", []),
        "human_review_if": lane.get("human_review_if", []),
        "policy_refs": lane["policy_refs"],
        "primary_policy_ref": lane.get("primary_policy_ref", ""),
        "policy_book_id": lane.get("policy_book_id", ""),
        "matched_action_refs": matched_refs,
        "unknown_action_refs": unknown_refs,
        "violations": violations,
        "warnings": warnings,
    }


def _action_supervision(
    action: dict[str, Any],
    eval_result: dict[str, Any],
    known_refs: set[str],
    lanes: list[dict[str, Any]],
    policy_engine: PolicyEngine,
    park_state: dict[str, Any],
    scenario: dict[str, Any],
) -> dict[str, Any]:
    engine_result = policy_engine.evaluate_action(action, park_state, eval_result, scenario)
    lanes = [_lane_decision(lane, action, eval_result, known_refs, engine_result) for lane in lanes]
    status = engine_result["status"]

    return {
        "action_id": action.get("action_id", action.get("title", "action")),
        "title": action.get("title", "ParkPulse action"),
        "owner": action.get("owner", "Park Ops"),
        "deadline_minutes": action.get("deadline_minutes"),
        "park_action": action.get("park_action", {}),
        "policy_status": status,
        "policy_refs": engine_result.get("policy_refs", []),
        "policy_engine": engine_result,
        "lanes": lanes,
    }


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _latest_decision_telemetry(latest_decisions: list[dict[str, Any]] | None) -> dict[str, Any]:
    if not latest_decisions:
        return {}
    latest = latest_decisions[0] if isinstance(latest_decisions[0], dict) else {}
    runtime = latest.get("runtimeTelemetry", {}) if isinstance(latest.get("runtimeTelemetry"), dict) else {}
    selected = latest.get("selectedAction", {}) if isinstance(latest.get("selectedAction"), dict) else {}
    return {
        "decision_id": latest.get("_id"),
        "created_at": latest.get("createdAt"),
        "recommended_action": latest.get("recommendedAction"),
        "selected_action": selected,
        "confidence_score": latest.get("confidenceScore"),
        "runtime": runtime.get("runtime"),
        "model": runtime.get("model"),
        "gemini_ready": runtime.get("geminiReady"),
        "attempted_gemini": runtime.get("attemptedGemini"),
        "performance_status": runtime.get("performanceStatus"),
        "response_latency_ms": runtime.get("responseLatencyMs"),
        "timeout_seconds": runtime.get("timeoutSeconds"),
        "errors": runtime.get("errors", []),
    }


def _gemini_performance(action_plan: dict[str, Any], latest_decisions: list[dict[str, Any]] | None, gcp_trace_eval: dict[str, Any]) -> dict[str, Any]:
    props = get_gemini_agent_properties().public_dict()
    latest = _latest_decision_telemetry(latest_decisions)
    timeout_seconds = _float_or_none(action_plan.get("timeout_seconds")) or _float_or_none(latest.get("timeout_seconds"))
    if timeout_seconds is None:
        timeout_seconds = _float_or_none(os.getenv("PARKPULSE_GEMINI_TIMEOUT_SECONDS")) or 22.0
    latency_ms = _int_or_none(action_plan.get("response_latency_ms")) or _int_or_none(latest.get("response_latency_ms"))
    errors = action_plan.get("errors") if isinstance(action_plan.get("errors"), list) else latest.get("errors", [])
    if not errors and not props.get("ready"):
        errors = props.get("readiness_issues", [])
    runtime = str(action_plan.get("runtime") or latest.get("runtime") or props.get("platform") or "")
    attempted = action_plan.get("attempted_gemini")
    if attempted is None:
        attempted = latest.get("attempted_gemini")
    if attempted is None:
        attempted = bool(props.get("ready"))
    status = str(action_plan.get("performance_status") or latest.get("performance_status") or "")
    if not status:
        if not props.get("ready"):
            status = "not_ready"
        elif runtime.startswith("deterministic_fallback"):
            status = "fallback"
        elif latest:
            status = "observed"
        else:
            status = "ready_no_run"

    timeout_ms = int(timeout_seconds * 1000)
    budget_used_pct = round((latency_ms / timeout_ms) * 100) if latency_ms is not None and timeout_ms > 0 else None
    latency_status = "unknown"
    if latency_ms is not None:
        latency_status = "slow" if budget_used_pct is not None and budget_used_pct >= 80 else "ok"

    return {
        "status": status,
        "provider": props.get("provider", ""),
        "platform": props.get("platform", ""),
        "model": action_plan.get("model") or latest.get("model") or props.get("model", ""),
        "project": props.get("project"),
        "location": props.get("location"),
        "ready": bool(props.get("ready")),
        "runtime": runtime or props.get("platform", ""),
        "attempted_gemini": bool(attempted),
        "latency_ms": latency_ms,
        "timeout_seconds": timeout_seconds,
        "latency_status": latency_status,
        "budget_used_pct": budget_used_pct,
        "confidence_score": action_plan.get("confidence_score") or latest.get("confidence_score") or 0,
        "candidate_count": len(action_plan.get("candidate_actions") or action_plan.get("recommended_actions") or []),
        "custom_mix_count": len(action_plan.get("custom_action_mixes") or []),
        "readiness_issues": props.get("readiness_issues", []),
        "errors": errors or [],
        "latest_decision": {
            "decision_id": latest.get("decision_id"),
            "created_at": latest.get("created_at"),
            "recommended_action": latest.get("recommended_action"),
            "selected_action": latest.get("selected_action"),
        },
        "gcp_monitor": {
            "trace_eval_ready": bool(gcp_trace_eval.get("ready")),
            "trace_project": gcp_trace_eval.get("trace_project"),
            "dataset": gcp_trace_eval.get("dataset"),
            "primary_path": gcp_trace_eval.get("primary_path"),
        },
    }


def build_park_agent_monitoring(
    park_state: dict[str, Any],
    action_plan: dict[str, Any],
    eval_result: dict[str, Any],
    signals: dict[str, Any],
    latest_decisions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    with _tracer.start_as_current_span("parkpulse.agent_monitoring.build") as span:
        books_by_id = _policy_books_by_id()
        loaded_policy_books = get_policy_books()
        policy_engine = PolicyEngine(loaded_policy_books)
        policy_integrity = validate_policy_books(loaded_policy_books)
        known_refs = set(policy_reference_index(loaded_policy_books).get("policy_refs", []))
        policy_index = _park_policy_index(books_by_id)
        policy_lanes = _monitoring_lanes(books_by_id)
        arize = get_arize_status().public_dict()
        online_improvement = online_improvement_status()
        gcp_trace_eval = get_gcp_trace_eval_status().public_dict()
        gemini_performance = _gemini_performance(action_plan, latest_decisions, gcp_trace_eval)
        actions = action_plan.get("recommended_actions", []) or []
        scorecard = eval_result.get("scorecard", {}) or {}
        scenario = action_plan.get("scenario", {}) or park_state.get("guestFlow", {}).get("activeScenario", {}) or {}
        supervised_actions = [_action_supervision(action, eval_result, known_refs, policy_lanes, policy_engine, park_state, scenario) for action in actions]
        blocked_count = sum(1 for action in supervised_actions if action["policy_status"] == "blocked")
        review_count = sum(1 for action in supervised_actions if action["policy_status"] == "review")
        clear_count = sum(1 for action in supervised_actions if action["policy_status"] == "clear")

        if blocked_count:
            overall_status = "blocked"
        elif review_count or scorecard.get("needs_human_approval"):
            overall_status = "review"
        else:
            overall_status = "clear"

        span.set_attribute("parkpulse.monitor.status", overall_status)
        span.set_attribute("parkpulse.monitor.action_count", len(supervised_actions))
        span.set_attribute("parkpulse.monitor.blocked_count", blocked_count)
        span.set_attribute("parkpulse.monitor.review_count", review_count)
        span.set_attribute("parkpulse.monitor.gcp_trace_eval_ready", bool(gcp_trace_eval.get("ready")))
        span.set_attribute("parkpulse.monitor.arize_ready", bool(arize.get("ready")))
        span.set_attribute("parkpulse.monitor.gcp_improvement_ready", bool(online_improvement.get("ready")))
        span.set_attribute("parkpulse.monitor.gemini_status", gemini_performance["status"])
        if gemini_performance.get("latency_ms") is not None:
            span.set_attribute("parkpulse.monitor.gemini_latency_ms", gemini_performance["latency_ms"])
        eval_trace = eval_result.get("gcp_trace_eval") or eval_result.get("arize_trace", {})

        return {
            "monitoring_id": f"PP-MON-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
            "created_at": _now_iso(),
            "domain": "amusement_park_operations",
            "overall_status": overall_status,
            "scenario": {
                "key": scenario.get("key", "ride_down"),
                "name": scenario.get("name") or scenario.get("title") or "ParkPulse scenario",
            },
            "summary": {
                "action_count": len(supervised_actions),
                "clear_count": clear_count,
                "review_count": review_count,
                "blocked_count": blocked_count,
                "policy_book_count": len(books_by_id),
                "gcp_trace_eval_ready": bool(gcp_trace_eval.get("ready")),
                "arize_ready": bool(arize.get("ready")),
                "gcp_improvement_ready": bool(online_improvement.get("ready")),
                "primary_improvement_loop": online_improvement.get("primary_path", "gcp_bigquery"),
                "overall_eval_score": scorecard.get("overall", 0),
                "needs_human_approval": bool(scorecard.get("needs_human_approval")),
                "open_signal_count": int(signals.get("count", 0) or 0),
            },
            "online_improvement": online_improvement,
            "gemini_performance": gemini_performance,
            "gcp_trace_eval": {
                "status": "primary_ready" if gcp_trace_eval.get("ready") else "local_preview",
                "platform": gcp_trace_eval.get("platform", "GCP internal trace/eval"),
                "mode": gcp_trace_eval.get("mode", "local_scorecard_with_gcp_export_preview"),
                "project": gcp_trace_eval.get("project"),
                "dataset": gcp_trace_eval.get("dataset"),
                "readiness_issues": gcp_trace_eval.get("readiness_issues", []),
                "eval_subject": "park_operations_action_plan",
                "dimensions": eval_trace.get("dimensions", []),
                "trace_lookup_query": eval_trace.get("trace_lookup_query"),
                "trace_url": eval_trace.get("trace_url"),
            },
            "arize_monitor": {
                "status": "optional_connected" if arize.get("ready") else "optional_disabled",
                "project_name": arize.get("project_name", ""),
                "collector_endpoint": arize.get("collector_endpoint", ""),
                "readiness_issues": arize.get("readiness_issues", []),
                "eval_subject": "park_operations_action_plan",
                "dimensions": eval_trace.get("dimensions", []),
                "trace_lookup_query": eval_trace.get("trace_lookup_query"),
                "trace_url": eval_trace.get("trace_url"),
            },
            "policy_index": policy_index,
            "policy_integrity": policy_integrity,
            "policy_lanes": policy_lanes,
            "supervised_actions": supervised_actions,
            "operator_checklist": [
                "Confirm every action has a ParkPulse target/action and owner.",
                "Block any action that violates ride safety, maintenance, weather, security, medical, or accessibility constraints.",
                "Confirm routing and promotions do not overload a destination zone.",
                "Confirm guest messages are honest and do not promise reopening, compensation, or individualized care without approval.",
                "Review the GCP internal trace/eval record after each agent run and preserve the decision ledger entry.",
            ],
        }
