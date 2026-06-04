from __future__ import annotations

import os
import time
import hashlib
import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from bigquery_analytics import bigquery_status, online_improvement_status
from live_feedback_loop import live_food_ops_training_gate, live_guest_flow_training_gate, live_operator_signal_training_gate, live_ride_ops_training_gate, live_staffing_training_gate, live_weather_training_gate
from mongo_memory import get_latest_memory_documents, get_operational_memory_dashboard


MIN_ACTUAL_TRAINING_ROWS = 3
GENERATED_SOURCE_PATTERNS = ("seed", "synthetic", "demo", "validation")
_LAST_BQML_TRAINING: dict[str, Any] = {}
KNOWN_TRAINING_SCENARIOS = {
    "ride_down",
    "food_spike",
    "staff_shortage",
    "storm_response",
    "proactive_eventops",
    "proactive_watchtower",
    "scan",
}


def actual_training_status(min_rows: int = MIN_ACTUAL_TRAINING_ROWS, run_gcp_training: bool | None = None, detail: str = "full") -> dict[str, Any]:
    if str(detail or "full").strip().lower() in {"readiness", "gate", "fast"}:
        return _actual_training_readiness_status(min_rows=min_rows, run_gcp_training=run_gcp_training)

    dashboard = get_operational_memory_dashboard("actual outcome training reward policy gate follow through")
    memory_rows = _bounded_memory_training_rows()
    case_bank_rows = _live_feed_case_bank_training_rows()
    bq = bigquery_status()
    bq_rows, bq_error = _bigquery_training_rows(bq)
    heartbeat_rows = _dedupe_training_rows([*_heartbeat_training_signal_rows(), *_delayed_outcome_attribution_training_rows()])
    reasoning_audits = _reasoning_training_audits()
    causal_memories = _causal_reasoning_memories()
    observed_rows = _sort_training_rows_latest_first(_dedupe_training_rows([*heartbeat_rows, *bq_rows, *memory_rows, *case_bank_rows]))
    rows = _augment_rows_with_reasoning_features(observed_rows, reasoning_audits, causal_memories)
    source = _training_source(heartbeat_rows, bq_rows, memory_rows, case_bank_rows)
    sample_count = len(rows)
    gcp_training_enabled = _env_bool("PARKPULSE_ENABLE_GCP_ML_TRAINING")
    requested_gcp_training = bool(run_gcp_training)
    reasoning_export = (
        _export_reasoning_audits_to_bigquery(bq, reasoning_audits)
        if requested_gcp_training and gcp_training_enabled
        else _reasoning_audit_export_not_started(bq, reasoning_audits)
    )
    causal_export = (
        _export_causal_memory_to_bigquery(bq, causal_memories)
        if requested_gcp_training and gcp_training_enabled
        else _causal_memory_export_not_started(bq, causal_memories)
    )
    include_reasoning_features = reasoning_export.get("status") in {"exported", "ready", "unchanged"}
    include_causal_features = causal_export.get("status") in {"exported", "ready", "unchanged"}
    gcp_training = (
        _run_bigquery_ml_training(bq, True, include_reasoning_features=include_reasoning_features, include_causal_features=include_causal_features)
        if requested_gcp_training and gcp_training_enabled
        else _gcp_training_not_started(bq)
    )
    model = _train_contextual_bandit(rows)
    model_version = _model_version(source, model, rows)
    fitness_curve = _fitness_curve(rows)
    scenario_fitness = _scenario_balanced_fitness(rows)
    promotion_gate = _model_promotion_gate(rows, model, fitness_curve, scenario_fitness, source, bq)
    promoted_slice_policy = _promoted_slice_policy_snapshot(model_version, model, promotion_gate, scenario_fitness, source, bq)
    reasoning_feature_audit = _reasoning_feature_audit_summary(reasoning_audits, rows, reasoning_export)
    causal_feature_audit = _causal_feature_audit_summary(causal_memories, rows, causal_export)
    live_weather_gate = live_weather_training_gate()
    live_ride_ops_gate = live_ride_ops_training_gate()
    live_guest_flow_gate = live_guest_flow_training_gate()
    live_staffing_gate = live_staffing_training_gate()
    live_food_ops_gate = live_food_ops_training_gate()
    live_operator_signal_gate = live_operator_signal_training_gate()
    offline_training_path = _offline_training_path(bq, gcp_training, model_version, reasoning_feature_audit, causal_feature_audit)
    promoted_slice_policy_log = _write_promoted_slice_policy_snapshot(promoted_slice_policy)
    rollback_ledger = _slice_rollback_ledger_payload(promoted_slice_policy)
    readiness_issues: list[str] = []
    if sample_count < min_rows:
        readiness_issues.append(f"Need at least {min_rows} observed outcome rows; found {sample_count}.")
    if bq_error:
        readiness_issues.append(f"BigQuery training row query failed: {bq_error}")
    if requested_gcp_training and not gcp_training_enabled:
        readiness_issues.append("PARKPULSE_ENABLE_GCP_ML_TRAINING is not enabled.")
    if requested_gcp_training and gcp_training_enabled and gcp_training.get("status") not in {"started", "recently_started"}:
        readiness_issues.extend(gcp_training.get("readiness_issues", []))
    if requested_gcp_training and gcp_training_enabled and reasoning_export.get("status") == "error":
        readiness_issues.extend(reasoning_export.get("readiness_issues", []))
    if requested_gcp_training and gcp_training_enabled and causal_export.get("status") == "error":
        readiness_issues.extend(causal_export.get("readiness_issues", []))
    if live_weather_gate.get("eligible") is False:
        readiness_issues.append(f"Live weather training gate blocked: {live_weather_gate.get('reason')}")
    if live_ride_ops_gate.get("eligible") is False:
        readiness_issues.append(f"Live ride ops training gate blocked: {live_ride_ops_gate.get('reason')}")
    if live_guest_flow_gate.get("eligible") is False:
        readiness_issues.append(f"Live guest flow training gate blocked: {live_guest_flow_gate.get('reason')}")
    for label, gate in (("staffing", live_staffing_gate), ("food ops", live_food_ops_gate), ("operator signal", live_operator_signal_gate)):
        if gate.get("eligible") is False:
            readiness_issues.append(f"Live {label} training gate blocked: {gate.get('reason')}")

    return {
        "status": "ready" if sample_count >= min_rows else "not_ready",
        "mode": "actual_outcome_training",
        "uses_generated_data": False,
        "source": source,
        "sample_count": sample_count,
        "min_sample_count": min_rows,
        "model": model,
        "model_ops": {
            "version": model_version,
            "current_policy_id": model.get("best_policy_id"),
            "candidate_generator": "bounded_optimizer_candidate_layer",
            "promotion_gate": promotion_gate,
            "fitness_curve": fitness_curve,
            "scenario_fitness": scenario_fitness,
            "promoted_slice_policy": promoted_slice_policy,
            "promoted_slice_policy_log": promoted_slice_policy_log,
            "slice_rollback_ledger": rollback_ledger,
            "offline_training_path": offline_training_path,
            "reasoning_feature_audit": reasoning_feature_audit,
            "causal_feature_audit": causal_feature_audit,
            "rollback": {
                "available": True,
                "mechanism": "Keep last promoted policy snapshot and reload it if challenger fitness regresses.",
            },
            "live_weather_training_gate": live_weather_gate,
            "live_ride_ops_training_gate": live_ride_ops_gate,
            "live_guest_flow_training_gate": live_guest_flow_gate,
            "live_staffing_training_gate": live_staffing_gate,
            "live_food_ops_training_gate": live_food_ops_gate,
            "live_operator_signal_training_gate": live_operator_signal_gate,
        },
        "training_rows": rows[:12],
        "gcp_ml": {
            "online_improvement": online_improvement_status(),
            "bigquery": bq,
            "bigquery_ml_training": gcp_training,
            "bigquery_ml_training_enabled": gcp_training_enabled,
            "reasoning_audit_export": reasoning_export,
            "causal_memory_export": causal_export,
        },
        "debug": {
            "readiness_issues": readiness_issues,
            "memory_rows_available": len(memory_rows),
            "case_bank_rows_available": len(case_bank_rows),
            "bigquery_rows_available": len(bq_rows),
            "heartbeat_training_signal_rows_available": len(heartbeat_rows),
            "memory_status": dashboard.get("status", {}),
        },
    }


def _actual_training_readiness_status(min_rows: int = MIN_ACTUAL_TRAINING_ROWS, run_gcp_training: bool | None = None) -> dict[str, Any]:
    bq = bigquery_status()
    heartbeat_rows = _dedupe_training_rows([*_heartbeat_training_signal_rows(), *_delayed_outcome_attribution_training_rows()])
    memory_rows = _bounded_memory_training_rows()
    case_bank_rows = _live_feed_case_bank_training_rows()
    bq_rows: list[dict[str, Any]] = []
    bq_error: str | None = None
    if _env_bool("PARKPULSE_READINESS_LOAD_BQ_ROWS"):
        bq_rows, bq_error = _bigquery_training_rows(bq, limit=int(_float(os.getenv("PARKPULSE_READINESS_BQ_ROW_LIMIT"), 80)))
    observed_rows = _sort_training_rows_latest_first(_dedupe_training_rows([*heartbeat_rows, *bq_rows, *memory_rows, *case_bank_rows]))
    rows = _augment_rows_with_reasoning_features(observed_rows, [], [])
    sample_count = len(rows)
    gcp_training_enabled = _env_bool("PARKPULSE_ENABLE_GCP_ML_TRAINING")
    requested_gcp_training = bool(run_gcp_training)
    reasoning_export = _reasoning_audit_export_not_started(bq, [])
    causal_export = _causal_memory_export_not_started(bq, [])
    gcp_training = (
        _run_bigquery_ml_training(bq, True, include_reasoning_features=False, include_causal_features=False)
        if requested_gcp_training and gcp_training_enabled
        else _gcp_training_not_started(bq)
    )
    model = _train_contextual_bandit(rows)
    fitness_curve = _fitness_curve(rows)
    scenario_fitness = _scenario_balanced_fitness(rows)
    live_weather_gate = live_weather_training_gate()
    live_ride_ops_gate = live_ride_ops_training_gate()
    live_guest_flow_gate = live_guest_flow_training_gate()
    live_staffing_gate = live_staffing_training_gate()
    live_food_ops_gate = live_food_ops_training_gate()
    live_operator_signal_gate = live_operator_signal_training_gate()
    readiness_issues: list[str] = []
    if sample_count < min_rows:
        readiness_issues.append(f"Need at least {min_rows} observed outcome rows; found {sample_count}.")
    if bq_error:
        readiness_issues.append(f"BigQuery readiness row check failed: {bq_error[:180]}")
    if requested_gcp_training and not gcp_training_enabled:
        readiness_issues.append("PARKPULSE_ENABLE_GCP_ML_TRAINING is not enabled.")
    if requested_gcp_training and gcp_training_enabled and gcp_training.get("status") not in {"started", "recently_started"}:
        readiness_issues.extend(gcp_training.get("readiness_issues", []))
    if live_weather_gate.get("eligible") is False:
        readiness_issues.append(f"Live weather training gate blocked: {live_weather_gate.get('reason')}")
    if live_ride_ops_gate.get("eligible") is False:
        readiness_issues.append(f"Live ride ops training gate blocked: {live_ride_ops_gate.get('reason')}")
    if live_guest_flow_gate.get("eligible") is False:
        readiness_issues.append(f"Live guest flow training gate blocked: {live_guest_flow_gate.get('reason')}")
    for label, gate in (("staffing", live_staffing_gate), ("food ops", live_food_ops_gate), ("operator signal", live_operator_signal_gate)):
        if gate.get("eligible") is False:
            readiness_issues.append(f"Live {label} training gate blocked: {gate.get('reason')}")
    source = _training_source(heartbeat_rows, bq_rows, memory_rows, case_bank_rows)
    model_version = _model_version(source, model, rows)
    promotion_gate = {
        "status": "hold",
        "decision": "defer_full_promotion_diagnostics",
        "minimum_rows": int(_float(os.getenv("PARKPULSE_MODEL_PROMOTION_MIN_ROWS"), 50)),
        "observed_rows": sample_count,
        "blockers": readiness_issues[:12],
        "warnings": ["Fast readiness mode skips promotion artifact writes; use full/async training evidence for promotion diagnostics."],
        "live_weather_training_gate": live_weather_gate,
        "live_ride_ops_training_gate": live_ride_ops_gate,
        "live_guest_flow_training_gate": live_guest_flow_gate,
        "live_staffing_training_gate": live_staffing_gate,
        "live_food_ops_training_gate": live_food_ops_gate,
        "live_operator_signal_training_gate": live_operator_signal_gate,
    }
    return {
        "status": "ready" if sample_count >= min_rows else "not_ready",
        "mode": "actual_outcome_training",
        "detail": "readiness",
        "uses_generated_data": False,
        "source": source,
        "sample_count": sample_count,
        "min_sample_count": min_rows,
        "model": model,
        "model_ops": {
            "version": model_version,
            "current_policy_id": model.get("best_policy_id"),
            "candidate_generator": "bounded_optimizer_candidate_layer",
            "promotion_gate": promotion_gate,
            "fitness_curve": fitness_curve,
            "scenario_fitness": scenario_fitness,
            "promoted_slice_policy": {"status": "not_evaluated", "reason": "Fast readiness mode does not write promotion snapshots."},
            "promoted_slice_policy_log": {"status": "not_written", "reason": "Fast readiness mode does not write promotion snapshots."},
            "slice_rollback_ledger": {"status": "not_loaded", "reason": "Fast readiness mode skips rollback ledger reads."},
            "offline_training_path": _offline_training_path(
                bq,
                gcp_training,
                model_version,
                _reasoning_feature_audit_summary([], rows, reasoning_export),
                _causal_feature_audit_summary([], rows, causal_export),
            ),
            "reasoning_feature_audit": _reasoning_feature_audit_summary([], rows, reasoning_export),
            "causal_feature_audit": _causal_feature_audit_summary([], rows, causal_export),
            "rollback": {"available": True, "mechanism": "Full diagnostics retain the promoted snapshot rollback path."},
            "live_weather_training_gate": live_weather_gate,
            "live_ride_ops_training_gate": live_ride_ops_gate,
            "live_guest_flow_training_gate": live_guest_flow_gate,
            "live_staffing_training_gate": live_staffing_gate,
            "live_food_ops_training_gate": live_food_ops_gate,
            "live_operator_signal_training_gate": live_operator_signal_gate,
        },
        "training_rows": rows[:12],
        "gcp_ml": {
            "online_improvement": {
                "provider": os.getenv("PARKPULSE_ONLINE_IMPROVEMENT_PROVIDER", "gcp").strip().lower() or "gcp",
                "primary_path": "gcp_bigquery",
                "ready": bool(bq.get("ready")),
                "mode": "online_gcp" if bq.get("ready") else "local_scorecard_with_gcp_export_preview",
                "blocking": False,
                "bigquery": bq,
                "readiness_issues": [] if bq.get("ready") else bq.get("readiness_issues", []),
            },
            "bigquery": bq,
            "bigquery_ml_training": gcp_training,
            "bigquery_ml_training_enabled": gcp_training_enabled,
            "reasoning_audit_export": reasoning_export,
            "causal_memory_export": causal_export,
        },
        "debug": {
            "readiness_issues": _dedupe_text(readiness_issues),
            "memory_rows_available": len(memory_rows),
            "case_bank_rows_available": len(case_bank_rows),
            "bigquery_rows_available": len(bq_rows),
            "bigquery_rows_error": bq_error,
            "heartbeat_training_signal_rows_available": len(heartbeat_rows),
            "memory_status": {"status": "bounded_latest_documents", "limit": int(_float(os.getenv("PARKPULSE_READINESS_MEMORY_ROW_LIMIT"), 120))},
            "bounded_runtime": True,
        },
    }


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value in {None, ""}:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _dedupe_text(values: list[Any]) -> list[str]:
    rows: list[str] = []
    seen = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        rows.append(text)
    return rows


