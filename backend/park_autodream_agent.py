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
AUTODREAM_CACHE_REPLAY_ROLES = ["scan_agent", "react_agent", "proact_agent", "maintenance_agent", "autodream_agent"]


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
    memory_dashboard = get_operational_memory_dashboard(f"{scenario} outcome take rate follow through eval failure")
    priors = build_bigquery_agent_priors(scenario, memory_dashboard, allow_live_query=False)
    replay_context = replay_collaboration_context(5)
    cache_replay_audit = _run_cache_replay_audit(memory_dashboard, scenario, persist=persist)
    outcomes = _candidate_outcomes(memory_dashboard, scenario, max_cases)

    learnings: list[dict[str, Any]] = []
    simulated_cases: list[dict[str, Any]] = []
    for row in outcomes:
        if not isinstance(row, dict):
            continue
        row_scenario = _scenario_from_row(row, scenario)
        signal = _outcome_signal(row)
        learning = _counterfactual_for_signal(row_scenario, signal, priors)
        learning["sourceOutcomeId"] = row.get("_id")
        learning["source"] = "autodream_off_hours"
        learnings.append(learning)
        simulated_cases.append(
            {
                "sourceOutcomeId": row.get("_id"),
                "scenarioKey": row_scenario,
                "signal": signal,
                "counterfactualLabel": learning["outcomeLabel"],
                "confidence": learning["confidence"],
            }
        )

    created_at = _utc_now()
    fingerprint = f"{scenario}:{created_at}:{len(learnings)}:{priors.get('source')}"
    dream_run_id = f"dream_run_{hashlib.sha1(fingerprint.encode('utf-8')).hexdigest()[:12]}"
    dream_run = {
        "_id": dream_run_id,
        "dreamRunId": dream_run_id,
        "createdAt": created_at,
        "scenarioKey": scenario,
        "offlineOnly": True,
        "executionWindow": "off_hours",
        "status": "review_required",
        "inputSummary": {
            "outcomeCases": len(outcomes),
            "generatedLearnings": len(learnings),
            "bigQueryPriorSource": priors.get("source"),
            "replayReady": replay_context.get("ready"),
            "cacheReplayStatus": cache_replay_audit.get("status"),
        },
        "simulatedCases": simulated_cases,
        "guardrails": [
            "offline_only_no_live_action_execution",
            "do_not_write_live_park_state",
            "human_review_required_before_playbook_promotion",
            "cache_accuracy_replay_required_before_promotion",
        ],
        "bigqueryPriors": {
            "source": priors.get("source"),
            "queryName": priors.get("query_name"),
            "bestPrior": priors.get("best_prior"),
            "weakestPrior": priors.get("weakest_prior"),
        },
        "cacheReplayAudit": {
            "status": cache_replay_audit.get("status"),
            "summary": cache_replay_audit.get("summary"),
        },
    }
    storage = record_dream_run(dream_run, learnings) if persist else {"status": "preview", "dream_run_id": dream_run_id, "dream_learning_ids": []}
    result = {
        "status": "complete",
        "mode": "offline_autodream",
        "agent_id": "autodream_agent",
        "dream_run_id": dream_run_id,
        "scenario_key": scenario,
        "offline_only": True,
        "storage": storage,
        "summary": {
            "cases_reviewed": len(outcomes),
            "learnings_generated": len(learnings),
            "review_required": True,
            "prior_source": priors.get("source"),
            "cache_replay_status": cache_replay_audit.get("status"),
            "cache_replay_pass_rate": cache_replay_audit.get("summary", {}).get("pass_rate"),
        },
        "dream_run": dream_run,
        "dream_learnings": learnings,
        "cache_replay_audit": cache_replay_audit,
        "operator_review": {
            "required": True,
            "promotion_targets": ["agent_learnings", "playbooks"],
            "note": "AutoDream outputs are not live operational actions. Promote only after operator review and passing cache accuracy replay.",
        },
    }
    analytics_rows = build_dream_analytics_rows(result)
    result["analytics"] = export_analytics_rows(analytics_rows) if persist else {"status": "preview", "row_counts": {key: len(value) for key, value in analytics_rows.items()}}
    return result


