from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


def _state_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    flow = state.get("guestFlow", {}) if isinstance(state, dict) else {}
    zones = flow.get("zones", []) if isinstance(flow, dict) else []
    rides = flow.get("rides", []) if isinstance(flow, dict) else []
    paths = flow.get("paths", []) if isinstance(flow, dict) else []
    return {
        "avg_satisfaction": int(flow.get("avgSatisfaction", 0) or 0),
        "max_zone_density": max([int(zone.get("density", 0) or 0) for zone in zones if isinstance(zone, dict)] or [0]),
        "avg_zone_comfort": _avg([float(zone.get("comfortScore", 0) or 0) for zone in zones if isinstance(zone, dict)]),
        "max_path_congestion": max([int(path.get("congestionLevel", 0) or 0) for path in paths if isinstance(path, dict)] or [0]),
        "high_wait_rides": sum(1 for ride in rides if isinstance(ride, dict) and int(ride.get("waitMins", 0) or 0) >= 45),
        "queued_guests": sum(int(ride.get("queueGuests", 0) or 0) for ride in rides if isinstance(ride, dict)),
        "active_policy": flow.get("activePolicy", "normal"),
    }


def _delta(before: dict[str, Any], after: dict[str, Any], key: str) -> float:
    return round(float(after.get(key, 0) or 0) - float(before.get(key, 0) or 0), 2)


def _channel_metrics(dispatches: list[dict[str, Any]]) -> dict[str, Any]:
    guest = [item for item in dispatches if item.get("channel") == "guest_app"]
    workers = [item for item in dispatches if item.get("channel") == "worker_device"]
    equipment = [item for item in dispatches if item.get("channel") == "equipment_controller"]
    return {
        "guest": {
            "dispatches": len(guest),
            "accepted": sum(int(item.get("response", {}).get("acceptedCount", 0) or 0) for item in guest),
            "followed": sum(int(item.get("response", {}).get("followThroughCount", 0) or 0) for item in guest),
            "sample_size": sum(int(item.get("response", {}).get("sampleSize", 0) or 0) for item in guest),
        },
        "workers": {
            "dispatches": len(workers),
            "acknowledged": sum(int(item.get("response", {}).get("acknowledgedCount", 0) or 0) for item in workers),
            "median_ack_seconds": min(
                [int(item.get("response", {}).get("medianAckSeconds", 999) or 999) for item in workers] or [0]
            ),
        },
        "equipment": {
            "dispatches": len(equipment),
            "applied": sum(1 for item in equipment if item.get("response", {}).get("applied")),
        },
    }


def build_closed_loop_outcome(
    before_state: dict[str, Any],
    after_state: dict[str, Any],
    dispatches: list[dict[str, Any]],
    response_metrics: dict[str, Any],
    proactive: dict[str, Any],
    brief: dict[str, Any],
    proactive_eval: dict[str, Any],
) -> dict[str, Any]:
    before = _state_snapshot(before_state)
    after = _state_snapshot(after_state)
    channels = _channel_metrics(dispatches)
    density_delta = _delta(before, after, "max_zone_density")
    congestion_delta = _delta(before, after, "max_path_congestion")
    comfort_delta = _delta(before, after, "avg_zone_comfort")
    queue_delta = _delta(before, after, "queued_guests")
    response_score = int(response_metrics.get("score", 0) or 0)
    prevention_score = int(proactive_eval.get("expected_prevention", 0) or 0)
    state_score = round(
        max(0, min(100, 70 + max(0, -density_delta) * 1.1 + max(0, -congestion_delta) * 0.9 + max(0, comfort_delta) * 1.4))
    )
    overall = round(response_score * 0.34 + prevention_score * 0.26 + state_score * 0.4)
    loop_fingerprint = f"{proactive.get('proactive_id', '')}:{brief.get('operator_brief', '')}:{response_score}:{state_score}"
    should_learn = response_score < 75 or state_score < 82 or bool(brief.get("should_revise_event_plan"))
    return {
        "loop_id": f"loop_{hashlib.sha1(loop_fingerprint.encode('utf-8')).hexdigest()[:12]}",
        "created_at": _utc_now(),
        "mode": "proactive_closed_loop",
        "phases": [
            {"name": "scan", "status": "complete", "detail": f"{proactive.get('summary', {}).get('insight_count', 0)} proactive signals found."},
            {"name": "commit", "status": "complete", "detail": f"{len(dispatches)} actions emitted to guest, worker, and equipment ports."},
            {"name": "observe", "status": "complete", "detail": f"Take rate {round(float(response_metrics.get('takeRate', 0) or 0) * 100)}%, follow-through {round(float(response_metrics.get('reactiveFollowThroughRate', 0) or 0) * 100)}%."},
            {"name": "adapt", "status": "complete" if should_learn else "watch", "detail": "Event plan revision requested." if brief.get("should_revise_event_plan") else "Outcome stored for future plan retrieval."},
        ],
        "response_metrics": response_metrics,
        "channel_metrics": channels,
        "state_impact": {
            "before": before,
            "after": after,
            "density_delta": density_delta,
            "congestion_delta": congestion_delta,
            "comfort_delta": comfort_delta,
            "queued_guest_delta": queue_delta,
            "headline": (
                f"Max density {density_delta:+.0f}, path congestion {congestion_delta:+.0f}, "
                f"comfort {comfort_delta:+.1f}, queued guests {queue_delta:+.0f}."
            ),
        },
        "scorecard": {
            "overall": overall,
            "response_score": response_score,
            "state_movement_score": state_score,
            "prevention_score": prevention_score,
            "status": "learn_and_revise" if should_learn else "healthy",
        },
        "learning": {
            "should_update_plan": bool(brief.get("should_revise_event_plan")),
            "should_adjust_policy": response_score < 75,
            "take_rate_signal": (
                "increase incentive or personalize routing" if float(response_metrics.get("takeRate", 0) or 0) < 0.35 else "routing incentive is acceptable"
            ),
            "next_prompt": brief.get("plan_revision_prompt", ""),
        },
    }


