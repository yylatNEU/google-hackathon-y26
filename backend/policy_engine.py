from __future__ import annotations

from functools import lru_cache
from typing import Any

from policy_loader import get_policy_books, policy_reference_index


DEFAULT_ACTION_REFS = ("PARK-OPS-001", "PARK-EXP-001", "PARK-CARE-001")
DEFAULT_ACTION_CHECKS = ("source-grounded", "capacity-aware", "customer-care-approved")


def _text_for_action(action_doc: dict[str, Any]) -> str:
    park_action = action_doc.get("park_action", {}) or {}
    values = [
        action_doc.get("title", ""),
        action_doc.get("expected_impact", ""),
        action_doc.get("owner", ""),
        park_action.get("target", ""),
        park_action.get("action", ""),
    ]
    return " ".join(str(value).lower() for value in values)


def _park_action(action_doc: dict[str, Any]) -> tuple[str, str]:
    park_action = action_doc.get("park_action", {}) or {}
    return str(park_action.get("target", "")), str(park_action.get("action", ""))


def _normalized_action_doc(action_doc: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(action_doc, dict):
        return {}
    if isinstance(action_doc.get("park_action"), dict):
        return action_doc
    if "target" not in action_doc and "action" not in action_doc:
        return action_doc
    return {
        **action_doc,
        "park_action": {
            "target": action_doc.get("target", ""),
            "action": action_doc.get("action", ""),
        },
    }


def _scenario_key(scenario: dict[str, Any] | str | None) -> str:
    return scenario if isinstance(scenario, str) else str((scenario or {}).get("key", ""))


class PolicyEngine:
    def __init__(self, policy_books: dict[str, Any] | None = None):
        self.policy_books = policy_books or get_policy_books()
        self.reference_index = policy_reference_index(self.policy_books)
        self.known_refs = set(self.reference_index.get("policy_refs", []))
        self.books_by_id = self._books_by_id()
        self.rules_by_ref = self._rules_by_ref()
        self.governance_index = self.books_by_id.get("parkpulse_governance_index", {}).get("content", {}) or {}

    def _books_by_id(self) -> dict[str, dict[str, Any]]:
        books: dict[str, dict[str, Any]] = {}
        for envelope in self.policy_books.get("policy_books", []) or []:
            content = envelope.get("content", {}) or {}
            book_id = str(content.get("policy_book_id") or envelope.get("source", ""))
            books[book_id] = {"source": envelope.get("source", ""), "content": content}
        return books

    def _rules_by_ref(self) -> dict[str, dict[str, Any]]:
        rules: dict[str, dict[str, Any]] = {}
        for book_id, envelope in self.books_by_id.items():
            content = envelope.get("content", {}) or {}
            for rule in content.get("decision_rules", []) or []:
                if isinstance(rule, dict) and rule.get("id"):
                    rules[str(rule["id"])] = {
                        **rule,
                        "policy_book_id": book_id,
                        "source": envelope.get("source", ""),
                    }
        return rules

    def get_rule(self, policy_ref: str) -> dict[str, Any] | None:
        return self.rules_by_ref.get(policy_ref)

    def _default_action_refs(self) -> set[str]:
        configured = self.governance_index.get("default_action_policy_refs", [])
        refs = configured if isinstance(configured, list) and configured else list(DEFAULT_ACTION_REFS)
        return {str(ref) for ref in refs if str(ref) in self.known_refs}

    def _rule_applies(self, rule: dict[str, Any], target: str, action: str, scenario: dict[str, Any] | str | None = None) -> bool:
        applies_to = rule.get("applies_to", {}) if isinstance(rule.get("applies_to"), dict) else {}
        if not applies_to:
            return False
        targets = {str(value) for value in applies_to.get("targets", []) or []}
        actions = {str(value) for value in applies_to.get("actions", []) or []}
        scenarios = {str(value) for value in applies_to.get("scenarios", []) or []}
        scenario_value = _scenario_key(scenario)
        if targets and target not in targets:
            return False
        if actions and action and action not in actions:
            return False
        if scenarios and scenario_value not in scenarios:
            return False
        return bool(targets or actions or scenarios)

    def refs_for_action(self, target: str, action: str, scenario: dict[str, Any] | str | None = None) -> list[str]:
        refs = self._default_action_refs()
        for ref, rule in self.rules_by_ref.items():
            if self._rule_applies(rule, target, action, scenario):
                refs.add(ref)
        return sorted(ref for ref in refs if ref in self.known_refs)

    def policy_compliance_for_action(
        self,
        target: str,
        action: str,
        *,
        status: str = "allowed",
        checks: list[str] | tuple[str, ...] | None = None,
        scenario: dict[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "checks": list(checks or DEFAULT_ACTION_CHECKS),
            "policy_refs": self.refs_for_action(target, action, scenario),
        }

    def validate_action_refs(self, action_doc: dict[str, Any], scenario: dict[str, Any] | str | None = None) -> dict[str, Any]:
        normalized = _normalized_action_doc(action_doc)
        target, action = _park_action(normalized)
        expected_refs = self.refs_for_action(target, action, scenario) if target or action else []
        cited_refs = list(dict.fromkeys(str(ref) for ref in (normalized.get("policy_compliance", {}) or {}).get("policy_refs", []) or []))
        known_cited_refs = [ref for ref in cited_refs if ref in self.known_refs]
        unknown_refs = sorted(ref for ref in cited_refs if ref not in self.known_refs)
        missing_refs = sorted(ref for ref in expected_refs if ref not in known_cited_refs)
        unexpected_refs = sorted(ref for ref in known_cited_refs if ref not in expected_refs)
        issues: list[str] = []
        if not target or not action:
            issues.append("Action is missing executable ParkPulse target/action.")
        if unknown_refs:
            issues.append(f"Unknown policy refs: {', '.join(unknown_refs)}.")
        if missing_refs:
            issues.append(f"Missing required policy refs: {', '.join(missing_refs)}.")
        if unexpected_refs:
            issues.append(f"Unexpected policy refs for {target}/{action}: {', '.join(unexpected_refs)}.")
        return {
            "status": "invalid" if issues else "clean",
            "target": target,
            "action": action,
            "scenario_key": _scenario_key(scenario),
            "expected_policy_refs": expected_refs,
            "cited_policy_refs": cited_refs,
            "missing_policy_refs": missing_refs,
            "unknown_policy_refs": unknown_refs,
            "unexpected_policy_refs": unexpected_refs,
            "issues": issues,
        }

    def validate_plan(self, action_plan: dict[str, Any]) -> dict[str, Any]:
        scenario = action_plan.get("scenario", {}) if isinstance(action_plan, dict) else {}
        recommended_actions = action_plan.get("recommended_actions", []) if isinstance(action_plan, dict) else []
        action_results = [
            {
                "action_id": action.get("action_id", f"recommended-{index}") if isinstance(action, dict) else f"recommended-{index}",
                **self.validate_action_refs(action, scenario),
            }
            for index, action in enumerate(recommended_actions if isinstance(recommended_actions, list) else [])
        ]
        selected_result = self.validate_action_refs(action_plan.get("selected_action", {}) if isinstance(action_plan, dict) else {}, scenario)
        issues = [f"selected_action: {issue}" for issue in selected_result["issues"]]
        for result in action_results:
            issues.extend(f"{result['action_id']}: {issue}" for issue in result["issues"])
        return {
            "status": "invalid" if issues else "clean",
            "scenario_key": _scenario_key(scenario),
            "selected_action": selected_result,
            "recommended_actions": action_results,
            "issues": issues,
        }

    def policy_context_for_planner(self, scenario: dict[str, Any] | str | None = None) -> dict[str, Any]:
        scenario_key = scenario if isinstance(scenario, str) else (scenario or {}).get("key", "")
        targets = [
            "ride",
            "traffic",
            "staff",
            "food",
            "energy",
            "event",
            "guest",
            "medical",
            "accessibility",
            "security",
            "guest_services",
            "signage",
            "queue_gate",
            "entertainment",
            "maintenance",
        ]
        refs = self._default_action_refs()
        for target in targets:
            refs.update(self.refs_for_action(target, "", scenario_key))
        rules = []
        for ref in sorted(refs):
            rule = self.get_rule(ref)
            if not rule:
                continue
            rules.append(
                {
                    "id": ref,
                    "name": rule.get("name", ""),
                    "policy_book_id": rule.get("policy_book_id", ""),
                    "allowed_action": rule.get("allowed_action", ""),
                    "blocked_action": rule.get("blocked_action", ""),
                    "human_review_if": rule.get("human_review_if", []),
                }
            )
        return {"scenario_key": scenario_key, "policy_refs": sorted(refs), "rules": rules}

    def _state_condition_matches(self, state_condition: dict[str, Any], park_state: dict[str, Any]) -> bool:
        weather = park_state.get("weather", {}) if isinstance(park_state, dict) else {}
        flow = park_state.get("guestFlow", {}) if isinstance(park_state, dict) else {}
        rides = flow.get("rides", []) if isinstance(flow, dict) else []
        zones = flow.get("zones", []) if isinstance(flow, dict) else []
        if "any_ride_status" in state_condition:
            expected = str(state_condition["any_ride_status"])
            if not any(isinstance(ride, dict) and str(ride.get("status", "")) == expected for ride in rides):
                return False
        if "any_zone_density_gte" in state_condition:
            minimum = int(state_condition["any_zone_density_gte"])
            if not any(isinstance(zone, dict) and int(zone.get("density", 0) or 0) >= minimum for zone in zones):
                return False
        if "weather_storm_risk_gte" in state_condition:
            minimum = int(state_condition["weather_storm_risk_gte"])
            if int(weather.get("stormRisk", 0) or 0) < minimum:
                return False
        return True

    def _condition_matches(
        self,
        condition: dict[str, Any],
        *,
        target: str,
        action: str,
        text: str,
        park_state: dict[str, Any],
        compliance_status: str,
    ) -> bool:
        targets = {str(value) for value in condition.get("targets", []) or []}
        actions = {str(value) for value in condition.get("actions", []) or []}
        text_patterns = [str(value).lower() for value in condition.get("text_contains", []) or []]
        excluded_statuses = {str(value) for value in condition.get("unless_policy_status", []) or []}
        if targets and target not in targets:
            return False
        if actions and action not in actions:
            return False
        if text_patterns and not any(pattern in text for pattern in text_patterns):
            return False
        if excluded_statuses and compliance_status in excluded_statuses:
            return False
        state_condition = condition.get("state", {}) if isinstance(condition.get("state"), dict) else {}
        if state_condition and not self._state_condition_matches(state_condition, park_state):
            return False
        return bool(targets or actions or text_patterns or state_condition)

    def _eval_threshold_findings(self, eval_result: dict[str, Any] | None) -> list[dict[str, Any]]:
        evals = {item.get("label", "").lower(): int(item.get("score", 0) or 0) for item in (eval_result or {}).get("evals", []) or []}
        findings: list[dict[str, Any]] = []
        for lane in self.governance_index.get("monitoring_lanes", []) or []:
            if not isinstance(lane, dict):
                continue
            threshold = lane.get("eval_threshold", {}) if isinstance(lane.get("eval_threshold"), dict) else {}
            label = str(threshold.get("label", "")).lower()
            if not label or label not in evals:
                continue
            minimum = int(threshold.get("minimum", 0) or 0)
            if evals[label] >= minimum:
                continue
            message = str(threshold.get("failure") or threshold.get("warning") or f"{threshold.get('label')} score is below {minimum}.")
            severity = "block" if threshold.get("failure") else "review"
            policy_ref = str(lane.get("primary_policy_ref", ""))
            findings.append({"severity": severity, "message": message, "policy_refs": [policy_ref] if policy_ref in self.known_refs else []})
        return findings

    def evaluate_action(
        self,
        action_doc: dict[str, Any],
        park_state: dict[str, Any] | None = None,
        eval_result: dict[str, Any] | None = None,
        scenario: dict[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        park_state = park_state or {}
        target, action = _park_action(action_doc)
        resolved_refs = self.refs_for_action(target, action, scenario)
        cited_refs = list((action_doc.get("policy_compliance", {}) or {}).get("policy_refs", []) or [])
        unknown_refs = sorted(ref for ref in cited_refs if ref not in self.known_refs)
        findings: list[dict[str, Any]] = []

        def add(severity: str, message: str, refs: list[str]) -> None:
            finding = {"severity": severity, "message": message, "policy_refs": [ref for ref in refs if ref in self.known_refs]}
            if finding not in findings:
                findings.append(finding)

        text = _text_for_action(action_doc)
        compliance_status = str((action_doc.get("policy_compliance", {}) or {}).get("status", ""))

        if unknown_refs:
            add("block", f"Unknown policy refs: {', '.join(unknown_refs)}", [])
        if not action_doc.get("park_action"):
            add("block", "Action has no executable ParkPulse target/action.", ["PARK-OPS-001"])

        safety_blockers = [
            (
                target == "ride" and (action in {"reopen", "test_dispatch", "reduce_inspection"} or "reopen" in text),
                "Ride action requires certified maintenance clearance before execution.",
                ["PARK-SAFE-001"],
            ),
            (
                target == "medical" and any(term in text for term in ("diagnose", "diagnosis", "patient name", "guest medical details")),
                "Medical support must not diagnose guests or expose individual health details.",
                ["PARK-CARE-002"],
            ),
            (
                target in {"security", "guest_services"} and any(term in text for term in ("detain", "detention", "restrain", "enforce")),
                "Security actions remain decision-support only and require human incident command.",
                ["PARK-CARE-002"],
            ),
            (
                any(term in text for term in ("evacuation", "evacuate", "emergency route", "emergency egress")) and target in {"queue_gate", "traffic", "signage"},
                "ParkPulse cannot control evacuation authority or block emergency egress paths.",
                ["PARK-EQUIP-002", "PARK-SAFE-003"],
            ),
            (
                "uncertified" in text and target in {"staff", "medical", "security", "maintenance", "ride"},
                "Move only certified or role-compatible staff; uncertified safety-critical assignments are blocked.",
                ["PARK-LABOR-001"],
            ),
            (
                target == "maintenance" and action in {"override_safety", "reopen_ride", "clear_fault"},
                "ParkPulse cannot override maintenance or safety-critical ride controls.",
                ["PARK-EQUIP-002", "PARK-SAFE-001"],
            ),
        ]
        for matched, message, refs in safety_blockers:
            if matched:
                add("block", message, refs)

        for ref in sorted(set(resolved_refs) | {ref for ref in cited_refs if ref in self.known_refs}):
            rule = self.get_rule(ref) or {}
            for condition in rule.get("block_conditions", []) or []:
                if isinstance(condition, dict) and self._condition_matches(
                    condition,
                    target=target,
                    action=action,
                    text=text,
                    park_state=park_state,
                    compliance_status=compliance_status,
                ):
                    add("block", str(condition.get("message") or rule.get("blocked_action") or "Policy rule blocked this action."), [ref])
            for condition in rule.get("review_conditions", []) or []:
                if isinstance(condition, dict) and self._condition_matches(
                    condition,
                    target=target,
                    action=action,
                    text=text,
                    park_state=park_state,
                    compliance_status=compliance_status,
                ):
                    add("review", str(condition.get("message") or "Policy rule requires human review."), [ref])

        for finding in self._eval_threshold_findings(eval_result):
            add(str(finding["severity"]), str(finding["message"]), list(finding.get("policy_refs", [])))

        violations = [item["message"] for item in findings if item["severity"] == "block"]
        warnings = [item["message"] for item in findings if item["severity"] == "review"]
        if violations:
            status = "blocked"
        elif warnings:
            status = "review"
        else:
            status = "clear"
        return {
            "status": status,
            "policy_refs": resolved_refs,
            "cited_policy_refs": cited_refs,
            "unknown_policy_refs": unknown_refs,
            "violations": violations,
            "warnings": warnings,
            "findings": findings,
        }


@lru_cache(maxsize=1)
def get_policy_engine() -> PolicyEngine:
    return PolicyEngine()


def policy_compliance_for_action(
    target: str,
    action: str,
    *,
    status: str = "allowed",
    checks: list[str] | tuple[str, ...] | None = None,
    scenario: dict[str, Any] | str | None = None,
) -> dict[str, Any]:
    return get_policy_engine().policy_compliance_for_action(target, action, status=status, checks=checks, scenario=scenario)


def resolve_policy_refs_for_action(target: str, action: str, scenario: dict[str, Any] | str | None = None) -> list[str]:
    return get_policy_engine().refs_for_action(target, action, scenario)
