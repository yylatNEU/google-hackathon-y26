from __future__ import annotations

from copy import deepcopy
from typing import Any


ACCESSIBILITY_JOURNEY_VERSION = "2026-06-01.mvp1"


SUPPORTED_NEEDS: list[dict[str, Any]] = [
    {
        "id": "low_sensory",
        "label": "Low sensory",
        "description": "Reduce loud shows, dense paths, long queues, and bright/high-stimulation venues.",
        "keywords": ["sensory", "autism", "autistic", "quiet", "low sensory", "noise", "loud", "overstimulated", "calm"],
    },
    {
        "id": "mobility",
        "label": "Mobility aware",
        "description": "Prefer step-free paths, shorter walks, rest points, ramps, elevators, and nearby restrooms.",
        "keywords": ["wheelchair", "mobility", "walker", "stairs", "step free", "elevator", "scooter", "elderly", "cane"],
    },
    {
        "id": "allergy",
        "label": "Allergy aware dining",
        "description": "Show only dining options with explicit allergy-handling metadata and staff confirmation steps.",
        "keywords": ["allergy", "allergic", "peanut", "tree nut", "dairy", "gluten", "soy", "egg", "shellfish"],
    },
    {
        "id": "family_care",
        "label": "Family and elder care",
        "description": "Prioritize restrooms, water, shade, indoor breaks, stroller-friendly paths, and slower pacing.",
        "keywords": ["child", "children", "kid", "stroller", "baby", "elderly", "grandparent", "bathroom", "restroom"],
    },
    {
        "id": "language",
        "label": "Language support",
        "description": "Keep instructions simple and provide staffed handoff points for translation help.",
        "keywords": ["language", "translate", "translation", "spanish", "mandarin", "chinese", "visitor", "english"],
    },
    {
        "id": "medical",
        "label": "Medical constraint",
        "description": "Prioritize first aid proximity, heat breaks, hydration, and staff handoff for uncertain needs.",
        "keywords": ["medical", "medicine", "medication", "heat", "asthma", "diabetes", "first aid", "pregnant"],
    },
]


ACCESSIBILITY_BOT_PROHIBITED_CLAIMS = [
    "guarantee_allergen_free_food",
    "diagnose_medical_condition",
    "declare_route_ada_compliant",
    "promise_staff_or_equipment_availability_without_confirmation",
    "override_ride_safety_or_height_rules",
    "collect_sensitive_medical_identity_details",
]


ACCESSIBILITY_COPY_RULES = [
    "Separate verified park facts from recommendations.",
    "For allergies, tell the guest to confirm with trained restaurant staff before ordering.",
    "For medical uncertainty or immediate danger, hand off to staff or emergency services instead of giving medical advice.",
    "Prefer short steps with named landmarks, nearby restrooms, and backup options.",
    "Do not expose internal operator, staffing, policy, or private guest data.",
]


