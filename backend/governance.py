from __future__ import annotations

from typing import Any

from park_governance_runtime import list_runtime_governance


def governance_status() -> dict[str, Any]:
    runtime = list_runtime_governance(20)
    return {
        "domain": "amusement_park_operations",
        "status": "ready",
        "runtime_governance": runtime,
        "summary": runtime.get("summary", {}),
    }

