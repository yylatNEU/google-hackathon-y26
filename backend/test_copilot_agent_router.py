import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("MONGODB_DISABLE_DRIVER_IMPORT", "1")

import parkpulse_api


def run(coro):
    return asyncio.run(coro)


def _disable_llm(monkeypatch):
    monkeypatch.setattr(
        parkpulse_api,
        "get_gemini_agent_properties",
        lambda: SimpleNamespace(ready=False, readiness_issues=["unit test"], model=None, platform="unit"),
    )


def chat(message, prior=None):
    context = {"last_copilot": prior} if prior else {}
    return run(
        parkpulse_api.park_copilot_chat(
            parkpulse_api.CopilotChatRequest(
                message=message,
                turn_mode="auto",
                allow_action=True,
                selected_map_context=context,
            )
        )
    )


def assert_read_only(response, tool):
    assert response["mode"] == "answer"
    assert response["recommended_action"]["gate"] == "read_only"
    assert response["recommended_action"]["dispatch_count"] == 0
    assert response["turn_contract"]["state_mutation"] is False
    assert response["turn_contract"]["map_effect"] == "none"
    assert response["tool_trace"]["tool_calls"][0]["tool"] == tool


def test_copilot_answers_read_only_tools(monkeypatch):
    _disable_llm(monkeypatch)

    queues = chat("give me the queue of all rides")
    assert_read_only(queues, "queues.read_ride_waits")
    assert "Dragon Coaster" in queues["answer"]

    distance = chat("distance from entrance to dragon coaster")
    assert_read_only(distance, "map.calculate_distance")
    assert "677 meters" in distance["answer"]
    assert distance["synthetic_park_context"]["primary_example"]["id"] == "SYN-MAP-DISTANCE-001"
    assert distance["tool_trace"]["tool_calls"][1]["tool"] == "synthetic_park_knowledge.retrieve"

    distance_paraphrase = chat("how far is the coaster from the front gate")
    assert_read_only(distance_paraphrase, "map.calculate_distance")
    assert distance_paraphrase["synthetic_park_context"]["primary_example"]["id"] == "SYN-MAP-DISTANCE-001"

    problem = chat("what's the problem in the park")
    assert_read_only(problem, "park.rank_current_risks")
    assert "Primary risk" in problem["answer"]

    staffing = chat("staffing status")
    assert_read_only(staffing, "staffing.read_status")
    assert "Staffing status" in staffing["answer"]

    weather = chat("weather status")
    assert_read_only(weather, "weather.read_status")
    assert "Weather status" in weather["answer"]


def test_copilot_clarifies_ambiguous_text_without_action(monkeypatch):
    _disable_llm(monkeypatch)

    response = chat("hello")
    assert_read_only(response, "clarification.none")
    assert response["recommended_action"]["label"] == "Clarification required"
    assert "split flow" not in response["answer"].lower()
    assert response["object_action_plan"]["overall_gate"] == "read_only"


def test_copilot_only_proposes_for_explicit_operating_problem(monkeypatch):
    _disable_llm(monkeypatch)

    response = chat("The coaster queue is too long and families are stuck near the parade. What should we do?")
    assert response["mode"] == "propose"
    assert response["recommended_action"]["gate"] == "prepared"
    assert response["recommended_action"]["matched_case_id"] == "CASE-RIDE-DOWN-PARADE-001"
    assert "PARK-ACT-001" in response["recommended_action"]["policy_refs"]
    assert response["recommended_action"]["policy_selected_action"]
    assert response["object_action_plan"]["policy_doctrine"]["primary_case"]["id"] == "CASE-RIDE-DOWN-PARADE-001"
    assert len(response["policy_reasoning"]["steps"]) == 9
    assert response["tool_call_timeline"][0]["tool"] == "policy.retrieve_actionable_case"
    assert response["tool_call_timeline"][1]["tool"] == "policy.interpret_before_action"
    assert response["turn_contract"]["state_mutation"] is False
    assert "Proposed plan" in response["answer"]


def test_copilot_does_not_downgrade_action_shaped_problem_to_status(monkeypatch):
    _disable_llm(monkeypatch)

    response = chat("What is the biggest operational problem in the park right now, and what bounded action should we take?")
    assert response["mode"] == "propose"
    assert response["recommended_action"]["gate"] in {"prepared", "approval_required"}
    assert response["recommended_action"]["label"] != "Park status report"
    assert response["turn_contract"]["state_mutation"] is False
    assert response["object_action_plan"]["actions"]
    assert any(
        action.get("action") and action.get("action") != "inspect"
        for action in response["object_action_plan"]["actions"]
    )
    assert "Gate is" in response["answer"] or "no dispatch" in response["answer"].lower()


