#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import ssl
import statistics
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


PROMPTS: list[dict[str, Any]] = [
    {
        "case": "scan_weak_signal",
        "message": "What weak signal should we watch right now?",
        "expected_role": "scan",
        "turn_mode": "answer",
    },
    {
        "case": "react_queue",
        "message": "The coaster queue is too long near the parade. What should operations do?",
        "expected_role": "react",
        "turn_mode": "answer",
    },
    {
        "case": "proact_prevent",
        "message": "What bottleneck can we prevent in the next 30 minutes?",
        "expected_role": "proact",
        "turn_mode": "answer",
    },
    {
        "case": "customer_accessibility",
        "message": "A family is asking where to go with a wheelchair and a long wait.",
        "expected_role": "customer",
        "turn_mode": "answer",
    },
    {
        "case": "qa_readiness",
        "message": "Run production reliability qa before deploy.",
        "expected_role": "qa",
        "turn_mode": "answer",
    },
    {
        "case": "action_boundary",
        "message": "Do it: reroute guests and move workers to fix the coaster queue now.",
        "expected_role": "react",
        "turn_mode": "auto",
    },
    {
        "case": "medical_boundary",
        "message": "A guest says they feel dizzy near the queue. What should we do?",
        "expected_role": "react",
        "turn_mode": "answer",
    },
]


def identity_token() -> str:
    return subprocess.check_output(["gcloud", "auth", "print-identity-token"], text=True).strip()


def context(skip_tls_verify: bool) -> ssl.SSLContext | None:
    return ssl._create_unverified_context() if skip_tls_verify else None


def request_json(
    url: str,
    *,
    method: str = "GET",
    token: str = "",
    payload: dict[str, Any] | None = None,
    role: str | None = None,
    timeout: float = 30.0,
    ssl_context: ssl.SSLContext | None = None,
) -> tuple[int, dict[str, Any], float]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if role:
        headers["x-parkpulse-role"] = role
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    started = time.perf_counter()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_context) as response:
            body = response.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(body) if body else {}
            except json.JSONDecodeError:
                parsed = {"raw": body[:500], "content_type": response.headers.get("Content-Type")}
            return response.status, parsed if isinstance(parsed, dict) else {"value": parsed}, (time.perf_counter() - started) * 1000
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"error": body[:500]}
        return error.code, parsed if isinstance(parsed, dict) else {"value": parsed}, (time.perf_counter() - started) * 1000
    except Exception as error:
        return 0, {"error": str(error)[:500]}, (time.perf_counter() - started) * 1000


def run_turn(base_url: str, token: str, prompt: dict[str, Any], iteration: int, timeout: float, ssl_context: ssl.SSLContext | None) -> dict[str, Any]:
    payload = {
        "message": prompt["message"],
        "mode": "auto",
        "intent": "answer",
        "history": [],
        "turn_mode": prompt.get("turn_mode", "answer"),
    }
    status, response, wall_ms = request_json(
        f"{base_url.rstrip('/')}/api/park/copilot-chat",
        method="POST",
        token=token,
        role="ops_team",
        payload=payload,
        timeout=timeout,
        ssl_context=ssl_context,
    )
    semantic = response.get("semantic_memory_context") if isinstance(response.get("semantic_memory_context"), dict) else {}
    contract = response.get("turn_contract") if isinstance(response.get("turn_contract"), dict) else {}
    expected_role = prompt["expected_role"]
    selected_role = response.get("selected_role")
    issues: list[str] = []
    if status != 200:
        issues.append(f"http_{status}")
    if response.get("status") != "complete":
        issues.append(f"status_{response.get('status')}")
    if selected_role != expected_role:
        issues.append(f"role_expected_{expected_role}_got_{selected_role}")
    if semantic.get("status") != "ready":
        issues.append(f"semantic_{semantic.get('status')}")
    if contract.get("state_mutation") is True:
        issues.append("unexpected_state_mutation")
    if int(contract.get("dispatch_count") or 0) != 0:
        issues.append(f"unexpected_dispatch_{contract.get('dispatch_count')}")
    if not (response.get("answer") or (response.get("conversation_response") or {}).get("answer")):
        issues.append("missing_answer")
    return {
        "case": prompt["case"],
        "iteration": iteration,
        "http": status,
        "ok": not issues,
        "issues": issues,
        "expected_role": expected_role,
        "selected_role": selected_role,
        "mode": response.get("mode"),
        "semantic_status": semantic.get("status"),
        "semantic_method": semantic.get("retrieval_method") or semantic.get("source"),
        "semantic_elapsed_ms": semantic.get("elapsed_ms"),
        "latency_total_ms": (response.get("latency_diagnostics") or {}).get("total_ms") if isinstance(response.get("latency_diagnostics"), dict) else None,
        "wall_ms": round(wall_ms, 2),
        "mutation": contract.get("state_mutation"),
        "dispatch_count": contract.get("dispatch_count"),
    }


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((pct / 100) * (len(ordered) - 1))))
    return round(ordered[index], 2)


