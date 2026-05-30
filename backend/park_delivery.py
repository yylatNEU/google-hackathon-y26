from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reliability import CircuitOpenError, call_with_retries, registry


_outbox: list[dict[str, Any]] = []


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _local_gcp_delivery(dispatch: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": "local_delivery_envelope",
        "agentBoundary": dispatch.get("agentBoundary"),
        "pubsub": {"status": "skipped", "reason": "live GCP delivery adapter disabled", "event_type": "parkpulse.delivery.dispatch"},
        "fcm": {"status": "skipped", "reason": "live GCP delivery adapter disabled"},
        "firestore": {"status": "skipped", "reason": "Firestore adapter disabled"},
        "dataflow": {"status": "skipped", "reason": "Dataflow adapter disabled"},
    }


def _local_approval_delivery(decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": "local_delivery_envelope",
        "agentBoundary": decision.get("agentBoundary"),
        "pubsub": {"status": "skipped", "reason": "live GCP delivery adapter disabled", "event_type": "parkpulse.delivery.approval_decision"},
        "pseudoFirebase": {"status": "skipped", "reason": "live GCP delivery adapter disabled", "decision": decision.get("decision")},
        "firestore": {"status": "skipped", "reason": "Firestore adapter disabled"},
        "dataflow": {"status": "skipped", "reason": "Dataflow adapter disabled"},
    }


def _runtime_dir() -> Path:
    return Path(os.getenv("PARKPULSE_RUNTIME_DIR", "/tmp/parkpulse"))


def _dispatch_id(channel: str, payload: dict[str, Any]) -> str:
    raw = f"{channel}:{payload}".encode("utf-8")
    return f"dispatch_{hashlib.sha1(raw).hexdigest()[:12]}"


def _outbox_path() -> Path:
    configured = os.getenv("PARKPULSE_DELIVERY_OUTBOX")
    if configured:
        return Path(configured)
    return _runtime_dir() / "delivery_outbox.jsonl"


def _persist_dispatch(document: dict[str, Any]) -> None:
    path = _outbox_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")


def _persist_with_recovery(name: str, document: dict[str, Any], *, attempts: int = 2, base_delay: float = 0.05) -> None:
    try:
        call_with_retries(name, lambda: _persist_dispatch(document), attempts=attempts, base_delay=base_delay)
        return
    except CircuitOpenError:
        _persist_dispatch(document)
        registry.breaker(name).record_success()


def _existing_dispatch(idempotency_key: str) -> dict[str, Any] | None:
    for document in _outbox:
        if document.get("idempotencyKey") == idempotency_key:
            duplicate = deepcopy(document)
            duplicate["deduplicated"] = True
            duplicate["deduplicatedAt"] = _utc_now()
            return duplicate
    return None


def _tool_for_channel(channel: str) -> str:
    return {
        "guest_app": "dispatch_guest_message",
        "worker_device": "dispatch_worker_task",
        "equipment_controller": "dispatch_equipment_command",
    }.get(channel, "dispatch_receiver_payload")


def _default_agent_for_channel(channel: str, payload: dict[str, Any]) -> str:
    if payload.get("agentId") or payload.get("agent_id"):
        return str(payload.get("agentId") or payload.get("agent_id"))
    if channel == "guest_app":
        return "guest_flow_agent"
    if channel == "worker_device":
        return "staffing_agent"
    if channel == "equipment_controller":
        return "facilities_energy_agent"
    return "decision_bridge_agent"


def _agent_boundary_for_dispatch(channel: str, target_system: str, payload: dict[str, Any], status: str) -> dict[str, Any]:
    from park_multi_agent import enforce_agent_tool_boundary

    return enforce_agent_tool_boundary(
        _default_agent_for_channel(channel, payload),
        _tool_for_channel(channel),
        {
            "channel": channel,
            "targetSystem": target_system,
            "payload": payload,
            "status": status,
            "policy_gate_checked": bool(
                payload.get("policyGateChecked")
                or payload.get("policy_gate_checked")
                or payload.get("policyGate")
                or payload.get("policyGateStatus")
                or payload.get("decisionId")
                or payload.get("decision_id")
                or payload.get("requiresHumanApproval")
                or status == "pending_operator_approval"
            ),
        },
    )


def _durable_outbox_count() -> int:
    path = _outbox_path()
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as file:
        return sum(1 for line in file if line.strip())


