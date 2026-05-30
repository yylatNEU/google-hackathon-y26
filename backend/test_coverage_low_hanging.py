from __future__ import annotations

import io
import json
import sys
import types
import urllib.error

import pytest


def test_agent_role_routing_and_registry_are_copy_safe():
    import agent_role_skills as roles

    registry = roles.list_agent_role_skills()
    registry["roles"][0]["name"] = "mutated"

    assert roles.list_agent_role_skills()["roles"][0]["name"] == "Scan Agent"
    role_modes = {role["mode"]: role for role in roles.list_agent_role_skills()["roles"]}
    assert role_modes["customer"]["permissions"]["dispatch"] is False
    assert "customer_send_to_phone" in role_modes["customer"]["mcp_tools"]
    assert roles.route_agent_role("customer support station recommends a family route")["selected_role"] == "customer"
    assert roles.route_agent_role("run production reliability qa before deploy")["selected_role"] == "qa"
    assert roles.route_agent_role("prevent crowd issue before it starts")["selected_role"] == "proact"
    assert roles.route_agent_role("guest note says dizzy near the queue")["selected_role"] == "proact"
    assert roles.route_agent_role("ride is down send maintenance")["selected_role"] == "react"
    assert roles.route_agent_role("what is happening in the park")["selected_role"] == "scan"
    assert roles.route_agent_role("anything", mode="react")["selected_role"] == "react"


