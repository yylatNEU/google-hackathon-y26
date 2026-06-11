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
    return round(sum(filtered) / len(filtered), 3) if filtered else None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _round(value: Any, digits: int = 3) -> float | None:
    number = _num(value)
    return round(number, digits) if number is not None else None


def _episode(cycle: dict[str, Any]) -> dict[str, Any]:
    return _get(cycle, ["actions", "risk_escalation_episode_fitness"], {}) or {}


def _digest(cycle: dict[str, Any], label: str) -> dict[str, Any]:
    return _get(_episode(cycle), ["digests", label], {}) or {}


def _path_congestion(cycle: dict[str, Any], branch: str) -> float | None:
    return _num(_get(_digest(cycle, branch), ["topPath", "congestionLevel"]))


def _satisfaction(cycle: dict[str, Any], branch: str) -> float | None:
    return _num(_digest(cycle, branch).get("avgSatisfaction"))


def _episode_metric(cycle: dict[str, Any], metric: str) -> float | None:
    return _num(_get(_episode(cycle), ["metrics", "actual", metric]))


def _baseline_metric(cycle: dict[str, Any], metric: str) -> float | None:
    return _num(_get(_episode(cycle), ["metrics", "baseline", metric]))


def _safety_score(cycle: dict[str, Any], branch: str) -> float | None:
    metric_branch = "actual" if branch == "actual_after" else "baseline"
    violations = _num(_get(_episode(cycle), ["metrics", metric_branch, "safety_violations"]))
    if violations is None:
        return None
    escalation = str(_get(_digest(cycle, branch), ["incidentReadiness", "operatorEscalation"]) or "")
    score = 100 - 20 * violations
    if escalation and escalation != "required":
        score += 10
    return round(_clamp(score), 2)


def _congestion_score(cycle: dict[str, Any], branch: str) -> float | None:
    before = _path_congestion(cycle, "before")
    after = _path_congestion(cycle, branch)
    if before is None or after is None:
        return None
    return round(_clamp(50 + before - after), 2)


def _interpolate(baseline: float | None, current: float | None, factor: float) -> float | None:
    if baseline is None or current is None:
        return None
    return round(baseline + (current - baseline) * factor, 3)


def _scenario_index(report: dict[str, Any], path: list[Any]) -> dict[str, dict[str, Any]]:
    rows = _get(report, path, []) or []
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("scenario_key"):
            indexed[str(row["scenario_key"])] = row
    return indexed


def _baseline_monitor_score(cycle: dict[str, Any]) -> float:
    rows = _get(cycle, ["measurement", "reward_layers", "substitute_outcome_attribution", "rows"], []) or []
    scores = [row.get("monitor_only_counterfactual_score") for row in rows if isinstance(row, dict)]
    return _avg(scores) or 0.05


def _hard_decision_activation(cycle: dict[str, Any]) -> tuple[float, str]:
    layers = _get(cycle, ["measurement", "reward_layers"], {}) or {}
    if not isinstance(layers, dict):
        return 0.0, "hard_decision_missing_layers"
    explicit = _num(layers.get("hard_decision_activation_reward"))
    label = str(layers.get("hard_decision_activation_label") or "")
    if explicit is not None:
        return round(explicit * 100, 3), label or "hard_decision_scored"
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
    return round(score * 100, 3), inferred_label


