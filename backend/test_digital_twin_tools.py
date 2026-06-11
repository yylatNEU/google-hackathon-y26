from __future__ import annotations

import os
from copy import deepcopy

os.environ.setdefault("MONGODB_DISABLE_DRIVER_IMPORT", "1")
os.environ.setdefault("ENABLE_BIGQUERY_ANALYTICS", "false")
os.environ.setdefault("PARKPULSE_ENABLE_OTEL_SPANS", "false")
os.environ.setdefault("PARKPULSE_MONGO_MODEL_EMBEDDINGS", "false")

from digital_twin_tools import build_digital_twin_tool_trace, list_digital_twin_tools, run_digital_twin_tool
from park_simulation import ParkSimulation


_CACHED_STATE = None


def _state():
    global _CACHED_STATE
    import asyncio

    if _CACHED_STATE is None:
        _CACHED_STATE = asyncio.run(ParkSimulation().get_state())
    return deepcopy(_CACHED_STATE)


def test_tool_registry_exposes_mcp_style_digital_twin_tools():
    registry = list_digital_twin_tools()

    names = {tool["name"] for tool in registry["tools"]}

    assert registry["server"] == "parkpulse.digital_twin"
    assert "simulate_action" in names
    assert "tick_simulation" in names
    assert "get_noisy_observation" in names
    assert "score_outcome" in names
    assert "compare_action_candidates" in names
    assert "validate_policy" in names
    assert "dispatch_guest_message" in names


def test_simulate_action_projects_state_movement():
    state = _state()

    result = run_digital_twin_tool("simulate_action", state, {"target": "ride", "action": "reroute"})

    assert result["tool"] == "simulate_action"
    assert result["output"]["status"] == "ok"
    assert result["output"]["source"] == "stateful_stress_transition_model"
    assert result["output"]["projected_impact"]["movedGuests"] > 0
    assert result["output"]["projected_impact"]["densityDeltaPct"] != 0
    assert result["output"]["projected_impact"]["guestSatisfactionDelta"] > 0
    assert result["output"]["checkpoints"]
    assert result["output"]["uncertainty"]["drivers"]


def test_simulate_action_handles_malformed_action_payload_without_crashing():
    import asyncio

    state = _state()

    tool_result = run_digital_twin_tool("simulate_action", state, {"action_plan": "reroute now"})
    direct_result = asyncio.run(ParkSimulation().simulate_action([{"target": "ride", "action": "reroute"}], 5))
    policy_result = run_digital_twin_tool("validate_policy", state, {"park_action": []})
    quality_result = run_digital_twin_tool("score_decision_quality", state, {"decision": {"selected_action": {"park_action": []}}})
    memory_result = run_digital_twin_tool("retrieve_similar_incidents", state, {}, {"retrieved": []})

    assert tool_result["output"]["status"] == "ok"
    assert tool_result["output"]["outcome"]["action"]["action"] == "natural"
    assert direct_result["status"] == "ok"
    assert direct_result["outcome"]["action"]["action"] == "natural"
    assert policy_result["output"]["status"] == "ok"
    assert quality_result["output"]["status"] == "ok"
    assert memory_result["output"]["status"] == "ok"


def test_noisy_observation_hides_perfect_ground_truth():
    state = _state()

    result = run_digital_twin_tool("get_noisy_observation", state, {"seed": "unit-test"})

    assert result["output"]["mode"] == "noisy_partial_observation"
    assert result["output"]["hidden_truth_available_to"] == "evaluator_only"
    assert result["output"]["staleness_seconds"]["queue_camera"] >= 20


def test_policy_gate_keeps_safety_adjacent_actions_under_human_authority():
    state = _state()

    result = run_digital_twin_tool(
        "validate_policy",
        state,
        {"target": "ride", "action": "reroute", "label": "Pause intake and reroute"},
    )

    assert result["output"]["allowed"] is True
    assert result["output"]["gate_status"] == "pending_operator_approval"
    assert "ride reopening and safety clearance" in result["output"]["human_authority"]


def test_full_trace_separates_read_simulate_gate_and_score_steps():
    state = _state()

    trace = build_digital_twin_tool_trace(state, "ride_down", {}, {}, None)
    tools = [call["tool"] for call in trace["tool_calls"]]

    assert trace["server"] == "parkpulse.digital_twin"
    assert trace["tool_count"] >= 9
    assert "get_park_state" in tools
    assert "simulate_action" in tools
    assert "get_noisy_observation" in tools
    assert "validate_policy" in tools
    assert "score_decision_quality" in tools
    assert trace["summary"]["policy_gate"] in {"allowed", "pending_operator_approval", "blocked"}
