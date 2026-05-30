import asyncio

from park_simulation import park_simulation
from synthetic_park_runner import find_synthetic_example, injection_plan_for_example, score_synthetic_copilot_response, synthetic_eval_cases


def run(coro):
    return asyncio.run(coro)


def test_synthetic_runner_builds_injection_plan_from_example():
    example = find_synthetic_example("SYN-MIXED-CONFLICT-001")
    plan = injection_plan_for_example(example)

    assert plan["kind"] == "lost_child"
    assert plan["target_id"] == "foodCourt1"
    assert plan["expected_owner"] == "Guest Care + Security Agent"
    assert plan["expected_case_id"] == "CASE-LOST-CHILD-FOODCOURT-001"


def test_synthetic_injection_adds_live_incident_overlay_to_park_state():
    run(park_simulation.reset_demo())
    example = find_synthetic_example("SYN-LOST-CHILD-001")
    plan = injection_plan_for_example(example)
    try:
        result = run(park_simulation.inject_synthetic_incident(plan))
        state = run(park_simulation.get_state())

        assert result["status"] == "success"
        incidents = state["incidentReadiness"]["activeSyntheticIncidents"]
        assert incidents[0]["id"] == "SYN-LOST-CHILD-001"
        assert incidents[0]["expectedOwner"] == "Guest Care + Security Agent"
        assert state["digitalTwin"]["syntheticScenario"]["active"] is True
        assert any(group["id"] == "incident_SYN-LOST-CHILD-001" for group in state["physicalMap"]["guestGroups"])
        assert any(station["id"] == "command_SYN-LOST-CHILD-001" for station in state["physicalMap"]["supportStations"])
    finally:
        run(park_simulation.reset_demo())


def test_synthetic_eval_scoring_checks_owner_case_gate_and_retrieval():
    eval_case = synthetic_eval_cases(limit_examples=12, utterances_per_example=1)[-1]
    response = {
        "mode": "propose",
        "answer": "Synthetic answer",
        "recommended_action": {"matched_case_id": eval_case["expected_case_id"], "gate": eval_case["expected_gate"]},
        "synthetic_park_context": {"primary_example": {"id": eval_case["example_id"], "expected_owner": eval_case["expected_owner"]}},
        "multi_agent_deliberation": {"supervisor": {"selected_agent": eval_case["expected_owner"]}},
    }
    score = score_synthetic_copilot_response(eval_case, response)

    assert score["passed"] is True
    assert score["score"] == 100
