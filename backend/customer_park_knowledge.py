from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import time
from typing import Any


_ATTRACTIONS: list[dict[str, Any]] = [
    {
        "id": "dragonCoaster",
        "aliases": ["dragon", "coaster", "dragon coaster"],
        "name": "Dragon Coaster",
        "zone_id": "coasterPlaza",
        "category": "thrill coaster",
        "thrill_level": "high",
        "duration_minutes": 3,
        "height_requirement_inches": 48,
        "indoor": False,
        "outdoor": True,
        "family_fit": "best for thrill-seeking groups with eligible riders",
        "accessibility_note": "Use the marked accessible queue entrance near Coaster Plaza.",
        "sensory_note": "Fast turns, loud launch audio, and outdoor exposure.",
        "guest_tips": ["Use this when waits are moderate and weather is clear.", "Avoid sending every displaced group here during surge periods."],
    },
    {
        "id": "indoorLaunch",
        "aliases": ["indoor launch", "launch ride"],
        "name": "Indoor Launch",
        "zone_id": "indoorHub",
        "category": "indoor thrill ride",
        "thrill_level": "medium-high",
        "duration_minutes": 4,
        "height_requirement_inches": 44,
        "indoor": True,
        "outdoor": False,
        "family_fit": "good weather-safe thrill option",
        "accessibility_note": "Accessible entrance is inside Indoor Hub by the blue elevator bank.",
        "sensory_note": "Dark scenes, launch motion, and moderate audio.",
        "guest_tips": ["Strong option during heat or storm risk.", "Mention indoor queue comfort when outdoor areas are busy."],
    },
    {
        "id": "skyDrop",
        "aliases": ["sky drop", "drop tower"],
        "name": "Sky Drop",
        "zone_id": "skyPier",
        "category": "drop tower",
        "thrill_level": "high",
        "duration_minutes": 2,
        "height_requirement_inches": 52,
        "indoor": False,
        "outdoor": True,
        "family_fit": "best for older thrill riders",
        "accessibility_note": "Ask nearby attraction staff for transfer boarding support.",
        "sensory_note": "Sudden drop, heights, wind exposure.",
        "guest_tips": ["Avoid during high wind or storm risk.", "Works as a short-duration thrill option when queue is light."],
    },
    {
        "id": "arcade",
        "aliases": ["arcade zone", "arcade"],
        "name": "Arcade Zone",
        "zone_id": "arcadeZone",
        "category": "indoor games",
        "thrill_level": "low",
        "duration_minutes": 20,
        "height_requirement_inches": None,
        "indoor": True,
        "outdoor": False,
        "family_fit": "good for mixed-age groups and breaks",
        "accessibility_note": "Main aisles are step-free; lower-crowd side entrance is near Covered Plaza.",
        "sensory_note": "Flashing lights and game audio.",
        "guest_tips": ["Useful as a low-wait backup.", "Do not overload it when crowd density is already high."],
    },
    {
        "id": "theaterB",
        "aliases": ["theater", "theatre", "show", "theater b"],
        "name": "Theater B",
        "zone_id": "indoorHub",
        "category": "indoor show",
        "thrill_level": "low",
        "duration_minutes": 18,
        "height_requirement_inches": None,
        "indoor": True,
        "outdoor": False,
        "family_fit": "best for cooling down, families, and mixed mobility groups",
        "accessibility_note": "Wheelchair seating is available on the entry level.",
        "sensory_note": "Seated show with moderate audio and low motion.",
        "guest_tips": ["Good recovery option during heat, rain, or high waits.", "Pair with nearby food pickup when show timing allows."],
    },
]

_FOOD: list[dict[str, Any]] = [
    {
        "id": "foodCourtA",
        "aliases": ["foodcourt1", "food court a", "food court 1", "pizza", "pizza pier"],
        "name": "Food Court A",
        "zone_id": "foodCourt1",
        "cuisine": "burgers, tenders, pizza, drinks",
        "dietary_tags": ["vegetarian options", "kids meals"],
        "mobile_order": True,
        "seating": "large indoor/outdoor family seating",
        "shade": "partial",
        "guest_tips": ["Avoid recommending if pickup ETA or backlog is high.", "Good for full meals when pressure is normal."],
    },
    {
        "id": "foodCourtB",
        "aliases": ["food court b", "snack", "main street snacks", "snacks"],
        "name": "Food Court B",
        "zone_id": "foodCourt2",
        "cuisine": "snacks, pizza combo, drinks, grab-and-go",
        "dietary_tags": ["vegetarian options", "quick pickup"],
        "mobile_order": True,
        "seating": "compact shaded seating",
        "shade": "covered",
        "guest_tips": ["Strong backup when Food Court A is overloaded.", "Good for quick pickup before a show."],
    },
]

_LANDMARKS: dict[str, list[dict[str, Any]]] = {
    "restrooms": [
        {"id": "restroomEntrance", "name": "Entrance Plaza Restrooms", "zone_id": "entrancePlaza", "accessible": True, "family_room": True},
        {"id": "restroomIndoorHub", "name": "Indoor Hub Restrooms", "zone_id": "indoorHub", "accessible": True, "family_room": True},
        {"id": "restroomFoodCourtA", "name": "Food Court A Restrooms", "zone_id": "foodCourt1", "accessible": True, "family_room": False},
    ],
    "first_aid": [
        {"id": "careLagoon", "name": "Care Lagoon First Aid", "zone_id": "careLagoon", "guest_instruction": "For urgent issues, contact nearby staff immediately."}
    ],
    "guest_services": [
        {"id": "guestServicesEntrance", "name": "Guest Services", "zone_id": "entrancePlaza", "services": ["lost and found", "accessibility help", "ticket help"]},
        {"id": "familyReunification", "name": "Family Reunification Point", "zone_id": "careLagoon", "services": ["separated-party support"]},
    ],
    "water_refill": [
        {"id": "waterIndoorHub", "name": "Indoor Hub Water Refill", "zone_id": "indoorHub"},
        {"id": "waterCoveredPlaza", "name": "Covered Plaza Water Refill", "zone_id": "coveredPlaza"},
    ],
    "quiet_or_cooling": [
        {"id": "indoorHub", "name": "Indoor Hub", "zone_id": "indoorHub", "best_for": ["cooling", "lower sun exposure", "mobility-friendly routing"]},
        {"id": "coveredPlaza", "name": "Covered Plaza", "zone_id": "coveredPlaza", "best_for": ["shade", "storm shelter overflow"]},
        {"id": "theaterB", "name": "Theater B", "zone_id": "indoorHub", "best_for": ["seated break", "family cooldown"]},
    ],
}

