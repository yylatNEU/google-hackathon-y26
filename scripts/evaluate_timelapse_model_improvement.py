#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import html
import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

DEFAULT_OUTPUT_ROOT = REPO_ROOT / "output" / "qa"
EVALUATOR_VERSION = "timelapse-model-improvement-eval-v1"


def _now_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
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


def _get(row: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = row
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return default
    return current


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _first_json_object(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text or ""):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _candidate_ids(example: dict[str, Any]) -> set[str]:
    return {
        str(item.get("id"))
        for item in _get(example, "input_payload.candidate_summaries", [])
        if isinstance(item, dict) and item.get("id")
    }


def _candidate_by_id(example: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("id")): item
        for item in _get(example, "input_payload.candidate_summaries", [])
        if isinstance(item, dict) and item.get("id")
    }


def _candidate_deltas(example: dict[str, Any], candidate_id: str) -> dict[str, float]:
    candidate = _candidate_by_id(example).get(candidate_id, {})
    deltas = candidate.get("deltas", {}) if isinstance(candidate.get("deltas"), dict) else {}
    parsed: dict[str, float] = {}
    for key, value in deltas.items():
        try:
            parsed[str(key)] = float(value)
        except (TypeError, ValueError):
            parsed[str(key)] = 0.0
    return parsed


REGRESSION_DELTA_KEYS = {
    "satisfaction": ("avg_satisfaction_delta", False),
    "slowest_ride_wait": ("slowest_ride_wait_delta", True),
    "food_backlog": ("food_backlog_delta", True),
    "food_eta_minutes": ("food_eta_minutes_delta", True),
    "busiest_zone_density": ("busiest_zone_density_delta", True),
    "path_congestion": ("path_congestion_delta", True),
    "open_callouts": ("open_callouts_delta", True),
    "grid_load": ("grid_load_delta", True),
}


def _outcome_equivalent_selection(example: dict[str, Any], selected: str, ideal: str) -> bool:
    if not selected or not ideal or selected == ideal:
        return selected == ideal
    selected_deltas = _candidate_deltas(example, selected)
    ideal_deltas = _candidate_deltas(example, ideal)
    regressions = [str(item) for item in _get(example, "expected_output.case_metric_regressions", []) or []]
    comparable = [metric for metric in regressions if metric in REGRESSION_DELTA_KEYS]
    if not comparable:
        return False
    no_worse_count = 0
    for metric in comparable:
        delta_key, lower_is_better = REGRESSION_DELTA_KEYS[metric]
        selected_value = selected_deltas.get(delta_key, 0.0)
        ideal_value = ideal_deltas.get(delta_key, 0.0)
        if lower_is_better:
            if selected_value <= ideal_value + 1.0:
                no_worse_count += 1
        elif selected_value >= ideal_value - 0.25:
            no_worse_count += 1
    return no_worse_count >= max(1, len(comparable) - 1)


def _blocked_candidate_ids(example: dict[str, Any]) -> set[str]:
    return set(str(item) for item in _get(example, "expected_output.blocked_candidate_ids", []) or [])


def _passed_candidate_ids(example: dict[str, Any]) -> set[str]:
    return _candidate_ids(example) - _blocked_candidate_ids(example)


def _recorded_response(example: dict[str, Any]) -> dict[str, Any]:
    response = _get(example, "input_payload.llm_response", {})
    if not isinstance(response, dict):
        return {}
    return {
        "risk_classification": response.get("risk_classification", {}),
        "ranked_candidate_ids": response.get("ranked_candidate_ids", []),
        "selected_candidate_id": response.get("selected_candidate_id"),
        "operator_explanation": response.get("operator_explanation") or "",
        "rejected_alternatives": response.get("rejected_alternatives", []),
        "source": "recorded_llm_response",
    }


