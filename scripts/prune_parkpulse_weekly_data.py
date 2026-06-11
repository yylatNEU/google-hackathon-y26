#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QA_DIR = REPO_ROOT / "output" / "qa"
DEFAULT_CASE_BANK = DEFAULT_QA_DIR / "live-feed-case-bank" / "index.jsonl"
DEFAULT_SUMMARY = DEFAULT_QA_DIR / "live-feed-case-bank" / "summary.json"


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _row_time(row: dict[str, Any]) -> datetime | None:
    for key in ("created_at", "started_at", "closed_at", "captured_at"):
        parsed = _parse_time(row.get(key))
        if parsed:
            return parsed
    artifacts = row.get("source_artifacts", {})
    if isinstance(artifacts, dict):
        for key in ("run_json", "training_dir", "batch_dir"):
            value = artifacts.get(key)
            if not value:
                continue
            path = Path(str(value))
            if not path.is_absolute():
                path = REPO_ROOT / path
            if path.exists():
                return _mtime(path)
    return None


def _rewrite_case_bank(path: Path, summary_path: Path, cutoff: datetime, apply: bool) -> dict[str, Any]:
    rows = _read_jsonl(path)
    kept: list[dict[str, Any]] = []
    pruned: list[dict[str, Any]] = []
    unknown_time: list[dict[str, Any]] = []
    for row in rows:
        row_time = _row_time(row)
        if row_time is None:
            unknown_time.append(row)
            kept.append(row)
        elif row_time >= cutoff:
            kept.append(row)
        else:
            pruned.append(row)
    backup_path = path.with_suffix(path.suffix + f".pre-weekly-prune-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}.bak")
    if apply and pruned:
        shutil.copy2(path, backup_path)
        with path.open("w", encoding="utf-8") as handle:
            for row in kept:
                handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(summary, dict):
                summary["total_case_count"] = len(kept)
                summary["closed_case_count"] = sum(1 for row in kept if row.get("closed_case"))
                summary["reward_candidate_count"] = sum(1 for row in kept if row.get("reward_candidate"))
                summary["weekly_retention"] = {
                    "status": "applied",
                    "retention_days": 7,
                    "pruned_count": len(pruned),
                    "kept_count": len(kept),
                    "backup_path": str(backup_path),
                    "applied_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
                }
                summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return {
        "path": str(path),
        "row_count": len(rows),
        "kept_count": len(kept),
        "pruned_count": len(pruned),
        "unknown_time_count": len(unknown_time),
        "backup_path": str(backup_path) if apply and pruned else None,
    }


def _candidate_paths(root: Path, cutoff: datetime, keep_case_bank: Path) -> list[Path]:
    candidates: list[Path] = []
    if not root.exists():
        return candidates
    keep_parent = keep_case_bank.parent.resolve()
    for path in root.iterdir():
        resolved = path.resolve()
        if resolved == keep_parent:
            continue
        if path.name.startswith("."):
            continue
        try:
            modified = _mtime(path)
        except OSError:
            continue
        if modified < cutoff:
            candidates.append(path)
    return sorted(candidates)


def _delete_paths(paths: list[Path], apply: bool) -> dict[str, Any]:
    total_bytes = 0
    deleted: list[str] = []
    for path in paths:
        if path.is_dir():
            size = sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
        else:
            size = path.stat().st_size
        total_bytes += size
        deleted.append(str(path))
        if apply:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
    return {
        "path_count": len(paths),
        "bytes": total_bytes,
        "mb": round(total_bytes / 1024 / 1024, 2),
        "paths": deleted[:80],
        "truncated_path_list": len(deleted) > 80,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prune ParkPulse QA/timelapse artifacts to a one-week retention window.")
    parser.add_argument("--root", default=str(DEFAULT_QA_DIR), help="QA/timelapse artifact root to prune.")
    parser.add_argument("--case-bank", default=str(DEFAULT_CASE_BANK), help="Compact case-bank JSONL to rewrite by row timestamp.")
    parser.add_argument("--summary", default=str(DEFAULT_SUMMARY), help="Case-bank summary JSON to update after apply.")
    parser.add_argument("--retention-days", type=int, default=7)
    parser.add_argument("--apply", action="store_true", help="Actually delete/rewrite. Without this flag the command is a dry run.")
    args = parser.parse_args()

    cutoff = datetime.now(UTC) - timedelta(days=max(1, args.retention_days))
    root = Path(args.root)
    case_bank = Path(args.case_bank)
    summary = Path(args.summary)
    candidates = _candidate_paths(root, cutoff, case_bank)
    report = {
        "status": "applied" if args.apply else "dry_run",
        "retention_days": max(1, args.retention_days),
        "cutoff": cutoff.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "root": str(root),
        "case_bank": _rewrite_case_bank(case_bank, summary, cutoff, args.apply),
        "artifact_prune": _delete_paths(candidates, args.apply),
        "boundary": "This prunes local QA/timelapse artifacts and rewrites the compact local case-bank only. It does not delete GCP Cloud Storage, BigQuery, Cloud Logging, or MongoDB documents.",
    }
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
