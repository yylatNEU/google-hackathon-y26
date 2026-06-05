import asyncio
import copy
import json
import os
from types import SimpleNamespace

os.environ.setdefault("MONGODB_DISABLE_DRIVER_IMPORT", "1")

import pytest

import parkpulse_api
from park_simulation import ParkSimulation

pytestmark = pytest.mark.integration


def run(coro):
    return asyncio.run(coro)


def sample_state():
    return run(ParkSimulation().get_state())


def test_find_industrial_dossier_accepts_live_conflict_alias():
    payload = {
        "dossiers": [
            {
                "id": "industrial_premium_recovery_vs_standby_fairness",
                "sourceConflictId": "premium_recovery_vs_standby_fairness",
                "title": "Premium recovery conflicts with standby fairness",
            }
        ]
    }

    assert parkpulse_api.find_industrial_dossier(payload, "industrial_premium_recovery_vs_standby_fairness")["sourceConflictId"] == "premium_recovery_vs_standby_fairness"
    assert parkpulse_api.find_industrial_dossier(payload, "premium_recovery_vs_standby_fairness")["sourceConflictId"] == "premium_recovery_vs_standby_fairness"
    assert parkpulse_api.find_industrial_dossier(payload, "live_conflict_premium_recovery_vs_standby_fairness")["sourceConflictId"] == "premium_recovery_vs_standby_fairness"


def test_parkpulse_api_health_sync_cache_and_context_helpers(monkeypatch):
    state = sample_state()

    assert run(parkpulse_api.root_health())["service"] == "parkpulse-api"
    assert run(parkpulse_api.healthz())["status"] == "ok"
    assert run(parkpulse_api.readyz())["startup"] is parkpulse_api._startup_status

    monkeypatch.setattr(parkpulse_api, "replay_store_status", lambda: {"ready": False})
    monkeypatch.setattr(parkpulse_api, "delivery_outbox_status", lambda: {"ready": True})
    monkeypatch.setattr(parkpulse_api, "gcp_operations_status", lambda: {"pubsub": {"ready": False}})
    monkeypatch.setattr(parkpulse_api, "audit_store_status", lambda: {"ready": True})
    monkeypatch.setattr(parkpulse_api, "reliability_status", lambda: {"enabled": True})
    assert run(parkpulse_api.readyz_deep())["status"] == "degraded"

    monkeypatch.setattr(parkpulse_api, "_last_memory_sync_at", 0)
    monkeypatch.setattr(parkpulse_api, "_memory_sync_min_interval_seconds", 0)
    monkeypatch.setattr(parkpulse_api, "sync_park_state", lambda current_state: {"status": "stored"})
    assert run(parkpulse_api.sync_park_state_safe(state, force=True))["status"] == "stored"
    monkeypatch.setattr(parkpulse_api, "sync_park_state", lambda current_state: (_ for _ in ()).throw(RuntimeError("mongo down")))
    assert run(parkpulse_api.sync_park_state_safe(state, force=True))["status"] == "skipped"

    rows = {"agent_action_outcomes": [{"id": 1}, {"id": 2}, {"id": 3}]}
    monkeypatch.delenv("PARKPULSE_LIVE_BIGQUERY", raising=False)
    monkeypatch.delenv("PARKPULSE_COLLABORATION_LIVE_BIGQUERY", raising=False)
    monkeypatch.setattr(parkpulse_api, "bigquery_status", lambda: {"mode": "fallback"})
    assert parkpulse_api._export_agent_analytics(rows)["preview"]["agent_action_outcomes"] == [{"id": 1}, {"id": 2}]
    monkeypatch.setenv("PARKPULSE_COLLABORATION_LIVE_BIGQUERY", "on")
    monkeypatch.setattr(parkpulse_api, "export_analytics_rows", lambda payload: {"status": "exported", "tables": sorted(payload)})
    assert parkpulse_api._export_agent_analytics(rows)["status"] == "exported"

    calls = []

    def fake_priors(scenario_key, dashboard, allow_live_query=None):
        calls.append(allow_live_query)
        if allow_live_query is not None:
            raise TypeError("allow_live_query is not accepted")
        return {"scenario": scenario_key, "fallback_signature": True}

    monkeypatch.setattr(parkpulse_api, "build_bigquery_agent_priors", fake_priors)
    assert parkpulse_api._build_agent_bigquery_priors("ride_down", {})["fallback_signature"] is True
    assert calls == [True, None]

    monkeypatch.setattr(parkpulse_api, "get_operational_memory_dashboard", lambda query: {"dashboard": query})
    monkeypatch.setattr(parkpulse_api, "_build_agent_bigquery_priors", lambda scenario, dashboard: {"scenario": scenario})
    monkeypatch.setattr(parkpulse_api, "replay_collaboration_context", lambda limit: {"limit": limit})
    enriched = parkpulse_api._collaboration_context({"status": "ok"}, "food_spike")
    assert enriched["bigquery_priors"]["scenario"] == "food_spike"
    assert enriched["relational_context"]["limit"] == 8

    parkpulse_api.clear_hot_endpoint_cache()
    assert run(parkpulse_api.cached_hot_endpoint("zero", 0, lambda: asyncio.sleep(0, result={"fresh": True})))["fresh"] is True
    loop_value = {"old": True}

    async def never_called():
        return {"new": True}

    async def exercise_stale_cache():
        loop = asyncio.get_running_loop()
        parkpulse_api._hot_endpoint_cache["stale"] = (loop.time() - 1, loop_value)
        created = []

        def fake_create_task(coro):
            created.append(coro)
            coro.close()
            return SimpleNamespace(done=lambda: True)

        monkeypatch.setattr(parkpulse_api.asyncio, "create_task", fake_create_task)
        result = await parkpulse_api.cached_hot_endpoint("stale", 5, never_called)
        return result, created

    cached, created = run(exercise_stale_cache())
    assert cached is loop_value
    assert created

    async def broken_builder():
        raise RuntimeError("refresh failed")

    run(parkpulse_api.refresh_hot_endpoint("broken", 1, broken_builder))


