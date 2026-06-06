from __future__ import annotations

from typing import Any


SCENARIOS = ["ride_down", "staff_shortage", "food_spike", "storm_response", "proactive_eventops"]
AUTODREAM_CACHE_REPLAY_ROLES = ["scan_agent", "react_agent", "proact_agent", "maintenance_agent"]
AUTODREAM_RETIREMENT_REASON = "AutoDream has been retired; ParkPulse no longer runs offline dream learning, promotion, or paired replay benchmarks."


def run_autodream(
    scenario_key: str = "proactive_eventops",
    *,
    max_cases: int = 8,
    persist: bool = True,
) -> dict[str, Any]:
    scenario = scenario_key if scenario_key in SCENARIOS else "proactive_eventops"
    return {
        "status": "retired",
        "mode": "retired_autodream",
        "agent_id": "autodream_agent",
        "scenario_key": scenario,
        "max_cases": max(1, min(25, int(max_cases or 1))),
        "persist": bool(persist),
        "offline_only": True,
        "storage": {"status": "disabled", "dream_run_id": None, "dream_learning_ids": []},
        "summary": {
            "retired": True,
            "cases_reviewed": 0,
            "learnings_generated": 0,
            "review_required": False,
            "prior_source": "disabled",
            "cache_replay_status": "disabled",
            "cache_replay_pass_rate": None,
            "reason": AUTODREAM_RETIREMENT_REASON,
        },
        "dream_run": {
            "status": "retired",
            "offlineOnly": True,
            "scenarioKey": scenario,
            "guardrails": ["feature_retired_no_live_or_offline_execution"],
        },
        "dream_learnings": [],
        "cache_replay_audit": {
            "status": "disabled",
            "summary": {
                "roles_checked": 0,
                "roles_passed": 0,
                "pass_rate": None,
                "failures": ["autodream_retired"],
            },
            "replays": [],
        },
        "operator_review": {
            "required": False,
            "promotion_targets": [],
            "note": AUTODREAM_RETIREMENT_REASON,
        },
        "analytics": {"status": "disabled", "row_counts": {"dream_eval_results": 0}},
    }


def autodream_status(limit: int = 8) -> dict[str, Any]:
    safe_limit = max(1, min(25, int(limit or 8)))
    return {
        "agent_id": "autodream_agent",
        "mode": "retired_autodream",
        "offline_only": True,
        "status": "retired",
        "limit": safe_limit,
        "summary": {
            "retired": True,
            "dream_runs": 0,
            "dream_learnings": 0,
            "pending_review": 0,
            "promoted": 0,
            "rejected": 0,
            "archived": 0,
            "needs_more_evidence": 0,
            "impact_improved": 0,
            "impact_neutral": 0,
            "impact_regressed": 0,
            "promotion_ready": 0,
            "promotion_blocked": 0,
            "rollback_watch": 0,
            "reason": AUTODREAM_RETIREMENT_REASON,
        },
        "latest_dream_runs": [],
        "latest_dream_learnings": [],
        "promotion_readiness": [],
        "rollback_watch": {"status": "retired", "count": 0, "documents": []},
        "operator_review": {
            "required_for_promotion": False,
            "allowed_targets": [],
            "allowed_review_statuses": [],
        },
    }


def promote_autodream_learning(
    dream_learning_id: str,
    target: str = "agent_learnings",
    reviewer: str = "operator",
) -> dict[str, Any]:
    return {
        "agent_id": "autodream_agent",
        "mode": "retired_autodream_promotion",
        "offline_source": True,
        "status": "retired",
        "promotion": {
            "status": "retired",
            "dream_learning_id": dream_learning_id,
            "target": target,
            "reviewer": reviewer,
            "reason": AUTODREAM_RETIREMENT_REASON,
            "blockers": ["autodream_retired"],
        },
        "cache_replay_audit": {"status": "disabled", "summary": {"failures": ["autodream_retired"]}},
        "paired_benchmark": {"status": "retired", "summary": {"reason": AUTODREAM_RETIREMENT_REASON}},
        "promotion_readiness": {
            "status": "retired",
            "dream_learning_id": dream_learning_id,
            "promotion_ready": False,
            "blockers": ["autodream_retired"],
        },
        "post_status": autodream_status(8),
    }


def review_autodream_learning(
    dream_learning_id: str,
    review_status: str = "rejected",
    reviewer: str = "operator",
    reason: str = "",
) -> dict[str, Any]:
    return {
        "agent_id": "autodream_agent",
        "mode": "retired_autodream_review",
        "offline_source": True,
        "status": "retired",
        "review": {
            "status": "retired",
            "dream_learning_id": dream_learning_id,
            "review_status": review_status,
            "reviewer": reviewer,
            "reason": reason or AUTODREAM_RETIREMENT_REASON,
        },
        "post_status": autodream_status(8),
    }