_SHOWS: list[dict[str, Any]] = [
    {
        "id": "theaterB_show",
        "name": "Theater B Cooling Show",
        "zone_id": "indoorHub",
        "typical_duration_minutes": 18,
        "best_for": ["families", "heat break", "rain break"],
        "accessibility_note": "Entry-level wheelchair seating is available.",
    },
    {
        "id": "parade_crossing",
        "name": "Main Parade Crossing",
        "zone_id": "coasterPlaza",
        "typical_window": "afternoon",
        "guest_tip": "Expect slower walking routes during parade holds.",
    },
]

_FAMILY_SERVICES: list[dict[str, Any]] = [
    {"id": "strollerRental", "name": "Stroller Rental", "zone_id": "entrancePlaza"},
    {"id": "lockersEntrance", "name": "Entrance Lockers", "zone_id": "entrancePlaza"},
    {"id": "sensoryBreakIndoorHub", "name": "Indoor Hub Lower-Stimulus Corner", "zone_id": "indoorHub"},
]

_VENUE_MAP: dict[str, Any] = {
    "source": "parkpulse_demo_public_venue_map_v1",
    "scale": {"width_meters": 820, "height_meters": 540, "north": "top"},
    "nodes": [
        {"id": "frontGate", "name": "Front Gate", "type": "entry", "zone_id": "entrancePlaza", "x": 120, "y": 520, "width": 160, "height": 50},
        {"id": "mainStreet", "name": "Main Street Shops", "type": "retail", "zone_id": "entrancePlaza", "x": 245, "y": 454, "width": 180, "height": 56},
        {"id": "dragonCoaster", "name": "Dragon Coaster", "type": "attraction", "zone_id": "coasterPlaza", "x": 690, "y": 145, "width": 210, "height": 155},
        {"id": "indoorLaunch", "name": "Indoor Launch", "type": "attraction", "zone_id": "indoorHub", "x": 120, "y": 88, "width": 290, "height": 170},
        {"id": "theaterB", "name": "Theater B", "type": "show", "zone_id": "indoorHub", "x": 188, "y": 300, "width": 220, "height": 102},
        {"id": "arcade", "name": "Arcade Zone", "type": "attraction", "zone_id": "arcadeZone", "x": 435, "y": 312, "width": 185, "height": 102},
        {"id": "foodCourtA", "name": "Food Court A", "type": "food", "zone_id": "foodCourt1", "x": 615, "y": 470, "width": 190, "height": 85},
        {"id": "foodCourtB", "name": "Food Court B", "type": "food", "zone_id": "foodCourt2", "x": 245, "y": 454, "width": 180, "height": 56},
        {"id": "firstAid", "name": "First Aid", "type": "first_aid", "zone_id": "careLagoon", "x": 486, "y": 500, "width": 58, "height": 42},
        {"id": "fireworksViewing", "name": "Fireworks Viewing", "type": "show", "zone_id": "lake", "x": 620, "y": 335, "width": 275, "height": 66},
        {"id": "restroomEast", "name": "East Restrooms", "type": "restroom", "zone_id": "foodCourt1", "x": 578, "y": 438},
        {"id": "restroomWest", "name": "West Restrooms", "type": "restroom", "zone_id": "entrancePlaza", "x": 152, "y": 404},
        {"id": "waterNorth", "name": "North Water Refill", "type": "water_refill", "zone_id": "coveredPlaza", "x": 522, "y": 244},
        {"id": "lockerFront", "name": "Front Lockers", "type": "locker", "zone_id": "entrancePlaza", "x": 286, "y": 520},
        {"id": "guestServices", "name": "Guest Services", "type": "guest_services", "zone_id": "entrancePlaza", "x": 204, "y": 545},
        {"id": "shadeGarden", "name": "Shade Garden", "type": "quiet_or_cooling", "zone_id": "coveredPlaza", "x": 526, "y": 152},
    ],
}

_MENUS: dict[str, list[dict[str, Any]]] = {
    "foodCourtA": [
        {"name": "Dragon Burger Basket", "tags": ["kids meal available"], "mobile_order": True},
        {"name": "Pizza Slice Combo", "tags": ["vegetarian option"], "mobile_order": True},
        {"name": "Chicken Tender Basket", "tags": ["popular"], "mobile_order": True},
        {"name": "Bottled Water", "tags": ["quick pickup"], "mobile_order": True},
    ],
    "foodCourtB": [
        {"name": "Main Street Pretzel", "tags": ["vegetarian option", "quick pickup"], "mobile_order": True},
        {"name": "Pizza Combo", "tags": ["family share"], "mobile_order": True},
        {"name": "Fruit Cup", "tags": ["lighter option"], "mobile_order": True},
        {"name": "Cold Drinks", "tags": ["quick pickup"], "mobile_order": True},
    ],
}

_COPY_VARIANTS: dict[str, dict[str, str]] = {
    "en": {
        "route_help": "I can show the best public route from here.",
        "service_help": "Guest Services and First Aid are available on the public map.",
        "weather_help": "For heat or rain, prefer Indoor Hub, Theater B, Arcade Zone, or Covered Plaza.",
    },
    "es": {
        "route_help": "Puedo mostrar la mejor ruta publica desde aqui.",
        "service_help": "Servicios al visitante y primeros auxilios aparecen en el mapa publico.",
        "weather_help": "Con calor o lluvia, use Indoor Hub, Theater B, Arcade Zone o Covered Plaza.",
    },
}


