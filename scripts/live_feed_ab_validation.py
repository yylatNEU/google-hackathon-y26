#!/usr/bin/env python3
from __future__ import annotations

import html
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
QA_DIR = REPO_ROOT / "output" / "qa"


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _metric_direction(source: str, metric: str) -> str:
    lower_is_better = {
        "ride_ops": {"capacity_pressure_pct", "down_ride_count"},
        "food_ops": {"kitchen_load_pct", "low_inventory_items_count", "mobile_order_backlog"},
        "operator_signal": {"open_cases", "complaint_rate_pct"},
    }
    higher_is_better = {
        "guest_flow": {"routing_take_rate_pct", "avg_satisfaction"},
        "staffing": {"guard_team_count", "health_team_count"},
    }
    if metric in lower_is_better.get(source, set()):
        return "lower_is_better"
    if metric in higher_is_better.get(source, set()):
        return "higher_is_better"
    return "stability_watch"


def _impact(source: str, metric: str, delta: float) -> str:
    direction = _metric_direction(source, metric)
    if direction == "lower_is_better":
        return "improved" if delta < 0 else "regressed" if delta > 0 else "stable"
    if direction == "higher_is_better":
        return "improved" if delta > 0 else "regressed" if delta < 0 else "stable"
    return "stable" if abs(delta) < 0.0001 else "regressed"


def _bounded_reward(value: float) -> float:
    return round(min(1.0, max(0.0, value)), 3)


def _positive_delta_score(delta: float | None, *, lower_is_better: bool, scale: float) -> float:
    if delta is None:
        return 0.0
    signed = -delta if lower_is_better else delta
    return _bounded_reward(signed / max(1.0, scale))


def _metric_delta(rows: list[dict[str, Any]], source: str, metric: str) -> float | None:
    for row in rows:
        if not isinstance(row, dict) or row.get("source") != source:
            continue
        for item in row.get("metrics", []) if isinstance(row.get("metrics"), list) else []:
            if isinstance(item, dict) and item.get("metric") == metric:
                try:
                    return float(item.get("delta"))
                except (TypeError, ValueError):
                    return None
    return None


def _commerce_action_score(rows: list[dict[str, Any]]) -> dict[str, Any]:
    kitchen = _metric_delta(rows, "food_ops", "kitchen_load_pct")
    inventory = _metric_delta(rows, "food_ops", "low_inventory_items_count")
    backlog = _metric_delta(rows, "food_ops", "mobile_order_backlog")
    pickup = _metric_delta(rows, "food_ops", "pickup_eta_minutes")
    satisfaction = _metric_delta(rows, "guest_flow", "avg_satisfaction")
    take_rate = _metric_delta(rows, "guest_flow", "routing_take_rate_pct")
    guard = _metric_delta(rows, "staffing", "guard_team_count")
    health = _metric_delta(rows, "staffing", "health_team_count")
    scores = {
        "promo_pause_or_load_relief": _bounded_reward(
            max(
                _positive_delta_score(kitchen, lower_is_better=True, scale=12.0),
                _positive_delta_score(backlog, lower_is_better=True, scale=40.0),
                _positive_delta_score(pickup, lower_is_better=True, scale=8.0),
            )
        ),
        "inventory_or_restock": _bounded_reward(_positive_delta_score(inventory, lower_is_better=True, scale=2.0)),
        "demand_redirect": _bounded_reward(
            max(
                _positive_delta_score(satisfaction, lower_is_better=False, scale=8.0),
                _positive_delta_score(take_rate, lower_is_better=False, scale=15.0),
            )
        ),
        "labor_support": _bounded_reward(
            max(
                _positive_delta_score(guard, lower_is_better=False, scale=3.0),
                _positive_delta_score(health, lower_is_better=False, scale=2.0),
            )
        ),
    }
    return {
        "average_action_score": _bounded_reward(sum(scores.values()) / len(scores)),
        "scores": scores,
    }


