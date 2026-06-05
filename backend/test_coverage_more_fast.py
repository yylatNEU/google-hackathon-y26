from __future__ import annotations

import asyncio
import builtins
import io
import json
import sys
import types
import urllib.error

import pytest


def test_trace_context_valid_template_project_and_invalid_paths(monkeypatch):
    import trace_context

    monkeypatch.delenv("PARKPULSE_ENABLE_OTEL_SPANS", raising=False)
    monkeypatch.delenv("ARIZE_TRACE_URL_TEMPLATE", raising=False)
    monkeypatch.delenv("GCP_TRACE_PROJECT", raising=False)
    assert trace_context.current_trace_context()["trace_id"] == ""

    monkeypatch.setenv("PARKPULSE_ENABLE_OTEL_SPANS", "true")
    monkeypatch.setitem(sys.modules, "opentelemetry", types.SimpleNamespace())
    assert trace_context.current_trace_context()["trace_id"] == ""

    class SpanContext:
        is_valid = False
        trace_id = 1
        span_id = 2

    class Span:
        def get_span_context(self):
            return SpanContext()

    fake_trace = types.SimpleNamespace(get_current_span=lambda: Span())
    monkeypatch.setitem(sys.modules, "opentelemetry", types.SimpleNamespace(trace=fake_trace))
    assert trace_context.current_trace_context()["trace_id"] == ""

    SpanContext.is_valid = True
    monkeypatch.setenv("GCP_TRACE_URL_TEMPLATE", "https://trace/{project}/{trace_id}/{span_id}")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo-project")
    payload = trace_context.current_trace_context()
    assert payload["trace_id"] == "00000000000000000000000000000001"
    assert payload["span_id"] == "0000000000000002"
    assert payload["trace_url"] == "https://trace/demo-project/00000000000000000000000000000001/0000000000000002"

    monkeypatch.delenv("GCP_TRACE_URL_TEMPLATE", raising=False)
    assert "console.cloud.google.com" in trace_context.current_trace_context()["trace_url"]

    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    assert trace_context.current_trace_context()["trace_url"] == ""


def test_trace_helpers_finish_payload_noop_and_import_failure(monkeypatch):
    import trace_helpers

    noop = trace_helpers._NoopSpan()
    assert noop.set_attribute("x", "y") is None
    assert noop.record_exception(RuntimeError("ignored")) is None

    original_dumps = trace_helpers.json.dumps
    monkeypatch.setattr(trace_helpers.json, "dumps", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("json failed")))
    assert trace_helpers._json_preview({"fallback": True}).startswith("{")
    monkeypatch.setattr(trace_helpers.json, "dumps", original_dumps)

    class Span:
        def __init__(self):
            self.attrs = {}

        def set_attribute(self, key, value):
            self.attrs[key] = value

    span = Span()
    trace_helpers.finish_span(span, output_value={"ok": True}, attributes={"extra": "yes"})
    assert "output.value" in span.attrs
    assert span.attrs["extra"] == "yes"

    monkeypatch.setattr(trace_helpers, "current_trace_context", lambda: {"trace_id": "t"})
    assert trace_helpers.traced_payload({"extra": 1}) == {"trace_id": "t", "extra": 1}

    class BrokenOtel:
        @property
        def trace(self):
            raise RuntimeError("otel import failed")

    monkeypatch.setitem(sys.modules, "opentelemetry", BrokenOtel())
    monkeypatch.setenv("PARKPULSE_ENABLE_OTEL_SPANS", "true")
    with trace_helpers.traced_span("broken-otel") as fallback_span:
        assert isinstance(fallback_span, trace_helpers._NoopSpan)


