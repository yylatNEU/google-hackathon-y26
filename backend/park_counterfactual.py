from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _clamp(value: float, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, round(value)))


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _safe_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _top_by(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    if not rows:
        return {}
    return max(rows, key=lambda item: _safe_int(item.get(key), 0))


def _risk_label(value: int) -> str:
    if value >= 85:
        return "critical"
    if value >= 68:
        return "warning"
    return "watch"


def _top_anomaly(audit: dict[str, Any]) -> dict[str, Any]:
    anomalies = audit.get("anomalies", []) if isinstance(audit.get("anomalies"), list) else []
    if not anomalies:
        return {}
    weight = {"critical": 3, "warning": 2, "watch": 1}
    return max(
        anomalies,
        key=lambda item: (
            weight.get(str(item.get("severity")), 0),
            100 - _safe_int(item.get("leadTimeMinutes"), 99),
        ),
    )


def _action_name(domain: str) -> str:
    if domain == "ride_reliability":
        return "pause intake + capacity-aware reroute"
    if domain == "staff_schedule":
        return "stagger break + redeploy certified floater"
    if domain == "food_inventory":
        return "suppress constrained items + redirect orders"
    if domain == "incident_readiness":
        return "protect shelter HVAC + clear access lanes"
    return "split guest flow + worker task"


def _queue_for_ride(state: dict[str, Any], ride_id: str) -> dict[str, Any]:
    physical = state.get("physicalMap", {}) if isinstance(state.get("physicalMap"), dict) else {}
    queues = physical.get("queues", []) if isinstance(physical.get("queues"), list) else []
    if ride_id:
        for queue in queues:
            if queue.get("rideId") == ride_id:
                return queue
    if queues:
        return max(
            queues,
            key=lambda item: (
                60 if item.get("spillbackRisk") == "critical" else 25 if item.get("spillbackRisk") == "watch" else 0,
                _safe_int(item.get("waitMins"), 0),
                _safe_int(item.get("guests"), 0),
            ),
        )
    return {}


def _time_to_threshold(start: int, per_minute: float, threshold: int) -> int | None:
    if start >= threshold:
        return 0
    if per_minute <= 0:
        return None
    return max(1, round((threshold - start) / per_minute))


def _build_spillback_forecast(
    state: dict[str, Any],
    queue: dict[str, Any],
    current_density: int,
    current_path: int,
    current_wait: int,
    critical_count: int,
    mitigation: int,
) -> dict[str, Any]:
    queue_points = queue.get("points", []) if isinstance(queue.get("points"), list) else []
    queue_guests = _safe_int(queue.get("guests"), 0)
    queue_wait = _safe_int(queue.get("waitMins"), current_wait)
    switchback_capacity = max(180, len(queue_points) * 95)
    walkway_capacity = switchback_capacity + 130
    service_lane_capacity = switchback_capacity + 245
    current_overflow = max(0, queue_guests - switchback_capacity)
    no_action_growth = max(5.0, queue_wait / 5 + current_density / 18 + current_path / 25 + critical_count * 3)
    with_audit_growth = max(-18.0, no_action_growth * 0.28 - mitigation * 0.7)

    horizons = []
    for minutes in (5, 10, 15, 30):
        without_guests = round(queue_guests + no_action_growth * minutes)
        with_guests = max(0, round(queue_guests + with_audit_growth * minutes))
        without_overflow = max(0, without_guests - switchback_capacity)
        with_overflow = max(0, with_guests - switchback_capacity)
        horizons.append(
            {
                "minutes": minutes,
                "withoutAudit": {
                    "queueGuests": without_guests,
                    "overflowGuests": without_overflow,
                    "overflowMeters": round(without_overflow * 0.42),
                    "walkwayBlocked": without_guests >= walkway_capacity,
                    "serviceLaneBlocked": without_guests >= service_lane_capacity,
                    "spillbackRiskPct": _clamp((without_guests / max(1, service_lane_capacity)) * 100),
                },
                "withAudit": {
                    "queueGuests": with_guests,
                    "overflowGuests": with_overflow,
                    "overflowMeters": round(with_overflow * 0.42),
                    "walkwayBlocked": with_guests >= walkway_capacity,
                    "serviceLaneBlocked": with_guests >= service_lane_capacity,
                    "spillbackRiskPct": _clamp((with_guests / max(1, service_lane_capacity)) * 100),
                },
                "delta": {
                    "guestsKeptInside": max(0, without_guests - with_guests),
                    "overflowMetersAvoided": max(0, round((without_overflow - with_overflow) * 0.42)),
                    "spillbackRiskReducedPct": max(
                        0,
                        _clamp((without_guests / max(1, service_lane_capacity)) * 100)
                        - _clamp((with_guests / max(1, service_lane_capacity)) * 100),
                    ),
                },
            }
        )

    time_to_walkway = _time_to_threshold(queue_guests, no_action_growth, walkway_capacity)
    time_to_service = _time_to_threshold(queue_guests, no_action_growth, service_lane_capacity)
    audit_time_to_walkway = _time_to_threshold(queue_guests, with_audit_growth, walkway_capacity)
    audit_time_to_service = _time_to_threshold(queue_guests, with_audit_growth, service_lane_capacity)
    selected = horizons[2]
    segments = [
        {
            "id": "switchback",
            "label": "Switchback",
            "capacityGuests": switchback_capacity,
            "statusWithoutAudit": "overflow" if selected["withoutAudit"]["overflowGuests"] else "contained",
            "statusWithAudit": "overflow" if selected["withAudit"]["overflowGuests"] else "contained",
        },
        {
            "id": "walkway",
            "label": "Main walkway",
            "capacityGuests": walkway_capacity,
            "statusWithoutAudit": "blocked" if selected["withoutAudit"]["walkwayBlocked"] else "watch",
            "statusWithAudit": "blocked" if selected["withAudit"]["walkwayBlocked"] else "clear",
        },
        {
            "id": "service_lane",
            "label": "Service lane",
            "capacityGuests": service_lane_capacity,
            "statusWithoutAudit": "blocked" if selected["withoutAudit"]["serviceLaneBlocked"] else "watch",
            "statusWithAudit": "blocked" if selected["withAudit"]["serviceLaneBlocked"] else "clear",
        },
    ]
    return {
        "queueId": queue.get("id", "unknownQueue"),
        "queueName": queue.get("name", "Selected queue"),
        "rideId": queue.get("rideId", ""),
        "currentGuests": queue_guests,
        "currentWaitMins": queue_wait,
        "shadePct": _safe_int(queue.get("shadePct"), 0),
        "currentSpillbackRisk": queue.get("spillbackRisk", "watch"),
        "geometry": {
            "points": queue_points,
            "switchbackCapacityGuests": switchback_capacity,
            "walkwayCapacityGuests": walkway_capacity,
            "serviceLaneCapacityGuests": service_lane_capacity,
            "metersPerOverflowGuest": 0.42,
            "currentOverflowGuests": current_overflow,
            "currentOverflowMeters": round(current_overflow * 0.42),
        },
        "thresholds": {
            "withoutAuditWalkwayBlockedInMinutes": time_to_walkway,
            "withoutAuditServiceLaneBlockedInMinutes": time_to_service,
            "withAuditWalkwayBlockedInMinutes": audit_time_to_walkway,
            "withAuditServiceLaneBlockedInMinutes": audit_time_to_service,
        },
        "segments": segments,
        "horizons": horizons,
        "summary": (
            f"{queue.get('name', 'Selected queue')} is {current_overflow} guests beyond switchback capacity now. "
            f"Without action, walkway blockage is projected in "
            f"{time_to_walkway if time_to_walkway is not None else 'no'} minutes and service-lane blockage in "
            f"{time_to_service if time_to_service is not None else 'no'} minutes."
        ),
    }


def _build_action_execution_model(
    domain: str,
    queue: dict[str, Any],
    current_queue: int,
    current_wait: int,
    current_density: int,
    current_path: int,
    storm_risk: int,
    heat_index: int,
    food_backlog: int,
) -> dict[str, Any]:
    queue_shade = _safe_int(queue.get("shadePct"), 35)
    urgency = max(current_density, current_path, min(100, current_wait + 34))
    weather_friction = (storm_risk >= 65) * 8 + (heat_index >= 95) * 5 + max(0, 45 - queue_shade) * 0.12
    destination_friction = max(0, food_backlog - 40) * 0.05 + max(0, current_path - 78) * 0.16
    base_take_rate = 0.2 + min(0.26, max(0, current_wait - 20) * 0.006) + min(0.12, max(0, urgency - 72) * 0.003)
    if domain == "ride_reliability":
        base_take_rate += 0.08
    elif domain == "food_inventory":
        base_take_rate -= 0.03
    elif domain == "incident_readiness":
        base_take_rate += 0.03
    final_take_rate = _safe_float(base_take_rate - weather_friction * 0.002 - destination_friction * 0.0015, 0.34)
    final_take_rate = max(0.18, min(0.58, final_take_rate))
    worker_delay = 6 if domain in {"ride_reliability", "incident_readiness"} else 8 if domain == "staff_schedule" else 5
    signage_delay = 2
    app_delay = 1

    stages = [
        {
            "minute": 0,
            "stage": "decision_locked",
            "channel": "agent",
            "label": "Policy-checked action selected",
            "cumulativeTakeRatePct": 0,
            "movedGuests": 0,
            "effectivenessPct": 0,
            "friction": "approval and payload fan-out",
        },
        {
            "minute": app_delay,
            "stage": "guest_app_sent",
            "channel": "guest_app",
            "label": "Targeted guest guidance reaches affected queue",
            "cumulativeTakeRatePct": round(final_take_rate * 100 * 0.18),
            "movedGuests": round(current_queue * final_take_rate * 0.18),
            "effectivenessPct": 18,
            "friction": "guests read, discuss, and orient before moving",
        },
        {
            "minute": signage_delay + 1,
            "stage": "signage_visible",
            "channel": "digital_signage",
            "label": "Signs and map prompts reinforce the alternate route",
            "cumulativeTakeRatePct": round(final_take_rate * 100 * 0.42),
            "movedGuests": round(current_queue * final_take_rate * 0.42),
            "effectivenessPct": 42,
            "friction": "groups near the front hesitate because ride status may change",
        },
        {
            "minute": worker_delay,
            "stage": "worker_path_opened",
            "channel": "worker_app",
            "label": "Crowd lead opens the alternate path and protects merge points",
            "cumulativeTakeRatePct": round(final_take_rate * 100 * 0.68),
            "movedGuests": round(current_queue * final_take_rate * 0.68),
            "effectivenessPct": 68,
            "friction": "staff travel time and guest flow at the first merge",
        },
        {
            "minute": 10,
            "stage": "destination_absorbing",
            "channel": "destination_capacity",
            "label": "Destination rides, food, and indoor zones absorb redirected demand",
            "cumulativeTakeRatePct": round(final_take_rate * 100 * 0.86),
            "movedGuests": round(current_queue * final_take_rate * 0.86),
            "effectivenessPct": 86,
            "friction": "secondary queue and food backlog determine final capacity fit",
        },
        {
            "minute": 15,
            "stage": "stabilized_flow",
            "channel": "digital_twin",
            "label": "Flow stabilizes enough to verify spillback avoidance",
            "cumulativeTakeRatePct": round(final_take_rate * 100),
            "movedGuests": round(current_queue * final_take_rate),
            "effectivenessPct": 100,
            "friction": "late movers and families with fixed ride preference remain",
        },
    ]
    return {
        "mode": "delayed_action_guest_response_model",
        "finalTakeRatePct": round(final_take_rate * 100),
        "workerDelayMinutes": worker_delay,
        "guestAppDelayMinutes": app_delay,
        "signageDelayMinutes": signage_delay,
        "primaryFriction": "guest hesitation + path merge friction + destination capacity",
        "responseCurve": [
            {"minutes": 5, "effectivenessPct": 52, "takeRatePct": round(final_take_rate * 100 * 0.52)},
            {"minutes": 10, "effectivenessPct": 86, "takeRatePct": round(final_take_rate * 100 * 0.86)},
            {"minutes": 15, "effectivenessPct": 100, "takeRatePct": round(final_take_rate * 100)},
            {"minutes": 30, "effectivenessPct": 100, "takeRatePct": round(final_take_rate * 100)},
        ],
        "capacityChain": [
            {"link": "origin_queue", "effect": f"{round(current_queue * final_take_rate)} guests expected to leave pressure queue by 15m."},
            {"link": "walkway", "effect": f"Path friction is {round(destination_friction)} points from congestion and food backlog."},
            {"link": "workers", "effect": f"Physical merge control starts after {worker_delay}m."},
            {"link": "destination", "effect": "Indoor, food, and lower-wait ride capacity absorb demand gradually instead of instantly."},
        ],
        "timeline": stages,
    }


def _execution_effectiveness(action_execution: dict[str, Any], minutes: int) -> float:
    curve = action_execution.get("responseCurve", []) if isinstance(action_execution.get("responseCurve"), list) else []
    closest = next((item for item in curve if _safe_int(item.get("minutes")) == minutes), None)
    if closest:
        return _safe_int(closest.get("effectivenessPct"), 100) / 100
    if minutes < 5:
        return 0.25
    return 1.0


def build_counterfactual_forecast(state: dict[str, Any]) -> dict[str, Any]:
    flow = state.get("guestFlow", {}) if isinstance(state.get("guestFlow"), dict) else {}
    zones = flow.get("zones", []) if isinstance(flow.get("zones"), list) else []
    rides = flow.get("rides", []) if isinstance(flow.get("rides"), list) else []
    paths = flow.get("paths", []) if isinstance(flow.get("paths"), list) else []
    audit = state.get("operationsAudit", {}) if isinstance(state.get("operationsAudit"), dict) else {}
    weather = state.get("weather", {}) if isinstance(state.get("weather"), dict) else {}
    staffing = state.get("staffing", {}) if isinstance(state.get("staffing"), dict) else {}
    guest_care = state.get("guestCare", {}) if isinstance(state.get("guestCare"), dict) else {}
    food = state.get("foodInventory", {}) if isinstance(state.get("foodInventory"), dict) else {}

    busiest_zone = _top_by(zones, "density")
    slowest_ride = _top_by(rides, "waitMins")
    busiest_path = _top_by(paths, "congestionLevel")
    top_anomaly = _top_anomaly(audit)
    domain = str(top_anomaly.get("domain") or "crowd_flow")
    critical_count = _safe_int((audit.get("summary", {}) or {}).get("criticalAnomalies"), 0)
    schedule_risk = _safe_int((audit.get("summary", {}) or {}).get("scheduleRiskPct"), 70)
    lead_time = max(1, _safe_int((audit.get("summary", {}) or {}).get("earliestReactionMinutes"), _safe_int(top_anomaly.get("leadTimeMinutes"), 8)))
    current_density = _safe_int(busiest_zone.get("density"), 72)
    current_path = _safe_int(busiest_path.get("congestionLevel"), 70)
    current_wait = _safe_int(slowest_ride.get("waitMins"), 28)
    current_queue = _safe_int(slowest_ride.get("queueGuests"), 240)
    storm_risk = _safe_int(weather.get("stormRisk"), 35)
    heat_index = _safe_int(weather.get("heatIndexF"), 86)
    open_callouts = _safe_int(staffing.get("openCallouts"), 0)
    open_cases = _safe_int(guest_care.get("openCases"), 18)
    complaint_rate = _safe_int(guest_care.get("complaintRatePct"), 11)
    food_locations = food.get("locations", []) if isinstance(food.get("locations"), list) else []
    food_backlog = max([_safe_int(item.get("mobileOrderBacklog"), 0) for item in food_locations] or [0])

    pressure = max(current_density, current_path, current_wait + 30, schedule_risk)
    mitigation = 18
    if domain == "staff_schedule":
        mitigation = 24
    elif domain == "food_inventory":
        mitigation = 20
    elif domain == "ride_reliability":
        mitigation = 22
    elif domain == "incident_readiness":
        mitigation = 17
    selected_queue = _queue_for_ride(state, str(slowest_ride.get("id", "")))
    action_execution = _build_action_execution_model(
        domain,
        selected_queue,
        current_queue,
        current_wait,
        current_density,
        current_path,
        storm_risk,
        heat_index,
        food_backlog,
    )
    spillback = _build_spillback_forecast(
        state,
        selected_queue,
        current_density,
        current_path,
        current_wait,
        critical_count,
        mitigation,
    )

    horizons = []
    for minutes in (5, 10, 15, 30):
        action_effect = _execution_effectiveness(action_execution, minutes)
        no_action_density = _clamp(current_density + minutes * 0.48 + critical_count * 2.4 + (current_wait >= 45) * 4, 0, 118)
        with_audit_density = _clamp(current_density + minutes * 0.14 + critical_count - mitigation * action_effect * (minutes / 30), 0, 118)
        no_action_path = _clamp(current_path + minutes * 0.62 + (storm_risk >= 70) * 5, 0, 118)
        with_audit_path = _clamp(current_path + minutes * 0.18 - (mitigation - 4) * action_effect * (minutes / 30), 0, 118)
        no_action_complaints = round(open_cases + complaint_rate * (minutes / 12) + max(0, no_action_density - 80) * 0.7 + food_backlog / 24)
        with_audit_complaints = round(open_cases + complaint_rate * (minutes / 24) + max(0, with_audit_density - 80) * 0.25 + food_backlog / 55 + (1 - action_effect) * 5)
        no_action_staff = _clamp(schedule_risk + minutes * 0.38 + open_callouts * 0.3, 0, 100)
        with_audit_staff = _clamp(schedule_risk - 18 * action_effect + minutes * 0.12 + open_callouts * 0.12, 0, 100)
        no_action_heat = _clamp((heat_index - 75) * 1.8 + minutes * 0.35 + max(0, current_density - 70) * 0.35, 0, 100)
        with_audit_heat = _clamp(no_action_heat - (12 + (domain == "incident_readiness") * 10) * action_effect, 0, 100)
        no_action_guest_minutes = round(current_queue * max(1, current_wait + minutes * 0.7) / 10 + max(0, no_action_path - 70) * 18)
        with_audit_guest_minutes = round(current_queue * max(1, current_wait + minutes * 0.22) / (11.5 + 1.5 * action_effect) + max(0, with_audit_path - 70) * 7)
        horizons.append(
            {
                "minutes": minutes,
                "withoutAudit": {
                    "densityPct": no_action_density,
                    "serviceLaneRiskPct": no_action_path,
                    "staffConflictRiskPct": no_action_staff,
                    "guestComplaintCases": no_action_complaints,
                    "heatMedicalRiskPct": no_action_heat,
                    "guestMinutesLost": no_action_guest_minutes,
                    "risk": _risk_label(max(no_action_density, no_action_path, no_action_staff, no_action_heat)),
                },
                "withAudit": {
                    "densityPct": with_audit_density,
                    "serviceLaneRiskPct": with_audit_path,
                    "staffConflictRiskPct": with_audit_staff,
                    "guestComplaintCases": with_audit_complaints,
                    "heatMedicalRiskPct": with_audit_heat,
                    "guestMinutesLost": with_audit_guest_minutes,
                    "risk": _risk_label(max(with_audit_density, with_audit_path, with_audit_staff, with_audit_heat)),
                    "actionEffectivenessPct": round(action_effect * 100),
                },
                "delta": {
                    "densityPct": no_action_density - with_audit_density,
                    "serviceLaneRiskPct": no_action_path - with_audit_path,
                    "staffConflictRiskPct": no_action_staff - with_audit_staff,
                    "guestComplaintCases": no_action_complaints - with_audit_complaints,
                    "heatMedicalRiskPct": no_action_heat - with_audit_heat,
                    "guestMinutesSaved": no_action_guest_minutes - with_audit_guest_minutes,
                },
            }
        )

    main = horizons[2]
    without = main["withoutAudit"]
    with_audit = main["withAudit"]
    delta = main["delta"]
    metrics = [
        {
            "id": "density",
            "label": f"{busiest_zone.get('name', 'Busiest zone')} density in 15m",
            "unit": "%",
            "withoutAudit": without["densityPct"],
            "withAudit": with_audit["densityPct"],
            "improvement": delta["densityPct"],
            "tone": _risk_label(without["densityPct"]),
        },
        {
            "id": "service_lane",
            "label": "Service lane blockage risk",
            "unit": "%",
            "withoutAudit": without["serviceLaneRiskPct"],
            "withAudit": with_audit["serviceLaneRiskPct"],
            "improvement": delta["serviceLaneRiskPct"],
            "tone": _risk_label(without["serviceLaneRiskPct"]),
        },
        {
            "id": "staff_conflict",
            "label": "Staff break conflict risk",
            "unit": "%",
            "withoutAudit": without["staffConflictRiskPct"],
            "withAudit": with_audit["staffConflictRiskPct"],
            "improvement": delta["staffConflictRiskPct"],
            "tone": _risk_label(without["staffConflictRiskPct"]),
        },
        {
            "id": "complaints",
            "label": "Expected guest-care cases",
            "unit": "cases",
            "withoutAudit": without["guestComplaintCases"],
            "withAudit": with_audit["guestComplaintCases"],
            "improvement": delta["guestComplaintCases"],
            "tone": _risk_label(min(100, without["guestComplaintCases"] * 2)),
        },
        {
            "id": "guest_minutes",
            "label": "Guest-minutes lost",
            "unit": "min",
            "withoutAudit": without["guestMinutesLost"],
            "withAudit": with_audit["guestMinutesLost"],
            "improvement": delta["guestMinutesSaved"],
            "tone": _risk_label(min(100, round(without["guestMinutesLost"] / 80))),
        },
    ]

    chain = [
        {
            "id": "signal",
            "label": "Weak signal",
            "withoutAudit": "First symptom remains isolated in logs.",
            "withAudit": f"{top_anomaly.get('owner', 'Audit agent')} correlates logs and schedule.",
            "evidence": top_anomaly.get("evidence", ["Audit signal exceeded threshold."])[:2],
        },
        {
            "id": "propagation",
            "label": "Risk propagation",
            "withoutAudit": f"{slowest_ride.get('name', 'Top ride')} wait pushes guests into {busiest_path.get('toName', 'nearby path')}.",
            "withAudit": f"{_action_name(domain).title()} reduces pressure before the path locks.",
            "evidence": [
                f"{slowest_ride.get('name', 'Top ride')} wait {current_wait}m, queue {current_queue}.",
                f"{busiest_path.get('fromName', 'Path')} to {busiest_path.get('toName', 'destination')} congestion {current_path}%.",
            ],
        },
        {
            "id": "operational_effect",
            "label": "Operational effect",
            "withoutAudit": "Density, schedule conflict, complaints, and heat risk compound in the same window.",
            "withAudit": f"15-minute forecast saves {delta['guestMinutesSaved']} guest-minutes and reduces complaints by {delta['guestComplaintCases']} cases.",
            "evidence": [
                f"{delta['densityPct']} density points reduced in the busiest zone.",
                f"{delta['staffConflictRiskPct']} staff-conflict risk points reduced.",
            ],
        },
    ]

    return {
        "forecastId": f"CF-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
        "generatedAt": _utc_now(),
        "mode": "counterfactual_audit_intervention",
        "headline": (
            f"Audit lead time is {lead_time}m; acting now prevents the 15-minute forecast from reaching "
            f"{without['risk']} risk."
        ),
        "leadTimeMinutes": lead_time,
        "horizonMinutes": 15,
        "focus": {
            "zoneId": busiest_zone.get("id", ""),
            "zoneName": busiest_zone.get("name", "Busiest zone"),
            "rideId": slowest_ride.get("id", ""),
            "rideName": slowest_ride.get("name", "Top ride"),
            "path": f"{busiest_path.get('fromName', 'Path')} -> {busiest_path.get('toName', 'destination')}",
            "queueId": selected_queue.get("id", ""),
            "queueName": selected_queue.get("name", "Selected queue"),
            "topAnomalyId": top_anomaly.get("id", ""),
            "topAnomalyTitle": top_anomaly.get("title", "No anomaly selected"),
            "response": _action_name(domain),
        },
        "metrics": metrics,
        "horizons": horizons,
        "spillback": spillback,
        "actionExecution": action_execution,
        "causalChain": chain,
        "impact": {
            "densityPointsAvoided": delta["densityPct"],
            "serviceLaneRiskReducedPct": delta["serviceLaneRiskPct"],
            "staffConflictRiskReducedPct": delta["staffConflictRiskPct"],
            "guestCareCasesAvoided": delta["guestComplaintCases"],
            "guestMinutesSaved": delta["guestMinutesSaved"],
            "summary": (
                f"Compared with waiting, the audit intervention saves {delta['guestMinutesSaved']} guest-minutes, "
                f"avoids {delta['guestComplaintCases']} expected guest-care cases, and lowers service-lane risk "
                f"by {delta['serviceLaneRiskPct']} points in the 15-minute window."
            ),
        },
        "assumptions": [
            "Forecast uses deterministic micro-simulation from current queues, path congestion, staffing risk, food backlog, weather, audit findings, and delayed action execution.",
            "With-audit path assumes guest response ramps through app delivery, signage, worker merge control, and destination absorption rather than taking effect instantly.",
            "Values are directional operational estimates for demo decision support, not a safety certification.",
        ],
    }
