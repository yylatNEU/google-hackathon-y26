from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from typing import Any


RUBRIC_DIMENSIONS = [
    "empathy",
    "policy_correctness",
    "escalation_decision",
    "clarity",
    "safety_awareness",
    "de_escalation",
    "brand_tone",
]

_SESSIONS: dict[str, dict[str, Any]] = {}

STAFF_ROLE_ASSIGNMENT_SCENARIOS = {
    "guest_services": ["angry_parent", "refund_request", "accessibility_accommodation", "language_barrier"],
    "ride_ops": ["ride_closure_complaint", "safety_rule_refusal", "line_cutting_conflict", "weather_evacuation_confusion"],
    "entry": ["language_barrier", "lost_child_report", "refund_request"],
    "security": ["lost_child_report", "line_cutting_conflict", "weather_evacuation_confusion"],
    "food": ["heat_exhaustion_concern", "refund_request", "line_cutting_conflict"],
}

STAFF_TRAINING_REVIEW_DECISIONS = {"approve_shadowing", "require_retry", "hold"}

DEMO_TRAINEES = [
    {
        "trainee_name": "Maya Chen",
        "staff_role": "guest_services",
        "scenario_id": "lost_child_report",
        "scorecard": {"overall": 91, "dimensions": {"empathy": 4.4, "policy_correctness": 4.5, "escalation_decision": 5, "clarity": 4.5, "safety_awareness": 5, "de_escalation": 4.5, "brand_tone": 4.5}, "turn_count": 2},
        "critical_miss": False,
    },
    {
        "trainee_name": "Jon Bell",
        "staff_role": "ride_ops",
        "scenario_id": "safety_rule_refusal",
        "scorecard": {"overall": 58, "dimensions": {"empathy": 2.5, "policy_correctness": 3, "escalation_decision": 2, "clarity": 3, "safety_awareness": 2, "de_escalation": 3, "brand_tone": 3.5}, "turn_count": 2},
        "critical_miss": True,
    },
    {
        "trainee_name": "Priya Nair",
        "staff_role": "entry",
        "scenario_id": "language_barrier",
        "scorecard": {"overall": 73, "dimensions": {"empathy": 3.5, "policy_correctness": 3.5, "escalation_decision": 3, "clarity": 4, "safety_awareness": 3.5, "de_escalation": 4, "brand_tone": 4}, "turn_count": 3},
        "critical_miss": False,
    },
]

_EMPATHY_TERMS = (
    "sorry",
    "i understand",
    "understand",
    "frustrating",
    "worried",
    "scary",
    "help",
    "thank you",
    "stay with",
    "we will",
)
_CLARITY_TERMS = ("first", "next", "now", "please", "where", "when", "what", "who", "stay", "meet", "follow")
_DEESCALATION_TERMS = ("calm", "step", "safe", "together", "right now", "i can", "we can", "stay here", "work through")
_RUDE_TERMS = ("calm down", "not my problem", "can't help", "deal with", "your fault", "stop yelling", "whatever")


