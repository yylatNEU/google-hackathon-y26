from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
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
    "profile_information_request",
    "unclear_guest_request",
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
    "guest_question": "profile_information_request",
    "unknown": "unclear_guest_request",
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
    "profile_information_request": "guest_services",
    "unclear_guest_request": "guest_services",
}

HIGH_RISK_ISSUES = {"lost_child_report", "heat_exhaustion_concern", "injury_or_safety_incident", "safety_rule_refusal", "weather_evacuation_confusion"}
HUMAN_EXCEPTION_ISSUES = HIGH_RISK_ISSUES | {"accessibility_accommodation", "refund_request", "unclear_guest_request"}
AUTO_LEARNING_MIN_EVIDENCE = 2
AUTO_LEARNING_MIN_CONFIDENCE = 0.74
HUMAN_REVIEW_PLACES = {
    "accessibility_accommodation": "accessibility_lead",
    "heat_exhaustion_concern": "first_aid_station",
    "injury_or_safety_incident": "safety_command",
    "lost_child_report": "security_command",
    "refund_request": "guest_services_refund_policy",
    "safety_rule_refusal": "ride_safety_lead",
    "unclear_guest_request": "guest_services_information_desk",
}
ISSUE_TICKET_SOURCES = {"guest", "employee", "historical_park_data", "dynamic_park", "place_risk", "random_incident"}
STABLE_ISSUE_TICKET_SOURCES = {"historical_park_data", "dynamic_park", "place_risk", "random_incident"}
TICKET_DEDUPE_WINDOW_MINUTES = 120
SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}
LOW_ATTENDANCE_CROWD_TICKET_FLOOR = 500
MIN_PATH_GUESTS_FOR_CROWD_TICKET = 250
LEARNING_VERSION_EVENT_TYPES = {
    "learning_version_promoted",
    "learning_version_rolled_back",
    "learning_version_outcome_recorded",
}
HUMAN_REVIEW_DECISIONS = {"approve", "reject", "hold"}
AUTO_PROMOTION_TARGET_SURFACES = {"staff_training", "ops_checklist"}
OUTCOME_BASELINE_OVERALL = 75.0
OUTCOME_ROLLBACK_SCORE_FLOOR = 65.0
TRAINING_SCENARIO_BY_GUEST_ISSUE = {
    "angry_parent": "angry_parent",
    "lost_child_report": "lost_child_report",
    "ride_closure_complaint": "ride_closure_complaint",
    "accessibility_accommodation": "accessibility_accommodation",
    "language_barrier": "language_barrier",
    "refund_request": "refund_request",
    "heat_exhaustion_concern": "heat_exhaustion_concern",
    "line_cutting_conflict": "line_cutting_conflict",
    "safety_rule_refusal": "safety_rule_refusal",
    "weather_evacuation_confusion": "weather_evacuation_confusion",
    "injury_or_safety_incident": "heat_exhaustion_concern",
    "profile_information_request": "language_barrier",
    "unclear_guest_request": "angry_parent",
}

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

GUEST_TRIAGE_RULES = [
    {
        "issue_type": "lost_child_report",
        "terms": ("lost child", "missing child", "can't find my child", "cannot find my child", "my kid is gone", "missing kid", "lost my son", "lost my daughter"),
        "urgency": "critical",
        "score": 98,
        "sla": 1,
    },
    {
        "issue_type": "heat_exhaustion_concern",
        "terms": ("faint", "dizzy", "pale", "heat", "dehydrated", "passed out", "heat exhaustion", "too hot", "medical"),
        "urgency": "critical",
        "score": 94,
        "sla": 2,
    },
    {
        "issue_type": "injury_or_safety_incident",
        "terms": ("injured", "hurt", "bleeding", "fell", "slipped", "accident", "collision", "broken", "can't stand", "cannot stand"),
        "urgency": "critical",
        "score": 96,
        "sla": 1,
    },
    {
        "issue_type": "weather_evacuation_confusion",
        "terms": ("storm", "lightning", "evacuation", "shelter", "where do we go", "weather", "tornado", "severe weather"),
        "urgency": "high",
        "score": 86,
        "sla": 3,
    },
    {
        "issue_type": "safety_rule_refusal",
        "terms": ("won't follow", "refuses", "refusing", "safety rule", "restraint", "seatbelt", "lap bar", "loose item"),
        "urgency": "high",
        "score": 84,
        "sla": 3,
    },
    {
        "issue_type": "line_cutting_conflict",
        "terms": ("line cutting", "cut the line", "argument", "fight", "pushing", "queue conflict", "threatening"),
        "urgency": "high",
        "score": 82,
        "sla": 5,
    },
    {
        "issue_type": "accessibility_accommodation",
        "terms": ("wheelchair", "accessibility", "accessible", "mobility", "accommodation", "medical history", "can't stand", "cannot stand"),
        "urgency": "high",
        "score": 78,
        "sla": 8,
    },
    {
        "issue_type": "refund_request",
        "terms": ("refund", "money back", "compensation", "paid for", "wasted money", "credit"),
        "urgency": "medium",
        "score": 56,
        "sla": 20,
    },
    {
        "issue_type": "ride_closure_complaint",
        "terms": ("ride closed", "closed ride", "closure", "waited and closed", "not operating", "down"),
        "urgency": "medium",
        "score": 52,
        "sla": 15,
    },
    {
        "issue_type": "language_barrier",
        "terms": ("no english", "do not understand", "don't understand", "language", "translator", "interpreter", "ticket problem"),
        "urgency": "medium",
        "score": 50,
        "sla": 10,
    },
    {
        "issue_type": "profile_information_request",
        "terms": (
            "where is",
            "where are",
            "closest",
            "nearest",
            "restroom",
            "bathroom",
            "toilet",
            "first aid",
            "guest services",
            "lost and found",
            "food",
            "eat",
            "vegetarian",
            "vegan",
            "water refill",
            "water fountain",
            "quiet",
            "sensory",
            "shade",
            "cooling",
            "height requirement",
            "how tall",
            "show time",
            "duration",
            "locker",
            "stroller",
        ),
        "urgency": "low",
        "score": 42,
        "sla": 20,
    },
    {
        "issue_type": "angry_parent",
        "terms": ("angry", "upset", "crying", "ridiculous", "manager", "complaint", "frustrated", "family"),
        "urgency": "medium",
        "score": 48,
        "sla": 15,
    },
]


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


def _scenario_for_guest_issue(issue_type: str | None) -> str:
    normalized = _normalize_issue_type(issue_type)
    return TRAINING_SCENARIO_BY_GUEST_ISSUE.get(normalized, normalized)


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


