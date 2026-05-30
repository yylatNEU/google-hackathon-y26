from __future__ import annotations

import os
from copy import deepcopy
from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Any

from policy_engine import get_policy_engine, resolve_policy_refs_for_action


class _NoopSpan:
    def set_attribute(self, *_args, **_kwargs) -> None:
        return None


class _NoopTracer:
    def start_as_current_span(self, *_args, **_kwargs):
        return nullcontext(_NoopSpan())


def _get_tracer(name: str):
    if str(os.getenv("PARKPULSE_ENABLE_OTEL_SPANS", "")).strip().lower() not in {"1", "true", "yes", "on"}:
        return _NoopTracer()
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except Exception:
        return _NoopTracer()


_tracer = _get_tracer("parkpulse.governance_runtime")
_decision_ledger: list[dict[str, Any]] = []
_remediation_tasks: list[dict[str, Any]] = []
_customer_care_cases: list[dict[str, Any]] = []


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _new_id(prefix: str, count: int) -> str:
    return f"{prefix}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{count + 1:03d}"


def build_runtime_action(
    target: str,
    action: str,
    *,
    title: str | None = None,
    owner: str = "ParkPulse runtime",
    expected_impact: str | None = None,
    deadline_minutes: int = 10,
    source: str = "manual_action",
    payload: dict[str, Any] | None = None,
    scenario: dict[str, Any] | str | None = None,
) -> dict[str, Any]:
    return {
        "action_id": f"{source}:{target}:{action}",
        "title": title or f"Execute {target}/{action}",
        "owner": owner,
        "deadline_minutes": deadline_minutes,
        "expected_impact": expected_impact or "Runtime action requested against live ParkPulse state.",
        "park_action": {"target": target, "action": action},
        "payload": deepcopy(payload or {}),
        "policy_compliance": {
            "status": "pending_runtime_gate",
            "checks": ["pre-execution-policy-gate", "arize-scorecard", "customer-care-escalation"],
            "policy_refs": resolve_policy_refs_for_action(target, action, scenario),
        },
    }


