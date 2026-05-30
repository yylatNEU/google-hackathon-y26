from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from policy_engine import get_policy_engine, policy_compliance_for_action


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _risk_counts(state: dict[str, Any]) -> dict[str, int]:
    rides = state.get("guestFlow", {}).get("rides", [])
    zones = state.get("guestFlow", {}).get("zones", [])
    return {
        "down_rides": sum(1 for ride in rides if ride.get("status") == "down"),
        "overloaded_rides": sum(1 for ride in rides if int(ride.get("waitMins", 0) or 0) >= 50),
        "crowded_zones": sum(1 for zone in zones if int(zone.get("density", 0) or 0) >= 80),
    }


def _primary_disrupted_ride(state: dict[str, Any]) -> dict[str, Any]:
    rides = state.get("guestFlow", {}).get("rides", [])
    if not rides:
        return {"name": "Dragon Coaster", "zoneName": "Coaster Plaza"}
    return max(
        rides,
        key=lambda ride: (
            100 if ride.get("status") == "down" else 30 if ride.get("status") == "constrained" else 0,
            int(ride.get("downtimeRisk", 0) or 0),
            int(ride.get("waitMins", 0) or 0),
            int(ride.get("queueGuests", 0) or 0),
        ),
    )


def build_park_action_plan(state: dict[str, Any]) -> dict[str, Any]:
    scenario = state.get("guestFlow", {}).get("activeScenario", {})
    scenario_key = scenario.get("key", "ride_down")
    policy_engine = get_policy_engine()
    counts = _risk_counts(state)
    disrupted_ride = _primary_disrupted_ride(state)
    ride_name = disrupted_ride.get("name", "Dragon Coaster")
    ride_zone = disrupted_ride.get("zoneName", "Coaster Plaza")
    common = {
        "created_at": _utc_now(),
        "scope": "parkpulse_operations_only",
        "domain": "amusement_park_operations",
        "scenario": scenario,
        "risk_counts": counts,
        "needs_human_approval": scenario_key in {"ride_down", "staff_shortage", "storm_response"},
        "arize_trace": {
            "span": "park_action_bridge.plan",
            "eval_subject": "park_operations_action_plan",
            "dimensions": ["groundedness", "capacity", "staff_stress", "safety", "actionability"],
        },
    }

    if scenario_key == "staff_shortage":
        actions = [
            _action("staff-protect-breaks", "Protect ride-operator breaks and minimum staffing", "Staffing", 5, "Prevents labor and safety guardrail violation.", "staff", "redeploy"),
            _action("reduce-low-priority-throughput", "Reduce throughput on low-demand attractions before closing core rides", "Ride Ops", 10, "Absorbs labor shortage without broad guest disruption.", "ride", "reroute"),
            _action("food-menu-simplify", "Simplify mobile-order menu where staff are short", "Food Ops", 8, "Cuts kitchen and pickup workload while preserving sales.", "food", "suppress_item"),
        ]
    elif scenario_key == "food_spike":
        actions = [
            _action("suppress-constrained-skus", "Hide chicken tenders and bottled drinks from Food Court A mobile order", "Food Ops", 3, "Avoids selling items below inventory threshold.", "food", "suppress_item"),
            _action("promote-food-court-b", "Promote pizza combo and drink pickup at Food Court B", "Guest Flow", 5, "Redirects demand to available inventory and spare capacity.", "traffic", "redirect_food"),
            _action("correct-pickup-etas", "Update pickup estimates before accepting more orders", "Food Ops", 4, "Improves guest fairness and reduces complaints.", "food", "suppress_item"),
        ]
    elif scenario_key == "storm_response":
        actions = [
            _action("taper-outdoor-intake", "Taper outdoor queue intake ahead of storm arrival", "Ride Ops", 10, "Reduces exposed guest queues before closure.", "ride", "reroute"),
            _action("protect-shelter-hvac", "Block HVAC reduction in indoor shelter zones", "Energy", 5, "Protects guest comfort while indoor density rises.", "energy", "protect_hvac"),
            _action("split-shelter-demand", "Split guests across Theater B, Arcade Zone, and covered routes", "Guest Flow", 8, "Avoids creating one indoor bottleneck.", "traffic", "redirect_food"),
        ]
    else:
        actions = [
            _action("pause-ride-intake", f"Pause new queue intake at {ride_name}", "Ride Ops", 5, "Prevents additional guests from joining a dead queue.", "ride", "reroute"),
            _action("split-guest-routing", f"Redirect guests away from {ride_name} into available indoor shows, arcade, and food capacity", "Guest Flow", 10, f"Reduces {ride_zone} density without creating a new single bottleneck.", "traffic", "redirect_food"),
            _action("move-crowd-control", f"Move two crowd-control staff to {ride_zone}", "Staffing", 10, "Keeps exit flow calm and protects ride operators from service overload.", "staff", "redeploy"),
            _action("send-honest-message", "Send guest app message with downtime uncertainty and nearby alternatives", "Guest Experience", 8, "Improves recovery satisfaction without promising reopening.", "ride", "reroute"),
        ]

    for action_doc in actions:
        park_action = action_doc.get("park_action", {}) or {}
        action_doc["policy_compliance"] = policy_engine.policy_compliance_for_action(
            str(park_action.get("target", "")),
            str(park_action.get("action", "")),
            checks=["safety-first", "source-grounded", "capacity-aware", "customer-care-approved"],
            scenario=scenario,
        )

    plan = {
        **common,
        "recommended_actions": actions,
        "selected_action": actions[0],
        "policy_context": policy_engine.policy_context_for_planner(scenario),
        "tradeoffs": {
            "guest_satisfaction": "Short-term disappointment is accepted to prevent a worse bottleneck.",
            "staff_stress": "Redeployments are capped and do not pull certified operators below minimums.",
            "energy_cost": "Energy savings are secondary when indoor guest comfort or shelter demand is high.",
            "revenue": "Targeted recovery and demand redirection are preferred over blanket compensation.",
            "safety": "Maintenance, weather, and staffing guardrails override throughput.",
        },
        "confidence": 0.86 if scenario_key == "food_spike" else 0.82,
    }
    plan["policy_contract"] = policy_engine.validate_plan(plan)
    return plan


def _action(
    action_id: str,
    title: str,
    owner: str,
    deadline_minutes: int,
    expected_impact: str,
    target: str,
    action: str,
) -> dict[str, Any]:
    return {
        "action_id": action_id,
        "title": title,
        "owner": owner,
        "deadline_minutes": deadline_minutes,
        "expected_impact": expected_impact,
        "park_action": {"target": target, "action": action},
        "policy_compliance": policy_compliance_for_action(
            target,
            action,
            checks=["safety-first", "source-grounded", "capacity-aware", "customer-care-approved"],
        ),
    }


# Compatibility alias for older callers.
build_delay_action_plan = build_park_action_plan
