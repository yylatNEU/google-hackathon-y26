from __future__ import annotations

from copy import deepcopy
from typing import Any

from venue_profile import build_venue_profile


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


def build_accessibility_scope() -> dict[str, Any]:
    venue_profile = build_venue_profile()
    venue_readiness = venue_profile.get("readiness") or {}
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
        "venueProfile": {
            "status": venue_readiness.get("status"),
            "source": (venue_profile.get("realInputs") or {}).get("source"),
            "venueIdentity": venue_profile.get("venueIdentity"),
            "sourceIntegrity": venue_profile.get("sourceIntegrity"),
            "counts": venue_readiness.get("counts") or {},
            "issues": venue_readiness.get("issues") or [],
        },
    }


def build_accessibility_journey(payload: dict[str, Any], park_state: dict[str, Any]) -> dict[str, Any]:
    profile = _profile_from_payload(payload)
    venue_profile = build_venue_profile()
    venue_readiness = venue_profile.get("readiness") or {}
    venue_catalog = _venue_accessibility_catalog(venue_profile)
    if not venue_readiness.get("autofillAllowed"):
        return {
            "status": "blocked",
            "mode": "accessible_journey_builder",
            "version": ACCESSIBILITY_JOURNEY_VERSION,
            "summary": {
                "headline": "Accessibility Journey needs an active Venue Profile before it can build guest routes.",
                "durationMinutes": profile["durationMinutes"],
                "needs": profile["needs"],
                "confidence": 0,
                "requiresHumanReview": True,
                "reviewReason": "Venue Profile is not ready.",
            },
            "profile": profile,
            "planSteps": [],
            "diningOptions": [],
            "attractionOptions": [],
            "breakPlan": {"cadenceMinutes": 0, "plannedBreakCount": 0, "preferredBreaks": []},
            "staffHandoff": {
                "recommended": True,
                "owner": "Venue Profile owner",
                "message": "Connect a studio-ready Venue Profile with accessibility, safety, location, and channel-owner data.",
            },
            "guardrails": list(ACCESSIBILITY_COPY_RULES),
            "evidence": [
                {
                    "id": "venue_profile_blocked",
                    "source": "venue_profile",
                    "label": "Venue Profile readiness",
                    "detail": "Accessibility Journey does not use local seed accessibility facts.",
                }
            ],
            "venueProfile": _venue_profile_summary(venue_profile),
            "readinessIssues": venue_readiness.get("issues") or [],
            "runtime": {
                "provider": "deterministic_accessibility_planner",
                "liveParkState": bool(park_state),
                "llmControlAuthority": False,
            },
        }
    flow = park_state.get("guestFlow", {}) if isinstance(park_state.get("guestFlow"), dict) else {}
    zones = flow.get("zones", []) if isinstance(flow.get("zones"), list) else []
    rides = flow.get("rides", []) if isinstance(flow.get("rides"), list) else []
    food_inventory = park_state.get("foodInventory", {}) if isinstance(park_state.get("foodInventory"), dict) else {}
    weather = park_state.get("weather", {}) if isinstance(park_state.get("weather"), dict) else {}
    readiness = park_state.get("incidentReadiness", {}) if isinstance(park_state.get("incidentReadiness"), dict) else {}

    evidence = _build_evidence(zones, rides, food_inventory, weather, readiness, venue_profile, venue_catalog)
    zone_scores = _score_zones(profile, zones, weather, readiness, venue_catalog)
    dining_options = _dining_options(profile, food_inventory, zone_scores, venue_catalog)
    attraction_options = _attraction_options(profile, rides, zone_scores, venue_catalog)
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
        "venueProfile": _venue_profile_summary(venue_profile),
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


def _venue_profile_summary(venue_profile: dict[str, Any]) -> dict[str, Any]:
    readiness = venue_profile.get("readiness") or {}
    return {
        "venueIdentity": venue_profile.get("venueIdentity"),
        "readiness": {
            "status": readiness.get("status"),
            "autofillAllowed": readiness.get("autofillAllowed"),
            "counts": readiness.get("counts") or {},
            "issues": readiness.get("issues") or [],
            "loadedFrom": readiness.get("loadedFrom"),
        },
        "sourceIntegrity": venue_profile.get("sourceIntegrity") or {},
        "source": (venue_profile.get("realInputs") or {}).get("source"),
    }


