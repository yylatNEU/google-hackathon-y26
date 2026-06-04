#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from live_feed_operating_cycle import _append_case_bank  # noqa: E402


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _default_report_paths(root: Path) -> list[Path]:
    candidates = [
        root / "output/qa/live-feed-operating-cycle.json",
        *sorted((root / "output/qa").glob("operating-cycle-batch-*/live-feed-operating-cycle.json")),
    ]
    seen: set[Path] = set()
    paths: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if path.exists() and resolved not in seen:
            paths.append(path)
            seen.add(resolved)
    return paths


def backfill_case_bank(report_paths: list[Path], case_bank_dir: Path) -> dict[str, Any]:
    imported: list[dict[str, Any]] = []
    latest_summary: dict[str, Any] = {}
    for report_path in report_paths:
        report = _read_json(report_path)
        cycles = report.get("cycles", [])
        if not isinstance(cycles, list):
            continue
        result = _append_case_bank(
            [row for row in cycles if isinstance(row, dict)],
            case_bank_dir=case_bank_dir,
            batch_id=report_path.parent.name,
            output_dir=report_path.parent,
        )
        summary = result.get("summary", {}) if isinstance(result.get("summary"), dict) else {}
        latest_summary = summary
        imported.append(
            {
                "report_path": str(report_path),
                "cycle_count": len(cycles),
                "added_count": summary.get("added_count"),
                "duplicate_count": summary.get("duplicate_count"),
                "total_case_count_after": summary.get("total_case_count"),
                "closed_case_count_after": summary.get("closed_case_count"),
                "reward_candidate_count_after": summary.get("reward_candidate_count"),
            }
        )
    return {
        "status": "complete",
        "mode": "live_feed_case_bank_backfill",
        "report_count": len(report_paths),
        "case_bank_dir": str(case_bank_dir),
        "imports": imported,
        "summary": latest_summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill the append-only live-feed case bank from existing operating-cycle reports.")
    parser.add_argument("reports", nargs="*", help="Specific live-feed-operating-cycle.json reports to import.")
    parser.add_argument("--case-bank-dir", default=str(REPO_ROOT / "output/qa/live-feed-case-bank"))
    args = parser.parse_args()
    report_paths = [Path(item) for item in args.reports] if args.reports else _default_report_paths(REPO_ROOT)
    result = backfill_case_bank(report_paths, Path(args.case_bank_dir))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
