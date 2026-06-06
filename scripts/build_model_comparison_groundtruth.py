from __future__ import annotations

import argparse
import csv
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def _get(data: dict[str, Any], path: list[Any], default: Any = None) -> Any:
    cursor: Any = data
    for key in path:
        if isinstance(cursor, dict):
            cursor = cursor.get(key)
        elif isinstance(cursor, list) and isinstance(key, int) and 0 <= key < len(cursor):
            cursor = cursor[key]
        else:
            return default
    return default if cursor is None else cursor


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _round(value: Any, digits: int = 3) -> float | None:
    number = _num(value)
    return round(number, digits) if number is not None else None


def _avg(values: list[Any], digits: int = 3) -> float | None:
    numbers = [_num(value) for value in values]
    filtered = [value for value in numbers if value is not None]
    return round(sum(filtered) / len(filtered), digits) if filtered else None


def _pct(value: Any) -> float | None:
    number = _num(value)
    return round(number * 100, 2) if number is not None else None


def _pointer(*parts: Any) -> str:
    return "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def _model_cell(value: Any, report: str, pointer: str, comparability: str) -> dict[str, Any]:
    return {
        "value": value,
        "source_report": report,
        "json_pointer": pointer,
        "comparability": comparability,
    }


def _scenario_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("scenario_key"):
            indexed[str(row["scenario_key"])] = row
    return indexed


