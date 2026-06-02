from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from live_feedback_loop import ingest_live_feed_event


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


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


def guest_flow_feed_config() -> dict[str, Any]:
    return {
        "provider": os.getenv("PARKPULSE_GUEST_FLOW_FEED_PROVIDER", "parkpulse_runtime"),
        "source": os.getenv("PARKPULSE_GUEST_FLOW_FEED_SOURCE", "park_state.guestFlow.zones_paths"),
        "source_url": os.getenv("PARKPULSE_GUEST_FLOW_FEED_URL", "runtime://park_state/guestFlow"),
        "timeout_seconds": _safe_int(os.getenv("PARKPULSE_GUEST_FLOW_FEED_TIMEOUT_SECONDS"), 5),
        "boundary": "Guest flow facts can guide routing and staffing recommendations, but crowd safety actions still require policy gates, accessibility checks, and human review where applicable.",
    }


def _flow_from_state(park_state: dict[str, Any] | None) -> dict[str, Any]:
    state = park_state if isinstance(park_state, dict) else {}
    return state.get("guestFlow", {}) if isinstance(state.get("guestFlow"), dict) else {}


def _normalize_zone(zone: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(zone.get("id") or zone.get("zoneId") or zone.get("name") or "unknown"),
        "name": zone.get("name") or zone.get("id") or "Unknown zone",
        "area": zone.get("area"),
        "process_type": zone.get("processType"),
        "flow_type": zone.get("flowType"),
        "capacity": _safe_int(zone.get("capacity")),
        "current_guests": _safe_int(zone.get("currentGuests")),
        "density_pct": _safe_int(zone.get("density")),
        "density_guests_per_sqm": _safe_float(zone.get("densityGuestsPerSqM")),
        "comfort_score": _safe_int(zone.get("comfortScore")),
        "dominant_intent": zone.get("dominantIntent"),
        "wait_mins": _safe_int(zone.get("waitMins")),
    }


def _normalize_path(path: dict[str, Any]) -> dict[str, Any]:
    return {
        "from": path.get("from"),
        "to": path.get("to"),
        "from_name": path.get("fromName"),
        "to_name": path.get("toName"),
        "walk_minutes": _safe_int(path.get("walkMinutes")),
        "capacity": _safe_int(path.get("capacity")),
        "current_guests": _safe_int(path.get("currentGuests")),
        "congestion_level_pct": _safe_int(path.get("congestionLevel")),
        "width_utilization_pct": _safe_int(path.get("widthUtilizationPct")),
        "status": str(path.get("status") or "open").lower(),
        "forward_transfers": _safe_int(path.get("forwardTransfers")),
        "reverse_transfers": _safe_int(path.get("reverseTransfers")),
    }


def build_guest_flow_live_feed_events(park_state: dict[str, Any] | None, observed_at: str | None = None) -> list[dict[str, Any]]:
    config = guest_flow_feed_config()
    observed = observed_at or _now_iso()
    flow = _flow_from_state(park_state)
    zones = [_normalize_zone(zone) for zone in flow.get("zones", []) if isinstance(zone, dict)] if isinstance(flow.get("zones"), list) else []
    paths = [_normalize_path(path) for path in flow.get("paths", []) if isinstance(path, dict)] if isinstance(flow.get("paths"), list) else []
    if not zones and not paths:
        return []
    top_zone = max(zones, key=lambda zone: _safe_int(zone.get("density_pct")), default={})
    top_path = max(paths, key=lambda path: _safe_int(path.get("congestion_level_pct")), default={})
    congested_path_count = sum(1 for path in paths if path.get("status") in {"congested", "blocked"} or _safe_int(path.get("congestion_level_pct")) >= 75)
    routing_take_rate_pct = max(
        0,
        min(
            100,
            round(
                100
                - _safe_float(flow.get("avgSatisfaction"), 0) * 0.25
                + min(40, len(flow.get("interventions", []) if isinstance(flow.get("interventions"), list) else []) * 6)
            ),
        ),
    )
    confidence = 0.9 if zones else 0.72 if paths else 0.35
    base = {
        "provider": config["provider"],
        "represented_guests": _safe_int(flow.get("representedGuests")),
        "active_groups": _safe_int(flow.get("activeGroups")),
        "avg_satisfaction": _safe_float(flow.get("avgSatisfaction")),
        "zone_count": len(zones),
        "path_count": len(paths),
        "congested_path_count": congested_path_count,
        "routing_take_rate_pct": routing_take_rate_pct,
        "zones": zones,
        "paths": paths,
    }
    return [
        {
            "source": "guest_flow",
            "source_event_id": f"guest-flow-zone-density:{top_zone.get('id')}:{observed}",
            "observed_at": observed,
            "entity_type": "zone",
            "entity_id": top_zone.get("id") or "unknown",
            "signal_type": "zone_density",
            "value": {**base, "top_zone": top_zone},
            "confidence": confidence,
            "raw_payload_ref": config["source_url"],
            "raw": {"provider": config["provider"], "source": config["source"]},
        },
        {
            "source": "guest_flow",
            "source_event_id": f"guest-flow-path-congestion:{top_path.get('from')}:{top_path.get('to')}:{observed}",
            "observed_at": observed,
            "entity_type": "path",
            "entity_id": f"{top_path.get('from') or 'unknown'}->{top_path.get('to') or 'unknown'}",
            "signal_type": "path_congestion",
            "value": {"top_path": top_path, "paths": paths, "congested_path_count": congested_path_count},
            "confidence": confidence,
            "raw_payload_ref": config["source_url"],
            "raw": {"provider": config["provider"]},
        },
        {
            "source": "guest_flow",
            "source_event_id": f"guest-flow-routing-take-rate:{observed}",
            "observed_at": observed,
            "entity_type": "park",
            "entity_id": "guest_routing",
            "signal_type": "routing_take_rate",
            "value": {
                "routing_take_rate_pct": routing_take_rate_pct,
                "represented_guests": base["represented_guests"],
                "active_groups": base["active_groups"],
                "avg_satisfaction": base["avg_satisfaction"],
            },
            "confidence": confidence,
            "raw_payload_ref": config["source_url"],
            "raw": {"provider": config["provider"]},
        },
    ]


def ingest_live_guest_flow_feed(park_state: dict[str, Any] | None) -> dict[str, Any]:
    events = build_guest_flow_live_feed_events(park_state)
    ingested = [ingest_live_feed_event(event) for event in events]
    review_cases = [item.get("review_case") for item in ingested if item.get("review_case")]
    return {
        "status": "loaded" if ingested else "empty",
        "mode": "live_guest_flow_feed_load",
        "loaded_at": _now_iso(),
        "provider": guest_flow_feed_config()["provider"],
        "event_count": len(ingested),
        "review_case_count": len(review_cases),
        "events": [item.get("event") for item in ingested],
        "review_cases": review_cases,
        "fetch": {"status": "fetched" if ingested else "empty", "fetched_at": _now_iso(), "config": guest_flow_feed_config()},
        "boundary": guest_flow_feed_config()["boundary"],
    }
