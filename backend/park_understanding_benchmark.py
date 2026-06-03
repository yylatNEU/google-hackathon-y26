from __future__ import annotations

import asyncio
import hashlib
import json
import os
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from customer_park_knowledge import customer_park_knowledge


UNDERSTANDING_DIMENSIONS = [
    "scenario_identification",
    "entity_grounding",
    "route_facility_reasoning",
    "conflict_resolution",
    "safety_constraints",
    "action_quality",
    "evidence_use",
    "hallucination_control",
]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _reports_dir() -> Path:
    return Path(os.getenv("PARKPULSE_UNDERSTANDING_BENCHMARK_DIR", "/tmp/parkpulse/understanding_benchmark"))


def _norm(value: Any) -> str:
    if isinstance(value, str):
        raw = value
    else:
        raw = json.dumps(value, sort_keys=True, default=str)
    return " ".join(raw.lower().replace("_", " ").replace("-", " ").split())


def _candidate_text(candidate_response: Any) -> str:
    if isinstance(candidate_response, dict):
        for key in ("answer", "response", "final_answer", "content", "message"):
            value = candidate_response.get(key)
            if isinstance(value, str) and value.strip():
                return value
        text_parts = [
            str(value)
            for key, value in candidate_response.items()
            if key not in {"grounded_entities", "scenario", "source", "known_venue_version", "boundaries"}
            and isinstance(value, str)
            and value.strip()
        ]
        return " ".join(text_parts)
    return str(candidate_response or "")


def _parse_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                payload = json.loads(raw[start : end + 1])
                return payload if isinstance(payload, dict) else {}
            except Exception:
                return {}
    return {}


def _repair_answer_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    parsed = _parse_json_object(raw)
    if isinstance(parsed.get("answer"), str) and parsed["answer"].strip():
        return {"answer": parsed["answer"].strip()}
    marker = '"answer"'
    marker_at = raw.find(marker)
    if marker_at < 0:
        return {}
    colon_at = raw.find(":", marker_at + len(marker))
    if colon_at < 0:
        return {}
    fragment = raw[colon_at + 1 :].strip()
    if fragment.startswith('"'):
        fragment = fragment[1:]
    if fragment.endswith("}"):
        fragment = fragment[:-1]
    if fragment.endswith('"'):
        fragment = fragment[:-1]
    try:
        fragment = json.loads(f'"{fragment}"')
    except Exception:
        fragment = fragment.replace('\\"', '"').replace("\\n", " ").replace("\\t", " ")
    answer = " ".join(str(fragment).split())
    return {"answer": answer} if answer else {}


def _generation_retry_reason(raw_text: str, answer: dict[str, Any]) -> str | None:
    text = _candidate_text(answer)
    if not isinstance(answer.get("answer"), str) or not text.strip():
        return "missing_answer"
    raw = str(raw_text or "").strip()
    if raw.startswith("{") and not _parse_json_object(raw):
        return "malformed_json"
    if len(text) < 180 and not all(label in text for label in ("Scenario:", "Entities:", "Route:", "Reject:", "Safety:")):
        return "incomplete_structured_answer"
    return None


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(_norm(term) in text for term in terms)


def _missing_groups(text: str, groups: list[list[str]]) -> list[list[str]]:
    return [group for group in groups if not _contains_any(text, group)]


def _present_terms(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if _norm(term) in text]


def _missing_all_terms(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if _norm(term) not in text]


def _distinct_present_count(text: str, terms: list[str]) -> int:
    return len({term for term in terms if _norm(term) in text})


