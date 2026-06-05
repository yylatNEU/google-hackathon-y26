from __future__ import annotations

from copy import deepcopy
from typing import Any

from mongo_memory import get_latest_memory_documents
from park_optimizer import optimize_park_response
from park_twin_engine import simulate_action_plan

AUTODREAM_RETIREMENT_REASON = "AutoDream has been retired; paired replay benchmarks are disabled."


def _number(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _active_scenario(state: dict[str, Any]) -> str:
    flow = state.get("guestFlow", {}) if isinstance(state.get("guestFlow"), dict) else {}
    scenario = flow.get("activeScenario", {}) if isinstance(flow.get("activeScenario"), dict) else {}
    return str(scenario.get("key") or "ride_down")


def _primary_ride(state: dict[str, Any]) -> dict[str, Any]:
    flow = state.get("guestFlow", {}) if isinstance(state.get("guestFlow"), dict) else {}
    rides = flow.get("rides", []) if isinstance(flow.get("rides"), list) else []
    if not rides:
        return {"id": "dragonCoaster", "queueGuests": 700, "waitMins": 60}
    return max(
        rides,
        key=lambda ride: (
            100 if ride.get("status") == "down" else 30 if ride.get("status") == "constrained" else 0,
            int(ride.get("downtimeRisk", 0) or 0),
            int(ride.get("queueGuests", 0) or 0),
            int(ride.get("waitMins", 0) or 0),
        ),
    )


def _find_ride(state: dict[str, Any], ride_id: str) -> dict[str, Any]:
    flow = state.get("guestFlow", {}) if isinstance(state.get("guestFlow"), dict) else {}
    rides = flow.get("rides", []) if isinstance(flow.get("rides"), list) else []
    return next((ride for ride in rides if str(ride.get("id")) == ride_id), {})


def _promoted_rule(scenario_key: str, promoted_rule_id: str | None = None) -> dict[str, Any] | None:
    candidates = []
    if promoted_rule_id:
        for row in get_latest_memory_documents("dream_learnings", 50):
            if not isinstance(row, dict) or row.get("_id") != promoted_rule_id:
                continue
            if str(row.get("scenarioKey", "")) == scenario_key:
                candidates.append(
                    {
                        **row,
                        "sourceDreamLearningId": row.get("_id"),
                        "benchmarkCollection": "dream_learnings",
                    }
                )
    for collection_name, scenario_field in (("agent_learnings", "scenarioKey"), ("playbooks", "incidentType")):
        for row in get_latest_memory_documents(collection_name, 50):
            if not isinstance(row, dict):
                continue
            if promoted_rule_id and row.get("_id") != promoted_rule_id:
                continue
            if row.get("sourceDreamLearningId") and str(row.get(scenario_field, "")) == scenario_key:
                candidates.append({**row, "benchmarkCollection": collection_name})
    if promoted_rule_id:
        return candidates[0] if candidates else None
    measured = [
        item
        for item in candidates
        if (item.get("promotionImpact", {}) if isinstance(item.get("promotionImpact"), dict) else {}).get("status")
        in {"improved", "neutral", "regressed", "pending_measurement"}
    ]
    return (measured or candidates)[0] if candidates else None


def _plan_for_simulation(plan: dict[str, Any]) -> dict[str, Any]:
    simulated = deepcopy(plan)
    scorecard = simulated.get("scorecard", {}) if isinstance(simulated.get("scorecard"), dict) else {}
    action_mix = simulated.get("action_mix", {}) if isinstance(simulated.get("action_mix"), dict) else {}
    reroute = action_mix.get("guest_reroute", {}) if isinstance(action_mix.get("guest_reroute"), dict) else {}
    take_rate = _number(scorecard.get("take_rate_likelihood")) / 100
    if reroute and take_rate > 0:
        reroute["expectedTakeRate"] = round(max(0.1, min(0.68, take_rate)), 3)
        reroute["expectedFollowThroughRate"] = round(max(0.08, min(0.64, take_rate - 0.04)), 3)
    action_mix["guest_reroute"] = reroute
    simulated["action_mix"] = action_mix
    simulated["selected_action"] = {
        "target": "ride",
        "action": "reroute",
        "label": simulated.get("selected_action", {}).get("label") or simulated.get("name", "benchmark plan"),
    }
    return simulated


def _run_once(
    state: dict[str, Any],
    scenario_key: str,
    seed: str,
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    optimization = optimize_park_response(state, scenario_key, context=context)
    selected = _plan_for_simulation(optimization.get("selected_plan", {}))
    before_ride = _primary_ride(state)
    before_queue = int(before_ride.get("queueGuests", 0) or 0)
    before_wait = int(before_ride.get("waitMins", 0) or 0)
    result = simulate_action_plan(state, selected, horizon_minutes=30, seed=seed)
    projected = result.get("projected_state", {}) if isinstance(result.get("projected_state"), dict) else {}
    after_ride = _find_ride(projected, str(before_ride.get("id"))) or _primary_ride(projected)
    after_queue = int(after_ride.get("queueGuests", 0) or 0)
    after_wait = int(after_ride.get("waitMins", 0) or 0)
    moved = int(result.get("projected_impact", {}).get("movedGuests", 0) or max(0, before_queue - after_queue))
    take_rate = round(moved / max(1, before_queue), 3)
    return {
        "seed": seed,
        "plan_id": selected.get("id"),
        "plan_name": selected.get("name"),
        "overall_score": _number(result.get("scorecard", {}).get("overall")),
        "plan_score": _number(selected.get("scorecard", {}).get("overall")),
        "take_rate": take_rate,
        "moved_guests": moved,
        "queue_before": before_queue,
        "queue_after": after_queue,
        "queue_delta": after_queue - before_queue,
        "wait_before": before_wait,
        "wait_after": after_wait,
        "wait_delta": after_wait - before_wait,
        "state_source": result.get("source"),
    }


def _confidence(sample_size: int, win_rate: float, take_rate_lift: float) -> str:
    if sample_size <= 0:
        return "no_signal"
    if win_rate < 0.45 or take_rate_lift < 0:
        return "regression_risk"
    if sample_size < 3:
        return "early_signal"
    if sample_size < 5:
        return "directional"
    if win_rate >= 0.7 and take_rate_lift >= 0.05:
        return "validated"
    if win_rate >= 0.7 and take_rate_lift > 0:
        return "directional"
    return "mixed"


def run_autodream_benchmark(
    state: dict[str, Any],
    *,
    scenario_key: str | None = None,
    promoted_rule_id: str | None = None,
    seeds: int = 5,
) -> dict[str, Any]:
    scenario = scenario_key or _active_scenario(state)
    safe_seeds = max(1, min(20, int(seeds or 5)))
    return {
        "status": "retired",
        "mode": "retired_autodream_benchmark",
        "scenario_key": scenario,
        "promoted_rule_id": promoted_rule_id,
        "sample_size": 0,
        "requested_seeds": safe_seeds,
        "confidence": "disabled",
        "summary": {
            "retired": True,
            "reason": AUTODREAM_RETIREMENT_REASON,
            "win_rate": 0,
            "take_rate_lift": 0,
        },
        "pairs": [],
        "recommendation": AUTODREAM_RETIREMENT_REASON,
    }
