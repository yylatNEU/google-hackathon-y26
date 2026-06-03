from __future__ import annotations

from copy import deepcopy
from typing import Any


CUSTOMER_EMERGENCY_SCOPE_VERSION = "2026-05-31.phase1"


INCIDENT_CATEGORIES: list[dict[str, Any]] = [
    {
        "id": "medical",
        "label": "Medical or first aid",
        "description": "Guest injury, collapse, heat illness, breathing concern, or request for first aid.",
        "keywords": ["medical", "first aid", "faint", "fainted", "passed out", "collapse", "injury", "hurt", "bleeding", "chest pain", "cannot breathe", "ambulance", "dehydrated"],
        "default_owner": "Medical",
        "minimum_severity": "critical",
        "minimum_escalation": 3,
        "mandatory_questions": ["Exact location or nearest landmark", "Is anyone in immediate danger?", "Is trained staff already on scene?", "Is the emergency/service lane clear?"],
    },
    {
        "id": "fire_smoke_hazard",
        "label": "Fire, smoke, gas, or electrical hazard",
        "description": "Smoke, visible fire, gas smell, sparks, power hazard, or unsafe equipment effect.",
        "keywords": ["fire", "smoke", "gas", "sparking", "electrical", "burning", "power outage", "fog machine", "controller", "hazard"],
        "default_owner": "Safety and Maintenance",
        "minimum_severity": "critical",
        "minimum_escalation": 4,
        "mandatory_questions": ["Exact location or asset", "Is fire, smoke, gas, or sparking visible now?", "Are exits or access lanes blocked?", "Are guests moving away from the hazard?"],
    },
    {
        "id": "security_threat",
        "label": "Security threat",
        "description": "Fight, weapon concern, threat, aggressive behavior, unattended bag, or panic-producing security report.",
        "keywords": ["fight", "weapon", "threat", "security", "aggressive", "unattended bag", "suspicious bag", "panic", "violence", "assault"],
        "default_owner": "Security",
        "minimum_severity": "critical",
        "minimum_escalation": 4,
        "mandatory_questions": ["Exact location", "Is anyone in immediate danger?", "Are guests moving toward or away from the area?", "Is security already present?"],
    },
    {
        "id": "missing_person",
        "label": "Missing child or separated person",
        "description": "Lost child, missing child, separated family member, or vulnerable guest separation.",
        "keywords": ["lost child", "missing child", "missing kid", "separated child", "separated kid", "lost parent", "missing person", "separated family"],
        "default_owner": "Guest Services and Security",
        "minimum_severity": "urgent",
        "minimum_escalation": 3,
        "mandatory_questions": ["Last known location", "Time last seen", "Guardian or group is with staff now", "Do not enter names, photos, or private identifiers in chat"],
    },
    {
        "id": "ride_or_equipment_safety",
        "label": "Ride or equipment safety",
        "description": "Ride stop, restraint concern, stuck guests, sensor fault, maintenance warning, or equipment clearance issue.",
        "keywords": ["stuck on ride", "stopped on ride", "restraint", "seatbelt", "harness", "safety stop", "block zone", "sensor", "fault", "maintenance", "ride stopped"],
        "default_owner": "Ride Operations and Maintenance",
        "minimum_severity": "urgent",
        "minimum_escalation": 3,
        "mandatory_questions": ["Ride or asset name", "Whether guests are currently stuck or exposed", "Whether ride operations or maintenance is already aware", "Nearby crowd pressure"],
    },
    {
        "id": "crowd_pressure",
        "label": "Crowd pressure or blocked access",
        "description": "Crowd crush risk, pushing, blocked path, queue spillback, blocked emergency route, or evacuation-flow pressure.",
        "keywords": ["crowd crush", "crush", "pushing", "stampede", "surge", "blocked", "bottleneck", "spillback", "packed", "evacuation", "access lane"],
        "default_owner": "Crowd Control",
        "minimum_severity": "urgent",
        "minimum_escalation": 2,
        "mandatory_questions": ["Exact pressure point", "Crowd direction", "Are exits or service lanes blocked?", "Any medical, accessibility, or child-care signal nearby?"],
    },
    {
        "id": "severe_weather",
        "label": "Severe weather",
        "description": "Lightning, storm, heat, high wind, flooding, or weather shelter demand.",
        "keywords": ["lightning", "storm", "high wind", "flood", "heat", "heat index", "weather", "shelter", "rain"],
        "default_owner": "Operations Supervisor",
        "minimum_severity": "watch",
        "minimum_escalation": 1,
        "mandatory_questions": ["Guest exposure location", "Shelter capacity nearby", "Any ride or route affected", "Whether accessibility support is needed"],
    },
    {
        "id": "accessibility_support",
        "label": "Accessibility support",
        "description": "Wheelchair, mobility, sensory, service access, or other extra-care support need.",
        "keywords": ["wheelchair", "mobility", "accessibility", "accessible", "sensory", "stroller", "service animal", "assistance needed"],
        "default_owner": "Accessibility Lead",
        "minimum_severity": "watch",
        "minimum_escalation": 1,
        "mandatory_questions": ["Current location", "Destination or immediate need", "Whether path is blocked", "Whether medical support is also needed"],
    },
    {
        "id": "guest_care",
        "label": "Guest care or complaint",
        "description": "Customer frustration, refund pressure, app confusion, unfairness concern, or non-emergency support request.",
        "keywords": ["complaint", "refund", "angry", "upset", "unfair", "app wrong", "long wait", "confused", "lost"],
        "default_owner": "Guest Recovery",
        "minimum_severity": "watch",
        "minimum_escalation": 1,
        "mandatory_questions": ["Location", "What outcome the guest needs", "Whether there is a safety concern", "Avoid private payment or identity details"],
    },
]


