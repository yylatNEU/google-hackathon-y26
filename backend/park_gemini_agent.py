from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import nullcontext
from copy import deepcopy
from typing import Any

from pydantic import BaseModel, Field

from gemini_hard_timeout import generate_gemini_json_hard_timeout
from gemini_provider import get_gemini_agent_properties, get_gemini_client, get_gemini_model
from park_action_bridge import build_park_action_plan
from reliability import call_with_retries


ALLOWED_PARK_ACTIONS = {
    ("ride", "reroute"),
    ("staff", "redeploy"),
    ("food", "suppress_item"),
    ("traffic", "redirect_food"),
    ("energy", "protect_hvac"),
    ("medical", "dispatch"),
    ("accessibility", "assist"),
    ("security", "respond"),
    ("guest_services", "message"),
    ("signage", "update"),
    ("queue_gate", "hold_intake"),
    ("entertainment", "activate"),
    ("maintenance", "inspect"),
}

PARKPULSE_AGENT_CONTEXT = """
You are ParkPulse AI, a multi-agent operations copilot for amusement parks.
Use only the supplied park_state and retrieved MongoDB memory. Make a balanced operational
recommendation across guest satisfaction, ride wait times, staff stress, food/inventory pressure,
energy cost, and safety. Safety and maintenance clearance override throughput.
Use tools deliberately. A high-accuracy answer must first ground itself in live state, retrieve
similar incidents or playbooks, simulate or score candidate impact when selecting an action, and
validate policy before recommending dispatch. If a required tool result is not present in the
supplied context, mark it as needed instead of pretending it ran.
When operator_request is supplied, treat it as the live human intent. Preserve the requested
constraints, explain tradeoffs, ask for clarification only if an executable action would be unsafe
without missing facts, and make the candidate actions specific to that request.
For operator_request, first produce operator_understanding. This is the proof that you interpreted
the free-form request rather than selecting a canned scenario. Distinguish hard constraints from
soft preferences, name the real park zones/rides/staff roles/equipment controls you inferred, and
explain which option you rejected. If a local operator_constraints draft is supplied, use it only as
a hint; correct it when the text implies something different.

Allowed executable park_action pairs:
- ride / reroute
- staff / redeploy
- food / suppress_item
- traffic / redirect_food
- energy / protect_hvac
- medical / dispatch
- accessibility / assist
- security / respond
- guest_services / message
- signage / update
- queue_gate / hold_intake
- entertainment / activate
- maintenance / inspect

Also produce exactly 3 custom_action_mixes. Each mix must be a parameterized operating plan,
not a generic label. Include route target percentages, hold/recovery share, promotion strength,
staff moves, food/menu changes when relevant, and HVAC setpoints when shelter comfort or energy
load matters. Target_mix shares should normally sum to 0.55-0.9, leaving the rest as hold/recovery.
Never route guests toward a down ride or a location already described as overloaded unless the
mix explicitly explains why that risk is acceptable.
For operator_request, the custom_action_mixes must be uniquely shaped by that exact text. Do not
reuse the standard ride-down/weather/food templates unless the request genuinely asks for them.

Every answer must cite concrete evidence from park_state or memory in evidence_citations and must
include a tool_use_plan. Cite ride, zone, food, staff, weather, alert, policy, memory, or simulator
facts by field/name. Do not cite facts that are not in the supplied inputs.
Use amusement park operations language only. Avoid unrelated transportation, travel, or identity-data framing.
Return JSON only.
""".strip()


TOOL_USE_SEQUENCE = [
    "get_park_state",
    "retrieve_similar_incidents",
    "simulate_action",
    "validate_policy",
    "inspect_observability_contract",
]

SCENARIO_EVIDENCE_TERMS = {
    "ride_down": ["dragon", "coaster", "queue", "wait", "coaster plaza", "maintenance", "clearance"],
    "food_spike": ["food", "mobile", "pickup", "eta", "backlog", "court"],
    "staff_shortage": ["staff", "break", "callout", "operator", "crowd", "greeter"],
    "storm_response": ["storm", "weather", "indoor", "shelter", "hvac", "cooling", "comfort"],
    "guest_care": ["first aid", "guest services", "privacy", "medical", "family reunification"],
}


class _NoopSpan:
    def set_attribute(self, *_args, **_kwargs) -> None:
        return None


class _NoopTracer:
    def start_as_current_span(self, *_args, **_kwargs):
        return nullcontext(_NoopSpan())


def _get_tracer(name: str):
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except Exception:
        return _NoopTracer()


class ParkCandidateAction(BaseModel):
    target: str = Field(description="Executable target: ride, staff, food, traffic, energy, medical, accessibility, security, guest_services, signage, queue_gate, entertainment, or maintenance.")
    action: str = Field(description="Executable action for the target.")
    label: str = Field(description="Human-readable action label.")
    owner: str = Field(description="Operational owner.")
    expected_effect: str = Field(description="Expected operational effect.")
    risk_notes: list[str] = Field(description="Safety, staff, guest, inventory, or energy risks.")
    estimated_score: int = Field(description="Planner-estimated score from 0 to 100.")


class ParkRouteTarget(BaseModel):
    destination_id: str = Field(description="Ride, restaurant, show, or zone id to receive guests.")
    destination: str = Field(description="Human-readable destination name.")
    share: float = Field(description="Share of affected guests to route to this destination, 0.0 to 0.7.")
    rationale: str = Field(description="Why this destination belongs in the mix.")


class ParkStaffMove(BaseModel):
    role: str = Field(description="Staff role to move, such as crowd_control, greeter, cashier, ride_operator.")
    count: int = Field(description="Number of workers to move.")
    from_location: str = Field(description="Source location or staffing pool.")
    to_location: str = Field(description="Destination location.")


class ParkOperatorPlaceConstraint(BaseModel):
    id: str = Field(description="Known park id if available.")
    name: str = Field(description="Human-readable ride, zone, restaurant, or service point.")
    kind: str = Field(description="ride, zone, food, service, path, or equipment.")
    reason: str = Field(description="Why this place is constrained or preferred.")


