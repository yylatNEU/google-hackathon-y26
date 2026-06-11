#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "output" / "qa"
EVALUATION_CONTRACT_VERSION = "timelapse-policy-scorecard-v3"
POLICY_SCORE_WEIGHTS = {
    "final_critical_bypass_penalty": 25,
    "reroute_streak_penalty_after_two": 3,
    "override_penalty": 1,
    "dominant_action_share_threshold": 0.70,
    "dominant_action_share_penalty_per_point": 1,
}
METRIC_TOLERANCES = {
    "satisfaction": 0.25,
    "slowest_ride_wait": 1.0,
    "food_backlog": 5.0,
    "food_eta_minutes": 0.5,
    "busiest_zone_density": 0.5,
    "open_callouts": 0.5,
    "grid_load": 0.5,
}


METRICS: dict[str, tuple[str, bool]] = {
    "satisfaction": ("digest.avg_satisfaction", False),
    "slowest_ride_wait": ("digest.slowest_ride.waitMins", True),
    "food_backlog": ("digest.food_backlog", True),
    "food_eta_minutes": ("digest.food_eta_minutes", True),
    "busiest_zone_density": ("digest.busiest_zone.density", True),
    "open_callouts": ("digest.open_callouts", True),
    "grid_load": ("digest.grid_load", True),
}