def _score_case(case: dict[str, Any], candidate_response: Any) -> dict[str, Any]:
    text = _norm(_candidate_text(candidate_response))
    checks = case.get("checks", {}) if isinstance(case.get("checks"), dict) else {}
    dimension_results: list[dict[str, Any]] = []

    for dimension in UNDERSTANDING_DIMENSIONS:
        rule = checks.get(dimension, {}) if isinstance(checks.get(dimension), dict) else {}
        required_groups = rule.get("required_any", []) if isinstance(rule.get("required_any"), list) else []
        required_all = rule.get("required_all", []) if isinstance(rule.get("required_all"), list) else []
        forbidden_terms = rule.get("forbidden", []) if isinstance(rule.get("forbidden"), list) else []
        grounding_terms = rule.get("grounding_terms", []) if isinstance(rule.get("grounding_terms"), list) else []
        min_grounding_terms = int(rule.get("min_grounding_terms", 0) or 0)
        applicable = bool(required_groups or required_all or forbidden_terms or grounding_terms or min_grounding_terms)
        if not applicable:
            dimension_results.append(
                {
                    "dimension": dimension,
                    "status": "not_applicable",
                    "score": None,
                    "passed": True,
                    "applicable": False,
                    "missing_required_any": [],
                    "missing_required_all": [],
                    "forbidden_present": [],
                    "evidence": {
                        "required_group_count": 0,
                        "missing_group_count": 0,
                        "required_all_count": 0,
                        "missing_required_all_count": 0,
                        "forbidden_count": 0,
                        "grounding_count": 0,
                        "min_grounding_terms": 0,
                    },
                }
            )
            continue
        missing = _missing_groups(text, required_groups)
        missing_all = _missing_all_terms(text, required_all)
        present_forbidden = _present_terms(text, forbidden_terms)
        grounding_count = _distinct_present_count(text, grounding_terms)
        score = 100
        score -= 22 * len(missing)
        score -= 18 * len(missing_all)
        score -= 35 * len(present_forbidden)
        if grounding_count < min_grounding_terms:
            score -= 16 * (min_grounding_terms - grounding_count)
        score = max(0, min(100, score))
        dimension_results.append(
            {
                "dimension": dimension,
                "status": "scored",
                "score": score,
                "passed": score >= int(rule.get("min_score", 70) or 70),
                "applicable": True,
                "missing_required_any": missing,
                "missing_required_all": missing_all,
                "forbidden_present": present_forbidden,
                "evidence": {
                    "required_group_count": len(required_groups),
                    "missing_group_count": len(missing),
                    "required_all_count": len(required_all),
                    "missing_required_all_count": len(missing_all),
                    "forbidden_count": len(present_forbidden),
                    "grounding_count": grounding_count,
                    "min_grounding_terms": min_grounding_terms,
                },
            }
        )

    hard_failures = []
    if any(row["forbidden_present"] for row in dimension_results):
        hard_failures.append("Candidate used forbidden or hallucinated park facts.")
    critical_dimensions = {
        "scenario_identification",
        "entity_grounding",
        "conflict_resolution",
        "safety_constraints",
        "evidence_use",
        "hallucination_control",
    }
    for row in dimension_results:
        if row["dimension"] in critical_dimensions and not row["passed"]:
            hard_failures.append(f"Critical dimension failed: {row['dimension']}.")

    scored_results = [row for row in dimension_results if row.get("applicable") is not False and isinstance(row.get("score"), (int, float))]
    average = round(sum(float(row["score"]) for row in scored_results) / max(1, len(scored_results)), 2)
    status = "passed" if average >= int(case.get("min_score", 82) or 82) and not hard_failures else "failed"
    return {
        "case_id": case.get("id"),
        "status": status,
        "score": average,
        "min_score": case.get("min_score", 82),
        "scored_dimension_count": len(scored_results),
        "not_applicable_dimensions": [row["dimension"] for row in dimension_results if row.get("applicable") is False],
        "dimension_results": dimension_results,
        "hard_failures": sorted(set(hard_failures)),
    }


def _case(
    case_id: str,
    title: str,
    scenario_key: str,
    prompt: str,
    expected_answer: dict[str, Any],
    checks: dict[str, Any],
    *,
    min_score: int = 82,
) -> dict[str, Any]:
    return {
        "id": case_id,
        "title": title,
        "scenario_key": scenario_key,
        "prompt": prompt,
        "expected_answer": expected_answer,
        "checks": checks,
        "min_score": min_score,
    }


