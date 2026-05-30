import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import main  # noqa: E402


def _payload_for(message: str) -> dict:
    return main._lazy_operator_payload(message)


def _dispatch_text(payload: dict) -> str:
    dispatches = payload["run_telemetry"]["delivery"]["dispatches"]
    return json.dumps(dispatches, sort_keys=True).lower()


def _constraints(payload: dict) -> dict:
    return payload["operator_constraints"]


def _roles(payload: dict) -> set[str]:
    return {move["role"] for move in _constraints(payload)["required_staff_moves"]}


def test_food_court_down_uses_food_receivers_without_stale_ride_copy():
    payload = _payload_for("Food court is down, do not send people there. Redirect mobile orders and workers.")
    text = _dispatch_text(payload)
    constraints = _constraints(payload)

    assert payload["route"]["scenario_key"] == "food_spike"
    assert constraints["avoid_zones"][0]["name"] == "Food Court A"
    assert "food court a" in text
    assert "food court b" in text
    assert "main street" in text
    assert "dragon coaster" not in text
    assert payload["run_telemetry"]["delivery"]["summary"]["guest_app"] == 1
    assert payload["run_telemetry"]["delivery"]["summary"]["worker_device"] == 1
    assert payload["run_telemetry"]["delivery"]["summary"]["equipment_controller"] == 1


def test_medical_and_accessibility_prompt_dispatches_guest_care_privately():
    payload = _payload_for("Someone fainted near Food Court A. Medical team and wheelchair assistance needed.")
    text = _dispatch_text(payload)
    constraints = _constraints(payload)

    assert constraints["requires_human_review"] is True
    assert constraints["inferred_incident_type"] == "medical_accessibility"
    assert {"medical", "accessibility_support"}.issubset(_roles(payload))
    assert payload["run_telemetry"]["planner"]["selected_action"]["target"] == "medical"
    assert "privacy" in text
    assert "access lane" in text
    assert "dragon coaster" not in text


def test_food_and_hvac_prompt_emits_both_menu_and_hvac_controls():
    payload = _payload_for("HVAC too cold in indoor hub but food line is overheating near Food Court A.")
    text = _dispatch_text(payload)
    equipment_types = {
        control["equipmentType"]
        for control in _constraints(payload)["equipment_controls"]
    }

    assert {"menu_control", "hvac"}.issubset(equipment_types)
    assert "suppress_mobile_order_intake" in text
    assert "apply_custom_comfort_mix" in text
    assert "foodcourta" in text
    assert "indoorhub" in text
    assert "dragon coaster" not in text


def test_family_care_prompt_routes_to_calm_family_destinations():
    payload = _payload_for("Kids are scared and parents are angry near the haunted zone. Send help and avoid scary routes.")
    text = _dispatch_text(payload)
    constraints = _constraints(payload)

    segments = {segment["segment"] for segment in constraints["guest_segments"]}
    destinations = {destination["name"] for destination in constraints["preferred_destinations"]}

    assert "families_with_children" in segments
    assert {"Theater B", "Family Garden"}.issubset(destinations)
    assert "calmer route" in text
    assert "family garden" in text
    assert "dragon coaster" not in text


def test_panic_evacuation_prompt_prioritizes_security_and_clear_paths():
    payload = _payload_for("Panic evacuation near maze exit, send security and keep emergency paths clear.")
    text = _dispatch_text(payload)
    constraints = _constraints(payload)

    assert constraints["requires_human_review"] is True
    assert "security" in _roles(payload)
    assert constraints["inferred_incident_type"] == "crowd_safety"
    assert "keep_access_lane_clear" in text
    assert "security" in text
    assert "dragon coaster" not in text