def test_gcp_trace_eval_exporter_setup_verify_and_flush(monkeypatch):
    import gcp_trace_eval

    monkeypatch.setattr(gcp_trace_eval, "_gcp_trace_exporter", None)
    monkeypatch.setattr(gcp_trace_eval, "_gcp_trace_provider", None)
    monkeypatch.setattr(gcp_trace_eval, "_gcp_trace_startup_error", None)
    monkeypatch.delenv("ENABLE_GCP_CLOUD_TRACE_EXPORT", raising=False)
    assert gcp_trace_eval.setup_gcp_cloud_trace_exporter() is None

    monkeypatch.setenv("ENABLE_GCP_CLOUD_TRACE_EXPORT", "true")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GCP_TRACE_PROJECT", raising=False)
    monkeypatch.delenv("BIGQUERY_PROJECT", raising=False)
    assert gcp_trace_eval.setup_gcp_cloud_trace_exporter() is None
    assert "no GCP_TRACE_PROJECT" in gcp_trace_eval.get_gcp_trace_eval_status().trace_export_error

    class ProviderWithoutAdd:
        pass

    class ProviderWithFlush:
        def __init__(self, resource=None):
            self.resource = resource
            self.processors = []

        def add_span_processor(self, processor):
            self.processors.append(processor)

        def force_flush(self, timeout_millis=None):
            return True

    class Exporter:
        def __init__(self, project_id):
            self.project_id = project_id

        def force_flush(self, *_args, **_kwargs):
            return True

    class Resource:
        @staticmethod
        def create(payload):
            return payload

    fake_trace = types.SimpleNamespace(
        get_tracer_provider=lambda: ProviderWithoutAdd(),
        set_tracer_provider=lambda provider: setattr(fake_trace, "provider", provider),
    )
    monkeypatch.setitem(sys.modules, "opentelemetry", types.SimpleNamespace(trace=fake_trace))
    monkeypatch.setitem(sys.modules, "opentelemetry.exporter.cloud_trace", types.SimpleNamespace(CloudTraceSpanExporter=Exporter))
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.resources", types.SimpleNamespace(Resource=Resource))
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.trace", types.SimpleNamespace(TracerProvider=ProviderWithFlush))
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.trace.export", types.SimpleNamespace(BatchSpanProcessor=lambda exporter: {"exporter": exporter}))
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo-project")

    provider = gcp_trace_eval.setup_gcp_cloud_trace_exporter()
    assert isinstance(provider, ProviderWithFlush)
    assert gcp_trace_eval.setup_gcp_cloud_trace_exporter() is provider

    monkeypatch.setattr(
        gcp_trace_eval,
        "current_trace_context",
        lambda: {
            "trace_id": "abc",
            "span_id": "def",
            "trace_lookup_query": "trace_id:abc",
            "trace_url": "",
        },
    )
    verified = gcp_trace_eval.verify_gcp_trace_export()
    assert verified["status"] == "flush_succeeded"
    assert verified["verified"] is True
    assert "console.cloud.google.com" in verified["trace_url"]

    class TypeErrorFlush:
        def force_flush(self, *_args):
            raise TypeError("named only")

    monkeypatch.setattr(gcp_trace_eval, "_gcp_trace_provider", TypeErrorFlush())
    monkeypatch.setattr(gcp_trace_eval, "_gcp_trace_exporter", types.SimpleNamespace(force_flush=lambda timeout_millis=None: False))
    assert gcp_trace_eval._force_flush_gcp_trace() is False

    monkeypatch.setattr(gcp_trace_eval, "_gcp_trace_provider", types.SimpleNamespace(force_flush=lambda *_args: False))
    monkeypatch.setattr(gcp_trace_eval, "_gcp_trace_exporter", None)
    assert gcp_trace_eval._force_flush_gcp_trace() is False


def test_gcp_trace_eval_status_and_eval_trace_modes(monkeypatch):
    import gcp_trace_eval

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo")
    monkeypatch.setenv("ENABLE_BIGQUERY_ANALYTICS", "true")
    monkeypatch.setenv("ENABLE_VERTEX_GENAI_EVAL", "true")
    monkeypatch.setenv("VERTEX_GENAI_EVALUATOR_ID", "eval-1")
    monkeypatch.setenv("ENABLE_VERTEX_CONTINUOUS_EVAL", "true")
    monkeypatch.setenv("GCP_TRACE_URL_TEMPLATE", "https://trace/{trace_id}")
    monkeypatch.setattr(gcp_trace_eval, "_gcp_trace_exporter", object())
    status = gcp_trace_eval.get_gcp_trace_eval_status().public_dict()
    assert status["ready"] is True
    assert status["evaluation"]["continuous_monitoring"]["configured"] is True

    monkeypatch.setattr(
        gcp_trace_eval,
        "current_trace_context",
        lambda: {"trace_id": "trace", "span_id": "span", "trace_lookup_query": "trace_id:trace", "trace_url": "url"},
    )
    payload = gcp_trace_eval.build_gcp_eval_trace(span="s", eval_subject="decision", dimensions=["safety"], decision_id="d")
    assert payload["trace_state"] == "export_configured"
    assert payload["evaluation_status"] == "hosted_continuous_configured"