LOCATION_ACCESSIBILITY: dict[str, dict[str, Any]] = {
    "entrancePlaza": {
        "name": "Entrance Plaza",
        "type": "arrival",
        "indoor": False,
        "quietScore": 62,
        "stepFree": True,
        "strollerFriendly": True,
        "restrooms": ["Restrooms West"],
        "breakFeatures": ["guest services nearby", "wide paths"],
        "sensoryNotes": ["arrival announcements", "moderate crowd movement"],
    },
    "coveredPlaza": {
        "name": "Covered Plaza",
        "type": "shelter",
        "indoor": False,
        "quietScore": 76,
        "stepFree": True,
        "strollerFriendly": True,
        "restrooms": ["Restrooms West", "Restrooms East"],
        "breakFeatures": ["covered seating", "rain-safe route", "shade"],
        "sensoryNotes": ["mixed traffic", "lower ride noise than Coaster Plaza"],
    },
    "indoorHub": {
        "name": "Indoor Ride Hub",
        "type": "indoor_attraction",
        "indoor": True,
        "quietScore": 68,
        "stepFree": True,
        "strollerFriendly": True,
        "restrooms": ["Restrooms West"],
        "breakFeatures": ["air conditioning", "water refill nearby", "wide indoor corridors"],
        "sensoryNotes": ["ride audio nearby", "avoid show doors during release"],
    },
    "arcadeZone": {
        "name": "Arcade Zone",
        "type": "indoor_break",
        "indoor": True,
        "quietScore": 82,
        "stepFree": True,
        "strollerFriendly": True,
        "restrooms": ["Restrooms West"],
        "breakFeatures": ["indoor seating edge", "short wait", "easy exit path"],
        "sensoryNotes": ["some game audio", "best used along the calmer outer edge"],
    },
    "foodCourt1": {
        "name": "Food Court A",
        "type": "food",
        "indoor": True,
        "quietScore": 54,
        "stepFree": True,
        "strollerFriendly": True,
        "restrooms": ["Restrooms East"],
        "breakFeatures": ["indoor seating", "water refill route"],
        "sensoryNotes": ["pickup announcements", "crowded at meal peaks"],
    },
    "foodCourtB": {
        "name": "Food Court B",
        "type": "food",
        "indoor": True,
        "quietScore": 73,
        "stepFree": True,
        "strollerFriendly": True,
        "restrooms": ["Restrooms East"],
        "breakFeatures": ["lower pickup pressure", "side seating", "staffed ordering counter"],
        "sensoryNotes": ["moderate dining noise"],
    },
    "coasterPlaza": {
        "name": "Coaster Plaza",
        "type": "thrill_zone",
        "indoor": False,
        "quietScore": 28,
        "stepFree": True,
        "strollerFriendly": False,
        "restrooms": ["Restrooms East"],
        "breakFeatures": ["shade garden nearby"],
        "sensoryNotes": ["thrill ride noise", "dense queues", "outdoor heat exposure"],
    },
    "firstAid": {
        "name": "First Aid",
        "type": "care",
        "indoor": True,
        "quietScore": 88,
        "stepFree": True,
        "strollerFriendly": True,
        "restrooms": ["Restrooms East"],
        "breakFeatures": ["staffed care location", "quiet waiting area"],
        "sensoryNotes": ["staff handoff point"],
    },
}


ATTRACTION_ACCESSIBILITY: dict[str, dict[str, Any]] = {
    "indoorLaunch": {
        "sensoryLoad": "medium",
        "loud": True,
        "stepFreeQueue": True,
        "transferRequired": True,
        "indoor": True,
        "goodFor": ["mobility_if_transfer_ok", "indoor_break_after_queue"],
        "cautions": ["ride audio and launch effects", "confirm transfer needs with staff"],
    },
    "arcade": {
        "sensoryLoad": "medium",
        "loud": False,
        "stepFreeQueue": True,
        "transferRequired": False,
        "indoor": True,
        "goodFor": ["low_sensory_edge_route", "family_care", "mobility"],
        "cautions": ["some game audio and flashing screens"],
    },
    "theaterB": {
        "sensoryLoad": "high",
        "loud": True,
        "stepFreeQueue": True,
        "transferRequired": False,
        "indoor": True,
        "goodFor": ["indoor_seating"],
        "cautions": ["scheduled show audio", "crowd release after show"],
    },
    "skyDrop": {
        "sensoryLoad": "high",
        "loud": True,
        "stepFreeQueue": False,
        "transferRequired": True,
        "indoor": False,
        "goodFor": ["thrill"],
        "cautions": ["height/thrill effects", "outdoor queue"],
    },
    "dragonCoaster": {
        "sensoryLoad": "high",
        "loud": True,
        "stepFreeQueue": False,
        "transferRequired": True,
        "indoor": False,
        "goodFor": ["thrill"],
        "cautions": ["do not recommend while down or awaiting clearance"],
    },
}


