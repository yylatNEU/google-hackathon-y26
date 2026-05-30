from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any


_signal_inbox: list[dict[str, Any]] = []

RISK_ORDER = {"WATCH": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


ZONE_ALIASES = {
    "coasterPlaza": ["coaster", "dragon", "thrill", "sky drop", "ride down"],
    "indoorHub": ["indoor", "launch", "theater", "show", "shelter"],
    "arcadeZone": ["arcade", "games", "prize"],
    "foodCourt1": ["food", "kitchen", "mobile order", "drink", "restaurant", "pizza", "first aid", "medical", "fainted"],
    "coveredPlaza": ["covered", "plaza", "barrier", "maze", "backlot", "stroller", "queue exit"],
    "entrancePlaza": ["entrance", "gate", "entry", "exit", "parking", "tram"],
}

ZONE_NAMES = {
    "coasterPlaza": "Coaster Plaza",
    "indoorHub": "Indoor Ride Hub",
    "arcadeZone": "Arcade Zone",
    "foodCourt1": "Food Court 1",
    "coveredPlaza": "Covered Plaza",
    "entrancePlaza": "Entrance Plaza",
}

CATEGORY_KEYWORDS = {
    "child_care": ["child", "kid", "crying", "parent", "guardian", "lost", "separated", "family"],
    "panic_evacuation": ["panic", "running", "evacuate", "evacuation", "stampede", "crush", "pushing", "surge"],
    "medical": ["faint", "fainted", "passed out", "medical", "injury", "hurt", "sick", "collapse", "ambulance", "dehydrated", "heat exhaustion", "first aid"],
    "equipment_safety": ["smoke", "fire", "gas", "sparking", "electrical", "vibration", "fault", "sensor", "lighting", "controller", "fog", "heartbeat", "automation"],
    "security": ["fight", "yelling", "threat", "security", "aggressive", "blocked"],
    "accessibility": ["wheelchair", "mobility", "stroller", "accessibility", "accessible", "extra care", "sensory", "autism", "assistance needed"],
    "crowd_pressure": ["crowd", "crowded", "line", "queue", "packed", "bottleneck", "overflow", "stuck"],
    "guest_complaint": ["complaint", "angry", "refund", "upset", "unfair", "long wait"],
    "rumor": ["heard", "someone said", "maybe", "possibly", "rumor", "social post", "unconfirmed"],
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _signal_id(text: str, source: str, zone_id: str | None) -> str:
    raw = f"{source}:{zone_id or ''}:{text[:320]}".encode("utf-8")
    return f"signal_{hashlib.sha1(raw).hexdigest()[:12]}"


def _infer_zone(text: str, requested_zone_id: str | None, park_state: dict[str, Any]) -> dict[str, Any]:
    if requested_zone_id:
        return {"id": requested_zone_id, "name": ZONE_NAMES.get(requested_zone_id, requested_zone_id)}

    lowered = text.lower()
    best_zone = "coveredPlaza"
    best_score = 0
    for zone_id, aliases in ZONE_ALIASES.items():
        score = sum(1 for alias in aliases if alias in lowered)
        if score > best_score:
            best_zone = zone_id
            best_score = score

    zones = (park_state.get("guestFlow", {}) if isinstance(park_state, dict) else {}).get("zones", [])
    live_zone = next((zone for zone in zones if isinstance(zone, dict) and zone.get("id") == best_zone), None)
    return {
        "id": best_zone,
        "name": (live_zone or {}).get("name", ZONE_NAMES.get(best_zone, best_zone)),
        "density": (live_zone or {}).get("density"),
        "currentGuests": (live_zone or {}).get("currentGuests"),
    }


def _classify_categories(text: str) -> tuple[list[str], float]:
    lowered = text.lower()
    scored: list[tuple[str, int]] = []
    for category, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword in lowered)
        if score:
            scored.append((category, score))
    if not scored:
        return ["unusual_situation"], 0.52
    scored.sort(key=lambda item: item[1], reverse=True)
    categories = [category for category, _ in scored[:4]]
    confidence = min(0.95, 0.58 + sum(score for _, score in scored[:4]) * 0.08)
    return categories, round(confidence, 2)


def _risk_from_categories(categories: list[str], zone: dict[str, Any], text: str) -> tuple[str, int, bool]:
    high_risk = {"panic_evacuation", "medical", "equipment_safety", "security", "child_care"}
    emergency = {"panic_evacuation", "medical"}
    density = int(zone.get("density") or 0)
    lowered = text.lower()
    if emergency.intersection(categories) or any(keyword in lowered for keyword in ["fire", "stampede", "collapse"]):
        return "CRITICAL", 4, True
    if high_risk.intersection(categories) or density >= 90:
        return "HIGH", 3, True
    if "crowd_pressure" in categories or "accessibility" in categories or density >= 75:
        return "MEDIUM", 2, False
    return "WATCH", 1, False


def _missing_info(categories: list[str], confidence: float) -> list[str]:
    missing = []
    if confidence < 0.75:
        missing.append("Exact location and nearest landmark")
    if "child_care" in categories:
        missing.extend(["Whether guardian is present", "Do not enter child name or identifying details"])
    if "panic_evacuation" in categories or "crowd_pressure" in categories:
        missing.extend(["Crowd direction", "Whether any exits or access lanes are blocked"])
    if "equipment_safety" in categories:
        missing.extend(["Whether smoke/fire is visible", "Equipment asset or controller ID"])
    if "medical" in categories:
        missing.append("Whether medical team is already on scene")
    if "rumor" in categories:
        missing.append("Verification source before public messaging")
    return list(dict.fromkeys(missing))[:5]


def _recommendations(
    categories: list[str],
    zone: dict[str, Any],
    risk_level: str,
    source: str,
    reporter_role: str | None,
) -> list[dict[str, Any]]:
    zone_id = zone.get("id", "coveredPlaza")
    zone_name = zone.get("name", "Covered Plaza")
    actions: list[dict[str, Any]] = []

    if "child_care" in categories:
        actions.append(
            {
                "action": "Open a privacy-safe family assistance case and dispatch guest services.",
                "owner": "Guest Services",
                "target": "guest",
                "operation": "open_child_care_case",
                "deadline_minutes": 2,
                "expected_impact": f"Gets trained staff to {zone_name} without exposing child or family PII.",
            }
        )
    if "panic_evacuation" in categories or "crowd_pressure" in categories:
        actions.append(
            {
                "action": "Send crowd-control staff and open a split-flow route away from the pressure point.",
                "owner": "Crowd Control",
                "target": "traffic",
                "operation": "split_flow",
                "deadline_minutes": 3 if risk_level == "CRITICAL" else 7,
                "expected_impact": f"Reduces surge risk around {zone_name} while avoiding a one-destination redirect.",
            }
        )
    if "medical" in categories:
        actions.append(
            {
                "action": "Dispatch medical team and keep emergency access lane clear.",
                "owner": "Medical",
                "target": "staff",
                "operation": "dispatch_medical",
                "deadline_minutes": 1,
                "expected_impact": "Prioritizes human response and keeps automation in decision-support mode.",
            }
        )
    if "equipment_safety" in categories:
        actions.append(
            {
                "action": "Freeze nearby automated equipment changes and request technician verification.",
                "owner": "Maintenance",
                "target": "energy",
                "operation": "hold_equipment_changes",
                "deadline_minutes": 4,
                "expected_impact": "Prevents comfort or lighting automation from masking a safety signal.",
            }
        )
    if "accessibility" in categories:
        actions.append(
            {
                "action": "Route accessibility support to the zone and protect an accessible path.",
                "owner": "Accessibility Lead",
                "target": "staff",
                "operation": "accessibility_support",
                "deadline_minutes": 5,
                "expected_impact": "Handles extra-care needs without relying on generic crowd messaging.",
            }
        )
    if "guest_complaint" in categories and not actions:
        actions.append(
            {
                "action": "Create guest recovery review and compare the complaint against live wait and delivery data.",
                "owner": "Guest Recovery",
                "target": "guest",
                "operation": "complaint_triage",
                "deadline_minutes": 10,
                "expected_impact": "Avoids issuing generic compensation before the issue is grounded.",
            }
        )

    actions.append(
        {
            "action": "Ask for one confirming observation before broad guest messaging.",
            "owner": reporter_role or source.replace("_", " ").title(),
            "target": "event",
            "operation": "verify_signal",
            "deadline_minutes": 2 if risk_level in {"HIGH", "CRITICAL"} else 8,
            "expected_impact": "Keeps the agent responsive to vague reports without amplifying rumors.",
        }
    )
    return actions[:5]


def _dispatch_payloads(signal: dict[str, Any], actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    zone = signal["zone"]
    categories = signal["categories"]
    risk_level = signal["risk_level"]
    decision_id = signal["id"]
    payloads: list[dict[str, Any]] = []

    if "medical" in categories:
        payloads.append(
            {
                "channel": "worker_device",
                "payload": {
                    "decisionId": decision_id,
                    "scenarioKey": "messy_signal_triage",
                    "role": "medical_team",
                    "targetZone": zone["id"],
                    "task": f"Dispatch medical response to {zone['name']}, keep emergency access clear, and confirm whether crowd control is needed.",
                    "priority": "high",
                    "deadlineMinutes": 1,
                    "constraints": ["no_public_medical_details", "human_supervised_response"],
                },
            }
        )
    if any(category in categories for category in ["panic_evacuation", "crowd_pressure", "child_care", "accessibility"]):
        payloads.append(
            {
                "channel": "worker_device",
                "payload": {
                    "decisionId": decision_id,
                    "scenarioKey": "messy_signal_triage",
                    "role": "accessibility_support" if "accessibility" in categories and "panic_evacuation" not in categories and "crowd_pressure" not in categories else "crowd_control" if "panic_evacuation" in categories or "crowd_pressure" in categories else "guest_services",
                    "targetZone": zone["id"],
                    "task": f"Verify report at {zone['name']}, protect access lanes, and report crowd direction.",
                    "priority": "high" if risk_level in {"HIGH", "CRITICAL"} else "normal",
                    "deadlineMinutes": 2 if risk_level == "CRITICAL" else 6,
                },
            }
        )
    if "child_care" not in categories and "medical" not in categories and "panic_evacuation" not in categories:
        payloads.append(
            {
                "channel": "guest_app",
                "payload": {
                    "decisionId": decision_id,
                    "scenarioKey": "messy_signal_triage",
                    "audience": {"segment": f"guests_near_{zone['id']}", "radiusMeters": 220},
                    "message": f"We are easing flow near {zone['name']}. Nearby lower-wait options are available in the app.",
                    "promotion": {"type": "soft_flow_nudge", "offer": "Bonus points for checking a lower-wait attraction nearby.", "expiresMinutes": 20},
                    "routingTargets": ["arcadeZone", "theaterB", "foodCourt1"],
                    "expectedTakeRate": 0.31,
                    "expectedFollowThroughRate": 0.25,
                    "estimatedMovedGuests": 420,
                },
            }
        )
    if "equipment_safety" in categories:
        payloads.append(
            {
                "channel": "equipment_controller",
                "payload": {
                    "decisionId": decision_id,
                    "scenarioKey": "messy_signal_triage",
                    "equipmentType": "facility_controls",
                    "zones": [zone["id"]],
                    "command": "hold_noncritical_automation_until_technician_check",
                    "settings": {"holdLightingChanges": True, "holdFogEffects": True},
                    "requiresHumanApproval": True,
                    "reason": "Unstructured safety signal needs technician verification.",
                },
            }
        )
    return payloads[:3]


def classify_unstructured_signal(
    *,
    text: str,
    source: str,
    zone_id: str | None,
    reporter_role: str | None,
    park_state: dict[str, Any],
) -> dict[str, Any]:
    clean_text = " ".join(text.strip().split())
    zone = _infer_zone(clean_text, zone_id, park_state)
    categories, confidence = _classify_categories(clean_text)
    risk_level, escalation_level, human_approval = _risk_from_categories(categories, zone, clean_text)
    actions = _recommendations(categories, zone, risk_level, source, reporter_role)
    signal = {
        "id": _signal_id(clean_text, source, zone.get("id")),
        "createdAt": _now_iso(),
        "source": source,
        "reporterRole": reporter_role,
        "text": clean_text,
        "categories": categories,
        "risk_level": risk_level,
        "escalation_level": escalation_level,
        "confidence": confidence,
        "zone": zone,
        "missing_info": _missing_info(categories, confidence),
        "human_approval_required": human_approval,
        "recommended_actions": actions,
        "dispatch_payloads": [],
        "map_overlay": {
            "zoneId": zone["id"],
            "tone": "risk" if risk_level in {"HIGH", "CRITICAL"} else "watch" if risk_level == "MEDIUM" else "ok",
            "pulse": risk_level in {"MEDIUM", "HIGH", "CRITICAL"},
            "label": "Messy signal",
        },
        "triage_explanation": (
            "Classified from unstructured text, then constrained by live zone pressure and policy gates. "
            "The system asks for missing facts instead of treating vague reports as perfect telemetry."
        ),
    }
    signal["dispatch_payloads"] = _dispatch_payloads(signal, actions)
    _signal_inbox.insert(0, deepcopy(signal))
    del _signal_inbox[50:]
    return signal


def realistic_signal_batch(park_state: dict[str, Any], preset: str = "crowd_care_conflict") -> list[dict[str, Any]]:
    flow = park_state.get("guestFlow", {}) if isinstance(park_state, dict) else {}
    zones = flow.get("zones", []) if isinstance(flow, dict) else []
    rides = flow.get("rides", []) if isinstance(flow, dict) else []
    covered = next((zone for zone in zones if isinstance(zone, dict) and zone.get("id") == "coveredPlaza"), {})
    coaster = next((zone for zone in zones if isinstance(zone, dict) and zone.get("id") == "coasterPlaza"), {})
    dragon = next((ride for ride in rides if isinstance(ride, dict) and ride.get("id") == "dragonCoaster"), {})
    covered_density = int(covered.get("density", 79) or 79)
    coaster_density = int(coaster.get("density", 89) or 89)
    dragon_wait = int(dragon.get("waitMins", 60) or 60)
    if preset == "health_accessibility":
        return [
            {
                "source": "guest_health_report",
                "source_label": "Guest health report",
                "zoneId": "foodCourt1",
                "text": "Someone fainted near Food Court A pickup. Guests say they may be dehydrated and medical team is needed.",
                "signal_quality": "subjective_high_urgency",
            },
            {
                "source": "worker_quick_tap",
                "source_label": "Worker device quick tap",
                "zoneId": "foodCourt1",
                "text": "Medical team needed at Food Court A. Keep crowd back and clear the service lane for first aid.",
                "signal_quality": "trusted_human_observer",
            },
            {
                "source": "accessibility_request",
                "source_label": "Accessibility request",
                "zoneId": "foodCourt1",
                "text": "Wheelchair assistance needed near Food Court A. Mobility support requested and shaded route should be protected.",
                "signal_quality": "guest_service_request",
            },
            {
                "source": "first_aid_dispatch",
                "source_label": "First-aid console",
                "zoneId": "foodCourt1",
                "text": "First aid request opened for possible fainted guest. Medical team not yet confirmed on scene.",
                "signal_quality": "operational_system",
            },
            {
                "source": "camera_density_summary",
                "source_label": "Crowd-density summary",
                "zoneId": "foodCourt1",
                "text": "Food Court A walkway is crowded and movement speed is slow around pickup counters.",
                "signal_quality": "derived_computer_vision_metric",
            },
            {
                "source": "weather_heat_signal",
                "source_label": "Heat index monitor",
                "zoneId": "foodCourt1",
                "text": "Heat index remains elevated near outdoor-to-food-court transition; dehydration risk is elevated.",
                "signal_quality": "environmental_sensor",
            },
            {
                "source": "guest_app_search",
                "source_label": "Guest app search spike",
                "zoneId": "foodCourt1",
                "text": "Searches for first aid, water, wheelchair, and medical assistance increased near Food Court A.",
                "signal_quality": "behavioral_signal",
            },
        ]
    return [
        {
            "source": "guest_complaint",
            "source_label": "Guest app complaint",
            "zoneId": "coveredPlaza",
            "text": f"The app says the maze route is open but we are stuck near the covered plaza. People are pushing and kids are crying. Density feels above {covered_density}%.",
            "signal_quality": "subjective_high_urgency",
        },
        {
            "source": "worker_quick_tap",
            "source_label": "Worker device quick tap",
            "zoneId": "coveredPlaza",
            "text": "Need backup at the barrier by maze exit. Stroller families need extra care and crowd direction is unclear.",
            "signal_quality": "trusted_human_observer",
        },
        {
            "source": "queue_anomaly",
            "source_label": "Queue sensor anomaly",
            "zoneId": "coasterPlaza",
            "text": f"Dragon Coaster queue abandonment rose while posted wait is {dragon_wait} minutes. Overflow movement toward Covered Plaza is accelerating.",
            "signal_quality": "structured_sensor",
        },
        {
            "source": "camera_density_summary",
            "source_label": "Crowd-density summary",
            "zoneId": "coveredPlaza",
            "text": f"Covered Plaza density is {covered_density}% with slow movement and direction conflict at the maze exit corridor.",
            "signal_quality": "derived_computer_vision_metric",
        },
        {
            "source": "mobile_order_pressure",
            "source_label": "Mobile order pressure",
            "zoneId": "foodCourt1",
            "text": "Food Court A mobile order cart abandonment increased and pickup ETA is climbing as guests leave the coaster area.",
            "signal_quality": "transactional_behavior",
        },
        {
            "source": "equipment_telemetry",
            "source_label": "Equipment telemetry",
            "zoneId": "coveredPlaza",
            "text": "Covered Plaza lighting controller missed two heartbeats; fog effects should be held until technician checks the controller.",
            "signal_quality": "machine_telemetry",
        },
        {
            "source": "social_snippet",
            "source_label": "Public social snippet",
            "zoneId": "coveredPlaza",
            "text": "Unconfirmed post says avoid the maze exit because it is chaos and people are panicking.",
            "signal_quality": "unverified_external",
        },
        {
            "source": "turnstile_flow",
            "source_label": "Turnstile flow",
            "zoneId": "entrancePlaza",
            "text": f"Entry is normal, but internal movement from coaster zone is heavy. Coaster Plaza density is {coaster_density}%.",
            "signal_quality": "structured_flow_counter",
        },
    ]


def fuse_signal_batch(raw_signals: list[dict[str, Any]], park_state: dict[str, Any]) -> dict[str, Any]:
    classified = [
        classify_unstructured_signal(
            text=str(item.get("text", "")),
            source=str(item.get("source", "unknown")),
            zone_id=item.get("zoneId"),
            reporter_role=None,
            park_state=park_state,
        )
        for item in raw_signals
    ]
    zone_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    for signal in classified:
        zone_id = signal.get("zone", {}).get("id", "unknown")
        zone_counts[zone_id] = zone_counts.get(zone_id, 0) + 1
        for category in signal.get("categories", []):
            category_counts[category] = category_counts.get(category, 0) + 1

    dominant_zone = max(zone_counts, key=zone_counts.get) if zone_counts else "coveredPlaza"
    dominant_categories = sorted(category_counts, key=category_counts.get, reverse=True)[:5]
    for critical_category in ("equipment_safety", "medical", "security"):
        if critical_category in category_counts and critical_category not in dominant_categories:
            dominant_categories.append(critical_category)
    max_risk = max((signal.get("risk_level", "WATCH") for signal in classified), key=lambda risk: RISK_ORDER.get(str(risk), 1))
    disagreement = len(zone_counts) > 2 or ("rumor" in category_counts and len(classified) >= 4)
    corroboration_count = max(zone_counts.values()) if zone_counts else 0
    source_count = len(classified)
    synthesized_text = (
        f"Multi-source fusion: {corroboration_count}/{source_count} sources point to {ZONE_NAMES.get(dominant_zone, dominant_zone)}. "
        f"Top categories are {', '.join(category.replace('_', ' ') for category in dominant_categories) or 'unusual situation'}. "
        f"Highest individual risk is {max_risk}. "
        f"{'External rumor conflicts with operational feeds; verify before public messaging.' if disagreement else 'Sources are directionally consistent.'}"
    )
    fused = classify_unstructured_signal(
        text=synthesized_text,
        source="signal_fusion",
        zone_id=dominant_zone,
        reporter_role="signal_fusion_agent",
        park_state=park_state,
    )
    if RISK_ORDER.get(max_risk, 1) > RISK_ORDER.get(fused["risk_level"], 1):
        fused["risk_level"] = max_risk
        fused["escalation_level"] = RISK_ORDER.get(max_risk, fused["escalation_level"])
        fused["human_approval_required"] = max_risk in {"HIGH", "CRITICAL"}
        fused["map_overlay"]["tone"] = "risk" if max_risk in {"HIGH", "CRITICAL"} else "watch"
    fused["categories"] = list(dict.fromkeys([*dominant_categories, *fused.get("categories", [])]))[:6]
    if "equipment_safety" in fused["categories"] and not any(action.get("operation") == "hold_equipment_changes" for action in fused.get("recommended_actions", [])):
        fused["recommended_actions"].insert(
            0,
            {
                "action": "Hold nearby fog, lighting, and noncritical automation until technician verification.",
                "owner": "Maintenance",
                "target": "energy",
                "operation": "hold_equipment_changes",
                "deadline_minutes": 4,
                "expected_impact": "Turns equipment telemetry into a visible control action without automating safety decisions.",
            },
        )
    if "equipment_safety" in fused["categories"] and not any(item.get("channel") == "equipment_controller" for item in fused.get("dispatch_payloads", [])):
        fused["dispatch_payloads"].append(
            {
                "channel": "equipment_controller",
                "payload": {
                    "decisionId": fused["id"],
                    "scenarioKey": "messy_signal_fusion",
                    "equipmentType": "facility_controls",
                    "zones": [dominant_zone],
                    "command": "hold_noncritical_automation_until_technician_check",
                    "settings": {"holdLightingChanges": True, "holdFogEffects": True},
                    "requiresHumanApproval": True,
                    "reason": "Equipment telemetry corroborated a messy crowd-care signal.",
                },
            }
        )
    fused["confidence"] = round(min(0.96, max(fused.get("confidence", 0.7), 0.58 + corroboration_count * 0.06 - (0.08 if disagreement else 0))), 2)
    fused["source_signals"] = [
        {
            "id": signal.get("id"),
            "source": raw.get("source"),
            "source_label": raw.get("source_label"),
            "signal_quality": raw.get("signal_quality"),
            "risk_level": signal.get("risk_level"),
            "categories": signal.get("categories", []),
            "zone": signal.get("zone", {}),
            "text": raw.get("text"),
        }
        for raw, signal in zip(raw_signals, classified, strict=False)
    ]
    fused["fusion"] = {
        "source_count": source_count,
        "corroboration_count": corroboration_count,
        "dominant_zone": dominant_zone,
        "zone_votes": zone_counts,
        "category_votes": category_counts,
        "disagreement": disagreement,
        "agent_read": "Escalate because human complaints, worker taps, density summary, and queue movement all converge on one corridor."
        if corroboration_count >= 3
        else "Keep in watch mode until more sources agree.",
    }
    fused["triage_explanation"] = (
        "Fused subjective complaints, worker quick taps, queue anomalies, camera-density summaries, transactional signals, "
        "equipment telemetry, and social snippets. The agent separates verified operational feeds from unverified public chatter."
    )
    return fused


def latest_signals(limit: int = 20) -> dict[str, Any]:
    signals = deepcopy(_signal_inbox[:limit])
    return {
        "count": len(signals),
        "signals": signals,
        "summary": {
            "critical": sum(1 for item in signals if item.get("risk_level") == "CRITICAL"),
            "high": sum(1 for item in signals if item.get("risk_level") == "HIGH"),
            "needs_human_approval": sum(1 for item in signals if item.get("human_approval_required")),
        },
    }
