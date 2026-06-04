#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
SCRIPTS_DIR = REPO_ROOT / "scripts"
for path in (BACKEND_DIR, SCRIPTS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from live_feed_operating_cycle import _case_bank_paths, _case_bank_summary, _json_default, _read_case_bank_rows  # noqa: E402
from parkpulse_api import _build_live_feed_outcome_measurement  # noqa: E402


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _has_reward_vector(row: dict[str, Any]) -> bool:
    measurement = row.get("measurement", {}) if isinstance(row.get("measurement"), dict) else {}
    reward_layers = measurement.get("reward_layers", {}) if isinstance(measurement.get("reward_layers"), dict) else {}
    return reward_layers.get("version") == "live_feed_reward_vector_v1" and "operational_reward" in reward_layers


def _source_run_json(row: dict[str, Any]) -> Path | None:
    artifacts = row.get("source_artifacts", {}) if isinstance(row.get("source_artifacts"), dict) else {}
    raw = artifacts.get("run_json")
    if not raw:
        return None
    path = Path(str(raw))
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def _measurement_row(measurement: dict[str, Any]) -> dict[str, Any]:
    reward_layers = measurement.get("reward_layers", {}) if isinstance(measurement.get("reward_layers"), dict) else {}
    controlled_effect_projection = (
        measurement.get("controlled_effect_projection", {})
        if isinstance(measurement.get("controlled_effect_projection"), dict)
        else {}
    )
    return {
        "status": measurement.get("status"),
        "attribution_confidence": measurement.get("attribution_confidence"),
        "reward_value": measurement.get("reward_value"),
        "reward_label": measurement.get("reward_label"),
        "eligible_for_reward": measurement.get("eligible_for_reward"),
        "promotion_eligible": measurement.get("promotion_eligible"),
        "reward_layers": reward_layers,
        "controlled_effect_projection": controlled_effect_projection,
    }


def migrate_case_bank_reward_vectors(
    case_bank_dir: Path,
    *,
    update_run_json: bool,
    dry_run: bool,
    force_recompute: bool,
    min_training_rows: int,
    min_issue_kinds: int,
    min_targets: int,
    max_dominant_issue_ratio: float,
    min_memory_applied_ratio: float,
) -> dict[str, Any]:
    rows = _read_case_bank_rows(case_bank_dir)
    migrated_rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    changed = 0
    now = _now_iso()

    for row in rows:
        if _has_reward_vector(row) and not force_recompute:
            migrated_rows.append(row)
            skipped_rows.append({"case_id": row.get("case_id"), "reason": "already_reward_vector"})
            continue

        run_json = _source_run_json(row)
        if not run_json or not run_json.exists():
            migrated_rows.append(row)
            skipped_rows.append({"case_id": row.get("case_id"), "reason": "missing_run_json", "run_json": str(run_json) if run_json else None})
            continue

        try:
            payload = _read_json(run_json)
            post_action_refresh = payload.get("live_feed_post_action_refresh", {}) if isinstance(payload.get("live_feed_post_action_refresh"), dict) else {}
            measurement = _build_live_feed_outcome_measurement(payload, post_action_refresh)
        except Exception as error:
            migrated_rows.append(row)
            skipped_rows.append({"case_id": row.get("case_id"), "reason": f"{type(error).__name__}: {error}", "run_json": str(run_json)})
            continue

        new_row = dict(row)
        new_row["measurement"] = _measurement_row(measurement)
        new_row["reward_vector_migration"] = {
            "status": "backfilled",
            "backfilled_at": now,
            "source": "saved_live_feed_run_json",
            "run_json": str(run_json),
            "previous_reward_value": (row.get("measurement", {}) if isinstance(row.get("measurement"), dict) else {}).get("reward_value"),
        }
        migrated_rows.append(new_row)
        changed += 1

        if update_run_json and not dry_run:
            payload["live_feed_outcome_measurement"] = measurement
            payload.setdefault("reward_vector_migration", {})
            if isinstance(payload["reward_vector_migration"], dict):
                payload["reward_vector_migration"].update(new_row["reward_vector_migration"])
            run_json.write_text(json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")

    summary = _case_bank_summary(
        migrated_rows,
        added_count=0,
        duplicate_count=0,
        case_bank_dir=case_bank_dir,
        min_training_rows=min_training_rows,
        min_issue_kinds=min_issue_kinds,
        min_targets=min_targets,
        max_dominant_issue_ratio=max_dominant_issue_ratio,
        min_memory_applied_ratio=min_memory_applied_ratio,
    )
    paths = _case_bank_paths(case_bank_dir)
    backup_paths: dict[str, str] = {}
    if changed and not dry_run:
        case_bank_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        for name, path in paths.items():
            if path.exists():
                backup = path.with_name(f"{path.name}.pre-reward-vector-{stamp}.bak")
                shutil.copy2(path, backup)
                backup_paths[name] = str(backup)
        with paths["index"].open("w", encoding="utf-8") as handle:
            for row in migrated_rows:
                handle.write(json.dumps(row, sort_keys=True, default=_json_default) + "\n")
        paths["summary"].write_text(json.dumps(summary, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")

    return {
        "status": "dry_run" if dry_run else "complete",
        "mode": "live_feed_case_bank_reward_vector_migration",
        "case_bank_dir": str(case_bank_dir),
        "row_count": len(rows),
        "migrated_count": changed,
        "skipped_count": len(skipped_rows),
        "update_run_json": update_run_json,
        "force_recompute": force_recompute,
        "backup_paths": backup_paths,
        "summary": summary,
        "skipped_rows": skipped_rows[:25],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill reward-vector measurements for existing live-feed case-bank rows from saved run JSON.")
    parser.add_argument("--case-bank-dir", default=str(REPO_ROOT / "output/qa/live-feed-case-bank"))
    parser.add_argument("--update-run-json", action="store_true", help="Also update each saved live-feed run JSON with the recomputed reward-vector measurement.")
    parser.add_argument("--force-recompute", action="store_true", help="Recompute rows that already have reward vectors.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--min-training-rows", type=int, default=50)
    parser.add_argument("--min-issue-kinds", type=int, default=12)
    parser.add_argument("--min-targets", type=int, default=6)
    parser.add_argument("--max-dominant-issue-ratio", type=float, default=0.3)
    parser.add_argument("--min-memory-applied-ratio", type=float, default=0.45)
    args = parser.parse_args()
    result = migrate_case_bank_reward_vectors(
        Path(args.case_bank_dir),
        update_run_json=args.update_run_json,
        dry_run=args.dry_run,
        force_recompute=args.force_recompute,
        min_training_rows=args.min_training_rows,
        min_issue_kinds=args.min_issue_kinds,
        min_targets=args.min_targets,
        max_dominant_issue_ratio=args.max_dominant_issue_ratio,
        min_memory_applied_ratio=args.min_memory_applied_ratio,
    )
    print(json.dumps(result, indent=2, sort_keys=True, default=_json_default))
    return 0 if result.get("status") in {"complete", "dry_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
