from __future__ import annotations

import random
from copy import deepcopy
from typing import Any


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


def _space_capacity(area_sqm: float, fallback_capacity: int, sqm_per_guest: float = 1.35) -> int:
    if area_sqm > 0:
        return max(1, round(area_sqm / sqm_per_guest))
    return max(1, fallback_capacity)


def _path_flow_capacity(path: dict[str, Any], minutes: int) -> int:
    explicit = _as_int(path.get("maxFlowPerMinute"))
    if explicit > 0:
        return max(1, round(explicit * minutes))
    width_m = _as_float(path.get("widthM"), 4.0)
    # Conservative bidirectional crowd flow: about 52 people / meter / minute.
    return max(1, round(width_m * 52 * minutes))


def _flow(state: dict[str, Any]) -> dict[str, Any]:
    flow = state.get("guestFlow", {})
    return flow if isinstance(flow, dict) else {}


def _zones(state: dict[str, Any]) -> list[dict[str, Any]]:
    zones = _flow(state).get("zones", [])
    return zones if isinstance(zones, list) else []


def _rides(state: dict[str, Any]) -> list[dict[str, Any]]:
    rides = _flow(state).get("rides", [])
    return rides if isinstance(rides, list) else []


def _paths(state: dict[str, Any]) -> list[dict[str, Any]]:
    paths = _flow(state).get("paths", [])
    return paths if isinstance(paths, list) else []


def _physical(state: dict[str, Any]) -> dict[str, Any]:
    physical = state.get("physicalMap", {})
    return physical if isinstance(physical, dict) else {}


def _guest_groups(state: dict[str, Any]) -> list[dict[str, Any]]:
    groups = _physical(state).get("guestGroups", [])
    return groups if isinstance(groups, list) else []


def _queues(state: dict[str, Any]) -> list[dict[str, Any]]:
    queues = _physical(state).get("queues", [])
    return queues if isinstance(queues, list) else []


def _by_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("id")): row for row in rows if row.get("id")}


def _primary_ride(state: dict[str, Any]) -> dict[str, Any]:
    rides = _rides(state)
    if not rides:
        return {
            "id": "dragonCoaster",
            "name": "Dragon Coaster",
            "zone": "coasterPlaza",
            "queueGuests": 700,
            "waitMins": 60,
            "status": "down",
        }
    return max(
        rides,
        key=lambda ride: (
            100 if ride.get("status") == "down" else 30 if ride.get("status") == "constrained" else 0,
            _as_int(ride.get("downtimeRisk")),
            _as_int(ride.get("queueGuests")),
            _as_int(ride.get("waitMins")),
        ),
    )


def _scenario_key(state: dict[str, Any]) -> str:
    scenario = _flow(state).get("activeScenario", {})
    return str((scenario if isinstance(scenario, dict) else {}).get("key") or "ride_down")


def _normalize_action(action_plan: dict[str, Any] | None) -> dict[str, Any]:
    plan = action_plan if isinstance(action_plan, dict) else {}
    selected = plan.get("selected_action") if isinstance(plan.get("selected_action"), dict) else {}
    park_action = selected.get("park_action") if isinstance(selected.get("park_action"), dict) else {}
    if not selected and isinstance(plan.get("park_action"), dict):
        park_action = plan["park_action"]
    target = str(selected.get("target") or park_action.get("target") or plan.get("target") or "none")
    action = str(selected.get("action") or park_action.get("action") or plan.get("action") or "natural")
    return {
        "target": target,
        "action": action,
        "label": selected.get("label") or plan.get("label") or f"{target}/{action}",
        "plan": plan,
    }


def _default_target_mix(state: dict[str, Any]) -> list[dict[str, Any]]:
    rides = [ride for ride in _rides(state) if ride.get("status") != "down"]
    if rides:
        ranked = sorted(rides, key=lambda ride: (_as_int(ride.get("waitMins")), -_as_int(ride.get("capacityPerHour"))))
        shares = [0.32, 0.22, 0.16]
        return [
            {
                "zoneId": ride.get("zone"),
                "destination": ride.get("name"),
                "share": shares[index],
                "currentWaitMins": ride.get("waitMins", 0),
            }
            for index, ride in enumerate(ranked[:3])
        ]
    return [
        {"zoneId": "indoorHub", "destination": "Indoor Ride Hub", "share": 0.34, "currentWaitMins": 32},
        {"zoneId": "arcadeZone", "destination": "Arcade Zone", "share": 0.24, "currentWaitMins": 10},
        {"zoneId": "coveredPlaza", "destination": "Covered Plaza", "share": 0.16, "currentWaitMins": 8},
    ]


def _target_mix(action_plan: dict[str, Any] | None, state: dict[str, Any]) -> list[dict[str, Any]]:
    plan = action_plan if isinstance(action_plan, dict) else {}
    action_mix = plan.get("action_mix", {}) if isinstance(plan.get("action_mix"), dict) else {}
    reroute = action_mix.get("guest_reroute", {}) if isinstance(action_mix.get("guest_reroute"), dict) else {}
    raw_targets = reroute.get("target_mix", []) if isinstance(reroute.get("target_mix"), list) else []
    targets = [target for target in raw_targets if isinstance(target, dict)]
    return targets or _default_target_mix(state)


def _action_mix(action_plan: dict[str, Any] | None) -> dict[str, Any]:
    plan = action_plan if isinstance(action_plan, dict) else {}
    action_mix = plan.get("action_mix", {}) if isinstance(plan.get("action_mix"), dict) else {}
    return action_mix


def _guest_reroute_mix(action_plan: dict[str, Any] | None) -> dict[str, Any]:
    reroute = _action_mix(action_plan).get("guest_reroute", {})
    return reroute if isinstance(reroute, dict) else {}


def _reroute_requested(action_plan: dict[str, Any] | None, normalized: dict[str, Any]) -> bool:
    reroute = _guest_reroute_mix(action_plan)
    has_targets = isinstance(reroute.get("target_mix"), list) and bool(reroute.get("target_mix"))
    explicit = normalized["target"] in {"ride", "traffic", "queue_gate"} and normalized["action"] in {
        "reroute",
        "redirect_food",
        "staged_reroute",
        "hold_intake",
    }
    return explicit or bool(reroute.get("enabled") and has_targets)


def _staff_requested(action_plan: dict[str, Any] | None, normalized: dict[str, Any]) -> bool:
    staffing = _action_mix(action_plan).get("staffing", {})
    moves = staffing.get("move_staff") if isinstance(staffing, dict) else None
    return (
        normalized["target"] == "staff"
        and normalized["action"] in {"redeploy", "redeploy_food_certified"}
    ) or (isinstance(moves, list) and bool(moves))


