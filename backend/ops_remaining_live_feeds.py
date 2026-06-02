from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from live_feedback_loop import ingest_live_feed_event


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in {None, ""}:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in {None, ""}:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _config(feed: str, source: str, boundary: str) -> dict[str, Any]:
    upper = feed.upper()
    return {
        "provider": os.getenv(f"PARKPULSE_{upper}_FEED_PROVIDER", "parkpulse_runtime"),
        "source": source,
        "source_url": os.getenv(f"PARKPULSE_{upper}_FEED_URL", f"runtime://park_state/{source}"),
        "timeout_seconds": _safe_int(os.getenv(f"PARKPULSE_{upper}_FEED_TIMEOUT_SECONDS"), 5),
        "boundary": boundary,
    }


def staffing_feed_config() -> dict[str, Any]:
    return _config(
        "STAFFING",
        "staffing",
        "Staffing facts can guide coverage and task recommendations, but staff movement still requires labor, certification, break, and human-approval gates.",
    )


def food_ops_feed_config() -> dict[str, Any]:
    return _config(
        "FOOD_OPS",
        "foodInventory",
        "Food operations facts can guide inventory, prep, and guest-routing recommendations, but substitutions, safety, and guest compensation still require policy gates.",
    )


def operator_signal_feed_config() -> dict[str, Any]:
    return _config(
        "OPERATOR_SIGNAL",
        "guestCare",
        "Operator and guest reports are evidence inputs only. Sensitive reports create review cases and do not set reward or dispatch authority.",
    )


def build_staffing_live_feed_events(park_state: dict[str, Any] | None, observed_at: str | None = None) -> list[dict[str, Any]]:
    state = park_state if isinstance(park_state, dict) else {}
    staffing = state.get("staffing", {}) if isinstance(state.get("staffing"), dict) else {}
    if not staffing:
        return []
    observed = observed_at or _now_iso()
    config = staffing_feed_config()
    scheduled = _safe_int(staffing.get("scheduled"))
    checked_in = _safe_int(staffing.get("checkedIn"))
    open_callouts = _safe_int(staffing.get("openCallouts"))
    ready_pct = round((checked_in / scheduled) * 100) if scheduled else 0
    fatigue_risk_pct = max(0, min(100, open_callouts * 4 + max(0, 85 - ready_pct)))
    base = {
        "provider": config["provider"],
        "scheduled": scheduled,
        "checked_in": checked_in,
        "open_callouts": open_callouts,
        "health_team_count": _safe_int(staffing.get("medicalTeams")),
        "guard_team_count": _safe_int(staffing.get("securityTeams")),
        "staff_ready_pct": ready_pct,
        "fatigue_risk_pct": fatigue_risk_pct,
        "coverage_status": "critical" if ready_pct < 75 or open_callouts >= 20 else "watch" if ready_pct < 88 or open_callouts >= 8 else "ready",
    }
    return [
        _event("staffing", "coverage", observed, "staffing", "park_staff", base, config),
        _event("staffing", "fatigue", observed, "staffing", "park_staff", {"fatigue_risk_pct": fatigue_risk_pct, "open_callouts": open_callouts}, config),
        _event("staffing", "break_window", observed, "staffing", "break_coverage", {"staff_ready_pct": ready_pct, "coverage_status": base["coverage_status"]}, config),
        _event("staffing", "training_tag", observed, "staffing", "certification_pool", {"health_team_count": base["health_team_count"], "guard_team_count": base["guard_team_count"]}, config),
    ]


def build_food_ops_live_feed_events(park_state: dict[str, Any] | None, observed_at: str | None = None) -> list[dict[str, Any]]:
    state = park_state if isinstance(park_state, dict) else {}
    food = state.get("foodInventory", {}) if isinstance(state.get("foodInventory"), dict) else {}
    locations = [row for row in food.get("locations", []) if isinstance(row, dict)] if isinstance(food.get("locations"), list) else []
    if not food and not locations:
        return []
    observed = observed_at or _now_iso()
    config = food_ops_feed_config()
    normalized_locations = [_food_location(row) for row in locations]
    top_backlog = max(normalized_locations, key=lambda row: _safe_int(row.get("mobile_order_backlog")), default={})
    top_eta = max(normalized_locations, key=lambda row: _safe_int(row.get("pickup_eta_minutes")), default={})
    low_inventory_items = sorted({str(item) for row in normalized_locations for item in row.get("low_inventory_items", [])})
    base = {
        "provider": config["provider"],
        "locations": normalized_locations,
        "suppressed_items": food.get("suppressedItems", []) if isinstance(food.get("suppressedItems"), list) else [],
        "policy": food.get("policy"),
        "top_backlog_location": top_backlog,
        "top_eta_location": top_eta,
        "low_inventory_items": low_inventory_items,
        "kitchen_load_pct": min(100, _safe_int(top_backlog.get("mobile_order_backlog")) + _safe_int(top_eta.get("pickup_eta_minutes"))),
    }
    return [
        _event("food_ops", "inventory", observed, "food_location", "park_food", base, config),
        _event("food_ops", "mobile_backlog", observed, "food_location", str(top_backlog.get("id") or "unknown"), top_backlog, config),
        _event("food_ops", "prep_eta", observed, "food_location", str(top_eta.get("id") or "unknown"), top_eta, config),
        _event("food_ops", "kitchen_load", observed, "food_location", "park_food", {"kitchen_load_pct": base["kitchen_load_pct"], "low_inventory_items": low_inventory_items}, config),
    ]