def test_parkpulse_api_route_inference_edge_cases():
    explicit = parkpulse_api._infer_operator_command_route("anything", "signal_triage")
    assert explicit["route"] == "signal_triage"
    event = parkpulse_api._infer_operator_command_route("Plan event parade with haunted overlay", "auto")
    assert event["route"] == "event_plan"
    staff = parkpulse_api._infer_operator_command_route("Protect staff breaks and avoid overload", "auto")
    assert staff["scenario_key"] in {"ride_down", "staff_shortage"}
    critical = parkpulse_api._infer_operator_command_route("Guest fainted near coaster, medical support needed", "auto")
    assert critical["urgency"] == "critical"
    assert critical["requires_human_review"] is True


def test_operator_constraints_customize_plan_from_free_text():
    state = sample_state()
    message = (
        "Dragon Coaster is down. Keep families happy, avoid Food Court A, "
        "send people to arcade and theater, dispatch medical near Indoor Launch, adjust HVAC comfort."
    )
    constraints = parkpulse_api.extract_operator_constraints(
        message,
        state,
        {"scenario_key": "ride_down", "requires_human_review": True},
    )
    assert any(item["id"] == "foodCourt1" for item in constraints["avoid_zones"])
    assert any(item["id"] in {"arcade", "arcadeZone"} for item in constraints["preferred_destinations"])
    assert any(item["role"] == "medical" and item["to"] == "Indoor Launch" for item in constraints["required_staff_moves"])
    assert constraints["equipment_controls"][0]["equipmentType"] == "hvac"

    base_optimization = parkpulse_api.optimize_park_response(state, "ride_down", {}, {})
    patched = parkpulse_api.apply_operator_constraints_to_optimization(base_optimization, constraints, state, "ride_down")
    action_mix = patched["selected_plan"]["action_mix"]
    target_ids = {
        str(item.get("destinationId") or item.get("zoneId"))
        for item in action_mix["guest_reroute"]["target_mix"]
    }
    assert "foodCourt1" not in target_ids
    assert {"arcade", "arcadeZone"} & target_ids
    assert any(move["role"] == "medical" for move in action_mix["staffing"]["move_staff"])
    assert action_mix["facilities"]["hvac"]["protectShelterComfort"] is True
    assert patched["operator_candidate_frame"]["mode"] == "constraint_compiled_plan_tournament"