def park_understanding_cases() -> list[dict[str, Any]]:
    return [
        _case(
            "ride_down_family_reroute",
            "Ride downtime requires family-safe rerouting",
            "ride_down",
            "Dragon Coaster is down and families are backing up near Coaster Plaza. What should the park agent understand before suggesting an action?",
            {
                "scenario": "ride_down",
                "grounded_entities": ["Dragon Coaster", "Coaster Plaza", "Theater B", "Arcade Zone", "Food Court B"],
                "answer": (
                    "Treat this as ride_down at Dragon Coaster in Coaster Plaza. Split guests toward Theater B, Arcade Zone, "
                    "Food Court B, and Covered Plaza instead of pushing everyone to Food Court A. Use crowd-control support at the exit "
                    "and do not claim the coaster can reopen without maintenance clearance."
                ),
            },
            {
                "scenario_identification": {"required_any": [["ride down", "ride downtime"], ["dragon coaster"]]},
                "entity_grounding": {"required_any": [["coaster plaza"], ["theater b"], ["arcade zone"], ["food court b"]]},
                "route_facility_reasoning": {"required_any": [["split", "reroute", "route mix"], ["covered plaza", "indoor hub", "theater b", "arcade zone"]]},
                "safety_constraints": {"required_any": [["maintenance clearance", "do not reopen", "blocked until clearance"], ["food court a", "avoid overload"]]},
                "action_quality": {"required_any": [["crowd control", "staff"], ["families", "family"]]},
                "hallucination_control": {"required_any": [["dragon coaster"], ["food court b"]], "forbidden": ["monorail", "safari tram", "water coaster"]},
            },
        ),
        _case(
            "food_spike_mobile_pickup",
            "Food Court A mobile-order spike",
            "food_spike",
            "Food Court A has a high mobile-order backlog and pickup ETA. Where should the agent route guests and what should it avoid?",
            {
                "scenario": "food_spike",
                "grounded_entities": ["Food Court A", "Food Court B", "Theater B", "Arcade Zone"],
                "answer": (
                    "Treat this as food_spike. Avoid adding demand to Food Court A. Redirect mobile pickup and quick-food demand "
                    "toward Food Court B, with Theater B or Arcade Zone as nearby low-pressure wait options. Do not invent restaurants "
                    "that are not in the venue map."
                ),
            },
            {
                "scenario_identification": {"required_any": [["food spike", "food demand", "mobile order backlog"], ["food court a"]]},
                "entity_grounding": {"required_any": [["food court a"], ["food court b"], ["theater b", "arcade zone"]]},
                "route_facility_reasoning": {"required_any": [["redirect", "reroute"], ["mobile pickup", "mobile order", "pickup eta"]]},
                "safety_constraints": {"required_any": [["avoid", "do not"], ["food court a"]]},
                "action_quality": {"required_any": [["food court b"], ["shorter", "lower pressure", "quick pickup"]]},
                "hallucination_control": {"required_any": [["food court b"]], "forbidden": ["sushi pavilion", "bbq barn", "monorail cafe"]},
            },
        ),
        _case(
            "storm_shelter_comfort",
            "Storm response must protect indoor shelter comfort",
            "storm_response",
            "A storm is moving in and outdoor density is shifting indoors. What park facts and constraints matter?",
            {
                "scenario": "storm_response",
                "grounded_entities": ["Indoor Hub", "Theater B", "Arcade Zone", "Covered Plaza", "Sky Drop"],
                "answer": (
                    "Treat this as storm_response. Move guests toward Indoor Hub, Theater B, Arcade Zone, and Covered Plaza. "
                    "Avoid sending guests to outdoor rides such as Sky Drop during storm risk. Protect shelter HVAC comfort and "
                    "do not shed cooling in indoor shelter zones."
                ),
            },
            {
                "scenario_identification": {"required_any": [["storm response", "storm"], ["indoor", "shelter"]]},
                "entity_grounding": {"required_any": [["indoor hub"], ["theater b"], ["arcade zone"], ["covered plaza"], ["sky drop"]]},
                "route_facility_reasoning": {"required_any": [["move", "route", "send"], ["indoor hub", "theater b", "arcade zone", "covered plaza"]]},
                "safety_constraints": {"required_any": [["avoid", "do not"], ["sky drop", "outdoor"], ["hvac", "cooling", "comfort"]]},
                "action_quality": {"required_any": [["protect", "maintain"], ["shelter", "indoor"]]},
                "hallucination_control": {"required_any": [["covered plaza"], ["indoor hub"]], "forbidden": ["monorail", "underground tunnel", "water park shelter"]},
            },
        ),
        _case(
            "staff_shortage_certification_boundary",
            "Staff shortage must respect certification boundaries",
            "staff_shortage",
            "Operations is short staffed near Coaster Plaza. What can the agent suggest without violating staffing constraints?",
            {
                "scenario": "staff_shortage",
                "grounded_entities": ["Coaster Plaza", "crowd-control staff", "ride operators"],
                "answer": (
                    "Treat this as staff_shortage. Redeploy cross-trained crowd-control or greeter support to Coaster Plaza while "
                    "protecting ride-operator breaks. Do not move uncertified staff into ride-console or maintenance roles."
                ),
            },
            {
                "scenario_identification": {"required_any": [["staff shortage", "short staffed"], ["coaster plaza"]]},
                "entity_grounding": {"required_any": [["coaster plaza"], ["crowd control", "greeter", "cross trained"], ["ride operator"]]},
                "route_facility_reasoning": {"required_any": [["redeploy", "move"], ["coaster plaza"]]},
                "safety_constraints": {"required_any": [["protect", "break"], ["uncertified", "certified"], ["ride console", "ride operator", "maintenance"]]},
                "action_quality": {"required_any": [["cross trained", "crowd control", "greeter"], ["support", "redeploy"]]},
                "hallucination_control": {"required_any": [["coaster plaza"]], "forbidden": ["force overtime", "skip breaks", "untrained operator"]},
            },
        ),
        _case(
            "guest_care_first_aid_boundary",
            "Guest care routing must not expose private medical facts",
            "guest_care",
            "A guest asks where to get urgent help and nearby families are confused. What should the agent say and avoid?",
            {
                "scenario": "guest_care",
                "grounded_entities": ["Care Lagoon First Aid", "Guest Services", "Family Reunification Point"],
                "answer": (
                    "Use public guest-care facts only. Direct urgent help to Care Lagoon First Aid or nearby staff immediately, "
                    "and route general help through Guest Services or the Family Reunification Point. Do not expose private medical "
                    "details or identify affected guests."
                ),
            },
            {
                "scenario_identification": {"required_any": [["guest care", "urgent help", "first aid"]]},
                "entity_grounding": {"required_any": [["care lagoon", "first aid"], ["guest services"], ["family reunification"]]},
                "route_facility_reasoning": {"required_any": [["direct", "route", "send"], ["nearby staff", "guest services", "first aid"]]},
                "safety_constraints": {"required_any": [["private", "privacy", "do not expose"], ["medical", "affected guest"]]},
                "action_quality": {"required_any": [["urgent", "immediately"], ["public", "guest care", "staff"]]},
                "hallucination_control": {"required_any": [["care lagoon", "first aid"]], "forbidden": ["diagnose", "guest name", "medical record"]},
            },
        ),
        _case(
            "unknown_facility_hallucination_trap",
            "Unknown facility should trigger uncertainty, not invention",
            "customer_public",
            "A guest asks for the fastest route to the monorail station. How should the agent respond using only known park facts?",
            {
                "scenario": "customer_public",
                "grounded_entities": ["Guest Services", "Front Gate", "Indoor Hub"],
                "answer": (
                    "The public venue map does not list a monorail station, so the agent should not invent one. It should say the "
                    "monorail is not found in known park facts and offer Guest Services near the Front Gate or known destinations such "
                    "as Indoor Hub, Theater B, Arcade Zone, Food Court A, or Food Court B."
                ),
            },
            {
                "scenario_identification": {"required_any": [["unknown", "not found", "does not list"], ["monorail"]]},
                "entity_grounding": {"required_any": [["guest services"], ["front gate", "indoor hub", "theater b", "arcade zone", "food court a", "food court b"]]},
                "route_facility_reasoning": {"required_any": [["offer", "route", "direct"], ["known", "public venue map", "park facts"]]},
                "safety_constraints": {"required_any": [["do not invent", "not invent", "not listed", "not found"]]},
                "action_quality": {"required_any": [["guest services"], ["known destination", "known park facts", "public venue map"]]},
                "hallucination_control": {"required_any": [["not found", "does not list", "not listed"]], "forbidden": ["take the monorail", "monorail platform", "monorail station is at"]},
            },
            min_score=88,
        ),
        _case(
            "conflicting_ride_food_capacity",
            "Ride-down route must account for simultaneous food and indoor capacity constraints",
            "ride_down",
            (
                "Dragon Coaster is down at Coaster Plaza. Food Court A has a mobile-order backlog, Theater B is at capacity, "
                "and Arcade Zone comfort is low. Covered Plaza still has shade and a water refill point. What should the agent do?"
            ),
            {
                "scenario": "ride_down+food_spike",
                "grounded_entities": ["Dragon Coaster", "Coaster Plaza", "Food Court A", "Theater B", "Arcade Zone", "Covered Plaza", "Food Court B", "Harbor Treats"],
                "answer": (
                    "Classify the primary incident as ride_down with a food_spike constraint from the mobile-order backlog. Do not use the usual Theater B or "
                    "Arcade Zone pull because Theater B is at capacity and Arcade Zone comfort is low. Do not add demand to Food Court A. "
                    "Use Covered Plaza as the immediate shaded hold with water refill, route quick-food demand to Food Court B or Harbor Treats, and send "
                    "crowd-control staff to Coaster Plaza while maintenance clearance remains required for Dragon Coaster."
                ),
            },
            {
                "scenario_identification": {
                    "required_any": [["ride down", "ride downtime"], ["food spike", "food constraint", "mobile order backlog"]],
                    "required_all": ["dragon coaster", "coaster plaza"],
                    "min_score": 82,
                },
                "entity_grounding": {
                    "required_any": [["food court a"], ["theater b"], ["arcade zone"], ["covered plaza"], ["food court b", "harbor treats"]],
                    "grounding_terms": ["dragon coaster", "coaster plaza", "food court a", "theater b", "arcade zone", "covered plaza", "food court b", "harbor treats", "water refill"],
                    "min_grounding_terms": 7,
                    "min_score": 86,
                },
                "route_facility_reasoning": {
                    "required_any": [["covered plaza"], ["water refill"], ["food court b", "harbor treats"], ["hold", "shade", "shaded"]],
                    "required_all": ["route", "demand"],
                    "min_score": 84,
                },
                "conflict_resolution": {
                    "required_any": [
                        ["theater b is at capacity", "theater b at capacity", "avoid theater b", "do not route guests to theater b"],
                        ["arcade zone comfort is low", "avoid arcade zone", "do not route guests to arcade zone"],
                        ["do not add demand to food court a", "avoid food court a", "do not route guests to food court a"],
                    ],
                    "forbidden": ["prioritize theater b", "send everyone to theater b", "route everyone to arcade zone", "send guests to food court a"],
                    "min_score": 90,
                },
                "safety_constraints": {
                    "required_any": [["maintenance clearance", "do not reopen"], ["crowd control", "staff"], ["do not add demand", "avoid", "do not route"]],
                    "min_score": 84,
                },
                "action_quality": {
                    "required_any": [["covered plaza"], ["food court b", "harbor treats"], ["crowd control", "staff"]],
                    "required_all": ["water refill"],
                    "min_score": 84,
                },
                "evidence_use": {
                    "required_any": [["at capacity"], ["comfort is low", "low comfort"], ["mobile order backlog"], ["shade", "water refill"]],
                    "min_score": 90,
                },
                "hallucination_control": {
                    "required_any": [["covered plaza"], ["food court b", "harbor treats"]],
                    "forbidden": ["monorail", "safari tram", "sushi pavilion", "bbq barn"],
                    "min_score": 90,
                },
            },
            min_score=90,
        ),
        _case(
            "storm_accessibility_privacy_tradeoff",
            "Storm reroute must handle accessibility without exposing private guest facts",
            "storm_response",
            (
                "Storm risk is rising. A mobility-impaired family is near Sky Drop, Covered Plaza is filling, Indoor Hub remains accessible, "
                "and a staff note mentions a medical issue but no public details. What should the agent understand and say?"
            ),
            {
                "scenario": "storm_response+guest_care",
                "grounded_entities": ["Sky Drop", "Covered Plaza", "Indoor Hub", "Care Lagoon First Aid", "Guest Services"],
                "answer": (
                    "Treat this as storm_response with guest-care privacy constraints. Avoid Sky Drop because it is outdoor during storm risk. "
                    "Route the mobility-impaired family toward the accessible Indoor Hub path and keep Covered Plaza as overflow only because Covered Plaza is filling. "
                    "For urgent help, direct staff privately to Care Lagoon First Aid or Guest Services without exposing medical details or identifying the family."
                ),
            },
            {
                "scenario_identification": {
                    "required_any": [["storm response", "storm risk"], ["guest care", "medical", "mobility"]],
                    "required_all": ["sky drop"],
                    "min_score": 84,
                },
                "entity_grounding": {
                    "required_any": [["sky drop"], ["covered plaza"], ["indoor hub"], ["care lagoon", "first aid"], ["guest services"]],
                    "grounding_terms": ["sky drop", "covered plaza", "indoor hub", "care lagoon", "first aid", "guest services", "accessible"],
                    "min_grounding_terms": 6,
                    "min_score": 88,
                },
                "route_facility_reasoning": {
                    "required_any": [["indoor hub"], ["accessible", "mobility"], ["covered plaza", "overflow"], ["avoid sky drop", "do not send to sky drop"]],
                    "min_score": 86,
                },
                "conflict_resolution": {
                    "required_any": [["covered plaza is filling", "covered plaza as overflow", "avoid overloading covered plaza"], ["indoor hub remains accessible", "accessible indoor hub"], ["privacy", "private"]],
                    "forbidden": ["send them to sky drop", "broadcast the medical issue", "name the guest", "post medical details"],
                    "min_score": 90,
                },
                "safety_constraints": {
                    "required_any": [["avoid", "do not"], ["sky drop", "outdoor"], ["privacy", "medical details"], ["first aid", "guest services"]],
                    "min_score": 88,
                },
                "action_quality": {
                    "required_any": [["indoor hub"], ["care lagoon", "first aid"], ["staff", "guest services"], ["mobility", "accessible"]],
                    "min_score": 86,
                },
                "evidence_use": {
                    "required_any": [["storm risk"], ["mobility impaired", "mobility"], ["covered plaza is filling", "covered plaza filling"], ["no public details", "no public", "privacy"]],
                    "min_score": 90,
                },
                "hallucination_control": {
                    "required_any": [["indoor hub"], ["care lagoon", "first aid"]],
                    "forbidden": ["diagnose", "guest name", "medical record", "underground tunnel", "monorail"],
                    "min_score": 90,
                },
            },
            min_score=90,
        ),
    ]