def _memory_query(example: dict[str, Any]) -> str:
    expected = example.get("expected_output", {}) if isinstance(example.get("expected_output"), dict) else {}
    digest = _get(example, "input_payload.state_digest", {})
    slowest = digest.get("slowest_ride", {}) if isinstance(digest, dict) and isinstance(digest.get("slowest_ride"), dict) else {}
    return " ".join(
        str(part)
        for part in (
            example.get("scenario"),
            expected.get("deterministic_food_severity"),
            " ".join(expected.get("case_metric_regressions", []) if isinstance(expected.get("case_metric_regressions"), list) else []),
            digest.get("food_backlog") if isinstance(digest, dict) else None,
            digest.get("food_eta_minutes") if isinstance(digest, dict) else None,
            slowest.get("waitMins"),
            digest.get("open_callouts") if isinstance(digest, dict) else None,
        )
        if part is not None
    )


def _compact_memory_example(row: dict[str, Any]) -> dict[str, Any]:
    expected = row.get("expected_output", {}) if isinstance(row.get("expected_output"), dict) else {}
    reward = row.get("reward", {}) if isinstance(row.get("reward"), dict) else {}
    return {
        "id": row.get("id") or row.get("_id"),
        "scenario": row.get("scenario") or row.get("scenarioKey"),
        "split": row.get("split"),
        "food_severity": expected.get("deterministic_food_severity") or row.get("foodSeverity"),
        "case_metric_regressions": expected.get("case_metric_regressions") or row.get("caseMetricRegressions", []),
        "ideal_candidate_id": expected.get("ideal_candidate_id") or row.get("idealCandidateId"),
        "ideal_action": expected.get("ideal_action"),
        "selected_candidate_id": expected.get("final_selected_candidate_id") or row.get("selectedCandidateId"),
        "reward_score": reward.get("score") or row.get("rewardScore"),
        "quality_issues": reward.get("issues") or row.get("qualityIssues", []),
        "lesson": "Prefer the candidate that repairs the metrics that actually regressed in the prior scorecard, not just the raw highest score.",
    }


def _retrieve_memory_context(example: dict[str, Any], *, use_memory: bool, limit: int) -> dict[str, Any]:
    if not use_memory:
        return {"status": "disabled", "examples": []}
    try:
        from mongo_memory import retrieve_timelapse_model_memory

        result = retrieve_timelapse_model_memory(
            _memory_query(example),
            scenario_key=str(example.get("scenario") or ""),
            limit=max(limit * 3, limit),
            exclude_ids=[str(example.get("id") or "")],
        )
        examples = [
            _compact_memory_example(row)
            for row in result.get("examples", [])
            if isinstance(row, dict) and str(row.get("split") or "") == "train"
        ][:limit]
        return {
            "status": "ready" if examples else "no_train_memory",
            "method": result.get("method"),
            "mode": result.get("mode"),
            "connected": result.get("connected"),
            "query": result.get("query"),
            "examples": examples,
            "raw_count": result.get("count", 0),
        }
    except Exception as error:
        return {"status": "error", "error": str(error)[:500], "examples": []}


