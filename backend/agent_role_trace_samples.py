from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_role_skills import evaluate_agent_role_trace, route_agent_role


ROLE_MODES = ("scan", "react", "proact", "customer", "qa")


def _sample_log_path() -> Path:
    configured = os.getenv("PARKPULSE_AGENT_ROLE_TRACE_SAMPLE_LOG_PATH")
    if configured:
        return Path(configured).expanduser()
    runtime_dir = Path(os.getenv("PARKPULSE_RUNTIME_DIR", "/tmp/parkpulse"))
    return runtime_dir / "agent_role_trace_samples.jsonl"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _bounded_payload(payload: dict[str, Any]) -> dict[str, Any]:
    telemetry = payload.get("run_telemetry", {}) if isinstance(payload.get("run_telemetry"), dict) else {}
    delivery = telemetry.get("delivery", {}) if isinstance(telemetry.get("delivery"), dict) else {}
    return {
        "status": payload.get("status"),
        "selected_role": payload.get("selected_role"),
        "skill": payload.get("skill"),
        "role_route": payload.get("role_route") if isinstance(payload.get("role_route"), dict) else payload.get("route"),
        "role_run": payload.get("role_run"),
        "digital_twin_tools": payload.get("digital_twin_tools"),
        "operator_response": payload.get("operator_response"),
        "answer": payload.get("answer"),
        "actions": payload.get("actions"),
        "scan": payload.get("scan"),
        "role_receipt": payload.get("role_receipt"),
        "run_telemetry": {
            "scenario_key": telemetry.get("scenario_key"),
            "governance": telemetry.get("governance"),
            "eval": telemetry.get("eval"),
            "delivery": {
                "summary": delivery.get("summary") if isinstance(delivery, dict) else {},
                "dispatches": delivery.get("dispatches") if isinstance(delivery, dict) else [],
            },
        },
        "go_no_go_recommendation": payload.get("go_no_go_recommendation"),
        "failure_mode_matrix": payload.get("failure_mode_matrix"),
    }


def record_agent_role_trace_sample(
    payload: dict[str, Any],
    *,
    message: str = "",
    mode: str = "auto",
    source: str = "parkpulse_api.agent_role_run",
) -> dict[str, Any]:
    role = str(payload.get("selected_role") or (payload.get("role_run", {}) if isinstance(payload.get("role_run"), dict) else {}).get("role") or "unknown")
    trace = payload.get("digital_twin_tools", {}) if isinstance(payload.get("digital_twin_tools"), dict) else {}
    row = {
        "id": f"role_trace_{int(time.time() * 1000)}_{role}",
        "created_at": _now_iso(),
        "source": source,
        "message": message[:500],
        "mode": mode,
        "role": role,
        "trace_status": (trace.get("deliberate_eval", {}) if isinstance(trace.get("deliberate_eval"), dict) else {}).get("status"),
        "trace_score": (trace.get("deliberate_eval", {}) if isinstance(trace.get("deliberate_eval"), dict) else {}).get("score"),
        "payload": _bounded_payload(payload),
    }
    path = _sample_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_jsonable(row), sort_keys=True, separators=(",", ":")) + "\n")
    return {"status": "recorded", "path": str(path), "sample": row}


def latest_agent_role_trace_samples(limit: int = 50) -> dict[str, Any]:
    safe_limit = max(1, min(500, int(limit or 50)))
    path = _sample_log_path()
    if not path.exists():
        return {"status": "empty", "mode": "agent_role_trace_samples", "path": str(path), "count": 0, "samples": []}
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    samples = list(reversed(rows))[:safe_limit]
    return {"status": "ready" if samples else "empty", "mode": "agent_role_trace_samples", "path": str(path), "count": len(samples), "samples": samples}