class ParkOperatorStaffRequirement(BaseModel):
    role: str = Field(description="Role required, such as medical, accessibility_support, security, crowd_control, cashier, technician.")
    count: int = Field(description="Estimated worker count.")
    from_location: str = Field(description="Source location, base, or staffing pool.")
    to_location: str = Field(description="Destination location.")
    reason: str = Field(description="Why this role is required.")
    deadline_minutes: int = Field(description="How quickly the staff action should happen.")


class ParkOperatorEquipmentControl(BaseModel):
    equipment_type: str = Field(description="hvac, lighting, signage, audio, queue_gate, or other equipment class.")
    zones: list[str] = Field(description="Zone or device ids affected by the control.")
    settings: dict[str, int | str | bool] = Field(description="Specific setting changes.")
    reason: str = Field(description="Why the equipment control is useful.")


class ParkGuestServiceMessage(BaseModel):
    audience: str = Field(description="Affected guest segment.")
    message: str = Field(description="Short honest app or guest-service message.")
    offer: str = Field(description="Recovery or guidance offer, if any.")
    radiusMeters: int = Field(description="Approximate targeting radius.")


class ParkSignageUpdate(BaseModel):
    zones: list[str] = Field(description="Zones where signage should change.")
    message: str = Field(description="Short digital signage copy.")
    durationMinutes: int = Field(description="How long to display the update.")


class ParkQueueGateControl(BaseModel):
    zones: list[str] = Field(description="Queue or ride zones affected.")
    command: str = Field(description="Gate/control command such as pause_new_queue_intake or open_overflow_queue.")
    settings: dict[str, int | str | bool] = Field(description="Specific command settings.")
    requiresHumanApproval: bool = Field(description="Whether operator approval is required.")


class ParkOperatorUnderstanding(BaseModel):
    intent_summary: str = Field(description="One sentence describing what the operator actually asked for.")
    inferred_incident_type: str = Field(description="Specific incident or planning type inferred from the text.")
    hard_constraints: list[str] = Field(description="Constraints that must not be violated.")
    soft_preferences: list[str] = Field(description="Preferences that can be traded off.")
    avoid_zones: list[ParkOperatorPlaceConstraint] = Field(description="Places that should not receive more demand.")
    preferred_destinations: list[ParkOperatorPlaceConstraint] = Field(description="Places the operator wants to use if capacity allows.")
    required_staff_moves: list[ParkOperatorStaffRequirement] = Field(description="Role-specific staff actions inferred from the text.")
    equipment_controls: list[ParkOperatorEquipmentControl] = Field(description="Equipment or facility controls inferred from the text.")
    guest_segments: list[str] = Field(description="Guest segments named or implied by the text.")
    rejected_option: str = Field(description="A plausible but rejected response and why it was rejected.")
    missing_facts: list[str] = Field(description="Facts the agent would still want before high-risk execution.")


class ParkCustomActionMix(BaseModel):
    name: str = Field(description="Short unique candidate mix name.")
    strategy: str = Field(description="One-sentence strategy behind this candidate.")
    guest_reroute_enabled: bool = Field(description="Whether the plan sends guests to alternate locations.")
    target_mix: list[ParkRouteTarget] = Field(description="Route percentage mix across concrete destinations.")
    hold_share: float = Field(description="Share of affected guests to hold, recover, or delay instead of rerouting.")
    promotion_strength: str = Field(description="low, medium, or high.")
    offer: str = Field(description="Guest-facing incentive or message strategy.")
    staff_moves: list[ParkStaffMove] = Field(description="Concrete worker redeployments.")
    protect_breaks: bool = Field(description="Whether staff breaks are protected.")
    suppress_items: list[str] = Field(description="Menu/order items to suppress when inventory or kitchen load is risky.")
    promote_items: list[str] = Field(description="Menu/order items to promote when demand should be redirected.")
    hvac_setpoints: dict[str, int] = Field(description="Indoor zone HVAC setpoints in Fahrenheit.")
    guest_messages: list[ParkGuestServiceMessage] = Field(description="Guest-service or app messages shaped by the exact operator request.")
    signage_updates: list[ParkSignageUpdate] = Field(description="Digital signage updates, if wayfinding or panic reduction matters.")
    queue_gate_controls: list[ParkQueueGateControl] = Field(description="Queue gate or intake controls, if relevant.")
    rationale: str = Field(description="Tradeoff reasoning for why this mix could work.")


class ParkAgentResponse(BaseModel):
    operator_understanding: ParkOperatorUnderstanding | None = Field(default=None, description="GenAI interpretation of free-form operator text when operator_request is supplied.")
    analysis: str = Field(description="Brief grounded analysis of the live park state.")
    root_cause_classification: str = Field(description="Scenario/root cause class.")
    recommended_action: str = Field(description="Recommended operational change.")
    guest_message: str = Field(description="Draft park-app message for operator review.")
    confidence_score: int = Field(description="Confidence score from 0 to 100.")
    evidence_citations: list[str] = Field(default_factory=list, description="Concrete input facts from park_state or memory that support the answer.")
    tool_use_plan: list[dict[str, str]] = Field(default_factory=list, description="Tools used or required before dispatch, with status and reason.")
    candidate_actions: list[ParkCandidateAction] = Field(description="Two to four compared candidate actions.")
    custom_action_mixes: list[ParkCustomActionMix] = Field(description="Exactly three parameterized operating mixes for optimizer scoring.")
    selected_action: ParkCandidateAction = Field(description="Selected action to execute.")
    tradeoffs: dict[str, str] = Field(description="Guest, staff, safety, revenue, and energy tradeoffs.")


