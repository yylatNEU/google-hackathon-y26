from __future__ import annotations

from typing import Any


DEFAULT_MIN_REVIEW_LABELS = 25
DEFAULT_MIN_OUTCOME_ROWS = 50


def build_training_readiness_report(
    *,
    customer_details: dict[str, Any],
    actual_training: dict[str, Any],
    review_ledger: dict[str, Any],
    live_feed_health: dict[str, Any],
    min_review_labels: int = DEFAULT_MIN_REVIEW_LABELS,
    min_outcome_rows: int = DEFAULT_MIN_OUTCOME_ROWS,
) -> dict[str, Any]:
    review_summary = review_ledger.get("summary", {}) if isinstance(review_ledger.get("summary"), dict) else {}
    training_labels = _int(review_summary.get("training_candidate_count"))
    open_reviews = _int(review_summary.get("open_count"))
    outcome_rows = _int(actual_training.get("sample_count"))
    actual_debug = actual_training.get("debug", {}) if isinstance(actual_training.get("debug"), dict) else {}
    actual_issues = [str(item) for item in actual_debug.get("readiness_issues", []) if item]
    live_summary = live_feed_health.get("summary", {}) if isinstance(live_feed_health.get("summary"), dict) else {}
    required_feeds = _int(live_summary.get("required_feed_count"))
    ready_feeds = _int(live_summary.get("ready_feed_count"))
    missing_or_weak_feeds = _int(live_summary.get("missing_or_weak_feed_count"))
    live_feeds_ready = required_feeds > 0 and ready_feeds >= required_feeds and missing_or_weak_feeds == 0
    customer_quality = customer_details.get("data_quality", {}) if isinstance(customer_details.get("data_quality"), dict) else {}
    feed_contract = customer_details.get("feed_contract", {}) if isinstance(customer_details.get("feed_contract"), dict) else {}
    customer_production_ready = (
        customer_quality.get("status") == "production_ready"
        and bool(feed_contract.get("production_publishable"))
        and bool(feed_contract.get("customer_safe", True))
    )
    outcome_training_ready = actual_training.get("status") == "ready" and outcome_rows >= min_outcome_rows and not actual_issues

    agents = {
        "customer_agent": _customer_agent_readiness(customer_production_ready, training_labels, min_review_labels, customer_quality, feed_contract),
        "scan_agent": _scan_agent_readiness(live_feeds_ready, training_labels, min_review_labels, open_reviews, live_feed_health),
        "react_agent": _react_agent_readiness(live_feeds_ready, training_labels, min_review_labels, outcome_rows, min_outcome_rows, actual_issues),
        "proactive_agent": _proactive_agent_readiness(live_feeds_ready, training_labels, min_review_labels, outcome_rows, min_outcome_rows, actual_issues),
        "ops_chat": _ops_chat_readiness(training_labels, min_review_labels, open_reviews),
        "rl_action_policy": _rl_policy_readiness(outcome_training_ready, outcome_rows, min_outcome_rows, actual_issues, actual_training),
    }
    ready_count = len([row for row in agents.values() if row["status"] in {"ready", "ready_for_eval_generation"}])
    training_ready_count = len([row for row in agents.values() if row["model_training_ready"] is True])
    blockers = [blocker for row in agents.values() for blocker in row.get("blockers", [])]
    return {
        "status": "ready" if training_ready_count == len(agents) else "partially_ready" if ready_count else "not_ready",
        "mode": "role_scoped_training_readiness",
        "whole_system_training_ready": training_ready_count == len(agents),
        "whole_system_rl_ready": agents["rl_action_policy"]["model_training_ready"],
        "summary": {
            "agent_count": len(agents),
            "ready_or_eval_ready_count": ready_count,
            "model_training_ready_count": training_ready_count,
            "training_label_count": training_labels,
            "min_review_labels": min_review_labels,
            "observed_outcome_rows": outcome_rows,
            "min_outcome_rows": min_outcome_rows,
            "live_feed_ready_count": ready_feeds,
            "required_live_feed_count": required_feeds,
            "open_review_count": open_reviews,
        },
        "agents": agents,
        "global_blockers": sorted(set(blockers))[:30],
        "next_actions": _global_next_actions(agents),
        "boundaries": [
            "Customer public data can generate evals only when the customer feed is production-ready.",
            "Supervised training requires human-reviewed labels; review labels do not become reward.",
            "RL/action-policy training requires observed outcome rows, measured rewards, clean live gates, and promotion/rollback gates.",
            "Customer public data and internal ops/action data remain separate training scopes.",
        ],
        "inputs": {
            "customer_data_quality": {
                "status": customer_quality.get("status"),
                "score": customer_quality.get("score"),
                "production_publishable": feed_contract.get("production_publishable"),
            },
            "review_ledger": review_summary,
            "actual_training": {
                "status": actual_training.get("status"),
                "sample_count": outcome_rows,
                "source": actual_training.get("source"),
                "readiness_issues": actual_issues[:12],
            },
            "live_feed_health": live_summary,
        },
    }