def build_sampled_agent_role_trace_eval_report(limit: int = 50) -> dict[str, Any]:
    ledger = latest_agent_role_trace_samples(limit=limit)
    samples = ledger.get("samples", []) if isinstance(ledger.get("samples"), list) else []
    if not samples:
        return {
            "status": "skipped",
            "mode": "sampled_agent_role_trace_eval_report",
            "sample_count": 0,
            "passed_count": 0,
            "failed_count": 0,
            "path": ledger.get("path"),
            "readiness_issues": ["No persisted role-run trace samples found."],
        }
    results = []
    for sample in samples:
        payload = sample.get("payload", {}) if isinstance(sample, dict) and isinstance(sample.get("payload"), dict) else {}
        role = str(sample.get("role") or payload.get("selected_role") or "scan")
        route = payload.get("role_route") if isinstance(payload.get("role_route"), dict) else route_agent_role(str(sample.get("message") or "sampled role trace"), role if role in ROLE_MODES else "scan")
        trace = payload.get("digital_twin_tools", {}) if isinstance(payload.get("digital_twin_tools"), dict) else {}
        eval_result = evaluate_agent_role_trace(route, trace, payload)
        results.append(
            {
                "id": sample.get("id"),
                "created_at": sample.get("created_at"),
                "role": role,
                "status": eval_result.get("status"),
                "score": eval_result.get("score"),
                "required_without_output": eval_result.get("required_without_output", []),
                "critical_failures": eval_result.get("critical_failures", []),
                "readiness_issues": eval_result.get("readiness_issues", []),
            }
        )
    failed = [row for row in results if row.get("status") != "passed"]
    average = round(sum(float(row.get("score") or 0) for row in results) / max(1, len(results)), 2)
    return {
        "status": "passed" if not failed and average >= 88 else "failed",
        "mode": "sampled_agent_role_trace_eval_report",
        "sample_count": len(results),
        "passed_count": len(results) - len(failed),
        "failed_count": len(failed),
        "average_score": average,
        "path": ledger.get("path"),
        "samples": results,
        "readiness_issues": sorted({issue for row in results for issue in row.get("readiness_issues", [])}),
    }


