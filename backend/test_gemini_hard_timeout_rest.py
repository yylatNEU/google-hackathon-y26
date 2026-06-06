from __future__ import annotations

import asyncio
import io
import json
import sys
from types import SimpleNamespace
from urllib.error import URLError

import pytest

import gemini_hard_timeout as hard_timeout


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _install_env_and_provider(monkeypatch, *, vertex_props=None):
    monkeypatch.setitem(sys.modules, "env_bootstrap", SimpleNamespace(load_backend_env=lambda: None))
    provider = SimpleNamespace(
        get_gemini_model=lambda: "gemini test/model",
        get_gemini_agent_properties=lambda: vertex_props
        or SimpleNamespace(use_vertex_ai=True, project="project-1", location="global"),
        get_gemini_client=lambda: SimpleNamespace(
            models=SimpleNamespace(generate_content=lambda **kwargs: SimpleNamespace(text='{"ok": true}'))
        ),
    )
    monkeypatch.setitem(sys.modules, "gemini_provider", provider)
    return provider


def test_gemini_rest_selection_ssl_and_candidate_edges(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "google-key")
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    assert hard_timeout._gemini_rest_available() is True
    assert hard_timeout._candidate_text({"candidates": "bad"}) == ("", {})

    monkeypatch.setitem(sys.modules, "certifi", SimpleNamespace(where=lambda: (_ for _ in ()).throw(RuntimeError("no certs"))))
    called = []
    monkeypatch.setattr(hard_timeout.ssl, "create_default_context", lambda cafile=None: called.append(cafile) or SimpleNamespace())
    assert hard_timeout._ssl_context()
    assert called[-1] is None


def test_gemini_rest_sync_success_and_errors(monkeypatch):
    _install_env_and_provider(monkeypatch)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="API key"):
        hard_timeout._generate_gemini_json_rest_sync({"prompt": "x"}, timeout_seconds=0.1)

    monkeypatch.setenv("GEMINI_API_KEY", "key")
    monkeypatch.setattr(
        hard_timeout.urllib_request,
        "urlopen",
        lambda request, timeout, context=None: Response(
            {
                "candidates": [{"content": {"parts": [{"text": '{"answer":"ok"}'}]}, "finishReason": "STOP"}],
                "usageMetadata": {"totalTokenCount": 3},
            }
        ),
    )
    result = hard_timeout._generate_gemini_json_rest_sync({"prompt": "x"}, timeout_seconds=0.1)
    assert result["transport"] == "gemini_rest_api_key"
    assert result["text"] == '{"answer":"ok"}'
    assert result["finish_reason"] == "STOP"

    monkeypatch.setattr(hard_timeout.urllib_request, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("offline")))
    with pytest.raises(RuntimeError, match="Gemini REST request failed"):
        hard_timeout._generate_gemini_json_rest_sync({"prompt": "x"}, timeout_seconds=0.1)


def test_vertex_rest_sync_success_token_and_configuration_edges(monkeypatch):
    _install_env_and_provider(monkeypatch, vertex_props=SimpleNamespace(use_vertex_ai=False, project="", location=""))
    with pytest.raises(RuntimeError, match="not configured"):
        hard_timeout._generate_vertex_json_rest_sync({"prompt": "x"}, timeout_seconds=0.1)

    _install_env_and_provider(monkeypatch, vertex_props=SimpleNamespace(use_vertex_ai=True, project="project-1", location="us-central1"))

    class Credentials:
        token = None

        def refresh(self, request):
            self.token = "token-1"

    transport_requests = SimpleNamespace(Request=lambda: object())
    google_auth = SimpleNamespace(default=lambda scopes: (Credentials(), None), transport=SimpleNamespace(requests=transport_requests))
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(auth=google_auth))
    monkeypatch.setitem(sys.modules, "google.auth", google_auth)
    monkeypatch.setitem(sys.modules, "google.auth.transport", SimpleNamespace(requests=transport_requests))
    monkeypatch.setitem(sys.modules, "google.auth.transport.requests", transport_requests)
    monkeypatch.setattr(
        hard_timeout.urllib_request,
        "urlopen",
        lambda request, timeout, context=None: Response(
            {"candidates": [{"content": {"parts": [{"text": '{"vertex":true}'}]}, "finishReason": "STOP"}]}
        ),
    )
    result = hard_timeout._generate_vertex_json_rest_sync({"prompt": "x"}, timeout_seconds=0.1)
    assert result["transport"] == "vertex_ai_rest"
    assert result["text"] == '{"vertex":true}'

    class EmptyTokenCredentials:
        token = None

        def refresh(self, request):
            self.token = None

    empty_auth = SimpleNamespace(default=lambda scopes: (EmptyTokenCredentials(), None), transport=SimpleNamespace(requests=transport_requests))
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(auth=empty_auth))
    monkeypatch.setitem(sys.modules, "google.auth", empty_auth)
    with pytest.raises(RuntimeError, match="did not produce"):
        hard_timeout._generate_vertex_json_rest_sync({"prompt": "x"}, timeout_seconds=0.1)


def test_async_fast_paths_and_main_vertex_branch(monkeypatch, capsys):
    monkeypatch.setattr(hard_timeout, "_gemini_rest_available", lambda: True)
    monkeypatch.setattr(hard_timeout, "_generate_gemini_json_rest_sync", lambda *args, **kwargs: {"ok": True, "transport": "gemini"})
    assert asyncio.run(hard_timeout.generate_gemini_json_hard_timeout({"x": 1}, timeout_seconds=0.1))["transport"] == "gemini"

    monkeypatch.setattr(hard_timeout, "_gemini_rest_available", lambda: False)
    monkeypatch.setattr(hard_timeout, "_vertex_rest_available", lambda: True)
    monkeypatch.setattr(hard_timeout, "_generate_vertex_json_rest_sync", lambda *args, **kwargs: {"ok": True, "transport": "vertex"})
    assert asyncio.run(hard_timeout.generate_gemini_json_hard_timeout({"x": 1}, timeout_seconds=0.1))["transport"] == "vertex"

    _install_env_and_provider(monkeypatch)
    monkeypatch.setattr(hard_timeout.sys, "stdin", io.StringIO('{"prompt":{"x":1},"timeout_seconds":0.1}'))
    assert hard_timeout._main() == 0
    assert json.loads(capsys.readouterr().out)["transport"] == "vertex"