def build(args: argparse.Namespace) -> dict[str, Any]:
    current_path = (ROOT / args.current).resolve()
    previous_path = (ROOT / args.previous).resolve()
    output_dir = (ROOT / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    current = _read_json(current_path)
    previous = _read_json(previous_path)
    current_scenarios = _scenario_index(current, ["actual_training", "model_ops", "scenario_fitness", "scenarios"])
    previous_scenarios = _scenario_index(previous, ["actual_training_status", "model_ops", "scenario_fitness", "scenarios"])
    previous_summary = previous.get("summary", {}) if isinstance(previous.get("summary"), dict) else {}
    previous_blockers = previous_summary.get("blockers", []) if isinstance(previous_summary.get("blockers"), list) else []
    previous_deployed_gate_blocked = bool(previous_blockers)
    rows = []
    cycles = current.get("cycles", []) if isinstance(current.get("cycles"), list) else []
    for index, cycle in enumerate(cycles):
        if not isinstance(cycle, dict):
            continue
        scenario_key = str(_get(cycle, ["ml_policy", "scenario_key"]) or "unknown")
        previous_slice = previous_scenarios.get(scenario_key, {})
        current_slice = current_scenarios.get(scenario_key, {})
        previous_decision = str(previous_slice.get("decision") or "unknown")
        current_decision = str(current_slice.get("decision") or _get(cycle, ["ml_policy", "slice_decision"]) or "unknown")
        previous_reward = _num(previous_slice.get("latest_average_reward"))
        current_reward = _num(current_slice.get("latest_average_reward"))
        replay_factor = 0.0
        replay_reason = "previous_slice_not_promoted"
        if previous_decision == "promote_slice" and current_reward and previous_reward:
            replay_factor = _clamp(previous_reward / current_reward, 0.0, 1.05)
            replay_reason = "previous_promoted_slice_scaled_by_archived_reward_strength"
        if previous_deployed_gate_blocked:
            deployed_factor = 0.0
            deployed_reason = "previous_snapshot_global_gate_held_by_stale_live_feeds"
        else:
            deployed_factor = replay_factor
            deployed_reason = replay_reason
        current_operational = _num(_get(cycle, ["measurement", "reward_layers", "operational_reward"]))
        baseline_reward = _baseline_monitor_score(cycle)
        current_safety = _safety_score(cycle, "actual_after")
        baseline_safety = _safety_score(cycle, "baseline_after")
        current_congestion = _congestion_score(cycle, "actual_after")
        baseline_congestion = _congestion_score(cycle, "baseline_after")
        current_satisfaction = _satisfaction(cycle, "actual_after")
        baseline_satisfaction = _satisfaction(cycle, "baseline_after")
        current_hard_decision, current_hard_decision_label = _hard_decision_activation(cycle)
        previous_replay = {
            "action": "execute_previous_promoted_slice_policy" if replay_factor > 0 else "monitor_only_hold",
            "factor": round(replay_factor, 3),
            "reason": replay_reason,
            "safety_score": _interpolate(baseline_safety, current_safety, replay_factor),
            "congestion_score": _interpolate(baseline_congestion, current_congestion, replay_factor),
            "satisfaction_score": _interpolate(baseline_satisfaction, current_satisfaction, replay_factor),
            "hard_decision_score": _interpolate(0.0, current_hard_decision, replay_factor),
            "operational_reward": _interpolate(baseline_reward, current_operational, replay_factor),
        }
        previous_as_deployed = {
            "action": "monitor_only_hold" if deployed_factor == 0 else previous_replay["action"],
            "factor": round(deployed_factor, 3),
            "reason": deployed_reason,
            "safety_score": _interpolate(baseline_safety, current_safety, deployed_factor),
            "congestion_score": _interpolate(baseline_congestion, current_congestion, deployed_factor),
            "satisfaction_score": _interpolate(baseline_satisfaction, current_satisfaction, deployed_factor),
            "hard_decision_score": _interpolate(0.0, current_hard_decision, deployed_factor),
            "operational_reward": _interpolate(baseline_reward, current_operational, deployed_factor),
        }
        rows.append(
            {
                "case_key": f"cycle_{cycle.get('cycle')}",
                "json_pointer": f"/cycles/{index}",
                "issue_kind": _get(cycle, ["issue", "kind"]),
                "target_id": _get(cycle, ["issue", "target_id"]),
                "intensity": _get(cycle, ["issue", "intensity"]),
                "scenario_key": scenario_key,
                "current_decision": current_decision,
                "previous_decision": previous_decision,
                "current": {
                    "action": "execute_controlled_plus_risk_lift",
                    "safety_score": current_safety,
                    "congestion_score": current_congestion,
                    "satisfaction_score": current_satisfaction,
                    "hard_decision_score": current_hard_decision,
                    "hard_decision_label": current_hard_decision_label,
                    "operational_reward": _round(current_operational),
                    "executed_count": _get(cycle, ["actions", "executed_count"]),
                    "held_count": _get(cycle, ["actions", "held_count"]),
                    "risk_lift_label": _get(cycle, ["measurement", "reward_layers", "risk_lift_label"]),
                },
                "previous_policy_replay": previous_replay,
                "previous_as_deployed": previous_as_deployed,
                "baseline": {
                    "action": "monitor_only_hold",
                    "safety_score": baseline_safety,
                    "congestion_score": baseline_congestion,
                    "satisfaction_score": baseline_satisfaction,
                    "hard_decision_score": 0.0,
                    "operational_reward": baseline_reward,
                },
                "park_parameters": {
                    "path_congestion_before": _path_congestion(cycle, "before"),
                    "path_congestion_current_after": _path_congestion(cycle, "actual_after"),
                    "path_congestion_baseline_after": _path_congestion(cycle, "baseline_after"),
                    "satisfaction_before": _satisfaction(cycle, "before"),
                    "current_pressure_reduction_vs_baseline": _get(_episode(cycle), ["pressure", "reduction_vs_baseline"]),
                    "actual_safety_violations": _episode_metric(cycle, "safety_violations"),
                    "baseline_safety_violations": _baseline_metric(cycle, "safety_violations"),
                },
            }
        )

    def model_average(label: str, key: str) -> float | None:
        return _avg([_get(row, [label, key]) for row in rows])

    summary = {
        "case_count": len(rows),
        "previous_snapshot_gate": previous_summary.get("promotion_gate_status"),
        "previous_snapshot_decision": previous_summary.get("promotion_decision"),
        "previous_snapshot_blocker_count": len(previous_blockers),
        "current_average": {
            "safety": model_average("current", "safety_score"),
            "congestion": model_average("current", "congestion_score"),
            "satisfaction": model_average("current", "satisfaction_score"),
            "hard_decision": model_average("current", "hard_decision_score"),
            "operational_reward": model_average("current", "operational_reward"),
        },
        "previous_policy_replay_average": {
            "safety": model_average("previous_policy_replay", "safety_score"),
            "congestion": model_average("previous_policy_replay", "congestion_score"),
            "satisfaction": model_average("previous_policy_replay", "satisfaction_score"),
            "hard_decision": model_average("previous_policy_replay", "hard_decision_score"),
            "operational_reward": model_average("previous_policy_replay", "operational_reward"),
            "average_replay_factor": _avg([_get(row, ["previous_policy_replay", "factor"]) for row in rows]),
        },
        "previous_as_deployed_average": {
            "safety": model_average("previous_as_deployed", "safety_score"),
            "congestion": model_average("previous_as_deployed", "congestion_score"),
            "satisfaction": model_average("previous_as_deployed", "satisfaction_score"),
            "hard_decision": model_average("previous_as_deployed", "hard_decision_score"),
            "operational_reward": model_average("previous_as_deployed", "operational_reward"),
        },
        "baseline_average": {
            "safety": model_average("baseline", "safety_score"),
            "congestion": model_average("baseline", "congestion_score"),
            "satisfaction": model_average("baseline", "satisfaction_score"),
            "hard_decision": model_average("baseline", "hard_decision_score"),
            "operational_reward": model_average("baseline", "operational_reward"),
        },
    }
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "previous_model_replay_case_comparison",
        "inputs": {
            "current_live_feed_report": str(current_path.relative_to(ROOT)),
            "previous_model_snapshot": str(previous_path.relative_to(ROOT)),
        },
        "replay_contract": {
            "previous_as_deployed": "Uses the archived previous snapshot exactly: because its global promotion gate had stale live-feed blockers, it falls back to monitor-only on these cases.",
            "previous_policy_replay_with_fresh_feeds": "Applies previous per-scenario slice decisions to the same cases. If the previous slice was promotable, it receives a replay factor = previous slice latest reward / current slice latest reward, capped at 1.05. Scores interpolate between monitor-only baseline and current observed outcome.",
            "current": "Observed outcome from the fresh live-feed run.",
            "baseline": "Same-case no-action/monitor-only counterfactual from the live episode.",
        },
        "summary": summary,
        "case_replay_matrix": rows,
    }
    output_json = output_dir / "previous-model-replay-case-comparison.json"
    output_html = output_dir / "previous-model-replay-case-comparison.html"
    payload["outputs"] = {
        "json": str(output_json.relative_to(ROOT)),
        "html": str(output_html.relative_to(ROOT)),
    }
    output_json.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    output_html.write_text(_render_html(payload), encoding="utf-8")
    return payload


