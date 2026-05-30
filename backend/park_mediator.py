from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


_park_signals: list[dict[str, Any]] = []


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


async def react_to_park_state(state: dict[str, Any], fast_eval: bool = False, **_: Any) -> list[dict[str, Any]]:
    scenario = state.get("guestFlow", {}).get("activeScenario", {})
    scenario_key = scenario.get("key", "ride_down")
    signals = _signals_for_scenario(scenario_key, state, fast_eval)
    existing_ids = {signal["id"] for signal in _park_signals}
    created = [signal for signal in signals if signal["id"] not in existing_ids]
    _park_signals[:0] = created
    del _park_signals[50:]
    return created


async def get_park_signals() -> dict[str, Any]:
    return {
        "domain": "amusement_park_operations",
        "signal_bus": "park_operations_signals",
        "count": len(_park_signals),
        "signals": list(_park_signals),
    }


async def get_park_agent_findings(state: dict[str, Any]) -> dict[str, Any]:
    guest_flow = state.get("guestFlow", {})
    rides = guest_flow.get("rides", [])
    zones = guest_flow.get("zones", [])
    staffing = state.get("staffing", {})
    energy = state.get("energy", {})
    return {
        "domain": "amusement_park_operations",
        "summary": {
            "agent_count": 7,
            "scenario": guest_flow.get("activeScenario", {}).get("key", "unknown"),
            "down_rides": sum(1 for ride in rides if ride.get("status") == "down"),
            "overloaded_rides": sum(1 for ride in rides if int(ride.get("waitMins", 0) or 0) >= 50),
            "crowded_zones": sum(1 for zone in zones if int(zone.get("density", 0) or 0) >= 80),
            "open_callouts": staffing.get("openCallouts", 0),
            "energy_risk": energy.get("demandChargeRisk", "normal"),
        },
        "agents": [
            {"name": "Ride Ops Agent", "finding": "Keep maintenance holds non-negotiable and cap alternate ride redirects."},
            {"name": "Guest Flow Agent", "finding": "Split guests across attractions, shows, food, and covered paths."},
            {"name": "Staffing Agent", "finding": "Use crowd-control staff without violating certified operator minimums."},
            {"name": "Food Agent", "finding": "Route demand toward available inventory and update mobile-order promises."},
            {"name": "Energy Agent", "finding": "Do not reduce HVAC in dense indoor shelter zones."},
            {"name": "Decision Bridge Agent", "finding": "Produce a bounded action plan with owners, deadlines, and tradeoffs."},
            {"name": "GCP Eval Judge", "finding": "Score groundedness, safety, staff stress, capacity awareness, and actionability."},
        ],
    }


async def acknowledge_park_signal(signal_id: str, partner: str, status: str, response: dict[str, Any] | None = None) -> dict[str, Any]:
    response = response or {}
    for signal in _park_signals:
        if signal["id"] == signal_id:
            signal["status"] = status
            signal["acknowledged_by"] = partner
            signal["response"] = response
            signal["acknowledged_at"] = _utc_now()
            return {"status": "success", "signal_id": signal_id, "partner": partner, "ack_status": status, "response": response}
    return {"status": "not_found", "signal_id": signal_id, "partner": partner, "ack_status": status, "response": response}


def _signals_for_scenario(scenario_key: str, state: dict[str, Any], fast_eval: bool) -> list[dict[str, Any]]:
    now = _utc_now()
    signal_map = {
        "ride_down": [
            ("park-sig-ride-down", "Ride Ops", "Pause Dragon Coaster intake and require maintenance clearance before reopening.", "critical"),
            ("park-sig-guest-flow", "Guest Flow", "Split affected guests across Sky Drop, Theater B, Arcade Zone, and food offers.", "warning"),
            ("park-sig-staff", "Staffing", "Move crowd-control staff to Coaster Plaza without pulling certified operators.", "warning"),
        ],
        "staff_shortage": [
            ("park-sig-breaks", "Staffing", "Protect break windows and reduce lower-priority throughput.", "critical"),
            ("park-sig-food-labor", "Food Ops", "Simplify food menu and redirect orders to lower-load locations.", "warning"),
        ],
        "food_spike": [
            ("park-sig-inventory", "Food Ops", "Suppress constrained SKUs and promote Food Court B capacity.", "critical"),
            ("park-sig-eta", "Guest Experience", "Correct pickup promises before accepting more mobile orders.", "warning"),
        ],
        "storm_response": [
            ("park-sig-storm", "Weather", "Taper exposed outdoor queues before storm arrival.", "critical"),
            ("park-sig-hvac", "Energy", "Protect HVAC in indoor shelter zones.", "warning"),
        ],
    }
    scenario = state.get("guestFlow", {}).get("activeScenario", {})
    return [
        {
            "id": signal_id,
            "domain": "amusement_park_operations",
            "scenario": scenario.get("key", scenario_key),
            "recipient": recipient,
            "subject": subject,
            "severity": severity,
            "requires_ack": severity == "critical",
            "status": "created",
            "created_at": now,
            "fast_eval": fast_eval,
        }
        for signal_id, recipient, subject, severity in signal_map.get(scenario_key, signal_map["ride_down"])
    ]
