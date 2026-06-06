from __future__ import annotations

import json

import park_actual_training as training


def _row(row_id: str, scenario: str, reward: float, policy: str = "reroute") -> dict:
    return {
        "row_id": row_id,
        "decision_id": f"decision-{row_id}",
        "source": "unit_actual",
        "scenario_key": scenario,
        "policy_key": policy,
        "reward": reward,
        "overall": reward,
        "response_score": reward - 2,
        "take_rate": 0.5,
        "follow_through_rate": 0.6,
        "created_at": f"2026-06-04T12:0{min(int(reward) % 9, 9)}:00Z",
    }


def _gate(eligible=True, reason="ready"):
    return {"eligible": eligible, "reason": reason}


def test_actual_training_full_status_uses_isolated_rows_and_gates(monkeypatch, tmp_path):
    monkeypatch.setenv("PARKPULSE_ENABLE_GCP_ML_TRAINING", "1")
    monkeypatch.setenv("PARKPULSE_MODEL_PROMOTION_MIN_ROWS", "2")
    monkeypatch.setenv("PARKPULSE_PROMOTED_SLICE_POLICY_PATH", str(tmp_path / "slice.json"))
    monkeypatch.setenv("PARKPULSE_SLICE_ROLLBACK_LEDGER_PATH", str(tmp_path / "rollback.jsonl"))
    bq = {"ready": True, "dataset": "parkpulse"}
    rows = [
        _row("heartbeat", "ride_down", 88, "ride_reroute"),
        _row("bq", "food_spike", 82, "food_restock"),
        _row("memory", "storm_response", 76, "storm_shelter"),
        _row("case", "staff_shortage", 72, "staff_coverage"),
    ]
    audit = {
        "id": "audit-1",
        "mode": "grounded_llm_reasoning_feature_audit",
        "scenario_key": "ride_down",
        "action": {"target": "ride", "action": "reroute"},
        "accepted_feature_tags": ["queue", "clearance"],
        "reward_metric_audit_questions": ["q1"],
        "feature_backlog": ["b1"],
        "labels_or_reward_changed": False,
        "llm_used_for": "offline_feature_audit_only",
        "uses_seed_data": False,
    }
    causal = {
        "id": "causal-1",
        "mode": "deterministic_causal_reasoning_memory",
        "scenario_key": "ride_down",
        "action": {"target": "ride", "action": "reroute"},
        "mechanism_ids": ["queue_pressure"],
        "training_feature_view": {
            "causal_context": "ride_down|queue_pressure",
            "audit_quality_score": 91,
            "temporal_window_count": 2,
            "reward_delta": 6,
            "pressure_reduction": 4,
            "failure_depth": 1,
        },
        "labels_or_reward_changed": False,
        "llm_used_for_reward_or_label": False,
        "uses_seed_data": False,
    }

    monkeypatch.setattr(training, "get_operational_memory_dashboard", lambda query: {"status": {"mode": "unit"}, "query": query})
    monkeypatch.setattr(training, "_heartbeat_training_signal_rows", lambda: [rows[0]])
    monkeypatch.setattr(training, "_delayed_outcome_attribution_training_rows", lambda: [])
    monkeypatch.setattr(training, "_bigquery_training_rows", lambda status, limit=None: ([rows[1]], None))
    monkeypatch.setattr(training, "_bounded_memory_training_rows", lambda: [rows[2]])
    monkeypatch.setattr(training, "_live_feed_case_bank_training_rows", lambda: [rows[3]])
    monkeypatch.setattr(training, "_reasoning_training_audits", lambda: [audit])
    monkeypatch.setattr(training, "_causal_reasoning_memories", lambda: [causal])
    monkeypatch.setattr(training, "bigquery_status", lambda: bq)
    monkeypatch.setattr(training, "online_improvement_status", lambda: {"ready": True})
    monkeypatch.setattr(training, "_export_reasoning_audits_to_bigquery", lambda status, audits: {"status": "exported", "count": len(audits)})
    monkeypatch.setattr(training, "_export_causal_memory_to_bigquery", lambda status, memories: {"status": "exported", "count": len(memories)})
    monkeypatch.setattr(training, "_run_bigquery_ml_training", lambda status, requested, **kwargs: {"status": "started", "kwargs": kwargs})
    monkeypatch.setattr(training, "_write_promoted_slice_policy_snapshot", lambda payload: {"status": "written", "path": "unit"})
    monkeypatch.setattr(training, "_slice_rollback_ledger_payload", lambda payload: {"status": "ready", "policy_version": payload.get("model_version")})
    monkeypatch.setattr(training, "live_weather_training_gate", lambda: _gate(False, "weather stale"))
    monkeypatch.setattr(training, "live_ride_ops_training_gate", lambda: _gate())
    monkeypatch.setattr(training, "live_guest_flow_training_gate", lambda: _gate())
    monkeypatch.setattr(training, "live_staffing_training_gate", lambda: _gate())
    monkeypatch.setattr(training, "live_food_ops_training_gate", lambda: _gate())
    monkeypatch.setattr(training, "live_operator_signal_training_gate", lambda: _gate())

    result = training.actual_training_status(min_rows=3, run_gcp_training=True)

    assert result["status"] == "ready"
    assert result["source"] == "bigquery_outcome_events+mongodb_outcome_events+heartbeat_delayed_outcome_signals+live_feed_case_bank_reward_vectors"
    assert result["gcp_ml"]["bigquery_ml_training"]["status"] == "started"
    assert result["model_ops"]["reasoning_feature_audit"]["status"] == "active"
    assert result["model_ops"]["causal_feature_audit"]["status"] == "active"
    assert any("Live weather training gate blocked" in issue for issue in result["debug"]["readiness_issues"])


