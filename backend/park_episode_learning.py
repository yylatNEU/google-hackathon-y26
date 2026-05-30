from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any


EPISODE_LIBRARY: list[dict[str, Any]] = [
    {
        "episode_id": "ep_med_foodcourt_heat_001",
        "incident_type": "medical_accessibility",
        "zone": "foodCourt1",
        "signals": ["guest_health_report", "worker_quick_tap", "first_aid_dispatch", "weather_heat_signal", "guest_app_search"],
        "categories": ["medical", "accessibility", "crowd_pressure"],
        "state_before": {"density": 78, "heatIndexF": 99, "staffReadyPct": 91},
        "best_action": "dispatch_medical_clear_lane_accessibility_support",
        "actions_taken": ["dispatch_medical_team", "clear_service_lane", "send_crowd_control", "route_wheelchair_assistance"],
        "outcome": {
            "medical_ack_seconds": 42,
            "crowd_density_delta_10min": -18,
            "access_lane_clear": True,
            "complaints_delta_15min": -7,
        },
        "labels": {"escalation_correct": True, "false_alarm": False, "response_quality": "good", "policy_safe": True},
        "lesson": "Medical worker tap plus first-aid/search/heat signals should bypass normal guest-flow optimization and dispatch medical first.",
    },
    {
        "episode_id": "ep_med_social_noise_002",
        "incident_type": "medical_accessibility",
        "zone": "entrancePlaza",
        "signals": ["social_snippet"],
        "categories": ["medical", "rumor"],
        "state_before": {"density": 42, "heatIndexF": 82},
        "best_action": "verify_before_dispatch",
        "actions_taken": ["ask_nearest_supervisor_to_verify"],
        "outcome": {"medical_ack_seconds": None, "false_alarm_confirmed": True, "guest_message_sent": False},
        "labels": {"escalation_correct": True, "false_alarm": True, "response_quality": "good", "policy_safe": True},
        "lesson": "Do not dispatch broad guest messaging or compensation from a single unverified public post.",
    },
    {
        "episode_id": "ep_access_parade_003",
        "incident_type": "accessibility_support",
        "zone": "coveredPlaza",
        "signals": ["accessibility_request", "camera_density_summary", "worker_quick_tap"],
        "categories": ["accessibility", "crowd_pressure"],
        "state_before": {"density": 86, "blockedRoute": True},
        "best_action": "protect_accessible_lane_and_staff_assist",
        "actions_taken": ["route_accessibility_support", "open_accessible_path", "hold_static_queue"],
        "outcome": {"support_ack_seconds": 64, "access_lane_clear": True, "crowd_density_delta_10min": -11},
        "labels": {"escalation_correct": True, "false_alarm": False, "response_quality": "good", "policy_safe": True},
        "lesson": "Accessibility needs get worse when crowd-control treats them as generic flow problems.",
    },
    {
        "episode_id": "ep_crowd_maze_004",
        "incident_type": "crowd_pressure",
        "zone": "coveredPlaza",
        "signals": ["guest_complaint", "worker_quick_tap", "camera_density_summary", "queue_anomaly", "social_snippet"],
        "categories": ["crowd_pressure", "panic_evacuation", "child_care"],
        "state_before": {"density": 94, "queueAbandonment": "high"},
        "best_action": "split_flow_worker_dispatch_no_public_panic",
        "actions_taken": ["send_crowd_control", "split_flow_route", "open_guest_care_case", "verify_social_claim"],
        "outcome": {"crowd_density_delta_10min": -22, "worker_ack_seconds": 38, "complaints_delta_15min": -12},
        "labels": {"escalation_correct": True, "false_alarm": False, "response_quality": "good", "policy_safe": True},
        "lesson": "When worker and density feeds corroborate complaint/social panic, escalate staff but keep public messaging calm.",
    },
    {
        "episode_id": "ep_ride_down_005",
        "incident_type": "ride_downtime",
        "zone": "coasterPlaza",
        "signals": ["queue_anomaly", "ride_status", "guest_complaint", "worker_quick_tap"],
        "categories": ["crowd_pressure", "guest_complaint"],
        "state_before": {"rideStatus": "down", "queueGuests": 700, "nearbyDensity": 89},
        "best_action": "pause_intake_split_redirect_staff_exit",
        "actions_taken": ["pause_queue_intake", "split_guest_reroute", "send_crowd_control"],
        "outcome": {"moved_guests": 520, "take_rate": 0.41, "complaints_delta_15min": -9},
        "labels": {"escalation_correct": True, "false_alarm": False, "response_quality": "good", "policy_safe": True},
        "lesson": "Split destinations outperform one-destination redirects when the anchor ride is down.",
    },
    {
        "episode_id": "ep_food_mobile_006",
        "incident_type": "food_spike",
        "zone": "foodCourt1",
        "signals": ["mobile_order_pressure", "guest_complaint", "inventory_stockout"],
        "categories": ["guest_complaint", "crowd_pressure"],
        "state_before": {"pickupEtaMinutes": 34, "cartAbandonment": "high"},
        "best_action": "suppress_stockout_items_redirect_orders",
        "actions_taken": ["suppress_low_inventory_items", "promote_nearby_capacity", "update_pickup_eta"],
        "outcome": {"take_rate": 0.36, "pickup_eta_delta": -12, "stockout_avoided": True},
        "labels": {"escalation_correct": True, "false_alarm": False, "response_quality": "good", "policy_safe": True},
        "lesson": "Do not accept orders that cannot be fulfilled; redirect demand with accurate pickup promises.",
    },
    {
        "episode_id": "ep_equipment_fog_007",
        "incident_type": "equipment_safety",
        "zone": "coveredPlaza",
        "signals": ["equipment_telemetry", "worker_quick_tap", "guest_complaint"],
        "categories": ["equipment_safety", "crowd_pressure"],
        "state_before": {"controllerHeartbeatLoss": 2, "density": 82},
        "best_action": "hold_effects_request_technician_keep_routes_open",
        "actions_taken": ["hold_fog_effects", "request_technician", "send_worker_notification"],
        "outcome": {"equipment_hold_applied": True, "technician_ack_seconds": 74, "guest_message_sent": False},
        "labels": {"escalation_correct": True, "false_alarm": False, "response_quality": "good", "policy_safe": True},
        "lesson": "Equipment telemetry should trigger control holds and technician review, not public alarm messaging.",
    },
    {
        "episode_id": "ep_staff_shortage_008",
        "incident_type": "staff_shortage",
        "zone": "coasterPlaza",
        "signals": ["staff_callout", "worker_ack_delay", "queue_anomaly"],
        "categories": ["crowd_pressure"],
        "state_before": {"openCallouts": 18, "breakWindowsAtRisk": True},
        "best_action": "protect_breaks_reduce_lower_priority_load",
        "actions_taken": ["call_standby_pool", "reduce_low_priority_dispatch", "protect_break_windows"],
        "outcome": {"staff_stress_delta": -9, "wait_delta": 4, "policy_violation": False},
        "labels": {"escalation_correct": True, "false_alarm": False, "response_quality": "acceptable", "policy_safe": True},
        "lesson": "Protect breaks and role certification even when wait-time pressure rises.",
    },
]

