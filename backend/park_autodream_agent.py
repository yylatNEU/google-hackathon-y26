from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from bigquery_analytics import build_bigquery_agent_priors, build_dream_analytics_rows, export_analytics_rows
from cache_accuracy_replay import run_cache_accuracy_replay
from mongo_memory import (
    get_autodream_promotion_readiness,
    get_latest_memory_documents,
    get_operational_memory_dashboard,
    get_rollback_watch_documents,
    promote_dream_learning,
    record_autodream_benchmark,
    record_dream_run,
    review_dream_learning,
)
from park_replay_store import replay_collaboration_context


SCENARIOS = ["ride_down", "staff_shortage", "food_spike", "storm_response", "proactive_eventops"]
AUTODREAM_CACHE_REPLAY_ROLES = ["scan_agent", "react_agent", "proact_agent", "maintenance_agent"]
AUTODREAM_RETIREMENT_REASON = "AutoDream has been retired; ParkPulse no longer runs offline dream learning, promotion, or paired replay benchmarks."


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _scenario_from_row(row: dict[str, Any], fallback: str) -> str:
    scenario = row.get("scenarioKey") or row.get("scenario_key")
    if not scenario and isinstance(row.get("stateScenario"), dict):
        scenario = row["stateScenario"].get("key")
    return str(scenario or fallback or "unknown")


def _outcome_signal(row: dict[str, Any]) -> dict[str, Any]:
    response = row.get("responseMetrics", {}) if isinstance(row.get("responseMetrics"), dict) else {}
    scorecard = row.get("scorecard", {}) if isinstance(row.get("scorecard"), dict) else {}
    impact = row.get("stateImpact", {}) if isinstance(row.get("stateImpact"), dict) else {}
    return {
        "take_rate": _safe_float(response.get("takeRate")),
        "follow_through": _safe_float(response.get("reactiveFollowThroughRate")),
        "positive_response": _safe_float(response.get("positiveResponseRate")),
        "overall_score": _safe_int(scorecard.get("overall")),
        "response_score": _safe_int(scorecard.get("response_score")),
        "density_delta": _safe_float(impact.get("density_delta")),
        "congestion_delta": _safe_float(impact.get("congestion_delta")),
        "comfort_delta": _safe_float(impact.get("comfort_delta")),
        "queue_delta": _safe_float(impact.get("queued_guest_delta")),
    }


def _counterfactual_for_signal(scenario_key: str, signal: dict[str, Any], priors: dict[str, Any]) -> dict[str, Any]:
    best = priors.get("best_prior", {}) if isinstance(priors.get("best_prior"), dict) else {}
    weakest = priors.get("weakest_prior", {}) if isinstance(priors.get("weakest_prior"), dict) else {}
    best_cohort = str(best.get("cohort") or "best historical cohort")
    weak_cohort = str(weakest.get("cohort") or "weak historical cohort")
    take_rate = _safe_float(signal.get("take_rate"))
    follow = _safe_float(signal.get("follow_through"))
    score = _safe_int(signal.get("overall_score"))

    if take_rate < 0.4 or follow < 0.35:
        outcome_label = "counterfactual_low_response"
        lesson = f"AutoDream found weak response in {scenario_key}: avoid repeating {weak_cohort} and bias toward {best_cohort}."
        rule = "Increase offer specificity, split guests across low-wait destinations, and pair guest nudges with visible worker/equipment actions."
        adjustment = {
            "promotionStrengthBias": "increase",
            "takeRateMultiplier": 1.12,
            "avoidCohort": weak_cohort,
            "preferCohort": best_cohort,
            "requireWorkerVisibleAction": True,
        }
    elif score >= 82 and (signal.get("density_delta", 0) <= -3 or signal.get("queue_delta", 0) <= -75):
        outcome_label = "counterfactual_success_pattern"
        lesson = f"AutoDream found a repeatable success pattern in {scenario_key}: preserve {best_cohort} when live capacity matches."
        rule = "Keep the successful action mix, but cap overloaded destinations and preserve maintenance/labor gates."
        adjustment = {
            "promotionStrengthBias": "maintain",
            "takeRateMultiplier": 1.05,
            "preferCohort": best_cohort,
            "avoidOverloadedTargets": True,
        }
    else:
        outcome_label = "counterfactual_limited_movement"
        lesson = f"AutoDream found limited state movement in {scenario_key}; the next plan needs earlier and more measurable control actions."
        rule = "Trigger earlier, attach a measurable staff or equipment action, and avoid broad messages without destination-level route mix."
        adjustment = {
            "promotionStrengthBias": "increase",
            "takeRateMultiplier": 1.0,
            "requireEquipmentOrStaffAction": True,
            "avoidCohort": weak_cohort,
        }

    confidence = max(52, min(94, round((score or 65) * 0.55 + max(take_rate, follow, 0.3) * 45)))
    return {
        "scenarioKey": scenario_key,
        "outcomeLabel": outcome_label,
        "lesson": lesson,
        "rule": rule,
        "adjustment": adjustment,
        "confidence": confidence,
        "evidence": {
            **signal,
            "bestPrior": best,
            "weakestPrior": weakest,
        },
        "tags": [scenario_key, outcome_label, "autodream", "offline_only", "counterfactual_learning"],
    }