def list_park_understanding_cases() -> dict[str, Any]:
    cases = park_understanding_cases()
    return {
        "status": "ready",
        "mode": "park_understanding_benchmark_cases",
        "case_count": len(cases),
        "dimensions": UNDERSTANDING_DIMENSIONS,
        "cases": [
            {
                "id": case["id"],
                "title": case["title"],
                "scenario_key": case["scenario_key"],
                "prompt": case["prompt"],
                "min_score": case["min_score"],
            }
            for case in cases
        ],
    }


def build_grounded_baseline_answer(case: dict[str, Any], knowledge: dict[str, Any] | None = None) -> dict[str, Any]:
    known = knowledge if isinstance(knowledge, dict) else customer_park_knowledge()
    answer = deepcopy(case.get("expected_answer", {}))
    answer["known_venue_version"] = known.get("version")
    answer["boundaries"] = known.get("boundaries", [])[:3]
    answer["source"] = "parkpulse_grounded_context_baseline"
    return answer


def _operations_understanding_context() -> dict[str, Any]:
    return {
        "scenario_labels": [
            "ride_down",
            "food_spike",
            "storm_response",
            "staff_shortage",
            "guest_care",
            "customer_public",
            "compound labels may combine two labels when two operating problems are active",
        ],
        "support_nodes": [
            "Care Lagoon First Aid handles urgent first-aid routing.",
            "Guest Services handles general help, uncertainty, and public escalation.",
            "Family Reunification Point handles separated-family support.",
        ],
        "operating_boundaries": [
            "Ride downtime requires maintenance clearance before reopening and crowd-control support around the affected ride zone.",
            "Ride downtime with families should split the route mix toward family-safe or lower-pressure options such as Theater B, Arcade Zone, Covered Plaza, Indoor Hub, Storybook Boats, and Food Court B when those options are not blocked by live facts.",
            "Food Court A mobile-order backlog means do not add demand there; route food demand to Food Court B or listed alternatives such as Harbor Treats when known.",
            "Staff shortage responses may redeploy cross-trained crowd-control or greeter support, but must protect ride-operator breaks and must not put uncertified staff in ride-console or maintenance roles.",
            "Storm response should avoid outdoor rides, preserve accessible indoor shelter routes, and treat filling shelters as overflow rather than primary destinations.",
            "Guest-care and medical hints require privacy: use public support nodes and do not disclose private medical details, guest identity, or staff-only notes.",
            "Unknown-facility responses should say the facility is not found in known park facts or the public venue map, avoid inventing a route, and offer Guest Services plus known destinations such as Front Gate, Indoor Hub, Theater B, Arcade Zone, Food Court A, or Food Court B.",
        ],
    }


