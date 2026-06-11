#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

DEFAULT_OUTPUT_ROOT = REPO_ROOT / "output" / "qa"

ALLOWED_GEMINI_ACTIONS = [
    {
        "target": "ride",
        "action": "reroute",
        "label": "Reroute guests away from the most constrained ride.",
        "boundary": "No ride control or reopening authority.",
    },
    {
        "target": "staff",
        "action": "redeploy",
        "label": "Redeploy available staff to the pressure zone.",
        "boundary": "Preserve protected breaks and role qualifications.",
    },
    {
        "target": "staff",
        "action": "redeploy_food_certified",
        "label": "Redeploy food-certified staff to pickup and prep bottlenecks.",
        "boundary": "Preserve protected breaks, minor labor limits, and role qualifications.",
    },
    {
        "target": "traffic",
        "action": "redirect_food",
        "label": "Redirect demand toward lower-pressure food and guest-flow zones.",
        "boundary": "No public promises or discounts.",
    },
    {
        "target": "food",
        "action": "suppress_item",
        "label": "Suppress a constrained mobile-order item and promote safer alternatives.",
        "boundary": "No allergen or inventory guarantees.",
    },
    {
        "target": "food",
        "action": "pause_mobile_order_intake",
        "label": "Temporarily pause new mobile-order intake at the overloaded food location.",
        "boundary": "Internal load-shedding only; no refund or public promise automation.",
    },
    {
        "target": "food",
        "action": "open_temp_pickup",
        "label": "Open a temporary pickup lane to increase food throughput.",
        "boundary": "Requires available food-certified staff and safe staging space.",
    },
    {
        "target": "food",
        "action": "open_satellite_cart",
        "label": "Open a satellite food cart away from Food Court A to add physical service capacity.",
        "boundary": "Requires stocked portable cart, health-code setup, and staff certified for food handling.",
    },
    {
        "target": "food",
        "action": "throttle_mobile_pickup_windows",
        "label": "Throttle new pickup windows and smooth mobile-order demand without fully closing intake.",
        "boundary": "No cancellation of paid orders; only future pickup-window pacing and guest messaging.",
    },
    {
        "target": "queue_gate",
        "action": "hold_intake",
        "label": "Temporarily hold new queue intake at the most constrained attraction.",
        "boundary": "No ride restart or maintenance clearance authority; guest messaging must be reversible.",
    },
    {
        "target": "traffic",
        "action": "staged_reroute",
        "label": "Stage guests through multiple lower-pressure destinations instead of one broad reroute.",
        "boundary": "No emergency instruction; only bounded app nudges with capacity-aware destinations.",
    },
    {
        "target": "energy",
        "action": "protect_hvac",
        "label": "Protect indoor shelter HVAC while energy load is high.",
        "boundary": "No automated building-control override.",
    },
    {
        "target": "signage",
        "action": "update",
        "label": "Update internal/digital wayfinding guidance.",
        "boundary": "No emergency or safety-critical instruction.",
    },
]

FOOD_RECOVERY_ACTION_KEYS = {
    "food/suppress_item",
    "food/pause_mobile_order_intake",
    "food/open_temp_pickup",
    "food/open_satellite_cart",
    "food/throttle_mobile_pickup_windows",
    "staff/redeploy_food_certified",
}


def _now_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    return path.stat().st_size


