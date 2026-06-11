#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

DEFAULT_OUTPUT_ROOT = REPO_ROOT / "output" / "qa"
FROZEN_BENCHMARK_VERSION = "timelapse-heldout-benchmark-v1"
DEFAULT_SCENARIOS = ["ride_down", "food_spike", "staff_shortage", "storm_response"]
DEFAULT_SEEDS = ["heldout-a", "heldout-b"]


def _now_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    parsed = json.loads(path.read_text(encoding="utf-8"))
    return parsed if isinstance(parsed, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


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


def _arg_namespace(**overrides: Any) -> argparse.Namespace:
    defaults = {
        "sim_minutes": 1440,
        "llm_interval_minutes": int(os.getenv("PARKPULSE_TIMELAPSE_LLM_INTERVAL_MINUTES", "15")),
        "full_snapshot_interval_minutes": int(os.getenv("PARKPULSE_TIMELAPSE_FULL_SNAPSHOT_INTERVAL_MINUTES", "15")),
        "input_tokens_per_llm": 4000,
        "output_tokens_per_llm": 900,
        "temperature": 0.2,
        "gemini_timeout_seconds": 8.0,
        "gemini_retries": 1,
        "counterfactual_horizon_minutes": 30,
        "score_gap_override": 10,
        "score_calibration_report": None,
        "call_gemini": False,
        "gemini_candidate_ranking": False,
        "execute_gemini_actions": False,
        "enforce_policy_regulation_alignment": False,
        "use_mongodb_memory": False,
        "memory_limit": 3,
        "cloud_run_vcpu": 1.0,
        "cloud_run_gib": 1.0,
        "api_tick_requests": False,
        "weekly_budget_usd": float(os.getenv("PARKPULSE_WEEKLY_BUDGET_USD", "25")),
        "model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        "scenario": "ride_down",
        "seed": "frozen-benchmark",
        "start_hour": 9,
        "start_minute": 0,
        "include_closed_hours_gemini": False,
        "output_dir": str(DEFAULT_OUTPUT_ROOT),
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _metric_delta(scorecard: dict[str, Any], key: str, field: str = "avg") -> float:
    return float(
        scorecard.get("operational_metrics", {})
        .get(key, {})
        .get("delta", {})
        .get(field, 0)
        or 0
    )


def _stability_delta(scorecard: dict[str, Any], key: str) -> float:
    return float(
        scorecard.get("long_term_operating_stability", {})
        .get("delta", {})
        .get(key, 0)
        or 0
    )


def _stability_current(scorecard: dict[str, Any], key: str) -> float:
    return float(
        scorecard.get("long_term_operating_stability", {})
        .get("current", {})
        .get(key, 0)
        or 0
    )


def _action_load(scorecard: dict[str, Any], key: str) -> float:
    return float(
        scorecard.get("long_term_operating_stability", {})
        .get("candidate_action_load", {})
        .get(key, 0)
        or 0
    )


def _summarize_cases(case_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not case_rows:
        return {}
    memory_statuses: Counter[str] = Counter()
    memory_methods: Counter[str] = Counter()
    for row in case_rows:
        for key, value in (row.get("memory_statuses") or {}).items():
            memory_statuses[str(key)] += int(value or 0)
        for key, value in (row.get("memory_methods") or {}).items():
            memory_methods[str(key)] += int(value or 0)
    total_cases = len(case_rows)
    clean_cases = sum(1 for row in case_rows if int(row.get("critical_bypass") or 0) == 0)
    regression_cases = sum(1 for row in case_rows if row.get("regression_count", 0) > 0)
    reasoning_issue_cases = sum(1 for row in case_rows if row.get("reasoning_issue_count", 0) > 0)
    unresolved_tradeoff_cases = sum(1 for row in case_rows if row.get("unresolved_tradeoff_count", 0) > 0)
    release_clean_cases = sum(
        1
        for row in case_rows
        if int(row.get("critical_bypass") or 0) == 0
        and int(row.get("gemini_errors") or 0) == 0
        and int(row.get("reasoning_issue_count") or 0) == 0
        and int(row.get("unresolved_tradeoff_count") or 0) == 0
    )
    decision = "GO" if release_clean_cases == total_cases else "GO_WITH_CONDITIONS" if clean_cases == total_cases else "NO_GO"
    return {
        "case_count": total_cases,
        "policy_clean_cases": clean_cases,
        "release_clean_cases": release_clean_cases,
        "cases_with_metric_regression": regression_cases,
        "cases_with_reasoning_issues": reasoning_issue_cases,
        "cases_with_unresolved_tradeoffs": unresolved_tradeoff_cases,
        "decision": decision,
        "average_policy_score": round(sum(float(row.get("policy_score") or 0) for row in case_rows) / total_cases, 3),
        "average_satisfaction_delta": round(sum(float(row.get("satisfaction_delta") or 0) for row in case_rows) / total_cases, 3),
        "average_wait_delta": round(sum(float(row.get("wait_delta") or 0) for row in case_rows) / total_cases, 3),
        "average_food_delta": round(sum(float(row.get("food_delta") or 0) for row in case_rows) / total_cases, 3),
        "average_eta_delta": round(sum(float(row.get("eta_delta") or 0) for row in case_rows) / total_cases, 3),
        "average_stability_score_delta": round(sum(float(row.get("stability_score_delta") or 0) for row in case_rows) / total_cases, 3),
        "average_operating_stress_delta": round(sum(float(row.get("operating_stress_delta") or 0) for row in case_rows) / total_cases, 3),
        "average_recovery_gain_delta": round(sum(float(row.get("recovery_gain_delta") or 0) for row in case_rows) / total_cases, 3),
        "average_late_day_stress_delta": round(sum(float(row.get("late_day_stress_delta") or 0) for row in case_rows) / total_cases, 3),
        "total_severe_pressure_tick_delta": sum(int(row.get("severe_pressure_tick_delta") or 0) for row in case_rows),
        "total_guest_disruption_actions": sum(int(row.get("guest_disruption_actions") or 0) for row in case_rows),
        "average_guest_disruption_share": round(sum(float(row.get("guest_disruption_share") or 0) for row in case_rows) / total_cases, 3),
        "total_gemini_calls": sum(int(row.get("gemini_calls") or 0) for row in case_rows),
        "total_gemini_errors": sum(int(row.get("gemini_errors") or 0) for row in case_rows),
        "total_memory_calls": sum(int(row.get("memory_calls") or 0) for row in case_rows),
        "total_memory_guidance_calls": sum(int(row.get("memory_guidance_calls") or 0) for row in case_rows),
        "total_cautionary_memory_calls": sum(int(row.get("cautionary_memory_calls") or 0) for row in case_rows),
        "memory_connected_cases": sum(1 for row in case_rows if row.get("memory_connected") is True),
        "memory_statuses": dict(memory_statuses),
        "memory_methods": dict(memory_methods),
        "total_reasoning_issues": sum(int(row.get("reasoning_issue_count") or 0) for row in case_rows),
        "total_unresolved_tradeoffs": sum(int(row.get("unresolved_tradeoff_count") or 0) for row in case_rows),
        "total_projected_week_cost_usd": round(sum(float(row.get("projected_week_cost_usd") or 0) for row in case_rows), 6),
        "policy_regulation_allowed_calls": sum(int(row.get("policy_regulation_allowed_calls") or 0) for row in case_rows),
        "policy_regulation_review_required_calls": sum(int(row.get("policy_regulation_review_required_calls") or 0) for row in case_rows),
        "policy_regulation_blocked_calls": sum(int(row.get("policy_regulation_blocked_calls") or 0) for row in case_rows),
        "policy_regulation_held_execution_count": sum(int(row.get("policy_regulation_held_execution_count") or 0) for row in case_rows),
        "gemini_executed_action_count": sum(int(row.get("gemini_executed_action_count") or 0) for row in case_rows),
    }


def render_html(report: dict[str, Any], path: Path) -> None:
    summary = report.get("summary", {})
    cases = report.get("cases", [])
    rows = [
        [
            row.get("scenario"),
            row.get("seed"),
            row.get("policy_score"),
            row.get("critical_bypass"),
            row.get("gemini_errors"),
            row.get("memory_calls"),
            row.get("memory_guidance_calls"),
            row.get("memory_connected"),
            row.get("satisfaction_delta"),
            row.get("wait_delta"),
            row.get("food_delta"),
            row.get("eta_delta"),
            row.get("stability_score_delta"),
            row.get("operating_stress_delta"),
            row.get("recovery_gain_delta"),
            row.get("late_day_stress_delta"),
            row.get("severe_pressure_tick_delta"),
            row.get("guest_disruption_actions"),
            row.get("regression_count"),
            row.get("reasoning_issue_count"),
            row.get("unresolved_tradeoff_count"),
        ]
        for row in cases
    ]
    risks = "".join(f"<li>{html.escape(item)}</li>" for item in report.get("audit_notes", []))
    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>ParkPulse Frozen Timelapse Benchmark</title>
<style>
body {{ margin: 0; font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #182230; }}
main {{ max-width: 1160px; margin: 0 auto; padding: 30px 22px 56px; }}
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
@media (max-width: 850px) {{ .stats {{ grid-template-columns: 1fr; }} table {{ font-size: 12px; }} }}
</style>
</head>
<body>
<main>
<h1>ParkPulse Frozen Timelapse Benchmark</h1>
<p>{html.escape(report.get("benchmark_version", ""))} / evaluator {html.escape(str(report.get("evaluation_contract", {}).get("fingerprint", "")))}</p>
<section class="stats">
  <div class="stat">Cases<b>{summary.get("case_count", 0)}</b></div>
  <div class="stat">Policy clean<b>{summary.get("policy_clean_cases", 0)}</b></div>
  <div class="stat">Release clean<b>{summary.get("release_clean_cases", 0)}</b></div>
  <div class="stat">Gemini errors<b>{summary.get("total_gemini_errors", 0)}</b></div>
</section>
<section class="stats">
  <div class="stat">Memory enabled<b>{report.get("manifest", {}).get("use_mongodb_memory", False)}</b></div>
  <div class="stat">Memory calls<b>{summary.get("total_memory_calls", 0)}</b></div>
	  <div class="stat">Guidance calls<b>{summary.get("total_memory_guidance_calls", 0)}</b></div>
	  <div class="stat">Cautionary calls<b>{summary.get("total_cautionary_memory_calls", 0)}</b></div>
	  <div class="stat">Memory limit<b>{report.get("manifest", {}).get("memory_limit", "none")}</b></div>
	</section>
	<section class="stats">
	  <div class="stat">Stability score d<b>{summary.get("average_stability_score_delta", 0)}</b></div>
	  <div class="stat">Stress d<b>{summary.get("average_operating_stress_delta", 0)}</b></div>
	  <div class="stat">Recovery d<b>{summary.get("average_recovery_gain_delta", 0)}</b></div>
	  <div class="stat">Guest disruptions<b>{summary.get("total_guest_disruption_actions", 0)}</b></div>
	</section>
	<section class="card"><h2>Memory Status</h2><p>{html.escape(json.dumps(summary.get("memory_statuses", {}), sort_keys=True))}</p></section>
	<section class="card"><h2>Decision</h2><p>{html.escape(str(summary.get("decision", "")))}. Policy-clean means no critical bypass. Release-clean additionally requires zero Gemini failures, zero unresolved metric regressions, zero reasoning audit issues, and zero unresolved tradeoffs.</p></section>
	<section class="card"><h2>Case Results</h2>{_html_table(rows, ["scenario", "seed", "policy", "critical bypass", "gemini errors", "direct memory", "guidance memory", "memory connected", "sat d", "wait d", "food d", "eta d", "stability d", "stress d", "recovery d", "late stress d", "severe ticks d", "guest disruptions", "regressions", "reasoning issues", "unresolved tradeoffs"])}</section>
<section class="card"><h2>Audit Notes</h2><ul>{risks}</ul></section>
</main>
</body>
</html>
"""
    path.write_text(doc, encoding="utf-8")


async def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    from evaluate_timelapse_policy_scorecard import _evaluation_contract, evaluate_run, render_html as render_scorecard_html
    from run_one_day_timelapse_cost_probe import run_probe

    output_root = Path(args.output_dir).expanduser().resolve() / f"frozen-timelapse-benchmark-{_now_id()}"
    output_root.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []
    scenarios = args.scenarios or DEFAULT_SCENARIOS
    seeds = args.seeds or DEFAULT_SEEDS

    for scenario in scenarios:
        for seed in seeds:
            case_id = f"{scenario}-{seed}"
            case_dir = output_root / case_id
            replay_seed = f"{FROZEN_BENCHMARK_VERSION}-{scenario}-{seed}"
            baseline_report = await run_probe(
                _arg_namespace(
                    sim_minutes=args.sim_minutes,
                    llm_interval_minutes=args.llm_interval_minutes,
                    full_snapshot_interval_minutes=args.full_snapshot_interval_minutes,
                    scenario=scenario,
                    seed=replay_seed,
                    output_dir=str(case_dir / "baseline"),
                    model=args.model,
                    weekly_budget_usd=args.weekly_budget_usd,
                )
            )
            candidate_report = await run_probe(
                _arg_namespace(
                    sim_minutes=args.sim_minutes,
                    llm_interval_minutes=args.llm_interval_minutes,
                    full_snapshot_interval_minutes=args.full_snapshot_interval_minutes,
                    scenario=scenario,
                    seed=replay_seed,
                    output_dir=str(case_dir / "candidate"),
                    model=args.model,
                    weekly_budget_usd=args.weekly_budget_usd,
                    call_gemini=args.call_gemini,
                    gemini_candidate_ranking=True,
                    execute_gemini_actions=args.call_gemini,
                    enforce_policy_regulation_alignment=args.enforce_policy_regulation_alignment,
                    gemini_timeout_seconds=args.gemini_timeout_seconds,
                    gemini_retries=args.gemini_retries,
                    counterfactual_horizon_minutes=args.counterfactual_horizon_minutes,
                    score_gap_override=args.score_gap_override,
                    score_calibration_report=args.score_calibration_report,
                    use_mongodb_memory=args.use_mongodb_memory,
                    memory_limit=args.memory_limit,
                )
            )
            baseline_run_dir = Path(baseline_report["run"]["artifacts"]["run_dir"])
            candidate_run_dir = Path(candidate_report["run"]["artifacts"]["run_dir"])
            scorecard = evaluate_run(candidate_run_dir, baseline_run_dir)
            scorecard_dir = case_dir / "scorecard"
            scorecard_dir.mkdir(parents=True, exist_ok=True)
            scorecard_json = scorecard_dir / "policy-scorecard.json"
            scorecard_html = scorecard_dir / "policy-scorecard.html"
            _write_json(scorecard_json, scorecard)
            render_scorecard_html(scorecard, scorecard_html)
            regressions = scorecard.get("bias_audit", {}).get("metric_regressions", [])
            tradeoff_ledger = scorecard.get("bias_audit", {}).get("tradeoff_ledger", {})
            reasoning_audit = scorecard.get("policy", {}).get("llm_reasoning_audit", {})
            cases.append(
                {
                    "scenario": scenario,
                    "seed": seed,
                    "baseline_run": str(baseline_run_dir),
                    "candidate_run": str(candidate_run_dir),
                    "scorecard": str(scorecard_html),
                    "policy_score": scorecard.get("policy", {}).get("score", 0),
                    "critical_bypass": scorecard.get("policy", {}).get("final_critical_food_ride_bypass_count", 0),
	                    "gemini_calls": candidate_report.get("run", {}).get("gemini_call_count", 0),
                    "gemini_errors": candidate_report.get("run", {}).get("gemini_error_count", 0),
                    "gemini_executed_action_count": candidate_report.get("run", {}).get("gemini_executed_action_count", 0),
                    "policy_regulation_alignment": candidate_report.get("run", {}).get("policy_regulation_alignment", {}),
                    "policy_regulation_allowed_calls": candidate_report.get("run", {}).get("policy_regulation_alignment", {}).get("allowed_count", 0),
                    "policy_regulation_review_required_calls": candidate_report.get("run", {}).get("policy_regulation_alignment", {}).get("review_required_count", 0),
                    "policy_regulation_blocked_calls": candidate_report.get("run", {}).get("policy_regulation_alignment", {}).get("blocked_count", 0),
                    "policy_regulation_held_execution_count": candidate_report.get("run", {}).get("policy_regulation_alignment", {}).get("held_execution_count", 0),
                    "memory_calls": candidate_report.get("run", {}).get("memory", {}).get("calls_with_memory", 0),
                    "memory_guidance_calls": candidate_report.get("run", {}).get("memory", {}).get("calls_with_memory_guidance", 0),
                    "cautionary_memory_calls": candidate_report.get("run", {}).get("memory", {}).get("calls_with_cautionary_memory", 0),
                    "memory_connected": candidate_report.get("run", {}).get("memory", {}).get("connected", False),
                    "memory_statuses": candidate_report.get("run", {}).get("memory", {}).get("statuses", {}),
                    "memory_methods": candidate_report.get("run", {}).get("memory", {}).get("methods", {}),
                    "projected_week_cost_usd": candidate_report.get("projected_week_from_probe", {}).get("estimated_total_usd_with_llm", 0),
                    "satisfaction_delta": _metric_delta(scorecard, "satisfaction"),
                    "wait_delta": _metric_delta(scorecard, "slowest_ride_wait"),
                    "food_delta": _metric_delta(scorecard, "food_backlog"),
                    "eta_delta": _metric_delta(scorecard, "food_eta_minutes"),
                    "stability_score_current": _stability_current(scorecard, "stability_score"),
                    "stability_score_delta": _stability_delta(scorecard, "stability_score"),
                    "operating_stress_delta": _stability_delta(scorecard, "avg_operating_stress"),
                    "recovery_gain_delta": _stability_delta(scorecard, "recovery_gain"),
                    "late_day_stress_delta": _stability_delta(scorecard, "late_day_operating_stress"),
                    "severe_pressure_tick_delta": int(_stability_delta(scorecard, "severe_pressure_tick_count")),
                    "max_severe_pressure_streak_delta": int(_stability_delta(scorecard, "max_severe_pressure_streak")),
                    "guest_disruption_actions": int(_action_load(scorecard, "guest_disruption_action_count")),
                    "guest_disruption_share": _action_load(scorecard, "guest_disruption_action_share"),
                    "regression_count": len(regressions) if isinstance(regressions, list) else 0,
                    "reasoning_issue_count": int(reasoning_audit.get("issue_count") or 0)
                    if isinstance(reasoning_audit, dict)
                    else 0,
                    "unresolved_tradeoff_count": int(tradeoff_ledger.get("unresolved_count") or 0)
                    if isinstance(tradeoff_ledger, dict)
                    else 0,
                }
            )

    report = {
        "status": "complete",
        "benchmark_version": FROZEN_BENCHMARK_VERSION,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "output_dir": str(output_root),
        "call_gemini": bool(args.call_gemini),
        "evaluation_contract": _evaluation_contract(),
        "manifest": {
            "scenarios": scenarios,
            "seeds": seeds,
            "sim_minutes": args.sim_minutes,
            "llm_interval_minutes": args.llm_interval_minutes,
            "full_snapshot_interval_minutes": args.full_snapshot_interval_minutes,
            "counterfactual_horizon_minutes": args.counterfactual_horizon_minutes,
            "score_gap_override": args.score_gap_override,
            "score_calibration_report": args.score_calibration_report,
            "use_mongodb_memory": bool(args.use_mongodb_memory),
            "enforce_policy_regulation_alignment": bool(args.enforce_policy_regulation_alignment),
            "memory_limit": args.memory_limit,
            "model": args.model,
            "weekly_budget_usd": args.weekly_budget_usd,
        },
        "summary": _summarize_cases(cases),
        "cases": cases,
        "audit_notes": [
            "The evaluator contract is frozen and fingerprinted in every scorecard.",
            "Baseline and candidate metrics use the same open-to-guests filter.",
            "Baseline and candidate runs use the same replay seed for each scenario/case.",
            "The benchmark still depends on simulated action-effect constants; real-world claims require calibration with park operations data.",
            "A case is not clean if Gemini transport fails or any average/worst metric regression appears without a signed tradeoff reason.",
            "A case is not release-clean if LLM reasoning labels deterministic food severity incorrectly.",
            "A case is not release-clean if the tradeoff ledger has unresolved regressions.",
        ],
    }
    report_json = output_root / "frozen-benchmark-report.json"
    report_html = output_root / "frozen-benchmark-report.html"
    _write_json(report_json, report)
    render_html(report, report_html)
    report["artifacts"] = {"json": str(report_json), "html": str(report_html)}
    _write_json(report_json, report)
    return report


def _split_csv(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a frozen held-out timelapse benchmark with baseline vs candidate-ranking runs.")
    parser.add_argument("--call-gemini", action="store_true", help="Call Gemini for candidate-ranking runs. Without this, candidate runs are no-action controls.")
    parser.add_argument("--scenarios", type=lambda value: _split_csv(value, DEFAULT_SCENARIOS), default=DEFAULT_SCENARIOS)
    parser.add_argument("--seeds", type=lambda value: _split_csv(value, DEFAULT_SEEDS), default=DEFAULT_SEEDS)
    parser.add_argument("--sim-minutes", type=int, default=1440)
    parser.add_argument("--llm-interval-minutes", type=int, default=int(os.getenv("PARKPULSE_TIMELAPSE_LLM_INTERVAL_MINUTES", "15")))
    parser.add_argument("--full-snapshot-interval-minutes", type=int, default=int(os.getenv("PARKPULSE_TIMELAPSE_FULL_SNAPSHOT_INTERVAL_MINUTES", "15")))
    parser.add_argument("--gemini-timeout-seconds", type=float, default=8.0)
    parser.add_argument("--gemini-retries", type=int, default=int(os.getenv("PARKPULSE_GEMINI_RETRIES", "1")))
    parser.add_argument("--counterfactual-horizon-minutes", type=int, default=int(os.getenv("PARKPULSE_COUNTERFACTUAL_HORIZON_MINUTES", "30")))
    parser.add_argument("--score-gap-override", type=int, default=int(os.getenv("PARKPULSE_SCORE_GAP_OVERRIDE", "10")))
    parser.add_argument("--score-calibration-report", help="Optional score-calibration.json generated by analyze_memory_influence.py.")
    parser.add_argument("--enforce-policy-regulation-alignment", action="store_true", help="Hold candidate simulated execution unless policy_regulation_judgment.status is allowed.")
    parser.add_argument("--use-mongodb-memory", action="store_true", help="Retrieve MongoDB timelapse memory for runtime candidate-ranking prompts.")
    parser.add_argument("--memory-limit", type=int, default=3)
    parser.add_argument("--weekly-budget-usd", type=float, default=float(os.getenv("PARKPULSE_WEEKLY_BUDGET_USD", "25")))
    parser.add_argument("--model", default=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    args = parser.parse_args()
    if args.sim_minutes < 1:
        raise SystemExit("--sim-minutes must be >= 1")
    if args.memory_limit < 1:
        raise SystemExit("--memory-limit must be >= 1")
    report = asyncio.run(run_benchmark(args))
    print(
        json.dumps(
            {
                "status": report["status"],
                "benchmark_version": report["benchmark_version"],
                "cases": report["summary"].get("case_count", 0),
                "decision": report["summary"].get("decision"),
                "policy_clean_cases": report["summary"].get("policy_clean_cases", 0),
                "release_clean_cases": report["summary"].get("release_clean_cases", 0),
                "regression_cases": report["summary"].get("cases_with_metric_regression", 0),
                "reasoning_issue_cases": report["summary"].get("cases_with_reasoning_issues", 0),
                "unresolved_tradeoff_cases": report["summary"].get("cases_with_unresolved_tradeoffs", 0),
                "gemini_errors": report["summary"].get("total_gemini_errors", 0),
                "memory_enabled": report["manifest"].get("use_mongodb_memory", False),
                "html": report["artifacts"]["html"],
                "json": report["artifacts"]["json"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
