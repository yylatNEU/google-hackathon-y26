from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from typing import Any

from customer_park_knowledge import customer_venue_export, validate_customer_venue_export


REQUIRED_CHANNEL_OWNERS = ("guest_app", "signage", "email", "staff_cue")
PROFILE_INTELLIGENCE_VERSION = "profile_intelligence_v1"


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _source_ids(item: dict[str, Any]) -> list[str]:
    return [str(source_id) for source_id in _as_list(item.get("source_ids")) if str(source_id or "").strip()]


def _source_catalog(export: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(export.get("source_catalog"))


def _sources(export: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(_source_catalog(export).get("sources"))


def _has_synthetic_sources(export: dict[str, Any]) -> bool:
    for source_id, source in _sources(export).items():
        source_type = _text(_as_dict(source).get("source_type")).lower()
        if "synthetic" in source_type or "synthetic" in str(source_id).lower():
            return True
    return False


def profile_intelligence_contract() -> dict[str, Any]:
    return {
        "version": PROFILE_INTELLIGENCE_VERSION,
        "purpose": "Venue-owned facts that let creative and accessibility agents reason beyond a basic public profile without inventing paths, capacity, timing, or approval authority.",
        "readinessTiers": {
            "not_supplied": "Experience Studio may draft, but route confidence is limited to derived profile hints.",
            "partial": "Some venue-owned intelligence is available; unresolved components remain review gates.",
            "certified": "Core path, capacity, and timing components are venue-owned and can support real-venue-ready handoff review.",
        },
        "components": {
            "certifiedPaths": {
                "requiredForRealVenueReady": True,
                "minimumRows": 1,
                "requiredFields": ["id", "fromZoneId", "toZoneId", "estimatedWalkMinutes", "stepFree", "certificationStatus", "source"],
                "certifiedValue": {"certificationStatus": "venue_certified"},
            },
            "capacityModel": {
                "requiredForRealVenueReady": True,
                "requiredFields": ["status", "zoneComfort"],
                "certifiedValue": {"status": "venue_certified"},
            },
            "timingModel": {
                "requiredForRealVenueReady": True,
                "requiredFields": ["status", "showtimes", "blackoutWindows"],
                "certifiedValue": {"status": "venue_scheduled"},
            },
            "experienceRules": {
                "requiredForRealVenueReady": False,
                "recommendedFields": ["rainyDayAnchors", "kidFriendlyAnchors", "lowSensoryAnchors", "vipRouteAnchors", "routePatterns", "noGoPairings"],
            },
            "brandBible": {
                "requiredForRealVenueReady": False,
                "recommendedFields": ["tone", "bannedClaims", "approvedPhrases", "supportedLocales"],
            },
            "reviewOwners": {
                "requiredForRealVenueReady": False,
                "recommendedFields": ["experience_design", "accessibility", "safety", "crm", "operations"],
            },
        },
    }


def _is_sample_export(export: dict[str, Any]) -> bool:
    loaded_from = _text(export.get("loaded_from"))
    if not loaded_from:
        return _matches_bundled_sample(export)
    name = Path(loaded_from).name.lower()
    blocked_tokens = ("sample", ".example", "demo", "seed", "test", "fake")
    return any(token in name for token in blocked_tokens) or _matches_bundled_sample(export)


def _sample_compare_payload(value: Any) -> Any:
    ignored = {"loaded_from", "loaded_at_epoch", "imported_by", "imported_source_name", "channel_owners"}
    if isinstance(value, dict):
        return {key: _sample_compare_payload(row) for key, row in sorted(value.items()) if key not in ignored}
    if isinstance(value, list):
        return [_sample_compare_payload(row) for row in value]
    return value


def _matches_bundled_sample(export: dict[str, Any]) -> bool:
    sample_path = Path(__file__).with_name("data") / "customer_venue_export.sample.json"
    try:
        sample = json.loads(sample_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return _sample_compare_payload(export) == _sample_compare_payload(sample)


def _runtime_export_path() -> Path:
    return Path(os.getenv("PARKPULSE_CUSTOMER_VENUE_EXPORT_RUNTIME_PATH", "/tmp/parkpulse/customer_venue_export.json"))


def _synthetic_venue_export_path() -> Path:
    return Path(__file__).with_name("data") / "parkpulse_synthetic_venue_export.approved.json"


def approved_synthetic_venue_export() -> dict[str, Any]:
    return json.loads(_synthetic_venue_export_path().read_text(encoding="utf-8"))


def _venue_identity(export: dict[str, Any]) -> dict[str, Any]:
    identity = _as_dict(export.get("venue_identity"))
    source_catalog = _source_catalog(export)
    return {
        "venueId": _text(identity.get("venue_id")),
        "name": _text(identity.get("name")) or "Unspecified venue",
        "profileType": _text(identity.get("profile_type") or source_catalog.get("profile_type") or "venue_export"),
        "description": _text(identity.get("description")),
        "primaryAudiences": [item for item in _as_list(identity.get("primary_audiences")) if _text(item)],
        "publicZones": [zone for zone in _as_list(identity.get("public_zones")) if isinstance(zone, dict)],
    }


def _known_approved_sources(export: dict[str, Any], item: dict[str, Any]) -> bool:
    sources = _sources(export)
    ids = _source_ids(item)
    if not ids:
        return False
    for source_id in ids:
        source = _as_dict(sources.get(source_id))
        if source.get("source_type") == "seed_catalog":
            return False
        if source.get("review_status") != "venue_approved":
            return False
        if not source.get("last_verified_at"):
            return False
    return True


def _append_unique(rows: list[str], value: str) -> None:
    clean = _text(value)
    if clean and clean.lower() not in {row.lower() for row in rows}:
        rows.append(clean)


def _venue_location_names(export: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for collection in ("attractions", "shows", "food", "family_services"):
        for item in _as_list(export.get(collection)):
            if isinstance(item, dict) and _known_approved_sources(export, item):
                _append_unique(names, _text(item.get("name")))
    for rows in _as_dict(export.get("landmarks")).values():
        for item in _as_list(rows):
            if isinstance(item, dict) and _known_approved_sources(export, item):
                _append_unique(names, _text(item.get("name")))
    for node in _as_list(_as_dict(export.get("venue_map")).get("nodes")):
        if isinstance(node, dict) and _known_approved_sources(export, node):
            _append_unique(names, _text(node.get("name")))
    return names


def _venue_indoor_or_sheltered(export: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for item in _as_list(export.get("attractions")):
        if not isinstance(item, dict) or not _known_approved_sources(export, item):
            continue
        if item.get("indoor") is True or item.get("covered") is True:
            _append_unique(names, _text(item.get("name")))
    for item in _as_list(export.get("food")):
        if not isinstance(item, dict) or not _known_approved_sources(export, item):
            continue
        seating = _text(item.get("seating")).lower()
        if "covered" in seating or "indoor" in seating or item.get("covered") is True:
            _append_unique(names, _text(item.get("name")))
    for item in _as_list(_as_dict(export.get("landmarks")).get("quiet_or_cooling")):
        if isinstance(item, dict) and _known_approved_sources(export, item):
            _append_unique(names, _text(item.get("name")))
    return names


def _venue_quiet_or_cooling(export: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for item in _as_list(_as_dict(export.get("landmarks")).get("quiet_or_cooling")):
        if isinstance(item, dict) and _known_approved_sources(export, item):
            _append_unique(names, _text(item.get("name")))
    for item in _as_list(export.get("family_services")):
        if isinstance(item, dict) and _known_approved_sources(export, item) and "stimulus" in _text(item.get("name")).lower():
            _append_unique(names, _text(item.get("name")))
    return names


def _venue_attraction_names(export: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for item in _as_list(export.get("attractions")):
        if isinstance(item, dict) and _known_approved_sources(export, item):
            _append_unique(names, _text(item.get("name")))
    return names


def _location_details(export: dict[str, Any]) -> dict[str, dict[str, Any]]:
    details: dict[str, dict[str, Any]] = {}

    def add(name: str, payload: dict[str, Any]) -> None:
        clean = _text(name)
        if not clean:
            return
        existing = details.get(clean, {})
        merged = {**existing, **{key: value for key, value in payload.items() if value not in (None, "", [])}}
        merged["name"] = clean
        details[clean] = merged

    for item in _as_list(export.get("attractions")):
        if not isinstance(item, dict) or not _known_approved_sources(export, item):
            continue
        add(
            _text(item.get("name")),
            {
                "kind": "attraction",
                "zoneId": item.get("zone_id"),
                "category": item.get("category"),
                "thrillLevel": item.get("thrill_level"),
                "durationMinutes": item.get("duration_minutes"),
                "heightRequirementInches": item.get("height_requirement_inches"),
                "indoor": item.get("indoor"),
                "covered": item.get("covered"),
                "familyFit": item.get("family_fit"),
                "accessibilityNote": item.get("accessibility_note"),
                "sensoryNote": item.get("sensory_note"),
                "sourceIds": _source_ids(item),
            },
        )
    for item in _as_list(export.get("food")):
        if not isinstance(item, dict) or not _known_approved_sources(export, item):
            continue
        add(
            _text(item.get("name")),
            {
                "kind": "food",
                "zoneId": item.get("zone_id"),
                "cuisine": item.get("cuisine"),
                "dietaryTags": item.get("dietary_tags"),
                "mobileOrder": item.get("mobile_order"),
                "seating": item.get("seating"),
                "covered": item.get("covered"),
                "sourceIds": _source_ids(item),
            },
        )
    for group, rows in _as_dict(export.get("landmarks")).items():
        for item in _as_list(rows):
            if not isinstance(item, dict) or not _known_approved_sources(export, item):
                continue
            add(
                _text(item.get("name")),
                {
                    "kind": group,
                    "zoneId": item.get("zone_id"),
                    "bestFor": item.get("best_for"),
                    "accessible": item.get("accessible"),
                    "familyRoom": item.get("family_room"),
                    "guestInstruction": item.get("guest_instruction"),
                    "services": item.get("services"),
                    "sourceIds": _source_ids(item),
                },
            )
    for item in _as_list(export.get("shows")):
        if not isinstance(item, dict) or not _known_approved_sources(export, item):
            continue
        add(
            _text(item.get("name")),
            {
                "kind": "show",
                "zoneId": item.get("zone_id"),
                "durationMinutes": item.get("typical_duration_minutes"),
                "bestFor": item.get("best_for"),
                "accessibilityNote": item.get("accessibility_note"),
                "guestTip": item.get("guest_tip"),
                "sourceIds": _source_ids(item),
            },
        )
    for item in _as_list(export.get("family_services")):
        if isinstance(item, dict) and _known_approved_sources(export, item):
            add(_text(item.get("name")), {"kind": "family_service", "zoneId": item.get("zone_id"), "sourceIds": _source_ids(item)})
    return details


def _venue_accessibility_notes(export: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    for collection in ("attractions", "shows"):
        for item in _as_list(export.get(collection)):
            if not isinstance(item, dict) or not _known_approved_sources(export, item):
                continue
            note = _text(item.get("accessibility_note"))
            if note:
                _append_unique(notes, f"{_text(item.get('name'))}: {note}")
    for rows in _as_dict(export.get("landmarks")).values():
        for item in _as_list(rows):
            if not isinstance(item, dict) or not _known_approved_sources(export, item):
                continue
            if item.get("accessible") is True:
                _append_unique(notes, f"{_text(item.get('name'))}: accessible public map location")
            if item.get("family_room") is True:
                _append_unique(notes, f"{_text(item.get('name'))}: family room available")
    return notes


def _venue_safety_instructions(export: dict[str, Any]) -> list[str]:
    instructions: list[str] = []
    for item in _as_list(export.get("safety_instructions")):
        if isinstance(item, dict) and _known_approved_sources(export, item):
            label = _text(item.get("location") or item.get("name") or item.get("id"))
            instruction = _text(item.get("instruction") or item.get("guest_instruction"))
            if instruction:
                _append_unique(instructions, f"{label}: {instruction}" if label else instruction)
        elif isinstance(item, str):
            _append_unique(instructions, item)
    for item in _as_list(_as_dict(export.get("landmarks")).get("first_aid")):
        if isinstance(item, dict) and _known_approved_sources(export, item):
            instruction = _text(item.get("guest_instruction"))
            if instruction:
                _append_unique(instructions, f"{_text(item.get('name'))}: {instruction}")
    return instructions


def _approved_map_nodes(export: dict[str, Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for node in _as_list(_as_dict(export.get("venue_map")).get("nodes")):
        if isinstance(node, dict) and _known_approved_sources(export, node):
            nodes.append(node)
    return nodes


def _zone_name_map(export: dict[str, Any]) -> dict[str, str]:
    identity = _venue_identity(export)
    zones: dict[str, str] = {}
    for zone in _as_list(identity.get("publicZones")):
        if not isinstance(zone, dict):
            continue
        zone_id = _text(zone.get("id"))
        if zone_id:
            zones[zone_id] = _text(zone.get("name")) or zone_id
    return zones


def _location_names_by_zone(details: dict[str, dict[str, Any]], zone_id: str, kinds: set[str] | None = None) -> list[str]:
    names: list[str] = []
    for name, item in details.items():
        if _text(item.get("zoneId")) != zone_id:
            continue
        if kinds is not None and _text(item.get("kind")) not in kinds:
            continue
        _append_unique(names, name)
    return names


def _zone_center(nodes: list[dict[str, Any]], zone_id: str) -> dict[str, float] | None:
    rows = [node for node in nodes if _text(node.get("zone_id")) == zone_id and isinstance(node.get("x"), (int, float)) and isinstance(node.get("y"), (int, float))]
    if not rows:
        return None
    return {
        "x": round(sum(float(node["x"]) for node in rows) / len(rows), 1),
        "y": round(sum(float(node["y"]) for node in rows) / len(rows), 1),
    }


def _zone_role(types: set[str], zone_name: str) -> str:
    lowered = zone_name.lower()
    if "entry" in types or "entrance" in lowered:
        return "arrival_and_guest_services"
    if "first_aid" in types or "guest_services" in types or "care" in lowered:
        return "guest_care_and_recovery"
    if "food" in types:
        return "dining_and_dwell"
    if "show" in types or "quiet_or_cooling" in types or "sheltered_area" in types:
        return "shelter_show_or_reset"
    if "attraction" in types:
        return "attraction_demand"
    return "general_public_area"


def _sensory_baseline(types: set[str], location_names: list[str], details: dict[str, dict[str, Any]]) -> str:
    high_terms = ("coaster", "drop", "launch", "thrill")
    low_terms = ("quiet", "cooling", "shade", "lower-stimulus", "care")
    joined = " ".join(location_names).lower()
    if any(term in joined for term in low_terms) or "quiet_or_cooling" in types:
        return "low"
    for name in location_names:
        note = _text(details.get(name, {}).get("sensoryNote")).lower()
        if "low" in note or "quiet" in note:
            return "low"
        if "loud" in note or "high" in note or "strobe" in note:
            return "high"
    if any(term in joined for term in high_terms):
        return "high"
    return "medium" if types & {"food", "show", "retail"} else "variable"


def _zone_intelligence(export: dict[str, Any], details: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    nodes = _approved_map_nodes(export)
    zone_names = _zone_name_map(export)
    quiet_names = set(_venue_quiet_or_cooling(export))
    indoor_names = set(_venue_indoor_or_sheltered(export))
    zone_index: dict[str, dict[str, Any]] = {}
    for zone_id, zone_name in zone_names.items():
        zone_nodes = [node for node in nodes if _text(node.get("zone_id")) == zone_id]
        node_types = {_text(node.get("type")) for node in zone_nodes if _text(node.get("type"))}
        location_names = _location_names_by_zone(details, zone_id)
        indoor_or_sheltered = bool(indoor_names & set(location_names)) or "sheltered_area" in node_types
        quiet_or_cooling = bool(quiet_names & set(location_names)) or "quiet_or_cooling" in node_types
        restrooms = _location_names_by_zone(details, zone_id, {"restrooms"})
        first_aid = _location_names_by_zone(details, zone_id, {"first_aid"})
        guest_services = _location_names_by_zone(details, zone_id, {"guest_services", "family_service"})
        dining = _location_names_by_zone(details, zone_id, {"food"})
        attractions = _location_names_by_zone(details, zone_id, {"attraction", "show"})
        zone_index[zone_id] = {
            "id": zone_id,
            "name": zone_name,
            "role": _zone_role(node_types, zone_name),
            "center": _zone_center(nodes, zone_id),
            "publicLocationCount": len(location_names),
            "nodeTypes": sorted(node_types),
            "locations": location_names,
            "attractions": attractions,
            "dining": dining,
            "restrooms": restrooms,
            "firstAid": first_aid,
            "guestServices": guest_services,
            "indoorOrSheltered": indoor_or_sheltered,
            "quietOrCooling": quiet_or_cooling,
            "sensoryBaseline": _sensory_baseline(node_types, location_names, details),
            "agentReasoningHints": [
                hint
                for hint in [
                    "good reset or weather fallback" if indoor_or_sheltered or quiet_or_cooling else "",
                    "keep as care handoff anchor" if first_aid or guest_services else "",
                    "watch meal-time dwell and mobile-order pressure" if dining else "",
                    "watch queue spillback and thrill-seeker demand" if attractions and not quiet_or_cooling else "",
                    "use as restroom waypoint" if restrooms else "",
                ]
                if hint
            ],
            "source": "venue_profile.public_zones + venue_map.nodes + approved public location records",
        }
    return zone_index


def _distance_between(a: dict[str, float] | None, b: dict[str, float] | None) -> float | None:
    if not a or not b:
        return None
    return ((float(a["x"]) - float(b["x"])) ** 2 + (float(a["y"]) - float(b["y"])) ** 2) ** 0.5


def _spatial_model(export: dict[str, Any], zones: dict[str, dict[str, Any]]) -> dict[str, Any]:
    map_payload = _as_dict(export.get("venue_map"))
    scale = _as_dict(map_payload.get("scale"))
    explicit_paths = [path for path in _as_list(map_payload.get("paths")) if isinstance(path, dict) and _known_approved_sources(export, path)]
    paths: list[dict[str, Any]] = []
    if explicit_paths:
        for path in explicit_paths:
            from_zone = _text(path.get("from_zone_id") or path.get("from"))
            to_zone = _text(path.get("to_zone_id") or path.get("to"))
            if from_zone and to_zone:
                paths.append(
                    {
                        "id": _text(path.get("id")) or f"{from_zone}_to_{to_zone}",
                        "fromZoneId": from_zone,
                        "toZoneId": to_zone,
                        "estimatedWalkMinutes": path.get("estimated_walk_minutes"),
                        "covered": path.get("covered"),
                        "stepFree": path.get("step_free"),
                        "notes": path.get("notes"),
                        "source": "venue_map.paths",
                    }
                )
    else:
        zone_rows = [zone for zone in zones.values() if zone.get("center")]
        seen: set[tuple[str, str]] = set()
        for zone in zone_rows:
            distances = []
            for other in zone_rows:
                if zone["id"] == other["id"]:
                    continue
                distance = _distance_between(zone.get("center"), other.get("center"))
                if distance is not None:
                    distances.append((distance, other))
            for distance, other in sorted(distances, key=lambda row: row[0])[:2]:
                key = tuple(sorted([zone["id"], other["id"]]))
                if key in seen:
                    continue
                seen.add(key)
                paths.append(
                    {
                        "id": f"{key[0]}_to_{key[1]}",
                        "fromZoneId": zone["id"],
                        "toZoneId": other["id"],
                        "estimatedWalkMinutes": max(2, round(distance / 70)),
                        "distanceMapUnits": round(distance, 1),
                        "covered": bool(zone.get("indoorOrSheltered") and other.get("indoorOrSheltered")),
                        "stepFree": True,
                        "crowdSensitivity": "high" if {"attraction_demand", "dining_and_dwell"} & {zone.get("role"), other.get("role")} else "medium",
                        "source": "derived_from_venue_map_node_geometry",
                    }
                )
    return {
        "source": "venue_profile.venue_map",
        "scale": scale,
        "zones": zones,
        "paths": paths,
        "routingAssumptions": [
            "Use explicit venue_map.paths when supplied; otherwise derive coarse adjacency from approved map node geometry.",
            "Derived paths are planning hints, not certified walking directions.",
            "Accessibility, emergency, and crowd-control route changes require staff confirmation before guest-facing publication.",
        ],
    }


def _guest_segments(export: dict[str, Any], zones: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    supplied = [row for row in _as_list(export.get("guest_segments")) if isinstance(row, dict)]
    if supplied:
        return supplied
    quiet_zones = [zone["id"] for zone in zones.values() if zone.get("quietOrCooling")]
    sheltered_zones = [zone["id"] for zone in zones.values() if zone.get("indoorOrSheltered")]
    thrill_zones = [zone["id"] for zone in zones.values() if zone.get("role") == "attraction_demand"]
    care_zones = [zone["id"] for zone in zones.values() if zone.get("firstAid") or zone.get("guestServices")]
    dining_zones = [zone["id"] for zone in zones.values() if zone.get("dining")]
    return [
        {
            "id": "families_with_strollers",
            "label": "Families with strollers",
            "decisionDrivers": ["shorter walks", "restrooms", "shade or indoor breaks", "simple wayfinding"],
            "preferredZones": list(dict.fromkeys(care_zones + sheltered_zones))[:5],
            "handoffTriggers": ["separated party", "lost item", "child-care need", "weather exposure"],
        },
        {
            "id": "thrill_seekers",
            "label": "Thrill seekers",
            "decisionDrivers": ["wait time", "ride intensity", "nearby secondary attractions", "weather closures"],
            "preferredZones": thrill_zones[:5],
            "handoffTriggers": ["ride safety rule question", "closure dispute", "height or transfer uncertainty"],
        },
        {
            "id": "low_sensory_guests",
            "label": "Lower-sensory guests",
            "decisionDrivers": ["quiet spaces", "indoor reset points", "avoid loud shows", "avoid dense queues"],
            "preferredZones": list(dict.fromkeys(quiet_zones + sheltered_zones))[:5],
            "handoffTriggers": ["sensory overload", "accessibility accommodation question", "route blockage"],
        },
        {
            "id": "rainy_day_parties",
            "label": "Rainy-day parties",
            "decisionDrivers": ["covered paths", "indoor attractions", "food dwell", "reduced walking"],
            "preferredZones": sheltered_zones[:6],
            "handoffTriggers": ["storm shelter direction", "slip risk", "temporary outdoor closure"],
        },
        {
            "id": "allergy_or_dietary_guests",
            "label": "Allergy or dietary guests",
            "decisionDrivers": ["venue-approved menu tags", "staff confirmation", "mobile order availability", "low-crowd seating"],
            "preferredZones": dining_zones[:5],
            "handoffTriggers": ["ingredient confirmation", "cross-contact concern", "medical uncertainty"],
        },
    ]


def _operating_priors(export: dict[str, Any], zones: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "source": "derived_from_approved_venue_profile",
        "zoneDemandPriors": [
            {
                "zoneId": zone["id"],
                "role": zone.get("role"),
                "typicalPressureDrivers": [
                    driver
                    for driver in [
                        "arrival and exit waves" if zone.get("role") == "arrival_and_guest_services" else "",
                        "meal periods and mobile pickup" if zone.get("role") == "dining_and_dwell" else "",
                        "show start/end pulses" if "show" in zone.get("nodeTypes", []) else "",
                        "ride wait-time imbalance" if zone.get("role") == "attraction_demand" else "",
                        "heat, rain, and accessibility reset demand" if zone.get("quietOrCooling") or zone.get("indoorOrSheltered") else "",
                    ]
                    if driver
                ],
                "watchSignals": [
                    signal
                    for signal in [
                        "crowd_density" if zone.get("role") in {"arrival_and_guest_services", "dining_and_dwell", "attraction_demand"} else "",
                        "queue_spillback" if zone.get("attractions") else "",
                        "food_pickup_eta" if zone.get("dining") else "",
                        "care_or_accessibility_request" if zone.get("firstAid") or zone.get("guestServices") else "",
                        "weather_exposure" if not zone.get("indoorOrSheltered") else "",
                    ]
                    if signal
                ],
            }
            for zone in zones.values()
        ],
        "crossModuleRules": [
            "Experience copy can recommend public places but cannot claim operational availability beyond the active source.",
            "Accessibility and allergy plans must include staff confirmation steps when guest safety depends on live human judgment.",
            "Command Center actions may use profile priors for triage, but physical reroutes and safety actions still require live state and policy gates.",
            "Learning should attach outcomes to zone, segment, weather, crowd, and source version rather than private guest identity.",
        ],
    }


def _learning_context(export: dict[str, Any], zones: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "source": "venue_profile_learning_contract",
        "scenarioTaxonomy": [
            "experience_design",
            "accessibility_journey",
            "rainy_day_reroute",
            "low_sensory_route",
            "dining_allergy_handoff",
            "vip_tour_script",
            "signage_language",
            "guest_recovery_copy",
            "command_center_triage",
        ],
        "observationKeys": [
            "venueProfileVersion",
            "sourceIntegrity.profileType",
            "zoneId",
            "guestSegmentId",
            "weatherCondition",
            "crowdDensityBand",
            "waitTimeBand",
            "foodPickupEtaBand",
            "staffHandoffRecommended",
            "humanReviewOutcome",
            "guestFeedbackLabel",
        ],
        "feedbackLabels": [
            "accepted_as_drafted",
            "edited_for_brand_voice",
            "edited_for_safety",
            "rerouted_by_staff",
            "blocked_by_missing_profile_fact",
            "allergy_staff_confirmed",
            "accessibility_staff_confirmed",
            "guest_completed_route",
            "guest_abandoned_route",
            "guest_reported_confusion",
        ],
        "privacyBoundary": [
            "Do not learn or store medical diagnosis, disability identity, protected class, or private guest identifiers.",
            "Learn from aggregate route outcomes, public zone context, source version, and reviewer labels.",
            "Keep venue facts versioned so agent regressions can be replayed against the profile that produced them.",
        ],
        "coverageTargets": {
            "zones": len(zones),
            "guestSegments": 5,
            "minimumReviewerLabelsPerScenario": 20,
            "minimumRouteOutcomeSamplesPerSegment": 30,
        },
    }


def _experience_operations(export: dict[str, Any]) -> dict[str, Any]:
    operations = _as_dict(export.get("experience_operations") or export.get("experienceOperations"))
    if not operations:
        return {}
    current_status = _as_dict(operations.get("current_status_snapshot"))
    path_status = _as_dict(operations.get("path_status"))
    signage = _as_dict(operations.get("signage_inventory"))
    channel_templates = _as_dict(operations.get("channel_templates"))
    calendar = _as_dict(operations.get("operating_calendar"))
    weather_policy = _as_dict(operations.get("weather_policy"))
    return {
        "source": _text(operations.get("source")) or "venue_profile.experience_operations",
        "status": _text(operations.get("status")) or "supplied",
        "snapshotLocalDate": _text(operations.get("snapshot_local_date")),
        "snapshotTimeLocal": _text(operations.get("snapshot_time_local")),
        "currentStatus": current_status,
        "pathStatus": path_status,
        "signageInventory": signage,
        "channelTemplates": channel_templates,
        "operatingCalendar": calendar,
        "weatherPolicy": weather_policy,
        "coverage": {
            "currentOptions": len(_as_list(current_status.get("attractions"))),
            "facilityStatuses": len(_as_list(current_status.get("facilityStatus"))),
            "pathStatusSegments": len(_as_list(path_status.get("routeSegments"))),
            "blockedPathRows": len(_as_list(path_status.get("blockedPathStatus"))),
            "signagePlacements": len(_as_list(signage.get("placements"))),
            "channelTemplates": len(_as_dict(channel_templates.get("templates"))),
            "approvalWorkflowRows": len(_as_list(channel_templates.get("approvalWorkflow"))),
            "eventWindows": len(_as_list(calendar.get("eventWindows"))),
            "weatherPolicies": len([key for key in ("rain", "heat") if _as_dict(weather_policy.get(key))]),
        },
    }


def venue_operating_context_coverage(real_inputs: dict[str, Any]) -> dict[str, Any]:
    intelligence = _as_dict(real_inputs.get("profileIntelligence"))
    nested_operating_context = _as_dict(intelligence.get("operatingContext"))
    operating_context = _as_dict(real_inputs.get("operatingContext")) or nested_operating_context
    current_status = _as_dict(real_inputs.get("currentStatus")) or _as_dict(operating_context.get("currentStatus"))
    path_status = _as_dict(real_inputs.get("pathStatus")) or _as_dict(operating_context.get("pathStatus"))
    signage = _as_dict(real_inputs.get("signageInventory")) or _as_dict(operating_context.get("signageInventory"))
    templates = _as_dict(real_inputs.get("channelTemplates")) or _as_dict(operating_context.get("channelTemplates"))
    calendar = _as_dict(real_inputs.get("operatingCalendar")) or _as_dict(operating_context.get("operatingCalendar"))
    weather_policy = _as_dict(real_inputs.get("weatherPolicy")) or _as_dict(operating_context.get("weatherPolicy"))
    return {
        "currentOptions": len(_as_list(current_status.get("attractions"))),
        "facilityStatuses": len(_as_list(current_status.get("facilityStatus"))),
        "pathStatusSegments": len(_as_list(path_status.get("routeSegments"))),
        "blockedPathRows": len(_as_list(path_status.get("blockedPathStatus"))),
        "signagePlacements": len(_as_list(signage.get("placements"))),
        "channelTemplates": len(_as_dict(templates.get("templates"))),
        "approvalWorkflowRows": len(_as_list(templates.get("approvalWorkflow"))),
        "eventWindows": len(_as_list(calendar.get("eventWindows"))),
        "weatherPolicies": len([key for key in ("rain", "heat") if _as_dict(weather_policy.get(key))]),
    }


def _synthetic_profile_gap_rows(real_inputs: dict[str, Any]) -> tuple[list[str], list[str], dict[str, Any]]:
    coverage = venue_operating_context_coverage(real_inputs)
    missing = ["real venue source feed instead of approved synthetic profile"]
    filled = []
    if coverage["currentOptions"]:
        filled.append("synthetic current-options and attraction status snapshot")
    else:
        missing.append("live attraction closure/current-options feed")
    if coverage["pathStatusSegments"] and coverage["blockedPathRows"]:
        filled.append("synthetic indoor, sheltered, step-free, and blocked-path status")
    else:
        missing.append("current indoor, sheltered, and blocked-path status")
    if coverage["signagePlacements"]:
        filled.append("synthetic physical signage placement inventory")
    else:
        missing.append("approved physical signage placement inventory")
    if coverage["channelTemplates"] and coverage["approvalWorkflowRows"]:
        filled.append("synthetic channel-owner CRM/app/signage/staff templates")
    else:
        missing.append("channel-owner approved CRM/app/staff language templates")
    if coverage["eventWindows"] and coverage["weatherPolicies"]:
        filled.append("synthetic operating calendar, weather policy, and blackout constraints")
    else:
        missing.append("operating calendar, weather policy, and event blackout constraints")
    if coverage["facilityStatuses"]:
        filled.append("synthetic food, restroom, guest services, and family-room status")
    else:
        missing.append("food, restroom, guest services, and family-room status")
    return missing, filled, coverage


def venue_profile_gap_contract(
    real_inputs: dict[str, Any],
    profile_type: str,
    readiness: dict[str, Any] | None = None,
    intelligence_coverage: dict[str, Any] | None = None,
    quality_gaps: list[str] | None = None,
    include_generation_requirements: bool = True,
) -> dict[str, Any]:
    readiness = _as_dict(readiness)
    intelligence_coverage = _as_dict(intelligence_coverage)
    quality_gaps = [_text(item) for item in (quality_gaps or []) if _text(item)]
    clean_profile_type = _text(profile_type) or "unknown"
    production_missing = [_text(item) for item in _as_list(readiness.get("missingForRealVenueReady")) if _text(item)]
    synthetic_filled: list[str] = []
    synthetic_coverage: dict[str, Any] = {}
    if clean_profile_type == "synthetic_approved":
        synthetic_missing, synthetic_filled, synthetic_coverage = _synthetic_profile_gap_rows(real_inputs)
        production_missing.extend(synthetic_missing)
    if include_generation_requirements:
        if not _as_dict(real_inputs.get("channelOwners")):
            production_missing.append("named channel owners for guest_app, signage, email, and staff_cue")
        if not intelligence_coverage.get("certifiedPaths"):
            production_missing.append("certified path records for selected route segments")
    missing_for_production = list(dict.fromkeys([item for item in production_missing + quality_gaps if item]))
    production_real_venue_ready = bool(readiness.get("realVenueReady") and clean_profile_type != "synthetic_approved" and not missing_for_production)
    synthetic_complete = clean_profile_type == "synthetic_approved" and missing_for_production == ["real venue source feed instead of approved synthetic profile"]
    return {
        "status": "real_venue_ready" if production_real_venue_ready else "synthetic_complete_review_required" if synthetic_complete else "creative_ready_review_required",
        "profileType": clean_profile_type,
        "productionRealVenueReady": production_real_venue_ready,
        "missingForProduction": missing_for_production,
        "filledForSyntheticDemo": synthetic_filled,
        "syntheticOperatingCoverage": synthetic_coverage,
        "nextProfileImports": [
            "replace approved synthetic operating snapshot with venue-owned live status feed",
            "replace synthetic path status with real accessibility/path certification export",
            "replace synthetic signage placements with real signage inventory and placement approvals",
            "replace synthetic channel templates with channel-owner CMS/CRM/app template exports",
        ],
    }


def _agent_context(export: dict[str, Any], zones: dict[str, dict[str, Any]]) -> dict[str, Any]:
    operations = _experience_operations(export)
    return {
        "source": "derived_from_approved_venue_profile",
        "groundingFields": [
            "venueIdentity",
            "publicZones",
            "locationDetails",
            "spatialModel",
            "guestSegments",
            "operatingPriors",
            "safetyInstructions",
            "channelOwners",
            "copyVariants",
            "currentStatus",
            "pathStatus",
            "signageInventory",
            "channelTemplates",
            "operatingCalendar",
            "weatherPolicy",
        ],
        "capabilitiesBacked": [
            "draft themed attraction and event copy from venue-approved locations",
            "build low-sensory, rainy-day, family-care, and VIP guest journeys",
            "rank route options using zone role, shelter, accessibility, dining, and care anchors",
            "generate signage and pre-arrival language with source-integrity warnings",
            "attach demo current-options, signage placement, operating calendar, and channel-template constraints",
            "label agent outcomes for later prompt and policy evaluation",
        ],
        "humanReviewTriggers": [
            "allergy ingredient or cross-contact claims",
            "medical advice or urgent care decisions",
            "ride transfer, height, or safety-rule interpretation",
            "route changes affecting emergency, accessibility, or service lanes",
            "claims about live staffing, equipment, refunds, or guaranteed availability",
        ],
        "moduleBindings": {
            "experience_studio": ["venueIdentity", "locationDetails", "guestSegments", "copyVariants", "channelOwners", "currentStatus", "pathStatus", "signageInventory", "channelTemplates", "weatherPolicy"],
            "accessibility_journey": ["spatialModel", "locationDetails", "guestSegments", "safetyInstructions"],
            "command_center_review": ["spatialModel", "operatingPriors", "safetyInstructions"],
            "guest_recommendations": ["locationDetails", "guestSegments", "spatialModel"],
            "learning_evaluation": ["learningContext", "sourceIntegrity", "operatingPriors"],
        },
        "operationsCoverage": {
            "currentOptions": len(_as_list(_as_dict(operations.get("currentStatus")).get("attractions"))),
            "pathStatusSegments": len(_as_list(_as_dict(operations.get("pathStatus")).get("routeSegments"))),
            "signagePlacements": len(_as_list(_as_dict(operations.get("signageInventory")).get("placements"))),
            "channelTemplates": len(_as_dict(_as_dict(operations.get("channelTemplates")).get("templates"))),
            "eventWindows": len(_as_list(_as_dict(operations.get("operatingCalendar")).get("eventWindows"))),
        },
        "knownGaps": [
            "live capacity by room or queue is simulated in the approved profile and must be replaced by real venue state before production publish",
            "staff rosters and backstage procedures are intentionally excluded",
            "certified ADA claims remain blocked even when step-free route facts are supplied",
        ],
    }


def _certified_paths(spatial_model: dict[str, Any]) -> list[dict[str, Any]]:
    paths: list[dict[str, Any]] = []
    for path in _as_list(spatial_model.get("paths")):
        if not isinstance(path, dict):
            continue
        source = _text(path.get("source"))
        certified = source == "venue_map.paths"
        paths.append(
            {
                "id": path.get("id"),
                "fromZoneId": path.get("fromZoneId"),
                "toZoneId": path.get("toZoneId"),
                "estimatedWalkMinutes": path.get("estimatedWalkMinutes"),
                "stepFree": path.get("stepFree"),
                "covered": path.get("covered"),
                "crowdSensitivity": path.get("crowdSensitivity"),
                "certificationStatus": "venue_certified" if certified else "derived_needs_venue_certification",
                "allowedUses": ["planning_hint", "internal_ranking"] if not certified else ["guest_route_copy", "internal_ranking", "accessibility_planning"],
                "blockedClaims": [] if certified else ["certified_accessible_route", "exact_walking_direction", "ada_compliant_path"],
                "source": source or "unknown",
            }
        )
    return paths


def _capacity_model(zones: dict[str, dict[str, Any]]) -> dict[str, Any]:
    zone_rows: list[dict[str, Any]] = []
    for zone in zones.values():
        role = _text(zone.get("role"))
        location_count = int(zone.get("publicLocationCount") or 0)
        base = 120 + location_count * 45
        if role == "arrival_and_guest_services":
            base += 220
        elif role == "dining_and_dwell":
            base += 160
        elif role == "attraction_demand":
            base += 240
        elif role == "shelter_show_or_reset":
            base += 120
        if zone.get("quietOrCooling"):
            base = min(base, 280)
        zone_rows.append(
            {
                "zoneId": zone.get("id"),
                "comfortCapacityEstimate": base,
                "dwellMinutesTypical": 35 if role == "dining_and_dwell" else 25 if zone.get("quietOrCooling") else 18,
                "spillbackRisk": "high" if role in {"attraction_demand", "dining_and_dwell"} else "medium" if role == "arrival_and_guest_services" else "low",
                "confidence": "heuristic",
                "source": "derived_from_public_zone_role_and_location_count",
                "venueOwnedReplacementField": "profile_intelligence.capacity_model.zoneComfort",
            }
        )
    return {
        "status": "derived_needs_venue_capacity_feed",
        "zoneComfort": zone_rows,
        "blockedClaims": ["certified_capacity", "fire_code_limit", "staffing_level"],
        "recommendedLiveFeeds": ["guestFlow.zones.densityPct", "queue_spillback", "foodInventory.locations.pickupEtaMinutes"],
    }


def _experience_rules(export: dict[str, Any], zones: dict[str, dict[str, Any]], details: dict[str, dict[str, Any]]) -> dict[str, Any]:
    event_ready_zones = [
        zone["id"]
        for zone in zones.values()
        if zone.get("role") in {"shelter_show_or_reset", "dining_and_dwell", "arrival_and_guest_services"} or zone.get("quietOrCooling")
    ]
    halloween_locations = [
        name
        for name, item in details.items()
        if _text(item.get("kind")) in {"attraction", "show", "photo_spots", "quiet_or_cooling"} and not item.get("heightRequirementInches")
    ]
    kid_friendly = [
        name
        for name, item in details.items()
        if _text(item.get("kind")) in {"show", "family_service", "quiet_or_cooling", "restrooms", "guest_services"} or "family" in _text(item.get("familyFit")).lower()
    ]
    sheltered_zone_ids = [zone["id"] for zone in zones.values() if zone.get("indoorOrSheltered")]
    sheltered_stops = [name for name, item in details.items() if item.get("zoneId") in sheltered_zone_ids or item.get("zone_id") in sheltered_zone_ids][:8]
    food_stops = [name for name, item in details.items() if _text(item.get("kind")) == "food"][:6]
    photo_stops = [name for name, item in details.items() if _text(item.get("kind")) in {"photo_spots", "attraction", "show"}][:6]
    quiet_stops = [name for name, item in details.items() if _text(item.get("kind")) in {"quiet_or_cooling", "family_service", "guest_services", "show"}][:6]
    all_names = list(details.keys())

    def stops(*groups: list[str], fallback: list[str] | None = None) -> list[str]:
        names: list[str] = []
        for group in groups:
            names.extend(group)
        names.extend(fallback or all_names)
        return list(dict.fromkeys([name for name in names if name]))[:5]

    route_patterns = {
        "festival_plan": {
            "recommendedArc": ["festival month invite", "landmark photo ritual", "lantern discovery", "food or craft pause", "show or finale close"],
            "preferredStops": stops(photo_stops, food_stops, quiet_stops),
            "mustInclude": ["cultural review gate", "optional participation mechanic", "current schedule caveat", "no guaranteed reward"],
            "avoidClaims": ["cultural claims without review", "guaranteed prize", "always-on show or menu availability"],
        },
        "seasonal_overlay": {
            "recommendedArc": ["seasonal arrival signal", "overlay discovery", "photo or decor pause", "flexible activity choice", "seasonal close"],
            "preferredStops": stops(photo_stops, quiet_stops, food_stops),
            "mustInclude": ["temporary-install review", "decor placement approval", "weather alternate", "current dates caveat"],
            "avoidClaims": ["permanent decor", "all-day activation guarantee", "unapproved character or IP references"],
        },
        "food_festival": {
            "recommendedArc": ["taste invitation", "first sample choice", "seated reset", "craft or retail pairing", "flavor finale"],
            "preferredStops": stops(food_stops, quiet_stops),
            "mustInclude": ["menu-owner review", "allergy handoff language", "seating caveat", "non-purchase participation option"],
            "avoidClaims": ["allergen-free assurance", "guaranteed sample availability", "dietary or medical advice"],
        },
        "photo_moment_route": {
            "recommendedArc": ["photo invite", "landmark shot", "scenic transition", "group photo pause", "shareable close"],
            "preferredStops": stops(photo_stops, quiet_stops),
            "mustInclude": ["alternate no-photo participation", "accessible viewing check", "crowd-safe pause point", "privacy-respectful language"],
            "avoidClaims": ["professional photo guarantee", "exclusive photo access", "blocking path for photos"],
        },
        "accessibility_family_day": {
            "recommendedArc": ["plain arrival", "step-free choice", "rest point", "flexible activity", "supported close"],
            "preferredStops": stops(quiet_stops, food_stops),
            "mustInclude": ["step-free verification", "restroom or family-room cue", "permission to pause", "staff handoff caveat"],
            "avoidClaims": ["ADA compliance claim", "equipment availability guarantee", "medical or diagnosis-specific advice"],
        },
        "teen_night_out": {
            "recommendedArc": ["meet-up signal", "photo beat", "food or hangout choice", "thrill or show option", "regroup close"],
            "preferredStops": stops(photo_stops, food_stops, quiet_stops),
            "mustInclude": ["caregiver-friendly regroup point", "well-lit close", "current-options caveat", "not childish tone"],
            "avoidClaims": ["unsupervised safety guarantee", "exclusive teen access", "pressure to ride or purchase"],
        },
        "first_time_visitor": {
            "recommendedArc": ["arrival confidence", "orientation landmark", "first signature choice", "comfort reset", "next-step close"],
            "preferredStops": stops(photo_stops, food_stops, quiet_stops),
            "mustInclude": ["map/app orientation cue", "skip-or-switch language", "restroom or support cue", "next best option"],
            "avoidClaims": ["must-do route", "complete park guarantee", "live wait-time promise"],
        },
        "date_night": {
            "recommendedArc": ["warm evening welcome", "scenic pause", "food or show beat", "quiet choice", "photo close"],
            "preferredStops": stops(photo_stops, food_stops, quiet_stops),
            "mustInclude": ["relaxed pacing", "quiet bypass option", "tasteful photo cue", "current food/show caveat"],
            "avoidClaims": ["romantic guarantee", "priority seating", "private or exclusive access"],
        },
        "education_field_trip": {
            "recommendedArc": ["group arrival", "observation prompt", "learning stop", "lunch or reset", "reflection close"],
            "preferredStops": stops(kid_friendly, food_stops, quiet_stops),
            "mustInclude": ["chaperone cue", "headcount pause", "learning prompt", "school-owner review"],
            "avoidClaims": ["curriculum certification", "student supervision guarantee", "unsafe crowd-control instruction"],
        },
        "post_incident_recovery_copy": {
            "recommendedArc": ["acknowledge concern", "orient to support", "offer current alternate", "staff phrase", "follow-up close"],
            "preferredStops": stops(quiet_stops, food_stops),
            "mustInclude": ["empathetic acknowledgement", "current source handoff", "no fault speculation", "owner-approved escalation path"],
            "avoidClaims": ["incident cause speculation", "compensation promise", "resolved without live confirmation"],
        },
        "retail_merch_quest": {
            "recommendedArc": ["quest invite", "display clue", "shop or story beat", "non-purchase option", "collectible close"],
            "preferredStops": stops(photo_stops, food_stops, quiet_stops),
            "mustInclude": ["non-purchase path", "fulfillment review", "display placement approval", "caregiver opt-out"],
            "avoidClaims": ["purchase requirement", "guaranteed item availability", "limited-edition claim without retail approval"],
        },
        "scavenger_hunt": {
            "recommendedArc": ["map pickup", "visual clue", "landmark solve", "validation pause", "final reveal"],
            "preferredStops": stops(halloween_locations, kid_friendly, food_stops),
            "mustInclude": ["visible clue object", "skip option", "non-purchase validation", "path-safe pause"],
            "avoidClaims": ["guaranteed prize", "blocking paths", "requiring staff to validate every clue"],
        },
        "attraction_copy": {
            "recommendedArc": ["expectation set", "signature detail", "access and comfort cue", "nearby pairing", "current-options handoff"],
            "preferredStops": stops(photo_stops, quiet_stops, food_stops),
            "mustInclude": ["height or eligibility review", "accessibility review", "nearby lower-pressure alternate", "current operating caveat"],
            "avoidClaims": ["no wait", "always open", "safe for every guest", "medical suitability"],
        },
        "safety_signage": {
            "recommendedArc": ["plain instruction", "reason cue", "location context", "staff-support phrase", "app or follow-up reminder"],
            "preferredStops": stops(quiet_stops, food_stops),
            "mustInclude": ["one action per sign", "plain language", "readability check", "safety-owner approval"],
            "avoidClaims": ["new rule without source", "ambiguous direction", "operational instruction beyond approved safety copy"],
        },
        "rainy_day": {
            "recommendedArc": ["dry start", "choice pause", "seated reset", "food or restroom option", "covered close"],
            "preferredStops": stops(sheltered_stops, food_stops, quiet_stops),
            "mustInclude": ["one seated reset", "one app-confirmed current-options cue", "one explicit opt-out"],
            "avoidClaims": ["fully covered route unless every path segment is certified covered", "weather guarantee", "staff availability guarantee"],
        },
        "kid_quest": {
            "recommendedArc": ["mission start", "visual clue", "low-pressure discovery", "caregiver reset", "celebration"],
            "preferredStops": stops(kid_friendly, photo_stops, food_stops),
            "mustInclude": ["caregiver bypass language", "non-purchase reward option", "visible clue object"],
            "avoidClaims": ["guaranteed prize", "age suitability beyond approved attraction rules"],
        },
        "low_sensory": {
            "recommendedArc": ["orient", "quiet move", "reset", "optional delight", "easy return"],
            "preferredStops": stops(quiet_stops),
            "mustInclude": ["audio/light expectations", "named bypass", "permission to stop"],
            "avoidClaims": ["quiet guarantee", "medical or diagnosis-specific advice"],
        },
        "vip_tour": {
            "recommendedArc": ["host welcome", "insider reveal", "signature moment", "relaxed pause", "keepsake close"],
            "preferredStops": stops(photo_stops, quiet_stops, food_stops),
            "mustInclude": ["availability caveat", "weather alternate", "host transition script"],
            "avoidClaims": ["backstage access", "priority access guarantee", "staffing promise"],
        },
        "halloween_route": {
            "recommendedArc": ["soft spooky invite", "glow clue", "creature-free mystery", "treat or photo pause", "lantern finale"],
            "preferredStops": stops(halloween_locations, food_stops),
            "mustInclude": ["family-safe scare level", "well-lit exit option", "no jump-scare wording"],
            "avoidClaims": ["fear pressure", "dark route guarantee", "age-inappropriate threat language"],
        },
    }
    return {
        "eventReadyZones": event_ready_zones,
        "halloweenCandidateLocations": halloween_locations[:12],
        "kidFriendlyAnchors": kid_friendly[:12],
        "rainyDayAnchors": [zone["id"] for zone in zones.values() if zone.get("indoorOrSheltered")][:8],
        "vipRouteAnchors": [name for name, item in details.items() if _text(item.get("kind")) in {"attraction", "show", "photo_spots", "guest_services"}][:10],
        "routePatterns": route_patterns,
        "noGoPairings": [
            {"rule": "Do not pair allergy dining copy with a guarantee of allergen-free food.", "severity": "critical"},
            {"rule": "Do not route low-sensory guests through high-sensory thrill zones without an alternate reset point.", "severity": "high"},
            {"rule": "Do not publish safety, transfer, or access-lane claims without staff review.", "severity": "critical"},
        ],
        "source": "derived_from_location_details_and_zone_intelligence",
    }


def _segment_needs(segments: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        str(segment.get("id")): {
            "label": segment.get("label"),
            "preferredPace": "slow" if "families" in _text(segment.get("id")) or "sensory" in _text(segment.get("id")) else "moderate",
            "needs": segment.get("decisionDrivers") or [],
            "avoid": [
                item
                for item in [
                    "dense queues" if "sensory" in _text(segment.get("id")) else "",
                    "long exposed walks" if "rainy" in _text(segment.get("id")) or "families" in _text(segment.get("id")) else "",
                    "ingredient assumptions" if "allergy" in _text(segment.get("id")) else "",
                    "closed or restricted rides" if "thrill" in _text(segment.get("id")) else "",
                ]
                if item
            ],
            "requiredHandoff": segment.get("handoffTriggers") or [],
        }
        for segment in segments
        if segment.get("id")
    }


def _timing_model(export: dict[str, Any]) -> dict[str, Any]:
    shows = [
        {
            "id": item.get("id"),
            "name": item.get("name"),
            "zoneId": item.get("zone_id"),
            "typicalDurationMinutes": item.get("typical_duration_minutes"),
            "crowdPulse": "show_start_end",
            "sourceIds": _source_ids(item),
        }
        for item in _as_list(export.get("shows"))
        if isinstance(item, dict) and _known_approved_sources(export, item)
    ]
    return {
        "status": "schedule_feed_required_for_exact_times",
        "showDurationModel": shows,
        "knownPulses": [
            {"id": "arrival_wave", "when": "opening_hour", "affectedZoneRoles": ["arrival_and_guest_services"]},
            {"id": "meal_wave", "when": "lunch_and_dinner_periods", "affectedZoneRoles": ["dining_and_dwell"]},
            {"id": "show_pulse", "when": "before_and_after_showtimes", "affectedZoneRoles": ["shelter_show_or_reset"]},
        ],
        "missingForExactScheduling": ["showtimes", "parade_routes", "event_windows", "setup_teardown_windows", "blackout_periods"],
    }


def _profile_intelligence_supplied(export: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(export.get("profile_intelligence") or export.get("profileIntelligence"))


def _normalize_profile_intelligence(supplied: dict[str, Any]) -> dict[str, Any]:
    mapping = {
        "certified_paths": "certifiedPaths",
        "capacity_model": "capacityModel",
        "timing_model": "timingModel",
        "experience_rules": "experienceRules",
        "module_policy": "modulePolicy",
        "field_source_ledger": "fieldSourceLedger",
        "learning_schema": "learningSchema",
        "brand_bible": "brandBible",
        "live_feed_bindings": "liveFeedBindings",
        "review_owners": "reviewOwners",
    }
    normalized: dict[str, Any] = {}
    for key, value in supplied.items():
        normalized[mapping.get(str(key), str(key))] = value
    return normalized


def _profile_intelligence_readiness(intelligence: dict[str, Any], supplied: dict[str, Any]) -> dict[str, Any]:
    certified_paths = _as_list(intelligence.get("certifiedPaths"))
    capacity_model = _as_dict(intelligence.get("capacityModel"))
    timing_model = _as_dict(intelligence.get("timingModel"))
    checks = [
        {
            "id": "certified_paths",
            "label": "Certified paths",
            "status": "passed" if any(path.get("certificationStatus") == "venue_certified" for path in certified_paths if isinstance(path, dict)) else "missing",
            "detail": "At least one path has venue_certified status.",
            "replacementField": "profile_intelligence.certified_paths",
        },
        {
            "id": "capacity_model",
            "label": "Capacity model",
            "status": "passed" if capacity_model.get("status") == "venue_certified" and _as_list(capacity_model.get("zoneComfort")) else "missing",
            "detail": "Capacity status is venue_certified and zoneComfort rows are present.",
            "replacementField": "profile_intelligence.capacity_model",
        },
        {
            "id": "timing_model",
            "label": "Timing model",
            "status": "passed" if timing_model.get("status") == "venue_scheduled" and (_as_list(timing_model.get("showtimes")) or _as_list(timing_model.get("blackoutWindows"))) else "missing",
            "detail": "Timing status is venue_scheduled with showtimes or blackout windows.",
            "replacementField": "profile_intelligence.timing_model",
        },
    ]
    passed = sum(1 for check in checks if check["status"] == "passed")
    optional = {
        "experienceRules": bool(_as_dict(intelligence.get("experienceRules"))),
        "brandBible": bool(_as_dict(intelligence.get("brandBible"))),
        "reviewOwners": bool(_as_dict(intelligence.get("reviewOwners"))),
        "liveFeedBindings": bool(_as_dict(intelligence.get("liveFeedBindings"))),
    }
    supplied_keys = sorted(_normalize_profile_intelligence(supplied).keys())
    if not supplied:
        status = "not_supplied"
    elif passed == len(checks):
        status = "certified"
    elif passed:
        status = "partial"
    else:
        status = "supplied_but_not_certified"
    return {
        "version": PROFILE_INTELLIGENCE_VERSION,
        "status": status,
        "realVenueReady": status == "certified",
        "score": round((passed / len(checks)) * 100),
        "requiredChecks": checks,
        "optionalCoverage": optional,
        "suppliedKeys": supplied_keys,
        "missingForRealVenueReady": [check["replacementField"] for check in checks if check["status"] != "passed"],
    }


def _module_policy(agent_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "experience_studio": {
            "mayDraft": ["themed copy", "guest journey concepts", "scavenger hunts", "VIP scripts", "pre-arrival email drafts"],
            "mustReview": ["safety messaging", "accessibility language", "claims about availability or staff actions"],
            "neverClaim": ["guaranteed access", "certified safety status", "medical or allergy assurance"],
        },
        "accessibility_journey": {
            "mayRecommend": ["public route options", "rest points", "staff handoff points", "conservative alternates"],
            "mustReview": ["ride transfer help", "allergy dining", "medical uncertainty", "route blockage"],
            "neverClaim": ["ADA compliance", "equipment availability", "diagnosis-specific advice"],
        },
        "command_center_review": {
            "mayUse": ["zone priors", "public map anchors", "handoff owners", "safety instruction references"],
            "mustReview": ["physical reroutes", "access lane changes", "staff dispatch", "guest compensation"],
            "neverClaim": ["live staffing from profile data", "incident resolution without live confirmation"],
        },
        "learning_evaluation": {
            "mayLearnFrom": ["reviewer labels", "aggregate route outcomes", "source version", "zone and segment context"],
            "mustExclude": ["private guest identity", "medical diagnosis", "disability identity", "protected class"],
            "knownGaps": agent_context.get("knownGaps") or [],
        },
    }


def _field_source_ledger(export: dict[str, Any]) -> dict[str, Any]:
    source_catalog = _source_catalog(export)
    field_sources = _as_dict(source_catalog.get("field_sources"))
    sources = _sources(export)
    rows = []
    for field, source_ids in field_sources.items():
        for source_id in _as_list(source_ids):
            source = _as_dict(sources.get(str(source_id)))
            rows.append(
                {
                    "field": field,
                    "sourceId": source_id,
                    "label": source.get("label"),
                    "sourceType": source.get("source_type"),
                    "reviewStatus": source.get("review_status"),
                    "lastVerifiedAt": source.get("last_verified_at"),
                    "maxAgeSeconds": source.get("max_age_seconds"),
                    "confidence": source.get("confidence"),
                    "staleBehavior": "block_guest_facing_claims" if field in {"venue_map", "landmarks", "food"} else "require_review",
                }
            )
    return {
        "status": "ready" if rows else "missing_source_catalog",
        "rows": rows,
        "staleFieldPolicy": [
            "Block guest-facing safety, accessibility, menu, and path claims when their source is stale.",
            "Allow creative drafts from stale copy sources only with reviewer warning.",
            "Do not use seed_catalog source types for production grounding.",
        ],
    }


def _brand_bible(export: dict[str, Any]) -> dict[str, Any]:
    identity = _venue_identity(export)
    copy_variants = _as_dict(export.get("copy_variants"))
    return {
        "brandName": identity.get("name"),
        "tone": ["clear", "warm", "family-friendly", "operationally cautious"],
        "audiences": identity.get("primaryAudiences") or [],
        "copyRules": [
            "Use public place names exactly as venue-approved.",
            "Prefer plain language for safety, accessibility, and wayfinding.",
            "Use staff-confirmation language for allergy, medical, accessibility, and ride-rule uncertainty.",
            "Avoid fear-based phrasing during weather, crowd, or safety guidance.",
        ],
        "bannedClaims": ["guaranteed", "allergen-free", "ADA compliant", "always available", "no wait"],
        "supportedLocales": sorted(copy_variants.keys()),
        "approvedSnippets": copy_variants,
    }


def _live_feed_bindings(details: dict[str, dict[str, Any]], zones: dict[str, dict[str, Any]]) -> dict[str, Any]:
    attraction_bindings = []
    food_bindings = []
    care_bindings = []
    for name, item in details.items():
        kind = _text(item.get("kind"))
        row = {"name": name, "zoneId": item.get("zoneId"), "profileKey": name}
        if kind in {"attraction", "show"}:
            attraction_bindings.append({**row, "liveFeed": "guestFlow.rides", "matchStrategy": "name_or_profile_id"})
        elif kind == "food":
            food_bindings.append({**row, "liveFeed": "foodInventory.locations", "matchStrategy": "name_or_profile_id"})
        elif kind in {"first_aid", "guest_services", "family_service", "restrooms"}:
            care_bindings.append({**row, "liveFeed": "incidentReadiness_or_staff_handoff", "matchStrategy": "zone_and_service_kind"})
    return {
        "zones": [
            {"zoneId": zone_id, "liveFeed": "guestFlow.zones", "matchStrategy": "zone_id", "profileRole": zone.get("role")}
            for zone_id, zone in zones.items()
        ],
        "attractions": attraction_bindings,
        "food": food_bindings,
        "careAndServices": care_bindings,
        "weather": [
            {"profileField": "zoneDetails.indoorOrSheltered", "liveFeed": "weather", "use": "rank shelter and exposed-route risk"},
            {"profileField": "zoneDetails.quietOrCooling", "liveFeed": "weather.heatIndexF", "use": "rank cooling breaks"},
        ],
        "missingBindingsPolicy": "If a live feed cannot be matched, agents may draft but must mark the recommendation as needing operator confirmation.",
    }


def _outcome_learning_schema(learning_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": "venue_profile_learning_schema_v1",
        "observationKeys": learning_context.get("observationKeys") or [],
        "feedbackLabels": learning_context.get("feedbackLabels") or [],
        "successMetrics": [
            "guest_completed_route",
            "reviewer_accepted_without_safety_edit",
            "lower_confusion_report_rate",
            "staff_handoff_completed_when_required",
        ],
        "failureMetrics": [
            "edited_for_safety",
            "rerouted_by_staff",
            "blocked_by_missing_profile_fact",
            "guest_reported_confusion",
        ],
        "updateTargets": {
            "profile_update": ["blocked_by_missing_profile_fact", "rerouted_by_staff"],
            "prompt_or_policy_update": ["edited_for_safety", "guest_reported_confusion"],
            "source_feed_update": ["stale_source_detected", "live_feed_binding_missing"],
        },
        "reviewOwners": {
            "experience_design": "Park Experience Content Owner",
            "accessibility_journey": "Guest Experience Training Owner",
            "dining_allergy_handoff": "Digital Experience Owner",
            "command_center_triage": "Operations Review Lead",
        },
    }


def _profile_intelligence(
    export: dict[str, Any],
    details: dict[str, dict[str, Any]],
    zones: dict[str, dict[str, Any]],
    spatial_model: dict[str, Any],
    guest_segments: list[dict[str, Any]],
    operating_priors: dict[str, Any],
    learning_context: dict[str, Any],
    agent_context: dict[str, Any],
) -> dict[str, Any]:
    supplied_raw = _profile_intelligence_supplied(export)
    supplied = _normalize_profile_intelligence(supplied_raw)
    generated = {
        "version": PROFILE_INTELLIGENCE_VERSION,
        "certifiedPaths": _certified_paths(spatial_model),
        "capacityModel": _capacity_model(zones),
        "experienceRules": _experience_rules(export, zones, details),
        "segmentNeeds": _segment_needs(guest_segments),
        "timingModel": _timing_model(export),
        "modulePolicy": _module_policy(agent_context),
        "fieldSourceLedger": _field_source_ledger(export),
        "learningSchema": _outcome_learning_schema(learning_context),
        "brandBible": _brand_bible(export),
        "liveFeedBindings": _live_feed_bindings(details, zones),
        "operatingContext": _experience_operations(export),
    }
    merged = {**generated, **{key: value for key, value in supplied.items() if value not in (None, "", [], {})}}
    merged["source"] = "venue_profile.profile_intelligence" if supplied_raw else "derived_from_approved_venue_profile"
    merged["coverage"] = {
        "certifiedPaths": len(_as_list(merged.get("certifiedPaths"))),
        "capacityZones": len(_as_list(_as_dict(merged.get("capacityModel")).get("zoneComfort"))),
        "experienceRuleGroups": len(_as_dict(merged.get("experienceRules"))),
        "segmentNeeds": len(_as_dict(merged.get("segmentNeeds"))),
        "timingEvents": len(_as_list(_as_dict(merged.get("timingModel")).get("showDurationModel"))),
        "policyModules": len(_as_dict(merged.get("modulePolicy"))),
        "fieldSourceRows": len(_as_list(_as_dict(merged.get("fieldSourceLedger")).get("rows"))),
        "learningLabels": len(_as_list(_as_dict(merged.get("learningSchema")).get("feedbackLabels"))),
        "liveFeedBindingGroups": len(_as_dict(merged.get("liveFeedBindings"))),
        "currentOptions": int(_as_dict(_as_dict(merged.get("operatingContext")).get("coverage")).get("currentOptions") or 0),
        "pathStatusSegments": int(_as_dict(_as_dict(merged.get("operatingContext")).get("coverage")).get("pathStatusSegments") or 0),
        "signagePlacements": int(_as_dict(_as_dict(merged.get("operatingContext")).get("coverage")).get("signagePlacements") or 0),
        "channelTemplates": int(_as_dict(_as_dict(merged.get("operatingContext")).get("coverage")).get("channelTemplates") or 0),
        "operatingEventWindows": int(_as_dict(_as_dict(merged.get("operatingContext")).get("coverage")).get("eventWindows") or 0),
        "venueOwnedOverrides": len(supplied),
    }
    readiness = _profile_intelligence_readiness(merged, supplied_raw)
    merged["qualityGaps"] = [
        gap
        for gap in [
            "certified path feed missing; paths are derived hints" if not any(path.get("certificationStatus") == "venue_certified" for path in _as_list(merged.get("certifiedPaths"))) else "",
            "capacity model is heuristic until venue supplies room, queue, and seating capacities" if _as_dict(merged.get("capacityModel")).get("status") != "venue_certified" else "",
            "exact showtimes, parade routes, setup, teardown, and blackout windows require a schedule feed" if _as_dict(merged.get("timingModel")).get("status") != "venue_scheduled" else "",
        ]
        if gap
    ]
    merged["readiness"] = readiness
    merged["contract"] = profile_intelligence_contract()
    return merged


def _channel_owners(export: dict[str, Any]) -> dict[str, str]:
    owners = _as_dict(export.get("channel_owners"))
    return {key: _text(owners.get(key)) for key in REQUIRED_CHANNEL_OWNERS if _text(owners.get(key))}


def _experience_validation_issues(export: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not export:
        return [
            {
                "id": "venue_export_not_connected",
                "severity": "critical",
                "field": "PARKPULSE_CUSTOMER_VENUE_EXPORT_PATH",
                "detail": "No real venue export is configured.",
            }
        ]
    if _is_sample_export(export):
        issues.append(
            {
                "id": "sample_export_not_allowed",
                "severity": "critical",
                "field": "loaded_from",
                "detail": "Sample venue exports cannot be used for Experience Studio autofill.",
            }
        )

    locations = _venue_location_names(export)
    indoor = _venue_indoor_or_sheltered(export)
    accessibility = _venue_accessibility_notes(export)
    safety = _venue_safety_instructions(export)
    owners = _channel_owners(export)

    checks = [
        ("verified_locations", len(locations) >= 3, "critical", "At least three venue-approved public locations are required.", "locations"),
        ("indoor_or_sheltered_locations", bool(indoor), "high", "At least one venue-approved indoor or sheltered location is required.", "indoorLocations"),
        ("accessibility_notes", bool(accessibility), "critical", "Venue-approved accessibility notes or map facts are required.", "accessibleRoutes"),
        ("safety_instructions", bool(safety), "critical", "Venue-approved safety or first-aid guest instructions are required.", "safetyInstructions"),
        ("channel_owners", all(key in owners for key in REQUIRED_CHANNEL_OWNERS), "critical", "Guest app, signage, email, and staff cue owners are required.", "channel_owners"),
    ]
    for issue_id, passed, severity, detail, field in checks:
        if not passed:
            issues.append({"id": issue_id, "severity": severity, "field": field, "detail": detail})
    return issues


def validate_venue_experience_export(export: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = deepcopy(export) if isinstance(export, dict) else customer_venue_export()
    customer_validation = validate_customer_venue_export(payload) if payload else validate_customer_venue_export({})
    experience_issues = _experience_validation_issues(payload)
    critical_count = sum(1 for issue in experience_issues if issue.get("severity") == "critical")
    high_count = sum(1 for issue in experience_issues if issue.get("severity") == "high")
    customer_ready = customer_validation.get("status") == "production_ready"
    studio_ready = customer_ready and not experience_issues
    profile_readiness = _profile_intelligence_readiness(_normalize_profile_intelligence(_profile_intelligence_supplied(payload)), _profile_intelligence_supplied(payload))
    profile_type = _venue_identity(payload).get("profileType") if payload else "not_connected"
    synthetic_source = _has_synthetic_sources(payload) or profile_type == "synthetic_approved"
    return {
        "status": "studio_ready" if studio_ready else "blocked",
        "customerValidation": customer_validation,
        "experienceIssueCount": len(experience_issues),
        "criticalCount": critical_count,
        "highCount": high_count,
        "issues": experience_issues,
        "autofillAllowed": bool(payload) and customer_ready and not _is_sample_export(payload),
        "handoffReady": studio_ready,
        "profileIntelligence": profile_readiness,
        "realVenueReady": bool(studio_ready and not synthetic_source and profile_readiness.get("realVenueReady")),
        "loadedFrom": payload.get("loaded_from") if isinstance(payload, dict) else None,
    }


def build_venue_experience_data_from_export(export: dict[str, Any] | None, loaded_from: str | None = None) -> dict[str, Any]:
    validation = validate_venue_experience_export(export if export else {})
    profile_type = (_venue_identity(export).get("profileType") if export else "not_connected")
    is_approved_synthetic = profile_type == "synthetic_approved" or _has_synthetic_sources(export or {})
    location_details = _location_details(export) if export and validation.get("autofillAllowed") else {}
    zone_details = _zone_intelligence(export, location_details) if export and validation.get("autofillAllowed") else {}
    spatial_model = _spatial_model(export, zone_details) if export and validation.get("autofillAllowed") else {"zones": {}, "paths": []}
    guest_segments = _guest_segments(export, zone_details) if export and validation.get("autofillAllowed") else []
    operating_priors = _operating_priors(export, zone_details) if export and validation.get("autofillAllowed") else {}
    learning_context = _learning_context(export, zone_details) if export and validation.get("autofillAllowed") else {}
    agent_context = _agent_context(export, zone_details) if export and validation.get("autofillAllowed") else {}
    operating_context = _experience_operations(export) if export and validation.get("autofillAllowed") else {}
    profile_intelligence = (
        _profile_intelligence(export, location_details, zone_details, spatial_model, guest_segments, operating_priors, learning_context, agent_context)
        if export and validation.get("autofillAllowed")
        else {}
    )
    real_inputs = {
        "source": f"venue_experience_data:{loaded_from or validation.get('loadedFrom') or 'not_connected'}",
        "venueIdentity": _venue_identity(export) if export else None,
        "locations": _venue_location_names(export) if validation.get("autofillAllowed") else [],
        "indoorLocations": _venue_indoor_or_sheltered(export) if validation.get("autofillAllowed") else [],
        "quietLocations": _venue_quiet_or_cooling(export) if validation.get("autofillAllowed") else [],
        "attractionLocations": _venue_attraction_names(export) if validation.get("autofillAllowed") else [],
        "accessibleRoutes": _venue_accessibility_notes(export) if validation.get("autofillAllowed") else [],
        "safetyInstructions": _venue_safety_instructions(export) if validation.get("autofillAllowed") else [],
        "channelOwners": _channel_owners(export) if validation.get("autofillAllowed") else {},
        "locationDetails": location_details,
        "zoneDetails": zone_details,
        "spatialModel": spatial_model,
        "guestSegments": guest_segments,
        "operatingPriors": operating_priors,
        "operatingContext": operating_context,
        "currentStatus": operating_context.get("currentStatus", {}) if operating_context else {},
        "pathStatus": operating_context.get("pathStatus", {}) if operating_context else {},
        "signageInventory": operating_context.get("signageInventory", {}) if operating_context else {},
        "channelTemplates": operating_context.get("channelTemplates", {}) if operating_context else {},
        "operatingCalendar": operating_context.get("operatingCalendar", {}) if operating_context else {},
        "weatherPolicy": operating_context.get("weatherPolicy", {}) if operating_context else {},
        "learningContext": learning_context,
        "agentContext": agent_context,
        "profileIntelligence": profile_intelligence,
    }
    counts = {
        "locations": len(real_inputs["locations"]),
        "indoorLocations": len(real_inputs["indoorLocations"]),
        "accessibleRoutes": len(real_inputs["accessibleRoutes"]),
        "safetyInstructions": len(real_inputs["safetyInstructions"]),
        "channelOwners": len(real_inputs["channelOwners"]),
        "zones": len(zone_details),
        "paths": len(spatial_model.get("paths") or []) if isinstance(spatial_model, dict) else 0,
        "guestSegments": len(guest_segments),
        "agentGroundingFields": len(agent_context.get("groundingFields") or []) if isinstance(agent_context, dict) else 0,
        "learningSignals": len(learning_context.get("feedbackLabels") or []) if isinstance(learning_context, dict) else 0,
        "certifiedPaths": len(profile_intelligence.get("certifiedPaths") or []) if isinstance(profile_intelligence, dict) else 0,
        "capacityZones": len((profile_intelligence.get("capacityModel") or {}).get("zoneComfort") or []) if isinstance(profile_intelligence, dict) else 0,
        "fieldSourceRows": len((profile_intelligence.get("fieldSourceLedger") or {}).get("rows") or []) if isinstance(profile_intelligence, dict) else 0,
        "modulePolicies": len(profile_intelligence.get("modulePolicy") or {}) if isinstance(profile_intelligence, dict) else 0,
        "liveFeedBindingGroups": len(profile_intelligence.get("liveFeedBindings") or {}) if isinstance(profile_intelligence, dict) else 0,
        "currentOptions": len(((operating_context.get("currentStatus") or {}).get("attractions") or [])) if isinstance(operating_context, dict) else 0,
        "pathStatusSegments": len(((operating_context.get("pathStatus") or {}).get("routeSegments") or [])) if isinstance(operating_context, dict) else 0,
        "signagePlacements": len(((operating_context.get("signageInventory") or {}).get("placements") or [])) if isinstance(operating_context, dict) else 0,
        "channelTemplates": len(((operating_context.get("channelTemplates") or {}).get("templates") or {})) if isinstance(operating_context, dict) else 0,
        "operatingEventWindows": len(((operating_context.get("operatingCalendar") or {}).get("eventWindows") or [])) if isinstance(operating_context, dict) else 0,
    }
    return {
        "status": "ready",
        "mode": "venue_experience_data",
        "venueIdentity": _venue_identity(export) if export else None,
        "readiness": {
            "status": validation["status"],
            "autofillAllowed": validation["autofillAllowed"],
            "handoffReady": validation["handoffReady"],
            "loadedFrom": loaded_from or validation.get("loadedFrom"),
            "counts": counts,
            "issues": validation["issues"],
            "profileIntelligence": profile_intelligence.get("readiness") if isinstance(profile_intelligence, dict) else validation.get("profileIntelligence"),
            "realVenueReady": bool(validation.get("realVenueReady")),
        },
        "realInputs": real_inputs,
        "sourceIntegrity": {
            "usesSeedData": False,
            "usesSampleData": _is_sample_export(export),
            "usesApprovedSyntheticProfile": is_approved_synthetic,
            "realVenueFeedConnected": bool(export) and not is_approved_synthetic,
            "realVenueReady": bool(not is_approved_synthetic and profile_intelligence.get("readiness", {}).get("realVenueReady")) if isinstance(profile_intelligence, dict) else False,
            "profileType": profile_type,
            "customerValidationStatus": validation["customerValidation"].get("status"),
            "profileIntelligenceStatus": profile_intelligence.get("readiness", {}).get("status") if isinstance(profile_intelligence, dict) else validation.get("profileIntelligence", {}).get("status"),
        },
        "validation": validation,
        "contract": {
            "requiredFields": [
                "verified public locations",
                "indoor or sheltered locations",
                "accessibility map facts",
                "safety instructions",
                "channel owners",
                "agent grounding fields",
                "learning outcome labels",
                "profile intelligence contract",
            ],
            "blockedSources": ["seed_catalog", "sample venue exports", "simulated park state"],
            "agentUse": "Agents may reason from Venue Profile facts and derived public-map intelligence, but must separate profile priors from live state and human-authorized actions.",
        },
    }


def build_venue_experience_data() -> dict[str, Any]:
    export = customer_venue_export()
    return build_venue_experience_data_from_export(export)


def activate_synthetic_venue_export(actor: str = "experience_studio") -> dict[str, Any]:
    try:
        export = approved_synthetic_venue_export()
    except Exception as error:
        return {
            "status": "blocked",
            "mode": "synthetic_venue_profile_activation",
            "message": f"Approved synthetic venue profile could not load: {str(error)[:240]}",
        }
    return import_venue_experience_export(
        {
            "sourceName": "parkpulse_synthetic_venue_export.approved.json",
            "export": export,
            "actor": actor or "experience_studio",
        }
    )


def import_venue_experience_export(payload: dict[str, Any]) -> dict[str, Any]:
    export = payload.get("export") if isinstance(payload.get("export"), dict) else {}
    source_name = _text(payload.get("sourceName") or payload.get("source_name"))
    actor = _text(payload.get("actor")) or "venue_data_admin"
    if not export:
        return {
            "status": "blocked",
            "mode": "venue_experience_data_import",
            "message": "Import requires an export JSON object.",
            "validation": validate_venue_experience_export({}),
        }
    if not source_name:
        return {
            "status": "blocked",
            "mode": "venue_experience_data_import",
            "message": "Import requires a real source name, such as a venue CMS export path or approved data package name.",
            "validation": validate_venue_experience_export(export),
        }

    candidate = deepcopy(export)
    candidate["loaded_from"] = source_name
    validation = validate_venue_experience_export(candidate)
    if validation.get("status") != "studio_ready":
        return {
            "status": "blocked",
            "mode": "venue_experience_data_import",
            "message": "Venue export did not pass Experience Studio readiness checks.",
            "validation": validation,
        }

    saved = deepcopy(export)
    saved["imported_by"] = actor
    saved["imported_source_name"] = source_name
    target = _runtime_export_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(f"{target.suffix}.tmp")
    temp.write_text(json.dumps(saved, indent=2, default=str), encoding="utf-8")
    temp.replace(target)
    os.environ["PARKPULSE_CUSTOMER_VENUE_EXPORT_PATH"] = str(target)
    return {
        "status": "imported",
        "mode": "venue_experience_data_import",
        "message": "Venue export imported and activated for Experience Studio.",
        "savedTo": str(target),
        "sourceName": source_name,
        "validation": validate_venue_experience_export(customer_venue_export()),
        "venueExperienceData": build_venue_experience_data(),
    }


def resolve_experience_studio_real_inputs(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved = deepcopy(payload) if isinstance(payload, dict) else {}
    venue_data = build_venue_experience_data()
    if resolved.get("useVenueExperienceData") is not True:
        return resolved, venue_data
    if not venue_data.get("readiness", {}).get("autofillAllowed"):
        return resolved, venue_data

    existing = _as_dict(resolved.get("realInputs"))
    venue_inputs = _as_dict(venue_data.get("realInputs"))
    merged = deepcopy(existing)
    for key in (
        "locations",
        "indoorLocations",
        "quietLocations",
        "attractionLocations",
        "accessibleRoutes",
        "safetyInstructions",
        "zoneDetails",
        "spatialModel",
        "guestSegments",
        "operatingPriors",
        "learningContext",
        "agentContext",
        "profileIntelligence",
    ):
        if not _as_list(existing.get(key)) and not _text(existing.get(key)):
            merged[key] = venue_inputs.get(key, [])
    existing_owners = _as_dict(existing.get("channelOwners"))
    venue_owners = _as_dict(venue_inputs.get("channelOwners"))
    merged["channelOwners"] = {**venue_owners, **{key: value for key, value in existing_owners.items() if _text(value)}}
    if not _as_dict(existing.get("venueIdentity")):
        merged["venueIdentity"] = venue_inputs.get("venueIdentity")
    if not _as_dict(existing.get("locationDetails")):
        merged["locationDetails"] = venue_inputs.get("locationDetails", {})
    if not _text(existing.get("source")):
        merged["source"] = venue_inputs.get("source")
    else:
        merged["source"] = f"{existing.get('source')} + {venue_inputs.get('source')}"
    resolved["realInputs"] = merged
    resolved["venueExperienceDataUsed"] = True
    return resolved, venue_data
