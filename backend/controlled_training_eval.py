from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from controlled_training_generation import TRAINING_AGENT_ORDER, latest_controlled_training_pack


DEFAULT_MIN_ROLE_SCORE = 80
RL_MIN_ROLE_SCORE = 90


def run_controlled_training_eval(pack: dict[str, Any] | None = None, *, write_artifact: bool = True) -> dict[str, Any]:
    source_pack = pack if isinstance(pack, dict) else latest_controlled_training_pack()
    examples = source_pack.get("examples", []) if isinstance(source_pack.get("examples"), list) else []
    role_results = [_score_role(agent_id, examples) for agent_id in TRAINING_AGENT_ORDER]
    blockers = _global_blockers(source_pack, role_results)
    passed_roles = len([row for row in role_results if row.get("passed") is True])
    status = "passed" if not blockers and passed_roles == len(role_results) else "failed"
    report = {
        "id": f"controlled_training_eval_{source_pack.get('id') or 'unknown'}",
        "created_at": _now_iso(),
        "status": status,
        "mode": "controlled_eval_training_gate",
        "pack_id": source_pack.get("id"),
        "summary": {
            "role_count": len(role_results),
            "passed_role_count": passed_roles,
            "example_count": len(examples),
            "min_role_score": DEFAULT_MIN_ROLE_SCORE,
            "rl_min_role_score": RL_MIN_ROLE_SCORE,
        },
        "role_results": role_results,
        "readiness_issues": blockers,
        "decision": "allow_offline_training_generation" if status == "passed" else "block_training_until_eval_passes",
        "training_rule": "Offline training may start only after this controlled eval gate passes. This eval never starts training, changes reward, promotes policies, or dispatches actions.",
        "boundaries": [
            "Customer and ops examples remain separated by role scope.",
            "Supervised labels are not reward.",
            "RL reward rows must be measured outcome rows with observed reward source.",
            "LLM-derived content cannot set labels, reward, promotion, or live actions.",
        ],
        "uses_seed_data": False,
        "labels_or_reward_changed": False,
        "llm_used_for_reward_or_label": False,
        "gcp_training_started": False,
        "model_promotion_started": False,
    }
    artifacts = _write_eval_artifact(report) if write_artifact else {"status": "not_written", "paths": {}}
    return {**report, "artifacts": artifacts}


def latest_controlled_training_eval() -> dict[str, Any]:
    durable = _latest_durable_eval()
    if durable:
        durable["artifacts"] = {**durable.get("artifacts", {}), "durable_storage": "mongodb"}
        return durable
    directory = _artifact_dir()
    if not os.path.isdir(directory):
        return {"status": "empty", "mode": "controlled_eval_training_gate_latest", "readiness_issues": ["No controlled training eval artifacts have been written."]}
    reports = [os.path.join(directory, name) for name in os.listdir(directory) if name.endswith(".eval.json")]
    if not reports:
        return {"status": "empty", "mode": "controlled_eval_training_gate_latest", "readiness_issues": ["No eval report artifacts found."]}
    latest = max(reports, key=lambda path: os.path.getmtime(path))
    with open(latest, "r", encoding="utf-8") as handle:
        report = json.load(handle)
    if isinstance(report, dict):
        report["artifacts"] = {**report.get("artifacts", {}), "latest_eval_path": latest, "durable_storage": "local_artifact"}
        return report
    return {"status": "error", "mode": "controlled_eval_training_gate_latest", "readiness_issues": [f"Latest eval report is not an object: {latest}"]}