def _flatten_lane_messages(supervised_action: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    for lane in supervised_action.get("lanes", []) or []:
        for key in ("violations", "warnings"):
            for message in lane.get(key, []) or []:
                if message not in messages:
                    messages.append(str(message))
    return messages


def _create_remediation_task(
    gate_status: str,
    action_doc: dict[str, Any],
    messages: list[str],
    park_state: dict[str, Any],
) -> dict[str, Any]:
    flow = park_state.get("guestFlow", {}) if isinstance(park_state, dict) else {}
    scenario = flow.get("activeScenario", {}) if isinstance(flow, dict) else {}
    park_action = action_doc.get("park_action", {}) or {}
    task = {
        "id": _new_id("PP-REMEDIATE", len(_remediation_tasks)),
        "createdAt": _now_iso(),
        "status": "open",
        "severity": "critical" if gate_status == "blocked" else "review",
        "owner": "operations_supervisor" if gate_status == "blocked" else "duty_manager",
        "scenarioKey": scenario.get("key", "unknown"),
        "sourceActionId": action_doc.get("action_id"),
        "action": f"{park_action.get('target', '')}/{park_action.get('action', '')}",
        "title": "Policy gate blocked action" if gate_status == "blocked" else "Policy gate requires approval",
        "requiredAction": (
            "Stop the action, resolve the policy violation, and rerun the agent plan."
            if gate_status == "blocked"
            else "Approve, revise, or reject the action before it reaches guests, workers, or equipment."
        ),
        "policyFindings": messages,
    }
    _remediation_tasks.insert(0, task)
    del _remediation_tasks[50:]
    return deepcopy(task)


def _create_customer_care_case(
    gate_status: str,
    action_doc: dict[str, Any],
    park_state: dict[str, Any],
    messages: list[str],
) -> dict[str, Any] | None:
    title = str(action_doc.get("title", "")).lower()
    park_action = action_doc.get("park_action", {}) or {}
    target = str(park_action.get("target", ""))
    if gate_status == "clear" and target not in {"ride", "traffic", "food", "guest"} and "message" not in title:
        return None

    flow = park_state.get("guestFlow", {}) if isinstance(park_state, dict) else {}
    scenario = flow.get("activeScenario", {}) if isinstance(flow, dict) else {}
    guest_care = park_state.get("guestCare", {}) if isinstance(park_state, dict) else {}
    case = {
        "id": _new_id("PP-CARE", len(_customer_care_cases)),
        "createdAt": _now_iso(),
        "status": "queued" if gate_status != "blocked" else "supervisor_review",
        "severity": "high" if gate_status != "clear" else "normal",
        "scenarioKey": scenario.get("key", "unknown"),
        "sourceActionId": action_doc.get("action_id"),
        "reason": (
            "Guest-facing action needs recovery language review."
            if gate_status != "clear"
            else "Guest-facing action logged for recovery follow-through."
        ),
        "safeAudience": "aggregate affected guest segment",
        "prohibited": ["named guest details", "payment data", "medical details", "individual compensation promise"],
        "openCasePressure": guest_care.get("openCases", 0),
        "policyFindings": messages[:4],
    }
    _customer_care_cases.insert(0, case)
    del _customer_care_cases[50:]
    return deepcopy(case)


def _record_ledger(entry: dict[str, Any]) -> dict[str, Any]:
    _decision_ledger.insert(0, entry)
    del _decision_ledger[80:]
    return deepcopy(entry)


def supervise_runtime_action(
    action_doc: dict[str, Any],
    park_state: dict[str, Any],
    *,
    source: str = "runtime",
    eval_result: dict[str, Any] | None = None,
    signals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with _tracer.start_as_current_span("parkpulse.policy_gate.supervise_action") as span:
        active_scenario = park_state.get("guestFlow", {}).get("activeScenario", {})
        scenario_key = active_scenario.get("key", "ride_down")
        if eval_result is None:
            from park_eval import evaluate_park_decision

            eval_result = evaluate_park_decision(scenario_key, park_state)
        from park_agent_monitoring import build_park_agent_monitoring

        policy_engine = get_policy_engine()
        monitoring = build_park_agent_monitoring(
            park_state,
            {
                "scenario": active_scenario,
                "recommended_actions": [action_doc],
            },
            eval_result,
            signals or {"count": 0},
        )
        supervised = (monitoring.get("supervised_actions") or [{}])[0]
        lane_messages = _flatten_lane_messages(supervised)
        policy_contract = policy_engine.validate_action_refs(action_doc, active_scenario)
        contract_messages = list(policy_contract.get("issues", []))
        engine_result = policy_engine.evaluate_action(action_doc, park_state, eval_result, active_scenario)
        engine_messages = [*engine_result.get("violations", []), *engine_result.get("warnings", [])]
        cache_contract = (action_doc.get("payload", {}) or {}).get("cache_accuracy_contract", {})
        cache_messages: list[str] = []
        if isinstance(cache_contract, dict) and cache_contract.get("must_revalidate"):
            drift = cache_contract.get("semantic_drift", {}) if isinstance(cache_contract.get("semantic_drift"), dict) else {}
            drift_level = drift.get("level", "unknown")
            cache_messages.append(
                f"Cache accuracy contract requires revalidation before execution; drift={drift_level}, "
                f"trust_penalty={cache_contract.get('cache_trust_penalty', 0)}."
            )
        messages = list(dict.fromkeys([*contract_messages, *engine_messages, *lane_messages, *cache_messages]))
        monitor_status = supervised.get("policy_status", engine_result["status"])

        drift_level = (
            cache_contract.get("semantic_drift", {}).get("level")
            if isinstance(cache_contract, dict) and isinstance(cache_contract.get("semantic_drift"), dict)
            else None
        )
        if policy_contract["status"] == "invalid" or engine_result["status"] == "blocked" or drift_level == "dangerous":
            gate_status = "blocked"
            allowed = False
        elif engine_result["status"] == "review" or (isinstance(cache_contract, dict) and cache_contract.get("must_revalidate")):
            gate_status = "review"
            allowed = False
        else:
            gate_status = "clear"
            allowed = True

        remediation = None if gate_status == "clear" else _create_remediation_task(gate_status, action_doc, messages, park_state)
        customer_case = _create_customer_care_case(gate_status, action_doc, park_state, messages)
        ledger = _record_ledger(
            {
                "id": _new_id("PP-GATE", len(_decision_ledger)),
                "createdAt": _now_iso(),
                "source": source,
                "actionId": action_doc.get("action_id"),
                "title": action_doc.get("title"),
                "parkAction": action_doc.get("park_action", {}),
                "gateStatus": gate_status,
                "allowed": allowed,
                "policyStatus": monitor_status,
                "policyContract": policy_contract,
                "policyFindings": messages,
                "cacheAccuracyContract": cache_contract if isinstance(cache_contract, dict) else {},
                "monitoringId": monitoring.get("monitoring_id"),
                "arizeTrace": monitoring.get("arize_monitor", {}),
                "remediationTaskId": (remediation or {}).get("id"),
                "customerCareCaseId": (customer_case or {}).get("id"),
            }
        )
        span.set_attribute("parkpulse.policy_gate.status", gate_status)
        span.set_attribute("parkpulse.policy_gate.allowed", allowed)
        span.set_attribute("parkpulse.policy_gate.action_id", str(action_doc.get("action_id", "")))
        return {
            "allowed": allowed,
            "gate_status": gate_status,
            "action": deepcopy(action_doc),
            "supervision": supervised,
            "monitoring": monitoring,
            "policy_contract": policy_contract,
            "findings": messages,
            "remediation_task": remediation,
            "customer_care_case": customer_case,
            "ledger_entry": ledger,
        }


def list_runtime_governance(limit: int = 20) -> dict[str, Any]:
    return {
        "decision_ledger": deepcopy(_decision_ledger[:limit]),
        "remediation_tasks": deepcopy(_remediation_tasks[:limit]),
        "customer_care_cases": deepcopy(_customer_care_cases[:limit]),
        "summary": {
            "ledger_count": len(_decision_ledger),
            "open_remediation_count": sum(1 for task in _remediation_tasks if task.get("status") == "open"),
            "open_customer_care_count": sum(1 for case in _customer_care_cases if case.get("status") in {"queued", "supervisor_review"}),
        },
    }


def create_customer_care_case(payload: dict[str, Any], park_state: dict[str, Any]) -> dict[str, Any]:
    flow = park_state.get("guestFlow", {}) if isinstance(park_state, dict) else {}
    scenario = flow.get("activeScenario", {}) if isinstance(flow, dict) else {}
    case = {
        "id": _new_id("PP-CARE", len(_customer_care_cases)),
        "createdAt": _now_iso(),
        "status": "queued",
        "severity": str(payload.get("severity", "normal")),
        "scenarioKey": payload.get("scenarioKey") or scenario.get("key", "unknown"),
        "sourceActionId": payload.get("sourceActionId"),
        "reason": payload.get("reason", "Guest recovery review requested."),
        "safeAudience": payload.get("safeAudience", "aggregate affected guest segment"),
        "prohibited": ["named guest details", "payment data", "medical details", "individual compensation promise"],
        "openCasePressure": park_state.get("guestCare", {}).get("openCases", 0),
        "policyFindings": payload.get("policyFindings", []),
    }
    _customer_care_cases.insert(0, case)
    del _customer_care_cases[50:]
    return deepcopy(case)
