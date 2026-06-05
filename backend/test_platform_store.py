from __future__ import annotations

import sqlite3

import platform_store


def test_safe_migrate_platform_store_creates_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("PARKPULSE_PLATFORM_DB", str(tmp_path / "park_data.db"))
    monkeypatch.setenv("PARKPULSE_REPLAY_DB", str(tmp_path / "park_replay.db"))
    monkeypatch.setenv("PARKPULSE_AUDIT_DB", str(tmp_path / "park_audit.db"))
    monkeypatch.setenv("PARKPULSE_AGENT_TRUST_DB", str(tmp_path / "agent_trust.db"))
    monkeypatch.setenv("PARKPULSE_LEGACY_PLATFORM_DB", str(tmp_path / "legacy_empty.db"))

    legacy = tmp_path / "legacy_empty.db"
    sqlite3.connect(legacy).close()

    result = platform_store.safe_migrate_platform_store(actor="test")

    assert result["ready"] is True
    assert result["source_of_truth"] == "local_sqlite_wal"
    assert result["migration"]["non_destructive"] is True
    assert {row["store_key"] for row in result["registered_stores"]} >= {
        "platform_registry",
        "replay_store",
        "audit_store",
        "agent_trust_store",
        "delivery_outbox",
        "agent_ops_ledger",
        "review_ledger",
        "policy_books",
        "monitor_evidence_snapshot",
        "legacy_repo_park_data_db",
    }
    monitor_record = next(row for row in result["registered_stores"] if row["store_key"] == "monitor_evidence_snapshot")
    assert monitor_record["data_model"] == "derived_snapshot"
    assert monitor_record["source_of_truth"] is False
    policy_record = next(row for row in result["registered_stores"] if row["store_key"] == "policy_books")
    assert policy_record["data_model"] == "document_store"
    assert policy_record["source_of_truth"] is True

    with sqlite3.connect(tmp_path / "park_data.db") as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
        }
        columns = {row[1] for row in conn.execute("PRAGMA table_info(platform_store_registry)")}
    assert {"platform_schema_migrations", "platform_store_registry", "platform_migration_events"} <= tables
    assert {"data_model", "source_of_truth"} <= columns


def test_safe_migrate_platform_store_preserves_non_empty_legacy_db(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("PARKPULSE_PLATFORM_DB", str(tmp_path / "new_platform.db"))
    monkeypatch.setenv("PARKPULSE_LEGACY_PLATFORM_DB", str(tmp_path / "legacy_platform.db"))

    legacy = tmp_path / "legacy_platform.db"
    with sqlite3.connect(legacy) as conn:
        conn.execute("CREATE TABLE legacy_rows (id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO legacy_rows (id) VALUES ('keep-me')")

    result = platform_store.safe_migrate_platform_store(actor="test")
    legacy_record = next(row for row in result["observed_stores"] if row["store_key"] == "legacy_repo_park_data_db")

    assert legacy_record["status"] == "legacy_non_empty_preserved"
    assert legacy_record["metadata"]["safe_migration_action"] == "preserved_without_copy_or_delete"
    with sqlite3.connect(legacy) as conn:
        assert conn.execute("SELECT id FROM legacy_rows").fetchone()[0] == "keep-me"


def test_safe_migrate_platform_store_upgrades_v1_registry_columns(tmp_path, monkeypatch):
    db_path = tmp_path / "park_data.db"
    monkeypatch.setenv("PARKPULSE_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("PARKPULSE_PLATFORM_DB", str(db_path))

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE platform_store_registry (
                store_key TEXT PRIMARY KEY,
                authority TEXT NOT NULL,
                mode TEXT NOT NULL,
                path TEXT NOT NULL,
                data_classification TEXT NOT NULL,
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
        conn.execute(
            """
            INSERT INTO platform_store_registry (
                store_key, authority, mode, path, data_classification, shared_across_instances,
                required_for_core, status, record_count, metadata_json, migrated_at, updated_at
            ) VALUES ('old', 'old_authority', 'sqlite_wal', '/tmp/old.db', 'old_data', 0, 0, 'ready', 0, '{}', '2026-06-05T00:00:00Z', '2026-06-05T00:00:00Z')
            """
        )

    result = platform_store.safe_migrate_platform_store(actor="test")
    old_record = next(row for row in result["registered_stores"] if row["store_key"] == "old")

    assert old_record["data_model"] == "unspecified"
    assert old_record["source_of_truth"] is False
    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(platform_store_registry)")}
    assert {"data_model", "source_of_truth"} <= columns