FAST_REACTION_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "operator_understanding": {
            "type": "object",
            "properties": {
                "intent_summary": {"type": "string"},
                "inferred_incident_type": {"type": "string"},
                "hard_constraints": {"type": "array", "items": {"type": "string"}},
                "soft_preferences": {"type": "array", "items": {"type": "string"}},
                "avoid_zones": {"type": "array", "items": {"type": "object"}},
                "preferred_destinations": {"type": "array", "items": {"type": "object"}},
                "required_staff_moves": {"type": "array", "items": {"type": "object"}},
                "equipment_controls": {"type": "array", "items": {"type": "object"}},
                "guest_segments": {"type": "array", "items": {"type": "string"}},
                "rejected_option": {"type": "string"},
                "missing_facts": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["intent_summary", "inferred_incident_type"],
        },
        "analysis": {"type": "string"},
        "root_cause_classification": {"type": "string"},
        "selected_action": {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "action": {"type": "string"},
                "label": {"type": "string"},
                "owner": {"type": "string"},
                "expected_effect": {"type": "string"},
                "risk_notes": {"type": "array", "items": {"type": "string"}},
                "estimated_score": {"type": "integer"},
            },
            "required": ["target", "action", "label", "owner", "expected_effect"],
        },
        "candidate_actions": {"type": "array", "items": {"type": "object"}},
        "custom_action_mix": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "strategy": {"type": "string"},
                "guest_reroute_enabled": {"type": "boolean"},
                "target_mix": {"type": "array", "items": {"type": "object"}},
                "hold_share": {"type": "number"},
                "promotion_strength": {"type": "string"},
                "offer": {"type": "string"},
                "staff_moves": {"type": "array", "items": {"type": "object"}},
                "suppress_items": {"type": "array", "items": {"type": "string"}},
                "promote_items": {"type": "array", "items": {"type": "string"}},
                "guest_messages": {"type": "array", "items": {"type": "object"}},
                "signage_updates": {"type": "array", "items": {"type": "object"}},
                "queue_gate_controls": {"type": "array", "items": {"type": "object"}},
                "rationale": {"type": "string"},
            },
        },
        "guest_message": {"type": "string"},
        "confidence_score": {"type": "integer"},
        "evidence_citations": {"type": "array", "items": {"type": "string"}},
        "tool_use_plan": {"type": "array", "items": {"type": "object"}},
        "tradeoffs": {"type": "object"},
    },
    "required": [
        "operator_understanding",
        "analysis",
        "root_cause_classification",
        "selected_action",
        "candidate_actions",
        "guest_message",
        "confidence_score",
        "evidence_citations",
        "tool_use_plan",
        "tradeoffs",
    ],
}


def _compact_state(state: dict[str, Any]) -> dict[str, Any]:
    flow = state.get("guestFlow", {}) if isinstance(state, dict) else {}
    return {
        "product": state.get("product", {}),
        "simTime": state.get("simTime", {}),
        "weather": state.get("weather", {}),
        "energy": state.get("energy", {}),
        "staffing": state.get("staffing", {}),
        "parkOps": state.get("parkOps", {}),
        "alerts": state.get("alerts", [])[:6],
        "guestFlow": {
            "activePolicy": flow.get("activePolicy"),
            "activeScenario": flow.get("activeScenario", {}),
            "interventions": flow.get("interventions", [])[:6],
            "representedGuests": flow.get("representedGuests"),
            "avgSatisfaction": flow.get("avgSatisfaction"),
            "zones": flow.get("zones", [])[:8],
            "rides": flow.get("rides", [])[:8],
            "paths": flow.get("paths", [])[:8],
        },
    }


def _reaction_state(state: dict[str, Any], route: dict[str, Any] | None = None) -> dict[str, Any]:
    flow = state.get("guestFlow", {}) if isinstance(state, dict) else {}
    zones = [zone for zone in flow.get("zones", []) if isinstance(zone, dict)]
    rides = [ride for ride in flow.get("rides", []) if isinstance(ride, dict)]
    route_name = str((route or {}).get("route") or "")
    dense_zones = sorted(zones, key=lambda zone: int(zone.get("density", 0) or 0), reverse=True)[:5]
    relevant_rides = [
        ride
        for ride in rides
        if ride.get("status") != "normal" or int(ride.get("waitMins", 0) or 0) >= 35 or int(ride.get("queueGuests", 0) or 0) >= 350
    ][:6]
    payload = {
        "simTime": state.get("simTime", {}),
        "weather": state.get("weather", {}),
        "energy": {
            "gridLoadPercent": state.get("energy", {}).get("gridLoadPercent")
            if isinstance(state.get("energy"), dict)
            else None
        },
        "staffing": state.get("staffing", {}),
        "alerts": state.get("alerts", [])[:4],
        "activeScenario": flow.get("activeScenario", {}),
        "representedGuests": flow.get("representedGuests"),
        "avgSatisfaction": flow.get("avgSatisfaction"),
        "zones": dense_zones,
        "rides": relevant_rides or rides[:4],
    }
    if route_name in {"food_spike", "operations"}:
        payload["food"] = state.get("food", {}) or state.get("parkOps", {}).get("food", {})
    if route_name in {"event_plan", "signal_triage"}:
        payload["parkOps"] = state.get("parkOps", {})
    return payload


def _compact_context(retrieved_context: dict[str, Any]) -> dict[str, Any]:
    retrieved = retrieved_context.get("retrieved", {}) if isinstance(retrieved_context, dict) else {}
    bigquery_priors = retrieved_context.get("bigquery_priors", {}) if isinstance(retrieved_context, dict) else {}
    relational_context = retrieved_context.get("relational_context", {}) if isinstance(retrieved_context, dict) else {}
    return {
        "summary": retrieved_context.get("summary", ""),
        "operator_request": retrieved_context.get("operator_request"),
        "operator_mode": retrieved_context.get("operator_mode"),
        "operator_constraints_hint": retrieved_context.get("operator_constraints", {}),
        "method": retrieved.get("method", ""),
        "playbooks": [
            {
                "_id": item.get("_id"),
                "title": item.get("title"),
                "summary": item.get("summary"),
                "guardrails": item.get("guardrails", [])[:4],
            }
            for item in retrieved.get("playbooks", [])[:3]
            if isinstance(item, dict)
        ],
        "incidents": [
            {
                "_id": item.get("_id"),
                "summary": item.get("summary"),
                "lesson": item.get("lesson"),
            }
            for item in retrieved.get("incidents", [])[:3]
            if isinstance(item, dict)
        ],
        "learnings": [
            {
                "_id": item.get("_id"),
                "scenarioKey": item.get("scenarioKey"),
                "outcomeLabel": item.get("outcomeLabel"),
                "lesson": item.get("lesson"),
                "rule": item.get("rule"),
                "adjustment": item.get("adjustment", {}),
                "confidence": item.get("confidence"),
                "useCount": item.get("useCount"),
            }
            for item in retrieved.get("learnings", [])[:4]
            if isinstance(item, dict)
        ],
        "bigquery_priors": {
            "source": bigquery_priors.get("source"),
            "query_name": bigquery_priors.get("query_name"),
            "best_prior": bigquery_priors.get("best_prior", {}),
            "weakest_prior": bigquery_priors.get("weakest_prior", {}),
            "agent_context": bigquery_priors.get("agent_context", [])[:3]
            if isinstance(bigquery_priors.get("agent_context"), list)
            else [],
        },
        "relational_context": {
            "mode": relational_context.get("mode"),
            "latest_run": relational_context.get("latest_run"),
            "recent_events": relational_context.get("recent_events", [])[:5]
            if isinstance(relational_context.get("recent_events"), list)
            else [],
            "join_keys": relational_context.get("join_keys", []),
        },
    }


