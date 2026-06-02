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


def ride_ops_feed_config() -> dict[str, Any]:
    return {
        "provider": os.getenv("PARKPULSE_RIDE_OPS_FEED_PROVIDER", "parkpulse_runtime"),
        "source": os.getenv("PARKPULSE_RIDE_OPS_FEED_SOURCE", "park_state.guestFlow.rides"),
        "source_url": os.getenv("PARKPULSE_RIDE_OPS_FEED_URL", "runtime://park_state/guestFlow/rides"),
        "timeout_seconds": _safe_int(os.getenv("PARKPULSE_RIDE_OPS_FEED_TIMEOUT_SECONDS"), 5),
        "boundary": "Ride operations facts can update state and policy gates, but reopening, maintenance clearance, and equipment control still require ParkPulse safety gates and human authority.",
    }


def _ride_rows_from_state(park_state: dict[str, Any] | None) -> list[dict[str, Any]]:
    state = park_state if isinstance(park_state, dict) else {}
    flow = state.get("guestFlow", {}) if isinstance(state.get("guestFlow"), dict) else {}
    rides = flow.get("rides", []) if isinstance(flow.get("rides"), list) else []
    return [ride for ride in rides if isinstance(ride, dict)]


def _normalize_ride(ride: dict[str, Any]) -> dict[str, Any]:
    status = str(ride.get("status") or "unknown").lower()
    downtime_risk = _safe_int(ride.get("downtimeRisk"))
    return {
        "id": str(ride.get("id") or ride.get("rideId") or ride.get("name") or "unknown"),
        "name": ride.get("name") or ride.get("rideName") or ride.get("id") or "Unknown ride",
        "zone": ride.get("zoneName") or ride.get("zone") or ride.get("area"),
        "status": status,
        "queue_guests": _safe_int(ride.get("queueGuests")),
        "wait_mins": _safe_int(ride.get("waitMins")),
        "downtime_risk_pct": downtime_risk,
        "capacity_per_hour": _safe_int(ride.get("capacityPerHour")),
        "effective_throughput": _safe_int(ride.get("effectiveThroughput")),
        "staff_available": _safe_int(ride.get("staffAvailable")),
        "staff_required": _safe_int(ride.get("staffRequired")),
        "maintenance_clearance": bool(ride.get("maintenanceClearance") or ride.get("maintenanceCleared")),
        "control_lockout": status in {"down", "closed", "maintenance", "stopped"} or downtime_risk >= 80,
    }


def build_ride_ops_live_feed_events(park_state: dict[str, Any] | None, observed_at: str | None = None) -> list[dict[str, Any]]:
    config = ride_ops_feed_config()
    observed = observed_at or _now_iso()
    rides = [_normalize_ride(ride) for ride in _ride_rows_from_state(park_state)]
    if not rides:
        return []
    top_wait = max(rides, key=lambda ride: _safe_int(ride.get("wait_mins")), default={})
    top_downtime = max(rides, key=lambda ride: _safe_int(ride.get("downtime_risk_pct")), default={})
    capacity_pressure = max(
        0,
        min(
            100,
            round(
                sum(max(0, _safe_int(ride.get("queue_guests")) - _safe_int(ride.get("effective_throughput"))) for ride in rides)
                / max(1, sum(max(1, _safe_int(ride.get("capacity_per_hour"))) for ride in rides))
                * 100
            ),
        ),
    )
    down_count = sum(1 for ride in rides if ride.get("control_lockout"))
    confidence = 0.9 if rides else 0.35
    base = {
        "provider": config["provider"],
        "ride_count": len(rides),
        "down_ride_count": down_count,
        "capacity_pressure_pct": capacity_pressure,
        "rides": rides,
    }
    return [
        {
            "source": "ride_ops",
            "source_event_id": f"ride-ops-roster:{observed}",
            "observed_at": observed,
            "entity_type": "park",
            "entity_id": "ride_roster",
            "signal_type": "ride_status",
            "value": base,
            "confidence": confidence,
            "raw_payload_ref": config["source_url"],
            "raw": {"provider": config["provider"], "source": config["source"]},
        },
        {
            "source": "ride_ops",
            "source_event_id": f"ride-ops-wait:{top_wait.get('id')}:{observed}",
            "observed_at": observed,
            "entity_type": "ride",
            "entity_id": top_wait.get("id") or "unknown",
            "signal_type": "wait_time",
            "value": top_wait,
            "confidence": confidence,
            "raw_payload_ref": config["source_url"],
            "raw": {"provider": config["provider"]},
        },
        {
            "source": "ride_ops",
            "source_event_id": f"ride-ops-downtime:{top_downtime.get('id')}:{observed}",
            "observed_at": observed,
            "entity_type": "ride",
            "entity_id": top_downtime.get("id") or "unknown",
            "signal_type": "downtime",
            "value": top_downtime,
            "confidence": confidence,
            "raw_payload_ref": config["source_url"],
            "raw": {"provider": config["provider"]},
        },
        {
            "source": "ride_ops",
            "source_event_id": f"ride-ops-capacity:{observed}",
            "observed_at": observed,
            "entity_type": "park",
            "entity_id": "ride_capacity",
            "signal_type": "capacity",
            "value": {"capacity_pressure_pct": capacity_pressure, "ride_count": len(rides), "down_ride_count": down_count},
            "confidence": confidence,
            "raw_payload_ref": config["source_url"],
            "raw": {"provider": config["provider"]},
        },
    ]


def ingest_live_ride_ops_feed(park_state: dict[str, Any] | None) -> dict[str, Any]:
    events = build_ride_ops_live_feed_events(park_state)
    ingested = [ingest_live_feed_event(event) for event in events]
    review_cases = [item.get("review_case") for item in ingested if item.get("review_case")]
    return {
        "status": "loaded" if ingested else "empty",
        "mode": "live_ride_ops_feed_load",
        "loaded_at": _now_iso(),
        "provider": ride_ops_feed_config()["provider"],
        "event_count": len(ingested),
        "review_case_count": len(review_cases),
        "events": [item.get("event") for item in ingested],
        "review_cases": review_cases,
        "fetch": {"status": "fetched" if ingested else "empty", "fetched_at": _now_iso(), "config": ride_ops_feed_config()},
        "boundary": ride_ops_feed_config()["boundary"],
    }