def _build_prompt(example: dict[str, Any], memory_context: dict[str, Any] | None = None) -> dict[str, Any]:
    expected = example.get("expected_output", {}) if isinstance(example.get("expected_output"), dict) else {}
    payload = example.get("input_payload", {}) if isinstance(example.get("input_payload"), dict) else {}
    memory_context = memory_context or {"status": "disabled", "examples": []}
    return {
        "role": "ParkPulse outcome-aligned candidate ranker",
        "task": "Rank supplied policy-passed candidates for this held-out park operation example. Do not invent actions.",
        "output_contract": {
            "risk_classification": {
                "primary_risk": "food | ride | staffing | traffic | energy | signage",
                "severity": "normal | p2_warning | p1_critical | p0_gridlock",
                "why": "short evidence-based explanation",
            },
            "ranked_candidate_ids": ["policy-passed candidate IDs only, best first"],
            "selected_candidate_id": "one exact policy-passed candidate ID",
            "tradeoff_focus": ["metric names the decision is protecting"],
            "rejected_alternatives": [{"candidate_id": "candidate ID", "reason": "why rejected"}],
            "operator_explanation": "concise internal explanation including the main tradeoff",
        },
        "instructions": [
            "Return JSON only.",
            "Return the output fields at the top level. Do not wrap the answer inside output_contract or another object.",
            "Use candidate IDs exactly as supplied.",
            "Never rank or select blocked candidates.",
            "risk_classification.severity must exactly equal outcome_learning_context.deterministic_food_severity.",
            "Do not blindly follow raw candidate score when outcome_learning_context identifies a case-level regression.",
            "If food_backlog or food_eta_minutes regressed and food severity is p2_warning or worse, favor candidates with negative food deltas unless they create a larger explicit safety or staffing harm.",
            "If slowest_ride_wait, busiest_zone_density, path_congestion, or open_callouts regressed and food is not p1/p0 critical, favor candidates that improve those metrics.",
            "Explain the top rejected tempting alternative, especially if it has a high raw score but misses the regression being corrected.",
            "Use retrieved_memory_examples as prior lessons only. Do not copy them if current severity, regressions, or candidate deltas differ.",
        ],
        "candidate_id_set": sorted(_candidate_ids(example)),
        "blocked_candidate_ids": sorted(_blocked_candidate_ids(example)),
        "outcome_learning_context": {
            "deterministic_food_severity": expected.get("deterministic_food_severity"),
            "case_metric_regressions": expected.get("case_metric_regressions", []),
            "deterministic_score_best_candidate_id": expected.get("deterministic_score_best_candidate_id"),
            "deterministic_score_best_action": expected.get("deterministic_score_best_action"),
            "retrieved_memory_examples": memory_context.get("examples", []),
            "memory_status": {
                "status": memory_context.get("status"),
                "method": memory_context.get("method"),
                "connected": memory_context.get("connected"),
                "raw_count": memory_context.get("raw_count"),
            },
        },
        "park_context": {
            "scenario": example.get("scenario"),
            "sim_minute": example.get("sim_minute"),
            "operating_phase": payload.get("operating_phase", {}),
            "state_digest": payload.get("state_digest", {}),
            "candidate_summaries": payload.get("candidate_summaries", []),
        },
    }


