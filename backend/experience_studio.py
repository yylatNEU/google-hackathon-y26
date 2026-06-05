from __future__ import annotations

import hashlib
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

STUDIO_CORE_PRESET: dict[str, Any] = {
    "id": "parkpulse_experience_studio_core_v1",
    "version": "2026-06-04",
    "mission": "Help park experience teams design guest journeys, story, signage, scripts, and channel copy that feel imaginative while staying grounded in approved venue facts.",
    "coreValues": [
        "Guest comfort before novelty.",
        "Accessibility and sensory care by default.",
        "Family-safe imagination without fear, shame, or pressure.",
        "Operational humility: never imply live control, availability, staffing, safety clearance, or dispatch authority.",
        "Source-grounded specificity: use real venue names and facts, or say what input is missing.",
        "Reviewable craft: produce work that creative, accessibility, safety, and channel owners can inspect.",
    ],
    "creativePrinciples": [
        "Use story to reduce uncertainty, not to obscure instructions.",
        "Make every stop earn its place with a guest purpose, emotional beat, staff cue, and accessibility note.",
        "Give guests optionality: a route should invite, not force.",
        "Prefer concrete sensory and pacing language over generic excitement.",
        "Separate guest-facing copy from internal staff notes and operational review items.",
        "Keep rewards, character appearances, shortcuts, and access claims reviewable until owners approve them.",
    ],
    "reasoningPriorities": [
        "1. Protect source integrity and policy boundaries.",
        "2. Fit the target audience and visit context.",
        "3. Improve comfort, clarity, and accessibility.",
        "4. Build a coherent story arc across verified stops.",
        "5. Produce channel-ready copy with explicit review questions.",
    ],
    "voiceDefaults": [
        "Clear, warm, practical, and lightly themed.",
        "Confident about experience design, cautious about operations.",
        "Specific enough for production review; never falsely certain about live park conditions.",
    ],
    "antiPatterns": [
        "Do not invent attractions, zones, characters, rewards, wait times, discounts, weather, crowd levels, or accessibility facts.",
        "Do not use fear, urgency, guilt, or exclusion as creative pressure.",
        "Do not turn a creative route into dispatch, crowd-control, safety, or live-publishing instruction.",
    ],
}


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


EXPERIENCE_STUDIO_MEMORY_COLLECTIONS = [
    "experience_studio_generation_runs",
    "experience_studio_drafts",
    "experience_studio_feedback",
    "experience_studio_revision_events",
    "experience_studio_learning_rules",
]

EXPERIENCE_STUDIO_RETENTION_POLICY = {
    "generationRuns": {"collection": "experience_studio_generation_runs", "retentionDays": 90, "purpose": "Audit prompt, source, model, and merge-guard receipts."},
    "drafts": {"collection": "experience_studio_drafts", "retentionDays": 365, "purpose": "Preserve saved creative packages and source-integrity state."},
    "feedback": {"collection": "experience_studio_feedback", "retentionDays": 365, "purpose": "Preserve review decisions as audit receipts only."},
    "revisionEvents": {"collection": "experience_studio_revision_events", "retentionDays": 365, "purpose": "Preserve content updates, workflow transitions, and handoff receipts."},
    "learningRules": {"collection": "experience_studio_learning_rules", "retentionDays": None, "purpose": "Human-promoted reusable Studio rules from approved finished work; reversible and never automatic training."},
}


FINISHED_WORK_STATUSES = {"approved", "ready_for_publish"}


def _route_summary(draft: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "stop": item.get("stop"),
            "purpose": item.get("purpose"),
            "source": item.get("source"),
            "profileIntelligenceNote": item.get("profileIntelligenceNote"),
        }
        for item in draft.get("route", [])
        if isinstance(item, dict)
    ]


def _review_status_summary(draft: dict[str, Any]) -> dict[str, str]:
    return {
        str(item.get("agentId") or item.get("agentName") or "reviewer"): str(item.get("status") or "unknown")
        for item in draft.get("studioReview", [])
        if isinstance(item, dict)
    }


def _creative_fingerprint(draft: dict[str, Any]) -> dict[str, Any]:
    package = draft.get("creativePackage") if isinstance(draft.get("creativePackage"), dict) else {}
    synthesis = draft.get("creativeSynthesis") if isinstance(draft.get("creativeSynthesis"), dict) else package.get("creativeSynthesis") if isinstance(package.get("creativeSynthesis"), dict) else {}
    executive = package.get("executiveConcept") if isinstance(package.get("executiveConcept"), dict) else {}
    voice = package.get("copyVoice") if isinstance(package.get("copyVoice"), dict) else {}
    selected = synthesis.get("selectedConcept") if isinstance(synthesis.get("selectedConcept"), dict) else {}
    return {
        "title": draft.get("title"),
        "audience": draft.get("audience"),
        "selectedConceptId": synthesis.get("selectedConceptId"),
        "selectedConceptName": synthesis.get("selectedConceptName") or executive.get("name"),
        "guestPromise": executive.get("guestPromise") or selected.get("guestPromise"),
        "route": [item.get("stop") for item in draft.get("route", []) if isinstance(item, dict)],
        "experienceBeats": [item.get("beat") for item in package.get("experienceBeats", []) if isinstance(item, dict)],
        "channelArtifacts": {
            "signageCount": len(package.get("signageSet", [])) if isinstance(package.get("signageSet"), list) else 0,
            "hasPreArrivalEmail": bool(package.get("preArrivalEmail")),
            "hasStaffScript": bool(package.get("staffScript")),
        },
        "selectedTerms": _as_text_list(voice.get("selectedTerms")),
        "reviewStatuses": _review_status_summary(draft),
    }


def _record_studio_memory(collection: str, event: dict[str, Any]) -> dict[str, Any]:
    try:
        from mongo_memory import record_experience_studio_memory_event

        return record_experience_studio_memory_event(collection, event)
    except Exception as error:
        return {
            "status": "skipped",
            "mode": "import_error",
            "connected": False,
            "collection": collection,
            "memoryId": None,
            "error": str(error)[:240],
        }


def _latest_studio_memory(collection: str, limit: int) -> list[dict[str, Any]]:
    try:
        from mongo_memory import get_latest_memory_documents_fast

        return get_latest_memory_documents_fast(collection, max(1, min(limit, 100)))
    except Exception:
        return []


def _active_learning_rules(template_id: str, audience: str, channel_targets: list[str] | None = None, limit: int = 12) -> list[dict[str, Any]]:
    channel_set = {str(item) for item in (channel_targets or []) if str(item).strip()}
    rows = _latest_studio_memory("experience_studio_learning_rules", max(limit * 3, 20))
    active: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_id = str(row.get("id") or row.get("_id") or "")
        if row_id and row_id in seen_ids:
            continue
        if row_id:
            seen_ids.add(row_id)
        if str(row.get("approvalStatus") or "") != "approved":
            continue
        scope = row.get("scope") if isinstance(row.get("scope"), dict) else {}
        row_template = str(scope.get("templateId") or row.get("templateId") or "")
        if row_template and row_template != template_id:
            continue
        rule_channels = {str(item) for item in _as_text_list(scope.get("channels") or row.get("channels"))}
        if rule_channels and channel_set and not rule_channels.intersection(channel_set):
            continue
        active.append(
            {
                "id": row.get("id") or row.get("_id"),
                "rule": row.get("rule"),
                "lesson": row.get("lesson"),
                "sourceDraftId": row.get("sourceDraftId"),
                "templateId": row_template or template_id,
                "audience": scope.get("audience") or audience,
                "channels": sorted(rule_channels),
                "tags": _as_text_list(row.get("tags")),
                "guardrails": _as_text_list(row.get("guardrails")),
                "promotedBy": row.get("promotedBy"),
                "updatedAt": row.get("updatedAt"),
            }
        )
    return active[: max(1, min(limit, 50))]


def _learning_rule_context(template_id: str, audience: str, channel_targets: list[str] | None = None) -> dict[str, Any]:
    rules = _active_learning_rules(template_id, audience, channel_targets)
    return {
        "status": "ready" if rules else "no_approved_rules",
        "mode": "human_approved_learning_rules_v1",
        "source": "experience_studio_learning_rules",
        "ruleCount": len(rules),
        "rules": rules,
        "appliedRules": [str(rule.get("rule")) for rule in rules if rule.get("rule")],
        "guardrails": list(dict.fromkeys(guardrail for rule in rules for guardrail in _as_text_list(rule.get("guardrails")))),
        "learningBoundary": "Rules are human-promoted from finished work and can shape generation, but they cannot override Venue Profile facts, route locks, banned claims, or review gates.",
    }


def _studio_memory_count(collection: str) -> int:
    try:
        from mongo_memory import get_memory_collection_count

        return get_memory_collection_count(collection)
    except Exception:
        return 0


def _studio_memory_connection() -> dict[str, Any]:
    try:
        from mongo_memory import get_memory_connection_status

        status = get_memory_connection_status()
    except Exception as error:
        status = {"mode": "unavailable", "connected": False, "error": str(error)[:240]}
    connected = bool(status.get("connected"))
    return {
        "connected": connected,
        "mode": status.get("mode") or "unknown",
        "database": status.get("database"),
        "primary": "mongodb" if connected else "file_fallback",
        "fallbackPath": None if connected else os.getenv("PARKPULSE_EXPERIENCE_STUDIO_MEMORY_FALLBACK_PATH", "/tmp/parkpulse/experience_studio_memory_fallback.json"),
        "connectivity": status.get("connectivity", {}),
    }


def _memory_learning_policy() -> dict[str, Any]:
    return {
        "primaryMemory": "mongodb",
        "analyticsMirror": "gcp_bigquery_later",
        "rule": "Experience Studio does not run an automatic feedback loop. Generated copy, saved drafts, and reviews are audit receipts. Only approved or ready-for-publish finished-work patterns and explicitly promoted human-approved rules may be reused as bounded creative context.",
        "presetCoreId": STUDIO_CORE_PRESET["id"],
        "generatedTextLearningEligible": False,
        "humanFeedbackLearningEligible": False,
        "finishedWorkPatternMemoryEligible": True,
        "approvedRulePromotionEligible": True,
        "approvedRuleAuthority": "human_promoted_rules_only",
        "finishedWorkAllowedStatuses": sorted(FINISHED_WORK_STATUSES),
    }


def _studio_core_preset() -> dict[str, Any]:
    configured_path = Path(os.getenv("PARKPULSE_EXPERIENCE_STUDIO_CORE_PATH", "")).expanduser()
    default_path = Path(__file__).resolve().parent / "data" / "experience_studio_core.v1.json"
    for path in (configured_path if str(configured_path) not in {"", "."} else None, default_path):
        if path is None or not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and isinstance(payload.get("coreValues"), list) and isinstance(payload.get("reasoningPriorities"), list):
            return {
                **json.loads(json.dumps(STUDIO_CORE_PRESET, default=str)),
                **payload,
                "source": str(path),
            }
    return {**json.loads(json.dumps(STUDIO_CORE_PRESET, default=str)), "source": "builtin"}


def _generation_memory_event(payload: dict[str, Any], draft: dict[str, Any], llm: dict[str, Any], venue_experience_data: dict[str, Any] | None) -> dict[str, Any]:
    source_integrity = draft.get("sourceIntegrity", {}) if isinstance(draft.get("sourceIntegrity"), dict) else {}
    creative_brief = draft.get("creativeBrief", {}) if isinstance(draft.get("creativeBrief"), dict) else {}
    return {
        "_id": f"exp_gen_{uuid.uuid4().hex[:12]}",
        "eventType": "generation_run",
        "templateId": payload.get("templateId") or payload.get("template"),
        "audience": draft.get("audience"),
        "creativeBrief": creative_brief,
        "studioCore": draft.get("studioCore") if isinstance(draft.get("studioCore"), dict) else _studio_core_preset(),
        "llm": llm,
        "route": _route_summary(draft),
        "sourceIntegrity": {
            "readyForHandoff": source_integrity.get("readyForHandoff"),
            "usesSeedData": source_integrity.get("usesSeedData"),
            "usesInventedLocations": source_integrity.get("usesInventedLocations"),
            "realInputSource": source_integrity.get("realInputSource"),
            "realInputCount": source_integrity.get("realInputCount"),
            "missingRealInputs": source_integrity.get("missingRealInputs", []),
        },
        "reviewStatuses": _review_status_summary(draft),
        "venueExperienceDataStatus": venue_experience_data.get("status") if isinstance(venue_experience_data, dict) else None,
        "learningEligible": False,
        "learningSource": "generation_receipt_only",
        "learningPolicy": _memory_learning_policy(),
    }