_TRAINING_EPISODE_LOG: list[dict[str, Any]] = []


MIN_PROMOTION_SAMPLE_SIZE = 3


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _token_set(values: list[Any] | None) -> set[str]:
    return {str(value).lower() for value in values or [] if value}


def _episode_sources(episode: dict[str, Any]) -> set[str]:
    values = episode.get("signals", [])
    if not isinstance(values, list):
        return set()
    sources = set()
    for value in values:
        if isinstance(value, dict):
            if value.get("source"):
                sources.add(str(value["source"]).lower())
        elif value:
            sources.add(str(value).lower())
    return sources


def _episode_categories(episode: dict[str, Any]) -> set[str]:
    categories = set(episode.get("categories", []) or [])
    for value in episode.get("signals", []) if isinstance(episode.get("signals"), list) else []:
        if isinstance(value, dict):
            categories.update(value.get("categories", []) or [])
    return {str(value).lower() for value in categories if value}


def _signal_sources(signal: dict[str, Any]) -> set[str]:
    sources = {str(signal.get("source", "")).lower()} if signal.get("source") else set()
    for item in signal.get("source_signals", []) if isinstance(signal.get("source_signals"), list) else []:
        if isinstance(item, dict) and item.get("source"):
            sources.add(str(item["source"]).lower())
    return sources