SCENARIOS: dict[str, dict[str, Any]] = {
    "angry_parent": {
        "id": "angry_parent",
        "title": "Angry Parent At Guest Services",
        "category": "Guest Recovery",
        "difficulty": "medium",
        "guest_role": "angry parent",
        "opening_message": "This is ridiculous. My kid has been crying for twenty minutes because your staff sent us to a closed ride.",
        "context": "A parent is angry after a ride closure reroute failed. They want acknowledgement, a clear next step, and a supervisor if compensation is requested.",
        "objectives": ["Acknowledge the impact", "Confirm what happened", "Offer a concrete next step", "Escalate refund or compensation decisions"],
        "policy_keywords": [["sorry", "understand", "frustrating"], ["ride", "closed", "what happened", "confirm"], ["next", "option", "guest services"], ["supervisor", "lead", "manager", "guest services"]],
        "safety_keywords": [["child", "kid", "family"], ["safe", "together", "stay"]],
        "escalation_keywords": [["supervisor", "lead", "manager", "guest services"]],
        "guest_followups": [
            "I do not want a vague apology. What are you actually going to do for us?",
            "Are you saying you cannot fix this without a manager?",
            "Fine, but I need you to be clear with my family about where we go now.",
        ],
        "prohibited_terms": ["nothing i can do", "not my problem", "read the sign"],
    },
    "lost_child_report": {
        "id": "lost_child_report",
        "title": "Lost Child Report",
        "category": "Safety",
        "difficulty": "critical",
        "guest_role": "panicked guardian",
        "opening_message": "I cannot find my six-year-old. She was next to me near the carousel and now she is gone.",
        "context": "A guardian reports a missing child. Staff must show empathy, collect key details, keep the guardian reachable, and escalate immediately to security/ops.",
        "objectives": ["Reassure without minimizing", "Collect child description and last seen location", "Keep guardian at a meeting point", "Escalate to security immediately"],
        "policy_keywords": [["sorry", "help", "right now"], ["description", "wearing", "name", "age"], ["last seen", "carousel", "location"], ["stay", "meeting", "here"], ["security", "supervisor", "operations", "radio"]],
        "safety_keywords": [["security", "radio", "operations"], ["stay", "meeting", "here"], ["description", "wearing", "age"]],
        "escalation_keywords": [["security", "radio", "operations", "supervisor"]],
        "guest_followups": [
            "Why are you asking questions? Shouldn't someone already be looking?",
            "She has a pink shirt and light-up shoes. What do I do while you call someone?",
            "Please do not make me run around the park alone.",
        ],
        "fatal_if_missing_after_turn": 1,
        "prohibited_terms": ["go look", "search yourself", "wait and see", "probably fine"],
    },
    "ride_closure_complaint": {
        "id": "ride_closure_complaint",
        "title": "Ride Closure Complaint",
        "category": "Ride Ops",
        "difficulty": "medium",
        "guest_role": "disappointed coaster fan",
        "opening_message": "We paid for tickets mostly for Dragon Coaster, and now it is closed. Nobody told us before we waited.",
        "context": "Guest complains about a closure. Staff should acknowledge, avoid unsafe reopen promises, explain available updates, and offer alternatives.",
        "objectives": ["Acknowledge wait impact", "Avoid promising reopen time", "Offer live alternatives", "Direct refund/compensation to approved channel"],
        "policy_keywords": [["sorry", "understand", "frustrating"], ["cannot promise", "no exact", "updates", "temporary"], ["alternative", "nearby", "theater", "arcade"], ["guest services", "supervisor", "refund"]],
        "safety_keywords": [["cannot promise", "safety", "clearance"], ["updates", "temporary"]],
        "escalation_keywords": [["guest services", "supervisor", "lead"]],
        "guest_followups": [
            "So when exactly will it reopen?",
            "I do not want another ride. I want someone to make this right.",
            "At least tell us where to go without wasting more time.",
        ],
        "prohibited_terms": ["it will reopen", "definitely open", "ignore the closure"],
    },
    "accessibility_accommodation": {
        "id": "accessibility_accommodation",
        "title": "Accessibility Accommodation Request",
        "category": "Accessibility",
        "difficulty": "high",
        "guest_role": "guest requesting mobility accommodation",
        "opening_message": "My father cannot stand in this sun for the whole queue. We need help, but I do not want to explain his medical history in public.",
        "context": "A party requests accessibility support. Staff must preserve dignity, avoid medical probing, explain available assistance, and escalate to accessibility/guest services.",
        "objectives": ["Respect privacy", "Offer accessible route or waiting support", "Avoid asking for diagnosis", "Escalate to accessibility support"],
        "policy_keywords": [["privacy", "private", "do not need medical"], ["accessible", "mobility", "route", "seating", "shade"], ["guest services", "accessibility", "support"], ["dignity", "respect"]],
        "safety_keywords": [["shade", "seating", "sun", "heat"], ["accessible", "mobility", "route"]],
        "escalation_keywords": [["guest services", "accessibility", "supervisor", "lead"]],
        "guest_followups": [
            "Are you going to make him prove his condition?",
            "He needs shade or a place to sit while we figure this out.",
            "Who can actually approve the accommodation?",
        ],
        "prohibited_terms": ["prove", "diagnosis", "medical records", "handicapped"],
    },
    "language_barrier": {
        "id": "language_barrier",
        "title": "Language Barrier At Entry",
        "category": "Guest Support",
        "difficulty": "medium",
        "guest_role": "confused multilingual family",
        "opening_message": "No English good. Ticket problem. Family inside? We do not understand where to go.",
        "context": "A guest has a language barrier and possible party separation. Staff should simplify, use translation resources, confirm safety, and guide one step at a time.",
        "objectives": ["Use simple language", "Offer translation support", "Confirm party status", "Give one clear next step"],
        "policy_keywords": [["translator", "translation", "language", "interpreter"], ["family", "party", "inside", "together"], ["one step", "follow", "stay", "here"], ["ticket", "entry", "guest services"]],
        "safety_keywords": [["family", "together", "inside"], ["stay", "here"]],
        "escalation_keywords": [["guest services", "lead", "translator", "interpreter"]],
        "guest_followups": [
            "Family inside. We have phone but do not understand app.",
            "Can you show us, not only say words?",
            "We are worried we are separated.",
        ],
        "prohibited_terms": ["speak english", "figure it out", "not understand you"],
    },
    "refund_request": {
        "id": "refund_request",
        "title": "Refund Request",
        "category": "Guest Recovery",
        "difficulty": "medium",
        "guest_role": "upset purchaser",
        "opening_message": "I want a refund now. The ride was closed, the food line was terrible, and this day is not what we paid for.",
        "context": "Guest requests refund. Staff should empathize, avoid unauthorized promises, gather context, and route to Guest Services or supervisor.",
        "objectives": ["Acknowledge frustration", "Avoid promising refund", "Collect issue summary", "Escalate through approved channel"],
        "policy_keywords": [["sorry", "understand", "frustrating"], ["cannot promise", "review", "policy"], ["what happened", "receipt", "ticket", "details"], ["guest services", "supervisor", "manager"]],
        "safety_keywords": [["calm", "safe", "help"], ["guest services", "supervisor"]],
        "escalation_keywords": [["guest services", "supervisor", "manager"]],
        "guest_followups": [
            "Do not tell me policy. Are you refunding me or not?",
            "What information do you need?",
            "Then get me someone who can make the decision.",
        ],
        "prohibited_terms": ["full refund guaranteed", "cash now", "nothing i can do"],
    },
    "heat_exhaustion_concern": {
        "id": "heat_exhaustion_concern",
        "title": "Heat Exhaustion Concern",
        "category": "Safety",
        "difficulty": "critical",
        "guest_role": "concerned friend",
        "opening_message": "My friend is dizzy and looks pale. We have been in the sun for an hour and she says she might faint.",
        "context": "Possible heat exhaustion. Staff must prioritize safety, move to shade if safe, call first aid/medical, and avoid medical diagnosis.",
        "objectives": ["Treat as urgent", "Call first aid or medical", "Move to shade/cooling if safe", "Avoid diagnosis or delay"],
        "policy_keywords": [["first aid", "medical", "nurse", "call"], ["shade", "cool", "water", "sit"], ["do not move", "if safe", "stay"], ["right now", "urgent"]],
        "safety_keywords": [["first aid", "medical", "nurse"], ["shade", "cool", "water"], ["faint", "dizzy", "urgent"]],
        "escalation_keywords": [["first aid", "medical", "nurse", "call", "radio"]],
        "guest_followups": [
            "Should I walk her to the front or wait here?",
            "She is embarrassed and says she is fine, but she looks worse.",
            "Please call someone now.",
        ],
        "fatal_if_missing_after_turn": 1,
        "prohibited_terms": ["walk it off", "probably fine", "wait in line", "not serious"],
    },
    "line_cutting_conflict": {
        "id": "line_cutting_conflict",
        "title": "Line-Cutting Conflict",
        "category": "Crowd Conflict",
        "difficulty": "high",
        "guest_role": "angry guest in queue",
        "opening_message": "Those people cut the entire line. If you do not do something, I am going to handle it myself.",
        "context": "Queue conflict with possible escalation. Staff should acknowledge, separate tension, avoid blame, call lead/security if needed, and keep the queue moving safely.",
        "objectives": ["Acknowledge concern", "Discourage confrontation", "Call lead/security if threat escalates", "Investigate without public blame"],
        "policy_keywords": [["understand", "frustrating", "help"], ["do not confront", "stay", "safe"], ["lead", "security", "supervisor"], ["check", "look into", "queue"]],
        "safety_keywords": [["safe", "do not confront", "stay"], ["security", "lead", "supervisor"]],
        "escalation_keywords": [["security", "lead", "supervisor"]],
        "guest_followups": [
            "So you are just letting them get away with it?",
            "I am not calming down unless someone steps in.",
            "Can you check without making this a fight?",
        ],
        "prohibited_terms": ["go confront", "fight", "push", "handle it yourself"],
    },
    "safety_rule_refusal": {
        "id": "safety_rule_refusal",
        "title": "Guest Refusing Safety Rule",
        "category": "Ride Safety",
        "difficulty": "critical",
        "guest_role": "defiant ride guest",
        "opening_message": "I am not taking off my loose backpack strap. I have ridden like this before. Just start the ride.",
        "context": "Guest refuses a ride safety rule. Staff must stay firm, explain safety requirement, avoid bargaining, and escalate to ride lead/security if refusal continues.",
        "objectives": ["State rule clearly", "Do not start ride unless compliant", "Explain safety reason", "Escalate persistent refusal"],
        "policy_keywords": [["safety", "rule", "requirement"], ["cannot start", "cannot ride", "before"], ["secure", "remove", "strap", "locker"], ["lead", "supervisor", "security"]],
        "safety_keywords": [["cannot start", "cannot ride"], ["secure", "remove", "strap"], ["safety", "rule"]],
        "escalation_keywords": [["lead", "supervisor", "security"]],
        "guest_followups": [
            "You are holding up the line over a strap?",
            "What if I just hold it down?",
            "Get your lead then, because this is absurd.",
        ],
        "fatal_if_missing_after_turn": 1,
        "prohibited_terms": ["just this once", "go ahead", "start the ride", "ignore it"],
    },
    "weather_evacuation_confusion": {
        "id": "weather_evacuation_confusion",
        "title": "Weather Evacuation Confusion",
        "category": "Weather Response",
        "difficulty": "high",
        "guest_role": "confused family during storm hold",
        "opening_message": "The alert says move to shelter, but everyone is walking different directions. We have a stroller and do not know where to go.",
        "context": "Storm shelter movement. Staff should give calm clear route, preserve accessibility, avoid panic language, and direct to assigned shelter/lead.",
        "objectives": ["Use calm evacuation language", "Give specific shelter route", "Preserve accessible/stroller route", "Escalate blocked-route or lightning risk"],
        "policy_keywords": [["shelter", "indoor", "covered"], ["follow", "route", "this way", "left", "right"], ["stroller", "accessible", "ramp"], ["lead", "staff", "weather"]],
        "safety_keywords": [["shelter", "indoor", "covered"], ["stroller", "accessible", "ramp"], ["weather", "lightning", "safe"]],
        "escalation_keywords": [["lead", "staff", "security", "operations"]],
        "guest_followups": [
            "Which shelter exactly? We cannot use stairs with the stroller.",
            "People are running and it is making my kids scared.",
            "Can someone guide us instead of pointing?",
        ],
        "prohibited_terms": ["run", "panic", "everybody evacuate now", "take the stairs"],
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _session_log_path() -> str:
    return os.getenv("PARKPULSE_STAFF_TRAINING_LOG_PATH", "/tmp/parkpulse/staff_training_sessions.jsonl")


def _write_jsonl(row: dict[str, Any]) -> None:
    path = _session_log_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def _read_jsonl(limit: int = 200) -> list[dict[str, Any]]:
    path = _session_log_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()[-max(1, min(2000, int(limit or 200))) :]
    except Exception:
        return []
    rows = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _read_training_events(limit: int = 2000) -> list[dict[str, Any]]:
    return _read_jsonl(limit=max(1, min(5000, int(limit or 2000))))


def _public_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": scenario["id"],
        "title": scenario["title"],
        "category": scenario["category"],
        "difficulty": scenario["difficulty"],
        "guest_role": scenario["guest_role"],
        "opening_message": scenario["opening_message"],
        "context": scenario["context"],
        "objectives": scenario["objectives"],
    }


def list_staff_training_scenarios() -> dict[str, Any]:
    scenarios = [_public_scenario(item) for item in SCENARIOS.values()]
    return {
        "status": "ready",
        "mode": "staff_roleplay_scenario_catalog",
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
        "rubric_dimensions": RUBRIC_DIMENSIONS,
        "boundary": "Roleplay data is simulated staff training evidence. It is not fed into live operations dispatch or the actual outcome reward model.",
        "uses_generated_data": True,
        "feeds_actual_reward_model": False,
        "llm_guest_mode": {
            "available_when_configured": True,
            "request_fields": ["use_llm_guest", "useLlmGuest"],
            "fallback": "deterministic_guest_reply",
            "llm_controls_score": False,
        },
        "llm_control_authority": False,
    }


def staff_training_policy_pack() -> dict[str, Any]:
    scenarios = [_public_scenario(item) for item in SCENARIOS.values()]
    return {
        "status": "ready",
        "mode": "staff_roleplay_policy_pack",
        "id": "parkpulse_staff_roleplay_training_v1",
        "title": "ParkPulse Staff Roleplay Training Policy Pack",
        "scenario_count": len(scenarios),
        "rubric_dimensions": RUBRIC_DIMENSIONS,
        "scenario_categories": sorted({str(item.get("category") or "Uncategorized") for item in SCENARIOS.values()}),
        "critical_scenarios": [
            item["id"]
            for item in SCENARIOS.values()
            if item.get("difficulty") == "critical" or item.get("fatal_if_missing_after_turn") is not None
        ],
        "scenarios": scenarios,
        "scoring_contract": {
            "authority": "deterministic_policy_and_safety_rubric",
            "llm_controls_score": False,
            "fatal_miss_caps_score": True,
            "dimensions": RUBRIC_DIMENSIONS,
        },
        "llm_guest_contract": {
            "allowed": "Generate only guest-side roleplay replies when configured.",
            "not_allowed": [
                "score employee turns",
                "reveal rubric internals",
                "approve refunds or accommodations",
                "resolve safety incidents",
                "dispatch live park actions",
            ],
            "fallback": "deterministic_guest_reply",
        },
        "data_boundary": {
            "uses_generated_data": True,
            "feeds_actual_reward_model": False,
            "writes_live_dispatch": False,
            "contains_guest_pii": False,
            "training_labels_source": "deterministic rubric over simulated staff responses",
        },
        "manager_review": {
            "recommended_metrics": [
                "critical_miss_rate",
                "weakest_rubric_dimension",
                "scenario_average_score",
                "coach_and_retry_count",
            ],
            "minimum_live_shadowing_gate": "No critical miss and overall score at least 75.",
        },
    }


def create_staff_training_assignment(
    trainee_name: str | None = None,
    staff_role: str | None = None,
    scenario_ids: list[str] | None = None,
    assigned_by: str | None = None,
) -> dict[str, Any]:
    role = _normalize_staff_role(staff_role)
    requested = [str(item or "").strip() for item in (scenario_ids or [])]
    valid_requested = [item for item in requested if item in SCENARIOS]
    assigned_scenarios = valid_requested or list(STAFF_ROLE_ASSIGNMENT_SCENARIOS.get(role) or STAFF_ROLE_ASSIGNMENT_SCENARIOS["guest_services"])
    assignment_id = "staff-assign-" + hashlib.sha1(f"{trainee_name or ''}:{role}:{','.join(assigned_scenarios)}:{time.time()}".encode("utf-8")).hexdigest()[:14]
    assignment = {
        "event": "assignment_created",
        "id": assignment_id,
        "assignment_id": assignment_id,
        "trainee_name": str(trainee_name or "Seasonal staff trainee")[:80],
        "staff_role": role,
        "scenario_ids": assigned_scenarios,
        "assigned_by": str(assigned_by or "ParkPulse manager")[:80],
        "status": "assigned",
        "created_at": _now_iso(),
        "boundary": "Training assignment only; does not dispatch live work or create actual reward labels.",
    }
    _write_jsonl(assignment)
    return {
        "status": "created",
        "mode": "staff_roleplay_assignment",
        "assignment": _assignment_response(assignment),
        "uses_generated_data": True,
        "feeds_actual_reward_model": False,
    }


def list_staff_training_assignments(limit: int = 200) -> dict[str, Any]:
    events = _read_training_events(limit)
    assignments = [_assignment_response(row) for row in events if row.get("event") == "assignment_created"]
    readiness = _readiness_by_assignment(events)
    for assignment in assignments:
        status = readiness.get(str(assignment.get("id") or ""))
        if status:
            assignment.update(
                {
                    "status": status.get("status"),
                    "completed_count": status.get("completed_count"),
                    "required_count": status.get("required_count"),
                    "last_score": status.get("last_score"),
                    "critical_miss_count": status.get("critical_miss_count"),
                }
            )
    return {
        "status": "ready" if assignments else "empty",
        "mode": "staff_roleplay_assignments",
        "assignment_count": len(assignments),
        "assignments": assignments[-max(1, min(200, int(limit or 200))) :],
        "role_templates": _role_templates(),
        "boundary": "Assignments are manager training workflow records only.",
        "uses_generated_data": True,
        "feeds_actual_reward_model": False,
    }


def staff_training_readiness(limit: int = 500) -> dict[str, Any]:
    events = _read_training_events(limit)
    assignments = [_assignment_response(row) for row in events if row.get("event") == "assignment_created"]
    status_by_assignment = _readiness_by_assignment(events)
    rows = []
    for assignment in assignments:
        assignment_id = str(assignment.get("id") or "")
        status = status_by_assignment.get(assignment_id) or _assignment_readiness(assignment, [])
        rows.append(status)
    rows = rows[-max(1, min(300, int(limit or 500))) :]
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row.get("status") or "unknown")] = counts.get(str(row.get("status") or "unknown"), 0) + 1
    return {
        "status": "ready" if rows else "empty",
        "mode": "staff_roleplay_readiness",
        "trainee_count": len(rows),
        "status_counts": counts,
        "readiness": rows,
        "minimum_live_shadowing_gate": "No critical miss and overall score at least 75 on every assigned scenario.",
        "boundary": "Readiness gates live shadowing only after manager review; this does not authorize live dispatch.",
        "uses_generated_data": True,
        "feeds_actual_reward_model": False,
    }


