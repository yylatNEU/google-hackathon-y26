import json

import pytest

import gemini_enterprise_client


class FakeResponse:
    def __init__(self, ok=True, status_code=200, payload=None, text=""):
        self.ok = ok
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeProps:
    project = "project-1"
    location = "global"
    enterprise_collection_id = "default_collection"
    enterprise_engine_id = "engine-1"
    enterprise_assistant_id = "assistant-1"


def test_enterprise_config_helpers(monkeypatch):
    monkeypatch.setenv("GEMINI_ENTERPRISE_ENDPOINT", "https://example.com/")
    monkeypatch.setenv("GEMINI_ENTERPRISE_API_VERSION", "v1")
    monkeypatch.setenv("GEMINI_ENTERPRISE_TIMEOUT_SECONDS", "7")
    monkeypatch.setattr(gemini_enterprise_client, "get_gemini_agent_properties", lambda: FakeProps())

    assert gemini_enterprise_client._api_base() == "https://example.com"
    assert gemini_enterprise_client._version() == "v1"
    assert gemini_enterprise_client._timeout() == 7
    assert gemini_enterprise_client._assistant_collection_path("project-1").endswith("/engines/engine-1/assistants")


def test_raise_for_response_extract_and_parse_text():
    ok = FakeResponse()
    bad = FakeResponse(ok=False, status_code=500, text="line1\nline2")

    gemini_enterprise_client._raise_for_enterprise_response(ok, "test")
    with pytest.raises(gemini_enterprise_client.GeminiEnterpriseError) as error:
        gemini_enterprise_client._raise_for_enterprise_response(bad, "lookup")

    assert "HTTP 500" in str(error.value)
    assert gemini_enterprise_client._extract_text_parts({"a": [{"text": "one"}, {"nested": {"text": "two"}}]}) == ["one", "two"]
    assert gemini_enterprise_client._parse_stream_assist_text([{"text": "a"}, {"text": "a"}, {"text": "b"}]) == "ab"
    assert gemini_enterprise_client._response_payload(FakeResponse(payload={"ok": True})) == {"ok": True}
    assert gemini_enterprise_client._response_payload(FakeResponse(payload=json.JSONDecodeError("bad", "", 0), text="raw")) == "raw"


def test_resolve_assistant_name_finds_assistant(monkeypatch):
    gemini_enterprise_client.resolve_assistant_name.cache_clear()
    monkeypatch.setattr(gemini_enterprise_client, "assert_gemini_ready", lambda: None)
    monkeypatch.setattr(gemini_enterprise_client, "get_gemini_agent_properties", lambda: FakeProps())
    monkeypatch.setattr(gemini_enterprise_client, "_authorized_headers", lambda: {"Authorization": "Bearer token"})
    monkeypatch.setattr(
        gemini_enterprise_client.requests,
        "get",
        lambda url, headers, timeout: FakeResponse(payload={"assistants": [{"name": "projects/p/locations/global/assistants/assistant-1"}]}),
    )

    assert gemini_enterprise_client.resolve_assistant_name().endswith("/assistant-1")


def test_stream_assist_posts_and_parses_response(monkeypatch):
    monkeypatch.setattr(gemini_enterprise_client, "resolve_assistant_name", lambda: "projects/p/assistants/assistant-1")
    monkeypatch.setattr(gemini_enterprise_client, "_authorized_headers", lambda: {"Authorization": "Bearer token"})
    monkeypatch.setattr(
        gemini_enterprise_client.requests,
        "post",
        lambda url, headers, json, timeout: FakeResponse(payload=[{"answer": {"text": "hello"}}, {"answer": {"text": " world"}}], status_code=200),
    )

    result = gemini_enterprise_client.stream_assist("help", {"guestFlow": {"activeScenario": {"key": "ride_down"}}})

    assert result["text"] == "hello world"
    assert result["assistant_name"] == "projects/p/assistants/assistant-1"
    assert result["raw_chunk_count"] == 2


def test_check_enterprise_health_reports_ready_and_errors(monkeypatch):
    monkeypatch.setattr(gemini_enterprise_client, "resolve_assistant_name", lambda: "assistant")
    ready = gemini_enterprise_client.check_enterprise_health()
    monkeypatch.setattr(gemini_enterprise_client, "resolve_assistant_name", lambda: (_ for _ in ()).throw(RuntimeError("missing")))
    failed = gemini_enterprise_client.check_enterprise_health()

    assert ready["ready"] is True
    assert failed["ready"] is False
    assert failed["readiness_issues"] == ["missing"]


def test_enterprise_auth_retry_and_missing_assistant_branches(monkeypatch):
    class FakeCredentials:
        token = "token-1"

        def refresh(self, request):
            self.token = "token-2"

    monkeypatch.setattr(gemini_enterprise_client, "default", lambda scopes: (FakeCredentials(), "project"))
    monkeypatch.setattr(gemini_enterprise_client, "Request", lambda: object())
    assert gemini_enterprise_client._authorized_headers()["Authorization"] == "Bearer token-2"

    retryable = gemini_enterprise_client.GeminiEnterpriseError("HTTP 503 unavailable")
    non_retryable = gemini_enterprise_client.GeminiEnterpriseError("HTTP 400 bad")
    assert gemini_enterprise_client._retryable_enterprise_error(retryable) is True
    assert gemini_enterprise_client._retryable_enterprise_error(non_retryable) is False
    assert gemini_enterprise_client._retryable_enterprise_error(gemini_enterprise_client.requests.RequestException("timeout")) is True

    class MissingProps(FakeProps):
        project = ""

    gemini_enterprise_client.resolve_assistant_name.cache_clear()
    monkeypatch.setattr(gemini_enterprise_client, "assert_gemini_ready", lambda: None)
    monkeypatch.setattr(gemini_enterprise_client, "get_gemini_agent_properties", lambda: MissingProps())
    with pytest.raises(gemini_enterprise_client.GeminiEnterpriseError):
        gemini_enterprise_client.resolve_assistant_name()

    gemini_enterprise_client.resolve_assistant_name.cache_clear()
    monkeypatch.setattr(gemini_enterprise_client, "get_gemini_agent_properties", lambda: FakeProps())
    monkeypatch.setattr(gemini_enterprise_client, "_authorized_headers", lambda: {"Authorization": "Bearer token"})
    monkeypatch.setattr(
        gemini_enterprise_client.requests,
        "get",
        lambda url, headers, timeout: FakeResponse(payload={"assistants": [{"name": "projects/p/locations/global/assistants/other"}]}),
    )
    with pytest.raises(gemini_enterprise_client.GeminiEnterpriseError) as error:
        gemini_enterprise_client.resolve_assistant_name()
    assert "Available assistants" in str(error.value)
