#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _hash_id(prefix: str, payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(encoded).hexdigest()[:18]}"


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _proposal_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    proposals = payload.get("role_agent_proposals", {})
    rows = proposals.get("proposals", []) if isinstance(proposals, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def _receipt_by_agent(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    executor = payload.get("tool_executor_live_test", {})
    receipts = executor.get("receipts", []) if isinstance(executor, dict) else []
    by_agent: dict[str, dict[str, Any]] = {}
    for row in receipts:
        if not isinstance(row, dict) or not row.get("agent"):
            continue
        agent = str(row.get("agent"))
        existing = by_agent.get(agent)
        if existing is None or (existing.get("companion_action") and not row.get("companion_action")):
            by_agent[agent] = row
    return by_agent


def _receipts_by_agent(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    executor = payload.get("tool_executor_live_test", {})
    receipts = executor.get("receipts", []) if isinstance(executor, dict) else []
    by_agent: dict[str, list[dict[str, Any]]] = {}
    for row in receipts:
        if isinstance(row, dict) and row.get("agent"):
            by_agent.setdefault(str(row.get("agent")), []).append(row)
    return by_agent


def _event_ids(proposal: dict[str, Any]) -> list[str]:
    grounding = proposal.get("live_feed_grounding", {}) if isinstance(proposal.get("live_feed_grounding"), dict) else {}
    return [str(item) for item in grounding.get("event_ids", []) if item]


def _alternative_negotiation_summary(payload: dict[str, Any]) -> dict[str, Any]:
    proposals = payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}
    board = proposals.get("alternative_action_negotiation", {}) if isinstance(proposals.get("alternative_action_negotiation"), dict) else payload.get("alternative_action_negotiation", {}) if isinstance(payload.get("alternative_action_negotiation"), dict) else {}
    rows = board.get("rows", []) if isinstance(board.get("rows"), list) else []
    distilled = [
        {
            "alternative_id": row.get("alternative_id"),
            "held_agent": row.get("held_agent"),
            "held_department": row.get("held_department"),
            "held_tool": row.get("held_tool"),
            "held_policy_status": row.get("held_policy_status"),
            "held_decision": row.get("held_decision"),
            "substitute_agent": row.get("substitute_agent"),
            "substitute_department": row.get("substitute_department"),
            "substitute_tool": row.get("substitute_tool"),
            "substitute_policy_status": row.get("substitute_policy_status"),
            "substitute_executable_if_approved": row.get("substitute_executable_if_approved"),
            "resolution": row.get("resolution"),
            "tradeoff_reason": row.get("tradeoff_reason"),
            "execution_boundary": row.get("execution_boundary"),
            "live_feed_event_ids": row.get("live_feed_event_ids", []),
        }
        for row in rows
        if isinstance(row, dict)
    ]
    return {
        "status": board.get("status"),
        "substitute_count": board.get("substitute_count") if board.get("substitute_count") is not None else len(distilled),
        "safe_executable_substitute_count": board.get("safe_executable_substitute_count"),
        "unresolved_without_safe_substitute_count": board.get("unresolved_without_safe_substitute_count"),
        "policy": board.get("policy"),
        "rows": distilled,
    }


def _flatten_measurement_deltas(outcome_measurement: dict[str, Any]) -> list[dict[str, Any]]:
    rows = outcome_measurement.get("measurement_rows", []) if isinstance(outcome_measurement.get("measurement_rows"), list) else []
    deltas: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        metrics = row.get("metrics", []) if isinstance(row.get("metrics"), list) else []
        for metric in metrics:
            if not isinstance(metric, dict):
                continue
            deltas.append(
                {
                    "source": row.get("source"),
                    "metric": metric.get("metric"),
                    "before": metric.get("before"),
                    "after": metric.get("after"),
                    "impact": metric.get("impact"),
                    "before_event_id": row.get("before_event_id"),
                    "after_event_id": row.get("after_event_id"),
                }
            )
    return deltas


def _semantic_payload_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    measurement = payload.get("live_feed_outcome_measurement", {}) if isinstance(payload.get("live_feed_outcome_measurement"), dict) else {}
    projection = measurement.get("controlled_effect_projection", {}) if isinstance(measurement.get("controlled_effect_projection"), dict) else {}
    rows = projection.get("semantic_parameter_rows", []) if isinstance(projection.get("semantic_parameter_rows"), list) else []
    distilled: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        distilled.append(
            {
                "learning_id": row.get("learning_id"),
                "source_outcome_id": row.get("source_outcome_id"),
                "semantic_score": row.get("semantic_score"),
                "routing_strategy": row.get("routing_strategy"),
                "traffic_cap_policy": row.get("traffic_cap_policy"),
                "offer_strength": row.get("offer_strength"),
                "guest_segmenting": row.get("guest_segmenting"),
                "avoid_targets": row.get("avoid_targets", []),
                "tool_payload_delta": row.get("tool_payload_delta", {}),
                "policy": row.get("policy"),
            }
        )
    return distilled


def _semantic_companion_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    executor = payload.get("tool_executor_live_test", {}) if isinstance(payload.get("tool_executor_live_test"), dict) else {}
    receipts = executor.get("receipts", []) if isinstance(executor.get("receipts"), list) else []
    rows: list[dict[str, Any]] = []
    for receipt in receipts:
        if not isinstance(receipt, dict):
            continue
        result = receipt.get("result", {}) if isinstance(receipt.get("result"), dict) else {}
        if not (receipt.get("companion_action") or result.get("companion_action")):
            continue
        if receipt.get("companion_source") != "semantic_agent_learning" and result.get("companion_source") != "semantic_agent_learning":
            continue
        rows.append(
            {
                "agent": receipt.get("agent"),
                "department": receipt.get("department"),
                "source_tool": receipt.get("source_tool"),
                "parent_tool": receipt.get("companion_parent_tool"),
                "status": result.get("status"),
                "executed": result.get("executed"),
                "idempotency_key": result.get("idempotency_key"),
                "learning_id": (receipt.get("semantic_action_parameters", {}) if isinstance(receipt.get("semantic_action_parameters"), dict) else {}).get("learning_id"),
                "boundary": "Same-department low-risk companion action created by semantic memory; no sensitive authority expansion.",
            }
        )
    return rows


def _substitute_outcome_summary(payload: dict[str, Any]) -> dict[str, Any]:
    measurement = payload.get("live_feed_outcome_measurement", {}) if isinstance(payload.get("live_feed_outcome_measurement"), dict) else {}
    attribution = measurement.get("substitute_outcome_attribution", {}) if isinstance(measurement.get("substitute_outcome_attribution"), dict) else {}
    if not attribution:
        reward_layers = measurement.get("reward_layers", {}) if isinstance(measurement.get("reward_layers"), dict) else {}
        attribution = reward_layers.get("substitute_outcome_attribution", {}) if isinstance(reward_layers.get("substitute_outcome_attribution"), dict) else {}
    rows = attribution.get("rows", []) if isinstance(attribution.get("rows"), list) else []
    distilled_rows = [
        {
            "alternative_id": row.get("alternative_id"),
            "held_agent": row.get("held_agent"),
            "held_department": row.get("held_department"),
            "held_tool": row.get("held_tool"),
            "held_policy_status": row.get("held_policy_status"),
            "substitute_agent": row.get("substitute_agent"),
            "substitute_department": row.get("substitute_department"),
            "substitute_tool": row.get("substitute_tool"),
            "action_family": row.get("action_family"),
            "substitute_executed": row.get("substitute_executed"),
            "substitute_outcome_score": row.get("substitute_outcome_score"),
            "monitor_only_counterfactual_score": row.get("monitor_only_counterfactual_score"),
            "branch_lift_vs_monitor": row.get("branch_lift_vs_monitor"),
            "best_branch": row.get("best_branch"),
            "measurement_evidence": row.get("measurement_evidence", []),
            "held_action_counterfactual": row.get("held_action_counterfactual", {}),
            "execution_boundary": row.get("execution_boundary"),
        }
        for row in rows
        if isinstance(row, dict)
    ]
    return {
        "status": attribution.get("status"),
        "branch_count": attribution.get("branch_count"),
        "executed_branch_count": attribution.get("executed_branch_count"),
        "average_substitute_score": attribution.get("average_substitute_score"),
        "average_lift_vs_monitor": attribution.get("average_lift_vs_monitor"),
        "bundle": attribution.get("bundle", {}),
        "bundle_candidates": attribution.get("bundle_candidates", []),
        "selected_bundle": attribution.get("selected_bundle", {}),
        "rows": distilled_rows,
        "boundary": attribution.get("boundary"),
    }


def _semantic_training_summary(payload: dict[str, Any]) -> dict[str, Any]:
    memory_priors = payload.get("live_feed_memory_priors", {}) if isinstance(payload.get("live_feed_memory_priors"), dict) else {}
    proposals = payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}
    memory_prior_use = proposals.get("memory_prior_use", {}) if isinstance(proposals.get("memory_prior_use"), dict) else {}
    executor = payload.get("tool_executor_live_test", {}) if isinstance(payload.get("tool_executor_live_test"), dict) else {}
    measurement = payload.get("live_feed_outcome_measurement", {}) if isinstance(payload.get("live_feed_outcome_measurement"), dict) else {}
    reward_layers = measurement.get("reward_layers", {}) if isinstance(measurement.get("reward_layers"), dict) else {}
    reward_metrics = reward_layers.get("metrics", {}) if isinstance(reward_layers.get("metrics"), dict) else {}
    projection = measurement.get("controlled_effect_projection", {}) if isinstance(measurement.get("controlled_effect_projection"), dict) else {}
    semantic_rows = _semantic_payload_rows(payload)
    companion_rows = _semantic_companion_rows(payload)
    accepted_rows = memory_prior_use.get("rows", []) if isinstance(memory_prior_use.get("rows"), list) else []
    weak_rows = memory_prior_use.get("weak_context_rows", []) if isinstance(memory_prior_use.get("weak_context_rows"), list) else []
    return {
        "retrieval_method": memory_priors.get("retrieval_method"),
        "semantic_prior_count": memory_priors.get("semantic_prior_count", 0),
        "semantic_learning_ids": memory_priors.get("semantic_learning_ids", []),
        "semantic_prior_accepted_departments": sorted(
            {
                str(row.get("department"))
                for row in accepted_rows
                if isinstance(row, dict) and row.get("status") == "accepted_semantic_learning" and row.get("department")
            }
        ),
        "semantic_context_only_departments": [
            row.get("department")
            for row in weak_rows
            if isinstance(row, dict) and row.get("status") == "semantic_context_only"
        ],
        "semantic_action_parameter_count": executor.get("semantic_action_parameter_count") or reward_metrics.get("semantic_action_parameter_count") or len(semantic_rows),
        "semantic_companion_count": len(companion_rows),
        "semantic_companion_tools": [row.get("source_tool") for row in companion_rows if row.get("source_tool")],
        "semantic_companion_rows": companion_rows,
        "semantic_parameters_applied": bool(measurement.get("semantic_parameters_applied") or projection.get("semantic_parameters_applied")),
        "semantic_parameter_rows": semantic_rows,
        "measurement_deltas": _flatten_measurement_deltas(measurement),
        "reward_layers": {
            "operational_reward": reward_layers.get("operational_reward"),
            "composite_reward": reward_layers.get("composite_reward"),
            "semantic_action_quality_reward": reward_metrics.get("semantic_action_quality_reward"),
            "commerce_action_average_score": reward_metrics.get("commerce_action_average_score"),
            "promotion_eligible": reward_layers.get("promotion_eligible"),
        },
        "training_boundary": "Semantic memory may refine low-risk action parameters and training examples; it cannot create new authority, bypass policy, or mutate live park state.",
    }


def _training_example(
    *,
    agent_id: str,
    split: str,
    training_scope: str,
    source: str,
    input_payload: dict[str, Any],
    expected_output: dict[str, Any],
    evidence: dict[str, Any],
    eligible_for_supervised_training: bool,
    eligible_for_reward: bool = False,
) -> dict[str, Any]:
    basis = {
        "agent_id": agent_id,
        "split": split,
        "training_scope": training_scope,
        "source": source,
        "input": input_payload,
        "expected_output": expected_output,
        "evidence": evidence,
    }
    return {
        "id": _hash_id("live_feed_training_example", basis),
        "created_at": _now_iso(),
        **basis,
        "eligible_for_supervised_training": eligible_for_supervised_training,
        "eligible_for_reward": eligible_for_reward,
        "generated_by": "live_feed_training_closure",
        "uses_seed_data": False,
        "scripted_case": False,
        "labels_or_reward_changed": False,
        "llm_used_for_reward_or_label": False,
    }


def _proposal_training_examples(payload: dict[str, Any]) -> list[dict[str, Any]]:
    receipts = _receipt_by_agent(payload)
    receipts_by_agent = _receipts_by_agent(payload)
    examples: list[dict[str, Any]] = []
    for proposal in _proposal_rows(payload):
        envelope = proposal.get("proposal_envelope", {}) if isinstance(proposal.get("proposal_envelope"), dict) else {}
        policy = proposal.get("policy_judge", {}) if isinstance(proposal.get("policy_judge"), dict) else {}
        receipt = receipts.get(str(proposal.get("agent_id")), {})
        agent_receipts = receipts_by_agent.get(str(proposal.get("agent_id")), [])
        companion_receipts = [
            row
            for row in agent_receipts
            if isinstance(row, dict) and (row.get("companion_action") or (row.get("result", {}) if isinstance(row.get("result"), dict) else {}).get("companion_action"))
        ]
        result = receipt.get("result", {}) if isinstance(receipt.get("result"), dict) else {}
        action_disposition = receipt.get("action_disposition") or proposal.get("action_disposition")
        if not isinstance(action_disposition, dict):
            action_disposition = {}
        reasoning = proposal.get("department_reasoning", {}) if isinstance(proposal.get("department_reasoning"), dict) else {}
        semantic_action_parameters = (
            envelope.get("semantic_action_parameters")
            or envelope.get("action_parameters")
            or proposal.get("semantic_action_parameters")
            or {}
        )
        if not isinstance(semantic_action_parameters, dict):
            semantic_action_parameters = {}
        examples.append(
            _training_example(
                agent_id=str(proposal.get("agent_id") or "unknown"),
                split="train" if receipt else "eval",
                training_scope="live_feed_department_policy_and_executor_supervision",
                source="live_feed_agent_run_closed_loop",
                input_payload={
                    "department": proposal.get("department"),
                    "requested_tool": envelope.get("requested_tool") or proposal.get("requested_tool"),
                    "intent": envelope.get("intent") or proposal.get("recommendation"),
                    "live_feed_event_ids": _event_ids(proposal),
                    "risk_level": envelope.get("risk_level"),
                    "executor_status_before_closure": envelope.get("executor_status"),
                    "semantic_action_parameters": semantic_action_parameters,
                    "proposal_payload": envelope.get("proposal_payload", {}),
                    "department_reasoning": {
                        "diagnosis": reasoning.get("diagnosis"),
                        "candidate_actions": reasoning.get("candidate_actions"),
                        "forecast": reasoning.get("forecast"),
                        "failure_modes": reasoning.get("failure_modes"),
                        "selected_rationale": reasoning.get("selected_rationale"),
                    },
                },
                expected_output={
                    "policy_check": envelope.get("policy_check") or proposal.get("policy_check"),
                    "policy_status": policy.get("status"),
                    "executor_decision": "execute_controlled" if receipt.get("approved_for_controlled_executor") else "hold",
                    "executor_result_status": result.get("status"),
                    "follow_through_decision": action_disposition.get("decision"),
                    "follow_through_next_owner": action_disposition.get("next_owner"),
                    "follow_through_exit_condition": action_disposition.get("exit_condition"),
                    "rollback": envelope.get("rollback") or proposal.get("rollback"),
                    "semantic_payload_delta": semantic_action_parameters.get("tool_payload_delta") if semantic_action_parameters else {},
                    "semantic_companion_tools": [row.get("source_tool") for row in companion_receipts if row.get("source_tool")],
                },
                evidence={
                    "policy_reason": policy.get("reason"),
                    "executor_receipt": {
                        "approved_for_controlled_executor": receipt.get("approved_for_controlled_executor"),
                        "result_status": result.get("status"),
                        "idempotency_key": result.get("idempotency_key"),
                        "executed": result.get("executed"),
                    },
                    "executor_receipts_for_agent": [
                        {
                            "source_tool": row.get("source_tool"),
                            "status": (row.get("result", {}) if isinstance(row.get("result"), dict) else {}).get("status"),
                            "executed": (row.get("result", {}) if isinstance(row.get("result"), dict) else {}).get("executed"),
                            "companion_action": row.get("companion_action"),
                            "companion_parent_tool": row.get("companion_parent_tool"),
                            "companion_source": row.get("companion_source"),
                        }
                        for row in agent_receipts
                        if isinstance(row, dict)
                    ],
                    "live_feed_sources": (proposal.get("live_feed_grounding", {}) if isinstance(proposal.get("live_feed_grounding"), dict) else {}).get("sources", []),
                    "agent_loop": proposal.get("agent_loop", {}),
                    "memory_carry_forward": reasoning.get("memory_carry_forward"),
                    "semantic_learning_id": semantic_action_parameters.get("learning_id") if semantic_action_parameters else None,
                    "semantic_source_outcome_id": semantic_action_parameters.get("source_outcome_id") if semantic_action_parameters else None,
                    "semantic_policy_boundary": semantic_action_parameters.get("policy") if semantic_action_parameters else None,
                },
                eligible_for_supervised_training=True,
            )
        )
    return examples


def _run_level_examples(payload: dict[str, Any]) -> list[dict[str, Any]]:
    summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
    proposals = payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}
    tradeoff = proposals.get("executive_tradeoff", {}) if isinstance(proposals.get("executive_tradeoff"), dict) else {}
    executor = payload.get("tool_executor_live_test", {}) if isinstance(payload.get("tool_executor_live_test"), dict) else {}
    graph = payload.get("live_feed_cooperation", {}) if isinstance(payload.get("live_feed_cooperation"), dict) else {}
    live_case = payload.get("live_feed_case", {}) if isinstance(payload.get("live_feed_case"), dict) else {}
    memory_priors = payload.get("live_feed_memory_priors", {}) if isinstance(payload.get("live_feed_memory_priors"), dict) else {}
    memory_prior_use = proposals.get("memory_prior_use", {}) if isinstance(proposals.get("memory_prior_use"), dict) else {}
    receiver_delivery = payload.get("live_feed_receiver_delivery", {}) if isinstance(payload.get("live_feed_receiver_delivery"), dict) else {}
    outcome_measurement = payload.get("live_feed_outcome_measurement", {}) if isinstance(payload.get("live_feed_outcome_measurement"), dict) else {}
    outcome_memory = payload.get("live_feed_outcome_memory", {}) if isinstance(payload.get("live_feed_outcome_memory"), dict) else {}
    semantic_summary = _semantic_training_summary(payload)
    alternative_summary = _alternative_negotiation_summary(payload)
    substitute_outcome_summary = _substitute_outcome_summary(payload)
    rows = [
        _training_example(
            agent_id="decision_bridge_agent",
            split="train",
            training_scope="live_feed_executive_tradeoff_supervision",
            source="live_feed_agent_run_closed_loop",
            input_payload={
                "lead_source": live_case.get("lead_source"),
                "lead_signal_type": live_case.get("lead_signal_type"),
                "proposal_count": summary.get("proposal_count"),
                "departments": summary.get("active_departments"),
                "conflicts": proposals.get("conflicts", []),
                "memory_prior_outcome_ids": memory_priors.get("latest_outcome_ids", []),
                "semantic_memory": {
                    "retrieval_method": semantic_summary.get("retrieval_method"),
                    "semantic_learning_ids": semantic_summary.get("semantic_learning_ids"),
                    "accepted_departments": semantic_summary.get("semantic_prior_accepted_departments"),
                    "context_only_departments": semantic_summary.get("semantic_context_only_departments"),
                },
                "alternative_action_negotiation": alternative_summary,
                "substitute_outcome_attribution": substitute_outcome_summary,
            },
            expected_output={
                "decision": tradeoff.get("decision"),
                "approved_departments": tradeoff.get("approved_departments"),
                "held_departments": tradeoff.get("held_departments"),
                "safe_substitute_count": alternative_summary.get("safe_executable_substitute_count"),
                "unresolved_without_safe_substitute_count": alternative_summary.get("unresolved_without_safe_substitute_count"),
                "substitute_bundle_decision": (substitute_outcome_summary.get("bundle", {}) if isinstance(substitute_outcome_summary.get("bundle"), dict) else {}).get("decision"),
                "reason": tradeoff.get("reason"),
            },
            evidence={
                "negotiation_turns": proposals.get("negotiation_turns", []),
                "concrete_policy_count": summary.get("concrete_policy_count"),
                "missing_policy_check_count": summary.get("missing_policy_check_count"),
                "memory_prior_use": memory_prior_use,
                "semantic_training_summary": semantic_summary,
                "alternative_negotiation_rows": alternative_summary.get("rows", []),
                "substitute_outcome_rows": substitute_outcome_summary.get("rows", []),
            },
            eligible_for_supervised_training=True,
        ),
        _training_example(
            agent_id="gcp_eval_judge_agent",
            split="eval",
            training_scope="live_feed_trace_quality_eval",
            source="live_feed_agent_run_closed_loop",
            input_payload={
                "proposal_mode": summary.get("proposal_mode"),
                "grounded_proposals": summary.get("live_feed_grounded_proposal_count"),
                "proposal_count": summary.get("proposal_count"),
                "cooperation_graph_nodes": len(graph.get("nodes", [])) if isinstance(graph.get("nodes"), list) else 0,
                "cooperation_graph_edges": len(graph.get("edges", [])) if isinstance(graph.get("edges"), list) else 0,
            },
            expected_output={
                "label": "trace_contract_training_ready",
                "requirements": [
                    "Every proposal has live feed evidence.",
                    "Every proposal has concrete policy status.",
                    "Controlled executor executes only approved low-risk envelopes.",
                ],
            },
            evidence={
                "smoke_status": summary.get("status"),
                "trace_contract_present": (summary.get("judge", {}) if isinstance(summary.get("judge"), dict) else {}).get("trace_contract_present"),
                "executor_status": executor.get("status"),
                "executed_count": executor.get("executed_count"),
                "held_count": executor.get("held_count"),
            },
            eligible_for_supervised_training=False,
        ),
    ]
    if outcome_memory:
        outcome = outcome_memory.get("outcome", {}) if isinstance(outcome_memory.get("outcome"), dict) else {}
        response_metrics = outcome.get("response_metrics", {}) if isinstance(outcome.get("response_metrics"), dict) else {}
        learning = outcome.get("learning", {}) if isinstance(outcome.get("learning"), dict) else {}
        reward_layers = learning.get("reward_layers") if isinstance(learning.get("reward_layers"), dict) else response_metrics.get("rewardLayers") if isinstance(response_metrics.get("rewardLayers"), dict) else outcome_measurement.get("reward_layers") if isinstance(outcome_measurement.get("reward_layers"), dict) else {}
        reward_ready = bool(learning.get("eligible_for_reward")) and bool(response_metrics.get("measuredOutcomeAvailable"))
        rows.append(
            _training_example(
                agent_id="rl_action_policy",
                split="reward" if reward_ready else "eval",
                training_scope="live_feed_outcome_reward_candidate" if reward_ready else "live_feed_outcome_memory_reward_readiness_eval",
                source="mongo_outcome_events_live_feed_controlled",
                input_payload={
                    "decision_id": outcome_memory.get("decision_id"),
                    "outcome_id": outcome_memory.get("outcome_id"),
                    "mode": outcome.get("mode"),
                    "state_impact": outcome.get("state_impact", {}),
                    "response_metrics": response_metrics,
                    "post_action_measurement": outcome_measurement,
                    "memory_priors": memory_priors,
                    "semantic_memory_payload": semantic_summary,
                    "substitute_outcome_attribution": substitute_outcome_summary,
                },
                expected_output={
                    "label": learning.get("reward_label") or ("reward_ready_controlled_handoff" if reward_ready else "not_reward_ready_until_measured_outcome"),
                    "eligible_for_reward": reward_ready,
                    "reward_value": learning.get("reward_value") if reward_ready else None,
                    "reward_layers": reward_layers,
                    "promotion_eligible": bool(learning.get("promotion_eligible")) if "promotion_eligible" in learning else bool(outcome_measurement.get("promotion_eligible")),
                    "reason": (
                        "Controlled executor outcome memory, receiver delivery proof, and post-action live-feed measurements are present."
                        if reward_ready
                        else "Controlled executor outcome memory exists, but measured post-action attribution is incomplete."
                    ),
                    "substitute_bundle": substitute_outcome_summary.get("bundle", {}),
                },
                evidence={
                    "mongo_collection": outcome_memory.get("mongo_collection"),
                    "scorecard": outcome.get("scorecard", {}),
                    "learning": learning,
                    "receiver_delivery": {
                        "status": receiver_delivery.get("status"),
                        "proof_id": receiver_delivery.get("proof_id"),
                        "delivered_count": receiver_delivery.get("delivered_count"),
                        "acknowledged_count": receiver_delivery.get("acknowledged_count"),
                        "public_guest_messages_sent": receiver_delivery.get("public_guest_messages_sent"),
                        "material_state_mutation": receiver_delivery.get("material_state_mutation"),
                    },
                    "memory_prior_use": memory_prior_use,
                    "outcome_measurement": {
                        "status": outcome_measurement.get("status"),
                        "measurement_id": outcome_measurement.get("measurement_id"),
                        "attribution_confidence": outcome_measurement.get("attribution_confidence"),
                        "reward_value": outcome_measurement.get("reward_value"),
                        "reward_layers": outcome_measurement.get("reward_layers"),
                        "promotion_eligible": outcome_measurement.get("promotion_eligible"),
                        "measurement_rows": outcome_measurement.get("measurement_rows", []),
                        "semantic_parameters_applied": outcome_measurement.get("semantic_parameters_applied"),
                        "controlled_effect_projection": {
                            "status": (outcome_measurement.get("controlled_effect_projection", {}) if isinstance(outcome_measurement.get("controlled_effect_projection"), dict) else {}).get("status"),
                            "semantic_parameter_rows": semantic_summary.get("semantic_parameter_rows"),
                        },
                        "substitute_outcome_attribution": substitute_outcome_summary,
                    },
                },
                eligible_for_supervised_training=False,
                eligible_for_reward=reward_ready,
            )
        )
    for branch in substitute_outcome_summary.get("rows", []) if isinstance(substitute_outcome_summary.get("rows"), list) else []:
        if not isinstance(branch, dict):
            continue
        rows.append(
            _training_example(
                agent_id="decision_bridge_agent",
                split="train",
                training_scope="live_feed_safe_substitute_branch_supervision",
                source="live_feed_substitute_outcome_attribution",
                input_payload={
                    "held_action": {
                        "agent": branch.get("held_agent"),
                        "department": branch.get("held_department"),
                        "tool": branch.get("held_tool"),
                        "policy_status": branch.get("held_policy_status"),
                        "counterfactual": branch.get("held_action_counterfactual", {}),
                    },
                    "candidate_substitute": {
                        "agent": branch.get("substitute_agent"),
                        "department": branch.get("substitute_department"),
                        "tool": branch.get("substitute_tool"),
                        "action_family": branch.get("action_family"),
                    },
                    "monitor_only_counterfactual_score": branch.get("monitor_only_counterfactual_score"),
                    "measurement_evidence": branch.get("measurement_evidence", []),
                },
                expected_output={
                    "best_branch": branch.get("best_branch"),
                    "substitute_executed": branch.get("substitute_executed"),
                    "substitute_outcome_score": branch.get("substitute_outcome_score"),
                    "branch_lift_vs_monitor": branch.get("branch_lift_vs_monitor"),
                    "execution_boundary": branch.get("execution_boundary"),
                },
                evidence={
                    "alternative_id": branch.get("alternative_id"),
                    "bundle": substitute_outcome_summary.get("bundle", {}),
                    "boundary": substitute_outcome_summary.get("boundary"),
                },
                eligible_for_supervised_training=True,
            )
        )
    bundle_candidates = substitute_outcome_summary.get("bundle_candidates", []) if isinstance(substitute_outcome_summary.get("bundle_candidates"), list) else []
    selected_bundle = substitute_outcome_summary.get("selected_bundle", {}) if isinstance(substitute_outcome_summary.get("selected_bundle"), dict) else {}
    if bundle_candidates:
        rows.append(
            _training_example(
                agent_id="executive_agent",
                split="train",
                training_scope="live_feed_executive_bundle_selection_supervision",
                source="live_feed_substitute_bundle_attribution",
                input_payload={
                    "bundle_candidates": bundle_candidates,
                    "branch_rows": substitute_outcome_summary.get("rows", []),
                    "policy_boundary": substitute_outcome_summary.get("boundary"),
                    "selection_question": "Choose the safest high-utility bundle from measured safe substitutes while keeping held sensitive actions blocked.",
                },
                expected_output={
                    "selected_bundle_id": selected_bundle.get("bundle_id"),
                    "selected_bundle_score": selected_bundle.get("score"),
                    "selected_tools": selected_bundle.get("selected_tools", []),
                    "bundle_decision": (substitute_outcome_summary.get("bundle", {}) if isinstance(substitute_outcome_summary.get("bundle"), dict) else {}).get("decision"),
                    "rejected_bundles": (substitute_outcome_summary.get("bundle", {}) if isinstance(substitute_outcome_summary.get("bundle"), dict) else {}).get("rejected_bundles", []),
                    "reason": selected_bundle.get("decision_rationale"),
                },
                evidence={
                    "average_lift_vs_monitor": substitute_outcome_summary.get("average_lift_vs_monitor"),
                    "average_substitute_score": substitute_outcome_summary.get("average_substitute_score"),
                    "executed_branch_count": substitute_outcome_summary.get("executed_branch_count"),
                },
                eligible_for_supervised_training=True,
            )
        )
    return rows