def _first_json_object(text: str) -> dict[str, Any] | None:
    clean = (text or "").strip()
    if not clean:
        return None
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass
    start = clean.find("{")
    end = clean.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(clean[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def _normalize_candidate(candidate: dict[str, Any] | None, fallback: dict[str, Any]) -> dict[str, Any]:
    candidate = deepcopy(candidate or {})
    action_pair = candidate.get("park_action") if isinstance(candidate.get("park_action"), dict) else candidate
    target = str(action_pair.get("target") or fallback.get("target") or "ride").strip()
    action = str(action_pair.get("action") or fallback.get("action") or "reroute").strip()
    if (target, action) not in ALLOWED_PARK_ACTIONS:
        target, action = fallback.get("target", "ride"), fallback.get("action", "reroute")

    return {
        "target": target,
        "action": action,
        "label": str(candidate.get("label") or candidate.get("title") or fallback.get("label") or f"{target}/{action}"),
        "owner": str(candidate.get("owner") or fallback.get("owner") or "Decision Bridge"),
        "expected_effect": str(
            candidate.get("expected_effect")
            or candidate.get("expected_impact")
            or fallback.get("expected_effect")
            or fallback.get("expected_impact")
            or "Improve the active park incident response."
        ),
        "risk_notes": candidate.get("risk_notes") if isinstance(candidate.get("risk_notes"), list) else [],
        "estimated_score": int(candidate.get("estimated_score") or fallback.get("estimated_score") or 82),
    }


def _text_blob(*values: Any) -> str:
    return " ".join(str(value or "").lower().replace("_", " ") for value in values)


def _scenario_terms(scenario_key: str, retrieved_context: dict[str, Any] | None = None) -> list[str]:
    terms = list(SCENARIO_EVIDENCE_TERMS.get(str(scenario_key), []))
    route = (retrieved_context or {}).get("operator_route") if isinstance(retrieved_context, dict) else {}
    if isinstance(route, dict):
        route_scenario = str(route.get("scenario_key") or "")
        terms.extend(SCENARIO_EVIDENCE_TERMS.get(route_scenario, []))
    return sorted(set(term for term in terms if term))


def _has_memory_evidence(retrieved_context: dict[str, Any] | None) -> bool:
    compact = _compact_context(retrieved_context or {})
    return bool(compact.get("playbooks") or compact.get("incidents") or compact.get("learnings") or compact.get("bigquery_priors", {}).get("best_prior"))


def _tool_use_plan(raw_tools: Any, *, selected_action: dict[str, Any], has_memory: bool) -> list[dict[str, str]]:
    provided = raw_tools if isinstance(raw_tools, list) else []
    by_tool = {
        str(item.get("tool") or item.get("name") or ""): item
        for item in provided
        if isinstance(item, dict)
    }
    selected_pair = f"{selected_action.get('target', 'unknown')}/{selected_action.get('action', 'unknown')}"
    defaults = {
        "get_park_state": ("used", "Ground selected action in the latest compact park_state."),
        "retrieve_similar_incidents": ("used" if has_memory else "needed", "Use playbooks, incidents, learnings, or priors before trusting a recommendation."),
        "simulate_action": ("needed", f"Project impact and secondary risk before dispatching {selected_pair}."),
        "validate_policy": ("needed", f"Policy gate must validate {selected_pair} before execution."),
        "inspect_observability_contract": ("needed", "Attach trace, evidence, fallback, and delivery receipt data before release."),
    }
    plan: list[dict[str, str]] = []
    for tool in TOOL_USE_SEQUENCE:
        supplied = by_tool.get(tool, {}) if isinstance(by_tool.get(tool), dict) else {}
        status, reason = defaults[tool]
        plan.append(
            {
                "tool": tool,
                "status": str(supplied.get("status") or status),
                "reason": str(supplied.get("reason") or supplied.get("rationale") or reason),
            }
        )
    return plan


def _evidence_citations(raw_citations: Any, *, state: dict[str, Any], retrieved_context: dict[str, Any]) -> list[str]:
    citations = [str(item).strip() for item in raw_citations if isinstance(item, str) and item.strip()] if isinstance(raw_citations, list) else []
    flow = state.get("guestFlow", {}) if isinstance(state, dict) else {}
    active = flow.get("activeScenario", {}) if isinstance(flow.get("activeScenario"), dict) else {}
    if active.get("key"):
        citations.append(f"activeScenario:{active.get('key')}")
    rides = [ride for ride in flow.get("rides", []) if isinstance(ride, dict)]
    abnormal_ride = next((ride for ride in rides if ride.get("status") != "normal" or int(ride.get("waitMins", 0) or 0) >= 35), None)
    if abnormal_ride:
        citations.append(
            f"ride:{abnormal_ride.get('name') or abnormal_ride.get('id')} status={abnormal_ride.get('status')} wait={abnormal_ride.get('waitMins')}"
        )
    alerts = state.get("alerts", []) if isinstance(state.get("alerts"), list) else []
    if alerts:
        first_alert = alerts[0] if isinstance(alerts[0], dict) else {"message": alerts[0]}
        citations.append(f"alert:{str(first_alert.get('message') or first_alert.get('title') or first_alert)[:120]}")
    compact = _compact_context(retrieved_context)
    for key in ("playbooks", "incidents", "learnings"):
        rows = compact.get(key, []) if isinstance(compact.get(key), list) else []
        if rows:
            citations.append(f"memory:{key}:{rows[0].get('_id') or rows[0].get('title') or rows[0].get('scenarioKey')}")
    unique: list[str] = []
    for citation in citations:
        if citation and citation not in unique:
            unique.append(citation)
    return unique[:8]


def _answer_accuracy_audit(plan: dict[str, Any], state: dict[str, Any], scenario_key: str, retrieved_context: dict[str, Any]) -> dict[str, Any]:
    selected = plan.get("selected_action", {}) if isinstance(plan.get("selected_action"), dict) else {}
    citations = plan.get("evidence_citations", []) if isinstance(plan.get("evidence_citations"), list) else []
    tools = plan.get("tool_use_plan", []) if isinstance(plan.get("tool_use_plan"), list) else []
    text = _text_blob(
        plan.get("analysis"),
        plan.get("recommended_action"),
        plan.get("guest_message"),
        plan.get("root_cause_classification"),
        plan.get("operator_understanding"),
        citations,
    )
    scenario_hits = [term for term in _scenario_terms(scenario_key, retrieved_context) if term in text]
    selected_pair = (selected.get("target"), selected.get("action"))
    checks = {
        "has_live_state_evidence": any(str(item).startswith(("activeScenario:", "ride:", "alert:")) for item in citations),
        "has_memory_evidence": any(str(item).startswith("memory:") for item in citations) or _has_memory_evidence(retrieved_context),
        "scenario_terms_hit": len(scenario_hits),
        "has_selected_action": selected_pair in ALLOWED_PARK_ACTIONS,
        "has_policy_tool_plan": any(item.get("tool") == "validate_policy" for item in tools if isinstance(item, dict)),
        "has_simulation_tool_plan": any(item.get("tool") == "simulate_action" for item in tools if isinstance(item, dict)),
    }
    score = 54
    score += 12 if checks["has_live_state_evidence"] else 0
    score += 8 if checks["has_memory_evidence"] else 0
    score += min(18, checks["scenario_terms_hit"] * 6)
    score += 5 if checks["has_selected_action"] else 0
    score += 8 if checks["has_policy_tool_plan"] else 0
    score += 7 if checks["has_simulation_tool_plan"] else 0
    score = max(0, min(100, score))
    missing = [name for name, passed in checks.items() if not passed and name != "scenario_terms_hit"]
    if checks["scenario_terms_hit"] < 2:
        missing.append("scenario_specific_evidence")
    return {
        "status": "verified" if score >= 82 and not missing else "needs_evidence",
        "score": score,
        "checks": checks,
        "scenario_terms": scenario_hits[:8],
        "missing": sorted(set(missing)),
        "confidence_cap_applied": score < int(plan.get("confidence_score") or 0),
    }


def _apply_answer_accuracy_controls(
    plan: dict[str, Any],
    state: dict[str, Any],
    scenario_key: str,
    retrieved_context: dict[str, Any],
    raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw = raw or {}
    plan["evidence_citations"] = _evidence_citations(raw.get("evidence_citations") or plan.get("evidence_citations"), state=state, retrieved_context=retrieved_context)
    plan["tool_use_plan"] = _tool_use_plan(raw.get("tool_use_plan") or plan.get("tool_use_plan"), selected_action=plan.get("selected_action", {}), has_memory=_has_memory_evidence(retrieved_context))
    audit = _answer_accuracy_audit(plan, state, scenario_key, retrieved_context)
    plan["answer_accuracy"] = audit
    if audit["confidence_cap_applied"]:
        plan["confidence_score"] = min(int(plan.get("confidence_score") or 0), audit["score"])
    plan.setdefault("tradeoffs", {})["answer_accuracy"] = (
        "Verified against live-state evidence, memory, selected action, and required tool plan."
        if audit["status"] == "verified"
        else f"Needs stronger evidence before execution: {', '.join(audit['missing'])}."
    )
    return plan


def _fallback_plan(state: dict[str, Any], runtime: str, errors: list[str] | None = None) -> dict[str, Any]:
    native = build_park_action_plan(state)
    props = get_gemini_agent_properties()
    native_selected = native.get("selected_action", {})
    fallback_action = native_selected.get("park_action", {"target": "ride", "action": "reroute"})
    candidates = [
        _normalize_candidate(
            {
                **item,
                "label": item.get("title"),
                "expected_effect": item.get("expected_impact"),
            },
            item.get("park_action", fallback_action),
        )
        for item in native.get("recommended_actions", [])
        if isinstance(item, dict)
    ]
    selected = _normalize_candidate(native_selected, fallback_action)
    plan = {
        "runtime": runtime,
        "gemini_ready": props.ready,
        "model": props.model,
        "attempted_gemini": runtime != "deterministic_fallback",
        "operator_understanding": None,
        "analysis": "Native ParkPulse planner used deterministic ride, staff, food, traffic, and energy guardrails.",
        "root_cause_classification": native.get("scenario", {}).get("key", "ride_down"),
        "recommended_action": selected["label"],
        "guest_message": "We are adjusting park operations to reduce waits. Check the app for updated ride, food, and indoor attraction options.",
        "confidence_score": round(float(native.get("confidence", 0.82)) * 100),
        "candidate_actions": candidates or [selected],
        "custom_action_mixes": [],
        "selected_action": selected,
        "tradeoffs": native.get("tradeoffs", {}),
        "errors": errors or [],
        "source_plan": native,
    }
    return _apply_answer_accuracy_controls(plan, state, str(plan.get("root_cause_classification") or ""), {}, {})


def _normalize_gemini_plan(raw: dict[str, Any], state: dict[str, Any], runtime: str, scenario_key: str = "", retrieved_context: dict[str, Any] | None = None) -> dict[str, Any]:
    fallback = _fallback_plan(state, "deterministic_fallback")
    fallback_selected = fallback["selected_action"]
    selected = _normalize_candidate(raw.get("selected_action"), fallback_selected)
    candidates = [
        _normalize_candidate(item, fallback_selected)
        for item in raw.get("candidate_actions", [])
        if isinstance(item, dict)
    ]
    if not candidates:
        candidates = fallback["candidate_actions"]
    if not any(item["target"] == selected["target"] and item["action"] == selected["action"] for item in candidates):
        candidates.insert(0, selected)
    custom_mixes = raw.get("custom_action_mixes") if isinstance(raw.get("custom_action_mixes"), list) else []

    plan = {
        "runtime": runtime,
        "gemini_ready": True,
        "attempted_gemini": True,
        "model": get_gemini_agent_properties().model,
        "operator_understanding": raw.get("operator_understanding") if isinstance(raw.get("operator_understanding"), dict) else None,
        "analysis": str(raw.get("analysis") or fallback["analysis"]),
        "root_cause_classification": str(raw.get("root_cause_classification") or fallback["root_cause_classification"]),
        "recommended_action": str(raw.get("recommended_action") or selected["label"]),
        "guest_message": str(raw.get("guest_message") or fallback["guest_message"]),
        "confidence_score": int(raw.get("confidence_score") or fallback["confidence_score"]),
        "evidence_citations": raw.get("evidence_citations") if isinstance(raw.get("evidence_citations"), list) else [],
        "tool_use_plan": raw.get("tool_use_plan") if isinstance(raw.get("tool_use_plan"), list) else [],
        "candidate_actions": candidates,
        "custom_action_mixes": custom_mixes[:4],
        "selected_action": selected,
        "tradeoffs": raw.get("tradeoffs") if isinstance(raw.get("tradeoffs"), dict) else fallback["tradeoffs"],
        "errors": [],
    }
    return _apply_answer_accuracy_controls(plan, state, scenario_key or str(plan.get("root_cause_classification") or ""), retrieved_context or {}, raw)


def _attach_performance(plan: dict[str, Any], started_at: float, timeout_seconds: float, status: str) -> dict[str, Any]:
    plan["response_latency_ms"] = int((time.monotonic() - started_at) * 1000)
    plan["timeout_seconds"] = timeout_seconds
    plan["performance_status"] = status
    return plan


def _env_float(name: str, default: float, minimum: float = 0.5) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default))))
    except ValueError:
        return default


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _scenario_preferred_action(scenario_key: str) -> tuple[str, str] | None:
    return {
        "ride_down": ("ride", "reroute"),
        "staff_shortage": ("staff", "redeploy"),
        "food_spike": ("food", "suppress_item"),
        "storm_response": ("ride", "reroute"),
    }.get(scenario_key)