def test_parkpulse_api_endpoint_wrappers_cover_recent_surfaces(monkeypatch, tmp_path):
    state = sample_state()

    class FakeParkSimulation:
        async def get_state(self):
            return copy.deepcopy(state)

        async def apply_delivery_outcomes(self, dispatches, source):
            return {"status": "applied", "source": source, "dispatch_count": len(dispatches)}

        async def get_replay(self, limit):
            return {"mode": "replay", "event_count": 1, "limit": limit}

        async def start_replay_run(self, seed, scenario_key):
            return {"status": "started", "seed": seed, "scenario_key": scenario_key}

    async def fake_sync(current_state, force=False):
        return {"status": "synced", "force": force}

    async def fake_agent_benchmark(*args, **kwargs):
        return {"status": "agent_benchmark", "scenario_id": kwargs.get("scenario_id")}

    parkpulse_api.clear_hot_endpoint_cache()
    monkeypatch.setattr(parkpulse_api, "park_simulation", FakeParkSimulation())
    monkeypatch.setattr(parkpulse_api, "sync_park_state_safe", fake_sync)
    monkeypatch.setattr(parkpulse_api, "get_operational_memory_dashboard", lambda query: {"status": {"mode": "test"}, "query": query})
    monkeypatch.setattr(parkpulse_api, "_build_agent_bigquery_priors", lambda scenario, dashboard: {"best_prior": {"cohort": "guest_app"}, "weakest_prior": {}})
    monkeypatch.setattr(parkpulse_api, "delivery_contract", lambda: {"channels": ["guest_app"]})
    monkeypatch.setattr(parkpulse_api, "latest_dispatches", lambda limit: [{"id": "dispatch-1", "status": "sent"}])
    monkeypatch.setattr(parkpulse_api, "delivery_summary", lambda dispatches: {"count": len(dispatches)})
    monkeypatch.setattr(parkpulse_api, "response_summary", lambda dispatches: {"takeRate": 0.5})
    monkeypatch.setattr(parkpulse_api, "delivery_outbox_status", lambda: {"durable_count": 1})
    monkeypatch.setattr(parkpulse_api, "reliability_status", lambda: {"enabled": True})
    monkeypatch.setattr(parkpulse_api, "replay_store_status", lambda: {"backup_count": 2})
    monkeypatch.setattr(parkpulse_api, "backup_replay_store", lambda: {"status": "backed_up"})
    monkeypatch.setattr(parkpulse_api, "list_runtime_governance", lambda limit: {"customer_care_cases": [], "summary": {"limit": limit}})
    monkeypatch.setattr(parkpulse_api, "create_customer_care_case", lambda payload, current_state: {"id": "case-1", **payload})
    monkeypatch.setattr(parkpulse_api, "classify_unstructured_signal", lambda **kwargs: {"id": "signal-1", "text": kwargs["text"]})
    monkeypatch.setattr(parkpulse_api, "realistic_signal_batch", lambda current_state, preset: [{"source": preset}])
    monkeypatch.setattr(parkpulse_api, "fuse_signal_batch", lambda signals, current_state: {"id": "fused", "signals": signals})
    monkeypatch.setattr(parkpulse_api, "_action_execution_for_signal", lambda signal, current_state: {"status": "triaged", "signal": signal})
    monkeypatch.setattr(parkpulse_api, "latest_signals", lambda limit: [{"id": "signal", "limit": limit}])
    monkeypatch.setattr(parkpulse_api, "episode_dataset_status", lambda: {"status": "ready"})
    monkeypatch.setattr(parkpulse_api, "list_digital_twin_tools", lambda: [{"name": "get_park_state"}])
    monkeypatch.setattr(parkpulse_api, "retrieve_operational_context", lambda query, current_state: {"status": {"mode": "test"}, "retrieved": {}})
    monkeypatch.setattr(parkpulse_api, "_collaboration_context", lambda context, scenario, *args: {**context, "scenario": scenario})
    monkeypatch.setattr(parkpulse_api, "run_digital_twin_tool", lambda tool, current_state, arguments, context: {"tool": tool, "arguments": arguments, "context": context})
    monkeypatch.setattr(parkpulse_api, "build_park_action_plan", lambda current_state: {"selected_action": {"target": "ride", "action": "reroute"}})
    monkeypatch.setattr(parkpulse_api, "optimize_park_response", lambda current_state, scenario, context, plan: {"selected_plan": {"id": "opt"}})
    monkeypatch.setattr(parkpulse_api, "build_digital_twin_tool_trace", lambda current_state, scenario, context, plan, optimization: {"tool_calls": [scenario]})
    monkeypatch.setattr(parkpulse_api, "list_benchmark_scenarios", lambda: [{"id": "ride_down"}])
    monkeypatch.setattr(parkpulse_api, "run_parkpulse_agent_benchmark", fake_agent_benchmark)
    monkeypatch.setattr(parkpulse_api, "run_digital_twin_benchmark", lambda current_state, **kwargs: {"status": "benchmark", **kwargs})
    monkeypatch.setattr(parkpulse_api, "send_guest_promotion", lambda payload: {"id": "guest", "status": "sent", "payload": payload})
    monkeypatch.setattr(parkpulse_api, "send_worker_notification", lambda payload: {"id": "worker", "status": "sent", "payload": payload})
    monkeypatch.setattr(parkpulse_api, "send_equipment_command", lambda payload: {"id": "equipment", "status": "sent", "payload": payload})
    monkeypatch.setattr(parkpulse_api, "acknowledge_dispatch", lambda dispatch_id, actor, choice, channel=None: {"id": dispatch_id, "status": choice, "actor": actor, "channel": channel})
    monkeypatch.setattr(parkpulse_api, "record_approval_decision", lambda dispatch_id, actor, decision, reason=None, channel=None: {"id": dispatch_id, "status": "approved_for_execution", "approvalDecision": {"decision": decision, "actor": actor, "reason": reason}, "approvalDelivery": {"pubsub": {"status": "published"}}, "channel": channel})
    monkeypatch.setattr(parkpulse_api, "build_memory_ops_report", lambda query: {"overall_status": "healthy", "query": query})
    monkeypatch.setattr(parkpulse_api, "run_memory_ops_repair", lambda query, collections, limit: {"status": "repaired", "collections": collections, "limit": limit})
    monkeypatch.setattr(parkpulse_api, "run_autodream", lambda scenario_key, max_cases=8, persist=True: {"status": "retired", "scenario_key": scenario_key, "max_cases": max_cases, "persist": persist})
    monkeypatch.setattr(parkpulse_api, "autodream_status", lambda limit=8: {"status": "retired", "limit": limit})
    monkeypatch.setattr(parkpulse_api, "promote_autodream_learning", lambda dream_learning_id, target, reviewer: {"status": "retired", "id": dream_learning_id, "target": target, "reviewer": reviewer})
    monkeypatch.setattr(parkpulse_api, "review_autodream_learning", lambda dream_learning_id, status, reviewer, reason: {"status": "retired", "review_status": status, "id": dream_learning_id, "reason": reason})
    monkeypatch.setattr(parkpulse_api, "run_autodream_benchmark", lambda current_state, **kwargs: {"status": "retired", "summary": {"retired": True}, **kwargs})
    monkeypatch.setattr(parkpulse_api, "record_mongo_autodream_benchmark", lambda benchmark: {"status": "stored", "benchmark_id": "bench-1"})
    monkeypatch.setattr(parkpulse_api, "get_latest_memory_documents", lambda collection, limit: [{"_id": "bench-1", "limit": limit}])
    monkeypatch.setattr(parkpulse_api, "analytics_learning_summary", lambda dashboard: {"status": "analytics", "dashboard": dashboard})
    monkeypatch.setattr(parkpulse_api, "_park_integration_status_cache_ttl_seconds", 0)
    monkeypatch.setattr(parkpulse_api, "_park_monitoring_cache_ttl_seconds", 0)
    monkeypatch.setattr(parkpulse_api, "build_park_integration_status_response", lambda: asyncio.sleep(0, result={"status": "integrated"}))
    monkeypatch.setattr(parkpulse_api, "build_park_agent_monitoring_response", lambda: asyncio.sleep(0, result={"overall_status": "clear"}))
    monkeypatch.setattr(parkpulse_api, "build_review_snapshot", lambda current_state, governance, dispatches, signals, replay: {"review_id": "review-1", "status": "ready", "overall_score": 91, "scenario": {"key": "ride_down"}})
    monkeypatch.setattr(parkpulse_api, "get_park_scenarios", lambda: {"ride_down": {"name": "Ride down"}})
    monkeypatch.setattr(parkpulse_api, "get_agent_registry", lambda: [{"name": "agent"}])
    monkeypatch.setattr(parkpulse_api, "get_agent_topology", lambda: {"nodes": 1})
    monkeypatch.setattr(parkpulse_api, "role_alignment_report", lambda: {"aligned": True})
    monkeypatch.setattr(parkpulse_api, "evaluate_park_decision", lambda scenario, current_state: {"scenario": scenario, "score": 90})

    class PublicStatus:
        def __init__(self, **payload):
            self.payload = payload

        def public_dict(self):
            return self.payload

    monkeypatch.setattr(parkpulse_api, "get_gemini_agent_properties", lambda: PublicStatus(ready=True))
    monkeypatch.setattr(parkpulse_api, "get_gcp_trace_eval_status", lambda: PublicStatus(trace=True))
    monkeypatch.setattr(parkpulse_api, "online_improvement_status", lambda: {"ready": True})
    monkeypatch.setattr(parkpulse_api, "bigquery_status", lambda: {"mode": "test"})
    monkeypatch.setattr(parkpulse_api, "get_arize_status", lambda: PublicStatus(arize=True))
    monkeypatch.setattr(parkpulse_api, "gcp_operations_status", lambda: {"pubsub": {"ready": True}})
    monkeypatch.setattr(parkpulse_api, "pseudo_firebase_status", lambda: {"ready": True})
    monkeypatch.setattr(parkpulse_api, "firestore_status", lambda: {"ready": True, "mirror": {"count": 1}})
    monkeypatch.setattr(parkpulse_api, "latest_pseudo_firebase_messages", lambda limit=50, topic=None: [{"topic": topic, "limit": limit}])
    monkeypatch.setattr(parkpulse_api, "latest_firestore_operations", lambda limit=50, kind=None: [{"kind": kind, "limit": limit}])
    monkeypatch.setattr(parkpulse_api, "publish_park_event", lambda event_type, payload, attributes: {"status": "published", "event_type": event_type, "payload": payload, "attributes": attributes})
    monkeypatch.setattr(parkpulse_api, "start_operator_workflow", lambda payload: {"status": "started", "payload": payload})

    assert run(parkpulse_api.park_bigquery_priors("ride_down"))["best_prior"]["cohort"] == "guest_app"
    assert run(parkpulse_api.park_delivery_contract())["channels"] == ["guest_app"]
    assert run(parkpulse_api.park_delivery_outbox(5))["count"] == 1
    assert run(parkpulse_api.park_reliability())["backup_systems"]["sqlite_replay_backups"] == 2
    assert run(parkpulse_api.park_replay_backup())["status"] == "backed_up"
    assert run(parkpulse_api.park_governance_runtime(3))["domain"] == "amusement_park_operations"
    assert run(parkpulse_api.park_customer_care(2))["summary"]["limit"] == 2
    assert run(parkpulse_api.park_customer_care_create(parkpulse_api.CustomerCareRequest(reason="care")))["case"]["reason"] == "care"
    assert run(parkpulse_api.park_signal_intake(parkpulse_api.SignalIntakeRequest(text="ride stopped")))["status"] == "triaged"
    assert run(parkpulse_api.park_signal_fusion_demo(parkpulse_api.SignalFusionRequest(preset="crowd")))["pipeline"]["name"]
    assert run(parkpulse_api.park_signal_inbox(4))[0]["limit"] == 4
    assert run(parkpulse_api.park_learning_episodes())["status"] == "ready"
    assert run(parkpulse_api.park_digital_twin_tools())[0]["name"] == "get_park_state"
    assert run(parkpulse_api.park_digital_twin_tool_run(parkpulse_api.DigitalTwinToolRequest(tool="get_park_state", arguments={"x": 1})))["tool"] == "get_park_state"
    assert run(parkpulse_api.park_digital_twin_trace())["tool_calls"]
    assert run(parkpulse_api.park_digital_twin_benchmark_scenarios())[0]["id"] == "ride_down"
    assert run(parkpulse_api.park_digital_twin_benchmark(parkpulse_api.DigitalTwinBenchmarkRequest(policy_under_test="agent")))["status"] == "agent_benchmark"
    assert run(parkpulse_api.park_digital_twin_benchmark(parkpulse_api.DigitalTwinBenchmarkRequest(policy_under_test="baseline")))["status"] == "benchmark"
    assert run(parkpulse_api.park_delivery_guest_promotion(parkpulse_api.DeliveryRequest(payload={"message": "go"})))["dispatch"]["id"] == "guest"
    assert run(parkpulse_api.park_delivery_worker_notification(parkpulse_api.DeliveryRequest(payload={"task": "go"})))["dispatch"]["id"] == "worker"
    assert run(parkpulse_api.park_delivery_equipment_command(parkpulse_api.DeliveryRequest(payload={"command": "go"})))["dispatch"]["id"] == "equipment"
    assert run(parkpulse_api.park_delivery_acknowledge(parkpulse_api.DeliveryAckRequest(dispatch_id="dispatch-1", actor="lead", choice="accepted", channel="worker_device")))["status"] == "accepted"
    approval = run(parkpulse_api.park_delivery_approval_decision(parkpulse_api.DeliveryApprovalDecisionRequest(dispatch_id="dispatch-1", actor="lead", decision="approved", reason="ok", channel="equipment_controller")))
    assert approval["status"] == "approved_for_execution"
    assert approval["approval"]["decision"] == "approved"
    assert run(parkpulse_api.gcp_firestore_status())["ready"] is True
    firestore_ops = run(parkpulse_api.gcp_firestore_operations(3, "approvals"))
    assert firestore_ops["count"] == 1
    assert firestore_ops["operations"][0]["kind"] == "approvals"
    assert run(parkpulse_api.park_memory("ride"))["memory_ops"]["overall_status"] == "healthy"
    assert run(parkpulse_api.park_memory_maintenance("ride"))["query"] == "ride"
    assert run(parkpulse_api.park_memory_maintenance_repair(parkpulse_api.MemoryOpsRepairRequest(query="ride", collections=["playbooks"], limit=5)))["status"] == "repaired"
    autodream_run = run(parkpulse_api.park_autodream_run(parkpulse_api.AutoDreamRunRequest(scenario_key="ride_down", max_cases=2, persist=False)))
    assert autodream_run["status"] == "retired"
    assert autodream_run["max_cases"] == 2
    assert run(parkpulse_api.park_autodream_status(6))["status"] == "retired"
    assert run(parkpulse_api.park_autodream_promote(parkpulse_api.AutoDreamPromoteRequest(dream_learning_id="dream-1")))["status"] == "retired"
    retired_review = run(parkpulse_api.park_autodream_review(parkpulse_api.AutoDreamReviewRequest(dream_learning_id="dream-1", review_status="approved", reason="ok")))
    assert retired_review["status"] == "retired"
    assert retired_review["review_status"] == "approved"
    retired_benchmark = run(parkpulse_api.park_autodream_benchmark(parkpulse_api.AutoDreamBenchmarkRequest(scenario_key="ride_down", seeds=2)))
    assert retired_benchmark["status"] == "retired"
    assert "storage" not in retired_benchmark
    assert run(parkpulse_api.park_autodream_benchmarks(99))["latest_benchmarks"][0]["limit"] == 25
    assert run(parkpulse_api.park_analytics("ride"))["status"] == "analytics"
    assert run(parkpulse_api.park_integration_status())["status"] == "integrated"
    assert run(parkpulse_api.park_agent_monitoring())["overall_status"] == "clear"
    smoke_path = tmp_path / "live-smoke.json"
    smoke_path.write_text(json.dumps({"summary": {"status": "passed", "activated_role_count": 10, "activated_department_count": 11}}), encoding="utf-8")
    monkeypatch.setenv("PARKPULSE_LIVE_AGENTS_SMOKE_REPORT", str(smoke_path))
    smoke = run(parkpulse_api.park_live_agents_smoke_latest())
    assert smoke["summary"]["status"] == "passed"
    assert smoke["summary"]["activated_department_count"] == 11
    assert run(parkpulse_api.park_replay(7))["limit"] == 7
    assert run(parkpulse_api.park_replay_start(parkpulse_api.ReplayStartRequest(seed="s", scenario_key="ride_down")))["state"]["guestFlow"]
    assert run(parkpulse_api.park_review_snapshot())["review_id"] == "review-1"
    assert "ride_down" in run(parkpulse_api.park_scenarios())
    assert run(parkpulse_api.park_agent_roles())["role_alignment"]["aligned"] is True
    assert run(parkpulse_api.park_eval_result("ride_down"))["score"] == 90
    assert run(parkpulse_api.gcp_gemini_status())["gemini"]["ready"] is True
    assert run(parkpulse_api.gcp_improvement_status())["ready"] is True
    trace_eval_status = run(parkpulse_api.gcp_trace_eval_status())
    assert trace_eval_status["trace"] is True
    assert trace_eval_status["judge_agent"]["agent_id"] == "gcp_eval_judge_agent"
    assert "score_decision" in trace_eval_status["judge_agent"]["exclusive_tools"]
    assert run(parkpulse_api.gcp_operations_status_endpoint())["pubsub"]["ready"] is True
    assert run(parkpulse_api.gcp_pseudo_firebase_status())["ready"] is True
    assert run(parkpulse_api.gcp_pseudo_firebase_messages(500, "guest"))["messages"][0]["limit"] == 200
    assert run(parkpulse_api.gcp_pubsub_park_event(parkpulse_api.GcpParkEventRequest(event_type="evt", payload={"x": 1}, attributes={"a": "b"})))["status"] == "published"

    monkeypatch.setattr(
        parkpulse_api,
        "decode_eventarc_pubsub_signal",
        lambda body: {"event": {"eventType": "other"}, "text": "ignored", "source": "gcp"},
    )
    assert run(parkpulse_api.gcp_eventarc_park_signal({"message": {}}))["status"] == "ignored"
    monkeypatch.setattr(
        parkpulse_api,
        "decode_eventarc_pubsub_signal",
        lambda body: {"event": {"eventType": "parkpulse.manual.signal"}, "text": "ride stopped", "source": "gcp", "zoneId": "coasterPlaza", "reporterRole": "ops"},
    )
    assert run(parkpulse_api.gcp_eventarc_park_signal({"message": {}}))["gcp_eventarc"]["status"] == "accepted"
    assert run(parkpulse_api.gcp_workflows_operator_approval(parkpulse_api.GcpWorkflowRequest(payload={"dispatch": "d"})))["status"] == "started"
    assert run(parkpulse_api.arize_status())["arize"] is True