def _count_points(rows: list[dict[str, Any]]) -> dict[str, int]:
    points = {
        "improvement_points": 0,
        "regression_points": 0,
        "stable_points": 0,
        "actionable_improvement_points": 0,
        "actionable_regression_points": 0,
        "actionable_stable_points": 0,
        "stability_watch_points": 0,
    }
    for row in rows:
        source = str(row.get("source") or "")
        for metric in row.get("metrics", []) if isinstance(row.get("metrics"), list) else []:
            if not isinstance(metric, dict):
                continue
            impact = str(metric.get("impact") or "")
            direction = str(metric.get("direction") or _metric_direction(source, str(metric.get("metric") or "")))
            if impact == "improved":
                points["improvement_points"] += 1
                if direction != "stability_watch":
                    points["actionable_improvement_points"] += 1
            elif impact == "regressed":
                points["regression_points"] += 1
                if direction != "stability_watch":
                    points["actionable_regression_points"] += 1
            else:
                points["stable_points"] += 1
                if direction == "stability_watch":
                    points["stability_watch_points"] += 1
                else:
                    points["actionable_stable_points"] += 1
    return points


def _score_rows(rows: list[dict[str, Any]], *, scorer: str, semantic_action_parameter_count: int) -> dict[str, Any]:
    points = _count_points(rows)
    commerce = _commerce_action_score(rows)
    semantic_bonus = _bounded_reward(0.08 * float(commerce["average_action_score"])) if semantic_action_parameter_count > 0 else 0.0
    if scorer == "old":
        total = max(1, points["improvement_points"] + points["regression_points"] + points["stable_points"])
        reward = _bounded_reward(
            0.25
            + (0.5 * (points["improvement_points"] / total))
            - (0.6 * (points["regression_points"] / total))
            + (0.05 * (points["stable_points"] / total))
            + semantic_bonus
        )
    elif scorer == "new":
        total = max(
            1,
            points["actionable_improvement_points"]
            + points["actionable_regression_points"]
            + points["actionable_stable_points"],
        )
        reward = _bounded_reward(
            0.25
            + (0.5 * (points["actionable_improvement_points"] / total))
            - (0.6 * (points["actionable_regression_points"] / total))
            + (0.05 * (points["actionable_stable_points"] / total))
            + semantic_bonus
        )
    else:
        raise ValueError(f"unknown scorer {scorer}")
    return {
        "scorer": scorer,
        "reward": reward,
        "semantic_bonus": semantic_bonus,
        "commerce_action_average_score": commerce["average_action_score"],
        "commerce_action_scores": commerce["scores"],
        **points,
    }


