from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from digital_twin_benchmark import (
    evaluate_benchmark_gate,
    latest_benchmark_report,
    record_benchmark_result,
    run_digital_twin_benchmark,
)
from park_simulation import ParkSimulation


def _load_report(path: str | None) -> dict[str, Any]:
    if not path:
        return latest_benchmark_report()
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run or evaluate the ParkPulse digital twin regression gate.")
    parser.add_argument("--latest", action="store_true", help="Evaluate the latest generated report instead of running a fresh benchmark.")
    parser.add_argument("--report", help="Evaluate a specific report JSON file.")
    parser.add_argument("--seed", default="ci-gate", help="Seed for fresh benchmark runs.")
    parser.add_argument("--scenario-id", default=None, help="Optional scenario id for a narrow gate run.")
    parser.add_argument("--min-readiness", type=int, default=70, help="Minimum average readiness score.")
    parser.add_argument("--max-failed", type=int, default=0, help="Maximum failed episodes allowed.")
    parser.add_argument("--allow-policy-violations", action="store_true", help="Do not fail on blocked selected actions.")
    parser.add_argument("--allow-learned-regression", action="store_true", help="Do not fail on learned rerun regression deltas.")
    args = parser.parse_args()

    if args.latest or args.report:
        report = _load_report(args.report)
    else:
        state = asyncio.run(ParkSimulation().get_state())
        result = run_digital_twin_benchmark(state, scenario_id=args.scenario_id, seed=args.seed)
        result = record_benchmark_result(result)
        report = latest_benchmark_report()

    gate = evaluate_benchmark_gate(
        report,
        min_readiness=args.min_readiness,
        max_failed=args.max_failed,
        fail_on_policy_gate_violation=not args.allow_policy_violations,
        fail_on_learned_regression=not args.allow_learned_regression,
    )
    print(json.dumps({"status": "passed" if gate["passed"] else "failed", "gate": gate, "summary": report.get("summary"), "run_id": report.get("run_id")}, indent=2))
    return 0 if gate["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
