from __future__ import annotations

from copy import deepcopy
from typing import Any


def _bounded(value: float, low: float = 0, high: float = 100) -> float:
    return max(low, min(high, value))


def _norm(value: Any) -> str:
    return "".join(char for char in str(value or "").lower() if char.isalnum())


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _near(text: str, alias: str, terms: tuple[str, ...], window: int = 52) -> bool:
    index = text.find(alias)
    if index < 0:
        return False
    left = max(0, index - window)
    right = min(len(text), index + len(alias) + window)
    neighborhood = text[left:right]
    return any(term in neighborhood for term in terms)


def _prefixed_intent(text: str, alias: str, terms: tuple[str, ...], window: int = 30) -> bool:
    index = text.find(alias)
    if index < 0:
        return False
    prefix = text[max(0, index - window) : index]
    return any(term in prefix for term in terms)


def _capacity_after_mention(text: str, alias: str, terms: tuple[str, ...], window: int = 32) -> bool:
    index = text.find(alias)
    if index < 0:
        return False
    suffix = text[index + len(alias) : min(len(text), index + len(alias) + window)]
    return any(term in suffix for term in terms)


def _place_catalog(state: dict[str, Any]) -> list[dict[str, Any]]:
    flow = state.get("guestFlow", {}) if isinstance(state, dict) else {}
    places: list[dict[str, Any]] = []
    for zone in flow.get("zones", []) if isinstance(flow.get("zones"), list) else []:
        if isinstance(zone, dict):
            name = str(zone.get("name") or zone.get("id") or "")
            places.append(
                {
                    "id": str(zone.get("id") or name),
                    "name": name,
                    "kind": "zone",
                    "aliases": {name.lower(), str(zone.get("id") or "").lower(), str(zone.get("area") or "").lower()},
                }
            )
    for ride in flow.get("rides", []) if isinstance(flow.get("rides"), list) else []:
        if isinstance(ride, dict):
            name = str(ride.get("name") or ride.get("id") or "")
            places.append(
                {
                    "id": str(ride.get("id") or name),
                    "name": name,
                    "kind": "ride",
                    "zone_id": str(ride.get("zone") or ""),
                    "aliases": {name.lower(), str(ride.get("id") or "").lower(), str(ride.get("zoneName") or "").lower()},
                }
            )

    virtual_places = [
        ("foodCourt1", "Food Court A", "zone", ("food court a", "food court 1", "foodcourt a", "main food court")),
        ("arcadeZone", "Arcade Zone", "zone", ("arcade", "arcade zone")),
        ("indoorHub", "Indoor Ride Hub", "zone", ("indoor hub", "indoor ride hub", "inside rides")),
        ("indoorLaunch", "Indoor Launch", "ride", ("indoor launch",)),
        ("theaterB", "Theater B", "ride", ("theater b", "theater", "show")),
        ("coasterPlaza", "Coaster Plaza", "zone", ("coaster plaza", "dragon zone", "thrill zone")),
        ("firstAid", "First Aid", "service", ("first aid", "medical", "nurse station")),
        ("coveredPlaza", "Covered Plaza", "zone", ("covered plaza", "shelter", "covered route")),
    ]
    existing = {_norm(item.get("id")) for item in places}
    for place_id, name, kind, aliases in virtual_places:
        if _norm(place_id) in existing:
            for item in places:
                if _norm(item.get("id")) == _norm(place_id):
                    item["aliases"] = set(item.get("aliases", set())) | set(aliases)
                    if place_id == "foodCourt1":
                        item["name"] = "Food Court A"
                    break
            continue
        places.append({"id": place_id, "name": name, "kind": kind, "aliases": set(aliases) | {place_id.lower(), name.lower()}})
    return places


def _place_from_text(text: str, state: dict[str, Any], *, prefer_non_service: bool = False) -> dict[str, Any] | None:
    matches = []
    for place in _place_catalog(state):
        if prefer_non_service and place.get("kind") == "service":
            continue
        aliases = sorted((alias for alias in place.get("aliases", set()) if alias), key=len, reverse=True)
        for alias in aliases:
            if alias and alias in text:
                matches.append((len(alias), place))
                break
    if not matches:
        return None
    return sorted(matches, key=lambda item: item[0], reverse=True)[0][1]


