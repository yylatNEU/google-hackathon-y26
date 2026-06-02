from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any


REQUIRED_FEEDS = [
    {
        "source": "weather",
        "label": "Weather and safety",
        "signal_types": ["storm_risk", "heat_index", "lightning_window"],
        "max_stale_seconds": 1800,
        "owner": "Safety operations",
    },
    {
        "source": "ride_ops",
        "label": "Ride operations",
        "signal_types": ["ride_status", "wait_time", "capacity", "downtime"],
        "max_stale_seconds": 90,
        "owner": "Ride operations",
    },
    {
        "source": "guest_flow",
        "label": "Guest flow",
        "signal_types": ["zone_density", "path_congestion", "routing_take_rate"],
        "max_stale_seconds": 60,
        "owner": "Crowd control",
    },
    {
        "source": "staffing",
        "label": "Staffing",
        "signal_types": ["coverage", "training_tag", "break_window", "fatigue"],
        "max_stale_seconds": 180,
        "owner": "Labor operations",
    },
    {
        "source": "food_ops",
        "label": "Food operations",
        "signal_types": ["inventory", "mobile_backlog", "prep_eta", "kitchen_load"],
        "max_stale_seconds": 120,
        "owner": "Food operations",
    },
    {
        "source": "operator_signal",
        "label": "Operator and guest reports",
        "signal_types": ["staff_note", "guest_care", "incident_report"],
        "max_stale_seconds": 120,
        "owner": "Park command",
    },
]

SOURCE_ALIASES = {
    "weather_feed": "weather",
    "ride": "ride_ops",
    "rides": "ride_ops",
    "ride_status": "ride_ops",
    "crowd": "guest_flow",
    "guest": "guest_flow",
    "guestflow": "guest_flow",
    "staff": "staffing",
    "labor": "staffing",
    "food": "food_ops",
    "food_inventory": "food_ops",
    "staff_note": "operator_signal",
    "manual": "operator_signal",
    "operator": "operator_signal",
}

REVIEW_TRIGGERS = {
    "safety",
    "medical",
    "security",
    "child_care",
    "panic_evacuation",
    "equipment_safety",
    "privacy",
    "accessibility",
}

_mongo_client_lock = threading.Lock()
_mongo_client: Any | None = None
_mongo_db: Any | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC)
        except (OSError, ValueError):
            return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _jsonl_path(name: str, default_filename: str) -> str:
    return os.getenv(name, f"/tmp/parkpulse/{default_filename}")


def _feed_log_path() -> str:
    return _jsonl_path("PARKPULSE_LIVE_FEED_EVENT_LOG_PATH", "live_feed_events.jsonl")


def _review_log_path() -> str:
    return _jsonl_path("PARKPULSE_REVIEW_LEDGER_LOG_PATH", "review_ledger.jsonl")


def _live_feed_storage_mode() -> str:
    return str(os.getenv("PARKPULSE_LIVE_FEED_STORAGE", "auto")).strip().lower()


def _strip_secret(value: str | None) -> str:
    raw = (value or "").strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        return raw[1:-1].strip()
    return raw


