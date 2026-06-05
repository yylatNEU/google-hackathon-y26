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


def chat(message, prior=None, *, turn_mode="auto", allow_action=True, messages=None):
    context = {"last_copilot": prior} if prior else {}
    return run(
        parkpulse_api.park_copilot_chat(
            parkpulse_api.CopilotChatRequest(
                message=message,
                messages=messages or [],
                turn_mode=turn_mode,
                allow_action=allow_action,
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


def test_copilot_rejects_apply_without_prior_plan(monkeypatch):
    _disable_llm(monkeypatch)

    response = chat("do it", turn_mode="apply", allow_action=True)
    assert_read_only(response, "clarification.none")
    assert response["conversation_memory"]["conversation_intent"] == "clarification"
    assert response["recommended_action"]["dispatch_count"] == 0
    assert response["action_receipt"] is None


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


def test_copilot_followup_reuses_prior_receipt_without_mutation(monkeypatch):
    _disable_llm(monkeypatch)

    prior = chat("The coaster queue is too long and families are stuck near the parade. What should we do?")
    followup = chat(
        "why that plan?",
        prior=prior,
        messages=[
            {"role": "user", "content": "The coaster queue is too long and families are stuck near the parade. What should we do?"},
            {"role": "assistant", "content": prior["answer"]},
        ],
    )
    assert followup["mode"] == "follow_up"
    assert followup["conversation_memory"]["followup_of_previous_run"] is True
    assert followup["turn_contract"]["state_mutation"] is False
    assert followup["turn_contract"]["dispatch_count"] == 0
    assert followup["action_receipt"] is None
    assert followup["recommended_action"]["matched_case_id"] == prior["recommended_action"]["matched_case_id"]
    assert followup["recommended_action"]["object_action_plan_id"] == prior["recommended_action"]["object_action_plan_id"]
    assert followup["tool_call_timeline"][-1]["id"] == "answer_operator"


def test_copilot_revision_followup_does_not_start_new_action_plan(monkeypatch):
    _disable_llm(monkeypatch)

    prior = chat("The coaster queue is too long and families are stuck near the parade. What should we do?")
    followup = chat("change it to avoid the parade crowd", prior=prior)

    assert followup["mode"] == "follow_up"
    assert followup["conversation_memory"]["followup_of_previous_run"] is True
    assert followup["turn_contract"]["state_mutation"] is False
    assert followup["turn_contract"]["dispatch_count"] == 0
    assert followup["action_receipt"] is None
    assert followup["recommended_action"]["matched_case_id"] == prior["recommended_action"]["matched_case_id"]
    assert "prior selected action" in followup["answer"].lower()


def test_copilot_apply_turn_requires_explicit_action_permission(monkeypatch):
    _disable_llm(monkeypatch)

    prior = chat("The coaster queue is too long and families are stuck near the parade. What should we do?")
    response = chat("apply", prior=prior, turn_mode="apply", allow_action=False)
    assert response["mode"] == "propose"
    assert response["conversation_memory"]["conversation_intent"] == "apply_plan"
    assert response["turn_contract"]["state_mutation"] is False
    assert response["turn_contract"]["dispatch_count"] == 0
    assert response["recommended_action"]["gate"] in {"prepared", "approval_required"}
    assert response["object_action_plan"]["will_execute"] is False
    assert response["action_receipt"] is None
    assert response["impact_replay"] is None


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


def test_copilot_includes_semantic_memory_context_when_enabled(monkeypatch):
    _disable_llm(monkeypatch)
    monkeypatch.setenv("PARKPULSE_COPILOT_SEMANTIC_MEMORY", "true")

    def fake_retrieve_context(query, state, limit, agent_role, cache_policy, persist_trace):
        assert cache_policy == "role_cache_only"
        return {
            "status": {
                "mode": "demo_fallback",
                "connected": False,
                "modelApi": {
                    "provider": "voyage",
                    "configured": True,
                    "enabled": True,
                    "model": "voyage-4-lite",
                    "dimensions": 256,
                    "vectorPath": "modelEmbedding",
                },
            },
            "query": query,
            "scenario_key": "ride_down",
            "agent_role": agent_role,
            "retrieved": {
                "method": "mongodb_vector_search_voyage",
                "playbooks": [{"_id": "pb-1", "title": "Ride queue split", "score": 0.91}],
                "incidents": [{"_id": "inc-1", "summary": "Prior parade congestion incident", "score": 0.88}],
                "learnings": [{"_id": "learn-1", "lesson": "Avoid routing families through parade edge."}],
            },
            "summary": "Retrieved memory for react from provider embeddings.",
        }

    monkeypatch.setattr(parkpulse_api, "retrieve_operational_context", fake_retrieve_context)

    response = chat("The coaster queue is too long and families are stuck near the parade. What should we do?")

    semantic = response["semantic_memory_context"]
    assert semantic["status"] == "ready"
    assert semantic["model_api"]["provider"] == "voyage"
    assert semantic["retrieval_method"] == "mongodb_vector_search_voyage"
    assert semantic["counts"] == {"playbooks": 1, "incidents": 1, "learnings": 1}
    assert response["conversation_response"]["semantic_memory"]["status"] == "ready"
    assert any(item["tool"] == "memory.retrieve_semantic_context" for item in response["tool_call_timeline"])
    assert response["conversation_memory"]["semantic_memory_status"] == "ready"


def test_copilot_semantic_memory_marks_model_text_fallback_degraded(monkeypatch):
    _disable_llm(monkeypatch)
    monkeypatch.setenv("PARKPULSE_COPILOT_SEMANTIC_MEMORY", "true")

    def fake_retrieve_context(query, state, limit, agent_role, cache_policy, persist_trace):
        return {
            "status": {
                "modelApi": {
                    "provider": "voyage",
                    "configured": True,
                    "enabled": True,
                    "model": "voyage-4-lite",
                    "dimensions": 256,
                    "vectorPath": "modelEmbedding",
                },
            },
            "query": query,
            "scenario_key": "ride_down",
            "agent_role": agent_role,
            "cache_policy": cache_policy,
            "retrieved": {
                "method": "mongodb_text_search",
                "playbooks": [{"_id": "pb-1", "title": "Ride queue split"}],
                "incidents": [],
                "learnings": [],
            },
            "summary": "Retrieved memory via text fallback.",
        }

    monkeypatch.setattr(parkpulse_api, "retrieve_operational_context", fake_retrieve_context)

    response = chat("The coaster queue is too long. What should we do?")

    semantic = response["semantic_memory_context"]
    assert semantic["status"] == "degraded"
    assert semantic["retrieval_method"] == "mongodb_text_search"
    assert semantic["readiness_issues"]
    assert response["conversation_memory"]["semantic_memory_status"] == "degraded"
