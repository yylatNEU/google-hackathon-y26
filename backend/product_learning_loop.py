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
    "injury_or_safety_incident",
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
    "injury": "injury_or_safety_incident",
    "accident": "injury_or_safety_incident",
    "safety_incident": "injury_or_safety_incident",
    "accessibility_request": "accessibility_accommodation",
    "line_conflict": "line_cutting_conflict",
    "safety_refusal": "safety_rule_refusal",
    "weather_evacuation": "weather_evacuation_confusion",
}

TEAM_BY_ISSUE = {
    "lost_child_report": "security",
    "heat_exhaustion_concern": "first_aid",
    "injury_or_safety_incident": "safety",
    "accessibility_accommodation": "accessibility",
    "refund_request": "guest_services",
    "angry_parent": "guest_services",
    "ride_closure_complaint": "ride_ops",
    "line_cutting_conflict": "security",
    "safety_rule_refusal": "ride_ops",
    "weather_evacuation_confusion": "ops_lead",
    "language_barrier": "guest_services",
}

HIGH_RISK_ISSUES = {"lost_child_report", "heat_exhaustion_concern", "injury_or_safety_incident", "safety_rule_refusal", "weather_evacuation_confusion"}
HUMAN_EXCEPTION_ISSUES = HIGH_RISK_ISSUES | {"accessibility_accommodation", "refund_request"}
AUTO_LEARNING_MIN_EVIDENCE = 2
AUTO_LEARNING_MIN_CONFIDENCE = 0.74

BACKLOG_ISSUE_MAP = {
    "food-court-a-backlog": "refund_request",
    "fast-lane-fairness-risk": "angry_parent",
    "showtime-traffic-wave": "weather_evacuation_confusion",
    "guest-recovery-pressure": "angry_parent",
    "safety-access-readiness": "weather_evacuation_confusion",
    "finance-exposure-watch": "refund_request",
    "planning-horizon-risk": "weather_evacuation_confusion",
    "customer-experience-trust-risk": "angry_parent",
}


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


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _bounded(value: float, floor: float, ceiling: float) -> float:
    return max(floor, min(ceiling, value))


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


def generate_park_issue_tickets_from_operational_backlog(backlog: dict[str, Any] | None, *, limit: int = 12) -> list[dict[str, Any]]:
    """Project dynamic park backlog issues into live issue tickets without UI/manual creation."""
    issues = backlog.get("issues", []) if isinstance(backlog, dict) and isinstance(backlog.get("issues"), list) else []
    tickets: list[dict[str, Any]] = []
    for issue in issues[: max(1, min(50, int(limit or 12)))]:
        if not isinstance(issue, dict):
            continue
        issue_id = str(issue.get("id") or issue.get("title") or "")
        issue_type = BACKLOG_ISSUE_MAP.get(issue_id) or _issue_type_from_backlog_issue(issue)
        severity = _severity_from_backlog_issue(issue)
        ticket = {
            "event": "park_issue_ticket_generated",
            "id": _stable_id(
                "park-issue",
                {
                    "source": "dynamic_park",
                    "issue_id": issue_id,
                    "issue_type": issue_type,
                    "current": issue.get("current"),
                    "severity": severity,
                },
            ),
            "source": "dynamic_park",
            "issue_type": issue_type,
            "severity": severity,
            "location": str(issue.get("domain") or issue.get("executiveDomain") or "")[:120] or None,
            "reporter_role": "dynamic_park_backend",
            "summary": _backlog_issue_summary(issue),
            "required_action": str(issue.get("recommendedNext") or _default_required_action(issue_type))[:500],
            "assigned_team": TEAM_BY_ISSUE.get(issue_type) or "ops_lead",
            "status": str(issue.get("status") or "unresolved")[:80],
            "live_ops_authority": True,
            "requires_human_ack": severity in {"high", "critical"} or issue_type in HIGH_RISK_ISSUES,
            "created_at": _now_iso(),
            "derived_from": "operational_backlog",
            "dynamic_park_issue_id": issue_id or None,
            "evidence": issue.get("evidence") if isinstance(issue.get("evidence"), list) else [],
            "classification_confidence": _backlog_classification_confidence(issue_id, issue_type),
            "severity_confidence": 0.82,
            "ticket_generation_trace": {
                "decision": "generated",
                "source": "operational_backlog",
                "matched_rule": "known_backlog_issue_id" if issue_id in BACKLOG_ISSUE_MAP else "keyword_backlog_classifier",
                "causal_chain": issue.get("evidence") if isinstance(issue.get("evidence"), list) else [],
                "human_ack_required_reason": "high_risk_issue_type_or_severity" if severity in {"high", "critical"} or issue_type in HIGH_RISK_ISSUES else "not_required",
            },
            "boundary": "Generated from dynamic park operational backlog; high-risk actions still require human acknowledgement before live dispatch.",
        }
        tickets.append(ticket)
    return tickets