def _compact_guest_triage_memory_document(event: dict[str, Any], ticket_result: dict[str, Any] | None = None) -> dict[str, Any]:
    issue_type = _normalize_issue_type(str(event.get("issue_type") or "unclear_guest_request"))
    scenario_id = _scenario_for_guest_issue(issue_type)
    ticket = ticket_result.get("ticket") if isinstance(ticket_result, dict) and isinstance(ticket_result.get("ticket"), dict) else {}
    created_at = str(event.get("created_at") or _now_iso())
    checklist = event.get("staff_checklist") if isinstance(event.get("staff_checklist"), list) else []
    return {
        "_id": f"guest_triage_{event.get('id') or _stable_id('guest-triage-memory', event)}",
        "documentType": "guest_triage_memory",
        "source": "guest_message_triage",
        "createdAt": created_at,
        "updatedAt": created_at,
        "scenarioKey": scenario_id,
        "issueType": issue_type,
        "severity": event.get("severity"),
        "urgency": event.get("urgency"),
        "urgencyScore": event.get("urgency_score"),
        "confidence": (event.get("understanding") or {}).get("confidence") if isinstance(event.get("understanding"), dict) else None,
        "channel": event.get("channel"),
        "location": event.get("location"),
        "guestNamePresent": bool(event.get("guest_name")),
        "messageExcerpt": str(event.get("message_excerpt") or "")[:500],
        "guestReplyDraft": str(event.get("guest_reply_draft") or "")[:600],
        "staffChecklist": [str(item)[:240] for item in checklist[:6]],
        "assignedTeam": event.get("assigned_team"),
        "humanReviewPlace": event.get("human_review_place"),
        "humanAckRequired": bool(event.get("human_ack_required")),
        "ticketId": ticket.get("id") or event.get("ticket_id"),
        "trainingUse": {
            "targetSurface": "staff_training",
            "recommendedScenarioId": scenario_id,
            "usesRawGuestIdentity": False,
            "requiresManagerReview": True,
        },
        "boundary": "Guest triage memory can suggest staff training scenarios only; it cannot dispatch live operations or train a reward model automatically.",
    }


def _record_guest_triage_memory(event: dict[str, Any], ticket_result: dict[str, Any] | None = None) -> dict[str, Any]:
    document = _compact_guest_triage_memory_document(event, ticket_result)
    try:
        from mongo_memory import _clean_for_bson, _ensure_memory_initialized, _memory

        _ensure_memory_initialized()
        collection = _memory._collection("guest_messages")
        if collection is not None:
            collection.replace_one({"_id": document["_id"]}, _clean_for_bson(document), upsert=True)
            return {
                "status": "stored",
                "mode": "mongodb_guest_triage_memory",
                "collection": "guest_messages",
                "document_id": document["_id"],
                "scenario_id": document["scenarioKey"],
            }
        _memory._fallback["guest_messages"] = [
            row for row in _memory._fallback.get("guest_messages", []) if row.get("_id") != document["_id"]
        ]
        _memory._fallback["guest_messages"].insert(0, document)
        _memory._fallback["guest_messages"] = _memory._fallback["guest_messages"][:200]
        return {
            "status": "stored",
            "mode": "mongo_memory_fallback_guest_triage",
            "collection": "guest_messages",
            "document_id": document["_id"],
            "scenario_id": document["scenarioKey"],
        }
    except Exception as error:
        return {
            "status": "skipped",
            "mode": "mongodb_guest_triage_memory",
            "collection": "guest_messages",
            "reason": str(error)[:180],
            "scenario_id": document.get("scenarioKey"),
        }


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


def _guest_triage_memory_rows_from_mongo(limit: int) -> list[dict[str, Any]]:
    try:
        from mongo_memory import get_latest_memory_documents

        documents = get_latest_memory_documents("guest_messages", max(1, min(500, int(limit or 100))))
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for document in documents:
        if not isinstance(document, dict):
            continue
        document_type = str(document.get("documentType") or "")
        if document_type != "guest_triage_memory":
            continue
        issue_type = str(document.get("issueType") or document.get("issue_type") or "")
        scenario_id = str(document.get("scenarioKey") or document.get("scenario_id") or _scenario_for_guest_issue(issue_type))
        if not scenario_id:
            continue
        rows.append(
            {
                "id": str(document.get("id") or document.get("_id") or ""),
                "source": "mongodb_guest_messages",
                "scenario_id": scenario_id,
                "issue_type": _normalize_issue_type(issue_type),
                "severity": str(document.get("severity") or "medium"),
                "urgency": str(document.get("urgency") or ""),
                "urgency_score": document.get("urgencyScore") if document.get("urgencyScore") is not None else document.get("urgency_score"),
                "human_review_place": document.get("humanReviewPlace") or document.get("human_review_place"),
                "assigned_team": document.get("assignedTeam") or document.get("assigned_team"),
                "summary": str(document.get("messageExcerpt") or document.get("message") or "")[:500],
                "staff_checklist": document.get("staffChecklist") if isinstance(document.get("staffChecklist"), list) else [],
                "guest_reply_draft": str(document.get("guestReplyDraft") or document.get("message") or "")[:600],
                "created_at": str(document.get("createdAt") or document.get("created_at") or ""),
                "memory_source": "mongodb",
            }
        )
    return rows


def _guest_triage_memory_rows_from_events(limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in _read_events(max(1, min(5000, int(limit or 100)))):
        if event.get("event") not in {"guest_message_triaged", "park_issue_ticket_created", "park_issue_ticket_generated"}:
            continue
        if event.get("event") in {"park_issue_ticket_created", "park_issue_ticket_generated"} and str(event.get("source") or "") not in ISSUE_TICKET_SOURCES:
            continue
        issue_type = _normalize_issue_type(str(event.get("issue_type") or "unclear_guest_request"))
        rows.append(
            {
                "id": str(event.get("id") or ""),
                "source": f"local_{event.get('source') or 'product_learning'}_ticket",
                "scenario_id": _scenario_for_guest_issue(issue_type),
                "issue_type": issue_type,
                "severity": str(event.get("severity") or "medium"),
                "urgency": str(event.get("urgency") or ""),
                "urgency_score": event.get("urgency_score"),
                "human_review_place": event.get("human_review_place"),
                "assigned_team": event.get("assigned_team"),
                "summary": str(event.get("message_excerpt") or event.get("summary") or "")[:500],
                "staff_checklist": event.get("staff_checklist") if isinstance(event.get("staff_checklist"), list) else [],
                "guest_reply_draft": str(event.get("guest_reply_draft") or "")[:600],
                "created_at": str(event.get("created_at") or ""),
                "memory_source": "sqlite_jsonl",
            }
        )
    return rows


def _dedupe_guest_triage_memory_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("id") or "")
        if not key:
            key = _stable_id("guest-triage-memory-row", {"scenario": row.get("scenario_id"), "summary": row.get("summary"), "created": row.get("created_at")})
        existing = deduped.get(key)
        if existing and existing.get("memory_source") == "mongodb":
            continue
        deduped[key] = row
    return sorted(deduped.values(), key=lambda item: str(item.get("created_at") or ""), reverse=True)