def _score_episode(signal: dict[str, Any], episode: dict[str, Any]) -> tuple[float, list[str]]:
    categories = _token_set(signal.get("categories", []))
    episode_categories = _episode_categories(episode)
    sources = _signal_sources(signal)
    episode_sources = _episode_sources(episode)
    zone = str((signal.get("zone", {}) or {}).get("id", "")).lower()
    episode_zone = str(episode.get("zone", "")).lower()
    reasons: list[str] = []

    category_overlap = len(categories & episode_categories)
    source_overlap = len(sources & episode_sources)
    score = category_overlap * 0.18 + source_overlap * 0.11

    if category_overlap:
        reasons.append(f"{category_overlap} shared incident categories")
    if source_overlap:
        reasons.append(f"{source_overlap} shared signal sources")
    if zone and zone == episode_zone:
        score += 0.2
        reasons.append("same operating zone")

    signal_risk = str(signal.get("risk_level", "")).upper()
    if signal_risk == "CRITICAL" and episode.get("labels", {}).get("false_alarm") is False:
        score += 0.08
        reasons.append("confirmed high-escalation precedent")
    if "medical" in categories and episode.get("incident_type") == "medical_accessibility":
        score += 0.18
        reasons.append("medical/accessibility precedent")
    if "equipment_safety" in categories and episode.get("incident_type") == "equipment_safety":
        score += 0.18
        reasons.append("equipment-control precedent")

    return min(score, 0.98), reasons or ["weak contextual match"]


def retrieve_similar_episodes(signal: dict[str, Any], limit: int = 3) -> list[dict[str, Any]]:
    scored = []
    for episode in [*_TRAINING_EPISODE_LOG, *EPISODE_LIBRARY]:
        score, reasons = _score_episode(signal, episode)
        scored.append(
            {
                **deepcopy(episode),
                "match": round(score, 2),
                "why_match": reasons,
                "memory_source": "generated_episode" if episode in _TRAINING_EPISODE_LOG else "seeded_episode",
            }
        )
    return sorted(scored, key=lambda item: item["match"], reverse=True)[:limit]


def build_training_episode(
    signal: dict[str, Any],
    delivery: dict[str, Any],
    governance: dict[str, Any],
    park_state: dict[str, Any],
) -> dict[str, Any]:
    source_ids = [item.get("source") for item in signal.get("source_signals", []) if isinstance(item, dict)]
    if not source_ids and signal.get("source"):
        source_ids = [signal.get("source")]
    zone_id = (signal.get("zone", {}) or {}).get("id", "unknown")
    raw = f"{signal.get('id')}:{zone_id}:{','.join(str(item) for item in source_ids)}".encode("utf-8")
    response = delivery.get("response", {}) if isinstance(delivery, dict) else {}
    return {
        "episode_id": f"episode_{hashlib.sha1(raw).hexdigest()[:12]}",
        "createdAt": _now_iso(),
        "incident_type": _infer_incident_type(signal),
        "zone": zone_id,
        "categories": signal.get("categories", []),
        "best_action": "_".join(
            str(action.get("operation", "action"))
            for action in signal.get("recommended_actions", [])[:3]
            if isinstance(action, dict)
        )
        or "operator_review",
        "state_before": {
            "simTime": park_state.get("simTime", {}),
            "weather": park_state.get("weather", {}),
            "staffing": park_state.get("staffing", {}),
            "activeScenario": (park_state.get("guestFlow", {}) or {}).get("activeScenario", {}),
        },
        "signals": signal.get("source_signals", []) or [{"source": signal.get("source"), "text": signal.get("text"), "categories": signal.get("categories", [])}],
        "agent_decision": {
            "risk_level": signal.get("risk_level"),
            "confidence": signal.get("confidence"),
            "recommended_actions": signal.get("recommended_actions", []),
            "human_approval_required": signal.get("human_approval_required"),
        },
        "policy_gate": governance.get("summary", {}),
        "actions_sent": delivery.get("dispatches", []),
        "outcome_proxy": {
            "take_rate": response.get("takeRate"),
            "positive_response_rate": response.get("positiveResponseRate"),
            "follow_through_rate": response.get("reactiveFollowThroughRate"),
            "sample_size": response.get("sampleSize"),
            "status": response.get("status"),
        },
        "training_labels": {
            "good_escalation": signal.get("risk_level") in {"HIGH", "CRITICAL"},
            "false_alarm": False if signal.get("fusion", {}).get("corroboration_count", 0) >= 3 else None,
            "actionable": bool(signal.get("recommended_actions")),
            "grounded": bool(signal.get("source_signals")) or signal.get("confidence", 0) >= 0.7,
            "human_supervised": bool(signal.get("human_approval_required")),
        },
    }


