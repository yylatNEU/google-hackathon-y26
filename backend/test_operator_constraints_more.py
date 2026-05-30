from __future__ import annotations

import park_operator_constraints as constraints


def sample_constraint_state():
    return {
        "guestFlow": {
            "zones": [
                {"id": "", "name": "", "area": ""},
                {"id": "foodCourt1", "name": "Food Court 1"},
                {"id": "arcadeZone", "name": "Arcade Zone"},
            ],
            "rides": [
                {"id": "theaterB", "name": "Theater B", "zone": "theaterB", "zoneName": "Theater Zone", "status": "normal", "waitMins": 8, "capacityPerHour": 900},
                {"id": "skyDrop", "name": "Sky Drop", "zone": "thrill", "zoneName": "Thrill", "status": "normal", "waitMins": 18, "capacityPerHour": 700},
                {"id": "downRide", "name": "Down Ride", "zone": "closed", "status": "down", "waitMins": 99, "capacityPerHour": 0},
            ],
        }
    }


def test_operator_constraint_text_helpers_and_extraction_edges():
    state = sample_constraint_state()

    assert constraints._near("send guests near arcade now", "missing", ("send",)) is False
    assert constraints._near("send guests near arcade now", "arcade", ("send",)) is True
    assert constraints._prefixed_intent("reroute to theater b", "missing", ("reroute",)) is False
    assert constraints._capacity_after_mention("food court a is full", "missing", ("full",)) is False

    parsed = constraints.extract_operator_constraints(
        "Avoid food because the kitchen backed up. Use arcade. Security fight near theater b. HVAC too hot for families and VIP guests.",
        state,
        {"requires_human_review": False},
    )
    assert any(item["id"] == "foodCourt1" for item in parsed["avoid_zones"])
    assert any(item["id"] == "arcadeZone" for item in parsed["preferred_destinations"])
    assert any(move["role"] == "security" for move in parsed["required_staff_moves"])
    assert any(segment["segment"] == "families_with_children" for segment in parsed["guest_segments"])
    assert any(segment["segment"] == "priority_pass_guests" for segment in parsed["guest_segments"])
    assert parsed["equipment_controls"][0]["equipmentType"] == "hvac"
    assert parsed["requires_human_review"] is True

    staff = constraints.extract_operator_constraints("Need staff to move people near arcade.", state)
    assert staff["required_staff_moves"][0]["role"] == "crowd_control"


def test_genai_merge_dedupe_and_primary_action_helpers():
    assert constraints.constraints_from_genai_understanding(None, "m") == {}
    genai = constraints.constraints_from_genai_understanding(
        {
            "intent_summary": "take rate and comfort",
            "avoid_zones": ["bad", {"id": "foodCourt1", "name": "Food Court A"}],
            "preferred_destinations": [{"name": "Theater B"}],
            "required_staff_moves": ["bad", {"role": "medical", "count": 2, "to_location": "First Aid"}],
            "equipment_controls": ["bad", {"equipment_type": "hvac", "zones": ["indoorHub"], "settings": {"indoorHubSetpointF": 71}}],
            "guest_segments": ["families"],
            "hard_constraints": ["no unsafe routing"],
            "soft_preferences": ["positive response"],
            "missing_facts": ["exact guest count"],
        },
        "medical comfort",
        {"requires_human_review": False},
    )
    assert genai["requires_human_review"] is True
    assert genai["avoid_zones"][0]["id"] == "foodCourt1"
    assert genai["equipment_controls"][0]["equipmentType"] == "hvac"

    local = {"avoid_zones": [{"id": "foodCourt1", "name": "Food Court A"}], "decision_rules": ["local"], "requires_human_review": False}
    assert constraints.merge_operator_constraints(local, {}) is local
    assert constraints.merge_operator_constraints({}, genai) is genai
    merged = constraints.merge_operator_constraints(local, genai)
    assert merged["source"] == "gemini_operator_understanding+local_constraint_compiler"
    assert merged["requires_human_review"] is True
    assert len(merged["avoid_zones"]) == 1
    assert constraints._dedupe_places([{}, {"id": "a"}, {"id": "a"}]) == [{"id": "a"}]

    assert constraints._objective_weights({"command": "hvac too cold"})["energy_comfort"] == 0.24
    assert constraints._objective_weights({"command": "increase take rate acceptance"})["take_rate"] == 0.24
    assert constraints._primary_operator_action({"required_staff_moves": [{"role": "security"}]}, "ride_down")[0] == "security"
    assert constraints._primary_operator_action({"equipment_controls": [{"equipmentType": "hvac"}]}, "ride_down")[0] == "energy"
    assert constraints._primary_operator_action({}, "food_spike")[0] == "food"
    assert constraints._primary_operator_action({}, "ride_down")[0] == "ride"


