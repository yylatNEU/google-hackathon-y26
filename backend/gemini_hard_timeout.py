from __future__ import annotations

import asyncio
import json
import os
import sys
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError
from pathlib import Path
from typing import Any
from urllib.parse import quote


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


async def generate_gemini_json_hard_timeout(
    prompt: dict[str, Any],
    *,
    timeout_seconds: float,
    max_output_tokens: int = 600,
    temperature: float = 0.2,
) -> dict[str, Any]:
    """Run Gemini generation in a child process so a stuck SDK call cannot block a request."""
    worker_path = Path(__file__).resolve()
    request = {
        "prompt": prompt,
        "max_output_tokens": max_output_tokens,
        "temperature": temperature,
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
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    prompt_text = json.dumps(request.get("prompt") or {}, separators=(",", ":"), sort_keys=True)
    timeout_seconds = float(os.getenv("PARKPULSE_GEMINI_REST_TIMEOUT_SECONDS", "5"))
    model = os.getenv("PARKPULSE_FAST_GEMINI_MODEL") or get_gemini_model()
    if api_key and not _truthy(os.getenv("GOOGLE_GENAI_USE_VERTEXAI")) and not _truthy(os.getenv("PARKPULSE_DISABLE_GEMINI_REST_FAST_PATH")):
        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{quote(model, safe='')}:generateContent?key={quote(api_key, safe='')}"
        )
        body = json.dumps(
            {
                "contents": [{"role": "user", "parts": [{"text": prompt_text}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "temperature": float(request.get("temperature", 0.2)),
                    "maxOutputTokens": int(request.get("max_output_tokens", 600)),
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
            with urllib_request.urlopen(http_request, timeout=timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Gemini REST HTTP {error.code}: {detail[:500]}") from error
        except URLError as error:
            raise RuntimeError(f"Gemini REST request failed: {error}") from error
        parts = payload.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        text = "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict))
        print(json.dumps({"ok": True, "text": text, "transport": "gemini_rest_api_key"}, separators=(",", ":")))
        return 0

    from google.genai import types

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
