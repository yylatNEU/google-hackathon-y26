from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RUBRIC_DIMENSIONS = [
    "empathy",
    "policy_correctness",
    "escalation_decision",
    "clarity",
    "safety_awareness",
    "de_escalation",
    "brand_tone",
]

_SESSIONS: dict[str, dict[str, Any]] = {}
_STAFF_TRAINING_SESSION_COLLECTION = "staff_training_sessions"

STAFF_ROLE_ASSIGNMENT_SCENARIOS = {
    "guest_services": ["angry_parent", "refund_request", "accessibility_accommodation", "language_barrier"],
    "ride_ops": ["ride_closure_complaint", "safety_rule_refusal", "line_cutting_conflict", "weather_evacuation_confusion"],
    "entry": ["language_barrier", "lost_child_report", "refund_request"],
    "security": ["lost_child_report", "line_cutting_conflict", "weather_evacuation_confusion"],
    "food": ["heat_exhaustion_concern", "refund_request", "line_cutting_conflict"],
}
TRAINING_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}

STAFF_TRAINING_REVIEW_DECISIONS = {"approve_shadowing", "require_retry", "hold"}

STAFF_TRAINING_AGENT_ROLES = [
    {
        "id": "context_retriever",
        "purpose": "Retrieve scenario policy, active learning versions, prior trainee outcomes, and training-gap memory before a roleplay starts.",
        "score_authority": False,
        "live_ops_authority": False,
    },
    {
        "id": "guest_simulator",
        "purpose": "Generate or select the next guest-only roleplay turn while staying inside scenario facts.",
        "score_authority": False,
        "live_ops_authority": False,
    },
    {
        "id": "deterministic_scorer",
        "purpose": "Score employee turns with the policy and safety rubric.",
        "score_authority": True,
        "live_ops_authority": False,
    },
    {
        "id": "mastery_tracker",
        "purpose": "Track open and repaired coaching gaps across turns and sessions.",
        "score_authority": False,
        "live_ops_authority": False,
    },
    {
        "id": "shadow_evaluator",
        "purpose": "Optionally comment on rubric alignment without changing the official score.",
        "score_authority": False,
        "live_ops_authority": False,
    },
]

STAFF_TRAINING_TOOL_MANIFEST = [
    {
        "id": "staff_training.retrieve_context",
        "owner_agent": "context_retriever",
        "allowed": True,
        "inputs": ["scenario_id", "trainee_name", "assignment_id"],
        "outputs": ["policy_refs", "active_learning_versions", "prior_sessions", "training_gap_patterns"],
    },
    {
        "id": "staff_training.generate_guest_turn",
        "owner_agent": "guest_simulator",
        "allowed": True,
        "inputs": ["scenario", "transcript", "retrieved_training_context", "deterministic_score_summary"],
        "outputs": ["guest_reply"],
        "constraints": ["guest voice only", "no scoring", "no live-action approval"],
    },
    {
        "id": "staff_training.score_turn",
        "owner_agent": "deterministic_scorer",
        "allowed": True,
        "inputs": ["scenario", "employee_message", "turn_count"],
        "outputs": ["turn_score", "coaching_notes"],
        "authority": "official_training_score",
    },
    {
        "id": "staff_training.update_mastery_memory",
        "owner_agent": "mastery_tracker",
        "allowed": True,
        "inputs": ["previous_mastery_tracker", "turn_score"],
        "outputs": ["open_gaps", "repaired_gaps", "mastery_level"],
    },
    {
        "id": "product_learning.create_training_gap_ticket",
        "owner_agent": "mastery_tracker",
        "allowed": True,
        "inputs": ["finished_session", "open_gaps"],
        "outputs": ["training_gap_ticket"],
        "constraints": ["training/product-learning only", "no live dispatch", "no reward label"],
    },
    {
        "id": "staff_training.shadow_eval",
        "owner_agent": "shadow_evaluator",
        "allowed": True,
        "inputs": ["scenario", "employee_message", "deterministic_score"],
        "outputs": ["alignment_comment"],
        "constraints": ["no score authority"],
    },
]

STAFF_TRAINING_BLOCKED_TOOLS = [
    "live_dispatch.execute",
    "refund.approve",
    "medical.diagnose",
    "ride_control.override",
    "reward_model.write_label",
    "model_registry.promote",
]

DEMO_TRAINEES = [
    {
        "trainee_name": "Maya Chen",
        "staff_role": "guest_services",
        "scenario_id": "lost_child_report",
        "scorecard": {"overall": 91, "dimensions": {"empathy": 4.4, "policy_correctness": 4.5, "escalation_decision": 5, "clarity": 4.5, "safety_awareness": 5, "de_escalation": 4.5, "brand_tone": 4.5}, "turn_count": 2},
        "critical_miss": False,
    },
    {
        "trainee_name": "Jon Bell",
        "staff_role": "ride_ops",
        "scenario_id": "safety_rule_refusal",
        "scorecard": {"overall": 58, "dimensions": {"empathy": 2.5, "policy_correctness": 3, "escalation_decision": 2, "clarity": 3, "safety_awareness": 2, "de_escalation": 3, "brand_tone": 3.5}, "turn_count": 2},
        "critical_miss": True,
    },
    {
        "trainee_name": "Priya Nair",
        "staff_role": "entry",
        "scenario_id": "language_barrier",
        "scorecard": {"overall": 73, "dimensions": {"empathy": 3.5, "policy_correctness": 3.5, "escalation_decision": 3, "clarity": 4, "safety_awareness": 3.5, "de_escalation": 4, "brand_tone": 4}, "turn_count": 3},
        "critical_miss": False,
    },
]

_EMPATHY_TERMS = (
    "sorry",
    "i understand",
    "understand",
    "i hear",
    "acknowledge",
    "impact",
    "waited",
    "upset",
    "do not need",
    "urgent",
    "treating",
    "frustrating",
    "worried",
    "scary",
    "help",
    "thank you",
    "stay with",
    "we will",
)
_CLARITY_TERMS = (
    "first",
    "next",
    "now",
    "please",
    "where",
    "when",
    "what",
    "who",
    "stay",
    "meet",
    "follow",
    "confirm",
    "show",
    "connect",
    "collect",
    "route",
    "current",
    "until",
    "while",
)
_DEESCALATION_TERMS = (
    "calm",
    "step",
    "safe",
    "together",
    "right now",
    "i can",
    "we can",
    "stay here",
    "work through",
    "listen",
    "confirm",
    "show",
    "connect",
    "collect",
    "review",
    "contact",
    "call",
    "bring",
    "check",
    "guide",
    "explain",
)
_RUDE_TERMS = ("calm down", "not my problem", "can't help", "deal with", "your fault", "stop yelling", "whatever")


SCENARIOS: dict[str, dict[str, Any]] = {
    "angry_parent": {
        "id": "angry_parent",
        "title": "Angry Parent At Guest Services",
        "category": "Guest Recovery",
        "difficulty": "medium",
        "guest_role": "angry parent",
        "opening_message": "This is ridiculous. My kid has been crying for twenty minutes because your staff sent us to a closed ride.",
        "context": "A parent is angry after a ride closure reroute failed. They want acknowledgement, a clear next step, and a supervisor if compensation is requested.",
        "objectives": ["Acknowledge the impact", "Confirm what happened", "Offer a concrete next step", "Escalate refund or compensation decisions"],
        "policy_keywords": [["sorry", "understand", "frustrating", "this happened"], ["ride", "closed", "what happened", "confirm", "communicated"], ["next", "option", "alternative", "open", "nearby", "guest services"], ["supervisor", "lead", "manager", "guest services"]],
        "safety_keywords": [["child", "kid", "family"], ["safe", "together", "stay"]],
        "escalation_keywords": [["supervisor", "lead", "manager", "guest services"]],
        "guest_followups": [
            "I do not want a vague apology. What are you actually going to do for us?",
            "Are you saying you cannot fix this without a manager?",
            "Fine, but I need you to be clear with my family about where we go now.",
        ],
        "prohibited_terms": ["nothing i can do", "not my problem", "read the sign"],
    },
    "lost_child_report": {
        "id": "lost_child_report",
        "title": "Lost Child Report",
        "category": "Safety",
        "difficulty": "critical",
        "guest_role": "panicked guardian",
        "opening_message": "I cannot find my six-year-old. She was next to me near the carousel and now she is gone.",
        "context": "A guardian reports a missing child. Staff must show empathy, collect key details, keep the guardian reachable, and escalate immediately to security/ops.",
        "objectives": ["Reassure without minimizing", "Collect child description and last seen location", "Keep guardian at a meeting point", "Escalate to security immediately"],
        "policy_keywords": [["sorry", "help", "right now"], ["description", "wearing", "name", "age"], ["last seen", "carousel", "location"], ["stay", "meeting", "here"], ["security", "supervisor", "operations", "radio"]],
        "safety_keywords": [["security", "radio", "operations"], ["stay", "meeting", "here"], ["description", "wearing", "age"]],
        "escalation_keywords": [["security", "radio", "operations", "supervisor"]],
        "guest_followups": [
            "Why are you asking questions? Shouldn't someone already be looking?",
            "She has a pink shirt and light-up shoes. What do I do while you call someone?",
            "Please do not make me run around the park alone.",
        ],
        "fatal_if_missing_after_turn": 1,
        "prohibited_terms": ["go look", "search yourself", "wait and see", "probably fine"],
    },
    "ride_closure_complaint": {
        "id": "ride_closure_complaint",
        "title": "Ride Closure Complaint",
        "category": "Ride Ops",
        "difficulty": "medium",
        "guest_role": "disappointed coaster fan",
        "opening_message": "We paid for tickets mostly for Dragon Coaster, and now it is closed. Nobody told us before we waited.",
        "context": "Guest complains about a closure. Staff should acknowledge, avoid unsafe reopen promises, explain available updates, and offer alternatives.",
        "objectives": ["Acknowledge wait impact", "Avoid promising reopen time", "Offer live alternatives", "Direct refund/compensation to approved channel"],
        "policy_keywords": [["sorry", "understand", "frustrating"], ["cannot promise", "no exact", "updates", "temporary", "reopen time", "until clearance"], ["alternative", "nearby", "open", "theater", "arcade"], ["guest services", "supervisor", "refund"]],
        "safety_keywords": [["cannot promise", "safety", "clearance"], ["updates", "temporary"]],
        "escalation_keywords": [["guest services", "supervisor", "lead"]],
        "guest_followups": [
            "So when exactly will it reopen?",
            "I do not want another ride. I want someone to make this right.",
            "At least tell us where to go without wasting more time.",
        ],
        "prohibited_terms": ["it will reopen", "definitely open", "definitely reopen", "ignore the closure"],
    },
    "accessibility_accommodation": {
        "id": "accessibility_accommodation",
        "title": "Accessibility Accommodation Request",
        "category": "Accessibility",
        "difficulty": "high",
        "guest_role": "guest requesting mobility accommodation",
        "opening_message": "My father cannot stand in this sun for the whole queue. We need help, but I do not want to explain his medical history in public.",
        "context": "A party requests accessibility support. Staff must preserve dignity, avoid medical probing, explain available assistance, and escalate to accessibility/guest services.",
        "objectives": ["Respect privacy", "Offer accessible route or waiting support", "Avoid asking for diagnosis", "Escalate to accessibility support"],
        "policy_keywords": [["privacy", "private", "do not need medical", "medical details", "without asking"], ["accessible", "accessibility", "mobility", "route", "seating", "shade"], ["guest services", "accessibility", "support"], ["dignity", "respect", "without asking"]],
        "safety_keywords": [["shade", "seating", "sun", "heat"], ["accessible", "mobility", "route"]],
        "escalation_keywords": [["guest services", "accessibility", "supervisor", "lead"]],
        "guest_followups": [
            "Are you going to make him prove his condition?",
            "He needs shade or a place to sit while we figure this out.",
            "Who can actually approve the accommodation?",
        ],
        "prohibited_terms": ["prove", "diagnosis", "medical records", "handicapped"],
    },
    "language_barrier": {
        "id": "language_barrier",
        "title": "Language Barrier At Entry",
        "category": "Guest Support",
        "difficulty": "medium",
        "guest_role": "confused multilingual family",
        "opening_message": "No English good. Ticket problem. Family inside? We do not understand where to go.",
        "context": "A guest has a language barrier and possible party separation. Staff should simplify, use translation resources, confirm safety, and guide one step at a time.",
        "objectives": ["Use simple language", "Offer translation support", "Confirm party status", "Give one clear next step"],
        "policy_keywords": [["translator", "translation", "language", "interpreter"], ["family", "party", "inside", "together"], ["one step", "follow", "stay", "here"], ["ticket", "entry", "guest services"]],
        "safety_keywords": [["family", "together", "inside"], ["stay", "here"]],
        "escalation_keywords": [["guest services", "lead", "translator", "interpreter"]],
        "guest_followups": [
            "Family inside. We have phone but do not understand app.",
            "Can you show us, not only say words?",
            "We are worried we are separated.",
        ],
        "prohibited_terms": ["speak english", "figure it out", "not understand you"],
    },
    "refund_request": {
        "id": "refund_request",
        "title": "Refund Request",
        "category": "Guest Recovery",
        "difficulty": "medium",
        "guest_role": "upset purchaser",
        "opening_message": "I want a refund now. The ride was closed, the food line was terrible, and this day is not what we paid for.",
        "context": "Guest requests refund. Staff should empathize, avoid unauthorized promises, gather context, and route to Guest Services or supervisor.",
        "objectives": ["Acknowledge frustration", "Avoid promising refund", "Collect issue summary", "Escalate through approved channel"],
        "policy_keywords": [["sorry", "understand", "frustrating"], ["cannot promise", "review", "policy"], ["what happened", "receipt", "ticket", "details", "collect", "issue summary"], ["guest services", "supervisor", "manager"]],
        "safety_keywords": [["calm", "safe", "help"], ["guest services", "supervisor"]],
        "escalation_keywords": [["guest services", "supervisor", "manager"]],
        "guest_followups": [
            "Do not tell me policy. Are you refunding me or not?",
            "What information do you need?",
            "Then get me someone who can make the decision.",
        ],
        "prohibited_terms": ["full refund guaranteed", "guarantee a full", "cash refund", "cash now", "nothing i can do"],
    },
    "heat_exhaustion_concern": {
        "id": "heat_exhaustion_concern",
        "title": "Heat Exhaustion Concern",
        "category": "Safety",
        "difficulty": "critical",
        "guest_role": "concerned friend",
        "opening_message": "My friend is dizzy and looks pale. We have been in the sun for an hour and she says she might faint.",
        "context": "Possible heat exhaustion. Staff must prioritize safety, move to shade if safe, call first aid/medical, and avoid medical diagnosis.",
        "objectives": ["Treat as urgent", "Call first aid or medical", "Move to shade/cooling if safe", "Avoid diagnosis or delay"],
        "policy_keywords": [["first aid", "medical", "nurse", "call"], ["shade", "cool", "water", "sit"], ["do not move", "if safe", "stay"], ["right now", "urgent"]],
        "safety_keywords": [["first aid", "medical", "nurse"], ["shade", "cool", "water"], ["faint", "dizzy", "urgent"]],
        "escalation_keywords": [["first aid", "medical", "nurse", "call", "radio"]],
        "guest_followups": [
            "Should I walk her to the front or wait here?",
            "She is embarrassed and says she is fine, but she looks worse.",
            "Please call someone now.",
        ],
        "fatal_if_missing_after_turn": 1,
        "prohibited_terms": ["walk it off", "probably fine", "wait in line", "not serious"],
    },
    "line_cutting_conflict": {
        "id": "line_cutting_conflict",
        "title": "Line-Cutting Conflict",
        "category": "Crowd Conflict",
        "difficulty": "high",
        "guest_role": "angry guest in queue",
        "opening_message": "Those people cut the entire line. If you do not do something, I am going to handle it myself.",
        "context": "Queue conflict with possible escalation. Staff should acknowledge, separate tension, avoid blame, call lead/security if needed, and keep the queue moving safely.",
        "objectives": ["Acknowledge concern", "Discourage confrontation", "Call lead/security if threat escalates", "Investigate without public blame"],
        "policy_keywords": [["understand", "frustrating", "help"], ["do not confront", "stay", "safe"], ["lead", "security", "supervisor"], ["check", "look into", "queue"]],
        "safety_keywords": [["safe", "do not confront", "stay"], ["security", "lead", "supervisor"]],
        "escalation_keywords": [["security", "lead", "supervisor"]],
        "guest_followups": [
            "So you are just letting them get away with it?",
            "I am not calming down unless someone steps in.",
            "Can you check without making this a fight?",
        ],
        "prohibited_terms": ["go confront", "fight", "push", "handle it yourself"],
    },
    "safety_rule_refusal": {
        "id": "safety_rule_refusal",
        "title": "Guest Refusing Safety Rule",
        "category": "Ride Safety",
        "difficulty": "critical",
        "guest_role": "defiant ride guest",
        "opening_message": "I am not taking off my loose backpack strap. I have ridden like this before. Just start the ride.",
        "context": "Guest refuses a ride safety rule. Staff must stay firm, explain safety requirement, avoid bargaining, and escalate to ride lead/security if refusal continues.",
        "objectives": ["State rule clearly", "Do not start ride unless compliant", "Explain safety reason", "Escalate persistent refusal"],
        "policy_keywords": [["safety", "rule", "requirement"], ["cannot start", "cannot ride", "before"], ["secure", "remove", "strap", "locker"], ["lead", "supervisor", "security"]],
        "safety_keywords": [["cannot start", "cannot ride"], ["secure", "remove", "strap"], ["safety", "rule"]],
        "escalation_keywords": [["lead", "supervisor", "security"]],
        "guest_followups": [
            "You are holding up the line over a strap?",
            "What if I just hold it down?",
            "Get your lead then, because this is absurd.",
        ],
        "fatal_if_missing_after_turn": 1,
        "prohibited_terms": ["just this once", "go ahead", "start the ride", "ignore it"],
    },
    "weather_evacuation_confusion": {
        "id": "weather_evacuation_confusion",
        "title": "Weather Evacuation Confusion",
        "category": "Weather Response",
        "difficulty": "high",
        "guest_role": "confused family during storm hold",
        "opening_message": "The alert says move to shelter, but everyone is walking different directions. We have a stroller and do not know where to go.",
        "context": "Storm shelter movement. Staff should give calm clear route, preserve accessibility, avoid panic language, and direct to assigned shelter/lead.",
        "objectives": ["Use calm evacuation language", "Give specific shelter route", "Preserve accessible/stroller route", "Escalate blocked-route or lightning risk"],
        "policy_keywords": [["shelter", "indoor", "covered"], ["follow", "route", "this way", "left", "right"], ["stroller", "accessible", "ramp"], ["lead", "staff", "weather"]],
        "safety_keywords": [["shelter", "indoor", "covered"], ["stroller", "accessible", "ramp"], ["weather", "lightning", "safe"]],
        "escalation_keywords": [["lead", "staff", "security", "operations"]],
        "guest_followups": [
            "Which shelter exactly? We cannot use stairs with the stroller.",
            "People are running and it is making my kids scared.",
            "Can someone guide us instead of pointing?",
        ],
        "prohibited_terms": ["run", "panic", "everybody evacuate now", "take the stairs"],
    },
}