def build_operator_signal_live_feed_events(park_state: dict[str, Any] | None, observed_at: str | None = None) -> list[dict[str, Any]]:
    state = park_state if isinstance(park_state, dict) else {}
    guest_care = state.get("guestCare", {}) if isinstance(state.get("guestCare"), dict) else {}
    if not guest_care:
        return []
    observed = observed_at or _now_iso()
    config = operator_signal_feed_config()
    complaint_rate = _safe_float(guest_care.get("complaintRatePct"))
    open_cases = _safe_int(guest_care.get("openCases"))
    top_drivers = guest_care.get("topDrivers", []) if isinstance(guest_care.get("topDrivers"), list) else []
    recovery_queue = guest_care.get("recoveryQueue", []) if isinstance(guest_care.get("recoveryQueue"), list) else []
    value = {
        "provider": config["provider"],
        "open_cases": open_cases,
        "complaint_rate_pct": complaint_rate,
        "top_drivers": top_drivers,
        "recovery_queue": recovery_queue,
        "policy": guest_care.get("policy"),
        "sensitive_report": any(str(item).lower() in {"medical", "security", "safety"} for item in top_drivers),
    }
    return [
        _event("operator_signal", "guest_care", observed, "guest_care", "park_guest_care", value, config),
        _event("operator_signal", "staff_note", observed, "operator_note", "park_command", {"note": f"{open_cases} open guest-care cases; complaint rate {complaint_rate}%."}, config),
        _event("operator_signal", "incident_report", observed, "incident", "guest_care_pressure", {"open_cases": open_cases, "top_drivers": top_drivers}, config),
    ]


def ingest_live_staffing_feed(park_state: dict[str, Any] | None) -> dict[str, Any]:
    return _ingest("live_staffing_feed_load", staffing_feed_config(), build_staffing_live_feed_events(park_state))


def ingest_live_food_ops_feed(park_state: dict[str, Any] | None) -> dict[str, Any]:
    return _ingest("live_food_ops_feed_load", food_ops_feed_config(), build_food_ops_live_feed_events(park_state))


def ingest_live_operator_signal_feed(park_state: dict[str, Any] | None) -> dict[str, Any]:
    return _ingest("live_operator_signal_feed_load", operator_signal_feed_config(), build_operator_signal_live_feed_events(park_state))


def _food_location(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id") or row.get("name") or "unknown"),
        "name": row.get("name") or row.get("id") or "Unknown location",
        "mobile_order_backlog": _safe_int(row.get("mobileOrderBacklog")),
        "pickup_eta_minutes": _safe_int(row.get("pickupEtaMinutes")),
        "low_inventory_items": row.get("lowInventoryItems", []) if isinstance(row.get("lowInventoryItems"), list) else [],
        "available_items": row.get("availableItems", []) if isinstance(row.get("availableItems"), list) else [],
    }


def _event(source: str, signal_type: str, observed_at: str, entity_type: str, entity_id: str, value: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": source,
        "source_event_id": f"{source}-{signal_type}:{entity_id}:{observed_at}",
        "observed_at": observed_at,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "signal_type": signal_type,
        "value": value,
        "confidence": 0.88,
        "raw_payload_ref": config["source_url"],
        "raw": {"provider": config["provider"], "source": config["source"]},
    }


def _ingest(mode: str, config: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    ingested = [ingest_live_feed_event(event) for event in events]
    review_cases = [item.get("review_case") for item in ingested if item.get("review_case")]
    return {
        "status": "loaded" if ingested else "empty",
        "mode": mode,
        "loaded_at": _now_iso(),
        "provider": config["provider"],
        "event_count": len(ingested),
        "review_case_count": len(review_cases),
        "events": [item.get("event") for item in ingested],
        "review_cases": review_cases,
        "fetch": {"status": "fetched" if ingested else "empty", "fetched_at": _now_iso(), "config": config},
        "boundary": config["boundary"],
    }
