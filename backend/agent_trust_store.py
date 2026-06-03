from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _runtime_dir() -> Path:
    return Path(os.getenv("PARKPULSE_RUNTIME_DIR", "/tmp/parkpulse"))


def _db_path() -> Path:
    configured = os.getenv("PARKPULSE_AGENT_TRUST_DB")
    if configured:
        return Path(configured).expanduser()
    return _runtime_dir() / "agent_trust.db"


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _from_json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def init_agent_trust_store(default_partners: dict[str, dict[str, Any]] | None = None) -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_partners (
                partner_id TEXT PRIMARY KEY,
                partner_name TEXT NOT NULL,
                contact TEXT NOT NULL DEFAULT '',
                trust_tier TEXT NOT NULL,
                status TEXT NOT NULL,
                allowed_scopes_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS credential_revocations (
                certification_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL DEFAULT '',
                reason TEXT NOT NULL,
                revoked_by TEXT NOT NULL,
                revoked_at TEXT NOT NULL,
                record_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS certification_keys (
                kid TEXT PRIMARY KEY,
                version TEXT NOT NULL,
                alg TEXT NOT NULL,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                activated_at TEXT,
                retired_at TEXT,
                metadata_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trust_audit_events (
                event_id TEXT PRIMARY KEY,
                at TEXT NOT NULL,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                target_id TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        if default_partners:
            for partner in default_partners.values():
                upsert_partner(partner, actor="system_default", audit=False, conn=conn)


def upsert_partner(partner: dict[str, Any], actor: str = "parkpulse_trust_admin", audit: bool = True, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    close = conn is None
    conn = conn or _connect()
    try:
        now = _utc_now()
        partner_id = str(partner.get("partner_id") or "demo_external_partner")
        existing = conn.execute("SELECT created_at FROM agent_partners WHERE partner_id = ?", (partner_id,)).fetchone()
        record = {
            "partner_id": partner_id,
            "partner_name": str(partner.get("partner_name") or partner_id),
            "contact": str(partner.get("contact") or ""),
            "trust_tier": str(partner.get("trust_tier") or "sandbox"),
            "status": str(partner.get("status") or "active"),
            "allowed_scopes": sorted({str(scope) for scope in (partner.get("allowed_scopes") or []) if str(scope).strip()}),
            "created_at": existing["created_at"] if existing else now,
            "updated_at": now,
        }
        conn.execute(
            """
            INSERT INTO agent_partners (partner_id, partner_name, contact, trust_tier, status, allowed_scopes_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(partner_id) DO UPDATE SET
                partner_name = excluded.partner_name,
                contact = excluded.contact,
                trust_tier = excluded.trust_tier,
                status = excluded.status,
                allowed_scopes_json = excluded.allowed_scopes_json,
                updated_at = excluded.updated_at
            """,
            (record["partner_id"], record["partner_name"], record["contact"], record["trust_tier"], record["status"], _json(record["allowed_scopes"]), record["created_at"], record["updated_at"]),
        )
        if audit:
            record_audit_event("partner_upsert", partner_id, record, actor=actor, conn=conn)
        if close:
            conn.commit()
        return record
    finally:
        if close:
            conn.close()


def _partner_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "partner_id": row["partner_id"],
        "partner_name": row["partner_name"],
        "contact": row["contact"],
        "trust_tier": row["trust_tier"],
        "status": row["status"],
        "allowed_scopes": _from_json(row["allowed_scopes_json"], []),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_partner(partner_id: str) -> dict[str, Any] | None:
    init_agent_trust_store()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM agent_partners WHERE partner_id = ?", (partner_id,)).fetchone()
    return _partner_from_row(row) if row else None


def list_partners() -> list[dict[str, Any]]:
    init_agent_trust_store()
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM agent_partners ORDER BY partner_id").fetchall()
    return [_partner_from_row(row) for row in rows]


def record_revocation(record: dict[str, Any], actor: str = "parkpulse_agent_onboarding_authority") -> dict[str, Any]:
    init_agent_trust_store()
    certification_id = str(record.get("certification_id") or "")
    if not certification_id:
        raise ValueError("certification_id is required")
    stored = {
        "certification_id": certification_id,
        "agent_id": str(record.get("agent_id") or ""),
        "reason": str(record.get("reason") or "revoked_by_parkpulse"),
        "revoked_at": str(record.get("revoked_at") or _utc_now()),
        "revoked_by": str(record.get("revoked_by") or actor),
    }
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO credential_revocations (certification_id, agent_id, reason, revoked_by, revoked_at, record_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(certification_id) DO UPDATE SET
                agent_id = excluded.agent_id,
                reason = excluded.reason,
                revoked_by = excluded.revoked_by,
                revoked_at = excluded.revoked_at,
                record_json = excluded.record_json
            """,
            (stored["certification_id"], stored["agent_id"], stored["reason"], stored["revoked_by"], stored["revoked_at"], _json(stored)),
        )
        record_audit_event("credential_revoke", certification_id, stored, actor=actor, conn=conn)
    return stored


def get_revocation(certification_id: str) -> dict[str, Any] | None:
    init_agent_trust_store()
    with _connect() as conn:
        row = conn.execute("SELECT record_json FROM credential_revocations WHERE certification_id = ?", (certification_id,)).fetchone()
    return _from_json(row["record_json"], {}) if row else None


def list_revocations(limit: int = 100) -> list[dict[str, Any]]:
    init_agent_trust_store()
    with _connect() as conn:
        rows = conn.execute("SELECT record_json FROM credential_revocations ORDER BY revoked_at DESC LIMIT ?", (max(1, min(limit, 500)),)).fetchall()
    return [_from_json(row["record_json"], {}) for row in rows]


def record_key(kid: str, version: str, alg: str, mode: str, status: str, metadata: dict[str, Any] | None = None, actor: str = "parkpulse_trust_admin") -> dict[str, Any]:
    init_agent_trust_store()
    now = _utc_now()
    record = {
        "kid": kid,
        "version": version,
        "alg": alg,
        "mode": mode,
        "status": status,
        "created_at": now,
        "activated_at": now if status == "active" else None,
        "retired_at": now if status == "retired" else None,
        "metadata": metadata or {},
    }
    with _connect() as conn:
        if status == "active":
            conn.execute("UPDATE certification_keys SET status = 'retired', retired_at = COALESCE(retired_at, ?) WHERE status = 'active'", (now,))
        existing = conn.execute("SELECT created_at, activated_at FROM certification_keys WHERE kid = ?", (kid,)).fetchone()
        if existing:
            record["created_at"] = existing["created_at"]
            record["activated_at"] = now if status == "active" else existing["activated_at"]
        conn.execute(
            """
            INSERT INTO certification_keys (kid, version, alg, mode, status, created_at, activated_at, retired_at, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(kid) DO UPDATE SET
                version = excluded.version,
                alg = excluded.alg,
                mode = excluded.mode,
                status = excluded.status,
                activated_at = excluded.activated_at,
                retired_at = excluded.retired_at,
                metadata_json = excluded.metadata_json
            """,
            (kid, version, alg, mode, status, record["created_at"], record["activated_at"], record["retired_at"], _json(record["metadata"])),
        )
        record_audit_event("key_record", kid, record, actor=actor, conn=conn)
    return record


def active_key_record() -> dict[str, Any] | None:
    init_agent_trust_store()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM certification_keys WHERE status = 'active' ORDER BY activated_at DESC LIMIT 1").fetchone()
    return _key_from_row(row) if row else None


def get_key_record(kid: str) -> dict[str, Any] | None:
    init_agent_trust_store()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM certification_keys WHERE kid = ?", (kid,)).fetchone()
    return _key_from_row(row) if row else None


def list_key_records() -> list[dict[str, Any]]:
    init_agent_trust_store()
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM certification_keys ORDER BY created_at DESC").fetchall()
    return [_key_from_row(row) for row in rows]


def _key_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "kid": row["kid"],
        "version": row["version"],
        "alg": row["alg"],
        "mode": row["mode"],
        "status": row["status"],
        "created_at": row["created_at"],
        "activated_at": row["activated_at"],
        "retired_at": row["retired_at"],
        "metadata": _from_json(row["metadata_json"], {}),
    }


def record_audit_event(action: str, target_id: str, payload: dict[str, Any], actor: str = "parkpulse_trust_admin", conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    close = conn is None
    conn = conn or _connect()
    try:
        event = {
            "event_id": f"trust_evt_{uuid4().hex[:12]}",
            "at": _utc_now(),
            "actor": actor,
            "action": action,
            "target_id": target_id,
            "payload": payload,
        }
        conn.execute(
            "INSERT INTO trust_audit_events (event_id, at, actor, action, target_id, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            (event["event_id"], event["at"], event["actor"], event["action"], event["target_id"], _json(event["payload"])),
        )
        if close:
            conn.commit()
        return event
    finally:
        if close:
            conn.close()


def list_audit_events(limit: int = 100) -> list[dict[str, Any]]:
    init_agent_trust_store()
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM trust_audit_events ORDER BY at DESC LIMIT ?", (max(1, min(limit, 500)),)).fetchall()
    return [
        {
            "event_id": row["event_id"],
            "at": row["at"],
            "actor": row["actor"],
            "action": row["action"],
            "target_id": row["target_id"],
            "payload": _from_json(row["payload_json"], {}),
        }
        for row in rows
    ]


def trust_store_status() -> dict[str, Any]:
    init_agent_trust_store()
    path = _db_path()
    with _connect() as conn:
        partners = conn.execute("SELECT COUNT(*) AS count FROM agent_partners").fetchone()["count"]
        revocations = conn.execute("SELECT COUNT(*) AS count FROM credential_revocations").fetchone()["count"]
        keys = conn.execute("SELECT COUNT(*) AS count FROM certification_keys").fetchone()["count"]
        audits = conn.execute("SELECT COUNT(*) AS count FROM trust_audit_events").fetchone()["count"]
    return {
        "ready": True,
        "mode": "sqlite_wal",
        "path": str(path),
        "exists": path.exists(),
        "bytes": path.stat().st_size if path.exists() else 0,
        "partners": partners,
        "revocations": revocations,
        "keys": keys,
        "audit_events": audits,
    }
