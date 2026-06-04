import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import digital_twin_gate
import gcp_trace_eval
import gemini_hard_timeout
import main
import park_operator_constraints
import scenario_eval_sweep


def run(coro):
    return asyncio.run(coro)


def test_digital_twin_gate_cli_latest_and_fresh_run(monkeypatch, tmp_path, capsys):
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps({"run_id": "r1", "summary": {"failed": 0}}))
    gates = []

    def fake_gate(report, **kwargs):
        gates.append((report, kwargs))
        return {"passed": kwargs["max_failed"] == 0, "kwargs": kwargs}

    monkeypatch.setattr(digital_twin_gate, "evaluate_benchmark_gate", fake_gate)
    monkeypatch.setattr(sys, "argv", ["digital_twin_gate.py", "--report", str(report_path), "--allow-policy-violations", "--allow-learned-regression"])
    assert digital_twin_gate.main() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "passed"
    assert gates[-1][1]["fail_on_policy_gate_violation"] is False
    assert gates[-1][1]["fail_on_learned_regression"] is False

    monkeypatch.setattr(digital_twin_gate, "ParkSimulation", lambda: SimpleNamespace(get_state=lambda: asyncio.sleep(0, result={"state": True})))
    monkeypatch.setattr(digital_twin_gate, "run_digital_twin_benchmark", lambda state, scenario_id=None, seed=None: {"fresh": state, "scenario_id": scenario_id, "seed": seed})
    monkeypatch.setattr(digital_twin_gate, "record_benchmark_result", lambda result: {**result, "recorded": True})
    monkeypatch.setattr(digital_twin_gate, "latest_benchmark_report", lambda: {"run_id": "fresh", "summary": {}})
    monkeypatch.setattr(sys, "argv", ["digital_twin_gate.py", "--seed", "s1", "--scenario-id", "ride", "--max-failed", "1"])
    assert digital_twin_gate.main() == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"


def test_scenario_eval_sweep_edges_and_async_outcomes():
    assert scenario_eval_sweep._parse_iso(None) is None
    assert scenario_eval_sweep._parse_iso("not-a-date") is None
    assert scenario_eval_sweep._as_float("bad") is None
    assert scenario_eval_sweep._vertex_score_100({"score": 0.82}) == 82
    assert scenario_eval_sweep._selected_action({"optimization": {"selected_plan": {"selected_action": {"label": "A"}}}})["label"] == "A"

    result = {
        "scenario_key": "ride_down",
        "status": "complete",
        "decision_id": "d1",
        "outcome_id": "o1",
        "planner": {"selected_action": {"label": "Fallback", "target": "ride", "action": "reroute", "owner": "Ops"}},
        "eval": {
            "scorecard": {"overall": 80, "plan_quality_score": 79, "outcome_effectiveness_score": 81, "score_method": "unit", "status": "ok", "response_score": 78, "policy_gate_status": "clear", "needs_human_approval": False},
            "dimension_scores": {"Safety": 70, "Grounding": 90},
            "failure_reasons": ["low safety"],
            "hosted_eval": {"vertex_result": {"status": "completed", "transport": "vertex", "result": {"score": 0.95, "explanation": "ok"}, "evaluator_id": "eval1", "location": "us"}},
        },
        "delivery": {"response": {"status": "ok", "score": 77, "takeRate": 0.4, "positiveResponseRate": 0.7, "reactiveFollowThroughRate": 0.5}},
    }
    summary = scenario_eval_sweep.summarize_scenario_result(result, elapsed_ms=12)
    assert summary["comparison"]["delta_vertex_minus_internal"] == 15
    assert summary["comparison"]["needs_review"] is True
    rows = scenario_eval_sweep.build_sweep_analytics_rows({"sweep_id": "sweep", "scenarios": [summary, "bad"]})
    assert rows["eval_results"][0]["decision_id"] == "d1"

    recent = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    latest = scenario_eval_sweep.latest_sweep_payload([{"documentType": "scenario_eval_sweep", "_id": "s1", "createdAt": recent, "summary": {"scenario_count": 1}, "scenarios": [summary]}])
    assert latest["freshness"]["status"] == "fresh"
    stale = scenario_eval_sweep.latest_sweep_payload([{"documentType": "scenario_eval_sweep", "_id": "s2", "createdAt": (datetime.now(UTC) - timedelta(hours=48)).isoformat(), "summary": {}, "scenarios": []}])
    assert stale["freshness"]["stale"] is True
    assert scenario_eval_sweep.latest_sweep_payload([])["status"] == "empty"

    async def scenario_runner(key, execute):
        if key == "timeout":
            await asyncio.sleep(0.02)
        if key == "error":
            raise RuntimeError("boom")
        return {**result, "scenario_key": key}

    sweep = run(scenario_eval_sweep.run_vertex_eval_scenario_sweep(scenario_runner, scenario_keys=["ride_down", "error", "timeout"], timeout_seconds=0.001))
    assert sweep["summary"]["scenario_count"] == 3
    assert {row["status"] for row in sweep["scenarios"]} >= {"complete", "error", "timeout"}