def _scenario_key(row: dict[str, Any]) -> str:
    state_scenario = row.get("stateScenario", {}) if isinstance(row.get("stateScenario"), dict) else {}
    explicit = str(row.get("scenario_key") or state_scenario.get("key") or row.get("scenario") or "").strip()
    if explicit and explicit.lower() != "unknown":
        return explicit
    return _infer_training_scenario_key(row)


def _infer_training_scenario_key(row: dict[str, Any]) -> str:
    text_fields = [
        row.get("policy_key"),
        row.get("decision_id"),
        row.get("row_id"),
        row.get("source"),
        row.get("mode"),
        row.get("action_type"),
        row.get("reasoning_context"),
        row.get("causal_context"),
    ]
    action = row.get("action", {}) if isinstance(row.get("action"), dict) else {}
    text_fields.extend([action.get("action"), action.get("target"), action.get("label")])
    learning = row.get("learning", {}) if isinstance(row.get("learning"), dict) else {}
    text_fields.extend([learning.get("policy"), learning.get("take_rate_signal")])
    text = " ".join(str(item or "").lower().replace("-", "_") for item in text_fields)
    scenario_terms = [
        ("food_spike", ("food", "inventory", "pos", "promo", "restock", "kitchen", "mobile_order", "pickup")),
        ("staff_shortage", ("staff", "shift", "fatigue", "overtime", "callout", "break", "coverage")),
        ("storm_response", ("storm", "weather", "lightning", "heat", "shelter", "indoor", "covered")),
        ("proactive_eventops", ("proactive_eventops", "eventops", "event_ops")),
        ("proactive_watchtower", ("watchtower", "proactive_watchtower")),
        ("scan", ("scan", "triage_only", "read_only")),
        ("ride_down", ("ride", "coaster", "queue", "reroute", "route", "capacity", "downtime", "outage", "reopen")),
    ]
    for scenario, terms in scenario_terms:
        if any(term in text for term in terms):
            return scenario
    return "unknown"


def _policy_key(row: dict[str, Any]) -> str:
    learning = row.get("learning", {}) if isinstance(row.get("learning"), dict) else {}
    state_impact = row.get("stateImpact", {}) if isinstance(row.get("stateImpact"), dict) else {}
    after = state_impact.get("after", {}) if isinstance(state_impact.get("after"), dict) else {}
    active_policy = after.get("active_policy") or after.get("activePolicy")
    signal = learning.get("take_rate_signal") or learning.get("policy") or row.get("mode") or active_policy
    return str(signal or "observed_policy").lower().replace(" ", "_")[:90]


def _is_actual_training_source(value: Any) -> bool:
    source = str(value or "").strip().lower()
    return not any(pattern in source for pattern in GENERATED_SOURCE_PATTERNS)


def _reasoning_training_audit_log_path() -> str:
    return os.getenv("PARKPULSE_REASONING_TRAINING_AUDIT_LOG_PATH", "/tmp/parkpulse/reasoning_training_audits.jsonl")


def _causal_reasoning_memory_log_path() -> str:
    return os.getenv("PARKPULSE_CAUSAL_REASONING_MEMORY_LOG_PATH", "/tmp/parkpulse/causal_reasoning_memory.jsonl")


def _heartbeat_training_signal_log_path() -> str:
    return os.getenv("PARKPULSE_HEARTBEAT_TRAINING_SIGNAL_LOG_PATH", "/tmp/parkpulse/heartbeat_training_signals.jsonl")


def _delayed_outcome_attribution_log_path() -> str:
    return os.getenv("PARKPULSE_DELAYED_OUTCOME_ATTRIBUTION_LOG_PATH", "/tmp/parkpulse/delayed_outcome_attributions.jsonl")


def _promoted_slice_policy_snapshot_path() -> str:
    return os.getenv("PARKPULSE_PROMOTED_SLICE_POLICY_PATH", "/tmp/parkpulse/promoted_slice_policy_snapshot.json")


def _slice_rollback_ledger_log_path() -> str:
    return os.getenv("PARKPULSE_SLICE_ROLLBACK_LEDGER_PATH", "/tmp/parkpulse/slice_rollback_ledger.jsonl")


def _recent_jsonl_records(path: str, limit: int = 500) -> list[dict[str, Any]]:
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()[-max(1, min(2000, int(limit or 500))) :]
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for line in reversed(lines):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _read_json_file(path: str) -> dict[str, Any] | None:
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _reasoning_training_audits(limit: int = 500) -> list[dict[str, Any]]:
    audits = []
    for row in _recent_jsonl_records(_reasoning_training_audit_log_path(), limit=limit):
        if row.get("mode") != "grounded_llm_reasoning_feature_audit":
            continue
        if row.get("labels_or_reward_changed") is not False:
            continue
        if row.get("llm_used_for") != "offline_feature_audit_only":
            continue
        if row.get("uses_seed_data") is not False:
            continue
        audits.append(row)
    return audits


def _causal_reasoning_memories(limit: int = 500) -> list[dict[str, Any]]:
    memories = []
    for row in _recent_jsonl_records(_causal_reasoning_memory_log_path(), limit=limit):
        if row.get("mode") != "deterministic_causal_reasoning_memory":
            continue
        if row.get("labels_or_reward_changed") is not False:
            continue
        if row.get("llm_used_for_reward_or_label") is not False:
            continue
        if row.get("uses_seed_data") is not False:
            continue
        memories.append(row)
    return memories


def _reasoning_audit_for_row(row: dict[str, Any], audits: list[dict[str, Any]]) -> dict[str, Any] | None:
    scenario_key = str(row.get("scenario_key") or "unknown")
    policy_key = str(row.get("policy_key") or "")
    for audit in audits:
        action = audit.get("action", {}) if isinstance(audit.get("action"), dict) else {}
        same_scenario = str(audit.get("scenario_key") or "") == scenario_key
        action_tokens = {str(action.get("target") or ""), str(action.get("action") or "")}
        policy_tokens = set(policy_key.replace("/", "_").split("_"))
        if same_scenario and (not policy_tokens or action_tokens & policy_tokens or "live" in policy_tokens):
            return audit
    for audit in audits:
        if str(audit.get("scenario_key") or "") == scenario_key:
            return audit
    return None


def _causal_memory_for_row(row: dict[str, Any], memories: list[dict[str, Any]]) -> dict[str, Any] | None:
    scenario_key = str(row.get("scenario_key") or "unknown")
    policy_key = str(row.get("policy_key") or "")
    for memory in memories:
        action = memory.get("action", {}) if isinstance(memory.get("action"), dict) else {}
        same_scenario = str(memory.get("scenario_key") or "") == scenario_key
        action_tokens = {str(action.get("target") or ""), str(action.get("action") or "")}
        policy_tokens = set(policy_key.replace("/", "_").split("_"))
        if same_scenario and (not policy_tokens or action_tokens & policy_tokens or "live" in policy_tokens):
            return memory
    for memory in memories:
        if str(memory.get("scenario_key") or "") == scenario_key:
            return memory
    return None


