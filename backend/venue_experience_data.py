from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from typing import Any

from customer_park_knowledge import customer_venue_export, validate_customer_venue_export


REQUIRED_CHANNEL_OWNERS = ("guest_app", "signage", "email", "staff_cue")


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
    return {
        "status": "studio_ready" if studio_ready else "blocked",
        "customerValidation": customer_validation,
        "experienceIssueCount": len(experience_issues),
        "criticalCount": critical_count,
        "highCount": high_count,
        "issues": experience_issues,
        "autofillAllowed": bool(payload) and customer_ready and not _is_sample_export(payload),
        "handoffReady": studio_ready,
        "loadedFrom": payload.get("loaded_from") if isinstance(payload, dict) else None,
    }


def build_venue_experience_data_from_export(export: dict[str, Any] | None, loaded_from: str | None = None) -> dict[str, Any]:
    validation = validate_venue_experience_export(export if export else {})
    profile_type = (_venue_identity(export).get("profileType") if export else "not_connected")
    is_approved_synthetic = profile_type == "synthetic_approved"
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
        "locationDetails": _location_details(export) if validation.get("autofillAllowed") else {},
    }
    counts = {
        "locations": len(real_inputs["locations"]),
        "indoorLocations": len(real_inputs["indoorLocations"]),
        "accessibleRoutes": len(real_inputs["accessibleRoutes"]),
        "safetyInstructions": len(real_inputs["safetyInstructions"]),
        "channelOwners": len(real_inputs["channelOwners"]),
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
        },
        "realInputs": real_inputs,
        "sourceIntegrity": {
            "usesSeedData": False,
            "usesSampleData": _is_sample_export(export),
            "usesApprovedSyntheticProfile": is_approved_synthetic,
            "realVenueFeedConnected": bool(export) and not is_approved_synthetic,
            "profileType": profile_type,
            "customerValidationStatus": validation["customerValidation"].get("status"),
        },
        "validation": validation,
        "contract": {
            "requiredFields": ["verified public locations", "indoor or sheltered locations", "accessibility map facts", "safety instructions", "channel owners"],
            "blockedSources": ["seed_catalog", "sample venue exports", "simulated park state"],
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
    for key in ("locations", "indoorLocations", "quietLocations", "attractionLocations", "accessibleRoutes", "safetyInstructions"):
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