def customer_park_knowledge() -> dict[str, Any]:
    source_catalog = customer_park_source_catalog()
    venue_export = customer_venue_export()
    return {
        "version": "customer_public_park_knowledge_v1",
        "attractions": deepcopy(venue_export.get("attractions") if isinstance(venue_export.get("attractions"), list) else _ATTRACTIONS),
        "food": deepcopy(venue_export.get("food") if isinstance(venue_export.get("food"), list) else _FOOD),
        "landmarks": deepcopy(venue_export.get("landmarks") if isinstance(venue_export.get("landmarks"), dict) else _LANDMARKS),
        "shows": deepcopy(venue_export.get("shows") if isinstance(venue_export.get("shows"), list) else _SHOWS),
        "family_services": deepcopy(venue_export.get("family_services") if isinstance(venue_export.get("family_services"), list) else _FAMILY_SERVICES),
        "venue_map": deepcopy(venue_export.get("venue_map") if isinstance(venue_export.get("venue_map"), dict) else _VENUE_MAP),
        "menus": deepcopy(venue_export.get("menus") if isinstance(venue_export.get("menus"), dict) else _MENUS),
        "copy_variants": deepcopy(venue_export.get("copy_variants") if isinstance(venue_export.get("copy_variants"), dict) else _COPY_VARIANTS),
        "source_catalog": venue_export.get("source_catalog") if isinstance(venue_export.get("source_catalog"), dict) else source_catalog,
        "venue_export": {
            "connected": bool(venue_export),
            "version": venue_export.get("version") if isinstance(venue_export, dict) else None,
            "loaded_from": venue_export.get("loaded_from") if isinstance(venue_export, dict) else None,
            "validation": validate_customer_venue_export(venue_export) if venue_export else None,
        },
        "boundaries": [
            "Public attraction, food, restroom, first-aid, guest-services, route, map, schedule, accessibility, and weather facts only.",
            "No internal staffing, security procedures, policy internals, model behavior, training data, or private guest records.",
        ],
    }


def customer_park_source_catalog() -> dict[str, Any]:
    configured_path = os.getenv("PARKPULSE_CUSTOMER_SOURCE_CATALOG_PATH")
    source_path = Path(configured_path) if configured_path else Path(__file__).with_name("data") / "customer_public_park_sources.json"
    try:
        with source_path.open("r", encoding="utf-8") as handle:
            catalog = json.load(handle)
        if not isinstance(catalog, dict):
            raise ValueError("source catalog must be a JSON object")
        catalog = deepcopy(catalog)
        catalog["loaded_from"] = str(source_path)
    except Exception as error:
        catalog = {
            "version": "customer_public_source_catalog_fallback",
            "catalog_status": "source_catalog_unavailable",
            "real_venue_feed_connected": False,
            "sources": {},
            "field_sources": {},
            "review_queue": [{"id": "source_catalog_load_failed", "severity": "high", "owner": "platform", "item": str(error)[:240]}],
            "publish_gates": ["Source catalog must load before production publishing."],
            "loaded_from": str(source_path),
        }
    catalog["loaded_at_epoch"] = int(time.time())
    return catalog


def customer_venue_export() -> dict[str, Any]:
    configured_path = os.getenv("PARKPULSE_CUSTOMER_VENUE_EXPORT_PATH")
    if not configured_path:
        runtime_path = Path(os.getenv("PARKPULSE_CUSTOMER_VENUE_EXPORT_RUNTIME_PATH", "/tmp/parkpulse/customer_venue_export.json"))
        configured_path = str(runtime_path) if runtime_path.exists() else ""
    if not configured_path:
        return {}
    source_path = Path(configured_path)
    try:
        with source_path.open("r", encoding="utf-8") as handle:
            export = json.load(handle)
        if not isinstance(export, dict):
            raise ValueError("venue export must be a JSON object")
        export = deepcopy(export)
        export["loaded_from"] = str(source_path)
        return export
    except Exception as error:
        return {
            "version": "customer_venue_export_load_failed",
            "loaded_from": str(source_path),
            "load_error": str(error)[:240],
        }