def _augment_rows_with_reasoning_features(rows: list[dict[str, Any]], audits: list[dict[str, Any]], causal_memories: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    causal_memories = causal_memories or []
    augmented = []
    for row in rows:
        enriched = dict(row)
        audit = _reasoning_audit_for_row(enriched, audits)
        if audit:
            tags = [str(tag) for tag in audit.get("accepted_feature_tags", []) if tag][:10] if isinstance(audit.get("accepted_feature_tags"), list) else []
            enriched["reasoning_context"] = audit.get("reasoning_context") or enriched.get("scenario_key") or "unknown"
            enriched["reasoning_feature_tags"] = tags
            enriched["reasoning_feature_source"] = "grounded_llm_audit"
            enriched["reasoning_audit_id"] = audit.get("id")
            enriched["reasoning_reward_audit_question_count"] = len(audit.get("reward_metric_audit_questions", []) if isinstance(audit.get("reward_metric_audit_questions"), list) else [])
            enriched["reasoning_feature_backlog_count"] = len(audit.get("feature_backlog", []) if isinstance(audit.get("feature_backlog"), list) else [])
        else:
            enriched["reasoning_context"] = enriched.get("scenario_key") or "unknown"
            enriched["reasoning_feature_tags"] = []
            enriched["reasoning_feature_source"] = "none"
            enriched["reasoning_reward_audit_question_count"] = 0
            enriched["reasoning_feature_backlog_count"] = 0
        causal_memory = _causal_memory_for_row(enriched, causal_memories)
        if causal_memory:
            feature_view = causal_memory.get("training_feature_view", {}) if isinstance(causal_memory.get("training_feature_view"), dict) else {}
            mechanism_ids = causal_memory.get("mechanism_ids", []) if isinstance(causal_memory.get("mechanism_ids"), list) else []
            enriched["causal_context"] = feature_view.get("causal_context") or "|".join([str(causal_memory.get("scenario_key") or "unknown"), *[str(item) for item in mechanism_ids[:5]]])
            enriched["causal_mechanism_ids"] = [str(item) for item in causal_memory.get("mechanism_ids", []) if item][:10] if isinstance(causal_memory.get("mechanism_ids"), list) else []
            enriched["causal_feature_source"] = "deterministic_causal_reasoning_memory"
            enriched["causal_memory_id"] = causal_memory.get("id")
            enriched["audit_quality_score"] = _float(feature_view.get("audit_quality_score"))
            enriched["temporal_window_count"] = int(_float(feature_view.get("temporal_window_count")))
            enriched["counterfactual_reward_delta"] = _float(feature_view.get("reward_delta"))
            enriched["counterfactual_pressure_reduction"] = _float(feature_view.get("pressure_reduction"))
            enriched["failure_depth"] = int(_float(feature_view.get("failure_depth")))
        else:
            enriched["causal_context"] = enriched.get("scenario_key") or "unknown"
            enriched["causal_mechanism_ids"] = []
            enriched["causal_feature_source"] = "none"
            enriched["audit_quality_score"] = 0.0
            enriched["temporal_window_count"] = 0
            enriched["counterfactual_reward_delta"] = 0.0
            enriched["counterfactual_pressure_reduction"] = 0.0
            enriched["failure_depth"] = 0
        enriched["llm_used_for_reward_or_label"] = False
        augmented.append(enriched)
    return augmented


def _reasoning_feature_audit_summary(audits: list[dict[str, Any]], rows: list[dict[str, Any]], export: dict[str, Any]) -> dict[str, Any]:
    matched_rows = [row for row in rows if row.get("reasoning_feature_source") == "grounded_llm_audit"]
    contexts = sorted({str(row.get("reasoning_context")) for row in matched_rows if row.get("reasoning_context")})
    tags: dict[str, int] = {}
    for row in matched_rows:
        for tag in row.get("reasoning_feature_tags", []) if isinstance(row.get("reasoning_feature_tags"), list) else []:
            tags[str(tag)] = tags.get(str(tag), 0) + 1
    return {
        "status": "active" if matched_rows else "waiting_for_grounded_audits",
        "mode": "grounded_llm_reasoning_features_for_offline_training",
        "audit_count": len(audits),
        "matched_training_rows": len(matched_rows),
        "llm_used_for_reward_or_label": False,
        "feature_source": "grounded heartbeat LLM audit logs",
        "accepted_effect": "offline categorical feature context only",
        "excluded_from": ["reward", "training_label", "promotion_gate", "live_action"],
        "top_tags": sorted(tags.items(), key=lambda item: item[1], reverse=True)[:8],
        "contexts": contexts[:12],
        "bigquery_export": export,
    }


def _causal_feature_audit_summary(memories: list[dict[str, Any]], rows: list[dict[str, Any]], export: dict[str, Any]) -> dict[str, Any]:
    matched_rows = [row for row in rows if row.get("causal_feature_source") == "deterministic_causal_reasoning_memory"]
    mechanisms: dict[str, int] = {}
    quality_scores = []
    for row in matched_rows:
        quality_scores.append(_float(row.get("audit_quality_score")))
        for mechanism_id in row.get("causal_mechanism_ids", []) if isinstance(row.get("causal_mechanism_ids"), list) else []:
            mechanisms[str(mechanism_id)] = mechanisms.get(str(mechanism_id), 0) + 1
    return {
        "status": "active" if matched_rows else "waiting_for_causal_memory",
        "mode": "deterministic_causal_memory_features_for_offline_training",
        "memory_count": len(memories),
        "matched_training_rows": len(matched_rows),
        "llm_used_for_reward_or_label": False,
        "labels_or_reward_changed": False,
        "feature_source": "heartbeat action logs plus deterministic outcome error ledger",
        "accepted_effect": "offline categorical causal context only",
        "excluded_from": ["reward", "training_label", "promotion_gate", "live_action"],
        "average_audit_quality_score": round(sum(quality_scores) / max(1, len(quality_scores)), 1) if quality_scores else 0,
        "top_mechanisms": sorted(mechanisms.items(), key=lambda item: item[1], reverse=True)[:8],
        "bigquery_export": export,
    }


def _row_reward(row: dict[str, Any]) -> float:
    response = row.get("responseMetrics", {}) if isinstance(row.get("responseMetrics"), dict) else {}
    scorecard = row.get("scorecard", {}) if isinstance(row.get("scorecard"), dict) else {}
    state_impact = row.get("stateImpact", {}) if isinstance(row.get("stateImpact"), dict) else {}
    response_score = _float(response.get("score") or scorecard.get("response_score"))
    overall = _float(scorecard.get("overall"))
    state_score = _float(scorecard.get("state_movement_score"))
    take_rate = _float(response.get("takeRate")) * 100
    follow_rate = _float(response.get("reactiveFollowThroughRate") or response.get("followThroughRate")) * 100
    density_delta = _float(state_impact.get("density_delta"))
    congestion_delta = _float(state_impact.get("congestion_delta"))
    relief_bonus = max(0.0, -density_delta) * 0.35 + max(0.0, -congestion_delta) * 0.25
    return round(overall * 0.36 + response_score * 0.24 + state_score * 0.18 + take_rate * 0.12 + follow_rate * 0.1 + relief_bonus, 2)


def _memory_training_rows(dashboard: dict[str, Any]) -> list[dict[str, Any]]:
    return _memory_training_rows_from_outcomes(
        dashboard.get("latest_outcomes", []) if isinstance(dashboard.get("latest_outcomes"), list) else []
    )


def _memory_training_rows_from_outcomes(outcomes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in outcomes if isinstance(outcomes, list) else []:
        if not isinstance(row, dict):
            continue
        if not _is_actual_training_source(row.get("source") or row.get("mode") or row.get("agentId")):
            continue
        response = row.get("responseMetrics", {}) if isinstance(row.get("responseMetrics"), dict) else {}
        scorecard = row.get("scorecard", {}) if isinstance(row.get("scorecard"), dict) else {}
        reward = _row_reward(row)
        if reward <= 0:
            continue
        rows.append(
            {
                "row_id": row.get("_id"),
                "decision_id": row.get("decisionId"),
                "source": "mongodb_outcome_events",
                "scenario_key": _scenario_key(row),
                "policy_key": _policy_key(row),
                "reward": reward,
                "overall": _float(scorecard.get("overall")),
                "response_score": _float(response.get("score") or scorecard.get("response_score")),
                "take_rate": _float(response.get("takeRate")),
                "follow_through_rate": _float(response.get("reactiveFollowThroughRate") or response.get("followThroughRate")),
                "created_at": row.get("createdAt"),
            }
        )
    return rows


def _heartbeat_training_signal_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for signal in _recent_jsonl_records(_heartbeat_training_signal_log_path(), limit=500):
        if not isinstance(signal, dict):
            continue
        if signal.get("mode") != "deterministic_outcome_training_signal" or signal.get("eligible_for_training") is not True:
            continue
        if signal.get("uses_seed_data") is not False or signal.get("llm_used") is not False:
            continue
        delayed = signal.get("delayed_attribution", {}) if isinstance(signal.get("delayed_attribution"), dict) else {}
        if delayed.get("status") != "matured":
            continue
        labels = signal.get("labels", {}) if isinstance(signal.get("labels"), dict) else {}
        action = signal.get("action", {}) if isinstance(signal.get("action"), dict) else {}
        reward_delta = _float(labels.get("reward_delta"))
        fitness = _float(labels.get("fitness"))
        pressure_reduction = _float(labels.get("pressure_reduction"))
        if fitness <= 0:
            continue
        reward = round(fitness * 0.72 + max(-25.0, min(25.0, reward_delta)) * 0.18 + max(-25.0, min(25.0, pressure_reduction)) * 0.1, 2)
        rows.append(
            {
                "row_id": signal.get("id") or f"heartbeat_signal_{signal.get('source_action_id')}",
                "decision_id": signal.get("source_action_id"),
                "source": "heartbeat_delayed_outcome_signal",
                "scenario_key": _scenario_key(signal),
                "policy_key": str(action.get("action") or action.get("target") or "heartbeat_policy").lower().replace(" ", "_")[:90],
                "reward": reward,
                "overall": fitness,
                "response_score": fitness,
                "take_rate": max(0.0, min(0.99, 0.45 + reward_delta / 100)),
                "follow_through_rate": max(0.0, min(0.99, 0.5 + pressure_reduction / 100)),
                "created_at": signal.get("created_at"),
                "delayed_attribution_status": delayed.get("status"),
            }
        )
    return rows


def _training_row_from_delayed_attribution(row: dict[str, Any]) -> dict[str, Any] | None:
    if row.get("mode") != "delayed_heartbeat_outcome_attribution" or row.get("status") != "matured":
        return None
    if row.get("uses_seed_data") is not False or row.get("llm_used_for_reward_or_label") is not False:
        return None
    training = row.get("training", {}) if isinstance(row.get("training"), dict) else {}
    if training.get("eligible") is not True:
        return None
    outcome = row.get("outcome", {}) if isinstance(row.get("outcome"), dict) else {}
    scores = outcome.get("scores", {}) if isinstance(outcome.get("scores"), dict) else {}
    pressure = outcome.get("pressure", {}) if isinstance(outcome.get("pressure"), dict) else {}
    action = row.get("action", {}) if isinstance(row.get("action"), dict) else {}
    fitness = _float(scores.get("fitness"))
    reward_delta = _float(scores.get("reward_delta"))
    pressure_reduction = _float(pressure.get("reduction_vs_baseline"))
    if fitness <= 0:
        return None
    reward = round(fitness * 0.72 + max(-25.0, min(25.0, reward_delta)) * 0.18 + max(-25.0, min(25.0, pressure_reduction)) * 0.1, 2)
    return {
        "row_id": row.get("id") or f"delayed_outcome_{row.get('source_action_id')}",
        "decision_id": row.get("source_action_id"),
        "source": "heartbeat_delayed_outcome_attribution",
        "scenario_key": _scenario_key(row),
        "policy_key": str(action.get("action") or action.get("target") or "heartbeat_policy").lower().replace(" ", "_")[:90],
        "reward": reward,
        "overall": fitness,
        "response_score": fitness,
        "take_rate": max(0.0, min(0.99, 0.45 + reward_delta / 100)),
        "follow_through_rate": max(0.0, min(0.99, 0.5 + pressure_reduction / 100)),
        "created_at": row.get("created_at"),
        "delayed_attribution_status": row.get("status"),
    }


def _delayed_outcome_attribution_training_rows() -> list[dict[str, Any]]:
    rows = []
    for row in _recent_jsonl_records(_delayed_outcome_attribution_log_path(), limit=500):
        training_row = _training_row_from_delayed_attribution(row)
        if training_row:
            rows.append(training_row)
    return rows


def _live_feed_case_bank_path() -> Path:
    return Path(
        os.getenv(
            "PARKPULSE_LIVE_FEED_CASE_BANK_PATH",
            str(Path(__file__).resolve().parents[1] / "output" / "qa" / "live-feed-case-bank" / "index.jsonl"),
        )
    )


def _case_bank_issue_scenario(row: dict[str, Any]) -> str:
    issue = row.get("issue", {}) if isinstance(row.get("issue"), dict) else {}
    kind = str(issue.get("kind") or "").lower()
    target = str(issue.get("target_id") or issue.get("targetId") or "").lower()
    text = f"{kind} {target}"
    if any(term in text for term in ("food", "inventory", "mobile_order", "payment")):
        return "food_spike"
    if any(term in text for term in ("staff", "callout", "labor")):
        return "staff_shortage"
    if any(term in text for term in ("storm", "lightning", "heat", "weather")):
        return "storm_response"
    if any(term in text for term in ("ride", "coaster", "queue", "show_dump")):
        return "ride_down"
    if any(term in text for term in ("parade", "parking", "gate", "access_lane")):
        return "proactive_eventops"
    if any(term in text for term in ("sensor", "energy", "water_leak", "radio_dead_zone", "security", "restroom")):
        return "scan"
    return "unknown"


def _case_bank_operational_reward(row: dict[str, Any]) -> float:
    measurement = row.get("measurement", {}) if isinstance(row.get("measurement"), dict) else {}
    layers = measurement.get("reward_layers", {}) if isinstance(measurement.get("reward_layers"), dict) else {}
    reward = layers.get("operational_reward")
    if reward in {None, ""}:
        return 0.0
    return max(0.0, min(1.0, _float(reward)))


def _case_bank_policy_key(row: dict[str, Any]) -> str:
    actions = row.get("actions", {}) if isinstance(row.get("actions"), dict) else {}
    executed = actions.get("executed_count")
    issue = row.get("issue", {}) if isinstance(row.get("issue"), dict) else {}
    kind = str(issue.get("kind") or "live_feed_case").lower()
    if int(_float(executed)) > 0:
        return f"live_feed_controlled_executor_{kind}"[:90]
    return f"live_feed_trace_only_{kind}"[:90]


def _case_bank_executed_tools(row: dict[str, Any]) -> list[str]:
    measurement = row.get("measurement", {}) if isinstance(row.get("measurement"), dict) else {}
    projection = measurement.get("controlled_effect_projection", {}) if isinstance(measurement.get("controlled_effect_projection"), dict) else {}
    tools = projection.get("executed_tools", [])
    return [str(tool) for tool in tools if tool][:12] if isinstance(tools, list) else []


def _live_feed_case_bank_training_rows(limit: int | None = None) -> list[dict[str, Any]]:
    path = _live_feed_case_bank_path()
    if not path.exists():
        return []
    max_rows = int(_float(limit if limit is not None else os.getenv("PARKPULSE_CASE_BANK_TRAINING_ROW_LIMIT"), 500))
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-max_rows:]:
        if not line.strip():
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(case, dict):
            continue
        reward = _case_bank_operational_reward(case)
        if reward <= 0:
            continue
        measurement = case.get("measurement", {}) if isinstance(case.get("measurement"), dict) else {}
        reward_100 = round(reward * 100, 2)
        promotion_eligible = measurement.get("promotion_eligible") is True
        eligible_for_reward = measurement.get("eligible_for_reward") is True
        attribution_confidence = max(0.0, min(1.0, _float(measurement.get("attribution_confidence"), 0.0)))
        rows.append(
            {
                "row_id": f"live_feed_case_bank:{case.get('outcome_id') or case.get('case_id')}",
                "decision_id": case.get("decision_id") or case.get("decisionId"),
                "source": "live_feed_case_bank_reward_vectors",
                "scenario_key": _case_bank_issue_scenario(case),
                "policy_key": _case_bank_policy_key(case),
                "reward": reward_100,
                "overall": reward_100,
                "response_score": reward_100,
                "take_rate": 1.0 if promotion_eligible else max(0.5, round(0.5 + reward / 2, 3)),
                "follow_through_rate": attribution_confidence or (1.0 if eligible_for_reward else 0.5),
                "created_at": case.get("created_at"),
                "normalized_from": "operational_reward_0_1_to_training_0_100",
                "original_operational_reward": reward,
                "case_bank_outcome_id": case.get("outcome_id"),
                "promotion_eligible": promotion_eligible,
                "eligible_for_reward": eligible_for_reward,
                "reward_label": measurement.get("reward_label"),
                "controlled_effect_status": (
                    measurement.get("controlled_effect_projection", {}).get("status")
                    if isinstance(measurement.get("controlled_effect_projection"), dict)
                    else None
                ),
                "executed_tools": _case_bank_executed_tools(case),
                "llm_used_for_reward_or_label": False,
                "labels_or_reward_changed": False,
            }
        )
    return rows


def _dedupe_training_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("row_id") or row.get("decision_id") or hashlib.sha1(json.dumps(row, default=str, sort_keys=True).encode("utf-8")).hexdigest())
        if key not in deduped:
            deduped[key] = row
    return list(deduped.values())