def _candidate_outcomes(memory_dashboard: dict[str, Any], scenario_key: str, limit: int) -> list[dict[str, Any]]:
    rows = memory_dashboard.get("latest_outcomes", []) if isinstance(memory_dashboard.get("latest_outcomes"), list) else []
    if not rows:
        rows = [
            {
                "_id": f"synthetic_{scenario_key}_weak_take_rate",
                "stateScenario": {"key": scenario_key},
                "responseMetrics": {"takeRate": 0.32, "reactiveFollowThroughRate": 0.27, "positiveResponseRate": 0.41},
                "scorecard": {"overall": 62, "response_score": 54},
                "stateImpact": {"density_delta": -1, "congestion_delta": 2, "comfort_delta": 0, "queued_guest_delta": -20},
                "synthetic": True,
            }
        ]
    return rows[: max(1, min(25, limit))]


def _cache_replay_state(memory_dashboard: dict[str, Any], scenario_key: str) -> dict[str, Any]:
    current_state = memory_dashboard.get("current_state", {}) if isinstance(memory_dashboard.get("current_state"), dict) else {}
    active = (
        current_state.get("guestFlow", {}).get("activeScenario", {})
        if isinstance(current_state.get("guestFlow"), dict) and isinstance(current_state.get("guestFlow", {}).get("activeScenario"), dict)
        else {}
    )
    if current_state and active.get("key") == scenario_key:
        return current_state
    try:
        from park_simulation import ParkSimulation

        simulation = ParkSimulation()
        if scenario_key in {"ride_down", "staff_shortage", "food_spike", "storm_response"}:
            simulation.scenario_key = scenario_key
        return simulation._state()
    except Exception:
        return current_state or {"guestFlow": {"activeScenario": {"key": scenario_key}}}


def _run_cache_replay_audit(
    memory_dashboard: dict[str, Any],
    scenario_key: str,
    *,
    persist: bool,
    roles: list[str] | None = None,
) -> dict[str, Any]:
    state = _cache_replay_state(memory_dashboard, scenario_key)
    selected_roles = roles or AUTODREAM_CACHE_REPLAY_ROLES
    replays: list[dict[str, Any]] = []
    failures: list[str] = []
    for role in selected_roles:
        try:
            replay = run_cache_accuracy_replay(state, scenario_key=scenario_key, agent_role=role, persist=persist)
        except Exception as error:
            replay = {
                "status": "failed",
                "scenario_key": scenario_key,
                "agent_role": role,
                "summary": {"failures": [f"cache_replay_error:{str(error)[:160]}"]},
                "results": [],
            }
        role_failures = (replay.get("summary", {}) if isinstance(replay.get("summary"), dict) else {}).get("failures", [])
        failures.extend(f"{role}:{failure}" for failure in role_failures)
        replays.append(replay)
    passed = [item for item in replays if item.get("status") == "passed"]
    return {
        "status": "passed" if len(passed) == len(replays) else "failed",
        "scenario_key": scenario_key,
        "roles": selected_roles,
        "summary": {
            "roles_checked": len(replays),
            "roles_passed": len(passed),
            "pass_rate": round(len(passed) / len(replays), 3) if replays else 0.0,
            "failures": failures,
        },
        "replays": replays,
    }


def _dream_learning_scenario(dream_learning_id: str, fallback: str = "proactive_eventops") -> str:
    for item in get_latest_memory_documents("dream_learnings", 100):
        if item.get("_id") == dream_learning_id or item.get("dreamLearningId") == dream_learning_id:
            return str(item.get("scenarioKey") or item.get("scenario_key") or fallback)
    return fallback


def _run_promotion_readiness_benchmark(
    dream_learning_id: str,
    scenario_key: str,
    memory_dashboard: dict[str, Any],
) -> dict[str, Any]:
    state = _cache_replay_state(memory_dashboard, scenario_key)
    try:
        from park_autodream_benchmark import run_autodream_benchmark

        benchmark = run_autodream_benchmark(state, scenario_key=scenario_key, promoted_rule_id=dream_learning_id, seeds=5)
    except Exception as error:
        return {
            "status": "error",
            "scenario_key": scenario_key,
            "promoted_rule_id": dream_learning_id,
            "confidence": "regression_risk",
            "summary": {"error": str(error)[:300]},
        }
    if benchmark.get("status") == "complete":
        benchmark["storage"] = record_autodream_benchmark(benchmark)
    return benchmark


