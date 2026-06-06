import asyncio
import os

os.environ.setdefault("MONGODB_DISABLE_DRIVER_IMPORT", "1")

import pytest

import park_action_bridge
import park_audit_agent
import park_counterfactual
import digital_twin_calibration
import park_mission_replay
import park_scenario_lab
import park_readiness_brief
import park_learned_agent_maturity
import park_learning_evidence_ledger
import park_eval
import park_gemini_agent
import park_mediator
import park_multi_agent
import park_review
import mongo_memory
import park_scenarios
from park_simulation import ParkSimulation


@pytest.fixture(autouse=True)
def disable_hosted_eval(monkeypatch):
    for name in (
        "ENABLE_VERTEX_GENAI_EVAL",
        "PARKPULSE_ENABLE_HOSTED_EVAL_TRIGGER",
        "ENABLE_VERTEX_CONTINUOUS_EVAL",
        "ENABLE_GCP_CLOUD_TRACE_EXPORT",
        "ENABLE_BIGQUERY_ANALYTICS",
        "PARKPULSE_ENABLE_OTEL_SPANS",
        "PARKPULSE_MONGO_MODEL_EMBEDDINGS",
        "PARKPULSE_COPILOT_SEMANTIC_MEMORY",
    ):
        monkeypatch.setenv(name, "false")
    for name in ("VERTEX_GENAI_EVALUATOR_ID", "ARIZE_HOSTED_EVALUATOR_ID", "VERTEX_EVAL_ACCESS_TOKEN"):
        monkeypatch.delenv(name, raising=False)


def test_park_scenarios_and_eval_default_fallback():
    scenarios = park_scenarios.get_park_scenarios()
    ride_down = park_scenarios.get_park_eval_result("ride_down")
    defaulted = park_scenarios.get_park_eval_result("missing")

    assert scenarios["source"] == "parkpulse_backend"
    assert {item["key"] for item in scenarios["scenarios"]} == {
        "ride_down",
        "staff_shortage",
        "food_spike",
        "storm_response",
    }
    assert ride_down["scenario"]["key"] == "ride_down"
    assert ride_down["arize_trace"]["span"] == "parkpulse.decision_bridge.ride_down"
    assert defaulted["scenario"]["key"] == "ride_down"


def test_day_in_life_operating_clock_changes_park_pressure():
    sim = ParkSimulation()

    sim.hour = 0
    sim.minute = 15
    midnight = asyncio.run(sim.get_state())
    sim.hour = 9
    sim.minute = 30
    morning = asyncio.run(sim.get_state())
    sim.hour = 12
    sim.minute = 30
    lunch = asyncio.run(sim.get_state())
    sim.hour = 20
    sim.minute = 15
    night_show = asyncio.run(sim.get_state())
    sim.hour = 22
    sim.minute = 15
    closing = asyncio.run(sim.get_state())

    assert midnight["operatingClock"]["phase"]["id"] == "overnight_maintenance"
    assert morning["operatingClock"]["phase"]["id"] == "opening"
    assert lunch["operatingClock"]["phase"]["id"] == "lunch_peak"
    assert night_show["operatingClock"]["phase"]["id"] == "night_show"
    assert closing["operatingClock"]["phase"]["id"] == "closing_exit"
    assert midnight["operatingClock"]["heartbeat"]["isOvernight"] is True
    assert sum(zone["currentGuests"] for zone in midnight["guestFlow"]["zones"]) < sum(zone["currentGuests"] for zone in morning["guestFlow"]["zones"])
    assert max(ride["waitMins"] for ride in midnight["guestFlow"]["rides"]) == 0
    midnight_coaster = next(zone for zone in midnight["guestFlow"]["zones"] if zone["id"] == "coasterPlaza")
    midnight_coaster_paths = [
        path for path in midnight["guestFlow"]["paths"]
        if path["from"] == "coasterPlaza" or path["to"] == "coasterPlaza"
    ]
    midnight_dragon_queues = [
        queue for queue in midnight["physicalMap"]["queues"]
        if queue.get("rideId") == "dragonCoaster"
    ]
    assert midnight_coaster["currentGuests"] < 30
    assert midnight_coaster["density"] < 5
    assert max(path["congestionLevel"] for path in midnight_coaster_paths) < 10
    assert all(queue["guests"] == 0 for queue in midnight_dragon_queues)
    assert all("coaster" not in group.get("destination", "").lower() for group in midnight["physicalMap"]["guestGroups"])
    assert lunch["operatingClock"]["foodRetailLifecycle"]["prepPressurePct"] > morning["operatingClock"]["foodRetailLifecycle"]["prepPressurePct"]
    assert closing["operatingClock"]["guestIntent"]["exitSeekingPct"] > lunch["operatingClock"]["guestIntent"]["exitSeekingPct"]
    assert lunch["foodInventory"]["locations"][0]["mobileOrderBacklog"] > morning["foodInventory"]["locations"][0]["mobileOrderBacklog"]
    assert closing["guestFlow"]["zones"][0]["dominantIntent"] == "showtime pressure: exit and arrival pressure"


