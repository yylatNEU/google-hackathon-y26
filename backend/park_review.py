from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _status(score: int) -> str:
    if score >= 85:
        return "ready"
    if score >= 65:
        return "review"
    return "gap"


def _score_item(
    key: str,
    label: str,
    score: int,
    evidence: list[str],
    missing: list[str] | None = None,
) -> dict[str, Any]:
    score = max(0, min(100, score))
    return {
        "key": key,
        "label": label,
        "score": score,
        "status": _status(score),
        "evidence": evidence,
        "missing": missing or [],
    }


def _top_item(rows: list[dict[str, Any]], score_key: str) -> dict[str, Any] | None:
    if not rows:
        return None
    return max(rows, key=lambda item: _as_int(item.get(score_key)))


def _timeline(
    state: dict[str, Any],
    runtime_governance: dict[str, Any] | None,
    dispatches: list[dict[str, Any]] | None,
    signals: dict[str, Any] | None,
    replay: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in (replay or {}).get("events", []) or []:
        rows.append(
            {
                "at": event.get("at"),
                "kind": f"replay_{event.get('kind', 'event')}",
                "label": event.get("label") or event.get("kind") or "Replay event",
                "detail": event.get("narrative", ""),
                "source": "simulation_replay",
                "delta": event.get("delta", {}),
                "before": event.get("before", {}),
                "after": event.get("after", {}),
            }
        )
    for event in state.get("guestFlow", {}).get("interventions", []) or []:
        rows.append(
            {
                "at": event.get("createdAt"),
                "kind": "injected_event",
                "label": str(event.get("kind", "event")).replace("_", " "),
                "detail": f"{event.get('targetId', 'unknown target')} at {event.get('intensity', '--')}% intensity",
                "source": "park_simulation",
            }
        )
    for action in state.get("lastActions", []) or []:
        rows.append(
            {
                "at": action.get("createdAt"),
                "kind": "sim_action",
                "label": f"{action.get('target', 'park')}/{action.get('action', 'action')}",
                "detail": action.get("message", ""),
                "source": "park_simulation",
            }
        )
    for dispatch in dispatches or []:
        payload = dispatch.get("payload", {}) if isinstance(dispatch, dict) else {}
        rows.append(
            {
                "at": dispatch.get("createdAt"),
                "kind": "dispatch",
                "label": str(dispatch.get("channel", "action_bus")),
                "detail": payload.get("message") or payload.get("task") or payload.get("command") or "Dispatch emitted",
                "source": "delivery_outbox",
            }
        )
    for signal in (signals or {}).get("signals", []) or []:
        rows.append(
            {
                "at": signal.get("createdAt") or signal.get("created_at"),
                "kind": "signal",
                "label": signal.get("subject") or signal.get("risk_level") or "park signal",
                "detail": signal.get("body") or signal.get("text") or signal.get("triage_explanation") or "",
                "source": signal.get("source", "signal_bus"),
            }
        )
    for ledger in (runtime_governance or {}).get("decision_ledger", []) or []:
        rows.append(
            {
                "at": ledger.get("createdAt") or ledger.get("created_at"),
                "kind": "policy_gate",
                "label": ledger.get("title") or ledger.get("id") or "Policy gate",
                "detail": " / ".join(ledger.get("policyFindings", [])[:2]),
                "source": ledger.get("source", "runtime_governance"),
            }
        )

    return sorted(rows, key=lambda item: str(item.get("at") or ""), reverse=True)[:18]


def build_review_snapshot(
    state: dict[str, Any],
    runtime_governance: dict[str, Any] | None = None,
    dispatches: list[dict[str, Any]] | None = None,
    signals: dict[str, Any] | None = None,
    replay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    flow = state.get("guestFlow", {}) if isinstance(state.get("guestFlow"), dict) else {}
    physical = state.get("physicalMap", {}) if isinstance(state.get("physicalMap"), dict) else {}
    scenario = flow.get("activeScenario", {}) if isinstance(flow.get("activeScenario"), dict) else {}
    zones = flow.get("zones", []) if isinstance(flow.get("zones"), list) else []
    paths = flow.get("paths", []) if isinstance(flow.get("paths"), list) else []
    rides = flow.get("rides", []) if isinstance(flow.get("rides"), list) else []
    interventions = flow.get("interventions", []) if isinstance(flow.get("interventions"), list) else []
    landmarks = physical.get("landmarks", []) if isinstance(physical.get("landmarks"), list) else []
    facilities = physical.get("facilities", []) if isinstance(physical.get("facilities"), list) else []
    queues = physical.get("queues", []) if isinstance(physical.get("queues"), list) else []
    guest_groups = physical.get("guestGroups", []) if isinstance(physical.get("guestGroups"), list) else []
    service_routes = physical.get("serviceRoutes", []) if isinstance(physical.get("serviceRoutes"), list) else []
    alerts = state.get("alerts", []) if isinstance(state.get("alerts"), list) else []
    last_actions = state.get("lastActions", []) if isinstance(state.get("lastActions"), list) else []
    readiness = state.get("incidentReadiness", {}) if isinstance(state.get("incidentReadiness"), dict) else {}
    guest_care = state.get("guestCare", {}) if isinstance(state.get("guestCare"), dict) else {}
    maintenance = state.get("maintenance", {}) if isinstance(state.get("maintenance"), dict) else {}
    food = state.get("foodInventory", {}) if isinstance(state.get("foodInventory"), dict) else {}
    replay_events = (replay or {}).get("events", []) if isinstance((replay or {}).get("events", []), list) else []
    timeline = _timeline(state, runtime_governance, dispatches, signals, replay)

    physical_score = 45
    physical_score += min(20, len(landmarks) * 2)
    physical_score += min(12, len(queues) * 4)
    physical_score += min(8, len(service_routes) * 3)
    physical_score += min(8, len(facilities))
    physical_score = min(92, physical_score)

    movement_score = 35
    movement_score += min(18, len(guest_groups) * 3)
    movement_score += min(14, len(paths) * 3)
    movement_score += 8 if all(group.get("destination") for group in guest_groups[:4]) else 0
    movement_score += 6 if any(group.get("mood") not in {"neutral", "normal", None} for group in guest_groups) else 0
    movement_score = min(72, movement_score)

    cause_effect_score = 50
    cause_effect_score += min(16, len(interventions) * 8)
    cause_effect_score += min(14, len(last_actions) * 3)
    cause_effect_score += min(14, len(replay_events) * 5)
    cause_effect_score += min(10, len(alerts) * 3)
    cause_effect_score += 8 if flow.get("activePolicy") and flow.get("activePolicy") != "normal" else 0
    cause_effect_score = min(94, cause_effect_score)

    constraints_score = 55
    constraints_score += 10 if maintenance else 0
    constraints_score += 8 if food else 0
    constraints_score += 8 if readiness else 0
    constraints_score += 6 if state.get("staffing") else 0
    constraints_score += 6 if state.get("energy") else 0
    constraints_score = min(93, constraints_score)

    incident_score = 38
    incident_score += 16 if readiness else 0
    incident_score += 12 if guest_care else 0
    incident_score += 10 if maintenance.get("openWorkOrders") else 0
    incident_score += 8 if (signals or {}).get("signals") else 0
    incident_score += 8 if (runtime_governance or {}).get("customer_care_cases") else 0
    incident_score = min(76, incident_score)

    reviewability_score = 48
    reviewability_score += 12 if timeline else 0
    reviewability_score += 12 if replay_events else 0
    reviewability_score += 10 if physical else 0
    reviewability_score += 10 if scenario else 0
    reviewability_score += 8 if dispatches else 0
    reviewability_score += 6 if physical.get("realismNotes") else 0
    reviewability_score = min(91, reviewability_score)

    scorecard = [
        _score_item(
            "physical_grounding",
            "Physical park grounding",
            physical_score,
            [
                f"{len(landmarks)} landmarks",
                f"{len(queues)} queue footprints",
                f"{len(service_routes)} service routes",
                f"{len(facilities)} facilities",
            ],
            [] if physical_score >= 85 else ["Normalize map scale and SVG coordinates for spatial reasoning."],
        ),
        _score_item(
            "guest_movement",
            "Guest movement realism",
            movement_score,
            [
                f"{len(guest_groups)} aggregate guest groups",
                f"{len(paths)} path segments",
                "Groups include mood, pace, and destination." if guest_groups else "No guest groups loaded.",
            ],
            ["No per-tick guest positions or path-by-path travel history yet."],
        ),
        _score_item(
            "cause_effect",
            "Cause/effect trace",
            cause_effect_score,
            [
                f"{len(interventions)} injected events",
                f"{len(last_actions)} recent sim actions",
                f"{len(replay_events)} before/after replay events",
                f"{len(alerts)} active alerts",
            ],
            [] if replay_events or interventions or last_actions else ["Run or inject a scenario before asking Codex for a reaction review."],
        ),
        _score_item(
            "operational_constraints",
            "Operational constraints",
            constraints_score,
            [
                "Maintenance, food, incident, staffing, weather, and energy surfaces are exported.",
                f"{len(maintenance.get('openWorkOrders', []) or [])} maintenance holds",
                f"{_as_int(state.get('staffing', {}).get('openCallouts'))} open staff callouts",
            ],
        ),
        _score_item(
            "incident_lifecycle",
            "Incident lifecycle",
            incident_score,
            [
                f"Operator escalation: {readiness.get('operatorEscalation', 'unknown')}",
                f"{guest_care.get('openCases', 0)} guest-care cases in aggregate state",
                f"{len((signals or {}).get('signals', []) or [])} signal-bus items",
            ],
            ["Incident workflows still need explicit report-confirm-dispatch-resolve-after-action phases."],
        ),
        _score_item(
            "codex_reviewability",
            "Codex reviewability",
            reviewability_score,
            [
                f"{len(timeline)} timeline records",
                f"{len(replay_events)} replay events with before/after digests",
                "Snapshot includes rubric, state digest, observations, limitations, and review prompt.",
            ],
            [] if timeline else ["Capture a replay timeline before deep agent evaluation."],
        ),
    ]
    overall_score = round(sum(item["score"] for item in scorecard) / len(scorecard))

    busiest_zone = _top_item(zones, "density")
    highest_wait_ride = _top_item(rides, "waitMins")
    top_queue = _top_item(queues, "waitMins")
    counts = {
        "zones": len(zones),
        "paths": len(paths),
        "rides": len(rides),
        "landmarks": len(landmarks),
        "queues": len(queues),
        "guest_groups": len(guest_groups),
        "service_routes": len(service_routes),
        "facilities": len(facilities),
        "interventions": len(interventions),
        "timeline_records": len(timeline),
        "replay_events": len(replay_events),
    }
    scenario_key = str(scenario.get("key", "unknown"))
    review_id = f"PP-REVIEW-{scenario_key}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    missing_capabilities = sorted({missing for item in scorecard for missing in item.get("missing", [])})
    recommended_next_fixes = [
        "Move guest groups along paths over time instead of only changing aggregate counts.",
        "Add explicit incident lifecycle phases for report, verification, dispatch, resolution, and after-action review.",
        "Separate raw backend truth from demo fallback values so realism review cannot be masked by UI defaults.",
        "Persist replay events outside process memory for repeatable seeded scenario comparisons.",
    ]
    if overall_score >= 78:
        readiness_status = "reviewable"
    elif overall_score >= 65:
        readiness_status = "prototype_review"
    else:
        readiness_status = "not_ready"

    codex_review_prompt = (
        "Review this ParkPulse simulation snapshot as an operations-realism evaluator. "
        "Judge whether the simulated park feels believable enough for agent training and evaluation. "
        "Focus on physical map plausibility, guest movement, queue and density reactions, incident escalation, "
        "staff response, safety guardrails, and whether the timeline gives enough cause/effect evidence. "
        "Return concrete missing pieces and the next highest-impact implementation fixes."
    )

    return {
        "review_id": review_id,
        "created_at": _utc_now(),
        "domain": "amusement_park_operations",
        "status": readiness_status,
        "overall_score": overall_score,
        "scenario": {
            "key": scenario_key,
            "name": scenario.get("name", "Unknown scenario"),
            "description": scenario.get("description", ""),
            "condition": scenario.get("condition", ""),
            "active_policy": flow.get("activePolicy", "normal"),
        },
        "sim_time": state.get("simTime", {}),
        "state_digest": {
            "counts": counts,
            "represented_guests": flow.get("representedGuests", 0),
            "avg_satisfaction": flow.get("avgSatisfaction", 0),
            "busiest_zone": busiest_zone,
            "highest_wait_ride": highest_wait_ride,
            "top_queue": top_queue,
            "weather": state.get("weather", {}),
            "staffing": state.get("staffing", {}),
            "incident_readiness": readiness,
            "guest_care": guest_care,
        },
        "observation_surface": {
            "frontend": [
                "layered physical map",
                "scenario console",
                "signal intake and fusion console",
                "action bus and receiver alignment",
                "policy monitor link",
            ],
            "api": [
                "GET /api/park/state",
                "POST /api/park/simulate",
                "POST /api/park/agent-run",
                "POST /api/park/signals/intake",
                "GET /api/park/review-snapshot",
                "GET /api/park/replay",
                "POST /api/park/replay/start",
            ],
        },
        "scorecard": scorecard,
        "timeline": timeline,
        "replay": replay or {"mode": "in_memory_simulation_replay", "event_count": 0, "events": []},
        "realism_notes": physical.get("realismNotes", []),
        "missing_capabilities": missing_capabilities,
        "recommended_next_fixes": recommended_next_fixes,
        "codex_review_prompt": codex_review_prompt,
        "snapshot_state": state,
    }