def offline_training_eval_gate_passed(required_agent_ids: list[str] | tuple[str, ...] | None = None) -> dict[str, Any]:
    report = latest_controlled_training_eval()
    if report.get("status") == "passed":
        return {"allowed": True, "status": "passed", "eval": report}
    required = [str(item) for item in required_agent_ids or [] if str(item)]
    if required and isinstance(report.get("role_results"), list):
        role_results = {
            str(row.get("agent_id")): row
            for row in report.get("role_results", [])
            if isinstance(row, dict) and row.get("agent_id")
        }
        required_failures = [
            f"{agent_id} failed scoped eval gate: score {role_results.get(agent_id, {}).get('score', 0)}/{role_results.get(agent_id, {}).get('min_score', 0)}."
            for agent_id in required
            if role_results.get(agent_id, {}).get("passed") is not True
        ]
        critical_blockers = [
            issue
            for issue in report.get("readiness_issues", [])
            if not any(str(issue).startswith(f"{agent_id} failed eval gate:") for agent_id in TRAINING_AGENT_ORDER)
        ]
        if not required_failures and not critical_blockers:
            scoped_report = {
                **report,
                "status": "scoped_passed",
                "decision": "allow_scoped_offline_training_generation",
                "scope": {"required_agent_ids": required, "ignored_agent_ids": [agent_id for agent_id in TRAINING_AGENT_ORDER if agent_id not in required]},
                "readiness_issues": [],
            }
            return {"allowed": True, "status": "scoped_passed", "eval": scoped_report}
        scoped_report = {
            **report,
            "status": "scoped_failed",
            "scope": {"required_agent_ids": required},
            "readiness_issues": [*critical_blockers, *required_failures],
        }
        return {
            "allowed": False,
            "status": "scoped_failed",
            "eval": scoped_report,
            "readiness_issues": scoped_report["readiness_issues"],
        }
    return {
        "allowed": False,
        "status": report.get("status") or "missing",
        "eval": report,
        "readiness_issues": report.get("readiness_issues") or ["Run and pass /api/park/controlled-training-eval before starting offline training."],
    }


