#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate ParkPulse operating loop sustainability, anti-fragility, and self-improvement gates.")
    parser.add_argument("--no-artifact", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on conditional failures, not only critical failures.")
    args = parser.parse_args()

    from operating_loop_resilience import build_operating_loop_resilience_report

    report = build_operating_loop_resilience_report(write_artifact=not args.no_artifact)
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    if report["status"] == "failed":
        return 1
    if args.strict and report["status"] != "passed":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
