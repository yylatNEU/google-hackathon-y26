from __future__ import annotations

from copy import deepcopy
from typing import Any

from venue_experience_data import (
    activate_synthetic_venue_export,
    approved_synthetic_venue_export,
    build_venue_experience_data,
    build_venue_experience_data_from_export,
    import_venue_experience_export,
    validate_venue_experience_export,
)


def _with_global_profile(profile: dict[str, Any]) -> dict[str, Any]:
    profile = deepcopy(profile)
    profile["mode"] = "venue_profile"
    profile["globalProfile"] = {
        "scope": "tenant_venue",
        "tenantId": "default",
        "venueId": (profile.get("venueIdentity") or {}).get("venueId"),
        "profileType": (profile.get("venueIdentity") or {}).get("profileType"),
        "consumers": [
            "experience_studio",
            "accessibility_journey",
            "guest_recommendations",
            "signage_copy",
            "vip_tours",
            "command_center_review",
        ],
        "ownership": "Venue Profile layer owns source integrity; consumers use allowed public fields only.",
    }
    return profile


def build_venue_profile() -> dict[str, Any]:
    return _with_global_profile(build_venue_experience_data())


def approved_synthetic_venue_profile_export() -> dict[str, Any]:
    export = approved_synthetic_venue_export()
    return {
        "status": "ready",
        "mode": "venue_profile_synthetic_export",
        "sourceName": "parkpulse_synthetic_venue_export.approved.json",
        "export": export,
        "validation": validate_venue_profile_export({**export, "loaded_from": "parkpulse_synthetic_venue_export.approved.json"}),
        "message": "Approved synthetic venue export loaded for preview only. It has not been activated.",
    }


def _stable(value: Any) -> str:
    return str(value or "").strip().lower()


