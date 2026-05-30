import json
from pathlib import Path
from typing import Any

from synthetic_park_knowledge import retrieve_synthetic_park_context


BASE_DIR = Path(__file__).resolve().parent
LEGACY_POLICY_BOOK = BASE_DIR / "policy_book.json"
POLICY_BOOK_DIR = BASE_DIR / "policy_books"
APPLIES_TO_KEYS = {"targets", "actions", "scenarios"}
CONDITION_KEYS = {"targets", "actions", "text_contains", "state", "unless_policy_status", "message"}
STATE_CONDITION_KEYS = {"any_ride_status", "any_zone_density_gte", "weather_storm_risk_gte"}
TOKEN_STOPWORDS = {"the", "and", "for", "with", "near", "from", "that", "this", "while", "into", "are", "was", "were", "has", "have", "had", "not", "but", "out", "all"}

SEMANTIC_PHRASES: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("child separated", "separated child", "kid separated", "separated kid", "can't find child", "cant find child", "missing youngster"), ("missing", "lost", "child", "kid", "guest_care", "security", "reunification")),
    (("restaurant", "dining", "eatery", "cafeteria"), ("food", "foodcourt", "food court", "restaurant")),
    (("blackout", "power cut", "lost power", "no power"), ("power", "outage", "lights", "energy", "facilities")),
    (("collapse", "collapsed", "unconscious", "can't breathe", "cant breathe"), ("medical", "first aid", "injury", "care")),
    (("bag left", "left bag", "backpack left", "unclaimed bag"), ("unattended", "bag", "suspicious", "security")),
    (("crowd packed", "people cannot move", "can't move", "cant move", "too packed"), ("crowd", "crush", "pinch", "density", "congestion")),
    (("app alert", "push alert", "notification", "mobile app"), ("push", "notification", "app", "message")),
    (("guest data", "personal info", "phone", "email"), ("pii", "privacy", "guest", "personal")),
    (("water rescue", "pool rescue", "swimmer rescue"), ("lifeguard", "rescue", "aquatic", "waterpark")),
]


