from __future__ import annotations

from copy import deepcopy
from typing import Any


def _bounded(value: float, low: float = 0, high: float = 100) -> float:
    return max(low, min(high, value))


def _primary_disrupted_ride(rides: list[dict[str, Any]]) -> dict[str, Any]:
    if not rides:
        return {"id": "dragonCoaster", "name": "Dragon Coaster", "zone": "coasterPlaza", "zoneName": "Coaster Plaza", "waitMins": 60, "queueGuests": 700}
    return max(
        rides,
        key=lambda ride: (
            100 if ride.get("status") == "down" else 30 if ride.get("status") == "constrained" else 0,
            int(ride.get("downtimeRisk", 0) or 0),
            int(ride.get("queueGuests", 0) or 0),
            int(ride.get("waitMins", 0) or 0),
        ),
    )


def _zone_by_id(zones: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(zone.get("id")): zone for zone in zones}


def _food_pressure_zone(zones: list[dict[str, Any]]) -> dict[str, Any]:
    for zone in zones:
        if not isinstance(zone, dict):
            continue
        zone_id = str(zone.get("id") or "").lower()
        zone_name = str(zone.get("name") or "").lower()
        if zone_id in {"foodcourt1", "foodcourta"} or "food court a" in zone_name or zone.get("processType") == "food":
            return zone
    return {"id": "foodCourt1", "name": "Food Court A", "capacity": 1400, "density": 87, "waitMins": 38}


def _available_destinations(rides: list[dict[str, Any]], failed_ride_id: str) -> list[dict[str, Any]]:
    available = [ride for ride in rides if ride.get("id") != failed_ride_id and ride.get("status") != "down"]
    return sorted(
        available,
        key=lambda ride: (
            0 if ride.get("status") == "normal" else 1,
            int(ride.get("waitMins", 0) or 0),
            -int(ride.get("capacityPerHour", 0) or 0),
        ),
    )


def _route_mix(destinations: list[dict[str, Any]], shares: list[float]) -> list[dict[str, Any]]:
    rows = []
    for ride, share in zip(destinations, shares):
        rows.append(
            {
                "destinationId": ride.get("id"),
                "destination": ride.get("name"),
                "zoneId": ride.get("zone"),
                "share": round(share, 2),
                "currentWaitMins": ride.get("waitMins", 0),
                "status": ride.get("status", "normal"),
            }
        )
    return rows


