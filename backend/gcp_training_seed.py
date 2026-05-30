from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

from dotenv import load_dotenv

from bigquery_analytics import build_analytics_rows, export_analytics_rows, online_improvement_status
from mongo_memory import (
    init_operational_memory,
    record_agent_decision,
    record_outcome_event,
    retrieve_operational_context,
    sync_park_state,
)
from park_action_bridge import build_park_action_plan
from park_delivery import build_delivery_plan, response_summary
from park_eval import evaluate_park_decision
from park_optimizer import optimize_park_response
from park_outcome_loop import build_reactive_outcome
from park_scenarios import PARK_SCENARIOS
from park_simulation import park_simulation


SYNTHETIC_CASES: list[dict[str, Any]] = [
    {
        "case_id": "ride_cascade_high_heat_01",
        "scenario": "ride_down",
        "events": [
            {"kind": "ride_failure", "target_id": "dragonCoaster", "intensity": 92},
            {"kind": "demand_spike", "target_id": "coasterPlaza", "intensity": 84},
            {"kind": "energy_spike", "target_id": "indoorHub", "intensity": 58},
        ],
    },
    {
        "case_id": "ride_split_indoor_overload_02",
        "scenario": "ride_down",
        "events": [
            {"kind": "ride_failure", "target_id": "dragonCoaster", "intensity": 78},
            {"kind": "demand_spike", "target_id": "indoorHub", "intensity": 88},
            {"kind": "staff_callout", "target_id": "coasterPlaza", "intensity": 52},
        ],
    },
    {
        "case_id": "staff_food_dual_pressure_01",
        "scenario": "staff_shortage",
        "events": [
            {"kind": "staff_callout", "target_id": "foodCourt1", "intensity": 90},
            {"kind": "food_spike", "target_id": "foodCourt1", "intensity": 82},
        ],
    },
    {
        "case_id": "staff_ride_coverage_gap_02",
        "scenario": "staff_shortage",
        "events": [
            {"kind": "staff_callout", "target_id": "dragonCoaster", "intensity": 76},
            {"kind": "demand_spike", "target_id": "coasterPlaza", "intensity": 70},
        ],
    },
    {
        "case_id": "food_inventory_mobile_backlog_01",
        "scenario": "food_spike",
        "events": [
            {"kind": "food_spike", "target_id": "foodCourt1", "intensity": 94},
            {"kind": "staff_callout", "target_id": "foodCourt1", "intensity": 66},
        ],
    },
    {
        "case_id": "food_redirect_capacity_conflict_02",
        "scenario": "food_spike",
        "events": [
            {"kind": "food_spike", "target_id": "foodCourt1", "intensity": 72},
            {"kind": "demand_spike", "target_id": "coveredPlaza", "intensity": 80},
            {"kind": "energy_spike", "target_id": "coveredPlaza", "intensity": 45},
        ],
    },
    {
        "case_id": "storm_shelter_energy_01",
        "scenario": "storm_response",
        "events": [
            {"kind": "storm_risk", "target_id": "coveredPlaza", "intensity": 88},
            {"kind": "energy_spike", "target_id": "indoorHub", "intensity": 74},
        ],
    },
    {
        "case_id": "storm_ride_taper_staff_02",
        "scenario": "storm_response",
        "events": [
            {"kind": "storm_risk", "target_id": "coasterPlaza", "intensity": 96},
            {"kind": "ride_failure", "target_id": "dragonCoaster", "intensity": 64},
            {"kind": "staff_callout", "target_id": "coveredPlaza", "intensity": 50},
        ],
    },
    {
        "case_id": "cross_domain_peak_day_01",
        "scenario": "ride_down",
        "events": [
            {"kind": "ride_failure", "target_id": "dragonCoaster", "intensity": 86},
            {"kind": "food_spike", "target_id": "foodCourt1", "intensity": 75},
            {"kind": "staff_callout", "target_id": "coasterPlaza", "intensity": 68},
            {"kind": "storm_risk", "target_id": "coveredPlaza", "intensity": 60},
        ],
    },
    {
        "case_id": "cross_domain_recovery_window_02",
        "scenario": "staff_shortage",
        "events": [
            {"kind": "demand_spike", "target_id": "arcadeZone", "intensity": 82},
            {"kind": "food_spike", "target_id": "foodCourt1", "intensity": 69},
            {"kind": "energy_spike", "target_id": "indoorHub", "intensity": 63},
        ],
    },
]