def test_actual_training_readiness_status_bounded_with_bq_error(monkeypatch):
    monkeypatch.setenv("PARKPULSE_READINESS_LOAD_BQ_ROWS", "true")
    monkeypatch.setenv("PARKPULSE_READINESS_BQ_ROW_LIMIT", "2")
    monkeypatch.delenv("PARKPULSE_ENABLE_GCP_ML_TRAINING", raising=False)
    monkeypatch.setattr(training, "bigquery_status", lambda: {"ready": False, "readiness_issues": ["missing table"]})
    monkeypatch.setattr(training, "_heartbeat_training_signal_rows", lambda: [])
    monkeypatch.setattr(training, "_delayed_outcome_attribution_training_rows", lambda: [])
    monkeypatch.setattr(training, "_bounded_memory_training_rows", lambda: [])
    monkeypatch.setattr(training, "_live_feed_case_bank_training_rows", lambda: [])
    monkeypatch.setattr(training, "_bigquery_training_rows", lambda status, limit=None: ([], "query failed"))
    monkeypatch.setattr(training, "live_weather_training_gate", lambda: _gate())
    monkeypatch.setattr(training, "live_ride_ops_training_gate", lambda: _gate(False, "ride feed stale"))
    monkeypatch.setattr(training, "live_guest_flow_training_gate", lambda: _gate())
    monkeypatch.setattr(training, "live_staffing_training_gate", lambda: _gate())
    monkeypatch.setattr(training, "live_food_ops_training_gate", lambda: _gate())
    monkeypatch.setattr(training, "live_operator_signal_training_gate", lambda: _gate())

    result = training.actual_training_status(min_rows=1, run_gcp_training=True, detail="fast")

    assert result["detail"] == "readiness"
    assert result["status"] == "not_ready"
    assert result["debug"]["bigquery_rows_error"] == "query failed"
    assert "PARKPULSE_ENABLE_GCP_ML_TRAINING is not enabled." in result["debug"]["readiness_issues"]
    assert any("Live ride ops training gate blocked" in issue for issue in result["debug"]["readiness_issues"])