def _food_requested(action_plan: dict[str, Any] | None, normalized: dict[str, Any]) -> bool:
    food = _action_mix(action_plan).get("food", {})
    suppress = food.get("suppressItems") if isinstance(food, dict) else None
    avoid = food.get("avoidExtraDemandAt") if isinstance(food, dict) else None
    return (
        normalized["target"] == "food"
        and normalized["action"] in {
            "suppress_item",
            "pause_mobile_order_intake",
            "open_temp_pickup",
            "open_satellite_cart",
            "throttle_mobile_pickup_windows",
        }
    ) or (isinstance(suppress, list) and bool(suppress)) or (isinstance(avoid, list) and bool(avoid))


def _queue_gate_requested(action_plan: dict[str, Any] | None, normalized: dict[str, Any]) -> bool:
    controls = _action_mix(action_plan).get("controls", {})
    gates = controls.get("queue_gates", []) if isinstance(controls, dict) and isinstance(controls.get("queue_gates"), list) else []
    return (normalized["target"] == "queue_gate" and normalized["action"] == "hold_intake") or bool(gates)


def _energy_requested(action_plan: dict[str, Any] | None, normalized: dict[str, Any]) -> bool:
    facilities = _action_mix(action_plan).get("facilities", {})
    hvac = facilities.get("hvac") if isinstance(facilities, dict) else None
    return (normalized["target"] == "energy" and normalized["action"] == "protect_hvac") or (
        isinstance(hvac, dict) and bool(hvac.get("protectShelterComfort"))
    )


def _reroute_active_minutes(action_plan: dict[str, Any] | None, normalized: dict[str, Any], horizon_minutes: int) -> int:
    if not _reroute_requested(action_plan, normalized):
        return 5
    reroute = _guest_reroute_mix(action_plan)
    controls = _action_mix(action_plan).get("controls", {})
    gates = controls.get("queue_gates", []) if isinstance(controls, dict) and isinstance(controls.get("queue_gates"), list) else []
    gate_hold = max((_as_int((gate.get("settings", {}) if isinstance(gate, dict) else {}).get("holdMinutes"), 0) for gate in gates), default=0)
    duration = _as_int(reroute.get("durationMinutes") or reroute.get("expiresMinutes"), 0) or gate_hold or 15
    return max(5, min(horizon_minutes, duration))


def _reroute_only_action_plan(action_plan: dict[str, Any] | None, normalized: dict[str, Any]) -> dict[str, Any]:
    reroute = deepcopy(_guest_reroute_mix(action_plan))
    return {
        "target": "ride",
        "action": "reroute",
        "label": normalized.get("label") or "Persistent guest reroute",
        "action_mix": {"guest_reroute": reroute} if reroute else {},
    }


def _recompute_zone(zone: dict[str, Any], heat_index: int = 92, storm_risk: int = 0) -> None:
    area_sqm = _as_float(zone.get("areaSqM"))
    capacity = _space_capacity(area_sqm, _as_int(zone.get("capacity"), 1))
    zone["capacity"] = capacity
    if area_sqm > 0:
        zone["densityGuestsPerSqM"] = round(_as_int(zone.get("currentGuests")) / area_sqm, 2)
    guests = _as_int(zone.get("currentGuests"))
    density = round((guests / capacity) * 100)
    zone["density"] = _bounded(density, 0, 125)
    crowd_penalty = max(0, zone["density"] - 62) * 0.55
    weather_penalty = 6 if zone.get("flowType") == "outdoor" and (heat_index >= 98 or storm_risk >= 65) else 0
    zone["comfortScore"] = round(_bounded(94 - crowd_penalty - weather_penalty, 20, 96))
    zone["waitMins"] = max(0, round(_as_int(zone.get("waitMins")) * 0.58 + max(0, zone["density"] - 55) * 0.42))


def _recompute_ride(ride: dict[str, Any], minutes: int, intake_factor: float = 1.0) -> None:
    queue = _as_int(ride.get("queueGuests"))
    status = str(ride.get("status", "normal"))
    effective = _as_int(ride.get("effectiveThroughput"))
    capacity = max(1, _as_int(ride.get("capacityPerHour"), effective or 1))
    staff_required = max(1, _as_int(ride.get("staffRequired"), 1))
    staff_available = _as_int(ride.get("staffAvailable"), staff_required)
    staff_ratio = _bounded(staff_available / staff_required, 0.2, 1.1)

    if status == "down":
        queue = max(0, queue + round(4 * minutes * intake_factor))
        ride["waitMins"] = max(_as_int(ride.get("waitMins")), round(queue / 11))
        ride["throughputGap"] = capacity
    else:
        if status == "constrained":
            effective = max(1, round(effective * 0.82))
        processed = round((effective / 60) * minutes * staff_ratio)
        arrivals = round((capacity / 60) * minutes * 0.28 * intake_factor)
        queue = max(0, queue - processed + arrivals)
        ride["waitMins"] = round((queue / max(1, effective)) * 60)
        ride["throughputGap"] = max(0, capacity - round(effective * staff_ratio))
        if staff_ratio < 0.85 or ride["waitMins"] >= 48:
            ride["status"] = "constrained"
    ride["queueGuests"] = queue


