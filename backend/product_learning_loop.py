from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from typing import Any


ISSUE_TYPES = {
    "angry_parent",
    "lost_child_report",
    "ride_closure_complaint",
    "accessibility_accommodation",
    "language_barrier",
    "refund_request",
    "heat_exhaustion_concern",
    "line_cutting_conflict",
    "safety_rule_refusal",
    "weather_evacuation_confusion",
}

ISSUE_TYPE_ALIASES = {
    "lost_child": "lost_child_report",
    "heat_exhaustion": "heat_exhaustion_concern",
    "accessibility_request": "accessibility_accommodation",
    "line_conflict": "line_cutting_conflict",
    "safety_refusal": "safety_rule_refusal",
    "weather_evacuation": "weather_evacuation_confusion",
}

TEAM_BY_ISSUE = {
    "lost_child_report": "security",
    "heat_exhaustion_concern": "first_aid",
    "accessibility_accommodation": "accessibility",
    "refund_request": "guest_services",
    "angry_parent": "guest_services",
    "ride_closure_complaint": "ride_ops",
    "line_cutting_conflict": "security",
    "safety_rule_refusal": "ride_ops",
    "weather_evacuation_confusion": "ops_lead",
    "language_barrier": "guest_services",
}

HIGH_RISK_ISSUES = {"lost_child_report", "heat_exhaustion_concern", "safety_rule_refusal", "weather_evacuation_confusion"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ledger_path() -> str:
    return os.getenv("PARKPULSE_PRODUCT_LEARNING_LOG_PATH", "/tmp/parkpulse/product_learning_loop.jsonl")


def _ensure_parent(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


def _write_event(event: dict[str, Any]) -> None:
    path = _ledger_path()
    _ensure_parent(path)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")


def _read_events(limit: int = 500) -> list[dict[str, Any]]:
    path = _ledger_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()[-max(1, min(5000, int(limit or 500))) :]
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _id(prefix: str, payload: dict[str, Any]) -> str:
    seed = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return f"{prefix}-" + hashlib.sha1(f"{seed}:{time.time()}".encode("utf-8")).hexdigest()[:14]


def _stable_id(prefix: str, payload: dict[str, Any]) -> str:
    seed = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return f"{prefix}-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:14]


def _normalize_issue_type(value: str | None) -> str:
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    normalized = ISSUE_TYPE_ALIASES.get(raw, raw)
    return normalized if normalized in ISSUE_TYPES else "angry_parent"


def _normalize_severity(value: str | None, issue_type: str) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"low", "medium", "high", "critical"}:
        return raw
    return "critical" if issue_type in HIGH_RISK_ISSUES else "medium"


def create_park_issue_ticket(
    *,
    source: str | None = None,
    issue_type: str | None = None,
    summary: str | None = None,
    severity: str | None = None,
    location: str | None = None,
    reporter_role: str | None = None,
    required_action: str | None = None,
    assigned_team: str | None = None,
) -> dict[str, Any]:
    normalized_source = str(source or "employee").strip().lower()
    if normalized_source not in {"guest", "employee"}:
        return {"status": "invalid", "mode": "park_issue_ticket", "readiness_issues": ["source must be guest or employee."]}
    normalized_issue = _normalize_issue_type(issue_type)
    normalized_severity = _normalize_severity(severity, normalized_issue)
    ticket = {
        "event": "park_issue_ticket_created",
        "id": _id("park-issue", {"source": normalized_source, "issue_type": normalized_issue, "summary": summary or ""}),
        "source": normalized_source,
        "issue_type": normalized_issue,
        "severity": normalized_severity,
        "location": str(location or "")[:120] or None,
        "reporter_role": str(reporter_role or normalized_source)[:80],
        "summary": str(summary or "Park issue reported.")[:1000],
        "required_action": str(required_action or _default_required_action(normalized_issue))[:500],
        "assigned_team": str(assigned_team or TEAM_BY_ISSUE.get(normalized_issue) or "ops_lead")[:80],
        "status": "new",
        "live_ops_authority": True,
        "requires_human_ack": normalized_severity in {"high", "critical"} or normalized_issue in HIGH_RISK_ISSUES,
        "created_at": _now_iso(),
        "boundary": "Real guest/employee issue ticket; high-risk actions require human acknowledgement before live dispatch.",
    }
    _write_event(ticket)
    return {"status": "created", "mode": "park_issue_ticket", "ticket": ticket, "feeds_training_model": "via_product_learning_signal_only"}


def _default_required_action(issue_type: str) -> str:
    return {
        "lost_child_report": "Route to Security/Ops and keep guardian at a meeting point.",
        "heat_exhaustion_concern": "Route to First Aid and keep guest seated in shade if safe.",
        "safety_rule_refusal": "Route to ride lead; do not start ride until compliant.",
        "weather_evacuation_confusion": "Route to ops lead and give a covered accessible shelter path.",
        "accessibility_accommodation": "Route to Accessibility or Guest Services while preserving privacy.",
        "refund_request": "Route to Guest Services for policy review.",
    }.get(issue_type, "Route to responsible owner and capture resolution receipt.")


def create_training_gap_ticket(
    *,
    scenario_id: str | None = None,
    gap_type: str | None = None,
    severity: str | None = None,
    evidence: dict[str, Any] | None = None,
    trainee_name: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    normalized_scenario = _normalize_issue_type(scenario_id)
    normalized_gap = str(gap_type or "policy_correctness").strip().lower().replace("-", "_").replace(" ", "_")
    normalized_severity = str(severity or "coaching").strip().lower()
    if normalized_severity not in {"coaching", "critical_training_gap"}:
        normalized_severity = "coaching"
    ticket = {
        "event": "training_gap_ticket_created",
        "id": _stable_id("training-gap", {"session_id": session_id or "", "scenario_id": normalized_scenario, "gap_type": normalized_gap, "severity": normalized_severity}),
        "source": "staff_roleplay",
        "session_id": str(session_id or "")[:120] or None,
        "trainee_name": str(trainee_name or "")[:120] or None,
        "scenario_id": normalized_scenario,
        "gap_type": normalized_gap,
        "severity": normalized_severity,
        "evidence": evidence or {},
        "status": "open",
        "live_ops_authority": False,
        "created_at": _now_iso(),
        "boundary": "Training gap only; cannot create live park issue, dispatch, refund, or reward-model label.",
    }
    _write_event(ticket)
    return {"status": "created", "mode": "training_gap_ticket", "ticket": ticket, "feeds_ops_model": "via_product_learning_signal_only"}


def record_training_gap_from_staff_session(session: dict[str, Any]) -> dict[str, Any]:
    scorecard = session.get("scorecard", {}) if isinstance(session.get("scorecard"), dict) else {}
    mastery = session.get("mastery_tracker", {}) if isinstance(session.get("mastery_tracker"), dict) else {}
    debrief = session.get("debrief", {}) if isinstance(session.get("debrief"), dict) else {}
    open_gaps = mastery.get("open_gaps", []) if isinstance(mastery.get("open_gaps"), list) else []
    critical = bool(session.get("critical_miss") or mastery.get("unrepaired_critical_count"))
    if debrief.get("result") == "pass" and not critical and not open_gaps:
        return {"status": "skipped", "mode": "training_gap_ticket", "reason": "session_passed_without_open_gap"}
    dimensions = scorecard.get("dimensions", {}) if isinstance(scorecard.get("dimensions"), dict) else {}
    weakest = sorted(dimensions.items(), key=lambda item: float(item[1] if isinstance(item[1], (int, float)) else 99))
    first_gap = next((item for item in open_gaps if isinstance(item, dict)), {})
    gap_type = str(first_gap.get("type") or (weakest[0][0] if weakest else "policy_correctness"))
    evidence = {
        "score": scorecard.get("overall", 0),
        "critical_miss": bool(session.get("critical_miss")),
        "open_gaps": [str(item.get("label") or item.get("signal") or "") for item in open_gaps if isinstance(item, dict)][:8],
        "repaired_gaps": [str(item.get("label") or item.get("signal") or "") for item in (mastery.get("repaired_gaps", []) if isinstance(mastery.get("repaired_gaps"), list) else [])][:8],
        "mastery_level": mastery.get("mastery_level"),
        "transcript_excerpt": _employee_excerpt(session),
    }
    return create_training_gap_ticket(
        scenario_id=str(session.get("scenario_id") or ""),
        gap_type=gap_type,
        severity="critical_training_gap" if critical else "coaching",
        evidence=evidence,
        trainee_name=str(session.get("trainee_name") or ""),
        session_id=str(session.get("id") or ""),
    )


def _employee_excerpt(session: dict[str, Any]) -> str:
    transcript = session.get("transcript", []) if isinstance(session.get("transcript"), list) else []
    messages = [str(turn.get("message") or "") for turn in transcript if isinstance(turn, dict) and turn.get("speaker") == "employee"]
    return " / ".join(messages[-2:])[:800]


def _derive_product_learning_signals(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    park_tickets = [row for row in events if row.get("event") == "park_issue_ticket_created"]
    training_gaps = [row for row in events if row.get("event") == "training_gap_ticket_created"]
    signals: list[dict[str, Any]] = []
    for issue_type in sorted({str(row.get("issue_type") or "") for row in park_tickets if row.get("issue_type")}):
        group = [row for row in park_tickets if row.get("issue_type") == issue_type]
        signals.append(_signal("park_issue_ticket", issue_type, "scenario_undertrained", len(group), "new_scenario", f"Review real {issue_type.replace('_', ' ')} tickets and update the matching training scenario."))
    for scenario_id in sorted({str(row.get("scenario_id") or "") for row in training_gaps if row.get("scenario_id")}):
        group = [row for row in training_gaps if row.get("scenario_id") == scenario_id]
        gap_types = sorted({str(row.get("gap_type") or "unknown") for row in group})
        signals.append(_signal("training_gap_ticket", scenario_id, "common_escalation_miss" if "escalation" in " ".join(gap_types) else "policy_confusion", len(group), "ops_policy_clarification", f"Use training gaps in {scenario_id.replace('_', ' ')} to tighten live ops prompts/checklists."))
    issue_types = {str(row.get("issue_type") or "") for row in park_tickets}
    scenario_ids = {str(row.get("scenario_id") or "") for row in training_gaps}
    for shared in sorted(issue_types & scenario_ids):
        signals.append(_signal("manager_review", shared, "manager_override_pattern", 2, "update_scoring_rubric", f"Real tickets and training gaps both mention {shared.replace('_', ' ')}; review scenario, rubric, and ops checklist together."))
    return signals


def _signal(source: str, scenario: str, pattern: str, count: int, change_type: str, recommendation: str) -> dict[str, Any]:
    payload = {"source": source, "scenario": scenario, "pattern": pattern, "change_type": change_type}
    return {
        "id": _stable_id("learning-signal", payload),
        "source": source,
        "pattern": pattern,
        "affected_scenarios": [scenario],
        "evidence_count": count,
        "recommendation": recommendation,
        "proposed_change_type": change_type,
        "status": "candidate",
        "requires_review": True,
        "boundary": "Product learning signal only; requires review/golden eval before training or ops behavior changes.",
    }


def product_learning_loop_status(limit: int = 500) -> dict[str, Any]:
    events = _read_events(limit)
    park_tickets = [row for row in events if row.get("event") == "park_issue_ticket_created"]
    training_gaps = [row for row in events if row.get("event") == "training_gap_ticket_created"]
    signals = _derive_product_learning_signals(events)
    return {
        "status": "ready",
        "mode": "product_learning_loop",
        "park_issue_ticket_count": len(park_tickets),
        "training_gap_ticket_count": len(training_gaps),
        "learning_signal_count": len(signals),
        "park_issue_tickets": park_tickets[-80:],
        "training_gap_tickets": training_gaps[-80:],
        "product_learning_signals": signals[-120:],
        "loop_contract": {
            "live_tickets_improve_training": "via reviewed ProductLearningSignal and golden eval only",
            "training_gaps_help_ops": "via reviewed checklist/prompt candidates only",
            "training_gaps_create_live_issues": False,
            "llm_guest_controls_score": False,
            "simulated_data_feeds_reward_model": False,
        },
        "boundary": "Separates live operational tickets from simulated training gaps; both can produce reviewed product-learning signals.",
    }
