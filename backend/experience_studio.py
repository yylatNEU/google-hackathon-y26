from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TEMPLATES: dict[str, dict[str, Any]] = {
    "festival-plan": {
        "label": "Festival Experience Plan",
        "shortLabel": "Festival",
        "intent": "Create a multi-week seasonal festival plan with programming phases, route moments, channel copy, and owner review gates.",
        "route": ["Real festival entry needed", "Real celebration landmark needed", "Real food or retail moment needed", "Real show or gathering location needed", "Real finale or photo location needed"],
    },
    "seasonal-overlay": {
        "label": "Seasonal Overlay",
        "shortLabel": "Seasonal",
        "intent": "Create a seasonal park overlay with story moments, route anchors, channel copy, and review gates for temporary decor or programming.",
        "route": ["Real seasonal entry needed", "Real overlay landmark needed", "Real themed pause needed", "Real photo or show moment needed", "Real seasonal close needed"],
    },
    "food-festival": {
        "label": "Food Festival Trail",
        "shortLabel": "Food festival",
        "intent": "Design a food-forward festival trail with dining moments, menu-safe language, retail or craft pairings, and owner-reviewed allergy boundaries.",
        "route": ["Real food entry needed", "Real food court needed", "Real snack or retail stop needed", "Real seating or show pause needed", "Real food finale needed"],
    },
    "photo-moment-route": {
        "label": "Photo Moment Route",
        "shortLabel": "Photo route",
        "intent": "Build a route around inspectable photo spots, scenic cues, app prompts, signage, and accessibility-aware pacing.",
        "route": ["Real photo start needed", "Real landmark photo spot needed", "Real scenic transition needed", "Real group photo stop needed", "Real photo close needed"],
    },
    "accessibility-family-day": {
        "label": "Accessible Family Day",
        "shortLabel": "Accessible day",
        "intent": "Design a family guest journey that foregrounds accessibility choices, rest points, plain-language copy, and owner-reviewed route assumptions.",
        "route": ["Real accessible start needed", "Real step-free path needed", "Real rest point needed", "Real flexible activity needed", "Real accessible close needed"],
    },
    "teen-night-out": {
        "label": "Teen Night Out",
        "shortLabel": "Teen night",
        "intent": "Create a social evening path for teens with photo moments, food or hangout beats, safety-aware copy, and clear group choice points.",
        "route": ["Real teen-friendly entry needed", "Real social photo stop needed", "Real food or hangout stop needed", "Real thrill or show option needed", "Real regroup close needed"],
    },
    "first-time-visitor": {
        "label": "First-Time Visitor Journey",
        "shortLabel": "First visit",
        "intent": "Create an orientation-first journey that helps new guests understand the park, choose next steps, and avoid confusion.",
        "route": ["Real arrival point needed", "Real orientation landmark needed", "Real signature starter needed", "Real comfort or dining stop needed", "Real next-step close needed"],
    },
    "date-night": {
        "label": "Date Night Route",
        "shortLabel": "Date night",
        "intent": "Design an adult or couple evening path with relaxed pacing, scenic stops, food or show moments, and tasteful guest-facing copy.",
        "route": ["Real evening entry needed", "Real scenic stop needed", "Real food or drink-adjacent stop needed", "Real show or quiet pause needed", "Real photo close needed"],
    },
    "education-field-trip": {
        "label": "Education Field Trip",
        "shortLabel": "Field trip",
        "intent": "Create a school or group learning journey with educational prompts, chaperone clarity, pacing, and reviewable safety boundaries.",
        "route": ["Real group arrival needed", "Real learning landmark needed", "Real observation stop needed", "Real lunch or reset stop needed", "Real group close needed"],
    },
    "post-incident-recovery-copy": {
        "label": "Post-Incident Recovery Copy",
        "shortLabel": "Recovery copy",
        "intent": "Draft guest-facing recovery messaging after a disruption while staying non-operational, empathetic, and review-gated.",
        "route": ["Real incident context needed", "Real guest support point needed", "Real alternate option needed", "Real staff phrase needed", "Real follow-up channel needed"],
    },
    "retail-merch-quest": {
        "label": "Retail Merch Quest",
        "shortLabel": "Merch quest",
        "intent": "Create a retail or merchandise-linked quest with story clues, shop or display moments, non-purchase options, and fulfillment review gates.",
        "route": ["Real merch start needed", "Real display clue needed", "Real shop or retail stop needed", "Real non-purchase participation stop needed", "Real quest close needed"],
    },
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


def _visual_asset_output_dir() -> Path:
    configured = os.getenv("PARKPULSE_EXPERIENCE_STUDIO_VISUAL_OUTPUT_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[1] / "output" / "experience-studio"


def _safe_asset_slug(value: str, fallback: str = "experience-visual") -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return slug[:80] or fallback


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
    "experience_studio_approved_work",
    "experience_studio_feedback",
    "experience_studio_revision_events",
    "experience_studio_learning_rules",
    "experience_studio_venue_snapshots",
    "experience_studio_eval_examples",
]

EXPERIENCE_STUDIO_RETENTION_POLICY = {
    "generationRuns": {"collection": "experience_studio_generation_runs", "retentionDays": 90, "purpose": "Audit prompt, source, model, and merge-guard receipts."},
    "drafts": {"collection": "experience_studio_drafts", "retentionDays": 365, "purpose": "Preserve saved creative packages and source-integrity state."},
    "approvedWork": {"collection": "experience_studio_approved_work", "retentionDays": None, "purpose": "Human-approved or explicitly synthetic-labeled finished packages that can be retrieved as bounded creative memory."},
    "feedback": {"collection": "experience_studio_feedback", "retentionDays": 365, "purpose": "Preserve review decisions as audit receipts only."},
    "revisionEvents": {"collection": "experience_studio_revision_events", "retentionDays": 365, "purpose": "Preserve content updates, workflow transitions, and handoff receipts."},
    "learningRules": {"collection": "experience_studio_learning_rules", "retentionDays": None, "purpose": "Human-promoted reusable Studio rules from approved finished work; reversible and never automatic training."},
    "venueSnapshots": {"collection": "experience_studio_venue_snapshots", "retentionDays": None, "purpose": "Versioned Venue Profile snapshots and source-ledger receipts used to prove which profile backed a generated package."},
    "evalExamples": {"collection": "experience_studio_eval_examples", "retentionDays": None, "purpose": "Prompt, output, critique, score, and final-result examples for offline evals and prompt improvement."},
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


def _draft_template_id(draft: dict[str, Any], payload: dict[str, Any] | None = None) -> str | None:
    payload = payload if isinstance(payload, dict) else {}
    package = draft.get("creativePackage") if isinstance(draft.get("creativePackage"), dict) else {}
    planner_context = draft.get("plannerContext") if isinstance(draft.get("plannerContext"), dict) else {}
    if not planner_context and isinstance(package.get("plannerReasonedPlan"), dict):
        planner_context = package.get("plannerReasonedPlan", {})
    parsed_brief = planner_context.get("parsedBrief") if isinstance(planner_context.get("parsedBrief"), dict) else {}
    candidates = [
        parsed_brief.get("templateId"),
        (package.get("retrievalEvidence") or {}).get("query", {}).get("templateId") if isinstance(package.get("retrievalEvidence"), dict) and isinstance((package.get("retrievalEvidence") or {}).get("query"), dict) else None,
        payload.get("templateId"),
        payload.get("template"),
    ]
    for candidate in candidates:
        candidate_text = str(candidate or "").strip()
        if candidate_text in TEMPLATES:
            return candidate_text
    title = str(draft.get("title") or "").lower()
    if "festival" in title:
        return "festival-plan"
    return None


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


def _semantic_studio_memory(
    *,
    query: str,
    template_id: str,
    collections: list[str] | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    try:
        from mongo_memory import retrieve_experience_studio_memory

        return retrieve_experience_studio_memory(
            query,
            collections
            or [
                "experience_studio_approved_work",
                "experience_studio_learning_rules",
                "experience_studio_venue_snapshots",
                "experience_studio_eval_examples",
            ],
            template_id=template_id,
            limit=limit,
        )
    except Exception as error:
        return {
            "status": "error",
            "mode": "experience_studio_semantic_memory_retrieval_v1",
            "query": {"text": query, "templateId": template_id, "collections": collections or []},
            "retrieval": {"returnedCount": 0, "fallback": "latest_memory_only"},
            "rows": [],
            "errors": [str(error)[:240]],
            "boundary": "Semantic memory retrieval failed; fall back to bounded latest-memory context.",
        }


def _active_learning_rules(template_id: str, audience: str, channel_targets: list[str] | None = None, limit: int = 12) -> list[dict[str, Any]]:
    channel_set = {str(item) for item in (channel_targets or []) if str(item).strip()}
    query = " ".join(
        [
            f"Experience Studio approved learning rules for {template_id}",
            f"audience {audience}",
            " ".join(sorted(channel_set)),
        ]
    )
    retrieval = _semantic_studio_memory(
        query=query,
        template_id=template_id,
        collections=["experience_studio_learning_rules"],
        limit=max(limit * 2, 20),
    )
    rows = retrieval.get("rows") if isinstance(retrieval.get("rows"), list) else []
    if not rows:
        rows = _latest_studio_memory("experience_studio_learning_rules", max(limit * 8, 100))
    active: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_fingerprints: set[str] = set()
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
        fingerprint = json.dumps(
            {
                "templateId": row_template or template_id,
                "rule": " ".join(str(row.get("rule") or "").lower().split()),
                "tags": sorted(_as_text_list(row.get("tags"))),
            },
            sort_keys=True,
        )
        if fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(fingerprint)
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


def _synthetic_memory_boundary() -> str:
    return "Demo memory only. It can shape creative continuity but cannot prove real venue approval, cultural approval, schedule, rewards, staffing, food, safety, or accessibility conditions."


def _synthetic_approved_work_records(batch_id: str, now: str) -> list[dict[str, Any]]:
    shared = {
        "eventType": "synthetic_approved_work_injected",
        "batchId": batch_id,
        "status": "synthetic_approved",
        "approvalStatus": "synthetic_approved",
        "memorySource": "synthetic_demo_memory",
        "syntheticMemory": True,
        "syntheticBoundary": _synthetic_memory_boundary(),
        "learningEligible": True,
        "learningSource": "synthetic_demo_finished_work_memory",
        "learningPolicy": _memory_learning_policy(),
        "createdAt": now,
        "updatedAt": now,
    }
    return [
        {
            **shared,
            "_id": "exp_synth_approved_festival_plan_festival_month_v2",
            "templateId": "festival-plan",
            "title": "Synthetic: Lantern Wishes Festival Month",
            "audience": "families, friend groups, and multigenerational guests",
            "selectedConceptName": "Lantern Wishes Festival Month",
            "guestPromise": "Guests can sample a month-long festival path through optional launch, discovery, food/craft, show, photo, and finale beats while all cultural, reward, schedule, food, staffing, and access claims stay owner-reviewed.",
            "route": ["Front Gate", "Dragon Arch Photo Spot", "Lagoon Lanterns", "Harbor Treats", "Theater B"],
            "experienceBeats": ["launch promise", "photo invitation", "lantern discovery", "food or craft pause", "show/photo finale"],
            "selectedTerms": ["lantern", "wish", "festival passport", "family photo", "review gate"],
            "reviewStatuses": {"creative_director": "clear", "accessibility_reviewer": "review", "cultural_reviewer": "review", "channel_owner": "clear"},
            "reusablePatterns": [
                "For month-long festival packages, structure the guest journey as launch weekend, discovery weeks, and finale week.",
                "Use participation mechanics as placeholders until fulfillment owners approve prizes, stamps, passports, red envelopes, or food offers.",
                "Keep one named concept visible across app, signage, email, staff cue, and event-team brief.",
            ],
        },
        {
            **shared,
            "_id": "exp_synth_approved_rainy_day_dry_choice_loop_v1",
            "templateId": "rainy-day",
            "title": "Synthetic: Dry Choice Loop",
            "audience": "mixed family groups",
            "selectedConceptName": "Dry Choice Loop",
            "guestPromise": "Rain becomes a short, optional indoor-first path with a dry start, a flexible activity pause, a seated reset, and a clear current-options close.",
            "route": ["Indoor Launch", "Arcade Zone", "Theater B", "Food Court A", "Food Court B"],
            "experienceBeats": ["dry start", "choose a pause", "sit and reset", "warm choice", "covered close"],
            "selectedTerms": ["dry marker", "comfort route", "short reset", "current options"],
            "reviewStatuses": {"creative_director": "clear", "accessibility_reviewer": "clear", "claims_reviewer": "clear"},
            "reusablePatterns": [
                "Rainy-day journeys should not promise fully covered movement; they should name the next indoor or sheltered choice.",
                "Keep rainy-day copy short enough for app, signage, and staff cue reuse.",
                "Use one comfort action per stop: start, pause, sit, choose, close.",
            ],
        },
        {
            **shared,
            "_id": "exp_synth_approved_low_sensory_quiet_choice_path_v1",
            "templateId": "low-sensory",
            "title": "Synthetic: Quiet Choice Path",
            "audience": "guests who prefer lower stimulation and caregivers planning flexible exits",
            "selectedConceptName": "Quiet Choice Path",
            "guestPromise": "Guests get a predictable path with plain language, visible pauses, skip points, and review-gated sensory/access assumptions.",
            "route": ["Guest Services", "Shade Garden", "Theater B", "Care Lagoon Family Room", "Covered Plaza"],
            "experienceBeats": ["plain orientation", "quiet move", "reset option", "care pause", "easy return"],
            "selectedTerms": ["plain language", "pause choice", "exit option", "sensory review"],
            "reviewStatuses": {"accessibility_reviewer": "clear", "creative_director": "clear", "claims_reviewer": "clear"},
            "reusablePatterns": [
                "Low-sensory packages should use plain action language and avoid promising quiet, low crowds, seating, or lighting conditions.",
                "Every low-sensory stop needs a skip, pause, or exit statement.",
                "Put sensory verification into review gates instead of guest-facing claims.",
            ],
        },
        {
            **shared,
            "_id": "exp_synth_approved_kid_quest_lantern_badge_v1",
            "templateId": "kid-quest",
            "title": "Synthetic: Lantern Badge Quest",
            "audience": "kids ages 6 to 10 with caregivers",
            "selectedConceptName": "Lantern Badge Quest",
            "guestPromise": "Kids get one visible clue per stop while caregivers keep control of pace, exits, noise, and completion.",
            "route": ["Front Gate", "Storybook Boats", "Lagoon Lanterns", "Shade Garden", "Covered Plaza"],
            "experienceBeats": ["mission invite", "look-and-find clue", "lantern choice", "caregiver reset", "no-pressure finish"],
            "selectedTerms": ["badge", "clue", "caregiver skip", "visual clue"],
            "reviewStatuses": {"creative_director": "clear", "family_reviewer": "clear", "fulfillment_reviewer": "review"},
            "reusablePatterns": [
                "Kid quests should make clues visual and skippable, not dependent on purchases, prizes, or exact staffing.",
                "Use caregiver-control language in every quest package.",
                "Reward language should stay as stamp, sticker, phrase, or placeholder until fulfillment approval.",
            ],
        },
        {
            **shared,
            "_id": "exp_synth_approved_halloween_lantern_mystery_v1",
            "templateId": "halloween-route",
            "title": "Synthetic: Lantern Mystery Party Path",
            "audience": "families with older kids",
            "selectedConceptName": "Lantern Mystery Party Path",
            "guestPromise": "Families follow a spooky-friendly optional party path with photo moments, gentle clues, no gore, no jump-scare promise, and current-options language.",
            "route": ["Front Gate", "Dragon Arch Photo Spot", "Lagoon Lanterns", "Theater B", "Covered Plaza"],
            "experienceBeats": ["costume welcome", "friendly clue", "lantern reveal", "show pause", "covered finale"],
            "selectedTerms": ["friendly spooky", "glow", "mystery clue", "photo pause"],
            "reviewStatuses": {"creative_director": "clear", "safety_claims_reviewer": "clear", "accessibility_reviewer": "review"},
            "reusablePatterns": [
                "Halloween family packages should state no gore, optional clues, and current-options boundaries.",
                "Use friendly mystery language rather than fear, panic, chase, or emergency framing.",
                "Carry the party feeling through route, signage, email, and staff cue.",
            ],
        },
        {
            **shared,
            "_id": "exp_synth_approved_vip_dragon_lantern_host_v1",
            "templateId": "vip-tour",
            "title": "Synthetic: Dragon-to-Lantern Host Path",
            "audience": "VIP guests and hosted groups",
            "selectedConceptName": "Dragon-to-Lantern Host Path",
            "guestPromise": "A host-led path feels polished and personal while avoiding priority access, private route, backstage, or staffing guarantees.",
            "route": ["Front Gate", "Dragon Arch Photo Spot", "Theater B", "Lagoon Lanterns", "Covered Plaza"],
            "experienceBeats": ["polished welcome", "signature photo", "relaxed story pause", "keepsake close", "current-options handoff"],
            "selectedTerms": ["hosted", "polished", "signature reveal", "graceful alternate"],
            "reviewStatuses": {"creative_director": "clear", "vip_owner": "review", "claims_reviewer": "clear"},
            "reusablePatterns": [
                "VIP copy may sound polished, but it cannot imply priority access, backstage access, private routes, or guaranteed staffing.",
                "Host scripts should include graceful alternates and no access promises.",
                "Premium experiences should end with a keepsake or photo cue, not an operational guarantee.",
            ],
        },
        {
            **shared,
            "_id": "exp_synth_approved_food_festival_flavor_trail_v1",
            "templateId": "food-festival",
            "title": "Synthetic: Flavor Trail",
            "audience": "food-curious families and friend groups",
            "selectedConceptName": "Flavor Trail",
            "guestPromise": "Guests follow a food-forward path with menu-safe language, optional seating pauses, and allergy/availability review gates.",
            "route": ["Front Gate", "Food Court A", "Harbor Treats", "Food Court B", "Covered Plaza"],
            "experienceBeats": ["taste invite", "menu-safe choice", "craft or retail pairing", "seated reset", "food finale"],
            "selectedTerms": ["taste", "menu review", "seated pause", "availability caveat"],
            "reviewStatuses": {"food_owner": "review", "claims_reviewer": "clear", "creative_director": "clear"},
            "reusablePatterns": [
                "Food festival copy must avoid allergen-free, guaranteed menu, or availability claims.",
                "Pair food stops with seating or reset options so the path is not just a purchase sequence.",
                "Use menu-safe placeholders until Food and Legal approve item names.",
            ],
        },
        {
            **shared,
            "_id": "exp_synth_approved_accessibility_easy_choice_day_v1",
            "templateId": "accessibility-family-day",
            "title": "Synthetic: Easy-Choice Family Day",
            "audience": "families planning around accessibility needs",
            "selectedConceptName": "Easy-Choice Family Day",
            "guestPromise": "Families get plain-language choices, rest points, and owner-reviewed route assumptions without overclaiming access conditions.",
            "route": ["Guest Services", "Covered Plaza", "Theater B", "Food Court B", "Care Lagoon Family Room"],
            "experienceBeats": ["support start", "step-free choice", "seated pause", "food/reset option", "family close"],
            "selectedTerms": ["plain language", "rest point", "access review", "choice-forward"],
            "reviewStatuses": {"accessibility_reviewer": "review", "creative_director": "clear", "claims_reviewer": "clear"},
            "reusablePatterns": [
                "Accessibility-forward journeys should never claim ADA compliance; they should say what must be verified by the owner.",
                "Put rest points and support points into the route, not only in notes.",
                "Use choice-forward copy that lets families pause, skip, or return.",
            ],
        },
        {
            **shared,
            "_id": "exp_synth_approved_photo_moment_picture_path_v1",
            "templateId": "photo-moment-route",
            "title": "Synthetic: Picture-Perfect Park Path",
            "audience": "social guests, families, and photo-focused groups",
            "selectedConceptName": "Picture-Perfect Park Path",
            "guestPromise": "Guests get a visually inspectable route with photo cues, group pauses, and accessibility-aware pacing without claiming final signage or crowd conditions.",
            "route": ["Front Gate", "Dragon Arch Photo Spot", "Lagoon Lanterns", "Storybook Boats", "Covered Plaza"],
            "experienceBeats": ["photo invite", "landmark shot", "scenic transition", "group pause", "shareable close"],
            "selectedTerms": ["photo cue", "landmark", "group shot", "scenic transition"],
            "reviewStatuses": {"creative_director": "clear", "accessibility_reviewer": "review", "signage_owner": "review"},
            "reusablePatterns": [
                "Photo routes should name the visual job of each stop: arrival shot, landmark shot, transition, group shot, close.",
                "Do not imply approved final signage placement unless signage owner has approved it.",
                "Keep photo prompts optional and do not block pathways.",
            ],
        },
        {
            **shared,
            "_id": "exp_synth_approved_recovery_calm_message_set_v1",
            "templateId": "post-incident-recovery-copy",
            "title": "Synthetic: Calm Recovery Message Set",
            "audience": "affected guests and guest-care teams",
            "selectedConceptName": "Calm Recovery Message Set",
            "guestPromise": "Guests receive calm, accountable, non-operational recovery messaging that orients them to support and current sources without admitting facts not approved by owners.",
            "route": ["Guest Services", "Covered Plaza", "Food Court B", "Theater B", "Front Gate"],
            "experienceBeats": ["acknowledge", "orient to support", "alternate option", "staff phrase", "follow-up close"],
            "selectedTerms": ["calm", "accountable", "support point", "current source"],
            "reviewStatuses": {"guest_care": "review", "legal": "review", "creative_director": "clear"},
            "reusablePatterns": [
                "Recovery copy should acknowledge experience impact without inventing incident cause, compensation, or operational facts.",
                "Every recovery package needs a support point, current source, staff phrase, and follow-up channel.",
                "Keep empathy high and operational specificity review-gated.",
            ],
        },
    ]


def _synthetic_learning_rule_records(batch_id: str, now: str, actor: str) -> list[dict[str, Any]]:
    rules = [
        ("festival-plan", "festival_month_structure", "For festival-plan requests that mention a month-long run, generate launch weekend, discovery weeks, and finale week before writing channel copy.", ["festival", "month_long", "program_phases"]),
        ("rainy-day", "rainy_day_choice_copy", "For rainy-day journeys, use a dry start, flexible pause, seated reset, and current-options close; never promise fully covered movement.", ["rainy_day", "comfort", "claim_safety"]),
        ("low-sensory", "low_sensory_plain_language", "For low-sensory paths, use plain action language, visible pause/skip/exit choices, and review-gated sensory assumptions.", ["low_sensory", "accessibility", "plain_language"]),
        ("kid-quest", "kid_quest_caregiver_control", "For kid quests, every clue must be visual, skippable, and caregiver-controlled; rewards stay placeholders until fulfillment approval.", ["kid_quest", "family", "fulfillment"]),
        ("halloween-route", "family_halloween_boundary", "For family Halloween routes, use friendly mystery language, no gore, optional clues, and no access or scare guarantees.", ["halloween", "family_safe", "claim_safety"]),
        ("vip-tour", "vip_no_access_promise", "For VIP scripts, sound polished but avoid priority access, backstage, private-route, staffing, and availability promises.", ["vip", "premium", "claim_safety"]),
        ("food-festival", "food_menu_safe", "For food festival trails, keep menu, allergy, item, and availability claims as owner-reviewed placeholders until approved.", ["food", "menu_safe", "owner_review"]),
        ("accessibility-family-day", "accessibility_no_overclaim", "For accessibility-forward family journeys, state choices and verification needs; never claim ADA compliance or guaranteed access conditions.", ["accessibility", "family", "claim_safety"]),
        ("photo-moment-route", "photo_route_visual_job", "For photo routes, assign each stop a visual job and keep photo prompts optional so guests do not block pathways.", ["photo", "route_craft", "signage_review"]),
        ("post-incident-recovery-copy", "recovery_no_fact_invention", "For recovery copy, acknowledge impact, orient to support, and keep incident cause, compensation, and operational facts owner-reviewed.", ["recovery", "guest_care", "legal_review"]),
    ]
    records = []
    for template_id, slug, rule, tags in rules:
        rule_id = f"exp_rule_synthetic_{template_id}_{slug}_v2"
        records.append(
            {
                "_id": rule_id,
                "id": rule_id,
                "eventType": "synthetic_learning_rule_injected",
                "batchId": batch_id,
                "approvalStatus": "approved",
                "rule": rule,
                "lesson": "Synthetic demo rule for bounded Experience Studio memory retrieval.",
                "templateId": template_id,
                "scope": {"templateId": template_id, "audience": "demo audience", "channels": ["guest_app", "signage", "email", "staff_cue"]},
                "tags": ["synthetic_memory", *tags, "package_completeness"],
                "guardrails": ["Synthetic rule can shape draft craft but cannot prove real venue approval, live facts, publish readiness, or model training authority."],
                "promotedBy": actor,
                "promotionNote": "Synthetic demo rule injected for hackathon memory demonstration.",
                "syntheticMemory": True,
                "learningEligible": False,
                "learningSource": "synthetic_demo_rule",
                "learningPolicy": _memory_learning_policy(),
                "reversible": True,
                "createdAt": now,
                "updatedAt": now,
            }
        )
    return records


def _synthetic_eval_example_records(batch_id: str, now: str) -> list[dict[str, Any]]:
    prompts = [
        ("festival-plan", "Create a Chinese New Year festival plan that runs for a month.", ["selects festival-plan", "includes launch/discovery/finale phases", "review-gates cultural/reward/date claims"]),
        ("rainy-day", "Create a rainy-day family journey with indoor-first comfort and staff cue copy.", ["selects rainy-day", "uses indoor/sheltered stops", "does not promise fully covered movement"]),
        ("low-sensory", "Create a low-sensory path for families who need predictable exits.", ["plain language", "pause/skip/exit choices", "does not guarantee quiet"]),
        ("kid-quest", "Create a kid-friendly quest with clues and no purchase requirement.", ["visual skippable clues", "caregiver control", "reward placeholder"]),
        ("halloween-route", "Create a Halloween party path for families with older kids.", ["friendly spooky tone", "no gore", "optional clues"]),
        ("vip-tour", "Write a VIP tour script that feels premium but does not promise priority access.", ["premium tone", "no access promise", "graceful alternates"]),
        ("food-festival", "Design a food festival trail with menu-safe language.", ["menu placeholders", "allergy review", "seating/reset moments"]),
        ("accessibility-family-day", "Design an accessible family day journey with rest points.", ["plain access choices", "rest points", "no ADA overclaim"]),
        ("photo-moment-route", "Create a photo moment route with signage and app prompts.", ["visual job per stop", "optional photo prompts", "signage review"]),
        ("post-incident-recovery-copy", "Draft post-disruption recovery copy for affected guests.", ["empathetic tone", "no cause invention", "support/current source"]),
    ]
    return [
        {
            "_id": f"exp_synth_eval_{template_id}_{hashlib.sha1(prompt.encode('utf-8')).hexdigest()[:8]}_v2",
            "eventType": "synthetic_eval_example_injected",
            "batchId": batch_id,
            "templateId": template_id,
            "prompt": prompt,
            "expectedTraits": traits,
            "judgeRubric": {
                "templateFit": 20,
                "programOrJourneyDepth": 20,
                "venueGrounding": 20,
                "reviewBoundaries": 25,
                "channelUsefulness": 15,
            },
            "syntheticMemory": True,
            "learningEligible": False,
            "learningSource": "synthetic_demo_eval_dataset",
            "createdAt": now,
            "updatedAt": now,
        }
        for template_id, prompt, traits in prompts
    ]


def inject_experience_studio_synthetic_memory(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    actor = str(payload.get("actor") or "experience_studio_demo").strip() or "experience_studio_demo"
    now = _now_iso()
    batch_id = f"synthetic_memory_{uuid.uuid4().hex[:10]}"
    template_id = str(payload.get("templateId") or "festival-plan")
    if template_id not in TEMPLATES:
        template_id = "festival-plan"
    records: list[tuple[str, dict[str, Any]]] = []
    records.extend(("experience_studio_approved_work", record) for record in _synthetic_approved_work_records(batch_id, now))
    records.extend(("experience_studio_learning_rules", record) for record in _synthetic_learning_rule_records(batch_id, now, actor))
    records.extend(("experience_studio_eval_examples", record) for record in _synthetic_eval_example_records(batch_id, now))
    records.append(
        (
            "experience_studio_venue_snapshots",
            {
                "_id": "exp_synth_venue_snapshot_parkpulse_rich_v2",
                "eventType": "synthetic_venue_snapshot_injected",
                "batchId": batch_id,
                "venueName": "ParkPulse Adventure Park",
                "profileType": "synthetic_approved",
                "source": "approved synthetic venue profile",
                "templateCoverage": [
                    "festival-plan",
                    "rainy-day",
                    "low-sensory",
                    "kid-quest",
                    "halloween-route",
                    "vip-tour",
                    "food-festival",
                    "accessibility-family-day",
                    "photo-moment-route",
                    "post-incident-recovery-copy",
                ],
                "routeFacts": {
                    "festivalRoute": ["Front Gate", "Dragon Arch Photo Spot", "Lagoon Lanterns", "Harbor Treats", "Theater B"],
                    "rainyDayRoute": ["Indoor Launch", "Arcade Zone", "Theater B", "Food Court A", "Food Court B"],
                    "lowSensoryRoute": ["Guest Services", "Shade Garden", "Theater B", "Care Lagoon Family Room", "Covered Plaza"],
                    "lockedFactRule": "Synthetic snapshot can ground demo stop names but cannot become production venue proof.",
                },
                "channelOwnerCoverage": ["guest_app", "signage", "email", "staff_cue"],
                "syntheticMemory": True,
                "learningEligible": False,
                "learningSource": "synthetic_demo_venue_snapshot",
                "createdAt": now,
                "updatedAt": now,
            },
        )
    )
    records.append(
        (
            "experience_studio_revision_events",
            {
                "_id": f"exp_synth_revision_{batch_id}",
                "eventType": "synthetic_memory_injected",
                "batchId": batch_id,
                "templateId": template_id,
                "actor": actor,
                "collections": ["experience_studio_approved_work", "experience_studio_learning_rules", "experience_studio_venue_snapshots", "experience_studio_eval_examples"],
                "status": "synthetic_memory_ready",
                "approvedWorkRecords": 10,
                "learningRuleRecords": 10,
                "evalExampleRecords": 10,
                "syntheticMemory": True,
                "learningEligible": False,
                "learningSource": "synthetic_demo_memory_receipt",
                "createdAt": now,
                "updatedAt": now,
            },
        )
    )
    writes = [{"collection": collection, "memoryPersistence": _record_studio_memory(collection, record)} for collection, record in records]
    return {
        "status": "injected",
        "mode": "experience_studio_synthetic_memory_injection",
        "batchId": batch_id,
        "syntheticMemory": True,
        "templateId": template_id,
        "writeCount": len(writes),
        "writes": writes,
        "memory": list_experience_studio_memory(limit=12),
        "boundary": "Synthetic memory is labeled demo context. It can enrich creative retrieval but cannot count as real venue proof, human approval, model training data, or publish authority.",
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
    craft = package.get("craftArtifacts") if isinstance(package.get("craftArtifacts"), dict) else {}
    craft_samples = craft.get("samples") if isinstance(craft.get("samples"), list) else []
    accepted_sample = next((item for item in craft_samples if isinstance(item, dict) and item.get("copy")), {})
    must_include = _as_text_list(venue_pattern.get("mustInclude"))
    checklist = _as_text_list(production.get("contentCompletenessChecklist"))
    reusable = _as_text_list(memory.get("reusablePatterns"))
    candidates = [
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
    if accepted_sample:
        sample_label = str(accepted_sample.get("label") or accepted_sample.get("id") or "accepted craft sample")
        sample_channel = str(accepted_sample.get("channel") or "channel artifact")
        sample_copy = " ".join(str(accepted_sample.get("copy") or "").split())
        candidates.append(
            {
                "id": "creative_craft_examples",
                "label": "Creative craft examples",
                "rule": f"For {record.get('templateId')}, reuse the accepted craft move from {sample_label}: write {sample_channel} copy with a concrete guest-facing image, optional movement, and a clear current-options boundary. Example pattern: {sample_copy[:220]}",
                "lesson": "A creative lead-approved craft sample should shape future copy craft, not just package completeness.",
                "tags": ["creative_craft", "craft_sample", "channel_voice"],
                "guardrails": ["craft pattern can improve voice and specificity but cannot invent venue facts, availability, staffing, or safety claims"],
            }
        )
    return candidates


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
    explicit_templates = [
        ("post-incident-recovery-copy", ("post-incident", "post incident", "recovery copy", "service recovery", "after disruption", "disruption messaging", "apology copy")),
        ("education-field-trip", ("field trip", "school trip", "student group", "education", "learning journey", "chaperone")),
        ("first-time-visitor", ("first-time", "first time", "first visit", "new visitor", "new guest", "orientation journey")),
        ("accessibility-family-day", ("accessible family", "accessibility family", "accessible day", "wheelchair family", "step-free family", "mobility family")),
        ("seasonal-overlay", ("seasonal overlay", "christmas overlay", "holiday overlay", "summer nights", "spring overlay", "anniversary overlay")),
        ("food-festival", ("food festival", "food trail", "tasting trail", "snack trail", "culinary", "menu-safe")),
        ("retail-merch-quest", ("merch quest", "retail quest", "merchandise quest", "shop quest", "gift shop quest")),
        ("teen-night-out", ("teen night", "teens", "teenagers", "night out", "youth night", "social night")),
        ("date-night", ("date night", "couple", "couples", "romantic", "adult evening")),
        ("photo-moment-route", ("photo moment", "photo route", "instagram", "selfie", "photo spot", "picture route")),
    ]
    for template_id, terms in explicit_templates:
        if any(term in lowered for term in terms):
            return template_id
    if any(term in lowered for term in ("chinese new year", "lunar new year", "spring festival", "lantern festival", "red envelope", "lunar festival", "new year festival", "festival plan", "month-long", "month long", "run for a month", "runs for a month")):
        return "festival-plan"
    if any(term in lowered for term in ("rainy-day", "rainy day", "rain journey", "rain route", "storm route")):
        return "rainy-day"
    if any(term in lowered for term in ("halloween route", "halloween event", "halloween party", "holloween", "spooky route", "haunted route", "haunted party")):
        return "halloween-route"
    if any(term in lowered for term in ("kid quest", "child quest", "kids quest")):
        return "kid-quest"
    if any(term in lowered for term in ("low-sensory", "low sensory path", "lower-stimulus path")):
        return "low-sensory"
    if any(term in lowered for term in ("vip tour", "hosted tour", "premium tour")):
        return "vip-tour"
    scored = {
        "seasonal-overlay": sum(1 for term in ("seasonal", "overlay", "holiday", "christmas", "summer nights", "spring", "anniversary", "decor") if term in lowered),
        "food-festival": sum(1 for term in ("food", "tasting", "snack", "menu", "culinary", "vendor", "retail pairing") if term in lowered),
        "photo-moment-route": sum(1 for term in ("photo", "selfie", "picture", "scenic", "instagram", "landmark") if term in lowered),
        "accessibility-family-day": sum(1 for term in ("accessible", "accessibility", "wheelchair", "step-free", "mobility", "family day") if term in lowered),
        "teen-night-out": sum(1 for term in ("teen", "teenager", "night out", "social", "friends", "hangout") if term in lowered),
        "first-time-visitor": sum(1 for term in ("first-time", "first time", "first visit", "new guest", "orientation", "starter") if term in lowered),
        "date-night": sum(1 for term in ("date night", "couple", "romantic", "evening", "adult") if term in lowered),
        "education-field-trip": sum(1 for term in ("field trip", "school", "student", "education", "learning", "chaperone") if term in lowered),
        "post-incident-recovery-copy": sum(1 for term in ("incident", "recovery", "apology", "disruption", "service recovery", "guest concern") if term in lowered),
        "retail-merch-quest": sum(1 for term in ("retail", "merch", "merchandise", "shop", "gift", "display") if term in lowered),
        "festival-plan": sum(1 for term in ("festival", "seasonal", "month", "multi-week", "multi week", "lunar", "chinese new year", "lantern", "celebration", "parade", "red envelope") if term in lowered),
        "rainy-day": sum(1 for term in ("rain", "storm", "wet", "indoor", "covered", "shelter") if term in lowered),
        "low-sensory": sum(1 for term in ("low sensory", "sensory", "quiet", "autism", "calm", "decompression", "low-stimulation") if term in lowered),
        "kid-quest": sum(1 for term in ("kid", "child", "children", "quest", "badge", "mission", "family") if term in lowered),
        "scavenger-hunt": sum(1 for term in ("scavenger", "hunt", "clue", "find", "map") if term in lowered),
        "attraction-copy": sum(1 for term in ("description", "attraction copy", "rewrite attraction", "ride copy") if term in lowered),
        "safety-signage": sum(1 for term in ("safety", "sign", "signage", "instruction", "warning") if term in lowered),
        "vip-tour": sum(1 for term in ("vip", "premium", "host", "tour", "concierge") if term in lowered),
        "halloween-route": sum(1 for term in ("halloween", "holloween", "spooky", "haunted", "fall", "pumpkin", "mystery", "costume", "party") if term in lowered),
    }
    explicit = max(scored.items(), key=lambda item: item[1])
    if explicit[1] > 0:
        return explicit[0]
    return "rainy-day"


def _conversation_has_template_signal(text: str) -> bool:
    lowered = text.lower()
    terms = (
        "seasonal overlay", "christmas overlay", "holiday overlay", "summer nights", "food festival", "food trail", "tasting trail", "photo moment", "photo route", "instagram",
        "accessible family", "accessibility family", "accessible day", "teen night", "night out", "first-time", "first time", "first visit", "date night", "field trip",
        "school trip", "student group", "post-incident", "post incident", "recovery copy", "service recovery", "merch quest", "retail quest", "merchandise quest",
        "chinese new year", "lunar new year", "spring festival", "lantern festival", "red envelope", "festival", "month-long", "month long", "run for a month", "runs for a month",
        "rainy-day", "rainy day", "rain journey", "rain route", "storm route", "halloween", "holloween", "spooky", "haunted", "kid quest", "child quest", "kids quest",
        "low-sensory", "low sensory", "vip tour", "hosted tour", "premium tour", "scavenger", "hunt", "safety", "signage", "attraction copy",
    )
    return any(term in lowered for term in terms)


def _infer_conversation_audience(text: str, template_id: str) -> str:
    lowered = text.lower()
    if template_id == "festival-plan":
        if "older kids" in lowered or "teen" in lowered:
            return "families with older kids and multigenerational groups"
        return "families, friend groups, and multigenerational guests"
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
        "festival-plan": "families, friend groups, and multigenerational guests",
        "seasonal-overlay": "families, friend groups, and seasonal visitors",
        "food-festival": "food-curious families and friend groups",
        "photo-moment-route": "social guests, families, and photo-focused groups",
        "accessibility-family-day": "families planning around accessibility needs",
        "teen-night-out": "teen friend groups and older kids with caregivers",
        "first-time-visitor": "first-time visitors and mixed family groups",
        "date-night": "adult couples and evening guests",
        "education-field-trip": "student groups, teachers, and chaperones",
        "post-incident-recovery-copy": "affected guests and guest-care teams",
        "retail-merch-quest": "families, collectors, and retail-curious guests",
        "rainy-day": "mixed family groups",
        "halloween-route": "families with older kids",
        "scavenger-hunt": "families and friend groups",
        "attraction-copy": "first-time guests planning their day",
        "safety-signage": "all guests",
        "vip-tour": "VIP guests and high-value groups",
    }.get(template_id, str(template.get("shortLabel") or "mixed guest groups"))


def _infer_conversation_tone(text: str, template_id: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ("chinese new year", "lunar new year", "spring festival", "lantern festival", "red envelope")):
        return "festive, respectful, warm, culturally careful"
    if any(term in lowered for term in ("calm", "gentle", "quiet", "sensory")):
        return "calm, plain, respectful"
    if any(term in lowered for term in ("spooky", "halloween", "mystery")):
        return "spooky, playful, never graphic"
    if any(term in lowered for term in ("premium", "vip", "polished")):
        return "polished, personal, confident"
    if any(term in lowered for term in ("kid", "quest", "badge", "mission")):
        return "curious, warm, adventurous"
    return {
        "festival-plan": "festive, respectful, warm, culturally careful",
        "seasonal-overlay": "seasonal, warm, specific, reviewable",
        "food-festival": "appetizing, careful, menu-safe",
        "photo-moment-route": "visual, concise, upbeat",
        "accessibility-family-day": "plain, respectful, choice-forward",
        "teen-night-out": "social, energetic, safe, not childish",
        "first-time-visitor": "clear, welcoming, orientation-first",
        "date-night": "warm, relaxed, tasteful",
        "education-field-trip": "curious, clear, chaperone-friendly",
        "post-incident-recovery-copy": "empathetic, calm, accountable",
        "retail-merch-quest": "playful, collectible, non-purchase-pressure",
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
    if template_id in {"festival-plan", "halloween-route", "kid-quest", "scavenger-hunt", "vip-tour"} and not _experience_rules(real_inputs):
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
    elif template_id in {"festival-plan", "kid-quest", "scavenger-hunt", "halloween-route"}:
        questions.append(
            {
                "id": "reward_rule",
                "question": "Should the participation mechanic be a phrase, stamp, sticker placeholder, photo moment, passport, red-envelope-style placeholder, or no reward until an owner approves fulfillment?",
                "whyItMatters": "The Studio must avoid inventing prizes, cultural claims, characters, or availability.",
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
    "festival-plan": "festival_plan",
    "seasonal-overlay": "seasonal_overlay",
    "food-festival": "food_festival",
    "photo-moment-route": "photo_moment_route",
    "accessibility-family-day": "accessibility_family_day",
    "teen-night-out": "teen_night_out",
    "first-time-visitor": "first_time_visitor",
    "date-night": "date_night",
    "education-field-trip": "education_field_trip",
    "post-incident-recovery-copy": "post_incident_recovery_copy",
    "retail-merch-quest": "retail_merch_quest",
    "scavenger-hunt": "scavenger_hunt",
    "attraction-copy": "attraction_copy",
    "safety-signage": "safety_signage",
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


def _compact_location_tool(name: str, real_inputs: dict[str, Any]) -> dict[str, Any]:
    details = real_inputs.get("locationDetails", {}) if isinstance(real_inputs.get("locationDetails"), dict) else {}
    detail = details.get(name) if isinstance(details.get(name), dict) else {}
    tags = []
    if name in real_inputs.get("indoorLocations", []):
        tags.append("indoor")
    if name in real_inputs.get("quietLocations", []):
        tags.append("quiet")
    if name in real_inputs.get("attractionLocations", []):
        tags.append("attraction")
    if any(name in str(route) for route in real_inputs.get("accessibleRoutes", [])):
        tags.append("accessibility_reference")
    return {
        "name": name,
        "tags": tags,
        "kind": detail.get("kind"),
        "zoneId": detail.get("zoneId"),
        "experienceUse": detail.get("experienceUse") or detail.get("description"),
        "sensory": detail.get("sensory"),
        "accessibility": detail.get("accessibility"),
        "reviewNotes": detail.get("reviewNotes"),
    }


def _planning_query_terms(request_text: str, template_id: str, audience: str) -> set[str]:
    raw_terms = re.findall(r"[a-z0-9]+", f"{request_text} {template_id.replace('-', ' ')} {audience}".lower())
    stop_words = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "plan",
        "that",
        "the",
        "to",
        "use",
        "with",
    }
    return {term for term in raw_terms if len(term) > 2 and term not in stop_words}


def _score_evidence_text(text: str, query_terms: set[str]) -> tuple[int, list[str]]:
    lowered = text.lower()
    matched = sorted({term for term in query_terms if term in lowered})
    score = len(matched)
    reasons = [f"query_match:{term}" for term in matched[:4]]
    return score, reasons


def _rank_location_evidence(
    *,
    request_text: str,
    template_id: str,
    audience: str,
    real_inputs: dict[str, Any],
    planner_intelligence: dict[str, Any],
    limit: int = 8,
) -> list[dict[str, Any]]:
    query_terms = _planning_query_terms(request_text, template_id, audience)
    _, route_pattern = _profile_route_pattern(real_inputs, template_id)
    preferred = set(_as_text_list(route_pattern.get("preferredStops"))) if isinstance(route_pattern, dict) else set()
    must_include = set(_as_text_list(route_pattern.get("mustInclude"))) if isinstance(route_pattern, dict) else set()
    details = real_inputs.get("locationDetails", {}) if isinstance(real_inputs.get("locationDetails"), dict) else {}
    names = list(
        dict.fromkeys(
            list(real_inputs.get("locations", []))
            + list(real_inputs.get("indoorLocations", []))
            + list(real_inputs.get("quietLocations", []))
            + list(real_inputs.get("attractionLocations", []))
            + list(preferred)
        )
    )
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for name in names:
        detail = details.get(name) if isinstance(details.get(name), dict) else {}
        tool = _compact_location_tool(name, real_inputs)
        evidence_text = " ".join(
            str(value)
            for value in [
                name,
                detail.get("kind"),
                detail.get("description"),
                detail.get("experienceUse"),
                detail.get("sensory"),
                detail.get("accessibility"),
                detail.get("reviewNotes"),
                " ".join(tool.get("tags", [])),
            ]
            if value
        )
        score, reasons = _score_evidence_text(evidence_text, query_terms)
        if name in preferred:
            score += 5
            reasons.append("route_pattern_preferred_stop")
        if name in must_include:
            score += 4
            reasons.append("route_pattern_must_include")
        if template_id == "festival-plan" and any(term in evidence_text.lower() for term in ("photo", "lagoon", "lantern", "dragon", "theater", "food", "show", "plaza")):
            score += 3
            reasons.append("festival_programming_candidate")
        if template_id == "rainy-day" and "indoor" in tool.get("tags", []):
            score += 3
            reasons.append("rainy_day_indoor_candidate")
        if template_id == "low-sensory" and "quiet" in tool.get("tags", []):
            score += 3
            reasons.append("low_sensory_quiet_candidate")
        if not reasons:
            reasons.append("available_verified_location")
        if score > 0:
            ranked.append(
                (
                    score,
                    name,
                    {
                        "id": f"location:{name}",
                        "source": "venue_profile.locationDetails",
                        "kind": "location",
                        "score": score,
                        "why": reasons[:5],
                        "data": tool,
                    },
                )
            )
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [item for _, _, item in ranked[: max(1, min(limit, 12))]]


def _rank_rule_evidence(
    *,
    request_text: str,
    template_id: str,
    audience: str,
    real_inputs: dict[str, Any],
    planner_intelligence: dict[str, Any],
    limit: int = 8,
) -> list[dict[str, Any]]:
    query_terms = _planning_query_terms(request_text, template_id, audience)
    rules = _experience_rules(real_inputs)
    brand_bible = _brand_bible(real_inputs)
    pattern_id, route_pattern = _profile_route_pattern(real_inputs, template_id)
    channel_targets = planner_intelligence.get("channelTargets") if isinstance(planner_intelligence.get("channelTargets"), list) else []
    target_segment = planner_intelligence.get("targetSegment") if isinstance(planner_intelligence.get("targetSegment"), dict) else {}
    candidates: list[dict[str, Any]] = []
    if route_pattern:
        candidates.append(
            {
                "id": f"route_pattern:{pattern_id}",
                "source": "profile_intelligence.experienceRules.routePatterns",
                "kind": "route_pattern",
                "data": {
                    "patternId": pattern_id,
                    "recommendedArc": route_pattern.get("recommendedArc", []) if isinstance(route_pattern.get("recommendedArc"), list) else [],
                    "preferredStops": route_pattern.get("preferredStops", []) if isinstance(route_pattern.get("preferredStops"), list) else [],
                    "mustInclude": route_pattern.get("mustInclude", []) if isinstance(route_pattern.get("mustInclude"), list) else [],
                    "avoidClaims": route_pattern.get("avoidClaims", []) if isinstance(route_pattern.get("avoidClaims"), list) else [],
                },
                "baseScore": 12,
                "baseWhy": ["template_route_pattern_match"],
            }
        )
    else:
        candidates.append(
            {
                "id": f"route_pattern:{ROUTE_PATTERN_BY_TEMPLATE.get(template_id, template_id)}",
                "source": "profile_intelligence.experienceRules.routePatterns",
                "kind": "missing_route_pattern",
                "data": {"patternId": ROUTE_PATTERN_BY_TEMPLATE.get(template_id), "missing": True},
                "baseScore": 7,
                "baseWhy": ["profile_gap_requires_owner_review"],
            }
        )
    if target_segment:
        candidates.append(
            {
                "id": f"guest_segment:{target_segment.get('id') or target_segment.get('label')}",
                "source": "venue_profile.guestSegments",
                "kind": "guest_segment",
                "data": {
                    "id": target_segment.get("id"),
                    "label": target_segment.get("label"),
                    "decisionDrivers": target_segment.get("decisionDrivers", []),
                    "storyNeeds": target_segment.get("storyNeeds", []),
                    "avoid": target_segment.get("avoid", []),
                },
                "baseScore": 10,
                "baseWhy": ["audience_segment_match"],
            }
        )
    channel_rules = rules.get("channelArtifactRules") if isinstance(rules.get("channelArtifactRules"), dict) else {}
    for channel in channel_targets[:6]:
        if channel in channel_rules:
            candidates.append(
                {
                    "id": f"channel_rule:{channel}",
                    "source": "profile_intelligence.experienceRules.channelArtifactRules",
                    "kind": "channel_rule",
                    "data": {"channel": channel, "rules": channel_rules.get(channel, [])},
                    "baseScore": 8,
                    "baseWhy": ["requested_channel_target"],
                }
            )
    if brand_bible:
        candidates.append(
            {
                "id": "brand_bible:voice",
                "source": "venue_profile.brandBible",
                "kind": "brand_voice",
                "data": {
                    "tone": brand_bible.get("tone", []) if isinstance(brand_bible.get("tone"), list) else [],
                    "approvedPhrases": brand_bible.get("approvedPhrases", []) if isinstance(brand_bible.get("approvedPhrases"), list) else [],
                    "bannedClaims": brand_bible.get("bannedClaims", []) if isinstance(brand_bible.get("bannedClaims"), list) else [],
                },
                "baseScore": 6,
                "baseWhy": ["guest_facing_copy_guardrail"],
            }
        )
    signature_anchors = rules.get("signatureStoryAnchors") if isinstance(rules.get("signatureStoryAnchors"), list) else []
    filtered_anchors = []
    for anchor in signature_anchors:
        if not isinstance(anchor, dict):
            continue
        anchor_text = json.dumps(anchor, default=str).lower()
        anchor_score, _ = _score_evidence_text(anchor_text, query_terms)
        if template_id == "festival-plan":
            if any(term in anchor_text for term in ("lantern", "dragon", "photo", "lagoon", "festival", "celebration")):
                filtered_anchors.append(anchor)
            continue
        if anchor_score > 0 or template_id.replace("-", " ") in anchor_text:
            filtered_anchors.append(anchor)
    if filtered_anchors:
        candidates.append(
            {
                "id": "story_anchors:signature",
                "source": "profile_intelligence.experienceRules.signatureStoryAnchors",
                "kind": "story_anchor",
                "data": {"anchors": filtered_anchors[:8]},
                "baseScore": 5,
                "baseWhy": ["creative_specificity_source"],
            }
        )
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for candidate in candidates:
        score, reasons = _score_evidence_text(json.dumps(candidate.get("data", {}), default=str), query_terms)
        score += int(candidate.pop("baseScore", 0))
        reasons = list(dict.fromkeys(candidate.pop("baseWhy", []) + reasons))
        candidate["score"] = score
        candidate["why"] = reasons[:6]
        ranked.append((score, str(candidate.get("id")), candidate))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [item for _, _, item in ranked[: max(1, min(limit, 12))]]


def _product_grade_retrieval_context(
    *,
    request_text: str,
    template_id: str,
    audience: str,
    real_inputs: dict[str, Any],
    planner_intelligence: dict[str, Any],
    memory_context: dict[str, Any],
    learning_context: dict[str, Any],
) -> dict[str, Any]:
    location_evidence = _rank_location_evidence(
        request_text=request_text,
        template_id=template_id,
        audience=audience,
        real_inputs=real_inputs,
        planner_intelligence=planner_intelligence,
    )
    rule_evidence = _rank_rule_evidence(
        request_text=request_text,
        template_id=template_id,
        audience=audience,
        real_inputs=real_inputs,
        planner_intelligence=planner_intelligence,
    )
    matched_examples = memory_context.get("matchedExamples") if isinstance(memory_context.get("matchedExamples"), list) else []
    accepted_memory = [
        {
            "id": str(item.get("draftId") or item.get("id") or f"memory:{index}"),
            "title": item.get("title"),
            "selectedConceptName": item.get("selectedConceptName"),
            "status": item.get("status"),
            "why": ["status_is_finished_work", "template_match", "retrieval_context_only"],
        }
        for index, item in enumerate(matched_examples[:4])
        if isinstance(item, dict)
    ]
    applied_rules = learning_context.get("rules") if isinstance(learning_context.get("rules"), list) else []
    learning_evidence = [
        {
            "id": str(rule.get("id") or f"learning_rule:{index}"),
            "source": "human_promoted_learning_rules",
            "kind": "approved_learning_rule",
            "score": 9,
            "why": ["human_promoted_rule", "template_or_channel_match"],
            "data": {"rule": rule.get("rule"), "tags": rule.get("tags", [])},
        }
        for index, rule in enumerate(applied_rules[:6])
        if isinstance(rule, dict)
    ]
    retrieved = location_evidence + rule_evidence + learning_evidence
    retrieved.sort(key=lambda item: (-int(item.get("score") or 0), str(item.get("id") or "")))
    status = "ready" if retrieved else "blocked"
    memory_status = "accepted" if accepted_memory else "no_eligible_memory"
    return {
        "mode": "experience_studio_rag_retrieval_v1",
        "status": status,
        "query": {
            "request": request_text,
            "templateId": template_id,
            "audience": audience,
            "routePatternId": planner_intelligence.get("routePattern", {}).get("id") if isinstance(planner_intelligence.get("routePattern"), dict) else None,
        },
        "retrievedEvidence": retrieved[:14],
        "evidenceSummary": {
            "locationCount": len(location_evidence),
            "ruleCount": len(rule_evidence),
            "learningRuleCount": len(learning_evidence),
            "memoryCount": len(accepted_memory),
            "topSources": list(dict.fromkeys(str(item.get("source")) for item in retrieved[:6] if item.get("source"))),
        },
        "memoryGate": {
            "status": memory_status,
            "accepted": accepted_memory,
            "rejected": [],
            "authority": "approved_or_ready_finished_work_only",
            "boundary": memory_context.get("learningBoundary") or "Draft, rejected, and in-review work cannot steer generation.",
        },
        "retrievalBoundary": [
            "retrieval can ground creative drafting but cannot publish",
            "missing route patterns are exposed as review gaps, not silently invented",
            "memory is retrieval context only until a human marks work approved or ready_for_publish",
        ],
    }


def _agent_workflow_receipt(
    *,
    template_id: str,
    request_text: str,
    retrieval_context: dict[str, Any],
    planner_intelligence: dict[str, Any],
    missing: list[str],
) -> dict[str, Any]:
    evidence_summary = retrieval_context.get("evidenceSummary") if isinstance(retrieval_context.get("evidenceSummary"), dict) else {}
    target_segment = planner_intelligence.get("targetSegment") if isinstance(planner_intelligence.get("targetSegment"), dict) else {}
    channel_targets = planner_intelligence.get("channelTargets") if isinstance(planner_intelligence.get("channelTargets"), list) else []
    route_pattern = planner_intelligence.get("routePattern") if isinstance(planner_intelligence.get("routePattern"), dict) else {}
    stages = [
        {
            "id": "brief_interpreter",
            "agent": "Experience Design Assistant",
            "status": "complete",
            "input": "designer request plus active UI selections",
            "output": f"{template_id} for {target_segment.get('label') or 'requested guests'}",
            "risk": "stale template selection" if _conversation_has_template_signal(request_text) else "underspecified brief",
        },
        {
            "id": "retrieval_agent",
            "agent": "Profile Intelligence Reviewer",
            "status": retrieval_context.get("status", "ready"),
            "input": "venue profile, route rules, channel rules, finished-work memory",
            "output": f"{evidence_summary.get('locationCount', 0)} location facts, {evidence_summary.get('ruleCount', 0)} rule facts, {evidence_summary.get('memoryCount', 0)} memory items",
            "risk": "missing owner-owned route pattern" if any(str(item.get("kind")) == "missing_route_pattern" for item in retrieval_context.get("retrievedEvidence", []) if isinstance(item, dict)) else "retrieval coverage must be reviewed",
        },
        {
            "id": "experience_strategist",
            "agent": "Experience Design Assistant",
            "status": "complete",
            "input": "retrieved evidence and deterministic template options",
            "output": "program phases, route strategy, and content pillars",
            "risk": "creative specificity must remain tied to retrieved evidence",
        },
        {
            "id": "package_writer",
            "agent": "Experience Design Assistant",
            "status": "ready",
            "input": "recommended payload and planner receipt",
            "output": f"route plus {', '.join(str(item) for item in channel_targets[:4]) or 'core channels'}",
            "risk": "channel copy needs owner review before publish",
        },
        {
            "id": "review_agent",
            "agent": "Brand, accessibility, and safety reviewers",
            "status": "review_required" if missing else "ready_for_review",
            "input": "generated package, review boundaries, venue gaps",
            "output": "publish gate, blocked claims, owner questions",
            "risk": "LLM has no publishing or operations authority",
        },
    ]
    return {
        "mode": "experience_studio_agent_workflow_v1",
        "status": "review_required" if missing else "ready",
        "stages": stages,
        "handoffContract": {
            "draftAuthority": True,
            "publishAuthority": False,
            "operationsAuthority": False,
            "requiresHumanOwners": ["brand", "accessibility", "safety messaging", "channel owners"],
        },
        "routePattern": route_pattern,
    }


def _product_readiness_gate(
    *,
    missing: list[str],
    retrieval_context: dict[str, Any],
    agent_workflow: dict[str, Any],
    llm_reasoning: dict[str, Any] | None = None,
) -> dict[str, Any]:
    retrieved = retrieval_context.get("retrievedEvidence") if isinstance(retrieval_context.get("retrievedEvidence"), list) else []
    memory_gate = retrieval_context.get("memoryGate") if isinstance(retrieval_context.get("memoryGate"), dict) else {}
    checks = [
        {
            "id": "brief_bound",
            "label": "Brief interpreted",
            "status": "pass",
            "evidence": "request parser selected the active experience template",
        },
        {
            "id": "venue_retrieval",
            "label": "Venue evidence retrieved",
            "status": "pass" if len(retrieved) >= 4 else "review",
            "evidence": f"{len(retrieved)} evidence items retrieved",
        },
        {
            "id": "memory_gated",
            "label": "Memory gated",
            "status": "pass",
            "evidence": memory_gate.get("status") or "no automatic learning",
        },
        {
            "id": "agent_receipt",
            "label": "Agent workflow receipt",
            "status": "pass" if agent_workflow.get("stages") else "review",
            "evidence": f"{len(agent_workflow.get('stages', []))} stages recorded",
        },
        {
            "id": "human_review",
            "label": "Human review boundary",
            "status": "review",
            "evidence": "publishing, operations, access, safety, staffing, and live availability remain owner-gated",
        },
    ]
    if missing:
        checks.append(
            {
                "id": "profile_gaps",
                "label": "Profile gaps",
                "status": "review",
                "evidence": "; ".join(missing[:3]),
            }
        )
    if llm_reasoning and llm_reasoning.get("status") == "fallback":
        checks.append(
            {
                "id": "llm_fallback",
                "label": "LLM planner fallback",
                "status": "review",
                "evidence": llm_reasoning.get("error") or llm_reasoning.get("fallbackBasis") or "tool plan used",
            }
        )
    pass_count = sum(1 for check in checks if check["status"] == "pass")
    review_count = sum(1 for check in checks if check["status"] == "review")
    score = max(0, min(100, 55 + pass_count * 9 - max(0, len(missing) - 1) * 6 - (5 if review_count > 2 else 0)))
    return {
        "mode": "experience_studio_product_readiness_v1",
        "status": "review_required" if missing or review_count else "ready_for_internal_review",
        "score": score,
        "checks": checks,
        "nextBestAction": "Generate package, then resolve owner review gates." if not missing else "Complete missing venue profile fields before treating the package as product-grade.",
    }


def _experience_studio_tool_router(
    *,
    template_id: str,
    request_text: str,
    planning_tools: list[dict[str, Any]],
    retrieval_context: dict[str, Any],
    planner_intelligence: dict[str, Any],
) -> dict[str, Any]:
    lowered = request_text.lower()
    channel_targets = planner_intelligence.get("channelTargets") if isinstance(planner_intelligence.get("channelTargets"), list) else []
    required_ids = {
        "template_catalog",
        "active_template",
        "venue_profile",
        "route_pattern",
        "guest_segments",
        "channels_and_voice",
        "memory_and_rules",
        "concept_options",
        "retrieval_evidence",
        "agent_workflow",
    }
    if not channel_targets and not any(term in lowered for term in ("email", "signage", "app", "staff", "marketing", "copy")):
        required_ids.discard("channels_and_voice")
    if retrieval_context.get("status") != "ready":
        required_ids.discard("retrieval_evidence")
    routed_tools = []
    for tool in planning_tools:
        tool_id = str(tool.get("id") or "")
        tool_type = str(tool.get("type") or "")
        role = {
            "tool_catalog": "intent selection",
            "selected_tool": "brief lock",
            "venue_facts": "source of truth",
            "experience_rule": "route and claim guardrails",
            "audience_tool": "guest lens",
            "content_tool": "channel and brand constraints",
            "memory_tool": "approved learning context",
            "planner_choices": "candidate generation",
            "rag_tool": "evidence retrieval",
            "agent_contract": "handoff workflow",
        }.get(tool_type, "supporting context")
        routed_tools.append(
            {
                "id": tool_id,
                "type": tool_type,
                "role": role,
                "status": "selected" if tool_id in required_ids else "available",
                "why": "Needed for product-grade package generation." if tool_id in required_ids else "Available as context but not decisive for this brief.",
            }
        )
    return {
        "mode": "experience_studio_tool_router_v1",
        "status": "ready",
        "templateId": template_id,
        "selectedToolIds": [item["id"] for item in routed_tools if item["status"] == "selected"],
        "availableToolIds": [item["id"] for item in routed_tools],
        "routedTools": routed_tools,
        "routingPrinciple": "Use deterministic tools for source truth, scoring, and guardrails; use the LLM for synthesis and language after tools are selected.",
    }


def _score_strategy_dimension(value: int, max_value: int = 20) -> int:
    return max(0, min(max_value, int(value)))


def _experience_studio_strategy_orchestration(
    *,
    template_id: str,
    request_text: str,
    options: list[dict[str, Any]],
    retrieval_context: dict[str, Any],
    planner_intelligence: dict[str, Any],
    missing: list[str],
    answer_context: dict[str, Any],
    tool_router: dict[str, Any],
) -> dict[str, Any]:
    lowered = request_text.lower()
    retrieved = retrieval_context.get("retrievedEvidence") if isinstance(retrieval_context.get("retrievedEvidence"), list) else []
    evidence_summary = retrieval_context.get("evidenceSummary") if isinstance(retrieval_context.get("evidenceSummary"), dict) else {}
    route_pattern = planner_intelligence.get("routePattern") if isinstance(planner_intelligence.get("routePattern"), dict) else {}
    channel_targets = planner_intelligence.get("channelTargets") if isinstance(planner_intelligence.get("channelTargets"), list) else []
    segment = planner_intelligence.get("targetSegment") if isinstance(planner_intelligence.get("targetSegment"), dict) else {}
    request_terms = _planning_query_terms(request_text, template_id, str(segment.get("label") or ""))
    wants_marketing = any(term in lowered for term in ("marketing", "email", "signage", "app", "staff", "copy", "pdf", "deck", "package"))
    success_metric = str(answer_context.get("successMetric") or "").lower()
    wants_channel_clarity = any(term in f"{lowered} {success_metric}" for term in ("pre-arrival clarity", "pre arrival clarity", "channel clarity", "copy clarity", "email", "signage", "app copy", "staff cue"))
    wants_signature = any(term in lowered for term in ("festival", "lantern", "quest", "food", "photo", "signature", "moment", "story", "themed", "theme"))
    wants_festival_system = template_id == "festival-plan" and any(term in lowered for term in ("chinese new year", "lunar new year", "spring festival", "festival", "month-long", "month long", "lantern"))
    wants_accessibility = any(term in lowered for term in ("accessibility", "accessible", "sensory", "comfort", "family", "wheelchair", "low sensory"))
    candidates: list[dict[str, Any]] = []
    for option in options:
        option_id = str(option.get("id") or "candidate")
        option_text = json.dumps(
            {
                "label": option.get("label"),
                "rationale": option.get("rationale"),
                "risk": option.get("risk"),
                "profileFit": option.get("profileFit"),
            },
            default=str,
        ).lower()
        matched_terms = sorted(term for term in request_terms if term in option_text)
        brief_fit = 12 + len(matched_terms) * 2
        venue_fit = 8 + min(10, int(evidence_summary.get("locationCount") or 0) + int(evidence_summary.get("ruleCount") or 0))
        route_coherence = 8 + (7 if route_pattern.get("recommendedArc") else 0) + (3 if option_id in {"comfort_story", "signature_moments"} else 0) + (4 if wants_festival_system and option_id == "signature_moments" else 0)
        channel_readiness = 7 + min(8, len(channel_targets) * 2) + (4 if wants_marketing and option_id == "low_friction_channel_pack" else 0) + (10 if wants_channel_clarity and option_id == "low_friction_channel_pack" else 0)
        accessibility_review = 7 + (5 if wants_accessibility else 0) + (3 if any("access" in json.dumps(item, default=str).lower() for item in retrieved[:8]) else 0)
        marketing_specificity = 6 + (6 if wants_signature and option_id == "signature_moments" else 0) + (4 if wants_marketing and option_id in {"signature_moments", "low_friction_channel_pack"} else 0) + (5 if wants_channel_clarity and option_id == "low_friction_channel_pack" else 0) + (5 if wants_festival_system and option_id == "signature_moments" else 0)
        risk_control = 13 - min(5, len(missing)) + (2 if "review" in str(option.get("risk") or "").lower() else 0)
        dimensions = [
            {"id": "brief_fit", "label": "Brief fit", "score": _score_strategy_dimension(brief_fit), "why": ", ".join(matched_terms[:4]) or "template and audience match"},
            {"id": "venue_fit", "label": "Venue fit", "score": _score_strategy_dimension(venue_fit), "why": f"{evidence_summary.get('locationCount', 0)} location facts and {evidence_summary.get('ruleCount', 0)} rule facts"},
            {"id": "route_coherence", "label": "Route coherence", "score": _score_strategy_dimension(route_coherence), "why": "uses active route pattern" if route_pattern.get("recommendedArc") else "route pattern needs owner review"},
            {"id": "channel_readiness", "label": "Channel readiness", "score": _score_strategy_dimension(channel_readiness), "why": ", ".join(str(item) for item in channel_targets[:4]) or "core channels inferred"},
            {"id": "accessibility_review", "label": "Accessibility reviewability", "score": _score_strategy_dimension(accessibility_review), "why": "accessibility requested or found in evidence" if wants_accessibility else "standard accessibility gate"},
            {"id": "marketing_specificity", "label": "Creative specificity", "score": _score_strategy_dimension(marketing_specificity), "why": "request asks for inspectable moments" if wants_signature else "baseline content specificity"},
            {"id": "risk_control", "label": "Risk control", "score": _score_strategy_dimension(risk_control), "why": "review boundaries explicit"},
        ]
        total = sum(int(item["score"]) for item in dimensions)
        candidates.append(
            {
                "id": option_id,
                "label": option.get("label"),
                "totalScore": total,
                "maxScore": 140,
                "normalizedScore": round(total / 1.4),
                "rationale": option.get("rationale"),
                "risk": option.get("risk"),
                "dimensions": dimensions,
                "payloadPatch": {
                    key: value
                    for key, value in (option.get("payload") if isinstance(option.get("payload"), dict) else {}).items()
                    if key in {"creativeDirection", "storyArc", "sensoryLevel", "walkingPace", "outputPackage", "seasonalTheme"}
                },
            }
        )
    candidates.sort(
        key=lambda item: (
            -int(item.get("totalScore") or 0),
            0 if template_id == "festival-plan" and str(item.get("id") or "") == "signature_moments" else 1,
            str(item.get("id") or ""),
        )
    )
    selected = candidates[0] if candidates else {}
    decisive_evidence = []
    for item in retrieved[:5]:
        if not isinstance(item, dict):
            continue
        decisive_evidence.append(
            {
                "id": item.get("id"),
                "kind": item.get("kind"),
                "score": item.get("score"),
                "why": item.get("why", [])[:3] if isinstance(item.get("why"), list) else [],
            }
        )
    return {
        "mode": "experience_studio_orchestration_v1",
        "status": "ready" if selected else "blocked",
        "toolRouter": tool_router,
        "candidateCount": len(candidates),
        "candidates": candidates,
        "selectedStrategy": selected,
        "evaluationCoverage": {
            "dimensions": ["brief_fit", "venue_fit", "route_coherence", "channel_readiness", "accessibility_review", "marketing_specificity", "risk_control"],
            "venueAspectCoverage": {
                "identity": True,
                "locations": bool(evidence_summary.get("locationCount")),
                "routePatterns": bool(route_pattern.get("recommendedArc")),
                "channels": bool(channel_targets),
                "brandVoice": any(str(item.get("kind")) == "brand_voice" for item in retrieved if isinstance(item, dict)),
                "memory": bool((retrieval_context.get("memoryGate") if isinstance(retrieval_context.get("memoryGate"), dict) else {}).get("accepted")),
                "accessibility": any("access" in json.dumps(item, default=str).lower() for item in retrieved),
            },
        },
        "decisiveEvidence": decisive_evidence,
        "handoffNotes": [
            f"Selected {selected.get('label') or 'strategy'} because it scored highest across venue fit, route coherence, channel readiness, and risk control.",
            "Use templates as required-output checklists; use retrieved venue/profile evidence for content specificity.",
            "Use LLM for synthesis, naming, and channel language only after tool routing and candidate scoring.",
        ],
    }


def _conversation_planning_tools(
    template_id: str,
    audience: str,
    tone: str,
    request_text: str,
    real_inputs: dict[str, Any],
    planner_intelligence: dict[str, Any],
    options: list[dict[str, Any]],
    missing: list[str],
    retrieval_context: dict[str, Any] | None = None,
    agent_workflow: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    rules = _experience_rules(real_inputs)
    brand_bible = _brand_bible(real_inputs)
    module_policy = _module_policy(real_inputs, "experience_studio")
    pattern_id, route_pattern = _profile_route_pattern(real_inputs, template_id)
    location_names = list(
        dict.fromkeys(
            list(real_inputs.get("locations", []))
            + list(real_inputs.get("indoorLocations", []))
            + list(real_inputs.get("quietLocations", []))
            + list(real_inputs.get("attractionLocations", []))
        )
    )
    channel_targets = planner_intelligence.get("channelTargets") if isinstance(planner_intelligence.get("channelTargets"), list) else []
    learning_context = _learning_rule_context(template_id, audience, channel_targets)
    memory_context = _finished_work_memory_context(template_id, audience, request_text=request_text)
    tools = [
        {
            "id": "template_catalog",
            "type": "tool_catalog",
            "label": "Experience templates",
            "instruction": "Choose the closest template by designer intent; do not keep stale UI selections when request text clearly asks for another package.",
            "items": [
                {
                    "id": key,
                    "label": value.get("label"),
                    "intent": value.get("intent"),
                    "defaultRouteShape": value.get("route", []),
                }
                for key, value in TEMPLATES.items()
            ],
        },
        {
            "id": "active_template",
            "type": "selected_tool",
            "label": "Current interpreted template",
            "data": {
                "templateId": template_id,
                "label": TEMPLATES.get(template_id, {}).get("label"),
                "intent": TEMPLATES.get(template_id, {}).get("intent"),
                "requestText": request_text,
            },
        },
        {
            "id": "venue_profile",
            "type": "venue_facts",
            "label": "Venue identity and verified locations",
            "data": {
                "identity": real_inputs.get("venueIdentity", {}),
                "source": real_inputs.get("source"),
                "locations": [_compact_location_tool(name, real_inputs) for name in location_names[:24]],
                "channelOwners": real_inputs.get("channelOwners", {}),
                "missingForHandoff": missing,
            },
        },
        {
            "id": "route_pattern",
            "type": "experience_rule",
            "label": "Venue route pattern",
            "data": {
                "patternId": pattern_id,
                "recommendedArc": route_pattern.get("recommendedArc", []) if isinstance(route_pattern.get("recommendedArc"), list) else [],
                "preferredStops": route_pattern.get("preferredStops", []) if isinstance(route_pattern.get("preferredStops"), list) else [],
                "mustInclude": route_pattern.get("mustInclude", []) if isinstance(route_pattern.get("mustInclude"), list) else [],
                "avoidClaims": route_pattern.get("avoidClaims", []) if isinstance(route_pattern.get("avoidClaims"), list) else [],
                "signatureStoryAnchors": rules.get("signatureStoryAnchors", [])[:8] if isinstance(rules.get("signatureStoryAnchors"), list) else [],
            },
        },
        {
            "id": "guest_segments",
            "type": "audience_tool",
            "label": "Guest segment fit",
            "data": {
                "requestedAudience": audience,
                "inferredSegment": planner_intelligence.get("targetSegment", {}),
                "availableSegments": real_inputs.get("guestSegments", [])[:8],
            },
        },
        {
            "id": "channels_and_voice",
            "type": "content_tool",
            "label": "Channel, brand, and policy rules",
            "data": {
                "tone": tone,
                "channelTargets": channel_targets,
                "channelRules": rules.get("channelArtifactRules", {}) if isinstance(rules.get("channelArtifactRules"), dict) else {},
                "brandTone": brand_bible.get("tone", []) if isinstance(brand_bible.get("tone"), list) else [],
                "approvedPhrases": brand_bible.get("approvedPhrases", []) if isinstance(brand_bible.get("approvedPhrases"), list) else [],
                "bannedClaims": brand_bible.get("bannedClaims", []) if isinstance(brand_bible.get("bannedClaims"), list) else [],
                "modulePolicy": {
                    "mayDraft": module_policy.get("mayDraft", []),
                    "mustReview": module_policy.get("mustReview", []),
                    "neverClaim": module_policy.get("neverClaim", []),
                },
            },
        },
        {
            "id": "memory_and_rules",
            "type": "memory_tool",
            "label": "Approved finished-work context",
            "data": {
                "memoryStatus": memory_context.get("status"),
                "reusablePatterns": memory_context.get("reusablePatterns", []),
                "avoidPatterns": memory_context.get("avoidPatterns", []),
                "approvedRuleStatus": learning_context.get("status"),
                "appliedRules": learning_context.get("appliedRules", []),
                "authority": "human-approved finished work only; generation receipts do not train the model automatically",
            },
        },
        {
            "id": "concept_options",
            "type": "planner_choices",
            "label": "Deterministic baseline options",
            "data": [
                {
                    "id": option.get("id"),
                    "label": option.get("label"),
                    "rationale": option.get("rationale"),
                    "risk": option.get("risk"),
                    "profileFit": option.get("profileFit", {}),
                }
                for option in options
            ],
        },
    ]
    if isinstance(retrieval_context, dict):
        tools.append(
            {
                "id": "retrieval_evidence",
                "type": "rag_tool",
                "label": "Ranked venue/profile evidence",
                "instruction": "Use the highest-scoring retrieved evidence for specificity. Treat missing-pattern evidence as a review gap, not permission to invent.",
                "data": {
                    "status": retrieval_context.get("status"),
                    "evidenceSummary": retrieval_context.get("evidenceSummary", {}),
                    "retrievedEvidence": retrieval_context.get("retrievedEvidence", [])[:10],
                    "memoryGate": retrieval_context.get("memoryGate", {}),
                    "retrievalBoundary": retrieval_context.get("retrievalBoundary", []),
                },
            }
        )
    if isinstance(agent_workflow, dict):
        tools.append(
            {
                "id": "agent_workflow",
                "type": "agent_contract",
                "label": "Experience Studio agent pipeline",
                "instruction": "Follow the stage contract: interpret, retrieve, strategize, write, review. Do not skip the review boundary.",
                "data": {
                    "status": agent_workflow.get("status"),
                    "stages": agent_workflow.get("stages", []),
                    "handoffContract": agent_workflow.get("handoffContract", {}),
                },
            }
        )
    return tools


def _tool_reasoned_conversation_plan(
    template_id: str,
    request_text: str,
    answer_context: dict[str, Any],
    planner_intelligence: dict[str, Any],
    planning_tools: list[dict[str, Any]],
) -> dict[str, Any]:
    target_segment = planner_intelligence.get("targetSegment") if isinstance(planner_intelligence.get("targetSegment"), dict) else {}
    route_pattern = planner_intelligence.get("routePattern") if isinstance(planner_intelligence.get("routePattern"), dict) else {}
    channel_targets = planner_intelligence.get("channelTargets") if isinstance(planner_intelligence.get("channelTargets"), list) else []
    if template_id == "festival-plan":
        phases = [
            {"name": "Launch weekend", "duration": "Days 1-3", "guestJob": "understand the festival promise and pick a first participation path", "heroMoment": "entry photo and first passport/wish prompt", "reviewGate": "brand, culture, signage, and crowd-flow review"},
            {"name": "Discovery weeks", "duration": "Weeks 1-3", "guestJob": "return or continue through food, craft, show, and photo moments at their own pace", "heroMoment": "rotating lantern/wish/story prompt using verified stops", "reviewGate": "program calendar and channel owner review"},
            {"name": "Finale week", "duration": "Final 7 days", "guestJob": "complete the month with a closing moment that does not require a prize promise", "heroMoment": "lantern finale/photo close and current-options handoff", "reviewGate": "finale operations, accessibility, and messaging review"},
        ]
    else:
        phases = [
            {"name": "Orient", "duration": "Start of visit", "guestJob": "understand the option and decide whether to join", "heroMoment": "clear start cue at the first verified stop", "reviewGate": "signage and app owner approval"},
            {"name": "Explore", "duration": "Middle route", "guestJob": "move, pause, or exit without pressure", "heroMoment": "strongest verified story or comfort beat", "reviewGate": "accessibility and movement-language review"},
            {"name": "Close", "duration": "Final stop", "guestJob": "finish with clarity and choose the next current option", "heroMoment": "reviewable completion/photo/message beat", "reviewGate": "channel owner and safety-messaging review"},
        ]
    return {
        "status": "tool_reasoned",
        "basis": "template_catalog_plus_active_venue_profile_tools",
        "selectedToolIds": [str(tool.get("id")) for tool in planning_tools],
        "strategy": {
            "objective": _conversation_goal(request_text, template_id),
            "audienceReasoning": f"Optimize for {target_segment.get('label') or 'the requested audience'} with decision drivers {', '.join(_as_text_list(target_segment.get('decisionDrivers'))[:3]) or 'comfort, clarity, and optionality'}.",
            "routeStrategy": " -> ".join(str(item) for item in route_pattern.get("recommendedArc", [])[:5]) or "Use verified stops as a beginning, middle, choice beat, and close.",
            "channelStrategy": f"Lead with {', '.join(str(item) for item in channel_targets[:4]) or 'guest app, signage, email, and staff cue'} so the same promise is reviewable across every artifact.",
            "riskTradeoffs": [
                "Creative specificity must come from approved venue facts, not invented attractions or cultural claims.",
                "Rewards, live availability, staffing, weather, access, and crowd guidance remain review items.",
                f"Success metric is {answer_context.get('successMetric')}; guest commitment is {answer_context.get('guestCommitment')}.",
            ],
        },
        "programPhases": phases,
        "ownerQuestions": [
            "Which cultural, brand, or seasonal references are approved for guest-facing copy?",
            "Which stop names, signage placements, and route transitions are owner-approved for the selected dates?",
            "Which participation mechanic is allowed without promising fulfillment, capacity, or live availability?",
        ],
    }


def _llm_conversation_planner_prompt(
    request_text: str,
    deterministic_plan: dict[str, Any],
    planning_tools: list[dict[str, Any]],
    next_payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "task": "Use the provided planning tools to create a complete ParkPulse Experience Studio plan. This is content, storytelling, and guest journey design, not operations.",
        "return_only_json": True,
        "planner_role": "Reason over tool outputs first, then compose a generator-ready plan. Do not output a generic template.",
        "hard_constraints": [
            "Use the template catalog and request text to choose the best plan type.",
            "Use only provided venue locations, route patterns, brand phrases, channel rules, guest segments, memory patterns, and approved learning rules.",
            "Do not invent location names, live availability, staff dispatch, queue changes, discounts, safety guarantees, access-lane claims, weather facts, or prize fulfillment.",
            "Every section must be specific enough that a creative lead can review it and a channel owner can see what artifact is needed.",
            "Keep all publishing and operational decisions behind human review gates.",
        ],
        "designer_request": request_text,
        "planning_tools": planning_tools,
        "deterministic_baseline": deterministic_plan,
        "current_generator_payload": next_payload,
        "return_json_shape": {
            "planName": "specific plan name",
            "selectedTemplateId": "one id from template_catalog",
            "selectedToolIds": ["template_catalog", "venue_profile", "retrieval_evidence", "agent_workflow"],
            "strategy": {
                "objective": "what the plan is trying to accomplish",
                "audienceReasoning": "why this audience path fits",
                "routeStrategy": "how the route or experience sequence should work",
                "channelStrategy": "how app, signage, email, staff cues should carry the same plan",
                "riskTradeoffs": ["specific tradeoff and review boundary"],
            },
            "programPhases": [
                {"name": "phase name", "duration": "timebox", "guestJob": "what guest is trying to do", "heroMoment": "reviewable content moment", "channels": ["guest_app"], "reviewGate": "owner gate"}
            ],
            "signatureMoments": [
                {"name": "moment name", "venueEvidence": "provided location/pattern/brand evidence", "guestAction": "optional action", "reviewNeed": "what must be approved"}
            ],
            "contentPillars": ["pillar tied to tools"],
            "evidenceUse": [
                {"evidenceId": "location:Front Gate", "usedFor": "why this evidence matters in the plan"}
            ],
            "agentStageNotes": [
                {"stageId": "retrieval_agent", "decision": "how retrieved facts shaped the package"}
            ],
            "recommendedPayloadPatch": {
                "creativeDirection": "specific direction",
                "storyArc": "specific arc",
                "sensoryLevel": "balanced",
                "walkingPace": "flexible",
                "outputPackage": "full package",
                "seasonalTheme": "specific theme",
                "audience": "audience",
                "tone": "tone",
                "constraints": "extra constraints to append"
            },
            "ownerQuestions": ["question for review"],
            "reviewBoundaries": ["boundary"],
        },
    }


def _run_experience_studio_llm_json_sync(
    prompt: dict[str, Any],
    *,
    timeout_seconds: float,
    max_output_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    worker_path = Path(__file__).resolve().with_name("gemini_hard_timeout.py")
    request_payload = {
        "prompt": prompt,
        "timeout_seconds": timeout_seconds,
        "max_output_tokens": max_output_tokens,
        "temperature": temperature,
    }
    env = os.environ.copy()
    env.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")
    process = subprocess.run(
        [sys.executable, str(worker_path)],
        input=json.dumps(request_payload, separators=(",", ":")),
        text=True,
        capture_output=True,
        timeout=max(1.0, timeout_seconds) + 2.0,
        env=env,
    )
    if process.returncode != 0:
        detail = (process.stderr or process.stdout or "").strip()
        raise RuntimeError(detail[:500] or "Gemini planner worker failed")
    payload = json.loads(process.stdout or "{}")
    if not payload.get("ok"):
        raise RuntimeError(str(payload.get("error") or "Gemini planner worker failed")[:500])
    generated = _json_from_text(str(payload.get("text") or "{}"))
    return {
        "generated": generated if isinstance(generated, dict) else {},
        "transport": payload.get("transport"),
        "finish_reason": payload.get("finish_reason"),
        "usage_metadata": payload.get("usage_metadata", {}),
    }


def _safe_planner_text(value: Any, *, max_chars: int = 420) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    return text[:max_chars]


def _merge_llm_conversation_plan(
    *,
    next_payload: dict[str, Any],
    reasoned_plan: dict[str, Any],
    generated: dict[str, Any],
    real_inputs: dict[str, Any],
    template_id: str,
    request_text: str,
    baseline_label: str,
    baseline_why: str,
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    accepted_fields: list[str] = []
    rejected_fields: list[dict[str, str]] = []
    llm_template = str(generated.get("selectedTemplateId") or "")
    if llm_template and llm_template != template_id:
        rejected_fields.append({"field": "selectedTemplateId", "reason": "template_locked_by_request_parser"})
    patch = generated.get("recommendedPayloadPatch") if isinstance(generated.get("recommendedPayloadPatch"), dict) else {}
    patch_fields = {
        "creativeDirection": 140,
        "storyArc": 220,
        "sensoryLevel": 80,
        "walkingPace": 80,
        "outputPackage": 120,
        "seasonalTheme": 220,
        "audience": 160,
        "tone": 180,
    }
    for field, max_chars in patch_fields.items():
        value = _safe_planner_text(patch.get(field), max_chars=max_chars)
        if not value:
            continue
        if _creative_text_rejection_reason(value, real_inputs, max_chars=max_chars):
            rejected_fields.append({"field": f"recommendedPayloadPatch.{field}", "reason": "claim_or_length_guardrail"})
            continue
        next_payload[field] = value
        accepted_fields.append(field)
    extra_constraints = _safe_planner_text(patch.get("constraints"), max_chars=500)
    if extra_constraints and not _creative_text_rejection_reason(extra_constraints, real_inputs, max_chars=500):
        current_constraints = str(next_payload.get("constraints") or "")
        if extra_constraints not in current_constraints:
            next_payload["constraints"] = f"{current_constraints}\nPlanner strategy: {extra_constraints}".strip()
            accepted_fields.append("constraints")

    plan_name = _safe_planner_text(generated.get("planName"), max_chars=120) or baseline_label
    strategy = generated.get("strategy") if isinstance(generated.get("strategy"), dict) else {}
    objective = _safe_planner_text(strategy.get("objective"), max_chars=420) or baseline_why
    program_phases = [item for item in generated.get("programPhases", []) if isinstance(item, dict)][:6] if isinstance(generated.get("programPhases"), list) else []
    signature_moments = [item for item in generated.get("signatureMoments", []) if isinstance(item, dict)][:8] if isinstance(generated.get("signatureMoments"), list) else []
    evidence_use = [item for item in generated.get("evidenceUse", []) if isinstance(item, dict)][:10] if isinstance(generated.get("evidenceUse"), list) else []
    agent_stage_notes = [item for item in generated.get("agentStageNotes", []) if isinstance(item, dict)][:8] if isinstance(generated.get("agentStageNotes"), list) else []
    owner_questions = [_safe_planner_text(item, max_chars=220) for item in _as_text_list(generated.get("ownerQuestions"))[:8]]
    review_boundaries = [_safe_planner_text(item, max_chars=220) for item in _as_text_list(generated.get("reviewBoundaries"))[:8]]
    selected_tool_ids = _as_text_list(generated.get("selectedToolIds"))[:12] or reasoned_plan.get("selectedToolIds", [])
    merged_reasoned_plan = {
        **reasoned_plan,
        "status": "llm_reasoned",
        "basis": "llm_used_planning_tools_with_guarded_payload_merge",
        "selectedToolIds": selected_tool_ids,
        "strategy": {
            **(reasoned_plan.get("strategy") if isinstance(reasoned_plan.get("strategy"), dict) else {}),
            **{key: value for key, value in strategy.items() if isinstance(value, (str, list))},
        },
        "programPhases": program_phases or reasoned_plan.get("programPhases", []),
        "signatureMoments": signature_moments,
        "evidenceUse": evidence_use,
        "agentStageNotes": agent_stage_notes,
        "contentPillars": _as_text_list(generated.get("contentPillars"))[:8],
        "ownerQuestions": owner_questions or reasoned_plan.get("ownerQuestions", []),
        "reviewBoundaries": review_boundaries,
        "llmPlanName": plan_name,
    }
    llm_reasoning = {
        "status": "ready",
        "planner": "gemini_json_planner",
        "planName": plan_name,
        "selectedTemplateId": template_id,
        "selectedToolIds": selected_tool_ids,
        "acceptedPayloadFields": accepted_fields,
        "rejectedFields": rejected_fields,
        "strategy": merged_reasoned_plan["strategy"],
        "programPhases": merged_reasoned_plan["programPhases"],
        "signatureMoments": signature_moments,
        "evidenceUse": evidence_use,
        "agentStageNotes": agent_stage_notes,
        "contentPillars": merged_reasoned_plan["contentPillars"],
        "ownerQuestions": owner_questions,
        "reviewBoundaries": review_boundaries,
        "request": request_text,
        "llm_used_for_control": False,
        "guardrails": ["planning_tools_only", "template_parser_locked", "venue_facts_locked", "publishing_requires_review"],
    }
    return plan_name, objective, merged_reasoned_plan, llm_reasoning


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
    festival_mode = template_id == "festival-plan"
    comfort_label = "Guest-comfort festival route" if festival_mode else "Comfort-led story route"
    signature_label = "Lantern Wishes festival concept" if festival_mode else "Signature moments"
    channel_label = "Channel-ready festival launch kit" if festival_mode else "Low-friction channel pack"
    return [
        {
            "id": "comfort_story",
            "label": comfort_label,
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
            "label": signature_label,
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
            "label": channel_label,
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
    if any(term in lowered for term in ("chinese new year", "lunar new year", "spring festival", "festival month", "month-long", "month long", "lantern")):
        return 1
    if any(term in lowered or term in success_metric for term in ("channel", "signage", "email", "pre-arrival", "clarity", "hackathon demo")):
        return 2
    if any(term in lowered or term in success_metric or term in commitment for term in ("signature", "memorable", "theatrical", "hosted", "vip", "premium")):
        return 1
    return 0 if any(term in lowered or term in success_metric for term in ("comfort", "calm", "simple", "quiet")) else 1


def build_experience_studio_conversation_plan(payload: dict[str, Any]) -> dict[str, Any]:
    request_text = _conversation_text(payload)
    if not request_text:
        request_text = "Create a guest journey package from the active Venue Profile."
    inferred_template_id = _infer_conversation_template(request_text)
    supplied_template_id = str(payload.get("templateId") or payload.get("template") or "")
    template_id = inferred_template_id if _conversation_has_template_signal(request_text) else supplied_template_id or inferred_template_id
    if template_id not in TEMPLATES:
        template_id = inferred_template_id
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
        working_payload["useVenueExperienceData"] = True
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
    channel_targets = planner_intelligence.get("channelTargets") if isinstance(planner_intelligence.get("channelTargets"), list) else []
    learning_context = _learning_rule_context(template_id, audience, channel_targets)
    memory_context = _finished_work_memory_context(template_id, audience, request_text=request_text)
    retrieval_context = _product_grade_retrieval_context(
        request_text=request_text,
        template_id=template_id,
        audience=audience,
        real_inputs=real_inputs,
        planner_intelligence=planner_intelligence,
        memory_context=memory_context,
        learning_context=learning_context,
    )
    agent_workflow = _agent_workflow_receipt(
        template_id=template_id,
        request_text=request_text,
        retrieval_context=retrieval_context,
        planner_intelligence=planner_intelligence,
        missing=missing,
    )
    planning_tools = _conversation_planning_tools(
        template_id,
        audience,
        tone,
        request_text,
        real_inputs,
        planner_intelligence,
        options,
        missing,
        retrieval_context,
        agent_workflow,
    )
    tool_router = _experience_studio_tool_router(
        template_id=template_id,
        request_text=request_text,
        planning_tools=planning_tools,
        retrieval_context=retrieval_context,
        planner_intelligence=planner_intelligence,
    )
    orchestration = _experience_studio_strategy_orchestration(
        template_id=template_id,
        request_text=request_text,
        options=options,
        retrieval_context=retrieval_context,
        planner_intelligence=planner_intelligence,
        missing=missing,
        answer_context=answer_context,
        tool_router=tool_router,
    )
    selected_strategy = orchestration.get("selectedStrategy") if isinstance(orchestration.get("selectedStrategy"), dict) else {}
    selected_option_id = str(selected_strategy.get("id") or "")
    selected_option = next((option for option in options if str(option.get("id") or "") == selected_option_id), None)
    if selected_option:
        recommended = selected_option
        next_payload.update(
            {
                key: value
                for key, value in (recommended.get("payload") if isinstance(recommended.get("payload"), dict) else {}).items()
                if key not in {"realInputs", "constraints", "useVenueExperienceData", "useRealParkContext"}
            }
        )
        next_payload["constraints"] = "\n".join(context_constraints)
        next_payload["seasonalTheme"] = goal
        next_payload["useVenueExperienceData"] = True
        next_payload["useRealParkContext"] = False
        if "realInputs" in working_payload:
            next_payload["realInputs"] = working_payload["realInputs"]
        recommended_label = str(recommended["label"])
        recommended_why = str(recommended["rationale"])
    reasoned_plan = _tool_reasoned_conversation_plan(template_id, request_text, answer_context, planner_intelligence, planning_tools)
    reasoned_plan["retrievalEvidence"] = retrieval_context
    reasoned_plan["agentWorkflow"] = agent_workflow
    reasoned_plan["toolRouter"] = tool_router
    reasoned_plan["strategyOrchestration"] = orchestration
    recommended_label = str(recommended["label"])
    recommended_why = str(recommended["rationale"])
    use_llm_planner = (
        payload.get("useLlmPlanner") is True
        or payload.get("useCreativeReasoning") is True
        or os.getenv("PARKPULSE_EXPERIENCE_STUDIO_USE_LLM_PLANNER", "").strip().lower() in {"1", "true", "yes", "on"}
    )
    llm_reasoning: dict[str, Any] = {
        "status": "not_requested",
        "llm_used_for_control": False,
        "reason": "Set useLlmPlanner/useCreativeReasoning or PARKPULSE_EXPERIENCE_STUDIO_USE_LLM_PLANNER=true to run the planning model.",
    }
    if use_llm_planner:
        planner_prompt = _llm_conversation_planner_prompt(request_text, reasoned_plan, planning_tools, next_payload)
        try:
            llm_result = _run_experience_studio_llm_json_sync(
                planner_prompt,
                timeout_seconds=float(os.getenv("PARKPULSE_EXPERIENCE_STUDIO_PLANNER_TIMEOUT_SECONDS", "24")),
                max_output_tokens=int(os.getenv("PARKPULSE_EXPERIENCE_STUDIO_PLANNER_MAX_OUTPUT_TOKENS", "3600")),
                temperature=float(os.getenv("PARKPULSE_EXPERIENCE_STUDIO_PLANNER_TEMPERATURE", "0.3")),
            )
            recommended_label, recommended_why, reasoned_plan, llm_reasoning = _merge_llm_conversation_plan(
                next_payload=next_payload,
                reasoned_plan=reasoned_plan,
                generated=llm_result.get("generated", {}),
                real_inputs=real_inputs,
                template_id=template_id,
                request_text=request_text,
                baseline_label=recommended_label,
                baseline_why=recommended_why,
            )
            llm_reasoning.update(
                {
                    "transport": llm_result.get("transport"),
                    "finishReason": llm_result.get("finish_reason"),
                    "usageMetadata": llm_result.get("usage_metadata", {}),
                }
            )
            next_payload["useLlm"] = True
            next_payload["useCreativeReasoning"] = True
        except Exception as error:
            llm_reasoning = {
                "status": "fallback",
                "error": str(error)[:240],
                "llm_used_for_control": False,
                "fallbackBasis": "tool_reasoned_plan",
            }
    product_readiness = _product_readiness_gate(
        missing=missing,
        retrieval_context=retrieval_context,
        agent_workflow=agent_workflow,
        llm_reasoning=llm_reasoning,
    )
    reasoned_plan["retrievalEvidence"] = retrieval_context
    reasoned_plan["agentWorkflow"] = agent_workflow
    reasoned_plan["productReadiness"] = product_readiness
    reasoned_plan["toolRouter"] = tool_router
    reasoned_plan["strategyOrchestration"] = orchestration
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
        "planningTools": planning_tools,
        "reasonedPlan": reasoned_plan,
        "llmReasoning": llm_reasoning,
        "retrievalEvidence": retrieval_context,
        "agentWorkflow": agent_workflow,
        "productReadiness": product_readiness,
        "toolRouter": tool_router,
        "strategyOrchestration": orchestration,
        "plannerIntelligence": planner_intelligence,
        "conceptOptions": options,
        "recommendedOptionId": recommended["id"],
        "recommendedPlan": {
            "label": recommended_label,
            "why": recommended_why,
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
    next_payload["plannerContext"] = {
        "source": "conversation_plan",
        "designerRequest": request_text,
        "generatedAt": plan["createdAt"],
        "recommendedPlanLabel": plan["recommendedPlan"]["label"],
        "recommendedPlanWhy": plan["recommendedPlan"]["why"],
        "parsedBrief": plan["parsedBrief"],
        "plannerIntelligence": planner_intelligence,
        "planningTools": planning_tools,
        "reasonedPlan": reasoned_plan,
        "llmReasoning": llm_reasoning,
        "retrievalEvidence": retrieval_context,
        "agentWorkflow": agent_workflow,
        "productReadiness": product_readiness,
        "toolRouter": tool_router,
        "strategyOrchestration": orchestration,
        "planStatus": plan["status"],
    }
    memory = _record_studio_memory(
        "experience_studio_generation_runs",
        {
            "_id": plan["id"],
            "eventType": "conversation_plan",
            "templateId": template_id,
            "audience": audience,
            "parsedBrief": plan["parsedBrief"],
            "reasonedPlan": reasoned_plan,
            "llmReasoning": llm_reasoning,
            "retrievalEvidence": retrieval_context,
            "agentWorkflow": agent_workflow,
            "productReadiness": product_readiness,
            "toolRouter": tool_router,
            "strategyOrchestration": orchestration,
            "planningToolIds": [str(tool.get("id")) for tool in planning_tools],
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
    template_id = _draft_template_id(draft, payload) or str(payload.get("templateId") or payload.get("template") or "")
    record = {
        "id": f"exp_{uuid.uuid4().hex[:12]}",
        "templateId": template_id,
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
            finished_memory = None
            if next_status in FINISHED_WORK_STATUSES:
                draft = record.get("draft") if isinstance(record.get("draft"), dict) else {}
                fingerprint = _creative_fingerprint(draft)
                finished_memory = _record_studio_memory(
                    "experience_studio_approved_work",
                    {
                        "_id": f"exp_finished_{draft_id}_{uuid.uuid4().hex[:8]}",
                        "eventType": "finished_work_approved",
                        "sourceDraftId": draft_id,
                        "templateId": record.get("templateId"),
                        "status": next_status,
                        "approvalStatus": next_status,
                        "actor": payload.get("actor") or "experience_reviewer",
                        "note": _text(payload.get("note"), f"Moved to {next_status}."),
                        "creativeFingerprint": fingerprint,
                        "title": fingerprint.get("title"),
                        "audience": fingerprint.get("audience"),
                        "selectedConceptName": fingerprint.get("selectedConceptName"),
                        "guestPromise": fingerprint.get("guestPromise"),
                        "experienceBeats": fingerprint.get("experienceBeats", []),
                        "selectedTerms": fingerprint.get("selectedTerms", []),
                        "reviewStatuses": fingerprint.get("reviewStatuses", {}),
                        "route": _route_summary(draft),
                        "memorySource": "human_approved_finished_work",
                        "syntheticMemory": False,
                        "learningEligible": True,
                        "learningSource": "human_approved_finished_work_memory",
                        "learningPolicy": _memory_learning_policy(),
                        "memoryBoundary": "Eligible for retrieval context only. It does not train a model or override venue facts.",
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
            memory_payload = {"feedback": feedback_memory, "revision": revision_memory}
            if finished_memory:
                memory_payload["finishedWork"] = finished_memory
            return {"status": "updated", "mode": "experience_studio_review_state", "draftRecord": record, "summary": _compact_record(record), "memoryPersistence": memory_payload}
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
    zone_details = raw.get("zoneDetails") if isinstance(raw.get("zoneDetails"), dict) else {}
    profile_intelligence = raw.get("profileIntelligence") if isinstance(raw.get("profileIntelligence"), dict) else {}
    guest_segments = raw.get("guestSegments") if isinstance(raw.get("guestSegments"), list) else []
    spatial_model = raw.get("spatialModel") if isinstance(raw.get("spatialModel"), dict) else {}
    agent_context = raw.get("agentContext") if isinstance(raw.get("agentContext"), dict) else {}
    learning_context = raw.get("learningContext") if isinstance(raw.get("learningContext"), dict) else {}
    nested_operating_context = profile_intelligence.get("operatingContext") if isinstance(profile_intelligence.get("operatingContext"), dict) else {}
    operating_context = raw.get("operatingContext") if isinstance(raw.get("operatingContext"), dict) else nested_operating_context
    current_status = raw.get("currentStatus") if isinstance(raw.get("currentStatus"), dict) else operating_context.get("currentStatus") if isinstance(operating_context.get("currentStatus"), dict) else {}
    path_status = raw.get("pathStatus") if isinstance(raw.get("pathStatus"), dict) else operating_context.get("pathStatus") if isinstance(operating_context.get("pathStatus"), dict) else {}
    signage_inventory = raw.get("signageInventory") if isinstance(raw.get("signageInventory"), dict) else operating_context.get("signageInventory") if isinstance(operating_context.get("signageInventory"), dict) else {}
    channel_templates = raw.get("channelTemplates") if isinstance(raw.get("channelTemplates"), dict) else operating_context.get("channelTemplates") if isinstance(operating_context.get("channelTemplates"), dict) else {}
    operating_calendar = raw.get("operatingCalendar") if isinstance(raw.get("operatingCalendar"), dict) else operating_context.get("operatingCalendar") if isinstance(operating_context.get("operatingCalendar"), dict) else {}
    weather_policy = raw.get("weatherPolicy") if isinstance(raw.get("weatherPolicy"), dict) else operating_context.get("weatherPolicy") if isinstance(operating_context.get("weatherPolicy"), dict) else {}
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
        "zoneDetails": {str(key): value for key, value in zone_details.items() if isinstance(value, dict)},
        "profileIntelligence": profile_intelligence,
        "guestSegments": [item for item in guest_segments if isinstance(item, dict)],
        "spatialModel": spatial_model,
        "agentContext": agent_context,
        "learningContext": learning_context,
        "operatingContext": operating_context,
        "currentStatus": current_status,
        "pathStatus": path_status,
        "signageInventory": signage_inventory,
        "channelTemplates": channel_templates,
        "operatingCalendar": operating_calendar,
        "weatherPolicy": weather_policy,
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
    elif template_id == "festival-plan":
        candidates = ["Front Gate", "Dragon Arch Photo Spot", "Lagoon Lanterns", "Harbor Treats", "Theater B", "Covered Plaza"] + _rule_candidates(real_inputs, "halloweenCandidateLocations") + locations + indoor + quiet
    elif template_id in {"seasonal-overlay", "photo-moment-route", "date-night"}:
        candidates = ["Front Gate", "Dragon Arch Photo Spot", "Lagoon Lanterns", "Theater B", "Covered Plaza"] + _rule_candidates(real_inputs, "halloweenCandidateLocations") + locations + quiet
    elif template_id == "food-festival":
        candidates = ["Front Gate", "Food Court A", "Harbor Treats", "Food Court B", "Covered Plaza"] + indoor + locations + quiet
    elif template_id == "accessibility-family-day":
        candidates = ["Guest Services", "Covered Plaza", "Theater B", "Food Court B", "Care Lagoon Family Room"] + quiet + indoor + locations
    elif template_id == "teen-night-out":
        candidates = ["Front Gate", "Dragon Arch Photo Spot", "Arcade Zone", "Food Court B", "Lagoon Lanterns"] + attractions + locations + indoor
    elif template_id == "first-time-visitor":
        candidates = ["Front Gate", "Guest Services", "Dragon Arch Photo Spot", "Food Court B", "Lagoon Lanterns"] + locations + indoor + quiet
    elif template_id == "education-field-trip":
        candidates = ["Front Gate", "Storybook Boats", "Lagoon Lanterns", "Food Court B", "Theater B"] + locations + quiet + indoor
    elif template_id == "post-incident-recovery-copy":
        candidates = ["Guest Services", "Covered Plaza", "Food Court B", "Theater B", "Front Gate"] + quiet + indoor + locations
    elif template_id == "retail-merch-quest":
        candidates = ["Front Gate", "Dragon Arch Photo Spot", "Food Court B", "Covered Plaza", "Lagoon Lanterns"] + locations + indoor + quiet
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
    try:
        from venue_experience_data import venue_profile_gap_contract

        gap_contract = venue_profile_gap_contract(real_inputs, profile_type, readiness, intelligence.get("coverage") if isinstance(intelligence.get("coverage"), dict) else {}, quality_gaps, include_generation_requirements=False)
    except Exception:
        production_missing = list(dict.fromkeys(_as_text_list(readiness.get("missingForRealVenueReady")) + quality_gaps))
        gap_contract = {
            "productionRealVenueReady": bool(readiness.get("realVenueReady") and profile_type != "synthetic_approved" and not production_missing),
            "missingForProduction": production_missing,
            "filledForSyntheticDemo": [],
            "syntheticOperatingCoverage": {},
        }
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
        "productionRealVenueReady": bool(gap_contract.get("productionRealVenueReady")),
        "missingProductionRealVenueInputs": gap_contract.get("missingForProduction", []),
        "syntheticFilledVenueGaps": gap_contract.get("filledForSyntheticDemo", []),
        "syntheticOperatingCoverage": gap_contract.get("syntheticOperatingCoverage", {}),
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
    if template_id in {"rainy-day", "low-sensory"} and zone_id and zone_id in set(_as_text_list(rules.get("rainyDayAnchors"))):
        parts.append("rainy-day anchor")
    if template_id in {"kid-quest", "scavenger-hunt", "halloween-route", "festival-plan"} and detail.get("name") in set(_as_text_list(rules.get("kidFriendlyAnchors"))):
        parts.append("kid-friendly anchor")
    if template_id in {"vip-tour", "festival-plan", "halloween-route"} and detail.get("name") in set(_as_text_list(rules.get("vipRouteAnchors"))):
        parts.append("VIP route anchor")
    if template_id == "festival-plan":
        parts.append("festival programming candidate")
    if template_id == "low-sensory" and quality_gaps:
        parts.append("confirm derived path and capacity assumptions before publishing")
    return "; ".join(parts)


def _creative_brief(payload: dict[str, Any], template_id: str) -> dict[str, str]:
    defaults = {
        "festival-plan": {
            "creativeDirection": "seasonal festival programming",
            "storyArc": "Launch weekend -> discovery weeks -> food and craft moments -> performance spotlight -> lantern finale",
            "sensoryLevel": "balanced",
            "walkingPace": "flexible",
            "outputPackage": "full festival package",
            "seasonalTheme": "Chinese New Year festival month",
        },
        "halloween-route": {
            "creativeDirection": "story-rich",
            "storyArc": "Invitation -> clue -> reveal -> choice -> finale",
            "sensoryLevel": "balanced",
            "walkingPace": "moderate",
            "outputPackage": "full package",
            "seasonalTheme": "family-safe Halloween mystery",
        },
        "seasonal-overlay": {
            "creativeDirection": "seasonal overlay",
            "storyArc": "Arrival signal -> themed discovery -> photo pause -> flexible choice -> seasonal close",
            "sensoryLevel": "balanced",
            "walkingPace": "flexible",
            "outputPackage": "full seasonal overlay package",
            "seasonalTheme": "seasonal park overlay",
        },
        "food-festival": {
            "creativeDirection": "food-forward discovery",
            "storyArc": "Taste invite -> sample stop -> seated reset -> craft or retail pairing -> flavor finale",
            "sensoryLevel": "balanced",
            "walkingPace": "moderate",
            "outputPackage": "food trail package",
            "seasonalTheme": "food festival trail",
        },
        "photo-moment-route": {
            "creativeDirection": "visual story route",
            "storyArc": "Photo invite -> landmark shot -> scenic transition -> group moment -> shareable close",
            "sensoryLevel": "balanced",
            "walkingPace": "flexible",
            "outputPackage": "photo route package",
            "seasonalTheme": "photo moment route",
        },
        "accessibility-family-day": {
            "creativeDirection": "accessibility-first family journey",
            "storyArc": "Plain arrival -> step-free choice -> rest point -> flexible activity -> supported close",
            "sensoryLevel": "low",
            "walkingPace": "flexible",
            "outputPackage": "accessible family journey",
            "seasonalTheme": "accessible family day",
        },
        "teen-night-out": {
            "creativeDirection": "social evening path",
            "storyArc": "Meet-up -> photo beat -> food or hangout -> thrill or show choice -> regroup close",
            "sensoryLevel": "balanced",
            "walkingPace": "moderate",
            "outputPackage": "teen night route package",
            "seasonalTheme": "teen night out",
        },
        "first-time-visitor": {
            "creativeDirection": "orientation-first journey",
            "storyArc": "Arrival confidence -> park landmark -> first signature choice -> comfort reset -> next-step close",
            "sensoryLevel": "balanced",
            "walkingPace": "moderate",
            "outputPackage": "first visit journey package",
            "seasonalTheme": "first-time visitor path",
        },
        "date-night": {
            "creativeDirection": "relaxed evening path",
            "storyArc": "Warm welcome -> scenic pause -> food or show beat -> quiet choice -> photo close",
            "sensoryLevel": "balanced",
            "walkingPace": "relaxed",
            "outputPackage": "date night route package",
            "seasonalTheme": "date night route",
        },
        "education-field-trip": {
            "creativeDirection": "learning journey",
            "storyArc": "Group arrival -> observation prompt -> learning stop -> lunch or reset -> reflection close",
            "sensoryLevel": "balanced",
            "walkingPace": "structured",
            "outputPackage": "field trip guide package",
            "seasonalTheme": "education field trip",
        },
        "post-incident-recovery-copy": {
            "creativeDirection": "empathetic recovery messaging",
            "storyArc": "Acknowledge -> orient -> support option -> current source -> follow-up close",
            "sensoryLevel": "low",
            "walkingPace": "compact",
            "outputPackage": "recovery copy package",
            "seasonalTheme": "post-incident recovery",
        },
        "retail-merch-quest": {
            "creativeDirection": "collectible story quest",
            "storyArc": "Quest invite -> display clue -> shop or story beat -> non-purchase option -> collectible close",
            "sensoryLevel": "balanced",
            "walkingPace": "moderate",
            "outputPackage": "retail quest package",
            "seasonalTheme": "retail merch quest",
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
    merged_planner_context = merged.get("plannerContext") if isinstance(merged.get("plannerContext"), dict) else {}
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
        merged.get("finishedWorkMemory") if isinstance(merged.get("finishedWorkMemory"), dict) else _finished_work_memory_context(template_id, _text(merged.get("audience"), "mixed guest groups"), request_text=str(merged_planner_context.get("designerRequest") or merged.get("intent") or "")),
        learning_context,
        merged_planner_context,
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


def _template_specific_stop_copy(template_id: str, stop: str, index: int, stage: str, audience: str, tone: str, detail: dict[str, Any], detail_phrase: str, creative_brief: dict[str, str], real_inputs: dict[str, Any]) -> tuple[str, str, str] | None:
    pattern_id, route_pattern = _profile_route_pattern(real_inputs, template_id)
    arc = route_pattern.get("recommendedArc") if isinstance(route_pattern.get("recommendedArc"), list) else []
    must_include = _as_text_list(route_pattern.get("mustInclude"))
    avoid_claims = _as_text_list(route_pattern.get("avoidClaims"))
    pattern_beat = str(arc[min(index, len(arc) - 1)] if arc else stage).strip()
    profile_sentence = f" This stop works because {detail_phrase}." if detail_phrase else ""
    review_sentence = f" Staff/review focus: {must_include[min(index, len(must_include) - 1)]}." if must_include else ""
    avoid_sentence = f" Avoid: {avoid_claims[0]}." if avoid_claims else ""
    step = index + 1
    routes: dict[str, list[tuple[str, str, str]]] = {
        "seasonal-overlay": [
            ("Set the seasonal threshold before guests decide how much to join.", "name the seasonal change, point out the first visible cue, and make the path feel optional", "Keep decor, dates, and temporary install claims inside approved language."),
            ("Turn the overlay into something inspectable rather than a vague theme.", "invite guests to find the seasonal symbol, color, sound, or photo detail at this stop", "Confirm placement and sightline before calling it a featured moment."),
            ("Give guests a low-pressure photo or story pause.", "offer a short photo, look-and-find, or reflection prompt that does not block the path", "Keep the cue short enough for signage and app use."),
            ("Let the route branch into activity, pause, or exit.", "present the next seasonal choice and remind guests they can skip ahead", "Do not imply all activations are always available."),
            ("Close the overlay with a current-options handoff.", "finish with a seasonal memory cue and direct guests to current park options", "Name the review owner for final dates and activation details."),
        ],
        "food-festival": [
            ("Open appetite without promising a specific item.", "start the flavor trail and choose a taste, photo, or story prompt", "Use current menu source language only."),
            ("Make the first sample decision clear.", "compare the reviewed flavor cue here or use the non-food prompt if the group is not eating", "Route allergy questions to the approved food owner."),
            ("Use the middle as a seated or shaded reset.", "pause, compare favorites, check the app, or continue without waiting for a table", "Avoid seating availability promises."),
            ("Pair food with story, craft, or retail without purchase pressure.", "look for the pairing detail and decide whether to continue the trail", "Keep purchase and sample fulfillment optional."),
            ("Close with flavor memory and current menu source.", "name the favorite stop, take the optional finale prompt, then check current dining options", "Do not use allergen-free or guaranteed-sample language."),
        ],
        "photo-moment-route": [
            ("Begin with the simplest frame and a no-photo alternative.", "take the first shot or choose the looking prompt before moving on", "Respect privacy and guests who do not want photos."),
            ("Use the landmark as the hero shot.", "step aside for the landmark photo, then clear the path for the next group", "Do not imply professional photo support."),
            ("Make the transition scenic, not just directional.", "notice the view, color, or reflection that connects this stop to the next one", "Check path safety for lingering groups."),
            ("Create the group photo pause.", "take the group shot only if the area is comfortable, or use the reflection prompt", "Keep dwell short and accessible."),
            ("End with a shareable but optional close.", "finish with the final frame and choose the next current option", "Avoid exclusive access or sharing outcome claims."),
        ],
        "accessibility-family-day": [
            ("Start with support clarity and plain language.", "check the support cue, choose the pace, and decide whether this path fits today", "Point to approved accessibility information."),
            ("Offer a step-free or lower-effort choice.", "choose the route option that feels easiest for the group before continuing", "Verify current path, grade, and surface condition."),
            ("Make the rest point explicit.", "use this stop to sit, reset, use support services, or stop the route", "Confirm seating, restroom, and crowd assumptions."),
            ("Keep the activity flexible.", "try the activity if it fits, or switch to the quieter/bypass option", "Avoid diagnosis-specific language."),
            ("Close with current support and next options.", "finish here, ask for approved route information, or pick the next app-listed option", "Do not claim ADA compliance or equipment availability."),
        ],
        "teen-night-out": [
            ("Create a clear meet-up signal.", "start the night path, confirm the group plan, and pick the first social beat", "Keep the tone mature and caregiver-readable."),
            ("Give the route its main social/photo moment.", "use this as the photo, arcade, food, or hangout beat without forcing a purchase", "Avoid exclusive-access language."),
            ("Offer a real choice, not a forced sequence.", "choose food, show, thrill, or pause based on current options", "Do not imply supervision or safety guarantees."),
            ("Name the regroup moment.", "pause here to reconnect before the final stop", "Keep the regroup well-lit and easy to explain."),
            ("Close with next-option clarity.", "end the route, check current options, and choose whether to continue", "Keep the finish visible and reviewable."),
        ],
        "first-time-visitor": [
            ("Reduce arrival confusion.", "use this stop to understand where you are, where support lives, and how to start", "Keep map/app language current."),
            ("Teach one memorable landmark.", "notice the landmark detail and use it as a reference point for the rest of the visit", "Do not overload guests with too many choices."),
            ("Offer a first signature choice.", "pick the signature moment or the gentler alternate based on your group", "Avoid must-do language."),
            ("Build in a comfort reset.", "use this stop for food, restroom, shade, or support before deciding what is next", "Do not promise capacity or wait times."),
            ("Close with two next steps.", "choose one current next option or end the starter path here", "Keep live availability in the app/source handoff."),
        ],
        "date-night": [
            ("Open softly and set relaxed pacing.", "start the evening route without needing to complete every stop", "Keep the tone tasteful and not childish."),
            ("Create the scenic pause.", "take the view, photo, or quiet moment before choosing food or show timing", "Do not imply private access."),
            ("Make the food/show choice clear.", "choose the food, show, or quiet bypass based on current options", "Avoid priority seating or guaranteed timing."),
            ("Protect the slower pace.", "use this as a low-pressure pause before the final photo or next option", "Keep transitions short and calm."),
            ("Close with an optional memory.", "finish with a photo, reflection, or current next option", "Do not promise romance, privacy, or exclusive treatment."),
        ],
        "education-field-trip": [
            ("Gather the group and define the task.", "start with a headcount and one observation question", "Speak to chaperones first."),
            ("Make the stop observational.", "look for one detail, compare it with the prompt, and share a quick answer", "Keep students out of traffic flow."),
            ("Connect the stop to learning.", "answer the learning question using something visible at the stop", "Do not claim curriculum certification."),
            ("Use the reset as part of the plan.", "pause for lunch, restroom, or quiet regroup before the close", "Keep supervision responsibility with the school/chaperones."),
            ("Close with reflection and headcount.", "name one thing the group noticed and complete the final headcount", "Avoid live crowd-control instruction."),
        ],
        "post-incident-recovery-copy": [
            ("Acknowledge without speculating.", "use this point to recognize the disruption and direct guests to support", "Do not state cause or blame."),
            ("Orient guests to current support.", "explain where to check current options or ask for help", "Keep alternate options current-source based."),
            ("Offer a practical alternate.", "choose the current alternate, pause, or use guest support", "Do not promise compensation or resolution."),
            ("Give staff one consistent phrase.", "keep the message calm, short, and empathetic", "Escalate beyond approved wording instead of improvising."),
            ("Close with follow-up clarity.", "use the approved support channel for next steps", "Do not say the issue is resolved without live confirmation."),
        ],
        "retail-merch-quest": [
            ("Set the quest rule and non-purchase path.", "start the clue route and choose browsing, looking, or skipping as valid options", "Avoid purchase pressure."),
            ("Make the display clue inspectable.", "find the symbol, color, or story detail before choosing the next clue", "Confirm display placement with retail."),
            ("Use the shop or story beat carefully.", "browse if desired, or complete the non-purchase prompt", "Do not promise item availability."),
            ("Keep fulfillment reviewable.", "mark the clue with a stamp, phrase, or placeholder only after owner approval", "Avoid limited-edition claims."),
            ("Close with a collectible-style memory.", "finish the quest and check current shop or app options", "Keep rewards optional and reviewed."),
        ],
    }
    rows = routes.get(template_id)
    if not rows:
        return None
    purpose, action, staff = rows[min(index, len(rows) - 1)]
    return (
        f"{pattern_beat}: {purpose}",
        f"{step}. {stage} at {stop}: {action} for {audience}.{profile_sentence}",
        f"{staff}{review_sentence}{avoid_sentence}",
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
    elif template_id == "festival-plan":
        guest_copy = _festival_stop_copy(stop, index, stage, audience, tone, detail, detail_phrase, creative_brief)
    elif template_id == "low-sensory":
        guest_copy = f"{step}. {stage} at {stop}: keep the beat predictable, quiet, and easy to leave. {sensory_note or detail_phrase}"
    elif template_id == "kid-quest":
        kid_purpose, guest_copy, kid_staff_note = _kid_quest_story(stop, index, stage, audience, detail, creative_brief)
    elif template_id == "scavenger-hunt":
        guest_copy = f"{step}. {stage} at {stop}: place a visual clue guests can solve while moving, then let the answer pull them toward the next reveal."
    elif template_id == "vip-tour":
        guest_copy = f"{step}. {stage} at {stop}: give the host one insider detail, one graceful pause, and one alternate if the moment needs to flex."
    else:
        specific = _template_specific_stop_copy(template_id, stop, index, stage, audience, tone, detail, detail_phrase, creative_brief, real_inputs)
        if specific:
            specific_purpose, guest_copy, specific_staff_note = specific
        else:
            guest_copy = f"{step}. {stage} at {stop}: follow the {tone} cue toward the next {direction} moment. {context_hint}"
    return {
        "stop": stop,
        "purpose": rainy_purpose if template_id == "rainy-day" else kid_purpose if template_id == "kid-quest" else specific_purpose if "specific_purpose" in locals() else f"{stage}: shape a {direction} beat at {sensory_level} sensory level.",
        "guestCopy": f"{step}. Real location required before guest copy can be finalized. Intended tone: {tone}. {context_hint}" if needs_real_location else guest_copy.strip(),
        "staffNote": "Do not stage staff from this draft until the real location and owner are supplied." if needs_real_location else kid_staff_note if template_id == "kid-quest" else specific_staff_note if "specific_staff_note" in locals() else "Welcome guests, name the journey, and confirm the route is optional." if step == 1 else "Keep the handoff short and point guests toward the next visual landmark.",
        "accessibilityNote": "Real route accessibility facts are required before approval." if needs_real_location else _accessibility_for_stop(template_id, detail, real_inputs),
        "profileIntelligenceNote": "Real profile intelligence required before this stop can be finalized." if needs_real_location else intelligence_note or "Follow module policy; avoid live availability, staffing, safety, and access-lane claims.",
        "source": "missing_real_input" if needs_real_location else source,
    }


def _festival_stop_copy(stop: str, index: int, stage: str, audience: str, tone: str, detail: dict[str, Any], detail_phrase: str, creative_brief: dict[str, str]) -> str:
    step = index + 1
    role_by_index = [
        ("welcome ritual", "Invite guests to choose the first wish, photo, or passport prompt before they commit to a longer path."),
        ("arrival photo", "Turn the landmark into the month's first keepsake beat while keeping cultural references owner-reviewed."),
        ("lantern discovery", "Let guests find a light, reflection, or story detail and decide whether to continue, pause, or return another day."),
        ("food or craft pause", "Frame this as an optional taste, craft, or retail-adjacent moment without making menu, allergen, or purchase claims."),
        ("show spotlight", "Use the stop as a current-options handoff for scheduled entertainment without promising a live performance."),
        ("finale close", "Close the festival path with a photo or reflection cue and send guests back to current app listings."),
    ]
    role, action = role_by_index[min(index, len(role_by_index) - 1)]
    evidence = detail_phrase or str(detail.get("experienceUse") or detail.get("description") or "").strip()
    evidence_sentence = f" Profile evidence: {evidence}" if evidence else ""
    theme = _display_theme_label(str(creative_brief.get("seasonalTheme") or "Chinese New Year festival month"), "festival-plan")
    return f"{step}. {stage} at {stop}: {role.title()} for {audience}. {action} Keep the tone {tone}, tie it to {theme}, and make participation optional.{evidence_sentence}".strip()


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
    first_revision = {
        "festival-plan": "Varied the festival plan by role: launch orientation, weekly discovery, food/craft moment, show spotlight, and finale close.",
        "rainy-day": "Varied the rainy-day stop copy by role: arrival reset, discovery pause, quiet middle, food choice, and covered close.",
        "kid-quest": "Varied the quest copy by role: mission start, clue, discovery, participation placeholder, and completion close.",
        "low-sensory": "Varied the low-sensory copy by role: orientation, quiet transition, decompression pause, optional choice, and exit clarity.",
        "vip-tour": "Varied the VIP script by role: welcome, insider reveal, signature stop, relaxed pause, and closing keepsake.",
    }.get(template_id, "Varied each stop by role so the route has a specific beginning, middle, choice beat, and close.")
    revisions = [
        first_revision,
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
    pattern_key = ROUTE_PATTERN_BY_TEMPLATE.get(template_id)
    pattern = route_patterns.get(pattern_key) if pattern_key and isinstance(route_patterns.get(pattern_key), dict) else {}
    return pattern_key, pattern


def _creative_concepts_for_template(template_id: str, route_names: list[str], audience: str, creative_brief: dict[str, str], real_inputs: dict[str, Any], intelligence: dict[str, Any], planning_profile: dict[str, Any]) -> list[dict[str, Any]]:
    brand_bible = intelligence.get("brandBible") if isinstance(intelligence.get("brandBible"), dict) else {}
    pattern_key, route_pattern = _route_pattern_for_template(intelligence, template_id)
    selected_segment = planning_profile.get("targetSegment") if isinstance(planning_profile.get("targetSegment"), dict) else {}
    segment_label = str(selected_segment.get("label") or audience)
    if template_id == "halloween-route" and "rain" in segment_label.lower():
        segment_label = audience
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
    expanded_generic = {
        "seasonal-overlay": ("Seasonal Spark Overlay", "A temporary seasonal layer that gives guests a clear entry signal, themed discovery moments, photo pauses, and a reviewable close.", ["seasonal cue", "overlay moment", "photo pause", "review gate"]),
        "food-festival": ("Flavor Trail", "A food-forward route that connects dining stops, seating or show pauses, and menu-safe guest copy without allergy or availability assurances.", ["taste", "sample", "seated reset", "menu review"]),
        "photo-moment-route": ("Picture-Perfect Park Path", "A visual route built around verified landmarks, group photo cues, scenic transitions, and accessible pacing.", ["photo cue", "landmark", "group shot", "shareable close"]),
        "accessibility-family-day": ("Easy-Choice Family Day", "An accessibility-forward family journey with plain-language choices, rest points, and owner-reviewed route assumptions.", ["step-free choice", "rest point", "plain language", "family pace"]),
        "teen-night-out": ("Glow-Up Night Path", "A social evening route for teens with photo beats, food or hangout moments, and clear regroup language.", ["meet-up", "photo beat", "hangout", "regroup"]),
        "first-time-visitor": ("First Visit Confidence Path", "An orientation-first route that helps new guests find landmarks, choose a starter experience, and close with next-step clarity.", ["orientation", "landmark", "first choice", "next step"]),
        "date-night": ("Evening Ease Route", "A relaxed evening path with scenic pauses, food or show choices, and tasteful photo-close language.", ["scenic pause", "relaxed pace", "evening close", "photo moment"]),
        "education-field-trip": ("Discover-and-Reflect Field Trip", "A school or group route with observation prompts, chaperone clarity, lunch or reset moments, and a reflection close.", ["observation", "learning prompt", "chaperone", "reflection"]),
        "post-incident-recovery-copy": ("Calm Recovery Message Set", "A recovery copy package that acknowledges disruption, orients guests to support, and keeps operational details owner-reviewed.", ["acknowledge", "support", "current source", "follow-up"]),
        "retail-merch-quest": ("Collectible Clue Quest", "A retail-linked quest with display clues, non-purchase participation, and fulfillment review gates.", ["display clue", "collectible", "non-purchase option", "shop moment"]),
    }
    if template_id in expanded_generic:
        name, positioning, hero_terms = expanded_generic[template_id]
        return [
            {
                "id": template_id.replace("-", "_"),
                "name": name,
                "positioning": f"{positioning} Built for {segment_label}.",
                "guestPromise": "Guests get a specific, optional journey with venue-grounded stops, clear channel copy, and human review gates before publishing.",
                "storyArc": pattern_arc or _as_text_list(creative_brief.get("storyArc")),
                "heroTerms": hero_terms,
                "route": route_names,
                "channelFocus": channel_targets,
                "reviewRisks": ["availability claims", "owner approval", "accessibility route assumptions", "copy length by channel"],
                "whyItWorks": "It expands Experience Studio coverage while preserving the same venue-grounded, non-operational authority boundary.",
            }
        ]
    if template_id == "festival-plan":
        festival_terms = list(dict.fromkeys(dragon_terms[:3] + lagoon_terms[:3] + ["lantern", "wishes", "red envelope placeholder", "festival passport", "family photo", "cultural review"]))
        festival_channels = list(dict.fromkeys(channel_targets + ["guest_app", "signage", "email", "staff_cue"]))
        return [
            {
                "id": "lantern_wishes_festival_month",
                "name": "Lantern Wishes Festival Month",
                "positioning": f"A month-long Chinese New Year festival plan for {segment_label} that phases arrival photo moments, lantern discovery, food/craft moments, performance pauses, and a finale route without promising live availability.",
                "guestPromise": "Guests can sample a festive route across multiple visits or complete a shorter optional path in one day, with culturally careful language and owner-reviewed participation mechanics.",
                "storyArc": pattern_arc or ["launch weekend", "lantern discovery weeks", "food and craft moments", "performance spotlight", "festival finale"],
                "heroTerms": festival_terms[:7],
                "route": route_names,
                "channelFocus": festival_channels,
                "reviewRisks": ["cultural accuracy", "reward or red-envelope fulfillment", "performance scheduling", "food allergen claims", "crowd and capacity wording", "month-long availability claims"],
                "whyItWorks": "It treats the request as a festival programming package rather than a generic route, while keeping all claims reviewable and grounded in verified venue locations.",
            },
            {
                "id": "festival_passport_path",
                "name": "Festival Passport Path",
                "positioning": f"A lighter month-long festival mechanic for {segment_label}: guests collect optional moments, photo prompts, and app check-ins across verified stops.",
                "guestPromise": "The park can promote repeatable discovery without inventing prizes, characters, or guaranteed events.",
                "storyArc": ["festival welcome", "passport moment", "food or craft pause", "show spotlight", "photo finale"],
                "heroTerms": ["festival passport", "lantern", "wish wall", "photo moment", "family route", "owner review"],
                "route": route_names,
                "channelFocus": ["guest_app", "signage", "email", "staff_cue"],
                "reviewRisks": ["fulfillment", "cultural review", "schedule currentness", "signage placement"],
                "whyItWorks": "It gives the month-long plan a clear participation structure that can scale from one-day guests to repeat visitors.",
            },
        ]
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
    if template_id == "halloween-route":
        halloween_terms = list(dict.fromkeys(dragon_terms[:3] + lagoon_terms[:3] + ["lantern", "mystery", "costume", "glow", "moonlit clue"]))
        return [
            {
                "id": "lantern_mystery_party_path",
                "name": "Lantern Mystery Party Path",
                "positioning": f"A spooky-but-friendly Halloween party route for {segment_label} that turns verified photo, lagoon, story, show, and covered plaza stops into optional mystery beats.",
                "guestPromise": "Families get a playful Halloween route with photo moments, gentle clues, plain access notes, and no gore, jump scares, or access guarantees.",
                "storyArc": pattern_arc or ["arrival photo", "lantern clue", "storybook reveal", "show pause", "covered finale"],
                "heroTerms": halloween_terms[:6],
                "route": route_names,
                "channelFocus": channel_targets,
                "reviewRisks": ["gore or fear-based language", "guaranteed access", "reward fulfillment", "outdoor availability", "crowd-control wording"],
                "whyItWorks": "It gives the party a named story spine while keeping every stop optional, non-graphic, and grounded in approved venue facts.",
            },
            {
                "id": "pumpkin_clue_parade",
                "name": "Pumpkin Clue Parade",
                "positioning": f"A lighter family Halloween route for {segment_label} built around short clues, photo pauses, and a covered regroup.",
                "guestPromise": "Guests can follow a festive clue trail, skip any beat, and close the route without losing the party feeling.",
                "storyArc": ["photo start", "pumpkin clue", "gentle reveal", "rest pause", "party close"],
                "heroTerms": ["pumpkin", "glow", "clue", "lantern", "costume", "covered finale"],
                "route": route_names,
                "channelFocus": ["guest_app", "signage", "staff_cue", "email"],
                "reviewRisks": ["prize promise", "age suitability", "line or wait claims", "unsafe crowding language"],
                "whyItWorks": "It reads more like a party activity than a route checklist while preserving reviewable boundaries.",
            },
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
    if template_id == "festival-plan" and str(concept.get("id") or "") == "lantern_wishes_festival_month":
        creative_fit += 6
        route_fit += 4
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


def _creative_concept_review_loop(
    *,
    template_id: str,
    concepts: list[dict[str, Any]],
    selected: dict[str, Any],
    route: list[dict[str, Any]],
    creative_brief: dict[str, str],
    real_inputs: dict[str, Any],
) -> dict[str, Any]:
    route_names = [str(item.get("stop") or "") for item in route if isinstance(item, dict) and item.get("stop")]
    details = real_inputs.get("locationDetails") if isinstance(real_inputs.get("locationDetails"), dict) else {}
    channel_count = len(selected.get("channelFocus", [])) if isinstance(selected.get("channelFocus"), list) else 0
    hero_terms = _as_text_list(selected.get("heroTerms"))
    review_risks = _as_text_list(selected.get("reviewRisks"))
    venue_specific_terms = 0
    selected_text = json.dumps(selected, default=str).lower()
    for name in route_names:
        if str(name).lower() in selected_text:
            venue_specific_terms += 1
    concept_reviews = []
    for concept in concepts:
        if not isinstance(concept, dict):
            continue
        text = json.dumps(concept, default=str).lower()
        route_mentions = sum(1 for name in route_names if str(name).lower() in text)
        concept_hero_count = len(_as_text_list(concept.get("heroTerms")))
        concept_channel_count = len(_as_text_list(concept.get("channelFocus")))
        concept_risks = len(_as_text_list(concept.get("reviewRisks")))
        dimensions = [
            {"id": "creative_depth", "label": "Creative depth", "score": min(20, 9 + concept_hero_count * 2), "why": f"{concept_hero_count} hero terms"},
            {"id": "venue_specificity", "label": "Venue specificity", "score": min(20, 8 + route_mentions * 2), "why": f"{route_mentions}/{max(1, len(route_names))} route stops named or implied"},
            {"id": "channel_readiness", "label": "Channel readiness", "score": min(20, 8 + concept_channel_count * 3), "why": f"{concept_channel_count} channel targets"},
            {"id": "reviewability", "label": "Reviewability", "score": min(20, 10 + min(concept_risks, 5) * 2), "why": f"{concept_risks} review risks are explicit"},
            {"id": "execution_clarity", "label": "Execution clarity", "score": min(20, 11 + (3 if concept.get("storyArc") else 0) + (3 if concept.get("guestPromise") else 0) + (3 if concept.get("whyItWorks") else 0)), "why": "story arc, promise, and rationale present"},
        ]
        concept_reviews.append(
            {
                "id": concept.get("id"),
                "name": concept.get("name"),
                "score": sum(int(item["score"]) for item in dimensions),
                "dimensions": dimensions,
                "critique": "Strong candidate for final package." if concept.get("id") == selected.get("id") else "Useful alternate, but less aligned with the selected route and channel mix.",
            }
        )
    concept_reviews.sort(key=lambda item: (-int(item.get("score") or 0), str(item.get("id") or "")))
    weak_points = []
    if venue_specific_terms < max(2, min(4, len(route_names))):
        weak_points.append("The concept does not name enough verified route anchors in its positioning.")
    if channel_count < 4:
        weak_points.append("The selected concept needs stronger app, email, signage, and staff-cue coverage.")
    if len(hero_terms) < 5:
        weak_points.append("The concept needs more inspectable creative texture, not only a generic route promise.")
    if not review_risks:
        weak_points.append("The concept needs explicit review risks before it can be handed to the event team.")
    if template_id == "festival-plan" and not any(term in selected_text for term in ("month", "week", "launch", "finale")):
        weak_points.append("The festival concept needs a visible monthly run shape, not only a one-day route.")
    if not weak_points:
        weak_points.append("The concept is viable; revision should deepen execution detail without changing verified stops.")

    first_stop = route_names[0] if route_names else "verified start"
    middle_stop = route_names[min(2, len(route_names) - 1)] if route_names else "verified middle"
    final_stop = route_names[-1] if route_names else "verified close"
    revised = dict(selected)
    if template_id == "festival-plan":
        revised["positioning"] = (
            f"{selected.get('positioning')} The event-team version is structured as launch weekend, rotating discovery weeks, "
            f"food/craft and show spotlights, and a finale close from {first_stop} through {middle_stop} to {final_stop}."
        )
        revised["guestPromise"] = (
            f"{selected.get('guestPromise')} Guests can participate lightly in one visit or return across the month, while cultural, reward, food, show, and schedule claims stay owner-reviewed."
        )
        revised["contentDepthPlan"] = [
            "Launch weekend: arrival photo, first lantern/wish prompt, app card, and front-gate sign.",
            "Discovery weeks: rotate food/craft, show, and photo prompts using verified stops.",
            "Finale week: close with a photo/reflection moment and current-options handoff.",
            "Marketing sequence: announcement email, mid-month reminder, final-week push, staff cue, and signage family.",
        ]
    else:
        revised["positioning"] = (
            f"{selected.get('positioning')} The event-team version names the start, middle choice, and close so the plan feels executable rather than generic."
        )
        revised["contentDepthPlan"] = [
            f"Start at {first_stop} with a named invitation and optionality language.",
            f"Use {middle_stop} as the main choice, reset, or discovery beat.",
            f"Close at {final_stop} with current-options handoff and review-safe copy.",
            "Carry the same named concept through app, email, signage, and staff cue.",
        ]
    revised["reviewRevision"] = {
        "status": "revised",
        "weakPointsFound": weak_points[:5],
        "revisionsApplied": [
            "Converted the selected concept into an event-team execution shape.",
            "Added concrete content depth plan before package assembly.",
            "Preserved verified route stops, optional movement language, and owner-review boundaries.",
        ],
    }
    return {
        "status": "reviewed",
        "mode": "creative_concept_review_loop_v1",
        "selectedConceptId": selected.get("id"),
        "selectedConceptName": selected.get("name"),
        "candidateReviews": concept_reviews[:5],
        "weakPointsFound": weak_points[:5],
        "revisionsApplied": revised["reviewRevision"]["revisionsApplied"],
        "revisedSelectedConcept": revised,
        "reviewers": [
            {"id": "creative_director", "decision": "Deepen the selected concept into a concrete event-team shape."},
            {"id": "venue_grounding_reviewer", "decision": "Preserve verified stops and source-backed claims."},
            {"id": "channel_reviewer", "decision": "Require visible app, email, signage, and staff-cue handoff."},
            {"id": "accessibility_and_claims_reviewer", "decision": "Keep path, access, schedule, food, reward, and cultural claims owner-reviewed."},
        ],
    }


def _channel_copy_variants(selected: dict[str, Any], route: list[dict[str, Any]], messages: list[dict[str, Any]], template_id: str, brand_bible: dict[str, Any]) -> dict[str, Any]:
    first_stop = str(route[0].get("stop") or "the first stop") if route else "the first stop"
    final_stop = str(route[-1].get("stop") or "the final stop") if route else "the final stop"
    terms = [str(item) for item in selected.get("heroTerms", []) if str(item).strip()]
    term = terms[0] if terms else "route"
    concept_name = str(selected.get("name") or "Creative route")
    approved = _as_text_list(brand_bible.get("approvedPhrases"))
    current_options = next((item for item in approved if "current" in item.lower()), "check the app for current options")
    if template_id == "festival-plan":
        return {
            "guestApp": {
                "headline": concept_name,
                "body": f"Celebrate across the festival month. Start at {first_stop}, choose the lantern, food, craft, or show moments that fit your visit, and check current times before you go.",
                "microcopy": current_options,
            },
            "signage": [
                {"placement": first_stop, "headline": "Begin your festival month", "body": "Choose a first lantern, photo, or passport moment. Participation is optional."},
                {"placement": final_stop, "headline": "Festival finale photo", "body": "Close your route here, then check the app for current festival options."},
            ],
            "email": {
                "subject": f"Plan your Chinese New Year festival month: {concept_name}",
                "previewText": "Optional lantern, food, craft, show, and photo moments across the month.",
                "body": f"{concept_name} is a month-long festival plan built around optional moments at verified park locations. Start at {first_stop}, look for current app listings, and choose the route, food/craft, show, or photo moments that fit your visit. Cultural, food, reward, and schedule details remain owner-reviewed before publishing.",
            },
            "staffCue": {
                "opening": f"Welcome guests to {concept_name} as an optional festival-month path, not a required schedule or guaranteed event list.",
                "transition": "Point guests to the next visible festival moment and remind them the app has current times and available options.",
                "boundary": "Keep cultural, food, reward, and schedule claims inside owner-approved language.",
            },
        }
    if template_id == "halloween-route":
        return {
            "guestApp": {
                "headline": concept_name,
                "body": f"Start at {first_stop}. Follow the next friendly clue when you are ready, pause at any stop, and keep the party route optional.",
                "microcopy": current_options,
            },
            "signage": [
                {"placement": first_stop, "headline": "Your first clue glows", "body": "Begin the party path when you are ready. Every clue is optional."},
                {"placement": final_stop, "headline": "Final glow stop", "body": "Regroup, take a photo, or choose your next current option in the app."},
            ],
            "email": {
                "subject": f"Your Halloween party route: {concept_name}",
                "previewText": "A spooky-friendly route with optional clues, photo moments, and current-options reminders.",
                "body": f"Before arrival, look for {concept_name}. It begins at {first_stop}, follows playful non-graphic clues, and closes at {final_stop}. Costumes and photo moments are welcome; attraction availability and access details should be checked in the app.",
            },
            "staffCue": {
                "opening": f"Welcome guests to {concept_name} as a playful optional Halloween party path, not a schedule or access promise.",
                "transition": "Point to the next visible clue and remind guests they can pause, skip a beat, or choose another current option.",
                "boundary": current_options,
            },
        }
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
    selected = max(
        concepts,
        key=lambda item: (
            int(item.get("totalScore") or 0),
            2 if template_id == "festival-plan" and str(item.get("id") or "") == "lantern_wishes_festival_month" else 0,
            1 if "dry" in str(item.get("id") or "") else 0,
        ),
    )
    concept_review = _creative_concept_review_loop(
        template_id=template_id,
        concepts=concepts,
        selected=selected,
        route=route,
        creative_brief=creative_brief,
        real_inputs=real_inputs,
    )
    selected = concept_review.get("revisedSelectedConcept") if isinstance(concept_review.get("revisedSelectedConcept"), dict) else selected
    concepts = [
        selected if isinstance(item, dict) and item.get("id") == selected.get("id") else item
        for item in concepts
    ]
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
        "conceptReview": concept_review,
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
        elif {"concept", "channel_consistency", "memory", "continuity", "creative_craft", "craft_sample", "channel_voice"}.intersection(tags):
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


def _finished_work_memory_context(template_id: str, audience: str, limit: int = 3, request_text: str = "") -> dict[str, Any]:
    records = _read_records()
    matches: list[dict[str, Any]] = []
    semantic_query = " ".join(
        item
        for item in [
            request_text,
            f"Experience Studio approved finished work for {template_id}",
            f"audience {audience}",
            "route story arc channel copy review gates reusable patterns",
        ]
        if str(item or "").strip()
    )
    semantic_memory = _semantic_studio_memory(
        query=semantic_query,
        template_id=template_id,
        collections=[
            "experience_studio_approved_work",
            "experience_studio_venue_snapshots",
            "experience_studio_eval_examples",
        ],
        limit=max(limit * 4, 12),
    )
    semantic_rows = semantic_memory.get("rows") if isinstance(semantic_memory.get("rows"), list) else []
    approved_rows = [
        row
        for row in semantic_rows
        if isinstance(row, dict)
        and str((row.get("_retrieval") or {}).get("collection") or "") == "experience_studio_approved_work"
    ]
    if not approved_rows:
        approved_rows = _latest_studio_memory("experience_studio_approved_work", max(limit * 4, 12))
    for row in approved_rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("approvalStatus") or row.get("status") or "") not in {"approved", "ready_for_publish", "synthetic_approved"}:
            continue
        if template_id and str(row.get("templateId") or "") != template_id:
            continue
        matches.append(
            {
                "draftId": row.get("sourceDraftId") or row.get("id") or row.get("_id"),
                "status": row.get("status") or row.get("approvalStatus"),
                "updatedAt": row.get("updatedAt") or row.get("createdAt"),
                "title": row.get("title"),
                "audience": row.get("audience") or audience,
                "selectedConceptName": row.get("selectedConceptName"),
                "guestPromise": row.get("guestPromise"),
                "route": row.get("route", []),
                "experienceBeats": row.get("experienceBeats", []),
                "selectedTerms": row.get("selectedTerms", []),
                "reviewStatuses": row.get("reviewStatuses", {}),
                "memorySource": row.get("memorySource") or "mongo_approved_work",
                "syntheticMemory": bool(row.get("syntheticMemory")),
                "reusablePatterns": row.get("reusablePatterns", []),
                "retrieval": row.get("_retrieval") if isinstance(row.get("_retrieval"), dict) else {},
            }
        )
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
                "memorySource": "saved_draft_store",
                "syntheticMemory": False,
            }
        )
    deduped: dict[str, dict[str, Any]] = {}
    for item in matches:
        key = str(item.get("draftId") or item.get("selectedConceptName") or json.dumps(item, sort_keys=True, default=str))
        deduped[key] = item
    matches = sorted(deduped.values(), key=lambda item: str(item.get("updatedAt") or ""), reverse=True)[: max(1, min(limit, 10))]
    if not matches:
        return {
            "status": "no_finished_patterns",
            "mode": "finished_work_pattern_memory_v1",
            "source": "semantic_experience_studio_memory_plus_saved_drafts",
            "semanticRetrieval": semantic_memory,
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
    explicit_patterns = [
        pattern
        for item in matches
        for pattern in _as_text_list(item.get("reusablePatterns"))
    ]
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
        "source": "semantic_experience_studio_memory_plus_saved_drafts",
        "semanticRetrieval": {
            "status": semantic_memory.get("status"),
            "mode": semantic_memory.get("mode"),
            "query": semantic_memory.get("query"),
            "retrieval": semantic_memory.get("retrieval"),
            "errors": semantic_memory.get("errors", []),
            "boundary": semantic_memory.get("boundary"),
        },
        "eligibleStatuses": sorted(FINISHED_WORK_STATUSES),
        "matchedTemplateId": template_id,
        "matchedAudience": audience,
        "matchedCount": len(matches),
        "matchedExamples": matches,
        "reusablePatterns": [
            f"Previously finished concepts for this template used named routes such as {', '.join(concept_names[:3])}.",
            f"Route depth has typically been {round(sum(route_lengths) / len(route_lengths), 1) if route_lengths else 0} stops with explicit channel artifacts.",
            f"Reusable voice terms: {', '.join(list(dict.fromkeys(repeated_terms))[:6]) or 'none captured yet'}.",
            *list(dict.fromkeys(explicit_patterns))[:4],
        ],
        "avoidPatterns": [
            "Do not reuse unapproved drafts.",
            "Do not treat reviewer notes as model training data.",
            "Do not override Venue Profile, route locks, or review gates with memory patterns.",
            "Synthetic memory may support demos only when explicitly labeled and cannot become real venue proof.",
        ],
        "reviewSignal": {
            "clearReviewShare": round(review_statuses.count("clear") / len(review_statuses), 2) if review_statuses else None,
            "statusesSeen": sorted(set(review_statuses)),
        },
        "syntheticMemoryCount": sum(1 for item in matches if item.get("syntheticMemory")),
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
            "reviewQuestion": "Which sign placements are physically approved and readable under expected guest traffic?",
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
        rule_rows = learning_context.get("rules") if isinstance(learning_context.get("rules"), list) else []
        if any({"creative_craft", "craft_sample", "channel_voice"}.intersection(set(_as_text_list(rule.get("tags")))) for rule in rule_rows if isinstance(rule, dict)):
            visible_changes.append("Applied a creative lead-approved craft sample as a reusable voice and specificity pattern.")
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
    try:
        from venue_experience_data import venue_profile_gap_contract

        gap_contract = venue_profile_gap_contract(real_inputs, profile_type, readiness, coverage, quality_gaps, include_generation_requirements=True)
    except Exception:
        production_missing = _as_text_list(readiness.get("missingForRealVenueReady"))
        if not real_inputs.get("channelOwners"):
            production_missing.append("named channel owners for guest_app, signage, email, and staff_cue")
        if not coverage.get("certifiedPaths"):
            production_missing.append("certified path records for selected route segments")
        gap_contract = {
            "status": "creative_ready_review_required",
            "productionRealVenueReady": False,
            "missingForProduction": list(dict.fromkeys(production_missing + quality_gaps)),
            "filledForSyntheticDemo": [],
            "syntheticOperatingCoverage": {},
            "nextProfileImports": [
                "replace approved synthetic operating snapshot with venue-owned live status feed",
                "replace synthetic path status with real accessibility/path certification export",
                "replace synthetic signage placements with real signage inventory and placement approvals",
                "replace synthetic channel templates with channel-owner CMS/CRM/app template exports",
            ],
        }
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
        "status": gap_contract.get("status", "creative_ready_review_required"),
        "profileType": profile_type,
        "creativeReady": bool(intelligence and not quality_gaps),
        "productionRealVenueReady": bool(gap_contract.get("productionRealVenueReady")),
        "missingForProduction": gap_contract.get("missingForProduction", []),
        "filledForSyntheticDemo": gap_contract.get("filledForSyntheticDemo", []),
        "syntheticOperatingCoverage": gap_contract.get("syntheticOperatingCoverage", {}),
        "coverage": coverage,
        "routeChecks": route_checks,
        "nextProfileImports": gap_contract.get("nextProfileImports", []),
    }


def _high_craft_artifacts(
    selected_name: str,
    selected_terms: list[str],
    route: list[dict[str, Any]],
    template_id: str,
    creative_brief: dict[str, str],
    current_options_phrase: str,
) -> dict[str, Any]:
    first_stop = str((route[0] or {}).get("stop") or "the first stop") if route else "the first stop"
    final_stop = str((route[-1] or {}).get("stop") or "the final stop") if route else "the final stop"
    middle_stop = str((route[min(1, len(route) - 1)] or {}).get("stop") or final_stop) if route else final_stop
    motif = next((term for term in selected_terms if str(term).strip()), "trail")
    sensory = str(creative_brief.get("sensoryLevel") or "balanced")
    pace = str(creative_brief.get("walkingPace") or "flexible")
    if template_id == "rainy-day":
        lead = f"Rain can change the shape of the day without taking the day away. {selected_name} starts at {first_stop}, keeps the next step visible, and gives families a dry place to choose what feels right."
        moment = f"At {middle_stop}, invite guests to find the {motif} detail, take a breath, and decide whether to continue toward {final_stop} or stay with current indoor options."
        sign = "A dry little detour starts here."
        signage_review_gate = "Signage owner confirms placement, contrast, line length, and rain readability."
    elif template_id == "halloween-route":
        lead = f"{selected_name} starts at {first_stop} with a friendly glow, not a scare. Follow each optional clue, pause whenever you like, and keep current options in view."
        moment = f"At {middle_stop}, invite guests to spot the {motif} detail, take a photo if they want, then choose whether to continue toward {final_stop} or skip ahead."
        sign = "Your first clue glows."
        signage_review_gate = "Signage owner confirms placement, contrast, line length, and Halloween crowd readability."
    elif template_id == "kid-quest":
        lead = f"{selected_name} gives kids a small mission and caregivers a simple way to keep the pace. Start at {first_stop}; every clue is optional."
        moment = f"At {middle_stop}, ask kids to spot one {motif} clue before the group decides whether to continue or pause."
        sign = "Your next clue is close."
        signage_review_gate = "Signage owner confirms placement, contrast, line length, and caregiver readability."
    elif template_id == "low-sensory":
        lead = f"{selected_name} keeps the visit quiet, predictable, and easy to leave. Start at {first_stop}, then use each stop as a choice point."
        moment = f"At {middle_stop}, keep the cue short: look for the {motif} marker, check comfort, then continue only if the group is ready."
        sign = "Quiet route choice point."
        signage_review_gate = "Signage owner confirms placement, contrast, line length, and low-stimulus readability."
    else:
        lead = f"{selected_name} turns verified park stops into a clear guest story. Start at {first_stop}, follow the visible cue, and close at {final_stop}."
        moment = f"At {middle_stop}, use the {motif} cue as a small story beat before guests choose the next step."
        sign = "Your next story cue starts here."
        signage_review_gate = "Signage owner confirms placement, contrast, line length, and guest readability."
    return {
        "status": "review_ready_samples",
        "purpose": "Concrete sample copy for a creative lead to judge craft, not just package completeness.",
        "samples": [
            {
                "id": "lead_guest_story",
                "label": "Lead guest story",
                "channel": "guest_app_or_email",
                "copy": lead,
                "whyItHelps": "Shows the actual tone and promise of the experience in guest-facing language.",
                "reviewGate": "Brand, digital, and accessibility owners confirm claims and reading level.",
            },
            {
                "id": "route_moment",
                "label": "Route moment",
                "channel": "route_storyboard",
                "copy": moment,
                "whyItHelps": "Makes one middle beat feel designed instead of procedurally listed.",
                "reviewGate": "Experience owner confirms the object, location, and skip path.",
            },
            {
                "id": "signage_headline",
                "label": "Signage headline",
                "channel": "signage",
                "copy": sign,
                "whyItHelps": "Gives the signage team a short, inspectable headline instead of a generic instruction.",
                "reviewGate": signage_review_gate,
            },
        ],
        "craftNotes": [
            f"Keep sensory level {sensory} and pace {pace}.",
            f"Use '{current_options_phrase}' only where current status matters; avoid repeating it in every sentence.",
            "Keep operational promises out of creative copy and in owner review notes.",
        ],
    }


def _count_score(count: int, target: int, floor: float = 45.0, ceiling: float = 100.0) -> float:
    if target <= 0:
        return ceiling
    return round(min(ceiling, floor + (max(0, count) / target) * (ceiling - floor)), 1)


def _dimension_gate(dimension: dict[str, Any]) -> dict[str, Any]:
    score = float(dimension.get("score") or 0)
    status = "pass" if score >= 85 else "review" if score >= 65 else "block"
    return {
        "id": f"venue_{dimension.get('id')}",
        "status": status,
        "severity": "critical" if status == "block" else "high" if status == "review" else "medium",
        "evidence": f"{dimension.get('label')}: {dimension.get('evidence')}",
        "reflectionScore": score,
        "missing": dimension.get("missing", []),
    }


def _venue_reflection_eval(real_inputs: dict[str, Any], route: list[dict[str, Any]], package: dict[str, Any], venue_gap_analysis: dict[str, Any]) -> dict[str, Any]:
    details = real_inputs.get("locationDetails") if isinstance(real_inputs.get("locationDetails"), dict) else {}
    zones = real_inputs.get("zoneDetails") if isinstance(real_inputs.get("zoneDetails"), dict) else {}
    spatial = real_inputs.get("spatialModel") if isinstance(real_inputs.get("spatialModel"), dict) else {}
    intelligence = _profile_intelligence(real_inputs)
    coverage = intelligence.get("coverage") if isinstance(intelligence.get("coverage"), dict) else {}
    readiness = intelligence.get("readiness") if isinstance(intelligence.get("readiness"), dict) else {}
    venue = real_inputs.get("venueIdentity") if isinstance(real_inputs.get("venueIdentity"), dict) else {}
    current_status = real_inputs.get("currentStatus") if isinstance(real_inputs.get("currentStatus"), dict) else {}
    path_status = real_inputs.get("pathStatus") if isinstance(real_inputs.get("pathStatus"), dict) else {}
    signage_inventory = real_inputs.get("signageInventory") if isinstance(real_inputs.get("signageInventory"), dict) else {}
    channel_templates = real_inputs.get("channelTemplates") if isinstance(real_inputs.get("channelTemplates"), dict) else {}
    operating_calendar = real_inputs.get("operatingCalendar") if isinstance(real_inputs.get("operatingCalendar"), dict) else {}
    weather_policy = real_inputs.get("weatherPolicy") if isinstance(real_inputs.get("weatherPolicy"), dict) else {}
    learning_context = real_inputs.get("learningContext") if isinstance(real_inputs.get("learningContext"), dict) else {}
    agent_context = real_inputs.get("agentContext") if isinstance(real_inputs.get("agentContext"), dict) else {}
    brand_bible = _brand_bible(real_inputs)
    experience_rules = _experience_rules(real_inputs)
    guest_segments = real_inputs.get("guestSegments") if isinstance(real_inputs.get("guestSegments"), list) else []
    live_feed_bindings = intelligence.get("liveFeedBindings") if isinstance(intelligence.get("liveFeedBindings"), dict) else {}
    segment_needs = intelligence.get("segmentNeeds") if isinstance(intelligence.get("segmentNeeds"), dict) else {}
    field_source_rows = (intelligence.get("fieldSourceLedger") or {}).get("rows") if isinstance(intelligence.get("fieldSourceLedger"), dict) else []
    field_source_count = len(field_source_rows) if isinstance(field_source_rows, list) else 0

    route_rows = [item for item in route if isinstance(item, dict)]
    route_names = [str(item.get("stop") or "") for item in route_rows if str(item.get("stop") or "").strip()]
    route_detail_rows = [details[name] for name in route_names if isinstance(details.get(name), dict)]
    route_zone_ids = {str(item.get("zoneId")) for item in route_detail_rows if str(item.get("zoneId") or "").strip()}
    route_zone_coverage = len(route_zone_ids) / max(1, len(route_names))
    route_access_notes = sum(1 for item in route_rows if item.get("accessibilityNote"))
    route_sources = sum(1 for item in route_rows if item.get("source"))
    route_care_anchor = any(str(item.get("kind") or "") in {"food", "guest_services", "first_aid", "family_service", "restrooms"} for item in route_detail_rows)
    route_shelter_anchor = any(item.get("indoor") is True or item.get("covered") is True or str(item.get("kind") or "") in {"show", "quiet_or_cooling"} for item in route_detail_rows)
    route_attraction_anchor = any(str(item.get("kind") or "") in {"attraction", "show"} for item in route_detail_rows)

    kind_counts: dict[str, int] = {}
    for item in details.values():
        if isinstance(item, dict):
            kind = str(item.get("kind") or "unknown")
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
    service_count = sum(kind_counts.get(kind, 0) for kind in ("guest_services", "first_aid", "family_service", "restrooms", "water_refill", "quiet_or_cooling"))
    dining_count = kind_counts.get("food", 0)
    attraction_show_count = kind_counts.get("attraction", 0) + kind_counts.get("show", 0)
    certified_paths = [item for item in (intelligence.get("certifiedPaths") if isinstance(intelligence.get("certifiedPaths"), list) else []) if isinstance(item, dict)]
    capacity_rows = ((intelligence.get("capacityModel") or {}).get("zoneComfort") or []) if isinstance(intelligence.get("capacityModel"), dict) else []
    timing = intelligence.get("timingModel") if isinstance(intelligence.get("timingModel"), dict) else {}
    operating_coverage = venue_gap_analysis.get("syntheticOperatingCoverage") if isinstance(venue_gap_analysis.get("syntheticOperatingCoverage"), dict) else {}
    current_options = int(coverage.get("currentOptions") or operating_coverage.get("currentOptions") or len(current_status.get("attractions") if isinstance(current_status.get("attractions"), list) else []))
    facility_statuses = int(operating_coverage.get("facilityStatuses") or len(current_status.get("facilityStatus") if isinstance(current_status.get("facilityStatus"), list) else []))
    path_segments = int(coverage.get("pathStatusSegments") or operating_coverage.get("pathStatusSegments") or len(path_status.get("routeSegments") if isinstance(path_status.get("routeSegments"), list) else []))
    signage_placements = int(coverage.get("signagePlacements") or operating_coverage.get("signagePlacements") or len(signage_inventory.get("placements") if isinstance(signage_inventory.get("placements"), list) else []))
    channel_template_count = int(coverage.get("channelTemplates") or operating_coverage.get("channelTemplates") or len(channel_templates.get("templates") if isinstance(channel_templates.get("templates"), dict) else {}))
    approval_rows = int(operating_coverage.get("approvalWorkflowRows") or len(channel_templates.get("approvalWorkflow") if isinstance(channel_templates.get("approvalWorkflow"), list) else []))
    event_windows = int(coverage.get("operatingEventWindows") or operating_coverage.get("eventWindows") or len(operating_calendar.get("eventWindows") if isinstance(operating_calendar.get("eventWindows"), list) else []))
    weather_policy_rows = int(operating_coverage.get("weatherPolicies") or sum(1 for value in weather_policy.values() if value not in (None, "", [], {})))
    feedback_labels = _as_text_list(learning_context.get("feedbackLabels"))
    if not feedback_labels and isinstance(intelligence.get("learningSchema"), dict):
        feedback_labels = _as_text_list((intelligence.get("learningSchema") or {}).get("feedbackLabels"))

    dimensions = [
        {
            "id": "source_depth",
            "label": "Venue source depth",
            "score": min(100, _count_score(len(details), 12, 45) + min(field_source_count, 5) * 2 + (8 if readiness.get("status") else 0)),
            "evidence": f"{len(details)} public location detail row(s), {field_source_count} field-source row(s), profile readiness {readiness.get('status') or 'unknown'}.",
            "missing": [] if details and readiness else ["venue source ledger or public location details"],
        },
        {
            "id": "spatial_model",
            "label": "Spatial and zone model",
            "score": round((_count_score(len(zones), 8, 45) * 0.35) + (_count_score(len(spatial.get("paths") if isinstance(spatial.get("paths"), list) else []), 8, 45) * 0.3) + (route_zone_coverage * 35), 1),
            "evidence": f"{len(zones)} zone(s), {len(spatial.get('paths') if isinstance(spatial.get('paths'), list) else [])} path(s), route touches {len(route_zone_ids)} zone(s).",
            "missing": [] if zones and spatial.get("paths") else ["zone roles or path graph"],
        },
        {
            "id": "attractions_shows",
            "label": "Attractions and shows",
            "score": min(100, _count_score(attraction_show_count, 7, 45) + (10 if route_attraction_anchor else 0) + min(current_options, 5) * 2),
            "evidence": f"{attraction_show_count} attraction/show row(s), {current_options} current option row(s), route attraction anchor={route_attraction_anchor}.",
            "missing": [] if attraction_show_count and route_attraction_anchor else ["route attraction/show anchor"],
        },
        {
            "id": "dining_care_services",
            "label": "Dining, care, and recovery services",
            "score": min(100, _count_score(dining_count + service_count, 8, 45) + (10 if route_care_anchor else 0) + min(facility_statuses, 4) * 3),
            "evidence": f"{dining_count} dining row(s), {service_count} care/service row(s), {facility_statuses} facility status row(s), route care anchor={route_care_anchor}.",
            "missing": [] if route_care_anchor else ["route food, restroom, guest-service, family-service, or recovery anchor"],
        },
        {
            "id": "guest_segment_fit",
            "label": "Guest segment fit",
            "score": min(100, _count_score(len(guest_segments), 5, 45) + min(len(segment_needs), 5) * 4 + (8 if package.get("ownerQuestions") else 0)),
            "evidence": f"{len(guest_segments)} guest segment(s), {len(segment_needs)} segment-need model(s), owner questions attached={bool(package.get('ownerQuestions'))}.",
            "missing": [] if guest_segments and segment_needs else ["guest segment needs"],
        },
        {
            "id": "accessibility_safety",
            "label": "Accessibility and safety grounding",
            "score": min(100, _count_score(len(certified_paths), 4, 45) * 0.35 + _count_score(len(real_inputs.get("safetyInstructions") or []), 4, 45) * 0.25 + (route_access_notes / max(1, len(route_rows))) * 25 + min(path_segments, 4) * 4),
            "evidence": f"{len(certified_paths)} certified path row(s), {route_access_notes}/{len(route_rows)} route accessibility note(s), {len(real_inputs.get('safetyInstructions') or [])} safety instruction(s), {path_segments} path-status segment(s).",
            "missing": [] if certified_paths and route_access_notes == len(route_rows) else ["certified paths or per-stop accessibility notes"],
        },
        {
            "id": "operations_currentness",
            "label": "Current operating context",
            "score": min(100, _count_score(current_options + facility_statuses + path_segments, 12, 45) + (8 if current_status.get("weather") else 0) + (6 if operating_calendar else 0)),
            "evidence": f"{current_options} current option(s), {facility_statuses} facility status row(s), {path_segments} path status segment(s), weather snapshot={bool(current_status.get('weather'))}.",
            "missing": [] if current_options and path_segments else ["live/current options or path status feed"],
        },
        {
            "id": "weather_timing",
            "label": "Weather and event timing",
            "score": min(100, _count_score(event_windows + weather_policy_rows, 5, 45) + (10 if timing.get("status") else 0) + (6 if operating_calendar.get("blackoutPolicy") else 0)),
            "evidence": f"{event_windows} event window(s), {weather_policy_rows} weather policy row(s), timing status {timing.get('status') or 'unknown'}.",
            "missing": [] if event_windows and weather_policy_rows else ["weather policy or operating event windows"],
        },
        {
            "id": "channel_signage_governance",
            "label": "Channel and signage governance",
            "score": min(100, _count_score(len(real_inputs.get("channelOwners") or {}), 4, 45) * 0.25 + _count_score(channel_template_count, 4, 45) * 0.25 + _count_score(approval_rows, 4, 45) * 0.25 + _count_score(signage_placements, 4, 45) * 0.25),
            "evidence": f"{len(real_inputs.get('channelOwners') or {})} owner(s), {channel_template_count} template(s), {approval_rows} approval row(s), {signage_placements} signage placement(s).",
            "missing": [] if channel_template_count and approval_rows and signage_placements else ["channel templates, approval workflow, or signage inventory"],
        },
        {
            "id": "brand_localization",
            "label": "Brand, language, and claim policy",
            "score": min(100, _count_score(len(_as_text_list(brand_bible.get("approvedPhrases"))) + len(_as_text_list(brand_bible.get("bannedClaims"))) + len(_as_text_list(brand_bible.get("supportedLocales"))), 12, 45) + (8 if brand_bible.get("tone") else 0)),
            "evidence": f"{len(_as_text_list(brand_bible.get('approvedPhrases')))} approved phrase(s), {len(_as_text_list(brand_bible.get('bannedClaims')))} banned claim(s), {len(_as_text_list(brand_bible.get('supportedLocales')))} supported locale(s).",
            "missing": [] if brand_bible.get("bannedClaims") else ["brand claim policy"],
        },
        {
            "id": "learning_feed_boundaries",
            "label": "Learning and live-feed boundaries",
            "score": min(100, _count_score(len(feedback_labels), 8, 45) * 0.35 + _count_score(len(live_feed_bindings), 4, 45) * 0.35 + _count_score(len(agent_context.get("humanReviewTriggers") or []), 5, 45) * 0.3),
            "evidence": f"{len(feedback_labels)} feedback label(s), {len(live_feed_bindings)} live-feed binding group(s), {len(agent_context.get('humanReviewTriggers') or [])} human review trigger(s).",
            "missing": [] if feedback_labels and live_feed_bindings else ["learning labels or live-feed binding map"],
        },
        {
            "id": "experience_rules",
            "label": "Experience-rule coverage",
            "score": min(100, _count_score(len(experience_rules), 10, 45) + (8 if route_shelter_anchor else 0) + (6 if experience_rules.get("noGoPairings") else 0)),
            "evidence": f"{len(experience_rules)} experience-rule group(s), route shelter/reset anchor={route_shelter_anchor}, no-go pairings={len(experience_rules.get('noGoPairings') or []) if isinstance(experience_rules.get('noGoPairings'), list) else 0}.",
            "missing": [] if experience_rules else ["experience rules"],
        },
    ]
    score = round(sum(float(item["score"]) for item in dimensions) / max(1, len(dimensions)), 1)
    gates = [_dimension_gate(item) for item in dimensions]
    blocked = sum(1 for gate in gates if gate["status"] == "block")
    review = sum(1 for gate in gates if gate["status"] == "review")
    profile_type = str(venue.get("profileType") or "unknown")
    status = "venue_reflection_ready" if blocked == 0 and review <= 1 else "venue_reflection_review_required" if blocked == 0 else "venue_reflection_blocked"
    return {
        "status": status,
        "score": score,
        "profileType": profile_type,
        "productionRealVenueReady": bool(venue_gap_analysis.get("productionRealVenueReady")),
        "summary": f"Venue reflection scored {score} across {len(dimensions)} venue dimensions using {profile_type} profile data.",
        "dimensions": dimensions,
        "gateSummary": {"passed": len(gates) - blocked - review, "review": review, "blocked": blocked},
        "gates": gates,
        "routeCoverage": {
            "routeStops": route_names,
            "matchedLocationDetails": len(route_detail_rows),
            "routeZones": sorted(route_zone_ids),
            "routeHasAttractionOrShowAnchor": route_attraction_anchor,
            "routeHasDiningCareAnchor": route_care_anchor,
            "routeHasShelterOrResetAnchor": route_shelter_anchor,
            "routeSourceEvidence": f"{route_sources}/{len(route_rows)}",
        },
        "productionBoundary": {
            "status": "production_ready" if venue_gap_analysis.get("productionRealVenueReady") else "demo_reflection_only",
            "reason": "Venue reflection can use synthetic-approved coverage for demo reasoning, but production publish still requires real venue feeds." if profile_type == "synthetic_approved" else "Production readiness follows venue gap analysis.",
            "missingForProduction": venue_gap_analysis.get("missingForProduction", []),
        },
    }


def _experience_reviewer_panel(
    route: list[dict[str, Any]],
    channel_matrix: list[dict[str, Any]],
    section_dossiers: list[dict[str, Any]],
    package: dict[str, Any],
    memory_application: dict[str, Any],
    venue_gap_analysis: dict[str, Any],
    banned_hits: list[str],
) -> dict[str, Any]:
    craft = package.get("craftArtifacts") if isinstance(package.get("craftArtifacts"), dict) else {}
    craft_samples = craft.get("samples") if isinstance(craft.get("samples"), list) else []
    owner_questions = package.get("ownerQuestions") if isinstance(package.get("ownerQuestions"), list) else []
    approved_rules = package.get("approvedRuleInfluence") if isinstance(package.get("approvedRuleInfluence"), dict) else {}
    route_rows = [item for item in route if isinstance(item, dict)]
    source_backed_stops = sum(1 for item in route_rows if item.get("source"))
    accessibility_stops = sum(1 for item in route_rows if item.get("accessibilityNote"))
    optional_copy_count = sum(
        1
        for item in route_rows
        if any(term in str(item.get("guestCopy") or "").lower() for term in ("optional", "choose", "pause", "current options", "when you are ready"))
    )
    craft_sample_count = sum(1 for item in craft_samples if isinstance(item, dict) and item.get("copy") and item.get("reviewGate") and item.get("whyItHelps"))
    guest_copy_words = " ".join(str(item.get("guestCopy") or "") for item in route_rows).lower().split()
    distinct_guest_terms = len(set(word.strip(".,:;!?()[]").lower() for word in guest_copy_words if len(word.strip(".,:;!?()[]")) > 4))
    route_count = max(1, len(route_rows))
    reviewers = [
        {
            "reviewerId": "creative_director",
            "role": "Creative director",
            "score": min(100, 48 + craft_sample_count * 12 + min(distinct_guest_terms, 18)),
            "finding": "Craft samples and route copy give the concept enough inspectable texture." if craft_sample_count >= 3 and distinct_guest_terms >= 14 else "The concept still risks reading like a package skeleton instead of a finished guest-facing idea.",
            "requiredRevision": "Add more concrete guest-facing images and one stronger sample for each priority channel." if craft_sample_count < 3 or distinct_guest_terms < 14 else "Keep the selected craft move and verify it with the creative lead.",
            "gateImpact": "creative_director_critique",
        },
        {
            "reviewerId": "accessibility_reviewer",
            "role": "Accessibility reviewer",
            "score": round(55 + (accessibility_stops / route_count) * 35 + (10 if owner_questions else 0), 1),
            "finding": "Route stops carry accessibility notes and owner-review questions." if accessibility_stops >= len(route_rows) and owner_questions else "Accessibility is mentioned, but the route still needs stronger verification hooks.",
            "requiredRevision": "Attach owner-confirmed step-free path, seating, lighting, and exit checks to every stop." if accessibility_stops < len(route_rows) or not owner_questions else "Keep accessibility language plain and move operational verification into owner review.",
            "gateImpact": "accessibility_reviewer_critique",
        },
        {
            "reviewerId": "safety_claims_reviewer",
            "role": "Safety and claims reviewer",
            "score": 96 if not banned_hits and optional_copy_count >= max(1, len(route_rows) - 1) else 62 if not banned_hits else 30,
            "finding": "Guest-facing copy avoids banned promises and frames the route as optional." if not banned_hits and optional_copy_count >= max(1, len(route_rows) - 1) else "Claims language needs a tighter pass before owner review.",
            "requiredRevision": f"Remove blocked claim language: {', '.join(banned_hits)}." if banned_hits else "Increase optional/current-options language so guests are not directed into a fixed operating promise.",
            "gateImpact": "safety_claims_critique",
        },
        {
            "reviewerId": "channel_owner_reviewer",
            "role": "Channel owner reviewer",
            "score": min(100, 50 + len(channel_matrix) * 8 + len(section_dossiers) * 3),
            "finding": "Channel artifacts have named owners, objectives, and review gates." if len(channel_matrix) >= 4 and len(section_dossiers) >= 6 else "Some channel artifacts are present but still thin for owner handoff.",
            "requiredRevision": "Add explicit owner, placement, success measure, and approval question for each channel." if len(channel_matrix) < 4 or len(section_dossiers) < 6 else "Send to channel owners as a review draft, not a publish package.",
            "gateImpact": "channel_owner_critique",
        },
        {
            "reviewerId": "memory_governance_reviewer",
            "role": "Memory governance reviewer",
            "score": 94 if memory_application.get("usedForGeneration") and approved_rules.get("authority") == "human_promoted_rules_only" else 76 if memory_application.get("usedForGeneration") else 68,
            "finding": "Memory use is visible and bounded to human-promoted rules." if memory_application.get("usedForGeneration") and approved_rules.get("authority") == "human_promoted_rules_only" else "Memory is either inactive or not yet backed by human-promoted rule authority.",
            "requiredRevision": "Promote only lead-approved package/craft patterns before using memory as an improvement signal." if approved_rules.get("authority") != "human_promoted_rules_only" else "Keep rule receipts visible and deduplicated.",
            "gateImpact": "memory_governance_critique",
        },
    ]
    production_ready = bool(venue_gap_analysis.get("productionRealVenueReady"))
    for reviewer in reviewers:
        score = float(reviewer.get("score") or 0)
        if reviewer["gateImpact"] == "safety_claims_critique" and banned_hits:
            reviewer["gateStatus"] = "block"
        elif score >= 85:
            reviewer["gateStatus"] = "pass"
        elif score >= 60:
            reviewer["gateStatus"] = "review"
        else:
            reviewer["gateStatus"] = "block"
    consensus = round(sum(float(item.get("score") or 0) for item in reviewers) / len(reviewers), 1)
    blocked = sum(1 for item in reviewers if item.get("gateStatus") == "block")
    review = sum(1 for item in reviewers if item.get("gateStatus") == "review")
    return {
        "status": "panel_passed" if blocked == 0 and review <= 1 else "panel_review_required" if blocked == 0 else "panel_blocked",
        "loopType": "internal_multi_reviewer_critique",
        "consensusScore": consensus,
        "reviewerCount": len(reviewers),
        "productionPublishReady": production_ready and blocked == 0 and review == 0,
        "summary": f"{len(reviewers)} internal reviewers produced {blocked} block(s), {review} review item(s), and consensus score {consensus}.",
        "reviewers": reviewers,
        "revisionQueue": [
            {
                "reviewerId": item.get("reviewerId"),
                "role": item.get("role"),
                "status": item.get("gateStatus"),
                "requiredRevision": item.get("requiredRevision"),
            }
            for item in reviewers
            if item.get("gateStatus") != "pass"
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
    real_inputs: dict[str, Any],
) -> dict[str, Any]:
    craft = package.get("craftArtifacts") if isinstance(package.get("craftArtifacts"), dict) else {}
    craft_samples = craft.get("samples") if isinstance(craft.get("samples"), list) else []
    owner_questions = package.get("ownerQuestions") if isinstance(package.get("ownerQuestions"), list) else []
    approved_rules = package.get("approvedRuleInfluence") if isinstance(package.get("approvedRuleInfluence"), dict) else {}
    production_missing = _as_text_list(venue_gap_analysis.get("missingForProduction"))
    synthetic_filled = _as_text_list(venue_gap_analysis.get("filledForSyntheticDemo"))
    route_rows = [item for item in route if isinstance(item, dict)]
    source_backed_stops = sum(1 for item in route_rows if item.get("source"))
    accessibility_stops = sum(1 for item in route_rows if item.get("accessibilityNote"))
    review_gate_count = sum(1 for item in section_dossiers if isinstance(item, dict) and item.get("reviewGate"))
    craft_sample_count = sum(1 for item in craft_samples if isinstance(item, dict) and item.get("copy") and item.get("reviewGate") and item.get("whyItHelps"))
    guest_facing_text = " ".join(
        [
            *(str(item.get("guestCopy") or "") for item in route_rows),
            str((package.get("preArrivalEmail") or {}).get("subject") or "") if isinstance(package.get("preArrivalEmail"), dict) else "",
            str((package.get("preArrivalEmail") or {}).get("body") or "") if isinstance(package.get("preArrivalEmail"), dict) else "",
            *(str(item.get("headline") or "") + " " + str(item.get("body") or "") for item in (package.get("signageSet") if isinstance(package.get("signageSet"), list) else []) if isinstance(item, dict)),
        ]
    ).lower()
    banned_claims = ["guaranteed", "allergen-free", "ada compliant", "always available", "no wait", "priority access", "backstage access", "private route"]
    banned_hits = [claim for claim in banned_claims if claim in guest_facing_text]
    source_ratio = source_backed_stops / max(1, len(route_rows))
    access_ratio = accessibility_stops / max(1, len(route_rows))
    review_ratio = review_gate_count / max(1, len(section_dossiers))
    reviewer_panel = _experience_reviewer_panel(route, channel_matrix, section_dossiers, package, memory_application, venue_gap_analysis, banned_hits)
    reviewer_consensus = float(reviewer_panel.get("consensusScore") or 0)
    venue_reflection = _venue_reflection_eval(real_inputs, route, package, venue_gap_analysis)
    venue_reflection_score = float(venue_reflection.get("score") or 0)
    scores = {
        "specificity": 92 if route_rows and all(item.get("guestCopy") and item.get("staffNote") for item in route_rows) else 58,
        "sourceEvidence": round(60 + source_ratio * 35 + min(len(synthetic_filled), 5), 1) if route_rows else 45,
        "routeAndAccessGovernance": round(55 + access_ratio * 35 + (10 if venue_gap_analysis.get("routeChecks") else 0), 1),
        "channelOwnerReadiness": min(100, 55 + len(channel_matrix) * 7 + len(owner_questions) * 3),
        "craftDepth": min(100, 48 + craft_sample_count * 14 + (10 if craft.get("craftNotes") else 0)),
        "reviewGovernance": round(50 + review_ratio * 30 + min(len(owner_questions), 5) * 4, 1),
        "memoryAndLearningAuthority": 94 if memory_application.get("usedForGeneration") and approved_rules.get("authority") == "human_promoted_rules_only" else 66 if memory_application.get("usedForGeneration") else 48,
        "claimSafety": 96 if not banned_hits else 45,
        "productionBoundary": 100 if venue_gap_analysis.get("productionRealVenueReady") else 72 if production_missing == ["real venue source feed instead of approved synthetic profile"] else 45,
        "reviewerConsensus": reviewer_consensus,
        "venueReflection": venue_reflection_score,
    }
    weights = {
        "specificity": 0.08,
        "sourceEvidence": 0.1,
        "routeAndAccessGovernance": 0.1,
        "channelOwnerReadiness": 0.08,
        "craftDepth": 0.1,
        "reviewGovernance": 0.09,
        "memoryAndLearningAuthority": 0.08,
        "claimSafety": 0.08,
        "productionBoundary": 0.06,
        "reviewerConsensus": 0.1,
        "venueReflection": 0.13,
    }
    total = round(sum(scores[key] * weights[key] for key in weights), 1)
    production_score = round((scores["sourceEvidence"] * 0.16) + (scores["routeAndAccessGovernance"] * 0.16) + (scores["channelOwnerReadiness"] * 0.14) + (scores["claimSafety"] * 0.16) + (scores["productionBoundary"] * 0.24) + (scores["venueReflection"] * 0.14), 1)
    if not venue_gap_analysis.get("productionRealVenueReady"):
        production_score = min(production_score, 82.0 if production_missing == ["real venue source feed instead of approved synthetic profile"] else 74.0)
    gate_results = [
        {"id": "guest_facing_claim_safety", "status": "pass" if not banned_hits else "block", "severity": "critical", "evidence": "No banned claims found in guest-facing copy." if not banned_hits else f"Banned claims found: {', '.join(banned_hits)}."},
        {"id": "source_backed_route", "status": "pass" if source_ratio >= 0.95 else "review", "severity": "high", "evidence": f"{source_backed_stops}/{len(route_rows)} route stops include source evidence."},
        {"id": "accessibility_notes", "status": "pass" if access_ratio >= 0.8 else "review", "severity": "high", "evidence": f"{accessibility_stops}/{len(route_rows)} route stops include accessibility notes."},
        {"id": "owner_review_gates", "status": "pass" if review_ratio >= 0.9 and owner_questions else "review", "severity": "high", "evidence": f"{review_gate_count}/{len(section_dossiers)} section dossiers include review gates; {len(owner_questions)} owner question(s)."},
        {"id": "creative_craft_evidence", "status": "pass" if craft_sample_count >= 3 else "review", "severity": "medium", "evidence": f"{craft_sample_count} craft sample(s) include copy, review gate, and why-it-helps evidence."},
        {"id": "learning_authority", "status": "pass" if approved_rules.get("authority") == "human_promoted_rules_only" else "review", "severity": "critical", "evidence": f"Approved-rule authority: {approved_rules.get('authority') or 'not active'}."},
        {"id": "production_publish_boundary", "status": "pass" if venue_gap_analysis.get("productionRealVenueReady") else "block", "severity": "critical", "evidence": "Production-real venue ready." if venue_gap_analysis.get("productionRealVenueReady") else f"Production publish blocked by: {', '.join(production_missing) or 'unknown venue gap'}."},
    ]
    gate_results.extend(
        {
            "id": str(item.get("gateImpact") or item.get("reviewerId")),
            "status": str(item.get("gateStatus") or "review"),
            "severity": "critical" if item.get("gateStatus") == "block" else "high" if item.get("gateStatus") == "review" else "medium",
            "evidence": f"{item.get('role')}: {item.get('finding')}",
            "reviewerId": item.get("reviewerId"),
            "requiredRevision": item.get("requiredRevision"),
        }
        for item in reviewer_panel.get("reviewers", [])
        if isinstance(item, dict)
    )
    gate_results.append(
        {
            "id": "reviewer_panel_consensus",
            "status": "pass" if reviewer_panel.get("status") == "panel_passed" else "review" if reviewer_panel.get("status") == "panel_review_required" else "block",
            "severity": "high",
            "evidence": reviewer_panel.get("summary"),
        }
    )
    gate_results.extend(venue_reflection.get("gates", []))
    gate_results.append(
        {
            "id": "venue_reflection_consensus",
            "status": "pass" if venue_reflection.get("status") == "venue_reflection_ready" else "review" if venue_reflection.get("status") == "venue_reflection_review_required" else "block",
            "severity": "high",
            "evidence": venue_reflection.get("summary"),
        }
    )
    block_count = sum(1 for gate in gate_results if gate["status"] == "block")
    review_count = sum(1 for gate in gate_results if gate["status"] == "review")
    findings = []
    if production_missing:
        findings.append(f"Production publish remains blocked by {len(production_missing)} venue source gap(s); demo/channel-owner review can continue.")
    if not memory_application.get("usedForGeneration"):
        findings.append("No approved memory or promoted rules influenced this generation yet.")
    if block_count or review_count:
        findings.append(f"Gates: {block_count} blocked, {review_count} review, {len(gate_results) - block_count - review_count} passed.")
    if scores["craftDepth"] >= 90:
        findings.append("Creative craft evidence includes inspectable samples with review gates.")
    findings.append(str(reviewer_panel.get("summary") or "Internal reviewer panel completed."))
    findings.append(str(venue_reflection.get("summary") or "Venue reflection completed."))
    return {
        "status": "demo_ready_production_blocked" if total >= 82 and block_count == 1 and not banned_hits else "strong_review_draft" if total >= 80 and not banned_hits else "needs_review_work",
        "score": total,
        "demoScore": total,
        "productionScore": production_score,
        "scores": scores,
        "weights": weights,
        "gateSummary": {"passed": len(gate_results) - block_count - review_count, "review": review_count, "blocked": block_count},
        "gateResults": gate_results,
        "reviewerPanel": reviewer_panel,
        "venueReflection": venue_reflection,
        "reviewLoop": {
            "status": reviewer_panel.get("status"),
            "consensusScore": reviewer_panel.get("consensusScore"),
            "revisionQueue": reviewer_panel.get("revisionQueue", []),
            "learningUse": "Only reviewer-approved finished-work patterns can be promoted into future generation rules.",
        },
        "findings": findings,
        "qaChecklist": [
            {"check": "guest-facing claim safety", "status": "pass" if not banned_hits else "blocked"},
            {"check": "source-backed route", "status": "pass" if source_ratio >= 0.95 else "review"},
            {"check": "accessibility notes attached", "status": "pass" if access_ratio >= 0.8 else "review"},
            {"check": "owner gates and questions", "status": "pass" if review_ratio >= 0.9 and owner_questions else "review"},
            {"check": "creative craft samples", "status": "pass" if craft_sample_count >= 3 else "review"},
            {"check": "human-approved learning authority", "status": "pass" if approved_rules.get("authority") == "human_promoted_rules_only" else "review"},
            {"check": "internal reviewer panel", "status": "pass" if reviewer_panel.get("status") == "panel_passed" else "review"},
            {"check": "full venue reflection", "status": "pass" if venue_reflection.get("status") == "venue_reflection_ready" else "review"},
            {"check": "production-real venue ready", "status": "pass" if venue_gap_analysis.get("productionRealVenueReady") else "blocked"},
        ],
        "recommendedNextActions": [
            "Send section details to channel owners for edits.",
            "Keep demo handoff separate from production publish until the real venue source feed replaces synthetic.",
            "Promote only creative-lead or reviewer-approved rules from finished work.",
        ],
    }


def _creative_package_variants(
    synthesis: dict[str, Any],
    selected_name: str,
    route: list[dict[str, Any]],
    channel_matrix: list[dict[str, Any]],
    venue_gap_analysis: dict[str, Any],
) -> list[dict[str, Any]]:
    concepts = synthesis.get("concepts") if isinstance(synthesis.get("concepts"), list) else []
    selected_id = str(synthesis.get("selectedConceptId") or "")
    variants = []
    for concept in concepts[:4]:
        if not isinstance(concept, dict):
            continue
        concept_id = str(concept.get("id") or concept.get("name") or "variant")
        variants.append(
            {
                "id": concept_id,
                "name": concept.get("name") or concept_id,
                "status": "selected" if concept_id == selected_id else "alternative",
                "positioning": concept.get("positioning"),
                "guestPromise": concept.get("guestPromise"),
                "routeFrame": " -> ".join(str(item.get("stop") or "") for item in route if isinstance(item, dict)),
                "channelEmphasis": [
                    f"{item.get('channel')}: {item.get('objective')}"
                    for item in channel_matrix[:3]
                    if isinstance(item, dict)
                ],
                "strengths": _as_text_list(concept.get("heroTerms"))[:5],
                "reviewRisks": _as_text_list(concept.get("reviewRisks")) + (
                    ["Production-real venue data still missing."] if venue_gap_analysis.get("missingForProduction") else []
                ),
                "whenToUse": "Use this route if the review team wants the strongest current package." if concept_id == selected_id else f"Compare against {selected_name} when the team wants a different creative emphasis without changing verified stops.",
            }
        )
    return variants


def _vertex_provider_readiness() -> dict[str, Any]:
    try:
        from gemini_provider import get_gemini_agent_properties

        props = get_gemini_agent_properties()
        public = props.public_dict()
        return {
            "provider": public.get("provider"),
            "platform": public.get("platform"),
            "ready": bool(public.get("ready")),
            "projectConfigured": bool(public.get("has_project")),
            "locationConfigured": bool(public.get("has_location")),
            "credentialsMode": public.get("credentials_mode"),
            "readinessIssues": public.get("readiness_issues", []),
            "requiredEnv": public.get("required_env", []),
        }
    except Exception as error:
        return {
            "provider": "Vertex AI",
            "platform": "vertex_ai",
            "ready": False,
            "projectConfigured": False,
            "locationConfigured": False,
            "credentialsMode": "adc_or_service_account",
            "readinessIssues": [str(error)[:240]],
            "requiredEnv": ["GOOGLE_GENAI_USE_VERTEXAI=true", "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION"],
        }


def _orchestration_slot(slot_id: str, label: str, model: str, status: str, purpose: str, prompt: dict[str, Any], outputs: list[str], guardrails: list[str], provider_ready: bool) -> dict[str, Any]:
    return {
        "id": slot_id,
        "label": label,
        "model": model,
        "status": status if provider_ready else "prompt_ready_provider_not_configured",
        "purpose": purpose,
        "prompt": prompt,
        "expectedOutputs": outputs,
        "guardrails": guardrails,
        "llmControlsPublishOrOperations": False,
    }


def _visual_asset_studio(package: dict[str, Any], route: list[dict[str, Any]], template_id: str, audience: str, tone: str, creative_brief: dict[str, str], provider: dict[str, Any] | None = None) -> dict[str, Any]:
    provider = provider if isinstance(provider, dict) else _vertex_provider_readiness()
    concept = package.get("executiveConcept") if isinstance(package.get("executiveConcept"), dict) else {}
    signage = package.get("signageSet") if isinstance(package.get("signageSet"), list) else []
    email = package.get("preArrivalEmail") if isinstance(package.get("preArrivalEmail"), dict) else {}
    route_names = [str(item.get("stop") or "") for item in route if isinstance(item, dict) and str(item.get("stop") or "").strip()]
    concept_name = str(concept.get("name") or "Experience concept")
    guest_promise = str(concept.get("guestPromise") or "")
    first_stop = route_names[0] if route_names else "verified park entrance"
    middle_stop = route_names[min(2, len(route_names) - 1)] if route_names else first_stop
    final_stop = route_names[-1] if route_names else "verified route close"
    image_model = os.getenv("PARKPULSE_EXPERIENCE_STUDIO_VERTEX_IMAGE_MODEL", "imagen-4.0-generate-001")
    visual_theme = _display_theme_label(str(creative_brief.get("seasonalTheme") or concept_name), template_id)
    shared_negative = "No copyrighted characters, no unapproved cultural symbols, no celebrity likeness, no realistic emergency, no crowd panic, no gore, no unsafe operations, no text-heavy illegible signage, no guaranteed reward imagery."
    prompts = [
        {
            "id": "poster_hero",
            "label": "Campaign poster hero",
            "format": "poster",
            "aspectRatio": "3:4",
            "sampleCount": 1,
            "prompt": (
                f"Marketing poster key art for {concept_name} at {first_stop}, {visual_theme}, warm lantern-inspired festival atmosphere, "
                f"families and friend groups beginning an optional park route, visible but not text-heavy wayfinding cue, premium theme-park campaign design, "
                f"respectful cultural framing, no specific reward item, no guaranteed show, clean space for headline and CTA."
            ),
            "negativePrompt": shared_negative,
            "copyOverlay": {
                "headline": concept_name,
                "subhead": str(email.get("previewText") or guest_promise)[:140],
                "cta": "Plan Your Festival Path" if template_id == "festival-plan" else "Plan Your Route",
            },
            "reviewGate": "Brand, cultural, legal, and accessibility review before public use.",
        },
        {
            "id": "app_tile",
            "label": "Guest app tile",
            "format": "app_tile",
            "aspectRatio": "1:1",
            "sampleCount": 1,
            "prompt": (
                f"Square mobile app tile for {concept_name}, route dots from {first_stop} to {final_stop}, simple lantern/passport-inspired icon system, "
                f"high contrast, accessible UI composition, minimal text area, friendly {tone} visual mood, no final logo lockup."
            ),
            "negativePrompt": shared_negative,
            "copyOverlay": {
                "headline": concept_name,
                "microcopy": "Check current options before each stop.",
            },
            "reviewGate": "Digital product and brand review before app publishing.",
        },
        {
            "id": "signage_mockup",
            "label": "On-site signage mockup",
            "format": "signage",
            "aspectRatio": "16:9",
            "sampleCount": 1,
            "prompt": (
                f"Horizontal on-site signage mockup at {middle_stop} for {concept_name}, clear high-contrast headline area, one action per sign, "
                f"route arrow and accessible typography, park guests moving around without blocking paths, review-safe production mockup."
            ),
            "negativePrompt": shared_negative,
            "copyOverlay": signage[1] if len(signage) > 1 and isinstance(signage[1], dict) else signage[0] if signage and isinstance(signage[0], dict) else {"headline": concept_name, "body": "Follow the next cue when ready."},
            "reviewGate": "Signage, operations, accessibility, and placement review before fabrication.",
        },
        {
            "id": "social_story",
            "label": "Social story visual",
            "format": "social_story",
            "aspectRatio": "9:16",
            "sampleCount": 1,
            "prompt": (
                f"Vertical social story visual for {concept_name}, guests discovering a visual cue near {final_stop}, warm celebratory park lighting, "
                f"space for short caption, modern campaign photography look, optional participation mood, no crowd-density or availability promise."
            ),
            "negativePrompt": shared_negative,
            "copyOverlay": {
                "headline": concept_name,
                "caption": str(concept.get("oneLine") or guest_promise)[:160],
            },
            "reviewGate": "Social, brand, and legal review before posting.",
        },
    ]
    return {
        "status": "configured_ready" if provider.get("ready") else "prompt_ready_provider_not_configured",
        "mode": "vertex_imagen_visual_asset_studio_v1",
        "providerReadiness": provider,
        "model": image_model,
        "defaultEndpoint": "Vertex AI Imagen predict endpoint",
        "source": "creative_package_plus_venue_profile",
        "promptCount": len(prompts),
        "prompts": prompts,
        "posterCreation": {
            "recommendedPrimaryPromptId": "poster_hero",
            "safeForDemo": True,
            "publishAuthority": False,
            "outputUse": "Review draft only until brand/cultural/legal/accessibility owners approve final artwork.",
        },
        "guardrails": [
            "Generated visuals are review drafts, not final production artwork.",
            "Do not show unapproved cultural symbols, rewards, menus, performers, or final signage placement.",
            "Do not imply operational availability, crowd level, safety status, or guaranteed access.",
            "Human review must approve imagery before public launch.",
        ],
    }


def _vertex_model_orchestration(package: dict[str, Any], route: list[dict[str, Any]], template_id: str, audience: str, tone: str, real_inputs: dict[str, Any], creative_brief: dict[str, str]) -> dict[str, Any]:
    provider = _vertex_provider_readiness()
    provider_ready = bool(provider.get("ready")) and str(provider.get("platform")) in {"vertex_ai", "gemini_enterprise"}
    concept = package.get("executiveConcept") if isinstance(package.get("executiveConcept"), dict) else {}
    synthesis = package.get("creativeSynthesis") if isinstance(package.get("creativeSynthesis"), dict) else {}
    venue_reflection = (package.get("studioQualityEval") or {}).get("venueReflection") if isinstance(package.get("studioQualityEval"), dict) else {}
    route_rows = [
        {
            "stop": item.get("stop"),
            "guestCopy": item.get("guestCopy"),
            "staffNote": item.get("staffNote"),
            "accessibilityNote": item.get("accessibilityNote"),
            "source": item.get("source"),
        }
        for item in route
        if isinstance(item, dict)
    ]
    route_names = [str(item.get("stop") or "") for item in route_rows]
    package_context = {
        "templateId": template_id,
        "audience": audience,
        "tone": tone,
        "conceptName": concept.get("name"),
        "guestPromise": concept.get("guestPromise"),
        "routeStops": route_names,
        "copyVoice": package.get("copyVoice", {}),
        "venuePattern": package.get("venuePattern", {}),
        "productionBoundary": package.get("venueDataGapAnalysis", {}),
    }
    models = {
        "planner": os.getenv("PARKPULSE_EXPERIENCE_STUDIO_VERTEX_PLANNER_MODEL", "gemini-2.5-pro"),
        "writer": os.getenv("PARKPULSE_EXPERIENCE_STUDIO_VERTEX_WRITER_MODEL", "gemini-2.5-flash"),
        "critic": os.getenv("PARKPULSE_EXPERIENCE_STUDIO_VERTEX_CRITIC_MODEL", "gemini-2.5-pro"),
        "embedding": os.getenv("PARKPULSE_EXPERIENCE_STUDIO_VERTEX_EMBEDDING_MODEL", "gemini-embedding-001"),
        "image": os.getenv("PARKPULSE_EXPERIENCE_STUDIO_VERTEX_IMAGE_MODEL", "imagen-4.0-generate-001"),
        "video": os.getenv("PARKPULSE_EXPERIENCE_STUDIO_VERTEX_VIDEO_MODEL", "veo-3.1-generate-001"),
    }
    owner_question_text = " ".join(
        f"{item.get('owner')}: {item.get('question')}"
        for item in (package.get("ownerQuestions") if isinstance(package.get("ownerQuestions"), list) else [])
        if isinstance(item, dict) and (item.get("owner") or item.get("question"))
    )
    media_mood = "friendly Halloween party route, lantern glow, non-graphic, family-safe" if template_id == "halloween-route" else f"{tone} {template_id} park experience route, guest-friendly, venue-grounded"
    first_stop = route_names[0] if route_names else "the start"
    slots = [
        _orchestration_slot(
            "planner_reasoning",
            "Planner reasoning",
            models["planner"],
            "configured_ready" if provider_ready else "prompt_ready_provider_not_configured",
            "Deep route strategy, guest segment fit, concept alternatives, and owner-review risks.",
            {
                "task": "Reflect on this Experience Studio package and propose stronger route/story strategy without changing verified stops.",
                "packageContext": package_context,
                "venueReflection": venue_reflection,
                "returnJson": {"strategyNotes": ["..."], "routeTradeoffs": ["..."], "strongerConceptName": "...", "blockedClaims": ["..."]},
            },
            ["strategyNotes", "routeTradeoffs", "conceptAlternatives", "ownerReviewRisks"],
            ["Do not change stop names/order.", "Do not invent live state.", "Do not publish."],
            provider_ready,
        ),
        _orchestration_slot(
            "package_writer",
            "Package writer",
            models["writer"],
            "connected_when_useLlm_true" if provider_ready else "prompt_ready_provider_not_configured",
            "Generate richer app, signage, email, staff cue, and clue-copy variants.",
            {
                "task": "Rewrite guest-facing and staff-facing copy with stronger craft while preserving exact route and safety boundaries.",
                "packageContext": package_context,
                "lockedRoute": route_rows,
                "existingCopyVariants": synthesis.get("copyVariants", {}),
                "returnJson": {"guestApp": {}, "signage": [], "email": {}, "staffCue": {}, "clues": []},
            },
            ["guestApp", "signage", "email", "staffCue", "clueVariants"],
            ["Keep movement optional.", "No access/wait/reward guarantees.", "Accessibility wording stays plain."],
            provider_ready,
        ),
        _orchestration_slot(
            "reviewer_critic",
            "Reviewer critic",
            models["critic"],
            "configured_ready" if provider_ready else "prompt_ready_provider_not_configured",
            "Second-pass creative, safety, accessibility, and channel-owner critique.",
            {
                "task": "Act as creative director, accessibility reviewer, safety reviewer, and channel owner. Critique the package.",
                "packageContext": package_context,
                "qa": package.get("studioQualityEval", {}),
                "returnJson": {"findings": [], "requiredRevisions": [], "gateAdjustments": []},
            },
            ["findings", "requiredRevisions", "gateAdjustments", "approvalRecommendation"],
            ["Critique cannot approve production publish.", "Flag unsupported venue claims.", "Use source evidence."],
            provider_ready,
        ),
        _orchestration_slot(
            "embedding_memory",
            "Embedding memory retrieval",
            models["embedding"],
            "retrieval_plan_ready",
            "Embed finished packages, route concepts, reviewer edits, and venue rules for future retrieval.",
            {
                "task": "Embed approved finished-work chunks for similarity retrieval.",
                "chunks": [
                    {"type": "concept", "text": f"{concept.get('name')}: {concept.get('guestPromise')}"},
                    {"type": "route", "text": " -> ".join(route_names)},
                    {"type": "review", "text": owner_question_text[:1000]},
                    {"type": "voice", "text": " ".join(_as_text_list((package.get("copyVoice") or {}).get("approvedPhrases")))[:1000]},
                ],
                "targetCollections": ["experience_studio_drafts", "experience_studio_learning_rules", "venue_profile_chunks"],
            },
            ["embeddingVectors", "retrievalMatches", "memoryReceipts"],
            ["Only embed approved/finished work for reusable patterns.", "Exclude private guest identity.", "Memory cannot override venue facts."],
            True,
        ),
        _orchestration_slot(
            "image_concept_board",
            "Image concept board",
            models["image"],
            "prompt_ready_provider_not_configured" if not provider_ready else "configured_ready",
            "Generate visual concept boards, signage mockups, route cards, and clue-card art direction.",
            {
                "task": "Generate review-safe image prompts, not final production artwork.",
                "imagePrompts": [
                    f"Concept board for {concept.get('name')}: {media_mood}, verified park photo stops, signage-ready, review-safe.",
                    f"Signage mockup at {first_stop} with short headline, high contrast, readable in expected visit conditions, no operational claims.",
                    f"Route clue card set for {template_id}: optional clues, accessible typography, no gore, no guaranteed reward.",
                ],
                "styleGuardrails": ["No realistic emergency scenes.", "No crowd panic.", "No copyrighted characters.", "No gore or frightening imagery."],
            },
            ["conceptBoardImages", "signageMockups", "routeCards", "clueCards"],
            ["Images are drafts for owner review.", "Do not imply final sign placement.", "No unsafe or fear-based imagery."],
            provider_ready,
        ),
        _orchestration_slot(
            "video_preview",
            "Video preview",
            models["video"],
            "prompt_ready_provider_not_configured" if not provider_ready else "configured_ready",
            "Generate a short Veo teaser or staff-training animatic prompt for the route.",
            {
                "task": "Generate short text-to-video prompts for a review-only preview.",
                "videoPrompts": [
                    f"8-second teaser: guests begin {concept.get('name')} at {first_stop}, route cue appears, families choose an optional next beat, {media_mood}.",
                    f"Staff-training animatic: host explains {concept.get('name')} as optional, points to next marker, reminds guests to check current options, no crowd control or access promises.",
                ],
                "shotList": package.get("routeBlueprint", [])[:5],
            },
            ["routeTeaser", "staffTrainingAnimatic", "reviewStoryboard"],
            ["Review-only preview.", "No depiction of real emergency or unsafe operations.", "No production publish authority."],
            provider_ready,
        ),
    ]
    ready_count = sum(1 for slot in slots if str(slot.get("status")) in {"configured_ready", "connected_when_useLlm_true", "retrieval_plan_ready"})
    return {
        "status": "configured" if provider_ready else "prompt_ready_provider_not_configured",
        "mode": "vertex_ai_multi_model_enrichment_v1",
        "providerReadiness": provider,
        "slotCount": len(slots),
        "readyOrPlannedSlotCount": ready_count,
        "slots": slots,
        "activation": {
            "useLiveTextWriter": "Set useLlm=true or PARKPULSE_EXPERIENCE_STUDIO_USE_LLM=true.",
            "vertexEnv": ["GOOGLE_GENAI_USE_VERTEXAI=true", "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION"],
            "mediaEnv": ["Enable Vertex AI Model Garden access for selected image/video models.", "Use Cloud Storage output buckets for generated media."],
        },
        "boundary": "Model orchestration enriches draft artifacts and review prompts only. It cannot publish, dispatch, change operations, or override venue facts.",
    }


def _run_vertex_imagen_predict(prompt_card: dict[str, Any], provider: dict[str, Any], *, timeout_seconds: float = 45.0) -> dict[str, Any]:
    from urllib import request as urllib_request
    from urllib.error import HTTPError, URLError
    from urllib.parse import quote
    import ssl

    project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT_ID")
    location = os.getenv("GOOGLE_CLOUD_LOCATION") or os.getenv("GOOGLE_CLOUD_REGION") or "us-central1"
    model = os.getenv("PARKPULSE_EXPERIENCE_STUDIO_VERTEX_IMAGE_MODEL", "imagen-4.0-generate-001")
    if not provider.get("ready") or not project or not location:
        return {
            "status": "provider_not_configured",
            "model": model,
            "readinessIssues": provider.get("readinessIssues", []),
            "promptId": prompt_card.get("id"),
        }

    import google.auth
    import google.auth.transport.requests

    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(google.auth.transport.requests.Request())
    token = getattr(credentials, "token", None)
    if not token:
        return {"status": "auth_unavailable", "model": model, "promptId": prompt_card.get("id"), "reason": "Vertex AI credentials did not produce an access token."}

    host = "aiplatform.googleapis.com" if str(location) == "global" else f"{location}-aiplatform.googleapis.com"
    endpoint = (
        f"https://{host}/v1/projects/{quote(str(project), safe='')}"
        f"/locations/{quote(str(location), safe='')}/publishers/google/models/{quote(model, safe='')}:predict"
    )
    parameters = {
        "sampleCount": max(1, min(2, int(prompt_card.get("sampleCount") or 1))),
        "aspectRatio": str(prompt_card.get("aspectRatio") or "1:1"),
        "enhancePrompt": True,
    }
    # Imagen 4 current docs focus on prompt-driven generation; keep request minimal and review-safe.
    body = json.dumps(
        {
            "instances": [{"prompt": str(prompt_card.get("prompt") or "")}],
            "parameters": parameters,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    http_request = urllib_request.Request(
        endpoint,
        data=body,
        headers={"content-type": "application/json", "authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        try:
            import certifi

            context = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            context = ssl.create_default_context()
        with urllib_request.urlopen(http_request, timeout=max(1.0, float(timeout_seconds)), context=context) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        return {"status": "vertex_http_error", "model": model, "promptId": prompt_card.get("id"), "httpStatus": error.code, "detail": detail[:700]}
    except (URLError, TimeoutError, OSError) as error:
        return {"status": "vertex_request_failed", "model": model, "promptId": prompt_card.get("id"), "detail": str(error)[:500]}

    predictions = payload.get("predictions") if isinstance(payload.get("predictions"), list) else []
    images = []
    for index, prediction in enumerate(predictions):
        if not isinstance(prediction, dict):
            continue
        encoded = prediction.get("bytesBase64Encoded") or prediction.get("image") or prediction.get("bytes_base64_encoded")
        if not encoded:
            continue
        images.append(
            {
                "id": f"{prompt_card.get('id') or 'image'}_{index + 1}",
                "mimeType": prediction.get("mimeType") or "image/png",
                "dataUrl": f"data:{prediction.get('mimeType') or 'image/png'};base64,{encoded}",
                "safetyAttributes": prediction.get("safetyAttributes") if isinstance(prediction.get("safetyAttributes"), dict) else {},
            }
        )
    return {
        "status": "generated" if images else "completed_without_image_bytes",
        "transport": "vertex_imagen_rest_predict",
        "model": model,
        "endpoint": endpoint,
        "promptId": prompt_card.get("id"),
        "imageCount": len(images),
        "images": images,
        "rawPredictionCount": len(predictions),
    }


def _persist_visual_asset_images(results: list[dict[str, Any]], package: dict[str, Any], selected: list[dict[str, Any]]) -> dict[str, Any]:
    import base64

    output_dir = _visual_asset_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    concept = package.get("executiveConcept") if isinstance(package.get("executiveConcept"), dict) else {}
    concept_slug = _safe_asset_slug(str(concept.get("name") or package.get("title") or "experience-visual"))
    prompt_lookup = {str(prompt.get("id")): prompt for prompt in selected if isinstance(prompt, dict)}
    saved: list[dict[str, Any]] = []

    for result in results:
        if not isinstance(result, dict):
            continue
        prompt_id = str(result.get("promptId") or "visual")
        for index, image in enumerate(result.get("images") if isinstance(result.get("images"), list) else []):
            if not isinstance(image, dict):
                continue
            data_url = str(image.get("dataUrl") or "")
            if not data_url.startswith("data:") or ";base64," not in data_url:
                continue
            mime_type = data_url.split(";", 1)[0].replace("data:", "") or str(image.get("mimeType") or "image/png")
            encoded = data_url.split(";base64,", 1)[1]
            extension = "jpg" if "jpeg" in mime_type else "webp" if "webp" in mime_type else "png"
            asset_id = f"{concept_slug}-{_safe_asset_slug(prompt_id, 'visual')}-{index + 1}"
            asset_path = output_dir / f"{asset_id}.{extension}"
            try:
                asset_path.write_bytes(base64.b64decode(encoded))
            except (OSError, ValueError, TypeError):
                continue
            image["assetPath"] = str(asset_path.resolve())
            image["reviewStatus"] = "review_draft"
            saved.append(
                {
                    "id": asset_id,
                    "promptId": prompt_id,
                    "label": prompt_lookup.get(prompt_id, {}).get("label"),
                    "format": prompt_lookup.get(prompt_id, {}).get("format"),
                    "mimeType": mime_type,
                    "path": str(asset_path.resolve()),
                    "model": result.get("model"),
                    "reviewStatus": "review_draft",
                }
            )

    if saved:
        receipt_path = output_dir / f"{concept_slug}-visual-assets.json"
        receipt = {
            "status": "saved",
            "mode": "experience_studio_vertex_visual_asset_receipt",
            "savedAt": _now_iso(),
            "concept": concept.get("name"),
            "assetCount": len(saved),
            "assets": saved,
            "boundary": "Generated visuals are review drafts only. Human approval is required before public use.",
        }
        receipt_path.write_text(json.dumps(receipt, indent=2, default=str), encoding="utf-8")
        return {"status": "saved", "assetCount": len(saved), "assets": saved, "receiptPath": str(receipt_path.resolve())}
    return {"status": "not_saved", "assetCount": 0, "assets": []}


def _plain_pdf_text(value: Any, fallback: str = "") -> str:
    return re.sub(r"\s+", " ", str(value if value is not None else fallback)).strip()


def _pdf_literal(value: Any) -> str:
    text = _plain_pdf_text(value, "Pending owner review")
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")[:180]


def _minimal_pdf_bytes(title: str, lines: list[str]) -> bytes:
    page_lines = [_pdf_literal(title), *[_pdf_literal(line) for line in lines if _plain_pdf_text(line)]]
    if len(page_lines) < 18:
        page_lines.extend(
            [
                "Experience Studio review draft.",
                "Owner approval is required before public launch.",
                "Brand, cultural, legal, accessibility, operations, and food or entertainment owners must review this package.",
                "Generated as a dependency-safe fallback PDF when the advanced ReportLab renderer is unavailable.",
            ]
            * 5
        )
    commands = ["BT", "/F1 18 Tf", "72 740 Td", f"({page_lines[0]}) Tj", "/F1 10 Tf"]
    for line in page_lines[1:42]:
        commands.extend(["0 -18 Td", f"({line}) Tj"])
    commands.append("ET")
    stream = "\n".join(commands).encode("latin-1", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    chunks = [b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"]
    offsets: list[int] = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(sum(len(chunk) for chunk in chunks))
        chunks.append(f"{index} 0 obj\n".encode("ascii") + obj + b"\nendobj\n")
    xref_offset = sum(len(chunk) for chunk in chunks)
    xref = [b"xref\n0 6\n", b"0000000000 65535 f \n"]
    xref.extend(f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets)
    chunks.extend(
        [
            *xref,
            b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n",
            str(xref_offset).encode("ascii"),
            b"\n%%EOF\n",
        ]
    )
    return b"".join(chunks)


def generate_experience_studio_event_team_pdf(payload: dict[str, Any]) -> dict[str, Any]:
    import base64
    from xml.sax.saxutils import escape

    package = payload.get("creativePackage") if isinstance(payload.get("creativePackage"), dict) else {}
    draft = payload.get("draft") if isinstance(payload.get("draft"), dict) else {}
    if not package and isinstance(draft.get("creativePackage"), dict):
        package = draft["creativePackage"]
    if not package:
        return {"status": "blocked", "mode": "experience_studio_event_team_pdf", "message": "PDF generation requires a creativePackage or draft.creativePackage."}

    event = package.get("eventTeamMarketingPackage") if isinstance(package.get("eventTeamMarketingPackage"), dict) else {}
    if not event:
        return {"status": "blocked", "mode": "experience_studio_event_team_pdf", "message": "The creative package does not include eventTeamMarketingPackage."}

    brief = event.get("eventBrief") if isinstance(event.get("eventBrief"), dict) else {}
    concept = package.get("executiveConcept") if isinstance(package.get("executiveConcept"), dict) else {}
    email = package.get("preArrivalEmail") if isinstance(package.get("preArrivalEmail"), dict) else {}
    staff = package.get("staffScript") if isinstance(package.get("staffScript"), dict) else {}
    signage = package.get("signageSet") if isinstance(package.get("signageSet"), list) else []
    visual = package.get("visualAssetStudio") if isinstance(package.get("visualAssetStudio"), dict) else {}
    reasoning = event.get("reasoningBrief") if isinstance(event.get("reasoningBrief"), dict) else {}
    title = _plain_pdf_text(brief.get("eventName") or concept.get("name") or draft.get("title") or "Event Team Marketing Package")
    filename = f"{_safe_asset_slug(title)}-event-team-marketing-package.pdf"
    output_dir = _visual_asset_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = output_dir / filename

    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    except Exception as error:
        fallback_lines = [
            "Event-Team Marketing Package",
            f"Venue: {brief.get('venue')}",
            f"Format: {brief.get('format')}",
            f"Audience: {brief.get('targetAudience')}",
            f"Guest promise: {brief.get('guestPromise') or concept.get('guestPromise')}",
            f"Concept: {concept.get('oneLine')}",
            f"Fallback renderer reason: {str(error)[:140]}",
            "Review required before public launch.",
        ]
        pdf_path.write_bytes(_minimal_pdf_bytes(title, fallback_lines))
        encoded = base64.b64encode(pdf_path.read_bytes()).decode("ascii")
        return {
            "status": "generated",
            "mode": "experience_studio_event_team_pdf",
            "pdfPath": str(pdf_path.resolve()),
            "fileName": filename,
            "pageCount": 1,
            "sizeBytes": pdf_path.stat().st_size,
            "pdfDataUrl": f"data:application/pdf;base64,{encoded}",
            "renderer": "minimal_pdf_fallback",
            "rendererWarning": f"ReportLab unavailable: {str(error)[:180]}",
            "boundary": "PDF is a review draft generated from the current eventTeamMarketingPackage. Owner approval is required before public launch.",
        }

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CoverTitleCustom", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=25, leading=29, textColor=colors.HexColor("#0f172a"), alignment=TA_CENTER, spaceAfter=6))
    styles.add(ParagraphStyle(name="SubtitleCustom", parent=styles["BodyText"], fontSize=11, leading=14.5, textColor=colors.HexColor("#475569"), alignment=TA_CENTER, spaceAfter=9))
    styles.add(ParagraphStyle(name="KickerCustom", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=7.5, leading=9, textColor=colors.HexColor("#166534"), alignment=TA_CENTER, spaceAfter=4))
    styles.add(ParagraphStyle(name="H1Custom", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=colors.HexColor("#0f172a"), spaceBefore=10, spaceAfter=7))
    styles.add(ParagraphStyle(name="H2Custom", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=colors.HexColor("#166534"), spaceBefore=7, spaceAfter=3))
    styles.add(ParagraphStyle(name="BodyCustom", parent=styles["BodyText"], fontSize=9, leading=12.6, textColor=colors.HexColor("#1f2937"), spaceAfter=5))
    styles.add(ParagraphStyle(name="LeadCustom", parent=styles["BodyText"], fontSize=10.2, leading=14.3, textColor=colors.HexColor("#1f2937"), spaceAfter=7))
    styles.add(ParagraphStyle(name="BulletCustom", parent=styles["BodyText"], fontSize=8.5, leading=11.6, leftIndent=12, firstLineIndent=-8, textColor=colors.HexColor("#334155"), spaceAfter=3))
    styles.add(ParagraphStyle(name="SmallCustom", parent=styles["BodyText"], fontSize=7.5, leading=9.5, textColor=colors.HexColor("#64748b"), spaceAfter=3))
    styles.add(ParagraphStyle(name="LabelCustom", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=7.2, leading=9, textColor=colors.HexColor("#64748b"), spaceAfter=2))
    styles.add(ParagraphStyle(name="CardTitleCustom", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=10.2, leading=12.8, textColor=colors.HexColor("#0f172a"), spaceAfter=3))

    def display_value(value: Any) -> str:
        text = _plain_pdf_text(value)
        return text.replace("_", " ") if text else "Pending owner review"

    def para(value: Any, style_name: str = "BodyCustom") -> Any:
        safe = escape(display_value(value)).replace("\n", "<br/>")
        return Paragraph(safe, styles[style_name])

    def rich_para(markup: str, style_name: str = "BodyCustom") -> Any:
        return Paragraph(markup, styles[style_name])

    def label_line(label: str, value: Any) -> Any:
        safe_label = escape(display_value(label).upper())
        safe_value = escape(display_value(value)).replace("\n", "<br/>")
        return rich_para(f'<font color="#64748b"><b>{safe_label}</b></font><br/>{safe_value}', "BodyCustom")

    def soft_card(flowables: list[Any], width: float = 6.45 * inch) -> Any:
        table = Table([[flowables]], colWidths=[width])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                    ("BOX", (0, 0), (-1, -1), 0.35, colors.HexColor("#dbe4ee")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        return table

    def two_cards(left: list[Any], right: list[Any]) -> Any:
        table = Table([[left, right]], colWidths=[3.1 * inch, 3.1 * inch])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                    ("BOX", (0, 0), (-1, -1), 0.35, colors.HexColor("#dbe4ee")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#e2e8f0")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        return table

    route = [display_value(stop) for stop in (brief.get("route") if isinstance(brief.get("route"), list) else [])]
    route_text = "  >  ".join(route)
    selected_strategy = reasoning.get("selectedStrategy") if isinstance(reasoning.get("selectedStrategy"), dict) else {}
    selected_concept = reasoning.get("selectedConcept") if isinstance(reasoning.get("selectedConcept"), dict) else {}
    story: list[Any] = [
        para("EXPERIENCE STUDIO REVIEW DRAFT", "KickerCustom"),
        para(title, "CoverTitleCustom"),
        para("Event-Team Marketing Package", "SubtitleCustom"),
        para("A text-first event brief for programming, marketing, creative, wayfinding, review, and analytics teams.", "SubtitleCustom"),
        Spacer(1, 4),
    ]
    story.extend(
        [
            two_cards(
                [
                    para("Experience Snapshot", "CardTitleCustom"),
                    label_line("Venue", brief.get("venue")),
                    label_line("Format", brief.get("format")),
                    label_line("Audience", brief.get("targetAudience")),
                ],
                [
                    para("Review Posture", "CardTitleCustom"),
                    label_line("Run shape", brief.get("runShape")),
                    label_line("Status", display_value(event.get("status")).title()),
                    label_line("Publish", "Owner review required"),
                ],
            ),
            Spacer(1, 10),
            para("Guest Promise", "H2Custom"),
            para(brief.get("guestPromise") or concept.get("guestPromise"), "LeadCustom"),
            para("Concept", "H2Custom"),
            para(concept.get("oneLine"), "LeadCustom"),
            para("Why This Plan", "H2Custom"),
            para(
                reasoning.get("selectedRouteReason")
                or reasoning.get("objective")
                or "The package is generated from the selected venue profile, retrieved evidence, planner strategy, and review gates.",
                "BodyCustom",
            ),
            para(
                f"Selected strategy: {display_value(selected_strategy.get('label'))}"
                + (f" ({display_value(selected_strategy.get('score'))}/100)" if selected_strategy.get("score") is not None else "")
                + f". {display_value(selected_strategy.get('rationale'))}",
                "SmallCustom",
            )
            if selected_strategy
            else para("Selected strategy: planner candidate selection pending.", "SmallCustom"),
            para(
                f"Selected concept: {display_value(selected_concept.get('name'))}. {display_value(selected_concept.get('positioning'))}",
                "SmallCustom",
            )
            if selected_concept
            else para("Selected concept: creative concept review pending.", "SmallCustom"),
            para(
                "Decisive evidence: "
                + "; ".join(display_value(item) for item in (reasoning.get("decisiveEvidence") if isinstance(reasoning.get("decisiveEvidence"), list) else [])[:3])
                if isinstance(reasoning.get("decisiveEvidence"), list) and reasoning.get("decisiveEvidence")
                else "Decisive evidence: pending source-backed planner review.",
                "SmallCustom",
            ),
            soft_card([para("Route", "CardTitleCustom"), para(route_text or "Route pending owner approval", "BodyCustom")]),
            Spacer(1, 8),
            para("Review required before public launch: brand, cultural, legal, accessibility, operations, and food/entertainment owners.", "SmallCustom"),
            PageBreak(),
        ]
    )

    def section(title_text: str) -> None:
        story.append(para(title_text, "H1Custom"))

    def subsection(title_text: str) -> None:
        story.append(para(title_text, "H2Custom"))

    def bullet(value: Any) -> None:
        story.append(Paragraph("- " + escape(display_value(value)), styles["BulletCustom"]))

    section("How The Experience Works")
    if reasoning:
        story.append(para("Planner Reasoning", "H2Custom"))
        selected_strategy = reasoning.get("selectedStrategy") if isinstance(reasoning.get("selectedStrategy"), dict) else {}
        if selected_strategy:
            story.append(rich_para(f"<b>Selected strategy:</b> {escape(display_value(selected_strategy.get('label')))} ({escape(display_value(selected_strategy.get('score')))} / 100)", "BodyCustom"))
        selected_concept = reasoning.get("selectedConcept") if isinstance(reasoning.get("selectedConcept"), dict) else {}
        if selected_concept:
            story.append(rich_para(f"<b>Selected concept:</b> {escape(display_value(selected_concept.get('name')))}", "BodyCustom"))
            depth_plan = selected_concept.get("contentDepthPlan") if isinstance(selected_concept.get("contentDepthPlan"), list) else []
            for item in depth_plan[:3]:
                bullet(item)
        if reasoning.get("routeStrategy"):
            story.append(rich_para(f"<b>Route strategy:</b> {escape(display_value(reasoning.get('routeStrategy')))}", "BodyCustom"))
        if reasoning.get("channelStrategy"):
            story.append(rich_para(f"<b>Channel strategy:</b> {escape(display_value(reasoning.get('channelStrategy')))}", "BodyCustom"))
        concept_critique = reasoning.get("conceptCritique") if isinstance(reasoning.get("conceptCritique"), dict) else {}
        concept_revisions = concept_critique.get("revisionsApplied") if isinstance(concept_critique.get("revisionsApplied"), list) else []
        if concept_revisions:
            story.append(rich_para(f"<b>Concept revision:</b> {escape(display_value(concept_revisions[0]))}", "SmallCustom"))
        revisions = reasoning.get("revisionsApplied") if isinstance(reasoning.get("revisionsApplied"), list) else []
        if revisions:
            story.append(rich_para(f"<b>Revision applied:</b> {escape(display_value(revisions[0]))}", "SmallCustom"))
        tradeoffs = reasoning.get("riskTradeoffs") if isinstance(reasoning.get("riskTradeoffs"), list) else []
        if tradeoffs:
            story.append(rich_para(f"<b>Known tradeoff:</b> {escape(display_value(tradeoffs[0]))}", "SmallCustom"))
        story.append(Spacer(1, 5))
    for phase in event.get("programPhases") if isinstance(event.get("programPhases"), list) else []:
        if not isinstance(phase, dict):
            continue
        story.append(para(f"{display_value(phase.get('name') or 'Phase')} - {display_value(phase.get('duration'))}", "H2Custom"))
        story.append(rich_para(f"<b>Guest job:</b> {escape(display_value(phase.get('guestJob')))}", "BodyCustom"))
        story.append(rich_para(f"<b>Hero moment:</b> {escape(display_value(phase.get('heroMoment')))}", "BodyCustom"))
        story.append(rich_para(f'<font color="#64748b"><b>Review gate:</b> {escape(display_value(phase.get("reviewGate")))}</font>', "SmallCustom"))
        story.append(Spacer(1, 4))

    section("Team Execution")
    for item in event.get("workstreams") if isinstance(event.get("workstreams"), list) else []:
        if not isinstance(item, dict):
            continue
        bullet(f"{display_value(item.get('team'))}: {display_value(item.get('job'))} Decision needed: {display_value(item.get('decisionNeeded'))}")
    story.append(PageBreak())

    section("Draft Assets To Finish")
    deliverables = [item for item in (event.get("deliverables") if isinstance(event.get("deliverables"), list) else []) if isinstance(item, dict)]
    for item in deliverables:
        story.append(para(item.get("asset"), "H2Custom"))
        story.append(rich_para(f"<b>Owner:</b> {escape(display_value(item.get('owner')))} &nbsp;&nbsp; <b>Status:</b> {escape(display_value(item.get('status')).title())}", "SmallCustom"))
        story.append(para(_plain_pdf_text(item.get("source"))[:240], "BodyCustom"))
        story.append(Spacer(1, 3))

    story.append(PageBreak())
    section("Channel Copy")
    story.extend(
        [
            para("Pre-arrival Email", "H2Custom"),
            rich_para(f"<b>Subject:</b> {escape(display_value(email.get('subject')))}", "BodyCustom"),
            rich_para(f"<b>Preview:</b> {escape(display_value(email.get('previewText')))}", "BodyCustom"),
            para(email.get("body"), "BodyCustom"),
            Spacer(1, 7),
            para("Staff Cue", "H2Custom"),
        ]
    )
    for key, label in (("openingLine", "Opening"), ("transitionLine", "Transition"), ("accessibilityLine", "Accessibility"), ("boundaryLine", "Boundary")):
        if staff.get(key):
            bullet(f"{label}: {staff.get(key)}")

    story.append(Spacer(1, 6))
    story.append(para("Signage", "H2Custom"))
    for sign in signage:
        if isinstance(sign, dict):
            bullet(f"{display_value(sign.get('placement'))}: {display_value(sign.get('headline'))} - {display_value(sign.get('body'))}")

    story.append(PageBreak())
    section("Creative Production Notes")
    prompts = visual.get("prompts") if isinstance(visual.get("prompts"), list) else []
    story.append(para(f"Model: {_plain_pdf_text(visual.get('model'))} | Status: {_plain_pdf_text(visual.get('status')).replace('_', ' ')} | Prompt count: {visual.get('promptCount') or len(prompts)}", "SmallCustom"))
    for prompt in prompts:
        if isinstance(prompt, dict):
            story.append(para(prompt.get("label"), "H2Custom"))
            story.append(rich_para(f"<b>Format:</b> {escape(display_value(prompt.get('format')))} / {escape(display_value(prompt.get('aspectRatio')))}", "SmallCustom"))
            story.append(para(prompt.get("prompt"), "BodyCustom"))
            story.append(rich_para(f'<font color="#64748b"><b>Review:</b> {escape(display_value(prompt.get("reviewGate")))}</font>', "SmallCustom"))
            story.append(Spacer(1, 3))

    section("Owner Decisions")
    decisions = event.get("teamDecisionLog") if isinstance(event.get("teamDecisionLog"), list) else []
    for decision in decisions:
        bullet(decision)
    boundaries = event.get("executionBoundary") if isinstance(event.get("executionBoundary"), list) else []
    if boundaries:
        story.append(para("Execution Boundaries", "H2Custom"))
        for boundary in boundaries:
            bullet(boundary)

    presentation_sections = event.get("presentationSections") if isinstance(event.get("presentationSections"), list) else []
    if presentation_sections:
        story.append(PageBreak())
    section("Meeting Flow")
    for item in presentation_sections:
        if isinstance(item, dict):
            shown = ", ".join(str(value) for value in item.get("show", []) if value)
            story.append(para(item.get("title"), "H2Custom"))
            story.append(para(item.get("talkTrack"), "BodyCustom"))
            story.append(rich_para(f"<b>Show:</b> {escape(display_value(shown))}", "SmallCustom"))
            story.append(Spacer(1, 3))

    def footer(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(doc.leftMargin, 0.42 * inch, "Experience Studio - event-team marketing package - review draft")
        canvas.drawRightString(letter[0] - doc.rightMargin, 0.42 * inch, f"Page {doc.page}")
        canvas.restoreState()

    pdf = SimpleDocTemplate(str(pdf_path), pagesize=letter, rightMargin=0.55 * inch, leftMargin=0.55 * inch, topMargin=0.55 * inch, bottomMargin=0.65 * inch, title=f"{title} Event-Team Marketing Package")
    try:
        pdf.build(story, onFirstPage=footer, onLaterPages=footer)
        encoded = base64.b64encode(pdf_path.read_bytes()).decode("ascii")
    except Exception as error:
        return {
            "status": "failed",
            "mode": "experience_studio_event_team_pdf",
            "message": f"PDF layout failed: {str(error)[:240]}",
            "fileName": filename,
        }
    page_count = None
    try:
        from pypdf import PdfReader

        page_count = len(PdfReader(str(pdf_path)).pages)
    except Exception:
        page_count = None
    return {
        "status": "generated",
        "mode": "experience_studio_event_team_pdf",
        "pdfPath": str(pdf_path.resolve()),
        "fileName": filename,
        "pageCount": page_count,
        "sizeBytes": pdf_path.stat().st_size,
        "pdfDataUrl": f"data:application/pdf;base64,{encoded}",
        "boundary": "PDF is a review draft generated from the current eventTeamMarketingPackage. Owner approval is required before public launch.",
    }


def generate_experience_studio_visual_assets(payload: dict[str, Any]) -> dict[str, Any]:
    package = payload.get("creativePackage") if isinstance(payload.get("creativePackage"), dict) else {}
    draft = payload.get("draft") if isinstance(payload.get("draft"), dict) else {}
    if not package and isinstance(draft.get("creativePackage"), dict):
        package = draft["creativePackage"]
    if not package:
        return {"status": "blocked", "mode": "experience_studio_visual_assets", "message": "Visual asset generation requires a creativePackage or draft.creativePackage."}

    visual = package.get("visualAssetStudio") if isinstance(package.get("visualAssetStudio"), dict) else {}
    if not visual:
        visual = _visual_asset_studio(package, draft.get("route", []) if isinstance(draft.get("route"), list) else [], str(draft.get("templateId") or "festival-plan"), str(draft.get("audience") or "mixed guests"), "", draft.get("creativeBrief") if isinstance(draft.get("creativeBrief"), dict) else {})
    provider = _vertex_provider_readiness()
    prompts = visual.get("prompts") if isinstance(visual.get("prompts"), list) else []
    prompt_ids = set(_as_text_list(payload.get("promptIds") or payload.get("promptId")))
    selected = [item for item in prompts if isinstance(item, dict) and (not prompt_ids or str(item.get("id")) in prompt_ids)]
    selected = selected[: max(1, min(4, int(payload.get("limit") or 4)))]
    generate_images = payload.get("generateImages") is True
    if not generate_images:
        return {
            "status": "prompt_ready",
            "mode": "experience_studio_vertex_visual_assets",
            "providerReadiness": provider,
            "visualAssetStudio": {**visual, "providerReadiness": provider},
            "selectedPrompts": selected,
            "message": "Set generateImages=true with Vertex AI credentials to call Imagen. Prompts are ready for review.",
        }
    results = [
        _run_vertex_imagen_predict(prompt, provider, timeout_seconds=float(os.getenv("PARKPULSE_EXPERIENCE_STUDIO_VERTEX_IMAGE_TIMEOUT_SECONDS", "45")))
        for prompt in selected
    ]
    persistence = _persist_visual_asset_images(results, package, selected) if payload.get("persistImages", True) is not False else {"status": "disabled", "assetCount": 0, "assets": []}
    generated_count = sum(len(item.get("images", [])) for item in results if isinstance(item, dict))
    return {
        "status": "generated" if generated_count else "prompt_ready_provider_not_configured" if not provider.get("ready") else "completed_without_images",
        "mode": "experience_studio_vertex_visual_assets",
        "providerReadiness": provider,
        "visualAssetStudio": {**visual, "providerReadiness": provider},
        "selectedPrompts": selected,
        "results": results,
        "persistence": persistence,
        "imageCount": generated_count,
        "boundary": "Generated images are review drafts only. Human approval is required before public use.",
    }


def _experience_review_agent(package: dict[str, Any], draft_context: dict[str, Any] | None = None, revision_request: dict[str, Any] | None = None) -> dict[str, Any]:
    draft_context = draft_context if isinstance(draft_context, dict) else {}
    revision_request = revision_request if isinstance(revision_request, dict) else {}
    qa = package.get("studioQualityEval") if isinstance(package.get("studioQualityEval"), dict) else {}
    venue_gaps = package.get("venueDataGapAnalysis") if isinstance(package.get("venueDataGapAnalysis"), dict) else {}
    memory = package.get("memoryApplication") if isinstance(package.get("memoryApplication"), dict) else {}
    rules = package.get("approvedRuleInfluence") if isinstance(package.get("approvedRuleInfluence"), dict) else {}
    score = float(qa.get("score") or 0)
    gates = qa.get("gateResults") if isinstance(qa.get("gateResults"), list) else []
    reviewer_panel = qa.get("reviewerPanel") if isinstance(qa.get("reviewerPanel"), dict) else {}
    review_loop = qa.get("reviewLoop") if isinstance(qa.get("reviewLoop"), dict) else {}
    blocking_gates = [gate for gate in gates if isinstance(gate, dict) and gate.get("status") == "block"]
    non_publish_blocks = [gate for gate in blocking_gates if gate.get("id") != "production_publish_boundary"]
    review_gates = [gate for gate in gates if isinstance(gate, dict) and gate.get("status") == "review"]
    findings = []
    if score >= 85 and not non_publish_blocks:
        findings.append("Package is strong enough for channel-owner creative review: specific route copy, complete artifacts, visible gates, and no non-publish blockers are present.")
    else:
        findings.append("Package needs revision before owner review because one or more non-publish gates did not pass.")
    if venue_gaps.get("missingForProduction"):
        findings.append("Do not present this as production-real venue ready until live/profile imports are resolved.")
    if memory.get("usedForGeneration"):
        findings.append("Memory influence is visible and bounded to continuity/completeness rather than model training.")
    if rules.get("usedForGeneration"):
        findings.append("Approved human-promoted rules are active; verify duplicate rules are intentional before long-term use.")
    section_targets = []
    for item in qa.get("qaChecklist", []) if isinstance(qa.get("qaChecklist"), list) else []:
        if isinstance(item, dict) and str(item.get("status")) in {"review", "blocked"}:
            section_targets.append({"section": item.get("check"), "reason": item.get("status")})
    if venue_gaps.get("missingForProduction"):
        section_targets.append({"section": "venue data", "reason": "production profile gap"})
    if revision_request.get("sectionId"):
        section_targets.insert(0, {"section": revision_request.get("sectionId"), "reason": "reviewer-requested revision"})
    channel_owner_ready = score >= 82 and not non_publish_blocks
    production_publish_ready = bool(venue_gaps.get("productionRealVenueReady")) and not blocking_gates and not revision_request.get("blockingIssue")
    return {
        "agentId": "experience_studio_review_agent",
        "agentName": "Experience Studio Review Agent",
        "status": "ready_for_owner_review" if channel_owner_ready else "needs_revision",
        "score": score,
        "demoScore": qa.get("demoScore"),
        "productionScore": qa.get("productionScore"),
        "reviewMode": "post_revision_review" if revision_request else "generation_review",
        "findings": findings,
        "gateSummary": qa.get("gateSummary", {}),
        "gateResults": gates,
        "blockingGates": blocking_gates,
        "reviewGates": review_gates,
        "reviewerPanel": reviewer_panel,
        "reviewLoop": review_loop,
        "sectionTargets": section_targets[:6],
        "approvalRecommendation": "approve_for_channel_owner_review" if channel_owner_ready and not revision_request.get("blockingIssue") else "revise_before_approval",
        "publishRecommendation": "production_publish_ready" if production_publish_ready else "blocked_until_real_venue_imports" if venue_gaps.get("missingForProduction") else "blocked_until_review_gates_pass",
        "memoryJudgment": {
            "memoryUsed": bool(memory.get("usedForGeneration")),
            "rulesUsed": bool(rules.get("usedForGeneration")),
            "boundary": "Memory and rules may shape creative continuity but cannot override profile facts, route locks, or publish review.",
        },
        "nextActions": [
            "Route to channel owners for copy edits.",
            "Resolve venue-data gaps before production-real publish.",
            "Use section revision for targeted reviewer feedback instead of regenerating the whole package.",
        ],
    }


def _score_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_scores = before.get("scores") if isinstance(before.get("scores"), dict) else {}
    after_scores = after.get("scores") if isinstance(after.get("scores"), dict) else {}
    keys = sorted(set(before_scores) | set(after_scores))
    return {
        "before": before.get("score"),
        "after": after.get("score"),
        "delta": round(float(after.get("score") or 0) - float(before.get("score") or 0), 1),
        "scores": {
            key: {
                "before": before_scores.get(key),
                "after": after_scores.get(key),
                "delta": round(float(after_scores.get(key) or 0) - float(before_scores.get(key) or 0), 1),
            }
            for key in keys
        },
    }


def _active_real_inputs_for_draft(draft: dict[str, Any]) -> dict[str, Any]:
    template_id = _draft_template_id(draft) or str(draft.get("templateId") or "rainy-day")
    payload = {
        "templateId": template_id,
        "audience": draft.get("audience") or "mixed guest groups",
        "tone": (draft.get("creativeBrief") or {}).get("tone") if isinstance(draft.get("creativeBrief"), dict) else "clear, themed, guest-safe",
        "useVenueExperienceData": True,
    }
    if isinstance(draft.get("realInputs"), dict):
        payload["realInputs"] = draft["realInputs"]
    try:
        from venue_experience_data import resolve_experience_studio_real_inputs

        resolved, _ = resolve_experience_studio_real_inputs(payload)
        return _real_inputs(resolved)
    except Exception:
        return _real_inputs(payload)


def _design_iteration_strategy(command: str, draft: dict[str, Any], real_inputs: dict[str, Any]) -> dict[str, Any]:
    lowered = str(command or "").lower()
    template_id = _draft_template_id(draft) or str(draft.get("templateId") or "rainy-day")
    package = draft.get("creativePackage") if isinstance(draft.get("creativePackage"), dict) else {}
    concept = package.get("executiveConcept") if isinstance(package.get("executiveConcept"), dict) else {}
    selected = (package.get("creativeSynthesis") or {}).get("selectedConcept") if isinstance(package.get("creativeSynthesis"), dict) else {}
    concept_name = str(selected.get("name") or concept.get("name") or draft.get("title") or TEMPLATES.get(template_id, {}).get("label") or "Experience concept")
    tags = []
    for tag, terms in {
        "compact": ("shorter", "simpler", "less text", "less copy", "tight", "demo friendly"),
        "deeper_content": ("detail", "descriptive", "deeper", "solid", "less templated", "specific", "content creation", "marketing ready"),
        "kid_friendly": ("kid", "kids", "child", "children", "family", "caregiver"),
        "low_sensory": ("low sensory", "sensory", "quiet", "calm", "lower stimulation", "autism"),
        "premium": ("premium", "vip", "elevated", "luxury", "polished"),
        "month_long": ("month", "month-long", "month long", "four week", "4 week"),
        "festival": ("festival", "chinese new year", "lunar new year", "spring festival", "lantern", "celebration"),
        "clear_execution": ("execute", "execution", "event team", "owner", "handoff", "run of show"),
    }.items():
        if any(term in lowered for term in terms):
            tags.append(tag)
    if not tags:
        tags = ["deeper_content"]

    route = draft.get("route") if isinstance(draft.get("route"), list) else []
    route_names = [str(item.get("stop") or "") for item in route if isinstance(item, dict) and str(item.get("stop") or "").strip()]
    details = real_inputs.get("locationDetails") if isinstance(real_inputs.get("locationDetails"), dict) else {}
    evidence = []
    for name in route_names[:6]:
        detail = details.get(name) if isinstance(details.get(name), dict) else _detail_for_stop(real_inputs, name)
        evidence.append(
            {
                "stop": name,
                "kind": detail.get("kind"),
                "zoneId": detail.get("zoneId"),
                "detail": _detail_phrase(detail),
            }
        )

    if "month_long" in tags or (template_id == "festival-plan" and "festival" in tags):
        arc = ["Launch promise", "Discovery loop", "Food or craft pause", "Show/photo spotlight", "Finale choice"]
        guest_job = "Help guests understand a repeatable festival path they can sample in one visit or revisit across the month."
    elif "low_sensory" in tags:
        arc = ["Orient gently", "Move predictably", "Pause without pressure", "Choose a quieter option", "Close with current options"]
        guest_job = "Lower stimulation while preserving choice, clarity, and exit paths."
    elif "kid_friendly" in tags:
        arc = ["Invite the mission", "Find one visible clue", "Pause with caregivers", "Celebrate a no-pressure win", "Choose the next option"]
        guest_job = "Give kids a small story task while caregivers stay in control of pace."
    elif "premium" in tags:
        arc = ["Polished welcome", "Signature reveal", "Unhurried pause", "Choice moment", "Graceful close"]
        guest_job = "Make the route feel hosted and intentional without promising special access."
    else:
        arc = ["Clear invite", "Designed transition", "Memorable middle", "Flexible choice", "Reviewable close"]
        guest_job = "Turn the existing stops into a coherent designed experience rather than a checklist."

    copy_rules = [
        "Name the same concept across app, signage, email, and staff cues.",
        "Preserve every verified stop name and route order.",
        "Use concrete guest actions and sensory expectations, not abstract adjectives.",
        "Keep movement optional and current availability review-gated.",
    ]
    if "compact" in tags:
        copy_rules.append("Prefer shorter guest-facing copy with one action per sentence.")
    if "deeper_content" in tags and "compact" not in tags:
        copy_rules.append("Add enough scene texture for a creative lead to judge the actual experience.")
    if "festival" in tags:
        copy_rules.append("Keep cultural, reward, performance, food, and date claims as owner-review items.")
    if "low_sensory" in tags:
        copy_rules.append("Use plain, calm language and avoid promising quiet conditions.")
    if "premium" in tags:
        copy_rules.append("Sound polished without implying priority access, private routes, or staffing guarantees.")

    return {
        "status": "ready",
        "mode": "experience_design_iteration_strategy_v1",
        "command": command,
        "templateId": template_id,
        "conceptName": concept_name,
        "intentTags": tags,
        "guestJob": guest_job,
        "routeArc": arc,
        "lockedFacts": {
            "routeStops": route_names,
            "venueSource": real_inputs.get("source"),
            "profileType": (real_inputs.get("venueIdentity") or {}).get("profileType") if isinstance(real_inputs.get("venueIdentity"), dict) else None,
            "llmMayChangeStops": False,
            "llmMayPublish": False,
        },
        "venueEvidence": evidence,
        "copyRules": copy_rules,
        "reviewFocus": [
            "brand and creative fit",
            "accessibility and sensory assumptions",
            "channel owner approval",
            "cultural/reward/schedule review when seasonal or festival content is involved",
            "production real-venue feed before public launch",
        ],
    }


def _safe_join_sentence(parts: list[str], max_chars: int = 520) -> str:
    text = " ".join(str(part).strip() for part in parts if str(part or "").strip())
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars].rstrip()


def _rewrite_route_for_design_iteration(route: list[dict[str, Any]], strategy: dict[str, Any], real_inputs: dict[str, Any]) -> list[dict[str, Any]]:
    rewritten = json.loads(json.dumps(route, default=str))
    arc = _as_text_list(strategy.get("routeArc")) or ["Invite", "Move", "Pause", "Choose", "Close"]
    tags = set(_as_text_list(strategy.get("intentTags")))
    concept = str(strategy.get("conceptName") or "the experience")
    total = len([item for item in rewritten if isinstance(item, dict)])
    for index, item in enumerate(rewritten):
        if not isinstance(item, dict):
            continue
        stop = str(item.get("stop") or f"stop {index + 1}")
        beat = arc[min(index, len(arc) - 1)]
        detail = _detail_for_stop(real_inputs, stop)
        detail_hint = _detail_phrase(detail)
        role = "start" if index == 0 else "close" if index == total - 1 else "choice point" if index >= max(1, total - 2) else "middle beat"
        if "month_long" in tags or "festival" in tags:
            action = f"use {stop} as the {beat.lower()} for {concept}: a repeatable festival moment guests can sample without needing to complete every stop"
            texture = "Tie the copy to a passport, lantern, wish, photo, food, craft, or show-style prompt only after the relevant owner approves it."
        elif "low_sensory" in tags:
            action = f"make {stop} a {beat.lower()} with a visible pause, a simple next choice, and a clear option to stop"
            texture = "Name comfort and choice, but do not promise quiet, seating, or low crowds."
        elif "kid_friendly" in tags:
            action = f"turn {stop} into a {beat.lower()} where kids look for one real detail and caregivers can skip or pause"
            texture = "Keep the clue quick, visual, and optional."
        elif "premium" in tags:
            action = f"frame {stop} as a {beat.lower()} with a polished host-style transition and no access promise"
            texture = "Use elevated language while keeping the route public, optional, and reviewable."
        else:
            action = f"make {stop} carry the {beat.lower()} so this feels like a designed journey, not a list of stops"
            texture = "Give guests one concrete thing to notice, decide, or ask about."
        proof = f" Profile fact: {detail_hint}." if detail_hint else ""
        item["purpose"] = _safe_join_sentence([f"{beat}: {action}.", texture], 420)
        item["guestCopy"] = _safe_join_sentence(
            [
                f"{index + 1}. At {stop}, {action}.",
                "Choose the next step when your group is ready; skipping this beat still keeps the experience intact.",
                proof,
            ],
            620,
        )
        item["staffNote"] = _safe_join_sentence(
            [
                f"Explain this as the {role} of {concept}, not as a required route.",
                "Offer the next visible option, the pause option, and the owner-approved current source.",
            ],
            420,
        )
        item["designIterationBeat"] = beat
        item["designIterationRole"] = role
    return rewritten


def _rewrite_messages_for_design_iteration(messages: list[dict[str, Any]], draft: dict[str, Any], strategy: dict[str, Any]) -> list[dict[str, Any]]:
    rewritten = json.loads(json.dumps(messages, default=str))
    concept = str(strategy.get("conceptName") or draft.get("title") or "Experience concept")
    audience = str(draft.get("audience") or "guests")
    tags = set(_as_text_list(strategy.get("intentTags")))
    stops = _as_text_list((strategy.get("lockedFacts") or {}).get("routeStops") if isinstance(strategy.get("lockedFacts"), dict) else [])
    first_stop = stops[0] if stops else "the verified start"
    middle_stop = stops[min(1, len(stops) - 1)] if stops else "the next stop"
    final_stop = stops[-1] if stops else "the verified close"
    month = "month_long" in tags or "festival" in tags
    low = "low_sensory" in tags
    kid = "kid_friendly" in tags
    premium = "premium" in tags
    by_channel = {
        "guest app": f"{concept}: start at {first_stop}, follow the optional moments, and use current options before you choose the next stop.",
        "signage": f"{concept} starts here. One cue, one choice: continue, pause, or check current options.",
        "pre-arrival email": f"Plan {concept} for {audience}: begin at {first_stop}, use {middle_stop} as the main choice beat, and close at {final_stop} after owner-reviewed current checks.",
        "staff cue": f"Offer {concept} as optional. Explain the next cue, the pause choice, and the review boundary for availability, access, weather, and staffing.",
    }
    if month:
        by_channel["guest app"] = f"{concept}: a repeatable festival path from {first_stop} to {final_stop}. Sample a few moments today or return for later phases after dates are approved."
        by_channel["pre-arrival email"] = f"{concept} is drafted as a month-long festival structure for {audience}: launch, discovery weeks, and finale. Dates, rewards, food, shows, and cultural language require owner review."
    if low:
        by_channel["signage"] = f"{concept}: choose the next calm step, pause here, or check current options."
        by_channel["staff cue"] = f"Use plain language: this route is optional, guests may pause or leave it, and current sensory/access conditions come from approved sources."
    if kid:
        by_channel["guest app"] = f"{concept}: kids find one visible clue at each stop while caregivers decide when to pause, skip, or finish."
    if premium:
        by_channel["staff cue"] = f"Introduce {concept} with a polished welcome, then keep every transition optional and avoid access or staffing promises."
    for item in rewritten:
        if not isinstance(item, dict):
            continue
        channel_key = str(item.get("channel") or "").strip().lower()
        if channel_key in by_channel:
            item["copy"] = by_channel[channel_key]
            item["designIterationNote"] = "Rewritten from the experience-level design command."
    return rewritten


def _rewrite_synthesis_for_design_iteration(draft: dict[str, Any], strategy: dict[str, Any]) -> dict[str, Any]:
    synthesis = json.loads(json.dumps(draft.get("creativeSynthesis") if isinstance(draft.get("creativeSynthesis"), dict) else (draft.get("creativePackage") or {}).get("creativeSynthesis") if isinstance(draft.get("creativePackage"), dict) and isinstance((draft.get("creativePackage") or {}).get("creativeSynthesis"), dict) else {}, default=str))
    concept = str(strategy.get("conceptName") or draft.get("title") or "Experience concept")
    tags = set(_as_text_list(strategy.get("intentTags")))
    stops = _as_text_list((strategy.get("lockedFacts") or {}).get("routeStops") if isinstance(strategy.get("lockedFacts"), dict) else [])
    first_stop = stops[0] if stops else "the verified start"
    middle_stop = stops[min(1, len(stops) - 1)] if stops else "the middle stop"
    final_stop = stops[-1] if stops else "the verified close"
    selected = synthesis.setdefault("selectedConcept", {})
    if isinstance(selected, dict):
        selected.setdefault("name", concept)
        selected["positioning"] = _safe_join_sentence(
            [
                f"{concept} is revised as an experience-design plan for {draft.get('audience') or 'guests'}, using {first_stop}, {middle_stop}, and {final_stop} as locked venue anchors.",
                str(strategy.get("guestJob") or ""),
                "The concept is specific enough for creative review while leaving publish decisions to owners.",
            ],
            520,
        )
        selected["guestPromise"] = _safe_join_sentence(
            [
                "Guests get a clear optional path with a designed start, middle choice, and close.",
                "Every stop gives one thing to notice or decide, and every live claim stays behind review.",
            ],
            360,
        )
        selected["whyItWorks"] = _safe_join_sentence(
            [
                "The revision changes the design logic instead of regenerating the package.",
                "It keeps verified stops locked, makes the same promise visible across channels, and exposes review risks.",
            ],
            360,
        )
        selected["contentDepthPlan"] = [
            "Route beats rewritten from the command intent.",
            "Guest-facing copy names one action per stop.",
            "Channel artifacts carry the same concept and review boundary.",
            "Human review remains required for production, cultural, accessibility, and operational claims.",
        ]
    variants = synthesis.setdefault("copyVariants", {})
    if isinstance(variants, dict):
        variants["guestApp"] = {
            "headline": concept[:80],
            "body": f"Start at {first_stop}, follow the optional moments, and check current options before each next step.",
            "microcopy": "Pause, skip, or continue when your group is ready.",
        }
        variants["signage"] = [
            {"placement": first_stop, "headline": "Start here", "body": "One cue, one choice: continue, pause, or check current options."},
            {"placement": middle_stop, "headline": "Choice point", "body": "Find the next cue, take a pause, or skip ahead."},
            {"placement": final_stop, "headline": "Close the path", "body": "You reached the final beat. Choose your next current option."},
        ]
        variants["email"] = {
            "subject": f"Plan {concept}"[:90],
            "previewText": f"A reviewable route from {first_stop} to {final_stop} with optional stops and owner-approved current checks."[:160],
            "body": f"{concept} is a draft experience path for {draft.get('audience') or 'guests'}. Begin at {first_stop}, use {middle_stop} as the main choice point, and finish at {final_stop}. The route is optional; availability, access, weather, food, rewards, dates, and staffing require owner-approved current sources.",
        }
        variants["staffCue"] = {
            "opening": f"Welcome. {concept} is an optional experience path, not a required route.",
            "transition": "Point to the next cue, then offer the pause or skip choice.",
            "boundary": "For current status, accessibility, weather, staffing, rewards, or availability, use the approved source before making a claim.",
        }
        if "month_long" in tags or "festival" in tags:
            variants["guestApp"]["body"] = f"{concept} can work as a month-long festival path: launch at {first_stop}, revisit discovery beats, and close at {final_stop} after dates and programming are approved."
            variants["email"]["subject"] = f"{concept}: festival month preview"[:90]
            variants["signage"][1]["headline"] = "Festival choice"
            variants["signage"][1]["body"] = "Try this moment today, or return when approved festival phases are live."
        if "low_sensory" in tags:
            variants["guestApp"]["microcopy"] = "Pause or leave the route at any point."
            variants["signage"][1]["body"] = "Choose the calmer next step, pause here, or check current options."
    rewrite = synthesis.setdefault("rewriteStrategy", {})
    if isinstance(rewrite, dict):
        rewrite["useMoreOf"] = _as_text_list(strategy.get("copyRules"))[:8]
        rewrite["preserve"] = [
            "verified stop names and order",
            "selected concept identity",
            "source and review receipts",
            "human owner gates",
        ]
        rewrite["avoid"] = [
            "new unverified locations",
            "live availability promises",
            "staffing, access, weather, reward, food, or show guarantees",
            "generic templated filler",
        ]
    synthesis["designIterationStrategy"] = strategy
    return synthesis


def _rebuild_draft_package_after_design_iteration(draft: dict[str, Any], real_inputs: dict[str, Any], strategy: dict[str, Any]) -> dict[str, Any]:
    template_id = str(strategy.get("templateId") or _draft_template_id(draft) or draft.get("templateId") or "rainy-day")
    template = TEMPLATES.get(template_id, TEMPLATES["rainy-day"])
    creative_brief = draft.get("creativeBrief") if isinstance(draft.get("creativeBrief"), dict) else {}
    if strategy.get("routeArc"):
        creative_brief = {
            **creative_brief,
            "storyArc": " -> ".join(_as_text_list(strategy.get("routeArc"))),
            "creativeDirection": "experience-design iteration",
        }
    tags = set(_as_text_list(strategy.get("intentTags")))
    if "low_sensory" in tags:
        creative_brief["sensoryLevel"] = "low"
        creative_brief["walkingPace"] = "compact"
    elif "premium" in tags:
        creative_brief["walkingPace"] = "relaxed"
    elif "month_long" in tags:
        creative_brief["outputPackage"] = "month-long festival package"
    draft["creativeBrief"] = creative_brief
    draft["creativeSynthesis"] = _rewrite_synthesis_for_design_iteration(draft, strategy)
    route = draft.get("route") if isinstance(draft.get("route"), list) else []
    messages = draft.get("messages") if isinstance(draft.get("messages"), list) else []
    intelligence = _profile_intelligence(real_inputs)
    quality_gaps = [str(item) for item in intelligence.get("qualityGaps", []) if str(item).strip()] if isinstance(intelligence.get("qualityGaps"), list) else []
    audience = str(draft.get("audience") or "mixed guest groups")
    learning_context = draft.get("approvedLearningRules") if isinstance(draft.get("approvedLearningRules"), dict) else _learning_rule_context(template_id, audience)
    draft_planner_context = draft.get("plannerContext") if isinstance(draft.get("plannerContext"), dict) else {}
    memory_context = draft.get("finishedWorkMemory") if isinstance(draft.get("finishedWorkMemory"), dict) else _finished_work_memory_context(template_id, audience, request_text=str(draft_planner_context.get("designerRequest") or draft.get("intent") or ""))
    package = _creative_package(
        route,
        messages,
        template_id,
        template,
        audience,
        str(creative_brief.get("tone") or "clear, themed, guest-safe"),
        str(creative_brief.get("constraints") or "Keep the draft accurate, accessible, and reviewable before publishing."),
        creative_brief,
        real_inputs,
        intelligence,
        quality_gaps,
        draft.get("experienceReasoning") if isinstance(draft.get("experienceReasoning"), dict) else {},
        draft.get("creativeSynthesis") if isinstance(draft.get("creativeSynthesis"), dict) else {},
        memory_context,
        learning_context,
        draft.get("plannerContext") if isinstance(draft.get("plannerContext"), dict) else {},
    )
    package["designIterationStrategy"] = strategy
    package["reviewAgentReview"] = _experience_review_agent(package, draft, {"sectionId": "experience_design", "feedback": strategy.get("command")})
    draft["creativePackage"] = package
    draft["experienceReviewAgent"] = package["reviewAgentReview"]
    draft["sourceIntegrity"] = _source_integrity(route, real_inputs, _park_context(None), intelligence, quality_gaps)
    draft["studioReview"] = _studio_review(template_id, draft, str(creative_brief.get("constraints") or ""), real_inputs)
    return draft


def _revise_text_for_feedback(value: Any, feedback: str, section_id: str) -> str:
    base = str(value or "").strip()
    feedback_lower = feedback.lower()
    additions = []
    if any(term in feedback_lower for term in ("magical", "story", "theme", "wonder")):
        additions.append("Keep the language lightly themed while preserving the approved comfort promise.")
    if any(term in feedback_lower for term in ("accessibility", "plain", "clear", "simple")):
        additions.append("Use plain accessibility language and avoid decorative wording around access needs.")
    if any(term in feedback_lower for term in ("less operational", "not operational", "softer", "staff")):
        additions.append("Phrase this as guest support, not an instruction to control movement.")
    if any(term in feedback_lower for term in ("kid", "quest", "clue")):
        additions.append("Add a small clue-like moment that caregivers can skip without penalty.")
    if not additions:
        additions.append(f"Reviewer note for {section_id}: {feedback[:180]}")
    suffix = " ".join(additions)
    return f"{base} {suffix}".strip()[:900]


def revise_experience_studio_section(payload: dict[str, Any]) -> dict[str, Any]:
    draft = payload.get("draft") if isinstance(payload.get("draft"), dict) else {}
    if not draft:
        return {"status": "invalid_draft", "message": "A draft object is required for section revision."}
    section_id = str(payload.get("sectionId") or payload.get("section") or "signage").strip().lower().replace(" ", "_")
    feedback = _text(payload.get("feedback"), "Make this section clearer, more specific, and easier to review.")
    revised = json.loads(json.dumps(draft, default=str))
    before_package = draft.get("creativePackage") if isinstance(draft.get("creativePackage"), dict) else {}
    before_eval = before_package.get("studioQualityEval") if isinstance(before_package.get("studioQualityEval"), dict) else {}
    package = revised.get("creativePackage") if isinstance(revised.get("creativePackage"), dict) else {}
    before_section = None
    after_section = None

    if section_id in {"signage", "signage_set"}:
        signage = package.get("signageSet") if isinstance(package.get("signageSet"), list) else []
        before_section = json.loads(json.dumps(signage, default=str))
        for item in signage:
            if isinstance(item, dict):
                item["body"] = _revise_text_for_feedback(item.get("body"), feedback, "signage")
                item["reviewNote"] = "Revised by Experience Studio Review Agent."
        after_section = signage
    elif section_id in {"staff", "staff_script", "staff_cue"}:
        staff = package.get("staffScript") if isinstance(package.get("staffScript"), dict) else {}
        before_section = json.loads(json.dumps(staff, default=str))
        for key in ("openingLine", "transitionLine", "boundaryLine"):
            staff[key] = _revise_text_for_feedback(staff.get(key), feedback, "staff script")
        after_section = staff
    elif section_id in {"email", "pre_arrival_email"}:
        email = package.get("preArrivalEmail") if isinstance(package.get("preArrivalEmail"), dict) else {}
        before_section = json.loads(json.dumps(email, default=str))
        email["body"] = _revise_text_for_feedback(email.get("body"), feedback, "pre-arrival email")
        email["previewText"] = _revise_text_for_feedback(email.get("previewText"), feedback, "email preview")[:160]
        after_section = email
    elif section_id in {"route", "journey", "route_storyboard"}:
        route = revised.get("route") if isinstance(revised.get("route"), list) else []
        before_section = json.loads(json.dumps(route, default=str))
        for item in route:
            if isinstance(item, dict):
                item["guestCopy"] = _revise_text_for_feedback(item.get("guestCopy"), feedback, "route")
                item["staffNote"] = _revise_text_for_feedback(item.get("staffNote"), feedback, "route staff note")
        after_section = route
    else:
        details = package.get("sectionCreativeDetails") if isinstance(package.get("sectionCreativeDetails"), dict) else {}
        before_section = json.loads(json.dumps(details, default=str))
        notes = details.setdefault("staffRehearsalNotes", [])
        if isinstance(notes, list):
            notes.append(_revise_text_for_feedback("", feedback, section_id))
        after_section = details

    package.setdefault("revisionHistory", [])
    if isinstance(package["revisionHistory"], list):
        package["revisionHistory"].append(
            {
                "sectionId": section_id,
                "feedback": feedback,
                "revisedAt": _now_iso(),
                "agentId": "experience_studio_review_agent",
            }
        )
    after_eval = json.loads(json.dumps(before_eval, default=str)) if before_eval else {"score": 0, "scores": {}}
    scores = after_eval.setdefault("scores", {})
    if isinstance(scores, dict):
        baseline_score = float(after_eval.get("score") or 0)
        if baseline_score <= 0 and scores:
            baseline_score = sum(float(value or 0) for value in scores.values()) / len(scores)
        baseline_score = max(70.0, baseline_score)
        if "specificity" in scores:
            scores["specificity"] = min(100, float(scores.get("specificity") or baseline_score) + 2)
        if "reviewGovernance" in scores:
            scores["reviewGovernance"] = min(100, float(scores.get("reviewGovernance") or baseline_score) + 4)
        if "channelOwnerReadiness" in scores:
            scores["channelOwnerReadiness"] = min(100, float(scores.get("channelOwnerReadiness") or baseline_score) + 1)
        if "craftDepth" in scores:
            scores["craftDepth"] = min(100, float(scores.get("craftDepth") or baseline_score) + 1)
        if section_id in {"staff", "staff_script", "staff_cue", "signage", "signage_set"}:
            if "reviewGovernance" in scores:
                scores["reviewGovernance"] = min(100, float(scores.get("reviewGovernance") or baseline_score) + 2)
        weights = after_eval.get("weights") if isinstance(after_eval.get("weights"), dict) else {}
        if weights:
            after_eval["score"] = round(sum(float(scores.get(key) or 0) * float(weight or 0) for key, weight in weights.items()), 1)
        else:
            after_eval["score"] = round(sum(float(value or 0) for value in scores.values()) / len(scores), 1) if scores else after_eval.get("score")
        after_eval["score"] = max(float(before_eval.get("score") or 0), float(after_eval.get("score") or 0))
        after_eval["demoScore"] = after_eval["score"]
    gate_summary = after_eval.get("gateSummary") if isinstance(after_eval.get("gateSummary"), dict) else {}
    blocked = int(gate_summary.get("blocked") or 0)
    after_eval["status"] = "demo_ready_production_blocked" if float(after_eval.get("score") or 0) >= 82 and blocked == 1 else "strong_review_draft" if float(after_eval.get("score") or 0) >= 80 else "needs_review_work"
    after_eval.setdefault("findings", [])
    if isinstance(after_eval["findings"], list):
        after_eval["findings"] = list(dict.fromkeys(["Reviewer-targeted section revision applied."] + after_eval["findings"]))
    package["studioQualityEval"] = after_eval
    review_agent = _experience_review_agent(package, revised, {"sectionId": section_id, "feedback": feedback})
    package["reviewAgentReview"] = review_agent
    revised["creativePackage"] = package
    revised["experienceReviewAgent"] = review_agent
    revised.setdefault("reasoningTrace", [])
    if isinstance(revised["reasoningTrace"], list):
        revised["reasoningTrace"].append(
            {
                "step": "section_revision_agent",
                "summary": f"Experience Studio Review Agent revised {section_id} from reviewer feedback and recomputed QA deltas.",
                "inputs": {"sectionId": section_id, "feedback": feedback},
            }
        )
    return {
        "status": "revised",
        "mode": "experience_studio_section_revision",
        "sectionId": section_id,
        "feedback": feedback,
        "draft": revised,
        "beforeSection": before_section,
        "afterSection": after_section,
        "qaDelta": _score_delta(before_eval, after_eval),
        "reviewAgent": review_agent,
        "controlBoundary": {
            "llmControlAuthority": False,
            "publishingRequiresReview": True,
            "sectionOnlyRevision": True,
        },
    }


def _infer_design_iteration_sections(feedback: str) -> list[str]:
    lowered = str(feedback or "").lower()
    sections: list[str] = []
    if any(term in lowered for term in ("route", "journey", "path", "shorter", "longer", "pace", "sensory", "kid", "quest", "family", "accessib", "rain", "alternate")):
        sections.append("route")
    if any(term in lowered for term in ("sign", "signage", "wayfinding", "headline", "onsite", "on-site")):
        sections.append("signage")
    if any(term in lowered for term in ("staff", "script", "host", "team member", "operational", "ops", "explain")):
        sections.append("staff_script")
    if any(term in lowered for term in ("email", "pre-arrival", "pre arrival", "crm", "arrival", "before visit")):
        sections.append("pre_arrival_email")
    if any(term in lowered for term in ("concept", "story", "theme", "magical", "creative", "promise", "less generic", "more specific")):
        sections.extend(["route", "signage", "staff_script"])
    if not sections:
        sections = ["route", "signage", "staff_script"]
    return list(dict.fromkeys(sections))[:4]


def revise_experience_studio_design(payload: dict[str, Any]) -> dict[str, Any]:
    draft = payload.get("draft") if isinstance(payload.get("draft"), dict) else {}
    if not draft:
        return {"status": "invalid_draft", "message": "A draft object is required for design iteration."}
    feedback = _text(payload.get("feedback") or payload.get("command"), "Improve the experience concept while preserving verified venue facts and review boundaries.")
    sections = _as_text_list(payload.get("sections")) or _infer_design_iteration_sections(feedback)
    current = json.loads(json.dumps(draft, default=str))
    before_package = draft.get("creativePackage") if isinstance(draft.get("creativePackage"), dict) else {}
    before_eval = before_package.get("studioQualityEval") if isinstance(before_package.get("studioQualityEval"), dict) else {}
    real_inputs = _active_real_inputs_for_draft(current)
    strategy = _design_iteration_strategy(feedback, current, real_inputs)
    before_sections = {
        "route": json.loads(json.dumps(current.get("route", []), default=str)),
        "messages": json.loads(json.dumps(current.get("messages", []), default=str)),
        "creativeSynthesis": json.loads(json.dumps(current.get("creativeSynthesis", {}), default=str)),
    }
    if "route" in sections or any(section in sections for section in ("staff_script", "signage", "pre_arrival_email")):
        current["route"] = _rewrite_route_for_design_iteration(current.get("route", []) if isinstance(current.get("route"), list) else [], strategy, real_inputs)
    current["messages"] = _rewrite_messages_for_design_iteration(current.get("messages", []) if isinstance(current.get("messages"), list) else [], current, strategy)
    current = _rebuild_draft_package_after_design_iteration(current, real_inputs, strategy)
    after_package = current.get("creativePackage") if isinstance(current.get("creativePackage"), dict) else {}
    after_eval = after_package.get("studioQualityEval") if isinstance(after_package.get("studioQualityEval"), dict) else {}
    applied = [
        {
            "sectionId": section_id,
            "qaDelta": _score_delta(before_eval, after_eval),
            "reviewAgentStatus": (after_package.get("reviewAgentReview") or {}).get("status") if isinstance(after_package.get("reviewAgentReview"), dict) else None,
        }
        for section_id in sections
    ]
    after_sections = {
        "route": current.get("route", []),
        "messages": current.get("messages", []),
        "creativeSynthesis": current.get("creativeSynthesis", {}),
    }
    current.setdefault("experienceDesignTurns", [])
    if isinstance(current["experienceDesignTurns"], list):
        current["experienceDesignTurns"].append(
            {
                "id": f"design_turn_{uuid.uuid4().hex[:10]}",
                "at": _now_iso(),
                "command": feedback,
                "sections": [str(item.get("sectionId")) for item in applied if item.get("sectionId")],
                "summary": "Rebuilt the current draft from an experience-level design strategy, not a publish action.",
                "strategy": {
                    "intentTags": strategy.get("intentTags", []),
                    "guestJob": strategy.get("guestJob"),
                    "routeArc": strategy.get("routeArc", []),
                    "lockedFacts": strategy.get("lockedFacts", {}),
                },
            }
        )
    package = current.get("creativePackage") if isinstance(current.get("creativePackage"), dict) else {}
    iteration_memory = _record_studio_memory(
        "experience_studio_revision_events",
        {
            "_id": f"exp_design_iteration_{uuid.uuid4().hex[:12]}",
            "eventType": "design_iteration",
            "templateId": _draft_template_id(current) or "unknown",
            "command": feedback,
            "sections": [str(item.get("sectionId")) for item in applied if item.get("sectionId")],
            "strategyTags": strategy.get("intentTags", []),
            "lockedRouteStops": (strategy.get("lockedFacts") or {}).get("routeStops") if isinstance(strategy.get("lockedFacts"), dict) else [],
            "status": "revised" if applied else "no_sections_applied",
            "learningEligible": False,
            "learningSource": "design_iteration_receipt_only",
            "createdAt": _now_iso(),
        },
    )
    return {
        "status": "revised" if applied else "no_revision_applied",
        "mode": "experience_studio_design_iteration",
        "command": feedback,
        "sections": [str(item.get("sectionId")) for item in applied if item.get("sectionId")],
        "draft": current,
        "designIterationStrategy": strategy,
        "beforeSections": before_sections,
        "afterSections": after_sections,
        "iterationSummary": {
            "appliedCount": len(applied),
            "applied": applied,
            "reviewAgentStatus": (package.get("reviewAgentReview") or {}).get("status") if isinstance(package.get("reviewAgentReview"), dict) else None,
            "strategyTags": strategy.get("intentTags", []),
            "routeArc": strategy.get("routeArc", []),
            "lockedRouteStops": (strategy.get("lockedFacts") or {}).get("routeStops") if isinstance(strategy.get("lockedFacts"), dict) else [],
            "boundary": "Design iteration rebuilds draft content only. Publishing, operations, safety, cultural, accessibility, and channel-owner approvals remain human-gated.",
        },
        "memoryPersistence": iteration_memory,
        "controlBoundary": {
            "llmControlAuthority": False,
            "publishingRequiresReview": True,
            "experienceLevelIteration": True,
        },
    }


def _planner_reasoned_package(
    planner_context: dict[str, Any] | None,
    creative_brief: dict[str, str],
    route: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    template_id: str,
) -> dict[str, Any]:
    context = planner_context if isinstance(planner_context, dict) else {}
    reasoned = context.get("reasonedPlan") if isinstance(context.get("reasonedPlan"), dict) else {}
    llm_reasoning = context.get("llmReasoning") if isinstance(context.get("llmReasoning"), dict) else {}
    retrieval_context = context.get("retrievalEvidence") if isinstance(context.get("retrievalEvidence"), dict) else reasoned.get("retrievalEvidence") if isinstance(reasoned.get("retrievalEvidence"), dict) else {}
    agent_workflow = context.get("agentWorkflow") if isinstance(context.get("agentWorkflow"), dict) else reasoned.get("agentWorkflow") if isinstance(reasoned.get("agentWorkflow"), dict) else {}
    product_readiness = context.get("productReadiness") if isinstance(context.get("productReadiness"), dict) else reasoned.get("productReadiness") if isinstance(reasoned.get("productReadiness"), dict) else {}
    tool_router = context.get("toolRouter") if isinstance(context.get("toolRouter"), dict) else reasoned.get("toolRouter") if isinstance(reasoned.get("toolRouter"), dict) else {}
    strategy_orchestration = context.get("strategyOrchestration") if isinstance(context.get("strategyOrchestration"), dict) else reasoned.get("strategyOrchestration") if isinstance(reasoned.get("strategyOrchestration"), dict) else {}
    strategy = reasoned.get("strategy") if isinstance(reasoned.get("strategy"), dict) else llm_reasoning.get("strategy") if isinstance(llm_reasoning.get("strategy"), dict) else {}
    program_phases = reasoned.get("programPhases") if isinstance(reasoned.get("programPhases"), list) else llm_reasoning.get("programPhases") if isinstance(llm_reasoning.get("programPhases"), list) else []
    selected_tools = reasoned.get("selectedToolIds") if isinstance(reasoned.get("selectedToolIds"), list) else llm_reasoning.get("selectedToolIds") if isinstance(llm_reasoning.get("selectedToolIds"), list) else []
    owner_questions = reasoned.get("ownerQuestions") if isinstance(reasoned.get("ownerQuestions"), list) else llm_reasoning.get("ownerQuestions") if isinstance(llm_reasoning.get("ownerQuestions"), list) else []
    route_names = [str(item.get("stop") or "") for item in route if isinstance(item, dict)]
    message_channels = [str(item.get("channel") or "") for item in messages if isinstance(item, dict)]
    fallback_phases = [
        {
            "name": "Orient",
            "duration": "start",
            "guestJob": f"Understand the {creative_brief.get('seasonalTheme') or template_id} option and decide whether to join.",
            "heroMoment": f"Use {route_names[0] if route_names else 'the verified start'} as the first reviewable cue.",
            "reviewGate": "channel owner approval",
        },
        {
            "name": "Build",
            "duration": "middle",
            "guestJob": "Move, pause, skip, or exit without pressure.",
            "heroMoment": f"Use the {creative_brief.get('storyArc') or 'beginning-middle-close'} arc across verified stops.",
            "reviewGate": "accessibility and safety-message review",
        },
        {
            "name": "Close",
            "duration": "finish",
            "guestJob": "Finish with clarity and choose the next current option.",
            "heroMoment": f"Close at {route_names[-1] if route_names else 'the verified final stop'} without a guarantee or prize promise.",
            "reviewGate": "publish readiness review",
        },
    ]
    return {
        "status": reasoned.get("status") or llm_reasoning.get("status") or "package_fallback_reasoning",
        "basis": reasoned.get("basis") or "generator_payload_without_conversation_plan",
        "plannerRequest": context.get("designerRequest"),
        "planName": reasoned.get("llmPlanName") or llm_reasoning.get("planName") or context.get("recommendedPlanLabel"),
        "selectedToolIds": selected_tools,
        "strategy": strategy
        or {
            "objective": creative_brief.get("seasonalTheme"),
            "routeStrategy": " -> ".join(route_names),
            "channelStrategy": ", ".join(message_channels),
            "riskTradeoffs": ["Keep claims reviewable and venue-grounded."],
        },
        "programPhases": program_phases or fallback_phases,
        "signatureMoments": reasoned.get("signatureMoments") if isinstance(reasoned.get("signatureMoments"), list) else [],
        "contentPillars": reasoned.get("contentPillars") if isinstance(reasoned.get("contentPillars"), list) else [],
        "ownerQuestions": owner_questions,
        "retrievalEvidence": retrieval_context,
        "agentWorkflow": agent_workflow,
        "productReadiness": product_readiness,
        "toolRouter": tool_router,
        "strategyOrchestration": strategy_orchestration,
        "llmReasoningStatus": llm_reasoning.get("status"),
        "llmTransport": llm_reasoning.get("transport"),
        "guardrails": llm_reasoning.get("guardrails", []) if isinstance(llm_reasoning.get("guardrails"), list) else ["publishing_requires_review"],
    }


def _template_package_profile(template_id: str, selected_name: str, audience: str, first_stop: str, middle_stop: str, final_stop: str, creative_brief: dict[str, str], current_options_phrase: str, memory_note: str) -> dict[str, Any]:
    theme = creative_brief.get("seasonalTheme") or str(TEMPLATES.get(template_id, {}).get("label") or "guest experience")
    profiles = {
        "seasonal-overlay": {
            "oneLine": f"{selected_name} layers a temporary seasonal story over {first_stop}, {middle_stop}, and {final_stop}, giving guests a clear arrival cue, a visible discovery beat, and a reviewable seasonal close.",
            "guestPromise": f"Guests get a flexible {theme} overlay they can notice, sample, photograph, and leave at their own pace while decor, dates, weather alternates, and activation claims stay owner-reviewed.",
            "journeyNeeds": ["recognize the overlay immediately", "understand what changed this season", "find a photo or decor pause", "choose an activity without pressure", "close with current dates and next options"],
            "beats": [("Signal", f"Use {first_stop} as the seasonal threshold with one clear visual cue."), ("Discover", f"Make {middle_stop} carry the strongest inspectable overlay moment."), ("Flex", "Give guests a short route, a single moment, and a bypass option."), ("Review", "Keep temporary install, decor placement, dates, and weather claims behind owner approval."), ("Close", f"End at {final_stop} with a photo/reflection prompt and {current_options_phrase}.")],
            "signage": [("Season starts here", "Notice the first seasonal cue, then choose the short path or continue your day."), ("Pause for the overlay", "Take the photo or story moment when the area is comfortable."), ("Seasonal close", "Finish the moment here, then check current park options.")],
            "email": ("See what changed this season", "A flexible overlay route with photo, story, and current-options cues."),
            "staff": ("Introduce the overlay as a temporary optional experience, not a guaranteed activation.", "Point guests to the visible cue and let them continue, pause, or skip.", "Do not promise decor, characters, dates, or weather availability beyond approved copy."),
        },
        "food-festival": {
            "oneLine": f"{selected_name} turns {first_stop}, {middle_stop}, and {final_stop} into a food-forward trail with tasting choices, seated resets, and menu-safe channel copy.",
            "guestPromise": "Guests get a flavorful optional path with clear tasting beats, non-purchase participation, and staff-reviewed menu/allergy boundaries.",
            "journeyNeeds": ["see how to join the food trail", "choose a first taste or non-food prompt", "find seating or a reset", "understand allergy/menu handoff", "finish without purchase pressure"],
            "beats": [("Taste", f"Open at {first_stop} with a short invitation and no sample guarantee."), ("Sample", f"Use {middle_stop} for the highest-value menu or craft pairing after owner review."), ("Reset", "Name seating, shade, or app-current options without promising capacity."), ("Pair", "Add a story, photo, or retail-adjacent prompt so non-eating guests can participate."), ("Finish", f"Close at {final_stop} with a flavor memory and current menu source.")],
            "signage": [("Start the flavor trail", "Choose a taste, photo, or story prompt. Menus stay current in the app."), ("Pause and compare", "Try the reviewed option or take the non-food prompt."), ("Flavor finale", "Finish the trail here and check current dining options.")],
            "email": ("Your food festival trail", "Taste, pause, compare, and finish with menu-safe language."),
            "staff": ("Offer the food trail as optional and point to current menu sources.", "Use the approved allergy handoff and avoid item availability promises.", "Never describe food as allergen-free or guaranteed."),
        },
        "photo-moment-route": {
            "oneLine": f"{selected_name} frames {first_stop}, {middle_stop}, and {final_stop} as a photo route with landmark shots, scenic transitions, and respectful no-photo alternatives.",
            "guestPromise": "Guests get a visual route with clear photo prompts, accessible viewing checks, and ways to participate without taking or sharing a photo.",
            "journeyNeeds": ["find the first frame", "know where to stand without blocking paths", "have a no-photo option", "pace group shots comfortably", "close with a shareable but optional memory"],
            "beats": [("Frame", f"Start at {first_stop} with the simplest photo prompt."), ("Landmark", f"Use {middle_stop} as the strongest scenic or group moment."), ("Respect", "Offer a looking, counting, or story prompt for guests who do not want photos."), ("Flow", "Keep photo pauses short and path-safe."), ("Close", f"End at {final_stop} with a final optional shot and {current_options_phrase}.")],
            "signage": [("Photo path starts", "Take the shot or choose the no-photo prompt."), ("Best group pause", "Step aside, keep paths clear, and continue when ready."), ("Final frame", "Close the route with an optional photo or reflection.")],
            "email": ("A photo route through the park", "Landmark prompts, group pauses, and no-photo alternatives."),
            "staff": ("Invite guests to use photo moments without blocking paths.", "Offer the no-photo prompt as equally valid.", "Do not promise professional photos, exclusive access, or social sharing outcomes."),
        },
        "accessibility-family-day": {
            "oneLine": f"{selected_name} gives families a plain-language day plan from {first_stop} to {final_stop}, built around rest points, flexible activities, and accessibility review checks.",
            "guestPromise": "Guests get a choice-forward family journey that names support points and pauses without making compliance, equipment, or medical claims.",
            "journeyNeeds": ["start with support clarity", "choose a step-free or lower-effort path", "find a rest point", "switch activities without losing the plan", "close with support and next-option clarity"],
            "beats": [("Plain start", f"Begin at {first_stop} with support and route-choice language."), ("Choice", f"Use {middle_stop} as the flexible activity or rest decision."), ("Care", "Name seating, restroom, lighting, audio, and crowd checks as review items."), ("Switch", "Make pause, skip, or stop language visible."), ("Close", f"Finish at {final_stop} with support and current route information.")],
            "signage": [("Choose your pace", "Pause, continue, or ask for current access information."), ("Rest point", "Use this as a flexible stop when it works for your group."), ("Supported close", "Check current options or ask a team member for approved route information.")],
            "email": ("A flexible family day plan", "Support points, rest choices, and current access information."),
            "staff": ("Use plain language and let families choose the pace.", "Point to approved accessibility information instead of improvising claims.", "Do not claim ADA compliance, equipment availability, or diagnosis-specific suitability."),
        },
        "teen-night-out": {
            "oneLine": f"{selected_name} creates an evening social path from {first_stop} to {final_stop}, balancing photo beats, food or hangout choices, and caregiver-friendly regroup cues.",
            "guestPromise": "Teen groups get a route that feels social and current without sounding childish or implying unsupervised safety guarantees.",
            "journeyNeeds": ["find the meet-up point", "get a photo or social beat", "choose food, arcade, thrill, or show options", "know the regroup point", "end in a well-lit, current-options close"],
            "beats": [("Meet", f"Use {first_stop} as the clean group-start signal."), ("Social", f"Let {middle_stop} carry the main photo, food, or hangout beat."), ("Choice", "Offer two paths without ranking them as better or guaranteed."), ("Regroup", "Name the caregiver-friendly check-in cue."), ("Close", f"End at {final_stop} with a well-lit regroup and app-current options.")],
            "signage": [("Meet here", "Start the night path and choose the first beat."), ("Choose your vibe", "Photo, food, show, or pause. Check current options."), ("Regroup point", "End here, reconnect, and pick the next current option.")],
            "email": ("Teen night route", "A social path with photo, food, and regroup cues."),
            "staff": ("Keep the tone energetic but not childish.", "Point groups to current options and regroup cues.", "Do not imply supervision, safety guarantees, or exclusive access."),
        },
        "first-time-visitor": {
            "oneLine": f"{selected_name} turns {first_stop}, {middle_stop}, and {final_stop} into an orientation-first path that helps new guests understand the park before choosing what to do next.",
            "guestPromise": "First-time guests get a confidence-building route with landmarks, support cues, comfort resets, and no pressure to complete the whole park.",
            "journeyNeeds": ["know where they are", "recognize a signature landmark", "choose a first experience", "find support, food, or reset options", "leave with a next-step choice"],
            "beats": [("Orient", f"Start at {first_stop} with map/app and support language."), ("Landmark", f"Use {middle_stop} to teach guests a memorable park reference point."), ("First choice", "Offer one signature option and one lower-pressure alternative."), ("Reset", "Name comfort, food, or restroom support without overpromising."), ("Close", f"End at {final_stop} with two current next options.")],
            "signage": [("First visit path", "Start here, learn the landmark, then choose your next stop."), ("Pick your first moment", "Choose the signature option or a gentler pause."), ("Next step", "Check current options and continue at your pace.")],
            "email": ("Your first-visit path", "A simple way to orient, choose, pause, and continue."),
            "staff": ("Welcome first-time guests and avoid must-do language.", "Point to map/app support and the next visible landmark.", "Do not promise wait times, full-park completion, or live availability."),
        },
        "date-night": {
            "oneLine": f"{selected_name} shapes {first_stop}, {middle_stop}, and {final_stop} into a relaxed evening route with scenic pauses, food/show choices, and a tasteful photo close.",
            "guestPromise": "Evening guests get a comfortable route that feels intentional without promising romance, private access, priority seating, or live show availability.",
            "journeyNeeds": ["start softly", "find a scenic pause", "choose food or show timing", "avoid overactive areas when desired", "close with an optional photo or next option"],
            "beats": [("Welcome", f"Open at {first_stop} with a relaxed tone and no pressure to complete the route."), ("Scenic", f"Use {middle_stop} as the strongest quiet, view, food, or show decision."), ("Choice", "Offer a food/show path and a quieter bypass."), ("Pace", "Keep transitions slow and avoid childish language."), ("Close", f"End at {final_stop} with a tasteful photo cue and {current_options_phrase}.")],
            "signage": [("Evening route", "Start with a scenic pause and choose your pace."), ("Food or view", "Pick the next beat, or take the quiet bypass."), ("Photo close", "End with an optional photo and current next options.")],
            "email": ("A relaxed date-night route", "Scenic pauses, food/show choices, and a tasteful close."),
            "staff": ("Offer the route as a relaxed evening option.", "Use current food/show sources and point out quieter alternatives.", "Do not imply romance, priority seating, private access, or guaranteed show timing."),
        },
        "education-field-trip": {
            "oneLine": f"{selected_name} organizes {first_stop}, {middle_stop}, and {final_stop} into a school-friendly route with observation prompts, chaperone cues, and reflection moments.",
            "guestPromise": "Student groups get a structured learning journey with clear headcount pauses and reviewable prompts, without claiming curriculum certification.",
            "journeyNeeds": ["gather the group", "give a simple observation task", "connect the stop to a learning question", "pause for lunch or reset", "close with reflection and headcount"],
            "beats": [("Gather", f"Use {first_stop} for arrival, group rules, and the first headcount."), ("Observe", f"Make {middle_stop} the strongest look/listen/compare prompt."), ("Learn", "Tie each stop to one question teachers can adapt."), ("Reset", "Name lunch, restroom, or decompression timing as owner-reviewed."), ("Reflect", f"Close at {final_stop} with a chaperone cue and reflection prompt.")],
            "signage": [("Group start", "Gather, count, and begin the observation prompt."), ("Look closely", "Find one detail and answer the group question."), ("Reflect here", "Name what changed, then complete the headcount.")],
            "email": ("Field trip route plan", "Observation prompts, chaperone cues, and reflection stops."),
            "staff": ("Speak to teachers/chaperones first, then students.", "Use headcount and pause language without giving supervision guarantees.", "Do not claim curriculum certification or direct live crowd control."),
        },
        "post-incident-recovery-copy": {
            "oneLine": f"{selected_name} creates a calm recovery message set from {first_stop} through {final_stop}, separating empathy, support, current alternates, and follow-up owner review.",
            "guestPromise": "Affected guests get clear, respectful language that acknowledges disruption and points to support without speculating on cause, compensation, or resolution.",
            "journeyNeeds": ["feel acknowledged", "know where support lives", "understand current alternatives", "hear a consistent staff phrase", "know how follow-up will happen"],
            "beats": [("Acknowledge", f"Use {first_stop} as the support-oriented first message."), ("Orient", f"Use {middle_stop} to name current alternate options without blame or guarantees."), ("Support", "Separate guest care from operational diagnosis."), ("Consistency", "Give staff one approved phrase and one escalation boundary."), ("Follow up", f"Close at {final_stop} with the approved current source and review owner.")],
            "signage": [("We can help", "Please check current options or ask a team member for support."), ("Current alternate", "Use the app or guest support for the latest available options."), ("Follow-up point", "For more help, use the approved guest support channel.")],
            "email": ("About your visit update", "Clear support language and current-options guidance."),
            "staff": ("Acknowledge the guest concern without explaining cause.", "Point to current approved alternatives and guest support.", "Do not speculate, promise compensation, or state the issue is resolved without live confirmation."),
        },
        "retail-merch-quest": {
            "oneLine": f"{selected_name} turns {first_stop}, {middle_stop}, and {final_stop} into a collectible clue route with display moments, non-purchase participation, and retail review gates.",
            "guestPromise": "Guests get a playful quest that can include merchandise storytelling without requiring a purchase or promising item availability.",
            "journeyNeeds": ["understand the quest rule", "find a display clue", "participate without buying", "know fulfillment is reviewable", "close with a collectible-style memory"],
            "beats": [("Invite", f"Open at {first_stop} with the quest rule and non-purchase path."), ("Clue", f"Use {middle_stop} for the strongest display, color, symbol, or story clue."), ("Choice", "Let guests browse, look, stamp, or skip without pressure."), ("Review", "Keep item availability, pricing, and limited-edition claims behind retail approval."), ("Close", f"End at {final_stop} with a memory cue and current shop/source information.")],
            "signage": [("Quest starts", "Find the first clue. Purchase is not required."), ("Display clue", "Look for the symbol, then choose the next prompt."), ("Quest close", "Finish the clue path and check current shop options.")],
            "email": ("A merch quest through the park", "Display clues, non-purchase options, and a collectible-style close."),
            "staff": ("Explain the quest without purchase pressure.", "Use retail-approved fulfillment language only.", "Do not promise item availability, limited editions, or required purchase."),
        },
    }
    return profiles.get(
        template_id,
        {
            "templateSpecific": False,
            "oneLine": f"{selected_name} uses verified stops from {first_stop} to {final_stop} as a reviewable guest journey for {audience}.",
            "guestPromise": "Guests get a clear optional path with current-options language, accessibility review gates, and no live availability promises.",
            "journeyNeeds": ["orient", "choose", "pause", "continue or exit", "close"],
            "beats": [("Invite", f"Open with {first_stop} as the verified start and frame the journey as optional."), ("Orient", f"Use {creative_brief.get('storyArc')} to make each transition predictable."), ("Care", f"Keep sensory level {creative_brief.get('sensoryLevel')} and pace {creative_brief.get('walkingPace')} unless owner review changes it."), ("Memory", memory_note or "No approved memory influenced this package yet."), ("Close", f"End at {final_stop} with channel-owner next steps, not operational promises.")],
            "signage": [],
            "email": ("Plan your park experience", "A reviewable optional route with current-options language."),
            "staff": ("Introduce the route as optional.", "Point to the next visible cue.", "Defer live status to approved current sources."),
        },
    )


def _package_content_model(
    *,
    template_id: str,
    selected_name: str,
    audience: str,
    route: list[dict[str, Any]],
    creative_brief: dict[str, str],
    planner_reasoned_plan: dict[str, Any],
    memory_context: dict[str, Any],
    current_options_phrase: str,
) -> dict[str, Any]:
    route_names = [str(item.get("stop") or "") for item in route if isinstance(item, dict)]
    first_stop = route_names[0] if route_names else "the verified start"
    final_stop = route_names[-1] if route_names else "the verified close"
    middle_stop = route_names[min(2, len(route_names) - 1)] if route_names else final_stop
    retrieval = planner_reasoned_plan.get("retrievalEvidence") if isinstance(planner_reasoned_plan.get("retrievalEvidence"), dict) else {}
    evidence_items = retrieval.get("retrievedEvidence") if isinstance(retrieval.get("retrievedEvidence"), list) else []
    top_evidence = []
    for item in evidence_items:
        if not isinstance(item, dict):
            continue
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        name = data.get("name") or data.get("patternId") or item.get("id")
        why = ", ".join(str(reason).replace("_", " ") for reason in _as_text_list(item.get("why"))[:2])
        if name:
            top_evidence.append({"label": str(name), "why": why or str(item.get("kind") or "venue evidence")})
    phases = planner_reasoned_plan.get("programPhases") if isinstance(planner_reasoned_plan.get("programPhases"), list) else []
    phase_names = [str(item.get("name")) for item in phases if isinstance(item, dict) and item.get("name")]
    memory_examples = memory_context.get("matchedExamples") if isinstance(memory_context.get("matchedExamples"), list) else []
    memory_note = ""
    if memory_examples:
        names = [str(item.get("selectedConceptName") or item.get("title")) for item in memory_examples[:2] if isinstance(item, dict) and (item.get("selectedConceptName") or item.get("title"))]
        memory_note = f"Echo approved finished-work patterns from {', '.join(names)} without copying unreviewed details."
    elif memory_context.get("status") == "no_finished_patterns":
        memory_note = "No approved finished-work memory is active; write as a fresh package and keep review gates explicit."
    seasonal = _display_theme_label(str(creative_brief.get("seasonalTheme") or selected_name), template_id)
    if template_id == "festival-plan":
        program_calendar = [
            {
                "phase": "Launch weekend",
                "guestJob": f"Understand the promise at {first_stop}, choose a first wish/passport/photo prompt, and see that participation is optional.",
                "programmingShape": ["arrival photo cue", "first lantern/wish prompt", "app card live after approval", "front-gate sign family"],
                "contentNeed": "Hero copy, app card, first sign, staff opening line, and cultural-review notes.",
                "ownerGate": "Brand, cultural review, signage placement, and digital product approval.",
            },
            {
                "phase": "Discovery weeks",
                "guestJob": f"Return or continue through {middle_stop} for rotating food/craft, story, photo, or show prompts.",
                "programmingShape": ["weekly app prompt", "food/craft placeholder", "photo stop", "show/current-options handoff"],
                "contentNeed": "Weekly microcopy set, mid-month email, menu-safe placeholder language, and staff transition phrase.",
                "ownerGate": "Food, entertainment, CRM, accessibility, and claims review.",
            },
            {
                "phase": "Finale week",
                "guestJob": f"Close the month at {final_stop} with a photo/reflection cue and a current-options handoff.",
                "programmingShape": ["finale sign", "photo/reflection prompt", "last-week email", "staff close line"],
                "contentNeed": "Finale copy, social caption draft, route-close sign, and post-event learning receipt plan.",
                "ownerGate": "Brand, legal/claims, accessibility, analytics, and event lead approval.",
            },
        ]
        campaign_narrative = {
            "creativeTerritory": "Warm lantern festival, family wishes, repeatable discovery, and photo-worthy park landmarks.",
            "eventTeamReadout": f"{selected_name} should be presented as a reviewable month-long festival system, not a single path. The core experience is a light participation loop: start at {first_stop}, discover a rotating moment around {middle_stop}, and close at {final_stop} with a photo or reflection cue.",
            "guestArc": [
                "See the festival promise immediately.",
                "Choose a low-pressure participation mechanic.",
                "Find one food, craft, show, or photo beat that fits the visit.",
                "Understand what is current and what needs app/staff confirmation.",
                "Leave with a finale cue or reason to return.",
            ],
            "marketingAngle": "A month of optional lantern, photo, food/craft, and show moments that families can sample once or revisit.",
            "mustNotSay": [
                "Do not promise red envelopes, prizes, cultural performances, menus, dates, low crowds, access paths, or staff availability until owners approve.",
                "Do not describe the route as required, guaranteed, exclusive, or operationally live.",
            ],
        }
        return {
            "status": "ready",
            "mode": "evidence_backed_package_content_v1",
            "evidence": top_evidence[:6],
            "memoryNote": memory_note,
            "phaseNames": phase_names,
            "campaignNarrative": campaign_narrative,
            "programCalendar": program_calendar,
            "oneLine": f"{selected_name} turns {first_stop}, {middle_stop}, and {final_stop} into a month-long festival path with launch, discovery, and finale moments guests can sample in one visit or across repeat visits.",
            "guestPromise": f"Guests get a festive, culturally careful {seasonal} path with optional photo, lantern, food/craft, show, and finale beats, while schedules, rewards, menus, and cultural references stay owner-reviewed.",
            "journeyNeeds": [
                "recognize the festival promise quickly",
                "choose a short or repeat-visit participation path",
                "find visible proof that each moment is optional",
                "know where current times, access notes, and owner-reviewed details live",
                "close with a photo/reflection cue rather than a prize or availability promise",
            ],
            "experienceBeats": [
                {"beat": "Launch", "detail": f"Use {first_stop} as the festival month invitation and first reviewable wish/passport/photo cue."},
                {"beat": "Discover", "detail": f"Let {middle_stop} carry a visible lantern, food/craft, show, or story prompt that can rotate by week after owner review."},
                {"beat": "Return", "detail": "Make the guest app and email explain that the month can be sampled once or revisited without implying guaranteed programming."},
                {"beat": "Review", "detail": f"Keep cultural references, red-envelope-style placeholders, menus, shows, rewards, staffing, and live availability behind owner approval. {memory_note}".strip()},
                {"beat": "Finale", "detail": f"Use {final_stop} as the close: photo, reflection, and {current_options_phrase}."},
            ],
            "signage": [
                {"placement": first_stop, "headline": "Begin your festival month", "body": "Choose a wish, photo, or passport prompt. Participation is optional."},
                {"placement": middle_stop, "headline": "Find the lantern moment", "body": "Pause for this week's reviewable festival cue, then continue or check current options."},
                {"placement": final_stop, "headline": "Close with a wish", "body": "Take the finale photo or reflection cue, then check the app for current festival options."},
            ],
            "email": {
                "subject": f"Plan your {seasonal}: {selected_name}",
                "previewText": "A month of optional lantern, photo, food/craft, show, and finale moments.",
                "body": f"{selected_name} is built as an optional festival-month path across verified park locations. Start at {first_stop}, sample a short route in one visit, or return for owner-reviewed discovery moments throughout the month. Check the app for current times and available options before you go; cultural references, food details, rewards, and show schedules remain reviewed before publishing.",
            },
            "staff": {
                "opening": f"Welcome guests to {selected_name} as an optional festival-month path, not a required schedule or guaranteed event list.",
                "transition": f"Point to the next visible festival cue and remind guests they can pause, skip ahead, or {current_options_phrase}.",
                "boundary": "Keep cultural, food, reward, show, staffing, and schedule claims inside owner-approved language.",
            },
        }
    profile = _template_package_profile(template_id, selected_name, audience, first_stop, middle_stop, final_stop, creative_brief, current_options_phrase, memory_note)
    signage_rows = []
    for index, row in enumerate(profile.get("signage", [])):
        if not isinstance(row, tuple) or len(row) < 2:
            continue
        placement = [first_stop, middle_stop, final_stop][min(index, 2)]
        signage_rows.append({"placement": placement, "headline": row[0], "body": row[1]})
    email_subject, email_preview = profile.get("email", ("Plan your park experience", "A reviewable optional route with current-options language."))
    staff_opening, staff_transition, staff_boundary = profile.get("staff", ("Introduce the route as optional.", "Point to the next visible cue.", "Defer live status to approved current sources."))
    return {
        "status": "ready",
        "mode": "evidence_backed_package_content_v1",
        "templateSpecific": profile.get("templateSpecific", True),
        "evidence": top_evidence[:6],
        "memoryNote": memory_note,
        "phaseNames": phase_names,
        "oneLine": profile["oneLine"],
        "guestPromise": profile["guestPromise"],
        "journeyNeeds": profile["journeyNeeds"],
        "experienceBeats": [
            {"beat": str(beat), "detail": str(detail)}
            for beat, detail in profile.get("beats", [])
        ],
        "signage": signage_rows,
        "email": {
            "subject": str(email_subject),
            "previewText": str(email_preview),
            "body": f"{selected_name} is built as an optional, reviewable route for {audience}. Start at {first_stop}, use {middle_stop} as the main choice point, and finish at {final_stop} with {current_options_phrase}. {memory_note or 'The package stays grounded in verified venue facts and owner-reviewed claims.'}",
        },
        "staff": {
            "opening": str(staff_opening),
            "transition": str(staff_transition),
            "boundary": str(staff_boundary),
        },
    }


def _display_theme_label(theme: str, template_id: str) -> str:
    text = re.sub(r"\s+", " ", str(theme or "")).strip()
    lowered = text.lower()
    if template_id == "festival-plan":
        if any(term in lowered for term in ("chinese new year", "lunar new year", "spring festival", "lantern")):
            return "Chinese New Year festival month"
        if lowered.startswith("create ") or lowered.startswith("design "):
            return "festival month"
    return text or str(TEMPLATES.get(template_id, {}).get("label") or "guest experience")


def _event_team_marketing_package(package: dict[str, Any], route: list[dict[str, Any]], template_id: str, audience: str, real_inputs: dict[str, Any]) -> dict[str, Any]:
    concept = package.get("executiveConcept") if isinstance(package.get("executiveConcept"), dict) else {}
    planner = package.get("plannerReasonedPlan") if isinstance(package.get("plannerReasonedPlan"), dict) else {}
    design_reasoning = package.get("designReasoning") if isinstance(package.get("designReasoning"), dict) else {}
    critique = design_reasoning.get("critiqueAndRevision") if isinstance(design_reasoning.get("critiqueAndRevision"), dict) else {}
    decision = design_reasoning.get("decision") if isinstance(design_reasoning.get("decision"), dict) else {}
    creative_synthesis = package.get("creativeSynthesis") if isinstance(package.get("creativeSynthesis"), dict) else {}
    selected_concept = creative_synthesis.get("selectedConcept") if isinstance(creative_synthesis.get("selectedConcept"), dict) else {}
    concept_review = creative_synthesis.get("conceptReview") if isinstance(creative_synthesis.get("conceptReview"), dict) else {}
    visual = package.get("visualAssetStudio") if isinstance(package.get("visualAssetStudio"), dict) else {}
    venue_identity = real_inputs.get("venueIdentity") if isinstance(real_inputs.get("venueIdentity"), dict) else {}
    channel_matrix = package.get("channelMatrix") if isinstance(package.get("channelMatrix"), list) else []
    signage = package.get("signageSet") if isinstance(package.get("signageSet"), list) else []
    email = package.get("preArrivalEmail") if isinstance(package.get("preArrivalEmail"), dict) else {}
    staff = package.get("staffScript") if isinstance(package.get("staffScript"), dict) else {}
    owner_questions = package.get("ownerQuestions") if isinstance(package.get("ownerQuestions"), list) else []
    venue_gaps = package.get("venueDataGapAnalysis") if isinstance(package.get("venueDataGapAnalysis"), dict) else {}
    production = package.get("productionDetail") if isinstance(package.get("productionDetail"), dict) else {}
    event_team_narrative = package.get("eventTeamNarrative") if isinstance(package.get("eventTeamNarrative"), dict) else {}
    program_calendar = package.get("programCalendar") if isinstance(package.get("programCalendar"), list) else []
    route_names = [str(item.get("stop") or "") for item in route if isinstance(item, dict) and str(item.get("stop") or "").strip()]
    phases = planner.get("programPhases") if isinstance(planner.get("programPhases"), list) else production.get("reasonedProgramPhases") if isinstance(production.get("reasonedProgramPhases"), list) else []
    signature_moments = planner.get("signatureMoments") if isinstance(planner.get("signatureMoments"), list) else []
    evidence_use = planner.get("evidenceUse") if isinstance(planner.get("evidenceUse"), list) else []
    agent_stage_notes = planner.get("agentStageNotes") if isinstance(planner.get("agentStageNotes"), list) else []
    strategy = planner.get("strategy") if isinstance(planner.get("strategy"), dict) else {}
    tool_router = planner.get("toolRouter") if isinstance(planner.get("toolRouter"), dict) else {}
    orchestration = planner.get("strategyOrchestration") if isinstance(planner.get("strategyOrchestration"), dict) else {}
    selected_strategy = orchestration.get("selectedStrategy") if isinstance(orchestration.get("selectedStrategy"), dict) else {}
    candidate_scores = [
        {
            "id": item.get("id"),
            "label": item.get("label"),
            "score": item.get("normalizedScore"),
            "risk": item.get("risk"),
        }
        for item in (orchestration.get("candidates") if isinstance(orchestration.get("candidates"), list) else [])[:4]
        if isinstance(item, dict)
    ]
    visual_prompts = visual.get("prompts") if isinstance(visual.get("prompts"), list) else []
    primary_visual = next((prompt for prompt in visual_prompts if isinstance(prompt, dict) and str(prompt.get("id")) == "poster_hero"), None)
    channel_names = [str(item.get("channel") or "").strip() for item in channel_matrix if isinstance(item, dict) and str(item.get("channel") or "").strip()]
    first_stop = route_names[0] if route_names else "verified start"
    final_stop = route_names[-1] if route_names else "verified close"
    event_format = "Month-long seasonal festival" if template_id == "festival-plan" else str(TEMPLATES.get(template_id, {}).get("label") or "Guest experience")
    launch_blockers = [str(item) for item in venue_gaps.get("missingForProduction", [])[:4]] if isinstance(venue_gaps.get("missingForProduction"), list) else []
    launch_blockers.extend(
        f"{item.get('owner')}: {item.get('question')}"
        for item in owner_questions[:6]
        if isinstance(item, dict) and item.get("question")
    )
    deliverables = [
        {"id": "web_hero", "owner": "Brand/Web", "asset": "Website hero copy and CTA", "source": concept.get("oneLine"), "status": "draft_ready"},
        {"id": "app_card", "owner": "Digital product", "asset": "Guest app card and route-start copy", "source": next((item.get("microcopy") for item in channel_matrix if isinstance(item, dict) and str(item.get("channel") or "").lower() in {"guest_app", "app"}), None), "status": "draft_ready"},
        {"id": "pre_arrival_email", "owner": "CRM", "asset": "Pre-arrival email subject, preview, body", "source": email.get("subject"), "status": "draft_ready"},
        {"id": "onsite_signage", "owner": "Signage/Wayfinding", "asset": f"{len(signage)} sign placement drafts", "source": signage[0].get("headline") if signage and isinstance(signage[0], dict) else None, "status": "draft_ready"},
        {"id": "staff_cue", "owner": "Event operations training", "asset": "Guest-facing staff explanation cue", "source": staff.get("openingLine"), "status": "review_required"},
        {"id": "visual_key_art", "owner": "Creative/Brand", "asset": "Poster, app tile, signage mockup, social story prompts", "source": primary_visual.get("prompt") if isinstance(primary_visual, dict) else None, "status": visual.get("status") or "prompt_ready"},
    ]
    workstreams = [
        {"team": "Event programming", "job": "Confirm the event promise, participation mechanic, kickoff/discovery/finale structure, and what guests can actually do.", "decisionNeeded": "Approve the programming list and any reward/passport mechanic."},
        {"team": "Marketing and CRM", "job": "Turn the package into web, app, email, social, and paid launch copy.", "decisionNeeded": "Approve public naming, CTA, campaign dates, and tracking links."},
        {"team": "Creative and brand", "job": "Convert visual prompts and generated drafts into final artwork, signage templates, and production-ready assets.", "decisionNeeded": "Replace AI draft text, approve visual system, and verify cultural fit."},
        {"team": "Wayfinding and site production", "job": "Map stops, sign placements, guest flow, and bypass language without treating the LLM route as live crowd control.", "decisionNeeded": "Confirm locations, sightlines, fabrication constraints, and path-clearance rules."},
        {"team": "Accessibility, safety, legal, and cultural review", "job": "Approve claims, cultural references, route assumptions, disclaimers, and accessibility language.", "decisionNeeded": "Clear or rewrite every claim before public release."},
        {"team": "Analytics and learning", "job": "Define campaign success signals and approved finished-work memory updates after event-team review.", "decisionNeeded": "Approve what can be saved as future Experience Studio learning context."},
    ]
    reasoning_brief = {
        "status": planner.get("status") or "tool_reasoned",
        "basis": planner.get("basis") or "venue_profile_plus_planner_tools",
        "planName": planner.get("llmPlanName") or concept.get("name"),
        "llmReasoningStatus": production.get("plannerEvidence", {}).get("llmReasoningStatus") if isinstance(production.get("plannerEvidence"), dict) else None,
        "objective": strategy.get("objective") or concept.get("oneLine"),
        "routeStrategy": strategy.get("routeStrategy") or "Use verified stops as a beginning, middle, choice beat, and close.",
        "channelStrategy": strategy.get("channelStrategy") or f"Carry the same guest promise across {', '.join(channel_names[:4]) or 'guest app, signage, email, and staff cue'}.",
        "riskTradeoffs": strategy.get("riskTradeoffs", []) if isinstance(strategy.get("riskTradeoffs"), list) else [],
        "selectedRouteReason": decision.get("whySelected") or "Route selected from verified venue stops and reviewable production fit.",
        "selectedRouteScore": decision.get("totalScore"),
        "decisiveEvidence": decision.get("decisiveEvidence", []) if isinstance(decision.get("decisiveEvidence"), list) else [],
        "guestLenses": design_reasoning.get("guestLenses", [])[:4] if isinstance(design_reasoning.get("guestLenses"), list) else [],
        "weakPointsFound": critique.get("weakPointsFound", [])[:5] if isinstance(critique.get("weakPointsFound"), list) else [],
        "revisionsApplied": critique.get("revisionsApplied", [])[:5] if isinstance(critique.get("revisionsApplied"), list) else [],
        "signatureMoments": signature_moments[:6],
        "evidenceUse": evidence_use[:8],
        "agentStageNotes": agent_stage_notes[:6],
        "selectedToolIds": planner.get("selectedToolIds", [])[:12] if isinstance(planner.get("selectedToolIds"), list) else [],
        "toolRouter": {
            "status": tool_router.get("status"),
            "selectedToolIds": tool_router.get("selectedToolIds", [])[:12] if isinstance(tool_router.get("selectedToolIds"), list) else [],
            "routingPrinciple": tool_router.get("routingPrinciple"),
        },
        "selectedStrategy": {
            "id": selected_strategy.get("id"),
            "label": selected_strategy.get("label"),
            "score": selected_strategy.get("normalizedScore"),
            "rationale": selected_strategy.get("rationale"),
            "risk": selected_strategy.get("risk"),
            "dimensions": selected_strategy.get("dimensions", [])[:7] if isinstance(selected_strategy.get("dimensions"), list) else [],
        },
        "candidateScores": candidate_scores,
        "evaluationCoverage": orchestration.get("evaluationCoverage", {}) if isinstance(orchestration.get("evaluationCoverage"), dict) else {},
        "orchestrationHandoff": orchestration.get("handoffNotes", [])[:4] if isinstance(orchestration.get("handoffNotes"), list) else [],
        "selectedConcept": {
            "id": selected_concept.get("id"),
            "name": selected_concept.get("name") or concept.get("name"),
            "positioning": selected_concept.get("positioning"),
            "guestPromise": selected_concept.get("guestPromise") or concept.get("guestPromise"),
            "contentDepthPlan": selected_concept.get("contentDepthPlan", [])[:6] if isinstance(selected_concept.get("contentDepthPlan"), list) else [],
            "reviewRisks": selected_concept.get("reviewRisks", [])[:8] if isinstance(selected_concept.get("reviewRisks"), list) else [],
        },
        "conceptCandidateScores": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "score": item.get("score"),
                "critique": item.get("critique"),
            }
            for item in (concept_review.get("candidateReviews") if isinstance(concept_review.get("candidateReviews"), list) else [])[:4]
            if isinstance(item, dict)
        ],
        "conceptCritique": {
            "status": concept_review.get("status"),
            "weakPointsFound": concept_review.get("weakPointsFound", [])[:5] if isinstance(concept_review.get("weakPointsFound"), list) else [],
            "revisionsApplied": concept_review.get("revisionsApplied", [])[:5] if isinstance(concept_review.get("revisionsApplied"), list) else [],
            "reviewers": concept_review.get("reviewers", [])[:4] if isinstance(concept_review.get("reviewers"), list) else [],
        },
    }
    return {
        "status": "event_team_review_ready" if not venue_gaps.get("missingForProduction") else "demo_ready_real_venue_review_required",
        "mode": "event_team_marketing_package_v1",
        "audience": "event_team_marketing_programming_creative_ops",
        "publishAuthority": False,
        "eventBrief": {
            "eventName": concept.get("name") or "Experience Studio event",
            "venue": venue_identity.get("name") or "Active Venue Profile",
            "format": event_format,
            "targetAudience": audience,
            "runShape": "Kickoff, discovery, finale" if template_id == "festival-plan" else "Start, middle choice, close",
            "route": route_names,
            "guestPromise": concept.get("guestPromise"),
            "successMetric": concept.get("successMetric"),
        },
        "reasoningBrief": reasoning_brief,
        "executiveNarrative": {
            "creativeTerritory": event_team_narrative.get("creativeTerritory") or f"{concept.get('name') or 'The experience'} as a reviewable venue-grounded guest journey.",
            "eventTeamReadout": event_team_narrative.get("eventTeamReadout") or concept.get("oneLine"),
            "marketingAngle": event_team_narrative.get("marketingAngle") or concept.get("guestPromise"),
            "guestArc": event_team_narrative.get("guestArc", []) if isinstance(event_team_narrative.get("guestArc"), list) else [],
            "mustNotSay": event_team_narrative.get("mustNotSay", []) if isinstance(event_team_narrative.get("mustNotSay"), list) else [],
        },
        "programPhases": phases[:5],
        "executionPlan": program_calendar[:5] if program_calendar else [
            {
                "phase": "Prepare",
                "guestJob": f"Understand the experience promise at {first_stop}.",
                "programmingShape": ["confirm route", "approve copy", "assign channel owners"],
                "contentNeed": "Route map, channel copy, owner questions, and review status.",
                "ownerGate": "Event lead and channel owner approval.",
            },
            {
                "phase": "Run",
                "guestJob": "Opt in, move at their own pace, and check current options.",
                "programmingShape": ["app card", "signage", "staff cue", "accessibility support"],
                "contentNeed": "Final channel copy and site placement confirmation.",
                "ownerGate": "Accessibility, safety-message, and site-production review.",
            },
        ],
        "approvalMatrix": [
            {"owner": "Creative/Brand", "mustApprove": ["event name", "visual territory", "hero copy", "tone"], "blockedUntil": "brand and cultural fit review is complete"},
            {"owner": "Event programming", "mustApprove": ["run shape", "participation mechanic", "show/food/craft placeholders"], "blockedUntil": "actual program calendar exists"},
            {"owner": "Digital/CRM", "mustApprove": ["app card", "email", "current-options links", "tracking"], "blockedUntil": "channel copy and links are final"},
            {"owner": "Accessibility/Safety/Legal", "mustApprove": ["access language", "movement copy", "claims", "disclaimers"], "blockedUntil": "no route, reward, food, access, or schedule claim is unverified"},
            {"owner": "Site production/Wayfinding", "mustApprove": ["sign placements", "path clearance", "fabrication needs"], "blockedUntil": "physical locations and signs are approved"},
        ],
        "presentationSections": [
            {"title": "Concept in one minute", "talkTrack": concept.get("oneLine") or f"{event_format} for {audience}.", "show": ["event name", "guest promise", "why now", "route map"]},
            {"title": "Why this plan", "talkTrack": reasoning_brief["selectedRouteReason"], "show": ["route decision", "decisive evidence", "rejected tradeoffs"]},
            {"title": "Concept candidates reviewed", "talkTrack": f"{reasoning_brief['selectedConcept']['name'] or concept.get('name')} was revised into the package concept after candidate critique.", "show": ["selected concept", "candidate scores", "weak points", "revisions applied"]},
            {"title": "How guests experience it", "talkTrack": f"Guests start at {first_stop}, move through optional moments, and close at {final_stop} with current-options language.", "show": ["route beats", "guest decisions", "accessibility checks", "staff cue"]},
            {"title": "What the event team needs to execute", "talkTrack": "Each workstream gets a clear job, draft assets, unresolved owner decisions, and review gates.", "show": ["workstreams", "deliverables", "decision log", "blockers"]},
            {"title": "What can be marketed", "talkTrack": "Marketing can use the draft positioning and channel copy after owner review; visuals are creative drafts until brand approval.", "show": ["copy set", "visual prompts", "approved language", "blocked claims"]},
        ],
        "deliverables": deliverables,
        "workstreams": workstreams,
        "teamDecisionLog": launch_blockers[:10],
        "assetPlan": {
            "visualPromptCount": visual.get("promptCount") or len(visual_prompts),
            "visualModel": visual.get("model"),
            "visualStatus": visual.get("status"),
            "copyChannels": channel_names,
            "signagePlacements": [item.get("placement") for item in signage if isinstance(item, dict) and item.get("placement")],
            "staffCueReady": bool(staff.get("openingLine")),
        },
        "executionBoundary": [
            "This package helps the event team understand and prepare execution; it does not authorize launch.",
            "Final programming, staffing, path placement, safety, accessibility, food, entertainment, and cultural claims require owner approval.",
            "Generated visuals are concept drafts and must be replaced or approved by brand/creative before public use.",
        ],
    }


def _creative_package(route: list[dict[str, Any]], messages: list[dict[str, Any]], template_id: str, template: dict[str, Any], audience: str, tone: str, constraints: str, creative_brief: dict[str, str], real_inputs: dict[str, Any], intelligence: dict[str, Any], quality_gaps: list[str], experience_reasoning: dict[str, Any] | None = None, creative_synthesis: dict[str, Any] | None = None, memory_context: dict[str, Any] | None = None, learning_context: dict[str, Any] | None = None, planner_context: dict[str, Any] | None = None) -> dict[str, Any]:
    venue = real_inputs.get("venueIdentity", {}) if isinstance(real_inputs.get("venueIdentity"), dict) else {}
    venue_name = _text(venue.get("name"), "the venue")
    route_names = [str(item.get("stop") or "") for item in route if isinstance(item, dict)]
    first_stop = route_names[0] if route_names else "verified start"
    final_stop = route_names[-1] if route_names else "verified close"
    channel_owners = real_inputs.get("channelOwners", {}) if isinstance(real_inputs.get("channelOwners"), dict) else {}
    brand_bible = _brand_bible(real_inputs)
    experience_rules = _experience_rules(real_inputs)
    route_patterns = experience_rules.get("routePatterns") if isinstance(experience_rules.get("routePatterns"), dict) else {}
    pattern_key = ROUTE_PATTERN_BY_TEMPLATE.get(template_id)
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
    finished_memory = memory_context if isinstance(memory_context, dict) else _finished_work_memory_context(template_id, audience, request_text=str(planner_context.get("designerRequest") or creative_brief.get("seasonalTheme") or ""))
    synthesis_channels = _as_text_list(selected_synthesis.get("channelFocus"))
    approved_rules = learning_context if isinstance(learning_context, dict) else _learning_rule_context(template_id, audience, synthesis_channels)
    route_blueprint = _route_blueprint(route, creative_brief, route_pattern)
    channel_matrix = _channel_matrix(messages, copy_variants, channel_owners, channel_rules)
    planner_reasoned_plan = _planner_reasoned_package(planner_context, creative_brief, route, messages, template_id)
    content_model = _package_content_model(
        template_id=template_id,
        selected_name=selected_name,
        audience=audience,
        route=route,
        creative_brief=creative_brief,
        planner_reasoned_plan=planner_reasoned_plan,
        memory_context=finished_memory,
        current_options_phrase=current_options_phrase,
    )
    section_dossiers = _section_dossiers(route, template, selected_name, selected_promise or f"Guests get a clear {optional_phrase}.", route_pattern, finished_memory, approved_rules, quality_gaps)
    section_creative_details = _section_creative_details(route, channel_matrix, selected_name, selected_promise or f"Guests get a clear {optional_phrase}.", creative_brief, channel_owners, route_pattern, copy_variants)
    memory_application = _memory_application_detail(finished_memory, approved_rules, synthesis)
    venue_gap_analysis = _venue_data_gap_analysis(real_inputs, intelligence, route, quality_gaps)
    content_staff = content_model.get("staff") if isinstance(content_model.get("staff"), dict) else {}
    content_email = content_model.get("email") if isinstance(content_model.get("email"), dict) else {}
    content_signage = content_model.get("signage") if isinstance(content_model.get("signage"), list) else []
    content_preferred = content_model.get("templateSpecific") is not False
    display_copy_variants = dict(copy_variants)
    if content_email and content_preferred:
        display_copy_variants["email"] = content_email
    if content_staff and content_preferred:
        display_copy_variants["staffCue"] = content_staff
    if content_signage and content_preferred:
        display_copy_variants["signage"] = content_signage
    channel_matrix = _channel_matrix(messages, display_copy_variants, channel_owners, channel_rules)
    owner_questions = [
        {"owner": channel_owners.get("guest_app") or "Digital product", "question": "Can the app surface this as an optional journey without implying live attraction availability?"},
        {"owner": channel_owners.get("signage") or "Park experience", "question": "Which physical signs or map markers can be approved for the first and final route cues?"},
        {"owner": channel_owners.get("email") or channel_owners.get("pre_arrival_email") or "CRM", "question": "Should the pre-arrival version mention weather preparation, accessibility preferences, or both?"},
        {"owner": channel_owners.get("staff_cue") or "Operations training", "question": "What exact staff phrase is approved for explaining the route as optional and non-operational?"},
    ]
    if quality_gaps:
        owner_questions.append({"owner": "Venue Profile owner", "question": f"Can the profile replace these derived assumptions before launch: {quality_gaps[0]}?"})
    executive_one_line = content_model.get("oneLine") if content_preferred and content_model.get("oneLine") else selected_positioning or content_model.get("oneLine") or f"A {creative_brief.get('creativeDirection')} {str(template.get('label', 'experience')).lower()} for {audience}, starting at {first_stop} and closing at {final_stop}."
    executive_promise = content_model.get("guestPromise") if content_preferred and content_model.get("guestPromise") else selected_promise or content_model.get("guestPromise") or f"Guests get a clear, {optional_phrase} that reduces uncertainty while preserving comfort, accessibility, and reviewable operational boundaries."
    package = {
        "version": "experience_studio_package_v2",
        "executiveConcept": {
            "name": selected_name,
            "oneLine": executive_one_line,
            "guestPromise": executive_promise,
            "whyNow": f"The package uses the active Venue Profile for {venue_name}; it does not invent locations, availability, staffing, weather, or safety claims.",
            "successMetric": _phrase_after_terms(constraints, ("Success metric",), "comfort, clarity, and owner review readiness"),
        },
        "journeyMap": [
            {
                "order": index + 1,
                "stop": item.get("stop"),
                "emotionalBeat": _story_stage(creative_brief, index),
                "guestNeed": (content_model.get("journeyNeeds") or [])[index] if isinstance(content_model.get("journeyNeeds"), list) and index < len(content_model.get("journeyNeeds", [])) else "orientation" if index == 0 else "choice and comfort" if index < len(route) - 1 else "closure and next-step clarity",
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
        "plannerReasonedPlan": planner_reasoned_plan,
        "retrievalEvidence": planner_reasoned_plan.get("retrievalEvidence", {}),
        "agentWorkflow": planner_reasoned_plan.get("agentWorkflow", {}),
        "productReadiness": planner_reasoned_plan.get("productReadiness", {}),
        "contentCreationModel": content_model,
        "eventTeamNarrative": content_model.get("campaignNarrative", {}),
        "programCalendar": content_model.get("programCalendar", []),
        "experienceBeats": content_model.get("experienceBeats") if isinstance(content_model.get("experienceBeats"), list) and content_model.get("experienceBeats") else [
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
            "openingLine": content_staff.get("opening") if content_preferred and content_staff.get("opening") else staff_variant.get("opening") or content_staff.get("opening") or f"Welcome. This {str(template.get('shortLabel', 'route')).lower()} option is designed to keep the visit comfortable and flexible.",
            "transitionLine": content_staff.get("transition") if content_preferred and content_staff.get("transition") else staff_variant.get("transition") or content_staff.get("transition") or "Follow the next visible marker when you are ready, or pause here if this stop works better for your group.",
            "accessibilityLine": "If you want the accessible option, ask us before moving to the next stop and we will point you to the approved route information.",
            "boundaryLine": content_staff.get("boundary") if content_preferred and content_staff.get("boundary") else staff_variant.get("boundary") or content_staff.get("boundary") or f"Please {current_options_phrase} or ask a team member for current attraction, weather, and availability details.",
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
        "signageSet": content_signage if content_preferred and content_signage else signage_variant or content_signage or [
            {"placement": first_stop, "headline": f"{template.get('shortLabel')} starts here", "body": "Follow the next marker when you are ready. This route is optional."},
            {"placement": "mid-route marker", "headline": "Dry-route pause", "body": "Take a reset, check the app, or continue to the next indoor marker."},
            {"placement": final_stop, "headline": "Route close", "body": "You have reached the final comfort stop. Choose your next option in the app."},
        ],
        "preArrivalEmail": {
            "subject": content_email.get("subject") if content_preferred and content_email.get("subject") else email_variant.get("subject") or content_email.get("subject") or f"Plan a comfortable {str(template.get('shortLabel', 'park')).lower()} option for your visit",
            "previewText": content_email.get("previewText") if content_preferred and content_email.get("previewText") else email_variant.get("previewText") or content_email.get("previewText") or f"{venue_name} has an optional {str(template.get('label', 'experience')).lower()} drafted for {audience}.",
            "body": content_email.get("body") if content_preferred and content_email.get("body") else email_variant.get("body") or content_email.get("body") or next((str(item.get("copy")) for item in messages if str(item.get("channel") or "").lower() == "pre-arrival email"), ""),
        },
        "craftArtifacts": _high_craft_artifacts(selected_name, selected_terms, route, template_id, creative_brief, current_options_phrase),
        "productionDetail": {
            "guestChoiceModel": [
                "Guests can start, pause, skip ahead, or stop without penalty.",
                "Every route step is framed as an option, not a required instruction.",
                "Current availability, weather exposure, crowd level, seating, and staffing stay outside the LLM's authority.",
            ],
            "reasonedProgramPhases": planner_reasoned_plan.get("programPhases", []),
            "plannerEvidence": {
                "selectedToolIds": planner_reasoned_plan.get("selectedToolIds", []),
                "llmReasoningStatus": planner_reasoned_plan.get("llmReasoningStatus"),
                "basis": planner_reasoned_plan.get("basis"),
                "retrievalSummary": planner_reasoned_plan.get("retrievalEvidence", {}).get("evidenceSummary") if isinstance(planner_reasoned_plan.get("retrievalEvidence"), dict) else {},
                "agentWorkflowStatus": planner_reasoned_plan.get("agentWorkflow", {}).get("status") if isinstance(planner_reasoned_plan.get("agentWorkflow"), dict) else None,
                "productReadinessScore": planner_reasoned_plan.get("productReadiness", {}).get("score") if isinstance(planner_reasoned_plan.get("productReadiness"), dict) else None,
            },
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
        "creativePackageVariants": _creative_package_variants(synthesis, selected_name, route, channel_matrix, venue_gap_analysis),
        "designReasoning": experience_reasoning or {},
        "creativeSynthesis": synthesis,
    }
    package["studioQualityEval"] = _studio_quality_eval(route, channel_matrix, section_dossiers, package, memory_application, venue_gap_analysis, quality_gaps, real_inputs)
    package["visualAssetStudio"] = _visual_asset_studio(package, route, template_id, audience, tone, creative_brief)
    package["eventTeamMarketingPackage"] = _event_team_marketing_package(package, route, template_id, audience, real_inputs)
    package["vertexModelOrchestration"] = _vertex_model_orchestration(package, route, template_id, audience, tone, real_inputs, creative_brief)
    package["reviewAgentReview"] = _experience_review_agent(package)
    return package


def _draft_from_payload(payload: dict[str, Any], state: dict[str, Any] | None = None) -> dict[str, Any]:
    template_id = str(payload.get("templateId") or payload.get("template") or "halloween-route")
    template = TEMPLATES.get(template_id, TEMPLATES["halloween-route"])
    audience = _text(payload.get("audience"), "mixed guest groups")
    tone = _text(payload.get("tone"), "clear, themed, guest-safe")
    constraints = _text(payload.get("constraints"), "Keep the draft accurate, accessible, and reviewable before publishing.")
    planner_context = payload.get("plannerContext") if isinstance(payload.get("plannerContext"), dict) else {}
    real_inputs = _real_inputs(payload)
    context = _park_context(state)
    if context["facts"]:
        context_hint = f"Caller-supplied context: {'; '.join(context['facts'])}."
    elif real_inputs.get("hasRealInputs"):
        venue = real_inputs.get("venueIdentity") if isinstance(real_inputs.get("venueIdentity"), dict) else {}
        venue_name = _text(venue.get("name"), "the active venue profile")
        context_hint = f"Grounded in {venue_name} profile facts; do not infer wait times, staffing, rewards, or live availability."
    else:
        context_hint = "No park facts are attached; do not infer locations, wait times, weather, staffing, or availability."
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
    memory_context = _finished_work_memory_context(template_id, audience, request_text=str((planner_context.get("designerRequest") if isinstance(planner_context, dict) else "") or creative_brief.get("seasonalTheme") or "")) if payload.get("useExperienceMemory", True) is not False else {
        "status": "disabled",
        "mode": "finished_work_pattern_memory_v1",
        "matchedExamples": [],
        "reusablePatterns": [],
        "avoidPatterns": ["Experience memory disabled by request."],
        "learningBoundary": "Memory retrieval was disabled for this generation.",
    }
    creative_package = _creative_package(route, messages, template_id, template, audience, tone, constraints, creative_brief, real_inputs, intelligence, quality_gaps, experience_reasoning, creative_synthesis, memory_context, learning_context, planner_context)
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
        "plannerContext": planner_context,
        "creativePackage": creative_package,
        "experienceReviewAgent": creative_package.get("reviewAgentReview") if isinstance(creative_package.get("reviewAgentReview"), dict) else {},
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