def test_gemini_hard_timeout_worker_error_payloads(monkeypatch):
    import gemini_hard_timeout

    class Process:
        def __init__(self, stdout=b"", stderr=b"", returncode=0):
            self.stdout = stdout
            self.stderr = stderr
            self.returncode = returncode
            self.killed = False

        async def communicate(self, _payload=None):
            return self.stdout, self.stderr

        def kill(self):
            self.killed = True

    async def run_with(process):
        async def fake_create(*_args, **_kwargs):
            return process

        monkeypatch.setenv("PARKPULSE_DISABLE_GEMINI_REST_FAST_PATH", "1")
        monkeypatch.setenv("PARKPULSE_DISABLE_VERTEX_REST_FAST_PATH", "1")
        monkeypatch.setattr(gemini_hard_timeout.asyncio, "create_subprocess_exec", fake_create)
        return await gemini_hard_timeout.generate_gemini_json_hard_timeout({"x": 1}, timeout_seconds=1)

    with pytest.raises(RuntimeError, match="worker exploded"):
        asyncio.run(run_with(Process(stderr=b"worker exploded", returncode=2)))
    with pytest.raises(RuntimeError, match="invalid JSON"):
        asyncio.run(run_with(Process(stdout=b"not-json")))
    with pytest.raises(RuntimeError, match="bad payload"):
        asyncio.run(run_with(Process(stdout=b'{"ok":false,"error":"bad payload"}')))


def test_gemini_hard_timeout_main_rest_success_and_errors(monkeypatch, capsys):
    import gemini_hard_timeout

    monkeypatch.setenv("GOOGLE_API_KEY", "key")
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    monkeypatch.delenv("PARKPULSE_DISABLE_GEMINI_REST_FAST_PATH", raising=False)
    monkeypatch.setitem(sys.modules, "env_bootstrap", types.SimpleNamespace(load_backend_env=lambda: ()))
    monkeypatch.setitem(
        sys.modules,
        "gemini_provider",
        types.SimpleNamespace(
            get_gemini_model=lambda: "gemini-test",
            get_gemini_client=lambda: (_ for _ in ()).throw(AssertionError("SDK path should not run")),
        ),
    )

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def read(self):
            return json.dumps({"candidates": [{"content": {"parts": [{"text": '{"ok":true}'}, {"text": ""}]}}]}).encode()

    monkeypatch.setattr(gemini_hard_timeout.sys, "stdin", io.StringIO('{"prompt":{"task":"x"},"temperature":0.1,"max_output_tokens":10}'))
    monkeypatch.setattr(gemini_hard_timeout.urllib_request, "urlopen", lambda request, timeout, context=None: Response())
    assert gemini_hard_timeout._main() == 0
    assert json.loads(capsys.readouterr().out)["transport"] == "gemini_rest_api_key"

    class ErrorBody(io.BytesIO):
        pass

    def raise_http(_request, timeout=None, context=None):
        raise urllib.error.HTTPError("url", 400, "bad", {}, ErrorBody(b"bad request"))

    monkeypatch.setattr(gemini_hard_timeout.sys, "stdin", io.StringIO("{}"))
    monkeypatch.setattr(gemini_hard_timeout.urllib_request, "urlopen", raise_http)
    with pytest.raises(RuntimeError, match="Gemini REST HTTP 400"):
        gemini_hard_timeout._main()

    monkeypatch.setattr(gemini_hard_timeout.sys, "stdin", io.StringIO("{}"))
    monkeypatch.setattr(gemini_hard_timeout.urllib_request, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(urllib.error.URLError("offline")))
    with pytest.raises(RuntimeError, match="Gemini REST request failed"):
        gemini_hard_timeout._main()