def _indexed_by_name(rows: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for name, value in (rows or {}).items():
        if isinstance(value, dict):
            clean_name = str(value.get("name") or name or "").strip()
            if clean_name:
                indexed[clean_name] = value
    return indexed


def _changed_fields(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    fields: list[str] = []
    for key in sorted(set(before) | set(after)):
        if key == "sourceIds":
            continue
        if before.get(key) != after.get(key):
            fields.append(key)
    return fields


def _set_diff(before: list[str], after: list[str]) -> dict[str, list[str]]:
    before_set = {_stable(item): item for item in before if _stable(item)}
    after_set = {_stable(item): item for item in after if _stable(item)}
    return {
        "added": [after_set[key] for key in sorted(set(after_set) - set(before_set))],
        "removed": [before_set[key] for key in sorted(set(before_set) - set(after_set))],
    }


def _zone_key(zone: dict[str, Any]) -> str:
    return _stable(zone.get("id") or zone.get("name"))


def _profile_diff(current: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    current_inputs = current.get("realInputs") or {}
    candidate_inputs = candidate.get("realInputs") or {}
    current_identity = current.get("venueIdentity") or {}
    candidate_identity = candidate.get("venueIdentity") or {}

    current_locations = _indexed_by_name(current_inputs.get("locationDetails"))
    candidate_locations = _indexed_by_name(candidate_inputs.get("locationDetails"))
    current_location_keys = {_stable(name): name for name in current_locations}
    candidate_location_keys = {_stable(name): name for name in candidate_locations}
    added_location_keys = sorted(set(candidate_location_keys) - set(current_location_keys))
    removed_location_keys = sorted(set(current_location_keys) - set(candidate_location_keys))
    common_location_keys = sorted(set(current_location_keys) & set(candidate_location_keys))
    changed_locations = []
    for key in common_location_keys:
        before_name = current_location_keys[key]
        after_name = candidate_location_keys[key]
        fields = _changed_fields(current_locations[before_name], candidate_locations[after_name])
        if fields:
            changed_locations.append({"name": after_name, "fields": fields})

    current_owners = current_inputs.get("channelOwners") or {}
    candidate_owners = candidate_inputs.get("channelOwners") or {}
    owner_channels = sorted(set(current_owners) | set(candidate_owners))
    owner_changes = [
        {"channel": channel, "before": current_owners.get(channel), "after": candidate_owners.get(channel)}
        for channel in owner_channels
        if current_owners.get(channel) != candidate_owners.get(channel)
    ]

    current_zones = {_zone_key(zone): zone for zone in current_identity.get("publicZones") or [] if isinstance(zone, dict) and _zone_key(zone)}
    candidate_zones = {_zone_key(zone): zone for zone in candidate_identity.get("publicZones") or [] if isinstance(zone, dict) and _zone_key(zone)}
    changed_zones = []
    for key in sorted(set(current_zones) & set(candidate_zones)):
        fields = _changed_fields(current_zones[key], candidate_zones[key])
        if fields:
            changed_zones.append({"name": candidate_zones[key].get("name") or candidate_zones[key].get("id"), "fields": fields})

    identity_changes = [
        {"field": field, "before": current_identity.get(field), "after": candidate_identity.get(field)}
        for field in ("venueId", "name", "profileType", "description", "primaryAudiences")
        if current_identity.get(field) != candidate_identity.get(field)
    ]

    safety_diff = _set_diff(current_inputs.get("safetyInstructions") or [], candidate_inputs.get("safetyInstructions") or [])
    counts_before = current.get("readiness", {}).get("counts") or {}
    counts_after = candidate.get("readiness", {}).get("counts") or {}
    count_delta = {
        key: int(counts_after.get(key, 0) or 0) - int(counts_before.get(key, 0) or 0)
        for key in sorted(set(counts_before) | set(counts_after))
    }

    added_locations = [candidate_location_keys[key] for key in added_location_keys]
    removed_locations = [current_location_keys[key] for key in removed_location_keys]
    added_zones = [candidate_zones[key] for key in sorted(set(candidate_zones) - set(current_zones))]
    removed_zones = [current_zones[key] for key in sorted(set(current_zones) - set(candidate_zones))]
    total_changes = (
        len(added_locations)
        + len(removed_locations)
        + len(changed_locations)
        + len(safety_diff["added"])
        + len(safety_diff["removed"])
        + len(owner_changes)
        + len(added_zones)
        + len(removed_zones)
        + len(changed_zones)
        + len(identity_changes)
    )
    return {
        "summary": {
            "totalChanges": total_changes,
            "addedLocations": len(added_locations),
            "removedLocations": len(removed_locations),
            "changedLocations": len(changed_locations),
            "safetyAdded": len(safety_diff["added"]),
            "safetyRemoved": len(safety_diff["removed"]),
            "ownerChanges": len(owner_changes),
            "zoneChanges": len(added_zones) + len(removed_zones) + len(changed_zones),
            "identityChanges": len(identity_changes),
            "replacementRisk": "high" if removed_locations or safety_diff["removed"] or identity_changes else ("medium" if changed_locations or owner_changes else "low"),
        },
        "countsBefore": counts_before,
        "countsAfter": counts_after,
        "countDelta": count_delta,
        "locations": {
            "added": added_locations,
            "removed": removed_locations,
            "changed": changed_locations,
        },
        "safetyInstructions": safety_diff,
        "channelOwners": {"changed": owner_changes},
        "publicZones": {
            "added": added_zones,
            "removed": removed_zones,
            "changed": changed_zones,
        },
        "identity": {"changed": identity_changes},
    }


def validate_venue_profile_export(export: dict[str, Any] | None = None) -> dict[str, Any]:
    return validate_venue_experience_export(export)


def preview_venue_profile_import(payload: dict[str, Any]) -> dict[str, Any]:
    export = payload.get("export") if isinstance(payload.get("export"), dict) else {}
    source_name = str(payload.get("sourceName") or payload.get("source_name") or "").strip()
    if not export:
        return {
            "status": "blocked",
            "mode": "venue_profile_import_preview",
            "message": "Preview requires an export JSON object.",
            "validation": validate_venue_profile_export({}),
            "canActivate": False,
        }
    candidate_export = deepcopy(export)
    if source_name:
        candidate_export["loaded_from"] = source_name
    validation = validate_venue_profile_export(candidate_export)
    current_profile = build_venue_profile()
    candidate_profile = _with_global_profile(build_venue_experience_data_from_export(candidate_export, loaded_from=source_name or None))
    diff = _profile_diff(current_profile, candidate_profile)
    can_activate = validation.get("status") == "studio_ready"
    return {
        "status": "ready" if can_activate else "blocked",
        "mode": "venue_profile_import_preview",
        "message": "Profile import preview ready." if can_activate else "Profile import preview found blocking validation issues.",
        "sourceName": source_name,
        "validation": validation,
        "canActivate": can_activate,
        "diff": diff,
        "candidate": {
            "venueIdentity": candidate_profile.get("venueIdentity"),
            "readiness": candidate_profile.get("readiness"),
            "sourceIntegrity": candidate_profile.get("sourceIntegrity"),
        },
        "current": {
            "venueIdentity": current_profile.get("venueIdentity"),
            "readiness": current_profile.get("readiness"),
            "sourceIntegrity": current_profile.get("sourceIntegrity"),
        },
    }


def import_venue_profile_export(payload: dict[str, Any]) -> dict[str, Any]:
    result = import_venue_experience_export(payload)
    if result.get("venueExperienceData"):
        result["venueProfile"] = build_venue_profile()
    result["mode"] = "venue_profile_import"
    return result


def activate_synthetic_venue_profile(actor: str = "venue_profile") -> dict[str, Any]:
    result = activate_synthetic_venue_export(actor=actor)
    if result.get("venueExperienceData"):
        result["venueProfile"] = build_venue_profile()
    result["mode"] = "venue_profile_synthetic_activation"
    return result
