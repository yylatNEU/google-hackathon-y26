from __future__ import annotations

import time
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]]


BOUNDARY = {
    "can_read": [
        "live_park_state",
        "heartbeat_actions",
        "outcome_ledger",
        "policy_gate",
        "park_understanding_score",
        "memory_retrieval",
        "counterfactual_failures",
        "training_status",
        "bigquery_training_status",
        "role_access_contracts",
    ],
    "cannot_do": [
        "dispatch",
        "execute_action",
        "override_controller",
        "set_reward",
        "write_label",
        "promote_model",
        "rollback_policy",
        "load_bigquery_per_tick",
        "run_arbitrary_bigquery_sql",
        "read_raw_bigquery_tables_from_chat",
    ],
    "hard_rule": "ParkOps MCP is an evidence interface only. It never exposes live control, reward, label, promotion, rollback, raw BigQuery SQL, raw warehouse tables, or per-tick BigQuery tools.",
}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    timeout_seconds: float
    args_schema: dict[str, Any]
    authority: str = "read_only"

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "timeout_seconds": self.timeout_seconds,
            "args_schema": self.args_schema,
            "authority": self.authority,
        }


TOOL_SPECS: dict[str, ToolSpec] = {
    "get_live_park_state": ToolSpec(
        "get_live_park_state",
        "Read the current simulator time, active scenario, and live incident signals.",
        1.5,
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    "get_latest_heartbeat_action": ToolSpec(
        "get_latest_heartbeat_action",
        "Read the latest heartbeat controller receipt and policy-gate status.",
        1.0,
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    "get_action_log": ToolSpec(
        "get_action_log",
        "Read recent heartbeat action records for tracing what the controller has considered or executed.",
        1.0,
        {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 40}}, "additionalProperties": False},
    ),
    "get_outcome_ledger": ToolSpec(
        "get_outcome_ledger",
        "Read measured outcome/error ledger rows derived from live controller action logs.",
        1.5,
        {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 40}}, "additionalProperties": False},
    ),
    "get_policy_gate_status": ToolSpec(
        "get_policy_gate_status",
        "Read the current policy-gate finding for the latest heartbeat action.",
        1.0,
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    "get_park_understanding_score": ToolSpec(
        "get_park_understanding_score",
        "Read the latest Park Understanding Score and evidence caps from observed memory.",
        1.5,
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    "get_memory_retrieval": ToolSpec(
        "get_memory_retrieval",
        "Read compact Mongo/local memory retrieval quality and relevant observed memory summaries.",
        1.5,
        {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 12}}, "additionalProperties": False},
    ),
    "get_counterfactual_failures": ToolSpec(
        "get_counterfactual_failures",
        "Read recent counterfactual mutation, uncertainty, and policy-trap failures.",
        1.5,
        {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 20}}, "additionalProperties": False},
    ),
    "get_training_status": ToolSpec(
        "get_training_status",
        "Read actual observed-outcome RL training status without starting training.",
        6.0,
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    "get_bigquery_training_status": ToolSpec(
        "get_bigquery_training_status",
        "Read a governed offline BigQuery/BigQuery ML readiness summary. This is not raw SQL access and is never called per tick.",
        2.5,
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    "get_llm_boundary_contract": ToolSpec(
        "get_llm_boundary_contract",
        "Read the hard authority boundary for the LLM/chat layer.",
        0.5,
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    "get_role_access_contracts": ToolSpec(
        "get_role_access_contracts",
        "Read role-specific visibility and authority contracts for customer, worker, ops, and ML/admin surfaces.",
        0.5,
        {
            "type": "object",
            "properties": {"role": {"type": "string", "enum": ["customer", "onsite_worker", "ops_team", "ml_ops_admin"]}},
            "additionalProperties": False,
        },
    ),
}


def tool_manifest() -> dict[str, Any]:
    return {
        "status": "ready",
        "mode": "park_ops_mcp_tool_manifest",
        "tool_count": len(TOOL_SPECS),
        "tools": [spec.as_dict() for spec in TOOL_SPECS.values()],
        "boundary": BOUNDARY,
        "uses_seed_data": False,
        "loads_bigquery_per_tick": False,
    }


def blocked_authority(message: str) -> str | None:
    lowered = str(message or "").lower()
    blocked_map = {
        "live_action": ["execute", "dispatch", "take action", "override", "send command", "control the park"],
        "reward": ["set reward", "change reward", "change the reward", "write reward", "reward override"],
        "training_label": ["label this", "set label", "write label", "mark successful", "mark as success", "mark that action successful", "mark action successful"],
        "promotion": ["promote model", "promote the model", "promote policy", "approve model", "ship model"],
        "rollback": ["rollback", "roll back"],
        "bigquery_tick": ["load bigquery every tick", "query bigquery every tick", "bigquery per tick"],
    }
    for authority, terms in blocked_map.items():
        if any(term in lowered for term in terms):
            return authority
    return None


def select_tools(message: str) -> list[str]:
    lowered = str(message or "").lower()
    if blocked_authority(lowered):
        return ["get_llm_boundary_contract", "get_latest_heartbeat_action", "get_policy_gate_status"]
    selected = ["get_live_park_state", "get_latest_heartbeat_action", "get_llm_boundary_contract"]
    if any(term in lowered for term in ("hi", "hello", "hey")) and len(lowered.strip()) <= 8:
        return selected
    if any(term in lowered for term in ("status", "happening", "right now", "current", "park", "pressure", "worry", "bad", "okay", "problem", "issue")):
        selected.extend(["get_policy_gate_status", "get_action_log"])
    if any(term in lowered for term in ("score", "cap", "pus", "understanding", "trust", "improve", "evidence")):
        selected.extend(["get_park_understanding_score", "get_outcome_ledger", "get_memory_retrieval"])
    if any(term in lowered for term in ("missing", "memory", "mongo", "retrieve", "case", "why")):
        selected.extend(["get_memory_retrieval", "get_outcome_ledger"])
    if any(term in lowered for term in ("uncertainty", "failed", "fail", "counterfactual", "mutation", "trap")):
        selected.extend(["get_counterfactual_failures", "get_policy_gate_status"])
    if any(term in lowered for term in ("train", "training", "fitness", "reward", "model", "bigquery", "bqml")):
        selected.extend(["get_training_status", "get_bigquery_training_status"])
    if any(term in lowered for term in ("role", "access", "customer", "guest", "worker", "onsite", "ops team", "admin", "authority", "permission", "ood")):
        selected.extend(["get_role_access_contracts"])
    deduped: list[str] = []
    for tool_name in selected:
        if tool_name in TOOL_SPECS and tool_name not in deduped:
            deduped.append(tool_name)
    return deduped[:8]


async def call_tool(
    tool_name: str,
    handlers: dict[str, ToolHandler],
    args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spec = TOOL_SPECS.get(tool_name)
    started = time.monotonic()
    if not spec:
        return {
            "tool": tool_name,
            "status": "error",
            "elapsed_ms": 0,
            "readiness_issues": [f"Unknown ParkOps MCP tool: {tool_name}"],
        }
    handler = handlers.get(tool_name)
    if not handler:
        return {
            "tool": tool_name,
            "status": "unavailable",
            "elapsed_ms": 0,
            "readiness_issues": [f"No handler registered for ParkOps MCP tool: {tool_name}"],
            "authority": spec.authority,
        }
    try:
        result = handler(args or {})
        if hasattr(result, "__await__"):
            result = await asyncio.wait_for(result, timeout=max(0.1, spec.timeout_seconds))  # type: ignore[assignment]
        elapsed_ms = int((time.monotonic() - started) * 1000)
        payload = dict(result) if isinstance(result, dict) else {"value": result}
        return {
            "tool": tool_name,
            "status": payload.get("status") or "ready",
            "elapsed_ms": elapsed_ms,
            "authority": spec.authority,
            "data": payload,
            "readiness_issues": payload.get("readiness_issues", []),
        }
    except asyncio.TimeoutError:
        return {
            "tool": tool_name,
            "status": "timeout",
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "authority": spec.authority,
            "readiness_issues": [f"{tool_name} exceeded {spec.timeout_seconds:g}s MCP evidence budget."],
        }
    except Exception as error:
        return {
            "tool": tool_name,
            "status": "error",
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "authority": spec.authority,
            "readiness_issues": [str(error)[:300]],
        }


def result_data(tool_results: list[dict[str, Any]], tool_name: str) -> dict[str, Any]:
    for result in tool_results:
        if result.get("tool") == tool_name and isinstance(result.get("data"), dict):
            return result["data"]
    return {}


def compact_context(tool_results: list[dict[str, Any]]) -> dict[str, Any]:
    live = result_data(tool_results, "get_live_park_state")
    latest = result_data(tool_results, "get_latest_heartbeat_action")
    policy = result_data(tool_results, "get_policy_gate_status") or {
        "policy_gate": latest.get("policy_gate") if isinstance(latest.get("policy_gate"), dict) else {}
    }
    pus = result_data(tool_results, "get_park_understanding_score")
    memory = result_data(tool_results, "get_memory_retrieval")
    outcomes = result_data(tool_results, "get_outcome_ledger")
    failures = result_data(tool_results, "get_counterfactual_failures")
    training = result_data(tool_results, "get_training_status")
    bigquery = result_data(tool_results, "get_bigquery_training_status")
    role_access = result_data(tool_results, "get_role_access_contracts")
    return {
        "live_state": live,
        "latest_action": latest,
        "policy_gate": policy.get("policy_gate") or policy,
        "park_understanding_score": pus,
        "memory_retrieval": memory,
        "outcome_ledger": outcomes,
        "counterfactual_failures": failures,
        "training_status": training,
        "bigquery_training_status": bigquery,
        "role_access_contracts": role_access,
        "boundary": BOUNDARY,
        "tool_status": [
            {
                "tool": item.get("tool"),
                "status": item.get("status"),
                "elapsed_ms": item.get("elapsed_ms"),
                "readiness_issues": item.get("readiness_issues", []),
            }
            for item in tool_results
        ],
    }


def prompt_packet(message: str, history: list[dict[str, Any]], tool_results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "task": "Answer as a natural ParkPulse ops analyst. Use ParkOps MCP tool evidence, not scripted app text.",
        "user_question": message,
        "recent_history": history[-6:],
        "mcp": {
            "manifest": tool_manifest(),
            "selected_tools": [item.get("tool") for item in tool_results],
            "tool_results": tool_results,
            "compact_context": compact_context(tool_results),
        },
        "hard_rules": [
            BOUNDARY["hard_rule"],
            "If Gemini or any evidence tool is unavailable, say that clearly and answer from available observed evidence.",
            "Do not invent incidents, outcomes, model improvements, staff, rides, or sensor facts.",
            "Use a normal conversational tone, but keep evidence and uncertainty explicit.",
        ],
        "required_json": {
            "headline": "short answer title",
            "answer": "natural concise answer",
            "evidence": ["specific observed evidence used"],
            "uncertainty": ["missing, weak, stale, timed-out, or low-reliability evidence"],
            "next_checks": ["next safe checks or operator review steps"],
            "cannot_do": BOUNDARY["cannot_do"],
        },
    }