def guest_triage_training_memory(scenario_id: str | None = None, *, limit: int = 80) -> dict[str, Any]:
    safe_limit = max(1, min(500, int(limit or 80)))
    target_scenario = str(scenario_id or "").strip()
    rows = _dedupe_guest_triage_memory_rows(
        [
            *_guest_triage_memory_rows_from_mongo(safe_limit),
            *_guest_triage_memory_rows_from_events(max(safe_limit, 500)),
        ]
    )
    if target_scenario:
        rows = [row for row in rows if str(row.get("scenario_id") or "") == target_scenario]
    issue_groups: dict[str, list[dict[str, Any]]] = {}
    scenario_groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        issue_groups.setdefault(str(row.get("issue_type") or "unclear_guest_request"), []).append(row)
        scenario_groups.setdefault(str(row.get("scenario_id") or _scenario_for_guest_issue(str(row.get("issue_type") or ""))), []).append(row)
    scenario_frequencies = []
    for scenario_key, group in scenario_groups.items():
        severities = [str(item.get("severity") or "medium") for item in group]
        highest = sorted(severities, key=lambda value: SEVERITY_RANK.get(value, 0), reverse=True)[0] if severities else "medium"
        sources: dict[str, int] = {}
        issue_types: dict[str, int] = {}
        for item in group:
            source = str(item.get("source") or "unknown")
            issue = str(item.get("issue_type") or "unknown")
            sources[source] = sources.get(source, 0) + 1
            issue_types[issue] = issue_types.get(issue, 0) + 1
        scenario_frequencies.append(
            {
                "scenario_id": scenario_key,
                "ticket_count": len(group),
                "highest_severity": highest,
                "latest_summary": str(group[0].get("summary") or "")[:240],
                "latest_created_at": str(group[0].get("created_at") or ""),
                "sources": sources,
                "issue_types": issue_types,
                "frequency_label": f"{len(group)} historical tickets/signals",
            }
        )
    scenario_frequencies.sort(key=lambda item: (int(item.get("ticket_count") or 0), SEVERITY_RANK.get(str(item.get("highest_severity") or ""), 0)), reverse=True)
    patterns = []
    for issue_type, group in issue_groups.items():
        highest = sorted((str(item.get("severity") or "medium") for item in group), key=lambda value: SEVERITY_RANK.get(value, 0), reverse=True)[0]
        latest = group[0]
        patterns.append(
            {
                "issue_type": issue_type,
                "scenario_id": str(latest.get("scenario_id") or _scenario_for_guest_issue(issue_type)),
                "count": len(group),
                "frequency": len(group),
                "frequency_label": f"{len(group)} historical tickets/signals",
                "highest_severity": highest,
                "latest_summary": str(latest.get("summary") or "")[:240],
                "latest_created_at": str(latest.get("created_at") or ""),
                "human_review_place": latest.get("human_review_place"),
                "assigned_team": latest.get("assigned_team"),
                "recommended_action": f"Prioritize {str(latest.get('scenario_id') or _scenario_for_guest_issue(issue_type)).replace('_', ' ')} roleplay from training memory and historical ticket frequency.",
            }
        )
    patterns.sort(key=lambda item: (int(item.get("count") or 0), SEVERITY_RANK.get(str(item.get("highest_severity") or ""), 0)), reverse=True)
    recent_examples = [
        {
            "id": row.get("id"),
            "source": row.get("source"),
            "scenario_id": row.get("scenario_id"),
            "issue_type": row.get("issue_type"),
            "severity": row.get("severity"),
            "summary": row.get("summary"),
            "staff_checklist": row.get("staff_checklist", [])[:4] if isinstance(row.get("staff_checklist"), list) else [],
            "created_at": row.get("created_at"),
        }
        for row in rows[: min(10, safe_limit)]
    ]
    return {
        "status": "ready" if rows else "empty",
        "mode": "guest_triage_training_memory",
        "scenario_id": target_scenario or None,
        "memory_source": "mongodb_plus_sqlite_jsonl",
        "memory_count": len(rows),
        "patterns": patterns[:12],
        "scenario_frequencies": scenario_frequencies[:12],
        "recent_examples": recent_examples,
        "assignment_recommendation": patterns[0] if patterns else None,
        "boundary": "Guest triage memory recommends staff training only. It does not approve live operations, refunds, dispatch, or model promotion.",
    }


def recommended_training_scenarios_from_guest_triage(*, limit: int = 6) -> list[dict[str, Any]]:
    memory = guest_triage_training_memory(limit=max(80, int(limit or 6) * 20))
    by_scenario: dict[str, dict[str, Any]] = {}
    for pattern in memory.get("patterns", []):
        scenario_id = str(pattern.get("scenario_id") or "")
        if not scenario_id:
            continue
        current = by_scenario.setdefault(
            scenario_id,
            {
                "scenario_id": scenario_id,
                "issue_types": [],
                "evidence_count": 0,
                "highest_severity": "low",
                "latest_summary": "",
                "latest_created_at": "",
                "source": "guest_triage_memory",
                "requires_manager_review": True,
            },
        )
        current["issue_types"].append(pattern.get("issue_type"))
        current["evidence_count"] = int(current.get("evidence_count") or 0) + int(pattern.get("count") or 0)
        if SEVERITY_RANK.get(str(pattern.get("highest_severity") or ""), 0) > SEVERITY_RANK.get(str(current.get("highest_severity") or ""), 0):
            current["highest_severity"] = pattern.get("highest_severity")
        if str(pattern.get("latest_created_at") or "") > str(current.get("latest_created_at") or ""):
            current["latest_created_at"] = pattern.get("latest_created_at")
            current["latest_summary"] = pattern.get("latest_summary")
    recommendations = list(by_scenario.values())
    recommendations.sort(key=lambda item: (SEVERITY_RANK.get(str(item.get("highest_severity") or ""), 0), int(item.get("evidence_count") or 0)), reverse=True)
    return recommendations[: max(1, min(20, int(limit or 6)))]