def _customer_agent_readiness(
    customer_production_ready: bool,
    training_labels: int,
    min_review_labels: int,
    customer_quality: dict[str, Any],
    feed_contract: dict[str, Any],
) -> dict[str, Any]:
    blockers = []
    if not customer_production_ready:
        blockers.append("Customer public feed is not production-ready.")
    if training_labels < min_review_labels:
        blockers.append(f"Need at least {min_review_labels} human-reviewed customer/ops labels; found {training_labels}.")
    return {
        "status": "ready" if customer_production_ready and training_labels >= min_review_labels else "ready_for_eval_generation" if customer_production_ready else "not_ready",
        "model_training_ready": customer_production_ready and training_labels >= min_review_labels,
        "eval_generation_ready": customer_production_ready,
        "recommended_training_mode": "customer_llm_eval_and_supervised_examples" if customer_production_ready else "hold",
        "blockers": blockers,
        "evidence": {
            "customer_quality_status": customer_quality.get("status"),
            "customer_quality_score": customer_quality.get("score"),
            "production_publishable": feed_contract.get("production_publishable"),
            "training_label_count": training_labels,
        },
        "next_actions": ["Generate customer evals from venue-approved feed.", "Collect reviewed customer Q&A labels."] if customer_production_ready else ["Load venue-approved customer export and clear quality blockers."],
    }


def _scan_agent_readiness(live_feeds_ready: bool, training_labels: int, min_review_labels: int, open_reviews: int, live_feed_health: dict[str, Any]) -> dict[str, Any]:
    blockers = []
    if not live_feeds_ready:
        blockers.append("Required live feeds are missing or weak.")
    if training_labels < min_review_labels:
        blockers.append(f"Need at least {min_review_labels} reviewed scan labels; found {training_labels}.")
    if open_reviews:
        blockers.append(f"Resolve open review cases before broad scan training; open={open_reviews}.")
    return {
        "status": "ready" if not blockers else "not_ready",
        "model_training_ready": not blockers,
        "eval_generation_ready": live_feeds_ready,
        "recommended_training_mode": "scan_supervised_signal_ranking",
        "blockers": blockers,
        "evidence": {"live_feed_status": live_feed_health.get("status"), "training_label_count": training_labels, "open_review_count": open_reviews},
        "next_actions": ["Load and stabilize all required live feeds.", "Close review queue and convert dispositions to supervised labels."],
    }


def _react_agent_readiness(live_feeds_ready: bool, training_labels: int, min_review_labels: int, outcome_rows: int, min_outcome_rows: int, actual_issues: list[str]) -> dict[str, Any]:
    blockers = _ops_common_blockers(live_feeds_ready, training_labels, min_review_labels, outcome_rows, min_outcome_rows, actual_issues)
    return {
        "status": "ready" if not blockers else "not_ready",
        "model_training_ready": not blockers,
        "eval_generation_ready": training_labels > 0,
        "recommended_training_mode": "react_agent_supervised_decision_and_outcome_eval",
        "blockers": blockers,
        "evidence": {"training_label_count": training_labels, "observed_outcome_rows": outcome_rows, "actual_training_issues": actual_issues[:8]},
        "next_actions": ["Collect reviewed incident response cases.", "Mature measured outcomes for every dispatched response."],
    }


