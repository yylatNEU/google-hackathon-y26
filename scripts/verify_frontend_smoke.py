#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import ssl
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    import certifi
except Exception:  # pragma: no cover - depends on local Python install
    certifi = None


def fetch(
    base_url: str,
    path: str,
    timeout: float,
    ssl_context: ssl.SSLContext | None,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    started = time.perf_counter()
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request_headers = {"accept": "application/json,text/html", **(headers or {})}
    if body is not None:
        request_headers["content-type"] = "application/json"
    try:
        with urlopen(Request(url, data=body, headers=request_headers, method=method), timeout=timeout, context=ssl_context) as response:
            response_body = response.read()
            status = response.status
            response_headers = dict(response.headers.items())
    except HTTPError as error:
        response_body = error.read()
        status = error.code
        response_headers = dict(error.headers.items())
    except URLError as error:
        return {
            "path": path,
            "method": method,
            "status": 0,
            "ok": False,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": str(error.reason),
        }

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    text = response_body.decode("utf-8", errors="replace")
    payload: Any = None
    content_type = response_headers.get("Content-Type", "").lower()
    looks_like_json = text.lstrip().startswith(("{", "["))
    if "application/json" in content_type or looks_like_json:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = {"parse_error": text[:500]}
    return {
        "path": path,
        "method": method,
        "status": status,
        "ok": 200 <= status < 300,
        "elapsed_ms": elapsed_ms,
        "payload": payload,
        "body_preview": None if payload is not None else text[:200],
    }


def require(condition: bool, failures: list[str], message: str) -> None:
    if not condition:
        failures.append(message)


def ssl_context(skip_tls_verify: bool) -> ssl.SSLContext | None:
    if skip_tls_verify:
        return ssl._create_unverified_context()
    if certifi is not None:
        return ssl.create_default_context(cafile=certifi.where())
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify deployed ParkPulse frontend and monitoring proxy contract.")
    parser.add_argument("--frontend-url", required=True, help="Base URL for the deployed frontend service.")
    parser.add_argument("--timeout", type=float, default=15.0, help="Per-request timeout in seconds.")
    parser.add_argument("--output-json", default="output/qa/frontend-smoke.json", help="Path to write the smoke report.")
    parser.add_argument("--insecure-skip-tls-verify", action="store_true", help="Skip TLS verification for local CA-store issues.")
    parser.add_argument("--include-deep-monitoring", action="store_true", help="Also call /api/park/agent-monitoring/deep during frontend smoke.")
    parser.add_argument("--strict-deep-monitoring", action="store_true", help="Require /api/park/agent-monitoring/deep to load full runtime policy_index.")
    args = parser.parse_args()
    context = ssl_context(args.insecure_skip_tls_verify)

    check_specs: dict[str, dict[str, Any]] = {
        "index": {"path": "/"},
        "ops_agent": {"path": "/ops-agent"},
        "monitor": {"path": "/monitor"},
        "summary": {"path": "/api/park/agent-monitoring"},
        "copilot": {
            "path": "/api/park/copilot-chat",
            "method": "POST",
            "headers": {"x-parkpulse-role": "ops_team"},
            "payload": {
                "message": "What is the biggest park risk right now?",
                "mode": "auto",
                "intent": "answer",
                "history": [],
            },
        },
    }
    if args.include_deep_monitoring or args.strict_deep_monitoring:
        check_specs["deep"] = {"path": "/api/park/agent-monitoring/deep"}

    checks: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=len(check_specs)) as executor:
        futures = {
            executor.submit(
                fetch,
                args.frontend_url,
                spec["path"],
                args.timeout,
                context,
                method=spec.get("method", "GET"),
                headers=spec.get("headers"),
                payload=spec.get("payload"),
            ): name
            for name, spec in check_specs.items()
        }
        for future in as_completed(futures):
            checks[futures[future]] = future.result()

    failures: list[str] = []
    require(checks["index"]["ok"], failures, "frontend / did not return 2xx")
    require(checks["ops_agent"]["ok"], failures, "frontend /ops-agent did not return 2xx")
    require(checks["monitor"]["ok"], failures, "frontend /monitor did not return 2xx")

    summary = checks["summary"].get("payload") if isinstance(checks["summary"].get("payload"), dict) else {}
    deep = checks.get("deep", {}).get("payload") if isinstance(checks.get("deep", {}).get("payload"), dict) else {}
    require(checks["summary"]["ok"], failures, "summary proxy did not return 2xx")
    require(summary.get("entrypoint") == "lazy-main", failures, "summary proxy is not using lazy-main")
    require(summary.get("mode") == "stale_while_revalidate_fast_monitoring", failures, "summary proxy mode changed")
    require("policy_index" not in summary, failures, "summary proxy returned deep policy_index")
    if "deep" in checks:
        require(checks["deep"]["ok"], failures, "deep proxy did not return 2xx")
    if "deep" in checks and (args.strict_deep_monitoring or deep.get("entrypoint") == "full-runtime"):
        require(deep.get("entrypoint") == "full-runtime", failures, "deep proxy is not using full-runtime")
        require(deep.get("mode") == "deep_monitoring", failures, "deep proxy mode changed")
        require("policy_index" in deep, failures, "deep proxy did not return policy_index")
    copilot = checks["copilot"].get("payload") if isinstance(checks["copilot"].get("payload"), dict) else {}
    require(checks["copilot"]["ok"], failures, "copilot proxy did not return 2xx")
    require(bool(copilot.get("answer") or copilot.get("message")), failures, "copilot proxy did not return an answer")
    require(copilot.get("mutation_applied") is not True, failures, "copilot smoke unexpectedly applied a mutation")

    report = {
        "status": "passed" if not failures else "failed",
        "frontend_url": args.frontend_url,
        "failures": failures,
        "checks": checks,
    }
    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": report["status"],
                "frontend_url": args.frontend_url,
                "failures": failures,
                "checks": {
                    name: {
                        "status": check["status"],
                        "ok": check["ok"],
                        "elapsed_ms": check["elapsed_ms"],
                        "entrypoint": (check.get("payload") or {}).get("entrypoint") if isinstance(check.get("payload"), dict) else None,
                        "mode": (check.get("payload") or {}).get("mode") if isinstance(check.get("payload"), dict) else None,
                    }
                    for name, check in checks.items()
                },
                "output_json": str(output_path),
            },
            indent=2,
        )
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
