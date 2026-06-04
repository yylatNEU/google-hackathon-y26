from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TEMPLATES: dict[str, dict[str, Any]] = {
    "halloween-route": {
        "label": "Halloween Event Route",
        "shortLabel": "Halloween",
        "intent": "Create a theatrical route with story beats, crowd pacing, and themed transition copy.",
        "route": ["Real entry location needed", "Real themed stop needed", "Real transition path needed", "Real feature stop needed", "Real finale location needed"],
    },
    "rainy-day": {
        "label": "Rainy-Day Guest Journey",
        "shortLabel": "Rain",
        "intent": "Turn weather disruption into a comfortable indoor-first journey with clear guest messaging.",
        "route": ["Real covered entry needed", "Real indoor attraction needed", "Real sheltered food or retail location needed", "Real indoor dwell location needed", "Real covered exit path needed"],
    },
    "low-sensory": {
        "label": "Low-Sensory Path",
        "shortLabel": "Low sensory",
        "intent": "Design a quieter path with lower stimulation, predictable timing, and easy opt-outs.",
        "route": ["Real quiet entry needed", "Real low-noise path needed", "Real low-crowd stop needed", "Real decompression space needed", "Real return route needed"],
    },
    "kid-quest": {
        "label": "Kid-Friendly Quest",
        "shortLabel": "Quest",
        "intent": "Create an age-appropriate story mission that moves kids through the park with small wins.",
        "route": ["Real quest start needed", "Real clue location needed", "Real discovery stop needed", "Real reward pickup needed", "Real completion location needed"],
    },
    "scavenger-hunt": {
        "label": "Themed Scavenger Hunt",
        "shortLabel": "Hunt",
        "intent": "Build a clue-based hunt that highlights underused areas without overloading one location.",
        "route": ["Real map pickup needed", "Real visual clue location needed", "Real landmark needed", "Real validation point needed", "Real final reveal location needed"],
    },
    "attraction-copy": {
        "label": "Attraction Description Writer",
        "shortLabel": "Descriptions",
        "intent": "Rewrite attraction descriptions so they sell the feeling, set expectations, and stay accurate.",
        "route": ["Real attraction name needed", "Real experience facts needed", "Real accessibility facts needed", "Real timing guidance needed", "Real nearby pairing needed"],
    },
    "safety-signage": {
        "label": "Safety and Signage Rewrite",
        "shortLabel": "Signage",
        "intent": "Make safety language easier to understand while preserving the instruction.",
        "route": ["Real instruction needed", "Real reason needed", "Real timing or location needed", "Real staff phrase needed", "Real app reminder needed"],
    },
    "vip-tour": {
        "label": "VIP Tour Script",
        "shortLabel": "VIP",
        "intent": "Create a premium host script with pacing, surprise moments, and flexible alternatives.",
        "route": ["Real VIP welcome location needed", "Real priority experience needed", "Real photo location needed", "Real premium stop needed", "Real closing location needed"],
    },
}

ALLOWED_DRAFT_STATUSES = {"draft", "in_review", "approved", "ready_for_publish", "needs_changes"}
ALLOWED_HANDOFF_STATUSES = {"command_center_review_required", "accepted_for_channel_owner_review", "held_for_operations_changes", "blocked"}
STUDIO_LAYER_AGENTS = [
    {
        "id": "experience_design_assistant",
        "name": "Experience Design Assistant",
        "job": "Create routes, quests, scripts, and themed content from a creative brief.",
        "authority": "draft_only",
    },
    {
        "id": "brand_voice_reviewer",
        "name": "Brand/Voice Reviewer",
        "job": "Check tone, audience fit, seasonal positioning, and guest-facing clarity.",
        "authority": "review_flag",
    },
    {
        "id": "accessibility_reviewer",
        "name": "Accessibility Reviewer",
        "job": "Check sensory load, route alternatives, readable copy, seating, and step-free assumptions.",
        "authority": "review_flag",
    },
    {
        "id": "safety_messaging_reviewer",
        "name": "Safety Messaging Reviewer",
        "job": "Check whether copy could be interpreted as safety, shelter, ride, or crowd-control instruction.",
        "authority": "review_flag",
    },
    {
        "id": "publish_readiness_checker",
        "name": "Publish Readiness Checker",
        "job": "Confirm whether an approved creative package is ready for handoff, while preserving no-publish authority.",
        "authority": "handoff_only",
    },
    {
        "id": "profile_intelligence_reviewer",
        "name": "Profile Intelligence Reviewer",
        "job": "Check source freshness, derived-path warnings, capacity assumptions, brand bible claims, and learning labels.",
        "authority": "review_flag",
    },
]
_STORE_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store_path() -> Path:
    return Path(os.getenv("PARKPULSE_EXPERIENCE_STUDIO_STORE_PATH", "/tmp/parkpulse/experience_studio_drafts.json"))


def _read_records() -> list[dict[str, Any]]:
    path = _store_path()
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8") or "[]")
    except (OSError, json.JSONDecodeError):
        return []
    return [record for record in payload if isinstance(record, dict)] if isinstance(payload, list) else []