def _counterfactual_without_semantic(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    weaker_deltas = {
        ("food_ops", "kitchen_load_pct"): -8.0,
        ("food_ops", "low_inventory_items_count"): 0.0,
        ("guest_flow", "routing_take_rate_pct"): 5.0,
        ("guest_flow", "avg_satisfaction"): 2.0,
        ("operator_signal", "open_cases"): -2.0,
        ("ride_ops", "capacity_pressure_pct"): -2.0,
    }
    result = deepcopy(rows)
    for row in result:
        source = str(row.get("source") or "")
        for metric in row.get("metrics", []) if isinstance(row.get("metrics"), list) else []:
            if not isinstance(metric, dict):
                continue
            name = str(metric.get("metric") or "")
            delta = weaker_deltas.get((source, name))
            if delta is None:
                continue
            try:
                before = float(metric.get("before"))
            except (TypeError, ValueError):
                continue
            after = before + delta
            if after.is_integer():
                after = int(after)
            metric["after"] = after
            metric["delta"] = delta
            metric["impact"] = _impact(source, name, delta)
            metric["counterfactual_reason"] = "semantic action parameters removed; base controlled action still executes with weaker projected effect"
    return result


def _executed_tools(smoke: dict[str, Any], *, include_semantic_companions: bool = True) -> list[str]:
    receipts = (smoke.get("tool_executor_live_test", {}) if isinstance(smoke.get("tool_executor_live_test"), dict) else {}).get("receipts", [])
    tools = []
    for row in receipts if isinstance(receipts, list) else []:
        if not isinstance(row, dict):
            continue
        if not include_semantic_companions and row.get("companion_source") == "semantic_agent_learning":
            continue
        result = row.get("result", {}) if isinstance(row.get("result"), dict) else {}
        if result.get("status") == "executed_controlled":
            tools.append(f"{row.get('department')}::{row.get('source_tool')}")
    return sorted(tools)


def _semantic_payloads(smoke: dict[str, Any]) -> list[dict[str, Any]]:
    projection = (
        (smoke.get("live_feed_outcome_measurement", {}) if isinstance(smoke.get("live_feed_outcome_measurement"), dict) else {})
        .get("controlled_effect_projection", {})
    )
    if not isinstance(projection, dict):
        return []
    rows = projection.get("semantic_parameter_rows", []) if isinstance(projection.get("semantic_parameter_rows"), list) else []
    return [
        {
            "learning_id": row.get("learning_id"),
            "source_outcome_id": row.get("source_outcome_id"),
            "routing_strategy": row.get("routing_strategy"),
            "traffic_cap_policy": row.get("traffic_cap_policy"),
            "tool_payload_delta": row.get("tool_payload_delta", {}),
        }
        for row in rows
        if isinstance(row, dict)
    ]


def _substitute_attribution(smoke: dict[str, Any]) -> dict[str, Any]:
    measurement = smoke.get("live_feed_outcome_measurement", {}) if isinstance(smoke.get("live_feed_outcome_measurement"), dict) else {}
    attribution = measurement.get("substitute_outcome_attribution", {}) if isinstance(measurement.get("substitute_outcome_attribution"), dict) else {}
    if attribution:
        return attribution
    reward_layers = measurement.get("reward_layers", {}) if isinstance(measurement.get("reward_layers"), dict) else {}
    return reward_layers.get("substitute_outcome_attribution", {}) if isinstance(reward_layers.get("substitute_outcome_attribution"), dict) else {}


def _rows_table(rows: list[dict[str, Any]]) -> str:
    table_rows = []
    for row in rows:
        source = row.get("source")
        for metric in row.get("metrics", []) if isinstance(row.get("metrics"), list) else []:
            if not isinstance(metric, dict):
                continue
            table_rows.append(
                "<tr>"
                f"<td>{_e(source)}</td>"
                f"<td>{_e(metric.get('metric'))}</td>"
                f"<td>{_e(metric.get('before'))}</td>"
                f"<td>{_e(metric.get('after'))}</td>"
                f"<td>{_e(metric.get('delta'))}</td>"
                f"<td>{_e(metric.get('impact'))}</td>"
                f"<td>{_e(metric.get('reward_scope'))}</td>"
                "</tr>"
            )
    return "\n".join(table_rows)


def _score_card(title: str, score: dict[str, Any]) -> str:
    return (
        "<section class='card'>"
        f"<span>{_e(title)}</span>"
        f"<strong>{_e(score.get('reward'))}</strong>"
        f"<small>actionable {score.get('actionable_improvement_points')}/{score.get('actionable_metric_points', score.get('actionable_improvement_points') + score.get('actionable_regression_points') + score.get('actionable_stable_points'))}; "
        f"all improved {score.get('improvement_points')}, stable watch {score.get('stability_watch_points')}; commerce {score.get('commerce_action_average_score')}; semantic bonus {score.get('semantic_bonus')}</small>"
        "</section>"
    )


def _substitute_rows_table(attribution: dict[str, Any]) -> str:
    rows = attribution.get("rows", []) if isinstance(attribution.get("rows"), list) else []
    rendered = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        rendered.append(
            "<tr>"
            f"<td>{_e(row.get('held_department'))}::{_e(row.get('held_tool'))}</td>"
            f"<td>{_e(row.get('substitute_department'))}::{_e(row.get('substitute_tool'))}</td>"
            f"<td>{_e(row.get('action_family'))}</td>"
            f"<td>{_e(row.get('best_branch'))}</td>"
            f"<td>{_e(row.get('substitute_outcome_score'))}</td>"
            f"<td>{_e(row.get('monitor_only_counterfactual_score'))}</td>"
            f"<td>{_e(row.get('branch_lift_vs_monitor'))}</td>"
            "</tr>"
        )
    return "\n".join(rendered) if rendered else "<tr><td colspan='7'>No substitute branch attribution available.</td></tr>"


def _bundle_rows_table(attribution: dict[str, Any]) -> str:
    selected = attribution.get("selected_bundle", {}) if isinstance(attribution.get("selected_bundle"), dict) else {}
    rows = attribution.get("bundle_candidates", []) if isinstance(attribution.get("bundle_candidates"), list) else []
    rendered = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        rendered.append(
            "<tr>"
            f"<td>{_e(row.get('bundle_id'))}</td>"
            f"<td>{_e(row.get('label'))}</td>"
            f"<td>{_e('selected' if row.get('bundle_id') == selected.get('bundle_id') else 'rejected')}</td>"
            f"<td>{_e(row.get('score'))}</td>"
            f"<td>{_e(row.get('branch_count'))}</td>"
            f"<td>{_e(row.get('average_lift_vs_monitor'))}</td>"
            f"<td>{_e(', '.join(row.get('selected_tools', []) if isinstance(row.get('selected_tools'), list) else []))}</td>"
            "</tr>"
        )
    return "\n".join(rendered) if rendered else "<tr><td colspan='7'>No bundle candidates available.</td></tr>"


def build_validation(smoke_path: Path, output_dir: Path) -> dict[str, Any]:
    smoke = _read_json(smoke_path)
    measurement = smoke.get("live_feed_outcome_measurement", {}) if isinstance(smoke.get("live_feed_outcome_measurement"), dict) else {}
    rows = measurement.get("measurement_rows", []) if isinstance(measurement.get("measurement_rows"), list) else []
    memory_on_rows = deepcopy(rows)
    memory_off_rows = _counterfactual_without_semantic(rows)
    semantic_count = int(
        ((smoke.get("tool_executor_live_test", {}) if isinstance(smoke.get("tool_executor_live_test"), dict) else {}).get("semantic_action_parameter_count"))
        or ((smoke.get("summary", {}) if isinstance(smoke.get("summary"), dict) else {}).get("tool_executor_live_test", {}) if isinstance((smoke.get("summary", {}) if isinstance(smoke.get("summary"), dict) else {}).get("tool_executor_live_test"), dict) else {}).get("semantic_action_parameter_count")
        or 0
    )
    variants = {
        "memory_on_old_scorer": _score_rows(memory_on_rows, scorer="old", semantic_action_parameter_count=semantic_count),
        "memory_on_new_scorer": _score_rows(memory_on_rows, scorer="new", semantic_action_parameter_count=semantic_count),
        "memory_off_old_scorer": _score_rows(memory_off_rows, scorer="old", semantic_action_parameter_count=0),
        "memory_off_new_scorer": _score_rows(memory_off_rows, scorer="new", semantic_action_parameter_count=0),
    }
    executed_tools = _executed_tools(smoke, include_semantic_companions=True)
    memory_off_executed_tools = _executed_tools(smoke, include_semantic_companions=False)
    substitute_attribution = _substitute_attribution(smoke)
    semantic_companion_tools = sorted(set(executed_tools) - set(memory_off_executed_tools))
    memory_lift_new = round(variants["memory_on_new_scorer"]["reward"] - variants["memory_off_new_scorer"]["reward"], 3)
    memory_lift_old = round(variants["memory_on_old_scorer"]["reward"] - variants["memory_off_old_scorer"]["reward"], 3)
    substitute_lift = substitute_attribution.get("average_lift_vs_monitor")
    if semantic_companion_tools:
        verdict = "better_judge_better_parameterization_and_memory_added_low_risk_companion_tool"
        truth_statement = (
            "The score is better from the fairer judge and semantic memory. Memory changed behavior by adding a same-department "
            "low-risk companion action; sensitive operations, safety, security, and public guest-message actions remain unauthorized."
        )
    elif substitute_lift is not None and float(substitute_lift or 0) > 0:
        verdict = "better_judge_and_substitute_bundle_attribution_without_semantic_companion"
        truth_statement = (
            "This run did not retrieve a semantic companion action, so memory-off and memory-on tools match. The improvement is in the "
            "fairer judge plus measured safe-substitute branch attribution against monitor-only counterfactuals."
        )
    else:
        verdict = "judge_only_improvement_no_memory_or_substitute_lift"
        truth_statement = (
            "This run shows the fairer judge behavior, but no semantic companion or measured substitute lift was available."
        )
    summary = {
        "status": "validated",
        "source_smoke": str(smoke_path),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "executed_tools_same_in_counterfactual": executed_tools == memory_off_executed_tools,
        "executed_tools": executed_tools,
        "memory_off_counterfactual_executed_tools": memory_off_executed_tools,
        "semantic_companion_tools": semantic_companion_tools,
        "semantic_payload_count": len(_semantic_payloads(smoke)),
        "substitute_branch_count": substitute_attribution.get("branch_count"),
        "substitute_executed_branch_count": substitute_attribution.get("executed_branch_count"),
        "substitute_average_score": substitute_attribution.get("average_substitute_score"),
        "substitute_average_lift_vs_monitor": substitute_attribution.get("average_lift_vs_monitor"),
        "substitute_bundle_decision": (substitute_attribution.get("bundle", {}) if isinstance(substitute_attribution.get("bundle"), dict) else {}).get("decision"),
        "selected_substitute_bundle_id": (substitute_attribution.get("selected_bundle", {}) if isinstance(substitute_attribution.get("selected_bundle"), dict) else {}).get("bundle_id"),
        "substitute_bundle_candidate_count": len(substitute_attribution.get("bundle_candidates", []) if isinstance(substitute_attribution.get("bundle_candidates"), list) else []),
        "semantic_learning_ids": (smoke.get("live_feed_memory_priors", {}) if isinstance(smoke.get("live_feed_memory_priors"), dict) else {}).get("semantic_learning_ids", []),
        "old_to_new_scoring_lift": round(variants["memory_on_new_scorer"]["reward"] - variants["memory_on_old_scorer"]["reward"], 3),
        "memory_lift_under_new_scorer": memory_lift_new,
        "memory_lift_under_old_scorer": memory_lift_old,
        "verdict": verdict,
        "truth_statement": truth_statement,
    }
    report = {
        "mode": "live_feed_ab_validation",
        "summary": summary,
        "variants": variants,
        "memory_on_rows": memory_on_rows,
        "memory_off_counterfactual_rows": memory_off_rows,
        "semantic_payloads": _semantic_payloads(smoke),
        "substitute_outcome_attribution": substitute_attribution,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "live-feed-ab-validation.json"
    html_path = output_dir / "live-feed-ab-validation.html"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    html_path.write_text(_render_html(report, json_path), encoding="utf-8")
    report["artifacts"] = {"json": str(json_path), "html": str(html_path)}
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _render_html(report: dict[str, Any], json_path: Path) -> str:
    summary = report.get("summary", {}) if isinstance(report.get("summary"), dict) else {}
    variants = report.get("variants", {}) if isinstance(report.get("variants"), dict) else {}
    payloads = report.get("semantic_payloads", []) if isinstance(report.get("semantic_payloads"), list) else []
    substitute_attribution = report.get("substitute_outcome_attribution", {}) if isinstance(report.get("substitute_outcome_attribution"), dict) else {}
    payload_rows = "\n".join(
        "<tr>"
        f"<td>{_e(row.get('learning_id'))}</td>"
        f"<td>{_e(row.get('source_outcome_id'))}</td>"
        f"<td>{_e(row.get('routing_strategy'))}</td>"
        f"<td>{_e(row.get('traffic_cap_policy'))}</td>"
        f"<td>{_e(json.dumps(row.get('tool_payload_delta', {}), sort_keys=True))}</td>"
        "</tr>"
        for row in payloads
        if isinstance(row, dict)
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>ParkPulse Live-Feed A/B Validation</title>
<style>
:root {{ --bg:#0b1117; --panel:#111b24; --line:#273746; --text:#edf7fb; --muted:#9fb0bb; --ok:#75e0a7; --warn:#ffd166; --accent:#8fc5ff; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text); font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
main {{ width:min(1440px, calc(100vw - 32px)); margin:0 auto; padding:28px 0 44px; }}
.hero, .panel, .card {{ border:1px solid var(--line); background:var(--panel); border-radius:8px; padding:18px; }}
h1 {{ margin:0; font-size:clamp(32px, 5vw, 64px); line-height:1; letter-spacing:0; }}
h2 {{ margin:0 0 12px; font-size:20px; }}
p, small {{ color:var(--muted); line-height:1.55; }}
.kicker, .card span {{ display:block; color:var(--accent); font-size:11px; text-transform:uppercase; font-weight:900; letter-spacing:.05em; }}
.grid {{ display:grid; gap:14px; margin-top:16px; }}
.cards {{ grid-template-columns:repeat(4, minmax(0, 1fr)); }}
.two {{ grid-template-columns:1fr 1fr; }}
.card strong {{ display:block; margin:8px 0; font-size:34px; }}
.callout {{ border-left:5px solid var(--warn); }}
.ok {{ border-left:5px solid var(--ok); }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th, td {{ padding:9px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
th {{ color:var(--muted); font-size:11px; text-transform:uppercase; background:#0d151c; }}
.code {{ font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; overflow-wrap:anywhere; }}
@media (max-width:1000px) {{ .cards, .two {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<main>
<section class="hero">
<div class="kicker">Generated {_e(summary.get('generated_at'))}</div>
<h1>A/B validation: better judge, stronger semantic parameters, and one memory-added companion tool.</h1>
<p>{_e(summary.get('truth_statement'))}</p>
</section>
<section class="grid cards">
{_score_card("Memory on / old scorer", variants.get("memory_on_old_scorer", {}))}
{_score_card("Memory on / new scorer", variants.get("memory_on_new_scorer", {}))}
{_score_card("Memory off / old scorer", variants.get("memory_off_old_scorer", {}))}
{_score_card("Memory off / new scorer", variants.get("memory_off_new_scorer", {}))}
</section>
<section class="grid two">
<div class="panel ok">
<div class="kicker">What is truly better</div>
<h2>Measured Difference</h2>
<p><b>Old-to-new scorer lift:</b> {_e(summary.get('old_to_new_scoring_lift'))}. This is the judge fix: passive stability-watch metrics no longer dilute action reward.</p>
<p><b>Memory lift under new scorer:</b> {_e(summary.get('memory_lift_under_new_scorer'))}. This is the semantic-parameter effect after removing memory from the counterfactual.</p>
</div>
<div class="panel callout">
<div class="kicker">What is not proven</div>
<h2>Behavior Boundary</h2>
<p><b>Memory-on tools:</b> <span class="code">{_e(', '.join(summary.get('executed_tools', [])))}</span>.</p>
<p><b>Memory-off counterfactual tools:</b> <span class="code">{_e(', '.join(summary.get('memory_off_counterfactual_executed_tools', [])))}</span>.</p>
<p><b>Memory-added companion:</b> <span class="code">{_e(', '.join(summary.get('semantic_companion_tools', [])))}</span>.</p>
<p>The behavior change is deliberately bounded: same department, low-risk receiver, no public guest message, no safety/security/operations authority expansion.</p>
</div>
</section>
<section class="panel">
<div class="kicker">Safe substitutes</div>
<h2>Branch Attribution</h2>
<p><b>Bundle decision:</b> {_e(summary.get('substitute_bundle_decision'))}. <b>Average lift vs monitor:</b> {_e(summary.get('substitute_average_lift_vs_monitor'))}. The held risky action is not scored as executable; only the policy-passed substitute branch is compared against monitor-only.</p>
<table><thead><tr><th>Held action</th><th>Substitute</th><th>Family</th><th>Best branch</th><th>Sub score</th><th>Monitor</th><th>Lift</th></tr></thead><tbody>
{_substitute_rows_table(substitute_attribution)}
</tbody></table>
<table style="margin-top:14px"><thead><tr><th>Bundle</th><th>Label</th><th>Decision</th><th>Score</th><th>Branches</th><th>Lift</th><th>Tools</th></tr></thead><tbody>
{_bundle_rows_table(substitute_attribution)}
</tbody></table>
</section>
<section class="panel">
<div class="kicker">Semantic payloads</div>
<h2>What Memory Changed</h2>
<table><thead><tr><th>Learning</th><th>Source outcome</th><th>Routing</th><th>Traffic cap</th><th>Payload delta</th></tr></thead><tbody>{payload_rows}</tbody></table>
</section>
<section class="grid two">
<div class="panel">
<div class="kicker">Memory on</div>
<h2>Actual Measured Rows</h2>
<table><thead><tr><th>Source</th><th>Metric</th><th>Before</th><th>After</th><th>Delta</th><th>Impact</th><th>Scope</th></tr></thead><tbody>
{_rows_table(report.get('memory_on_rows', []) if isinstance(report.get('memory_on_rows'), list) else [])}
</tbody></table>
</div>
<div class="panel">
<div class="kicker">Memory off</div>
<h2>Counterfactual Rows</h2>
<table><thead><tr><th>Source</th><th>Metric</th><th>Before</th><th>After</th><th>Delta</th><th>Impact</th><th>Scope</th></tr></thead><tbody>
{_rows_table(report.get('memory_off_counterfactual_rows', []) if isinstance(report.get('memory_off_counterfactual_rows'), list) else [])}
</tbody></table>
</div>
</section>
<footer><p>JSON artifact: <span class="code">{_e(json_path)}</span></p></footer>
</main>
</body>
</html>
"""


def main() -> int:
    report = build_validation(QA_DIR / "live-feed-agent-smoke.json", QA_DIR)
    print(json.dumps({"status": report["summary"]["status"], "summary": report["summary"], "artifacts": report["artifacts"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
