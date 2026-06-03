#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


ROLE_CASES: list[tuple[str, str]] = [
    ("scan", "scan vague guest complaints and worker taps for early crowd risk"),
    ("react", "food court is down and mobile orders are backing up near the west plaza"),
    ("proact", "Staff note: kids are crying near the barrier and the crowd stopped moving by the maze exit"),
    ("customer", "where should my family go next"),
    ("qa", "pre-deploy reliability QA failure mode matrix"),
]


SCENARIO_CASES: list[str] = ["ride_down", "food_spike", "marketing_promo_conflict", "storm_response"]


def _now_ms() -> int:
    return int(time.time() * 1000)


async def _timed(label: str, coro: Any, timeout_seconds: float) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    started = time.perf_counter()
    started_ms = _now_ms()
    try:
        payload = await asyncio.wait_for(coro, timeout=timeout_seconds)
        return payload, {
            "label": label,
            "call_status": "complete",
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "started_ms": started_ms,
            "timeout_seconds": timeout_seconds,
        }
    except Exception as error:
        return None, {
            "label": label,
            "call_status": "error",
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "started_ms": started_ms,
            "timeout_seconds": timeout_seconds,
            "error": f"{type(error).__name__}: {error}",
        }


async def run_role_cases(args: argparse.Namespace) -> list[dict[str, Any]]:
    import parkpulse_api

    rows: list[dict[str, Any]] = []
    for mode, message in ROLE_CASES:
        timeout = args.proact_timeout_seconds if mode == "proact" else args.role_timeout_seconds
        payload, timing = await _timed(
            f"role:{mode}",
            parkpulse_api.park_agent_role_run(parkpulse_api.OperatorCommandRequest(message=message, mode=mode)),
            timeout,
        )
        if payload is None:
            rows.append({"mode": mode, "status": "error", **timing})
            continue
        telemetry = payload.get("run_telemetry", {}) if isinstance(payload.get("run_telemetry"), dict) else {}
        delivery = telemetry.get("delivery", {}) if isinstance(telemetry.get("delivery"), dict) else {}
        trace_eval = payload.get("digital_twin_tools", {}).get("deliberate_eval", {}) if isinstance(payload.get("digital_twin_tools"), dict) else {}
        row = {
            "mode": mode,
            "status": "passed" if trace_eval.get("status") == "passed" else "failed",
            "selected_role": payload.get("selected_role"),
            "trace_eval_status": trace_eval.get("status"),
            "dispatch_total": delivery.get("summary", {}).get("total", 0) if isinstance(delivery.get("summary"), dict) else 0,
            "latency_budget_status": (
                "failed"
                if mode == "proact" and timing["elapsed_ms"] > args.max_proact_seconds * 1000
                else "passed"
            ),
            **timing,
        }
        rows.append(row)
    return rows


async def run_real_role_eval(args: argparse.Namespace) -> dict[str, Any]:
    import parkpulse_api

    payload, timing = await _timed("real_role_eval", parkpulse_api.park_agent_role_eval(real=True), args.real_eval_timeout_seconds)
    if payload is None:
        return timing
    return {
        "status": payload.get("status"),
        "decision": payload.get("decision"),
        "role_count": payload.get("role_count"),
        "passed_role_count": payload.get("passed_role_count"),
        "failed_role_count": payload.get("failed_role_count"),
        "average_score": payload.get("average_score"),
        "roles": [
            {"role": row.get("role"), "status": row.get("status"), "score": row.get("score")}
            for row in payload.get("roles", [])
            if isinstance(row, dict)
        ],
        **timing,
    }


async def run_scenario_cases(args: argparse.Namespace) -> list[dict[str, Any]]:
    import parkpulse_api

    rows: list[dict[str, Any]] = []
    for scenario_key in SCENARIO_CASES:
        payload, timing = await _timed(
            f"scenario:{scenario_key}",
            parkpulse_api.park_agent_run(parkpulse_api.ParkAgentRunRequest(scenario_key=scenario_key, execute=False)),
            args.scenario_timeout_seconds,
        )
        if payload is None:
            rows.append({"scenario": scenario_key, "status": "error", **timing})
            continue
        proposals = payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}
        orchestration = payload.get("agent_orchestration") or payload.get("orchestration") or {}
        department_system = orchestration.get("department_system", {}) if isinstance(orchestration, dict) else {}
        rows.append(
            {
                "scenario": scenario_key,
                "status": payload.get("status"),
                "active_roles": proposals.get("active_roles", []),
                "proposal_count": proposals.get("proposal_count"),
                "proposal_active_departments": proposals.get("active_departments", []),
                "orchestration_active_departments": department_system.get("active_departments", []),
                "policy_gate": payload.get("governance", {}).get("policy_contract", {}).get("status") if isinstance(payload.get("governance"), dict) else None,
                "eval_status": payload.get("eval", {}).get("scorecard", {}).get("status") if isinstance(payload.get("eval"), dict) else None,
                **timing,
            }
        )
    return rows