def list_experience_studio_memory(limit: int = 20) -> dict[str, Any]:
    safe_limit = max(1, min(limit, 100))
    memory_connection = _studio_memory_connection()
    collections = {
        collection: _latest_studio_memory(collection, safe_limit)
        for collection in EXPERIENCE_STUDIO_MEMORY_COLLECTIONS
    }
    receipts = [
        row
        for rows in collections.values()
        for row in rows
        if isinstance(row, dict)
    ]
    receipts = sorted(receipts, key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    return {
        "status": "ready",
        "mode": "experience_studio_memory",
        "memoryLayer": "mongodb_primary_with_file_fallback",
        "memoryConnection": memory_connection,
        "learningPolicy": _memory_learning_policy(),
        "retentionPolicy": EXPERIENCE_STUDIO_RETENTION_POLICY,
        "collections": collections,
        "latestReceipts": receipts[:safe_limit],
        "collectionCounts": {name: _studio_memory_count(name) for name in EXPERIENCE_STUDIO_MEMORY_COLLECTIONS},
    }


def experience_studio_readiness() -> dict[str, Any]:
    core = _studio_core_preset()
    memory = list_experience_studio_memory(limit=1)
    role_gate_enabled = str(os.getenv("PARKPULSE_ENFORCE_EXPERIENCE_STUDIO_ROLES", "")).strip().lower() in {"1", "true", "yes", "on"}
    return {
        "status": "ready" if memory.get("memoryConnection", {}).get("connected") or memory.get("memoryConnection", {}).get("primary") == "file_fallback" else "review",
        "mode": "experience_studio_production_readiness",
        "studioCore": {
            "id": core.get("id"),
            "version": core.get("version"),
            "source": core.get("source"),
            "configurableBy": "PARKPULSE_EXPERIENCE_STUDIO_CORE_PATH",
        },
        "memory": {
            "connection": memory.get("memoryConnection"),
            "counts": memory.get("collectionCounts"),
            "retentionPolicy": EXPERIENCE_STUDIO_RETENTION_POLICY,
            "fallbackAllowed": True,
        },
        "roleGate": {
            "enabled": role_gate_enabled,
            "env": "PARKPULSE_ENFORCE_EXPERIENCE_STUDIO_ROLES",
            "capabilities": {
                "read": "read_experience_studio",
                "draftAndSave": "use_experience_studio",
                "reviewAndHandoff": "review_experience_studio",
                "manageCore": "manage_experience_studio_core",
            },
        },
        "contracts": {
            "noFeedbackLoop": _memory_learning_policy()["humanFeedbackLearningEligible"] is False,
            "approvedRulePromotion": True,
            "approvedRuleAuthority": "human_promoted_rules_only",
            "llmControlAuthority": False,
            "notOperations": True,
            "publishingRequiresReview": True,
        },
    }


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


def list_experience_studio_learning_rules(limit: int = 30) -> dict[str, Any]:
    rows = _latest_studio_memory("experience_studio_learning_rules", max(1, min(limit, 100)))
    return {
        "status": "ready",
        "mode": "experience_studio_learning_rules",
        "rules": rows,
        "count": len(rows),
        "learningPolicy": _memory_learning_policy(),
    }


def _promotable_rule_candidates(record: dict[str, Any]) -> list[dict[str, Any]]:
    draft = record.get("draft") if isinstance(record.get("draft"), dict) else {}
    package = draft.get("creativePackage") if isinstance(draft.get("creativePackage"), dict) else {}
    synthesis = draft.get("creativeSynthesis") if isinstance(draft.get("creativeSynthesis"), dict) else package.get("creativeSynthesis") if isinstance(package.get("creativeSynthesis"), dict) else {}
    concept_name = str(synthesis.get("selectedConceptName") or (package.get("executiveConcept") or {}).get("name") or draft.get("title") or "approved concept")
    venue_pattern = package.get("venuePattern") if isinstance(package.get("venuePattern"), dict) else {}
    production = package.get("productionDetail") if isinstance(package.get("productionDetail"), dict) else {}
    memory = package.get("memoryInfluence") if isinstance(package.get("memoryInfluence"), dict) else {}
    must_include = _as_text_list(venue_pattern.get("mustInclude"))
    checklist = _as_text_list(production.get("contentCompletenessChecklist"))
    reusable = _as_text_list(memory.get("reusablePatterns"))
    return [
        {
            "id": "concept_continuity",
            "label": "Concept continuity",
            "rule": f"For {record.get('templateId')}, keep a named concept such as {concept_name} visible across final package, app, email, signage, and staff cue.",
            "lesson": "Finished packages are easier to review when the same named concept anchors every artifact.",
            "tags": ["concept", "channel_consistency"],
            "guardrails": ["selected concept identity can guide copy but cannot override route locks or Venue Profile facts"],
        },
        {
            "id": "route_requirements",
            "label": "Route requirements",
            "rule": f"For {record.get('templateId')}, include {', '.join(must_include[:4]) or 'explicit opt-out, current-options caveat, and owner review gates'} before a package is considered complete.",
            "lesson": "Finished routes need concrete proof points, not just story copy.",
            "tags": ["route", "review_readiness"],
            "guardrails": ["must-include items are review requirements, not live operational claims"],
        },
        {
            "id": "complete_package_shape",
            "label": "Complete package shape",
            "rule": f"For {record.get('templateId')}, generate a complete package checklist: {', '.join(checklist[:8]) or 'concept, journey, channels, accessibility, owner questions, memory receipt'}.",
            "lesson": "Experience Studio outputs improve when every section has a job, review gate, and owner-facing artifact.",
            "tags": ["package_completeness", "owner_review"],
            "guardrails": ["completion checklist does not mean publish readiness"],
        },
        {
            "id": "finished_memory_use",
            "label": "Finished memory use",
            "rule": reusable[0] if reusable else f"For {record.get('templateId')}, compare against approved finished packages before writing new copy.",
            "lesson": "Finished-work memory improves continuity without treating raw feedback as training data.",
            "tags": ["memory", "continuity"],
            "guardrails": ["only approved or ready_for_publish work can influence generation"],
        },
    ]


def promote_experience_studio_learning_rule(draft_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    requested_rule_id = str(payload.get("candidateId") or payload.get("ruleId") or "complete_package_shape")
    with _STORE_LOCK:
        record = next((item for item in _read_records() if isinstance(item, dict) and str(item.get("id")) == draft_id), None)
    if not record:
        return {"status": "not_found", "message": f"Draft {draft_id} was not found."}
    current_status = str(record.get("status") or "draft")
    if current_status not in FINISHED_WORK_STATUSES:
        return {
            "status": "blocked",
            "message": "Only approved or ready_for_publish drafts can promote reusable Experience Studio rules.",
            "currentDraftStatus": current_status,
            "requiredStatuses": sorted(FINISHED_WORK_STATUSES),
        }
    candidates = _promotable_rule_candidates(record)
    candidate = next((item for item in candidates if item["id"] == requested_rule_id), candidates[0])
    draft = record.get("draft") if isinstance(record.get("draft"), dict) else {}
    package = draft.get("creativePackage") if isinstance(draft.get("creativePackage"), dict) else {}
    channel_matrix = package.get("channelMatrix") if isinstance(package.get("channelMatrix"), list) else []
    channels = [str(item.get("channel")) for item in channel_matrix if isinstance(item, dict) and item.get("channel")]
    now = _now_iso()
    candidate_id = str(candidate["id"])
    rule_hash = hashlib.sha1(f"{draft_id}:{candidate_id}".encode("utf-8")).hexdigest()[:10]
    rule_id = f"exp_rule_{record.get('templateId')}_{candidate_id}_{rule_hash}"
    rule = {
        "_id": rule_id,
        "id": rule_id,
        "eventType": "learning_rule_promoted",
        "approvalStatus": "approved",
        "rule": str(payload.get("rule") or candidate["rule"]),
        "lesson": str(payload.get("lesson") or candidate["lesson"]),
        "sourceDraftId": draft_id,
        "sourceDraftStatus": current_status,
        "templateId": record.get("templateId"),
        "scope": {
            "templateId": record.get("templateId"),
            "audience": draft.get("audience"),
            "channels": channels,
        },
        "tags": _as_text_list(payload.get("tags")) or candidate["tags"],
        "guardrails": _as_text_list(payload.get("guardrails")) or candidate["guardrails"],
        "promotedBy": payload.get("actor") or "experience_reviewer",
        "promotionNote": _text(payload.get("note"), "Promoted from approved finished Experience Studio package."),
        "createdAt": now,
        "updatedAt": now,
        "learningEligible": False,
        "learningSource": "human_promoted_finished_work_rule",
        "learningPolicy": _memory_learning_policy(),
        "reversible": True,
    }
    memory = _record_studio_memory("experience_studio_learning_rules", rule)
    return {
        "status": "promoted",
        "mode": "experience_studio_learning_rule_promotion",
        "rule": rule,
        "candidate": candidate,
        "availableCandidates": candidates,
        "memoryPersistence": memory,
    }


def update_experience_studio_learning_rule(rule_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    next_status = str(payload.get("approvalStatus") or payload.get("status") or "demoted").strip().lower()
    if next_status not in {"approved", "demoted", "archived"}:
        return {"status": "invalid_status", "allowedStatuses": ["approved", "demoted", "archived"]}
    existing = next((row for row in _latest_studio_memory("experience_studio_learning_rules", 100) if str(row.get("id") or row.get("_id")) == rule_id), None)
    if not existing:
        return {"status": "not_found", "message": f"Learning rule {rule_id} was not found."}
    updated = {
        **existing,
        "_id": rule_id,
        "id": rule_id,
        "approvalStatus": next_status,
        "updatedAt": _now_iso(),
        "reviewedBy": payload.get("actor") or "experience_reviewer",
        "reviewNote": _text(payload.get("note"), f"Rule moved to {next_status}."),
        "learningEligible": False,
        "learningSource": "human_rule_review_receipt",
        "learningPolicy": _memory_learning_policy(),
    }
    memory = _record_studio_memory("experience_studio_learning_rules", updated)
    return {"status": "updated", "mode": "experience_studio_learning_rule_review", "rule": updated, "memoryPersistence": memory}


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
        "studioCore": _studio_core_preset(),
        "boundary": {
            "experience_studio_can": ["draft_route", "draft_copy", "review_brand_fit", "review_accessibility", "mark_publish_readiness"],
            "experience_studio_cannot": ["dispatch_staff", "change_queue", "publish_guest_message", "override_safety_policy", "alter_live_operations"],
            "handoff_rule": "Anything that changes live operations or guest-facing production systems must go through Command Center review.",
        },
    }


def _conversation_text(payload: dict[str, Any]) -> str:
    parts = [
        payload.get("message"),
        payload.get("prompt"),
        payload.get("request"),
        payload.get("conversation"),
        payload.get("designerIntent"),
    ]
    history = payload.get("history")
    if isinstance(history, list):
        for item in history:
            if isinstance(item, dict):
                parts.append(item.get("content") or item.get("message") or item.get("text"))
            else:
                parts.append(item)
    text = "\n".join(str(part or "").strip() for part in parts if str(part or "").strip())
    return text[:4000]


def _infer_conversation_template(text: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ("rainy-day", "rainy day", "rain journey", "rain route", "storm route")):
        return "rainy-day"
    if any(term in lowered for term in ("halloween route", "halloween event", "spooky route")):
        return "halloween-route"
    if any(term in lowered for term in ("kid quest", "child quest", "kids quest")):
        return "kid-quest"
    if any(term in lowered for term in ("low-sensory", "low sensory path", "lower-stimulus path")):
        return "low-sensory"
    if any(term in lowered for term in ("vip tour", "hosted tour", "premium tour")):
        return "vip-tour"
    scored = {
        "rainy-day": sum(1 for term in ("rain", "storm", "wet", "indoor", "covered", "shelter") if term in lowered),
        "low-sensory": sum(1 for term in ("low sensory", "sensory", "quiet", "autism", "calm", "decompression", "low-stimulation") if term in lowered),
        "kid-quest": sum(1 for term in ("kid", "child", "children", "quest", "badge", "mission", "family") if term in lowered),
        "scavenger-hunt": sum(1 for term in ("scavenger", "hunt", "clue", "find", "map") if term in lowered),
        "attraction-copy": sum(1 for term in ("description", "attraction copy", "rewrite attraction", "ride copy") if term in lowered),
        "safety-signage": sum(1 for term in ("safety", "sign", "signage", "instruction", "warning") if term in lowered),
        "vip-tour": sum(1 for term in ("vip", "premium", "host", "tour", "concierge") if term in lowered),
        "halloween-route": sum(1 for term in ("halloween", "spooky", "fall", "pumpkin", "mystery") if term in lowered),
    }
    explicit = max(scored.items(), key=lambda item: item[1])
    if explicit[1] > 0:
        return explicit[0]
    return "rainy-day"


def _infer_conversation_audience(text: str, template_id: str) -> str:
    lowered = text.lower()
    if "vip" in lowered or "premium" in lowered:
        return "VIP guests and hosted groups"
    if any(term in lowered for term in ("kid", "children", "ages 6", "ages six")):
        return "kids ages 6 to 10 with caregivers"
    if "family" in lowered or "families" in lowered:
        return "mixed family groups"
    if any(term in lowered for term in ("teen", "older kids")):
        return "families with older kids"
    if any(term in lowered for term in ("sensory", "autism", "quiet", "low-stimulation")):
        return "guests who prefer lower stimulation"
    template = TEMPLATES.get(template_id, TEMPLATES["rainy-day"])
    return {
        "rainy-day": "mixed family groups",
        "halloween-route": "families with older kids",
        "scavenger-hunt": "families and friend groups",
        "attraction-copy": "first-time guests planning their day",
        "safety-signage": "all guests",
        "vip-tour": "VIP guests and high-value groups",
    }.get(template_id, str(template.get("shortLabel") or "mixed guest groups"))


def _infer_conversation_tone(text: str, template_id: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ("calm", "gentle", "quiet", "sensory")):
        return "calm, plain, respectful"
    if any(term in lowered for term in ("spooky", "halloween", "mystery")):
        return "spooky, playful, never graphic"
    if any(term in lowered for term in ("premium", "vip", "polished")):
        return "polished, personal, confident"
    if any(term in lowered for term in ("kid", "quest", "badge", "mission")):
        return "curious, warm, adventurous"
    return {
        "rainy-day": "calm, helpful, upbeat",
        "safety-signage": "direct, calm, simple",
        "attraction-copy": "vivid, specific, accurate",
    }.get(template_id, "clear, warm, lightly themed")


def _conversation_goal(text: str, template_id: str) -> str:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if len(first_line) >= 18:
        return first_line[:220]
    return TEMPLATES.get(template_id, TEMPLATES["rainy-day"])["intent"]


def _phrase_after_terms(text: str, terms: tuple[str, ...], fallback: str = "") -> str:
    for term in terms:
        pattern = re.compile(rf"{re.escape(term)}\s*(?:is|are|:|-)?\s*([^.\n;]+)", re.IGNORECASE)
        match = pattern.search(text)
        if match:
            value = match.group(1).strip(" :,-")
            if value:
                return value[:180]
    return fallback


def _conversation_answer_context(text: str) -> dict[str, Any]:
    lowered = text.lower()
    success_metric = _phrase_after_terms(text, ("success metric", "improve", "goal"), "")
    if not success_metric:
        for label, terms in {
            "comfort": ("comfort", "guest comfort", "dry", "calm"),
            "underused-area discovery": ("underused", "discovery", "explore"),
            "pre-arrival clarity": ("pre-arrival", "email", "planning clarity"),
            "premium guest satisfaction": ("premium", "vip", "host satisfaction"),
            "dwell time": ("dwell", "linger"),
        }.items():
            if any(term in lowered for term in terms):
                success_metric = label
                break
    guest_commitment = _phrase_after_terms(text, ("guest commitment", "commitment", "duration", "journey length"), "")
    if not guest_commitment:
        if any(term in lowered for term in ("short", "5 minute", "ten minute", "10 minute", "quick")):
            guest_commitment = "short optional moment"
        elif any(term in lowered for term in ("20 minute", "twenty minute", "half hour", "30 minute")):
            guest_commitment = "20-minute route"
        elif any(term in lowered for term in ("full hosted", "hosted journey", "vip tour")):
            guest_commitment = "full hosted journey"
    approved_claims = []
    claim_terms = {
        "covered path": ("covered path", "covered route", "covered walk"),
        "indoor stop": ("indoor stop", "indoor stops", "inside stop"),
        "quiet zone": ("quiet zone", "quiet area", "quiet decompression"),
        "seating": ("seating", "benches", "seat"),
        "restroom proximity": ("restroom", "bathroom"),
        "step-free access": ("step-free", "accessible route", "wheelchair"),
    }
    for label, terms in claim_terms.items():
        if any(term in lowered for term in terms):
            approved_claims.append(label)
    reward_rule = _phrase_after_terms(text, ("reward", "reward rule", "fulfillment"), "")
    review_owner = _phrase_after_terms(text, ("review owner", "owner", "final review"), "")
    target_segment = _phrase_after_terms(text, ("guest segment", "target segment", "segment"), "")
    channel_target = _phrase_after_terms(text, ("channel target", "channels", "channel"), "")
    return {
        "successMetric": success_metric or "not answered",
        "guestCommitment": guest_commitment or "not answered",
        "approvedComfortClaims": approved_claims,
        "rewardRule": reward_rule or "not answered",
        "reviewOwner": review_owner or "not answered",
        "targetSegment": target_segment or "not answered",
        "channelTarget": channel_target or "not answered",
        "answeredQuestionIds": [
            question_id
            for question_id, answered in {
                "success_metric": success_metric,
                "guest_commitment": guest_commitment,
                "comfort_boundary": approved_claims,
                "reward_rule": reward_rule,
                "review_owner": review_owner,
                "target_segment": target_segment,
                "channel_target": channel_target,
            }.items()
            if bool(answered)
        ],
    }


def _conversation_missing_inputs(template_id: str, real_inputs: dict[str, Any], text: str) -> list[str]:
    missing = []
    if not real_inputs.get("locations"):
        missing.append("approved location names for the route or copy")
    if template_id in {"rainy-day", "low-sensory"} and not real_inputs.get("indoorLocations") and not real_inputs.get("quietLocations"):
        missing.append("verified indoor, covered, quiet, or decompression locations")
    if template_id in {"halloween-route", "kid-quest", "scavenger-hunt", "vip-tour"} and not _experience_rules(real_inputs):
        missing.append("experience rules such as kid-friendly anchors, themed candidates, or VIP anchors")
    if not real_inputs.get("accessibleRoutes"):
        missing.append("accessibility route facts and alternate-path notes")
    if not real_inputs.get("channelOwners"):
        missing.append("channel owners for app, signage, email, and staff cues")
    if "reward" in text.lower() and "reward approval" not in " ".join(missing).lower():
        missing.append("approved reward or fulfillment owner; otherwise keep rewards as placeholders")
    return missing


def _conversation_questions(template_id: str, missing: list[str], text: str, answer_context: dict[str, Any] | None = None, profile_prompts: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    template = TEMPLATES.get(template_id, TEMPLATES["rainy-day"])
    answered_ids = set(answer_context.get("answeredQuestionIds", []) if isinstance(answer_context, dict) else [])
    questions = [
        {
            "id": "success_metric",
            "question": "What should this experience improve: comfort, dwell time, underused-area discovery, pre-arrival clarity, or premium guest satisfaction?",
            "whyItMatters": "The answer changes route density, channel copy, and review priorities.",
        },
        {
            "id": "guest_commitment",
            "question": "How much guest commitment is acceptable: a short optional moment, a 20-minute route, or a full hosted journey?",
            "whyItMatters": "The planner needs a realistic pacing boundary before production review.",
        },
    ]
    if template_id in {"rainy-day", "low-sensory"}:
        questions.append(
            {
                "id": "comfort_boundary",
                "question": "Which comfort claims are already approved: covered path, indoor stop, quiet zone, seating, restroom proximity, or step-free access?",
                "whyItMatters": "Studio can only say these things if the Venue Profile supports them.",
            }
        )
    elif template_id in {"kid-quest", "scavenger-hunt", "halloween-route"}:
        questions.append(
            {
                "id": "reward_rule",
                "question": "Should the reward be a phrase, stamp, sticker placeholder, photo moment, or no reward until an owner approves fulfillment?",
                "whyItMatters": "The Studio must avoid inventing prizes, characters, or availability.",
            }
        )
    else:
        questions.append(
            {
                "id": "review_owner",
                "question": "Who owns final review for this package: brand, accessibility, safety, CRM, signage, or VIP operations?",
                "whyItMatters": "The output package should name the right owner before handoff.",
            }
        )
    questions.extend(profile_prompts or [])
    if missing:
        questions.append(
            {
                "id": "missing_profile_fact",
                "question": f"Can the Venue Profile supply {missing[0]}?",
                "whyItMatters": f"{template['label']} cannot become handoff-ready without this fact.",
            }
        )
    open_questions = [question for question in questions if question["id"] not in answered_ids]
    return open_questions[:5]


def _conversation_quality_rubric(template_id: str, missing: list[str]) -> list[dict[str, Any]]:
    source_ready = not missing
    return [
        {"id": "source_grounding", "label": "Source-grounded", "status": "pass" if source_ready else "review", "check": "Uses approved venue names and facts; placeholders remain visible when facts are missing."},
        {"id": "story_arc", "label": "Coherent story arc", "status": "pass", "check": "Has a clear beginning, middle, choice or reward beat, and close."},
        {"id": "guest_comfort", "label": "Guest comfort", "status": "pass", "check": "Includes optionality, pacing, sensory care, and accessible alternatives."},
        {"id": "ops_boundary", "label": "Operations boundary", "status": "pass", "check": "Does not dispatch, publish, promise availability, or change live operations."},
        {"id": "reviewability", "label": "Reviewable package", "status": "pass" if source_ready else "review", "check": "Names owner questions and separates guest copy from internal notes."},
    ]


ROUTE_PATTERN_BY_TEMPLATE = {
    "rainy-day": "rainy_day",
    "kid-quest": "kid_quest",
    "low-sensory": "low_sensory",
    "vip-tour": "vip_tour",
    "halloween-route": "halloween_route",
}


def _profile_route_pattern(real_inputs: dict[str, Any], template_id: str) -> tuple[str | None, dict[str, Any]]:
    rules = _experience_rules(real_inputs)
    route_patterns = rules.get("routePatterns") if isinstance(rules.get("routePatterns"), dict) else {}
    pattern_id = ROUTE_PATTERN_BY_TEMPLATE.get(template_id)
    pattern = route_patterns.get(pattern_id) if pattern_id and isinstance(route_patterns.get(pattern_id), dict) else {}
    return pattern_id, pattern


def _infer_channel_targets(text: str) -> list[str]:
    lowered = text.lower()
    targets = []
    channel_terms = {
        "guest_app": ("app", "mobile", "in-app"),
        "signage": ("sign", "signage", "wayfinding"),
        "email": ("email", "pre-arrival", "crm"),
        "staff_cue": ("staff", "host", "script", "cue"),
    }
    for channel, terms in channel_terms.items():
        if any(term in lowered for term in terms):
            targets.append(channel)
    return targets or ["guest_app", "signage", "email", "staff_cue"]


def _infer_guest_segment(real_inputs: dict[str, Any], audience: str, text: str) -> dict[str, Any]:
    segments = [item for item in real_inputs.get("guestSegments", []) if isinstance(item, dict)]
    haystack = f"{audience} {text}".lower()
    if not segments:
        return {}
    scored: list[tuple[int, dict[str, Any]]] = []
    for segment in segments:
        terms = [str(segment.get("id") or ""), str(segment.get("label") or "")]
        terms.extend(str(item) for item in segment.get("decisionDrivers", []) if str(item).strip()) if isinstance(segment.get("decisionDrivers"), list) else None
        terms.extend(str(item) for item in segment.get("storyNeeds", []) if str(item).strip()) if isinstance(segment.get("storyNeeds"), list) else None
        score = 0
        for term in terms:
            lowered_term = term.replace("_", " ").lower()
            if lowered_term and lowered_term in haystack:
                score += 3 if term in {segment.get("id"), segment.get("label")} else 1
        if "family" in haystack and "family" in str(segment.get("label") or "").lower():
            score += 2
        if "rain" in haystack and "rain" in str(segment.get("id") or "").lower():
            score += 3
        if "sensory" in haystack and "sensory" in str(segment.get("id") or "").lower():
            score += 3
        if "vip" in haystack and "vip" in str(segment.get("id") or "").lower():
            score += 3
        scored.append((score, segment))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1] if scored and scored[0][0] > 0 else segments[0]


def _planner_intelligence(template_id: str, audience: str, text: str, real_inputs: dict[str, Any]) -> dict[str, Any]:
    pattern_id, route_pattern = _profile_route_pattern(real_inputs, template_id)
    target_segment = _infer_guest_segment(real_inputs, audience, text)
    channel_targets = _infer_channel_targets(text)
    rules = _experience_rules(real_inputs)
    prompts = []
    if target_segment:
        prompts.append(
            {
                "id": "target_segment",
                "question": f"Should the plan optimize for {target_segment.get('label')} or a different guest segment?",
                "whyItMatters": "Segment choice changes pacing, language, bypasses, and owner review risk.",
            }
        )
    if route_pattern:
        prompts.append(
            {
                "id": "route_pattern",
                "question": f"Should the route follow the profile pattern {pattern_id}: {' -> '.join(str(item) for item in route_pattern.get('recommendedArc', [])[:5])}?",
                "whyItMatters": "The venue pattern gives the planner a stronger creative structure than generic route copy.",
            }
        )
    prompts.append(
        {
            "id": "channel_target",
            "question": f"Which channel should lead the package: {', '.join(channel_targets)} or a different channel?",
            "whyItMatters": "Channel priority changes copy length, review owner, and proof of value for the demo.",
        }
    )
    return {
        "targetSegment": {
            "id": target_segment.get("id"),
            "label": target_segment.get("label"),
            "decisionDrivers": target_segment.get("decisionDrivers", []),
            "storyNeeds": target_segment.get("storyNeeds", []),
            "avoid": target_segment.get("avoid", []),
        } if target_segment else {},
        "routePattern": {
            "id": pattern_id,
            "recommendedArc": route_pattern.get("recommendedArc", []) if isinstance(route_pattern.get("recommendedArc"), list) else [],
            "preferredStops": route_pattern.get("preferredStops", []) if isinstance(route_pattern.get("preferredStops"), list) else [],
            "mustInclude": route_pattern.get("mustInclude", []) if isinstance(route_pattern.get("mustInclude"), list) else [],
            "avoidClaims": route_pattern.get("avoidClaims", []) if isinstance(route_pattern.get("avoidClaims"), list) else [],
        },
        "channelTargets": channel_targets,
        "profileEvidence": {
            "experienceRuleKeys": sorted(_experience_rules(real_inputs).keys()),
            "hasRoutePattern": bool(route_pattern),
            "signatureStoryAnchorCount": len(rules.get("signatureStoryAnchors", [])) if isinstance(rules.get("signatureStoryAnchors"), list) else 0,
        },
        "refinementPrompts": prompts[:3],
    }


def _concept_options(template_id: str, audience: str, tone: str, real_inputs: dict[str, Any], missing: list[str], answer_context: dict[str, Any] | None = None, planner_intelligence: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    template = TEMPLATES.get(template_id, TEMPLATES["rainy-day"])
    answer_context = answer_context if isinstance(answer_context, dict) else {}
    planner_intelligence = planner_intelligence if isinstance(planner_intelligence, dict) else {}
    route_pattern = planner_intelligence.get("routePattern") if isinstance(planner_intelligence.get("routePattern"), dict) else {}
    target_segment = planner_intelligence.get("targetSegment") if isinstance(planner_intelligence.get("targetSegment"), dict) else {}
    channel_targets = planner_intelligence.get("channelTargets") if isinstance(planner_intelligence.get("channelTargets"), list) else []
    base_payload = {
        "templateId": template_id,
        "audience": audience,
        "tone": tone,
        "useVenueExperienceData": True,
        "useLlm": False,
        "useCreativeReasoning": False,
    }
    defaults = _creative_brief(base_payload, template_id)
    location_count = len(real_inputs.get("locations", []))
    guest_commitment = str(answer_context.get("guestCommitment") or "")
    commitment_pace = "compact" if any(term in guest_commitment.lower() for term in ("short", "quick")) else "exploratory" if "hosted" in guest_commitment.lower() else defaults.get("walkingPace", "moderate")
    route_arc = " -> ".join(str(item) for item in route_pattern.get("recommendedArc", [])[:5]) if route_pattern.get("recommendedArc") else defaults.get("storyArc", "")
    segment_label = target_segment.get("label") or audience
    channel_summary = ", ".join(str(item) for item in channel_targets[:4]) if channel_targets else "all core channels"
    return [
        {
            "id": "comfort_story",
            "label": "Comfort-led story route",
            "rationale": f"Best for {segment_label}; follows the venue pattern {route_arc or 'from the active profile'} with clear movement, optionality, and reviewable copy.",
            "risk": "Can feel conservative unless the creative pass adds sharper themed language.",
            "profileFit": {
                "routePatternId": route_pattern.get("id"),
                "mustInclude": route_pattern.get("mustInclude", []),
                "segmentNeeds": target_segment.get("storyNeeds", []),
                "channelTargets": channel_targets,
            },
            "payload": {**base_payload, **defaults, "creativeDirection": "comfort-first", "walkingPace": commitment_pace, "outputPackage": "full package", "planningProfile": planner_intelligence},
        },
        {
            "id": "signature_moments",
            "label": "Signature moments",
            "rationale": f"Uses {location_count or 'available'} profile locations as stronger story beats for a more memorable {template['shortLabel']} concept.",
            "risk": "Needs stronger owner review for rewards, photo moments, character references, and any availability claim.",
            "profileFit": {
                "routePatternId": route_pattern.get("id"),
                "preferredStops": route_pattern.get("preferredStops", []),
                "segmentNeeds": target_segment.get("storyNeeds", []),
                "channelTargets": channel_targets,
            },
            "payload": {**base_payload, **defaults, "creativeDirection": "story-rich", "sensoryLevel": "balanced", "walkingPace": commitment_pace, "outputPackage": "full package", "planningProfile": planner_intelligence},
        },
        {
            "id": "low_friction_channel_pack",
            "label": "Low-friction channel pack",
            "rationale": f"Best for a hackathon demo because it produces {channel_summary} artifacts that visibly connect to the same brief and profile pattern.",
            "risk": "Less theatrical than a full route unless paired with one approved hero moment.",
            "profileFit": {
                "routePatternId": route_pattern.get("id"),
                "channelTargets": channel_targets,
                "channelRules": _experience_rules(real_inputs).get("channelArtifactRules", {}),
                "avoidClaims": route_pattern.get("avoidClaims", []),
            },
            "payload": {**base_payload, **defaults, "creativeDirection": defaults.get("creativeDirection", "comfort-first"), "walkingPace": "compact", "outputPackage": "channel copy" if template_id in {"safety-signage", "attraction-copy"} else "full package", "planningProfile": planner_intelligence},
        },
    ]


def _recommended_option_index(text: str, missing: list[str], answer_context: dict[str, Any]) -> int:
    lowered = text.lower()
    success_metric = str(answer_context.get("successMetric") or "").lower()
    commitment = str(answer_context.get("guestCommitment") or "").lower()
    if missing:
        return 0
    if any(term in lowered or term in success_metric for term in ("channel", "signage", "email", "pre-arrival", "clarity", "hackathon demo")):
        return 2
    if any(term in lowered or term in success_metric or term in commitment for term in ("signature", "memorable", "theatrical", "hosted", "vip", "premium")):
        return 1
    return 0 if any(term in lowered or term in success_metric for term in ("comfort", "calm", "simple", "quiet")) else 1


def build_experience_studio_conversation_plan(payload: dict[str, Any]) -> dict[str, Any]:
    request_text = _conversation_text(payload)
    if not request_text:
        request_text = "Create a guest journey package from the active Venue Profile."
    template_id = str(payload.get("templateId") or payload.get("template") or _infer_conversation_template(request_text))
    if template_id not in TEMPLATES:
        template_id = _infer_conversation_template(request_text)
    audience = _text(payload.get("audience"), _infer_conversation_audience(request_text, template_id))
    tone = _text(payload.get("tone"), _infer_conversation_tone(request_text, template_id))
    constraints = _text(
        payload.get("constraints"),
        "Use verified venue facts only. Keep movement optional. Treat rewards, staffing, safety, access, weather, and availability claims as review items.",
    )
    venue_experience_data = None
    working_payload = dict(payload)
    working_payload.update({"templateId": template_id, "audience": audience, "tone": tone, "constraints": constraints})
    if payload.get("useVenueExperienceData", True) is not False:
        try:
            from venue_experience_data import resolve_experience_studio_real_inputs

            working_payload, venue_experience_data = resolve_experience_studio_real_inputs(working_payload)
        except Exception as error:
            venue_experience_data = {
                "status": "error",
                "mode": "venue_experience_data",
                "readiness": {"status": "blocked", "issues": [{"id": "venue_experience_data_load_failed", "detail": str(error)[:240]}]},
            }
    real_inputs = _real_inputs(working_payload)
    missing = _conversation_missing_inputs(template_id, real_inputs, request_text)
    answer_context = _conversation_answer_context(request_text)
    planner_intelligence = _planner_intelligence(template_id, audience, request_text, real_inputs)
    options = _concept_options(template_id, audience, tone, real_inputs, missing, answer_context, planner_intelligence)
    recommended_index = _recommended_option_index(request_text, missing, answer_context)
    recommended = options[recommended_index]
    goal = _conversation_goal(request_text, template_id)
    context_constraints = [
        constraints,
        f"Success metric: {answer_context['successMetric']}.",
        f"Guest commitment: {answer_context['guestCommitment']}.",
    ]
    if answer_context.get("approvedComfortClaims"):
        context_constraints.append(f"Approved comfort claims: {', '.join(str(item) for item in answer_context['approvedComfortClaims'])}.")
    if answer_context.get("rewardRule") != "not answered":
        context_constraints.append(f"Reward rule: {answer_context['rewardRule']}.")
    if answer_context.get("reviewOwner") != "not answered":
        context_constraints.append(f"Review owner: {answer_context['reviewOwner']}.")
    next_payload = {
        **recommended["payload"],
        "constraints": "\n".join(context_constraints),
        "seasonalTheme": goal,
        "useVenueExperienceData": True,
        "useRealParkContext": False,
    }
    if "realInputs" in working_payload:
        next_payload["realInputs"] = working_payload["realInputs"]
    plan = {
        "id": f"exp_plan_{uuid.uuid4().hex[:12]}",
        "status": "ready",
        "mode": "experience_studio_conversation_plan",
        "createdAt": _now_iso(),
        "request": request_text,
        "parsedBrief": {
            "templateId": template_id,
            "templateLabel": TEMPLATES[template_id]["label"],
            "goal": goal,
            "audience": audience,
            "tone": tone,
            "constraints": constraints,
            "successMetric": answer_context["successMetric"],
            "guestCommitment": answer_context["guestCommitment"],
            "approvedComfortClaims": answer_context["approvedComfortClaims"],
            "rewardRule": answer_context["rewardRule"],
            "reviewOwner": answer_context["reviewOwner"],
            "targetSegment": planner_intelligence.get("targetSegment", {}).get("label") if isinstance(planner_intelligence.get("targetSegment"), dict) else None,
            "channelTargets": planner_intelligence.get("channelTargets", []),
            "source": "conversation_plus_active_venue_profile",
        },
        "planningMode": "clarify_then_generate" if missing else "generate_ready",
        "missingInputs": missing,
        "answeredQuestionIds": answer_context["answeredQuestionIds"],
        "clarifyingQuestions": _conversation_questions(template_id, missing, request_text, answer_context, planner_intelligence.get("refinementPrompts", [])),
        "plannerIntelligence": planner_intelligence,
        "conceptOptions": options,
        "recommendedOptionId": recommended["id"],
        "recommendedPlan": {
            "label": recommended["label"],
            "why": recommended["rationale"],
            "payload": next_payload,
        },
        "qualityRubric": _conversation_quality_rubric(template_id, missing),
        "studioCore": _studio_core_preset(),
        "venueExperienceData": venue_experience_data,
        "sourceIntegrity": {
            "usesSeedData": False,
            "usesSimulatedParkState": False,
            "usesInventedLocations": False,
            "venueExperienceDataAttached": bool(venue_experience_data),
            "realInputSource": real_inputs.get("source"),
            "realInputCount": len(real_inputs.get("locations", [])) + len(real_inputs.get("indoorLocations", [])) + len(real_inputs.get("quietLocations", [])),
            "missingRealInputs": missing,
        },
        "controlBoundary": {
            "surface": "Experience Studio",
            "layer": "Studio Layer",
            "category": "conversational_creative_planning",
            "llm_control_authority": False,
            "publishing_requires_review": True,
            "not_operations": True,
        },
    }
    memory = _record_studio_memory(
        "experience_studio_generation_runs",
        {
            "_id": plan["id"],
            "eventType": "conversation_plan",
            "templateId": template_id,
            "audience": audience,
            "parsedBrief": plan["parsedBrief"],
            "missingInputs": missing,
            "recommendedOptionId": recommended["id"],
            "studioCore": plan["studioCore"],
            "learningEligible": False,
            "learningSource": "conversation_plan_receipt_only",
            "learningPolicy": _memory_learning_policy(),
        },
    )
    return {**plan, "memoryPersistence": memory}


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
    memory = _record_studio_memory(
        "experience_studio_drafts",
        {
            "_id": f"exp_draft_{record['id']}",
            "eventType": "draft_saved",
            "draftId": record["id"],
            "templateId": record.get("templateId"),
            "status": record.get("status"),
            "summary": _compact_record(record),
            "route": _route_summary(draft),
            "creativeFingerprint": _creative_fingerprint(draft),
            "sourceIntegrity": draft.get("sourceIntegrity", {}),
            "reviewStatuses": _review_status_summary(draft),
            "learningEligible": False,
            "learningSource": "saved_draft_receipt",
            "learningPolicy": _memory_learning_policy(),
        },
    )
    return {"status": "saved", "mode": "experience_studio_saved_draft", "draftRecord": record, "summary": _compact_record(record), "memoryPersistence": memory}


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
            previous_status = str(record.get("status") or "draft")
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
            feedback_memory = _record_studio_memory(
                "experience_studio_feedback",
                {
                    "_id": f"exp_feedback_{draft_id}_{uuid.uuid4().hex[:8]}",
                    "eventType": "draft_status_review",
                    "draftId": draft_id,
                    "reviewStatus": next_status,
                    "actor": payload.get("actor") or "experience_reviewer",
                    "note": _text(payload.get("note"), f"Moved to {next_status}."),
                    "templateId": record.get("templateId"),
                    "creativeFingerprint": _creative_fingerprint(record.get("draft", {}) if isinstance(record.get("draft"), dict) else {}),
                    "learningEligible": False,
                    "learningSource": "human_review_receipt_only",
                    "learningPolicy": _memory_learning_policy(),
                },
            )
            revision_memory = _record_studio_memory(
                "experience_studio_revision_events",
                {
                    "_id": f"exp_revision_status_{draft_id}_{uuid.uuid4().hex[:8]}",
                    "eventType": "status_changed",
                    "draftId": draft_id,
                    "fromStatus": previous_status,
                    "toStatus": next_status,
                    "actor": payload.get("actor") or "experience_reviewer",
                    "learningEligible": False,
                    "learningSource": "workflow_receipt",
                },
            )
            return {"status": "updated", "mode": "experience_studio_review_state", "draftRecord": record, "summary": _compact_record(record), "memoryPersistence": {"feedback": feedback_memory, "revision": revision_memory}}
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
            revision_memory = _record_studio_memory(
                "experience_studio_revision_events",
                {
                    "_id": f"exp_revision_content_{draft_id}_{uuid.uuid4().hex[:8]}",
                    "eventType": "content_updated",
                    "draftId": draft_id,
                    "actor": payload.get("actor") or "experience_designer",
                    "note": _text(payload.get("note"), "Draft content updated."),
                    "status": record.get("status", "draft"),
                    "creativeFingerprint": _creative_fingerprint(record.get("draft", {}) if isinstance(record.get("draft"), dict) else {}),
                    "route": _route_summary(incoming_draft),
                    "sourceIntegrity": integrity,
                    "reviewStatuses": _review_status_summary(incoming_draft),
                    "learningEligible": False,
                    "learningSource": "revision_receipt",
                    "learningPolicy": _memory_learning_policy(),
                },
            )
            return {
                "status": "updated",
                "mode": "experience_studio_draft_content",
                "draftRecord": record,
                "summary": _compact_record(record),
                "memoryPersistence": revision_memory,
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
            handoff_memory = _record_studio_memory(
                "experience_studio_revision_events",
                {
                    "_id": f"exp_handoff_{handoff['id']}",
                    "eventType": "handoff_created",
                    "draftId": draft_id,
                    "handoffId": handoff["id"],
                    "handoffStatus": handoff.get("status"),
                    "requiresCommandCenterReview": handoff.get("requiresCommandCenterReview"),
                    "operationalReviewReasons": handoff.get("operationalReviewReasons", []),
                    "summary": _compact_handoff(record, handoff),
                    "learningEligible": False,
                    "learningSource": "handoff_receipt",
                    "learningPolicy": _memory_learning_policy(),
                },
            )
            return {
                "status": "created",
                "mode": "experience_studio_command_center_handoff",
                "handoff": handoff,
                "summary": _compact_handoff(record, handoff),
                "draftSummary": _compact_record(record),
                "memoryPersistence": handoff_memory,
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
                feedback_memory = _record_studio_memory(
                    "experience_studio_feedback",
                    {
                        "_id": f"exp_handoff_feedback_{handoff_id}_{uuid.uuid4().hex[:8]}",
                        "eventType": "handoff_status_review",
                        "draftId": record.get("id"),
                        "handoffId": handoff_id,
                        "reviewStatus": next_status,
                        "actor": payload.get("actor") or "command_center",
                        "note": handoff["commandCenterNote"],
                        "learningEligible": False,
                        "learningSource": "command_center_review_receipt_only",
                        "learningPolicy": _memory_learning_policy(),
                    },
                )
                return {
                    "status": "updated",
                    "mode": "experience_studio_command_center_handoff_review",
                    "handoff": handoff,
                    "summary": _compact_handoff(record, handoff),
                    "draftSummary": _compact_record(record),
                    "memoryPersistence": feedback_memory,
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
    readiness = intelligence.get("readiness") if isinstance(intelligence.get("readiness"), dict) else {}
    venue = real_inputs.get("venueIdentity", {}) if isinstance(real_inputs.get("venueIdentity"), dict) else {}
    profile_type = str(venue.get("profileType") or "")
    production_missing = _as_text_list(readiness.get("missingForRealVenueReady"))
    if profile_type == "synthetic_approved":
        production_missing.extend(
            [
                "real venue source feed instead of approved synthetic profile",
                "live attraction closure/current-options feed",
                "current indoor, sheltered, and blocked-path status",
                "approved physical signage placement inventory",
                "channel-owner approved CRM/app/staff language templates",
            ]
        )
    return {
        "usesSeedData": False,
        "usesSimulatedParkState": False,
        "usesInventedLocations": False,
        "usesApprovedSyntheticProfile": profile_type == "synthetic_approved",
        "profileType": profile_type or "unknown",
        "parkContextSource": context.get("source"),
        "realInputSource": real_inputs.get("source"),
        "realInputCount": len(real_inputs.get("locations", [])) + len(real_inputs.get("indoorLocations", [])) + len(real_inputs.get("quietLocations", [])) + len(real_inputs.get("accessibleRoutes", [])) + len(real_inputs.get("safetyInstructions", [])),
        "profileIntelligenceAttached": bool(intelligence),
        "profileIntelligenceStatus": readiness.get("status") or "unknown",
        "profileIntelligenceQualityGaps": quality_gaps,
        "realVenueReady": bool(readiness.get("realVenueReady") and profile_type != "synthetic_approved"),
        "productionRealVenueReady": bool(readiness.get("realVenueReady") and profile_type != "synthetic_approved" and not production_missing),
        "missingProductionRealVenueInputs": list(dict.fromkeys(production_missing + quality_gaps)),
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
    studio_core = _studio_core_preset()
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
            "step": "studio_core_preset",
            "summary": "The draft uses a fixed Studio Core preset before LLM polish: guest comfort, accessibility, family-safe imagination, operational humility, source-grounded specificity, and reviewable craft.",
            "inputs": {
                "presetId": studio_core.get("id"),
                "version": studio_core.get("version"),
                "coreValues": studio_core.get("coreValues", []),
                "reasoningPriorities": studio_core.get("reasoningPriorities", []),
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
    creative_synthesis = deterministic_draft.get("creativeSynthesis") if isinstance(deterministic_draft.get("creativeSynthesis"), dict) else {}
    selected_concept = creative_synthesis.get("selectedConcept") if isinstance(creative_synthesis.get("selectedConcept"), dict) else {}
    finished_memory = deterministic_draft.get("finishedWorkMemory") if isinstance(deterministic_draft.get("finishedWorkMemory"), dict) else {}
    approved_rules = deterministic_draft.get("approvedLearningRules") if isinstance(deterministic_draft.get("approvedLearningRules"), dict) else {}
    return {
        "task": "Improve a ParkPulse Experience Studio draft as a creative writing pass after verified route and concept selection.",
        "return_only_json": True,
        "studio_core_preset": _studio_core_preset(),
        "hard_constraints": [
            "Apply the Studio Core preset before style choices.",
            "Keep the exact stop names, stop count, and stop order.",
            "Keep the selected creative concept id and selected creative concept name exactly as provided.",
            "Only rewrite purpose, guestCopy, staffNote, message copy, selected concept positioning, selected concept guestPromise, selected concept whyItWorks, channel copy variants, creative_rationale, and review_questions.",
            "Do not invent places, characters, live availability, wait times, weather, staffing, safety instructions, discounts, guarantees, or access-lane claims.",
            "Do not promise a specific reward item; keep rewards reviewable.",
            "Keep movement optional and reviewable.",
            "Use the selected concept as the creative container; do not create a fourth concept.",
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
        "locked_creative_synthesis": {
            "selectedConceptId": creative_synthesis.get("selectedConceptId"),
            "selectedConceptName": creative_synthesis.get("selectedConceptName"),
            "selectedConcept": {
                "id": selected_concept.get("id"),
                "name": selected_concept.get("name"),
                "positioning": selected_concept.get("positioning"),
                "guestPromise": selected_concept.get("guestPromise"),
                "heroTerms": selected_concept.get("heroTerms", []),
                "route": selected_concept.get("route", []),
                "reviewRisks": selected_concept.get("reviewRisks", []),
            },
            "copyVariants": creative_synthesis.get("copyVariants", {}),
            "rewriteStrategy": creative_synthesis.get("rewriteStrategy", {}),
        },
        "finished_work_memory_context": {
            "status": finished_memory.get("status"),
            "mode": finished_memory.get("mode"),
            "reusablePatterns": finished_memory.get("reusablePatterns", []),
            "avoidPatterns": finished_memory.get("avoidPatterns", []),
            "learningBoundary": finished_memory.get("learningBoundary"),
        },
        "approved_learning_rules": {
            "status": approved_rules.get("status"),
            "mode": approved_rules.get("mode"),
            "appliedRules": approved_rules.get("appliedRules", []),
            "guardrails": approved_rules.get("guardrails", []),
            "learningBoundary": approved_rules.get("learningBoundary"),
            "authority": "human_promoted_rules_only",
        },
        "messages": deterministic_draft.get("messages", []),
        "state_context_source": state_context.get("source"),
        "return_json_shape": {
            "route": [{"stop": item.get("stop"), "purpose": "...", "guestCopy": "...", "staffNote": "..."} for item in route_contract],
            "messages": deterministic_draft.get("messages", []),
            "creative_synthesis": {
                "selectedConceptId": creative_synthesis.get("selectedConceptId"),
                "selectedConceptName": creative_synthesis.get("selectedConceptName"),
                "selectedConcept": {
                    "id": selected_concept.get("id"),
                    "name": selected_concept.get("name"),
                    "positioning": "richer positioning, same concept identity",
                    "guestPromise": "richer promise, no guarantees",
                    "whyItWorks": "why this concept works for the guest and review flow",
                },
                "copyVariants": {
                    "guestApp": {"headline": "...", "body": "...", "microcopy": "..."},
                    "signage": [{"placement": "same placement as input", "headline": "...", "body": "..."}],
                    "email": {"subject": "...", "previewText": "...", "body": "..."},
                    "staffCue": {"opening": "...", "transition": "...", "boundary": "..."},
                },
                "rewriteStrategy": {"useMoreOf": ["..."], "preserve": ["..."], "avoid": ["..."]},
            },
            "creative_rationale": ["why this route works"],
            "review_questions": ["short review questions"],
        },
    }


def _blocked_claim_terms(real_inputs: dict[str, Any]) -> list[str]:
    brand_bible = _brand_bible(real_inputs)
    policy = _module_policy(real_inputs, "experience_studio")
    terms = _as_text_list(brand_bible.get("bannedClaims")) + _as_text_list(policy.get("neverClaim"))
    terms.extend(["guaranteed", "guarantee", "no wait", "always available", "priority access", "backstage access", "ada compliant", "allergen-free"])
    return list(dict.fromkeys(term.lower() for term in terms if term))


def _creative_text_rejection_reason(value: Any, real_inputs: dict[str, Any], max_chars: int = 520) -> str | None:
    text = str(value or "").strip()
    if not text:
        return "empty"
    if len(text) > max_chars:
        return "too_long"
    lowered = text.lower()
    blocked = next((term for term in _blocked_claim_terms(real_inputs) if term and term in lowered), "")
    if blocked:
        return f"blocked_claim:{blocked}"
    if any(term in lowered for term in ("dispatch ", "reroute staff", "open the ride", "close the ride", "skip the line")):
        return "operational_control_claim"
    return None


def _safe_creative_text(value: Any, real_inputs: dict[str, Any], rejected: list[dict[str, str]], field: str, max_chars: int = 520) -> str | None:
    reason = _creative_text_rejection_reason(value, real_inputs, max_chars=max_chars)
    if reason:
        if reason != "empty":
            rejected.append({"field": field, "reason": reason})
        return None
    return str(value).strip()


def _merge_generated_creative_synthesis(merged: dict[str, Any], generated: dict[str, Any], real_inputs: dict[str, Any]) -> tuple[int, list[dict[str, str]]]:
    base_synthesis = merged.get("creativeSynthesis") if isinstance(merged.get("creativeSynthesis"), dict) else {}
    generated_synthesis = generated.get("creative_synthesis") if isinstance(generated.get("creative_synthesis"), dict) else generated.get("creativeSynthesis") if isinstance(generated.get("creativeSynthesis"), dict) else {}
    if not base_synthesis or not generated_synthesis:
        return 0, []

    accepted = 0
    rejected: list[dict[str, str]] = []
    base_concept_id = str(base_synthesis.get("selectedConceptId") or "")
    base_concept_name = str(base_synthesis.get("selectedConceptName") or "")
    generated_concept_id = str(generated_synthesis.get("selectedConceptId") or base_concept_id)
    generated_concept_name = str(generated_synthesis.get("selectedConceptName") or base_concept_name)
    if generated_concept_id != base_concept_id or generated_concept_name != base_concept_name:
        rejected.append({"field": "creative_synthesis.identity", "reason": "selected_concept_identity_locked"})
        base_synthesis["llmPolish"] = {
            "status": "identity_rejected",
            "acceptedFields": 0,
            "rejectedFields": rejected,
            "guardrails": ["selected_concept_identity_locked"],
        }
        return 0, rejected

    selected = base_synthesis.get("selectedConcept") if isinstance(base_synthesis.get("selectedConcept"), dict) else {}
    generated_selected = generated_synthesis.get("selectedConcept") if isinstance(generated_synthesis.get("selectedConcept"), dict) else {}
    if str(generated_selected.get("id") or selected.get("id") or "") != str(selected.get("id") or "") or str(generated_selected.get("name") or selected.get("name") or "") != str(selected.get("name") or ""):
        rejected.append({"field": "creative_synthesis.selectedConcept", "reason": "selected_concept_identity_locked"})
    else:
        for field, max_chars in (("positioning", 360), ("guestPromise", 360), ("whyItWorks", 360)):
            value = _safe_creative_text(generated_selected.get(field), real_inputs, rejected, f"creative_synthesis.selectedConcept.{field}", max_chars)
            if value:
                selected[field] = value
                accepted += 1

    copy_variants = base_synthesis.get("copyVariants") if isinstance(base_synthesis.get("copyVariants"), dict) else {}
    generated_variants = generated_synthesis.get("copyVariants") if isinstance(generated_synthesis.get("copyVariants"), dict) else {}
    guest_app = copy_variants.get("guestApp") if isinstance(copy_variants.get("guestApp"), dict) else {}
    generated_guest_app = generated_variants.get("guestApp") if isinstance(generated_variants.get("guestApp"), dict) else {}
    for field, max_chars in (("headline", 80), ("body", 240), ("microcopy", 120)):
        value = _safe_creative_text(generated_guest_app.get(field), real_inputs, rejected, f"creative_synthesis.copyVariants.guestApp.{field}", max_chars)
        if value:
            guest_app[field] = value
            accepted += 1

    email = copy_variants.get("email") if isinstance(copy_variants.get("email"), dict) else {}
    generated_email = generated_variants.get("email") if isinstance(generated_variants.get("email"), dict) else {}
    for field, max_chars in (("subject", 90), ("previewText", 160), ("body", 520)):
        value = _safe_creative_text(generated_email.get(field), real_inputs, rejected, f"creative_synthesis.copyVariants.email.{field}", max_chars)
        if value:
            email[field] = value
            accepted += 1

    staff_cue = copy_variants.get("staffCue") if isinstance(copy_variants.get("staffCue"), dict) else {}
    generated_staff_cue = generated_variants.get("staffCue") if isinstance(generated_variants.get("staffCue"), dict) else {}
    for field, max_chars in (("opening", 180), ("transition", 220), ("boundary", 180)):
        value = _safe_creative_text(generated_staff_cue.get(field), real_inputs, rejected, f"creative_synthesis.copyVariants.staffCue.{field}", max_chars)
        if value:
            staff_cue[field] = value
            accepted += 1

    signage = copy_variants.get("signage") if isinstance(copy_variants.get("signage"), list) else []
    generated_signage = generated_variants.get("signage") if isinstance(generated_variants.get("signage"), list) else []
    if signage and generated_signage and len(signage) == len(generated_signage):
        for index, (base_item, generated_item) in enumerate(zip(signage, generated_signage, strict=False)):
            if not isinstance(base_item, dict) or not isinstance(generated_item, dict):
                continue
            if str(base_item.get("placement") or "") != str(generated_item.get("placement") or ""):
                rejected.append({"field": f"creative_synthesis.copyVariants.signage.{index}.placement", "reason": "placement_locked"})
                continue
            headline = _safe_creative_text(generated_item.get("headline"), real_inputs, rejected, f"creative_synthesis.copyVariants.signage.{index}.headline", 42)
            body = _safe_creative_text(generated_item.get("body"), real_inputs, rejected, f"creative_synthesis.copyVariants.signage.{index}.body", 120)
            if headline:
                base_item["headline"] = headline
                accepted += 1
            if body:
                base_item["body"] = body
                accepted += 1

    rewrite = base_synthesis.get("rewriteStrategy") if isinstance(base_synthesis.get("rewriteStrategy"), dict) else {}
    generated_rewrite = generated_synthesis.get("rewriteStrategy") if isinstance(generated_synthesis.get("rewriteStrategy"), dict) else {}
    for field in ("useMoreOf", "preserve", "avoid"):
        terms = []
        for item in _as_text_list(generated_rewrite.get(field))[:6]:
            if not _creative_text_rejection_reason(item, real_inputs, max_chars=80):
                terms.append(item)
        if terms:
            rewrite[field] = terms
            accepted += 1

    base_synthesis["selectedConcept"] = selected
    base_synthesis["copyVariants"] = copy_variants
    base_synthesis["rewriteStrategy"] = rewrite
    base_synthesis["llmPolish"] = {
        "status": "merged" if accepted else "no_safe_fields",
        "acceptedFields": accepted,
        "rejectedFields": rejected,
        "guardrails": ["selected_concept_identity_locked", "copy_claims_checked", "signage_placements_locked", "package_rebuilt_after_polish"],
    }
    return accepted, rejected


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
            if copy and not _creative_text_rejection_reason(copy, real_inputs, max_chars=640):
                base_item["copy"] = copy

    synthesis_accepted, synthesis_rejected = _merge_generated_creative_synthesis(merged, generated, real_inputs)

    intelligence = _profile_intelligence(real_inputs)
    quality_gaps = [str(item) for item in intelligence.get("qualityGaps", []) if str(item).strip()] if isinstance(intelligence.get("qualityGaps"), list) else []
    creative_brief = merged.get("creativeBrief") if isinstance(merged.get("creativeBrief"), dict) else {}
    template = TEMPLATES.get(template_id, TEMPLATES["halloween-route"])
    audience = _text(merged.get("audience"), "mixed guest groups")
    learning_context = merged.get("approvedLearningRules") if isinstance(merged.get("approvedLearningRules"), dict) else _learning_rule_context(template_id, audience)
    merged["creativePackage"] = _creative_package(
        base_route,
        base_messages,
        template_id,
        template,
        audience,
        _text(creative_brief.get("tone"), "clear, themed, guest-safe"),
        constraints,
        creative_brief,
        real_inputs,
        intelligence,
        quality_gaps,
        merged.get("experienceReasoning") if isinstance(merged.get("experienceReasoning"), dict) else {},
        merged.get("creativeSynthesis") if isinstance(merged.get("creativeSynthesis"), dict) else {},
        merged.get("finishedWorkMemory") if isinstance(merged.get("finishedWorkMemory"), dict) else _finished_work_memory_context(template_id, _text(merged.get("audience"), "mixed guest groups")),
        learning_context,
    )
    merged["sourceIntegrity"] = _source_integrity(base_route, real_inputs, context, intelligence, quality_gaps)
    merged["studioReview"] = _studio_review(template_id, merged, constraints, real_inputs)
    merged["llmCreativePass"] = {
        "status": "merged" if accepted_route else "route_rejected_preserved_deterministic",
        "routeAccepted": accepted_route,
        "synthesisAcceptedFields": synthesis_accepted,
        "synthesisRejectedFields": synthesis_rejected,
        "creativeRationale": generated.get("creative_rationale", []) if isinstance(generated.get("creative_rationale"), list) else [],
        "reviewQuestions": generated.get("review_questions", []) if isinstance(generated.get("review_questions"), list) else [],
        "guardrails": ["verified_stop_names_locked", "selected_concept_identity_locked", "source_integrity_recomputed", "reviewers_rerun", "package_rebuilt_after_polish"],
    }
    return merged


def _rainy_day_stop_copy(stop: str, index: int, stage: str, audience: str, tone: str, pace: str, detail: dict[str, Any], detail_phrase: str) -> tuple[str, str]:
    stop_lower = stop.lower()
    detail_sentence = f" Profile fact: {detail_phrase}." if detail_phrase else ""
    if index == 0:
        return (
            f"{stage}: reset arrival energy, name the dry route, and give {audience} a simple first choice.",
            f"{index + 1}. Start dry at {stop}. Open the route with one calm promise: stay comfortable, keep choices optional, and use the next indoor marker when the weather interrupts the day.{detail_sentence}",
        )
    if "arcade" in stop_lower:
        return (
            f"{stage}: turn waiting out the rain into a flexible discovery beat with no purchase or play requirement.",
            f"{index + 1}. Step into {stop} for a choose-your-own pause. Look for the next dry-route marker, take a short reset, or skip ahead if the space feels too active.{detail_sentence}",
        )
    if "theater" in stop_lower or "show" in stop_lower:
        return (
            f"{stage}: create the warm pause where families can sit, reorient, and decide the next move.",
            f"{index + 1}. Use {stop} as the quiet middle beat. Invite guests to sit, check the app, and choose whether to continue the route or stay with the lower-stimulation option.{detail_sentence}",
        )
    if "food" in stop_lower or "court" in stop_lower or "treat" in stop_lower:
        if index >= 4:
            return (
                f"{stage}: close the journey with a practical covered finish and a clear next-step handoff.",
                f"{index + 1}. Finish at {stop} with a covered regroup. Remind guests that this is a comfort route, not a schedule guarantee, and point them to the app for current next options.{detail_sentence}",
            )
        return (
            f"{stage}: offer a flexible choice point where the group can warm up, eat, or continue without pressure.",
            f"{index + 1}. Pause at {stop}. Give families permission to use this as a snack stop, seating reset, or easy bypass before the final covered close.{detail_sentence}",
        )
    return (
        f"{stage}: shape a {tone} rainy-day beat with a {pace} pace and a clear optional exit.",
        f"{index + 1}. Move to {stop} for the next dry-route beat. Keep the cue simple: follow the indoor marker, pause if needed, and choose the next comfortable stop.{detail_sentence}",
    )


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
        rainy_purpose, guest_copy = _rainy_day_stop_copy(stop, index, stage, audience, tone, pace, detail, detail_phrase)
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
        "purpose": rainy_purpose if template_id == "rainy-day" else kid_purpose if template_id == "kid-quest" else f"{stage}: shape a {direction} beat at {sensory_level} sensory level.",
        "guestCopy": f"{step}. Real location required before guest copy can be finalized. Intended tone: {tone}. {context_hint}" if needs_real_location else guest_copy.strip(),
        "staffNote": "Do not stage staff from this draft until the real location and owner are supplied." if needs_real_location else kid_staff_note if template_id == "kid-quest" else "Welcome guests, name the journey, and confirm the route is optional." if step == 1 else "Keep the handoff short and point guests toward the next visual landmark.",
        "accessibilityNote": "Real route accessibility facts are required before approval." if needs_real_location else _accessibility_for_stop(template_id, detail, real_inputs),
        "profileIntelligenceNote": "Real profile intelligence required before this stop can be finalized." if needs_real_location else intelligence_note or "Follow module policy; avoid live availability, staffing, safety, and access-lane claims.",
        "source": "missing_real_input" if needs_real_location else source,
    }


def _route_detail(real_inputs: dict[str, Any], stop: str) -> dict[str, Any]:
    details = real_inputs.get("locationDetails", {}) if isinstance(real_inputs.get("locationDetails"), dict) else {}
    return details.get(stop, {}) if isinstance(details.get(stop), dict) else {}


def _route_variants(template_id: str, selected_route: list[str], real_inputs: dict[str, Any]) -> list[dict[str, Any]]:
    locations = list(real_inputs.get("locations", []))
    indoor = list(real_inputs.get("indoorLocations", []))
    quiet = list(real_inputs.get("quietLocations", []))
    attractions = list(real_inputs.get("attractionLocations", []))
    details = real_inputs.get("locationDetails", {}) if isinstance(real_inputs.get("locationDetails"), dict) else {}

    def unique(names: list[str]) -> list[str]:
        return [name for name in dict.fromkeys([str(item) for item in names if str(item or "").strip()])]

    def fill(names: list[str]) -> list[str]:
        base = unique(names + selected_route + locations)
        return base[: max(3, min(5, len(selected_route) or 5))]

    service_or_food = [
        name
        for name, detail in details.items()
        if isinstance(detail, dict) and str(detail.get("kind") or "") in {"food", "guest_services", "quiet_or_cooling", "restrooms"}
    ]
    show_or_signature = [
        name
        for name, detail in details.items()
        if isinstance(detail, dict) and str(detail.get("kind") or "") in {"attraction", "show", "photo_spots", "quiet_or_cooling"}
    ]
    if template_id == "rainy-day":
        variants = [
            {
                "id": "comfort_first",
                "label": "Comfort-first shelter route",
                "positioning": "Minimize uncertainty with indoor, covered, seated, and optional reset moments.",
                "route": fill(indoor + quiet + service_or_food),
            },
            {
                "id": "signature_story",
                "label": "Signature story route",
                "positioning": "Use stronger attraction and show beats so the rainy-day plan still feels memorable.",
                "route": fill(attractions + show_or_signature + quiet),
            },
            {
                "id": "low_friction",
                "label": "Low-friction channel route",
                "positioning": "Prioritize easy app, signage, email, and staff execution with simple handoff points.",
                "route": fill(selected_route),
            },
        ]
    elif template_id == "kid-quest":
        variants = [
            {"id": "kid_win", "label": "Small-win quest", "positioning": "Give kids a quick first success and caregivers easy exits.", "route": fill(selected_route)},
            {"id": "visual_clue", "label": "Visual clue quest", "positioning": "Favor visible details over waits, purchases, or staff dependency.", "route": fill(show_or_signature + quiet)},
            {"id": "caregiver_safe", "label": "Caregiver-safe quest", "positioning": "Keep services, restrooms, seating, and lower-stimulation options close.", "route": fill(quiet + service_or_food)},
        ]
    else:
        variants = [
            {"id": "balanced", "label": "Balanced route", "positioning": "Balance story, comfort, and production review burden.", "route": fill(selected_route)},
            {"id": "story_rich", "label": "Story-rich route", "positioning": "Favor stronger emotional beats and memorable public landmarks.", "route": fill(show_or_signature + attractions)},
            {"id": "operationally_light", "label": "Operationally light route", "positioning": "Favor low-risk public copy, obvious locations, and simple review.", "route": fill(quiet + service_or_food + indoor)},
        ]
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for variant in variants:
        signature = "|".join(variant["route"])
        if signature and signature not in seen:
            seen.add(signature)
            result.append(variant)
    return result


def _score_route_variant(variant: dict[str, Any], template_id: str, creative_brief: dict[str, str], real_inputs: dict[str, Any], intelligence: dict[str, Any]) -> dict[str, Any]:
    route = [str(item) for item in variant.get("route", []) if str(item or "").strip()]
    details = [_route_detail(real_inputs, stop) for stop in route]
    kinds = {str(item.get("kind") or "") for item in details if item}
    zones = {str(item.get("zoneId") or "") for item in details if item.get("zoneId")}
    indoor_count = sum(1 for item in details if item.get("indoor") or item.get("covered") or str(item.get("kind") or "") in {"quiet_or_cooling", "show"})
    quiet_count = sum(1 for item in details if str(item.get("kind") or "") == "quiet_or_cooling" or "quiet" in str(item.get("sensoryNote") or "").lower())
    food_count = sum(1 for item in details if str(item.get("kind") or "") == "food")
    certified_paths = intelligence.get("certifiedPaths") if isinstance(intelligence.get("certifiedPaths"), list) else []
    capacity_model = intelligence.get("capacityModel") if isinstance(intelligence.get("capacityModel"), dict) else {}
    timing_model = intelligence.get("timingModel") if isinstance(intelligence.get("timingModel"), dict) else {}
    readiness = intelligence.get("readiness") if isinstance(intelligence.get("readiness"), dict) else {}
    quality_gaps = intelligence.get("qualityGaps") if isinstance(intelligence.get("qualityGaps"), list) else []
    certified_path_score = 1 if any(isinstance(path, dict) and path.get("certificationStatus") == "venue_certified" for path in certified_paths) else 0
    capacity_score = 1 if capacity_model.get("status") == "venue_certified" else 0
    timing_score = 1 if timing_model.get("status") == "venue_scheduled" else 0
    story_strength = min(100, 48 + len(kinds) * 10 + len(zones) * 5 + (12 if route and route[0] != route[-1] else 0))
    guest_comfort = min(100, 42 + indoor_count * 10 + quiet_count * 8 + food_count * 5 + (10 if creative_brief.get("sensoryLevel") == "low" else 0))
    accessibility_confidence = min(100, 45 + certified_path_score * 25 + capacity_score * 12 + quiet_count * 6 + (8 if real_inputs.get("accessibleRoutes") else 0))
    source_grounding = min(100, 48 + len([item for item in details if item]) * 7 + certified_path_score * 12 + timing_score * 8)
    operational_fit = min(100, 46 + capacity_score * 18 + timing_score * 18 + (8 if not quality_gaps else -8))
    creative_distinctiveness = min(100, 44 + len(kinds) * 8 + (12 if "attraction" in kinds and "show" in kinds else 0) + (8 if "food" in kinds else 0))
    scores = {
        "guestComfort": guest_comfort,
        "storyStrength": story_strength,
        "accessibilityConfidence": accessibility_confidence,
        "sourceGrounding": source_grounding,
        "operationalFit": operational_fit,
        "creativeDistinctiveness": creative_distinctiveness,
    }
    total = round(sum(scores.values()) / len(scores))
    risk_flags = []
    if not certified_path_score:
        risk_flags.append("Path confidence is derived, not certified.")
    if not capacity_score:
        risk_flags.append("Comfort and seating capacity are heuristic.")
    if not timing_score:
        risk_flags.append("Showtime, parade, setup, and blackout timing are not scheduled.")
    if timing_score and any(str(item.get("zoneId") or "") == "indoorHub" for item in details):
        risk_flags.append("Use Theater B timing windows to avoid show seating and exit pulses.")
    evidence = [
        f"{indoor_count}/{len(route)} stops are indoor, covered, quiet, or reset-friendly.",
        f"{len(kinds)} stop types and {len(zones)} zones give the story arc room to change.",
        f"Profile Intelligence readiness is {readiness.get('status', 'unknown')}.",
    ]
    return {
        **variant,
        "scores": scores,
        "totalScore": total,
        "decisiveEvidence": evidence,
        "riskFlags": risk_flags,
    }


def _experience_reasoning_layer(template_id: str, route_names: list[str], route: list[dict[str, Any]], creative_brief: dict[str, str], real_inputs: dict[str, Any], intelligence: dict[str, Any]) -> dict[str, Any]:
    scored = [
        _score_route_variant(variant, template_id, creative_brief, real_inputs, intelligence)
        for variant in _route_variants(template_id, route_names, real_inputs)
    ]
    if not scored:
        return {"status": "not_available", "conceptRoutes": [], "selectedConceptId": None}
    selected = max(scored, key=lambda item: (int(item.get("totalScore") or 0), 1 if item.get("id") == "comfort_first" else 0))
    rejected = [
        {
            "id": item.get("id"),
            "label": item.get("label"),
            "whyNot": "Lower combined guest comfort, source grounding, or operational fit for this brief.",
            "scoreDelta": int(selected.get("totalScore") or 0) - int(item.get("totalScore") or 0),
        }
        for item in scored
        if item.get("id") != selected.get("id")
    ]
    weak_copy = [
        "Initial route copy can become generic if each stop only says to move to the next marker.",
        "Operational review needs timing and capacity context, not only a generic review warning.",
    ]
    if selected.get("riskFlags"):
        weak_copy.append("Risk flags must stay visible in staff and owner review instead of being hidden by polished guest copy.")
    revisions = [
        "Varied the rainy-day stop copy by role: arrival reset, discovery pause, quiet middle, food choice, and covered close.",
        "Kept operational claims bounded by app/team-member confirmation language.",
        "Attached owner questions so channel teams can approve app, signage, email, and staff cue use.",
    ]
    guest_lenses = [
        {
            "guest": "Family with stroller",
            "likelyExperience": "Needs short transitions, seating, restrooms nearby, and clear permission to pause.",
            "designResponse": "Use compact pacing, keep food/seating resets in the route, and avoid forced completion language.",
        },
        {
            "guest": "Child overwhelmed by noise",
            "likelyExperience": "Arcade and show pulses may become too active unless a reset option is named.",
            "designResponse": "Make Theater B or a quiet corner the optional middle beat and preserve bypass language.",
        },
        {
            "guest": "Rain plus lunch crowd",
            "likelyExperience": "Dining stops can solve comfort but may create crowding or seating disappointment.",
            "designResponse": "Frame food stops as optional regroup points, not guaranteed seating or service promises.",
        },
    ]
    return {
        "status": "ready",
        "mode": "experience_design_reasoning_v1",
        "selectedConceptId": selected.get("id"),
        "selectedConceptLabel": selected.get("label"),
        "decision": {
            "whySelected": f"{selected.get('label')} best matches the brief because it has the strongest combined score for guest comfort, story clarity, source grounding, and reviewability.",
            "route": selected.get("route"),
            "totalScore": selected.get("totalScore"),
            "decisiveEvidence": selected.get("decisiveEvidence"),
            "rejectedAlternatives": rejected,
        },
        "conceptRoutes": scored,
        "critiqueAndRevision": {
            "weakPointsFound": weak_copy,
            "revisionsApplied": revisions,
        },
        "guestLenses": guest_lenses,
        "qualityScores": selected.get("scores"),
    }


def _lexicon_terms(brand_bible: dict[str, Any], *keys: str) -> list[str]:
    lexicon = brand_bible.get("thematicLexicon") if isinstance(brand_bible.get("thematicLexicon"), dict) else {}
    terms: list[str] = []
    for key in keys:
        terms.extend(_as_text_list(lexicon.get(key)))
    return list(dict.fromkeys(terms))


def _route_pattern_for_template(intelligence: dict[str, Any], template_id: str) -> tuple[str | None, dict[str, Any]]:
    rules = intelligence.get("experienceRules") if isinstance(intelligence.get("experienceRules"), dict) else {}
    route_patterns = rules.get("routePatterns") if isinstance(rules.get("routePatterns"), dict) else {}
    pattern_key = {
        "rainy-day": "rainy_day",
        "kid-quest": "kid_quest",
        "low-sensory": "low_sensory",
        "vip-tour": "vip_tour",
        "halloween-route": "halloween_route",
    }.get(template_id)
    pattern = route_patterns.get(pattern_key) if pattern_key and isinstance(route_patterns.get(pattern_key), dict) else {}
    return pattern_key, pattern


def _creative_concepts_for_template(template_id: str, route_names: list[str], audience: str, creative_brief: dict[str, str], real_inputs: dict[str, Any], intelligence: dict[str, Any], planning_profile: dict[str, Any]) -> list[dict[str, Any]]:
    brand_bible = intelligence.get("brandBible") if isinstance(intelligence.get("brandBible"), dict) else {}
    pattern_key, route_pattern = _route_pattern_for_template(intelligence, template_id)
    selected_segment = planning_profile.get("targetSegment") if isinstance(planning_profile.get("targetSegment"), dict) else {}
    segment_label = str(selected_segment.get("label") or audience)
    rain_terms = _lexicon_terms(brand_bible, "rain")
    dragon_terms = _lexicon_terms(brand_bible, "dragon")
    lagoon_terms = _lexicon_terms(brand_bible, "lagoon")
    low_terms = _lexicon_terms(brand_bible, "low_sensory")
    vip_terms = _lexicon_terms(brand_bible, "vip")
    first_stop = route_names[0] if route_names else "verified start"
    final_stop = route_names[-1] if route_names else "verified close"
    pattern_arc = route_pattern.get("recommendedArc", []) if isinstance(route_pattern.get("recommendedArc"), list) else []
    must_include = route_pattern.get("mustInclude", []) if isinstance(route_pattern.get("mustInclude"), list) else []
    channel_targets = planning_profile.get("channelTargets") if isinstance(planning_profile.get("channelTargets"), list) else ["guest_app", "signage", "email", "staff_cue"]
    if template_id == "rainy-day":
        return [
            {
                "id": "dry_dragon_trail",
                "name": "Dry Dragon Trail",
                "positioning": f"A lightly adventurous rain route for {segment_label} that uses {first_stop} as the dry spark and keeps every move optional.",
                "guestPromise": "Rain becomes a clear indoor-first path with a seated reset, a simple regroup point, and current-options language.",
                "storyArc": pattern_arc or ["dry start", "choice pause", "seated reset", "covered close"],
                "heroTerms": list(dict.fromkeys((rain_terms[:3] + dragon_terms[:3]) or ["dry marker", "launch", "glow"])),
                "route": route_names,
                "channelFocus": channel_targets,
                "reviewRisks": ["fully covered claims", "weather guarantee", "staff availability guarantee"],
                "whyItWorks": "It gives the route a memorable park-specific name while preserving the comfort-first rainy-day pattern.",
            },
            {
                "id": "lantern_rain_reset",
                "name": "Lantern Rain Reset",
                "positioning": f"A calmer version for {segment_label} that makes the middle of the route feel like a warm pause instead of a delay.",
                "guestPromise": "Families get permission to sit, skip ahead, or close the route without feeling like they failed the plan.",
                "storyArc": ["dry start", "quiet middle", "food or restroom option", "soft finale"],
                "heroTerms": list(dict.fromkeys((rain_terms[:3] + lagoon_terms[:3] + low_terms[:2]) or ["warm pause", "lantern", "quiet reset"])),
                "route": route_names,
                "channelFocus": ["email", "staff_cue", "signage"],
                "reviewRisks": ["quiet guarantee", "current seating availability", "show timing"],
                "whyItWorks": "It uses the profile's lagoon and low-sensory language to make the rainy-day concept feel less mechanical.",
            },
            {
                "id": "indoor_choice_loop",
                "name": "Indoor Choice Loop",
                "positioning": "A practical channel-first package that is easiest to publish as app, sign, email, and staff-cue variants.",
                "guestPromise": "Guests always know the next dry marker, the optional pause, and where to check current options.",
                "storyArc": pattern_arc or ["dry start", "choice pause", "covered close"],
                "heroTerms": rain_terms[:4] or ["dry marker", "covered regroup", "comfort stop"],
                "route": route_names,
                "channelFocus": ["guest_app", "signage", "email", "staff_cue"],
                "reviewRisks": must_include + ["copy length per channel"],
                "whyItWorks": "It gives the demo a clear throughline across every artifact while staying tightly reviewable.",
            },
        ]
    if template_id == "kid-quest":
        return [
            {
                "id": "lantern_badge_quest",
                "name": "Lantern Badge Quest",
                "positioning": "A simple clue route with visible objects, caregiver opt-outs, and no required purchase.",
                "guestPromise": "Kids get small wins while caregivers keep control of pace, noise, and exits.",
                "storyArc": pattern_arc or ["mission start", "visual clue", "celebration"],
                "heroTerms": lagoon_terms[:4] or ["lantern", "ripple", "soft finale"],
                "route": route_names,
                "channelFocus": channel_targets,
                "reviewRisks": ["reward fulfillment", "age suitability", "crowd language"],
                "whyItWorks": "It turns the quest into a specific, family-safe concept without inventing a prize.",
            },
            {
                "id": "storybook_wave_walk",
                "name": "Storybook Wave Walk",
                "positioning": "A softer quest that uses gentle visual details and caregiver reset points.",
                "guestPromise": "The route feels playful, but every clue can be skipped or completed at the group's pace.",
                "storyArc": ["mission start", "gentle clue", "caregiver reset", "photo close"],
                "heroTerms": ["storybook", "wave", "lantern", "soft finale"],
                "route": route_names,
                "channelFocus": ["staff_cue", "signage"],
                "reviewRisks": ["reward claims", "overly childish tone"],
                "whyItWorks": "It creates a kid-friendly route that still reads as useful to adults.",
            },
        ]
    if template_id == "vip-tour":
        return [
            {
                "id": "dragon_lantern_host_path",
                "name": "Dragon-to-Lantern Host Path",
                "positioning": "A hosted route that moves from a signature thrill/photo moment into a relaxed keepsake close.",
                "guestPromise": "The host has polished transitions, graceful alternates, and no access guarantees.",
                "storyArc": pattern_arc or ["host welcome", "signature moment", "keepsake close"],
                "heroTerms": list(dict.fromkeys(dragon_terms[:3] + lagoon_terms[:3] + vip_terms[:3])),
                "route": route_names,
                "channelFocus": ["staff_cue", "email"],
                "reviewRisks": ["priority access", "backstage access", "staffing promise"],
                "whyItWorks": "It gives VIP copy a premium shape while staying inside approved public facts.",
            }
        ]
    return [
        {
            "id": "profile_backed_story_path",
            "name": "Profile-Backed Story Path",
            "positioning": f"A source-grounded {creative_brief.get('creativeDirection', 'story')} concept for {audience}.",
            "guestPromise": "Guests get a coherent route with optional movement and reviewable channel copy.",
            "storyArc": pattern_arc or _as_text_list(creative_brief.get("storyArc")),
            "heroTerms": _lexicon_terms(brand_bible, "dragon", "lagoon", "low_sensory")[:5],
            "route": route_names,
            "channelFocus": channel_targets,
            "reviewRisks": ["availability claims", "movement instructions", "owner approval"],
            "whyItWorks": "It turns verified venue facts into a named creative route without inventing live operations.",
        }
    ]


def _score_creative_concept(concept: dict[str, Any], template_id: str, creative_brief: dict[str, str], experience_reasoning: dict[str, Any]) -> dict[str, Any]:
    channel_count = len(concept.get("channelFocus", [])) if isinstance(concept.get("channelFocus"), list) else 0
    hero_count = len(concept.get("heroTerms", [])) if isinstance(concept.get("heroTerms"), list) else 0
    route_count = len(concept.get("route", [])) if isinstance(concept.get("route"), list) else 0
    creative_fit = 72 + min(hero_count * 4, 16)
    channel_fit = 64 + min(channel_count * 6, 24)
    route_fit = 70 + min(route_count * 3, 15)
    if template_id == "rainy-day" and "dry" in str(concept.get("name", "")).lower():
        creative_fit += 5
    if creative_brief.get("creativeDirection") == "comfort-first" and "reset" in str(concept.get("positioning", "")).lower():
        route_fit += 4
    reasoning_score = int((experience_reasoning.get("decision") or {}).get("totalScore") or 80) if isinstance(experience_reasoning.get("decision"), dict) else 80
    scores = {
        "creativeFit": min(100, creative_fit),
        "channelCraft": min(100, channel_fit),
        "routeFit": min(100, route_fit),
        "reasoningAlignment": min(100, reasoning_score),
    }
    return {**concept, "scores": scores, "totalScore": round(sum(scores.values()) / len(scores))}


def _channel_copy_variants(selected: dict[str, Any], route: list[dict[str, Any]], messages: list[dict[str, Any]], template_id: str, brand_bible: dict[str, Any]) -> dict[str, Any]:
    first_stop = str(route[0].get("stop") or "the first stop") if route else "the first stop"
    final_stop = str(route[-1].get("stop") or "the final stop") if route else "the final stop"
    terms = [str(item) for item in selected.get("heroTerms", []) if str(item).strip()]
    term = terms[0] if terms else "route"
    concept_name = str(selected.get("name") or "Creative route")
    approved = _as_text_list(brand_bible.get("approvedPhrases"))
    current_options = next((item for item in approved if "current" in item.lower()), "check the app for current options")
    return {
        "guestApp": {
            "headline": concept_name,
            "body": f"Start at {first_stop}. Follow the next {term} marker when you are ready, or pause at any stop.",
            "microcopy": current_options,
        },
        "signage": [
            {"placement": first_stop, "headline": f"{term.title()} starts here"[:36], "body": "Follow the next marker when you are ready."},
            {"placement": final_stop, "headline": "Regroup here", "body": "Choose your next option in the app."},
        ],
        "email": {
            "subject": f"Try the {concept_name}",
            "previewText": "A profile-backed park route with optional movement and current-options language.",
            "body": f"Before arrival, look for {concept_name}. It begins at {first_stop}, keeps movement optional, and ends with a clear regroup at {final_stop}.",
        },
        "staffCue": {
            "opening": f"Offer {concept_name} as an optional path, not a schedule promise.",
            "transition": "Point to the next visible marker and remind guests they can pause or stop.",
            "boundary": current_options,
        },
    }


def _creative_synthesis_layer(template_id: str, route: list[dict[str, Any]], messages: list[dict[str, Any]], audience: str, creative_brief: dict[str, str], real_inputs: dict[str, Any], intelligence: dict[str, Any], experience_reasoning: dict[str, Any], planning_profile: dict[str, Any]) -> dict[str, Any]:
    route_names = [str(item.get("stop") or "") for item in route if isinstance(item, dict)]
    brand_bible = intelligence.get("brandBible") if isinstance(intelligence.get("brandBible"), dict) else {}
    concepts = [
        _score_creative_concept(concept, template_id, creative_brief, experience_reasoning)
        for concept in _creative_concepts_for_template(template_id, route_names, audience, creative_brief, real_inputs, intelligence, planning_profile)
    ]
    if not concepts:
        return {"status": "not_available", "concepts": [], "selectedConceptId": None}
    selected = max(concepts, key=lambda item: (int(item.get("totalScore") or 0), 1 if "dry" in str(item.get("id") or "") else 0))
    rejected = [
        {
            "id": item.get("id"),
            "name": item.get("name"),
            "whyNot": "Lower combined creative fit, channel craft, or route alignment for this brief.",
            "scoreDelta": int(selected.get("totalScore") or 0) - int(item.get("totalScore") or 0),
        }
        for item in concepts
        if item.get("id") != selected.get("id")
    ]
    return {
        "status": "ready",
        "mode": "creative_synthesis_v1",
        "selectedConceptId": selected.get("id"),
        "selectedConceptName": selected.get("name"),
        "selectedConcept": selected,
        "concepts": concepts,
        "decision": {
            "whySelected": f"{selected.get('name')} gives the strongest named creative direction while preserving the selected route, review boundaries, and profile-backed channel rules.",
            "rejectedAlternatives": rejected,
        },
        "copyVariants": _channel_copy_variants(selected, route, messages, template_id, brand_bible),
        "rewriteStrategy": {
            "useMoreOf": selected.get("heroTerms", []),
            "preserve": ["verified stop names", "optional movement", "current-options caveats", "owner review questions"],
            "avoid": selected.get("reviewRisks", []),
        },
    }


def _apply_learning_rules_to_synthesis(synthesis: dict[str, Any], learning_context: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(synthesis, dict) or not isinstance(learning_context, dict):
        return synthesis
    rules = learning_context.get("rules") if isinstance(learning_context.get("rules"), list) else []
    if not rules:
        return synthesis
    result = json.loads(json.dumps(synthesis, default=str))
    rewrite = result.get("rewriteStrategy") if isinstance(result.get("rewriteStrategy"), dict) else {}
    preserve = _as_text_list(rewrite.get("preserve"))
    use_more = _as_text_list(rewrite.get("useMoreOf"))
    avoid = _as_text_list(rewrite.get("avoid"))
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        tags = set(_as_text_list(rule.get("tags")))
        text = str(rule.get("rule") or "").strip()
        if not text:
            continue
        if {"package_completeness", "owner_review", "route", "review_readiness"}.intersection(tags):
            preserve.append(text)
        elif {"concept", "channel_consistency", "memory", "continuity"}.intersection(tags):
            use_more.append(text)
        guardrails = _as_text_list(rule.get("guardrails"))
        avoid.extend(guardrails)
    rewrite["preserve"] = list(dict.fromkeys(preserve))[:8]
    rewrite["useMoreOf"] = list(dict.fromkeys(use_more))[:8]
    rewrite["avoid"] = list(dict.fromkeys(avoid))[:8]
    result["rewriteStrategy"] = rewrite
    result["learningRuleInfluence"] = {
        "status": "applied",
        "usedForGeneration": True,
        "ruleCount": len(rules),
        "rules": [{"id": rule.get("id"), "rule": rule.get("rule"), "tags": rule.get("tags", [])} for rule in rules if isinstance(rule, dict)],
        "boundary": learning_context.get("learningBoundary"),
    }
    return result


def _finished_work_memory_context(template_id: str, audience: str, limit: int = 3) -> dict[str, Any]:
    records = _read_records()
    matches: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        if str(record.get("status") or "") not in FINISHED_WORK_STATUSES:
            continue
        if template_id and str(record.get("templateId") or "") != template_id:
            continue
        draft = record.get("draft") if isinstance(record.get("draft"), dict) else {}
        fingerprint = _creative_fingerprint(draft)
        if not fingerprint.get("selectedConceptName"):
            continue
        matches.append(
            {
                "draftId": record.get("id"),
                "status": record.get("status"),
                "updatedAt": record.get("updatedAt"),
                "title": fingerprint.get("title"),
                "audience": fingerprint.get("audience"),
                "selectedConceptName": fingerprint.get("selectedConceptName"),
                "guestPromise": fingerprint.get("guestPromise"),
                "route": fingerprint.get("route", []),
                "experienceBeats": fingerprint.get("experienceBeats", []),
                "selectedTerms": fingerprint.get("selectedTerms", []),
                "reviewStatuses": fingerprint.get("reviewStatuses", {}),
            }
        )
    matches = sorted(matches, key=lambda item: str(item.get("updatedAt") or ""), reverse=True)[: max(1, min(limit, 10))]
    if not matches:
        return {
            "status": "no_finished_patterns",
            "mode": "finished_work_pattern_memory_v1",
            "source": "experience_studio_drafts",
            "eligibleStatuses": sorted(FINISHED_WORK_STATUSES),
            "matchedExamples": [],
            "reusablePatterns": [],
            "avoidPatterns": ["Do not infer preferences from draft, rejected, or in-review work."],
            "learningBoundary": "No automatic feedback loop; only approved or ready-for-publish finished work can shape reusable creative context.",
        }

    concept_names = [str(item.get("selectedConceptName")) for item in matches if item.get("selectedConceptName")]
    repeated_terms = []
    for item in matches:
        repeated_terms.extend(_as_text_list(item.get("selectedTerms")))
    route_lengths = [len(item.get("route", [])) for item in matches if isinstance(item.get("route"), list)]
    review_statuses = [
        status
        for item in matches
        for status in (item.get("reviewStatuses") or {}).values()
        if str(status).strip()
    ]
    return {
        "status": "ready",
        "mode": "finished_work_pattern_memory_v1",
        "source": "experience_studio_drafts",
        "eligibleStatuses": sorted(FINISHED_WORK_STATUSES),
        "matchedTemplateId": template_id,
        "matchedAudience": audience,
        "matchedCount": len(matches),
        "matchedExamples": matches,
        "reusablePatterns": [
            f"Previously finished concepts for this template used named routes such as {', '.join(concept_names[:3])}.",
            f"Route depth has typically been {round(sum(route_lengths) / len(route_lengths), 1) if route_lengths else 0} stops with explicit channel artifacts.",
            f"Reusable voice terms: {', '.join(list(dict.fromkeys(repeated_terms))[:6]) or 'none captured yet'}.",
        ],
        "avoidPatterns": [
            "Do not reuse unapproved drafts.",
            "Do not treat reviewer notes as model training data.",
            "Do not override Venue Profile, route locks, or review gates with memory patterns.",
        ],
        "reviewSignal": {
            "clearReviewShare": round(review_statuses.count("clear") / len(review_statuses), 2) if review_statuses else None,
            "statusesSeen": sorted(set(review_statuses)),
        },
        "learningBoundary": "Finished-work memory is retrieval context only. It improves continuity over time but does not auto-promote rules or publish content.",
    }


def _route_blueprint(route: list[dict[str, Any]], creative_brief: dict[str, str], route_pattern: dict[str, Any]) -> list[dict[str, Any]]:
    arc = route_pattern.get("recommendedArc", []) if isinstance(route_pattern.get("recommendedArc"), list) else []
    result = []
    for index, item in enumerate(route):
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "order": index + 1,
                "stop": item.get("stop"),
                "storyBeat": arc[index] if index < len(arc) else _story_stage(creative_brief, index),
                "guestAction": "choose, pause, or continue" if 0 < index < len(route) - 1 else "start with consent and orientation" if index == 0 else "regroup and choose next option",
                "hostAction": item.get("staffNote"),
                "contentJob": item.get("purpose"),
                "accessibilityCheck": item.get("accessibilityNote"),
                "proofNeeded": ["current path status", "crowd/sensory condition", "signage placement approval"],
                "fallbackIfBusy": "Hold the same story beat but use the nearest approved indoor or quiet profile stop after owner review.",
            }
        )
    return result


def _channel_matrix(messages: list[dict[str, Any]], copy_variants: dict[str, Any], channel_owners: dict[str, Any], channel_rules: dict[str, Any]) -> list[dict[str, Any]]:
    app = copy_variants.get("guestApp") if isinstance(copy_variants.get("guestApp"), dict) else {}
    email = copy_variants.get("email") if isinstance(copy_variants.get("email"), dict) else {}
    staff = copy_variants.get("staffCue") if isinstance(copy_variants.get("staffCue"), dict) else {}
    signage = copy_variants.get("signage") if isinstance(copy_variants.get("signage"), list) else []
    base_message = {str(item.get("channel") or "").lower(): item for item in messages if isinstance(item, dict)}
    return [
        {
            "channel": "guest_app",
            "owner": channel_owners.get("guest_app") or "Digital product",
            "objective": "Help guests opt into the route in the moment without implying availability or operational control.",
            "primaryCopy": app.get("body") or (base_message.get("guest app") or {}).get("copy"),
            "headline": app.get("headline"),
            "microcopy": app.get("microcopy"),
            "rules": channel_rules.get("guest_app", []) if isinstance(channel_rules.get("guest_app"), list) else [],
            "reviewQuestion": "Can this app surface include current-options and accessibility links without suggesting guaranteed conditions?",
        },
        {
            "channel": "signage",
            "owner": channel_owners.get("signage") or "Park experience",
            "objective": "Give one short action at each physical decision point.",
            "primaryCopy": signage,
            "rules": channel_rules.get("signage", []) if isinstance(channel_rules.get("signage"), list) else [],
            "reviewQuestion": "Which sign placements are physically approved and readable under rainy-day traffic?",
        },
        {
            "channel": "email",
            "owner": channel_owners.get("email") or channel_owners.get("pre_arrival_email") or "CRM",
            "objective": "Set expectations before arrival while avoiding weather, seating, staffing, or access promises.",
            "primaryCopy": email.get("body") or (base_message.get("pre-arrival email") or {}).get("copy"),
            "headline": email.get("subject"),
            "microcopy": email.get("previewText"),
            "rules": channel_rules.get("email", []) if isinstance(channel_rules.get("email"), list) else [],
            "reviewQuestion": "Should this email emphasize comfort planning, accessibility planning, or a lighter story hook?",
        },
        {
            "channel": "staff_cue",
            "owner": channel_owners.get("staff_cue") or "Operations training",
            "objective": "Keep spoken guidance consistent, optional, and non-operational.",
            "primaryCopy": staff,
            "rules": channel_rules.get("staff_cue", []) if isinstance(channel_rules.get("staff_cue"), list) else [],
            "reviewQuestion": "Can training owners approve this as guest-facing language instead of an operational instruction?",
        },
    ]


def _section_dossiers(route: list[dict[str, Any]], template: dict[str, Any], selected_name: str, selected_promise: str, route_pattern: dict[str, Any], memory_context: dict[str, Any], learning_context: dict[str, Any], quality_gaps: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "section": "concept",
            "purpose": "Make the creative idea specific enough for a design team to judge.",
            "details": [
                f"Working title: {selected_name}.",
                f"Guest promise: {selected_promise}",
                f"Template intent: {template.get('intent')}",
            ],
            "reviewGate": "Brand and experience owner confirms name, promise, and audience fit.",
        },
        {
            "section": "journey",
            "purpose": "Turn the concept into a paced route with explicit guest choices.",
            "details": [
                f"{len(route)} stops, each with purpose, guest copy, staff cue, and accessibility check.",
                f"Venue pattern arc: {', '.join(str(item) for item in route_pattern.get('recommendedArc', [])[:6]) or 'not supplied'}.",
                "Every movement line must remain optional and reviewable.",
            ],
            "reviewGate": "Experience design confirms stop order, bypass logic, and pacing.",
        },
        {
            "section": "channels",
            "purpose": "Translate the same idea into app, signage, email, and staff cue artifacts.",
            "details": [
                "App copy gives the opt-in and current-options caveat.",
                "Signage uses one action per placement.",
                "Email sets expectations before arrival without making live claims.",
                "Staff cue keeps spoken language consistent with review boundaries.",
            ],
            "reviewGate": "Each channel owner approves their artifact before publishing or production handoff.",
        },
        {
            "section": "accessibility_and_sensory",
            "purpose": "Keep comfort and access checks visible instead of burying them in generic notes.",
            "details": [
                "Each stop carries an accessibility check.",
                "Sensory/crowd/current path conditions remain review items, not claims.",
                f"Profile quality gaps: {', '.join(quality_gaps) if quality_gaps else 'none returned'}.",
            ],
            "reviewGate": "Accessibility owner verifies step-free path, seating, audio, lighting, and decompression assumptions.",
        },
        {
            "section": "memory",
            "purpose": "Improve continuity from finished work over time without automatic training.",
            "details": memory_context.get("reusablePatterns", []) if memory_context.get("status") == "ready" else ["No approved finished pattern is available yet."],
            "reviewGate": "Memory can suggest reusable patterns, but the current Venue Profile and review gates stay authoritative.",
        },
        {
            "section": "approved rules",
            "purpose": "Apply human-promoted reusable rules before LLM polish.",
            "details": learning_context.get("appliedRules", []) if learning_context.get("status") == "ready" else ["No approved promoted rules are active yet."],
            "reviewGate": "Rules are reversible and cannot override profile facts, banned claims, route locks, or publish review.",
        },
    ]


def _section_creative_details(
    route: list[dict[str, Any]],
    channel_matrix: list[dict[str, Any]],
    selected_name: str,
    selected_promise: str,
    creative_brief: dict[str, str],
    channel_owners: dict[str, Any],
    route_pattern: dict[str, Any],
    copy_variants: dict[str, Any],
) -> dict[str, Any]:
    arc = route_pattern.get("recommendedArc", []) if isinstance(route_pattern.get("recommendedArc"), list) else []
    route_cards = []
    for index, item in enumerate(route):
        if not isinstance(item, dict):
            continue
        stop = str(item.get("stop") or f"stop {index + 1}")
        beat = str(arc[index]) if index < len(arc) else _story_stage(creative_brief, index)
        route_cards.append(
            {
                "order": index + 1,
                "stop": stop,
                "beat": beat,
                "guestFacingMoment": item.get("guestCopy"),
                "designerIntent": item.get("purpose"),
                "staffCue": item.get("staffNote"),
                "transitionLine": "Look for the next marker when your group is ready." if index < len(route) - 1 else "This is the close; choose the next current option in the app.",
                "choiceArchitecture": "start, pause, skip, or exit" if 0 < index < len(route) - 1 else "opt in" if index == 0 else "regroup and decide",
                "proofBeforePublish": [
                    "current path and crowd condition",
                    "step-free route and seating confirmation",
                    "channel owner approval",
                ],
            }
        )
    signage = copy_variants.get("signage") if isinstance(copy_variants.get("signage"), list) else []
    return {
        "conceptBoard": {
            "workingTitle": selected_name,
            "promise": selected_promise,
            "storyArc": creative_brief.get("storyArc"),
            "sensoryIntent": creative_brief.get("sensoryLevel"),
            "pace": creative_brief.get("walkingPace"),
            "creativeDirection": creative_brief.get("creativeDirection"),
            "reviewUse": "Use this as the creative-review frame before editing route or channel artifacts.",
        },
        "routeStoryCards": route_cards,
        "channelArtifactBriefs": [
            {
                "channel": item.get("channel"),
                "owner": item.get("owner"),
                "jobToBeDone": item.get("objective"),
                "draftArtifact": item.get("primaryCopy"),
                "headline": item.get("headline"),
                "microcopy": item.get("microcopy"),
                "reviewQuestion": item.get("reviewQuestion"),
                "productionRisk": "May imply live operational conditions unless current-options language and owner review stay attached.",
            }
            for item in channel_matrix
            if isinstance(item, dict)
        ],
        "signageProductionCards": [
            {
                "placement": item.get("placement"),
                "headline": item.get("headline"),
                "body": item.get("body"),
                "format": "short physical marker",
                "readabilityCheck": "One action, one reassurance, no availability promise.",
            }
            for item in signage
            if isinstance(item, dict)
        ],
        "emailModules": {
            "subjectJob": "Name the route and set comfort expectations without promising weather, seating, or availability.",
            "bodyJob": "Tell guests where to start, how to opt out, and where to check current options.",
            "crmOwner": channel_owners.get("email") or channel_owners.get("pre_arrival_email") or "CRM",
        },
        "staffRehearsalNotes": [
            "Use the same route name across spoken and written artifacts.",
            "Offer the route as optional; avoid commands that sound like crowd control.",
            "Escalate safety, accessibility, weather, staffing, or availability questions to the approved live source.",
        ],
    }


def _memory_application_detail(memory_context: dict[str, Any], learning_context: dict[str, Any], synthesis: dict[str, Any]) -> dict[str, Any]:
    rewrite = synthesis.get("rewriteStrategy") if isinstance(synthesis.get("rewriteStrategy"), dict) else {}
    matched = memory_context.get("matchedExamples") if isinstance(memory_context.get("matchedExamples"), list) else []
    applied_rules = learning_context.get("appliedRules") if isinstance(learning_context.get("appliedRules"), list) else []
    if memory_context.get("status") != "ready" and learning_context.get("status") != "ready":
        return {
            "status": "not_active",
            "usedForGeneration": False,
            "visibleChanges": ["No approved finished-work memory or promoted rules were active for this generation."],
            "preservedPatterns": [],
            "avoidedPatterns": ["Do not infer preferences from unapproved work."],
            "matchedDrafts": [],
            "reviewBoundary": "Memory remains audit/retrieval context only; it does not train the model or publish content.",
        }
    visible_changes = []
    if memory_context.get("status") == "ready":
        visible_changes.extend(
            [
                "Kept the output as a complete package rather than a single copy artifact.",
                "Preserved named route/concept continuity across app, email, signage, and staff cue.",
                "Kept review gates and owner questions visible in the final package.",
            ]
        )
    if applied_rules:
        visible_changes.append("Inserted human-promoted package rules into the synthesis preserve/avoid strategy.")
    return {
        "status": "active",
        "usedForGeneration": True,
        "visibleChanges": visible_changes,
        "preservedPatterns": _as_text_list(memory_context.get("reusablePatterns")) + _as_text_list(rewrite.get("preserve"))[:4],
        "avoidedPatterns": _as_text_list(memory_context.get("avoidPatterns")) + _as_text_list(rewrite.get("avoid"))[:4],
        "matchedDrafts": [
            {
                "draftId": item.get("draftId"),
                "status": item.get("status"),
                "selectedConceptName": item.get("selectedConceptName"),
                "route": item.get("route", []),
            }
            for item in matched[:3]
            if isinstance(item, dict)
        ],
        "approvedRulesApplied": applied_rules,
        "reviewBoundary": "Memory can influence continuity and completeness, but Venue Profile facts, route locks, banned claims, and review gates remain authoritative.",
    }


def _venue_data_gap_analysis(real_inputs: dict[str, Any], intelligence: dict[str, Any], route: list[dict[str, Any]], quality_gaps: list[str]) -> dict[str, Any]:
    venue = real_inputs.get("venueIdentity", {}) if isinstance(real_inputs.get("venueIdentity"), dict) else {}
    readiness = intelligence.get("readiness") if isinstance(intelligence.get("readiness"), dict) else {}
    coverage = intelligence.get("coverage") if isinstance(intelligence.get("coverage"), dict) else {}
    profile_type = str(venue.get("profileType") or "unknown")
    missing_for_real = _as_text_list(readiness.get("missingForRealVenueReady"))
    production_missing = list(missing_for_real)
    if profile_type == "synthetic_approved":
        production_missing.extend(
            [
                "real venue source feed instead of approved synthetic profile",
                "live attraction closure and current-options feed",
                "current indoor, sheltered, and blocked-path status",
                "approved physical signage placement inventory",
                "channel-owner approved CRM/app/staff language templates",
            ]
        )
    if not real_inputs.get("channelOwners"):
        production_missing.append("named channel owners for guest_app, signage, email, and staff_cue")
    if not coverage.get("certifiedPaths"):
        production_missing.append("certified path records for selected route segments")
    route_checks = [
        {
            "stop": item.get("stop"),
            "hasAccessibilityNote": bool(item.get("accessibilityNote")),
            "hasProfileFact": bool(item.get("profileIntelligenceNote")),
            "stillNeeds": [
                "current crowd/sensory condition",
                "current step-free route confirmation",
                "owner signoff before publishing",
            ],
        }
        for item in route
        if isinstance(item, dict)
    ]
    return {
        "status": "real_venue_ready" if readiness.get("realVenueReady") and profile_type != "synthetic_approved" and not production_missing else "creative_ready_review_required",
        "profileType": profile_type,
        "creativeReady": bool(intelligence and not quality_gaps),
        "productionRealVenueReady": bool(readiness.get("realVenueReady") and profile_type != "synthetic_approved" and not production_missing),
        "missingForProduction": list(dict.fromkeys(production_missing + quality_gaps)),
        "coverage": coverage,
        "routeChecks": route_checks,
        "nextProfileImports": [
            "venue-owned live status feed",
            "accessibility/path certification export",
            "signage inventory and placement approvals",
            "channel owner templates and banned-claim updates",
        ],
    }


def _studio_quality_eval(
    route: list[dict[str, Any]],
    channel_matrix: list[dict[str, Any]],
    section_dossiers: list[dict[str, Any]],
    package: dict[str, Any],
    memory_application: dict[str, Any],
    venue_gap_analysis: dict[str, Any],
    quality_gaps: list[str],
) -> dict[str, Any]:
    scores = {
        "specificity": 90 if route and all(item.get("guestCopy") and item.get("staffNote") for item in route if isinstance(item, dict)) else 55,
        "venueGrounding": 92 if route and all(item.get("source") for item in route if isinstance(item, dict)) else 65,
        "sectionCompleteness": min(100, 50 + len(section_dossiers) * 7 + len(channel_matrix) * 3),
        "creativeQuality": 88 if (package.get("executiveConcept") or {}).get("name") and (package.get("creativeSynthesis") or {}).get("concepts") else 70,
        "reviewReadiness": 72 if quality_gaps else 88,
        "memoryUse": 90 if memory_application.get("usedForGeneration") else 60,
        "publishRisk": 55 if venue_gap_analysis.get("missingForProduction") else 85,
    }
    total = round(sum(scores.values()) / len(scores), 1)
    findings = []
    if venue_gap_analysis.get("missingForProduction"):
        findings.append("Production-real venue launch still needs live/profile imports before publish.")
    if not memory_application.get("usedForGeneration"):
        findings.append("No approved memory or promoted rules influenced this generation yet.")
    if scores["sectionCompleteness"] >= 85:
        findings.append("Package includes concept, journey, channels, staff, accessibility, memory, and review sections.")
    return {
        "status": "strong_review_draft" if total >= 80 else "needs_review_work",
        "score": total,
        "scores": scores,
        "findings": findings,
        "qaChecklist": [
            {"check": "specific copy in each stop", "status": "pass" if scores["specificity"] >= 80 else "review"},
            {"check": "venue facts attached", "status": "pass" if scores["venueGrounding"] >= 80 else "review"},
            {"check": "complete artifacts", "status": "pass" if scores["sectionCompleteness"] >= 80 else "review"},
            {"check": "memory/rule influence visible", "status": "pass" if scores["memoryUse"] >= 80 else "review"},
            {"check": "production-real venue ready", "status": "pass" if not venue_gap_analysis.get("missingForProduction") else "blocked"},
        ],
        "recommendedNextActions": [
            "Send section details to channel owners for edits.",
            "Resolve production data gaps before publish or live deployment.",
            "Promote only reviewer-approved rules from finished work.",
        ],
    }


def _creative_package(route: list[dict[str, Any]], messages: list[dict[str, Any]], template_id: str, template: dict[str, Any], audience: str, tone: str, constraints: str, creative_brief: dict[str, str], real_inputs: dict[str, Any], intelligence: dict[str, Any], quality_gaps: list[str], experience_reasoning: dict[str, Any] | None = None, creative_synthesis: dict[str, Any] | None = None, memory_context: dict[str, Any] | None = None, learning_context: dict[str, Any] | None = None) -> dict[str, Any]:
    venue = real_inputs.get("venueIdentity", {}) if isinstance(real_inputs.get("venueIdentity"), dict) else {}
    venue_name = _text(venue.get("name"), "the venue")
    route_names = [str(item.get("stop") or "") for item in route if isinstance(item, dict)]
    first_stop = route_names[0] if route_names else "verified start"
    final_stop = route_names[-1] if route_names else "verified close"
    channel_owners = real_inputs.get("channelOwners", {}) if isinstance(real_inputs.get("channelOwners"), dict) else {}
    brand_bible = _brand_bible(real_inputs)
    experience_rules = _experience_rules(real_inputs)
    route_patterns = experience_rules.get("routePatterns") if isinstance(experience_rules.get("routePatterns"), dict) else {}
    pattern_key = {
        "rainy-day": "rainy_day",
        "kid-quest": "kid_quest",
        "low-sensory": "low_sensory",
        "vip-tour": "vip_tour",
        "halloween-route": "halloween_route",
    }.get(template_id)
    route_pattern = route_patterns.get(pattern_key) if pattern_key and isinstance(route_patterns.get(pattern_key), dict) else {}
    channel_rules = experience_rules.get("channelArtifactRules") if isinstance(experience_rules.get("channelArtifactRules"), dict) else {}
    brand_tone = [str(item) for item in brand_bible.get("tone", []) if str(item).strip()] if isinstance(brand_bible.get("tone"), list) else []
    approved_phrases = [str(item) for item in brand_bible.get("approvedPhrases", []) if str(item).strip()] if isinstance(brand_bible.get("approvedPhrases"), list) else []
    optional_phrase = next((item for item in approved_phrases if "optional" in item.lower()), "optional route")
    current_options_phrase = next((item for item in approved_phrases if "current" in item.lower()), "check the app for current options")
    synthesis = creative_synthesis if isinstance(creative_synthesis, dict) else {}
    selected_synthesis = synthesis.get("selectedConcept") if isinstance(synthesis.get("selectedConcept"), dict) else {}
    selected_name = _text(selected_synthesis.get("name"), str(template.get("label") or "Experience package"))
    selected_positioning = _text(selected_synthesis.get("positioning"), "")
    selected_promise = _text(selected_synthesis.get("guestPromise"), "")
    selected_terms = _as_text_list(selected_synthesis.get("heroTerms"))
    copy_variants = synthesis.get("copyVariants") if isinstance(synthesis.get("copyVariants"), dict) else {}
    app_variant = copy_variants.get("guestApp") if isinstance(copy_variants.get("guestApp"), dict) else {}
    email_variant = copy_variants.get("email") if isinstance(copy_variants.get("email"), dict) else {}
    staff_variant = copy_variants.get("staffCue") if isinstance(copy_variants.get("staffCue"), dict) else {}
    signage_variant = copy_variants.get("signage") if isinstance(copy_variants.get("signage"), list) else []
    finished_memory = memory_context if isinstance(memory_context, dict) else _finished_work_memory_context(template_id, audience)
    synthesis_channels = _as_text_list(selected_synthesis.get("channelFocus"))
    approved_rules = learning_context if isinstance(learning_context, dict) else _learning_rule_context(template_id, audience, synthesis_channels)
    route_blueprint = _route_blueprint(route, creative_brief, route_pattern)
    channel_matrix = _channel_matrix(messages, copy_variants, channel_owners, channel_rules)
    section_dossiers = _section_dossiers(route, template, selected_name, selected_promise or f"Guests get a clear {optional_phrase}.", route_pattern, finished_memory, approved_rules, quality_gaps)
    section_creative_details = _section_creative_details(route, channel_matrix, selected_name, selected_promise or f"Guests get a clear {optional_phrase}.", creative_brief, channel_owners, route_pattern, copy_variants)
    memory_application = _memory_application_detail(finished_memory, approved_rules, synthesis)
    venue_gap_analysis = _venue_data_gap_analysis(real_inputs, intelligence, route, quality_gaps)
    owner_questions = [
        {"owner": channel_owners.get("guest_app") or "Digital product", "question": "Can the app surface this as an optional journey without implying live attraction availability?"},
        {"owner": channel_owners.get("signage") or "Park experience", "question": "Which physical signs or map markers can be approved for the first and final route cues?"},
        {"owner": channel_owners.get("email") or channel_owners.get("pre_arrival_email") or "CRM", "question": "Should the pre-arrival version mention weather preparation, accessibility preferences, or both?"},
        {"owner": channel_owners.get("staff_cue") or "Operations training", "question": "What exact staff phrase is approved for explaining the route as optional and non-operational?"},
    ]
    if quality_gaps:
        owner_questions.append({"owner": "Venue Profile owner", "question": f"Can the profile replace these derived assumptions before launch: {quality_gaps[0]}?"})
    package = {
        "version": "experience_studio_package_v2",
        "executiveConcept": {
            "name": selected_name,
            "oneLine": selected_positioning or f"A {creative_brief.get('creativeDirection')} {str(template.get('label', 'experience')).lower()} for {audience}, starting at {first_stop} and closing at {final_stop}.",
            "guestPromise": selected_promise or f"Guests get a clear, {optional_phrase} that reduces uncertainty while preserving comfort, accessibility, and reviewable operational boundaries.",
            "whyNow": f"The package uses the active Venue Profile for {venue_name}; it does not invent locations, availability, staffing, weather, or safety claims.",
            "successMetric": _phrase_after_terms(constraints, ("Success metric",), "comfort, clarity, and owner review readiness"),
        },
        "journeyMap": [
            {
                "order": index + 1,
                "stop": item.get("stop"),
                "emotionalBeat": _story_stage(creative_brief, index),
                "guestNeed": "orientation" if index == 0 else "choice and comfort" if index < len(route) - 1 else "closure and next-step clarity",
                "guestCopy": item.get("guestCopy"),
                "staffCue": item.get("staffNote"),
                "accessibilityCheck": item.get("accessibilityNote"),
                "guestDecision": "opt in and orient" if index == 0 else "pause, continue, or exit" if index < len(route) - 1 else "regroup and choose next option",
                "proofNeeded": ["current route condition", "accessibility owner confirmation", "channel owner approval"],
            }
            for index, item in enumerate(route)
            if isinstance(item, dict)
        ],
        "routeBlueprint": route_blueprint,
        "experienceBeats": [
            {"beat": "Invite", "detail": f"Open with {first_stop} as the verified start and frame the journey as optional."},
            {"beat": "Orient", "detail": f"Use the {creative_brief.get('storyArc')} story arc to make each transition predictable."},
            {"beat": "Pattern", "detail": f"Venue pattern: {' -> '.join(str(item) for item in route_pattern.get('recommendedArc', [])[:5])}" if route_pattern.get("recommendedArc") else "Use the venue profile route pattern when an owner-approved recipe exists."},
            {"beat": "Care", "detail": f"Keep sensory level {creative_brief.get('sensoryLevel')} and pace {creative_brief.get('walkingPace')} unless owner review changes it."},
            {"beat": "Close", "detail": f"End at {final_stop} with channel-owner next steps, not operational promises."},
        ],
        "sectionDossiers": section_dossiers,
        "sectionCreativeDetails": section_creative_details,
        "channelMatrix": channel_matrix,
        "staffScript": {
            "openingLine": staff_variant.get("opening") or f"Welcome. This {str(template.get('shortLabel', 'route')).lower()} option is designed to keep the visit comfortable and flexible.",
            "transitionLine": staff_variant.get("transition") or "Follow the next visible marker when you are ready, or pause here if this stop works better for your group.",
            "accessibilityLine": "If you want the accessible option, ask us before moving to the next stop and we will point you to the approved route information.",
            "boundaryLine": staff_variant.get("boundary") or f"Please {current_options_phrase} or ask a team member for current attraction, weather, and availability details.",
        },
        "staffRunOfShow": [
            {
                "phase": "brief",
                "who": channel_owners.get("staff_cue") or "Operations training",
                "detail": f"Use the approved opening line for {selected_name}; do not describe it as a guaranteed route.",
                "reviewGate": "Training owner approval",
            },
            {
                "phase": "start",
                "who": "frontline host",
                "detail": f"At {first_stop}, offer the route as optional and point guests to the first visible marker.",
                "reviewGate": "On-site placement confirmation",
            },
            {
                "phase": "transition",
                "who": "route-facing team members",
                "detail": "Use the same short transition phrase, then let guests pause, exit, or continue.",
                "reviewGate": "No movement-control language",
            },
            {
                "phase": "close",
                "who": "final stop host or signage",
                "detail": f"At {final_stop}, close the story and send guests to current options.",
                "reviewGate": "Digital/current-options owner confirmation",
            },
        ],
        "signageSet": signage_variant or [
            {"placement": first_stop, "headline": f"{template.get('shortLabel')} starts here", "body": "Follow the next marker when you are ready. This route is optional."},
            {"placement": "mid-route marker", "headline": "Dry-route pause", "body": "Take a reset, check the app, or continue to the next indoor marker."},
            {"placement": final_stop, "headline": "Route close", "body": "You have reached the final comfort stop. Choose your next option in the app."},
        ],
        "preArrivalEmail": {
            "subject": email_variant.get("subject") or f"Plan a comfortable {str(template.get('shortLabel', 'park')).lower()} option for your visit",
            "previewText": email_variant.get("previewText") or f"{venue_name} has an optional {str(template.get('label', 'experience')).lower()} drafted for {audience}.",
            "body": email_variant.get("body") or next((str(item.get("copy")) for item in messages if str(item.get("channel") or "").lower() == "pre-arrival email"), ""),
        },
        "productionDetail": {
            "guestChoiceModel": [
                "Guests can start, pause, skip ahead, or stop without penalty.",
                "Every route step is framed as an option, not a required instruction.",
                "Current availability, weather exposure, crowd level, seating, and staffing stay outside the LLM's authority.",
            ],
                "contentCompletenessChecklist": [
                    "named concept",
                    "guest promise",
                    "route storyboard",
                "app copy",
                "signage set",
                "pre-arrival email",
                "staff cue",
                "accessibility review packet",
                "owner questions",
                    "memory influence receipt",
                    "approved rule receipt",
                ],
            "measurementPlan": [
                {"metric": "comfort", "signal": "guest-care edits, route completion, confusion reports", "learningUse": "aggregate review context only"},
                {"metric": "clarity", "signal": "channel-owner edits and guest app tap-through", "learningUse": "finished-work pattern after approval"},
                {"metric": "review effort", "signal": "number of blocked or rewritten claims", "learningUse": "guardrail tuning only after owner approval"},
            ],
            "localizationNotes": ["Use approved phrases from the brand bible.", "Spanish or other locale copy requires separate owner review before publishing."],
        },
        "accessibilityReviewPacket": {
            "mustVerify": [
                "current step-free path between every selected stop",
                "seating and decompression availability",
                "lighting, audio, crowding, and weather exposure at each stop",
                "readability of signage and app copy",
            ],
            "profileQualityGaps": quality_gaps,
            "routeChecks": [
                {"stop": item.get("stop"), "accessibilityNote": item.get("accessibilityNote"), "source": item.get("source")}
                for item in route
                if isinstance(item, dict)
            ],
        },
        "ownerQuestions": owner_questions,
        "copyVoice": {
            "tone": tone,
            "brandTone": brand_tone,
            "avoid": brand_bible.get("bannedClaims", []) if isinstance(brand_bible.get("bannedClaims"), list) else [],
            "approvedPhrases": approved_phrases,
            "thematicLexicon": brand_bible.get("thematicLexicon", {}) if isinstance(brand_bible.get("thematicLexicon"), dict) else {},
            "selectedTerms": selected_terms,
        },
        "venuePattern": {
            "id": pattern_key,
            "recommendedArc": route_pattern.get("recommendedArc", []) if isinstance(route_pattern.get("recommendedArc"), list) else [],
            "mustInclude": route_pattern.get("mustInclude", []) if isinstance(route_pattern.get("mustInclude"), list) else [],
            "avoidClaims": route_pattern.get("avoidClaims", []) if isinstance(route_pattern.get("avoidClaims"), list) else [],
            "channelRules": channel_rules,
        },
        "memoryInfluence": {
            **finished_memory,
            "usedForGeneration": finished_memory.get("status") == "ready",
            "authority": "retrieval_context_only",
        },
        "memoryApplication": memory_application,
        "approvedRuleInfluence": {
            **approved_rules,
            "usedForGeneration": approved_rules.get("status") == "ready",
            "authority": "human_promoted_rules_only",
        },
        "venueDataGapAnalysis": venue_gap_analysis,
        "designReasoning": experience_reasoning or {},
        "creativeSynthesis": synthesis,
    }
    package["studioQualityEval"] = _studio_quality_eval(route, channel_matrix, section_dossiers, package, memory_application, venue_gap_analysis, quality_gaps)
    return package


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
    experience_reasoning = _experience_reasoning_layer(template_id, route_names, route, creative_brief, real_inputs, intelligence)
    planning_profile = payload.get("planningProfile") if isinstance(payload.get("planningProfile"), dict) else {}
    creative_synthesis = _creative_synthesis_layer(template_id, route, messages, audience, creative_brief, real_inputs, intelligence, experience_reasoning, planning_profile)
    channel_targets = planning_profile.get("channelTargets") if isinstance(planning_profile.get("channelTargets"), list) else []
    learning_context = _learning_rule_context(template_id, audience, channel_targets) if payload.get("useApprovedLearningRules", True) is not False else {
        "status": "disabled",
        "mode": "human_approved_learning_rules_v1",
        "ruleCount": 0,
        "rules": [],
        "appliedRules": [],
        "guardrails": [],
        "learningBoundary": "Approved learning rules were disabled for this generation.",
    }
    creative_synthesis = _apply_learning_rules_to_synthesis(creative_synthesis, learning_context)
    memory_context = _finished_work_memory_context(template_id, audience) if payload.get("useExperienceMemory", True) is not False else {
        "status": "disabled",
        "mode": "finished_work_pattern_memory_v1",
        "matchedExamples": [],
        "reusablePatterns": [],
        "avoidPatterns": ["Experience memory disabled by request."],
        "learningBoundary": "Memory retrieval was disabled for this generation.",
    }
    creative_package = _creative_package(route, messages, template_id, template, audience, tone, constraints, creative_brief, real_inputs, intelligence, quality_gaps, experience_reasoning, creative_synthesis, memory_context, learning_context)
    draft = {
        "title": template["label"],
        "audience": audience,
        "intent": template["intent"],
        "studioCore": _studio_core_preset(),
        "creativeBrief": {
            **creative_brief,
            "tone": tone,
            "constraints": constraints,
        },
        "route": route,
        "messages": messages,
        "experienceReasoning": experience_reasoning,
        "creativeSynthesis": creative_synthesis,
        "creativePackage": creative_package,
        "finishedWorkMemory": memory_context,
        "approvedLearningRules": learning_context,
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
            "readiness": intelligence.get("readiness") if isinstance(intelligence.get("readiness"), dict) else {},
            "contract": intelligence.get("contract") if isinstance(intelligence.get("contract"), dict) else {},
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
            "studio_core_preset": _studio_core_preset(),
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
                timeout_seconds=float(os.getenv("PARKPULSE_EXPERIENCE_STUDIO_LLM_TIMEOUT_SECONDS", "20")),
                max_output_tokens=int(os.getenv("PARKPULSE_EXPERIENCE_STUDIO_LLM_MAX_OUTPUT_TOKENS", "6000")),
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

    memory_persistence = _record_studio_memory(
        "experience_studio_generation_runs",
        _generation_memory_event(payload, draft, llm, venue_experience_data),
    )

    return {
        "status": "ready",
        "mode": "experience_studio_creative_draft",
        "draft": draft,
        "prompt": prompt,
        "creativePrompt": creative_prompt,
        "llm": llm,
        "studioCore": _studio_core_preset(),
        "sourceContext": state_context,
        "memoryPersistence": memory_persistence,
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
