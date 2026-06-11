from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from park_twin_engine import apply_stress_event, simulate_action_plan


MAX_DETAIL_ROWS = 1200
MAX_PENDING_ROWS = 300
RETENTION_HOURS = 72
RESOLUTION_HORIZONS = (5, 15, 30)

_pending: dict[str, dict[str, Any]] = {}
_resolved: deque[dict[str, Any]] = deque(maxlen=MAX_DETAIL_ROWS)
_seen_forecasts: set[str] = set()

SCENARIO_CALIBRATION_FIXTURES: list[dict[str, Any]] = [
    {
        "id": "ride_down_bounded_reroute",
        "scenario_key": "ride_down",
        "description": "A down headline ride should project meaningful queue relief, but must fail readiness if crowd density remains critical.",
        "stress_events": [{"kind": "ride_failure", "targetId": "dragonCoaster", "intensity": 86}],
        "action_plan": {
            "target": "ride",
            "action": "reroute",
            "label": "Calibration bounded ride reroute",
            "action_mix": {
                "guest_reroute": {
                    "enabled": True,
                    "expectedTakeRate": 0.42,
                    "durationMinutes": 20,
                    "target_mix": [
                        {"zoneId": "arcadeZone", "destination": "Arcade Zone", "share": 0.34, "currentWaitMins": 7},
                        {"zoneId": "indoorHub", "destination": "Theater B", "share": 0.24, "currentWaitMins": 18},
                        {"zoneId": "coveredPlaza", "destination": "Covered Plaza", "share": 0.14, "currentWaitMins": 12},
                    ],
                },
                "staffing": {"move_staff": [{"role": "crowd_control", "count": 2, "from": "Entrance Plaza", "to": "Coaster Plaza"}]},
                "controls": {"queue_gates": [{"zones": ["coasterPlaza"], "settings": {"holdMinutes": 20}}]},
            },
        },
        "expectations": [
            {"metric": "projected_impact.movedGuests", "min": 350},
            {"metric": "projected_impact.avgWaitDeltaMinutes", "max": 2},
            {"metric": "outcome.metrics.critical_density_excess", "max": 30},
            {"metric": "scorecard.overall", "min": 35, "max": 85},
        ],
    },
    {
        "id": "food_spike_menu_control",
        "scenario_key": "food_spike",
        "description": "Food demand controls should reduce or contain mobile-order backlog and avoid shifting guests into a worse ride bottleneck.",
        "stress_events": [{"kind": "food_spike", "targetId": "foodCourt1", "intensity": 78}],
        "action_plan": {
            "target": "food",
            "action": "suppress_item",
            "label": "Calibration food menu and routing control",
            "action_mix": {
                "food": {"suppressItems": ["chicken_tenders", "bottled_drinks"], "promoteItems": ["pizza_combo"]},
                "guest_reroute": {
                    "enabled": True,
                    "expectedTakeRate": 0.28,
                    "durationMinutes": 15,
                    "target_mix": [
                        {"zoneId": "arcadeZone", "destination": "Arcade Zone", "share": 0.28, "currentWaitMins": 7},
                        {"zoneId": "coveredPlaza", "destination": "Covered Plaza", "share": 0.16, "currentWaitMins": 12},
                    ],
                },
                "staffing": {"move_staff": [{"role": "food_runner", "count": 2, "from": "break_pool", "to": "Food Court 1"}]},
            },
        },
        "expectations": [
            {"metric": "outcome.metrics.food_backlog_delta", "max": 8},
            {"metric": "projected_impact.movedGuests", "min": 100},
            {"metric": "scorecard.safety", "min": 50},
            {"metric": "scorecard.overall", "min": 35, "max": 90},
        ],
    },
    {
        "id": "staff_shortage_redeploy",
        "scenario_key": "staff_shortage",
        "description": "A staff redeploy should improve comfort or wait pressure without pretending callouts disappeared.",
        "stress_events": [{"kind": "staff_callout", "targetId": "coasterPlaza", "intensity": 72}],
        "action_plan": {
            "target": "staff",
            "action": "redeploy",
            "label": "Calibration staff redeploy",
            "action_mix": {
                "staffing": {"move_staff": [{"role": "crowd_control", "count": 2, "from": "Entrance Plaza", "to": "Coaster Plaza"}]},
                "guest_reroute": {
                    "enabled": True,
                    "expectedTakeRate": 0.22,
                    "durationMinutes": 10,
                    "target_mix": [{"zoneId": "arcadeZone", "destination": "Arcade Zone", "share": 0.22, "currentWaitMins": 7}],
                },
            },
        },
        "expectations": [
            {"metric": "outcome.metrics.staff_callout_delta", "min": -2, "max": 2},
            {"metric": "projected_impact.guestSatisfactionDelta", "min": -4},
            {"metric": "scorecard.staff_burden", "min": 75},
            {"metric": "scorecard.overall", "min": 30, "max": 90},
        ],
    },
    {
        "id": "storm_response_comfort_protection",
        "scenario_key": "storm_response",
        "description": "Storm response should protect indoor comfort while exposing energy and secondary bottleneck tradeoffs.",
        "stress_events": [
            {"kind": "storm_risk", "targetId": "coveredPlaza", "intensity": 82},
            {"kind": "energy_spike", "targetId": "indoorHub", "intensity": 62},
        ],
        "action_plan": {
            "target": "energy",
            "action": "protect_hvac",
            "label": "Calibration storm comfort protection",
            "action_mix": {
                "facilities": {"hvac": {"protectShelterComfort": True, "indoorHubSetpointF": 72, "arcadeZoneSetpointF": 73}},
                "guest_reroute": {
                    "enabled": True,
                    "expectedTakeRate": 0.26,
                    "durationMinutes": 15,
                    "target_mix": [
                        {"zoneId": "arcadeZone", "destination": "Arcade Zone", "share": 0.22, "currentWaitMins": 7},
                        {"zoneId": "coveredPlaza", "destination": "Covered Plaza", "share": 0.18, "currentWaitMins": 12},
                    ],
                },
            },
        },
        "expectations": [
            {"metric": "projected_impact.guestSatisfactionDelta", "min": -6},
            {"metric": "outcome.metrics.grid_load_delta", "max": 10},
            {"metric": "scorecard.safety", "min": 50},
            {"metric": "scorecard.overall", "min": 30, "max": 90},
        ],
    },
]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


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