NEXT_RESPONSE_TEMPLATES = {
    "angry_parent": "I am sorry your child was sent to a closed ride. I am going to confirm what happened, give you the best open nearby option now, and bring Guest Services or a supervisor into any compensation review.",
    "lost_child_report": "I am sorry. We are going to help right now. Please stay with me at this meeting point while I radio Security and Operations. What is your child's name, age, what are they wearing, and where were they last seen?",
    "ride_closure_complaint": "I am sorry you waited without a clear update. I cannot promise a reopen time until the ride is cleared, but I can show you current open alternatives and connect you with Guest Services for any refund or compensation question.",
    "accessibility_accommodation": "You do not need to explain medical details here. I can help your father get shade or seating and contact Accessibility or Guest Services to confirm the right route or accommodation.",
    "language_barrier": "I can help. Please stay here with me. I will use translation support, confirm whether your family is inside, and then show you the next ticket or Guest Services step one at a time.",
    "refund_request": "I understand why you are upset. I cannot promise a refund myself, but I can collect your ticket details and issue summary, then bring Guest Services or a supervisor into the policy review.",
    "heat_exhaustion_concern": "I am treating this as urgent. Please stay with her in the shade if it is safe, have her sit, and I am calling First Aid or medical now. Do not try to walk her across the park until they advise us.",
    "line_cutting_conflict": "I understand why that feels unfair. Please do not confront them; I need everyone to stay safe. I will check what happened and call a lead or Security if the conflict continues.",
    "safety_rule_refusal": "For safety, this ride cannot start until the loose strap is removed or secured in a locker. I can help you do that now, and if you still disagree I will call my ride lead.",
    "weather_evacuation_confusion": "Stay calm and follow me toward the covered shelter route. We will use the stroller-accessible path, and I will contact a lead if the route is blocked or weather risk changes.",
}