def test_gemini_hard_timeout_subprocess_success_errors_and_worker(monkeypatch, capsys):
    monkeypatch.setenv("PARKPULSE_DISABLE_GEMINI_REST_FAST_PATH", "1")

    class FakeProcess:
        def __init__(self, stdout=b'{"ok":true,"text":"{}"}', stderr=b"", returncode=0, delay=0):
            self.stdout = stdout
            self.stderr = stderr
            self.returncode = returncode
            self.delay = delay
            self.killed = False

        async def communicate(self, payload=None):
            if self.delay:
                await asyncio.sleep(self.delay)
            return self.stdout, self.stderr

        def kill(self):
            self.killed = True

    async def create_success(*args, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(gemini_hard_timeout.asyncio, "create_subprocess_exec", create_success)
    assert run(gemini_hard_timeout.generate_gemini_json_hard_timeout({"x": 1}, timeout_seconds=1))["ok"] is True

    async def create_bad_json(*args, **kwargs):
        return FakeProcess(stdout=b"not-json")

    monkeypatch.setattr(gemini_hard_timeout.asyncio, "create_subprocess_exec", create_bad_json)
    with pytest.raises(RuntimeError, match="invalid JSON"):
        run(gemini_hard_timeout.generate_gemini_json_hard_timeout({}, timeout_seconds=1))

    async def create_worker_error(*args, **kwargs):
        return FakeProcess(stdout=b'{"ok":false,"error":"nope"}')

    monkeypatch.setattr(gemini_hard_timeout.asyncio, "create_subprocess_exec", create_worker_error)
    with pytest.raises(RuntimeError, match="nope"):
        run(gemini_hard_timeout.generate_gemini_json_hard_timeout({}, timeout_seconds=1))

    async def create_nonzero(*args, **kwargs):
        return FakeProcess(stderr=b"worker failed", returncode=2)

    monkeypatch.setattr(gemini_hard_timeout.asyncio, "create_subprocess_exec", create_nonzero)
    with pytest.raises(RuntimeError, match="worker failed"):
        run(gemini_hard_timeout.generate_gemini_json_hard_timeout({}, timeout_seconds=1))

    async def create_timeout(*args, **kwargs):
        return FakeProcess(delay=0.6)

    monkeypatch.setattr(gemini_hard_timeout.asyncio, "create_subprocess_exec", create_timeout)
    with pytest.raises(TimeoutError):
        run(gemini_hard_timeout.generate_gemini_json_hard_timeout({}, timeout_seconds=0.001))

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(gemini_hard_timeout.sys, "stdin", SimpleNamespace(read=lambda: json.dumps({"prompt": {"hello": "world"}})))

    class FakeTypes:
        class ThinkingConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class GenerateContentConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

    class FakeClient:
        models = SimpleNamespace(generate_content=lambda **kwargs: SimpleNamespace(text='{"ok":1}'))

    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=SimpleNamespace(types=FakeTypes)))
    monkeypatch.setitem(sys.modules, "google.genai", SimpleNamespace(types=FakeTypes))
    monkeypatch.setattr("gemini_provider.get_gemini_client", lambda: FakeClient())
    monkeypatch.setattr("gemini_provider.get_gemini_model", lambda: "gemini-test")
    assert gemini_hard_timeout._main() == 0
    assert json.loads(capsys.readouterr().out)["transport"] == "google_genai_sdk"


def test_gemini_rest_fast_path_does_not_override_vertex_mode(monkeypatch):
    monkeypatch.delenv("PARKPULSE_DISABLE_GEMINI_REST_FAST_PATH", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "dev-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "dev-google-key")
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")

    assert gemini_hard_timeout._gemini_rest_available() is False

    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "false")
    assert gemini_hard_timeout._gemini_rest_available() is True


