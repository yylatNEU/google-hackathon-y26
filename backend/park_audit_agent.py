from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from policy_engine import policy_compliance_for_action
from reliability import call_with_retries


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _runtime_dir() -> Path:
    return Path(os.getenv("PARKPULSE_RUNTIME_DIR", "/tmp/parkpulse"))


def _db_path() -> Path:
    configured = os.getenv("PARKPULSE_AUDIT_DB")
    if configured:
        return Path(configured)
    return _runtime_dir() / "park_audit.db"


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_audit_store() -> None:
    with call_with_retries("sqlite.audit_store.connect", _connect) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                event_id TEXT PRIMARY KEY,
                at TEXT NOT NULL,
                source TEXT NOT NULL,
                zone_id TEXT NOT NULL,
                asset_id TEXT NOT NULL,
                signal TEXT NOT NULL,
                severity TEXT NOT NULL,
                abnormality_score INTEGER NOT NULL,
                event_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_findings (
                finding_id TEXT PRIMARY KEY,
                first_seen_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                severity TEXT NOT NULL,
                domain TEXT NOT NULL,
                status TEXT NOT NULL,
                title TEXT NOT NULL,
                finding_json TEXT NOT NULL,
                response_json TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_at ON audit_events (at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_signal ON audit_events (signal, abnormality_score DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_findings_updated ON audit_findings (updated_at DESC)")


def audit_store_status() -> dict[str, Any]:
    path = _db_path()
    try:
        init_audit_store()
        with _connect() as conn:
            event_count = conn.execute("SELECT COUNT(*) AS count FROM audit_events").fetchone()
            finding_count = conn.execute("SELECT COUNT(*) AS count FROM audit_findings").fetchone()
        return {
            "ready": True,
            "mode": "sqlite_wal",
            "path": str(path),
            "exists": path.exists(),
            "bytes": path.stat().st_size if path.exists() else 0,
            "events": int(event_count["count"] if event_count else 0),
            "findings": int(finding_count["count"] if finding_count else 0),
            "error": None,
        }
    except Exception as exc:
        return {
            "ready": False,
            "mode": "sqlite_wal",
            "path": str(path),
            "exists": path.exists(),
            "bytes": path.stat().st_size if path.exists() else 0,
            "events": 0,
            "findings": 0,
            "error": str(exc)[:300],
        }


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _severity_for_score(score: int) -> str:
    if score >= 88:
        return "critical"
    if score >= 70:
        return "warning"
    return "watch"


def record_audit_event(payload: dict[str, Any]) -> dict[str, Any]:
    init_audit_store()
    now = _utc_now()
    event_id = str(payload.get("id") or payload.get("eventId") or f"AUD-EVT-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}-{uuid4().hex[:6]}")
    score = max(0, min(100, _safe_int(payload.get("abnormalityScore", payload.get("score", 70)), 70)))
    event = {
        "id": event_id,
        "at": str(payload.get("at") or payload.get("createdAt") or now),
        "source": str(payload.get("source") or "external_audit_event"),
        "zoneId": str(payload.get("zoneId") or payload.get("zone_id") or "park"),
        "assetId": str(payload.get("assetId") or payload.get("asset_id") or payload.get("zoneId") or "park"),
        "message": str(payload.get("message") or payload.get("text") or "Operational audit event ingested."),
        "signal": str(payload.get("signal") or payload.get("kind") or "manual_audit_signal"),
        "abnormalityScore": score,
        "severity": str(payload.get("severity") or _severity_for_score(score)),
        "correlatedBy": [str(item) for item in payload.get("correlatedBy", payload.get("correlated_by", [])) or []],
        "raw": payload.get("raw", {}),
    }

    def write_event() -> None:
        with _connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO audit_events
                    (event_id, at, source, zone_id, asset_id, signal, severity, abnormality_score, event_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["id"],
                    event["at"],
                    event["source"],
                    event["zoneId"],
                    event["assetId"],
                    event["signal"],
                    event["severity"],
                    event["abnormalityScore"],
                    json.dumps(event, separators=(",", ":"), sort_keys=True),
                ),
            )

    call_with_retries("sqlite.audit_events.write", write_event)
    return event


def list_audit_events(limit: int = 20) -> list[dict[str, Any]]:
    init_audit_store()
    safe_limit = max(1, min(100, int(limit or 20)))
    with _connect() as conn:
        rows = conn.execute(
            "SELECT event_json FROM audit_events ORDER BY at DESC LIMIT ?",
            (safe_limit,),
        ).fetchall()
    return [_json_row(row["event_json"]) for row in rows]


def list_audit_findings(limit: int = 20) -> list[dict[str, Any]]:
    init_audit_store()
    safe_limit = max(1, min(100, int(limit or 20)))
    with _connect() as conn:
        rows = conn.execute(
            "SELECT finding_json, response_json FROM audit_findings ORDER BY updated_at DESC LIMIT ?",
            (safe_limit,),
        ).fetchall()
    findings = []
    for row in rows:
        finding = _json_row(row["finding_json"])
        response = _json_row(row["response_json"]) if row["response_json"] else None
        if response:
            finding["latestResponse"] = response
        findings.append(finding)
    return findings


def _json_row(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _persist_finding(finding: dict[str, Any]) -> None:
    init_audit_store()
    finding_id = str(finding.get("id") or f"AUD-FIND-{uuid4().hex[:8]}")
    now = _utc_now()

    def write_finding() -> None:
        with _connect() as conn:
            existing = conn.execute("SELECT first_seen_at, response_json FROM audit_findings WHERE finding_id = ?", (finding_id,)).fetchone()
            first_seen_at = existing["first_seen_at"] if existing else str(finding.get("detectedAt") or now)
            response_json = existing["response_json"] if existing else None
            conn.execute(
                """
                INSERT OR REPLACE INTO audit_findings
                    (finding_id, first_seen_at, updated_at, severity, domain, status, title, finding_json, response_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    finding_id,
                    first_seen_at,
                    now,
                    str(finding.get("severity", "watch")),
                    str(finding.get("domain", "operations")),
                    str(finding.get("status", "open")),
                    str(finding.get("title", "Audit finding")),
                    json.dumps({**finding, "firstSeenAt": first_seen_at, "updatedAt": now}, separators=(",", ":"), sort_keys=True),
                    response_json,
                ),
            )

    call_with_retries("sqlite.audit_findings.upsert", write_finding)


def record_audit_response(finding_id: str, response: dict[str, Any]) -> None:
    init_audit_store()
    now = _utc_now()

    def write_response() -> None:
        with _connect() as conn:
            row = conn.execute("SELECT finding_json FROM audit_findings WHERE finding_id = ?", (finding_id,)).fetchone()
            finding = _json_row(row["finding_json"]) if row else {"id": finding_id, "title": "Audit response", "severity": "watch", "domain": "operations"}
            finding["status"] = response.get("status", "responded")
            finding["updatedAt"] = now
            conn.execute(
                """
                INSERT OR REPLACE INTO audit_findings
                    (finding_id, first_seen_at, updated_at, severity, domain, status, title, finding_json, response_json)
                VALUES (?, COALESCE((SELECT first_seen_at FROM audit_findings WHERE finding_id = ?), ?), ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    finding_id,
                    finding_id,
                    str(finding.get("firstSeenAt") or now),
                    now,
                    str(finding.get("severity", "watch")),
                    str(finding.get("domain", "operations")),
                    str(finding.get("status", "responded")),
                    str(finding.get("title", "Audit finding")),
                    json.dumps(finding, separators=(",", ":"), sort_keys=True),
                    json.dumps(response, separators=(",", ":"), sort_keys=True),
                ),
            )

    call_with_retries("sqlite.audit_findings.response", write_response)


def _event_to_work_log(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(event.get("id", "")),
        "at": str(event.get("at", ""))[11:16] if "T" in str(event.get("at", "")) else str(event.get("at", ""))[:5],
        "source": str(event.get("source", "external_audit_event")),
        "zoneId": str(event.get("zoneId", "park")),
        "assetId": str(event.get("assetId", "park")),
        "message": str(event.get("message", "Operational audit event ingested.")),
        "signal": str(event.get("signal", "manual_audit_signal")),
        "abnormalityScore": _safe_int(event.get("abnormalityScore"), 0),
        "correlatedBy": [str(item) for item in event.get("correlatedBy", []) or []],
    }


def _event_finding(event: dict[str, Any]) -> dict[str, Any] | None:
    score = _safe_int(event.get("abnormalityScore"), 0)
    if score < 70:
        return None
    signal = str(event.get("signal", "manual_audit_signal"))
    event_id = str(event.get("id", "event"))
    title_by_signal = {
        "ride_dispatch_log": "External ride log confirms abnormal dispatch behavior",
        "schedule_collision": "External schedule event confirms staffing collision",
        "crowd_flow_delta": "External crowd-flow event confirms path pressure",
        "food_backlog": "External POS/inventory event confirms food backlog",
    }
    return {
        "id": f"ANOM-EVENT-{event_id}",
        "severity": _severity_for_score(score),
        "domain": _domain_for_signal(signal),
        "zoneId": str(event.get("zoneId", "park")),
        "title": title_by_signal.get(signal, f"External audit signal: {signal.replace('_', ' ')}"),
        "evidence": [
            str(event.get("message", "External audit event exceeded abnormality threshold.")),
            f"Abnormality score {score} from {event.get('source', 'external source')}.",
        ],
        "detectedAt": str(event.get("at", _utc_now()))[:16],
        "leadTimeMinutes": max(1, min(20, round((100 - score) / 3) + 2)),
        "recommendedAction": _recommendation_for_signal(signal),
        "linkedLogs": [event_id],
        "owner": _owner_for_signal(signal),
        "status": "open",
    }


def _domain_for_signal(signal: str) -> str:
    if "ride" in signal or "dispatch" in signal:
        return "ride_reliability"
    if "schedule" in signal or "staff" in signal:
        return "staff_schedule"
    if "food" in signal or "pos" in signal:
        return "food_inventory"
    if "crowd" in signal or "queue" in signal or "path" in signal:
        return "crowd_flow"
    return "operations"


def _owner_for_signal(signal: str) -> str:
    return {
        "ride_reliability": "Ride Reliability Agent",
        "staff_schedule": "Schedule Audit Agent",
        "food_inventory": "Food Ops Agent",
        "crowd_flow": "Crowd Flow Agent",
    }.get(_domain_for_signal(signal), "Micro-Ops Audit Agent")


def _recommendation_for_signal(signal: str) -> str:
    domain = _domain_for_signal(signal)
    if domain == "ride_reliability":
        return "Pause new queue intake and publish a realistic downtime message while maintenance verifies clearance."
    if domain == "staff_schedule":
        return "Stagger the break window and assign a trained floater before minimum staffing is violated."
    if domain == "food_inventory":
        return "Suppress constrained menu items and redirect new mobile orders to the lower-backlog food location."
    if domain == "crowd_flow":
        return "Split guest flow before the corridor spills into emergency or service access lanes."
    return "Send a worker verification task and hold automation until the abnormal signal is confirmed."


def _merge_unique_by_id(primary: list[dict[str, Any]], secondary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in primary + secondary:
        item_id = str(item.get("id", ""))
        if item_id and item_id in seen:
            continue
        if item_id:
            seen.add(item_id)
        merged.append(item)
    return merged


def build_audit_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    base = state.get("operationsAudit", {}) if isinstance(state.get("operationsAudit"), dict) else {}
    snapshot = json.loads(json.dumps(base)) if base else {
        "auditAgent": {
            "name": "Micro-Ops Audit Agent",
            "status": "stable",
            "lastScanAt": _utc_now()[11:16],
            "lookaheadMinutes": 30,
            "confidence": 0.78,
            "method": "Correlates work logs, shift schedules, ride telemetry, queue deltas, POS/inventory, weather, and incident readiness.",
        },
        "summary": {},
        "workLogs": [],
        "schedule": [],
        "anomalies": [],
        "reactionTimeline": [],
    }

    events = list_audit_events(12)
    event_logs = [_event_to_work_log(event) for event in events]
    event_findings = [finding for event in events if (finding := _event_finding(event))]
    anomalies = _merge_unique_by_id(event_findings, snapshot.get("anomalies", []))
    for finding in anomalies:
        _persist_finding(finding)

    persisted_findings = list_audit_findings(20)
    anomalies = _merge_unique_by_id(persisted_findings, anomalies)
    work_logs = _merge_unique_by_id(event_logs, snapshot.get("workLogs", []))
    critical_count = sum(1 for item in anomalies if item.get("severity") == "critical")
    watch_count = sum(1 for item in anomalies if item.get("severity") in {"warning", "watch"})
    schedule = snapshot.get("schedule", []) if isinstance(snapshot.get("schedule"), list) else []
    earliest = min([_safe_int(item.get("leadTimeMinutes"), 99) for item in anomalies] or [snapshot.get("summary", {}).get("earliestReactionMinutes", 0) or 0])
    schedule_risk = max(
        [_safe_int(item.get("risk"), 0) for item in schedule]
        + [_safe_int(item.get("abnormalityScore"), 0) for item in work_logs]
        + [_safe_int((snapshot.get("summary", {}) or {}).get("scheduleRiskPct"), 0)]
    )

    audit_agent = snapshot.get("auditAgent", {}) if isinstance(snapshot.get("auditAgent"), dict) else {}
    audit_agent["status"] = "critical" if critical_count else "watch" if watch_count else "stable"
    audit_agent["lastScanAt"] = _utc_now()[11:16]
    audit_agent["persistent"] = True
    snapshot["auditAgent"] = audit_agent
    snapshot["summary"] = {
        **(snapshot.get("summary", {}) if isinstance(snapshot.get("summary"), dict) else {}),
        "criticalAnomalies": critical_count,
        "watchItems": watch_count,
        "earliestReactionMinutes": earliest,
        "scheduleRiskPct": schedule_risk,
        "openWorkLogs": len(work_logs),
        "scheduleItems": len(schedule),
        "ingestedEvents": len(events),
        "persistedFindings": len(persisted_findings),
    }
    snapshot["workLogs"] = work_logs[:8]
    snapshot["anomalies"] = anomalies[:8]
    snapshot["store"] = audit_store_status()
    return snapshot


def build_audit_action_candidate(audit: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    anomalies = audit.get("anomalies", []) if isinstance(audit.get("anomalies"), list) else []
    top = _top_anomaly(anomalies)
    scenario = state.get("guestFlow", {}).get("activeScenario", {}) if isinstance(state.get("guestFlow"), dict) else {}
    if not top:
        return {
            "mode": "audit_action_candidate",
            "status": "noop",
            "finding": None,
            "selected_action": {},
            "recommended_actions": [],
            "reason": "No open audit anomaly is available.",
        }

    domain = str(top.get("domain", "operations"))
    selected = _candidate_for_domain(domain, top)
    recommended = [selected]
    if domain != "crowd_flow":
        recommended.append(_candidate_for_domain("crowd_flow", top))
    if domain != "staff_schedule":
        recommended.append(_candidate_for_domain("staff_schedule", top))

    return {
        "mode": "audit_action_candidate",
        "status": "ready",
        "created_at": _utc_now(),
        "scope": "parkpulse_operations_only",
        "domain": "amusement_park_operations",
        "scenario": scenario,
        "finding": top,
        "selected_action": selected,
        "recommended_actions": recommended[:3],
        "confidence": 0.88 if top.get("severity") == "critical" else 0.78,
        "reason": f"{top.get('owner', 'Audit agent')} selected response for {top.get('title', 'audit finding')}.",
    }


def _top_anomaly(anomalies: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not anomalies:
        return None
    severity_weight = {"critical": 3, "warning": 2, "watch": 1}
    return max(
        anomalies,
        key=lambda item: (
            severity_weight.get(str(item.get("severity")), 0),
            100 - _safe_int(item.get("leadTimeMinutes"), 99),
            1 if item.get("status") == "open" else 0,
        ),
    )


def _candidate_for_domain(domain: str, finding: dict[str, Any]) -> dict[str, Any]:
    finding_id = str(finding.get("id", "audit_finding"))
    if domain == "ride_reliability":
        return _action(f"audit-{finding_id}-ride", "Pause queue intake and reroute from audited ride anomaly", "Ride Ops", 5, finding, "ride", "reroute")
    if domain == "staff_schedule":
        return _action(f"audit-{finding_id}-staff", "Stagger break block and redeploy trained floater", "Staffing", 8, finding, "staff", "redeploy")
    if domain == "food_inventory":
        return _action(f"audit-{finding_id}-food", "Suppress constrained food items and redirect demand", "Food Ops", 4, finding, "food", "suppress_item")
    if domain == "incident_readiness":
        return _action(f"audit-{finding_id}-hvac", "Protect shelter HVAC and emergency access", "Safety", 5, finding, "energy", "protect_hvac")
    return _action(f"audit-{finding_id}-traffic", "Split guests away from audited crowd-flow pressure", "Guest Flow", 6, finding, "traffic", "redirect_food")


def _action(
    action_id: str,
    title: str,
    owner: str,
    deadline_minutes: int,
    finding: dict[str, Any],
    target: str,
    action: str,
) -> dict[str, Any]:
    return {
        "action_id": action_id,
        "title": title,
        "owner": owner,
        "deadline_minutes": deadline_minutes,
        "expected_impact": str(finding.get("recommendedAction") or "Reduce the audited abnormality before it becomes guest-visible."),
        "park_action": {"target": target, "action": action},
        "source_finding_id": finding.get("id"),
        "policy_compliance": policy_compliance_for_action(
            target,
            action,
            checks=["safety-first", "source-grounded", "capacity-aware", "human-review-if-needed"],
        ),
    }
