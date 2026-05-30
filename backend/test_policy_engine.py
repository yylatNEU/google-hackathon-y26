from __future__ import annotations

from copy import deepcopy

from policy_engine import PolicyEngine, policy_compliance_for_action
from park_action_bridge import build_park_action_plan


def sample_state() -> dict:
    return {
        "weather": {"stormRisk": 80},
        "guestFlow": {
            "activeScenario": {"key": "ride_down", "name": "Ride Down"},
            "rides": [{"name": "Dragon Coaster", "status": "down"}],
            "zones": [{"id": "coaster-plaza", "density": 72}],
        },
    }


def test_policy_engine_resolves_refs_from_policybook():
    compliance = policy_compliance_for_action("ride", "reroute")

    assert compliance["status"] == "allowed"
    assert "PARK-SAFE-001" in compliance["policy_refs"]
    assert "PARK-OPS-001" in compliance["policy_refs"]
    assert "PARK-EXP-001" in compliance["policy_refs"]


def test_policy_engine_blocks_dangerous_actions():
    engine = PolicyEngine()
    result = engine.evaluate_action(
        {
            "title": "Reopen Dragon Coaster without clearance",
            "park_action": {"target": "ride", "action": "reopen"},
            "policy_compliance": {"policy_refs": ["PARK-SAFE-001"]},
        },
        sample_state(),
        {"evals": [{"label": "Safety", "score": 95}]},
    )

    assert result["status"] == "blocked"
    assert "PARK-SAFE-001" in result["policy_refs"]
    assert any("maintenance clearance" in message or "reopening" in message for message in result["violations"])


def test_policy_engine_blocks_unknown_refs():
    engine = PolicyEngine()
    result = engine.evaluate_action(
        {
            "title": "Route guests to lower wait zones",
            "park_action": {"target": "traffic", "action": "redirect_food"},
            "policy_compliance": {"policy_refs": ["UNKNOWN-REF"]},
        },
        sample_state(),
    )

    assert result["status"] == "blocked"
    assert result["unknown_policy_refs"] == ["UNKNOWN-REF"]


def test_policy_engine_blocks_labor_routing_energy_and_guest_violations():
    engine = PolicyEngine()
    state = sample_state()

    labor = engine.evaluate_action(
        {"title": "Delay breaks", "park_action": {"target": "staff", "action": "delay_breaks"}, "policy_compliance": {"policy_refs": ["PARK-LABOR-002"]}},
        state,
    )
    route_all = engine.evaluate_action(
        {"title": "Route all guests to Arcade", "park_action": {"target": "traffic", "action": "route_all"}, "policy_compliance": {"policy_refs": ["PARK-OPS-002"]}},
        state,
    )
    energy = engine.evaluate_action(
        {"title": "Reduce HVAC in shelter", "park_action": {"target": "energy", "action": "reduce_hvac"}, "policy_compliance": {"policy_refs": ["PARK-EQUIP-002"]}},
        state,
    )
    guest = engine.evaluate_action(
        {"title": "Named guest compensation", "park_action": {"target": "guest", "action": "personal_compensation"}, "policy_compliance": {"policy_refs": ["PARK-CARE-001"]}},
        state,
    )

    assert labor["status"] == "blocked"
    assert route_all["status"] == "blocked"
    assert energy["status"] == "blocked"
    assert guest["status"] == "blocked"


def test_policy_engine_refs_follow_policybook_metadata():
    engine = PolicyEngine(
        {
            "policy_books": [
                {
                    "source": "custom",
                    "content": {
                        "policy_book_id": "custom_policy_book",
                        "decision_rules": [
                            {
                                "id": "CUSTOM-RIDE-001",
                                "applies_to": {"targets": ["ride"], "actions": ["reroute"]},
                                "allowed_action": "Custom ride rule.",
                            }
                        ],
                    },
                }
            ]
        }
    )

    assert engine.refs_for_action("ride", "reroute") == ["CUSTOM-RIDE-001"]
    assert engine.refs_for_action("staff", "redeploy") == []


def test_scenario_scoped_refs_do_not_leak_without_active_scenario():
    engine = PolicyEngine(
        {
            "policy_books": [
                {
                    "source": "custom",
                    "content": {
                        "policy_book_id": "custom_policy_book",
                        "decision_rules": [
                            {
                                "id": "CUSTOM-STORM-001",
                                "applies_to": {
                                    "targets": ["energy"],
                                    "actions": ["protect_hvac"],
                                    "scenarios": ["storm_response"],
                                },
                                "allowed_action": "Protect shelter HVAC during storm response.",
                            }
                        ],
                    },
                }
            ]
        }
    )

    assert engine.refs_for_action("energy", "protect_hvac") == []
    assert engine.refs_for_action("energy", "protect_hvac", {"key": "ride_down"}) == []
    assert engine.refs_for_action("energy", "protect_hvac", {"key": "storm_response"}) == ["CUSTOM-STORM-001"]


def test_policy_context_for_planner_is_rule_based():
    context = PolicyEngine().policy_context_for_planner({"key": "storm_response"})

    assert context["scenario_key"] == "storm_response"
    assert "PARK-SAFE-002" in context["policy_refs"]
    assert any(rule["id"] == "PARK-EQUIP-002" for rule in context["rules"])


def test_generated_action_plan_policy_contract_is_clean():
    plan = build_park_action_plan(sample_state())

    assert plan["policy_contract"]["status"] == "clean"
    assert PolicyEngine().validate_plan(plan)["status"] == "clean"


def test_policy_contract_rejects_missing_and_extra_refs():
    engine = PolicyEngine()
    plan = build_park_action_plan(sample_state())

    missing = deepcopy(plan)
    selected_refs = missing["selected_action"]["policy_compliance"]["policy_refs"]
    selected_refs.remove("PARK-SAFE-001")
    missing_contract = engine.validate_plan(missing)

    extra = deepcopy(plan)
    extra["selected_action"]["policy_compliance"]["policy_refs"].append("PARK-EQUIP-002")
    extra_contract = engine.validate_plan(extra)

    assert missing_contract["status"] == "invalid"
    assert "PARK-SAFE-001" in missing_contract["selected_action"]["missing_policy_refs"]
    assert extra_contract["status"] == "invalid"
    assert "PARK-EQUIP-002" in extra_contract["selected_action"]["unexpected_policy_refs"]


def test_runtime_gate_blocks_tampered_policy_contract():
    from park_governance_runtime import build_runtime_action, supervise_runtime_action

    state = sample_state()
    action_doc = build_runtime_action("ride", "reroute", title="Reroute queue", scenario=state["guestFlow"]["activeScenario"])
    action_doc["policy_compliance"]["policy_refs"].remove("PARK-SAFE-001")

    gate = supervise_runtime_action(
        action_doc,
        state,
        eval_result={"evals": [{"label": "Safety", "score": 95}, {"label": "Capacity", "score": 95}]},
    )

    assert gate["allowed"] is False
    assert gate["gate_status"] == "blocked"
    assert gate["policy_contract"]["status"] == "invalid"
    assert "PARK-SAFE-001" in gate["policy_contract"]["missing_policy_refs"]