DINING_ACCESSIBILITY: dict[str, dict[str, Any]] = {
    "foodCourt1": {
        "name": "Food Court A",
        "zoneId": "foodCourt1",
        "allergyProtocols": ["staff_allergy_binder", "manager_confirmation"],
        "allergensHandled": ["dairy", "gluten", "soy"],
        "lowCrowdSeating": False,
        "nearbyRestrooms": ["Restrooms East"],
        "cautions": ["high pickup pressure during meal rush", "peanut handling not verified in seed data"],
    },
    "foodCourtB": {
        "name": "Food Court B",
        "zoneId": "foodCourtB",
        "allergyProtocols": ["staff_allergy_binder", "manager_confirmation", "separate_prep_request"],
        "allergensHandled": ["peanut", "tree nut", "dairy", "gluten", "soy"],
        "lowCrowdSeating": True,
        "nearbyRestrooms": ["Restrooms East"],
        "cautions": ["must confirm ingredients with trained staff before ordering"],
    },
}


def build_accessibility_scope() -> dict[str, Any]:
    return {
        "version": ACCESSIBILITY_JOURNEY_VERSION,
        "domain": "amusement_park_accessible_journey_builder",
        "purpose": "Customer-facing accessible journey planning from public park state, explicit accessibility metadata, and conservative safety boundaries.",
        "customer_bot_role": "preference_intake_and_plain_language_explanation",
        "planner_role": "deterministic_constraint_filtering_and_live_state_scoring",
        "human_authority": [
            "allergy ingredient confirmation",
            "medical advice or emergency response",
            "ride transfer assistance and safety rules",
            "accessibility equipment availability",
            "private accommodation decisions",
        ],
        "supported_needs": deepcopy(SUPPORTED_NEEDS),
        "minimum_intake_fields": [
            {"id": "request", "label": "What kind of help or route is needed", "required": True},
            {"id": "duration_minutes", "label": "Available time", "required": False},
            {"id": "party", "label": "Party needs such as wheelchair, stroller, child, elderly guest, allergy, or language", "required": False},
            {"id": "current_location", "label": "Current location or nearest landmark", "required": False},
            {"id": "allergies", "label": "Allergies or dietary constraints", "required": False},
        ],
        "prohibited_claims": list(ACCESSIBILITY_BOT_PROHIBITED_CLAIMS),
        "customer_copy_rules": list(ACCESSIBILITY_COPY_RULES),
        "default_safety_banner": "Plans use live park conditions and accessibility metadata, but allergies, medical needs, ride transfer help, and equipment availability must be confirmed with trained park staff.",
    }


def build_accessibility_journey(payload: dict[str, Any], park_state: dict[str, Any]) -> dict[str, Any]:
    profile = _profile_from_payload(payload)
    flow = park_state.get("guestFlow", {}) if isinstance(park_state.get("guestFlow"), dict) else {}
    zones = flow.get("zones", []) if isinstance(flow.get("zones"), list) else []
    rides = flow.get("rides", []) if isinstance(flow.get("rides"), list) else []
    food_inventory = park_state.get("foodInventory", {}) if isinstance(park_state.get("foodInventory"), dict) else {}
    weather = park_state.get("weather", {}) if isinstance(park_state.get("weather"), dict) else {}
    readiness = park_state.get("incidentReadiness", {}) if isinstance(park_state.get("incidentReadiness"), dict) else {}

    evidence = _build_evidence(zones, rides, food_inventory, weather, readiness)
    zone_scores = _score_zones(profile, zones, weather, readiness)
    dining_options = _dining_options(profile, food_inventory, zone_scores)
    attraction_options = _attraction_options(profile, rides, zone_scores)
    plan_steps = _build_steps(profile, zone_scores, dining_options, attraction_options)
    guardrails = _guardrails_for_profile(profile, readiness)
    requires_review = _requires_human_review(profile, readiness)

    headline = _headline(profile, plan_steps, dining_options)
    return {
        "status": "ok",
        "mode": "accessible_journey_builder",
        "version": ACCESSIBILITY_JOURNEY_VERSION,
        "summary": {
            "headline": headline,
            "durationMinutes": profile["durationMinutes"],
            "needs": profile["needs"],
            "confidence": _confidence(profile, plan_steps, dining_options),
            "requiresHumanReview": requires_review,
            "reviewReason": _review_reason(profile, readiness) if requires_review else None,
        },
        "profile": profile,
        "planSteps": plan_steps,
        "diningOptions": dining_options,
        "attractionOptions": attraction_options,
        "breakPlan": _break_plan(profile, plan_steps),
        "staffHandoff": _staff_handoff(profile, requires_review),
        "guardrails": guardrails,
        "evidence": evidence,
        "runtime": {
            "provider": "deterministic_accessibility_planner",
            "liveParkState": bool(park_state),
            "llmControlAuthority": False,
        },
    }