def test_parkpulse_api_eventops_lifecycle_and_learning_helpers():
    dispatches = [
        {
            "id": "guest-1",
            "channel": "guest_app",
            "status": "sent",
            "payload": {
                "message": "Split demand",
                "targetMix": [{"destination": "Theater", "destinationId": "theater", "share": 1.0}],
            },
            "response": {"state": "acknowledged"},
        },
        {
            "id": "worker-1",
            "channel": "worker_device",
            "status": "sent",
            "payload": {"task": "Pre-stage crew"},
            "response": {"state": "observed"},
        },
        {
            "id": "equipment-1",
            "channel": "equipment_controller",
            "status": "sent",
            "payload": {"command": "pre-cool", "zones": ["indoorHub"]},
            "response": {"applied": True},
        },
    ]
    proactive = {
        "proactive_id": "proactive-1",
        "summary": {"insight_count": 1, "busiest_zone": "coaster", "busiest_path": "main"},
        "forecast": [{"time": "T+15", "baseline_risk": 0.8}],
        "insights": [{"id": "queue_pressure_prediversion", "agent": "Watchtower", "trigger": "Queue rising"}],
    }
    brief = {"why_now": "Act before the queue locks.", "plan_revision_prompt": "Move food pop-up."}
    response = {
        "takeRate": 0.42,
        "positiveResponseRate": 0.84,
        "reactiveFollowThroughRate": 0.36,
        "score": 78,
        "sampleSize": 80,
        "status": "review",
    }
    outcome = {
        "loop_id": "loop-1",
        "state_impact": {"headline": "Queue moved", "density_delta": -8},
        "learning": {"take_rate_signal": "increase specificity", "next_prompt": "raise offer strength"},
    }
    revision = {"decision_id": "decision-2", "event_plan_id": "event-v2", "plan": {"revision_summary": "Add exit crew."}}

    lifecycle = parkpulse_api._build_eventops_lifecycle(
        proactive,
        brief,
        {"overall": 82},
        dispatches,
        response,
        outcome,
        revision,
        [{"agent": "Watchtower", "trace_span": "span-1", "confidence": 0.9, "policy_refs": ["ops"]}],
        {"conflicts": [{"conflict": "labor", "resolution": "protect breaks", "status": "learning"}]},
        "decision-1",
        "outcome-1",
    )

    assert lifecycle["completed_count"] == lifecycle["stage_count"]
    assert {item["channel"] for item in lifecycle["action_effects"]} == {
        "guest_app",
        "worker_device",
        "equipment_controller",
    }
    assert lifecycle["metrics"]["dispatch_total"] == 3

    comparison = parkpulse_api._build_intelligence_comparison(
        proactive,
        brief,
        response,
        outcome,
        revision,
        {
            "conflicts": [{"conflict": "labor gap", "resolution": "standby pool", "status": "learning"}],
            "gates": [{"gate": "Observed response", "status": "review"}],
        },
        "decision-1",
        "outcome-1",
    )
    assert comparison["after"]["revision_created"] is True
    assert comparison["learning"]["mongodb_rule"] == "increase specificity"

    proof = parkpulse_api._build_two_run_learning_proof(
        response,
        outcome,
        revision,
        {
            "dataset": "analytics",
            "query_name": "priors",
            "best_prior": {"cohort": "targeted", "prior_take_rate": 0.66, "prior_follow_through": 0.58},
            "weakest_prior": {"cohort": "generic"},
        },
        dispatches,
        "decision-1",
        "outcome-1",
        {"retrieved": {"learnings": [{"_id": "learning-1"}, {"missing": True}]}},
    )

    assert proof["memory_write"]["retrieved_learning_ids"] == ["learning-1"]
    assert proof["run_2"]["expected_take_rate"] == 0.66
    assert proof["run_2"]["revision_event_plan_id"] == "event-v2"
