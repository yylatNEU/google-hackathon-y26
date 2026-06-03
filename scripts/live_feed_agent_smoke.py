#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


async def main() -> int:
    import parkpulse_api

    started = time.perf_counter()
    load_results: dict[str, Any] = {}
    for source, loader in [
        ("ride_ops", parkpulse_api.park_live_ride_ops_feed_load),
        ("guest_flow", parkpulse_api.park_live_guest_flow_feed_load),
        ("staffing", parkpulse_api.park_live_staffing_feed_load),
        ("food_ops", parkpulse_api.park_live_food_ops_feed_load),
        ("operator_signal", parkpulse_api.park_live_operator_signal_feed_load),
    ]:
        try:
            load_results[source] = await loader()
        except Exception as error:
            load_results[source] = {"status": "error", "readiness_issues": [f"{type(error).__name__}: {error}"]}

    payload = await asyncio.wait_for(
        parkpulse_api.park_live_feed_agent_run(
            parkpulse_api.LiveFeedAgentRunRequest(
                refresh_stale=False,
                execute=False,
                min_ready_feeds=4,
                require_persisted_events=True,
            )
        ),
        timeout=90,
    )
    live_case = payload.get("live_feed_case", {}) if isinstance(payload.get("live_feed_case"), dict) else {}
    tool_use = payload.get("tool_use_clarity", {}) if isinstance(payload.get("tool_use_clarity"), dict) else {}
    summary = {
        "status": "passed"
        if payload.get("status") == "complete"
        and payload.get("uses_seed_data") is False
        and payload.get("scripted_case") is False
        and int(live_case.get("persisted_event_count") or 0) > 0
        and int(live_case.get("ready_feed_count") or 0) >= 4
        and int(tool_use.get("proposal_count") or 0) > 0
        and (tool_use.get("judge", {}) if isinstance(tool_use.get("judge"), dict) else {}).get("trace_contract_present")
        else "failed",
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "run_status": payload.get("status"),
        "persisted_event_count": live_case.get("persisted_event_count"),
        "ready_feed_count": live_case.get("ready_feed_count"),
        "lead_source": live_case.get("lead_source"),
        "lead_signal_type": live_case.get("lead_signal_type"),
        "proposal_count": tool_use.get("proposal_count"),
        "judge": tool_use.get("judge"),
        "active_departments": (
            (payload.get("agent_orchestration") or payload.get("orchestration") or {})
            .get("department_system", {})
            .get("active_departments", [])
            if isinstance(payload.get("agent_orchestration") or payload.get("orchestration") or {}, dict)
            else []
        ),
        "readiness_issues": payload.get("readiness_issues", []),
    }
    report = {
        "mode": "live_feed_agent_smoke",
        "summary": summary,
        "load_results": load_results,
        "live_feed_case": live_case,
        "tool_use_clarity": tool_use,
    }
    output_path = REPO_ROOT / "output/qa/live-feed-agent-smoke.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"summary": summary, "output_json": str(output_path)}, indent=2, sort_keys=True))
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