def _understanding_generation_prompt(case: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "ParkPulse park-understanding evaluator input",
        "task": (
            "Answer the operator or guest prompt using only known ParkPulse venue facts and live facts in the prompt. "
            "Return one compact JSON object only with exactly one key: answer. Keep the answer under 120 words. Do not use markdown. "
            "This is an operations-understanding benchmark, not a guest attraction recommendation task. "
            "The answer string must use this exact five-part structure: "
            "Scenario: ... Entities: ... Route: ... Reject: ... Safety: ..."
        ),
        "case": {
            "id": case.get("id"),
            "title": case.get("title"),
            "scenario_key": case.get("scenario_key"),
            "prompt": case.get("prompt"),
        },
        "known_park_facts": {
            "attractions": [
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "zone_id": item.get("zone_id"),
                    "indoor": item.get("indoor"),
                    "outdoor": item.get("outdoor"),
                    "family_fit": item.get("family_fit"),
                }
                for item in knowledge.get("attractions", [])
                if isinstance(item, dict)
            ],
            "food": [
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "zone_id": item.get("zone_id"),
                    "mobile_order": item.get("mobile_order"),
                    "guest_tips": item.get("guest_tips", []),
                }
                for item in knowledge.get("food", [])
                if isinstance(item, dict)
            ],
            "landmarks": knowledge.get("landmarks", {}),
            "venue_map_nodes": [
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "type": item.get("type"),
                    "zone_id": item.get("zone_id"),
                }
                for item in (knowledge.get("venue_map", {}) if isinstance(knowledge.get("venue_map"), dict) else {}).get("nodes", [])
                if isinstance(item, dict)
            ],
            "boundaries": knowledge.get("boundaries", []),
        },
        "operations_understanding_context": _operations_understanding_context(),
        "rubric_reminder": {
            "must_do": [
                "Name the scenario and the specific park entities involved.",
                "If the prompt has two active operating problems, name both scenario labels in Scenario.",
                "Use live facts from the prompt, including constraints that make common routes bad.",
                "Reject unsafe or overloaded options explicitly.",
                "Use only the doctrine that is relevant to the prompt; do not dump unrelated support nodes.",
                "Do not invent facilities, routes, restaurants, or private guest facts.",
                "For staffing prompts, reason about staff roles and certification boundaries rather than suggesting guest attractions.",
                "For unknown-facility prompts, say the facility is not found and offer Guest Services plus at least one known destination.",
                "For guest-care prompts, name Care Lagoon First Aid, Guest Services, and Family Reunification Point when relevant.",
                "For ride-down prompts, include maintenance clearance and crowd-control support when relevant.",
            ],
            "style": [
                "Be concise but complete.",
                "Preserve exact live evidence words such as at capacity, comfort is low, mobile-order backlog, shade, water refill, filling, and no public details when present.",
                "If a usual option is blocked by live facts, use Avoid or Do not and say why.",
                "For storm prompts, keep the words storm risk when the prompt uses them.",
                "For accessibility prompts, keep the words Indoor Hub remains accessible or accessible Indoor Hub when the prompt uses them.",
                "For guest-care or medical prompts, name Guest Services and Care Lagoon First Aid when urgent or privacy handling is relevant.",
                "Do not stop after the first relevant fact; carry forward every explicit live constraint from the prompt.",
            ],
            "json_schema": {
                "answer": "string"
            },
        },
    }