def staff_training_receipts(limit: int = 80) -> dict[str, Any]:
    events = _read_training_events(limit=max(500, int(limit or 80) * 8))
    finished = [row for row in events if row.get("event") == "session_finished"]
    reviews = _latest_reviews_by_session(events)
    receipts = [_receipt_response(row, reviews.get(str(row.get("id") or row.get("session_id") or ""))) for row in finished[-max(1, min(200, int(limit or 80))) :]]
    return {
        "status": "ready" if receipts else "empty",
        "mode": "staff_roleplay_receipts",
        "receipt_count": len(receipts),
        "receipts": receipts,
        "boundary": "Receipts are manager review evidence from simulated roleplay only.",
        "uses_generated_data": True,
        "feeds_actual_reward_model": False,
    }


def staff_training_certification_packet(assignment_id: str | None = None, trainee_name: str | None = None) -> dict[str, Any]:
    events = _read_training_events()
    assignments = [_assignment_response(row) for row in events if row.get("event") == "assignment_created"]
    assignment = _find_assignment(assignments, assignment_id=assignment_id, trainee_name=trainee_name)
    if not assignment:
        return {
            "status": "not_found",
            "mode": "staff_roleplay_certification_packet",
            "readiness_issues": ["Training assignment was not found."],
        }

    reviews = _latest_reviews_by_session(events)
    finished = [row for row in events if row.get("event") == "session_finished" and str(row.get("assignment_id") or "") == str(assignment.get("id") or "")]
    readiness = _assignment_readiness(assignment, finished, reviews)
    receipts = [_receipt_response(row, reviews.get(str(row.get("id") or row.get("session_id") or ""))) for row in finished]
    packet_status = "eligible_for_manager_signoff" if readiness.get("status") == "ready_for_shadowing" else "blocked"
    packet_id = "staff-cert-" + hashlib.sha1(str(assignment.get("id") or "").encode("utf-8")).hexdigest()[:14]
    return {
        "status": "ready",
        "mode": "staff_roleplay_certification_packet",
        "id": packet_id,
        "assignment": assignment,
        "readiness": readiness,
        "receipts": receipts,
        "packet_status": packet_status,
        "manager_signoff_required": True,
        "next_actions": _packet_next_actions(assignment, readiness, receipts),
        "gate_contract": {
            "minimum_live_shadowing_gate": "No critical miss and overall score at least 75 on every assigned scenario.",
            "manager_review_can_override_score": False,
            "manager_review_can_hold_or_require_retry": True,
        },
        "boundary": "Certification packet summarizes simulated training evidence only; it does not dispatch live work, approve compensation, promote models, or create reward labels.",
        "uses_generated_data": True,
        "feeds_actual_reward_model": False,
        "writes_live_dispatch": False,
    }


