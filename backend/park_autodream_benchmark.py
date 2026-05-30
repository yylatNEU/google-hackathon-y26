from __future__ import annotations

from copy import deepcopy
from typing import Any

from mongo_memory import get_latest_memory_documents
from park_optimizer import optimize_park_response
from park_twin_engine import simulate_action_plan


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
    rule = _promoted_rule(scenario, promoted_rule_id)
    if not rule:
        return {
            "status": "no_promoted_rule",
            "scenario_key": scenario,
            "promoted_rule_id": promoted_rule_id,
            "message": "Promote an AutoDream rule for this scenario before running the paired benchmark.",
        }

    baseline_context = {"retrieved": {"learnings": []}}
    learned_context = {"retrieved": {"learnings": [rule]}}
    pairs = []
    for index in range(safe_seeds):
        seed = f"autodream_benchmark:{scenario}:{rule.get('_id')}:{index + 1}"
        baseline = _run_once(deepcopy(state), scenario, seed, baseline_context)
        learned = _run_once(deepcopy(state), scenario, seed, learned_context)
        take_lift = round(learned["take_rate"] - baseline["take_rate"], 3)
        queue_lift = baseline["queue_after"] - learned["queue_after"]
        score_lift = round(learned["overall_score"] - baseline["overall_score"], 1)
        learned_wins_seed = (take_lift >= 0.005 or queue_lift > 0) and score_lift >= -2
        pairs.append(
            {
                "seed": seed,
                "baseline": baseline,
                "learned": learned,
                "lift": {
                    "take_rate": take_lift,
                    "moved_guests": learned["moved_guests"] - baseline["moved_guests"],
                    "queue_after": queue_lift,
                    "wait_after": baseline["wait_after"] - learned["wait_after"],
                    "overall_score": score_lift,
                },
                "winner": "learned" if learned_wins_seed else "baseline",
            }
        )

    learned_wins = sum(1 for pair in pairs if pair["winner"] == "learned")
    avg_baseline_take = round(sum(pair["baseline"]["take_rate"] for pair in pairs) / len(pairs), 3)
    avg_learned_take = round(sum(pair["learned"]["take_rate"] for pair in pairs) / len(pairs), 3)
    avg_baseline_score = round(sum(pair["baseline"]["overall_score"] for pair in pairs) / len(pairs), 1)
    avg_learned_score = round(sum(pair["learned"]["overall_score"] for pair in pairs) / len(pairs), 1)
    take_lift = round(avg_learned_take - avg_baseline_take, 3)
    win_rate = round(learned_wins / len(pairs), 3)
    confidence = _confidence(len(pairs), win_rate, take_lift)
    return {
        "status": "complete",
        "mode": "paired_replay_benchmark",
        "source": "park_twin_engine.simulate_action_plan",
        "scenario_key": scenario,
        "promoted_rule": {
            "_id": rule.get("_id"),
            "sourceDreamLearningId": rule.get("sourceDreamLearningId"),
            "outcomeLabel": rule.get("outcomeLabel"),
            "confidence": rule.get("confidence"),
            "collection": rule.get("benchmarkCollection"),
        },
        "sample_size": len(pairs),
        "minimum_sample_size": 5,
        "confidence": confidence,
        "summary": {
            "baseline_take_rate": avg_baseline_take,
            "learned_take_rate": avg_learned_take,
            "take_rate_lift": take_lift,
            "baseline_overall_score": avg_baseline_score,
            "learned_overall_score": avg_learned_score,
            "overall_score_lift": round(avg_learned_score - avg_baseline_score, 1),
            "learned_wins": learned_wins,
            "win_rate": win_rate,
            "queued_guests_avoided": sum(pair["lift"]["queue_after"] for pair in pairs),
            "wait_minutes_avoided": sum(pair["lift"]["wait_after"] for pair in pairs),
        },
        "recommendation": (
            "Benchmark validates this promoted rule for matching scenarios."
            if confidence == "validated"
            else "Benchmark indicates regression risk; keep the rule review-gated or roll it back."
            if confidence == "regression_risk"
            else "Benchmark is directional only; collect more paired seeds before broad generalization."
        ),
        "pairs": pairs,
    }
