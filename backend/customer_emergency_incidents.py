from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any


_customer_emergency_incidents: list[dict[str, Any]] = []
_idempotency_index: dict[str, str] = {}

STATUS_ORDER = ["submitted", "triaged", "operator_review", "dispatched", "resolved"]
ACTION_STATUS = {
    "acknowledge": "operator_review",
    "dispatch": "dispatched",
    "resolve": "resolved",
    "false_alarm": "resolved",
}

_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}(?!\d)")
_LONG_NUMBER_RE = re.compile(r"\b\d{5,}\b")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _new_id() -> str:
    return f"PP-EMERG-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{len(_customer_emergency_incidents) + 1:03d}"


def redact_customer_text(text: str) -> dict[str, Any]:
    redacted = _EMAIL_RE.sub("[redacted-email]", text)
    redacted = _PHONE_RE.sub("[redacted-phone]", redacted)
    redacted = _LONG_NUMBER_RE.sub("[redacted-number]", redacted)
    return {
        "text": redacted[:1400],
        "changed": redacted != text,
        "rules": ["email", "phone", "long_number"],
    }


def _fingerprint(payload: dict[str, Any]) -> str:
    raw = "|".join(
        [
            str(payload.get("text", ""))[:500].lower(),
            str(payload.get("location", "")).lower(),
            str(payload.get("zoneId", "")),
            str(payload.get("immediateDanger", "")),
            str(payload.get("accessBlocked", "")),
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _timeline(statuses: list[str], actor: str = "system", note: str = "") -> list[dict[str, Any]]:
    now = _now_iso()
    return [{"status": status, "at": now, "actor": actor, "note": note} for status in statuses]


def create_customer_emergency_incident(
    payload: dict[str, Any],
    *,
    classification: dict[str, Any],
    signal_execution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    idempotency_key = str(payload.get("idempotencyKey") or "").strip() or _fingerprint(payload)
    existing_id = _idempotency_index.get(idempotency_key)
    if existing_id:
        existing = next((incident for incident in _customer_emergency_incidents if incident.get("id") == existing_id), None)
        if existing:
            copied = deepcopy(existing)
            copied["deduped"] = True
            return copied

    text = str(payload.get("text", "")).strip()
    redaction = redact_customer_text(text)
    requires_review = bool(classification.get("requires_human_review"))
    initial_statuses = ["submitted", "triaged"]
    if requires_review:
        initial_statuses.append("operator_review")
    status = initial_statuses[-1]
    signal = (signal_execution or {}).get("signal", {}) if isinstance(signal_execution, dict) else {}
    delivery = (signal_execution or {}).get("delivery", {}) if isinstance(signal_execution, dict) else {}
    customer_care_case = (signal_execution or {}).get("customer_care_case", {}) if isinstance(signal_execution, dict) else {}
    if not isinstance(signal, dict):
        signal = {}
    if not isinstance(delivery, dict):
        delivery = {}
    if not isinstance(customer_care_case, dict):
        customer_care_case = {}
    incident = {
        "id": _new_id(),
        "createdAt": _now_iso(),
        "updatedAt": _now_iso(),
        "status": status,
        "lifecycle": {
            "current": status,
            "allowed_next_actions": allowed_incident_actions(status),
            "timeline": _timeline(initial_statuses, note="Customer report accepted and triaged."),
        },
        "source": "customer_emergency_chat",
        "idempotencyKey": idempotency_key,
        "deduped": False,
        "customer_report": {
            "text": redaction["text"],
            "redacted": redaction["changed"],
            "redaction_rules": redaction["rules"],
            "location": str(payload.get("location", "")).strip(),
            "zoneId": payload.get("zoneId"),
            "flags": {
                "immediateDanger": bool(payload.get("immediateDanger")),
                "accessBlocked": bool(payload.get("accessBlocked")),
                "staffOnScene": bool(payload.get("staffOnScene")),
                "contactAllowed": bool(payload.get("contactAllowed")),
            },
        },
        "classification": deepcopy(classification),
        "severity": classification.get("severity"),
        "escalation_level": classification.get("escalation_level"),
        "recommended_owner": classification.get("recommended_owner", "Guest Services"),
        "requires_human_review": requires_review,
        "signal_id": signal.get("id"),
        "signal_risk_level": signal.get("risk_level"),
        "missing_info": signal.get("missing_info", []),
        "customer_care_case_id": customer_care_case.get("id"),
        "delivery_summary": delivery.get("summary", {}),
        "operator": {
            "assigned_to": classification.get("recommended_owner", "Guest Services"),
            "last_action": "auto_triaged",
            "last_actor": "system",
            "notes": [],
        },
        "audit": {
            "privacy_redaction_applied": redaction["changed"],
            "signal_pipeline_status": (signal_execution or {}).get("status") if isinstance(signal_execution, dict) else None,
            "prohibited_autonomy": [
                "no_medical_diagnosis",
                "no_area_safe_claim",
                "no_evacuate_without_human_authority",
                "no_ride_reopen_or_clearance",
            ],
        },
    }
    _customer_emergency_incidents.insert(0, incident)
    _idempotency_index[idempotency_key] = incident["id"]
    del _customer_emergency_incidents[80:]
    return deepcopy(incident)


def upsert_customer_emergency_incident(incident: dict[str, Any]) -> dict[str, Any]:
    incident_id = str(incident.get("id") or incident.get("_id") or "")
    if not incident_id:
        raise ValueError("Customer emergency incident requires an id.")
    document = deepcopy(incident)
    document["id"] = incident_id
    _customer_emergency_incidents[:] = [row for row in _customer_emergency_incidents if row.get("id") != incident_id and row.get("_id") != incident_id]
    _customer_emergency_incidents.insert(0, document)
    idempotency_key = str(document.get("idempotencyKey") or "").strip()
    if idempotency_key:
        _idempotency_index[idempotency_key] = incident_id
    del _customer_emergency_incidents[80:]
    return deepcopy(document)


def build_customer_emergency_audit_event(
    incident: dict[str, Any],
    event_type: str,
    *,
    actor: str = "system",
    action: str | None = None,
    note: str = "",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    incident_id = str(incident.get("id") or incident.get("_id") or "unknown")
    created_at = _now_iso()
    event_id_seed = f"{incident_id}:{event_type}:{actor}:{action or ''}:{note}:{created_at}"
    return {
        "id": f"PP-EMERG-AUDIT-{hashlib.sha1(event_id_seed.encode('utf-8')).hexdigest()[:16]}",
        "createdAt": created_at,
        "incidentId": incident_id,
        "eventType": event_type,
        "actor": actor,
        "action": action,
        "status": incident.get("status"),
        "severity": incident.get("severity"),
        "escalationLevel": incident.get("escalation_level"),
        "recommendedOwner": incident.get("recommended_owner"),
        "note": note,
        "details": deepcopy(details or {}),
    }


def allowed_incident_actions(status: str) -> list[str]:
    if status in {"submitted", "triaged"}:
        return ["acknowledge", "dispatch", "resolve", "false_alarm"]
    if status == "operator_review":
        return ["dispatch", "resolve", "false_alarm"]
    if status == "dispatched":
        return ["resolve"]
    return []


def list_customer_emergency_incidents(limit: int = 30, status: str | None = None) -> dict[str, Any]:
    incidents = _customer_emergency_incidents
    if status:
        incidents = [incident for incident in incidents if incident.get("status") == status]
    copied = deepcopy(incidents[:limit])
    return {
        "status": "ok",
        "count": len(copied),
        "incidents": copied,
        "summary": {
            "open": sum(1 for incident in _customer_emergency_incidents if incident.get("status") != "resolved"),
            "operator_review": sum(1 for incident in _customer_emergency_incidents if incident.get("status") == "operator_review"),
            "dispatched": sum(1 for incident in _customer_emergency_incidents if incident.get("status") == "dispatched"),
            "resolved": sum(1 for incident in _customer_emergency_incidents if incident.get("status") == "resolved"),
            "critical_or_life_safety": sum(1 for incident in _customer_emergency_incidents if incident.get("severity") in {"critical", "life_safety"}),
        },
    }


def get_customer_emergency_incident(incident_id: str) -> dict[str, Any] | None:
    incident = next((item for item in _customer_emergency_incidents if item.get("id") == incident_id), None)
    return deepcopy(incident) if incident else None


def update_customer_emergency_incident(incident_id: str, *, action: str, actor: str, note: str = "") -> dict[str, Any]:
    if action not in ACTION_STATUS:
        raise ValueError(f"Unsupported emergency incident action: {action}")
    for incident in _customer_emergency_incidents:
        if incident.get("id") != incident_id:
            continue
        next_status = ACTION_STATUS[action]
        now = _now_iso()
        incident["status"] = next_status
        incident["updatedAt"] = now
        incident["lifecycle"]["current"] = next_status
        incident["lifecycle"]["allowed_next_actions"] = allowed_incident_actions(next_status)
        incident["lifecycle"]["timeline"].append(
            {
                "status": next_status,
                "at": now,
                "actor": actor or "operator",
                "action": action,
                "note": note,
            }
        )
        incident["operator"]["last_action"] = action
        incident["operator"]["last_actor"] = actor or "operator"
        if note:
            incident["operator"]["notes"].append({"at": now, "actor": actor or "operator", "note": note})
        return deepcopy(incident)
    raise KeyError(incident_id)


def reset_customer_emergency_incidents() -> None:
    _customer_emergency_incidents.clear()
    _idempotency_index.clear()
    try:
        from mongo_memory import _memory

        fallback = getattr(_memory, "_fallback", None)
        if isinstance(fallback, dict):
            fallback["customer_emergency_incidents"] = []
            fallback["customer_emergency_audit"] = []
    except Exception:
        pass
    _idempotency_index.clear()