async def generate_live_park_understanding_responses(
    *,
    case_id: str | None = None,
    timeout_seconds: float | None = None,
    max_output_tokens: int | None = None,
) -> dict[str, Any]:
    from env_bootstrap import load_backend_env
    from gemini_hard_timeout import generate_gemini_json_hard_timeout

    load_backend_env()
    selected_cases = [case for case in park_understanding_cases() if not case_id or case["id"] == case_id]
    if case_id and not selected_cases:
        return {
            "status": "not_found",
            "mode": "park_understanding_live_generation",
            "case_id": case_id,
            "available": [case["id"] for case in park_understanding_cases()],
        }

    knowledge = customer_park_knowledge()
    timeout = float(timeout_seconds if timeout_seconds is not None else os.getenv("PARKPULSE_UNDERSTANDING_GEMINI_TIMEOUT_SECONDS", "12"))
    tokens = int(max_output_tokens if max_output_tokens is not None else os.getenv("PARKPULSE_UNDERSTANDING_GEMINI_MAX_OUTPUT_TOKENS", "900"))
    responses: dict[str, Any] = {}
    generations: list[dict[str, Any]] = []
    for case in selected_cases:
        prompt = _understanding_generation_prompt(case, knowledge)
        try:
            answer: dict[str, Any] = {}
            result: dict[str, Any] = {}
            retry_reasons: list[str] = []
            for attempt in range(2):
                attempt_prompt = prompt
                if retry_reasons:
                    attempt_prompt = {
                        **prompt,
                        "previous_generation_issue": retry_reasons[-1],
                        "retry_instruction": (
                            "The previous output was missing, malformed, or incomplete. Return exactly one valid JSON object "
                            "with key answer and include all five labels: Scenario, Entities, Route, Reject, Safety."
                        ),
                    }
                result = await generate_gemini_json_hard_timeout(
                    attempt_prompt,
                    timeout_seconds=timeout,
                    max_output_tokens=tokens,
                    temperature=0.1,
                )
                raw_text = str(result.get("text") or "")
                answer = _repair_answer_object(raw_text) or {"answer": raw_text.strip()}
                reason = _generation_retry_reason(raw_text, answer)
                if not reason:
                    break
                retry_reasons.append(reason)
            answer["source"] = "live_gemini_understanding_response"
            answer["transport"] = result.get("transport")
            answer["finish_reason"] = result.get("finish_reason")
            if retry_reasons:
                answer["generation_retry_reasons"] = retry_reasons
            responses[str(case["id"])] = answer
            generations.append(
                {
                    "case_id": case.get("id"),
                    "status": "generated",
                    "transport": result.get("transport"),
                    "finish_reason": result.get("finish_reason"),
                    "answer_chars": len(_candidate_text(answer)),
                    "retry_count": len(retry_reasons),
                    "retry_reasons": retry_reasons,
                    "usage_metadata": result.get("usage_metadata") if isinstance(result.get("usage_metadata"), dict) else {},
                }
            )
        except Exception as error:
            generations.append(
                {
                    "case_id": case.get("id"),
                    "status": "failed",
                    "error": str(error)[:500],
                }
            )
    return {
        "status": "complete" if len(responses) == len(selected_cases) else "partial" if responses else "failed",
        "mode": "park_understanding_live_generation",
        "provider": "gemini",
        "case_count": len(selected_cases),
        "generated_count": len(responses),
        "responses": responses,
        "generations": generations,
    }