def _record_review_dispositions(payload: dict[str, Any], *, reviewer: str) -> list[dict[str, Any]]:
    from live_feedback_loop import record_review_decision, review_training_ledger

    recorded = []
    existing_rows = review_training_ledger(limit=1000).get("rows", [])
    existing: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in existing_rows if isinstance(existing_rows, list) else []:
        if not isinstance(row, dict):
            continue
        existing[(str(row.get("case_id")), str(row.get("reviewer")), str(row.get("training_label")))] = row
    for proposal in _proposal_rows(payload):
        envelope = proposal.get("proposal_envelope", {}) if isinstance(proposal.get("proposal_envelope"), dict) else {}
        policy = proposal.get("policy_judge", {}) if isinstance(proposal.get("policy_judge"), dict) else {}
        status = str(policy.get("status") or "unknown")
        disposition = "approved" if status in {"passed", "approved_with_exclusions", "trace_only"} else "hold_for_review"
        case_id = f"live-feed:{proposal.get('agent_id')}:{envelope.get('requested_tool') or proposal.get('requested_tool')}"
        training_label = str(envelope.get("policy_check") or proposal.get("policy_check") or status)
        existing_row = existing.get((case_id, reviewer, training_label))
        if existing_row:
            recorded.append({**existing_row, "deduped_existing_review": True})
            continue
        result = record_review_decision(
            {
                "case_id": case_id,
                "decision": disposition,
                "reviewer": reviewer,
                "reason": policy.get("reason") or "Closed from live-feed training loop.",
                "training_label": training_label,
            }
        )
        if isinstance(result, dict) and result.get("review"):
            recorded.append(result["review"])
    return recorded


