from __future__ import annotations

import asyncio
import json
import os
import ssl
import sys
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError
from pathlib import Path
from typing import Any
from urllib.parse import quote


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _gemini_rest_available() -> bool:
    if _truthy(os.getenv("PARKPULSE_DISABLE_GEMINI_REST_FAST_PATH")):
        return False
    if _truthy(os.getenv("GOOGLE_GENAI_USE_VERTEXAI")):
        return False
    if os.getenv("GEMINI_API_KEY"):
        return True
    return bool(os.getenv("GOOGLE_API_KEY"))


def _vertex_rest_available() -> bool:
    if _truthy(os.getenv("PARKPULSE_DISABLE_VERTEX_REST_FAST_PATH")):
        return False
    if not _truthy(os.getenv("GOOGLE_GENAI_USE_VERTEXAI")):
        return False
    return bool(
        (os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT_ID"))
        and (os.getenv("GOOGLE_CLOUD_LOCATION") or os.getenv("GOOGLE_CLOUD_REGION"))
    )


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _candidate_text(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    candidate = payload.get("candidates", [{}])[0] if isinstance(payload.get("candidates"), list) else {}
    parts = candidate.get("content", {}).get("parts", []) if isinstance(candidate, dict) else []
    text = "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict))
    return text, candidate if isinstance(candidate, dict) else {}


def _generate_gemini_json_rest_sync(
    prompt: dict[str, Any],
    *,
    timeout_seconds: float,
    max_output_tokens: int = 600,
    temperature: float = 0.2,
) -> dict[str, Any]:
    from env_bootstrap import load_backend_env
    from gemini_provider import get_gemini_model

    load_backend_env()
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Gemini REST API key is not configured.")
    model = os.getenv("PARKPULSE_FAST_GEMINI_MODEL") or get_gemini_model()
    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{quote(model, safe='')}:generateContent?key={quote(api_key, safe='')}"
    )
    body = json.dumps(
        {
            "contents": [{"role": "user", "parts": [{"text": json.dumps(prompt, separators=(',', ':'), sort_keys=True)}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": float(temperature),
                "maxOutputTokens": int(max_output_tokens),
                "thinkingConfig": {"thinkingBudget": 0},
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")
    http_request = urllib_request.Request(
        endpoint,
        data=body,
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(http_request, timeout=max(0.5, timeout_seconds), context=_ssl_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini REST HTTP {error.code}: {detail[:500]}") from error
    except URLError as error:
        raise RuntimeError(f"Gemini REST request failed: {error}") from error
    text, candidate = _candidate_text(payload)
    return {
        "ok": True,
        "text": text,
        "transport": "gemini_rest_api_key",
        "finish_reason": candidate.get("finishReason") if isinstance(candidate, dict) else None,
        "usage_metadata": payload.get("usageMetadata") if isinstance(payload.get("usageMetadata"), dict) else {},
    }


def _generate_vertex_json_rest_sync(
    prompt: dict[str, Any],
    *,
    timeout_seconds: float,
    max_output_tokens: int = 600,
    temperature: float = 0.2,
) -> dict[str, Any]:
    from env_bootstrap import load_backend_env
    from gemini_provider import get_gemini_agent_properties, get_gemini_model
    import google.auth
    import google.auth.transport.requests

    load_backend_env()
    props = get_gemini_agent_properties()
    if not props.use_vertex_ai or not props.project or not props.location:
        raise RuntimeError("Vertex AI REST is not configured with project and location.")

    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(google.auth.transport.requests.Request())
    token = getattr(credentials, "token", None)
    if not token:
        raise RuntimeError("Vertex AI credentials did not produce an access token.")

    model = os.getenv("PARKPULSE_FAST_GEMINI_MODEL") or get_gemini_model()
    location = str(props.location)
    host = "aiplatform.googleapis.com" if location == "global" else f"{location}-aiplatform.googleapis.com"
    endpoint = (
        f"https://{host}/v1/projects/{quote(str(props.project), safe='')}"
        f"/locations/{quote(location, safe='')}/publishers/google/models/{quote(model, safe='')}:generateContent"
    )
    body = json.dumps(
        {
            "contents": [{"role": "user", "parts": [{"text": json.dumps(prompt, separators=(",", ":"), sort_keys=True)}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": float(temperature),
                "maxOutputTokens": int(max_output_tokens),
                "thinkingConfig": {"thinkingBudget": 0},
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")
    http_request = urllib_request.Request(
        endpoint,
        data=body,
        headers={"content-type": "application/json", "authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(http_request, timeout=max(0.5, timeout_seconds), context=_ssl_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Vertex AI REST HTTP {error.code}: {detail[:500]}") from error
    except URLError as error:
        raise RuntimeError(f"Vertex AI REST request failed: {error}") from error

    text, candidate = _candidate_text(payload)
    return {
        "ok": True,
        "text": text,
        "transport": "vertex_ai_rest",
        "finish_reason": candidate.get("finishReason") if isinstance(candidate, dict) else None,
        "usage_metadata": payload.get("usageMetadata") if isinstance(payload.get("usageMetadata"), dict) else {},
    }


async def generate_gemini_json_hard_timeout(
    prompt: dict[str, Any],
    *,
    timeout_seconds: float,
    max_output_tokens: int = 600,
    temperature: float = 0.2,
) -> dict[str, Any]:
    """Run Gemini generation in a child process so a stuck SDK call cannot block a request."""
    if _gemini_rest_available():
        return await asyncio.wait_for(
            asyncio.to_thread(
                _generate_gemini_json_rest_sync,
                prompt,
                timeout_seconds=timeout_seconds,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
            ),
            timeout=max(0.5, timeout_seconds) + 0.5,
        )
    if _vertex_rest_available():
        return await asyncio.wait_for(
            asyncio.to_thread(
                _generate_vertex_json_rest_sync,
                prompt,
                timeout_seconds=timeout_seconds,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
            ),
            timeout=max(0.5, timeout_seconds) + 0.5,
        )
    worker_path = Path(__file__).resolve()
    request = {
        "prompt": prompt,
        "max_output_tokens": max_output_tokens,
        "temperature": temperature,
        "timeout_seconds": timeout_seconds,
    }
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(worker_path),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(worker_path.parent),
        env=os.environ.copy(),
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(json.dumps(request, separators=(",", ":")).encode("utf-8")),
            timeout=max(0.5, timeout_seconds),
        )
    except asyncio.TimeoutError as error:
        process.kill()
        await process.communicate()
        raise TimeoutError(f"Gemini provider exceeded hard timeout of {timeout_seconds:g}s") from error

    if process.returncode != 0:
        detail = (stderr or stdout).decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or f"Gemini worker exited with code {process.returncode}")

    try:
        payload = json.loads(stdout.decode("utf-8"))
    except json.JSONDecodeError as error:
        raise RuntimeError("Gemini worker returned invalid JSON") from error

    if not payload.get("ok"):
        raise RuntimeError(str(payload.get("error") or "Gemini worker failed"))
    return payload


def _main() -> int:
    from env_bootstrap import load_backend_env
    from gemini_provider import get_gemini_client, get_gemini_model

    load_backend_env()
    request = json.loads(sys.stdin.read() or "{}")
    timeout_seconds = float(request.get("timeout_seconds") or os.getenv("PARKPULSE_GEMINI_REST_TIMEOUT_SECONDS", "5"))
    prompt_text = json.dumps(request.get("prompt") or {}, separators=(",", ":"), sort_keys=True)
    if _gemini_rest_available():
        payload = _generate_gemini_json_rest_sync(
            request.get("prompt") or {},
            timeout_seconds=timeout_seconds,
            max_output_tokens=int(request.get("max_output_tokens", 600)),
            temperature=float(request.get("temperature", 0.2)),
        )
        print(json.dumps(payload, separators=(",", ":")))
        return 0
    if _vertex_rest_available():
        payload = _generate_vertex_json_rest_sync(
            request.get("prompt") or {},
            timeout_seconds=timeout_seconds,
            max_output_tokens=int(request.get("max_output_tokens", 600)),
            temperature=float(request.get("temperature", 0.2)),
        )
        print(json.dumps(payload, separators=(",", ":")))
        return 0

    from google.genai import types

    model = get_gemini_model()
    response = get_gemini_client().models.generate_content(
        model=model,
        contents=prompt_text,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=float(request.get("temperature", 0.2)),
            max_output_tokens=int(request.get("max_output_tokens", 600)),
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    print(json.dumps({"ok": True, "text": getattr(response, "text", "") or "", "transport": "google_genai_sdk"}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(_main())
    except Exception as error:
        print(json.dumps({"ok": False, "error": str(error)}, separators=(",", ":")), file=sys.stderr)
        raise SystemExit(1)