def test_gcp_trace_eval_exporter_and_flush_paths(monkeypatch):
    for key in ("BIGQUERY_PROJECT", "GOOGLE_CLOUD_PROJECT", "GCP_TRACE_PROJECT", "ENABLE_GCP_CLOUD_TRACE_EXPORT", "GCP_TRACE_URL_TEMPLATE", "ENABLE_VERTEX_GENAI_EVAL", "VERTEX_GENAI_EVALUATOR_ID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(gcp_trace_eval, "_gcp_trace_exporter", None)
    monkeypatch.setattr(gcp_trace_eval, "_gcp_trace_provider", None)
    monkeypatch.setattr(gcp_trace_eval, "_gcp_trace_startup_error", None)
    assert gcp_trace_eval.verify_gcp_trace_export()["status"] == "not_configured"

    monkeypatch.setenv("ENABLE_GCP_CLOUD_TRACE_EXPORT", "true")
    assert gcp_trace_eval.setup_gcp_cloud_trace_exporter() is None
    assert "no GCP_TRACE_PROJECT" in gcp_trace_eval.get_gcp_trace_eval_status().trace_export_error

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "project")
    processors = []

    class FakeTrace:
        provider = SimpleNamespace()

        @classmethod
        def get_tracer_provider(cls):
            return cls.provider

        @classmethod
        def set_tracer_provider(cls, provider):
            cls.provider = provider

    class FakeTracerProvider:
        def __init__(self, resource=None):
            self.resource = resource

        def add_span_processor(self, processor):
            processors.append(processor)

        def force_flush(self, *args, **kwargs):
            return True

    fake_modules = {
        "opentelemetry": SimpleNamespace(trace=FakeTrace),
        "opentelemetry.trace": FakeTrace,
        "opentelemetry.exporter.cloud_trace": SimpleNamespace(CloudTraceSpanExporter=lambda project_id: SimpleNamespace(project_id=project_id, force_flush=lambda *args, **kwargs: True)),
        "opentelemetry.sdk.resources": SimpleNamespace(Resource=SimpleNamespace(create=lambda attrs: attrs)),
        "opentelemetry.sdk.trace": SimpleNamespace(TracerProvider=FakeTracerProvider),
        "opentelemetry.sdk.trace.export": SimpleNamespace(BatchSpanProcessor=lambda exporter: ("processor", exporter)),
    }
    for name, module in fake_modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    provider = gcp_trace_eval.setup_gcp_cloud_trace_exporter()
    assert provider is not None
    assert processors
    assert gcp_trace_eval._force_flush_gcp_trace() is True

    monkeypatch.setattr(gcp_trace_eval, "_gcp_trace_provider", SimpleNamespace(force_flush=lambda *args: False))
    assert gcp_trace_eval._force_flush_gcp_trace() is False
    monkeypatch.setattr(gcp_trace_eval, "_gcp_trace_provider", SimpleNamespace(force_flush=lambda *args: (_ for _ in ()).throw(TypeError("kw"))))
    monkeypatch.setattr(gcp_trace_eval, "_gcp_trace_exporter", SimpleNamespace(force_flush=lambda timeout_millis=0: True))
    assert gcp_trace_eval._force_flush_gcp_trace() is False