def _int_env(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except ValueError:
        return default


def _path_env_is_default(name: str) -> bool:
    return not os.getenv(name, "").strip()


def _collection_for_path(path: str) -> str | None:
    if path == _feed_log_path():
        return "live_feed_events"
    if path == _review_log_path():
        return "live_review_ledger"
    return None


def _mongo_live_feed_storage_enabled(path: str) -> bool:
    mode = _live_feed_storage_mode()
    if mode in {"jsonl", "file", "local"}:
        return False
    if mode in {"mongodb", "mongo"}:
        return _collection_for_path(path) is not None
    if mode != "auto":
        return False
    if not _mongo_uri():
        return False
    if path == _feed_log_path() and not _path_env_is_default("PARKPULSE_LIVE_FEED_EVENT_LOG_PATH"):
        return False
    if path == _review_log_path() and not _path_env_is_default("PARKPULSE_REVIEW_LEDGER_LOG_PATH"):
        return False
    return _collection_for_path(path) is not None


def _mongo_uri() -> str:
    return _strip_secret(os.getenv("MONGODB_DIRECT_URI") or os.getenv("MONGODB_URI") or os.getenv("MONGO_URI"))


def _live_feed_mongo_db():
    global _mongo_client, _mongo_db
    if _mongo_db is not None:
        return _mongo_db
    uri = _mongo_uri()
    if not uri:
        return None
    with _mongo_client_lock:
        if _mongo_db is not None:
            return _mongo_db
        try:
            from pymongo import MongoClient
            import certifi

            timeout_ms = max(250, _int_env("MONGODB_OPERATION_TIMEOUT_MS", 1500))
            _mongo_client = MongoClient(
                uri,
                serverSelectionTimeoutMS=timeout_ms,
                connectTimeoutMS=timeout_ms,
                socketTimeoutMS=timeout_ms,
                tlsCAFile=os.getenv("MONGODB_TLS_CA_FILE") or certifi.where(),
            )
            _mongo_client.admin.command("ping")
            _mongo_db = _mongo_client[os.getenv("MONGODB_DATABASE", "parkpulse_ops")]
        except Exception:
            _mongo_client = None
            _mongo_db = None
            return None
    return _mongo_db


def _mongo_document(row: dict[str, Any]) -> dict[str, Any]:
    document = json.loads(json.dumps(row, default=str))
    document_id = str(document.get("_id") or document.get("id") or _hash_id("live", document))
    document["_id"] = document_id
    document.setdefault("id", document_id)
    document.setdefault("createdAt", document.get("created_at") or document.get("received_at") or document.get("observed_at") or _now_iso())
    document["updatedAt"] = _now_iso()
    return document


def _write_mongo_document(collection: str, row: dict[str, Any]) -> bool:
    try:
        db = _live_feed_mongo_db()
        if db is None:
            return False
        document = _mongo_document(row)
        db[collection].update_one({"_id": document["_id"]}, {"$set": document}, upsert=True)
        return True
    except Exception:
        return False


def _read_mongo_documents(collection: str, limit: int = 500) -> list[dict[str, Any]]:
    try:
        db = _live_feed_mongo_db()
        if db is None:
            return []
        bounded_limit = max(1, min(5000, int(limit or 500)))
        rows = list(db[collection].find({}, {"embedding": 0, "embeddingText": 0}).sort("createdAt", -1).limit(bounded_limit))
        for row in rows:
            if "_id" in row:
                row["_id"] = str(row["_id"])
        return rows
    except Exception:
        return []


def _append_jsonl(path: str, row: dict[str, Any]) -> None:
    collection = _collection_for_path(path)
    if collection and _mongo_live_feed_storage_enabled(path) and _write_mongo_document(collection, row):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def _read_jsonl(path: str, limit: int = 500) -> list[dict[str, Any]]:
    collection = _collection_for_path(path)
    if collection and _mongo_live_feed_storage_enabled(path):
        rows = _read_mongo_documents(collection, limit)
        if rows:
            return rows
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()[-max(1, min(5000, int(limit or 500))) :]
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in reversed(lines):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def live_feed_storage_status() -> dict[str, Any]:
    feed_collection = _collection_for_path(_feed_log_path())
    review_collection = _collection_for_path(_review_log_path())
    feed_mongo = bool(feed_collection and _mongo_live_feed_storage_enabled(_feed_log_path()))
    review_mongo = bool(review_collection and _mongo_live_feed_storage_enabled(_review_log_path()))
    return {
        "mode": "mongodb" if feed_mongo and review_mongo else "jsonl" if not feed_mongo and not review_mongo else "hybrid",
        "configured_mode": _live_feed_storage_mode(),
        "event_collection": feed_collection if feed_mongo else None,
        "review_collection": review_collection if review_mongo else None,
        "event_log_path": None if feed_mongo else _feed_log_path(),
        "review_log_path": None if review_mongo else _review_log_path(),
        "shared_across_instances": feed_mongo and review_mongo,
    }


def _source(value: Any) -> str:
    normalized = str(value or "operator_signal").strip().lower().replace("-", "_").replace(" ", "_")
    return SOURCE_ALIASES.get(normalized, normalized)


def _hash_id(prefix: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return f"{prefix}_{hashlib.sha1(raw).hexdigest()[:14]}"


def normalize_live_feed_event(payload: dict[str, Any]) -> dict[str, Any]:
    received_at = _parse_time(payload.get("received_at") or payload.get("receivedAt")) or _now()
    observed_at = _parse_time(payload.get("observed_at") or payload.get("observedAt") or payload.get("timestamp")) or received_at
    source = _source(payload.get("source") or payload.get("feed") or payload.get("system"))
    signal_type = str(payload.get("signal_type") or payload.get("signalType") or payload.get("type") or "state_update").strip().lower().replace(" ", "_")
    entity_type = str(payload.get("entity_type") or payload.get("entityType") or payload.get("target_type") or payload.get("targetType") or "park").strip().lower()
    entity_id = str(payload.get("entity_id") or payload.get("entityId") or payload.get("target_id") or payload.get("targetId") or "park").strip()
    raw_ref = payload.get("raw_payload_ref") or payload.get("rawPayloadRef") or payload.get("source_url") or payload.get("sourceUrl")
    confidence = payload.get("confidence", 1.0)
    try:
        confidence_float = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence_float = 0.5
    freshness_seconds = payload.get("freshness_seconds") or payload.get("freshnessSeconds")
    if freshness_seconds is None:
        freshness_seconds = max(0, int((received_at - observed_at).total_seconds()))
    try:
        freshness_int = max(0, int(float(freshness_seconds)))
    except (TypeError, ValueError):
        freshness_int = 999999
    event_core = {
        "source": source,
        "source_event_id": str(payload.get("source_event_id") or payload.get("sourceEventId") or ""),
        "observed_at": observed_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "entity_type": entity_type,
        "entity_id": entity_id,
        "signal_type": signal_type,
        "value": payload.get("value"),
    }
    if not event_core["source_event_id"]:
        event_core["source_event_id"] = _hash_id("src", event_core)
    event_id = str(payload.get("id") or payload.get("event_id") or payload.get("eventId") or _hash_id("feed", event_core))
    warnings: list[str] = []
    if source not in {feed["source"] for feed in REQUIRED_FEEDS}:
        warnings.append(f"Unknown feed source '{source}'.")
    if confidence_float < 0.7:
        warnings.append("Low-confidence feed event requires corroboration.")
    if raw_ref is None and payload.get("raw") is None:
        warnings.append("No raw payload reference supplied.")
    return {
        "id": event_id,
        **event_core,
        "received_at": received_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "freshness_seconds": freshness_int,
        "confidence": round(confidence_float, 3),
        "raw_payload_ref": raw_ref,
        "raw": payload.get("raw", {}),
        "normalized_by": "parkpulse_live_feedback_loop_v1",
        "status": "accepted" if not warnings else "accepted_with_warnings",
        "warnings": warnings,
    }


def _state_derived_events(park_state: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(park_state, dict):
        return []
    now = _now_iso()
    flow = park_state.get("guestFlow", {}) if isinstance(park_state.get("guestFlow"), dict) else {}
    weather = park_state.get("weather", {}) if isinstance(park_state.get("weather"), dict) else {}
    staffing = park_state.get("staffing", {}) if isinstance(park_state.get("staffing"), dict) else {}
    food = park_state.get("foodInventory", {}) if isinstance(park_state.get("foodInventory"), dict) else {}
    rides = flow.get("rides", []) if isinstance(flow.get("rides"), list) else []
    zones = flow.get("zones", []) if isinstance(flow.get("zones"), list) else []
    food_locations = food.get("locations", []) if isinstance(food.get("locations"), list) else []
    top_ride = max([ride for ride in rides if isinstance(ride, dict)], key=lambda row: int(row.get("waitMins", 0) or 0), default={})
    top_zone = max([zone for zone in zones if isinstance(zone, dict)], key=lambda row: int(row.get("density", 0) or 0), default={})
    top_food = max([row for row in food_locations if isinstance(row, dict)], key=lambda row: int(row.get("mobileOrderBacklog", 0) or 0), default={})
    candidates = [
        {
            "source": "weather",
            "source_event_id": "state-derived-weather",
            "observed_at": now,
            "entity_type": "park",
            "entity_id": "park",
            "signal_type": "weather_state",
            "value": {"heat_index_f": weather.get("heatIndexF"), "storm_risk": weather.get("stormRisk")},
            "confidence": 0.86 if weather else 0.35,
            "raw_payload_ref": "park_state.weather",
        },
        {
            "source": "ride_ops",
            "source_event_id": "state-derived-ride-ops",
            "observed_at": now,
            "entity_type": "ride",
            "entity_id": top_ride.get("id") or "unknown",
            "signal_type": "wait_time",
            "value": {"ride": top_ride.get("name"), "wait_mins": top_ride.get("waitMins"), "queue_guests": top_ride.get("queueGuests")},
            "confidence": 0.82 if top_ride else 0.35,
            "raw_payload_ref": "park_state.guestFlow.rides",
        },
        {
            "source": "guest_flow",
            "source_event_id": "state-derived-guest-flow",
            "observed_at": now,
            "entity_type": "zone",
            "entity_id": top_zone.get("id") or "unknown",
            "signal_type": "zone_density",
            "value": {"zone": top_zone.get("name"), "density": top_zone.get("density"), "current_guests": top_zone.get("currentGuests")},
            "confidence": 0.82 if top_zone else 0.35,
            "raw_payload_ref": "park_state.guestFlow.zones",
        },
        {
            "source": "staffing",
            "source_event_id": "state-derived-staffing",
            "observed_at": now,
            "entity_type": "staffing",
            "entity_id": "park_staff",
            "signal_type": "coverage",
            "value": {"scheduled": staffing.get("scheduled"), "checked_in": staffing.get("checkedIn"), "open_callouts": staffing.get("openCallouts")},
            "confidence": 0.78 if staffing else 0.35,
            "raw_payload_ref": "park_state.staffing",
        },
        {
            "source": "food_ops",
            "source_event_id": "state-derived-food-ops",
            "observed_at": now,
            "entity_type": "food_location",
            "entity_id": top_food.get("id") or "unknown",
            "signal_type": "mobile_backlog",
            "value": {"location": top_food.get("name"), "mobile_order_backlog": top_food.get("mobileOrderBacklog"), "pickup_eta_minutes": top_food.get("pickupEtaMinutes")},
            "confidence": 0.78 if top_food else 0.35,
            "raw_payload_ref": "park_state.foodInventory.locations",
        },
    ]
    return [normalize_live_feed_event({**candidate, "received_at": now, "raw": {"derived_from": "park_state"}}) for candidate in candidates]


def ingest_live_feed_event(payload: dict[str, Any]) -> dict[str, Any]:
    event = normalize_live_feed_event(payload)
    _append_jsonl(_feed_log_path(), event)
    review_case = review_case_for_event(event)
    if review_case:
        _append_jsonl(_review_log_path(), review_case)
    return {
        "status": event["status"],
        "mode": "normalized_live_feed_ingest",
        "event": event,
        "review_case": review_case,
        "schema": live_feed_schema(),
        "boundary": "Feed ingestion records facts only. Recommendations still require policy gates, review gates, and outcome attribution.",
    }


def review_case_for_event(event: dict[str, Any]) -> dict[str, Any] | None:
    source_config = next((feed for feed in REQUIRED_FEEDS if feed["source"] == event.get("source")), {})
    max_stale = int(source_config.get("max_stale_seconds") or 120)
    signal_type = str(event.get("signal_type") or "")
    value_blob = _review_trigger_blob(event)
    trigger_set = {trigger for trigger in REVIEW_TRIGGERS if trigger in signal_type or trigger in value_blob}
    triggers = sorted(trigger_set)
    stale = int(event.get("freshness_seconds") or 0) > max_stale
    low_confidence = float(event.get("confidence") or 0) < 0.7
    unknown_source = not source_config
    if not (triggers or stale or low_confidence or unknown_source):
        return None
    reason_parts = []
    if triggers:
        reason_parts.append(f"sensitive trigger: {', '.join(triggers)}")
    if stale:
        reason_parts.append("stale feed event")
    if low_confidence:
        reason_parts.append("low confidence")
    if unknown_source:
        reason_parts.append("unknown source")
    return {
        "id": _hash_id("review", {"event_id": event.get("id"), "reason": reason_parts}),
        "created_at": _now_iso(),
        "source_event_id": event.get("id"),
        "review_type": "feed_event_review",
        "status": "open",
        "priority": "critical" if trigger_set.intersection({"medical", "security", "child_care", "panic_evacuation"}) else "watch",
        "owner": source_config.get("owner") or "Park command",
        "reason": "; ".join(reason_parts),
        "decision_options": ["approve_for_state", "request_corroboration", "hold_for_review", "escalate"],
        "training_effect": "Reviewer disposition becomes a label candidate only after outcome attribution; it does not set reward.",
        "event": event,
    }


def _review_trigger_blob(event: dict[str, Any]) -> str:
    value = event.get("value")
    if not isinstance(value, dict):
        return json.dumps(value, default=str).lower()
    fields: list[Any] = []
    if value.get("sensitive_report") is True:
        fields.extend([value.get("note"), value.get("summary"), value.get("description")])
        fields.extend(value.get("top_drivers", []) if isinstance(value.get("top_drivers"), list) else [])
    else:
        fields.extend(
            value.get(key)
            for key in ["note", "summary", "description", "incident_type", "incidentType", "category"]
            if value.get(key)
        )
    return json.dumps(fields, default=str).lower()


def record_review_decision(payload: dict[str, Any]) -> dict[str, Any]:
    case_id = str(payload.get("case_id") or payload.get("caseId") or payload.get("id") or "")
    decision = str(payload.get("decision") or payload.get("status") or "held_for_review").strip().lower()
    reviewer = str(payload.get("reviewer") or payload.get("actor") or "operator").strip()
    row = {
        "id": _hash_id("review_decision", {"case_id": case_id, "decision": decision, "at": _now_iso()}),
        "created_at": _now_iso(),
        "case_id": case_id,
        "review_type": "operator_disposition",
        "status": "closed"
        if decision in {"approved", "rejected", "escalated", "escalate", "approve_for_state", "request_corroboration", "hold_for_review"}
        else "open",
        "decision": decision,
        "reviewer": reviewer,
        "reason": str(payload.get("reason") or payload.get("note") or ""),
        "training_label": str(payload.get("training_label") or payload.get("trainingLabel") or decision),
        "labels_or_reward_changed": False,
        "llm_used_for_reward_or_label": False,
        "boundary": "Human review disposition is captured as evidence. Measured outcomes set reward after the attribution window.",
    }
    _append_jsonl(_review_log_path(), row)
    return {"status": "recorded", "mode": "operator_review_ledger", "review": row, "ledger": review_training_ledger()}


def live_feed_schema() -> dict[str, Any]:
    return {
        "version": "parkpulse.live_feed_event.v1",
        "required_fields": [
            "source",
            "source_event_id",
            "observed_at",
            "received_at",
            "entity_type",
            "entity_id",
            "signal_type",
            "value",
            "confidence",
            "freshness_seconds",
            "raw_payload_ref",
        ],
        "required_feeds": REQUIRED_FEEDS,
    }


def live_feed_health(park_state: dict[str, Any] | None = None, limit: int = 500) -> dict[str, Any]:
    persisted = _read_jsonl(_feed_log_path(), limit=limit)
    records = [*persisted, *_state_derived_events(park_state)]
    latest_by_source: dict[str, dict[str, Any]] = {}
    for event in records:
        source = str(event.get("source") or "")
        if source and source not in latest_by_source:
            latest_by_source[source] = event
    rows = []
    now = _now()
    ready_count = 0
    for feed in REQUIRED_FEEDS:
        event = latest_by_source.get(feed["source"])
        observed_at = _parse_time((event or {}).get("observed_at"))
        age = int((now - observed_at).total_seconds()) if observed_at else None
        stale = age is None or age > int(feed["max_stale_seconds"])
        confidence = float((event or {}).get("confidence") or 0)
        status = "ready" if event and not stale and confidence >= 0.7 else "stale" if event and stale else "weak" if event else "missing"
        if status == "ready":
            ready_count += 1
        rows.append(
            {
                **feed,
                "status": status,
                "latest_event_id": (event or {}).get("id"),
                "latest_signal_type": (event or {}).get("signal_type"),
                "latest_observed_at": (event or {}).get("observed_at"),
                "age_seconds": age,
                "confidence": round(confidence, 2),
                "freshness_seconds": (event or {}).get("freshness_seconds"),
                "value": (event or {}).get("value"),
                "readiness_issues": [] if status == "ready" else _feed_issues(feed, event, stale, confidence),
            }
        )
    review_rows = _read_jsonl(_review_log_path(), limit=limit)
    review_state = _fold_review_state(review_rows)
    open_reviews = review_state["open_reviews"]
    status = "ready" if ready_count == len(REQUIRED_FEEDS) and not open_reviews else "review" if ready_count >= 4 else "not_ready"
    return {
        "status": status,
        "mode": "live_feed_health_and_review_contract",
        "created_at": _now_iso(),
        "schema": live_feed_schema(),
        "summary": {
            "required_feed_count": len(REQUIRED_FEEDS),
            "ready_feed_count": ready_count,
            "missing_or_weak_feed_count": len(REQUIRED_FEEDS) - ready_count,
            "open_review_count": len(open_reviews),
            "persisted_event_count": len(persisted),
        },
        "storage": live_feed_storage_status(),
        "feeds": rows,
        "open_reviews": open_reviews[:8],
        "growth_loop": [
            "Normalize live events into one feed envelope.",
            "Reconcile accepted events into park_state.",
            "Route sensitive, stale, or low-confidence events to human review.",
            "Attach review disposition to the decision receipt.",
            "Admit training rows only after measured outcome attribution.",
        ],
        "boundary": "This panel proves feed coverage and review readiness; it does not bypass policy gates or dispatch authority.",
        "uses_seed_data": False,
        "llm_control_authority": False,
    }


def _feed_issues(feed: dict[str, Any], event: dict[str, Any] | None, stale: bool, confidence: float) -> list[str]:
    issues = []
    if not event:
        issues.append(f"No {feed['label']} event has been received.")
    if event and stale:
        issues.append(f"Latest event exceeded {feed['max_stale_seconds']}s freshness budget.")
    if event and confidence < 0.7:
        issues.append("Latest event confidence is below 0.70.")
    return issues


def _latest_event(rows: list[dict[str, Any]], *, source: str, signal_type: str) -> dict[str, Any] | None:
    matches = [row for row in rows if row.get("source") == source and row.get("signal_type") == signal_type]
    if not matches:
        return None
    return max(matches, key=lambda row: _parse_time(row.get("observed_at")) or datetime.min.replace(tzinfo=UTC))


def _required_feed(source: str) -> dict[str, Any]:
    return next((feed for feed in REQUIRED_FEEDS if feed["source"] == source), {})


def _review_disposition_for_event(event_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    cases = [row for row in rows if row.get("review_type") == "feed_event_review" and row.get("source_event_id") == event_id]
    if not cases:
        return {"status": "not_required", "trusted": True}
    folded = _fold_review_state(rows)
    closed_by_id = {row.get("id"): row for row in folded["closed_reviews"]}
    open_by_id = {row.get("id"): row for row in folded["open_reviews"]}
    for case in cases:
        case_id = case.get("id")
        if case_id in open_by_id:
            return {"status": "open_review", "trusted": False, "case": open_by_id[case_id]}
        closed = closed_by_id.get(case_id)
        decision = str((closed or {}).get("disposition", {}).get("decision") or "").lower()
        if decision == "approve_for_state":
            return {"status": "approved", "trusted": True, "case": closed}
        if decision:
            return {"status": decision, "trusted": False, "case": closed}
    return {"status": "open_review", "trusted": False, "case": cases[0]}


def live_weather_state_evidence(limit: int = 500) -> dict[str, Any]:
    feed_rows = _read_jsonl(_feed_log_path(), limit=limit)
    review_rows = _read_jsonl(_review_log_path(), limit=limit)
    weather_event = _latest_event(feed_rows, source="weather", signal_type="weather_state")
    if not weather_event:
        return {
            "status": "fallback",
            "mode": "live_weather_state_evidence",
            "source": "simulated_state",
            "trusted": False,
            "reason": "No live weather_state feed event has been loaded.",
            "state_patch": {},
        }

    observed_at = _parse_time(weather_event.get("observed_at"))
    age_seconds = int((_now() - observed_at).total_seconds()) if observed_at else None
    stale = age_seconds is None or age_seconds > int(REQUIRED_FEEDS[0]["max_stale_seconds"])
    disposition = _review_disposition_for_event(str(weather_event.get("id") or ""), review_rows)
    trusted = bool(disposition.get("trusted")) and not stale
    value = weather_event.get("value", {}) if isinstance(weather_event.get("value"), dict) else {}
    state_patch = _weather_state_patch(value, weather_event) if trusted else {}
    status = "trusted" if trusted else "stale" if stale else "review_blocked"
    reason = "Live weather is trusted for state reconciliation."
    if stale:
        reason = f"Latest weather event exceeded {REQUIRED_FEEDS[0]['max_stale_seconds']}s freshness budget."
    elif not disposition.get("trusted"):
        reason = f"Weather event review disposition is {disposition.get('status')}."
    return {
        "status": status,
        "mode": "live_weather_state_evidence",
        "source": "live_feed",
        "trusted": trusted,
        "reason": reason,
        "event_id": weather_event.get("id"),
        "source_event_id": weather_event.get("source_event_id"),
        "observed_at": weather_event.get("observed_at"),
        "age_seconds": age_seconds,
        "confidence": weather_event.get("confidence"),
        "review": disposition,
        "weather": value,
        "state_patch": state_patch,
    }


def _weather_state_patch(value: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    storm_risk = _safe_int(value.get("storm_risk_pct"), 0)
    heat_index = _safe_float(value.get("heat_index_f"), 0)
    wind_gust = _safe_float(value.get("wind_gust_mph"), 0)
    weather_label = str(value.get("weather_label") or "live_weather")
    lightning = bool(value.get("lightning_window"))
    outdoor_review = bool(value.get("outdoor_ride_review_required"))
    shelter_mode = lightning or storm_risk >= 70 or heat_index >= 95
    return {
        "weather": {
            "condition": weather_label,
            "temperatureF": _safe_float(value.get("temperature_f"), 0),
            "heatIndexF": heat_index,
            "humidity": _safe_int(value.get("humidity_pct"), 0),
            "windMph": _safe_float(value.get("wind_speed_mph") or value.get("wind_gust_mph"), 0),
            "stormRisk": storm_risk,
            "source": "live_feed",
            "sourceEventId": event.get("id"),
            "provider": value.get("provider"),
            "observedAt": event.get("observed_at"),
        },
        "incidentReadiness": {
            "shelterMode": shelter_mode,
            "operatorEscalation": "weather_review_required" if outdoor_review else "normal",
        },
        "parkOps": {
            "outdoorCapacityCutPct": 35 if lightning else 20 if storm_risk >= 70 or wind_gust >= 35 else 10 if heat_index >= 95 else 0,
        },
        "policy": {
            "weatherRequiresOutdoorReview": outdoor_review,
            "lightningWindow": lightning,
            "heatRisk": value.get("heat_risk"),
            "stormRiskPct": storm_risk,
        },
    }


def live_ride_ops_state_evidence(limit: int = 500) -> dict[str, Any]:
    feed_rows = _read_jsonl(_feed_log_path(), limit=limit)
    review_rows = _read_jsonl(_review_log_path(), limit=limit)
    ride_event = _latest_event(feed_rows, source="ride_ops", signal_type="ride_status")
    if not ride_event:
        return {
            "status": "fallback",
            "mode": "live_ride_ops_state_evidence",
            "source": "simulated_state",
            "trusted": False,
            "reason": "No live ride_status feed event has been loaded.",
            "state_patch": {},
        }

    feed_config = _required_feed("ride_ops")
    observed_at = _parse_time(ride_event.get("observed_at"))
    age_seconds = int((_now() - observed_at).total_seconds()) if observed_at else None
    stale = age_seconds is None or age_seconds > int(feed_config.get("max_stale_seconds") or 90)
    disposition = _review_disposition_for_event(str(ride_event.get("id") or ""), review_rows)
    trusted = bool(disposition.get("trusted")) and not stale
    value = ride_event.get("value", {}) if isinstance(ride_event.get("value"), dict) else {}
    state_patch = _ride_ops_state_patch(value, ride_event) if trusted else {}
    status = "trusted" if trusted else "stale" if stale else "review_blocked"
    reason = "Live ride operations are trusted for state reconciliation."
    if stale:
        reason = f"Latest ride operations event exceeded {feed_config.get('max_stale_seconds', 90)}s freshness budget."
    elif not disposition.get("trusted"):
        reason = f"Ride operations event review disposition is {disposition.get('status')}."
    return {
        "status": status,
        "mode": "live_ride_ops_state_evidence",
        "source": "live_feed",
        "trusted": trusted,
        "reason": reason,
        "event_id": ride_event.get("id"),
        "source_event_id": ride_event.get("source_event_id"),
        "observed_at": ride_event.get("observed_at"),
        "age_seconds": age_seconds,
        "confidence": ride_event.get("confidence"),
        "review": disposition,
        "ride_ops": value,
        "state_patch": state_patch,
    }


def _ride_ops_state_patch(value: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    rides = value.get("rides", []) if isinstance(value.get("rides"), list) else []
    normalized_rides = [_ride_state_row(ride, event) for ride in rides if isinstance(ride, dict)]
    top_wait = max(normalized_rides, key=lambda ride: _safe_int(ride.get("waitMins"), 0), default={})
    top_downtime = max(normalized_rides, key=lambda ride: _safe_int(ride.get("downtimeRisk"), 0), default={})
    down_count = sum(1 for ride in normalized_rides if str(ride.get("status") or "").lower() in {"down", "closed", "maintenance", "stopped"} or _safe_int(ride.get("downtimeRisk"), 0) >= 80)
    capacity_pressure = _safe_int(value.get("capacity_pressure_pct"), 0)
    return {
        "guestFlow": {
            "rides": normalized_rides,
            "rideOpsSource": "live_feed",
            "rideOpsSourceEventId": event.get("id"),
            "rideOpsObservedAt": event.get("observed_at"),
        },
        "policy": {
            "rideOpsTrusted": True,
            "downRideCount": down_count,
            "topWaitRideId": top_wait.get("id"),
            "topWaitMins": top_wait.get("waitMins"),
            "topDowntimeRideId": top_downtime.get("id"),
            "topDowntimeRiskPct": top_downtime.get("downtimeRisk"),
            "capacityPressurePct": capacity_pressure,
            "rideControlRequiresMaintenanceClearance": down_count > 0,
        },
    }


def _ride_state_row(ride: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(ride.get("id") or "unknown"),
        "name": ride.get("name") or ride.get("id") or "Unknown ride",
        "zoneName": ride.get("zone"),
        "status": ride.get("status") or "unknown",
        "queueGuests": _safe_int(ride.get("queue_guests"), 0),
        "waitMins": _safe_int(ride.get("wait_mins"), 0),
        "downtimeRisk": _safe_int(ride.get("downtime_risk_pct"), 0),
        "capacityPerHour": _safe_int(ride.get("capacity_per_hour"), 0),
        "effectiveThroughput": _safe_int(ride.get("effective_throughput"), 0),
        "staffAvailable": _safe_int(ride.get("staff_available"), 0),
        "staffRequired": _safe_int(ride.get("staff_required"), 0),
        "maintenanceClearance": bool(ride.get("maintenance_clearance")),
        "liveFeedSource": "ride_ops",
        "sourceEventId": event.get("id"),
        "observedAt": event.get("observed_at"),
    }


def live_guest_flow_state_evidence(limit: int = 500) -> dict[str, Any]:
    feed_rows = _read_jsonl(_feed_log_path(), limit=limit)
    review_rows = _read_jsonl(_review_log_path(), limit=limit)
    flow_event = _latest_event(feed_rows, source="guest_flow", signal_type="zone_density")
    if not flow_event:
        return {
            "status": "fallback",
            "mode": "live_guest_flow_state_evidence",
            "source": "simulated_state",
            "trusted": False,
            "reason": "No live zone_density guest flow feed event has been loaded.",
            "state_patch": {},
        }

    feed_config = _required_feed("guest_flow")
    observed_at = _parse_time(flow_event.get("observed_at"))
    age_seconds = int((_now() - observed_at).total_seconds()) if observed_at else None
    stale = age_seconds is None or age_seconds > int(feed_config.get("max_stale_seconds") or 60)
    disposition = _review_disposition_for_event(str(flow_event.get("id") or ""), review_rows)
    trusted = bool(disposition.get("trusted")) and not stale
    value = flow_event.get("value", {}) if isinstance(flow_event.get("value"), dict) else {}
    state_patch = _guest_flow_state_patch(value, flow_event) if trusted else {}
    status = "trusted" if trusted else "stale" if stale else "review_blocked"
    reason = "Live guest flow is trusted for state reconciliation."
    if stale:
        reason = f"Latest guest flow event exceeded {feed_config.get('max_stale_seconds', 60)}s freshness budget."
    elif not disposition.get("trusted"):
        reason = f"Guest flow event review disposition is {disposition.get('status')}."
    return {
        "status": status,
        "mode": "live_guest_flow_state_evidence",
        "source": "live_feed",
        "trusted": trusted,
        "reason": reason,
        "event_id": flow_event.get("id"),
        "source_event_id": flow_event.get("source_event_id"),
        "observed_at": flow_event.get("observed_at"),
        "age_seconds": age_seconds,
        "confidence": flow_event.get("confidence"),
        "review": disposition,
        "guest_flow": value,
        "state_patch": state_patch,
    }


def _guest_flow_state_patch(value: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    zones = value.get("zones", []) if isinstance(value.get("zones"), list) else []
    paths = value.get("paths", []) if isinstance(value.get("paths"), list) else []
    normalized_zones = [_zone_state_row(zone, event) for zone in zones if isinstance(zone, dict)]
    normalized_paths = [_path_state_row(path, event) for path in paths if isinstance(path, dict)]
    top_zone = max(normalized_zones, key=lambda zone: _safe_int(zone.get("density"), 0), default={})
    top_path = max(normalized_paths, key=lambda path: _safe_int(path.get("congestionLevel"), 0), default={})
    congested_count = sum(1 for path in normalized_paths if str(path.get("status") or "").lower() in {"congested", "blocked"} or _safe_int(path.get("congestionLevel"), 0) >= 75)
    return {
        "guestFlow": {
            "zones": normalized_zones,
            "paths": normalized_paths,
            "representedGuests": _safe_int(value.get("represented_guests"), 0),
            "activeGroups": _safe_int(value.get("active_groups"), 0),
            "avgSatisfaction": _safe_float(value.get("avg_satisfaction"), 0),
            "guestFlowSource": "live_feed",
            "guestFlowSourceEventId": event.get("id"),
            "guestFlowObservedAt": event.get("observed_at"),
        },
        "policy": {
            "guestFlowTrusted": True,
            "topZoneId": top_zone.get("id"),
            "topZoneDensityPct": top_zone.get("density"),
            "topPath": f"{top_path.get('from')}->{top_path.get('to')}" if top_path else None,
            "topPathCongestionPct": top_path.get("congestionLevel"),
            "congestedPathCount": congested_count,
            "routingTakeRatePct": _safe_int(value.get("routing_take_rate_pct"), 0),
            "crowdSafetyReviewRequired": _safe_int(top_zone.get("density"), 0) >= 92 or _safe_int(top_path.get("congestionLevel"), 0) >= 90 or congested_count >= 2,
        },
    }


def _zone_state_row(zone: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(zone.get("id") or "unknown"),
        "name": zone.get("name") or zone.get("id") or "Unknown zone",
        "area": zone.get("area"),
        "processType": zone.get("process_type"),
        "flowType": zone.get("flow_type"),
        "capacity": _safe_int(zone.get("capacity"), 0),
        "currentGuests": _safe_int(zone.get("current_guests"), 0),
        "density": _safe_int(zone.get("density_pct"), 0),
        "densityGuestsPerSqM": _safe_float(zone.get("density_guests_per_sqm"), 0),
        "comfortScore": _safe_int(zone.get("comfort_score"), 0),
        "dominantIntent": zone.get("dominant_intent"),
        "waitMins": _safe_int(zone.get("wait_mins"), 0),
        "liveFeedSource": "guest_flow",
        "sourceEventId": event.get("id"),
        "observedAt": event.get("observed_at"),
    }


def _path_state_row(path: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    return {
        "from": path.get("from"),
        "to": path.get("to"),
        "fromName": path.get("from_name"),
        "toName": path.get("to_name"),
        "walkMinutes": _safe_int(path.get("walk_minutes"), 0),
        "capacity": _safe_int(path.get("capacity"), 0),
        "currentGuests": _safe_int(path.get("current_guests"), 0),
        "congestionLevel": _safe_int(path.get("congestion_level_pct"), 0),
        "widthUtilizationPct": _safe_int(path.get("width_utilization_pct"), 0),
        "status": path.get("status") or "open",
        "forwardTransfers": _safe_int(path.get("forward_transfers"), 0),
        "reverseTransfers": _safe_int(path.get("reverse_transfers"), 0),
        "liveFeedSource": "guest_flow",
        "sourceEventId": event.get("id"),
        "observedAt": event.get("observed_at"),
    }


def _latest_source_event(rows: list[dict[str, Any]], *, source: str) -> dict[str, Any] | None:
    matches = [row for row in rows if row.get("source") == source]
    if not matches:
        return None
    return max(matches, key=lambda row: _parse_time(row.get("observed_at")) or datetime.min.replace(tzinfo=UTC))


def live_staffing_state_evidence(limit: int = 500) -> dict[str, Any]:
    return _ops_state_evidence("staffing", "coverage", "live_staffing_state_evidence", _staffing_state_patch, limit)


def live_food_ops_state_evidence(limit: int = 500) -> dict[str, Any]:
    return _ops_state_evidence("food_ops", "inventory", "live_food_ops_state_evidence", _food_ops_state_patch, limit)


def live_operator_signal_state_evidence(limit: int = 500) -> dict[str, Any]:
    feed_rows = _read_jsonl(_feed_log_path(), limit=limit)
    event = _latest_source_event(feed_rows, source="operator_signal")
    return _event_state_evidence("operator_signal", event, "live_operator_signal_state_evidence", _operator_signal_state_patch, limit)


def _ops_state_evidence(source: str, signal_type: str, mode: str, patch_builder, limit: int) -> dict[str, Any]:
    feed_rows = _read_jsonl(_feed_log_path(), limit=limit)
    event = _latest_event(feed_rows, source=source, signal_type=signal_type)
    return _event_state_evidence(source, event, mode, patch_builder, limit)


def _event_state_evidence(source: str, event: dict[str, Any] | None, mode: str, patch_builder, limit: int) -> dict[str, Any]:
    if not event:
        return {
            "status": "fallback",
            "mode": mode,
            "source": "simulated_state",
            "trusted": False,
            "reason": f"No live {source} feed event has been loaded.",
            "state_patch": {},
        }
    review_rows = _read_jsonl(_review_log_path(), limit=limit)
    feed_config = _required_feed(source)
    observed_at = _parse_time(event.get("observed_at"))
    age_seconds = int((_now() - observed_at).total_seconds()) if observed_at else None
    stale = age_seconds is None or age_seconds > int(feed_config.get("max_stale_seconds") or 120)
    disposition = _review_disposition_for_event(str(event.get("id") or ""), review_rows)
    trusted = bool(disposition.get("trusted")) and not stale
    value = event.get("value", {}) if isinstance(event.get("value"), dict) else {}
    state_patch = patch_builder(value, event) if trusted else {}
    status = "trusted" if trusted else "stale" if stale else "review_blocked"
    reason = f"Live {source} is trusted for state reconciliation."
    if stale:
        reason = f"Latest {source} event exceeded {feed_config.get('max_stale_seconds', 120)}s freshness budget."
    elif not disposition.get("trusted"):
        reason = f"{source} event review disposition is {disposition.get('status')}."
    return {
        "status": status,
        "mode": mode,
        "source": "live_feed",
        "trusted": trusted,
        "reason": reason,
        "event_id": event.get("id"),
        "source_event_id": event.get("source_event_id"),
        "observed_at": event.get("observed_at"),
        "age_seconds": age_seconds,
        "confidence": event.get("confidence"),
        "review": disposition,
        source: value,
        "state_patch": state_patch,
    }


def _staffing_state_patch(value: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    return {
        "staffing": {
            "scheduled": _safe_int(value.get("scheduled"), 0),
            "checkedIn": _safe_int(value.get("checked_in"), 0),
            "openCallouts": _safe_int(value.get("open_callouts"), 0),
            "medicalTeams": _safe_int(value.get("medical_teams", value.get("health_team_count")), 0),
            "securityTeams": _safe_int(value.get("security_teams", value.get("guard_team_count")), 0),
            "source": "live_feed",
            "sourceEventId": event.get("id"),
            "observedAt": event.get("observed_at"),
        },
        "parkOps": {"staffReadyPct": _safe_int(value.get("staff_ready_pct"), 0)},
        "policy": {
            "staffingTrusted": True,
            "staffReadyPct": _safe_int(value.get("staff_ready_pct"), 0),
            "openCallouts": _safe_int(value.get("open_callouts"), 0),
            "coverageStatus": value.get("coverage_status"),
            "fatigueRiskPct": _safe_int(value.get("fatigue_risk_pct"), 0),
            "staffMovementReviewRequired": value.get("coverage_status") == "critical" or _safe_int(value.get("fatigue_risk_pct"), 0) >= 70,
        },
    }


def _food_ops_state_patch(value: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    locations = value.get("locations", []) if isinstance(value.get("locations"), list) else []
    return {
        "foodInventory": {
            "locations": [_food_state_row(row, event) for row in locations if isinstance(row, dict)],
            "suppressedItems": value.get("suppressed_items", []),
            "policy": value.get("policy"),
            "source": "live_feed",
            "sourceEventId": event.get("id"),
            "observedAt": event.get("observed_at"),
        },
        "policy": {
            "foodOpsTrusted": True,
            "topBacklogLocationId": (value.get("top_backlog_location") or {}).get("id") if isinstance(value.get("top_backlog_location"), dict) else None,
            "topBacklog": (value.get("top_backlog_location") or {}).get("mobile_order_backlog") if isinstance(value.get("top_backlog_location"), dict) else None,
            "topEtaMinutes": (value.get("top_eta_location") or {}).get("pickup_eta_minutes") if isinstance(value.get("top_eta_location"), dict) else None,
            "kitchenLoadPct": _safe_int(value.get("kitchen_load_pct"), 0),
            "foodReviewRequired": _safe_int(value.get("kitchen_load_pct"), 0) >= 85 or bool(value.get("low_inventory_items")),
        },
    }


def _food_state_row(row: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id") or "unknown"),
        "name": row.get("name") or row.get("id") or "Unknown location",
        "mobileOrderBacklog": _safe_int(row.get("mobile_order_backlog"), 0),
        "pickupEtaMinutes": _safe_int(row.get("pickup_eta_minutes"), 0),
        "lowInventoryItems": row.get("low_inventory_items", []),
        "availableItems": row.get("available_items", []),
        "liveFeedSource": "food_ops",
        "sourceEventId": event.get("id"),
        "observedAt": event.get("observed_at"),
    }


def _operator_signal_state_patch(value: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    return {
        "guestCare": {
            "openCases": _safe_int(value.get("open_cases"), 0),
            "complaintRatePct": _safe_float(value.get("complaint_rate_pct"), 0),
            "topDrivers": value.get("top_drivers", []),
            "recoveryQueue": value.get("recovery_queue", []),
            "policy": value.get("policy"),
            "source": "live_feed",
            "sourceEventId": event.get("id"),
            "observedAt": event.get("observed_at"),
        },
        "policy": {
            "operatorSignalTrusted": True,
            "openGuestCareCases": _safe_int(value.get("open_cases"), 0),
            "complaintRatePct": _safe_float(value.get("complaint_rate_pct"), 0),
            "sensitiveReport": bool(value.get("sensitive_report")),
            "operatorReviewRequired": bool(value.get("sensitive_report")) or _safe_int(value.get("open_cases"), 0) >= 40,
        },
    }


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in {None, ""}:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in {None, ""}:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def apply_live_weather_to_state(state: dict[str, Any], limit: int = 500) -> dict[str, Any]:
    patched = deepcopy(state) if isinstance(state, dict) else {}
    evidence = live_weather_state_evidence(limit=limit)
    patched.setdefault("liveFeedEvidence", {})["weather"] = evidence
    if not evidence.get("trusted"):
        return patched

    patch = evidence.get("state_patch", {}) if isinstance(evidence.get("state_patch"), dict) else {}
    patched["weather"] = {**(patched.get("weather", {}) if isinstance(patched.get("weather"), dict) else {}), **patch.get("weather", {})}
    if isinstance(patch.get("incidentReadiness"), dict):
        patched["incidentReadiness"] = {
            **(patched.get("incidentReadiness", {}) if isinstance(patched.get("incidentReadiness"), dict) else {}),
            **patch["incidentReadiness"],
        }
    if isinstance(patch.get("parkOps"), dict):
        patched["parkOps"] = {**(patched.get("parkOps", {}) if isinstance(patched.get("parkOps"), dict) else {}), **patch["parkOps"]}
    if isinstance(patch.get("policy"), dict):
        patched.setdefault("policyGates", {})["liveWeather"] = patch["policy"]
    _append_weather_alert(patched, evidence)
    return patched


def apply_live_ride_ops_to_state(state: dict[str, Any], limit: int = 500) -> dict[str, Any]:
    patched = deepcopy(state) if isinstance(state, dict) else {}
    evidence = live_ride_ops_state_evidence(limit=limit)
    patched.setdefault("liveFeedEvidence", {})["ride_ops"] = evidence
    if not evidence.get("trusted"):
        return patched

    patch = evidence.get("state_patch", {}) if isinstance(evidence.get("state_patch"), dict) else {}
    guest_patch = patch.get("guestFlow", {}) if isinstance(patch.get("guestFlow"), dict) else {}
    if guest_patch:
        guest_flow = patched.get("guestFlow", {}) if isinstance(patched.get("guestFlow"), dict) else {}
        patched["guestFlow"] = {**guest_flow, **guest_patch}
    if isinstance(patch.get("policy"), dict):
        patched.setdefault("policyGates", {})["liveRideOps"] = patch["policy"]
    _append_ride_ops_alert(patched, evidence)
    return patched


def apply_live_guest_flow_to_state(state: dict[str, Any], limit: int = 500) -> dict[str, Any]:
    patched = deepcopy(state) if isinstance(state, dict) else {}
    evidence = live_guest_flow_state_evidence(limit=limit)
    patched.setdefault("liveFeedEvidence", {})["guest_flow"] = evidence
    if not evidence.get("trusted"):
        return patched

    patch = evidence.get("state_patch", {}) if isinstance(evidence.get("state_patch"), dict) else {}
    guest_patch = patch.get("guestFlow", {}) if isinstance(patch.get("guestFlow"), dict) else {}
    if guest_patch:
        guest_flow = patched.get("guestFlow", {}) if isinstance(patched.get("guestFlow"), dict) else {}
        patched["guestFlow"] = {**guest_flow, **guest_patch}
    if isinstance(patch.get("policy"), dict):
        patched.setdefault("policyGates", {})["liveGuestFlow"] = patch["policy"]
    _append_guest_flow_alert(patched, evidence)
    return patched


def apply_live_staffing_to_state(state: dict[str, Any], limit: int = 500) -> dict[str, Any]:
    return _apply_ops_evidence_to_state(state, live_staffing_state_evidence(limit), "staffing", "liveStaffing", _append_staffing_alert)


def apply_live_food_ops_to_state(state: dict[str, Any], limit: int = 500) -> dict[str, Any]:
    return _apply_ops_evidence_to_state(state, live_food_ops_state_evidence(limit), "food_ops", "liveFoodOps", _append_food_ops_alert)


def apply_live_operator_signal_to_state(state: dict[str, Any], limit: int = 500) -> dict[str, Any]:
    return _apply_ops_evidence_to_state(state, live_operator_signal_state_evidence(limit), "operator_signal", "liveOperatorSignal", _append_operator_signal_alert)


def _apply_ops_evidence_to_state(state: dict[str, Any], evidence: dict[str, Any], evidence_key: str, policy_key: str, alert_fn) -> dict[str, Any]:
    patched = deepcopy(state) if isinstance(state, dict) else {}
    patched.setdefault("liveFeedEvidence", {})[evidence_key] = evidence
    if not evidence.get("trusted"):
        return patched
    patch = evidence.get("state_patch", {}) if isinstance(evidence.get("state_patch"), dict) else {}
    for key in ("staffing", "parkOps", "foodInventory", "guestCare"):
        if isinstance(patch.get(key), dict):
            patched[key] = {**(patched.get(key, {}) if isinstance(patched.get(key), dict) else {}), **patch[key]}
    if isinstance(patch.get("policy"), dict):
        patched.setdefault("policyGates", {})[policy_key] = patch["policy"]
    alert_fn(patched, evidence)
    return patched


def live_weather_policy_gate(action: dict[str, Any] | None, state: dict[str, Any] | None = None) -> dict[str, Any]:
    action = action if isinstance(action, dict) else {}
    target = str(action.get("target") or "").lower()
    action_name = str(action.get("action") or "").lower()
    evidence = (
        (state.get("liveFeedEvidence", {}) if isinstance(state, dict) else {}).get("weather", {})
        if isinstance((state or {}).get("liveFeedEvidence", {}), dict)
        else {}
    )
    if not isinstance(evidence, dict) or not evidence:
        evidence = live_weather_state_evidence()
    policy = (evidence.get("state_patch", {}) or {}).get("policy", {}) if isinstance(evidence.get("state_patch"), dict) else {}
    weather_sensitive_targets = {"ride", "equipment", "crowd_safety", "traffic", "event", "energy", "show", "entertainment"}
    weather_sensitive_actions = {"reroute_down_ride", "custom_response", "calm_reroute", "apply_custom_comfort_mix", "dispatch", "respond"}
    weather_sensitive = target in weather_sensitive_targets or action_name in weather_sensitive_actions
    findings = []

    if evidence.get("source") == "live_feed" and not evidence.get("trusted") and weather_sensitive:
        return {
            "allowed": False,
            "gate_status": "review",
            "weather_gate_status": evidence.get("status"),
            "findings": [
                f"Weather-sensitive action requires review because live weather evidence is {evidence.get('status')}.",
                evidence.get("reason") or "Live weather is not trusted for state reconciliation.",
            ],
            "evidence": evidence,
        }

    if policy.get("weatherRequiresOutdoorReview") and weather_sensitive:
        return {
            "allowed": False,
            "gate_status": "review",
            "weather_gate_status": "outdoor_review_required",
            "findings": [
                "Live weather requires human review before outdoor, crowd, ride, or equipment actions.",
                f"Storm {policy.get('stormRiskPct')}%, heat {policy.get('heatRisk')}, lightning window {policy.get('lightningWindow')}.",
            ],
            "evidence": evidence,
        }

    if evidence.get("trusted"):
        findings.append(f"Live weather event {evidence.get('event_id')} was trusted for this gate.")
    else:
        findings.append("No trusted live weather event affected this action.")
    return {
        "allowed": True,
        "gate_status": "allowed",
        "weather_gate_status": "trusted" if evidence.get("trusted") else evidence.get("status", "fallback"),
        "findings": findings,
        "evidence": evidence,
    }


def live_ride_ops_policy_gate(action: dict[str, Any] | None, state: dict[str, Any] | None = None) -> dict[str, Any]:
    action = action if isinstance(action, dict) else {}
    target = str(action.get("target") or "").lower()
    action_name = str(action.get("action") or action.get("id") or "").lower()
    label = str(action.get("label") or "").lower()
    evidence = (
        (state.get("liveFeedEvidence", {}) if isinstance(state, dict) else {}).get("ride_ops", {})
        if isinstance((state or {}).get("liveFeedEvidence", {}), dict)
        else {}
    )
    if not isinstance(evidence, dict) or not evidence:
        evidence = live_ride_ops_state_evidence()
    policy = (evidence.get("state_patch", {}) or {}).get("policy", {}) if isinstance(evidence.get("state_patch"), dict) else {}
    ride_sensitive = target in {"ride", "equipment"} or any(term in action_name or term in label for term in ("ride", "coaster", "reopen", "queue", "maintenance"))
    reopening = any(term in action_name or term in label for term in ("reopen", "mark_safe", "maintenance_clearance", "override"))

    if evidence.get("source") == "live_feed" and not evidence.get("trusted") and ride_sensitive:
        return {
            "allowed": False,
            "gate_status": "review",
            "ride_ops_gate_status": evidence.get("status"),
            "findings": [
                f"Ride-sensitive action requires review because live ride operations evidence is {evidence.get('status')}.",
                evidence.get("reason") or "Live ride operations are not trusted for state reconciliation.",
            ],
            "evidence": evidence,
        }

    if ride_sensitive and evidence.get("source") != "live_feed":
        return {
            "allowed": False,
            "gate_status": "review",
            "ride_ops_gate_status": evidence.get("status", "fallback"),
            "findings": ["Ride-sensitive action requires a fresh ride_ops feed event before dispatch or training admission."],
            "evidence": evidence,
        }

    if reopening and policy.get("rideControlRequiresMaintenanceClearance"):
        return {
            "allowed": False,
            "gate_status": "review",
            "ride_ops_gate_status": "maintenance_clearance_required",
            "findings": [
                "Ride reopening or safety-clearance action requires explicit maintenance authority.",
                f"Live ride ops reports {policy.get('downRideCount')} down/high-risk ride(s); top downtime risk {policy.get('topDowntimeRiskPct')}%.",
            ],
            "evidence": evidence,
        }

    findings = []
    if evidence.get("trusted"):
        findings.append(f"Live ride ops event {evidence.get('event_id')} was trusted for this gate.")
    else:
        findings.append("No trusted live ride ops event affected this action.")
    return {
        "allowed": True,
        "gate_status": "allowed",
        "ride_ops_gate_status": "trusted" if evidence.get("trusted") else evidence.get("status", "fallback"),
        "findings": findings,
        "evidence": evidence,
    }


def live_guest_flow_policy_gate(action: dict[str, Any] | None, state: dict[str, Any] | None = None) -> dict[str, Any]:
    action = action if isinstance(action, dict) else {}
    target = str(action.get("target") or "").lower()
    action_name = str(action.get("action") or action.get("id") or "").lower()
    label = str(action.get("label") or "").lower()
    evidence = (
        (state.get("liveFeedEvidence", {}) if isinstance(state, dict) else {}).get("guest_flow", {})
        if isinstance((state or {}).get("liveFeedEvidence", {}), dict)
        else {}
    )
    if not isinstance(evidence, dict) or not evidence:
        evidence = live_guest_flow_state_evidence()
    policy = (evidence.get("state_patch", {}) or {}).get("policy", {}) if isinstance(evidence.get("state_patch"), dict) else {}
    flow_sensitive = target in {"ride", "food", "crowd_safety", "traffic", "event", "show", "guest_app"} or any(
        term in action_name or term in label for term in ("reroute", "route", "crowd", "queue", "dispatch", "guest", "path", "zone")
    )

    if evidence.get("source") == "live_feed" and not evidence.get("trusted") and flow_sensitive:
        return {
            "allowed": False,
            "gate_status": "review",
            "guest_flow_gate_status": evidence.get("status"),
            "findings": [
                f"Flow-sensitive action requires review because live guest flow evidence is {evidence.get('status')}.",
                evidence.get("reason") or "Live guest flow is not trusted for state reconciliation.",
            ],
            "evidence": evidence,
        }

    if flow_sensitive and evidence.get("source") != "live_feed":
        return {
            "allowed": False,
            "gate_status": "review",
            "guest_flow_gate_status": evidence.get("status", "fallback"),
            "findings": ["Flow-sensitive action requires a fresh guest_flow feed event before dispatch or training admission."],
            "evidence": evidence,
        }

    if policy.get("crowdSafetyReviewRequired") and flow_sensitive:
        return {
            "allowed": False,
            "gate_status": "review",
            "guest_flow_gate_status": "crowd_safety_review_required",
            "findings": [
                "Live guest flow requires human review before crowd routing or high-pressure guest messaging.",
                f"Top zone {policy.get('topZoneId')} at {policy.get('topZoneDensityPct')}%; top path congestion {policy.get('topPathCongestionPct')}%.",
            ],
            "evidence": evidence,
        }

    findings = []
    if evidence.get("trusted"):
        findings.append(f"Live guest flow event {evidence.get('event_id')} was trusted for this gate.")
    else:
        findings.append("No trusted live guest flow event affected this action.")
    return {
        "allowed": True,
        "gate_status": "allowed",
        "guest_flow_gate_status": "trusted" if evidence.get("trusted") else evidence.get("status", "fallback"),
        "findings": findings,
        "evidence": evidence,
    }


def live_staffing_policy_gate(action: dict[str, Any] | None, state: dict[str, Any] | None = None) -> dict[str, Any]:
    action = action if isinstance(action, dict) else {}
    text = f"{action.get('target','')} {action.get('action','')} {action.get('label','')}".lower()
    sensitive = any(term in text for term in ("staff", "worker", "labor", "medical", "security", "move", "dispatch"))
    evidence = _evidence_from_state_or_latest(state, "staffing", live_staffing_state_evidence)
    policy = (evidence.get("state_patch", {}) or {}).get("policy", {}) if isinstance(evidence.get("state_patch"), dict) else {}
    return _ops_policy_gate(evidence, policy, sensitive, "staffing", "staffing_gate_status", "staffMovementReviewRequired", "Staff movement requires human review under current live staffing pressure.")


def live_food_ops_policy_gate(action: dict[str, Any] | None, state: dict[str, Any] | None = None) -> dict[str, Any]:
    action = action if isinstance(action, dict) else {}
    text = f"{action.get('target','')} {action.get('action','')} {action.get('label','')}".lower()
    sensitive = any(term in text for term in ("food", "kitchen", "inventory", "mobile", "prep", "restaurant"))
    evidence = _evidence_from_state_or_latest(state, "food_ops", live_food_ops_state_evidence)
    policy = (evidence.get("state_patch", {}) or {}).get("policy", {}) if isinstance(evidence.get("state_patch"), dict) else {}
    return _ops_policy_gate(evidence, policy, sensitive, "food_ops", "food_ops_gate_status", "foodReviewRequired", "Food operations requires human review under current kitchen/inventory pressure.")


def live_operator_signal_policy_gate(action: dict[str, Any] | None, state: dict[str, Any] | None = None) -> dict[str, Any]:
    action = action if isinstance(action, dict) else {}
    text = f"{action.get('target','')} {action.get('action','')} {action.get('label','')}".lower()
    sensitive = any(term in text for term in ("guest", "care", "incident", "medical", "security", "safety", "compensation", "recovery"))
    evidence = _evidence_from_state_or_latest(state, "operator_signal", live_operator_signal_state_evidence)
    policy = (evidence.get("state_patch", {}) or {}).get("policy", {}) if isinstance(evidence.get("state_patch"), dict) else {}
    return _ops_policy_gate(evidence, policy, sensitive, "operator_signal", "operator_signal_gate_status", "operatorReviewRequired", "Operator/guest report requires human review before action.")


def _evidence_from_state_or_latest(state: dict[str, Any] | None, key: str, getter) -> dict[str, Any]:
    evidence = (
        (state.get("liveFeedEvidence", {}) if isinstance(state, dict) else {}).get(key, {})
        if isinstance((state or {}).get("liveFeedEvidence", {}), dict)
        else {}
    )
    return evidence if isinstance(evidence, dict) and evidence else getter()


def _ops_policy_gate(evidence: dict[str, Any], policy: dict[str, Any], sensitive: bool, source: str, status_key: str, review_key: str, review_msg: str) -> dict[str, Any]:
    if evidence.get("source") == "live_feed" and not evidence.get("trusted") and sensitive:
        return {
            "allowed": False,
            "gate_status": "review",
            status_key: evidence.get("status"),
            "findings": [f"{source} action requires review because live evidence is {evidence.get('status')}.", evidence.get("reason") or f"Live {source} is not trusted."],
            "evidence": evidence,
        }
    if sensitive and evidence.get("source") != "live_feed":
        return {
            "allowed": False,
            "gate_status": "review",
            status_key: evidence.get("status", "fallback"),
            "findings": [f"{source} action requires a fresh live feed event before dispatch or training admission."],
            "evidence": evidence,
        }
    if policy.get(review_key) and sensitive:
        return {
            "allowed": False,
            "gate_status": "review",
            status_key: "human_review_required",
            "findings": [review_msg],
            "evidence": evidence,
        }
    return {
        "allowed": True,
        "gate_status": "allowed",
        status_key: "trusted" if evidence.get("trusted") else evidence.get("status", "fallback"),
        "findings": [f"Live {source} event {evidence.get('event_id')} was trusted for this gate." if evidence.get("trusted") else f"No trusted live {source} event affected this action."],
        "evidence": evidence,
    }


def live_weather_training_gate() -> dict[str, Any]:
    evidence = live_weather_state_evidence()
    if evidence.get("source") == "live_feed" and not evidence.get("trusted"):
        return {
            "eligible": False,
            "status": "blocked",
            "reason": evidence.get("reason") or "Live weather evidence is not trusted.",
            "evidence": evidence,
            "required_for_training": ["fresh live weather or explicit fallback mode", "no open review on weather event", "measured outcome reward"],
        }
    return {
        "eligible": True,
        "status": "eligible_live_weather" if evidence.get("trusted") else "eligible_no_live_weather",
        "reason": "Weather feed quality does not block training eligibility.",
        "evidence": evidence,
        "required_for_training": ["fresh live weather or explicit fallback mode", "no open review on weather event", "measured outcome reward"],
    }


def live_ride_ops_training_gate() -> dict[str, Any]:
    evidence = live_ride_ops_state_evidence()
    if evidence.get("source") == "live_feed" and not evidence.get("trusted"):
        return {
            "eligible": False,
            "status": "blocked",
            "reason": evidence.get("reason") or "Live ride operations evidence is not trusted.",
            "evidence": evidence,
            "required_for_training": ["fresh ride_ops feed", "no open review on ride_ops event", "measured post-action queue/downtime outcome"],
        }
    if evidence.get("source") != "live_feed":
        return {
            "eligible": False,
            "status": "blocked",
            "reason": "Ride operations training requires a real ride_ops feed event, not simulated state fallback.",
            "evidence": evidence,
            "required_for_training": ["fresh ride_ops feed", "no open review on ride_ops event", "measured post-action queue/downtime outcome"],
        }
    return {
        "eligible": True,
        "status": "eligible_live_ride_ops",
        "reason": "Ride operations feed quality does not block training eligibility.",
        "evidence": evidence,
        "required_for_training": ["fresh ride_ops feed", "no open review on ride_ops event", "measured post-action queue/downtime outcome"],
    }


def live_guest_flow_training_gate() -> dict[str, Any]:
    evidence = live_guest_flow_state_evidence()
    if evidence.get("source") == "live_feed" and not evidence.get("trusted"):
        return {
            "eligible": False,
            "status": "blocked",
            "reason": evidence.get("reason") or "Live guest flow evidence is not trusted.",
            "evidence": evidence,
            "required_for_training": ["fresh guest_flow feed", "no open review on guest_flow event", "measured post-action density/path outcome"],
        }
    if evidence.get("source") != "live_feed":
        return {
            "eligible": False,
            "status": "blocked",
            "reason": "Guest flow training requires a real guest_flow feed event, not simulated state fallback.",
            "evidence": evidence,
            "required_for_training": ["fresh guest_flow feed", "no open review on guest_flow event", "measured post-action density/path outcome"],
        }
    return {
        "eligible": True,
        "status": "eligible_live_guest_flow",
        "reason": "Guest flow feed quality does not block training eligibility.",
        "evidence": evidence,
        "required_for_training": ["fresh guest_flow feed", "no open review on guest_flow event", "measured post-action density/path outcome"],
    }


def live_staffing_training_gate() -> dict[str, Any]:
    return _live_required_training_gate(live_staffing_state_evidence(), "staffing", "eligible_live_staffing", ["fresh staffing feed", "no open review on staffing event", "measured post-action coverage outcome"])


def live_food_ops_training_gate() -> dict[str, Any]:
    return _live_required_training_gate(live_food_ops_state_evidence(), "food_ops", "eligible_live_food_ops", ["fresh food_ops feed", "no open review on food_ops event", "measured post-action backlog/ETA outcome"])


def live_operator_signal_training_gate() -> dict[str, Any]:
    return _live_required_training_gate(live_operator_signal_state_evidence(), "operator_signal", "eligible_live_operator_signal", ["fresh operator_signal feed", "no open review on sensitive report", "measured post-action guest-care outcome"])


def _live_required_training_gate(evidence: dict[str, Any], source: str, eligible_status: str, required: list[str]) -> dict[str, Any]:
    if evidence.get("source") == "live_feed" and not evidence.get("trusted"):
        return {"eligible": False, "status": "blocked", "reason": evidence.get("reason") or f"Live {source} evidence is not trusted.", "evidence": evidence, "required_for_training": required}
    if evidence.get("source") != "live_feed":
        return {"eligible": False, "status": "blocked", "reason": f"{source} training requires a real live feed event, not simulated state fallback.", "evidence": evidence, "required_for_training": required}
    return {"eligible": True, "status": eligible_status, "reason": f"{source} feed quality does not block training eligibility.", "evidence": evidence, "required_for_training": required}


def _append_weather_alert(state: dict[str, Any], evidence: dict[str, Any]) -> None:
    policy = (evidence.get("state_patch", {}) or {}).get("policy", {}) if isinstance(evidence.get("state_patch"), dict) else {}
    if not policy.get("weatherRequiresOutdoorReview"):
        return
    alerts = state.setdefault("alerts", [])
    if not isinstance(alerts, list):
        state["alerts"] = alerts = []
    alerts.insert(
        0,
        {
            "severity": "warning",
            "title": "Live weather review required",
            "detail": f"Storm {policy.get('stormRiskPct', 0)}%, heat {policy.get('heatRisk', 'unknown')}; outdoor actions require policy review.",
        },
    )


def _append_ride_ops_alert(state: dict[str, Any], evidence: dict[str, Any]) -> None:
    policy = (evidence.get("state_patch", {}) or {}).get("policy", {}) if isinstance(evidence.get("state_patch"), dict) else {}
    if _safe_int(policy.get("downRideCount"), 0) <= 0 and _safe_int(policy.get("topWaitMins"), 0) < 75:
        return
    alerts = state.setdefault("alerts", [])
    if not isinstance(alerts, list):
        state["alerts"] = alerts = []
    alerts.insert(
        0,
        {
            "severity": "warning",
            "title": "Live ride operations pressure",
            "detail": f"{policy.get('downRideCount', 0)} down/high-risk ride(s); top wait {policy.get('topWaitMins', 0)} min.",
        },
    )


def _append_guest_flow_alert(state: dict[str, Any], evidence: dict[str, Any]) -> None:
    policy = (evidence.get("state_patch", {}) or {}).get("policy", {}) if isinstance(evidence.get("state_patch"), dict) else {}
    if not policy.get("crowdSafetyReviewRequired") and _safe_int(policy.get("topZoneDensityPct"), 0) < 85:
        return
    alerts = state.setdefault("alerts", [])
    if not isinstance(alerts, list):
        state["alerts"] = alerts = []
    alerts.insert(
        0,
        {
            "severity": "warning",
            "title": "Live guest flow pressure",
            "detail": f"Top zone {policy.get('topZoneId', 'unknown')} density {policy.get('topZoneDensityPct', 0)}%; path congestion {policy.get('topPathCongestionPct', 0)}%.",
        },
    )


def _append_staffing_alert(state: dict[str, Any], evidence: dict[str, Any]) -> None:
    policy = (evidence.get("state_patch", {}) or {}).get("policy", {}) if isinstance(evidence.get("state_patch"), dict) else {}
    if not policy.get("staffMovementReviewRequired") and _safe_int(policy.get("openCallouts"), 0) < 8:
        return
    _append_alert(state, "Live staffing pressure", f"{policy.get('staffReadyPct', 0)}% ready; {policy.get('openCallouts', 0)} open callouts.")


def _append_food_ops_alert(state: dict[str, Any], evidence: dict[str, Any]) -> None:
    policy = (evidence.get("state_patch", {}) or {}).get("policy", {}) if isinstance(evidence.get("state_patch"), dict) else {}
    if not policy.get("foodReviewRequired") and _safe_int(policy.get("topBacklog"), 0) < 60:
        return
    _append_alert(state, "Live food operations pressure", f"Top backlog {policy.get('topBacklog', 0)}; ETA {policy.get('topEtaMinutes', 0)} min.")


def _append_operator_signal_alert(state: dict[str, Any], evidence: dict[str, Any]) -> None:
    policy = (evidence.get("state_patch", {}) or {}).get("policy", {}) if isinstance(evidence.get("state_patch"), dict) else {}
    if not policy.get("operatorReviewRequired") and _safe_float(policy.get("complaintRatePct"), 0) < 10:
        return
    _append_alert(state, "Live operator/guest report pressure", f"{policy.get('openGuestCareCases', 0)} cases; complaint rate {policy.get('complaintRatePct', 0)}%.")


def _append_alert(state: dict[str, Any], title: str, detail: str) -> None:
    alerts = state.setdefault("alerts", [])
    if not isinstance(alerts, list):
        state["alerts"] = alerts = []
    alerts.insert(0, {"severity": "warning", "title": title, "detail": detail})


def review_training_ledger(limit: int = 120) -> dict[str, Any]:
    rows = _read_jsonl(_review_log_path(), limit=limit)
    review_state = _fold_review_state(rows)
    statuses = Counter(str(row.get("status") or "unknown") for row in rows)
    decisions = Counter(str(row.get("decision") or row.get("priority") or "pending") for row in rows)
    training_candidates = [
        row
        for row in rows
        if row.get("review_type") == "operator_disposition" and row.get("labels_or_reward_changed") is False
    ]
    return {
        "status": "ready" if rows else "empty",
        "mode": "human_review_training_ledger",
        "created_at": _now_iso(),
        "summary": {
            "row_count": len(rows),
            "open_count": len(review_state["open_reviews"]),
            "closed_count": len(review_state["closed_reviews"]),
            "training_candidate_count": len(training_candidates),
            "statuses": dict(statuses),
            "decisions": dict(decisions),
        },
        "open_reviews": review_state["open_reviews"][:20],
        "closed_reviews": review_state["closed_reviews"][:20],
        "rows": rows[:limit],
        "training_rule": "Review decisions become supervised evidence; reward remains measured from post-action outcomes.",
        "boundary": "No LLM-generated label is accepted as reward. Human labels require measured outcome attribution before promotion.",
        "uses_seed_data": False,
        "llm_used_for_reward_or_label": False,
        "labels_or_reward_changed": False,
    }


def _fold_review_state(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    dispositions_by_case: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("review_type") != "operator_disposition":
            continue
        case_id = str(row.get("case_id") or "")
        if case_id and case_id not in dispositions_by_case:
            dispositions_by_case[case_id] = row

    open_reviews: list[dict[str, Any]] = []
    closed_reviews: list[dict[str, Any]] = []
    seen_cases: set[str] = set()
    for row in rows:
        if row.get("review_type") != "feed_event_review":
            continue
        case_id = str(row.get("id") or "")
        if not case_id or case_id in seen_cases:
            continue
        seen_cases.add(case_id)
        disposition = dispositions_by_case.get(case_id)
        if disposition:
            closed_reviews.append(
                {
                    **row,
                    "status": "closed",
                    "disposition": {
                        "id": disposition.get("id"),
                        "created_at": disposition.get("created_at"),
                        "decision": disposition.get("decision"),
                        "reviewer": disposition.get("reviewer"),
                        "reason": disposition.get("reason"),
                        "training_label": disposition.get("training_label"),
                    },
                }
            )
        elif row.get("status") != "closed":
            open_reviews.append(row)
    return {"open_reviews": open_reviews, "closed_reviews": closed_reviews}