def build_reactive_outcome(
    before_state: dict[str, Any],
    after_state: dict[str, Any],
    dispatches: list[dict[str, Any]],
    response_metrics: dict[str, Any],
    optimization: dict[str, Any],
    plan: dict[str, Any],
    eval_result: dict[str, Any],
) -> dict[str, Any]:
    before = _state_snapshot(before_state)
    after = _state_snapshot(after_state)
    channels = _channel_metrics(dispatches)
    density_delta = _delta(before, after, "max_zone_density")
    congestion_delta = _delta(before, after, "max_path_congestion")
    comfort_delta = _delta(before, after, "avg_zone_comfort")
    queue_delta = _delta(before, after, "queued_guests")
    response_score = int(response_metrics.get("score", 0) or 0)
    eval_score = int((eval_result.get("scorecard", {}) or {}).get("overall", 0) or 0)
    state_score = round(
        max(0, min(100, 68 + max(0, -density_delta) * 1.1 + max(0, -congestion_delta) * 0.9 + max(0, comfort_delta) * 1.2))
    )
    overall = round(response_score * 0.42 + state_score * 0.34 + eval_score * 0.24)
    selected = optimization.get("selected_plan", {}) if isinstance(optimization, dict) else {}
    selected_name = selected.get("name") or plan.get("recommended_action", "reactive agent plan")
    loop_fingerprint = f"{selected_name}:{response_score}:{state_score}:{eval_score}:{queue_delta}"
    take_rate = float(response_metrics.get("takeRate", 0) or 0)
    follow_rate = float(response_metrics.get("reactiveFollowThroughRate", 0) or 0)
    should_learn = response_score < 78 or state_score < 82 or take_rate < 0.45 or follow_rate < 0.4
    return {
        "loop_id": f"loop_{hashlib.sha1(loop_fingerprint.encode('utf-8')).hexdigest()[:12]}",
        "created_at": _utc_now(),
        "mode": "reactive_closed_loop",
        "phases": [
            {"name": "detect", "status": "complete", "detail": f"Scenario classified as {plan.get('root_cause_classification', 'unknown')}."},
            {"name": "plan", "status": "complete", "detail": f"Selected {selected_name} from {len(optimization.get('candidates', []) or [])} candidate mixes."},
            {"name": "emit", "status": "complete", "detail": f"{len(dispatches)} actions emitted to guest, worker, and equipment ports."},
            {"name": "observe", "status": "complete", "detail": f"Take rate {round(take_rate * 100)}%, follow-through {round(follow_rate * 100)}%."},
            {"name": "learn", "status": "complete" if should_learn else "watch", "detail": "Outcome converted into a reusable agent learning rule." if should_learn else "Healthy outcome stored as a positive pattern."},
        ],
        "response_metrics": response_metrics,
        "channel_metrics": channels,
        "state_impact": {
            "before": before,
            "after": after,
            "density_delta": density_delta,
            "congestion_delta": congestion_delta,
            "comfort_delta": comfort_delta,
            "queued_guest_delta": queue_delta,
            "headline": (
                f"Max density {density_delta:+.0f}, path congestion {congestion_delta:+.0f}, "
                f"comfort {comfort_delta:+.1f}, queued guests {queue_delta:+.0f}."
            ),
        },
        "scorecard": {
            "overall": overall,
            "response_score": response_score,
            "state_movement_score": state_score,
            "eval_score": eval_score,
            "status": "learn_and_adjust" if should_learn else "healthy_pattern",
        },
        "learning": {
            "should_update_plan": should_learn,
            "should_adjust_policy": response_score < 75,
            "take_rate_signal": (
                "increase incentive or personalize routing" if take_rate < 0.35 else "routing incentive is acceptable"
            ),
            "next_prompt": (
                "Use this outcome when selecting the next custom action mix: avoid overloaded targets, "
                "prefer visible guest/worker/equipment actions, and tune offer strength from observed take rate."
            ),
        },
    }