def _first_json_object(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start < 0:
        return {}
    depth = 0
    in_string = False
    escape = False
    for index, char in enumerate(text[start:], start=start):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(text[start : index + 1])
                except json.JSONDecodeError:
                    return {}
                return parsed if isinstance(parsed, dict) else {}
    return {}


def _selected_allowed_action(raw: dict[str, Any]) -> dict[str, Any] | None:
    selected = raw.get("selected_action") if isinstance(raw.get("selected_action"), dict) else raw
    target = str(selected.get("target") or "").strip()
    action = str(selected.get("action") or "").strip()
    for allowed in ALLOWED_GEMINI_ACTIONS:
        if allowed["target"] == target and allowed["action"] == action:
            return dict(allowed)
    return None


def _allowed_action(target: str, action: str) -> dict[str, Any] | None:
    for allowed in ALLOWED_GEMINI_ACTIONS:
        if allowed["target"] == target and allowed["action"] == action:
            return dict(allowed)
    return None


def _action_key(action: dict[str, Any] | None) -> str:
    if not isinstance(action, dict):
        return "none"
    return f"{action.get('target')}/{action.get('action')}"


def _action_family(action: dict[str, Any] | None) -> str:
    key = _action_key(action)
    if key in {
        "food/suppress_item",
        "food/pause_mobile_order_intake",
        "food/open_temp_pickup",
        "food/open_satellite_cart",
        "food/throttle_mobile_pickup_windows",
        "staff/redeploy_food_certified",
    }:
        return "food_service"
    if key in {"ride/reroute", "traffic/redirect_food", "traffic/staged_reroute", "queue_gate/hold_intake"}:
        return "guest_flow"
    if key == "staff/redeploy":
        return "staffing"
    if key == "energy/protect_hvac":
        return "energy"
    if key == "signage/update":
        return "signage"
    return "none"


def _food_pressure(digest: dict[str, Any]) -> dict[str, Any]:
    backlog = int(digest.get("food_backlog") or 0)
    eta = int(digest.get("food_eta_minutes") or 0)
    if backlog >= 700 or eta >= 75:
        severity = "p0_gridlock"
    elif backlog >= 400 or eta >= 45:
        severity = "p1_critical"
    elif backlog >= 140 or eta >= 25:
        severity = "p2_warning"
    else:
        severity = "normal"
    return {
        "backlog": backlog,
        "eta_minutes": eta,
        "severity": severity,
        "is_critical": severity in {"p0_gridlock", "p1_critical"},
        "is_warning_or_worse": severity != "normal",
    }


def _food_trend_risk(current_digest: dict[str, Any], recent_digests: list[dict[str, Any]]) -> dict[str, Any]:
    pressure = _food_pressure(current_digest)
    previous = recent_digests[-4] if len(recent_digests) >= 4 and isinstance(recent_digests[-4], dict) else None
    if previous:
        backlog_delta = int(current_digest.get("food_backlog") or 0) - int(previous.get("food_backlog") or 0)
        eta_delta = int(current_digest.get("food_eta_minutes") or 0) - int(previous.get("food_eta_minutes") or 0)
    else:
        backlog_delta = 0
        eta_delta = 0
    rising = backlog_delta >= 30 or eta_delta >= 3
    return {
        "severity": pressure["severity"],
        "is_warning_or_worse": pressure["is_warning_or_worse"],
        "is_critical": pressure["is_critical"],
        "backlog_delta_recent": backlog_delta,
        "eta_delta_recent": eta_delta,
        "rising": rising,
        "requires_food_protection": pressure["is_warning_or_worse"] or rising,
    }


def _recent_effective_action_keys(gemini_rows: list[dict[str, Any]], limit: int = 3) -> list[str]:
    keys: list[str] = []
    for row in reversed(gemini_rows):
        gate = row.get("policy_gate", {}) if isinstance(row.get("policy_gate"), dict) else {}
        effective = gate.get("effective_action") if isinstance(gate.get("effective_action"), dict) else row.get("allowed_action")
        keys.append(_action_key(effective))
        if len(keys) >= limit:
            break
    return keys


def _recent_effective_action_families(gemini_rows: list[dict[str, Any]], limit: int = 4) -> list[str]:
    families: list[str] = []
    for row in reversed(gemini_rows):
        gate = row.get("policy_gate", {}) if isinstance(row.get("policy_gate"), dict) else {}
        effective = gate.get("effective_action") if isinstance(gate.get("effective_action"), dict) else row.get("allowed_action")
        families.append(_action_family(effective))
        if len(families) >= limit:
            break
    return families


def _arbitrate_allowed_action(
    *,
    selected: dict[str, Any] | None,
    state_digest: dict[str, Any],
    gemini_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    pressure = _food_pressure(state_digest)
    selected_key = _action_key(selected)
    recent_keys = _recent_effective_action_keys(gemini_rows, 3)
    reasons: list[str] = []
    effective = dict(selected) if selected else None

    if selected is None:
        return None, {
            "status": "blocked",
            "reason": "Gemini selected an action outside the allowed bounded action set.",
            "food_pressure": pressure,
            "selected_action": None,
            "effective_action": None,
            "recent_effective_actions": recent_keys,
        }

    if pressure["is_critical"] and selected_key == "ride/reroute":
        effective = (
            _allowed_action("food", "open_temp_pickup")
            if pressure["severity"] == "p0_gridlock"
            else _allowed_action("food", "pause_mobile_order_intake")
        )
        reasons.append(
            "food-critical hard gate: ride/reroute is blocked while food_backlog >= 400 or food_eta_minutes >= 45"
        )
    elif (
        pressure["is_warning_or_worse"]
        and selected_key == "ride/reroute"
        and recent_keys[:1] == ["ride/reroute"]
    ):
        effective = _allowed_action("food", "pause_mobile_order_intake")
        reasons.append("food-warning persistence gate: second consecutive ride/reroute is blocked while food remains warning")
    elif selected_key != "signage/update" and recent_keys[:2] == [selected_key, selected_key]:
        effective = _allowed_action("staff", "redeploy")
        reasons.append(f"action-diversity gate: more than two consecutive {selected_key} decisions are blocked")

    status = "overridden" if _action_key(effective) != selected_key else "passed"
    return effective, {
        "status": status,
        "reason": "; ".join(reasons) if reasons else "selected action passed hard policy gates",
        "food_pressure": pressure,
        "selected_action": selected,
        "effective_action": effective,
        "recent_effective_actions": recent_keys,
    }


def _candidate_id(action: dict[str, Any]) -> str:
    return f"{action['target']}__{action['action']}"


def _ride_wait(digest: dict[str, Any]) -> int:
    ride = digest.get("slowest_ride", {}) if isinstance(digest.get("slowest_ride"), dict) else {}
    return int(ride.get("waitMins") or 0)


def _zone_density(digest: dict[str, Any]) -> int:
    zone = digest.get("busiest_zone", {}) if isinstance(digest.get("busiest_zone"), dict) else {}
    return int(zone.get("density") or 0)


def _path_congestion(digest: dict[str, Any]) -> int:
    path = digest.get("most_congested_path", {}) if isinstance(digest.get("most_congested_path"), dict) else {}
    return int(path.get("congestionLevel") or 0)


def _candidate_score(action: dict[str, Any], digest: dict[str, Any], pressure: dict[str, Any], recent_keys: list[str]) -> int:
    key = _action_key(action)
    wait = _ride_wait(digest)
    density = _zone_density(digest)
    path = _path_congestion(digest)
    callouts = int(digest.get("open_callouts") or 0)
    grid = int(digest.get("grid_load") or 0)
    backlog = int(pressure["backlog"])
    eta = int(pressure["eta_minutes"])

    if key == "food/suppress_item":
        return min(100, 48 + backlog // 18 + eta // 2)
    if key == "food/pause_mobile_order_intake":
        return min(100, 55 + backlog // 20 + eta // 2)
    if key == "food/open_temp_pickup":
        return min(100, 58 + backlog // 16 + eta // 2)
    if key == "food/open_satellite_cart":
        return min(100, 62 + backlog // 15 + eta // 2 + max(0, density - 95) // 5)
    if key == "food/throttle_mobile_pickup_windows":
        return min(100, 54 + backlog // 18 + eta // 2 + max(0, path - 95) // 8)
    if key == "staff/redeploy_food_certified":
        return min(100, 50 + callouts // 2 + backlog // 22 + eta // 3)
    if key == "staff/redeploy":
        return min(100, 42 + callouts + backlog // 45 + max(0, wait - 60) // 3)
    if key == "traffic/redirect_food":
        return min(100, 46 + max(0, density - 85) + max(0, path - 85) // 2 + backlog // 55)
    if key == "traffic/staged_reroute":
        repeat_penalty = 10 if recent_keys[:1] == ["traffic/staged_reroute"] else 0
        return min(100, 52 + max(0, wait - 65) // 2 + max(0, path - 90) // 3 + max(0, density - 100) // 4 - repeat_penalty)
    if key == "ride/reroute":
        repeat_penalty = 18 if recent_keys[:1] == ["ride/reroute"] else 0
        return min(100, max(0, 45 + max(0, wait - 45) + max(0, density - 95) // 2 - repeat_penalty))
    if key == "queue_gate/hold_intake":
        repeat_penalty = 12 if recent_keys[:1] == ["queue_gate/hold_intake"] else 0
        return min(100, max(0, 56 + max(0, wait - 70) + max(0, path - 95) // 3 - repeat_penalty))
    if key == "energy/protect_hvac":
        return min(100, 36 + max(0, grid - 88) * 3 + max(0, density - 100) // 2)
    if key == "signage/update":
        return 40
    return 0


def _candidate_policy_status(action: dict[str, Any], digest: dict[str, Any], recent_keys: list[str]) -> tuple[str, list[str]]:
    pressure = _food_pressure(digest)
    key = _action_key(action)
    reasons: list[str] = []
    if pressure["is_critical"] and key not in FOOD_RECOVERY_ACTION_KEYS:
        reasons.append("POL-FOOD-RECOVERY-DUTY requires a food-throughput action while food_backlog >= 400 or food_eta_minutes >= 45.")
    if pressure["is_critical"] and key == "ride/reroute":
        reasons.append("POL-FOOD-CRITICAL blocks ride/reroute while food_backlog >= 400 or food_eta_minutes >= 45.")
    if pressure["severity"] == "p0_gridlock" and key == "ride/reroute":
        reasons.append("POL-FOOD-P0 requires food, staff, or traffic handling before ride action.")
    if pressure["is_warning_or_worse"] and key in {"ride/reroute", "traffic/staged_reroute"} and recent_keys[:1] == [key]:
        reasons.append(f"POL-REROUTE-PERSISTENCE blocks repeated {key} while food remains warning or worse.")
    if key != "signage/update" and recent_keys[:2] == [key, key]:
        reasons.append(f"POL-ACTION-DIVERSITY blocks more than two consecutive {key} decisions.")
    return ("blocked" if reasons else "passed", reasons)


def _action_plan_for_candidate(action: dict[str, Any]) -> dict[str, Any]:
    action_key = _action_key(action)
    plan = {
        "target": action["target"],
        "action": action["action"],
        "label": action.get("label") or _action_key(action),
    }
    if action_key == "traffic/staged_reroute":
        plan["action_mix"] = {
            "guest_reroute": {
                "enabled": True,
                "durationMinutes": 12,
                "expectedTakeRate": 0.28,
                "target_mix": [
                    {"zoneId": "arcadeZone", "destination": "Arcade Zone", "share": 0.32, "currentWaitMins": 10},
                    {"zoneId": "indoorHub", "destination": "Indoor Ride Hub", "share": 0.24, "currentWaitMins": 32},
                    {"zoneId": "coveredPlaza", "destination": "Covered Plaza", "share": 0.18, "currentWaitMins": 8},
                ],
            },
            "controls": {"queue_gates": [{"target": "primary_ride", "settings": {"holdMinutes": 10}}]},
        }
    elif action_key == "queue_gate/hold_intake":
        plan["action_mix"] = {
            "controls": {"queue_gates": [{"target": "primary_ride", "settings": {"holdMinutes": 12}}]},
            "guest_reroute": {
                "enabled": True,
                "durationMinutes": 8,
                "expectedTakeRate": 0.18,
                "target_mix": [
                    {"zoneId": "arcadeZone", "destination": "Arcade Zone", "share": 0.26, "currentWaitMins": 10},
                    {"zoneId": "coveredPlaza", "destination": "Covered Plaza", "share": 0.18, "currentWaitMins": 8},
                ],
            },
        }
    elif action_key == "food/open_satellite_cart":
        plan["action_mix"] = {
            "food": {
                "satelliteCapacity": True,
                "avoidExtraDemandAt": ["foodCourt1"],
                "promoteItems": ["grab_and_go_combo", "bottled_drinks"],
            }
        }
    elif action_key == "food/throttle_mobile_pickup_windows":
        plan["action_mix"] = {
            "food": {
                "pickupWindowThrottle": True,
                "avoidExtraDemandAt": ["foodCourt1"],
                "promoteItems": ["later_pickup_windows"],
            }
        }
    return plan


def _counterfactual_score(
    projection: dict[str, Any],
    heuristic_score: int,
    *,
    action: dict[str, Any],
    digest: dict[str, Any],
    pressure: dict[str, Any],
    recent_families: list[str],
    score_calibration: dict[str, Any] | None = None,
) -> int:
    if not isinstance(projection, dict) or projection.get("status") != "ok":
        return heuristic_score
    outcome = projection.get("outcome", {}) if isinstance(projection.get("outcome"), dict) else {}
    metrics = outcome.get("metrics", {}) if isinstance(outcome.get("metrics"), dict) else {}
    relative = projection.get("relative_to_no_action", {}) if isinstance(projection.get("relative_to_no_action"), dict) else {}
    scorecard = projection.get("scorecard", {}) if isinstance(projection.get("scorecard"), dict) else {}
    secondary_risks = projection.get("secondary_risks", []) if isinstance(projection.get("secondary_risks"), list) else []
    key = _action_key(action)
    family = _action_family(action)
    relative = _calibrated_relative(relative, key, score_calibration)
    wait = _ride_wait(digest)
    path = _path_congestion(digest)
    density = _zone_density(digest)
    callouts = int(digest.get("open_callouts") or 0)
    if relative:
        score = 68
        food_backlog_gain = max(0, -int(relative.get("food_backlog_delta") or 0)) // 8
        food_eta_gain = max(0, -int(relative.get("food_eta_minutes_delta") or 0)) * 2
        food_gain_cap = {
            "normal": 4,
            "p2_warning": 14,
            "p1_critical": 30,
            "p0_gridlock": 38,
        }.get(str(pressure.get("severity")), 12)
        score += min(food_gain_cap, food_backlog_gain + food_eta_gain)
        score += max(0, -int(relative.get("slowest_ride_wait_delta") or 0)) // 2
        score += max(0, int(relative.get("avg_satisfaction_delta") or 0)) * 3
        score += max(0, -int(relative.get("busiest_zone_density_delta") or 0)) * 2
        score -= max(0, int(relative.get("food_backlog_delta") or 0)) // 6
        score -= max(0, int(relative.get("food_eta_minutes_delta") or 0)) * 3
        score -= max(0, int(relative.get("slowest_ride_wait_delta") or 0)) // 2
        score -= max(0, int(relative.get("open_callouts_delta") or 0)) * 5
    else:
        score = int(scorecard.get("overall") or outcome.get("overall") or heuristic_score)
        score -= max(0, int(metrics.get("food_backlog_delta") or 0)) // 8
        score -= max(0, int(metrics.get("slowest_ride_wait_delta") or 0)) // 3
        score -= max(0, int(metrics.get("staff_callout_delta") or 0)) * 4
    if family == "food_service" and pressure["severity"] in {"normal", "p2_warning"}:
        if wait >= 90:
            score -= min(24, (wait - 75) // 2)
        if path >= 110 or density >= 118:
            score -= 8
    if family == "guest_flow" and not pressure["is_critical"]:
        score += min(18, max(0, wait - 70) // 3 + max(0, path - 95) // 6 + max(0, density - 105) // 5)
    if key == "staff/redeploy" and callouts >= 28:
        score += min(14, (callouts - 24) // 2)
    if family == "food_service" and recent_families[:2] == ["food_service", "food_service"] and not pressure["is_critical"]:
        score -= 18
    if family == "food_service" and recent_families[:3] == ["food_service", "food_service", "food_service"]:
        score -= 12
    if family == "guest_flow" and recent_families[:2] == ["guest_flow", "guest_flow"] and pressure["is_warning_or_worse"]:
        score -= 12
    score -= max(0, int(metrics.get("critical_density_excess") or 0)) * 2
    score -= max(0, len(secondary_risks) - 1) * 4
    return max(0, min(100, score))


def _digest_delta(after: dict[str, Any], baseline_after: dict[str, Any]) -> dict[str, int]:
    return {
        "avg_satisfaction_delta": int(after.get("avg_satisfaction") or 0) - int(baseline_after.get("avg_satisfaction") or 0),
        "slowest_ride_wait_delta": _ride_wait(after) - _ride_wait(baseline_after),
        "food_backlog_delta": int(after.get("food_backlog") or 0) - int(baseline_after.get("food_backlog") or 0),
        "food_eta_minutes_delta": int(after.get("food_eta_minutes") or 0) - int(baseline_after.get("food_eta_minutes") or 0),
        "busiest_zone_density_delta": _zone_density(after) - _zone_density(baseline_after),
        "path_congestion_delta": _path_congestion(after) - _path_congestion(baseline_after),
        "open_callouts_delta": int(after.get("open_callouts") or 0) - int(baseline_after.get("open_callouts") or 0),
        "grid_load_delta": int(after.get("grid_load") or 0) - int(baseline_after.get("grid_load") or 0),
    }


def _attach_relative_to_no_action(projection: dict[str, Any], no_action_projection: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(projection, dict) or not isinstance(no_action_projection, dict):
        return projection
    outcome = projection.get("outcome", {}) if isinstance(projection.get("outcome"), dict) else {}
    baseline_outcome = no_action_projection.get("outcome", {}) if isinstance(no_action_projection.get("outcome"), dict) else {}
    after = outcome.get("after", {}) if isinstance(outcome.get("after"), dict) else {}
    baseline_after = baseline_outcome.get("after", {}) if isinstance(baseline_outcome.get("after"), dict) else {}
    if after and baseline_after:
        projection["relative_to_no_action"] = _digest_delta(after, baseline_after)
    return projection


def _counterfactual_summary(projection: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(projection, dict) or projection.get("status") != "ok":
        return {"status": "not_available"}
    outcome = projection.get("outcome", {}) if isinstance(projection.get("outcome"), dict) else {}
    metrics = outcome.get("metrics", {}) if isinstance(outcome.get("metrics"), dict) else {}
    return {
        "status": "ok",
        "horizon_minutes": projection.get("horizon_minutes"),
        "overall": outcome.get("overall"),
        "scorecard": projection.get("scorecard", {}),
        "metrics": {
            "busiest_zone_density_delta": metrics.get("busiest_zone_density_delta"),
            "slowest_ride_wait_delta": metrics.get("slowest_ride_wait_delta"),
            "avg_satisfaction_delta": metrics.get("avg_satisfaction_delta"),
            "food_backlog_delta": metrics.get("food_backlog_delta"),
            "path_congestion_delta": metrics.get("path_congestion_delta"),
            "staff_callout_delta": metrics.get("staff_callout_delta"),
            "grid_load_delta": metrics.get("grid_load_delta"),
            "storm_risk_delta": metrics.get("storm_risk_delta"),
            "safety_violations": metrics.get("safety_violations"),
            "critical_density_excess": metrics.get("critical_density_excess"),
        },
        "projected_impact": projection.get("projected_impact", {}),
        "secondary_risks": projection.get("secondary_risks", []),
        "relative_to_no_action": projection.get("relative_to_no_action", {}),
    }


def _build_policy_candidates(
    state_digest: dict[str, Any],
    gemini_rows: list[dict[str, Any]],
    *,
    state: dict[str, Any] | None = None,
    counterfactual_horizon_minutes: int = 30,
    score_calibration: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    pressure = _food_pressure(state_digest)
    recent_keys = _recent_effective_action_keys(gemini_rows, 3)
    recent_families = _recent_effective_action_families(gemini_rows, 4)
    candidates: list[dict[str, Any]] = []
    simulate_action_plan = None
    if state is not None:
        from park_twin_engine import simulate_action_plan as _simulate_action_plan

        simulate_action_plan = _simulate_action_plan
    no_action_projection: dict[str, Any] | None = None
    if simulate_action_plan is not None:
        try:
            no_action_projection = simulate_action_plan(
                state,
                {"target": "none", "action": "natural", "label": "No action baseline"},
                horizon_minutes=counterfactual_horizon_minutes,
                seed=f"candidate-counterfactual:no-action:{len(gemini_rows)}",
            )
        except Exception:
            no_action_projection = None
    for action in ALLOWED_GEMINI_ACTIONS:
        policy_status, policy_reasons = _candidate_policy_status(action, state_digest, recent_keys)
        heuristic_score = _candidate_score(action, state_digest, pressure, recent_keys)
        counterfactual: dict[str, Any] = {"status": "not_run"}
        score = heuristic_score
        if simulate_action_plan is not None and policy_status == "passed":
            try:
                projection = simulate_action_plan(
                    state,
                    _action_plan_for_candidate(action),
                    horizon_minutes=counterfactual_horizon_minutes,
                    seed=f"candidate-counterfactual:{_candidate_id(action)}:{len(gemini_rows)}",
                )
                projection = _attach_relative_to_no_action(projection, no_action_projection)
                counterfactual = _counterfactual_summary(projection)
                score = _counterfactual_score(
                    projection,
                    heuristic_score,
                    action=action,
                    digest=state_digest,
                    pressure=pressure,
                    recent_families=recent_families,
                    score_calibration=score_calibration,
                )
                if isinstance(counterfactual, dict) and isinstance(counterfactual.get("relative_to_no_action"), dict):
                    counterfactual["calibrated_relative_to_no_action"] = _calibrated_relative(
                        counterfactual["relative_to_no_action"],
                        _action_key(action),
                        score_calibration,
                    )
            except Exception as error:
                counterfactual = {"status": "error", "error": str(error)[:300]}
        candidate = {
            "id": _candidate_id(action),
            "target": action["target"],
            "action": action["action"],
            "label": action["label"],
            "boundary": action["boundary"],
            "policy_status": policy_status,
            "policy_reasons": policy_reasons,
            "heuristic_score": heuristic_score,
            "counterfactual_score": score,
            "counterfactual": counterfactual,
            "score": score if policy_status == "passed" else max(0, score - 45),
            "risk_context": {
                "food_pressure": pressure,
                "ride_wait_minutes": _ride_wait(state_digest),
                "busiest_zone_density": _zone_density(state_digest),
                "path_congestion": _path_congestion(state_digest),
                "recent_effective_actions": recent_keys,
                "recent_effective_families": recent_families,
            },
        }
        candidates.append(candidate)
    return sorted(candidates, key=lambda item: (item["policy_status"] == "passed", item["score"]), reverse=True)


def _best_policy_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    passed = [candidate for candidate in candidates if candidate.get("policy_status") == "passed"]
    return max(passed, key=lambda item: int(item.get("score") or 0), default=None)


def _candidate_relative(candidate: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        return {}
    counterfactual = candidate.get("counterfactual", {})
    if not isinstance(counterfactual, dict):
        return {}
    relative = counterfactual.get("relative_to_no_action", {})
    return relative if isinstance(relative, dict) else {}


def _candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": candidate.get("id"),
        "action": _action_key(_candidate_to_action(candidate)),
        "policy_status": candidate.get("policy_status"),
        "policy_reasons": candidate.get("policy_reasons", []),
        "score": candidate.get("score"),
        "deltas": {
            key: _float_value(value)
            for key, value in _candidate_relative(candidate).items()
            if key in RUNTIME_MEMORY_METRICS
        },
        "risk_context": candidate.get("risk_context", {}),
    }


def _relative_int(relative: dict[str, Any], key: str) -> int:
    try:
        return int(relative.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _load_score_calibration(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        parsed = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _calibrated_relative(relative: dict[str, Any], action_key: str, score_calibration: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(relative, dict):
        return {}
    calibrated = dict(relative)
    multipliers = (
        score_calibration.get("action_metric_multipliers", {}).get(action_key, {})
        if isinstance(score_calibration, dict) and isinstance(score_calibration.get("action_metric_multipliers"), dict)
        else {}
    )
    if not isinstance(multipliers, dict):
        return calibrated
    for metric, multiplier in multipliers.items():
        if metric not in calibrated:
            continue
        try:
            calibrated[metric] = round(float(calibrated[metric]) * float(multiplier), 3)
        except (TypeError, ValueError):
            continue
    return calibrated


def _override_food_regression_guard(
    *,
    selected: dict[str, Any],
    override: dict[str, Any],
    material_backlog_delta: int = 25,
    material_eta_delta: int = 2,
    emergency_flow_benefit: int = 20,
) -> dict[str, Any]:
    selected_relative = _candidate_relative(selected)
    override_relative = _candidate_relative(override)
    pressure = override.get("risk_context", {}).get("food_pressure", {}) if isinstance(override.get("risk_context"), dict) else {}
    severity = str(pressure.get("severity") or "normal")

    food_backlog_regression_vs_selected = _relative_int(override_relative, "food_backlog_delta") - _relative_int(
        selected_relative, "food_backlog_delta"
    )
    food_eta_regression_vs_selected = _relative_int(override_relative, "food_eta_minutes_delta") - _relative_int(
        selected_relative, "food_eta_minutes_delta"
    )
    food_backlog_regression_vs_no_action = _relative_int(override_relative, "food_backlog_delta")
    food_eta_regression_vs_no_action = _relative_int(override_relative, "food_eta_minutes_delta")

    material_food_regression = (
        food_backlog_regression_vs_selected > material_backlog_delta
        or food_eta_regression_vs_selected > material_eta_delta
        or food_backlog_regression_vs_no_action > material_backlog_delta
        or food_eta_regression_vs_no_action > material_eta_delta
    )
    ride_wait_benefit = _relative_int(selected_relative, "slowest_ride_wait_delta") - _relative_int(
        override_relative, "slowest_ride_wait_delta"
    )
    path_benefit = _relative_int(selected_relative, "path_congestion_delta") - _relative_int(
        override_relative, "path_congestion_delta"
    )
    density_benefit = _relative_int(selected_relative, "busiest_zone_density_delta") - _relative_int(
        override_relative, "busiest_zone_density_delta"
    )
    emergency_exception = severity == "normal" and max(ride_wait_benefit, path_benefit, density_benefit) >= emergency_flow_benefit

    return {
        "status": "passed" if not material_food_regression or emergency_exception else "blocked",
        "reason": (
            "override accepted"
            if not material_food_regression
            else "override accepted by normal-food emergency flow exception"
            if emergency_exception
            else "score-gap override blocked because it materially worsens food backlog or ETA"
        ),
        "food_severity": severity,
        "material_backlog_delta": material_backlog_delta,
        "material_eta_delta": material_eta_delta,
        "emergency_flow_benefit": emergency_flow_benefit,
        "food_backlog_regression_vs_selected": food_backlog_regression_vs_selected,
        "food_eta_regression_vs_selected": food_eta_regression_vs_selected,
        "food_backlog_regression_vs_no_action": food_backlog_regression_vs_no_action,
        "food_eta_regression_vs_no_action": food_eta_regression_vs_no_action,
        "ride_wait_benefit_vs_selected": ride_wait_benefit,
        "path_congestion_benefit_vs_selected": path_benefit,
        "busiest_zone_density_benefit_vs_selected": density_benefit,
    }


def _memory_prior_for_candidate(candidate_id: str | None, memory_context: dict[str, Any]) -> dict[str, Any]:
    if not candidate_id or not isinstance(memory_context, dict):
        return {"boost": 0, "direct_votes": 0, "cautionary_votes": 0, "matched_examples": []}
    direct_examples = memory_context.get("examples", []) if isinstance(memory_context.get("examples"), list) else []
    mediator_examples = (
        memory_context.get("mediator_examples", [])
        if isinstance(memory_context.get("mediator_examples"), list)
        else []
    )
    cautionary_examples = (
        memory_context.get("cautionary_examples", [])
        if isinstance(memory_context.get("cautionary_examples"), list)
        else []
    )
    direct_matches = [
        item
        for item in [*direct_examples, *mediator_examples]
        if isinstance(item, dict) and str(item.get("ideal_candidate_id") or "") == candidate_id
    ]
    cautionary_matches = [
        item
        for item in cautionary_examples
        if isinstance(item, dict) and str(item.get("ideal_candidate_id") or "") == candidate_id
    ]
    boost = min(12, len(direct_matches) * 6 + len(cautionary_matches) * 2)
    return {
        "boost": boost,
        "direct_votes": len(direct_matches),
        "cautionary_votes": len(cautionary_matches),
        "matched_examples": [
            {
                "id": item.get("id"),
                "relevance_score": item.get("relevance_score"),
                "memory_role": item.get("memory_role", "direct_prior"),
                "reward_score": item.get("reward_score"),
            }
            for item in [*direct_matches[:2], *cautionary_matches[:2]]
        ],
    }


def _candidate_utility_ledger(
    candidate: dict[str, Any] | None,
    *,
    state_digest: dict[str, Any],
    memory_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        return {"candidate_id": None, "status": "missing", "utility": -999}
    candidate_id = str(candidate.get("id") or "")
    relative = _candidate_relative(candidate)
    pressure = _food_pressure(state_digest)
    score = int(candidate.get("score") or 0)
    wait_delta = _relative_int(relative, "slowest_ride_wait_delta")
    food_delta = _relative_int(relative, "food_backlog_delta")
    eta_delta = _relative_int(relative, "food_eta_minutes_delta")
    satisfaction_delta = _relative_int(relative, "avg_satisfaction_delta")
    path_delta = _relative_int(relative, "path_congestion_delta")
    density_delta = _relative_int(relative, "busiest_zone_density_delta")
    wait = _ride_wait(state_digest)
    path = _path_congestion(state_digest)
    density = _zone_density(state_digest)
    latent_food_pressure = (
        pressure["is_warning_or_worse"]
        or (
            str(state_digest.get("scenario_key") or "") == "food_spike"
            and int(pressure.get("backlog") or 0) >= 100
            and int(pressure.get("eta_minutes") or 0) >= 12
        )
    )

    utility = score
    utility += min(18, max(0, -wait_delta) // 3)
    utility += min(16, max(0, -path_delta) // 4 + max(0, -density_delta) // 4)
    food_recovery_credit = 0
    if latent_food_pressure:
        recovery_cap = 34 if pressure["is_critical"] else 24
        food_recovery_credit = min(recovery_cap, max(0, -food_delta) // 8 + max(0, -eta_delta) * 2)
        utility += food_recovery_credit
    utility += max(0, satisfaction_delta) * 4
    utility -= max(0, -satisfaction_delta) * 5
    utility -= max(0, wait_delta) // 2
    food_penalty_scale = 4 if pressure["is_warning_or_worse"] else 8
    eta_penalty_scale = 3 if pressure["is_warning_or_worse"] else 2
    utility -= max(0, food_delta) // food_penalty_scale
    utility -= max(0, eta_delta) * eta_penalty_scale
    action_key = _action_key(_candidate_to_action(candidate))
    stability_penalties: list[dict[str, Any]] = []
    if latent_food_pressure and action_key in {"traffic/redirect_food", "ride/reroute"}:
        food_recovery_gap = max(0, -food_delta) + max(0, -eta_delta) * 12
        if food_recovery_gap < 45:
            penalty = 18 if pressure["is_critical"] else 10
            if pressure.get("backlog", 0) >= 250 or pressure.get("eta_minutes", 0) >= 30:
                penalty += 8
            utility -= penalty
            stability_penalties.append(
                {
                    "kind": "food_pressure_without_food_recovery",
                    "penalty": penalty,
                    "reason": "Flow relief is discounted while food pressure is warning or worse unless it also materially reduces food backlog or ETA.",
                }
            )
    if pressure["is_critical"] and action_key not in FOOD_RECOVERY_ACTION_KEYS and action_key != "traffic/redirect_food":
        utility -= 45
        stability_penalties.append(
            {
                "kind": "critical_food_non_recovery",
                "penalty": 45,
                "reason": "Critical food pressure requires recovery-first action.",
            }
        )
    constraint_violations: list[dict[str, Any]] = []
    if satisfaction_delta < 0:
        constraint_violations.append(
            {
                "metric": "avg_satisfaction_delta",
                "delta": satisfaction_delta,
                "reason": "Protected guest satisfaction cannot regress for an automatic action.",
            }
        )
    if food_delta > 25:
        constraint_violations.append(
            {
                "metric": "food_backlog_delta",
                "delta": food_delta,
                "reason": "Food backlog cannot materially regress for an automatic action.",
            }
        )
    if eta_delta > 2:
        constraint_violations.append(
            {
                "metric": "food_eta_minutes_delta",
                "delta": eta_delta,
                "reason": "Food ETA cannot materially regress for an automatic action.",
            }
        )
    if latent_food_pressure and action_key not in FOOD_RECOVERY_ACTION_KEYS and food_delta > -25 and eta_delta > -2:
        constraint_violations.append(
            {
                "metric": "food_recovery_floor",
                "delta": {"food_backlog_delta": food_delta, "food_eta_minutes_delta": eta_delta},
                "reason": "Latent or active food pressure requires an action with measurable food recovery.",
            }
        )
    if wait >= 90 and wait_delta > 5:
        constraint_violations.append(
            {
                "metric": "slowest_ride_wait_delta",
                "delta": wait_delta,
                "reason": "High ride wait cannot be made worse for an automatic action.",
            }
        )
    if path >= 110 and path_delta > 8:
        constraint_violations.append(
            {
                "metric": "path_congestion_delta",
                "delta": path_delta,
                "reason": "High path congestion cannot be materially worsened for an automatic action.",
            }
        )
    if density >= 118 and density_delta > 5:
        constraint_violations.append(
            {
                "metric": "busiest_zone_density_delta",
                "delta": density_delta,
                "reason": "High zone density cannot be materially worsened for an automatic action.",
            }
        )
    memory_prior = _memory_prior_for_candidate(candidate_id, memory_context or {})
    utility += int(memory_prior.get("boost") or 0)
    return {
        "candidate_id": candidate_id,
        "target": candidate.get("target"),
        "action": candidate.get("action"),
        "policy_status": candidate.get("policy_status"),
        "counterfactual_score": candidate.get("score"),
        "utility": max(-999, min(150, utility)),
        "constraint_status": "passed" if not constraint_violations else "blocked",
        "constraint_violation_count": len(constraint_violations),
        "constraint_violations": constraint_violations,
        "memory_prior": memory_prior,
        "long_term_stability_adjustment": {
            "food_recovery_credit": food_recovery_credit,
            "stability_penalties": stability_penalties,
        },
        "relative_to_no_action": {
            "avg_satisfaction_delta": satisfaction_delta,
            "slowest_ride_wait_delta": wait_delta,
            "food_backlog_delta": food_delta,
            "food_eta_minutes_delta": eta_delta,
            "path_congestion_delta": path_delta,
            "busiest_zone_density_delta": density_delta,
        },
        "food_pressure": pressure,
        "latent_food_pressure": latent_food_pressure,
    }


def _unique_candidates(candidates: list[dict[str, Any] | None]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        candidate_id = str(candidate.get("id") or "")
        if not candidate_id or candidate_id in seen:
            continue
        seen.add(candidate_id)
        unique.append(candidate)
    return unique


def _adjudicate_negotiated_candidate(
    *,
    selected_candidate: dict[str, Any] | None,
    candidate_selection: dict[str, Any] | None,
    policy_candidates: list[dict[str, Any]],
    parsed_response: dict[str, Any],
    state_digest: dict[str, Any],
    memory_context: dict[str, Any],
) -> dict[str, Any]:
    passed = [candidate for candidate in policy_candidates if candidate.get("policy_status") == "passed"]
    by_id = {str(candidate.get("id")): candidate for candidate in passed}
    best_overall = max(passed, key=lambda item: int(item.get("score") or 0), default=None)
    food_candidates = [
        candidate
        for candidate in passed
        if _action_key(_candidate_to_action(candidate)) in FOOD_RECOVERY_ACTION_KEYS
    ]
    best_food = max(food_candidates, key=lambda item: int(item.get("score") or 0), default=None)
    ranked_challengers = [
        by_id[item]
        for item in parsed_response.get("ranked_candidate_ids", [])
        if isinstance(item, str) and item in by_id
    ][:3]
    challengers = _unique_candidates([selected_candidate, best_overall, best_food, *ranked_challengers])
    if not challengers:
        return {
            "status": "no_candidate",
            "reason": "No policy-passed candidate was available for executive adjudication.",
            "final_candidate": None,
            "final_candidate_id": None,
            "challenger_ledgers": [],
            "rejected_candidates": [],
        }

    initial = selected_candidate if isinstance(selected_candidate, dict) else best_overall
    initial_id = str(initial.get("id") or "") if isinstance(initial, dict) else None
    ledgers = [
        _candidate_utility_ledger(candidate, state_digest=state_digest, memory_context=memory_context)
        for candidate in challengers
    ]
    ledgers_by_id = {str(item.get("candidate_id")): item for item in ledgers}
    ranked_ledgers = sorted(
        ledgers,
        key=lambda item: (
            1 if item.get("constraint_status") == "passed" else 0,
            -int(item.get("constraint_violation_count") or 0),
            int(item.get("utility") or -999),
            int(item.get("counterfactual_score") or 0),
        ),
        reverse=True,
    )
    winner_ledger = ranked_ledgers[0]
    winner = by_id.get(str(winner_ledger.get("candidate_id"))) or initial
    initial_ledger = ledgers_by_id.get(
        str(initial_id),
        _candidate_utility_ledger(initial, state_digest=state_digest, memory_context=memory_context),
    )
    utility_gap = int(winner_ledger.get("utility") or 0) - int(initial_ledger.get("utility") or 0)
    pressure = _food_pressure(state_digest)
    selected_key = _action_key(_candidate_to_action(initial))
    best_food_id = best_food.get("id") if isinstance(best_food, dict) else None
    best_overall_id = best_overall.get("id") if isinstance(best_overall, dict) else None
    conflict_types: list[str] = []
    if best_overall_id and best_food_id and best_overall_id != best_food_id:
        conflict_types.append("highest_score_vs_food_specific_candidate")
    if pressure["is_warning_or_worse"] and selected_key in {"ride/reroute", "traffic/redirect_food"}:
        conflict_types.append("guest_flow_relief_vs_food_recovery")
    if str((candidate_selection or {}).get("status") or "").startswith("fallback"):
        conflict_types.append("llm_degraded_fallback_selection")

    status = "kept_ranker_selection"
    reason = "Initial candidate retained after executive utility comparison."
    final_candidate = initial
    guard: dict[str, Any] = {"status": "not_applicable"}
    if winner and str(winner.get("id")) != initial_id:
        guard = _override_food_regression_guard(selected=initial, override=winner) if isinstance(initial, dict) else {"status": "passed"}
        initial_constraints = int(initial_ledger.get("constraint_violation_count") or 0)
        winner_constraints = int(winner_ledger.get("constraint_violation_count") or 0)
        winner_constraint_passed = winner_ledger.get("constraint_status") == "passed"
        strong_utility_case = utility_gap >= (6 if conflict_types else 10)
        critical_food_block = pressure["is_critical"] and _action_key(_candidate_to_action(winner)) not in FOOD_RECOVERY_ACTION_KEYS
        if winner_constraint_passed and initial_constraints > 0:
            final_candidate = winner
            status = "constraint_first_override"
            reason = "Executive mediator rejected the initial candidate because it violated protected no-regression constraints."
        elif winner_constraint_passed and strong_utility_case and guard.get("status") == "passed" and not critical_food_block:
            final_candidate = winner
            status = "pareto_feasible_override"
            reason = "Executive mediator selected a higher-utility challenger only after protected no-regression constraints passed."
        elif strong_utility_case and guard.get("status") == "blocked":
            status = "kept_ranker_selection_food_guard"
            reason = "Higher-utility challenger was rejected because it materially worsened food backlog or ETA."
        elif critical_food_block:
            status = "kept_ranker_selection_critical_food"
            reason = "Higher-utility challenger was rejected because critical food pressure requires recovery-first action."
        elif winner_constraints > 0:
            status = "kept_ranker_selection_constraint_guard"
            reason = "Higher-utility challenger was rejected because it violated protected no-regression constraints."
        else:
            status = "kept_ranker_selection_low_utility_gap"
            reason = "Challenger utility gap was too small for executive override."

    final_id = str(final_candidate.get("id") or "") if isinstance(final_candidate, dict) else None
    rejected = []
    for ledger in ranked_ledgers:
        candidate_id = str(ledger.get("candidate_id") or "")
        if candidate_id == final_id:
            continue
        rejected.append(
            {
                "candidate_id": candidate_id,
                "utility": ledger.get("utility"),
                "counterfactual_score": ledger.get("counterfactual_score"),
                "reason": (
                    "lower executive utility than final candidate"
                    if status == "negotiated_override"
                    else "challenger rejected by food-regression guard"
                    if candidate_id == str(winner_ledger.get("candidate_id")) and guard.get("status") == "blocked"
                    else "not selected by executive mediator"
                ),
            }
        )
    return {
        "status": status,
        "reason": reason,
        "initial_candidate_id": initial_id,
        "final_candidate": final_candidate,
        "final_candidate_id": final_id,
        "winner_candidate_id": winner_ledger.get("candidate_id"),
        "utility_gap_vs_initial": utility_gap,
        "conflict_types": conflict_types,
        "memory_status": memory_context.get("status"),
        "challenger_ledgers": ranked_ledgers,
        "food_regression_guard": guard,
        "rejected_candidates": rejected,
    }


def _candidate_to_action(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(candidate, dict):
        return None
    return _allowed_action(str(candidate.get("target") or ""), str(candidate.get("action") or ""))


def _candidate_prompt_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    relative = _candidate_relative(candidate)
    counterfactual = candidate.get("counterfactual", {}) if isinstance(candidate.get("counterfactual"), dict) else {}
    secondary = counterfactual.get("secondary_risks", []) if isinstance(counterfactual.get("secondary_risks"), list) else []
    return {
        "id": candidate.get("id"),
        "target": candidate.get("target"),
        "action": candidate.get("action"),
        "policy_status": candidate.get("policy_status"),
        "score": candidate.get("score"),
        "blocked_reasons": candidate.get("policy_reasons", [])[:2],
        "deltas": {
            "sat": _relative_int(relative, "avg_satisfaction_delta"),
            "wait": _relative_int(relative, "slowest_ride_wait_delta"),
            "food": _relative_int(relative, "food_backlog_delta"),
            "eta": _relative_int(relative, "food_eta_minutes_delta"),
            "path": _relative_int(relative, "path_congestion_delta"),
            "density": _relative_int(relative, "busiest_zone_density_delta"),
        },
        "secondary_risks": [str(item)[:90] for item in secondary[:2]],
    }


def _build_gemini_candidate_ranking_prompt(
    *,
    sim_minute: int,
    state_digest: dict[str, Any],
    recent_digests: list[dict[str, Any]],
    phase: dict[str, Any],
    scenario: str,
    model_params: dict[str, Any],
    candidates: list[dict[str, Any]],
    memory_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    memory_context = memory_context or {"status": "disabled", "examples": []}
    return {
        "role": "ParkPulse policy interpreter and safe-candidate ranker",
        "task": "Return a compact JSON ranking of supplied candidate IDs. Do not invent actions.",
        "output_contract": {
            "risk_classification": {"primary_risk": "food|ride|staffing|traffic|energy|signage", "severity": "normal|p2_warning|p1_critical|p0_gridlock", "why": "max 12 words"},
            "blocked_candidate_ids": ["candidate IDs blocked by policy"],
            "ranked_candidate_ids": ["policy-passed candidate IDs in recommended order"],
            "selected_candidate_id": "one exact policy-passed candidate ID",
            "policy_evidence": ["max 2 short strings"],
            "rejected_alternatives": [{"candidate_id": "candidate ID", "reason": "max 8 words"}],
            "operator_explanation": "max 18 words",
        },
        "constraints": [
            "Return JSON only.",
            "Keep the full response under 220 words.",
            "Use candidate IDs exactly as supplied.",
            "Do not normalize, rename, expand, or infer candidate IDs.",
            "Use risk_classification.severity exactly from deterministic_risk_context.food_pressure.severity when primary_risk is food.",
            "If deterministic_risk_context.food_pressure.is_critical is true, primary_risk must be food unless a higher safety, medical, security, or emergency risk is explicitly present in the supplied state.",
            "Rank only candidates whose policy_status is passed.",
            "Never select a candidate whose policy_status is blocked.",
            "Prefer candidates with non-negative satisfaction and no material food/wait/path regression.",
            "Use candidate score as the default tiebreaker among policy-passed candidates.",
            "Use retrieved_memory_examples as prior audited lessons only. Do not copy a prior decision when the current severity, regressed metrics, or candidate deltas differ.",
            "Use cautionary_memory_examples only to notice historical tradeoff patterns. They are not similar enough to copy and must not override current candidate deltas.",
        ],
        "candidate_id_set": [candidate["id"] for candidate in candidates],
        "sim_context": {
            "sim_minute": sim_minute,
            "scenario": scenario,
            "operating_phase": phase,
            "state_digest": state_digest,
            "recent_digests": recent_digests[-4:],
            "deterministic_risk_context": {
                "food_pressure": _food_pressure(state_digest),
                "food_severity_thresholds": {
                    "p0_gridlock": "food_backlog >= 700 or food_eta_minutes >= 75",
                    "p1_critical": "food_backlog >= 400 or food_eta_minutes >= 45",
                    "p2_warning": "food_backlog >= 140 or food_eta_minutes >= 25",
                    "normal": "food_backlog < 140 and food_eta_minutes < 25",
                },
            },
	            "policy_candidates": [_candidate_prompt_summary(candidate) for candidate in candidates],
        },
        "outcome_memory_context": {
            "status": memory_context.get("status"),
            "method": memory_context.get("method"),
            "retrieved_memory_examples": memory_context.get("examples", []),
            "cautionary_memory_examples": memory_context.get("cautionary_examples", []),
            "candidate_votes": memory_context.get("candidate_votes", {}),
        },
        "model_params": model_params,
    }


def _policy_regulation_judgment(
    *,
    state_digest: dict[str, Any],
    selected_candidate: dict[str, Any] | None,
    effective_action: dict[str, Any] | None,
    policy_gate: dict[str, Any],
) -> dict[str, Any]:
    pressure = _food_pressure(state_digest)
    selected_key = _action_key(effective_action)
    selected_relative = _candidate_relative(selected_candidate)
    storm_risk = int(state_digest.get("storm_risk") or 0)
    open_callouts = int(state_digest.get("open_callouts") or 0)
    policy_refs = ["PARK-OPS-BOUNDED-ACTION", "PARK-SAFE-NO-AUTONOMOUS-RIDE-CLEARANCE"]
    blocked_authorities = [
        "ride_reopening_or_maintenance_clearance",
        "medical_diagnosis_or_emergency_command",
        "security_detention_or_enforcement",
        "refund_compensation_or_public_promise",
    ]
    findings: list[str] = []
    human_review_reasons: list[str] = []
    blocked_reasons: list[str] = []

    if pressure["is_warning_or_worse"]:
        policy_refs.append("POL-FOOD-RECOVERY-DUTY")
        findings.append(
            f"Food pressure is {pressure['severity']} with backlog {pressure['backlog']} and ETA {pressure['eta_minutes']}."
        )
    if pressure["is_critical"]:
        policy_refs.append("POL-FOOD-CRITICAL-RECOVERY-FIRST")
        if selected_key not in FOOD_RECOVERY_ACTION_KEYS and selected_key != "traffic/redirect_food":
            blocked_reasons.append("critical food pressure requires a food-throughput or food-demand action, not approval deferral")
    if selected_key == "ride/reroute":
        policy_refs.append("POL-RIDE-NO-REOPEN-AUTHORITY")
        findings.append("Ride action is limited to guest rerouting; it cannot imply reopening or maintenance clearance.")
    if selected_key.startswith("staff/"):
        policy_refs.append("POL-LABOR-CERTIFICATION-BREAKS")
        blocked_authorities.append("uncertified_staff_reassignment_or_break_violation")
        findings.append("Staff movement must preserve role certification, fatigue limits, and protected breaks.")
    if selected_key.startswith("food/") or selected_key == "traffic/redirect_food":
        policy_refs.append("POL-GUEST-COMMS-NO-PROMISES")
        findings.append("Food and guest-flow actions cannot promise inventory, refunds, queue times, or unavailable capacity.")
    if storm_risk >= 70:
        policy_refs.append("POL-WEATHER-SHELTER-BOUNDED-ACTION")
        findings.append(f"Storm risk {storm_risk} requires bounded comfort, shelter, signage, or traffic actions; emergency commands remain blocked.")
    if open_callouts >= 25 and selected_key == "staff/redeploy":
        policy_refs.append("POL-LABOR-FATIGUE-BLOCK-GENERAL-REDEPLOY")
        blocked_reasons.append(f"open callouts {open_callouts} blocks general staff redeploy; use certified food redeploy or non-labor action")
    elif open_callouts >= 25:
        policy_refs.append("POL-LABOR-FATIGUE-CONTEXT")
        findings.append(f"Open callouts {open_callouts} are policy context; they do not require approval for non-labor bounded actions.")
    if int(selected_relative.get("food_backlog_delta") or 0) > 25 or int(selected_relative.get("food_eta_minutes_delta") or 0) > 2:
        policy_refs.append("POL-SECONDARY-FOOD-REGRESSION")
        blocked_reasons.append("selected candidate materially worsens projected food backlog or ETA")

    gate_status = str(policy_gate.get("status") or "unknown")
    status = "blocked" if gate_status == "blocked" or blocked_reasons else "review_required" if human_review_reasons else "allowed"
    return {
        "status": status,
        "hard_gate_status": gate_status,
        "policy_refs": list(dict.fromkeys(policy_refs)),
        "findings": findings or ["Selected action stayed inside the bounded action catalog."],
        "human_review_required": status == "review_required",
        "human_review_reasons": human_review_reasons,
        "blocked_reasons": blocked_reasons,
        "approval_owner": "park_operations_executive" if status == "review_required" else None,
        "blocked_authorities": blocked_authorities,
        "boundary_note": "This is a policy/regulation judgment trace for the timelapse model. It is stricter than the legacy benchmark policy score, which only covered limited hard gates.",
    }


def _agent_position(agent: str, claim: str, evidence: list[str], recommendation: str, status: str = "position") -> dict[str, Any]:
    return {
        "agent": agent,
        "claim": claim,
        "evidence": evidence,
        "recommendation": recommendation,
        "status": status,
    }


def _build_ranked_decision_negotiation_trace(
    *,
    sim_minute: int,
    scenario: str,
    state_digest: dict[str, Any],
    memory_context: dict[str, Any],
    policy_candidates: list[dict[str, Any]],
    parsed_response: dict[str, Any],
    selected_candidate: dict[str, Any] | None,
    effective_action: dict[str, Any] | None,
    policy_gate: dict[str, Any],
    policy_regulation_judgment: dict[str, Any],
    executive_adjudication: dict[str, Any],
) -> dict[str, Any]:
    pressure = _food_pressure(state_digest)
    selected_id = selected_candidate.get("id") if isinstance(selected_candidate, dict) else _action_key(effective_action)
    selected_key = _action_key(effective_action)
    passed_candidates = [candidate for candidate in policy_candidates if candidate.get("policy_status") == "passed"]
    food_candidates = [
        candidate
        for candidate in passed_candidates
        if _action_key(_candidate_to_action(candidate)) in FOOD_RECOVERY_ACTION_KEYS or str(candidate.get("id", "")).startswith("traffic__")
    ]
    best_food = max(food_candidates, key=lambda item: int(item.get("score") or 0), default=None)
    best_overall = max(passed_candidates, key=lambda item: int(item.get("score") or 0), default=None)
    memory_status = str(memory_context.get("status") or "none")
    direct_memory_count = len(memory_context.get("examples", []) if isinstance(memory_context.get("examples"), list) else [])
    cautionary_count = len(
        memory_context.get("cautionary_examples", [])
        if isinstance(memory_context.get("cautionary_examples"), list)
        else []
    )
    positions = [
        _agent_position(
            "scan_agent",
            "Current state is read from the latest timelapse digest.",
            [
                f"slowest_wait={_ride_wait(state_digest)}",
                f"food_backlog={pressure['backlog']}",
                f"food_eta={pressure['eta_minutes']}",
                f"storm_risk={state_digest.get('storm_risk')}",
            ],
            "escalate to ranked action selection",
        ),
        _agent_position(
            "memory_agent",
            f"MongoDB memory status is {memory_status}.",
            [f"direct_examples={direct_memory_count}", f"cautionary_examples={cautionary_count}"],
            "use direct memory only when ready; otherwise use cautionary memory as a warning, not an override",
        ),
        _agent_position(
            "ride_ops_agent",
            "Ride and path pressure favor guest-flow relief when wait, density, or congestion is high.",
            [f"ride_wait={_ride_wait(state_digest)}", f"path_congestion={_path_congestion(state_digest)}"],
            "support ride/reroute or traffic/redirect_food only if food pressure and policy allow it",
        ),
        _agent_position(
            "food_ops_agent",
            "Food pressure can be worsened by guest-flow moves and must challenge non-food actions.",
            [f"food_severity={pressure['severity']}", f"best_food_candidate={(best_food or {}).get('id')}"],
            "prefer food throughput or demand-shedding when backlog or ETA is warning or worse",
        ),
        _agent_position(
            "staffing_agent",
            "Staff movement is useful only inside certification, fatigue, overtime, and break boundaries.",
            [f"open_callouts={state_digest.get('open_callouts')}"],
            "hold staffing actions for review when callouts are high or certification is unclear",
        ),
        _agent_position(
            "gemini_ranker",
            "Gemini ranked supplied policy-passed candidate IDs instead of inventing actions.",
            [
                f"selected_candidate={(executive_adjudication or {}).get('initial_candidate_id') or selected_id}",
                f"primary_risk={_get_nested(parsed_response, ['risk_classification', 'primary_risk'])}",
            ],
            "select the highest-fit candidate with an explanation of rejected alternatives",
            "selected",
        ),
        _agent_position(
            "executive_mediator",
            "Executive mediator compares ranker selection, deterministic best candidate, food challenger, and memory context before execution.",
            [
                f"initial_candidate={(executive_adjudication or {}).get('initial_candidate_id')}",
                f"final_candidate={(executive_adjudication or {}).get('final_candidate_id')}",
                f"utility_gap={(executive_adjudication or {}).get('utility_gap_vs_initial')}",
            ],
            "select final candidate from policy-passed challengers and record rejected alternatives",
            (executive_adjudication or {}).get("status", "not_run"),
        ),
        _agent_position(
            "policy_regulation_judge",
            f"Policy/regulation status is {policy_regulation_judgment['status']}.",
            policy_regulation_judgment.get("policy_refs", [])[:5],
            "allow, block, or require human approval before execution",
            policy_regulation_judgment["status"],
        ),
    ]
    conflicts: list[dict[str, Any]] = []
    if pressure["is_warning_or_worse"] and selected_key in {"ride/reroute", "traffic/redirect_food"}:
        conflicts.append(
            {
                "conflict": "guest_flow_relief_vs_food_recovery",
                "agents": ["ride_ops_agent", "food_ops_agent", "policy_regulation_judge"],
                "challenge": "Guest-flow action may improve wait while delaying food recovery.",
                "resolution": "Require food regression check and human review if projected food backlog or ETA worsens.",
            }
        )
    if best_overall and best_food and best_overall.get("id") != best_food.get("id"):
        conflicts.append(
            {
                "conflict": "highest_score_vs_food_specific_candidate",
                "agents": ["gemini_ranker", "food_ops_agent", "executive_bridge"],
                "challenge": f"Top overall candidate {best_overall.get('id')} differs from food candidate {best_food.get('id')}.",
                "resolution": "Executive bridge must compare satisfaction/wait gains against food backlog and ETA risk.",
            }
        )
    if policy_regulation_judgment.get("human_review_required"):
        conflicts.append(
            {
                "conflict": "automation_vs_human_authority",
                "agents": ["policy_regulation_judge", "executive_bridge"],
                "challenge": "; ".join(policy_regulation_judgment.get("human_review_reasons", [])),
                "resolution": "Hold final approval for park_operations_executive.",
            }
        )
    executive_status = (
        "blocked"
        if policy_regulation_judgment["status"] == "blocked"
        else "human_review_required"
        if policy_regulation_judgment["status"] == "review_required"
        else "approved_for_bounded_sim_execution"
    )
    return {
        "mode": "ranked_timelapse_structured_negotiation_v1",
        "sim_minute": sim_minute,
        "scenario": scenario,
        "selected_candidate_id": selected_id,
        "selected_action": effective_action,
        "positions": positions,
        "conflicts": conflicts,
        "rounds": [
            {"round": 1, "name": "local_positions", "positions": positions[:5]},
            {
                "round": 2,
                "name": "llm_candidate_ranking",
                "ranked_candidate_ids": parsed_response.get("ranked_candidate_ids", []),
                "selected_candidate_id": (executive_adjudication or {}).get("initial_candidate_id") or selected_id,
                "operator_explanation": parsed_response.get("operator_explanation"),
            },
            {"round": 3, "name": "cross_agent_challenges", "conflicts": conflicts},
            {
                "round": 4,
                "name": "executive_mediation",
                "adjudication": {
                    key: value
                    for key, value in (executive_adjudication or {}).items()
                    if key != "final_candidate"
                },
            },
            {"round": 5, "name": "policy_regulation_judgment", "judgment": policy_regulation_judgment},
            {
                "round": 6,
                "name": "executive_resolution",
                "decision": executive_status,
                "reason": (
                    "Hard gate blocked the action."
                    if executive_status == "blocked"
                    else "Human executive review is required by policy/regulation judgment."
                    if executive_status == "human_review_required"
                    else "Bounded simulated execution can proceed; this is not physical dispatch approval."
                ),
            },
        ],
        "final_executive_decision": {
            "status": executive_status,
            "selected_candidate_id": selected_id,
            "selected_action": effective_action,
            "mediation_status": (executive_adjudication or {}).get("status"),
            "mediation_reason": (executive_adjudication or {}).get("reason"),
            "rejected_candidates": (executive_adjudication or {}).get("rejected_candidates", []),
            "not_physical_dispatch": True,
        },
    }


def _get_nested(value: dict[str, Any], path: list[str]) -> Any:
    current: Any = value
    for part in path:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _runtime_memory_query(*, scenario: str, state_digest: dict[str, Any], candidates: list[dict[str, Any]]) -> str:
    pressure = _food_pressure(state_digest)
    slowest = state_digest.get("slowest_ride", {}) if isinstance(state_digest.get("slowest_ride"), dict) else {}
    best_candidates = sorted(
        [candidate for candidate in candidates if isinstance(candidate, dict) and candidate.get("policy_status") == "passed"],
        key=lambda candidate: int(candidate.get("score") or 0),
        reverse=True,
    )[:5]
    candidate_text = " ".join(
        " ".join(
            str(part)
            for part in (
                candidate.get("id"),
                candidate.get("action"),
                candidate.get("score"),
                _candidate_relative(candidate),
                candidate.get("secondary_risks", []),
            )
        )
        for candidate in best_candidates
    )
    return " ".join(
        str(part)
        for part in (
            scenario,
            "timelapse_mediation_outcome mediated executive_adjudication negotiated_compromise_override",
            pressure.get("severity"),
            state_digest.get("food_backlog"),
            state_digest.get("food_eta_minutes"),
            slowest.get("waitMins"),
            _zone_density(state_digest),
            _path_congestion(state_digest),
            state_digest.get("open_callouts"),
            candidate_text,
        )
        if part is not None
    )


RUNTIME_MEMORY_METRICS = [
    "avg_satisfaction_delta",
    "slowest_ride_wait_delta",
    "food_backlog_delta",
    "food_eta_minutes_delta",
    "busiest_zone_density_delta",
    "path_congestion_delta",
    "open_callouts_delta",
    "grid_load_delta",
]

RUNTIME_MEMORY_NORMALIZERS = {
    "avg_satisfaction_delta": 4.0,
    "slowest_ride_wait_delta": 20.0,
    "food_backlog_delta": 100.0,
    "food_eta_minutes_delta": 10.0,
    "busiest_zone_density_delta": 12.0,
    "path_congestion_delta": 18.0,
    "open_callouts_delta": 5.0,
    "grid_load_delta": 8.0,
}


def _float_value(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _candidate_by_id(candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(candidate.get("id")): candidate
        for candidate in candidates
        if isinstance(candidate, dict) and candidate.get("policy_status") == "passed" and candidate.get("id")
    }


def _memory_candidate_summaries(row: dict[str, Any]) -> list[dict[str, Any]]:
    payload = row.get("input_payload", {}) if isinstance(row.get("input_payload"), dict) else {}
    summaries = payload.get("candidate_summaries", []) if isinstance(payload.get("candidate_summaries"), list) else []
    return [item for item in summaries if isinstance(item, dict)]


def _memory_candidate_deltas(row: dict[str, Any], candidate_id: str) -> dict[str, float]:
    expected = row.get("expected_output", {}) if isinstance(row.get("expected_output"), dict) else {}
    if candidate_id == str(expected.get("ideal_candidate_id") or "") and isinstance(expected.get("ideal_candidate_deltas"), dict):
        return {key: _float_value(value) for key, value in expected["ideal_candidate_deltas"].items()}
    for candidate in _memory_candidate_summaries(row):
        if str(candidate.get("id") or "") == candidate_id and isinstance(candidate.get("deltas"), dict):
            return {key: _float_value(value) for key, value in candidate["deltas"].items()}
    return {}


def _memory_state_digest(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("input_payload", {}) if isinstance(row.get("input_payload"), dict) else {}
    digest = payload.get("state_digest", {}) if isinstance(payload.get("state_digest"), dict) else {}
    if digest:
        return digest
    summaries = _memory_candidate_summaries(row)
    if summaries and isinstance(summaries[0].get("risk_context"), dict):
        risk = summaries[0]["risk_context"]
        pressure = risk.get("food_pressure", {}) if isinstance(risk.get("food_pressure"), dict) else {}
        return {
            "food_backlog": pressure.get("backlog"),
            "food_eta_minutes": pressure.get("eta_minutes"),
            "slowest_ride": {"waitMins": risk.get("ride_wait_minutes")},
            "busiest_zone": {"density": risk.get("busiest_zone_density")},
            "most_congested_path": {"congestionLevel": risk.get("path_congestion")},
        }
    return {}


def _state_similarity(row: dict[str, Any], state_digest: dict[str, Any]) -> float:
    memory_digest = _memory_state_digest(row)
    current_slowest = state_digest.get("slowest_ride", {}) if isinstance(state_digest.get("slowest_ride"), dict) else {}
    memory_slowest = memory_digest.get("slowest_ride", {}) if isinstance(memory_digest.get("slowest_ride"), dict) else {}
    current_zone = state_digest.get("busiest_zone", {}) if isinstance(state_digest.get("busiest_zone"), dict) else {}
    memory_zone = memory_digest.get("busiest_zone", {}) if isinstance(memory_digest.get("busiest_zone"), dict) else {}
    current_path = state_digest.get("most_congested_path", {}) if isinstance(state_digest.get("most_congested_path"), dict) else {}
    memory_path = memory_digest.get("most_congested_path", {}) if isinstance(memory_digest.get("most_congested_path"), dict) else {}
    comparisons = [
        (state_digest.get("food_backlog"), memory_digest.get("food_backlog"), 250.0),
        (state_digest.get("food_eta_minutes"), memory_digest.get("food_eta_minutes"), 25.0),
        (current_slowest.get("waitMins"), memory_slowest.get("waitMins"), 40.0),
        (current_zone.get("density"), memory_zone.get("density"), 20.0),
        (current_path.get("congestionLevel"), memory_path.get("congestionLevel"), 25.0),
    ]
    distances = [
        min(1.0, abs(_float_value(current) - _float_value(memory)) / normalizer)
        for current, memory, normalizer in comparisons
        if current is not None and memory is not None
    ]
    if not distances:
        return 0.5
    return max(0.0, 1.0 - (sum(distances) / len(distances)))


def _delta_similarity(row: dict[str, Any], current_candidate: dict[str, Any], candidate_id: str) -> float:
    memory_deltas = _memory_candidate_deltas(row, candidate_id)
    current_deltas = {key: _float_value(value) for key, value in _candidate_relative(current_candidate).items()}
    distances: list[float] = []
    for metric in RUNTIME_MEMORY_METRICS:
        if metric not in memory_deltas or metric not in current_deltas:
            continue
        normalizer = RUNTIME_MEMORY_NORMALIZERS.get(metric, 10.0)
        distances.append(min(1.0, abs(current_deltas[metric] - memory_deltas[metric]) / normalizer))
    if not distances:
        return 0.0
    return max(0.0, 1.0 - (sum(distances) / len(distances)))


def _score_runtime_memory_example(row: dict[str, Any], *, state_digest: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    expected = row.get("expected_output", {}) if isinstance(row.get("expected_output"), dict) else {}
    pressure = _food_pressure(state_digest)
    severity = str(expected.get("deterministic_food_severity") or row.get("foodSeverity") or "")
    ideal_id = str(expected.get("ideal_candidate_id") or row.get("idealCandidateId") or "")
    current_candidates = _candidate_by_id(candidates)
    reasons: list[str] = []
    if str(row.get("split") or "") != "train":
        return {"accepted": False, "score": 0.0, "reasons": ["not_train_split"]}
    if severity != pressure["severity"]:
        return {"accepted": False, "score": 0.0, "reasons": [f"severity_mismatch:{severity}:{pressure['severity']}"]}
    if ideal_id not in current_candidates:
        return {"accepted": False, "score": 0.0, "reasons": [f"ideal_candidate_not_currently_passed:{ideal_id}"]}
    reward_score = _float_value((row.get("reward", {}) if isinstance(row.get("reward"), dict) else {}).get("score") or row.get("rewardScore"))
    if reward_score < 90:
        return {"accepted": False, "score": 0.0, "reasons": [f"low_reward:{reward_score:g}"]}
    state_score = _state_similarity(row, state_digest)
    delta_score = _delta_similarity(row, current_candidates[ideal_id], ideal_id)
    combined = round((state_score * 0.45) + (delta_score * 0.55), 3)
    if state_score < 0.35:
        reasons.append(f"weak_state_similarity:{state_score:.3f}")
    if delta_score < 0.55:
        reasons.append(f"weak_delta_similarity:{delta_score:.3f}")
    if combined < 0.55 or reasons:
        return {
            "accepted": False,
            "score": combined,
            "state_similarity": round(state_score, 3),
            "delta_similarity": round(delta_score, 3),
            "ideal_candidate_id": ideal_id,
            "reasons": reasons or ["weak_combined_similarity"],
        }
    return {
        "accepted": True,
        "score": combined,
        "state_similarity": round(state_score, 3),
        "delta_similarity": round(delta_score, 3),
        "ideal_candidate_id": ideal_id,
        "reasons": ["accepted"],
    }


def _severity_memory_similarity(memory_severity: str, current_severity: str) -> float:
    if memory_severity == current_severity:
        return 1.0
    warning_or_worse = {"p2_warning", "p1_critical", "p0_gridlock"}
    if memory_severity in warning_or_worse and current_severity in warning_or_worse:
        return 0.65
    if memory_severity == "normal" or current_severity == "normal":
        return 0.25
    return 0.4


def _score_cautionary_runtime_memory_example(row: dict[str, Any], *, state_digest: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    expected = row.get("expected_output", {}) if isinstance(row.get("expected_output"), dict) else {}
    pressure = _food_pressure(state_digest)
    severity = str(expected.get("deterministic_food_severity") or row.get("foodSeverity") or "")
    ideal_id = str(expected.get("ideal_candidate_id") or row.get("idealCandidateId") or "")
    current_candidates = _candidate_by_id(candidates)
    if str(row.get("split") or "") != "train":
        return {"accepted": False, "score": 0.0, "reasons": ["not_train_split"]}
    if ideal_id not in current_candidates:
        return {"accepted": False, "score": 0.0, "reasons": [f"ideal_candidate_not_currently_passed:{ideal_id}"]}
    reward_score = _float_value((row.get("reward", {}) if isinstance(row.get("reward"), dict) else {}).get("score") or row.get("rewardScore"))
    if reward_score < 85:
        return {"accepted": False, "score": 0.0, "reasons": [f"low_reward:{reward_score:g}"]}
    state_score = _state_similarity(row, state_digest)
    delta_score = _delta_similarity(row, current_candidates[ideal_id], ideal_id)
    severity_score = _severity_memory_similarity(severity, pressure["severity"])
    combined = round((state_score * 0.30) + (delta_score * 0.45) + (severity_score * 0.25), 3)
    reasons = []
    if severity != pressure["severity"]:
        reasons.append(f"severity_mismatch:{severity}:{pressure['severity']}")
    if state_score < 0.25:
        reasons.append(f"weak_state_similarity:{state_score:.3f}")
    if delta_score < 0.35:
        reasons.append(f"weak_delta_similarity:{delta_score:.3f}")
    if combined < 0.35:
        reasons.append(f"weak_cautionary_similarity:{combined:.3f}")
    return {
        "accepted": not any(reason.startswith("weak_cautionary_similarity") for reason in reasons),
        "score": combined,
        "state_similarity": round(state_score, 3),
        "delta_similarity": round(delta_score, 3),
        "severity_similarity": round(severity_score, 3),
        "ideal_candidate_id": ideal_id,
        "reasons": reasons or ["cautionary_match"],
    }


def _metric_aware_memory_guard(
    relevance: dict[str, Any],
    *,
    state_digest: dict[str, Any],
    recent_digests: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    ideal_id = str(relevance.get("ideal_candidate_id") or "")
    current = _candidate_by_id(candidates).get(ideal_id)
    if not current:
        return {"status": "blocked", "reason": "ideal_candidate_not_currently_passed"}
    trend = _food_trend_risk(state_digest, recent_digests)
    relative = _candidate_relative(current)
    food_delta = _relative_int(relative, "food_backlog_delta")
    eta_delta = _relative_int(relative, "food_eta_minutes_delta")
    candidate_family = _action_family(_candidate_to_action(current))
    food_recovery = food_delta <= -20 or eta_delta <= -2 or candidate_family == "food_service"
    if trend["requires_food_protection"] and candidate_family == "guest_flow" and not food_recovery:
        return {
            "status": "blocked",
            "reason": "food_trend_blocks_guest_flow_cautionary_memory",
            "food_trend": trend,
            "candidate_family": candidate_family,
            "candidate_food_backlog_delta": food_delta,
            "candidate_food_eta_delta": eta_delta,
        }
    if trend["is_critical"] and not food_recovery:
        return {
            "status": "blocked",
            "reason": "critical_food_requires_recovery_memory",
            "food_trend": trend,
            "candidate_family": candidate_family,
            "candidate_food_backlog_delta": food_delta,
            "candidate_food_eta_delta": eta_delta,
        }
    return {
        "status": "passed",
        "reason": "memory passed metric-aware food guard",
        "food_trend": trend,
        "candidate_family": candidate_family,
        "candidate_food_backlog_delta": food_delta,
        "candidate_food_eta_delta": eta_delta,
    }


def _compact_runtime_memory_example(row: dict[str, Any], relevance: dict[str, Any]) -> dict[str, Any]:
    expected = row.get("expected_output", {}) if isinstance(row.get("expected_output"), dict) else {}
    reward = row.get("reward", {}) if isinstance(row.get("reward"), dict) else {}
    return {
        "id": row.get("id") or row.get("_id"),
        "scenario": row.get("scenario") or row.get("scenarioKey"),
        "split": row.get("split"),
        "food_severity": expected.get("deterministic_food_severity") or row.get("foodSeverity"),
        "case_metric_regressions": expected.get("case_metric_regressions") or row.get("caseMetricRegressions", []),
        "ideal_candidate_id": expected.get("ideal_candidate_id") or row.get("idealCandidateId"),
        "ideal_action": expected.get("ideal_action"),
        "reward_score": reward.get("score") or row.get("rewardScore"),
        "quality_issues": reward.get("issues") or row.get("qualityIssues", []),
        "relevance_score": relevance.get("score"),
        "state_similarity": relevance.get("state_similarity"),
        "delta_similarity": relevance.get("delta_similarity"),
        "severity_similarity": relevance.get("severity_similarity"),
        "metric_guard": relevance.get("metric_guard"),
        "lesson": "Select the policy-passed candidate that repairs the metrics that actually regressed, then explain the rejected high-score alternative.",
    }


def _compact_cautionary_runtime_memory_example(row: dict[str, Any], relevance: dict[str, Any]) -> dict[str, Any]:
    compact = _compact_runtime_memory_example(row, relevance)
    compact["memory_role"] = "cautionary_tradeoff_pattern"
    compact["why_cautionary"] = relevance.get("reasons", [])
    compact["lesson"] = (
        "This prior case is related but not similar enough to copy. Use it only to check whether the current choice could repeat a known tradeoff."
    )
    return compact


def _retrieve_runtime_memory(
    *,
    enabled: bool,
    scenario: str,
    state_digest: dict[str, Any],
    recent_digests: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    limit: int,
) -> dict[str, Any]:
    if not enabled:
        return {"status": "disabled", "examples": []}
    try:
        from mongo_memory import retrieve_timelapse_model_memory

        result = retrieve_timelapse_model_memory(
            _runtime_memory_query(scenario=scenario, state_digest=state_digest, candidates=candidates),
            scenario_key=scenario,
            limit=max(limit * 8, limit + 12),
        )
        mediator_result = retrieve_timelapse_model_memory(
            " ".join(
                str(part)
                for part in (
                    "timelapse_mediation_outcome",
                    "executive_adjudication",
                    "negotiated_compromise_override",
                    scenario,
                    _food_pressure(state_digest).get("severity"),
                    " ".join(str(candidate.get("id")) for candidate in candidates[:6] if isinstance(candidate, dict)),
                )
                if part
            ),
            scenario_key=scenario,
            limit=max(limit * 4, limit + 6),
        )
        scored_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
        mediator_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
        cautionary_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
        rejected_reasons: list[str] = []
        for row in result.get("examples", []):
            if not isinstance(row, dict):
                continue
            relevance = _score_runtime_memory_example(row, state_digest=state_digest, candidates=candidates)
            if relevance.get("accepted") is True:
                guard = _metric_aware_memory_guard(
                    relevance,
                    state_digest=state_digest,
                    recent_digests=recent_digests,
                    candidates=candidates,
                )
                relevance["metric_guard"] = guard
                if guard.get("status") == "passed":
                    scored_rows.append((row, relevance))
                else:
                    rejected_reasons.append(str(guard.get("reason") or "metric_guard_blocked"))
            else:
                rejected_reasons.extend(str(item) for item in relevance.get("reasons", [])[:2])
                cautionary = _score_cautionary_runtime_memory_example(row, state_digest=state_digest, candidates=candidates)
                if cautionary.get("accepted") is True:
                    guard = _metric_aware_memory_guard(
                        cautionary,
                        state_digest=state_digest,
                        recent_digests=recent_digests,
                        candidates=candidates,
                    )
                    cautionary["metric_guard"] = guard
                    if guard.get("status") == "passed":
                        cautionary_rows.append((row, cautionary))
                    else:
                        rejected_reasons.append(str(guard.get("reason") or "metric_guard_blocked"))
        for row in mediator_result.get("examples", []):
            if not isinstance(row, dict) or row.get("source") != "timelapse_mediation_outcome":
                continue
            relevance = _score_runtime_memory_example(row, state_digest=state_digest, candidates=candidates)
            if relevance.get("accepted") is not True:
                rejected_reasons.extend(str(item) for item in relevance.get("reasons", [])[:2])
                cautionary = _score_cautionary_runtime_memory_example(row, state_digest=state_digest, candidates=candidates)
                if cautionary.get("accepted") is True:
                    relevance = cautionary
                else:
                    continue
            guard = _metric_aware_memory_guard(
                relevance,
                state_digest=state_digest,
                recent_digests=recent_digests,
                candidates=candidates,
            )
            relevance["metric_guard"] = guard
            if guard.get("status") == "passed":
                mediator_rows.append((row, relevance))
            else:
                rejected_reasons.append(str(guard.get("reason") or "mediator_metric_guard_blocked"))
        scored_rows.sort(key=lambda item: _float_value(item[1].get("score")), reverse=True)
        mediator_rows.sort(key=lambda item: _float_value(item[1].get("score")), reverse=True)
        cautionary_rows.sort(key=lambda item: _float_value(item[1].get("score")), reverse=True)
        candidate_votes: dict[str, int] = {}
        for _, relevance in scored_rows[: max(limit, 1)]:
            ideal_id = str(relevance.get("ideal_candidate_id") or "")
            if ideal_id:
                candidate_votes[ideal_id] = candidate_votes.get(ideal_id, 0) + 1
        if scored_rows and len(candidate_votes) > 1:
            top_votes = max(candidate_votes.values())
            if top_votes / max(1, sum(candidate_votes.values())) < 0.67:
                return {
                    "status": "cautionary_conflicting_memory",
                    "method": result.get("method"),
                    "mode": result.get("mode"),
                    "connected": result.get("connected"),
                    "query": result.get("query"),
                    "examples": [],
                    "cautionary_examples": [
                        _compact_cautionary_runtime_memory_example(row, relevance)
                        for row, relevance in [item for item in scored_rows[:limit] if item[1].get("ideal_candidate_id")]
                    ],
                    "raw_count": result.get("count", 0),
                    "accepted_count": len(scored_rows),
                    "cautionary_count": len(scored_rows),
                    "candidate_votes": candidate_votes,
                    "rejected_reason_sample": rejected_reasons[:6],
                }
        examples = [_compact_runtime_memory_example(row, relevance) for row, relevance in scored_rows[:limit]]
        mediator_examples = [
            {
                **_compact_runtime_memory_example(row, relevance),
                "memory_role": "mediator_outcome_prior",
                "lesson": "Prior mediated outcome: use as a utility prior only when current state severity and candidate deltas match.",
            }
            for row, relevance in mediator_rows[:limit]
        ]
        cautionary_examples = [_compact_cautionary_runtime_memory_example(row, relevance) for row, relevance in cautionary_rows[:limit]]
        status = (
            "ready"
            if examples or mediator_examples
            else "cautionary_only"
            if cautionary_examples
            else "abstained_low_similarity"
        )
        return {
            "status": status,
            "method": result.get("method"),
            "mode": result.get("mode"),
            "connected": result.get("connected"),
            "query": result.get("query"),
            "examples": examples,
            "mediator_examples": mediator_examples,
            "cautionary_examples": cautionary_examples,
            "raw_count": result.get("count", 0),
            "mediator_raw_count": mediator_result.get("count", 0),
            "accepted_count": len(scored_rows),
            "mediator_accepted_count": len(mediator_rows),
            "cautionary_count": len(cautionary_rows),
            "candidate_votes": candidate_votes,
            "rejected_reason_sample": rejected_reasons[:6],
        }
    except Exception as error:
        return {"status": "error", "error": str(error)[:500], "examples": []}


def _stable_example_id(prefix: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return f"{prefix}_{hashlib.sha1(encoded).hexdigest()[:16]}"


def _mediation_metric_regressions(before_digest: dict[str, Any], after_digest: dict[str, Any]) -> list[str]:
    regressions: list[str] = []
    if int(after_digest.get("avg_satisfaction") or 0) < int(before_digest.get("avg_satisfaction") or 0):
        regressions.append("satisfaction")
    if _ride_wait(after_digest) > _ride_wait(before_digest):
        regressions.append("slowest_ride_wait")
    if int(after_digest.get("food_backlog") or 0) > int(before_digest.get("food_backlog") or 0):
        regressions.append("food_backlog")
    if int(after_digest.get("food_eta_minutes") or 0) > int(before_digest.get("food_eta_minutes") or 0):
        regressions.append("food_eta_minutes")
    if _path_congestion(after_digest) > _path_congestion(before_digest):
        regressions.append("path_congestion")
    return regressions


def _mediation_reward(row: dict[str, Any]) -> tuple[int, list[str]]:
    issues: list[str] = []
    reward = 92
    adjudication = row.get("executive_adjudication", {}) if isinstance(row.get("executive_adjudication"), dict) else {}
    policy = row.get("policy_regulation_judgment", {}) if isinstance(row.get("policy_regulation_judgment"), dict) else {}
    execution = row.get("execution", {}) if isinstance(row.get("execution"), dict) else {}
    if row.get("status") != "success":
        reward -= 25
        issues.append(str(row.get("status") or "model_status_not_success"))
    if execution.get("status") != "success":
        reward -= 20
        issues.append(str(execution.get("status") or "execution_not_success"))
    if policy.get("status") != "allowed":
        reward -= 30
        issues.append(f"policy_{policy.get('status') or 'unknown'}")
    if adjudication.get("status") == "negotiated_compromise_override":
        reward += min(8, max(0, int(adjudication.get("utility_gap_vs_initial") or 0)) // 5)
    elif adjudication.get("status") == "negotiated_override":
        reward += min(6, max(0, int(adjudication.get("utility_gap_vs_initial") or 0)) // 6)
    final_candidate = row.get("selected_policy_candidate", {}) if isinstance(row.get("selected_policy_candidate"), dict) else {}
    relative = _candidate_relative(final_candidate)
    if _relative_int(relative, "food_backlog_delta") > 25 or _relative_int(relative, "food_eta_minutes_delta") > 2:
        reward -= 18
        issues.append("final_candidate_projected_food_regression")
    if _relative_int(relative, "slowest_ride_wait_delta") > 10:
        reward -= 12
        issues.append("final_candidate_projected_wait_regression")
    return max(0, min(100, reward)), issues


def _build_mediation_memory_examples(gemini_rows: list[dict[str, Any]], *, source_run_id: str) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for row in gemini_rows:
        adjudication = row.get("executive_adjudication", {}) if isinstance(row.get("executive_adjudication"), dict) else {}
        final_candidate = row.get("selected_policy_candidate", {}) if isinstance(row.get("selected_policy_candidate"), dict) else {}
        policy_candidates = row.get("policy_candidates", []) if isinstance(row.get("policy_candidates"), list) else []
        final_id = str(adjudication.get("final_candidate_id") or final_candidate.get("id") or "")
        if not final_id or not final_candidate:
            continue
        if adjudication.get("status") not in {"negotiated_override", "negotiated_compromise_override", "kept_ranker_selection"}:
            continue
        reward_score, issues = _mediation_reward(row)
        if reward_score < 88:
            continue
        before_digest = row.get("before_digest", {}) if isinstance(row.get("before_digest"), dict) else {}
        after_digest = row.get("after_digest", {}) if isinstance(row.get("after_digest"), dict) else {}
        expected_output = {
            "ideal_candidate_id": final_id,
            "ideal_action": _action_key(_candidate_to_action(final_candidate)),
            "ideal_candidate_deltas": {
                key: _float_value(value)
                for key, value in _candidate_relative(final_candidate).items()
                if key in RUNTIME_MEMORY_METRICS
            },
            "final_selected_candidate_id": final_id,
            "final_action": _action_key(row.get("allowed_action") if isinstance(row.get("allowed_action"), dict) else None),
            "deterministic_food_severity": _food_pressure(before_digest).get("severity"),
            "case_metric_regressions": _mediation_metric_regressions(before_digest, after_digest),
            "mediation_status": adjudication.get("status"),
            "initial_candidate_id": adjudication.get("initial_candidate_id"),
            "utility_gap_vs_initial": adjudication.get("utility_gap_vs_initial"),
            "reward_score": reward_score,
        }
        input_payload = {
            "state_digest": before_digest,
            "candidate_summaries": [
                _candidate_summary(candidate)
                for candidate in policy_candidates
                if isinstance(candidate, dict)
            ],
            "memory_context_status": (row.get("memory_context", {}) if isinstance(row.get("memory_context"), dict) else {}).get("status"),
            "executive_adjudication": {
                key: value
                for key, value in adjudication.items()
                if key != "final_candidate"
            },
        }
        base = {
            "scenario": row.get("scenario"),
            "split": "train",
            "source": "timelapse_mediation_outcome",
            "source_run_id": source_run_id,
            "sim_minute": row.get("sim_minute"),
            "input_payload": input_payload,
            "expected_output": expected_output,
            "reward": {
                "score": reward_score,
                "issues": issues,
                "lesson": "Use mediated override outcomes only when current candidate deltas and food severity are similar.",
            },
            "created_at": _now_iso(),
        }
        base["id"] = _stable_example_id("timelapse_mediation", base)
        examples.append(base)
    return examples


def _record_mediation_memory_examples(
    *,
    enabled: bool,
    examples: list[dict[str, Any]],
    source_manifest: str,
) -> dict[str, Any]:
    if not enabled:
        return {"status": "disabled", "storedCount": 0}
    if not examples:
        return {"status": "skipped", "reason": "no_high_confidence_mediation_examples", "storedCount": 0}
    try:
        from mongo_memory import record_timelapse_model_examples

        result = record_timelapse_model_examples(examples, source_manifest=source_manifest)
        return {
            **result,
            "exampleIds": [example.get("id") for example in examples[:12]],
        }
    except Exception as error:
        return {"status": "error", "error": str(error)[:500], "storedCount": 0}


def _select_ranked_candidate(parsed: dict[str, Any], candidates: list[dict[str, Any]], score_gap_override: int = 10) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    by_id = {str(candidate.get("id")): candidate for candidate in candidates}
    passed_ids = {str(candidate.get("id")) for candidate in candidates if candidate.get("policy_status") == "passed"}
    selected_id = str(parsed.get("selected_candidate_id") or "")
    ranked_ids = [str(item) for item in parsed.get("ranked_candidate_ids", []) if isinstance(item, str)]
    invalid_ranked_ids = [item for item in ranked_ids if item not in by_id]
    ranked_blocked_ids = [item for item in ranked_ids if item in by_id and item not in passed_ids]
    selected = by_id.get(selected_id)
    best = _best_policy_candidate(candidates)
    best_score = int(best.get("score") or 0) if isinstance(best, dict) else 0

    if selected_id in passed_ids and selected:
        selected_score = int(selected.get("score") or 0)
        if best and str(best.get("id")) != selected_id and best_score - selected_score >= score_gap_override:
            guard = _override_food_regression_guard(selected=selected, override=best)
            if guard.get("status") == "blocked":
                return selected, {
                    "status": "score_gap_override_blocked_by_pareto_guard",
                    "reason": guard.get("reason"),
                    "selected_candidate_id": selected_id,
                    "selected_candidate_score": selected_score,
                    "blocked_override_candidate_id": best.get("id"),
                    "blocked_override_candidate_score": best_score,
                    "score_gap_override_threshold": score_gap_override,
                    "pareto_guard": guard,
                    "ranked_candidate_ids": ranked_ids,
                    "invalid_ranked_candidate_ids": invalid_ranked_ids,
                    "ranked_blocked_candidate_ids": ranked_blocked_ids,
                }
            return best, {
                "status": "score_gap_override",
                "reason": "Gemini selected an exact policy-passed candidate, but deterministic counterfactual score gap exceeded the override threshold.",
                "selected_candidate_id": selected_id,
                "selected_candidate_score": selected_score,
                "override_candidate_id": best.get("id"),
                "override_candidate_score": best_score,
                "score_gap_override_threshold": score_gap_override,
                "pareto_guard": guard,
                "ranked_candidate_ids": ranked_ids,
                "invalid_ranked_candidate_ids": invalid_ranked_ids,
                "ranked_blocked_candidate_ids": ranked_blocked_ids,
            }
        return selected, {
            "status": "passed",
            "reason": "Gemini selected an exact policy-passed candidate ID.",
            "selected_candidate_id": selected_id,
            "selected_candidate_score": selected_score,
            "ranked_candidate_ids": ranked_ids,
            "invalid_ranked_candidate_ids": invalid_ranked_ids,
            "ranked_blocked_candidate_ids": ranked_blocked_ids,
        }

    fallback = best
    return fallback, {
        "status": "fallback",
        "reason": "Gemini did not select an exact policy-passed candidate ID; using highest-scored policy-passed candidate.",
        "selected_candidate_id": selected_id or None,
        "fallback_candidate_id": fallback.get("id") if fallback else None,
        "ranked_candidate_ids": ranked_ids,
        "invalid_ranked_candidate_ids": invalid_ranked_ids,
        "ranked_blocked_candidate_ids": ranked_blocked_ids,
    }


def _phase_info(state: dict[str, Any]) -> dict[str, Any]:
    clock = state.get("operatingClock", {}) if isinstance(state.get("operatingClock"), dict) else {}
    phase = clock.get("phase", {}) if isinstance(clock.get("phase"), dict) else {}
    return {
        "id": phase.get("id"),
        "label": phase.get("label"),
        "is_open_to_guests": phase.get("isOpenToGuests") is True,
        "demand_pressure_pct": phase.get("demandPressurePct"),
        "reason": phase.get("reason"),
    }


def _build_gemini_operating_prompt(
    *,
    sim_minute: int,
    state_digest: dict[str, Any],
    recent_digests: list[dict[str, Any]],
    phase: dict[str, Any],
    scenario: str,
    model_params: dict[str, Any],
) -> dict[str, Any]:
    return {
        "role": "ParkPulse bounded park operations agent",
        "task": "Choose exactly one bounded operational action for the current simulated park state.",
        "output_contract": {
            "selected_action": {"target": "one allowed target", "action": "one allowed action"},
            "rationale": "short operational reason using only supplied state",
            "policy_status": "allowed | hold",
            "confidence": 0.0,
            "expected_effect": {
                "metric": "wait | density | staffing | food | energy | signage",
                "direction": "improve | hold | watch",
            },
            "receiver_payload": {
                "audience": "internal operator team only",
                "message": "short internal instruction",
            },
        },
        "constraints": [
            "Return JSON only.",
            "Use only the supplied state digest and recent trend.",
            "Hard priority rule: if food_backlog >= 400 or food_eta_minutes >= 45, food is critical and ride/reroute must not be selected unless food pressure is explicitly stabilized first.",
            "Hard gridlock rule: if food_backlog >= 700 or food_eta_minutes >= 75, select a food, staff, or traffic action before any ride action.",
            "Diversity rule: do not repeat ride/reroute more than two consecutive decision slots.",
            "Do not claim real park connectivity.",
            "Do not automate ride safety, security enforcement, medical diagnosis, or public guest messaging.",
            "If no action is justified, choose signage/update with policy_status hold and explain the watch condition.",
        ],
        "allowed_actions": ALLOWED_GEMINI_ACTIONS,
        "sim_context": {
            "sim_minute": sim_minute,
            "scenario": scenario,
            "operating_phase": phase,
            "state_digest": state_digest,
            "recent_digests": recent_digests[-4:],
        },
        "model_params": model_params,
    }


def _cost_estimate(
    *,
    elapsed_seconds: float,
    storage_bytes: int,
    sim_minutes: int,
    llm_interval_minutes: int,
    input_tokens_per_llm: int,
    output_tokens_per_llm: int,
    cloud_run_vcpu: float,
    cloud_run_gib: float,
    api_tick_requests: bool,
    llm_call_count: int | None = None,
) -> dict[str, Any]:
    llm_calls = sim_minutes // max(1, llm_interval_minutes) if llm_call_count is None else max(0, int(llm_call_count))
    request_count = sim_minutes if api_tick_requests else 1

    # Public list prices change; keep these configurable and visible in the report.
    cloud_run_vcpu_second_usd = float(os.getenv("PARKPULSE_COST_CLOUD_RUN_VCPU_SECOND_USD", "0.000024"))
    cloud_run_gib_second_usd = float(os.getenv("PARKPULSE_COST_CLOUD_RUN_GIB_SECOND_USD", "0.0000025"))
    cloud_run_request_per_million_usd = float(os.getenv("PARKPULSE_COST_CLOUD_RUN_REQUEST_PER_MILLION_USD", "0.40"))
    gemini_flash_input_per_million_usd = float(os.getenv("PARKPULSE_COST_GEMINI_FLASH_INPUT_PER_MILLION_USD", "0.54"))
    gemini_flash_output_per_million_usd = float(os.getenv("PARKPULSE_COST_GEMINI_FLASH_OUTPUT_PER_MILLION_USD", "4.50"))
    bigquery_stream_per_200mib_usd = float(os.getenv("PARKPULSE_COST_BIGQUERY_STREAM_PER_200MIB_USD", "0.01"))
    storage_gb_month_usd = float(os.getenv("PARKPULSE_COST_STORAGE_GB_MONTH_USD", "0.02"))

    compute_usd = elapsed_seconds * cloud_run_vcpu * cloud_run_vcpu_second_usd
    memory_usd = elapsed_seconds * cloud_run_gib * cloud_run_gib_second_usd
    request_usd = (request_count / 1_000_000) * cloud_run_request_per_million_usd
    input_token_usd = (llm_calls * input_tokens_per_llm / 1_000_000) * gemini_flash_input_per_million_usd
    output_token_usd = (llm_calls * output_tokens_per_llm / 1_000_000) * gemini_flash_output_per_million_usd
    storage_gb = storage_bytes / 1024 / 1024 / 1024
    storage_usd_for_week = storage_gb * storage_gb_month_usd * (7 / 30)
    bigquery_stream_usd = (storage_bytes / (200 * 1024 * 1024)) * bigquery_stream_per_200mib_usd

    total_with_llm = compute_usd + memory_usd + request_usd + input_token_usd + output_token_usd + storage_usd_for_week + bigquery_stream_usd
    total_without_llm = compute_usd + memory_usd + request_usd + storage_usd_for_week + bigquery_stream_usd
    return {
        "sim_minutes": sim_minutes,
        "llm_interval_minutes": llm_interval_minutes,
        "llm_call_count_if_enabled": llm_calls,
        "request_count_assumption": request_count,
        "storage_bytes": storage_bytes,
        "storage_mb": round(storage_bytes / 1024 / 1024, 4),
        "elapsed_seconds": round(elapsed_seconds, 4),
        "rates": {
            "cloud_run_vcpu_second_usd": cloud_run_vcpu_second_usd,
            "cloud_run_gib_second_usd": cloud_run_gib_second_usd,
            "cloud_run_request_per_million_usd": cloud_run_request_per_million_usd,
            "gemini_flash_input_per_million_usd": gemini_flash_input_per_million_usd,
            "gemini_flash_output_per_million_usd": gemini_flash_output_per_million_usd,
            "bigquery_stream_per_200mib_usd": bigquery_stream_per_200mib_usd,
            "storage_gb_month_usd": storage_gb_month_usd,
        },
        "line_items_usd": {
            "cloud_run_cpu": round(compute_usd, 6),
            "cloud_run_memory": round(memory_usd, 6),
            "cloud_run_requests": round(request_usd, 6),
            "gemini_flash_input": round(input_token_usd, 6),
            "gemini_flash_output": round(output_token_usd, 6),
            "bigquery_streaming_insert_equivalent": round(bigquery_stream_usd, 6),
            "cloud_storage_one_week_equivalent": round(storage_usd_for_week, 6),
        },
        "estimated_total_usd_without_llm": round(total_without_llm, 6),
        "estimated_total_usd_with_llm": round(total_with_llm, 6),
    }


async def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    from park_simulation import ParkSimulation
    from park_twin_engine import state_digest

    score_calibration = _load_score_calibration(getattr(args, "score_calibration_report", None))
    sim = ParkSimulation()
    await sim.start_replay_run(seed=args.seed, scenario_key=args.scenario)
    await sim.set_time(args.start_hour, args.start_minute)

    tick_rows: list[dict[str, Any]] = []
    snapshot_rows: list[dict[str, Any]] = []
    llm_slot_rows: list[dict[str, Any]] = []
    gemini_rows: list[dict[str, Any]] = []
    recent_digests: list[dict[str, Any]] = []
    model_params = {
        "model": args.model,
        "temperature": args.temperature,
        "max_output_tokens": args.output_tokens_per_llm,
        "timeout_seconds": args.gemini_timeout_seconds,
        "retries": args.gemini_retries,
        "counterfactual_horizon_minutes": args.counterfactual_horizon_minutes,
        "score_gap_override": args.score_gap_override,
        "score_calibration_report": getattr(args, "score_calibration_report", None),
        "score_calibration_actions": sorted(
            (score_calibration.get("action_metric_multipliers") or {}).keys()
        )
        if isinstance(score_calibration.get("action_metric_multipliers"), dict)
        else [],
        "thinking_budget": 0,
        "response_mime_type": "application/json",
    }
    started = time.perf_counter()
    for sim_minute in range(1, args.sim_minutes + 1):
        await sim.step()
        state = await sim.get_state_lite()
        sim_time = state.get("simTime", {}) if isinstance(state.get("simTime"), dict) else {}
        phase = _phase_info(state)
        digest = state_digest(state)
        recent_digests.append(digest)
        recent_digests = recent_digests[-12:]
        tick_rows.append(
            {
                "sim_minute": sim_minute,
                "sim_time": sim_time,
                "phase": phase,
                "scenario": args.scenario,
                "digest": digest,
            }
        )
        if sim_minute % args.full_snapshot_interval_minutes == 0:
            snapshot_rows.append(
                {
                    "sim_minute": sim_minute,
                    "sim_time": sim_time,
                    "phase": phase,
                    "scenario": args.scenario,
                    "state": state,
                }
            )
        if sim_minute % args.llm_interval_minutes == 0:
            closed_for_guests = phase.get("is_open_to_guests") is not True
            slot_status = "eligible" if not closed_for_guests or args.include_closed_hours_gemini else "skipped_closed_phase"
            llm_slot_rows.append(
                {
                    "sim_minute": sim_minute,
                    "sim_time": sim_time,
                    "phase": phase,
                    "scenario": args.scenario,
                    "status": slot_status,
                    "would_call_model": args.model,
                    "input_token_budget": args.input_tokens_per_llm,
                    "output_token_budget": args.output_tokens_per_llm,
                    "digest": digest,
                }
            )
            if args.call_gemini and (not closed_for_guests or args.include_closed_hours_gemini):
                policy_candidates = (
                    _build_policy_candidates(
                        digest,
                        gemini_rows,
                        state=state,
                        counterfactual_horizon_minutes=args.counterfactual_horizon_minutes,
                        score_calibration=score_calibration,
                    )
                    if args.gemini_candidate_ranking
                    else []
                )
                memory_context = (
                    _retrieve_runtime_memory(
                        enabled=args.use_mongodb_memory,
                        scenario=args.scenario,
                        state_digest=digest,
                        recent_digests=recent_digests,
                        candidates=policy_candidates,
                        limit=args.memory_limit,
                    )
                    if args.gemini_candidate_ranking
                    else {"status": "not_candidate_ranking", "examples": []}
                )
                prompt = (
                    _build_gemini_candidate_ranking_prompt(
                        sim_minute=sim_minute,
                        state_digest=digest,
                        recent_digests=recent_digests,
                        phase=phase,
                        scenario=args.scenario,
                        model_params=model_params,
                        candidates=policy_candidates,
                        memory_context=memory_context,
                    )
                    if args.gemini_candidate_ranking
                    else _build_gemini_operating_prompt(
                        sim_minute=sim_minute,
                        state_digest=digest,
                        recent_digests=recent_digests,
                        phase=phase,
                        scenario=args.scenario,
                        model_params=model_params,
                    )
                )
                call_started = time.perf_counter()
                gemini_record: dict[str, Any] = {
                    "sim_minute": sim_minute,
                    "sim_time": sim_time,
                    "phase": phase,
                    "scenario": args.scenario,
                    "decision_mode": "candidate_ranking" if args.gemini_candidate_ranking else "direct_action",
                    "request": {
                        "prompt": prompt,
                        "params": model_params,
                    },
                    "memory_context": memory_context,
                    "before_digest": digest,
                }
                from gemini_hard_timeout import generate_gemini_json_hard_timeout

                result: dict[str, Any] | None = None
                call_attempts: list[dict[str, Any]] = []
                last_error = ""
                for attempt_index in range(args.gemini_retries + 1):
                    attempt_started = time.perf_counter()
                    try:
                        result = await generate_gemini_json_hard_timeout(
                            prompt,
                            timeout_seconds=args.gemini_timeout_seconds,
                            max_output_tokens=args.output_tokens_per_llm,
                            temperature=args.temperature,
                        )
                        call_attempts.append(
                            {
                                "attempt": attempt_index + 1,
                                "status": "success",
                                "latency_ms": round((time.perf_counter() - attempt_started) * 1000),
                                "transport": result.get("transport"),
                                "finish_reason": result.get("finish_reason"),
                            }
                        )
                        break
                    except Exception as error:
                        last_error = str(error)[:700]
                        call_attempts.append(
                            {
                                "attempt": attempt_index + 1,
                                "status": "error",
                                "latency_ms": round((time.perf_counter() - attempt_started) * 1000),
                                "error": last_error,
                            }
                        )

                try:
                    if result is None:
                        raise RuntimeError(last_error or "Gemini call failed without an error message.")
                    raw_text = str(result.get("text") or "")
                    parsed = _first_json_object(raw_text)
                    if args.gemini_candidate_ranking and not parsed:
                        raise ValueError("Gemini returned no parseable JSON for candidate ranking.")
                    candidate_selection: dict[str, Any] | None = None
                    selected_candidate: dict[str, Any] | None = None
                    if args.gemini_candidate_ranking:
                        preliminary_candidate, candidate_selection = _select_ranked_candidate(
                            parsed,
                            policy_candidates,
                            score_gap_override=args.score_gap_override,
                        )
                        executive_adjudication = _adjudicate_negotiated_candidate(
                            selected_candidate=preliminary_candidate,
                            candidate_selection=candidate_selection,
                            policy_candidates=policy_candidates,
                            parsed_response=parsed,
                            state_digest=digest,
                            memory_context=memory_context,
                        )
                        selected_candidate = executive_adjudication.get("final_candidate")
                        allowed = _candidate_to_action(selected_candidate)
                    else:
                        executive_adjudication = {}
                        allowed = _selected_allowed_action(parsed)
                    effective_allowed, policy_gate = _arbitrate_allowed_action(
                        selected=allowed,
                        state_digest=digest,
                        gemini_rows=gemini_rows,
                    )
                    policy_regulation_judgment = _policy_regulation_judgment(
                        state_digest=digest,
                        selected_candidate=selected_candidate,
                        effective_action=effective_allowed,
                        policy_gate=policy_gate,
                    )
                    policy_alignment_allows_execution = (
                        not args.enforce_policy_regulation_alignment
                        or policy_regulation_judgment.get("status") == "allowed"
                    )
                    execution: dict[str, Any] = {
                        "status": "not_executed",
                        "reason": "execute_gemini_actions flag is false",
                    }
                    after_digest = digest
                    if args.execute_gemini_actions and effective_allowed and policy_alignment_allows_execution:
                        execution = await sim.execute_action(effective_allowed["target"], effective_allowed["action"])
                        after_state = await sim.get_state_lite()
                        after_digest = state_digest(after_state)
                    elif args.execute_gemini_actions and not effective_allowed:
                        execution = {
                            "status": "blocked",
                            "reason": policy_gate.get("reason") or "Gemini selected an action outside the allowed bounded action set.",
                        }
                    elif args.execute_gemini_actions and effective_allowed and not policy_alignment_allows_execution:
                        execution = {
                            "status": "pending_operator_approval"
                            if policy_regulation_judgment.get("status") == "review_required"
                            else "blocked",
                            "reason": "policy/regulation alignment prevented simulated execution",
                            "policy_regulation_status": policy_regulation_judgment.get("status"),
                            "approval_owner": policy_regulation_judgment.get("approval_owner"),
                        }
                    negotiation_trace = (
                        _build_ranked_decision_negotiation_trace(
                            sim_minute=sim_minute,
                            scenario=args.scenario,
                            state_digest=digest,
                            memory_context=memory_context,
                            policy_candidates=policy_candidates,
                            parsed_response=parsed,
                            selected_candidate=selected_candidate,
                            effective_action=effective_allowed,
                            policy_gate=policy_gate,
                            policy_regulation_judgment=policy_regulation_judgment,
                            executive_adjudication=executive_adjudication,
                        )
                        if args.gemini_candidate_ranking
                        else {}
                    )
                    gemini_record.update(
                        {
                            "status": "success",
                            "latency_ms": round((time.perf_counter() - call_started) * 1000),
                            "transport": result.get("transport"),
                            "finish_reason": result.get("finish_reason"),
                            "usage_metadata": result.get("usage_metadata", {}),
                            "call_attempts": call_attempts,
                            "response_text": raw_text,
                            "parsed_response": parsed,
                            "model_allowed_action": allowed,
                            "allowed_action": effective_allowed,
                            "policy_candidates": policy_candidates,
                            "selected_policy_candidate": selected_candidate,
                            "candidate_selection": candidate_selection,
                            "executive_adjudication": executive_adjudication,
                            "policy_gate": policy_gate,
                            "policy_regulation_judgment": policy_regulation_judgment,
                            "negotiation_trace": negotiation_trace,
                            "execution": execution,
                            "after_digest": after_digest,
                        }
                    )
                except Exception as error:
                    if args.gemini_candidate_ranking and policy_candidates:
                        fallback_status = "fallback_model_parse_error" if result is not None else "fallback_transport_error"
                        fallback_reason = (
                            "Gemini returned no parseable candidate-ranking JSON; using highest-scored policy-passed candidate."
                            if fallback_status == "fallback_model_parse_error"
                            else "Gemini transport failed after retries; using highest-scored policy-passed candidate."
                        )
                        preliminary_candidate = _best_policy_candidate(policy_candidates)
                        executive_adjudication = _adjudicate_negotiated_candidate(
                            selected_candidate=preliminary_candidate,
                            candidate_selection={
                                "status": fallback_status,
                                "reason": fallback_reason,
                            },
                            policy_candidates=policy_candidates,
                            parsed_response={},
                            state_digest=digest,
                            memory_context=memory_context,
                        )
                        selected_candidate = executive_adjudication.get("final_candidate")
                        allowed = _candidate_to_action(selected_candidate)
                        effective_allowed, policy_gate = _arbitrate_allowed_action(
                            selected=allowed,
                            state_digest=digest,
                            gemini_rows=gemini_rows,
                        )
                        policy_regulation_judgment = _policy_regulation_judgment(
                            state_digest=digest,
                            selected_candidate=selected_candidate,
                            effective_action=effective_allowed,
                            policy_gate=policy_gate,
                        )
                        policy_alignment_allows_execution = (
                            not args.enforce_policy_regulation_alignment
                            or policy_regulation_judgment.get("status") == "allowed"
                        )
                        execution = {
                            "status": "not_executed",
                            "reason": "execute_gemini_actions flag is false",
                        }
                        after_digest = digest
                        if args.execute_gemini_actions and effective_allowed and policy_alignment_allows_execution:
                            execution = await sim.execute_action(effective_allowed["target"], effective_allowed["action"])
                            after_state = await sim.get_state_lite()
                            after_digest = state_digest(after_state)
                        elif args.execute_gemini_actions and not effective_allowed:
                            execution = {
                                "status": "blocked",
                                "reason": policy_gate.get("reason") or "fallback selected an action outside the allowed bounded action set.",
                            }
                        elif args.execute_gemini_actions and effective_allowed and not policy_alignment_allows_execution:
                            execution = {
                                "status": "pending_operator_approval"
                                if policy_regulation_judgment.get("status") == "review_required"
                                else "blocked",
                                "reason": "policy/regulation alignment prevented simulated execution",
                                "policy_regulation_status": policy_regulation_judgment.get("status"),
                                "approval_owner": policy_regulation_judgment.get("approval_owner"),
                            }
                        negotiation_trace = _build_ranked_decision_negotiation_trace(
                            sim_minute=sim_minute,
                            scenario=args.scenario,
                            state_digest=digest,
                            memory_context=memory_context,
                            policy_candidates=policy_candidates,
                            parsed_response={},
                            selected_candidate=selected_candidate,
                            effective_action=effective_allowed,
                            policy_gate=policy_gate,
                            policy_regulation_judgment=policy_regulation_judgment,
                            executive_adjudication=executive_adjudication,
                        )
                        fallback_candidate_id = selected_candidate.get("id") if isinstance(selected_candidate, dict) else None
                        gemini_record.update(
                            {
                                "status": fallback_status,
                                "latency_ms": round((time.perf_counter() - call_started) * 1000),
                                "error": str(error)[:700],
                                "call_attempts": call_attempts,
                                "response_text": str(result.get("text") or "") if isinstance(result, dict) else "",
                                "parsed_response": {},
                                "model_allowed_action": None,
                                "allowed_action": effective_allowed,
                                "policy_candidates": policy_candidates,
                                "selected_policy_candidate": selected_candidate,
                                "candidate_selection": {
                                    "status": fallback_status,
                                    "reason": fallback_reason,
                                    "fallback_candidate_id": fallback_candidate_id,
                                    "ranked_candidate_ids": [],
                                    "invalid_ranked_candidate_ids": [],
                                    "ranked_blocked_candidate_ids": [],
                                },
                                "executive_adjudication": executive_adjudication,
                                "policy_gate": policy_gate,
                                "policy_regulation_judgment": policy_regulation_judgment,
                                "negotiation_trace": negotiation_trace,
                                "execution": execution,
                                "after_digest": after_digest,
                            }
                        )
                    else:
                        gemini_record.update(
                            {
                                "status": "error",
                                "latency_ms": round((time.perf_counter() - call_started) * 1000),
                                "error": str(error)[:700],
                                "call_attempts": call_attempts,
                                "execution": {"status": "not_executed", "reason": "gemini_call_failed"},
                                "after_digest": digest,
                            }
                        )
                gemini_rows.append(gemini_record)
    elapsed = time.perf_counter() - started

    run_dir = Path(args.output_dir) / f"timelapse-cost-probe-{_now_id()}"
    tick_path = run_dir / "tick-digests.jsonl"
    snapshot_path = run_dir / "full-snapshots.jsonl"
    llm_path = run_dir / "llm-decision-slots.jsonl"
    gemini_path = run_dir / "gemini-operation-calls.jsonl"
    mediation_memory_path = run_dir / "mediation-memory-examples.jsonl"
    tick_bytes = _write_jsonl(tick_path, tick_rows)
    snapshot_bytes = _write_jsonl(snapshot_path, snapshot_rows)
    llm_bytes = _write_jsonl(llm_path, llm_slot_rows)
    gemini_bytes = _write_jsonl(gemini_path, gemini_rows) if args.call_gemini else 0
    mediation_examples = (
        _build_mediation_memory_examples(gemini_rows, source_run_id=run_dir.name)
        if args.call_gemini and args.gemini_candidate_ranking
        else []
    )
    mediation_memory_bytes = _write_jsonl(mediation_memory_path, mediation_examples) if mediation_examples else 0
    storage_bytes = tick_bytes + snapshot_bytes + llm_bytes + gemini_bytes + mediation_memory_bytes
    eligible_slot_count = sum(1 for row in llm_slot_rows if row.get("status") == "eligible")
    skipped_closed_slot_count = sum(1 for row in llm_slot_rows if row.get("status") == "skipped_closed_phase")
    estimate = _cost_estimate(
        elapsed_seconds=elapsed,
        storage_bytes=storage_bytes,
        sim_minutes=args.sim_minutes,
        llm_interval_minutes=args.llm_interval_minutes,
        input_tokens_per_llm=args.input_tokens_per_llm,
        output_tokens_per_llm=args.output_tokens_per_llm,
        cloud_run_vcpu=args.cloud_run_vcpu,
        cloud_run_gib=args.cloud_run_gib,
        api_tick_requests=args.api_tick_requests,
        llm_call_count=len(gemini_rows) if args.call_gemini else eligible_slot_count,
    )
    report = {
        "status": "complete",
        "mode": "one_day_sim_time_cost_probe",
        "created_at": _now_iso(),
        "budget_profile": {
            "weekly_budget_usd": args.weekly_budget_usd,
            "target_sim_days": 7,
            "probe_sim_days": round(args.sim_minutes / 1440, 3),
            "probe_sim_minutes": args.sim_minutes,
            "one_week_sim_minutes": 10080,
        },
        "run": {
            "scenario": args.scenario,
            "seed": args.seed,
            "tick_count": len(tick_rows),
            "snapshot_count": len(snapshot_rows),
            "llm_decision_slot_count": len(llm_slot_rows),
            "llm_skipped_closed_slot_count": skipped_closed_slot_count,
            "llm_eligible_slot_count": eligible_slot_count,
            "llm_called": bool(args.call_gemini),
            "gemini_call_count": len(gemini_rows),
            "gemini_success_count": sum(1 for row in gemini_rows if row.get("status") == "success"),
            "gemini_error_count": sum(
                1
                for row in gemini_rows
                if row.get("status") in {"error", "fallback_transport_error", "fallback_model_parse_error"}
            ),
            "gemini_fallback_transport_error_count": sum(1 for row in gemini_rows if row.get("status") == "fallback_transport_error"),
            "gemini_fallback_model_parse_error_count": sum(1 for row in gemini_rows if row.get("status") == "fallback_model_parse_error"),
            "gemini_executed_action_count": sum(
                1
                for row in gemini_rows
                if isinstance(row.get("execution"), dict) and row["execution"].get("status") == "success"
            ),
            "model_params": model_params,
            "policy_regulation_alignment": {
                "enforced": bool(args.enforce_policy_regulation_alignment),
                "allowed_count": sum(
                    1
                    for row in gemini_rows
                    if row.get("policy_regulation_judgment", {}).get("status") == "allowed"
                ),
                "review_required_count": sum(
                    1
                    for row in gemini_rows
                    if row.get("policy_regulation_judgment", {}).get("status") == "review_required"
                ),
                "blocked_count": sum(
                    1
                    for row in gemini_rows
                    if row.get("policy_regulation_judgment", {}).get("status") == "blocked"
                ),
                "held_execution_count": sum(
                    1
                    for row in gemini_rows
                    if isinstance(row.get("execution"), dict)
                    and row["execution"].get("status") in {"pending_operator_approval", "blocked"}
                    and row["execution"].get("reason") == "policy/regulation alignment prevented simulated execution"
                ),
            },
            "score_calibration": {
                "enabled": bool(score_calibration),
                "version": score_calibration.get("version") if isinstance(score_calibration, dict) else None,
                "source_report": getattr(args, "score_calibration_report", None),
                "action_metric_multipliers": score_calibration.get("action_metric_multipliers", {})
                if isinstance(score_calibration, dict)
                else {},
            },
            "memory": {
                "use_mongodb_memory": bool(args.use_mongodb_memory),
                "memory_limit": args.memory_limit,
                "calls_with_memory": sum(1 for row in gemini_rows if row.get("memory_context", {}).get("examples")),
                "calls_with_mediator_memory": sum(
                    1 for row in gemini_rows if row.get("memory_context", {}).get("mediator_examples")
                ),
                "calls_with_memory_guidance": sum(
                    1
                    for row in gemini_rows
                    if row.get("memory_context", {}).get("examples")
                    or row.get("memory_context", {}).get("mediator_examples")
                    or row.get("memory_context", {}).get("cautionary_examples")
                ),
                "calls_with_cautionary_memory": sum(
                    1 for row in gemini_rows if row.get("memory_context", {}).get("cautionary_examples")
                ),
                "connected": any(row.get("memory_context", {}).get("connected") for row in gemini_rows),
                "statuses": {
                    status: sum(
                        1
                        for row in gemini_rows
                        if str(row.get("memory_context", {}).get("status") or "not_used") == status
                    )
                    for status in sorted({str(row.get("memory_context", {}).get("status") or "not_used") for row in gemini_rows})
                },
                "methods": {
                    method: sum(
                        1
                        for row in gemini_rows
                        if str(row.get("memory_context", {}).get("method") or "none") == method
                    )
                    for method in sorted({str(row.get("memory_context", {}).get("method") or "none") for row in gemini_rows})
                },
                "mediation_learning": {
                    "candidate_example_count": len(mediation_examples),
                    "artifact": str(mediation_memory_path) if mediation_examples else None,
                    "status_counts": {
                        status: sum(
                            1
                            for row in gemini_rows
                            if str(row.get("executive_adjudication", {}).get("status") or "none") == status
                        )
                        for status in sorted(
                            {
                                str(row.get("executive_adjudication", {}).get("status") or "none")
                                for row in gemini_rows
                            }
                        )
                    },
                    "memory_prior_boosted_calls": sum(
                        1
                        for row in gemini_rows
                        for ledger in (
                            row.get("executive_adjudication", {}).get("challenger_ledgers", [])
                            if isinstance(row.get("executive_adjudication"), dict)
                            else []
                        )
                        if isinstance(ledger, dict)
                        and int((ledger.get("memory_prior", {}) if isinstance(ledger.get("memory_prior"), dict) else {}).get("boost") or 0)
                        > 0
                    ),
                },
            },
            "decision_mode": "candidate_ranking" if args.gemini_candidate_ranking else "direct_action",
            "start_time": {"hour": args.start_hour, "minute": args.start_minute},
            "closed_hours_gemini_enabled": bool(args.include_closed_hours_gemini),
            "artifact_bytes": {
                "tick_digests": tick_bytes,
                "full_snapshots": snapshot_bytes,
                "llm_decision_slots": llm_bytes,
                "gemini_operation_calls": gemini_bytes,
                "mediation_memory_examples": mediation_memory_bytes,
                "total": storage_bytes,
            },
            "artifacts": {
                "run_dir": str(run_dir),
                "tick_digests": str(tick_path),
                "full_snapshots": str(snapshot_path),
                "llm_decision_slots": str(llm_path),
                "gemini_operation_calls": str(gemini_path) if args.call_gemini else None,
                "mediation_memory_examples": str(mediation_memory_path) if mediation_examples else None,
            },
        },
        "cost_estimate": estimate,
        "projected_week_from_probe": {
            "storage_mb": round((storage_bytes * 7) / 1024 / 1024, 3),
            "estimated_total_usd_without_llm": round(estimate["estimated_total_usd_without_llm"] * 7, 6),
            "estimated_total_usd_with_llm": round(estimate["estimated_total_usd_with_llm"] * 7, 6),
            "llm_call_count_if_enabled": estimate["llm_call_count_if_enabled"] * 7,
        },
        "boundary": (
            "This is a local sim-time probe. With --call-gemini it calls Gemini for bounded internal operation choices and can execute only allow-listed simulation actions. "
            + (
                "With --use-mongodb-memory it also reads MongoDB timelapse_model_examples as retrieval memory. "
                if args.use_mongodb_memory
                else "It does not call Cloud Run, BigQuery, MongoDB, or Cloud Billing. "
            )
            + "The cost is an estimate using configured public-rate assumptions and measured runtime/storage."
        ),
    }
    if gemini_rows:
        usage_rows = [row.get("usage_metadata", {}) for row in gemini_rows if isinstance(row.get("usage_metadata"), dict)]
        prompt_tokens = sum(int(row.get("promptTokenCount") or row.get("prompt_token_count") or 0) for row in usage_rows)
        candidate_tokens = sum(int(row.get("candidatesTokenCount") or row.get("candidates_token_count") or 0) for row in usage_rows)
        total_tokens = sum(int(row.get("totalTokenCount") or row.get("total_token_count") or 0) for row in usage_rows)
        report["gemini_usage_observed"] = {
            "rows_with_usage_metadata": len([row for row in usage_rows if row]),
            "prompt_tokens": prompt_tokens,
            "candidate_tokens": candidate_tokens,
            "total_tokens": total_tokens,
        }
    report_path = run_dir / "one-day-cost-report.json"
    report["run"]["memory"]["mediation_learning"]["mongodb_write"] = _record_mediation_memory_examples(
        enabled=bool(args.use_mongodb_memory),
        examples=mediation_examples,
        source_manifest=str(report_path),
    )
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    report["run"]["artifacts"]["report"] = str(report_path)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one simulated park day and estimate the equivalent GCP cost.")
    parser.add_argument("--sim-minutes", type=int, default=1440)
    parser.add_argument("--llm-interval-minutes", type=int, default=int(os.getenv("PARKPULSE_TIMELAPSE_LLM_INTERVAL_MINUTES", "15")))
    parser.add_argument("--full-snapshot-interval-minutes", type=int, default=int(os.getenv("PARKPULSE_TIMELAPSE_FULL_SNAPSHOT_INTERVAL_MINUTES", "15")))
    parser.add_argument("--input-tokens-per-llm", type=int, default=4000)
    parser.add_argument("--output-tokens-per-llm", type=int, default=900)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--gemini-timeout-seconds", type=float, default=8.0)
    parser.add_argument("--gemini-retries", type=int, default=int(os.getenv("PARKPULSE_GEMINI_RETRIES", "1")))
    parser.add_argument("--counterfactual-horizon-minutes", type=int, default=int(os.getenv("PARKPULSE_COUNTERFACTUAL_HORIZON_MINUTES", "30")))
    parser.add_argument("--score-gap-override", type=int, default=int(os.getenv("PARKPULSE_SCORE_GAP_OVERRIDE", "10")))
    parser.add_argument("--score-calibration-report", help="Optional score-calibration.json generated by analyze_memory_influence.py.")
    parser.add_argument("--call-gemini", action="store_true", help="Actually call Gemini at each LLM decision slot.")
    parser.add_argument("--gemini-candidate-ranking", action="store_true", help="Ask Gemini to rank policy-passed candidate IDs instead of selecting an action directly.")
    parser.add_argument("--execute-gemini-actions", action="store_true", help="Execute Gemini's selected allow-listed simulation action.")
    parser.add_argument("--enforce-policy-regulation-alignment", action="store_true", help="Hold simulated execution unless policy_regulation_judgment.status is allowed.")
    parser.add_argument("--use-mongodb-memory", action="store_true", help="Retrieve similar timelapse train examples from MongoDB and include them in candidate-ranking prompts.")
    parser.add_argument("--memory-limit", type=int, default=3)
    parser.add_argument("--cloud-run-vcpu", type=float, default=1.0)
    parser.add_argument("--cloud-run-gib", type=float, default=1.0)
    parser.add_argument("--api-tick-requests", action="store_true", help="Estimate 1 API request per simulated minute instead of one batch job request.")
    parser.add_argument("--weekly-budget-usd", type=float, default=float(os.getenv("PARKPULSE_WEEKLY_BUDGET_USD", "25")))
    parser.add_argument("--model", default=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
    parser.add_argument("--scenario", default="ride_down", choices=["ride_down", "staff_shortage", "food_spike", "storm_response"])
    parser.add_argument("--seed", default="one-day-cost-probe")
    parser.add_argument("--start-hour", type=int, default=9)
    parser.add_argument("--start-minute", type=int, default=0)
    parser.add_argument("--include-closed-hours-gemini", action="store_true", help="Also call Gemini during closed/pre-open/post-close phases.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    args = parser.parse_args()
    if args.sim_minutes < 1:
        raise SystemExit("--sim-minutes must be >= 1")
    if args.llm_interval_minutes < 1:
        raise SystemExit("--llm-interval-minutes must be >= 1")
    if args.full_snapshot_interval_minutes < 1:
        raise SystemExit("--full-snapshot-interval-minutes must be >= 1")
    if args.counterfactual_horizon_minutes < 5:
        raise SystemExit("--counterfactual-horizon-minutes must be >= 5")
    if args.score_gap_override < 1:
        raise SystemExit("--score-gap-override must be >= 1")
    if args.memory_limit < 1:
        raise SystemExit("--memory-limit must be >= 1")
    report = asyncio.run(run_probe(args))
    print(
        json.dumps(
            {
                "status": report["status"],
                "sim_minutes": report["budget_profile"]["probe_sim_minutes"],
                "artifact_mb": round(report["run"]["artifact_bytes"]["total"] / 1024 / 1024, 4),
                "llm_decision_slots": report["run"]["llm_decision_slot_count"],
                "llm_eligible_slots": report["run"]["llm_eligible_slot_count"],
                "llm_skipped_closed_slots": report["run"]["llm_skipped_closed_slot_count"],
                "gemini_calls": report["run"]["gemini_call_count"],
                "gemini_success": report["run"]["gemini_success_count"],
                "gemini_executed_actions": report["run"]["gemini_executed_action_count"],
                "memory_calls": report["run"]["memory"]["calls_with_memory"],
                "memory_connected": report["run"]["memory"]["connected"],
                "decision_mode": report["run"]["decision_mode"],
                "estimated_total_usd_without_llm": report["cost_estimate"]["estimated_total_usd_without_llm"],
                "estimated_total_usd_with_llm": report["cost_estimate"]["estimated_total_usd_with_llm"],
                "projected_week_usd_with_llm": report["projected_week_from_probe"]["estimated_total_usd_with_llm"],
                "report": report["run"]["artifacts"]["report"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
