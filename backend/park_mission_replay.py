from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _clock(state: dict[str, Any], offset_minutes: int = 0) -> str:
    sim_time = state.get("simTime", {}) if isinstance(state.get("simTime"), dict) else {}
    total = (_safe_int(sim_time.get("hour"), 11) * 60 + _safe_int(sim_time.get("minute"), 45) + offset_minutes) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def _top_anomaly(audit: dict[str, Any]) -> dict[str, Any]:
    anomalies = audit.get("anomalies", []) if isinstance(audit.get("anomalies"), list) else []
    if not anomalies:
        return {}
    weight = {"critical": 3, "warning": 2, "watch": 1}
    return max(
        anomalies,
        key=lambda item: (weight.get(str(item.get("severity")), 0), 100 - _safe_int(item.get("leadTimeMinutes"), 99)),
    )


def _tone(status: str) -> str:
    if status in {"critical", "blocked", "drifting", "risk"}:
        return "critical"
    if status in {"warning", "watch", "pending_operator_approval", "warming_up"}:
        return "watch"
    return "ok"


def _execution_stage(forecast: dict[str, Any], stage_name: str, fallback_index: int = 0) -> dict[str, Any]:
    action_execution = forecast.get("actionExecution", {}) if isinstance(forecast.get("actionExecution"), dict) else {}
    timeline = action_execution.get("timeline", []) if isinstance(action_execution.get("timeline"), list) else []
    for stage in timeline:
        if stage.get("stage") == stage_name:
            return stage
    return timeline[fallback_index] if len(timeline) > fallback_index else {}


