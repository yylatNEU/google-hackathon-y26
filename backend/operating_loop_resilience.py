from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _check(name: str, passed: bool, *, critical: bool, evidence: dict[str, Any] | None = None, issue: str | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "status": "passed" if passed else "failed",
        "passed": passed,
        "critical": critical,
        "evidence": evidence or {},
        "issue": issue,
    }


def _artifact_path() -> Path:
    configured = os.getenv("PARKPULSE_LOOP_RESILIENCE_ARTIFACT_PATH", "").strip()
    if configured:
        return Path(configured)
    return Path("artifacts") / "operating-loop-resilience-latest.json"


def _persist_artifact(report: dict[str, Any]) -> dict[str, Any]:
    path = _artifact_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
        return {"status": "written", "path": str(path)}
    except Exception as error:
        return {"status": "failed", "path": str(path), "reason": str(error)[:300]}


def _load_default_inputs() -> dict[str, Any]:
    from controlled_training_eval import latest_controlled_training_eval
    from gcp_live_readiness import build_gcp_live_readiness
    from live_feedback_loop import live_feed_health, review_training_ledger
    from prod_reliability_qa_agent import run_production_reliability_qa

    return {
        "reliability_report": run_production_reliability_qa("operating loop resilience validation"),
        "gcp_live_readiness": build_gcp_live_readiness(),
        "live_feed_health": live_feed_health(),
        "review_ledger": review_training_ledger(limit=240),
        "controlled_eval": latest_controlled_training_eval(),
    }


