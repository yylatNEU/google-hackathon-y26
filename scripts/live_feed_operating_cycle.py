#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import html
import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in {None, ""}:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in {None, ""}:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _json_default(value: Any) -> str:
    return str(value)


DIVERSITY_EVENT_CATALOG = [
    {"kind": "ride_failure", "target_id": "dragonCoaster", "intensity": 84, "domain": "ride_ops"},
    {"kind": "demand_spike", "target_id": "mainStreet", "intensity": 82, "domain": "guest_flow"},
    {"kind": "food_spike", "target_id": "foodCourt1", "intensity": 86, "domain": "food_retail"},
    {"kind": "staff_callout", "target_id": "coasterPlaza", "intensity": 74, "domain": "hr_labor"},
    {"kind": "storm_risk", "target_id": "outdoor_park", "intensity": 82, "domain": "safety"},
    {"kind": "energy_spike", "target_id": "indoorHub", "intensity": 78, "domain": "maintenance"},
    {"kind": "show_dump", "target_id": "coasterPlaza", "intensity": 78, "domain": "guest_flow"},
    {"kind": "mobile_order_outage", "target_id": "foodCourt1", "intensity": 72, "domain": "food_retail"},
    {"kind": "payment_outage", "target_id": "foodCourt1", "intensity": 70, "domain": "finance"},
    {"kind": "access_lane_block", "target_id": "coveredPlaza", "intensity": 76, "domain": "security"},
    {"kind": "water_leak", "target_id": "coveredPlaza", "intensity": 68, "domain": "maintenance"},
    {"kind": "sensor_anomaly", "target_id": "riverRafts", "intensity": 66, "domain": "maintenance"},
    {"kind": "parade_route_conflict", "target_id": "mainStreet", "intensity": 76, "domain": "operations"},
    {"kind": "ticketing_gate_surge", "target_id": "mainGate", "intensity": 74, "domain": "operations"},
    {"kind": "parking_arrival_wave", "target_id": "mainGate", "intensity": 72, "domain": "operations"},
    {"kind": "inventory_stockout", "target_id": "foodCourt1", "intensity": 68, "domain": "food_retail"},
    {"kind": "restroom_closure", "target_id": "coveredPlaza", "intensity": 64, "domain": "guest_experience"},
    {"kind": "radio_dead_zone", "target_id": "coasterPlaza", "intensity": 64, "domain": "security"},
    {"kind": "security_perimeter", "target_id": "mainStreet", "intensity": 76, "domain": "security"},
    {"kind": "heat_index_spike", "target_id": "outdoor_park", "intensity": 80, "domain": "safety"},
    {"kind": "lightning_delay", "target_id": "outdoor_park", "intensity": 88, "domain": "safety"},
]


async def _load_all_live_feeds(parkpulse_api: Any) -> dict[str, Any]:
    results: dict[str, Any] = {}
    loaders = [
        ("weather", parkpulse_api.park_live_weather_feed_load),
        ("ride_ops", parkpulse_api.park_live_ride_ops_feed_load),
        ("guest_flow", parkpulse_api.park_live_guest_flow_feed_load),
        ("staffing", parkpulse_api.park_live_staffing_feed_load),
        ("food_ops", parkpulse_api.park_live_food_ops_feed_load),
        ("operator_signal", parkpulse_api.park_live_operator_signal_feed_load),
    ]
    for source, loader in loaders:
        try:
            results[source] = await loader()
        except Exception as error:
            results[source] = {"status": "error", "readiness_issues": [f"{type(error).__name__}: {error}"]}
    return results


def _proposal_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    proposals = payload.get("role_agent_proposals", {})
    rows = proposals.get("proposals", []) if isinstance(proposals, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def _summarize_payload(payload: dict[str, Any], cycle_index: int, injected_issue: dict[str, Any], load_results: dict[str, Any], closure: dict[str, Any]) -> dict[str, Any]:
    live_case = payload.get("live_feed_case", {}) if isinstance(payload.get("live_feed_case"), dict) else {}
    proposals = payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}
    rows = _proposal_rows(payload)
    executor = payload.get("tool_executor_live_test", {}) if isinstance(payload.get("tool_executor_live_test"), dict) else {}
    hard_follow = payload.get("hard_decision_follow_through", {}) if isinstance(payload.get("hard_decision_follow_through"), dict) else {}
    receiver_delivery = payload.get("live_feed_receiver_delivery", {}) if isinstance(payload.get("live_feed_receiver_delivery"), dict) else {}
    outcome_measurement = payload.get("live_feed_outcome_measurement", {}) if isinstance(payload.get("live_feed_outcome_measurement"), dict) else {}
    outcome_memory = payload.get("live_feed_outcome_memory", {}) if isinstance(payload.get("live_feed_outcome_memory"), dict) else {}
    reward_layers = outcome_measurement.get("reward_layers", {}) if isinstance(outcome_measurement.get("reward_layers"), dict) else {}
    controlled_effect_projection = (
        outcome_measurement.get("controlled_effect_projection", {})
        if isinstance(outcome_measurement.get("controlled_effect_projection"), dict)
        else {}
    )
    memory_priors = payload.get("live_feed_memory_priors", {}) if isinstance(payload.get("live_feed_memory_priors"), dict) else {}
    memory_prior_use = proposals.get("memory_prior_use", {}) if isinstance(proposals.get("memory_prior_use"), dict) else {}
    tradeoff = proposals.get("executive_tradeoff", {}) if isinstance(proposals.get("executive_tradeoff"), dict) else {}
    closure_summary = closure.get("summary", {}) if isinstance(closure.get("summary"), dict) else {}
    issue_event = injected_issue.get("event", {}) if isinstance(injected_issue.get("event"), dict) else {}
    accepted_departments = tradeoff.get("approved_departments", [])
    held_departments = tradeoff.get("held_departments", [])
    if not isinstance(accepted_departments, list):
        accepted_departments = []
    if not isinstance(held_departments, list):
        held_departments = []
    return {
        "cycle": cycle_index,
        "status": "passed" if payload.get("status") == "complete" and closure.get("status") == "closed_loop_materialized" else "review",
        "issue": {
            "status": injected_issue.get("status"),
            "selection_mode": injected_issue.get("selection_mode"),
            "kind": issue_event.get("kind"),
            "target_id": issue_event.get("targetId"),
            "intensity": issue_event.get("intensity"),
            "reason": issue_event.get("reason") or injected_issue.get("message"),
            "unexpected": issue_event.get("unexpected"),
            "visibility": issue_event.get("visibility"),
            "signal_reliability_pct": issue_event.get("signalReliabilityPct"),
        },
        "live_feed": {
            "lead_source": live_case.get("lead_source"),
            "lead_signal_type": live_case.get("lead_signal_type"),
            "persisted_event_count": live_case.get("persisted_event_count"),
            "ready_feed_count": live_case.get("ready_feed_count"),
            "event_ids": live_case.get("live_feed_event_ids", []),
            "loaded_sources": sorted(load_results.keys()),
            "load_error_count": sum(1 for row in load_results.values() if isinstance(row, dict) and row.get("status") == "error"),
        },
        "agents": {
            "proposal_count": len(rows),
            "negotiation_round_count": len(proposals.get("negotiation_rounds", []) if isinstance(proposals.get("negotiation_rounds"), list) else []),
            "tradeoff_matrix_count": len(proposals.get("tradeoff_matrix", []) if isinstance(proposals.get("tradeoff_matrix"), list) else []),
            "memory_decision_delta_count": len(proposals.get("memory_decision_deltas", []) if isinstance(proposals.get("memory_decision_deltas"), list) else []),
            "approved_departments": accepted_departments,
            "held_departments": held_departments,
            "evidence_argument_count": sum(
                1
                for row in rows
                if isinstance(row.get("department_reasoning"), dict) and row["department_reasoning"].get("evidence_argument")
            ),
            "profile_context_count": sum(
                1
                for row in rows
                if isinstance(row.get("park_profile_context"), dict) and row["park_profile_context"].get("status") == "attached"
            ),
        },
        "actions": {
            "executor_status": executor.get("status"),
            "executed_count": executor.get("executed_count"),
            "held_count": executor.get("held_count"),
            "receipt_count": executor.get("receipt_count"),
            "receiver_delivery_status": receiver_delivery.get("status"),
            "delivered_count": receiver_delivery.get("delivered_count"),
            "acknowledged_count": receiver_delivery.get("acknowledged_count"),
            "material_state_mutation": receiver_delivery.get("material_state_mutation"),
            "public_guest_messages_sent": receiver_delivery.get("public_guest_messages_sent"),
            "follow_through_status": hard_follow.get("status"),
            "follow_through_task_count": hard_follow.get("task_count"),
            "active_follow_up_count": hard_follow.get("active_follow_up_count"),
            "unresolved_without_owner_count": hard_follow.get("unresolved_without_owner_count"),
        },
        "memory": {
            "prior_status": memory_priors.get("status"),
            "prior_count": memory_priors.get("prior_count"),
            "latest_prior_outcome_ids": memory_priors.get("latest_outcome_ids", []),
            "applied_count": memory_prior_use.get("applied_count"),
            "accepted_departments": memory_prior_use.get("accepted_departments", []),
            "blocked_departments": memory_prior_use.get("blocked_departments", []),
            "outcome_memory_status": outcome_memory.get("status"),
            "outcome_id": outcome_memory.get("outcome_id"),
            "decision_id": outcome_memory.get("decision_id"),
        },
        "measurement": {
            "status": outcome_measurement.get("status"),
            "measured_outcome_available": outcome_measurement.get("measured_outcome_available"),
            "attribution_confidence": outcome_measurement.get("attribution_confidence"),
            "eligible_for_reward": outcome_measurement.get("eligible_for_reward"),
            "reward_value": outcome_measurement.get("reward_value"),
            "reward_label": outcome_measurement.get("reward_label"),
            "promotion_eligible": outcome_measurement.get("promotion_eligible"),
            "reward_layers": reward_layers,
            "controlled_effect_projection": controlled_effect_projection,
        },
        "training_closure": {
            "status": closure.get("status"),
            "example_count": closure_summary.get("example_count"),
            "supervised_example_count": closure_summary.get("supervised_example_count"),
            "eval_example_count": closure_summary.get("eval_example_count"),
            "reward_example_count": closure_summary.get("reward_example_count"),
            "review_disposition_count": closure_summary.get("review_disposition_count"),
            "artifacts": closure.get("artifacts", {}),
        },
        "truth_boundaries": {
            "uses_seed_data": payload.get("uses_seed_data"),
            "scripted_case": payload.get("scripted_case"),
            "controlled_executor_only": True,
            "real_external_park_connected": False,
            "gcp_training_started_by_closure": closure.get("gcp_training_started"),
            "model_promotion_started_by_closure": closure.get("model_promotion_started"),
        },
    }