def customer_venue_export_template() -> dict[str, Any]:
    return {
        "version": "customer_venue_export_v1",
        "approved_for_production": True,
        "approved_by": "venue_content_ops",
        "approved_at": "2026-06-01T00:00:00Z",
        "source_catalog": {
            "version": "customer_public_source_catalog_v1",
            "catalog_status": "venue_verified",
            "real_venue_feed_connected": True,
            "sources": {
                "venue_attraction_rules": {
                    "label": "Venue-approved attraction rules",
                    "source_type": "venue_export.attractions",
                    "confidence": 0.96,
                    "review_status": "venue_approved",
                    "last_verified_at": "2026-06-01T00:00:00Z",
                    "max_age_seconds": 86400,
                },
                "venue_menu_catalog": {
                    "label": "Venue-approved menu and dietary catalog",
                    "source_type": "venue_export.food",
                    "confidence": 0.94,
                    "review_status": "venue_approved",
                    "last_verified_at": "2026-06-01T00:00:00Z",
                    "max_age_seconds": 3600,
                },
                "venue_public_map": {
                    "label": "Venue-approved public map",
                    "source_type": "venue_export.venue_map",
                    "confidence": 0.95,
                    "review_status": "venue_approved",
                    "last_verified_at": "2026-06-01T00:00:00Z",
                    "max_age_seconds": 86400,
                },
                "venue_event_schedule": {
                    "label": "Venue event schedule feed",
                    "source_type": "venue_export.event_schedule",
                    "confidence": 0.9,
                    "review_status": "venue_approved",
                    "last_verified_at": "2026-06-01T00:00:00Z",
                    "max_age_seconds": 300,
                },
                "venue_guest_copy": {
                    "label": "Venue-approved guest copy",
                    "source_type": "venue_export.copy_variants",
                    "confidence": 0.92,
                    "review_status": "venue_approved",
                    "last_verified_at": "2026-06-01T00:00:00Z",
                    "max_age_seconds": 604800,
                },
            },
            "field_sources": {
                "rides": ["venue_attraction_rules", "venue_public_map"],
                "food": ["venue_menu_catalog", "venue_public_map"],
                "venue_map": ["venue_public_map"],
                "event_schedule": ["venue_event_schedule"],
                "landmarks": ["venue_public_map"],
                "shows": ["venue_event_schedule", "venue_attraction_rules"],
                "family_services": ["venue_public_map"],
                "copy_variants": ["venue_guest_copy"],
            },
            "review_queue": [],
            "publish_gates": [
                "Every public fact has a venue source id.",
                "Accessibility, attraction requirements, first aid, and menu/dietary data are venue-approved.",
                "Backstage, staffing, policy, model, training, and private guest data are excluded.",
            ],
        },
        "attractions": [
            {
                "id": "theaterB",
                "aliases": ["theater", "theater b"],
                "name": "Theater B",
                "zone_id": "indoorHub",
                "category": "indoor show",
                "thrill_level": "low",
                "duration_minutes": 18,
                "height_requirement_inches": None,
                "indoor": True,
                "outdoor": False,
                "family_fit": "venue-approved cooling and seated show option",
                "accessibility_note": "Wheelchair seating is available on the entry level.",
                "sensory_note": "Moderate show audio with seated viewing.",
                "source_ids": ["venue_attraction_rules", "venue_public_map"],
            }
        ],
        "food": [
            {
                "id": "foodCourtB",
                "aliases": ["main street snacks", "snack"],
                "name": "Food Court B",
                "zone_id": "foodCourt2",
                "cuisine": "snacks, drinks, grab-and-go",
                "dietary_tags": ["vegetarian options", "quick pickup"],
                "mobile_order": True,
                "seating": "covered compact seating",
                "source_ids": ["venue_menu_catalog", "venue_public_map"],
            }
        ],
        "menus": {
            "foodCourtB": [
                {"name": "Main Street Pretzel", "tags": ["vegetarian option"], "mobile_order": True, "source_ids": ["venue_menu_catalog"]},
                {"name": "Cold Drinks", "tags": ["quick pickup"], "mobile_order": True, "source_ids": ["venue_menu_catalog"]}
            ]
        },
        "landmarks": {
            "restrooms": [{"id": "restroomIndoorHub", "name": "Indoor Hub Restrooms", "zone_id": "indoorHub", "accessible": True, "family_room": True, "source_ids": ["venue_public_map"]}],
            "first_aid": [{"id": "careLagoon", "name": "Care Lagoon First Aid", "zone_id": "careLagoon", "guest_instruction": "For urgent issues, contact nearby staff immediately.", "source_ids": ["venue_public_map"]}],
            "guest_services": [{"id": "guestServicesEntrance", "name": "Guest Services", "zone_id": "entrancePlaza", "services": ["lost and found", "accessibility help"], "source_ids": ["venue_public_map"]}],
            "water_refill": [{"id": "waterIndoorHub", "name": "Indoor Hub Water Refill", "zone_id": "indoorHub", "source_ids": ["venue_public_map"]}],
            "quiet_or_cooling": [{"id": "indoorHub", "name": "Indoor Hub", "zone_id": "indoorHub", "best_for": ["cooling", "mobility-friendly routing"], "source_ids": ["venue_public_map"]}],
        },
        "shows": [{"id": "theaterB_show", "name": "Theater B Cooling Show", "zone_id": "indoorHub", "typical_duration_minutes": 18, "source_ids": ["venue_event_schedule"]}],
        "family_services": [{"id": "strollerRental", "name": "Stroller Rental", "zone_id": "entrancePlaza", "source_ids": ["venue_public_map"]}],
        "venue_map": {
            "source": "venue_public_map",
            "scale": {"width_meters": 820, "height_meters": 540, "north": "top"},
            "nodes": [
                {"id": "theaterB", "name": "Theater B", "type": "show", "zone_id": "indoorHub", "x": 188, "y": 300, "width": 220, "height": 102, "source_ids": ["venue_public_map"]},
                {"id": "foodCourtB", "name": "Food Court B", "type": "food", "zone_id": "foodCourt2", "x": 245, "y": 454, "width": 180, "height": 56, "source_ids": ["venue_public_map"]},
                {"id": "careLagoon", "name": "Care Lagoon First Aid", "type": "first_aid", "zone_id": "careLagoon", "x": 486, "y": 500, "width": 58, "height": 42, "source_ids": ["venue_public_map"]}
            ],
        },
        "copy_variants": {
            "en": {
                "route_help": "I can show the best public route from here.",
                "service_help": "Guest Services and First Aid are available on the public map.",
                "weather_help": "For heat or rain, prefer indoor or covered options.",
            },
            "es": {
                "route_help": "Puedo mostrar la mejor ruta publica desde aqui.",
                "service_help": "Servicios al visitante y primeros auxilios aparecen en el mapa publico.",
                "weather_help": "Con calor o lluvia, use opciones interiores o cubiertas.",
            },
        },
    }