def test_simulation_step_advances_operating_clock():
    sim = ParkSimulation()
    sim.hour = 11
    sim.minute = 59

    before = asyncio.run(sim.get_state())
    asyncio.run(sim.step())
    after = asyncio.run(sim.get_state())

    assert before["operatingClock"]["phase"]["id"] == "morning_peak"
    assert after["simTime"] == {"hour": 12, "minute": 0, "day": 1, "seasonIndex": 0}
    assert after["operatingClock"]["phase"]["id"] == "lunch_peak"
    assert after["guestFlow"]["activeScenario"]["key"] == sim.scenario_key


def test_dynamic_park_eval_scores_live_state(monkeypatch):
    monkeypatch.setattr(
        park_eval,
        "get_latest_memory_documents",
        lambda collection, limit=5: [
            {
                "_id": "decision_1",
                "stateScenario": {"key": "ride_down"},
                "selectedAction": {"target": "ride", "action": "reroute"},
                "retrievedPlaybooks": ["pb_ride_breakdown"],
                "retrievedIncidents": ["inc_dragon_indoor_overload"],
            }
        ]
        if collection == "agent_decisions"
        else [
            {
                "_id": "eval_1",
                "scores": {"safety": 100, "workerStress": 84},
            }
        ],
    )

    result = park_eval.evaluate_park_decision(
        "ride_down",
        {
            "guestFlow": {
                "activeScenario": {"key": "ride_down"},
                "rides": [{"status": "down", "waitMins": 60}, {"status": "normal", "waitMins": 55}],
            },
            "alerts": [{"title": "Dragon Coaster downtime", "detail": "Pause intake"}],
        },
    )

    assert result["source"] == "parkpulse_gcp_internal_eval_loop"
    assert result["scorecard"]["decision_id"] == "decision_1"
    assert result["scorecard"]["policy_violation"] is False
    assert {item["label"] for item in result["evals"]} >= {
        "Groundedness",
        "Playbook retrieval",
        "Capacity awareness",
        "Staff stress",
        "Safety",
        "Actionability",
        "Policy guidance compliance",
        "Take rate",
        "Positive response",
        "Reactive follow-through",
    }


def test_park_eval_grades_policy_guidance():
    result = park_eval.evaluate_park_decision(
        "ride_down",
        {
            "guestFlow": {
                "activeScenario": {"key": "ride_down"},
                "rides": [{"status": "down", "waitMins": 60}],
            },
            "alerts": [{"title": "Ride down"}],
        },
        governance={"allowed": False, "gate_status": "blocked", "findings": ["Ride action requires clearance."]},
    )

    policy_eval = next(item for item in result["evals"] if item["label"] == "Policy guidance compliance")

    assert policy_eval["score"] < 75
    assert result["scorecard"]["policy_violation"] is True
    assert result["scorecard"]["policy_gate_status"] == "blocked"


def test_park_action_bridge_translates_plan_and_alias(monkeypatch):
    state = {
        "guestFlow": {
            "activeScenario": {"key": "ride_down", "name": "Ride Down"},
            "rides": [{"status": "down", "waitMins": 60}, {"status": "constrained", "waitMins": 55}],
            "zones": [{"density": 89}],
        }
    }

    plan = park_action_bridge.build_park_action_plan(state)
    alias_plan = park_action_bridge.build_delay_action_plan(state)

    assert plan["scope"] == "parkpulse_operations_only"
    assert plan["domain"] == "amusement_park_operations"
    assert plan["arize_trace"]["span"] == "park_action_bridge.plan"
    assert plan["arize_trace"]["eval_subject"] == "park_operations_action_plan"
    assert plan["recommended_actions"][0]["title"] == "Pause new queue intake at Dragon Coaster"
    assert plan["selected_action"]["park_action"] == {"target": "ride", "action": "reroute"}
    assert alias_plan["scope"] == "parkpulse_operations_only"


