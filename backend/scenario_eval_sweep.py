from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable


DEFAULT_SWEEP_SCENARIOS = ("ride_down", "staff_shortage", "food_spike", "storm_response")


ScenarioRunner = Callable[[str, bool], Awaitable[dict[str, Any]]]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _vertex_score_100(vertex_metric: dict[str, Any]) -> float | None:
    score = _as_float(vertex_metric.get("score"))
    if score is None:
        return None
    return round(score * 100 if score <= 1 else score, 2)


def _selected_action(result: dict[str, Any]) -> dict[str, Any]:
    optimization = result.get("optimization", {}) if isinstance(result.get("optimization"), dict) else {}
    selected_plan = optimization.get("selected_plan", {}) if isinstance(optimization.get("selected_plan"), dict) else {}
    selected = selected_plan.get("selected_action") if isinstance(selected_plan.get("selected_action"), dict) else None
    if selected:
        return selected
    planner = result.get("planner", {}) if isinstance(result.get("planner"), dict) else {}
    return planner.get("selected_action", {}) if isinstance(planner.get("selected_action"), dict) else {}


def summarize_scenario_result(result: dict[str, Any], *, elapsed_ms: int | None = None) -> dict[str, Any]:
    eval_result = result.get("eval", {}) if isinstance(result.get("eval"), dict) else {}
    scorecard = eval_result.get("scorecard", {}) if isinstance(eval_result.get("scorecard"), dict) else {}
    hosted_eval = eval_result.get("hosted_eval", {}) if isinstance(eval_result.get("hosted_eval"), dict) else {}
    vertex_result = hosted_eval.get("vertex_result", {}) if isinstance(hosted_eval.get("vertex_result"), dict) else {}
    vertex_metric = vertex_result.get("result", {}) if isinstance(vertex_result.get("result"), dict) else {}
    dimension_scores = eval_result.get("dimension_scores", {}) if isinstance(eval_result.get("dimension_scores"), dict) else {}
    response = result.get("delivery", {}).get("response", {}) if isinstance(result.get("delivery"), dict) else {}
    internal_score = _as_float(scorecard.get("overall"))
    vertex_100 = _vertex_score_100(vertex_metric)
    delta = round(vertex_100 - internal_score, 2) if vertex_100 is not None and internal_score is not None else None
    low_dimensions = [
        {"dimension": key, "score": value}
        for key, value in dimension_scores.items()
        if _as_float(value) is not None and float(value) < 75
    ]
    selected_action = _selected_action(result)
    return {
        "scenario_key": result.get("scenario_key"),
        "status": result.get("status"),
        "elapsed_ms": elapsed_ms,
        "decision_id": result.get("decision_id"),
        "outcome_id": result.get("outcome_id"),
        "selected_action": {
            "label": selected_action.get("label") or selected_action.get("title"),
            "target": selected_action.get("target"),
            "action": selected_action.get("action"),
            "owner": selected_action.get("owner"),
        },
        "internal": {
            "overall": internal_score,
            "plan_quality_score": _as_float(scorecard.get("plan_quality_score")),
            "outcome_effectiveness_score": _as_float(scorecard.get("outcome_effectiveness_score")),
            "score_method": scorecard.get("score_method"),
            "status": scorecard.get("status"),
            "response_score": _as_float(scorecard.get("response_score")),
            "policy_gate_status": scorecard.get("policy_gate_status"),
            "needs_human_approval": scorecard.get("needs_human_approval"),
            "failure_count": len(eval_result.get("failure_reasons", []) if isinstance(eval_result.get("failure_reasons"), list) else []),
            "low_dimensions": low_dimensions,
        },
        "response": {
            "status": response.get("status"),
            "score": _as_float(response.get("score")),
            "take_rate": _as_float(response.get("takeRate")),
            "positive_response_rate": _as_float(response.get("positiveResponseRate")),
            "follow_through_rate": _as_float(response.get("reactiveFollowThroughRate")),
        },
        "vertex": {
            "status": vertex_result.get("status"),
            "transport": vertex_result.get("transport"),
            "score": vertex_metric.get("score"),
            "score_100": vertex_100,
            "explanation": vertex_metric.get("explanation"),
            "evaluator_id": vertex_result.get("evaluator_id") or hosted_eval.get("evaluator_id"),
            "location": vertex_result.get("location") or hosted_eval.get("location"),
        },
        "comparison": {
            "delta_vertex_minus_internal": delta,
            "aligned": abs(delta) <= 20 if delta is not None else False,
            "needs_review": delta is None or abs(delta) > 20 or bool(low_dimensions),
        },
    }


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [row for row in rows if row.get("status") == "complete"]
    vertex_completed = [row for row in completed if row.get("vertex", {}).get("status") == "completed"]
    internal_scores = [row["internal"]["overall"] for row in completed if row.get("internal", {}).get("overall") is not None]
    vertex_scores = [row["vertex"]["score_100"] for row in vertex_completed if row.get("vertex", {}).get("score_100") is not None]
    deltas = [
        abs(row["comparison"]["delta_vertex_minus_internal"])
        for row in vertex_completed
        if row.get("comparison", {}).get("delta_vertex_minus_internal") is not None
    ]
    aligned = sum(1 for row in vertex_completed if row.get("comparison", {}).get("aligned"))
    return {
        "scenario_count": len(rows),
        "completed_count": len(completed),
        "vertex_completed_count": len(vertex_completed),
        "aligned_count": aligned,
        "avg_internal_score": round(sum(internal_scores) / len(internal_scores), 2) if internal_scores else None,
        "avg_vertex_score_100": round(sum(vertex_scores) / len(vertex_scores), 2) if vertex_scores else None,
        "avg_abs_delta": round(sum(deltas) / len(deltas), 2) if deltas else None,
    }


