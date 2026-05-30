from __future__ import annotations

from copy import deepcopy
from typing import Any


PARK_SCENARIOS: dict[str, dict[str, Any]] = {
    "ride_down": {
        "key": "ride_down",
        "label": "Scenario A",
        "title": "Ride Down",
        "situation": "Dragon Coaster is down for an estimated 60 minutes. 700 guests are nearby, Indoor Ride B already has a 55-minute wait, and Food Court 2 is understaffed.",
        "riskLevel": "HIGH",
        "confidence": 0.82,
        "humanApproval": True,
        "evals": [
            {"label": "Groundedness", "score": 91, "detail": "Uses actual ride status, queue size, and alternate wait data."},
            {"label": "Capacity awareness", "score": 88, "detail": "Avoids dumping all guests into already-overloaded Indoor Ride B."},
            {"label": "Staff impact", "score": 76, "detail": "Adds staff where needed but creates a near-term coverage gap."},
            {"label": "Guest recovery", "score": 84, "detail": "Message is helpful and honest about downtime uncertainty."},
            {"label": "Safety", "score": 96, "detail": "Does not suggest shortcutting maintenance or reopening without clearance."},
            {"label": "Actionability", "score": 89, "detail": "Owners, deadlines, and expected impacts are specific."},
            {"label": "Take rate", "score": 34, "detail": "Measures whether the guest offer actually redirects guests from the down ride."},
            {"label": "Positive response", "score": 78, "detail": "Tracks guest sentiment and worker acknowledgment after delivery."},
            {"label": "Reactive follow-through", "score": 29, "detail": "Checks whether guests and staff physically move toward recommended zones."},
        ],
    },
    "staff_shortage": {
        "key": "staff_shortage",
        "label": "Scenario B",
        "title": "Staff Shortage",
        "situation": "Multiple workers call out during peak demand. Ride waits are rising, food lines are long, and protected break windows are at risk.",
        "riskLevel": "HIGH",
        "confidence": 0.78,
        "humanApproval": True,
        "evals": [
            {"label": "Groundedness", "score": 89, "detail": "Uses staffing, wait, and break-window data."},
            {"label": "Staff stress", "score": 93, "detail": "Protects breaks and avoids unlimited redeployment."},
            {"label": "Operational feasibility", "score": 81, "detail": "Moves staff across compatible roles only."},
            {"label": "Guest impact", "score": 77, "detail": "Accepts localized wait increases to reduce system-wide risk."},
            {"label": "Policy compliance", "score": 95, "detail": "Flags break-delay policy as a hard guardrail."},
            {"label": "Conflict resolution", "score": 86, "detail": "Balances ride ops, food ops, and worker wellbeing."},
            {"label": "Take rate", "score": 96, "detail": "Measures whether assigned staff acknowledge and accept redeployment."},
            {"label": "Positive response", "score": 88, "detail": "Tracks whether staff response is timely and non-escalatory."},
            {"label": "Reactive follow-through", "score": 91, "detail": "Checks whether staff actually move toward the crowded zone."},
        ],
    },
    "food_spike": {
        "key": "food_spike",
        "label": "Scenario C",
        "title": "Food Demand Spike",
        "situation": "Lunch demand spikes near Adventure Zone. Mobile orders are backing up, chicken tenders and bottled drinks are low, and Food Court B has spare capacity.",
        "riskLevel": "MEDIUM",
        "confidence": 0.86,
        "humanApproval": False,
        "evals": [
            {"label": "Inventory groundedness", "score": 94, "detail": "Recommendations match SKU availability and kitchen load."},
            {"label": "Demand logic", "score": 90, "detail": "Responds to order backlog and local guest density."},
            {"label": "Guest fairness", "score": 87, "detail": "Pickup estimates are corrected before new orders arrive."},
            {"label": "Revenue impact", "score": 84, "detail": "Redirects demand instead of turning mobile ordering off."},
            {"label": "Staff impact", "score": 79, "detail": "Staff move is useful but should be time-boxed."},
            {"label": "Actionability", "score": 92, "detail": "Specific menu, location, staffing, and ETA changes."},
            {"label": "Take rate", "score": 28, "detail": "Measures whether guests accept the Food Court B redirect offer."},
            {"label": "Positive response", "score": 73, "detail": "Tracks guest response to item suppression and pickup-time changes."},
            {"label": "Reactive follow-through", "score": 24, "detail": "Checks whether demand shifts away from the overloaded kitchen."},
        ],
    },
    "storm_response": {
        "key": "storm_response",
        "label": "Scenario D",
        "title": "Storm Response",
        "situation": "A storm front is pushing outdoor queues into indoor shelter zones while HVAC and energy load are already constrained.",
        "riskLevel": "HIGH",
        "confidence": 0.8,
        "humanApproval": True,
        "evals": [
            {"label": "Weather groundedness", "score": 92, "detail": "Uses live storm risk, shelter pressure, and outdoor ride exposure."},
            {"label": "Shelter capacity", "score": 86, "detail": "Splits guests across indoor zones instead of creating one shelter bottleneck."},
            {"label": "Energy protection", "score": 88, "detail": "Protects HVAC in high-density shelter areas despite peak load."},
            {"label": "Safety", "score": 97, "detail": "Tapers outdoor queues before storm exposure becomes unsafe."},
            {"label": "Staff impact", "score": 82, "detail": "Uses crowd-control staff without breaking safety-critical ride coverage."},
            {"label": "Actionability", "score": 89, "detail": "Specifies outdoor intake, shelter routing, and comfort-protection controls."},
            {"label": "Take rate", "score": 42, "detail": "Measures whether guests follow shelter routing before weather peaks."},
            {"label": "Positive response", "score": 81, "detail": "Tracks guest and worker acceptance of storm routing instructions."},
            {"label": "Reactive follow-through", "score": 35, "detail": "Checks whether guests physically move from exposed queues into safer zones."},
        ],
    },
}


def get_park_scenarios() -> dict[str, Any]:
    return {
        "source": "parkpulse_backend",
        "scenarios": [deepcopy(scenario) for scenario in PARK_SCENARIOS.values()],
    }


def get_park_eval_result(scenario_key: str) -> dict[str, Any]:
    scenario = deepcopy(PARK_SCENARIOS.get(scenario_key, PARK_SCENARIOS["ride_down"]))
    return {
        "source": "parkpulse_gcp_internal_eval_loop",
        "scenario": {
            "key": scenario["key"],
            "title": scenario["title"],
            "riskLevel": scenario["riskLevel"],
            "confidence": scenario["confidence"],
            "humanApproval": scenario["humanApproval"],
        },
        "evals": scenario["evals"],
        "arize_trace": {
            "span": f"parkpulse.decision_bridge.{scenario['key']}",
            "eval_subject": "park_operations_action_plan",
            "dimensions": [item["label"] for item in scenario["evals"]],
        },
    }