def _record(channel: str, target_system: str, endpoint: str, payload: dict[str, Any], status: str = "delivered") -> dict[str, Any]:
    idempotency_key = _dispatch_id(channel, {"target": target_system, "payload": payload})
    duplicate = _existing_dispatch(idempotency_key)
    if duplicate:
        return duplicate

    boundary = _agent_boundary_for_dispatch(channel, target_system, payload, status)
    if not boundary["allowed"]:
        document = {
            "id": _dispatch_id(channel, payload),
            "createdAt": _utc_now(),
            "channel": channel,
            "targetSystem": target_system,
            "method": "POST",
            "endpoint": endpoint,
            "status": "blocked_by_agent_boundary",
            "idempotencyKey": idempotency_key,
            "payload": deepcopy(payload),
            "response": {
                "state": "blocked",
                "takeRate": 0,
                "positiveResponseRate": 0,
                "reactiveFollowThroughRate": 0,
                "sampleSize": 0,
                "signal": boundary["reason"],
            },
            "agentBoundary": boundary,
            "gcpDelivery": {
                "status": "skipped",
                "reason": "Agent Builder boundary blocked receiver dispatch.",
                "agentBoundary": boundary,
            },
        }
        try:
            _persist_with_recovery("delivery_outbox.persist", document)
            document["durable"] = True
        except Exception as error:
            document["durable"] = False
            document["durabilityError"] = str(error)[:300]
        _outbox.insert(0, document)
        del _outbox[50:]
        return document

    response = _simulate_response(channel, payload, status)
    document = {
        "id": _dispatch_id(channel, payload),
        "createdAt": _utc_now(),
        "channel": channel,
        "targetSystem": target_system,
        "method": "POST",
        "endpoint": endpoint,
        "status": status,
        "idempotencyKey": idempotency_key,
        "payload": deepcopy(payload),
        "response": response,
        "agentBoundary": boundary,
    }
    try:
        _persist_with_recovery("delivery_outbox.persist", document)
        document["durable"] = True
    except Exception as error:
        document["durable"] = False
        document["durabilityError"] = str(error)[:300]
    try:
        if (
            _env_bool("PARKPULSE_ENABLE_LIVE_GCP_DELIVERY_ADAPTER")
            or _env_bool("ENABLE_PARKPULSE_FIRESTORE")
            or _env_bool("ENABLE_PARKPULSE_DATAFLOW")
            or _env_bool("PARKPULSE_ENABLE_FIRESTORE_MIRROR", True)
        ):
            from gcp_operations import enrich_delivery_dispatch

            document["gcpDelivery"] = enrich_delivery_dispatch(document)
        else:
            document["gcpDelivery"] = _local_gcp_delivery(document)
    except Exception as error:
            fallback_delivery = _local_gcp_delivery(document)
            fallback_delivery["status"] = "degraded"
            fallback_delivery["live_error"] = str(error)[:300]
            document["gcpDelivery"] = fallback_delivery
    _outbox.insert(0, document)
    del _outbox[50:]
    return document


def _simulate_response(channel: str, payload: dict[str, Any], status: str) -> dict[str, Any]:
    scenario_key = payload.get("scenarioKey", "ride_down")
    if status == "pending_operator_approval":
        return {
            "windowMinutes": 15,
            "state": "pending",
            "takeRate": 0,
            "positiveResponseRate": 0,
            "reactiveFollowThroughRate": 0,
            "sampleSize": 0,
            "signal": "Waiting for operator approval.",
        }

    if channel == "guest_app":
        if payload.get("expectedTakeRate"):
            take_rate = float(payload.get("expectedTakeRate", 0.34) or 0.34)
            follow_rate = float(payload.get("expectedFollowThroughRate", max(0.1, take_rate - 0.05)) or max(0.1, take_rate - 0.05))
            positive_rate = min(0.92, take_rate + 0.42)
            sample_size = int(payload.get("estimatedMovedGuests", 900) or 900)
            return {
                "windowMinutes": 15,
                "state": "observed",
                "takeRate": round(take_rate, 3),
                "positiveResponseRate": round(positive_rate, 3),
                "reactiveFollowThroughRate": round(follow_rate, 3),
                "sampleSize": sample_size,
                "acceptedCount": round(sample_size * take_rate),
                "followThroughCount": round(sample_size * follow_rate),
                "sentiment": "positive" if positive_rate >= 0.72 else "mixed",
                "signal": "Custom route-mix acceptance and destination movement were observed.",
            }
        baseline = {
            "ride_down": (0.34, 0.78, 0.29, 1180),
            "food_spike": (0.28, 0.73, 0.24, 840),
            "storm_response": (0.42, 0.81, 0.35, 1620),
        }.get(scenario_key, (0.25, 0.70, 0.20, 600))
        take_rate, positive_rate, follow_rate, sample_size = baseline
        return {
            "windowMinutes": 15,
            "state": "observed",
            "takeRate": take_rate,
            "positiveResponseRate": positive_rate,
            "reactiveFollowThroughRate": follow_rate,
            "sampleSize": sample_size,
            "acceptedCount": round(sample_size * take_rate),
            "followThroughCount": round(sample_size * follow_rate),
            "sentiment": "positive" if positive_rate >= 0.72 else "mixed",
            "signal": "Guest app offer acceptance and destination movement were observed.",
        }

    if channel == "worker_device":
        ack_rate = 0.96 if payload.get("priority") == "high" else 0.86
        return {
            "windowMinutes": 10,
            "state": "observed",
            "takeRate": ack_rate,
            "positiveResponseRate": 0.88,
            "reactiveFollowThroughRate": 0.91,
            "sampleSize": 4 if payload.get("role") == "crowd_control" else 2,
            "acknowledgedCount": 4 if payload.get("role") == "crowd_control" else 2,
            "medianAckSeconds": 42 if payload.get("priority") == "high" else 78,
            "signal": "Worker task acknowledgments and movement toward target zone were observed.",
        }

    if channel == "equipment_controller":
        return {
            "windowMinutes": 5,
            "state": "observed",
            "takeRate": 1.0,
            "positiveResponseRate": 1.0,
            "reactiveFollowThroughRate": 1.0,
            "sampleSize": 1,
            "applied": True,
            "medianAckSeconds": 8,
            "signal": "BMS accepted the command and reported the target setting as active.",
        }

    return {
        "windowMinutes": 15,
        "state": "unknown",
        "takeRate": 0,
        "positiveResponseRate": 0,
        "reactiveFollowThroughRate": 0,
        "sampleSize": 0,
        "signal": "No response telemetry available.",
    }