def test_department_negotiation_demo_rejects_unsafe_marketing_offer():
    state = {
        "guestFlow": {
            "activeScenario": {"key": "marketing_promo_conflict", "name": "Marketing Promo Conflict"},
            "rides": [{"name": "Dragon Coaster", "status": "down", "waitMins": 55, "queueGuests": 650}],
            "zones": [
                {"id": "zone_b", "name": "Zone B Indoor Food Court", "processType": "food", "density": 91, "waitMins": 34},
                {"id": "zone_c", "name": "Zone C Garden Market", "processType": "food", "density": 42, "waitMins": 9},
            ],
            "paths": [{"fromName": "Coaster Plaza", "toName": "Zone B Indoor Food Court", "congestionLevel": 88}],
        },
        "weather": {"condition": "rain", "stormRisk": 68},
        "staffing": {"scheduled": 210, "checkedIn": 201, "openCallouts": 7},
    }

    artifact = park_multi_agent.build_role_agent_proposals(state, {"scenario_key": "marketing_promo_conflict"})
    by_agent = {proposal["agent_id"]: proposal for proposal in artifact["proposals"]}

    assert {"event_creative_agent", "ride_ops_agent", "safety_policy_agent", "finance_agent", "decision_bridge_agent"} <= set(by_agent)
    assert {"marketing", "operations", "safety", "finance", "executive"} <= set(artifact["active_departments"])
    assert artifact["active_department_count"] == len(artifact["active_departments"])
    assert by_agent["event_creative_agent"]["requested_tool"] == "redirect_offer"
    assert by_agent["ride_ops_agent"]["requested_tool"] == "recommend_route_change"
    assert by_agent["safety_policy_agent"]["requires_compliance"] is True
    assert by_agent["finance_agent"]["requested_tool"] == "revenue_impact_report"
    redirect = next(proposal for proposal in artifact["proposals"] if proposal["proposed_action"].get("decision") == "reject_zone_b_redirect_to_zone_c")
    assert redirect["agent_id"] == "decision_bridge_agent"
    assert redirect["proposal_envelope"]["executor_agent"] == "tool_executor_agent"
    assert artifact["proposal_envelope_summary"]["requires_executive"] >= 1
    assert any("Zone B" in conflict["conflict"] and conflict["status"] == "resolved" for conflict in artifact["conflicts"])


def test_multi_agent_registry_and_runtime_findings_are_park_native():
    registry = park_multi_agent.get_agent_registry()
    topology = park_multi_agent.get_agent_topology()
    report = park_multi_agent.role_alignment_report()
    state = {
        "guestFlow": {
            "activeScenario": {"key": "ride_down", "name": "Ride Down"},
            "rides": [{"name": "Dragon Coaster", "status": "down", "waitMins": 60, "queueGuests": 700}],
            "zones": [{"name": "Coaster Plaza", "density": 89}, {"name": "Food Court 1", "processType": "food", "density": 74, "waitMins": 28}],
            "paths": [{"fromName": "Coaster Plaza", "toName": "Covered Plaza", "congestionLevel": 91}],
        },
        "weather": {"stormRisk": 72, "heatIndexF": 99},
        "energy": {"gridLoadPercent": 93},
        "staffing": {"scheduled": 214, "checkedIn": 196, "openCallouts": 18},
    }
    findings = park_multi_agent.build_reactive_agent_findings(
        state,
        "ride_down",
        {"retrieved": {"playbooks": [{"_id": "pb"}], "incidents": [], "learnings": []}},
        {"selected_action": {"target": "ride", "action": "reroute", "label": "Reroute guests"}, "confidence_score": 82},
        {"mode": "custom_mix_tournament", "selected_plan": {"selected_action": {"target": "ride", "action": "reroute", "label": "Reroute guests"}}},
        {"evals": [{"label": "Safety", "score": 96}], "scorecard": {"overall": 84, "needs_human_approval": True}},
        {"response": {"takeRate": 0.34, "reactiveFollowThroughRate": 0.29}},
    )
    proposals = park_multi_agent.build_role_agent_proposals(state, {"scenario_key": "ride_down"}, retrieved_context={"retrieved": {"playbooks": [{"_id": "pb"}]}})

    assert report["status"] == "aligned"
    assert report["department_count"] == 12
    assert report["agent_group_count"] == 3
    assert report["phase_count"] == 7
    assert report["handoff_count"] >= 12
    assert topology["pattern"] == "department_systematic_enterprise_nervous_system"
    assert topology["lifecycle_pattern"] == "pre_event_during_event_post_event_agent_groups"
    assert [group["id"] for group in topology["agent_groups"]] == ["pre_event", "during_event", "post_event"]
    assert [row["group_id"] for row in topology["lifecycle_artifact"]] == ["pre_event", "during_event", "post_event"]
    assert [step.lower() for step in topology["department_system"]["loop"]] == ["observe", "interpret", "predict", "recommend", "justify", "trace"]
    assert {department["department"] for department in topology["department_system"]["departments"]} >= {"operations", "safety", "food_retail", "executive", "qa_judge"}
    assert len(topology["phases"]) == 7
    assert topology["logic_graph"]["audit_agent"]["agent_id"] == "logic_audit_agent"
    assert topology["logic_graph"]["decision_layers"][-1]["id"] == "post_decision_result"
    assert {agent["agent_id"] for agent in registry} >= {"ride_ops_agent", "guest_flow_agent", "traffic_flow_agent", "finance_agent", "decision_bridge_agent", "logic_audit_agent", "gcp_eval_judge_agent", "tool_executor_agent"}
    assert {agent["department"] for agent in registry} >= {"operations", "guest_experience", "finance", "executive", "compliance", "qa_judge", "tool_executor"}
    assert {finding["agent_id"] for finding in findings} >= {"ride_ops_agent", "guest_flow_agent", "staffing_agent", "decision_bridge_agent", "logic_audit_agent", "gcp_eval_judge_agent"}
    assert {finding["department"] for finding in findings} >= {"operations", "guest_experience", "hr_labor", "executive", "compliance", "qa_judge"}
    assert all(finding["trace_span"].startswith("parkpulse.agent.") for finding in findings)
    assert proposals["proposal_envelope_summary"]["total"] == proposals["proposal_count"]
    assert proposals["proposal_envelope_summary"]["proposed"] >= 1
    assert all("proposal_envelope" in proposal for proposal in proposals["proposals"])
    assert {proposal["proposal_envelope"]["executor_agent"] for proposal in proposals["proposals"]} == {"tool_executor_agent"}
    orchestration = park_multi_agent.build_orchestration_run(findings, "reactive", {"takeRate": 0.34, "score": 52}, {"event_plan_id": "v2"})
    assert orchestration["pattern"] == "department_systematic_enterprise_nervous_system"
    assert orchestration["lifecycle_pattern"] == "pre_event_during_event_post_event_agent_groups"
    assert orchestration["department_system"]["active_department_count"] >= 5
    assert {group["id"] for group in orchestration["agent_groups"] if group["status"] == "active"} >= {"during_event", "post_event"}
    assert orchestration["lifecycle_artifact"][1]["status"] == "complete"
    assert orchestration["lifecycle_artifact"][2]["status"] == "revise"
    assert "Take rate 34%" in orchestration["lifecycle_artifact"][1]["measured_result"]
    assert orchestration["conflicts"]
    assert orchestration["gates"][1]["status"] == "revise"
    assert orchestration["logic_graph"]["audit_agent"]["status"] == "updating"
    assert orchestration["logic_graph"]["decision_layers"][-1]["status"] == "revise"