def test_copilot_routes_missing_child_at_foodcourt_to_safety_case(monkeypatch):
    _disable_llm(monkeypatch)

    response = chat("report show a missing kid at the foodcourt")
    assert response["mode"] == "propose"
    assert response["recommended_action"]["matched_case_id"] == "CASE-LOST-CHILD-FOODCOURT-001"
    assert response["recommended_action"]["gate"] in {"approval_required", "prepared"}
    assert response["tool_call_timeline"][0]["tool"] == "policy.retrieve_actionable_case"
    assert response["tool_call_timeline"][1]["tool"] == "policy.interpret_before_action"
    assert response["turn_contract"]["state_mutation"] is False
    assert "Food operations status" not in response["answer"]
    assert "Policy allows" in response["answer"]
    assert "It blocks" in response["answer"]
    assert "Evidence required" in response["answer"]
    assert "I need one confirmation" in response["answer"]
    assert "guest-care/security rather than food operations" in response["answer"]
    deliberation = response["agent_runtime"]["multi_agent_deliberation"]
    action_layer = response["agent_runtime"]["analytics_action_layer"]
    branch_comparison = response["agent_runtime"]["branch_comparison"]
    assert deliberation["matched_case_id"] == "CASE-LOST-CHILD-FOODCOURT-001"
    assert deliberation["supervisor"]["selected_agent"] == "Guest Care + Security Agent"
    assert deliberation["handoff"]["to"] == "Guest Care + Security Agent"
    assert "Policy Agent" in [agent["name"] for agent in deliberation["specialists"]]
    assert deliberation["critic"]["required_fixes_before_apply"]
    assert deliberation["audit"]["all_specialists_have_confidence"] is True
    assert action_layer["mode"] == "analytics_to_governed_action_v1"
    assert action_layer["opportunities"]
    assert action_layer["opportunities"][0]["system_actions"]
    assert branch_comparison["mode"] == "three_branch_realism_comparison"
    assert {branch["id"] for branch in branch_comparison["branches"]} == {"no_action", "bad_metric_action", "governed_agent_action"}


def test_copilot_routes_researched_case_study_incidents(monkeypatch):
    _disable_llm(monkeypatch)

    examples = [
        ("unattended bag found near the queue", "CASE-SECURITY-UNATTENDED-BAG-001"),
        ("lifeguard rescue in the wave pool", "CASE-WATERPARK-LIFEGUARD-RESCUE-001"),
        ("partial power outage and lights out near rides", "CASE-POWER-OUTAGE-RIDES-001"),
        ("operator text contains phone number and guest name pii", "CASE-PRIVACY-PII-IN-OPERATOR-TEXT-001"),
    ]
    for message, expected_case in examples:
        response = chat(message)
        assert response["mode"] == "propose"
        assert response["recommended_action"]["matched_case_id"] == expected_case
        assert len(response["policy_reasoning"]["steps"]) == 9


def test_copilot_routes_semantic_paraphrases_and_conflict_priority(monkeypatch):
    _disable_llm(monkeypatch)

    examples = [
        ("child separated from parents near restaurant", "CASE-LOST-CHILD-FOODCOURT-001"),
        ("blackout around coaster and no power in that area", "CASE-POWER-OUTAGE-RIDES-001"),
        ("someone collapsed and cannot breathe by the queue", "CASE-MEDICAL-CHEST-PAIN-001"),
        ("backpack left unclaimed near coaster line", "CASE-SECURITY-UNATTENDED-BAG-001"),
        ("child separated near restaurant while food orders are backed up and coaster queue is long", "CASE-LOST-CHILD-FOODCOURT-001"),
    ]
    for message, expected_case in examples:
        response = chat(message)
        assert response["mode"] == "propose"
        assert response["recommended_action"]["matched_case_id"] == expected_case
        assert len(response["policy_reasoning"]["steps"]) == 9


def test_copilot_multi_agent_supervisor_prioritizes_safety_over_adjacent_domains(monkeypatch):
    _disable_llm(monkeypatch)

    response = chat("child separated near restaurant while food orders are backed up and coaster queue is long")
    deliberation = response["multi_agent_deliberation"]
    synthetic = response["synthetic_park_context"]
    assert response["recommended_action"]["matched_case_id"] == "CASE-LOST-CHILD-FOODCOURT-001"
    assert synthetic["primary_example"]["id"] == "SYN-MIXED-CONFLICT-001"
    assert synthetic["primary_example"]["expected_owner"] == "Guest Care + Security Agent"
    assert deliberation["supervisor"]["selected_agent"] == "Guest Care + Security Agent"
    assert deliberation["audit"]["synthetic_example_id"] == "SYN-MIXED-CONFLICT-001"
    priority = deliberation["supervisor"]["priority_order"]
    assert priority.index("Guest Care + Security Agent") < priority.index("Food Operations Agent")
    assert priority.index("Guest Care + Security Agent") < priority.index("Ride Safety Agent")
    assert deliberation["audit"]["disagreements"]


def test_copilot_multi_agent_routes_ride_incident_to_ride_safety_owner(monkeypatch):
    _disable_llm(monkeypatch)

    response = chat("coaster restraint alarm and riders stuck on ride, prepare evacuation support")
    deliberation = response["multi_agent_deliberation"]
    assert response["mode"] == "propose"
    assert deliberation["supervisor"]["selected_agent"] == "Ride Safety Agent"
    assert deliberation["supervisor"]["selected_domain"] == "ride_safety"
    assert "Policy Agent" in [agent["name"] for agent in deliberation["specialists"]]
    assert deliberation["critic"]["failure_modes"]