def test_gemini_hard_timeout_main_sdk_fallback(monkeypatch, capsys):
    import gemini_hard_timeout

    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("PARKPULSE_DISABLE_VERTEX_REST_FAST_PATH", "1")
    monkeypatch.setitem(sys.modules, "env_bootstrap", types.SimpleNamespace(load_backend_env=lambda: ()))

    class Config:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class ThinkingConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class Models:
        def generate_content(self, model, contents, config):
            assert model == "gemini-sdk"
            assert contents == '{"task":"sdk"}'
            assert config.kwargs["thinking_config"].kwargs["thinking_budget"] == 0
            return types.SimpleNamespace(text='{"sdk":true}')

    monkeypatch.setitem(
        sys.modules,
        "gemini_provider",
        types.SimpleNamespace(
            get_gemini_model=lambda: "gemini-sdk",
            get_gemini_client=lambda: types.SimpleNamespace(models=Models()),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "google.genai",
        types.SimpleNamespace(types=types.SimpleNamespace(GenerateContentConfig=Config, ThinkingConfig=ThinkingConfig)),
    )
    monkeypatch.setattr(gemini_hard_timeout.sys, "stdin", io.StringIO('{"prompt":{"task":"sdk"}}'))

    assert gemini_hard_timeout._main() == 0
    assert json.loads(capsys.readouterr().out)["transport"] == "google_genai_sdk"


def test_trace_helpers_exception_recording_failure_is_swallowed(monkeypatch):
    import trace_helpers

    class Span:
        def set_attribute(self, *_args, **_kwargs):
            raise RuntimeError("attribute write failed")

        def record_exception(self, _error):
            raise RuntimeError("record failed")

    class Context:
        def __enter__(self):
            return Span()

        def __exit__(self, *_exc):
            return False

    fake_trace = types.SimpleNamespace(get_tracer=lambda _name: types.SimpleNamespace(start_as_current_span=lambda _span: Context()))
    monkeypatch.setitem(sys.modules, "opentelemetry", types.SimpleNamespace(trace=fake_trace))
    monkeypatch.setenv("PARKPULSE_ENABLE_OTEL_SPANS", "true")

    with pytest.raises(ValueError, match="boom"):
        with trace_helpers.traced_span("records-error"):
            raise ValueError("boom")


def test_park_eval_helper_branches():
    import park_eval

    assert park_eval._bounded(-3) == 0
    assert park_eval._bounded(103) == 100
    assert park_eval._scenario_from_state({"guestFlow": []}) == {}

    care_scores = park_eval._incident_response_scores(
        "medical",
        "dispatch",
        [
            {"channel": "worker_device", "payload": {"role": "medical", "task": "Assist guest near gate"}},
            {"channel": "guest_app", "payload": {"message": "Please use alternate path"}},
        ],
        {"positiveResponseRate": 0.75, "reactiveFollowThroughRate": 0.5},
    )
    assert [item["label"] for item in care_scores] == [
        "Incident response fit",
        "Sensitive-care privacy",
        "Responder acknowledgement",
    ]
    assert care_scores[0]["score"] > 90
    assert care_scores[1]["score"] == 96
    assert care_scores[2]["score"] == 68

    unsafe_scores = park_eval._incident_response_scores(
        "security",
        "escort",
        [{"channel": "guest_app", "payload": {"message": "patient name and diagnosis visible"}}],
        {"positiveResponseRate": 0, "reactiveFollowThroughRate": 0},
    )
    assert unsafe_scores[0]["score"] < 75
    assert unsafe_scores[1]["score"] == 48
    assert park_eval._incident_response_scores("ride", "reroute", [], {}) == []

    summary = park_eval._score_summary(
        [
            {"label": "Safety", "score": 90},
            {"label": "Take rate", "score": 50},
            {"label": "Responder acknowledgement", "score": 100},
        ],
        {},
    )
    assert summary["plan_quality_score"] == 90
    assert summary["outcome_effectiveness_score"] == 75
    assert summary["overall"] == 80
    assert park_eval._score_summary([{"label": "Safety", "score": 20}], {"score": 140})["outcome_effectiveness_score"] == 100

    digest = park_eval._state_digest(
        {
            "alerts": [{"id": 1}, {"id": 2}],
            "guestFlow": {
                "activeScenario": {"key": "ride_down"},
                "rides": [
                    {"id": "r1", "status": "down", "waitMins": 0},
                    {"name": "Coaster", "waitMins": 80, "queueGuests": 120},
                ],
                "zones": [
                    {"name": "Low", "density": 0.2, "currentGuests": 10},
                    {"name": "High", "density": 0.9, "currentGuests": 90},
                ],
            },
        }
    )
    assert digest["down_rides"] == ["r1"]
    assert digest["overloaded_rides"][0]["name"] == "Coaster"
    assert digest["busiest_zones"][0]["name"] == "High"

    assert park_eval._policy_guidance_score(None) == 84
    assert park_eval._policy_guidance_score({"gate_status": "blocked", "findings": [1, 2]}) == 54
    assert park_eval._policy_guidance_score({"gate_status": "review", "findings": [1]}) == 88
    assert park_eval._policy_guidance_score({"gate_status": "pending_operator_approval", "findings": list(range(20))}) == 76
    assert park_eval._policy_guidance_score({"gate_status": "clear", "findings": [1, 2]}) == 96
    assert park_eval._policy_guidance_score({"gate_status": "unknown"}) == 84

    reasons = park_eval._failure_reasons(
        [{"label": "Safety", "score": 70, "detail": "too low"}, {"label": "Capacity", "score": 90, "detail": "ok"}],
        "blocked",
        True,
    )
    assert [reason["dimension"] for reason in reasons] == ["Safety", "Policy gate", "Human approval"]
    assert reasons[1]["score"] == 0
    assert park_eval._failure_reasons([], "review", False)[0]["score"] == 75


def test_gcp_operations_fcm_pseudo_status_and_publish_branches(monkeypatch, tmp_path):
    import gcp_operations

    monkeypatch.setenv("PARKPULSE_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("ENABLE_PARKPULSE_FCM", raising=False)
    monkeypatch.delenv("ENABLE_PARKPULSE_PSEUDO_FCM", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    gcp_operations._pseudo_fcm_messages.clear()

    assert gcp_operations._topic_path("events") == "events"
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "demo")
    assert gcp_operations._topic_path("events") == "projects/demo/topics/events"
    assert gcp_operations._topic_path("projects/x/topics/events") == "projects/x/topics/events"

    assert gcp_operations._string_data({"skip": None, "ok": True, "num": 3, "payload": {"a": "b"}})["ok"] == "true"
    assert gcp_operations._fcm_message_for_dispatch({"channel": "unknown"})[2] == "FCM is not configured for channel unknown"
    monkeypatch.setenv("PARKPULSE_FCM_GUEST_TOPIC", "")
    assert gcp_operations.fcm_dispatch_for_delivery({"channel": "guest_app"})["reason"] == "FCM topic is not set"

    monkeypatch.setenv("PARKPULSE_FCM_GUEST_TOPIC", "guests")
    assert gcp_operations.fcm_dispatch_for_delivery({"channel": "guest_app"})["reason"] == "ENABLE_PARKPULSE_FCM is false"

    monkeypatch.setenv("ENABLE_PARKPULSE_PSEUDO_FCM", "true")
    result = gcp_operations.fcm_dispatch_for_delivery(
        {
            "id": "dispatch-1",
            "channel": "guest_app",
            "status": "sent",
            "targetSystem": "guest_app",
            "payload": {"message": "Move to north gate", "decisionId": "d1"},
        }
    )
    assert result["status"] == "sent"
    assert result["provider"] == "pseudo_firebase"
    assert result["durable"] is True
    assert gcp_operations.latest_pseudo_firebase_messages(topic="guests")[0]["dispatchId"] == "dispatch-1"
    assert gcp_operations.pseudo_firebase_status()["message_count"] == 1

    broken_file = tmp_path / "broken.jsonl"
    broken_file.write_text("{not-json}\n", encoding="utf-8")
    monkeypatch.setenv("PARKPULSE_PSEUDO_FCM_OUTBOX", str(broken_file))
    assert gcp_operations.latest_pseudo_firebase_messages()[0]["dispatchId"] == "dispatch-1"

    class BadPath:
        parent = types.SimpleNamespace(mkdir=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("mkdir failed")))

        def __str__(self):
            return "/bad/path"

        def exists(self):
            raise RuntimeError("stat failed")

    monkeypatch.setattr(gcp_operations, "_pseudo_fcm_path", lambda: BadPath())
    status = gcp_operations.pseudo_firebase_status()
    assert status["ready"] is False
    assert "stat failed" in status["error"]
    durable_error = gcp_operations.send_pseudo_firebase_message("topic", "title", "body", {}, {"id": "d2"}, {})
    assert durable_error["durable"] is False
    assert "mkdir failed" in durable_error["durabilityError"]

    monkeypatch.setenv("ENABLE_PARKPULSE_PUBSUB", "false")
    assert gcp_operations.publish_park_event("signal", {"x": 1})["status"] == "skipped"

    monkeypatch.setenv("ENABLE_PARKPULSE_PUBSUB", "true")
    monkeypatch.delenv("PARKPULSE_PUBSUB_TOPIC", raising=False)
    assert gcp_operations.publish_park_event("signal", {"x": 1})["reason"] == "PARKPULSE_PUBSUB_TOPIC is not set"

    monkeypatch.setenv("PARKPULSE_PUBSUB_TOPIC", "events")
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "google.cloud" and "pubsub_v1" in fromlist:
            raise ImportError("missing pubsub")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    unavailable = gcp_operations.publish_park_event("signal", {"x": 1})
    assert unavailable["status"] == "unavailable"
    assert "missing pubsub" in unavailable["reason"]