def send_guest_promotion(payload: dict[str, Any]) -> dict[str, Any]:
    return _record("guest_app", "guest-mobile-app", "/partner/guest-app/promotions", payload)


def send_worker_notification(payload: dict[str, Any]) -> dict[str, Any]:
    return _record("worker_device", "staff-dispatch-app", "/partner/staff-dispatch/notifications", payload)


def send_equipment_command(payload: dict[str, Any]) -> dict[str, Any]:
    approval_required = bool(payload.get("requiresHumanApproval", False))
    return _record(
        "equipment_controller",
        "building-management-system",
        "/partner/bms/commands",
        payload,
        status="pending_operator_approval" if approval_required else "delivered",
    )


def latest_dispatches(limit: int = 20) -> list[dict[str, Any]]:
    return deepcopy(_outbox[:limit])


def acknowledge_dispatch(dispatch_id: str, *, actor: str, choice: str, channel: str | None = None) -> dict[str, Any]:
    now = _utc_now()
    for document in _outbox:
        if document.get("id") != dispatch_id:
            continue
        response = document.setdefault("response", {})
        response["state"] = "acknowledged"
        response["acknowledgedAt"] = now
        response["acknowledgedBy"] = actor
        response["choice"] = choice
        if document.get("channel") == "guest_app":
            response["acceptedCount"] = max(1, int(response.get("acceptedCount", 0) or 0))
            response["takeRate"] = max(float(response.get("takeRate", 0) or 0), 0.72)
            response["reactiveFollowThroughRate"] = max(float(response.get("reactiveFollowThroughRate", 0) or 0), 0.68)
            response["signal"] = f"Guest app acknowledgement received: {choice}."
        elif document.get("channel") == "worker_device":
            response["acknowledgedCount"] = max(1, int(response.get("acknowledgedCount", 0) or 0))
            response["medianAckSeconds"] = min(int(response.get("medianAckSeconds", 42) or 42), 24)
            response["signal"] = f"Worker acknowledgement received: {choice}."
        else:
            response["signal"] = f"{actor} acknowledgement received: {choice}."
        document["status"] = "acknowledged"
        document["lastAcknowledgement"] = {"actor": actor, "choice": choice, "channel": channel or document.get("channel"), "at": now}
        try:
            _persist_with_recovery("delivery_outbox.persist_ack", {"acknowledgement": deepcopy(document)})
        except Exception as error:
            document["ackDurabilityError"] = str(error)[:300]
        return deepcopy(document)
    return {
        "status": "not_found",
        "id": dispatch_id,
        "actor": actor,
        "choice": choice,
        "channel": channel,
        "acknowledgedAt": now,
    }


def record_approval_decision(
    dispatch_id: str,
    *,
    actor: str,
    decision: str,
    reason: str | None = None,
    channel: str | None = None,
) -> dict[str, Any]:
    normalized = decision.strip().lower()
    approved = normalized in {"approved", "approve", "accepted", "execute", "approved_for_execution"}
    held = normalized in {"held_for_review", "hold", "held", "rejected", "manual_review"}
    now = _utc_now()
    if not approved and not held:
        return {
            "status": "invalid_decision",
            "id": dispatch_id,
            "actor": actor,
            "decision": decision,
            "reason": "decision must be approved or held_for_review",
            "decidedAt": now,
        }

    for document in _outbox:
        if document.get("id") != dispatch_id:
            continue

        next_status = "approved_for_execution" if approved else "held_for_review"
        approval_decision = {
            "approved": approved,
            "held_for_review": held,
            "decision": "approved" if approved else "held_for_review",
            "actor": actor,
            "reason": reason or ("Operator approved execution." if approved else "Operator held dispatch for manual review."),
            "channel": channel or document.get("channel"),
            "decidedAt": now,
            "agentBoundary": document.get("agentBoundary"),
        }
        response = document.setdefault("response", {})
        response["state"] = next_status
        response["approved"] = approved
        response["heldForReview"] = held
        response["decidedAt"] = now
        response["decisionReason"] = approval_decision["reason"]
        response["signal"] = (
            f"Operator approved execution: {approval_decision['reason']}"
            if approved
            else f"Operator held for review: {approval_decision['reason']}"
        )
        document["status"] = next_status
        document["approvalDecision"] = approval_decision
        document["lastAcknowledgement"] = {
            "actor": actor,
            "choice": approval_decision["decision"],
            "channel": channel or document.get("channel"),
            "at": now,
        }
        try:
            if (
                _env_bool("PARKPULSE_ENABLE_LIVE_GCP_DELIVERY_ADAPTER")
                or _env_bool("ENABLE_PARKPULSE_FIRESTORE")
                or _env_bool("ENABLE_PARKPULSE_DATAFLOW")
                or _env_bool("PARKPULSE_ENABLE_FIRESTORE_MIRROR", True)
            ):
                from gcp_operations import publish_approval_decision

                document["approvalDelivery"] = publish_approval_decision(document, approval_decision)
            else:
                document["approvalDelivery"] = _local_approval_delivery(approval_decision)
        except Exception as error:
            fallback_delivery = _local_approval_delivery(approval_decision)
            fallback_delivery["status"] = "degraded"
            fallback_delivery["live_error"] = str(error)[:300]
            document["approvalDelivery"] = fallback_delivery
        try:
            _persist_with_recovery(
                "delivery_outbox.persist_approval",
                {"approvalDecision": deepcopy(document)},
            )
            document["approvalDurable"] = True
        except Exception as error:
            document["approvalDurable"] = False
            document["approvalDurabilityError"] = str(error)[:300]
        return deepcopy(document)

    return {
        "status": "not_found",
        "id": dispatch_id,
        "actor": actor,
        "decision": decision,
        "channel": channel,
        "decidedAt": now,
    }