def _issue_counts(rows: list[dict[str, Any]], batch_summaries: list[dict[str, Any]] | None = None) -> tuple[Counter[str], Counter[str], Counter[str]]:
    kind_counts: Counter[str] = Counter()
    target_counts: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()
    for row in rows:
        issue = row.get("issue", {}) if isinstance(row.get("issue"), dict) else {}
        kind = str(issue.get("kind") or "")
        target = str(issue.get("target_id") or issue.get("targetId") or "")
        if kind:
            kind_counts[kind] += 1
        if target:
            target_counts[target] += 1
    for summary in batch_summaries or []:
        issue = summary.get("issue", {}) if isinstance(summary.get("issue"), dict) else {}
        kind = str(issue.get("kind") or "")
        target = str(issue.get("target_id") or "")
        if kind:
            kind_counts[kind] += 1
        if target:
            target_counts[target] += 1
    for item in DIVERSITY_EVENT_CATALOG:
        domain = str(item.get("domain") or "")
        kind = str(item.get("kind") or "")
        if domain and kind_counts.get(kind, 0):
            domain_counts[domain] += kind_counts[kind]
    return kind_counts, target_counts, domain_counts


def _select_diverse_issue_plan(case_bank_rows: list[dict[str, Any]], batch_summaries: list[dict[str, Any]], cycle_index: int) -> dict[str, Any]:
    kind_counts, target_counts, domain_counts = _issue_counts(case_bank_rows, batch_summaries)
    scored: list[tuple[float, dict[str, Any]]] = []
    for order, item in enumerate(DIVERSITY_EVENT_CATALOG):
        kind = str(item["kind"])
        target = str(item["target_id"])
        domain = str(item.get("domain") or "")
        score = (
            kind_counts.get(kind, 0) * 100.0
            + target_counts.get(target, 0) * 16.0
            + domain_counts.get(domain, 0) * 5.0
            + order * 0.01
        )
        scored.append((score, item))
    selected = min(scored, key=lambda row: row[0])[1]
    return {
        **selected,
        "selection_mode": "historical_case_bank_diversity",
        "cycle_index": cycle_index,
        "prior_kind_count": kind_counts.get(str(selected["kind"]), 0),
        "prior_target_count": target_counts.get(str(selected["target_id"]), 0),
        "prior_domain_count": domain_counts.get(str(selected.get("domain") or ""), 0),
    }