def test_park_gemini_agent_falls_back_when_not_ready(monkeypatch):
    class NotReadyGemini:
        platform = "gemini_api"
        model = "gemini-test"
        ready = False
        readiness_issues = ["missing key"]
        use_gemini_enterprise = False

    monkeypatch.setattr(park_gemini_agent, "get_gemini_agent_properties", lambda: NotReadyGemini())

    plan = asyncio.run(
        park_gemini_agent.build_park_gemini_plan(
            {
                "guestFlow": {
                    "activeScenario": {"key": "ride_down", "name": "Ride Down"},
                    "rides": [{"status": "down", "waitMins": 60}],
                }
            },
            "ride_down",
            {"retrieved": {"playbooks": [{"_id": "pb_ride_breakdown"}], "incidents": []}},
        )
    )

    assert plan["runtime"] == "deterministic_fallback"
    assert plan["selected_action"]["target"] == "ride"
    assert plan["selected_action"]["action"] == "reroute"
    assert "missing key" in plan["errors"]


def test_park_mediator_is_native_park_signal_bus():
    park_mediator._park_signals.clear()
    state = {
        "guestFlow": {
            "activeScenario": {"key": "ride_down"},
            "rides": [{"status": "down", "waitMins": 60}, {"status": "constrained", "waitMins": 55}],
            "zones": [{"density": 89}],
        },
        "staffing": {"openCallouts": 18},
        "energy": {"demandChargeRisk": "critical"},
    }

    created = asyncio.run(park_mediator.react_to_park_state(state, fast_eval=True))
    signals = asyncio.run(park_mediator.get_park_signals())
    findings = asyncio.run(park_mediator.get_park_agent_findings(state))
    ack = asyncio.run(park_mediator.acknowledge_park_signal(created[0]["id"], "Ride Ops", "acknowledged", {"ride": "Dragon Coaster"}))

    assert created[0]["domain"] == "amusement_park_operations"
    assert created[0]["recipient"] == "Ride Ops"
    assert signals["domain"] == "amusement_park_operations"
    assert signals["signal_bus"] == "park_operations_signals"
    assert signals["signals"][0]["subject"].startswith("Pause Dragon Coaster")
    assert findings["domain"] == "amusement_park_operations"
    assert findings["summary"]["down_rides"] == 1
    assert ack["partner"] == "Ride Ops"
    assert ack["response"]["ride"] == "Dragon Coaster"

    assert asyncio.run(park_mediator.react_to_park_state(state)) == []
    assert asyncio.run(park_mediator.get_park_signals())["signal_bus"] == "park_operations_signals"