def validate_customer_venue_export(export: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(export) if isinstance(export, dict) else {}
    issues: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []

    def add(check_id: str, passed: bool, severity: str, detail: str, field: str | None = None) -> None:
        row = {"id": check_id, "passed": passed, "severity": severity, "detail": detail}
        if field:
            row["field"] = field
        checks.append(row)
        if not passed:
            issues.append({"id": check_id, "severity": severity, "field": field, "detail": detail})

    add("json_object", isinstance(export, dict), "critical", "Venue export must be a JSON object.")
    add("approved_for_production", bool(payload.get("approved_for_production")), "critical", "Venue export must be explicitly approved for production.", "approved_for_production")
    add("approved_metadata", bool(payload.get("approved_by")) and bool(payload.get("approved_at")), "high", "Venue export must include approved_by and approved_at.", "approved_by")

    source_catalog = payload.get("source_catalog") if isinstance(payload.get("source_catalog"), dict) else {}
    sources = source_catalog.get("sources", {}) if isinstance(source_catalog.get("sources"), dict) else {}
    field_sources = source_catalog.get("field_sources", {}) if isinstance(source_catalog.get("field_sources"), dict) else {}
    add("source_catalog_present", bool(source_catalog), "critical", "source_catalog is required.", "source_catalog")
    add("real_venue_feed_connected", bool(source_catalog.get("real_venue_feed_connected")), "critical", "source_catalog.real_venue_feed_connected must be true.", "source_catalog.real_venue_feed_connected")
    add("review_queue_empty", not _as_list(source_catalog.get("review_queue")), "critical", "source_catalog.review_queue must be empty.", "source_catalog.review_queue")
    add("no_seed_source_types", not any(isinstance(source, dict) and source.get("source_type") == "seed_catalog" for source in sources.values()), "critical", "Seed source types are not production-approved.", "source_catalog.sources")

    for field in ("rides", "food", "venue_map", "event_schedule", "landmarks", "shows", "family_services", "copy_variants"):
        ids = [str(source_id) for source_id in _as_list(field_sources.get(field))]
        add(f"field_sources_{field}", bool(ids), "critical", f"{field} must list source ids.", f"source_catalog.field_sources.{field}")
        add(
            f"field_sources_known_{field}",
            all(source_id in sources for source_id in ids),
            "critical",
            f"{field} source ids must exist in source_catalog.sources.",
            f"source_catalog.field_sources.{field}",
        )

    for source_id, source in sources.items():
        if not isinstance(source, dict):
            add(f"source_object_{source_id}", False, "critical", f"{source_id} must be a source object.", f"source_catalog.sources.{source_id}")
            continue
        confidence = source.get("confidence")
        add(f"source_confidence_{source_id}", isinstance(confidence, (int, float)) and float(confidence) >= 0.74, "high", f"{source_id} confidence must be >= 0.74.", f"source_catalog.sources.{source_id}.confidence")
        add(f"source_review_{source_id}", str(source.get("review_status") or "") == "venue_approved", "critical", f"{source_id} must be venue_approved.", f"source_catalog.sources.{source_id}.review_status")
        add(f"source_verified_at_{source_id}", bool(source.get("last_verified_at")), "high", f"{source_id} must include last_verified_at.", f"source_catalog.sources.{source_id}.last_verified_at")
        add(f"source_freshness_{source_id}", isinstance(source.get("max_age_seconds"), int), "high", f"{source_id} must include max_age_seconds.", f"source_catalog.sources.{source_id}.max_age_seconds")

    add("attractions_present", bool(_as_list(payload.get("attractions"))), "critical", "attractions must be populated.", "attractions")
    add("food_present", bool(_as_list(payload.get("food"))), "critical", "food must be populated.", "food")
    add("menus_present", bool(payload.get("menus")) if isinstance(payload.get("menus"), dict) else False, "critical", "menus must be populated.", "menus")
    add("venue_map_nodes_present", bool(_as_list((payload.get("venue_map") or {}).get("nodes") if isinstance(payload.get("venue_map"), dict) else [])), "critical", "venue_map.nodes must be populated.", "venue_map.nodes")
    add("landmark_services_present", bool((payload.get("landmarks") or {}).get("restrooms")) and bool((payload.get("landmarks") or {}).get("first_aid")) if isinstance(payload.get("landmarks"), dict) else False, "critical", "landmarks must include restrooms and first_aid.", "landmarks")
    add("english_copy_present", bool((payload.get("copy_variants") or {}).get("en")) if isinstance(payload.get("copy_variants"), dict) else False, "critical", "copy_variants.en is required.", "copy_variants.en")

    required_item_fields = {
        "attractions": ("id", "name", "zone_id", "category", "thrill_level", "accessibility_note", "source_ids"),
        "food": ("id", "name", "zone_id", "cuisine", "dietary_tags", "source_ids"),
    }
    for collection, fields in required_item_fields.items():
        for index, item in enumerate(_as_list(payload.get(collection))[:20]):
            if not isinstance(item, dict):
                add(f"{collection}_{index}_object", False, "critical", f"{collection}[{index}] must be an object.", collection)
                continue
            missing = [field for field in fields if not item.get(field)]
            add(f"{collection}_{index}_required_fields", not missing, "critical", f"{collection}[{index}] missing fields: {', '.join(missing)}.", collection)

    leak_hits = _customer_public_leak_hits(
        {
            "rides": payload.get("attractions"),
            "food": payload.get("food"),
            "venue_map": payload.get("venue_map"),
            "landmarks": payload.get("landmarks"),
            "shows": payload.get("shows"),
            "family_services": payload.get("family_services"),
            "copy_variants": payload.get("copy_variants"),
        }
    )
    add("public_payload_leak_scan", not leak_hits, "critical", f"Venue export leak terms: {', '.join(leak_hits[:6])}" if leak_hits else "No leak terms found.", "guest_visible_payload")

    critical_count = sum(1 for issue in issues if issue.get("severity") == "critical")
    high_count = sum(1 for issue in issues if issue.get("severity") == "high")
    return {
        "status": "production_ready" if not issues else "blocked",
        "score": max(0, 100 - critical_count * 18 - high_count * 8),
        "critical_count": critical_count,
        "high_count": high_count,
        "check_count": len(checks),
        "passed_count": len([check for check in checks if check.get("passed")]),
        "issues": issues[:60],
        "checks": checks,
        "next_actions": _customer_quality_next_actions(issues),
    }


def build_customer_public_data_feed(dynamic_details: dict[str, Any]) -> dict[str, Any]:
    return enrich_customer_park_details(dynamic_details)


def enrich_customer_park_details(details: dict[str, Any]) -> dict[str, Any]:
    enriched = deepcopy(details) if isinstance(details, dict) else {}
    knowledge = customer_park_knowledge()
    source_catalog = knowledge["source_catalog"] if isinstance(knowledge.get("source_catalog"), dict) else {}

    venue_nodes = _as_list((knowledge.get("venue_map") or {}).get("nodes") if isinstance(knowledge.get("venue_map"), dict) else [])
    enriched["rides"] = [_merge_public_item(_merge_location(row, venue_nodes), knowledge["attractions"]) for row in _as_list(enriched.get("rides"))]
    picks = enriched.get("recommended_public_options") if isinstance(enriched.get("recommended_public_options"), dict) else {}
    if picks:
        if isinstance(picks.get("best_ride"), dict):
            picks["best_ride"] = _merge_public_item(_merge_location(picks["best_ride"], venue_nodes), knowledge["attractions"])
        if isinstance(picks.get("best_food"), dict):
            picks["best_food"] = _merge_public_item(_merge_menu(_merge_location(picks["best_food"], venue_nodes), knowledge["menus"]), knowledge["food"])

    enriched["food"] = [_merge_public_item(_merge_menu(_merge_location(row, venue_nodes), knowledge["menus"]), knowledge["food"]) for row in _as_list(enriched.get("food"))]
    enriched["landmarks"] = knowledge["landmarks"]
    enriched["shows"] = knowledge["shows"]
    enriched["family_services"] = knowledge["family_services"]
    enriched["venue_reference"] = knowledge["venue_map"]
    enriched["copy_variants"] = knowledge["copy_variants"]
    enriched["knowledge_version"] = knowledge["version"]
    enriched["data_readiness"] = _customer_data_readiness(source_catalog)
    enriched["source_catalog"] = _customer_public_source_catalog(source_catalog)
    enriched["field_provenance"] = _customer_field_provenance(source_catalog)
    enriched["data_quality"] = _customer_data_quality_report(enriched)
    enriched["feed_contract"] = _customer_feed_contract(enriched, knowledge)
    boundaries = _as_list(enriched.get("customer_boundaries"))
    enriched["customer_boundaries"] = boundaries + [item for item in knowledge["boundaries"] if item not in boundaries]
    return enriched


def _merge_public_item(item: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    row = deepcopy(item) if isinstance(item, dict) else {}
    match = _find_record(row, records)
    if not match:
        return row
    public = {key: value for key, value in match.items() if key != "aliases"}
    public.update(row)
    if "guest_tips" in match:
        public["guest_tips"] = match["guest_tips"][:3]
    return public


def _customer_data_readiness(catalog: dict[str, Any]) -> dict[str, Any]:
    sources = catalog.get("sources", {}) if isinstance(catalog.get("sources"), dict) else {}
    review_queue = _as_list(catalog.get("review_queue"))
    real_connected = bool(catalog.get("real_venue_feed_connected"))
    seed_sources = [source_id for source_id, source in sources.items() if isinstance(source, dict) and source.get("source_type") == "seed_catalog"]
    needs_review = [
        source_id
        for source_id, source in sources.items()
        if isinstance(source, dict) and str(source.get("review_status") or "").startswith("needs_")
    ]
    return {
        "status": "venue_verified" if real_connected and not needs_review else "seeded_needs_review",
        "real_venue_feed_connected": real_connected,
        "source_count": len(sources),
        "seed_source_count": len(seed_sources),
        "needs_review_count": len(needs_review) + len(review_queue),
        "missing_for_production": [
            item.get("id")
            for item in review_queue
            if isinstance(item, dict) and item.get("severity") in {"high", "critical"}
        ],
        "publishable_for_demo": True,
        "publishable_for_production": real_connected and not needs_review and not review_queue,
    }


def _customer_public_source_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    sources = catalog.get("sources", {}) if isinstance(catalog.get("sources"), dict) else {}
    return {
        "version": catalog.get("version"),
        "catalog_status": catalog.get("catalog_status"),
        "real_venue_feed_connected": bool(catalog.get("real_venue_feed_connected")),
        "loaded_from": catalog.get("loaded_from"),
        "sources": {
            source_id: {
                "label": source.get("label"),
                "source_type": source.get("source_type"),
                "confidence": source.get("confidence"),
                "review_status": source.get("review_status"),
                "last_verified_at": source.get("last_verified_at"),
                "max_age_seconds": source.get("max_age_seconds"),
            }
            for source_id, source in sources.items()
            if isinstance(source, dict)
        },
        "review_queue": _as_list(catalog.get("review_queue")),
        "publish_gates": _as_list(catalog.get("publish_gates")),
    }


def _customer_field_provenance(catalog: dict[str, Any]) -> dict[str, Any]:
    sources = catalog.get("sources", {}) if isinstance(catalog.get("sources"), dict) else {}
    field_sources = catalog.get("field_sources", {}) if isinstance(catalog.get("field_sources"), dict) else {}
    provenance: dict[str, Any] = {}
    for field, source_ids in field_sources.items():
        ids = [str(source_id) for source_id in _as_list(source_ids)]
        source_rows = [sources.get(source_id, {}) for source_id in ids if isinstance(sources.get(source_id), dict)]
        confidences = [float(source.get("confidence")) for source in source_rows if isinstance(source.get("confidence"), (int, float))]
        ages = [int(source.get("max_age_seconds")) for source in source_rows if isinstance(source.get("max_age_seconds"), int)]
        review_statuses = sorted({str(source.get("review_status") or "unknown") for source in source_rows})
        provenance[str(field)] = {
            "source_ids": ids,
            "confidence": round(min(confidences), 2) if confidences else None,
            "freshness_policy_seconds": min(ages) if ages else None,
            "review_statuses": review_statuses,
            "needs_real_venue_review": any(status.startswith("needs_") for status in review_statuses),
        }
    return provenance


def _customer_data_quality_report(details: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []

    def add_check(check_id: str, passed: bool, severity: str, detail: str, field: str | None = None) -> None:
        row = {"id": check_id, "passed": passed, "severity": severity, "detail": detail}
        if field:
            row["field"] = field
        checks.append(row)
        if not passed:
            issues.append({"id": check_id, "severity": severity, "field": field, "detail": detail})

    required_collections = {
        "rides": details.get("rides"),
        "zones": details.get("zones"),
        "routes": details.get("routes"),
        "food": details.get("food"),
        "venue_map.landmarks": (details.get("venue_map") or {}).get("landmarks") if isinstance(details.get("venue_map"), dict) else None,
        "venue_map.facilities": (details.get("venue_map") or {}).get("facilities") if isinstance(details.get("venue_map"), dict) else None,
        "landmarks.restrooms": (details.get("landmarks") or {}).get("restrooms") if isinstance(details.get("landmarks"), dict) else None,
        "landmarks.first_aid": (details.get("landmarks") or {}).get("first_aid") if isinstance(details.get("landmarks"), dict) else None,
        "copy_variants.en": (details.get("copy_variants") or {}).get("en") if isinstance(details.get("copy_variants"), dict) else None,
    }
    for field, value in required_collections.items():
        has_value = bool(value) if isinstance(value, (list, dict)) else value not in {None, ""}
        add_check(f"required_{_quality_id(field)}", has_value, "critical", f"{field} must be populated for customer production.", field)

    next_event = (details.get("event_schedule") or {}).get("next_event") if isinstance(details.get("event_schedule"), dict) else {}
    add_check("required_next_event_or_schedule", isinstance(next_event, dict), "medium", "Event schedule must be present, even when no event is active.", "event_schedule")

    provenance = details.get("field_provenance", {}) if isinstance(details.get("field_provenance"), dict) else {}
    for field in ("rides", "food", "venue_map", "event_schedule", "landmarks", "shows", "family_services", "copy_variants"):
        field_row = provenance.get(field, {}) if isinstance(provenance.get(field), dict) else {}
        has_sources = bool(field_row.get("source_ids"))
        confidence = field_row.get("confidence")
        add_check(f"source_coverage_{field}", has_sources, "critical", f"{field} must declare source ids.", field)
        add_check(
            f"confidence_{field}",
            isinstance(confidence, (int, float)) and float(confidence) >= 0.74,
            "high",
            f"{field} confidence should be >= 0.74 for production.",
            field,
        )
        if field in {"rides", "food", "venue_map", "event_schedule"}:
            add_check(
                f"freshness_policy_{field}",
                field_row.get("freshness_policy_seconds") is not None,
                "high",
                f"{field} must define a freshness policy.",
                field,
            )

    readiness = details.get("data_readiness", {}) if isinstance(details.get("data_readiness"), dict) else {}
    add_check(
        "real_venue_feed_connected",
        bool(readiness.get("real_venue_feed_connected")),
        "critical",
        "Real venue-owned source feed must be connected before production.",
        "data_readiness",
    )
    add_check(
        "no_seed_sources_for_production",
        int(readiness.get("seed_source_count") or 0) == 0,
        "critical",
        "Seed source data must be replaced or explicitly venue-approved before production.",
        "data_readiness",
    )
    add_check(
        "review_queue_empty",
        int(readiness.get("needs_review_count") or 0) == 0,
        "critical",
        "Venue/content review queue must be empty before production.",
        "source_catalog.review_queue",
    )

    leak_hits = _customer_public_leak_hits(details)
    add_check("public_payload_leak_scan", not leak_hits, "critical", f"Guest-visible payload leak terms: {', '.join(leak_hits[:6])}" if leak_hits else "No leak terms found.", "guest_visible_payload")

    critical_count = sum(1 for issue in issues if issue.get("severity") == "critical")
    high_count = sum(1 for issue in issues if issue.get("severity") == "high")
    medium_count = sum(1 for issue in issues if issue.get("severity") == "medium")
    score = max(0, 100 - critical_count * 18 - high_count * 8 - medium_count * 3)
    return {
        "status": "production_ready" if not issues else "blocked_for_production",
        "score": score,
        "critical_count": critical_count,
        "high_count": high_count,
        "medium_count": medium_count,
        "check_count": len(checks),
        "passed_count": len([check for check in checks if check.get("passed")]),
        "issues": issues[:40],
        "checks": checks,
        "next_actions": _customer_quality_next_actions(issues),
    }


def _customer_feed_contract(details: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
    venue_export = knowledge.get("venue_export") if isinstance(knowledge.get("venue_export"), dict) else {}
    source_catalog = details.get("source_catalog") if isinstance(details.get("source_catalog"), dict) else {}
    quality = details.get("data_quality") if isinstance(details.get("data_quality"), dict) else {}
    readiness = details.get("data_readiness") if isinstance(details.get("data_readiness"), dict) else {}
    return {
        "mode": "consolidated_customer_public_data_feed",
        "status": "production_ready" if quality.get("status") == "production_ready" else "demo_or_blocked",
        "customer_safe": not any(issue.get("id") == "public_payload_leak_scan" for issue in _as_list(quality.get("issues")) if isinstance(issue, dict)),
        "production_publishable": bool(readiness.get("publishable_for_production")) and quality.get("status") == "production_ready",
        "venue_feed": {
            "connected": bool(venue_export.get("connected")),
            "version": venue_export.get("version"),
            "loaded_from": venue_export.get("loaded_from"),
            "validation_status": (venue_export.get("validation") or {}).get("status") if isinstance(venue_export.get("validation"), dict) else None,
        },
        "dynamic_layers": {
            "rides": _feed_layer("guestFlow.rides", details.get("rides"), "id/name", "live wait/status"),
            "zones": _feed_layer("guestFlow.zones", details.get("zones"), "id", "live crowd density"),
            "routes": _feed_layer("guestFlow.paths", details.get("routes"), "from/to", "live walk time/congestion"),
            "food": _feed_layer("foodInventory.locations", details.get("food"), "id/name", "live pickup ETA/backlog"),
            "venue_map": _feed_layer("physicalMap", (details.get("venue_map") or {}).get("landmarks") if isinstance(details.get("venue_map"), dict) else [], "id", "guest-visible map and facilities"),
            "event_schedule": _feed_layer("operatingClock.eventSchedule", (details.get("event_schedule") or {}).get("upcoming") if isinstance(details.get("event_schedule"), dict) else [], "id", "live event timing"),
            "weather": _feed_layer("weather", details.get("weather") if isinstance(details.get("weather"), dict) else {}, "park", "live weather context"),
        },
        "venue_layers": {
            "attractions": _feed_layer("venue_export.attractions|demo_seed.attractions", knowledge.get("attractions"), "id/aliases/name", "official attraction rules and notes"),
            "food_catalog": _feed_layer("venue_export.food|demo_seed.food", knowledge.get("food"), "id/aliases/name", "official dining metadata"),
            "menus": _feed_layer("venue_export.menus|demo_seed.menus", knowledge.get("menus"), "food location id", "menu highlights and dietary tags"),
            "landmarks": _feed_layer("venue_export.landmarks|demo_seed.landmarks", knowledge.get("landmarks"), "id/zone_id", "restrooms, first aid, services"),
            "copy_variants": _feed_layer("venue_export.copy_variants|demo_seed.copy_variants", knowledge.get("copy_variants"), "language code", "approved guest copy"),
        },
        "join_keys": ["id", "name", "aliases", "zone_id", "from/to"],
        "consolidated_sections": [
            "park",
            "station",
            "weather",
            "rides",
            "zones",
            "routes",
            "food",
            "venue_map",
            "event_schedule",
            "accessibility",
            "guest_care",
            "recommended_public_options",
            "landmarks",
            "shows",
            "family_services",
            "copy_variants",
            "source_catalog",
            "field_provenance",
            "data_readiness",
            "data_quality",
        ],
        "source_catalog_version": source_catalog.get("version"),
        "boundary": "Dynamic park state and venue facts are joined into one customer-safe read-only feed. The feed never dispatches actions or exposes internal operations data.",
    }


def _feed_layer(source: str, value: Any, join_key: str, role: str) -> dict[str, Any]:
    if isinstance(value, list):
        count = len(value)
    elif isinstance(value, dict):
        count = len(value)
    elif value:
        count = 1
    else:
        count = 0
    return {"source": source, "row_count": count, "join_key": join_key, "role": role}


def _customer_public_leak_hits(details: dict[str, Any]) -> list[str]:
    scan = {
        "rides": details.get("rides"),
        "zones": details.get("zones"),
        "routes": details.get("routes"),
        "food": details.get("food"),
        "venue_map": details.get("venue_map"),
        "event_schedule": details.get("event_schedule"),
        "accessibility": details.get("accessibility"),
        "guest_care": details.get("guest_care"),
        "recommended_public_options": details.get("recommended_public_options"),
        "public_alerts": details.get("public_alerts"),
        "landmarks": details.get("landmarks"),
        "shows": details.get("shows"),
        "family_services": details.get("family_services"),
        "copy_variants": details.get("copy_variants"),
    }
    text = json.dumps(_drop_quality_metadata(scan), sort_keys=True, default=str).lower()
    blocked_terms = {
        "serviceyard": "serviceYard",
        "maintenance yard": "Maintenance Yard",
        "backstage": "backstage",
        "back_of_house": "back_of_house",
        "maintenance_only": "maintenance_only",
        "controlactions": "controlActions",
        "staffing": "staffing",
        "policydoctrine": "policyDoctrine",
        "private_guest": "private_guest",
    }
    return [label for term, label in blocked_terms.items() if term in text]


def _customer_quality_next_actions(issues: list[dict[str, Any]]) -> list[str]:
    ids = {str(issue.get("id") or "") for issue in issues}
    actions = []
    if "real_venue_feed_connected" in ids:
        actions.append("Connect venue-owned attraction, menu, map, service, and schedule feeds.")
    if "no_seed_sources_for_production" in ids:
        actions.append("Replace demo seed facts or mark each seed record as venue-approved with verified source metadata.")
    if "review_queue_empty" in ids:
        actions.append("Clear venue/content review queue for attraction rules, menus/allergens, map nodes, and translations.")
    if any(item.startswith("confidence_") for item in ids):
        actions.append("Raise low-confidence fields with stronger source authority or human approval.")
    if any(item.startswith("freshness_policy_") for item in ids):
        actions.append("Define freshness windows for every live customer-facing field.")
    if "public_payload_leak_scan" in ids:
        actions.append("Remove internal/backstage terms from guest-visible payload sections.")
    return actions[:8]


def _drop_quality_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _drop_quality_metadata(item)
            for key, item in value.items()
            if str(key) not in {"boundary", "source", "source_catalog", "field_provenance", "data_quality", "data_readiness"}
        }
    if isinstance(value, list):
        return [_drop_quality_metadata(item) for item in value]
    return value


def _quality_id(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value.lower()).strip("_")


def _merge_location(item: dict[str, Any], nodes: list[dict[str, Any]]) -> dict[str, Any]:
    row = deepcopy(item) if isinstance(item, dict) else {}
    match = _find_record(row, nodes)
    if not match:
        return row
    row["map_position"] = {key: match.get(key) for key in ("x", "y", "width", "height") if key in match}
    row.setdefault("zone_id", match.get("zone_id"))
    return row


def _merge_menu(item: dict[str, Any], menus: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    row = deepcopy(item) if isinstance(item, dict) else {}
    menu_id = _menu_id_for_item(row)
    if menu_id and menu_id in menus:
        row["menu_highlights"] = deepcopy(menus[menu_id][:5])
    return row


def _menu_id_for_item(item: dict[str, Any]) -> str | None:
    key = _normalize(item.get("id"))
    name = _normalize(item.get("name"))
    if key in {"foodcourta", "foodcourt1", "pizza"} or name in {"foodcourta", "foodcourt1", "pizzapier"}:
        return "foodCourtA"
    if key in {"foodcourtb", "foodcourt2", "snack"} or name in {"foodcourtb", "foodcourt2", "mainstreetsnacks"}:
        return "foodCourtB"
    return None


def _find_record(item: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any] | None:
    keys = {_normalize(item.get("id")), _normalize(item.get("name"))}
    for record in records:
        aliases = {_normalize(alias) for alias in record.get("aliases", []) if alias}
        candidates = {_normalize(record.get("id")), _normalize(record.get("name")), *aliases}
        if keys & candidates:
            return record
    return None


def _normalize(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