def _score_role(agent_id: str, examples: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [row for row in examples if isinstance(row, dict) and row.get("agent_id") == agent_id]
    threshold = RL_MIN_ROLE_SCORE if agent_id == "rl_action_policy" else DEFAULT_MIN_ROLE_SCORE
    if not rows:
        return {
            "agent_id": agent_id,
            "status": "failed",
            "passed": False,
            "score": 0,
            "min_score": threshold,
            "example_count": 0,
            "failure_reasons": ["No examples exist for this role scope."],
        }
    scored = [_score_example(agent_id, row) for row in rows]
    score = round(sum(item["score"] for item in scored) / len(scored), 2)
    failures = [reason for item in scored for reason in item.get("failure_reasons", [])]
    failures.extend(_role_requirement_failures(agent_id, rows))
    if failures:
        score = min(score, threshold - 1)
    status = "passed" if score >= threshold and not failures else "failed"
    return {
        "agent_id": agent_id,
        "status": status,
        "passed": status == "passed",
        "score": score,
        "min_score": threshold,
        "example_count": len(rows),
        "checks": _role_checks(agent_id),
        "failure_reasons": sorted(set(failures))[:12],
        "example_scores": scored[:12],
    }


def _score_example(agent_id: str, row: dict[str, Any]) -> dict[str, Any]:
    score = 100
    failures: list[str] = []
    score, failures = _common_guardrail_score(row, score, failures)
    if agent_id == "customer_agent":
        score, failures = _customer_score(row, score, failures)
    elif agent_id == "scan_agent":
        score, failures = _scan_score(row, score, failures)
    elif agent_id in {"react_agent", "proactive_agent"}:
        score, failures = _ops_decision_score(row, score, failures)
    elif agent_id == "ops_chat":
        score, failures = _ops_chat_score(row, score, failures)
    elif agent_id == "rl_action_policy":
        score, failures = _rl_score(row, score, failures)
    else:
        score -= 30
        failures.append(f"Unknown agent scope: {agent_id}.")
    return {
        "example_id": row.get("id"),
        "source": row.get("source"),
        "split": row.get("split"),
        "score": max(0, min(100, score)),
        "failure_reasons": failures,
    }


def _common_guardrail_score(row: dict[str, Any], score: int, failures: list[str]) -> tuple[int, list[str]]:
    if row.get("uses_seed_data") is not False:
        score -= 40
        failures.append("Example must not use seed/generated data.")
    if row.get("labels_or_reward_changed") is not False:
        score -= 60
        failures.append("Eval pack must not mutate labels or reward.")
    if row.get("llm_used_for_reward_or_label") is not False:
        score -= 60
        failures.append("LLM must not set reward or labels.")
    if not row.get("training_scope"):
        score -= 15
        failures.append("Missing role-scoped training scope.")
    return score, failures


def _customer_score(row: dict[str, Any], score: int, failures: list[str]) -> tuple[int, list[str]]:
    if row.get("eligible_for_reward"):
        score -= 40
        failures.append("Customer examples must never be reward rows.")
    if row.get("source") not in {"customer_public_data_feed", "approved_review_label_decision"}:
        score -= 20
        failures.append("Customer example must come from public venue feed or approved supervised label.")
    expected = row.get("expected_output", {}) if isinstance(row.get("expected_output"), dict) else {}
    if not expected.get("label"):
        score -= 15
        failures.append("Customer example is missing an expected label.")
    return score, failures


def _scan_score(row: dict[str, Any], score: int, failures: list[str]) -> tuple[int, list[str]]:
    if row.get("eligible_for_reward"):
        score -= 35
        failures.append("Scan examples must not be reward rows.")
    if row.get("source") == "live_feed_health":
        input_payload = row.get("input", {}) if isinstance(row.get("input"), dict) else {}
        if input_payload.get("status") in {"ready", "trusted"} and _float(input_payload.get("confidence")) < 0.7:
            score -= 25
            failures.append("Trusted live-feed eval requires confidence >= 0.7.")
    elif row.get("source") != "approved_review_label_decision":
        score -= 20
        failures.append("Scan example must come from live feed health or approved review label.")
    return score, failures


def _ops_decision_score(row: dict[str, Any], score: int, failures: list[str]) -> tuple[int, list[str]]:
    if row.get("eligible_for_reward"):
        score -= 30
        failures.append("React/proactive eval examples must not be reward rows.")
    if row.get("source") == "approved_review_label_decision":
        expected = row.get("expected_output", {}) if isinstance(row.get("expected_output"), dict) else {}
        if not expected.get("label"):
            score -= 20
            failures.append("Approved react/proactive supervised label is missing an expected label.")
        return score, failures
    if row.get("source") != "observed_outcome_training_row":
        score -= 25
        failures.append("React/proactive examples require observed outcome rows.")
    input_payload = row.get("input", {}) if isinstance(row.get("input"), dict) else {}
    if not input_payload.get("scenario_key"):
        score -= 15
        failures.append("Observed outcome example is missing scenario_key.")
    if not input_payload.get("policy"):
        score -= 15
        failures.append("Observed outcome example is missing selected policy.")
    return score, failures


def _role_requirement_failures(agent_id: str, rows: list[dict[str, Any]]) -> list[str]:
    if agent_id in {"react_agent", "proactive_agent"}:
        has_observed_outcome = any(row.get("source") == "observed_outcome_training_row" for row in rows)
        return [] if has_observed_outcome else ["React/proactive gate requires at least one observed outcome example."]
    if agent_id == "rl_action_policy":
        has_reward_row = any(
            row.get("source") == "observed_outcome_training_row"
            and row.get("eligible_for_reward") is True
            and isinstance((row.get("expected_output") or {}).get("reward"), (int, float))
            and (row.get("expected_output") or {}).get("reward_source") == "observed_outcome_row"
            for row in rows
            if isinstance(row.get("expected_output"), dict)
        )
        return [] if has_reward_row else ["RL/action-policy gate requires measured reward rows from observed outcomes."]
    return []


def _ops_chat_score(row: dict[str, Any], score: int, failures: list[str]) -> tuple[int, list[str]]:
    if row.get("eligible_for_reward"):
        score -= 40
        failures.append("Ops chat examples must never be reward rows.")
    expected = row.get("expected_output", {}) if isinstance(row.get("expected_output"), dict) else {}
    if not (expected.get("label") or expected.get("decision")):
        score -= 20
        failures.append("Ops chat eval requires expected safety/style label or decision.")
    return score, failures


def _rl_score(row: dict[str, Any], score: int, failures: list[str]) -> tuple[int, list[str]]:
    if row.get("source") != "observed_outcome_training_row":
        score -= 45
        failures.append("RL/action-policy rows must come from observed outcome rows.")
    if row.get("eligible_for_reward") is not True:
        score -= 35
        failures.append("RL/action-policy eval requires reward-eligible measured rows.")
    expected = row.get("expected_output", {}) if isinstance(row.get("expected_output"), dict) else {}
    if expected.get("reward_source") != "observed_outcome_row":
        score -= 35
        failures.append("RL reward source must be observed_outcome_row.")
    if not isinstance(expected.get("reward"), (int, float)):
        score -= 25
        failures.append("RL reward must be numeric.")
    return score, failures


def _role_checks(agent_id: str) -> list[str]:
    return {
        "customer_agent": ["grounded public venue facts", "no reward rows", "customer/internal data separation"],
        "scan_agent": ["live-feed trust classification", "review labels supervised only", "confidence threshold"],
        "react_agent": ["observed incident outcome rows", "scenario and policy present", "no reward mutation"],
        "proactive_agent": ["observed weak-signal outcome rows", "scenario and policy present", "no generated cases"],
        "ops_chat": ["style/safety labels present", "no reward rows", "operator-safe scope"],
        "rl_action_policy": ["measured outcome reward", "numeric reward", "observed_outcome_row reward source"],
    }.get(agent_id, ["known role scope"])


def _global_blockers(pack: dict[str, Any], role_results: list[dict[str, Any]]) -> list[str]:
    blockers = []
    if pack.get("status") not in {"generated", "generated_with_blockers"}:
        blockers.append(f"Controlled pack status is {pack.get('status') or 'missing'}.")
    if pack.get("uses_seed_data") is not False:
        blockers.append("Controlled pack must not use seed/generated data.")
    if pack.get("labels_or_reward_changed") is not False:
        blockers.append("Controlled pack must not change labels or reward.")
    if pack.get("llm_used_for_reward_or_label") is not False:
        blockers.append("Controlled pack must not use LLM for reward or labels.")
    for row in role_results:
        if row.get("passed") is not True:
            blockers.append(f"{row.get('agent_id')} failed eval gate: score {row.get('score')}/{row.get('min_score')}.")
    return blockers[:30]


def _write_eval_artifact(report: dict[str, Any]) -> dict[str, Any]:
    directory = _artifact_dir()
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{report.get('id')}.eval.json")
    report_with_path = dict(report)
    durable = _write_durable_eval(report)
    report_with_path["artifacts"] = {"status": "written", "paths": {"eval_report": path}, "durable": durable}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report_with_path, handle, indent=2, sort_keys=True)
    return {"status": "written", "paths": {"eval_report": path}, "durable": durable}