def autodream_status(limit: int = 8) -> dict[str, Any]:
    safe_limit = max(1, min(25, int(limit or 8)))
    dream_runs = get_latest_memory_documents("dream_runs", safe_limit)
    dream_learnings = get_latest_memory_documents("dream_learnings", safe_limit * 2)
    readiness_rows = []
    for item in dream_learnings:
        if not item.get("_id"):
            continue
        readiness = get_autodream_promotion_readiness(item["_id"])
        stored_readiness = item.get("promotionReadiness", {}) if isinstance(item.get("promotionReadiness"), dict) else {}
        rollback_active = bool((readiness.get("rollback_watch", {}) if isinstance(readiness.get("rollback_watch"), dict) else {}).get("active"))
        if stored_readiness.get("promotion_ready") and not readiness.get("regression_risk") and not rollback_active:
            readiness = {
                **readiness,
                **stored_readiness,
                "status": "ready",
                "promotion_ready": True,
                "blockers": [],
            }
        readiness_rows.append(readiness)
    rollback_watch = get_rollback_watch_documents(limit=safe_limit * 3)
    readiness_by_id = {row.get("dream_learning_id"): row for row in readiness_rows}
    dream_learnings = [
        {**item, "promotionReadiness": readiness_by_id.get(item.get("_id"), {})}
        for item in dream_learnings
    ]
    pending = [item for item in dream_learnings if item.get("reviewStatus") == "pending_operator_review"]
    promoted = [item for item in dream_learnings if item.get("reviewStatus") == "promoted" or item.get("promoted")]
    rejected = [item for item in dream_learnings if item.get("reviewStatus") == "rejected"]
    archived = [item for item in dream_learnings if item.get("reviewStatus") == "archived"]
    needs_more_evidence = [item for item in dream_learnings if item.get("reviewStatus") == "needs_more_evidence"]
    improved = [item for item in dream_learnings if item.get("promotionMeasurementStatus") == "improved" or (item.get("promotionImpact", {}) if isinstance(item.get("promotionImpact"), dict) else {}).get("status") == "improved"]
    neutral = [item for item in dream_learnings if item.get("promotionMeasurementStatus") == "neutral" or (item.get("promotionImpact", {}) if isinstance(item.get("promotionImpact"), dict) else {}).get("status") == "neutral"]
    regressed = [item for item in dream_learnings if item.get("promotionMeasurementStatus") == "regressed" or (item.get("promotionImpact", {}) if isinstance(item.get("promotionImpact"), dict) else {}).get("status") == "regressed"]
    return {
        "agent_id": "autodream_agent",
        "mode": "offline_learning",
        "offline_only": True,
        "status": "ready",
        "summary": {
            "dream_runs": len(dream_runs),
            "dream_learnings": len(dream_learnings),
            "pending_review": len(pending),
            "promoted": len(promoted),
            "rejected": len(rejected),
            "archived": len(archived),
            "needs_more_evidence": len(needs_more_evidence),
            "impact_improved": len(improved),
            "impact_neutral": len(neutral),
            "impact_regressed": len(regressed),
            "promotion_ready": sum(1 for item in readiness_rows if item.get("promotion_ready")),
            "promotion_blocked": sum(1 for item in readiness_rows if not item.get("promotion_ready")),
            "rollback_watch": rollback_watch.get("count", 0),
        },
        "latest_dream_runs": dream_runs,
        "latest_dream_learnings": dream_learnings,
        "promotion_readiness": readiness_rows,
        "rollback_watch": rollback_watch,
        "operator_review": {
            "required_for_promotion": True,
            "allowed_targets": ["agent_learnings", "playbooks"],
            "allowed_review_statuses": ["rejected", "archived", "needs_more_evidence"],
        },
    }


def promote_autodream_learning(
    dream_learning_id: str,
    target: str = "agent_learnings",
    reviewer: str = "operator",
) -> dict[str, Any]:
    scenario = _dream_learning_scenario(dream_learning_id)
    memory_dashboard = get_operational_memory_dashboard(f"{scenario} cache promotion safety")
    cache_replay_audit = _run_cache_replay_audit(memory_dashboard, scenario, persist=True, roles=["react_agent", "proact_agent", "autodream_agent"])
    benchmark = _run_promotion_readiness_benchmark(dream_learning_id, scenario, memory_dashboard)
    readiness = get_autodream_promotion_readiness(dream_learning_id, cache_replay_audit, benchmark)
    if not readiness.get("promotion_ready"):
        return {
            "agent_id": "autodream_agent",
            "mode": "operator_review_promotion",
            "offline_source": True,
            "status": "blocked_promotion_readiness",
            "promotion": {
                "status": "blocked_promotion_readiness",
                "dream_learning_id": dream_learning_id,
                "target": target,
                "reviewer": reviewer,
                "reason": "Promotion readiness requires cache replay, paired benchmark, and no regression risk.",
                "blockers": readiness.get("blockers", []),
            },
            "cache_replay_audit": cache_replay_audit,
            "paired_benchmark": benchmark,
            "promotion_readiness": readiness,
            "post_status": autodream_status(8),
        }
    promotion = promote_dream_learning(dream_learning_id, target, reviewer, readiness)
    return {
        "agent_id": "autodream_agent",
        "mode": "operator_review_promotion",
        "offline_source": True,
        "promotion": promotion,
        "status": promotion.get("status", "unknown"),
        "cache_replay_audit": cache_replay_audit,
        "paired_benchmark": benchmark,
        "promotion_readiness": readiness,
        "post_status": autodream_status(8),
    }


def review_autodream_learning(
    dream_learning_id: str,
    review_status: str = "rejected",
    reviewer: str = "operator",
    reason: str = "",
) -> dict[str, Any]:
    review = review_dream_learning(dream_learning_id, review_status, reviewer, reason)
    return {
        "agent_id": "autodream_agent",
        "mode": "operator_review",
        "offline_source": True,
        "review": review,
        "status": review.get("status", "unknown"),
        "post_status": autodream_status(8),
    }