def _proactive_agent_readiness(live_feeds_ready: bool, training_labels: int, min_review_labels: int, outcome_rows: int, min_outcome_rows: int, actual_issues: list[str]) -> dict[str, Any]:
    blockers = _ops_common_blockers(live_feeds_ready, training_labels, min_review_labels, outcome_rows, min_outcome_rows * 2, actual_issues)
    if outcome_rows < min_outcome_rows * 2:
        blockers.append(f"Proactive training needs at least {min_outcome_rows * 2} observed outcome rows; found {outcome_rows}.")
    return {
        "status": "ready" if not blockers else "not_ready",
        "model_training_ready": not blockers,
        "eval_generation_ready": training_labels > 0 and live_feeds_ready,
        "recommended_training_mode": "proactive_weak_signal_forecast_eval",
        "blockers": sorted(set(blockers)),
        "evidence": {"training_label_count": training_labels, "observed_outcome_rows": outcome_rows, "actual_training_issues": actual_issues[:8]},
        "next_actions": ["Run more live outcome cycles.", "Add counterfactual review for weak-signal misses."],
    }


def _ops_chat_readiness(training_labels: int, min_review_labels: int, open_reviews: int) -> dict[str, Any]:
    blockers = []
    if training_labels < min_review_labels:
        blockers.append(f"Need at least {min_review_labels} reviewed ops chat labels; found {training_labels}.")
    if open_reviews:
        blockers.append(f"Open review queue should be triaged before ops chat fine-tuning; open={open_reviews}.")
    return {
        "status": "ready" if not blockers else "not_ready",
        "model_training_ready": not blockers,
        "eval_generation_ready": training_labels > 0,
        "recommended_training_mode": "ops_chat_eval_and_supervised_style_safety",
        "blockers": blockers,
        "evidence": {"training_label_count": training_labels, "open_review_count": open_reviews},
        "next_actions": ["Create reviewed ops chat transcripts and safety refusals.", "Separate customer-facing and operator-facing examples."],
    }


def _rl_policy_readiness(outcome_training_ready: bool, outcome_rows: int, min_outcome_rows: int, actual_issues: list[str], actual_training: dict[str, Any]) -> dict[str, Any]:
    blockers = []
    if outcome_rows < min_outcome_rows:
        blockers.append(f"Need at least {min_outcome_rows} observed outcome rows; found {outcome_rows}.")
    blockers.extend(actual_issues)
    return {
        "status": "ready" if outcome_training_ready else "not_ready",
        "model_training_ready": outcome_training_ready,
        "eval_generation_ready": outcome_rows > 0,
        "recommended_training_mode": "observed_outcome_batch_rl_or_contextual_bandit_only",
        "blockers": blockers,
        "evidence": {
            "actual_training_status": actual_training.get("status"),
            "observed_outcome_rows": outcome_rows,
            "source": actual_training.get("source"),
            "uses_generated_data": actual_training.get("uses_generated_data"),
        },
        "next_actions": ["Collect more measured outcome rows.", "Keep LLM labels out of reward.", "Run promotion/rollback gates before deployment."],
    }


def _ops_common_blockers(
    live_feeds_ready: bool,
    training_labels: int,
    min_review_labels: int,
    outcome_rows: int,
    min_outcome_rows: int,
    actual_issues: list[str],
) -> list[str]:
    blockers = []
    if not live_feeds_ready:
        blockers.append("Required live feeds are missing or weak.")
    if training_labels < min_review_labels:
        blockers.append(f"Need at least {min_review_labels} reviewed labels; found {training_labels}.")
    if outcome_rows < min_outcome_rows:
        blockers.append(f"Need at least {min_outcome_rows} observed outcome rows; found {outcome_rows}.")
    blockers.extend(actual_issues[:8])
    return blockers


def _global_next_actions(agents: dict[str, dict[str, Any]]) -> list[str]:
    actions = []
    if agents["customer_agent"]["eval_generation_ready"] is False:
        actions.append("Make customer public feed production-ready before generating customer LLM examples.")
    if agents["scan_agent"]["model_training_ready"] is False:
        actions.append("Stabilize all live feeds and close human review cases.")
    if agents["rl_action_policy"]["model_training_ready"] is False:
        actions.append("Collect measured outcome rows before RL/action-policy training.")
    actions.append("Keep customer, ops-chat, and action-policy datasets separated by role and authority.")
    return actions


def _int(value: Any, default: int = 0) -> int:
    try:
        if value in {None, ""}:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default