def _profile_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    request = " ".join(
        str(value or "")
        for value in [
            payload.get("request"),
            payload.get("prompt"),
            payload.get("party"),
            payload.get("notes"),
            " ".join(payload.get("needs") or []) if isinstance(payload.get("needs"), list) else "",
            " ".join(payload.get("allergies") or []) if isinstance(payload.get("allergies"), list) else str(payload.get("allergies") or ""),
        ]
    ).strip()
    lowered = " ".join(request.lower().split())
    requested_needs = set(str(need).strip() for need in payload.get("needs", []) if str(need).strip()) if isinstance(payload.get("needs"), list) else set()
    detected = {
        need["id"]
        for need in SUPPORTED_NEEDS
        if need["id"] in requested_needs or any(keyword in lowered for keyword in need["keywords"])
    }
    if not detected:
        detected.add("family_care")
    allergies = _allergens_from_payload(payload, lowered)
    if allergies:
        detected.add("allergy")
    duration = _safe_int(payload.get("durationMinutes") or payload.get("duration_minutes"), 180)
    current_location = str(payload.get("currentLocation") or payload.get("current_location") or "Entrance Plaza").strip() or "Entrance Plaza"
    return {
        "request": request or "Create an accessible park route.",
        "needs": sorted(detected),
        "allergies": allergies,
        "durationMinutes": max(45, min(360, duration)),
        "currentLocation": current_location,
        "avoidStairs": bool(payload.get("avoidStairs")) or "stairs" in lowered or "step free" in lowered or "wheelchair" in lowered,
        "needsIndoorBreaks": bool(payload.get("indoorBreaks")) or "indoor" in lowered or "heat" in lowered or "break" in lowered,
        "nearRestrooms": bool(payload.get("nearRestrooms")) or "restroom" in lowered or "bathroom" in lowered,
        "avoidLoudShows": bool(payload.get("avoidLoudShows")) or "no loud" in lowered or "loud shows" in lowered or "low sensory" in lowered,
        "minimalWalking": bool(payload.get("minimalWalking")) or "minimal walking" in lowered or "short walk" in lowered or "elderly" in lowered,
    }


def _allergens_from_payload(payload: dict[str, Any], lowered: str) -> list[str]:
    raw = payload.get("allergies")
    tokens: list[str] = []
    if isinstance(raw, list):
        tokens.extend(str(item).strip().lower() for item in raw if str(item).strip())
    elif raw:
        tokens.extend(part.strip().lower() for part in str(raw).replace("/", ",").split(",") if part.strip())
    known = ["peanut", "tree nut", "dairy", "gluten", "soy", "egg", "shellfish"]
    for item in known:
        if item in lowered and item not in tokens:
            tokens.append(item)
    if "nut" in lowered and "tree nut" not in tokens:
        tokens.append("tree nut")
    return sorted(set(tokens))


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _zone_by_id(zones: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(zone.get("id")): zone for zone in zones if isinstance(zone, dict) and zone.get("id")}


