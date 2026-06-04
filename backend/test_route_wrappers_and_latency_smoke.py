import asyncio
import json
import sys
import types
import urllib.error

from fastapi import FastAPI
from fastapi.testclient import TestClient


class FakeSimulation:
    async def get_state(self):
        return {"guestFlow": {"activeScenario": {"key": "ride_down"}}}

    async def apply_delivery_outcomes(self, dispatches, reason):
        return {"status": "applied", "count": len(dispatches), "reason": reason}


def client_for(register, deps=None):
    app = FastAPI()
    base_deps = {
        "park_simulation": FakeSimulation(),
        "sync_park_state_safe": lambda state: asyncio.sleep(0, result={"status": "synced"}),
        "clear_hot_endpoint_cache": lambda: None,
    }
    if deps:
        base_deps.update(deps)
    register(app, base_deps)
    return TestClient(app)


def test_latency_smoke_gate_cli_success_refresh_and_failures(monkeypatch, capsys):
    import latency_smoke_gate

    calls = []

    def fake_fetch(url, timeout):
        calls.append((url, timeout))
        return {"summary": {"top_cause": {"name": "ok"}}, "acceptance_gate": {"status": "passed"}}

    monkeypatch.setattr(latency_smoke_gate, "_fetch_json", fake_fetch)
    monkeypatch.setattr(latency_smoke_gate.time, "sleep", lambda seconds: calls.append(("sleep", seconds)))
    monkeypatch.setattr(
        latency_smoke_gate,
        "latency_acceptance_gate",
        lambda diagnostics, fail_on_warning=False: {
            "status": "passed" if not fail_on_warning else "failed",
            "mode": "strict" if fail_on_warning else "normal",
            "blockers": [] if not fail_on_warning else ["warning promoted"],
            "warnings": ["slow"],
            "budgets": {"hot_path": 3},
        },
    )
    monkeypatch.setattr(sys, "argv", ["latency_smoke_gate.py", "--url", "http://x/test", "--refresh", "--wait-seconds", "0.01"])
    assert latency_smoke_gate.main() == 0
    assert calls[0][0] == "http://x/test?refresh=true"
    assert json.loads(capsys.readouterr().out)["status"] == "passed"

    monkeypatch.setattr(sys, "argv", ["latency_smoke_gate.py", "--url", "http://x/test?a=1", "--strict"])
    assert latency_smoke_gate.main() == 1
    assert calls[-1][0] == "http://x/test?a=1"
    assert json.loads(capsys.readouterr().out)["status"] == "failed"

    monkeypatch.setattr(latency_smoke_gate, "_fetch_json", lambda *_args, **_kwargs: (_ for _ in ()).throw(urllib.error.URLError("offline")))
    monkeypatch.setattr(sys, "argv", ["latency_smoke_gate.py"])
    assert latency_smoke_gate.main() == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "diagnostics_unavailable"