def test_apply_operator_constraints_candidate_edges():
    state = sample_constraint_state()
    assert constraints.apply_operator_constraints_to_optimization({"selected_plan": {"id": "p"}}, {}, state, "ride_down") == {"selected_plan": {"id": "p"}}

    avoid_keys = {constraints._norm("Food Court A"), constraints._norm("foodCourt1")}
    assert constraints._destination_for_place({"id": "firstAid", "name": "First Aid", "kind": "service"}, state, set()) is None
    assert constraints._fallback_targets(state, avoid_keys)[0]["destinationId"] == "theaterB"
    assert constraints._normalize_target_mix([{"destinationId": "a", "share": "bad"}, {"destinationId": "b", "share": 0}], 0.1)[0]["share"] == 0.22
    assert constraints._normalize_target_mix([{"destinationId": "a", "share": -1}, {"destinationId": "b", "share": -1}], 0.1)[0]["share"] == 0.41

    optimization = {
        "selected_plan_id": "p1",
        "selected_plan": {
            "id": "p1",
            "name": "Base",
            "action_mix": {
                "guest_reroute": {
                    "enabled": True,
                    "holdShare": 0.2,
                    "target_mix": [
                        {"destinationId": "foodCourt1", "destination": "Food Court A", "share": 0.6},
                    ],
                }
            },
            "scorecard": {"overall": 40, "safety": 80, "capacity_fit": 70, "take_rate_likelihood": 50},
        },
        "candidates": [
            "bad",
            {
                "id": "p2",
                "name": "Other",
                "action_mix": {"guest_reroute": {"enabled": False, "target_mix": []}},
                "scorecard": {"overall": 10},
            },
        ],
    }
    patched = constraints.apply_operator_constraints_to_optimization(
        optimization,
        {
            "command": "medical guest near theater b",
            "avoid_zones": [{"id": "foodCourt1", "name": "Food Court A"}],
            "preferred_destinations": [{"id": "theaterB", "name": "Theater B", "kind": "ride"}],
            "required_staff_moves": [{"role": "medical", "count": 2, "from": "First Aid", "to": "Theater B"}],
            "equipment_controls": [{"equipmentType": "hvac", "zones": ["indoorHub"], "settings": {"arcadeZoneSetpointF": 73}}],
            "guest_segments": [{"segment": "families"}],
            "safety_escalations": [{"type": "medical"}],
            "decision_rules": ["protect privacy"],
        },
        state,
        "ride_down",
    )
    assert patched["selected_action"]["target"] == "medical"
    assert patched["operator_candidate_frame"]["rejected_options"]
    assert patched["action_mix"]["guest_reroute"]["operatorConstraintAware"] is True
    assert all(target["destinationId"] != "foodCourt1" for target in patched["action_mix"]["guest_reroute"]["target_mix"])
    assert patched["action_mix"]["facilities"]["hvac"]["protectShelterComfort"] is True

    no_target = constraints.apply_operator_constraints_to_optimization(
        {
            "selected_plan": {
                "id": "p3",
                "name": "No route",
                "action_mix": {"guest_reroute": {"enabled": False}},
                "scorecard": {"overall": 50},
            },
            "candidates": [],
        },
        {"required_staff_moves": [{"role": "accessibility_support", "to": "Gate"}]},
        state,
        "ride_down",
    )
    assert no_target["action_mix"]["guest_reroute"]["enabled"] is False
    assert no_target["action_mix"]["guest_reroute"]["holdShare"] == 0.92