STAFF_TRAINING_GOLDEN_RESPONSES: dict[str, list[dict[str, Any]]] = {
    "angry_parent": [
        {"id": "angry_parent_bad", "label": "bad", "message": "Read the sign. There is nothing I can do.", "max_score": 55, "critical_miss": True},
        {"id": "angry_parent_partial", "label": "partial", "message": "Sorry. You can try another ride nearby.", "min_score": 45, "max_score": 74},
        {"id": "angry_parent_passing", "label": "passing", "message": "I am sorry this happened. I will confirm what was communicated, show nearby open options, and bring Guest Services into any compensation review.", "min_score": 75, "max_score": 89},
        {"id": "angry_parent_excellent", "label": "excellent", "message": "I am sorry your child was sent to a closed ride. I will listen, confirm what happened, show the best open nearby option, and bring a supervisor or Guest Services into any compensation decision.", "min_score": 85},
    ],
    "lost_child_report": [
        {"id": "lost_child_bad", "label": "bad", "message": "Go look around the carousel and come back if you cannot find her.", "max_score": 55, "critical_miss": True},
        {"id": "lost_child_partial", "label": "partial", "message": "I am sorry. What is she wearing?", "min_score": 35, "max_score": 74},
        {"id": "lost_child_passing", "label": "passing", "message": "I am sorry. Stay here while I call Security now. What is her name, age, clothing, and last seen location near the carousel?", "min_score": 75, "max_score": 92},
        {"id": "lost_child_excellent", "label": "excellent", "message": "I am sorry. We are going to help right now. Please stay with me at this meeting point while I radio Security and Operations. What is her name, age, what is she wearing, and where was she last seen?", "min_score": 85},
    ],
    "ride_closure_complaint": [
        {"id": "ride_closure_bad", "label": "bad", "message": "It will definitely reopen soon, just wait here.", "max_score": 55, "critical_miss": True},
        {"id": "ride_closure_partial", "label": "partial", "message": "Sorry, it is closed. Try another ride.", "min_score": 35, "max_score": 74},
        {"id": "ride_closure_passing", "label": "passing", "message": "I am sorry for the wait. I cannot promise a reopen time until clearance, but I can show open alternatives and connect Guest Services for refund questions.", "min_score": 75, "max_score": 90},
        {"id": "ride_closure_excellent", "label": "excellent", "message": "I am sorry you waited without a clear update. I cannot promise a reopen time until safety clearance, but I can show current open alternatives and connect you with Guest Services for any refund or compensation review.", "min_score": 85},
    ],
    "accessibility_accommodation": [
        {"id": "accessibility_bad", "label": "bad", "message": "He needs to prove his diagnosis before we can help.", "max_score": 55, "critical_miss": True},
        {"id": "accessibility_partial", "label": "partial", "message": "I can help you find shade.", "min_score": 35, "max_score": 74},
        {"id": "accessibility_passing", "label": "passing", "message": "I can help without asking for medical details. Let me get shade or seating and contact Accessibility or Guest Services to confirm the accommodation route.", "min_score": 75, "max_score": 92},
        {"id": "accessibility_excellent", "label": "excellent", "message": "You do not need to explain medical details here. I can help your father get shade or seating and contact Accessibility or Guest Services to confirm the right route or accommodation while preserving privacy.", "min_score": 85},
    ],
    "language_barrier": [
        {"id": "language_bad", "label": "bad", "message": "You need to speak English or figure it out.", "max_score": 55, "critical_miss": True},
        {"id": "language_partial", "label": "partial", "message": "Ticket problem? Go to Guest Services.", "min_score": 35, "max_score": 74},
        {"id": "language_passing", "label": "passing", "message": "I can help. Please stay here while I use translation support, confirm your family status, and show the next ticket or Guest Services step.", "min_score": 75, "max_score": 92},
        {"id": "language_excellent", "label": "excellent", "message": "I can help. Please stay here with me. I will use translation support, confirm whether your family is inside, and show one clear ticket or Guest Services step at a time.", "min_score": 85},
    ],
    "refund_request": [
        {"id": "refund_bad", "label": "bad", "message": "I guarantee a full cash refund right now.", "max_score": 55, "critical_miss": True},
        {"id": "refund_partial", "label": "partial", "message": "I understand. Guest Services handles refunds.", "min_score": 35, "max_score": 74},
        {"id": "refund_passing", "label": "passing", "message": "I understand. I cannot promise a refund myself, but I can collect the ticket details and bring Guest Services or a supervisor into the policy review.", "min_score": 75, "max_score": 92},
        {"id": "refund_excellent", "label": "excellent", "message": "I understand why you are upset. I cannot promise a refund myself, but I can collect your ticket details and issue summary, then bring Guest Services or a supervisor into the approved policy review.", "min_score": 85},
    ],
    "heat_exhaustion_concern": [
        {"id": "heat_bad", "label": "bad", "message": "She can probably walk it off after drinking something.", "max_score": 55, "critical_miss": True},
        {"id": "heat_partial", "label": "partial", "message": "Have her sit in shade and drink water.", "min_score": 35, "max_score": 74},
        {"id": "heat_passing", "label": "passing", "message": "This is urgent. Keep her seated in shade if safe while I call First Aid now. Do not walk her across the park until medical advises us.", "min_score": 75, "max_score": 92},
        {"id": "heat_excellent", "label": "excellent", "message": "I am treating this as urgent. Please keep her seated in shade if it is safe while I call First Aid or medical now. Do not walk her across the park until they advise us.", "min_score": 85},
    ],
    "line_cutting_conflict": [
        {"id": "line_bad", "label": "bad", "message": "Go confront them yourself if you are that mad.", "max_score": 55, "critical_miss": True},
        {"id": "line_partial", "label": "partial", "message": "I understand. I will check what happened.", "min_score": 35, "max_score": 74},
        {"id": "line_passing", "label": "passing", "message": "I understand why that feels unfair. Please do not confront them. I will check what happened and call a lead or Security if the conflict continues.", "min_score": 75, "max_score": 92},
        {"id": "line_excellent", "label": "excellent", "message": "I understand why that feels unfair. Please do not confront them; I need everyone to stay safe. I will check what happened and call a lead or Security if the conflict continues.", "min_score": 85},
    ],
    "safety_rule_refusal": [
        {"id": "safety_bad", "label": "bad", "message": "Fine, just this once I will start the ride.", "max_score": 55, "critical_miss": True},
        {"id": "safety_partial", "label": "partial", "message": "Please remove the strap.", "min_score": 35, "max_score": 74},
        {"id": "safety_passing", "label": "passing", "message": "For safety, the ride cannot start until the loose strap is removed or secured. I can help now and call my ride lead if you disagree.", "min_score": 75, "max_score": 92},
        {"id": "safety_excellent", "label": "excellent", "message": "For safety, this ride cannot start until the loose strap is removed or secured in a locker. I can help you do that now, and if you still disagree I will call my ride lead.", "min_score": 85},
    ],
    "weather_evacuation_confusion": [
        {"id": "weather_bad", "label": "bad", "message": "Everybody run to shelter now and take the stairs.", "max_score": 55, "critical_miss": True},
        {"id": "weather_partial", "label": "partial", "message": "Stay calm and go to shelter.", "min_score": 35, "max_score": 74},
        {"id": "weather_passing", "label": "passing", "message": "Stay calm and follow me to the covered shelter route. We will use the stroller-accessible path and I will contact a lead if the route is blocked.", "min_score": 75, "max_score": 92},
        {"id": "weather_excellent", "label": "excellent", "message": "Stay calm and follow me toward the covered shelter route. We will use the stroller-accessible path, and I will contact a lead if the route is blocked or weather risk changes.", "min_score": 85},
    ],
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_timestamp(value: Any) -> float:
    try:
        text = str(value or "").strip()
        if not text:
            return 0.0
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _session_log_path() -> str:
    return os.getenv("PARKPULSE_STAFF_TRAINING_LOG_PATH", "/tmp/parkpulse/staff_training_sessions.jsonl")


def _write_jsonl(row: dict[str, Any]) -> None:
    path = _session_log_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def _read_jsonl(limit: int = 200) -> list[dict[str, Any]]:
    path = _session_log_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()[-max(1, min(2000, int(limit or 200))) :]
    except Exception:
        return []
    rows = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _read_training_events(limit: int = 2000) -> list[dict[str, Any]]:
    return _read_jsonl(limit=max(1, min(5000, int(limit or 2000))))


def _persist_staff_training_session(session: dict[str, Any]) -> None:
    session_id = str(session.get("id") or "").strip()
    if not session_id:
        return
    try:
        from mongo_memory import _clean_for_bson, _ensure_memory_initialized, _memory

        _ensure_memory_initialized()
        collection = _memory._collection(_STAFF_TRAINING_SESSION_COLLECTION)
        document = {
            "_id": session_id,
            "id": session_id,
            "mode": "staff_roleplay_session",
            "session": session,
            "session_response": _session_response(session),
            "scenario_id": session.get("scenario_id"),
            "trainee_name": session.get("trainee_name"),
            "status": session.get("status"),
            "turn_count": session.get("turn_count"),
            "createdAt": session.get("started_at") or _now_iso(),
            "updatedAt": session.get("updated_at") or _now_iso(),
        }
        if collection is not None:
            collection.replace_one({"_id": session_id}, _clean_for_bson(document), upsert=True)
            return
        _memory._fallback[_STAFF_TRAINING_SESSION_COLLECTION] = [
            row for row in _memory._fallback.get(_STAFF_TRAINING_SESSION_COLLECTION, []) if row.get("_id") != session_id
        ]
        _memory._fallback[_STAFF_TRAINING_SESSION_COLLECTION].insert(0, document)
        _memory._fallback[_STAFF_TRAINING_SESSION_COLLECTION] = _memory._fallback[_STAFF_TRAINING_SESSION_COLLECTION][:200]
    except Exception:
        return


def _normalize_staff_training_session(session: dict[str, Any]) -> dict[str, Any]:
    scenario_id = str(session.get("scenario_id") or (session.get("scenario") or {}).get("id") or "lost_child_report")
    scenario = SCENARIOS.get(scenario_id) or SCENARIOS["lost_child_report"]
    active_learning_versions = session.get("active_learning_versions") if isinstance(session.get("active_learning_versions"), list) else []
    normalized = dict(session)
    normalized["id"] = str(normalized.get("id") or "")
    normalized["mode"] = normalized.get("mode") or "staff_roleplay_session"
    normalized["scenario_id"] = scenario["id"]
    normalized["scenario"] = normalized.get("scenario") if isinstance(normalized.get("scenario"), dict) else _public_scenario(scenario, active_learning_versions)
    normalized["status"] = normalized.get("status") or "active"
    normalized["trainee_name"] = str(normalized.get("trainee_name") or "Seasonal staff trainee")[:80]
    normalized["started_at"] = normalized.get("started_at") or normalized.get("createdAt") or _now_iso()
    normalized["updated_at"] = normalized.get("updated_at") or normalized.get("updatedAt") or normalized["started_at"]
    normalized["turn_count"] = int(normalized.get("turn_count") or 0)
    if not isinstance(normalized.get("transcript"), list) or not normalized["transcript"]:
        normalized["transcript"] = [{"speaker": "guest", "message": scenario["opening_message"], "at": normalized["started_at"]}]
    if not isinstance(normalized.get("scores"), list):
        normalized["scores"] = []
    normalized["scorecard"] = normalized.get("scorecard") if isinstance(normalized.get("scorecard"), dict) else _empty_scorecard()
    normalized["mastery_tracker"] = normalized.get("mastery_tracker") if isinstance(normalized.get("mastery_tracker"), dict) else _empty_mastery_tracker()
    normalized["completed_objectives"] = normalized.get("completed_objectives") if isinstance(normalized.get("completed_objectives"), list) else []
    normalized["missing_objectives"] = normalized.get("missing_objectives") if isinstance(normalized.get("missing_objectives"), list) else list(scenario["objectives"])
    normalized["critical_miss"] = bool(normalized.get("critical_miss"))
    normalized["guest_simulator"] = normalized.get("guest_simulator") if isinstance(normalized.get("guest_simulator"), dict) else {
        "mode": "deterministic_guest",
        "llm_requested": False,
        "llm_controls_score": False,
        "fallback": "deterministic_guest_reply",
    }
    normalized["boundary"] = normalized.get("boundary") or "Training simulator only; no live dispatch, guest PII, reward labels, or policy promotion authority."
    return normalized


def _load_persisted_staff_training_session(session_id: str) -> dict[str, Any] | None:
    safe_id = str(session_id or "").strip()
    if not safe_id:
        return None
    try:
        from mongo_memory import get_memory_document

        document = get_memory_document(_STAFF_TRAINING_SESSION_COLLECTION, safe_id)
    except Exception:
        document = None
    if isinstance(document, dict):
        session = document.get("session") if isinstance(document.get("session"), dict) else document.get("session_response")
        if isinstance(session, dict):
            loaded = _normalize_staff_training_session(session)
            if loaded.get("id"):
                _SESSIONS[str(loaded["id"])] = loaded
                return loaded
    for row in reversed(_read_training_events(5000)):
        row_id = str(row.get("id") or row.get("session_id") or "")
        if row_id != safe_id:
            continue
        scenario_id = str(row.get("scenario_id") or "lost_child_report")
        scenario = SCENARIOS.get(scenario_id) or SCENARIOS["lost_child_report"]
        loaded = _normalize_staff_training_session(
            {
                "id": safe_id,
                "scenario_id": scenario["id"],
                "scenario": _public_scenario(scenario, row.get("active_learning_versions") if isinstance(row.get("active_learning_versions"), list) else []),
                "trainee_name": row.get("trainee_name"),
                "assignment_id": row.get("assignment_id"),
                "retry_of_session_id": row.get("retry_of_session_id"),
                "status": row.get("status"),
                "turn_count": row.get("turn_count"),
                "scorecard": row.get("scorecard"),
                "critical_miss": row.get("critical_miss"),
                "mastery_tracker": row.get("mastery_tracker"),
                "active_learning_versions": row.get("active_learning_versions"),
                "active_learning_version_ids": row.get("active_learning_version_ids"),
                "learning_version_guidance": row.get("learning_version_guidance"),
                "retrieved_training_context": row.get("retrieved_training_context"),
                "agent_contract": row.get("agent_contract"),
                "agent_tool_manifest": row.get("agent_tool_manifest"),
                "tool_trace": row.get("tool_trace"),
                "completed_objectives": row.get("completed_objectives"),
                "missing_objectives": row.get("missing_objectives"),
                "started_at": row.get("created_at"),
                "updated_at": row.get("created_at"),
                "transcript": row.get("transcript"),
                "scores": row.get("scores"),
            }
        )
        _SESSIONS[safe_id] = loaded
        return loaded
    return None


def _get_staff_training_session(session_id: str) -> dict[str, Any] | None:
    safe_id = str(session_id or "").strip()
    if not safe_id:
        return None
    return _SESSIONS.get(safe_id) or _load_persisted_staff_training_session(safe_id)


def _public_scenario(scenario: dict[str, Any], active_learning_versions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    public = {
        "id": scenario["id"],
        "title": scenario["title"],
        "category": scenario["category"],
        "difficulty": scenario["difficulty"],
        "guest_role": scenario["guest_role"],
        "opening_message": scenario["opening_message"],
        "context": scenario["context"],
        "objectives": scenario["objectives"],
    }
    versions = active_learning_versions or []
    if versions:
        guidance = _learning_version_guidance(versions)
        public["active_learning_versions"] = versions
        public["learning_version_guidance"] = guidance
        public["context"] = f"{public['context']} Active learning guidance: {' '.join(guidance)}"
    return public


def _active_learning_versions_for_scenario(scenario_id: str) -> list[dict[str, Any]]:
    try:
        from product_learning_loop import active_learning_versions_for_scenario

        return active_learning_versions_for_scenario(scenario_id, target_surface="staff_training")
    except Exception:
        return []


def _guest_triage_training_memory(scenario_id: str) -> dict[str, Any]:
    try:
        from product_learning_loop import guest_triage_training_memory

        memory = guest_triage_training_memory(scenario_id, limit=80)
        return memory if isinstance(memory, dict) else {"status": "empty", "patterns": [], "recent_examples": []}
    except Exception as error:
        return {"status": "error", "patterns": [], "recent_examples": [], "readiness_issues": [str(error)[:180]]}


def _guest_triage_assignment_recommendations(role: str, limit: int = 6) -> list[dict[str, Any]]:
    try:
        from product_learning_loop import recommended_training_scenarios_from_guest_triage

        recommendation_limit = max(12, min(20, int(limit or 6) * 4))
        recommendations = recommended_training_scenarios_from_guest_triage(limit=recommendation_limit)
    except Exception:
        return []
    allowed = set(STAFF_ROLE_ASSIGNMENT_SCENARIOS.get(role) or [])
    role_priority = {scenario_id: index for index, scenario_id in enumerate(STAFF_ROLE_ASSIGNMENT_SCENARIOS.get(role) or [])}
    rows: list[dict[str, Any]] = []
    for item in recommendations:
        if not isinstance(item, dict):
            continue
        scenario_id = str(item.get("scenario_id") or "")
        if scenario_id in SCENARIOS and (not allowed or scenario_id in allowed):
            rows.append(item)
    rows.sort(
        key=lambda item: (
            0 if TRAINING_SEVERITY_RANK.get(str(item.get("highest_severity") or ""), 0) >= TRAINING_SEVERITY_RANK["critical"] else 1,
            -_iso_timestamp(item.get("latest_created_at")),
            -TRAINING_SEVERITY_RANK.get(str(item.get("highest_severity") or ""), 0),
            -int(item.get("evidence_count") or 0),
            role_priority.get(str(item.get("scenario_id") or ""), 999),
        )
    )
    return rows[: max(1, min(12, int(limit or 6)))]


def _learning_version_guidance(active_learning_versions: list[dict[str, Any]]) -> list[str]:
    guidance: list[str] = []
    for version in active_learning_versions[:3]:
        summary = str(version.get("content_summary") or version.get("draft_title") or "").strip()
        if summary:
            guidance.append(summary[:500])
    return guidance


def _staff_training_agent_contract() -> dict[str, Any]:
    return {
        "mode": "staff_training_agent_contract",
        "roles": STAFF_TRAINING_AGENT_ROLES,
        "tool_manifest": STAFF_TRAINING_TOOL_MANIFEST,
        "blocked_tools": STAFF_TRAINING_BLOCKED_TOOLS,
        "rag_contract": {
            "retrieval_method": "scenario_and_trainee_lexical_jsonl_plus_product_learning_versions",
            "retrieves": ["active staff-training learning versions", "prior session outcomes", "training gap tickets", "scenario policy refs"],
            "llm_controls_retrieval": False,
            "llm_controls_score": False,
        },
        "boundaries": [
            "LLM guest generation can use retrieved context but cannot score turns.",
            "Training memory can create product-learning tickets only after debrief.",
            "No training agent can dispatch live actions, approve refunds, diagnose guests, write reward labels, or promote models.",
        ],
    }


def _scenario_policy_refs(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    refs = [
        {"id": f"scenario:{scenario.get('id')}", "label": str(scenario.get("title") or ""), "type": "scenario"},
        {"id": "rubric:staff_training_v1", "label": "Deterministic staff-training rubric", "type": "rubric"},
    ]
    if scenario.get("difficulty") == "critical":
        refs.append({"id": "policy:safety_escalation_required", "label": "Critical scenarios require explicit safety escalation.", "type": "policy"})
    category = str(scenario.get("category") or "").lower()
    if "access" in category:
        refs.append({"id": "policy:accessibility_privacy", "label": "Respect privacy and avoid medical probing.", "type": "policy"})
    if "safety" in category or "ride" in category:
        refs.append({"id": "policy:ride_safety_no_override", "label": "Never override safety requirements during training.", "type": "policy"})
    return refs


def _text_tokens(value: Any) -> set[str]:
    raw = str(value or "").lower()
    token = ""
    tokens: set[str] = set()
    for char in raw:
        if char.isalnum() or char == "_":
            token += char
        elif token:
            if len(token) >= 3:
                tokens.add(token)
            token = ""
    if token and len(token) >= 3:
        tokens.add(token)
    return tokens


def _compact_session_memory(row: dict[str, Any], query_tokens: set[str], scenario_id: str, trainee_key: str) -> dict[str, Any] | None:
    row_scenario = str(row.get("scenario_id") or "")
    scorecard = row.get("scorecard", {}) if isinstance(row.get("scorecard"), dict) else {}
    mastery = row.get("mastery_tracker", {}) if isinstance(row.get("mastery_tracker"), dict) else {}
    debrief = row.get("debrief", {}) if isinstance(row.get("debrief"), dict) else {}
    trainee = str(row.get("trainee_name") or "")
    row_tokens = _text_tokens(
        " ".join(
            [
                row_scenario,
                trainee,
                str(debrief.get("summary") or ""),
                " ".join(str(item.get("label") or "") for item in (mastery.get("open_gaps", []) if isinstance(mastery.get("open_gaps"), list) else []) if isinstance(item, dict)),
            ]
        )
    )
    score = len(query_tokens & row_tokens)
    if row_scenario == scenario_id:
        score += 6
    if trainee_key and trainee.strip().lower() == trainee_key:
        score += 4
    if row.get("critical_miss"):
        score += 1
    if score <= 0:
        return None
    return {
        "session_id": row.get("id") or row.get("session_id"),
        "scenario_id": row_scenario,
        "trainee_name": trainee,
        "overall": scorecard.get("overall"),
        "critical_miss": bool(row.get("critical_miss")),
        "mastery_level": mastery.get("mastery_level"),
        "open_gaps": [str(item.get("label") or item.get("type") or "") for item in (mastery.get("open_gaps", []) if isinstance(mastery.get("open_gaps"), list) else []) if isinstance(item, dict)][:5],
        "repaired_gaps": [str(item.get("label") or item.get("type") or "") for item in (mastery.get("repaired_gaps", []) if isinstance(mastery.get("repaired_gaps"), list) else []) if isinstance(item, dict)][:5],
        "debrief_result": debrief.get("result"),
        "summary": str(debrief.get("summary") or "")[:240],
        "finished_at": row.get("finished_at") or row.get("created_at"),
        "retrieval_score": score,
    }


def _product_learning_gap_patterns(scenario_id: str, limit: int = 500) -> list[dict[str, Any]]:
    try:
        from product_learning_loop import _read_events

        events = _read_events(limit)
    except Exception:
        events = []
    patterns: dict[str, dict[str, Any]] = {}
    for row in events:
        if row.get("event") != "training_gap_ticket_created" or str(row.get("scenario_id") or "") != scenario_id:
            continue
        gap_type = str(row.get("gap_type") or "unknown")
        pattern = patterns.setdefault(
            gap_type,
            {
                "gap_type": gap_type,
                "count": 0,
                "highest_severity": "low",
                "latest_summary": "",
            },
        )
        pattern["count"] = int(pattern.get("count") or 0) + 1
        severity = str(row.get("severity") or "low")
        if {"low": 1, "coaching": 2, "medium": 2, "high": 3, "critical_training_gap": 4, "critical": 4}.get(severity, 1) > {"low": 1, "coaching": 2, "medium": 2, "high": 3, "critical_training_gap": 4, "critical": 4}.get(str(pattern.get("highest_severity") or "low"), 1):
            pattern["highest_severity"] = severity
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        summary = str(evidence.get("summary") or evidence.get("transcript_excerpt") or row.get("summary") or "").strip()
        if summary:
            pattern["latest_summary"] = summary[:240]
    return sorted(patterns.values(), key=lambda item: int(item.get("count") or 0), reverse=True)[:6]


def _policy_book_snippets(scenario: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    query = " ".join(
        [
            str(scenario.get("id") or ""),
            str(scenario.get("title") or ""),
            str(scenario.get("category") or ""),
            str(scenario.get("context") or ""),
            " ".join(str(item) for item in scenario.get("objectives", []) or []),
        ]
    )
    try:
        from policy_loader import retrieve_operational_doctrine

        doctrine = retrieve_operational_doctrine(query, {"scenario": scenario.get("id"), "active_policy": scenario.get("category")}, limit=limit)
    except Exception:
        return []
    snippets: list[dict[str, Any]] = []
    for item in doctrine.get("matches", []) if isinstance(doctrine.get("matches"), list) else []:
        if not isinstance(item, dict):
            continue
        snippets.append(
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "book_id": item.get("book_id"),
                "kind": item.get("kind"),
                "summary": str(item.get("summary") or "")[:360],
                "policy_refs": [str(ref) for ref in item.get("policy_refs", []) if ref][:8],
                "blocked_actions": [str(action) for action in item.get("blocked_actions", []) if action][:5],
                "matched_terms": [str(term) for term in item.get("matched_terms", []) if term][:8],
                "retrieval_score": item.get("score"),
            }
        )
    return snippets[:limit]


def _manager_review_memory(events: list[dict[str, Any]], scenario_id: str, trainee_key: str) -> list[dict[str, Any]]:
    finished_by_session = {
        str(row.get("id") or row.get("session_id") or ""): row
        for row in events
        if row.get("event") == "session_finished"
    }
    reviews: list[dict[str, Any]] = []
    for row in events:
        if row.get("event") != "receipt_reviewed":
            continue
        session_id = str(row.get("session_id") or "")
        finished = finished_by_session.get(session_id, {})
        row_scenario = str(row.get("scenario_id") or finished.get("scenario_id") or "")
        trainee = str(row.get("trainee_name") or finished.get("trainee_name") or "")
        if row_scenario != scenario_id and (not trainee_key or trainee.strip().lower() != trainee_key):
            continue
        reviews.append(
            {
                "review_id": row.get("review_id") or row.get("id"),
                "session_id": session_id,
                "scenario_id": row_scenario,
                "trainee_name": trainee,
                "decision": row.get("decision"),
                "reviewer": row.get("reviewer"),
                "notes": str(row.get("notes") or "")[:360],
                "created_at": row.get("created_at"),
                "boundary": "Manager review memory guides simulated coaching only.",
            }
        )
    reviews.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return reviews[:8]


def _trainee_profile_from_memory(prior_sessions: list[dict[str, Any]], manager_reviews: list[dict[str, Any]], trainee_name: str | None) -> dict[str, Any]:
    scores = [float(item.get("overall") or 0) for item in prior_sessions if isinstance(item.get("overall"), (int, float))]
    open_gap_counts: dict[str, int] = {}
    for item in prior_sessions:
        for gap in item.get("open_gaps", []) if isinstance(item.get("open_gaps"), list) else []:
            key = str(gap or "").strip() or "unknown"
            open_gap_counts[key] = open_gap_counts.get(key, 0) + 1
    review_counts: dict[str, int] = {}
    for review in manager_reviews:
        decision = str(review.get("decision") or "unknown")
        review_counts[decision] = review_counts.get(decision, 0) + 1
        note = str(review.get("notes") or "")
        if note:
            for token in sorted(_text_tokens(note))[:12]:
                if token in {"escalation", "safety", "policy", "clarity", "empathy"}:
                    open_gap_counts[token] = open_gap_counts.get(token, 0) + 1
    recurring = [
        {"label": label, "count": count}
        for label, count in sorted(open_gap_counts.items(), key=lambda item: item[1], reverse=True)
    ][:6]
    return {
        "status": "ready" if prior_sessions or manager_reviews else "empty",
        "trainee_name": str(trainee_name or "")[:80],
        "session_count": len(prior_sessions),
        "average_score": round(sum(scores) / len(scores), 1) if scores else None,
        "critical_miss_count": sum(1 for item in prior_sessions if item.get("critical_miss")),
        "manager_review_count": len(manager_reviews),
        "manager_review_decisions": review_counts,
        "recurring_gaps": recurring,
        "coaching_priority": recurring[0]["label"] if recurring else None,
        "boundary": "Longitudinal trainee profile is simulated-training memory only.",
    }


def _staff_training_tool_trace(session: dict[str, Any], phase: str, score: dict[str, Any] | None = None, guest_generation: dict[str, Any] | None = None, shadow_eval: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    context = session.get("retrieved_training_context") if isinstance(session.get("retrieved_training_context"), dict) else {}
    counts = context.get("counts") if isinstance(context.get("counts"), dict) else {}
    trace = [
        {
            "tool": "staff_training.retrieve_context",
            "agent": "context_retriever",
            "status": "complete",
            "output": counts,
            "live_ops_authority": False,
        }
    ]
    if phase == "start":
        return trace
    trace.append(
        {
            "tool": "staff_training.score_turn",
            "agent": "deterministic_scorer",
            "status": "complete",
            "output": {"overall": (score or {}).get("overall"), "critical_miss": bool((score or {}).get("critical_miss"))},
            "score_authority": True,
            "live_ops_authority": False,
        }
    )
    trace.append(
        {
            "tool": "staff_training.update_mastery_memory",
            "agent": "mastery_tracker",
            "status": "complete",
            "output": {
                "mastery_level": (session.get("mastery_tracker") or {}).get("mastery_level") if isinstance(session.get("mastery_tracker"), dict) else None,
                "open_gap_count": len((session.get("mastery_tracker") or {}).get("open_gaps", [])) if isinstance(session.get("mastery_tracker"), dict) else 0,
            },
            "live_ops_authority": False,
        }
    )
    trace.append(
        {
            "tool": "staff_training.generate_guest_turn",
            "agent": "guest_simulator",
            "status": (guest_generation or {}).get("status") or "complete",
            "output": {"source": (guest_generation or {}).get("source"), "llm_controls_score": False},
            "score_authority": False,
            "live_ops_authority": False,
        }
    )
    if shadow_eval:
        trace.append(
            {
                "tool": "staff_training.shadow_eval",
                "agent": "shadow_evaluator",
                "status": shadow_eval.get("status"),
                "output": {"alignment": shadow_eval.get("alignment"), "score_authority": False},
                "score_authority": False,
                "live_ops_authority": False,
            }
        )
    return trace


def retrieve_staff_training_context(
    scenario_id: str | None = None,
    trainee_name: str | None = None,
    assignment_id: str | None = None,
    *,
    limit: int = 6,
) -> dict[str, Any]:
    scenario = SCENARIOS.get(str(scenario_id or "").strip()) or SCENARIOS["lost_child_report"]
    scenario_key = str(scenario.get("id") or "")
    trainee_key = str(trainee_name or "").strip().lower()
    query_tokens = _text_tokens(" ".join([scenario_key, str(scenario.get("title") or ""), str(scenario.get("context") or ""), str(trainee_name or ""), str(assignment_id or "")]))
    session_rows = [row for row in _read_training_events(1200) if row.get("event") == "session_finished"]
    all_training_events = _read_training_events(1600)
    compact_rows = [
        item
        for item in (_compact_session_memory(row, query_tokens, scenario_key, trainee_key) for row in session_rows)
        if item is not None
    ]
    compact_rows.sort(key=lambda item: (int(item.get("retrieval_score") or 0), str(item.get("finished_at") or "")), reverse=True)
    active_versions = _active_learning_versions_for_scenario(scenario_key)
    manager_reviews = _manager_review_memory(all_training_events, scenario_key, trainee_key)
    trainee_profile = _trainee_profile_from_memory(compact_rows, manager_reviews, trainee_name)
    policy_snippets = _policy_book_snippets(scenario)
    training_gap_patterns = _product_learning_gap_patterns(scenario_key)
    guest_triage_memory = _guest_triage_training_memory(scenario_key)
    guest_triage_patterns = guest_triage_memory.get("patterns") if isinstance(guest_triage_memory.get("patterns"), list) else []
    guest_triage_examples = guest_triage_memory.get("recent_examples") if isinstance(guest_triage_memory.get("recent_examples"), list) else []
    historical_ticket_frequency = guest_triage_memory.get("scenario_frequencies") if isinstance(guest_triage_memory.get("scenario_frequencies"), list) else []
    context = {
        "status": "ready",
        "mode": "staff_training_rag_context",
        "scenario_id": scenario_key,
        "trainee_name": str(trainee_name or "")[:80],
        "assignment_id": str(assignment_id or "")[:80] or None,
        "retrieval_method": "scenario_and_trainee_lexical_jsonl_plus_product_learning_versions_plus_guest_triage_mongodb",
        "retrieved": {
            "policy_refs": _scenario_policy_refs(scenario),
            "policy_snippets": policy_snippets,
            "active_learning_versions": active_versions[:3],
            "active_learning_guidance": _learning_version_guidance(active_versions),
            "prior_sessions": compact_rows[: max(1, min(12, int(limit or 6)))],
            "training_gap_patterns": training_gap_patterns,
            "guest_triage_patterns": guest_triage_patterns[:6],
            "guest_triage_examples": guest_triage_examples[:5],
            "historical_ticket_frequency": historical_ticket_frequency[:6],
            "scenario_recommendation": guest_triage_memory.get("assignment_recommendation"),
            "manager_reviews": manager_reviews,
            "trainee_profile": trainee_profile,
        },
        "counts": {
            "policy_refs": len(_scenario_policy_refs(scenario)),
            "policy_snippets": len(policy_snippets),
            "active_learning_versions": len(active_versions),
            "prior_sessions": len(compact_rows),
            "training_gap_patterns": len(training_gap_patterns),
            "guest_triage_patterns": len(guest_triage_patterns),
            "guest_triage_examples": len(guest_triage_examples),
            "historical_ticket_frequency": len(historical_ticket_frequency),
            "manager_reviews": len(manager_reviews),
        },
        "tool_manifest_ids": [str(item.get("id") or "") for item in STAFF_TRAINING_TOOL_MANIFEST],
        "blocked_tools": STAFF_TRAINING_BLOCKED_TOOLS,
        "memory_scope": "staff_training_sessions_jsonl+product_learning_events+guest_messages_mongodb",
        "boundary": "Retrieved context can guide simulated training only. It cannot authorize live operations, reward labels, refunds, diagnoses, or model promotion.",
    }
    return context


def _llm_guest_provider_status() -> dict[str, Any]:
    try:
        from gemini_provider import get_gemini_agent_properties, get_gemini_model

        props = get_gemini_agent_properties()
        return {
            "ready": bool(props.ready),
            "provider": props.provider,
            "platform": props.platform,
            "model": get_gemini_model(),
            "use_vertex_ai": bool(getattr(props, "use_vertex_ai", False)),
            "vertex_ai_ready": bool(getattr(props, "use_vertex_ai", False) and props.ready),
            "readiness_issues": list(getattr(props, "readiness_issues", []) or []),
            "required_env": list(getattr(props, "required_env", []) or []),
            "llm_controls_score": False,
        }
    except Exception as error:
        return {
            "ready": False,
            "provider": "unknown",
            "platform": "unknown",
            "use_vertex_ai": False,
            "vertex_ai_ready": False,
            "readiness_issues": [str(error)[:240]],
            "required_env": [],
            "llm_controls_score": False,
        }


def list_staff_training_scenarios() -> dict[str, Any]:
    scenarios = [_public_scenario(item) for item in SCENARIOS.values()]
    return {
        "status": "ready",
        "mode": "staff_roleplay_scenario_catalog",
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
        "rubric_dimensions": RUBRIC_DIMENSIONS,
        "boundary": "Roleplay data is simulated staff training evidence. It is not fed into live operations dispatch or the actual outcome reward model.",
        "uses_generated_data": True,
        "feeds_actual_reward_model": False,
        "llm_guest_mode": {
            "available_when_configured": True,
            "request_fields": ["use_llm_guest", "useLlmGuest"],
            "fallback": "deterministic_guest_reply",
            "provider_status": _llm_guest_provider_status(),
            "llm_controls_score": False,
        },
        "llm_control_authority": False,
    }


def staff_training_policy_pack() -> dict[str, Any]:
    scenarios = [_public_scenario(item) for item in SCENARIOS.values()]
    agent_contract = _staff_training_agent_contract()
    return {
        "status": "ready",
        "mode": "staff_roleplay_policy_pack",
        "id": "parkpulse_staff_roleplay_training_v1",
        "title": "ParkPulse Staff Roleplay Training Policy Pack",
        "scenario_count": len(scenarios),
        "rubric_dimensions": RUBRIC_DIMENSIONS,
        "scenario_categories": sorted({str(item.get("category") or "Uncategorized") for item in SCENARIOS.values()}),
        "critical_scenarios": [
            item["id"]
            for item in SCENARIOS.values()
            if item.get("difficulty") == "critical" or item.get("fatal_if_missing_after_turn") is not None
        ],
        "scenarios": scenarios,
        "scoring_contract": {
            "authority": "deterministic_policy_and_safety_rubric",
            "llm_controls_score": False,
            "fatal_miss_caps_score": True,
            "dimensions": RUBRIC_DIMENSIONS,
            "golden_eval_case_count": sum(len(items) for items in STAFF_TRAINING_GOLDEN_RESPONSES.values()),
            "golden_eval_route": "/api/park/staff-training/golden-eval",
        },
        "llm_guest_contract": {
            "allowed": "Generate only guest-side roleplay replies when configured.",
            "not_allowed": [
                "score employee turns",
                "reveal rubric internals",
                "approve refunds or accommodations",
                "resolve safety incidents",
                "dispatch live park actions",
            ],
            "fallback": "deterministic_guest_reply",
            "provider_status": _llm_guest_provider_status(),
        },
        "data_boundary": {
            "uses_generated_data": True,
            "feeds_actual_reward_model": False,
            "writes_live_dispatch": False,
            "contains_guest_pii": False,
            "training_labels_source": "deterministic rubric over simulated staff responses",
        },
        "manager_review": {
            "recommended_metrics": [
                "critical_miss_rate",
                "weakest_rubric_dimension",
                "scenario_average_score",
                "coach_and_retry_count",
            ],
            "minimum_live_shadowing_gate": "No critical miss and overall score at least 75.",
        },
        "agent_contract": agent_contract,
        "tool_manifest": agent_contract["tool_manifest"],
        "rag_contract": agent_contract["rag_contract"],
        "blocked_tools": STAFF_TRAINING_BLOCKED_TOOLS,
    }


def create_staff_training_assignment(
    trainee_name: str | None = None,
    staff_role: str | None = None,
    scenario_ids: list[str] | None = None,
    assigned_by: str | None = None,
) -> dict[str, Any]:
    role = _normalize_staff_role(staff_role)
    requested = [str(item or "").strip() for item in (scenario_ids or [])]
    valid_requested = [item for item in requested if item in SCENARIOS]
    default_scenarios = list(STAFF_ROLE_ASSIGNMENT_SCENARIOS.get(role) or STAFF_ROLE_ASSIGNMENT_SCENARIOS["guest_services"])
    recommended = _guest_triage_assignment_recommendations(role, limit=len(default_scenarios))
    recommended_ids = [str(item.get("scenario_id") or "") for item in recommended if str(item.get("scenario_id") or "") in default_scenarios]
    assigned_scenarios = valid_requested or [*recommended_ids, *[item for item in default_scenarios if item not in set(recommended_ids)]]
    assignment_id = "staff-assign-" + hashlib.sha1(f"{trainee_name or ''}:{role}:{','.join(assigned_scenarios)}:{time.time()}".encode("utf-8")).hexdigest()[:14]
    assignment = {
        "event": "assignment_created",
        "id": assignment_id,
        "assignment_id": assignment_id,
        "trainee_name": str(trainee_name or "Seasonal staff trainee")[:80],
        "staff_role": role,
        "scenario_ids": assigned_scenarios,
        "assigned_by": str(assigned_by or "ParkPulse manager")[:80],
        "status": "assigned",
        "created_at": _now_iso(),
        "source": "explicit_manager_selection" if valid_requested else "guest_triage_memory_prioritized" if recommended_ids else "role_default",
        "source_signals": recommended[:4] if not valid_requested else [],
        "boundary": "Training assignment only; does not dispatch live work or create actual reward labels.",
    }
    _write_jsonl(assignment)
    return {
        "status": "created",
        "mode": "staff_roleplay_assignment",
        "assignment": _assignment_response(assignment),
        "uses_generated_data": True,
        "feeds_actual_reward_model": False,
    }


def list_staff_training_assignments(limit: int = 200) -> dict[str, Any]:
    events = _read_training_events(limit)
    assignments = [_assignment_response(row) for row in events if row.get("event") == "assignment_created"]
    readiness = _readiness_by_assignment(events)
    for assignment in assignments:
        status = readiness.get(str(assignment.get("id") or ""))
        if status:
            assignment.update(
                {
                    "status": status.get("status"),
                    "completed_count": status.get("completed_count"),
                    "required_count": status.get("required_count"),
                    "last_score": status.get("last_score"),
                    "critical_miss_count": status.get("critical_miss_count"),
                }
            )
    return {
        "status": "ready" if assignments else "empty",
        "mode": "staff_roleplay_assignments",
        "assignment_count": len(assignments),
        "assignments": assignments[-max(1, min(200, int(limit or 200))) :],
        "role_templates": _role_templates(),
        "boundary": "Assignments are manager training workflow records only.",
        "uses_generated_data": True,
        "feeds_actual_reward_model": False,
    }


def staff_training_readiness(limit: int = 500) -> dict[str, Any]:
    events = _read_training_events(limit)
    assignments = [_assignment_response(row) for row in events if row.get("event") == "assignment_created"]
    status_by_assignment = _readiness_by_assignment(events)
    rows = []
    for assignment in assignments:
        assignment_id = str(assignment.get("id") or "")
        status = status_by_assignment.get(assignment_id) or _assignment_readiness(assignment, [])
        rows.append(status)
    rows = rows[-max(1, min(300, int(limit or 500))) :]
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row.get("status") or "unknown")] = counts.get(str(row.get("status") or "unknown"), 0) + 1
    return {
        "status": "ready" if rows else "empty",
        "mode": "staff_roleplay_readiness",
        "trainee_count": len(rows),
        "status_counts": counts,
        "readiness": rows,
        "minimum_live_shadowing_gate": "No critical miss and overall score at least 75 on every assigned scenario.",
        "boundary": "Readiness gates live shadowing only after manager review; this does not authorize live dispatch.",
        "uses_generated_data": True,
        "feeds_actual_reward_model": False,
    }


def staff_training_receipts(limit: int = 80) -> dict[str, Any]:
    events = _read_training_events(limit=max(500, int(limit or 80) * 8))
    finished = [row for row in events if row.get("event") == "session_finished"]
    reviews = _latest_reviews_by_session(events)
    receipts = [_receipt_response(row, reviews.get(str(row.get("id") or row.get("session_id") or ""))) for row in finished[-max(1, min(200, int(limit or 80))) :]]
    return {
        "status": "ready" if receipts else "empty",
        "mode": "staff_roleplay_receipts",
        "receipt_count": len(receipts),
        "receipts": receipts,
        "boundary": "Receipts are manager review evidence from simulated roleplay only.",
        "uses_generated_data": True,
        "feeds_actual_reward_model": False,
    }


def staff_training_certification_packet(assignment_id: str | None = None, trainee_name: str | None = None) -> dict[str, Any]:
    events = _read_training_events()
    assignments = [_assignment_response(row) for row in events if row.get("event") == "assignment_created"]
    assignment = _find_assignment(assignments, assignment_id=assignment_id, trainee_name=trainee_name)
    if not assignment:
        return {
            "status": "not_found",
            "mode": "staff_roleplay_certification_packet",
            "readiness_issues": ["Training assignment was not found."],
        }

    reviews = _latest_reviews_by_session(events)
    finished = [row for row in events if row.get("event") == "session_finished" and str(row.get("assignment_id") or "") == str(assignment.get("id") or "")]
    readiness = _assignment_readiness(assignment, finished, reviews)
    receipts = [_receipt_response(row, reviews.get(str(row.get("id") or row.get("session_id") or ""))) for row in finished]
    packet_status = "eligible_for_manager_signoff" if readiness.get("status") == "ready_for_shadowing" else "blocked"
    packet_id = "staff-cert-" + hashlib.sha1(str(assignment.get("id") or "").encode("utf-8")).hexdigest()[:14]
    return {
        "status": "ready",
        "mode": "staff_roleplay_certification_packet",
        "id": packet_id,
        "assignment": assignment,
        "readiness": readiness,
        "receipts": receipts,
        "packet_status": packet_status,
        "manager_signoff_required": True,
        "next_actions": _packet_next_actions(assignment, readiness, receipts),
        "gate_contract": {
            "minimum_live_shadowing_gate": "No critical miss and overall score at least 75 on every assigned scenario.",
            "manager_review_can_override_score": False,
            "manager_review_can_hold_or_require_retry": True,
        },
        "boundary": "Certification packet summarizes simulated training evidence only; it does not dispatch live work, approve compensation, promote models, or create reward labels.",
        "uses_generated_data": True,
        "feeds_actual_reward_model": False,
        "writes_live_dispatch": False,
    }


def review_staff_training_receipt(
    session_id: str | None = None,
    receipt_id: str | None = None,
    decision: str | None = None,
    reviewer: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    normalized_decision = str(decision or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized_decision == "approve":
        normalized_decision = "approve_shadowing"
    if normalized_decision not in STAFF_TRAINING_REVIEW_DECISIONS:
        return {
            "status": "invalid",
            "mode": "staff_roleplay_receipt_review",
            "readiness_issues": ["Review decision must be approve_shadowing, require_retry, or hold."],
        }

    events = _read_training_events()
    finished = [row for row in events if row.get("event") == "session_finished"]
    target = _find_receipt_target(finished, session_id=session_id, receipt_id=receipt_id)
    if not target:
        return {
            "status": "not_found",
            "mode": "staff_roleplay_receipt_review",
            "readiness_issues": ["Training receipt was not found."],
        }

    target_session_id = str(target.get("id") or target.get("session_id") or "")
    review_id = "staff-review-" + hashlib.sha1(f"{target_session_id}:{normalized_decision}:{time.time()}".encode("utf-8")).hexdigest()[:14]
    review = {
        "event": "receipt_reviewed",
        "id": review_id,
        "review_id": review_id,
        "receipt_id": _receipt_id(target_session_id),
        "session_id": target_session_id,
        "assignment_id": target.get("assignment_id"),
        "trainee_name": target.get("trainee_name") or "Seasonal staff trainee",
        "scenario_id": target.get("scenario_id"),
        "decision": normalized_decision,
        "reviewer": str(reviewer or "ParkPulse manager")[:80],
        "notes": str(notes or "")[:500],
        "created_at": _now_iso(),
        "boundary": "Manager review disposition only; it does not alter deterministic score, live dispatch, or reward labels.",
        "uses_generated_data": True,
        "feeds_actual_reward_model": False,
    }
    _write_jsonl(review)
    return {
        "status": "recorded",
        "mode": "staff_roleplay_receipt_review",
        "review": _review_response(review),
        "receipt": _receipt_response(target, review),
        "readiness": staff_training_readiness(),
        "uses_generated_data": True,
        "feeds_actual_reward_model": False,
    }


def seed_staff_training_demo_data() -> dict[str, Any]:
    events = _read_training_events()
    if any(row.get("event") == "demo_seeded" for row in events):
        return {
            "status": "already_seeded",
            "mode": "staff_roleplay_demo_seed",
            "message": "Demo staff training data already exists.",
            "readiness": staff_training_readiness(),
            "uses_generated_data": True,
            "feeds_actual_reward_model": False,
        }

    created_assignments = []
    created_receipts = []
    for item in DEMO_TRAINEES:
        assignment = create_staff_training_assignment(
            item["trainee_name"],
            item["staff_role"],
            [item["scenario_id"]],
            assigned_by="Demo manager",
        )["assignment"]
        receipt = _demo_finished_session(item, assignment)
        _write_jsonl(receipt)
        created_assignments.append(assignment)
        created_receipts.append(_receipt_response(receipt))
    _write_jsonl({"event": "demo_seeded", "created_at": _now_iso(), "assignment_count": len(created_assignments), "receipt_count": len(created_receipts)})
    return {
        "status": "seeded",
        "mode": "staff_roleplay_demo_seed",
        "assignment_count": len(created_assignments),
        "receipt_count": len(created_receipts),
        "assignments": created_assignments,
        "receipts": created_receipts,
        "readiness": staff_training_readiness(),
        "uses_generated_data": True,
        "feeds_actual_reward_model": False,
    }


def start_staff_training_session(
    scenario_key: str | None = None,
    trainee_name: str | None = None,
    use_llm_guest: bool | None = None,
    assignment_id: str | None = None,
    retry_of_session_id: str | None = None,
) -> dict[str, Any]:
    scenario = SCENARIOS.get(str(scenario_key or "").strip()) or SCENARIOS["lost_child_report"]
    session_id = "staff-train-" + hashlib.sha1(f"{scenario['id']}:{time.time()}:{trainee_name or ''}".encode("utf-8")).hexdigest()[:16]
    llm_guest_enabled = _llm_guest_requested(use_llm_guest)
    active_learning_versions = _active_learning_versions_for_scenario(scenario["id"])
    public_scenario = _public_scenario(scenario, active_learning_versions=active_learning_versions)
    retrieved_context = retrieve_staff_training_context(
        scenario["id"],
        trainee_name=trainee_name,
        assignment_id=assignment_id,
    )
    agent_contract = _staff_training_agent_contract()
    session = {
        "id": session_id,
        "status": "active",
        "mode": "staff_roleplay_session",
        "scenario_id": scenario["id"],
        "scenario": public_scenario,
        "active_learning_versions": active_learning_versions,
        "active_learning_version_ids": [str(item.get("version_id") or "") for item in active_learning_versions if item.get("version_id")],
        "learning_version_guidance": _learning_version_guidance(active_learning_versions),
        "retrieved_training_context": retrieved_context,
        "agent_contract": agent_contract,
        "agent_tool_manifest": agent_contract["tool_manifest"],
        "tool_trace": [],
        "trainee_name": str(trainee_name or "Seasonal staff trainee")[:80],
        "assignment_id": str(assignment_id or "")[:80] or None,
        "retry_of_session_id": str(retry_of_session_id or "")[:80] or None,
        "started_at": _now_iso(),
        "updated_at": _now_iso(),
        "turn_count": 0,
        "transcript": [{"speaker": "guest", "message": scenario["opening_message"], "at": _now_iso()}],
        "scores": [],
        "scorecard": _empty_scorecard(),
        "critical_miss": False,
        "guest_simulator": {
            "mode": "llm_guest_with_deterministic_scoring" if llm_guest_enabled else "deterministic_guest",
            "llm_requested": llm_guest_enabled,
            "llm_controls_score": False,
            "fallback": "deterministic_guest_reply",
        },
        "mastery_tracker": _empty_mastery_tracker(),
        "completed_objectives": [],
        "missing_objectives": list(scenario["objectives"]),
        "boundary": "Training simulator only; no live dispatch, guest PII, reward labels, or policy promotion authority.",
    }
    session["tool_trace"] = _staff_training_tool_trace(session, "start")
    _SESSIONS[session_id] = session
    _persist_staff_training_session(session)
    _write_jsonl({"event": "session_started", **_session_event_snapshot(session)})
    return _session_response(session)


def advance_staff_training_turn(session_id: str, employee_message: str, use_llm_guest: bool | None = None, use_shadow_eval: bool | None = None) -> dict[str, Any]:
    session = _get_staff_training_session(str(session_id or ""))
    if not session:
        return {"status": "not_found", "mode": "staff_roleplay_turn", "readiness_issues": ["Training session was not found or has expired. Start a new session."]}
    if session.get("status") != "active":
        return {"status": "closed", "mode": "staff_roleplay_turn", "session": _session_response(session)}

    scenario = SCENARIOS[session["scenario_id"]]
    message = str(employee_message or "").strip()
    if not message:
        return {"status": "invalid", "mode": "staff_roleplay_turn", "readiness_issues": ["Employee message is required."]}

    session["turn_count"] = int(session.get("turn_count") or 0) + 1
    employee_turn = {"speaker": "employee", "message": message[:2000], "at": _now_iso()}
    session["transcript"].append(employee_turn)
    score = _score_employee_message(scenario, message, session["turn_count"])
    session["scores"].append(score)
    session["scorecard"] = _aggregate_scorecard(session["scores"])
    session["critical_miss"] = bool(session.get("critical_miss") or score.get("critical_miss"))
    completed, missing = _objective_progress(scenario, session["transcript"])
    session["completed_objectives"] = completed
    session["missing_objectives"] = missing
    session["mastery_tracker"] = _update_mastery_tracker(session.get("mastery_tracker"), score, session["turn_count"])

    fallback_reply = _guest_reply(scenario, score, missing, session["turn_count"])
    llm_guest_requested = _llm_guest_requested(use_llm_guest, session)
    guest_generation = (
        _generate_llm_guest_reply(scenario, session, message, score, missing, fallback_reply)
        if llm_guest_requested
        else {"status": "not_requested", "source": "deterministic", "reply": fallback_reply}
    )
    guest_reply = str(guest_generation.get("reply") or fallback_reply)
    session["guest_simulator"] = {
        "mode": "llm_guest_with_deterministic_scoring" if llm_guest_requested else "deterministic_guest",
        "llm_requested": llm_guest_requested,
        "llm_status": guest_generation.get("status"),
        "llm_controls_score": False,
        "fallback": "deterministic_guest_reply",
        "source": guest_generation.get("source"),
        "model": guest_generation.get("model"),
    }
    session["transcript"].append({"speaker": "guest", "message": guest_reply, "at": _now_iso(), "source": guest_generation.get("source")})
    session["updated_at"] = _now_iso()
    if session["turn_count"] >= 4 or (not missing and not session["critical_miss"]):
        session["status"] = "ready_to_finish"
    shadow_eval = _generate_shadow_evaluator(scenario, session, message, score) if use_shadow_eval else {"status": "not_requested", "score_authority": False}
    tool_trace = _staff_training_tool_trace(session, "turn", score=score, guest_generation=guest_generation, shadow_eval=shadow_eval if use_shadow_eval else None)
    session["tool_trace"] = tool_trace

    payload = {
        "status": "complete",
        "mode": "staff_roleplay_turn",
        "session": _session_response(session),
        "guest_reply": guest_reply,
        "turn_score": score,
        "coaching_notes": score["coaching_notes"],
        "critical_miss": score["critical_miss"],
        "guest_reply_source": guest_generation.get("source"),
        "llm_guest": {key: value for key, value in guest_generation.items() if key != "reply"},
        "mastery_tracker": session.get("mastery_tracker"),
        "shadow_evaluator": shadow_eval,
        "tool_trace": tool_trace,
    }
    _SESSIONS[str(session["id"])] = session
    _persist_staff_training_session(session)
    _write_jsonl({"event": "turn_scored", "turn_score": score, **_session_event_snapshot(session)})
    return payload


def finish_staff_training_session(session_id: str) -> dict[str, Any]:
    session = _get_staff_training_session(str(session_id or ""))
    if not session:
        return {"status": "not_found", "mode": "staff_roleplay_finish", "readiness_issues": ["Training session was not found or has expired."]}
    session["status"] = "finished"
    session["finished_at"] = _now_iso()
    session["updated_at"] = _now_iso()
    debrief = _debrief(session)
    session["debrief"] = debrief
    try:
        from product_learning_loop import record_training_gap_from_staff_session

        session["training_gap_ticket"] = record_training_gap_from_staff_session(session)
    except Exception as error:
        session["training_gap_ticket"] = {"status": "error", "readiness_issues": [str(error)[:240]], "live_ops_authority": False}
    try:
        from product_learning_loop import record_learning_version_outcome_from_staff_session

        session["learning_version_outcome"] = record_learning_version_outcome_from_staff_session(session)
    except Exception as error:
        session["learning_version_outcome"] = {"status": "error", "readiness_issues": [str(error)[:240]], "live_ops_authority": False}
    _SESSIONS[str(session["id"])] = session
    _persist_staff_training_session(session)
    _write_jsonl({"event": "session_finished", "debrief": debrief, **_session_event_snapshot(session)})
    return {
        "status": "complete",
        "mode": "staff_roleplay_finish",
        "session": _session_response(session),
        "debrief": debrief,
        "training_gap_ticket": session.get("training_gap_ticket"),
        "learning_version_outcome": session.get("learning_version_outcome"),
    }


def staff_training_analytics(limit: int = 200) -> dict[str, Any]:
    rows = [row for row in _read_jsonl(limit=limit) if row.get("event") == "session_finished"]
    if not rows:
        return {
            "status": "empty",
            "mode": "staff_roleplay_analytics",
            "session_count": 0,
            "scenario_summary": [],
            "weakest_dimensions": [],
            "boundary": "Analytics summarize simulated training sessions only.",
            "uses_generated_data": True,
            "feeds_actual_reward_model": False,
        }
    by_scenario: dict[str, list[dict[str, Any]]] = {}
    dimension_totals = {dimension: [] for dimension in RUBRIC_DIMENSIONS}
    for row in rows:
        by_scenario.setdefault(str(row.get("scenario_id") or "unknown"), []).append(row)
        scorecard = row.get("scorecard", {}) if isinstance(row.get("scorecard"), dict) else {}
        dimensions = scorecard.get("dimensions", {}) if isinstance(scorecard.get("dimensions"), dict) else {}
        for dimension in RUBRIC_DIMENSIONS:
            value = dimensions.get(dimension)
            if isinstance(value, (int, float)):
                dimension_totals[dimension].append(float(value))

    scenario_summary = []
    for scenario_id, scenario_rows in sorted(by_scenario.items()):
        totals = [float(row.get("scorecard", {}).get("overall", 0)) for row in scenario_rows if isinstance(row.get("scorecard"), dict)]
        scenario_summary.append(
            {
                "scenario_id": scenario_id,
                "title": SCENARIOS.get(scenario_id, {}).get("title", scenario_id.replace("_", " ")),
                "session_count": len(scenario_rows),
                "average_overall": round(sum(totals) / max(1, len(totals)), 1),
                "critical_miss_count": sum(1 for row in scenario_rows if row.get("critical_miss")),
            }
        )
    weakest = sorted(
        (
            {"dimension": dimension, "average": round(sum(values) / max(1, len(values)), 1)}
            for dimension, values in dimension_totals.items()
            if values
        ),
        key=lambda item: item["average"],
    )[:4]
    return {
        "status": "ready",
        "mode": "staff_roleplay_analytics",
        "session_count": len(rows),
        "scenario_summary": scenario_summary,
        "weakest_dimensions": weakest,
        "recent_sessions": rows[-8:],
        "boundary": "Analytics summarize simulated training sessions only; they do not create live operations labels.",
        "uses_generated_data": True,
        "feeds_actual_reward_model": False,
    }


def staff_training_golden_eval() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    scenario_summary: dict[str, dict[str, Any]] = {}
    label_summary: dict[str, dict[str, Any]] = {}
    for scenario_id, examples in STAFF_TRAINING_GOLDEN_RESPONSES.items():
        scenario = SCENARIOS.get(scenario_id)
        if not scenario:
            continue
        scenario_summary.setdefault(
            scenario_id,
            {"scenario_id": scenario_id, "title": scenario.get("title", scenario_id), "case_count": 0, "pass_count": 0, "fail_count": 0},
        )
        for example in examples:
            label = str(example.get("label") or "unknown")
            label_summary.setdefault(label, {"label": label, "case_count": 0, "pass_count": 0, "fail_count": 0})
            score = _score_employee_message(scenario, str(example.get("message") or ""), 1)
            overall = int(score.get("overall") or 0)
            expected_min = example.get("min_score")
            expected_max = example.get("max_score")
            expected_critical = example.get("critical_miss")
            failures: list[str] = []
            if isinstance(expected_min, int) and overall < expected_min:
                failures.append(f"overall {overall} below min {expected_min}")
            if isinstance(expected_max, int) and overall > expected_max:
                failures.append(f"overall {overall} above max {expected_max}")
            if expected_critical is not None and bool(score.get("critical_miss")) != bool(expected_critical):
                failures.append(f"critical_miss {bool(score.get('critical_miss'))} expected {bool(expected_critical)}")
            expected_verdicts = {
                "excellent": {"passing", "strong"},
                "passing": {"passing", "strong"},
                "partial": {"critical_miss", "needs_coaching", "passing"},
                "bad": {"critical_miss", "needs_coaching"},
            }.get(label, set())
            verdict = str((score.get("turn_coaching") or {}).get("verdict") or "")
            if expected_verdicts and verdict not in expected_verdicts:
                failures.append(f"verdict {verdict or 'missing'} not in {sorted(expected_verdicts)}")

            passed = not failures
            rows.append(
                {
                    "id": example.get("id"),
                    "scenario_id": scenario_id,
                    "scenario_title": scenario.get("title", scenario_id),
                    "label": label,
                    "status": "pass" if passed else "fail",
                    "overall": overall,
                    "expected_min": expected_min,
                    "expected_max": expected_max,
                    "verdict": verdict,
                    "critical_miss": bool(score.get("critical_miss")),
                    "failures": failures,
                    "weak_dimensions": (score.get("turn_coaching") or {}).get("weak_dimensions", []),
                    "message": str(example.get("message") or "")[:500],
                }
            )
            scenario_summary[scenario_id]["case_count"] += 1
            scenario_summary[scenario_id]["pass_count"] += 1 if passed else 0
            scenario_summary[scenario_id]["fail_count"] += 0 if passed else 1
            label_summary[label]["case_count"] += 1
            label_summary[label]["pass_count"] += 1 if passed else 0
            label_summary[label]["fail_count"] += 0 if passed else 1

    fail_count = sum(1 for row in rows if row["status"] == "fail")
    return {
        "status": "pass" if fail_count == 0 else "fail",
        "mode": "staff_roleplay_golden_eval",
        "case_count": len(rows),
        "pass_count": len(rows) - fail_count,
        "fail_count": fail_count,
        "scenario_count": len(scenario_summary),
        "scenario_summary": sorted(scenario_summary.values(), key=lambda item: str(item.get("scenario_id") or "")),
        "label_summary": sorted(label_summary.values(), key=lambda item: str(item.get("label") or "")),
        "failures": [row for row in rows if row["status"] == "fail"],
        "cases": rows,
        "scoring_contract": {
            "authority": "deterministic_policy_and_safety_rubric",
            "llm_controls_score": False,
            "golden_cases_source": "hand-authored staff-training calibration fixtures",
        },
        "boundary": "Golden eval validates simulated training scoring only; it does not dispatch live work or create actual reward labels.",
        "uses_generated_data": True,
        "feeds_actual_reward_model": False,
    }


def _normalize_staff_role(value: str | None) -> str:
    role = str(value or "guest_services").strip().lower().replace("-", "_").replace(" ", "_")
    return role if role in STAFF_ROLE_ASSIGNMENT_SCENARIOS else "guest_services"


def _role_templates() -> list[dict[str, Any]]:
    return [
        {
            "staff_role": role,
            "scenario_ids": scenario_ids,
            "scenarios": [_public_scenario(SCENARIOS[item]) for item in scenario_ids if item in SCENARIOS],
        }
        for role, scenario_ids in STAFF_ROLE_ASSIGNMENT_SCENARIOS.items()
    ]


def _assignment_response(row: dict[str, Any]) -> dict[str, Any]:
    scenario_ids = [item for item in row.get("scenario_ids", []) if item in SCENARIOS] if isinstance(row.get("scenario_ids"), list) else []
    return {
        "id": row.get("assignment_id") or row.get("id"),
        "trainee_name": row.get("trainee_name") or "Seasonal staff trainee",
        "staff_role": _normalize_staff_role(str(row.get("staff_role") or "")),
        "scenario_ids": scenario_ids,
        "scenarios": [_public_scenario(SCENARIOS[item]) for item in scenario_ids],
        "assigned_by": row.get("assigned_by") or "ParkPulse manager",
        "status": row.get("status") or "assigned",
        "created_at": row.get("created_at"),
        "source": row.get("source") or "role_default",
        "source_signals": row.get("source_signals") if isinstance(row.get("source_signals"), list) else [],
        "boundary": row.get("boundary") or "Training assignment only.",
    }


def _find_assignment(assignments: list[dict[str, Any]], assignment_id: str | None = None, trainee_name: str | None = None) -> dict[str, Any] | None:
    assignment_key = str(assignment_id or "").strip()
    trainee_key = str(trainee_name or "").strip().lower()
    for assignment in reversed(assignments):
        if assignment_key and str(assignment.get("id") or "") == assignment_key:
            return assignment
        if trainee_key and str(assignment.get("trainee_name") or "").strip().lower() == trainee_key:
            return assignment
    return None


def _packet_next_actions(assignment: dict[str, Any], readiness: dict[str, Any], receipts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if readiness.get("status") == "ready_for_shadowing":
        actions.append({"type": "manager_signoff", "label": "Manager may sign off for live shadowing.", "severity": "ready"})
        return actions

    missing = [item for item in readiness.get("required_scenarios", []) if item not in readiness.get("completed_scenarios", []) and item not in readiness.get("needs_retry_scenarios", [])]
    for scenario_id in readiness.get("needs_retry_scenarios", []) or []:
        scenario = SCENARIOS.get(str(scenario_id) or "")
        actions.append(
            {
                "type": "retry_scenario",
                "scenario_id": scenario_id,
                "label": f"Retry {scenario.get('title') if scenario else str(scenario_id).replace('_', ' ')} before live shadowing.",
                "severity": "hold",
            }
        )
    for scenario_id in missing:
        scenario = SCENARIOS.get(str(scenario_id) or "")
        actions.append(
            {
                "type": "complete_scenario",
                "scenario_id": scenario_id,
                "label": f"Complete {scenario.get('title') if scenario else str(scenario_id).replace('_', ' ')}.",
                "severity": "pending",
            }
        )
    if any(str(receipt.get("review_status") or "") == "pending_review" for receipt in receipts):
        actions.append({"type": "manager_review", "label": "Review pending receipts before signoff.", "severity": "review"})
    return actions or [{"type": "start_assignment", "label": f"Start training for {assignment.get('trainee_name')}.", "severity": "pending"}]


def _receipt_id(session_id: str) -> str:
    return "receipt-" + hashlib.sha1(str(session_id or "").encode("utf-8")).hexdigest()[:14]


def _review_response(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "id": row.get("review_id") or row.get("id"),
        "receipt_id": row.get("receipt_id"),
        "session_id": row.get("session_id"),
        "assignment_id": row.get("assignment_id"),
        "decision": row.get("decision"),
        "reviewer": row.get("reviewer"),
        "notes": row.get("notes") or "",
        "created_at": row.get("created_at"),
        "boundary": row.get("boundary") or "Manager review disposition only.",
    }


def _latest_reviews_by_session(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    reviews: dict[str, dict[str, Any]] = {}
    for row in events:
        if row.get("event") == "receipt_reviewed":
            session_id = str(row.get("session_id") or "")
            if session_id:
                reviews[session_id] = row
    return reviews


def _find_receipt_target(finished: list[dict[str, Any]], session_id: str | None = None, receipt_id: str | None = None) -> dict[str, Any] | None:
    session_key = str(session_id or "").strip()
    receipt_key = str(receipt_id or "").strip()
    for row in reversed(finished):
        row_session_id = str(row.get("id") or row.get("session_id") or "")
        if session_key and row_session_id == session_key:
            return row
        if receipt_key and _receipt_id(row_session_id) == receipt_key:
            return row
    return None


def _receipt_response(row: dict[str, Any], latest_review: dict[str, Any] | None = None) -> dict[str, Any]:
    scorecard = row.get("scorecard", {}) if isinstance(row.get("scorecard"), dict) else {}
    debrief = row.get("debrief", {}) if isinstance(row.get("debrief"), dict) else {}
    session_id = str(row.get("id") or row.get("session_id") or "")
    scenario_id = str(row.get("scenario_id") or "")
    manager_review_required = bool(row.get("critical_miss") or float(scorecard.get("overall") or 0) < 75)
    review = _review_response(latest_review)
    return {
        "id": _receipt_id(session_id),
        "session_id": session_id,
        "assignment_id": row.get("assignment_id"),
        "retry_of_session_id": row.get("retry_of_session_id"),
        "trainee_name": row.get("trainee_name") or "Seasonal staff trainee",
        "staff_role": row.get("staff_role"),
        "scenario_id": scenario_id,
        "scenario_title": SCENARIOS.get(scenario_id, {}).get("title", scenario_id.replace("_", " ")),
        "finished_at": row.get("finished_at") or row.get("created_at"),
        "overall": scorecard.get("overall", 0),
        "critical_miss": bool(row.get("critical_miss")),
        "result": debrief.get("result") or ("coach_and_retry" if row.get("critical_miss") else "pass"),
        "summary": debrief.get("summary") or "",
        "recommended_retry": debrief.get("recommended_retry"),
        "manager_review_required": manager_review_required,
        "manager_review": review,
        "review_status": review.get("decision") if review else ("pending_review" if manager_review_required else "not_required"),
        "transcript_turn_count": row.get("turn_count", 0),
        "boundary": "Training receipt only; not a live operations action or reward label.",
    }


def _readiness_by_assignment(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    assignments = [_assignment_response(row) for row in events if row.get("event") == "assignment_created"]
    finished = [row for row in events if row.get("event") == "session_finished"]
    reviews = _latest_reviews_by_session(events)
    result: dict[str, dict[str, Any]] = {}
    for assignment in assignments:
        assignment_id = str(assignment.get("id") or "")
        receipts = [row for row in finished if str(row.get("assignment_id") or "") == assignment_id]
        result[assignment_id] = _assignment_readiness(assignment, receipts, reviews)
    return result


def _assignment_readiness(assignment: dict[str, Any], receipts: list[dict[str, Any]], reviews: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    reviews = reviews or {}
    required = [item for item in assignment.get("scenario_ids", []) if item in SCENARIOS]
    latest_by_scenario: dict[str, dict[str, Any]] = {}
    for receipt in receipts:
        scenario_id = str(receipt.get("scenario_id") or "")
        if scenario_id in required:
            latest_by_scenario[scenario_id] = receipt
    completed = []
    needs_retry = []
    critical_miss_count = 0
    review_hold_count = 0
    scores = []
    for scenario_id in required:
        receipt = latest_by_scenario.get(scenario_id)
        if not receipt:
            continue
        scorecard = receipt.get("scorecard", {}) if isinstance(receipt.get("scorecard"), dict) else {}
        overall = float(scorecard.get("overall") or 0)
        critical = bool(receipt.get("critical_miss"))
        session_id = str(receipt.get("id") or receipt.get("session_id") or "")
        review_decision = str((reviews.get(session_id) or {}).get("decision") or "")
        critical_miss_count += 1 if critical else 0
        review_hold_count += 1 if review_decision in {"require_retry", "hold"} else 0
        scores.append(overall)
        if overall >= 75 and not critical and review_decision not in {"require_retry", "hold"}:
            completed.append(scenario_id)
        else:
            needs_retry.append(scenario_id)
    if not latest_by_scenario:
        status = "not_started"
    elif needs_retry:
        status = "needs_coaching"
    elif len(completed) >= len(required):
        status = "ready_for_shadowing"
    else:
        status = "in_progress"
    return {
        "assignment_id": assignment.get("id"),
        "trainee_name": assignment.get("trainee_name"),
        "staff_role": assignment.get("staff_role"),
        "status": status,
        "required_count": len(required),
        "completed_count": len(completed),
        "required_scenarios": required,
        "completed_scenarios": completed,
        "needs_retry_scenarios": needs_retry,
        "last_score": round(scores[-1], 1) if scores else None,
        "average_score": round(sum(scores) / max(1, len(scores)), 1) if scores else None,
        "critical_miss_count": critical_miss_count,
        "review_hold_count": review_hold_count,
        "live_shadowing_gate": "pass" if status == "ready_for_shadowing" else "hold",
    }


def _demo_finished_session(item: dict[str, Any], assignment: dict[str, Any]) -> dict[str, Any]:
    scenario_id = str(item.get("scenario_id") or "")
    scenario = SCENARIOS[scenario_id]
    session_id = "staff-demo-" + hashlib.sha1(f"{assignment.get('id')}:{scenario_id}".encode("utf-8")).hexdigest()[:14]
    scorecard = item.get("scorecard", _empty_scorecard())
    critical_miss = bool(item.get("critical_miss"))
    debrief = {
        "result": "coach_and_retry" if critical_miss or float(scorecard.get("overall") or 0) < 75 else "pass",
        "summary": "Ready for live shadowing." if not critical_miss and float(scorecard.get("overall") or 0) >= 75 else "Needs another roleplay pass before live shadowing.",
        "overall": scorecard.get("overall", 0),
        "weakest_dimensions": [],
        "completed_objectives": scenario.get("objectives", []) if not critical_miss else scenario.get("objectives", [])[:2],
        "missing_objectives": [] if not critical_miss else scenario.get("objectives", [])[2:],
        "critical_miss": critical_miss,
        "recommended_retry": scenario_id if critical_miss or float(scorecard.get("overall") or 0) < 75 else None,
    }
    return {
        "event": "session_finished",
        "id": session_id,
        "assignment_id": assignment.get("id"),
        "trainee_name": item.get("trainee_name"),
        "staff_role": item.get("staff_role"),
        "scenario_id": scenario_id,
        "status": "finished",
        "turn_count": scorecard.get("turn_count", 2),
        "scorecard": scorecard,
        "critical_miss": critical_miss,
        "completed_objectives": debrief["completed_objectives"],
        "missing_objectives": debrief["missing_objectives"],
        "debrief": debrief,
        "finished_at": _now_iso(),
        "created_at": _now_iso(),
    }


def _empty_scorecard() -> dict[str, Any]:
    return {"overall": 0, "dimensions": {dimension: 0 for dimension in RUBRIC_DIMENSIONS}, "turn_count": 0}


def _contains_any(text: str, terms: list[str] | tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _group_hits(text: str, groups: list[list[str]]) -> tuple[int, list[str]]:
    hits = 0
    missing: list[str] = []
    for group in groups:
        if any(term in text for term in group):
            hits += 1
        else:
            missing.append(" or ".join(group[:2]))
    return hits, missing


def _scale(hits: int, total: int, base: int = 1) -> int:
    if total <= 0:
        return 3
    return max(1, min(5, base + round((hits / total) * (5 - base))))


def _score_employee_message(scenario: dict[str, Any], message: str, turn_count: int) -> dict[str, Any]:
    text = f" {message.lower()} "
    policy_hits, missing_policy = _group_hits(text, scenario.get("policy_keywords", []))
    safety_hits, missing_safety = _group_hits(text, scenario.get("safety_keywords", []))
    escalation_hits, missing_escalation = _group_hits(text, scenario.get("escalation_keywords", []))
    rude = _contains_any(text, _RUDE_TERMS) or _contains_any(text, tuple(scenario.get("prohibited_terms", [])))

    dimensions = {
        "empathy": max(1, min(5, 2 + sum(1 for term in _EMPATHY_TERMS if term in text))) if not rude else 1,
        "policy_correctness": _scale(policy_hits, len(scenario.get("policy_keywords", []))),
        "escalation_decision": _scale(escalation_hits, len(scenario.get("escalation_keywords", []))),
        "clarity": max(1, min(5, 2 + sum(1 for term in _CLARITY_TERMS if term in text))),
        "safety_awareness": _scale(safety_hits, len(scenario.get("safety_keywords", [])), base=1 if scenario.get("difficulty") == "critical" else 2),
        "de_escalation": max(1, min(5, 2 + sum(1 for term in _DEESCALATION_TERMS if term in text))) if not rude else 1,
        "brand_tone": 4 if not rude else 1,
    }
    if len(message.split()) < 7:
        dimensions["clarity"] = min(dimensions["clarity"], 2)
        dimensions["empathy"] = min(dimensions["empathy"], 2)
    fatal_after = int(scenario.get("fatal_if_missing_after_turn") or 99)
    critical_miss = rude or (turn_count >= fatal_after and escalation_hits == 0 and scenario.get("difficulty") == "critical")
    if critical_miss:
        dimensions["safety_awareness"] = min(dimensions["safety_awareness"], 2)
        dimensions["escalation_decision"] = min(dimensions["escalation_decision"], 2)
        dimensions["policy_correctness"] = min(dimensions["policy_correctness"], 2)

    overall = round(sum(dimensions.values()) / len(dimensions) * 20)
    if critical_miss:
        overall = min(overall, 55)
    coaching_notes = _coaching_notes(missing_policy, missing_safety, missing_escalation, rude, critical_miss)
    turn_coaching = _turn_coaching(
        scenario,
        dimensions,
        overall,
        missing_policy,
        missing_safety,
        missing_escalation,
        rude,
        critical_miss,
    )
    return {
        "overall": overall,
        "dimensions": dimensions,
        "missing_policy_signals": missing_policy[:3],
        "missing_safety_signals": missing_safety[:3],
        "missing_escalation_signals": missing_escalation[:2],
        "critical_miss": critical_miss,
        "coaching_notes": coaching_notes,
        "turn_coaching": turn_coaching,
    }


def _dimension_label(dimension: str) -> str:
    return dimension.replace("_", " ").title()


def _humanize_signal(signal: str) -> str:
    cleaned = str(signal or "").replace(" or ", " / ").strip()
    return cleaned[:1].upper() + cleaned[1:]


def _turn_coaching(
    scenario: dict[str, Any],
    dimensions: dict[str, int],
    overall: int,
    missing_policy: list[str],
    missing_safety: list[str],
    missing_escalation: list[str],
    rude: bool,
    critical_miss: bool,
) -> dict[str, Any]:
    weak_dimensions = [
        {"dimension": key, "label": _dimension_label(key), "score": value}
        for key, value in sorted(dimensions.items(), key=lambda item: item[1])
        if value <= 3
    ][:3]
    strengths = [
        _dimension_label(key)
        for key, value in sorted(dimensions.items(), key=lambda item: item[1], reverse=True)
        if value >= 4
    ][:3]
    misses: list[dict[str, str]] = []
    if rude:
        misses.append({"type": "tone", "label": "Tone became dismissive or adversarial."})
    for signal in missing_escalation[:1]:
        misses.append({"type": "escalation", "label": f"Name the escalation path: {_humanize_signal(signal)}."})
    for signal in missing_safety[:2]:
        misses.append({"type": "safety", "label": f"Make the safety action explicit: {_humanize_signal(signal)}."})
    for signal in missing_policy[:2]:
        misses.append({"type": "policy", "label": f"Add the policy detail: {_humanize_signal(signal)}."})

    if critical_miss:
        verdict = "critical_miss"
        headline = "Critical miss: safety or escalation was not explicit enough."
        priority = "Stop and retry this scenario before shadowing."
    elif overall >= 85 and not misses:
        verdict = "strong"
        headline = "Strong response: the guest heard empathy, policy, and a next step."
        priority = "Continue the conversation and keep the same structure."
    elif overall >= 75:
        verdict = "passing"
        headline = "Passing response, but tighten the missing step before finishing."
        priority = "Use the next reply to close the most important gap."
    else:
        verdict = "needs_coaching"
        headline = "Needs coaching: the response did not make the next safe action clear enough."
        priority = "Repair the response with a concrete action and escalation path."

    if not strengths:
        strengths = ["Clear intent to respond"] if overall >= 55 else []
    if not misses and verdict == "strong":
        misses = [{"type": "none", "label": "No major scoring gap on this turn."}]

    return {
        "verdict": verdict,
        "headline": headline,
        "priority": priority,
        "strengths": strengths,
        "misses": misses[:5],
        "weak_dimensions": weak_dimensions,
        "next_response": NEXT_RESPONSE_TEMPLATES.get(str(scenario.get("id") or ""), ""),
        "scoring_basis": "Deterministic rubric: empathy, policy correctness, escalation, clarity, safety, de-escalation, and brand tone.",
    }


def _empty_mastery_tracker() -> dict[str, Any]:
    return {
        "status": "not_started",
        "mastery_level": "not_started",
        "turn_count": 0,
        "open_gaps": [],
        "repaired_gaps": [],
        "latest_repairs": [],
        "repair_count": 0,
        "unrepaired_critical_count": 0,
        "summary": "No scored turns yet.",
        "boundary": "Mastery tracks simulated training repairs only; it does not authorize live work.",
    }


def _gap_key(kind: str, signal: str) -> str:
    return f"{kind}:{' '.join(str(signal or '').lower().split())}"


def _score_gap_entries(score: dict[str, Any], turn_count: int) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    sources = [
        ("policy", score.get("missing_policy_signals", []), "policy detail"),
        ("safety", score.get("missing_safety_signals", []), "safety action"),
        ("escalation", score.get("missing_escalation_signals", []), "escalation path"),
    ]
    for kind, signals, label_prefix in sources:
        for signal in signals if isinstance(signals, list) else []:
            signal_text = str(signal or "").strip()
            if not signal_text:
                continue
            severity = "critical" if kind in {"safety", "escalation"} and bool(score.get("critical_miss")) else "coaching"
            entries.append(
                {
                    "key": _gap_key(kind, signal_text),
                    "type": kind,
                    "label": f"Missing {label_prefix}: {_humanize_signal(signal_text)}.",
                    "signal": signal_text,
                    "severity": severity,
                    "first_seen_turn": turn_count,
                    "last_seen_turn": turn_count,
                }
            )
    if bool(score.get("critical_miss")) and not any(entry["severity"] == "critical" for entry in entries):
        entries.append(
            {
                "key": f"critical_miss:turn_{turn_count}",
                "type": "critical_miss",
                "label": "Critical miss remained unresolved on this turn.",
                "signal": "critical miss",
                "severity": "critical",
                "first_seen_turn": turn_count,
                "last_seen_turn": turn_count,
            }
        )
    return entries


def _update_mastery_tracker(previous: dict[str, Any] | None, score: dict[str, Any], turn_count: int) -> dict[str, Any]:
    prior = previous if isinstance(previous, dict) else _empty_mastery_tracker()
    prior_open = {str(item.get("key")): item for item in prior.get("open_gaps", []) if isinstance(item, dict) and item.get("key")}
    current_entries = {entry["key"]: entry for entry in _score_gap_entries(score, turn_count)}
    repaired = [dict(item, repaired_at_turn=turn_count) for key, item in prior_open.items() if key not in current_entries]
    repaired_gaps = [item for item in prior.get("repaired_gaps", []) if isinstance(item, dict)] + repaired
    open_gaps = []
    for key, entry in current_entries.items():
        original = prior_open.get(key)
        if original:
            entry["first_seen_turn"] = original.get("first_seen_turn", entry["first_seen_turn"])
        open_gaps.append(entry)

    unrepaired_critical = sum(1 for item in open_gaps if item.get("severity") == "critical")
    if not open_gaps and repaired_gaps:
        level = "repaired"
        summary = "Previous misses were repaired; continue holding the standard through the scenario."
    elif not open_gaps:
        level = "on_track"
        summary = "No open scoring gaps on the latest turn."
    elif unrepaired_critical:
        level = "blocked"
        summary = "Critical safety or escalation gaps remain open; retry before live shadowing."
    elif repaired:
        level = "repairing"
        summary = "Some earlier gaps were repaired, but coaching gaps remain open."
    else:
        level = "needs_practice"
        summary = "Coaching gaps remain open on the latest turn."
    return {
        "status": "ready",
        "mastery_level": level,
        "turn_count": turn_count,
        "open_gaps": open_gaps,
        "repaired_gaps": repaired_gaps[-12:],
        "latest_repairs": repaired,
        "repair_count": len(repaired_gaps),
        "unrepaired_critical_count": unrepaired_critical,
        "summary": summary,
        "boundary": "Mastery tracks simulated training repairs only; it does not authorize live work.",
    }


def _coaching_notes(missing_policy: list[str], missing_safety: list[str], missing_escalation: list[str], rude: bool, critical_miss: bool) -> list[str]:
    notes: list[str] = []
    if rude:
        notes.append("Avoid dismissive or adversarial wording; keep the guest's dignity intact.")
    if missing_escalation:
        notes.append(f"Name the escalation path explicitly: {missing_escalation[0]}.")
    if missing_safety:
        notes.append(f"Make the safety step concrete: {missing_safety[0]}.")
    if missing_policy:
        notes.append(f"Add the missing policy detail: {missing_policy[0]}.")
    if critical_miss:
        notes.append("Critical miss: safety or escalation cannot be implied in this scenario.")
    if not notes:
        notes.append("Strong turn: empathy, policy, and next step were visible.")
    return notes[:4]


def _objective_progress(scenario: dict[str, Any], transcript: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    employee_text = " ".join(str(turn.get("message") or "").lower() for turn in transcript if turn.get("speaker") == "employee")
    groups = scenario.get("policy_keywords", [])
    completed: list[str] = []
    missing: list[str] = []
    for idx, objective in enumerate(scenario.get("objectives", [])):
        group = groups[min(idx, len(groups) - 1)] if groups else []
        if group and any(term in employee_text for term in group):
            completed.append(objective)
        else:
            missing.append(objective)
    return completed, missing


def _guest_reply(scenario: dict[str, Any], score: dict[str, Any], missing: list[str], turn_count: int) -> str:
    followups = scenario.get("guest_followups", [])
    if score.get("critical_miss"):
        scenario_id = str(scenario.get("id") or "")
        critical_replies = {
            "lost_child_report": "No. I need you to call Security now and keep me here while they start looking. I cannot just wander around by myself.",
            "heat_exhaustion_concern": "She might faint. Please call medical now. I do not want to walk her across the park if that could make this worse.",
            "safety_rule_refusal": "So are you starting the ride or not? If this is really a safety rule, get your lead here and explain it clearly.",
            "line_cutting_conflict": "If you will not step in, this is going to turn into a fight. I need a lead or Security here.",
            "weather_evacuation_confusion": "We need a specific shelter route now. We have a stroller and cannot just follow a crowd in a storm.",
        }
        return critical_replies.get(scenario_id, "That does not feel safe or helpful. I need someone responsible involved right now.")
    if score.get("overall", 0) >= 82 and not missing:
        return "Okay. That is clear, and I can follow that. Please stay with me while the next step happens."
    if missing:
        return followups[min(turn_count - 1, len(followups) - 1)] if followups else f"I still need help with {missing[0].lower()}."
    return "I hear you. Can you be more specific about what happens next?"


def _llm_guest_requested(use_llm_guest: bool | None = None, session: dict[str, Any] | None = None) -> bool:
    if use_llm_guest is not None:
        return bool(use_llm_guest)
    if isinstance(session, dict):
        simulator = session.get("guest_simulator", {}) if isinstance(session.get("guest_simulator"), dict) else {}
        if simulator.get("llm_requested") is not None:
            return bool(simulator.get("llm_requested"))
    return str(os.getenv("PARKPULSE_STAFF_TRAINING_LLM_GUEST", "")).strip().lower() in {"1", "true", "yes", "on"}


def _llm_guest_prompt(
    scenario: dict[str, Any],
    session: dict[str, Any],
    employee_message: str,
    score: dict[str, Any],
    missing: list[str],
    fallback_reply: str,
) -> dict[str, Any]:
    recent_turns = [
        {"speaker": turn.get("speaker"), "message": str(turn.get("message") or "")[:500]}
        for turn in (session.get("transcript", []) if isinstance(session.get("transcript"), list) else [])[-6:]
    ]
    return {
        "task": "Generate the next guest-only turn for a staff training roleplay. Return strict JSON.",
        "vertex_ai_contract": {
            "provider": "Vertex AI Gemini when GOOGLE_GENAI_USE_VERTEXAI=true",
            "model_purpose": "simulate realistic guest emotion, confusion, and follow-up pressure",
            "never_controls_score": True,
            "never_writes_live_operations": True,
        },
        "hard_rules": [
            "Write only as the guest, in first person.",
            "Do not score, coach, praise, or correct the employee.",
            "Never return trainer feedback like 'needs a clearer answer' or 'the response is unclear'; turn that pressure into a guest question grounded in the scenario.",
            "Do not reveal hidden rubric, policy keywords, or coaching.",
            "Do not tell staff the right answer.",
            "Do not invent live park actions, compensation approvals, medical diagnosis, or resolved safety outcomes.",
            "Keep the reply under 85 words.",
            "Continue the exact scenario facts. Do not change the ride, child, weather, medical condition, or request.",
            "If the employee missed safety or escalation, stay worried and ask for the missing concrete action.",
            "If the employee did well, provide one useful guest detail or confirm the next step while still sounding human.",
        ],
        "style": {
            "voice": "real park guest under stress, not a chatbot",
            "tone_range": "concerned, frustrated, confused, or relieved depending on employee response",
            "avoid": ["generic apology acceptance", "corporate language", "training jargon", "rubric words"],
        },
        "scenario": {
            "id": scenario.get("id"),
            "title": scenario.get("title"),
            "guest_role": scenario.get("guest_role"),
            "difficulty": scenario.get("difficulty"),
            "context": scenario.get("context"),
            "opening_message": scenario.get("opening_message"),
            "objectives_still_missing": missing[:4],
            "known_guest_followups": scenario.get("guest_followups", [])[:3],
            "active_learning_version_ids": session.get("active_learning_version_ids", []),
            "active_learning_guidance": session.get("learning_version_guidance", []),
        },
        "retrieved_training_context": _llm_context_excerpt(session.get("retrieved_training_context")),
        "conversation": recent_turns,
        "latest_employee_message": employee_message[:1000],
        "deterministic_score_summary": {
            "overall": score.get("overall"),
            "critical_miss": score.get("critical_miss"),
            "weak_dimensions": score.get("turn_coaching", {}).get("weak_dimensions", []) if isinstance(score.get("turn_coaching"), dict) else [],
            "missing_safety_signals": score.get("missing_safety_signals", [])[:2],
            "missing_escalation_signals": score.get("missing_escalation_signals", [])[:2],
        },
        "fallback_reply_if_uncertain": fallback_reply,
        "response_schema": {
            "guest_reply": "string under 85 words, guest voice only",
            "emotion": "one of worried|angry|confused|relieved|insistent",
            "pressure_level": "one of low|medium|high|critical",
        },
    }


def _llm_context_excerpt(context: Any) -> dict[str, Any]:
    if not isinstance(context, dict):
        return {}
    retrieved = context.get("retrieved") if isinstance(context.get("retrieved"), dict) else {}
    return {
        "retrieval_method": context.get("retrieval_method"),
        "policy_refs": (retrieved.get("policy_refs") if isinstance(retrieved.get("policy_refs"), list) else [])[:4],
        "policy_snippets": [
            {
                "title": item.get("title"),
                "summary": item.get("summary"),
                "policy_refs": item.get("policy_refs", [])[:4] if isinstance(item.get("policy_refs"), list) else [],
                "blocked_actions": item.get("blocked_actions", [])[:3] if isinstance(item.get("blocked_actions"), list) else [],
            }
            for item in (retrieved.get("policy_snippets") if isinstance(retrieved.get("policy_snippets"), list) else [])[:3]
            if isinstance(item, dict)
        ],
        "active_learning_guidance": (retrieved.get("active_learning_guidance") if isinstance(retrieved.get("active_learning_guidance"), list) else [])[:3],
        "prior_session_summaries": [
            {
                "overall": item.get("overall"),
                "critical_miss": item.get("critical_miss"),
                "open_gaps": item.get("open_gaps", [])[:3] if isinstance(item.get("open_gaps"), list) else [],
                "summary": item.get("summary"),
            }
            for item in (retrieved.get("prior_sessions") if isinstance(retrieved.get("prior_sessions"), list) else [])[:3]
            if isinstance(item, dict)
        ],
        "training_gap_patterns": (retrieved.get("training_gap_patterns") if isinstance(retrieved.get("training_gap_patterns"), list) else [])[:4],
        "guest_triage_patterns": (retrieved.get("guest_triage_patterns") if isinstance(retrieved.get("guest_triage_patterns"), list) else [])[:4],
        "historical_ticket_frequency": [
            {
                "scenario_id": item.get("scenario_id"),
                "ticket_count": item.get("ticket_count"),
                "highest_severity": item.get("highest_severity"),
                "frequency_label": item.get("frequency_label"),
                "latest_summary": item.get("latest_summary"),
                "sources": item.get("sources") if isinstance(item.get("sources"), dict) else {},
                "issue_types": item.get("issue_types") if isinstance(item.get("issue_types"), dict) else {},
            }
            for item in (retrieved.get("historical_ticket_frequency") if isinstance(retrieved.get("historical_ticket_frequency"), list) else [])[:4]
            if isinstance(item, dict)
        ],
        "scenario_recommendation": retrieved.get("scenario_recommendation") if isinstance(retrieved.get("scenario_recommendation"), dict) else None,
        "manager_reviews": [
            {"decision": item.get("decision"), "notes": item.get("notes")}
            for item in (retrieved.get("manager_reviews") if isinstance(retrieved.get("manager_reviews"), list) else [])[:3]
            if isinstance(item, dict)
        ],
        "trainee_profile": retrieved.get("trainee_profile") if isinstance(retrieved.get("trainee_profile"), dict) else {},
        "blocked_tools": (context.get("blocked_tools") if isinstance(context.get("blocked_tools"), list) else [])[:8],
    }


def _first_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(raw[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _sanitize_llm_guest_reply(value: Any, fallback_reply: str) -> str:
    reply = " ".join(str(value or "").replace("\n", " ").split())
    if not reply:
        return fallback_reply
    blocked = (
        "your score",
        "rubric",
        "policy keyword",
        "as an ai",
        "you should",
        "the correct answer",
        "needs clearer answer",
        "need clearer answer",
        "needs a clearer answer",
        "need a clearer answer",
        "clearer answer",
        "unclear answer",
        "not clear enough",
        "response needs",
        "employee response",
        "staff response",
        "trainer",
        "trainee",
        "coaching",
        "i approve",
        "refund approved",
        "ride is now safe",
    )
    lowered = reply.lower()
    if any(term in lowered for term in blocked):
        return fallback_reply
    return reply[:420]


def _generate_gemini_json_sync_hard_timeout(
    prompt: dict[str, Any],
    *,
    timeout_seconds: float,
    max_output_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    worker_path = Path(__file__).resolve().with_name("gemini_hard_timeout.py")
    request = {
        "prompt": prompt,
        "max_output_tokens": max_output_tokens,
        "temperature": temperature,
        "timeout_seconds": timeout_seconds,
    }
    env = os.environ.copy()
    env.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")
    try:
        completed = subprocess.run(
            [sys.executable, str(worker_path)],
            input=json.dumps(request, sort_keys=True, separators=(",", ":")),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            close_fds=False,
            timeout=max(0.5, timeout_seconds) + 0.5,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise TimeoutError(f"Gemini provider exceeded hard timeout of {timeout_seconds:g}s") from error

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(detail[:500] or f"Gemini worker exited with code {completed.returncode}")
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as error:
        raise RuntimeError("Gemini worker returned invalid JSON") from error
    if not payload.get("ok"):
        raise RuntimeError(str(payload.get("error") or "Gemini worker failed")[:500])
    return payload


def _generate_llm_guest_reply(
    scenario: dict[str, Any],
    session: dict[str, Any],
    employee_message: str,
    score: dict[str, Any],
    missing: list[str],
    fallback_reply: str,
) -> dict[str, Any]:
    props = None
    timeout_seconds = float(os.getenv("PARKPULSE_STAFF_TRAINING_LLM_TIMEOUT_SECONDS", "4"))
    try:
        from gemini_provider import get_gemini_agent_properties, get_gemini_model

        props = get_gemini_agent_properties()
        if not props.ready:
            return {
                "status": "fallback_not_configured",
                "source": "deterministic",
                "reply": fallback_reply,
                "readiness_issues": props.readiness_issues,
                "provider": props.provider,
                "platform": props.platform,
                "vertex_ai_ready": bool(getattr(props, "use_vertex_ai", False) and props.ready),
                "required_env": props.required_env,
                "llm_controls_score": False,
            }

        prompt = _llm_guest_prompt(scenario, session, employee_message, score, missing, fallback_reply)
        model = get_gemini_model()
        result = _generate_gemini_json_sync_hard_timeout(
            prompt,
            timeout_seconds=timeout_seconds,
            temperature=float(os.getenv("PARKPULSE_STAFF_TRAINING_LLM_TEMPERATURE", "0.72")),
            max_output_tokens=int(os.getenv("PARKPULSE_STAFF_TRAINING_LLM_MAX_OUTPUT_TOKENS", "240")),
        )
        parsed = _first_json_object(result.get("text", "") or "")
        reply = _sanitize_llm_guest_reply((parsed or {}).get("guest_reply"), fallback_reply)
        source = "llm_guest" if reply != fallback_reply else "deterministic"
        return {
            "status": "generated" if source == "llm_guest" else "fallback_sanitized",
            "source": source,
            "reply": reply,
            "model": model,
            "provider": props.provider,
            "platform": props.platform,
            "vertex_ai_ready": bool(props.use_vertex_ai and props.ready),
            "transport": result.get("transport"),
            "timeout_seconds": timeout_seconds,
            "emotion": (parsed or {}).get("emotion"),
            "pressure_level": (parsed or {}).get("pressure_level"),
            "llm_controls_score": False,
        }
    except Exception as error:
        is_timeout = isinstance(error, TimeoutError) or "timeout" in str(error).lower() or "timed out" in str(error).lower()
        return {
            "status": "fallback_timeout" if is_timeout else "fallback_error",
            "source": "deterministic",
            "reply": fallback_reply,
            "error": str(error)[:240],
            "provider": getattr(props, "provider", None),
            "platform": getattr(props, "platform", None),
            "vertex_ai_ready": bool(getattr(props, "use_vertex_ai", False) and getattr(props, "ready", False)),
            "timeout_seconds": timeout_seconds,
            "llm_controls_score": False,
        }


def _shadow_evaluator_prompt(scenario: dict[str, Any], session: dict[str, Any], employee_message: str, score: dict[str, Any]) -> dict[str, Any]:
    return {
        "task": "Review a staff-training response as a shadow evaluator. Return strict JSON.",
        "hard_rules": [
            "Do not change or override the official score.",
            "Do not invent live park actions, dispatches, approvals, diagnoses, refunds, or accommodations.",
            "Do not reveal hidden policy keywords.",
            "Focus on whether the deterministic rubric seems aligned, too strict, or too lenient.",
            "Keep commentary concise and useful for a trainer.",
        ],
        "scenario": {
            "id": scenario.get("id"),
            "title": scenario.get("title"),
            "difficulty": scenario.get("difficulty"),
            "context": scenario.get("context"),
            "objectives": scenario.get("objectives", []),
        },
        "latest_employee_message": employee_message[:1000],
        "conversation": [
            {"speaker": turn.get("speaker"), "message": str(turn.get("message") or "")[:500]}
            for turn in (session.get("transcript", []) if isinstance(session.get("transcript"), list) else [])[-8:]
        ],
        "deterministic_score": {
            "overall": score.get("overall"),
            "dimensions": score.get("dimensions"),
            "critical_miss": score.get("critical_miss"),
            "coaching": score.get("turn_coaching"),
            "missing_policy_signals": score.get("missing_policy_signals", []),
            "missing_safety_signals": score.get("missing_safety_signals", []),
            "missing_escalation_signals": score.get("missing_escalation_signals", []),
        },
        "response_schema": {
            "alignment": "one of aligned|too_strict|too_lenient|needs_human_review",
            "summary": "one sentence",
            "coaching_focus": ["one to three concise strings"],
            "rubric_disagreement": "string or empty",
            "suggested_human_review": "boolean",
            "score_authority": False,
        },
    }


def _generate_shadow_evaluator(scenario: dict[str, Any], session: dict[str, Any], employee_message: str, score: dict[str, Any]) -> dict[str, Any]:
    props = None
    timeout_seconds = float(os.getenv("PARKPULSE_STAFF_TRAINING_SHADOW_EVAL_TIMEOUT_SECONDS", "8"))
    try:
        from gemini_provider import get_gemini_agent_properties, get_gemini_model

        props = get_gemini_agent_properties()
        if not props.ready:
            return {
                "status": "fallback_not_configured",
                "score_authority": False,
                "provider": props.provider,
                "platform": props.platform,
                "readiness_issues": props.readiness_issues,
            }
        result = _generate_gemini_json_sync_hard_timeout(
            _shadow_evaluator_prompt(scenario, session, employee_message, score),
            timeout_seconds=timeout_seconds,
            temperature=float(os.getenv("PARKPULSE_STAFF_TRAINING_SHADOW_EVAL_TEMPERATURE", "0.2")),
            max_output_tokens=int(os.getenv("PARKPULSE_STAFF_TRAINING_SHADOW_EVAL_MAX_OUTPUT_TOKENS", "360")),
        )
        parsed = _first_json_object(result.get("text", "") or "") or {}
        coaching_focus = parsed.get("coaching_focus") if isinstance(parsed.get("coaching_focus"), list) else []
        alignment = str(parsed.get("alignment") or "aligned").strip().lower()
        if alignment not in {"aligned", "too_strict", "too_lenient", "needs_human_review"}:
            alignment = "needs_human_review"
        return {
            "status": "generated",
            "alignment": alignment,
            "summary": " ".join(str(parsed.get("summary") or "Shadow evaluator completed.").split())[:300],
            "coaching_focus": [" ".join(str(item).split())[:180] for item in coaching_focus[:3]],
            "rubric_disagreement": " ".join(str(parsed.get("rubric_disagreement") or "").split())[:300],
            "suggested_human_review": bool(parsed.get("suggested_human_review")) or alignment in {"too_strict", "too_lenient", "needs_human_review"},
            "score_authority": False,
            "model": get_gemini_model(),
            "provider": props.provider,
            "platform": props.platform,
            "transport": result.get("transport"),
            "timeout_seconds": timeout_seconds,
            "llm_controls_score": False,
        }
    except Exception as error:
        return {
            "status": "fallback_timeout" if isinstance(error, TimeoutError) or "timeout" in str(error).lower() else "fallback_error",
            "score_authority": False,
            "error": str(error)[:240],
            "provider": getattr(props, "provider", None),
            "platform": getattr(props, "platform", None),
            "llm_controls_score": False,
        }


def _aggregate_scorecard(scores: list[dict[str, Any]]) -> dict[str, Any]:
    if not scores:
        return _empty_scorecard()
    dimensions: dict[str, float] = {}
    for dimension in RUBRIC_DIMENSIONS:
        values = [float(score.get("dimensions", {}).get(dimension, 0)) for score in scores if isinstance(score.get("dimensions"), dict)]
        dimensions[dimension] = round(sum(values) / max(1, len(values)), 1)
    overall = round(sum(float(score.get("overall", 0)) for score in scores) / len(scores), 1)
    if any(score.get("critical_miss") for score in scores):
        overall = min(overall, 60)
    return {"overall": overall, "dimensions": dimensions, "turn_count": len(scores)}


def _debrief(session: dict[str, Any]) -> dict[str, Any]:
    scorecard = session.get("scorecard", _empty_scorecard())
    dimensions = scorecard.get("dimensions", {}) if isinstance(scorecard.get("dimensions"), dict) else {}
    weakest = sorted(
        [{"dimension": key, "score": value} for key, value in dimensions.items()],
        key=lambda item: float(item["score"]),
    )[:3]
    passed = float(scorecard.get("overall") or 0) >= 75 and not session.get("critical_miss") and not session.get("missing_objectives")
    return {
        "result": "pass" if passed else "coach_and_retry",
        "summary": "Ready for live shadowing." if passed else "Needs another roleplay pass before live shadowing.",
        "overall": scorecard.get("overall", 0),
        "weakest_dimensions": weakest,
        "completed_objectives": session.get("completed_objectives", []),
        "missing_objectives": session.get("missing_objectives", []),
        "critical_miss": bool(session.get("critical_miss")),
        "mastery_tracker": session.get("mastery_tracker") or _empty_mastery_tracker(),
        "recommended_retry": session.get("scenario_id") if not passed else None,
    }


def _session_event_snapshot(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": session.get("id"),
        "assignment_id": session.get("assignment_id"),
        "retry_of_session_id": session.get("retry_of_session_id"),
        "trainee_name": session.get("trainee_name"),
        "scenario_id": session.get("scenario_id"),
        "status": session.get("status"),
        "turn_count": session.get("turn_count"),
        "started_at": session.get("started_at"),
        "updated_at": session.get("updated_at"),
        "finished_at": session.get("finished_at"),
        "transcript": session.get("transcript", []),
        "scores": session.get("scores", []),
        "scorecard": session.get("scorecard"),
        "critical_miss": session.get("critical_miss"),
        "guest_simulator": session.get("guest_simulator"),
        "mastery_tracker": session.get("mastery_tracker"),
        "training_gap_ticket": session.get("training_gap_ticket"),
        "learning_version_outcome": session.get("learning_version_outcome"),
        "active_learning_version_ids": session.get("active_learning_version_ids", []),
        "active_learning_versions": session.get("active_learning_versions", []),
        "learning_version_guidance": session.get("learning_version_guidance", []),
        "retrieved_training_context": session.get("retrieved_training_context"),
        "agent_contract": session.get("agent_contract"),
        "agent_tool_manifest": session.get("agent_tool_manifest", []),
        "tool_trace": session.get("tool_trace", []),
        "completed_objectives": session.get("completed_objectives", []),
        "missing_objectives": session.get("missing_objectives", []),
        "created_at": _now_iso(),
    }


def _session_response(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": session.get("id"),
        "assignment_id": session.get("assignment_id"),
        "retry_of_session_id": session.get("retry_of_session_id"),
        "status": session.get("status"),
        "mode": session.get("mode"),
        "scenario_id": session.get("scenario_id"),
        "scenario": session.get("scenario"),
        "trainee_name": session.get("trainee_name"),
        "started_at": session.get("started_at"),
        "updated_at": session.get("updated_at"),
        "finished_at": session.get("finished_at"),
        "turn_count": session.get("turn_count"),
        "transcript": session.get("transcript", []),
        "scorecard": session.get("scorecard", _empty_scorecard()),
        "critical_miss": bool(session.get("critical_miss")),
        "mastery_tracker": session.get("mastery_tracker") or _empty_mastery_tracker(),
        "completed_objectives": session.get("completed_objectives", []),
        "missing_objectives": session.get("missing_objectives", []),
        "debrief": session.get("debrief"),
        "training_gap_ticket": session.get("training_gap_ticket"),
        "learning_version_outcome": session.get("learning_version_outcome"),
        "active_learning_version_ids": session.get("active_learning_version_ids", []),
        "active_learning_versions": session.get("active_learning_versions", []),
        "learning_version_guidance": session.get("learning_version_guidance", []),
        "retrieved_training_context": session.get("retrieved_training_context"),
        "agent_contract": session.get("agent_contract"),
        "agent_tool_manifest": session.get("agent_tool_manifest", []),
        "tool_trace": session.get("tool_trace", []),
        "guest_simulator": session.get("guest_simulator"),
        "boundary": session.get("boundary"),
        "uses_generated_data": True,
        "feeds_actual_reward_model": False,
        "llm_control_authority": False,
    }