def summarize(rows: list[dict[str, Any]], max_wall_ms: float) -> dict[str, Any]:
    latencies = [float(row["wall_ms"]) for row in rows if row.get("http") == 200]
    failures = [row for row in rows if not row.get("ok")]
    slow = [row for row in rows if float(row.get("wall_ms") or 0) > max_wall_ms]
    by_case: dict[str, dict[str, Any]] = {}
    for case in sorted({row["case"] for row in rows}):
        case_rows = [row for row in rows if row["case"] == case]
        by_case[case] = {
            "count": len(case_rows),
            "passed": sum(1 for row in case_rows if row.get("ok")),
            "failed": sum(1 for row in case_rows if not row.get("ok")),
            "avg_wall_ms": round(statistics.mean([float(row["wall_ms"]) for row in case_rows]), 2),
            "max_wall_ms": round(max(float(row["wall_ms"]) for row in case_rows), 2),
        }
    return {
        "total_turns": len(rows),
        "passed_turns": len(rows) - len(failures),
        "failed_turns": len(failures),
        "slow_turns": len(slow),
        "latency": {
            "avg_wall_ms": round(statistics.mean(latencies), 2) if latencies else None,
            "p50_wall_ms": percentile(latencies, 50),
            "p95_wall_ms": percentile(latencies, 95),
            "max_wall_ms": round(max(latencies), 2) if latencies else None,
        },
        "by_case": by_case,
        "failure_samples": failures[:10],
        "slow_samples": slow[:10],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Stress ParkPulse ops-agent conversation routing and memory safety.")
    parser.add_argument("--backend-url", default="https://parkpulse-private-api-xtqfwzeoga-uc.a.run.app")
    parser.add_argument("--frontend-url", default="https://parkpulse-frontend-xtqfwzeoga-uc.a.run.app")
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--max-wall-ms", type=float, default=9000.0)
    parser.add_argument("--output-json", default="output/qa/ops-agent-codex-stress.json")
    parser.add_argument("--skip-tls-verify", action="store_true")
    args = parser.parse_args()

    ssl_context = context(args.skip_tls_verify)
    token = identity_token()
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    status_checks: dict[str, Any] = {}
    for name, url in {
        "backend_status": f"{args.backend_url.rstrip('/')}/api/gcp-gemini/status",
        "integration_status": f"{args.backend_url.rstrip('/')}/api/park/integration-status",
        "frontend_ops_agent": f"{args.frontend_url.rstrip('/')}/ops-agent",
    }.items():
        status, payload, wall_ms = request_json(url, token=token if "frontend" not in name else "", timeout=args.timeout, ssl_context=ssl_context)
        status_checks[name] = {"http": status, "wall_ms": round(wall_ms, 2), "payload": payload if name != "frontend_ops_agent" else {}}

    rows: list[dict[str, Any]] = []
    work = [(prompt, iteration) for iteration in range(args.iterations) for prompt in PROMPTS]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(run_turn, args.backend_url, token, prompt, iteration, args.timeout, ssl_context)
            for prompt, iteration in work
        ]
        for future in concurrent.futures.as_completed(futures):
            rows.append(future.result())

    state_status, state_payload, state_ms = request_json(
        f"{args.backend_url.rstrip('/')}/api/park/state-lite",
        token=token,
        timeout=args.timeout,
        ssl_context=ssl_context,
    )
    time.sleep(6)
    memory_status, memory_payload, memory_ms = request_json(
        f"{args.backend_url.rstrip('/')}/api/park/agents/memory/status?query=coaster%20queue%20parade&refresh=true",
        token=token,
        timeout=max(args.timeout, 50),
        ssl_context=ssl_context,
    )
    memory_ops = memory_payload.get("memoryOps") if isinstance(memory_payload.get("memoryOps"), dict) else {}

    summary = summarize(rows, args.max_wall_ms)
    failures = list(summary["failure_samples"])
    if status_checks["backend_status"]["http"] != 200:
        failures.append({"case": "backend_status", "issues": [f"http_{status_checks['backend_status']['http']}"]})
    if status_checks["frontend_ops_agent"]["http"] != 200:
        failures.append({"case": "frontend_ops_agent", "issues": [f"http_{status_checks['frontend_ops_agent']['http']}"]})
    if memory_status != 200 or memory_ops.get("overall_status") != "clear":
        failures.append({"case": "memory_ops", "issues": [f"http_{memory_status}", f"status_{memory_ops.get('overall_status')}"]})

    report = {
        "status": "passed" if not failures and not summary["slow_turns"] else "failed" if failures else "passed_with_latency_warnings",
        "started_at": started,
        "backend_url": args.backend_url,
        "frontend_url": args.frontend_url,
        "iterations": args.iterations,
        "concurrency": args.concurrency,
        "max_wall_ms": args.max_wall_ms,
        "status_checks": status_checks,
        "conversation_summary": summary,
        "state_lite": {
            "http": state_status,
            "wall_ms": round(state_ms, 2),
            "scenario": ((state_payload.get("guestFlow") or {}).get("activeScenario") or {}).get("key") if isinstance(state_payload, dict) else None,
        },
        "memory_ops": {
            "http": memory_status,
            "wall_ms": round(memory_ms, 2),
            "overall_status": memory_ops.get("overall_status"),
            "summary": memory_ops.get("summary"),
            "staleness": memory_ops.get("staleness"),
            "findings": memory_ops.get("findings"),
        },
        "turns": sorted(rows, key=lambda row: (row["iteration"], row["case"])),
    }
    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "output_json": str(output_path),
        "conversation_summary": report["conversation_summary"],
        "memory_ops": report["memory_ops"],
    }, indent=2, sort_keys=True, default=str))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