def _location_id(name: str) -> str:
    parts = "".join(ch if ch.isalnum() else " " for ch in name).strip().split()
    if not parts:
        return "venueLocation"
    first, *rest = parts
    return first[:1].lower() + first[1:] + "".join(part[:1].upper() + part[1:] for part in rest)


def _normalize_profile_location(item: dict[str, Any], restrooms_by_zone: dict[str, list[str]]) -> dict[str, Any]:
    kind = str(item.get("kind") or "location")
    zone_id = str(item.get("zoneId") or "")
    name = str(item.get("name") or "Venue location")
    indoor = item.get("indoor") is True
    covered = item.get("covered") is True
    accessibility_note = str(item.get("accessibilityNote") or item.get("guestInstruction") or "").strip()
    sensory_note = str(item.get("sensoryNote") or item.get("guestTip") or "").strip()
    best_for = [str(value) for value in item.get("bestFor", []) if str(value).strip()] if isinstance(item.get("bestFor"), list) else []
    services = [str(value) for value in item.get("services", []) if str(value).strip()] if isinstance(item.get("services"), list) else []
    dietary_tags = [str(value) for value in item.get("dietaryTags", []) if str(value).strip()] if isinstance(item.get("dietaryTags"), list) else []
    accessible = item.get("accessible") is True or bool(accessibility_note) or kind not in {"attraction", "show"}
    caution_text = " ".join([sensory_note, str(item.get("category") or ""), str(item.get("thrillLevel") or "")]).lower()
    quiet_score = 58
    if kind == "quiet_or_cooling":
        quiet_score += 28
    if kind in {"first_aid", "guest_services", "family_service"}:
        quiet_score += 18
    if indoor:
        quiet_score += 10
    if covered:
        quiet_score += 6
    if any(token in caution_text for token in ("loud", "launch", "drop", "thrill", "flashing", "heights")):
        quiet_score -= 22
    if kind == "food":
        quiet_score -= 6
    break_features = [feature for feature in [*best_for, *services, "indoor" if indoor else "", "covered" if covered else "", "accessible public location" if accessible else ""] if feature]
    return {
        "id": _location_id(name),
        "name": name,
        "kind": kind,
        "zoneId": zone_id,
        "indoor": indoor,
        "covered": covered,
        "quietScore": max(20, min(95, quiet_score)),
        "stepFree": accessible,
        "strollerFriendly": accessible and kind != "thrill_zone",
        "restrooms": restrooms_by_zone.get(zone_id, []),
        "breakFeatures": list(dict.fromkeys(break_features)),
        "sensoryNotes": [note for note in [sensory_note, accessibility_note] if note],
        "accessibilityNote": accessibility_note,
        "sensoryNote": sensory_note,
        "dietaryTags": dietary_tags,
        "cuisine": item.get("cuisine"),
        "seating": item.get("seating"),
        "mobileOrder": item.get("mobileOrder"),
        "durationMinutes": item.get("durationMinutes"),
        "heightRequirementInches": item.get("heightRequirementInches"),
        "familyFit": item.get("familyFit"),
        "category": item.get("category"),
        "thrillLevel": item.get("thrillLevel"),
    }


def _venue_accessibility_catalog(venue_profile: dict[str, Any]) -> dict[str, Any]:
    real_inputs = venue_profile.get("realInputs") or {}
    details = real_inputs.get("locationDetails") if isinstance(real_inputs.get("locationDetails"), dict) else {}
    restrooms_by_zone: dict[str, list[str]] = {}
    for item in details.values():
        if isinstance(item, dict) and str(item.get("kind") or "") == "restrooms":
            restrooms_by_zone.setdefault(str(item.get("zoneId") or ""), []).append(str(item.get("name") or "Restroom"))
    locations = [_normalize_profile_location(item, restrooms_by_zone) for item in details.values() if isinstance(item, dict)]
    return {
        "locations": locations,
        "dining": [item for item in locations if item["kind"] == "food"],
        "attractions": [item for item in locations if item["kind"] in {"attraction", "show"}],
        "safetyInstructions": [str(item) for item in real_inputs.get("safetyInstructions", []) if str(item).strip()],
        "source": real_inputs.get("source"),
    }