def _score_zones(profile: dict[str, Any], zones: list[dict[str, Any]], weather: dict[str, Any], readiness: dict[str, Any]) -> list[dict[str, Any]]:
    live_zones = _zone_by_id(zones)
    heat_index = _safe_int(weather.get("heatIndexF"), 80)
    routes_open = readiness.get("accessibilityRoutesOpen", True) is not False
    scored: list[dict[str, Any]] = []
    for zone_id, meta in LOCATION_ACCESSIBILITY.items():
        live = live_zones.get(zone_id, {})
        density = _safe_int(live.get("density"), 50)
        wait = _safe_int(live.get("waitMins"), 0)
        comfort = _safe_int(live.get("comfortScore"), 75)
        score = comfort + int(meta["quietScore"]) - density - wait
        reasons = [
            f"live density {density}%",
            f"comfort score {comfort}",
            f"{'indoor' if meta['indoor'] else 'outdoor/covered'} location",
        ]
        if "low_sensory" in profile["needs"]:
            score += int(meta["quietScore"]) // 3
            if int(meta["quietScore"]) < 60:
                score -= 30
                reasons.append("sensory caution")
        if profile["avoidStairs"] and not meta["stepFree"]:
            score -= 80
            reasons.append("not step-free")
        if profile["needsIndoorBreaks"] or heat_index >= 95:
            score += 24 if meta["indoor"] else 8 if "shade" in meta["breakFeatures"] else -10
            reasons.append("break suitability checked")
        if profile["nearRestrooms"]:
            score += 10 if meta["restrooms"] else -25
            reasons.append("restroom proximity checked")
        if not routes_open and profile["avoidStairs"]:
            score -= 35
            reasons.append("accessibility route status needs staff confirmation")
        scored.append(
            {
                "zoneId": zone_id,
                "name": meta["name"],
                "score": score,
                "density": density,
                "waitMins": wait,
                "comfortScore": comfort,
                "indoor": meta["indoor"],
                "stepFree": meta["stepFree"],
                "strollerFriendly": meta["strollerFriendly"],
                "restrooms": list(meta["restrooms"]),
                "breakFeatures": list(meta["breakFeatures"]),
                "sensoryNotes": list(meta["sensoryNotes"]),
                "reasons": reasons,
            }
        )
    return sorted(scored, key=lambda item: item["score"], reverse=True)


