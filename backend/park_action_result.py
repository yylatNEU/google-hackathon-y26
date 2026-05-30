from __future__ import annotations

from copy import deepcopy
from typing import Any


def build_park_action_result(result: dict[str, Any], target: str, action: str) -> dict[str, Any]:
    status = str(result.get("status", "unknown"))
    message = str(result.get("message", "Park action completed."))
    return {
        **deepcopy(result),
        "status": status,
        "message": message,
        "domain": "amusement_park_operations",
        "park_action": {"target": target, "action": action},
        "controlled_scope": _controlled_scope(target, action),
    }


def _controlled_scope(target: str, action: str) -> str:
    if (target, action) == ("ride", "reroute"):
        return "guest routing, queue intake messaging, and crowd-flow support only"
    if (target, action) == ("staff", "redeploy"):
        return "role-compatible worker notification and supervisor-reviewed redeployment"
    if (target, action) == ("food", "suppress_item"):
        return "mobile-order menu visibility, pickup ETA, and inventory-safe promotion"
    if (target, action) == ("traffic", "redirect_food"):
        return "guest-app nudges and path/food demand distribution"
    if (target, action) == ("energy", "protect_hvac"):
        return "comfort-preserving HVAC and noncritical load settings"
    return "operator-reviewed park operation"
