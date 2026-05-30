from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from reliability import call_with_retries


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _db_path() -> Path:
    configured = os.getenv("PARKPULSE_REPLAY_DB")
    if configured:
        return Path(configured)
    return _runtime_dir() / "park_replay.db"


def _backup_dir() -> Path:
    configured = os.getenv("PARKPULSE_DB_BACKUP_DIR")
    if configured:
        return Path(configured)
    return _runtime_dir() / "db_backups"


def _runtime_dir() -> Path:
    return Path(os.getenv("PARKPULSE_RUNTIME_DIR", "/tmp/parkpulse"))


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:32] or "seed"


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_replay_store() -> None:
    with call_with_retries("sqlite.replay_store.connect", _connect) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS replay_runs (
                run_id TEXT PRIMARY KEY,
                seed TEXT NOT NULL,
                scenario_key TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS replay_events (
                run_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                at TEXT NOT NULL,
                kind TEXT NOT NULL,
                label TEXT NOT NULL,
                event_json TEXT NOT NULL,
                PRIMARY KEY (run_id, event_id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_replay_events_run_sequence ON replay_events (run_id, sequence DESC)")


def backup_replay_store() -> dict[str, Any]:
    init_replay_store()
    backup_dir = _backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"park_replay-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.db"

    def copy_db() -> None:
        with _connect() as source, sqlite3.connect(backup_path) as target:
            source.backup(target)

    call_with_retries("sqlite.replay_store.backup", copy_db)
    return {
        "status": "ok",
        "source": str(_db_path()),
        "backup": str(backup_path),
        "bytes": backup_path.stat().st_size,
        "created_at": _utc_now(),
    }


def replay_store_status() -> dict[str, Any]:
    path = _db_path()
    backups = sorted(_backup_dir().glob("park_replay-*.db"), key=lambda item: item.stat().st_mtime, reverse=True)
    try:
        init_replay_store()
        with _connect() as conn:
            runs = conn.execute("SELECT COUNT(*) AS count FROM replay_runs").fetchone()
            events = conn.execute("SELECT COUNT(*) AS count FROM replay_events").fetchone()
        ready = True
        error = None
    except Exception as exc:
        ready = False
        error = str(exc)[:300]
        runs = events = {"count": 0}
    return {
        "ready": ready,
        "mode": "sqlite_wal",
        "path": str(path),
        "exists": path.exists(),
        "bytes": path.stat().st_size if path.exists() else 0,
        "runs": int(runs["count"] if runs else 0),
        "events": int(events["count"] if events else 0),
        "backup_dir": str(_backup_dir()),
        "latest_backup": str(backups[0]) if backups else None,
        "backup_count": len(backups),
        "error": error,
    }


def create_replay_run(seed: str | None, scenario_key: str) -> dict[str, Any]:
    init_replay_store()
    clean_seed = seed or "demo"
    created_at = _utc_now()
    run_id = f"PP-RUN-{_slug(clean_seed)}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}-{uuid4().hex[:6]}"

    def write_run() -> None:
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO replay_runs (run_id, seed, scenario_key, created_at, updated_at, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (run_id, clean_seed, scenario_key, created_at, created_at, "active"),
            )

    call_with_retries("sqlite.replay_runs.write", write_run)
    return {
        "run_id": run_id,
        "seed": clean_seed,
        "scenario_key": scenario_key,
        "created_at": created_at,
        "updated_at": created_at,
        "status": "active",
        "persistent": True,
    }


def append_replay_event(run_id: str, event: dict[str, Any]) -> None:
    if not run_id:
        return
    init_replay_store()

    def write_event() -> None:
        with _connect() as conn:
            row = conn.execute("SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM replay_events WHERE run_id = ?", (run_id,)).fetchone()
            sequence = int(row["next_sequence"] if row else 1)
            conn.execute(
                """
                INSERT OR REPLACE INTO replay_events (run_id, event_id, sequence, at, kind, label, event_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    str(event.get("id", f"replay-{sequence:04d}")),
                    sequence,
                    str(event.get("at", _utc_now())),
                    str(event.get("kind", "event")),
                    str(event.get("label", "Replay event")),
                    json.dumps(event, separators=(",", ":"), sort_keys=True),
                ),
            )
            conn.execute("UPDATE replay_runs SET updated_at = ? WHERE run_id = ?", (_utc_now(), run_id))

    call_with_retries("sqlite.replay_events.write", write_event)


def get_replay_run(run_id: str) -> dict[str, Any] | None:
    init_replay_store()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM replay_runs WHERE run_id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def list_replay_events(run_id: str, limit: int = 20) -> list[dict[str, Any]]:
    if not run_id:
        return []
    init_replay_store()
    safe_limit = max(1, min(100, int(limit or 20)))
    with _connect() as conn:
        rows = conn.execute(
            "SELECT event_json FROM replay_events WHERE run_id = ? ORDER BY sequence DESC LIMIT ?",
            (run_id, safe_limit),
        ).fetchall()
    events: list[dict[str, Any]] = []
    for row in rows:
        try:
            events.append(json.loads(row["event_json"]))
        except (TypeError, json.JSONDecodeError):
            continue
    return events


def list_replay_runs(limit: int = 20) -> list[dict[str, Any]]:
    init_replay_store()
    safe_limit = max(1, min(100, int(limit or 20)))
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM replay_runs ORDER BY updated_at DESC LIMIT ?",
            (safe_limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def replay_collaboration_context(limit: int = 8) -> dict[str, Any]:
    """Return compact relational state for agent prompts and cross-store joins."""
    safe_limit = max(1, min(25, int(limit or 8)))
    status = replay_store_status()
    if not status.get("ready"):
        return {
            "role": "transactional replay and action audit",
            "mode": status.get("mode", "sqlite_wal"),
            "ready": False,
            "error": status.get("error"),
            "latest_run": None,
            "recent_events": [],
        }

    runs = list_replay_runs(safe_limit)
    latest_run = runs[0] if runs else None
    events = list_replay_events(str(latest_run.get("run_id", "")), safe_limit) if latest_run else []
    compact_events = [
        {
            "event_id": item.get("id"),
            "at": item.get("at"),
            "kind": item.get("kind"),
            "label": item.get("label"),
            "status": (item.get("result", {}) if isinstance(item.get("result"), dict) else {}).get("status"),
        }
        for item in events
        if isinstance(item, dict)
    ]
    return {
        "role": "transactional replay and action audit",
        "mode": status.get("mode", "sqlite_wal"),
        "ready": True,
        "latest_run": latest_run,
        "recent_runs": runs[: min(5, safe_limit)],
        "recent_events": compact_events,
        "join_keys": ["run_id", "event_id", "scenario_key", "decision_id", "outcome_id"],
    }