def _load_json_file(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as policy_file:
        return json.load(policy_file)


def get_policy_books() -> dict[str, Any]:
    books: list[dict[str, Any]] = []

    if LEGACY_POLICY_BOOK.exists():
        books.append(
            {
                "source": LEGACY_POLICY_BOOK.name,
                "content": _load_json_file(LEGACY_POLICY_BOOK),
            }
        )

    if POLICY_BOOK_DIR.exists():
        for path in sorted(POLICY_BOOK_DIR.glob("*.json")):
            books.append(
                {
                    "source": f"{POLICY_BOOK_DIR.name}/{path.name}",
                    "content": _load_json_file(path),
                }
            )

    return {
        "policy_book_count": len(books),
        "policy_books": books,
    }


def _book_id(envelope: dict[str, Any]) -> str:
    content = envelope.get("content", {}) if isinstance(envelope, dict) else {}
    return str(content.get("policy_book_id") or envelope.get("source", ""))


def _collect_policy_refs(content: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for rule in content.get("decision_rules", []) or []:
        if isinstance(rule, dict) and rule.get("id"):
            refs.add(str(rule["id"]))
    judges = content.get("judges", {}) if isinstance(content.get("judges"), dict) else {}
    for judge in judges.values():
        if isinstance(judge, dict) and judge.get("policy_ref"):
            refs.add(str(judge["policy_ref"]))
    return refs


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _validate_applies_to(rule_id: str, applies_to: Any) -> list[str]:
    if applies_to is None:
        return []
    if not isinstance(applies_to, dict):
        return [f"{rule_id}.applies_to must be an object"]
    issues: list[str] = []
    unknown_keys = sorted(set(applies_to) - APPLIES_TO_KEYS)
    if unknown_keys:
        issues.append(f"{rule_id}.applies_to has unknown keys: {', '.join(unknown_keys)}")
    for key in APPLIES_TO_KEYS:
        if key in applies_to and not _is_string_list(applies_to[key]):
            issues.append(f"{rule_id}.applies_to.{key} must be a list of strings")
    return issues


def _validate_conditions(rule_id: str, field_name: str, conditions: Any) -> list[str]:
    if conditions is None:
        return []
    if not isinstance(conditions, list):
        return [f"{rule_id}.{field_name} must be a list"]
    issues: list[str] = []
    for index, condition in enumerate(conditions):
        prefix = f"{rule_id}.{field_name}[{index}]"
        if not isinstance(condition, dict):
            issues.append(f"{prefix} must be an object")
            continue
        unknown_keys = sorted(set(condition) - CONDITION_KEYS)
        if unknown_keys:
            issues.append(f"{prefix} has unknown keys: {', '.join(unknown_keys)}")
        if not isinstance(condition.get("message"), str) or not condition.get("message", "").strip():
            issues.append(f"{prefix}.message is required")
        for key in ("targets", "actions", "text_contains", "unless_policy_status"):
            if key in condition and not _is_string_list(condition[key]):
                issues.append(f"{prefix}.{key} must be a list of strings")
        state = condition.get("state")
        if state is not None:
            if not isinstance(state, dict):
                issues.append(f"{prefix}.state must be an object")
            else:
                unknown_state_keys = sorted(set(state) - STATE_CONDITION_KEYS)
                if unknown_state_keys:
                    issues.append(f"{prefix}.state has unknown keys: {', '.join(unknown_state_keys)}")
                for numeric_key in ("any_zone_density_gte", "weather_storm_risk_gte"):
                    if numeric_key in state and not isinstance(state[numeric_key], int):
                        issues.append(f"{prefix}.state.{numeric_key} must be an integer")
                if "any_ride_status" in state and not isinstance(state["any_ride_status"], str):
                    issues.append(f"{prefix}.state.any_ride_status must be a string")
    return issues


def _validate_policy_schema(policy_books: dict[str, Any], known_refs: set[str]) -> list[str]:
    issues: list[str] = []
    for envelope in policy_books.get("policy_books", []) or []:
        content = envelope.get("content", {}) or {}
        for rule in content.get("decision_rules", []) or []:
            if not isinstance(rule, dict):
                continue
            rule_id = str(rule.get("id") or f"{_book_id(envelope)}.unnamed_rule")
            issues.extend(_validate_applies_to(rule_id, rule.get("applies_to")))
            issues.extend(_validate_conditions(rule_id, "block_conditions", rule.get("block_conditions")))
            issues.extend(_validate_conditions(rule_id, "review_conditions", rule.get("review_conditions")))

        if _book_id(envelope) == "parkpulse_governance_index":
            default_refs = content.get("default_action_policy_refs", [])
            if default_refs and not _is_string_list(default_refs):
                issues.append("parkpulse_governance_index.default_action_policy_refs must be a list of strings")
            for ref in default_refs or []:
                if ref not in known_refs:
                    issues.append(f"Default action policy ref is missing: {ref}")
            for index, lane in enumerate(content.get("monitoring_lanes", []) or []):
                if not isinstance(lane, dict):
                    issues.append(f"parkpulse_governance_index.monitoring_lanes[{index}] must be an object")
                    continue
                ref = lane.get("primary_policy_ref")
                if not isinstance(ref, str) or not ref:
                    issues.append(f"parkpulse_governance_index.monitoring_lanes[{index}].primary_policy_ref is required")
                elif ref not in known_refs:
                    issues.append(f"Monitoring lane primary_policy_ref is missing: {ref}")
    return issues


def policy_reference_index(policy_books: dict[str, Any] | None = None) -> dict[str, Any]:
    policy_books = policy_books or get_policy_books()
    book_ids: set[str] = set()
    refs: set[str] = set()
    refs_by_book: dict[str, list[str]] = {}
    for envelope in policy_books.get("policy_books", []) or []:
        content = envelope.get("content", {}) or {}
        book_id = _book_id(envelope)
        book_ids.add(book_id)
        book_refs = sorted(_collect_policy_refs(content))
        refs.update(book_refs)
        refs_by_book[book_id] = book_refs
    return {
        "book_ids": sorted(book_ids),
        "policy_refs": sorted(refs),
        "refs_by_book": refs_by_book,
    }


def validate_policy_books(policy_books: dict[str, Any] | None = None) -> dict[str, Any]:
    policy_books = policy_books or get_policy_books()
    envelopes = policy_books.get("policy_books", []) or []
    ids = [_book_id(envelope) for envelope in envelopes]
    duplicate_ids = sorted({book_id for book_id in ids if ids.count(book_id) > 1})
    id_set = set(ids)
    governance = next(
        (
            envelope.get("content", {})
            for envelope in envelopes
            if _book_id(envelope) == "parkpulse_governance_index"
        ),
        {},
    )
    active_books = governance.get("active_policy_books", []) if isinstance(governance, dict) else []
    missing_active_books = sorted(str(book_id) for book_id in active_books if str(book_id) not in id_set)
    stale_terms: list[str] = []
    reference_index = policy_reference_index(policy_books)
    known_refs = set(reference_index["policy_refs"])
    required_action_refs = {
        "PARK-SAFE-001",
        "PARK-OPS-001",
        "PARK-EXP-001",
        "PARK-CARE-001",
        "PARK-LABOR-002",
        "PARK-MSG-003",
        "PARK-EQUIP-001",
        "PARK-EVENT-001",
        "PARK-EVENT-004",
        "PARK-FIN-001",
    }
    missing_required_refs = sorted(required_action_refs - known_refs)
    schema_issues = _validate_policy_schema(policy_books, known_refs)
    issues = []
    if duplicate_ids:
        issues.append(f"Duplicate policy_book_id values: {', '.join(duplicate_ids)}")
    if missing_active_books:
        issues.append(f"Active policy books missing from directory: {', '.join(missing_active_books)}")
    if missing_required_refs:
        issues.append(f"Required ParkPulse policy refs missing: {', '.join(missing_required_refs)}")
    issues.extend(schema_issues)
    return {
        "status": "clean" if not issues else "needs_cleanup",
        "issues": issues,
        "book_count": len(envelopes),
        "active_policy_books": active_books,
        "book_ids": reference_index["book_ids"],
        "policy_ref_count": len(reference_index["policy_refs"]),
        "policy_refs": reference_index["policy_refs"],
        "stale_terms": stale_terms,
        "missing_active_books": missing_active_books,
        "missing_required_refs": missing_required_refs,
    }


def load_policy_books_text() -> str:
    try:
        return json.dumps(get_policy_books(), indent=2)
    except Exception as error:
        return f"Policy books unavailable: {error}"


def _as_text_tokens(value: Any) -> set[str]:
    if isinstance(value, str):
        text = value.lower()
    elif isinstance(value, list):
        text = " ".join(str(item).lower() for item in value)
    else:
        text = json.dumps(value, sort_keys=True).lower() if value is not None else ""
    return {
        token
        for token in (raw.strip(".,:;!?()[]{}\"'") for raw in text.replace("_", " ").replace("-", " ").split())
        if len(token) >= 3 and token not in TOKEN_STOPWORDS
    }


def _semantic_text_tokens(value: Any) -> set[str]:
    if isinstance(value, str):
        text = value.lower()
    elif isinstance(value, list):
        text = " ".join(str(item).lower() for item in value)
    else:
        text = json.dumps(value, sort_keys=True).lower() if value is not None else ""
    tokens = _as_text_tokens(value)
    for phrases, expanded in SEMANTIC_PHRASES:
        if any(phrase in text for phrase in phrases):
            tokens |= _as_text_tokens(list(expanded))
    return tokens


def _case_priority(item: dict[str, Any]) -> int:
    text = " ".join(
        str(part).lower()
        for part in (
            item.get("id", ""),
            item.get("title", ""),
            " ".join(item.get("triggers", []) or []),
            " ".join(item.get("policy_refs", []) or []),
        )
    )
    if any(term in text for term in ("lost child", "missing child", "medical", "chest pain", "lifeguard", "near drowning", "crowd crush", "unattended bag", "security", "fight", "fire", "smoke", "evac")):
        return 10
    if any(term in text for term in ("restraint", "ride evacuation", "safety stop", "power outage", "key control", "chemical", "water quality")):
        return 20
    if any(term in text for term in ("accessibility", "heat illness", "lightning", "storm", "slip fall", "air quality")):
        return 30
    if any(term in text for term in ("staff", "labor", "certification", "fatigue")):
        return 40
    if any(term in text for term in ("queue", "food", "signage", "push notification", "retail", "compensation")):
        return 50
    return 60


def _actionable_entries(policy_books: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    policy_books = policy_books or get_policy_books()
    entries: list[dict[str, Any]] = []
    for envelope in policy_books.get("policy_books", []) or []:
        content = envelope.get("content", {}) if isinstance(envelope, dict) else {}
        if not isinstance(content, dict):
            continue
        book_id = _book_id(envelope)
        for rule in content.get("decision_rules", []) or []:
            if isinstance(rule, dict):
                entries.append(
                    {
                        "kind": "policy_rule",
                        "book_id": book_id,
                        "id": str(rule.get("id") or ""),
                        "title": str(rule.get("name") or rule.get("id") or "Policy rule"),
                        "policy_refs": [str(rule.get("id"))] if rule.get("id") else [],
                        "summary": str(rule.get("allowed_action") or rule.get("condition") or ""),
                        "blocked_actions": [str(rule.get("blocked_action"))] if rule.get("blocked_action") else [],
                        "required_evidence": [str(item) for item in rule.get("required_evidence", []) if item],
                        "raw": rule,
                    }
                )
        for case in content.get("action_cases", []) or []:
            if isinstance(case, dict):
                entries.append(
                    {
                        "kind": "action_case",
                        "book_id": book_id,
                        "id": str(case.get("id") or ""),
                        "title": str(case.get("title") or case.get("id") or "Action case"),
                        "policy_refs": [str(item) for item in case.get("policy_refs", []) if item],
                        "summary": " ".join(str(item) for item in case.get("action_plan", []) if item),
                        "triggers": [str(item) for item in case.get("triggers", []) if item],
                        "state_signals": [str(item) for item in case.get("state_signals", []) if item],
                        "recommended_primitives": [str(item) for item in case.get("recommended_primitives", []) if item],
                        "receiver_payloads": [item for item in case.get("receiver_payloads", []) if isinstance(item, dict)],
                        "blocked_actions": [str(item) for item in case.get("blocked_actions", []) if item],
                        "success_metric": str(case.get("success_metric") or ""),
                        "rollback_condition": str(case.get("rollback_condition") or ""),
                        "raw": case,
                    }
                )
    return entries


def operational_doctrine_index(policy_books: dict[str, Any] | None = None) -> dict[str, Any]:
    policy_books = policy_books or get_policy_books()
    action_primitives: list[dict[str, Any]] = []
    action_cases: list[dict[str, Any]] = []
    for envelope in policy_books.get("policy_books", []) or []:
        content = envelope.get("content", {}) if isinstance(envelope, dict) else {}
        if not isinstance(content, dict):
            continue
        action_primitives.extend(item for item in content.get("action_primitives", []) or [] if isinstance(item, dict))
        action_cases.extend(item for item in content.get("action_cases", []) or [] if isinstance(item, dict))
    return {
        "policy_book_count": policy_books.get("policy_book_count", 0),
        "action_case_count": len(action_cases),
        "action_primitive_count": len(action_primitives),
        "action_cases": action_cases,
        "action_primitives": action_primitives,
        "policy_refs": policy_reference_index(policy_books)["policy_refs"],
    }


def retrieve_operational_doctrine(message: str, compact_state: dict[str, Any] | None = None, limit: int = 5) -> dict[str, Any]:
    compact_state = compact_state or {}
    lowered_message = (message or "").lower()
    query_tokens = _semantic_text_tokens(message)
    synthetic_context = retrieve_synthetic_park_context(message, compact_state, limit=limit)
    primary_synthetic = synthetic_context.get("primary_example") if isinstance(synthetic_context.get("primary_example"), dict) else {}
    if primary_synthetic:
        query_tokens |= _semantic_text_tokens(
            [
                primary_synthetic.get("domain"),
                primary_synthetic.get("expected_owner"),
                primary_synthetic.get("expected_case_id"),
                primary_synthetic.get("expected_action"),
                primary_synthetic.get("hard_constraints", []),
                primary_synthetic.get("evaluation_assertions", []),
            ]
        )
    query_tokens |= _semantic_text_tokens(compact_state.get("scenario"))
    query_tokens |= _semantic_text_tokens(compact_state.get("active_policy"))
    for zone in compact_state.get("top_zones", []) or []:
        if isinstance(zone, dict) and int(zone.get("density") or 0) >= 80:
            query_tokens |= _semantic_text_tokens([zone.get("id"), zone.get("name"), "crowd", "density", "queue"])
    for ride in compact_state.get("constrained_rides", []) or []:
        if isinstance(ride, dict):
            query_tokens |= _semantic_text_tokens([ride.get("id"), ride.get("name"), ride.get("status"), "ride", "queue"])
    weather = compact_state.get("weather", {}) if isinstance(compact_state.get("weather"), dict) else {}
    if int(weather.get("stormRisk") or 0) >= 55 or int(weather.get("heatIndexF") or 0) >= 95:
        query_tokens |= {"weather", "storm", "heat", "shelter"}
    staffing = compact_state.get("staffing", {}) if isinstance(compact_state.get("staffing"), dict) else {}
    if int(staffing.get("openCallouts") or 0) > 0:
        query_tokens |= {"staff", "coverage", "break", "callout"}

    scored: list[dict[str, Any]] = []
    for entry in _actionable_entries():
        searchable = [
            entry.get("id"),
            entry.get("title"),
            entry.get("summary"),
            entry.get("book_id"),
            entry.get("kind"),
            entry.get("triggers", []),
            entry.get("state_signals", []),
            entry.get("policy_refs", []),
            entry.get("recommended_primitives", []),
            entry.get("blocked_actions", []),
        ]
        entry_tokens: set[str] = set()
        for value in searchable:
            entry_tokens |= _semantic_text_tokens(value)
        overlap = sorted(query_tokens & entry_tokens)
        score = len(overlap) * 10
        if entry.get("kind") == "action_case":
            score += 6
            exact_triggers = [
                trigger
                for trigger in entry.get("triggers", []) or []
                if isinstance(trigger, str) and trigger.lower() in lowered_message
            ]
            score += sum(1000 if " " in trigger.strip() else 120 for trigger in exact_triggers)
            if exact_triggers:
                overlap = sorted(set([*overlap, *exact_triggers]))
            high_risk_terms = {"child", "kid", "missing", "lost", "security", "medical", "injury", "rescue", "fire", "evac", "unattended", "suspicious", "power", "outage", "lights", "key", "chemical"}
            if _case_priority(entry) <= 20 and (query_tokens & entry_tokens & high_risk_terms):
                score += 260
        if "policy" in query_tokens and entry.get("kind") == "policy_rule":
            score += 5
        if score > 0:
            scored.append({**entry, "score": score, "matched_terms": overlap[:12], "priority": _case_priority(entry)})

    scored.sort(key=lambda item: (int(item.get("score") or 0), 100 - int(item.get("priority") or 99), 1 if item.get("kind") == "action_case" else 0), reverse=True)
    selected = scored[: max(1, limit)]
    primary_case = next((item for item in selected if item.get("kind") == "action_case"), selected[0] if selected else None)
    policy_refs: list[str] = []
    for item in selected:
        for ref in item.get("policy_refs", []) or []:
            if ref not in policy_refs:
                policy_refs.append(str(ref))
    return {
        "retrieval_status": "matched" if selected else "no_match",
        "query_terms": sorted(query_tokens)[:24],
        "primary_case": primary_case,
        "matches": selected,
        "policy_refs": policy_refs[:12],
        "synthetic_context": synthetic_context,
        "doctrine_index": {
            "action_case_count": operational_doctrine_index()["action_case_count"],
            "action_primitive_count": operational_doctrine_index()["action_primitive_count"],
        },
    }


def interpret_policy_for_action(
    message: str,
    compact_state: dict[str, Any] | None = None,
    doctrine: dict[str, Any] | None = None,
) -> dict[str, Any]:
    compact_state = compact_state or {}
    doctrine = doctrine or retrieve_operational_doctrine(message, compact_state)
    primary_case = doctrine.get("primary_case") if isinstance(doctrine.get("primary_case"), dict) else {}
    matches = [item for item in doctrine.get("matches", []) if isinstance(item, dict)]
    policy_matches = [item for item in matches if item.get("kind") == "policy_rule"]
    case_matches = [item for item in matches if item.get("kind") == "action_case"]
    prioritized_cases = sorted(case_matches[:6], key=lambda item: (_case_priority(item), -int(item.get("score") or 0)))
    conflict_analysis = {
        "detected": len(prioritized_cases) > 1,
        "priority_order": [
            {
                "case_id": item.get("id"),
                "title": item.get("title"),
                "priority": _case_priority(item),
                "score": item.get("score"),
                "reason": "Safety/security/medical/access risks are handled before queue, food, comfort, or comms optimization."
                if _case_priority(item) <= 30
                else "Operational pressure case is secondary unless no higher-risk incident is present.",
            }
            for item in prioritized_cases[:5]
        ],
        "selected_case_id": primary_case.get("id") if primary_case else None,
    }
    relevant_books = list(dict.fromkeys(str(item.get("book_id")) for item in matches if item.get("book_id")))
    synthetic_context = doctrine.get("synthetic_context") if isinstance(doctrine.get("synthetic_context"), dict) else {}
    primary_synthetic = synthetic_context.get("primary_example") if isinstance(synthetic_context.get("primary_example"), dict) else {}
    applicable_rules = [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "book_id": item.get("book_id"),
            "policy_refs": item.get("policy_refs", []),
            "allowed_guidance": item.get("summary"),
            "blocked_actions": item.get("blocked_actions", []),
            "required_evidence": item.get("required_evidence", []),
        }
        for item in policy_matches[:6]
    ]
    case_plan = [str(item) for item in primary_case.get("raw", {}).get("action_plan", []) if item] if primary_case else []
    case_blocked = [str(item) for item in primary_case.get("blocked_actions", []) if item] if primary_case else []
    case_payloads = [item for item in primary_case.get("receiver_payloads", []) if isinstance(item, dict)] if primary_case else []
    primitive_actions = [str(item) for item in primary_case.get("recommended_primitives", []) if item] if primary_case else []
    allowed_actions = list(dict.fromkeys([*primitive_actions, *[str(item.get("label") or item.get("id")) for item in case_payloads if item], *case_plan[:4]]))
    blocked_actions = list(
        dict.fromkeys(
            [
                *case_blocked,
                *[str(action) for item in applicable_rules for action in item.get("blocked_actions", []) if action],
            ]
        )
    )
    required_evidence = list(
        dict.fromkeys(
            [
                "operator request",
                "live park state",
                "matched policy book",
                *(["matched synthetic park example"] if primary_synthetic else []),
                *[str(evidence) for item in applicable_rules for evidence in item.get("required_evidence", []) if evidence],
                *([str(signal) for signal in primary_case.get("state_signals", []) if signal] if primary_case else []),
            ]
        )
    )
    approval_required = any(
        term in " ".join([message, primary_case.get("title", ""), " ".join(primary_case.get("policy_refs", []) if primary_case else [])]).lower()
        for term in ("medical", "security", "accessibility", "emergency", "labor", "staff", "fire", "evac")
    )
    candidate_actions = []
    for index, step in enumerate(case_plan[:5], start=1):
        blocked = any(blocked.lower() in step.lower() for blocked in case_blocked)
        candidate_actions.append(
            {
                "id": f"candidate_{index}",
                "label": step,
                "source": primary_case.get("id") if primary_case else "policy_rule",
                "policy_refs": primary_case.get("policy_refs", []) if primary_case else doctrine.get("policy_refs", []),
                "verdict": "rejected" if blocked else "candidate",
                "rejection_reason": "Conflicts with blocked action from matched case." if blocked else None,
            }
        )
    for blocked in blocked_actions[:4]:
        candidate_actions.append(
            {
                "id": f"blocked_{len(candidate_actions) + 1}",
                "label": blocked,
                "source": "policy_blocked_action",
                "policy_refs": doctrine.get("policy_refs", []),
                "verdict": "rejected",
                "rejection_reason": "Explicitly blocked by relevant policy/case guidance.",
            }
        )
    selected_action = next((item for item in candidate_actions if item.get("verdict") == "candidate"), None)
    policy_refs = list(dict.fromkeys([*(primary_case.get("policy_refs", []) if primary_case else []), *doctrine.get("policy_refs", [])]))
    steps = [
        {"step": 1, "name": "Read operator request", "status": "complete", "output": message},
        {"step": 2, "name": "Read live park state", "status": "complete", "output": compact_state.get("scenario") or "Live park state"},
        {"step": 3, "name": "Retrieve policy books", "status": doctrine.get("retrieval_status") or "complete", "output": relevant_books},
        {"step": 4, "name": "Interpret applicable guidance", "status": "complete", "output": {"allowed": allowed_actions[:6], "blocked": blocked_actions[:6]}},
        {"step": 5, "name": "Create candidate actions", "status": "complete", "output": [item.get("label") for item in candidate_actions if item.get("verdict") == "candidate"][:5]},
        {"step": 6, "name": "Reject blocked actions", "status": "complete", "output": [item.get("label") for item in candidate_actions if item.get("verdict") == "rejected"][:5]},
        {"step": 7, "name": "Select safest useful action", "status": "complete" if selected_action else "needs_review", "output": {"selected_action": selected_action, "conflict_priority": conflict_analysis}},
        {"step": 8, "name": "Approval or execution gate", "status": "approval_required" if approval_required else "prepared", "output": "human approval required" if approval_required else "operator apply turn required before mutation"},
        {"step": 9, "name": "Trace outcome and evaluation", "status": "prepared", "output": primary_case.get("success_metric") if primary_case else "Trace selected action against policy refs."},
    ]
    return {
        "status": "interpreted" if matches else "no_policy_match",
        "primary_case_id": primary_case.get("id") if primary_case else None,
        "primary_case_title": primary_case.get("title") if primary_case else None,
        "relevant_policy_books": relevant_books,
        "applicable_rules": applicable_rules,
        "allowed_actions": allowed_actions[:10],
        "blocked_actions": blocked_actions[:10],
        "required_evidence": required_evidence[:12],
        "candidate_actions": candidate_actions[:12],
        "selected_action": selected_action,
        "conflict_analysis": conflict_analysis,
        "approval_required": approval_required,
        "policy_refs": policy_refs[:12],
        "success_metric": primary_case.get("success_metric") if primary_case else None,
        "rollback_condition": primary_case.get("rollback_condition") if primary_case else None,
        "steps": steps,
        "case_matches": case_matches[:4],
        "synthetic_context": synthetic_context,
    }
