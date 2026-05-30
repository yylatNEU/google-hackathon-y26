from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any


MAX_DETAIL_ROWS = 1200
MAX_PENDING_ROWS = 300
RETENTION_HOURS = 72
RESOLUTION_HORIZONS = (5, 15, 30)

_pending: dict[str, dict[str, Any]] = {}
_resolved: deque[dict[str, Any]] = deque(maxlen=MAX_DETAIL_ROWS)
_seen_forecasts: set[str] = set()


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


def reset_calibration_ledger() -> None:
    _pending.clear()
    _resolved.clear()
    _seen_forecasts.clear()
