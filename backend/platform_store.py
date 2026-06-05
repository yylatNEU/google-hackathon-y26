from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


SCHEMA_VERSION = 2
MIGRATION_ID = "20260605_0002_platform_store_data_boundaries"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _runtime_dir() -> Path:
    return Path(os.getenv("PARKPULSE_RUNTIME_DIR", "/tmp/parkpulse"))


def _platform_db_path() -> Path:
    configured = os.getenv("PARKPULSE_PLATFORM_DB")
    if configured:
        return Path(configured).expanduser()
    return _runtime_dir() / "park_data.db"


def _legacy_platform_db_path() -> Path:
    configured = os.getenv("PARKPULSE_LEGACY_PLATFORM_DB")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parent / "park_data.db"


def _connect() -> sqlite3.Connection:
    path = _platform_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _checksum(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sqlite_tables(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        with sqlite3.connect(path) as conn:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
        return [str(row[0]) for row in rows]
    except sqlite3.DatabaseError:
        return []


def _sqlite_count(path: Path, table_names: list[str]) -> int | None:
    if not path.exists():
        return 0
    try:
        total = 0
        with sqlite3.connect(path) as conn:
            for table_name in table_names:
                if table_name not in _sqlite_tables(path):
                    continue
                row = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()
                total += int(row[0] if row else 0)
        return total
    except sqlite3.DatabaseError:
        return None


def _jsonl_count(path: Path) -> int | None:
    if not path.exists():
        return 0
    if os.getenv("PARKPULSE_PLATFORM_STATUS_COUNT_JSONL", "").strip().lower() not in {"1", "true", "yes", "on"}:
        return None
    try:
        with path.open("rb") as file:
            return sum(1 for line in file if line.strip())
    except OSError:
        return None


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    return {str(row[1]) for row in rows}


def _monitor_evidence_snapshot_path() -> Path:
    configured = os.getenv("PARKPULSE_MONITOR_EVIDENCE_SNAPSHOT_PATH")
    if configured:
        return Path(configured).expanduser()
    return Path.cwd() / "output" / "monitor-evidence-limit-40.json"


def _store_record(
    *,
    store_key: str,
    authority: str,
    mode: str,
    path: Path,
    data_classification: str,
    data_model: str,
    source_of_truth: bool,
    shared_across_instances: bool,
    required_for_core: bool,
    status: str,
    record_count: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = _utc_now()
    return {
        "store_key": store_key,
        "authority": authority,
        "mode": mode,
        "path": str(path),
        "data_classification": data_classification,
        "data_model": data_model,
        "source_of_truth": source_of_truth,
        "shared_across_instances": shared_across_instances,
        "required_for_core": required_for_core,
        "status": status,
        "record_count": record_count,
        "metadata": metadata or {},
        "migrated_at": now,
        "updated_at": now,
    }


def _observed_store_records() -> list[dict[str, Any]]:
    runtime_dir = _runtime_dir()
    replay_path = Path(os.getenv("PARKPULSE_REPLAY_DB", runtime_dir / "park_replay.db"))
    audit_path = Path(os.getenv("PARKPULSE_AUDIT_DB", runtime_dir / "park_audit.db"))
    trust_path = Path(os.getenv("PARKPULSE_AGENT_TRUST_DB", runtime_dir / "agent_trust.db"))
    delivery_path = Path(os.getenv("PARKPULSE_DELIVERY_OUTBOX", runtime_dir / "delivery_outbox.jsonl"))
    live_feed_path = Path(os.getenv("PARKPULSE_LIVE_FEED_PATH", runtime_dir / "live_feed_events.jsonl"))
    legacy_path = _legacy_platform_db_path()
    legacy_tables = _sqlite_tables(legacy_path)
    return [
        _store_record(
            store_key="platform_registry",
            authority="core_sqlite_store_registry",
            mode="sqlite_wal",
            path=_platform_db_path(),
            data_classification="platform_metadata",
            data_model="relational_registry",
            source_of_truth=True,
            shared_across_instances=False,
            required_for_core=True,
            status="ready",
            metadata={"schema_version": SCHEMA_VERSION, "migration_id": MIGRATION_ID},
        ),
        _store_record(
            store_key="replay_store",
            authority="transactional_replay_and_action_audit",
            mode="sqlite_wal",
            path=replay_path,
            data_classification="operator_action_replay",
            data_model="relational_event_index",
            source_of_truth=True,
            shared_across_instances=False,
            required_for_core=True,
            status="ready" if replay_path.exists() else "will_initialize_on_first_write",
            record_count=_sqlite_count(replay_path, ["replay_runs", "replay_events"]),
            metadata={"override_env": "PARKPULSE_REPLAY_DB"},
        ),
        _store_record(
            store_key="audit_store",
            authority="policy_audit_findings",
            mode="sqlite_wal",
            path=audit_path,
            data_classification="operational_audit",
            data_model="relational_audit_log",
            source_of_truth=True,
            shared_across_instances=False,
            required_for_core=True,
            status="ready" if audit_path.exists() else "will_initialize_on_first_write",
            record_count=_sqlite_count(audit_path, ["audit_events", "audit_findings"]),
            metadata={"override_env": "PARKPULSE_AUDIT_DB"},
        ),
        _store_record(
            store_key="agent_trust_store",
            authority="agent_partner_trust_and_revocation_registry",
            mode="sqlite_wal",
            path=trust_path,
            data_classification="identity_authority_metadata",
            data_model="relational_identity_registry",
            source_of_truth=True,
            shared_across_instances=False,
            required_for_core=True,
            status="ready" if trust_path.exists() else "will_initialize_on_first_write",
            record_count=_sqlite_count(trust_path, ["agent_partners", "credential_revocations", "certification_keys", "trust_audit_events"]),
            metadata={"override_env": "PARKPULSE_AGENT_TRUST_DB"},
        ),
        _store_record(
            store_key="delivery_outbox",
            authority="append_first_receiver_dispatch_outbox",
            mode="jsonl_durable_outbox",
            path=delivery_path,
            data_classification="receiver_dispatch_receipts",
            data_model="append_event_log",
            source_of_truth=True,
            shared_across_instances=False,
            required_for_core=True,
            status="ready" if delivery_path.parent.exists() else "directory_missing",
            record_count=_jsonl_count(delivery_path),
            metadata={"override_env": "PARKPULSE_DELIVERY_OUTBOX"},
        ),
        _store_record(
            store_key="live_feed_events",
            authority="local_live_feed_event_buffer",
            mode="jsonl_or_mongodb",
            path=live_feed_path,
            data_classification="observed_operational_signals",
            data_model="event_log",
            source_of_truth=True,
            shared_across_instances=os.getenv("PARKPULSE_LIVE_FEED_STORAGE", "").strip().lower() in {"mongo", "mongodb"},
            required_for_core=False,
            status="mongodb_configured" if os.getenv("PARKPULSE_LIVE_FEED_STORAGE", "").strip().lower() in {"mongo", "mongodb"} else "local_jsonl",
            record_count=_jsonl_count(live_feed_path),
            metadata={"override_env": "PARKPULSE_LIVE_FEED_STORAGE"},
        ),
        _store_record(
            store_key="monitor_evidence_snapshot",
            authority="derived_monitor_evidence_graph_cache",
            mode="json_snapshot_cache",
            path=_monitor_evidence_snapshot_path(),
            data_classification="derived_case_trace_review_policy_graph",
            data_model="derived_snapshot",
            source_of_truth=False,
            shared_across_instances=False,
            required_for_core=False,
            status="ready" if _monitor_evidence_snapshot_path().exists() else "will_initialize_on_first_read",
            record_count=None,
            metadata={
                "override_env": "PARKPULSE_MONITOR_EVIDENCE_SNAPSHOT_PATH",
                "derived_from": ["agent_ops_ledger", "review_ledger", "live_feed_events", "policy_books", "case_index"],
                "cache_invalidation": "source_watermark_fingerprint",
                "production_target": "shared_mongodb_or_redis_snapshot",
            },
        ),
        _store_record(
            store_key="agent_ops_ledger",
            authority="agent_run_receipt_and_eval_ledger",
            mode="jsonl_receipt_ledger",
            path=Path(os.getenv("PARKPULSE_AGENT_OPS_LEDGER") or runtime_dir / "agent_ops_ledger.jsonl"),
            data_classification="agent_decision_trace_receipts",
            data_model="append_event_log",
            source_of_truth=True,
            shared_across_instances=False,
            required_for_core=False,
            status="ready" if Path(os.getenv("PARKPULSE_AGENT_OPS_LEDGER") or runtime_dir / "agent_ops_ledger.jsonl").exists() else "will_initialize_on_first_write",
            record_count=_jsonl_count(Path(os.getenv("PARKPULSE_AGENT_OPS_LEDGER") or runtime_dir / "agent_ops_ledger.jsonl")),
            metadata={"override_env": "PARKPULSE_AGENT_OPS_LEDGER"},
        ),
        _store_record(
            store_key="review_ledger",
            authority="human_review_training_ledger",
            mode="jsonl_or_mongodb",
            path=Path(os.getenv("PARKPULSE_REVIEW_LEDGER_LOG_PATH") or runtime_dir / "review_ledger.jsonl"),
            data_classification="human_review_sessions_and_dispositions",
            data_model="event_log",
            source_of_truth=True,
            shared_across_instances=os.getenv("PARKPULSE_LIVE_FEED_STORAGE", "").strip().lower() in {"mongo", "mongodb"},
            required_for_core=False,
            status="mongodb_configured" if os.getenv("PARKPULSE_LIVE_FEED_STORAGE", "").strip().lower() in {"mongo", "mongodb"} else "local_jsonl",
            record_count=_jsonl_count(Path(os.getenv("PARKPULSE_REVIEW_LEDGER_LOG_PATH") or runtime_dir / "review_ledger.jsonl")),
            metadata={"override_env": "PARKPULSE_REVIEW_LEDGER_LOG_PATH"},
        ),
        _store_record(
            store_key="policy_books",
            authority="policy_doctrine_source_files",
            mode="versioned_json_documents",
            path=Path(__file__).resolve().parent / "policy_books",
            data_classification="policy_doctrine",
            data_model="document_store",
            source_of_truth=True,
            shared_across_instances=True,
            required_for_core=True,
            status="ready" if (Path(__file__).resolve().parent / "policy_books").exists() else "missing",
            record_count=len(list((Path(__file__).resolve().parent / "policy_books").glob("*.json"))) if (Path(__file__).resolve().parent / "policy_books").exists() else 0,
            metadata={"legacy_policy_book": str(Path(__file__).resolve().parent / "policy_book.json")},
        ),
        _store_record(
            store_key="legacy_repo_park_data_db",
            authority="legacy_artifact_not_current_source_of_truth",
            mode="sqlite_legacy",
            path=legacy_path,
            data_classification="legacy_platform_database",
            data_model="legacy_relational_database",
            source_of_truth=False,
            shared_across_instances=False,
            required_for_core=False,
            status="legacy_empty" if legacy_path.exists() and not legacy_tables else "not_present" if not legacy_path.exists() else "legacy_non_empty_preserved",
            record_count=_sqlite_count(legacy_path, legacy_tables),
            metadata={"tables": legacy_tables, "safe_migration_action": "preserved_without_copy_or_delete"},
        ),
    ]


def init_platform_store() -> dict[str, Any]:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS platform_schema_migrations (
                migration_id TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL,
                checksum TEXT NOT NULL,
                description TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS platform_store_registry (
                store_key TEXT PRIMARY KEY,
                authority TEXT NOT NULL,
                mode TEXT NOT NULL,
                path TEXT NOT NULL,
                data_classification TEXT NOT NULL,
                data_model TEXT NOT NULL DEFAULT 'unspecified',
                source_of_truth INTEGER NOT NULL DEFAULT 0,
                shared_across_instances INTEGER NOT NULL,
                required_for_core INTEGER NOT NULL,
                status TEXT NOT NULL,
                record_count INTEGER,
                metadata_json TEXT NOT NULL,
                migrated_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        columns = _table_columns(conn, "platform_store_registry")
        if "data_model" not in columns:
            conn.execute("ALTER TABLE platform_store_registry ADD COLUMN data_model TEXT NOT NULL DEFAULT 'unspecified'")
        if "source_of_truth" not in columns:
            conn.execute("ALTER TABLE platform_store_registry ADD COLUMN source_of_truth INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS platform_migration_events (
                event_id TEXT PRIMARY KEY,
                at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                status TEXT NOT NULL,
                detail_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO platform_schema_migrations (migration_id, applied_at, checksum, description)
            VALUES (?, ?, ?, ?)
            """,
            (
                MIGRATION_ID,
                _utc_now(),
                _checksum("platform_store_registry:v2:data_boundaries"),
                "Add explicit data model and source-of-truth boundaries to the platform store registry.",
            ),
        )
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return {"status": "ok", "mode": "sqlite_wal", "path": str(_platform_db_path()), "schema_version": SCHEMA_VERSION}


def _upsert_store_record(conn: sqlite3.Connection, record: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO platform_store_registry (
            store_key, authority, mode, path, data_classification, data_model, source_of_truth, shared_across_instances,
            required_for_core, status, record_count, metadata_json, migrated_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(store_key) DO UPDATE SET
            authority = excluded.authority,
            mode = excluded.mode,
            path = excluded.path,
            data_classification = excluded.data_classification,
            data_model = excluded.data_model,
            source_of_truth = excluded.source_of_truth,
            shared_across_instances = excluded.shared_across_instances,
            required_for_core = excluded.required_for_core,
            status = excluded.status,
            record_count = excluded.record_count,
            metadata_json = excluded.metadata_json,
            updated_at = excluded.updated_at
        """,
        (
            record["store_key"],
            record["authority"],
            record["mode"],
            record["path"],
            record["data_classification"],
            record["data_model"],
            1 if record["source_of_truth"] else 0,
            1 if record["shared_across_instances"] else 0,
            1 if record["required_for_core"] else 0,
            record["status"],
            record["record_count"],
            _json(record["metadata"]),
            record["migrated_at"],
            record["updated_at"],
        ),
    )


def safe_migrate_platform_store(*, actor: str = "system") -> dict[str, Any]:
    init_platform_store()
    records = _observed_store_records()
    event = {
        "event_id": f"platform_migration_{uuid4().hex[:12]}",
        "at": _utc_now(),
        "event_type": "safe_platform_store_registry_sync",
        "status": "applied",
        "actor": actor,
        "non_destructive": True,
        "store_count": len(records),
    }
    with _connect() as conn:
        for record in records:
            _upsert_store_record(conn, record)
        conn.execute(
            """
            INSERT INTO platform_migration_events (event_id, at, event_type, status, detail_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (event["event_id"], event["at"], event["event_type"], event["status"], _json(event)),
        )
    return {**platform_store_status(), "migration": event}


def _registry_rows() -> list[dict[str, Any]]:
    init_platform_store()
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM platform_store_registry ORDER BY required_for_core DESC, store_key").fetchall()
    records: list[dict[str, Any]] = []
    for row in rows:
        records.append(
            {
                "store_key": row["store_key"],
                "authority": row["authority"],
                "mode": row["mode"],
                "path": row["path"],
                "data_classification": row["data_classification"],
                "data_model": row["data_model"],
                "source_of_truth": bool(row["source_of_truth"]),
                "shared_across_instances": bool(row["shared_across_instances"]),
                "required_for_core": bool(row["required_for_core"]),
                "status": row["status"],
                "record_count": row["record_count"],
                "metadata": json.loads(row["metadata_json"] or "{}"),
                "migrated_at": row["migrated_at"],
                "updated_at": row["updated_at"],
            }
        )
    return records


def platform_store_status() -> dict[str, Any]:
    try:
        init_status = init_platform_store()
        registered = _registry_rows()
        observed = _observed_store_records()
        required = [record for record in observed if record["required_for_core"]]
        readiness_issues = [f"{record['store_key']} status is {record['status']}" for record in required if record["status"] == "directory_missing"]
        return {
            "status": "ok" if not readiness_issues else "degraded",
            "mode": "sqlite_platform_registry",
            "source_of_truth": "local_sqlite_wal",
            "path": init_status["path"],
            "schema_version": SCHEMA_VERSION,
            "ready": not readiness_issues,
            "non_destructive": True,
            "authority_boundary": "SQLite owns local transactional app authority. MongoDB/GCP remain optional operational memory and analytics integrations.",
            "registered_store_count": len(registered),
            "observed_store_count": len(observed),
            "registered_stores": registered,
            "observed_stores": observed,
            "readiness_issues": readiness_issues,
        }
    except Exception as error:
        return {
            "status": "error",
            "mode": "sqlite_platform_registry",
            "source_of_truth": "local_sqlite_wal",
            "path": str(_platform_db_path()),
            "ready": False,
            "non_destructive": True,
            "readiness_issues": [str(error)[:300]],
        }