def test_park_simulation_is_native_and_actionable():
    sim = ParkSimulation()

    state = asyncio.run(sim.get_state())
    operation_event = asyncio.run(sim.inject_random_unexpected_event())
    after_event = asyncio.run(sim.get_state())
    action_result = asyncio.run(sim.execute_action("ride", "reroute"))
    updated = asyncio.run(sim.get_state())
    replay = asyncio.run(sim.get_replay())
    seeded = asyncio.run(sim.start_replay_run("dragon-rain-001", "storm_response"))
    seeded_replay = asyncio.run(sim.get_replay())

    assert state["product"]["name"] == "ParkPulse AI"
    assert state["guestFlow"]["activeScenario"]["key"] == "ride_down"
    assert operation_event["event"]["unexpected"] is True
    assert after_event["guestFlow"]["interventions"][0]["unexpected"] is True
    assert action_result["status"] == "success"
    assert updated["guestFlow"]["activePolicy"] == "reroute"
    assert updated["lastActions"][0]["target"] == "ride"
    assert replay["event_count"] >= 2
    assert replay["events"][0]["kind"] == "operator_action"
    assert replay["events"][0]["delta"]["policyChanged"] is True
    assert seeded["run"]["seed"] == "dragon-rain-001"
    assert seeded_replay["run_id"] == seeded["run"]["run_id"]
    assert seeded_replay["events"][0]["kind"] == "run_started"


def test_park_simulation_stateful_twin_stresses_and_scores_actions():
    sim = ParkSimulation()

    before = asyncio.run(sim.get_state())
    projection = asyncio.run(sim.simulate_action({"target": "ride", "action": "reroute"}, 30))
    action_result = asyncio.run(sim.execute_action("ride", "reroute"))
    after = asyncio.run(sim.get_state())
    noisy = asyncio.run(sim.get_noisy_observation())
    ground_truth = asyncio.run(sim.get_ground_truth_state())

    assert projection["source"] == "stateful_stress_transition_model"
    assert projection["projected_impact"]["movedGuests"] > 0
    assert projection["secondary_risks"]
    assert action_result["status"] == "success"
    assert after["digitalTwin"]["stressHarness"]["stateful"] is True
    assert after["guestFlow"]["zones"][1]["density"] <= before["guestFlow"]["zones"][1]["density"]
    assert after["digitalTwin"]["lastAppliedAction"]["outcomeScore"] >= 0
    assert noisy["mode"] == "noisy_partial_observation"
    assert ground_truth["mode"] == "evaluator_ground_truth"


def test_park_audit_agent_persists_events_and_builds_action_candidate(monkeypatch, tmp_path):
    monkeypatch.setenv("PARKPULSE_AUDIT_DB", str(tmp_path / "audit.db"))
    sim = ParkSimulation()
    state = asyncio.run(sim.get_state())
    recorded = park_audit_agent.record_audit_event(
        {
            "source": "shift_roster",
            "signal": "schedule_collision",
            "zoneId": "coasterPlaza",
            "assetId": "break_block:C",
            "message": "Two ride operators are scheduled for break while queue split is still active.",
            "abnormalityScore": 100,
            "correlatedBy": ["staff_badge_checkin", "ride_minimum_staffing"],
        }
    )
    audit = park_audit_agent.build_audit_snapshot(state)
    candidate = park_audit_agent.build_audit_action_candidate(audit, state)

    assert recorded["id"].startswith("AUD-EVT-")
    assert audit["store"]["ready"] is True
    assert audit["summary"]["ingestedEvents"] == 1
    assert audit["workLogs"][0]["source"] == "shift_roster"
    assert any(item["id"] == f"ANOM-EVENT-{recorded['id']}" for item in audit["anomalies"])
    assert candidate["status"] == "ready"
    assert candidate["selected_action"]["park_action"] == {"target": "staff", "action": "redeploy"}

    park_audit_agent.record_audit_response(
        candidate["finding"]["id"],
        {"status": "success", "selected_action": candidate["selected_action"], "executed": True},
    )
    findings = park_audit_agent.list_audit_findings(5)
    responded = next(item for item in findings if item["id"] == candidate["finding"]["id"])
    assert responded["latestResponse"]["executed"] is True


