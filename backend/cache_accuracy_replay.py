from __future__ import annotations

import time
from copy import deepcopy
from typing import Any

import mongo_memory
from mongo_memory import get_operational_intelligence, record_cache_accuracy_replay, retrieve_operational_context, sync_park_state


def _number(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _scenario_key(state: dict[str, Any]) -> str:
    flow = state.get("guestFlow", {}) if isinstance(state.get("guestFlow"), dict) else {}
    scenario = flow.get("activeScenario", {}) if isinstance(flow.get("activeScenario"), dict) else {}
    return str(scenario.get("key") or "ride_down")


def _state_for_scenario(state: dict[str, Any], scenario_key: str) -> dict[str, Any]:
    replay_state = deepcopy(state)
    flow = replay_state.get("guestFlow", {}) if isinstance(replay_state.get("guestFlow"), dict) else {}
    active = flow.get("activeScenario", {}) if isinstance(flow.get("activeScenario"), dict) else {}
    active["key"] = scenario_key
    active.setdefault("name", scenario_key.replace("_", " ").title())
    active.setdefault("description", "Cache accuracy replay scenario.")
    flow["activeScenario"] = active
    replay_state["guestFlow"] = flow
    park_ops = replay_state.get("parkOps", {}) if isinstance(replay_state.get("parkOps"), dict) else {}
    park_ops["mode"] = scenario_key
    replay_state["parkOps"] = park_ops
    return replay_state


def _cache_contract(context: dict[str, Any]) -> dict[str, Any]:
    accuracy = context.get("cache_accuracy", {}) if isinstance(context.get("cache_accuracy"), dict) else {}
    gate = context.get("freshness_gate", {}) if isinstance(context.get("freshness_gate"), dict) else {}
    semantic = accuracy.get("semanticDrift") or gate.get("semanticDrift") or {}
    return {
        "trust_level": accuracy.get("trustLevel") or gate.get("trustLevel", "unknown"),
        "cache_trust_penalty": _number(accuracy.get("cacheTrustPenalty", gate.get("cacheTrustPenalty", 0))),
        "must_revalidate": bool(accuracy.get("mustRevalidate", gate.get("mustRevalidate", False))),
        "semantic_drift": semantic if isinstance(semantic, dict) else {},
        "instruction": accuracy.get("instruction") or gate.get("agentInstruction", ""),
    }


def _adjusted_confidence(raw_confidence: float, context: dict[str, Any]) -> tuple[int, int, dict[str, Any]]:
    contract = _cache_contract(context)
    original = round(max(0, min(100, raw_confidence)))
    adjusted = round(max(0, min(100, original * (1 - max(0, min(0.75, contract["cache_trust_penalty"]))))))
    return original, adjusted, contract


def _cache_policy_gate(contract: dict[str, Any]) -> dict[str, Any]:
    drift = contract.get("semantic_drift", {}) if isinstance(contract.get("semantic_drift"), dict) else {}
    drift_level = drift.get("level")
    findings = []
    if contract.get("must_revalidate"):
        findings.append(
            f"Cache accuracy contract requires revalidation before execution; drift={drift_level}, "
            f"trust_penalty={contract.get('cache_trust_penalty', 0)}."
        )
    if drift_level == "dangerous":
        return {"gate_status": "blocked", "allowed": False, "findings": findings or ["Dangerous cache drift blocks execution."]}
    if contract.get("must_revalidate"):
        return {"gate_status": "review", "allowed": False, "findings": findings}
    return {"gate_status": "clear", "allowed": True, "findings": findings}


def _set_role_cache_window(scenario_key: str, agent_role: str, *, fresh_until: str, usable_until: str) -> None:
    cache_id = f"role_context_{scenario_key}_{agent_role}"
    collection = mongo_memory._memory._collection("role_context_cache")
    update = {
        "freshUntil": fresh_until,
        "usableUntil": usable_until,
        "refreshState": "idle",
        "refreshLeaseUntil": None,
    }
    if collection is not None:
        collection.update_one({"_id": cache_id}, {"$set": update}, upsert=False)
        return
    for row in mongo_memory._memory._fallback.get("role_context_cache", []):
        if row.get("_id") == cache_id:
            row.update(update)
            return


def _dangerous_state(state: dict[str, Any]) -> dict[str, Any]:
    mutated = deepcopy(state)
    mutated["alerts"] = [
        {
            "title": "Lightning evacuation",
            "severity": "critical",
            "detail": "Severe storm cell entered the park perimeter.",
        }
    ]
    weather = mutated.get("weather", {}) if isinstance(mutated.get("weather"), dict) else {}
    weather["condition"] = "severe storm"
    mutated["weather"] = weather
    return mutated


def _evaluate_mode(
    mode: str,
    state: dict[str, Any],
    *,
    scenario_key: str,
    agent_role: str,
    query: str,
) -> dict[str, Any]:
    started = time.monotonic()
    context_state = _dangerous_state(state) if mode == "dangerous_drift_blocked" else deepcopy(state)
    if mode == "fresh_retrieval":
        context = retrieve_operational_context(query, context_state, limit=4, agent_role=agent_role, cache_policy="fresh_retrieval")
    else:
        context = retrieve_operational_context(query, context_state, limit=4, agent_role=agent_role)
    retrieval_latency_ms = round((time.monotonic() - started) * 1000, 2)
    from park_optimizer import optimize_park_response

    optimization = optimize_park_response(context_state, scenario_key, context=context)
    selected_plan = optimization.get("selected_plan", {}) if isinstance(optimization.get("selected_plan"), dict) else {}
    selected_action = selected_plan.get("selected_action", {}) if isinstance(selected_plan.get("selected_action"), dict) else {}
    raw_confidence = _number((selected_plan.get("scorecard", {}) if isinstance(selected_plan.get("scorecard"), dict) else {}).get("overall"), 75)
    original_confidence, adjusted_confidence, contract = _adjusted_confidence(raw_confidence, context)
    gate = _cache_policy_gate(contract)
    gate_status = gate.get("gate_status")
    safety_score = 100 if gate_status == "clear" else 75 if gate_status == "review" else 35
    return {
        "mode": mode,
        "retrievalMethod": context.get("retrieved", {}).get("method"),
        "retrievalLatencyMs": retrieval_latency_ms,
        "trustLevel": contract.get("trust_level"),
        "semanticDrift": contract.get("semantic_drift", {}),
        "mustRevalidate": contract.get("must_revalidate"),
        "cacheTrustPenalty": contract.get("cache_trust_penalty"),
        "confidence": {
            "original": original_confidence,
            "adjusted": adjusted_confidence,
            "delta": adjusted_confidence - original_confidence,
        },
        "selectedAction": selected_action,
        "selectedPlanId": selected_plan.get("id"),
        "selectedPlanName": selected_plan.get("name"),
        "policyGate": {
            "status": gate_status,
            "allowed": gate.get("allowed"),
            "findings": gate.get("findings", [])[:5],
        },
        "scores": {
            "optimizerOverall": raw_confidence,
            "cacheAdjustedConfidence": adjusted_confidence,
            "safety": safety_score,
        },
    }


def _action_key(row: dict[str, Any]) -> str:
    action = row.get("selectedAction", {}) if isinstance(row.get("selectedAction"), dict) else {}
    return f"{action.get('target')}:{action.get('action')}:{action.get('label')}"


def run_cache_accuracy_replay(
    state: dict[str, Any],
    *,
    scenario_key: str | None = None,
    agent_role: str = "react_agent",
    persist: bool = True,
) -> dict[str, Any]:
    scenario = scenario_key or _scenario_key(state)
    role = agent_role or "react_agent"
    state = _state_for_scenario(state, scenario)
    query = f"{scenario} cache accuracy replay active incident ride queue staffing weather safety"
    sync_park_state(state)
    get_operational_intelligence(query, scenario, role)
    modes = ["fresh_retrieval", "fresh_role_cache", "stale_usable_cache", "dangerous_drift_blocked"]
    results: list[dict[str, Any]] = []
    for mode in modes:
        if mode == "stale_usable_cache":
            _set_role_cache_window(scenario, role, fresh_until="2000-01-01T00:00:00Z", usable_until="2999-01-01T00:00:00Z")
        elif mode == "dangerous_drift_blocked":
            _set_role_cache_window(scenario, role, fresh_until="2000-01-01T00:00:00Z", usable_until="2999-01-01T00:00:00Z")
        else:
            get_operational_intelligence(query, scenario, role)
        results.append(_evaluate_mode(mode, state, scenario_key=scenario, agent_role=role, query=query))

    baseline_action = _action_key(results[0])
    for row in results:
        row["selectedActionStableVsFresh"] = _action_key(row) == baseline_action

    failures = []
    dangerous = next((row for row in results if row["mode"] == "dangerous_drift_blocked"), {})
    stale = next((row for row in results if row["mode"] == "stale_usable_cache"), {})
    if dangerous.get("policyGate", {}).get("allowed"):
        failures.append("dangerous_drift_allowed_execution")
    if not dangerous.get("mustRevalidate"):
        failures.append("dangerous_drift_missing_revalidation")
    if stale.get("retrievalMethod") != "role_context_cache_stale_usable":
        failures.append("stale_usable_cache_not_served")
    summary = {
        "mode_count": len(results),
        "stable_action_modes": sum(1 for row in results if row.get("selectedActionStableVsFresh")),
        "dangerous_blocked": dangerous.get("policyGate", {}).get("status") == "blocked",
        "stale_usable_served": stale.get("retrievalMethod") == "role_context_cache_stale_usable",
        "avg_latency_ms": round(sum(_number(row.get("retrievalLatencyMs")) for row in results) / max(1, len(results)), 2),
        "avg_adjusted_confidence": round(sum(_number(row.get("confidence", {}).get("adjusted")) for row in results) / max(1, len(results)), 1),
        "failures": failures,
    }
    replay = {
        "status": "passed" if not failures else "failed",
        "scenario_key": scenario,
        "agent_role": role,
        "query": query,
        "summary": summary,
        "results": results,
    }
    if persist:
        replay["storage"] = record_cache_accuracy_replay(replay)
    return replay