def _align_selected_action_to_scenario(plan: dict[str, Any], state: dict[str, Any], scenario_key: str) -> dict[str, Any]:
    preferred = _scenario_preferred_action(scenario_key)
    if not preferred:
        return plan
    selected = plan.get("selected_action", {})
    if (selected.get("target"), selected.get("action")) == preferred:
        return plan

    for candidate in plan.get("candidate_actions", []):
        if (candidate.get("target"), candidate.get("action")) == preferred:
            plan["selected_action"] = candidate
            plan["recommended_action"] = candidate.get("label", plan.get("recommended_action", ""))
            plan.setdefault("tradeoffs", {})["demo_visibility"] = "Selected the scenario-primary executable action so the park map changes during the demo."
            return plan

    fallback = _fallback_plan(state, "deterministic_fallback")
    fallback_selected = fallback["selected_action"]
    if (fallback_selected.get("target"), fallback_selected.get("action")) == preferred:
        plan["candidate_actions"] = [fallback_selected, *plan.get("candidate_actions", [])]
        plan["selected_action"] = fallback_selected
        plan["recommended_action"] = fallback_selected.get("label", plan.get("recommended_action", ""))
        plan.setdefault("tradeoffs", {})["demo_visibility"] = "Selected the scenario-primary executable action so the park map changes during the demo."
    return plan


