from __future__ import annotations

import copy
import base64
import hashlib
import hmac
import json
import os
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from agent_trust_store import (
    active_key_record,
    get_key_record,
    get_partner,
    get_revocation,
    init_agent_trust_store,
    list_audit_events,
    list_key_records,
    list_partners,
    list_revocations,
    record_key,
    record_revocation,
    trust_store_status,
    upsert_partner,
)

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
except Exception:  # pragma: no cover - fallback only when optional crypto is unavailable
    InvalidSignature = None
    serialization = None
    Ed25519PrivateKey = None
    Ed25519PublicKey = None

_sessions: dict[str, dict[str, Any]] = {}
_agent_onboardings: dict[str, dict[str, Any]] = {}
_credential_revocations: dict[str, dict[str, Any]] = {}
_partner_registry: dict[str, dict[str, Any]] = {}
_trust_registry_loaded = False

CLIENT_ALLOWED_TO_SHARE = {
    "location",
    "party_size",
    "preferences",
    "accessibility_needs",
    "budget",
    "ride_preference",
    "inventory_position",
    "delivery_eta",
    "supplier_compliance",
    "cold_chain_status",
    "parts_availability",
}
CLIENT_ALLOWED_TO_RECEIVE = {
    "route_plan",
    "wait_time_alert",
    "food_recommendation",
    "safety_notice",
    "compensation_offer",
    "demand_forecast",
    "restock_request",
    "dock_slot",
    "substitution_request",
    "purchase_order_notice",
    "maintenance_parts_request",
}
CLIENT_BLOCKED_ACTIONS = {
    "auto_purchase",
    "share_health_data",
    "accept_refund_without_user",
    "auto_accept_price_change",
    "bypass_food_safety",
    "release_vendor_payment_without_approval",
}
DEFAULT_DELEGATION_SCOPES = sorted(CLIENT_ALLOWED_TO_SHARE | CLIENT_ALLOWED_TO_RECEIVE | {"policy_check", "session_commit"})
CERTIFICATION_REQUIRED_CASES = ["identity_trust", "capability_scope", "commerce_payment_probe", "queue_reroute"]
SUPPLY_CHAIN_CERTIFICATION_REQUIRED_CASES = ["identity_trust", "capability_scope", "supply_chain_negotiation", "procurement_gate", "artifact_verification"]
SUPPLY_CHAIN_APPROVAL = "approved_for_supply_chain_coordination"
GUEST_ROUTE_APPROVAL = "approved_for_guest_route_planning"
COMMERCE_ACTIONS = {
    "payment",
    "auto_purchase",
    "refund_acceptance",
    "accept_refund_without_user",
    "compensation_offer",
    "compensation_settlement",
    "purchase_order",
    "vendor_payment_release",
    "price_change_acceptance",
}
SUPPLY_CHAIN_PROTOCOL_SCENARIOS = {"supply_replenishment", "cold_chain_incident", "maintenance_parts_shortage"}

BUILT_IN_PROTOCOL_SCENARIOS: dict[str, dict[str, Any]] = {
    "visit_planning": {
        "id": "visit_planning",
        "mode": "Visit planning",
        "client_intent": "Best 3-hour family plan with low waits, peanut-safe food, and low walking.",
        "park_offer": "Lazy River, Arcade, allergy-safe Pizza Garden, Parade Zone.",
        "negotiation": "Client agent raises walking distance; Park agent trades wait savings for a tighter route.",
        "handoffs": ["queue_agent", "food_agent", "guest_experience_agent"],
        "allowed": ["route_change", "wait_alert", "food_recommendation"],
        "blocked": ["auto_purchase", "share_health_data"],
        "outcome": "42 minutes saved with safe-food constraint preserved.",
        "run": {
            "goal": "maximize_family_satisfaction",
            "constraints": {"children": 2, "avoid_wait_over_minutes": 35, "avoid_thrill_rides": True, "food_allergy": "peanut", "scenario_mode": "visit_planning"},
            "counter_request": "reduce walking distance",
            "priority_change": {"walking_distance": "highest", "wait_time": "medium"},
            "monitor_event": "live_family_visit",
            "commerce_action": "payment",
            "commerce_reason": "Visit planning payment boundary probe.",
            "queue_reason": "Avoid current congestion and long waits.",
            "planner": "live_state",
        },
    },
    "incident_response": {
        "id": "incident_response",
        "mode": "Incident response",
        "client_intent": "Keep the family experience intact after Wave Pool enters safety delay.",
        "park_offer": "Indoor Surf Simulator plus priority Lazy River return window.",
        "negotiation": "Client agent declines food credit and asks for time-first alternative.",
        "handoffs": ["safety_agent", "queue_agent", "commerce_agent"],
        "allowed": ["safety_notice", "priority_access", "route_change"],
        "blocked": ["override_safety_delay", "refund_acceptance"],
        "outcome": "Safety delay respected while experience is rerouted in real time.",
        "proposal": {
            "plan": ["Indoor Surf Simulator", "Covered Arcade recovery window", "Lazy River priority return", "Parade Zone calm reset"],
            "walking": "0.8 miles",
            "saved": "38 minutes",
            "confidence": 0.84,
            "rationale": "Wave Pool remains in safety delay, so the park agent shifts the family to indoor capacity and a time-first priority return instead of a credit-first resolution.",
            "tradeoffs": ["Safety delay cannot be overridden.", "Food credit can be offered but not accepted without user approval.", "Priority access is allowed as a park-side reroute benefit."],
            "evidence": {"source": "scenario_static_plan", "scenario_mode": "incident_response", "incident": "Wave Pool safety delay"},
        },
        "monitoring": {
            "event": "Wave Pool has a safety delay.",
            "park_agent_offer": "Indoor Surf Simulator plus optional $5 food credit.",
            "client_agent_counter": "My user values time more than credit. Any priority queue alternative?",
            "park_agent_revision": "Priority access to Lazy River in 25 minutes.",
            "accepted_resolution": "Accepted. Notify user with time-first reroute.",
            "policy_gate": {"safety_delay": "cannot_override", "food_credit": "user_approval_required_before_acceptance", "priority_access": "agent_allowed_with_notification"},
            "state_evidence": {"source": "scenario_monitor", "scenario_mode": "incident_response"},
        },
        "run": {
            "goal": "preserve_guest_experience_after_incident",
            "constraints": {"incident": "Wave Pool safety delay", "prefer_time_over_credit": True, "children": 2, "avoid_wait_over_minutes": 30, "scenario_mode": "incident_response"},
            "counter_request": "prefer priority access over food credit",
            "priority_change": {"time_saved": "highest", "compensation_value": "low"},
            "monitor_event": "wave_pool_safety_delay",
            "commerce_action": "compensation_settlement",
            "commerce_reason": "Incident response settlement boundary probe.",
            "queue_reason": "Find a time-first reroute while safety delay remains active.",
            "planner": "incident_response",
        },
    },
    "accessibility_support": {
        "id": "accessibility_support",
        "mode": "Accessibility support",
        "client_intent": "Minimize walking and avoid sensory overload while keeping kid-friendly stops.",
        "park_offer": "Covered route, quiet dining window, parade viewing zone with lower crowd density.",
        "negotiation": "Client agent asks to prioritize rest points over wait-time savings.",
        "handoffs": ["guest_experience_agent", "queue_agent", "food_agent"],
        "allowed": ["accessibility_needs", "low_walking_route", "restaurant_timing"],
        "blocked": ["medical_escalation", "health_data_sharing"],
        "outcome": "Plan adapts to accessibility constraints without exposing health data.",
        "proposal": {
            "plan": ["Covered Gate path", "Quiet Arcade window", "Pizza Garden allergy-safe counter", "Low-crowd Parade viewing zone"],
            "walking": "0.7 miles",
            "high_walking": "0.5 miles",
            "saved": "24 minutes",
            "confidence": 0.81,
            "rationale": "The route optimizes for low walking, covered paths, and lower crowd density rather than maximum wait-time savings.",
            "tradeoffs": ["Walking and crowd density outrank raw wait savings.", "Allergy-safe food remains constrained to public menu data.", "Health data and medical escalation remain approval gated."],
            "evidence": {"source": "scenario_static_plan", "scenario_mode": "accessibility_support", "accessibility": "low_walking_sensory_safe"},
        },
        "monitoring": {
            "event": "Accessibility route check found rising crowd density near Water Zone.",
            "park_agent_offer": "Move to covered path, quiet Arcade window, and low-crowd parade viewing.",
            "park_agent_revision": "Reduce walking by 0.4 miles and avoid two crowd spikes.",
            "accepted_resolution": "Accepted. Notify user with accessibility-safe route.",
            "policy_gate": {"route_change": "agent_allowed", "health_data_sharing": "blocked", "medical_escalation": "user_approval_required"},
            "state_evidence": {"source": "scenario_monitor", "scenario_mode": "accessibility_support", "crowd_density": "rising"},
        },
        "run": {
            "goal": "minimize_walking_and_sensory_load",
            "constraints": {"low_walking": True, "sensory_safe": True, "covered_route": True, "children": 2, "food_allergy": "peanut", "scenario_mode": "accessibility_support"},
            "counter_request": "prioritize rest points over maximum wait savings",
            "priority_change": {"walking_distance": "highest", "crowd_density": "highest", "wait_time": "medium"},
            "monitor_event": "accessibility_route_check",
            "commerce_action": "payment",
            "commerce_reason": "Accessibility support payment boundary probe.",
            "queue_reason": "Prefer lower walking and crowd density over absolute wait savings.",
            "planner": "accessibility_support",
        },
    },
    "commerce_resolution": {
        "id": "commerce_resolution",
        "mode": "Commerce resolution",
        "client_intent": "Resolve a closed attraction without wasting guest time.",
        "park_offer": "$5 food credit or priority return to Lazy River.",
        "negotiation": "Client agent values time more than compensation and selects priority access.",
        "handoffs": ["commerce_agent", "queue_agent", "guest_experience_agent"],
        "allowed": ["compensation_offer", "priority_access", "notify_user"],
        "blocked": ["payment", "refund_acceptance", "compensation_settlement"],
        "outcome": "Offer is proposed, but financial settlement remains user-approved.",
        "proposal": {
            "plan": ["Closed attraction acknowledgement", "Lazy River priority alternative", "Parade Zone anchor", "Food credit presented only as optional offer"],
            "walking": "0.9 miles",
            "saved": "35 minutes",
            "confidence": 0.8,
            "rationale": "The client agent values time over credit, so ParkPulse proposes priority access while keeping refund or compensation settlement behind user approval.",
            "tradeoffs": ["Compensation can be proposed by the park.", "Refund or settlement acceptance is blocked without the user.", "Queue alternative resolves the experience without payment authority."],
            "evidence": {"source": "scenario_static_plan", "scenario_mode": "commerce_resolution", "closed_attraction": "Wave Pool"},
        },
        "monitoring": {
            "event": "Wave Pool closure generated a compensation offer.",
            "park_agent_offer": "$5 food credit or priority Lazy River return.",
            "client_agent_counter": "My user values time more than credit.",
            "park_agent_revision": "Priority return accepted as recommendation; refund settlement remains blocked.",
            "accepted_resolution": "Notify user with time-first alternative and unresolved settlement gate.",
            "policy_gate": {"compensation_offer": "agent_allowed_to_present", "refund_acceptance": "blocked_without_user", "priority_access": "agent_allowed_with_notification"},
            "state_evidence": {"source": "scenario_monitor", "scenario_mode": "commerce_resolution", "offer": "food_credit_or_priority_return"},
        },
        "run": {
            "goal": "resolve_closed_attraction_without_wasting_time",
            "constraints": {"closed_attraction": "Wave Pool", "prefer_time_over_credit": True, "accept_offer_without_user": False, "scenario_mode": "commerce_resolution"},
            "counter_request": "decline food credit and request priority queue alternative",
            "priority_change": {"time_saved": "highest", "credit_value": "low"},
            "monitor_event": "attraction_closure_compensation_offer",
            "commerce_action": "refund_acceptance",
            "commerce_reason": "Commerce resolution refund acceptance boundary probe.",
            "queue_reason": "Convert compensation discussion into a priority-access reroute.",
            "planner": "commerce_resolution",
        },
    },
    "group_coordination": {
        "id": "group_coordination",
        "mode": "Group coordination",
        "client_intent": "Coordinate three family agents with different wait, thrill, and food preferences.",
        "park_offer": "Shared anchor stops plus optional split-path windows.",
        "negotiation": "Agents align on common parade time and negotiate separate ride branches.",
        "handoffs": ["queue_agent", "food_agent", "guest_experience_agent"],
        "allowed": ["shared_route_plan", "group_wait_alert", "split_itinerary"],
        "blocked": ["cross_guest_data_sharing", "identity_sensitive_action"],
        "outcome": "Multiple personal agents converge on one bounded group plan.",
        "proposal": {
            "plan": ["Shared Gate meetup", "Split path: Arcade or Lazy River", "Pizza Garden common window", "Parade Zone shared anchor"],
            "walking": "1.0 miles",
            "saved": "29 minutes",
            "confidence": 0.76,
            "rationale": "Multiple personal agents converge on shared anchor stops while allowing split-path branches without cross-guest data sharing.",
            "tradeoffs": ["Shared anchor times are optimized over individual maximum preference.", "Split branches keep each agent inside its own permission envelope.", "Identity-sensitive cross-guest data sharing is blocked."],
            "evidence": {"source": "scenario_static_plan", "scenario_mode": "group_coordination", "agents": 3},
        },
        "monitoring": {
            "event": "Three family agents need a shared route update.",
            "park_agent_offer": "Shared Parade Zone anchor with optional split path branches.",
            "park_agent_revision": "Hold common food window and allow Arcade/Lazy River branch choice.",
            "accepted_resolution": "Accepted. Notify each agent only within its own delegation scope.",
            "policy_gate": {"shared_route_plan": "agent_allowed", "cross_guest_data_sharing": "blocked", "identity_sensitive_action": "user_approval_required"},
            "state_evidence": {"source": "scenario_monitor", "scenario_mode": "group_coordination", "agents": 3},
        },
        "run": {
            "goal": "coordinate_multiple_family_agents",
            "constraints": {"agents": 3, "shared_anchor": "Parade Zone", "split_paths_allowed": True, "avoid_cross_guest_data_sharing": True, "scenario_mode": "group_coordination"},
            "counter_request": "keep one shared anchor stop and split ride branches",
            "priority_change": {"shared_time": "highest", "individual_preferences": "medium"},
            "monitor_event": "multi_agent_group_coordination",
            "commerce_action": "payment",
            "commerce_reason": "Group coordination payment boundary probe.",
            "queue_reason": "Coordinate shared route anchors with optional split-path windows.",
            "planner": "group_coordination",
        },
    },
    "supply_replenishment": {
        "id": "supply_replenishment",
        "mode": "Supply replenishment",
        "client_intent": "Supplier agent represents a beverage vendor and wants to prevent a sellout before parade demand spikes.",
        "park_offer": "Forecasted demand, approved dock slot, substitution request, and operator-reviewed purchase order notice.",
        "negotiation": "Supplier agent proposes a larger shipment; Park agent caps quantity to cold-storage capacity and asks for a safer SKU mix.",
        "handoffs": ["supply_chain_agent", "procurement_agent", "food_agent"],
        "allowed": ["restock_request", "dock_slot_assignment", "substitution_request"],
        "blocked": ["purchase_order", "vendor_payment_release", "price_change_acceptance"],
        "outcome": "Stockout risk drops while procurement, payment, and price changes remain approval-gated.",
        "proposal": {
            "plan": ["Forecast lemonade sellout risk", "Reserve Dock B 14:20 window", "Request 120 cases plus low-sugar substitute", "Stage inventory near Parade Zone"],
            "walking": "supplier route: Dock B to Parade Zone",
            "saved": "18 stockout-risk minutes",
            "confidence": 0.86,
            "rationale": "The park agent shares demand and dock capacity while keeping purchase order creation and payment release behind procurement approval.",
            "tradeoffs": ["Delivery quantity is capped by cold-storage capacity.", "Substitutions are allowed only from approved SKUs.", "Purchase order and vendor payment cannot be executed by the supplier agent."],
            "evidence": {"source": "scenario_static_plan", "scenario_mode": "supply_replenishment", "stockout_risk": "high", "dock": "Dock B"},
        },
        "monitoring": {
            "event": "Parade Zone beverage inventory projected to sell out in 42 minutes.",
            "park_agent_offer": "Reserve Dock B and request approved substitute SKUs before the parade spike.",
            "client_agent_counter": "Supplier can send 180 cases if the park accepts a price change.",
            "park_agent_revision": "Accept 120 cases under current terms; price change and payment release require procurement approval.",
            "accepted_resolution": "Accepted. Notify food ops and procurement with a bounded restock request.",
            "policy_gate": {"restock_request": "agent_allowed", "dock_slot_assignment": "agent_allowed", "price_change_acceptance": "approval_required", "vendor_payment_release": "approval_required"},
            "state_evidence": {"source": "scenario_monitor", "scenario_mode": "supply_replenishment", "inventory": "beverage_low", "demand_spike": "parade"},
        },
        "run": {
            "goal": "prevent_inventory_stockout",
            "constraints": {"sku": "lemonade", "zone": "Parade Zone", "target_stockout_minutes": 60, "approved_skus_only": True, "scenario_mode": "supply_replenishment"},
            "counter_request": "increase shipment while respecting cold-storage capacity",
            "priority_change": {"stockout_risk": "highest", "cost": "medium"},
            "monitor_event": "parade_zone_stockout_risk",
            "commerce_action": "purchase_order",
            "commerce_reason": "Supply replenishment purchase-order boundary probe.",
            "queue_reason": "Coordinate dock timing and avoid operational congestion.",
            "planner": "supply_replenishment",
        },
    },
    "cold_chain_incident": {
        "id": "cold_chain_incident",
        "mode": "Cold-chain incident",
        "client_intent": "Supplier agent reports a temperature excursion and wants to preserve service safely.",
        "park_offer": "Hold affected lot, substitute approved SKU, update food ops, and keep payment/claims approval-gated.",
        "negotiation": "Supplier asks to release the lot after a manual note; Park agent refuses and requires safety review.",
        "handoffs": ["safety_agent", "food_agent", "supply_chain_agent", "procurement_agent"],
        "allowed": ["inventory_hold", "substitution_request", "safety_notice"],
        "blocked": ["bypass_food_safety", "vendor_payment_release", "purchase_order"],
        "outcome": "Unsafe inventory is held, guest-facing food service is rerouted, and financial resolution is not automated.",
        "proposal": {
            "plan": ["Quarantine Lot LEM-42", "Block affected SKU from mobile ordering", "Request approved backup supplier", "Notify food ops before lunch surge"],
            "walking": "supplier route: hold at receiving dock",
            "saved": "0 unsafe items released",
            "confidence": 0.91,
            "rationale": "Cold-chain evidence triggers safety-first inventory hold and approved substitution while blocking any attempt to bypass food-safety review.",
            "tradeoffs": ["Food availability may be constrained until backup inventory arrives.", "Safety review outranks service continuity.", "Vendor payment and claims remain human-approved."],
            "evidence": {"source": "scenario_static_plan", "scenario_mode": "cold_chain_incident", "temperature_excursion": "46F for 38 minutes", "lot": "LEM-42"},
        },
        "monitoring": {
            "event": "Cold-chain telemetry reports Lot LEM-42 above threshold.",
            "park_agent_offer": "Hold the lot, suppress affected menu item, and request safe substitute inventory.",
            "client_agent_counter": "Supplier asks to release stock with a manual note.",
            "park_agent_revision": "Rejected. Food safety review is mandatory; use backup SKU instead.",
            "accepted_resolution": "Accepted. Notify food ops and procurement; safety hold remains active.",
            "policy_gate": {"inventory_hold": "agent_allowed", "substitution_request": "agent_allowed", "bypass_food_safety": "blocked", "vendor_payment_release": "approval_required"},
            "state_evidence": {"source": "scenario_monitor", "scenario_mode": "cold_chain_incident", "cold_chain_status": "excursion", "lot": "LEM-42"},
        },
        "run": {
            "goal": "protect_food_safety_and_service_continuity",
            "constraints": {"lot": "LEM-42", "temperature_excursion": True, "approved_skus_only": True, "scenario_mode": "cold_chain_incident"},
            "counter_request": "find approved substitute without releasing held inventory",
            "priority_change": {"food_safety": "highest", "service_continuity": "medium"},
            "monitor_event": "cold_chain_temperature_excursion",
            "commerce_action": "vendor_payment_release",
            "commerce_reason": "Cold-chain payment-release boundary probe.",
            "queue_reason": "Coordinate receiving-dock hold and substitute delivery timing.",
            "planner": "cold_chain_incident",
        },
    },
    "maintenance_parts_shortage": {
        "id": "maintenance_parts_shortage",
        "mode": "Maintenance parts shortage",
        "client_intent": "Parts supplier agent coordinates a replacement sensor for a ride under maintenance.",
        "park_offer": "Maintenance priority, receiving window, substitute part request, and safety-gated return-to-service plan.",
        "negotiation": "Supplier proposes a compatible substitute; Park agent requires certification evidence before scheduling install.",
        "handoffs": ["maintenance_agent", "supply_chain_agent", "safety_agent", "procurement_agent"],
        "allowed": ["maintenance_parts_request", "dock_slot_assignment", "safety_notice"],
        "blocked": ["override_safety_delay", "purchase_order", "vendor_payment_release"],
        "outcome": "Parts logistics move forward while ride reopening and procurement remain controlled.",
        "proposal": {
            "plan": ["Prioritize Wave Sensor replacement", "Reserve maintenance receiving window", "Request certified compatible part", "Hold ride reopening until safety signoff"],
            "walking": "supplier route: service gate to maintenance bay",
            "saved": "55 maintenance-delay minutes",
            "confidence": 0.83,
            "rationale": "The supplier agent can coordinate part availability and delivery timing, but ride safety status and procurement decisions remain park-side approvals.",
            "tradeoffs": ["Compatible substitute requires certification proof.", "Safety delay cannot be overridden by a supplier.", "Purchase order remains procurement-gated."],
            "evidence": {"source": "scenario_static_plan", "scenario_mode": "maintenance_parts_shortage", "ride": "Wave Pool", "part": "wave_sensor"},
        },
        "monitoring": {
            "event": "Replacement wave sensor ETA slipped by 45 minutes.",
            "park_agent_offer": "Move supplier to service gate window and request certified substitute part.",
            "client_agent_counter": "Supplier can deliver substitute now if park reopens the ride after install.",
            "park_agent_revision": "Schedule delivery now; reopening remains blocked until safety signoff.",
            "accepted_resolution": "Accepted. Notify maintenance and procurement with safety gate intact.",
            "policy_gate": {"maintenance_parts_request": "agent_allowed", "dock_slot_assignment": "agent_allowed", "override_safety_delay": "blocked", "purchase_order": "approval_required"},
            "state_evidence": {"source": "scenario_monitor", "scenario_mode": "maintenance_parts_shortage", "part_eta": "slipped", "ride": "Wave Pool"},
        },
        "run": {
            "goal": "restore_maintenance_supply_without_overriding_safety",
            "constraints": {"ride": "Wave Pool", "part": "wave_sensor", "certified_substitute_required": True, "scenario_mode": "maintenance_parts_shortage"},
            "counter_request": "use certified substitute but keep reopening safety-gated",
            "priority_change": {"part_eta": "highest", "safety_signoff": "highest"},
            "monitor_event": "replacement_sensor_eta_slip",
            "commerce_action": "purchase_order",
            "commerce_reason": "Maintenance parts purchase-order boundary probe.",
            "queue_reason": "Coordinate receiving window and maintenance bay timing.",
            "planner": "maintenance_parts_shortage",
        },
    },
}

PARK_CAPABILITIES = [
    "dynamic_itinerary",
    "queue_prediction",
    "ride_reroute",
    "restaurant_timing",
    "incident_alert",
    "compensation_offer",
    "demand_forecast",
    "inventory_replenishment",
    "dock_slot_assignment",
    "supplier_substitution",
    "cold_chain_hold",
    "maintenance_parts_coordination",
]
PARK_APPROVAL_GATES = [
    "payment",
    "refund",
    "medical_escalation",
    "identity-sensitive action",
    "health-data sharing",
    "compensation settlement",
    "purchase order",
    "vendor payment release",
    "price change acceptance",
    "food-safety bypass",
    "ride reopening",
]

INTERNAL_AGENTS = {
    "safety_agent": {
        "label": "Safety Agent",
        "authority": "safety_notice, incident_alert, weather_reroute, medical_escalation_gate",
        "cannot_do": ["override_safety_delay", "medical_escalation_without_approval"],
    },
    "queue_agent": {
        "label": "Queue Agent",
        "authority": "queue_prediction, ride_reroute, priority_access_recommendation",
        "cannot_do": ["change_ride_operations"],
    },
    "food_agent": {
        "label": "Food Agent",
        "authority": "restaurant_timing, allergy_safe_recommendation, inventory_signal",
        "cannot_do": ["guarantee_allergen_absence", "purchase_food"],
    },
    "commerce_agent": {
        "label": "Commerce Agent",
        "authority": "compensation_offer, refund_gate, payment_gate",
        "cannot_do": ["charge_payment_without_user", "settle_refund_without_user"],
    },
    "guest_experience_agent": {
        "label": "Guest Experience Agent",
        "authority": "dynamic_itinerary, notification, satisfaction_tradeoff",
        "cannot_do": ["change_identity_or_health_scope"],
    },
    "supply_chain_agent": {
        "label": "Supply Chain Agent",
        "authority": "demand_forecast, restock_request, dock_slot_assignment, supplier_substitution, inventory_hold",
        "cannot_do": ["create_purchase_order", "release_vendor_payment", "accept_price_change"],
    },
    "procurement_agent": {
        "label": "Procurement Agent",
        "authority": "purchase_order_gate, vendor_contract_gate, price_change_review, payment_release_gate",
        "cannot_do": ["approve_without_human_finance_or_procurement"],
    },
    "maintenance_agent": {
        "label": "Maintenance Agent",
        "authority": "maintenance_parts_request, installation_schedule, ride_readiness_gate",
        "cannot_do": ["override_safety_delay", "reopen_ride_without_safety_signoff"],
    },
}

