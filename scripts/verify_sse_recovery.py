#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import ssl
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def request_json(
    base_url: str,
    path: str,
    *,
    token: str,
    context: ssl.SSLContext | None,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: float = 20,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"{base_url.rstrip('/')}{path}", data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return json.loads(response.read().decode("utf-8"))


def read_first_sse_event(
    base_url: str,
    path: str,
    *,
    token: str,
    context: ssl.SSLContext | None,
    timeout: float = 8,
) -> dict[str, Any]:
    headers = {"Accept": "text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"{base_url.rstrip('/')}{path}", headers=headers)
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        event_name = ""
        data_lines: list[str] = []
        while time.perf_counter() - started < timeout:
            raw = response.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())
            elif line == "" and (event_name or data_lines):
                data = json.loads("".join(data_lines)) if data_lines else {}
                return {"event": event_name, "data": data}
    raise RuntimeError(f"No SSE event received from {path}")


def verify_operator(base_url: str, token: str, context: ssl.SSLContext | None) -> dict[str, Any]:
    message = "Food court is down, redirect mobile orders and protect staff breaks."
    query = urllib.parse.urlencode({"message": message, "mode": "auto", "execute": "true"})
    first = read_first_sse_event(base_url, f"/api/park/operator-command/stream?{query}", token=token, context=context)
    recovered = request_json(
        base_url,
        "/api/park/operator-command",
        token=token,
        context=context,
        method="POST",
        payload={"message": message, "mode": "auto", "execute": True},
    )
    receipt_id = recovered.get("run_receipt", {}).get("id")
    receipt = request_json(base_url, f"/api/park/run-receipt/{receipt_id}", token=token, context=context)
    return {
        "stream": "operator-command",
        "first_event": first.get("event"),
        "recovered_status": recovered.get("status"),
        "receipt_id": receipt_id,
        "receipt_status": receipt.get("status"),
        "observability": recovered.get("observability", {}).get("status"),
        "passed": bool(receipt_id and receipt.get("status") == "found" and recovered.get("observability", {}).get("status") == "complete"),
    }


def verify_proactive(base_url: str, token: str, context: ssl.SSLContext | None) -> dict[str, Any]:
    query = urllib.parse.urlencode({"client_run_id": f"sse_recovery_{int(time.time())}"})
    first = read_first_sse_event(base_url, f"/api/park/proactive-run/stream?{query}", token=token, context=context)
    recovered = request_json(
        base_url,
        "/api/park/proactive-run",
        token=token,
        context=context,
        method="POST",
        payload={},
        timeout=30,
    )
    receipt_id = recovered.get("run_receipt", {}).get("id")
    receipt = request_json(base_url, f"/api/park/run-receipt/{receipt_id}", token=token, context=context)
    return {
        "stream": "proactive-run",
        "first_event": first.get("event"),
        "recovered_status": recovered.get("status"),
        "receipt_id": receipt_id,
        "receipt_status": receipt.get("status"),
        "observability": recovered.get("observability", {}).get("status"),
        "passed": bool(receipt_id and receipt.get("status") == "found" and recovered.get("observability", {}).get("status") == "complete"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify ParkPulse SSE interruption recovery through non-streaming receipts.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--bearer-token", default=os.getenv("PARKPULSE_LOAD_BEARER_TOKEN", ""))
    parser.add_argument("--insecure-skip-tls-verify", action="store_true")
    parser.add_argument("--output-json", default="")
    args = parser.parse_args()

    context = ssl._create_unverified_context() if args.insecure_skip_tls_verify else None
    results = [verify_operator(args.base_url, args.bearer_token, context), verify_proactive(args.base_url, args.bearer_token, context)]
    summary = {"base_url": args.base_url, "passed": all(item["passed"] for item in results), "results": results}
    print(json.dumps(summary, indent=2, sort_keys=True))
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return 0 if summary["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