def delivery_outbox_status() -> dict[str, Any]:
    circuit_breakers = {
        name: registry.breaker(name).snapshot()
        for name in [
            "delivery_outbox.persist",
            "delivery_outbox.persist_ack",
            "delivery_outbox.persist_approval",
        ]
        if name in registry.breakers
    }
    open_circuits = [name for name, snapshot in circuit_breakers.items() if snapshot.get("state") == "open"]
    try:
        durable_count = _durable_outbox_count()
        durable_ready = True
        error = None
    except Exception as exc:
        durable_count = 0
        durable_ready = False
        error = str(exc)[:300]
    return {
        "mode": "durable_jsonl_outbox",
        "memory_depth": len(_outbox),
        "durable_count": durable_count,
        "path": str(_outbox_path()),
        "ready": durable_ready and not open_circuits,
        "error": error or (f"open delivery circuits: {', '.join(open_circuits)}" if open_circuits else None),
        "circuit_breakers": circuit_breakers,
        "processing": "append-first, idempotency-keyed dispatch records; partner retries can replay durable rows safely",
    }


def delivery_contract() -> dict[str, Any]:
    return {
        "name": "ParkPulse Action Delivery REST Port",
        "purpose": "Transforms agent decisions into guest app promotions, worker notifications, and equipment commands.",
        "ports": [
            {
                "channel": "guest_app",
                "method": "POST",
                "endpoint": "/api/park/delivery/guest-promotion",
                "delivers": "Promotions and rerouting nudges to affected guest segments.",
            },
            {
                "channel": "worker_device",
                "method": "POST",
                "endpoint": "/api/park/delivery/worker-notification",
                "delivers": "Task notifications to staff leads or worker devices.",
            },
            {
                "channel": "equipment_controller",
                "method": "POST",
                "endpoint": "/api/park/delivery/equipment-command",
                "delivers": "Simple HVAC, lighting, and facility setting changes through a BMS adapter.",
            },
        ],
        "guardrails": [
            "Ride safety and maintenance clearances are never automated.",
            "Guest messages use aggregate segments, not guest PII.",
            "Equipment commands are limited to comfort and load settings; safety-critical commands require approval.",
        ],
        "durability": delivery_outbox_status(),
    }