def _score_zones(profile: dict[str, Any], zones: list[dict[str, Any]], weather: dict[str, Any], readiness: dict[str, Any], venue_catalog: dict[str, Any]) -> list[dict[str, Any]]:
    live_zones = _zone_by_id(zones)
    heat_index = _safe_int(weather.get("heatIndexF"), 80)
    routes_open = readiness.get("accessibilityRoutesOpen", True) is not False
    scored: list[dict[str, Any]] = []
    for meta in venue_catalog["locations"]:
        zone_id = str(meta.get("zoneId") or meta.get("id"))
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


def _dining_options(profile: dict[str, Any], food_inventory: dict[str, Any], zone_scores: list[dict[str, Any]], venue_catalog: dict[str, Any]) -> list[dict[str, Any]]:
    live_food = {str(item.get("id")): item for item in food_inventory.get("locations", []) if isinstance(item, dict) and item.get("id")}
    zone_score_by_id = {item["zoneId"]: item for item in zone_scores}
    options: list[dict[str, Any]] = []
    for meta in venue_catalog["dining"]:
        dining_id = str(meta["id"])
        live = live_food.get(dining_id, {})
        handled = {tag.lower().replace(" option", "").replace(" available", "") for tag in meta.get("dietaryTags", [])}
        requested = set(profile["allergies"])
        explicit_match = not requested or requested.issubset(handled) or not handled
        if requested and not explicit_match:
            continue
        eta = _safe_int(live.get("pickupEtaMinutes"), 15)
        backlog = _safe_int(live.get("mobileOrderBacklog"), 40)
        zone = zone_score_by_id.get(meta["zoneId"], {})
        low_crowd = "side" in str(meta.get("seating") or "").lower() or "covered" in str(meta.get("seating") or "").lower()
        score = int(zone.get("score", 50)) - eta - backlog // 8 + (20 if low_crowd else 0)
        options.append(
            {
                "id": dining_id,
                "name": meta["name"],
                "score": score,
                "pickupEtaMinutes": eta,
                "mobileOrderBacklog": backlog,
                "availableItems": list(live.get("availableItems", [])) if isinstance(live.get("availableItems"), list) else [],
                "allergyProtocols": ["trained staff confirmation", "ingredient and cross-contact check"],
                "allergensHandled": sorted(handled),
                "lowCrowdSeating": bool(low_crowd),
                "nearbyRestrooms": list(meta["restrooms"]),
                "cautions": ["Confirm ingredients and cross-contact process with trained restaurant staff before ordering."],
                "staffConfirmationRequired": bool(requested),
            }
        )
    return sorted(options, key=lambda item: item["score"], reverse=True)


def _sensory_load(meta: dict[str, Any]) -> str:
    text = " ".join(str(meta.get(key) or "") for key in ("sensoryNote", "category", "thrillLevel")).lower()
    if any(token in text for token in ("loud", "launch", "drop", "thrill", "flashing", "heights")):
        return "high"
    if meta.get("indoor") or meta.get("covered"):
        return "medium"
    return "medium"