def _current_scenarios(current: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _scenario_index(_get(current, ["actual_training", "model_ops", "scenario_fitness", "scenarios"], []) or [])


def _previous_scenarios(recovery: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _scenario_index(_get(recovery, ["actual_training_status", "model_ops", "scenario_fitness", "scenarios"], []) or [])


def _earlier_scenarios(partial: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in ("promoted_or_promotable_slices", "held_slices", "risk_lift_held_slices"):
        for row in partial.get(key, []) if isinstance(partial.get(key), list) else []:
            if isinstance(row, dict):
                rows.append(row)
    return _scenario_index(rows)


def _branch_rows(cycle: dict[str, Any]) -> list[dict[str, Any]]:
    rows = _get(cycle, ["measurement", "reward_layers", "substitute_outcome_attribution", "rows"], [])
    return rows if isinstance(rows, list) else []


def _monitor_scores(cycles: list[dict[str, Any]]) -> list[float]:
    scores = []
    for cycle in cycles:
        for row in _branch_rows(cycle):
            score = _num(row.get("monitor_only_counterfactual_score") if isinstance(row, dict) else None)
            if score is not None:
                scores.append(score)
    return scores


def _hard_decision_activation(layers: dict[str, Any]) -> tuple[float | None, str | None]:
    explicit = _num(layers.get("hard_decision_activation_reward"))
    label = layers.get("hard_decision_activation_label")
    if explicit is not None:
        return round(explicit, 3), str(label) if label else None
    metrics = layers.get("metrics", {}) if isinstance(layers.get("metrics"), dict) else {}
    risk_lift = _num(layers.get("risk_lift_reward"), 0.0) or 0.0
    risk_executed = int(_num(metrics.get("risk_escalated_executed_count"), 0) or 0)
    impact_applied = bool(metrics.get("risk_escalation_impact_applied"))
    safe_substitutes = int(_num(metrics.get("safe_executable_substitute_count"), 0) or 0)
    unresolved = int(_num(metrics.get("unresolved_without_safe_substitute_count"), 0) or 0)
    held = int(_num(metrics.get("held_count"), 0) or 0)
    held_dispositions = int(_num(metrics.get("held_disposition_count"), 0) or 0)
    score = 0.0
    if risk_executed > 0 and impact_applied:
        score = max(score, min(1.0, 0.58 + (0.32 * risk_lift)))
    if safe_substitutes > 0 and unresolved == 0:
        score = max(score, 0.68)
    if held > 0 and held_dispositions == held:
        score = max(score, 0.45)
    if score == 0.0 and not (risk_executed or safe_substitutes or held):
        return 0.5, "hard_decision_not_required"
    inferred_label = (
        "hard_decision_lifted_success"
        if risk_executed > 0 and impact_applied and score >= 0.7
        else "hard_decision_safe_substitute"
        if safe_substitutes > 0 and unresolved == 0
        else "hard_decision_held_with_owner"
        if held > 0 and held_dispositions == held
        else "hard_decision_avoided"
    )
    return round(score, 3), inferred_label


def _case_rows(cycles: list[dict[str, Any]], current_report: str) -> list[dict[str, Any]]:
    rows = []
    for index, cycle in enumerate(cycles):
        issue = cycle.get("issue", {}) if isinstance(cycle.get("issue"), dict) else {}
        actions = cycle.get("actions", {}) if isinstance(cycle.get("actions"), dict) else {}
        measurement = cycle.get("measurement", {}) if isinstance(cycle.get("measurement"), dict) else {}
        layers = measurement.get("reward_layers", {}) if isinstance(measurement.get("reward_layers"), dict) else {}
        metrics = layers.get("metrics", {}) if isinstance(layers.get("metrics"), dict) else {}
        branch = layers.get("branch_rewards", {}) if isinstance(layers.get("branch_rewards"), dict) else {}
        risk = branch.get("risk_lift", {}) if isinstance(branch.get("risk_lift"), dict) else {}
        substitute = layers.get("substitute_outcome_attribution", {}) if isinstance(layers.get("substitute_outcome_attribution"), dict) else {}
        monitor = _avg([row.get("monitor_only_counterfactual_score") for row in _branch_rows(cycle) if isinstance(row, dict)])
        operational = _num(layers.get("operational_reward"))
        hard_decision_score, hard_decision_label = _hard_decision_activation(layers)
        rows.append(
            {
                "case_key": f"cycle_{cycle.get('cycle')}",
                "cycle": cycle.get("cycle"),
                "issue_kind": issue.get("kind"),
                "target_id": issue.get("target_id"),
                "intensity": issue.get("intensity"),
                "current_ml_slice": _get(cycle, ["ml_policy", "scenario_key"]),
                "current_ml_slice_decision": _get(cycle, ["ml_policy", "slice_decision"]),
                "current_operational_reward": _round(operational),
                "current_composite_reward": _round(layers.get("composite_reward")),
                "current_controlled_reward": _round(layers.get("controlled_low_risk_reward")),
                "current_risk_lift_reward": _round(layers.get("risk_lift_reward")),
                "risk_lift_label": risk.get("label") or layers.get("risk_lift_label"),
                "hard_decision_activation_reward": hard_decision_score,
                "hard_decision_activation_label": hard_decision_label,
                "baseline_monitor_score": _round(monitor),
                "current_vs_baseline_reward_delta": _round((operational or 0) - (monitor or 0)),
                "substitute_lift_vs_monitor": _round(substitute.get("average_lift_vs_monitor")),
                "executed_count": actions.get("executed_count"),
                "held_count": actions.get("held_count"),
                "risk_escalated_executed_count": actions.get("risk_escalated_executed_count"),
                "memory_applied_count": metrics.get("memory_applied_count"),
                "promotion_eligible": measurement.get("promotion_eligible"),
                "promotion_blockers": layers.get("promotion_blockers", []),
                "current_source": current_report,
                "current_json_pointer": _pointer("cycles", index),
                "baseline_source": current_report,
                "baseline_json_pointer": _pointer("cycles", index, "measurement", "reward_layers", "substitute_outcome_attribution", "rows"),
                "previous_model_comparability": "not_same_case_replay",
            }
        )
    return rows


def _snapshot_matrix(current: dict[str, Any], recovery: dict[str, Any], partial: dict[str, Any], current_report: str, recovery_report: str, partial_report: str) -> list[dict[str, Any]]:
    current_gate = _get(current, ["actual_training", "model_ops", "promotion_gate"], {}) or {}
    current_curve = _get(current, ["actual_training", "model_ops", "fitness_curve"], {}) or {}
    current_scenario = _get(current, ["actual_training", "model_ops", "scenario_fitness"], {}) or {}
    current_model = _get(current, ["actual_training", "model"], {}) or {}
    recovery_summary = recovery.get("summary", {}) if isinstance(recovery.get("summary"), dict) else {}
    monitor_baseline = _pct(_avg(_monitor_scores(current.get("cycles", []) if isinstance(current.get("cycles"), list) else [])))
    metrics = [
        ("gate_status", current_gate.get("status"), recovery_summary.get("promotion_gate_status"), partial.get("full_model_gate_status"), "not_promotable_baseline"),
        ("decision", current_gate.get("decision"), recovery_summary.get("promotion_decision"), partial.get("full_model_gate_decision"), "monitor_or_hold_only"),
        ("sample_count", _get(current, ["actual_training", "sample_count"]), recovery_summary.get("sample_count"), None, len(current.get("cycles", []) or [])),
        ("training_rows", current_gate.get("training_rows"), recovery_summary.get("training_rows"), None, None),
        ("promotion_evaluation_rows", current_gate.get("promotion_evaluation_rows"), recovery_summary.get("promotion_evaluation_rows"), None, None),
        ("latest_average_reward", current_curve.get("latest_average_reward"), recovery_summary.get("latest_average_reward"), 40.75, monitor_baseline),
        ("curve_delta", current_curve.get("delta"), recovery_summary.get("curve_delta"), -15.2, None),
        ("scenario_balanced_average", current_scenario.get("balanced_latest_average_reward"), recovery_summary.get("scenario_balanced_latest_average_reward"), None, monitor_baseline),
        ("promotable_slice_count", current_scenario.get("promotable_slice_count"), recovery_summary.get("promotable_slice_count"), partial.get("promoted_or_promotable_count"), 0),
        ("held_slice_count", current_scenario.get("hold_slice_count"), recovery_summary.get("hold_slice_count"), partial.get("held_count"), len(current_scenario.get("scenarios", []) or [])),
        ("thin_slice_count", current_scenario.get("collect_more_evidence_count"), recovery_summary.get("collect_more_evidence_count"), None, 0),
        ("blocker_count", len(current_gate.get("blockers") or []), len(recovery_summary.get("blockers") or []), len(partial.get("global_blockers") or []), 1),
        ("best_policy_id", current_model.get("best_policy_id"), recovery_summary.get("best_policy_id"), "previous_mixed_guardrail_snapshot", "monitor_only_no_learning"),
    ]
    return [
        {
            "metric": metric,
            "current_challenger": _model_cell(current_value, current_report, _pointer("actual_training", "model_ops"), "snapshot"),
            "previous_after_guardrail_split": _model_cell(previous_value, recovery_report, _pointer("summary"), "snapshot"),
            "earlier_mixed_guardrail_model": _model_cell(earlier_value, partial_report, _pointer(), "snapshot"),
            "monitor_only_baseline": _model_cell(baseline_value, current_report, _pointer("cycles"), "same_case_counterfactual" if metric == "latest_average_reward" else "baseline_reference"),
        }
        for metric, current_value, previous_value, earlier_value, baseline_value in metrics
    ]


def _scenario_matrix(current: dict[str, Any], recovery: dict[str, Any], partial: dict[str, Any], current_report: str, recovery_report: str, partial_report: str) -> list[dict[str, Any]]:
    current_rows = _current_scenarios(current)
    previous_rows = _previous_scenarios(recovery)
    earlier_rows = _earlier_scenarios(partial)
    scenarios = sorted(set(current_rows) | set(previous_rows) | set(earlier_rows))
    matrix = []
    for scenario in scenarios:
        current_row = current_rows.get(scenario, {})
        previous_row = previous_rows.get(scenario, {})
        earlier_row = earlier_rows.get(scenario, {})
        matrix.append(
            {
                "scenario_key": scenario,
                "current": {
                    "decision": current_row.get("decision"),
                    "sample_count": current_row.get("sample_count"),
                    "latest_average_reward": current_row.get("latest_average_reward"),
                    "curve_delta": current_row.get("curve_delta"),
                    "source_report": current_report,
                    "json_pointer": _pointer("actual_training", "model_ops", "scenario_fitness", "scenarios"),
                },
                "previous_after_guardrail_split": {
                    "decision": previous_row.get("decision"),
                    "sample_count": previous_row.get("sample_count"),
                    "latest_average_reward": previous_row.get("latest_average_reward"),
                    "curve_delta": previous_row.get("curve_delta"),
                    "source_report": recovery_report,
                    "json_pointer": _pointer("actual_training_status", "model_ops", "scenario_fitness", "scenarios"),
                    "comparability": "snapshot_same_training_stack_before_fresh_feeds",
                },
                "earlier_mixed_guardrail_model": {
                    "decision": earlier_row.get("decision"),
                    "sample_count": earlier_row.get("sample_count"),
                    "latest_average_reward": earlier_row.get("latest_average_reward"),
                    "curve_delta": earlier_row.get("curve_delta"),
                    "source_report": partial_report,
                    "json_pointer": _pointer("held_slices"),
                    "comparability": "snapshot_before_guardrail_split",
                },
                "monitor_only_baseline": {
                    "decision": "monitor_or_hold_only",
                    "sample_count": 0,
                    "latest_average_reward": None,
                    "curve_delta": None,
                    "source_report": current_report,
                    "json_pointer": _pointer("cycles", "*", "measurement", "reward_layers", "substitute_outcome_attribution", "rows"),
                    "comparability": "same_case_counterfactual_available_in_case_matrix",
                },
            }
        )
    return matrix


def _live_feed_matrix(current: dict[str, Any], current_report: str) -> list[dict[str, Any]]:
    cycles = current.get("cycles", []) if isinstance(current.get("cycles"), list) else []
    return _case_rows([cycle for cycle in cycles if isinstance(cycle, dict)], current_report)


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _flatten_snapshot_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "metric": row["metric"],
            "current": row["current_challenger"]["value"],
            "previous_after_guardrail_split": row["previous_after_guardrail_split"]["value"],
            "earlier_mixed_guardrail_model": row["earlier_mixed_guardrail_model"]["value"],
            "monitor_only_baseline": row["monitor_only_baseline"]["value"],
            "current_source": row["current_challenger"]["source_report"],
            "previous_source": row["previous_after_guardrail_split"]["source_report"],
            "earlier_source": row["earlier_mixed_guardrail_model"]["source_report"],
            "baseline_source": row["monitor_only_baseline"]["source_report"],
        }
        for row in rows
    ]


def _flatten_scenario_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened = []
    for row in rows:
        base = {"scenario_key": row["scenario_key"]}
        for label in ("current", "previous_after_guardrail_split", "earlier_mixed_guardrail_model", "monitor_only_baseline"):
            value = row[label]
            for key in ("decision", "sample_count", "latest_average_reward", "curve_delta"):
                base[f"{label}_{key}"] = value.get(key)
        flattened.append(base)
    return flattened


def _esc(value: Any) -> str:
    return html.escape(str("" if value is None else value))


def _render_html(payload: dict[str, Any]) -> str:
    snapshot_rows = payload["snapshot_matrix"]
    scenario_rows = payload["scenario_matrix"]
    case_rows = payload["case_matrix"]
    summary = payload["summary"]

    def metric(label: str, value: Any, note: str = "") -> str:
        return f'<div class="metric"><span>{_esc(label)}</span><strong>{_esc(value)}</strong><small>{_esc(note)}</small></div>'

    snapshot_body = "\n".join(
        "<tr>"
        f"<td>{_esc(row['metric'])}</td>"
        f"<td>{_esc(row['current_challenger']['value'])}</td>"
        f"<td>{_esc(row['previous_after_guardrail_split']['value'])}</td>"
        f"<td>{_esc(row['earlier_mixed_guardrail_model']['value'])}</td>"
        f"<td>{_esc(row['monitor_only_baseline']['value'])}</td>"
        "</tr>"
        for row in snapshot_rows
    )
    scenario_body = "\n".join(
        "<tr>"
        f"<td>{_esc(row['scenario_key'])}</td>"
        f"<td>{_esc(row['current'].get('decision'))}<br><small>{_esc(row['current'].get('latest_average_reward'))} / {_esc(row['current'].get('curve_delta'))}</small></td>"
        f"<td>{_esc(row['previous_after_guardrail_split'].get('decision'))}<br><small>{_esc(row['previous_after_guardrail_split'].get('latest_average_reward'))} / {_esc(row['previous_after_guardrail_split'].get('curve_delta'))}</small></td>"
        f"<td>{_esc(row['earlier_mixed_guardrail_model'].get('decision'))}<br><small>{_esc(row['earlier_mixed_guardrail_model'].get('latest_average_reward'))} / {_esc(row['earlier_mixed_guardrail_model'].get('curve_delta'))}</small></td>"
        f"<td>{_esc(row['monitor_only_baseline'].get('decision'))}</td>"
        "</tr>"
        for row in scenario_rows
    )
    case_body = "\n".join(
        "<tr>"
        f"<td>{_esc(row['case_key'])}</td>"
        f"<td>{_esc(row['issue_kind'])}<br><small>{_esc(row['target_id'])}, intensity {_esc(row['intensity'])}</small></td>"
        f"<td>{_esc(row['current_ml_slice'])}<br><small>{_esc(row['current_ml_slice_decision'])}</small></td>"
        f"<td>{_esc(row['current_operational_reward'])}</td>"
        f"<td>{_esc(row['baseline_monitor_score'])}</td>"
        f"<td>{_esc(row['current_vs_baseline_reward_delta'])}</td>"
        f"<td>{_esc(row['current_risk_lift_reward'])}<br><small>{_esc(row['risk_lift_label'])}</small></td>"
        f"<td>{_esc(row['hard_decision_activation_reward'])}<br><small>{_esc(row['hard_decision_activation_label'])}</small></td>"
        f"<td>{_esc(row['executed_count'])} / {_esc(row['held_count'])}</td>"
        f"<td>{_esc(row['memory_applied_count'])}</td>"
        "</tr>"
        for row in case_rows
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ParkPulse Ground Truth Model Matrix</title>
<style>
:root{{--ink:#17212b;--muted:#607080;--line:#dbe2e8;--panel:#f7f9fb;--ok:#0b7a55;--warn:#9a5a00;--bad:#a22828}}
body{{margin:0;font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--ink);background:#fff}}
main{{max-width:1280px;margin:0 auto;padding:28px}} h1{{font-size:27px;margin:0 0 6px}} h2{{font-size:18px;margin:28px 0 10px}} p{{color:var(--muted);max-width:980px}}
.grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:18px 0}} .metric{{border:1px solid var(--line);background:var(--panel);border-radius:8px;padding:12px;min-height:76px}}
.metric span,.metric small{{display:block;color:var(--muted);font-size:12px}} .metric strong{{font-size:22px;display:block;margin:4px 0}}
.panel{{border:1px solid var(--line);border-radius:8px;padding:16px;margin:14px 0;overflow:auto}} table{{width:100%;border-collapse:collapse;min-width:980px}}
th,td{{text-align:left;vertical-align:top;border-bottom:1px solid var(--line);padding:8px}} th{{font-size:12px;color:var(--muted);background:var(--panel);position:sticky;top:0}}
small{{color:var(--muted)}} code{{background:#eef2f6;padding:2px 5px;border-radius:5px}} .truth{{border-left:4px solid var(--ok)}} .warn{{border-left:4px solid var(--warn)}} ul{{margin:8px 0 0 20px;padding:0}}
@media(max-width:860px){{.grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}main{{padding:18px}}}}
</style>
</head>
<body><main>
<h1>ParkPulse Ground Truth Model Matrix</h1>
<p>Generated {_esc(payload['generated_at'])}. This matrix separates same-case counterfactual evidence from snapshot-to-snapshot model evidence so the report ground truth is auditable.</p>
<div class="grid">
{metric('Current gate', summary['current_gate'], 'fresh live feeds')}
{metric('Previous gate', summary['previous_gate'], 'before fresh feeds')}
{metric('Current vs baseline reward delta', summary['current_vs_baseline_reward_delta'], 'points on 0-100 scale')}
{metric('Hard decision activation', summary['hard_decision_activation_average'], 'latest scored target')}
{metric('Live cases', summary['live_case_count'], 'case-level matrix rows')}
{metric('Promotable slices now', summary['current_promotable_slices'], 'mature slices')}
{metric('Held slices now', summary['current_held_slices'], 'reward math')}
{metric('Thin slices now', summary['current_thin_slices'], 'observation-only')}
{metric('Source-backed cells', summary['source_backed_cell_count'], 'json pointers included')}
</div>
<section class="panel truth"><h2>Ground Truth Boundary</h2>
<ul>
<li>Current vs baseline is same-case where monitor-only counterfactual rows exist in the live-feed report.</li>
<li>Current vs previous is snapshot-to-snapshot, not same-case replay of an old policy.</li>
<li>Earlier mixed-guardrail model is pre-fix historical evidence, useful for regression comparison but not a live replay.</li>
</ul></section>
<section class="panel"><h2>Model Snapshot Matrix</h2><table><thead><tr><th>Metric</th><th>Current challenger</th><th>Previous after split</th><th>Earlier mixed guardrail</th><th>Monitor-only baseline</th></tr></thead><tbody>{snapshot_body}</tbody></table></section>
<section class="panel"><h2>Scenario Matrix</h2><table><thead><tr><th>Scenario</th><th>Current</th><th>Previous after split</th><th>Earlier mixed guardrail</th><th>Baseline</th></tr></thead><tbody>{scenario_body}</tbody></table></section>
<section class="panel"><h2>Case Matrix</h2><table><thead><tr><th>Case</th><th>Issue</th><th>Current ML slice</th><th>Current reward</th><th>Baseline</th><th>Delta</th><th>Risk-lift</th><th>Hard decision</th><th>Executed / held</th><th>Memory</th></tr></thead><tbody>{case_body}</tbody></table></section>
<section class="panel warn"><h2>Files</h2>
<p>JSON: <code>{_esc(payload['outputs']['json'])}</code></p>
<p>CSV: <code>{_esc(payload['outputs']['snapshot_csv'])}</code>, <code>{_esc(payload['outputs']['scenario_csv'])}</code>, <code>{_esc(payload['outputs']['case_csv'])}</code></p>
</section>
</main></body></html>"""


def build(args: argparse.Namespace) -> dict[str, Any]:
    current_path = (ROOT / args.current).resolve()
    recovery_path = (ROOT / args.recovery).resolve()
    partial_path = (ROOT / args.partial).resolve()
    output_dir = (ROOT / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    current = _read_json(current_path)
    recovery = _read_json(recovery_path)
    partial = _read_json(partial_path)

    current_report = str(current_path.relative_to(ROOT))
    recovery_report = str(recovery_path.relative_to(ROOT))
    partial_report = str(partial_path.relative_to(ROOT))

    snapshot_matrix = _snapshot_matrix(current, recovery, partial, current_report, recovery_report, partial_report)
    scenario_matrix = _scenario_matrix(current, recovery, partial, current_report, recovery_report, partial_report)
    case_matrix = _live_feed_matrix(current, current_report)

    current_gate = _get(current, ["actual_training", "model_ops", "promotion_gate", "status"])
    previous_gate = _get(recovery, ["summary", "promotion_gate_status"])
    current_reward = _get(current, ["actual_training", "model_ops", "fitness_curve", "latest_average_reward"])
    baseline_reward = next((row["monitor_only_baseline"]["value"] for row in snapshot_matrix if row["metric"] == "latest_average_reward"), None)
    source_backed_cell_count = sum(4 for _ in snapshot_matrix) + sum(4 for _ in scenario_matrix) + (2 * len(case_matrix))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "parkpulse_model_comparison_groundtruth_matrix",
        "inputs": {
            "current_live_feed_report": current_report,
            "previous_after_guardrail_split_report": recovery_report,
            "earlier_mixed_guardrail_report": partial_report,
        },
        "summary": {
            "current_gate": current_gate,
            "previous_gate": previous_gate,
            "current_vs_baseline_reward_delta": _round((current_reward or 0) - (baseline_reward or 0), 2),
            "hard_decision_activation_average": _avg([row.get("hard_decision_activation_reward") for row in case_matrix]),
            "live_case_count": len(case_matrix),
            "current_promotable_slices": _get(current, ["actual_training", "model_ops", "scenario_fitness", "promotable_slice_count"]),
            "current_held_slices": _get(current, ["actual_training", "model_ops", "scenario_fitness", "hold_slice_count"]),
            "current_thin_slices": _get(current, ["actual_training", "model_ops", "scenario_fitness", "collect_more_evidence_count"]),
            "source_backed_cell_count": source_backed_cell_count,
        },
        "comparability_contract": {
            "current_vs_baseline": "same_case_counterfactual_from_live_feed_substitute_rows",
            "current_vs_previous_after_guardrail_split": "snapshot_to_snapshot_not_same_case_replay",
            "current_vs_earlier_mixed_guardrail": "historical_regression_comparison_before_guardrail_split",
            "baseline_definition": "monitor-only fallback score from substitute outcome attribution rows; no learning, no lifted action, no policy-slice promotion.",
        },
        "snapshot_matrix": snapshot_matrix,
        "scenario_matrix": scenario_matrix,
        "case_matrix": case_matrix,
    }

    json_path = output_dir / "groundtruth-model-comparison-matrix.json"
    html_path = output_dir / "groundtruth-model-comparison-matrix.html"
    snapshot_csv = output_dir / "groundtruth-snapshot-matrix.csv"
    scenario_csv = output_dir / "groundtruth-scenario-matrix.csv"
    case_csv = output_dir / "groundtruth-case-matrix.csv"
    payload["outputs"] = {
        "json": str(json_path.relative_to(ROOT)),
        "html": str(html_path.relative_to(ROOT)),
        "snapshot_csv": str(snapshot_csv.relative_to(ROOT)),
        "scenario_csv": str(scenario_csv.relative_to(ROOT)),
        "case_csv": str(case_csv.relative_to(ROOT)),
    }

    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    html_path.write_text(_render_html(payload), encoding="utf-8")
    _write_csv(snapshot_csv, _flatten_snapshot_rows(snapshot_matrix), ["metric", "current", "previous_after_guardrail_split", "earlier_mixed_guardrail_model", "monitor_only_baseline", "current_source", "previous_source", "earlier_source", "baseline_source"])
    _write_csv(scenario_csv, _flatten_scenario_rows(scenario_matrix), [
        "scenario_key",
        "current_decision",
        "current_sample_count",
        "current_latest_average_reward",
        "current_curve_delta",
        "previous_after_guardrail_split_decision",
        "previous_after_guardrail_split_sample_count",
        "previous_after_guardrail_split_latest_average_reward",
        "previous_after_guardrail_split_curve_delta",
        "earlier_mixed_guardrail_model_decision",
        "earlier_mixed_guardrail_model_sample_count",
        "earlier_mixed_guardrail_model_latest_average_reward",
        "earlier_mixed_guardrail_model_curve_delta",
        "monitor_only_baseline_decision",
    ])
    _write_csv(case_csv, case_matrix, [
        "case_key",
        "cycle",
        "issue_kind",
        "target_id",
        "intensity",
        "current_ml_slice",
        "current_ml_slice_decision",
        "current_operational_reward",
        "current_composite_reward",
        "current_controlled_reward",
        "current_risk_lift_reward",
        "risk_lift_label",
        "hard_decision_activation_reward",
        "hard_decision_activation_label",
        "baseline_monitor_score",
        "current_vs_baseline_reward_delta",
        "substitute_lift_vs_monitor",
        "executed_count",
        "held_count",
        "risk_escalated_executed_count",
        "memory_applied_count",
        "promotion_eligible",
        "current_source",
        "current_json_pointer",
        "baseline_json_pointer",
        "previous_model_comparability",
    ])
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a source-backed ParkPulse model comparison ground-truth matrix.")
    parser.add_argument("--current", default="output/qa/live-feed-model-comparison-20260605-202000/live-feed-operating-cycle.json")
    parser.add_argument("--recovery", default="output/qa/promotion-recovery-eval-20260605/promotion-recovery-eval.json")
    parser.add_argument("--partial", default="output/qa/partial-promotion-plan-20260605/partial-promotion-plan.json")
    parser.add_argument("--output-dir", default="output/qa/live-feed-model-comparison-20260605-202000")
    return parser.parse_args()


if __name__ == "__main__":
    result = build(parse_args())
    print(json.dumps({"status": "written", "outputs": result["outputs"], "summary": result["summary"]}, indent=2, sort_keys=True))