def close_live_feed_training_loop(input_path: Path, output_dir: Path, *, record_ledger: bool, reviewer: str) -> dict[str, Any]:
    payload = _read_json(input_path)
    proposal_rows = _proposal_rows(payload)
    semantic_summary = _semantic_training_summary(payload)
    alternative_summary = _alternative_negotiation_summary(payload)
    substitute_outcome_summary = _substitute_outcome_summary(payload)
    deep_reasoning_count = sum(1 for row in proposal_rows if isinstance(row.get("department_reasoning"), dict) and row.get("agent_loop"))
    candidate_action_count = sum(len((row.get("department_reasoning", {}) if isinstance(row.get("department_reasoning"), dict) else {}).get("candidate_actions", [])) for row in proposal_rows)
    failure_mode_count = sum(len((row.get("department_reasoning", {}) if isinstance(row.get("department_reasoning"), dict) else {}).get("failure_modes", [])) for row in proposal_rows)
    profile_context_count = sum(1 for row in proposal_rows if isinstance(row.get("park_profile_context"), dict) and row.get("park_profile_context", {}).get("status") == "attached")
    profile_counterfactual_count = sum(
        len(
            [
                candidate
                for candidate in ((row.get("department_reasoning", {}) if isinstance(row.get("department_reasoning"), dict) else {}).get("candidate_actions", []))
                if isinstance(candidate, dict) and isinstance(candidate.get("profile_counterfactual"), dict)
            ]
        )
        for row in proposal_rows
    )
    examples = [*_run_level_examples(payload), *_proposal_training_examples(payload)]
    supervised = [row for row in examples if row.get("eligible_for_supervised_training")]
    eval_rows = [row for row in examples if row.get("split") == "eval"]
    reward_rows = [row for row in examples if row.get("eligible_for_reward")]
    recorded_reviews = _record_review_dispositions(payload, reviewer=reviewer) if record_ledger else []
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": _hash_id("live_feed_training_closure", {"input_path": str(input_path), "examples": [row["id"] for row in examples]}),
        "created_at": _now_iso(),
        "status": "closed_loop_materialized" if examples else "blocked",
        "mode": "live_feed_training_loop_closure",
        "source_artifact": str(input_path),
        "summary": {
            "example_count": len(examples),
            "supervised_example_count": len(supervised),
            "eval_example_count": len(eval_rows),
            "reward_example_count": len(reward_rows),
            "review_disposition_count": len(recorded_reviews),
            "proposal_count": len(proposal_rows),
            "deep_reasoning_proposal_count": deep_reasoning_count,
            "candidate_action_count": candidate_action_count,
            "failure_mode_count": failure_mode_count,
            "profile_context_proposal_count": profile_context_count,
            "profile_counterfactual_candidate_count": profile_counterfactual_count,
            "park_profile_context_status": ((payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}).get("park_profile_context_status")),
            "park_profile_version": ((payload.get("park_profile_summary", {}) if isinstance(payload.get("park_profile_summary"), dict) else {}).get("profile_version")),
            "controlled_executor_executed_count": (payload.get("tool_executor_live_test", {}) if isinstance(payload.get("tool_executor_live_test"), dict) else {}).get("executed_count"),
            "controlled_executor_held_count": (payload.get("tool_executor_live_test", {}) if isinstance(payload.get("tool_executor_live_test"), dict) else {}).get("held_count"),
            "hard_follow_status": (payload.get("hard_decision_follow_through", {}) if isinstance(payload.get("hard_decision_follow_through"), dict) else {}).get("status"),
            "hard_follow_task_count": (payload.get("hard_decision_follow_through", {}) if isinstance(payload.get("hard_decision_follow_through"), dict) else {}).get("task_count"),
            "hard_follow_active_count": (payload.get("hard_decision_follow_through", {}) if isinstance(payload.get("hard_decision_follow_through"), dict) else {}).get("active_follow_up_count"),
            "hard_follow_unresolved_without_owner_count": (payload.get("hard_decision_follow_through", {}) if isinstance(payload.get("hard_decision_follow_through"), dict) else {}).get("unresolved_without_owner_count"),
            "alternative_negotiation_status": alternative_summary.get("status"),
            "alternative_substitute_count": alternative_summary.get("substitute_count"),
            "safe_executable_substitute_count": alternative_summary.get("safe_executable_substitute_count"),
            "unresolved_without_safe_substitute_count": alternative_summary.get("unresolved_without_safe_substitute_count"),
            "substitute_outcome_status": substitute_outcome_summary.get("status"),
            "substitute_outcome_branch_count": substitute_outcome_summary.get("branch_count"),
            "substitute_outcome_executed_branch_count": substitute_outcome_summary.get("executed_branch_count"),
            "substitute_outcome_average_score": substitute_outcome_summary.get("average_substitute_score"),
            "substitute_outcome_average_lift_vs_monitor": substitute_outcome_summary.get("average_lift_vs_monitor"),
            "substitute_bundle_candidate_count": len(substitute_outcome_summary.get("bundle_candidates", []) if isinstance(substitute_outcome_summary.get("bundle_candidates"), list) else []),
            "selected_substitute_bundle_id": (substitute_outcome_summary.get("selected_bundle", {}) if isinstance(substitute_outcome_summary.get("selected_bundle"), dict) else {}).get("bundle_id"),
            "memory_prior_status": (payload.get("live_feed_memory_priors", {}) if isinstance(payload.get("live_feed_memory_priors"), dict) else {}).get("status"),
            "memory_prior_count": (payload.get("live_feed_memory_priors", {}) if isinstance(payload.get("live_feed_memory_priors"), dict) else {}).get("prior_count"),
            "memory_prior_outcome_ids": (payload.get("live_feed_memory_priors", {}) if isinstance(payload.get("live_feed_memory_priors"), dict) else {}).get("latest_outcome_ids", []),
            "memory_prior_applied_count": (((payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}).get("memory_prior_use", {}) if isinstance((payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}).get("memory_prior_use", {}), dict) else {}).get("applied_count")),
            "memory_prior_weak_context_count": (((payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}).get("memory_prior_use", {}) if isinstance((payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}).get("memory_prior_use", {}), dict) else {}).get("weak_context_count")),
            "memory_prior_blocked_count": (((payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}).get("memory_prior_use", {}) if isinstance((payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}).get("memory_prior_use", {}), dict) else {}).get("blocked_count")),
            "memory_prior_accepted_departments": (((payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}).get("memory_prior_use", {}) if isinstance((payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}).get("memory_prior_use", {}), dict) else {}).get("accepted_departments", [])),
            "semantic_retrieval_method": semantic_summary.get("retrieval_method"),
            "semantic_prior_count": semantic_summary.get("semantic_prior_count"),
            "semantic_learning_ids": semantic_summary.get("semantic_learning_ids"),
            "semantic_prior_accepted_departments": semantic_summary.get("semantic_prior_accepted_departments"),
            "semantic_context_only_departments": semantic_summary.get("semantic_context_only_departments"),
            "semantic_action_parameter_count": semantic_summary.get("semantic_action_parameter_count"),
            "semantic_companion_count": semantic_summary.get("semantic_companion_count"),
            "semantic_companion_tools": semantic_summary.get("semantic_companion_tools"),
            "semantic_parameters_applied": semantic_summary.get("semantic_parameters_applied"),
            "semantic_measurement_delta_count": len(semantic_summary.get("measurement_deltas", [])),
            "semantic_action_quality_reward": (semantic_summary.get("reward_layers", {}) if isinstance(semantic_summary.get("reward_layers"), dict) else {}).get("semantic_action_quality_reward"),
            "commerce_action_average_score": (semantic_summary.get("reward_layers", {}) if isinstance(semantic_summary.get("reward_layers"), dict) else {}).get("commerce_action_average_score"),
            "receiver_delivery_status": (payload.get("live_feed_receiver_delivery", {}) if isinstance(payload.get("live_feed_receiver_delivery"), dict) else {}).get("status"),
            "receiver_delivery_proof_id": (payload.get("live_feed_receiver_delivery", {}) if isinstance(payload.get("live_feed_receiver_delivery"), dict) else {}).get("proof_id"),
            "receiver_delivery_delivered_count": (payload.get("live_feed_receiver_delivery", {}) if isinstance(payload.get("live_feed_receiver_delivery"), dict) else {}).get("delivered_count"),
            "receiver_delivery_acknowledged_count": (payload.get("live_feed_receiver_delivery", {}) if isinstance(payload.get("live_feed_receiver_delivery"), dict) else {}).get("acknowledged_count"),
            "outcome_measurement_status": (payload.get("live_feed_outcome_measurement", {}) if isinstance(payload.get("live_feed_outcome_measurement"), dict) else {}).get("status"),
            "outcome_measurement_id": (payload.get("live_feed_outcome_measurement", {}) if isinstance(payload.get("live_feed_outcome_measurement"), dict) else {}).get("measurement_id"),
            "outcome_measurement_attribution_confidence": (payload.get("live_feed_outcome_measurement", {}) if isinstance(payload.get("live_feed_outcome_measurement"), dict) else {}).get("attribution_confidence"),
            "outcome_measurement_reward_value": (payload.get("live_feed_outcome_measurement", {}) if isinstance(payload.get("live_feed_outcome_measurement"), dict) else {}).get("reward_value"),
            "outcome_memory_status": (payload.get("live_feed_outcome_memory", {}) if isinstance(payload.get("live_feed_outcome_memory"), dict) else {}).get("status"),
            "outcome_memory_id": (payload.get("live_feed_outcome_memory", {}) if isinstance(payload.get("live_feed_outcome_memory"), dict) else {}).get("outcome_id"),
        },
        "training_rule": "Closed-loop live-feed material may include reward candidates when receiver delivery and post-action measurements are present. It does not start training, promote a model, or dispatch additional actions.",
        "boundaries": [
            "Controlled executor receipts can supervise execute-vs-hold decisions.",
            "Receiver delivery proof can supervise bounded handoff completion.",
            "Post-action live-feed measurements can produce next-term reward candidates when attribution confidence passes the threshold.",
            "Memory priors may bias only low-risk proposal evidence and cannot override live feed, policy, Executive, or human-approval gates.",
            "Policy and executive labels are deterministic training targets for role-scoped eval/supervised examples.",
            "Reward candidates remain offline material only until a separate training job consumes them.",
            "Held safety, security, guest-message, maintenance, and operations actions stay approval-gated.",
        ],
        "uses_seed_data": False,
        "scripted_case": False,
        "labels_or_reward_changed": False,
        "llm_used_for_reward_or_label": False,
        "eligible_for_reward_training": bool(reward_rows),
        "gcp_training_started": False,
        "model_promotion_started": False,
        "review_dispositions": recorded_reviews,
        "semantic_memory_training_material": semantic_summary,
        "alternative_action_training_material": alternative_summary,
        "substitute_outcome_training_material": substitute_outcome_summary,
    }
    manifest_path = output_dir / "live-feed-training-closure.json"
    examples_path = output_dir / "live-feed-training-examples.jsonl"
    supervised_path = output_dir / "live-feed-supervised-examples.jsonl"
    eval_path = output_dir / "live-feed-eval-examples.jsonl"
    reward_path = output_dir / "live-feed-reward-examples.jsonl"
    manifest["artifacts"] = {
        "manifest": str(manifest_path),
        "examples_jsonl": str(examples_path),
        "supervised_jsonl": str(supervised_path),
        "eval_jsonl": str(eval_path),
        "reward_jsonl": str(reward_path),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_jsonl(examples_path, examples)
    _write_jsonl(supervised_path, supervised)
    _write_jsonl(eval_path, eval_rows)
    _write_jsonl(reward_path, reward_rows)
    return manifest


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Close the latest live-feed agent run into training/eval material.")
    parser.add_argument("--input", default=str(REPO_ROOT / "output/qa/live-feed-agent-smoke.json"))
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "output/qa"))
    parser.add_argument("--no-ledger", action="store_true", help="Do not record review dispositions into the review training ledger.")
    parser.add_argument("--reviewer", default="parkpulse-live-feed-loop-closure")
    args = parser.parse_args()
    manifest = close_live_feed_training_loop(
        Path(args.input),
        Path(args.output_dir),
        record_ledger=not args.no_ledger,
        reviewer=args.reviewer,
    )
    print(json.dumps({"status": manifest["status"], "summary": manifest["summary"], "artifacts": manifest["artifacts"]}, indent=2, sort_keys=True))
    return 0 if manifest["status"] == "closed_loop_materialized" else 1


if __name__ == "__main__":
    raise SystemExit(main())
