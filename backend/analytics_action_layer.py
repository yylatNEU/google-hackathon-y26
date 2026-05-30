from __future__ import annotations

from copy import deepcopy
from typing import Any


PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _name(row: dict[str, Any], *keys: str, default: str = "unknown") -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return default


def _gate(priority: str, safety: bool = False) -> str:
    if safety or priority == "P0":
        return "approval_required"
    if priority == "P1":
        return "prepared"
    return "read_only"


def _system_action(system: str, operation: str, gate: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "system": system,
        "operation": operation,
        "gate": gate,
        "payload": payload or {},
    }


def _opportunity(
    *,
    oid: str,
    signal: dict[str, Any],
    business_object: dict[str, Any],
    owner_agent: str,
    support_agents: list[str],
    priority: str,
    proposed_action: dict[str, Any],
    system_actions: list[dict[str, Any]],
    approval_reason: str,
    verification_metric: str,
    baseline: str,
    success: str,
    rollback: str,
    safety: bool = False,
) -> dict[str, Any]:
    gate = _gate(priority, safety=safety)
    return {
        "id": oid,
        "analytics_signal": signal,
        "business_object": business_object,
        "owner_agent": owner_agent,
        "support_agents": support_agents,
        "priority": priority,
        "policy_gate": gate,
        "proposed_action": proposed_action,
        "system_actions": system_actions,
        "approval": {
            "required": gate == "approval_required",
            "reason": approval_reason if gate == "approval_required" else "Agent can prepare the plan, but external execution remains gated.",
        },
        "verification": {
            "metric": verification_metric,
            "baseline": baseline,
            "success": success,
            "rollback": rollback,
        },
        "audit": {
            "trace_fields": [
                "operator_intent",
                "analytics_signal",
                "policy_refs",
                "tool_calls",
                "owner_agent",
                "human_approval",
                "system_mutations",
                "post_action_metrics",
            ],
        },
    }


def _conflict(
    *,
    cid: str,
    title: str,
    severity: str,
    involved: list[dict[str, Any]],
    rejected_action: str,
    selected_resolution: str,
    why: str,
    required_checks: list[str],
    simulated_side_effect: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": cid,
        "title": title,
        "severity": severity,
        "involved_opportunities": involved,
        "rejected_action": rejected_action,
        "selected_resolution": selected_resolution,
        "why": why,
        "required_checks": required_checks,
        "simulated_side_effect": simulated_side_effect,
    }


def _find_opportunities(opportunities: list[dict[str, Any]], owner_contains: str | None = None, object_type: str | None = None) -> list[dict[str, Any]]:
    matches = []
    owner_term = (owner_contains or "").lower()
    object_term = (object_type or "").lower()
    for opportunity in opportunities:
        owner = str(opportunity.get("owner_agent") or "").lower()
        obj = opportunity.get("business_object", {}) if isinstance(opportunity.get("business_object"), dict) else {}
        obj_type = str(obj.get("type") or "").lower()
        if owner_term and owner_term not in owner:
            continue
        if object_term and object_term != obj_type:
            continue
        matches.append(opportunity)
    return matches


def _ref(opportunity: dict[str, Any]) -> dict[str, Any]:
    obj = opportunity.get("business_object", {}) if isinstance(opportunity.get("business_object"), dict) else {}
    return {
        "id": opportunity.get("id"),
        "priority": opportunity.get("priority"),
        "owner_agent": opportunity.get("owner_agent"),
        "object": obj.get("name") or obj.get("id"),
        "gate": opportunity.get("policy_gate"),
    }