def build_mission_replay(state: dict[str, Any]) -> dict[str, Any]:
    audit = state.get("operationsAudit", {}) if isinstance(state.get("operationsAudit"), dict) else {}
    forecast = state.get("counterfactualForecast", {}) if isinstance(state.get("counterfactualForecast"), dict) else {}
    calibration = state.get("digitalTwinCalibration", {}) if isinstance(state.get("digitalTwinCalibration"), dict) else {}
    anomaly = _top_anomaly(audit)
    focus = forecast.get("focus", {}) if isinstance(forecast.get("focus"), dict) else {}
    spillback = forecast.get("spillback", {}) if isinstance(forecast.get("spillback"), dict) else {}
    thresholds = spillback.get("thresholds", {}) if isinstance(spillback.get("thresholds"), dict) else {}
    action_execution = forecast.get("actionExecution", {}) if isinstance(forecast.get("actionExecution"), dict) else {}
    impact = forecast.get("impact", {}) if isinstance(forecast.get("impact"), dict) else {}
    calibration_summary = calibration.get("summary", {}) if isinstance(calibration.get("summary"), dict) else {}
    latest_resolved = calibration.get("latestResolved", []) if isinstance(calibration.get("latestResolved"), list) else []
    latest_accuracy = latest_resolved[0] if latest_resolved else {}
    worker_stage = _execution_stage(forecast, "worker_path_opened", 3)
    stabilized_stage = _execution_stage(forecast, "stabilized_flow", -1)

    response = str(focus.get("response") or "capacity-aware operating action")
    queue_name = str(focus.get("queueName") or spillback.get("queueName") or "pressure queue")
    anomaly_title = str(anomaly.get("title") or focus.get("topAnomalyTitle") or "Park pressure signal detected")
    walkway = thresholds.get("withoutAuditWalkwayBlockedInMinutes")
    service_lane = thresholds.get("withoutAuditServiceLaneBlockedInMinutes")
    accuracy = calibration_summary.get("accuracyScore")
    accuracy_label = f"{accuracy}% accuracy" if isinstance(accuracy, (int, float)) else "accuracy warming up"

    steps = [
        {
            "id": "signal",
            "time": _clock(state, -6),
            "label": "Signal detected",
            "title": anomaly_title,
            "detail": "; ".join((anomaly.get("evidence") or ["Audit agent correlated live queue, work log, schedule, and guest-care pressure."])[:2]),
            "tone": _tone(str(anomaly.get("severity") or "warning")),
            "proof": ["operationsAudit", str(anomaly.get("id") or "audit_snapshot")],
        },
        {
            "id": "forecast",
            "time": _clock(state, -4),
            "label": "Twin forecast",
            "title": f"{queue_name} spillback forecast",
            "detail": f"Walkway blocks in {walkway if walkway is not None else 'no'}m; service lane in {service_lane if service_lane is not None else 'no'}m if the park waits.",
            "tone": "critical" if walkway == 0 or (isinstance(walkway, int) and walkway <= 5) else "watch",
            "proof": ["counterfactualForecast", str(forecast.get("forecastId") or "")],
        },
        {
            "id": "decision",
            "time": _clock(state, -3),
            "label": "Decision",
            "title": response.title(),
            "detail": f"Agent chooses the bounded operating move with {forecast.get('leadTimeMinutes', 0)}m early-warning lead time.",
            "tone": "ok",
            "proof": ["actionExecution", action_execution.get("mode", "delayed_action_guest_response_model")],
        },
        {
            "id": "governance",
            "time": _clock(state, -2),
            "label": "Governance",
            "title": "Unsafe ride control stays blocked",
            "detail": "Guest, signage, and worker tasks are bounded; ride reopening, labor exceptions, medical, security, and compensation remain approval boundaries.",
            "tone": "watch",
            "proof": ["policy", "bounded_action_only"],
        },
        {
            "id": "execution",
            "time": _clock(state, _safe_int(worker_stage.get("minute"), 6)),
            "label": "Execution",
            "title": str(worker_stage.get("label") or "Worker path opens and guest guidance is active"),
            "detail": f"{worker_stage.get('movedGuests', 0)} guests moving by minute {worker_stage.get('minute', 6)}; final take-rate projected at {action_execution.get('finalTakeRatePct', 0)}%.",
            "tone": "ok",
            "proof": ["actionExecution.timeline", str(worker_stage.get("stage") or "worker_path_opened")],
        },
        {
            "id": "outcome",
            "time": _clock(state, 15),
            "label": "Outcome",
            "title": "Spillback avoided and service access protected",
            "detail": f"{impact.get('guestMinutesSaved', 0)} guest-minutes saved; {impact.get('guestCareCasesAvoided', 0)} guest-care cases avoided; {stabilized_stage.get('movedGuests', 0)} guests moved by stabilization.",
            "tone": "ok",
            "proof": ["counterfactualForecast.impact", "spillback.delta"],
        },
        {
            "id": "learning",
            "time": _clock(state, 16),
            "label": "Learning",
            "title": "Forecast logged for calibration",
            "detail": f"{accuracy_label}; drift status is {calibration_summary.get('driftStatus', 'warming_up')}.",
            "tone": _tone(str(calibration_summary.get("driftStatus") or "warming_up")),
            "proof": ["digitalTwinCalibration", str(latest_accuracy.get("id") or "pending_rows")],
        },
    ]

    completed = sum(1 for step in steps if step["id"] != "learning" or calibration_summary.get("resolvedRows", 0))
    return {
        "mode": "mission_replay",
        "generatedAt": _utc_now(),
        "headline": f"From {anomaly_title.lower()} to bounded action, outcome, and learning in one operating thread.",
        "scenario": (state.get("guestFlow", {}) if isinstance(state.get("guestFlow"), dict) else {}).get("activeScenario", {}),
        "status": "learning" if calibration_summary.get("resolvedRows", 0) else "in_progress",
        "progressPct": round((completed / len(steps)) * 100),
        "primaryTarget": {
            "zoneName": focus.get("zoneName", ""),
            "rideName": focus.get("rideName", ""),
            "queueName": queue_name,
        },
        "summary": {
            "leadTimeMinutes": forecast.get("leadTimeMinutes", 0),
            "finalTakeRatePct": action_execution.get("finalTakeRatePct", 0),
            "guestMinutesSaved": impact.get("guestMinutesSaved", 0),
            "accuracyScore": accuracy,
            "driftStatus": calibration_summary.get("driftStatus", "warming_up"),
        },
        "steps": steps,
    }