def _sim_index(state: dict[str, Any]) -> int:
    sim_time = state.get("simTime", {}) if isinstance(state.get("simTime"), dict) else {}
    day = _safe_int(sim_time.get("day"), 1)
    hour = _safe_int(sim_time.get("hour"), 0)
    minute = _safe_int(sim_time.get("minute"), 0)
    return day * 24 * 60 + hour * 60 + minute


def _rows(state: dict[str, Any], key: str) -> list[dict[str, Any]]:
    flow = state.get("guestFlow", {}) if isinstance(state.get("guestFlow"), dict) else {}
    rows = flow.get(key, [])
    return rows if isinstance(rows, list) else []


def _find(rows: list[dict[str, Any]], item_id: str | None) -> dict[str, Any]:
    if item_id:
        for item in rows:
            if str(item.get("id")) == str(item_id):
                return item
    return {}


def _top(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    return max(rows, key=lambda item: _safe_int(item.get(key)), default={})


def _food_backlog(state: dict[str, Any]) -> int:
    food = state.get("foodInventory", {}) if isinstance(state.get("foodInventory"), dict) else {}
    locations = food.get("locations", []) if isinstance(food.get("locations"), list) else []
    return max([_safe_int(item.get("mobileOrderBacklog")) for item in locations if isinstance(item, dict)] or [0])


def _queue_actual(state: dict[str, Any], forecast: dict[str, Any]) -> dict[str, int]:
    spillback = forecast.get("spillback", {}) if isinstance(forecast.get("spillback"), dict) else {}
    geometry = spillback.get("geometry", {}) if isinstance(spillback.get("geometry"), dict) else {}
    queue_id = str(spillback.get("queueId") or "")
    queues = (state.get("physicalMap", {}) if isinstance(state.get("physicalMap"), dict) else {}).get("queues", [])
    queue = _find(queues if isinstance(queues, list) else [], queue_id)
    guests = _safe_int(queue.get("guests"), _safe_int(spillback.get("currentGuests")))
    switchback_capacity = max(1, _safe_int(geometry.get("switchbackCapacityGuests"), 1))
    overflow_guests = max(0, guests - switchback_capacity)
    meters_per_guest = _safe_float(geometry.get("metersPerOverflowGuest"), 0.42)
    return {
        "queueGuests": guests,
        "overflowGuests": overflow_guests,
        "overflowMeters": round(overflow_guests * meters_per_guest),
    }


def _actual_metrics(state: dict[str, Any], forecast: dict[str, Any]) -> dict[str, Any]:
    focus = forecast.get("focus", {}) if isinstance(forecast.get("focus"), dict) else {}
    zone = _find(_rows(state, "zones"), str(focus.get("zoneId") or "")) or _top(_rows(state, "zones"), "density")
    ride = _find(_rows(state, "rides"), str(focus.get("rideId") or "")) or _top(_rows(state, "rides"), "waitMins")
    path = _top(_rows(state, "paths"), "congestionLevel")
    guest_care = state.get("guestCare", {}) if isinstance(state.get("guestCare"), dict) else {}
    queue = _queue_actual(state, forecast)
    return {
        "densityPct": _safe_int(zone.get("density")),
        "serviceLaneRiskPct": _safe_int(path.get("congestionLevel")),
        "guestComplaintCases": _safe_int(guest_care.get("openCases")),
        "rideWaitMins": _safe_int(ride.get("waitMins")),
        "queueGuests": queue["queueGuests"],
        "overflowMeters": queue["overflowMeters"],
        "foodBacklog": _food_backlog(state),
        "avgSatisfaction": _safe_int((state.get("guestFlow", {}) if isinstance(state.get("guestFlow"), dict) else {}).get("avgSatisfaction")),
    }


def _predicted_metrics(forecast: dict[str, Any], minutes: int, branch: str) -> dict[str, Any]:
    horizons = forecast.get("horizons", []) if isinstance(forecast.get("horizons"), list) else []
    horizon = next((item for item in horizons if _safe_int(item.get("minutes")) == minutes), horizons[0] if horizons else {})
    branch_metrics = horizon.get(branch, {}) if isinstance(horizon.get(branch), dict) else {}
    spillback = forecast.get("spillback", {}) if isinstance(forecast.get("spillback"), dict) else {}
    spillback_horizons = spillback.get("horizons", []) if isinstance(spillback.get("horizons"), list) else []
    spill_horizon = next((item for item in spillback_horizons if _safe_int(item.get("minutes")) == minutes), spillback_horizons[0] if spillback_horizons else {})
    spill_branch = spill_horizon.get(branch, {}) if isinstance(spill_horizon.get(branch), dict) else {}
    return {
        "densityPct": _safe_int(branch_metrics.get("densityPct")),
        "serviceLaneRiskPct": _safe_int(branch_metrics.get("serviceLaneRiskPct")),
        "guestComplaintCases": _safe_int(branch_metrics.get("guestComplaintCases")),
        "queueGuests": _safe_int(spill_branch.get("queueGuests")),
        "overflowMeters": _safe_int(spill_branch.get("overflowMeters")),
        "spillbackRiskPct": _safe_int(spill_branch.get("spillbackRiskPct")),
    }


def _error(predicted: dict[str, Any], actual: dict[str, Any]) -> dict[str, int]:
    keys = ("densityPct", "serviceLaneRiskPct", "guestComplaintCases", "queueGuests", "overflowMeters")
    return {key: abs(_safe_int(actual.get(key)) - _safe_int(predicted.get(key))) for key in keys}


def _accuracy(error: dict[str, int]) -> int:
    tolerances = {
        "densityPct": 24,
        "serviceLaneRiskPct": 28,
        "guestComplaintCases": 30,
        "queueGuests": 240,
        "overflowMeters": 120,
    }
    scores = [
        max(0.0, 100.0 - (float(error.get(key, 0)) / tolerance) * 100.0)
        for key, tolerance in tolerances.items()
    ]
    return round(sum(scores) / max(1, len(scores)))


def _confidence_label(score: int | None, resolved_count: int, pending_count: int) -> str:
    if resolved_count < 3:
        return "warming_up" if pending_count else "low"
    if score is None or score < 65:
        return "low"
    if score < 82:
        return "medium"
    return "high"


def _compact_forecast(state: dict[str, Any], forecast: dict[str, Any]) -> dict[str, Any]:
    focus = forecast.get("focus", {}) if isinstance(forecast.get("focus"), dict) else {}
    return {
        "forecastId": str(forecast.get("forecastId") or f"CF-{_utc_now()}"),
        "createdAt": str(forecast.get("generatedAt") or _utc_now()),
        "createdSimMinute": _sim_index(state),
        "target": {
            "zoneId": focus.get("zoneId", ""),
            "zoneName": focus.get("zoneName", ""),
            "rideId": focus.get("rideId", ""),
            "rideName": focus.get("rideName", ""),
            "queueId": focus.get("queueId", ""),
            "queueName": focus.get("queueName", ""),
        },
        "forecast": deepcopy(forecast),
    }


def _add_pending_forecast(state: dict[str, Any], forecast: dict[str, Any]) -> None:
    compact = _compact_forecast(state, forecast)
    if compact["forecastId"] in _seen_forecasts:
        return
    _seen_forecasts.add(compact["forecastId"])
    for minutes in RESOLUTION_HORIZONS:
        row_id = f"{compact['forecastId']}:{minutes}"
        _pending[row_id] = {
            "id": row_id,
            "forecastId": compact["forecastId"],
            "createdAt": compact["createdAt"],
            "horizonMinutes": minutes,
            "dueSimMinute": compact["createdSimMinute"] + minutes,
            "target": compact["target"],
            "predicted": {
                "withoutAudit": _predicted_metrics(compact["forecast"], minutes, "withoutAudit"),
                "withAudit": _predicted_metrics(compact["forecast"], minutes, "withAudit"),
            },
            "forecast": compact["forecast"],
        }
    while len(_pending) > MAX_PENDING_ROWS:
        oldest = min(_pending, key=lambda key: _pending[key].get("dueSimMinute", 0))
        _pending.pop(oldest, None)


def _resolve_due(state: dict[str, Any]) -> None:
    now_index = _sim_index(state)
    due_ids = [row_id for row_id, row in _pending.items() if _safe_int(row.get("dueSimMinute")) <= now_index]
    for row_id in due_ids:
        pending = _pending.pop(row_id, None)
        if not pending:
            continue
        forecast = pending.get("forecast", {}) if isinstance(pending.get("forecast"), dict) else {}
        actual = _actual_metrics(state, forecast)
        without_error = _error(pending["predicted"]["withoutAudit"], actual)
        with_error = _error(pending["predicted"]["withAudit"], actual)
        without_accuracy = _accuracy(without_error)
        with_accuracy = _accuracy(with_error)
        closest = "withAudit" if with_accuracy >= without_accuracy else "withoutAudit"
        selected_error = with_error if closest == "withAudit" else without_error
        selected_accuracy = max(with_accuracy, without_accuracy)
        _resolved.appendleft(
            {
                "id": row_id,
                "resolvedAt": _utc_now(),
                "forecastId": pending.get("forecastId"),
                "horizonMinutes": pending.get("horizonMinutes"),
                "target": pending.get("target", {}),
                "predicted": pending.get("predicted", {}),
                "actual": actual,
                "error": selected_error,
                "accuracyScore": selected_accuracy,
                "closestBranch": closest,
                "branchScores": {"withoutAudit": without_accuracy, "withAudit": with_accuracy},
            }
        )


def _summary() -> dict[str, Any]:
    rows = list(_resolved)
    recent = rows[:40]
    score = round(sum(_safe_int(row.get("accuracyScore")) for row in recent) / len(recent)) if recent else None
    misses = [row for row in recent if _safe_int(row.get("accuracyScore")) < 65]
    by_target: dict[str, dict[str, Any]] = {}
    for row in recent:
        target = row.get("target", {}) if isinstance(row.get("target"), dict) else {}
        key = str(target.get("queueName") or target.get("rideName") or target.get("zoneName") or "park")
        bucket = by_target.setdefault(key, {"target": key, "samples": 0, "scoreTotal": 0, "latestAccuracy": None})
        bucket["samples"] += 1
        bucket["scoreTotal"] += _safe_int(row.get("accuracyScore"))
        if bucket["latestAccuracy"] is None:
            bucket["latestAccuracy"] = row.get("accuracyScore")
    targets = [
        {
            "target": item["target"],
            "samples": item["samples"],
            "averageAccuracy": round(item["scoreTotal"] / max(1, item["samples"])),
            "latestAccuracy": item["latestAccuracy"],
        }
        for item in by_target.values()
    ]
    targets.sort(key=lambda item: (item["averageAccuracy"], -item["samples"]))
    drift = "watch"
    if score is None:
        drift = "warming_up"
    elif score < 65 or len(misses) >= 3:
        drift = "drifting"
    elif score >= 82:
        drift = "stable"
    return {
        "resolvedRows": len(rows),
        "recentWindow": len(recent),
        "accuracyScore": score,
        "confidence": _confidence_label(score, len(rows), len(_pending)),
        "driftStatus": drift,
        "missCount": len(misses),
        "lowestAccuracyTargets": targets[:4],
    }


def build_calibration_ledger(state: dict[str, Any], forecast: dict[str, Any] | None = None) -> dict[str, Any]:
    if forecast:
        _add_pending_forecast(state, forecast)
    _resolve_due(state)
    summary = _summary()
    pending_rows = sorted(_pending.values(), key=lambda row: row.get("dueSimMinute", 0))[:6]
    return {
        "mode": "compact_digital_twin_calibration_ledger",
        "generatedAt": _utc_now(),
        "storagePolicy": {
            "detailRetentionHours": RETENTION_HOURS,
            "maxDetailRows": MAX_DETAIL_ROWS,
            "maxPendingRows": MAX_PENDING_ROWS,
            "fullStateSnapshots": False,
            "estimatedHotStorageKb": round((len(_resolved) + len(_pending)) * 1.6, 1),
        },
        "summary": summary,
        "pendingCount": len(_pending),
        "pendingPreview": [
            {
                "id": row.get("id"),
                "target": row.get("target"),
                "horizonMinutes": row.get("horizonMinutes"),
                "dueInSimMinutes": max(0, _safe_int(row.get("dueSimMinute")) - _sim_index(state)),
                "predicted": row.get("predicted"),
            }
            for row in pending_rows
        ],
        "latestResolved": list(_resolved)[:6],
        "method": [
            "Store only target metrics, predictions, actuals, absolute error, and branch score.",
            "Resolve forecast rows when the simulation clock reaches the forecast horizon.",
            "Compare actual state against both wait and audit branches, then mark the closest realized branch.",
        ],
    }


def list_scenario_calibration_fixtures() -> dict[str, Any]:
    return {
        "mode": "digital_twin_scenario_calibration_fixture_catalog",
        "fixture_count": len(SCENARIO_CALIBRATION_FIXTURES),
        "fixtures": [
            {
                "id": fixture["id"],
                "scenario_key": fixture["scenario_key"],
                "description": fixture["description"],
                "expectation_count": len(fixture.get("expectations", [])),
                "stress_event_count": len(fixture.get("stress_events", [])),
            }
            for fixture in SCENARIO_CALIBRATION_FIXTURES
        ],
    }


def run_scenario_calibration(
    base_state: dict[str, Any],
    fixtures: list[dict[str, Any]] | None = None,
    horizon_minutes: int = 30,
) -> dict[str, Any]:
    selected_fixtures = fixtures if isinstance(fixtures, list) and fixtures else SCENARIO_CALIBRATION_FIXTURES
    rows = [_run_calibration_fixture(base_state, fixture, horizon_minutes=horizon_minutes) for fixture in selected_fixtures]
    sensitivity = run_sensitivity_sweeps(base_state, selected_fixtures, horizon_minutes=horizon_minutes)
    average_score = round(sum(_safe_int(row.get("score")) for row in rows) / max(1, len(rows)))
    failed = [row for row in rows if row.get("status") != "passed"]
    sensitivity_failed = [row for row in sensitivity.get("sweeps", []) if row.get("status") != "passed"]
    status = "passed" if not failed and not sensitivity_failed else "needs_tuning"
    return {
        "mode": "digital_twin_scenario_calibration",
        "generatedAt": _utc_now(),
        "status": status,
        "horizonMinutes": max(5, min(60, _safe_int(horizon_minutes, 30))),
        "fixtureCount": len(rows),
        "passedFixtureCount": len(rows) - len(failed),
        "averageScore": average_score,
        "readiness": {
            "status": "calibrated" if status == "passed" else "calibration_watch",
            "summary": (
                "Scenario fixtures and sensitivity sweeps are within expected bounds."
                if status == "passed"
                else "One or more fixtures or monotonic sensitivity sweeps failed; inspect suggestedTuning."
            ),
        },
        "fixtures": rows,
        "sensitivity": sensitivity,
        "suggestedTuning": _suggest_tuning(rows, sensitivity.get("sweeps", [])),
        "method": [
            "Apply deterministic stress events to a shared baseline state.",
            "Run each named action plan through simulate_action_plan.",
            "Compare projected impact, scorecard, and outcome metrics against explicit expectation bounds.",
            "Run monotonic sweeps for take rate and action horizon so parameter changes behave predictably.",
        ],
    }


def run_sensitivity_sweeps(
    base_state: dict[str, Any],
    fixtures: list[dict[str, Any]] | None = None,
    horizon_minutes: int = 30,
) -> dict[str, Any]:
    selected_fixtures = fixtures if isinstance(fixtures, list) and fixtures else SCENARIO_CALIBRATION_FIXTURES
    sweeps = []
    for fixture in selected_fixtures:
        action_plan = fixture.get("action_plan", {}) if isinstance(fixture.get("action_plan"), dict) else {}
        reroute = _guest_reroute(action_plan)
        if not reroute.get("enabled"):
            continue
        sweeps.append(_take_rate_sweep(base_state, fixture, horizon_minutes=horizon_minutes))
        sweeps.append(_horizon_sweep(base_state, fixture, horizon_minutes=horizon_minutes))
    failed = [row for row in sweeps if row.get("status") != "passed"]
    return {
        "mode": "digital_twin_parameter_sensitivity",
        "status": "passed" if not failed else "needs_tuning",
        "sweepCount": len(sweeps),
        "passedSweepCount": len(sweeps) - len(failed),
        "sweeps": sweeps,
    }


def _run_calibration_fixture(base_state: dict[str, Any], fixture: dict[str, Any], horizon_minutes: int) -> dict[str, Any]:
    scenario_key = str(fixture.get("scenario_key") or "ride_down")
    state = _fixture_state(base_state, fixture)
    action_plan = deepcopy(fixture.get("action_plan", {}) if isinstance(fixture.get("action_plan"), dict) else {})
    seed = f"calibration:{fixture.get('id', scenario_key)}"
    projection = simulate_action_plan(state, action_plan, horizon_minutes=horizon_minutes, seed=seed)
    checks = [_evaluate_expectation(projection, expectation) for expectation in fixture.get("expectations", []) if isinstance(expectation, dict)]
    passed = [check for check in checks if check.get("passed")]
    score = round((len(passed) / max(1, len(checks))) * 100)
    return {
        "id": fixture.get("id"),
        "scenario_key": scenario_key,
        "status": "passed" if len(passed) == len(checks) else "failed",
        "score": score,
        "seed": seed,
        "description": fixture.get("description"),
        "action": {
            "target": action_plan.get("target"),
            "action": action_plan.get("action"),
            "label": action_plan.get("label"),
        },
        "checks": checks,
        "projected_impact": projection.get("projected_impact", {}),
        "scorecard": projection.get("scorecard", {}),
        "outcome_metrics": (projection.get("outcome", {}) if isinstance(projection.get("outcome"), dict) else {}).get("metrics", {}),
        "secondary_risks": projection.get("secondary_risks", []),
    }


def _fixture_state(base_state: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
    state = deepcopy(base_state)
    scenario_key = str(fixture.get("scenario_key") or "ride_down")
    flow = state.setdefault("guestFlow", {})
    if isinstance(flow, dict):
        active = flow.get("activeScenario", {}) if isinstance(flow.get("activeScenario"), dict) else {}
        active["key"] = scenario_key
        active["name"] = scenario_key.replace("_", " ").title()
        flow["activeScenario"] = active
    for event in fixture.get("stress_events", []) if isinstance(fixture.get("stress_events"), list) else []:
        if isinstance(event, dict):
            state = apply_stress_event(state, event)
    return state


def _evaluate_expectation(projection: dict[str, Any], expectation: dict[str, Any]) -> dict[str, Any]:
    metric = str(expectation.get("metric") or "")
    value = _path_value(projection, metric)
    numeric_value = _safe_float(value)
    min_value = expectation.get("min")
    max_value = expectation.get("max")
    passed = True
    if min_value is not None and numeric_value < _safe_float(min_value):
        passed = False
    if max_value is not None and numeric_value > _safe_float(max_value):
        passed = False
    return {
        "metric": metric,
        "value": numeric_value,
        "min": min_value,
        "max": max_value,
        "passed": passed,
        "detail": _expectation_detail(metric, numeric_value, min_value, max_value, passed),
    }


def _path_value(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _expectation_detail(metric: str, value: float, min_value: Any, max_value: Any, passed: bool) -> str:
    if passed:
        return f"{metric}={round(value, 2)} is within expected bounds."
    if min_value is not None and value < _safe_float(min_value):
        return f"{metric}={round(value, 2)} is below minimum {min_value}."
    if max_value is not None and value > _safe_float(max_value):
        return f"{metric}={round(value, 2)} exceeds maximum {max_value}."
    return f"{metric}={round(value, 2)} failed expectation."


def _guest_reroute(action_plan: dict[str, Any]) -> dict[str, Any]:
    action_mix = action_plan.get("action_mix", {}) if isinstance(action_plan.get("action_mix"), dict) else {}
    reroute = action_mix.get("guest_reroute", {}) if isinstance(action_mix.get("guest_reroute"), dict) else {}
    return reroute


def _with_take_rate(action_plan: dict[str, Any], take_rate: float) -> dict[str, Any]:
    plan = deepcopy(action_plan)
    mix = plan.setdefault("action_mix", {})
    reroute = mix.setdefault("guest_reroute", {})
    reroute["enabled"] = True
    reroute["expectedTakeRate"] = take_rate
    return plan


def _with_duration(action_plan: dict[str, Any], minutes: int) -> dict[str, Any]:
    plan = deepcopy(action_plan)
    mix = plan.setdefault("action_mix", {})
    reroute = mix.setdefault("guest_reroute", {})
    reroute["enabled"] = True
    reroute["durationMinutes"] = minutes
    return plan


def _take_rate_sweep(base_state: dict[str, Any], fixture: dict[str, Any], horizon_minutes: int) -> dict[str, Any]:
    state = _fixture_state(base_state, fixture)
    action_plan = fixture.get("action_plan", {}) if isinstance(fixture.get("action_plan"), dict) else {}
    rates = [0.18, 0.34, 0.52]
    points = []
    for rate in rates:
        projection = simulate_action_plan(
            state,
            _with_take_rate(action_plan, rate),
            horizon_minutes=horizon_minutes,
            seed=f"sensitivity:{fixture.get('id')}:take_rate:{rate}",
        )
        points.append(
            {
                "takeRate": rate,
                "movedGuests": _safe_int(projection.get("projected_impact", {}).get("movedGuests")),
                "overall": _safe_int(projection.get("scorecard", {}).get("overall")),
            }
        )
    moved = [point["movedGuests"] for point in points]
    monotonic = all(right >= left for left, right in zip(moved, moved[1:]))
    return {
        "id": f"{fixture.get('id')}:take_rate",
        "fixtureId": fixture.get("id"),
        "parameter": "expectedTakeRate",
        "status": "passed" if monotonic else "failed",
        "points": points,
        "rule": "Higher take-rate should not move fewer guests.",
    }


def _horizon_sweep(base_state: dict[str, Any], fixture: dict[str, Any], horizon_minutes: int) -> dict[str, Any]:
    state = _fixture_state(base_state, fixture)
    action_plan = fixture.get("action_plan", {}) if isinstance(fixture.get("action_plan"), dict) else {}
    horizons = [10, 20, max(30, min(60, _safe_int(horizon_minutes, 30)))]
    points = []
    for duration in horizons:
        projection = simulate_action_plan(
            state,
            _with_duration(action_plan, duration),
            horizon_minutes=max(duration, horizon_minutes),
            seed=f"sensitivity:{fixture.get('id')}:horizon:{duration}",
        )
        points.append(
            {
                "durationMinutes": duration,
                "movedGuests": _safe_int(projection.get("projected_impact", {}).get("movedGuests")),
                "overall": _safe_int(projection.get("scorecard", {}).get("overall")),
            }
        )
    moved = [point["movedGuests"] for point in points]
    monotonic = all(right >= left for left, right in zip(moved, moved[1:]))
    return {
        "id": f"{fixture.get('id')}:duration",
        "fixtureId": fixture.get("id"),
        "parameter": "durationMinutes",
        "status": "passed" if monotonic else "failed",
        "points": points,
        "rule": "Longer active reroute duration should not move fewer cumulative guests.",
    }


def _suggest_tuning(rows: list[dict[str, Any]], sweeps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    suggestions = []
    for row in rows:
        failed_checks = [check for check in row.get("checks", []) if isinstance(check, dict) and not check.get("passed")]
        if not failed_checks:
            continue
        suggestions.append(
            {
                "fixtureId": row.get("id"),
                "issue": "fixture_bounds_failed",
                "failedMetrics": [check.get("metric") for check in failed_checks],
                "recommendation": _fixture_recommendation(failed_checks),
            }
        )
    for sweep in sweeps:
        if sweep.get("status") == "passed":
            continue
        suggestions.append(
            {
                "fixtureId": sweep.get("fixtureId"),
                "issue": "sensitivity_monotonicity_failed",
                "parameter": sweep.get("parameter"),
                "recommendation": "Check transition_state action duration and take-rate handling before tuning score weights.",
            }
        )
    return suggestions or [
        {
            "issue": "none",
            "recommendation": "Fixtures passed; next step is replacing synthetic bounds with measured historical ranges.",
        }
    ]


def _fixture_recommendation(failed_checks: list[dict[str, Any]]) -> str:
    metrics = {str(check.get("metric") or "") for check in failed_checks}
    if any("critical_density" in metric or "safety" in metric for metric in metrics):
        return "Increase critical-density penalty or generate lower-density target mixes before dispatch."
    if any("movedGuests" in metric for metric in metrics):
        return "Tune take-rate, route duration, or queue-gate effects so reroute volume matches fixture bounds."
    if any("food_backlog" in metric for metric in metrics):
        return "Tune food backlog arrivals, suppression relief, or runner throughput."
    if any("grid_load" in metric for metric in metrics):
        return "Tune HVAC protection energy tradeoff and storm-load coupling."
    return "Inspect fixture metrics and adjust either expected bounds or transition coefficients."


def reset_calibration_ledger() -> None:
    _pending.clear()
    _resolved.clear()
    _seen_forecasts.clear()