def test_counterfactual_forecast_quantifies_audit_impact(monkeypatch, tmp_path):
    monkeypatch.setenv("PARKPULSE_AUDIT_DB", str(tmp_path / "audit.db"))
    sim = ParkSimulation()
    state = asyncio.run(sim.get_state())
    state["operationsAudit"] = park_audit_agent.build_audit_snapshot(state)
    forecast = park_counterfactual.build_counterfactual_forecast(state)
    fifteen = next(item for item in forecast["horizons"] if item["minutes"] == 15)

    assert forecast["mode"] == "counterfactual_audit_intervention"
    assert forecast["leadTimeMinutes"] >= 1
    assert forecast["impact"]["guestMinutesSaved"] > 0
    assert fifteen["withoutAudit"]["densityPct"] > fifteen["withAudit"]["densityPct"]
    assert fifteen["withoutAudit"]["guestComplaintCases"] > fifteen["withAudit"]["guestComplaintCases"]
    assert forecast["spillback"]["queueName"]
    assert forecast["spillback"]["thresholds"]["withoutAuditWalkwayBlockedInMinutes"] is not None
    assert forecast["spillback"]["horizons"][2]["delta"]["overflowMetersAvoided"] >= 0
    assert forecast["actionExecution"]["mode"] == "delayed_action_guest_response_model"
    assert forecast["actionExecution"]["timeline"][0]["minute"] == 0
    assert forecast["actionExecution"]["timeline"][-1]["movedGuests"] > 0
    assert fifteen["withAudit"]["actionEffectivenessPct"] >= 50
    assert {item["id"] for item in forecast["metrics"]} >= {"density", "service_lane", "staff_conflict", "guest_minutes"}
    assert [item["id"] for item in forecast["causalChain"]] == ["signal", "propagation", "operational_effect"]


def test_digital_twin_calibration_ledger_resolves_compact_rows(monkeypatch, tmp_path):
    monkeypatch.setenv("PARKPULSE_AUDIT_DB", str(tmp_path / "audit.db"))
    digital_twin_calibration.reset_calibration_ledger()
    sim = ParkSimulation()
    state = asyncio.run(sim.get_state())
    state["operationsAudit"] = park_audit_agent.build_audit_snapshot(state)
    forecast = park_counterfactual.build_counterfactual_forecast(state)

    warming = digital_twin_calibration.build_calibration_ledger(state, forecast)
    assert warming["mode"] == "compact_digital_twin_calibration_ledger"
    assert warming["storagePolicy"]["fullStateSnapshots"] is False
    assert warming["pendingCount"] >= 3
    assert warming["summary"]["confidence"] == "warming_up"

    later = asyncio.run(sim.get_state())
    later["simTime"] = {**later["simTime"], "minute": later["simTime"]["minute"] + 15}
    later["operationsAudit"] = park_audit_agent.build_audit_snapshot(later)
    resolved = digital_twin_calibration.build_calibration_ledger(later)

    assert resolved["summary"]["resolvedRows"] >= 2
    assert resolved["latestResolved"][0]["accuracyScore"] >= 0
    assert resolved["latestResolved"][0]["closestBranch"] in {"withoutAudit", "withAudit"}
    assert "overflowMeters" in resolved["latestResolved"][0]["error"]


def test_mission_replay_connects_signal_forecast_execution_and_learning(monkeypatch, tmp_path):
    monkeypatch.setenv("PARKPULSE_AUDIT_DB", str(tmp_path / "audit.db"))
    digital_twin_calibration.reset_calibration_ledger()
    sim = ParkSimulation()
    state = asyncio.run(sim.get_state())
    state["operationsAudit"] = park_audit_agent.build_audit_snapshot(state)
    state["counterfactualForecast"] = park_counterfactual.build_counterfactual_forecast(state)
    state["digitalTwinCalibration"] = digital_twin_calibration.build_calibration_ledger(
        state,
        state["counterfactualForecast"],
    )

    replay = park_mission_replay.build_mission_replay(state)

    assert replay["mode"] == "mission_replay"
    assert [step["id"] for step in replay["steps"]] == ["signal", "forecast", "decision", "governance", "execution", "outcome", "learning"]
    assert replay["summary"]["guestMinutesSaved"] == state["counterfactualForecast"]["impact"]["guestMinutesSaved"]
    assert replay["summary"]["finalTakeRatePct"] == state["counterfactualForecast"]["actionExecution"]["finalTakeRatePct"]
    assert replay["steps"][3]["tone"] == "watch"
    assert replay["steps"][-1]["proof"][0] == "digitalTwinCalibration"


def test_scenario_lab_scores_generalization_without_full_snapshots(monkeypatch, tmp_path):
    monkeypatch.setenv("PARKPULSE_AUDIT_DB", str(tmp_path / "audit.db"))
    digital_twin_calibration.reset_calibration_ledger()
    sim = ParkSimulation()
    state = asyncio.run(sim.get_state())
    state["operationsAudit"] = park_audit_agent.build_audit_snapshot(state)
    state["counterfactualForecast"] = park_counterfactual.build_counterfactual_forecast(state)
    state["digitalTwinCalibration"] = digital_twin_calibration.build_calibration_ledger(
        state,
        state["counterfactualForecast"],
    )

    lab = park_scenario_lab.build_scenario_lab(state)

    assert lab["mode"] == "scenario_lab"
    assert lab["summary"]["scenarioCount"] == 5
    assert {row["id"] for row in lab["scoreboard"]} == {
        "normal_busy_day",
        "ride_cascade_day",
        "weather_shock_day",
        "low_staff_day",
        "high_anomaly_day",
    }
    assert lab["summary"]["totalGuestMinutesSaved"] == sum(row["parkpulse"]["guestMinutesSaved"] for row in lab["scoreboard"])
    assert all(row["baseline"]["guestMinutesAtRisk"] > row["parkpulse"]["guestMinutesAtRisk"] for row in lab["scoreboard"])
    assert lab["scoreboard"][-1]["parkpulse"]["policyBlocks"] >= lab["scoreboard"][0]["parkpulse"]["policyBlocks"]
    assert "Stores no full alternate worlds" in lab["method"][1]