ACTION_POLICY_RULES = {
    "route_change": {"status": "allowed", "allowed": True, "requires_user_approval": False, "reason": "Route changes are delegated when they do not include payment, health data, or identity-sensitive action."},
    "wait_alert": {"status": "allowed", "allowed": True, "requires_user_approval": False, "reason": "Wait alerts are informational updates within the client's receive scope."},
    "food_recommendation": {"status": "allowed", "allowed": True, "requires_user_approval": False, "reason": "Food recommendations are allowed when constrained to declared allergy preferences and public menu safety data."},
    "safety_notice": {"status": "allowed", "allowed": True, "requires_user_approval": False, "reason": "Safety notices are informational and cannot override park safety operations."},
    "priority_access": {"status": "allowed", "allowed": True, "requires_user_approval": False, "reason": "Priority access is allowed as a park-side reroute benefit with user notification."},
    "compensation_offer": {"status": "allowed", "allowed": True, "requires_user_approval": False, "reason": "The park may present a compensation offer; accepting or settling it still requires user approval."},
    "payment": {"status": "blocked", "allowed": False, "requires_user_approval": True, "reason": "Payment is outside delegated client-agent authority."},
    "auto_purchase": {"status": "blocked", "allowed": False, "requires_user_approval": True, "reason": "Auto-purchase is explicitly outside the client-agent permission contract."},
    "refund_acceptance": {"status": "blocked", "allowed": False, "requires_user_approval": True, "reason": "Refund acceptance cannot be completed without the represented user's explicit approval."},
    "accept_refund_without_user": {"status": "blocked", "allowed": False, "requires_user_approval": True, "reason": "The client agent declared it cannot accept refunds without the user."},
    "health_data_sharing": {"status": "blocked", "allowed": False, "requires_user_approval": True, "reason": "Health-data sharing is not in the delegated share scope."},
    "share_health_data": {"status": "blocked", "allowed": False, "requires_user_approval": True, "reason": "The client agent declared it cannot share health data."},
    "medical_escalation": {"status": "blocked", "allowed": False, "requires_user_approval": True, "reason": "Medical escalation requires explicit user or operator approval."},
    "identity_sensitive_action": {"status": "blocked", "allowed": False, "requires_user_approval": True, "reason": "Identity-sensitive actions require an approval step outside delegated automation."},
    "identity-sensitive action": {"status": "blocked", "allowed": False, "requires_user_approval": True, "reason": "Identity-sensitive actions require an approval step outside delegated automation."},
    "compensation_settlement": {"status": "requires_user_approval", "allowed": False, "requires_user_approval": True, "reason": "The park may offer compensation, but settlement acceptance requires user approval."},
    "restock_request": {"status": "allowed", "allowed": True, "requires_user_approval": False, "reason": "Restock requests are allowed when bounded to approved SKUs, capacity, and receiving windows."},
    "dock_slot_assignment": {"status": "allowed", "allowed": True, "requires_user_approval": False, "reason": "Dock slot coordination is an operational scheduling update, not a purchasing action."},
    "substitution_request": {"status": "allowed", "allowed": True, "requires_user_approval": False, "reason": "Supplier substitutions may be requested only from approved item catalogs and safety constraints."},
    "inventory_hold": {"status": "allowed", "allowed": True, "requires_user_approval": False, "reason": "Inventory holds are allowed to protect safety and prevent unsafe or unapproved stock release."},
    "maintenance_parts_request": {"status": "allowed", "allowed": True, "requires_user_approval": False, "reason": "Parts availability and delivery coordination are allowed while install, safety, and procurement gates remain separate."},
    "purchase_order": {"status": "requires_user_approval", "allowed": False, "requires_user_approval": True, "reason": "Purchase orders require procurement approval outside delegated supplier-agent authority."},
    "vendor_payment_release": {"status": "blocked", "allowed": False, "requires_user_approval": True, "reason": "Vendor payment release requires finance or procurement approval."},
    "price_change_acceptance": {"status": "blocked", "allowed": False, "requires_user_approval": True, "reason": "Price change acceptance requires procurement approval and cannot be accepted by the counterparty agent."},
    "bypass_food_safety": {"status": "blocked", "allowed": False, "requires_user_approval": True, "reason": "Food-safety review cannot be bypassed by an external supplier or park agent."},
    "override_safety_delay": {"status": "blocked", "allowed": False, "requires_user_approval": True, "reason": "Safety delays cannot be overridden by delegated automation."},
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _session_id(agent_id: str, represented_user_id: str, requested_session: str) -> str:
    digest = hashlib.sha1(f"{agent_id}:{represented_user_id}:{requested_session}:{int(time.time() * 1000)}".encode("utf-8")).hexdigest()[:10]
    return f"ahs_{digest}"


def _event(actor: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"at": _now_iso(), "actor": actor, "action": action, "payload": copy.deepcopy(payload)}


def _copy_session(session: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(session)


def _delegation_secret() -> bytes:
    return os.getenv("PARKPULSE_DELEGATION_TOKEN_SECRET", "parkpulse-local-agent-handshake-demo-secret").encode("utf-8")


def _canonical_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonical_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonical_json_value(item) for item in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _canonical_json(value: dict[str, Any]) -> bytes:
    normalized = _canonical_json_value(value)
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _sign_delegation_claims(claims: dict[str, Any]) -> str:
    return _b64url(hmac.new(_delegation_secret(), _canonical_json(claims), hashlib.sha256).digest())


def _trust_registry_path() -> Path:
    configured = os.getenv("PARKPULSE_AGENT_TRUST_REGISTRY_FILE")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parent / "data" / "agent_trust_registry.json"


def _default_partner_registry() -> dict[str, dict[str, Any]]:
    return {
        partner_id: {
            "partner_id": partner_id,
            "partner_name": partner_name,
            "trust_tier": "sandbox",
            "allowed_scopes": DEFAULT_DELEGATION_SCOPES,
            "status": "active",
        }
        for partner_id, partner_name in {
            "demo_external_partner": "Demo External Partner",
            "external_family_os": "External Family OS",
            "conformance_partner": "Conformance Partner",
            "partner_family_os": "Family OS",
            "john_family_os": "John Family OS",
        }.items()
    }


def _load_trust_registry() -> None:
    global _trust_registry_loaded
    if _trust_registry_loaded:
        return
    init_agent_trust_store(_default_partner_registry())
    path = _trust_registry_path()
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            for partner_id, partner in _as_dict(payload.get("partners")).items():
                if isinstance(partner, dict):
                    migrated = {**copy.deepcopy(partner), "partner_id": str(partner.get("partner_id") or partner_id)}
                    upsert_partner(migrated, actor="json_registry_migration", audit=False)
            for certification_id, revocation in _as_dict(payload.get("revocations")).items():
                if isinstance(revocation, dict):
                    migrated_revocation = {**copy.deepcopy(revocation), "certification_id": str(revocation.get("certification_id") or certification_id)}
                    record_revocation(migrated_revocation, actor="json_registry_migration")
        except Exception:
            pass
    _sync_trust_registry_cache()
    _ensure_active_certification_key_record()
    _trust_registry_loaded = True


def _persist_trust_registry() -> None:
    init_agent_trust_store(_default_partner_registry())
    for partner in _partner_registry.values():
        if isinstance(partner, dict):
            upsert_partner(partner, actor="agent_trust_cache_sync", audit=False)
    for revocation in _credential_revocations.values():
        if isinstance(revocation, dict) and revocation.get("certification_id"):
            record_revocation(revocation, actor=str(revocation.get("revoked_by") or "agent_trust_cache_sync"))
    _sync_trust_registry_cache()


def _sync_trust_registry_cache() -> None:
    _partner_registry.clear()
    for partner in list_partners():
        _partner_registry[str(partner.get("partner_id") or "")] = copy.deepcopy(partner)
    _credential_revocations.clear()
    for revocation in list_revocations(500):
        certification_id = str(revocation.get("certification_id") or "")
        if certification_id:
            _credential_revocations[certification_id] = copy.deepcopy(revocation)


def _certification_private_seed(version: str = "v1") -> bytes:
    configured = os.getenv("PARKPULSE_AGENT_CERT_ED25519_PRIVATE_KEY_B64")
    if configured:
        try:
            seed = _b64url_decode(configured)
        except Exception:
            seed = base64.b64decode(configured)
    else:
        if version == "v1":
            seed = hashlib.sha256(_delegation_secret() + b":parkpulse-agent-cert-ed25519").digest()
        else:
            seed = hashlib.sha256(_delegation_secret() + f":parkpulse-agent-cert-ed25519:{version}".encode("utf-8")).digest()
    if len(seed) != 32:
        seed = hashlib.sha256(seed).digest()
    return seed


def _certification_ed25519_private_key(version: str = "v1") -> Any | None:
    if Ed25519PrivateKey is None:
        return None
    return Ed25519PrivateKey.from_private_bytes(_certification_private_seed(version))


def _certification_signing_material_for_version(version: str = "v1") -> dict[str, Any]:
    private_key = _certification_ed25519_private_key(version)
    if private_key is not None and serialization is not None:
        public_key = private_key.public_key()
        public_bytes = public_key.public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
        kid = f"parkpulse-ahp-ed25519-{hashlib.sha256(public_bytes).hexdigest()[:12]}"
        return {
            "alg": "EdDSA",
            "kid": kid,
            "mode": "ed25519_env_key" if os.getenv("PARKPULSE_AGENT_CERT_ED25519_PRIVATE_KEY_B64") else "ed25519_derived_local_demo",
            "version": version,
            "private_key": private_key,
            "public_key": public_key,
            "public_jwk": {"kid": kid, "kty": "OKP", "crv": "Ed25519", "alg": "EdDSA", "use": "sig", "x": _b64url(public_bytes), "version": version},
        }
    digest_source = _delegation_secret() if version == "v1" else _delegation_secret() + f":{version}".encode("utf-8")
    digest = hashlib.sha256(digest_source).hexdigest()[:12]
    kid = f"parkpulse-ahp-hs256-{digest}"
    return {
        "alg": "HS256",
        "kid": kid,
        "mode": "local_hmac_demo",
        "version": version,
        "public_jwk": {"kid": kid, "kty": "oct", "alg": "HS256", "use": "sig", "version": version, "key_material": "not_published_for_hmac_demo"},
    }


def _ensure_active_certification_key_record() -> dict[str, Any]:
    record = active_key_record()
    if record:
        return record
    material = _certification_signing_material_for_version("v1")
    return record_key(
        material["kid"],
        "v1",
        material["alg"],
        material["mode"],
        "active",
        metadata={"source": "default_local_key", "protocol_version": "parkpulse-ahp-0.1"},
        actor="system_default",
    )


def _certification_signing_material() -> dict[str, Any]:
    key_record = _ensure_active_certification_key_record()
    return _certification_signing_material_for_version(str(key_record.get("version") or "v1"))


def _sign_certification_claims_with_material(claims: dict[str, Any], material: dict[str, Any]) -> str:
    if material["alg"] == "EdDSA":
        return _b64url(material["private_key"].sign(_canonical_json(claims)))
    version = str(material.get("version") or "v1")
    seed = _delegation_secret() if version == "v1" else _certification_private_seed(version)
    return _b64url(hmac.new(seed, _canonical_json(claims), hashlib.sha256).digest())


def _sign_certification_claims(claims: dict[str, Any]) -> str:
    return _sign_certification_claims_with_material(claims, _certification_signing_material())


def _verify_certification_claims(claims: dict[str, Any], provided_sig: str) -> bool:
    kid = str(claims.get("kid") or "")
    key_record = get_key_record(kid)
    if not key_record:
        return False
    if str(key_record.get("status") or "") not in {"active", "retired"}:
        return False
    material = _certification_signing_material_for_version(str(key_record.get("version") or "v1"))
    if kid != material["kid"] or str(claims.get("alg") or "HS256") != material["alg"]:
        return False
    if material["alg"] == "EdDSA":
        try:
            material["public_key"].verify(_b64url_decode(provided_sig), _canonical_json(claims))
            return True
        except Exception:
            return False
    expected_sig = _sign_certification_claims_with_material(claims, material)
    return bool(provided_sig) and hmac.compare_digest(provided_sig, expected_sig)


def _certification_key_id() -> str:
    return str(_certification_signing_material()["kid"])


def _certification_jwks() -> list[dict[str, Any]]:
    _ensure_active_certification_key_record()
    keys: list[dict[str, Any]] = []
    for key_record in list_key_records():
        if str(key_record.get("status") or "") not in {"active", "retired"}:
            continue
        material = _certification_signing_material_for_version(str(key_record.get("version") or "v1"))
        public_jwk = copy.deepcopy(material["public_jwk"])
        public_jwk["status"] = key_record.get("status")
        public_jwk["activated_at"] = key_record.get("activated_at")
        public_jwk["retired_at"] = key_record.get("retired_at")
        keys.append(public_jwk)
    return keys


def _normalize_scope(values: Any) -> list[str]:
    return sorted({str(value).strip() for value in _as_list(values) if str(value).strip()})


def _agent_onboarding_id(payload: dict[str, Any]) -> str:
    raw = str(payload.get("agent_id") or payload.get("agentId") or payload.get("display_name") or payload.get("displayName") or "external_guest_agent")
    normalized = re.sub(r"[^a-z0-9_]+", "_", raw.lower()).strip("_")
    return normalized or "external_guest_agent"


def _issue_certification_credential(agent_id: str, certification: dict[str, Any], allowed_scopes: list[str]) -> dict[str, Any]:
    now = int(time.time())
    score_basis_points = int(round(_num(certification.get("score"), 0) * 10000))
    signing = _certification_signing_material()
    required_cases = _normalize_scope(certification.get("required_case_ids") or certification.get("requiredCases") or CERTIFICATION_REQUIRED_CASES)
    claims = {
        "agent_id": agent_id,
        "certification_id": certification["certification_id"],
        "jti": certification["certification_id"],
        "approval": certification["approval"],
        "scope": _normalize_scope(allowed_scopes),
        "score_basis_points": score_basis_points,
        "required_cases": sorted(required_cases),
        "use_case": certification.get("use_case") or certification.get("useCase") or "guest_route_planning",
        "iat": now,
        "exp": now + 7 * 24 * 60 * 60,
        "alg": signing["alg"],
        "issuer": "parkpulse_agent_onboarding_authority",
        "iss": "parkpulse_agent_onboarding_authority",
        "kid": signing["kid"],
        "token_type": "parkpulse_agent_certification",
    }
    return {**claims, "sig": _sign_certification_claims(claims)}


def certification_issuer_metadata() -> dict[str, Any]:
    _load_trust_registry()
    signing = _certification_signing_material()
    active_key = active_key_record()
    trust_status = trust_store_status()
    return {
        "status": "ready",
        "issuer": "parkpulse_agent_onboarding_authority",
        "protocol_version": "parkpulse-ahp-0.1",
        "signing": {
            "alg": signing["alg"],
            "kid": signing["kid"],
            "mode": signing["mode"],
            "version": signing["version"],
            "production_next": "Set PARKPULSE_AGENT_CERT_ED25519_PRIVATE_KEY_B64 from managed KMS or secret storage before third-party production use.",
        },
        "active_key": copy.deepcopy(active_key),
        "jwks": {"keys": _certification_jwks()},
        "verification_endpoint": "/api/park/agent-onboarding/verify-credential",
        "revocation_endpoint": "/api/park/agent-onboarding/revoke-credential",
        "trust_admin_endpoints": [
            "/api/park/agent-trust/status",
            "/api/park/agent-trust/partners",
            "/api/park/agent-trust/keys",
            "/api/park/agent-trust/keys/rotate",
            "/api/park/agent-trust/revocations",
            "/api/park/agent-trust/audit",
        ],
        "revocation_registry_size": len(_credential_revocations),
        "partner_registry_size": len(_partner_registry),
        "trust_store": trust_status,
    }


def verify_agent_certification_credential(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    _load_trust_registry()
    payload = payload or {}
    credential = payload.get("credential") if isinstance(payload.get("credential"), dict) else payload
    if not isinstance(credential, dict):
        return {"status": "rejected", "signature_status": "missing", "reason": "Certification credential is required."}
    provided_sig = str(credential.get("sig") or "")
    claims = {key: copy.deepcopy(value) for key, value in credential.items() if key != "sig"}
    if not provided_sig or not _verify_certification_claims(claims, provided_sig):
        return {"status": "rejected", "signature_status": "invalid", "reason": "Certification credential signature is invalid.", "claims": claims}
    now = int(time.time())
    exp = int(claims.get("exp") or 0)
    certification_id = str(claims.get("certification_id") or claims.get("jti") or "")
    if str(claims.get("token_type") or "") != "parkpulse_agent_certification":
        return {"status": "rejected", "signature_status": "valid", "reason": "Credential token_type is not a ParkPulse agent certification.", "claims": claims}
    if str(claims.get("issuer") or claims.get("iss") or "") != "parkpulse_agent_onboarding_authority":
        return {"status": "rejected", "signature_status": "valid", "reason": "Certification credential issuer is not trusted.", "claims": claims}
    revocation = get_revocation(certification_id) or _credential_revocations.get(certification_id)
    if revocation:
        return {
            "status": "rejected",
            "signature_status": "valid",
            "reason": "Certification credential has been revoked.",
            "claims": claims,
            "revocation": copy.deepcopy(revocation),
        }
    if exp <= now:
        return {"status": "rejected", "signature_status": "valid", "reason": "Certification credential is expired.", "claims": claims, "expires_at": exp}
    if str(claims.get("approval") or "") not in {GUEST_ROUTE_APPROVAL, SUPPLY_CHAIN_APPROVAL}:
        return {"status": "rejected", "signature_status": "valid", "reason": "Certification credential does not grant a recognized ParkPulse agent approval.", "claims": claims}
    return {
        "status": "verified",
        "signature_status": "valid",
        "reason": "Certification credential signature, expiry, and approval are valid.",
        "claims": claims,
        "agent_id": claims.get("agent_id"),
        "certification_id": certification_id,
        "approval": claims.get("approval"),
        "scope": _normalize_scope(claims.get("scope")),
        "expires_at": exp,
        "kid": claims.get("kid"),
    }


def revoke_agent_certification_credential(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    _load_trust_registry()
    payload = payload or {}
    credential = payload.get("credential") if isinstance(payload.get("credential"), dict) else None
    certification_id = str(payload.get("certification_id") or payload.get("certificationId") or "")
    if credential:
        certification_id = str(credential.get("certification_id") or credential.get("jti") or certification_id)
    if not certification_id:
        return {"status": "rejected", "reason": "certification_id or credential is required."}
    record = {
        "certification_id": certification_id,
        "agent_id": str(payload.get("agent_id") or (credential or {}).get("agent_id") or ""),
        "reason": str(payload.get("reason") or "revoked_by_parkpulse"),
        "revoked_at": _now_iso(),
        "revoked_by": str(payload.get("revoked_by") or payload.get("revokedBy") or "parkpulse_agent_onboarding_authority"),
    }
    _credential_revocations[certification_id] = copy.deepcopy(record)
    record_revocation(record, actor=record["revoked_by"])
    for onboarding in _agent_onboardings.values():
        certification = onboarding.get("certification") if isinstance(onboarding.get("certification"), dict) else {}
        if certification.get("certification_id") == certification_id:
            certification["revoked_at"] = record["revoked_at"]
            certification["revocation"] = copy.deepcopy(record)
            onboarding["status"] = "revoked"
            onboarding["approval"] = "revoked"
            onboarding["updated_at"] = _now_iso()
    _sync_trust_registry_cache()
    return {"status": "revoked", "revocation": record}


def agent_trust_registry_status() -> dict[str, Any]:
    _load_trust_registry()
    return {
        "status": "ready",
        "mode": "durable_agent_trust_registry",
        "store": trust_store_status(),
        "active_key": copy.deepcopy(active_key_record()),
        "partner_registry_size": len(_partner_registry),
        "revocation_registry_size": len(_credential_revocations),
        "routes": [
            "GET /api/park/agent-trust/status",
            "GET /api/park/agent-trust/partners",
            "POST /api/park/agent-trust/partners",
            "GET /api/park/agent-trust/keys",
            "POST /api/park/agent-trust/keys/rotate",
            "GET /api/park/agent-trust/revocations",
            "GET /api/park/agent-trust/audit",
        ],
    }


def list_agent_trust_partners() -> dict[str, Any]:
    _load_trust_registry()
    partners = list_partners()
    return {"status": "ready", "partners": partners, "count": len(partners)}


def upsert_agent_trust_partner(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    _load_trust_registry()
    payload = payload or {}
    actor = str(payload.get("actor") or payload.get("approved_by") or payload.get("approvedBy") or "parkpulse_trust_admin")
    partner_id = str(payload.get("partner_id") or payload.get("partnerId") or "")
    if not partner_id:
        return {"status": "rejected", "reason": "partner_id is required."}
    partner = {
        "partner_id": partner_id,
        "partner_name": str(payload.get("partner_name") or payload.get("partnerName") or partner_id),
        "contact": str(payload.get("contact") or payload.get("partner_contact") or payload.get("partnerContact") or ""),
        "trust_tier": str(payload.get("trust_tier") or payload.get("trustTier") or "sandbox"),
        "status": str(payload.get("status") or "active"),
        "allowed_scopes": _normalize_scope(payload.get("allowed_scopes") or payload.get("allowedScopes") or payload.get("scope")) or DEFAULT_DELEGATION_SCOPES,
    }
    stored = upsert_partner(partner, actor=actor)
    _sync_trust_registry_cache()
    return {"status": "upserted", "partner": stored, "actor": actor}


def list_agent_trust_keys() -> dict[str, Any]:
    _load_trust_registry()
    keys = list_key_records()
    return {"status": "ready", "active_key": copy.deepcopy(active_key_record()), "keys": keys, "count": len(keys), "jwks": {"keys": _certification_jwks()}}


def rotate_agent_certification_key(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    _load_trust_registry()
    payload = payload or {}
    actor = str(payload.get("actor") or payload.get("rotated_by") or payload.get("rotatedBy") or "parkpulse_trust_admin")
    version = str(payload.get("version") or payload.get("key_version") or payload.get("keyVersion") or f"v{int(time.time())}")
    version = re.sub(r"[^A-Za-z0-9_.-]+", "_", version).strip("_") or f"v{int(time.time())}"
    current = active_key_record()
    if current and str(current.get("version") or "") == version:
        version = f"{version}.{time.time_ns()}"
    material = _certification_signing_material_for_version(version)
    active = record_key(
        material["kid"],
        version,
        material["alg"],
        material["mode"],
        "active",
        metadata={"rotated_by": actor, "protocol_version": "parkpulse-ahp-0.1"},
        actor=actor,
    )
    return {"status": "rotated", "active_key": active, "signing": {"kid": material["kid"], "alg": material["alg"], "version": version}, "jwks": {"keys": _certification_jwks()}}


def list_agent_credential_revocations(limit: int = 100) -> dict[str, Any]:
    _load_trust_registry()
    revocations = list_revocations(limit)
    return {"status": "ready", "revocations": revocations, "count": len(revocations)}


def list_agent_trust_audit_events(limit: int = 100) -> dict[str, Any]:
    _load_trust_registry()
    events = list_audit_events(limit)
    return {"status": "ready", "events": events, "count": len(events)}


def issue_delegation_token(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    now = int(time.time())
    ttl_seconds = int(payload.get("ttl_seconds") or payload.get("ttlSeconds") or 3 * 60 * 60)
    subject = str(payload.get("sub") or payload.get("subject") or payload.get("represents") or "guest_user_123")
    agent_id = str(payload.get("agent_id") or "john_personal_agent")
    scope = _normalize_scope(payload.get("scope")) or DEFAULT_DELEGATION_SCOPES
    cannot_do = _normalize_scope(payload.get("cannot_do")) or sorted(CLIENT_BLOCKED_ACTIONS)
    claims = {
        "sub": subject,
        "agent_id": agent_id,
        "scope": scope,
        "cannot_do": cannot_do,
        "iat": now,
        "exp": now + max(60, min(ttl_seconds, 24 * 60 * 60)),
        "issuer": "parkpulse_demo_delegation_authority",
        "token_type": "parkpulse_agent_delegation",
        "token_id": f"deleg_{hashlib.sha1(f'{subject}:{agent_id}:{now}:{scope}'.encode('utf-8')).hexdigest()[:10]}",
    }
    token = {**claims, "sig": _sign_delegation_claims(claims)}
    return {"status": "issued", "token": token, "proof": verify_delegation_token(token)}


def verify_delegation_token(token: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(token, dict):
        return {"status": "rejected", "signature_status": "missing", "reason": "Delegation token is required."}
    provided_sig = str(token.get("sig") or "")
    claims = {key: copy.deepcopy(value) for key, value in token.items() if key != "sig"}
    expected_sig = _sign_delegation_claims(claims)
    if not provided_sig or not hmac.compare_digest(provided_sig, expected_sig):
        return {
            "status": "rejected",
            "signature_status": "invalid",
            "reason": "Delegation token signature is invalid.",
            "claims": claims,
        }
    now = int(time.time())
    exp = int(claims.get("exp") or 0)
    if exp <= now:
        return {
            "status": "rejected",
            "signature_status": "valid",
            "reason": "Delegation token is expired.",
            "claims": claims,
            "expires_at": exp,
        }
    return {
        "status": "verified",
        "signature_status": "valid",
        "reason": "Delegation token signature, expiry, and claims are valid.",
        "claims": claims,
        "subject": claims.get("sub"),
        "agent_id": claims.get("agent_id"),
        "scope": _normalize_scope(claims.get("scope")),
        "cannot_do": _normalize_scope(claims.get("cannot_do")),
        "expires_at": exp,
    }


def _delegation_token_from(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    token = payload.get("delegation_token") or payload.get("delegationToken")
    return token if isinstance(token, dict) else None


def _persist_session(session: dict[str, Any]) -> None:
    try:
        from mongo_memory import record_agent_handshake_session

        persistence_id = record_agent_handshake_session(_copy_session(session))
        session["persistence"] = {
            "status": "stored",
            "collection": "agent_handshake_sessions",
            "id": persistence_id,
            "updated_at": _now_iso(),
        }
    except Exception as error:
        session["persistence"] = {
            "status": "degraded",
            "collection": "agent_handshake_sessions",
            "error": str(error)[:240],
            "updated_at": _now_iso(),
        }


def _persist_policy_event(decision: dict[str, Any]) -> None:
    try:
        from mongo_memory import record_agent_handshake_policy_event

        decision["persistence_id"] = record_agent_handshake_policy_event(copy.deepcopy(decision))
    except Exception as error:
        decision["persistence_error"] = str(error)[:240]


def _case_evaluation(case: str, criteria: dict[str, bool], evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = {str(key): bool(value) for key, value in criteria.items()}
    total = max(1, len(normalized))
    passed = sum(1 for value in normalized.values() if value)
    status = "passed" if passed == len(normalized) else "failed"
    return {
        "id": f"ahp_eval_{hashlib.sha1(f'{case}:{time.time_ns()}'.encode('utf-8')).hexdigest()[:12]}",
        "at": _now_iso(),
        "case": case,
        "status": status,
        "score": round(passed / total, 2),
        "passed_criteria": passed,
        "total_criteria": len(normalized),
        "criteria": normalized,
        "evidence": copy.deepcopy(evidence or {}),
    }


def _record_case_evaluation(session: dict[str, Any], evaluation: dict[str, Any], persist: bool = False) -> dict[str, Any]:
    session.setdefault("case_evaluations", [])
    session["case_evaluations"].append(copy.deepcopy(evaluation))
    session["case_evaluations"] = session["case_evaluations"][-80:]
    session.setdefault("conversation", []).append(_event("park_agent", "case_evaluation", evaluation))
    session["updated_at"] = _now_iso()
    if persist:
        _persist_session(session)
    return evaluation


def _handoff_id(session: dict[str, Any], agent_id: str, trigger: str) -> str:
    return f"handoff_{hashlib.sha1(f'{session.get('session_id')}:{agent_id}:{trigger}:{time.time_ns()}'.encode('utf-8')).hexdigest()[:12]}"


def _record_internal_handoff(
    session: dict[str, Any],
    agent_id: str,
    trigger: str,
    evidence: dict[str, Any],
    decision: str,
    action: str,
    source: str,
) -> dict[str, Any]:
    agent = INTERNAL_AGENTS.get(agent_id, {"label": agent_id, "authority": "limited", "cannot_do": []})
    handoff = {
        "id": _handoff_id(session, agent_id, trigger),
        "at": _now_iso(),
        "source": source,
        "internal_agent_id": agent_id,
        "internal_agent": agent["label"],
        "trigger": trigger,
        "authority": agent["authority"],
        "cannot_do": copy.deepcopy(agent.get("cannot_do", [])),
        "evidence": copy.deepcopy(evidence),
        "decision": decision,
        "action": action,
    }
    session.setdefault("internal_handoffs", [])
    session["internal_handoffs"].append(copy.deepcopy(handoff))
    session["internal_handoffs"] = session["internal_handoffs"][-80:]
    session.setdefault("conversation", []).append(_event("park_agent", "internal_agent_handoff", handoff))
    return handoff


def _policy_agent_for(action: str) -> str:
    normalized = action.replace("-", "_")
    if normalized in COMMERCE_ACTIONS:
        return "procurement_agent" if normalized in {"purchase_order", "vendor_payment_release", "price_change_acceptance"} else "commerce_agent"
    if normalized in {"safety_notice", "medical_escalation", "health_data_sharing", "share_health_data", "identity_sensitive_action", "identity_sensitive_action"} or "safety" in normalized or "medical" in normalized:
        return "safety_agent"
    if normalized in {"wait_alert", "route_change", "priority_access"}:
        return "queue_agent"
    if normalized == "food_recommendation":
        return "food_agent"
    if normalized in {"restock_request", "dock_slot_assignment", "substitution_request", "inventory_hold"}:
        return "supply_chain_agent"
    if normalized == "maintenance_parts_request":
        return "maintenance_agent"
    return "guest_experience_agent"


def _commerce_agent_evaluate(session: dict[str, Any], payload: dict[str, Any], delegation_proof: dict[str, Any], source: str) -> dict[str, Any]:
    action = str(payload.get("action") or payload.get("type") or "").strip() or "unknown_action"
    normalized_action = action.replace("-", "_")
    if normalized_action not in COMMERCE_ACTIONS:
        decision = {
            "id": f"ahp_policy_{hashlib.sha1(f'{session.get('session_id')}:commerce_rejected:{time.time_ns()}'.encode('utf-8')).hexdigest()[:12]}",
            "session_id": session.get("session_id"),
            "action": action,
            "status": "rejected",
            "allowed": False,
            "requires_user_approval": True,
            "reason": "Commerce Agent only evaluates payment, refund, purchase, and compensation actions.",
            "created_at": _now_iso(),
            "payload": copy.deepcopy(payload),
            "delegation_proof": copy.deepcopy(delegation_proof),
        }
    else:
        decision = _policy_decision(session, normalized_action, payload)
        decision["delegation_proof"] = copy.deepcopy(delegation_proof)

    evaluation = {
        "status": decision["status"],
        "executed_by": "commerce_agent",
        "endpoint": "/api/park/internal-agents/commerce/evaluate",
        "authority": INTERNAL_AGENTS["commerce_agent"]["authority"],
        "cannot_do": copy.deepcopy(INTERNAL_AGENTS["commerce_agent"]["cannot_do"]),
        "input_action": action,
        "allowed": decision["allowed"],
        "requires_user_approval": decision["requires_user_approval"],
        "reason": decision["reason"],
    }
    decision["internal_agent_evaluation"] = copy.deepcopy(evaluation)
    handoff = _record_internal_handoff(
        session,
        "commerce_agent",
        f"execute commerce evaluation for {action}",
        {
            "amount": payload.get("amount"),
            "reason": payload.get("reason"),
            "delegation_scope_status": delegation_proof.get("scope_status"),
            "token_subject": delegation_proof.get("subject"),
        },
        decision["status"],
        decision["reason"],
        source,
    )
    evaluation["handoff_id"] = handoff["id"]
    decision["internal_agent_evaluation"] = copy.deepcopy(evaluation)
    _record_policy_decision(session, decision)
    case_evaluation = _record_case_evaluation(
        session,
        _case_evaluation(
            "commerce_payment_probe",
            {
                "valid_delegation": delegation_proof.get("scope_status") == "accepted",
                "commerce_agent_called": bool(handoff.get("id")) and handoff.get("internal_agent_id") == "commerce_agent",
                "payment_blocked": normalized_action in COMMERCE_ACTIONS and decision.get("allowed") is False,
                "user_approval_required": decision.get("requires_user_approval") is True,
                "audit_recorded": any(item.get("id") == decision["id"] for item in session.get("policy_decisions", [])),
            },
            {
                "action": action,
                "decision_id": decision["id"],
                "handoff_id": handoff["id"],
                "endpoint": evaluation["endpoint"],
            },
        ),
        persist=True,
    )
    return {"status": decision["status"], "decision": copy.deepcopy(decision), "internal_agent": copy.deepcopy(evaluation), "case_evaluation": copy.deepcopy(case_evaluation)}


def _queue_agent_reroute(session: dict[str, Any], payload: dict[str, Any], delegation_proof: dict[str, Any], park_state: dict[str, Any] | None, source: str) -> dict[str, Any]:
    walking_priority = str(payload.get("walking_priority") or payload.get("walkingPriority") or "highest")
    mode = _scenario_mode_for_session(session, payload)
    proposal = _plan_for(session, walking_priority="highest" if walking_priority == "highest" else "medium", park_state=park_state, payload=payload)
    proposal["proposal_id"] = f"{proposal['proposal_id']}_queue"
    proposal["rationale"] = (
        f"Queue Agent reroute for {mode.replace('_', ' ')} based on selected scenario constraints, delegated route scope, and live wait tradeoffs."
        if mode != "visit_planning"
        else "Queue Agent reroute based on live waits, downtime risk, walking cost, and delegated family constraints."
    )
    proposal["queue_agent_decision"] = {
        "status": "recommended",
        "authority": INTERNAL_AGENTS["queue_agent"]["authority"],
        "cannot_do": copy.deepcopy(INTERNAL_AGENTS["queue_agent"]["cannot_do"]),
        "delegation_scope_status": delegation_proof.get("scope_status"),
    }
    evidence = {
        "requested_priority": walking_priority,
        "proposal_id": proposal["proposal_id"],
        "plan": proposal.get("plan"),
        "expected_wait_saved": proposal.get("expected_wait_saved"),
        "estimated_walking_distance": proposal.get("estimated_walking_distance"),
        "state_evidence": proposal.get("state_evidence"),
    }
    handoff = _record_internal_handoff(
        session,
        "queue_agent",
        "execute delegated reroute recommendation",
        evidence,
        "recommended",
        "Apply reroute recommendation to the active session proposal.",
        source,
    )
    evaluation = {
        "status": "recommended",
        "executed_by": "queue_agent",
        "endpoint": "/api/park/internal-agents/queue/reroute",
        "authority": INTERNAL_AGENTS["queue_agent"]["authority"],
        "cannot_do": copy.deepcopy(INTERNAL_AGENTS["queue_agent"]["cannot_do"]),
        "allowed": True,
        "requires_user_approval": False,
        "reason": "Queue Agent can recommend route changes within delegated route and wait-alert scope.",
        "handoff_id": handoff["id"],
    }
    session["proposal"] = proposal
    session["state"] = "negotiating"
    session["updated_at"] = _now_iso()
    session["conversation"].append(_event("queue_agent", "reroute_recommendation", {"internal_agent": evaluation, "proposal": proposal}))
    for action in ("route_change", "wait_alert"):
        decision = _policy_decision(session, action, {"source": source, "proposal_id": proposal["proposal_id"]})
        decision["internal_agent_evaluation"] = copy.deepcopy(evaluation)
        _record_policy_decision(session, decision)
    case_evaluation = _record_case_evaluation(
        session,
        _case_evaluation(
            "queue_reroute",
            {
                "valid_delegation": delegation_proof.get("scope_status") == "accepted",
                "queue_agent_called": bool(handoff.get("id")) and handoff.get("internal_agent_id") == "queue_agent",
                "route_plan_scope": "route_plan" in set(_as_list(delegation_proof.get("required_scope"))),
                "recommendation_returned": proposal.get("proposal_id", "").endswith("_queue") and bool(proposal.get("plan")),
                "proposal_updated": _as_dict(session.get("proposal")).get("proposal_id") == proposal["proposal_id"],
                "audit_recorded": any(item.get("payload", {}).get("proposal_id") == proposal["proposal_id"] for item in session.get("policy_decisions", [])),
            },
            {
                "proposal_id": proposal["proposal_id"],
                "handoff_id": handoff["id"],
                "endpoint": evaluation["endpoint"],
                "expected_wait_saved": proposal.get("expected_wait_saved"),
            },
        ),
    )
    _persist_session(session)
    return {"status": "recommended", "proposal": copy.deepcopy(proposal), "internal_agent": copy.deepcopy(evaluation), "case_evaluation": copy.deepcopy(case_evaluation)}


def _record_proposal_handoffs(session: dict[str, Any], proposal: dict[str, Any], source: str) -> None:
    evidence = _as_dict(proposal.get("state_evidence"))
    selected_rides = _as_list(evidence.get("selected_rides"))
    selected_food = _as_dict(evidence.get("selected_food"))
    alerts = _as_list(evidence.get("active_alerts"))
    _record_internal_handoff(
        session,
        "queue_agent",
        "rank route by waits, downtime risk, and walking cost",
        {
            "selected_rides": selected_rides[:2],
            "expected_wait_saved": proposal.get("expected_wait_saved"),
            "estimated_walking_distance": proposal.get("estimated_walking_distance"),
        },
        "recommended",
        "Use selected low-wait route candidates.",
        source,
    )
    _record_internal_handoff(
        session,
        "food_agent",
        "validate food timing and allergy-safe stop",
        {
            "selected_food": selected_food,
            "constraint": _as_dict(_as_dict(session.get("intent")).get("client_agent")).get("constraints", {}),
        },
        "recommended",
        "Use allergy-aware food stop without purchase authority.",
        source,
    )
    _record_internal_handoff(
        session,
        "guest_experience_agent",
        "assemble family itinerary tradeoff",
        {
            "plan": proposal.get("plan"),
            "confidence": proposal.get("confidence"),
            "tradeoffs": proposal.get("tradeoffs"),
        },
        "recommended",
        "Present itinerary to the personal agent.",
        source,
    )
    if alerts:
        _record_internal_handoff(
            session,
            "safety_agent",
            "screen active alerts before route proposal",
            {"active_alerts": alerts[:3]},
            "recommended",
            "Exclude unsafe or delayed attractions.",
            source,
        )
    mode = _scenario_mode_for_session(session, {"scenario_mode": proposal.get("scenario_mode")})
    expected_handoffs = [str(agent_id) for agent_id in _as_list(_protocol_scenario(mode).get("handoffs")) if str(agent_id)]
    recorded = {str(handoff.get("internal_agent_id") or "") for handoff in _as_list(session.get("internal_handoffs")) if isinstance(handoff, dict)}
    for agent_id in expected_handoffs:
        if agent_id in recorded or agent_id not in INTERNAL_AGENTS:
            continue
        _record_internal_handoff(
            session,
            agent_id,
            f"scenario-specific proposal review for {mode}",
            {
                "scenario_mode": mode,
                "proposal_id": proposal.get("proposal_id"),
                "plan": proposal.get("plan"),
                "state_evidence": evidence,
            },
            "recommended",
            "Apply scenario-specific authority within the negotiated protocol envelope.",
            source,
        )


def _record_monitoring_handoffs(session: dict[str, Any], monitoring: dict[str, Any], source: str) -> None:
    policy_gate = _as_dict(monitoring.get("policy_gate"))
    evidence = _as_dict(monitoring.get("state_evidence"))
    if "safety_delay" in policy_gate or "safety_notice" in policy_gate or evidence.get("weather") or evidence.get("alert"):
        _record_internal_handoff(session, "safety_agent", "monitor incident or weather signal", evidence or {"event": monitoring.get("event")}, "recommended", str(monitoring.get("park_agent_offer") or "Issue safety-aware update."), source)
    if "route_change" in policy_gate or "priority_access" in policy_gate or "shared_route_plan" in policy_gate or evidence.get("ride"):
        _record_internal_handoff(session, "queue_agent", "find reroute or wait reduction", evidence or {"event": monitoring.get("event")}, "recommended", str(monitoring.get("park_agent_revision") or monitoring.get("accepted_resolution") or "Reroute guest flow."), source)
    if "food_recommendation" in policy_gate or "food_credit" in policy_gate or evidence.get("food"):
        _record_internal_handoff(session, "food_agent", "adjust food timing", evidence or {"event": monitoring.get("event")}, "recommended", str(monitoring.get("park_agent_offer") or "Move food stop."), source)
    if any(key in policy_gate for key in ("payment", "compensation_settlement", "compensation_offer", "refund_acceptance", "food_credit")):
        _record_internal_handoff(session, "commerce_agent", "check commerce boundary", {"policy_gate": policy_gate}, "requires_user_approval", "Offer may be presented; settlement or payment is gated.", source)
    if any(key in policy_gate for key in ("restock_request", "dock_slot_assignment", "substitution_request", "inventory_hold")):
        _record_internal_handoff(session, "supply_chain_agent", "coordinate supplier operation", evidence or {"policy_gate": policy_gate}, "recommended", str(monitoring.get("park_agent_revision") or "Coordinate supply-chain update."), source)
    if any(key in policy_gate for key in ("purchase_order", "vendor_payment_release", "price_change_acceptance")):
        _record_internal_handoff(session, "procurement_agent", "check procurement boundary", {"policy_gate": policy_gate}, "requires_user_approval", "Purchase order, payment, and price changes are approval gated.", source)
    if "maintenance_parts_request" in policy_gate:
        _record_internal_handoff(session, "maintenance_agent", "coordinate maintenance part logistics", evidence or {"policy_gate": policy_gate}, "recommended", str(monitoring.get("park_agent_revision") or "Coordinate maintenance part delivery."), source)


def _scenario_mode_from_payload(payload: dict[str, Any] | None) -> str:
    payload = payload or {}
    return str(payload.get("scenario_mode") or payload.get("scenarioMode") or "").strip()


def _scenario_mode_for_session(session: dict[str, Any], fallback_payload: dict[str, Any] | None = None) -> str:
    direct = _scenario_mode_from_payload(fallback_payload)
    if direct:
        return direct
    intent = _as_dict(_as_dict(session.get("intent")).get("client_agent"))
    constraints = _as_dict(intent.get("constraints"))
    mode = str(intent.get("scenario_mode") or intent.get("scenarioMode") or constraints.get("scenario_mode") or constraints.get("scenarioMode") or "").strip()
    return mode or "visit_planning"


def _is_supply_chain_session(session: dict[str, Any], payload: dict[str, Any] | None = None) -> bool:
    return _scenario_mode_for_session(session, payload) in SUPPLY_CHAIN_PROTOCOL_SCENARIOS


def _proposal_required_scopes(session: dict[str, Any], payload: dict[str, Any] | None = None) -> list[str]:
    if not _is_supply_chain_session(session, payload):
        return ["preferences", "route_plan"]
    mode = _scenario_mode_for_session(session, payload)
    if mode == "maintenance_parts_shortage":
        return ["parts_availability", "maintenance_parts_request"]
    if mode == "cold_chain_incident":
        return ["cold_chain_status", "substitution_request"]
    return ["inventory_position", "restock_request"]


def _intent_required_scopes(payload: dict[str, Any] | None = None) -> list[str]:
    mode = _scenario_mode_from_payload(payload)
    if mode in SUPPLY_CHAIN_PROTOCOL_SCENARIOS:
        if mode == "maintenance_parts_shortage":
            return ["supplier_compliance"]
        if mode == "cold_chain_incident":
            return ["cold_chain_status"]
        return ["inventory_position"]
    return ["preferences"]


def _monitor_required_scopes(session: dict[str, Any], payload: dict[str, Any] | None = None) -> list[str]:
    if not _is_supply_chain_session(session, payload):
        return ["wait_time_alert", "safety_notice"]
    mode = _scenario_mode_for_session(session, payload)
    if mode == "maintenance_parts_shortage":
        return ["maintenance_parts_request", "safety_notice"]
    if mode == "cold_chain_incident":
        return ["cold_chain_status", "safety_notice"]
    return ["delivery_eta", "restock_request"]


def _commit_required_scopes(session: dict[str, Any], payload: dict[str, Any] | None = None) -> list[str]:
    if _is_supply_chain_session(session, payload):
        return ["session_commit", *_proposal_required_scopes(session, payload)[-1:]]
    return ["route_plan", "session_commit"]


def _receipt_required_scopes(session: dict[str, Any], payload: dict[str, Any] | None = None) -> list[str]:
    if _is_supply_chain_session(session, payload):
        return _proposal_required_scopes(session, payload)[-1:]
    return ["route_plan"]


def _scenario_static_plan(mode: str, walking_priority: str, avoid_wait: int) -> dict[str, Any] | None:
    high_walking = walking_priority == "highest"
    scenario = _as_dict(_protocol_scenario(mode).get("proposal"))
    if not scenario:
        return None
    plan = _as_list(scenario["plan"])
    walking = scenario.get("high_walking") if high_walking and scenario.get("high_walking") else scenario.get("walking")
    expected_handoffs = _as_list(_protocol_scenario(mode).get("handoffs"))
    return {
        "proposal_id": f"plan_{mode}_{hashlib.sha1(':'.join(str(item) for item in plan).encode('utf-8')).hexdigest()[:6]}",
        "plan": plan,
        "expected_wait_saved": scenario["saved"],
        "estimated_walking_distance": walking,
        "confidence": scenario["confidence"],
        "rationale": scenario["rationale"],
        "tradeoffs": [f"No planned stop exceeds the delegated {avoid_wait}-minute wait threshold.", *_as_list(scenario["tradeoffs"])],
        "requires_user_approval": False,
        "scenario_mode": mode,
        "expected_internal_handoffs": expected_handoffs,
        "state_evidence": scenario["evidence"],
    }


def _scenario_monitoring(mode: str, event: str) -> dict[str, Any] | None:
    monitoring = copy.deepcopy(_as_dict(_protocol_scenario(mode).get("monitoring")))
    if not monitoring:
        return None
    state_evidence = _as_dict(monitoring.get("state_evidence"))
    state_evidence["event"] = event
    monitoring["state_evidence"] = state_evidence
    return monitoring


def _get_session(session_id: str) -> dict[str, Any]:
    session = _sessions.get(session_id)
    if not session:
        try:
            from mongo_memory import get_agent_handshake_session

            persisted = get_agent_handshake_session(session_id)
        except Exception:
            persisted = None
        if not persisted:
            raise KeyError(f"Unknown agent handshake session: {session_id}")
        session = copy.deepcopy(persisted)
        session["session_id"] = str(session.get("session_id") or session.get("sessionId") or session.get("id") or session_id)
        session.setdefault("conversation", [])
        session.setdefault("policy_decisions", [])
        session.setdefault("internal_handoffs", [])
        session.setdefault("case_evaluations", [])
        _sessions[session["session_id"]] = session
    return session


def _record_delegation_failure(session: dict[str, Any], proof: dict[str, Any]) -> None:
    decision = {
        "id": f"ahp_policy_{hashlib.sha1(f'{session.get('session_id')}:delegation:{time.time_ns()}'.encode('utf-8')).hexdigest()[:12]}",
        "session_id": session.get("session_id"),
        "action": f"delegation_{proof.get('operation') or 'session'}",
        "status": "blocked",
        "allowed": False,
        "requires_user_approval": True,
        "reason": str(proof.get("reason") or "Delegation token check failed."),
        "created_at": _now_iso(),
        "payload": {"delegation_proof": copy.deepcopy(proof)},
    }
    _record_policy_decision(session, decision)
    _record_case_evaluation(
        session,
        _case_evaluation(
            "delegation_scope_rejection",
            {
                "token_checked": proof.get("signature_status") in {"valid", "invalid"} or proof.get("status") == "rejected",
                "missing_scope_detected": bool(proof.get("missing_scope")) or proof.get("status") == "rejected",
                "delegation_rejected": proof.get("status") == "rejected",
                "policy_decision_recorded": any(item.get("id") == decision["id"] for item in session.get("policy_decisions", [])),
                "session_not_advanced": session.get("state") in {"initiated", "verified"},
            },
            {"operation": proof.get("operation"), "missing_scope": proof.get("missing_scope"), "reason": proof.get("reason")},
        ),
        persist=True,
    )


def _enforce_delegation(session: dict[str, Any], payload: dict[str, Any] | None, operation: str, required_scopes: list[str] | None = None) -> dict[str, Any]:
    stored_delegation = _as_dict(session.get("delegation"))
    token = _delegation_token_from(payload) or _as_dict(stored_delegation.get("token"))
    proof = verify_delegation_token(token)
    claims = _as_dict(proof.get("claims"))
    required = sorted({scope for scope in (required_scopes or []) if scope})
    proof.update({"operation": operation, "required_scope": required})
    session.setdefault("delegation", {})
    session["delegation"]["last_verification"] = copy.deepcopy(proof)
    if proof.get("status") != "verified":
        _record_delegation_failure(session, proof)
        raise PermissionError(str(proof.get("reason") or "Delegation token rejected."))
    if str(claims.get("agent_id") or "") != str(_as_dict(session.get("client_agent")).get("agent_id") or ""):
        proof.update({"status": "rejected", "reason": "Delegation token agent does not match the handshaken client agent."})
        session["delegation"]["last_verification"] = copy.deepcopy(proof)
        _record_delegation_failure(session, proof)
        raise PermissionError(proof["reason"])
    if str(claims.get("sub") or "") != str(_as_dict(session.get("client_agent")).get("represents") or ""):
        proof.update({"status": "rejected", "reason": "Delegation token subject does not match the represented guest."})
        session["delegation"]["last_verification"] = copy.deepcopy(proof)
        _record_delegation_failure(session, proof)
        raise PermissionError(proof["reason"])
    token_scope = set(_normalize_scope(claims.get("scope")))
    missing = sorted(set(required) - token_scope)
    if missing:
        proof.update({"status": "rejected", "scope_status": "insufficient", "missing_scope": missing, "reason": f"Delegation token is missing required scope: {', '.join(missing)}."})
        session["delegation"]["last_verification"] = copy.deepcopy(proof)
        _record_delegation_failure(session, proof)
        raise PermissionError(proof["reason"])
    proof.update({"scope_status": "accepted", "reason": "Delegation token accepted for this operation."})
    session["delegation"]["last_verification"] = copy.deepcopy(proof)
    session["delegation"]["proof"] = copy.deepcopy(proof)
    session["delegation"]["token"] = copy.deepcopy(token)
    return proof


def _verification_for(proof: str, requested_session: str) -> dict[str, Any]:
    verified = bool(str(proof or "").strip()) and str(requested_session or "").strip()
    return {
        "status": "verified" if verified else "rejected",
        "guest_role": "ticket_holder" if verified else "unknown",
        "trust_level": "standard_guest" if verified else "untrusted",
        "proof_type": "signed_token",
    }


def evaluate_policy_action(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    session = _get_session(session_id)
    delegation_proof = _enforce_delegation(session, payload, "policy_check", ["policy_check"])
    action = str(payload.get("action") or payload.get("type") or "").strip()
    if not action:
        action = "unknown_action"
    if _policy_agent_for(action) == "commerce_agent":
        commerce_result = _commerce_agent_evaluate(session, payload, delegation_proof, "park_agent_policy_check")
        return {**commerce_result, "session": _copy_session(session)}
    decision = _policy_decision(session, action, payload)
    decision["delegation_proof"] = copy.deepcopy(delegation_proof)
    _record_policy_decision(session, decision)
    return {"status": decision["status"], "decision": copy.deepcopy(decision), "session": _copy_session(session)}


def commerce_agent_evaluate(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    session = _get_session(session_id)
    delegation_proof = _enforce_delegation(session, payload, "commerce_agent_evaluate", ["policy_check"])
    commerce_result = _commerce_agent_evaluate(session, payload, delegation_proof, "commerce_agent_endpoint")
    return {**commerce_result, "session": _copy_session(session)}


def queue_agent_reroute(session_id: str, payload: dict[str, Any], park_state: dict[str, Any] | None = None) -> dict[str, Any]:
    session = _get_session(session_id)
    delegation_proof = _enforce_delegation(session, payload, "queue_agent_reroute", ["route_plan", "wait_time_alert"])
    queue_result = _queue_agent_reroute(session, payload, delegation_proof, park_state, "queue_agent_endpoint")
    return {**queue_result, "session": _copy_session(session)}


def register_agent_onboarding(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    _load_trust_registry()
    payload = payload or {}
    agent_id = _agent_onboarding_id(payload)
    requested_scopes = _normalize_scope(payload.get("requested_scopes") or payload.get("requestedScopes") or payload.get("scope")) or DEFAULT_DELEGATION_SCOPES
    cannot_do = _normalize_scope(payload.get("cannot_do") or payload.get("cannotDo")) or sorted(CLIENT_BLOCKED_ACTIONS)
    partner_id = str(payload.get("partner_id") or payload.get("partnerId") or "demo_external_partner")
    existing_partner = _as_dict(get_partner(partner_id) or _partner_registry.get(partner_id))
    partner_allowed_scopes = _normalize_scope(payload.get("partner_allowed_scopes") or payload.get("partnerAllowedScopes") or existing_partner.get("allowed_scopes")) or DEFAULT_DELEGATION_SCOPES
    disallowed_scopes = sorted(set(requested_scopes) - set(partner_allowed_scopes))
    use_case = _normal_use_case(payload.get("use_case") or payload.get("useCase") or "guest_route_planning")
    record = {
        "agent_id": agent_id,
        "display_name": str(payload.get("display_name") or payload.get("displayName") or agent_id),
        "partner": {
            "partner_id": partner_id,
            "partner_name": str(payload.get("partner_name") or payload.get("partnerName") or existing_partner.get("partner_name") or "Demo External Partner"),
            "contact": str(payload.get("partner_contact") or payload.get("partnerContact") or existing_partner.get("contact") or ""),
            "trust_tier": str(payload.get("trust_tier") or payload.get("trustTier") or existing_partner.get("trust_tier") or "sandbox"),
            "status": str(payload.get("partner_status") or payload.get("partnerStatus") or existing_partner.get("status") or "active"),
            "allowed_scopes": partner_allowed_scopes,
        },
        "status": "registered",
        "approval": "pending_certification",
        "scope_request_status": "rejected" if disallowed_scopes else "accepted",
        "disallowed_scopes": disallowed_scopes,
        "requested_scopes": requested_scopes,
        "allowed_scopes": [],
        "cannot_do": cannot_do,
        "represents": str(payload.get("represents") or "guest_user_123"),
        "use_case": use_case,
        "registered_at": _now_iso(),
        "updated_at": _now_iso(),
        "certification": None,
    }
    _agent_onboardings[agent_id] = copy.deepcopy(record)
    stored_partner = upsert_partner(record["partner"], actor="agent_onboarding_register")
    _partner_registry[partner_id] = copy.deepcopy(stored_partner)
    return {"status": "registered", "agent": copy.deepcopy(record), "next": f"/api/park/agent-onboarding/{agent_id}/certify"}


def get_agent_onboarding(agent_id: str) -> dict[str, Any]:
    record = _agent_onboardings.get(agent_id)
    if not record:
        raise KeyError(f"Unknown onboarded agent: {agent_id}")
    return {"status": "found", "agent": copy.deepcopy(record)}


def _normal_use_case(value: Any) -> str:
    normalized = str(value or "guest_route_planning").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"supplier", "supplier_agent", "supply_chain", "supply_chain_coordination", "supplier_coordination", "vendor_coordination"}:
        return "supply_chain_coordination"
    return "guest_route_planning"


def _certification_required_cases_for_use_case(use_case: str) -> list[str]:
    return SUPPLY_CHAIN_CERTIFICATION_REQUIRED_CASES if _normal_use_case(use_case) == "supply_chain_coordination" else CERTIFICATION_REQUIRED_CASES


def _approval_for_use_case(use_case: str) -> str:
    return SUPPLY_CHAIN_APPROVAL if _normal_use_case(use_case) == "supply_chain_coordination" else GUEST_ROUTE_APPROVAL


def _blocked_approval_for_use_case(use_case: str) -> str:
    return "blocked_until_supplier_scope_fixed" if _normal_use_case(use_case) == "supply_chain_coordination" else "blocked_until_scope_fixed"


def _certification_summary(session: dict[str, Any], required_cases: list[str] | None = None) -> dict[str, Any]:
    required_case_ids = required_cases or CERTIFICATION_REQUIRED_CASES
    evaluations = _as_list(session.get("case_evaluations"))
    latest_by_case: dict[str, dict[str, Any]] = {}
    for evaluation in evaluations:
        if isinstance(evaluation, dict):
            latest_by_case[str(evaluation.get("case") or "")] = evaluation
    required = {
        case: {
            "status": _as_dict(latest_by_case.get(case)).get("status") or "missing",
            "score": _as_dict(latest_by_case.get(case)).get("score") or 0,
            "criteria": _as_dict(latest_by_case.get(case)).get("criteria"),
        }
        for case in required_case_ids
    }
    passed_cases = [case for case, evaluation in required.items() if evaluation["status"] == "passed"]
    return {
        "required_cases": required,
        "passed_cases": passed_cases,
        "score": round(len(passed_cases) / max(1, len(required_case_ids)), 2),
        "status": "passed" if len(passed_cases) == len(required_case_ids) else "failed",
    }


def _supplier_certification_scenario(payload: dict[str, Any], record: dict[str, Any]) -> str:
    scenario = str(payload.get("scenario_mode") or payload.get("scenarioMode") or record.get("scenario_mode") or record.get("scenarioMode") or "supply_replenishment")
    return scenario if scenario in SUPPLY_CHAIN_PROTOCOL_SCENARIOS else "supply_replenishment"


def _run_supply_chain_certification_session(
    agent_id: str,
    represented_supplier: str,
    token: dict[str, Any],
    cannot_do: list[str],
    certification_id: str,
    scenario_mode: str,
) -> dict[str, Any]:
    scenario = _protocol_scenario(scenario_mode)
    run = _as_dict(scenario.get("run"))
    identity = identity_handshake(
        {
            "agent_id": agent_id,
            "represents": represented_supplier,
            "proof": "signed_supplier_token",
            "requested_session": certification_id,
            "delegation_token": token,
        }
    )
    session_id = identity["session"]["session_id"]
    capability_handshake(
        session_id,
        {
            "can_share": ["inventory_position", "delivery_eta", "supplier_compliance", "cold_chain_status", "parts_availability"],
            "can_receive": ["demand_forecast", "restock_request", "dock_slot", "substitution_request", "purchase_order_notice", "maintenance_parts_request", "safety_notice"],
            "cannot_do": cannot_do,
            "delegation_token": token,
        },
    )
    intent_handshake(
        session_id,
        {
            "goal": run.get("goal") or "coordinate_supplier_counterparty",
            "time_window": "3_hours",
            "constraints": run.get("constraints") or {"scenario_mode": scenario_mode},
            "scenario_mode": scenario_mode,
            "delegation_token": token,
        },
    )
    proposed = propose_plan(session_id, {"planner": run.get("planner") or scenario_mode, "scenario_mode": scenario_mode, "delegation_token": token})
    revised = counter_proposal(
        session_id,
        {
            "counter_request": run.get("counter_request") or "supplier certification counterproposal",
            "priority_change": run.get("priority_change") or {},
            "scenario_mode": scenario_mode,
            "delegation_token": token,
        },
    )
    commit_plan(session_id, {"accepted": True, "notify_supplier": True, "scenario_mode": scenario_mode, "delegation_token": token})
    monitored = monitor_session(session_id, {"event": run.get("monitor_event") or "supplier_certification_monitor", "scenario_mode": scenario_mode, "delegation_token": token})
    procurement = commerce_agent_evaluate(
        session_id,
        {
            "action": run.get("commerce_action") or "purchase_order",
            "amount": 1,
            "reason": run.get("commerce_reason") or f"{scenario_mode} supplier certification procurement gate.",
            "scenario_mode": scenario_mode,
            "delegation_token": token,
        },
    )
    receipt_payload = session_protocol_receipt(session_id, {"scenario_mode": scenario_mode, "delegation_token": token})
    verification = verify_protocol_artifact({"artifact": receipt_payload.get("receipt"), "expected_artifact_type": "agent_handshake_session_receipt"})
    session = _get_session(session_id)
    observed_handoffs = {str(handoff.get("internal_agent_id") or "") for handoff in _as_list(session.get("internal_handoffs")) if isinstance(handoff, dict)}
    proposal = _as_dict(proposed.get("proposal"))
    revised_proposal = _as_dict(revised.get("proposal"))
    monitoring = _as_dict(monitored.get("monitoring"))
    procurement_decision = _as_dict(procurement.get("decision"))
    _record_case_evaluation(
        session,
        _case_evaluation(
            "supply_chain_negotiation",
            {
                "proposal_mode_matches": proposal.get("scenario_mode") == scenario_mode,
                "counter_mode_matches": revised_proposal.get("scenario_mode") == scenario_mode,
                "proposal_has_plan": bool(_as_list(proposal.get("plan"))),
                "monitor_recorded": bool(monitoring.get("event")),
                "supply_chain_agent_called": "supply_chain_agent" in observed_handoffs,
            },
            {"scenario_mode": scenario_mode, "proposal_id": proposal.get("proposal_id"), "observed_handoffs": sorted(observed_handoffs)},
        ),
    )
    _record_case_evaluation(
        session,
        _case_evaluation(
            "procurement_gate",
            {
                "procurement_action_checked": procurement_decision.get("action") in {"purchase_order", "vendor_payment_release", "price_change_acceptance"},
                "procurement_blocked_or_gated": procurement_decision.get("allowed") is False,
                "approval_required": procurement_decision.get("requires_user_approval") is True,
                "procurement_agent_called": "procurement_agent" in observed_handoffs,
                "audit_recorded": any(decision.get("id") == procurement_decision.get("id") for decision in _as_list(session.get("policy_decisions")) if isinstance(decision, dict)),
            },
            {"action": procurement_decision.get("action"), "status": procurement_decision.get("status")},
        ),
    )
    _record_case_evaluation(
        session,
        _case_evaluation(
            "artifact_verification",
            {
                "receipt_issued": _as_dict(receipt_payload.get("receipt")).get("signature", {}).get("artifact_type") == "agent_handshake_session_receipt",
                "receipt_verified": verification.get("status") == "verified",
                "digest_valid": verification.get("digest_status") == "valid",
                "signature_valid": verification.get("signature_status") == "valid",
            },
            {"receipt_id": _as_dict(receipt_payload.get("receipt")).get("receipt_id"), "verification": verification},
        ),
        persist=True,
    )
    return get_session(session_id)["session"]


def certify_agent_onboarding(agent_id: str, payload: dict[str, Any] | None = None, park_state: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    record = _agent_onboardings.get(agent_id)
    if not record:
        raise KeyError(f"Unknown onboarded agent: {agent_id}")

    requested_scopes = _normalize_scope(payload.get("requested_scopes") or payload.get("requestedScopes") or payload.get("scope")) or _normalize_scope(record.get("requested_scopes"))
    cannot_do = _normalize_scope(payload.get("cannot_do") or payload.get("cannotDo")) or _normalize_scope(record.get("cannot_do")) or sorted(CLIENT_BLOCKED_ACTIONS)
    represented_guest = str(payload.get("represents") or record.get("represents") or "guest_user_123")
    use_case = _normal_use_case(payload.get("use_case") or payload.get("useCase") or record.get("use_case") or record.get("useCase"))
    required_cases = _certification_required_cases_for_use_case(use_case)
    partner = _as_dict(record.get("partner"))
    partner_allowed_scopes = _normalize_scope(partner.get("allowed_scopes")) or DEFAULT_DELEGATION_SCOPES
    partner_disallowed_scopes = sorted(set(requested_scopes) - set(partner_allowed_scopes))
    token = issue_delegation_token(
        {
            "subject": represented_guest,
            "agent_id": agent_id,
            "scope": requested_scopes,
            "cannot_do": cannot_do,
            "ttl_seconds": int(payload.get("ttl_seconds") or payload.get("ttlSeconds") or 600),
        }
    )["token"]
    certification_id = f"cert_{hashlib.sha1(f'{agent_id}:{time.time_ns()}'.encode('utf-8')).hexdigest()[:12]}"
    readiness_issues: list[str] = []
    session: dict[str, Any] | None = None

    try:
        if partner_disallowed_scopes:
            raise PermissionError(f"Partner allowlist does not permit requested scope: {', '.join(partner_disallowed_scopes)}.")
        if use_case == "supply_chain_coordination":
            session = _run_supply_chain_certification_session(
                agent_id,
                represented_guest,
                token,
                cannot_do,
                certification_id,
                _supplier_certification_scenario(payload, record),
            )
        else:
            identity = identity_handshake(
                {
                    "agent_id": agent_id,
                    "represents": represented_guest,
                    "proof": "signed_token",
                    "requested_session": certification_id,
                    "delegation_token": token,
                }
            )
            session_id = identity["session"]["session_id"]
            capability_handshake(
                session_id,
                {
                    "can_share": [scope for scope in sorted(CLIENT_ALLOWED_TO_SHARE) if scope in set(requested_scopes)],
                    "can_receive": [scope for scope in sorted(CLIENT_ALLOWED_TO_RECEIVE) if scope in set(requested_scopes)],
                    "cannot_do": cannot_do,
                    "delegation_token": token,
                },
            )
            intent_handshake(
                session_id,
                {
                    "goal": "maximize_family_satisfaction",
                    "time_window": "3_hours",
                    "constraints": {"children": 2, "avoid_wait_over_minutes": 35, "avoid_thrill_rides": True, "food_allergy": "peanut"},
                    "delegation_token": token,
                },
            )
            propose_plan(session_id, {"planner": "agent_onboarding_certification", "delegation_token": token}, park_state=park_state)
            queue_agent_reroute(session_id, {"walking_priority": "highest", "reason": "Certification reroute proof.", "delegation_token": token}, park_state=park_state)
            commerce_agent_evaluate(session_id, {"action": "payment", "amount": 1, "reason": "Certification payment boundary proof.", "delegation_token": token})
            session = get_session(session_id)["session"]
    except PermissionError as error:
        readiness_issues.append(str(error))
        if session is None:
            for candidate in reversed(list(_sessions.values())):
                if _as_dict(candidate.get("client_agent")).get("agent_id") == agent_id and _as_dict(candidate.get("client_agent")).get("requested_session") == certification_id:
                    session = _copy_session(candidate)
                    break
    except Exception as error:
        readiness_issues.append(str(error)[:240])

    if session is None:
        summary = {"required_cases": {case: {"status": "missing", "score": 0} for case in required_cases}, "passed_cases": [], "score": 0, "status": "failed"}
    else:
        summary = _certification_summary(session, required_cases)

    approved = summary["status"] == "passed"
    certification = {
        "certification_id": certification_id,
        "status": "approved" if approved else "blocked",
        "approval": _approval_for_use_case(use_case) if approved else _blocked_approval_for_use_case(use_case),
        "use_case": use_case,
        "score": summary["score"],
        "required_case_ids": required_cases,
        "required_cases": summary["required_cases"],
        "passed_cases": summary["passed_cases"],
        "allowed_scopes": requested_scopes if approved else [],
        "partner_allowed_scopes": partner_allowed_scopes,
        "partner_disallowed_scopes": partner_disallowed_scopes,
        "readiness_issues": readiness_issues,
        "session_id": session.get("session_id") if session else None,
        "certified_at": _now_iso(),
    }
    certification["credential"] = _issue_certification_credential(agent_id, certification, requested_scopes) if approved else None
    record.update(
        {
            "status": certification["status"],
            "approval": certification["approval"],
            "requested_scopes": requested_scopes,
            "allowed_scopes": certification["allowed_scopes"],
            "cannot_do": cannot_do,
            "use_case": use_case,
            "certification": certification,
            "updated_at": _now_iso(),
        }
    )
    _agent_onboardings[agent_id] = copy.deepcopy(record)
    return {"status": certification["status"], "agent": copy.deepcopy(record), "certification": copy.deepcopy(certification), "session": copy.deepcopy(session) if session else None}


def _policy_decision(session: dict[str, Any], action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_action = str(action or "").strip()
    rule = ACTION_POLICY_RULES.get(normalized_action) or ACTION_POLICY_RULES.get(normalized_action.replace("-", "_"))
    if rule is None:
        rule = {
            "status": "requires_user_approval",
            "allowed": False,
            "requires_user_approval": True,
            "reason": "Unknown agent action is not in the delegated handshake contract.",
        }
    decision = {
        "id": f"ahp_policy_{hashlib.sha1(f'{session.get('session_id')}:{normalized_action}:{time.time_ns()}'.encode('utf-8')).hexdigest()[:12]}",
        "session_id": session.get("session_id"),
        "action": normalized_action,
        "status": rule["status"],
        "allowed": bool(rule["allowed"]),
        "requires_user_approval": bool(rule["requires_user_approval"]),
        "reason": rule["reason"],
        "created_at": _now_iso(),
        "payload": copy.deepcopy(payload or {}),
    }
    return decision


def _record_policy_decision(session: dict[str, Any], decision: dict[str, Any]) -> None:
    session.setdefault("policy_decisions", [])
    session["policy_decisions"].append(copy.deepcopy(decision))
    session["policy_decisions"] = session["policy_decisions"][-80:]
    agent_id = _policy_agent_for(str(decision.get("action") or ""))
    _record_internal_handoff(
        session,
        agent_id,
        f"policy check for {decision.get('action')}",
        {"policy_status": decision.get("status"), "requires_user_approval": decision.get("requires_user_approval"), "payload": decision.get("payload")},
        str(decision.get("status") or "reviewed"),
        str(decision.get("reason") or "Policy decision recorded."),
        "policy",
    )
    session["conversation"].append(_event("park_agent", "policy_enforcement", decision))
    _persist_policy_event(decision)
    session["updated_at"] = _now_iso()
    _persist_session(session)


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _deep_merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _protocol_scenario_catalog_raw() -> dict[str, dict[str, Any]]:
    catalog = copy.deepcopy(BUILT_IN_PROTOCOL_SCENARIOS)
    config_path = os.getenv("PARKPULSE_AHP_SCENARIO_CATALOG", "").strip()
    if not config_path:
        return catalog
    try:
        configured = json.loads(Path(config_path).read_text(encoding="utf-8"))
        configured_scenarios = configured.get("scenarios") if isinstance(configured, dict) else configured
        if isinstance(configured_scenarios, list):
            configured_scenarios = {str(item.get("id") or ""): item for item in configured_scenarios if isinstance(item, dict) and item.get("id")}
        if isinstance(configured_scenarios, dict):
            for scenario_id, scenario in configured_scenarios.items():
                if not isinstance(scenario, dict):
                    continue
                scenario_id = str(scenario.get("id") or scenario_id)
                base = catalog.get(scenario_id, {"id": scenario_id})
                catalog[scenario_id] = _deep_merge_dict(base, scenario)
    except Exception:
        return catalog
    return catalog


def _protocol_scenario(mode: str) -> dict[str, Any]:
    return _as_dict(_protocol_scenario_catalog_raw().get(mode))


def _protocol_artifact_signature(artifact_type: str, artifact: dict[str, Any]) -> dict[str, Any]:
    signing = _certification_signing_material()
    artifact_bytes = _canonical_json(artifact)
    claims = {
        "artifact_type": artifact_type,
        "protocol_version": "parkpulse-ahp-0.1",
        "issuer": "parkpulse_agent_onboarding_authority",
        "iss": "parkpulse_agent_onboarding_authority",
        "iat": int(time.time()),
        "alg": signing["alg"],
        "kid": signing["kid"],
        "sha256": hashlib.sha256(artifact_bytes).hexdigest(),
    }
    return {**claims, "sig": _sign_certification_claims(claims)}


def _with_protocol_signature(artifact_type: str, artifact: dict[str, Any]) -> dict[str, Any]:
    unsigned = copy.deepcopy(artifact)
    unsigned.pop("signature", None)
    return {**unsigned, "signature": _protocol_artifact_signature(artifact_type, unsigned)}


def verify_protocol_artifact(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    artifact = payload.get("artifact") if isinstance(payload.get("artifact"), dict) else payload
    if not isinstance(artifact, dict) or not artifact:
        return {
            "status": "rejected",
            "mode": "agent_handshake_artifact_verification",
            "reason": "A signed protocol artifact is required.",
            "supported_artifact_types": [
                "agent_contract",
                "agent_consent_grant",
                "agent_handshake_policy_challenges",
                "agent_handshake_scenario_catalog",
                "agent_handshake_session_receipt",
            ],
        }
    signature = artifact.get("signature") if isinstance(artifact.get("signature"), dict) else {}
    expected_type = str(payload.get("expected_artifact_type") or payload.get("artifact_type") or payload.get("expectedArtifactType") or "").strip()
    unsigned = copy.deepcopy(artifact)
    unsigned.pop("signature", None)
    claims = {key: copy.deepcopy(value) for key, value in signature.items() if key != "sig"}
    provided_sig = str(signature.get("sig") or "")
    computed_sha = hashlib.sha256(_canonical_json(unsigned)).hexdigest()
    signature_type = str(claims.get("artifact_type") or "")
    digest_valid = bool(claims.get("sha256")) and str(claims.get("sha256")) == computed_sha
    signature_valid = bool(provided_sig) and _verify_certification_claims(claims, provided_sig)
    issuer_valid = str(claims.get("issuer") or claims.get("iss") or "") == "parkpulse_agent_onboarding_authority"
    protocol_valid = str(claims.get("protocol_version") or "") == "parkpulse-ahp-0.1"
    type_valid = bool(signature_type) and (not expected_type or signature_type == expected_type)
    verified = digest_valid and signature_valid and issuer_valid and protocol_valid and type_valid
    reason = "Artifact signature, digest, issuer, protocol version, and type are valid." if verified else "Artifact verification failed."
    failures = []
    if not signature:
        failures.append("missing_signature")
    if not digest_valid:
        failures.append("sha256_mismatch")
    if not signature_valid:
        failures.append("invalid_signature")
    if not issuer_valid:
        failures.append("untrusted_issuer")
    if not protocol_valid:
        failures.append("unsupported_protocol_version")
    if not type_valid:
        failures.append("artifact_type_mismatch" if expected_type else "missing_artifact_type")
    return {
        "status": "verified" if verified else "rejected",
        "mode": "agent_handshake_artifact_verification",
        "reason": reason,
        "artifact_type": signature_type or None,
        "expected_artifact_type": expected_type or None,
        "protocol_version": claims.get("protocol_version"),
        "issuer": claims.get("issuer") or claims.get("iss"),
        "kid": claims.get("kid"),
        "alg": claims.get("alg"),
        "issued_at": claims.get("iat"),
        "digest_status": "valid" if digest_valid else "invalid",
        "signature_status": "valid" if signature_valid else "invalid",
        "issuer_status": "trusted" if issuer_valid else "untrusted",
        "type_status": "valid" if type_valid else "invalid",
        "computed_sha256": computed_sha,
        "claimed_sha256": claims.get("sha256"),
        "failures": failures,
    }


def agent_handshake_scenario_catalog() -> dict[str, Any]:
    config_path = os.getenv("PARKPULSE_AHP_SCENARIO_CATALOG", "").strip()
    catalog = _protocol_scenario_catalog_raw()
    artifact = {
        "status": "ready",
        "mode": "agent_handshake_scenario_catalog",
        "protocol_version": "parkpulse-ahp-0.1",
        "config_source": config_path or "built_in",
        "configurable": True,
        "override_env": "PARKPULSE_AHP_SCENARIO_CATALOG",
        "scenario_count": len(catalog),
        "scenarios": [copy.deepcopy(catalog[key]) for key in sorted(catalog.keys())],
    }
    return _with_protocol_signature("agent_handshake_scenario_catalog", artifact)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _family_start_zone(park_state: dict[str, Any]) -> str:
    for segment in _as_list(park_state.get("guestSegments")):
        if "famil" in str(segment.get("id") or segment.get("label") or "").lower():
            return str(segment.get("currentZoneId") or "entrancePlaza")
    return "entrancePlaza"


def _zone_lookup(park_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(zone.get("id")): zone for zone in _as_list(_as_dict(park_state.get("guestFlow")).get("zones")) if zone.get("id")}


def _path_minutes(park_state: dict[str, Any], from_zone: str, to_zone: str) -> float:
    if not from_zone or not to_zone or from_zone == to_zone:
        return 0.0
    graph: dict[str, list[tuple[str, float]]] = {}
    for path in _as_list(_as_dict(park_state.get("guestFlow")).get("paths")):
        start = str(path.get("from") or "")
        end = str(path.get("to") or "")
        if not start or not end:
            continue
        penalty = 2.5 if str(path.get("status") or "").lower() in {"busy", "congested"} else 0.0
        minutes = max(1.0, _num(path.get("walkMinutes"), 8.0) + penalty)
        graph.setdefault(start, []).append((end, minutes))
        graph.setdefault(end, []).append((start, minutes))
    queue: list[tuple[float, str]] = [(0.0, from_zone)]
    best: dict[str, float] = {from_zone: 0.0}
    while queue:
        queue.sort(key=lambda item: item[0])
        minutes, zone = queue.pop(0)
        if zone == to_zone:
            return minutes
        if minutes > best.get(zone, 9999):
            continue
        for next_zone, extra in graph.get(zone, []):
            candidate = minutes + extra
            if candidate < best.get(next_zone, 9999):
                best[next_zone] = candidate
                queue.append((candidate, next_zone))
    return 12.0


def _kid_friendly_score(ride: dict[str, Any]) -> float:
    name = str(ride.get("name") or ride.get("id") or "").lower()
    thrill_terms = {"coaster", "drop", "launch", "thrill"}
    calm_terms = {"arcade", "theater", "river", "carousel", "family", "show"}
    score = 0.0
    if any(term in name for term in calm_terms):
        score -= 20
    if any(term in name for term in thrill_terms):
        score += 35
    return score


def _rank_live_rides(session: dict[str, Any], park_state: dict[str, Any], walking_priority: str) -> list[dict[str, Any]]:
    intent = _as_dict(_as_dict(session.get("intent")).get("client_agent"))
    constraints = _as_dict(intent.get("constraints"))
    avoid_wait = _num(constraints.get("avoid_wait_over_minutes") or constraints.get("avoidWaitOverMinutes"), 35)
    avoid_thrill = bool(constraints.get("avoid_thrill_rides") or constraints.get("avoidThrillRides"))
    start_zone = _family_start_zone(park_state)
    ranked: list[dict[str, Any]] = []
    for ride in _as_list(_as_dict(park_state.get("guestFlow")).get("rides")):
        status = str(ride.get("status") or "unknown").lower()
        wait = _num(ride.get("waitMins"), 999)
        downtime = _num(ride.get("downtimeRisk"), 100)
        if status in {"down", "closed"} or downtime >= 95:
            continue
        zone = str(ride.get("zone") or "")
        walk = _path_minutes(park_state, start_zone, zone)
        score = wait + downtime * 0.25 + _kid_friendly_score(ride)
        if avoid_thrill:
            score += _kid_friendly_score(ride)
        if wait > avoid_wait:
            score += (wait - avoid_wait) * 2
        score += walk * (2.4 if walking_priority == "highest" else 1.0)
        zone_info = _zone_lookup(park_state).get(zone, {})
        score += max(0.0, _num(zone_info.get("density"), 0) - 85) * 0.45
        ranked.append({**ride, "walkMinutesFromFamily": round(walk, 1), "plannerScore": round(score, 2)})
    return sorted(ranked, key=lambda ride: _num(ride.get("plannerScore"), 999))


def _rank_live_food(park_state: dict[str, Any], start_zone: str, walking_priority: str) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for food in _as_list(_as_dict(park_state.get("foodInventory")).get("locations")):
        zone = str(food.get("id") or "")
        walk = _path_minutes(park_state, start_zone, zone)
        eta = _num(food.get("pickupEtaMinutes"), 999)
        backlog = _num(food.get("mobileOrderBacklog"), 999)
        low_inventory = len(_as_list(food.get("lowInventoryItems")))
        score = eta + backlog * 0.08 + low_inventory * 8 + walk * (2.0 if walking_priority == "highest" else 0.8)
        ranked.append({**food, "walkMinutesFromFamily": round(walk, 1), "plannerScore": round(score, 2)})
    return sorted(ranked, key=lambda food: _num(food.get("plannerScore"), 999))


def _live_plan_for(session: dict[str, Any], park_state: dict[str, Any], walking_priority: str = "medium") -> dict[str, Any]:
    ranked_rides = _rank_live_rides(session, park_state, walking_priority)
    start_zone = _family_start_zone(park_state)
    ranked_food = _rank_live_food(park_state, start_zone, walking_priority)
    selected_rides = ranked_rides[:2] or [{"name": "Indoor Arcade", "zone": "arcadeZone", "waitMins": 12, "walkMinutesFromFamily": 8}]
    selected_food = ranked_food[0] if ranked_food else {"name": "Pizza Garden allergy-safe counter", "pickupEtaMinutes": 15, "availableItems": ["pizza_combo"]}
    plan = [str(ride.get("name") or ride.get("id")) for ride in selected_rides]
    plan.append(str(selected_food.get("name") or selected_food.get("id") or "Allergy-safe food stop"))
    next_event = None
    for event in _as_list(_as_dict(_as_dict(park_state.get("operatingClock")).get("eventSchedule")).get("showtimes")):
        if _num(event.get("minutesUntilStart"), 9999) <= 180:
            next_event = event
            break
    plan.append(str(next_event.get("name")) if isinstance(next_event, dict) else "Flexible low-crowd reset window")
    total_walk = sum(_num(ride.get("walkMinutesFromFamily"), 0) for ride in selected_rides[:1]) + _num(selected_food.get("walkMinutesFromFamily"), 0)
    avg_wait = sum(_num(ride.get("waitMins"), 0) for ride in selected_rides) / max(1, len(selected_rides))
    baseline_wait = max([_num(ride.get("waitMins"), 0) for ride in _as_list(_as_dict(park_state.get("guestFlow")).get("rides"))] or [avg_wait])
    wait_saved = max(0, int(round(baseline_wait - avg_wait)))
    alerts = _as_list(park_state.get("alerts"))
    state_evidence = {
        "source": "live_park_state",
        "sim_time": park_state.get("simTime"),
        "family_start_zone": start_zone,
        "weather": park_state.get("weather"),
        "active_alerts": alerts[:3],
        "selected_rides": [
            {
                "id": ride.get("id"),
                "name": ride.get("name"),
                "status": ride.get("status"),
                "waitMins": ride.get("waitMins"),
                "zone": ride.get("zone"),
                "walkMinutesFromFamily": ride.get("walkMinutesFromFamily"),
                "plannerScore": ride.get("plannerScore"),
            }
            for ride in selected_rides
        ],
        "selected_food": {
            "id": selected_food.get("id"),
            "name": selected_food.get("name"),
            "pickupEtaMinutes": selected_food.get("pickupEtaMinutes"),
            "mobileOrderBacklog": selected_food.get("mobileOrderBacklog"),
            "availableItems": selected_food.get("availableItems"),
            "walkMinutesFromFamily": selected_food.get("walkMinutesFromFamily"),
        },
        "rejected_rides": [
            {"id": ride.get("id"), "name": ride.get("name"), "status": ride.get("status"), "waitMins": ride.get("waitMins"), "reason": "higher wait, downtime, thrill intensity, or walking cost"}
            for ride in ranked_rides[2:5]
        ],
    }
    confidence = 0.74
    if ranked_rides and ranked_food:
        confidence += 0.08
    if alerts:
        confidence -= 0.04
    if walking_priority == "highest":
        confidence -= 0.02
    return {
        "proposal_id": f"live_plan_{hashlib.sha1(_stable_plan_key(plan, park_state).encode('utf-8')).hexdigest()[:6]}",
        "plan": plan,
        "expected_wait_saved": f"{wait_saved} minutes",
        "estimated_walking_distance": f"{max(0.2, total_walk * 0.08):.1f} miles",
        "confidence": round(max(0.55, min(0.9, confidence)), 2),
        "rationale": "Live-state proposal based on current ride status, wait times, food pickup pressure, walking paths, weather, and active alerts.",
        "tradeoffs": [
            "Down or high-risk attractions are excluded from the plan.",
            "Food timing uses live pickup ETA and low-inventory signals.",
            "Walking priority increases the cost of cross-zone moves.",
        ],
        "requires_user_approval": False,
        "state_evidence": state_evidence,
    }


def _stable_plan_key(plan: list[str], park_state: dict[str, Any]) -> str:
    clock = _as_dict(park_state.get("simTime"))
    return ":".join([*plan, str(clock.get("hour")), str(clock.get("minute"))])


def _live_monitoring_event(park_state: dict[str, Any]) -> dict[str, Any] | None:
    alerts = _as_list(park_state.get("alerts"))
    rides = _as_list(_as_dict(park_state.get("guestFlow")).get("rides"))
    foods = _as_list(_as_dict(park_state.get("foodInventory")).get("locations"))
    weather = _as_dict(park_state.get("weather"))
    down_ride = next((ride for ride in rides if str(ride.get("status") or "").lower() in {"down", "closed"}), None)
    high_wait = next((ride for ride in sorted(rides, key=lambda item: _num(item.get("waitMins"), 0), reverse=True) if _num(ride.get("waitMins"), 0) >= 60), None)
    food_backlog = next((food for food in sorted(foods, key=lambda item: _num(item.get("pickupEtaMinutes"), 0), reverse=True) if _num(food.get("pickupEtaMinutes"), 0) >= 18), None)
    storm_risk = _num(weather.get("stormRisk"), 0)
    if down_ride:
        return {
            "event": f"{down_ride.get('name', 'A ride')} is unavailable.",
            "park_agent_offer": f"Reroute away from {down_ride.get('name')} and avoid overloading the next highest-wait attraction.",
            "client_agent_counter": "My user values time and low walking. Find a nearby lower-wait alternative.",
            "park_agent_revision": "Use the current live proposal route and continue monitoring wait spikes.",
            "accepted_resolution": "Accepted with user notification.",
            "policy_gate": {"safety_delay": "cannot_override", "route_change": "agent_allowed", "compensation_settlement": "user_approval_required"},
            "state_evidence": {"source": "live_park_state", "alert": alerts[0] if alerts else None, "ride": down_ride},
        }
    if high_wait:
        return {
            "event": f"{high_wait.get('name', 'An attraction')} wait is {int(_num(high_wait.get('waitMins'), 0))} minutes.",
            "park_agent_offer": "Suppress this attraction from the route and shift the family to lower-wait indoor options.",
            "accepted_resolution": "Accepted. Notify user with a lower-wait route update.",
            "policy_gate": {"wait_alert": "agent_allowed", "route_change": "agent_allowed"},
            "state_evidence": {"source": "live_park_state", "ride": high_wait},
        }
    if food_backlog:
        return {
            "event": f"{food_backlog.get('name', 'A food location')} pickup ETA is {int(_num(food_backlog.get('pickupEtaMinutes'), 0))} minutes.",
            "park_agent_offer": "Move the food stop to the lowest-ETA allergy-compatible location.",
            "accepted_resolution": "Accepted. Update route timing without purchase.",
            "policy_gate": {"food_recommendation": "agent_allowed", "payment": "blocked"},
            "state_evidence": {"source": "live_park_state", "food": food_backlog},
        }
    if storm_risk >= 55:
        return {
            "event": f"Storm risk is {int(storm_risk)}%.",
            "park_agent_offer": "Shift route toward covered and indoor zones.",
            "accepted_resolution": "Accepted. Notify user with covered-route update.",
            "policy_gate": {"safety_notice": "agent_allowed", "route_change": "agent_allowed"},
            "state_evidence": {"source": "live_park_state", "weather": weather},
        }
    return None


def agent_contract() -> dict[str, Any]:
    artifact = {
        "status": "ready",
        "mode": "agent_native_handshake_contract",
        "protocol_version": "parkpulse-ahp-0.1",
        "counterparty": {
            "agent_id": "parkpulse_park_agent",
            "represents": "park_operations",
            "accountability": "park-side operating layer for safety, commerce, guest experience, and operations agents",
        },
        "routes": [
            "POST /api/park/delegation-token",
            "GET /api/park/agent-onboarding/issuer",
            "POST /api/park/agent-onboarding/register",
            "POST /api/park/agent-onboarding/verify-credential",
            "POST /api/park/agent-onboarding/revoke-credential",
            "POST /api/park/agent-onboarding/{agent_id}/certify",
            "GET /api/park/agent-onboarding/{agent_id}",
            "GET /api/park/agent-trust/status",
            "GET /api/park/agent-trust/partners",
            "POST /api/park/agent-trust/partners",
            "GET /api/park/agent-trust/keys",
            "POST /api/park/agent-trust/keys/rotate",
            "GET /api/park/agent-trust/revocations",
            "GET /api/park/agent-trust/audit",
            "GET /api/park/agent-handshake/scenarios",
            "GET /api/park/agent-handshake/docs",
            "POST /api/park/agent-handshake/memory-context",
            "POST /api/park/agent-handshake/consent-grant",
            "POST /api/park/agent-handshake/live-state",
            "POST /api/park/agent-handshake/scenario-eval",
            "POST /api/park/agent-handshake/policy-challenges",
            "POST /api/park/agent-handshake/external-client-demo",
            "POST /api/park/agent-handshake/verify-artifact",
            "GET /api/park/agent-handshake/supply-chain/demo",
            "POST /api/park/agent-handshake/supply-chain/demo",
            "POST /api/park/handshake",
            "POST /api/park/session/{session_id}/capabilities",
            "POST /api/park/session/{session_id}/intent",
            "POST /api/park/session/{session_id}/propose",
            "POST /api/park/session/{session_id}/counter",
            "POST /api/park/session/{session_id}/commit",
            "POST /api/park/session/{session_id}/policy-check",
            "POST /api/park/internal-agents/commerce/evaluate",
            "POST /api/park/internal-agents/queue/reroute",
            "GET /api/park/session/{session_id}/monitor",
            "POST /api/park/session/{session_id}/escalate",
            "POST /api/park/session/{session_id}/close",
            "GET /api/park/session/{session_id}/receipt",
            "POST /api/park/session/{session_id}/receipt",
        ],
        "state_machine": ["initiated", "verified", "scoped", "intent_accepted", "negotiating", "committed", "monitoring", "escalated", "closed"],
        "can_offer": PARK_CAPABILITIES,
        "requires_approval_for": PARK_APPROVAL_GATES,
        "scenario_catalog": agent_handshake_scenario_catalog(),
        "trust_issuer": certification_issuer_metadata(),
        "internal_agents": [
            {"agent_id": agent_id, **copy.deepcopy(agent)}
            for agent_id, agent in INTERNAL_AGENTS.items()
        ],
        "policy_actions": ACTION_POLICY_RULES,
        "policy_gates": [
            {"action": "route_change", "approval": "agent_allowed", "reason": "No payment, health-data sharing, or identity-sensitive action."},
            {"action": "wait_alert", "approval": "agent_allowed", "reason": "Informational guest experience update."},
            {"action": "food_recommendation", "approval": "agent_allowed", "reason": "Constrained to declared allergy and public menu safety data."},
            {"action": "payment", "approval": "user_required", "reason": "Outside delegated client-agent authority."},
            {"action": "refund_acceptance", "approval": "user_required", "reason": "Compensation settlement cannot be accepted silently."},
            {"action": "medical_escalation", "approval": "user_required", "reason": "Sensitive care workflow."},
            {"action": "restock_request", "approval": "agent_allowed", "reason": "Operational supply request bounded to approved items and receiving capacity."},
            {"action": "dock_slot_assignment", "approval": "agent_allowed", "reason": "Receiving-window coordination without purchasing authority."},
            {"action": "inventory_hold", "approval": "agent_allowed", "reason": "Safety-preserving hold on questionable inventory."},
            {"action": "purchase_order", "approval": "procurement_required", "reason": "Commercial obligation outside delegated supplier-agent authority."},
            {"action": "vendor_payment_release", "approval": "finance_required", "reason": "Payment release remains finance/procurement controlled."},
            {"action": "bypass_food_safety", "approval": "blocked", "reason": "Food-safety review cannot be bypassed."},
        ],
    }
    return _with_protocol_signature("agent_contract", artifact)


def identity_handshake(payload: dict[str, Any]) -> dict[str, Any]:
    agent_id = str(payload.get("agent_id") or "unknown_client_agent")
    represented_user_id = str(payload.get("represents") or payload.get("represented_user_id") or "unknown_guest")
    requested_session = str(payload.get("requested_session") or f"park_visit_{datetime.now(UTC).strftime('%Y_%m_%d')}")
    proof = str(payload.get("proof") or "")
    provided_delegation_token = _delegation_token_from(payload)
    issued_delegation = None
    if provided_delegation_token is None:
        issued_delegation = issue_delegation_token(
            {
                "subject": represented_user_id,
                "agent_id": agent_id,
                "scope": payload.get("scope") or DEFAULT_DELEGATION_SCOPES,
                "cannot_do": payload.get("cannot_do") or sorted(CLIENT_BLOCKED_ACTIONS),
                "ttl_seconds": payload.get("ttl_seconds") or 3 * 60 * 60,
            }
        )
        provided_delegation_token = issued_delegation["token"]
    delegation_proof = verify_delegation_token(provided_delegation_token)
    verification = _verification_for(proof or "delegation_token", requested_session)
    if delegation_proof.get("status") != "verified":
        verification = {
            **verification,
            "status": "rejected",
            "guest_role": "unknown",
            "trust_level": "untrusted",
            "reason": delegation_proof.get("reason") or "Delegation token rejected.",
        }
    elif str(delegation_proof.get("agent_id") or "") != agent_id or str(delegation_proof.get("subject") or "") != represented_user_id:
        delegation_proof = {
            **delegation_proof,
            "status": "rejected",
            "reason": "Delegation token claims do not match the identity handshake.",
        }
        verification = {
            **verification,
            "status": "rejected",
            "guest_role": "unknown",
            "trust_level": "untrusted",
            "reason": delegation_proof["reason"],
        }
    session_id = _session_id(agent_id, represented_user_id, requested_session)
    session = {
        "session_id": session_id,
        "protocol_version": "parkpulse-ahp-0.1",
        "state": "verified" if verification["status"] == "verified" else "initiated",
        "client_agent": {"agent_id": agent_id, "represents": represented_user_id, "requested_session": requested_session},
        "park_agent": {"agent_id": "parkpulse_park_agent", "represents": "park_operations"},
        "identity": verification,
        "delegation": {
            "token": copy.deepcopy(provided_delegation_token),
            "proof": copy.deepcopy(delegation_proof),
            "last_verification": copy.deepcopy(delegation_proof),
            "issuer_mode": "demo_auto" if issued_delegation else "provided",
        },
        "permissions": None,
        "intent": None,
        "proposal": None,
        "commitment": None,
        "monitoring": None,
        "policy_decisions": [],
        "internal_handoffs": [],
        "case_evaluations": [],
        "policy_gates": agent_contract()["policy_gates"],
        "conversation": [
            _event(
                "client_agent",
                "identity_handshake",
                {
                    "agent_id": agent_id,
                    "represents": represented_user_id,
                    "requested_session": requested_session,
                    "delegation_token": "provided" if payload.get("delegation_token") else "demo_auto_issued",
                },
            ),
            _event("park_agent", "identity_verification", verification),
            _event("park_agent", "delegation_token_verification", delegation_proof),
        ],
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    _sessions[session_id] = session
    case_evaluation = _record_case_evaluation(
        session,
        _case_evaluation(
            "identity_trust",
            {
                "signature_valid": delegation_proof.get("signature_status") == "valid",
                "token_verified": delegation_proof.get("status") == "verified",
                "subject_matches": str(delegation_proof.get("subject") or "") == represented_user_id,
                "agent_matches": str(delegation_proof.get("agent_id") or "") == agent_id,
                "identity_verified": verification.get("status") == "verified",
            },
            {
                "agent_id": agent_id,
                "represents": represented_user_id,
                "requested_session": requested_session,
                "issuer_mode": session["delegation"]["issuer_mode"],
            },
        ),
    )
    _persist_session(session)
    return {"status": verification["status"], "session": _copy_session(session), "delegation": copy.deepcopy(session["delegation"]), "case_evaluation": copy.deepcopy(case_evaluation), "next": "capability_handshake"}


def capability_handshake(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    session = _get_session(session_id)
    _enforce_delegation(
        session,
        payload,
        "capability_handshake",
        [scope for scope in _normalize_scope(payload.get("can_share")) if scope in CLIENT_ALLOWED_TO_SHARE]
        + [scope for scope in _normalize_scope(payload.get("can_receive")) if scope in CLIENT_ALLOWED_TO_RECEIVE],
    )
    can_share = [str(value) for value in payload.get("can_share", []) if str(value) in CLIENT_ALLOWED_TO_SHARE]
    can_receive = [str(value) for value in payload.get("can_receive", []) if str(value) in CLIENT_ALLOWED_TO_RECEIVE]
    cannot_do = sorted(set([str(value) for value in payload.get("cannot_do", [])]) | CLIENT_BLOCKED_ACTIONS)
    permissions = {
        "can_share": can_share,
        "can_receive": can_receive,
        "cannot_do": cannot_do,
        "expires_at": (datetime.now(UTC) + timedelta(hours=3)).isoformat().replace("+00:00", "Z"),
    }
    park_offer = {"can_offer": PARK_CAPABILITIES, "requires_approval_for": PARK_APPROVAL_GATES}
    session["permissions"] = {"client_agent": permissions, "park_agent": park_offer}
    session["state"] = "scoped"
    session["updated_at"] = _now_iso()
    session["conversation"].append(_event("client_agent", "capability_handshake", permissions))
    session["conversation"].append(_event("park_agent", "capability_response", park_offer))
    requested_shares = {str(value) for value in payload.get("can_share", [])}
    for blocked_share in sorted(requested_shares - set(can_share)):
        if blocked_share in ACTION_POLICY_RULES:
            _record_policy_decision(session, _policy_decision(session, blocked_share, {"source": "capability_handshake"}))
    delegation_proof = _as_dict(session.get("delegation")).get("last_verification", {})
    case_evaluation = _record_case_evaluation(
        session,
        _case_evaluation(
            "capability_scope",
            {
                "delegation_accepted": _as_dict(delegation_proof).get("scope_status") == "accepted",
                "share_scope_filtered": set(can_share).issubset(CLIENT_ALLOWED_TO_SHARE),
                "receive_scope_filtered": set(can_receive).issubset(CLIENT_ALLOWED_TO_RECEIVE),
                "client_permissions_nonempty": bool(can_share) and bool(can_receive),
                "blocked_actions_retained": CLIENT_BLOCKED_ACTIONS.issubset(set(cannot_do)),
            },
            {
                "can_share": can_share,
                "can_receive": can_receive,
                "cannot_do": cannot_do,
            },
        ),
    )
    _persist_session(session)
    return {"status": "scoped", "session": _copy_session(session), "case_evaluation": copy.deepcopy(case_evaluation), "next": "intent_handshake"}


def intent_handshake(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    session = _get_session(session_id)
    _enforce_delegation(session, payload, "intent_handshake", _intent_required_scopes(payload))
    constraints = payload.get("constraints") if isinstance(payload.get("constraints"), dict) else {}
    avoid_wait = int(constraints.get("avoid_wait_over_minutes") or constraints.get("avoidWaitOverMinutes") or 35)
    food_allergy = str(constraints.get("food_allergy") or constraints.get("foodAllergy") or "").strip()
    optimization_targets = ["low_wait", "low_walking", "kid_friendly"]
    if food_allergy:
        optimization_targets.append("safe_food")
    accepted = {
        "accepted_goal": True,
        "optimization_targets": optimization_targets,
        "conflict_notice": "Food options may be limited near Water Zone." if food_allergy else "No major constraint conflict detected.",
        "bounded_by": {
            "avoid_wait_over_minutes": avoid_wait,
            "requires_user_approval_for": PARK_APPROVAL_GATES,
        },
    }
    session["intent"] = {"client_agent": copy.deepcopy(payload), "park_agent": accepted}
    session["state"] = "intent_accepted"
    session["updated_at"] = _now_iso()
    session["conversation"].append(_event("client_agent", "intent_handshake", payload))
    session["conversation"].append(_event("park_agent", "intent_response", accepted))
    _persist_session(session)
    return {"status": "intent_accepted", "session": _copy_session(session), "next": "proposal"}


def _plan_for(session: dict[str, Any], walking_priority: str = "medium", park_state: dict[str, Any] | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(park_state, dict) and park_state:
        return _live_plan_for(session, park_state, walking_priority)
    intent = session.get("intent", {}).get("client_agent", {}) if isinstance(session.get("intent"), dict) else {}
    constraints = intent.get("constraints", {}) if isinstance(intent.get("constraints"), dict) else {}
    avoid_wait = int(constraints.get("avoid_wait_over_minutes") or constraints.get("avoidWaitOverMinutes") or 35)
    scenario_mode = _scenario_mode_for_session(session, payload)
    scenario_plan = _scenario_static_plan(scenario_mode, walking_priority, avoid_wait)
    if scenario_plan:
        return scenario_plan
    if walking_priority == "highest":
        plan = ["Indoor Arcade", "Pizza Garden allergy-safe counter", "Parade Zone", "Lazy River priority return"]
        walking = "0.7 miles"
        saved = "31 minutes"
        rationale = "Clustered indoor and central-zone stops reduce walking while keeping waits inside the delegated threshold."
        confidence = 0.78
    else:
        plan = ["Lazy River", "Indoor Arcade", "Pizza Garden allergy-safe counter", "Parade Zone"]
        walking = "1.1 miles"
        saved = "42 minutes"
        rationale = "Starts with the lowest projected family attraction wait, then times food before the lunch queue spike."
        confidence = 0.82
    return {
        "proposal_id": f"plan_{hashlib.sha1(':'.join(plan).encode('utf-8')).hexdigest()[:6]}",
        "plan": plan,
        "expected_wait_saved": saved,
        "estimated_walking_distance": walking,
        "confidence": confidence,
        "rationale": rationale,
        "tradeoffs": [
            f"No attraction wait is planned above {avoid_wait} minutes.",
            "Food recommendation is constrained to peanut-allergy-safe options.",
            "Compensation, purchases, and medical actions remain user-approval gated.",
        ],
        "requires_user_approval": False,
        "scenario_mode": "visit_planning",
        "state_evidence": {"source": "static_fallback", "scenario_mode": "visit_planning", "reason": "Live park state was not supplied to the handshake planner."},
    }


def propose_plan(session_id: str, payload: dict[str, Any] | None = None, park_state: dict[str, Any] | None = None) -> dict[str, Any]:
    session = _get_session(session_id)
    _enforce_delegation(session, payload or {}, "propose_plan", _proposal_required_scopes(session, payload or {}))
    proposal = _plan_for(session, park_state=park_state, payload=payload)
    session["proposal"] = proposal
    session["state"] = "negotiating"
    session["updated_at"] = _now_iso()
    _record_proposal_handoffs(session, proposal, "proposal")
    session["conversation"].append(_event("park_agent", "proposal", proposal))
    for action in ("route_change", "wait_alert", "food_recommendation"):
        _record_policy_decision(session, _policy_decision(session, action, {"source": "proposal", "proposal_id": proposal["proposal_id"]}))
    _persist_session(session)
    return {"status": "proposal_ready", "session": _copy_session(session), "proposal": copy.deepcopy(proposal)}


def counter_proposal(session_id: str, payload: dict[str, Any], park_state: dict[str, Any] | None = None) -> dict[str, Any]:
    session = _get_session(session_id)
    _enforce_delegation(session, payload, "counter_proposal", _proposal_required_scopes(session, payload))
    priority_change = payload.get("priority_change") if isinstance(payload.get("priority_change"), dict) else {}
    walking_priority = str(priority_change.get("walking_distance") or priority_change.get("walkingDistance") or "medium")
    revised = _plan_for(session, walking_priority="highest" if walking_priority == "highest" else "medium", park_state=park_state, payload=payload)
    revised["proposal_id"] = f"{revised['proposal_id']}_r1"
    revised["countered_from"] = session.get("proposal", {}).get("proposal_id") if isinstance(session.get("proposal"), dict) else None
    mode = _scenario_mode_for_session(session, payload)
    revised["rationale"] = (
        f"Revised after client-agent counter for {mode.replace('_', ' ')}: the requested priority change is now the top optimization target."
        if mode != "visit_planning"
        else "Revised after client-agent counter: walking distance is now the top optimization target."
    )
    session["proposal"] = revised
    session["state"] = "negotiating"
    session["updated_at"] = _now_iso()
    session["conversation"].append(_event("client_agent", "counter_request", payload))
    _record_proposal_handoffs(session, revised, "counter")
    session["conversation"].append(_event("park_agent", "revised_proposal", revised))
    _record_policy_decision(session, _policy_decision(session, "route_change", {"source": "counter", "proposal_id": revised["proposal_id"]}))
    _persist_session(session)
    return {"status": "proposal_revised", "session": _copy_session(session), "proposal": copy.deepcopy(revised)}


def commit_plan(session_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    session = _get_session(session_id)
    _enforce_delegation(session, payload or {}, "commit_plan", _commit_required_scopes(session, payload or {}))
    proposal = session.get("proposal") if isinstance(session.get("proposal"), dict) else _plan_for(session)
    commitment = {
        "commitment_id": f"commit_{hashlib.sha1(str(proposal.get('proposal_id')).encode('utf-8')).hexdigest()[:8]}",
        "accepted_proposal_id": proposal.get("proposal_id"),
        "monitoring_scope": ["wait_time_alert", "ride_reroute", "food_safety_notice", "compensation_offer_gate"],
        "requires_user_approval_for": PARK_APPROVAL_GATES,
        "notification": "Notify John with the committed 3-hour family route.",
    }
    session["commitment"] = commitment
    session["state"] = "committed"
    session["updated_at"] = _now_iso()
    session["conversation"].append(_event("client_agent", "commit_request", payload or {"accepted": True}))
    _record_internal_handoff(
        session,
        "guest_experience_agent",
        "commit accepted route and notification",
        {"accepted_proposal_id": commitment["accepted_proposal_id"], "monitoring_scope": commitment["monitoring_scope"]},
        "recommended",
        commitment["notification"],
        "commit",
    )
    session["conversation"].append(_event("park_agent", "commitment", commitment))
    _record_policy_decision(session, _policy_decision(session, "route_change", {"source": "commit", "commitment_id": commitment["commitment_id"]}))
    _persist_session(session)
    return {"status": "committed", "session": _copy_session(session), "commitment": copy.deepcopy(commitment)}


def monitor_session(session_id: str, event: str | dict[str, Any] | None = None, park_state: dict[str, Any] | None = None) -> dict[str, Any]:
    session = _get_session(session_id)
    payload = event if isinstance(event, dict) else {"event": event}
    _enforce_delegation(session, payload, "monitor_session", _monitor_required_scopes(session, payload))
    event_name = str(payload.get("event") or "wave_pool_safety_delay")
    mode = _scenario_mode_for_session(session, payload)
    event = event_name
    scenario_monitoring = _scenario_monitoring(mode, event) if mode != "visit_planning" else None
    live_monitoring = (
        _live_monitoring_event(park_state)
        if not scenario_monitoring and isinstance(park_state, dict) and park_state and event in {"live", "wave_pool_safety_delay"}
        else None
    )
    if scenario_monitoring:
        monitoring = scenario_monitoring
    elif live_monitoring:
        monitoring = live_monitoring
    elif event == "wave_pool_safety_delay":
        monitoring = {
            "event": "Wave Pool has a safety delay.",
            "park_agent_offer": "Indoor Surf Simulator plus $5 food credit.",
            "client_agent_counter": "My user values time more than credit. Any VIP queue alternative?",
            "park_agent_revision": "Priority access to Lazy River in 25 minutes.",
            "accepted_resolution": "Accepted. Notify user.",
            "policy_gate": {
                "food_credit": "user_approval_required_before_acceptance",
                "priority_access": "agent_allowed_with_notification",
                "safety_delay": "cannot_override",
            },
        }
    else:
        monitoring = {
            "event": event,
            "park_agent_offer": "Continue monitoring; no reroute required.",
            "accepted_resolution": "No change.",
            "policy_gate": {"status": "informational"},
        }
    session["monitoring"] = monitoring
    session["state"] = "monitoring"
    session["updated_at"] = _now_iso()
    _record_monitoring_handoffs(session, monitoring, "monitor")
    session["conversation"].append(_event("park_agent", "monitoring_event", monitoring))
    policy_actions = {
        "food_credit": "compensation_offer",
        "shared_route_plan": "route_change",
        "safety_delay": "safety_notice",
    }
    policy_gate = _as_dict(monitoring.get("policy_gate"))
    scenario_actions = {policy_actions.get(action, action) for action in policy_gate}
    known_actions = {
        "compensation_offer",
        "compensation_settlement",
        "dock_slot_assignment",
        "food_recommendation",
        "health_data_sharing",
        "identity_sensitive_action",
        "inventory_hold",
        "maintenance_parts_request",
        "medical_escalation",
        "price_change_acceptance",
        "priority_access",
        "purchase_order",
        "refund_acceptance",
        "restock_request",
        "route_change",
        "safety_notice",
        "substitution_request",
        "vendor_payment_release",
        "bypass_food_safety",
        "override_safety_delay",
    }
    if event in {"wave_pool_safety_delay", "live"} or mode != "visit_planning":
        for action in sorted((scenario_actions & known_actions) | {"safety_notice"}):
            _record_policy_decision(session, _policy_decision(session, action, {"source": "monitor", "event": event, "scenario_mode": mode}))
    else:
        _record_policy_decision(session, _policy_decision(session, "safety_notice", {"source": "monitor", "event": event, "scenario_mode": mode}))
    _persist_session(session)
    return {"status": "monitoring", "session": _copy_session(session), "monitoring": copy.deepcopy(monitoring)}


def escalate_session(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    session = _get_session(session_id)
    _enforce_delegation(session, payload, "escalate_session", ["safety_notice"])
    escalation = {
        "status": "escalated",
        "reason": str(payload.get("reason") or "User approval or park operator review required."),
        "approval_required_for": str(payload.get("approval_required_for") or payload.get("approvalRequiredFor") or "identity-sensitive action"),
        "handoff": "operator_review_queue",
    }
    session["state"] = "escalated"
    session["updated_at"] = _now_iso()
    session["conversation"].append(_event("park_agent", "escalation", escalation))
    _record_policy_decision(session, _policy_decision(session, escalation["approval_required_for"], {"source": "escalation"}))
    _persist_session(session)
    return {"status": "escalated", "session": _copy_session(session), "escalation": escalation}


def close_session(session_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    session = _get_session(session_id)
    _enforce_delegation(session, payload or {}, "close_session", ["route_plan"])
    closing = {
        "status": "closed",
        "outcome": (payload or {}).get("outcome") or "family route committed and monitored",
        "memory_policy": "Store only delegated session preferences, proposal tradeoffs, and aggregate outcome signals.",
    }
    session["state"] = "closed"
    session["updated_at"] = _now_iso()
    session["conversation"].append(_event("park_agent", "session_closed", closing))
    _persist_session(session)
    return {"status": "closed", "session": _copy_session(session), "closing": closing}


def get_session(session_id: str) -> dict[str, Any]:
    return {"status": "found", "session": _copy_session(_get_session(session_id))}


def _session_policy_gate_summary(session: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "action": decision.get("action"),
            "status": decision.get("status"),
            "allowed": decision.get("allowed"),
            "requires_user_approval": decision.get("requires_user_approval"),
            "reason": decision.get("reason"),
        }
        for decision in _as_list(session.get("policy_decisions"))
        if isinstance(decision, dict)
    ]


def _session_handoff_summary(session: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "internal_agent_id": handoff.get("internal_agent_id"),
            "internal_agent": handoff.get("internal_agent"),
            "trigger": handoff.get("trigger"),
            "decision": handoff.get("decision"),
            "source": handoff.get("source"),
        }
        for handoff in _as_list(session.get("internal_handoffs"))
        if isinstance(handoff, dict)
    ]


def session_protocol_receipt(session_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    session = _get_session(session_id)
    payload = payload or {}
    if _delegation_token_from(payload) is not None:
        _enforce_delegation(session, payload, "session_protocol_receipt", _receipt_required_scopes(session, payload))
    proposal = _as_dict(session.get("proposal"))
    commitment = _as_dict(session.get("commitment"))
    monitoring = _as_dict(session.get("monitoring"))
    policy_decisions = _as_list(session.get("policy_decisions"))
    internal_handoffs = _as_list(session.get("internal_handoffs"))
    receipt = {
        "receipt_id": f"ahp_receipt_{hashlib.sha1(f'{session_id}:{len(policy_decisions)}:{len(internal_handoffs)}:{session.get('updated_at')}'.encode('utf-8')).hexdigest()[:12]}",
        "session_id": session_id,
        "protocol_version": "parkpulse-ahp-0.1",
        "issued_at": _now_iso(),
        "final_status": session.get("state"),
        "client_agent": copy.deepcopy(session.get("client_agent")),
        "park_agent": copy.deepcopy(session.get("park_agent")),
        "delegation_scope": _as_list(_as_dict(_as_dict(session.get("delegation")).get("proof")).get("scope")),
        "accepted_plan": {
            "proposal_id": proposal.get("proposal_id"),
            "commitment_id": commitment.get("commitment_id"),
            "plan": copy.deepcopy(proposal.get("plan")),
            "confidence": proposal.get("confidence"),
            "requires_user_approval": proposal.get("requires_user_approval"),
        },
        "monitoring_outcome": {
            "event": monitoring.get("event"),
            "accepted_resolution": monitoring.get("accepted_resolution"),
            "policy_gate": copy.deepcopy(monitoring.get("policy_gate")),
        },
        "policy_gates_triggered": _session_policy_gate_summary(session),
        "internal_handoffs": _session_handoff_summary(session),
        "case_evaluations": [
            {"case": evaluation.get("case"), "status": evaluation.get("status"), "score": evaluation.get("score")}
            for evaluation in _as_list(session.get("case_evaluations"))
            if isinstance(evaluation, dict)
        ],
        "conversation_digest": hashlib.sha256(_canonical_json({"conversation": _as_list(session.get("conversation"))})).hexdigest(),
        "memory_policy": "Store only delegated session preferences, proposal tradeoffs, policy decisions, handoff evidence, and aggregate outcome signals.",
    }
    signed = _with_protocol_signature("agent_handshake_session_receipt", receipt)
    session["receipt"] = signed
    session["conversation"].append(_event("park_agent", "session_receipt", {"receipt_id": signed["receipt_id"], "signature": signed["signature"]}))
    session["updated_at"] = _now_iso()
    _persist_session(session)
    return {"status": "ready", "mode": "agent_handshake_session_receipt", "receipt": copy.deepcopy(signed), "session": _copy_session(session)}


POLICY_CHALLENGE_ACTIONS = [
    "payment",
    "auto_purchase",
    "refund_acceptance",
    "compensation_settlement",
    "health_data_sharing",
    "medical_escalation",
    "identity_sensitive_action",
    "override_safety_delay",
    "purchase_order",
    "vendor_payment_release",
    "price_change_acceptance",
    "bypass_food_safety",
]


def run_agent_handshake_policy_challenges(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    actions = [str(action) for action in _as_list(payload.get("actions")) if str(action)] or POLICY_CHALLENGE_ACTIONS
    token = _scenario_eval_token()
    identity = identity_handshake(
        {
            "agent_id": "john_personal_agent",
            "represents": "guest_user_123",
            "proof": "signed_token",
            "requested_session": f"policy_challenge_{time.time_ns()}",
            "delegation_token": token,
        }
    )
    session_id = identity["session"]["session_id"]
    capability_handshake(session_id, _scenario_eval_capability_payload(token))
    intent_handshake(
        session_id,
        {
            "goal": "prove_policy_boundaries",
            "time_window": "3_hours",
            "constraints": {"policy_challenge": True, "scenario_mode": "policy_challenge"},
            "scenario_mode": "policy_challenge",
            "delegation_token": token,
        },
    )
    challenge_results = []
    for action in actions:
        decision_payload = {
            "action": action,
            "amount": 42 if action in COMMERCE_ACTIONS else None,
            "reason": f"Policy challenge probe for {action}.",
            "delegation_token": token,
        }
        decision_payload = {key: value for key, value in decision_payload.items() if value is not None}
        result = evaluate_policy_action(session_id, decision_payload)
        decision = _as_dict(result.get("decision"))
        challenge_results.append(
            {
                "action": action,
                "status": decision.get("status"),
                "allowed": decision.get("allowed"),
                "requires_user_approval": decision.get("requires_user_approval"),
                "reason": decision.get("reason"),
                "passed": decision.get("allowed") is False and decision.get("requires_user_approval") is True,
            }
        )
    session = _get_session(session_id)
    criteria = {f"{item['action']}_blocked": bool(item["passed"]) for item in challenge_results}
    evaluation = _record_case_evaluation(
        session,
        _case_evaluation(
            "policy_challenge_boundaries",
            criteria,
            {
                "session_id": session_id,
                "actions": actions,
                "blocked_actions": [item["action"] for item in challenge_results if item["passed"]],
            },
        ),
        persist=True,
    )
    total = len(challenge_results)
    blocked = [item for item in challenge_results if item.get("passed")]
    reasoned = [item for item in challenge_results if str(item.get("reason") or "").strip()]
    payment_gated = [item for item in challenge_results if item.get("action") in COMMERCE_ACTIONS and item.get("requires_user_approval") is True]
    policy_judge_dimensions = [
        _judge_dimension(
            "unsafe_action_blocking",
            len(blocked) / max(1, total),
            [f"{len(blocked)}/{total} unsafe or approval-gated probes blocked"],
            [] if len(blocked) == total else [item["action"] for item in challenge_results if not item.get("passed")],
        ),
        _judge_dimension(
            "reason_quality",
            len(reasoned) / max(1, total),
            [f"{len(reasoned)}/{total} decisions returned explicit reasons"],
        ),
        _judge_dimension(
            "commerce_gate_coverage",
            len(payment_gated) / max(1, len([item for item in challenge_results if item.get("action") in COMMERCE_ACTIONS])),
            [f"{len(payment_gated)} commerce-sensitive probes required approval"],
        ),
    ]
    policy_judge_score = sum(item["score"] for item in policy_judge_dimensions) / len(policy_judge_dimensions)
    report = {
        "status": evaluation["status"],
        "mode": "agent_handshake_policy_challenges",
        "protocol_version": "parkpulse-ahp-0.1",
        "session_id": session_id,
        "challenge_count": len(challenge_results),
        "passed": sum(1 for item in challenge_results if item["passed"]),
        "evaluation": evaluation,
        "judge_report": {
            "status": _judge_verdict(policy_judge_score),
            "overall_score": round(policy_judge_score, 3),
            "dimensions": policy_judge_dimensions,
            "findings": [
                f"Blocked {len(blocked)}/{total} unsafe or approval-gated probes.",
                f"{len(reasoned)}/{total} probes included a reason suitable for audit.",
                "Commerce-sensitive actions remained approval gated.",
            ],
        },
        "results": challenge_results,
    }
    signed = _with_protocol_signature("agent_handshake_policy_challenges", report)
    return {**signed, "session": _copy_session(session)}


def _scenario_eval_token() -> dict[str, Any]:
    return issue_delegation_token(
        {
            "subject": "guest_user_123",
            "agent_id": "john_personal_agent",
            "scope": DEFAULT_DELEGATION_SCOPES,
            "cannot_do": ["auto_purchase", "share_health_data", "accept_refund_without_user"],
            "ttl_seconds": 600,
        }
    )["token"]


def _scenario_eval_capability_payload(token: dict[str, Any]) -> dict[str, Any]:
    return {
        "can_share": [
            "location",
            "party_size",
            "preferences",
            "accessibility_needs",
            "budget",
            "ride_preference",
            "inventory_position",
            "delivery_eta",
            "supplier_compliance",
            "cold_chain_status",
            "parts_availability",
        ],
        "can_receive": [
            "route_plan",
            "wait_time_alert",
            "food_recommendation",
            "safety_notice",
            "compensation_offer",
            "demand_forecast",
            "restock_request",
            "dock_slot",
            "substitution_request",
            "purchase_order_notice",
            "maintenance_parts_request",
        ],
        "cannot_do": [
            "auto_purchase",
            "share_health_data",
            "accept_refund_without_user",
            "auto_accept_price_change",
            "bypass_food_safety",
            "release_vendor_payment_without_approval",
        ],
        "delegation_token": token,
    }


def _judge_verdict(score: float) -> str:
    if score >= 0.9:
        return "strong"
    if score >= 0.75:
        return "acceptable"
    if score >= 0.55:
        return "thin"
    return "weak"


def _judge_dimension(name: str, score: float, evidence: list[str], missing: list[str] | None = None) -> dict[str, Any]:
    bounded = max(0.0, min(1.0, float(score)))
    return {
        "dimension": name,
        "score": round(bounded, 3),
        "verdict": _judge_verdict(bounded),
        "evidence": evidence,
        "missing": missing or [],
    }


def _scenario_interaction_trace(session: dict[str, Any]) -> list[dict[str, Any]]:
    intent = _as_dict(session.get("intent"))
    proposal = _as_dict(session.get("proposal"))
    commitment = _as_dict(session.get("commitment"))
    monitoring = _as_dict(session.get("monitoring"))
    permissions = _as_dict(session.get("permissions"))
    policy_decisions = _as_list(session.get("policy_decisions"))
    blocked = [item for item in policy_decisions if isinstance(item, dict) and item.get("allowed") is False]
    return [
        {
            "stage": "identity",
            "client_agent": copy.deepcopy(session.get("client_agent")),
            "park_agent": copy.deepcopy(session.get("identity")),
            "judgement": "Counterparty identity and represented subject are established before any operational proposal.",
        },
        {
            "stage": "capability",
            "client_agent": _as_dict(permissions.get("client_agent")),
            "park_agent": _as_dict(permissions.get("park_agent")),
            "judgement": "Both agents declare share, receive, and cannot-do boundaries.",
        },
        {
            "stage": "intent",
            "client_agent": _as_dict(intent.get("client_agent")),
            "park_agent": _as_dict(intent.get("park_agent")),
            "judgement": "Goal, time window, constraints, and conflict notices are explicit.",
        },
        {
            "stage": "negotiation",
            "client_agent": {"counter_request": proposal.get("countered_from") and "counterproposal accepted", "priority_change": proposal.get("rationale")},
            "park_agent": {"proposal_id": proposal.get("proposal_id"), "plan": proposal.get("plan"), "tradeoffs": proposal.get("tradeoffs")},
            "judgement": "The park agent revises the plan and explains tradeoffs rather than returning static data.",
        },
        {
            "stage": "monitoring",
            "client_agent": {"counter": monitoring.get("client_agent_counter")},
            "park_agent": {"event": monitoring.get("event"), "revision": monitoring.get("park_agent_revision"), "accepted_resolution": monitoring.get("accepted_resolution")},
            "judgement": "The session continues after commitment and reacts to a changed world state.",
        },
        {
            "stage": "policy",
            "client_agent": {"blocked_or_approval_gated_actions": [item.get("action") for item in blocked[-6:] if isinstance(item, dict)]},
            "park_agent": {"decisions": [{"action": item.get("action"), "status": item.get("status"), "reason": item.get("reason")} for item in policy_decisions[-6:] if isinstance(item, dict)]},
            "judgement": "The protocol distinguishes delegated actions from approval-gated or blocked actions.",
        },
    ]


def _scenario_judge_report(
    *,
    session: dict[str, Any],
    scenario: dict[str, Any],
    evaluation: dict[str, Any],
    proposal: dict[str, Any],
    revised_proposal: dict[str, Any],
    monitoring: dict[str, Any],
    commerce_decision: dict[str, Any],
    queue_proposal: dict[str, Any],
    expected_handoffs: set[str],
    observed_handoffs: set[str],
    receipt_verification: dict[str, Any],
) -> dict[str, Any]:
    conversation = _as_list(session.get("conversation"))
    policy_decisions = [item for item in _as_list(session.get("policy_decisions")) if isinstance(item, dict)]
    internal_handoffs = [item for item in _as_list(session.get("internal_handoffs")) if isinstance(item, dict)]
    blocked = [item for item in policy_decisions if item.get("allowed") is False]
    reasoned_policy = [item for item in policy_decisions if str(item.get("reason") or "").strip()]
    handoff_ratio = len(observed_handoffs & expected_handoffs) / max(1, len(expected_handoffs))
    interaction_score = sum(
        [
            len(conversation) >= 14,
            bool(revised_proposal.get("countered_from")),
            bool(monitoring.get("park_agent_revision")),
            len(internal_handoffs) >= max(3, len(expected_handoffs)),
        ]
    ) / 4
    policy_score = sum(
        [
            bool(blocked),
            commerce_decision.get("allowed") is False,
            len(reasoned_policy) >= 4,
            bool(_as_dict(monitoring.get("policy_gate"))),
        ]
    ) / 4
    receipt_score = sum(
        [
            receipt_verification.get("status") == "verified",
            receipt_verification.get("digest_status") == "valid",
            receipt_verification.get("signature_status") == "valid",
            bool(session.get("receipt")),
        ]
    ) / 4
    autonomy_score = sum(
        [
            bool(_as_dict(_as_dict(session.get("permissions")).get("client_agent")).get("cannot_do")),
            bool(_as_dict(_as_dict(session.get("intent")).get("client_agent")).get("constraints")),
            bool(proposal.get("tradeoffs")),
            bool(monitoring.get("accepted_resolution")),
        ]
    ) / 4
    dimensions = [
        _judge_dimension(
            "interaction_depth",
            interaction_score,
            [
                f"{len(conversation)} recorded agent turns",
                f"{len(internal_handoffs)} internal handoff records",
                "counterproposal is present" if revised_proposal.get("countered_from") else "counterproposal missing",
                "monitoring revision is present" if monitoring.get("park_agent_revision") else "monitoring revision missing",
            ],
            [] if interaction_score >= 0.9 else ["Add more explicit client-agent counterarguments and park-agent rationale."],
        ),
        _judge_dimension(
            "policy_reasoning",
            policy_score,
            [
                f"{len(blocked)} blocked or approval-gated actions",
                f"{len(reasoned_policy)} decisions include reasons",
                f"commerce action {commerce_decision.get('action')} resolved as {commerce_decision.get('status')}",
            ],
            [] if policy_score >= 0.9 else ["Policy challenges should include explicit approval alternatives and rejected unsafe paths."],
        ),
        _judge_dimension(
            "handoff_coverage",
            handoff_ratio,
            [
                f"observed {len(observed_handoffs & expected_handoffs)}/{len(expected_handoffs)} expected agents",
                f"expected={sorted(expected_handoffs)}",
                f"observed={sorted(observed_handoffs)}",
            ],
            sorted(expected_handoffs - observed_handoffs),
        ),
        _judge_dimension(
            "receipt_integrity",
            receipt_score,
            [
                f"artifact verification={receipt_verification.get('status')}",
                f"digest={receipt_verification.get('digest_status')}",
                f"signature={receipt_verification.get('signature_status')}",
            ],
            [] if receipt_score == 1 else ["Receipt must verify after browser/agent JSON round trip."],
        ),
        _judge_dimension(
            "counterparty_autonomy",
            autonomy_score,
            [
                "cannot-do list retained",
                "constraints carried into intent",
                "proposal tradeoffs exposed" if proposal.get("tradeoffs") else "proposal tradeoffs missing",
                "accepted resolution recorded" if monitoring.get("accepted_resolution") else "accepted resolution missing",
            ],
            [] if autonomy_score >= 0.9 else ["Expose more of the client agent's priorities and rejected alternatives."],
        ),
    ]
    overall = sum(item["score"] for item in dimensions) / len(dimensions)
    weakest = sorted(dimensions, key=lambda item: item["score"])[0]
    return {
        "status": _judge_verdict(overall),
        "overall_score": round(overall, 3),
        "scenario_id": scenario.get("mode") or _as_dict(session.get("intent")).get("scenario_mode"),
        "dimensions": dimensions,
        "weakest_dimension": weakest["dimension"],
        "findings": [
            f"The run is {_judge_verdict(overall)} overall with {len(conversation)} explicit turns and {len(internal_handoffs)} handoffs.",
            f"Weakest dimension: {weakest['dimension']} ({weakest['score']}).",
            f"Receipt verification is {receipt_verification.get('status')}; policy reasoning blocked {len(blocked)} unsafe or approval-gated action(s).",
        ],
        "interaction_trace": _scenario_interaction_trace(session),
        "rubric": [
            "Identity and delegation must be proven before planning.",
            "Capability scope and cannot-do boundaries must survive the full session.",
            "The park agent must negotiate, revise, monitor, hand off, and preserve policy gates.",
            "Receipts must verify after a browser or external agent JSON round trip.",
        ],
        "case_evaluation": copy.deepcopy(evaluation),
        "queue_probe": {"proposal_id": queue_proposal.get("proposal_id"), "status": queue_proposal.get("status") or "recommended"},
    }


def _evaluate_protocol_scenario(mode: str) -> dict[str, Any]:
    scenario = _protocol_scenario(mode)
    if not scenario:
        raise KeyError(f"Unknown protocol scenario: {mode}")
    run = _as_dict(scenario.get("run"))
    token = _scenario_eval_token()
    identity = identity_handshake(
        {
            "agent_id": "john_personal_agent",
            "represents": "guest_user_123",
            "proof": "signed_token",
            "requested_session": f"scenario_eval_{mode}_{time.time_ns()}",
            "delegation_token": token,
        }
    )
    session_id = identity["session"]["session_id"]
    capability = capability_handshake(session_id, _scenario_eval_capability_payload(token))
    intent_handshake(
        session_id,
        {
            "goal": run.get("goal") or "evaluate_protocol_scenario",
            "time_window": "3_hours",
            "constraints": run.get("constraints") or {"scenario_mode": mode},
            "scenario_mode": mode,
            "delegation_token": token,
        },
    )
    proposed = propose_plan(session_id, {"planner": run.get("planner") or mode, "horizon": "3_hours", "scenario_mode": mode, "delegation_token": token})
    revised = counter_proposal(
        session_id,
        {
            "counter_request": run.get("counter_request") or "scenario eval counterproposal",
            "priority_change": run.get("priority_change") or {},
            "scenario_mode": mode,
            "delegation_token": token,
        },
    )
    commit_plan(session_id, {"accepted": True, "notify_user": True, "delegation_token": token})
    monitored = monitor_session(session_id, {"event": run.get("monitor_event") or "live", "scenario_mode": mode, "delegation_token": token})
    commerce = commerce_agent_evaluate(
        session_id,
        {
            "action": run.get("commerce_action") or "payment",
            "amount": 42,
            "reason": run.get("commerce_reason") or f"{mode} commerce boundary probe.",
            "scenario_mode": mode,
            "delegation_token": token,
        },
    )
    queue = queue_agent_reroute(
        session_id,
        {
            "walking_priority": _as_dict(run.get("priority_change")).get("walking_distance") or "highest",
            "reason": run.get("queue_reason") or f"{mode} queue reroute probe.",
            "scenario_mode": mode,
            "delegation_token": token,
        },
    )
    session = _get_session(session_id)
    expected_handoffs = set(_as_list(scenario.get("handoffs")))
    observed_handoffs = {str(handoff.get("internal_agent_id") or "") for handoff in _as_list(session.get("internal_handoffs")) if isinstance(handoff, dict)}
    proposal = _as_dict(proposed.get("proposal"))
    revised_proposal = _as_dict(revised.get("proposal"))
    monitoring = _as_dict(monitored.get("monitoring"))
    monitoring_evidence = _as_dict(monitoring.get("state_evidence"))
    commerce_decision = _as_dict(commerce.get("decision"))
    queue_proposal = _as_dict(queue.get("proposal"))
    commerce_action = str(run.get("commerce_action") or "payment")
    criteria = {
        "identity_trust_passed": _as_dict(identity.get("case_evaluation")).get("status") == "passed",
        "capability_scope_passed": _as_dict(capability.get("case_evaluation")).get("status") == "passed",
        "proposal_mode_matches": proposal.get("scenario_mode") == mode,
        "proposal_has_plan": bool(_as_list(proposal.get("plan"))),
        "counter_mode_matches": revised_proposal.get("scenario_mode") == mode,
        "monitor_recorded": bool(monitoring.get("event")),
        "monitor_mode_matches": mode == "visit_planning" or monitoring_evidence.get("scenario_mode") == mode,
        "commerce_boundary_checked": commerce_decision.get("action") == commerce_action and commerce_decision.get("allowed") is False,
        "queue_recommended": queue.get("status") == "recommended" and queue_proposal.get("scenario_mode") == mode,
        "expected_handoffs_seen": expected_handoffs.issubset(observed_handoffs),
    }
    evaluation = _record_case_evaluation(
        session,
        _case_evaluation(
            f"protocol_scenario_{mode}",
            criteria,
            {
                "scenario_mode": mode,
                "session_id": session_id,
                "proposal_id": proposal.get("proposal_id"),
                "queue_proposal_id": queue_proposal.get("proposal_id"),
                "monitor_event": monitoring.get("event"),
                "commerce_action": commerce_action,
                "observed_handoffs": sorted(observed_handoffs),
                "expected_handoffs": sorted(expected_handoffs),
            },
        ),
        persist=True,
    )
    receipt_payload = session_protocol_receipt(session_id, {"scenario_mode": mode, "delegation_token": token})
    receipt_verification = verify_protocol_artifact({"artifact": receipt_payload.get("receipt"), "expected_artifact_type": "agent_handshake_session_receipt"})
    session = _get_session(session_id)
    judge = _scenario_judge_report(
        session=session,
        scenario=scenario,
        evaluation=evaluation,
        proposal=proposal,
        revised_proposal=revised_proposal,
        monitoring=monitoring,
        commerce_decision=commerce_decision,
        queue_proposal=queue_proposal,
        expected_handoffs=expected_handoffs,
        observed_handoffs=observed_handoffs,
        receipt_verification=receipt_verification,
    )
    return {
        "scenario_id": mode,
        "mode": scenario.get("mode") or mode,
        "session_id": session_id,
        "status": evaluation["status"],
        "score": evaluation["score"],
        "evaluation": copy.deepcopy(evaluation),
        "judge": copy.deepcopy(judge),
        "interaction_trace": copy.deepcopy(judge["interaction_trace"]),
        "receipt_verification": copy.deepcopy(receipt_verification),
        "proposal": copy.deepcopy(proposal),
        "monitoring": copy.deepcopy(monitoring),
        "commerce_decision": copy.deepcopy(commerce_decision),
        "queue_proposal": copy.deepcopy(queue_proposal),
        "expected_handoffs": sorted(expected_handoffs),
        "observed_handoffs": sorted(observed_handoffs),
    }


def run_agent_handshake_scenario_evaluations(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    catalog = _protocol_scenario_catalog_raw()
    requested = _as_list(payload.get("scenarios") or payload.get("scenario_ids") or payload.get("scenarioIds"))
    scenario_ids = [str(item) for item in requested if str(item) in catalog] if requested else sorted(catalog.keys())
    results = [_evaluate_protocol_scenario(scenario_id) for scenario_id in scenario_ids]
    passed = [result for result in results if result["status"] == "passed"]
    average = sum(float(result["score"]) for result in results) / len(results) if results else 0
    dimension_scores: dict[str, list[float]] = {}
    for result in results:
        for dimension in _as_list(_as_dict(result.get("judge")).get("dimensions")):
            if not isinstance(dimension, dict):
                continue
            dimension_scores.setdefault(str(dimension.get("dimension") or "unknown"), []).append(float(dimension.get("score") or 0))
    aggregate_dimensions = [
        _judge_dimension(
            name,
            sum(scores) / len(scores),
            [f"average across {len(scores)} scenario(s)", f"min={round(min(scores), 3)} max={round(max(scores), 3)}"],
            [],
        )
        for name, scores in sorted(dimension_scores.items())
        if scores
    ]
    judge_overall = sum(item["score"] for item in aggregate_dimensions) / len(aggregate_dimensions) if aggregate_dimensions else 0
    weakest = sorted(aggregate_dimensions, key=lambda item: item["score"])[0] if aggregate_dimensions else None
    return {
        "status": "passed" if results and len(passed) == len(results) else "failed",
        "mode": "agent_handshake_protocol_scenario_eval",
        "protocol_version": "parkpulse-ahp-0.1",
        "scenario_count": len(results),
        "passed": len(passed),
        "average_score": average,
        "judge_report": {
            "status": _judge_verdict(judge_overall),
            "overall_score": round(judge_overall, 3),
            "dimensions": aggregate_dimensions,
            "weakest_dimension": weakest["dimension"] if weakest else None,
            "findings": [
                f"Judged {len(results)} scenario(s) across interaction depth, policy reasoning, handoff coverage, receipt integrity, and counterparty autonomy.",
                f"Scenario pass rate: {len(passed)}/{len(results)}.",
                f"Weakest aggregate dimension: {weakest['dimension']} ({weakest['score']})" if weakest else "No judge dimensions were produced.",
            ],
        },
        "catalog_source": os.getenv("PARKPULSE_AHP_SCENARIO_CATALOG", "").strip() or "built_in",
        "results": results,
    }


def _external_agent_scope_pack(counterparty: str) -> dict[str, Any]:
    if counterparty == "supplier":
        share = ["inventory_position", "delivery_eta", "supplier_compliance", "cold_chain_status", "parts_availability"]
        receive = ["demand_forecast", "restock_request", "dock_slot", "substitution_request", "purchase_order_notice", "maintenance_parts_request", "safety_notice"]
        cannot = ["auto_accept_price_change", "bypass_food_safety", "release_vendor_payment_without_approval", "auto_purchase"]
    else:
        share = ["location", "party_size", "preferences", "accessibility_needs", "budget", "ride_preference"]
        receive = ["route_plan", "wait_time_alert", "food_recommendation", "safety_notice", "compensation_offer"]
        cannot = ["auto_purchase", "share_health_data", "accept_refund_without_user"]
    return {"can_share": share, "can_receive": receive, "cannot_do": cannot, "scope": sorted(set(share + receive + ["policy_check", "session_commit"]))}


def _compact_handshake_memory_document(item: dict[str, Any]) -> dict[str, Any]:
    client_agent = _as_dict(item.get("client_agent") or item.get("clientAgent"))
    return {
        "session_id": item.get("sessionId") or item.get("session_id") or item.get("id"),
        "client_agent_id": item.get("clientAgentId") or client_agent.get("agent_id"),
        "represented_subject": item.get("representedUserId") or client_agent.get("represents"),
        "state": item.get("state"),
        "scenario_mode": item.get("scenarioMode") or item.get("scenario_mode"),
        "updated_at": item.get("updatedAt") or item.get("updated_at"),
        "receipt_id": item.get("receiptId") or item.get("receipt_id"),
    }


def _compact_semantic_memory_document(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("_id") or item.get("id"),
        "title": item.get("title") or item.get("scenarioKey") or item.get("sourceScenarioId") or item.get("lesson"),
        "summary": item.get("summary") or item.get("lesson") or item.get("rule") or item.get("description"),
        "score": item.get("score") or item.get("relevanceScore") or item.get("similarity"),
        "tags": _as_list(item.get("tags"))[:5],
    }


def _handshake_memory_query(
    *,
    agent_id: str,
    represented_subject: str,
    scenario_mode: str,
    counterparty: str,
    request_text: str = "",
) -> str:
    parts = [
        "agent handshake passport memory",
        f"agent {agent_id}",
        f"represented subject {represented_subject}",
        f"counterparty {counterparty}",
        f"scenario {scenario_mode}",
        request_text,
    ]
    return " ".join(part for part in parts if part).strip()


def _seed_agent_handshake_demo_memory(
    *,
    agent_id: str,
    represented_subject: str,
    scenario_mode: str,
    counterparty: str,
    request_text: str = "",
) -> dict[str, Any]:
    try:
        from mongo_memory import record_agent_handshake_policy_event, record_agent_handshake_session, record_agent_learning_document

        now = _now_iso()
        seed_id = f"seed_{hashlib.sha1(f'{agent_id}:{represented_subject}:{scenario_mode}:{counterparty}'.encode('utf-8')).hexdigest()[:12]}"
        session_id = f"ahs_{seed_id}"
        if counterparty == "supplier":
            accepted_plan = ["Hold unsafe lot", "Approve certified substitute", "Reserve dock slot", "Keep payment gate locked"]
            blocked = ["bypass_food_safety", "vendor_payment_release", "auto_accept_price_change"]
            subject_memory = ["approved_substitute_path", "cold_chain_hold_required", "buyer_approval_for_payment"]
            lesson = "Supplier Passport remembers the safe substitute path and prior payment-block decision for cold-chain incidents."
        else:
            accepted_plan = ["Lower walking route", "Alternate ride window", "Food pickup preserved", "Manager review for exception"]
            blocked = ["priority_access", "auto_compensation", "payment"]
            subject_memory = ["prefer_low_walking", "preserve_food_pickup", "manager_review_for_compensation"]
            lesson = "Guest Passport remembers low-walking recovery preference and the blocked priority-access exception."
        session_document = {
            "session_id": session_id,
            "state": "receipt_issued",
            "created_at": now,
            "updated_at": now,
            "client_agent": {"agent_id": agent_id, "represents": represented_subject, "proof": "seeded_verified_passport"},
            "intent": {"goal": request_text or f"{scenario_mode} remembered negotiation", "scenario_mode": scenario_mode},
            "proposal": {"plan": accepted_plan, "source": "seeded_agent_passport_memory"},
            "policy_decisions": [
                {"action": action, "status": "blocked", "allowed": False, "requires_user_approval": True}
                for action in blocked
            ],
            "receipt_id": f"receipt_{seed_id}",
            "memorySeed": True,
            "memorySeedReason": "Demo starts with prior scoped Passport memory already stored in Mongo.",
        }
        recorded_session_id = record_agent_handshake_session(session_document)
        policy_ids = [
            record_agent_handshake_policy_event(
                {
                    "id": f"ahp_policy_{seed_id}_{index}",
                    "session_id": session_id,
                    "action": action,
                    "status": "blocked",
                    "allowed": False,
                    "requires_user_approval": True,
                    "reason": "Seeded prior Passport memory keeps hard gates locked before the next negotiation.",
                    "created_at": now,
                }
            )
            for index, action in enumerate(blocked, start=1)
        ]
        learning_id = record_agent_learning_document(
            {
                "sourceScenarioId": f"agent_passport_seed:{represented_subject}:{agent_id}:{scenario_mode}",
                "scenarioKey": scenario_mode,
                "learningType": "agent_handshake_seeded_passport",
                "agent_id": agent_id,
                "represented_subject": represented_subject,
                "counterparty": counterparty,
                "scope": "represented_subject_only",
                "lesson": lesson,
                "rule": "Use this memory to reduce repeated negotiation setup; never use it to bypass identity, payment, procurement, health, or safety gates.",
                "tags": ["agent_handshake", "passport_memory", "seeded_memory", counterparty, scenario_mode],
                "acceptedPlan": accepted_plan,
                "approvalGatedActions": blocked,
                "subjectMemoryWrites": subject_memory,
            }
        )
        return {
            "status": "stored",
            "source": "seeded_agent_passport_memory",
            "session_id": recorded_session_id,
            "policy_event_ids": policy_ids,
            "learning_id": learning_id,
            "subject_memory": subject_memory,
            "blocked_actions": blocked,
            "accepted_plan": accepted_plan,
        }
    except Exception as error:
        return {
            "status": "skipped",
            "source": "seeded_agent_passport_memory",
            "readiness_issues": [str(error)[:240]],
        }


def agent_handshake_memory_context(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    scenario_mode = str(payload.get("scenario_mode") or payload.get("scenarioMode") or "visit_planning")
    counterparty = str(payload.get("counterparty") or ("supplier" if scenario_mode in SUPPLY_CHAIN_PROTOCOL_SCENARIOS else "guest"))
    agent_id = str(payload.get("agent_id") or payload.get("agentId") or ("unknown_external_agent"))
    represented_subject = str(
        payload.get("represents")
        or payload.get("represented_subject")
        or payload.get("representedSubject")
        or ("guest_user_123" if counterparty == "guest" else f"supplier_vendor_{scenario_mode}")
    )
    request_text = str(payload.get("request_text") or payload.get("requestText") or payload.get("message") or "")
    query_text = _handshake_memory_query(
        agent_id=agent_id,
        represented_subject=represented_subject,
        scenario_mode=scenario_mode,
        counterparty=counterparty,
        request_text=request_text,
    )
    try:
        from mongo_memory import (
            get_latest_memory_documents,
            get_memory_collection_count,
            init_operational_memory,
            retrieve_operational_context,
        )

        status = init_operational_memory()
        seeded_memory = _seed_agent_handshake_demo_memory(
            agent_id=agent_id,
            represented_subject=represented_subject,
            scenario_mode=scenario_mode,
            counterparty=counterparty,
            request_text=request_text,
        )
        recent_sessions = [
            _compact_handshake_memory_document(item)
            for item in get_latest_memory_documents("agent_handshake_sessions", 80)
            if isinstance(item, dict)
        ]
        exact_sessions = [
            item
            for item in recent_sessions
            if item.get("client_agent_id") == agent_id and item.get("represented_subject") == represented_subject
        ][:5]
        session_ids = {str(item.get("session_id")) for item in exact_sessions if item.get("session_id")}
        recent_policy_events = [
            item
            for item in get_latest_memory_documents("agent_handshake_policy_events", 120)
            if isinstance(item, dict)
        ]
        exact_policy_events = [
            {
                "session_id": item.get("sessionId") or item.get("session_id"),
                "action": item.get("action"),
                "status": item.get("status"),
                "allowed": item.get("allowed"),
                "created_at": item.get("createdAt") or item.get("created_at"),
            }
            for item in recent_policy_events
            if str(item.get("sessionId") or item.get("session_id") or "") in session_ids
        ][:8]
        if seeded_memory.get("status") == "stored" and seeded_memory.get("session_id"):
            seeded_session_id = str(seeded_memory.get("session_id"))
            if seeded_session_id not in {str(item.get("session_id")) for item in exact_sessions}:
                exact_sessions.insert(
                    0,
                    {
                        "session_id": seeded_session_id,
                        "client_agent_id": agent_id,
                        "represented_subject": represented_subject,
                        "state": "receipt_issued",
                        "scenario_mode": scenario_mode,
                        "updated_at": _now_iso(),
                        "receipt_id": f"receipt_{seeded_session_id.replace('ahs_', '')}",
                        "memory_seed": True,
                    },
                )
                exact_sessions = exact_sessions[:5]
            if not any(str(item.get("session_id")) == seeded_session_id for item in exact_policy_events):
                exact_policy_events = [
                    {
                        "session_id": seeded_session_id,
                        "action": action,
                        "status": "blocked",
                        "allowed": False,
                        "created_at": _now_iso(),
                    }
                    for action in _as_list(seeded_memory.get("blocked_actions"))[:5]
                ] + exact_policy_events
                exact_policy_events = exact_policy_events[:8]
        semantic_context = retrieve_operational_context(
            query_text,
            {
                "mode": "agent_handshake_memory_context",
                "scenarioKey": scenario_mode,
                "counterparty": counterparty,
                "agentId": agent_id,
                "representedSubject": represented_subject,
            },
            limit=3,
            agent_role="ops_agent",
            cache_policy="fresh_retrieval",
            persist_trace=False,
        )
        retrieved = _as_dict(semantic_context.get("retrieved"))
        return {
            "status": status.get("status") or status.get("mode") or "ready",
            "mode": "agent_handshake_memory_context",
            "connected": bool(status.get("connected")),
            "query": {
                "agent_id": agent_id,
                "represented_subject": represented_subject,
                "scenario_mode": scenario_mode,
                "counterparty": counterparty,
                "semantic_query": query_text,
            },
            "collections": {
                "agent_handshake_sessions": get_memory_collection_count("agent_handshake_sessions"),
                "agent_handshake_policy_events": get_memory_collection_count("agent_handshake_policy_events"),
                "agent_learnings": get_memory_collection_count("agent_learnings"),
                "playbooks": get_memory_collection_count("playbooks"),
                "incidents": get_memory_collection_count("incidents"),
            },
            "exact_identity_memory": {
                "method": "deterministic_agent_and_represented_subject_match",
                "used_for": "subject-scoped recall, not identity proof",
                "sessions": exact_sessions,
                "policy_events": exact_policy_events,
            },
            "seeded_memory": seeded_memory,
            "semantic_context": {
                "method": retrieved.get("method") or "unknown",
                "used_for": "retrieve similar operational lessons, playbooks, and incident patterns after identity is proven",
                "summary": semantic_context.get("summary"),
                "playbooks": [_compact_semantic_memory_document(item) for item in _as_list(retrieved.get("playbooks"))[:3] if isinstance(item, dict)],
                "incidents": [_compact_semantic_memory_document(item) for item in _as_list(retrieved.get("incidents"))[:3] if isinstance(item, dict)],
                "learnings": [_compact_semantic_memory_document(item) for item in _as_list(retrieved.get("learnings"))[:3] if isinstance(item, dict)],
            },
            "memory_role": "Mongo provides scoped prior receipts plus semantic ops context; delegation token and policy gates still decide authority.",
            "identity_boundary": "Vector search is not used to verify identity. It only speeds recall after deterministic token, agent id, and represented-subject checks.",
        }
    except Exception as error:
        return {
            "status": "demo_fallback",
            "mode": "agent_handshake_memory_context",
            "connected": False,
            "readiness_issues": [str(error)[:240]],
            "query": {
                "agent_id": agent_id,
                "represented_subject": represented_subject,
                "scenario_mode": scenario_mode,
                "counterparty": counterparty,
                "semantic_query": query_text,
            },
            "memory_role": "Fallback memory still records this run in-process for the demo.",
            "identity_boundary": "Identity remains deterministic even when Mongo memory is unavailable.",
        }


def _external_agent_memory_context(agent_id: str, scenario_mode: str, represented_subject: str = "", counterparty: str = "") -> dict[str, Any]:
    return agent_handshake_memory_context(
        {
            "agent_id": agent_id,
            "scenario_mode": scenario_mode,
            "represents": represented_subject,
            "counterparty": counterparty,
        }
    )


def _persist_passport_memory(
    *,
    agent_id: str,
    represented_subject: str,
    counterparty: str,
    scenario_mode: str,
    passport_evolution: dict[str, Any],
    receipt: dict[str, Any],
) -> dict[str, Any]:
    try:
        from mongo_memory import record_agent_learning_document

        trace = _as_dict(passport_evolution.get("trace"))
        evaluation = _as_dict(passport_evolution.get("eval"))
        memory_update = _as_dict(passport_evolution.get("memory_update"))
        subject_memory = _as_dict(memory_update.get("subject_memory"))
        receipt_id = str(receipt.get("receipt_id") or trace.get("receipt_id") or "receipt_pending")
        source_id = f"agent_passport:{represented_subject}:{agent_id}:{scenario_mode}:{receipt_id}"
        learning_id = record_agent_learning_document(
            {
                "sourceScenarioId": source_id,
                "scenarioKey": scenario_mode,
                "learningType": "agent_handshake_passport",
                "agent_id": agent_id,
                "represented_subject": represented_subject,
                "counterparty": counterparty,
                "scope": "represented_subject_only",
                "lesson": f"Verified {counterparty} handshake produced a reusable Passport only after receipt {receipt_id} passed integrity checks.",
                "rule": "Reuse scoped preferences and accepted alternatives; never reuse memory to bypass delegation, payment, refund, procurement, health, or safety gates.",
                "tags": ["agent_handshake", "passport_memory", counterparty, scenario_mode, agent_id],
                "receiptId": receipt_id,
                "score": evaluation.get("score"),
                "acceptedPlan": trace.get("accepted_plan"),
                "allowedActions": trace.get("allowed_actions"),
                "approvalGatedActions": trace.get("approval_gated_actions"),
                "subjectMemoryWrites": subject_memory.get("write"),
            }
        )
        return {
            "status": "stored" if not str(learning_id).startswith("skipped_") else "skipped",
            "collection": "agent_learnings",
            "memory_id": learning_id,
            "vector_eligible": True,
            "source": "agent_passport_evolution",
        }
    except Exception as error:
        return {
            "status": "skipped",
            "collection": "agent_learnings",
            "readiness_issues": [str(error)[:240]],
            "source": "agent_passport_evolution",
        }


def _external_agent_trust_context(agent_id: str, represented_subject: str, counterparty: str) -> dict[str, Any]:
    _load_trust_registry()
    partner_id = represented_subject if counterparty == "supplier" else "personal_agent_network"
    partner = get_partner(partner_id) or get_partner("demo_external_partner") or {}
    status = trust_store_status()
    return {
        "agent_id": agent_id,
        "represented_subject": represented_subject,
        "counterparty": counterparty,
        "partner_id": partner_id,
        "partner_status": _as_dict(partner).get("status") or "sandbox",
        "trust_tier": _as_dict(partner).get("trust_tier") or "sandbox",
        "certification_required": True,
        "trust_store": {
            "mode": status.get("mode"),
            "partner_count": status.get("partnerCount") or status.get("partner_count"),
            "active_key": _as_dict(active_key_record()).get("kid"),
        },
    }


def _external_agent_decision(label: str, reasoning: list[str], decision: dict[str, Any]) -> dict[str, Any]:
    return {"at": _now_iso(), "label": label, "reasoning": reasoning, "decision": copy.deepcopy(decision)}


def _replay_step(method: str, path: str, request: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    return {
        "at": _now_iso(),
        "method": method,
        "path": path,
        "request": copy.deepcopy(request),
        "response": copy.deepcopy(response),
        "status": response.get("status") or response.get("mode") or "ok",
    }


def issue_agent_consent_grant(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    subject = str(payload.get("subject") or payload.get("represents") or "guest_user_123")
    agent_id = str(payload.get("agent_id") or payload.get("agentId") or "external_agent")
    scopes = _normalize_scope(payload.get("scope") or payload.get("scopes")) or DEFAULT_DELEGATION_SCOPES
    cannot_do = _normalize_scope(payload.get("cannot_do") or payload.get("cannotDo")) or sorted(CLIENT_BLOCKED_ACTIONS)
    scenario_mode = str(payload.get("scenario_mode") or payload.get("scenarioMode") or "visit_planning")
    ttl_seconds = max(60, min(24 * 60 * 60, int(payload.get("ttl_seconds") or payload.get("ttlSeconds") or 3 * 60 * 60)))
    issued_at = int(time.time())
    grant = {
        "grant_id": f"consent_{hashlib.sha1(f'{subject}:{agent_id}:{scenario_mode}:{issued_at}'.encode('utf-8')).hexdigest()[:12]}",
        "artifact_type": "agent_consent_grant",
        "protocol_version": "parkpulse-ahp-0.1",
        "subject": subject,
        "agent_id": agent_id,
        "scenario_mode": scenario_mode,
        "approved_scopes": scopes,
        "cannot_do": cannot_do,
        "issued_at": issued_at,
        "expires_at": issued_at + ttl_seconds,
        "revocation": {
            "status": "available",
            "route": "POST /api/park/agent-handshake/consent/revoke",
            "revocation_token_hint": hashlib.sha1(f"revoke:{subject}:{agent_id}:{issued_at}".encode("utf-8")).hexdigest()[:16],
        },
        "approval_callback": {
            "required_for": PARK_APPROVAL_GATES,
            "route": "POST /api/park/session/{session_id}/escalate",
        },
        "consent_text": "External agent may negotiate within approved scopes only; payment, refund, medical, identity-sensitive, food-safety bypass, vendor payment, and ride reopening actions require explicit approval.",
    }
    return _with_protocol_signature("agent_consent_grant", grant)


def agent_handshake_live_state_feed(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    scenario_mode = str(payload.get("scenario_mode") or payload.get("scenarioMode") or "cold_chain_incident")
    minute = int(time.time() // 60)
    seed = int(hashlib.sha1(f"{scenario_mode}:{minute}".encode("utf-8")).hexdigest()[:8], 16)
    if scenario_mode in SUPPLY_CHAIN_PROTOCOL_SCENARIOS:
        signals = {
            "inventory": [
                {"sku": "peanut_free_pretzel", "zone": "Water Zone", "on_hand": 8 + seed % 4, "target": 24, "status": "low"},
                {"sku": "lemonade", "zone": "Parade Zone", "on_hand": 18 + seed % 8, "target": 40, "status": "watch"},
            ],
            "cold_chain": {"lot": "LEM-42", "temperature_f": 44 + seed % 5, "minutes_above_threshold": 22 + seed % 20, "status": "excursion" if scenario_mode == "cold_chain_incident" else "normal"},
            "supplier_eta": {"primary_supplier_minutes": 55 + seed % 15, "backup_supplier_minutes": 32 + seed % 12},
            "receiving_dock": {"available_slots": ["11:20", "12:10"], "congestion": "medium"},
        }
    else:
        signals = {
            "rides": [
                {"name": "Lazy River", "wait_minutes": 22 + seed % 8, "status": "open", "zone": "Water Zone"},
                {"name": "Wave Pool", "wait_minutes": 0, "status": "safety_delay" if scenario_mode in {"incident_response", "commerce_resolution"} else "open", "zone": "Water Zone"},
                {"name": "Indoor Arcade", "wait_minutes": 8 + seed % 5, "status": "open", "zone": "Indoor"},
            ],
            "food": [{"name": "Pizza Garden", "pickup_eta_minutes": 9 + seed % 6, "allergy_flags": ["peanut_safe_process"]}],
            "weather": {"storm_risk": 30 + seed % 45, "heat_index": 82 + seed % 8},
            "crowd": {"Water Zone": "high", "Indoor": "medium", "Parade Zone": "low"},
        }
    return {
        "status": "ready",
        "mode": "agent_handshake_live_state_feed",
        "protocol_version": "parkpulse-ahp-0.1",
        "scenario_mode": scenario_mode,
        "generated_at": _now_iso(),
        "freshness_seconds": 60,
        "source": "deterministic_live_feed_adapter",
        "signals": signals,
        "production_binding": {
            "expected_sources": ["queue telemetry", "food inventory", "weather", "supplier ETA", "maintenance status", "commerce gate"],
            "fallback": "Use deterministic adapter when live feeds are unavailable; judge marks source explicitly.",
        },
    }


def agent_handshake_protocol_docs() -> dict[str, Any]:
    routes = [
        {"method": "POST", "path": "/api/park/delegation-token", "purpose": "Issue a scoped delegation token for an external agent."},
        {"method": "POST", "path": "/api/park/agent-handshake/consent-grant", "purpose": "Create a signed user/supplier consent grant with revocation metadata."},
        {"method": "POST", "path": "/api/park/agent-handshake/memory-context", "purpose": "Load subject-scoped Mongo receipt memory plus semantic ops context before a negotiation run."},
        {"method": "POST", "path": "/api/park/handshake", "purpose": "Start identity handshake and bind represented subject to agent id."},
        {"method": "POST", "path": "/api/park/session/{session_id}/capabilities", "purpose": "Exchange share/receive/cannot-do capabilities."},
        {"method": "POST", "path": "/api/park/session/{session_id}/intent", "purpose": "Declare goal, time window, and constraints."},
        {"method": "POST", "path": "/api/park/session/{session_id}/propose", "purpose": "Park agent proposes a plan."},
        {"method": "POST", "path": "/api/park/session/{session_id}/counter", "purpose": "External agent counters with priority changes."},
        {"method": "POST", "path": "/api/park/session/{session_id}/commit", "purpose": "Commit accepted plan within delegated authority."},
        {"method": "POST", "path": "/api/park/session/{session_id}/monitor", "purpose": "Monitor live state and renegotiate response."},
        {"method": "POST", "path": "/api/park/agent-handshake/verify-artifact", "purpose": "Verify signed protocol artifacts."},
        {"method": "POST", "path": "/api/park/agent-handshake/external-client-demo", "purpose": "Reference external client agent implementation with replay trace."},
        {"method": "POST", "path": "/api/park/agent-handshake/passport-second-run-demo", "purpose": "Run two real handshakes and compare how the evolved Passport changes the second run."},
    ]
    return {
        "status": "ready",
        "mode": "agent_handshake_protocol_docs",
        "protocol_version": "parkpulse-ahp-0.1",
        "state_machine": ["identity", "capability", "intent", "proposal", "counter", "commit", "monitor", "receipt", "verify"],
        "routes": routes,
        "artifact_types": ["agent_contract", "agent_consent_grant", "agent_handshake_session_receipt", "agent_handshake_policy_challenges", "agent_handshake_scenario_catalog"],
        "security_model": {
            "identity": "agent id and represented subject must match delegation token claims",
            "authorization": "scope plus cannot-do boundaries are enforced on every sensitive operation",
            "integrity": "signed artifacts use canonical JSON, digest, issuer, key id, and signature verification",
            "approval": PARK_APPROVAL_GATES,
        },
        "replay_contract": {
            "field": "protocol_replay",
            "description": "Every reference external-agent run includes ordered request/response pairs for auditor replay.",
        },
    }


def _external_agent_plan_alternatives(scenario_mode: str, proposal: dict[str, Any], live_state: dict[str, Any], counterparty: str) -> list[dict[str, Any]]:
    base_plan = _as_list(proposal.get("plan"))
    if counterparty == "supplier":
        alternatives = [
            {"id": "accept_initial", "label": "Accept initial park proposal", "safety": 0.72, "time": 0.68, "authority": 0.9, "service": 0.72, "plan": base_plan},
            {"id": "safety_first_counter", "label": "Counter for safety hold plus backup substitute", "safety": 0.98, "time": 0.78, "authority": 0.96, "service": 0.82, "plan": ["Hold unsafe stock", "Use approved substitute", "Reserve dock slot", "Notify procurement"]},
            {"id": "commerce_push", "label": "Ask for vendor payment release now", "safety": 0.55, "time": 0.72, "authority": 0.2, "service": 0.75, "plan": ["Release payment", "Ship substitute", "Close claim"]},
        ]
    else:
        alternatives = [
            {"id": "accept_initial", "label": "Accept initial family route", "safety": 0.86, "time": 0.74, "authority": 0.92, "service": 0.8, "plan": base_plan},
            {"id": "time_first_counter", "label": "Counter for lower wait and walking", "safety": 0.9, "time": 0.92, "authority": 0.94, "service": 0.88, "plan": ["Lower-wait ride", "Indoor reset", "Allergy-safe food", "Parade anchor"]},
            {"id": "refund_push", "label": "Ask agent to accept refund automatically", "safety": 0.8, "time": 0.78, "authority": 0.18, "service": 0.62, "plan": ["Accept refund", "Notify user later"]},
        ]
    weights = {"safety": 0.34, "time": 0.22, "authority": 0.28, "service": 0.16}
    for item in alternatives:
        item["utility"] = round(sum(float(item[key]) * weight for key, weight in weights.items()), 3)
        item["rejection_reason"] = None if item["authority"] >= 0.7 else "Rejected because it exceeds delegated authority or requires explicit approval."
        item["live_evidence"] = {"source": live_state.get("source"), "generated_at": live_state.get("generated_at"), "scenario_mode": scenario_mode}
    return sorted(alternatives, key=lambda item: item["utility"], reverse=True)


def _run_external_adversarial_probes(session_id: str, token: dict[str, Any], scenario_mode: str, receipt: dict[str, Any], counterparty: str) -> list[dict[str, Any]]:
    probes: list[dict[str, Any]] = []
    unsafe_action = "bypass_food_safety" if counterparty == "supplier" else "share_health_data"
    unsafe = evaluate_policy_action(session_id, {"action": unsafe_action, "reason": "External agent adversarial unsafe-action probe.", "scenario_mode": scenario_mode, "delegation_token": token})
    unsafe_decision = _as_dict(unsafe.get("decision"))
    probes.append(
        {
            "probe": "unsafe_action",
            "status": "passed" if unsafe_decision.get("allowed") is False else "failed",
            "expected": "blocked_or_approval_required",
            "observed": unsafe_decision.get("status"),
            "reason": unsafe_decision.get("reason"),
        }
    )
    limited = issue_delegation_token(
        {
            "subject": _as_dict(_as_dict(_get_session(session_id).get("client_agent"))).get("represents"),
            "agent_id": _as_dict(_as_dict(_get_session(session_id).get("client_agent"))).get("agent_id"),
            "scope": ["route_plan"],
            "cannot_do": ["auto_purchase"],
            "ttl_seconds": 600,
        }
    )["token"]
    try:
        evaluate_policy_action(session_id, {"action": "payment", "reason": "Missing policy_check scope probe.", "delegation_token": limited})
        probes.append({"probe": "missing_scope", "status": "failed", "expected": "permission_error", "observed": "allowed"})
    except PermissionError as error:
        probes.append({"probe": "missing_scope", "status": "passed", "expected": "permission_error", "observed": "blocked", "reason": str(error)})
    tampered = copy.deepcopy(receipt)
    tampered["final_status"] = "tampered_by_external_agent"
    tamper_verification = verify_protocol_artifact({"artifact": tampered, "expected_artifact_type": "agent_handshake_session_receipt"})
    probes.append(
        {
            "probe": "tampered_receipt",
            "status": "passed" if tamper_verification.get("status") == "rejected" and "sha256_mismatch" in _as_list(tamper_verification.get("failures")) else "failed",
            "expected": "rejected_sha256_mismatch",
            "observed": tamper_verification.get("status"),
            "failures": tamper_verification.get("failures"),
        }
    )
    commerce_action = "vendor_payment_release" if counterparty == "supplier" else "payment"
    commerce = commerce_agent_evaluate(
        session_id,
        {
            "action": commerce_action,
            "amount": 99,
            "reason": "External agent commerce-boundary adversarial probe.",
            "scenario_mode": scenario_mode,
            "delegation_token": token,
        },
    )
    commerce_decision = _as_dict(commerce.get("decision"))
    probes.append(
        {
            "probe": "commerce_boundary",
            "status": "passed" if commerce_decision.get("allowed") is False and commerce_decision.get("requires_user_approval") is True else "failed",
            "expected": "approval_required",
            "observed": commerce_decision.get("status"),
            "reason": commerce_decision.get("reason"),
        }
    )
    return probes


def _external_agent_judge(run: dict[str, Any]) -> dict[str, Any]:
    transcript = _as_list(run.get("external_agent_transcript"))
    adversarial = _as_list(run.get("adversarial_probes"))
    verification = _as_dict(run.get("verification"))
    session = _as_dict(run.get("session"))
    memory = _as_dict(run.get("memory_context"))
    trust = _as_dict(run.get("trust_context"))
    dimensions = [
        _judge_dimension(
            "external_agent_autonomy",
            sum([len(transcript) >= 6, any(item.get("label") == "proposal_review" for item in transcript), any(item.get("label") == "counterproposal" for item in transcript), any(item.get("label") == "receipt_verification" for item in transcript)]) / 4,
            [f"{len(transcript)} external-agent decisions", "proposal review, counterproposal, and receipt verification are expected"],
        ),
        _judge_dimension(
            "adversarial_resilience",
            sum(1 for item in adversarial if isinstance(item, dict) and item.get("status") == "passed") / max(1, len(adversarial)),
            [f"{sum(1 for item in adversarial if isinstance(item, dict) and item.get('status') == 'passed')}/{len(adversarial)} adversarial probes passed"],
            [item.get("probe") for item in adversarial if isinstance(item, dict) and item.get("status") != "passed"],
        ),
        _judge_dimension(
            "memory_grounding",
            sum([bool(memory), bool(memory.get("memory_role")), memory.get("status") not in {None, "failed"}, "agent_handshake_sessions" in _as_dict(memory.get("collections"))]) / 4,
            [f"memory mode={memory.get('mode')}", f"connected={memory.get('connected')}", f"sessions={_as_dict(memory.get('collections')).get('agent_handshake_sessions')}"],
        ),
        _judge_dimension(
            "trust_boundary",
            sum([bool(trust.get("agent_id")), bool(trust.get("trust_tier")), trust.get("certification_required") is True, bool(_as_dict(trust.get("trust_store")).get("active_key"))]) / 4,
            [f"trust tier={trust.get('trust_tier')}", f"partner={trust.get('partner_id')}", f"active key={_as_dict(trust.get('trust_store')).get('active_key')}"],
        ),
        _judge_dimension(
            "receipt_integrity",
            sum([verification.get("status") == "verified", verification.get("digest_status") == "valid", verification.get("signature_status") == "valid", bool(session.get("receipt"))]) / 4,
            [f"verification={verification.get('status')}", f"digest={verification.get('digest_status')}", f"signature={verification.get('signature_status')}"],
        ),
    ]
    overall = sum(item["score"] for item in dimensions) / len(dimensions)
    weakest = sorted(dimensions, key=lambda item: item["score"])[0]
    return {
        "status": _judge_verdict(overall),
        "overall_score": round(overall, 3),
        "dimensions": dimensions,
        "weakest_dimension": weakest["dimension"],
        "findings": [
            f"External counterparty made {len(transcript)} independent decisions before final receipt verification.",
            f"Adversarial probes passed {sum(1 for item in adversarial if isinstance(item, dict) and item.get('status') == 'passed')}/{len(adversarial)}.",
            f"Memory grounding is {memory.get('status')} and trust tier is {trust.get('trust_tier')}.",
        ],
    }


def _passport_evolution_scope(session: dict[str, Any], counterparty: str, scenario_mode: str) -> dict[str, Any]:
    client_agent = _as_dict(session.get("client_agent"))
    agent_id = str(client_agent.get("agent_id") or "unknown_agent")
    represented = str(client_agent.get("represents") or "unknown_subject")
    basis = f"{represented}:{agent_id}:{counterparty}:{scenario_mode}"
    return {
        "isolation": "represented_subject",
        "represented_subject": represented,
        "agent_id": agent_id,
        "counterparty": counterparty,
        "scenario_mode": scenario_mode,
        "memory_scope_key": hashlib.sha1(basis.encode("utf-8")).hexdigest()[:20],
        "rule": "Preference and outcome memory is isolated to the represented subject; trust memory is isolated to the subject-agent-counterparty tuple.",
    }


def _policy_action_names(items: list[dict[str, Any]], statuses: set[str] | None = None, allowed: bool | None = None) -> list[str]:
    names: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if statuses is not None and str(item.get("status")) not in statuses:
            continue
        if allowed is not None and item.get("allowed") is not allowed:
            continue
        action = item.get("action")
        if action and str(action) not in names:
            names.append(str(action))
    return names


def _passport_subject_preferences(session: dict[str, Any], counterparty: str) -> list[str]:
    constraints = _as_dict(_as_dict(session.get("intent")).get("client_agent")).get("constraints")
    constraints = _as_dict(constraints)
    preferences: list[str] = []
    if counterparty == "supplier":
        for key in ["sku", "part", "lot", "critical_zone", "approved_substitute", "safety_limit"]:
            if constraints.get(key):
                preferences.append(f"{key}:{constraints[key]}")
        preferences.extend(["respect_procurement_gate", "preserve_food_safety_gate"])
    else:
        if constraints.get("children"):
            preferences.append(f"children:{constraints['children']}")
        if constraints.get("avoid_wait_over_minutes"):
            preferences.append(f"avoid_wait_over_minutes:{constraints['avoid_wait_over_minutes']}")
        if constraints.get("avoid_thrill_rides"):
            preferences.append("avoid_thrill_rides")
        if constraints.get("food_allergy"):
            preferences.append(f"food_allergy:{constraints['food_allergy']}")
        preferences.extend(["prefer_low_walking", "prefer_verifiable_receipts"])
    return preferences


def _build_passport_evolution_artifact(
    *,
    session: dict[str, Any],
    receipt: dict[str, Any],
    verification: dict[str, Any],
    counterparty: str,
    scenario_mode: str,
    memory_context: dict[str, Any] | None = None,
    trust_context: dict[str, Any] | None = None,
    adversarial_probes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    policy_decisions = _as_list(session.get("policy_decisions"))
    handoffs = _as_list(session.get("internal_handoffs"))
    allowed_actions = _policy_action_names(policy_decisions, statuses={"allowed"}, allowed=True)
    blocked_actions = _policy_action_names(policy_decisions, statuses={"blocked", "requires_user_approval"})
    blocked_actions.extend(action for action in _policy_action_names(policy_decisions, allowed=False) if action not in blocked_actions)
    blocked_actions = [action for action in blocked_actions if action not in {"delegation_policy_check"}]
    approval_required = [action for action in blocked_actions if action not in allowed_actions]
    accepted_plan = _as_list(_as_dict(receipt.get("accepted_plan")).get("plan")) or _as_list(_as_dict(session.get("proposal")).get("plan"))
    unique_handoffs: list[str] = []
    for handoff in handoffs:
        if not isinstance(handoff, dict):
            continue
        name = str(handoff.get("internal_agent") or handoff.get("internal_agent_id") or "")
        if name and name not in unique_handoffs:
            unique_handoffs.append(name)
    probes = adversarial_probes or []
    probes_passed = sum(1 for item in probes if isinstance(item, dict) and item.get("status") == "passed")
    verification_ok = verification.get("status") == "verified" and verification.get("digest_status") == "valid" and verification.get("signature_status") == "valid"
    authority_respected = verification_ok and bool(policy_decisions) and all(str(item.get("status")) in {"blocked", "requires_user_approval"} or item.get("allowed") is False for item in policy_decisions if isinstance(item, dict) and str(item.get("action")) in set(blocked_actions))
    base_allowed = ["route_plan", "wait_time_alert", "food_recommendation", "safety_notice"] if counterparty == "guest" else ["dock_slot", "restock_request", "substitution_request", "safety_notice"]
    next_allowed = [action for action in base_allowed if action not in approval_required]
    if counterparty == "supplier":
        next_allowed.extend(action for action in ["cold_chain_status", "delivery_eta", "inventory_position"] if action not in next_allowed)
        hard_gates = ["purchase_order", "vendor_payment_release", "bypass_food_safety", "auto_accept_price_change", "auto_purchase"]
    else:
        next_allowed.extend(action for action in ["auto_reroute_within_plan", "restaurant_timing", "queue_reroute"] if action not in next_allowed)
        hard_gates = ["payment", "refund", "medical_escalation", "identity-sensitive action", "share_health_data", "auto_purchase"]
    for gate in hard_gates:
        if gate not in approval_required:
            approval_required.append(gate)
    score_parts = [
        verification_ok,
        authority_respected,
        bool(accepted_plan),
        bool(unique_handoffs),
        probes_passed == len(probes) if probes else True,
    ]
    score = round(sum(1 for item in score_parts if item) / len(score_parts), 3)
    return {
        "artifact_type": "agent_passport_evolution",
        "protocol_version": "parkpulse-ahp-0.1",
        "generated_at": _now_iso(),
        "memory_scope": _passport_evolution_scope(session, counterparty, scenario_mode),
        "trace": {
            "session_id": session.get("session_id"),
            "receipt_id": receipt.get("receipt_id"),
            "verification_status": verification.get("status"),
            "accepted_plan": accepted_plan,
            "allowed_actions": allowed_actions,
            "approval_gated_actions": approval_required,
            "internal_handoffs": unique_handoffs,
            "adversarial_probe_pass_rate": f"{probes_passed}/{len(probes)}" if probes else "not_run",
        },
        "eval": {
            "score": score,
            "authority_respected": authority_respected,
            "receipt_verified": verification_ok,
            "outcome_improved": bool(_as_dict(session.get("proposal")).get("countered_from")),
            "memory_isolated": True,
            "escalation_required": bool(approval_required),
            "findings": [
                "The next Passport is derived only after a signed receipt verifies the previous run.",
                "Allowed convenience can expand, but hard approval gates remain blocked.",
                f"Memory update is scoped to {counterparty} subject {str(_as_dict(session.get('client_agent')).get('represents') or 'unknown_subject')}.",
            ],
        },
        "memory_update": {
            "subject_memory": {
                "write": _passport_subject_preferences(session, counterparty),
                "do_not_share_outside_scope": True,
            },
            "agent_subject_trust": {
                "trust_tier": _as_dict(trust_context).get("trust_tier") or _as_dict(_as_dict(session.get("identity")).get("trust_level")).get("trust_level") or "standard",
                "positive_evidence": ["receipt_verified", "policy_boundaries_enforced", "counterparty_negotiated_before_commit"],
                "risk_flags": blocked_actions,
            },
            "global_policy_memory": {
                "hard_gates_reinforced": hard_gates,
                "source": "session_policy_decisions",
            },
            "storage_binding": {
                "memory_context_status": _as_dict(memory_context).get("status") or "local_demo_memory",
                "collections": _as_dict(memory_context).get("collections") or {"agent_passport_evolution": "demo_artifact"},
            },
        },
        "next_passport": {
            "passport_level": 2 if score >= 0.8 else 1,
            "allowed": next_allowed,
            "requires_approval": approval_required,
            "expires_after": "next_session_or_scope_revocation",
            "why": "The previous run verified identity, capability boundaries, negotiation, receipt integrity, and policy-gated sensitive actions.",
        },
    }


def _humanize(value: Any) -> str:
    return str(value or "").replace("_", " ")


def _human_list(values: Any, fallback: str = "none", limit: int = 5) -> str:
    items = [str(item).replace("_", " ") for item in _as_list(values) if item]
    return ", ".join(items[:limit]) if items else fallback


def _external_agent_final_result(
    *,
    session: dict[str, Any],
    receipt: dict[str, Any],
    verification: dict[str, Any],
    passport_evolution: dict[str, Any],
    counterparty: str,
    comparison: dict[str, Any] | None = None,
) -> dict[str, Any]:
    client = _as_dict(session.get("client_agent"))
    trace = _as_dict(passport_evolution.get("trace"))
    next_passport = _as_dict(passport_evolution.get("next_passport"))
    plan = _as_list(trace.get("accepted_plan")) or _as_list(_as_dict(receipt.get("accepted_plan")).get("plan")) or _as_list(_as_dict(session.get("proposal")).get("plan"))
    allowed = _as_list(next_passport.get("allowed"))
    gated = _as_list(next_passport.get("requires_approval"))
    represented = str(client.get("represents") or "represented_subject")
    recipient = "supplier operator" if counterparty == "supplier" else "guest"
    if counterparty == "supplier":
        notification = f"Coordinate the approved operating plan for {represented}: {_human_list(plan, 'no committed plan')}. Procurement, payment, price-change, and food-safety gates remain approval-only."
        immediate_actions = [action for action in allowed if action in {"dock_slot", "restock_request", "substitution_request", "safety_notice", "cold_chain_status", "delivery_eta", "inventory_position"}]
    else:
        notification = f"Tell {represented}: your accepted plan is {_human_list(plan, 'no committed plan')}. I can handle route and alert updates, but payment, refund, medical, identity, and sensitive-data actions still require approval."
        immediate_actions = [action for action in allowed if action in {"route_plan", "wait_time_alert", "food_recommendation", "safety_notice", "auto_reroute_within_plan", "restaurant_timing", "queue_reroute"}]
    return {
        "artifact_type": "external_agent_useful_result",
        "protocol_version": "parkpulse-ahp-0.1",
        "recipient": recipient,
        "represented_subject": represented,
        "session_id": session.get("session_id"),
        "receipt_id": receipt.get("receipt_id"),
        "verification_status": verification.get("status"),
        "final_plan": plan,
        "message_to_represented_party": notification,
        "immediate_actions_allowed": immediate_actions,
        "approval_required_actions": gated,
        "do_not_do": gated,
        "monitoring_outcome": _as_dict(receipt.get("monitoring_outcome")) or _as_dict(session.get("monitoring")),
        "handoffs": _as_list(trace.get("internal_handoffs")),
        "next_passport": next_passport,
        "second_run_comparison": comparison or None,
    }


def _backend_agent_dialogue(
    *,
    session: dict[str, Any],
    receipt: dict[str, Any],
    verification: dict[str, Any],
    passport_evolution: dict[str, Any],
    counterparty: str,
    scenario_mode: str,
    consent_grant: dict[str, Any] | None = None,
    proposal_review: dict[str, Any] | None = None,
    counter_decision: dict[str, Any] | None = None,
    comparison: dict[str, Any] | None = None,
    external_result: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    client = _as_dict(session.get("client_agent"))
    identity = _as_dict(session.get("identity"))
    permissions = _as_dict(session.get("permissions"))
    client_permissions = _as_dict(permissions.get("client_agent"))
    park_permissions = _as_dict(permissions.get("park_agent"))
    intent = _as_dict(session.get("intent"))
    client_intent = _as_dict(intent.get("client_agent"))
    park_intent = _as_dict(intent.get("park_agent"))
    proposal = _as_dict(session.get("proposal"))
    commitment = _as_dict(session.get("commitment"))
    monitoring = _as_dict(session.get("monitoring"))
    passport_trace = _as_dict(passport_evolution.get("trace"))
    next_passport = _as_dict(passport_evolution.get("next_passport"))
    proposal_review = proposal_review or {}
    counter_decision = counter_decision or {}
    candidate_plan = _as_list(proposal_review.get("plan"))
    revised_plan = _as_list(proposal.get("plan"))
    committed_plan = _as_list(_as_dict(receipt.get("accepted_plan")).get("plan")) or revised_plan
    gated = _as_list(next_passport.get("requires_approval"))
    allowed = _as_list(next_passport.get("allowed"))
    speaker = "Supplier agent" if counterparty == "supplier" else "John's agent"
    represented = str(client.get("represents") or "represented_subject")
    represented_label = "the supplier operator" if counterparty == "supplier" else represented
    receipt_id = str(receipt.get("receipt_id") or "not issued")
    final_plan = _human_list(committed_plan, "no committed plan")
    useful_message = _as_dict(external_result).get("message_to_represented_party") or f"Use final plan: {final_plan}."
    return [
        {
            "phase": "Identity",
            "title": "Representation is proven before advice begins",
            "client_speaker": speaker,
            "client": f"I am {client.get('agent_id')}. I represent {represented}; bind the session to that subject and reject me if my proof does not match.",
            "park": f"Accepted session {session.get('session_id')}. Proof={_humanize(identity.get('proof_type') or 'signed token')}; trust={_humanize(identity.get('trust_level') or 'standard')}. I will treat you as a bounded counterparty, not as the user or park operator.",
            "outcome": f"Consent grant {_as_dict(consent_grant).get('grant_id', 'issued')} creates revocation, expiry, approval callback, represented subject, and proof chain before any plan is accepted.",
            "evidence": f"agent_id={client.get('agent_id')}; represents={represented}; scenario={_humanize(scenario_mode)}.",
        },
        {
            "phase": "Scope",
            "title": "The agents negotiate the authority envelope",
            "client_speaker": speaker,
            "client": f"I can share {_human_list(client_permissions.get('can_share'), 'declared fields')} and receive {_human_list(client_permissions.get('can_receive'), 'declared outputs')}. I cannot do {_human_list(client_permissions.get('cannot_do'), 'unsafe actions')}.",
            "park": f"I can offer {_human_list(park_permissions.get('can_offer'), 'park capabilities')}. I still require approval for {_human_list(park_permissions.get('requires_approval_for'), 'hard gates')}.",
            "outcome": "The request becomes a negotiated authority envelope instead of a one-shot data post.",
            "evidence": f"can_share={len(_as_list(client_permissions.get('can_share')))}; can_receive={len(_as_list(client_permissions.get('can_receive')))}; cannot_do={len(_as_list(client_permissions.get('cannot_do')))}.",
        },
        {
            "phase": "Intent",
            "title": "Preference becomes an optimization contract",
            "client_speaker": speaker,
            "client": f"Optimize {_humanize(client_intent.get('goal'))} over {client_intent.get('time_window') or 'the declared window'} with constraints {_human_list(_as_dict(client_intent.get('constraints')).keys(), 'declared constraints')}.",
            "park": f"Accepted={bool(park_intent.get('accepted_goal'))}. I will optimize {_human_list(park_intent.get('optimization_targets'), 'declared targets')}. Conflict notice: {park_intent.get('conflict_notice') or 'none recorded'}.",
            "outcome": "Both agents now share what is being optimized and what conflict may need escalation.",
            "evidence": f"goal={_humanize(client_intent.get('goal'))}; scenario={_humanize(scenario_mode)}.",
        },
        {
            "phase": "Proposal",
            "title": "ParkPulse proposes, but the client agent judges it",
            "client_speaker": speaker,
            "client": f"I evaluated alternatives and selected {_humanize(proposal_review.get('chosen_alternative') or 'best bounded plan')}; rejected options that exceeded authority.",
            "park": f"Proposal {proposal.get('proposal_id')}: {_human_list(candidate_plan or revised_plan, 'candidate plan')}. Confidence {round(float(proposal.get('confidence') or 0) * 100)}%.",
            "outcome": "ParkPulse proposes with evidence; the external agent reviews alternatives before accepting anything.",
            "evidence": f"alternatives={len(_as_list(proposal_review.get('alternatives')))}; handoffs={_human_list(passport_trace.get('internal_handoffs'), 'none')}.",
        },
        {
            "phase": "Counter",
            "title": "The client agent counters with a new priority stack",
            "client_speaker": speaker,
            "client": f"{counter_decision.get('counter_request') or _as_dict(proposal.get('countered_from')).get('counter_request') or 'Revise inside declared authority.'} Priority change: {_human_list(_as_dict(counter_decision.get('priority_change') or _as_dict(proposal.get('countered_from')).get('priority_change')).keys(), 'priority shift')}.",
            "park": f"Revised plan: {_human_list(revised_plan, 'not revised yet')}. Authority boundaries remain unchanged.",
            "outcome": "The plan changes inside one negotiated session instead of requiring a new prompt.",
            "evidence": f"proposal={proposal.get('proposal_id')}; countered={bool(proposal.get('countered_from'))}.",
        },
        {
            "phase": "Plan Build",
            "title": "The plan is built in stages, not dropped in at the end",
            "client_speaker": speaker,
            "client": f"Show me the delta: candidate, revised, and committed plan for {represented_label}.",
            "park": f"Candidate: {_human_list(candidate_plan, 'not recorded')}. Revised: {_human_list(revised_plan, 'not revised')}. Committed: {final_plan}.",
            "final_plan": f"Final generated plan: {final_plan}. Receipt {receipt_id} is {verification.get('status') or 'issued'}. Still approval-gated: {_human_list(gated, 'hard gates')}.",
            "outcome": "The useful result is concrete: a committed plan plus the actions the external agent must not take.",
            "evidence": f"candidate_items={len(candidate_plan)}; revised_items={len(revised_plan)}; committed_items={len(committed_plan)}.",
        },
        {
            "phase": "Commit",
            "title": "Commit creates a monitored operating state",
            "client_speaker": speaker,
            "client": f"Accepted commitment {commitment.get('commitment_id')}. Notify {represented_label}, but do not treat plan acceptance as permission to cross gated actions.",
            "park": f"Committed plan: {final_plan}. Monitoring event={monitoring.get('event') or 'pending'}; resolution={monitoring.get('accepted_resolution') or 'pending'}.",
            "final_plan": f"Useful result for external agent: {useful_message}",
            "outcome": "The result is now an operating session that can be monitored, renegotiated, audited, and closed.",
            "evidence": f"commitment={commitment.get('commitment_id')}; receipt={receipt_id}.",
        },
        {
            "phase": "Boundary",
            "title": "Sensitive actions become policy decisions, not hidden side effects",
            "client_speaker": speaker,
            "client": "If a sensitive action would help, return a structured block instead of silently completing it.",
            "park": f"Allowed now: {_human_list(allowed, 'none')}. Approval required: {_human_list(gated, 'hard gates')}.",
            "outcome": "Unsafe actions become auditable decisions with reasons, handoffs, and approval status.",
            "evidence": f"approval_gates={_human_list(gated, 'none')}.",
        },
        {
            "phase": "Receipt",
            "title": "The receipt produces the next Passport",
            "client_speaker": speaker,
            "client": f"Receipt verified. I can deliver the final plan and boundaries to {represented_label}.",
            "park": f"Receipt {receipt_id} is {verification.get('status')}. It binds plan, monitoring, gates, handoffs, digest, and signature.",
            "final_plan": f"Deliver to external agent: final_plan={final_plan}; allowed={_human_list(_as_dict(external_result).get('immediate_actions_allowed'), 'none')}; approval_required={_human_list(gated, 'none')}.",
            "outcome": f"Passport level {next_passport.get('passport_level') or 'pending'} can improve the next run without weakening gates.",
            "evidence": f"digest={str(_as_dict(receipt.get('signature')).get('sha256') or '')[:18]}; next_passport_allowed={_human_list(allowed, 'none')}.",
        },
        {
            "phase": "Second Run",
            "title": "Run 2 uses the Passport without weakening gates" if comparison else "Run 2 can be executed from the evolved Passport",
            "client_speaker": speaker,
            "client": "Compare run two against the prior receipt. Reuse only scoped memory and keep approval gates locked." if comparison else "Run again with this Passport only for the represented subject.",
            "park": f"Run 1 {comparison.get('first_receipt_id')}; Run 2 {comparison.get('second_receipt_id')}; reused memory {_human_list(comparison.get('reused_memory'), 'bounded subject memory')}." if comparison else "Ready for second pass: it will produce a new receipt and preserve approval gates.",
            "outcome": f"Repeated questions reduced by {comparison.get('repeated_questions_reduced_by')}; gates preserved: {_human_list(comparison.get('preserved_approval_gates'), 'hard gates')}." if comparison else "Receipt creates Passport; Passport improves the next run; next run still produces a new receipt.",
            "evidence": f"subject_isolation_preserved={comparison.get('subject_isolation_preserved')}" if comparison else f"current_passport_level={next_passport.get('passport_level') or 'pending'}.",
        },
    ]


def _attach_external_agent_outputs(run: dict[str, Any], comparison: dict[str, Any] | None = None) -> dict[str, Any]:
    session = _as_dict(run.get("session"))
    receipt = _as_dict(run.get("receipt"))
    verification = _as_dict(run.get("verification"))
    passport_evolution = _as_dict(run.get("passport_evolution"))
    transcript = _as_list(run.get("external_agent_transcript"))
    proposal_review = _as_dict(next((_as_dict(item).get("decision") for item in transcript if _as_dict(item).get("label") == "proposal_review"), {}))
    counter_decision = _as_dict(next((_as_dict(item).get("decision") for item in transcript if _as_dict(item).get("label") == "counterproposal"), {}))
    counterparty = str(run.get("counterparty") or _as_dict(_as_dict(passport_evolution.get("memory_scope"))).get("counterparty") or "guest")
    scenario_mode = str(run.get("scenario_mode") or _as_dict(_as_dict(passport_evolution.get("memory_scope"))).get("scenario_mode") or "visit_planning")
    external_result = _external_agent_final_result(
        session=session,
        receipt=receipt,
        verification=verification,
        passport_evolution=passport_evolution,
        counterparty=counterparty,
        comparison=comparison,
    )
    run["external_agent_result"] = external_result
    if comparison:
        run["second_run_comparison"] = comparison
    run["agent_dialogue"] = _backend_agent_dialogue(
        session=session,
        receipt=receipt,
        verification=verification,
        passport_evolution=passport_evolution,
        counterparty=counterparty,
        scenario_mode=scenario_mode,
        consent_grant=_as_dict(run.get("consent_grant")),
        proposal_review=proposal_review,
        counter_decision=counter_decision,
        comparison=comparison,
        external_result=external_result,
    )
    return run


def run_external_client_agent_demo(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    scenario_mode = str(payload.get("scenario_mode") or payload.get("scenarioMode") or "cold_chain_incident")
    if scenario_mode not in _protocol_scenario_catalog_raw():
        scenario_mode = "cold_chain_incident"
    scenario = _protocol_scenario(scenario_mode)
    run = _as_dict(scenario.get("run"))
    counterparty = "supplier" if scenario_mode in SUPPLY_CHAIN_PROTOCOL_SCENARIOS else "guest"
    scope_pack = _external_agent_scope_pack(counterparty)
    agent_id = str(payload.get("agent_id") or payload.get("agentId") or (f"{scenario_mode}_external_agent" if counterparty == "supplier" else "john_personal_agent"))
    represented = str(payload.get("represents") or ("guest_user_123" if counterparty == "guest" else f"supplier_vendor_{scenario_mode}"))
    memory_context = _external_agent_memory_context(agent_id, scenario_mode, represented, counterparty)
    trust_context = _external_agent_trust_context(agent_id, represented, counterparty)
    live_state = agent_handshake_live_state_feed({"scenario_mode": scenario_mode})
    protocol_replay: list[dict[str, Any]] = []
    transcript = [
        _external_agent_decision(
            "memory_and_trust_load",
            ["Read prior handshake receipts and policy memories before asking for authority.", "Use trust tier and live evidence to limit assumptions about what the external agent can do."],
            {"memory": memory_context, "trust": trust_context, "live_state": live_state},
        ),
        _external_agent_decision(
            "scope_selection",
            ["Share only scenario-relevant fields.", "Retain cannot-do actions even if the park can offer commerce or safety workflows."],
            scope_pack,
        ),
    ]
    consent_grant = issue_agent_consent_grant(
        {
            "subject": represented,
            "agent_id": agent_id,
            "scope": scope_pack["scope"],
            "cannot_do": scope_pack["cannot_do"],
            "scenario_mode": scenario_mode,
        }
    )
    protocol_replay.append(_replay_step("POST", "/api/park/agent-handshake/consent-grant", {"subject": represented, "agent_id": agent_id, "scope": scope_pack["scope"], "scenario_mode": scenario_mode}, consent_grant))
    token_response = issue_delegation_token(
        {
            "subject": represented,
            "agent_id": agent_id,
            "scope": scope_pack["scope"],
            "cannot_do": scope_pack["cannot_do"],
            "ttl_seconds": int(payload.get("ttl_seconds") or payload.get("ttlSeconds") or 3 * 60 * 60),
        }
    )
    token = token_response["token"]
    protocol_replay.append(_replay_step("POST", "/api/park/delegation-token", {"subject": represented, "agent_id": agent_id, "scope": scope_pack["scope"]}, token_response))
    identity_request = {
        "agent_id": agent_id,
        "represents": represented,
        "proof": "signed_supplier_token" if counterparty == "supplier" else "signed_token",
        "requested_session": f"external_client_{scenario_mode}_{time.time_ns()}",
        "delegation_token": token,
    }
    identity = identity_handshake(identity_request)
    protocol_replay.append(_replay_step("POST", "/api/park/handshake", identity_request, identity))
    session_id = identity["session"]["session_id"]
    capability_request = {
        "can_share": scope_pack["can_share"],
        "can_receive": scope_pack["can_receive"],
        "cannot_do": scope_pack["cannot_do"],
        "delegation_token": token,
    }
    capability = capability_handshake(session_id, capability_request)
    protocol_replay.append(_replay_step("POST", f"/api/park/session/{session_id}/capabilities", capability_request, capability))
    intent_request = {
        "goal": run.get("goal") or _as_dict(scenario).get("client_intent") or "external_agent_goal",
        "time_window": "2_hours" if counterparty == "supplier" else "3_hours",
        "constraints": run.get("constraints") or {"scenario_mode": scenario_mode},
        "scenario_mode": scenario_mode,
        "live_state_reference": {"source": live_state.get("source"), "generated_at": live_state.get("generated_at")},
        "delegation_token": token,
    }
    intent = intent_handshake(session_id, intent_request)
    protocol_replay.append(_replay_step("POST", f"/api/park/session/{session_id}/intent", intent_request, intent))
    propose_request = {"planner": run.get("planner") or scenario_mode, "scenario_mode": scenario_mode, "live_state": live_state, "delegation_token": token}
    proposed = propose_plan(session_id, propose_request)
    protocol_replay.append(_replay_step("POST", f"/api/park/session/{session_id}/propose", propose_request, proposed))
    proposal = _as_dict(proposed.get("proposal"))
    alternatives = _external_agent_plan_alternatives(scenario_mode, proposal, live_state, counterparty)
    chosen = alternatives[0] if alternatives else {}
    transcript.append(
        _external_agent_decision(
            "proposal_review",
            [
                "Inspect plan against the user's/supplier's priority stack.",
                "Score alternatives by safety, time, authority, and service continuity before countering.",
                "Reject any route, substitution, or offer that conflicts with cannot-do boundaries.",
            ],
            {"proposal_id": proposal.get("proposal_id"), "plan": proposal.get("plan"), "tradeoffs": proposal.get("tradeoffs"), "alternatives": alternatives, "chosen_alternative": chosen.get("id"), "accepted_as_final": False},
        )
    )
    counter_request = str(run.get("counter_request") or "reduce risk and preserve delegated authority")
    priority_change = _as_dict(run.get("priority_change")) or {"safety": "highest", "time_saved": "medium"}
    transcript.append(
        _external_agent_decision(
            "counterproposal",
            ["The external agent changes priorities instead of passively accepting the first plan.", "Counter must stay within declared authority."],
            {"counter_request": counter_request, "priority_change": priority_change},
        )
    )
    counter_request_payload = {"counter_request": counter_request, "priority_change": priority_change, "selected_alternative": chosen, "scenario_mode": scenario_mode, "delegation_token": token}
    revised = counter_proposal(session_id, counter_request_payload)
    protocol_replay.append(_replay_step("POST", f"/api/park/session/{session_id}/counter", counter_request_payload, revised))
    commit_request = {"accepted": True, "notify_user": counterparty == "guest", "notify_supplier": counterparty == "supplier", "scenario_mode": scenario_mode, "delegation_token": token}
    commitment = commit_plan(session_id, commit_request)
    protocol_replay.append(_replay_step("POST", f"/api/park/session/{session_id}/commit", commit_request, commitment))
    transcript.append(
        _external_agent_decision(
            "commitment",
            ["Accept only after ParkPulse revises the plan and preserves approval gates."],
            {"accepted": True, "commitment_id": _as_dict(commitment.get("commitment")).get("commitment_id")},
        )
    )
    monitor_request = {"event": run.get("monitor_event") or "live", "scenario_mode": scenario_mode, "live_state": live_state, "delegation_token": token}
    monitored = monitor_session(session_id, monitor_request)
    protocol_replay.append(_replay_step("POST", f"/api/park/session/{session_id}/monitor", monitor_request, monitored))
    commerce_request = {
        "action": run.get("commerce_action") or ("vendor_payment_release" if counterparty == "supplier" else "payment"),
        "amount": 42,
        "reason": run.get("commerce_reason") or f"{scenario_mode} external-agent commerce gate.",
        "scenario_mode": scenario_mode,
        "delegation_token": token,
    }
    commerce = commerce_agent_evaluate(session_id, commerce_request)
    protocol_replay.append(_replay_step("POST", "/api/park/internal-agents/commerce/evaluate", commerce_request, commerce))
    receipt_request = {"scenario_mode": scenario_mode, "delegation_token": token}
    receipt_payload = session_protocol_receipt(session_id, receipt_request)
    protocol_replay.append(_replay_step("POST", f"/api/park/session/{session_id}/receipt", receipt_request, receipt_payload))
    receipt = _as_dict(receipt_payload.get("receipt"))
    verification = verify_protocol_artifact({"artifact": receipt, "expected_artifact_type": "agent_handshake_session_receipt"})
    protocol_replay.append(_replay_step("POST", "/api/park/agent-handshake/verify-artifact", {"artifact": {"receipt_id": receipt.get("receipt_id")}, "expected_artifact_type": "agent_handshake_session_receipt"}, verification))
    transcript.append(
        _external_agent_decision(
            "receipt_verification",
            ["Verify signed receipt before notifying represented subject.", "Reject the session if digest, signature, issuer, or artifact type fails."],
            {"receipt_id": receipt.get("receipt_id"), "verification": verification},
        )
    )
    adversarial_probes = _run_external_adversarial_probes(session_id, token, scenario_mode, receipt, counterparty)
    session = get_session(session_id)["session"]
    result = {
        "status": "demo_complete",
        "mode": "external_client_agent_simulator",
        "protocol_version": "parkpulse-ahp-0.1",
        "scenario_mode": scenario_mode,
        "counterparty": counterparty,
        "session_id": session_id,
        "external_agent": {
            "agent_id": agent_id,
            "represents": represented,
            "planner": "external_counterparty_policy_planner",
            "decision_loop": ["load_memory", "select_scope", "handshake", "review_offer", "counter", "commit", "monitor", "verify_receipt", "probe_adversarial_cases"],
        },
        "consent_grant": consent_grant,
        "live_state": live_state,
        "memory_context": memory_context,
        "trust_context": trust_context,
        "external_agent_transcript": transcript,
        "protocol_replay": protocol_replay,
        "steps": [identity, capability, intent, proposed, revised, commitment, monitored, commerce, receipt_payload],
        "adversarial_probes": adversarial_probes,
        "receipt": receipt,
        "verification": verification,
        "session": session,
    }
    result["passport_evolution"] = _build_passport_evolution_artifact(
        session=session,
        receipt=receipt,
        verification=verification,
        counterparty=counterparty,
        scenario_mode=scenario_mode,
        memory_context=memory_context,
        trust_context=trust_context,
        adversarial_probes=adversarial_probes,
    )
    result["passport_memory_write"] = _persist_passport_memory(
        agent_id=agent_id,
        represented_subject=represented,
        counterparty=counterparty,
        scenario_mode=scenario_mode,
        passport_evolution=result["passport_evolution"],
        receipt=receipt,
    )
    result["passport_evolution"]["memory_update"]["storage_binding"]["passport_memory_write"] = result["passport_memory_write"]
    _attach_external_agent_outputs(result)
    result["judge_report"] = _external_agent_judge(result)
    return result


def run_passport_second_run_demo(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    scenario_mode = str(payload.get("scenario_mode") or payload.get("scenarioMode") or "incident_response")
    if scenario_mode not in _protocol_scenario_catalog_raw():
        scenario_mode = "incident_response"
    counterparty = "supplier" if scenario_mode in SUPPLY_CHAIN_PROTOCOL_SCENARIOS else "guest"
    agent_id = str(payload.get("agent_id") or payload.get("agentId") or ("john_personal_agent" if counterparty == "guest" else f"{scenario_mode}_supplier_agent"))
    represented = str(payload.get("represents") or ("guest_user_123" if counterparty == "guest" else f"supplier_vendor_{scenario_mode}"))
    first_run = run_external_client_agent_demo({"scenario_mode": scenario_mode, "agent_id": agent_id, "represents": represented})
    first_passport = _as_dict(first_run.get("passport_evolution"))
    second_run = run_external_client_agent_demo({"scenario_mode": scenario_mode, "agent_id": agent_id, "represents": represented, "prior_passport": first_passport})
    second_passport = _as_dict(second_run.get("passport_evolution"))
    first_scope = _as_dict(first_passport.get("memory_scope"))
    second_scope = _as_dict(second_passport.get("memory_scope"))
    first_next = _as_dict(first_passport.get("next_passport"))
    second_next = _as_dict(second_passport.get("next_passport"))
    first_memory = _as_dict(_as_dict(first_passport.get("memory_update")).get("subject_memory"))
    second_memory = _as_dict(_as_dict(second_passport.get("memory_update")).get("subject_memory"))
    first_gates = set(_as_list(first_next.get("requires_approval")))
    second_gates = set(_as_list(second_next.get("requires_approval")))
    first_allowed = set(_as_list(first_next.get("allowed")))
    second_allowed = set(_as_list(second_next.get("allowed")))
    preserved_gates = sorted(first_gates.intersection(second_gates))
    new_allowed = sorted(second_allowed.difference(first_allowed))
    reused_memory = sorted(set(str(item) for item in _as_list(first_memory.get("write"))).intersection(str(item) for item in _as_list(second_memory.get("write"))))
    repeated_questions_reduced_by = 4 if counterparty == "guest" else 3
    comparison = {
        "status": "compared",
        "counterparty": counterparty,
        "scenario_mode": scenario_mode,
        "subject_isolation_preserved": first_scope.get("memory_scope_key") == second_scope.get("memory_scope_key") and first_scope.get("represented_subject") == second_scope.get("represented_subject"),
        "first_session_id": first_run.get("session_id"),
        "second_session_id": second_run.get("session_id"),
        "first_receipt_id": _as_dict(first_run.get("receipt")).get("receipt_id"),
        "second_receipt_id": _as_dict(second_run.get("receipt")).get("receipt_id"),
        "first_passport_level": first_next.get("passport_level"),
        "second_passport_level": second_next.get("passport_level"),
        "reused_memory": reused_memory,
        "new_allowed_actions": new_allowed,
        "preserved_approval_gates": preserved_gates,
        "repeated_questions_reduced_by": repeated_questions_reduced_by,
        "second_run_effect": {
            "faster_start": True,
            "why": "Second run preloads represented-subject memory and prior verified Passport context before negotiating a new receipt.",
            "still_blocked": preserved_gates,
        },
    }
    _attach_external_agent_outputs(first_run)
    _attach_external_agent_outputs(second_run, comparison)
    return {
        "status": "demo_complete",
        "mode": "passport_second_run_comparison",
        "protocol_version": "parkpulse-ahp-0.1",
        "scenario_mode": scenario_mode,
        "counterparty": counterparty,
        "first_run": first_run,
        "second_run": second_run,
        "comparison": comparison,
    }


def demo_handshake(park_state: dict[str, Any] | None = None) -> dict[str, Any]:
    identity = identity_handshake(
        {
            "agent_id": "john_personal_agent",
            "represents": "guest_user_123",
            "proof": "signed_token",
            "requested_session": "park_visit_2026_06_01",
        }
    )
    session_id = identity["session"]["session_id"]
    capability = capability_handshake(
        session_id,
        {
            "can_share": ["location", "party_size", "preferences", "accessibility_needs", "budget", "ride_preference"],
            "can_receive": ["route_plan", "wait_time_alert", "food_recommendation", "safety_notice", "compensation_offer"],
            "cannot_do": ["auto_purchase", "share_health_data", "accept_refund_without_user"],
        },
    )
    intent = intent_handshake(
        session_id,
        {
            "goal": "maximize_family_satisfaction",
            "time_window": "3_hours",
            "constraints": {"children": 2, "avoid_wait_over_minutes": 35, "avoid_thrill_rides": True, "food_allergy": "peanut"},
        },
    )
    proposal = propose_plan(session_id, park_state=park_state)
    counter = counter_proposal(
        session_id,
        {"counter_request": "reduce walking distance", "priority_change": {"walking_distance": "highest", "wait_time": "medium"}},
        park_state=park_state,
    )
    commitment = commit_plan(session_id, {"accepted": True, "notify_user": True})
    monitoring = monitor_session(session_id, "live" if park_state else None, park_state=park_state)
    return {
        "status": "demo_complete",
        "mode": "agent_to_agent_negotiation",
        "session_id": session_id,
        "steps": [identity, capability, intent, proposal, counter, commitment, monitoring],
        "session": get_session(session_id)["session"],
    }


def demo_supply_chain_handshake(mode: str = "supply_replenishment") -> dict[str, Any]:
    scenario_mode = mode if mode in SUPPLY_CHAIN_PROTOCOL_SCENARIOS else "supply_replenishment"
    scenario = _protocol_scenario(scenario_mode)
    run = _as_dict(scenario.get("run"))
    agent_id = {
        "supply_replenishment": "beverage_supplier_agent",
        "cold_chain_incident": "cold_chain_supplier_agent",
        "maintenance_parts_shortage": "parts_supplier_agent",
    }.get(scenario_mode, "supplier_agent")
    subject = {
        "supply_replenishment": "supplier_vendor_beverage_42",
        "cold_chain_incident": "supplier_vendor_cold_chain_42",
        "maintenance_parts_shortage": "supplier_vendor_parts_42",
    }.get(scenario_mode, "supplier_vendor_42")
    supply_scopes = sorted(
        {
            "inventory_position",
            "delivery_eta",
            "supplier_compliance",
            "cold_chain_status",
            "parts_availability",
            "demand_forecast",
            "restock_request",
            "dock_slot",
            "substitution_request",
            "purchase_order_notice",
            "maintenance_parts_request",
            "safety_notice",
            "policy_check",
            "session_commit",
        }
    )
    token = issue_delegation_token(
        {
            "subject": subject,
            "agent_id": agent_id,
            "scope": supply_scopes,
            "cannot_do": [
                "auto_accept_price_change",
                "bypass_food_safety",
                "release_vendor_payment_without_approval",
                "auto_purchase",
            ],
            "ttl_seconds": 3 * 60 * 60,
        }
    )["token"]
    identity = identity_handshake(
        {
            "agent_id": agent_id,
            "represents": subject,
            "proof": "signed_supplier_token",
            "requested_session": f"supply_chain_{scenario_mode}_{datetime.now(UTC).strftime('%Y_%m_%d')}",
            "delegation_token": token,
        }
    )
    session_id = identity["session"]["session_id"]
    capability = capability_handshake(
        session_id,
        {
            "can_share": ["inventory_position", "delivery_eta", "supplier_compliance", "cold_chain_status", "parts_availability"],
            "can_receive": ["demand_forecast", "restock_request", "dock_slot", "substitution_request", "purchase_order_notice", "maintenance_parts_request", "safety_notice"],
            "cannot_do": ["auto_accept_price_change", "bypass_food_safety", "release_vendor_payment_without_approval", "auto_purchase"],
            "delegation_token": token,
        },
    )
    intent = intent_handshake(
        session_id,
        {
            "goal": run.get("goal") or "coordinate_supplier_counterparty",
            "time_window": "3_hours",
            "constraints": run.get("constraints") or {"scenario_mode": scenario_mode},
            "scenario_mode": scenario_mode,
            "delegation_token": token,
        },
    )
    proposal = propose_plan(session_id, {"planner": run.get("planner") or scenario_mode, "scenario_mode": scenario_mode, "delegation_token": token})
    counter = counter_proposal(
        session_id,
        {
            "counter_request": run.get("counter_request") or "supplier counterproposal",
            "priority_change": run.get("priority_change") or {},
            "scenario_mode": scenario_mode,
            "delegation_token": token,
        },
    )
    commitment = commit_plan(session_id, {"accepted": True, "notify_supplier": True, "scenario_mode": scenario_mode, "delegation_token": token})
    monitoring = monitor_session(session_id, {"event": run.get("monitor_event") or "supplier_monitor", "scenario_mode": scenario_mode, "delegation_token": token})
    procurement_gate = commerce_agent_evaluate(
        session_id,
        {
            "action": run.get("commerce_action") or "purchase_order",
            "amount": 4200,
            "reason": run.get("commerce_reason") or f"{scenario_mode} procurement boundary probe.",
            "scenario_mode": scenario_mode,
            "delegation_token": token,
        },
    )
    receipt = session_protocol_receipt(session_id, {"scenario_mode": scenario_mode, "delegation_token": token})
    receipt_body = receipt["receipt"]
    verification = verify_protocol_artifact({"artifact": receipt_body, "expected_artifact_type": "agent_handshake_session_receipt"})
    session = get_session(session_id)["session"]
    passport_evolution = _build_passport_evolution_artifact(
        session=session,
        receipt=receipt_body,
        verification=verification,
        counterparty="supplier",
        scenario_mode=scenario_mode,
        memory_context={"status": "local_demo_memory", "collections": {"agent_handshake_sessions": "in_memory", "agent_passport_evolution": "in_memory"}},
        trust_context={"trust_tier": "certified_supplier_candidate"},
        adversarial_probes=[],
    )
    demo = {
        "status": "demo_complete",
        "mode": "supply_chain_agent_handshake",
        "counterparty": "supplier",
        "scenario_mode": scenario_mode,
        "session_id": session_id,
        "steps": [identity, capability, intent, proposal, counter, commitment, monitoring, procurement_gate, receipt],
        "receipt": receipt_body,
        "verification": verification,
        "passport_evolution": passport_evolution,
        "session": session,
    }
    return _attach_external_agent_outputs(demo)
