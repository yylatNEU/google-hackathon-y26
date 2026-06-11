from __future__ import annotations

import argparse
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


def _get(data: Any, path: list[Any], default: Any = None) -> Any:
    cursor = data
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


def _avg(values: list[Any]) -> float | None:
    numbers = [_num(value) for value in values]
    filtered = [value for value in numbers if value is not None]
    return round(sum(filtered) / len(filtered), 2) if filtered else None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _round(value: Any, digits: int = 2) -> float | None:
    number = _num(value)
    return round(number, digits) if number is not None else None


def _episode(cycle: dict[str, Any]) -> dict[str, Any]:
    return _get(cycle, ["actions", "risk_escalation_episode_fitness"], {}) or {}


def _digest(cycle: dict[str, Any], label: str) -> dict[str, Any]:
    return _get(_episode(cycle), ["digests", label], {}) or {}


def _episode_metric(cycle: dict[str, Any], branch: str, metric: str) -> float | None:
    return _num(_get(_episode(cycle), ["metrics", branch, metric]))


def _path_congestion(cycle: dict[str, Any], branch: str) -> float | None:
    return _num(_get(_digest(cycle, branch), ["topPath", "congestionLevel"]))


def _satisfaction(cycle: dict[str, Any], branch: str) -> float | None:
    return _num(_digest(cycle, branch).get("avgSatisfaction"))


def _operator_escalation_ok(cycle: dict[str, Any], branch: str) -> bool:
    escalation = str(_get(_digest(cycle, branch), ["incidentReadiness", "operatorEscalation"]) or "")
    return escalation not in {"required", ""}


def _safety_score(cycle: dict[str, Any], branch: str) -> float | None:
    violations = _episode_metric(cycle, "actual" if branch == "actual_after" else "baseline", "safety_violations")
    if violations is None:
        return None
    score = 100 - (20 * violations)
    if _operator_escalation_ok(cycle, branch):
        score += 10
    return round(_clamp(score), 2)


def _congestion_relief_score(cycle: dict[str, Any], branch: str) -> float | None:
    before = _path_congestion(cycle, "before")
    after = _path_congestion(cycle, branch)
    if before is None or after is None:
        return None
    return round(_clamp(50 + before - after), 2)


def _hard_decision_activation(layers: dict[str, Any]) -> tuple[float | None, str | None]:
    explicit = _num(layers.get("hard_decision_activation_reward"))
    label = layers.get("hard_decision_activation_label")
    if explicit is not None:
        return round(explicit * 100, 2), str(label) if label else None
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
        return 50.0, "hard_decision_not_required"
    inferred_label = (
        "hard_decision_lifted_success"
        if risk_executed > 0 and impact_applied and score >= 0.7
        else "hard_decision_safe_substitute"
        if safe_substitutes > 0 and unresolved == 0
        else "hard_decision_held_with_owner"
        if held > 0 and held_dispositions == held
        else "hard_decision_avoided"
    )
    return round(score * 100, 2), inferred_label