def _bigquery_outcome_exists(outcome_id: str) -> bool:
    try:
        from google.cloud import bigquery

        project = os.getenv("BIGQUERY_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT")
        dataset = os.getenv("BIGQUERY_DATASET", "parkpulse_analytics")
        if not project or not dataset:
            return False
        client = bigquery.Client(project=project)
        query = f"""
            SELECT 1
            FROM `{project}.{dataset}.outcome_events`
            WHERE outcome_id = @outcome_id
            LIMIT 1
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("outcome_id", "STRING", outcome_id)]
        )
        return any(client.query(query, job_config=job_config).result())
    except Exception:
        return False


def _selected_action(plan: dict[str, Any]) -> dict[str, Any]:
    selected = dict(plan.get("selected_action", {}) or {})
    park_action = selected.get("park_action", {}) if isinstance(selected.get("park_action"), dict) else {}
    selected.setdefault("target", park_action.get("target", "ride"))
    selected.setdefault("action", park_action.get("action", "reroute"))
    selected.setdefault("label", selected.get("title", "Deterministic ParkPulse action"))
    return selected


def _memory_eval(plan: dict[str, Any], scenario_key: str) -> dict[str, Any]:
    risk_counts = plan.get("risk_counts", {}) if isinstance(plan.get("risk_counts"), dict) else {}
    approval_penalty = 6 if plan.get("needs_human_approval") else 0
    return {
        "energy_score": 84 if scenario_key != "food_spike" else 88,
        "comfort_score": max(74, 90 - int(risk_counts.get("crowded_zones", 0) or 0) * 3),
        "worker_stress_score": 82 - approval_penalty,
        "safety_score": 96 - approval_penalty,
        "reasoning": f"GCP training seed for {scenario_key}; deterministic local plan mirrors compact rows to BigQuery.",
    }


async def _prepare_case_state(scenario_key: str, events: list[dict[str, Any]] | None = None) -> None:
    await park_simulation.reset_demo()
    await park_simulation.execute_action("scenario", scenario_key)
    for event in events or []:
        await park_simulation.inject_event(
            str(event.get("kind", "")),
            str(event.get("target_id", "")),
            int(event.get("intensity", 75) or 75),
        )


async def _run_training_case(
    *,
    round_index: int,
    scenario_key: str,
    source: str,
    case_id: str | None,
    events: list[dict[str, Any]] | None,
    allow_duplicates: bool,
) -> dict[str, Any]:
    await _prepare_case_state(scenario_key, events)
    before_state = await park_simulation.get_state()
    sync_park_state(before_state)
    event_terms = " ".join(
        f"{event.get('kind')} {event.get('target_id')} intensity {event.get('intensity')}" for event in events or []
    )
    context = retrieve_operational_context(
        f"{scenario_key} {case_id or ''} {event_terms} gcp training decision dispatch outcome eval park operations",
        before_state,
    )
    plan = build_park_action_plan(before_state)
    selected = _selected_action(plan)
    if case_id:
        selected["synthetic_case_id"] = case_id
    optimization = optimize_park_response(before_state, scenario_key, context, {"selected_action": selected})
    decision_id = record_agent_decision(
        {
            "recommended_action": selected.get("title", ""),
            "selected_action": selected,
            "candidate_actions": plan.get("recommended_actions", []),
            "optimization": optimization,
            "confidence_score": plan.get("confidence", 0),
            "root_cause_classification": scenario_key,
            "guest_message": selected.get("expected_impact", ""),
        },
        _memory_eval(plan, scenario_key),
        before_state,
        context,
        source=source,
    )
    await park_simulation.execute_action(str(selected.get("target")), str(selected.get("action")))
    after_state = await park_simulation.get_state()
    sync_park_state(after_state)
    delivery_dispatches = build_delivery_plan(
        scenario_key,
        selected,
        after_state,
        decision_id,
        action_mix=optimization.get("selected_plan", {}).get("action_mix"),
    )
    response_metrics = response_summary(delivery_dispatches)
    eval_result = evaluate_park_decision(scenario_key, after_state, delivery_dispatches)
    outcome = build_reactive_outcome(
        before_state,
        after_state,
        delivery_dispatches,
        response_metrics,
        optimization,
        {
            "recommended_action": selected.get("title", ""),
            "root_cause_classification": scenario_key,
        },
        eval_result,
    )
    outcome_id = record_outcome_event(outcome, decision_id, after_state)
    rows = build_analytics_rows(
        decision_id=decision_id,
        outcome_id=outcome_id,
        scenario_key=scenario_key,
        delivery={"response": response_metrics, "dispatches": delivery_dispatches},
        outcome=outcome,
        eval_result=eval_result,
        source=source,
    )
    duplicate = bool(outcome_id and _bigquery_outcome_exists(outcome_id))
    export = (
        {"status": "skipped_existing", "inserted": {}, "errors": {}}
        if duplicate and not allow_duplicates
        else export_analytics_rows(rows)
    )
    return {
        "round": round_index + 1,
        "case_id": case_id,
        "scenario": scenario_key,
        "event_count": len(events or []),
        "decision_id": decision_id,
        "outcome_id": outcome_id,
        "duplicate": duplicate,
        "dispatch_count": len(delivery_dispatches),
        "response_score": response_metrics.get("score"),
        "take_rate": response_metrics.get("takeRate"),
        "follow_through": response_metrics.get("reactiveFollowThroughRate"),
        "eval_overall": eval_result.get("scorecard", {}).get("overall"),
        "analytics_status": export.get("status"),
        "inserted": export.get("inserted", {}),
        "errors": export.get("errors", {}),
    }


async def run_training_seed(rounds: int, scenarios: list[str], allow_duplicates: bool = False) -> list[dict[str, Any]]:
    init_operational_memory()
    results: list[dict[str, Any]] = []
    for round_index in range(rounds):
        for scenario_key in scenarios:
            results.append(
                await _run_training_case(
                    round_index=round_index,
                    scenario_key=scenario_key,
                    source="gcp_training_seed",
                    case_id=None,
                    events=None,
                    allow_duplicates=allow_duplicates,
                )
            )
    return results


async def run_synthetic_training(cases: list[dict[str, Any]], allow_duplicates: bool = False) -> list[dict[str, Any]]:
    init_operational_memory()
    results = []
    for index, case in enumerate(cases):
        results.append(
            await _run_training_case(
                round_index=index,
                scenario_key=str(case["scenario"]),
                source="gcp_synthetic_training",
                case_id=str(case["case_id"]),
                events=case.get("events", []),
                allow_duplicates=allow_duplicates,
            )
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed ParkPulse GCP/BigQuery training rows.")
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--scenarios", nargs="*", default=list(PARK_SCENARIOS.keys()))
    parser.add_argument("--allow-duplicates", action="store_true")
    parser.add_argument("--synthetic", action="store_true", help="Run named complex synthetic cases.")
    parser.add_argument("--max-cases", type=int, default=len(SYNTHETIC_CASES))
    args = parser.parse_args()
    load_dotenv(".env")
    status = online_improvement_status()
    if not status.get("ready"):
        raise SystemExit(json.dumps({"status": "blocked", "readiness_issues": status.get("readiness_issues", [])}))
    if args.synthetic:
        cases = SYNTHETIC_CASES[: max(1, args.max_cases)]
        results = asyncio.run(run_synthetic_training(cases, allow_duplicates=args.allow_duplicates))
    else:
        scenarios = [item for item in args.scenarios if item in PARK_SCENARIOS]
        if not scenarios:
            raise SystemExit("No valid scenarios provided.")
        results = asyncio.run(run_training_seed(max(1, args.rounds), scenarios, allow_duplicates=args.allow_duplicates))
    print(json.dumps({"status": "complete", "runs": len(results), "results": results}, indent=2, default=str))


if __name__ == "__main__":
    main()
