from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

SCENARIOS = ["ride_down", "staff_shortage", "food_spike", "storm_response", "proactive_eventops"]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report the retired ParkPulse AutoDream contract.")
    parser.add_argument("--scenario", action="append", choices=SCENARIOS, help="Retired scenario contract to report. Can be repeated.")
    parser.add_argument("--all-scenarios", action="store_true", help="Report every retired AutoDream scenario contract.")
    parser.add_argument("--max-cases", type=int, default=8, help="Retired compatibility value echoed in the response.")
    parser.add_argument("--preview", action="store_true", help="Compatibility flag; retired AutoDream does not generate or persist learnings.")
    parser.add_argument("--live-analytics", action="store_true", help="Compatibility flag; retired AutoDream does not read or export analytics.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser.parse_args()


def _selected_scenarios(args: argparse.Namespace) -> list[str]:
    if args.all_scenarios:
        return list(SCENARIOS)
    if args.scenario:
        return list(dict.fromkeys(args.scenario))
    return ["proactive_eventops"]


def main() -> int:
    args = _parse_args()
    if not args.live_analytics:
        os.environ["ENABLE_BIGQUERY_ANALYTICS"] = "false"

    from mongo_memory import init_operational_memory
    from park_autodream_agent import autodream_status, run_autodream

    init_operational_memory()
    scenarios = _selected_scenarios(args)
    runs: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for scenario in scenarios:
        try:
            runs.append(run_autodream(scenario, max_cases=args.max_cases, persist=not args.preview))
        except Exception as error:  # pragma: no cover - keeps scheduled runs reporting partial failures
            errors.append({"scenario_key": scenario, "error": str(error)[:500]})

    retired = bool(runs) and all(run.get("status") == "retired" for run in runs)
    payload = {
        "status": "partial_error" if errors else "retired" if retired else "complete",
        "mode": "preview" if args.preview else "persisted",
        "scenarios": scenarios,
        "run_count": len(runs),
        "errors": errors,
        "runs": runs,
        "post_status": autodream_status(12),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"AutoDream {payload['status']} ({payload['mode']}): {len(runs)}/{len(scenarios)} retired scenario contracts")
        for run in runs:
            summary = run.get("summary", {})
            print(
                "- "
                f"{run.get('scenario_key')}: retired, "
                f"{summary.get('learnings_generated', 0)} learnings, prior={summary.get('prior_source')}"
            )
        for error in errors:
            print(f"- {error['scenario_key']}: ERROR {error['error']}")
        status = payload["post_status"].get("summary", {})
        print(
            "Review queue: "
            f"{status.get('pending_review', 0)} pending, "
            f"{status.get('promoted', 0)} promoted, "
            f"{status.get('rejected', 0)} rejected"
        )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