SEVERITY_LEVELS: list[dict[str, Any]] = [
    {
        "id": "watch",
        "rank": 1,
        "meaning": "Low-confirmation or non-life-safety issue that needs verification or staff review.",
        "customer_posture": "Acknowledge, collect location, and submit for staff review.",
    },
    {
        "id": "urgent",
        "rank": 2,
        "meaning": "Operational safety or guest-care issue that needs a time-bound staff response.",
        "customer_posture": "Collect minimum facts, notify staff, and keep public wording conservative.",
    },
    {
        "id": "critical",
        "rank": 3,
        "meaning": "Potential harm, missing person, ride safety, security, medical, fire, or blocked emergency access.",
        "customer_posture": "Show emergency-services reminder, alert command center, and require human supervision.",
    },
    {
        "id": "life_safety",
        "rank": 4,
        "meaning": "Immediate danger or external emergency-services threshold.",
        "customer_posture": "Tell the customer to call 911 now if safe, notify staff, and stop autonomous response.",
    },
]


ESCALATION_LEVELS: list[dict[str, Any]] = [
    {"level": 0, "id": "answer_only", "owner": "Customer chatbot", "trigger": "General help with no safety signal.", "action": "Answer or route to normal support."},
    {"level": 1, "id": "staff_review", "owner": "Guest Services", "trigger": "Watch-level care, accessibility, weather, or complaint signal.", "action": "Create review case and ask one clarifying question."},
    {"level": 2, "id": "dispatch_staff", "owner": "Zone Lead", "trigger": "Urgent crowd, route, ride, weather, or guest-support issue.", "action": "Dispatch bounded worker task and keep operator informed."},
    {"level": 3, "id": "command_center", "owner": "Duty Manager", "trigger": "Critical medical, missing person, ride safety, blocked access, or uncertain high-risk signal.", "action": "Alert command center and require human decision before public messaging."},
    {"level": 4, "id": "external_emergency_threshold", "owner": "Human operator", "trigger": "Fire, smoke, violence, weapon, gas, immediate life safety, or external emergency-services need.", "action": "Display call-911 guidance and keep AI in intake/support mode only."},
]


CUSTOMER_BOT_ALLOWED_ACTIONS = [
    "collect_minimum_emergency_facts",
    "show_call_911_guidance_for_immediate_danger",
    "submit_structured_incident_to_server",
    "provide_non-diagnostic_safety_reminder",
    "send_status_update_approved_by_server",
    "handoff_to_human_operator",
]


CUSTOMER_BOT_PROHIBITED_ACTIONS = [
    "diagnose_medical_condition",
    "declare_area_safe",
    "tell_user_not_to_call_emergency_services",
    "publish_medical_or_child_identity_details",
    "order_evacuation_without_human_authority",
    "clear_or_reopen_ride_or_equipment",
    "detain_or_confront_security_subject",
    "promise_compensation_or_refund",
]


