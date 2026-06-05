from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import UTC, datetime
from typing import Any


DEFAULT_ARTIFACT_DIR = "/tmp/parkpulse/controlled_training_generation"
TRAINING_AGENT_ORDER = ("customer_agent", "scan_agent", "react_agent", "proactive_agent", "ops_chat", "rl_action_policy")


def generate_controlled_training_pack(
    *,
    customer_details: dict[str, Any],
    training_readiness: dict[str, Any],
    review_label_pipeline: dict[str, Any],
    review_label_decisions: dict[str, Any],
    actual_training: dict[str, Any],
    live_feed_health: dict[str, Any],
    max_examples: int = 60,
    write_artifacts: bool = True,
) -> dict[str, Any]:
    scope_plan = _scope_plan(training_readiness)
    examples = _bounded_examples(
        [
            *_customer_eval_examples(customer_details, scope_plan),
            *_review_label_examples(review_label_decisions),
            *_live_feed_eval_examples(live_feed_health, scope_plan),
            *_actual_outcome_examples(actual_training, scope_plan),
            *_ops_chat_eval_examples(review_label_pipeline, scope_plan),
        ],
        max_examples,
    )
    supervised_examples = [row for row in examples if row.get("eligible_for_supervised_training")]
    eval_examples = [row for row in examples if row.get("split") == "eval"]
    rl_examples = [row for row in examples if row.get("agent_id") == "rl_action_policy" and row.get("eligible_for_reward")]
    blockers = _generation_blockers(training_readiness, examples)
    status = "generated" if examples and not blockers else "generated_with_blockers" if examples else "blocked"
    manifest = {
        "id": _hash_id("controlled_training_pack", {"created_at": _now_iso(), "examples": [row.get("id") for row in examples]}),
        "created_at": _now_iso(),
        "status": status,
        "mode": "controlled_eval_training_generation",
        "readiness_status": training_readiness.get("status"),
        "summary": {
            "role_scope_count": len(scope_plan),
            "ready_model_scope_count": len([row for row in scope_plan if row.get("model_training_ready") is True]),
            "eval_generation_scope_count": len([row for row in scope_plan if row.get("eval_generation_ready") is True]),
            "example_count": len(examples),
            "supervised_example_count": len(supervised_examples),
            "eval_example_count": len(eval_examples),
            "rl_reward_example_count": len(rl_examples),
            "approved_review_label_count": _approved_review_label_count(review_label_decisions),
            "observed_outcome_rows": _int(actual_training.get("sample_count")),
        },
        "scope_plan": scope_plan,
        "examples": examples,
        "readiness_issues": blockers,
        "training_rule": "This pack creates role-scoped eval/training artifacts only. It does not start GCP training, change rewards, promote policies, or dispatch actions.",
        "boundaries": [
            "Customer examples use venue-approved public data and remain separate from internal ops data.",
            "Approved review labels are supervised-label evidence only.",
            "RL/action-policy rows use measured outcome rewards only; LLM and review labels cannot set reward.",
            "Promotion still requires the existing promotion and rollback gates after offline training.",
        ],
        "uses_seed_data": False,
        "labels_or_reward_changed": False,
        "llm_used_for_reward_or_label": False,
        "gcp_training_started": False,
        "model_promotion_started": False,
    }
    artifacts = _write_artifacts(manifest) if write_artifacts else {"status": "not_written", "artifact_count": 0, "paths": {}}
    return {**manifest, "artifacts": artifacts}


