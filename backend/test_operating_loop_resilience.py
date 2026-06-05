from operating_loop_resilience import build_operating_loop_resilience_report
import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "monitor_operating_loop_resilience.py"
SCRIPT_SPEC = importlib.util.spec_from_file_location("monitor_operating_loop_resilience", SCRIPT_PATH)
monitor_operating_loop_resilience = importlib.util.module_from_spec(SCRIPT_SPEC)
assert SCRIPT_SPEC and SCRIPT_SPEC.loader
SCRIPT_SPEC.loader.exec_module(monitor_operating_loop_resilience)


def _healthy_inputs():
    return {
        "reliability_report": {
            "agent": {"permissions": {"dispatch": False, "memory_write": False}},
            "critical_findings": [],
            "failure_mode_matrix": [{"mode": f"mode_{index}"} for index in range(12)],
            "scenario_coverage_evaluation": {"dynamic_state_chain": ["ride_outage", "crowd_redistribution", "staffing_pressure", "food_demand_spike", "guest_sentiment_shift", "safety_risk"]},
        },
        "gcp_live_readiness": {
            "summary": {"required_live_checks": ["cloud_trace_export", "vertex_eval_trigger", "bigquery"]},
            "checks": {
                "cloud_trace_export": {"proof_mode": "live"},
                "vertex_eval_trigger": {"proof_mode": "live"},
                "bigquery": {"proof_mode": "live"},
                "firestore": {"proof_mode": "mocked"},
            },
        },
        "live_feed_health": {"summary": {"required_feed_count": 6, "ready_feed_count": 6, "missing_or_weak_feed_count": 0}},
        "review_ledger": {
            "training_rule": "Review decisions become supervised evidence; reward remains measured from post-action outcomes.",
            "rows": [{"llm_used_for_reward_or_label": False, "labels_or_reward_changed": False}],
        },
        "controlled_eval": {
            "status": "passed",
            "labels_or_reward_changed": False,
            "llm_used_for_reward_or_label": False,
            "gcp_training_started": False,
            "model_promotion_started": False,
        },
        "training_readiness": {
            "status": "ready",
            "boundaries": ["RL reward rows require measured outcomes.", "Promotion requires rollback gates."],
        },
    }


def test_operating_loop_resilience_passes_healthy_contract():
    report = build_operating_loop_resilience_report(inputs=_healthy_inputs(), write_artifact=False)

    assert report["status"] == "passed"
    assert report["decision"] == "allow_loop_claim"
    assert report["summary"]["critical_failed_count"] == 0


def test_operating_loop_resilience_blocks_unsafe_training_mutation():
    inputs = _healthy_inputs()
    inputs["controlled_eval"]["labels_or_reward_changed"] = True

    report = build_operating_loop_resilience_report(inputs=inputs, write_artifact=False)

    assert report["status"] == "failed"
    assert "controlled_eval_gate_is_safe" in report["summary"]["critical_failures"]


def test_operating_loop_resilience_blocks_missing_strict_gcp_contract():
    inputs = _healthy_inputs()
    inputs["gcp_live_readiness"]["summary"]["required_live_checks"] = ["bigquery"]

    report = build_operating_loop_resilience_report(inputs=inputs, write_artifact=False)

    assert report["status"] == "failed"
    assert "strict_gcp_gate_available" in report["summary"]["critical_failures"]


def test_operating_loop_monitor_writes_timestamped_and_latest_artifacts(tmp_path):
    report = build_operating_loop_resilience_report(inputs=_healthy_inputs(), write_artifact=False)

    artifact = monitor_operating_loop_resilience._write_monitor_artifacts(report, artifact_dir=tmp_path)

    run_path = Path(artifact["run_path"])
    latest_path = Path(artifact["latest_path"])
    assert run_path.exists()
    assert latest_path.exists()
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    assert latest["report"]["decision"] == "allow_loop_claim"
    assert latest["monitor_id"].startswith("operating-loop-resilience-")


def test_controlled_training_eval_latest_reads_durable_copy(tmp_path, monkeypatch):
    import controlled_training_eval

    monkeypatch.setenv("PARKPULSE_CONTROLLED_TRAINING_ARTIFACT_DIR", str(tmp_path))
    durable_reports = []
    monkeypatch.setattr(
        controlled_training_eval,
        "_write_durable_eval",
        lambda report: durable_reports.append(controlled_training_eval._durable_eval_document(report)) or {"status": "stored", "mode": "unit_durable"},
    )
    monkeypatch.setattr(controlled_training_eval, "_latest_durable_eval", lambda: durable_reports[-1] if durable_reports else None)
    report = {
        "id": "controlled_training_eval_unit_durable",
        "created_at": "2026-06-04T19:00:00+00:00",
        "status": "failed",
        "mode": "controlled_eval_training_gate",
        "pack_id": "pack-unit",
        "readiness_issues": ["react_agent failed eval gate: score 79/80."],
        "labels_or_reward_changed": False,
        "llm_used_for_reward_or_label": False,
        "gcp_training_started": False,
        "model_promotion_started": False,
    }

    artifact = controlled_training_eval._write_eval_artifact(report)
    latest = controlled_training_eval.latest_controlled_training_eval()

    assert artifact["status"] == "written"
    assert artifact["durable"]["status"] in {"stored", "skipped"}
    assert latest["id"] == "controlled_training_eval_unit_durable"
    assert latest["artifacts"]["durable_storage"] in {"mongodb", "local_artifact"}