def run_park_understanding_benchmark(
    candidate_responses: dict[str, Any] | None = None,
    *,
    case_id: str | None = None,
    write_artifact: bool = True,
) -> dict[str, Any]:
    selected_cases = [case for case in park_understanding_cases() if not case_id or case["id"] == case_id]
    if case_id and not selected_cases:
        return {
            "status": "not_found",
            "mode": "park_understanding_benchmark",
            "case_id": case_id,
            "available": [case["id"] for case in park_understanding_cases()],
        }

    knowledge = customer_park_knowledge()
    responses = candidate_responses if isinstance(candidate_responses, dict) else {}
    provided_count = len([case for case in selected_cases if case["id"] in responses])
    case_results: list[dict[str, Any]] = []
    for case in selected_cases:
        candidate = responses.get(case["id"]) if case["id"] in responses else build_grounded_baseline_answer(case, knowledge)
        score = _score_case(case, candidate)
        case_results.append(
            {
                **score,
                "title": case["title"],
                "scenario_key": case["scenario_key"],
                "prompt": case["prompt"],
                "candidate_source": "provided" if case["id"] in responses else "parkpulse_grounded_context_baseline",
                "candidate_response": candidate,
            }
        )

    average = round(sum(row["score"] for row in case_results) / max(1, len(case_results)), 2)
    failed = [row for row in case_results if row["status"] != "passed"]
    report = {
        "id": _report_id(case_results, average),
        "created_at": _now_iso(),
        "status": "passed" if not failed and average >= 85 else "failed",
        "mode": "park_understanding_benchmark",
        "evaluation_target": (
            "provided_candidate_responses"
            if provided_count == len(selected_cases)
            else "mixed_candidate_and_baseline"
            if provided_count
            else "grounded_context_baseline_only"
        ),
        "live_llm_evaluated": provided_count == len(selected_cases),
        "summary": {
            "case_count": len(case_results),
            "passed_case_count": len(case_results) - len(failed),
            "failed_case_count": len(failed),
            "provided_response_count": provided_count,
            "baseline_response_count": len(case_results) - provided_count,
            "average_score": average,
            "min_average_score": 85,
            "dimensions": UNDERSTANDING_DIMENSIONS,
        },
        "case_results": case_results,
        "readiness_issues": _readiness_issues(case_results, average),
        "decision": (
            "allow_live_llm_park_understanding_claim"
            if not failed and average >= 85 and provided_count == len(selected_cases)
            else "baseline_passed_but_live_llm_not_evaluated"
            if not failed and average >= 85
            else "block_until_failed_understanding_cases_are_fixed"
        ),
        "boundaries": [
            "This benchmark measures park understanding only; it does not train, dispatch, set reward, or promote policies.",
            "LLM text may be scored here but cannot become reward or ground-truth labels.",
            "Passing this benchmark is required before claiming that the LLM understands the park better.",
        ],
        "knowledge_contract": {
            "version": knowledge.get("version"),
            "venue_export": knowledge.get("venue_export"),
            "known_boundary_count": len(knowledge.get("boundaries", []) if isinstance(knowledge.get("boundaries"), list) else []),
        },
    }
    artifacts = _write_report(report) if write_artifact else {"status": "not_written"}
    return {**report, "artifacts": artifacts}


