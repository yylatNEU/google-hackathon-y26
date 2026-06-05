from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from park_twin_engine import noisy_observation, score_outcome, simulate_action_plan, state_digest, transition_state
from trace_helpers import finish_span, traced_payload, traced_span


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bounded(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _flow(state: dict[str, Any]) -> dict[str, Any]:
    flow = state.get("guestFlow", {})
    return flow if isinstance(flow, dict) else {}


def _zones(state: dict[str, Any]) -> list[dict[str, Any]]:
    zones = _flow(state).get("zones", [])
    return zones if isinstance(zones, list) else []


def _rides(state: dict[str, Any]) -> list[dict[str, Any]]:
    rides = _flow(state).get("rides", [])
    return rides if isinstance(rides, list) else []


def _scenario_key(state: dict[str, Any], fallback: str = "ride_down") -> str:
    scenario = _flow(state).get("activeScenario", {})
    return str((scenario if isinstance(scenario, dict) else {}).get("key") or fallback)


def _find_by_id(rows: list[dict[str, Any]], item_id: str | None) -> dict[str, Any]:
    if item_id:
        for item in rows:
            if str(item.get("id")) == str(item_id):
                return item
    return {}


def _primary_ride(state: dict[str, Any]) -> dict[str, Any]:
    rides = _rides(state)
    if not rides:
        return {"id": "dragonCoaster", "name": "Dragon Coaster", "zone": "coasterPlaza", "status": "down", "queueGuests": 700, "waitMins": 60}
    return max(
        rides,
        key=lambda ride: (
            100 if ride.get("status") == "down" else 30 if ride.get("status") == "constrained" else 0,
            _as_int(ride.get("downtimeRisk")),
            _as_int(ride.get("queueGuests")),
            _as_int(ride.get("waitMins")),
        ),
    )


def _zone_for_ride(state: dict[str, Any], ride: dict[str, Any]) -> dict[str, Any]:
    return _find_by_id(_zones(state), str(ride.get("zone"))) or {"id": ride.get("zone"), "name": ride.get("zoneName", "Affected zone")}


def list_digital_twin_tools() -> dict[str, Any]:
    tools = [
        _tool_spec("get_park_state", "Read current digital-twin summary.", "read"),
        _tool_spec("get_zone_density", "Read zone density, comfort, and wait state.", "read"),
        _tool_spec("get_ride_status", "Read ride queue, status, capacity, and maintenance pressure.", "read"),
        _tool_spec("get_staff_constraints", "Read callouts, available staff, and protected human constraints.", "read"),
        _tool_spec("get_food_capacity", "Read food backlog, ETA, inventory, and available alternate capacity.", "read"),
        _tool_spec("simulate_action", "Project an action plan against the digital twin before dispatch.", "simulate"),
        _tool_spec("tick_simulation", "Advance the stress twin without taking a new action.", "simulate"),
        _tool_spec("compare_action_candidates", "Rank candidate plans and expose rejection reasons.", "reason"),
        _tool_spec("validate_policy", "Gate an action against safety, labor, privacy, and automation boundaries.", "gate"),
        _tool_spec("get_noisy_observation", "Read partial/stale operational signals instead of perfect truth.", "read"),
        _tool_spec("retrieve_similar_incidents", "Return memory IDs and lessons used by the agent.", "memory"),
        _tool_spec("score_decision_quality", "Score groundedness, safety, capacity, actionability, and authority split.", "eval"),
        _tool_spec("score_outcome", "Grade before/after twin state movement after an action.", "eval"),
        _tool_spec("dispatch_guest_message", "Prepare bounded guest-app payload; no PII or compensation promise.", "act"),
        _tool_spec("dispatch_worker_task", "Prepare worker task with role, location, and time-boxed scope.", "act"),
        _tool_spec("dispatch_equipment_command", "Prepare bounded equipment command with comfort/safety limits.", "act"),
        _tool_spec("write_decision_memory", "Persist decision, evidence, and outcome hooks for future runs.", "memory"),
    ]
    return {
        "server": "parkpulse.digital_twin",
        "style": "mcp_tool_registry",
        "principle": "ML predicts, agents choose with tools, policy gates, humans retain authority, action bus executes bounded commands.",
        "tools": tools,
    }


def _tool_spec(name: str, description: str, capability: str) -> dict[str, Any]:
    return {
        "name": name,
        "capability": capability,
        "description": description,
        "permission": "read_only" if capability in {"read", "simulate", "reason", "gate", "eval", "memory"} else "bounded_action",
    }


def run_digital_twin_tool(
    name: str,
    state: dict[str, Any],
    arguments: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    args = arguments or {}
    trace_context = context or {}
    agent_id = _agent_for_tool(name, args, trace_context)
    capability = _tool_capability(name)
    with traced_span(
        f"parkpulse.digital_twin.tool.{name}",
        span_kind="TOOL",
        attributes={
            "tool.name": name,
            "tool.server": "parkpulse.digital_twin",
            "tool.capability": capability,
            "parkpulse.scenario": _scenario_key(state),
            "parkpulse.tool.permission": "bounded_action" if capability == "act" else "read_or_eval",
        },
        input_value={"tool": name, "arguments": args},
    ) as span:
        output = _run_with_agent_boundary(agent_id, name, state, args, trace_context)
        status = str(output.get("status") or "ok") if isinstance(output, dict) else "ok"
        finish_span(
            span,
            output,
            {
                "tool.status": status,
                "parkpulse.tool.status": status,
            },
        )
        return {
            "tool": name,
            "server": "parkpulse.digital_twin",
            "capability": capability,
            "span_kind": "TOOL",
            "called_at": _utc_now(),
            "arguments": deepcopy(args),
            "agent_id": agent_id,
            "agentBoundary": output.get("agentBoundary") if isinstance(output, dict) else None,
            "output": output,
            "trace": traced_payload(),
        }


def _run_with_agent_boundary(agent_id: str, name: str, state: dict[str, Any], args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    from park_multi_agent import run_agent_tool

    return run_agent_tool(agent_id, name, {**context, **args, "scenario_key": _scenario_key(state)}, lambda: _execute_digital_twin_tool(name, state, args, context))


def _execute_digital_twin_tool(name: str, state: dict[str, Any], args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    if name == "get_park_state":
        return _get_park_state(state)
    if name == "get_zone_density":
        return _get_zone_density(state, str(args.get("zone_id") or ""))
    if name == "get_ride_status":
        return _get_ride_status(state, str(args.get("ride_id") or ""))
    if name == "get_staff_constraints":
        return _get_staff_constraints(state, str(args.get("zone_id") or ""))
    if name == "get_food_capacity":
        return _get_food_capacity(state, str(args.get("location_id") or ""))
    if name == "simulate_action":
        return _simulate_action(state, args.get("action_plan") if isinstance(args.get("action_plan"), dict) else args)
    if name == "tick_simulation":
        return _tick_simulation(state, _as_int(args.get("minutes"), 5))
    if name == "compare_action_candidates":
        candidates = args.get("candidates", [])
        return _compare_action_candidates(candidates if isinstance(candidates, list) else [])
    if name == "validate_policy":
        return _validate_policy(state, args.get("action") if isinstance(args.get("action"), dict) else args)
    if name == "get_noisy_observation":
        return noisy_observation(state, seed=str(args.get("seed") or "digital-twin-tool"))
    if name == "retrieve_similar_incidents":
        return _retrieve_similar_incidents(context)
    if name == "score_decision_quality":
        return _score_decision_quality(state, args.get("decision") if isinstance(args.get("decision"), dict) else args)
    if name == "score_outcome":
        return _score_outcome_tool(state, args)
    if name in {"dispatch_guest_message", "dispatch_worker_task", "dispatch_equipment_command"}:
        return _prepare_dispatch(name, args)
    if name == "write_decision_memory":
        return _write_decision_memory(args)
    return {"status": "error", "message": f"Unknown digital twin tool: {name}"}


def _agent_for_tool(name: str, args: dict[str, Any], context: dict[str, Any]) -> str:
    explicit = args.get("agent_id") or args.get("agentId") or context.get("agent_id") or context.get("agentId")
    if explicit:
        return str(explicit)
    return {
        "get_park_state": "park_understanding_agent",
        "retrieve_similar_incidents": "park_understanding_agent",
        "get_noisy_observation": "park_understanding_agent",
        "get_zone_density": "guest_flow_agent",
        "get_ride_status": "ride_ops_agent",
        "get_staff_constraints": "staffing_agent",
        "get_food_capacity": "food_demand_agent",
        "simulate_action": "ride_ops_agent",
        "tick_simulation": "planning_agent",
        "compare_action_candidates": "decision_bridge_agent",
        "validate_policy": "safety_policy_agent",
        "score_decision_quality": "gcp_eval_judge_agent",
        "score_outcome": "finance_agent",
        "dispatch_guest_message": "guest_flow_agent",
        "dispatch_worker_task": "staffing_agent",
        "dispatch_equipment_command": "facilities_energy_agent",
        "write_decision_memory": "decision_bridge_agent",
    }.get(name, "decision_bridge_agent")


def build_digital_twin_tool_trace(
    state: dict[str, Any],
    scenario_key: str | None = None,
    context: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
    optimization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_ride = _primary_ride(state)
    selected_zone = _zone_for_ride(state, selected_ride)
    selected_plan = (optimization or {}).get("selected_plan", {}) if isinstance(optimization, dict) else {}
    selected_action = (
        selected_plan.get("selected_action")
        or (plan or {}).get("selected_action")
        or {"target": "ride", "action": "reroute", "label": "Policy-checked route response"}
    )
    candidates = (optimization or {}).get("candidates", []) if isinstance(optimization, dict) else []
    trace_context = context or {}
    active_scenario = scenario_key or _scenario_key(state)

    with traced_span(
        "parkpulse.digital_twin.tool_trace",
        span_kind="CHAIN",
        attributes={
            "parkpulse.scenario": active_scenario,
            "parkpulse.selected_action": str(selected_action.get("label") or selected_action.get("action") or ""),
        },
        input_value={
            "scenario_key": active_scenario,
            "selected_ride": selected_ride.get("id"),
            "selected_zone": selected_zone.get("id"),
            "candidate_count": len(candidates),
        },
    ) as span:
        calls = [
            run_digital_twin_tool("get_park_state", state, {"scenario_key": active_scenario}, trace_context),
            run_digital_twin_tool("get_ride_status", state, {"ride_id": selected_ride.get("id")}, trace_context),
            run_digital_twin_tool("get_zone_density", state, {"zone_id": selected_zone.get("id")}, trace_context),
            run_digital_twin_tool("get_staff_constraints", state, {"zone_id": selected_zone.get("id")}, trace_context),
            run_digital_twin_tool("get_food_capacity", state, {"location_id": "foodCourt1"}, trace_context),
            run_digital_twin_tool("retrieve_similar_incidents", state, {"query": active_scenario}, trace_context),
            run_digital_twin_tool("get_noisy_observation", state, {"seed": active_scenario}, trace_context),
        ]
        if candidates:
            calls.append(run_digital_twin_tool("compare_action_candidates", state, {"candidates": candidates}, trace_context))
        calls.extend(
            [
                run_digital_twin_tool("simulate_action", state, {"action_plan": selected_plan or {"selected_action": selected_action}}, trace_context),
                run_digital_twin_tool("validate_policy", state, {"action": selected_action}, trace_context),
                run_digital_twin_tool("score_decision_quality", state, {"decision": selected_plan or {"selected_action": selected_action}}, trace_context),
            ]
        )

        validation = calls[-2]["output"]
        score = calls[-1]["output"]
        result = {
            "mode": "mcp_style_digital_twin_tool_trace",
            "server": "parkpulse.digital_twin",
            "span_kind": "CHAIN_WITH_TOOL_CHILDREN",
            "tool_count": len(calls),
            "trace": traced_payload(),
            "tool_calls": calls,
            "summary": {
                "scenario_key": active_scenario,
                "selected_ride": selected_ride.get("name"),
                "selected_zone": selected_zone.get("name"),
                "policy_gate": validation.get("gate_status"),
                "quality_score": score.get("overall"),
                "boundary": "ML forecast informs the agent; digital twin tools simulate and compare; policy gates and humans bound execution.",
            },
            "agent_boundary": {
                "ml_prediction": "Forecasts density, wait, take-rate, and likely pressure movement.",
                "agent_action": "Calls tools, compares candidates, chooses a policy-checked action.",
                "human_authority": "Approves safety-adjacent, labor-exception, compensation, and sensitive guest-care actions.",
                "automation": "Dispatches only bounded guest, worker, and equipment payloads after gate checks.",
            },
        }
        finish_span(
            span,
            {
                "tool_count": len(calls),
                "policy_gate": validation.get("gate_status"),
                "quality_score": score.get("overall"),
            },
            {
                "parkpulse.digital_twin.tool_count": len(calls),
                "parkpulse.digital_twin.policy_gate": validation.get("gate_status"),
                "parkpulse.digital_twin.quality_score": score.get("overall"),
            },
        )
        return result


def _tool_capability(name: str) -> str:
    if name.startswith("get_") or name == "retrieve_similar_incidents":
        return "read"
    if "simulate" in name or name == "tick_simulation":
        return "simulate"
    if "validate" in name:
        return "gate"
    if name.startswith("score_"):
        return "eval"
    if name.startswith("dispatch_"):
        return "act"
    if "memory" in name:
        return "memory"
    return "reason"


def _get_park_state(state: dict[str, Any]) -> dict[str, Any]:
    flow = _flow(state)
    zones = _zones(state)
    rides = _rides(state)
    busiest = max(zones, key=lambda item: _as_int(item.get("density")), default={})
    riskiest_ride = _primary_ride(state)
    return {
        "status": "ok",
        "scenario_key": _scenario_key(state),
        "active_policy": flow.get("activePolicy", "normal"),
        "represented_guests": flow.get("representedGuests", 0),
        "avg_satisfaction": flow.get("avgSatisfaction", 0),
        "busiest_zone": {"id": busiest.get("id"), "name": busiest.get("name"), "density": busiest.get("density")},
        "riskiest_ride": {"id": riskiest_ride.get("id"), "name": riskiest_ride.get("name"), "status": riskiest_ride.get("status"), "waitMins": riskiest_ride.get("waitMins")},
        "weather": state.get("weather", {}),
        "staffing": state.get("staffing", {}),
    }


def _get_zone_density(state: dict[str, Any], zone_id: str) -> dict[str, Any]:
    zone = _find_by_id(_zones(state), zone_id) or max(_zones(state), key=lambda item: _as_int(item.get("density")), default={})
    capacity = max(1, _as_int(zone.get("capacity"), 1))
    density = _as_int(zone.get("density"))
    return {
        "status": "ok" if zone else "not_found",
        "zone": zone,
        "spare_capacity_guests": max(0, capacity - _as_int(zone.get("currentGuests"))),
        "crowding_risk": "critical" if density >= 90 else "high" if density >= 80 else "watch" if density >= 70 else "ok",
    }


def _get_ride_status(state: dict[str, Any], ride_id: str) -> dict[str, Any]:
    ride = _find_by_id(_rides(state), ride_id) or _primary_ride(state)
    maintenance = state.get("maintenance", {}) if isinstance(state.get("maintenance"), dict) else {}
    work_orders = maintenance.get("openWorkOrders", []) if isinstance(maintenance.get("openWorkOrders"), list) else []
    relevant_orders = [item for item in work_orders if item.get("rideId") == ride.get("id")]
    return {
        "status": "ok" if ride else "not_found",
        "ride": ride,
        "maintenance_clearance": "not_cleared" if relevant_orders else "not_required",
        "blocked_automation": maintenance.get("blockedAutomation", []),
        "throughput_gap": ride.get("throughputGap", 0),
    }


def _get_staff_constraints(state: dict[str, Any], zone_id: str) -> dict[str, Any]:
    staffing = state.get("staffing", {}) if isinstance(state.get("staffing"), dict) else {}
    audit = state.get("operationsAudit", {}) if isinstance(state.get("operationsAudit"), dict) else {}
    schedule = audit.get("schedule", []) if isinstance(audit.get("schedule"), list) else []
    conflicts = [item for item in schedule if item.get("zoneId") in {zone_id, None, ""} or item.get("status") in {"conflict", "late"}]
    return {
        "status": "ok",
        "scheduled": staffing.get("scheduled", 0),
        "checked_in": staffing.get("checkedIn", 0),
        "open_callouts": staffing.get("openCallouts", 0),
        "medical_teams": staffing.get("medicalTeams", 0),
        "security_teams": staffing.get("securityTeams", 0),
        "hard_constraints": ["certified operator minimums", "protected breaks", "medical/security coverage"],
        "schedule_conflicts": conflicts[:3],
    }


def _get_food_capacity(state: dict[str, Any], location_id: str) -> dict[str, Any]:
    food = state.get("foodInventory", {}) if isinstance(state.get("foodInventory"), dict) else {}
    locations = food.get("locations", []) if isinstance(food.get("locations"), list) else []
    location = _find_by_id(locations, location_id) or min(locations, key=lambda item: _as_int(item.get("pickupEtaMinutes")), default={})
    return {
        "status": "ok" if location else "not_found",
        "location": location,
        "suppressed_items": food.get("suppressedItems", []),
        "policy": food.get("policy"),
        "capacity_read": "available" if _as_int(location.get("pickupEtaMinutes"), 99) <= 15 else "constrained",
    }


def _simulate_action(state: dict[str, Any], action_plan: dict[str, Any]) -> dict[str, Any]:
    projected = action_plan.get("projected_impact", {}) if isinstance(action_plan.get("projected_impact"), dict) else {}
    scorecard = action_plan.get("scorecard", {}) if isinstance(action_plan.get("scorecard"), dict) else {}
    simulation = simulate_action_plan(state, action_plan, horizon_minutes=_as_int(action_plan.get("horizon_minutes"), 30), seed="digital-twin-sim")
    if projected:
        simulation["optimizer_prior"] = {"projected_impact": projected, "scorecard": scorecard}
    return {key: value for key, value in simulation.items() if key != "projected_state"}


def _tick_simulation(state: dict[str, Any], minutes: int) -> dict[str, Any]:
    before = state_digest(state)
    after_state = transition_state(
        state,
        {"target": "none", "action": "natural", "label": "advance stress twin"},
        minutes=max(1, min(30, minutes)),
        seed="digital-twin-tick",
        stochastic=False,
    )
    return {
        "status": "ok",
        "source": "stateful_stress_transition_model",
        "minutes": max(1, min(30, minutes)),
        "before": before,
        "after": state_digest(after_state),
    }


def _compare_action_candidates(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = sorted(
        [item for item in candidates if isinstance(item, dict)],
        key=lambda item: _as_float((item.get("scorecard", {}) if isinstance(item.get("scorecard"), dict) else {}).get("overall")),
        reverse=True,
    )
    return {
        "status": "ok" if ranked else "empty",
        "ranked": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "overall": (item.get("scorecard", {}) if isinstance(item.get("scorecard"), dict) else {}).get("overall"),
                "take_rate_likelihood": (item.get("scorecard", {}) if isinstance(item.get("scorecard"), dict) else {}).get("take_rate_likelihood"),
                "rejected_reasons": item.get("rejected_reasons", []),
            }
            for item in ranked[:4]
        ],
        "selected": ranked[0].get("id") if ranked else None,
    }


def _validate_policy(state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    target = str(action.get("target") or action.get("park_action", {}).get("target") or "")
    operation = str(action.get("action") or action.get("park_action", {}).get("action") or "")
    findings = []
    blocked = False
    review = False
    maintenance = state.get("maintenance", {}) if isinstance(state.get("maintenance"), dict) else {}
    clock = state.get("operatingClock", {}) if isinstance(state.get("operatingClock"), dict) else {}
    events = clock.get("eventSchedule", {}) if isinstance(clock.get("eventSchedule"), dict) else {}
    event_risk = _as_int(events.get("eventTrafficRiskPct"), 0)
    if operation in set(maintenance.get("blockedAutomation", [])):
        blocked = True
        findings.append("Ride safety automation is blocked until maintenance clearance is recorded.")
    if target == "ride" and operation == "reopen" and any(ride.get("status") == "down" for ride in _rides(state)):
        blocked = True
        findings.append("Automated ride reopen is blocked while a ride remains down without maintenance clearance.")
    if target == "guest" and operation in {"broad_reroute", "move_all_guests_through_service_lane"} and event_risk >= 60:
        blocked = True
        findings.append("Broad guest movement is blocked during high showtime traffic because it can compromise access lanes and create secondary crowding.")
    if target == "guest" and operation == "bounded_split_flow":
        review = True
        findings.append("Bounded guest flow changes require receiver monitoring and operator-visible rollback criteria.")
    if target in {"ride", "energy"} and _scenario_key(state) in {"ride_down", "storm_response"}:
        review = True
        findings.append("Operator review required because action is safety-adjacent.")
    if target == "staff":
        review = True
        findings.append("Protected breaks and certified staffing minimums remain hard human constraints.")
    if target in {"guest", "customer_care"}:
        review = True
        findings.append("Guest-care actions must avoid PII and compensation promises.")
    return {
        "status": "ok",
        "allowed": not blocked,
        "gate_status": "blocked" if blocked else "pending_operator_approval" if review else "allowed",
        "findings": findings or ["Action is inside pre-approved operating policy."],
        "human_authority": [
            "ride reopening and safety clearance",
            "labor exceptions",
            "guest PII or compensation",
            "medical/security escalation",
        ],
    }


def _retrieve_similar_incidents(context: dict[str, Any] | None) -> dict[str, Any]:
    retrieved = (context or {}).get("retrieved", {}) if isinstance(context, dict) else {}
    return {
        "status": "ok",
        "playbooks": [item.get("_id") for item in retrieved.get("playbooks", [])[:3] if isinstance(item, dict)],
        "incidents": [item.get("_id") for item in retrieved.get("incidents", [])[:3] if isinstance(item, dict)],
        "learnings": [item.get("_id") for item in retrieved.get("learnings", [])[:4] if isinstance(item, dict)],
        "memory_mode": (context or {}).get("status", {}).get("mode") if isinstance(context, dict) else None,
    }


def _score_decision_quality(state: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    simulation = _simulate_action(state, decision)
    policy = _validate_policy(state, decision.get("selected_action", {}) if isinstance(decision.get("selected_action"), dict) else decision)
    scorecard = simulation.get("scorecard", {})
    safety = _as_int(scorecard.get("safety"), 92)
    capacity = _as_int(scorecard.get("capacity_fit"), 80)
    actionability = 88 if decision else 72
    authority_split = 96 if policy.get("gate_status") in {"allowed", "pending_operator_approval"} else 60
    overall = round(safety * 0.28 + capacity * 0.24 + actionability * 0.22 + authority_split * 0.26)
    return {
        "status": "ok",
        "overall": overall,
        "dimensions": {
            "safety": safety,
            "capacity_awareness": capacity,
            "actionability": actionability,
            "authority_split": authority_split,
        },
        "judge_note": "Scores the decision after tool simulation and policy validation, not just the final message.",
        "stress_model": {
            "source": simulation.get("source"),
            "uncertainty": simulation.get("uncertainty", {}),
            "secondary_risks": simulation.get("secondary_risks", []),
        },
    }


def _score_outcome_tool(state: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    action = args.get("action") if isinstance(args.get("action"), dict) else args
    projected = transition_state(
        state,
        action,
        minutes=_as_int(args.get("minutes"), 8),
        seed="digital-twin-score-outcome",
        stochastic=False,
    )
    return {
        "status": "ok",
        "source": "stateful_stress_transition_model",
        **score_outcome(state, projected, action),
    }


def _prepare_dispatch(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "prepared",
        "channel": name.replace("dispatch_", ""),
        "bounded": True,
        "requires_operator_approval": bool(args.get("requires_operator_approval", False)),
        "policy": "No unsafe ride control, PII, compensation promise, or labor exception in automated payloads.",
        "payload_preview": deepcopy(args.get("payload", args)),
    }


def _write_decision_memory(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "prepared",
        "memory_record": {
            "decision_id": args.get("decision_id", "pending"),
            "source": "digital_twin_tool_trace",
            "evidence_count": len(args.get("evidence", []) if isinstance(args.get("evidence"), list) else []),
            "outcome_hook": args.get("outcome_id", "pending"),
        },
    }