def _prompt(state: dict[str, Any], scenario_key: str, retrieved_context: dict[str, Any]) -> str:
    payload = {
        "scenario_key": scenario_key,
        "operator_request": retrieved_context.get("operator_request"),
        "operator_mode": retrieved_context.get("operator_mode"),
        "park_state": _compact_state(state),
        "mongodb_memory": _compact_context(retrieved_context),
        "tool_use_contract": {
            "required_sequence": TOOL_USE_SEQUENCE,
            "rules": [
                "Mark get_park_state as used only when the answer cites live park_state facts.",
                "Mark retrieve_similar_incidents as used only when memory playbooks, incidents, learnings, or priors are cited.",
                "Mark simulate_action as needed unless supplied context includes simulator or optimizer evidence.",
                "Mark validate_policy as needed before dispatch unless supplied context includes policy validation evidence.",
                "Never claim a tool was used when the result is not in the supplied context.",
            ],
        },
        "output_contract": {
            "schema": "ParkAgentResponse",
            "requirements": [
                "Return JSON only.",
                "Follow the response_schema supplied in GenerateContentConfig.",
                "Include exactly 3 custom_action_mixes for full planning runs.",
                "Include evidence_citations with concrete state or memory facts.",
                "Include tool_use_plan with tool, status, and reason for each required tool.",
            ],
        },
    }
    return f"{PARKPULSE_AGENT_CONTEXT}\n\n{json.dumps(payload, separators=(',', ':'), sort_keys=True)}"