def _infer_incident_type(signal: dict[str, Any]) -> str:
    categories = set(signal.get("categories", []))
    if "medical" in categories:
        return "medical_accessibility"
    if "equipment_safety" in categories:
        return "equipment_safety"
    if "panic_evacuation" in categories or "crowd_pressure" in categories:
        return "crowd_pressure"
    if "guest_complaint" in categories:
        return "guest_recovery"
    return "unusual_situation"


def build_learning_context(
    signal: dict[str, Any],
    delivery: dict[str, Any],
    governance: dict[str, Any],
    park_state: dict[str, Any],
) -> dict[str, Any]:
    similar = retrieve_similar_episodes(signal, 3)
    training_episode = build_training_episode(signal, delivery, governance, park_state)
    promotion_gate = evaluate_learning_promotion_gate(training_episode, signal, delivery, governance)
    if promotion_gate["trusted_for_planning"]:
        persistence = record_training_episode(training_episode)
    else:
        persistence = {
            "status": "blocked",
            "mode": "promotion_gate",
            "episode_id": training_episode.get("episode_id"),
            "stored_episode_count": len(_TRAINING_EPISODE_LOG),
            "bigquery_ready": True,
            "trusted_for_planning": False,
            "reasons": promotion_gate["reasons"],
        }
    confirmed = [item for item in similar if item.get("labels", {}).get("false_alarm") is False]
    false_alarms = [item for item in similar if item.get("labels", {}).get("false_alarm") is True]
    return {
        "mode": "local_episode_store_with_bigquery_export_shape",
        "dataset": "parkpulse_training_episodes",
        "similar_episodes": similar,
        "current_training_episode": training_episode,
        "promotion_gate": promotion_gate,
        "persistence": persistence,
        "retrieval_quality": _retrieval_quality(signal, similar),
        "priors": {
            "similar_count": len(similar),
            "confirmed_incident_count": len(confirmed),
            "false_alarm_count": len(false_alarms),
            "best_action": similar[0].get("best_action") if similar else None,
            "expected_response": _expected_response(similar),
        },
        "operational_timeline": _operational_timeline(signal, delivery, training_episode, similar, persistence),
        "learning_loop": [
            "Normalize raw operational feeds into signal events.",
            "Fuse partial and conflicting sources into one risk hypothesis.",
            "Retrieve similar historical episodes by source, category, zone, and outcome.",
            "Choose actions with better observed outcomes and policy-safe labels.",
            "Promote only policy-safe, observed, grounded outcomes into trusted planning memory.",
        ],
    }


def evaluate_learning_promotion_gate(
    training_episode: dict[str, Any],
    signal: dict[str, Any],
    delivery: dict[str, Any],
    governance: dict[str, Any],
    *,
    min_sample_size: int = MIN_PROMOTION_SAMPLE_SIZE,
) -> dict[str, Any]:
    response = delivery.get("response", {}) if isinstance(delivery, dict) else {}
    dispatches = delivery.get("dispatches", []) if isinstance(delivery, dict) else []
    source_signals = signal.get("source_signals", []) if isinstance(signal.get("source_signals"), list) else []
    confidence = float(signal.get("confidence", 0) or 0)
    categories = set(signal.get("categories", []) if isinstance(signal.get("categories"), list) else [])
    high_risk = bool(categories & {"medical", "panic_evacuation", "equipment_safety", "security", "child_care"})

    checks = {
        "policy_safe": _policy_gate_is_safe(governance),
        "observed_response": _has_observed_response(response),
        "sample_size_sufficient": _response_sample_size(response) >= min_sample_size,
        "grounded_signal": bool(source_signals) or confidence >= 0.7,
        "actionable": bool(signal.get("recommended_actions")) or bool(dispatches),
        "false_alarm_not_confirmed": training_episode.get("training_labels", {}).get("false_alarm") is not True,
        "human_supervised_when_high_risk": (not high_risk) or bool(signal.get("human_approval_required")),
        "secondary_risk_clear": _secondary_risk_is_clear(delivery),
    }
    reason_by_check = {
        "policy_safe": "policy gate did not prove the action was safe",
        "observed_response": "no receiver response or outcome metric has been observed",
        "sample_size_sufficient": f"observed sample size is below {min_sample_size}",
        "grounded_signal": "signal is not grounded by corroborating sources or high confidence",
        "actionable": "no recommended action or dispatched receiver payload exists",
        "false_alarm_not_confirmed": "episode is confirmed as a false alarm",
        "human_supervised_when_high_risk": "high-risk signal lacks an explicit human supervision boundary",
        "secondary_risk_clear": "secondary risk remains unresolved",
    }
    failed = [name for name, passed in checks.items() if not passed]
    status = "promoted" if not failed else "candidate_blocked"
    return {
        "status": status,
        "trusted_for_planning": not failed,
        "episode_id": training_episode.get("episode_id"),
        "min_sample_size": min_sample_size,
        "checks": checks,
        "reasons": [reason_by_check[name] for name in failed],
    }


