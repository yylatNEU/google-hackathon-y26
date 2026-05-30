import os
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class GeminiAgentProperties:
    provider: str
    platform: str
    model: str
    use_gemini_enterprise: bool
    use_vertex_ai: bool
    project: str | None
    location: str | None
    enterprise_collection_id: str
    enterprise_engine_id: str | None
    enterprise_assistant_id: str | None
    api_version: str
    credentials_mode: str
    has_api_key: bool
    has_project: bool
    has_location: bool
    has_cloud_runtime_credentials: bool
    phoenix_project: str | None
    phoenix_configured: bool
    phoenix_tracing_enabled: bool
    phoenix_collector_endpoint: str | None
    has_application_credentials_env: bool
    has_adc_file: bool

    def public_dict(self) -> dict:
        data = asdict(self)
        if not self.use_gemini_enterprise:
            data["enterprise_engine_id"] = None
            data["enterprise_assistant_id"] = None
        data["ready"] = self.ready
        data["required_env"] = self.required_env
        data["readiness_issues"] = self.readiness_issues
        return data

    @property
    def ready(self) -> bool:
        if self.use_gemini_enterprise:
            return (
                self.has_project
                and self.has_location
                and bool(self.enterprise_engine_id)
                and bool(self.enterprise_assistant_id)
                and (self.has_application_credentials_env or self.has_adc_file or self.has_cloud_runtime_credentials)
            )
        if self.use_vertex_ai:
            return self.has_project and self.has_location and (
                self.has_application_credentials_env or self.has_adc_file or self.has_cloud_runtime_credentials
            )
        return self.has_api_key

    @property
    def required_env(self) -> list[str]:
        if self.use_gemini_enterprise:
            return [
                "AEROBRIDGE_AGENT_PLATFORM=gemini_enterprise",
                "GOOGLE_CLOUD_PROJECT",
                "GOOGLE_CLOUD_LOCATION",
                "GEMINI_ENTERPRISE_ENGINE_ID",
                "GEMINI_ENTERPRISE_ASSISTANT_ID",
                "Application Default Credentials, GOOGLE_APPLICATION_CREDENTIALS, or Cloud Run service account",
            ]
        if self.use_vertex_ai:
            return [
                "GOOGLE_GENAI_USE_VERTEXAI=true",
                "GOOGLE_CLOUD_PROJECT",
                "GOOGLE_CLOUD_LOCATION",
                "Application Default Credentials, GOOGLE_APPLICATION_CREDENTIALS, or Cloud Run service account",
            ]
        return ["GEMINI_API_KEY or GOOGLE_API_KEY"]

    @property
    def readiness_issues(self) -> list[str]:
        issues: list[str] = []
        if self.use_gemini_enterprise:
            if not self.has_project:
                issues.append("GOOGLE_CLOUD_PROJECT is missing.")
            if not self.has_location:
                issues.append("GOOGLE_CLOUD_LOCATION is missing. Gemini Enterprise commonly uses global, us, or eu.")
            if not self.enterprise_engine_id:
                issues.append("GEMINI_ENTERPRISE_ENGINE_ID is missing.")
            if not self.enterprise_assistant_id:
                issues.append("GEMINI_ENTERPRISE_ASSISTANT_ID is missing.")
            if not (self.has_application_credentials_env or self.has_adc_file or self.has_cloud_runtime_credentials):
                issues.append(
                    "No Gemini Enterprise ADC auth found. Run gcloud auth application-default login, set GOOGLE_APPLICATION_CREDENTIALS, or run on Cloud Run."
                )
        elif self.use_vertex_ai:
            if not self.has_project:
                issues.append("GOOGLE_CLOUD_PROJECT is missing.")
            if not self.has_location:
                issues.append("GOOGLE_CLOUD_LOCATION is missing.")
            if not (self.has_application_credentials_env or self.has_adc_file or self.has_cloud_runtime_credentials):
                issues.append(
                    "No Vertex AI auth found. Run gcloud auth application-default login, set GOOGLE_APPLICATION_CREDENTIALS, or run on Cloud Run."
                )
        elif not self.has_api_key:
            issues.append("GEMINI_API_KEY or GOOGLE_API_KEY is missing.")
        return issues


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _api_key() -> str | None:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def _has_adc_file() -> bool:
    adc_path = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
    return adc_path.exists()