def test_readiness_brief_packages_operator_value_trust_and_conditions(monkeypatch, tmp_path):
    monkeypatch.setenv("PARKPULSE_AUDIT_DB", str(tmp_path / "audit.db"))
    digital_twin_calibration.reset_calibration_ledger()
    sim = ParkSimulation()
    state = asyncio.run(sim.get_state())
    state["operationsAudit"] = park_audit_agent.build_audit_snapshot(state)
    state["counterfactualForecast"] = park_counterfactual.build_counterfactual_forecast(state)
    state["digitalTwinCalibration"] = digital_twin_calibration.build_calibration_ledger(
        state,
        state["counterfactualForecast"],
    )
    state["missionReplay"] = park_mission_replay.build_mission_replay(state)
    state["scenarioLab"] = park_scenario_lab.build_scenario_lab(state)

    brief = park_readiness_brief.build_readiness_brief(state)

    assert brief["mode"] == "parkpulse_readiness_brief"
    assert brief["decision"]["label"] in {"Deploy as pilot", "Needs more telemetry", "Not ready for autonomous action"}
    assert brief["decision"]["goNoGo"] in {"GO WITH CONDITIONS", "CONDITIONAL", "NO-GO"}
    assert len(brief["decision"]["conditions"]) == 3
    assert {item["id"] for item in brief["operationalValue"]} == {
        "guest_minutes",
        "spillback",
        "staff_overload",
        "guest_care",
    }
    assert {item["id"] for item in brief["trust"]} == {
        "prediction_accuracy",
        "calibration_drift",
        "policy_blocks",
        "weakest_scenario",
    }
    assert brief["storageCost"]["fullStateSnapshots"] is False
    assert "missionReplay" in brief["evidence"]
    assert "scenarioLab" in brief["evidence"]


def test_learned_agent_maturity_shows_training_depth_and_boundaries(monkeypatch, tmp_path):
    monkeypatch.setenv("PARKPULSE_AUDIT_DB", str(tmp_path / "audit.db"))
    digital_twin_calibration.reset_calibration_ledger()
    sim = ParkSimulation()
    state = asyncio.run(sim.get_state())
    state["operationsAudit"] = park_audit_agent.build_audit_snapshot(state)
    state["counterfactualForecast"] = park_counterfactual.build_counterfactual_forecast(state)
    state["digitalTwinCalibration"] = digital_twin_calibration.build_calibration_ledger(
        state,
        state["counterfactualForecast"],
    )
    state["missionReplay"] = park_mission_replay.build_mission_replay(state)
    state["scenarioLab"] = park_scenario_lab.build_scenario_lab(state)
    state["readinessBrief"] = park_readiness_brief.build_readiness_brief(state)

    maturity = park_learned_agent_maturity.build_learned_agent_maturity(state)

    assert maturity["mode"] == "learned_agent_maturity"
    assert maturity["memoryDepth"]["policyBlockHistory"] == sum(
        row["parkpulse"]["policyBlocks"] for row in state["scenarioLab"]["scoreboard"]
    )
    assert maturity["beforeAfter"]["learnedAgent"]["expectedTakeRatePct"] >= maturity["beforeAfter"]["oldAgent"]["expectedTakeRatePct"]
    assert {item["id"] for item in maturity["scenarioCoverage"]} >= {
        "ride_cascade",
        "weather_shock",
        "food_spike",
        "staff_shortage",
        "high_anomaly",
        "event_night",
    }
    assert any(item["tone"] == "weak" for item in maturity["domainConfidence"])
    assert "cannot self-authorize" in maturity["fixedBoundaries"][0]