def _build_conflict_board(opportunities: list[dict[str, Any]], state: dict[str, Any]) -> dict[str, Any]:
    conflicts: list[dict[str, Any]] = []
    incident_ops = [item for item in opportunities if item.get("priority") == "P0"]
    ride_ops = _find_opportunities(opportunities, object_type="Ride")
    zone_ops = _find_opportunities(opportunities, object_type="Zone")
    food_ops = _find_opportunities(opportunities, object_type="FoodLocation")
    staffing_ops = _find_opportunities(opportunities, owner_contains="Staffing")
    weather_ops = _find_opportunities(opportunities, owner_contains="Weather")
    energy_ops = _find_opportunities(opportunities, owner_contains="Energy")

    if incident_ops and (ride_ops or zone_ops or food_ops):
        incident = incident_ops[0]
        pressure = (ride_ops or zone_ops or food_ops)[0]
        conflicts.append(
            _conflict(
                cid="conflict_safety_vs_throughput",
                title="Safety incident outranks throughput optimization",
                severity="critical",
                involved=[_ref(incident), _ref(pressure)],
                rejected_action="Use broad queue, food, or signage reroutes before confirming the incident perimeter.",
                selected_resolution="Freeze optimization near the incident, assign owner, protect access, then re-score crowd actions.",
                why="A missing child, medical, or security report can turn an otherwise useful reroute into scene contamination or blocked access.",
                required_checks=["human incident confirmation", "owner acknowledgement", "access lane clear", "no mass guest message before approval"],
                simulated_side_effect={
                    "if_rejected_action_taken": "crowd optimization may increase search area, panic, or access blockage",
                    "if_resolution_taken": "throughput benefit is delayed, but incident containment and auditability improve",
                },
            )
        )

    if ride_ops and food_ops:
        ride = ride_ops[0]
        food = food_ops[0]
        conflicts.append(
            _conflict(
                cid="conflict_ride_reroute_vs_food_backlog",
                title="Ride reroute can overload food operations",
                severity="high",
                involved=[_ref(ride), _ref(food)],
                rejected_action="Send most displaced ride guests to the nearest food court.",
                selected_resolution="Split ride guests across entertainment, shaded rest, and food only after POS/backlog check.",
                why="Queue relief looks good on a ride dashboard but can transfer the failure to food pickup and guest-care complaints.",
                required_checks=["food backlog below threshold", "alternate zones have spare capacity", "guest message names multiple destinations"],
                simulated_side_effect={
                    "if_rejected_action_taken": "ride wait falls while food ETA and crowd density spike",
                    "if_resolution_taken": "ride relief is slower but total park pressure is lower",
                },
            )
        )

    if (ride_ops or food_ops or zone_ops) and staffing_ops:
        pressure = (ride_ops or food_ops or zone_ops)[0]
        staffing = staffing_ops[0]
        conflicts.append(
            _conflict(
                cid="conflict_staff_redeploy_vs_minimum_coverage",
                title="Redeployment conflicts with minimum coverage and protected breaks",
                severity="high",
                involved=[_ref(pressure), _ref(staffing)],
                rejected_action="Pull any available worker to the hottest pressure zone.",
                selected_resolution="Draft role-compatible redeployments only after checking ride minimum staffing and break rules.",
                why="Agents need labor and safety constraints, not just a heatmap of where bodies are needed.",
                required_checks=["role compatibility", "ride minimum staffing", "protected break window", "manager approval"],
                simulated_side_effect={
                    "if_rejected_action_taken": "one zone improves while ride safety or labor compliance degrades",
                    "if_resolution_taken": "coverage improves with fewer hidden policy violations",
                },
            )
        )

    if weather_ops and energy_ops:
        weather = weather_ops[0]
        energy = energy_ops[0]
        conflicts.append(
            _conflict(
                cid="conflict_energy_shed_vs_shelter_comfort",
                title="Energy reduction can harm weather shelter comfort",
                severity="medium",
                involved=[_ref(weather), _ref(energy)],
                rejected_action="Shed HVAC load while guests are being moved indoors for heat or storm risk.",
                selected_resolution="Protect shelter HVAC first; shed only noncritical lighting/equipment after comfort simulation.",
                why="An energy optimization can be financially correct and operationally unsafe during shelter posture.",
                required_checks=["shelter density", "indoor comfort score", "storm/heat posture", "facility manager approval"],
                simulated_side_effect={
                    "if_rejected_action_taken": "grid load improves while guest comfort and safety degrade",
                    "if_resolution_taken": "demand reduction is smaller but shelter remains usable",
                },
            )
        )

    if len(zone_ops) >= 2:
        primary, secondary = zone_ops[:2]
        conflicts.append(
            _conflict(
                cid="conflict_pressure_transfer_between_zones",
                title="Solving one zone can transfer pressure to another",
                severity="medium",
                involved=[_ref(primary), _ref(secondary)],
                rejected_action="Route guests from the highest-density zone to the nearest open-looking zone.",
                selected_resolution="Compare route options against adjacent-zone capacity and accessibility path constraints.",
                why="Single-zone improvement is not success if it creates a new bottleneck five minutes later.",
                required_checks=["destination density", "path congestion", "accessibility route", "five-minute replay"],
                simulated_side_effect={
                    "if_rejected_action_taken": "top zone improves while secondary zone crosses density threshold",
                    "if_resolution_taken": "benefit is distributed and easier to rollback",
                },
            )
        )

    conflicts.sort(key=lambda item: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(str(item.get("severity")), 9))
    blocked_actions = [item["rejected_action"] for item in conflicts]
    return {
        "mode": "multi_object_action_conflict_board_v1",
        "conflict_count": len(conflicts),
        "conflicts": conflicts[:6],
        "blocked_actions": blocked_actions[:8],
        "operating_rule": "Do not optimize a single metric until safety, labor, accessibility, destination capacity, and rollback checks are scored.",
    }