def review_staff_training_receipt(
    session_id: str | None = None,
    receipt_id: str | None = None,
    decision: str | None = None,
    reviewer: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    normalized_decision = str(decision or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized_decision == "approve":
        normalized_decision = "approve_shadowing"
    if normalized_decision not in STAFF_TRAINING_REVIEW_DECISIONS:
        return {
            "status": "invalid",
            "mode": "staff_roleplay_receipt_review",
            "readiness_issues": ["Review decision must be approve_shadowing, require_retry, or hold."],
        }

    events = _read_training_events()
    finished = [row for row in events if row.get("event") == "session_finished"]
    target = _find_receipt_target(finished, session_id=session_id, receipt_id=receipt_id)
    if not target:
        return {
            "status": "not_found",
            "mode": "staff_roleplay_receipt_review",
            "readiness_issues": ["Training receipt was not found."],
        }

    target_session_id = str(target.get("id") or target.get("session_id") or "")
    review_id = "staff-review-" + hashlib.sha1(f"{target_session_id}:{normalized_decision}:{time.time()}".encode("utf-8")).hexdigest()[:14]
    review = {
        "event": "receipt_reviewed",
        "id": review_id,
        "review_id": review_id,
        "receipt_id": _receipt_id(target_session_id),
        "session_id": target_session_id,
        "assignment_id": target.get("assignment_id"),
        "trainee_name": target.get("trainee_name") or "Seasonal staff trainee",
        "scenario_id": target.get("scenario_id"),
        "decision": normalized_decision,
        "reviewer": str(reviewer or "ParkPulse manager")[:80],
        "notes": str(notes or "")[:500],
        "created_at": _now_iso(),
        "boundary": "Manager review disposition only; it does not alter deterministic score, live dispatch, or reward labels.",
        "uses_generated_data": True,
        "feeds_actual_reward_model": False,
    }
    _write_jsonl(review)
    return {
        "status": "recorded",
        "mode": "staff_roleplay_receipt_review",
        "review": _review_response(review),
        "receipt": _receipt_response(target, review),
        "readiness": staff_training_readiness(),
        "uses_generated_data": True,
        "feeds_actual_reward_model": False,
    }


def seed_staff_training_demo_data() -> dict[str, Any]:
    events = _read_training_events()
    if any(row.get("event") == "demo_seeded" for row in events):
        return {
            "status": "already_seeded",
            "mode": "staff_roleplay_demo_seed",
            "message": "Demo staff training data already exists.",
            "readiness": staff_training_readiness(),
        }

    created_assignments = []
    created_receipts = []
    for item in DEMO_TRAINEES:
        assignment = create_staff_training_assignment(
            item["trainee_name"],
            item["staff_role"],
            [item["scenario_id"]],
            assigned_by="Demo manager",
        )["assignment"]
        receipt = _demo_finished_session(item, assignment)
        _write_jsonl(receipt)
        created_assignments.append(assignment)
        created_receipts.append(_receipt_response(receipt))
    _write_jsonl({"event": "demo_seeded", "created_at": _now_iso(), "assignment_count": len(created_assignments), "receipt_count": len(created_receipts)})
    return {
        "status": "seeded",
        "mode": "staff_roleplay_demo_seed",
        "assignment_count": len(created_assignments),
        "receipt_count": len(created_receipts),
        "assignments": created_assignments,
        "receipts": created_receipts,
        "readiness": staff_training_readiness(),
        "uses_generated_data": True,
        "feeds_actual_reward_model": False,
    }


def start_staff_training_session(
    scenario_key: str | None = None,
    trainee_name: str | None = None,
    use_llm_guest: bool | None = None,
    assignment_id: str | None = None,
    retry_of_session_id: str | None = None,
) -> dict[str, Any]:
    scenario = SCENARIOS.get(str(scenario_key or "").strip()) or SCENARIOS["lost_child_report"]
    session_id = "staff-train-" + hashlib.sha1(f"{scenario['id']}:{time.time()}:{trainee_name or ''}".encode("utf-8")).hexdigest()[:16]
    llm_guest_enabled = _llm_guest_requested(use_llm_guest)
    session = {
        "id": session_id,
        "status": "active",
        "mode": "staff_roleplay_session",
        "scenario_id": scenario["id"],
        "scenario": _public_scenario(scenario),
        "trainee_name": str(trainee_name or "Seasonal staff trainee")[:80],
        "assignment_id": str(assignment_id or "")[:80] or None,
        "retry_of_session_id": str(retry_of_session_id or "")[:80] or None,
        "started_at": _now_iso(),
        "updated_at": _now_iso(),
        "turn_count": 0,
        "transcript": [{"speaker": "guest", "message": scenario["opening_message"], "at": _now_iso()}],
        "scores": [],
        "scorecard": _empty_scorecard(),
        "critical_miss": False,
        "guest_simulator": {
            "mode": "llm_guest_with_deterministic_scoring" if llm_guest_enabled else "deterministic_guest",
            "llm_requested": llm_guest_enabled,
            "llm_controls_score": False,
            "fallback": "deterministic_guest_reply",
        },
        "completed_objectives": [],
        "missing_objectives": list(scenario["objectives"]),
        "boundary": "Training simulator only; no live dispatch, guest PII, reward labels, or policy promotion authority.",
    }
    _SESSIONS[session_id] = session
    _write_jsonl({"event": "session_started", **_session_event_snapshot(session)})
    return _session_response(session)


def advance_staff_training_turn(session_id: str, employee_message: str, use_llm_guest: bool | None = None) -> dict[str, Any]:
    session = _SESSIONS.get(str(session_id or ""))
    if not session:
        return {"status": "not_found", "mode": "staff_roleplay_turn", "readiness_issues": ["Training session was not found or has expired. Start a new session."]}
    if session.get("status") != "active":
        return {"status": "closed", "mode": "staff_roleplay_turn", "session": _session_response(session)}

    scenario = SCENARIOS[session["scenario_id"]]
    message = str(employee_message or "").strip()
    if not message:
        return {"status": "invalid", "mode": "staff_roleplay_turn", "readiness_issues": ["Employee message is required."]}

    session["turn_count"] = int(session.get("turn_count") or 0) + 1
    employee_turn = {"speaker": "employee", "message": message[:2000], "at": _now_iso()}
    session["transcript"].append(employee_turn)
    score = _score_employee_message(scenario, message, session["turn_count"])
    session["scores"].append(score)
    session["scorecard"] = _aggregate_scorecard(session["scores"])
    session["critical_miss"] = bool(session.get("critical_miss") or score.get("critical_miss"))
    completed, missing = _objective_progress(scenario, session["transcript"])
    session["completed_objectives"] = completed
    session["missing_objectives"] = missing

    fallback_reply = _guest_reply(scenario, score, missing, session["turn_count"])
    llm_guest_requested = _llm_guest_requested(use_llm_guest, session)
    guest_generation = (
        _generate_llm_guest_reply(scenario, session, message, score, missing, fallback_reply)
        if llm_guest_requested
        else {"status": "not_requested", "source": "deterministic", "reply": fallback_reply}
    )
    guest_reply = str(guest_generation.get("reply") or fallback_reply)
    session["guest_simulator"] = {
        "mode": "llm_guest_with_deterministic_scoring" if llm_guest_requested else "deterministic_guest",
        "llm_requested": llm_guest_requested,
        "llm_status": guest_generation.get("status"),
        "llm_controls_score": False,
        "fallback": "deterministic_guest_reply",
        "source": guest_generation.get("source"),
        "model": guest_generation.get("model"),
    }
    session["transcript"].append({"speaker": "guest", "message": guest_reply, "at": _now_iso(), "source": guest_generation.get("source")})
    session["updated_at"] = _now_iso()
    if session["turn_count"] >= 4 or (not missing and not session["critical_miss"]):
        session["status"] = "ready_to_finish"

    payload = {
        "status": "complete",
        "mode": "staff_roleplay_turn",
        "session": _session_response(session),
        "guest_reply": guest_reply,
        "turn_score": score,
        "coaching_notes": score["coaching_notes"],
        "critical_miss": score["critical_miss"],
        "guest_reply_source": guest_generation.get("source"),
        "llm_guest": {key: value for key, value in guest_generation.items() if key != "reply"},
    }
    _write_jsonl({"event": "turn_scored", "turn_score": score, **_session_event_snapshot(session)})
    return payload


def finish_staff_training_session(session_id: str) -> dict[str, Any]:
    session = _SESSIONS.get(str(session_id or ""))
    if not session:
        return {"status": "not_found", "mode": "staff_roleplay_finish", "readiness_issues": ["Training session was not found or has expired."]}
    session["status"] = "finished"
    session["finished_at"] = _now_iso()
    session["updated_at"] = _now_iso()
    debrief = _debrief(session)
    session["debrief"] = debrief
    _write_jsonl({"event": "session_finished", "debrief": debrief, **_session_event_snapshot(session)})
    return {
        "status": "complete",
        "mode": "staff_roleplay_finish",
        "session": _session_response(session),
        "debrief": debrief,
    }


def staff_training_analytics(limit: int = 200) -> dict[str, Any]:
    rows = [row for row in _read_jsonl(limit=limit) if row.get("event") == "session_finished"]
    if not rows:
        return {
            "status": "empty",
            "mode": "staff_roleplay_analytics",
            "session_count": 0,
            "scenario_summary": [],
            "weakest_dimensions": [],
            "boundary": "Analytics summarize simulated training sessions only.",
            "uses_generated_data": True,
            "feeds_actual_reward_model": False,
        }
    by_scenario: dict[str, list[dict[str, Any]]] = {}
    dimension_totals = {dimension: [] for dimension in RUBRIC_DIMENSIONS}
    for row in rows:
        by_scenario.setdefault(str(row.get("scenario_id") or "unknown"), []).append(row)
        scorecard = row.get("scorecard", {}) if isinstance(row.get("scorecard"), dict) else {}
        dimensions = scorecard.get("dimensions", {}) if isinstance(scorecard.get("dimensions"), dict) else {}
        for dimension in RUBRIC_DIMENSIONS:
            value = dimensions.get(dimension)
            if isinstance(value, (int, float)):
                dimension_totals[dimension].append(float(value))

    scenario_summary = []
    for scenario_id, scenario_rows in sorted(by_scenario.items()):
        totals = [float(row.get("scorecard", {}).get("overall", 0)) for row in scenario_rows if isinstance(row.get("scorecard"), dict)]
        scenario_summary.append(
            {
                "scenario_id": scenario_id,
                "title": SCENARIOS.get(scenario_id, {}).get("title", scenario_id.replace("_", " ")),
                "session_count": len(scenario_rows),
                "average_overall": round(sum(totals) / max(1, len(totals)), 1),
                "critical_miss_count": sum(1 for row in scenario_rows if row.get("critical_miss")),
            }
        )
    weakest = sorted(
        (
            {"dimension": dimension, "average": round(sum(values) / max(1, len(values)), 1)}
            for dimension, values in dimension_totals.items()
            if values
        ),
        key=lambda item: item["average"],
    )[:4]
    return {
        "status": "ready",
        "mode": "staff_roleplay_analytics",
        "session_count": len(rows),
        "scenario_summary": scenario_summary,
        "weakest_dimensions": weakest,
        "recent_sessions": rows[-8:],
        "boundary": "Analytics summarize simulated training sessions only; they do not create live operations labels.",
        "uses_generated_data": True,
        "feeds_actual_reward_model": False,
    }


def _normalize_staff_role(value: str | None) -> str:
    role = str(value or "guest_services").strip().lower().replace("-", "_").replace(" ", "_")
    return role if role in STAFF_ROLE_ASSIGNMENT_SCENARIOS else "guest_services"


def _role_templates() -> list[dict[str, Any]]:
    return [
        {
            "staff_role": role,
            "scenario_ids": scenario_ids,
            "scenarios": [_public_scenario(SCENARIOS[item]) for item in scenario_ids if item in SCENARIOS],
        }
        for role, scenario_ids in STAFF_ROLE_ASSIGNMENT_SCENARIOS.items()
    ]


def _assignment_response(row: dict[str, Any]) -> dict[str, Any]:
    scenario_ids = [item for item in row.get("scenario_ids", []) if item in SCENARIOS] if isinstance(row.get("scenario_ids"), list) else []
    return {
        "id": row.get("assignment_id") or row.get("id"),
        "trainee_name": row.get("trainee_name") or "Seasonal staff trainee",
        "staff_role": _normalize_staff_role(str(row.get("staff_role") or "")),
        "scenario_ids": scenario_ids,
        "scenarios": [_public_scenario(SCENARIOS[item]) for item in scenario_ids],
        "assigned_by": row.get("assigned_by") or "ParkPulse manager",
        "status": row.get("status") or "assigned",
        "created_at": row.get("created_at"),
        "boundary": row.get("boundary") or "Training assignment only.",
    }


def _find_assignment(assignments: list[dict[str, Any]], assignment_id: str | None = None, trainee_name: str | None = None) -> dict[str, Any] | None:
    assignment_key = str(assignment_id or "").strip()
    trainee_key = str(trainee_name or "").strip().lower()
    for assignment in reversed(assignments):
        if assignment_key and str(assignment.get("id") or "") == assignment_key:
            return assignment
        if trainee_key and str(assignment.get("trainee_name") or "").strip().lower() == trainee_key:
            return assignment
    return None


def _packet_next_actions(assignment: dict[str, Any], readiness: dict[str, Any], receipts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if readiness.get("status") == "ready_for_shadowing":
        actions.append({"type": "manager_signoff", "label": "Manager may sign off for live shadowing.", "severity": "ready"})
        return actions

    missing = [item for item in readiness.get("required_scenarios", []) if item not in readiness.get("completed_scenarios", []) and item not in readiness.get("needs_retry_scenarios", [])]
    for scenario_id in readiness.get("needs_retry_scenarios", []) or []:
        scenario = SCENARIOS.get(str(scenario_id) or "")
        actions.append(
            {
                "type": "retry_scenario",
                "scenario_id": scenario_id,
                "label": f"Retry {scenario.get('title') if scenario else str(scenario_id).replace('_', ' ')} before live shadowing.",
                "severity": "hold",
            }
        )
    for scenario_id in missing:
        scenario = SCENARIOS.get(str(scenario_id) or "")
        actions.append(
            {
                "type": "complete_scenario",
                "scenario_id": scenario_id,
                "label": f"Complete {scenario.get('title') if scenario else str(scenario_id).replace('_', ' ')}.",
                "severity": "pending",
            }
        )
    if any(str(receipt.get("review_status") or "") == "pending_review" for receipt in receipts):
        actions.append({"type": "manager_review", "label": "Review pending receipts before signoff.", "severity": "review"})
    return actions or [{"type": "start_assignment", "label": f"Start training for {assignment.get('trainee_name')}.", "severity": "pending"}]


def _receipt_id(session_id: str) -> str:
    return "receipt-" + hashlib.sha1(str(session_id or "").encode("utf-8")).hexdigest()[:14]


def _review_response(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "id": row.get("review_id") or row.get("id"),
        "receipt_id": row.get("receipt_id"),
        "session_id": row.get("session_id"),
        "assignment_id": row.get("assignment_id"),
        "decision": row.get("decision"),
        "reviewer": row.get("reviewer"),
        "notes": row.get("notes") or "",
        "created_at": row.get("created_at"),
        "boundary": row.get("boundary") or "Manager review disposition only.",
    }


def _latest_reviews_by_session(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    reviews: dict[str, dict[str, Any]] = {}
    for row in events:
        if row.get("event") == "receipt_reviewed":
            session_id = str(row.get("session_id") or "")
            if session_id:
                reviews[session_id] = row
    return reviews


def _find_receipt_target(finished: list[dict[str, Any]], session_id: str | None = None, receipt_id: str | None = None) -> dict[str, Any] | None:
    session_key = str(session_id or "").strip()
    receipt_key = str(receipt_id or "").strip()
    for row in reversed(finished):
        row_session_id = str(row.get("id") or row.get("session_id") or "")
        if session_key and row_session_id == session_key:
            return row
        if receipt_key and _receipt_id(row_session_id) == receipt_key:
            return row
    return None


def _receipt_response(row: dict[str, Any], latest_review: dict[str, Any] | None = None) -> dict[str, Any]:
    scorecard = row.get("scorecard", {}) if isinstance(row.get("scorecard"), dict) else {}
    debrief = row.get("debrief", {}) if isinstance(row.get("debrief"), dict) else {}
    session_id = str(row.get("id") or row.get("session_id") or "")
    scenario_id = str(row.get("scenario_id") or "")
    manager_review_required = bool(row.get("critical_miss") or float(scorecard.get("overall") or 0) < 75)
    review = _review_response(latest_review)
    return {
        "id": _receipt_id(session_id),
        "session_id": session_id,
        "assignment_id": row.get("assignment_id"),
        "retry_of_session_id": row.get("retry_of_session_id"),
        "trainee_name": row.get("trainee_name") or "Seasonal staff trainee",
        "staff_role": row.get("staff_role"),
        "scenario_id": scenario_id,
        "scenario_title": SCENARIOS.get(scenario_id, {}).get("title", scenario_id.replace("_", " ")),
        "finished_at": row.get("finished_at") or row.get("created_at"),
        "overall": scorecard.get("overall", 0),
        "critical_miss": bool(row.get("critical_miss")),
        "result": debrief.get("result") or ("coach_and_retry" if row.get("critical_miss") else "pass"),
        "summary": debrief.get("summary") or "",
        "recommended_retry": debrief.get("recommended_retry"),
        "manager_review_required": manager_review_required,
        "manager_review": review,
        "review_status": review.get("decision") if review else ("pending_review" if manager_review_required else "not_required"),
        "transcript_turn_count": row.get("turn_count", 0),
        "boundary": "Training receipt only; not a live operations action or reward label.",
    }


def _readiness_by_assignment(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    assignments = [_assignment_response(row) for row in events if row.get("event") == "assignment_created"]
    finished = [row for row in events if row.get("event") == "session_finished"]
    reviews = _latest_reviews_by_session(events)
    result: dict[str, dict[str, Any]] = {}
    for assignment in assignments:
        assignment_id = str(assignment.get("id") or "")
        receipts = [row for row in finished if str(row.get("assignment_id") or "") == assignment_id]
        result[assignment_id] = _assignment_readiness(assignment, receipts, reviews)
    return result


def _assignment_readiness(assignment: dict[str, Any], receipts: list[dict[str, Any]], reviews: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    reviews = reviews or {}
    required = [item for item in assignment.get("scenario_ids", []) if item in SCENARIOS]
    latest_by_scenario: dict[str, dict[str, Any]] = {}
    for receipt in receipts:
        scenario_id = str(receipt.get("scenario_id") or "")
        if scenario_id in required:
            latest_by_scenario[scenario_id] = receipt
    completed = []
    needs_retry = []
    critical_miss_count = 0
    review_hold_count = 0
    scores = []
    for scenario_id in required:
        receipt = latest_by_scenario.get(scenario_id)
        if not receipt:
            continue
        scorecard = receipt.get("scorecard", {}) if isinstance(receipt.get("scorecard"), dict) else {}
        overall = float(scorecard.get("overall") or 0)
        critical = bool(receipt.get("critical_miss"))
        session_id = str(receipt.get("id") or receipt.get("session_id") or "")
        review_decision = str((reviews.get(session_id) or {}).get("decision") or "")
        critical_miss_count += 1 if critical else 0
        review_hold_count += 1 if review_decision in {"require_retry", "hold"} else 0
        scores.append(overall)
        if overall >= 75 and not critical and review_decision not in {"require_retry", "hold"}:
            completed.append(scenario_id)
        else:
            needs_retry.append(scenario_id)
    if not latest_by_scenario:
        status = "not_started"
    elif needs_retry:
        status = "needs_coaching"
    elif len(completed) >= len(required):
        status = "ready_for_shadowing"
    else:
        status = "in_progress"
    return {
        "assignment_id": assignment.get("id"),
        "trainee_name": assignment.get("trainee_name"),
        "staff_role": assignment.get("staff_role"),
        "status": status,
        "required_count": len(required),
        "completed_count": len(completed),
        "required_scenarios": required,
        "completed_scenarios": completed,
        "needs_retry_scenarios": needs_retry,
        "last_score": round(scores[-1], 1) if scores else None,
        "average_score": round(sum(scores) / max(1, len(scores)), 1) if scores else None,
        "critical_miss_count": critical_miss_count,
        "review_hold_count": review_hold_count,
        "live_shadowing_gate": "pass" if status == "ready_for_shadowing" else "hold",
    }


def _demo_finished_session(item: dict[str, Any], assignment: dict[str, Any]) -> dict[str, Any]:
    scenario_id = str(item.get("scenario_id") or "")
    scenario = SCENARIOS[scenario_id]
    session_id = "staff-demo-" + hashlib.sha1(f"{assignment.get('id')}:{scenario_id}".encode("utf-8")).hexdigest()[:14]
    scorecard = item.get("scorecard", _empty_scorecard())
    critical_miss = bool(item.get("critical_miss"))
    debrief = {
        "result": "coach_and_retry" if critical_miss or float(scorecard.get("overall") or 0) < 75 else "pass",
        "summary": "Ready for live shadowing." if not critical_miss and float(scorecard.get("overall") or 0) >= 75 else "Needs another roleplay pass before live shadowing.",
        "overall": scorecard.get("overall", 0),
        "weakest_dimensions": [],
        "completed_objectives": scenario.get("objectives", []) if not critical_miss else scenario.get("objectives", [])[:2],
        "missing_objectives": [] if not critical_miss else scenario.get("objectives", [])[2:],
        "critical_miss": critical_miss,
        "recommended_retry": scenario_id if critical_miss or float(scorecard.get("overall") or 0) < 75 else None,
    }
    return {
        "event": "session_finished",
        "id": session_id,
        "assignment_id": assignment.get("id"),
        "trainee_name": item.get("trainee_name"),
        "staff_role": item.get("staff_role"),
        "scenario_id": scenario_id,
        "status": "finished",
        "turn_count": scorecard.get("turn_count", 2),
        "scorecard": scorecard,
        "critical_miss": critical_miss,
        "completed_objectives": debrief["completed_objectives"],
        "missing_objectives": debrief["missing_objectives"],
        "debrief": debrief,
        "finished_at": _now_iso(),
        "created_at": _now_iso(),
    }


def _empty_scorecard() -> dict[str, Any]:
    return {"overall": 0, "dimensions": {dimension: 0 for dimension in RUBRIC_DIMENSIONS}, "turn_count": 0}


def _contains_any(text: str, terms: list[str] | tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _group_hits(text: str, groups: list[list[str]]) -> tuple[int, list[str]]:
    hits = 0
    missing: list[str] = []
    for group in groups:
        if any(term in text for term in group):
            hits += 1
        else:
            missing.append(" or ".join(group[:2]))
    return hits, missing


def _scale(hits: int, total: int, base: int = 1) -> int:
    if total <= 0:
        return 3
    return max(1, min(5, base + round((hits / total) * (5 - base))))


def _score_employee_message(scenario: dict[str, Any], message: str, turn_count: int) -> dict[str, Any]:
    text = f" {message.lower()} "
    policy_hits, missing_policy = _group_hits(text, scenario.get("policy_keywords", []))
    safety_hits, missing_safety = _group_hits(text, scenario.get("safety_keywords", []))
    escalation_hits, missing_escalation = _group_hits(text, scenario.get("escalation_keywords", []))
    rude = _contains_any(text, _RUDE_TERMS) or _contains_any(text, tuple(scenario.get("prohibited_terms", [])))

    dimensions = {
        "empathy": max(1, min(5, 2 + sum(1 for term in _EMPATHY_TERMS if term in text))) if not rude else 1,
        "policy_correctness": _scale(policy_hits, len(scenario.get("policy_keywords", []))),
        "escalation_decision": _scale(escalation_hits, len(scenario.get("escalation_keywords", []))),
        "clarity": max(1, min(5, 2 + sum(1 for term in _CLARITY_TERMS if term in text))),
        "safety_awareness": _scale(safety_hits, len(scenario.get("safety_keywords", []))),
        "de_escalation": max(1, min(5, 2 + sum(1 for term in _DEESCALATION_TERMS if term in text))) if not rude else 1,
        "brand_tone": 4 if not rude else 1,
    }
    if len(message.split()) < 7:
        dimensions["clarity"] = min(dimensions["clarity"], 2)
        dimensions["empathy"] = min(dimensions["empathy"], 2)
    fatal_after = int(scenario.get("fatal_if_missing_after_turn") or 99)
    critical_miss = rude or (turn_count >= fatal_after and escalation_hits == 0 and scenario.get("difficulty") == "critical")
    if critical_miss:
        dimensions["safety_awareness"] = min(dimensions["safety_awareness"], 2)
        dimensions["escalation_decision"] = min(dimensions["escalation_decision"], 2)
        dimensions["policy_correctness"] = min(dimensions["policy_correctness"], 2)

    overall = round(sum(dimensions.values()) / len(dimensions) * 20)
    if critical_miss:
        overall = min(overall, 55)
    coaching_notes = _coaching_notes(missing_policy, missing_safety, missing_escalation, rude, critical_miss)
    return {
        "overall": overall,
        "dimensions": dimensions,
        "missing_policy_signals": missing_policy[:3],
        "missing_safety_signals": missing_safety[:3],
        "missing_escalation_signals": missing_escalation[:2],
        "critical_miss": critical_miss,
        "coaching_notes": coaching_notes,
    }


def _coaching_notes(missing_policy: list[str], missing_safety: list[str], missing_escalation: list[str], rude: bool, critical_miss: bool) -> list[str]:
    notes: list[str] = []
    if rude:
        notes.append("Avoid dismissive or adversarial wording; keep the guest's dignity intact.")
    if missing_escalation:
        notes.append(f"Name the escalation path explicitly: {missing_escalation[0]}.")
    if missing_safety:
        notes.append(f"Make the safety step concrete: {missing_safety[0]}.")
    if missing_policy:
        notes.append(f"Add the missing policy detail: {missing_policy[0]}.")
    if critical_miss:
        notes.append("Critical miss: safety or escalation cannot be implied in this scenario.")
    if not notes:
        notes.append("Strong turn: empathy, policy, and next step were visible.")
    return notes[:4]


def _objective_progress(scenario: dict[str, Any], transcript: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    employee_text = " ".join(str(turn.get("message") or "").lower() for turn in transcript if turn.get("speaker") == "employee")
    groups = scenario.get("policy_keywords", [])
    completed: list[str] = []
    missing: list[str] = []
    for idx, objective in enumerate(scenario.get("objectives", [])):
        group = groups[min(idx, len(groups) - 1)] if groups else []
        if group and any(term in employee_text for term in group):
            completed.append(objective)
        else:
            missing.append(objective)
    return completed, missing


def _guest_reply(scenario: dict[str, Any], score: dict[str, Any], missing: list[str], turn_count: int) -> str:
    followups = scenario.get("guest_followups", [])
    if score.get("critical_miss"):
        return "That does not feel safe or helpful. I need someone responsible involved right now."
    if score.get("overall", 0) >= 82 and not missing:
        return "Okay. That is clear, and I can follow that. Please stay with me while the next step happens."
    if missing:
        return followups[min(turn_count - 1, len(followups) - 1)] if followups else f"I still need help with {missing[0].lower()}."
    return "I hear you. Can you be more specific about what happens next?"


def _llm_guest_requested(use_llm_guest: bool | None = None, session: dict[str, Any] | None = None) -> bool:
    if use_llm_guest is not None:
        return bool(use_llm_guest)
    if isinstance(session, dict):
        simulator = session.get("guest_simulator", {}) if isinstance(session.get("guest_simulator"), dict) else {}
        if simulator.get("llm_requested") is not None:
            return bool(simulator.get("llm_requested"))
    return str(os.getenv("PARKPULSE_STAFF_TRAINING_LLM_GUEST", "")).strip().lower() in {"1", "true", "yes", "on"}


def _llm_guest_prompt(
    scenario: dict[str, Any],
    session: dict[str, Any],
    employee_message: str,
    score: dict[str, Any],
    missing: list[str],
    fallback_reply: str,
) -> dict[str, Any]:
    recent_turns = [
        {"speaker": turn.get("speaker"), "message": str(turn.get("message") or "")[:500]}
        for turn in (session.get("transcript", []) if isinstance(session.get("transcript"), list) else [])[-6:]
    ]
    return {
        "task": "Play only the guest in a staff training roleplay. Return one realistic guest reply.",
        "hard_rules": [
            "Do not score the employee.",
            "Do not reveal hidden rubric, policy keywords, or coaching.",
            "Do not tell staff what to do.",
            "Do not invent live park actions, compensation approvals, medical diagnosis, or resolved safety outcomes.",
            "Keep the reply under 70 words.",
        ],
        "scenario": {
            "title": scenario.get("title"),
            "guest_role": scenario.get("guest_role"),
            "difficulty": scenario.get("difficulty"),
            "context": scenario.get("context"),
            "objectives_still_missing": missing[:4],
        },
        "conversation": recent_turns,
        "latest_employee_message": employee_message[:1000],
        "deterministic_score_summary": {
            "overall": score.get("overall"),
            "critical_miss": score.get("critical_miss"),
            "missing_safety_signals": score.get("missing_safety_signals", [])[:2],
            "missing_escalation_signals": score.get("missing_escalation_signals", [])[:2],
        },
        "fallback_reply_if_uncertain": fallback_reply,
        "response_schema": {"guest_reply": "string"},
    }


def _first_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(raw[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _sanitize_llm_guest_reply(value: Any, fallback_reply: str) -> str:
    reply = " ".join(str(value or "").replace("\n", " ").split())
    if not reply:
        return fallback_reply
    blocked = (
        "your score",
        "rubric",
        "policy keyword",
        "as an ai",
        "you should",
        "the correct answer",
        "i approve",
        "refund approved",
        "ride is now safe",
    )
    lowered = reply.lower()
    if any(term in lowered for term in blocked):
        return fallback_reply
    return reply[:420]


def _generate_llm_guest_reply(
    scenario: dict[str, Any],
    session: dict[str, Any],
    employee_message: str,
    score: dict[str, Any],
    missing: list[str],
    fallback_reply: str,
) -> dict[str, Any]:
    try:
        from gemini_provider import get_gemini_agent_properties, get_gemini_client, get_gemini_model

        props = get_gemini_agent_properties()
        if not props.ready:
            return {
                "status": "fallback_not_configured",
                "source": "deterministic",
                "reply": fallback_reply,
                "readiness_issues": props.readiness_issues,
            }
        from google.genai import types

        prompt = _llm_guest_prompt(scenario, session, employee_message, score, missing, fallback_reply)
        model = get_gemini_model()
        response = get_gemini_client().models.generate_content(
            model=model,
            contents=json.dumps(prompt, sort_keys=True, separators=(",", ":")),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=float(os.getenv("PARKPULSE_STAFF_TRAINING_LLM_TEMPERATURE", "0.55")),
                max_output_tokens=int(os.getenv("PARKPULSE_STAFF_TRAINING_LLM_MAX_OUTPUT_TOKENS", "180")),
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        parsed = _first_json_object(getattr(response, "text", "") or "")
        reply = _sanitize_llm_guest_reply((parsed or {}).get("guest_reply"), fallback_reply)
        source = "llm_guest" if reply != fallback_reply else "deterministic"
        return {
            "status": "generated" if source == "llm_guest" else "fallback_sanitized",
            "source": source,
            "reply": reply,
            "model": model,
            "provider": props.provider,
            "llm_controls_score": False,
        }
    except Exception as error:
        return {
            "status": "fallback_error",
            "source": "deterministic",
            "reply": fallback_reply,
            "error": str(error)[:240],
            "llm_controls_score": False,
        }


def _aggregate_scorecard(scores: list[dict[str, Any]]) -> dict[str, Any]:
    if not scores:
        return _empty_scorecard()
    dimensions: dict[str, float] = {}
    for dimension in RUBRIC_DIMENSIONS:
        values = [float(score.get("dimensions", {}).get(dimension, 0)) for score in scores if isinstance(score.get("dimensions"), dict)]
        dimensions[dimension] = round(sum(values) / max(1, len(values)), 1)
    overall = round(sum(float(score.get("overall", 0)) for score in scores) / len(scores), 1)
    if any(score.get("critical_miss") for score in scores):
        overall = min(overall, 60)
    return {"overall": overall, "dimensions": dimensions, "turn_count": len(scores)}


def _debrief(session: dict[str, Any]) -> dict[str, Any]:
    scorecard = session.get("scorecard", _empty_scorecard())
    dimensions = scorecard.get("dimensions", {}) if isinstance(scorecard.get("dimensions"), dict) else {}
    weakest = sorted(
        [{"dimension": key, "score": value} for key, value in dimensions.items()],
        key=lambda item: float(item["score"]),
    )[:3]
    passed = float(scorecard.get("overall") or 0) >= 75 and not session.get("critical_miss") and not session.get("missing_objectives")
    return {
        "result": "pass" if passed else "coach_and_retry",
        "summary": "Ready for live shadowing." if passed else "Needs another roleplay pass before live shadowing.",
        "overall": scorecard.get("overall", 0),
        "weakest_dimensions": weakest,
        "completed_objectives": session.get("completed_objectives", []),
        "missing_objectives": session.get("missing_objectives", []),
        "critical_miss": bool(session.get("critical_miss")),
        "recommended_retry": session.get("scenario_id") if not passed else None,
    }


def _session_event_snapshot(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": session.get("id"),
        "assignment_id": session.get("assignment_id"),
        "retry_of_session_id": session.get("retry_of_session_id"),
        "trainee_name": session.get("trainee_name"),
        "scenario_id": session.get("scenario_id"),
        "status": session.get("status"),
        "turn_count": session.get("turn_count"),
        "scorecard": session.get("scorecard"),
        "critical_miss": session.get("critical_miss"),
        "completed_objectives": session.get("completed_objectives", []),
        "missing_objectives": session.get("missing_objectives", []),
        "created_at": _now_iso(),
    }


def _session_response(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": session.get("id"),
        "assignment_id": session.get("assignment_id"),
        "retry_of_session_id": session.get("retry_of_session_id"),
        "status": session.get("status"),
        "mode": session.get("mode"),
        "scenario": session.get("scenario"),
        "trainee_name": session.get("trainee_name"),
        "started_at": session.get("started_at"),
        "updated_at": session.get("updated_at"),
        "finished_at": session.get("finished_at"),
        "turn_count": session.get("turn_count"),
        "transcript": session.get("transcript", []),
        "scorecard": session.get("scorecard", _empty_scorecard()),
        "critical_miss": bool(session.get("critical_miss")),
        "completed_objectives": session.get("completed_objectives", []),
        "missing_objectives": session.get("missing_objectives", []),
        "debrief": session.get("debrief"),
        "guest_simulator": session.get("guest_simulator"),
        "boundary": session.get("boundary"),
        "uses_generated_data": True,
        "feeds_actual_reward_model": False,
        "llm_control_authority": False,
    }