def _bounded_memory_training_rows() -> list[dict[str, Any]]:
    return _dedupe_training_rows(
        _memory_training_rows_from_outcomes(
            get_latest_memory_documents(
                "outcome_events",
                int(_float(os.getenv("PARKPULSE_READINESS_MEMORY_ROW_LIMIT"), 120)),
            )
        )
    )


def _training_row_timestamp(row: dict[str, Any]) -> float:
    raw = str(row.get("created_at") or "").strip()
    if not raw:
        return 0.0
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    except ValueError:
        return 0.0


def _sort_training_rows_latest_first(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (_training_row_timestamp(row), str(row.get("row_id") or row.get("decision_id") or "")),
        reverse=True,
    )


def _training_source(
    heartbeat_rows: list[dict[str, Any]],
    bq_rows: list[dict[str, Any]],
    memory_rows: list[dict[str, Any]],
    case_bank_rows: list[dict[str, Any]] | None = None,
) -> str:
    sources = []
    if bq_rows:
        sources.append("bigquery_outcome_events")
    if memory_rows:
        sources.append("mongodb_outcome_events")
    if heartbeat_rows:
        sources.append("heartbeat_delayed_outcome_signals")
    if case_bank_rows:
        sources.append("live_feed_case_bank_reward_vectors")
    return "+".join(sources) if sources else "none"


def _train_contextual_bandit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_policy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_context: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    by_reasoning_context: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    by_causal_context: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        policy = str(row.get("policy_key") or "observed_policy")
        context = str(row.get("scenario_key") or "unknown")
        reasoning_context = str(row.get("reasoning_context") or context)
        causal_context = str(row.get("causal_context") or context)
        reward = _float(row.get("reward"))
        by_policy[policy].append(row)
        by_context[context][policy].append(reward)
        by_reasoning_context[reasoning_context][policy].append(reward)
        by_causal_context[causal_context][policy].append(reward)

    policies = []
    for policy, policy_rows in by_policy.items():
        rewards = [_float(item.get("reward")) for item in policy_rows]
        policies.append(
            {
                "policy_id": policy,
                "sample_count": len(policy_rows),
                "average_reward": round(sum(rewards) / max(1, len(rewards)), 2),
                "best_reward": round(max(rewards), 2),
                "latest_reward": round(rewards[0], 2),
            }
        )
    policies.sort(key=lambda item: (item["average_reward"], item["sample_count"]), reverse=True)
    context_values = []
    for context, values_by_policy in by_context.items():
        ranked = sorted(
            (
                {
                    "policy_id": policy,
                    "q_value": round(sum(values) / max(1, len(values)), 2),
                    "sample_count": len(values),
                }
                for policy, values in values_by_policy.items()
            ),
            key=lambda item: (item["q_value"], item["sample_count"]),
            reverse=True,
        )
        context_values.append({"context": context, "ranked_policies": ranked})
    context_values.sort(key=lambda item: item["context"])
    reasoning_context_values = []
    for context, values_by_policy in by_reasoning_context.items():
        if context in by_context and not any(row.get("reasoning_feature_source") == "grounded_llm_audit" for policy_rows in by_policy.values() for row in policy_rows if str(row.get("reasoning_context") or "") == context):
            continue
        ranked = sorted(
            (
                {
                    "policy_id": policy,
                    "q_value": round(sum(values) / max(1, len(values)), 2),
                    "sample_count": len(values),
                }
                for policy, values in values_by_policy.items()
            ),
            key=lambda item: (item["q_value"], item["sample_count"]),
            reverse=True,
        )
        reasoning_context_values.append({"context": context, "ranked_policies": ranked})
    reasoning_context_values.sort(key=lambda item: item["context"])
    reasoning_matched_rows = sum(1 for row in rows if row.get("reasoning_feature_source") == "grounded_llm_audit")
    causal_context_values = []
    for context, values_by_policy in by_causal_context.items():
        if not any(row.get("causal_feature_source") == "deterministic_causal_reasoning_memory" for policy_rows in by_policy.values() for row in policy_rows if str(row.get("causal_context") or "") == context):
            continue
        ranked = sorted(
            (
                {
                    "policy_id": policy,
                    "q_value": round(sum(values) / max(1, len(values)), 2),
                    "sample_count": len(values),
                }
                for policy, values in values_by_policy.items()
            ),
            key=lambda item: (item["q_value"], item["sample_count"]),
            reverse=True,
        )
        causal_context_values.append({"context": context, "ranked_policies": ranked})
    causal_context_values.sort(key=lambda item: item["context"])
    causal_matched_rows = sum(1 for row in rows if row.get("causal_feature_source") == "deterministic_causal_reasoning_memory")
    return {
        "type": "actual_contextual_bandit_reward_model",
        "update_rule": "Q(context, policy) = average observed reward from outcome_events; grounded LLM audits and deterministic causal memory may add offline context features but never reward or labels.",
        "best_policy_id": policies[0]["policy_id"] if policies else None,
        "ranked_policies": policies,
        "context_values": context_values,
        "reasoning_context_values": reasoning_context_values,
        "causal_context_values": causal_context_values,
        "reasoning_feature_policy": {
            "enabled": reasoning_matched_rows > 0,
            "matched_rows": reasoning_matched_rows,
            "llm_used_for_reward_or_label": False,
            "source": "grounded_llm_reasoning_feature_audit",
        },
        "causal_feature_policy": {
            "enabled": causal_matched_rows > 0,
            "matched_rows": causal_matched_rows,
            "llm_used_for_reward_or_label": False,
            "source": "deterministic_causal_reasoning_memory",
        },
        "authority": "Ranks candidate policies only; dispatch still requires policy/eval gate and human review when required.",
    }