def _sustainability_checks(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    reliability = _as_dict(inputs.get("reliability_report"))
    live_readiness = _as_dict(inputs.get("gcp_live_readiness"))
    agent = _as_dict(reliability.get("agent"))
    permissions = _as_dict(agent.get("permissions"))
    checks = _as_dict(live_readiness.get("checks"))
    proof_modes = {name: _as_dict(value).get("proof_mode") for name, value in checks.items()}
    allowed_proof_modes = all(mode in {"live", "mocked", "skipped"} for mode in proof_modes.values())
    return [
        _check(
            "qa_agent_read_only",
            permissions.get("dispatch") is False and permissions.get("memory_write") is False,
            critical=True,
            evidence={"permissions": permissions},
            issue="Reliability QA must never dispatch or write memory.",
        ),
        _check(
            "no_critical_release_blockers",
            not _as_list(reliability.get("critical_findings")),
            critical=True,
            evidence={"critical_findings": reliability.get("critical_findings", [])},
            issue="Critical safety/policy findings block sustainable operation.",
        ),
        _check(
            "bounded_eval_latency",
            os.getenv("PARKPULSE_HOSTED_EVAL_BLOCKING", "").strip().lower() not in {"1", "true", "yes", "on"},
            critical=False,
            evidence={"hosted_eval_blocking": os.getenv("PARKPULSE_HOSTED_EVAL_BLOCKING", "false")},
            issue="Hosted eval should be deferred by default so operators get the local scorecard first.",
        ),
        _check(
            "proof_modes_are_explicit",
            bool(proof_modes) and allowed_proof_modes,
            critical=True,
            evidence={"proof_modes": proof_modes},
            issue="Every GCP proof surface must classify as live, mocked, or skipped.",
        ),
    ]


def _anti_fragility_checks(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    reliability = _as_dict(inputs.get("reliability_report"))
    live_readiness = _as_dict(inputs.get("gcp_live_readiness"))
    live_feed = _as_dict(inputs.get("live_feed_health"))
    failure_modes = _as_list(reliability.get("failure_mode_matrix"))
    required_live = _as_list(_as_dict(live_readiness.get("summary")).get("required_live_checks"))
    live_summary = _as_dict(live_feed.get("summary"))
    return [
        _check(
            "failure_mode_matrix_covers_degradation",
            len(failure_modes) >= 10,
            critical=True,
            evidence={"failure_mode_count": len(failure_modes)},
            issue="Anti-fragility requires explicit failure-mode coverage, not happy-path QA.",
        ),
        _check(
            "strict_gcp_gate_available",
            {"cloud_trace_export", "vertex_eval_trigger", "bigquery"} <= set(str(item) for item in required_live),
            critical=True,
            evidence={"required_live_checks": required_live},
            issue="Strict GCP proof must gate Cloud Trace, Vertex eval, and BigQuery together.",
        ),
        _check(
            "live_feed_health_contract_present",
            int(live_summary.get("required_feed_count") or 0) >= 6,
            critical=False,
            evidence={"summary": live_summary},
            issue="Weak-signal resilience needs all required live-feed domains represented.",
        ),
        _check(
            "dynamic_cascade_coverage_present",
            bool(_as_dict(reliability.get("scenario_coverage_evaluation")).get("dynamic_state_chain")),
            critical=True,
            evidence={"scenario_coverage": reliability.get("scenario_coverage_evaluation", {})},
            issue="Loop must test secondary effects across ride, crowd, staff, food, sentiment, and safety.",
        ),
    ]


def _self_improvement_checks(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    review_ledger = _as_dict(inputs.get("review_ledger"))
    controlled_eval = _as_dict(inputs.get("controlled_eval"))
    training_readiness = _as_dict(inputs.get("training_readiness"))
    rows = _as_list(review_ledger.get("rows"))
    unsafe_rows = [
        row
        for row in rows
        if isinstance(row, dict)
        and (row.get("llm_used_for_reward_or_label") is True or row.get("labels_or_reward_changed") is True)
    ]
    controlled_eval_present = controlled_eval.get("status") not in {None, "empty", "error"}
    controlled_eval_safe = (
        controlled_eval.get("labels_or_reward_changed") is not True
        and controlled_eval.get("llm_used_for_reward_or_label") is not True
        and controlled_eval.get("gcp_training_started") is not True
        and controlled_eval.get("model_promotion_started") is not True
    )
    training_boundaries = " ".join(str(item) for item in _as_list(training_readiness.get("boundaries"))).lower()
    return [
        _check(
            "human_review_labels_do_not_set_reward",
            not unsafe_rows and "reward remains measured" in str(review_ledger.get("training_rule", "")).lower(),
            critical=True,
            evidence={"unsafe_row_count": len(unsafe_rows), "training_rule": review_ledger.get("training_rule")},
            issue="Self-improvement must keep human/LLM labels separate from measured reward.",
        ),
        _check(
            "controlled_eval_gate_is_safe",
            controlled_eval_safe,
            critical=True,
            evidence={
                "status": controlled_eval.get("status"),
                "labels_or_reward_changed": controlled_eval.get("labels_or_reward_changed"),
                "llm_used_for_reward_or_label": controlled_eval.get("llm_used_for_reward_or_label"),
                "gcp_training_started": controlled_eval.get("gcp_training_started"),
                "model_promotion_started": controlled_eval.get("model_promotion_started"),
            },
            issue="Controlled eval must never mutate labels, reward, training, promotion, or live actions.",
        ),
        _check(
            "controlled_eval_gate_has_run",
            controlled_eval_present,
            critical=False,
            evidence={"status": controlled_eval.get("status"), "readiness_issues": controlled_eval.get("readiness_issues", [])},
            issue="Run controlled training eval before claiming the loop is actively improving.",
        ),
        _check(
            "training_readiness_boundaries_present",
            not training_readiness or ("reward" in training_boundaries and "rollback" in training_boundaries),
            critical=False,
            evidence={"status": training_readiness.get("status"), "boundaries": training_readiness.get("boundaries", [])},
            issue="Training readiness should state reward and rollback boundaries.",
        ),
    ]


def _summarize_sections(sections: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    all_checks = [check for checks in sections.values() for check in checks]
    failed = [check for check in all_checks if not check["passed"]]
    critical_failed = [check for check in failed if check["critical"]]
    score = round(100 * (len(all_checks) - len(failed)) / len(all_checks)) if all_checks else 0
    return {
        "status": "failed" if critical_failed else "passed" if not failed else "passed_with_conditions",
        "score": score,
        "check_count": len(all_checks),
        "failed_count": len(failed),
        "critical_failed_count": len(critical_failed),
        "critical_failures": [check["name"] for check in critical_failed],
        "conditions": [check["issue"] for check in failed if check.get("issue")],
    }


def build_operating_loop_resilience_report(
    *,
    inputs: dict[str, Any] | None = None,
    write_artifact: bool = True,
) -> dict[str, Any]:
    source_inputs = dict(inputs) if isinstance(inputs, dict) else _load_default_inputs()
    sections = {
        "sustainability": _sustainability_checks(source_inputs),
        "anti_fragility": _anti_fragility_checks(source_inputs),
        "self_improvement": _self_improvement_checks(source_inputs),
    }
    summary = _summarize_sections(sections)
    report = {
        "status": summary["status"],
        "mode": "operating_loop_resilience_gate",
        "generated_at": _now_iso(),
        "decision": "allow_loop_claim" if summary["status"] == "passed" else "allow_with_conditions" if summary["status"] == "passed_with_conditions" else "block_loop_claim",
        "summary": summary,
        "sections": sections,
        "principles": {
            "sustainable": "Operator response is bounded, read-only QA cannot mutate state, and proof surfaces explicitly show live/mocked/skipped state.",
            "anti_fragile": "Known failure modes, strict proof gates, live-feed health, and cascade tests make degradation visible and recoverable.",
            "self_improving": "Only reviewed labels and measured outcomes feed training; eval gates and promotion/rollback rules prevent silent model drift.",
        },
    }
    if write_artifact:
        report["artifact"] = _persist_artifact(report)
    else:
        report["artifact"] = {"status": "not_written"}
    return report