def _write_durable_eval(report: dict[str, Any]) -> dict[str, Any]:
    try:
        from mongo_memory import record_controlled_training_eval

        return record_controlled_training_eval(_durable_eval_document(report))
    except Exception as error:
        return {"status": "skipped", "mode": "durable_eval_error", "reason": str(error)[:160]}


def _latest_durable_eval() -> dict[str, Any] | None:
    try:
        from mongo_memory import get_latest_controlled_training_eval

        latest = get_latest_controlled_training_eval()
    except Exception:
        latest = None
    return latest if isinstance(latest, dict) and latest.get("id") else None


def _durable_eval_document(report: dict[str, Any]) -> dict[str, Any]:
    role_results = report.get("role_results", []) if isinstance(report.get("role_results"), list) else []
    compact_roles = [
        {
            "agent_id": row.get("agent_id"),
            "status": row.get("status"),
            "passed": row.get("passed"),
            "score": row.get("score"),
            "min_score": row.get("min_score"),
            "example_count": row.get("example_count"),
            "failure_reasons": row.get("failure_reasons", [])[:8] if isinstance(row.get("failure_reasons"), list) else [],
        }
        for row in role_results
        if isinstance(row, dict)
    ]
    return {
        "id": report.get("id"),
        "created_at": report.get("created_at"),
        "status": report.get("status"),
        "mode": report.get("mode"),
        "pack_id": report.get("pack_id"),
        "summary": report.get("summary") if isinstance(report.get("summary"), dict) else {},
        "role_results": compact_roles,
        "readiness_issues": report.get("readiness_issues", [])[:30] if isinstance(report.get("readiness_issues"), list) else [],
        "decision": report.get("decision"),
        "training_rule": report.get("training_rule"),
        "boundaries": report.get("boundaries", [])[:12] if isinstance(report.get("boundaries"), list) else [],
        "uses_seed_data": report.get("uses_seed_data"),
        "labels_or_reward_changed": report.get("labels_or_reward_changed"),
        "llm_used_for_reward_or_label": report.get("llm_used_for_reward_or_label"),
        "gcp_training_started": report.get("gcp_training_started"),
        "model_promotion_started": report.get("model_promotion_started"),
        "durability_contract": "Compact controlled-eval record for cross-instance resilience gates; full local JSON remains best-effort artifact.",
    }


def _artifact_dir() -> str:
    return os.getenv("PARKPULSE_CONTROLLED_TRAINING_ARTIFACT_DIR", "/tmp/parkpulse/controlled_training_generation")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value in {None, ""}:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default