def test_main_lazy_entrypoint_helpers_and_http_routes(monkeypatch):
    monkeypatch.setenv("PARKPULSE_REQUIRE_SIGNED_ROLE_TOKEN", "0")
    monkeypatch.setenv("PARKPULSE_HOT_PATH_TIMEOUT_SECONDS", "bad")
    assert main._timeout_tiers()["hot_path_seconds"] == 3
    assert main._api_capability_registry()["entrypoint"] == "lazy-main"
    assert main._agent_run_request_fields({"scenarioKey": "ride_down", "execute": "false"})["execute"] is False

    payload = main._store_run_receipt({"status": "ok", "run_telemetry": {"delivery": {"summary": {}}}}, message="m", mode="mode", kind="unit", receipt_id="unit-receipt")
    assert payload["run_receipt"]["id"] == "unit-receipt"
    main._mark_receipt_upgrade_status("unit-receipt", "running", {"x": 1})
    assert main._run_receipts["unit-receipt"]["receipt"]["upgrade_status"] == "running"

    async def failing_full_module(timeout=None):
        raise RuntimeError("full runtime offline")

    monkeypatch.setattr(main, "_get_full_module", failing_full_module)
    monkeypatch.setattr(main, "_schedule_operator_command_refinement", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "_schedule_agent_run_refinement", lambda *args, **kwargs: None)
    fallback = run(main._build_operator_payload_with_runtime("Coaster is down", "auto", False, "unit"))
    assert fallback["status"] == "bounded_fallback"

    async def call_app(method, path, body=None, query=b""):
        sent = []
        body_bytes = json.dumps(body or {}).encode()
        received = False

        async def receive():
            nonlocal received
            if received:
                return {"type": "http.disconnect"}
            received = True
            return {"type": "http.request", "body": body_bytes, "more_body": False}

        async def send(message):
            sent.append(message)

        await main.app({"type": "http", "method": method, "path": path, "query_string": query, "headers": []}, receive, send)
        status = next(item["status"] for item in sent if item["type"] == "http.response.start")
        response_body = b"".join(item.get("body", b"") for item in sent if item["type"] == "http.response.body")
        return status, json.loads(response_body or b"{}")

    assert run(call_app("OPTIONS", "/healthz"))[0] == 204
    assert run(call_app("GET", "/healthz"))[1]["service"] == "parkpulse-api"
    assert run(call_app("GET", "/readyz"))[1]["entrypoint"] == "lazy-main"
    assert run(call_app("GET", "/api/park/full-runtime-status"))[1]["status"] in {"idle", "loading", "loaded", "failed"}
    assert run(call_app("GET", "/api/park/api-capabilities"))[1]["status"] == "ready"
    assert run(call_app("GET", "/api/park/run-receipt/missing"))[0] == 404

    async def fake_agent_run(payload, reason):
        return {"status": "complete", "reason": reason, "payload": payload}

    monkeypatch.setattr(main, "_build_agent_run_payload_with_runtime", fake_agent_run)
    assert run(call_app("POST", "/api/park/agent-run", {"scenario_key": "ride_down"}))[1]["status"] == "complete"
    assert run(call_app("GET", "/api/park/state"))[1]["guestFlow"]
    assert run(call_app("GET", "/api/park/integration-status"))[1]["entrypoint"] == "lazy-main"
    assert run(call_app("GET", "/api/park/agent-role-skills", query=b"message=scan&mode=scan"))[1]["route"]["selected_role"] == "scan"
    assert run(call_app("GET", "/api/park/proactive-insights"))[1]["summary"]["insight_count"] >= 1


def test_operator_constraints_edge_branches():
    state = {
        "guestFlow": {
            "zones": [{"id": "foodCourt1", "name": "Original Food Name"}, {"id": "arcadeZone", "name": "Arcade Zone"}],
            "rides": [{"id": "show1", "name": "Theater B", "zone": "theaterB"}],
        }
    }
    text = "Avoid Food Court A because it is full. Send guests to arcade and theater. Wheelchair help for VIP families near Theater B. HVAC too cold."
    route = {"requires_human_review": False}
    constraints = park_operator_constraints.extract_operator_constraints(text, state, route)
    assert any(item["name"] == "Food Court A" for item in constraints["avoid_zones"])
    assert any(item["segment"] == "priority_pass_guests" for item in constraints["guest_segments"])
    assert any(move["role"] == "accessibility_support" for move in constraints["required_staff_moves"])
    assert constraints["equipment_controls"][0]["equipmentType"] == "hvac"

    understanding = {
        "intent_summary": "Move guests",
        "inferred_incident_type": "crowd",
        "avoid_zones": [{"id": "a", "name": "A"}],
        "preferred_destinations": [{"name": "B"}],
        "required_staff_moves": [{"role": "security", "count": 2, "from_location": "Base", "to_location": "Gate", "deadline_minutes": 4}],
        "equipment_controls": [{"equipment_type": "signage", "zones": ["z"], "settings": {"message": "go"}}],
        "guest_segments": ["families"],
        "hard_constraints": ["no unsafe routing"],
        "soft_preferences": ["calm"],
    }
    normalized = park_operator_constraints.constraints_from_genai_understanding(understanding, "m", route)
    assert normalized["requires_human_review"] is True

    optimization = {
        "selected_plan_id": "p1",
        "selected_plan": {
            "id": "p1",
            "score": 70,
            "action_mix": {
                "guest_reroute": {"enabled": True, "target_mix": [{"destinationId": "foodCourt1", "destination": "Food Court A", "share": "bad"}]},
                "staffing": {"move_staff": []},
            },
        },
        "candidates": [],
    }
    patched = park_operator_constraints.apply_operator_constraints_to_optimization(optimization, constraints, state, "ride_down")
    reroute = patched["selected_plan"]["action_mix"]["guest_reroute"]
    assert reroute["operatorConstraintAware"] is True
    assert all(target.get("destinationId") != "foodCourt1" for target in reroute["target_mix"])
    assert patched["operator_constraints"]["source"].startswith("operator_text")