def _policy_gate_is_safe(governance: dict[str, Any]) -> bool:
    summary = governance.get("summary", {}) if isinstance(governance, dict) else {}
    gate = summary if isinstance(summary, dict) else governance if isinstance(governance, dict) else {}
    status = str(gate.get("gate_status") or gate.get("status") or "").lower()
    if status in {"blocked", "failed", "deny", "denied"}:
        return False
    if bool(gate.get("policy_violation")):
        return False
    blocked = gate.get("blocked")
    if isinstance(blocked, bool) and blocked:
        return False
    if isinstance(blocked, (int, float)) and blocked > 0:
        return False
    violations = gate.get("violations", [])
    if isinstance(violations, list) and violations:
        return False
    allowed = gate.get("allowed")
    return bool(allowed) or status in {"allowed", "clear", "passed", "pass", "review"}


def _has_observed_response(response: dict[str, Any]) -> bool:
    if not isinstance(response, dict) or not response:
        return False
    state = str(response.get("state") or response.get("status") or "").lower()
    if state in {"observed", "acknowledged", "healthy", "complete", "completed", "success", "ok"}:
        return True
    observed_keys = (
        "takeRate",
        "positiveResponseRate",
        "reactiveFollowThroughRate",
        "acceptedCount",
        "followThroughCount",
        "acknowledgedCount",
        "applied",
    )
    return any(response.get(key) not in {None, "", 0, 0.0, False} for key in observed_keys)