def build_place_risk_graph(state: dict[str, Any] | None) -> dict[str, Any]:
    """Build a compact place-causality graph from park state for ticket generation."""
    state = _as_dict(state)
    configured = _as_dict(state.get("placeRiskGraph"))
    if isinstance(configured.get("places"), list):
        places = [_normalize_place_node(place) for place in configured.get("places", []) if isinstance(place, dict)]
        return {"mode": "state_supplied_place_risk_graph", "places": places}

    flow = _as_dict(state.get("guestFlow"))
    weather = _as_dict(state.get("weather"))
    heat_index = int(_number(weather.get("heatIndexF") or weather.get("heatIndex"), 0))
    storm_risk = int(_number(weather.get("stormRisk"), 0))
    places: dict[str, dict[str, Any]] = {}

    for zone in _as_list(flow.get("zones")):
        if not isinstance(zone, dict):
            continue
        place_id = str(zone.get("id") or zone.get("name") or "unknown_zone")
        name = str(zone.get("name") or place_id)
        density = int(_number(zone.get("density"), 0))
        wait = int(_number(zone.get("waitMins") or zone.get("waitMinutes"), 0))
        process_type = str(zone.get("processType") or zone.get("type") or "zone").lower()
        factors: list[str] = []
        if density >= 85:
            factors.append("high_density")
        if wait >= 25:
            factors.append("long_wait")
        if heat_index >= 100 and not any(term in name.lower() for term in ("indoor", "covered", "arcade")):
            factors.append("poor_shade")
        if process_type == "food" and (density >= 70 or wait >= 25):
            factors.append("food_pickup_spillover")
        if storm_risk >= 65 and density >= 70:
            factors.append("signage_gap")
        places[place_id] = {
            "place_id": place_id,
            "name": name,
            "type": process_type,
            "connected_places": [],
            "risk_factors": factors,
            "current_load": density,
            "wait_minutes": wait,
            "known_failure_modes": _failure_modes_for_place_factors(factors),
            "evidence": [f"density={density}", f"waitMins={wait}", f"heatIndexF={heat_index}", f"stormRisk={storm_risk}"],
        }

    for path in _as_list(flow.get("paths")):
        if not isinstance(path, dict):
            continue
        from_id = str(path.get("from") or path.get("fromName") or "unknown_from")
        to_id = str(path.get("to") or path.get("toName") or "unknown_to")
        name = f"{path.get('fromName') or from_id} to {path.get('toName') or to_id}"
        congestion = int(_number(path.get("congestionLevel"), 0))
        width = _number(path.get("widthM"), 99)
        current_guests = int(_number(path.get("currentGuests"), 0))
        place_id = f"path:{from_id}:{to_id}"
        factors = []
        if congestion >= 86:
            factors.append("crowd_bottleneck")
        if congestion >= 86 and width <= 4.8:
            factors.append("narrow_path")
        if congestion >= 78 and current_guests >= 500:
            factors.append("queue_merge_conflict")
        if storm_risk >= 65 and congestion >= 78:
            factors.append("confusing_route")
        places[place_id] = {
            "place_id": place_id,
            "name": name,
            "type": "path",
            "connected_places": [from_id, to_id],
            "risk_factors": factors,
            "current_load": congestion,
            "width_m": width,
            "current_guests": current_guests,
            "known_failure_modes": _failure_modes_for_place_factors(factors),
            "evidence": [f"pathCongestion={congestion}", f"widthM={width}", f"currentGuests={current_guests}", f"stormRisk={storm_risk}"],
        }

    return {"mode": "derived_place_risk_graph", "places": list(places.values())}


