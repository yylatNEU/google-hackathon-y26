#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import random
import ssl
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path


DEFAULT_PATHS = (
    "/api/park/state:8,"
    "/api/park/agent-monitoring:1,"
    "/api/park/integration-status:1"
)


@dataclass(frozen=True)
class WeightedPath:
    path: str
    weight: int


def parse_paths(raw: str) -> list[WeightedPath]:
    paths: list[WeightedPath] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" in item:
            path, weight = item.rsplit(":", 1)
            paths.append(WeightedPath(path.strip(), max(1, int(weight))))
        else:
            paths.append(WeightedPath(item, 1))
    if not paths:
        raise ValueError("At least one path is required.")
    return paths


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((pct / 100) * (len(ordered) - 1))))
    return ordered[index]


def choose_path(paths: list[WeightedPath]) -> str:
    total = sum(item.weight for item in paths)
    pick = random.randint(1, total)
    cursor = 0
    for item in paths:
        cursor += item.weight
        if pick <= cursor:
            return item.path
    return paths[-1].path


def request_once(
    base_url: str,
    path: str,
    timeout: float,
    headers: dict[str, str],
    tls_context: ssl.SSLContext | None,
) -> tuple[bool, float, int, str | None]:
    started = time.perf_counter()
    url = f"{base_url.rstrip('/')}{path}"
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "parkpulse-load-test/1.0", **headers})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=tls_context) as response:
            body = response.read()
            elapsed_ms = (time.perf_counter() - started) * 1000
            ok = 200 <= response.status < 300
            return ok, elapsed_ms, len(body), None if ok else f"http_{response.status}"
    except urllib.error.HTTPError as error:
        elapsed_ms = (time.perf_counter() - started) * 1000
        try:
            error.read()
        except Exception:
            pass
        return False, elapsed_ms, 0, f"http_{error.code}"
    except Exception as error:
        elapsed_ms = (time.perf_counter() - started) * 1000
        reason = getattr(error, "reason", None)
        return False, elapsed_ms, 0, f"{type(error).__name__}:{type(reason).__name__ if reason else 'unknown'}"


def run_worker(
    worker_id: int,
    base_url: str,
    paths: list[WeightedPath],
    deadline: float,
    timeout: float,
    headers: dict[str, str],
    tls_context: ssl.SSLContext | None,
    latencies: list[float],
    errors: dict[str, int],
    byte_count: list[int],
    lock: threading.Lock,
) -> None:
    random.seed(worker_id + int(time.time()))
    while time.perf_counter() < deadline:
        ok, elapsed_ms, response_bytes, error = request_once(base_url, choose_path(paths), timeout, headers, tls_context)
        with lock:
            latencies.append(elapsed_ms)
            byte_count[0] += response_bytes
            if not ok:
                errors[error or "unknown"] = errors.get(error or "unknown", 0) + 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Load test ParkPulse hot polling endpoints.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Backend base URL.")
    parser.add_argument("--duration", type=float, default=30.0, help="Test duration in seconds.")
    parser.add_argument("--concurrency", type=int, default=50, help="Concurrent worker count.")
    parser.add_argument("--timeout", type=float, default=3.0, help="Per-request timeout in seconds.")
    parser.add_argument("--paths", default=DEFAULT_PATHS, help="Comma-separated paths with optional weights, e.g. /a:8,/b:1.")
    parser.add_argument("--target-p95-ms", type=float, default=250.0, help="Fail when p95 latency is above this value.")
    parser.add_argument("--max-error-rate", type=float, default=0.01, help="Fail when error rate exceeds this fraction.")
    parser.add_argument("--bearer-token", default=os.getenv("PARKPULSE_LOAD_BEARER_TOKEN", ""), help="Bearer token for private services.")
    parser.add_argument("--output-json", default="", help="Optional path to write the JSON summary.")
    parser.add_argument("--insecure-skip-tls-verify", action="store_true", help="Skip TLS verification for local smoke runs with a broken Python CA store.")
    args = parser.parse_args()

    paths = parse_paths(args.paths)
    headers = {"Authorization": f"Bearer {args.bearer_token}"} if args.bearer_token else {}
    tls_context = ssl._create_unverified_context() if args.insecure_skip_tls_verify else None
    latencies: list[float] = []
    errors: dict[str, int] = {}
    byte_count = [0]
    lock = threading.Lock()
    started = time.perf_counter()
    deadline = started + max(1.0, args.duration)

    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as executor:
        for worker_id in range(max(1, args.concurrency)):
            executor.submit(
                run_worker,
                worker_id,
                args.base_url,
                paths,
                deadline,
                args.timeout,
                headers,
                tls_context,
                latencies,
                errors,
                byte_count,
                lock,
            )

    elapsed = time.perf_counter() - started
    total = len(latencies)
    error_count = sum(errors.values())
    success_count = total - error_count
    error_rate = error_count / total if total else 1.0
    p95 = percentile(latencies, 95)
    summary = {
        "base_url": args.base_url,
        "duration_seconds": round(elapsed, 2),
        "concurrency": args.concurrency,
        "requests": total,
        "successes": success_count,
        "errors": error_count,
        "error_rate": round(error_rate, 4),
        "requests_per_second": round(total / elapsed, 2) if elapsed else 0,
        "latency_ms": {
            "min": round(min(latencies), 2) if latencies else 0,
            "avg": round(statistics.mean(latencies), 2) if latencies else 0,
            "p50": round(percentile(latencies, 50), 2),
            "p95": round(p95, 2),
            "p99": round(percentile(latencies, 99), 2),
            "max": round(max(latencies), 2) if latencies else 0,
        },
        "bytes": byte_count[0],
        "error_breakdown": errors,
        "targets": {
            "p95_ms": args.target_p95_ms,
            "max_error_rate": args.max_error_rate,
        },
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    if p95 > args.target_p95_ms:
        print(f"FAIL: p95 {p95:.2f} ms exceeded target {args.target_p95_ms:.2f} ms.", file=sys.stderr)
        return 2
    if error_rate > args.max_error_rate:
        print(f"FAIL: error rate {error_rate:.4f} exceeded target {args.max_error_rate:.4f}.", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