def test_env_bootstrap_fallback_loader_preserves_existing_values(tmp_path, monkeypatch):
    import env_bootstrap

    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "\n".join(
            [
                "# comment",
                "EXISTING=value_from_file",
                "NEW_KEY='quoted value'",
                "MALFORMED",
                " =ignored",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EXISTING", "keep")

    env_bootstrap._fallback_load_dotenv(dotenv_path)

    assert env_bootstrap.os.environ["EXISTING"] == "keep"
    assert env_bootstrap.os.environ["NEW_KEY"] == "quoted value"


def test_trace_helpers_cover_preview_attributes_otel_and_exception_paths(monkeypatch):
    import trace_helpers

    class Span:
        def __init__(self, *, fail_attributes: bool = False):
            self.attrs = {}
            self.exceptions = []
            self.fail_attributes = fail_attributes

        def set_attribute(self, key, value):
            if self.fail_attributes:
                raise RuntimeError("attr failed")
            self.attrs[key] = value

        def record_exception(self, error):
            self.exceptions.append(type(error).__name__)

    assert trace_helpers._json_preview({"x": "y"}, limit=4).endswith("[truncated]")
    assert trace_helpers._json_preview(object()).startswith('"')

    span = Span()
    trace_helpers.set_span_attributes(span, {"a": 1, "b": None, "c": {"nested": True}})
    assert span.attrs["a"] == 1
    assert json.loads(span.attrs["c"]) == {"nested": True}
    trace_helpers.set_span_attributes(Span(fail_attributes=True), {"ignored": "value"})

    fake_span = Span()

    class Context:
        def __enter__(self):
            return fake_span

        def __exit__(self, *_exc):
            return False

    class Tracer:
        def start_as_current_span(self, name):
            assert name in {"otel-span", "failing"}
            return Context()

    fake_trace = types.SimpleNamespace(get_tracer=lambda _name: Tracer())
    fake_otel = types.SimpleNamespace(trace=fake_trace)
    monkeypatch.setitem(sys.modules, "opentelemetry", fake_otel)
    monkeypatch.setenv("PARKPULSE_ENABLE_OTEL_SPANS", "true")

    with trace_helpers.traced_span("otel-span", attributes={"payload": [1]}, input_value={"in": True}) as yielded:
        assert yielded is fake_span
    assert fake_span.attrs["parkpulse.span.kind"] == "chain"
    assert "input.value" in fake_span.attrs

    with pytest.raises(ValueError):
        with trace_helpers.traced_span("failing") as failing_span:
            assert failing_span is fake_span
            raise ValueError("bad")
    assert "ValueError" in fake_span.exceptions


def test_evaluator_loop_vertex_metric_and_transport_branches(monkeypatch):
    import evaluator_loop as loop

    class RubricMetric:
        GENERAL_QUALITY = "general"

    class Metric:
        def __init__(self, name):
            self.name = name

    metrics = loop._vertex_metrics(types.SimpleNamespace(RubricMetric=RubricMetric, Metric=Metric))
    assert metrics[0] == "general"
    assert any(getattr(metric, "name", "") == "instruction_following" for metric in metrics)

    monkeypatch.setenv("PARKPULSE_VERTEX_EVAL_TRANSPORT", "sdk")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("BIGQUERY_PROJECT", raising=False)
    assert loop.run_vertex_hosted_evaluation({})["status"] == "blocked"

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo-project")

    class FakeDataFrame:
        def __init__(self, rows):
            self.rows = rows

    class FakeClient:
        def __init__(self, project, location):
            self.evals = self

        def evaluate(self, dataset, metrics):
            return types.SimpleNamespace(summary_metrics={"score": 0.8})

    class FakeEvaluationDataset:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    fake_types = types.SimpleNamespace(
        EvaluationDataset=FakeEvaluationDataset,
        RubricMetric=types.SimpleNamespace(GENERAL_QUALITY="general"),
        Metric=Metric,
    )
    monkeypatch.setitem(sys.modules, "pandas", types.SimpleNamespace(DataFrame=FakeDataFrame))
    monkeypatch.setitem(sys.modules, "vertexai", types.SimpleNamespace(Client=FakeClient, types=fake_types))
    assert loop.run_vertex_hosted_evaluation({})["status"] == "completed"

    monkeypatch.setenv("VERTEX_EVAL_METRICS", "UNKNOWN_METRIC")
    monkeypatch.setitem(
        sys.modules,
        "vertexai",
        types.SimpleNamespace(Client=FakeClient, types=types.SimpleNamespace(EvaluationDataset=FakeEvaluationDataset)),
    )
    assert loop.run_vertex_hosted_evaluation({})["status"] == "blocked"

    monkeypatch.setenv("PARKPULSE_VERTEX_EVAL_TRANSPORT", "rest")
    monkeypatch.delenv("VERTEX_EVAL_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(loop, "_vertex_access_token", lambda: {"reason": "no token"})
    assert loop.run_vertex_rest_evaluation({})["status"] == "auth_unavailable"


def test_evaluator_loop_rest_success_http_error_and_summary(monkeypatch):
    import evaluator_loop as loop

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo-project")
    monkeypatch.setenv("VERTEX_EVAL_ACCESS_TOKEN", "token")
    monkeypatch.setenv("VERTEX_EVAL_SAMPLING_COUNT", "2")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def read(self):
            return b'{"pointwiseMetricResult":{"score":0.9}}'

    monkeypatch.setattr(loop.urllib.request, "urlopen", lambda request, timeout: Response())
    result = loop.run_vertex_rest_evaluation({"selected_action": {"id": "a"}})
    assert result["status"] == "completed"
    assert result["result"]["score"] == 0.9

    class ErrorResponse(io.BytesIO):
        pass

    def raise_http_error(_request, timeout):
        raise urllib.error.HTTPError("url", 429, "quota", {}, ErrorResponse(b"quota exceeded"))

    monkeypatch.setattr(loop.urllib.request, "urlopen", raise_http_error)
    assert "HTTP 429" in loop.run_vertex_rest_evaluation({})["reason"]

    class BadTable:
        def to_dict(self, orient):
            raise RuntimeError("table failed")

    summary = loop._summarize_vertex_eval_result(
        types.SimpleNamespace(summary_metrics={"quality": 1}, metrics_table=BadTable()),
        [types.SimpleNamespace(name="quality")],
        "demo",
        "us",
        "eval",
    )
    assert summary["result"]["metrics_table"].startswith(
        "<test_coverage_low_hanging.test_evaluator_loop_rest_success_http_error_and_summary.<locals>.BadTable object at "
    )


def test_evaluator_loop_gcloud_metadata_and_payload_branches(monkeypatch):
    import evaluator_loop as loop

    monkeypatch.setenv("VERTEX_EVAL_ACCESS_TOKEN", "env-token")
    assert loop._vertex_access_token()["source"] == "env"

    monkeypatch.delenv("VERTEX_EVAL_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(loop.shutil, "which", lambda name: "/bin/gcloud")

    class Completed:
        stdout = "gcloud-token\n"

    monkeypatch.setattr(loop.subprocess, "run", lambda *args, **kwargs: Completed())
    assert loop._vertex_access_token()["source"] == "gcloud_adc"

    def fail_run(*_args, **_kwargs):
        raise RuntimeError("gcloud down")

    monkeypatch.setattr(loop.subprocess, "run", fail_run)
    assert "gcloud ADC token failed" in loop._vertex_access_token()["reason"]

    monkeypatch.setattr(loop.shutil, "which", lambda name: None)

    class MetadataResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def read(self):
            return b'{"access_token":"metadata-token"}'

    monkeypatch.setattr(loop.urllib.request, "urlopen", lambda request, timeout: MetadataResponse())
    assert loop._vertex_access_token()["source"] == "metadata_server"

    monkeypatch.setattr(loop.urllib.request, "urlopen", lambda request, timeout: (_ for _ in ()).throw(RuntimeError("metadata down")))
    assert "metadata token failed" in loop._vertex_access_token()["reason"]

    assert loop._summarize_dispatches([{"not": "used"}, "bad"])[0]["id"] is None


def test_multi_agent_boundary_helpers_and_conflict_branches(monkeypatch):
    import park_multi_agent as multi

    contract = multi.build_agent_builder_boundary_contract()
    by_id = {agent["id"]: agent for agent in contract["agents"]}
    assert by_id["decision_bridge_agent"]["handoff_to"] == "delivery_proof_agent"
    assert by_id["memory_ops_agent"]["execution_boundary"] == "offline only; no live dispatch"
    assert "review" in by_id["safety_policy_agent"]["decision_rights"]
    assert by_id["customer_support_agent"]["handoff_to"] == "customer_kiosk_ui"
    assert "customer_send_to_phone" in by_id["customer_support_agent"]["allowed_tools"]
    assert "operator_console_redirect" in by_id["customer_support_agent"]["blocked_tools"]
    assert "no operator dispatch" in by_id["customer_support_agent"]["execution_boundary"]
    assert multi.enforce_agent_tool_boundary("customer_support_agent", "customer_send_to_phone")["allowed"] is True
    assert multi.enforce_agent_tool_boundary("customer_support_agent", "dispatch_worker_task")["allowed"] is False

    proposal = multi._role_proposal(
        "unknown_agent",
        "do something",
        {"target": "x"},
        ["signal"],
        ["constraint"],
        2.0,
        "stage",
    )
    assert proposal["agent_id"] == "decision_bridge_agent"
    assert proposal["confidence"] == 1.0

    conflicts = multi._role_proposal_conflicts(
        [
            {"agent_id": "guest_flow_agent"},
            {"agent_id": "staffing_agent"},
            {"agent_id": "food_demand_agent"},
            {"agent_id": "facilities_energy_agent"},
        ],
        "storm_response",
        25,
        {"density": 92},
        {"requires_human_review": True},
    )
    assert len(conflicts) == 4

    food_conflicts = multi._role_proposal_conflicts(
        [{"agent_id": "food_demand_agent"}, {"agent_id": "guest_flow_agent"}],
        "food_spike",
        1,
        {"density": 10},
        {},
    )
    assert any("Food demand" in item["conflict"] for item in food_conflicts)


def test_multi_agent_findings_logic_and_name_mapping():
    import park_multi_agent as multi

    assert multi._top_ride([]) == {}
    assert multi._top_zone([]) == {}
    assert multi._top_path([]) == {}
    assert multi._urgency(90) == "risk"
    assert multi._urgency(70) == "watch"
    assert multi._urgency(10) == "ok"
    assert multi._memory_count({"retrieved": {"playbooks": [1], "incidents": [2], "learnings": [3]}}) == 3

    names = [
        "Placement",
        "traffic flow",
        "creative concept",
        "finance revenue",
        "guest flow",
        "facilities energy",
        "food demand",
        "staff labor",
        "event setup",
        "ride ops",
        "other",
    ]
    mapped = [multi._agent_id_from_name(name) for name in names]
    assert mapped == [
        "placement_agent",
        "traffic_flow_agent",
        "event_creative_agent",
        "finance_agent",
        "guest_flow_agent",
        "facilities_energy_agent",
        "food_demand_agent",
        "staffing_agent",
        "event_setup_agent",
        "ride_ops_agent",
        "decision_bridge_agent",
    ]

    finding = multi._finding("ride_ops_agent", "reactive", [], "f", "r", "invalid", -1)
    assert finding["urgency"] == "watch"
    assert finding["confidence"] == 0.0

    findings = [
        {"agent_id": "guest_flow_agent", "urgency": "risk"},
        {"agent_id": "staffing_agent", "urgency": "watch"},
        {"agent_id": "logic_audit_agent", "urgency": "watch"},
    ]
    run = multi.build_orchestration_run(
        findings,
        "reactive",
        response_metrics={"score": 60, "takeRate": 0.2, "reactiveFollowThroughRate": 0.3},
        event_revision={"event_plan_id": "rev1"},
    )
    assert run["gates"][0]["status"] == "review"
    assert run["gates"][1]["status"] == "revise"
    assert run["gates"][2]["status"] == "v2_stored"
    assert run["logic_graph"]["audit_agent"]["status"] == "updating"
    assert run["conflicts"]
