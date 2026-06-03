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
        "legacy_repo_park_data_db",
    }

    with sqlite3.connect(tmp_path / "park_data.db") as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
        }
    assert {"platform_schema_migrations", "platform_store_registry", "platform_migration_events"} <= tables


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
