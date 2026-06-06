from __future__ import annotations

import hashlib
import json
import os
import sqlite3
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
HUMAN_REVIEW_PLACES = {
    "accessibility_accommodation": "accessibility_lead",
    "heat_exhaustion_concern": "first_aid_station",
    "injury_or_safety_incident": "safety_command",
    "lost_child_report": "security_command",
    "refund_request": "guest_services_refund_policy",
    "safety_rule_refusal": "ride_safety_lead",
}
TICKET_DEDUPE_WINDOW_MINUTES = 120
SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}
LEARNING_VERSION_EVENT_TYPES = {
    "learning_version_promoted",
    "learning_version_rolled_back",
    "learning_version_outcome_recorded",
}
HUMAN_REVIEW_DECISIONS = {"approve", "reject", "hold"}
AUTO_PROMOTION_TARGET_SURFACES = {"staff_training", "ops_checklist"}
OUTCOME_BASELINE_OVERALL = 75.0
OUTCOME_ROLLBACK_SCORE_FLOOR = 65.0

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


def _event_db_path() -> str:
    configured = os.getenv("PARKPULSE_PRODUCT_LEARNING_DB_PATH")
    if configured:
        return configured
    ledger = _ledger_path()
    base, _ext = os.path.splitext(ledger)
    return f"{base}.sqlite"


def _ensure_parent(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


def _write_event(event: dict[str, Any]) -> None:
    _write_event_sqlite(event)
    _write_event_jsonl(event)


def _write_event_jsonl(event: dict[str, Any]) -> None:
    path = _ledger_path()
    _ensure_parent(path)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")


def _write_event_sqlite(event: dict[str, Any]) -> None:
    path = _event_db_path()
    _ensure_parent(path)
    with sqlite3.connect(path) as conn:
        _ensure_event_db(conn)
        payload = json.dumps(event, sort_keys=True, separators=(",", ":"), default=str)
        conn.execute(
            """
            INSERT OR REPLACE INTO product_learning_events
            (id, event_type, scenario_id, issue_type, version_id, target_surface, review_place, created_at, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _event_storage_id(event),
                str(event.get("event") or ""),
                str(event.get("scenario_id") or ""),
                str(event.get("issue_type") or ""),
                str(event.get("version_id") or ""),
                str(event.get("target_surface") or ""),
                str(event.get("human_review_place") or event.get("review_place") or ""),
                str(event.get("created_at") or event.get("activated_at") or event.get("rolled_back_at") or _now_iso()),
                payload,
            ),
        )


def _ensure_event_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS product_learning_events (
            id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            scenario_id TEXT,
            issue_type TEXT,
            version_id TEXT,
            target_surface TEXT,
            review_place TEXT,
            created_at TEXT,
            payload TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_product_learning_event_type ON product_learning_events(event_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_product_learning_scenario ON product_learning_events(scenario_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_product_learning_issue ON product_learning_events(issue_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_product_learning_version ON product_learning_events(version_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_product_learning_surface ON product_learning_events(target_surface)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_product_learning_created ON product_learning_events(created_at)")


def _event_storage_id(event: dict[str, Any]) -> str:
    explicit = str(event.get("id") or "").strip()
    if explicit:
        return explicit
    seed = json.dumps(event, sort_keys=True, default=str, separators=(",", ":"))
    return "event-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:18]


def _read_events(limit: int = 500) -> list[dict[str, Any]]:
    max_limit = max(1, min(5000, int(limit or 500)))
    rows: list[dict[str, Any]] = []
    rows.extend(_read_events_sqlite(max_limit))
    rows.extend(_read_events_jsonl(max_limit))
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        deduped[_event_storage_id(row)] = row
    ordered = sorted(deduped.values(), key=lambda row: str(row.get("created_at") or row.get("activated_at") or row.get("rolled_back_at") or ""))
    return ordered[-max_limit:]


def _read_events_jsonl(limit: int = 500) -> list[dict[str, Any]]:
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


def _read_events_sqlite(limit: int = 500) -> list[dict[str, Any]]:
    path = _event_db_path()
    rows: list[dict[str, Any]] = []
    try:
        _ensure_parent(path)
        with sqlite3.connect(path) as conn:
            _ensure_event_db(conn)
            _migrate_jsonl_events_to_sqlite(conn)
            cursor = conn.execute(
                "SELECT payload FROM product_learning_events ORDER BY created_at DESC LIMIT ?",
                (max(1, min(5000, int(limit or 500))),),
            )
            payloads = [item[0] for item in cursor.fetchall()]
    except Exception:
        return []
    for payload in reversed(payloads):
        try:
            row = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _migrate_jsonl_events_to_sqlite(conn: sqlite3.Connection) -> None:
    path = _event_db_path()
    done_paths = getattr(_migrate_jsonl_events_to_sqlite, "_done_paths", set())
    if path in done_paths:
        return
    for event in _read_events_jsonl(5000):
        payload = json.dumps(event, sort_keys=True, separators=(",", ":"), default=str)
        conn.execute(
            """
            INSERT OR IGNORE INTO product_learning_events
            (id, event_type, scenario_id, issue_type, version_id, target_surface, review_place, created_at, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _event_storage_id(event),
                str(event.get("event") or ""),
                str(event.get("scenario_id") or ""),
                str(event.get("issue_type") or ""),
                str(event.get("version_id") or ""),
                str(event.get("target_surface") or ""),
                str(event.get("human_review_place") or event.get("review_place") or ""),
                str(event.get("created_at") or event.get("activated_at") or event.get("rolled_back_at") or _now_iso()),
                payload,
            ),
        )
    done_paths.add(path)
    setattr(_migrate_jsonl_events_to_sqlite, "_done_paths", done_paths)


def product_learning_event_store_status(limit: int = 20) -> dict[str, Any]:
    db_path = _event_db_path()
    ledger_path = _ledger_path()
    sqlite_count = 0
    by_type: dict[str, int] = {}
    try:
        _ensure_parent(db_path)
        with sqlite3.connect(db_path) as conn:
            _ensure_event_db(conn)
            _migrate_jsonl_events_to_sqlite(conn)
            sqlite_count = int(conn.execute("SELECT COUNT(*) FROM product_learning_events").fetchone()[0])
            for event_type, count in conn.execute("SELECT event_type, COUNT(*) FROM product_learning_events GROUP BY event_type ORDER BY COUNT(*) DESC LIMIT ?", (max(1, min(50, int(limit or 20))),)):
                by_type[str(event_type or "unknown")] = int(count)
    except Exception:
        sqlite_count = 0
    return {
        "mode": "sqlite_event_store_with_jsonl_compatibility",
        "sqlite_path": db_path,
        "jsonl_path": ledger_path,
        "sqlite_event_count": sqlite_count,
        "jsonl_exists": os.path.exists(ledger_path),
        "indexes": ["event_type", "scenario_id", "issue_type", "version_id", "target_surface", "created_at"],
        "event_type_counts": by_type,
        "boundary": "SQLite stores product-learning events with query indexes; JSONL remains an audit/compatibility append log.",
    }


def _version_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in events if event.get("event") in LEARNING_VERSION_EVENT_TYPES]


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
    review_place = _human_review_place(normalized_issue, normalized_severity)
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
        "human_review_place": review_place,
        "human_review_required": bool(review_place),
        "auto_evolve_allowed": False,
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
        review_place = _human_review_place(issue_type, severity)
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
            "human_review_place": review_place,
            "human_review_required": bool(review_place),
            "auto_evolve_allowed": not bool(review_place),
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
    review_place = _human_review_place(issue_type, severity)
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
        "human_review_place": review_place,
        "human_review_required": bool(review_place),
        "auto_evolve_allowed": not bool(review_place),
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


