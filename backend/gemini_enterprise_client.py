import json
import os
from functools import lru_cache
from typing import Any

import requests
from google.auth import default
from google.auth.transport.requests import Request
from opentelemetry import trace

from gemini_provider import assert_gemini_ready, get_gemini_agent_properties
from reliability import call_with_retries


DISCOVERY_SCOPE = "https://www.googleapis.com/auth/cloud-platform"

PARKPULSE_CONTEXT = """
You are ParkPulse AI, the operations copilot for amusement park incidents.
Industry-fit rule: source systems calculate operational truth; Gemini coordinates, explains,
governs, and audits decisions around those systems. Stay in amusement park operations scope:
ride downtime, queue pressure, guest flow, staff stress, food demand, inventory, energy load,
weather disruption, and operator-ready guest messaging. Do not claim to automate safety-critical
ride controls, override maintenance clearance, expose guest PII, or bypass human approval.
Return only operational recommendations that can be executed by ParkPulse's park action API.
"""


class GeminiEnterpriseError(RuntimeError):
    pass


def _api_base() -> str:
    return os.getenv("GEMINI_ENTERPRISE_ENDPOINT", "https://discoveryengine.googleapis.com").rstrip("/")


def _version() -> str:
    return os.getenv("GEMINI_ENTERPRISE_API_VERSION", "v1alpha")


def _timeout() -> int:
    return int(os.getenv("GEMINI_ENTERPRISE_TIMEOUT_SECONDS", "45"))


def _authorized_headers() -> dict[str, str]:
    credentials, _ = default(scopes=[DISCOVERY_SCOPE])
    credentials.refresh(Request())
    return {
        "Authorization": f"Bearer {credentials.token}",
        "Content-Type": "application/json",
    }


def _assistant_collection_path(project: str) -> str:
    props = get_gemini_agent_properties()
    return (
        f"projects/{project}/locations/{props.location}/collections/"
        f"{props.enterprise_collection_id}/engines/{props.enterprise_engine_id}/assistants"
    )


def _raise_for_enterprise_response(response: requests.Response, action: str) -> None:
    if response.ok:
        return
    detail = response.text[:1200].replace("\n", " ")
    raise GeminiEnterpriseError(f"Gemini Enterprise {action} failed with HTTP {response.status_code}: {detail}")


def _retryable_enterprise_error(error: BaseException) -> bool:
    if isinstance(error, GeminiEnterpriseError):
        text = str(error)
        return any(f"HTTP {code}" in text for code in (408, 409, 425, 429, 500, 502, 503, 504))
    return isinstance(error, requests.RequestException)


@lru_cache(maxsize=16)
def resolve_assistant_name() -> str:
    assert_gemini_ready()
    props = get_gemini_agent_properties()
    if not props.project or not props.enterprise_assistant_id:
        raise GeminiEnterpriseError("Gemini Enterprise project or assistant ID is missing.")

    url = f"{_api_base()}/{_version()}/{_assistant_collection_path(props.project)}"
    def lookup() -> requests.Response:
        response = requests.get(url, headers=_authorized_headers(), timeout=_timeout())
        _raise_for_enterprise_response(response, "assistant lookup")
        return response

    response = call_with_retries(
        "gemini_enterprise.assistant_lookup",
        lookup,
        retryable=_retryable_enterprise_error,
    )

    payload = response.json()
    assistants = payload.get("assistants", [])
    expected_suffix = f"/assistants/{props.enterprise_assistant_id}"
    for assistant in assistants:
        name = assistant.get("name")
        if isinstance(name, str) and name.endswith(expected_suffix):
            return name

    available = [assistant.get("name", "") for assistant in assistants]
    raise GeminiEnterpriseError(
        f"Assistant {props.enterprise_assistant_id} was not found under engine "
        f"{props.enterprise_engine_id}. Available assistants: {available}"
    )


def _extract_text_parts(value: Any) -> list[str]:
    parts: list[str] = []
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str):
            parts.append(text)
        for child in value.values():
            parts.extend(_extract_text_parts(child))
    elif isinstance(value, list):
        for child in value:
            parts.extend(_extract_text_parts(child))
    return parts


def _parse_stream_assist_text(payload: Any) -> str:
    parts = _extract_text_parts(payload)
    deduped: list[str] = []
    for part in parts:
        if part and (not deduped or deduped[-1] != part):
            deduped.append(part)
    return "".join(deduped).strip()


def _response_payload(response: requests.Response) -> Any:
    try:
        return response.json()
    except json.JSONDecodeError:
        return response.text


def stream_assist(
    message: str,
    trace_context: dict[str, Any] | None = None,
    system_context: str | None = None,
    agent_role: str = "parkpulse_decision_bridge",
    blocked_scope: str = "safety_control_override,maintenance_clearance,guest_pii,automated_ride_control",
) -> dict[str, Any]:
    assistant_name = resolve_assistant_name()
    url = f"{_api_base()}/{_version()}/{assistant_name}:streamAssist"
    scoped_message = f"{(system_context or PARKPULSE_CONTEXT).strip()}\n\nUser request:\n{message}"
    body = {
        "query": {"text": scoped_message},
        "assistSkippingMode": "REQUEST_ASSIST",
    }

    tracer = trace.get_tracer("parkpulse.gemini_enterprise")
    with tracer.start_as_current_span("gemini_enterprise.stream_assist") as span:
        span.set_attribute("gen_ai.system", "google_gemini_enterprise")
        span.set_attribute("gen_ai.operation.name", "streamAssist")
        span.set_attribute("gemini_enterprise.assistant", assistant_name)
        span.set_attribute("parkpulse.agent.role", agent_role)
        span.set_attribute("parkpulse.agent.blocked_scope", blocked_scope)
        span.set_attribute("parkpulse.input.length", len(message))
        if trace_context:
            scenario = (trace_context.get("guestFlow", {}) or {}).get("activeScenario", {}) if isinstance(trace_context, dict) else {}
            span.set_attribute("parkpulse.scenario", scenario.get("key", ""))

        def post_stream_assist() -> requests.Response:
            response = requests.post(url, headers=_authorized_headers(), json=body, timeout=_timeout())
            _raise_for_enterprise_response(response, "streamAssist")
            return response

        response = call_with_retries(
            "gemini_enterprise.stream_assist",
            post_stream_assist,
            retryable=_retryable_enterprise_error,
        )
        span.set_attribute("http.status_code", response.status_code)

        payload = _response_payload(response)
        text = _parse_stream_assist_text(payload)
        span.set_attribute("gen_ai.response.text_length", len(text))
        span.set_attribute("gemini_enterprise.raw_chunk_count", len(payload) if isinstance(payload, list) else 1)

    return {
        "text": text,
        "assistant_name": assistant_name,
        "api_version": _version(),
        "endpoint": _api_base(),
        "raw_chunk_count": len(payload) if isinstance(payload, list) else 1,
    }


def check_enterprise_health() -> dict[str, Any]:
    try:
        assistant_name = resolve_assistant_name()
        return {
            "ready": True,
            "assistant_name": assistant_name,
            "api_version": _version(),
            "endpoint": _api_base(),
            "readiness_issues": [],
        }
    except Exception as error:
        return {
            "ready": False,
            "assistant_name": None,
            "api_version": _version(),
            "endpoint": _api_base(),
            "readiness_issues": [str(error)],
        }