def run_registry_boundary_smoke() -> dict[str, Any]:
    import park_multi_agent as multi

    rows: list[dict[str, Any]] = []
    for agent in multi.get_agent_registry():
        agent_id = str(agent["agent_id"])
        tools = list(multi.AGENT_BUILDER_TOOL_ALLOWLIST.get(agent_id, []))
        chosen_tool = next((tool for tool in tools if not tool.startswith("dispatch_")), tools[0] if tools else "")
        department = multi._department_for_agent(agent_id).get("department")
        context = {
            "department": department,
            "intent": "live all-agent boundary smoke",
            "evidence": ["agent registry", "allowed tool contract"],
            "risk_level": "low",
            "policy_check": "passed",
            "expected_outcome": "agent can run at least one owned tool under boundary",
            "rollback": "block tool call if boundary fails",
            "policy_gate_checked": True,
        }
        boundary = multi.enforce_agent_tool_boundary(agent_id, chosen_tool, context)
        rows.append(
            {
                "agent_id": agent_id,
                "department": boundary.get("department"),
                "tool": chosen_tool,
                "allowed": boundary.get("allowed"),
                "status": boundary.get("status"),
            }
        )
    failures = [row for row in rows if not row["allowed"]]
    return {
        "status": "passed" if not failures else "failed",
        "agent_count": len(rows),
        "passed": len(rows) - len(failures),
        "failed": len(failures),
        "failures": failures,
        "agents": rows,
    }


def summarize(report: dict[str, Any]) -> dict[str, Any]:
    role_failures = [row for row in report["role_runs"] if row.get("status") != "passed" or row.get("latency_budget_status") == "failed"]
    scenario_failures = [row for row in report["scenario_runs"] if row.get("status") != "complete"]
    real_eval_failed = report["real_role_eval"].get("status") != "passed"
    boundary_failed = report["registry_boundary"].get("status") != "passed"
    activated_roles = sorted({role for row in report["scenario_runs"] for role in row.get("active_roles", [])})
    activated_departments = sorted(
        {
            department
            for row in report["scenario_runs"]
            for department in [*row.get("proposal_active_departments", []), *row.get("orchestration_active_departments", [])]
        }
    )
    status = "passed" if not role_failures and not scenario_failures and not real_eval_failed and not boundary_failed else "failed"
    return {
        "status": status,
        "role_failures": role_failures,
        "scenario_failures": scenario_failures,
        "real_eval_failed": real_eval_failed,
        "boundary_failed": boundary_failed,
        "activated_role_count": len(activated_roles),
        "activated_roles": activated_roles,
        "activated_department_count": len(activated_departments),
        "activated_departments": activated_departments,
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    report = {
        "mode": "live_all_agents_smoke",
        "role_runs": await run_role_cases(args),
        "real_role_eval": await run_real_role_eval(args),
        "scenario_runs": await run_scenario_cases(args),
        "registry_boundary": run_registry_boundary_smoke(),
    }
    report["summary"] = summarize(report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ParkPulse live smoke checks across role agents, scenario agents, judge, and executor boundaries.")
    parser.add_argument("--role-timeout-seconds", type=float, default=60.0)
    parser.add_argument("--proact-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--real-eval-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--scenario-timeout-seconds", type=float, default=90.0)
    parser.add_argument("--max-proact-seconds", type=float, default=90.0)
    parser.add_argument("--output-json", default="output/qa/live-all-agents-smoke.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = asyncio.run(run(args))
    output_path = REPO_ROOT / args.output_json
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"summary": report["summary"], "output_json": str(output_path)}, indent=2, sort_keys=True))
    return 0 if report["summary"]["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
