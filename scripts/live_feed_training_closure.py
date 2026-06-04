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
    return {
        str(row.get("agent")): row
        for row in receipts
        if isinstance(row, dict) and row.get("agent")
    }


def _event_ids(proposal: dict[str, Any]) -> list[str]:
    grounding = proposal.get("live_feed_grounding", {}) if isinstance(proposal.get("live_feed_grounding"), dict) else {}
    return [str(item) for item in grounding.get("event_ids", []) if item]


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
    examples: list[dict[str, Any]] = []
    for proposal in _proposal_rows(payload):
        envelope = proposal.get("proposal_envelope", {}) if isinstance(proposal.get("proposal_envelope"), dict) else {}
        policy = proposal.get("policy_judge", {}) if isinstance(proposal.get("policy_judge"), dict) else {}
        receipt = receipts.get(str(proposal.get("agent_id")), {})
        result = receipt.get("result", {}) if isinstance(receipt.get("result"), dict) else {}
        action_disposition = receipt.get("action_disposition") or proposal.get("action_disposition")
        if not isinstance(action_disposition, dict):
            action_disposition = {}
        reasoning = proposal.get("department_reasoning", {}) if isinstance(proposal.get("department_reasoning"), dict) else {}
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
                },
                evidence={
                    "policy_reason": policy.get("reason"),
                    "executor_receipt": {
                        "approved_for_controlled_executor": receipt.get("approved_for_controlled_executor"),
                        "result_status": result.get("status"),
                        "idempotency_key": result.get("idempotency_key"),
                        "executed": result.get("executed"),
                    },
                    "live_feed_sources": (proposal.get("live_feed_grounding", {}) if isinstance(proposal.get("live_feed_grounding"), dict) else {}).get("sources", []),
                    "agent_loop": proposal.get("agent_loop", {}),
                    "memory_carry_forward": reasoning.get("memory_carry_forward"),
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
            },
            expected_output={
                "decision": tradeoff.get("decision"),
                "approved_departments": tradeoff.get("approved_departments"),
                "held_departments": tradeoff.get("held_departments"),
                "reason": tradeoff.get("reason"),
            },
            evidence={
                "negotiation_turns": proposals.get("negotiation_turns", []),
                "concrete_policy_count": summary.get("concrete_policy_count"),
                "missing_policy_check_count": summary.get("missing_policy_check_count"),
                "memory_prior_use": memory_prior_use,
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
                },
                expected_output={
                    "label": learning.get("reward_label") or ("reward_ready_controlled_handoff" if reward_ready else "not_reward_ready_until_measured_outcome"),
                    "eligible_for_reward": reward_ready,
                    "reward_value": learning.get("reward_value") if reward_ready else None,
                    "reason": (
                        "Controlled executor outcome memory, receiver delivery proof, and post-action live-feed measurements are present."
                        if reward_ready
                        else "Controlled executor outcome memory exists, but measured post-action attribution is incomplete."
                    ),
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
                        "measurement_rows": outcome_measurement.get("measurement_rows", []),
                    },
                },
                eligible_for_supervised_training=False,
                eligible_for_reward=reward_ready,
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
            "memory_prior_status": (payload.get("live_feed_memory_priors", {}) if isinstance(payload.get("live_feed_memory_priors"), dict) else {}).get("status"),
            "memory_prior_count": (payload.get("live_feed_memory_priors", {}) if isinstance(payload.get("live_feed_memory_priors"), dict) else {}).get("prior_count"),
            "memory_prior_outcome_ids": (payload.get("live_feed_memory_priors", {}) if isinstance(payload.get("live_feed_memory_priors"), dict) else {}).get("latest_outcome_ids", []),
            "memory_prior_applied_count": (((payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}).get("memory_prior_use", {}) if isinstance((payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}).get("memory_prior_use", {}), dict) else {}).get("applied_count")),
            "memory_prior_weak_context_count": (((payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}).get("memory_prior_use", {}) if isinstance((payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}).get("memory_prior_use", {}), dict) else {}).get("weak_context_count")),
            "memory_prior_blocked_count": (((payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}).get("memory_prior_use", {}) if isinstance((payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}).get("memory_prior_use", {}), dict) else {}).get("blocked_count")),
            "memory_prior_accepted_departments": (((payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}).get("memory_prior_use", {}) if isinstance((payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}).get("memory_prior_use", {}), dict) else {}).get("accepted_departments", [])),
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