def _reaction_prompt(state: dict[str, Any], scenario_key: str, retrieved_context: dict[str, Any]) -> str:
    route = retrieved_context.get("operator_route") if isinstance(retrieved_context.get("operator_route"), dict) else {}
    payload = {
        "workflow": "react_first_operator_command",
        "task": (
            "Interpret the operator_request and return one bounded action plus one compact action mix. "
            "Use only relevant state, memory, and local constraints. Do not emit unrelated ride/food/event actions."
        ),
        "scenario_key": scenario_key,
        "operator_request": retrieved_context.get("operator_request"),
        "operator_mode": retrieved_context.get("operator_mode"),
        "route": route,
        "park_state": _reaction_state(state, route),
        "memory": _compact_context(retrieved_context),
        "local_operator_constraints": retrieved_context.get("operator_constraints", {}),
        "tool_use_contract": {
            "required_sequence": TOOL_USE_SEQUENCE,
            "react_first_rule": "Use get_park_state and retrieve_similar_incidents evidence when present; mark simulate_action and validate_policy as needed before dispatch if not present.",
        },
        "output_contract": {
            "schema": "ParkFastReactionResponse",
            "requirements": [
                "Return JSON only.",
                "Include exactly one selected_action.",
                "Include at most three candidate_actions.",
                "Include one custom_action_mix only when it helps dispatch, routing, staffing, food, signage, or queue control.",
                "Include evidence_citations with concrete state or memory facts.",
                "Include tool_use_plan with tool, status, and reason.",
                "Keep analysis and tradeoffs brief.",
            ],
        },
    }
    return f"{PARKPULSE_AGENT_CONTEXT}\n\n{json.dumps(payload, separators=(',', ':'), sort_keys=True)}"


def _normalize_fast_reaction_plan(raw: dict[str, Any], state: dict[str, Any], runtime: str, scenario_key: str = "", retrieved_context: dict[str, Any] | None = None) -> dict[str, Any]:
    fallback = _fallback_plan(state, "deterministic_fallback")
    fallback_selected = fallback["selected_action"]
    selected = _normalize_candidate(raw.get("selected_action"), fallback_selected)
    candidates = [
        _normalize_candidate(item, selected)
        for item in raw.get("candidate_actions", [])
        if isinstance(item, dict)
    ]
    if not candidates:
        candidates = [selected]
    if not any(item["target"] == selected["target"] and item["action"] == selected["action"] for item in candidates):
        candidates.insert(0, selected)
    custom_mix = raw.get("custom_action_mix") if isinstance(raw.get("custom_action_mix"), dict) else None
    custom_mixes = [custom_mix] if custom_mix else []
    plan = {
        "runtime": f"{runtime}_fast_reaction",
        "gemini_ready": True,
        "attempted_gemini": True,
        "model": get_gemini_agent_properties().model,
        "operator_understanding": raw.get("operator_understanding") if isinstance(raw.get("operator_understanding"), dict) else None,
        "analysis": str(raw.get("analysis") or fallback["analysis"]),
        "root_cause_classification": str(raw.get("root_cause_classification") or fallback["root_cause_classification"]),
        "recommended_action": selected["label"],
        "guest_message": str(raw.get("guest_message") or fallback["guest_message"]),
        "confidence_score": int(raw.get("confidence_score") or fallback["confidence_score"]),
        "evidence_citations": raw.get("evidence_citations") if isinstance(raw.get("evidence_citations"), list) else [],
        "tool_use_plan": raw.get("tool_use_plan") if isinstance(raw.get("tool_use_plan"), list) else [],
        "candidate_actions": candidates[:3],
        "custom_action_mixes": custom_mixes,
        "selected_action": selected,
        "tradeoffs": raw.get("tradeoffs") if isinstance(raw.get("tradeoffs"), dict) else fallback["tradeoffs"],
        "errors": [],
        "workflow": "react_first_operator_command",
    }
    return _apply_answer_accuracy_controls(plan, state, scenario_key or str(plan.get("root_cause_classification") or ""), retrieved_context or {}, raw)


async def build_park_gemini_plan(
    park_state: dict[str, Any],
    scenario_key: str,
    retrieved_context: dict[str, Any],
    *,
    enforce_scenario_alignment: bool = True,
) -> dict[str, Any]:
    started_at = time.monotonic()
    props = get_gemini_agent_properties()
    provider_timeout = _env_float("PARKPULSE_GEMINI_TIMEOUT_SECONDS", 22.0)
    max_output_tokens = _env_int("PARKPULSE_GEMINI_MAX_OUTPUT_TOKENS", 5000)
    thinking_budget = _env_int("PARKPULSE_GEMINI_THINKING_BUDGET", 0, minimum=0)
    errors: list[str] = []
    tracer = _get_tracer("parkpulse.gemini_agent")
    with tracer.start_as_current_span("parkpulse.gemini_agent.plan") as span:
        span.set_attribute("parkpulse.domain", "amusement_park_operations")
        span.set_attribute("parkpulse.scenario", scenario_key)
        span.set_attribute("parkpulse.gemini.platform", props.platform)
        span.set_attribute("parkpulse.gemini.ready", props.ready)
        span.set_attribute("gen_ai.system", "google_gemini")
        span.set_attribute("gen_ai.request.model", props.model)

        if not props.ready:
            errors = props.readiness_issues
            span.set_attribute("parkpulse.gemini.runtime", "deterministic_fallback")
            span.set_attribute("parkpulse.gemini.error", "; ".join(errors))
            plan = _attach_performance(
                _fallback_plan(park_state, "deterministic_fallback", errors),
                started_at,
                provider_timeout,
                "not_ready",
            )
            span.set_attribute("parkpulse.gemini.response_latency_ms", plan["response_latency_ms"])
            return plan

        prompt = _prompt(park_state, scenario_key, retrieved_context)
        try:
            if props.use_gemini_enterprise:
                from gemini_enterprise_client import PARKPULSE_CONTEXT, stream_assist

                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        stream_assist,
                        prompt,
                        park_state,
                        PARKPULSE_CONTEXT,
                        "parkpulse_decision_bridge",
                        "safety_control_override,maintenance_clearance,guest_pii,automated_ride_control",
                    ),
                    timeout=provider_timeout,
                )
                raw = _first_json_object(result.get("text", "")) or {}
                runtime = "gemini_enterprise"
                span.set_attribute("gemini_enterprise.assistant", result.get("assistant_name", ""))
                span.set_attribute("gemini_enterprise.raw_chunk_count", result.get("raw_chunk_count", 0))
            else:
                def generate_content():
                    from google.genai import types

                    client = get_gemini_client()
                    return client.models.generate_content(
                        model=get_gemini_model(),
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=ParkAgentResponse,
                            temperature=0.2,
                            max_output_tokens=max_output_tokens,
                            thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget),
                        ),
                    )

                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        call_with_retries,
                        "gemini.generate_content",
                        generate_content,
                    ),
                    timeout=provider_timeout,
                )
                raw = _first_json_object(getattr(response, "text", "") or "") or {}
                runtime = props.platform

            plan = _normalize_gemini_plan(raw, park_state, runtime, scenario_key, retrieved_context)
            if enforce_scenario_alignment:
                plan = _align_selected_action_to_scenario(plan, park_state, scenario_key)
                plan = _apply_answer_accuracy_controls(plan, park_state, scenario_key, retrieved_context, raw)
            span.set_attribute("parkpulse.gemini.runtime", plan["runtime"])
            span.set_attribute("parkpulse.gemini.custom_mix_count", len(plan.get("custom_action_mixes", [])))
            span.set_attribute("parkpulse.answer_accuracy.score", plan.get("answer_accuracy", {}).get("score", 0))
            span.set_attribute("parkpulse.answer_accuracy.status", plan.get("answer_accuracy", {}).get("status", "unknown"))
            span.set_attribute("parkpulse.selected_action", f"{plan['selected_action']['target']}/{plan['selected_action']['action']}")
            span.set_attribute("parkpulse.confidence_score", plan["confidence_score"])
            _attach_performance(plan, started_at, provider_timeout, "success")
            span.set_attribute("parkpulse.gemini.response_latency_ms", plan["response_latency_ms"])
            return plan
        except Exception as error:
            message = (
                f"Gemini provider timed out after {provider_timeout:g}s"
                if isinstance(error, asyncio.TimeoutError)
                else str(error)
            )
            errors = [message]
            span.set_attribute("parkpulse.gemini.runtime", "deterministic_fallback")
            span.set_attribute("parkpulse.gemini.error", message[:500])
            plan = _attach_performance(
                _fallback_plan(park_state, "deterministic_fallback_after_gemini_error", errors),
                started_at,
                provider_timeout,
                "timeout" if isinstance(error, asyncio.TimeoutError) else "error",
            )
            span.set_attribute("parkpulse.gemini.response_latency_ms", plan["response_latency_ms"])
            return plan