def build_delivery_plan(
    scenario_key: str,
    selected_action: dict[str, Any],
    park_state: dict[str, Any],
    decision_id: str,
    action_mix: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    target = selected_action.get("target")
    action = selected_action.get("action")
    flow = park_state.get("guestFlow", {})
    active_scenario = flow.get("activeScenario", {})
    rides = flow.get("rides", []) if isinstance(flow, dict) else []
    zones = flow.get("zones", []) if isinstance(flow, dict) else []
    disrupted_ride = _primary_disrupted_ride(rides)
    disrupted_zone = _zone_for_ride(disrupted_ride, zones)
    ride_name = disrupted_ride.get("name", "Dragon Coaster")
    zone_name = disrupted_zone.get("name", "Coaster Plaza")
    zone_id = disrupted_zone.get("id", "coasterPlaza")
    if _is_food_response(scenario_key, target, action):
        food_zone = _food_pressure_zone(zones)
        zone_name = food_zone.get("name", "Food Court A")
        zone_id = food_zone.get("id", "foodCourt1")
        ride_name = zone_name
    alternatives = _routing_alternatives(disrupted_ride, rides)
    alternative_names = ", ".join(item["name"] for item in alternatives[:3]) or "nearby indoor attractions"
    alternative_ids = [item["id"] for item in alternatives] or ["theaterB", "arcade", "foodCourt1"]
    weather = park_state.get("weather", {})
    energy = park_state.get("energy", {})
    hvac = (
        (action_mix or {}).get("facilities", {}).get("hvac", {})
        if isinstance((action_mix or {}).get("facilities", {}), dict)
        else {}
    )

    dispatches: list[dict[str, Any]] = []

    if action_mix:
        dispatches.extend(_dispatch_from_action_mix(scenario_key, action_mix, decision_id, ride_name, zone_id, zone_name))
        if dispatches and (target, action) in {
            ("ride", "reroute"),
            ("traffic", "redirect_food"),
            ("staff", "redeploy"),
            ("food", "suppress_item"),
            ("energy", "protect_hvac"),
        }:
            return dispatches

    def has_worker_role(role: str) -> bool:
        role_key = str(role or "").lower()
        return any(
            dispatch.get("channel") == "worker_device"
            and str((dispatch.get("payload") or {}).get("role") or "").lower() == role_key
            for dispatch in dispatches
            if isinstance(dispatch, dict)
        )

    if scenario_key == "ride_down" or (target, action) in {("ride", "reroute"), ("traffic", "redirect_food")}:
        dispatches.append(
            send_guest_promotion(
                {
                    "decisionId": decision_id,
                    "scenarioKey": scenario_key,
                    "audience": {
                        "segment": f"guests_near_{zone_id}",
                        "radiusMeters": 350,
                        "exclude": ["guests_already_in_indoor_launch_queue"],
                    },
                    "message": f"{ride_name} is temporarily unavailable. Visit {alternative_names} now for shorter waits.",
                    "promotion": {
                        "type": "ride_or_food_nudge",
                        "offer": "Bonus points for Theater B or Arcade Zone check-in within 30 minutes.",
                        "expiresMinutes": 30,
                    },
                    "routingTargets": [*alternative_ids, "foodCourt1"],
                }
            )
        )
        dispatches.append(
            send_worker_notification(
                {
                    "decisionId": decision_id,
                    "scenarioKey": scenario_key,
                    "role": "crowd_control",
                    "targetZone": zone_id,
                    "task": f"Move two crowd-control staff to {zone_name} exit and covered route junction.",
                    "priority": "high",
                    "deadlineMinutes": 10,
                }
            )
        )

    if scenario_key == "staff_shortage" or (target, action) == ("staff", "redeploy"):
        dispatches.append(
            send_worker_notification(
                {
                    "decisionId": decision_id,
                    "scenarioKey": scenario_key,
                    "role": "staffing_lead",
                    "targetZone": "coasterPlaza",
                    "task": "Redeploy cross-trained greeters to crowd flow while protecting ride-operator breaks.",
                    "priority": "high",
                    "deadlineMinutes": 8,
                    "constraints": ["do_not_move_uncertified_ride_operators", "protect_break_windows"],
                }
            )
        )

    if scenario_key == "food_spike" or (target, action) == ("food", "suppress_item"):
        dispatches.append(
            send_guest_promotion(
                {
                    "decisionId": decision_id,
                    "scenarioKey": scenario_key,
                    "audience": {"segment": "guests_near_food_court_a", "radiusMeters": 300},
                    "message": "Food Court B has faster pickup now. Pizza combo and drink pickup are available with shorter lines.",
                    "promotion": {"type": "mobile_order_redirect", "offer": "10% drink offer at Food Court B.", "expiresMinutes": 25},
                    "suppressItems": ["chicken_tenders", "bottled_drinks"],
                    "promoteItems": ["pizza_combo"],
                }
            )
        )

    if scenario_key == "storm_response" or (target, action) == ("energy", "protect_hvac"):
        dispatches.append(
            send_equipment_command(
                {
                    "decisionId": decision_id,
                    "scenarioKey": scenario_key,
                    "equipmentType": "hvac",
                    "zones": hvac.get("operatorRequestedZones") if isinstance(hvac.get("operatorRequestedZones"), list) and hvac.get("operatorRequestedZones") else ["indoorHub", "arcadeZone", "coveredPlaza"],
                    "command": "protect_comfort_setpoint",
                    "settings": {
                        "coolingSetpointF": 72 if int(weather.get("heatIndexF", 90) or 90) >= 90 else 74,
                        "shedLoadAllowed": False,
                        "demandChargeRisk": energy.get("demandChargeRisk", "normal"),
                    },
                    "requiresHumanApproval": False,
                }
            )
        )

    if (target, action) == ("medical", "dispatch") and not has_worker_role("medical"):
        incident_zone = selected_action.get("target_zone") or selected_action.get("targetZone") or zone_name
        dispatches.append(
            send_worker_notification(
                {
                    "decisionId": decision_id,
                    "scenarioKey": scenario_key,
                    "role": "medical",
                    "targetZone": incident_zone,
                    "task": selected_action.get("label") or f"Dispatch medical team to {incident_zone}; keep details private and coordinate with Guest Services.",
                    "priority": "critical",
                    "deadlineMinutes": 3,
                    "privacy": "need_to_know",
                    "constraints": ["no_guest_medical_details_in_public_messages", "human_supervisor_required"],
                }
            )
        )

    if (target, action) == ("accessibility", "assist") and not has_worker_role("accessibility_support"):
        target_zone = selected_action.get("target_zone") or selected_action.get("targetZone") or zone_name
        dispatches.append(
            send_worker_notification(
                {
                    "decisionId": decision_id,
                    "scenarioKey": scenario_key,
                    "role": "accessibility_support",
                    "targetZone": target_zone,
                    "task": selected_action.get("label") or f"Send accessibility support to {target_zone} and route guest flow around mobility constraints.",
                    "priority": "high",
                    "deadlineMinutes": 5,
                    "privacy": "need_to_know",
                    "constraints": ["protect_dignity", "avoid_named_guest_details"],
                }
            )
        )

    if (target, action) == ("security", "respond") and not has_worker_role("security"):
        target_zone = selected_action.get("target_zone") or selected_action.get("targetZone") or zone_name
        dispatches.append(
            send_worker_notification(
                {
                    "decisionId": decision_id,
                    "scenarioKey": scenario_key,
                    "role": "security",
                    "targetZone": target_zone,
                    "task": selected_action.get("label") or f"Move security lead and crowd-control support to {target_zone}; preserve exit routes.",
                    "priority": "critical",
                    "deadlineMinutes": 4,
                    "privacy": "need_to_know",
                    "constraints": ["do_not_cause_panic", "preserve_emergency_access"],
                }
            )
        )

    if (target, action) == ("guest_services", "message"):
        dispatches.append(
            send_guest_promotion(
                {
                    "decisionId": decision_id,
                    "scenarioKey": scenario_key,
                    "audience": {"segment": selected_action.get("audience", "affected_guest_segment"), "radiusMeters": 300},
                    "message": selected_action.get("label") or "ParkPulse has updated nearby guidance. Follow app directions and staff signs for the calmest route.",
                    "promotion": {"type": "guest_service_guidance", "offer": "Updated app guidance and guest-services support.", "expiresMinutes": 20},
                }
            )
        )

    if (target, action) == ("signage", "update"):
        dispatches.append(
            send_equipment_command(
                {
                    "decisionId": decision_id,
                    "scenarioKey": scenario_key,
                    "equipmentType": "digital_signage",
                    "zones": [selected_action.get("target_zone") or selected_action.get("targetZone") or zone_id],
                    "command": "update_wayfinding_message",
                    "settings": {"message": selected_action.get("label") or "Use alternate low-wait route.", "durationMinutes": 20},
                    "requiresHumanApproval": False,
                }
            )
        )

    if (target, action) == ("queue_gate", "hold_intake"):
        dispatches.append(
            send_equipment_command(
                {
                    "decisionId": decision_id,
                    "scenarioKey": scenario_key,
                    "equipmentType": "queue_gate",
                    "zones": [zone_id],
                    "command": "pause_new_queue_intake",
                    "settings": {"ride": ride_name, "holdMinutes": selected_action.get("hold_minutes", 15)},
                    "requiresHumanApproval": False,
                }
            )
        )

    if (target, action) == ("entertainment", "activate"):
        dispatches.append(
            send_worker_notification(
                {
                    "decisionId": decision_id,
                    "scenarioKey": scenario_key,
                    "role": "entertainment_lead",
                    "targetZone": selected_action.get("target_zone") or selected_action.get("targetZone") or "coveredPlaza",
                    "task": selected_action.get("label") or "Activate low-crowd pop-up entertainment to pull demand away from pressure zones.",
                    "priority": "watch",
                    "deadlineMinutes": 12,
                }
            )
        )

    if (target, action) == ("maintenance", "inspect"):
        dispatches.append(
            send_worker_notification(
                {
                    "decisionId": decision_id,
                    "scenarioKey": scenario_key,
                    "role": "maintenance_technician",
                    "targetZone": selected_action.get("target_zone") or selected_action.get("targetZone") or zone_id,
                    "task": selected_action.get("label") or f"Inspect {ride_name}; do not reopen until maintenance clearance is logged.",
                    "priority": "critical",
                    "deadlineMinutes": 6,
                    "constraints": ["maintenance_clearance_required", "no_throughput_override"],
                }
            )
        )

    if not dispatches:
        dispatches.append(
            send_worker_notification(
                {
                    "decisionId": decision_id,
                    "scenarioKey": active_scenario.get("key", scenario_key),
                    "role": "operations_lead",
                    "targetZone": "park_ops",
                    "task": selected_action.get("label", "Review ParkPulse recommendation."),
                    "priority": "watch",
                    "deadlineMinutes": 15,
                }
            )
        )

    return dispatches


def _dispatch_from_action_mix(
    scenario_key: str,
    action_mix: dict[str, Any],
    decision_id: str,
    ride_name: str,
    zone_id: str,
    zone_name: str,
) -> list[dict[str, Any]]:
    dispatches: list[dict[str, Any]] = []
    reroute = action_mix.get("guest_reroute", {}) if isinstance(action_mix.get("guest_reroute"), dict) else {}
    target_mix = reroute.get("target_mix", []) if isinstance(reroute.get("target_mix"), list) else []
    if reroute.get("enabled") and target_mix:
        readable_mix = [
            f"{round(float(item.get('share', 0) or 0) * 100)}% {item.get('destination')}"
            for item in target_mix[:4]
        ]
        is_food_context = scenario_key == "food_spike" or bool(action_mix.get("food", {}).get("suppressItems") if isinstance(action_mix.get("food"), dict) else [])
        if is_food_context:
            audience = {
                "segment": "guests_near_food_court_a",
                "radiusMeters": 300,
                "exclude": ["guests_already_waiting_at_food_court_a"],
            }
            message = (
                f"{zone_name} is constrained right now. ParkPulse is redirecting demand: "
                f"{', '.join(readable_mix)}. {reroute.get('offer', '')}"
            )
            promotion_type = "custom_food_redirect"
        else:
            audience = {
                "segment": f"guests_near_{zone_id}",
                "radiusMeters": 350,
                "exclude": [f"guests_already_in_{ride_name.lower().replace(' ', '_')}_queue"],
            }
            message = (
                f"{ride_name} is temporarily unavailable. ParkPulse is splitting demand: "
                f"{', '.join(readable_mix)}. {reroute.get('offer', '')}"
            )
            promotion_type = "custom_route_mix"
        dispatches.append(
            send_guest_promotion(
                {
                    "decisionId": decision_id,
                    "scenarioKey": scenario_key,
                    "audience": audience,
                    "message": message,
                    "promotion": {
                        "type": promotion_type,
                        "offer": reroute.get("offer", "App guidance toward lower-wait attractions."),
                        "strength": reroute.get("promotionStrength", "medium"),
                        "expiresMinutes": 30,
                    },
                    "routingTargets": [item.get("destinationId") for item in target_mix if item.get("destinationId")],
                    "targetMix": target_mix,
                    "holdShare": reroute.get("holdShare", 0),
                    "expectedTakeRate": reroute.get("expectedTakeRate"),
                    "expectedFollowThroughRate": reroute.get("expectedFollowThroughRate"),
                    "estimatedMovedGuests": reroute.get("estimatedMovedGuests"),
                }
            )
        )

    staffing = action_mix.get("staffing", {}) if isinstance(action_mix.get("staffing"), dict) else {}
    for move in staffing.get("move_staff", []) if isinstance(staffing.get("move_staff"), list) else []:
        role = str(move.get("role", "crowd_control"))
        sensitive_role = role in {"medical", "accessibility_support", "security"}
        dispatches.append(
            send_worker_notification(
                {
                    "decisionId": decision_id,
                    "scenarioKey": scenario_key,
                    "role": role,
                    "targetZone": move.get("to", zone_name),
                    "task": f"Move {move.get('count', 1)} {role} from {move.get('from', 'available pool')} to {move.get('to', zone_name)}.",
                    "priority": "critical" if role in {"medical", "security"} else "high",
                    "deadlineMinutes": move.get("deadlineMinutes") or move.get("deadline_minutes") or (3 if role == "medical" else 10),
                    "privacy": "need_to_know" if sensitive_role else "standard",
                    "protectedBreaks": staffing.get("protectedBreaks", True),
                    "constraints": ["avoid_named_guest_details", "human_supervisor_required"] if sensitive_role else [],
                }
            )
        )

    facilities = action_mix.get("facilities", {}) if isinstance(action_mix.get("facilities"), dict) else {}
    hvac = facilities.get("hvac", {}) if isinstance(facilities.get("hvac"), dict) else {}
    if hvac.get("protectShelterComfort"):
        dispatches.append(
            send_equipment_command(
                {
                    "decisionId": decision_id,
                    "scenarioKey": scenario_key,
                    "equipmentType": "hvac",
                    "zones": ["indoorHub", "arcadeZone", "coveredPlaza"],
                    "command": "apply_custom_comfort_mix",
                    "settings": {
                        "indoorHubSetpointF": hvac.get("indoorHubSetpointF", 72),
                        "arcadeZoneSetpointF": hvac.get("arcadeZoneSetpointF", 73),
                        "shedNoncriticalLighting": hvac.get("shedNoncriticalLighting", True),
                    },
                    "requiresHumanApproval": False,
                }
            )
        )

    food = action_mix.get("food", {}) if isinstance(action_mix.get("food"), dict) else {}
    if food.get("suppressItems") or food.get("avoidExtraDemandAt"):
        dispatches.append(
            send_guest_promotion(
                {
                    "decisionId": decision_id,
                    "scenarioKey": scenario_key,
                    "audience": {"segment": "mobile_order_guests_near_food_pressure", "radiusMeters": 300},
                    "message": "Food demand is being balanced. Use promoted in-stock items and avoid overloaded pickup zones.",
                    "promotion": {"type": "food_mix_control", "offer": "Promoted in-stock items with lower pickup wait.", "expiresMinutes": 25},
                    "suppressItems": food.get("suppressItems", []),
                    "promoteItems": food.get("promoteItems", []),
                    "avoidExtraDemandAt": food.get("avoidExtraDemandAt", []),
                }
            )
        )

    guest_services = action_mix.get("guest_services", {}) if isinstance(action_mix.get("guest_services"), dict) else {}
    if guest_services.get("messages"):
        for message in guest_services.get("messages", [])[:3]:
            if not isinstance(message, dict):
                continue
            dispatches.append(
                send_guest_promotion(
                    {
                        "decisionId": decision_id,
                        "scenarioKey": scenario_key,
                        "audience": {"segment": message.get("audience", "affected_guest_segment"), "radiusMeters": message.get("radiusMeters", 300)},
                        "message": message.get("message", "Updated guidance is available in the park app."),
                        "promotion": {"type": "guest_service_guidance", "offer": message.get("offer", "Guided alternate route."), "expiresMinutes": message.get("expiresMinutes", 20)},
                    }
                )
            )

    controls = action_mix.get("controls", {}) if isinstance(action_mix.get("controls"), dict) else {}
    for sign in controls.get("signage", []) if isinstance(controls.get("signage"), list) else []:
        if not isinstance(sign, dict):
            continue
        dispatches.append(
            send_equipment_command(
                {
                    "decisionId": decision_id,
                    "scenarioKey": scenario_key,
                    "equipmentType": "digital_signage",
                    "zones": sign.get("zones", [zone_id]),
                    "command": "update_wayfinding_message",
                    "settings": {"message": sign.get("message", "Use alternate low-wait route."), "durationMinutes": sign.get("durationMinutes", 20)},
                    "requiresHumanApproval": False,
                }
            )
        )

    for gate in controls.get("queue_gates", []) if isinstance(controls.get("queue_gates"), list) else []:
        if not isinstance(gate, dict):
            continue
        dispatches.append(
            send_equipment_command(
                {
                    "decisionId": decision_id,
                    "scenarioKey": scenario_key,
                    "equipmentType": "queue_gate",
                    "zones": gate.get("zones", [zone_id]),
                    "command": gate.get("command", "pause_new_queue_intake"),
                    "settings": gate.get("settings", {"holdMinutes": 15}),
                    "requiresHumanApproval": bool(gate.get("requiresHumanApproval", False)),
                }
            )
        )

    return dispatches


def _is_food_response(scenario_key: str, target: str | None, action: str | None) -> bool:
    return scenario_key == "food_spike" or (target, action) in {("food", "suppress_item"), ("traffic", "redirect_food")}


def _food_pressure_zone(zones: list[dict[str, Any]]) -> dict[str, Any]:
    for zone in zones:
        if not isinstance(zone, dict):
            continue
        zone_id = str(zone.get("id") or "").lower()
        zone_name = str(zone.get("name") or "").lower()
        if zone_id in {"foodcourt1", "foodcourta"} or "food court a" in zone_name or zone.get("processType") == "food":
            return zone
    return {"id": "foodCourt1", "name": "Food Court A"}


def _primary_disrupted_ride(rides: list[dict[str, Any]]) -> dict[str, Any]:
    if not rides:
        return {"id": "dragonCoaster", "name": "Dragon Coaster", "zone": "coasterPlaza"}
    return max(
        rides,
        key=lambda ride: (
            100 if ride.get("status") == "down" else 40 if ride.get("status") == "constrained" else 0,
            int(ride.get("downtimeRisk", 0) or 0),
            int(ride.get("waitMins", 0) or 0),
            int(ride.get("queueGuests", 0) or 0),
        ),
    )


def _zone_for_ride(ride: dict[str, Any], zones: list[dict[str, Any]]) -> dict[str, Any]:
    zone_id = ride.get("zone", "coasterPlaza")
    for zone in zones:
        if zone.get("id") == zone_id:
            return zone
    return {"id": zone_id, "name": ride.get("zoneName", "Coaster Plaza")}


def _routing_alternatives(disrupted_ride: dict[str, Any], rides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    disrupted_id = disrupted_ride.get("id")
    available = [
        ride
        for ride in rides
        if ride.get("id") != disrupted_id and ride.get("status") != "down"
    ]
    ranked = sorted(
        available,
        key=lambda ride: (
            0 if ride.get("status") == "normal" else 1,
            int(ride.get("waitMins", 0) or 0),
            -int(ride.get("capacityPerHour", 0) or 0),
        ),
    )
    return [
        {"id": str(ride.get("id")), "name": str(ride.get("name"))}
        for ride in ranked[:3]
    ]


def delivery_summary(dispatches: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "total": len(dispatches),
        "guest_app": sum(1 for item in dispatches if item.get("channel") == "guest_app"),
        "worker_device": sum(1 for item in dispatches if item.get("channel") == "worker_device"),
        "equipment_controller": sum(1 for item in dispatches if item.get("channel") == "equipment_controller"),
        "pending_operator_approval": sum(1 for item in dispatches if item.get("status") == "pending_operator_approval"),
    }


def response_summary(dispatches: list[dict[str, Any]]) -> dict[str, Any]:
    observed = [item.get("response", {}) for item in dispatches if item.get("response", {}).get("state") == "observed"]
    if not observed:
        return {
            "observedChannels": 0,
            "takeRate": 0,
            "positiveResponseRate": 0,
            "reactiveFollowThroughRate": 0,
            "sampleSize": 0,
            "score": 0,
            "status": "waiting_for_response",
        }

    sample_size = sum(int(item.get("sampleSize", 0) or 0) for item in observed)

    def weighted(metric: str) -> float:
        if sample_size <= 0:
            return round(sum(float(item.get(metric, 0) or 0) for item in observed) / len(observed), 3)
        return round(
            sum(float(item.get(metric, 0) or 0) * int(item.get("sampleSize", 0) or 0) for item in observed) / sample_size,
            3,
        )

    take_rate = weighted("takeRate")
    positive_rate = weighted("positiveResponseRate")
    follow_rate = weighted("reactiveFollowThroughRate")
    score = round(take_rate * 35 + positive_rate * 30 + follow_rate * 35)
    return {
        "observedChannels": len(observed),
        "takeRate": take_rate,
        "positiveResponseRate": positive_rate,
        "reactiveFollowThroughRate": follow_rate,
        "sampleSize": sample_size,
        "score": max(0, min(100, score)),
        "status": "healthy" if score >= 75 else "watch",
    }