def _place_after_location_marker(text: str, state: dict[str, Any]) -> dict[str, Any] | None:
    markers = (" near ", " at ", " by ", " around ", " beside ")
    best_tail = ""
    for marker in markers:
        index = text.rfind(marker)
        if index >= 0:
            best_tail = text[index + len(marker) : index + len(marker) + 96]
            break
    return _place_from_text(best_tail, state, prefer_non_service=True) if best_tail else None


def extract_operator_constraints(message: str, state: dict[str, Any], route: dict[str, Any] | None = None) -> dict[str, Any]:
    text = f" {(message or '').strip().lower()} "
    places = _place_catalog(state)
    avoid_terms = (
        "avoid",
        "do not overload",
        "don't overload",
        "dont overload",
        "do not send",
        "don't send",
        "dont send",
        "keep away",
        "no extra demand",
        "not to",
        "not indoor",
        "already full",
        "overloaded",
    )
    prefer_terms = (
        "send to",
        "send guests to",
        "send people to",
        "redirect to",
        "reroute to",
        "move to",
        "promote",
        "push to",
        "use",
    )

    avoid_zones: list[dict[str, Any]] = []
    preferred_destinations: list[dict[str, Any]] = []
    for place in places:
        aliases = sorted((alias for alias in place.get("aliases", set()) if len(alias) >= 3), key=len, reverse=True)
        if not aliases:
            continue
        mentioned_alias = next((alias for alias in aliases if f" {alias} " in text or alias in text), None)
        if not mentioned_alias:
            continue
        if _prefixed_intent(text, mentioned_alias, avoid_terms) or _capacity_after_mention(text, mentioned_alias, ("already full", "is full", "overloaded", "backed up")):
            avoid_zones.append(
                {
                    "id": place["id"],
                    "name": place["name"],
                    "kind": place.get("kind"),
                    "reason": f"Operator text says to avoid or not overload {place['name']}.",
                    "source": "operator_text",
                }
            )
        elif _prefixed_intent(text, mentioned_alias, prefer_terms, window=38):
            preferred_destinations.append(
                {
                    "id": place["id"],
                    "name": place["name"],
                    "kind": place.get("kind"),
                    "reason": f"Operator text prefers {place['name']} as a receiver destination.",
                    "source": "operator_text",
                }
            )

    if _contains_any(text, ("avoid food", "food already", "food court is full", "kitchen backed up")) and not any(_norm(item["id"]) == "foodcourt1" for item in avoid_zones):
        avoid_zones.append({"id": "foodCourt1", "name": "Food Court A", "kind": "zone", "reason": "Food demand should not receive more traffic.", "source": "operator_text"})
    if _contains_any(text, ("arcade", "games")) and not any(_norm(item["id"]) == "arcadezone" for item in avoid_zones + preferred_destinations):
        preferred_destinations.append({"id": "arcadeZone", "name": "Arcade Zone", "kind": "zone", "reason": "Operator mentioned arcade as a plausible relief destination.", "source": "operator_text"})
    if _contains_any(text, ("theater", "show")) and not any(_norm(item["id"]) == "theaterb" for item in avoid_zones + preferred_destinations):
        preferred_destinations.append({"id": "theaterB", "name": "Theater B", "kind": "ride", "reason": "Operator mentioned theater/show capacity.", "source": "operator_text"})

    incident_place = _place_after_location_marker(text, state) or _place_from_text(text, state, prefer_non_service=True) or {"id": "coasterPlaza", "name": "Coaster Plaza"}
    staff_moves: list[dict[str, Any]] = []
    safety_escalations: list[dict[str, Any]] = []
    if _contains_any(text, ("faint", "fainted", "collapse", "collapsed", "medical", "injury", "hurt", "first aid")):
        staff_moves.append(
            {
                "role": "medical",
                "count": 2,
                "from": "First Aid",
                "to": incident_place["name"],
                "reason": "Medical signal in operator text needs first-aid dispatch.",
                "deadlineMinutes": 3,
            }
        )
        safety_escalations.append({"type": "medical", "severity": "critical", "target": incident_place["name"], "requires_human_review": True})
    if _contains_any(text, ("handicapped", "wheelchair", "accessibility", "ada", "mobility")):
        staff_moves.append(
            {
                "role": "accessibility_support",
                "count": 1,
                "from": "Guest Services",
                "to": incident_place["name"],
                "reason": "Accessibility assistance requested.",
                "deadlineMinutes": 5,
            }
        )
    if _contains_any(text, ("panic", "evac", "evacuate", "crowd crush", "fight", "security")):
        staff_moves.append(
            {
                "role": "security",
                "count": 2,
                "from": "Security Base",
                "to": incident_place["name"],
                "reason": "Crowd safety signal needs security and controlled flow.",
                "deadlineMinutes": 4,
            }
        )
        safety_escalations.append({"type": "crowd_safety", "severity": "critical", "target": incident_place["name"], "requires_human_review": True})
    if _contains_any(text, ("staff", "worker", "crowd control", "move people")) and not any(item["role"] in {"security", "medical"} for item in staff_moves):
        staff_moves.append(
            {
                "role": "crowd_control",
                "count": 2,
                "from": "Entrance Plaza",
                "to": incident_place["name"],
                "reason": "Operator requested staff movement or crowd control.",
                "deadlineMinutes": 8,
            }
        )

    guest_segments = []
    if _contains_any(text, ("kid", "child", "children", "family", "families", "stroller")):
        guest_segments.append({"segment": "families_with_children", "constraint": "Prefer calm, indoor, low-wait destinations and avoid scary/high-pressure crowding."})
    if _contains_any(text, ("vip", "fast pass", "priority lane", "premium")):
        guest_segments.append({"segment": "priority_pass_guests", "constraint": "Balance paid priority value against standby fairness."})

    equipment_controls = []
    if _contains_any(text, ("hvac", "temperature", "comfort", "too hot", "too cold", "cool", "heat")):
        preferred_ids = {_norm(item["id"]) for item in preferred_destinations}
        zones = ["indoorHub", "arcadeZone"] if not preferred_ids else [item["id"] for item in preferred_destinations if item.get("kind") in {"zone", "ride"}][:3]
        equipment_controls.append(
            {
                "equipmentType": "hvac",
                "zones": zones or ["indoorHub", "arcadeZone"],
                "settings": {"indoorHubSetpointF": 72, "arcadeZoneSetpointF": 73, "shedNoncriticalLighting": True},
                "reason": "Operator text requested comfort or temperature control.",
            }
        )

    decision_rules = []
    if avoid_zones:
        decision_rules.append("Do not route new demand into avoided or already-overloaded zones.")
    if preferred_destinations:
        decision_rules.append("Prefer operator-named destinations if they remain under capacity.")
    if staff_moves:
        decision_rules.append("Dispatch role-specific worker tasks, not only guest messaging.")
    if equipment_controls:
        decision_rules.append("Issue equipment commands when comfort or facility controls are part of the request.")
    if guest_segments:
        decision_rules.append("Tune guest messaging to protected guest segments named by the operator.")

    return {
        "source": "operator_text_constraint_compiler",
        "command": message,
        "route": route or {},
        "avoid_zones": _dedupe_places(avoid_zones),
        "preferred_destinations": _dedupe_places(preferred_destinations),
        "required_staff_moves": staff_moves[:5],
        "equipment_controls": equipment_controls,
        "guest_segments": guest_segments,
        "safety_escalations": safety_escalations,
        "decision_rules": decision_rules,
        "requires_human_review": bool((route or {}).get("requires_human_review")) or bool(safety_escalations),
    }