def _now_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    parsed = json.loads(path.read_text(encoding="utf-8"))
    return parsed if isinstance(parsed, dict) else {}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parsed = json.loads(line)
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def _get(row: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = row
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return default
    return current


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_open(row: dict[str, Any]) -> bool:
    return _get(row, "phase.is_open_to_guests") is True


def _action_key(action: dict[str, Any] | None) -> str:
    if not isinstance(action, dict):
        return "none"
    return f"{action.get('target')}/{action.get('action')}"


def _model_action(row: dict[str, Any]) -> dict[str, Any] | None:
    model = row.get("model_allowed_action")
    if isinstance(model, dict):
        return model
    return row.get("allowed_action") if isinstance(row.get("allowed_action"), dict) else None


def _executed_action(row: dict[str, Any]) -> dict[str, Any] | None:
    allowed = row.get("allowed_action")
    return allowed if isinstance(allowed, dict) else None


def _food_severity(digest: dict[str, Any]) -> str:
    backlog = int(_number(digest.get("food_backlog")))
    eta = int(_number(digest.get("food_eta_minutes")))
    if backlog >= 700 or eta >= 75:
        return "p0_gridlock"
    if backlog >= 400 or eta >= 45:
        return "p1_critical"
    if backlog >= 140 or eta >= 25:
        return "p2_warning"
    return "normal"


def _metric(row: dict[str, Any], key: str) -> float:
    path = METRICS[key][0]
    return _number(_get(row, path, 0))


def _summarize_metric(rows: list[dict[str, Any]], key: str) -> dict[str, float]:
    values = [_metric(row, key) for row in rows]
    if not values:
        return {"avg": 0.0, "worst": 0.0, "best": 0.0}
    lower_is_better = METRICS[key][1]
    return {
        "avg": round(mean(values), 3),
        "worst": round(max(values) if lower_is_better else min(values), 3),
        "best": round(min(values) if lower_is_better else max(values), 3),
    }


def _delta(new_value: float, old_value: float) -> float:
    return round(new_value - old_value, 3)


def _evaluation_contract() -> dict[str, Any]:
    contract = {
        "version": EVALUATION_CONTRACT_VERSION,
        "open_tick_filter": "phase.is_open_to_guests == true for both candidate and baseline metrics",
        "metrics": {
            key: {"path": path, "lower_is_better": lower_is_better}
            for key, (path, lower_is_better) in METRICS.items()
        },
        "food_severity_thresholds": {
            "p0_gridlock": "food_backlog >= 700 or food_eta_minutes >= 75",
            "p1_critical": "food_backlog >= 400 or food_eta_minutes >= 45",
            "p2_warning": "food_backlog >= 140 or food_eta_minutes >= 25",
        },
        "policy_score_weights": POLICY_SCORE_WEIGHTS,
        "metric_tolerances": METRIC_TOLERANCES,
        "policy_score_is_not_operational_improvement": True,
        "long_term_operating_stability": {
            "purpose": "Adds day-stability evidence without replacing immediate guest outcome metrics.",
            "higher_stability_score_is_better": True,
            "severe_pressure_tick": "food critical, wait >= 120, density >= 125, path congestion >= 120, grid >= 115, or callouts >= 40",
            "recovery_gain": "first-half operating stress minus second-half operating stress; positive means the day recovered.",
            "guest_disruption_actions": [
                "ride/reroute",
                "traffic/redirect_food",
                "food/suppress_item",
                "food/pause_mobile_order_intake",
            ],
        },
    }
    encoded = json.dumps(contract, sort_keys=True).encode("utf-8")
    contract["fingerprint"] = hashlib.sha256(encoded).hexdigest()[:16]
    return contract


def _metric_direction(key: str, delta: float) -> str:
    if abs(delta) <= METRIC_TOLERANCES.get(key, 0.0):
        return "flat"
    lower_is_better = METRICS[key][1]
    if delta == 0:
        return "flat"
    improved = delta < 0 if lower_is_better else delta > 0
    return "improved" if improved else "regressed"


def _digest_value(row: dict[str, Any], path: str) -> float:
    return _number(_get(row, f"digest.{path}", 0))


def _operating_stress(row: dict[str, Any]) -> float:
    food_backlog = _digest_value(row, "food_backlog")
    food_eta = _digest_value(row, "food_eta_minutes")
    wait = _digest_value(row, "slowest_ride.waitMins")
    density = _digest_value(row, "busiest_zone.density")
    path = _digest_value(row, "most_congested_path.congestionLevel")
    callouts = _digest_value(row, "open_callouts")
    grid = _digest_value(row, "grid_load")
    stress_parts = [
        max(0.0, food_backlog - 140.0) / 560.0,
        max(0.0, food_eta - 25.0) / 50.0,
        max(0.0, wait - 90.0) / 60.0,
        max(0.0, density - 110.0) / 30.0,
        max(0.0, path - 100.0) / 40.0,
        max(0.0, callouts - 25.0) / 20.0,
        max(0.0, grid - 100.0) / 30.0,
    ]
    return round(sum(stress_parts), 4)


def _is_severe_pressure_tick(row: dict[str, Any]) -> bool:
    return (
        _food_severity(row.get("digest", {}) if isinstance(row.get("digest"), dict) else {}) in {"p0_gridlock", "p1_critical"}
        or _digest_value(row, "slowest_ride.waitMins") >= 120
        or _digest_value(row, "busiest_zone.density") >= 125
        or _digest_value(row, "most_congested_path.congestionLevel") >= 120
        or _digest_value(row, "grid_load") >= 115
        or _digest_value(row, "open_callouts") >= 40
    )


def _max_bool_streak(values: list[bool]) -> int:
    best = 0
    current = 0
    for value in values:
        current = current + 1 if value else 0
        best = max(best, current)
    return best


def _tail(rows: list[dict[str, Any]], share: float = 0.2) -> list[dict[str, Any]]:
    if not rows:
        return []
    count = max(1, round(len(rows) * share))
    return rows[-count:]


def _avg(values: list[float]) -> float:
    return round(mean(values), 4) if values else 0.0


def _run_stability_profile(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: _number(row.get("sim_minute")))
    stresses = [_operating_stress(row) for row in ordered]
    severe_flags = [_is_severe_pressure_tick(row) for row in ordered]
    midpoint = max(1, len(ordered) // 2)
    first_half_stress = _avg(stresses[:midpoint])
    second_half_stress = _avg(stresses[midpoint:])
    late_stress = _avg([_operating_stress(row) for row in _tail(ordered)])
    volatility = _avg([abs(stresses[index] - stresses[index - 1]) for index in range(1, len(stresses))])
    severe_tick_count = sum(1 for flag in severe_flags if flag)
    severe_tick_rate = round(severe_tick_count / max(1, len(ordered)), 4)
    max_severe_streak = _max_bool_streak(severe_flags)
    recovery_gain = round(first_half_stress - second_half_stress, 4)
    penalty = (
        _avg(stresses) * 12.0
        + severe_tick_rate * 35.0
        + max_severe_streak * 0.4
        + late_stress * 10.0
        + volatility * 3.0
    )
    return {
        "open_tick_count": len(ordered),
        "avg_operating_stress": _avg(stresses),
        "first_half_operating_stress": first_half_stress,
        "second_half_operating_stress": second_half_stress,
        "recovery_gain": recovery_gain,
        "late_day_operating_stress": late_stress,
        "stress_volatility": volatility,
        "severe_pressure_tick_count": severe_tick_count,
        "severe_pressure_tick_rate": severe_tick_rate,
        "max_severe_pressure_streak": max_severe_streak,
        "stability_score": round(max(0.0, min(100.0, 100.0 - penalty)), 3),
    }


def _action_load_profile(calls: list[dict[str, Any]]) -> dict[str, Any]:
    disruptive = {"ride/reroute", "traffic/redirect_food", "food/suppress_item", "food/pause_mobile_order_intake"}
    action_keys = [_action_key(_executed_action(row)) for row in calls]
    action_mix = Counter(action_keys)
    dominant = action_mix.most_common(1)[0] if action_mix else ("none", 0)
    max_streak = 0
    for action in action_mix:
        max_streak = max(max_streak, int(_max_action_streak(calls, action, "executed").get("count") or 0))
    return {
        "executed_action_count": len(action_keys),
        "guest_disruption_action_count": sum(1 for action in action_keys if action in disruptive),
        "guest_disruption_action_share": round(sum(1 for action in action_keys if action in disruptive) / max(1, len(action_keys)), 4),
        "dominant_action": dominant[0],
        "dominant_action_count": dominant[1],
        "dominant_action_share": round(dominant[1] / max(1, len(action_keys)), 4),
        "max_repeated_action_streak": max_streak,
    }


def _long_term_operating_stability(
    open_ticks: list[dict[str, Any]],
    baseline_open: list[dict[str, Any]],
    calls: list[dict[str, Any]],
) -> dict[str, Any]:
    current = _run_stability_profile(open_ticks)
    action_load = _action_load_profile(calls)
    result: dict[str, Any] = {
        "current": current,
        "candidate_action_load": action_load,
        "interpretation": "Positive deltas are better for stability_score and recovery_gain. Negative deltas are better for stress, severe pressure, late-day stress, and volatility.",
    }
    if baseline_open:
        baseline = _run_stability_profile(baseline_open)
        result["baseline"] = baseline
        result["delta"] = {
            "stability_score": _delta(current["stability_score"], baseline["stability_score"]),
            "avg_operating_stress": _delta(current["avg_operating_stress"], baseline["avg_operating_stress"]),
            "recovery_gain": _delta(current["recovery_gain"], baseline["recovery_gain"]),
            "late_day_operating_stress": _delta(current["late_day_operating_stress"], baseline["late_day_operating_stress"]),
            "stress_volatility": _delta(current["stress_volatility"], baseline["stress_volatility"]),
            "severe_pressure_tick_count": int(current["severe_pressure_tick_count"]) - int(baseline["severe_pressure_tick_count"]),
            "severe_pressure_tick_rate": _delta(current["severe_pressure_tick_rate"], baseline["severe_pressure_tick_rate"]),
            "max_severe_pressure_streak": int(current["max_severe_pressure_streak"]) - int(baseline["max_severe_pressure_streak"]),
        }
    return result


def _operational_delta_claims(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for key, entry in metrics.items():
        delta = entry.get("delta", {})
        if not isinstance(delta, dict) or "avg" not in delta:
            continue
        avg_delta = float(delta.get("avg") or 0)
        worst_delta = float(delta.get("worst") or 0)
        claims.append(
            {
                "metric": key,
                "avg_delta": avg_delta,
                "avg_direction": _metric_direction(key, avg_delta),
                "worst_delta": worst_delta,
                "worst_direction": _metric_direction(key, worst_delta),
                "lower_is_better": METRICS[key][1],
            }
        )
    return claims


def _tradeoff_ledger(claims: list[dict[str, Any]]) -> dict[str, Any]:
    improvements = [
        claim
        for claim in claims
        if claim.get("avg_direction") == "improved" and claim.get("worst_direction") != "regressed"
    ]
    regressions = [
        claim
        for claim in claims
        if claim.get("avg_direction") == "regressed" or claim.get("worst_direction") == "regressed"
    ]
    entries: list[dict[str, Any]] = []
    for regression in regressions:
        entries.append(
            {
                "metric": regression.get("metric"),
                "avg_delta": regression.get("avg_delta"),
                "avg_direction": regression.get("avg_direction"),
                "worst_delta": regression.get("worst_delta"),
                "worst_direction": regression.get("worst_direction"),
                "supporting_improvements": [
                    {
                        "metric": item.get("metric"),
                        "avg_delta": item.get("avg_delta"),
                        "worst_delta": item.get("worst_delta"),
                    }
                    for item in improvements
                    if item.get("metric") != regression.get("metric")
                ][:4],
                "tradeoff_status": "unresolved_requires_owner",
                "required_owner_note": "Explain why this regression is acceptable, or change candidate scoring/policy until the regression is removed.",
            }
        )
    return {
        "entry_count": len(entries),
        "unresolved_count": len(entries),
        "entries": entries,
        "release_expectation": "0 unresolved tradeoffs before release-clean promotion.",
    }


def _normalize_severity(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "p0": "p0_gridlock",
        "p0_gridlock": "p0_gridlock",
        "critical": "p1_critical",
        "p1": "p1_critical",
        "p1_critical": "p1_critical",
        "warning": "p2_warning",
        "p2": "p2_warning",
        "p2_warning": "p2_warning",
        "normal": "normal",
    }
    return aliases.get(normalized, normalized or "missing")


def _risk_classification(row: dict[str, Any]) -> dict[str, Any]:
    parsed = row.get("parsed_response", {}) if isinstance(row.get("parsed_response"), dict) else {}
    risk = parsed.get("risk_classification", {}) if isinstance(parsed.get("risk_classification"), dict) else {}
    return risk


def _llm_reasoning_audit(calls: list[dict[str, Any]]) -> dict[str, Any]:
    severity_mismatches: list[dict[str, Any]] = []
    missed_critical_food: list[dict[str, Any]] = []
    missing_risk_classification: list[dict[str, Any]] = []
    for row in calls:
        if row.get("status") not in {"success", "fallback_transport_error"}:
            continue
        deterministic = _food_severity(row.get("before_digest", {}) if isinstance(row.get("before_digest"), dict) else {})
        risk = _risk_classification(row)
        if not risk:
            missing_risk_classification.append({"sim_minute": row.get("sim_minute"), "status": row.get("status")})
            continue
        primary = str(risk.get("primary_risk") or "").strip().lower()
        model_severity = _normalize_severity(risk.get("severity"))
        if primary == "food" and model_severity != deterministic:
            severity_mismatches.append(
                {
                    "sim_minute": row.get("sim_minute"),
                    "deterministic_food_severity": deterministic,
                    "model_food_severity": model_severity,
                    "raw_model_severity": risk.get("severity"),
                    "food_backlog": _get(row, "before_digest.food_backlog"),
                    "food_eta_minutes": _get(row, "before_digest.food_eta_minutes"),
                    "selected_candidate_id": _get(row, "candidate_selection.selected_candidate_id")
                    or _get(row, "candidate_selection.fallback_candidate_id"),
                }
            )
        if deterministic in {"p0_gridlock", "p1_critical"} and primary != "food":
            missed_critical_food.append(
                {
                    "sim_minute": row.get("sim_minute"),
                    "deterministic_food_severity": deterministic,
                    "model_primary_risk": primary or "missing",
                    "raw_model_severity": risk.get("severity"),
                    "food_backlog": _get(row, "before_digest.food_backlog"),
                    "food_eta_minutes": _get(row, "before_digest.food_eta_minutes"),
                    "selected_candidate_id": _get(row, "candidate_selection.selected_candidate_id")
                    or _get(row, "candidate_selection.fallback_candidate_id"),
                }
            )
    issue_count = len(severity_mismatches) + len(missed_critical_food) + len(missing_risk_classification)
    return {
        "issue_count": issue_count,
        "food_severity_mismatch_count": len(severity_mismatches),
        "missed_critical_food_primary_risk_count": len(missed_critical_food),
        "missing_risk_classification_count": len(missing_risk_classification),
        "food_severity_mismatch_examples": severity_mismatches[:8],
        "missed_critical_food_examples": missed_critical_food[:8],
        "missing_risk_classification_examples": missing_risk_classification[:8],
        "release_expectation": "0 reasoning audit issues before release-clean promotion.",
    }


def _bias_audit(
    *,
    run_dir: Path,
    baseline_dir: Path | None,
    report: dict[str, Any],
    baseline_report: dict[str, Any],
    metrics: dict[str, Any],
    calls: list[dict[str, Any]],
) -> dict[str, Any]:
    run_config = report.get("run", {}) if isinstance(report.get("run"), dict) else {}
    baseline_config = baseline_report.get("run", {}) if isinstance(baseline_report.get("run"), dict) else {}
    candidate_mode = run_config.get("decision_mode")
    baseline_mode = baseline_config.get("decision_mode")
    action_mix = Counter(
        _action_key(row.get("allowed_action") if isinstance(row.get("allowed_action"), dict) else None)
        for row in calls
    )
    changed_simulator_assumption_risks = [
        {
            "risk": "stronger_food_levers_are_simulated_assumptions",
            "why_it_matters": "pause_mobile_order_intake, open_temp_pickup, and redeploy_food_certified have explicit backlog and ETA reductions inside the twin; real-world claims require calibration.",
        },
        {
            "risk": "candidate_scores_shape_model_behavior",
            "why_it_matters": "candidate scores guide Gemini ranking but are not the final evaluator; they can still steer the policy toward actions the simulator rewards.",
        },
    ]
    failed_calls = sum(1 for row in calls if row.get("status") != "success")
    executed_calls = sum(
        1
        for row in calls
        if isinstance(row.get("execution"), dict) and row["execution"].get("status") == "success"
    )
    claims = _operational_delta_claims(metrics)
    reasoning_audit = _llm_reasoning_audit(calls)
    tradeoff_ledger = _tradeoff_ledger(claims)
    return {
        "contract_fingerprint": _evaluation_contract()["fingerprint"],
        "scorecard_uses_same_metric_filter_for_baseline": bool(baseline_dir),
        "candidate_run_dir": str(run_dir),
        "baseline_run_dir": str(baseline_dir) if baseline_dir else None,
        "candidate_decision_mode": candidate_mode,
        "baseline_decision_mode": baseline_mode,
        "gemini_failure_count": failed_calls,
        "gemini_executed_action_count": executed_calls,
        "dominant_action": action_mix.most_common(1)[0][0] if action_mix else None,
        "llm_reasoning_audit": reasoning_audit,
        "tradeoff_ledger": tradeoff_ledger,
        "operational_delta_claims": claims,
        "metric_regressions": [
            claim
            for claim in claims
            if claim["avg_direction"] == "regressed" or claim["worst_direction"] == "regressed"
        ],
        "known_simulator_assumption_risks": changed_simulator_assumption_risks,
        "claim_boundary": "This scorecard supports simulator evidence only. It does not prove real park improvement without field calibration of action effects.",
    }


def _action_mix(calls: list[dict[str, Any]], field: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in calls:
        action = _model_action(row) if field == "model" else _executed_action(row)
        counter[_action_key(action)] += 1
    return dict(counter)


def _critical_ride_bypasses(calls: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    bypasses: list[dict[str, Any]] = []
    for row in calls:
        severity = _food_severity(row.get("before_digest", {}) if isinstance(row.get("before_digest"), dict) else {})
        if severity not in {"p0_gridlock", "p1_critical"}:
            continue
        action = _model_action(row) if field == "model" else _executed_action(row)
        if _action_key(action) == "ride/reroute":
            bypasses.append(row)
    return bypasses


def _food_increase_by_action(calls: list[dict[str, Any]], field: str) -> dict[str, dict[str, int]]:
    totals: Counter[str] = Counter()
    increases: Counter[str] = Counter()
    for row in calls:
        action = _model_action(row) if field == "model" else _executed_action(row)
        key = _action_key(action)
        totals[key] += 1
        before = _number(_get(row, "before_digest.food_backlog", 0))
        after = _number(_get(row, "after_digest.food_backlog", 0))
        if after > before:
            increases[key] += 1
    return {key: {"total": totals[key], "food_increased": increases[key]} for key in sorted(totals)}


def _candidate_relative(candidate: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        return {}
    counterfactual = candidate.get("counterfactual", {})
    if not isinstance(counterfactual, dict):
        return {}
    relative = counterfactual.get("relative_to_no_action", {})
    return relative if isinstance(relative, dict) else {}


def _selected_candidate_delta_rows(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    delta_keys = [
        "avg_satisfaction_delta",
        "slowest_ride_wait_delta",
        "food_backlog_delta",
        "food_eta_minutes_delta",
        "busiest_zone_density_delta",
        "path_congestion_delta",
        "open_callouts_delta",
        "grid_load_delta",
    ]
    for row in calls:
        candidate = row.get("selected_policy_candidate")
        if not isinstance(candidate, dict):
            continue
        relative = _candidate_relative(candidate)
        deltas = {key: _number(relative.get(key)) for key in delta_keys if key in relative}
        rows.append(
            {
                "sim_minute": row.get("sim_minute"),
                "action": _action_key(candidate),
                "selection_status": _get(row, "candidate_selection.status", "missing"),
                "score": candidate.get("score"),
                "relative_to_no_action": deltas,
            }
        )
    return rows


def _selected_candidate_delta_summary(calls: list[dict[str, Any]]) -> dict[str, Any]:
    rows = _selected_candidate_delta_rows(calls)
    grouped: dict[str, list[dict[str, float]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("action") or "none"), []).append(
            row.get("relative_to_no_action", {}) if isinstance(row.get("relative_to_no_action"), dict) else {}
        )
    action_rows: list[dict[str, Any]] = []
    for action, deltas in sorted(grouped.items()):
        def avg(key: str) -> float:
            values = [_number(item.get(key)) for item in deltas if key in item]
            return round(mean(values), 3) if values else 0.0

        action_rows.append(
            {
                "action": action,
                "count": len(deltas),
                "avg_satisfaction_delta": avg("avg_satisfaction_delta"),
                "avg_slowest_ride_wait_delta": avg("slowest_ride_wait_delta"),
                "avg_food_backlog_delta": avg("food_backlog_delta"),
                "avg_food_eta_minutes_delta": avg("food_eta_minutes_delta"),
                "avg_busiest_zone_density_delta": avg("busiest_zone_density_delta"),
                "avg_path_congestion_delta": avg("path_congestion_delta"),
                "avg_open_callouts_delta": avg("open_callouts_delta"),
                "avg_grid_load_delta": avg("grid_load_delta"),
            }
        )
    material_food_regressions = [
        row
        for row in rows
        if _number(_get(row, "relative_to_no_action.food_backlog_delta", 0)) > 25
        or _number(_get(row, "relative_to_no_action.food_eta_minutes_delta", 0)) > 2
    ]
    return {
        "row_count": len(rows),
        "material_food_regression_count": len(material_food_regressions),
        "action_summary": action_rows,
        "material_food_regression_examples": material_food_regressions[:8],
    }


def _max_action_streak(calls: list[dict[str, Any]], action_key: str, field: str) -> dict[str, Any]:
    best: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    for row in calls:
        action = _model_action(row) if field == "model" else _executed_action(row)
        if _action_key(action) == action_key:
            current.append(row)
            if len(current) > len(best):
                best = list(current)
        else:
            current = []
    return {
        "action": action_key,
        "count": len(best),
        "from_sim_minute": best[0].get("sim_minute") if best else None,
        "to_sim_minute": best[-1].get("sim_minute") if best else None,
    }


def _policy_score(final_critical_bypasses: int, override_count: int, max_reroute_streak: int, dominant_action_share: float) -> int:
    score = 100
    score -= final_critical_bypasses * POLICY_SCORE_WEIGHTS["final_critical_bypass_penalty"]
    score -= max(0, max_reroute_streak - 2) * POLICY_SCORE_WEIGHTS["reroute_streak_penalty_after_two"]
    score -= override_count * POLICY_SCORE_WEIGHTS["override_penalty"]
    score -= round(
        max(0.0, dominant_action_share - POLICY_SCORE_WEIGHTS["dominant_action_share_threshold"]) * 100
    )
    return max(0, min(100, score))


def evaluate_run(run_dir: Path, baseline_dir: Path | None = None) -> dict[str, Any]:
    tick_rows = _load_jsonl(run_dir / "tick-digests.jsonl")
    calls = _load_jsonl(run_dir / "gemini-operation-calls.jsonl")
    report = _load_json(run_dir / "one-day-cost-report.json")
    open_ticks = [row for row in tick_rows if _is_open(row)]

    baseline_ticks = _load_jsonl(baseline_dir / "tick-digests.jsonl") if baseline_dir else []
    baseline_report = _load_json(baseline_dir / "one-day-cost-report.json") if baseline_dir else {}
    baseline_open = [row for row in baseline_ticks if _is_open(row)]

    model_bypasses = _critical_ride_bypasses(calls, "model")
    final_bypasses = _critical_ride_bypasses(calls, "executed")
    policy_gates = Counter(
        (_get(row, "policy_gate.status") or "missing_policy_gate") for row in calls
    )
    candidate_selection_status = Counter(
        (_get(row, "candidate_selection.status") or "not_candidate_ranking") for row in calls
    )
    invalid_ranked_candidate_count = sum(
        len(_get(row, "candidate_selection.invalid_ranked_candidate_ids", []) or []) for row in calls
    )
    ranked_blocked_candidate_count = sum(
        len(_get(row, "candidate_selection.ranked_blocked_candidate_ids", []) or []) for row in calls
    )
    final_reroute_streak = _max_action_streak(calls, "ride/reroute", "executed")
    model_reroute_streak = _max_action_streak(calls, "ride/reroute", "model")
    final_action_mix = _action_mix(calls, "executed")
    dominant_action_count = max(final_action_mix.values(), default=0)
    dominant_action_share = round(dominant_action_count / max(1, len(calls)), 3)

    metrics: dict[str, Any] = {}
    for key in METRICS:
        current = _summarize_metric(open_ticks, key)
        entry: dict[str, Any] = {"current": current}
        if baseline_open:
            baseline = _summarize_metric(baseline_open, key)
            entry["baseline"] = baseline
            entry["delta"] = {
                "avg": _delta(current["avg"], baseline["avg"]),
                "worst": _delta(current["worst"], baseline["worst"]),
            }
        metrics[key] = entry

    severity_counts = Counter(
        _food_severity(row.get("before_digest", {}) if isinstance(row.get("before_digest"), dict) else {})
        for row in calls
    )
    reasoning_audit = _llm_reasoning_audit(calls)
    selected_candidate_deltas = _selected_candidate_delta_summary(calls)
    long_term_stability = _long_term_operating_stability(open_ticks, baseline_open, calls)
    override_count = int(policy_gates.get("overridden", 0))
    final_bypass_count = len(final_bypasses)
    score = _policy_score(final_bypass_count, override_count, int(final_reroute_streak["count"]), dominant_action_share)

    if final_bypass_count:
        decision = "NO_GO"
        reason = "critical food pressure can still execute ride/reroute"
    elif score < 80:
        decision = "GO_WITH_CONDITIONS"
        reason = "policy gates prevent critical bypasses, but action diversity or overrides still need tuning"
    else:
        decision = "GO_WITH_CONDITIONS" if baseline_open else "GO"
        reason = "hard policy gates are clean; compare operational tradeoffs before promotion" if baseline_open else "hard policy gates are clean"

    return {
        "run_dir": str(run_dir),
        "baseline_run_dir": str(baseline_dir) if baseline_dir else None,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "evaluation_contract": _evaluation_contract(),
        "run": {
            "tick_count": len(tick_rows),
            "open_tick_count": len(open_ticks),
            "gemini_call_count": len(calls),
            "closed_slots_skipped": _get(report, "run.llm_skipped_closed_slot_count", 0),
            "storage_mb": _get(report, "cost_estimate.storage_mb", 0),
            "estimated_day_cost_with_llm_usd": _get(report, "cost_estimate.estimated_total_usd_with_llm", 0),
            "projected_week_cost_with_llm_usd": _get(report, "projected_week_from_probe.estimated_total_usd_with_llm", 0),
        },
        "policy": {
            "score": score,
            "decision": decision,
            "reason": reason,
            "food_severity_counts_before_decision": dict(severity_counts),
            "model_critical_food_ride_bypass_count": len(model_bypasses),
            "final_critical_food_ride_bypass_count": final_bypass_count,
            "policy_gate_status_counts": dict(policy_gates),
            "candidate_selection_status_counts": dict(candidate_selection_status),
            "invalid_ranked_candidate_count": invalid_ranked_candidate_count,
            "ranked_blocked_candidate_count": ranked_blocked_candidate_count,
            "model_action_mix": _action_mix(calls, "model"),
            "final_action_mix": final_action_mix,
            "dominant_final_action_share": dominant_action_share,
            "model_max_ride_reroute_streak": model_reroute_streak,
            "final_max_ride_reroute_streak": final_reroute_streak,
            "food_increase_after_model_action": _food_increase_by_action(calls, "model"),
            "food_increase_after_final_action": _food_increase_by_action(calls, "executed"),
            "llm_reasoning_audit": reasoning_audit,
            "selected_candidate_delta_summary": selected_candidate_deltas,
        },
        "operational_metrics": metrics,
        "long_term_operating_stability": long_term_stability,
        "bias_audit": _bias_audit(
            run_dir=run_dir,
            baseline_dir=baseline_dir,
            report=report,
            baseline_report=baseline_report,
            metrics=metrics,
            calls=calls,
        ),
        "release_conditions": [
            "final_critical_food_ride_bypass_count must be 0",
            "closed-hour Gemini calls must remain 0 unless explicitly testing closed-phase policy",
            "final ride/reroute streak should stay <= 2 when food is warning or worse",
            "food backlog and ETA must not regress against baseline without an explicit executive tradeoff reason",
            "every override must record policy_gate.reason and selected/effective actions",
            "LLM reasoning audit issue_count must be 0 before release-clean promotion",
            "tradeoff_ledger.unresolved_count must be 0 before release-clean promotion",
            "long_term_operating_stability must be reviewed when satisfaction regresses but stability improves",
            "real-world claims require field calibration for each simulated action-effect constant",
        ],
    }


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def _html_table(rows: list[list[Any]], headers: list[str]) -> str:
    head = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(_fmt(cell))}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def render_html(scorecard: dict[str, Any], path: Path) -> None:
    policy = scorecard["policy"]
    run = scorecard["run"]
    contract = scorecard.get("evaluation_contract", {})
    bias = scorecard.get("bias_audit", {})
    reasoning = policy.get("llm_reasoning_audit", {})
    tradeoff_ledger = bias.get("tradeoff_ledger", {})
    selected_deltas = policy.get("selected_candidate_delta_summary", {})
    long_term = scorecard.get("long_term_operating_stability", {})
    metric_rows: list[list[Any]] = []
    for key, entry in scorecard["operational_metrics"].items():
        current = entry["current"]
        baseline = entry.get("baseline", {})
        delta = entry.get("delta", {})
        metric_rows.append(
            [
                key,
                current.get("avg"),
                current.get("worst"),
                baseline.get("avg", ""),
                baseline.get("worst", ""),
                delta.get("avg", ""),
                delta.get("worst", ""),
            ]
        )
    model_actions = [[key, value] for key, value in policy["model_action_mix"].items()]
    final_actions = [[key, value] for key, value in policy["final_action_mix"].items()]
    gate_rows = [[key, value] for key, value in policy["policy_gate_status_counts"].items()]
    claim_rows = [
        [
            claim.get("metric"),
            claim.get("avg_delta"),
            claim.get("avg_direction"),
            claim.get("worst_delta"),
            claim.get("worst_direction"),
        ]
        for claim in bias.get("operational_delta_claims", [])
        if isinstance(claim, dict)
    ]
    regression_rows = [
        [
            claim.get("metric"),
            claim.get("avg_delta"),
            claim.get("avg_direction"),
            claim.get("worst_delta"),
            claim.get("worst_direction"),
        ]
        for claim in bias.get("metric_regressions", [])
        if isinstance(claim, dict)
    ]
    reasoning_rows = [
        ["issue_count", reasoning.get("issue_count", 0)],
        ["food_severity_mismatch_count", reasoning.get("food_severity_mismatch_count", 0)],
        ["missed_critical_food_primary_risk_count", reasoning.get("missed_critical_food_primary_risk_count", 0)],
        ["missing_risk_classification_count", reasoning.get("missing_risk_classification_count", 0)],
    ]
    tradeoff_rows = [
        [
            item.get("metric"),
            item.get("avg_delta"),
            item.get("worst_delta"),
            item.get("tradeoff_status"),
        ]
        for item in tradeoff_ledger.get("entries", [])
        if isinstance(item, dict)
    ]
    selected_delta_rows = [
        [
            item.get("action"),
            item.get("count"),
            item.get("avg_satisfaction_delta"),
            item.get("avg_slowest_ride_wait_delta"),
            item.get("avg_food_backlog_delta"),
            item.get("avg_food_eta_minutes_delta"),
            item.get("avg_busiest_zone_density_delta"),
            item.get("avg_path_congestion_delta"),
        ]
        for item in selected_deltas.get("action_summary", [])
        if isinstance(item, dict)
    ]
    long_term_current = long_term.get("current", {}) if isinstance(long_term.get("current"), dict) else {}
    long_term_baseline = long_term.get("baseline", {}) if isinstance(long_term.get("baseline"), dict) else {}
    long_term_delta = long_term.get("delta", {}) if isinstance(long_term.get("delta"), dict) else {}
    action_load = long_term.get("candidate_action_load", {}) if isinstance(long_term.get("candidate_action_load"), dict) else {}
    long_term_rows = [
        [
            "stability_score",
            long_term_current.get("stability_score", ""),
            long_term_baseline.get("stability_score", ""),
            long_term_delta.get("stability_score", ""),
            "higher better",
        ],
        [
            "avg_operating_stress",
            long_term_current.get("avg_operating_stress", ""),
            long_term_baseline.get("avg_operating_stress", ""),
            long_term_delta.get("avg_operating_stress", ""),
            "lower better",
        ],
        [
            "recovery_gain",
            long_term_current.get("recovery_gain", ""),
            long_term_baseline.get("recovery_gain", ""),
            long_term_delta.get("recovery_gain", ""),
            "higher better",
        ],
        [
            "late_day_operating_stress",
            long_term_current.get("late_day_operating_stress", ""),
            long_term_baseline.get("late_day_operating_stress", ""),
            long_term_delta.get("late_day_operating_stress", ""),
            "lower better",
        ],
        [
            "severe_pressure_tick_count",
            long_term_current.get("severe_pressure_tick_count", ""),
            long_term_baseline.get("severe_pressure_tick_count", ""),
            long_term_delta.get("severe_pressure_tick_count", ""),
            "lower better",
        ],
        [
            "max_severe_pressure_streak",
            long_term_current.get("max_severe_pressure_streak", ""),
            long_term_baseline.get("max_severe_pressure_streak", ""),
            long_term_delta.get("max_severe_pressure_streak", ""),
            "lower better",
        ],
        [
            "stress_volatility",
            long_term_current.get("stress_volatility", ""),
            long_term_baseline.get("stress_volatility", ""),
            long_term_delta.get("stress_volatility", ""),
            "lower better",
        ],
    ]
    action_load_rows = [[key, value] for key, value in action_load.items()]
    conditions = "".join(f"<li>{html.escape(item)}</li>" for item in scorecard["release_conditions"])
    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>ParkPulse Timelapse Policy Scorecard</title>
<style>
body {{ margin: 0; font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #182230; }}
main {{ max-width: 1100px; margin: 0 auto; padding: 30px 22px 56px; }}
h1 {{ margin: 0 0 8px; font-size: 30px; }}
h2 {{ margin: 0 0 10px; font-size: 18px; }}
p {{ margin: 8px 0 0; color: #667085; }}
.stats {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 22px 0; }}
.stat, .card {{ border: 1px solid #d0d5dd; border-radius: 8px; padding: 16px; margin: 18px 0; background: #fff; }}
.stat {{ background: #f8fafc; margin: 0; }}
.stat b {{ display: block; font-size: 24px; margin-top: 4px; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ padding: 9px 10px; border-bottom: 1px solid #edf1f6; text-align: right; vertical-align: top; }}
th:first-child, td:first-child {{ text-align: left; }}
thead th {{ color: #667085; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
.grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
@media (max-width: 850px) {{ .stats, .grid {{ grid-template-columns: 1fr; }} table {{ font-size: 12px; }} }}
</style>
</head>
<body>
<main>
<h1>ParkPulse Timelapse Policy Scorecard</h1>
<p>{html.escape(scorecard["run_dir"])}</p>
<section class="stats">
  <div class="stat">Policy score<b>{policy["score"]}</b></div>
  <div class="stat">Decision<b>{html.escape(policy["decision"])}</b></div>
  <div class="stat">Critical bypasses<b>{policy["final_critical_food_ride_bypass_count"]}</b></div>
  <div class="stat">Week cost<b>${_fmt(run["projected_week_cost_with_llm_usd"])}</b></div>
</section>
<section class="card"><h2>Readout</h2><p>{html.escape(policy["reason"])}</p></section>
<section class="card"><h2>Evaluator Contract</h2><p>Version {html.escape(str(contract.get("version", "")))} / fingerprint {html.escape(str(contract.get("fingerprint", "")))}. Policy score is a compliance score, not an operational improvement score.</p></section>
<section class="card"><h2>Operational Metrics</h2>{_html_table(metric_rows, ["metric", "current avg", "current worst", "baseline avg", "baseline worst", "avg delta", "worst delta"])}</section>
<section class="card"><h2>Long-Term Operating Stability</h2><p>{html.escape(str(long_term.get("interpretation", "")))}</p>{_html_table(long_term_rows, ["metric", "current", "baseline", "delta", "direction"])}</section>
<section class="card"><h2>Candidate Action Load</h2>{_html_table(action_load_rows, ["metric", "value"])}</section>
<section class="card"><h2>Bias Audit</h2><p>{html.escape(str(bias.get("claim_boundary", "")))}</p>{_html_table(claim_rows, ["metric", "avg delta", "avg direction", "worst delta", "worst direction"])}</section>
<section class="card"><h2>LLM Reasoning Audit</h2>{_html_table(reasoning_rows, ["check", "count"])}</section>
<section class="card"><h2>Tradeoff Ledger</h2>{_html_table(tradeoff_rows, ["metric", "avg delta", "worst delta", "status"]) if tradeoff_rows else "<p>No unresolved tradeoffs detected.</p>"}</section>
<section class="card"><h2>Regressions</h2>{_html_table(regression_rows, ["metric", "avg delta", "avg direction", "worst delta", "worst direction"]) if regression_rows else "<p>No average or worst metric regression detected by this scorecard.</p>"}</section>
<section class="card"><h2>Selected Candidate Deltas</h2><p>Material food regression selections: {html.escape(_fmt(selected_deltas.get("material_food_regression_count", 0)))} / {html.escape(_fmt(selected_deltas.get("row_count", 0)))}.</p>{_html_table(selected_delta_rows, ["action", "count", "sat delta", "wait delta", "food backlog delta", "food ETA delta", "density delta", "path delta"]) if selected_delta_rows else "<p>No selected candidate delta records found.</p>"}</section>
<section class="grid">
  <div class="card"><h2>Model Action Mix</h2>{_html_table(model_actions, ["action", "count"])}</div>
  <div class="card"><h2>Final Action Mix</h2>{_html_table(final_actions, ["action", "count"])}</div>
</section>
<section class="card"><h2>Policy Gates</h2>{_html_table(gate_rows, ["status", "count"])}</section>
<section class="card"><h2>Release Conditions</h2><ul>{conditions}</ul></section>
</main>
</body>
</html>
"""
    path.write_text(doc, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a ParkPulse timelapse run against policy and outcome scorecards.")
    parser.add_argument("--run-dir", required=True, help="Timelapse run directory containing tick-digests.jsonl and one-day-cost-report.json.")
    parser.add_argument("--baseline-run-dir", help="Optional baseline run directory for outcome deltas.")
    parser.add_argument("--output-dir", help="Directory for scorecard artifacts.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    baseline_dir = Path(args.baseline_run_dir).expanduser().resolve() if args.baseline_run_dir else None
    if not run_dir.exists():
        raise SystemExit(f"run dir does not exist: {run_dir}")
    if baseline_dir and not baseline_dir.exists():
        raise SystemExit(f"baseline run dir does not exist: {baseline_dir}")

    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else DEFAULT_OUTPUT_ROOT / f"timelapse-policy-scorecard-{_now_id()}"
    output_dir.mkdir(parents=True, exist_ok=True)
    scorecard = evaluate_run(run_dir, baseline_dir)
    json_path = output_dir / "policy-scorecard.json"
    html_path = output_dir / "policy-scorecard.html"
    json_path.write_text(json.dumps(scorecard, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    render_html(scorecard, html_path)
    print(json.dumps({"status": "complete", "json": str(json_path), "html": str(html_path), "decision": scorecard["policy"]["decision"], "score": scorecard["policy"]["score"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
