from types import SimpleNamespace

import trace_context


def _install_current_span(monkeypatch, *, trace_id: int, span_id: int, is_valid: bool = True):
    span_context = SimpleNamespace(trace_id=trace_id, span_id=span_id, is_valid=is_valid)
    span = SimpleNamespace(get_span_context=lambda: span_context)
    trace = SimpleNamespace(get_current_span=lambda: span)
    monkeypatch.setitem(__import__("sys").modules, "opentelemetry", SimpleNamespace(trace=trace))


def test_current_trace_context_returns_empty_when_no_valid_span():
    context = trace_context.current_trace_context()

    assert context == {
        "trace_id": "",
        "span_id": "",
        "trace_lookup_query": "",
        "trace_url": "",
    }


def test_current_trace_context_formats_valid_span_and_url(monkeypatch):
    monkeypatch.setenv("PARKPULSE_ENABLE_OTEL_SPANS", "true")
    monkeypatch.setenv("ARIZE_TRACE_URL_TEMPLATE", "https://trace.example/{trace_id}/{span_id}")
    _install_current_span(monkeypatch, trace_id=0x123, span_id=0x456)
    context = trace_context.current_trace_context()

    assert context["trace_id"] == "00000000000000000000000000000123"
    assert context["span_id"] == "0000000000000456"
    assert context["trace_lookup_query"] == "trace_id:00000000000000000000000000000123"
    assert context["trace_url"] == "https://trace.example/00000000000000000000000000000123/0000000000000456"


def test_current_trace_context_uses_gcp_project_and_empty_valid_span(monkeypatch):
    monkeypatch.setenv("PARKPULSE_ENABLE_OTEL_SPANS", "true")
    monkeypatch.delenv("GCP_TRACE_URL_TEMPLATE", raising=False)
    monkeypatch.delenv("ARIZE_TRACE_URL_TEMPLATE", raising=False)
    monkeypatch.setenv("GCP_TRACE_PROJECT", "park-project")
    _install_current_span(monkeypatch, trace_id=0xABC, span_id=0xDEF)
    context = trace_context.current_trace_context()

    assert context["trace_url"].endswith("project=park-project&tid=00000000000000000000000000000abc")

    monkeypatch.delenv("GCP_TRACE_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    no_project = trace_context.current_trace_context()

    assert no_project["trace_url"] == ""