async def _inject_operating_issue(parkpulse_api: Any, *, cycle_index: int, diversity_control: bool, case_bank_rows: list[dict[str, Any]], batch_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    if not diversity_control:
        result = await parkpulse_api.park_simulation.inject_random_unexpected_event(f"live_feed_operating_cycle_{cycle_index}")
        if isinstance(result, dict):
            result["selection_mode"] = "random_unexpected_event"
        return result
    plan = _select_diverse_issue_plan(case_bank_rows, batch_summaries, cycle_index)
    result = await parkpulse_api.park_simulation.inject_event(str(plan["kind"]), str(plan["target_id"]), _safe_int(plan.get("intensity"), 75))
    if isinstance(result, dict):
        event = result.get("event", {}) if isinstance(result.get("event"), dict) else {}
        event.setdefault("reason", f"Diversity-directed operating stress for underrepresented {plan['kind']} cases.")
        event.setdefault("source", "live_feed_operating_cycle_diversity")
        event.setdefault("unexpected", True)
        event.setdefault("signalReliabilityPct", 90)
        event.setdefault("visibility", "clear")
        result["event"] = event
        result["selection_mode"] = plan["selection_mode"]
        result["diversity_plan"] = plan
    return result


async def _run_cycle(
    cycle_index: int,
    output_dir: Path,
    record_ledger: bool,
    *,
    diversity_control: bool,
    case_bank_rows: list[dict[str, Any]],
    batch_summaries: list[dict[str, Any]],
    agent_timeout_seconds: float,
) -> dict[str, Any]:
    import parkpulse_api
    from live_feed_training_closure import close_live_feed_training_loop

    started = time.perf_counter()
    injected_issue = await _inject_operating_issue(
        parkpulse_api,
        cycle_index=cycle_index,
        diversity_control=diversity_control,
        case_bank_rows=case_bank_rows,
        batch_summaries=batch_summaries,
    )
    await parkpulse_api.park_simulation.step()
    load_results = await _load_all_live_feeds(parkpulse_api)
    payload = await asyncio.wait_for(
        parkpulse_api.park_live_feed_agent_run(
            parkpulse_api.LiveFeedAgentRunRequest(
                refresh_stale=False,
                execute=False,
                controlled_executor_execute=True,
                measure_post_action=True,
                min_ready_feeds=4,
                require_persisted_events=True,
            )
        ),
        timeout=agent_timeout_seconds,
    )
    run_path = output_dir / f"live-feed-operating-cycle-run-{cycle_index}.json"
    run_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")
    closure_dir = output_dir / f"training-cycle-{cycle_index}"
    closure = close_live_feed_training_loop(
        run_path,
        closure_dir,
        record_ledger=record_ledger,
        reviewer="parkpulse-operating-cycle",
    )
    summary = _summarize_payload(payload, cycle_index, injected_issue, load_results, closure)
    summary["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
    summary["artifacts"] = {"run_json": str(run_path), "training_dir": str(closure_dir)}
    return {"summary": summary, "payload": payload, "closure": closure, "load_results": load_results, "injected_issue": injected_issue}


def _run_actual_training_status(min_rows: int, detail: str, timeout_seconds: float) -> dict[str, Any]:
    from park_actual_training import actual_training_status

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(actual_training_status, min_rows, False, detail)
        try:
            return future.result(timeout=timeout_seconds)
        except concurrent.futures.TimeoutError:
            return {
                "status": "timeout",
                "mode": "actual_outcome_training",
                "detail": detail,
                "sample_count": None,
                "min_sample_count": min_rows,
                "debug": {"readiness_issues": [f"actual_training_status exceeded {timeout_seconds:.1f}s timeout."]},
            }


def _deferred_training_status(min_rows: int, new_case_count: int, reward_case_count: int) -> dict[str, Any]:
    return {
        "status": "deferred",
        "mode": "actual_outcome_training",
        "detail": "threshold_gate",
        "source": "live_feed_operating_cycle_case_bank",
        "sample_count": new_case_count,
        "min_sample_count": min_rows,
        "uses_generated_data": False,
        "model": {"status": "not_fit", "reason": "case threshold has not been met"},
        "model_ops": {
            "promotion_gate": {
                "status": "hold",
                "decision": "accumulate_more_cases",
                "observed_rows": new_case_count,
                "minimum_rows": min_rows,
                "reward_candidate_rows": reward_case_count,
            },
            "offline_training_path": {
                "status": "not_started",
                "reason": "Training is intentionally deferred until enough measured outcome cases exist.",
            },
        },
        "debug": {
            "readiness_issues": [
                f"Training threshold not met: need at least {min_rows} closed outcome cases; historical case bank has {new_case_count}.",
                "Training examples and reward candidates were written to the case bank, but no model fit, GCP training, or promotion was started.",
            ]
        },
    }


def _quality_blocked_training_status(min_rows: int, case_bank_summary: dict[str, Any]) -> dict[str, Any]:
    quality_gate = case_bank_summary.get("quality_gate", {}) if isinstance(case_bank_summary.get("quality_gate"), dict) else {}
    blockers = quality_gate.get("blockers", []) if isinstance(quality_gate.get("blockers"), list) else []
    metrics = quality_gate.get("metrics", {}) if isinstance(quality_gate.get("metrics"), dict) else {}
    measured_reward_vector_count = _safe_int(metrics.get("reward_vector_case_count"), _safe_int(case_bank_summary.get("closed_case_count")))
    return {
        "status": "deferred",
        "mode": "actual_outcome_training",
        "detail": "quality_gate",
        "source": "live_feed_operating_cycle_case_bank",
        "sample_count": measured_reward_vector_count,
        "min_sample_count": min_rows,
        "uses_generated_data": False,
        "model": {"status": "not_fit", "reason": "case-bank quality gate has not passed"},
        "model_ops": {
            "promotion_gate": {
                "status": "hold",
                "decision": "improve_case_bank_quality",
                "observed_rows": measured_reward_vector_count,
                "minimum_rows": min_rows,
                "reward_candidate_rows": case_bank_summary.get("reward_candidate_count"),
                "quality_gate": quality_gate,
            },
            "offline_training_path": {
                "status": "not_started",
                "reason": "Training is intentionally deferred until enough diverse, measured, memory-usable cases exist.",
            },
        },
        "debug": {
            "readiness_issues": blockers
            or ["Case-bank quality gate did not pass; no model fit, GCP training, or promotion was started."]
        },
    }


def _apply_case_bank_reward_promotion_guard(actual_training: dict[str, Any], case_bank_summary: dict[str, Any]) -> dict[str, Any]:
    quality_gate = case_bank_summary.get("quality_gate", {}) if isinstance(case_bank_summary.get("quality_gate"), dict) else {}
    metrics = quality_gate.get("metrics", {}) if isinstance(quality_gate.get("metrics"), dict) else {}
    promotion_eligible_count = _safe_int(metrics.get("promotion_eligible_case_count"))
    average_operational_reward = _safe_float(metrics.get("average_operational_reward_vector_only", metrics.get("average_operational_reward")), 0.0)
    promotion_blockers = []
    if promotion_eligible_count <= 0:
        promotion_blockers.append("No reward-vector cases are promotion eligible.")
    if average_operational_reward < 0.55:
        promotion_blockers.append(f"Average operational reward is {average_operational_reward}; promotion requires at least 0.55.")
    if not promotion_blockers:
        return actual_training

    guarded = json.loads(json.dumps(actual_training, default=_json_default))
    model_ops = guarded.setdefault("model_ops", {})
    if not isinstance(model_ops, dict):
        guarded["model_ops"] = {}
        model_ops = guarded["model_ops"]
    original_gate = model_ops.get("promotion_gate", {}) if isinstance(model_ops.get("promotion_gate"), dict) else {}
    model_ops["promotion_gate"] = {
        **original_gate,
        "status": "hold",
        "decision": "train_but_do_not_promote_operational_policy",
        "source": "case_bank_reward_vector_guard",
        "original_gate": original_gate,
        "promotion_eligible_case_count": promotion_eligible_count,
        "average_operational_reward": average_operational_reward,
        "minimum_operational_reward": 0.55,
        "blockers": promotion_blockers,
    }
    guarded["promotion_guard"] = {
        "status": "hold",
        "decision": "train_but_do_not_promote_operational_policy",
        "blockers": promotion_blockers,
    }
    debug = guarded.setdefault("debug", {})
    if isinstance(debug, dict):
        issues = debug.setdefault("readiness_issues", [])
        if isinstance(issues, list):
            issues.extend(f"Promotion guard: {blocker}" for blocker in promotion_blockers)
    return guarded


def _case_bank_paths(case_bank_dir: Path) -> dict[str, Path]:
    return {
        "index": case_bank_dir / "index.jsonl",
        "summary": case_bank_dir / "summary.json",
    }


def _read_case_bank_rows(case_bank_dir: Path) -> list[dict[str, Any]]:
    index_path = _case_bank_paths(case_bank_dir)["index"]
    if not index_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with index_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _case_bank_row_from_summary(summary: dict[str, Any], *, batch_id: str, output_dir: Path) -> dict[str, Any] | None:
    memory = summary.get("memory", {}) if isinstance(summary.get("memory"), dict) else {}
    outcome_id = str(memory.get("outcome_id") or "")
    if not outcome_id:
        return None
    issue = summary.get("issue", {}) if isinstance(summary.get("issue"), dict) else {}
    live_feed = summary.get("live_feed", {}) if isinstance(summary.get("live_feed"), dict) else {}
    agents = summary.get("agents", {}) if isinstance(summary.get("agents"), dict) else {}
    actions = summary.get("actions", {}) if isinstance(summary.get("actions"), dict) else {}
    measurement = summary.get("measurement", {}) if isinstance(summary.get("measurement"), dict) else {}
    reward_layers = measurement.get("reward_layers", {}) if isinstance(measurement.get("reward_layers"), dict) else {}
    controlled_effect_projection = (
        measurement.get("controlled_effect_projection", {})
        if isinstance(measurement.get("controlled_effect_projection"), dict)
        else {}
    )
    training = summary.get("training_closure", {}) if isinstance(summary.get("training_closure"), dict) else {}
    artifacts = summary.get("artifacts", {}) if isinstance(summary.get("artifacts"), dict) else {}
    closed_case = (
        summary.get("status") == "passed"
        and memory.get("outcome_memory_status") == "recorded"
        and measurement.get("measured_outcome_available") is True
        and _safe_int(actions.get("unresolved_without_owner_count")) == 0
    )
    reward_candidate = closed_case and measurement.get("eligible_for_reward") is True and _safe_int(training.get("reward_example_count")) > 0
    return {
        "case_id": f"live_feed_case:{outcome_id}",
        "created_at": _now_iso(),
        "batch_id": batch_id,
        "cycle": summary.get("cycle"),
        "outcome_id": outcome_id,
        "decision_id": memory.get("decision_id"),
        "closed_case": closed_case,
        "reward_candidate": reward_candidate,
        "issue": {
            "kind": issue.get("kind"),
            "target_id": issue.get("target_id"),
            "selection_mode": issue.get("selection_mode"),
            "intensity": issue.get("intensity"),
            "signal_reliability_pct": issue.get("signal_reliability_pct"),
            "visibility": issue.get("visibility"),
            "unexpected": issue.get("unexpected"),
        },
        "live_feed": {
            "lead_source": live_feed.get("lead_source"),
            "lead_signal_type": live_feed.get("lead_signal_type"),
            "ready_feed_count": live_feed.get("ready_feed_count"),
            "persisted_event_count": live_feed.get("persisted_event_count"),
            "event_ids": live_feed.get("event_ids", []),
        },
        "agent_decision": {
            "proposal_count": agents.get("proposal_count"),
            "negotiation_round_count": agents.get("negotiation_round_count"),
            "tradeoff_matrix_count": agents.get("tradeoff_matrix_count"),
            "memory_decision_delta_count": agents.get("memory_decision_delta_count"),
            "approved_departments": agents.get("approved_departments", []),
            "held_departments": agents.get("held_departments", []),
            "evidence_argument_count": agents.get("evidence_argument_count"),
            "profile_context_count": agents.get("profile_context_count"),
        },
        "actions": {
            "executed_count": actions.get("executed_count"),
            "held_count": actions.get("held_count"),
            "active_follow_up_count": actions.get("active_follow_up_count"),
            "unresolved_without_owner_count": actions.get("unresolved_without_owner_count"),
            "receiver_delivery_status": actions.get("receiver_delivery_status"),
            "material_state_mutation": actions.get("material_state_mutation"),
            "public_guest_messages_sent": actions.get("public_guest_messages_sent"),
        },
        "memory": {
            "prior_status": memory.get("prior_status"),
            "prior_count": memory.get("prior_count"),
            "applied_count": memory.get("applied_count"),
            "accepted_departments": memory.get("accepted_departments", []),
            "blocked_departments": memory.get("blocked_departments", []),
        },
        "measurement": {
            "status": measurement.get("status"),
            "attribution_confidence": measurement.get("attribution_confidence"),
            "reward_value": measurement.get("reward_value"),
            "reward_label": measurement.get("reward_label"),
            "eligible_for_reward": measurement.get("eligible_for_reward"),
            "promotion_eligible": measurement.get("promotion_eligible"),
            "reward_layers": reward_layers,
            "controlled_effect_projection": controlled_effect_projection,
        },
        "training_material": {
            "example_count": training.get("example_count"),
            "supervised_example_count": training.get("supervised_example_count"),
            "eval_example_count": training.get("eval_example_count"),
            "reward_example_count": training.get("reward_example_count"),
            "review_disposition_count": training.get("review_disposition_count"),
            "artifacts": training.get("artifacts", {}),
        },
        "source_artifacts": {
            "batch_dir": str(output_dir),
            "run_json": artifacts.get("run_json"),
            "training_dir": artifacts.get("training_dir"),
        },
        "truth_boundaries": summary.get("truth_boundaries", {}),
    }


def _case_bank_quality_gate(
    rows: list[dict[str, Any]],
    *,
    min_training_rows: int,
    min_issue_kinds: int,
    min_targets: int,
    max_dominant_issue_ratio: float,
    min_memory_applied_ratio: float,
) -> dict[str, Any]:
    closed_rows = [row for row in rows if row.get("closed_case") is True]
    reward_rows = [row for row in rows if row.get("reward_candidate") is True]
    kind_counts, target_counts, _domain_counts = _issue_counts(closed_rows)
    dominant_kind, dominant_count = kind_counts.most_common(1)[0] if kind_counts else ("none", 0)
    dominant_ratio = round(dominant_count / max(1, len(closed_rows)), 3)
    memory_applied_rows = [
        row
        for row in closed_rows
        if _safe_int((row.get("memory", {}) if isinstance(row.get("memory"), dict) else {}).get("applied_count")) > 0
    ]
    memory_applied_ratio = round(len(memory_applied_rows) / max(1, len(closed_rows)), 3)
    reward_vector_rows: list[dict[str, Any]] = []
    legacy_scalar_reward_rows: list[dict[str, Any]] = []
    operational_rewards: list[float] = []
    for row in reward_rows:
        measurement = row.get("measurement", {}) if isinstance(row.get("measurement"), dict) else {}
        reward_layers = measurement.get("reward_layers", {}) if isinstance(measurement.get("reward_layers"), dict) else {}
        if reward_layers.get("version") == "live_feed_reward_vector_v1" and "operational_reward" in reward_layers:
            reward_vector_rows.append(row)
            operational_rewards.append(_safe_float(reward_layers.get("operational_reward"), 0.0))
        else:
            legacy_scalar_reward_rows.append(row)
    promotion_eligible_rows = [
        row
        for row in reward_vector_rows
        if (row.get("measurement", {}) if isinstance(row.get("measurement"), dict) else {}).get("promotion_eligible") is True
    ]
    average_operational_reward = round(sum(operational_rewards) / max(1, len(operational_rewards)), 3)
    blockers: list[str] = []
    if len(closed_rows) < min_training_rows:
        blockers.append(f"Need {min_training_rows} closed cases; found {len(closed_rows)}.")
    if len(reward_rows) < min_training_rows:
        blockers.append(f"Need {min_training_rows} reward candidates; found {len(reward_rows)}.")
    if len(reward_vector_rows) < min_training_rows:
        blockers.append(
            f"Need {min_training_rows} reward-vector cases with operational_reward; found {len(reward_vector_rows)}. "
            f"Legacy scalar reward rows kept for trace/eval only: {len(legacy_scalar_reward_rows)}."
        )
    if len(kind_counts) < min_issue_kinds:
        blockers.append(f"Need at least {min_issue_kinds} issue kinds; found {len(kind_counts)}.")
    if len(target_counts) < min_targets:
        blockers.append(f"Need at least {min_targets} targets/zones; found {len(target_counts)}.")
    if dominant_ratio > max_dominant_issue_ratio:
        blockers.append(f"Dominant issue kind ratio too high: {dominant_kind}={dominant_ratio}, max={max_dominant_issue_ratio}.")
    if memory_applied_ratio < min_memory_applied_ratio:
        blockers.append(f"Memory-applied case ratio too low: {memory_applied_ratio}, min={min_memory_applied_ratio}.")
    return {
        "status": "passed" if not blockers else "blocked",
        "ready_for_training": not blockers,
        "blockers": blockers,
        "requirements": {
            "min_training_rows": min_training_rows,
            "min_issue_kinds": min_issue_kinds,
            "min_targets": min_targets,
            "max_dominant_issue_ratio": max_dominant_issue_ratio,
            "min_memory_applied_ratio": min_memory_applied_ratio,
        },
        "metrics": {
            "closed_case_count": len(closed_rows),
            "reward_candidate_count": len(reward_rows),
            "reward_vector_case_count": len(reward_vector_rows),
            "legacy_scalar_reward_case_count": len(legacy_scalar_reward_rows),
            "promotion_eligible_case_count": len(promotion_eligible_rows),
            "average_operational_reward": average_operational_reward,
            "average_operational_reward_vector_only": average_operational_reward,
            "issue_kind_count": len(kind_counts),
            "target_count": len(target_counts),
            "dominant_issue_kind": dominant_kind,
            "dominant_issue_count": dominant_count,
            "dominant_issue_ratio": dominant_ratio,
            "memory_applied_case_count": len(memory_applied_rows),
            "memory_applied_ratio": memory_applied_ratio,
        },
    }


def _case_bank_sustainability_gate(
    rows: list[dict[str, Any]],
    *,
    min_training_rows: int,
    min_promotion_eligible_cases: int = 15,
    min_promotion_eligible_ratio: float = 0.25,
    min_average_operational_reward: float = 0.55,
    recent_window_size: int = 12,
    min_recent_operational_reward: float = 0.55,
    min_recent_promotion_eligible_cases: int = 3,
    min_promotion_issue_kinds: int = 8,
    min_promotion_targets: int = 6,
    min_controlled_effect_projection_ratio: float = 0.75,
) -> dict[str, Any]:
    reward_vector_rows: list[dict[str, Any]] = []
    promotion_eligible_rows: list[dict[str, Any]] = []
    operational_rewards: list[float] = []
    controlled_projection_rows: list[dict[str, Any]] = []
    for row in rows:
        measurement = row.get("measurement", {}) if isinstance(row.get("measurement"), dict) else {}
        reward_layers = measurement.get("reward_layers", {}) if isinstance(measurement.get("reward_layers"), dict) else {}
        if reward_layers.get("version") != "live_feed_reward_vector_v1" or "operational_reward" not in reward_layers:
            continue
        reward_vector_rows.append(row)
        operational_rewards.append(_safe_float(reward_layers.get("operational_reward"), 0.0))
        if measurement.get("promotion_eligible") is True:
            promotion_eligible_rows.append(row)
        projection = measurement.get("controlled_effect_projection", {}) if isinstance(measurement.get("controlled_effect_projection"), dict) else {}
        if projection.get("status") == "applied":
            controlled_projection_rows.append(row)

    promotion_kind_counts, promotion_target_counts, _domain_counts = _issue_counts(promotion_eligible_rows)
    recent_rows = sorted(reward_vector_rows, key=lambda row: str(row.get("created_at") or ""), reverse=True)[:recent_window_size]
    recent_rewards = [
        _safe_float(
            ((row.get("measurement", {}) if isinstance(row.get("measurement"), dict) else {}).get("reward_layers", {}) if isinstance((row.get("measurement", {}) if isinstance(row.get("measurement"), dict) else {}).get("reward_layers"), dict) else {}).get("operational_reward"),
            0.0,
        )
        for row in recent_rows
    ]
    recent_promotion_rows = [
        row
        for row in recent_rows
        if (row.get("measurement", {}) if isinstance(row.get("measurement"), dict) else {}).get("promotion_eligible") is True
    ]
    recent_memory_rows = [
        row
        for row in recent_rows
        if _safe_int((row.get("memory", {}) if isinstance(row.get("memory"), dict) else {}).get("applied_count")) > 0
    ]
    recent_projection_rows = [
        row
        for row in recent_rows
        if ((row.get("measurement", {}) if isinstance(row.get("measurement"), dict) else {}).get("controlled_effect_projection", {}) if isinstance((row.get("measurement", {}) if isinstance(row.get("measurement"), dict) else {}).get("controlled_effect_projection"), dict) else {}).get("status") == "applied"
    ]
    average_operational_reward = round(sum(operational_rewards) / max(1, len(operational_rewards)), 3)
    promotion_ratio = round(len(promotion_eligible_rows) / max(1, len(reward_vector_rows)), 3)
    recent_average_operational_reward = round(sum(recent_rewards) / max(1, len(recent_rewards)), 3)
    recent_memory_applied_ratio = round(len(recent_memory_rows) / max(1, len(recent_rows)), 3)
    controlled_projection_ratio = round(len(controlled_projection_rows) / max(1, len(reward_vector_rows)), 3)

    blockers: list[str] = []
    if len(reward_vector_rows) < min_training_rows:
        blockers.append(f"Need {min_training_rows} reward-vector cases for sustainable growth; found {len(reward_vector_rows)}.")
    if len(promotion_eligible_rows) < min_promotion_eligible_cases:
        blockers.append(f"Need {min_promotion_eligible_cases} promotion-eligible cases; found {len(promotion_eligible_rows)}.")
    if promotion_ratio < min_promotion_eligible_ratio:
        blockers.append(f"Promotion-eligible ratio too low: {promotion_ratio}, min={min_promotion_eligible_ratio}.")
    if average_operational_reward < min_average_operational_reward:
        blockers.append(f"Average operational reward too low: {average_operational_reward}, min={min_average_operational_reward}.")
    if recent_average_operational_reward < min_recent_operational_reward:
        blockers.append(f"Recent operational reward too low: {recent_average_operational_reward}, min={min_recent_operational_reward}.")
    if len(recent_promotion_rows) < min_recent_promotion_eligible_cases:
        blockers.append(f"Need {min_recent_promotion_eligible_cases} promotion-eligible cases in the latest {recent_window_size}; found {len(recent_promotion_rows)}.")
    if len(promotion_kind_counts) < min_promotion_issue_kinds:
        blockers.append(f"Promotion evidence needs {min_promotion_issue_kinds} issue kinds; found {len(promotion_kind_counts)}.")
    if len(promotion_target_counts) < min_promotion_targets:
        blockers.append(f"Promotion evidence needs {min_promotion_targets} targets/zones; found {len(promotion_target_counts)}.")
    if controlled_projection_ratio < min_controlled_effect_projection_ratio:
        blockers.append(f"Controlled-effect projection coverage too low: {controlled_projection_ratio}, min={min_controlled_effect_projection_ratio}.")

    return {
        "status": "growing" if not blockers else "watch",
        "ready_for_sustainable_growth": not blockers,
        "blockers": blockers,
        "requirements": {
            "min_training_rows": min_training_rows,
            "min_promotion_eligible_cases": min_promotion_eligible_cases,
            "min_promotion_eligible_ratio": min_promotion_eligible_ratio,
            "min_average_operational_reward": min_average_operational_reward,
            "recent_window_size": recent_window_size,
            "min_recent_operational_reward": min_recent_operational_reward,
            "min_recent_promotion_eligible_cases": min_recent_promotion_eligible_cases,
            "min_promotion_issue_kinds": min_promotion_issue_kinds,
            "min_promotion_targets": min_promotion_targets,
            "min_controlled_effect_projection_ratio": min_controlled_effect_projection_ratio,
        },
        "metrics": {
            "reward_vector_case_count": len(reward_vector_rows),
            "promotion_eligible_case_count": len(promotion_eligible_rows),
            "promotion_eligible_ratio": promotion_ratio,
            "promotion_issue_kind_count": len(promotion_kind_counts),
            "promotion_target_count": len(promotion_target_counts),
            "average_operational_reward": average_operational_reward,
            "recent_window_size": len(recent_rows),
            "recent_average_operational_reward": recent_average_operational_reward,
            "recent_promotion_eligible_case_count": len(recent_promotion_rows),
            "recent_memory_applied_ratio": recent_memory_applied_ratio,
            "controlled_effect_projection_case_count": len(controlled_projection_rows),
            "controlled_effect_projection_ratio": controlled_projection_ratio,
            "recent_controlled_effect_projection_count": len(recent_projection_rows),
        },
    }


def _case_bank_summary(
    rows: list[dict[str, Any]],
    *,
    added_count: int,
    duplicate_count: int,
    case_bank_dir: Path,
    min_training_rows: int = 50,
    min_issue_kinds: int = 12,
    min_targets: int = 6,
    max_dominant_issue_ratio: float = 0.3,
    min_memory_applied_ratio: float = 0.45,
) -> dict[str, Any]:
    closed_rows = [row for row in rows if row.get("closed_case") is True]
    reward_rows = [row for row in rows if row.get("reward_candidate") is True]
    kind_counts, target_counts, _domain_counts = _issue_counts(rows)
    issue_kinds = sorted(kind_counts)
    targets = sorted(target_counts)
    latest_rows = sorted(rows, key=lambda row: str(row.get("created_at") or ""), reverse=True)[:10]
    quality_gate = _case_bank_quality_gate(
        rows,
        min_training_rows=min_training_rows,
        min_issue_kinds=min_issue_kinds,
        min_targets=min_targets,
        max_dominant_issue_ratio=max_dominant_issue_ratio,
        min_memory_applied_ratio=min_memory_applied_ratio,
    )
    sustainability_gate = _case_bank_sustainability_gate(
        rows,
        min_training_rows=min_training_rows,
    )
    return {
        "status": "ready",
        "mode": "append_only_live_feed_case_bank",
        "case_bank_dir": str(case_bank_dir),
        "index_path": str(_case_bank_paths(case_bank_dir)["index"]),
        "summary_path": str(_case_bank_paths(case_bank_dir)["summary"]),
        "total_case_count": len(rows),
        "closed_case_count": len(closed_rows),
        "reward_candidate_count": len(reward_rows),
        "issue_kind_count": len(issue_kinds),
        "issue_kinds": issue_kinds,
        "issue_kind_counts": dict(sorted(kind_counts.items())),
        "target_count": len(targets),
        "targets": targets,
        "target_counts": dict(sorted(target_counts.items())),
        "added_count": added_count,
        "duplicate_count": duplicate_count,
        "latest_outcome_ids": [row.get("outcome_id") for row in latest_rows if row.get("outcome_id")],
        "dedupe_key": "outcome_id",
        "append_only": True,
        "training_threshold_uses": "historical closed_case_count plus reward-vector cases with operational_reward; legacy scalar reward rows are trace/eval material only",
        "quality_gate": quality_gate,
        "sustainability_gate": sustainability_gate,
        "updated_at": _now_iso(),
    }


def _append_case_bank(
    cycle_summaries: list[dict[str, Any]],
    *,
    case_bank_dir: Path,
    batch_id: str,
    output_dir: Path,
    min_training_rows: int = 50,
    min_issue_kinds: int = 12,
    min_targets: int = 6,
    max_dominant_issue_ratio: float = 0.3,
    min_memory_applied_ratio: float = 0.45,
) -> dict[str, Any]:
    case_bank_dir.mkdir(parents=True, exist_ok=True)
    paths = _case_bank_paths(case_bank_dir)
    existing_rows = _read_case_bank_rows(case_bank_dir)
    existing_ids = {str(row.get("outcome_id")) for row in existing_rows if row.get("outcome_id")}
    added_rows: list[dict[str, Any]] = []
    duplicate_count = 0
    for summary in cycle_summaries:
        row = _case_bank_row_from_summary(summary, batch_id=batch_id, output_dir=output_dir)
        if not row:
            continue
        if str(row.get("outcome_id")) in existing_ids:
            duplicate_count += 1
            continue
        added_rows.append(row)
        existing_ids.add(str(row.get("outcome_id")))
    if added_rows:
        with paths["index"].open("a", encoding="utf-8") as handle:
            for row in added_rows:
                handle.write(json.dumps(row, sort_keys=True, default=_json_default) + "\n")
    all_rows = [*existing_rows, *added_rows]
    summary = _case_bank_summary(
        all_rows,
        added_count=len(added_rows),
        duplicate_count=duplicate_count,
        case_bank_dir=case_bank_dir,
        min_training_rows=min_training_rows,
        min_issue_kinds=min_issue_kinds,
        min_targets=min_targets,
        max_dominant_issue_ratio=max_dominant_issue_ratio,
        min_memory_applied_ratio=min_memory_applied_ratio,
    )
    paths["summary"].write_text(json.dumps(summary, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")
    return {"summary": summary, "added_rows": added_rows}


def _aggregate_report(cycles: list[dict[str, Any]], actual_training: dict[str, Any], started_at: str, case_bank: dict[str, Any]) -> dict[str, Any]:
    summaries = [row["summary"] for row in cycles]
    outcome_ids = [
        str(summary.get("memory", {}).get("outcome_id"))
        for summary in summaries
        if isinstance(summary.get("memory"), dict) and summary.get("memory", {}).get("outcome_id")
    ]
    prior_counts = [_safe_int(summary.get("memory", {}).get("prior_count")) for summary in summaries if isinstance(summary.get("memory"), dict)]
    applied_counts = [_safe_int(summary.get("memory", {}).get("applied_count")) for summary in summaries if isinstance(summary.get("memory"), dict)]
    training_examples = sum(_safe_int(summary.get("training_closure", {}).get("example_count")) for summary in summaries if isinstance(summary.get("training_closure"), dict))
    reward_examples = sum(_safe_int(summary.get("training_closure", {}).get("reward_example_count")) for summary in summaries if isinstance(summary.get("training_closure"), dict))
    executed = sum(_safe_int(summary.get("actions", {}).get("executed_count")) for summary in summaries if isinstance(summary.get("actions"), dict))
    held = sum(_safe_int(summary.get("actions", {}).get("held_count")) for summary in summaries if isinstance(summary.get("actions"), dict))
    unresolved = sum(_safe_int(summary.get("actions", {}).get("unresolved_without_owner_count")) for summary in summaries if isinstance(summary.get("actions"), dict))
    active_followups = sum(_safe_int(summary.get("actions", {}).get("active_follow_up_count")) for summary in summaries if isinstance(summary.get("actions"), dict))
    memory_growth = {
        "outcome_ids_written": outcome_ids,
        "unique_outcome_id_count": len(set(outcome_ids)),
        "first_prior_count": prior_counts[0] if prior_counts else 0,
        "last_prior_count": prior_counts[-1] if prior_counts else 0,
        "max_prior_count": max(prior_counts) if prior_counts else 0,
        "total_memory_applied_count": sum(applied_counts),
        "memory_help_observed": bool(sum(applied_counts) > 0 or (prior_counts and prior_counts[-1] > prior_counts[0])),
    }
    model_ops = actual_training.get("model_ops", {}) if isinstance(actual_training.get("model_ops"), dict) else {}
    promotion_gate = model_ops.get("promotion_gate", {}) if isinstance(model_ops.get("promotion_gate"), dict) else {}
    model = actual_training.get("model", {}) if isinstance(actual_training.get("model"), dict) else {}
    actual_debug = actual_training.get("debug", {}) if isinstance(actual_training.get("debug"), dict) else {}
    case_bank_summary = case_bank.get("summary", {}) if isinstance(case_bank.get("summary"), dict) else {}
    quality_gate = case_bank_summary.get("quality_gate", {}) if isinstance(case_bank_summary.get("quality_gate"), dict) else {}
    sustainability_gate = case_bank_summary.get("sustainability_gate", {}) if isinstance(case_bank_summary.get("sustainability_gate"), dict) else {}
    status = "passed" if summaries and all(summary.get("status") == "passed" for summary in summaries) and unresolved == 0 else "review"
    return {
        "created_at": _now_iso(),
        "started_at": started_at,
        "status": status,
        "mode": "live_feed_operating_cycle_memory_training_validation",
        "summary": {
            "cycle_count": len(summaries),
            "passed_cycle_count": sum(1 for summary in summaries if summary.get("status") == "passed"),
            "generated_issue_count": len([summary for summary in summaries if summary.get("issue", {}).get("status") == "success"]),
            "executed_action_count": executed,
            "held_action_count": held,
            "active_follow_up_count": active_followups,
            "unresolved_without_owner_count": unresolved,
            "training_example_count": training_examples,
            "reward_example_count": reward_examples,
            "case_bank_total_case_count": case_bank_summary.get("total_case_count"),
            "case_bank_closed_case_count": case_bank_summary.get("closed_case_count"),
            "case_bank_reward_candidate_count": case_bank_summary.get("reward_candidate_count"),
            "case_bank_added_count": case_bank_summary.get("added_count"),
            "case_bank_duplicate_count": case_bank_summary.get("duplicate_count"),
            "case_bank_quality_status": quality_gate.get("status"),
            "case_bank_sustainability_status": sustainability_gate.get("status"),
            "memory_growth": memory_growth,
            "actual_training_status": actual_training.get("status"),
            "actual_training_sample_count": actual_training.get("sample_count"),
            "actual_training_min_sample_count": actual_training.get("min_sample_count"),
            "local_policy_id": model.get("best_policy_id") or model_ops.get("current_policy_id"),
            "promotion_gate_status": promotion_gate.get("status"),
            "promotion_gate_decision": promotion_gate.get("decision"),
        },
        "case_bank": case_bank_summary,
        "cycles": summaries,
        "actual_training": {
            "status": actual_training.get("status"),
            "mode": actual_training.get("mode"),
            "detail": actual_training.get("detail", "full"),
            "source": actual_training.get("source"),
            "sample_count": actual_training.get("sample_count"),
            "min_sample_count": actual_training.get("min_sample_count"),
            "uses_generated_data": actual_training.get("uses_generated_data"),
            "model": model,
            "model_ops": {
                "version": model_ops.get("version"),
                "current_policy_id": model_ops.get("current_policy_id"),
                "promotion_gate": promotion_gate,
                "fitness_curve": model_ops.get("fitness_curve"),
                "scenario_fitness": model_ops.get("scenario_fitness"),
                "offline_training_path": model_ops.get("offline_training_path"),
                "live_weather_training_gate": model_ops.get("live_weather_training_gate"),
                "live_ride_ops_training_gate": model_ops.get("live_ride_ops_training_gate"),
                "live_guest_flow_training_gate": model_ops.get("live_guest_flow_training_gate"),
                "live_staffing_training_gate": model_ops.get("live_staffing_training_gate"),
                "live_food_ops_training_gate": model_ops.get("live_food_ops_training_gate"),
                "live_operator_signal_training_gate": model_ops.get("live_operator_signal_training_gate"),
            },
            "readiness_issues": actual_debug.get("readiness_issues", []),
            "gcp_ml": actual_training.get("gcp_ml", {}),
        },
        "truth_boundaries": [
            "This is the app live-state simulation and persisted live-feed layer, not an external real park connection.",
            "Issues are generated as unexpected operating events on the current park state, then live feeds are refreshed from that state.",
            "The controlled executor executes only bounded internal tool envelopes and records receiver acknowledgements; public guest messages and material state mutation stay disabled in this validation.",
            "The historical case bank is append-only and dedupes by outcome_id, so reruns do not erase or double-count prior cases.",
            "Training closure materializes supervised, eval, and reward-candidate files. It does not by itself start GCP training or promote a production model.",
            "The actual-training call fits/evaluates the local observed-outcome policy path when enough rows exist; promotion remains gated by sample count, feed gates, fitness, and rollback rules.",
        ],
    }


def _badge(value: Any) -> str:
    text = html.escape(str(value))
    normalized = str(value).lower()
    cls = "ok" if normalized in {"passed", "ready", "success", "recorded", "growing", "eligible_live_weather", "eligible_live_ride_ops", "eligible_live_guest_flow", "eligible_live_staffing", "eligible_live_food_ops", "eligible_live_operator_signal"} else "warn" if normalized in {"review", "hold", "not_ready", "timeout", "watch"} else "muted"
    return f'<span class="badge {cls}">{text}</span>'


def _render_html(report: dict[str, Any], path: Path) -> None:
    summary = report.get("summary", {}) if isinstance(report.get("summary"), dict) else {}
    cycles = report.get("cycles", []) if isinstance(report.get("cycles"), list) else []
    actual = report.get("actual_training", {}) if isinstance(report.get("actual_training"), dict) else {}
    case_bank = report.get("case_bank", {}) if isinstance(report.get("case_bank"), dict) else {}
    quality_gate = case_bank.get("quality_gate", {}) if isinstance(case_bank.get("quality_gate"), dict) else {}
    quality_metrics = quality_gate.get("metrics", {}) if isinstance(quality_gate.get("metrics"), dict) else {}
    quality_blockers = quality_gate.get("blockers", []) if isinstance(quality_gate.get("blockers"), list) else []
    sustainability_gate = case_bank.get("sustainability_gate", {}) if isinstance(case_bank.get("sustainability_gate"), dict) else {}
    sustainability_metrics = sustainability_gate.get("metrics", {}) if isinstance(sustainability_gate.get("metrics"), dict) else {}
    sustainability_blockers = sustainability_gate.get("blockers", []) if isinstance(sustainability_gate.get("blockers"), list) else []
    memory_growth = summary.get("memory_growth", {}) if isinstance(summary.get("memory_growth"), dict) else {}
    cycle_cards = []
    for cycle in cycles:
        issue = cycle.get("issue", {}) if isinstance(cycle.get("issue"), dict) else {}
        actions = cycle.get("actions", {}) if isinstance(cycle.get("actions"), dict) else {}
        memory = cycle.get("memory", {}) if isinstance(cycle.get("memory"), dict) else {}
        agents = cycle.get("agents", {}) if isinstance(cycle.get("agents"), dict) else {}
        measurement = cycle.get("measurement", {}) if isinstance(cycle.get("measurement"), dict) else {}
        reward_layers = measurement.get("reward_layers", {}) if isinstance(measurement.get("reward_layers"), dict) else {}
        controlled_effect_projection = (
            measurement.get("controlled_effect_projection", {})
            if isinstance(measurement.get("controlled_effect_projection"), dict)
            else {}
        )
        training = cycle.get("training_closure", {}) if isinstance(cycle.get("training_closure"), dict) else {}
        cycle_cards.append(
            f"""
            <section class="cycle">
              <div class="cycle-head">
                <h2>Cycle {html.escape(str(cycle.get('cycle')))}</h2>
                {_badge(cycle.get('status'))}
              </div>
              <div class="grid four">
                <div><strong>Generated issue</strong><span>{html.escape(str(issue.get('kind')))} at {html.escape(str(issue.get('target_id')))}</span><small>Intensity {html.escape(str(issue.get('intensity')))}, reliability {html.escape(str(issue.get('signal_reliability_pct')))}%</small></div>
                <div><strong>Agent board</strong><span>{html.escape(str(agents.get('proposal_count')))} proposals, {html.escape(str(agents.get('negotiation_round_count')))} negotiation rounds</span><small>{html.escape(str(agents.get('memory_decision_delta_count')))} memory decision deltas</small></div>
                <div><strong>Actions</strong><span>{html.escape(str(actions.get('executed_count')))} executed, {html.escape(str(actions.get('held_count')))} held</span><small>{html.escape(str(actions.get('active_follow_up_count')))} active follow-ups, {html.escape(str(actions.get('unresolved_without_owner_count')))} ownerless</small></div>
                <div><strong>Learning</strong><span>{html.escape(str(training.get('example_count')))} examples, {html.escape(str(training.get('reward_example_count')))} reward candidates</span><small>{html.escape(str(memory.get('outcome_id')))}</small></div>
              </div>
              <div class="decision">
                <p><b>Why this was not scripted:</b> the event came from the current park simulation state, then live feeds were reloaded and agents grounded decisions in persisted feed event IDs.</p>
                <p><b>Memory use:</b> prior status {html.escape(str(memory.get('prior_status')))}, prior count {html.escape(str(memory.get('prior_count')))}, applied {html.escape(str(memory.get('applied_count')))}. Accepted departments: {html.escape(', '.join(str(x) for x in memory.get('accepted_departments', [])[:8]) or 'none')}.</p>
                <p><b>Measured outcome:</b> {html.escape(str(measurement.get('status')))} with attribution confidence {html.escape(str(measurement.get('attribution_confidence')))} and operational reward {html.escape(str(reward_layers.get('operational_reward', measurement.get('reward_value'))))}. Promotion eligible: {html.escape(str(measurement.get('promotion_eligible')))}.</p>
                <p><b>Reward layers:</b> trace {html.escape(str(reward_layers.get('trace_reward')))}, policy {html.escape(str(reward_layers.get('policy_reward')))}, execution {html.escape(str(reward_layers.get('execution_reward')))}, operational {html.escape(str(reward_layers.get('operational_reward')))}, learning {html.escape(str(reward_layers.get('learning_reward')))}.</p>
                <p><b>Controlled effect:</b> {html.escape(str(controlled_effect_projection.get('status') or 'not_applied'))}; {html.escape(str(controlled_effect_projection.get('projection_count') or 0))} projected feed rows from acknowledged low-risk receiver actions.</p>
              </div>
            </section>
            """
        )
    readiness_issues = actual.get("readiness_issues", [])
    if not isinstance(readiness_issues, list):
        readiness_issues = []
    issue_items = "".join(f"<li>{html.escape(str(item))}</li>" for item in readiness_issues[:10]) or "<li>No readiness blockers reported.</li>"
    quality_items = "".join(f"<li>{html.escape(str(item))}</li>" for item in quality_blockers[:10]) or "<li>Quality gate passed.</li>"
    sustainability_items = "".join(f"<li>{html.escape(str(item))}</li>" for item in sustainability_blockers[:10]) or "<li>Sustainable growth gate passed.</li>"
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ParkPulse Operating Cycle Learning Report</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #17212b;
      --muted: #5d6875;
      --line: #d9e1e8;
      --panel: #f7fafc;
      --ok: #0f7a55;
      --warn: #a45f00;
      --accent: #1d5f8f;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: var(--ink); background: #ffffff; }}
    header {{ padding: 32px 40px 24px; border-bottom: 1px solid var(--line); }}
    h1 {{ margin: 0 0 10px; font-size: 30px; line-height: 1.12; letter-spacing: 0; }}
    h2 {{ margin: 0; font-size: 18px; letter-spacing: 0; }}
    p {{ margin: 0; line-height: 1.5; }}
    main {{ padding: 24px 40px 42px; }}
    .lede {{ color: var(--muted); max-width: 980px; }}
    .grid {{ display: grid; gap: 12px; margin-top: 18px; }}
    .four {{ grid-template-columns: repeat(4, minmax(0, 1fr)); }}
    .three {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    .grid > div {{ border: 1px solid var(--line); border-radius: 8px; padding: 14px; background: var(--panel); min-height: 96px; }}
    strong {{ display: block; font-size: 12px; text-transform: uppercase; color: var(--muted); margin-bottom: 8px; letter-spacing: 0; }}
    span {{ display: block; font-size: 21px; font-weight: 700; line-height: 1.2; }}
    small {{ display: block; color: var(--muted); margin-top: 8px; line-height: 1.35; }}
    .badge {{ display: inline-flex; align-items: center; width: fit-content; border-radius: 999px; padding: 4px 9px; font-size: 12px; font-weight: 700; border: 1px solid var(--line); }}
    .badge.ok {{ color: var(--ok); background: #eaf8f2; border-color: #bfe8d8; }}
    .badge.warn {{ color: var(--warn); background: #fff4df; border-color: #f0d6a7; }}
    .badge.muted {{ color: var(--muted); background: #f3f6f8; }}
    .section-title {{ display: flex; align-items: center; justify-content: space-between; margin: 28px 0 12px; }}
    .cycle {{ border-top: 1px solid var(--line); padding: 22px 0 6px; }}
    .cycle-head {{ display: flex; justify-content: space-between; align-items: center; gap: 16px; }}
    .decision {{ margin-top: 14px; display: grid; gap: 8px; color: #293847; }}
    .truth {{ border: 1px solid var(--line); border-radius: 8px; padding: 16px; background: #fbfcfd; }}
    ul {{ margin: 10px 0 0; padding-left: 20px; color: #293847; }}
    li {{ margin: 6px 0; }}
    footer {{ color: var(--muted); padding-top: 24px; border-top: 1px solid var(--line); margin-top: 28px; }}
    @media (max-width: 980px) {{ header, main {{ padding-left: 18px; padding-right: 18px; }} .four, .three {{ grid-template-columns: 1fr; }} span {{ font-size: 18px; }} }}
  </style>
</head>
<body>
  <header>
    <h1>Operating Cycle Learning Report</h1>
    <p class="lede">ParkPulse generated unexpected operating issues, refreshed live-state feeds, ran department-agent negotiation, executed bounded internal actions, wrote memory, closed training material, and checked the actual-training path.</p>
  </header>
  <main>
    <section>
      <div class="grid four">
        <div><strong>Cycles</strong><span>{html.escape(str(summary.get('passed_cycle_count')))} / {html.escape(str(summary.get('cycle_count')))} passed</span><small>Status {_badge(report.get('status'))}</small></div>
        <div><strong>Actions</strong><span>{html.escape(str(summary.get('executed_action_count')))} executed</span><small>{html.escape(str(summary.get('held_action_count')))} held, {html.escape(str(summary.get('active_follow_up_count')))} active follow-ups</small></div>
        <div><strong>Memory growth</strong><span>{html.escape(str(memory_growth.get('unique_outcome_id_count')))} outcomes</span><small>Prior count {html.escape(str(memory_growth.get('first_prior_count')))} to {html.escape(str(memory_growth.get('last_prior_count')))}, applied {html.escape(str(memory_growth.get('total_memory_applied_count')))}</small></div>
        <div><strong>Training material</strong><span>{html.escape(str(summary.get('training_example_count')))} examples</span><small>{html.escape(str(summary.get('reward_example_count')))} reward candidates</small></div>
      </div>
    </section>

    <section>
      <div class="section-title"><h2>Historical Case Bank</h2>{_badge(case_bank.get('status'))}</div>
      <div class="grid four">
        <div><strong>Total cases</strong><span>{html.escape(str(case_bank.get('total_case_count')))}</span><small>Append-only, dedupe key: {html.escape(str(case_bank.get('dedupe_key')))}</small></div>
        <div><strong>Closed cases</strong><span>{html.escape(str(case_bank.get('closed_case_count')))}</span><small>Historical memory, trace, and eval material</small></div>
        <div><strong>Reward candidates</strong><span>{html.escape(str(case_bank.get('reward_candidate_count')))}</span><small>Added this run: {html.escape(str(case_bank.get('added_count')))}, duplicates skipped: {html.escape(str(case_bank.get('duplicate_count')))}</small></div>
        <div><strong>Diversity</strong><span>{html.escape(str(case_bank.get('issue_kind_count')))} issue kinds</span><small>{html.escape(', '.join(str(x) for x in case_bank.get('issue_kinds', [])[:5]))}</small></div>
      </div>
      <div class="grid four">
        <div><strong>Quality gate</strong><span>{html.escape(str(quality_gate.get('status')))}</span><small>Training can start only when this passes.</small></div>
        <div><strong>Targets</strong><span>{html.escape(str(quality_metrics.get('target_count')))}</span><small>Dominant issue: {html.escape(str(quality_metrics.get('dominant_issue_kind')))} ({html.escape(str(quality_metrics.get('dominant_issue_ratio')) )})</small></div>
        <div><strong>Memory use</strong><span>{html.escape(str(quality_metrics.get('memory_applied_ratio')))}</span><small>{html.escape(str(quality_metrics.get('memory_applied_case_count')))} cases used prior memory</small></div>
        <div><strong>Reward vectors</strong><span>{html.escape(str(quality_metrics.get('reward_vector_case_count')))}</span><small>{html.escape(str(quality_metrics.get('legacy_scalar_reward_case_count')))} legacy scalar rows kept for trace/eval</small></div>
      </div>
      <div class="grid three">
        <div><strong>Operational reward</strong><span>{html.escape(str(quality_metrics.get('average_operational_reward_vector_only', quality_metrics.get('average_operational_reward'))))}</span><small>Vector-only average; scalar fallback is excluded</small></div>
        <div><strong>Promotion evidence</strong><span>{html.escape(str(quality_metrics.get('promotion_eligible_case_count')))}</span><small>Cases with enough operational lift and policy gate pass</small></div>
        <div><strong>Threshold basis</strong><span>reward vector</span><small>{html.escape(str(case_bank.get('training_threshold_uses')))}</small></div>
      </div>
      <div class="truth">
        <strong>Quality gate issues</strong>
        <ul>{quality_items}</ul>
      </div>
    </section>

    <section>
      <div class="section-title"><h2>Sustainable Growth</h2>{_badge(sustainability_gate.get('status'))}</div>
      <div class="grid four">
        <div><strong>Promotion cases</strong><span>{html.escape(str(sustainability_metrics.get('promotion_eligible_case_count')))}</span><small>Ratio {html.escape(str(sustainability_metrics.get('promotion_eligible_ratio')))}</small></div>
        <div><strong>Recent reward</strong><span>{html.escape(str(sustainability_metrics.get('recent_average_operational_reward')))}</span><small>{html.escape(str(sustainability_metrics.get('recent_promotion_eligible_case_count')))} promotion cases in latest {html.escape(str(sustainability_metrics.get('recent_window_size')))}</small></div>
        <div><strong>Promotion diversity</strong><span>{html.escape(str(sustainability_metrics.get('promotion_issue_kind_count')))} kinds</span><small>{html.escape(str(sustainability_metrics.get('promotion_target_count')))} targets/zones</small></div>
        <div><strong>Effect coverage</strong><span>{html.escape(str(sustainability_metrics.get('controlled_effect_projection_ratio')))}</span><small>{html.escape(str(sustainability_metrics.get('controlled_effect_projection_case_count')))} cases with controlled-effect projection</small></div>
      </div>
      <div class="truth">
        <strong>Sustainability gate issues</strong>
        <ul>{sustainability_items}</ul>
      </div>
    </section>

    <section>
      <div class="section-title"><h2>Actual Training Check</h2>{_badge(actual.get('status'))}</div>
      <div class="grid three">
        <div><strong>Observed rows</strong><span>{html.escape(str(actual.get('sample_count')))} / {html.escape(str(actual.get('min_sample_count')))}</span><small>Source: {html.escape(str(actual.get('source')))}</small></div>
        <div><strong>Local policy</strong><span>{html.escape(str(summary.get('local_policy_id')))}</span><small>Promotion gate: {html.escape(str(summary.get('promotion_gate_status')))} / {html.escape(str(summary.get('promotion_gate_decision')))}</small></div>
        <div><strong>Boundary</strong><span>Offline gated</span><small>Closure did not start GCP training or production promotion.</small></div>
      </div>
      <div class="truth">
        <strong>Readiness issues</strong>
        <ul>{issue_items}</ul>
      </div>
    </section>

    <section>
      <div class="section-title"><h2>Cycle Walkthrough</h2></div>
      {''.join(cycle_cards)}
    </section>

    <section>
      <div class="section-title"><h2>Truth Boundaries</h2></div>
      <div class="truth">
        <ul>{''.join(f'<li>{html.escape(str(item))}</li>' for item in report.get('truth_boundaries', []))}</ul>
      </div>
    </section>
    <footer>Generated {html.escape(str(report.get('created_at')))}. JSON report: {html.escape(str(path.with_suffix('.json')))}</footer>
  </main>
</body>
</html>
"""
    path.write_text(html_doc, encoding="utf-8")


async def _async_main(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = _now_iso()
    batch_id = output_dir.name or f"operating-cycle-{started_at}"
    case_bank_dir = Path(args.case_bank_dir)
    starting_case_bank_rows = _read_case_bank_rows(case_bank_dir)
    cycles: list[dict[str, Any]] = []
    for index in range(1, args.cycles + 1):
        result = await _run_cycle(
            index,
            output_dir,
            record_ledger=not args.no_ledger,
            diversity_control=not args.no_diversity_control,
            case_bank_rows=starting_case_bank_rows,
            batch_summaries=[row["summary"] for row in cycles],
            agent_timeout_seconds=args.agent_timeout_seconds,
        )
        cycles.append(result)
    cycle_summaries = [row["summary"] for row in cycles]
    case_bank = _append_case_bank(
        cycle_summaries,
        case_bank_dir=case_bank_dir,
        batch_id=batch_id,
        output_dir=output_dir,
        min_training_rows=args.min_training_rows,
        min_issue_kinds=args.min_issue_kinds,
        min_targets=args.min_targets,
        max_dominant_issue_ratio=args.max_dominant_issue_ratio,
        min_memory_applied_ratio=args.min_memory_applied_ratio,
    )
    case_bank_summary = case_bank.get("summary", {}) if isinstance(case_bank.get("summary"), dict) else {}
    historical_case_count = _safe_int(case_bank_summary.get("closed_case_count"))
    historical_reward_count = _safe_int(case_bank_summary.get("reward_candidate_count"))
    quality_gate = case_bank_summary.get("quality_gate", {}) if isinstance(case_bank_summary.get("quality_gate"), dict) else {}
    if historical_case_count >= args.min_training_rows and historical_reward_count >= args.min_training_rows and quality_gate.get("ready_for_training") is True:
        actual_training = _run_actual_training_status(args.min_training_rows, args.training_detail, args.training_timeout_seconds)
    elif historical_case_count >= args.min_training_rows and historical_reward_count >= args.min_training_rows:
        actual_training = _quality_blocked_training_status(args.min_training_rows, case_bank_summary)
    else:
        actual_training = _deferred_training_status(args.min_training_rows, historical_case_count, historical_reward_count)
    actual_training = _apply_case_bank_reward_promotion_guard(actual_training, case_bank_summary)
    report = _aggregate_report(cycles, actual_training, started_at, case_bank)
    json_path = output_dir / "live-feed-operating-cycle.json"
    html_path = output_dir / "live-feed-operating-cycle.html"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")
    _render_html(report, html_path)
    print(
        json.dumps(
            {
                "status": report.get("status"),
                "summary": report.get("summary"),
                "case_bank": report.get("case_bank"),
                "output_json": str(json_path),
                "output_html": str(html_path),
            },
            indent=2,
            sort_keys=True,
            default=_json_default,
        )
    )
    return 0 if report.get("status") == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a bounded live-feed operating, memory, and training-closure cycle.")
    parser.add_argument("--cycles", type=int, default=3, help="Number of operating cycles to run.")
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "output/qa"))
    parser.add_argument("--case-bank-dir", default=str(REPO_ROOT / "output/qa/live-feed-case-bank"), help="Append-only historical case bank directory.")
    parser.add_argument("--min-training-rows", type=int, default=50, help="Closed outcome/reward cases required before any model-training path is invoked.")
    parser.add_argument("--min-issue-kinds", type=int, default=12, help="Minimum distinct issue kinds required before training.")
    parser.add_argument("--min-targets", type=int, default=6, help="Minimum distinct targets/zones required before training.")
    parser.add_argument("--max-dominant-issue-ratio", type=float, default=0.3, help="Maximum share allowed for the most common issue kind.")
    parser.add_argument("--min-memory-applied-ratio", type=float, default=0.45, help="Minimum share of closed cases that must show memory use.")
    parser.add_argument("--no-diversity-control", action="store_true", help="Use random unexpected events instead of case-bank diversity-directed issue selection.")
    parser.add_argument("--training-detail", choices=["readiness", "full"], default="full")
    parser.add_argument("--training-timeout-seconds", type=float, default=90.0)
    parser.add_argument("--agent-timeout-seconds", type=float, default=180.0, help="Maximum seconds to wait for each live-feed agent cycle.")
    parser.add_argument("--no-ledger", action="store_true", help="Do not write review dispositions to the review training ledger.")
    args = parser.parse_args()
    if args.cycles < 1:
        raise SystemExit("--cycles must be >= 1")
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