def test_learning_evidence_ledger_links_lessons_to_today_behavior(monkeypatch, tmp_path):
    monkeypatch.setenv("PARKPULSE_AUDIT_DB", str(tmp_path / "audit.db"))
    digital_twin_calibration.reset_calibration_ledger()
    sim = ParkSimulation()
    state = asyncio.run(sim.get_state())
    state["operationsAudit"] = park_audit_agent.build_audit_snapshot(state)
    state["counterfactualForecast"] = park_counterfactual.build_counterfactual_forecast(state)
    state["digitalTwinCalibration"] = digital_twin_calibration.build_calibration_ledger(
        state,
        state["counterfactualForecast"],
    )
    state["missionReplay"] = park_mission_replay.build_mission_replay(state)
    state["scenarioLab"] = park_scenario_lab.build_scenario_lab(state)
    state["readinessBrief"] = park_readiness_brief.build_readiness_brief(state)
    state["learnedAgentMaturity"] = park_learned_agent_maturity.build_learned_agent_maturity(state)

    ledger = park_learning_evidence_ledger.build_learning_evidence_ledger(state)

    assert ledger["mode"] == "learning_evidence_ledger"
    assert ledger["summary"]["ledgerEntries"] == 4
    assert ledger["summary"]["appliedToday"] == 3
    assert {entry["id"] for entry in ledger["entries"]} >= {
        "learn-ride-cascade-capacity",
        "learn-staff-break-protection",
        "learn-food-redirect-suppression",
        "learn-noisy-signal-restraint",
    }
    assert all(entry["pastIncident"]["id"].startswith("INC-") for entry in ledger["entries"])
    assert all(entry["lesson"]["rule"] for entry in ledger["entries"])
    assert all(entry["appliedToday"]["newAction"] for entry in ledger["entries"])
    assert all(entry["proof"]["incidentId"] == entry["pastIncident"]["id"] for entry in ledger["entries"])
    assert ledger["entries"][-1]["status"] == "watch_only"
    assert "observed take rate" in ledger["method"][0]


def test_park_review_snapshot_packages_realism_artifact():
    sim = ParkSimulation()

    asyncio.run(sim.inject_event("ride_failure", "dragonCoaster", 85))
    asyncio.run(sim.execute_action("ride", "reroute"))
    state = asyncio.run(sim.get_state())
    snapshot = park_review.build_review_snapshot(
        state,
        runtime_governance={"decision_ledger": [{"id": "gate-1", "title": "Policy check", "policyFindings": ["maintenance hold protected"]}]},
        dispatches=[{"channel": "guest_app", "payload": {"message": "Dragon Coaster is down; use nearby alternatives."}}],
        signals={"signals": [{"subject": "Queue pressure", "body": "Coaster Plaza congestion rising."}]},
        replay=asyncio.run(sim.get_replay()),
    )

    assert snapshot["domain"] == "amusement_park_operations"
    assert snapshot["scenario"]["key"] == "ride_down"
    assert snapshot["overall_score"] >= 65
    assert {item["key"] for item in snapshot["scorecard"]} >= {"physical_grounding", "guest_movement", "codex_reviewability"}
    assert snapshot["state_digest"]["counts"]["guest_groups"] >= 5
    assert snapshot["state_digest"]["counts"]["replay_events"] >= 2
    assert snapshot["replay"]["event_count"] >= 2
    assert snapshot["timeline"]
    assert "Review this ParkPulse simulation snapshot" in snapshot["codex_review_prompt"]
    assert "snapshot_state" in snapshot


def test_operational_memory_dedupes_useful_append_documents(monkeypatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    memory = mongo_memory.OperationalMemory()
    memory.initialize()
    draft = {
        "recommended_action": "Split crowd across indoor rides",
        "selected_action": {"target": "ride", "action": "reroute", "label": "Reroute guests"},
        "candidate_actions": [{"target": "ride", "action": "reroute"}],
        "confidence_score": 91,
        "root_cause_classification": "ride_down",
    }
    evaluation = {"energy_score": 84, "comfort_score": 88, "worker_stress_score": 82, "safety_score": 100}
    state = {"guestFlow": {"activeScenario": {"key": "ride_down", "name": "Ride down"}}}
    context = {"retrieved": {"playbooks": [{"_id": "pb_ride_breakdown"}], "incidents": []}}

    first_id = memory.record_agent_decision(draft, evaluation, state, context)
    second_id = memory.record_agent_decision(draft, evaluation, state, context)

    assert first_id == second_id
    assert len(memory.latest_documents("agent_decisions", 10)) == 1
    assert len(memory.latest_documents("eval_results", 10)) == 1
    assert len(memory.latest_documents("guest_messages", 10)) == 1
    stored = memory.latest_documents("agent_decisions", 1)[0]
    assert "retrieval_grounded" in stored["pipelinePolicy"]["storedBecause"]


def test_operational_memory_skips_low_signal_append_documents(monkeypatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    memory = mongo_memory.OperationalMemory()
    memory.initialize()

    decision_id = memory.record_agent_decision({}, {"energy_score": 0, "comfort_score": 0, "worker_stress_score": 0, "safety_score": 100})

    assert decision_id.startswith("skipped_decision_")
    assert memory.latest_documents("agent_decisions", 10) == []
    assert "Decision memory skipped: missing_recommendation" in memory.status()["errors"]
