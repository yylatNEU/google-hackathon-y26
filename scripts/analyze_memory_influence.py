#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "output" / "qa"

LOWER_IS_BETTER = {
    "slowest_ride_wait_delta",
    "food_backlog_delta",
    "food_eta_minutes_delta",
    "busiest_zone_density_delta",
    "path_congestion_delta",
    "open_callouts_delta",
    "grid_load_delta",
}
HIGHER_IS_BETTER = {"avg_satisfaction_delta"}
CALIBRATION_METRICS = [
    "avg_satisfaction_delta",
    "slowest_ride_wait_delta",
    "food_backlog_delta",
    "food_eta_minutes_delta",
    "path_congestion_delta",
    "open_callouts_delta",
]
CASE_METRICS = [
    ("satisfaction_delta", True, 0.1),
    ("wait_delta", False, 0.5),
    ("food_delta", False, 5.0),
    ("eta_delta", False, 0.5),
]


def _now_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _load_json(path: Path) -> dict[str, Any]:
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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def _html_table(rows: list[list[Any]], headers: list[str]) -> str:
    head = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(_fmt(cell))}</td>" for cell in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _find_gemini_calls(case: dict[str, Any]) -> Path | None:
    run_dir = Path(str(case.get("candidate_run") or ""))
    direct = run_dir / "gemini-operation-calls.jsonl"
    if direct.exists():
        return direct
    matches = list(run_dir.glob("**/gemini-operation-calls.jsonl"))
    return matches[0] if matches else None


def _action_key(action: dict[str, Any] | None) -> str:
    if not isinstance(action, dict):
        return "none"
    return f"{action.get('target')}/{action.get('action')}"