def constraints_from_genai_understanding(understanding: dict[str, Any] | None, message: str, route: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(understanding, dict) or not understanding:
        return {}

    def place_rows(key: str) -> list[dict[str, Any]]:
        rows = []
        for item in understanding.get(key, []) if isinstance(understanding.get(key), list) else []:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "id": item.get("id") or item.get("name"),
                    "name": item.get("name") or item.get("id"),
                    "kind": item.get("kind", "zone"),
                    "reason": item.get("reason") or f"Gemini inferred {key.replace('_', ' ')} from the operator request.",
                    "source": "gemini_operator_understanding",
                }
            )
        return rows

    staff_moves = []
    for move in understanding.get("required_staff_moves", []) if isinstance(understanding.get("required_staff_moves"), list) else []:
        if not isinstance(move, dict):
            continue
        staff_moves.append(
            {
                "role": move.get("role", "crowd_control"),
                "count": move.get("count", 1),
                "from": move.get("from_location") or move.get("from") or "available pool",
                "to": move.get("to_location") or move.get("to") or "affected zone",
                "reason": move.get("reason") or "Gemini inferred a role-specific staff requirement.",
                "deadlineMinutes": move.get("deadline_minutes") or move.get("deadlineMinutes") or 8,
                "source": "gemini_operator_understanding",
            }
        )

    equipment_controls = []
    for control in understanding.get("equipment_controls", []) if isinstance(understanding.get("equipment_controls"), list) else []:
        if not isinstance(control, dict):
            continue
        equipment_controls.append(
            {
                "equipmentType": control.get("equipment_type") or control.get("equipmentType") or "control",
                "zones": control.get("zones", []) if isinstance(control.get("zones"), list) else [],
                "settings": control.get("settings", {}) if isinstance(control.get("settings"), dict) else {},
                "reason": control.get("reason") or "Gemini inferred an equipment-control action.",
                "source": "gemini_operator_understanding",
            }
        )

    guest_segments = [
        {"segment": str(item), "constraint": "Named or implied by Gemini operator understanding."}
        for item in understanding.get("guest_segments", [])
        if item
    ] if isinstance(understanding.get("guest_segments"), list) else []
    hard_constraints = [str(item) for item in understanding.get("hard_constraints", []) if item] if isinstance(understanding.get("hard_constraints"), list) else []
    soft_preferences = [str(item) for item in understanding.get("soft_preferences", []) if item] if isinstance(understanding.get("soft_preferences"), list) else []

    return {
        "source": "gemini_operator_understanding",
        "command": message,
        "route": route or {},
        "intent_summary": understanding.get("intent_summary"),
        "inferred_incident_type": understanding.get("inferred_incident_type"),
        "avoid_zones": _dedupe_places(place_rows("avoid_zones")),
        "preferred_destinations": _dedupe_places(place_rows("preferred_destinations")),
        "required_staff_moves": staff_moves[:6],
        "equipment_controls": equipment_controls[:4],
        "guest_segments": guest_segments,
        "safety_escalations": [
            {
                "type": "operator_high_risk",
                "severity": "critical",
                "target": understanding.get("inferred_incident_type", "operator request"),
                "requires_human_review": True,
            }
        ]
        if any("medical" in str(move.get("role", "")).lower() or "security" in str(move.get("role", "")).lower() for move in staff_moves)
        else [],
        "decision_rules": [*hard_constraints, *soft_preferences],
        "rejected_option": understanding.get("rejected_option"),
        "missing_facts": understanding.get("missing_facts", []) if isinstance(understanding.get("missing_facts"), list) else [],
        "requires_human_review": bool((route or {}).get("requires_human_review")) or bool(staff_moves and any(str(move.get("role", "")).lower() in {"medical", "security"} for move in staff_moves)),
    }