def _attraction_options(profile: dict[str, Any], rides: list[dict[str, Any]], zone_scores: list[dict[str, Any]], venue_catalog: dict[str, Any]) -> list[dict[str, Any]]:
    zone_score_by_id = {item["zoneId"]: item for item in zone_scores}
    live_ride_by_name = {str(ride.get("name") or "").strip().lower(): ride for ride in rides if isinstance(ride, dict)}
    options: list[dict[str, Any]] = []
    for meta in venue_catalog["attractions"]:
        ride = live_ride_by_name.get(str(meta["name"]).strip().lower(), {})
        ride_id = str(ride.get("id") or meta["id"])
        status = str(ride.get("status") or "unknown")
        if status == "down":
            continue
        sensory_load = _sensory_load(meta)
        if profile["avoidLoudShows"] and sensory_load == "high":
            continue
        if profile["avoidStairs"] and not meta["stepFree"]:
            continue
        zone = zone_score_by_id.get(str(meta.get("zoneId") or ride.get("zone") or ""))
        wait = _safe_int(ride.get("waitMins"), 30)
        score = int((zone or {}).get("score", 40)) - wait
        if "low_sensory" in profile["needs"] and sensory_load == "high":
            score -= 50
        options.append(
            {
                "id": ride_id,
                "name": str(meta.get("name") or ride.get("name") or ride_id),
                "zoneName": str(ride.get("zoneName") or (zone or {}).get("name") or ""),
                "score": score,
                "waitMins": wait,
                "status": status,
                "sensoryLoad": sensory_load,
                "stepFreeQueue": meta["stepFree"],
                "transferRequired": bool(meta.get("heightRequirementInches")) or "transfer" in str(meta.get("accessibilityNote") or "").lower(),
                "indoor": meta["indoor"],
                "cautions": [note for note in [meta.get("sensoryNote"), meta.get("accessibilityNote")] if note],
            }
        )
    if "low_sensory" in profile["needs"]:
        quiet = next((location for location in zone_scores if location["score"] >= 70), zone_scores[0] if zone_scores else {})
        options.append(
            {
                "id": "profile_quiet_activity",
                "name": f"{quiet.get('name', 'Quiet area')} reset activity",
                "zoneName": str(quiet.get("name") or ""),
                "score": int(quiet.get("score", 70)) + 10,
                "waitMins": _safe_int(quiet.get("waitMins"), 10),
                "status": "open",
                "sensoryLoad": "low",
                "stepFreeQueue": True,
                "transferRequired": False,
                "indoor": bool(quiet.get("indoor")),
                "cautions": list(quiet.get("sensoryNotes") or []),
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
    if not calm_zones:
        return []
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
                "evidenceIds": ["rides_live", "venue_profile_accessibility_metadata"],
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
                "evidenceIds": ["food_live", "venue_profile_accessibility_metadata"],
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
        "evidenceIds": ["zones_live", "weather_live", "venue_profile_accessibility_metadata"],
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
    venue_profile: dict[str, Any],
    venue_catalog: dict[str, Any],
) -> list[dict[str, Any]]:
    max_density = max((_safe_int(zone.get("density"), 0) for zone in zones if isinstance(zone, dict)), default=0)
    open_rides = sum(1 for ride in rides if isinstance(ride, dict) and ride.get("status") != "down")
    venue_identity = venue_profile.get("venueIdentity") or {}
    venue_counts = (venue_profile.get("readiness") or {}).get("counts") or {}
    return [
        {"id": "zones_live", "source": "guestFlow.zones", "label": "Live crowd and comfort state", "detail": f"{len(zones)} zones read; highest density {max_density}%."},
        {"id": "rides_live", "source": "guestFlow.rides", "label": "Live ride status and waits", "detail": f"{open_rides} ride/activity options are currently usable after closure filtering."},
        {"id": "food_live", "source": "foodInventory.locations", "label": "Live dining pressure", "detail": f"{len(food_inventory.get('locations', []) if isinstance(food_inventory.get('locations'), list) else [])} dining locations read."},
        {"id": "weather_live", "source": "weather", "label": "Weather and heat context", "detail": f"Heat index {weather.get('heatIndexF', 'unknown')}F; storm risk {weather.get('stormRisk', 'unknown')}%."},
        {"id": "readiness_live", "source": "incidentReadiness", "label": "Accessibility route readiness", "detail": f"Accessibility routes open: {readiness.get('accessibilityRoutesOpen', 'unknown')}."},
        {
            "id": "venue_profile_accessibility_metadata",
            "source": "venue_profile.realInputs.locationDetails",
            "label": "Venue Profile accessibility metadata",
            "detail": f"{venue_identity.get('name', 'Active venue')} supplied {len(venue_catalog.get('locations', []))} profile locations, {len(venue_catalog.get('dining', []))} dining records, and {venue_counts.get('safetyInstructions', 0)} safety instructions.",
        },
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
