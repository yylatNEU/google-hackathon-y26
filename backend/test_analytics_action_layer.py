import asyncio

from analytics_action_layer import build_analytics_to_action_layer
from park_simulation import park_simulation
from synthetic_park_runner import find_synthetic_example, injection_plan_for_example


def run(coro):
    return asyncio.run(coro)


def test_analytics_action_layer_turns_live_pressure_into_owned_actions():
    run(park_simulation.reset_demo())
    state = run(park_simulation.get_state())

    layer = build_analytics_to_action_layer(state)

    assert layer["mode"] == "analytics_to_governed_action_v1"
    assert layer["coverage"]["signal_count"] >= 1
    assert layer["opportunities"]
    first = layer["opportunities"][0]
    assert first["owner_agent"]
    assert first["analytics_signal"]["evidence"]
    assert first["proposed_action"]["label"]
    assert first["verification"]["metric"]
    assert any(action["system"] == "digital_twin" for action in first["system_actions"])
    assert layer["conflict_board"]["mode"] == "multi_object_action_conflict_board_v1"
    assert layer["coverage"]["conflict_count"] >= 1


def test_analytics_action_layer_prioritizes_synthetic_safety_incident():
    run(park_simulation.reset_demo())
    example = find_synthetic_example("SYN-MIXED-CONFLICT-001")
    try:
        run(park_simulation.inject_synthetic_incident(injection_plan_for_example(example)))
        state = run(park_simulation.get_state())

        layer = build_analytics_to_action_layer(state)
        first = layer["opportunities"][0]
        systems = {action["system"] for action in first["system_actions"]}

        assert first["priority"] == "P0"
        assert first["owner_agent"] == "Guest Care + Security Agent"
        assert first["policy_gate"] == "approval_required"
        assert first["approval"]["required"] is True
        assert {"digital_twin", "worker_device", "guest_app", "map"}.issubset(systems)
        conflict = layer["conflict_board"]["conflicts"][0]
        assert conflict["id"] == "conflict_safety_vs_throughput"
        assert "Freeze optimization" in conflict["selected_resolution"]
        assert "broad queue" in conflict["rejected_action"]
    finally:
        run(park_simulation.reset_demo())