async def build_park_gemini_reaction_plan(
    park_state: dict[str, Any],
    scenario_key: str,
    retrieved_context: dict[str, Any],
) -> dict[str, Any]:
    started_at = time.monotonic()
    props = get_gemini_agent_properties()
    provider_timeout = _env_float(
        "PARKPULSE_GEMINI_REACTION_TIMEOUT_SECONDS",
        min(_env_float("PARKPULSE_GEMINI_TIMEOUT_SECONDS", 22.0), 8.0),
    )
    max_output_tokens = _env_int("PARKPULSE_GEMINI_REACTION_MAX_OUTPUT_TOKENS", 1800)
    thinking_budget = _env_int("PARKPULSE_GEMINI_REACTION_THINKING_BUDGET", 0, minimum=0)
    tracer = _get_tracer("parkpulse.gemini_agent")
    with tracer.start_as_current_span("parkpulse.gemini_agent.react_first") as span:
        span.set_attribute("parkpulse.domain", "amusement_park_operations")
        span.set_attribute("parkpulse.scenario", scenario_key)
        span.set_attribute("parkpulse.gemini.platform", props.platform)
        span.set_attribute("parkpulse.gemini.ready", props.ready)
        span.set_attribute("gen_ai.system", "google_gemini")
        span.set_attribute("gen_ai.request.model", props.model)
        if not props.ready:
            plan = _attach_performance(
                _fallback_plan(park_state, "deterministic_fallback", props.readiness_issues),
                started_at,
                provider_timeout,
                "not_ready",
            )
            plan["workflow"] = "react_first_operator_command"
            return plan

        prompt = _reaction_prompt(park_state, scenario_key, retrieved_context)
        try:
            if props.use_gemini_enterprise:
                from gemini_enterprise_client import PARKPULSE_CONTEXT, stream_assist

                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        stream_assist,
                        prompt,
                        park_state,
                        PARKPULSE_CONTEXT,
                        "parkpulse_react_first",
                        "safety_control_override,maintenance_clearance,guest_pii,automated_ride_control",
                    ),
                    timeout=provider_timeout,
                )
                raw = _first_json_object(result.get("text", "")) or {}
                runtime = "gemini_enterprise"
                span.set_attribute("gemini_enterprise.assistant", result.get("assistant_name", ""))
            else:
                result = await generate_gemini_json_hard_timeout(
                    {
                        "instruction": prompt,
                        "response_schema": FAST_REACTION_RESPONSE_SCHEMA,
                        "latency_contract": {
                            "workflow": "react_first_operator_command",
                            "return_json_only": True,
                            "single_selected_action": True,
                        },
                    },
                    timeout_seconds=provider_timeout,
                    max_output_tokens=max_output_tokens,
                    temperature=0.1,
                )
                raw = _first_json_object(str(result.get("text") or "")) or {}
                runtime = props.platform

            plan = _normalize_fast_reaction_plan(raw, park_state, runtime, scenario_key, retrieved_context)
            _attach_performance(plan, started_at, provider_timeout, "success")
            span.set_attribute("parkpulse.gemini.runtime", plan["runtime"])
            span.set_attribute("parkpulse.gemini.response_latency_ms", plan["response_latency_ms"])
            span.set_attribute("parkpulse.answer_accuracy.score", plan.get("answer_accuracy", {}).get("score", 0))
            span.set_attribute("parkpulse.answer_accuracy.status", plan.get("answer_accuracy", {}).get("status", "unknown"))
            span.set_attribute("parkpulse.selected_action", f"{plan['selected_action']['target']}/{plan['selected_action']['action']}")
            return plan
        except Exception as error:
            message = (
                f"Gemini reaction provider timed out after {provider_timeout:g}s"
                if isinstance(error, asyncio.TimeoutError)
                else str(error)
            )
            span.set_attribute("parkpulse.gemini.runtime", "deterministic_fallback")
            span.set_attribute("parkpulse.gemini.error", message[:500])
            plan = _attach_performance(
                _fallback_plan(park_state, "deterministic_fallback_after_gemini_error", [message]),
                started_at,
                provider_timeout,
                "timeout" if isinstance(error, asyncio.TimeoutError) else "error",
            )
            plan["workflow"] = "react_first_operator_command"
            return plan