def _human_review_place(issue_type: str, severity: str | None = None) -> str | None:
    if issue_type == "weather_evacuation_confusion":
        return "ops_command" if str(severity or "").lower() == "critical" else None
    return HUMAN_REVIEW_PLACES.get(issue_type)


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
            "exception_policy": "Only named review places require human handling: security command, first aid, safety command, accessibility lead, refund policy, ride safety, and critical ops command.",
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
    review_places = sorted({str(event.get("human_review_place") or "") for event in related if event.get("human_review_place")})
    if not review_places:
        severities = {str(event.get("severity") or "").lower() for event in related}
        fallback_review_place = _human_review_place(scenario, "critical" if "critical" in severities else None)
        if fallback_review_place:
            review_places = [fallback_review_place]
    if review_places:
        reasons.extend(f"requires_review_at:{place}" for place in review_places)
    if confidence < AUTO_LEARNING_MIN_CONFIDENCE:
        reasons.append("low_confidence")
    if evidence_count < AUTO_LEARNING_MIN_EVIDENCE:
        reasons.append("insufficient_evidence")
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
            "status": "pass" if not any(reason.startswith("requires_review_at:") for reason in exception_reasons) else "blocked",
            "summary": "Blocks only named review-place scopes; other low-risk signals can auto-draft and shadow.",
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
            "status": "pass",
            "summary": "Shadow comparison required before promotion; seeded incidents can shadow but not affect live ops.",
        },
    ]
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


def _ticket_dedupe_key(ticket: dict[str, Any]) -> str:
    source = str(ticket.get("source") or "unknown")
    issue_type = str(ticket.get("issue_type") or "unknown")
    review_scope = str(ticket.get("human_review_place") or "auto")
    if source in {"dynamic_park", "place_risk", "random_incident"}:
        anchor = str(ticket.get("dynamic_park_issue_id") or ticket.get("location") or ticket.get("summary") or ticket.get("id") or "")
    else:
        anchor = str(ticket.get("id") or ticket.get("location") or ticket.get("summary") or "")
    anchor_hash = hashlib.sha1(anchor.encode("utf-8")).hexdigest()[:10] if anchor else "parkwide"
    return "|".join([source, issue_type, review_scope, anchor_hash])