def _case_parameter_rows(current: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    cycles = current.get("cycles", []) if isinstance(current.get("cycles"), list) else []
    for cycle in cycles:
        if not isinstance(cycle, dict):
            continue
        issue = cycle.get("issue", {}) if isinstance(cycle.get("issue"), dict) else {}
        actions = cycle.get("actions", {}) if isinstance(cycle.get("actions"), dict) else {}
        layers = _get(cycle, ["measurement", "reward_layers"], {}) or {}
        hard_decision_score, hard_decision_label = _hard_decision_activation(layers if isinstance(layers, dict) else {})
        rows.append(
            {
                "case_key": f"cycle_{cycle.get('cycle')}",
                "issue": issue.get("kind"),
                "target": issue.get("target_id"),
                "intensity": issue.get("intensity"),
                "current_action": "execute_controlled_plus_risk_lift" if actions.get("risk_escalation_impact_status") == "applied" else "controlled_only",
                "baseline_action": "monitor_only_hold",
                "previous_action": "not_same_case_replay",
                "current_safety": _safety_score(cycle, "actual_after"),
                "baseline_safety": _safety_score(cycle, "baseline_after"),
                "current_congestion": _congestion_relief_score(cycle, "actual_after"),
                "baseline_congestion": _congestion_relief_score(cycle, "baseline_after"),
                "current_satisfaction": _round(_satisfaction(cycle, "actual_after")),
                "baseline_satisfaction": _round(_satisfaction(cycle, "baseline_after")),
                "path_before": _round(_path_congestion(cycle, "before")),
                "path_current_after": _round(_path_congestion(cycle, "actual_after")),
                "path_baseline_after": _round(_path_congestion(cycle, "baseline_after")),
                "satisfaction_before": _round(_satisfaction(cycle, "before")),
                "operational_reward": _round(layers.get("operational_reward"), 3),
                "risk_lift_reward": _round(layers.get("risk_lift_reward"), 3),
                "risk_lift_label": _get(layers, ["branch_rewards", "risk_lift", "label"]) or layers.get("risk_lift_label"),
                "hard_decision_activation": hard_decision_score,
                "hard_decision_label": hard_decision_label,
                "executed_count": actions.get("executed_count"),
                "held_count": actions.get("held_count"),
                "risk_escalated_executed_count": actions.get("risk_escalated_executed_count"),
                "memory_applied_count": _get(layers, ["metrics", "memory_applied_count"]),
                "promotion_eligible": _get(cycle, ["measurement", "promotion_eligible"]),
                "promotion_blockers": layers.get("promotion_blockers", []),
            }
        )
    return rows


def _scenario_rows(matrix: dict[str, Any]) -> list[dict[str, Any]]:
    rows = matrix.get("scenario_matrix", []) if isinstance(matrix.get("scenario_matrix"), list) else []
    output = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        current = row.get("current", {}) if isinstance(row.get("current"), dict) else {}
        previous = row.get("previous_after_guardrail_split", {}) if isinstance(row.get("previous_after_guardrail_split"), dict) else {}
        earlier = row.get("earlier_mixed_guardrail_model", {}) if isinstance(row.get("earlier_mixed_guardrail_model"), dict) else {}
        output.append(
            {
                "scenario_key": row.get("scenario_key"),
                "current_decision": current.get("decision"),
                "current_reward": current.get("latest_average_reward"),
                "current_delta": current.get("curve_delta"),
                "previous_decision": previous.get("decision"),
                "previous_reward": previous.get("latest_average_reward"),
                "previous_delta": previous.get("curve_delta"),
                "earlier_decision": earlier.get("decision"),
                "earlier_reward": earlier.get("latest_average_reward"),
                "earlier_delta": earlier.get("curve_delta"),
            }
        )
    return output


def _model_behavior(current: dict[str, Any], matrix: dict[str, Any], recovery: dict[str, Any], partial: dict[str, Any], case_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current_gate = _get(current, ["actual_training", "model_ops", "promotion_gate"], {}) or {}
    current_summary = current.get("summary", {}) if isinstance(current.get("summary"), dict) else {}
    previous_summary = recovery.get("summary", {}) if isinstance(recovery.get("summary"), dict) else {}
    current_scores = {
        "safety": _avg([row.get("current_safety") for row in case_rows]),
        "congestion": _avg([row.get("current_congestion") for row in case_rows]),
        "satisfaction": _avg([row.get("current_satisfaction") for row in case_rows]),
        "hard_decision": _avg([row.get("hard_decision_activation") for row in case_rows]),
    }
    baseline_scores = {
        "safety": _avg([row.get("baseline_safety") for row in case_rows]),
        "congestion": _avg([row.get("baseline_congestion") for row in case_rows]),
        "satisfaction": _avg([row.get("baseline_satisfaction") for row in case_rows]),
        "hard_decision": 0,
    }
    earlier_latest = next((row.get("earlier_mixed_guardrail_model", {}).get("value") for row in matrix.get("snapshot_matrix", []) if row.get("metric") == "latest_average_reward"), None)
    return [
        {
            "model": "Current challenger",
            "how_it_acts": "Reads fresh live feeds, retrieves memory, negotiates tradeoffs, executes policy-passed controlled actions, and lifts approved risky actions through Tool Executor.",
            "gate": current_gate.get("status"),
            "decision": current_gate.get("decision"),
            "park_result": "Six mature slices are promotable; one thin slice remains observation-only.",
            "executed_actions": current_summary.get("executed_action_count"),
            "held_actions": current_summary.get("held_action_count"),
            "safety_score": current_scores["safety"],
            "congestion_score": current_scores["congestion"],
            "satisfaction_score": current_scores["satisfaction"],
            "hard_decision_score": current_scores["hard_decision"],
            "reward": _get(current, ["actual_training", "model_ops", "fitness_curve", "latest_average_reward"]),
            "evidence": "same live-feed cases",
        },
        {
            "model": "Previous after guardrail split",
            "how_it_acts": "It had better reward math after guardrail separation, but its promotion decision stayed hold because live feed freshness gates were stale.",
            "gate": previous_summary.get("promotion_gate_status"),
            "decision": previous_summary.get("promotion_decision"),
            "park_result": "Reasonable model evidence, but no safe live promotion at that snapshot.",
            "executed_actions": "not replayed",
            "held_actions": "blocked by 5 feed gates",
            "safety_score": "not same-case",
            "congestion_score": "not same-case",
            "satisfaction_score": "not same-case",
            "hard_decision_score": "not same-case",
            "reward": previous_summary.get("latest_average_reward"),
            "evidence": "snapshot comparison only",
        },
        {
            "model": "Baseline monitor-only",
            "how_it_acts": "Does not learn, does not lift risk, does not execute park-relief actions; it monitors or holds.",
            "gate": "not_promotable_baseline",
            "decision": "monitor_or_hold_only",
            "park_result": "Lower congestion relief and no policy-slice promotion.",
            "executed_actions": 0,
            "held_actions": "all actions held",
            "safety_score": baseline_scores["safety"],
            "congestion_score": baseline_scores["congestion"],
            "satisfaction_score": baseline_scores["satisfaction"],
            "hard_decision_score": baseline_scores["hard_decision"],
            "reward": _avg([row.get("baseline_congestion") for row in case_rows]),
            "evidence": "same-case counterfactual",
        },
        {
            "model": "Earlier mixed-guardrail model",
            "how_it_acts": "Mixed QA guardrail failures into promotion math, so risk-lift slices looked bad even when operational cases were improving.",
            "gate": partial.get("full_model_gate_status"),
            "decision": partial.get("full_model_gate_decision"),
            "park_result": "Only two slices promotable and four risk-lift slices held.",
            "executed_actions": "historical snapshot",
            "held_actions": partial.get("held_count"),
            "safety_score": "not same-case",
            "congestion_score": "not same-case",
            "satisfaction_score": "not same-case",
            "hard_decision_score": "not same-case",
            "reward": earlier_latest,
            "evidence": "historical regression comparison",
        },
    ]


def _esc(value: Any) -> str:
    return html.escape(str("" if value is None else value))


def _bar(value: Any, max_value: float = 100.0) -> str:
    number = _num(value)
    if number is None:
        return '<div class="bar muted"><i style="width:0%"></i><span>n/a</span></div>'
    width = _clamp((number / max_value) * 100)
    return f'<div class="bar"><i style="width:{width:.1f}%"></i><span>{_esc(round(number, 2))}</span></div>'


def _render(payload: dict[str, Any]) -> str:
    behavior_rows = payload["model_behavior"]
    case_rows = payload["case_parameter_matrix"]
    scenario_rows = payload["scenario_decision_matrix"]

    cards = "\n".join(
        f"""
        <article class="card">
          <h3>{_esc(row['model'])}</h3>
          <p>{_esc(row['how_it_acts'])}</p>
          <div class="kv"><b>Gate</b><span>{_esc(row['gate'])}</span></div>
          <div class="kv"><b>Decision</b><span>{_esc(row['decision'])}</span></div>
          <div class="kv"><b>Result</b><span>{_esc(row['park_result'])}</span></div>
          <div class="score"><b>Safety / policy</b>{_bar(row['safety_score'])}</div>
          <div class="score"><b>Congestion relief</b>{_bar(row['congestion_score'])}</div>
          <div class="score"><b>Satisfaction</b>{_bar(row['satisfaction_score'])}</div>
          <div class="score"><b>Hard decision activation</b>{_bar(row['hard_decision_score'])}</div>
          <small>Evidence: {_esc(row['evidence'])}</small>
        </article>
        """
        for row in behavior_rows[:3]
    )
    scenario_body = "\n".join(
        "<tr>"
        f"<td>{_esc(row['scenario_key'])}</td>"
        f"<td>{_esc(row['current_decision'])}<br><small>{_esc(row['current_reward'])} / {_esc(row['current_delta'])}</small></td>"
        f"<td>{_esc(row['previous_decision'])}<br><small>{_esc(row['previous_reward'])} / {_esc(row['previous_delta'])}</small></td>"
        f"<td>{_esc(row['earlier_decision'])}<br><small>{_esc(row['earlier_reward'])} / {_esc(row['earlier_delta'])}</small></td>"
        "</tr>"
        for row in scenario_rows
    )
    case_body = "\n".join(
        "<tr>"
        f"<td>{_esc(row['case_key'])}<br><small>{_esc(row['issue'])} at {_esc(row['target'])}</small></td>"
        f"<td>{_esc(row['current_action'])}</td>"
        f"<td>{_bar(row['current_safety'])}</td>"
        f"<td>{_bar(row['current_congestion'])}<small>path {_esc(row['path_before'])} -> {_esc(row['path_current_after'])}</small></td>"
        f"<td>{_bar(row['current_satisfaction'])}<small>before {_esc(row['satisfaction_before'])}</small></td>"
        f"<td>{_bar(row['hard_decision_activation'])}<small>{_esc(row['hard_decision_label'])}</small></td>"
        f"<td>{_esc(row['baseline_action'])}</td>"
        f"<td>{_bar(row['baseline_congestion'])}<small>path {_esc(row['path_before'])} -> {_esc(row['path_baseline_after'])}</small></td>"
        f"<td>{_esc(row['executed_count'])} / {_esc(row['held_count'])}<br><small>risk lift {_esc(row['risk_lift_label'])}</small></td>"
        "</tr>"
        for row in case_rows
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ParkPulse Model Behavior By Park Parameters</title>
<style>
:root{{--ink:#17212b;--muted:#607080;--line:#dbe2e8;--panel:#f7f9fb;--ok:#0c7a55;--blue:#2458a6;--warn:#9a5a00}}
body{{margin:0;font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--ink);background:#fff}}
main{{max-width:1280px;margin:0 auto;padding:28px}} h1{{font-size:28px;margin:0 0 6px}} h2{{font-size:18px;margin:28px 0 10px}} h3{{margin:0 0 8px;font-size:17px}} p{{color:var(--muted)}} small{{color:var(--muted)}}
.cards{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:18px 0}} .card{{border:1px solid var(--line);border-radius:8px;padding:16px;background:var(--panel)}} .card p{{min-height:72px}}
.kv{{display:grid;grid-template-columns:80px 1fr;gap:8px;border-top:1px solid var(--line);padding:8px 0}} .score{{margin:10px 0}} .score b{{display:block;margin-bottom:4px}}
.bar{{position:relative;height:24px;border:1px solid var(--line);background:#fff;border-radius:5px;overflow:hidden}} .bar i{{display:block;height:100%;background:linear-gradient(90deg,#77b7a0,#2458a6)}} .bar span{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-weight:700}} .bar.muted{{background:#eef2f6}}
.panel{{border:1px solid var(--line);border-radius:8px;padding:16px;margin:14px 0;overflow:auto}} table{{width:100%;border-collapse:collapse;min-width:1080px}} th,td{{text-align:left;vertical-align:top;border-bottom:1px solid var(--line);padding:8px}} th{{font-size:12px;color:var(--muted);background:var(--panel);position:sticky;top:0}}
.note{{border-left:4px solid var(--warn);padding:10px 12px;background:#fff8ef;border-radius:6px}} code{{background:#eef2f6;padding:2px 5px;border-radius:5px}}
@media(max-width:940px){{.cards{{grid-template-columns:1fr}}main{{padding:18px}}}}
</style>
</head>
<body><main>
<h1>ParkPulse Model Behavior By Park Parameters</h1>
<p>Generated {_esc(payload['generated_at'])}. This view explains model behavior through safety/policy, congestion relief, and satisfaction instead of raw model scores.</p>
<section class="note">
<b>Scoring formulas:</b>
Safety/policy = 100 - 20 per safety violation + 10 when escalation is in a watched/handled state. Congestion relief = 50 + before path congestion - after path congestion. Satisfaction = reported average satisfaction after the action or baseline. Hard decision activation = approved risky execution, safe substitute, owner assignment, and measured impact; monitor-only baseline scores 0.
</section>
<div class="cards">{cards}</div>
<section class="panel">
<h2>How The Three Models Act Differently</h2>
<table><thead><tr><th>Model</th><th>Action style</th><th>Gate</th><th>Decision</th><th>Executed</th><th>Held</th><th>Hard decision</th><th>Reward</th><th>Evidence</th></tr></thead><tbody>
{''.join(f"<tr><td>{_esc(row['model'])}</td><td>{_esc(row['how_it_acts'])}</td><td>{_esc(row['gate'])}</td><td>{_esc(row['decision'])}</td><td>{_esc(row['executed_actions'])}</td><td>{_esc(row['held_actions'])}</td><td>{_esc(row['hard_decision_score'])}</td><td>{_esc(row['reward'])}</td><td>{_esc(row['evidence'])}</td></tr>" for row in behavior_rows)}
</tbody></table>
</section>
<section class="panel">
<h2>Scenario Decisions</h2>
<table><thead><tr><th>Scenario</th><th>Current challenger</th><th>Previous after split</th><th>Earlier mixed guardrail</th></tr></thead><tbody>{scenario_body}</tbody></table>
</section>
<section class="panel">
<h2>Live Case Park Parameters</h2>
<table><thead><tr><th>Case</th><th>Current action</th><th>Current safety</th><th>Current congestion</th><th>Current satisfaction</th><th>Hard decision</th><th>Baseline action</th><th>Baseline congestion</th><th>Execution</th></tr></thead><tbody>{case_body}</tbody></table>
</section>
<section class="panel">
<h2>Ground Truth Boundary</h2>
<p>Current vs baseline is same-case because baseline comes from each live episode's no-action counterfactual. Previous model and earlier mixed-guardrail model are snapshot comparisons, not same-case replays, so their park-parameter cards are marked as not same-case where appropriate.</p>
<p>JSON: <code>{_esc(payload['outputs']['json'])}</code></p>
</section>
</main></body></html>"""


def build(args: argparse.Namespace) -> dict[str, Any]:
    current_path = (ROOT / args.current).resolve()
    matrix_path = (ROOT / args.matrix).resolve()
    recovery_path = (ROOT / args.recovery).resolve()
    partial_path = (ROOT / args.partial).resolve()
    output_dir = (ROOT / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    current = _read_json(current_path)
    matrix = _read_json(matrix_path)
    recovery = _read_json(recovery_path)
    partial = _read_json(partial_path)
    case_rows = _case_parameter_rows(current)
    scenario_rows = _scenario_rows(matrix)
    model_behavior = _model_behavior(current, matrix, recovery, partial, case_rows)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "park_parameter_intuitive_model_comparison",
        "inputs": {
            "current_live_feed_report": str(current_path.relative_to(ROOT)),
            "groundtruth_matrix": str(matrix_path.relative_to(ROOT)),
            "previous_recovery_report": str(recovery_path.relative_to(ROOT)),
            "earlier_partial_report": str(partial_path.relative_to(ROOT)),
        },
        "scoring_contract": {
            "safety_policy_score": "100 - 20 per safety violation + 10 when operator escalation is already watch/handled instead of required; capped 0..100.",
            "congestion_relief_score": "50 + before top-path congestion - after top-path congestion; capped 0..100.",
            "satisfaction_score": "Average satisfaction after current action or baseline counterfactual.",
            "comparability": "Current and baseline are same-case. Previous and earlier models are snapshot comparisons unless explicitly marked otherwise.",
        },
        "model_behavior": model_behavior,
        "scenario_decision_matrix": scenario_rows,
        "case_parameter_matrix": case_rows,
    }
    json_path = output_dir / "park-parameter-intuitive-model-comparison.json"
    html_path = output_dir / "park-parameter-intuitive-model-comparison.html"
    payload["outputs"] = {
        "json": str(json_path.relative_to(ROOT)),
        "html": str(html_path.relative_to(ROOT)),
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    html_path.write_text(_render(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an intuitive ParkPulse model comparison from park parameters.")
    parser.add_argument("--current", default="output/qa/live-feed-model-comparison-20260605-202000/live-feed-operating-cycle.json")
    parser.add_argument("--matrix", default="output/qa/live-feed-model-comparison-20260605-202000/groundtruth-model-comparison-matrix.json")
    parser.add_argument("--recovery", default="output/qa/promotion-recovery-eval-20260605/promotion-recovery-eval.json")
    parser.add_argument("--partial", default="output/qa/partial-promotion-plan-20260605/partial-promotion-plan.json")
    parser.add_argument("--output-dir", default="output/qa/live-feed-model-comparison-20260605-202000")
    return parser.parse_args()


if __name__ == "__main__":
    result = build(parse_args())
    print(json.dumps({"status": "written", "outputs": result["outputs"], "model_count": len(result["model_behavior"]), "case_count": len(result["case_parameter_matrix"])}, indent=2, sort_keys=True))