def _destination_lookup(destinations: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for item in destinations:
        for key in (item.get("id"), item.get("name")):
            if key:
                lookup[str(key).strip().lower()] = item
    return lookup


def _strength(value: Any) -> str:
    raw = str(value or "medium").strip().lower()
    return raw if raw in {"low", "medium", "high"} else "medium"


def _as_float(value: Any, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _learning_rules(context: dict[str, Any] | None, scenario_key: str) -> list[dict[str, Any]]:
    retrieved = (context or {}).get("retrieved", {}) if isinstance(context, dict) else {}
    rows = retrieved.get("learnings", []) if isinstance(retrieved.get("learnings"), list) else []
    matching = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        impact = item.get("promotionImpact", {}) if isinstance(item.get("promotionImpact"), dict) else {}
        readiness = item.get("promotionReadiness", {}) if isinstance(item.get("promotionReadiness"), dict) else {}
        if (
            item.get("rollbackState") == "rollback_watch"
            or item.get("liveUseBlocked") is True
            or impact.get("rollbackState") == "rollback_watch"
            or readiness.get("regression_risk") is True
        ):
            continue
        item_scenario = str(item.get("scenarioKey", ""))
        if item_scenario in {scenario_key, "unknown", "proactive_event_monitoring"} or not item_scenario:
            matching.append(item)
    return matching[:4]


def _learning_summary(learnings: list[dict[str, Any]]) -> dict[str, Any]:
    if not learnings:
        return {
            "rules": [],
            "take_rate_multiplier": 1.0,
            "prefer_comfort_protection": False,
            "require_equipment_or_staff_action": False,
            "promotion_bias": "none",
        }
    multiplier = 1.0
    prefer_comfort = False
    require_control = False
    promotion_bias = "none"
    rules = []
    for item in learnings:
        adjustment = item.get("adjustment", {}) if isinstance(item.get("adjustment"), dict) else {}
        multiplier *= _bounded(_as_float(adjustment.get("takeRateMultiplier"), 1.0), 0.75, 1.25)
        prefer_comfort = prefer_comfort or bool(adjustment.get("preferComfortProtection"))
        require_control = require_control or bool(adjustment.get("requireEquipmentOrStaffAction"))
        if adjustment.get("promotionStrengthBias") == "increase":
            promotion_bias = "increase"
        elif adjustment.get("promotionStrengthBias") == "maintain" and promotion_bias == "none":
            promotion_bias = "maintain"
        rules.append(
            {
                "_id": item.get("_id"),
                "lesson": item.get("lesson"),
                "rule": item.get("rule"),
                "confidence": item.get("confidence"),
                "useCount": item.get("useCount"),
            }
        )
    return {
        "rules": rules,
        "take_rate_multiplier": round(_bounded(multiplier, 0.72, 1.32), 3),
        "prefer_comfort_protection": prefer_comfort,
        "require_equipment_or_staff_action": require_control,
        "promotion_bias": promotion_bias,
    }


def _apply_learning_to_candidates(candidates: list[dict[str, Any]], learning: dict[str, Any]) -> list[dict[str, Any]]:
    if not candidates or not learning.get("rules"):
        return candidates
    adjusted = []
    for candidate in candidates:
        item = deepcopy(candidate)
        scorecard = item.get("scorecard", {}) if isinstance(item.get("scorecard"), dict) else {}
        action_mix = item.get("action_mix", {}) if isinstance(item.get("action_mix"), dict) else {}
        reroute = action_mix.get("guest_reroute", {}) if isinstance(action_mix.get("guest_reroute"), dict) else {}
        staffing = action_mix.get("staffing", {}) if isinstance(action_mix.get("staffing"), dict) else {}
        facilities = action_mix.get("facilities", {}) if isinstance(action_mix.get("facilities"), dict) else {}
        hvac = facilities.get("hvac", {}) if isinstance(facilities.get("hvac"), dict) else {}
        target_mix = reroute.get("target_mix", []) if isinstance(reroute.get("target_mix"), list) else []

        learned_bonus = 0
        learned_penalty = 0
        if learning.get("promotion_bias") == "increase" and reroute.get("promotionStrength") == "high":
            learned_bonus += 5
        if learning.get("promotion_bias") == "increase" and reroute.get("promotionStrength") == "low":
            learned_penalty += 6
        if learning.get("prefer_comfort_protection") and hvac.get("protectShelterComfort"):
            learned_bonus += 4
        if learning.get("require_equipment_or_staff_action"):
            has_staff = bool(staffing.get("move_staff"))
            has_control = bool(hvac.get("protectShelterComfort"))
            if has_staff or has_control:
                learned_bonus += 4
            else:
                learned_penalty += 8
        if len(target_mix) >= 3:
            learned_bonus += 2
        if any(int(target.get("currentWaitMins", 0) or 0) >= 55 for target in target_mix):
            learned_penalty += 5

        multiplier = float(learning.get("take_rate_multiplier", 1.0) or 1.0)
        original_take = float(scorecard.get("take_rate_likelihood", 0) or 0)
        scorecard["take_rate_likelihood"] = round(_bounded(original_take * multiplier))
        scorecard["learning_adjustment"] = round(learned_bonus - learned_penalty)
        scorecard["overall"] = round(_bounded(float(scorecard.get("overall", 0) or 0) + learned_bonus - learned_penalty))
        item["scorecard"] = scorecard
        item["learned_adjustments"] = {
            "bonus": learned_bonus,
            "penalty": learned_penalty,
            "rules_applied": [rule.get("_id") for rule in learning.get("rules", []) if isinstance(rule, dict)],
        }
        adjusted.append(item)
    return adjusted


def _candidate_from_custom_mix(
    raw_mix: dict[str, Any],
    state: dict[str, Any],
    destinations: list[dict[str, Any]],
    failed_ride: dict[str, Any],
    failed_zone: dict[str, Any],
    base_common: dict[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(raw_mix, dict):
        return None

    destination_lookup = _destination_lookup(destinations)
    failed_id = str(failed_ride.get("id", "")).strip().lower()
    targets = []
    for raw_target in raw_mix.get("target_mix", []) if isinstance(raw_mix.get("target_mix"), list) else []:
        if not isinstance(raw_target, dict):
            continue
        target_id = str(raw_target.get("destination_id") or raw_target.get("destinationId") or "").strip()
        target_name = str(raw_target.get("destination") or "").strip()
        lookup_key = (target_id or target_name).lower()
        ride = destination_lookup.get(lookup_key) or destination_lookup.get(target_name.lower()) or {}
        resolved_id = str(ride.get("id") or target_id or target_name).strip()
        if not resolved_id or resolved_id.lower() == failed_id or ride.get("status") == "down":
            continue
        share = _bounded(_as_float(raw_target.get("share"), 0), 0.02, 0.7)
        targets.append(
            {
                "destinationId": resolved_id,
                "destination": ride.get("name") or target_name or resolved_id,
                "zoneId": ride.get("zone") or raw_target.get("zoneId") or resolved_id,
                "share": round(share, 2),
                "currentWaitMins": ride.get("waitMins", raw_target.get("currentWaitMins", 30)),
                "status": ride.get("status", "normal"),
                "rationale": raw_target.get("rationale", ""),
            }
        )

    has_custom_operations = any(
        isinstance(raw_mix.get(key), list) and raw_mix.get(key)
        for key in (
            "actions",
            "staff_moves",
            "guest_messages",
            "signage_updates",
            "queue_gate_controls",
            "equipment_controls",
        )
    )
    if not targets and not has_custom_operations:
        return None

    total_share = sum(float(item.get("share", 0) or 0) for item in targets)
    if total_share > 0.92:
        for item in targets:
            item["share"] = round(float(item["share"]) / total_share * 0.9, 2)
        total_share = sum(float(item.get("share", 0) or 0) for item in targets)

    if targets:
        hold_share = _bounded(_as_float(raw_mix.get("hold_share") or raw_mix.get("holdShare"), max(0.1, 1 - total_share)), 0.05, 0.55)
    else:
        hold_share = _bounded(_as_float(raw_mix.get("hold_share") or raw_mix.get("holdShare"), 0.92), 0.7, 0.98)
    promotion_strength = _strength(raw_mix.get("promotion_strength") or raw_mix.get("promotionStrength"))
    mix = deepcopy(base_common)
    mix["guest_reroute"] = {
        "enabled": bool(targets) and bool(raw_mix.get("guest_reroute_enabled", True)),
        "fromZone": failed_zone.get("name"),
        "target_mix": targets,
        "holdShare": round(hold_share, 2),
        "promotionStrength": promotion_strength,
        "offer": str(raw_mix.get("offer") or _offer_for_strength(promotion_strength)),
        "strategy": str(raw_mix.get("strategy") or ""),
        "rationale": str(raw_mix.get("rationale") or ""),
    }
    mix["operator_actions"] = [
        deepcopy(action)
        for action in (raw_mix.get("actions", []) if isinstance(raw_mix.get("actions"), list) else [])
        if isinstance(action, dict)
    ][:6]

    staff_moves = []
    for move in raw_mix.get("staff_moves", []) if isinstance(raw_mix.get("staff_moves"), list) else []:
        if not isinstance(move, dict):
            continue
        count = _as_int(move.get("count"), 0)
        if count <= 0:
            continue
        staff_moves.append(
            {
                "role": str(move.get("role") or "crowd_control"),
                "count": min(6, count),
                "from": str(move.get("from_location") or move.get("from") or "available pool"),
                "to": str(move.get("to_location") or move.get("to") or failed_zone.get("name", "affected zone")),
            }
        )
    mix["staffing"] = {
        "move_staff": staff_moves,
        "protectedBreaks": bool(raw_mix.get("protect_breaks", True)),
    }

    suppress_items = raw_mix.get("suppress_items") if isinstance(raw_mix.get("suppress_items"), list) else []
    promote_items = raw_mix.get("promote_items") if isinstance(raw_mix.get("promote_items"), list) else []
    mix["food"] = {
        "avoidExtraDemandAt": mix.get("food", {}).get("avoidExtraDemandAt", []),
        "promoteItems": [str(item) for item in promote_items[:5]] or mix.get("food", {}).get("promoteItems", []),
        "suppressItems": [str(item) for item in suppress_items[:5]],
    }

    raw_setpoints = raw_mix.get("hvac_setpoints") if isinstance(raw_mix.get("hvac_setpoints"), dict) else {}
    base_hvac = mix.get("facilities", {}).get("hvac", {})
    mix["facilities"] = {
        "hvac": {
            "protectShelterComfort": bool(raw_setpoints) or bool(base_hvac.get("protectShelterComfort")),
            "indoorHubSetpointF": _as_int(raw_setpoints.get("indoorHub") or raw_setpoints.get("indoorHubSetpointF"), base_hvac.get("indoorHubSetpointF", 72)),
            "arcadeZoneSetpointF": _as_int(raw_setpoints.get("arcadeZone") or raw_setpoints.get("arcadeZoneSetpointF"), base_hvac.get("arcadeZoneSetpointF", 73)),
            "shedNoncriticalLighting": bool(base_hvac.get("shedNoncriticalLighting", True)),
            "customSetpoints": raw_setpoints,
        }
    }

    guest_messages = []
    for message in raw_mix.get("guest_messages", []) if isinstance(raw_mix.get("guest_messages"), list) else []:
        if not isinstance(message, dict):
            continue
        guest_messages.append(
            {
                "audience": str(message.get("audience") or "affected_guest_segment"),
                "message": str(message.get("message") or "Updated park guidance is available in the app."),
                "offer": str(message.get("offer") or raw_mix.get("offer") or "Guided alternate route."),
                "radiusMeters": _as_int(message.get("radiusMeters"), 300),
                "expiresMinutes": _as_int(message.get("expiresMinutes"), 20),
            }
        )
    if guest_messages:
        mix["guest_services"] = {"messages": guest_messages[:3]}

    signage_updates = []
    for sign in raw_mix.get("signage_updates", []) if isinstance(raw_mix.get("signage_updates"), list) else []:
        if not isinstance(sign, dict):
            continue
        signage_updates.append(
            {
                "zones": sign.get("zones", [failed_zone.get("id", "coasterPlaza")]) if isinstance(sign.get("zones"), list) else [failed_zone.get("id", "coasterPlaza")],
                "message": str(sign.get("message") or "Use alternate low-wait route."),
                "durationMinutes": _as_int(sign.get("durationMinutes"), 20),
            }
        )
    queue_gate_controls = []
    for gate in raw_mix.get("queue_gate_controls", []) if isinstance(raw_mix.get("queue_gate_controls"), list) else []:
        if not isinstance(gate, dict):
            continue
        queue_gate_controls.append(
            {
                "zones": gate.get("zones", [failed_zone.get("id", "coasterPlaza")]) if isinstance(gate.get("zones"), list) else [failed_zone.get("id", "coasterPlaza")],
                "command": str(gate.get("command") or "pause_new_queue_intake"),
                "settings": gate.get("settings", {"holdMinutes": 15}) if isinstance(gate.get("settings"), dict) else {"holdMinutes": 15},
                "requiresHumanApproval": bool(gate.get("requiresHumanApproval", False)),
            }
        )
    if signage_updates or queue_gate_controls:
        mix["controls"] = {"signage": signage_updates[:3], "queue_gates": queue_gate_controls[:3]}

    name = str(raw_mix.get("name") or "Gemini custom mix").strip()[:80]
    aggressiveness = _bounded(1 - hold_share + (0.08 if promotion_strength == "high" else 0), 0.35, 1.05)
    candidate = _estimate_plan(name, state, mix, aggressiveness, promotion_strength, hold_share)
    candidate["source"] = "gemini_custom_mix"
    return candidate


def _role_agent_proposals(context: dict[str, Any] | None) -> dict[str, Any]:
    proposals = (context or {}).get("role_agent_proposals", {}) if isinstance(context, dict) else {}
    return proposals if isinstance(proposals, dict) else {}


def _role_quality_prior(context: dict[str, Any] | None, agent_id: str) -> dict[str, Any]:
    priors = (context or {}).get("role_quality_priors", {}) if isinstance(context, dict) else {}
    by_agent = priors.get("by_agent", {}) if isinstance(priors, dict) and isinstance(priors.get("by_agent"), dict) else {}
    prior = by_agent.get(agent_id, {})
    return prior if isinstance(prior, dict) else {}


def _candidate_from_role_proposal(
    proposal: dict[str, Any],
    state: dict[str, Any],
    scenario_key: str,
    destinations: list[dict[str, Any]],
    failed_ride: dict[str, Any],
    failed_zone: dict[str, Any],
    base_common: dict[str, Any],
    role_prior: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(proposal, dict):
        return None
    action = proposal.get("proposed_action", {}) if isinstance(proposal.get("proposed_action"), dict) else {}
    target = str(action.get("target") or "")
    verb = str(action.get("action") or "")
    if target in {"scenario"} or verb in {"ground_context", "policy_gate", "synthesize_role_proposals"}:
        return None

    agent_id = str(proposal.get("agent_id") or "role_agent")
    confidence = _bounded(_as_float(proposal.get("confidence"), 0.72), 0.2, 1.0)
    mix = deepcopy(base_common)
    promotion_strength = "medium"
    hold_share = 0.24
    aggressiveness = 0.76

    if target == "food" or verb in {"redirect_food_demand", "suppress_item"}:
        target_mix = _route_mix(destinations, [0.32, 0.24, 0.14])
        mix["guest_reroute"] = {
            "enabled": True,
            "fromZone": failed_zone.get("name"),
            "target_mix": target_mix,
            "holdShare": 0.26,
            "promotionStrength": "medium",
            "offer": "Route to available food capacity without adding new constrained-zone demand.",
            "strategy": "role_agent_food_demand_split",
            "rationale": proposal.get("recommendation", ""),
        }
        mix["food"] = {
            **mix.get("food", {}),
            "avoidExtraDemandAt": list(dict.fromkeys([*mix.get("food", {}).get("avoidExtraDemandAt", []), failed_zone.get("id") or failed_zone.get("name") or "foodCourtA"])),
            "suppressItems": ["chicken_tenders", "bottled_drinks"],
            "promoteItems": ["pizza_combo"],
        }
        mix["controls"] = {
            "signage": [{"zones": [failed_zone.get("id", "foodCourtA")], "message": "Use Food Court B or Main Street Shops for faster pickup.", "durationMinutes": 25}],
            "queue_gates": [],
        }
        promotion_strength = "medium"
        hold_share = 0.26
        aggressiveness = 0.74
    elif target == "staff" or verb == "redeploy":
        role = str(action.get("role") or "crowd_control")
        mix["guest_reroute"] = {
            "enabled": True,
            "fromZone": failed_zone.get("name"),
            "target_mix": _route_mix(destinations, [0.24, 0.2, 0.12]),
            "holdShare": 0.34,
            "promotionStrength": "low",
            "offer": _offer_for_strength("low"),
            "strategy": "role_agent_staff_limited_demand_shift",
            "rationale": proposal.get("recommendation", ""),
        }
        mix["staffing"] = {
            "move_staff": [{"role": role, "count": 2, "from": "available cross-trained pool", "to": failed_zone.get("name", "affected zone")}],
            "protectedBreaks": True,
        }
        promotion_strength = "low"
        hold_share = 0.34
        aggressiveness = 0.58
    elif target == "energy" or verb == "protect_hvac":
        mix["guest_reroute"] = {
            "enabled": True,
            "fromZone": failed_zone.get("name"),
            "target_mix": _route_mix(destinations, [0.26, 0.2, 0.14]),
            "holdShare": 0.28,
            "promotionStrength": "medium",
            "offer": "Guided route toward covered capacity while indoor comfort is protected.",
            "strategy": "role_agent_shelter_comfort",
            "rationale": proposal.get("recommendation", ""),
        }
        mix["facilities"] = {
            "hvac": {
                "protectShelterComfort": True,
                "indoorHubSetpointF": 72,
                "arcadeZoneSetpointF": 73,
                "shedNoncriticalLighting": True,
                "operatorRequestedZones": action.get("zones", ["indoorHub", "coveredPlaza"]) if isinstance(action.get("zones"), list) else ["indoorHub", "coveredPlaza"],
            }
        }
        promotion_strength = "medium"
        hold_share = 0.28
        aggressiveness = 0.68
    elif target in {"guest", "guest_services"} or verb == "message":
        mix["guest_reroute"] = {
            "enabled": True,
            "fromZone": failed_zone.get("name"),
            "target_mix": _route_mix(destinations, [0.3, 0.22, 0.16]),
            "holdShare": 0.22,
            "promotionStrength": "medium",
            "offer": _offer_for_strength("medium"),
            "strategy": str(action.get("routing") or "role_agent_guest_flow_split"),
            "rationale": proposal.get("recommendation", ""),
        }
        promotion_strength = "medium"
        hold_share = 0.22
        aggressiveness = 0.78
    elif target == "ride" or verb in {"reroute", "hold_and_reroute"}:
        mix["guest_reroute"] = {
            "enabled": True,
            "fromZone": failed_zone.get("name"),
            "target_mix": _route_mix(destinations, [0.34, 0.24, 0.14]),
            "holdShare": 0.24,
            "promotionStrength": "medium",
            "offer": _offer_for_strength("medium"),
            "strategy": "role_agent_ride_ops_hold_and_reroute",
            "rationale": proposal.get("recommendation", ""),
        }
        mix["controls"] = {
            "signage": [{"zones": [failed_zone.get("id", "coasterPlaza")], "message": "Attraction unavailable; use alternate low-wait routes.", "durationMinutes": 20}],
            "queue_gates": [{"zones": [failed_zone.get("id", "coasterPlaza")], "command": "pause_new_queue_intake", "settings": {"holdMinutes": 15}, "requiresHumanApproval": False}],
        }
        promotion_strength = "medium"
        hold_share = 0.24
        aggressiveness = 0.8
    else:
        return None

    name = f"{proposal.get('role', agent_id)} proposal"
    candidate = _estimate_plan(str(name)[:80], state, mix, aggressiveness, promotion_strength, hold_share)
    base_score = candidate.get("scorecard", {}).get("overall", 0)
    proposal_bonus = round(confidence * 6 + (3 if proposal.get("proposal_type") == "action" else 1))
    if scenario_key == "staff_shortage" and agent_id == "staffing_agent":
        proposal_bonus += 4
    if scenario_key == "food_spike" and agent_id == "food_demand_agent":
        proposal_bonus += 4
    if scenario_key == "storm_response" and agent_id == "facilities_energy_agent":
        proposal_bonus += 4
    prior = role_prior if isinstance(role_prior, dict) else {}
    prior_adjustment = round(_bounded(_as_float(prior.get("prior_adjustment"), 0), -6, 6))
    candidate["scorecard"]["role_alignment_bonus"] = proposal_bonus
    candidate["scorecard"]["role_memory_prior_adjustment"] = prior_adjustment
    candidate["scorecard"]["overall"] = round(_bounded(float(base_score or 0) + proposal_bonus + prior_adjustment))
    candidate["source"] = "role_agent_proposal"
    candidate["role_proposal"] = {
        "agent_id": agent_id,
        "role": proposal.get("role"),
        "proposal_type": proposal.get("proposal_type"),
        "recommendation": proposal.get("recommendation"),
        "proposed_action": action,
        "confidence": confidence,
        "constraints": proposal.get("constraints", []),
        "policy_refs": proposal.get("policy_refs", []),
        "memory_prior": prior,
    }
    return candidate


def _role_proposal_candidates(
    context: dict[str, Any] | None,
    state: dict[str, Any],
    scenario_key: str,
    destinations: list[dict[str, Any]],
    failed_ride: dict[str, Any],
    failed_zone: dict[str, Any],
    base_common: dict[str, Any],
) -> list[dict[str, Any]]:
    role_artifact = _role_agent_proposals(context)
    proposals = role_artifact.get("proposals", []) if isinstance(role_artifact.get("proposals"), list) else []
    candidates = []
    for proposal in proposals[:8]:
        agent_id = str(proposal.get("agent_id") or "") if isinstance(proposal, dict) else ""
        candidate = _candidate_from_role_proposal(
            proposal,
            state,
            scenario_key,
            destinations,
            failed_ride,
            failed_zone,
            base_common,
            _role_quality_prior(context, agent_id),
        )
        if candidate:
            candidates.append(candidate)
    return candidates


def _estimate_plan(
    name: str,
    state: dict[str, Any],
    base_mix: dict[str, Any],
    aggressiveness: float,
    promotion_strength: str,
    hold_share: float,
) -> dict[str, Any]:
    flow = state.get("guestFlow", {})
    rides = flow.get("rides", [])
    zones = flow.get("zones", [])
    zone_lookup = _zone_by_id(zones)
    failed_ride = _primary_disrupted_ride(rides)
    failed_zone = zone_lookup.get(str(failed_ride.get("zone")), {})
    queued = int(failed_ride.get("queueGuests", 500) or 500)
    target_mix = base_mix.get("guest_reroute", {}).get("target_mix", [])
    moved_guests = round(queued * (1 - hold_share) * aggressiveness)
    target_pressure = 0.0
    overloaded_targets: list[str] = []
    for target in target_mix:
        zone = zone_lookup.get(str(target.get("zoneId")), {})
        capacity = max(1, int(zone.get("capacity", 1500) or 1500))
        added = moved_guests * float(target.get("share", 0) or 0)
        projected_density = float(zone.get("density", 55) or 55) + (added / capacity) * 100
        wait = float(target.get("currentWaitMins", 20) or 20)
        target_pressure += projected_density * 0.55 + wait * 0.45
        if projected_density >= 92 or wait >= 55:
            overloaded_targets.append(str(target.get("destination")))

    target_count = max(1, len(target_mix))
    avg_target_pressure = target_pressure / target_count
    capacity_fit = _bounded(112 - avg_target_pressure)
    offer_bonus = {"low": 0.03, "medium": 0.09, "high": 0.16}.get(promotion_strength, 0.09)
    take_rate = _bounded(0.22 + offer_bonus + capacity_fit / 450 - hold_share * 0.08, 0.12, 0.68)
    follow_through = _bounded(take_rate - 0.05 + capacity_fit / 700, 0.08, 0.64)
    staff_moves = base_mix.get("staffing", {}).get("move_staff", [])
    moved_staff = sum(int(item.get("count", 0) or 0) for item in staff_moves)
    staff_burden = _bounded(100 - moved_staff * 8 - (12 if moved_guests > 600 else 0))
    energy_balance = 82 if base_mix.get("facilities", {}).get("hvac", {}).get("protectShelterComfort") else 72
    safety = 98 if failed_ride.get("status") == "down" else 92
    guest_recovery = _bounded(55 + take_rate * 45 + (8 if promotion_strength == "high" else 0) - len(overloaded_targets) * 8)
    overcorrection_risk = _bounded(len(overloaded_targets) * 25 + max(0, moved_guests - 650) / 12 + moved_staff * 3)
    total = round(
        capacity_fit * 0.22
        + guest_recovery * 0.2
        + staff_burden * 0.16
        + safety * 0.18
        + energy_balance * 0.08
        + (100 - overcorrection_risk) * 0.16
    )
    before_density = int(failed_zone.get("density", 85) or 85)
    density_delta = -round((moved_guests / max(1, int(failed_zone.get("capacity", 1600) or 1600))) * 100)
    if base_mix.get("guest_reroute"):
        base_mix["guest_reroute"]["estimatedMovedGuests"] = moved_guests
        base_mix["guest_reroute"]["expectedTakeRate"] = round(take_rate, 3)
        base_mix["guest_reroute"]["expectedFollowThroughRate"] = round(follow_through, 3)
    return {
        "id": name.lower().replace(" ", "_"),
        "name": name,
        "action_mix": base_mix,
        "scorecard": {
            "overall": _bounded(total),
            "capacity_fit": round(capacity_fit),
            "take_rate_likelihood": round(take_rate * 100),
            "staff_burden": round(staff_burden),
            "safety": round(safety),
            "energy_comfort_balance": round(energy_balance),
            "overcorrection_risk": round(overcorrection_risk),
        },
        "projected_impact": {
            "fromZone": failed_zone.get("name", "affected zone"),
            "movedGuests": moved_guests,
            "densityDeltaPct": density_delta,
            "projectedDensity": _bounded(before_density + density_delta, 0, 118),
            "avgWaitDeltaMinutes": -round(moved_guests / 90),
            "staffStressDelta": moved_staff * 3,
            "energyCostDeltaPct": 2 if base_mix.get("facilities", {}).get("hvac", {}).get("protectShelterComfort") else -3,
            "guestSatisfactionDelta": round(guest_recovery / 12),
        },
        "rejected_reasons": _rejection_reasons(overloaded_targets, staff_burden, overcorrection_risk, capacity_fit),
    }


def _rejection_reasons(overloaded_targets: list[str], staff_burden: float, overcorrection_risk: float, capacity_fit: float) -> list[str]:
    reasons = []
    if overloaded_targets:
        reasons.append(f"Would overload {', '.join(overloaded_targets[:2])}.")
    if staff_burden < 70:
        reasons.append("Requires more staff movement than current coverage can absorb.")
    if overcorrection_risk > 55:
        reasons.append("Moves too many guests too quickly and risks a new bottleneck.")
    if capacity_fit < 55:
        reasons.append("Target capacity fit is weak for the current queue and path pressure.")
    return reasons or ["Feasible, but lower total score than selected plan."]


def _normalized_selected_action(
    selected: dict[str, Any],
    scenario_key: str,
    failed_ride: dict[str, Any],
) -> dict[str, Any]:
    role_proposal = selected.get("role_proposal", {}) if isinstance(selected.get("role_proposal"), dict) else {}
    proposed = role_proposal.get("proposed_action", {}) if isinstance(role_proposal.get("proposed_action"), dict) else {}
    target = str(proposed.get("target") or "")
    action = str(proposed.get("action") or "")
    if selected.get("source") == "role_agent_proposal":
        if target == "food" or action in {"redirect_food_demand", "suppress_item"}:
            normalized_target, normalized_action = "food", "suppress_item"
        elif target == "staff" or action == "redeploy":
            normalized_target, normalized_action = "staff", "redeploy"
        elif target == "energy" or action == "protect_hvac":
            normalized_target, normalized_action = "energy", "protect_hvac"
        elif target in {"guest", "guest_services"} or action == "message":
            normalized_target, normalized_action = "guest_services", "message"
        else:
            normalized_target, normalized_action = "ride", "reroute"
        return {
            "target": normalized_target,
            "action": normalized_action,
            "label": f"{selected['name']}: {role_proposal.get('recommendation') or 'role-backed action'}",
            "owner": role_proposal.get("role") or "Decision Bridge",
            "expected_effect": (
                f"Use the {role_proposal.get('agent_id', 'role agent')} proposal with score {selected['scorecard']['overall']} "
                f"and {selected['scorecard']['take_rate_likelihood']}% take-rate likelihood."
            ),
            "risk_notes": selected.get("rejected_reasons", []),
            "estimated_score": selected["scorecard"]["overall"],
            "role_proposal": role_proposal,
        }
    if scenario_key == "food_spike":
        return {
            "target": "food",
            "action": "suppress_item",
            "label": f"{selected['name']}: rebalance Food Court A demand",
            "owner": "Food Demand Agent",
            "expected_effect": (
                f"Redirect demand away from Food Court A with a {selected['scorecard']['take_rate_likelihood']}% "
                "take-rate likelihood while preserving nearby guest experience."
            ),
            "risk_notes": selected.get("rejected_reasons", []),
            "estimated_score": selected["scorecard"]["overall"],
        }
    return {
        "target": "ride",
        "action": "reroute",
        "label": f"{selected['name']}: custom response mix for {failed_ride.get('name')}",
        "owner": "Decision Bridge",
        "expected_effect": (
            f"Move about {selected['projected_impact']['movedGuests']} guests from {selected['projected_impact']['fromZone']} "
            f"with a {selected['scorecard']['take_rate_likelihood']}% take-rate likelihood."
        ),
        "risk_notes": selected.get("rejected_reasons", []),
        "estimated_score": selected["scorecard"]["overall"],
    }


def _decision_bridge_resolution(ranked: list[dict[str, Any]], role_artifact: dict[str, Any]) -> dict[str, Any]:
    selected = ranked[0] if ranked else {}
    role_candidates = [item for item in ranked if item.get("source") == "role_agent_proposal"]
    accepted = selected.get("role_proposal") if selected.get("source") == "role_agent_proposal" else None
    rejected = []
    selected_id = selected.get("id")
    for item in role_candidates:
        if item.get("id") == selected_id:
            continue
        role = item.get("role_proposal", {}) if isinstance(item.get("role_proposal"), dict) else {}
        rejected.append(
            {
                "candidate_id": item.get("id"),
                "agent_id": role.get("agent_id"),
                "role": role.get("role"),
                "recommendation": role.get("recommendation"),
                "score": item.get("scorecard", {}).get("overall"),
                "reason": item.get("rejected_reasons", ["Lower scored after capacity, staff, safety, and response tradeoffs."])[0],
            }
        )
    return {
        "mode": "decision_bridge_role_resolution",
        "selected_candidate_id": selected.get("id"),
        "selected_source": selected.get("source"),
        "accepted_role_proposal": accepted,
        "rejected_role_proposals": rejected[:5],
        "conflicts": role_artifact.get("conflicts", []) if isinstance(role_artifact, dict) else [],
        "summary": (
            "Selected a role-backed candidate after scoring specialist proposals against deterministic alternatives."
            if accepted
            else "Role proposals were scored, but a non-role candidate won the tournament on capacity, safety, staff, and response balance."
        ),
    }


def optimize_park_response(
    state: dict[str, Any],
    scenario_key: str,
    context: dict[str, Any] | None = None,
    llm_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    flow = state.get("guestFlow", {})
    rides = flow.get("rides", [])
    zones = flow.get("zones", [])
    failed_ride = _primary_disrupted_ride(rides)
    destinations = _available_destinations(rides, str(failed_ride.get("id")))
    if len(destinations) < 3:
        fallback_destination = (
            {"id": "foodCourtB", "name": "Food Court B", "zone": "foodCourtB", "waitMins": 16, "status": "normal", "capacityPerHour": 900}
            if scenario_key == "food_spike"
            else {"id": "foodCourt1", "name": "Food Court 1", "zone": "foodCourt1", "waitMins": 28, "status": "normal", "capacityPerHour": 900}
        )
        destinations = destinations + [fallback_destination]
    zone_lookup = _zone_by_id(zones)
    failed_zone = zone_lookup.get(str(failed_ride.get("zone")), {"id": failed_ride.get("zone"), "name": failed_ride.get("zoneName", "Coaster Plaza")})
    if scenario_key == "food_spike":
        failed_zone = _food_pressure_zone(zones)
        failed_ride = {
            "id": failed_zone.get("id", "foodCourt1"),
            "name": failed_zone.get("name", "Food Court A"),
            "zone": failed_zone.get("id", "foodCourt1"),
            "zoneName": failed_zone.get("name", "Food Court A"),
            "waitMins": failed_zone.get("waitMins", 38),
            "queueGuests": failed_zone.get("currentGuests", 900),
            "status": "constrained",
            "capacityPerHour": failed_zone.get("capacity", 1400),
        }
    excluded = [failed_ride.get("id")]

    base_common = {
        "fromRide": failed_ride.get("name"),
        "fromZone": failed_zone.get("name"),
        "excludedDestinations": excluded,
        "staffing": {
            "move_staff": [
                {"role": "crowd_control", "count": 2, "from": "Entrance Plaza", "to": failed_zone.get("name", "affected zone")},
            ],
            "protectedBreaks": True,
        },
        "food": {
            "avoidExtraDemandAt": ["Food Court 1"] if any(float(zone.get("density", 0) or 0) >= 85 and zone.get("processType") == "food" for zone in zones) else [],
            "promoteItems": ["pizza_combo"],
            "suppressItems": ["chicken_tenders"] if scenario_key == "food_spike" else [],
        },
        "facilities": {
            "hvac": {
                "protectShelterComfort": scenario_key == "storm_response" or float(state.get("energy", {}).get("gridLoadPercent", 0) or 0) >= 92,
                "indoorHubSetpointF": 72,
                "arcadeZoneSetpointF": 73,
                "shedNoncriticalLighting": True,
            }
        },
    }

    deterministic_specs = [
        ("Balanced split", [0.35, 0.25, 0.15], 0.84, "medium", 0.15),
        ("Aggressive indoor pull", [0.55, 0.25, 0.08], 0.96, "high", 0.06),
        ("Conservative hold and recover", [0.25, 0.2, 0.15], 0.62, "high", 0.35),
    ]
    candidates = []
    custom_mixes = (llm_plan or {}).get("custom_action_mixes", [])
    if not isinstance(custom_mixes, list):
        custom_mixes = []
    for raw_mix in custom_mixes[:4]:
        candidate = _candidate_from_custom_mix(raw_mix, state, destinations, failed_ride, failed_zone, base_common)
        if candidate:
            candidates.append(candidate)

    role_artifact = _role_agent_proposals(context)
    role_candidates = _role_proposal_candidates(context, state, scenario_key, destinations, failed_ride, failed_zone, base_common)
    candidates.extend(role_candidates)

    operator_mode = bool((context or {}).get("operator_mode") == "operator_command")
    candidate_source = (
        "hybrid_role_proposals"
        if role_candidates
        else "gemini_custom_mixes"
        if candidates and (operator_mode or len(candidates) >= 2)
        else "deterministic_templates"
    )
    for name, shares, aggressiveness, promotion_strength, hold_share in deterministic_specs:
        if candidate_source in {"gemini_custom_mixes", "hybrid_role_proposals"} and (operator_mode or len(candidates) >= 3):
            break
        mix = deepcopy(base_common)
        mix["guest_reroute"] = {
            "enabled": True,
            "fromZone": failed_zone.get("name"),
            "target_mix": _route_mix(destinations, shares),
            "holdShare": round(hold_share, 2),
            "promotionStrength": promotion_strength,
            "offer": _offer_for_strength(promotion_strength),
        }
        if name == "Aggressive indoor pull":
            mix["staffing"]["move_staff"].append({"role": "greeter", "count": 1, "from": "Theater B", "to": "Indoor Ride Hub"})
        candidate = _estimate_plan(name, state, mix, aggressiveness, promotion_strength, hold_share)
        candidate["source"] = "deterministic_template"
        candidates.append(candidate)

    learning = _learning_summary(_learning_rules(context, scenario_key))
    candidates = _apply_learning_to_candidates(candidates, learning)

    selected = max(candidates, key=lambda item: item["scorecard"]["overall"])
    ranked = sorted(candidates, key=lambda item: item["scorecard"]["overall"], reverse=True)
    selected["selected_action"] = _normalized_selected_action(selected, scenario_key, failed_ride)
    resolution = _decision_bridge_resolution(ranked, role_artifact)
    return {
        "mode": (
            "hybrid_role_tournament"
            if candidate_source == "hybrid_role_proposals"
            else "gemini_plan_tournament"
            if candidate_source == "gemini_custom_mixes"
            else "parameterized_plan_tournament"
        ),
        "candidate_source": candidate_source,
        "gemini_custom_mix_count": len(custom_mixes),
        "role_proposal_candidate_count": len(role_candidates),
        "scenario_key": scenario_key,
        "selected_plan_id": selected["id"],
        "selected_plan": selected,
        "candidates": ranked,
        "decision_bridge_resolution": resolution,
        "decision_summary": (
            f"Selected {selected['name']} because it best balances role recommendations, capacity, staff burden, safety, and take-rate likelihood."
            if role_candidates
            else f"Selected {selected['name']} because it best balances capacity, staff burden, safety, and take-rate likelihood."
        ),
        "memory_used": {
            "playbooks": [item.get("_id") for item in (context or {}).get("retrieved", {}).get("playbooks", [])[:3] if isinstance(item, dict)],
            "incidents": [item.get("_id") for item in (context or {}).get("retrieved", {}).get("incidents", [])[:3] if isinstance(item, dict)],
            "learnings": [item.get("_id") for item in (context or {}).get("retrieved", {}).get("learnings", [])[:4] if isinstance(item, dict)],
            "learning_rules": learning.get("rules", []),
            "learning_effect": {
                "take_rate_multiplier": learning.get("take_rate_multiplier"),
                "promotion_bias": learning.get("promotion_bias"),
                "prefer_comfort_protection": learning.get("prefer_comfort_protection"),
                "require_equipment_or_staff_action": learning.get("require_equipment_or_staff_action"),
            },
            "role_quality_priors": (context or {}).get("role_quality_priors", {}),
        },
    }


def revise_plan_after_response(optimization: dict[str, Any], response_metrics: dict[str, Any]) -> dict[str, Any] | None:
    if int(response_metrics.get("score", 0) or 0) >= 70:
        return None
    selected = deepcopy(optimization.get("selected_plan", {}))
    action_mix = selected.get("action_mix", {})
    reroute = action_mix.get("guest_reroute", {}) if isinstance(action_mix.get("guest_reroute"), dict) else {}
    target_mix = reroute.get("target_mix", []) if isinstance(reroute.get("target_mix"), list) else []
    safer_targets = [
        item for item in target_mix if str(item.get("status")) == "normal" and int(item.get("currentWaitMins", 0) or 0) < 45
    ] or target_mix[:2]
    total_share = sum(float(item.get("share", 0) or 0) for item in safer_targets) or 1
    revised_targets = []
    for item in safer_targets:
        revised = deepcopy(item)
        revised["share"] = round((float(item.get("share", 0) or 0) / total_share) * 0.72, 2)
        revised_targets.append(revised)
    reroute["target_mix"] = revised_targets
    reroute["holdShare"] = 0.18
    reroute["promotionStrength"] = "high"
    reroute["offer"] = "Higher-value recovery offer for selected low-wait destinations; avoid overloaded targets."
    reroute["expectedTakeRate"] = round(min(0.68, float(response_metrics.get("takeRate", 0.3) or 0.3) + 0.16), 3)
    reroute["expectedFollowThroughRate"] = round(min(0.62, float(response_metrics.get("reactiveFollowThroughRate", 0.25) or 0.25) + 0.18), 3)
    reroute["estimatedMovedGuests"] = round(float(reroute.get("estimatedMovedGuests", 450) or 450) * 0.82)
    selected["name"] = f"Revision after low response: {selected.get('name', 'custom mix')}"
    selected["id"] = f"{selected.get('id', 'selected')}_revision"
    selected["action_mix"] = action_mix
    selected["selected_action"] = {
        "target": "ride",
        "action": "reroute",
        "label": "Revise route mix after weak take rate",
        "owner": "Decision Bridge",
        "expected_effect": "Increase incentive strength and remove overloaded destinations from the route mix.",
        "risk_notes": ["Triggered because GCP internal response score was below 70."],
        "estimated_score": max(70, int(selected.get("scorecard", {}).get("overall", 70) or 70)),
    }
    selected["revision_reason"] = (
        f"Response score {response_metrics.get('score')} was weak; take rate "
        f"{round(float(response_metrics.get('takeRate', 0) or 0) * 100)}% and follow-through "
        f"{round(float(response_metrics.get('reactiveFollowThroughRate', 0) or 0) * 100)}% require a stronger custom mix."
    )
    return selected


def _offer_for_strength(strength: str) -> str:
    if strength == "high":
        return "Priority bonus points plus show/arcade reward for check-in within 30 minutes."
    if strength == "medium":
        return "Bonus points for Arcade or Theater check-in within 30 minutes."
    return "App guidance toward lower-wait attractions."