def _model_version(source: str, model: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    basis = {
        "source": source,
        "sample_count": len(rows),
        "best_policy_id": model.get("best_policy_id"),
        "contexts": [
            {
                "context": item.get("context"),
                "top": (item.get("ranked_policies") or [{}])[0].get("policy_id") if isinstance(item.get("ranked_policies"), list) and item.get("ranked_policies") else None,
                "q": (item.get("ranked_policies") or [{}])[0].get("q_value") if isinstance(item.get("ranked_policies"), list) and item.get("ranked_policies") else None,
            }
            for item in model.get("context_values", []) if isinstance(item, dict)
        ],
        "reasoning_contexts": [
            {
                "context": item.get("context"),
                "top": (item.get("ranked_policies") or [{}])[0].get("policy_id") if isinstance(item.get("ranked_policies"), list) and item.get("ranked_policies") else None,
                "q": (item.get("ranked_policies") or [{}])[0].get("q_value") if isinstance(item.get("ranked_policies"), list) and item.get("ranked_policies") else None,
            }
            for item in model.get("reasoning_context_values", []) if isinstance(item, dict)
        ],
        "causal_contexts": [
            {
                "context": item.get("context"),
                "top": (item.get("ranked_policies") or [{}])[0].get("policy_id") if isinstance(item.get("ranked_policies"), list) and item.get("ranked_policies") else None,
                "q": (item.get("ranked_policies") or [{}])[0].get("q_value") if isinstance(item.get("ranked_policies"), list) and item.get("ranked_policies") else None,
            }
            for item in model.get("causal_context_values", []) if isinstance(item, dict)
        ],
        "reasoning_feature_policy": model.get("reasoning_feature_policy"),
        "causal_feature_policy": model.get("causal_feature_policy"),
        "latest_rows": [row.get("row_id") for row in rows[:20]],
    }
    digest = hashlib.sha1(json.dumps(basis, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]
    return {
        "id": f"parkpulse_policy_{digest}",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": source,
        "sample_count": len(rows),
        "lineage": "observed_outcome_rows_only",
        "uses_generated_data": False,
    }


def _fitness_curve(rows: list[dict[str, Any]], bucket_size: int = 10) -> dict[str, Any]:
    ordered = list(reversed(rows))
    points = []
    rewards = [_float(row.get("reward")) for row in ordered]
    for index in range(0, len(ordered), max(1, bucket_size)):
        bucket = ordered[index : index + bucket_size]
        if not bucket:
            continue
        bucket_rewards = [_float(row.get("reward")) for row in bucket]
        points.append(
            {
                "episode": index + len(bucket),
                "sample_count": len(bucket),
                "average_reward": round(sum(bucket_rewards) / max(1, len(bucket_rewards)), 2),
                "latest_reward": round(bucket_rewards[-1], 2),
                "from": bucket[0].get("created_at"),
                "to": bucket[-1].get("created_at"),
            }
        )
    first = points[0]["average_reward"] if points else None
    last = points[-1]["average_reward"] if points else None
    return {
        "status": "ready" if points else "waiting_for_observed_rows",
        "mode": "observed_reward_curve",
        "point_count": len(points),
        "points": points[-12:],
        "first_average_reward": first,
        "latest_average_reward": last,
        "delta": round((last or 0) - (first or 0), 2) if first is not None and last is not None else None,
        "latest_reward": round(rewards[-1], 2) if rewards else None,
    }


def _scenario_curve(rows: list[dict[str, Any]], bucket_size: int = 5) -> dict[str, Any]:
    ordered = list(reversed(rows))
    points = []
    rewards = [_float(row.get("reward")) for row in ordered]
    for index in range(0, len(ordered), max(1, bucket_size)):
        bucket = ordered[index : index + bucket_size]
        if not bucket:
            continue
        bucket_rewards = [_float(row.get("reward")) for row in bucket]
        points.append(
            {
                "episode": index + len(bucket),
                "sample_count": len(bucket),
                "average_reward": round(sum(bucket_rewards) / max(1, len(bucket_rewards)), 2),
                "latest_reward": round(bucket_rewards[-1], 2),
                "from": bucket[0].get("created_at"),
                "to": bucket[-1].get("created_at"),
            }
        )
    first = points[0]["average_reward"] if points else None
    last = points[-1]["average_reward"] if points else None
    return {
        "point_count": len(points),
        "points": points[-8:],
        "first_average_reward": first,
        "latest_average_reward": last,
        "delta": round((last or 0) - (first or 0), 2) if first is not None and last is not None else None,
        "latest_reward": round(rewards[-1], 2) if rewards else None,
    }


def _scenario_balanced_fitness(rows: list[dict[str, Any]]) -> dict[str, Any]:
    minimum_scenario_rows = int(_float(os.getenv("PARKPULSE_SCENARIO_PROMOTION_MIN_ROWS"), 12))
    by_scenario: dict[str, list[dict[str, Any]]] = defaultdict(list)
    quarantined_unknown_rows: list[dict[str, Any]] = []
    for row in rows:
        scenario = _infer_training_scenario_key(row) if str(row.get("scenario_key") or "").strip().lower() == "unknown" else str(row.get("scenario_key") or "unknown")
        if scenario == "unknown":
            quarantined_unknown_rows.append(row)
            continue
        by_scenario[scenario].append({**row, "scenario_key": scenario})
    scenarios = []
    promotable_count = 0
    hold_count = 0
    collect_more_count = 0
    latest_values = []
    for scenario, scenario_rows in sorted(by_scenario.items()):
        curve = _scenario_curve(scenario_rows)
        latest_average = _float(curve.get("latest_average_reward"))
        delta = _float(curve.get("delta"))
        sample_count = len(scenario_rows)
        if sample_count < minimum_scenario_rows:
            decision = "collect_more_evidence"
            collect_more_count += 1
        elif latest_average >= _float(os.getenv("PARKPULSE_MODEL_PROMOTION_MIN_AVG_REWARD"), 52.0) and delta >= 0:
            decision = "promote_slice"
            promotable_count += 1
        else:
            decision = "hold_slice"
            hold_count += 1
        latest_values.append(latest_average)
        scenarios.append(
            {
                "scenario_key": scenario,
                "sample_count": sample_count,
                "minimum_sample_count": minimum_scenario_rows,
                "latest_average_reward": latest_average,
                "curve_delta": delta,
                "latest_reward": curve.get("latest_reward"),
                "decision": decision,
                "status": "promotable" if decision == "promote_slice" else "needs_more_data" if decision == "collect_more_evidence" else "hold",
                "reason": (
                    f"Need {minimum_scenario_rows} rows; found {sample_count}."
                    if decision == "collect_more_evidence"
                    else "Latest reward is above threshold and the scenario curve is non-regressing."
                    if decision == "promote_slice"
                    else "Scenario slice is below reward threshold or has a regressed curve."
                ),
                "curve": curve,
            }
        )
    balanced_latest_average = round(sum(latest_values) / max(1, len(latest_values)), 2) if latest_values else None
    return {
        "status": "ready" if scenarios else "waiting_for_observed_rows",
        "mode": "scenario_balanced_fitness",
        "minimum_scenario_rows": minimum_scenario_rows,
        "scenario_count": len(scenarios),
        "balanced_latest_average_reward": balanced_latest_average,
        "promotable_slice_count": promotable_count,
        "hold_slice_count": hold_count,
        "collect_more_evidence_count": collect_more_count,
        "scenarios": scenarios,
        "promotable_slices": [item for item in scenarios if item.get("decision") == "promote_slice"],
        "held_slices": [item for item in scenarios if item.get("decision") == "hold_slice"],
        "thin_slices": [item for item in scenarios if item.get("decision") == "collect_more_evidence"],
        "label_quality": {
            "unknown_quarantined_count": len(quarantined_unknown_rows),
            "unknown_quarantined_row_ids": [row.get("row_id") for row in quarantined_unknown_rows[:12]],
            "policy": "Rows with unresolved scenario_key are excluded from scenario-slice promotion math until label repair maps them to a known slice.",
            "known_scenarios": sorted(KNOWN_TRAINING_SCENARIOS),
        },
        "boundary": "Scenario gates use observed outcome rows only. They may promote bounded policy slices but do not let LLM text promote a model; unresolved scenario labels are quarantine-only.",
    }


def _model_promotion_gate(
    rows: list[dict[str, Any]],
    model: dict[str, Any],
    fitness_curve: dict[str, Any],
    scenario_fitness: dict[str, Any],
    source: str,
    bq: dict[str, Any],
) -> dict[str, Any]:
    minimum_rows = int(_float(os.getenv("PARKPULSE_MODEL_PROMOTION_MIN_ROWS"), 50))
    minimum_average_reward = _float(os.getenv("PARKPULSE_MODEL_PROMOTION_MIN_AVG_REWARD"), 52.0)
    minimum_context_samples = int(_float(os.getenv("PARKPULSE_MODEL_PROMOTION_MIN_CONTEXT_SAMPLES"), 8))
    latest_average = _float(fitness_curve.get("latest_average_reward"))
    curve_delta = _float(fitness_curve.get("delta"))
    contexts = model.get("context_values", []) if isinstance(model.get("context_values"), list) else []
    weak_contexts = []
    for context in contexts:
        ranked = context.get("ranked_policies", []) if isinstance(context, dict) and isinstance(context.get("ranked_policies"), list) else []
        top = ranked[0] if ranked else {}
        if int(top.get("sample_count") or 0) < minimum_context_samples:
            weak_contexts.append(context.get("context"))
    blockers = []
    warnings = []
    live_weather_gate = live_weather_training_gate()
    live_ride_ops_gate = live_ride_ops_training_gate()
    live_guest_flow_gate = live_guest_flow_training_gate()
    live_staffing_gate = live_staffing_training_gate()
    live_food_ops_gate = live_food_ops_training_gate()
    live_operator_signal_gate = live_operator_signal_training_gate()
    if live_weather_gate.get("eligible") is False:
        blockers.append(f"Live weather training gate blocked: {live_weather_gate.get('reason')}")
    if live_ride_ops_gate.get("eligible") is False:
        blockers.append(f"Live ride ops training gate blocked: {live_ride_ops_gate.get('reason')}")
    if live_guest_flow_gate.get("eligible") is False:
        blockers.append(f"Live guest flow training gate blocked: {live_guest_flow_gate.get('reason')}")
    for label, gate in (("staffing", live_staffing_gate), ("food ops", live_food_ops_gate), ("operator signal", live_operator_signal_gate)):
        if gate.get("eligible") is False:
            blockers.append(f"Live {label} training gate blocked: {gate.get('reason')}")
    if len(rows) < minimum_rows:
        blockers.append(f"Need {minimum_rows} observed rows before promotion; found {len(rows)}.")
    if latest_average < minimum_average_reward:
        blockers.append(f"Latest average reward {latest_average:.2f} is below promotion threshold {minimum_average_reward:.2f}.")
    if weak_contexts:
        warnings.append(f"Thin context coverage: {', '.join(str(item) for item in weak_contexts[:4])}.")
    if curve_delta < 0:
        warnings.append(f"Reward curve regressed by {curve_delta:.2f}.")
    if "bigquery_outcome_events" not in source:
        warnings.append("BigQuery is not the active training source for this snapshot.")
    if not bq.get("ready"):
        warnings.append("BigQuery path is not ready; promotion can only be local/dev until export path is healthy.")
    promotable_slices = scenario_fitness.get("promotable_slices", []) if isinstance(scenario_fitness.get("promotable_slices"), list) else []
    held_slices = scenario_fitness.get("held_slices", []) if isinstance(scenario_fitness.get("held_slices"), list) else []
    thin_slices = scenario_fitness.get("thin_slices", []) if isinstance(scenario_fitness.get("thin_slices"), list) else []
    label_quality = scenario_fitness.get("label_quality", {}) if isinstance(scenario_fitness.get("label_quality"), dict) else {}
    unknown_quarantined_count = int(_float(label_quality.get("unknown_quarantined_count")))
    if unknown_quarantined_count:
        warnings.append(f"Quarantined {unknown_quarantined_count} unresolved scenario-label rows from slice promotion math.")
    if held_slices:
        warnings.append(
            "Held scenario slices: "
            + ", ".join(f"{item.get('scenario_key')} ({item.get('curve_delta')})" for item in held_slices[:5] if isinstance(item, dict))
            + "."
        )
    if thin_slices:
        warnings.append("Thin scenario slices: " + ", ".join(str(item.get("scenario_key")) for item in thin_slices[:5] if isinstance(item, dict)) + ".")
    if blockers:
        status = "hold"
        decision = "keep_current_snapshot"
    elif curve_delta >= 0 and not held_slices and not thin_slices:
        status = "promotable"
        decision = "promote_challenger_to_heartbeat_snapshot"
    elif promotable_slices:
        status = "slice_promotable"
        decision = "promote_eligible_policy_slices_only"
    else:
        status = "hold"
        decision = "keep_current_snapshot"
    return {
        "status": status,
        "decision": decision,
        "minimum_rows": minimum_rows,
        "minimum_average_reward": minimum_average_reward,
        "minimum_context_samples": minimum_context_samples,
        "observed_rows": len(rows),
        "latest_average_reward": latest_average,
        "curve_delta": curve_delta,
        "scenario_balanced_latest_average_reward": scenario_fitness.get("balanced_latest_average_reward"),
        "slice_summary": {
            "promotable": len(promotable_slices),
            "hold": len(held_slices),
            "collect_more_evidence": len(thin_slices),
        },
        "promotable_slices": [
            {
                "scenario_key": item.get("scenario_key"),
                "sample_count": item.get("sample_count"),
                "latest_average_reward": item.get("latest_average_reward"),
                "curve_delta": item.get("curve_delta"),
                "decision": item.get("decision"),
            }
            for item in promotable_slices[:8]
            if isinstance(item, dict)
        ],
        "held_slices": [
            {
                "scenario_key": item.get("scenario_key"),
                "sample_count": item.get("sample_count"),
                "latest_average_reward": item.get("latest_average_reward"),
                "curve_delta": item.get("curve_delta"),
                "decision": item.get("decision"),
                "reason": item.get("reason"),
            }
            for item in (held_slices + thin_slices)[:8]
            if isinstance(item, dict)
        ],
        "blockers": blockers,
        "warnings": warnings,
        "live_weather_training_gate": live_weather_gate,
        "live_ride_ops_training_gate": live_ride_ops_gate,
        "live_guest_flow_training_gate": live_guest_flow_gate,
        "live_staffing_training_gate": live_staffing_gate,
        "live_food_ops_training_gate": live_food_ops_gate,
        "live_operator_signal_training_gate": live_operator_signal_gate,
        "required_evidence": [
            "observed outcome rows only",
            "positive or flat reward curve",
            "positive or flat scenario-level reward curve for each promoted slice",
            "bounded candidate actions only",
            "policy gate pass rate remains clean",
            "rollback snapshot available",
        ],
    }


def _top_policy_for_scenario(model: dict[str, Any], scenario_key: str) -> dict[str, Any]:
    for context in model.get("context_values", []) if isinstance(model.get("context_values"), list) else []:
        if not isinstance(context, dict) or str(context.get("context") or "") != scenario_key:
            continue
        ranked = context.get("ranked_policies", []) if isinstance(context.get("ranked_policies"), list) else []
        top = ranked[0] if ranked and isinstance(ranked[0], dict) else {}
        if top:
            return {
                "policy_id": top.get("policy_id"),
                "q_value": top.get("q_value"),
                "sample_count": top.get("sample_count"),
                "source": "scenario_context_value",
            }
    return {"policy_id": model.get("best_policy_id"), "q_value": None, "sample_count": 0, "source": "global_default"}


def _promoted_slice_policy_snapshot(
    version: dict[str, Any],
    model: dict[str, Any],
    promotion_gate: dict[str, Any],
    scenario_fitness: dict[str, Any],
    source: str,
    bq: dict[str, Any],
) -> dict[str, Any]:
    previous = _read_json_file(_promoted_slice_policy_snapshot_path()) or {}
    previous_slices = previous.get("slices", {}) if isinstance(previous.get("slices"), dict) else {}
    scenarios = scenario_fitness.get("scenarios", []) if isinstance(scenario_fitness.get("scenarios"), list) else []
    slices: dict[str, Any] = {}
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            continue
        key = str(scenario.get("scenario_key") or "unknown")
        top_policy = _top_policy_for_scenario(model, key)
        previous_slice = previous_slices.get(key, {}) if isinstance(previous_slices.get(key), dict) else {}
        decision = scenario.get("decision")
        if decision == "promote_slice":
            runtime_status = "promoted_challenger"
            active_policy_version = version.get("id")
            active_policy_id = top_policy.get("policy_id")
            rollback_to = {
                "policy_version": previous_slice.get("active_policy_version"),
                "policy_id": previous_slice.get("active_policy_id"),
                "runtime_status": previous_slice.get("runtime_status"),
            }
        elif decision == "collect_more_evidence":
            runtime_status = "observation_only"
            active_policy_version = previous_slice.get("active_policy_version")
            active_policy_id = previous_slice.get("active_policy_id")
            rollback_to = previous_slice.get("rollback_to")
        else:
            runtime_status = "hold_previous_or_review"
            active_policy_version = previous_slice.get("active_policy_version")
            active_policy_id = previous_slice.get("active_policy_id")
            rollback_to = previous_slice.get("rollback_to")
        slices[key] = {
            "scenario_key": key,
            "runtime_status": runtime_status,
            "decision": decision,
            "active_policy_version": active_policy_version,
            "active_policy_id": active_policy_id,
            "candidate_policy_version": version.get("id"),
            "candidate_policy_id": top_policy.get("policy_id"),
            "q_value": top_policy.get("q_value"),
            "sample_count": scenario.get("sample_count"),
            "latest_average_reward": scenario.get("latest_average_reward"),
            "curve_delta": scenario.get("curve_delta"),
            "reason": scenario.get("reason"),
            "rollback_to": rollback_to,
            "rollback_status": "armed" if runtime_status == "promoted_challenger" else "not_promoted",
        }
    digest_basis = {
        "version": version.get("id"),
        "source": source,
        "gate": promotion_gate.get("status"),
        "slices": {
            key: {
                "runtime_status": value.get("runtime_status"),
                "active_policy_version": value.get("active_policy_version"),
                "active_policy_id": value.get("active_policy_id"),
                "curve_delta": value.get("curve_delta"),
            }
            for key, value in sorted(slices.items())
        },
    }
    digest = hashlib.sha1(json.dumps(digest_basis, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]
    return {
        "id": f"promoted_slice_policy_{digest}",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mode": "versioned_promoted_slice_policy_snapshot",
        "status": "ready" if slices else "waiting_for_scenario_fitness",
        "source": source,
        "uses_generated_data": False,
        "llm_used_for_reward_or_label": False,
        "loads_bigquery_per_tick": False,
        "base_policy_version": (previous.get("id") if previous else None),
        "candidate_policy_version": version.get("id"),
        "promotion_gate_status": promotion_gate.get("status"),
        "promotion_decision": promotion_gate.get("decision"),
        "bqml_model_id": _bqml_model_id(bq),
        "slice_summary": promotion_gate.get("slice_summary", {}),
        "slices": slices,
        "rollback_policy": {
            "scope": "per_scenario_slice",
            "trigger": "scenario slice moves from promoted_challenger to hold_previous_or_review or observation_only, or measured curve regresses below zero.",
            "effect": "Only the affected scenario slice is rolled back; other promoted slices remain active.",
        },
        "boundary": "This artifact is built from observed outcome rows and promotion gates only. LLM text cannot promote, roll back, or set reward.",
    }


def _write_promoted_slice_policy_snapshot(artifact: dict[str, Any]) -> dict[str, Any]:
    path = _promoted_slice_policy_snapshot_path()
    previous = _read_json_file(path)
    if previous and previous.get("id") == artifact.get("id"):
        return {"status": "unchanged", "path": path, "artifact_id": artifact.get("id")}
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(artifact, handle, default=str, sort_keys=True, indent=2)
        _write_slice_rollback_events(previous, artifact)
        return {"status": "written", "path": path, "artifact_id": artifact.get("id")}
    except Exception as error:
        return {"status": "error", "path": path, "readiness_issues": [str(error)[:300]]}


def _write_slice_rollback_events(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    if not previous:
        return {"status": "no_previous_snapshot", "written_count": 0}
    previous_slices = previous.get("slices", {}) if isinstance(previous.get("slices"), dict) else {}
    current_slices = current.get("slices", {}) if isinstance(current.get("slices"), dict) else {}
    events = []
    for key, prior in previous_slices.items():
        if not isinstance(prior, dict) or prior.get("runtime_status") != "promoted_challenger":
            continue
        now = current_slices.get(key, {}) if isinstance(current_slices.get(key), dict) else {}
        if now.get("runtime_status") == "promoted_challenger":
            continue
        events.append(
            {
                "id": f"slice_rollback_{key}_{current.get('id')}",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "mode": "per_scenario_slice_rollback_ledger",
                "uses_generated_data": False,
                "llm_used_for_reward_or_label": False,
                "scenario_key": key,
                "from_snapshot_id": previous.get("id"),
                "to_snapshot_id": current.get("id"),
                "previous_policy_version": prior.get("active_policy_version"),
                "previous_policy_id": prior.get("active_policy_id"),
                "new_runtime_status": now.get("runtime_status"),
                "reason": now.get("reason") or "Scenario slice is no longer promotable.",
                "effect": "rollback_this_slice_only",
            }
        )
    if not events:
        return {"status": "unchanged", "written_count": 0}
    path = _slice_rollback_ledger_log_path()
    existing_ids = {str(row.get("id") or "") for row in _recent_jsonl_records(path, limit=1000)}
    new_events = [event for event in events if str(event.get("id") or "") not in existing_ids]
    if not new_events:
        return {"status": "unchanged", "written_count": 0}
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            for event in new_events:
                handle.write(json.dumps(event, default=str, sort_keys=True) + "\n")
        return {"status": "written", "written_count": len(new_events), "path": path}
    except Exception as error:
        return {"status": "error", "written_count": 0, "path": path, "readiness_issues": [str(error)[:300]]}


def promoted_slice_policy_status() -> dict[str, Any]:
    artifact = _read_json_file(_promoted_slice_policy_snapshot_path())
    return {
        "status": "ready" if artifact else "not_available",
        "mode": "versioned_promoted_slice_policy_snapshot",
        "path": _promoted_slice_policy_snapshot_path(),
        "artifact": artifact,
        "rollback_ledger": _slice_rollback_ledger_payload(artifact),
    }


def gcp_training_dry_run_readiness(
    min_rows: int = MIN_ACTUAL_TRAINING_ROWS,
    *,
    validate_tables: bool = False,
    live_feed_preflight: dict[str, Any] | None = None,
    controlled_eval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bq = bigquery_status()
    training = actual_training_status(min_rows=min_rows, run_gcp_training=False, detail="readiness")
    eval_gate = _scoped_bqml_eval_gate(controlled_eval)
    table_validation = _validate_bqml_start_tables(bq, validate_tables=validate_tables)
    gcp_enabled = _env_bool("PARKPULSE_ENABLE_GCP_ML_TRAINING")
    real_bqml_start_enabled = _env_bool("PARKPULSE_ENABLE_REAL_BQML_START")
    feed_preflight = live_feed_preflight if isinstance(live_feed_preflight, dict) else {"status": "not_checked", "mode": "training_live_feed_preflight"}
    bqml_sql = _bqml_training_sql(bq, include_reasoning_features=False, include_causal_features=False) if bq.get("project") and bq.get("dataset") else None
    issues: list[Any] = []
    if not eval_gate.get("allowed"):
        issues.extend(eval_gate.get("readiness_issues", []) if isinstance(eval_gate.get("readiness_issues"), list) else ["Controlled eval gate has not passed."])
    if feed_preflight.get("status") not in {"ready", "no_due_feeds"}:
        issues.extend(feed_preflight.get("readiness_issues", []) if isinstance(feed_preflight.get("readiness_issues"), list) else [f"Live-feed preflight is {feed_preflight.get('status') or 'not ready'}."])
    if training.get("status") != "ready":
        debug = training.get("debug", {}) if isinstance(training.get("debug"), dict) else {}
        issues.extend(debug.get("readiness_issues", []) if isinstance(debug.get("readiness_issues"), list) else ["Training readiness is not ready."])
    if not gcp_enabled:
        issues.append("PARKPULSE_ENABLE_GCP_ML_TRAINING is not enabled.")
    if gcp_enabled and not real_bqml_start_enabled:
        issues.append("PARKPULSE_ENABLE_REAL_BQML_START is not enabled.")
    if not bq.get("ready"):
        issues.extend(bq.get("readiness_issues", []) if isinstance(bq.get("readiness_issues"), list) else ["BigQuery is not ready."])
    if table_validation.get("status") not in {"ready", "not_checked"}:
        issues.extend(table_validation.get("readiness_issues", []) if isinstance(table_validation.get("readiness_issues"), list) else ["BigQuery table validation failed."])
    readiness_issues = _dedupe_text(issues)
    status = "ready" if not readiness_issues else "blocked"
    return {
        "status": status,
        "mode": "gcp_training_dry_run_readiness",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "min_sample_count": min_rows,
        "controlled_eval_gate": {
            "allowed": bool(eval_gate.get("allowed")),
            "status": eval_gate.get("status"),
            "id": (eval_gate.get("eval", {}) if isinstance(eval_gate.get("eval"), dict) else {}).get("id"),
            "decision": (eval_gate.get("eval", {}) if isinstance(eval_gate.get("eval"), dict) else {}).get("decision"),
        },
        "live_feed_preflight": {
            "status": feed_preflight.get("status"),
            "refresh_status": feed_preflight.get("refresh_status"),
            "refreshed_sources": feed_preflight.get("refreshed_sources", []) if isinstance(feed_preflight.get("refreshed_sources"), list) else [],
            "remaining_issues": feed_preflight.get("remaining_issues", []) if isinstance(feed_preflight.get("remaining_issues"), list) else [],
        },
        "actual_training": {
            "status": training.get("status"),
            "detail": training.get("detail"),
            "sample_count": training.get("sample_count"),
            "source": training.get("source"),
            "readiness_issues": (training.get("debug", {}) if isinstance(training.get("debug"), dict) else {}).get("readiness_issues", []),
        },
        "bigquery": {
            "enabled": bq.get("enabled"),
            "ready": bq.get("ready"),
            "project": bq.get("project"),
            "dataset": bq.get("dataset"),
            "location": bq.get("location"),
            "readiness_issues": bq.get("readiness_issues", []) if isinstance(bq.get("readiness_issues"), list) else [],
        },
        "table_validation": table_validation,
        "bqml_start": {
            "would_start": status == "ready",
            "training_enabled": gcp_enabled,
            "real_bqml_start_enabled": real_bqml_start_enabled,
            "model_id": _bqml_model_id(bq),
            "sql": bqml_sql,
            "start_endpoint": "POST /api/park/actual-training?runGcpTraining=true",
        },
        "promotion": {
            "model_promotion_started": False,
            "promotion_allowed_by_dry_run": False,
            "reason": "Dry run validates BQML start conditions only; promotion remains gated by observed fitness and rollback policy.",
        },
        "readiness_issues": readiness_issues,
        "training_rule": "This endpoint is read-only. It validates start conditions and never submits BQML, changes labels/reward, dispatches actions, or promotes models.",
        "uses_seed_data": False,
        "labels_or_reward_changed": False,
        "llm_used_for_reward_or_label": False,
        "gcp_training_started": False,
        "model_promotion_started": False,
    }


def _scoped_bqml_eval_gate(controlled_eval: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(controlled_eval, dict) and controlled_eval:
        if controlled_eval.get("status") in {"passed", "scoped_passed"}:
            return {"allowed": True, "status": controlled_eval.get("status"), "eval": controlled_eval}
        role_results = {
            str(row.get("agent_id")): row
            for row in controlled_eval.get("role_results", [])
            if isinstance(row, dict) and row.get("agent_id")
        } if isinstance(controlled_eval.get("role_results"), list) else {}
        rl_result = role_results.get("rl_action_policy", {})
        critical_issues = [
            str(issue)
            for issue in controlled_eval.get("readiness_issues", [])
            if issue and not any(str(issue).startswith(f"{agent_id} failed eval gate:") for agent_id in ("customer_agent", "scan_agent", "react_agent", "proactive_agent", "ops_chat", "rl_action_policy"))
        ] if isinstance(controlled_eval.get("readiness_issues"), list) else []
        if rl_result.get("passed") is True and not critical_issues:
            scoped = {
                **controlled_eval,
                "status": "scoped_passed",
                "decision": "allow_scoped_offline_training_generation",
                "scope": {"required_agent_ids": ["rl_action_policy"], "source": "request_override"},
                "readiness_issues": [],
            }
            return {"allowed": True, "status": "scoped_passed", "eval": scoped}
        issues = critical_issues or [f"rl_action_policy failed scoped eval gate: score {rl_result.get('score', 0)}/{rl_result.get('min_score', 0)}."]
        return {"allowed": False, "status": "scoped_failed", "eval": controlled_eval, "readiness_issues": issues}
    try:
        from controlled_training_eval import offline_training_eval_gate_passed

        try:
            return offline_training_eval_gate_passed(required_agent_ids=["rl_action_policy"])
        except TypeError:
            return offline_training_eval_gate_passed()
    except Exception as error:
        return {"allowed": False, "status": "error", "readiness_issues": [str(error)[:240]]}


def _slice_rollback_ledger_payload(artifact: dict[str, Any] | None = None, limit: int = 80) -> dict[str, Any]:
    rows = _recent_jsonl_records(_slice_rollback_ledger_log_path(), limit=limit)
    return {
        "status": "ready" if rows else "no_rollbacks",
        "mode": "per_scenario_slice_rollback_ledger",
        "path": _slice_rollback_ledger_log_path(),
        "current_snapshot_id": artifact.get("id") if isinstance(artifact, dict) else None,
        "row_count": len(rows),
        "rows": rows,
        "boundary": "Rollback rows are deterministic artifact transitions from observed promotion gates; LLM text cannot trigger rollback.",
    }


def _offline_training_path(
    bq: dict[str, Any],
    gcp_training: dict[str, Any],
    version: dict[str, Any],
    reasoning_feature_audit: dict[str, Any],
    causal_feature_audit: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": "ready" if bq.get("ready") else "not_ready",
        "cadence": "batch_retrain_from_exported_outcomes",
        "loads_bigquery_per_tick": False,
        "steps": [
            "heartbeat writes action and outcome logs",
            "deterministic causal memory connects action, incident domain, counterfactual alternatives, delayed windows, and failure hierarchy",
            "LLM audit writes grounded feature hints only after measured outcomes exist",
            "episode exporter writes observed rows to BigQuery",
            "BigQuery ML or Vertex trains offline from observed rows plus accepted reasoning and causal context features when available",
            "heartbeat loads a cached promoted policy snapshot",
            "new challenger is promoted only after promotion gate passes",
        ],
        "current_model_id": gcp_training.get("model_id"),
        "latest_policy_version": version.get("id"),
        "reasoning_features": {
            "status": reasoning_feature_audit.get("status"),
            "audit_count": reasoning_feature_audit.get("audit_count"),
            "matched_training_rows": reasoning_feature_audit.get("matched_training_rows"),
            "llm_used_for_reward_or_label": False,
        },
        "causal_features": {
            "status": causal_feature_audit.get("status"),
            "memory_count": causal_feature_audit.get("memory_count"),
            "matched_training_rows": causal_feature_audit.get("matched_training_rows"),
            "llm_used_for_reward_or_label": False,
        },
        "readiness_issues": [] if bq.get("ready") else bq.get("readiness_issues", []),
    }


def _bigquery_training_rows(status: dict[str, Any], limit: int = 200) -> tuple[list[dict[str, Any]], str | None]:
    if not status.get("ready"):
        return [], None
    try:
        from google.cloud import bigquery

        client = bigquery.Client(project=status.get("project"))
        query = f"""
        SELECT
          outcome_id AS row_id,
          decision_id,
          scenario_key,
          COALESCE(NULLIF(source, ''), 'observed_policy') AS policy_key,
          response_score,
          overall_eval_score AS overall,
          take_rate,
          follow_through_rate,
          exported_at AS created_at
        FROM `{status['project']}.{status['dataset']}.outcome_events`
        WHERE (response_score IS NOT NULL OR overall_eval_score IS NOT NULL)
          AND NOT REGEXP_CONTAINS(LOWER(COALESCE(source, '')), r'(seed|synthetic|demo|validation)')
        ORDER BY exported_at DESC
        LIMIT @limit
        """
        job_config = bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("limit", "INT64", limit)])
        timeout = max(0.5, _float(os.getenv("BIGQUERY_QUERY_TIMEOUT_SECONDS"), 2.0))
        try:
            result = client.query(query, job_config=job_config, timeout=timeout).result(timeout=timeout)
        except TypeError:
            result = client.query(query, job_config=job_config).result()
        rows = []
        for row in result:
            item = dict(row)
            reward = round(
                _float(item.get("overall")) * 0.42
                + _float(item.get("response_score")) * 0.28
                + _float(item.get("take_rate")) * 100 * 0.16
                + _float(item.get("follow_through_rate")) * 100 * 0.14,
                2,
            )
            if reward <= 0:
                continue
            rows.append(
                {
                    "row_id": item.get("row_id"),
                    "decision_id": item.get("decision_id"),
                    "source": "bigquery_outcome_events",
                    "scenario_key": _scenario_key(item),
                    "policy_key": str(item.get("policy_key") or "observed_policy").lower().replace(" ", "_")[:90],
                    "reward": reward,
                    "overall": _float(item.get("overall")),
                    "response_score": _float(item.get("response_score")),
                    "take_rate": _float(item.get("take_rate")),
                    "follow_through_rate": _float(item.get("follow_through_rate")),
                    "created_at": str(item.get("created_at")) if item.get("created_at") else None,
                }
            )
        return rows, None
    except Exception as error:  # pragma: no cover - depends on live GCP credentials
        return [], str(error)


def _reasoning_audit_table_id(status: dict[str, Any]) -> str | None:
    project = status.get("project")
    dataset = status.get("dataset")
    if not project or not dataset:
        return None
    return f"{project}.{dataset}.reasoning_training_audits"


def _causal_memory_table_id(status: dict[str, Any]) -> str | None:
    project = status.get("project")
    dataset = status.get("dataset")
    if not project or not dataset:
        return None
    return f"{project}.{dataset}.causal_reasoning_memory"


def _reasoning_audit_export_not_started(status: dict[str, Any], audits: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "not_started",
        "ready": bool(status.get("ready")),
        "audit_count": len(audits),
        "table_id": _reasoning_audit_table_id(status),
        "llm_used_for_reward_or_label": False,
        "readiness_issues": [] if status.get("ready") else status.get("readiness_issues", []),
    }


def _causal_memory_export_not_started(status: dict[str, Any], memories: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "not_started",
        "ready": bool(status.get("ready")),
        "memory_count": len(memories),
        "table_id": _causal_memory_table_id(status),
        "llm_used_for_reward_or_label": False,
        "readiness_issues": [] if status.get("ready") else status.get("readiness_issues", []),
    }


def _export_reasoning_audits_to_bigquery(status: dict[str, Any], audits: list[dict[str, Any]]) -> dict[str, Any]:
    base = _reasoning_audit_export_not_started(status, audits)
    if not audits:
        return {**base, "status": "no_audits"}
    if not status.get("ready"):
        return {**base, "status": "not_ready"}
    table_id = _reasoning_audit_table_id(status)
    if not table_id:
        return {**base, "status": "not_ready", "readiness_issues": ["BigQuery project/dataset missing for reasoning audit export."]}
    try:
        from google.cloud import bigquery

        client = bigquery.Client(project=status.get("project"))
        schema = [
            bigquery.SchemaField("source_action_id", "STRING"),
            bigquery.SchemaField("created_at", "TIMESTAMP"),
            bigquery.SchemaField("scenario_key", "STRING"),
            bigquery.SchemaField("action_target", "STRING"),
            bigquery.SchemaField("action_name", "STRING"),
            bigquery.SchemaField("reasoning_context", "STRING"),
            bigquery.SchemaField("accepted_feature_tags", "STRING", mode="REPEATED"),
            bigquery.SchemaField("rejected_feature_tags", "STRING", mode="REPEATED"),
            bigquery.SchemaField("reward_audit_question_count", "INT64"),
            bigquery.SchemaField("feature_backlog_count", "INT64"),
            bigquery.SchemaField("llm_used_for", "STRING"),
            bigquery.SchemaField("labels_or_reward_changed", "BOOL"),
        ]
        try:
            client.get_table(table_id)
        except Exception:
            client.create_table(bigquery.Table(table_id, schema=schema))
        rows = []
        row_ids = []
        for audit in audits[:500]:
            action = audit.get("action", {}) if isinstance(audit.get("action"), dict) else {}
            rows.append(
                {
                    "source_action_id": str(audit.get("source_action_id") or audit.get("id") or ""),
                    "created_at": audit.get("created_at"),
                    "scenario_key": audit.get("scenario_key"),
                    "action_target": action.get("target"),
                    "action_name": action.get("action"),
                    "reasoning_context": audit.get("reasoning_context"),
                    "accepted_feature_tags": [str(item) for item in audit.get("accepted_feature_tags", []) if item] if isinstance(audit.get("accepted_feature_tags"), list) else [],
                    "rejected_feature_tags": [str(item) for item in audit.get("rejected_feature_tags", []) if item] if isinstance(audit.get("rejected_feature_tags"), list) else [],
                    "reward_audit_question_count": len(audit.get("reward_metric_audit_questions", []) if isinstance(audit.get("reward_metric_audit_questions"), list) else []),
                    "feature_backlog_count": len(audit.get("feature_backlog", []) if isinstance(audit.get("feature_backlog"), list) else []),
                    "llm_used_for": audit.get("llm_used_for"),
                    "labels_or_reward_changed": False,
                }
            )
            row_ids.append(str(audit.get("source_action_id") or audit.get("id") or len(row_ids)))
        errors = client.insert_rows_json(table_id, rows, row_ids=row_ids)
        if errors:
            return {**base, "status": "error", "readiness_issues": [str(errors)[:500]]}
        return {
            **base,
            "status": "exported",
            "exported_count": len(rows),
            "table_id": table_id,
            "readiness_issues": [],
        }
    except Exception as error:
        return {**base, "status": "error", "readiness_issues": [str(error)[:500]]}


def _export_causal_memory_to_bigquery(status: dict[str, Any], memories: list[dict[str, Any]]) -> dict[str, Any]:
    base = _causal_memory_export_not_started(status, memories)
    if not memories:
        return {**base, "status": "no_memory"}
    if not status.get("ready"):
        return {**base, "status": "not_ready"}
    table_id = _causal_memory_table_id(status)
    if not table_id:
        return {**base, "status": "not_ready", "readiness_issues": ["BigQuery project/dataset missing for causal memory export."]}
    try:
        from google.cloud import bigquery

        client = bigquery.Client(project=status.get("project"))
        schema = [
            bigquery.SchemaField("source_action_id", "STRING"),
            bigquery.SchemaField("created_at", "TIMESTAMP"),
            bigquery.SchemaField("scenario_key", "STRING"),
            bigquery.SchemaField("action_target", "STRING"),
            bigquery.SchemaField("action_name", "STRING"),
            bigquery.SchemaField("causal_context", "STRING"),
            bigquery.SchemaField("mechanism_ids", "STRING", mode="REPEATED"),
            bigquery.SchemaField("failure_hierarchy_text", "STRING"),
            bigquery.SchemaField("reward_delta", "FLOAT"),
            bigquery.SchemaField("pressure_reduction", "FLOAT"),
            bigquery.SchemaField("audit_quality_score", "FLOAT"),
            bigquery.SchemaField("temporal_window_count", "INT64"),
            bigquery.SchemaField("labels_or_reward_changed", "BOOL"),
            bigquery.SchemaField("uses_seed_data", "BOOL"),
        ]
        try:
            client.get_table(table_id)
        except Exception:
            client.create_table(bigquery.Table(table_id, schema=schema))
        rows = []
        row_ids = []
        for memory in memories[:500]:
            action = memory.get("action", {}) if isinstance(memory.get("action"), dict) else {}
            feature_view = memory.get("training_feature_view", {}) if isinstance(memory.get("training_feature_view"), dict) else {}
            rows.append(
                {
                    "source_action_id": str(memory.get("source_action_id") or memory.get("id") or ""),
                    "created_at": memory.get("created_at"),
                    "scenario_key": memory.get("scenario_key"),
                    "action_target": action.get("target"),
                    "action_name": action.get("action"),
                    "causal_context": feature_view.get("causal_context"),
                    "mechanism_ids": [str(item) for item in memory.get("mechanism_ids", []) if item] if isinstance(memory.get("mechanism_ids"), list) else [],
                    "failure_hierarchy_text": "|".join(str(item) for item in memory.get("failure_hierarchy", []) if item) if isinstance(memory.get("failure_hierarchy"), list) else "",
                    "reward_delta": _float(feature_view.get("reward_delta")),
                    "pressure_reduction": _float(feature_view.get("pressure_reduction")),
                    "audit_quality_score": _float(feature_view.get("audit_quality_score")),
                    "temporal_window_count": int(_float(feature_view.get("temporal_window_count"))),
                    "labels_or_reward_changed": False,
                    "uses_seed_data": False,
                }
            )
            row_ids.append(str(memory.get("source_action_id") or memory.get("id") or len(row_ids)))
        errors = client.insert_rows_json(table_id, rows, row_ids=row_ids)
        if errors:
            return {**base, "status": "error", "readiness_issues": [str(errors)[:500]]}
        return {
            **base,
            "status": "exported",
            "exported_count": len(rows),
            "table_id": table_id,
            "readiness_issues": [],
        }
    except Exception as error:
        return {**base, "status": "error", "readiness_issues": [str(error)[:500]]}


def _gcp_training_not_started(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "not_started",
        "enabled": False,
        "ready": bool(status.get("ready")),
        "tool": "BigQuery ML",
        "model_id": _bqml_model_id(status),
        "start_condition": "Set PARKPULSE_ENABLE_GCP_ML_TRAINING=true and PARKPULSE_ENABLE_REAL_BQML_START=true with BigQuery credentials to start a real BQML training job.",
        "readiness_issues": [] if status.get("ready") else status.get("readiness_issues", []),
        "sql": _bqml_training_sql(status, include_reasoning_features=False) if status.get("project") and status.get("dataset") else None,
    }


def _bqml_model_id(status: dict[str, Any]) -> str | None:
    project = status.get("project")
    dataset = status.get("dataset")
    if not project or not dataset:
        return None
    return f"{project}.{dataset}.parkpulse_policy_reward_model"


def _bqml_training_sql(status: dict[str, Any], include_reasoning_features: bool = False, include_causal_features: bool = False) -> str:
    model_id = _bqml_model_id(status) or "PROJECT.DATASET.parkpulse_policy_reward_model"
    table_prefix = f"{status.get('project', 'PROJECT')}.{status.get('dataset', 'DATASET')}"
    reasoning_table = _reasoning_audit_table_id(status) or f"{table_prefix}.reasoning_training_audits"
    causal_table = _causal_memory_table_id(status) or f"{table_prefix}.causal_reasoning_memory"
    ctes: list[str] = []
    reasoning_join = ""
    reasoning_columns = """
  o.scenario_key AS reasoning_context,
  0 AS reasoning_audit_count,
  0 AS reward_audit_question_count,
  0 AS feature_backlog_count,"""
    if include_reasoning_features:
        ctes.append(f"""
reasoning AS (
  SELECT
    scenario_key,
    ARRAY_AGG(reasoning_context IGNORE NULLS ORDER BY created_at DESC LIMIT 1)[SAFE_OFFSET(0)] AS reasoning_context,
    COUNT(*) AS reasoning_audit_count,
    MAX(COALESCE(reward_audit_question_count, 0)) AS reward_audit_question_count,
    MAX(COALESCE(feature_backlog_count, 0)) AS feature_backlog_count
  FROM `{reasoning_table}`
  WHERE labels_or_reward_changed IS FALSE
    AND llm_used_for = 'offline_feature_audit_only'
  GROUP BY scenario_key
)
""")
        reasoning_join = "LEFT JOIN reasoning AS r\nUSING (scenario_key)"
        reasoning_columns = """
  COALESCE(r.reasoning_context, o.scenario_key) AS reasoning_context,
  COALESCE(r.reasoning_audit_count, 0) AS reasoning_audit_count,
  COALESCE(r.reward_audit_question_count, 0) AS reward_audit_question_count,
  COALESCE(r.feature_backlog_count, 0) AS feature_backlog_count,"""
    causal_join = ""
    causal_columns = """
  o.scenario_key AS causal_context,
  0 AS causal_memory_count,
  0.0 AS audit_quality_score,
  0 AS temporal_window_count,"""
    if include_causal_features:
        ctes.append(f"""
causal AS (
  SELECT
    scenario_key,
    ARRAY_AGG(causal_context IGNORE NULLS ORDER BY created_at DESC LIMIT 1)[SAFE_OFFSET(0)] AS causal_context,
    ARRAY_AGG(failure_hierarchy_text IGNORE NULLS ORDER BY created_at DESC LIMIT 1)[SAFE_OFFSET(0)] AS failure_hierarchy_text,
    AVG(COALESCE(audit_quality_score, 0)) AS audit_quality_score,
    MAX(COALESCE(temporal_window_count, 0)) AS temporal_window_count,
    COUNT(*) AS causal_memory_count
  FROM `{causal_table}`
  WHERE uses_seed_data IS FALSE
    AND labels_or_reward_changed IS FALSE
  GROUP BY scenario_key
)
""")
        causal_join = "LEFT JOIN causal AS c\nUSING (scenario_key)"
        causal_columns = """
  COALESCE(c.causal_context, o.scenario_key) AS causal_context,
  COALESCE(c.causal_memory_count, 0) AS causal_memory_count,
  COALESCE(c.audit_quality_score, 0.0) AS audit_quality_score,
  COALESCE(c.temporal_window_count, 0) AS temporal_window_count,"""
    cte_sql = f"WITH {', '.join(cte.strip() for cte in ctes)}\n" if ctes else ""
    return f"""
CREATE OR REPLACE MODEL `{model_id}`
OPTIONS(model_type='linear_reg', input_label_cols=['reward'])
AS
{cte_sql}
SELECT
  COALESCE(o.response_score, 0) * 0.35
    + COALESCE(o.overall_eval_score, 0) * 0.35
    + COALESCE(o.take_rate, 0) * 100 * 0.15
    + COALESCE(o.follow_through_rate, 0) * 100 * 0.15 AS reward,
  o.scenario_key,
{reasoning_columns}
{causal_columns}
  COALESCE(d.channel, d.target_system, o.source, 'observed_policy') AS action_channel,
  COALESCE(o.take_rate, 0) AS take_rate,
  COALESCE(o.follow_through_rate, 0) AS follow_through_rate
FROM `{table_prefix}.outcome_events` AS o
LEFT JOIN `{table_prefix}.action_dispatches` AS d
USING (decision_id, outcome_id, scenario_key)
{reasoning_join}
{causal_join}
WHERE (o.response_score IS NOT NULL OR o.overall_eval_score IS NOT NULL)
  AND NOT REGEXP_CONTAINS(LOWER(COALESCE(o.source, '')), r'(seed|synthetic|demo|validation)')
""".strip()


def _validate_bqml_start_tables(status: dict[str, Any], *, validate_tables: bool = False) -> dict[str, Any]:
    required_tables = [
        f"{status.get('project')}.{status.get('dataset')}.outcome_events" if status.get("project") and status.get("dataset") else None,
        f"{status.get('project')}.{status.get('dataset')}.action_dispatches" if status.get("project") and status.get("dataset") else None,
    ]
    required_tables = [table for table in required_tables if table]
    if not validate_tables:
        return {
            "status": "not_checked",
            "required_tables": required_tables,
            "readiness_issues": [],
            "reason": "Set validateTables=true to verify BigQuery table existence before starting BQML.",
        }
    if not status.get("ready"):
        return {
            "status": "not_ready",
            "required_tables": required_tables,
            "checked_tables": [],
            "readiness_issues": status.get("readiness_issues", []) if isinstance(status.get("readiness_issues"), list) else ["BigQuery is not ready."],
        }
    if not _env_bool("PARKPULSE_ENABLE_LIVE_BQ_TABLE_VALIDATION"):
        return {
            "status": "requires_live_validation",
            "required_tables": required_tables,
            "checked_tables": [],
            "readiness_issues": [
                "Live BigQuery table validation is disabled. Set PARKPULSE_ENABLE_LIVE_BQ_TABLE_VALIDATION=true in the controlled GCP runtime to verify required tables."
            ],
            "safety": "No live BigQuery table calls were made.",
        }
    try:
        from google.cloud import bigquery

        client = bigquery.Client(project=status.get("project"))
        timeout = max(1.0, _float(os.getenv("PARKPULSE_BQ_TABLE_VALIDATION_TIMEOUT_SECONDS"), 8.0))
        checked = []
        missing = []
        for table_id in required_tables:
            try:
                client.get_table(table_id, timeout=timeout)
                checked.append(table_id)
            except Exception:
                missing.append(table_id)
        return {
            "status": "ready" if not missing else "missing_tables",
            "required_tables": required_tables,
            "checked_tables": checked,
            "missing_tables": missing,
            "readiness_issues": [f"Missing required BigQuery table: {table}" for table in missing],
        }
    except Exception as error:
        return {
            "status": "error",
            "required_tables": required_tables,
            "checked_tables": [],
            "readiness_issues": [str(error)[:300]],
        }


def _run_bigquery_ml_training(status: dict[str, Any], enabled: bool, include_reasoning_features: bool = False, include_causal_features: bool = False) -> dict[str, Any]:
    base = _gcp_training_not_started(status)
    base["enabled"] = enabled
    if not enabled:
        return base
    if not status.get("ready"):
        return {
            **base,
            "status": "not_ready",
            "readiness_issues": status.get("readiness_issues", []),
        }
    if not _env_bool("PARKPULSE_ENABLE_REAL_BQML_START"):
        return {
            **base,
            "status": "blocked_by_real_bqml_start_guard",
            "enabled": True,
            "ready": True,
            "start_condition": "Set PARKPULSE_ENABLE_REAL_BQML_START=true in the controlled GCP runtime to submit BQML training.",
            "readiness_issues": ["PARKPULSE_ENABLE_REAL_BQML_START is not enabled."],
        }
    model_id = _bqml_model_id(status)
    now = time.time()
    recent_window_seconds = _float(os.getenv("PARKPULSE_BQML_RETRAIN_COOLDOWN_SECONDS"), 900)
    if (
        _LAST_BQML_TRAINING.get("model_id") == model_id
        and now - float(_LAST_BQML_TRAINING.get("started_at", 0) or 0) < recent_window_seconds
    ):
        return {
            "status": "recently_started",
            "enabled": True,
            "ready": True,
            "tool": "BigQuery ML",
            "model_id": model_id,
            "job_id": _LAST_BQML_TRAINING.get("job_id"),
            "start_condition": f"Retrain cooldown active for {round(recent_window_seconds)}s to avoid duplicate dashboard-triggered jobs.",
            "uses_reasoning_features": include_reasoning_features,
            "uses_causal_features": include_causal_features,
            "sql": _bqml_training_sql(status, include_reasoning_features=include_reasoning_features, include_causal_features=include_causal_features),
            "readiness_issues": [],
        }
    try:
        from google.cloud import bigquery

        client = bigquery.Client(project=status.get("project"))
        sql = _bqml_training_sql(status, include_reasoning_features=include_reasoning_features, include_causal_features=include_causal_features)
        timeout = max(1.0, _float(os.getenv("PARKPULSE_BQML_START_TIMEOUT_SECONDS"), 10.0))
        job = client.query(sql, timeout=timeout)
        _LAST_BQML_TRAINING.update({"model_id": model_id, "job_id": getattr(job, "job_id", None), "started_at": now})
        return {
            "status": "started",
            "enabled": True,
            "ready": True,
            "tool": "BigQuery ML",
            "model_id": model_id,
            "job_id": getattr(job, "job_id", None),
            "uses_reasoning_features": include_reasoning_features,
            "uses_causal_features": include_causal_features,
            "sql": sql,
            "readiness_issues": [],
        }
    except Exception as error:  # pragma: no cover - depends on live GCP credentials
        return {
            **base,
            "status": "error",
            "readiness_issues": [str(error)[:300]],
        }