def _guest_triage_memory_impact(issue_type: str, persistence: dict[str, Any] | None = None) -> dict[str, Any]:
    scenario_id = _scenario_for_guest_issue(issue_type)
    memory = guest_triage_training_memory(scenario_id, limit=80)
    frequencies = memory.get("scenario_frequencies") if isinstance(memory.get("scenario_frequencies"), list) else []
    frequency = frequencies[0] if frequencies and isinstance(frequencies[0], dict) else {}
    examples = memory.get("recent_examples") if isinstance(memory.get("recent_examples"), list) else []
    patterns = memory.get("patterns") if isinstance(memory.get("patterns"), list) else []
    stored = bool(isinstance(persistence, dict) and persistence.get("status") == "stored")
    return {
        "mode": "guest_triage_to_staff_training_memory_impact",
        "stored": stored,
        "storage_mode": (persistence or {}).get("mode") if isinstance(persistence, dict) else None,
        "collection": (persistence or {}).get("collection") if isinstance(persistence, dict) else None,
        "document_id": (persistence or {}).get("document_id") if isinstance(persistence, dict) else None,
        "training_scenario_id": scenario_id,
        "recommended_action": f"Start or prioritize {scenario_id.replace('_', ' ')} roleplay for the relevant staff role.",
        "memory_count": memory.get("memory_count", 0),
        "historical_ticket_frequency": {
            "ticket_count": frequency.get("ticket_count", 0),
            "highest_severity": frequency.get("highest_severity"),
            "frequency_label": frequency.get("frequency_label"),
            "sources": frequency.get("sources") if isinstance(frequency.get("sources"), dict) else {},
            "issue_types": frequency.get("issue_types") if isinstance(frequency.get("issue_types"), dict) else {},
        },
        "top_patterns": patterns[:3],
        "recent_examples": examples[:3],
        "visible_benefit": "This triage is now retrievable by employee training for scenario selection, roleplay context, and LLM guest simulation context.",
        "boundary": "Memory benefit is limited to staff-training recommendations and context; it does not dispatch live actions or promote models automatically.",
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
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(raw)):
        char = raw[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(raw[start : index + 1])
                    return parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def _sanitize_guest_triage_llm_reply(value: Any, fallback_reply: str) -> str:
    reply = " ".join(str(value or "").replace("\n", " ").split())
    if not reply:
        return fallback_reply
    lowered = reply.lower()
    blocked = (
        "as an ai",
        "your score",
        "rubric",
        "trainer",
        "trainee",
        "approve refund",
        "refund approved",
        "i approved",
        "dispatching security",
        "dispatching medical",
        "ride is safe",
        "diagnosis",
        "medical diagnosis",
        "guarantee",
        "live availability is confirmed",
    )
    if any(term in lowered for term in blocked):
        return fallback_reply
    return reply[:520]


def _guest_message_acknowledgement(message: str, issue_type: str, profile_context: dict[str, Any]) -> str:
    text = " ".join(str(message or "").split())
    lowered = text.lower()
    if issue_type == "profile_information_request":
        category = str(profile_context.get("category") or "")
        if category == "food_dietary":
            if "coaster" in lowered:
                return "You are looking for vegetarian food near the coaster."
            return "You are looking for vegetarian food options in the park."
        if category == "water_cooling_quiet":
            return "You are looking for a quieter cooling or water-refill spot."
        if category == "accessibility_map":
            return "You are asking for accessibility information from the park profile."
        return "You are asking for park information I can check against the park profile."
    if issue_type == "refund_request":
        if "closed" in lowered or "waited" in lowered:
            return "I hear that you waited and the ride was closed, and you want the refund reviewed."
        return "I hear that you want help with a refund review."
    if issue_type == "lost_child_report":
        if "carousel" in lowered:
            return "I understand your child is missing near the carousel."
        return "I understand you cannot find your child."
    if issue_type == "heat_exhaustion_concern":
        return "I understand someone with you feels dizzy or unwell in the heat."
    if issue_type == "accessibility_accommodation":
        return "I hear that your group needs accessibility help without sharing private medical details."
    if issue_type == "line_cutting_conflict":
        return "I hear that people are yelling after a line-cutting conflict."
    if issue_type == "weather_evacuation_confusion":
        return "I hear that you need clearer shelter or evacuation directions."
    if issue_type == "language_barrier":
        return "I hear that you need help understanding the next step clearly."
    return "I hear what you are asking for."


def _conversational_guest_reply(message: str, issue_type: str, base_reply: str, profile_context: dict[str, Any]) -> str:
    acknowledgement = _guest_message_acknowledgement(message, issue_type, profile_context)
    base = " ".join(str(base_reply or "").split())
    if not base:
        return acknowledgement
    if base.lower().startswith(acknowledgement.lower()):
        return base[:620]
    return f"{acknowledgement} {base}"[:620]


def _generate_gemini_json_sync_hard_timeout(
    prompt: dict[str, Any],
    *,
    timeout_seconds: float,
    max_output_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    worker_path = Path(__file__).resolve().with_name("gemini_hard_timeout.py")
    request = {
        "prompt": prompt,
        "max_output_tokens": max_output_tokens,
        "temperature": temperature,
        "timeout_seconds": timeout_seconds,
    }
    env = os.environ.copy()
    env.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")
    try:
        completed = subprocess.run(
            [sys.executable, str(worker_path)],
            input=json.dumps(request, sort_keys=True, separators=(",", ":")),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            close_fds=False,
            timeout=max(0.5, timeout_seconds) + 0.5,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise TimeoutError(f"Gemini provider exceeded hard timeout of {timeout_seconds:g}s") from error
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(detail[:500] or f"Gemini worker exited with code {completed.returncode}")
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as error:
        raise RuntimeError("Gemini worker returned invalid JSON") from error
    if not payload.get("ok"):
        raise RuntimeError(str(payload.get("error") or "Gemini worker failed")[:500])
    return payload


def _guest_triage_llm_prompt(
    *,
    message: str,
    classification: dict[str, Any],
    profile_context: dict[str, Any],
    routing: dict[str, Any],
    staff_checklist: list[str],
    memory_impact: dict[str, Any],
    fallback_reply: str,
) -> dict[str, Any]:
    return {
        "task": "Draft the first guest-facing response for an amusement park guest-message triage. Return strict JSON.",
        "hard_rules": [
            "Write directly to the guest in first person from staff perspective.",
            "Start by naturally acknowledging the guest's actual message, using their specific concern, location, or request. Do not answer as a generic policy notice.",
            "Use the active park profile evidence when profile_context is answered_from_profile.",
            "Do not promise a refund, compensation, dispatch, ride safety, live availability, staffing, closure status, or medical diagnosis.",
            "If human acknowledgement or review is required, say the issue is being routed to the right team for review.",
            "Keep the response under 85 words.",
            "Do not mention hidden policy, rubric, memory stores, MongoDB, or training systems.",
        ],
        "guest_message": message[:1000],
        "classification": {
            "issue_type": classification.get("issue_type"),
            "urgency": classification.get("urgency"),
            "severity": classification.get("severity"),
            "confidence": classification.get("confidence"),
            "matched_terms": classification.get("matched_terms", [])[:6] if isinstance(classification.get("matched_terms"), list) else [],
        },
        "profile_context": {
            "status": profile_context.get("status"),
            "venue_name": profile_context.get("venue_name"),
            "category": profile_context.get("category"),
            "matched_locations": [
                {
                    "name": item.get("name"),
                    "kind": item.get("kind"),
                    "services": item.get("services", [])[:4] if isinstance(item.get("services"), list) else [],
                    "dietary_tags": item.get("dietary_tags", [])[:4] if isinstance(item.get("dietary_tags"), list) else [],
                    "accessibility_note": item.get("accessibility_note"),
                    "sensory_note": item.get("sensory_note"),
                }
                for item in (profile_context.get("matched_locations") if isinstance(profile_context.get("matched_locations"), list) else [])[:4]
                if isinstance(item, dict)
            ],
            "limitations": profile_context.get("limitations", [])[:4] if isinstance(profile_context.get("limitations"), list) else [],
        },
        "routing": routing,
        "staff_checklist": staff_checklist[:5],
        "training_memory_signal": {
            "training_scenario_id": memory_impact.get("training_scenario_id"),
            "memory_count": memory_impact.get("memory_count"),
            "frequency": memory_impact.get("historical_ticket_frequency"),
        },
        "fallback_reply_if_uncertain": fallback_reply,
        "required_conversational_opening": _guest_message_acknowledgement(message, str(classification.get("issue_type") or ""), profile_context),
        "response_schema": {
            "guest_reply": "string under 85 words",
            "tone": "one of calm|urgent|empathetic|direct",
            "used_profile": "boolean",
            "next_step": "short string",
            "confidence": "number from 0 to 1",
        },
    }


def _generate_guest_triage_llm_response(
    *,
    message: str,
    classification: dict[str, Any],
    profile_context: dict[str, Any],
    routing: dict[str, Any],
    staff_checklist: list[str],
    memory_impact: dict[str, Any],
    fallback_reply: str,
) -> dict[str, Any]:
    try:
        from gemini_provider import get_gemini_agent_properties, get_gemini_model

        props = get_gemini_agent_properties()
        if not props.ready:
            return {
                "status": "fallback_not_configured",
                "source": "deterministic",
                "reply": fallback_reply,
                "provider": props.provider,
                "platform": props.platform,
                "readiness_issues": props.readiness_issues,
                "required_env": props.required_env,
                "llm_controls_live_ops": False,
            }
        timeout_seconds = float(os.getenv("PARKPULSE_GUEST_TRIAGE_LLM_TIMEOUT_SECONDS", "4"))
        prompt = _guest_triage_llm_prompt(
            message=message,
            classification=classification,
            profile_context=profile_context,
            routing=routing,
            staff_checklist=staff_checklist,
            memory_impact=memory_impact,
            fallback_reply=fallback_reply,
        )
        result = _generate_gemini_json_sync_hard_timeout(
            prompt,
            timeout_seconds=timeout_seconds,
            max_output_tokens=int(os.getenv("PARKPULSE_GUEST_TRIAGE_LLM_MAX_OUTPUT_TOKENS", "260")),
            temperature=float(os.getenv("PARKPULSE_GUEST_TRIAGE_LLM_TEMPERATURE", "0.45")),
        )
        parsed = _first_json_object(str(result.get("text") or ""))
        reply = _sanitize_guest_triage_llm_reply((parsed or {}).get("guest_reply"), fallback_reply)
        source = "llm_guest_triage" if reply != fallback_reply else "deterministic"
        return {
            "status": "generated" if source == "llm_guest_triage" else "fallback_sanitized",
            "source": source,
            "reply": reply,
            "model": get_gemini_model(),
            "provider": props.provider,
            "platform": props.platform,
            "transport": result.get("transport"),
            "timeout_seconds": timeout_seconds,
            "tone": (parsed or {}).get("tone"),
            "used_profile": bool((parsed or {}).get("used_profile")),
            "next_step": (parsed or {}).get("next_step"),
            "confidence": (parsed or {}).get("confidence"),
            "llm_controls_live_ops": False,
        }
    except Exception as error:
        is_timeout = isinstance(error, TimeoutError) or "timeout" in str(error).lower() or "timed out" in str(error).lower()
        return {
            "status": "fallback_timeout" if is_timeout else "fallback_error",
            "source": "deterministic",
            "reply": fallback_reply,
            "readiness_issues": [str(error)[:240]],
            "llm_controls_live_ops": False,
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
    source_batch_id: str | None = None,
    historical_window: str | None = None,
    observed_at: str | None = None,
    stable_key: str | None = None,
) -> dict[str, Any]:
    normalized_source = str(source or "employee").strip().lower()
    if normalized_source not in ISSUE_TICKET_SOURCES:
        return {"status": "invalid", "mode": "park_issue_ticket", "readiness_issues": [f"source must be one of {', '.join(sorted(ISSUE_TICKET_SOURCES))}."]}
    normalized_issue = _normalize_issue_type(issue_type)
    normalized_severity = _normalize_severity(severity, normalized_issue)
    review_place = _human_review_place(normalized_issue, normalized_severity)
    stable_import_key = str(stable_key or "").strip()
    stable_payload = (
        {
            "source": normalized_source,
            "source_batch_id": str(source_batch_id or "")[:120],
            "stable_key": stable_import_key[:240],
        }
        if stable_import_key
        else {
            "source": normalized_source,
            "issue_type": normalized_issue,
            "summary": str(summary or "")[:1000],
            "location": str(location or "")[:120],
            "source_batch_id": str(source_batch_id or "")[:120],
            "historical_window": str(historical_window or "")[:120],
            "observed_at": str(observed_at or "")[:80],
        }
    )
    ticket_id = (
        _stable_id("park-issue", stable_payload)
        if normalized_source in STABLE_ISSUE_TICKET_SOURCES or stable_import_key
        else _id("park-issue", {"source": normalized_source, "issue_type": normalized_issue, "summary": summary or ""})
    )
    ticket = {
        "event": "park_issue_ticket_created",
        "id": ticket_id,
        "scenario_id": _scenario_for_guest_issue(normalized_issue),
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
        "observed_at": str(observed_at or "")[:80] or None,
        "source_batch_id": str(source_batch_id or "")[:120] or None,
        "historical_window": str(historical_window or "")[:120] or None,
        "dedupe_key": ticket_id if normalized_source in STABLE_ISSUE_TICKET_SOURCES or stable_import_key else None,
        "boundary": (
            "Imported or generated issue ticket for product-learning and staff-training memory; high-risk actions still require human acknowledgement before live dispatch."
            if normalized_source in STABLE_ISSUE_TICKET_SOURCES
            else "Real guest/employee issue ticket; high-risk actions require human acknowledgement before live dispatch."
        ),
    }
    _write_event(ticket)
    return {"status": "created", "mode": "park_issue_ticket", "ticket": ticket, "feeds_training_model": "via_product_learning_signal_only"}


def triage_guest_message(
    *,
    message: str | None = None,
    guest_name: str | None = None,
    location: str | None = None,
    channel: str | None = None,
    create_ticket: bool = True,
) -> dict[str, Any]:
    text = str(message or "").strip()
    if not text:
        return {"status": "invalid", "mode": "guest_message_triage", "readiness_issues": ["message is required."]}
    classification = _classify_guest_message(text)
    issue_type = classification["issue_type"]
    profile_context = _guest_triage_profile_context(text, issue_type)
    if issue_type == "profile_information_request" and profile_context.get("status") != "answered_from_profile":
        issue_type = "unclear_guest_request"
        classification = {
            **classification,
            "issue_type": issue_type,
            "urgency": "medium",
            "urgency_score": max(int(classification.get("urgency_score") or 0), 55),
            "sla_minutes": 10,
            "confidence": min(float(classification.get("confidence") or 0.5), 0.52),
        }
    severity = _severity_for_triage(classification["urgency"])
    review_place = _human_review_place(issue_type, severity)
    staff_checklist = _guest_triage_staff_checklist(issue_type)
    base_reply_draft = str(profile_context.get("guest_reply_draft") or _guest_reply_draft(issue_type)) if issue_type == "profile_information_request" else _guest_reply_draft(issue_type)
    reply_draft = _conversational_guest_reply(text, issue_type, base_reply_draft, profile_context)
    human_ack_required = bool(review_place) or severity in {"high", "critical"} or bool(profile_context.get("human_review_required")) or float(classification.get("confidence") or 0) < 0.55
    ticket_result = None
    if create_ticket:
        ticket_result = create_park_issue_ticket(
            source="guest",
            issue_type=issue_type,
            summary=text[:1000],
            severity=severity,
            location=location,
            reporter_role="guest_message",
            required_action=staff_checklist[0] if staff_checklist else _default_required_action(issue_type),
            assigned_team=TEAM_BY_ISSUE.get(issue_type) or "ops_lead",
        )
        ticket = ticket_result.get("ticket") if isinstance(ticket_result, dict) and isinstance(ticket_result.get("ticket"), dict) else None
        if ticket and human_ack_required and not ticket.get("requires_human_ack"):
            ticket["requires_human_ack"] = True
            ticket["human_review_required"] = True
            ticket["human_review_place"] = review_place or str(profile_context.get("human_review_place") or "guest_services_information_desk")
    event = {
        "event": "guest_message_triaged",
        "id": _id("guest-triage", {"message": text[:200], "issue_type": issue_type}),
        "message_excerpt": text[:1000],
        "guest_name": str(guest_name or "")[:120] or None,
        "location": str(location or "")[:120] or None,
        "channel": str(channel or "guest_message")[:80],
        "issue_type": issue_type,
        "urgency": classification["urgency"],
        "urgency_score": classification["urgency_score"],
        "matched_terms": classification["matched_terms"],
        "severity": severity,
        "assigned_team": TEAM_BY_ISSUE.get(issue_type) or "ops_lead",
        "human_review_place": review_place,
        "human_ack_required": human_ack_required,
        "sla_minutes": classification["sla_minutes"],
        "guest_reply_draft": reply_draft,
        "staff_checklist": staff_checklist,
        "understanding": {
            "status": "profile_grounded" if profile_context.get("status") == "answered_from_profile" else "needs_human_review" if human_ack_required and issue_type == "unclear_guest_request" else "rule_classified",
            "category": profile_context.get("category") or issue_type,
            "confidence": classification["confidence"],
        },
        "profile_context": profile_context,
        "ticket_id": (ticket_result or {}).get("ticket", {}).get("id") if isinstance(ticket_result, dict) else None,
        "created_at": _now_iso(),
        "live_ops_authority": False,
        "boundary": "Guest message triage can create a routed issue ticket and response draft, but high-risk action requires human acknowledgement.",
    }
    event["memory_persistence"] = _record_guest_triage_memory(event, ticket_result if isinstance(ticket_result, dict) else None)
    _write_event(event)
    memory_impact = _guest_triage_memory_impact(issue_type, event["memory_persistence"])
    response_classification = {
        "issue_type": issue_type,
        "urgency": classification["urgency"],
        "urgency_score": classification["urgency_score"],
        "severity": severity,
        "matched_terms": classification["matched_terms"],
        "confidence": classification["confidence"],
    }
    response_routing = {
        "assigned_team": event["assigned_team"],
        "human_review_place": review_place,
        "human_ack_required": event["human_ack_required"],
        "sla_minutes": event["sla_minutes"],
    }
    llm_response = _generate_guest_triage_llm_response(
        message=text,
        classification=response_classification,
        profile_context=profile_context,
        routing=response_routing,
        staff_checklist=staff_checklist,
        memory_impact=memory_impact,
        fallback_reply=reply_draft,
    )
    return {
        "status": "triaged",
        "mode": "guest_message_triage",
        "classification": response_classification,
        "understanding": event["understanding"],
        "profile_context": profile_context,
        "routing": response_routing,
        "reaction": {
            "guest_reply_draft": reply_draft,
            "staff_checklist": staff_checklist,
            "forbidden_auto_actions": ["dispatch_security_or_medical", "approve_refund", "override_safety_policy", "change_live_operations"],
        },
        "llm_response": llm_response,
        "ticket_result": ticket_result,
        "triage_event": event,
        "memory_persistence": event["memory_persistence"],
        "memory_impact": memory_impact,
        "boundary": event["boundary"],
    }


def _classify_guest_message(message: str) -> dict[str, Any]:
    text = message.lower()
    contextual = _classify_guest_message_context(text)
    if contextual:
        return contextual
    best: dict[str, Any] | None = None
    for rule in GUEST_TRIAGE_RULES:
        matched = [term for term in rule["terms"] if _guest_term_matches(text, term)]
        if not matched:
            continue
        score = int(rule["score"]) + min(8, (len(matched) - 1) * 3)
        candidate = {
            "issue_type": rule["issue_type"],
            "urgency": rule["urgency"],
            "urgency_score": min(100, score),
            "sla_minutes": rule["sla"],
            "matched_terms": matched[:8],
            "confidence": round(_bounded(0.66 + min(len(matched), 4) * 0.08, 0.66, 0.94), 2),
        }
        if best is None or candidate["urgency_score"] > best["urgency_score"]:
            best = candidate
    if best:
        return best
    return {
        "issue_type": "unclear_guest_request",
        "urgency": "low",
        "urgency_score": 24,
        "sla_minutes": 20,
        "matched_terms": [],
        "confidence": 0.34,
    }


def _guest_term_matches(text: str, term: str) -> bool:
    clean = str(term or "").strip().lower()
    if not clean:
        return False
    prefix = r"\b" if clean[0].isalnum() else ""
    suffix = r"\b" if clean[-1].isalnum() else ""
    return bool(re.search(f"{prefix}{re.escape(clean)}{suffix}", text))


GUEST_PROFILE_QUERY_CATEGORIES = {
    "restrooms": {
        "terms": ("restroom", "bathroom", "toilet"),
        "kinds": ("restrooms",),
    },
    "first_aid": {
        "terms": ("first aid", "medical station", "nurse", "health center"),
        "kinds": ("first_aid",),
    },
    "guest_services": {
        "terms": ("guest services", "lost and found", "ticket help", "information desk", "stroller", "locker"),
        "kinds": ("guest_services",),
        "services": ("lost and found", "ticket help", "accessibility help", "separated-party support"),
    },
    "food_dietary": {
        "terms": ("food", "eat", "restaurant", "vegetarian", "vegan", "kids meal", "dietary", "quick pickup"),
        "kinds": ("food",),
        "dietary": ("vegetarian", "vegan", "kids meals", "quick pickup", "lighter options"),
    },
    "water_cooling_quiet": {
        "terms": ("water", "water refill", "shade", "cooling", "quiet", "sensory", "overstimulated", "break"),
        "kinds": ("water_refill", "quiet_or_cooling"),
    },
    "accessibility_map": {
        "terms": ("accessible", "accessibility", "wheelchair", "step-free", "step free", "elevator", "transfer", "accessible entrance"),
        "fields": ("accessibilityNote",),
    },
    "attraction_facts": {
        "terms": ("ride", "coaster", "show", "height requirement", "how tall", "duration", "indoor", "theater"),
        "kinds": ("attraction", "quiet_or_cooling"),
    },
}


def _load_guest_triage_venue_profile() -> dict[str, Any]:
    try:
        from venue_profile import build_venue_profile

        profile = build_venue_profile()
        return profile if isinstance(profile, dict) else {}
    except Exception as error:
        return {"status": "unavailable", "readiness_issues": [str(error)[:240]]}


def _guest_triage_profile_context(message: str, issue_type: str) -> dict[str, Any]:
    profile = _load_guest_triage_venue_profile()
    real_inputs = profile.get("realInputs") if isinstance(profile.get("realInputs"), dict) else {}
    identity = profile.get("venueIdentity") if isinstance(profile.get("venueIdentity"), dict) else {}
    readiness = profile.get("readiness") if isinstance(profile.get("readiness"), dict) else {}
    location_details = real_inputs.get("locationDetails") if isinstance(real_inputs.get("locationDetails"), dict) else {}
    category = _profile_query_category(message)
    location_matches = _profile_location_matches(message, location_details)
    category_matches = _profile_category_location_matches(category, location_details) if issue_type in {"profile_information_request", "accessibility_accommodation"} else []
    matches = _dedupe_profile_matches([*location_matches, *category_matches])[:5]
    can_answer = issue_type in {"profile_information_request", "accessibility_accommodation"} and bool(matches) and bool(category)
    if can_answer:
        status = "answered_from_profile"
    elif issue_type == "unclear_guest_request":
        status = "needs_human_review"
    elif issue_type not in {"profile_information_request", "accessibility_accommodation"} and not location_matches:
        status = "not_applicable"
    else:
        status = "needs_human_review"
    venue_name = str(identity.get("name") or "active park profile").strip()
    context = {
        "status": status,
        "venue_name": venue_name,
        "profile_type": identity.get("profileType"),
        "readiness_status": readiness.get("status"),
        "category": category,
        "matched_locations": matches,
        "human_review_required": status == "needs_human_review",
        "human_review_place": "guest_services_information_desk" if status == "needs_human_review" else None,
        "limitations": _profile_context_limitations(profile),
    }
    if can_answer:
        context["guest_reply_draft"] = _profile_grounded_reply(category, matches, venue_name)
        context["evidence"] = [f"{item.get('name')} ({item.get('kind') or item.get('category') or 'profile place'})" for item in matches[:3]]
    elif status == "needs_human_review":
        context["guest_reply_draft"] = "I am not fully certain from the park profile. I will route this to Guest Services so a team member can confirm the right answer."
        context["evidence"] = []
    return context


def _profile_query_category(text: str) -> str | None:
    lowered = text.lower()
    best_category = None
    best_score = 0
    for category, config in GUEST_PROFILE_QUERY_CATEGORIES.items():
        score = sum(1 for term in config.get("terms", ()) if _guest_term_matches(lowered, str(term)))
        if score > best_score:
            best_score = score
            best_category = category
    return best_category


def _profile_location_matches(text: str, location_details: dict[str, Any]) -> list[dict[str, Any]]:
    lowered = text.lower()
    matches: list[dict[str, Any]] = []
    for key, detail in location_details.items():
        if not isinstance(detail, dict):
            continue
        name = str(detail.get("name") or key or "").strip()
        if name and name.lower() in lowered:
            matches.append(_compact_profile_location(name, detail, "name_match"))
    return matches


def _profile_category_location_matches(category: str | None, location_details: dict[str, Any]) -> list[dict[str, Any]]:
    if not category:
        return []
    config = GUEST_PROFILE_QUERY_CATEGORIES.get(category) or {}
    kinds = {str(item).lower() for item in config.get("kinds", ())}
    services = tuple(str(item).lower() for item in config.get("services", ()))
    dietary = tuple(str(item).lower() for item in config.get("dietary", ()))
    fields = tuple(str(item) for item in config.get("fields", ()))
    matches: list[dict[str, Any]] = []
    for key, detail in location_details.items():
        if not isinstance(detail, dict):
            continue
        kind = str(detail.get("kind") or detail.get("category") or "").lower()
        service_values = " ".join(str(item).lower() for item in _as_list(detail.get("services")))
        dietary_values = " ".join(str(item).lower() for item in _as_list(detail.get("dietaryTags")))
        has_field = any(str(detail.get(field) or "").strip() for field in fields)
        if kind in kinds or any(term in service_values for term in services) or any(term in dietary_values for term in dietary) or has_field:
            matches.append(_compact_profile_location(str(detail.get("name") or key), detail, "category_match"))
    return matches


def _compact_profile_location(name: str, detail: dict[str, Any], match_type: str) -> dict[str, Any]:
    return {
        "name": name,
        "kind": detail.get("kind") or detail.get("category"),
        "zone_id": detail.get("zoneId") or detail.get("zone_id"),
        "match_type": match_type,
        "services": _as_list(detail.get("services"))[:4],
        "dietary_tags": _as_list(detail.get("dietaryTags"))[:4],
        "accessibility_note": str(detail.get("accessibilityNote") or "")[:220] or None,
        "sensory_note": str(detail.get("sensoryNote") or "")[:220] or None,
    }


def _dedupe_profile_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in matches:
        key = str(item.get("name") or "").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _profile_grounded_reply(category: str, matches: list[dict[str, Any]], venue_name: str) -> str:
    names = ", ".join(str(item.get("name")) for item in matches[:3] if item.get("name"))
    lead = {
        "restrooms": "The park profile shows restroom options at",
        "first_aid": "The park profile shows First Aid at",
        "guest_services": "The park profile routes this to",
        "food_dietary": "The park profile shows food options at",
        "water_cooling_quiet": "The park profile shows comfort options at",
        "accessibility_map": "The park profile has accessibility notes for",
        "attraction_facts": "The park profile has attraction information for",
    }.get(category, "The park profile shows")
    suffix = " Please confirm live availability with a nearby team member if conditions look different."
    return f"{lead} {names or venue_name}.{suffix}"


def _profile_context_limitations(profile: dict[str, Any]) -> list[str]:
    limitations = ["Profile facts are not live wait, closure, staffing, or emergency authority."]
    real_inputs = profile.get("realInputs") if isinstance(profile.get("realInputs"), dict) else {}
    agent_context = real_inputs.get("agentContext") if isinstance(real_inputs.get("agentContext"), dict) else {}
    limitations.extend(str(item)[:180] for item in _as_list(agent_context.get("knownGaps"))[:2])
    return limitations


def _classify_guest_message_context(text: str) -> dict[str, Any] | None:
    if _is_lost_child_context(text):
        return {
            "issue_type": "lost_child_report",
            "urgency": "critical",
            "urgency_score": 99,
            "sla_minutes": 1,
            "matched_terms": _matched_context_terms(
                text,
                (
                    "cannot find",
                    "can't find",
                    "missing",
                    "lost",
                    "gone",
                    "separated",
                    "year-old",
                    "year old",
                    "child",
                    "kid",
                    "son",
                    "daughter",
                ),
            ),
            "confidence": 0.92,
        }
    if _is_accessibility_context(text):
        return {
            "issue_type": "accessibility_accommodation",
            "urgency": "high",
            "urgency_score": 84,
            "sla_minutes": 8,
            "matched_terms": _matched_context_terms(
                text,
                (
                    "accessibility",
                    "accessible",
                    "accommodation",
                    "wheelchair",
                    "mobility",
                    "medical history",
                    "cannot stand",
                    "can't stand",
                    "queue",
                ),
            ),
            "confidence": 0.88,
        }
    return None


def _is_lost_child_context(text: str) -> bool:
    separation_terms = ("cannot find", "can't find", "missing", "lost", "gone", "separated")
    child_terms = ("child", "kid", "son", "daughter", "boy", "girl", "toddler")
    has_separation = any(term in text for term in separation_terms)
    has_child_term = any(term in text for term in child_terms)
    has_minor_age = bool(re.search(r"\b(?:\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen)\s*[- ]\s*year\s*[- ]\s*old\b", text))
    return has_separation and (has_child_term or has_minor_age)


def _is_accessibility_context(text: str) -> bool:
    accessibility_terms = ("accessibility", "accessible", "accommodation", "wheelchair", "mobility", "medical history")
    injury_terms = ("injured", "hurt", "bleeding", "fell", "slipped", "accident", "collision", "broken")
    if any(term in text for term in injury_terms):
        return False
    return any(term in text for term in accessibility_terms)


def _matched_context_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if term in text][:8]


def _severity_for_triage(urgency: str) -> str:
    if urgency == "critical":
        return "critical"
    if urgency == "high":
        return "high"
    if urgency == "medium":
        return "medium"
    return "low"


def _guest_reply_draft(issue_type: str) -> str:
    return {
        "lost_child_report": "Stay with me here. I am contacting Security now. Please tell me the child's name, age, clothing, and last place you saw them.",
        "heat_exhaustion_concern": "I am getting First Aid involved now. If it is safe, move with me to shade and stay with your friend while help comes.",
        "injury_or_safety_incident": "I am calling the safety team now. Please stay where you are if it is safe, and tell me what happened and whether anyone is hurt.",
        "weather_evacuation_confusion": "I can help route you calmly. Please follow the nearest staff direction to shelter, and tell me if anyone in your group needs accessibility support.",
        "safety_rule_refusal": "For safety, the ride cannot proceed unless the rule is followed. I can bring a ride lead to help explain the requirement.",
        "line_cutting_conflict": "I hear this is frustrating. Please stay separated from the other party while I get a lead to help resolve the queue issue.",
        "accessibility_accommodation": "You do not need to share private medical details here. I will connect you with accessibility support and find a safe waiting option.",
        "refund_request": "I understand why you want this reviewed. I can collect the details and route you to Guest Services, but I cannot promise a refund from here.",
        "ride_closure_complaint": "I am sorry you waited through that closure. I can check current alternatives and route refund or compensation questions to Guest Services.",
        "language_barrier": "I can help one step at a time. I will find translation support and help confirm where your family is.",
        "angry_parent": "I hear how frustrating this has been for your family. I can help confirm what happened and get you a clear next step.",
        "profile_information_request": "I can answer from the active park profile and flag anything that needs a live team confirmation.",
        "unclear_guest_request": "I am not fully certain what you need yet. I will route this to Guest Services so a team member can clarify and help.",
    }.get(issue_type, "I can help. I will collect the details and route this to the right park team.")


def _guest_triage_staff_checklist(issue_type: str) -> list[str]:
    return {
        "lost_child_report": ["Radio Security/Ops immediately.", "Keep guardian at a fixed meeting point.", "Collect child name, age, clothing, and last seen location.", "Do not send guardian searching alone."],
        "heat_exhaustion_concern": ["Contact First Aid immediately.", "Move guest to shade/cooling only if safe.", "Avoid medical diagnosis.", "Stay with party until care team arrives."],
        "injury_or_safety_incident": ["Notify safety/medical lead.", "Preserve scene if needed.", "Ask what happened and whether anyone is hurt.", "Do not assign fault or diagnose."],
        "weather_evacuation_confusion": ["Use calm shelter routing.", "Protect accessibility routes.", "Avoid panic language.", "Escalate blocked or confused flow to Ops Command."],
        "safety_rule_refusal": ["Stop ride progression until compliant.", "State the rule clearly.", "Explain safety reason without bargaining.", "Escalate persistent refusal to ride lead/security."],
        "line_cutting_conflict": ["Separate parties if safe.", "Acknowledge frustration.", "Call lead/security if escalating.", "Document queue location and witnesses."],
        "accessibility_accommodation": ["Protect privacy.", "Do not ask for diagnosis.", "Offer accessibility support or safe waiting option.", "Route to accessibility lead."],
        "refund_request": ["Empathize.", "Do not promise refund.", "Collect ticket/receipt and issue summary.", "Route to Guest Services policy owner."],
        "ride_closure_complaint": ["Acknowledge wait impact.", "Do not promise reopen time.", "Offer current alternatives.", "Route compensation requests to Guest Services."],
        "language_barrier": ["Use simple language.", "Find translation support.", "Confirm whether party is separated.", "Give one clear next step."],
        "angry_parent": ["Acknowledge impact.", "Confirm what happened.", "Offer concrete next step.", "Escalate compensation or supervisor request."],
        "profile_information_request": ["Answer only from active park profile evidence.", "Name the matched place or category.", "Do not claim live availability, wait, closure, staffing, or emergency authority.", "Escalate if profile evidence is missing or stale."],
        "unclear_guest_request": ["Do not invent a park fact or policy.", "Ask one clarifying question if safe.", "Route to Guest Services information desk.", "Capture the exact guest wording for review."],
    }.get(issue_type, ["Collect details.", "Route to responsible owner.", "Avoid promises outside policy."])


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
    represented_guests = _represented_guests(state)
    low_attendance = 0 <= represented_guests < LOW_ATTENDANCE_CROWD_TICKET_FLOOR
    configured = _as_dict(state.get("placeRiskGraph"))
    if isinstance(configured.get("places"), list):
        places = [
            _attendance_gate_place_node(_normalize_place_node(place), represented_guests, low_attendance)
            for place in configured.get("places", [])
            if isinstance(place, dict)
        ]
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
        raw_current_guests = int(_number(path.get("currentGuests"), 0))
        current_guests = min(raw_current_guests, represented_guests) if represented_guests >= 0 else raw_current_guests
        enough_people = current_guests >= MIN_PATH_GUESTS_FOR_CROWD_TICKET and not low_attendance
        place_id = f"path:{from_id}:{to_id}"
        factors = []
        if congestion >= 86 and enough_people:
            factors.append("crowd_bottleneck")
        if congestion >= 86 and width <= 4.8 and enough_people:
            factors.append("narrow_path")
        if congestion >= 78 and current_guests >= 500 and not low_attendance:
            factors.append("queue_merge_conflict")
        if storm_risk >= 65 and congestion >= 78 and enough_people:
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
            "evidence": [
                f"pathCongestion={congestion}",
                f"widthM={width}",
                f"currentGuests={current_guests}",
                f"representedGuests={represented_guests}",
                f"stormRisk={storm_risk}",
            ],
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
    represented_guests = _represented_guests(state)
    low_attendance = 0 <= represented_guests < LOW_ATTENDANCE_CROWD_TICKET_FLOOR
    base_seed = str(seed or _state_seed(state))
    candidates: list[dict[str, Any]] = []
    for place in _as_list(graph.get("places")):
        if not isinstance(place, dict):
            continue
        factors = {str(item) for item in _as_list(place.get("risk_factors"))}
        load = int(_number(place.get("current_load"), 0))
        if low_attendance and factors & {"crowd_bottleneck", "narrow_path", "queue_merge_conflict", "confusing_route", "signage_gap"}:
            continue
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


def _attendance_gate_place_node(place: dict[str, Any], represented_guests: int, low_attendance: bool) -> dict[str, Any]:
    crowd_factors = {"crowd_bottleneck", "narrow_path", "queue_merge_conflict", "confusing_route", "signage_gap"}
    current_guests = int(_number(place.get("current_guests"), 0))
    if low_attendance or (represented_guests >= 0 and current_guests and current_guests < MIN_PATH_GUESTS_FOR_CROWD_TICKET):
        factors = [factor for factor in _as_list(place.get("risk_factors")) if str(factor) not in crowd_factors]
        gated = {**place, "risk_factors": factors, "known_failure_modes": _failure_modes_for_place_factors(factors)}
        evidence = [str(item) for item in _as_list(gated.get("evidence"))]
        gated["evidence"] = [*evidence, f"representedGuests={represented_guests}", "crowdRiskSuppressedByAttendance=true"]
        return gated
    evidence = [str(item) for item in _as_list(place.get("evidence"))]
    return {**place, "evidence": [*evidence, f"representedGuests={represented_guests}"]}


def _represented_guests(state: dict[str, Any] | None) -> int:
    state = _as_dict(state)
    flow = _as_dict(state.get("guestFlow"))
    explicit = flow.get("representedGuests")
    if explicit is not None:
        return int(_number(explicit, -1))
    zones = [zone for zone in _as_list(flow.get("zones")) if isinstance(zone, dict)]
    if zones:
        return sum(max(0, int(_number(zone.get("currentGuests"), 0))) for zone in zones)
    groups = _as_list(_as_dict(state.get("physicalMap")).get("guestGroups"))
    if groups:
        return sum(max(0, int(_number(group.get("count") or group.get("guestCount"), 0))) for group in groups if isinstance(group, dict))
    return -1


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
        "profile_information_request": "Answer only from the active park profile and remind guest to confirm live conditions.",
        "unclear_guest_request": "Route to Guest Services for human clarification; do not invent park facts.",
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