def _normalize_response(response: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {}
    nested = response.get("output_contract")
    if isinstance(nested, dict) and ("selected_candidate_id" in nested or "ranked_candidate_ids" in nested):
        return nested
    return response


def _score_response(example: dict[str, Any], response: dict[str, Any], *, source: str) -> dict[str, Any]:
    response = _normalize_response(response)
    ideal_id = str(_get(example, "expected_output.ideal_candidate_id") or "")
    expected_severity = str(_get(example, "expected_output.deterministic_food_severity") or "")
    expected_regressions = set(str(item) for item in _get(example, "expected_output.case_metric_regressions", []) or [])
    candidate_ids = _candidate_ids(example)
    blocked_ids = _blocked_candidate_ids(example)
    passed_ids = _passed_candidate_ids(example)
    ranked = [str(item) for item in _as_list(response.get("ranked_candidate_ids"))]
    selected = str(response.get("selected_candidate_id") or "")
    risk = response.get("risk_classification", {}) if isinstance(response.get("risk_classification"), dict) else {}
    explanation = str(response.get("operator_explanation") or "")
    tradeoff_focus = set(str(item) for item in _as_list(response.get("tradeoff_focus")))
    equivalent_selected = _outcome_equivalent_selection(example, selected, ideal_id)

    issues: list[str] = []
    score = 0
    if selected == ideal_id:
        score += 45
    elif equivalent_selected and selected in passed_ids:
        score += 40
        issues.append("selected_outcome_equivalent_alternative")
    elif selected in passed_ids:
        score += 18
        issues.append("selected_not_ideal")
    else:
        issues.append("selected_invalid_or_blocked")

    top_ranked = ranked[0] if ranked else ""
    if ranked and (top_ranked == ideal_id or _outcome_equivalent_selection(example, top_ranked, ideal_id)):
        score += 25
    elif ideal_id in ranked[:3]:
        score += 12
        issues.append("ideal_not_top_ranked")
    else:
        issues.append("ideal_missing_from_top_three")

    invalid_ranked = [item for item in ranked if item not in candidate_ids]
    blocked_ranked = [item for item in ranked if item in blocked_ids]
    if not invalid_ranked:
        score += 8
    else:
        issues.append("ranked_invalid_candidate")
    if not blocked_ranked:
        score += 8
    else:
        issues.append("ranked_blocked_candidate")

    severity = str(risk.get("severity") or "")
    severity_matches = severity == expected_severity
    if severity == expected_severity:
        score += 6
    else:
        issues.append("severity_mismatch")

    if expected_regressions:
        if tradeoff_focus & expected_regressions:
            score += 6
        elif any(metric in explanation for metric in expected_regressions):
            score += 4
        else:
            issues.append("missing_regression_tradeoff_focus")
    else:
        score += 6

    if explanation.strip():
        score += 8
    else:
        issues.append("missing_operator_explanation")

    return {
        "example_id": example.get("id"),
        "scenario": example.get("scenario"),
        "sim_minute": example.get("sim_minute"),
        "source": source,
        "score": max(0, min(100, score)),
        "passed": score >= 80 and (selected == ideal_id or equivalent_selected) and severity_matches and not blocked_ranked and not invalid_ranked,
        "outcome_equivalent_selected": bool(equivalent_selected),
        "ideal_candidate_id": ideal_id,
        "selected_candidate_id": selected or None,
        "top_ranked_candidate_id": ranked[0] if ranked else None,
        "issues": issues,
        "expected_regressions": sorted(expected_regressions),
        "expected_food_severity": expected_severity,
        "model_food_severity": severity or None,
        "response": response,
    }


async def _call_gemini(prompt: dict[str, Any], *, timeout_seconds: float, max_output_tokens: int, temperature: float) -> tuple[dict[str, Any], dict[str, Any]]:
    from gemini_hard_timeout import generate_gemini_json_hard_timeout

    started = time.perf_counter()
    result = await generate_gemini_json_hard_timeout(
        prompt,
        timeout_seconds=timeout_seconds,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
    )
    parsed = _first_json_object(str(result.get("text") or ""))
    metadata = {
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "transport": result.get("transport"),
        "finish_reason": result.get("finish_reason"),
        "usage_metadata": result.get("usage_metadata", {}),
        "raw_text": result.get("text"),
    }
    return parsed, metadata


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"count": 0}
    issue_counts: Counter[str] = Counter()
    scenario_rows: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        scenario_rows.setdefault(str(row.get("scenario") or "unknown"), []).append(row)
        for issue in row.get("issues", []) or []:
            issue_counts[str(issue)] += 1
    return {
        "count": len(rows),
        "passed": sum(1 for row in rows if row.get("passed")),
        "avg_score": round(mean(float(row.get("score") or 0) for row in rows), 3),
        "exact_ideal_selected": sum(1 for row in rows if row.get("selected_candidate_id") == row.get("ideal_candidate_id")),
        "issue_counts": dict(issue_counts),
        "scenario_summary": {
            scenario: {
                "count": len(items),
                "passed": sum(1 for item in items if item.get("passed")),
                "avg_score": round(mean(float(item.get("score") or 0) for item in items), 3),
            }
            for scenario, items in sorted(scenario_rows.items())
        },
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


def _render_html(report: dict[str, Any], path: Path) -> None:
    recorded = report.get("recorded_summary", {})
    gemini = report.get("gemini_summary", {})
    memory = report.get("memory_summary", {})
    issue_rows = [[key, value] for key, value in (gemini.get("issue_counts") or recorded.get("issue_counts") or {}).items()]
    case_rows = [
        [
            row.get("source"),
            row.get("scenario"),
            row.get("sim_minute"),
            row.get("score"),
            row.get("passed"),
            row.get("ideal_candidate_id"),
            row.get("selected_candidate_id"),
            ", ".join(row.get("issues", []) or []),
        ]
        for row in report.get("results", [])
    ]
    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>ParkPulse Timelapse Model Improvement Eval</title>
<style>
body {{ margin: 0; font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #182230; }}
main {{ max-width: 1180px; margin: 0 auto; padding: 30px 22px 56px; }}
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
<h1>ParkPulse Timelapse Model Improvement Eval</h1>
<p>{html.escape(str(report.get("eval_jsonl")))}</p>
<section class="stats">
  <div class="stat">Examples<b>{recorded.get("count", 0)}</b></div>
  <div class="stat">Recorded avg<b>{recorded.get("avg_score", 0)}</b></div>
  <div class="stat">Gemini avg<b>{gemini.get("avg_score", "not run")}</b></div>
  <div class="stat">Gemini passed<b>{gemini.get("passed", "not run")}</b></div>
</section>
<section class="stats">
  <div class="stat">Memory enabled<b>{report.get("use_mongodb_memory", False)}</b></div>
  <div class="stat">Memory calls<b>{memory.get("calls_with_memory", 0)} / {gemini.get("count", 0)}</b></div>
  <div class="stat">Mongo connected<b>{memory.get("connected", False)}</b></div>
  <div class="stat">Memory limit<b>{report.get("memory_limit", "none")}</b></div>
</section>
<section class="stats">
  <div class="stat">Memory status<b>{", ".join(f"{key}:{value}" for key, value in (memory.get("statuses", {}) if isinstance(memory.get("statuses"), dict) else {}).items()) or "none"}</b></div>
  <div class="stat">Memory method<b>{", ".join(f"{key}:{value}" for key, value in (memory.get("methods", {}) if isinstance(memory.get("methods"), dict) else {}).items()) or "none"}</b></div>
</section>
<section class="card"><h2>Readout</h2><p>{html.escape(str(report.get("decision", "")))}</p></section>
<section class="card"><h2>Issue Counts</h2>{_html_table(issue_rows, ["issue", "count"]) if issue_rows else "<p>No issues.</p>"}</section>
<section class="card"><h2>Results</h2>{_html_table(case_rows, ["source", "scenario", "minute", "score", "passed", "ideal", "selected", "issues"])}</section>
</main>
</body>
</html>
"""
    path.write_text(doc, encoding="utf-8")


async def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    eval_path = Path(args.eval_jsonl).expanduser().resolve()
    examples = _load_jsonl(eval_path)
    output_dir = Path(args.output_dir).expanduser().resolve() / f"timelapse-model-eval-{_now_id()}"
    output_dir.mkdir(parents=True, exist_ok=True)

    recorded_results = [_score_response(example, _recorded_response(example), source="recorded") for example in examples]
    gemini_results: list[dict[str, Any]] = []
    call_rows: list[dict[str, Any]] = []
    if args.call_gemini:
        for example in examples:
            memory_context = _retrieve_memory_context(example, use_memory=args.use_mongodb_memory, limit=args.memory_limit)
            prompt = _build_prompt(example, memory_context)
            try:
                parsed, metadata = await _call_gemini(
                    prompt,
                    timeout_seconds=args.gemini_timeout_seconds,
                    max_output_tokens=args.output_tokens,
                    temperature=args.temperature,
                )
                if not parsed:
                    raise RuntimeError("Gemini returned no parseable JSON.")
                scored = _score_response(example, parsed, source="gemini")
                scored["call_metadata"] = {key: value for key, value in metadata.items() if key != "raw_text"}
                call_rows.append(
                    {
                        "example_id": example.get("id"),
                        "prompt": prompt,
                        "memory_context": memory_context,
                        "response": parsed,
                        "metadata": metadata,
                        "score": scored,
                    }
                )
                gemini_results.append(scored)
            except Exception as error:
                scored = {
                    "example_id": example.get("id"),
                    "scenario": example.get("scenario"),
                    "sim_minute": example.get("sim_minute"),
                    "source": "gemini",
                    "score": 0,
                    "passed": False,
                    "ideal_candidate_id": _get(example, "expected_output.ideal_candidate_id"),
                    "selected_candidate_id": None,
                    "top_ranked_candidate_id": None,
                    "issues": ["gemini_call_or_parse_error"],
                    "error": str(error)[:700],
                }
                call_rows.append({"example_id": example.get("id"), "memory_context": memory_context, "error": str(error)[:700], "score": scored})
                gemini_results.append(scored)

    recorded_summary = _summarize(recorded_results)
    gemini_summary = _summarize(gemini_results)
    if args.call_gemini:
        decision = (
            "MODEL_EVAL_PASSED"
            if gemini_summary.get("passed", 0) == gemini_summary.get("count", 0) and gemini_summary.get("avg_score", 0) >= 90
            else "MODEL_EVAL_NEEDS_IMPROVEMENT"
        )
    else:
        decision = "RECORDED_BASELINE_ONLY"

    report = {
        "status": "complete",
        "created_at": _now_iso(),
        "evaluator_version": EVALUATOR_VERSION,
        "eval_jsonl": str(eval_path),
        "call_gemini": bool(args.call_gemini),
        "use_mongodb_memory": bool(args.use_mongodb_memory),
        "memory_limit": args.memory_limit,
        "memory_summary": {
            "calls_with_memory": sum(1 for row in call_rows if _get(row, "memory_context.examples", [])),
            "connected": any(_get(row, "memory_context.connected") for row in call_rows),
            "statuses": dict(Counter(str(_get(row, "memory_context.status", "not_used")) for row in call_rows)),
            "methods": dict(Counter(str(_get(row, "memory_context.method", "none")) for row in call_rows if row.get("memory_context"))),
        },
        "decision": decision,
        "recorded_summary": recorded_summary,
        "gemini_summary": gemini_summary,
        "results": [*recorded_results, *gemini_results],
        "boundaries": [
            "Offline eval only.",
            "No training job started.",
            "No model promotion started.",
            "No live park dispatch started.",
        ],
    }
    report_json = output_dir / "timelapse-model-eval-report.json"
    report_html = output_dir / "timelapse-model-eval-report.html"
    calls_jsonl = output_dir / "timelapse-model-eval-calls.jsonl"
    report["artifacts"] = {"json": str(report_json), "html": str(report_html), "calls_jsonl": str(calls_jsonl)}
    report_json.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    _write_jsonl(calls_jsonl, call_rows)
    _render_html(report, report_html)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate timelapse model-improvement eval examples against recorded decisions or live Gemini.")
    parser.add_argument("--eval-jsonl", required=True, help="Path to timelapse-model-improvement-eval.jsonl.")
    parser.add_argument("--call-gemini", action="store_true", help="Call Gemini on each eval example. Without this, only recorded decisions are scored.")
    parser.add_argument("--use-mongodb-memory", action="store_true", help="Retrieve similar train examples from MongoDB memory and include them in the Gemini prompt.")
    parser.add_argument("--memory-limit", type=int, default=3)
    parser.add_argument("--gemini-timeout-seconds", type=float, default=8.0)
    parser.add_argument("--output-tokens", type=int, default=700)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    args = parser.parse_args()
    report = asyncio.run(evaluate(args))
    print(
        json.dumps(
            {
                "status": report["status"],
                "decision": report["decision"],
                "recorded": report["recorded_summary"],
                "gemini": report["gemini_summary"],
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