def generate_place_risk_ticket_candidates(state: dict[str, Any] | None, *, limit: int = 8) -> list[dict[str, Any]]:
    graph = build_place_risk_graph(state)
    candidates: list[dict[str, Any]] = []
    for place in _as_list(graph.get("places")):
        if not isinstance(place, dict):
            continue
        factors = {str(item) for item in _as_list(place.get("risk_factors"))}
        load = int(_number(place.get("current_load"), 0))
        wait = int(_number(place.get("wait_minutes"), 0))
        evidence = [str(item) for item in _as_list(place.get("evidence"))]
        if {"poor_shade", "long_wait"} <= factors or ("poor_shade" in factors and load >= 85):
            candidates.append(_candidate("place_risk", place, "heat_exhaustion_concern", "critical" if load >= 90 else "high", "uncovered_heat_queue_risk", 0.9, evidence))
        if "narrow_path" in factors and load >= 88:
            candidates.append(_candidate("place_risk", place, "injury_or_safety_incident", "critical" if load >= 94 else "high", "narrow_congested_path_injury_risk", 0.86, evidence))
        if "confusing_route" in factors:
            candidates.append(_candidate("place_risk", place, "weather_evacuation_confusion", "high", "storm_route_confusion_risk", 0.82, evidence))
        if "queue_merge_conflict" in factors:
            candidates.append(_candidate("place_risk", place, "line_cutting_conflict", "high" if load >= 90 else "medium", "queue_merge_conflict_risk", 0.78, evidence))
        if "food_pickup_spillover" in factors and (load >= 80 or wait >= 25):
            candidates.append(_candidate("place_risk", place, "refund_request", "medium", "food_pickup_spillover_complaint_risk", 0.76, evidence))
        if "accessibility_lane_block" in factors or "misplaced_accessibility_route" in factors:
            candidates.append(_candidate("place_risk", place, "accessibility_accommodation", "high", "accessibility_route_blocked", 0.88, evidence))
    return candidates[: max(1, min(30, int(limit or 8)))]


def generate_random_incident_ticket_candidates(state: dict[str, Any] | None, *, seed: str | None = None, limit: int = 4) -> list[dict[str, Any]]:
    graph = build_place_risk_graph(state)
    base_seed = str(seed or _state_seed(state))
    candidates: list[dict[str, Any]] = []
    for place in _as_list(graph.get("places")):
        if not isinstance(place, dict):
            continue
        factors = {str(item) for item in _as_list(place.get("risk_factors"))}
        load = int(_number(place.get("current_load"), 0))
        if load < 75 or not factors:
            continue
        incident = _random_incident_for_place(place, factors, base_seed)
        if not incident:
            continue
        candidates.append(incident)
    return candidates[: max(1, min(12, int(limit or 4)))]