def _dining_options(profile: dict[str, Any], food_inventory: dict[str, Any], zone_scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    live_food = {str(item.get("id")): item for item in food_inventory.get("locations", []) if isinstance(item, dict) and item.get("id")}
    zone_score_by_id = {item["zoneId"]: item for item in zone_scores}
    options: list[dict[str, Any]] = []
    for dining_id, meta in DINING_ACCESSIBILITY.items():
        live = live_food.get(dining_id, {})
        handled = set(meta["allergensHandled"])
        requested = set(profile["allergies"])
        explicit_match = not requested or requested.issubset(handled)
        if requested and not explicit_match:
            continue
        eta = _safe_int(live.get("pickupEtaMinutes"), 15)
        backlog = _safe_int(live.get("mobileOrderBacklog"), 40)
        zone = zone_score_by_id.get(meta["zoneId"], {})
        score = int(zone.get("score", 50)) - eta - backlog // 8 + (20 if meta["lowCrowdSeating"] else 0)
        options.append(
            {
                "id": dining_id,
                "name": meta["name"],
                "score": score,
                "pickupEtaMinutes": eta,
                "mobileOrderBacklog": backlog,
                "availableItems": list(live.get("availableItems", [])) if isinstance(live.get("availableItems"), list) else [],
                "allergyProtocols": list(meta["allergyProtocols"]),
                "allergensHandled": list(meta["allergensHandled"]),
                "lowCrowdSeating": bool(meta["lowCrowdSeating"]),
                "nearbyRestrooms": list(meta["nearbyRestrooms"]),
                "cautions": list(meta["cautions"]),
                "staffConfirmationRequired": bool(requested),
            }
        )
    return sorted(options, key=lambda item: item["score"], reverse=True)


def _attraction_options(profile: dict[str, Any], rides: list[dict[str, Any]], zone_scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    zone_score_by_id = {item["zoneId"]: item for item in zone_scores}
    options: list[dict[str, Any]] = []
    for ride in rides:
        if not isinstance(ride, dict):
            continue
        ride_id = str(ride.get("id") or "")
        meta = ATTRACTION_ACCESSIBILITY.get(ride_id)
        if not meta:
            continue
        status = str(ride.get("status") or "unknown")
        if status == "down":
            continue
        if profile["avoidLoudShows"] and meta["loud"]:
            continue
        if profile["avoidStairs"] and not meta["stepFreeQueue"]:
            continue
        zone = zone_score_by_id.get(str(ride.get("zone") or ""))
        wait = _safe_int(ride.get("waitMins"), 30)
        score = int((zone or {}).get("score", 40)) - wait
        if "low_sensory" in profile["needs"] and meta["sensoryLoad"] == "high":
            score -= 50
        options.append(
            {
                "id": ride_id,
                "name": str(ride.get("name") or ride_id),
                "zoneName": str(ride.get("zoneName") or (zone or {}).get("name") or ""),
                "score": score,
                "waitMins": wait,
                "status": status,
                "sensoryLoad": meta["sensoryLoad"],
                "stepFreeQueue": meta["stepFreeQueue"],
                "transferRequired": meta["transferRequired"],
                "indoor": meta["indoor"],
                "cautions": list(meta["cautions"]),
            }
        )
    if "low_sensory" in profile["needs"]:
        options.append(
            {
                "id": "arcade_edge",
                "name": "Arcade Zone outer edge",
                "zoneName": "Arcade Zone",
                "score": int(zone_score_by_id.get("arcadeZone", {}).get("score", 70)) + 10,
                "waitMins": _safe_int(zone_score_by_id.get("arcadeZone", {}).get("waitMins"), 10),
                "status": "open",
                "sensoryLoad": "low_to_medium",
                "stepFreeQueue": True,
                "transferRequired": False,
                "indoor": True,
                "cautions": ["stay on the outer edge if screens or game audio become too much"],
            }
        )
    return sorted(options, key=lambda item: item["score"], reverse=True)[:4]


def _build_steps(
    profile: dict[str, Any],
    zone_scores: list[dict[str, Any]],
    dining_options: list[dict[str, Any]],
    attraction_options: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    duration = profile["durationMinutes"]
    calm_zones = [zone for zone in zone_scores if zone["zoneId"] not in {"coasterPlaza"}]
    first_break = next((zone for zone in calm_zones if zone["indoor"]), calm_zones[0])
    steps.append(_zone_step("start", "Start with a calm check-in", first_break, 20, "Begin at the lowest-pressure area that still keeps restrooms and staff help nearby."))

    if attraction_options:
        attraction = attraction_options[0]
        steps.append(
            {
                "id": "step_attraction_1",
                "type": "attraction_or_activity",
                "title": attraction["name"],
                "location": attraction["zoneName"] or attraction["name"],
                "durationMinutes": max(20, min(45, int(attraction["waitMins"]) + 15)),
                "walkMinutes": 6 if profile["minimalWalking"] else 9,
                "why": "Selected after filtering closed rides, loud/high-stimulation options, stairs, and live wait time.",
                "accessibility": [
                    "step-free queue" if attraction["stepFreeQueue"] else "staff confirmation needed for queue access",
                    "transfer required" if attraction["transferRequired"] else "no ride transfer expected for this activity",
                    f"sensory load: {attraction['sensoryLoad']}",
                ],
                "nearby": [],
                "risks": attraction["cautions"],
                "evidenceIds": ["rides_live", "accessibility_metadata"],
            }
        )

    if profile["needsIndoorBreaks"] or "low_sensory" in profile["needs"] or duration >= 120:
        second_break = next((zone for zone in calm_zones if zone["zoneId"] != first_break["zoneId"] and zone["indoor"]), first_break)
        steps.append(_zone_step("break_1", "Indoor decompression break", second_break, 25, "Adds a planned reset before fatigue, heat, or sensory load accumulates."))

    if dining_options and ("allergy" in profile["needs"] or duration >= 150):
        dining = dining_options[0]
        steps.append(
            {
                "id": "step_food_1",
                "type": "dining",
                "title": dining["name"],
                "location": dining["name"],
                "durationMinutes": max(25, min(50, int(dining["pickupEtaMinutes"]) + 18)),
                "walkMinutes": 5 if profile["minimalWalking"] else 8,
                "why": "Best available dining match for allergy metadata, lower crowd seating, pickup pressure, and restroom proximity.",
                "accessibility": [
                    "staff allergy confirmation required" if dining["staffConfirmationRequired"] else "standard dining confirmation",
                    "low-crowd seating nearby" if dining["lowCrowdSeating"] else "seating may be crowded",
                    f"pickup estimate: {dining['pickupEtaMinutes']} minutes",
                ],
                "nearby": dining["nearbyRestrooms"],
                "risks": dining["cautions"],
                "evidenceIds": ["food_live", "accessibility_metadata"],
            }
        )

    finish_zone = next((zone for zone in calm_zones if "shade" in zone["breakFeatures"] or zone["zoneId"] == "coveredPlaza"), calm_zones[0])
    steps.append(_zone_step("finish", "Finish near a flexible exit point", finish_zone, 20, "Ends near shade, restrooms, and easier staff handoff if the group needs to change plans."))
    return steps[:5]


def _zone_step(step_id: str, title: str, zone: dict[str, Any], duration: int, why: str) -> dict[str, Any]:
    return {
        "id": f"step_{step_id}",
        "type": "break_or_route",
        "title": title,
        "location": zone["name"],
        "zoneId": zone["zoneId"],
        "durationMinutes": duration,
        "walkMinutes": 4 if zone["score"] >= 120 else 7,
        "why": why,
        "accessibility": [
            "step-free route" if zone["stepFree"] else "staff confirmation needed for route",
            "indoor" if zone["indoor"] else "covered/outdoor",
            "stroller-friendly" if zone["strollerFriendly"] else "stroller caution",
        ],
        "nearby": zone["restrooms"] + zone["breakFeatures"],
        "risks": zone["sensoryNotes"],
        "evidenceIds": ["zones_live", "weather_live", "accessibility_metadata"],
    }


def _break_plan(profile: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any]:
    cadence = 35 if "low_sensory" in profile["needs"] else 45 if profile["needsIndoorBreaks"] else 60
    break_steps = [step for step in steps if step["type"] == "break_or_route"]
    return {
        "cadenceMinutes": cadence,
        "plannedBreakCount": len(break_steps),
        "preferredBreaks": [{"title": step["title"], "location": step["location"], "durationMinutes": step["durationMinutes"]} for step in break_steps],
    }


def _guardrails_for_profile(profile: dict[str, Any], readiness: dict[str, Any]) -> list[str]:
    guardrails = list(ACCESSIBILITY_COPY_RULES)
    if profile["allergies"]:
        guardrails.append("Allergy result is a dining shortlist, not an allergen-free guarantee.")
    if "medical" in profile["needs"]:
        guardrails.append("Medical constraints should be handled by First Aid or trained staff if symptoms, medication, or urgent uncertainty are involved.")
    if readiness.get("accessibilityRoutesOpen") is False:
        guardrails.append("Live accessibility route status is degraded; confirm route with staff before moving.")
    return guardrails


def _requires_human_review(profile: dict[str, Any], readiness: dict[str, Any]) -> bool:
    return bool(profile["allergies"] or "medical" in profile["needs"] or readiness.get("accessibilityRoutesOpen") is False)


def _review_reason(profile: dict[str, Any], readiness: dict[str, Any]) -> str:
    if readiness.get("accessibilityRoutesOpen") is False:
        return "Accessibility route status needs staff confirmation."
    if profile["allergies"]:
        return "Allergy handling must be confirmed by trained dining staff."
    if "medical" in profile["needs"]:
        return "Medical constraints should be reviewed by First Aid or trained staff."
    return "Staff review recommended."


def _staff_handoff(profile: dict[str, Any], requires_review: bool) -> dict[str, Any]:
    if not requires_review:
        return {
            "recommended": False,
            "owner": "Guest Services",
            "message": "No immediate staff handoff required for this plan, but Guest Services can adjust it.",
        }
    if profile["allergies"]:
        return {
            "recommended": True,
            "owner": "Dining manager or allergy-trained staff",
            "message": "Ask staff to confirm ingredients, cross-contact process, and safe ordering before purchasing food.",
        }
    if "medical" in profile["needs"]:
        return {
            "recommended": True,
            "owner": "First Aid",
            "message": "Use First Aid or trained staff for medical constraints, symptoms, medication storage, or urgent uncertainty.",
        }
    return {
        "recommended": True,
        "owner": "Accessibility Lead",
        "message": "Confirm route availability and any equipment or assistance needs before starting.",
    }


def _build_evidence(
    zones: list[dict[str, Any]],
    rides: list[dict[str, Any]],
    food_inventory: dict[str, Any],
    weather: dict[str, Any],
    readiness: dict[str, Any],
) -> list[dict[str, Any]]:
    max_density = max((_safe_int(zone.get("density"), 0) for zone in zones if isinstance(zone, dict)), default=0)
    open_rides = sum(1 for ride in rides if isinstance(ride, dict) and ride.get("status") != "down")
    return [
        {"id": "zones_live", "source": "guestFlow.zones", "label": "Live crowd and comfort state", "detail": f"{len(zones)} zones read; highest density {max_density}%."},
        {"id": "rides_live", "source": "guestFlow.rides", "label": "Live ride status and waits", "detail": f"{open_rides} ride/activity options are currently usable after closure filtering."},
        {"id": "food_live", "source": "foodInventory.locations", "label": "Live dining pressure", "detail": f"{len(food_inventory.get('locations', []) if isinstance(food_inventory.get('locations'), list) else [])} dining locations read."},
        {"id": "weather_live", "source": "weather", "label": "Weather and heat context", "detail": f"Heat index {weather.get('heatIndexF', 'unknown')}F; storm risk {weather.get('stormRisk', 'unknown')}%."},
        {"id": "readiness_live", "source": "incidentReadiness", "label": "Accessibility route readiness", "detail": f"Accessibility routes open: {readiness.get('accessibilityRoutesOpen', 'unknown')}."},
        {"id": "accessibility_metadata", "source": "accessibility_journey.metadata", "label": "Explicit accessibility metadata", "detail": "Planner used step-free, sensory, restroom, dining, and staff-confirmation metadata."},
    ]


def _headline(profile: dict[str, Any], steps: list[dict[str, Any]], dining_options: list[dict[str, Any]]) -> str:
    needs = set(profile["needs"])
    if "allergy" in needs and dining_options:
        return f"{profile['durationMinutes']}-minute accessible route with allergy-aware dining at {dining_options[0]['name']} and planned breaks."
    if "low_sensory" in needs:
        return f"{profile['durationMinutes']}-minute low-sensory route with indoor breaks, restroom proximity, and loud-show filtering."
    if "mobility" in needs:
        return f"{profile['durationMinutes']}-minute mobility-aware route using step-free stops and shorter walking segments."
    return f"{profile['durationMinutes']}-minute accessible family route with breaks, restrooms, and flexible exits."


def _confidence(profile: dict[str, Any], steps: list[dict[str, Any]], dining_options: list[dict[str, Any]]) -> int:
    confidence = 82 if steps else 55
    if "allergy" in profile["needs"] and not dining_options:
        confidence -= 25
    if profile["allergies"]:
        confidence -= 8
    if "medical" in profile["needs"]:
        confidence -= 10
    return max(35, min(92, confidence))
