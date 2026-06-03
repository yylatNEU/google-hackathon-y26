from __future__ import annotations

import json
import os
import time
from collections import deque
from pathlib import Path
from typing import Any


def _audit_log_path() -> Path:
    return Path(os.getenv("PARKPULSE_ROLE_ACCESS_AUDIT_LOG", "/tmp/parkpulse/role_access_audit.jsonl"))


def _safe_text(value: Any, limit: int = 160) -> str:
    return str(value or "").strip()[:limit]


def record_role_access_audit_event(event_type: str, *, role: Any = "", subject: Any = "", capability: Any = "", resource: Any = "", status: Any = "", reason: Any = "") -> dict[str, Any]:
    event = {
        "timestamp": int(time.time()),
        "mode": "role_access_audit",
        "event_type": _safe_text(event_type, 80),
        "role": _safe_text(role, 80),
        "subject": _safe_text(subject, 160),
        "capability": _safe_text(capability, 120),
        "resource": _safe_text(resource, 160),
        "status": _safe_text(status, 80),
        "reason": _safe_text(reason, 240),
    }
    try:
        path = _audit_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
    except Exception as error:
        event["write_status"] = "failed"
        event["write_error"] = str(error)[:160]
    else:
        event["write_status"] = "ok"
    return event


def role_access_audit_status(limit: int = 20) -> dict[str, Any]:
    path = _audit_log_path()
    events: list[dict[str, Any]] = []
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            lines = deque(handle, maxlen=max(1, min(limit, 100)))
        for line in lines:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                events.append(payload)
    return {
        "status": "ready",
        "mode": "role_access_audit",
        "path": str(path),
        "event_count": len(events),
        "events": events,
    }