def build_analytics_to_action_layer(
    state: dict[str, Any],
    policy_doctrine: dict[str, Any] | None = None,
    policy_reasoning: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert live analytics into governed operating opportunities.

    This is deliberately deterministic: it is the product surface showing what
    agents add on top of dashboards before an LLM writes or dispatches anything.
    """

    state = state if isinstance(state, dict) else {}
    flow = state.get("guestFlow", {}) if isinstance(state.get("guestFlow"), dict) else {}
    readiness = state.get("incidentReadiness", {}) if isinstance(state.get("incidentReadiness"), dict) else {}
    staffing = state.get("staffing", {}) if isinstance(state.get("staffing"), dict) else {}
    weather = state.get("weather", {}) if isinstance(state.get("weather"), dict) else {}
    energy = state.get("energy", {}) if isinstance(state.get("energy"), dict) else {}
    food = state.get("foodInventory", {}) if isinstance(state.get("foodInventory"), dict) else {}
    digital_twin = state.get("digitalTwin", {}) if isinstance(state.get("digitalTwin"), dict) else {}
    scenario = flow.get("activeScenario", {}) if isinstance(flow.get("activeScenario"), dict) else {}
    policy_case = (policy_doctrine or {}).get("primary_case", {}) if isinstance((policy_doctrine or {}).get("primary_case"), dict) else {}
    policy_refs = policy_case.get("policy_refs") or []

    opportunities: list[dict[str, Any]] = []

    for incident in readiness.get("activeSyntheticIncidents", []) if isinstance(readiness.get("activeSyntheticIncidents"), list) else []:
        if not isinstance(incident, dict):
            continue
        location = _name(incident, "location", "targetId")
        owner = _name(incident, "expectedOwner", default="Incident Supervisor Agent")
        kind = _name(incident, "kind", default="incident").replace("_", " ")
        opportunities.append(
            _opportunity(
                oid=f"opp_incident_{incident.get('id') or location}",
                signal={
                    "source": "incident_readiness",
                    "metric": "active_synthetic_incident",
                    "value": kind,
                    "threshold": "any P0 safety case",
                    "evidence": f"{kind} at {location}; expected owner {owner}.",
                },
                business_object={"type": "Incident", "id": str(incident.get("id") or "synthetic"), "name": f"{kind.title()} at {location}"},
                owner_agent=owner,
                support_agents=["Policy Agent", "Map Grounding Agent", "Operations Supervisor"],
                priority="P0",
                proposed_action={
                    "label": f"Run governed {kind} response",
                    "target": location,
                    "action": str(incident.get("expectedAction") or "secure_scene_and_coordinate_response"),
                    "policy_refs": policy_refs or incident.get("hardConstraints", []),
                },
                system_actions=[
                    _system_action("digital_twin", "simulate_before_apply", "read_only", {"incident_id": incident.get("id")}),
                    _system_action("worker_device", "draft_role_tasks", "approval_required", {"owner": owner, "location": location}),
                    _system_action("guest_app", "draft_location_message", "approval_required", {"location": location, "tone": "calm"}),
                    _system_action("map", "highlight_command_zone", "prepared", {"targetId": incident.get("targetId")}),
                ],
                approval_reason="Safety, security, medical, and missing-child workflows require accountable human approval before dispatch or guest messaging.",
                verification_metric="time_to_owner_acknowledgement and scene containment",
                baseline="No coordinated owner assignment or map command zone.",
                success="Owner acknowledges, access path stays open, and no conflicting crowd-flow action is applied.",
                rollback="Cancel drafted tasks/messages and restore previous map overlays if the report is invalid.",
                safety=True,
            )
        )

    zones = [row for row in flow.get("zones", []) if isinstance(row, dict)] if isinstance(flow.get("zones"), list) else []
    for zone in sorted(zones, key=lambda row: _as_int(row.get("density")), reverse=True)[:3]:
        density = _as_int(zone.get("density"))
        wait = _as_int(zone.get("waitMins", zone.get("wait")))
        comfort = _as_int(zone.get("comfortScore", zone.get("comfort")), 100)
        if density < 90 and wait < 45 and comfort > 60:
            continue
        zone_name = _name(zone, "name", "label", "id")
        opportunities.append(
            _opportunity(
                oid=f"opp_zone_{zone.get('id') or zone_name}",
                signal={
                    "source": "guest_flow_analytics",
                    "metric": "zone_pressure",
                    "value": density,
                    "threshold": "density >= 90% or wait >= 45m or comfort <= 60",
                    "evidence": f"{zone_name}: density {density}%, wait {wait} min, comfort {comfort}.",
                },
                business_object={"type": "Zone", "id": str(zone.get("id") or zone_name), "name": zone_name},
                owner_agent="Crowd Flow Agent",
                support_agents=["Guest Experience Agent", "Staffing Agent", "Policy Agent"],
                priority="P1" if density >= 105 or comfort <= 55 else "P2",
                proposed_action={"label": f"Reduce pressure at {zone_name}", "target": zone_name, "action": "split_flow_and_adjust_signage"},
                system_actions=[
                    _system_action("digital_twin", "compare_route_options", "read_only", {"zone": zone_name}),
                    _system_action("digital_signage", "draft_directional_change", "prepared", {"zone": zone_name}),
                    _system_action("worker_device", "draft_roaming_staff_task", "prepared", {"zone": zone_name}),
                ],
                approval_reason="Route and signage changes can affect accessibility lanes and emergency access.",
                verification_metric="zone density, wait minutes, comfort score",
                baseline=f"{zone_name} remains at density {density}%.",
                success="Density drops without increasing an adjacent zone above threshold.",
                rollback="Revert signage draft and remove temporary staffing task.",
            )
        )

    rides = [row for row in flow.get("rides", []) if isinstance(row, dict)] if isinstance(flow.get("rides"), list) else []
    for ride in sorted(rides, key=lambda row: max(_as_int(row.get("waitMins")), _as_int(row.get("downtimeRisk"))), reverse=True)[:3]:
        wait = _as_int(ride.get("waitMins"))
        risk = _as_int(ride.get("downtimeRisk"))
        status = str(ride.get("status") or "normal")
        if status == "normal" and wait < 55 and risk < 35:
            continue
        ride_name = _name(ride, "name", "id")
        opportunities.append(
            _opportunity(
                oid=f"opp_ride_{ride.get('id') or ride_name}",
                signal={
                    "source": "ride_queue_analytics",
                    "metric": "ride_wait_or_downtime_risk",
                    "value": max(wait, risk),
                    "threshold": "wait >= 55m, downtime risk >= 35, or non-normal status",
                    "evidence": f"{ride_name}: status {status}, wait {wait} min, downtime risk {risk}%.",
                },
                business_object={"type": "Ride", "id": str(ride.get("id") or ride_name), "name": ride_name},
                owner_agent="Ride Safety Agent" if status != "normal" or risk >= 45 else "Crowd Flow Agent",
                support_agents=["Maintenance Agent", "Guest Messaging Agent", "Policy Agent"],
                priority="P1" if status != "normal" or risk >= 45 else "P2",
                proposed_action={"label": f"Prepare ride queue intervention for {ride_name}", "target": ride_name, "action": "reroute_or_recovery_plan"},
                system_actions=[
                    _system_action("digital_twin", "simulate_wait_recovery", "read_only", {"ride": ride_name}),
                    _system_action("guest_app", "draft_queue_advisory", "prepared", {"ride": ride_name}),
                    _system_action("maintenance_cmms", "draft_inspection_task", "approval_required" if status != "normal" else "prepared", {"ride": ride_name}),
                ],
                approval_reason="Ride safety and maintenance dispatch need operations approval.",
                verification_metric="wait minutes, ride status, guest displacement",
                baseline=f"{ride_name} wait remains {wait} min.",
                success="Queue reduces and ride status does not degrade.",
                rollback="Restore queue messaging and cancel pending maintenance draft if telemetry normalizes.",
                safety=status != "normal",
            )
        )

    locations = [row for row in food.get("locations", []) if isinstance(row, dict)] if isinstance(food.get("locations"), list) else []
    for location in locations:
        backlog = _as_int(location.get("mobileBacklog"))
        eta = _as_int(location.get("etaMins", location.get("eta")))
        low_inventory = location.get("lowInventory") or []
        if backlog < 25 and eta < 18 and not low_inventory:
            continue
        name = _name(location, "name", "id")
        opportunities.append(
            _opportunity(
                oid=f"opp_food_{location.get('id') or name}",
                signal={
                    "source": "food_pos_inventory",
                    "metric": "backlog_eta_inventory",
                    "value": max(backlog, eta),
                    "threshold": "mobile backlog >= 25, ETA >= 18m, or low inventory",
                    "evidence": f"{name}: backlog {backlog}, ETA {eta} min, low inventory {', '.join(map(str, low_inventory)) or 'none'}.",
                },
                business_object={"type": "FoodLocation", "id": str(location.get("id") or name), "name": name},
                owner_agent="Food Operations Agent",
                support_agents=["Staffing Agent", "Guest Messaging Agent", "Finance Agent"],
                priority="P1" if backlog >= 45 or eta >= 25 else "P2",
                proposed_action={"label": f"Stabilize food demand at {name}", "target": name, "action": "menu_throttle_staff_and_message"},
                system_actions=[
                    _system_action("pos", "draft_menu_throttle", "prepared", {"location": name, "items": low_inventory}),
                    _system_action("worker_device", "draft_runner_task", "prepared", {"location": name}),
                    _system_action("guest_app", "draft_alternate_food_message", "prepared", {"location": name}),
                ],
                approval_reason="Menu throttles and guest messages affect revenue and guest experience.",
                verification_metric="mobile backlog and ETA",
                baseline=f"{name} backlog remains {backlog}.",
                success="Backlog and ETA fall without pushing adjacent food location above threshold.",
                rollback="Restore menu availability and cancel drafted task.",
            )
        )

    open_callouts = _as_int(staffing.get("openCallouts"))
    if open_callouts >= 20:
        opportunities.append(
            _opportunity(
                oid="opp_staffing_callouts",
                signal={
                    "source": "labor_schedule",
                    "metric": "open_callouts",
                    "value": open_callouts,
                    "threshold": ">= 20 open callouts",
                    "evidence": f"{open_callouts} open callouts; checked in {_as_int(staffing.get('checkedIn'))}.",
                },
                business_object={"type": "StaffPool", "id": "park_staffing", "name": "Park staffing"},
                owner_agent="Staffing Agent",
                support_agents=["Labor Policy Agent", "Ride Safety Agent", "Food Operations Agent"],
                priority="P1",
                proposed_action={"label": "Prepare role-compatible staffing recovery", "target": "Park staffing", "action": "redeploy_floaters_and_preserve_breaks"},
                system_actions=[
                    _system_action("schedule_system", "draft_redeployment", "approval_required", {"open_callouts": open_callouts}),
                    _system_action("worker_device", "draft_shift_offer", "approval_required", {"open_callouts": open_callouts}),
                    _system_action("digital_twin", "check_minimum_staffing_constraints", "read_only"),
                ],
                approval_reason="Labor, breaks, role compatibility, and ride minimum staffing need supervisor approval.",
                verification_metric="open callouts, staffReadyPct, minimum staffing violations",
                baseline=f"{open_callouts} callouts remain uncovered.",
                success="Coverage improves without break or minimum-staffing violations.",
                rollback="Cancel unaccepted redeployments and restore roster assumptions.",
                safety=True,
            )
        )

    storm_risk = _as_int(weather.get("stormRisk"))
    heat = _as_int(weather.get("heatIndexF"))
    if storm_risk >= 70 or heat >= 98:
        opportunities.append(
            _opportunity(
                oid="opp_weather_shelter",
                signal={
                    "source": "weather_feed",
                    "metric": "storm_or_heat_risk",
                    "value": max(storm_risk, heat),
                    "threshold": "storm risk >= 70% or heat index >= 98F",
                    "evidence": f"Storm risk {storm_risk}%, heat index {heat}F.",
                },
                business_object={"type": "WeatherRisk", "id": "weather_shelter", "name": "Weather and shelter posture"},
                owner_agent="Weather + Shelter Agent",
                support_agents=["Facilities Agent", "Crowd Flow Agent", "Guest Messaging Agent"],
                priority="P1",
                proposed_action={"label": "Prepare weather shelter posture", "target": "Indoor shelter network", "action": "protect_shelter_capacity_and_prewrite_alerts"},
                system_actions=[
                    _system_action("digital_twin", "simulate_shelter_load", "read_only"),
                    _system_action("guest_app", "draft_weather_alert", "approval_required"),
                    _system_action("facilities_bms", "protect_hvac_setpoints", "approval_required"),
                    _system_action("digital_signage", "draft_shelter_routing", "prepared"),
                ],
                approval_reason="Weather alerts, shelter routing, and HVAC controls affect safety and guest trust.",
                verification_metric="shelter density, heat comfort, weather alert acknowledgement",
                baseline="Guests continue flowing into outdoor queues.",
                success="Shelter capacity stays within threshold and comfort does not degrade.",
                rollback="Cancel draft alerts and restore noncritical facility controls.",
                safety=storm_risk >= 80,
            )
        )

    grid_load = _as_int(energy.get("gridLoadPercent"))
    if grid_load >= 92:
        opportunities.append(
            _opportunity(
                oid="opp_energy_peak",
                signal={
                    "source": "facilities_energy_meter",
                    "metric": "grid_load_percent",
                    "value": grid_load,
                    "threshold": ">= 92%",
                    "evidence": f"Grid load {grid_load}%, demand risk {energy.get('demandChargeRisk', 'unknown')}.",
                },
                business_object={"type": "FacilitySystem", "id": "energy_grid", "name": "Park energy grid"},
                owner_agent="Facilities Energy Agent",
                support_agents=["Weather + Shelter Agent", "Finance Agent", "Policy Agent"],
                priority="P2",
                proposed_action={"label": "Prepare noncritical load reduction", "target": "Energy grid", "action": "shed_noncritical_load_without_shelter_harm"},
                system_actions=[
                    _system_action("facilities_bms", "draft_noncritical_load_shed", "approval_required", {"grid_load": grid_load}),
                    _system_action("digital_twin", "check_guest_comfort_side_effects", "read_only"),
                ],
                approval_reason="Equipment and comfort controls require manager approval.",
                verification_metric="grid load and indoor comfort",
                baseline=f"Grid load remains {grid_load}%.",
                success="Grid load decreases without reducing shelter comfort.",
                rollback="Restore prior facility setpoints.",
            )
        )

    opportunities.sort(
        key=lambda item: (
            PRIORITY_ORDER.get(str(item.get("priority")), 9),
            -_as_int((item.get("analytics_signal") or {}).get("value")),
            str(item.get("id")),
        )
    )
    limited = opportunities[:6]
    approval_required = sum(1 for item in limited if item.get("approval", {}).get("required"))
    conflict_board = _build_conflict_board(limited, state)
    return {
        "mode": "analytics_to_governed_action_v1",
        "thesis": "Dashboards identify pressure; ParkPulse agents convert pressure into governed, cross-system, verified action.",
        "scenario": {
            "key": scenario.get("key"),
            "title": scenario.get("title") or scenario.get("name"),
            "synthetic_active": bool((digital_twin.get("syntheticScenario") or {}).get("active")) if isinstance(digital_twin.get("syntheticScenario"), dict) else False,
        },
        "policy_context": {
            "primary_case_id": policy_case.get("id"),
            "policy_refs": deepcopy(policy_refs),
            "reasoning_steps": len((policy_reasoning or {}).get("steps", []) if isinstance((policy_reasoning or {}).get("steps"), list) else []),
        },
        "opportunities": limited,
        "conflict_board": conflict_board,
        "coverage": {
            "signal_count": len(opportunities),
            "actionable_count": sum(1 for item in limited if item.get("policy_gate") != "read_only"),
            "approval_required_count": approval_required,
            "conflict_count": conflict_board.get("conflict_count", 0),
            "visible_count": len(limited),
        },
    }