def test_delivery_route_wrappers(monkeypatch):
    import park_delivery
    from parkpulse_routes.delivery_routes import register_delivery_routes

    dispatch = {"id": "d1", "status": "delivered", "channel": "guest_app", "response": {"state": "accepted"}}
    monkeypatch.setattr(park_delivery, "delivery_contract", lambda: {"name": "contract"})
    monkeypatch.setattr(park_delivery, "latest_dispatches", lambda limit=20: [dispatch][:limit])
    monkeypatch.setattr(park_delivery, "delivery_summary", lambda rows: {"total": len(rows)})
    monkeypatch.setattr(park_delivery, "response_summary", lambda rows: {"sampleSize": len(rows)})
    monkeypatch.setattr(park_delivery, "delivery_outbox_status", lambda: {"ready": True})
    monkeypatch.setattr(park_delivery, "send_guest_promotion", lambda payload: {**dispatch, "payload": payload})
    monkeypatch.setattr(park_delivery, "send_worker_notification", lambda payload: {**dispatch, "channel": "worker_device", "payload": payload})
    monkeypatch.setattr(park_delivery, "send_equipment_command", lambda payload: {**dispatch, "channel": "equipment_controller", "payload": payload})
    monkeypatch.setattr(park_delivery, "acknowledge_dispatch", lambda *args, **kwargs: {**dispatch, "status": "acknowledged"})
    monkeypatch.setattr(
        park_delivery,
        "record_approval_decision",
        lambda *args, **kwargs: {**dispatch, "status": "approval_recorded", "approvalDecision": {"decision": "approved"}},
    )

    client = client_for(register_delivery_routes)
    assert client.get("/api/park/delivery/contract").json()["name"] == "contract"
    assert client.get("/api/park/delivery/outbox?limit=1").json()["count"] == 1
    assert client.post("/api/park/delivery/guest-promotion", json={"payload": {"x": 1}}).json()["status"] == "delivered"
    assert client.post("/api/park/delivery/worker-notification", json={"payload": {"x": 1}}).json()["dispatch"]["channel"] == "worker_device"
    assert client.post("/api/park/delivery/equipment-command", json={"payload": {"x": 1}}).json()["dispatch"]["channel"] == "equipment_controller"
    assert client.post("/api/park/delivery/acknowledge", json={"dispatch_id": "d1"}).json()["application"]["status"] == "applied"
    approval = client.post("/api/park/delivery/approval-decision", json={"dispatch_id": "d1", "decision": "approved"}).json()
    assert approval["approval"]["decision"] == "approved"


def test_memory_route_wrappers(monkeypatch):
    import bigquery_analytics
    import cache_accuracy_replay
    import memory_ops_agent
    import mongo_memory
    import park_autodream_agent
    import park_autodream_benchmark
    from parkpulse_routes.memory_routes import register_memory_routes

    monkeypatch.setattr(mongo_memory, "get_operational_memory_dashboard", lambda query: {"query": query})
    monkeypatch.setattr(mongo_memory, "get_operational_intelligence", lambda query, scenario_key, agent_role: {"scenario_key": scenario_key, "agent_role": agent_role})
    monkeypatch.setattr(mongo_memory, "get_agent_performance_scorecards", lambda scenario_key, limit: {"scenario_key": scenario_key, "limit": limit})
    monkeypatch.setattr(mongo_memory, "record_autodream_benchmark", lambda benchmark: {"status": "stored", "id": "bench-1"})
    monkeypatch.setattr(mongo_memory, "get_latest_memory_documents", lambda collection, limit: [{"collection": collection, "limit": limit}])
    monkeypatch.setattr(memory_ops_agent, "build_memory_ops_report", lambda query: {"report": query})
    monkeypatch.setattr(memory_ops_agent, "run_memory_ops_repair", lambda query, collections, limit: {"query": query, "collections": collections, "limit": limit})
    monkeypatch.setattr(cache_accuracy_replay, "run_cache_accuracy_replay", lambda state, **kwargs: {"state": bool(state), **kwargs})
    monkeypatch.setattr(park_autodream_agent, "run_autodream", lambda scenario_key, **kwargs: {"scenario_key": scenario_key, **kwargs})
    monkeypatch.setattr(park_autodream_agent, "autodream_status", lambda limit: {"limit": limit})
    monkeypatch.setattr(park_autodream_agent, "promote_autodream_learning", lambda *args: {"promoted": args[0]})
    monkeypatch.setattr(park_autodream_agent, "review_autodream_learning", lambda *args: {"reviewed": args[0], "status": args[1]})
    monkeypatch.setattr(park_autodream_benchmark, "run_autodream_benchmark", lambda state, **kwargs: {"status": "complete", **kwargs})
    monkeypatch.setattr(bigquery_analytics, "analytics_learning_summary", lambda dashboard: {"dashboard": dashboard})

    client = client_for(register_memory_routes)
    assert client.get("/api/park/memory?query=q").json()["memory_ops"]["report"] == "q"
    assert client.get("/api/park/memory/maintenance?query=q").json()["report"] == "q"
    assert client.get("/api/park/memory/intelligence?scenario_key=s&agent_role=a").json()["agent_role"] == "a"
    assert client.get("/api/park/memory/scorecards?limit=500").json()["limit"] == 50
    assert client.post("/api/park/memory/cache-replay", json={"scenario_key": "s", "persist": False}).json()["persist"] is False
    assert client.post("/api/park/memory/maintenance/repair", json={"query": "q", "collections": ["c"], "limit": 3}).json()["limit"] == 3
    assert client.post("/api/park/autodream/run", json={"scenario_key": "s", "max_cases": 2}).json()["max_cases"] == 2
    assert client.get("/api/park/autodream/status?limit=4").json()["limit"] == 4
    assert client.post("/api/park/autodream/promote", json={"dream_learning_id": "d"}).json()["promoted"] == "d"
    assert client.post("/api/park/autodream/review", json={"dream_learning_id": "d", "review_status": "approved"}).json()["status"] == "approved"
    assert client.post("/api/park/autodream/benchmark", json={"scenario_key": "s", "seeds": 2}).json()["storage"]["id"] == "bench-1"
    assert client.get("/api/park/autodream/benchmarks?limit=3").json()["count"] == 1
    assert client.get("/api/park/analytics?query=q").json()["dashboard"]["query"] == "q"


