#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
DEFAULT_CASE_BANK = REPO_ROOT / "output" / "qa" / "live-feed-case-bank" / "index.jsonl"
DEFAULT_PROGRESS_DIR = REPO_ROOT / "output" / "qa" / "sustainable-growth-progress"


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


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _latest_operating_report() -> Path:
    candidates = sorted(
        (REPO_ROOT / "output" / "qa").glob("operating-cycle-*/live-feed-operating-cycle.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError("No operating-cycle live-feed report JSON found under output/qa.")
    return candidates[0]


def _measurement(row: dict[str, Any]) -> dict[str, Any]:
    measurement = row.get("measurement", {})
    return measurement if isinstance(measurement, dict) else {}


def _issue(row: dict[str, Any]) -> dict[str, Any]:
    issue = row.get("issue", {})
    return issue if isinstance(issue, dict) else {}


def _memory(row: dict[str, Any]) -> dict[str, Any]:
    memory = row.get("memory", {})
    return memory if isinstance(memory, dict) else {}


def _reward(row: dict[str, Any]) -> float:
    measurement = _measurement(row)
    layers = measurement.get("reward_layers", {})
    if isinstance(layers, dict) and layers.get("operational_reward") not in {None, ""}:
        return round(_safe_float(layers.get("operational_reward")), 3)
    return round(_safe_float(measurement.get("reward_value")), 3)


def _promotion_eligible(row: dict[str, Any]) -> bool:
    measurement = _measurement(row)
    layers = measurement.get("reward_layers", {})
    return bool(measurement.get("promotion_eligible") or (isinstance(layers, dict) and layers.get("promotion_eligible")))


def _controlled_effect_applied(row: dict[str, Any]) -> bool:
    projection = _measurement(row).get("controlled_effect_projection", {})
    return isinstance(projection, dict) and projection.get("status") == "applied"


def _memory_applied(row: dict[str, Any]) -> bool:
    return _safe_int(_memory(row).get("applied_count")) > 0


def _scenario_from_issue(row: dict[str, Any]) -> str:
    issue = _issue(row)
    kind = str(issue.get("kind") or "").lower()
    target = str(issue.get("target_id") or issue.get("targetId") or "").lower()
    text = f"{kind} {target}"
    if any(term in text for term in ("food", "inventory", "mobile_order", "payment")):
        return "food_spike"
    if any(term in text for term in ("staff", "callout", "labor")):
        return "staff_shortage"
    if any(term in text for term in ("storm", "lightning", "heat", "weather")):
        return "storm_response"
    if any(term in text for term in ("ride", "coaster", "queue", "show_dump")):
        return "ride_down"
    if any(term in text for term in ("parade", "parking", "gate", "access_lane")):
        return "proactive_eventops"
    if any(term in text for term in ("sensor", "energy", "water_leak", "radio_dead_zone", "security", "restroom")):
        return "scan"
    return "unknown"


def _slice_metrics(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    rewards = [_reward(row) for row in rows if _reward(row) > 0]
    issue_kinds = {str(_issue(row).get("kind")) for row in rows if _issue(row).get("kind")}
    targets = {str(_issue(row).get("target_id") or _issue(row).get("targetId")) for row in rows if _issue(row).get("target_id") or _issue(row).get("targetId")}
    promotion_count = sum(1 for row in rows if _promotion_eligible(row))
    memory_count = sum(1 for row in rows if _memory_applied(row))
    effect_count = sum(1 for row in rows if _controlled_effect_applied(row))
    count = len(rows)
    return {
        "label": label,
        "case_count": count,
        "average_operational_reward": round(sum(rewards) / len(rewards), 3) if rewards else 0.0,
        "promotion_eligible_count": promotion_count,
        "promotion_eligible_ratio": round(promotion_count / count, 3) if count else 0.0,
        "issue_kind_count": len(issue_kinds),
        "target_count": len(targets),
        "memory_applied_ratio": round(memory_count / count, 3) if count else 0.0,
        "controlled_effect_projection_ratio": round(effect_count / count, 3) if count else 0.0,
    }


def _case_bank_scenario_view(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    minimum_source_cases = 8
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_scenario_from_issue(row), []).append(row)
    result: dict[str, dict[str, Any]] = {}
    for scenario, scenario_rows in sorted(grouped.items()):
        rewards = [_reward(row) for row in scenario_rows if _reward(row) > 0]
        split = max(1, len(rewards) // 2)
        first_avg = round(sum(rewards[:split]) / len(rewards[:split]), 3) if rewards[:split] else 0.0
        recent_rewards = rewards[-min(12, len(rewards)) :]
        recent_avg = round(sum(recent_rewards) / len(recent_rewards), 3) if recent_rewards else 0.0
        promotion_count = sum(1 for row in scenario_rows if _promotion_eligible(row))
        promotion_ratio = round(promotion_count / len(scenario_rows), 3) if scenario_rows else 0.0
        status = (
            "strong"
            if len(scenario_rows) >= minimum_source_cases and recent_avg >= 0.55 and promotion_ratio >= 0.25
            else "watch"
            if recent_avg >= 0.52
            else "weak"
        )
        result[scenario] = {
            "source": "case_bank_live_feed",
            "scenario_key": scenario,
            "case_count": len(scenario_rows),
            "average_reward": round(sum(rewards) / len(rewards), 3) if rewards else 0.0,
            "recent_average_reward": recent_avg,
            "curve_delta": round(recent_avg - first_avg, 3),
            "promotion_eligible_count": promotion_count,
            "promotion_eligible_ratio": promotion_ratio,
            "status": status,
            "decision": "case_bank_supports_growth" if status == "strong" else "case_bank_watch" if status == "watch" else "case_bank_weak",
            "minimum_source_cases": minimum_source_cases,
        }
    return result


def _case_bank_curve(rows: list[dict[str, Any]]) -> dict[str, Any]:
    windows = [10, 20, 30, 40, 50]
    cumulative = [_slice_metrics(rows[:size], f"first_{size}") for size in windows if len(rows) >= size]
    if rows:
        cumulative.append(_slice_metrics(rows, f"current_{len(rows)}"))
    tail_sizes = [5, 12, 25]
    recent = [_slice_metrics(rows[-size:], f"latest_{size}") for size in tail_sizes if len(rows) >= size]
    return {
        "cumulative": cumulative,
        "recent": recent,
        "latest_rewards": [_reward(row) for row in rows[-12:]],
        "latest_promotion_flags": [_promotion_eligible(row) for row in rows[-12:]],
    }


def _actual_training_summary(report: dict[str, Any]) -> dict[str, Any]:
    actual = report.get("actual_training", {}) if isinstance(report.get("actual_training"), dict) else {}
    model_ops = actual.get("model_ops", {}) if isinstance(actual.get("model_ops"), dict) else {}
    promotion_gate = model_ops.get("promotion_gate", {}) if isinstance(model_ops.get("promotion_gate"), dict) else {}
    fitness = model_ops.get("fitness_curve", {}) if isinstance(model_ops.get("fitness_curve"), dict) else {}
    scenario_fitness = model_ops.get("scenario_fitness", {}) if isinstance(model_ops.get("scenario_fitness"), dict) else {}
    points = fitness.get("points", []) if isinstance(fitness.get("points"), list) else []
    return {
        "status": actual.get("status"),
        "source": actual.get("source"),
        "sample_count": actual.get("sample_count"),
        "promotion_gate_status": promotion_gate.get("status"),
        "promotion_gate_decision": promotion_gate.get("decision"),
        "curve_delta": promotion_gate.get("curve_delta", fitness.get("delta")),
        "first_average_reward": fitness.get("first_average_reward"),
        "latest_average_reward": fitness.get("latest_average_reward"),
        "latest_reward": fitness.get("latest_reward"),
        "point_count": fitness.get("point_count", len(points)),
        "recent_points": points[-6:],
        "label_quality": scenario_fitness.get("label_quality", {}),
        "scenario_balanced_latest_average_reward": scenario_fitness.get("balanced_latest_average_reward"),
    }


def _scenario_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    actual = report.get("actual_training", {}) if isinstance(report.get("actual_training"), dict) else {}
    model_ops = actual.get("model_ops", {}) if isinstance(actual.get("model_ops"), dict) else {}
    scenario_fitness = model_ops.get("scenario_fitness", [])
    if isinstance(scenario_fitness, list):
        rows = scenario_fitness
    elif isinstance(scenario_fitness, dict):
        scenarios = scenario_fitness.get("scenarios")
        if isinstance(scenarios, list):
            rows = scenarios
        else:
            rows = []
            for key in ("promotable_slices", "held_slices", "thin_slices"):
                slice_rows = scenario_fitness.get(key, [])
                if isinstance(slice_rows, list):
                    rows.extend(row for row in slice_rows if isinstance(row, dict))
    else:
        rows = []
    cleaned: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        cleaned.append(
            {
                "scenario_key": row.get("scenario_key"),
                "status": row.get("status"),
                "decision": row.get("decision"),
                "sample_count": row.get("sample_count"),
                "minimum_sample_count": row.get("minimum_sample_count"),
                "latest_average_reward": row.get("latest_average_reward"),
                "latest_reward": row.get("latest_reward"),
                "curve_delta": row.get("curve_delta"),
                "reason": row.get("reason"),
            }
        )
    return cleaned


def _training_scenario_view(report: dict[str, Any], source_label: str | None = None) -> dict[str, dict[str, Any]]:
    actual = report.get("actual_training", {}) if isinstance(report.get("actual_training"), dict) else {}
    source = str(source_label or actual.get("source") or "actual_training")
    result: dict[str, dict[str, Any]] = {}
    for row in _scenario_rows(report):
        scenario = str(row.get("scenario_key") or "unknown")
        decision = str(row.get("decision") or "")
        latest = _safe_float(row.get("latest_average_reward"))
        delta = _safe_float(row.get("curve_delta"))
        status = "strong" if decision == "promote_slice" else "watch" if decision == "collect_more_evidence" else "weak"
        result[scenario] = {
            "source": source,
            "scenario_key": scenario,
            "case_count": row.get("sample_count"),
            "average_reward": latest,
            "recent_average_reward": latest,
            "curve_delta": delta,
            "promotion_eligible_count": None,
            "promotion_eligible_ratio": None,
            "status": status,
            "decision": decision,
            "reason": row.get("reason"),
        }
    return result


def _source_reconciliation(report: dict[str, Any], case_rows: list[dict[str, Any]]) -> dict[str, Any]:
    source_views: dict[str, dict[str, dict[str, Any]]] = {
        "case_bank_live_feed": _case_bank_scenario_view(case_rows),
    }
    active_source_names = {"case_bank_live_feed"}
    historical_source_names: set[str] = set()
    original = report.get("source_reconciliation", {}) if isinstance(report.get("source_reconciliation"), dict) else {}
    original_actual = original.get("operating_report_actual_training") if isinstance(original.get("operating_report_actual_training"), dict) else None
    refreshed_actual = original.get("refreshed_actual_training") if isinstance(original.get("refreshed_actual_training"), dict) else None
    if original_actual:
        source_views["operating_report_actual_training"] = _training_scenario_view({"actual_training": original_actual}, str(original_actual.get("source") or "operating_report_actual_training"))
        historical_source_names.add("operating_report_actual_training")
    else:
        source_views["operating_report_actual_training"] = _training_scenario_view(report, str((_actual_training_summary(report).get("source") or "operating_report_actual_training")))
        active_source_names.add("operating_report_actual_training")
    if refreshed_actual:
        source_views["refreshed_actual_training"] = _training_scenario_view({"actual_training": refreshed_actual}, str(refreshed_actual.get("source") or "refreshed_actual_training"))
        active_source_names.add("refreshed_actual_training")
    scenarios = sorted({scenario for view in source_views.values() for scenario in view})
    rows: list[dict[str, Any]] = []
    conflicts = 0
    for scenario in scenarios:
        cells = {name: view.get(scenario) for name, view in source_views.items() if view.get(scenario)}
        active_cells = {name: cell for name, cell in cells.items() if name in active_source_names}
        historical_cells = {name: cell for name, cell in cells.items() if name in historical_source_names}
        statuses = {str(cell.get("status")) for cell in active_cells.values() if isinstance(cell, dict)}
        decisions = {str(cell.get("decision")) for cell in active_cells.values() if isinstance(cell, dict)}
        all_statuses = {str(cell.get("status")) for cell in cells.values() if isinstance(cell, dict)}
        all_decisions = {str(cell.get("decision")) for cell in cells.values() if isinstance(cell, dict)}
        has_strong = "strong" in statuses
        has_weak = "weak" in statuses
        conflict = has_strong and has_weak
        historical_drift = bool(historical_cells) and bool(active_cells) and any(
            str(historical.get("status")) not in statuses
            for historical in historical_cells.values()
            if isinstance(historical, dict)
        )
        conflict_priority = 0
        if conflict and "hold_slice" in decisions and has_strong:
            conflict_priority = 3
        elif conflict and "hold_slice" in decisions:
            conflict_priority = 2
        elif conflict:
            conflict_priority = 1
        if conflict:
            conflicts += 1
        if conflict:
            decision = "hold_source_conflicted_slice"
            next_action = "Reconcile source labels/rewards before promotion; compare live-feed case-bank outcomes against heartbeat and exported training rows."
        elif has_weak:
            decision = "repair_weak_slice"
            next_action = _next_action({"scenario_key": scenario, "decision": "hold_slice"})
        elif has_strong and statuses == {"strong"}:
            decision = "candidate_consistent_growth"
            next_action = "Keep collecting measured outcomes and require rollback monitoring before promotion."
        elif has_strong:
            decision = "candidate_needs_more_current_evidence"
            next_action = "Current sources do not conflict, but at least one source is still thin; collect measured rows before promotion."
        else:
            decision = "collect_more_source_evidence"
            next_action = "Collect enough measured rows across sources before promotion."
        rows.append(
            {
                "scenario_key": scenario,
                "source_count": len(cells),
                "statuses": sorted(statuses),
                "decisions": sorted(decisions),
                "all_statuses_including_history": sorted(all_statuses),
                "all_decisions_including_history": sorted(all_decisions),
                "conflict": conflict,
                "active_conflict": conflict,
                "historical_drift": historical_drift,
                "conflict_priority": conflict_priority,
                "reconciled_decision": decision,
                "next_action": next_action,
                "active_source_names": sorted(active_source_names),
                "historical_source_names": sorted(historical_source_names),
                "sources": cells,
            }
        )
    rows.sort(key=lambda row: (bool(row.get("conflict")), _safe_int(row.get("conflict_priority")), str(row.get("scenario_key"))), reverse=True)
    return {
        "mode": "source_consistent_learning_reconciliation",
        "source_names": sorted(source_views.keys()),
        "active_source_names": sorted(active_source_names),
        "historical_source_names": sorted(historical_source_names),
        "scenario_count": len(rows),
        "conflict_count": conflicts,
        "promotion_boundary": "A slice cannot be promoted when current active observed-outcome sources disagree. Historical operating snapshots are retained as drift evidence, not as the current promotion gate.",
        "rows": rows,
    }


def _next_action(row: dict[str, Any]) -> str:
    key = str(row.get("scenario_key") or "")
    decision = str(row.get("decision") or "")
    sample_count = _safe_int(row.get("sample_count"))
    minimum = _safe_int(row.get("minimum_sample_count"), 12)
    missing = max(0, minimum - sample_count)
    if key == "ride_down":
        return "Improve ride-down negotiation: compare reopen, route, staffing, and guest-message options against queue pressure and safety gates before approving bounded receiver actions."
    if key == "staff_shortage":
        return "Improve Labor/HR reasoning: use skill matrix, fatigue risk, break timing, and overtime constraints to produce narrow shift moves with clear owners."
    if key == "food_spike":
        return "Stabilize Commerce decisions: separate restock, promo pause, and labor help, then score backlog/ETA deltas instead of treating every food action as equal."
    if key == "storm_response":
        return "Repair storm-response reward consistency: compare local heartbeat labels against BigQuery outcomes before promoting or demoting this slice."
    if key == "unknown":
        return "Classify unknown rows before training: map them to a scenario or quarantine them as eval-only so they do not hide weak policy behavior."
    if "proactive" in key and missing:
        return f"Collect {missing} more outcome rows for this high-potential slice before promotion."
    if decision == "collect_more_evidence" and missing:
        return f"Collect {missing} more measured outcome rows before judging this slice."
    if decision == "promote_slice":
        return "Keep as promoted slice, but continue rollback monitoring."
    return "Review slice-specific reward and policy features before adding more generic cases."


def _priority_score(row: dict[str, Any]) -> float:
    decision = str(row.get("decision") or "")
    latest = _safe_float(row.get("latest_average_reward"))
    delta = _safe_float(row.get("curve_delta"))
    sample_count = _safe_int(row.get("sample_count"))
    minimum = _safe_int(row.get("minimum_sample_count"), 12)
    if decision == "promote_slice":
        return 0.0
    if decision == "hold_slice":
        return 100.0 + min(sample_count, 120) / 4.0 + max(0.0, -delta) + max(0.0, 55.0 - latest) * 2.0
    if decision == "collect_more_evidence":
        return 60.0 + max(0, minimum - sample_count) * 2.0 + max(0.0, latest - 55.0) / 2.0
    return 40.0


def _priority_backlog(scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    backlog: list[dict[str, Any]] = []
    for row in scenarios:
        item = dict(row)
        item["priority_score"] = round(_priority_score(row), 2)
        item["next_action"] = _next_action(row)
        backlog.append(item)
    return sorted(backlog, key=lambda item: item["priority_score"], reverse=True)


def _latest_cycle_summary(report: dict[str, Any]) -> dict[str, Any]:
    cycles = report.get("cycles", []) if isinstance(report.get("cycles"), list) else []
    latest = cycles[-1] if cycles else {}
    if not isinstance(latest, dict):
        latest = {}
    issue = latest.get("issue", {}) if isinstance(latest.get("issue"), dict) else {}
    agents = latest.get("agents", {}) if isinstance(latest.get("agents"), dict) else {}
    actions = latest.get("actions", {}) if isinstance(latest.get("actions"), dict) else {}
    memory = latest.get("memory", {}) if isinstance(latest.get("memory"), dict) else {}
    measurement = latest.get("measurement", {}) if isinstance(latest.get("measurement"), dict) else {}
    reward_layers = measurement.get("reward_layers", {}) if isinstance(measurement.get("reward_layers"), dict) else {}
    return {
        "issue_kind": issue.get("kind"),
        "target_id": issue.get("target_id"),
        "executed_count": actions.get("executed_count"),
        "held_count": actions.get("held_count"),
        "unresolved_without_owner_count": actions.get("unresolved_without_owner_count"),
        "negotiation_round_count": agents.get("negotiation_round_count"),
        "memory_applied_count": memory.get("applied_count"),
        "reward_value": measurement.get("reward_value"),
        "operational_reward": reward_layers.get("operational_reward", measurement.get("reward_value")),
        "promotion_eligible": measurement.get("promotion_eligible"),
    }


def _build_record(report: dict[str, Any], case_rows: list[dict[str, Any]], operating_report_path: Path) -> dict[str, Any]:
    scenarios = _scenario_rows(report)
    case_curve = _case_bank_curve(case_rows)
    backlog = _priority_backlog(scenarios)
    reconciliation = _source_reconciliation(report, case_rows)
    conflict_rows = [row for row in reconciliation.get("rows", []) if isinstance(row, dict) and row.get("conflict")]
    latest_recent = case_curve["recent"][1] if len(case_curve["recent"]) > 1 else (case_curve["recent"][0] if case_curve["recent"] else {})
    cumulative = case_curve["cumulative"][-1] if case_curve["cumulative"] else {}
    return {
        "created_at": _now_iso(),
        "mode": "sustainable_growth_improvement_curve_record",
        "source_report": str(operating_report_path),
        "case_bank_path": str(DEFAULT_CASE_BANK),
        "summary": {
            "case_count": len(case_rows),
            "actual_training_source": _actual_training_summary(report).get("source"),
            "current_average_operational_reward": cumulative.get("average_operational_reward"),
            "recent_average_operational_reward": latest_recent.get("average_operational_reward"),
            "promotion_eligible_count": cumulative.get("promotion_eligible_count"),
            "promotion_eligible_ratio": cumulative.get("promotion_eligible_ratio"),
            "recent_promotion_eligible_ratio": latest_recent.get("promotion_eligible_ratio"),
            "held_slice_count": sum(1 for row in scenarios if row.get("decision") == "hold_slice"),
            "thin_slice_count": sum(1 for row in scenarios if row.get("decision") == "collect_more_evidence"),
            "promotable_slice_count": sum(1 for row in scenarios if row.get("decision") == "promote_slice"),
            "source_conflict_count": reconciliation.get("conflict_count"),
            "source_consistent_promotion_ready": reconciliation.get("conflict_count") == 0 and sum(1 for row in scenarios if row.get("decision") == "hold_slice") == 0,
            "top_priority_slice": conflict_rows[0].get("scenario_key") if conflict_rows else backlog[0].get("scenario_key") if backlog else None,
            "top_priority_action": conflict_rows[0].get("next_action") if conflict_rows else backlog[0].get("next_action") if backlog else None,
        },
        "case_bank_curve": case_curve,
        "actual_training_curve": _actual_training_summary(report),
        "scenario_slices": scenarios,
        "source_reconciliation": reconciliation,
        "priority_backlog": backlog,
        "latest_cycle": _latest_cycle_summary(report),
        "recorded_boundary": [
            "This records app live-state simulation outcomes, not an external park feed.",
            "It does not retrain on every case. It records enough case history for later batch training and guarded slice promotion.",
            "Held slices are not unresolved; each has an owner-style next action and remains blocked from promotion until the curve recovers.",
        ],
    }


def _compact_actual_training_for_report(actual_training: dict[str, Any]) -> dict[str, Any]:
    model_ops = actual_training.get("model_ops", {}) if isinstance(actual_training.get("model_ops"), dict) else {}
    return {
        "status": actual_training.get("status"),
        "mode": actual_training.get("mode"),
        "detail": actual_training.get("detail", "full"),
        "source": actual_training.get("source"),
        "sample_count": actual_training.get("sample_count"),
        "min_sample_count": actual_training.get("min_sample_count"),
        "uses_generated_data": actual_training.get("uses_generated_data"),
        "model_ops": {
            "version": model_ops.get("version"),
            "current_policy_id": model_ops.get("current_policy_id"),
            "promotion_gate": model_ops.get("promotion_gate"),
            "fitness_curve": model_ops.get("fitness_curve"),
            "scenario_fitness": model_ops.get("scenario_fitness"),
            "offline_training_path": model_ops.get("offline_training_path"),
        },
    }


def _refresh_actual_training(report: dict[str, Any], min_training_rows: int, detail: str) -> dict[str, Any]:
    from park_actual_training import actual_training_status

    refreshed = dict(report)
    original_actual = report.get("actual_training", {}) if isinstance(report.get("actual_training"), dict) else {}
    refreshed_actual = _compact_actual_training_for_report(actual_training_status(min_rows=min_training_rows, run_gcp_training=False, detail=detail))
    refreshed["actual_training"] = refreshed_actual
    refreshed["actual_training_refreshed_at"] = _now_iso()
    refreshed["source_reconciliation"] = {
        "operating_report_actual_training": original_actual,
        "refreshed_actual_training": refreshed_actual,
        "refresh_detail": detail,
        "refresh_min_training_rows": min_training_rows,
        "policy": "Keep both snapshots so source disagreement is visible and promotion can be held until reconciled.",
    }
    return refreshed


def _badge(value: Any) -> str:
    text = html.escape(str(value))
    normalized = str(value).lower()
    cls = "ok" if normalized in {"promote_slice", "promotable", "ready", "true"} else "warn" if normalized in {"hold_slice", "hold", "needs_more_data", "collect_more_evidence", "false"} else "muted"
    return f'<span class="badge {cls}">{text}</span>'


def _render_metric_card(label: str, value: Any, note: str) -> str:
    return f"<div><strong>{html.escape(label)}</strong><span>{html.escape(str(value))}</span><small>{html.escape(note)}</small></div>"


def _render_curve_table(rows: list[dict[str, Any]]) -> str:
    body = "".join(
        f"""
        <tr>
          <td>{html.escape(str(row.get('label')))}</td>
          <td>{html.escape(str(row.get('case_count')))}</td>
          <td>{html.escape(str(row.get('average_operational_reward')))}</td>
          <td>{html.escape(str(row.get('promotion_eligible_count')))} ({html.escape(str(row.get('promotion_eligible_ratio')) )})</td>
          <td>{html.escape(str(row.get('issue_kind_count')))}</td>
          <td>{html.escape(str(row.get('memory_applied_ratio')))}</td>
        </tr>
        """
        for row in rows
    )
    return f"""
    <table>
      <thead><tr><th>Window</th><th>Cases</th><th>Avg Op Reward</th><th>Promo Eligible</th><th>Issue Kinds</th><th>Memory Ratio</th></tr></thead>
      <tbody>{body}</tbody>
    </table>
    """


def _render_backlog_table(rows: list[dict[str, Any]]) -> str:
    body = "".join(
        f"""
        <tr>
          <td>{html.escape(str(row.get('scenario_key')))}</td>
          <td>{_badge(row.get('decision'))}</td>
          <td>{html.escape(str(row.get('sample_count')))}</td>
          <td>{html.escape(str(row.get('latest_average_reward')))}</td>
          <td>{html.escape(str(row.get('curve_delta')))}</td>
          <td>{html.escape(str(row.get('priority_score')))}</td>
          <td>{html.escape(str(row.get('next_action')))}</td>
        </tr>
        """
        for row in rows
    )
    return f"""
    <table>
      <thead><tr><th>Slice</th><th>Decision</th><th>Rows</th><th>Latest Avg</th><th>Delta</th><th>Priority</th><th>Next Action</th></tr></thead>
      <tbody>{body}</tbody>
    </table>
    """


def _source_cell(cell: dict[str, Any] | None) -> str:
    if not isinstance(cell, dict):
        return '<span class="badge muted">missing</span>'
    reward = cell.get("recent_average_reward", cell.get("average_reward"))
    detail = f"{cell.get('status')} / {cell.get('decision')}"
    count = cell.get("case_count")
    return (
        f"{_badge(cell.get('status'))}"
        f"<small>{html.escape(str(detail))}<br>rows {html.escape(str(count))}; reward {html.escape(str(reward))}; delta {html.escape(str(cell.get('curve_delta')))}</small>"
    )


def _render_reconciliation_table(reconciliation: dict[str, Any]) -> str:
    rows = reconciliation.get("rows", []) if isinstance(reconciliation.get("rows"), list) else []
    body = "".join(
        f"""
        <tr>
          <td>{html.escape(str(row.get('scenario_key')))}</td>
          <td>{_badge('conflict' if row.get('conflict') else 'aligned')}</td>
          <td>{_source_cell((row.get('sources', {}) if isinstance(row.get('sources'), dict) else {}).get('case_bank_live_feed'))}</td>
          <td>{_source_cell((row.get('sources', {}) if isinstance(row.get('sources'), dict) else {}).get('operating_report_actual_training'))}</td>
          <td>{_source_cell((row.get('sources', {}) if isinstance(row.get('sources'), dict) else {}).get('refreshed_actual_training'))}</td>
          <td>{html.escape(str(row.get('reconciled_decision')))}<small>{html.escape(str(row.get('next_action')))}</small></td>
        </tr>
        """
        for row in rows
    )
    return f"""
    <table>
      <thead><tr><th>Slice</th><th>Status</th><th>Case Bank</th><th>Report Training</th><th>Refreshed Training</th><th>Reconciled Decision</th></tr></thead>
      <tbody>{body}</tbody>
    </table>
    """


def _render_html(record: dict[str, Any], path: Path) -> None:
    summary = record.get("summary", {}) if isinstance(record.get("summary"), dict) else {}
    curve = record.get("case_bank_curve", {}) if isinstance(record.get("case_bank_curve"), dict) else {}
    actual = record.get("actual_training_curve", {}) if isinstance(record.get("actual_training_curve"), dict) else {}
    latest = record.get("latest_cycle", {}) if isinstance(record.get("latest_cycle"), dict) else {}
    backlog = record.get("priority_backlog", []) if isinstance(record.get("priority_backlog"), list) else []
    reconciliation = record.get("source_reconciliation", {}) if isinstance(record.get("source_reconciliation"), dict) else {}
    label_quality = actual.get("label_quality", {}) if isinstance(actual.get("label_quality"), dict) else {}
    boundaries = record.get("recorded_boundary", []) if isinstance(record.get("recorded_boundary"), list) else []
    boundary_items = "".join(f"<li>{html.escape(str(item))}</li>" for item in boundaries)
    recent_rewards = ", ".join(str(value) for value in curve.get("latest_rewards", []))
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ParkPulse Sustainable Growth Progress</title>
  <style>
    :root {{
      --ink: #17212b;
      --muted: #607080;
      --line: #d8e0e7;
      --panel: #f7fafb;
      --ok: #0b7651;
      --warn: #9f6200;
      --accent: #245d7a;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; color: var(--ink); background: #fff; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    header {{ padding: 30px 40px 22px; border-bottom: 1px solid var(--line); }}
    main {{ padding: 24px 40px 44px; }}
    h1 {{ margin: 0 0 8px; font-size: 30px; line-height: 1.12; letter-spacing: 0; }}
    h2 {{ margin: 0 0 12px; font-size: 18px; letter-spacing: 0; }}
    p {{ margin: 0; line-height: 1.5; color: var(--muted); max-width: 1040px; }}
    section {{ margin-top: 26px; }}
    .grid {{ display: grid; gap: 12px; grid-template-columns: repeat(4, minmax(0, 1fr)); }}
    .grid > div {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px; min-height: 98px; }}
    strong {{ display: block; color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0; margin-bottom: 8px; }}
    span {{ display: block; font-size: 22px; font-weight: 750; line-height: 1.18; }}
    small {{ display: block; color: var(--muted); margin-top: 8px; line-height: 1.35; }}
    table {{ width: 100%; border-collapse: collapse; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }}
    th, td {{ padding: 10px 12px; text-align: left; vertical-align: top; border-bottom: 1px solid var(--line); font-size: 14px; }}
    th {{ color: var(--muted); background: #f2f6f8; font-size: 12px; text-transform: uppercase; letter-spacing: 0; }}
    tr:last-child td {{ border-bottom: 0; }}
    .badge {{ display: inline-flex; width: fit-content; border-radius: 999px; padding: 4px 8px; border: 1px solid var(--line); font-size: 12px; font-weight: 700; }}
    .badge.ok {{ color: var(--ok); background: #e9f8f1; border-color: #bde9d6; }}
    .badge.warn {{ color: var(--warn); background: #fff5df; border-color: #ecd39f; }}
    .badge.muted {{ color: var(--muted); background: #f4f6f8; }}
    .note {{ border: 1px solid var(--line); border-radius: 8px; padding: 14px; background: #fbfcfd; }}
    ul {{ margin: 8px 0 0; padding-left: 20px; color: #293847; }}
    li {{ margin: 6px 0; }}
    code {{ background: #eef3f6; padding: 1px 4px; border-radius: 4px; }}
    @media (max-width: 960px) {{ header, main {{ padding-left: 18px; padding-right: 18px; }} .grid {{ grid-template-columns: 1fr; }} table {{ display: block; overflow-x: auto; }} }}
  </style>
</head>
<body>
  <header>
    <h1>Sustainable Growth Progress</h1>
    <p>This is the recorded improvement curve for the multi-agent operating loop. It separates overall case-bank health from scenario-slice promotion, so weak slices are visible instead of hidden by aggregate readiness.</p>
  </header>
  <main>
    <section class="grid">
      {_render_metric_card("Cases recorded", summary.get("case_count"), "Append-only case bank rows used for the curve.")}
      {_render_metric_card("Current avg reward", summary.get("current_average_operational_reward"), "All reward-vector cases.")}
      {_render_metric_card("Recent avg reward", summary.get("recent_average_operational_reward"), "Latest operating window.")}
      {_render_metric_card("Top priority", summary.get("top_priority_slice"), str(summary.get("top_priority_action") or ""))}
    </section>

    <section>
      <h2>Case-Bank Curve</h2>
      {_render_curve_table(curve.get("cumulative", []) if isinstance(curve.get("cumulative"), list) else [])}
    </section>

    <section>
      <h2>Recent Window</h2>
      {_render_curve_table(curve.get("recent", []) if isinstance(curve.get("recent"), list) else [])}
      <div class="note" style="margin-top: 12px;"><strong>Latest 12 rewards</strong><p>{html.escape(recent_rewards)}</p></div>
    </section>

    <section>
      <h2>Actual Training Curve</h2>
      <div class="grid">
        {_render_metric_card("Training rows", actual.get("sample_count"), f"Status {actual.get('status')}; source {actual.get('source')}")}
        {_render_metric_card("Latest avg", actual.get("latest_average_reward"), f"Latest reward {actual.get('latest_reward')}")}
        {_render_metric_card("Curve delta", actual.get("curve_delta"), "Global curve is not the promotion decision by itself.")}
        {_render_metric_card("Promotion gate", actual.get("promotion_gate_decision"), f"Gate status {actual.get('promotion_gate_status')}")}
      </div>
      <div class="note" style="margin-top: 12px;"><strong>Label quality</strong><p>Unknown quarantined rows: {html.escape(str(label_quality.get('unknown_quarantined_count', 0)))}. {html.escape(str(label_quality.get('policy') or 'No label-quality policy reported.'))}</p></div>
    </section>

    <section>
      <h2>Source Reconciliation</h2>
      <div class="grid">
        {_render_metric_card("Source conflicts", reconciliation.get("conflict_count"), str(reconciliation.get("promotion_boundary") or ""))}
        {_render_metric_card("Sources compared", len(reconciliation.get("source_names", []) if isinstance(reconciliation.get("source_names"), list) else []), ", ".join(str(item) for item in reconciliation.get("source_names", []) if isinstance(reconciliation.get("source_names"), list)))}
        {_render_metric_card("Scenarios", reconciliation.get("scenario_count"), "Promotion requires source-consistent slice evidence.")}
        {_render_metric_card("Ready", summary.get("source_consistent_promotion_ready"), "False means keep learning but do not promote globally.")}
      </div>
      <div style="margin-top: 12px;">{_render_reconciliation_table(reconciliation)}</div>
    </section>

    <section>
      <h2>Slice Backlog</h2>
      {_render_backlog_table(backlog)}
    </section>

    <section>
      <h2>Latest Cycle Evidence</h2>
      <div class="grid">
        {_render_metric_card("Issue", f"{latest.get('issue_kind')} / {latest.get('target_id')}", "Generated against current app live-state simulation.")}
        {_render_metric_card("Agent negotiation", latest.get("negotiation_round_count"), f"Memory applied {latest.get('memory_applied_count')}")}
        {_render_metric_card("Actions", f"{latest.get('executed_count')} executed", f"{latest.get('held_count')} held, {latest.get('unresolved_without_owner_count')} ownerless")}
        {_render_metric_card("Reward", latest.get("operational_reward"), f"Promotion eligible {latest.get('promotion_eligible')}")}
      </div>
    </section>

    <section>
      <h2>Recorded Boundary</h2>
      <div class="note"><ul>{boundary_items}</ul></div>
    </section>

    <section>
      <h2>Artifact</h2>
      <div class="note">
        <p>JSON: <code>{html.escape(str(path.with_suffix('.json')))}</code></p>
        <p>Ledger: <code>{html.escape(str(path.parent / 'ledger.jsonl'))}</code></p>
      </div>
    </section>
  </main>
</body>
</html>
"""
    path.write_text(html_doc, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Record ParkPulse sustainable-growth improvement curve and scenario backlog.")
    parser.add_argument("--operating-report", type=Path, default=None, help="Path to live-feed-operating-cycle.json. Defaults to newest operating-cycle report.")
    parser.add_argument("--case-bank", type=Path, default=DEFAULT_CASE_BANK, help="Path to live-feed case-bank index.jsonl.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_PROGRESS_DIR, help="Directory for improvement-curve artifacts.")
    parser.add_argument("--refresh-actual-training", action="store_true", help="Recompute actual-training diagnostics before recording, without generating a new operating case.")
    parser.add_argument("--min-training-rows", type=int, default=50, help="Minimum observed rows for refreshed actual-training diagnostics.")
    parser.add_argument("--training-detail", choices=["readiness", "full"], default="full", help="Actual-training detail level when refreshing diagnostics.")
    args = parser.parse_args()

    operating_report = args.operating_report or _latest_operating_report()
    case_bank = args.case_bank
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    report = _read_json(operating_report)
    if args.refresh_actual_training:
        report = _refresh_actual_training(report, args.min_training_rows, args.training_detail)
    case_rows = _read_jsonl(case_bank)
    record = _build_record(report, case_rows, operating_report)

    json_path = output_dir / "improvement-curve.json"
    html_path = output_dir / "improvement-curve.html"
    ledger_path = output_dir / "ledger.jsonl"
    json_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    _render_html(record, html_path)

    print(json.dumps({"status": "recorded", "json": str(json_path), "html": str(html_path), "ledger": str(ledger_path), "summary": record["summary"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
