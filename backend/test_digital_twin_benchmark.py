from __future__ import annotations

import asyncio

from digital_twin_benchmark import (
    attach_learning_comparison,
    build_benchmark_report,
    evaluate_benchmark_gate,
    generate_remediation_playbooks,
    latest_benchmark_report,
    list_benchmark_scenarios,
    read_benchmark_history,
    record_benchmark_result,
    run_digital_twin_benchmark,
    run_parkpulse_agent_benchmark,
)
from park_simulation import ParkSimulation


def _state():
    return asyncio.run(ParkSimulation().get_state())


def test_benchmark_lists_adversarial_scenarios():
    registry = list_benchmark_scenarios()

    assert registry["mode"] == "digital_twin_adversarial_benchmark"
    assert registry["scenario_count"] >= 5
    assert {item["id"] for item in registry["scenarios"]} >= {"ride_storm_cascade", "policy_gate_pressure"}


def test_benchmark_runs_single_episode_with_hidden_truth_and_policy_gate():
    result = run_digital_twin_benchmark(_state(), scenario_id="policy_gate_pressure", seed="unit", horizon_minutes=25)

    assert result["status"] == "complete"
    assert result["summary"]["episodes"] == 1
    episode = result["episodes"][0]
    assert episode["scenario"]["id"] == "policy_gate_pressure"
    assert episode["observation"]["mode"] == "noisy_partial_observation"
    assert episode["hidden_ground_truth"]["available_to"] == "evaluator_only"
    assert episode["candidate_results"]
    assert any(candidate["policy_gate"] == "blocked" for candidate in episode["candidate_results"])
    assert episode["selected_action"]["policy_gate"] != "blocked"
    assert episode["scorecard"]["decision_latency_seconds"] > 1
    assert [step["stage"] for step in episode["failure_trace"]] == [
        "noisy signal",
        "planner assumption",
        "selected action",
        "policy gate",
        "twin outcome",
        "regret",
    ]
    assert isinstance(episode["failure_modes"], list)


def test_benchmark_runs_full_suite_and_unknown_scenario_path():
    result = run_digital_twin_benchmark(_state(), seed="suite", horizon_minutes=30)

    assert result["status"] == "complete"
    assert result["summary"]["episodes"] >= 5
    assert result["summary"]["average_score"] > 0
    assert result["episodes"][0]["tool_trace"]["tools_used"] == [
        "get_noisy_observation",
        "simulate_action",
        "validate_policy",
        "score_outcome",
    ]

    missing = run_digital_twin_benchmark(_state(), scenario_id="missing")
    assert missing["status"] == "not_found"
    assert "ride_storm_cascade" in missing["available"]


def test_benchmark_regression_history_records_matching_runs(tmp_path):
    history_path = tmp_path / "benchmark-history.json"

    first = run_digital_twin_benchmark(_state(), seed="history-a", horizon_minutes=30)
    recorded_first = record_benchmark_result(first, history_path=history_path)
    assert recorded_first["regression"]["previous"] is None
    assert recorded_first["regression"]["current"]["episodes"] >= 5

    second = run_digital_twin_benchmark(_state(), seed="history-b", horizon_minutes=30)
    recorded_second = record_benchmark_result(second, history_path=history_path)
    assert recorded_second["regression"]["previous"]["seed"] == "history-a"
    assert "average_score" in recorded_second["regression"]["delta"]
    assert read_benchmark_history(history_path)["runs"][-1]["seed"] == "history-b"


def test_benchmark_generates_remediation_playbooks_and_learning_comparison():
    baseline = run_digital_twin_benchmark(_state(), seed="remediation-a", horizon_minutes=30)
    baseline["episodes"][0]["passed"] = False
    baseline["episodes"][0]["failure_modes"] = ["regret versus benchmark selector", "secondary risk remains high"]
    remediations = generate_remediation_playbooks(baseline)

    assert remediations
    assert remediations[0]["documentType"] == "agent_learning"
    assert remediations[0]["adjustment"]["requireEquipmentOrStaffAction"] is True
    assert "digital_twin" in remediations[0]["tags"]

    learned = run_digital_twin_benchmark(_state(), seed="remediation-b", horizon_minutes=30)
    compared = attach_learning_comparison(
        learned,
        baseline,
        remediations,
        {"status": "stored", "target": "agent_learnings", "learning_ids": ["learning-1"]},
    )
    assert compared["learned_rerun"]["remediations_generated"] == len(remediations)
    assert "score_delta" in compared["learned_rerun"]["comparison"]


def test_benchmark_report_artifact_and_gate(tmp_path):
    result = run_digital_twin_benchmark(_state(), seed="report-a", horizon_minutes=30)
    report = build_benchmark_report(result)

    assert report["mode"] == "digital_twin_benchmark_report"
    assert "readiness" in report
    assert "gate" in report

    strict_gate = evaluate_benchmark_gate(report, min_readiness=101, max_failed=0)
    assert strict_gate["passed"] is False
    assert strict_gate["reasons"]

    recorded = record_benchmark_result(result, history_path=tmp_path / "history.json", reports_dir=tmp_path / "reports")
    assert recorded["report_artifact"]["run_id"]
    latest = latest_benchmark_report(tmp_path / "reports")
    assert latest["mode"] == "digital_twin_benchmark_report"


def test_parkpulse_agent_benchmark_scores_real_policy_contract():
    async def fake_planner(state, scenario_key, context):
        return {
            "runtime": "unit_agent",
            "recommended_action": "Bounded reroute",
            "confidence_score": 84,
            "selected_action": {"target": "ride", "action": "reroute", "label": "Bounded reroute"},
            "candidate_actions": [],
        }

    def fake_optimizer(state, scenario_key, context, plan):
        return {
            "mode": "unit_optimizer",
            "selected_plan_id": "unit_plan",
            "candidate_source": "unit",
            "selected_plan": {
                "id": "unit_plan",
                "name": "Unit bounded split",
                "selected_action": {"target": "ride", "action": "reroute", "label": "Bounded reroute"},
                "action_mix": {
                    "guest_reroute": {
                        "expectedTakeRate": 0.44,
                        "target_mix": [
                            {"zoneId": "theaterB", "destination": "Theater B", "share": 0.45},
                            {"zoneId": "foodCourt2", "destination": "Food Court B", "share": 0.25},
                        ],
                    }
                },
            },
        }

    def fake_context(scenario_key, observed_state, observation):
        return {"status": {"mode": "unit_context"}, "digital_twin_benchmark": {"observation_mode": observation["mode"]}}

    result = asyncio.run(
        run_parkpulse_agent_benchmark(
            _state(),
            fake_planner,
            fake_optimizer,
            fake_context,
            scenario_id="sensor_lag_mislead",
            seed="agent-unit",
        )
    )

    assert result["mode"] == "parkpulse_agent_adversarial_benchmark"
    assert result["policy_under_test"] == "ParkPulse planner + optimizer + digital twin policy gate"
    episode = result["episodes"][0]
    assert episode["agent_input"]["mode"] == "noisy_partial_observed_state"
    assert episode["planner"]["runtime"] == "unit_agent"
    assert episode["selected_action"]["id"] == "unit_plan"
    assert "regret_vs_benchmark_selector" in episode["scorecard"]