def _response_sample_size(response: dict[str, Any]) -> int:
    if not isinstance(response, dict):
        return 0
    samples: list[int] = []
    for key in ("sampleSize", "acceptedCount", "followThroughCount", "acknowledgedCount"):
        try:
            value = int(response.get(key, 0) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            samples.append(value)
    if response.get("applied"):
        samples.append(1)
    return max(samples, default=0)


def _secondary_risk_is_clear(delivery: dict[str, Any]) -> bool:
    if not isinstance(delivery, dict):
        return True
    candidates = [
        delivery.get("secondary_risks"),
        delivery.get("secondaryRisks"),
        (delivery.get("simulation", {}) if isinstance(delivery.get("simulation"), dict) else {}).get("secondary_risks"),
        (delivery.get("response", {}) if isinstance(delivery.get("response"), dict) else {}).get("secondary_risks"),
    ]
    for value in candidates:
        if not value:
            continue
        risks = value if isinstance(value, list) else [value]
        for risk in risks:
            text = str(risk).lower()
            if text and "no secondary" not in text and "clear" not in text and "none" not in text:
                return False
    return True


def record_training_episode(training_episode: dict[str, Any]) -> dict[str, Any]:
    document = deepcopy(training_episode)
    document["storedAt"] = _now_iso()
    document["storage"] = "local_memory"
    existing_index = next((index for index, item in enumerate(_TRAINING_EPISODE_LOG) if item.get("episode_id") == document.get("episode_id")), None)
    if existing_index is not None:
        _TRAINING_EPISODE_LOG.pop(existing_index)
    _TRAINING_EPISODE_LOG.insert(0, document)
    del _TRAINING_EPISODE_LOG[80:]
    return {
        "status": "stored",
        "mode": "local_memory",
        "episode_id": document.get("episode_id"),
        "stored_episode_count": len(_TRAINING_EPISODE_LOG),
        "bigquery_ready": True,
        "trusted_for_planning": True,
    }


def _retrieval_quality(signal: dict[str, Any], similar: list[dict[str, Any]]) -> dict[str, Any]:
    top = similar[0] if similar else {}
    top_match = float(top.get("match", 0) or 0)
    categories = set(signal.get("categories", []))
    top_categories = set(top.get("categories", []))
    used_prior = top_match >= 0.7 and bool(categories & top_categories)
    return {
        "status": "strong_match" if top_match >= 0.85 else "usable_match" if top_match >= 0.65 else "weak_match",
        "top_match": top_match,
        "used_prior_correctly": used_prior,
        "judge_note": (
            "Retrieved episode is close enough to justify using the prior action."
            if used_prior
            else "Retrieved episode should be treated as weak context, not an action template."
        ),
    }


def _operational_timeline(
    signal: dict[str, Any],
    delivery: dict[str, Any],
    training_episode: dict[str, Any],
    similar: list[dict[str, Any]],
    persistence: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    response = delivery.get("response", {}) if isinstance(delivery, dict) else {}
    top = similar[0] if similar else {}
    expected = _expected_response(similar)
    return [
        {
            "step": "before",
            "label": "Signals detected",
            "detail": f"{len(signal.get('source_signals', []) or [signal])} feeds point to {(signal.get('zone', {}) or {}).get('name', 'the park')}.",
            "status": "done",
        },
        {
            "step": "match",
            "label": "Similar episode matched",
            "detail": f"{round(float(top.get('match', 0) or 0) * 100)}% match to {str(top.get('incident_type', 'prior episode')).replace('_', ' ')}.",
            "status": "done" if top else "pending",
        },
        {
            "step": "action",
            "label": "Action emitted",
            "detail": f"{delivery.get('summary', {}).get('total', 0)} receiver payloads sent.",
            "status": "done" if delivery.get("summary", {}).get("total", 0) else "pending",
        },
        {
            "step": "observe",
            "label": "Response observed",
            "detail": f"Take {round(float(response.get('takeRate', 0) or 0) * 100)}%, follow {round(float(response.get('reactiveFollowThroughRate', 0) or 0) * 100)}%; prior ack {expected.get('median_ack_seconds') or '--'}s.",
            "status": "done" if response else "pending",
        },
        {
            "step": "learn",
            "label": "Training row promoted" if (persistence or {}).get("status") == "stored" else "Training row gated",
            "detail": str(training_episode.get("episode_id", "episode pending")),
            "status": "done" if (persistence or {}).get("status") == "stored" else "blocked",
        },
    ]


def _expected_response(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    ack_values = [
        value
        for episode in episodes
        for key, value in (episode.get("outcome", {}) or {}).items()
        if key.endswith("ack_seconds") and isinstance(value, (int, float))
    ]
    density_values = [
        value
        for episode in episodes
        for key, value in (episode.get("outcome", {}) or {}).items()
        if "density_delta" in key and isinstance(value, (int, float))
    ]
    return {
        "median_ack_seconds": sorted(ack_values)[len(ack_values) // 2] if ack_values else None,
        "typical_density_delta_10min": round(sum(density_values) / len(density_values), 1) if density_values else None,
        "confidence_note": "Used local synthetic episode library; export shape is BigQuery-ready.",
    }


def episode_dataset_status() -> dict[str, Any]:
    scenario_counts: dict[str, int] = {}
    for episode in EPISODE_LIBRARY:
        incident_type = str(episode.get("incident_type", "unknown"))
        scenario_counts[incident_type] = scenario_counts.get(incident_type, 0) + 1
    return {
        "dataset": "parkpulse_training_episodes",
        "mode": "local_seeded_training_episodes",
        "episode_count": len(EPISODE_LIBRARY),
        "generated_episode_count": len(_TRAINING_EPISODE_LOG),
        "latest_generated_episode": deepcopy(_TRAINING_EPISODE_LOG[0]) if _TRAINING_EPISODE_LOG else None,
        "scenario_counts": scenario_counts,
        "trainable_fields": [
            "state_before",
            "signals",
            "agent_decision",
            "policy_gate",
            "actions_sent",
            "outcome_proxy",
            "training_labels",
        ],
    }