def run_autodream(
    scenario_key: str = "proactive_eventops",
    *,
    max_cases: int = 8,
    persist: bool = True,
) -> dict[str, Any]:
    scenario = scenario_key if scenario_key in SCENARIOS else "proactive_eventops"
    return {
        "status": "retired",
        "mode": "retired_autodream",
        "agent_id": "autodream_agent",
        "scenario_key": scenario,
        "max_cases": max(1, min(25, int(max_cases or 1))),
        "persist": bool(persist),
        "offline_only": True,
        "storage": {"status": "disabled", "dream_run_id": None, "dream_learning_ids": []},
        "summary": {
            "retired": True,
            "cases_reviewed": 0,
            "learnings_generated": 0,
            "review_required": False,
            "prior_source": "disabled",
            "cache_replay_status": "disabled",
            "cache_replay_pass_rate": None,
            "reason": AUTODREAM_RETIREMENT_REASON,
        },
        "dream_run": {
            "status": "retired",
            "offlineOnly": True,
            "scenarioKey": scenario,
            "guardrails": ["feature_retired_no_live_or_offline_execution"],
        },
        "dream_learnings": [],
        "cache_replay_audit": {
            "status": "disabled",
            "summary": {
                "roles_checked": 0,
                "roles_passed": 0,
                "pass_rate": None,
                "failures": ["autodream_retired"],
            },
            "replays": [],
        },
        "operator_review": {
            "required": False,
            "promotion_targets": [],
            "note": AUTODREAM_RETIREMENT_REASON,
        },
        "analytics": {"status": "disabled", "row_counts": {"dream_eval_results": 0}},
    }


def autodream_status(limit: int = 8) -> dict[str, Any]:
    safe_limit = max(1, min(25, int(limit or 8)))
    return {
        "agent_id": "autodream_agent",
        "mode": "retired_autodream",
        "offline_only": True,
        "status": "retired",
        "limit": safe_limit,
        "summary": {
            "retired": True,
            "dream_runs": 0,
            "dream_learnings": 0,
            "pending_review": 0,
            "promoted": 0,
            "rejected": 0,
            "archived": 0,
            "needs_more_evidence": 0,
            "impact_improved": 0,
            "impact_neutral": 0,
            "impact_regressed": 0,
            "promotion_ready": 0,
            "promotion_blocked": 0,
            "rollback_watch": 0,
            "reason": AUTODREAM_RETIREMENT_REASON,
        },
        "latest_dream_runs": [],
        "latest_dream_learnings": [],
        "promotion_readiness": [],
        "rollback_watch": {"status": "retired", "count": 0, "documents": []},
        "operator_review": {
            "required_for_promotion": False,
            "allowed_targets": [],
            "allowed_review_statuses": [],
        },
    }


def promote_autodream_learning(
    dream_learning_id: str,
    target: str = "agent_learnings",
    reviewer: str = "operator",
) -> dict[str, Any]:
    return {
        "agent_id": "autodream_agent",
        "mode": "retired_autodream_promotion",
        "offline_source": True,
        "status": "retired",
        "promotion": {
            "status": "retired",
            "dream_learning_id": dream_learning_id,
            "target": target,
            "reviewer": reviewer,
            "reason": AUTODREAM_RETIREMENT_REASON,
            "blockers": ["autodream_retired"],
        },
        "cache_replay_audit": {"status": "disabled", "summary": {"failures": ["autodream_retired"]}},
        "paired_benchmark": {"status": "retired", "summary": {"reason": AUTODREAM_RETIREMENT_REASON}},
        "promotion_readiness": {
            "status": "retired",
            "dream_learning_id": dream_learning_id,
            "promotion_ready": False,
            "blockers": ["autodream_retired"],
        },
        "post_status": autodream_status(8),
    }


def review_autodream_learning(
    dream_learning_id: str,
    review_status: str = "rejected",
    reviewer: str = "operator",
    reason: str = "",
) -> dict[str, Any]:
    return {
        "agent_id": "autodream_agent",
        "mode": "retired_autodream_review",
        "offline_source": True,
        "status": "retired",
        "review": {
            "status": "retired",
            "dream_learning_id": dream_learning_id,
            "review_status": review_status,
            "reviewer": reviewer,
            "reason": reason or AUTODREAM_RETIREMENT_REASON,
        },
        "post_status": autodream_status(8),
    }