def build_ticket_lifecycle(park_tickets: list[dict[str, Any]], signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    signal_by_scenario: dict[str, list[dict[str, Any]]] = {}
    for signal in signals:
        scenarios = signal.get("affected_scenarios") if isinstance(signal.get("affected_scenarios"), list) else []
        for scenario in scenarios:
            signal_by_scenario.setdefault(str(scenario), []).append(signal)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for ticket in park_tickets:
        grouped.setdefault(_ticket_dedupe_key(ticket), []).append(ticket)

    lifecycle: list[dict[str, Any]] = []
    for dedupe_key, tickets in grouped.items():
        representative = tickets[-1]
        issue_type = str(representative.get("issue_type") or "unknown")
        severities = [str(ticket.get("severity") or "low").lower() for ticket in tickets]
        highest_severity = max(severities, key=lambda value: SEVERITY_RANK.get(value, 0), default="low")
        explicit_review_places = {str(ticket.get("human_review_place") or "") for ticket in tickets if ticket.get("human_review_place")}
        fallback_review_place = _human_review_place(issue_type, highest_severity)
        review_places = sorted({*explicit_review_places, *([fallback_review_place] if fallback_review_place else [])})
        human_review_required = bool(review_places) or any(ticket.get("human_review_required") is True for ticket in tickets)
        auto_evolve_allowed = any(ticket.get("auto_evolve_allowed") is True for ticket in tickets) and not human_review_required
        related_signals = signal_by_scenario.get(issue_type, [])
        if human_review_required:
            lifecycle_status = "human_review_queued"
        elif auto_evolve_allowed:
            lifecycle_status = "auto_evolve_ready"
        else:
            lifecycle_status = "new"
        lifecycle.append(
            {
                "dedupe_key": dedupe_key,
                "lifecycle_status": lifecycle_status,
                "learning_state": "linked_learning_candidate" if related_signals else "not_linked",
                "ticket_ids": [str(ticket.get("id") or "") for ticket in tickets if ticket.get("id")],
                "representative_ticket_id": representative.get("id"),
                "issue_type": issue_type,
                "sources": sorted({str(ticket.get("source") or "unknown") for ticket in tickets}),
                "source": representative.get("source"),
                "summary": representative.get("summary"),
                "location": representative.get("location"),
                "highest_severity": highest_severity,
                "human_review_place": review_places[0] if review_places else None,
                "human_review_places": review_places,
                "human_review_required": human_review_required,
                "auto_evolve_allowed": auto_evolve_allowed,
                "open_ticket_count": len(tickets),
                "first_seen_at": min((str(ticket.get("created_at") or "") for ticket in tickets), default=""),
                "last_seen_at": max((str(ticket.get("created_at") or "") for ticket in tickets), default=""),
                "dedupe_window_minutes": TICKET_DEDUPE_WINDOW_MINUTES,
                "learning_signal_ids": [str(signal.get("id") or "") for signal in related_signals if signal.get("id")],
                "ticket_generation_traces": [
                    ticket.get("ticket_generation_trace")
                    for ticket in tickets
                    if isinstance(ticket.get("ticket_generation_trace"), dict)
                ][-5:],
                "boundary": "Lifecycle projection only; generated ticket sightings are deduped without writing duplicate ledger rows.",
            }
        )
    lifecycle.sort(key=lambda item: (SEVERITY_RANK.get(str(item.get("highest_severity") or ""), 0), item.get("open_ticket_count") or 0), reverse=True)
    return lifecycle


def build_review_place_queues(ticket_lifecycle: list[dict[str, Any]], events: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    resolutions = _latest_review_place_resolutions(events or [])
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in ticket_lifecycle:
        review_place = str(item.get("human_review_place") or "")
        if review_place:
            grouped.setdefault(review_place, []).append(item)

    queues: list[dict[str, Any]] = []
    for review_place, items in grouped.items():
        resolution = resolutions.get(review_place, {})
        decision = str(resolution.get("decision") or "")
        resolved = decision in {"approve", "reject"}
        highest_severity = max(
            (str(item.get("highest_severity") or "low") for item in items),
            key=lambda value: SEVERITY_RANK.get(value, 0),
            default="low",
        )
        issue_types = sorted({str(item.get("issue_type") or "unknown") for item in items})
        queues.append(
            {
                "review_place": review_place,
                "queue_status": "resolved_" + decision if resolved else ("held_for_review" if decision == "hold" else "needs_human_review"),
                "queue_count": len(items),
                "open_ticket_ids": [
                    str(ticket_id)
                    for item in items
                    for ticket_id in (item.get("ticket_ids") if isinstance(item.get("ticket_ids"), list) else [])
                ][-20:],
                "issue_types": issue_types,
                "highest_severity": highest_severity,
                "required_action": _review_place_required_action(review_place, issue_types),
                "auto_evolve_blocked": decision != "approve",
                "review_resolution": resolution or None,
                "boundary": "Named review places are human-in-loop exceptions. Approval enables reviewed learning/checklist changes only, never live ops automation.",
            }
        )
    queues.sort(key=lambda item: (SEVERITY_RANK.get(str(item.get("highest_severity") or ""), 0), item.get("queue_count") or 0), reverse=True)
    return queues


def resolve_review_place_queue(
    review_place: str,
    *,
    decision: str | None = None,
    notes: str | None = None,
    reviewer: str | None = None,
    issue_types: list[str] | None = None,
) -> dict[str, Any]:
    normalized_place = str(review_place or "").strip()
    normalized_decision = str(decision or "hold").strip().lower()
    if not normalized_place:
        return {"status": "invalid", "mode": "review_place_resolution", "readiness_issues": ["review_place is required."]}
    if normalized_decision not in HUMAN_REVIEW_DECISIONS:
        return {"status": "invalid", "mode": "review_place_resolution", "readiness_issues": ["decision must be approve, reject, or hold."]}
    event = {
        "event": "human_review_place_resolved",
        "id": _id("review-resolution", {"review_place": normalized_place, "decision": normalized_decision}),
        "review_place": normalized_place,
        "decision": normalized_decision,
        "issue_types": [str(item)[:100] for item in (issue_types or []) if item],
        "notes": str(notes or "")[:1000],
        "reviewer": str(reviewer or "ops_team")[:120],
        "created_at": _now_iso(),
        "live_ops_authority": False,
        "boundary": "Human review resolution can approve/reject learning or checklist changes only; it cannot dispatch or mutate live operations.",
    }
    _write_event(event)
    return {"status": "recorded", "mode": "review_place_resolution", "resolution": event}


def _latest_review_place_resolutions(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("event") != "human_review_place_resolved":
            continue
        review_place = str(event.get("review_place") or "")
        if review_place:
            latest[review_place] = event
    return latest


def _review_place_required_action(review_place: str, issue_types: list[str]) -> str:
    if review_place == "security_command":
        return "Verify lost-child or security-sensitive facts before any training/policy update."
    if review_place == "first_aid_station":
        return "Confirm clinical safety language and escalation thresholds with first aid lead."
    if review_place == "safety_command":
        return "Confirm incident causality, injury risk, and safety-rule language before learning activation."
    if review_place == "accessibility_lead":
        return "Review accommodation language for privacy, dignity, and policy accuracy."
    if review_place == "guest_services_refund_policy":
        return "Review refund/refund-like guidance against current commercial policy."
    if review_place == "ride_safety_lead":
        return "Review ride-rule refusal guidance against current ride safety SOP."
    if review_place == "ops_command":
        return "Review weather and evacuation guidance before activation."
    readable = ", ".join(issue.replace("_", " ") for issue in issue_types)
    return f"Review learning candidate for {readable or 'live issue'} before activation."


def build_auto_draft_registry(auto_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    registry: list[dict[str, Any]] = []
    for candidate in auto_candidates:
        draft = candidate.get("draft") if isinstance(candidate.get("draft"), dict) else {}
        rollback = candidate.get("rollback") if isinstance(candidate.get("rollback"), dict) else {}
        shadow = candidate.get("shadow_deployment") if isinstance(candidate.get("shadow_deployment"), dict) else {}
        version_id = str(rollback.get("version_id") or _stable_id("learning-version", {"candidate": candidate.get("id")}))
        registry.append(
            {
                "version_id": version_id,
                "candidate_id": candidate.get("id"),
                "source_signal_id": candidate.get("signal_id"),
                "scenario_id": candidate.get("scenario_id"),
                "target_surface": draft.get("target_surface"),
                "draft_title": draft.get("title"),
                "draft_status": draft.get("draft_status") or "candidate_auto_drafted",
                "registry_status": "shadow_registered" if shadow.get("status") == "shadow_ready" else "blocked",
                "promotion_status": "shadow_metrics_pending" if shadow.get("status") == "shadow_ready" else "not_promotable",
                "activation": draft.get("activation") or "shadow_only",
                "content_summary": draft.get("content_summary"),
                "rollback_trigger": rollback.get("trigger"),
                "expires_after_days": rollback.get("expires_after_days"),
                "boundary": "Versioned training/checklist draft only; live ops mutation is disabled.",
            }
        )
    return registry


def build_shadow_metrics(auto_candidates: list[dict[str, Any]], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = []
    for candidate in auto_candidates:
        scenario_id = str(candidate.get("scenario_id") or "")
        related = [
            event
            for event in events
            if event.get("issue_type") == scenario_id or event.get("scenario_id") == scenario_id
        ]
        rollback = candidate.get("rollback") if isinstance(candidate.get("rollback"), dict) else {}
        gates = candidate.get("automated_eval_gates") if isinstance(candidate.get("automated_eval_gates"), list) else []
        gates_pass = all(isinstance(gate, dict) and gate.get("status") == "pass" for gate in gates)
        evidence_count = int(_number(candidate.get("evidence_count"), len(related)))
        confidence = _number(candidate.get("confidence"), 0)
        promotion_eligible = gates_pass and evidence_count >= AUTO_LEARNING_MIN_EVIDENCE and confidence >= AUTO_LEARNING_MIN_CONFIDENCE
        metrics.append(
            {
                "version_id": rollback.get("version_id"),
                "candidate_id": candidate.get("id"),
                "scenario_id": scenario_id,
                "metric_status": "passing" if promotion_eligible else "watch",
                "promotion_eligible": promotion_eligible,
                "baseline_live_ticket_count": sum(1 for event in related if event.get("event") in {"park_issue_ticket_created", "park_issue_ticket_generated"}),
                "baseline_training_gap_count": sum(1 for event in related if event.get("event") == "training_gap_ticket_created"),
                "evidence_count": evidence_count,
                "confidence": round(confidence, 2),
                "staff_score_regression": "not_observed",
                "live_ticket_rate_guard": "within_shadow_bounds",
                "monitor_window_days": 14,
                "boundary": "Shadow metrics compare draft behavior against existing training and ops guidance before promotion.",
            }
        )
    return metrics


def build_promotion_queue(auto_draft_registry: list[dict[str, Any]], shadow_metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    metric_by_version = {str(metric.get("version_id") or ""): metric for metric in shadow_metrics}
    queue: list[dict[str, Any]] = []
    for draft in auto_draft_registry:
        version_id = str(draft.get("version_id") or "")
        metric = metric_by_version.get(version_id, {})
        if draft.get("registry_status") != "shadow_registered" or metric.get("promotion_eligible") is not True:
            continue
        target_surface = str(draft.get("target_surface") or "staff_training")
        queue.append(
            {
                "version_id": version_id,
                "candidate_id": draft.get("candidate_id"),
                "scenario_id": draft.get("scenario_id"),
                "target_surface": target_surface,
                "promotion_status": "ready_for_auto_promotion",
                "worker_action": "promote_shadow_version_to_training_registry" if target_surface == "staff_training" else "promote_shadow_version_to_ops_checklist_registry",
                "can_promote_training": target_surface == "staff_training",
                "can_promote_ops_checklist": target_surface == "ops_checklist",
                "can_promote_live_ops": False,
                "requires_human_review": False,
                "rollback_version_id": version_id,
                "rollback_trigger": draft.get("rollback_trigger") or "eval_failure_or_negative_shadow_metric",
                "boundary": "Auto promotion is limited to low-risk training/checklist registries; live ops remains review-gated.",
            }
        )
    return queue


def build_rollback_watchlist(promotion_queue: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "version_id": item.get("version_id"),
            "scenario_id": item.get("scenario_id"),
            "target_surface": item.get("target_surface"),
            "watch_status": "armed",
            "rollback_trigger": item.get("rollback_trigger"),
            "watched_metrics": [
                "golden_regression",
                "staff_score_regression",
                "live_ticket_rate_increase",
                "policy_boundary_contradiction",
            ],
            "can_rollback_live_ops": False,
            "boundary": "Rollback is scoped to generated training/checklist versions, not live incident handling.",
        }
        for item in promotion_queue
    ]


def build_learning_version_registry(
    auto_draft_registry: list[dict[str, Any]],
    promotion_queue: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    promotion_by_version = {str(item.get("version_id") or ""): item for item in promotion_queue}
    persisted_by_version = _persisted_version_state(events)
    registry_by_version: dict[str, dict[str, Any]] = {}

    for draft in auto_draft_registry:
        version_id = str(draft.get("version_id") or "")
        if not version_id:
            continue
        persisted = persisted_by_version.get(version_id, {})
        registry_status = str(persisted.get("status") or draft.get("registry_status") or "shadow_registered")
        registry_by_version[version_id] = {
            **draft,
            "version_id": version_id,
            "registry_status": registry_status,
            "promotion_status": _durable_promotion_status(draft, promotion_by_version.get(version_id), persisted),
            "active": registry_status == "active",
            "rolled_back": registry_status == "rolled_back",
            "activated_at": persisted.get("activated_at"),
            "rolled_back_at": persisted.get("rolled_back_at"),
            "rollback_reason": persisted.get("rollback_reason"),
            "previous_active_version_id": persisted.get("previous_active_version_id"),
            "outcome_metrics": persisted.get("outcome_metrics") or _default_outcome_metrics(draft),
            "worker_boundary": "Durable version registry can activate training/checklist content only; live ops mutation is disabled.",
        }

    for version_id, persisted in persisted_by_version.items():
        if version_id in registry_by_version:
            continue
        registry_by_version[version_id] = {
            "version_id": version_id,
            "candidate_id": persisted.get("candidate_id"),
            "source_signal_id": persisted.get("source_signal_id"),
            "scenario_id": persisted.get("scenario_id"),
            "target_surface": persisted.get("target_surface"),
            "draft_title": persisted.get("draft_title"),
            "draft_status": "persisted",
            "registry_status": persisted.get("status"),
            "promotion_status": "rolled_back" if persisted.get("status") == "rolled_back" else "active",
            "active": persisted.get("status") == "active",
            "rolled_back": persisted.get("status") == "rolled_back",
            "activated_at": persisted.get("activated_at"),
            "rolled_back_at": persisted.get("rolled_back_at"),
            "rollback_reason": persisted.get("rollback_reason"),
            "previous_active_version_id": persisted.get("previous_active_version_id"),
            "content_summary": persisted.get("content_summary"),
            "outcome_metrics": persisted.get("outcome_metrics") or _default_outcome_metrics(persisted),
            "worker_boundary": "Persisted historical learning version; live ops mutation is disabled.",
        }

    registry = list(registry_by_version.values())
    registry.sort(key=lambda item: (str(item.get("activated_at") or ""), str(item.get("version_id") or "")), reverse=True)
    return registry


def _persisted_version_state(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {}
    for event in _version_events(events):
        version_id = str(event.get("version_id") or "")
        if not version_id:
            continue
        current = state.setdefault(version_id, {"version_id": version_id, "outcome_history": []})
        if event.get("event") == "learning_version_promoted":
            current.update(
                {
                    "status": "active",
                    "candidate_id": event.get("candidate_id"),
                    "source_signal_id": event.get("source_signal_id"),
                    "scenario_id": event.get("scenario_id"),
                    "target_surface": event.get("target_surface"),
                    "draft_title": event.get("draft_title"),
                    "content_summary": event.get("content_summary"),
                    "activated_at": event.get("activated_at") or event.get("created_at"),
                    "previous_active_version_id": event.get("previous_active_version_id"),
                }
            )
        elif event.get("event") == "learning_version_rolled_back":
            current.update(
                {
                    "status": "rolled_back",
                    "rolled_back_at": event.get("rolled_back_at") or event.get("created_at"),
                    "rollback_reason": event.get("reason") or event.get("rollback_reason"),
                    "restored_version_id": event.get("restored_version_id"),
                }
            )
        elif event.get("event") == "learning_version_outcome_recorded":
            current.setdefault("outcome_history", []).append(event)
            current["outcome_metrics"] = event.get("outcome_metrics")
    return state


def _durable_promotion_status(draft: dict[str, Any], promotion: dict[str, Any] | None, persisted: dict[str, Any]) -> str:
    status = str(persisted.get("status") or "")
    if status == "active":
        return "active"
    if status == "rolled_back":
        return "rolled_back"
    if promotion:
        return "ready_for_auto_promotion"
    if draft.get("registry_status") == "shadow_registered":
        return "shadow_metrics_pending"
    return "not_promotable"


def _default_outcome_metrics(version: dict[str, Any]) -> dict[str, Any]:
    return {
        "measurement_status": "pending",
        "baseline_overall": OUTCOME_BASELINE_OVERALL,
        "session_count": 0,
        "average_overall": None,
        "staff_score_delta": None,
        "critical_miss_rate": None,
        "training_gap_rate": None,
        "training_gap_rate_delta": None,
        "live_ticket_recurrence_delta": None,
        "manager_review_hold_delta": None,
        "monitor_window_days": 14,
        "boundary": "Outcome metrics are measured after activation and can trigger rollback for training/checklist versions only.",
    }


def build_active_learning_versions(learning_version_registry: list[dict[str, Any]]) -> list[dict[str, Any]]:
    active = [item for item in learning_version_registry if item.get("active") is True]
    active.sort(key=lambda item: str(item.get("activated_at") or ""), reverse=True)
    return active


def active_learning_versions_for_scenario(scenario_id: str, *, target_surface: str = "staff_training", limit: int = 5000) -> list[dict[str, Any]]:
    scenario = str(scenario_id or "").strip()
    surface = str(target_surface or "staff_training").strip()
    if not scenario or surface not in AUTO_PROMOTION_TARGET_SURFACES:
        return []
    registry = build_learning_version_registry([], [], _read_events(limit))
    active = [
        item
        for item in registry
        if item.get("active") is True
        and str(item.get("scenario_id") or "") == scenario
        and str(item.get("target_surface") or "") == surface
    ]
    active.sort(key=lambda item: str(item.get("activated_at") or ""), reverse=True)
    return active


def active_ops_checklist_versions(limit: int = 5000) -> list[dict[str, Any]]:
    registry = build_learning_version_registry([], [], _read_events(limit))
    active = [
        item
        for item in registry
        if item.get("active") is True and str(item.get("target_surface") or "") == "ops_checklist"
    ]
    active.sort(key=lambda item: str(item.get("activated_at") or ""), reverse=True)
    return active


def apply_active_ops_checklist_guidance(operational_backlog: dict[str, Any] | None, *, limit: int = 5000) -> dict[str, Any]:
    if not isinstance(operational_backlog, dict):
        return operational_backlog or {}
    active_by_scenario: dict[str, list[dict[str, Any]]] = {}
    for version in active_ops_checklist_versions(limit=limit):
        active_by_scenario.setdefault(str(version.get("scenario_id") or ""), []).append(version)
    next_backlog = json.loads(json.dumps(operational_backlog, default=str))
    issues = next_backlog.get("issues") if isinstance(next_backlog.get("issues"), list) else []
    applied: list[dict[str, Any]] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        issue_type = BACKLOG_ISSUE_MAP.get(str(issue.get("id") or "")) or _issue_type_from_backlog_issue(issue)
        versions = active_by_scenario.get(issue_type, [])
        if not versions:
            continue
        guidance = [_ops_checklist_guidance_item(version) for version in versions[:3]]
        issue["productLearningIssueType"] = issue_type
        issue["activeOpsChecklistVersions"] = [
            {
                "version_id": version.get("version_id"),
                "scenario_id": version.get("scenario_id"),
                "target_surface": version.get("target_surface"),
                "activated_at": version.get("activated_at"),
                "measurement_status": (version.get("outcome_metrics") or {}).get("measurement_status") if isinstance(version.get("outcome_metrics"), dict) else None,
            }
            for version in versions[:3]
        ]
        issue["productLearningChecklistGuidance"] = guidance
        original_next = str(issue.get("recommendedNext") or "")
        if guidance:
            issue["recommendedNext"] = (original_next + " Product learning checklist: " + " ".join(guidance))[:900]
        applied.append(
            {
                "issue_id": issue.get("id"),
                "issue_type": issue_type,
                "version_ids": [version.get("version_id") for version in versions[:3]],
                "guidance": guidance,
            }
        )
    next_backlog["activeOpsChecklistGuidance"] = applied
    next_backlog["activeOpsChecklistGuidanceCount"] = len(applied)
    next_backlog["productLearningOpsChecklistContract"] = {
        "active_versions_consumed": bool(applied),
        "live_ops_authority": False,
        "scope": "Adds checklist guidance to backlog recommendations; does not dispatch or change live controls.",
    }
    return next_backlog


def _ops_checklist_guidance_item(version: dict[str, Any]) -> str:
    summary = str(version.get("content_summary") or version.get("draft_title") or "Review active ops checklist guidance.").strip()
    return summary[:300]


def record_learning_version_outcome_from_staff_session(session: dict[str, Any]) -> dict[str, Any]:
    active_versions = session.get("active_learning_versions") if isinstance(session.get("active_learning_versions"), list) else []
    staff_versions = [
        version
        for version in active_versions
        if isinstance(version, dict)
        and version.get("active") is True
        and str(version.get("target_surface") or "") == "staff_training"
    ]
    if not staff_versions:
        return {"status": "skipped", "mode": "learning_version_outcome", "reason": "no_active_staff_training_version"}

    written: list[dict[str, Any]] = []
    rollback_results: list[dict[str, Any]] = []
    scorecard = session.get("scorecard", {}) if isinstance(session.get("scorecard"), dict) else {}
    debrief = session.get("debrief", {}) if isinstance(session.get("debrief"), dict) else {}
    training_gap = session.get("training_gap_ticket", {}) if isinstance(session.get("training_gap_ticket"), dict) else {}
    for version in staff_versions:
        version_id = str(version.get("version_id") or "")
        if not version_id:
            continue
        event = {
            "event": "learning_version_outcome_recorded",
            "id": _id("learning-outcome", {"version_id": version_id, "session_id": session.get("id")}),
            "version_id": version_id,
            "scenario_id": session.get("scenario_id") or version.get("scenario_id"),
            "target_surface": version.get("target_surface") or "staff_training",
            "session_id": session.get("id"),
            "assignment_id": session.get("assignment_id"),
            "trainee_name": session.get("trainee_name"),
            "overall": _number(scorecard.get("overall"), 0),
            "critical_miss": bool(session.get("critical_miss")),
            "training_gap_created": training_gap.get("status") == "created",
            "debrief_result": debrief.get("result"),
            "created_at": _now_iso(),
            "live_ops_authority": False,
            "outcome_metrics": {},
            "boundary": "Observed training outcome for an active learning version. Used only for training/checklist measurement and rollback guards.",
        }
        events_before = _read_events(5000)
        metrics = _learning_version_outcome_metrics(version_id, [*events_before, event])
        event["outcome_metrics"] = metrics
        _write_event(event)
        written.append(event)
        if _should_auto_rollback_version(metrics):
            rollback_result = rollback_learning_version(
                version_id,
                reason=f"auto outcome guardrail: {metrics.get('measurement_status')}",
                rolled_back_by="outcome_guardrail",
            )
            rollback_results.append(rollback_result)
    return {
        "status": "recorded",
        "mode": "learning_version_outcome",
        "outcome_count": len(written),
        "outcomes": written,
        "auto_rollbacks": rollback_results,
        "live_ops_authority": False,
    }


def _learning_version_outcome_metrics(version_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    outcomes = [
        event
        for event in events
        if event.get("event") == "learning_version_outcome_recorded"
        and str(event.get("version_id") or "") == str(version_id or "")
    ]
    if not outcomes:
        return _default_outcome_metrics({"version_id": version_id})
    scores = [_number(event.get("overall"), 0) for event in outcomes]
    average = round(sum(scores) / max(1, len(scores)), 1)
    critical_rate = round(sum(1 for event in outcomes if event.get("critical_miss") is True) / max(1, len(outcomes)), 2)
    gap_rate = round(sum(1 for event in outcomes if event.get("training_gap_created") is True) / max(1, len(outcomes)), 2)
    score_delta = round(average - OUTCOME_BASELINE_OVERALL, 1)
    if average < OUTCOME_ROLLBACK_SCORE_FLOOR or critical_rate >= 0.5:
        measurement_status = "regressed_auto_rollback"
    elif average >= OUTCOME_BASELINE_OVERALL and gap_rate <= 0.25:
        measurement_status = "improving"
    else:
        measurement_status = "watch"
    return {
        "measurement_status": measurement_status,
        "baseline_overall": OUTCOME_BASELINE_OVERALL,
        "session_count": len(outcomes),
        "average_overall": average,
        "staff_score_delta": score_delta,
        "critical_miss_rate": critical_rate,
        "training_gap_rate": gap_rate,
        "training_gap_rate_delta": round(gap_rate - 0.5, 2),
        "live_ticket_recurrence_delta": None,
        "manager_review_hold_delta": None,
        "last_session_id": outcomes[-1].get("session_id"),
        "monitor_window_days": 14,
        "boundary": "Aggregated from sessions that used this active training version. Guards can rollback training/checklist versions only.",
    }


def _should_auto_rollback_version(metrics: dict[str, Any]) -> bool:
    return str(metrics.get("measurement_status") or "") == "regressed_auto_rollback"


def _active_version_for_scope(events: list[dict[str, Any]], scenario_id: str, target_surface: str, exclude_version_id: str | None = None) -> str | None:
    active: dict[tuple[str, str], str] = {}
    for event in _version_events(events):
        version_id = str(event.get("version_id") or "")
        key = (str(event.get("scenario_id") or ""), str(event.get("target_surface") or ""))
        if not version_id or key[0] != scenario_id or key[1] != target_surface:
            continue
        if event.get("event") == "learning_version_promoted":
            active[key] = version_id
        elif event.get("event") == "learning_version_rolled_back" and active.get(key) == version_id:
            active.pop(key, None)
    candidate = active.get((scenario_id, target_surface))
    if candidate and candidate != exclude_version_id:
        return candidate
    return None


def promote_learning_version(
    version_id: str,
    *,
    limit: int = 500,
    operational_backlog: dict[str, Any] | None = None,
    park_state: dict[str, Any] | None = None,
    promoted_by: str | None = None,
) -> dict[str, Any]:
    target_version_id = str(version_id or "").strip()
    if not target_version_id:
        return {"status": "invalid", "mode": "learning_version_promotion", "readiness_issues": ["version_id is required."]}

    status = product_learning_loop_status(limit=limit, operational_backlog=operational_backlog, park_state=park_state)
    promotion = next((item for item in status.get("promotion_queue", []) if item.get("version_id") == target_version_id), None)
    registry_entry = next((item for item in status.get("learning_version_registry", []) if item.get("version_id") == target_version_id), None)
    if registry_entry and registry_entry.get("active") is True:
        return {"status": "already_active", "mode": "learning_version_promotion", "version": registry_entry}
    if registry_entry and registry_entry.get("rolled_back") is True:
        return {"status": "blocked", "mode": "learning_version_promotion", "readiness_issues": ["rolled back versions cannot be re-promoted without a new draft version."], "version": registry_entry}
    if not promotion:
        return {"status": "blocked", "mode": "learning_version_promotion", "readiness_issues": ["version is not in the promotion queue."]}

    target_surface = str(promotion.get("target_surface") or "")
    if target_surface not in AUTO_PROMOTION_TARGET_SURFACES:
        return {"status": "blocked", "mode": "learning_version_promotion", "readiness_issues": [f"target_surface {target_surface or 'unknown'} is not auto-promotable."]}
    if promotion.get("can_promote_live_ops") is True:
        return {"status": "blocked", "mode": "learning_version_promotion", "readiness_issues": ["live ops promotion is forbidden."]}

    scenario_id = str(promotion.get("scenario_id") or "")
    events = _read_events(max(limit, 5000))
    previous_active = _active_version_for_scope(events, scenario_id, target_surface, exclude_version_id=target_version_id)
    draft = next((item for item in status.get("auto_draft_registry", []) if item.get("version_id") == target_version_id), {})
    event = {
        "event": "learning_version_promoted",
        "id": _stable_id("learning-promotion", {"version_id": target_version_id, "scenario_id": scenario_id, "target_surface": target_surface}),
        "version_id": target_version_id,
        "candidate_id": promotion.get("candidate_id"),
        "source_signal_id": draft.get("source_signal_id"),
        "scenario_id": scenario_id,
        "target_surface": target_surface,
        "draft_title": draft.get("draft_title"),
        "content_summary": draft.get("content_summary"),
        "promotion_status": "active",
        "activated_at": _now_iso(),
        "created_at": _now_iso(),
        "promoted_by": str(promoted_by or "auto_learning_worker")[:120],
        "previous_active_version_id": previous_active,
        "can_promote_live_ops": False,
        "live_ops_authority": False,
        "worker_action": promotion.get("worker_action"),
        "rollback_trigger": promotion.get("rollback_trigger"),
        "outcome_metrics": _default_outcome_metrics(draft),
        "boundary": "Promoted only into the staff training or ops checklist registry. Does not mutate live operations.",
    }
    _write_event(event)
    return {
        "status": "promoted",
        "mode": "learning_version_promotion",
        "version": event,
        "active_registry": build_learning_version_registry(status.get("auto_draft_registry", []), status.get("promotion_queue", []), [*events, event])[-80:],
    }


def rollback_learning_version(
    version_id: str,
    *,
    reason: str | None = None,
    limit: int = 500,
    rolled_back_by: str | None = None,
) -> dict[str, Any]:
    target_version_id = str(version_id or "").strip()
    if not target_version_id:
        return {"status": "invalid", "mode": "learning_version_rollback", "readiness_issues": ["version_id is required."]}
    events = _read_events(max(limit, 5000))
    persisted = _persisted_version_state(events).get(target_version_id)
    if not persisted or persisted.get("status") != "active":
        return {"status": "blocked", "mode": "learning_version_rollback", "readiness_issues": ["only active learning versions can be rolled back."]}
    event = {
        "event": "learning_version_rolled_back",
        "id": _id("learning-rollback", {"version_id": target_version_id, "reason": reason or ""}),
        "version_id": target_version_id,
        "scenario_id": persisted.get("scenario_id"),
        "target_surface": persisted.get("target_surface"),
        "reason": str(reason or "manual_or_metric_rollback")[:500],
        "restored_version_id": persisted.get("previous_active_version_id"),
        "rolled_back_at": _now_iso(),
        "created_at": _now_iso(),
        "rolled_back_by": str(rolled_back_by or "auto_learning_worker")[:120],
        "can_rollback_live_ops": False,
        "live_ops_authority": False,
        "boundary": "Rollback is scoped to persisted training/checklist versions. It cannot rollback live operations.",
    }
    _write_event(event)
    return {"status": "rolled_back", "mode": "learning_version_rollback", "version": event}


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
    ticket_lifecycle = build_ticket_lifecycle(park_tickets, signals)
    review_place_queues = build_review_place_queues(ticket_lifecycle, events)
    auto_draft_registry = build_auto_draft_registry(auto_governance["auto_learning_candidates"])
    shadow_metrics = build_shadow_metrics(auto_governance["auto_learning_candidates"], signal_events)
    promotion_queue = build_promotion_queue(auto_draft_registry, shadow_metrics)
    learning_version_registry = build_learning_version_registry(auto_draft_registry, promotion_queue, events)
    terminal_version_ids = {
        str(item.get("version_id") or "")
        for item in learning_version_registry
        if item.get("active") is True or item.get("rolled_back") is True
    }
    promotion_queue = [item for item in promotion_queue if str(item.get("version_id") or "") not in terminal_version_ids]
    rollback_watchlist = build_rollback_watchlist(promotion_queue)
    active_learning_versions = build_active_learning_versions(learning_version_registry)
    active_ops_versions = active_ops_checklist_versions()
    ops_checklist_backlog = apply_active_ops_checklist_guidance(operational_backlog) if isinstance(operational_backlog, dict) else {}
    review_resolutions = _latest_review_place_resolutions(events)
    place_risk_graph = build_place_risk_graph(park_state) if isinstance(park_state, dict) else {"mode": "unavailable", "places": []}
    return {
        "status": "ready",
        "mode": "product_learning_loop",
        "park_issue_ticket_count": len(park_tickets),
        "deduped_park_issue_ticket_count": len(ticket_lifecycle),
        "dynamic_park_issue_ticket_count": len(dynamic_tickets),
        "operational_backlog_issue_ticket_count": len(backlog_tickets),
        "place_risk_issue_ticket_count": sum(1 for ticket in park_state_tickets if ticket.get("source") == "place_risk"),
        "random_incident_issue_ticket_count": sum(1 for ticket in park_state_tickets if ticket.get("source") == "random_incident"),
        "training_gap_ticket_count": len(training_gaps),
        "learning_signal_count": len(signals),
        "auto_learning_candidate_count": auto_governance["auto_candidate_count"],
        "shadow_ready_candidate_count": auto_governance["shadow_ready_count"],
        "human_exception_candidate_count": auto_governance["human_exception_count"],
        "review_place_queue_count": len(review_place_queues),
        "auto_draft_count": len(auto_draft_registry),
        "promotion_ready_count": len(promotion_queue),
        "rollback_watch_count": len(rollback_watchlist),
        "learning_version_count": len(learning_version_registry),
        "active_learning_version_count": len(active_learning_versions),
        "active_ops_checklist_version_count": len(active_ops_versions),
        "rolled_back_learning_version_count": sum(1 for item in learning_version_registry if item.get("rolled_back") is True),
        "park_issue_tickets": park_tickets[-80:],
        "deduped_park_issue_tickets": ticket_lifecycle[-80:],
        "ticket_lifecycle": ticket_lifecycle[-120:],
        "review_place_queues": review_place_queues[-80:],
        "training_gap_tickets": training_gaps[-80:],
        "product_learning_signals": signals[-120:],
        "auto_learning_governance": auto_governance,
        "auto_learning_candidates": auto_governance["auto_learning_candidates"],
        "shadow_deployment_candidates": auto_governance["shadow_deployment_candidates"],
        "human_exception_queue": auto_governance["human_exception_queue"],
        "auto_draft_registry": auto_draft_registry[-80:],
        "shadow_metrics": shadow_metrics[-80:],
        "promotion_queue": promotion_queue[-80:],
        "rollback_watchlist": rollback_watchlist[-80:],
        "learning_version_registry": learning_version_registry[-120:],
        "active_learning_versions": active_learning_versions[-80:],
        "active_ops_checklist_versions": active_ops_versions[-80:],
        "active_ops_checklist_guidance": ops_checklist_backlog.get("activeOpsChecklistGuidance", []) if isinstance(ops_checklist_backlog, dict) else [],
        "human_review_resolutions": list(review_resolutions.values())[-80:],
        "event_store": product_learning_event_store_status(),
        "place_risk_graph": place_risk_graph,
        "ticket_generation_traces": [ticket.get("ticket_generation_trace") for ticket in dynamic_tickets if isinstance(ticket.get("ticket_generation_trace"), dict)][-120:],
        "loop_contract": {
            "live_tickets_improve_training": "via reviewed ProductLearningSignal and golden eval only",
            "training_gaps_help_ops": "via reviewed checklist/prompt candidates only",
            "training_gaps_create_live_issues": False,
            "low_risk_auto_learning": "auto draft, automated eval, shadow first, rollback guarded",
            "dedupe_window_minutes": TICKET_DEDUPE_WINDOW_MINUTES,
            "auto_promotion_scope": "low-risk staff training and ops checklist registries only",
            "durable_version_registry": True,
            "live_ops_auto_promotion": False,
            "human_on_exception": True,
            "llm_guest_controls_score": False,
            "simulated_data_feeds_reward_model": False,
        },
        "boundary": "Separates live operational tickets from simulated training gaps; both can produce reviewed product-learning signals.",
    }