def _action_family(action_key: str) -> str:
    if action_key in {"food/suppress_item", "food/pause_mobile_order_intake", "food/open_temp_pickup", "staff/redeploy_food_certified"}:
        return "food_service"
    if action_key in {"ride/reroute", "traffic/redirect_food"}:
        return "guest_flow"
    if action_key == "staff/redeploy":
        return "staffing"
    if action_key == "energy/protect_hvac":
        return "energy"
    if action_key == "signage/update":
        return "signage"
    return "none"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _get(row: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = row
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return default
    return current


def _candidate_relative(row: dict[str, Any]) -> dict[str, float]:
    relative = _get(row, "selected_policy_candidate.counterfactual.relative_to_no_action", {})
    if not isinstance(relative, dict):
        return {}
    return {str(key): _num(value) for key, value in relative.items()}


def _observed_effect(row: dict[str, Any]) -> dict[str, float]:
    actual = _get(row, "execution.episode_fitness.metrics.actual", {})
    baseline = _get(row, "execution.episode_fitness.metrics.baseline", {})
    if not isinstance(actual, dict) or not isinstance(baseline, dict):
        return {}
    mapped = {
        "avg_satisfaction_delta": _num(actual.get("avg_satisfaction_delta")) - _num(baseline.get("avg_satisfaction_delta")),
        "slowest_ride_wait_delta": _num(actual.get("slowest_ride_wait_delta")) - _num(baseline.get("slowest_ride_wait_delta")),
        "food_backlog_delta": _num(actual.get("food_backlog_delta")) - _num(baseline.get("food_backlog_delta")),
        "path_congestion_delta": _num(actual.get("path_congestion_delta")) - _num(baseline.get("path_congestion_delta")),
        "open_callouts_delta": _num(actual.get("staff_callout_delta")) - _num(baseline.get("staff_callout_delta")),
        "grid_load_delta": _num(actual.get("grid_load_delta")) - _num(baseline.get("grid_load_delta")),
    }
    before = row.get("before_digest", {}) if isinstance(row.get("before_digest"), dict) else {}
    after = row.get("after_digest", {}) if isinstance(row.get("after_digest"), dict) else {}
    if before and after:
        mapped["food_eta_minutes_delta"] = _num(after.get("food_eta_minutes")) - _num(before.get("food_eta_minutes"))
    return mapped


def _memory_role(memory: dict[str, Any]) -> str:
    examples = memory.get("examples") if isinstance(memory.get("examples"), list) else []
    cautionary = memory.get("cautionary_examples") if isinstance(memory.get("cautionary_examples"), list) else []
    if examples:
        return "direct"
    if cautionary:
        return "cautionary"
    status = str(memory.get("status") or "none")
    if status.startswith("abstained"):
        return "abstained"
    return status


def _memory_ideal_ids(memory: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for key in ("examples", "cautionary_examples"):
        values = memory.get(key) if isinstance(memory.get(key), list) else []
        for item in values:
            if isinstance(item, dict) and item.get("ideal_candidate_id"):
                ids.add(str(item["ideal_candidate_id"]))
    return ids


def _local_effect_label(effect: dict[str, float]) -> str:
    if not effect:
        return "unknown"
    good = 0
    bad = 0
    for metric in CALIBRATION_METRICS:
        value = effect.get(metric)
        if value is None:
            continue
        if metric in HIGHER_IS_BETTER:
            good += value > 0.1
            bad += value < -0.1
        else:
            good += value < -0.5
            bad += value > 0.5
    if good > bad:
        return "helpful_local_effect"
    if bad > good:
        return "harmful_local_effect"
    return "mixed_local_effect"


def _case_influence(memory_case: dict[str, Any], control_case: dict[str, Any] | None) -> dict[str, Any]:
    if not control_case:
        return {"label": "no_control", "improved": [], "worsened": [], "flat": []}
    improved: list[str] = []
    worsened: list[str] = []
    flat: list[str] = []
    for key, higher_better, tolerance in CASE_METRICS:
        memory_value = _num(memory_case.get(key))
        control_value = _num(control_case.get(key))
        delta = memory_value - control_value
        if higher_better:
            if delta > tolerance:
                improved.append(key)
            elif delta < -tolerance:
                worsened.append(key)
            else:
                flat.append(key)
        else:
            if delta < -tolerance:
                improved.append(key)
            elif delta > tolerance:
                worsened.append(key)
            else:
                flat.append(key)
    label = "memory_helped" if len(improved) > len(worsened) else "memory_hurt" if len(worsened) > len(improved) else "mixed"
    return {"label": label, "improved": improved, "worsened": worsened, "flat": flat}


def _avg(values: list[float]) -> float:
    return round(mean(values), 3) if values else 0.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _calibration_multiplier(predicted: float, observed: float) -> float | None:
    if abs(predicted) < 1.0:
        return None
    if predicted == 0:
        return None
    if (predicted < 0 < observed) or (predicted > 0 > observed):
        return 0.25
    ratio = abs(observed) / max(1.0, abs(predicted))
    return round(_clamp(ratio, 0.25, 1.25), 3)


def _build_score_calibration(calibration_rows: list[dict[str, Any]]) -> dict[str, Any]:
    adjustments: dict[str, dict[str, float]] = {}
    evidence: dict[str, dict[str, Any]] = {}
    for row in calibration_rows:
        action = str(row.get("action") or "")
        if not action or int(row.get("count") or 0) < 3:
            continue
        metric_adjustments: dict[str, float] = {}
        metric_evidence: dict[str, Any] = {}
        for metric in CALIBRATION_METRICS:
            predicted = _num(row.get(f"predicted_{metric}"))
            observed = _num(row.get(f"observed_{metric}"))
            multiplier = _calibration_multiplier(predicted, observed)
            if multiplier is None:
                continue
            metric_adjustments[metric] = multiplier
            metric_evidence[metric] = {
                "predicted": predicted,
                "observed": observed,
                "multiplier": multiplier,
                "sample_count": row.get("count"),
            }
        if metric_adjustments:
            adjustments[action] = metric_adjustments
            evidence[action] = metric_evidence
    return {
        "version": "timelapse-score-calibration-v1",
        "created_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": "memory_influence_action_calibration",
        "policy": {
            "description": "Multiply candidate relative_to_no_action deltas before ranked-action scoring when historical observed effects are weaker or stronger than predictions.",
            "min_action_samples": 3,
            "multiplier_bounds": [0.25, 1.25],
            "lower_is_better_metrics": sorted(LOWER_IS_BETTER),
            "higher_is_better_metrics": sorted(HIGHER_IS_BETTER),
        },
        "action_metric_multipliers": adjustments,
        "evidence": evidence,
    }


def _analyze_calls(report: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []
    calibration: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "predicted": defaultdict(list), "observed": defaultdict(list), "memory_roles": Counter()})
    for case in report.get("cases", []):
        calls_path = _find_gemini_calls(case)
        if not calls_path:
            continue
        for row in _load_jsonl(calls_path):
            memory = row.get("memory_context", {}) if isinstance(row.get("memory_context"), dict) else {}
            role = _memory_role(memory)
            selected = row.get("selected_policy_candidate", {}) if isinstance(row.get("selected_policy_candidate"), dict) else {}
            selected_id = str(selected.get("id") or _get(row, "candidate_selection.selected_candidate_id", ""))
            action_key = _action_key(row.get("allowed_action"))
            prediction = _candidate_relative(row)
            observed = _observed_effect(row)
            local_effect = _local_effect_label(observed)
            ideal_ids = _memory_ideal_ids(memory)
            aligned = selected_id in ideal_ids if ideal_ids else False
            call = {
                "scenario": row.get("scenario") or case.get("scenario"),
                "seed": case.get("seed"),
                "sim_minute": row.get("sim_minute"),
                "status": row.get("status"),
                "memory_status": memory.get("status", "none"),
                "memory_role": role,
                "memory_direct_count": len(memory.get("examples", []) if isinstance(memory.get("examples"), list) else []),
                "memory_cautionary_count": len(memory.get("cautionary_examples", []) if isinstance(memory.get("cautionary_examples"), list) else []),
                "selected_candidate_id": selected_id,
                "memory_aligned_selection": aligned,
                "action": action_key,
                "action_family": _action_family(action_key),
                "selection_status": _get(row, "candidate_selection.status", ""),
                "local_effect": local_effect,
                "predicted": prediction,
                "observed": observed,
                "prompt_tokens": _num(_get(row, "usage_metadata.promptTokenCount", _get(row, "usage_metadata.prompt_token_count", 0))),
                "candidate_tokens": _num(_get(row, "usage_metadata.candidatesTokenCount", _get(row, "usage_metadata.candidates_token_count", 0))),
            }
            calls.append(call)
            bucket = calibration[action_key]
            bucket["count"] += 1
            bucket["memory_roles"][role] += 1
            for metric in CALIBRATION_METRICS:
                if metric in prediction:
                    bucket["predicted"][metric].append(prediction[metric])
                if metric in observed:
                    bucket["observed"][metric].append(observed[metric])
    calibration_rows: list[dict[str, Any]] = []
    for action, bucket in sorted(calibration.items()):
        row: dict[str, Any] = {
            "action": action,
            "family": _action_family(action),
            "count": bucket["count"],
            "memory_roles": dict(bucket["memory_roles"]),
        }
        for metric in CALIBRATION_METRICS:
            predicted = _avg(bucket["predicted"][metric])
            observed = _avg(bucket["observed"][metric])
            row[f"predicted_{metric}"] = predicted
            row[f"observed_{metric}"] = observed
            row[f"error_{metric}"] = round(observed - predicted, 3)
        calibration_rows.append(row)
    status_counts = Counter(str(call["memory_status"]) for call in calls)
    role_counts = Counter(str(call["memory_role"]) for call in calls)
    local_counts = Counter(str(call["local_effect"]) for call in calls)
    action_counts = Counter(str(call["action"]) for call in calls)
    summary = {
        "call_count": len(calls),
        "memory_statuses": dict(status_counts),
        "memory_roles": dict(role_counts),
        "local_effects": dict(local_counts),
        "action_counts": dict(action_counts),
        "prompt_tokens": int(sum(call["prompt_tokens"] for call in calls)),
        "candidate_tokens": int(sum(call["candidate_tokens"] for call in calls)),
    }
    return calls, summary, calibration_rows


def analyze(memory_report_path: Path, control_report_path: Path | None, output_root: Path) -> dict[str, Any]:
    memory_report = _load_json(memory_report_path)
    control_report = _load_json(control_report_path) if control_report_path else {}
    output_dir = output_root / f"memory-influence-analysis-{_now_id()}"
    output_dir.mkdir(parents=True, exist_ok=True)

    control_cases = {
        (str(case.get("scenario")), str(case.get("seed"))): case
        for case in control_report.get("cases", [])
        if isinstance(case, dict)
    }
    if not control_cases:
        control_cases = {
            (str(case.get("scenario")), ""): case
            for case in control_report.get("cases", [])
            if isinstance(case, dict)
        }

    case_rows: list[dict[str, Any]] = []
    for case in memory_report.get("cases", []):
        if not isinstance(case, dict):
            continue
        control = control_cases.get((str(case.get("scenario")), str(case.get("seed")))) or control_cases.get((str(case.get("scenario")), ""))
        influence = _case_influence(case, control)
        case_rows.append(
            {
                "scenario": case.get("scenario"),
                "seed": case.get("seed"),
                "label": influence["label"],
                "improved": influence["improved"],
                "worsened": influence["worsened"],
                "memory_satisfaction": case.get("satisfaction_delta"),
                "control_satisfaction": control.get("satisfaction_delta") if control else None,
                "memory_wait": case.get("wait_delta"),
                "control_wait": control.get("wait_delta") if control else None,
                "memory_food": case.get("food_delta"),
                "control_food": control.get("food_delta") if control else None,
                "memory_eta": case.get("eta_delta"),
                "control_eta": control.get("eta_delta") if control else None,
                "memory_guidance_calls": case.get("memory_guidance_calls"),
                "direct_memory_calls": case.get("memory_calls"),
                "cautionary_memory_calls": case.get("cautionary_memory_calls"),
                "tradeoffs": case.get("unresolved_tradeoff_count"),
            }
        )

    calls, call_summary, calibration_rows = _analyze_calls(memory_report)
    score_calibration = _build_score_calibration(calibration_rows)
    calibration_path = output_dir / "score-calibration.json"
    _write_json(calibration_path, score_calibration)

    report = {
        "status": "complete",
        "created_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "memory_report": str(memory_report_path),
        "control_report": str(control_report_path) if control_report_path else None,
        "memory_summary": memory_report.get("summary", {}),
        "control_summary": control_report.get("summary", {}) if control_report else {},
        "case_influence": case_rows,
        "call_summary": call_summary,
        "action_calibration": calibration_rows,
        "score_calibration": score_calibration,
        "sample_calls": calls[:250],
        "interpretation": [
            "Case-level influence compares the full memory run against the no-memory control on the same scenario and seed.",
            "Call-level local effects compare actual per-call execution metrics against the per-call no-action counterfactual, not against the no-memory full run.",
            "Calibration error is observed per-call effect minus predicted counterfactual relative-to-no-action effect.",
        ],
    }
    json_path = output_dir / "memory-influence-report.json"
    html_path = output_dir / "memory-influence-report.html"
    report["artifacts"] = {"json": str(json_path), "html": str(html_path), "score_calibration": str(calibration_path)}
    _write_json(json_path, report)
    _render_html(report, html_path)
    return report


def _render_html(report: dict[str, Any], path: Path) -> None:
    memory_summary = report.get("memory_summary", {})
    control_summary = report.get("control_summary", {})
    call_summary = report.get("call_summary", {})
    case_rows = [
        [
            row.get("scenario"),
            row.get("label"),
            ", ".join(row.get("improved", [])),
            ", ".join(row.get("worsened", [])),
            row.get("memory_satisfaction"),
            row.get("control_satisfaction"),
            row.get("memory_wait"),
            row.get("control_wait"),
            row.get("memory_food"),
            row.get("control_food"),
            row.get("memory_eta"),
            row.get("control_eta"),
            row.get("memory_guidance_calls"),
            row.get("tradeoffs"),
        ]
        for row in report.get("case_influence", [])
    ]
    calibration_rows = [
        [
            row.get("action"),
            row.get("count"),
            json.dumps(row.get("memory_roles", {}), sort_keys=True),
            row.get("predicted_avg_satisfaction_delta"),
            row.get("observed_avg_satisfaction_delta"),
            row.get("predicted_slowest_ride_wait_delta"),
            row.get("observed_slowest_ride_wait_delta"),
            row.get("predicted_food_backlog_delta"),
            row.get("observed_food_backlog_delta"),
            row.get("predicted_food_eta_minutes_delta"),
            row.get("observed_food_eta_minutes_delta"),
        ]
        for row in report.get("action_calibration", [])
    ]
    call_rows = [
        [
            row.get("scenario"),
            row.get("sim_minute"),
            row.get("memory_role"),
            row.get("memory_status"),
            row.get("selected_candidate_id"),
            row.get("memory_aligned_selection"),
            row.get("action"),
            row.get("local_effect"),
            row.get("prompt_tokens"),
        ]
        for row in report.get("sample_calls", [])[:80]
    ]
    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>ParkPulse Memory Influence Analysis</title>
<style>
body {{ margin: 0; font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #182230; }}
main {{ max-width: 1240px; margin: 0 auto; padding: 30px 22px 56px; }}
h1 {{ margin: 0 0 8px; font-size: 30px; }}
h2 {{ margin: 0 0 10px; font-size: 18px; }}
p {{ margin: 8px 0 0; color: #667085; }}
.stats {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 22px 0; }}
.stat, .card {{ border: 1px solid #d0d5dd; border-radius: 8px; padding: 16px; margin: 18px 0; background: #fff; }}
.stat {{ background: #f8fafc; margin: 0; }}
.stat b {{ display: block; font-size: 22px; margin-top: 4px; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ padding: 8px 9px; border-bottom: 1px solid #edf1f6; text-align: right; vertical-align: top; }}
th:first-child, td:first-child {{ text-align: left; }}
thead th {{ color: #667085; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
@media (max-width: 850px) {{ .stats {{ grid-template-columns: 1fr; }} table {{ font-size: 12px; }} }}
</style>
</head>
<body>
<main>
<h1>ParkPulse Memory Influence Analysis</h1>
<p>Memory run: {html.escape(str(report.get("memory_report")))}</p>
<p>Control run: {html.escape(str(report.get("control_report")))}</p>
<section class="stats">
  <div class="stat">Memory guidance<b>{memory_summary.get("total_memory_guidance_calls", 0)}</b></div>
  <div class="stat">Direct memory<b>{memory_summary.get("total_memory_calls", 0)}</b></div>
  <div class="stat">Gemini errors<b>{memory_summary.get("total_gemini_errors", 0)}</b></div>
  <div class="stat">Tradeoffs<b>{memory_summary.get("total_unresolved_tradeoffs", 0)} / control {control_summary.get("total_unresolved_tradeoffs", "n/a")}</b></div>
</section>
<section class="card"><h2>Call Memory Mix</h2><p>{html.escape(json.dumps(call_summary.get("memory_roles", {}), sort_keys=True))}</p><p>{html.escape(json.dumps(call_summary.get("memory_statuses", {}), sort_keys=True))}</p></section>
<section class="card"><h2>Case Influence</h2>{_html_table(case_rows, ["scenario", "label", "improved", "worsened", "mem sat", "ctrl sat", "mem wait", "ctrl wait", "mem food", "ctrl food", "mem eta", "ctrl eta", "guidance", "tradeoffs"])}</section>
<section class="card"><h2>Action Calibration</h2>{_html_table(calibration_rows, ["action", "count", "memory roles", "pred sat", "obs sat", "pred wait", "obs wait", "pred food", "obs food", "pred eta", "obs eta"])}</section>
<section class="card"><h2>Sample Calls</h2>{_html_table(call_rows, ["scenario", "minute", "memory role", "memory status", "selected", "aligned", "action", "local effect", "prompt tokens"])}</section>
</main>
</body>
</html>
"""
    path.write_text(doc, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze whether MongoDB memory helped or hurt a frozen timelapse benchmark run.")
    parser.add_argument("--memory-report", required=True, help="Path to memory-enabled frozen-benchmark-report.json.")
    parser.add_argument("--control-report", help="Optional no-memory frozen-benchmark-report.json for same-seed comparison.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    args = parser.parse_args()
    report = analyze(
        Path(args.memory_report).expanduser().resolve(),
        Path(args.control_report).expanduser().resolve() if args.control_report else None,
        Path(args.output_dir).expanduser().resolve(),
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "html": report["artifacts"]["html"],
                "json": report["artifacts"]["json"],
                "case_labels": Counter(row["label"] for row in report["case_influence"]),
                "memory_roles": report["call_summary"].get("memory_roles", {}),
                "memory_statuses": report["call_summary"].get("memory_statuses", {}),
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