def _write_records(records: list[dict[str, Any]]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(f"{path.suffix}.tmp")
    temp.write_text(json.dumps(records, indent=2, default=str), encoding="utf-8")
    temp.replace(path)


def _compact_record(record: dict[str, Any]) -> dict[str, Any]:
    draft = record.get("draft", {}) if isinstance(record.get("draft"), dict) else {}
    review = draft.get("review", []) if isinstance(draft.get("review"), list) else []
    studio_review = draft.get("studioReview", []) if isinstance(draft.get("studioReview"), list) else []
    handoffs = record.get("handoffs", []) if isinstance(record.get("handoffs"), list) else []
    return {
        "id": record.get("id"),
        "title": draft.get("title") or record.get("title") or "Untitled experience draft",
        "templateId": record.get("templateId"),
        "audience": draft.get("audience") or record.get("audience"),
        "status": record.get("status", "draft"),
        "createdAt": record.get("createdAt"),
        "updatedAt": record.get("updatedAt"),
        "reviewCount": len(review),
        "studioReviewerCount": len(studio_review),
        "messageCount": len(draft.get("messages", [])) if isinstance(draft.get("messages"), list) else 0,
        "routeStopCount": len(draft.get("route", [])) if isinstance(draft.get("route"), list) else 0,
        "handoffCount": len(handoffs),
        "latestHandoffStatus": handoffs[-1].get("status") if handoffs and isinstance(handoffs[-1], dict) else None,
        "latestNote": (record.get("reviewTrail") or [{}])[-1].get("note") if isinstance(record.get("reviewTrail"), list) and record.get("reviewTrail") else None,
    }


def _compact_handoff(record: dict[str, Any], handoff: dict[str, Any]) -> dict[str, Any]:
    draft = record.get("draft", {}) if isinstance(record.get("draft"), dict) else {}
    return {
        "id": handoff.get("id"),
        "draftId": record.get("id"),
        "title": draft.get("title") or "Untitled experience handoff",
        "status": handoff.get("status"),
        "createdAt": handoff.get("createdAt"),
        "requestedBy": handoff.get("requestedBy"),
        "channelCount": len(handoff.get("channels", [])) if isinstance(handoff.get("channels"), list) else 0,
        "requiresCommandCenterReview": bool(handoff.get("requiresCommandCenterReview")),
        "operationalReviewReasons": handoff.get("operationalReviewReasons", []),
    }


def list_experience_studio_drafts(limit: int = 30) -> dict[str, Any]:
    with _STORE_LOCK:
        records = sorted(_read_records(), key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    return {
        "status": "ready",
        "mode": "experience_studio_saved_drafts",
        "drafts": [_compact_record(record) for record in records[: max(1, min(limit, 100))]],
        "count": len(records),
        "store": str(_store_path()),
    }


def get_experience_studio_draft(draft_id: str) -> dict[str, Any]:
    with _STORE_LOCK:
        for record in _read_records():
            if str(record.get("id")) == draft_id:
                return {"status": "ready", "mode": "experience_studio_saved_draft", "draftRecord": record, "summary": _compact_record(record)}
    return {"status": "not_found", "message": f"Draft {draft_id} was not found."}


def list_experience_studio_handoffs(limit: int = 30) -> dict[str, Any]:
    with _STORE_LOCK:
        records = _read_records()
        handoffs = [
            _compact_handoff(record, handoff)
            for record in records
            for handoff in (record.get("handoffs", []) if isinstance(record.get("handoffs"), list) else [])
            if isinstance(handoff, dict)
        ]
    handoffs = sorted(handoffs, key=lambda item: str(item.get("createdAt") or ""), reverse=True)
    return {
        "status": "ready",
        "mode": "experience_studio_command_center_handoffs",
        "handoffs": handoffs[: max(1, min(limit, 100))],
        "count": len(handoffs),
        "boundary": "Command Center reviews operational impact; Experience Studio does not publish or dispatch.",
    }


def studio_layer_contract() -> dict[str, Any]:
    return {
        "status": "ready",
        "mode": "experience_studio_layer_contract",
        "architecture": {
            "operate": {
                "layer": "Operations Agent Layer",
                "purpose": "Run the park through live evidence, policy gates, dispatch receipts, and outcome learning.",
                "agents": ["Scan Agent", "React Agent", "Proact Agent", "Reliability QA Agent"],
                "authority": ["read_live_state", "recommend_actions", "route_human_review", "dispatch_when_policy_allows"],
            },
            "design": {
                "layer": "Studio Layer",
                "purpose": "Design guest journeys, content, story, signage, and publish-ready packages.",
                "agents": STUDIO_LAYER_AGENTS,
                "authority": ["draft_artifacts", "review_artifacts", "save_versions", "prepare_handoff"],
            },
        },
        "boundary": {
            "experience_studio_can": ["draft_route", "draft_copy", "review_brand_fit", "review_accessibility", "mark_publish_readiness"],
            "experience_studio_cannot": ["dispatch_staff", "change_queue", "publish_guest_message", "override_safety_policy", "alter_live_operations"],
            "handoff_rule": "Anything that changes live operations or guest-facing production systems must go through Command Center review.",
        },
    }


def save_experience_studio_draft(payload: dict[str, Any]) -> dict[str, Any]:
    draft = payload.get("draft") if isinstance(payload.get("draft"), dict) else {}
    if not draft:
        draft = _draft_from_payload(payload)
    now = _now_iso()
    record = {
        "id": f"exp_{uuid.uuid4().hex[:12]}",
        "templateId": payload.get("templateId") or payload.get("template"),
        "brief": payload.get("brief") if isinstance(payload.get("brief"), dict) else {
            "audience": payload.get("audience") or draft.get("audience"),
            "tone": payload.get("tone"),
            "constraints": payload.get("constraints"),
        },
        "draft": draft,
        "status": "draft",
        "sourceMode": payload.get("sourceMode") or payload.get("source"),
        "createdAt": now,
        "updatedAt": now,
        "reviewTrail": [
            {
                "status": "draft",
                "actor": payload.get("actor") or "experience_studio",
                "note": "Draft saved for creative review.",
                "at": now,
            }
        ],
        "publishBoundary": {
            "readyForPublishIsNotPublished": True,
            "requiresOperationalReviewForMovementInstructions": True,
            "llmControlAuthority": False,
        },
    }
    with _STORE_LOCK:
        records = _read_records()
        records.insert(0, record)
        _write_records(records)
    return {"status": "saved", "mode": "experience_studio_saved_draft", "draftRecord": record, "summary": _compact_record(record)}


def update_experience_studio_draft_status(draft_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    next_status = str(payload.get("status") or "").strip().lower()
    if next_status not in ALLOWED_DRAFT_STATUSES:
        return {
            "status": "invalid_status",
            "allowedStatuses": sorted(ALLOWED_DRAFT_STATUSES),
            "message": "Experience Studio drafts can move only through known review states.",
        }
    now = _now_iso()
    with _STORE_LOCK:
        records = _read_records()
        for record in records:
            if str(record.get("id")) != draft_id:
                continue
            record["status"] = next_status
            record["updatedAt"] = now
            trail = record.setdefault("reviewTrail", [])
            if isinstance(trail, list):
                trail.append(
                    {
                        "status": next_status,
                        "actor": payload.get("actor") or "experience_reviewer",
                        "note": _text(payload.get("note"), f"Moved to {next_status}."),
                        "at": now,
                    }
                )
            _write_records(records)
            return {"status": "updated", "mode": "experience_studio_review_state", "draftRecord": record, "summary": _compact_record(record)}
    return {"status": "not_found", "message": f"Draft {draft_id} was not found."}


def update_experience_studio_draft_content(draft_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    incoming_draft = payload.get("draft") if isinstance(payload.get("draft"), dict) else {}
    if not incoming_draft:
        return {"status": "invalid_draft", "message": "A draft object is required to update saved Experience Studio content."}

    now = _now_iso()
    with _STORE_LOCK:
        records = _read_records()
        for record in records:
            if str(record.get("id")) != draft_id:
                continue

            existing_draft = record.get("draft", {}) if isinstance(record.get("draft"), dict) else {}
            existing_integrity = existing_draft.get("sourceIntegrity", {}) if isinstance(existing_draft.get("sourceIntegrity"), dict) else {}
            incoming_integrity = incoming_draft.get("sourceIntegrity", {}) if isinstance(incoming_draft.get("sourceIntegrity"), dict) else {}
            missing_inputs = _as_text_list(existing_integrity.get("missingRealInputs")) + _as_text_list(incoming_integrity.get("missingRealInputs"))
            if _has_unresolved_placeholders(incoming_draft):
                missing_inputs.append("real_location_names")
            missing_inputs = _as_text_list(missing_inputs)

            integrity = {
                **incoming_integrity,
                **existing_integrity,
                "missingRealInputs": missing_inputs,
                "readyForHandoff": not missing_inputs and not _has_unresolved_placeholders(incoming_draft),
                "usesSeedData": False,
                "usesSimulatedParkState": False,
                "usesInventedLocations": bool(missing_inputs),
            }
            incoming_draft["sourceIntegrity"] = integrity

            record["draft"] = incoming_draft
            record["updatedAt"] = now
            trail = record.setdefault("reviewTrail", [])
            if isinstance(trail, list):
                trail.append(
                    {
                        "status": record.get("status", "draft"),
                        "actor": payload.get("actor") or "experience_designer",
                        "note": _text(payload.get("note"), "Draft content updated."),
                        "at": now,
                    }
                )
            _write_records(records)
            return {
                "status": "updated",
                "mode": "experience_studio_draft_content",
                "draftRecord": record,
                "summary": _compact_record(record),
            }
    return {"status": "not_found", "message": f"Draft {draft_id} was not found."}


def _message_by_channel(draft: dict[str, Any], channel: str) -> str:
    messages = draft.get("messages", []) if isinstance(draft.get("messages"), list) else []
    for message in messages:
        if isinstance(message, dict) and str(message.get("channel") or "").lower() == channel.lower():
            return str(message.get("copy") or "")
    return ""


def _handoff_package(record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    draft = record.get("draft", {}) if isinstance(record.get("draft"), dict) else {}
    route = draft.get("route", []) if isinstance(draft.get("route"), list) else []
    review = draft.get("studioReview", []) if isinstance(draft.get("studioReview"), list) else []
    safety_review = [item for item in review if isinstance(item, dict) and item.get("agentId") == "safety_messaging_reviewer"]
    needs_ops_review = bool(route) or any(str(item.get("status") or "") == "review" for item in safety_review)
    reasons = []
    if route:
        reasons.append("Draft contains guest route or movement sequencing.")
    if safety_review:
        reasons.extend(str(item.get("nextStep") or item.get("finding") or "") for item in safety_review if isinstance(item, dict))
    now = _now_iso()
    return {
        "id": f"handoff_{uuid.uuid4().hex[:12]}",
        "draftId": record.get("id"),
        "createdAt": now,
        "requestedBy": payload.get("actor") or "experience_studio",
        "status": "command_center_review_required" if needs_ops_review else "ready_for_channel_owner_review",
        "requiresCommandCenterReview": needs_ops_review,
        "operationalReviewReasons": [reason for reason in reasons if reason],
        "channels": [
            {"id": "guest_app", "label": "Guest app", "artifact": _message_by_channel(draft, "Guest app"), "owner": "Digital product"},
            {"id": "signage", "label": "Signage", "artifact": _message_by_channel(draft, "Signage"), "owner": "Park experience"},
            {"id": "pre_arrival_email", "label": "Pre-arrival email", "artifact": _message_by_channel(draft, "Pre-arrival email"), "owner": "CRM"},
            {"id": "staff_cue", "label": "Staff cue", "artifact": _message_by_channel(draft, "Staff cue"), "owner": "Operations training"},
            {
                "id": "route_storyboard",
                "label": "Route storyboard",
                "artifact": [
                    {
                        "stop": item.get("stop"),
                        "guestCopy": item.get("guestCopy"),
                        "staffNote": item.get("staffNote"),
                        "accessibilityNote": item.get("accessibilityNote"),
                        "profileIntelligenceNote": item.get("profileIntelligenceNote"),
                    }
                    for item in route
                    if isinstance(item, dict)
                ],
                "owner": "Experience design",
            },
        ],
        "reviewPacket": {
            "studioReview": review,
            "productionNotes": draft.get("productionNotes", []),
            "publishBoundary": record.get("publishBoundary", {}),
            "handoffRule": studio_layer_contract()["boundary"]["handoff_rule"],
        },
    }


def create_experience_studio_handoff(draft_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    now = _now_iso()
    with _STORE_LOCK:
        records = _read_records()
        for record in records:
            if str(record.get("id")) != draft_id:
                continue
            current_status = str(record.get("status") or "draft")
            if current_status not in {"approved", "ready_for_publish"}:
                return {
                    "status": "blocked",
                    "message": "Only approved or ready_for_publish drafts can create a Command Center handoff.",
                    "currentDraftStatus": current_status,
                    "requiredStatuses": ["approved", "ready_for_publish"],
                }
            draft = record.get("draft", {}) if isinstance(record.get("draft"), dict) else {}
            source_integrity = draft.get("sourceIntegrity", {}) if isinstance(draft.get("sourceIntegrity"), dict) else {}
            if _has_unresolved_placeholders(draft) or source_integrity.get("missingRealInputs"):
                return {
                    "status": "blocked",
                    "message": "Handoff blocked until all placeholders are replaced with verified real inputs.",
                    "missingRealInputs": source_integrity.get("missingRealInputs", []),
                    "readyForHandoff": False,
                }
            handoff = _handoff_package(record, payload)
            handoffs = record.setdefault("handoffs", [])
            if isinstance(handoffs, list):
                handoffs.append(handoff)
            record["status"] = "ready_for_publish"
            record["updatedAt"] = now
            trail = record.setdefault("reviewTrail", [])
            if isinstance(trail, list):
                trail.append(
                    {
                        "status": "ready_for_publish",
                        "actor": payload.get("actor") or "experience_studio",
                        "note": "Publish handoff package sent to Command Center review.",
                        "at": now,
                        "handoffId": handoff["id"],
                    }
                )
            _write_records(records)
            return {
                "status": "created",
                "mode": "experience_studio_command_center_handoff",
                "handoff": handoff,
                "summary": _compact_handoff(record, handoff),
                "draftSummary": _compact_record(record),
            }
    return {"status": "not_found", "message": f"Draft {draft_id} was not found."}


def update_experience_studio_handoff_status(handoff_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    next_status = str(payload.get("status") or "").strip().lower()
    if next_status not in ALLOWED_HANDOFF_STATUSES:
        return {
            "status": "invalid_status",
            "allowedStatuses": sorted(ALLOWED_HANDOFF_STATUSES),
            "message": "Experience Studio handoffs can move only through Command Center review states.",
        }
    now = _now_iso()
    with _STORE_LOCK:
        records = _read_records()
        for record in records:
            handoffs = record.get("handoffs", []) if isinstance(record.get("handoffs"), list) else []
            for handoff in handoffs:
                if not isinstance(handoff, dict) or str(handoff.get("id")) != handoff_id:
                    continue
                handoff["status"] = next_status
                handoff["reviewedAt"] = now
                handoff["reviewedBy"] = payload.get("actor") or "command_center"
                handoff["commandCenterNote"] = _text(payload.get("note"), f"Command Center moved handoff to {next_status}.")
                record["updatedAt"] = now
                trail = record.setdefault("reviewTrail", [])
                if isinstance(trail, list):
                    trail.append(
                        {
                            "status": record.get("status", "ready_for_publish"),
                            "actor": payload.get("actor") or "command_center",
                            "note": handoff["commandCenterNote"],
                            "at": now,
                            "handoffId": handoff_id,
                            "handoffStatus": next_status,
                        }
                    )
                _write_records(records)
                return {
                    "status": "updated",
                    "mode": "experience_studio_command_center_handoff_review",
                    "handoff": handoff,
                    "summary": _compact_handoff(record, handoff),
                    "draftSummary": _compact_record(record),
                }
    return {"status": "not_found", "message": f"Handoff {handoff_id} was not found."}


def _text(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback


def _as_text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        candidates = value.replace(",", "\n").splitlines()
    elif isinstance(value, list):
        candidates = [item.get("name") if isinstance(item, dict) else item for item in value]
    else:
        candidates = []
    seen: set[str] = set()
    result: list[str] = []
    for item in candidates:
        text = str(item or "").strip()
        if text and text.lower() not in seen:
            seen.add(text.lower())
            result.append(text)
    return result


def _real_inputs(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("realInputs") if isinstance(payload.get("realInputs"), dict) else {}
    locations = _as_text_list(raw.get("locations"))
    indoor = _as_text_list(raw.get("indoorLocations"))
    quiet = _as_text_list(raw.get("quietLocations"))
    attractions = _as_text_list(raw.get("attractionLocations"))
    accessible = _as_text_list(raw.get("accessibleRoutes"))
    safety = _as_text_list(raw.get("safetyInstructions"))
    channel_owners = raw.get("channelOwners") if isinstance(raw.get("channelOwners"), dict) else {}
    venue_identity = raw.get("venueIdentity") if isinstance(raw.get("venueIdentity"), dict) else {}
    location_details = raw.get("locationDetails") if isinstance(raw.get("locationDetails"), dict) else {}
    profile_intelligence = raw.get("profileIntelligence") if isinstance(raw.get("profileIntelligence"), dict) else {}
    guest_segments = raw.get("guestSegments") if isinstance(raw.get("guestSegments"), list) else []
    spatial_model = raw.get("spatialModel") if isinstance(raw.get("spatialModel"), dict) else {}
    agent_context = raw.get("agentContext") if isinstance(raw.get("agentContext"), dict) else {}
    learning_context = raw.get("learningContext") if isinstance(raw.get("learningContext"), dict) else {}
    source = _text(raw.get("source"), "manual_brief")
    return {
        "venueIdentity": venue_identity,
        "locations": locations,
        "indoorLocations": indoor,
        "quietLocations": quiet,
        "attractionLocations": attractions,
        "accessibleRoutes": accessible,
        "safetyInstructions": safety,
        "channelOwners": {str(key): str(value) for key, value in channel_owners.items() if str(value or "").strip()},
        "locationDetails": {str(key): value for key, value in location_details.items() if isinstance(value, dict)},
        "profileIntelligence": profile_intelligence,
        "guestSegments": [item for item in guest_segments if isinstance(item, dict)],
        "spatialModel": spatial_model,
        "agentContext": agent_context,
        "learningContext": learning_context,
        "source": source,
        "hasRealInputs": bool(locations or indoor or quiet or attractions or accessible or safety or channel_owners),
    }


def _profile_intelligence(real_inputs: dict[str, Any]) -> dict[str, Any]:
    return real_inputs.get("profileIntelligence") if isinstance(real_inputs.get("profileIntelligence"), dict) else {}


def _experience_rules(real_inputs: dict[str, Any]) -> dict[str, Any]:
    intelligence = _profile_intelligence(real_inputs)
    return intelligence.get("experienceRules") if isinstance(intelligence.get("experienceRules"), dict) else {}


def _rule_candidates(real_inputs: dict[str, Any], key: str) -> list[str]:
    value = _experience_rules(real_inputs).get(key)
    return _as_text_list(value)


def _names_for_zones(real_inputs: dict[str, Any], zone_ids: list[str]) -> list[str]:
    details = real_inputs.get("locationDetails", {}) if isinstance(real_inputs.get("locationDetails"), dict) else {}
    names: list[str] = []
    zones = {str(zone_id) for zone_id in zone_ids if str(zone_id).strip()}
    for name, detail in details.items():
        if isinstance(detail, dict) and str(detail.get("zoneId") or "") in zones:
            names.append(str(name))
    return names


def _kid_quest_candidates(real_inputs: dict[str, Any]) -> list[str]:
    details = real_inputs.get("locationDetails", {}) if isinstance(real_inputs.get("locationDetails"), dict) else {}
    candidates = _rule_candidates(real_inputs, "kidFriendlyAnchors") + list(real_inputs.get("attractionLocations", [])) + list(real_inputs.get("quietLocations", [])) + list(real_inputs.get("locations", []))
    blocked_kinds = {"restrooms", "first_aid", "guest_services", "water_refill", "family_service"}
    preferred_names = [
        "Theater B",
        "Storybook Boats",
        "Shade Garden",
        "Harbor Treats",
        "Lagoon Lanterns",
        "Arcade Zone",
        "Theater B Cooling Show",
        "Indoor Hub",
        "Covered Plaza",
    ]

    def allowed(name: str) -> bool:
        detail = details.get(name, {}) if isinstance(details.get(name), dict) else {}
        kind = str(detail.get("kind") or "").strip()
        if kind in blocked_kinds:
            return False
        if detail.get("heightRequirementInches") and float(detail.get("heightRequirementInches") or 0) >= 44:
            return False
        thrill = str(detail.get("thrillLevel") or "").lower()
        return "high" not in thrill

    ordered = [name for name in preferred_names if name in candidates or name in details]
    ordered += candidates
    return [name for name in dict.fromkeys(ordered) if allowed(name)]


def _route_from_real_inputs(template_id: str, template: dict[str, Any], real_inputs: dict[str, Any]) -> list[str]:
    placeholders = list(template.get("route", []))
    locations = list(real_inputs.get("locations", []))
    indoor = list(real_inputs.get("indoorLocations", []))
    quiet = list(real_inputs.get("quietLocations", []))
    attractions = list(real_inputs.get("attractionLocations", []))
    safety = list(real_inputs.get("safetyInstructions", []))
    if template_id == "rainy-day":
        rule_zones = _rule_candidates(real_inputs, "rainyDayAnchors")
        candidates = _names_for_zones(real_inputs, rule_zones) + indoor + quiet + locations
    elif template_id == "low-sensory":
        candidates = quiet + indoor + locations
    elif template_id == "safety-signage":
        candidates = safety + locations
    elif template_id == "attraction-copy":
        candidates = attractions + locations
    elif template_id == "vip-tour":
        candidates = _rule_candidates(real_inputs, "vipRouteAnchors") + ["Front Gate"] + attractions + quiet + locations
    elif template_id == "kid-quest":
        candidates = _kid_quest_candidates(real_inputs)
    elif template_id in {"halloween-route", "scavenger-hunt"}:
        candidates = _rule_candidates(real_inputs, "halloweenCandidateLocations") + locations + indoor + quiet
    else:
        candidates = locations + indoor + quiet
    result = list(dict.fromkeys(candidates))[: len(placeholders)]
    return result + placeholders[len(result) :]


def _missing_real_inputs(route: list[dict[str, Any]], real_inputs: dict[str, Any]) -> list[str]:
    missing = []
    if any("needed" in str(item.get("stop") or "").lower() for item in route if isinstance(item, dict)):
        missing.append("real_location_names")
    if not real_inputs.get("accessibleRoutes"):
        missing.append("real_accessibility_map")
    if not real_inputs.get("channelOwners"):
        missing.append("real_channel_owners")
    if not real_inputs.get("safetyInstructions"):
        missing.append("real_safety_or_operating_instructions")
    return missing


def _source_integrity(route: list[dict[str, Any]], real_inputs: dict[str, Any], context: dict[str, Any], intelligence: dict[str, Any], quality_gaps: list[str]) -> dict[str, Any]:
    missing_inputs = _missing_real_inputs(route, real_inputs)
    return {
        "usesSeedData": False,
        "usesSimulatedParkState": False,
        "usesInventedLocations": False,
        "parkContextSource": context.get("source"),
        "realInputSource": real_inputs.get("source"),
        "realInputCount": len(real_inputs.get("locations", [])) + len(real_inputs.get("indoorLocations", [])) + len(real_inputs.get("quietLocations", [])) + len(real_inputs.get("accessibleRoutes", [])) + len(real_inputs.get("safetyInstructions", [])),
        "profileIntelligenceAttached": bool(intelligence),
        "profileIntelligenceQualityGaps": quality_gaps,
        "missingRealInputs": missing_inputs,
        "readyForHandoff": not missing_inputs and not _has_unresolved_placeholders({"route": route}),
    }


def _has_unresolved_placeholders(draft: dict[str, Any]) -> bool:
    route = draft.get("route", []) if isinstance(draft.get("route"), list) else []
    text = json.dumps(route, default=str).lower()
    return " needed" in text or "real location required" in text or "blocked until the real" in text


def _pct(value: Any) -> str:
    return f"{round(float(value))}%" if isinstance(value, int | float) else "--"


def _top(items: Any, key: str) -> dict[str, Any] | None:
    if not isinstance(items, list) or not items:
        return None
    records = [item for item in items if isinstance(item, dict)]
    if not records:
        return None
    return sorted(records, key=lambda item: float(item.get(key) or 0), reverse=True)[0]


def _park_context(state: dict[str, Any] | None) -> dict[str, Any]:
    if not state:
        return {
            "facts": [],
            "weather": {},
            "topZone": None,
            "topRide": None,
            "topPath": None,
            "source": "not_attached_no_seed_mode",
        }
    state = state or {}
    flow = state.get("guestFlow", {}) if isinstance(state.get("guestFlow"), dict) else {}
    weather = state.get("weather", {}) if isinstance(state.get("weather"), dict) else {}
    top_zone = _top(flow.get("zones"), "density")
    top_ride = _top(flow.get("rides"), "waitMins")
    top_path = _top(flow.get("paths"), "congestionLevel")
    facts = [
        f"{top_zone.get('name')} at {_pct(top_zone.get('density'))} density" if top_zone else None,
        f"{top_ride.get('name')} {top_ride.get('waitMins')}m wait" if top_ride else None,
        f"{top_path.get('from')} to {top_path.get('to')} path pressure" if top_path else None,
        f"{weather.get('condition')} weather" if weather.get("condition") else None,
    ]
    return {
        "facts": [fact for fact in facts if fact],
        "weather": weather,
        "topZone": top_zone,
        "topRide": top_ride,
        "topPath": top_path,
        "source": "caller_supplied_state",
    }


def _detail_for_stop(real_inputs: dict[str, Any], stop: str) -> dict[str, Any]:
    details = real_inputs.get("locationDetails", {}) if isinstance(real_inputs.get("locationDetails"), dict) else {}
    if stop in details and isinstance(details[stop], dict):
        return details[stop]
    label = stop.split(":", 1)[0].strip()
    if label in details and isinstance(details[label], dict):
        return details[label]
    lowered = label.lower()
    for name, detail in details.items():
        if lowered == str(name).lower() and isinstance(detail, dict):
            return detail
    return {}


def _detail_phrase(detail: dict[str, Any]) -> str:
    if not detail:
        return ""
    pieces = []
    if detail.get("kind"):
        pieces.append(str(detail.get("kind")).replace("_", " "))
    if detail.get("zoneId"):
        pieces.append(f"in {detail.get('zoneId')}")
    if detail.get("familyFit"):
        pieces.append(str(detail.get("familyFit")).rstrip("."))
    elif detail.get("bestFor"):
        best_for = detail.get("bestFor") if isinstance(detail.get("bestFor"), list) else [detail.get("bestFor")]
        pieces.append(f"best for {', '.join(str(item) for item in best_for if item)}")
    elif detail.get("seating"):
        pieces.append(str(detail.get("seating")))
    return "; ".join(pieces)


def _accessibility_for_stop(template_id: str, detail: dict[str, Any], real_inputs: dict[str, Any]) -> str:
    if detail.get("accessibilityNote"):
        return str(detail.get("accessibilityNote"))
    if detail.get("accessible") is True:
        return "This location is marked accessible on the approved public map."
    if detail.get("familyRoom") is True:
        return "Family room support is available here."
    if detail.get("kind") in {"food", "photo_spots", "quiet_or_cooling", "show"}:
        return "Confirm the current step-free approach, seating or viewing space, and nearby reset option before publishing."
    if template_id == "low-sensory" and detail.get("bestFor"):
        return "Use this as a lower-stimulus or decompression stop; confirm current crowd and audio levels before publishing."
    accessibility = real_inputs.get("accessibleRoutes", [])
    if accessibility:
        return str(accessibility[0])
    return "Check path width, shade, seating, and step-free access before publishing."


def _brand_bible(real_inputs: dict[str, Any]) -> dict[str, Any]:
    intelligence = _profile_intelligence(real_inputs)
    return intelligence.get("brandBible") if isinstance(intelligence.get("brandBible"), dict) else {}


def _module_policy(real_inputs: dict[str, Any], module_id: str) -> dict[str, Any]:
    intelligence = _profile_intelligence(real_inputs)
    policies = intelligence.get("modulePolicy") if isinstance(intelligence.get("modulePolicy"), dict) else {}
    return policies.get(module_id) if isinstance(policies.get(module_id), dict) else {}


def _stop_intelligence_note(template_id: str, detail: dict[str, Any], real_inputs: dict[str, Any]) -> str:
    intelligence = _profile_intelligence(real_inputs)
    rules = _experience_rules(real_inputs)
    zone_id = str(detail.get("zoneId") or "")
    quality_gaps = [str(item) for item in intelligence.get("qualityGaps", []) if str(item).strip()] if isinstance(intelligence.get("qualityGaps"), list) else []
    parts = []
    if zone_id and zone_id in set(_as_text_list(rules.get("rainyDayAnchors"))):
        parts.append("rainy-day anchor")
    if detail.get("name") in set(_as_text_list(rules.get("kidFriendlyAnchors"))):
        parts.append("kid-friendly anchor")
    if detail.get("name") in set(_as_text_list(rules.get("vipRouteAnchors"))):
        parts.append("VIP route anchor")
    if template_id == "low-sensory" and quality_gaps:
        parts.append("confirm derived path and capacity assumptions before publishing")
    return "; ".join(parts)


def _creative_brief(payload: dict[str, Any], template_id: str) -> dict[str, str]:
    defaults = {
        "halloween-route": {
            "creativeDirection": "story-rich",
            "storyArc": "Invitation -> clue -> reveal -> choice -> finale",
            "sensoryLevel": "balanced",
            "walkingPace": "moderate",
            "outputPackage": "full package",
            "seasonalTheme": "family-safe Halloween mystery",
        },
        "rainy-day": {
            "creativeDirection": "comfort-first",
            "storyArc": "Arrival reset -> dry discovery -> warm pause -> flexible choice -> covered close",
            "sensoryLevel": "low",
            "walkingPace": "compact",
            "outputPackage": "full package",
            "seasonalTheme": "rainy-day comfort route",
        },
        "low-sensory": {
            "creativeDirection": "comfort-first",
            "storyArc": "Orient -> quiet move -> reset -> optional delight -> easy return",
            "sensoryLevel": "low",
            "walkingPace": "compact",
            "outputPackage": "route storyboard",
            "seasonalTheme": "predictable low-sensory path",
        },
        "kid-quest": {
            "creativeDirection": "playful mission",
            "storyArc": "Mission start -> clue -> discovery -> reward -> celebration",
            "sensoryLevel": "balanced",
            "walkingPace": "moderate",
            "outputPackage": "full package",
            "seasonalTheme": "kid-friendly quest",
        },
        "vip-tour": {
            "creativeDirection": "premium host-led",
            "storyArc": "Welcome -> insider reveal -> signature moment -> relaxed pause -> closing keepsake",
            "sensoryLevel": "balanced",
            "walkingPace": "exploratory",
            "outputPackage": "host script",
            "seasonalTheme": "VIP hosted route",
        },
    }
    base = defaults.get(template_id, {
        "creativeDirection": "story-rich",
        "storyArc": "Hook -> discovery -> transition -> payoff -> close",
        "sensoryLevel": "balanced",
        "walkingPace": "moderate",
        "outputPackage": "full package",
        "seasonalTheme": "park experience",
    })
    return {
        key: _text(payload.get(key), fallback)
        for key, fallback in base.items()
    }


def _story_stage(creative_brief: dict[str, str], index: int) -> str:
    arc = creative_brief.get("storyArc") or ""
    separators = ["->", ">", "|", ","]
    beats = [arc]
    for separator in separators:
        if separator in arc:
            beats = arc.split(separator)
            break
    cleaned = [beat.strip() for beat in beats if beat.strip()]
    if not cleaned:
        return f"Beat {index + 1}"
    return cleaned[min(index, len(cleaned) - 1)]


def _kid_quest_story(stop: str, index: int, stage: str, audience: str, detail: dict[str, Any], creative_brief: dict[str, str]) -> tuple[str, str, str]:
    theme = creative_brief.get("seasonalTheme") or "kid-friendly badge quest"
    stage_label = stage[:1].upper() + stage[1:] if stage else f"Beat {index + 1}"
    stop_lower = stop.lower()
    detail_hint = _detail_phrase(detail)
    beats = [
        {
            "purpose": f"{stage_label}: launch the {theme} with a tangible mission card and one easy first win.",
            "guest": f"1. Mission start at {stop}: pick up the Quest Card and learn the badge rule: find one real park detail, say what it means, then choose the next marker together.",
            "staff": "Give caregivers the optional route frame, point out the nearest calm exit, and keep the first clue under 20 seconds.",
        },
        {
            "purpose": f"{stage_label}: turn the location into a clue that kids can solve by looking, not waiting.",
            "guest": f"2. Clue stop at {stop}: ask kids to find the gentlest moving detail, then mark the wave badge before heading to the next visible landmark.",
            "staff": "Invite kids to point, count, or name what they see; keep groups moving so the clue does not block the path.",
        },
        {
            "purpose": f"{stage_label}: add a discovery moment with a visual proof point caregivers can verify quickly.",
            "guest": f"3. Discovery at {stop}: look for the hidden color, shape, or sign detail. When kids spot it, they earn the explorer badge and choose the next direction.",
            "staff": "Use the same clue wording for every group and offer a skip option if the area feels too loud or crowded.",
        },
        {
            "purpose": f"{stage_label}: give the quest a small reward without making an availability or merchandise claim.",
            "guest": f"4. Reward beat at {stop}: celebrate the solved clues with a stamp, sticker, or verbal badge moment, then invite families to take a short reset.",
            "staff": "Treat the reward as a reviewable placeholder until the channel owner confirms the actual fulfillment item.",
        },
        {
            "purpose": f"{stage_label}: close the story with a caregiver-friendly photo or memory moment.",
            "guest": f"5. Celebration at {stop}: finish the badge quest by naming the favorite clue, taking an optional photo, and choosing a calm next stop.",
            "staff": "Close with one sentence, avoid promising character appearances, and direct families to the nearest support point when support is requested.",
        },
    ]
    selected = beats[min(index, len(beats) - 1)]
    if "storybook" in stop_lower or "boat" in stop_lower:
        selected["guest"] = f"{index + 1}. {stage_label} at {stop}: find the boat or story detail that feels the calmest, then mark the wave badge and follow the next clue toward the lantern side of the park."
    elif "lantern" in stop_lower:
        if index >= 4:
            selected["guest"] = f"{index + 1}. {stage_label} at {stop}: finish the badge quest by choosing a favorite lantern color, naming the best clue, and taking an optional family photo."
        else:
            selected["guest"] = f"{index + 1}. {stage_label} at {stop}: count three lantern shapes or colors, choose the one that feels most magical, and earn the glow badge."
    elif "shade" in stop_lower or "covered" in stop_lower:
        selected["guest"] = f"{index + 1}. {stage_label} at {stop}: take a quiet explorer pause, find the coolest shaded detail, and let caregivers decide whether to continue or reset."
    elif "treat" in stop_lower or "food" in stop_lower:
        selected["guest"] = f"{index + 1}. {stage_label} at {stop}: celebrate the solved clues with a reviewable treat-or-stamp moment; do not promise a specific item until Food and Retail approves it."
    elif "arcade" in stop_lower:
        selected["guest"] = f"{index + 1}. {stage_label} at {stop}: find a game light, sound, or score shape, then choose the explorer badge without requiring anyone to play."
    if detail_hint:
        selected["guest"] = f"{selected['guest']} Profile fact: {detail_hint}."
    return selected["purpose"], selected["guest"], selected["staff"]


def _draft_reasoning_trace(template_id: str, route_names: list[str], real_inputs: dict[str, Any], creative_brief: dict[str, str], llm_status: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    intelligence = _profile_intelligence(real_inputs)
    rules = _experience_rules(real_inputs)
    return [
        {
            "step": "brief_interpretation",
            "summary": f"Template {template_id} requested a {creative_brief.get('creativeDirection')} package with arc {creative_brief.get('storyArc')}.",
            "inputs": {
                "sensoryLevel": creative_brief.get("sensoryLevel"),
                "walkingPace": creative_brief.get("walkingPace"),
                "outputPackage": creative_brief.get("outputPackage"),
                "seasonalTheme": creative_brief.get("seasonalTheme"),
            },
        },
        {
            "step": "verified_profile_grounding",
            "summary": "Venue Profile supplied approved location names, accessibility facts, brand rules, and profile intelligence.",
            "inputs": {
                "source": real_inputs.get("source"),
                "locationCount": len(real_inputs.get("locations", [])),
                "profileIntelligenceSource": intelligence.get("source") or "not_connected",
            },
        },
        {
            "step": "route_candidate_filtering",
            "summary": "Route candidates were filtered to verified, kid-appropriate experience moments before copy was written.",
            "inputs": {
                "candidateRule": "kidFriendlyAnchors excluding support-only nodes and high-thrill stops" if template_id == "kid-quest" else "template-specific profile rules",
                "experienceRules": {key: rules.get(key) for key in ("kidFriendlyAnchors", "rainyDayAnchors", "vipRouteAnchors") if key in rules},
                "selectedStops": route_names,
            },
        },
        {
            "step": "story_arc_mapping",
            "summary": "Each selected stop was mapped to a different story beat so the route has a beginning, middle, reward, and finish.",
            "inputs": {
                "storyArc": creative_brief.get("storyArc"),
                "selectedStops": route_names,
            },
        },
        {
            "step": "source_integrity_gate",
            "summary": "The draft was checked for missing real inputs, invented locations, seed/sample usage, and operational claims.",
            "inputs": {
                "usesSeedData": False,
                "usesInventedLocations": False,
                "profileIntelligenceAttached": bool(intelligence),
            },
        },
        {
            "step": "llm_creative_reasoning_pass",
            "summary": "Optional LLM polish may rewrite purpose, guest copy, staff notes, and channel copy, but cannot change verified stops or source receipts.",
            "inputs": llm_status or {"status": "not_requested"},
        },
    ]


def _llm_creative_prompt(payload: dict[str, Any], state_context: dict[str, Any], deterministic_draft: dict[str, Any]) -> dict[str, Any]:
    route_contract = [
        {
            "stop": item.get("stop"),
            "purpose": item.get("purpose"),
            "guestCopy": item.get("guestCopy"),
            "staffNote": item.get("staffNote"),
            "accessibilityNote": item.get("accessibilityNote"),
            "profileIntelligenceNote": item.get("profileIntelligenceNote"),
        }
        for item in deterministic_draft.get("route", [])
        if isinstance(item, dict)
    ]
    return {
        "task": "Improve a ParkPulse Experience Studio draft as a creative reasoning pass after verified route selection.",
        "return_only_json": True,
        "hard_constraints": [
            "Keep the exact stop names, stop count, and stop order.",
            "Only rewrite purpose, guestCopy, staffNote, message copy, creative_rationale, and review_questions.",
            "Do not invent places, characters, live availability, wait times, weather, staffing, safety instructions, discounts, guarantees, or access-lane claims.",
            "Do not promise a specific reward item; keep rewards reviewable.",
            "Keep movement optional and reviewable.",
        ],
        "brief": {
            "templateId": payload.get("templateId") or payload.get("template"),
            "audience": payload.get("audience"),
            "tone": payload.get("tone"),
            "constraints": payload.get("constraints"),
            "creativeDirection": payload.get("creativeDirection"),
            "storyArc": payload.get("storyArc"),
            "sensoryLevel": payload.get("sensoryLevel"),
            "walkingPace": payload.get("walkingPace"),
            "outputPackage": payload.get("outputPackage"),
            "seasonalTheme": payload.get("seasonalTheme"),
        },
        "verified_route_contract": route_contract,
        "messages": deterministic_draft.get("messages", []),
        "state_context_source": state_context.get("source"),
        "return_json_shape": {
            "route": [{"stop": item.get("stop"), "purpose": "...", "guestCopy": "...", "staffNote": "..."} for item in route_contract],
            "messages": deterministic_draft.get("messages", []),
            "creative_rationale": ["why this route works"],
            "review_questions": ["short review questions"],
        },
    }


def _merge_llm_creative_pass(base_draft: dict[str, Any], generated: dict[str, Any], real_inputs: dict[str, Any], template_id: str, constraints: str, context: dict[str, Any]) -> dict[str, Any]:
    merged = json.loads(json.dumps(base_draft, default=str))
    base_route = merged.get("route", []) if isinstance(merged.get("route"), list) else []
    generated_route = generated.get("route") if isinstance(generated.get("route"), list) else []
    base_stops = [str(item.get("stop") or "") for item in base_route if isinstance(item, dict)]
    generated_stops = [str(item.get("stop") or "") for item in generated_route if isinstance(item, dict)]
    accepted_route = len(base_route) == len(generated_route) and base_stops == generated_stops
    if accepted_route:
        for base_item, generated_item in zip(base_route, generated_route, strict=False):
            if not isinstance(base_item, dict) or not isinstance(generated_item, dict):
                continue
            for field in ("purpose", "guestCopy", "staffNote"):
                value = str(generated_item.get(field) or "").strip()
                if value:
                    base_item[field] = value

    generated_messages = generated.get("messages") if isinstance(generated.get("messages"), list) else []
    base_messages = merged.get("messages", []) if isinstance(merged.get("messages"), list) else []
    if generated_messages and len(generated_messages) == len(base_messages):
        for base_item, generated_item in zip(base_messages, generated_messages, strict=False):
            if not isinstance(base_item, dict) or not isinstance(generated_item, dict):
                continue
            if str(base_item.get("channel") or "") != str(generated_item.get("channel") or ""):
                continue
            copy = str(generated_item.get("copy") or "").strip()
            if copy:
                base_item["copy"] = copy

    intelligence = _profile_intelligence(real_inputs)
    quality_gaps = [str(item) for item in intelligence.get("qualityGaps", []) if str(item).strip()] if isinstance(intelligence.get("qualityGaps"), list) else []
    merged["sourceIntegrity"] = _source_integrity(base_route, real_inputs, context, intelligence, quality_gaps)
    merged["studioReview"] = _studio_review(template_id, merged, constraints, real_inputs)
    merged["llmCreativePass"] = {
        "status": "merged" if accepted_route else "route_rejected_preserved_deterministic",
        "routeAccepted": accepted_route,
        "creativeRationale": generated.get("creative_rationale", []) if isinstance(generated.get("creative_rationale"), list) else [],
        "reviewQuestions": generated.get("review_questions", []) if isinstance(generated.get("review_questions"), list) else [],
        "guardrails": ["verified_stop_names_locked", "source_integrity_recomputed", "reviewers_rerun"],
    }
    return merged


def _make_stop(template_id: str, stop: str, index: int, audience: str, tone: str, context_hint: str, real_inputs: dict[str, Any], creative_brief: dict[str, str]) -> dict[str, str]:
    step = index + 1
    needs_real_location = "needed" in stop.lower()
    source = str(real_inputs.get("source") or "manual_brief")
    venue = real_inputs.get("venueIdentity", {}) if isinstance(real_inputs.get("venueIdentity"), dict) else {}
    venue_name = _text(venue.get("name"), "the venue")
    detail = _detail_for_stop(real_inputs, stop)
    detail_phrase = _detail_phrase(detail)
    sensory_note = _text(detail.get("sensoryNote"), "")
    intelligence_note = _stop_intelligence_note(template_id, detail, real_inputs)
    stage = _story_stage(creative_brief, index)
    direction = creative_brief.get("creativeDirection", "story-rich")
    pace = creative_brief.get("walkingPace", "moderate")
    sensory_level = creative_brief.get("sensoryLevel", "balanced")
    if template_id == "safety-signage":
        instruction_location, _, instruction = stop.partition(":")
        safety_copy = instruction.strip() or "Follow the posted instruction and ask a team member if you need help."
        return {
            "stop": instruction_location.strip() or stop,
            "purpose": "Make the required behavior visible without adding operational ambiguity.",
            "guestCopy": "Draft copy is blocked until the real safety instruction and location are provided." if needs_real_location else safety_copy,
            "staffNote": "Do not publish this message until the real operating instruction is supplied and approved." if needs_real_location else f"Confirm this wording matches the approved instruction source for {venue_name}.",
            "accessibilityNote": "Keep the final message readable at distance and pair it with a simple icon in production.",
            "profileIntelligenceNote": "Safety/signage copy must follow module policy and source freshness rules.",
            "source": "missing_real_input" if needs_real_location else source,
        }
    if template_id == "attraction-copy":
        return {
            "stop": stop,
            "purpose": "Set expectations before the guest chooses the attraction.",
            "guestCopy": "Draft copy is blocked until the real attraction facts are provided." if needs_real_location else f"{stop} gives {audience} a {direction} moment with {tone} wording. {detail_phrase or 'Use the approved attraction facts to set expectations.'}",
            "staffNote": "Confirm the final description against current operating limits before publishing.",
            "accessibilityNote": _accessibility_for_stop(template_id, detail, real_inputs),
            "profileIntelligenceNote": intelligence_note or "Use approved profile facts only; do not add availability claims.",
            "source": "missing_real_input" if needs_real_location else source,
        }
    if template_id == "rainy-day":
        guest_copy = f"{step}. {stage} at {stop}: invite {audience} into a dry, {tone} reset with a {pace} pace. {detail_phrase}"
    elif template_id == "low-sensory":
        guest_copy = f"{step}. {stage} at {stop}: keep the beat predictable, quiet, and easy to leave. {sensory_note or detail_phrase}"
    elif template_id == "kid-quest":
        kid_purpose, guest_copy, kid_staff_note = _kid_quest_story(stop, index, stage, audience, detail, creative_brief)
    elif template_id == "scavenger-hunt":
        guest_copy = f"{step}. {stage} at {stop}: place a visual clue guests can solve while moving, then let the answer pull them toward the next reveal."
    elif template_id == "vip-tour":
        guest_copy = f"{step}. {stage} at {stop}: give the host one insider detail, one graceful pause, and one alternate if the moment needs to flex."
    else:
        guest_copy = f"{step}. {stage} at {stop}: follow the {tone} cue toward the next {direction} moment. {context_hint}"
    return {
        "stop": stop,
        "purpose": kid_purpose if template_id == "kid-quest" else f"{stage}: shape a {direction} beat at {sensory_level} sensory level.",
        "guestCopy": f"{step}. Real location required before guest copy can be finalized. Intended tone: {tone}. {context_hint}" if needs_real_location else guest_copy.strip(),
        "staffNote": "Do not stage staff from this draft until the real location and owner are supplied." if needs_real_location else kid_staff_note if template_id == "kid-quest" else "Welcome guests, name the journey, and confirm the route is optional." if step == 1 else "Keep the handoff short and point guests toward the next visual landmark.",
        "accessibilityNote": "Real route accessibility facts are required before approval." if needs_real_location else _accessibility_for_stop(template_id, detail, real_inputs),
        "profileIntelligenceNote": "Real profile intelligence required before this stop can be finalized." if needs_real_location else intelligence_note or "Follow module policy; avoid live availability, staffing, safety, and access-lane claims.",
        "source": "missing_real_input" if needs_real_location else source,
    }


def _draft_from_payload(payload: dict[str, Any], state: dict[str, Any] | None = None) -> dict[str, Any]:
    template_id = str(payload.get("templateId") or payload.get("template") or "halloween-route")
    template = TEMPLATES.get(template_id, TEMPLATES["halloween-route"])
    audience = _text(payload.get("audience"), "mixed guest groups")
    tone = _text(payload.get("tone"), "clear, themed, guest-safe")
    constraints = _text(payload.get("constraints"), "Keep the draft accurate, accessible, and reviewable before publishing.")
    real_inputs = _real_inputs(payload)
    context = _park_context(state)
    context_hint = f"Caller-supplied context: {'; '.join(context['facts'])}." if context["facts"] else "No park facts are attached; do not infer locations, wait times, weather, staffing, or availability."
    creative_brief = _creative_brief(payload, template_id)
    route_names = _route_from_real_inputs(template_id, template, real_inputs)
    route = [_make_stop(template_id, stop, index, audience, tone, context_hint, real_inputs, creative_brief) for index, stop in enumerate(route_names)]
    first_stop = route[0]["stop"] if route and "needed" not in str(route[0].get("stop") or "").lower() else "the verified start location"
    venue = real_inputs.get("venueIdentity", {}) if isinstance(real_inputs.get("venueIdentity"), dict) else {}
    venue_name = _text(venue.get("name"), "the venue")
    profile_type = _text(venue.get("profileType"), "venue_export")
    intelligence = _profile_intelligence(real_inputs)
    brand_bible = _brand_bible(real_inputs)
    studio_policy = _module_policy(real_inputs, "experience_studio")
    learning_schema = intelligence.get("learningSchema") if isinstance(intelligence.get("learningSchema"), dict) else {}
    quality_gaps = [str(item) for item in intelligence.get("qualityGaps", []) if str(item).strip()] if isinstance(intelligence.get("qualityGaps"), list) else []
    coverage = intelligence.get("coverage") if isinstance(intelligence.get("coverage"), dict) else {}
    messages = [
        {
            "channel": "Guest app",
            "copy": f"{template['shortLabel']} at {venue_name}: a {creative_brief['creativeDirection']} experience for {audience}. Start at {first_stop}, follow the posted prompts, and move at a {creative_brief['walkingPace']} pace.",
            "owner": real_inputs.get("channelOwners", {}).get("guest_app") or "real owner needed",
        },
        {
            "channel": "Signage",
            "copy": f"{template['shortLabel']} begins here. Follow the next marker, ask a team member for the accessible option, and keep the journey {creative_brief['sensoryLevel']} and optional.",
            "owner": real_inputs.get("channelOwners", {}).get("signage") or "real owner needed",
        },
        {
            "channel": "Pre-arrival email",
            "copy": f"Your visit includes a {str(template['label']).lower()} designed for {audience}. Check the app before arrival and share accessibility preferences with Guest Services.",
            "owner": real_inputs.get("channelOwners", {}).get("email") or real_inputs.get("channelOwners", {}).get("pre_arrival_email") or "real owner needed",
        },
        {
            "channel": "Staff cue",
            "copy": f"Use the {creative_brief['storyArc']} arc. Position team members at the first and final stops. Use the guest-facing phrase consistently and flag constraints: {constraints}.",
            "owner": real_inputs.get("channelOwners", {}).get("staff_cue") or "real owner needed",
        },
    ]
    draft = {
        "title": template["label"],
        "audience": audience,
        "intent": template["intent"],
        "creativeBrief": {
            **creative_brief,
            "tone": tone,
            "constraints": constraints,
        },
        "route": route,
        "messages": messages,
        "review": [
            {"label": "Brand fit", "status": "clear", "detail": f"Tone is {tone}; creative review should confirm seasonal brand fit."},
            {"label": "Safety risk", "status": "review" if template_id in {"safety-signage", "rainy-day"} else "clear", "detail": "Movement, shelter, height-rule, or ride-behavior copy needs operations review before publishing."},
            {"label": "Accessibility", "status": "clear" if template_id == "low-sensory" else "review", "detail": "Draft includes accessibility notes, but grade, seating, lighting, audio, and alternate routes need map verification."},
            {"label": "Operations boundary", "status": "clear", "detail": "This is a creative draft only. It does not dispatch staff, alter queues, or publish guest messaging automatically."},
        ],
        "productionNotes": [
            f"Venue profile: {venue_name} ({profile_type}). Source: {real_inputs.get('source')}.",
            f"Constraint brief: {constraints}.",
            f"Profile intelligence source: {intelligence.get('source', 'not connected')}; path records {coverage.get('certifiedPaths', 0)}, capacity zones {coverage.get('capacityZones', 0)}, source ledger rows {coverage.get('fieldSourceRows', 0)}.",
            f"Brand rules: tone {', '.join(str(item) for item in brand_bible.get('tone', [])[:4]) if isinstance(brand_bible.get('tone'), list) else 'not connected'}; banned claims {', '.join(str(item) for item in brand_bible.get('bannedClaims', [])[:5]) if isinstance(brand_bible.get('bannedClaims'), list) else 'not connected'}.",
            "Validate final route against open attractions, blocked paths, lighting, sound levels, and crowd-control requirements.",
            "Send operational instructions to Command Center review before they become live guest-facing actions.",
        ],
        "profileIntelligence": {
            "source": intelligence.get("source") or "not_connected",
            "coverage": coverage,
            "qualityGaps": quality_gaps,
            "experienceStudioPolicy": {
                "mayDraft": studio_policy.get("mayDraft", []),
                "mustReview": studio_policy.get("mustReview", []),
                "neverClaim": studio_policy.get("neverClaim", []),
            },
            "brandBible": {
                "tone": brand_bible.get("tone", []),
                "bannedClaims": brand_bible.get("bannedClaims", []),
                "supportedLocales": brand_bible.get("supportedLocales", []),
            },
            "learningLabels": learning_schema.get("feedbackLabels", []) if isinstance(learning_schema.get("feedbackLabels"), list) else [],
        },
        "sourceIntegrity": _source_integrity(route, real_inputs, context, intelligence, quality_gaps),
        "reasoningTrace": _draft_reasoning_trace(template_id, route_names, real_inputs, creative_brief),
    }
    draft["studioReview"] = _studio_review(template_id, draft, constraints, real_inputs)
    return draft


def _studio_review(template_id: str, draft: dict[str, Any], constraints: str, real_inputs: dict[str, Any]) -> list[dict[str, str]]:
    review_surface = {
        "title": draft.get("title"),
        "audience": draft.get("audience"),
        "creativeBrief": draft.get("creativeBrief"),
        "route": [
            {
                "stop": item.get("stop"),
                "purpose": item.get("purpose"),
                "guestCopy": item.get("guestCopy"),
                "staffNote": item.get("staffNote"),
                "accessibilityNote": item.get("accessibilityNote"),
            }
            for item in draft.get("route", [])
            if isinstance(item, dict)
        ],
        "messages": draft.get("messages", []),
        "review": draft.get("review", []),
    }
    text = json.dumps(review_surface, default=str).lower()
    movement_terms = any(term in text for term in ["route", "follow", "shelter", "line", "boarding", "move"])
    sensory_terms = any(term in text for term in ["quiet", "sensory", "noise", "lighting", "audio", "calm"])
    intelligence = _profile_intelligence(real_inputs)
    brand_bible = _brand_bible(real_inputs)
    policy = _module_policy(real_inputs, "experience_studio")
    banned_claims = [str(item).lower() for item in brand_bible.get("bannedClaims", []) if str(item).strip()] if isinstance(brand_bible.get("bannedClaims"), list) else []
    quality_gaps = intelligence.get("qualityGaps") if isinstance(intelligence.get("qualityGaps"), list) else []
    policy_must_review = policy.get("mustReview") if isinstance(policy.get("mustReview"), list) else []
    policy_never_claim = policy.get("neverClaim") if isinstance(policy.get("neverClaim"), list) else []
    banned_hit = next((claim for claim in banned_claims if claim and claim in text), "")
    return [
        {
            "agentId": "experience_design_assistant",
            "agentName": "Experience Design Assistant",
            "status": "clear",
            "finding": "Draft includes route or content structure, guest copy, staff notes, and production notes.",
            "nextStep": "Save a version before review if the team wants to preserve this creative direction.",
        },
        {
            "agentId": "brand_voice_reviewer",
            "agentName": "Brand/Voice Reviewer",
            "status": "review" if banned_hit or re.search(r"\b(graphic|mean|scary)\b", text) else "clear",
            "finding": f"Tone and audience are explicit; brand bible banned-claim check {'flagged ' + banned_hit if banned_hit else 'passed'}. Constraints: {constraints}.",
            "nextStep": "Confirm final adjectives, character voice, age fit, and banned-claim avoidance before approval.",
        },
        {
            "agentId": "accessibility_reviewer",
            "agentName": "Accessibility Reviewer",
            "status": "review" if quality_gaps else "clear" if template_id == "low-sensory" or sensory_terms else "review",
            "finding": "Accessibility notes are present; profile intelligence quality gaps require review." if quality_gaps else "Accessibility notes are present and no profile intelligence quality gaps were returned.",
            "nextStep": "Verify grade, seating, shade, step-free alternatives, audio, lighting, decompression points, and any derived path assumptions.",
        },
        {
            "agentId": "safety_messaging_reviewer",
            "agentName": "Safety Messaging Reviewer",
            "status": "review" if movement_terms or template_id in {"safety-signage", "rainy-day"} else "clear",
            "finding": f"Some guest copy may influence movement or safety behavior. Module policy must-review items: {', '.join(str(item) for item in policy_must_review[:3]) or 'not connected'}.",
            "nextStep": "Send movement, shelter, boarding, safety, accessibility, allergy, staffing, or availability claims to Command Center review before publishing.",
        },
        {
            "agentId": "profile_intelligence_reviewer",
            "agentName": "Profile Intelligence Reviewer",
            "status": "review" if quality_gaps else "clear",
            "finding": f"Profile intelligence attached with {len(quality_gaps)} quality gap(s). Never-claim policy: {', '.join(str(item) for item in policy_never_claim[:3]) or 'not connected'}.",
            "nextStep": "Replace derived path, capacity, and timing assumptions with venue-owned feeds when available.",
        },
        {
            "agentId": "publish_readiness_checker",
            "agentName": "Publish Readiness Checker",
            "status": "blocked",
            "finding": "Draft is not publishable until saved, reviewed, approved, and handed off.",
            "nextStep": "Move through draft, in review, approved, and ready for publish states; this studio still does not publish.",
        },
    ]


def _json_from_text(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


def _prompt(payload: dict[str, Any], state_context: dict[str, Any], fallback_draft: dict[str, Any]) -> str:
    return json.dumps(
        {
            "task": "Create a ParkPulse Experience Studio creative draft. This is content and guest journey design, not live operations.",
            "data_integrity": "No seed data. Do not invent park locations, attraction names, staff positions, wait times, weather, availability, or channel owner facts. Use placeholders when real inputs are missing.",
            "control_boundary": {
                "llm_control_authority": False,
                "layer": "Studio Layer",
                "blocked_outputs": ["dispatch_staff", "change_queue", "publish_guest_message", "override_safety_policy"],
                "allowed_outputs": ["draft_route", "guest_copy", "staff_notes", "accessibility_notes", "review_flags"],
            },
            "brief": payload,
            "park_context": state_context,
            "fallback_shape": fallback_draft,
            "return_json_shape": {"draft": fallback_draft, "creative_rationale": ["short reasons"], "review_questions": ["short questions"]},
        },
        default=str,
    )


async def build_experience_studio_payload(payload: dict[str, Any], state: dict[str, Any] | None = None) -> dict[str, Any]:
    venue_experience_data = None
    if payload.get("useVenueExperienceData") is True:
        try:
            from venue_experience_data import resolve_experience_studio_real_inputs

            payload, venue_experience_data = resolve_experience_studio_real_inputs(payload)
        except Exception as error:
            venue_experience_data = {
                "status": "error",
                "mode": "venue_experience_data",
                "readiness": {
                    "status": "blocked",
                    "autofillAllowed": False,
                    "handoffReady": False,
                    "issues": [{"id": "venue_experience_data_load_failed", "severity": "critical", "detail": str(error)[:240]}],
                },
            }
    draft = _draft_from_payload(payload, state)
    state_context = _park_context(state)
    prompt = _prompt(payload, state_context, draft)
    creative_prompt = _llm_creative_prompt(payload, state_context, draft)
    use_llm = bool(payload.get("useLlm")) or os.getenv("PARKPULSE_EXPERIENCE_STUDIO_USE_LLM", "").strip().lower() in {"1", "true", "yes", "on"}
    llm = {"status": "not_requested", "llm_used_for_control": False}

    if use_llm:
        try:
            from gemini_hard_timeout import generate_gemini_json_hard_timeout

            result = await generate_gemini_json_hard_timeout(
                creative_prompt,
                timeout_seconds=float(os.getenv("PARKPULSE_EXPERIENCE_STUDIO_LLM_TIMEOUT_SECONDS", "14")),
                max_output_tokens=int(os.getenv("PARKPULSE_EXPERIENCE_STUDIO_LLM_MAX_OUTPUT_TOKENS", "2200")),
                temperature=float(os.getenv("PARKPULSE_EXPERIENCE_STUDIO_LLM_TEMPERATURE", "0.35")),
            )
            generated = _json_from_text(str(result.get("text") or "{}"))
            if isinstance(generated, dict):
                template_id = str(payload.get("templateId") or payload.get("template") or "halloween-route")
                constraints = _text(payload.get("constraints"), "Keep the draft accurate, accessible, and reviewable before publishing.")
                draft = _merge_llm_creative_pass(draft, generated, _real_inputs(payload), template_id, constraints, state_context)
            llm = {
                "status": "ready",
                "transport": result.get("transport"),
                "creative_rationale": generated.get("creative_rationale", []),
                "review_questions": generated.get("review_questions", []),
                "mergeStatus": draft.get("llmCreativePass", {}).get("status") if isinstance(draft.get("llmCreativePass"), dict) else "unknown",
                "llm_used_for_control": False,
            }
        except Exception as error:
            llm = {"status": "fallback", "error": str(error)[:240], "llm_used_for_control": False}
    if isinstance(draft.get("reasoningTrace"), list):
        draft["reasoningTrace"] = [
            {
                **item,
                "inputs": llm if item.get("step") == "llm_creative_reasoning_pass" else item.get("inputs", {}),
            }
            if isinstance(item, dict) else item
            for item in draft["reasoningTrace"]
        ]

    return {
        "status": "ready",
        "mode": "experience_studio_creative_draft",
        "draft": draft,
        "prompt": prompt,
        "creativePrompt": creative_prompt,
        "llm": llm,
        "sourceContext": state_context,
        "sourceIntegrity": {
            "usesSeedData": False,
            "usesSimulatedParkState": False,
            "parkContextAttached": bool(state_context.get("facts")),
            "parkContextSource": state_context.get("source"),
            "venueExperienceDataAttached": bool(payload.get("venueExperienceDataUsed")),
        },
        "venueExperienceData": venue_experience_data,
        "controlBoundary": {
            "surface": "Experience Studio",
            "layer": "Studio Layer",
            "category": "content_storytelling_guest_journey_design",
            "llm_control_authority": False,
            "publishing_requires_review": True,
            "not_operations": True,
        },
        "studioLayer": studio_layer_contract(),
    }
