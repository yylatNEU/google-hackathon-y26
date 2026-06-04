#!/usr/bin/env python3
from __future__ import annotations

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


DEPARTMENT_AGENT_LOOP = ["observe", "interpret", "predict", "recommend", "justify", "trace"]


def _proposal_has_deep_reasoning(proposal: dict[str, Any]) -> bool:
    reasoning = proposal.get("department_reasoning", {}) if isinstance(proposal.get("department_reasoning"), dict) else {}
    loop = proposal.get("agent_loop", {}) if isinstance(proposal.get("agent_loop"), dict) else {}
    return (
        bool(reasoning.get("diagnosis"))
        and isinstance(reasoning.get("candidate_actions"), list)
        and len(reasoning.get("candidate_actions", [])) >= 2
        and bool(reasoning.get("forecast"))
        and isinstance(reasoning.get("failure_modes"), list)
        and len(reasoning.get("failure_modes", [])) >= 2
        and bool(reasoning.get("selected_rationale"))
        and all(step in loop and loop.get(step) for step in DEPARTMENT_AGENT_LOOP)
    )


async def main() -> int:
    import parkpulse_api

    started = time.perf_counter()
    load_results: dict[str, Any] = {}
    for source, loader in [
        ("ride_ops", parkpulse_api.park_live_ride_ops_feed_load),
        ("guest_flow", parkpulse_api.park_live_guest_flow_feed_load),
        ("staffing", parkpulse_api.park_live_staffing_feed_load),
        ("food_ops", parkpulse_api.park_live_food_ops_feed_load),
        ("operator_signal", parkpulse_api.park_live_operator_signal_feed_load),
    ]:
        try:
            load_results[source] = await loader()
        except Exception as error:
            load_results[source] = {"status": "error", "readiness_issues": [f"{type(error).__name__}: {error}"]}

    payload = await asyncio.wait_for(
        parkpulse_api.park_live_feed_agent_run(
            parkpulse_api.LiveFeedAgentRunRequest(
                refresh_stale=False,
                execute=False,
                controlled_executor_execute=True,
                min_ready_feeds=4,
                require_persisted_events=True,
            )
        ),
        timeout=90,
    )
    live_case = payload.get("live_feed_case", {}) if isinstance(payload.get("live_feed_case"), dict) else {}
    tool_use = payload.get("tool_use_clarity", {}) if isinstance(payload.get("tool_use_clarity"), dict) else {}
    proposals = payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}
    proposal_rows = proposals.get("proposals", []) if isinstance(proposals.get("proposals"), list) else []
    park_profile_summary = payload.get("park_profile_summary", {}) if isinstance(payload.get("park_profile_summary"), dict) else {}
    memory_priors = payload.get("live_feed_memory_priors", {}) if isinstance(payload.get("live_feed_memory_priors"), dict) else {}
    memory_prior_use = proposals.get("memory_prior_use", {}) if isinstance(proposals.get("memory_prior_use"), dict) else {}
    negotiation_rounds = proposals.get("negotiation_rounds", []) if isinstance(proposals.get("negotiation_rounds"), list) else []
    tradeoff_matrix = proposals.get("tradeoff_matrix", []) if isinstance(proposals.get("tradeoff_matrix"), list) else []
    memory_decision_deltas = proposals.get("memory_decision_deltas", []) if isinstance(proposals.get("memory_decision_deltas"), list) else []
    executor_test = payload.get("tool_executor_live_test", {}) if isinstance(payload.get("tool_executor_live_test"), dict) else {}
    hard_follow = payload.get("hard_decision_follow_through", {}) if isinstance(payload.get("hard_decision_follow_through"), dict) else {}
    receiver_delivery = payload.get("live_feed_receiver_delivery", {}) if isinstance(payload.get("live_feed_receiver_delivery"), dict) else {}
    outcome_measurement = payload.get("live_feed_outcome_measurement", {}) if isinstance(payload.get("live_feed_outcome_measurement"), dict) else {}
    outcome_memory = payload.get("live_feed_outcome_memory", {}) if isinstance(payload.get("live_feed_outcome_memory"), dict) else {}
    outcome = outcome_memory.get("outcome", {}) if isinstance(outcome_memory.get("outcome"), dict) else {}
    response_metrics = outcome.get("response_metrics", {}) if isinstance(outcome.get("response_metrics"), dict) else {}
    proposal_count = int(tool_use.get("proposal_count") or 0)
    grounded_proposal_count = int(tool_use.get("live_feed_grounded_proposal_count") or 0)
    deep_reasoning_proposal_count = sum(1 for proposal in proposal_rows if isinstance(proposal, dict) and _proposal_has_deep_reasoning(proposal))
    candidate_action_count = sum(len((proposal.get("department_reasoning", {}) if isinstance(proposal.get("department_reasoning"), dict) else {}).get("candidate_actions", [])) for proposal in proposal_rows if isinstance(proposal, dict))
    failure_mode_count = sum(len((proposal.get("department_reasoning", {}) if isinstance(proposal.get("department_reasoning"), dict) else {}).get("failure_modes", [])) for proposal in proposal_rows if isinstance(proposal, dict))
    action_disposition_count = sum(1 for proposal in proposal_rows if isinstance(proposal, dict) and isinstance(proposal.get("action_disposition"), dict))
    profile_context_count = sum(1 for proposal in proposal_rows if isinstance(proposal, dict) and isinstance(proposal.get("park_profile_context"), dict) and proposal.get("park_profile_context", {}).get("status") == "attached")
    profile_precedence_count = sum(1 for proposal in proposal_rows if isinstance(proposal, dict) and proposal.get("park_profile_context", {}).get("precedence") == "live_feed_over_profile_policy_over_both")
    profile_counterfactual_candidate_count = sum(
        len(
            [
                candidate
                for candidate in ((proposal.get("department_reasoning", {}) if isinstance(proposal.get("department_reasoning"), dict) else {}).get("candidate_actions", []))
                if isinstance(candidate, dict) and isinstance(candidate.get("profile_counterfactual"), dict)
            ]
        )
        for proposal in proposal_rows
        if isinstance(proposal, dict)
    )
    evidence_argument_count = sum(
        1
        for proposal in proposal_rows
        if isinstance(proposal, dict)
        and isinstance(proposal.get("department_reasoning"), dict)
        and proposal["department_reasoning"].get("evidence_argument")
        and "event" in str(proposal["department_reasoning"].get("evidence_argument"))
    )
    disposition_evidence_argument_count = sum(
        1
        for proposal in proposal_rows
        if isinstance(proposal, dict)
        and isinstance(proposal.get("action_disposition"), dict)
        and proposal["action_disposition"].get("evidence_argument")
        and proposal["action_disposition"].get("live_feed_event_ids")
    )
    tradeoff_evidence_argument_count = sum(
        1
        for row in tradeoff_matrix
        if isinstance(row, dict)
        and row.get("evidence_argument")
        and row.get("live_feed_event_ids")
    )
    follow_through_event_link_count = sum(
        1
        for task in hard_follow.get("tasks", [])
        if isinstance(task, dict)
        and isinstance(task.get("review_inputs"), dict)
        and task["review_inputs"].get("live_feed_event_ids")
    )
    missing_policy_check_count = int(tool_use.get("missing_policy_check_count") or 0)
    cooperation_graph_present = bool(tool_use.get("cooperation_graph_present"))
    trace_contract_present = bool((tool_use.get("judge", {}) if isinstance(tool_use.get("judge"), dict) else {}).get("trace_contract_present"))
    concrete_policy_count = sum(
        1
        for row in tool_use.get("tools", [])
        if isinstance(row, dict)
        and row.get("policy_check")
        and not str(row.get("policy_check")).startswith("pending")
    )
    active_departments = (
        (payload.get("agent_orchestration") or payload.get("orchestration") or {})
        .get("department_system", {})
        .get("active_departments", [])
        if isinstance(payload.get("agent_orchestration") or payload.get("orchestration") or {}, dict)
        else []
    )
    passed = (
        payload.get("status") == "complete"
        and payload.get("uses_seed_data") is False
        and payload.get("scripted_case") is False
        and int(live_case.get("persisted_event_count") or 0) > 0
        and int(live_case.get("ready_feed_count") or 0) >= 4
        and proposals.get("mode") == "live_feed_native_department_proposals"
        and proposal_count >= 12
        and grounded_proposal_count == proposal_count
        and deep_reasoning_proposal_count == proposal_count
        and candidate_action_count >= proposal_count * 2
        and failure_mode_count >= proposal_count * 2
        and action_disposition_count == proposal_count
        and profile_context_count == proposal_count
        and profile_precedence_count == proposal_count
        and profile_counterfactual_candidate_count >= proposal_count * 2
        and evidence_argument_count == proposal_count
        and disposition_evidence_argument_count == proposal_count
        and tradeoff_evidence_argument_count == len(tradeoff_matrix)
        and proposals.get("park_profile_context_status") == "attached"
        and len(negotiation_rounds) >= 4
        and len(tradeoff_matrix) == proposal_count
        and missing_policy_check_count == 0
        and concrete_policy_count == proposal_count
        and len(active_departments) >= 10
        and cooperation_graph_present
        and trace_contract_present
        and int(executor_test.get("executed_count") or 0) > 0
        and int(executor_test.get("held_count") or 0) > 0
        and int(executor_test.get("held_disposition_count") or 0) == int(executor_test.get("held_count") or 0)
        and hard_follow.get("status") == "routed"
        and int(hard_follow.get("task_count") or 0) == int(executor_test.get("held_count") or 0)
        and int(hard_follow.get("unresolved_without_owner_count") or 0) == 0
        and follow_through_event_link_count == int(hard_follow.get("task_count") or 0)
        and int(hard_follow.get("active_follow_up_count") or 0) > 0
        and receiver_delivery.get("status") == "proven_controlled"
        and int(receiver_delivery.get("delivered_count") or 0) == int(executor_test.get("executed_count") or 0)
        and int(receiver_delivery.get("acknowledged_count") or 0) == int(executor_test.get("executed_count") or 0)
        and receiver_delivery.get("material_state_mutation") is False
        and int(receiver_delivery.get("public_guest_messages_sent") or 0) == 0
        and outcome_measurement.get("status") == "measured"
        and outcome_measurement.get("measured_outcome_available") is True
        and float(outcome_measurement.get("attribution_confidence") or 0) >= 0.7
        and outcome_measurement.get("eligible_for_reward") is True
        and outcome_memory.get("status") in {"recorded", "skipped"}
        and bool(outcome_memory.get("outcome_id"))
        and response_metrics.get("measuredOutcomeAvailable") is True
    )
    summary = {
        "status": "passed" if passed else "failed",
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "run_status": payload.get("status"),
        "persisted_event_count": live_case.get("persisted_event_count"),
        "ready_feed_count": live_case.get("ready_feed_count"),
        "lead_source": live_case.get("lead_source"),
        "lead_signal_type": live_case.get("lead_signal_type"),
        "proposal_mode": proposals.get("mode"),
        "proposal_count": proposal_count,
        "deep_reasoning_proposal_count": deep_reasoning_proposal_count,
        "candidate_action_count": candidate_action_count,
        "failure_mode_count": failure_mode_count,
        "action_disposition_count": action_disposition_count,
        "profile_context_proposal_count": profile_context_count,
        "profile_precedence_count": profile_precedence_count,
        "profile_counterfactual_candidate_count": profile_counterfactual_candidate_count,
        "evidence_argument_count": evidence_argument_count,
        "disposition_evidence_argument_count": disposition_evidence_argument_count,
        "tradeoff_evidence_argument_count": tradeoff_evidence_argument_count,
        "follow_through_event_link_count": follow_through_event_link_count,
        "park_profile_context_status": proposals.get("park_profile_context_status"),
        "park_profile_summary": park_profile_summary,
        "negotiation_round_count": len(negotiation_rounds),
        "tradeoff_matrix_count": len(tradeoff_matrix),
        "memory_decision_delta_count": len(memory_decision_deltas),
        "live_feed_evidence_count": tool_use.get("live_feed_evidence_count"),
        "live_feed_grounded_proposal_count": grounded_proposal_count,
        "live_feed_memory_priors": {
            "status": memory_priors.get("status"),
            "prior_count": memory_priors.get("prior_count"),
            "latest_outcome_ids": memory_priors.get("latest_outcome_ids", []),
            "applied_count": memory_prior_use.get("applied_count"),
            "applied_prior_outcome_ids": memory_prior_use.get("prior_outcome_ids", []),
            "weak_context_count": memory_prior_use.get("weak_context_count"),
            "blocked_count": memory_prior_use.get("blocked_count"),
            "rejected_count": memory_prior_use.get("rejected_count"),
            "accepted_departments": memory_prior_use.get("accepted_departments", []),
            "blocked_departments": memory_prior_use.get("blocked_departments", []),
        },
        "missing_policy_check_count": missing_policy_check_count,
        "concrete_policy_count": concrete_policy_count,
        "cooperation_graph_present": cooperation_graph_present,
        "tool_executor_live_test": {
            "status": executor_test.get("status"),
            "executed_count": executor_test.get("executed_count"),
            "held_count": executor_test.get("held_count"),
            "held_disposition_count": executor_test.get("held_disposition_count"),
            "receipt_count": executor_test.get("receipt_count"),
        },
        "hard_decision_follow_through": {
            "status": hard_follow.get("status"),
            "task_count": hard_follow.get("task_count"),
            "active_follow_up_count": hard_follow.get("active_follow_up_count"),
            "closed_non_executable_count": hard_follow.get("closed_non_executable_count"),
            "unresolved_without_owner_count": hard_follow.get("unresolved_without_owner_count"),
            "owner_count": hard_follow.get("owner_count"),
        },
        "live_feed_receiver_delivery": {
            "status": receiver_delivery.get("status"),
            "proof_id": receiver_delivery.get("proof_id"),
            "executed_count": receiver_delivery.get("executed_count"),
            "delivered_count": receiver_delivery.get("delivered_count"),
            "acknowledged_count": receiver_delivery.get("acknowledged_count"),
            "public_guest_messages_sent": receiver_delivery.get("public_guest_messages_sent"),
            "material_state_mutation": receiver_delivery.get("material_state_mutation"),
        },
        "live_feed_outcome_measurement": {
            "status": outcome_measurement.get("status"),
            "measurement_id": outcome_measurement.get("measurement_id"),
            "measured_outcome_available": outcome_measurement.get("measured_outcome_available"),
            "attribution_confidence": outcome_measurement.get("attribution_confidence"),
            "eligible_for_reward": outcome_measurement.get("eligible_for_reward"),
            "reward_value": outcome_measurement.get("reward_value"),
            "measured_source_count": len(outcome_measurement.get("measurement_rows", []) if isinstance(outcome_measurement.get("measurement_rows"), list) else []),
        },
        "live_feed_outcome_memory": {
            "status": outcome_memory.get("status"),
            "decision_id": outcome_memory.get("decision_id"),
            "outcome_id": outcome_memory.get("outcome_id"),
            "mongo_collection": outcome_memory.get("mongo_collection"),
        },
        "judge": tool_use.get("judge"),
        "active_departments": active_departments,
        "readiness_issues": payload.get("readiness_issues", []),
    }
    report = {
        "mode": "live_feed_agent_smoke",
        "summary": summary,
        "load_results": load_results,
        "live_feed_case": live_case,
        "live_feed_cooperation": payload.get("live_feed_cooperation"),
        "role_agent_proposals": payload.get("role_agent_proposals"),
        "park_profile_summary": park_profile_summary,
        "live_feed_memory_priors": memory_priors,
        "tool_executor_live_test": executor_test,
        "hard_decision_follow_through": hard_follow,
        "live_feed_receiver_delivery": receiver_delivery,
        "live_feed_outcome_measurement": outcome_measurement,
        "live_feed_outcome_memory": outcome_memory,
        "tool_use_clarity": tool_use,
    }
    output_path = REPO_ROOT / "output/qa/live-feed-agent-smoke.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"summary": summary, "output_json": str(output_path)}, indent=2, sort_keys=True))
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
