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


def _clamp(value: float, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, round(value)))


def _tone_for_pct(value: int, warn: int = 70, ok: int = 82) -> str:
    if value >= ok:
        return "ok"
    if value >= warn:
        return "watch"
    return "critical"


def _scenario_policy_blocks(scenario_lab: dict[str, Any]) -> int:
    rows = scenario_lab.get("scoreboard", []) if isinstance(scenario_lab.get("scoreboard"), list) else []
    return sum(_safe_int((row.get("parkpulse", {}) if isinstance(row, dict) else {}).get("policyBlocks"), 0) for row in rows)


def _decision_label(average_score: int, accuracy: int, drift_status: str) -> str:
    if average_score >= 78 and accuracy >= 80 and drift_status in {"stable", "warming_up"}:
        return "Deploy as pilot"
    if average_score >= 65 and accuracy >= 70:
        return "Needs more telemetry"
    return "Not ready for autonomous action"


def build_readiness_brief(state: dict[str, Any]) -> dict[str, Any]:
    forecast = state.get("counterfactualForecast", {}) if isinstance(state.get("counterfactualForecast"), dict) else {}
    calibration = state.get("digitalTwinCalibration", {}) if isinstance(state.get("digitalTwinCalibration"), dict) else {}
    scenario_lab = state.get("scenarioLab", {}) if isinstance(state.get("scenarioLab"), dict) else {}
    mission_replay = state.get("missionReplay", {}) if isinstance(state.get("missionReplay"), dict) else {}
    impact = forecast.get("impact", {}) if isinstance(forecast.get("impact"), dict) else {}
    calibration_summary = calibration.get("summary", {}) if isinstance(calibration.get("summary"), dict) else {}
    scenario_summary = scenario_lab.get("summary", {}) if isinstance(scenario_lab.get("summary"), dict) else {}
    storage_policy = calibration.get("storagePolicy", {}) if isinstance(calibration.get("storagePolicy"), dict) else {}

    total_saved = _safe_int(scenario_summary.get("totalGuestMinutesSaved"), _safe_int(impact.get("guestMinutesSaved"), 0))
    spillback = _safe_int(scenario_summary.get("averageSpillbackAvoidedPct"), _safe_int(impact.get("serviceLaneRiskReducedPct"), 0))
    staff = _safe_int(scenario_summary.get("averageStaffOverloadReducedPct"), _safe_int(impact.get("staffConflictRiskReducedPct"), 0))
    guest_care = _safe_int(impact.get("guestCareCasesAvoided"), 0)
    accuracy = _safe_int(calibration_summary.get("accuracyScore"), 0)
    drift_status = str(calibration_summary.get("driftStatus") or "warming_up")
    average_score = _safe_int(scenario_summary.get("averageScore"), 0)
    policy_blocks = _scenario_policy_blocks(scenario_lab)
    weakest = str(scenario_summary.get("weakestScenario") or "not measured")
    decision = _decision_label(average_score, accuracy, drift_status)
    readiness_score = _clamp(average_score * 0.45 + accuracy * 0.3 + spillback * 0.12 + staff * 0.08 + min(policy_blocks, 8) * 1.5)

    if decision == "Deploy as pilot":
        go_no_go = "GO WITH CONDITIONS"
        reason = "The demo shows measurable operating value, calibrated forecasts, scenario coverage, and policy-block evidence, but it should remain supervised until live integrations prove durability."
    elif decision == "Needs more telemetry":
        go_no_go = "CONDITIONAL"
        reason = "The operating loop is useful, but trust evidence is not strong enough for a pilot without more live telemetry and failure testing."
    else:
        go_no_go = "NO-GO"
        reason = "The current proof does not yet meet minimum readiness for operator-facing deployment."

    return {
        "mode": "parkpulse_readiness_brief",
        "generatedAt": _utc_now(),
        "headline": "Executive proof of value, trust, readiness, and deployment posture for a supervised ParkPulse pilot.",
        "decision": {
            "label": decision,
            "goNoGo": go_no_go,
            "score": readiness_score,
            "reason": reason,
            "conditions": [
                "Keep medical, security, evacuation, accessibility, maintenance reopen, labor exception, and compensation actions behind explicit approval.",
                "Connect at least one real queue, staffing, delivery, and guest-feedback feed before claiming production readiness.",
                "Run failure-injection, duplicate-dispatch, stream-interruption, and load tests before autonomous operation.",
            ],
        },
        "operationalValue": [
            {
                "id": "guest_minutes",
                "label": "Guest-minutes saved",
                "value": total_saved,
                "unit": "minutes",
                "tone": "ok" if total_saved >= 2500 else "watch",
                "detail": "Scenario Lab aggregate compared with baseline operation.",
                "proof": ["scenarioLab.summary.totalGuestMinutesSaved", "counterfactualForecast.impact"],
            },
            {
                "id": "spillback",
                "label": "Spillback avoided",
                "value": spillback,
                "unit": "pct",
                "tone": _tone_for_pct(spillback, warn=18, ok=28),
                "detail": "Average service-lane and queue-spillback reduction across scenario rows.",
                "proof": ["scenarioLab.summary.averageSpillbackAvoidedPct", "spillback.delta"],
            },
            {
                "id": "staff_overload",
                "label": "Staff overload reduced",
                "value": staff,
                "unit": "pct",
                "tone": _tone_for_pct(staff, warn=20, ok=30),
                "detail": "Estimated reduction in staff conflict and overload pressure.",
                "proof": ["scenarioLab.summary.averageStaffOverloadReducedPct", "operationsAudit.schedule"],
            },
            {
                "id": "guest_care",
                "label": "Guest-care cases avoided",
                "value": guest_care,
                "unit": "cases",
                "tone": "ok" if guest_care >= 10 else "watch",
                "detail": "Counterfactual estimate for avoided guest-care escalation.",
                "proof": ["counterfactualForecast.impact.guestCareCasesAvoided"],
            },
        ],
        "trust": [
            {
                "id": "prediction_accuracy",
                "label": "Prediction accuracy",
                "value": accuracy,
                "unit": "pct",
                "tone": _tone_for_pct(accuracy),
                "detail": "Latest compact calibration ledger score.",
                "proof": ["digitalTwinCalibration.summary.accuracyScore"],
            },
            {
                "id": "calibration_drift",
                "label": "Calibration drift",
                "value": drift_status,
                "unit": "status",
                "tone": "ok" if drift_status == "stable" else "watch",
                "detail": "Whether recent forecasts are drifting away from observed outcomes.",
                "proof": ["digitalTwinCalibration.summary.driftStatus"],
            },
            {
                "id": "policy_blocks",
                "label": "Policy-blocked actions",
                "value": policy_blocks,
                "unit": "blocks",
                "tone": "ok" if policy_blocks > 0 else "watch",
                "detail": "Evidence that risky actions are blocked instead of silently executed.",
                "proof": ["scenarioLab.scoreboard.parkpulse.policyBlocks", "bounded_action_only"],
            },
            {
                "id": "weakest_scenario",
                "label": "Weakest scenario",
                "value": weakest,
                "unit": "scenario",
                "tone": "watch",
                "detail": str(scenario_summary.get("gap") or "Weakest scenario should drive the next validation pass."),
                "proof": ["scenarioLab.summary.weakestScenario"],
            },
        ],
        "readiness": [
            {
                "id": "live_now",
                "label": "Runs live now",
                "status": "ready",
                "detail": "State scan, audit snapshot, counterfactual forecast, mission replay, scenario lab, and calibration ledger are available through API/UI.",
                "proof": ["api.park_state", "api.park_mission_replay", "api.park_scenario_lab"],
            },
            {
                "id": "simulated",
                "label": "Still simulated",
                "status": "watch",
                "detail": "Scenario comparisons and guest movement are compact deterministic simulations, not full real-world validation.",
                "proof": ["scenarioLab.method", "park_simulation"],
            },
            {
                "id": "integration_needed",
                "label": "Needs real integration",
                "status": "watch",
                "detail": "Production proof still needs live queue sensors, staffing systems, delivery receipts, and guest-feedback loops.",
                "proof": ["readiness.conditions"],
            },
            {
                "id": "storage_cost",
                "label": "Storage/cost posture",
                "status": "ready" if not storage_policy.get("fullStateSnapshots") else "watch",
                "detail": f"Compact ledger keeps forecast rows only; estimated hot storage is {storage_policy.get('estimatedHotStorageKb', 'n/a')} KB.",
                "proof": ["digitalTwinCalibration.storagePolicy"],
            },
        ],
        "storageCost": {
            "posture": "compact_metric_rows",
            "fullStateSnapshots": bool(storage_policy.get("fullStateSnapshots", False)),
            "estimatedHotStorageKb": storage_policy.get("estimatedHotStorageKb"),
            "detailRetentionHours": storage_policy.get("detailRetentionHours"),
            "method": "Readiness uses existing scenario, forecast, and calibration summaries; it does not store replay video or full alternate worlds.",
        },
        "evidence": [
            "missionReplay" if mission_replay else "missionReplay:missing",
            "scenarioLab" if scenario_lab else "scenarioLab:missing",
            "counterfactualForecast" if forecast else "counterfactualForecast:missing",
            "digitalTwinCalibration" if calibration else "digitalTwinCalibration:missing",
        ],
    }
