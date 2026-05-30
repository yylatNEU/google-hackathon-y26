import sys
from types import SimpleNamespace

import arize_config


def clear_arize_env(monkeypatch):
    for key in (
        "ARIZE_COLLECTOR_ENDPOINT",
        "ARIZE_SPACE_ID",
        "ARIZE_API_KEY",
        "ENABLE_ARIZE_TRACING",
        "ARIZE_PROJECT_NAME",
        "ARIZE_EXPORT_POLICY",
        "ARIZE_EXPORT_BACKGROUND_SPANS",
        "PHOENIX_PROJECT_NAME",
        "PARKPULSE_ONLINE_IMPROVEMENT_PROVIDER",
        "PARKPULSE_ENABLE_OPTIONAL_ARIZE",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(arize_config, "_startup_error", None)


def test_get_arize_status_defaults_to_disabled(monkeypatch):
    clear_arize_env(monkeypatch)

    status = arize_config.get_arize_status()
    public = status.public_dict()

    assert status.platform == "Arize AX"
    assert status.project_name == "parkpulse-ai"
    assert status.tracing_enabled is False
    assert status.configured is False
    assert public["ready"] is False
    assert public["readiness_issues"] == []


def test_get_arize_status_reports_missing_enabled_config(monkeypatch):
    clear_arize_env(monkeypatch)
    monkeypatch.setenv("ENABLE_ARIZE_TRACING", "true")

    issues = arize_config.get_arize_status().readiness_issues

    assert "ENABLE_ARIZE_TRACING=true but ARIZE_SPACE_ID is missing." in issues
    assert "ENABLE_ARIZE_TRACING=true but ARIZE_API_KEY is missing." in issues


def test_get_arize_status_ready_when_required_env_present(monkeypatch):
    clear_arize_env(monkeypatch)
    monkeypatch.setenv("ENABLE_ARIZE_TRACING", "on")
    monkeypatch.setenv("ARIZE_SPACE_ID", "space-1")
    monkeypatch.setenv("ARIZE_API_KEY", "key-1")
    monkeypatch.setenv("ARIZE_COLLECTOR_ENDPOINT", "https://collector.example")
    monkeypatch.setenv("ARIZE_PROJECT_NAME", "demo-project")

    public = arize_config.get_arize_status().public_dict()

    assert public["project_name"] == "demo-project"
    assert public["ready"] is True
    assert public["readiness_issues"] == []


def test_gcp_improvement_provider_disables_arize_unless_opted_in(monkeypatch):
    clear_arize_env(monkeypatch)
    monkeypatch.setenv("PARKPULSE_ONLINE_IMPROVEMENT_PROVIDER", "gcp")
    monkeypatch.setenv("ENABLE_ARIZE_TRACING", "true")
    monkeypatch.setenv("ARIZE_SPACE_ID", "space-1")
    monkeypatch.setenv("ARIZE_API_KEY", "key-1")
    monkeypatch.setenv("ARIZE_COLLECTOR_ENDPOINT", "https://collector.example")

    status = arize_config.get_arize_status()

    assert status.tracing_enabled is False
    assert status.public_dict()["ready"] is False

    monkeypatch.setenv("PARKPULSE_ENABLE_OPTIONAL_ARIZE", "true")

    opted_in = arize_config.get_arize_status()

    assert opted_in.tracing_enabled is True
    assert opted_in.public_dict()["ready"] is True


def test_trace_endpoint_appends_traces_path_only_when_needed():
    assert arize_config._trace_endpoint("https://collector.example") == "https://collector.example/v1/traces"
    assert arize_config._trace_endpoint("https://collector.example/") == "https://collector.example/v1/traces"
    assert arize_config._trace_endpoint("https://collector.example/v1/traces") == "https://collector.example/v1/traces"


def test_setup_arize_tracing_returns_none_when_disabled(monkeypatch):
    clear_arize_env(monkeypatch)

    assert arize_config.setup_arize_tracing() is None
    assert arize_config.setup_phoenix_tracing() is None
    assert arize_config.get_arize_phoenix_status().platform == "Arize AX"


class FakeResource:
    @staticmethod
    def create(attributes):
        return {"resource": attributes}


class FakeProvider:
    def __init__(self, resource):
        self.resource = resource
        self.processors = []

    def add_span_processor(self, processor):
        self.processors.append(processor)


class FakeExporter:
    def __init__(self, endpoint, headers):
        self.endpoint = endpoint
        self.headers = headers
        self.exported = []

    def export(self, spans):
        self.exported.extend(spans)
        return "success"

    def shutdown(self):
        return True

    def force_flush(self, timeout_millis=30000):
        return True


class FakeBatchSpanProcessor:
    def __init__(self, exporter):
        self.exporter = exporter


def install_fake_otel(monkeypatch, resource_cls=FakeResource):
    trace_module = SimpleNamespace(set_tracer_provider=lambda provider: setattr(trace_module, "provider", provider))
    monkeypatch.setitem(sys.modules, "opentelemetry", SimpleNamespace(trace=trace_module))
    monkeypatch.setitem(sys.modules, "opentelemetry.trace", trace_module)
    monkeypatch.setitem(
        sys.modules,
        "opentelemetry.exporter.otlp.proto.http.trace_exporter",
        SimpleNamespace(OTLPSpanExporter=FakeExporter),
    )
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.resources", SimpleNamespace(Resource=resource_cls))
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.trace", SimpleNamespace(TracerProvider=FakeProvider))
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.trace.export", SimpleNamespace(BatchSpanProcessor=FakeBatchSpanProcessor))


def test_setup_arize_tracing_success_and_startup_error(monkeypatch):
    clear_arize_env(monkeypatch)
    install_fake_otel(monkeypatch)
    monkeypatch.setenv("ENABLE_ARIZE_TRACING", "true")
    monkeypatch.setenv("ARIZE_SPACE_ID", "space")
    monkeypatch.setenv("ARIZE_API_KEY", "key")
    monkeypatch.setenv("ARIZE_COLLECTOR_ENDPOINT", "https://collector")

    provider = arize_config.setup_arize_tracing()

    class BrokenResource:
        @staticmethod
        def create(attributes):
            raise RuntimeError("resource failed")

    clear_arize_env(monkeypatch)
    install_fake_otel(monkeypatch, BrokenResource)
    monkeypatch.setenv("ENABLE_ARIZE_TRACING", "true")
    monkeypatch.setenv("ARIZE_SPACE_ID", "space")
    monkeypatch.setenv("ARIZE_API_KEY", "key")
    failed = arize_config.setup_arize_tracing()
    issues = arize_config.get_arize_status().readiness_issues

    assert isinstance(provider, FakeProvider)
    assert provider.processors[0].exporter.exporter.endpoint == "https://collector/v1/traces"
    assert provider.processors[0].exporter.exporter.headers == {
        "authorization": "key",
        "api_key": "key",
        "arize-space-id": "space",
        "space_id": "space",
        "arize-interface": "otel",
    }
    assert failed is None
    assert any("resource failed" in issue for issue in issues)


class FakeReadableSpan:
    def __init__(self, name, attributes):
        self.name = name
        self.attributes = attributes


def test_useful_span_exporter_drops_noop_background_spans(monkeypatch):
    clear_arize_env(monkeypatch)
    monkeypatch.setenv("ENABLE_ARIZE_TRACING", "true")
    monkeypatch.setenv("ARIZE_SPACE_ID", "space")
    monkeypatch.setenv("ARIZE_API_KEY", "key")
    status = arize_config.get_arize_status()
    exporter = FakeExporter("https://collector/v1/traces", {})
    useful = arize_config.UsefulSpanExporter(exporter, status)

    result = useful.export(
        [
            FakeReadableSpan(
                "parkpulse.mediator.react_to_state",
                {"parkpulse.telemetry.source": "background_loop", "parkpulse.signal.new_count": 0},
            ),
            FakeReadableSpan("api.park_action", {"parkpulse.telemetry.source": "api"}),
            FakeReadableSpan(
                "parkpulse.mediator.react_to_state",
                {"parkpulse.telemetry.source": "background_loop", "parkpulse.signal.new_count": 2},
            ),
        ]
    )

    assert result == "success"
    assert [span.name for span in exporter.exported] == ["api.park_action", "parkpulse.mediator.react_to_state"]


def test_useful_span_exporter_can_keep_all_background_spans(monkeypatch):
    clear_arize_env(monkeypatch)
    monkeypatch.setenv("ENABLE_ARIZE_TRACING", "true")
    monkeypatch.setenv("ARIZE_SPACE_ID", "space")
    monkeypatch.setenv("ARIZE_API_KEY", "key")
    monkeypatch.setenv("ARIZE_EXPORT_BACKGROUND_SPANS", "true")
    status = arize_config.get_arize_status()
    exporter = FakeExporter("https://collector/v1/traces", {})
    useful = arize_config.UsefulSpanExporter(exporter, status)

    useful.export(
        [
            FakeReadableSpan(
                "parkpulse.mediator.react_to_state",
                {"parkpulse.telemetry.source": "background_loop", "parkpulse.signal.new_count": 0},
            )
        ]
    )

    assert [span.name for span in exporter.exported] == ["parkpulse.mediator.react_to_state"]