def _has_cloud_runtime_credentials() -> bool:
    return any(os.getenv(name) for name in ("K_SERVICE", "K_REVISION", "K_CONFIGURATION", "GAE_SERVICE"))


def get_gemini_agent_properties() -> GeminiAgentProperties:
    platform = os.getenv("AEROBRIDGE_AGENT_PLATFORM", "").strip().lower()
    use_enterprise = platform in {"gemini_enterprise", "enterprise", "agentspace"}
    use_vertex = _truthy(os.getenv("GOOGLE_GENAI_USE_VERTEXAI"))
    project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT_ID")
    location = os.getenv("GOOGLE_CLOUD_LOCATION") or os.getenv("GOOGLE_CLOUD_REGION") or ("global" if use_enterprise else None)
    api_key = _api_key()
    model = os.getenv("GEMINI_MODEL") or os.getenv("GOOGLE_GENAI_MODEL") or "gemini-2.5-flash"
    api_version = (
        os.getenv("GEMINI_ENTERPRISE_API_VERSION")
        if use_enterprise
        else os.getenv("GOOGLE_GENAI_API_VERSION") or ("v1" if use_vertex else "v1beta")
    )
    api_version = api_version or "v1alpha"
    phoenix_project = os.getenv("PHOENIX_PROJECT_NAME") or "parkpulse-ai"
    collection_id = os.getenv("GEMINI_ENTERPRISE_COLLECTION_ID") or "default_collection"
    engine_id = os.getenv("GEMINI_ENTERPRISE_ENGINE_ID")
    assistant_id = os.getenv("GEMINI_ENTERPRISE_ASSISTANT_ID")
    phoenix_endpoint = os.getenv("PHOENIX_COLLECTOR_ENDPOINT")
    phoenix_tracing_enabled = _truthy(os.getenv("ENABLE_PHOENIX_TRACING"))

    return GeminiAgentProperties(
        provider="Gemini Enterprise API" if use_enterprise else "Vertex AI Gemini" if use_vertex else "Gemini Developer API",
        platform="gemini_enterprise" if use_enterprise else "vertex_ai" if use_vertex else "gemini_api",
        model=model,
        use_gemini_enterprise=use_enterprise,
        use_vertex_ai=use_vertex,
        project=project,
        location=location,
        enterprise_collection_id=collection_id,
        enterprise_engine_id=engine_id,
        enterprise_assistant_id=assistant_id,
        api_version=api_version,
        credentials_mode="adc_or_service_account" if use_enterprise or use_vertex else "api_key",
        has_api_key=bool(api_key),
        has_project=bool(project),
        has_location=bool(location),
        has_cloud_runtime_credentials=_has_cloud_runtime_credentials(),
        phoenix_project=phoenix_project,
        phoenix_configured=bool(os.getenv("PHOENIX_API_KEY") or phoenix_endpoint),
        phoenix_tracing_enabled=phoenix_tracing_enabled,
        phoenix_collector_endpoint=phoenix_endpoint,
        has_application_credentials_env=bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS")),
        has_adc_file=_has_adc_file(),
    )


@lru_cache(maxsize=8)
def get_gemini_client():
    from google import genai
    from google.genai import types

    props = get_gemini_agent_properties()
    api_key = _api_key()
    http_options = types.HttpOptions(api_version=props.api_version)

    if props.use_vertex_ai:
        return genai.Client(
            vertexai=True,
            project=props.project,
            location=props.location,
            http_options=http_options,
        )

    if api_key:
        return genai.Client(api_key=api_key, http_options=http_options)
    return genai.Client(http_options=http_options)


def get_gemini_model() -> str:
    return get_gemini_agent_properties().model


def get_gemini_model_candidates() -> list[str]:
    primary = get_gemini_model()
    fallback_env = os.getenv("GEMINI_MODEL_FALLBACKS") or os.getenv("GOOGLE_GENAI_MODEL_FALLBACKS")
    fallbacks = fallback_env.split(",") if fallback_env else ["gemini-2.0-flash"]
    candidates = [primary, *fallbacks]
    return list(dict.fromkeys(candidate.strip() for candidate in candidates if candidate.strip()))


def assert_gemini_ready() -> None:
    props = get_gemini_agent_properties()
    if props.ready:
        return

    required = ", ".join(props.required_env)
    raise RuntimeError(f"Gemini is not configured. Required environment: {required}")