def merge_operator_constraints(local_constraints: dict[str, Any] | None, genai_constraints: dict[str, Any] | None) -> dict[str, Any]:
    local_constraints = local_constraints or {}
    genai_constraints = genai_constraints or {}
    if not genai_constraints:
        return local_constraints
    if not local_constraints:
        return genai_constraints

    merged = {**local_constraints, **{key: value for key, value in genai_constraints.items() if value not in (None, [], {})}}
    for key in ("avoid_zones", "preferred_destinations"):
        merged[key] = _dedupe_places([*(genai_constraints.get(key, []) or []), *(local_constraints.get(key, []) or [])])
    for key in ("required_staff_moves", "equipment_controls", "guest_segments", "safety_escalations", "decision_rules"):
        rows = [*(genai_constraints.get(key, []) or []), *(local_constraints.get(key, []) or [])]
        seen = set()
        deduped = []
        for row in rows:
            marker = str(row)
            if marker in seen:
                continue
            seen.add(marker)
            deduped.append(row)
        merged[key] = deduped
    merged["source"] = "gemini_operator_understanding+local_constraint_compiler"
    merged["requires_human_review"] = bool(local_constraints.get("requires_human_review") or genai_constraints.get("requires_human_review"))
    return merged


def _dedupe_places(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for item in items:
        key = _norm(item.get("id") or item.get("name"))
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _destination_for_place(place: dict[str, Any], state: dict[str, Any], avoid_keys: set[str]) -> dict[str, Any] | None:
    flow = state.get("guestFlow", {}) if isinstance(state, dict) else {}
    place_key = _norm(place.get("id") or place.get("name"))
    rides = [ride for ride in flow.get("rides", []) if isinstance(ride, dict)]
    normal_rides = [ride for ride in rides if ride.get("status") != "down"]
    matching = [
        ride
        for ride in normal_rides
        if place_key in {_norm(ride.get("id")), _norm(ride.get("name")), _norm(ride.get("zone")), _norm(ride.get("zoneName"))}
        and not _target_matches_keys({"destinationId": ride.get("id"), "destination": ride.get("name"), "zoneId": ride.get("zone")}, avoid_keys)
    ]
    if matching:
        ride = sorted(matching, key=lambda item: int(item.get("waitMins", 0) or 0))[0]
        return {
            "destinationId": ride.get("id"),
            "destination": ride.get("name"),
            "zoneId": ride.get("zone"),
            "share": 0.28,
            "currentWaitMins": ride.get("waitMins", 0),
            "status": ride.get("status", "normal"),
            "rationale": place.get("reason", "Operator-preferred destination."),
        }
    if place.get("kind") == "zone" and not _target_matches_keys({"zoneId": place.get("id"), "destination": place.get("name")}, avoid_keys):
        return {
            "destinationId": place.get("id"),
            "destination": place.get("name"),
            "zoneId": place.get("id"),
            "share": 0.22,
            "currentWaitMins": 12,
            "status": "normal",
            "rationale": place.get("reason", "Operator-preferred zone."),
        }
    return None


def _target_matches_keys(target: dict[str, Any], keys: set[str]) -> bool:
    target_keys = {
        _norm(target.get("destinationId")),
        _norm(target.get("destination")),
        _norm(target.get("zoneId")),
        _norm(target.get("zone")),
    }
    return bool(keys & target_keys)


def _objective_weights(constraints: dict[str, Any]) -> dict[str, float]:
    text = " ".join(
        str(value)
        for value in [
            constraints.get("command", ""),
            constraints.get("intent_summary", ""),
            constraints.get("inferred_incident_type", ""),
            constraints.get("decision_rules", []),
            constraints.get("guest_segments", []),
        ]
    ).lower()
    weights = {
        "safety": 0.24,
        "capacity_fit": 0.2,
        "guest_recovery": 0.18,
        "staff_burden": 0.16,
        "take_rate": 0.14,
        "energy_comfort": 0.08,
    }
    if any(term in text for term in ("medical", "faint", "injury", "panic", "evac", "security", "lost child")) or constraints.get("safety_escalations"):
        weights.update({"safety": 0.42, "capacity_fit": 0.12, "guest_recovery": 0.12, "staff_burden": 0.18, "take_rate": 0.08, "energy_comfort": 0.08})
    elif any(term in text for term in ("kids", "children", "family", "families", "accessibility", "wheelchair", "handicapped")):
        weights.update({"safety": 0.28, "capacity_fit": 0.16, "guest_recovery": 0.26, "staff_burden": 0.16, "take_rate": 0.08, "energy_comfort": 0.06})
    elif any(term in text for term in ("hvac", "temperature", "comfort", "too hot", "too cold")):
        weights.update({"safety": 0.22, "capacity_fit": 0.16, "guest_recovery": 0.16, "staff_burden": 0.12, "take_rate": 0.1, "energy_comfort": 0.24})
    elif any(term in text for term in ("take rate", "acceptance", "promotion", "positive response")):
        weights.update({"safety": 0.2, "capacity_fit": 0.18, "guest_recovery": 0.18, "staff_burden": 0.12, "take_rate": 0.24, "energy_comfort": 0.08})
    return weights


def _primary_operator_action(constraints: dict[str, Any], scenario_key: str) -> tuple[str, str, str]:
    roles = [str(move.get("role", "")).lower() for move in constraints.get("required_staff_moves", []) if isinstance(move, dict)]
    command = str(constraints.get("command", "")).lower()
    if any(role == "medical" for role in roles) or any(term in command for term in ("medical", "faint", "fainted", "injury", "collapsed")):
        return "medical", "dispatch", "Dispatch medical response and protect privacy"
    if any(role == "security" for role in roles) or any(term in command for term in ("panic", "evac", "security", "fight")):
        return "security", "respond", "Dispatch security and protect emergency routes"
    if any(role == "accessibility_support" for role in roles) or any(term in command for term in ("accessibility", "wheelchair", "handicapped", "mobility")):
        return "accessibility", "assist", "Dispatch accessibility support"
    if constraints.get("equipment_controls"):
        return "energy", "protect_hvac", "Adjust equipment controls requested by operator"
    if scenario_key == "food_spike":
        return "food", "suppress_item", "Balance food demand and inventory"
    return "ride", "reroute", "Custom guest-flow response"


def _fallback_targets(state: dict[str, Any], avoid_keys: set[str]) -> list[dict[str, Any]]:
    flow = state.get("guestFlow", {}) if isinstance(state, dict) else {}
    rides = [
        ride
        for ride in flow.get("rides", [])
        if isinstance(ride, dict)
        and ride.get("status") != "down"
        and not _target_matches_keys({"destinationId": ride.get("id"), "destination": ride.get("name"), "zoneId": ride.get("zone")}, avoid_keys)
    ]
    targets = []
    for ride in sorted(rides, key=lambda item: (int(item.get("waitMins", 0) or 0), -int(item.get("capacityPerHour", 0) or 0)))[:3]:
        targets.append(
            {
                "destinationId": ride.get("id"),
                "destination": ride.get("name"),
                "zoneId": ride.get("zone"),
                "share": 0.24,
                "currentWaitMins": ride.get("waitMins", 0),
                "status": ride.get("status", "normal"),
                "rationale": "Fallback low-wait destination after operator constraints removed unsafe targets.",
            }
        )
    return targets


def _normalize_target_mix(targets: list[dict[str, Any]], hold_share: float) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen = set()
    for target in targets:
        key = _norm(target.get("destinationId") or target.get("destination") or target.get("zoneId"))
        if not key or key in seen:
            continue
        seen.add(key)
        row = deepcopy(target)
        try:
            row["share"] = float(row.get("share", 0.22) or 0.22)
        except (TypeError, ValueError):
            row["share"] = 0.22
        unique.append(row)
    if not unique:
        return []
    max_share = _bounded(0.92 - hold_share, 0.38, 0.82)
    total = sum(float(item.get("share", 0) or 0) for item in unique)
    if total <= 0:
        for item in unique:
            item["share"] = round(max_share / len(unique), 2)
        return unique
    if total > max_share:
        for item in unique:
            item["share"] = round(float(item["share"]) / total * max_share, 2)
    return unique[:4]


def apply_operator_constraints_to_optimization(
    optimization: dict[str, Any],
    constraints: dict[str, Any] | None,
    state: dict[str, Any],
    scenario_key: str,
) -> dict[str, Any]:
    if not constraints or not any(
        constraints.get(key)
        for key in ("avoid_zones", "preferred_destinations", "required_staff_moves", "equipment_controls", "guest_segments", "safety_escalations")
    ):
        return optimization

    patched = deepcopy(optimization)
    avoid_keys = {_norm(item.get("id") or item.get("name")) for item in constraints.get("avoid_zones", []) if isinstance(item, dict)}
    preferred = [item for item in constraints.get("preferred_destinations", []) if isinstance(item, dict)]
    required_staff = [item for item in constraints.get("required_staff_moves", []) if isinstance(item, dict)]
    equipment = [item for item in constraints.get("equipment_controls", []) if isinstance(item, dict)]
    effects: list[str] = []
    rejected_options: list[dict[str, Any]] = []
    objective_weights = _objective_weights(constraints)
    primary_target, primary_action, primary_label = _primary_operator_action(constraints, scenario_key)

    candidates = patched.get("candidates", []) if isinstance(patched.get("candidates"), list) else []
    selected_id = str(patched.get("selected_plan_id") or "")
    if patched.get("selected_plan") and all(candidate is not patched["selected_plan"] for candidate in candidates):
        candidates.append(patched["selected_plan"])

    adjusted_candidates = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        item = deepcopy(candidate)
        action_mix = item.setdefault("action_mix", {})
        reroute = action_mix.setdefault("guest_reroute", {})
        raw_targets = reroute.get("target_mix", []) if isinstance(reroute.get("target_mix"), list) else []
        should_manage_reroute = bool(reroute.get("enabled")) or bool(raw_targets) or bool(preferred) or bool(avoid_keys) or bool(constraints.get("guest_segments"))
        removed: list[str] = []
        if should_manage_reroute:
            removed = [
                str(target.get("destination") or target.get("destinationId") or target.get("zoneId"))
                for target in raw_targets
                if isinstance(target, dict) and _target_matches_keys(target, avoid_keys)
            ]
            targets = [target for target in raw_targets if isinstance(target, dict) and not _target_matches_keys(target, avoid_keys)]
            for place in preferred:
                target = _destination_for_place(place, state, avoid_keys)
                if target and not any(_target_matches_keys(target, {_norm(row.get("destinationId") or row.get("destination") or row.get("zoneId"))}) for row in targets if isinstance(row, dict)):
                    targets.insert(0, target)
            if not targets and (preferred or raw_targets):
                targets = _fallback_targets(state, avoid_keys)
            hold_share = float(reroute.get("holdShare", 0.16) or 0.16)
            reroute["target_mix"] = _normalize_target_mix(targets, hold_share) if targets else []
            reroute["enabled"] = bool(targets) and bool(reroute.get("enabled", True))
            if constraints.get("guest_segments"):
                reroute["audienceStrategy"] = constraints["guest_segments"]
                reroute["offer"] = reroute.get("offer") or "Segment-aware app guidance toward calmer, lower-wait destinations."
        else:
            reroute["enabled"] = False
            reroute["target_mix"] = []
            reroute["holdShare"] = float(reroute.get("holdShare", 0.92) or 0.92)
        reroute["operatorConstraintAware"] = True
        action_mix["guest_reroute"] = reroute

        food = action_mix.setdefault("food", {})
        avoid_ids = [item.get("id") for item in constraints.get("avoid_zones", []) if isinstance(item, dict)]
        if avoid_ids:
            existing_food_avoid = food.get("avoidExtraDemandAt", []) if isinstance(food.get("avoidExtraDemandAt"), list) else []
            food["avoidExtraDemandAt"] = list(dict.fromkeys([*existing_food_avoid, *avoid_ids]))
        action_mix["food"] = food

        staffing = action_mix.setdefault("staffing", {})
        staff_moves = staffing.get("move_staff", []) if isinstance(staffing.get("move_staff"), list) else []
        for move in required_staff:
            move_key = (_norm(move.get("role")), _norm(move.get("to")))
            if not any((_norm(existing.get("role")), _norm(existing.get("to"))) == move_key for existing in staff_moves if isinstance(existing, dict)):
                staff_moves.append(
                    {
                        "role": move.get("role", "crowd_control"),
                        "count": move.get("count", 1),
                        "from": move.get("from", "available pool"),
                        "to": move.get("to", "affected zone"),
                        "reason": move.get("reason"),
                    }
                )
        staffing["move_staff"] = staff_moves
        staffing["protectedBreaks"] = bool(staffing.get("protectedBreaks", True))
        action_mix["staffing"] = staffing

        if equipment:
            facilities = action_mix.setdefault("facilities", {})
            hvac = facilities.setdefault("hvac", {})
            hvac["protectShelterComfort"] = True
            first = equipment[0]
            settings = first.get("settings", {}) if isinstance(first.get("settings"), dict) else {}
            hvac["indoorHubSetpointF"] = settings.get("indoorHubSetpointF", hvac.get("indoorHubSetpointF", 72))
            hvac["arcadeZoneSetpointF"] = settings.get("arcadeZoneSetpointF", hvac.get("arcadeZoneSetpointF", 73))
            hvac["shedNoncriticalLighting"] = settings.get("shedNoncriticalLighting", hvac.get("shedNoncriticalLighting", True))
            hvac["operatorRequestedZones"] = first.get("zones", [])
            hvac["operatorReason"] = first.get("reason")
            facilities["hvac"] = hvac
            action_mix["facilities"] = facilities

        item["action_mix"] = action_mix
        scorecard = item.setdefault("scorecard", {})
        original_score = float(scorecard.get("overall", 0) or 0)
        constraint_bonus = 6 + min(8, len(preferred) * 2 + len(required_staff) * 2 + len(equipment) * 2)
        if removed:
            rejected_options.append({"candidate": item.get("name"), "removed_targets": removed, "reason": "violated operator avoid/overload constraint"})
            effects.append(f"Removed {', '.join(removed[:2])} from {item.get('name', 'candidate')}.")
        if required_staff:
            effects.append(f"Added {len(required_staff)} role-specific worker dispatch requirement(s).")
        if equipment:
            effects.append("Added operator-requested facility control command.")
        scorecard["constraint_fit"] = 100
        weighted_score = (
            float(scorecard.get("safety", 80) or 80) * objective_weights["safety"]
            + float(scorecard.get("capacity_fit", 70) or 70) * objective_weights["capacity_fit"]
            + float(scorecard.get("take_rate_likelihood", 40) or 40) * objective_weights["take_rate"]
            + float(scorecard.get("staff_burden", 75) or 75) * objective_weights["staff_burden"]
            + float(scorecard.get("energy_comfort_balance", 75) or 75) * objective_weights["energy_comfort"]
            + float(scorecard.get("overall", 70) or 70) * objective_weights["guest_recovery"]
        )
        if constraints.get("safety_escalations") and required_staff:
            weighted_score += 10
        if equipment and action_mix.get("facilities", {}).get("hvac", {}).get("protectShelterComfort"):
            weighted_score += 5
        scorecard["request_objective_weights"] = objective_weights
        scorecard["request_weighted_score"] = round(_bounded(weighted_score))
        scorecard["overall"] = round(_bounded(max(original_score, weighted_score) + constraint_bonus))
        item["scorecard"] = scorecard
        item["constraint_effects"] = list(dict.fromkeys(effects))
        adjusted_candidates.append(item)

    ranked = sorted(adjusted_candidates, key=lambda item: item.get("scorecard", {}).get("overall", 0), reverse=True)
    selected = next((item for item in ranked if str(item.get("id")) == selected_id), ranked[0] if ranked else patched.get("selected_plan", {}))
    if ranked:
        selected = ranked[0]
    if isinstance(selected, dict):
        selected["name"] = f"Constraint-aware {selected.get('name', 'response mix')}"
        selected["selected_action"] = {
            "target": primary_target,
            "action": primary_action,
            "label": f"{primary_label}: {selected['name']}",
            "owner": "Decision Bridge",
            "expected_effect": "Applies operator text constraints before dispatching guest, worker, and equipment actions.",
            "risk_notes": constraints.get("decision_rules", []),
            "estimated_score": selected.get("scorecard", {}).get("overall"),
        }
    patched["candidates"] = ranked
    patched["selected_plan"] = selected
    patched["selected_plan_id"] = selected.get("id") if isinstance(selected, dict) else patched.get("selected_plan_id")
    if isinstance(selected, dict):
        patched["selected_action"] = selected.get("selected_action")
        patched["action_mix"] = selected.get("action_mix")
        patched["scorecard"] = selected.get("scorecard")
    patched["operator_constraints"] = constraints
    patched["operator_candidate_frame"] = {
        "mode": "constraint_compiled_plan_tournament",
        "selected_candidate_id": patched.get("selected_plan_id"),
        "rejected_options": rejected_options,
        "constraint_effects": list(dict.fromkeys(effects)),
        "decision_rules": constraints.get("decision_rules", []),
        "request_objective_weights": objective_weights,
        "primary_action": {"target": primary_target, "action": primary_action, "label": primary_label},
    }
    patched["decision_summary"] = "Selected a constraint-aware plan that customizes the response to the operator text before dispatch."
    return patched
