import sys
from types import SimpleNamespace

import gemini_provider


def clear_gemini_env(monkeypatch):
    for key in (
        "AEROBRIDGE_AGENT_PLATFORM",
        "GOOGLE_GENAI_USE_VERTEXAI",
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_PROJECT_ID",
        "GOOGLE_CLOUD_LOCATION",
        "GOOGLE_CLOUD_REGION",
        "GEMINI_ENTERPRISE_ENGINE_ID",
        "GEMINI_ENTERPRISE_ASSISTANT_ID",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_MODEL",
        "GOOGLE_GENAI_MODEL",
        "GEMINI_MODEL_FALLBACKS",
        "GOOGLE_GENAI_MODEL_FALLBACKS",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "K_SERVICE",
        "K_REVISION",
        "K_CONFIGURATION",
        "GAE_SERVICE",
    ):
        monkeypatch.delenv(key, raising=False)


def test_default_gemini_properties_require_api_key(monkeypatch):
    clear_gemini_env(monkeypatch)

    props = gemini_provider.get_gemini_agent_properties()

    assert props.platform == "gemini_api"
    assert props.provider == "Gemini Developer API"
    assert props.ready is False
    assert props.required_env == ["GEMINI_API_KEY or GOOGLE_API_KEY"]
    assert "GEMINI_API_KEY or GOOGLE_API_KEY is missing." in props.readiness_issues


def test_vertex_properties_require_cloud_auth(monkeypatch):
    clear_gemini_env(monkeypatch)
    monkeypatch.setattr(gemini_provider, "_has_adc_file", lambda: False)
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "project-1")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/tmp/service-account.json")

    props = gemini_provider.get_gemini_agent_properties()

    assert props.platform == "vertex_ai"
    assert props.ready is True
    assert props.credentials_mode == "adc_or_service_account"


def test_vertex_properties_use_cloud_run_service_account(monkeypatch):
    clear_gemini_env(monkeypatch)
    monkeypatch.setattr(gemini_provider, "_has_adc_file", lambda: False)
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "project-1")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    monkeypatch.setenv("K_SERVICE", "parkpulse-private-api")

    props = gemini_provider.get_gemini_agent_properties()

    assert props.platform == "vertex_ai"
    assert props.has_cloud_runtime_credentials is True
    assert props.ready is True


def test_enterprise_properties_report_missing_engine_and_auth(monkeypatch):
    clear_gemini_env(monkeypatch)
    monkeypatch.setenv("AEROBRIDGE_AGENT_PLATFORM", "gemini_enterprise")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT_ID", "project-1")

    props = gemini_provider.get_gemini_agent_properties()

    assert props.platform == "gemini_enterprise"
    assert props.location == "global"
    assert props.ready is False
    assert "GEMINI_ENTERPRISE_ENGINE_ID is missing." in props.readiness_issues
    assert "GEMINI_ENTERPRISE_ASSISTANT_ID is missing." in props.readiness_issues


def test_model_candidates_dedupes_and_strips(monkeypatch):
    clear_gemini_env(monkeypatch)
    monkeypatch.setenv("GEMINI_MODEL", "gemini-primary")
    monkeypatch.setenv("GEMINI_MODEL_FALLBACKS", " gemini-primary, gemini-backup, ")

    assert gemini_provider.get_gemini_model_candidates() == ["gemini-primary", "gemini-backup"]


def test_assert_gemini_ready_raises_with_required_env(monkeypatch):
    clear_gemini_env(monkeypatch)

    try:
        gemini_provider.assert_gemini_ready()
    except RuntimeError as error:
        assert "Gemini is not configured" in str(error)
        assert "GEMINI_API_KEY or GOOGLE_API_KEY" in str(error)
    else:
        raise AssertionError("assert_gemini_ready should fail without credentials")


class FakeHttpOptions:
    def __init__(self, api_version):
        self.api_version = api_version


class FakeGenaiClient:
    calls = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        FakeGenaiClient.calls.append(kwargs)


def install_fake_genai(monkeypatch):
    FakeGenaiClient.calls = []
    fake_types = SimpleNamespace(HttpOptions=FakeHttpOptions)
    fake_genai = SimpleNamespace(Client=FakeGenaiClient, types=fake_types)
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=fake_genai))
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)
    gemini_provider.get_gemini_client.cache_clear()


def test_enterprise_public_dict_ready_and_vertex_missing_issues(monkeypatch):
    clear_gemini_env(monkeypatch)
    monkeypatch.setattr(gemini_provider, "_has_adc_file", lambda: False)
    monkeypatch.setenv("AEROBRIDGE_AGENT_PLATFORM", "agentspace")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "project-1")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "global")
    monkeypatch.setenv("GEMINI_ENTERPRISE_ENGINE_ID", "engine-1")
    monkeypatch.setenv("GEMINI_ENTERPRISE_ASSISTANT_ID", "assistant-1")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/tmp/service-account.json")
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "https://collector")
    monkeypatch.setenv("ENABLE_PHOENIX_TRACING", "yes")

    enterprise = gemini_provider.get_gemini_agent_properties()
    public = enterprise.public_dict()

    clear_gemini_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    vertex = gemini_provider.get_gemini_agent_properties()

    assert enterprise.ready is True
    assert public["ready"] is True
    assert public["required_env"][0] == "AEROBRIDGE_AGENT_PLATFORM=gemini_enterprise"
    assert enterprise.phoenix_configured is True
    assert vertex.required_env[0] == "GOOGLE_GENAI_USE_VERTEXAI=true"
    assert "GOOGLE_CLOUD_PROJECT is missing." in vertex.readiness_issues
    assert "GOOGLE_CLOUD_LOCATION is missing." in vertex.readiness_issues
    assert any("No Vertex AI auth" in issue for issue in vertex.readiness_issues)


def test_get_gemini_client_covers_vertex_and_api_key_branches(monkeypatch):
    install_fake_genai(monkeypatch)
    clear_gemini_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "project-1")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    monkeypatch.setenv("GOOGLE_API_KEY", "key-1")
    monkeypatch.setenv("GOOGLE_GENAI_API_VERSION", "v1")
    vertex_client = gemini_provider.get_gemini_client()

    gemini_provider.get_gemini_client.cache_clear()
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    vertex_adc_client = gemini_provider.get_gemini_client()

    gemini_provider.get_gemini_client.cache_clear()
    clear_gemini_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "dev-key")
    api_key_client = gemini_provider.get_gemini_client()

    gemini_provider.get_gemini_client.cache_clear()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    anonymous_client = gemini_provider.get_gemini_client()

    assert vertex_client.kwargs["vertexai"] is True
    assert "api_key" not in vertex_client.kwargs
    assert vertex_adc_client.kwargs["vertexai"] is True
    assert "api_key" not in vertex_adc_client.kwargs
    assert api_key_client.kwargs["api_key"] == "dev-key"
    assert "api_key" not in anonymous_client.kwargs

    monkeypatch.setenv("GEMINI_API_KEY", "ready")
    gemini_provider.assert_gemini_ready()