def build_sweep_analytics_rows(sweep_result: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    now = _now_iso()
    sweep_id = sweep_result.get("sweep_id")
    rows: list[dict[str, Any]] = []
    for scenario in sweep_result.get("scenarios", []) if isinstance(sweep_result.get("scenarios"), list) else []:
        if not isinstance(scenario, dict):
            continue
        internal = scenario.get("internal", {}) if isinstance(scenario.get("internal"), dict) else {}
        vertex = scenario.get("vertex", {}) if isinstance(scenario.get("vertex"), dict) else {}
        comparison = scenario.get("comparison", {}) if isinstance(scenario.get("comparison"), dict) else {}
        low_dimensions = internal.get("low_dimensions", []) if isinstance(internal.get("low_dimensions"), list) else []
        rows.append(
            {
                "exported_at": now,
                "decision_id": scenario.get("decision_id") or f"{sweep_id}:{scenario.get('scenario_key')}",
                "outcome_id": scenario.get("outcome_id"),
                "scenario_key": scenario.get("scenario_key"),
                "source": "vertex_eval_scenario_sweep",
                "overall": _as_float(internal.get("overall")),
                "response_score": _as_float(internal.get("outcome_effectiveness_score") or internal.get("response_score")),
                "status": internal.get("status") or scenario.get("status"),
                "trace_id": None,
                "span_id": None,
                "trace_url": None,
                "trace_state": "scenario_sweep",
                "judge_mode": "vertex_eval_scenario_sweep",
                "evaluation_status": scenario.get("status"),
                "hosted_evaluator_id": vertex.get("evaluator_id"),
                "vertex_score": _as_float(vertex.get("score")),
                "vertex_status": vertex.get("status"),
                "vertex_transport": vertex.get("transport"),
                "vertex_explanation": vertex.get("explanation"),
                "policy_gate_status": internal.get("policy_gate_status"),
                "needs_human_approval": internal.get("needs_human_approval"),
                "dimensions_json": json.dumps([item.get("dimension") for item in low_dimensions if isinstance(item, dict)], sort_keys=True),
                "dimension_scores_json": json.dumps(
                    {
                        "overall": internal.get("overall"),
                        "plan_quality_score": internal.get("plan_quality_score"),
                        "outcome_effectiveness_score": internal.get("outcome_effectiveness_score"),
                        "delta_vertex_minus_internal": comparison.get("delta_vertex_minus_internal"),
                    },
                    sort_keys=True,
                    default=str,
                ),
                "dimension_explanations_json": internal.get("score_method"),
                "failure_reasons_json": json.dumps(low_dimensions, sort_keys=True, default=str),
            }
        )
    return {"eval_results": rows}


def latest_sweep_payload(rows: list[dict[str, Any]], *, max_age_hours: int = 24) -> dict[str, Any]:
    sweep = next((row for row in rows if isinstance(row, dict) and row.get("documentType") == "scenario_eval_sweep"), None)
    if not sweep:
        return {
            "status": "empty",
            "source": "parkpulse_reactive_path_vertex_eval_sweep",
            "freshness": {"status": "missing", "stale": True, "max_age_hours": max_age_hours},
            "summary": {"scenario_count": len(DEFAULT_SWEEP_SCENARIOS), "completed_count": 0, "vertex_completed_count": 0, "aligned_count": 0},
            "recommendation": {
                "decision": "GO WITH CONDITIONS",
                "reason": "No persisted Vertex scenario sweep has been recorded yet.",
                "conditions": ["Run the Vertex sweep before using eval alignment as demo evidence."],
            },
            "scenarios": [],
        }
    created_at = _parse_iso(sweep.get("createdAt"))
    age_hours = round((datetime.now(UTC) - created_at).total_seconds() / 3600, 2) if created_at else None
    stale = age_hours is None or age_hours > max_age_hours
    return {
        "sweep_id": sweep.get("_id"),
        "status": sweep.get("status", "complete"),
        "source": sweep.get("source", "vertex_eval_scenario_sweep"),
        "execute": sweep.get("execute"),
        "checked_at": sweep.get("createdAt"),
        "summary": sweep.get("summary", {}),
        "recommendation": sweep.get("recommendation", {}),
        "scenarios": sweep.get("scenarios", []),
        "persistence": {"mongo_eval_document_id": sweep.get("_id")},
        "freshness": {
            "status": "stale" if stale else "fresh",
            "stale": stale,
            "age_hours": age_hours,
            "max_age_hours": max_age_hours,
        },
    }


def _recommendation(summary: dict[str, Any]) -> dict[str, Any]:
    if summary["completed_count"] < summary["scenario_count"]:
        return {
            "decision": "NO-GO",
            "reason": "At least one real scenario did not complete through the reactive path.",
            "conditions": ["Fix scenario execution errors before using Vertex scores as trend data."],
        }
    if summary["vertex_completed_count"] < summary["scenario_count"]:
        return {
            "decision": "GO WITH CONDITIONS",
            "reason": "The internal eval loop ran, but not every scenario produced a Vertex score.",
            "conditions": ["Resolve Vertex failures or quotas before treating hosted eval coverage as complete."],
        }
    if summary["aligned_count"] < summary["scenario_count"]:
        return {
            "decision": "GO WITH CONDITIONS",
            "reason": "Vertex and internal scores disagree on at least one scenario by more than 20 points.",
            "conditions": ["Review rubric wording and low-dimension scenarios before optimizing prompts from the scores."],
        }
    return {
        "decision": "GO",
        "reason": "All scenarios completed and Vertex scores are directionally aligned with internal scorecards.",
        "conditions": [],
    }


async def run_vertex_eval_scenario_sweep(
    run_scenario: ScenarioRunner,
    *,
    scenario_keys: list[str] | tuple[str, ...] | None = None,
    execute: bool = False,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for scenario_key in scenario_keys or DEFAULT_SWEEP_SCENARIOS:
        start = time.perf_counter()
        try:
            result = await asyncio.wait_for(run_scenario(str(scenario_key), execute), timeout=timeout_seconds)
            rows.append(summarize_scenario_result(result, elapsed_ms=round((time.perf_counter() - start) * 1000)))
        except TimeoutError:
            rows.append(
                {
                    "scenario_key": scenario_key,
                    "status": "timeout",
                    "elapsed_ms": round((time.perf_counter() - start) * 1000),
                    "error": f"Scenario exceeded {timeout_seconds}s.",
                    "comparison": {"aligned": False, "needs_review": True},
                }
            )
        except Exception as error:
            rows.append(
                {
                    "scenario_key": scenario_key,
                    "status": "error",
                    "elapsed_ms": round((time.perf_counter() - start) * 1000),
                    "error": str(error)[:500],
                    "comparison": {"aligned": False, "needs_review": True},
                }
            )
    summary = _aggregate(rows)
    sweep_id = f"vertex_sweep_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    return {
        "sweep_id": sweep_id,
        "status": "complete" if summary["completed_count"] == summary["scenario_count"] else "review",
        "source": "parkpulse_reactive_path_vertex_eval_sweep",
        "execute": execute,
        "checked_at": _now_iso(),
        "summary": summary,
        "recommendation": _recommendation(summary),
        "scenarios": rows,
    }


def run_vertex_eval_contract_sweep(
    *,
    scenario_keys: list[str] | tuple[str, ...] | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    from evaluator_loop import build_hosted_evaluator_loop
    from park_eval import _score_summary
    from park_scenarios import PARK_SCENARIOS

    rows: list[dict[str, Any]] = []
    for scenario_key in scenario_keys or DEFAULT_SWEEP_SCENARIOS:
        start = time.perf_counter()
        key = str(scenario_key)
        scenario = PARK_SCENARIOS.get(key)
        if not scenario:
            rows.append(
                {
                    "scenario_key": key,
                    "status": "error",
                    "elapsed_ms": round((time.perf_counter() - start) * 1000),
                    "error": "Unknown scenario key.",
                    "comparison": {"aligned": False, "needs_review": True},
                }
            )
            continue
        evals = scenario.get("evals", []) if isinstance(scenario.get("evals"), list) else []
        scores = {item["label"]: item["score"] for item in evals if isinstance(item, dict) and item.get("label")}
        explanations = {item["label"]: item.get("detail", "") for item in evals if isinstance(item, dict) and item.get("label")}
        failure_reasons = [
            {"dimension": item["label"], "score": item["score"], "reason": item.get("detail", "")}
            for item in evals
            if isinstance(item, dict) and int(item.get("score", 0) or 0) < 75
        ]
        response_metrics = {
            "status": "scenario_contract",
            "score": scores.get("Reactive follow-through", scores.get("Responder acknowledgement", 0)),
            "takeRate": float(scores.get("Take rate", 0) or 0) / 100,
            "positiveResponseRate": float(scores.get("Positive response", 0) or 0) / 100,
            "reactiveFollowThroughRate": float(scores.get("Reactive follow-through", 0) or 0) / 100,
        }
        score_summary = _score_summary(evals, response_metrics)
        scorecard = {
            "overall": score_summary["overall"],
            "plan_quality_score": score_summary["plan_quality_score"],
            "outcome_effectiveness_score": score_summary["outcome_effectiveness_score"],
            "score_method": score_summary["method"],
            "status": "passed" if score_summary["overall"] >= 80 and not failure_reasons else "review",
            "response_score": response_metrics["score"],
            "policy_gate_status": "pending_operator_approval" if scenario.get("humanApproval") else "clear",
            "needs_human_approval": bool(scenario.get("humanApproval")),
            "failure_reasons": failure_reasons,
        }
        hosted_eval = build_hosted_evaluator_loop(
            scenario_key=key,
            scorecard=scorecard,
            dimension_scores=scores,
            dimension_explanations=explanations,
            failure_reasons=failure_reasons,
            response_metrics=response_metrics,
            trace_artifact={"trace_id": f"scenario-contract-{key}", "span_id": f"span-{key}", "trace_url": None},
            decision_id=f"scenario-contract-{key}",
            selected_action={"label": scenario.get("title"), "target": key, "action": "scenario_response", "owner": "ParkPulse"},
            governance={
                "gate_status": "pending_operator_approval" if scenario.get("humanApproval") else "clear",
                "allowed": not bool(scenario.get("humanApproval")),
                "findings": [],
            },
            dispatches=[
                {
                    "id": f"dispatch-{key}",
                    "channel": "guest_app",
                    "target_system": "guest-mobile-app",
                    "status": "sent",
                    "payload": {"message": scenario.get("situation")},
                }
            ],
            state_digest={
                "active_scenario": {"key": key, "title": scenario.get("title")},
                "alert_count": 1,
                "alerts": [{"message": scenario.get("situation")}],
                "down_rides": ["Dragon Coaster"] if key == "ride_down" else [],
                "overloaded_rides": [],
                "busiest_zones": [],
            },
        )
        result = {
            "status": "complete",
            "scenario_key": key,
            "decision_id": f"scenario-contract-{key}",
            "outcome_id": None,
            "optimization": {
                "selected_plan": {
                    "selected_action": {"label": scenario.get("title"), "target": key, "action": "scenario_response", "owner": "ParkPulse"}
                }
            },
            "delivery": {"response": response_metrics, "dispatches": hosted_eval.get("payload_preview", {}).get("dispatches", [])},
            "eval": {
                "scorecard": scorecard,
                "dimension_scores": scores,
                "failure_reasons": failure_reasons,
                "hosted_eval": hosted_eval,
            },
        }
        rows.append(summarize_scenario_result(result, elapsed_ms=round((time.perf_counter() - start) * 1000)))
    summary = _aggregate(rows)
    return {
        "sweep_id": f"vertex_sweep_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
        "status": "complete" if summary["completed_count"] == summary["scenario_count"] else "review",
        "source": "parkpulse_vertex_eval_contract_sweep",
        "execute": execute,
        "checked_at": _now_iso(),
        "summary": summary,
        "recommendation": _recommendation(summary),
        "scenarios": rows,
    }