def latest_controlled_training_pack() -> dict[str, Any]:
    directory = _artifact_dir()
    if not os.path.isdir(directory):
        return {"status": "empty", "mode": "controlled_eval_training_generation_latest", "readiness_issues": ["No controlled training generation artifacts have been written."]}
    manifests = [os.path.join(directory, name) for name in os.listdir(directory) if name.endswith(".manifest.json")]
    if not manifests:
        return {"status": "empty", "mode": "controlled_eval_training_generation_latest", "readiness_issues": ["No manifest artifacts found."]}
    latest = max(manifests, key=lambda path: os.path.getmtime(path))
    with open(latest, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if isinstance(manifest, dict):
        manifest["artifacts"] = {**manifest.get("artifacts", {}), "latest_manifest_path": latest}
        return manifest
    return {"status": "error", "mode": "controlled_eval_training_generation_latest", "readiness_issues": [f"Latest manifest is not an object: {latest}"]}


def _scope_plan(training: dict[str, Any]) -> list[dict[str, Any]]:
    agents = training.get("agents", {}) if isinstance(training.get("agents"), dict) else {}
    rows: list[dict[str, Any]] = []
    for agent_id in TRAINING_AGENT_ORDER:
        row = agents.get(agent_id, {}) if isinstance(agents.get(agent_id), dict) else {}
        model_ready = row.get("model_training_ready") is True
        eval_ready = row.get("eval_generation_ready") is True
        rows.append(
            {
                "agent_id": agent_id,
                "status": row.get("status") or "unknown",
                "model_training_ready": model_ready,
                "eval_generation_ready": eval_ready,
                "recommended_training_mode": row.get("recommended_training_mode") or "hold",
                "generation_mode": _generation_mode(agent_id, model_ready, eval_ready),
                "blockers": row.get("blockers", []) if isinstance(row.get("blockers"), list) else [],
                "evidence": row.get("evidence", {}) if isinstance(row.get("evidence"), dict) else {},
            }
        )
    return rows


def _generation_mode(agent_id: str, model_ready: bool, eval_ready: bool) -> str:
    if agent_id == "rl_action_policy" and model_ready:
        return "offline_rl_reward_manifest"
    if model_ready:
        return "supervised_training_and_eval"
    if eval_ready:
        return "eval_generation_only"
    return "hold"


def _customer_eval_examples(details: dict[str, Any], scope_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not _scope_ready(scope_plan, "customer_agent"):
        return []
    picks = details.get("recommended_public_options", {}) if isinstance(details.get("recommended_public_options"), dict) else {}
    best_ride = picks.get("best_ride", {}) if isinstance(picks.get("best_ride"), dict) else {}
    best_food = picks.get("best_food", {}) if isinstance(picks.get("best_food"), dict) else {}
    quality = details.get("data_quality", {}) if isinstance(details.get("data_quality"), dict) else {}
    return [
        _example(
            agent_id="customer_agent",
            split="eval",
            training_scope="customer_llm_eval_and_supervised_examples",
            source="customer_public_data_feed",
            input_payload={
                "task": "Recommend a guest-safe ride and food backup from the venue-approved public feed.",
                "best_ride": best_ride.get("name"),
                "best_food": best_food.get("name"),
            },
            expected_output={
                "label": "customer_recommendation_grounded",
                "requirements": ["Use only public venue facts.", "Do not expose internal operations policy.", "Include a fallback option."],
            },
            evidence={"quality_status": quality.get("status"), "quality_score": quality.get("score"), "source": "customer_public_data_feed"},
            eligible_for_supervised_training=False,
            eligible_for_reward=False,
        )
    ]


def _review_label_examples(decisions: dict[str, Any]) -> list[dict[str, Any]]:
    rows = decisions.get("rows", []) if isinstance(decisions.get("rows"), list) else []
    examples = []
    for row in rows:
        if not isinstance(row, dict) or row.get("eligible_for_supervised_training") is not True:
            continue
        snapshot = row.get("candidate_snapshot", {}) if isinstance(row.get("candidate_snapshot"), dict) else {}
        agent_id = str(row.get("agent_id") or snapshot.get("agent_id") or "unknown")
        if agent_id == "rl_action_policy":
            continue
        examples.append(
            _example(
                agent_id=agent_id,
                split="train",
                training_scope=str(row.get("training_scope") or snapshot.get("training_scope") or "review_label_supervised"),
                source="approved_review_label_decision",
                input_payload={"summary": snapshot.get("input_summary"), "evidence": snapshot.get("evidence")},
                expected_output={"label": row.get("final_label"), "decision": row.get("decision")},
                evidence={"decision_id": row.get("id"), "candidate_id": row.get("candidate_id"), "reviewer": row.get("reviewer")},
                eligible_for_supervised_training=True,
                eligible_for_reward=False,
            )
        )
    return examples


def _live_feed_eval_examples(health: dict[str, Any], scope_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not _scope_ready(scope_plan, "scan_agent"):
        return []
    feeds = health.get("feeds", []) if isinstance(health.get("feeds"), list) else []
    examples = []
    for feed in feeds[:12]:
        if not isinstance(feed, dict):
            continue
        examples.append(
            _example(
                agent_id="scan_agent",
                split="eval",
                training_scope="scan_supervised_signal_ranking",
                source="live_feed_health",
                input_payload={"source": feed.get("source"), "status": feed.get("status"), "confidence": feed.get("confidence"), "age_seconds": feed.get("age_seconds")},
                expected_output={"label": "trusted_feed" if str(feed.get("status")) in {"ready", "trusted"} else "weak_or_stale_feed"},
                evidence={"readiness_issues": feed.get("readiness_issues"), "required": feed.get("required")},
                eligible_for_supervised_training=False,
                eligible_for_reward=False,
            )
        )
    return examples


def _actual_outcome_examples(actual: dict[str, Any], scope_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = actual.get("training_rows", []) if isinstance(actual.get("training_rows"), list) else []
    if not rows:
        return []
    examples = []
    if _scope_ready(scope_plan, "react_agent"):
        examples.extend(_outcome_rows_for_agent(rows, "react_agent", "react_agent_supervised_decision_and_outcome_eval", reward=False))
    if _scope_ready(scope_plan, "proactive_agent"):
        examples.extend(_outcome_rows_for_agent(rows, "proactive_agent", "proactive_weak_signal_forecast_eval", reward=False))
    if _scope_ready(scope_plan, "rl_action_policy"):
        examples.extend(_outcome_rows_for_agent(rows, "rl_action_policy", "observed_outcome_batch_rl_or_contextual_bandit_only", reward=True))
    return examples


def _outcome_rows_for_agent(rows: list[dict[str, Any]], agent_id: str, training_scope: str, *, reward: bool) -> list[dict[str, Any]]:
    examples = []
    for row in rows[:12]:
        if not isinstance(row, dict):
            continue
        examples.append(
            _example(
                agent_id=agent_id,
                split="train" if reward else "eval",
                training_scope=training_scope,
                source="observed_outcome_training_row",
                input_payload={
                    "scenario_key": _scenario_key(row),
                    "policy": row.get("policy") or row.get("policy_id") or row.get("policy_key") or row.get("mode"),
                    "features": row.get("features") if isinstance(row.get("features"), dict) else {},
                },
                expected_output={
                    "label": row.get("label") or row.get("outcome_label") or "observed_outcome",
                    "reward": row.get("reward") or row.get("reward_delta") or row.get("fitness"),
                    "reward_source": "observed_outcome_row" if reward else None,
                },
                evidence={"row_id": row.get("id"), "source": row.get("source"), "uses_generated_data": False},
                eligible_for_supervised_training=not reward,
                eligible_for_reward=reward,
            )
        )
    return examples


def _scenario_key(row: dict[str, Any]) -> str | None:
    if row.get("scenario_key"):
        return str(row.get("scenario_key"))
    state_scenario = row.get("stateScenario", {}) if isinstance(row.get("stateScenario"), dict) else {}
    if state_scenario.get("key"):
        return str(state_scenario.get("key"))
    if row.get("scenario"):
        return str(row.get("scenario"))
    return None


def _ops_chat_eval_examples(pipeline: dict[str, Any], scope_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not _scope_ready(scope_plan, "ops_chat"):
        return []
    candidates = pipeline.get("decided", []) if isinstance(pipeline.get("decided"), list) else []
    examples = []
    for candidate in candidates[:8]:
        if not isinstance(candidate, dict):
            continue
        examples.append(
            _example(
                agent_id="ops_chat",
                split="eval",
                training_scope="ops_chat_eval_and_supervised_style_safety",
                source="review_label_pipeline_decided",
                input_payload={"summary": candidate.get("input_summary"), "training_scope": candidate.get("training_scope")},
                expected_output={"label": candidate.get("proposed_label"), "decision": (candidate.get("decision") or {}).get("decision") if isinstance(candidate.get("decision"), dict) else None},
                evidence={"candidate_id": candidate.get("id"), "source": candidate.get("source")},
                eligible_for_supervised_training=False,
                eligible_for_reward=False,
            )
        )
    return examples


def _bounded_examples(examples: list[dict[str, Any]], max_examples: int) -> list[dict[str, Any]]:
    limit = max(1, min(250, int(max_examples or 60)))
    deduped: dict[str, dict[str, Any]] = {}
    for row in examples:
        deduped[str(row["id"])] = row
    rows = list(deduped.values())
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    for agent_id in TRAINING_AGENT_ORDER:
        role_row = next((row for row in rows if row.get("agent_id") == agent_id and str(row.get("id")) not in selected_ids), None)
        if role_row is None:
            continue
        selected.append(role_row)
        selected_ids.add(str(role_row.get("id")))
        if len(selected) >= limit:
            return selected
    for row in rows:
        row_id = str(row.get("id"))
        if row_id in selected_ids:
            continue
        selected.append(row)
        selected_ids.add(row_id)
        if len(selected) >= limit:
            break
    return selected


def _example(
    *,
    agent_id: str,
    split: str,
    training_scope: str,
    source: str,
    input_payload: dict[str, Any],
    expected_output: dict[str, Any],
    evidence: dict[str, Any],
    eligible_for_supervised_training: bool,
    eligible_for_reward: bool,
) -> dict[str, Any]:
    payload = {
        "agent_id": agent_id,
        "split": split,
        "training_scope": training_scope,
        "source": source,
        "input": input_payload,
        "expected_output": expected_output,
        "evidence": evidence,
    }
    return {
        "id": _hash_id("training_example", payload),
        "created_at": _now_iso(),
        **payload,
        "eligible_for_supervised_training": bool(eligible_for_supervised_training),
        "eligible_for_reward": bool(eligible_for_reward),
        "generated_by": "deterministic_controlled_training_pack_builder",
        "uses_seed_data": False,
        "labels_or_reward_changed": False,
        "llm_used_for_reward_or_label": False,
    }


def _generation_blockers(training: dict[str, Any], examples: list[dict[str, Any]]) -> list[str]:
    blockers = []
    if not examples:
        blockers.append("No eval or training examples could be generated from current approved data.")
    if training.get("status") not in {"ready", "partially_ready"}:
        blockers.append(f"Training readiness status is {training.get('status') or 'unknown'}.")
    summary = training.get("summary", {}) if isinstance(training.get("summary"), dict) else {}
    if _int(summary.get("open_review_count")) > 0:
        blockers.append(f"Open review queue remains non-zero: {summary.get('open_review_count')}.")
    return blockers


def _scope_ready(scope_plan: list[dict[str, Any]], agent_id: str) -> bool:
    for row in scope_plan:
        if row.get("agent_id") == agent_id:
            return row.get("generation_mode") != "hold"
    return False


def _approved_review_label_count(decisions: dict[str, Any]) -> int:
    summary = decisions.get("summary", {}) if isinstance(decisions.get("summary"), dict) else {}
    return _int(summary.get("approved_label_count"))


def _write_artifacts(manifest: dict[str, Any]) -> dict[str, Any]:
    directory = _artifact_dir()
    os.makedirs(directory, exist_ok=True)
    artifact_id = str(manifest.get("id") or _hash_id("controlled_training_pack", manifest))
    manifest_path = os.path.join(directory, f"{artifact_id}.manifest.json")
    examples_path = os.path.join(directory, f"{artifact_id}.examples.jsonl")
    manifest_with_paths = dict(manifest)
    manifest_with_paths["artifacts"] = {"status": "written", "artifact_count": 2, "paths": {"manifest": manifest_path, "examples_jsonl": examples_path}}
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest_with_paths, handle, indent=2, sort_keys=True)
    with open(examples_path, "w", encoding="utf-8") as handle:
        for row in manifest.get("examples", []):
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    return {"status": "written", "artifact_count": 2, "paths": {"manifest": manifest_path, "examples_jsonl": examples_path}}


def _artifact_dir() -> str:
    return os.getenv("PARKPULSE_CONTROLLED_TRAINING_ARTIFACT_DIR", DEFAULT_ARTIFACT_DIR)


def _hash_id(prefix: str, payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(encoded).hexdigest()[:18]}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _int(value: Any, default: int = 0) -> int:
    try:
        if value in {None, ""}:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default