def _apply_reroute(state: dict[str, Any], action_plan: dict[str, Any] | None, minutes: int, rng: random.Random) -> dict[str, Any]:
    zones = _zones(state)
    rides = _rides(state)
    zone_by_id = _by_id(zones)
    ride = _primary_ride(state)
    origin = zone_by_id.get(str(ride.get("zone")))
    targets = _target_mix(action_plan, state)
    plan = action_plan if isinstance(action_plan, dict) else {}
    projected = plan.get("projected_impact", {}) if isinstance(plan.get("projected_impact"), dict) else {}
    action_mix = plan.get("action_mix", {}) if isinstance(plan.get("action_mix"), dict) else {}
    reroute = action_mix.get("guest_reroute", {}) if isinstance(action_mix.get("guest_reroute"), dict) else {}
    expected_take_rate = _as_float(reroute.get("expectedTakeRate"), 0.34)
    normalized = _normalize_action(action_plan)
    if normalized["action"] == "staged_reroute":
        expected_take_rate = _as_float(reroute.get("expectedTakeRate"), 0.28)
    if normalized["action"] == "hold_intake":
        expected_take_rate = _as_float(reroute.get("expectedTakeRate"), 0.18)
    if not reroute and projected:
        expected_take_rate = _bounded(_as_float(projected.get("movedGuests"), 360) / max(1, _as_int(ride.get("queueGuests"), 700)), 0.18, 0.58)
    take_rate = _bounded(expected_take_rate + rng.uniform(-0.05, 0.05), 0.14, 0.62)
    queued = _as_int(ride.get("queueGuests"), 500)
    moved = min(queued, round(queued * take_rate * _bounded(minutes / 18, 0.35, 1.25)))
    hold = max(0, queued - moved)
    ride["queueGuests"] = hold
    ride["waitMins"] = max(0, _as_int(ride.get("waitMins")) - round(moved / 42))

    if origin:
        origin["currentGuests"] = max(0, _as_int(origin.get("currentGuests")) - moved)

    total_share = sum(max(0, _as_float(target.get("share"))) for target in targets) or 1.0
    overloaded: list[str] = []
    for target in targets:
        zone_id = str(target.get("zoneId") or target.get("zone") or target.get("destinationId") or "")
        target_zone = zone_by_id.get(zone_id)
        if not target_zone:
            continue
        share = max(0, _as_float(target.get("share"))) / total_share
        added = round(moved * share)
        target_zone["currentGuests"] = _as_int(target_zone.get("currentGuests")) + added
        if (_as_int(target_zone.get("currentGuests")) / max(1, _as_int(target_zone.get("capacity"), 1))) >= 0.94:
            overloaded.append(str(target_zone.get("name") or zone_id))

    for path in _paths(state):
        if path.get("from") == str(ride.get("zone")) or path.get("to") in {target.get("zoneId") for target in targets}:
            path_increment = round(moved / (10 if normalized["action"] in {"staged_reroute", "hold_intake"} else 7))
            path["currentGuests"] = _as_int(path.get("currentGuests")) + path_increment
            path["congestionLevel"] = _bounded(round((_as_int(path.get("currentGuests")) / max(1, _as_int(path.get("capacity"), 1))) * 100), 0, 125)
            path["status"] = "congested" if path["congestionLevel"] >= 88 else "busy" if path["congestionLevel"] >= 65 else "open"

    return {"moved_guests": moved, "overloaded_targets": overloaded, "take_rate": round(take_rate, 3)}


def _apply_queue_gate(state: dict[str, Any], action_plan: dict[str, Any] | None, minutes: int) -> dict[str, Any]:
    ride = _primary_ride(state)
    hold_minutes = min(20, max(5, _reroute_active_minutes(action_plan, _normalize_action(action_plan), minutes)))
    queue_before = _as_int(ride.get("queueGuests"))
    prevented = round(hold_minutes * 9)
    ride["queueGuests"] = max(0, queue_before - round(prevented * 0.35))
    ride["waitMins"] = max(0, _as_int(ride.get("waitMins")) - round(prevented / 55))
    ride["intakeHoldActive"] = True
    ride["intakeHoldMinutes"] = hold_minutes
    for zone in _zones(state):
        if zone.get("id") == ride.get("zone"):
            zone["currentGuests"] = max(0, _as_int(zone.get("currentGuests")) - round(prevented * 0.28))
            zone["comfortScore"] = _bounded(_as_int(zone.get("comfortScore")) + 4, 20, 96)
    return {"queue_intake_hold_minutes": hold_minutes, "queue_arrivals_prevented": prevented}