def test_gcp_route_wrappers(monkeypatch, tmp_path):
    import arize_config
    import bigquery_analytics
    import evaluator_loop
    import gcp_operations
    import gcp_trace_eval
    import gemini_provider
    import mongo_memory
    import scenario_eval_sweep
    from parkpulse_routes.gcp_routes import register_gcp_routes

    monkeypatch.setenv("PARKPULSE_GCP_SMOKE_ARTIFACT_PATH", str(tmp_path / "gcp-smoke.json"))
    monkeypatch.setattr(gemini_provider, "get_gemini_agent_properties", lambda: types.SimpleNamespace(public_dict=lambda: {"ready": True}))
    monkeypatch.setattr(gcp_trace_eval, "get_gcp_trace_eval_status", lambda: types.SimpleNamespace(public_dict=lambda: {"ready": True}))
    monkeypatch.setattr(gcp_trace_eval, "verify_gcp_trace_export", lambda: {"status": "flush_succeeded"})
    monkeypatch.setattr(bigquery_analytics, "online_improvement_status", lambda: {"ready": True})
    monkeypatch.setattr(bigquery_analytics, "bigquery_status", lambda: {"ready": True, "project": "demo", "dataset": "parkpulse"})
    monkeypatch.setattr(arize_config, "get_arize_status", lambda: types.SimpleNamespace(public_dict=lambda: {"ready": False}))
    monkeypatch.setattr(
        evaluator_loop,
        "evaluator_loop_status",
        lambda: {
            "status": "local_only",
            "provider": "local_scorecard",
            "hosted_configured": False,
            "hosted_trigger_enabled": False,
            "readiness_issues": ["hosted eval off"],
            "tooling": {"vertex_eval_transport": "rest"},
        },
    )
    monkeypatch.setattr(evaluator_loop, "run_vertex_hosted_evaluation", lambda payload: {"status": "skipped", "provider": "vertex", "evaluator_id": "e", "location": "us", "reason": "off"})
    monkeypatch.setattr(scenario_eval_sweep, "run_vertex_eval_scenario_sweep", lambda *args, **kwargs: asyncio.sleep(0, result={"scenarios": [], "summary": {}}))
    monkeypatch.setattr(scenario_eval_sweep, "build_sweep_analytics_rows", lambda result: {"rows": [{"scenario_count": len(result.get("scenarios", []))}]})
    monkeypatch.setattr(scenario_eval_sweep, "latest_sweep_payload", lambda rows: {"rows": rows})
    monkeypatch.setattr(mongo_memory, "record_scenario_eval_sweep_fast", lambda result: "sweep-1")
    monkeypatch.setattr(mongo_memory, "get_latest_memory_documents_fast", lambda collection, limit: [{"collection": collection, "limit": limit}])

    monkeypatch.setattr(
        gcp_operations,
        "gcp_operations_status",
        lambda: {
            "ready": True,
            "pubsub": {"ready": True, "enabled": True, "topic": "projects/demo/topics/ops"},
            "workflows": {"ready": False, "enabled": False},
            "fcm": {"ready": True, "mode": "pseudo_firebase", "pseudo": {"ready": True}, "guest_topic": "guests", "worker_topic": "workers"},
            "firestore": {"ready": False, "enabled": False, "mirror": {"ready": True}},
            "agent_builder": {"ready": True, "enabled": True, "runtime": "Agent Engine", "agent_count": 12, "tool_count": 40},
            "dataflow": {"ready": False, "enabled": False, "mirror": {"ready": True}},
        },
    )
    monkeypatch.setattr(gcp_operations, "pseudo_firebase_status", lambda: {"ready": True})
    monkeypatch.setattr(gcp_operations, "firestore_status", lambda: {"ready": False})
    monkeypatch.setattr(gcp_operations, "latest_firestore_operations", lambda limit, kind=None: [{"kind": kind, "limit": limit}])
    monkeypatch.setattr(gcp_operations, "vertex_agent_builder_status", lambda: {"ready": True})
    monkeypatch.setattr(gcp_operations, "vertex_agent_builder_registry", lambda: {"agents": []})
    monkeypatch.setattr(gcp_operations, "dataflow_status", lambda: {"ready": True})
    monkeypatch.setattr(gcp_operations, "dataflow_stream_contract", lambda: {"contract": True})
    monkeypatch.setattr(gcp_operations, "latest_dataflow_events", lambda limit, event_type=None: [{"event_type": event_type, "limit": limit}])
    monkeypatch.setattr(gcp_operations, "latest_pseudo_firebase_messages", lambda limit, topic=None: [{"topic": topic, "limit": limit}])
    monkeypatch.setattr(gcp_operations, "publish_park_event", lambda event_type, payload, attributes=None: {"event_type": event_type, "payload": payload, "attributes": attributes})
    monkeypatch.setattr(gcp_operations, "decode_eventarc_pubsub_signal", lambda body: body)
    monkeypatch.setattr(gcp_operations, "start_operator_workflow", lambda payload: {"workflow": payload})

    class Request:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    async def fake_agent_run(request):
        return {
            "status": "complete",
            "scenario_key": request.scenario_key,
            "execute": request.execute,
            "decision_id": "decision-1",
            "outcome_id": "outcome-1",
            "eval": {
                "scorecard": {"overall": 91, "status": "passed", "decision_id": "decision-1"},
                "gcp_trace_eval": {"trace_state": "export_configured", "trace_id": "trace-1", "span_id": "span-1", "ready": True},
                "hosted_eval": {"status": "local_scorecard_only", "trigger": {"status": "not_triggered"}},
            },
            "analytics": {"inserted": False, "row_counts": {"eval_results": 1}, "status": "preview"},
        }

    client = client_for(
        register_gcp_routes,
        {
            "park_agent_run": fake_agent_run,
            "ParkAgentRunRequest": Request,
            "export_agent_analytics": lambda rows: {"exported": rows},
            "action_execution_for_signal": lambda signal, state: {"status": "executed", "signal": signal},
        },
    )
    assert client.get("/api/gcp-gemini/status").json()["agent"]["name"] == "ParkPulse AI"
    assert client.get("/api/gcp-gemini/status").json()["gcp_trace_eval"]["judge_agent"]["agent_id"] == "gcp_eval_judge_agent"
    assert client.get("/api/gcp/improvement-status").json()["ready"] is True
    trace_eval_status = client.get("/api/gcp/trace-eval-status").json()
    assert trace_eval_status["ready"] is True
    assert trace_eval_status["judge_contract"]["owner_agent"] == "gcp_eval_judge_agent"
    assert client.get("/api/gcp/trace-export-verify").json()["status"] == "flush_succeeded"
    evaluator_loop_status = client.get("/api/gcp/evaluator-loop").json()
    assert evaluator_loop_status["status"] == "local_only"
    assert evaluator_loop_status["judge_agent"]["department"] == "qa_judge"
    readiness = client.get("/api/gcp/live-readiness").json()
    assert readiness["judge_agent"]["agent_id"] == "gcp_eval_judge_agent"
    assert readiness["checks"]["pubsub"]["proof_mode"] == "live"
    assert readiness["checks"]["firestore"]["proof_mode"] == "mocked"
    smoke = client.post("/api/gcp/judge-smoke", json={"scenario_key": "ride_down", "execute": False}).json()
    assert smoke["status"] == "complete"
    assert smoke["smoke"]["proof"]["local_scorecard"]["proof_mode"] == "live"
    assert smoke["smoke"]["proof"]["analytics_export"]["proof_mode"] == "mocked"
    assert smoke["artifact"]["status"] == "written"
    evaluator_verify = client.post("/api/gcp/evaluator-loop/verify?scenario_key=s").json()
    assert evaluator_verify["hosted_eval"]["provider"] == "vertex"
    assert evaluator_verify["judge_agent"]["agent_id"] == "gcp_eval_judge_agent"
    assert client.post("/api/gcp/evaluator-loop/scenario-sweep", json={"scenario_keys": ["s"], "timeout_seconds": 5}).json()["persistence"]["mongo_eval_document_id"] == "sweep-1"
    assert client.get("/api/gcp/evaluator-loop/scenario-sweep/latest").json()["rows"][0]["collection"] == "eval_results"
    assert client.get("/api/gcp/operations/status").json()["ready"] is True
    assert client.get("/api/gcp/pseudo-firebase/status").json()["ready"] is True
    assert client.get("/api/gcp/firestore/status").json()["ready"] is False
    assert client.get("/api/gcp/firestore/operations?limit=500&kind=dispatch").json()["operations"][0]["limit"] == 200
    assert client.get("/api/gcp/agent-builder/status").json()["ready"] is True
    assert client.get("/api/gcp/agent-builder/registry").json()["agents"] == []
    assert client.get("/api/gcp/dataflow/status").json()["ready"] is True
    assert client.get("/api/gcp/dataflow/contract").json()["contract"] is True
    assert client.get("/api/gcp/dataflow/events?event_type=x").json()["events"][0]["event_type"] == "x"
    assert client.get("/api/gcp/pseudo-firebase/messages?topic=t").json()["messages"][0]["topic"] == "t"
    assert client.post("/api/gcp/pubsub/park-event", json={"event_type": "e", "payload": {"x": 1}, "attributes": {"a": "b"}}).json()["event_type"] == "e"
    ignored = client.post("/api/gcp/eventarc/park-signal", json={"event": {"eventType": "other"}, "text": "x", "source": "s"}).json()
    assert ignored["status"] == "ignored"
    accepted = client.post("/api/gcp/eventarc/park-signal", json={"event": {"eventType": "parkpulse.manual.signal"}, "text": "guest fainted", "source": "s"}).json()
    assert accepted["status"] == "executed"
    assert client.post("/api/gcp/workflows/operator-approval", json={"payload": {"id": "w"}}).json()["workflow"]["id"] == "w"
    resilience = client.get("/api/gcp/operating-loop-resilience").json()
    assert resilience["status"] in {"passed", "passed_with_conditions"}
    assert resilience["decision"] in {"allow_loop_claim", "allow_with_conditions"}
    assert client.get("/api/arize/status").json()["ready"] is False