def _esc(value: Any) -> str:
    return html.escape(str("" if value is None else value))


def _bar(value: Any) -> str:
    number = _num(value)
    if number is None:
        return '<div class="bar muted"><i style="width:0%"></i><span>n/a</span></div>'
    width = _clamp(number)
    return f'<div class="bar"><i style="width:{width:.1f}%"></i><span>{_esc(round(number, 2))}</span></div>'


def _render_html(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    rows = payload["case_replay_matrix"]

    def metric(label: str, value: Any, note: str = "") -> str:
        return f'<div class="metric"><span>{_esc(label)}</span><strong>{_esc(value)}</strong><small>{_esc(note)}</small></div>'

    avg = summary
    cards = [
        ("Current observed", avg["current_average"], "Actual fresh live-feed run"),
        ("Previous policy replay", avg["previous_policy_replay_average"], "Archived previous slices rerun on same cases"),
        ("Previous as deployed", avg["previous_as_deployed_average"], "Held by old stale-feed gate"),
        ("Baseline", avg["baseline_average"], "Monitor-only no-action counterfactual"),
    ]
    card_html = "\n".join(
        f"""
        <article class="card">
          <h3>{_esc(name)}</h3>
          <small>{_esc(note)}</small>
          <div><b>Safety</b>{_bar(values.get('safety'))}</div>
          <div><b>Congestion</b>{_bar(values.get('congestion'))}</div>
          <div><b>Satisfaction</b>{_bar(values.get('satisfaction'))}</div>
          <div><b>Hard decision</b>{_bar(values.get('hard_decision'))}</div>
          <div><b>Reward</b>{_bar((values.get('operational_reward') or 0) * 100 if isinstance(values.get('operational_reward'), (int, float)) else values.get('operational_reward'))}</div>
        </article>
        """
        for name, values, note in cards
    )
    body = "\n".join(
        "<tr>"
        f"<td>{_esc(row['case_key'])}<br><small>{_esc(row['issue_kind'])} at {_esc(row['target_id'])}</small></td>"
        f"<td>{_esc(row['scenario_key'])}<br><small>current {_esc(row['current_decision'])}, previous {_esc(row['previous_decision'])}</small></td>"
        f"<td>{_bar(row['current']['congestion_score'])}<small>{_esc(row['current']['action'])}</small></td>"
        f"<td>{_bar(row['previous_policy_replay']['congestion_score'])}<small>factor {_esc(row['previous_policy_replay']['factor'])}</small></td>"
        f"<td>{_bar(row['previous_as_deployed']['congestion_score'])}<small>{_esc(row['previous_as_deployed']['reason'])}</small></td>"
        f"<td>{_bar(row['baseline']['congestion_score'])}<small>{_esc(row['baseline']['action'])}</small></td>"
        f"<td>{_bar(row['current']['hard_decision_score'])}<small>{_esc(row['current']['hard_decision_label'])}</small></td>"
        f"<td>{_esc(row['park_parameters']['path_congestion_before'])} -> {_esc(row['park_parameters']['path_congestion_current_after'])} current<br><small>{_esc(row['park_parameters']['path_congestion_before'])} -> {_esc(row['park_parameters']['path_congestion_baseline_after'])} baseline</small></td>"
        "</tr>"
        for row in rows
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Previous Model Replay Case Comparison</title>
<style>
:root{{--ink:#17212b;--muted:#607080;--line:#dbe2e8;--panel:#f7f9fb;--ok:#0b7a55;--warn:#9a5a00;--blue:#2458a6}}
body{{margin:0;font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--ink)}} main{{max-width:1280px;margin:0 auto;padding:28px}}
h1{{font-size:28px;margin:0 0 6px}} h2{{font-size:18px;margin:28px 0 10px}} p,small{{color:var(--muted)}} .grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:18px 0}}
.metric,.card{{border:1px solid var(--line);background:var(--panel);border-radius:8px;padding:12px}} .metric span,.metric small{{display:block;color:var(--muted);font-size:12px}} .metric strong{{font-size:22px;display:block;margin:4px 0}}
.cards{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:18px 0}} .card h3{{margin:0 0 6px;font-size:16px}} .card b{{display:block;margin-top:10px}}
.bar{{position:relative;height:24px;border:1px solid var(--line);background:#fff;border-radius:5px;overflow:hidden}} .bar i{{display:block;height:100%;background:linear-gradient(90deg,#77b7a0,#2458a6)}} .bar span{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-weight:700}} .bar.muted{{background:#eef2f6}}
.panel{{border:1px solid var(--line);border-radius:8px;padding:16px;overflow:auto;margin:14px 0}} table{{width:100%;border-collapse:collapse;min-width:1100px}} th,td{{text-align:left;vertical-align:top;border-bottom:1px solid var(--line);padding:8px}} th{{font-size:12px;color:var(--muted);background:var(--panel);position:sticky;top:0}}
.note{{border-left:4px solid var(--warn);background:#fff8ef;border-radius:6px;padding:12px}} code{{background:#eef2f6;padding:2px 5px;border-radius:5px}}
@media(max-width:980px){{.grid,.cards{{grid-template-columns:1fr 1fr}}main{{padding:18px}}}}
</style></head>
<body><main>
<h1>Previous Model Replay Case Comparison</h1>
<p>Generated {_esc(payload['generated_at'])}. This enriches the case comparison by applying the archived previous model snapshot to the same live-feed cases.</p>
<section class="note"><b>Replay boundary:</b> this is not an old binary redeploy. It is a deterministic counterfactual replay from the archived previous model snapshot. The report keeps both views: previous as deployed, and previous policy replay with fresh feeds.</section>
<div class="grid">
{metric('Cases', summary['case_count'], 'same 8 live-feed cases')}
{metric('Previous snapshot gate', summary['previous_snapshot_gate'], summary['previous_snapshot_decision'])}
{metric('Previous blockers', summary['previous_snapshot_blocker_count'], 'why as-deployed holds')}
{metric('Avg replay factor', summary['previous_policy_replay_average'].get('average_replay_factor'), 'previous/current slice strength')}
</div>
<div class="cards">{card_html}</div>
<section class="panel"><h2>Case Replay Matrix</h2>
<table><thead><tr><th>Case</th><th>Scenario</th><th>Current observed</th><th>Previous policy replay</th><th>Previous as deployed</th><th>Baseline</th><th>Hard decision</th><th>Park congestion</th></tr></thead><tbody>{body}</tbody></table>
</section>
<section class="panel"><h2>Formula</h2>
<p><code>previous replay factor = previous slice latest reward / current slice latest reward</code>, capped at <code>1.05</code>. If the previous slice was not promotable, factor is <code>0</code>. Scores interpolate between same-case baseline and current observed outcome.</p>
<p>JSON: <code>{_esc(payload['outputs']['json'])}</code></p>
</section>
</main></body></html>"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay archived previous model snapshot against current live-feed cases.")
    parser.add_argument("--current", default="output/qa/live-feed-model-comparison-20260605-202000/live-feed-operating-cycle.json")
    parser.add_argument("--previous", default="output/qa/promotion-recovery-eval-20260605/promotion-recovery-eval.json")
    parser.add_argument("--output-dir", default="output/qa/live-feed-model-comparison-20260605-202000")
    return parser.parse_args()


if __name__ == "__main__":
    result = build(parse_args())
    print(json.dumps({"status": "written", "outputs": result["outputs"], "summary": result["summary"]}, indent=2, sort_keys=True))