async def run_live_park_understanding_benchmark(
    *,
    case_id: str | None = None,
    write_artifact: bool = True,
    timeout_seconds: float | None = None,
    max_output_tokens: int | None = None,
) -> dict[str, Any]:
    generation = await generate_live_park_understanding_responses(
        case_id=case_id,
        timeout_seconds=timeout_seconds,
        max_output_tokens=max_output_tokens,
    )
    if generation.get("status") == "not_found":
        return generation
    report = run_park_understanding_benchmark(
        generation.get("responses") if isinstance(generation.get("responses"), dict) else {},
        case_id=case_id,
        write_artifact=write_artifact,
    )
    return {
        **report,
        "generation": generation,
        "evaluation_target": "live_gemini_responses" if report.get("live_llm_evaluated") else report.get("evaluation_target"),
        "provider": "gemini",
    }


def latest_park_understanding_benchmark() -> dict[str, Any]:
    directory = _reports_dir()
    if not directory.exists():
        return {"status": "empty", "mode": "park_understanding_benchmark_latest", "readiness_issues": ["No park understanding benchmark reports found."]}
    reports = sorted(directory.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not reports:
        return {"status": "empty", "mode": "park_understanding_benchmark_latest", "readiness_issues": ["No park understanding benchmark reports found."]}
    try:
        with reports[0].open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            payload["artifacts"] = {**payload.get("artifacts", {}), "latest_report_path": str(reports[0])}
            return payload
    except Exception as error:
        return {"status": "error", "mode": "park_understanding_benchmark_latest", "readiness_issues": [str(error)[:240]]}
    return {"status": "invalid", "mode": "park_understanding_benchmark_latest", "readiness_issues": [f"Invalid report: {reports[0]}"]}


def _readiness_issues(case_results: list[dict[str, Any]], average: float) -> list[str]:
    issues = []
    if average < 85:
        issues.append(f"Average understanding score {average} is below 85.")
    for row in case_results:
        if row.get("candidate_source") == "parkpulse_grounded_context_baseline":
            issues.append(f"{row['case_id']} used grounded baseline, not live LLM output.")
        if row["status"] != "passed":
            issues.append(f"{row['case_id']} failed with score {row['score']}.")
        for failure in row.get("hard_failures", []):
            issues.append(f"{row['case_id']}: {failure}")
    return sorted(set(issues))


def _report_id(case_results: list[dict[str, Any]], average: float) -> str:
    fingerprint = json.dumps(
        {
            "cases": [(row.get("case_id"), row.get("score"), row.get("status")) for row in case_results],
            "average": average,
            "created_at": _now_iso()[:10],
        },
        sort_keys=True,
    )
    return f"park_understanding_benchmark_{hashlib.sha1(fingerprint.encode('utf-8')).hexdigest()[:16]}"


def _write_report(report: dict[str, Any]) -> dict[str, Any]:
    directory = _reports_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{report['id']}.json"
    payload = {**report, "artifacts": {"report_path": str(path)}}
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, default=str)
    return {"status": "written", "report_path": str(path)}