def generate_park_issue_tickets_from_park_state(state: dict[str, Any] | None, *, seed: str | None = None, limit: int = 12) -> list[dict[str, Any]]:
    candidates = [
        *generate_place_risk_ticket_candidates(state, limit=limit),
        *generate_random_incident_ticket_candidates(state, seed=seed, limit=max(1, int(limit or 12) // 2)),
    ]
    deduped: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        key = "|".join(str(candidate.get(part) or "") for part in ("source", "place_id", "issue_type", "matched_rule"))
        deduped.setdefault(key, candidate)
    return [_ticket_from_generated_candidate(candidate) for candidate in list(deduped.values())[: max(1, min(50, int(limit or 12)))]]


def _normalize_place_node(place: dict[str, Any]) -> dict[str, Any]:
    factors = [str(item) for item in _as_list(place.get("risk_factors") or place.get("riskFactors"))]
    place_id = str(place.get("place_id") or place.get("placeId") or place.get("id") or place.get("name") or "unknown_place")
    return {
        "place_id": place_id,
        "name": str(place.get("name") or place_id),
        "type": str(place.get("type") or "place"),
        "connected_places": [str(item) for item in _as_list(place.get("connected_places") or place.get("connectedPlaces"))],
        "risk_factors": factors,
        "current_load": int(_number(place.get("current_load") or place.get("currentLoad") or place.get("density"), 0)),
        "wait_minutes": int(_number(place.get("wait_minutes") or place.get("waitMinutes") or place.get("waitMins"), 0)),
        "known_failure_modes": [str(item) for item in _as_list(place.get("known_failure_modes") or place.get("knownFailureModes"))] or _failure_modes_for_place_factors(factors),
        "evidence": [str(item) for item in _as_list(place.get("evidence"))],
    }


def _failure_modes_for_place_factors(factors: list[str] | set[str]) -> list[str]:
    factor_set = set(factors)
    modes: list[str] = []
    if "poor_shade" in factor_set:
        modes.append("heat_exhaustion_concern")
    if "narrow_path" in factor_set or "wet_surface" in factor_set:
        modes.append("injury_or_safety_incident")
    if "confusing_route" in factor_set or "signage_gap" in factor_set:
        modes.append("weather_evacuation_confusion")
    if "queue_merge_conflict" in factor_set:
        modes.append("line_cutting_conflict")
    if "food_pickup_spillover" in factor_set:
        modes.append("refund_request")
    if "accessibility_lane_block" in factor_set or "misplaced_accessibility_route" in factor_set:
        modes.append("accessibility_accommodation")
    return modes


def _candidate(source: str, place: dict[str, Any], issue_type: str, severity: str, matched_rule: str, confidence: float, evidence: list[str]) -> dict[str, Any]:
    place_id = str(place.get("place_id") or "unknown_place")
    causal_chain = [*evidence, *[f"riskFactor={factor}" for factor in _as_list(place.get("risk_factors"))]][:10]
    return {
        "source": source,
        "place_id": place_id,
        "location": str(place.get("name") or place_id)[:120],
        "issue_type": issue_type,
        "severity": severity,
        "matched_rule": matched_rule,
        "classification_confidence": round(_bounded(confidence, 0.0, 1.0), 2),
        "severity_confidence": 0.84 if severity in {"high", "critical"} else 0.72,
        "summary": f"{str(place.get('name') or place_id)} risk: {matched_rule.replace('_', ' ')}.",
        "required_action": _default_required_action(issue_type),
        "evidence": evidence,
        "causal_chain": causal_chain,
    }


def _random_incident_for_place(place: dict[str, Any], factors: set[str], seed: str) -> dict[str, Any] | None:
    place_id = str(place.get("place_id") or "unknown_place")
    load = int(_number(place.get("current_load"), 0))
    probability = _stable_probability(f"{seed}:{place_id}:{','.join(sorted(factors))}")
    threshold = _bounded((load - 65) / 35, 0.10, 0.92)
    if probability > threshold:
        return None
    evidence = [str(item) for item in _as_list(place.get("evidence"))]
    if "wet_surface" in factors or "narrow_path" in factors:
        return _candidate("random_incident", place, "injury_or_safety_incident", "high", "seeded_slip_trip_or_collision", 0.74, evidence)
    if "poor_shade" in factors:
        return _candidate("random_incident", place, "heat_exhaustion_concern", "high", "seeded_heat_distress_report", 0.72, evidence)
    if "queue_merge_conflict" in factors:
        return _candidate("random_incident", place, "line_cutting_conflict", "medium", "seeded_queue_merge_argument", 0.7, evidence)
    if "confusing_route" in factors or "signage_gap" in factors:
        return _candidate("random_incident", place, "weather_evacuation_confusion", "high", "seeded_wayfinding_confusion", 0.7, evidence)
    return None


def _stable_probability(seed: str) -> float:
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]
    return int(digest, 16) / 0xFFFFFFFF


def _state_seed(state: dict[str, Any] | None) -> str:
    state = _as_dict(state)
    clock = _as_dict(state.get("simTime") or state.get("operatingClock"))
    return json.dumps(clock, sort_keys=True, default=str, separators=(",", ":"))[:240] or "parkpulse-live-ticket-seed"


def _ticket_from_generated_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    issue_type = _normalize_issue_type(str(candidate.get("issue_type") or "angry_parent"))
    severity = _normalize_severity(str(candidate.get("severity") or ""), issue_type)
    source = str(candidate.get("source") or "place_risk")
    place_id = str(candidate.get("place_id") or "")
    return {
        "event": "park_issue_ticket_generated",
        "id": _stable_id(
            "park-issue",
            {
                "source": source,
                "place_id": place_id,
                "issue_type": issue_type,
                "matched_rule": candidate.get("matched_rule"),
            },
        ),
        "source": source,
        "issue_type": issue_type,
        "severity": severity,
        "location": str(candidate.get("location") or place_id)[:120] or None,
        "reporter_role": "dynamic_park_backend",
        "summary": str(candidate.get("summary") or "Generated park issue.")[:1000],
        "required_action": str(candidate.get("required_action") or _default_required_action(issue_type))[:500],
        "assigned_team": TEAM_BY_ISSUE.get(issue_type) or "ops_lead",
        "status": "unresolved",
        "live_ops_authority": True,
        "requires_human_ack": severity in {"high", "critical"} or issue_type in HIGH_RISK_ISSUES,
        "created_at": _now_iso(),
        "derived_from": source,
        "dynamic_park_issue_id": place_id or None,
        "place_id": place_id or None,
        "evidence": [str(item) for item in _as_list(candidate.get("evidence"))][:12],
        "classification_confidence": candidate.get("classification_confidence", 0.7),
        "severity_confidence": candidate.get("severity_confidence", 0.75),
        "ticket_generation_trace": {
            "decision": "generated",
            "source": source,
            "matched_rule": candidate.get("matched_rule"),
            "causal_chain": [str(item) for item in _as_list(candidate.get("causal_chain"))][:12],
            "human_ack_required_reason": "high_risk_issue_type_or_severity" if severity in {"high", "critical"} or issue_type in HIGH_RISK_ISSUES else "not_required",
        },
        "boundary": "Generated from dynamic park place or incident risk; high-risk actions still require human acknowledgement before live dispatch.",
    }


def _issue_type_from_backlog_issue(issue: dict[str, Any]) -> str:
    blob = " ".join(str(issue.get(key) or "") for key in ("id", "domain", "title", "current", "recommendedNext")).lower()
    if any(term in blob for term in ("accessibility", "mobility", "privacy", "accommodation")):
        return "accessibility_accommodation"
    if any(term in blob for term in ("safety", "storm", "weather", "access", "crowd", "showtime", "traffic")):
        return "weather_evacuation_confusion"
    if any(term in blob for term in ("medical", "first aid", "heat", "care")):
        return "heat_exhaustion_concern"
    if any(term in blob for term in ("line", "merge", "queue conflict", "cutting")):
        return "line_cutting_conflict"
    if any(term in blob for term in ("refund", "compensation", "finance", "recovery", "food", "eta", "backlog")):
        return "refund_request"
    if any(term in blob for term in ("fairness", "complaint", "trust", "guest", "customer")):
        return "angry_parent"
    return "ride_closure_complaint"


def _backlog_classification_confidence(issue_id: str, issue_type: str) -> float:
    if issue_id in BACKLOG_ISSUE_MAP:
        return 0.92
    if issue_type in {"line_cutting_conflict", "ride_closure_complaint"}:
        return 0.78
    if issue_type in {"refund_request", "angry_parent"}:
        return 0.74
    return 0.68


def _severity_from_backlog_issue(issue: dict[str, Any]) -> str:
    raw = str(issue.get("severity") or "").lower()
    if raw == "critical":
        return "critical"
    if raw in {"warning", "high"}:
        return "high"
    if raw in {"low", "medium"}:
        return raw
    return "medium"


def _backlog_issue_summary(issue: dict[str, Any]) -> str:
    title = str(issue.get("title") or "Dynamic park issue")
    current = str(issue.get("current") or "").strip()
    impact = str(issue.get("businessImpact") or "").strip()
    parts = [title]
    if current:
        parts.append(current)
    if impact:
        parts.append(impact)
    return " / ".join(parts)[:1000]


def _default_required_action(issue_type: str) -> str:
    return {
        "lost_child_report": "Route to Security/Ops and keep guardian at a meeting point.",
        "injury_or_safety_incident": "Route to Safety and First Aid; preserve the scene and prevent additional guest exposure.",
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
    park_tickets = [row for row in events if row.get("event") in {"park_issue_ticket_created", "park_issue_ticket_generated"}]
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


def build_auto_learning_governance(signals: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [_auto_learning_candidate(signal, events) for signal in signals]
    auto_candidates = [candidate for candidate in candidates if candidate["governance_status"] == "candidate_auto_drafted"]
    shadow_ready = [candidate for candidate in auto_candidates if candidate["shadow_deployment"]["status"] == "shadow_ready"]
    exception_queue = [candidate for candidate in candidates if candidate["governance_status"] == "human_exception_required"]
    return {
        "mode": "human_on_exception_auto_learning_governance",
        "auto_candidate_count": len(auto_candidates),
        "shadow_ready_count": len(shadow_ready),
        "human_exception_count": len(exception_queue),
        "auto_learning_candidates": auto_candidates[-80:],
        "shadow_deployment_candidates": shadow_ready[-80:],
        "human_exception_queue": exception_queue[-80:],
        "eval_contract": {
            "auto_promote_live_ops": False,
            "auto_promote_training_content": True,
            "auto_promote_ops_checklists": True,
            "activation_mode": "shadow_first_then_auto_promote_low_risk_only",
            "exception_policy": "Safety, injury, lost child, heat, weather evacuation, accessibility, refund, low-confidence, and failed-eval changes require human review.",
        },
        "rollback_rules": [
            "rollback if golden regression fails",
            "rollback if staff score worsens after shadow comparison",
            "rollback if live ticket rate rises for the affected scenario",
            "rollback if policy boundary contradiction appears",
        ],
    }


def _auto_learning_candidate(signal: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    scenario = str((signal.get("affected_scenarios") or ["unknown"])[0] if isinstance(signal.get("affected_scenarios"), list) else "unknown")
    related = _related_events_for_signal(signal, events)
    confidence = _signal_confidence(signal, related)
    evidence_count = int(_number(signal.get("evidence_count"), len(related)))
    exception_reasons = _human_exception_reasons(scenario, related, confidence, evidence_count)
    gates = _automated_eval_gates(signal, related, confidence, evidence_count, exception_reasons)
    gate_pass = all(gate["status"] == "pass" for gate in gates)
    low_risk = not exception_reasons
    status = "candidate_auto_drafted" if low_risk and gate_pass else "human_exception_required"
    candidate = {
        "id": _stable_id("auto-learning", {"signal": signal.get("id"), "scenario": scenario, "pattern": signal.get("pattern")}),
        "signal_id": signal.get("id"),
        "source": signal.get("source"),
        "scenario_id": scenario,
        "pattern": signal.get("pattern"),
        "proposed_change_type": signal.get("proposed_change_type"),
        "governance_status": status,
        "evidence_count": evidence_count,
        "confidence": confidence,
        "risk_class": "low" if low_risk else "exception",
        "exception_reasons": exception_reasons,
        "draft": _auto_draft_for_signal(signal, scenario),
        "automated_eval_gates": gates,
        "shadow_deployment": {
            "status": "shadow_ready" if status == "candidate_auto_drafted" and gate_pass else "blocked",
            "live_active": False,
            "compares_against": "current_training_and_ops_guidance",
            "promotion_rule": "auto_promote_low_risk_after_shadow_metrics_hold",
        },
        "rollback": {
            "version_id": _stable_id("learning-version", {"signal": signal.get("id"), "scenario": scenario}),
            "trigger": "eval_failure_or_negative_shadow_metric",
            "expires_after_days": 14,
        },
        "boundary": "Auto learning drafts and shadow candidates only; no live dispatch or high-risk behavior changes without exception handling.",
    }
    return candidate


def _related_events_for_signal(signal: dict[str, Any], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scenario = str((signal.get("affected_scenarios") or [""])[0] if isinstance(signal.get("affected_scenarios"), list) else "")
    source = str(signal.get("source") or "")
    if source == "park_issue_ticket":
        return [event for event in events if event.get("event") in {"park_issue_ticket_created", "park_issue_ticket_generated"} and event.get("issue_type") == scenario]
    if source == "training_gap_ticket":
        return [event for event in events if event.get("event") == "training_gap_ticket_created" and event.get("scenario_id") == scenario]
    return [
        event
        for event in events
        if event.get("issue_type") == scenario or event.get("scenario_id") == scenario
    ]


def _signal_confidence(signal: dict[str, Any], related: list[dict[str, Any]]) -> float:
    confidences = [_number(event.get("classification_confidence"), -1) for event in related]
    valid = [value for value in confidences if value >= 0]
    if valid:
        return round(sum(valid) / len(valid), 2)
    evidence_count = int(_number(signal.get("evidence_count"), len(related)))
    return round(_bounded(0.55 + min(evidence_count, 8) * 0.06, 0.55, 0.86), 2)


def _human_exception_reasons(scenario: str, related: list[dict[str, Any]], confidence: float, evidence_count: int) -> list[str]:
    reasons: list[str] = []
    if scenario in HUMAN_EXCEPTION_ISSUES:
        reasons.append("protected_or_high_risk_issue_type")
    severities = {str(event.get("severity") or "").lower() for event in related}
    if "critical" in severities or any(event.get("requires_human_ack") is True for event in related):
        reasons.append("critical_or_ack_required_ticket")
    if confidence < AUTO_LEARNING_MIN_CONFIDENCE:
        reasons.append("low_confidence")
    if evidence_count < AUTO_LEARNING_MIN_EVIDENCE:
        reasons.append("insufficient_evidence")
    if any(str(event.get("source") or "") == "random_incident" for event in related):
        reasons.append("seeded_incident_requires_observation")
    return sorted(set(reasons))


def _automated_eval_gates(
    signal: dict[str, Any],
    related: list[dict[str, Any]],
    confidence: float,
    evidence_count: int,
    exception_reasons: list[str],
) -> list[dict[str, Any]]:
    gates = [
        {
            "id": "golden_regression",
            "status": "pass" if evidence_count >= AUTO_LEARNING_MIN_EVIDENCE else "fail",
            "summary": "Enough repeated evidence to test against golden roleplay/checklist cases.",
        },
        {
            "id": "policy_boundary",
            "status": "pass" if "protected_or_high_risk_issue_type" not in exception_reasons else "blocked",
            "summary": "Blocks high-risk, refund, accessibility, and safety-sensitive auto activation.",
        },
        {
            "id": "confidence_threshold",
            "status": "pass" if confidence >= AUTO_LEARNING_MIN_CONFIDENCE else "fail",
            "summary": f"Signal confidence {confidence:.2f}; threshold {AUTO_LEARNING_MIN_CONFIDENCE:.2f}.",
        },
        {
            "id": "no_live_dispatch",
            "status": "pass",
            "summary": "Candidate cannot dispatch, refund, reopen, close, or change live ops directly.",
        },
        {
            "id": "shadow_metric_guard",
            "status": "pass" if "seeded_incident_requires_observation" not in exception_reasons else "blocked",
            "summary": "Shadow comparison required before promotion; random incidents need observation before auto-use.",
        },
    ]
    if any(event.get("live_ops_authority") is True and event.get("requires_human_ack") is True for event in related):
        gates.append(
            {
                "id": "human_ack_boundary",
                "status": "blocked",
                "summary": "Related live ticket requires human acknowledgement, so the learning change cannot auto-promote.",
            }
        )
    return gates


def _auto_draft_for_signal(signal: dict[str, Any], scenario: str) -> dict[str, Any]:
    change_type = str(signal.get("proposed_change_type") or "training_prompt_candidate")
    readable = scenario.replace("_", " ")
    return {
        "title": f"Auto-draft {change_type.replace('_', ' ')} for {readable}",
        "target_surface": "staff_training" if signal.get("source") in {"park_issue_ticket", "manager_review"} else "ops_checklist",
        "draft_status": "candidate_auto_drafted",
        "content_summary": str(signal.get("recommendation") or f"Update guidance for {readable}.")[:500],
        "activation": "shadow_only",
    }


def product_learning_loop_status(
    limit: int = 500,
    operational_backlog: dict[str, Any] | None = None,
    park_state: dict[str, Any] | None = None,
    incident_seed: str | None = None,
) -> dict[str, Any]:
    events = _read_events(limit)
    backlog_tickets = generate_park_issue_tickets_from_operational_backlog(operational_backlog) if isinstance(operational_backlog, dict) else []
    park_state_tickets = generate_park_issue_tickets_from_park_state(park_state, seed=incident_seed) if isinstance(park_state, dict) else []
    dynamic_tickets = [*backlog_tickets, *park_state_tickets]
    signal_events = [*events, *dynamic_tickets]
    park_tickets = [row for row in signal_events if row.get("event") in {"park_issue_ticket_created", "park_issue_ticket_generated"}]
    training_gaps = [row for row in events if row.get("event") == "training_gap_ticket_created"]
    signals = _derive_product_learning_signals(signal_events)
    auto_governance = build_auto_learning_governance(signals, signal_events)
    place_risk_graph = build_place_risk_graph(park_state) if isinstance(park_state, dict) else {"mode": "unavailable", "places": []}
    return {
        "status": "ready",
        "mode": "product_learning_loop",
        "park_issue_ticket_count": len(park_tickets),
        "dynamic_park_issue_ticket_count": len(dynamic_tickets),
        "operational_backlog_issue_ticket_count": len(backlog_tickets),
        "place_risk_issue_ticket_count": sum(1 for ticket in park_state_tickets if ticket.get("source") == "place_risk"),
        "random_incident_issue_ticket_count": sum(1 for ticket in park_state_tickets if ticket.get("source") == "random_incident"),
        "training_gap_ticket_count": len(training_gaps),
        "learning_signal_count": len(signals),
        "auto_learning_candidate_count": auto_governance["auto_candidate_count"],
        "shadow_ready_candidate_count": auto_governance["shadow_ready_count"],
        "human_exception_candidate_count": auto_governance["human_exception_count"],
        "park_issue_tickets": park_tickets[-80:],
        "training_gap_tickets": training_gaps[-80:],
        "product_learning_signals": signals[-120:],
        "auto_learning_governance": auto_governance,
        "auto_learning_candidates": auto_governance["auto_learning_candidates"],
        "shadow_deployment_candidates": auto_governance["shadow_deployment_candidates"],
        "human_exception_queue": auto_governance["human_exception_queue"],
        "place_risk_graph": place_risk_graph,
        "ticket_generation_traces": [ticket.get("ticket_generation_trace") for ticket in dynamic_tickets if isinstance(ticket.get("ticket_generation_trace"), dict)][-120:],
        "loop_contract": {
            "live_tickets_improve_training": "via reviewed ProductLearningSignal and golden eval only",
            "training_gaps_help_ops": "via reviewed checklist/prompt candidates only",
            "training_gaps_create_live_issues": False,
            "low_risk_auto_learning": "auto draft, automated eval, shadow first, rollback guarded",
            "human_on_exception": True,
            "llm_guest_controls_score": False,
            "simulated_data_feeds_reward_model": False,
        },
        "boundary": "Separates live operational tickets from simulated training gaps; both can produce reviewed product-learning signals.",
    }