def _sample_trace(role: str, tools: list[str], *, shallow: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    route = route_agent_role("adversarial sampled role trace", role)
    calls = []
    for tool in tools:
        if shallow:
            output = {"status": "ok"}
        elif tool == "get_park_state":
            output = {"status": "ok", "summary": "sampled park state", "activeScenario": {"key": role}, "signals": ["sampled"]}
        elif tool == "get_noisy_observation":
            output = {"status": "ok", "signals": [{"kind": "weak_signal"}], "confidence": 0.71}
        elif tool.startswith("get_"):
            output = {"status": "ok", "summary": f"{tool} sampled context", "constraint": "bounded"}
        elif tool == "retrieve_similar_incidents":
            output = {"status": "ok", "incidents": [{"id": "sample_incident"}], "learnings": [{"id": "sample_learning"}]}
        elif tool == "compare_action_candidates":
            output = {"status": "ok", "candidates": [{"id": "a"}, {"id": "b"}], "selected": "b", "rejected": ["a"]}
        elif tool == "simulate_action":
            output = {"status": "ok", "simulation": {"horizon_minutes": 15}, "projected_impact": {"risk_delta": -0.1}}
        elif tool == "validate_policy":
            output = {"status": "ok", "gate_status": "checked", "policy_gate": "checked", "findings": ["bounded"]}
        elif tool.startswith("dispatch_"):
            output = {"status": "prepared", "dispatch_ids": [f"{tool}_sample"], "idempotencyKey": f"{tool}:sample", "targetSystem": "sample_receiver"}
        elif tool == "write_decision_memory":
            output = {"status": "ok", "decision_id": "sample_decision", "outcome_id": "sample_outcome", "memory_write": {"validity": "observed_response"}}
        elif tool == "score_outcome":
            output = {"status": "ok", "score": 0.9, "metrics": {"response": "bounded"}}
        elif tool.startswith("inspect_"):
            output = {"status": "ok", "readiness": {"api": "ready"}, "receipts": [{"id": "sample"}], "observability": {"trace": True}}
        else:
            output = {"status": "ok", "summary": f"{tool} sampled output"}
        calls.append({"tool": tool, "server": "parkpulse.agent_roles", "status": "ok", "output": output})
    trace = {
        "mode": "adversarial_sampled_role_trace",
        "server": "parkpulse.agent_roles",
        "tool_count": len(calls),
        "tool_calls": calls,
        "summary": {"selected_role": role, "selected_skill": route.get("skill")},
    }
    return route, trace


def build_adversarial_sampled_role_trace_eval_report() -> dict[str, Any]:
    fixtures = [
        {
            "id": "shallow_ordered_react_sample",
            "role": "react",
            "tools": route_agent_role("adversarial shallow react", "react")["deliberate_tool_use"]["required_sequence"],
            "shallow": True,
            "expected": {"missing_output:get_park_state", "missing_output:validate_policy", "policy_evidence_missing"},
        },
        {
            "id": "fake_policy_evidence_react_sample",
            "role": "react",
            "tools": ["get_park_state", "retrieve_similar_incidents", "compare_action_candidates", "simulate_action", "validate_policy"],
            "mutate": lambda trace: [call.update({"output": {"status": "ok"}}) for call in trace["tool_calls"] if call.get("tool") == "validate_policy"],
            "expected": {"missing_output:validate_policy", "policy_evidence_missing"},
        },
        {
            "id": "customer_internal_dispatch_sample",
            "role": "customer",
            "tools": ["get_park_state", "get_public_wait_times", "dispatch_worker_task"],
            "expected": {"missing_required:get_public_route_options", "forbidden:dispatch_worker_task", "dispatch_boundary_violation"},
        },
        {
            "id": "scan_dispatch_sample",
            "role": "scan",
            "tools": ["get_noisy_observation", "get_park_state", "retrieve_similar_incidents", "dispatch_guest_message"],
            "expected": {"forbidden:dispatch_guest_message", "dispatch_boundary_violation"},
        },
        {
            "id": "qa_missing_observability_sample",
            "role": "qa",
            "tools": ["get_park_state", "inspect_runtime_status", "simulate_action", "validate_policy"],
            "expected": {"missing_required:inspect_delivery_receipts", "missing_required:inspect_observability_contract", "inspection_evidence_missing"},
        },
        {
            "id": "proact_memory_without_policy_outcome_sample",
            "role": "proact",
            "tools": ["get_noisy_observation", "retrieve_similar_incidents", "simulate_action", "write_decision_memory"],
            "expected": {"missing_required:validate_policy", "missing_required:score_outcome", "policy_tool_missing"},
        },
    ]
    results = []
    for fixture in fixtures:
        route, trace = _sample_trace(str(fixture["role"]), [str(tool) for tool in fixture["tools"]], shallow=bool(fixture.get("shallow")))
        mutate = fixture.get("mutate")
        if callable(mutate):
            mutate(trace)
        eval_result = evaluate_agent_role_trace(route, trace, {"selected_role": fixture["role"], "digital_twin_tools": trace, "role_route": route})
        critical = set(eval_result.get("critical_failures", []))
        expected = {str(item) for item in fixture["expected"]}
        expected_met = expected.issubset(critical)
        results.append(
            {
                "id": fixture["id"],
                "role": fixture["role"],
                "status": eval_result.get("status"),
                "score": eval_result.get("score"),
                "expected_failures": sorted(expected),
                "expected_failures_met": expected_met,
                "critical_failures": eval_result.get("critical_failures", []),
                "readiness_issues": eval_result.get("readiness_issues", []),
            }
        )
    missed = [row for row in results if row.get("status") == "passed"]
    wrong_reason = [row for row in results if not row.get("expected_failures_met")]
    return {
        "status": "passed" if not missed and not wrong_reason else "failed",
        "mode": "adversarial_sampled_role_trace_eval_report",
        "fixture_count": len(results),
        "caught_count": len(results) - len(missed),
        "missed_count": len(missed),
        "wrong_reason_count": len(wrong_reason),
        "fixtures": results,
        "readiness_issues": sorted({issue for row in results for issue in row.get("readiness_issues", [])}) if missed or wrong_reason else [],
    }
