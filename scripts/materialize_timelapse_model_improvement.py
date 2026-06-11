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
MATERIALIZER_VERSION = "timelapse-model-improvement-v1"

DELTA_KEYS = [
    "avg_satisfaction_delta",
    "slowest_ride_wait_delta",
    "food_backlog_delta",
    "food_eta_minutes_delta",
    "busiest_zone_density_delta",
    "path_congestion_delta",
    "open_callouts_delta",
    "grid_load_delta",
]


def _now_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


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


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _hash_id(prefix: str, payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(encoded).hexdigest()[:16]}"


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


def _action_key(row: dict[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return "none"
    return f"{row.get('target')}/{row.get('action')}"


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


def _candidate_relative(candidate: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        return {}
    counterfactual = candidate.get("counterfactual", {})
    if not isinstance(counterfactual, dict):
        return {}
    relative = counterfactual.get("relative_to_no_action", {})
    return relative if isinstance(relative, dict) else {}


def _candidate_deltas(candidate: dict[str, Any] | None) -> dict[str, float]:
    relative = _candidate_relative(candidate)
    return {key: _number(relative.get(key)) for key in DELTA_KEYS if key in relative}


def _passed_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [candidate for candidate in candidates if candidate.get("policy_status") == "passed"]


def _best_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    passed = _passed_candidates(candidates)
    return max(passed, key=lambda item: int(item.get("score") or 0), default=None)


def _metric_regression_set(scorecard: dict[str, Any]) -> set[str]:
    regressions = _get(scorecard, "bias_audit.metric_regressions", [])
    if not isinstance(regressions, list):
        return set()
    return {
        str(item.get("metric"))
        for item in regressions
        if isinstance(item, dict) and item.get("metric")
    }


def _outcome_aligned_score(candidate: dict[str, Any], *, scorecard: dict[str, Any], severity: str) -> int:
    score = int(candidate.get("score") or 0)
    regressions = _metric_regression_set(scorecard)
    deltas = _candidate_deltas(candidate)
    action = _action_key(candidate)
    food_regressed = bool({"food_backlog", "food_eta_minutes"} & regressions)
    wait_regressed = "slowest_ride_wait" in regressions
    satisfaction_regressed = "satisfaction" in regressions
    density_regressed = "busiest_zone_density" in regressions
    callout_regressed = "open_callouts" in regressions

    food_gain = max(0, -_number(deltas.get("food_backlog_delta"))) / 8 + max(0, -_number(deltas.get("food_eta_minutes_delta"))) * 2
    wait_gain = max(0, -_number(deltas.get("slowest_ride_wait_delta"))) / 2
    satisfaction_gain = max(0, _number(deltas.get("avg_satisfaction_delta"))) * 3
    density_gain = max(0, -_number(deltas.get("busiest_zone_density_delta"))) * 2
    path_gain = max(0, -_number(deltas.get("path_congestion_delta"))) / 2
    callout_gain = max(0, -_number(deltas.get("open_callouts_delta"))) * 3

    if food_regressed and severity in {"p2_warning", "p1_critical", "p0_gridlock"}:
        score += min(45, int(food_gain))
        if food_gain <= 0:
            score -= 24
    elif food_gain > 0:
        score += min(12, int(food_gain))

    if wait_regressed:
        score += min(30, int(wait_gain))
    elif action == "ride/reroute" and food_regressed and severity != "normal":
        score -= 10

    if satisfaction_regressed:
        score += min(16, int(satisfaction_gain))
    if density_regressed:
        score += min(16, int(density_gain + path_gain))
    if callout_regressed:
        score += min(16, int(callout_gain))

    score -= max(0, int(_number(deltas.get("food_backlog_delta")))) // 6
    score -= max(0, int(_number(deltas.get("food_eta_minutes_delta")))) * 3
    score -= max(0, int(_number(deltas.get("slowest_ride_wait_delta")))) // 2
    score -= max(0, int(_number(deltas.get("open_callouts_delta")))) * 4
    return max(0, min(140, score))


def _best_outcome_aligned_candidate(candidates: list[dict[str, Any]], *, scorecard: dict[str, Any], severity: str) -> dict[str, Any] | None:
    passed = _passed_candidates(candidates)
    if not passed:
        return None
    return max(passed, key=lambda item: _outcome_aligned_score(item, scorecard=scorecard, severity=severity))


def _candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": candidate.get("id"),
        "action": _action_key(candidate),
        "policy_status": candidate.get("policy_status"),
        "policy_reasons": candidate.get("policy_reasons", []),
        "score": candidate.get("score"),
        "deltas": _candidate_deltas(candidate),
        "secondary_risks": _get(candidate, "counterfactual.secondary_risks", []),
        "risk_context": candidate.get("risk_context", {}),
    }


def _risk_classification(row: dict[str, Any]) -> dict[str, Any]:
    parsed = row.get("parsed_response", {}) if isinstance(row.get("parsed_response"), dict) else {}
    risk = parsed.get("risk_classification", {}) if isinstance(parsed.get("risk_classification"), dict) else {}
    return risk


def _selected_candidate_id(row: dict[str, Any]) -> str | None:
    selected = row.get("selected_policy_candidate", {})
    if isinstance(selected, dict) and selected.get("id"):
        return str(selected.get("id"))
    return _get(row, "candidate_selection.fallback_candidate_id") or _get(row, "candidate_selection.override_candidate_id")


def _model_selected_candidate_id(row: dict[str, Any]) -> str | None:
    return _get(row, "candidate_selection.selected_candidate_id")


def _material_food_regression(candidate: dict[str, Any] | None) -> bool:
    deltas = _candidate_deltas(candidate)
    return _number(deltas.get("food_backlog_delta")) > 25 or _number(deltas.get("food_eta_minutes_delta")) > 2


def _score_decision(
    row: dict[str, Any],
    best: dict[str, Any] | None,
    selected: dict[str, Any] | None,
    *,
    scorecard: dict[str, Any],
) -> tuple[int, list[str]]:
    issues: list[str] = []
    reward = 100
    if row.get("status") != "success":
        reward -= 30
        issues.append(str(row.get("status") or "non_success_model_status"))
    if not _risk_classification(row):
        reward -= 20
        issues.append("missing_risk_classification")
    invalid_count = len(_get(row, "candidate_selection.invalid_ranked_candidate_ids", []) or [])
    blocked_count = len(_get(row, "candidate_selection.ranked_blocked_candidate_ids", []) or [])
    if invalid_count:
        reward -= min(20, invalid_count * 5)
        issues.append("ranked_invalid_candidate_id")
    if blocked_count:
        reward -= min(30, blocked_count * 8)
        issues.append("ranked_blocked_candidate")
    if best and selected:
        severity = _food_severity(row.get("before_digest", {}))
        regret = max(
            0,
            _outcome_aligned_score(best, scorecard=scorecard, severity=severity)
            - _outcome_aligned_score(selected, scorecard=scorecard, severity=severity),
        )
        if regret > 0:
            reward -= min(25, regret)
            issues.append("outcome_aligned_candidate_regret")
    if _material_food_regression(selected):
        reward -= 25
        issues.append("selected_material_food_regression")
    if _food_severity(row.get("before_digest", {})) in {"p0_gridlock", "p1_critical"}:
        primary = str(_risk_classification(row).get("primary_risk") or "").lower()
        if primary and primary != "food":
            reward -= 20
            issues.append("missed_critical_food_primary_risk")
    return max(0, min(100, reward)), issues


def _expected_output(row: dict[str, Any], candidates: list[dict[str, Any]], scorecard: dict[str, Any]) -> dict[str, Any]:
    deterministic_best = _best_candidate(candidates)
    severity = _food_severity(row.get("before_digest", {}))
    best = _best_outcome_aligned_candidate(candidates, scorecard=scorecard, severity=severity)
    selected = row.get("selected_policy_candidate") if isinstance(row.get("selected_policy_candidate"), dict) else None
    reward, issues = _score_decision(row, best, selected, scorecard=scorecard)
    blocked_ids = [str(candidate.get("id")) for candidate in candidates if candidate.get("policy_status") == "blocked"]
    expected = {
        "target_task": "rank_safe_candidates_and_explain_tradeoff",
        "ideal_candidate_id": best.get("id") if best else None,
        "ideal_action": _action_key(best) if best else None,
        "deterministic_score_best_candidate_id": deterministic_best.get("id") if deterministic_best else None,
        "deterministic_score_best_action": _action_key(deterministic_best) if deterministic_best else None,
        "model_selected_candidate_id": _model_selected_candidate_id(row),
        "final_selected_candidate_id": _selected_candidate_id(row),
        "final_action": _action_key(row.get("allowed_action") if isinstance(row.get("allowed_action"), dict) else None),
        "deterministic_food_severity": severity,
        "case_metric_regressions": sorted(_metric_regression_set(scorecard)),
        "blocked_candidate_ids": blocked_ids,
        "selected_candidate_score": selected.get("score") if selected else None,
        "ideal_candidate_score": best.get("score") if best else None,
        "selected_outcome_aligned_score": _outcome_aligned_score(selected, scorecard=scorecard, severity=severity) if selected else None,
        "ideal_outcome_aligned_score": _outcome_aligned_score(best, scorecard=scorecard, severity=severity) if best else None,
        "candidate_score_regret": max(0, int(best.get("score") or 0) - int(selected.get("score") or 0)) if best and selected else None,
        "outcome_aligned_regret": (
            max(
                0,
                _outcome_aligned_score(best, scorecard=scorecard, severity=severity)
                - _outcome_aligned_score(selected, scorecard=scorecard, severity=severity),
            )
            if best and selected
            else None
        ),
        "selected_candidate_deltas": _candidate_deltas(selected),
        "ideal_candidate_deltas": _candidate_deltas(best),
        "reward_score": reward,
        "quality_issues": issues,
        "label_source": "outcome_aligned_policy_scorecard_and_candidate_counterfactuals",
    }
    return expected


def _split_for_example(example_index: int, reward_score: int) -> str:
    if reward_score < 80:
        return "eval"
    return "eval" if example_index % 5 == 0 else "train"


def _example_from_call(
    *,
    call: dict[str, Any],
    benchmark_case: dict[str, Any],
    scorecard: dict[str, Any],
    example_index: int,
) -> dict[str, Any] | None:
    candidates = call.get("policy_candidates", []) if isinstance(call.get("policy_candidates"), list) else []
    if not candidates:
        return None
    expected = _expected_output(call, candidates, scorecard)
    reward_score = int(expected.get("reward_score") or 0)
    split = _split_for_example(example_index, reward_score)
    selected = call.get("selected_policy_candidate") if isinstance(call.get("selected_policy_candidate"), dict) else None
    example = {
        "id": _hash_id(
            "timelapse_decision_example",
            {
                "candidate_run": benchmark_case.get("candidate_run"),
                "scenario": benchmark_case.get("scenario"),
                "sim_minute": call.get("sim_minute"),
                "selected": expected.get("final_selected_candidate_id"),
            },
        ),
        "created_at": _now_iso(),
        "materializer_version": MATERIALIZER_VERSION,
        "split": split,
        "source": "timelapse_gemini_operation_call",
        "training_scope": "parkpulse_timelapse_candidate_ranking",
        "scenario": benchmark_case.get("scenario"),
        "seed": benchmark_case.get("seed"),
        "sim_minute": call.get("sim_minute"),
        "input_payload": {
            "operating_phase": call.get("phase", {}),
            "state_digest": call.get("before_digest", {}),
            "deterministic_food_severity": expected.get("deterministic_food_severity"),
            "candidate_summaries": [_candidate_summary(candidate) for candidate in candidates],
            "llm_response": {
                "status": call.get("status"),
                "risk_classification": _risk_classification(call),
                "ranked_candidate_ids": _get(call, "parsed_response.ranked_candidate_ids", []),
                "selected_candidate_id": _get(call, "parsed_response.selected_candidate_id"),
                "operator_explanation": _get(call, "parsed_response.operator_explanation"),
                "rejected_alternatives": _get(call, "parsed_response.rejected_alternatives", []),
            },
            "selector_result": {
                "candidate_selection": call.get("candidate_selection", {}),
                "selected_policy_candidate": _candidate_summary(selected) if selected else None,
                "policy_gate": call.get("policy_gate", {}),
            },
        },
        "expected_output": expected,
        "evidence": {
            "benchmark_case": benchmark_case,
            "scorecard_path": benchmark_case.get("scorecard"),
            "case_regression_count": benchmark_case.get("regression_count"),
            "case_unresolved_tradeoff_count": benchmark_case.get("unresolved_tradeoff_count"),
            "case_reasoning_issue_count": benchmark_case.get("reasoning_issue_count"),
            "release_clean_case": (
                int(benchmark_case.get("critical_bypass") or 0) == 0
                and int(benchmark_case.get("gemini_errors") or 0) == 0
                and int(benchmark_case.get("reasoning_issue_count") or 0) == 0
                and int(benchmark_case.get("unresolved_tradeoff_count") or 0) == 0
            ),
            "scorecard_tradeoff_ledger": _get(scorecard, "bias_audit.tradeoff_ledger", {}),
        },
        "eligible_for_supervised_training": split == "train" and reward_score >= 80,
        "eligible_for_eval": split == "eval",
        "eligible_for_reward": True,
        "reward": {
            "score": reward_score,
            "issues": expected.get("quality_issues", []),
            "selected_candidate_score": expected.get("selected_candidate_score"),
            "ideal_candidate_score": expected.get("ideal_candidate_score"),
            "candidate_score_regret": expected.get("candidate_score_regret"),
        },
        "boundaries": {
            "offline_only": True,
            "gcp_training_started": False,
            "model_promotion_started": False,
            "llm_used_for_label": False,
            "labels_are_deterministic": True,
        },
    }
    return example


def _load_case_scorecard(case: dict[str, Any]) -> dict[str, Any]:
    scorecard_path = Path(str(case.get("scorecard") or "")).with_suffix(".json")
    return _load_json(scorecard_path)


def _examples_for_benchmark(benchmark: dict[str, Any]) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for case in benchmark.get("cases", []):
        if not isinstance(case, dict):
            continue
        candidate_run = Path(str(case.get("candidate_run") or ""))
        calls = _load_jsonl(candidate_run / "gemini-operation-calls.jsonl")
        scorecard = _load_case_scorecard(case)
        for call in calls:
            if not isinstance(call, dict):
                continue
            example = _example_from_call(
                call=call,
                benchmark_case=case,
                scorecard=scorecard,
                example_index=len(examples),
            )
            if example:
                examples.append(example)
    return examples


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


def _render_html(manifest: dict[str, Any], path: Path) -> None:
    summary = manifest.get("summary", {})
    reward = manifest.get("reward_distribution", {})
    issue_rows = [[key, value] for key, value in manifest.get("issue_counts", {}).items()]
    scenario_rows = [
        [
            scenario,
            values.get("count"),
            values.get("avg_reward"),
            values.get("low_reward_count"),
            values.get("train_count"),
            values.get("eval_count"),
        ]
        for scenario, values in sorted(manifest.get("scenario_summary", {}).items())
    ]
    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>ParkPulse Timelapse Model Improvement Material</title>
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
@media (max-width: 850px) {{ .stats {{ grid-template-columns: 1fr; }} table {{ font-size: 12px; }} }}
</style>
</head>
<body>
<main>
<h1>ParkPulse Timelapse Model Improvement Material</h1>
<p>{html.escape(str(manifest.get("source_benchmark")))} </p>
<section class="stats">
  <div class="stat">Examples<b>{summary.get("example_count", 0)}</b></div>
  <div class="stat">Supervised<b>{summary.get("supervised_example_count", 0)}</b></div>
  <div class="stat">Eval<b>{summary.get("eval_example_count", 0)}</b></div>
  <div class="stat">Avg reward<b>{reward.get("avg", 0)}</b></div>
</section>
<section class="card"><h2>Boundary</h2><p>This materializes offline training/evaluation examples only. It does not start training, promote a model, or dispatch actions.</p></section>
<section class="card"><h2>Scenario Summary</h2>{_html_table(scenario_rows, ["scenario", "examples", "avg reward", "low reward", "train", "eval"])}</section>
<section class="card"><h2>Issue Counts</h2>{_html_table(issue_rows, ["issue", "count"]) if issue_rows else "<p>No quality issues found.</p>"}</section>
</main>
</body>
</html>
"""
    path.write_text(doc, encoding="utf-8")


def materialize(benchmark_path: Path, output_dir: Path) -> dict[str, Any]:
    benchmark = _load_json(benchmark_path)
    if not benchmark:
        raise SystemExit(f"benchmark report not found or invalid: {benchmark_path}")
    examples = _examples_for_benchmark(benchmark)
    supervised = [row for row in examples if row.get("eligible_for_supervised_training")]
    eval_rows = [row for row in examples if row.get("eligible_for_eval")]
    reward_rows = [row for row in examples if row.get("eligible_for_reward")]
    rewards = [int(_get(row, "reward.score", 0) or 0) for row in examples]
    issues: Counter[str] = Counter()
    scenario_counts: dict[str, list[dict[str, Any]]] = {}
    for row in examples:
        scenario_counts.setdefault(str(row.get("scenario") or "unknown"), []).append(row)
        for issue in _get(row, "reward.issues", []) or []:
            issues[str(issue)] += 1

    run_dir = output_dir / f"timelapse-model-improvement-{_now_id()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "manifest": str(run_dir / "timelapse-model-improvement-manifest.json"),
        "examples_jsonl": str(run_dir / "timelapse-model-improvement-examples.jsonl"),
        "supervised_jsonl": str(run_dir / "timelapse-model-improvement-supervised.jsonl"),
        "eval_jsonl": str(run_dir / "timelapse-model-improvement-eval.jsonl"),
        "reward_jsonl": str(run_dir / "timelapse-model-improvement-reward.jsonl"),
        "html": str(run_dir / "timelapse-model-improvement-report.html"),
    }
    manifest = {
        "id": _hash_id("timelapse_model_improvement", {"benchmark": str(benchmark_path), "examples": len(examples)}),
        "created_at": _now_iso(),
        "status": "materialized" if examples else "empty",
        "materializer_version": MATERIALIZER_VERSION,
        "source_benchmark": str(benchmark_path),
        "benchmark_summary": benchmark.get("summary", {}),
        "summary": {
            "example_count": len(examples),
            "supervised_example_count": len(supervised),
            "eval_example_count": len(eval_rows),
            "reward_example_count": len(reward_rows),
            "low_reward_example_count": sum(1 for score in rewards if score < 80),
        },
        "reward_distribution": {
            "avg": round(mean(rewards), 3) if rewards else 0,
            "min": min(rewards) if rewards else 0,
            "max": max(rewards) if rewards else 0,
        },
        "issue_counts": dict(issues),
        "scenario_summary": {
            scenario: {
                "count": len(rows),
                "avg_reward": round(mean(int(_get(row, "reward.score", 0) or 0) for row in rows), 3) if rows else 0,
                "low_reward_count": sum(1 for row in rows if int(_get(row, "reward.score", 0) or 0) < 80),
                "train_count": sum(1 for row in rows if row.get("split") == "train"),
                "eval_count": sum(1 for row in rows if row.get("split") == "eval"),
            }
            for scenario, rows in scenario_counts.items()
        },
        "training_rule": "Offline examples supervise candidate ranking and explanation quality. Promotion requires a separate fixed benchmark run.",
        "boundaries": [
            "No GCP training job started.",
            "No model promotion started.",
            "No live park action dispatch started.",
            "Labels are deterministic from policy gates, candidate scores, scorecards, and selected action deltas.",
            "Reward rows are offline material only until a separate training/evaluation pipeline consumes them.",
        ],
        "artifacts": artifacts,
    }
    Path(artifacts["manifest"]).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_jsonl(Path(artifacts["examples_jsonl"]), examples)
    _write_jsonl(Path(artifacts["supervised_jsonl"]), supervised)
    _write_jsonl(Path(artifacts["eval_jsonl"]), eval_rows)
    _write_jsonl(Path(artifacts["reward_jsonl"]), reward_rows)
    _render_html(manifest, Path(artifacts["html"]))
    return manifest


def _persist_examples_to_mongodb(examples: list[dict[str, Any]], manifest_path: str) -> dict[str, Any]:
    try:
        import sys

        backend_dir = REPO_ROOT / "backend"
        if str(backend_dir) not in sys.path:
            sys.path.insert(0, str(backend_dir))
        from mongo_memory import get_memory_connection_status, record_timelapse_model_examples

        result = record_timelapse_model_examples(examples, source_manifest=manifest_path)
        return {
            **result,
            "memoryStatus": get_memory_connection_status(),
            "durable": bool(result.get("connected")),
            "boundary": "MongoDB-connected writes are durable. Demo fallback writes are process-local only.",
        }
    except Exception as error:
        return {
            "status": "skipped",
            "storedCount": 0,
            "durable": False,
            "error": str(error)[:500],
            "boundary": "No model training or promotion was attempted.",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize timelapse LLM decision traces into offline model-improvement examples.")
    parser.add_argument("--benchmark-report", required=True, help="Path to frozen-benchmark-report.json.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT), help="Output root for model-improvement artifacts.")
    parser.add_argument("--persist-mongodb", action="store_true", help="Persist materialized examples into MongoDB operational memory.")
    args = parser.parse_args()
    manifest = materialize(Path(args.benchmark_report).expanduser().resolve(), Path(args.output_dir).expanduser().resolve())
    if args.persist_mongodb:
        examples = _load_jsonl(Path(manifest["artifacts"]["examples_jsonl"]))
        memory_persistence = _persist_examples_to_mongodb(examples, manifest["artifacts"]["manifest"])
        manifest["mongodb_persistence"] = memory_persistence
        Path(manifest["artifacts"]["manifest"]).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "examples": manifest["summary"]["example_count"],
                "supervised": manifest["summary"]["supervised_example_count"],
                "eval": manifest["summary"]["eval_example_count"],
                "reward": manifest["summary"]["reward_example_count"],
                "avg_reward": manifest["reward_distribution"]["avg"],
                "mongodb": manifest.get("mongodb_persistence", {"status": "not_requested"}),
                "html": manifest["artifacts"]["html"],
                "manifest": manifest["artifacts"]["manifest"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
