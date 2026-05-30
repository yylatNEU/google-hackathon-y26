from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from latency_diagnostics import latency_acceptance_gate


def _fetch_json(url: str, timeout: float) -> dict[str, Any]:
    with urlopen(url, timeout=timeout) as response:
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    return data if isinstance(data, dict) else {}


def _with_refresh(url: str) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}refresh=true"


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail when ParkPulse latency diagnostics exceed the configured acceptance gate.")
    parser.add_argument("--url", default="http://127.0.0.1:8000/api/park/latency-diagnostics")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--refresh", action="store_true", help="Trigger background dependency probes before reading the final diagnostic sample.")
    parser.add_argument("--wait-seconds", type=float, default=2.0)
    parser.add_argument("--strict", action="store_true", help="Fail on warning-level causes as well as critical blockers.")
    args = parser.parse_args()

    try:
        if args.refresh:
            _fetch_json(_with_refresh(args.url), args.timeout)
            if args.wait_seconds > 0:
                time.sleep(args.wait_seconds)
        diagnostics = _fetch_json(args.url, args.timeout)
    except (OSError, URLError, TimeoutError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "blocked", "reason": "diagnostics_unavailable", "error": str(error)}, indent=2))
        return 2

    gate = latency_acceptance_gate(diagnostics, fail_on_warning=args.strict)
    summary = {
        "status": gate["status"],
        "mode": gate["mode"],
        "top_cause": (diagnostics.get("summary", {}) if isinstance(diagnostics.get("summary"), dict) else {}).get("top_cause", {}),
        "blockers": gate["blockers"],
        "warnings": gate["warnings"],
        "budgets": gate["budgets"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if gate["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
