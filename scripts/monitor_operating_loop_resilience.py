#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def _now_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _artifact_dir(configured: str | None) -> Path:
    if configured:
        return Path(configured)
    env_path = os.getenv("PARKPULSE_LOOP_RESILIENCE_MONITOR_DIR", "").strip()
    if env_path:
        return Path(env_path)
    return ROOT / "artifacts" / "operating-loop-resilience-monitor"


def _fetch_remote_report(api_url: str, *, write_remote_artifact: bool, timeout_seconds: float) -> dict[str, Any]:
    base = api_url.rstrip("/")
    query = urlencode({"write_artifact": "true" if write_remote_artifact else "false"})
    request = urllib.request.Request(f"{base}/api/gcp/operating-loop-resilience?{query}")
    token = os.getenv("PARKPULSE_MONITOR_BEARER_TOKEN", "").strip()
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Remote operating-loop resilience endpoint did not return a JSON object.")
    return payload


def _local_report() -> dict[str, Any]:
    from operating_loop_resilience import build_operating_loop_resilience_report

    return build_operating_loop_resilience_report(write_artifact=False)


def _write_monitor_artifacts(report: dict[str, Any], *, artifact_dir: Path) -> dict[str, Any]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    run_id = _now_id()
    payload = {
        "monitor_id": f"operating-loop-resilience-{run_id}",
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "report": report,
    }
    run_path = artifact_dir / f"{run_id}.json"
    latest_path = artifact_dir / "latest.json"
    rendered = json.dumps(payload, indent=2, sort_keys=True, default=str)
    run_path.write_text(rendered, encoding="utf-8")
    latest_path.write_text(rendered, encoding="utf-8")
    return {"status": "written", "run_path": str(run_path), "latest_path": str(latest_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Scheduled ParkPulse operating-loop resilience monitor.")
    parser.add_argument("--api-url", default=os.getenv("PARKPULSE_MONITOR_API_URL", "").strip(), help="Optional deployed API base URL.")
    parser.add_argument("--artifact-dir", default=None, help="Directory for timestamped monitor artifacts and latest.json.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on conditional failures, not only critical failures.")
    parser.add_argument("--write-remote-artifact", action="store_true", help="Ask the deployed API to write its own resilience artifact.")
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    args = parser.parse_args()

    try:
        report = (
            _fetch_remote_report(args.api_url, write_remote_artifact=args.write_remote_artifact, timeout_seconds=args.timeout_seconds)
            if args.api_url
            else _local_report()
        )
        monitor_artifact = _write_monitor_artifacts(report, artifact_dir=_artifact_dir(args.artifact_dir))
        output = {
            "status": report.get("status", "unknown"),
            "decision": report.get("decision"),
            "summary": report.get("summary", {}),
            "source": "remote_api" if args.api_url else "local_module",
            "monitor_artifact": monitor_artifact,
        }
        print(json.dumps(output, indent=2, sort_keys=True, default=str))
        if report.get("status") == "failed":
            return 1
        if args.strict and report.get("status") != "passed":
            return 1
        return 0
    except Exception as error:
        failure = {
            "status": "failed",
            "decision": "block_loop_claim",
            "source": "remote_api" if args.api_url else "local_module",
            "reason": str(error)[:500],
        }
        monitor_artifact = _write_monitor_artifacts(failure, artifact_dir=_artifact_dir(args.artifact_dir))
        print(json.dumps({**failure, "monitor_artifact": monitor_artifact}, indent=2, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