def test_actual_training_low_level_row_and_audit_helpers(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_REASONING_TRAINING_AUDIT_LOG_PATH", str(tmp_path / "audits.jsonl"))
    monkeypatch.setenv("PARKPULSE_CAUSAL_REASONING_MEMORY_LOG_PATH", str(tmp_path / "causal.jsonl"))

    assert training._env_bool("MISSING_BOOL", True) is True
    assert training._float("bad", 4.5) == 4.5
    assert training._dedupe_text([" a ", "", "a", "b"]) == ["a", "b"]
    assert training._scenario_key({"stateScenario": {"key": "unknown"}, "action": {"target": "food"}}) == "food_spike"
    assert training._policy_key({"stateImpact": {"after": {"activePolicy": "Active Policy"}}}) == "active_policy"
    assert training._is_actual_training_source("synthetic fixture") is False

    (tmp_path / "records.jsonl").write_text('{"ok": 1}\nnot-json\n[1]\n{"ok": 2}\n', encoding="utf-8")
    assert [row["ok"] for row in training._recent_jsonl_records(str(tmp_path / "records.jsonl"))] == [2, 1]
    assert training._read_json_file(str(tmp_path / "missing.json")) is None
    (tmp_path / "bad.json").write_text("[1]", encoding="utf-8")
    assert training._read_json_file(str(tmp_path / "bad.json")) is None
    (tmp_path / "good.json").write_text('{"ready": true}', encoding="utf-8")
    assert training._read_json_file(str(tmp_path / "good.json"))["ready"] is True

    audit = {
        "mode": "grounded_llm_reasoning_feature_audit",
        "labels_or_reward_changed": False,
        "llm_used_for": "offline_feature_audit_only",
        "uses_seed_data": False,
        "scenario_key": "food_spike",
        "action": {"target": "food", "action": "restock"},
        "accepted_feature_tags": ["food"],
    }
    causal = {
        "mode": "deterministic_causal_reasoning_memory",
        "labels_or_reward_changed": False,
        "llm_used_for_reward_or_label": False,
        "uses_seed_data": False,
        "scenario_key": "food_spike",
        "action": {"target": "food", "action": "restock"},
        "mechanism_ids": ["stockout"],
        "training_feature_view": {"audit_quality_score": 80, "reward_delta": 4},
    }
    (tmp_path / "audits.jsonl").write_text(json.dumps(audit) + "\n" + json.dumps({**audit, "uses_seed_data": True}) + "\n", encoding="utf-8")
    (tmp_path / "causal.jsonl").write_text(json.dumps(causal) + "\n" + json.dumps({**causal, "labels_or_reward_changed": True}) + "\n", encoding="utf-8")
    audits = training._reasoning_training_audits()
    memories = training._causal_reasoning_memories()
    rows = training._augment_rows_with_reasoning_features([_row("food", "food_spike", 80, "food_restock")], audits, memories)

    assert len(audits) == 1
    assert len(memories) == 1
    assert rows[0]["reasoning_feature_source"] == "grounded_llm_audit"
    assert rows[0]["causal_feature_source"] == "deterministic_causal_reasoning_memory"
    assert rows[0]["llm_used_for_reward_or_label"] is False

    trace_row = {
        **_row("risk", "ride_down", 91, "live_feed_risk_lift_approve_ride_failure"),
        "reasoning_context": "ride_down|risk_lift_success",
        "reasoning_feature_tags": ["risk_lift_success", "risk_lift_executed"],
        "reasoning_feature_source": "live_feed_case_bank_llm_trace",
    }
    trace_rows = training._augment_rows_with_reasoning_features([trace_row], [], [])
    model = training._train_contextual_bandit(trace_rows)

    assert trace_rows[0]["reasoning_feature_source"] == "live_feed_case_bank_llm_trace"
    assert trace_rows[0]["reasoning_context"] == "ride_down|risk_lift_success"
    assert model["reasoning_feature_policy"]["enabled"] is True
    assert model["reasoning_feature_policy"]["matched_rows"] == 1
    assert model["reasoning_context_values"][0]["context"] == "ride_down|risk_lift_success"