MINIMUM_INTAKE_FIELDS = [
    {"id": "incident_type", "label": "What happened", "required": True},
    {"id": "location", "label": "Location or nearest landmark", "required": True},
    {"id": "immediate_danger", "label": "Immediate danger", "required": True},
    {"id": "injury_or_access_need", "label": "Injury, medical, accessibility, or child-care need", "required": False},
    {"id": "access_blocked", "label": "Blocked exit, path, or emergency/service lane", "required": False},
    {"id": "staff_on_scene", "label": "Staff already on scene", "required": False},
    {"id": "contact_channel", "label": "Optional follow-up channel", "required": False},
]


CUSTOMER_COPY_RULES = [
    "Use short, direct language.",
    "For immediate danger, tell the customer to call 911 now if they can do so safely.",
    "Say that staff are being alerted only after the server accepts the incident.",
    "Ask at most one follow-up question at a time.",
    "Do not request child names, photos, medical details, payment data, or government IDs in chat.",
    "Do not claim an emergency has been resolved until a human operator or trusted system confirms it.",
]


def build_customer_emergency_scope() -> dict[str, Any]:
    return {
        "version": CUSTOMER_EMERGENCY_SCOPE_VERSION,
        "domain": "amusement_park_customer_emergency_intake",
        "purpose": "Phase 1 scope contract for a customer-end Gemini chatbot that reports emergencies to ParkPulse server AI.",
        "customer_bot_role": "intake_and_guidance_only",
        "server_ai_role": "classification_escalation_and_dispatch_recommendation",
        "human_authority": [
            "emergency response decisions",
            "medical/security command",
            "ride safety clearance",
            "evacuation authority",
            "public emergency messaging",
        ],
        "incident_categories": deepcopy(INCIDENT_CATEGORIES),
        "severity_levels": deepcopy(SEVERITY_LEVELS),
        "escalation_levels": deepcopy(ESCALATION_LEVELS),
        "minimum_intake_fields": deepcopy(MINIMUM_INTAKE_FIELDS),
        "allowed_customer_bot_actions": list(CUSTOMER_BOT_ALLOWED_ACTIONS),
        "prohibited_customer_bot_actions": list(CUSTOMER_BOT_PROHIBITED_ACTIONS),
        "customer_copy_rules": list(CUSTOMER_COPY_RULES),
        "default_customer_safety_banner": "If anyone is in immediate danger, call 911 now if you can do so safely. I can also alert park staff.",
        "structured_incident_contract": {
            "required": ["incident_type", "severity", "escalation_level", "location", "summary", "requires_human_review"],
            "optional": ["missing_info", "source", "reporter_contact_allowed", "customer_visible_status", "recommended_owner"],
        },
    }


def classify_customer_scope_text(text: str) -> dict[str, Any]:
    lowered = " ".join((text or "").lower().split())
    matches: list[dict[str, Any]] = []
    for category in INCIDENT_CATEGORIES:
        hit_keywords = [keyword for keyword in category["keywords"] if keyword in lowered]
        if hit_keywords:
            matches.append(
                {
                    "category_id": category["id"],
                    "label": category["label"],
                    "owner": category["default_owner"],
                    "minimum_severity": category["minimum_severity"],
                    "minimum_escalation": category["minimum_escalation"],
                    "matched_keywords": hit_keywords[:5],
                    "mandatory_questions": category["mandatory_questions"],
                }
            )

    if not matches:
        matches.append(
            {
                "category_id": "unknown",
                "label": "Unknown customer report",
                "owner": "Guest Services",
                "minimum_severity": "watch",
                "minimum_escalation": 1,
                "matched_keywords": [],
                "mandatory_questions": ["Exact location or nearest landmark", "What happened?", "Is anyone in immediate danger?"],
            }
        )

    top_match = max(matches, key=lambda item: (int(item["minimum_escalation"]), len(item["matched_keywords"])))
    escalation = int(top_match["minimum_escalation"])
    severity = "life_safety" if escalation >= 4 else str(top_match["minimum_severity"])
    return {
        "version": CUSTOMER_EMERGENCY_SCOPE_VERSION,
        "input_text": text,
        "primary_category": top_match["category_id"],
        "matched_categories": matches,
        "severity": severity,
        "escalation_level": escalation,
        "requires_human_review": escalation >= 2,
        "show_911_banner": escalation >= 3,
        "recommended_owner": top_match["owner"],
        "next_customer_question": top_match["mandatory_questions"][0],
        "prohibited_actions": list(CUSTOMER_BOT_PROHIBITED_ACTIONS),
    }
