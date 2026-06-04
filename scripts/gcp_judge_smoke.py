#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


async def _run(scenario_key: str, execute: bool, readiness_only: bool) -> dict[str, Any]:
    from gcp_live_readiness import run_gcp_judge_trace_eval_smoke

    if readiness_only:
        return await run_gcp_judge_trace_eval_smoke(scenario_key=scenario_key, execute=execute)

    from parkpulse_api import ParkAgentRunRequest, park_agent_run

    async def run_scenario(key: str, should_execute: bool) -> dict[str, Any]:
        return await park_agent_run(ParkAgentRunRequest(scenario_key=key, execute=should_execute))

    return await run_gcp_judge_trace_eval_smoke(
        scenario_key=scenario_key,
        execute=execute,
        scenario_runner=run_scenario,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a ParkPulse GCP judge trace/eval readiness and smoke proof.")
    parser.add_argument("--scenario-key", default="ride_down")
    parser.add_argument("--execute", action="store_true", help="Execute the selected scenario action instead of previewing it.")
    parser.add_argument("--readiness-only", action="store_true", help="Skip the agent run and only report GCP readiness.")
    parser.add_argument("--strict", action="store_true", help="Fail unless required GCP trace/eval/BigQuery proof is live.")
    parser.add_argument("--blocking-hosted-eval", action="store_true", help="Call Vertex hosted eval inline instead of deferring it.")
    args = parser.parse_args()

    if args.strict:
        import os

        os.environ["PARKPULSE_REQUIRE_STRICT_LIVE_GCP"] = "true"
    if args.blocking_hosted_eval:
        import os

        os.environ["PARKPULSE_HOSTED_EVAL_BLOCKING"] = "true"

    result = asyncio.run(_run(args.scenario_key, args.execute, args.readiness_only))
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    strict_gate = result.get("strict_gate", {}) if isinstance(result.get("strict_gate"), dict) else {}
    if strict_gate.get("required") and not strict_gate.get("passed"):
        return 1
    return 0 if result.get("status") in {"complete", "readiness_only"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