def _apply_staff_action(state: dict[str, Any], normalized: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = normalized or {}
    staffing = state.get("staffing", {}) if isinstance(state.get("staffing"), dict) else {}
    food_certified = normalized.get("action") == "redeploy_food_certified"
    staffing["checkedIn"] = min(_as_int(staffing.get("scheduled"), 214), _as_int(staffing.get("checkedIn"), 190) + (3 if food_certified else 2))
    impacted = 0
    if not food_certified:
        for ride in _rides(state):
            if ride.get("status") in {"down", "constrained"} and impacted < 2:
                ride["staffAvailable"] = min(_as_int(ride.get("staffRequired"), 1), _as_int(ride.get("staffAvailable")) + 1)
                impacted += 1
    food = state.get("foodInventory", {}) if isinstance(state.get("foodInventory"), dict) else {}
    if food_certified:
        food["foodCertifiedRedeploy"] = True
        for location in food.get("locations", []) if isinstance(food.get("locations"), list) else []:
            if location.get("id") == "foodCourt1":
                before = _as_int(location.get("mobileOrderBacklog"))
                location["mobileOrderBacklog"] = max(0, before - 120)
                location["pickupEtaMinutes"] = max(6, _as_int(location.get("pickupEtaMinutes")) - 22)
                impacted += 2
    for zone in _zones(state):
        if zone.get("id") in {"coasterPlaza", "foodCourt1"}:
            zone["waitMins"] = max(0, _as_int(zone.get("waitMins")) - (9 if food_certified and zone.get("id") == "foodCourt1" else 4))
            zone["comfortScore"] = _bounded(_as_int(zone.get("comfortScore")) + (8 if food_certified and zone.get("id") == "foodCourt1" else 5), 20, 96)
    return {"staff_added_to_pressure": impacted, "food_certified_redeploy": food_certified}


def _apply_food_action(state: dict[str, Any], normalized: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = normalized or {}
    action = str(normalized.get("action") or "suppress_item")
    food = state.get("foodInventory", {}) if isinstance(state.get("foodInventory"), dict) else {}
    suppressed = set(food.get("suppressedItems", []) if isinstance(food.get("suppressedItems"), list) else [])
    suppressed.update({"chicken_tenders", "bottled_drinks"})
    if action == "pause_mobile_order_intake":
        suppressed.add("mobile_order_intake")
        food["mobileOrderIntakePaused"] = True
    if action == "open_temp_pickup":
        suppressed.add("low_throughput_pickup_lane")
        food["tempPickupOpen"] = True
    if action == "open_satellite_cart":
        suppressed.add("satellite_cart_active")
        food["satelliteCartOpen"] = True
    if action == "throttle_mobile_pickup_windows":
        suppressed.add("pickup_window_throttle")
        food["pickupWindowThrottle"] = True
    food["suppressedItems"] = sorted(suppressed)
    reduced_backlog = 0
    for location in food.get("locations", []) if isinstance(food.get("locations"), list) else []:
        if location.get("id") == "foodCourt1":
            before = _as_int(location.get("mobileOrderBacklog"))
            backlog_delta = 42
            eta_delta = 8
            if action == "pause_mobile_order_intake":
                backlog_delta = 120
                eta_delta = 24
            elif action == "open_temp_pickup":
                backlog_delta = 220
                eta_delta = 36
            elif action == "open_satellite_cart":
                backlog_delta = 260
                eta_delta = 32
            elif action == "throttle_mobile_pickup_windows":
                backlog_delta = 160
                eta_delta = 24
            location["mobileOrderBacklog"] = max(0, before - backlog_delta)
            location["pickupEtaMinutes"] = max(5, _as_int(location.get("pickupEtaMinutes")) - eta_delta)
            reduced_backlog = before - location["mobileOrderBacklog"]
    for zone in _zones(state):
        if zone.get("id") == "foodCourt1":
            removed = (
                260
                if action == "open_satellite_cart"
                else 220
                if action == "open_temp_pickup"
                else 190
                if action == "throttle_mobile_pickup_windows"
                else 170
                if action == "pause_mobile_order_intake"
                else 110
            )
            zone["currentGuests"] = max(0, _as_int(zone.get("currentGuests")) - removed)
            zone["comfortScore"] = _bounded(_as_int(zone.get("comfortScore")) + (8 if action == "open_satellite_cart" else 5), 20, 96)
    return {"food_backlog_reduced": reduced_backlog, "food_action": action}


def _apply_energy_action(state: dict[str, Any]) -> dict[str, Any]:
    energy = state.get("energy", {}) if isinstance(state.get("energy"), dict) else {}
    energy["gridLoadPercent"] = min(99, _as_int(energy.get("gridLoadPercent"), 90) + 2)
    energy["demandChargeRisk"] = "elevated" if energy["gridLoadPercent"] < 94 else "critical"
    protected = 0
    for zone in _zones(state):
        if zone.get("flowType") == "indoor":
            zone["comfortScore"] = _bounded(_as_int(zone.get("comfortScore")) + 7, 20, 96)
            protected += _as_int(zone.get("currentGuests"))
    return {"comfort_protected_guests": protected}


def _zone_from_destination(destination: str, zone_by_name: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    normalized = destination.strip().lower()
    aliases = {
        "dragon coaster": "coaster plaza",
        "sky drop": "coaster plaza",
        "indoor launch": "indoor ride hub",
        "indoor ride hub": "indoor ride hub",
        "food court a": "food court 1",
        "food court b": "food court 1",
        "covered plaza": "covered plaza",
        "theater b": "arcade zone",
        "arcade": "arcade zone",
        "arcade zone": "arcade zone",
        "shade garden": "covered plaza",
        "front gate": "entrance plaza",
        "fireworks viewing": "covered plaza",
        "parade route": "covered plaza",
    }
    return zone_by_name.get(aliases.get(normalized, normalized))


def _path_between(paths: list[dict[str, Any]], from_zone: str, to_zone: str) -> dict[str, Any] | None:
    return next(
        (
            path
            for path in paths
            if {str(path.get("from") or ""), str(path.get("to") or "")} == {from_zone, to_zone}
        ),
        None,
    )


def _apply_physical_dynamics(state: dict[str, Any], action_meta: dict[str, Any], minutes: int, rng: random.Random) -> dict[str, Any]:
    zones = _zones(state)
    paths = _paths(state)
    rides = _rides(state)
    physical = _physical(state)
    groups = _guest_groups(state)
    queues = _queues(state)
    zone_by_id = _by_id(zones)
    zone_by_name = {str(zone.get("name", "")).lower(): zone for zone in zones}
    route_moves: list[dict[str, Any]] = []
    spillbacks: list[dict[str, Any]] = []
    service_updates: list[dict[str, Any]] = []
    staff_tasks: list[dict[str, Any]] = []
    blocked_paths = 0
    total_moved = 0

    for group in groups:
        origin = zone_by_id.get(str(group.get("zoneId") or "")) or zone_by_name.get(str(group.get("origin") or "").lower())
        if not origin:
            x = _as_int(group.get("x"))
            if x >= 610:
                origin = zone_by_id.get("foodCourt1") if _as_int(group.get("y")) >= 420 else zone_by_id.get("coasterPlaza")
            elif x <= 360:
                origin = zone_by_id.get("entrancePlaza") or zone_by_id.get("indoorHub")
            else:
                origin = zone_by_id.get("coveredPlaza")
        destination = _zone_from_destination(str(group.get("destination") or ""), zone_by_name)
        if not origin or not destination or origin.get("id") == destination.get("id"):
            continue
        count = _as_int(group.get("count"))
        pace = str(group.get("pace") or "medium")
        pace_factor = {"stopped": 0.02, "slow": 0.08, "medium": 0.14, "fast": 0.22, "working": 0.06}.get(pace, 0.12)
        route = _path_between(paths, str(origin.get("id")), str(destination.get("id")))
        route_capacity = max(1, _as_int((route or {}).get("capacity"), 700))
        flow_capacity = _path_flow_capacity(route or {}, minutes)
        route_load = _as_int((route or {}).get("currentGuests"), 0)
        available = max(0, route_capacity - route_load)
        desired = round(count * pace_factor * _bounded(minutes / 5, 0.25, 2.0))
        moved = min(count, desired, flow_capacity, max(0, round(available * 0.32)))
        if route and route_load >= route_capacity * 0.98:
            blocked_paths += 1
            group["pace"] = "stopped"
            group["mood"] = "blocked_path"
        if moved <= 0:
            continue
        group["count"] = max(0, count - moved)
        origin["currentGuests"] = max(0, _as_int(origin.get("currentGuests")) - moved)
        destination["currentGuests"] = _as_int(destination.get("currentGuests")) + moved
        if route:
            route["currentGuests"] = route_load + moved
            route["forwardTransfers"] = _as_int(route.get("forwardTransfers")) + moved
            route["flowCapacityThisTick"] = flow_capacity
            route["widthUtilizationPct"] = round(_bounded((moved / max(1, flow_capacity)) * 100, 0, 140))
            route["congestionLevel"] = round(_bounded((route["currentGuests"] / route_capacity) * 100, 0, 125))
            route["status"] = "congested" if route["congestionLevel"] >= 88 else "busy" if route["congestionLevel"] >= 65 else "open"
        total_moved += moved
        route_moves.append(
            {
                "groupId": group.get("id"),
                "from": origin.get("id"),
                "to": destination.get("id"),
                "guests": moved,
                "pathId": f"{origin.get('id')}->{destination.get('id')}",
                "flowCapacity": flow_capacity,
                "widthM": (route or {}).get("widthM"),
                "lengthM": (route or {}).get("lengthM"),
            }
        )

    for queue in queues:
        ride_id = str(queue.get("rideId") or "")
        ride = next((item for item in rides if item.get("id") == ride_id), None)
        if ride:
            queue["guests"] = _as_int(ride.get("queueGuests"))
            queue["waitMins"] = _as_int(ride.get("waitMins"))
        guests = _as_int(queue.get("guests"))
        queue_length_m = _as_float(queue.get("lengthM"))
        guest_spacing_m = max(0.45, _as_float(queue.get("guestSpacingM"), 0.75))
        physical_queue_m = guests * guest_spacing_m
        queue["physicalQueueM"] = round(physical_queue_m)
        queue["queueLengthUtilizationPct"] = round(_bounded((physical_queue_m / max(1, queue_length_m)) * 100, 0, 180)) if queue_length_m > 0 else None
        if guests >= 650 or _as_int(queue.get("waitMins")) >= 55 or (queue_length_m > 0 and physical_queue_m > queue_length_m):
            queue["spillbackRisk"] = "critical"
            spatial_spill = round(max(0, physical_queue_m - queue_length_m) / guest_spacing_m) if queue_length_m > 0 else 0
            spill = max(round(max(0, guests - 540) * 0.18), spatial_spill)
            zone_id = "coasterPlaza" if ride_id == "dragonCoaster" else "indoorHub" if ride_id == "indoorLaunch" else "foodCourt1"
            if zone_id in zone_by_id and spill:
                zone_by_id[zone_id]["currentGuests"] = _as_int(zone_by_id[zone_id].get("currentGuests")) + spill
            spillbacks.append({
                "queueId": queue.get("id"),
                "zoneId": zone_id,
                "spillGuests": spill,
                "risk": queue["spillbackRisk"],
                "physicalQueueM": round(physical_queue_m),
                "queueLengthM": queue_length_m or None,
            })

    food = state.get("foodInventory", {}) if isinstance(state.get("foodInventory"), dict) else {}
    staffing = state.get("staffing", {}) if isinstance(state.get("staffing"), dict) else {}
    staff_ready = max(1, _as_int(staffing.get("checkedIn"), 190) - _as_int(staffing.get("openCallouts"), 0))
    for location in food.get("locations", []) if isinstance(food.get("locations"), list) else []:
        backlog = _as_int(location.get("mobileOrderBacklog"))
        runners = max(1, round(staff_ready / 58))
        throughput = round((18 + runners * 5) * _bounded(minutes / 5, 0.2, 2.0))
        arrivals = round((12 if location.get("id") == "foodCourt1" else 7) * _bounded(minutes / 5, 0.2, 2.0))
        if food.get("suppressedItems"):
            arrivals = max(0, arrivals - 10)
        if food.get("mobileOrderIntakePaused"):
            arrivals = max(0, arrivals - round(24 * _bounded(minutes / 5, 0.2, 2.0)))
        if food.get("tempPickupOpen"):
            throughput += round(36 * _bounded(minutes / 5, 0.2, 2.0))
        if food.get("foodCertifiedRedeploy"):
            throughput += round(22 * _bounded(minutes / 5, 0.2, 2.0))
        next_backlog = max(0, backlog + arrivals - throughput)
        location["mobileOrderBacklog"] = next_backlog
        location["pickupEtaMinutes"] = max(5, round(next_backlog / max(1, runners * 3)))
        service_updates.append({"locationId": location.get("id"), "arrivals": arrivals, "throughput": throughput, "backlog": next_backlog})

    if action_meta.get("staff_added_to_pressure"):
        for index in range(int(action_meta["staff_added_to_pressure"])):
            staff_tasks.append(
                {
                    "taskId": f"redeploy_{index + 1}",
                    "from": "break_pool",
                    "to": "coasterPlaza" if index == 0 else "foodCourt1",
                    "travelMinutes": 4 + index * 3,
                    "ackDelaySeconds": 20 + index * 15,
                    "status": "arriving" if minutes >= 5 + index * 3 else "in_transit",
                }
            )

    for zone in zones:
        _recompute_zone(zone, _as_int((state.get("weather", {}) if isinstance(state.get("weather"), dict) else {}).get("heatIndexF"), 92), _as_int((state.get("weather", {}) if isinstance(state.get("weather"), dict) else {}).get("stormRisk"), 0))

    dynamics = {
        "mode": "physical_guest_staff_service_dynamics",
        "minutes": minutes,
        "routeMoves": route_moves[:12],
        "totalMovedGuests": total_moved,
        "blockedPathCount": blocked_paths,
        "spatialModel": {
            "zoneAreasSqM": {zone.get("id"): zone.get("areaSqM") for zone in zones if isinstance(zone, dict)},
            "pathWidthsM": {f"{path.get('from')}->{path.get('to')}": path.get("widthM") for path in paths if isinstance(path, dict)},
            "pathLengthsM": {f"{path.get('from')}->{path.get('to')}": path.get("lengthM") for path in paths if isinstance(path, dict)},
            "queueLengthsM": {queue.get("id"): queue.get("lengthM") for queue in queues if isinstance(queue, dict)},
        },
        "queueSpillbacks": spillbacks[:8],
        "foodService": service_updates[:6],
        "staffTasks": staff_tasks,
        "physicalConstraints": [
            "Guest groups move only along mapped paths with width, length, capacity, and flow limits.",
            "Queues spill into zones when physical queue length exceeds designed queue meters.",
            "Food backlog is generated from arrivals minus throughput, not a static number.",
            "Staff actions have travel and acknowledgement latency.",
        ],
    }
    state["physicalDynamics"] = dynamics
    physical["lastDynamics"] = dynamics
    state["physicalMap"] = physical
    return dynamics


def _evolve_natural(state: dict[str, Any], minutes: int, rng: random.Random, reroute_active: bool = False) -> None:
    weather = state.get("weather", {}) if isinstance(state.get("weather"), dict) else {}
    storm_risk = _as_int(weather.get("stormRisk"))
    heat_index = _as_int(weather.get("heatIndexF"), 92)
    weather["stormRisk"] = round(_bounded(storm_risk + rng.uniform(-2, 4) * (minutes / 10), 0, 98))

    for ride in _rides(state):
        _recompute_ride(ride, minutes, intake_factor=0.35 if reroute_active else 1.0)

    for zone in _zones(state):
        drift = round((_as_int(zone.get("density")) - 72) * 0.018 * minutes)
        if zone.get("flowType") == "outdoor" and weather["stormRisk"] >= 65:
            drift += round(5 * minutes)
        if zone.get("flowType") == "indoor" and weather["stormRisk"] >= 65:
            drift += round(9 * minutes)
        zone["currentGuests"] = max(0, _as_int(zone.get("currentGuests")) + drift)
        _recompute_zone(zone, heat_index, weather["stormRisk"])

    for path in _paths(state):
        congestion = _as_int(path.get("congestionLevel"))
        flow_capacity = _path_flow_capacity(path, minutes)
        path["flowCapacityThisTick"] = flow_capacity
        path["congestionLevel"] = round(_bounded(congestion + rng.uniform(-3, 5) * (minutes / 5), 0, 125))
        path["densityGuestsPerMeter"] = round(_as_int(path.get("currentGuests")) / max(1, _as_float(path.get("lengthM"), 100)), 2)
        path["status"] = "congested" if path["congestionLevel"] >= 88 else "busy" if path["congestionLevel"] >= 65 else "open"

    food = state.get("foodInventory", {}) if isinstance(state.get("foodInventory"), dict) else {}
    for location in food.get("locations", []) if isinstance(food.get("locations"), list) else []:
        growth = round((14 if location.get("id") == "foodCourt1" else 5) * (minutes / 5))
        if location.get("id") == "foodCourt1" and food.get("mobileOrderIntakePaused"):
            growth = -round(32 * (minutes / 5))
        elif location.get("id") == "foodCourt1" and food.get("satelliteCartOpen"):
            growth = -round(34 * (minutes / 5))
        elif location.get("id") == "foodCourt1" and food.get("tempPickupOpen"):
            growth = -round(28 * (minutes / 5))
        elif location.get("id") == "foodCourt1" and food.get("pickupWindowThrottle"):
            growth = -round(24 * (minutes / 5))
        elif location.get("id") == "foodCourt1" and food.get("foodCertifiedRedeploy"):
            growth = -round(22 * (minutes / 5))
        elif location.get("id") == "foodCourt1" and food.get("suppressedItems"):
            growth = -round(18 * (minutes / 5))
        location["mobileOrderBacklog"] = max(0, _as_int(location.get("mobileOrderBacklog")) + growth)
        location["pickupEtaMinutes"] = max(6, round(_as_int(location.get("pickupEtaMinutes")) + growth / 8))

    indoor_guests = sum(_as_int(zone.get("currentGuests")) for zone in _zones(state) if zone.get("flowType") == "indoor")
    energy = state.get("energy", {}) if isinstance(state.get("energy"), dict) else {}
    energy["gridLoadPercent"] = round(_bounded(72 + indoor_guests / 190 + max(0, heat_index - 90) * 0.8, 45, 99))


def _refresh_summary(state: dict[str, Any]) -> None:
    zones = _zones(state)
    represented = sum(_as_int(zone.get("currentGuests")) for zone in zones)
    avg_satisfaction = round(sum(_as_int(zone.get("comfortScore")) for zone in zones) / max(1, len(zones)))
    flow = _flow(state)
    flow["representedGuests"] = represented
    flow["avgSatisfaction"] = avg_satisfaction
    flow["activeGroups"] = round(represented / 8)
    park_ops = state.get("parkOps", {}) if isinstance(state.get("parkOps"), dict) else {}
    park_ops["rideConflictCount"] = sum(1 for ride in _rides(state) if ride.get("status") != "normal")
    park_ops["atRiskRides"] = sum(1 for ride in _rides(state) if _as_int(ride.get("downtimeRisk")) >= 30)
    park_ops["guestRecoveryPressure"] = max(50, 100 - avg_satisfaction)
    state["parkOps"] = park_ops
    readiness = state.get("incidentReadiness", {}) if isinstance(state.get("incidentReadiness"), dict) else {}
    readiness["highestZoneDensity"] = max((_as_int(zone.get("density")) for zone in zones), default=0)
    readiness["operatorEscalation"] = "required" if readiness["highestZoneDensity"] >= 95 else "watch"


def state_digest(state: dict[str, Any]) -> dict[str, Any]:
    zones = _zones(state)
    rides = _rides(state)
    paths = _paths(state)
    food = state.get("foodInventory", {}) if isinstance(state.get("foodInventory"), dict) else {}
    locations = food.get("locations", []) if isinstance(food.get("locations"), list) else []
    busiest = max(zones, key=lambda zone: _as_int(zone.get("density")), default={})
    slowest = max(rides, key=lambda ride: _as_int(ride.get("waitMins")), default={})
    path = max(paths, key=lambda item: _as_int(item.get("congestionLevel")), default={})
    food_a = next((item for item in locations if item.get("id") == "foodCourt1"), {})
    staffing = state.get("staffing", {}) if isinstance(state.get("staffing"), dict) else {}
    return {
        "scenario_key": _scenario_key(state),
        "represented_guests": _flow(state).get("representedGuests", 0),
        "avg_satisfaction": _flow(state).get("avgSatisfaction", 0),
        "busiest_zone": {"id": busiest.get("id"), "name": busiest.get("name"), "density": busiest.get("density")},
        "slowest_ride": {
            "id": slowest.get("id"),
            "name": slowest.get("name"),
            "status": slowest.get("status"),
            "waitMins": slowest.get("waitMins"),
            "queueGuests": slowest.get("queueGuests"),
        },
        "most_congested_path": {
            "from": path.get("fromName"),
            "to": path.get("toName"),
            "congestionLevel": path.get("congestionLevel"),
        },
        "food_backlog": food_a.get("mobileOrderBacklog", 0),
        "food_eta_minutes": food_a.get("pickupEtaMinutes", 0),
        "open_callouts": staffing.get("openCallouts", 0),
        "grid_load": (state.get("energy", {}) if isinstance(state.get("energy"), dict) else {}).get("gridLoadPercent", 0),
        "storm_risk": (state.get("weather", {}) if isinstance(state.get("weather"), dict) else {}).get("stormRisk", 0),
    }


def score_outcome(before: dict[str, Any], after: dict[str, Any], action_plan: dict[str, Any] | None = None) -> dict[str, Any]:
    before_digest = state_digest(before)
    after_digest = state_digest(after)
    density_delta = _as_int(after_digest.get("busiest_zone", {}).get("density")) - _as_int(before_digest.get("busiest_zone", {}).get("density"))
    wait_delta = _as_int(after_digest.get("slowest_ride", {}).get("waitMins")) - _as_int(before_digest.get("slowest_ride", {}).get("waitMins"))
    satisfaction_delta = _as_int(after_digest.get("avg_satisfaction")) - _as_int(before_digest.get("avg_satisfaction"))
    food_delta = _as_int(after_digest.get("food_backlog")) - _as_int(before_digest.get("food_backlog"))
    path_delta = _as_int(after_digest.get("most_congested_path", {}).get("congestionLevel")) - _as_int(before_digest.get("most_congested_path", {}).get("congestionLevel"))
    callout_delta = _as_int(after_digest.get("open_callouts")) - _as_int(before_digest.get("open_callouts"))
    grid_delta = _as_int(after_digest.get("grid_load")) - _as_int(before_digest.get("grid_load"))
    storm_delta = _as_int(after_digest.get("storm_risk")) - _as_int(before_digest.get("storm_risk"))
    before_care = before.get("guestCare", {}) if isinstance(before.get("guestCare"), dict) else {}
    after_care = after.get("guestCare", {}) if isinstance(after.get("guestCare"), dict) else {}
    care_delta = _as_int(after_care.get("openCases")) - _as_int(before_care.get("openCases"))
    safety_violations = 0
    if any(_as_int(zone.get("density")) >= 102 for zone in _zones(after)):
        safety_violations += 1
    if any(ride.get("status") == "down" and _as_int(ride.get("effectiveThroughput")) > 0 for ride in _rides(after)):
        safety_violations += 1
    if after.get("incidentReadiness", {}).get("emergencyAccessBlocked"):
        safety_violations += 1
    critical_density_excess = max((_as_int(zone.get("density")) - 100 for zone in _zones(after)), default=0)
    score = round(
        76
        + max(0, -density_delta) * 0.55
        - max(0, density_delta) * 0.65
        + max(0, -wait_delta) * 0.42
        - max(0, wait_delta) * 0.25
        + satisfaction_delta * 1.5
        + max(0, -food_delta) * 0.08
        - max(0, food_delta) * 0.04
        - max(0, path_delta) * 0.45
        - max(0, callout_delta) * 0.9
        - max(0, care_delta) * 1.1
        - max(0, grid_delta) * 0.35
        - max(0, storm_delta) * 0.18
        - max(0, critical_density_excess) * 0.8
        - safety_violations * 18
    )
    return {
        "overall": round(_bounded(score, 0, 100)),
        "metrics": {
            "busiest_zone_density_delta": density_delta,
            "slowest_ride_wait_delta": wait_delta,
            "avg_satisfaction_delta": satisfaction_delta,
            "food_backlog_delta": food_delta,
            "path_congestion_delta": path_delta,
            "staff_callout_delta": callout_delta,
            "guest_care_case_delta": care_delta,
            "grid_load_delta": grid_delta,
            "storm_risk_delta": storm_delta,
            "safety_violations": safety_violations,
            "critical_density_excess": max(0, critical_density_excess),
        },
        "before": before_digest,
        "after": after_digest,
        "action": _normalize_action(action_plan),
    }


def transition_state(
    state: dict[str, Any],
    action_plan: dict[str, Any] | None = None,
    minutes: int = 5,
    seed: str | None = None,
    stochastic: bool = True,
) -> dict[str, Any]:
    next_state = deepcopy(state)
    safe_minutes = max(1, min(60, _as_int(minutes, 5)))
    rng = random.Random(seed or f"{_scenario_key(state)}:{safe_minutes}:{_normalize_action(action_plan)['label']}")
    if stochastic:
        rng.seed((seed or "") + str(rng.random()))
    normalized = _normalize_action(action_plan)
    action_meta: dict[str, Any] = {}

    if _reroute_requested(action_plan, normalized):
        action_meta.update(_apply_reroute(next_state, action_plan, safe_minutes, rng))
        _flow(next_state)["activePolicy"] = normalized["action"]
    if _queue_gate_requested(action_plan, normalized):
        action_meta.update(_apply_queue_gate(next_state, action_plan, safe_minutes))
        _flow(next_state)["activePolicy"] = normalized["action"]
    if _staff_requested(action_plan, normalized):
        action_meta.update(_apply_staff_action(next_state, normalized))
        _flow(next_state)["activePolicy"] = normalized["action"]
    if _food_requested(action_plan, normalized):
        action_meta.update(_apply_food_action(next_state, normalized))
        _flow(next_state)["activePolicy"] = normalized["action"]
    if _energy_requested(action_plan, normalized):
        action_meta.update(_apply_energy_action(next_state))
        _flow(next_state)["activePolicy"] = normalized["action"]

    _evolve_natural(
        next_state,
        safe_minutes,
        rng,
        reroute_active=bool(action_meta.get("moved_guests") or action_meta.get("queue_arrivals_prevented")),
    )
    physical_dynamics = _apply_physical_dynamics(next_state, action_meta, safe_minutes, rng)
    _refresh_summary(next_state)
    meta = next_state.setdefault("digitalTwin", {})
    meta["mode"] = "stateful_stress_transition"
    meta["lastTransition"] = {
        "minutes": safe_minutes,
        "action": normalized,
        "action_effect": action_meta,
        "physical_dynamics": {
            "totalMovedGuests": physical_dynamics.get("totalMovedGuests"),
            "blockedPathCount": physical_dynamics.get("blockedPathCount"),
            "queueSpillbackCount": len(physical_dynamics.get("queueSpillbacks", [])),
            "staffTaskCount": len(physical_dynamics.get("staffTasks", [])),
        },
        "stochastic": stochastic,
    }
    return next_state


def apply_stress_event(state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    next_state = deepcopy(state)
    kind = str(event.get("kind", "demand_spike"))
    target_id = str(event.get("targetId") or event.get("target_id") or "coasterPlaza")
    intensity = max(10, min(100, _as_int(event.get("intensity"), 75)))
    zones = _by_id(_zones(next_state))
    rides = _by_id(_rides(next_state))
    target_zone_id = target_id
    if target_id in rides:
        target_zone_id = str(rides[target_id].get("zone") or target_zone_id)

    if kind == "ride_failure" and target_id in rides:
        ride = rides[target_id]
        ride["status"] = "down"
        ride["effectiveThroughput"] = 0
        ride["downtimeRisk"] = 100
        ride["queueGuests"] = max(_as_int(ride.get("queueGuests")), round(220 + intensity * 6.2))
        ride["waitMins"] = max(_as_int(ride.get("waitMins")), round(30 + intensity / 1.5))
        ride["throughputGap"] = _as_int(ride.get("capacityPerHour"))
    if target_zone_id in zones:
        zone = zones[target_zone_id]
        multiplier = 7.5 if kind in {"demand_spike", "food_spike"} else 4.5
        zone["currentGuests"] = _as_int(zone.get("currentGuests")) + round(intensity * multiplier)
        zone["waitMins"] = _as_int(zone.get("waitMins")) + round(intensity / 5)
    if kind == "staff_callout":
        staffing = next_state.get("staffing", {}) if isinstance(next_state.get("staffing"), dict) else {}
        staffing["openCallouts"] = _as_int(staffing.get("openCallouts")) + max(1, round(intensity / 10))
        staffing["checkedIn"] = max(0, _as_int(staffing.get("checkedIn")) - max(1, round(intensity / 10)))
    if kind in {"storm_risk", "energy_spike"}:
        weather = next_state.get("weather", {}) if isinstance(next_state.get("weather"), dict) else {}
        energy = next_state.get("energy", {}) if isinstance(next_state.get("energy"), dict) else {}
        weather["stormRisk"] = round(_bounded(_as_int(weather.get("stormRisk")) + intensity / 2, 0, 98))
        energy["gridLoadPercent"] = round(_bounded(_as_int(energy.get("gridLoadPercent"), 85) + intensity / 8, 0, 99))

    _evolve_natural(next_state, 3, random.Random(f"{kind}:{target_id}:{intensity}"), reroute_active=False)
    _refresh_summary(next_state)
    next_state.setdefault("digitalTwin", {})["lastStressEvent"] = deepcopy(event)
    return next_state


def simulate_action_plan(
    state: dict[str, Any],
    action_plan: dict[str, Any] | None = None,
    horizon_minutes: int = 30,
    seed: str | None = None,
) -> dict[str, Any]:
    before = deepcopy(state)
    safe_horizon = max(5, min(60, _as_int(horizon_minutes, 30)))
    checkpoints: list[dict[str, Any]] = []
    current = deepcopy(state)
    first_action_effect: dict[str, Any] = {}
    cumulative_moved_guests = 0
    normalized = _normalize_action(action_plan)
    reroute_active_minutes = _reroute_active_minutes(action_plan, normalized, safe_horizon)
    for elapsed in range(5, safe_horizon + 1, 5):
        if elapsed == 5:
            elapsed_action_plan = action_plan
        elif elapsed <= reroute_active_minutes:
            elapsed_action_plan = _reroute_only_action_plan(action_plan, normalized)
        else:
            elapsed_action_plan = {"target": "none", "action": "natural"}
        current = transition_state(
            current,
            elapsed_action_plan,
            minutes=5,
            seed=f"{seed or 'sim'}:{elapsed}",
            stochastic=False,
        )
        if elapsed == 5:
            first_action_effect = (
                current.get("digitalTwin", {}).get("lastTransition", {}).get("action_effect", {})
                if isinstance(current.get("digitalTwin"), dict)
                else {}
            )
        transition_effect = (
            current.get("digitalTwin", {}).get("lastTransition", {}).get("action_effect", {})
            if isinstance(current.get("digitalTwin"), dict)
            else {}
        )
        cumulative_moved_guests += _as_int(transition_effect.get("moved_guests"))
        checkpoints.append({"minute": elapsed, "digest": state_digest(current)})

    outcome = score_outcome(before, current, action_plan)
    before_digest = outcome["before"]
    after_digest = outcome["after"]
    origin_ride = _primary_ride(before)
    origin_zone_id = str(origin_ride.get("zone") or "")
    before_origin = _by_id(_zones(before)).get(origin_zone_id, {})
    after_origin = _by_id(_zones(current)).get(origin_zone_id, {})
    after_origin_ride = _by_id(_rides(current)).get(str(origin_ride.get("id")), {})
    moved_guests = cumulative_moved_guests or _as_int(first_action_effect.get("moved_guests"))
    if moved_guests <= 0:
        moved_guests = max(0, _as_int(origin_ride.get("queueGuests")) - _as_int(after_origin_ride.get("queueGuests")))
    density_delta = _as_int(after_origin.get("density")) - _as_int(before_origin.get("density"))
    wait_delta = _as_int(after_digest.get("slowest_ride", {}).get("waitMins")) - _as_int(before_digest.get("slowest_ride", {}).get("waitMins"))
    uncertainty = {
        "take_rate_band": [18, 62],
        "density_delta_band": [density_delta - 5, density_delta + 7],
        "wait_delta_band": [wait_delta - 6, wait_delta + 8],
        "drivers": ["guest take-rate", "path congestion", "repair ETA", "staff response latency"],
    }
    secondary_risks = []
    if any(_as_int(zone.get("density")) >= 92 for zone in _zones(current)):
        secondary_risks.append("Projected crowding remains above 92% in at least one zone.")
    if _as_int(after_digest.get("food_backlog")) > _as_int(before_digest.get("food_backlog")):
        secondary_risks.append("Food backlog worsens while crowd is being stabilized.")
    if _as_int(after_digest.get("most_congested_path", {}).get("congestionLevel")) >= 90:
        secondary_risks.append("A route path may become the next bottleneck.")

    return {
        "status": "ok",
        "source": "stateful_stress_transition_model",
        "horizon_minutes": safe_horizon,
        "projected_impact": {
            "fromZone": before_origin.get("name") or before_digest.get("busiest_zone", {}).get("name"),
            "movedGuests": moved_guests,
            "densityDeltaPct": density_delta,
            "projectedDensity": after_origin.get("density") or after_digest.get("busiest_zone", {}).get("density"),
            "avgWaitDeltaMinutes": wait_delta,
            "staffStressDelta": _as_int(after_digest.get("open_callouts")) - _as_int(before_digest.get("open_callouts")),
            "energyCostDeltaPct": _as_int(after_digest.get("grid_load")) - _as_int(before_digest.get("grid_load")),
            "guestSatisfactionDelta": _as_int(after_digest.get("avg_satisfaction")) - _as_int(before_digest.get("avg_satisfaction")),
        },
        "scorecard": {
            "overall": outcome["overall"],
            "capacity_fit": round(_bounded(100 - max(0, _as_int(after_digest.get("busiest_zone", {}).get("density")) - 75) * 1.7, 0, 100)),
            "safety": 100 if outcome["metrics"]["safety_violations"] == 0 else 58,
            "staff_burden": round(_bounded(92 - max(0, outcome["metrics"].get("staff_callout_delta", 0)) * 2, 0, 100)),
            "secondary_risk": round(_bounded(len(secondary_risks) * 24, 0, 100)),
        },
        "checkpoints": checkpoints,
        "uncertainty": uncertainty,
        "secondary_risks": secondary_risks or ["No secondary bottleneck projected above critical threshold."],
        "outcome": outcome,
        "projected_state": current,
    }


def noisy_observation(state: dict[str, Any], seed: str | None = None) -> dict[str, Any]:
    rng = random.Random(seed or f"obs:{_scenario_key(state)}")
    digest = state_digest(state)
    observed = deepcopy(digest)
    if observed.get("busiest_zone"):
        observed["busiest_zone"]["density"] = round(_bounded(_as_int(observed["busiest_zone"].get("density")) + rng.randint(-5, 6), 0, 125))
    if observed.get("slowest_ride"):
        observed["slowest_ride"]["waitMins"] = max(0, _as_int(observed["slowest_ride"].get("waitMins")) + rng.randint(-4, 7))
        observed["slowest_ride"]["queueGuests"] = max(0, _as_int(observed["slowest_ride"].get("queueGuests")) + rng.randint(-45, 60))
    observed["food_backlog"] = max(0, _as_int(observed.get("food_backlog")) + rng.randint(-12, 18))
    observed["storm_risk"] = round(_bounded(_as_int(observed.get("storm_risk")) + rng.randint(-6, 8), 0, 98))
    return {
        "status": "ok",
        "mode": "noisy_partial_observation",
        "staleness_seconds": {
            "queue_camera": rng.randint(20, 95),
            "pos_inventory": rng.randint(45, 180),
            "staff_badge": rng.randint(30, 120),
            "weather": rng.randint(60, 240),
        },
        "observation": observed,
        "hidden_truth_available_to": "evaluator_only",
    }
