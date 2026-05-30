#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import ssl
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def fetch(base_url: str, path: str, timeout: float, ssl_context: ssl.SSLContext | None) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    started = time.perf_counter()
    try:
        with urlopen(Request(url, headers={"accept": "application/json,text/html"}), timeout=timeout, context=ssl_context) as response:
            body = response.read()
            status = response.status
            headers = dict(response.headers.items())
    except HTTPError as error:
        body = error.read()
        status = error.code
        headers = dict(error.headers.items())
    except URLError as error:
        return {
            "path": path,
            "status": 0,
            "ok": False,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": str(error.reason),
        }

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    text = body.decode("utf-8", errors="replace")
    payload: Any = None
    content_type = headers.get("Content-Type", "").lower()
    looks_like_json = text.lstrip().startswith(("{", "["))
    if "application/json" in content_type or looks_like_json:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = {"parse_error": text[:500]}
    return {
        "path": path,
        "status": status,
        "ok": 200 <= status < 300,
        "elapsed_ms": elapsed_ms,
        "payload": payload,
        "body_preview": None if payload is not None else text[:200],
    }


def require(condition: bool, failures: list[str], message: str) -> None:
    if not condition:
        failures.append(message)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify deployed ParkPulse frontend and monitoring proxy contract.")
    parser.add_argument("--frontend-url", required=True, help="Base URL for the deployed frontend service.")
    parser.add_argument("--timeout", type=float, default=15.0, help="Per-request timeout in seconds.")
    parser.add_argument("--output-json", default="output/qa/frontend-smoke.json", help="Path to write the smoke report.")
    parser.add_argument("--insecure-skip-tls-verify", action="store_true", help="Skip TLS verification for local CA-store issues.")
    args = parser.parse_args()
    ssl_context = ssl._create_unverified_context() if args.insecure_skip_tls_verify else None

    checks = {
        "index": fetch(args.frontend_url, "/", args.timeout, ssl_context),
        "monitor": fetch(args.frontend_url, "/monitor", args.timeout, ssl_context),
        "summary": fetch(args.frontend_url, "/api/park/agent-monitoring", args.timeout, ssl_context),
        "deep": fetch(args.frontend_url, "/api/park/agent-monitoring/deep", args.timeout, ssl_context),
    }

    failures: list[str] = []
    require(checks["index"]["ok"], failures, "frontend / did not return 2xx")
    require(checks["monitor"]["ok"], failures, "frontend /monitor did not return 2xx")

    summary = checks["summary"].get("payload") if isinstance(checks["summary"].get("payload"), dict) else {}
    deep = checks["deep"].get("payload") if isinstance(checks["deep"].get("payload"), dict) else {}
    require(checks["summary"]["ok"], failures, "summary proxy did not return 2xx")
    require(summary.get("entrypoint") == "lazy-main", failures, "summary proxy is not using lazy-main")
    require(summary.get("mode") == "stale_while_revalidate_fast_monitoring", failures, "summary proxy mode changed")
    require("policy_index" not in summary, failures, "summary proxy returned deep policy_index")
    require(checks["deep"]["ok"], failures, "deep proxy did not return 2xx")
    require(deep.get("entrypoint") == "full-runtime", failures, "deep proxy is not using full-runtime")
    require(deep.get("mode") == "deep_monitoring", failures, "deep proxy mode changed")
    require("policy_index" in deep, failures, "deep proxy did not return policy_index")

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
