import sys
from types import SimpleNamespace

import latency_diagnostics
from latency_diagnostics import build_latency_diagnostics, latency_history_payload


def test_latency_diagnostics_flags_stale_full_runtime_load():
    payload = build_latency_diagnostics(
        full_runtime={
            "status": "stale_loading",
            "load_elapsed_ms": 91000,
            "timeout_tiers": {
                "agent_run_full_load_seconds": 1.5,
                "full_runtime_stale_load_seconds": 90,
            },
        },
        receipts={},
        latest_sweep={},
    )

    assert payload["status"] == "attention"
    assert payload["summary"]["top_cause"]["id"] == "full_runtime_import"
    assert payload["summary"]["top_cause"]["severity"] == "critical"
    assert payload["gate"]["status"] == "blocked"


def test_latency_diagnostics_uses_workflow_and_vertex_timings():
    payload = build_latency_diagnostics(
        full_runtime={"status": "loaded", "timeout_tiers": {}},
        receipts={
            "receipt-1": {
                "payload": {
                    "run_receipt": {"id": "receipt-1"},
                    "run_telemetry": {
                        "agent_workflow": {
                            "stages": [
                                {"stage": "sense.memory_retrieval", "mode": "targeted", "stage_ms": 2400, "elapsed_ms": 2600}
                            ]
                        }
                    },
                }
            }
        },
        latest_sweep={
            "scenarios": [
                {
                    "scenario_key": "ride_down",
                    "elapsed_ms": 12000,
                    "vertex": {"status": "completed", "transport": "rest"},
                }
            ]
        },
    )

    cause_ids = {cause["id"] for cause in payload["causes"]}
    assert "agent_workflow_stage" in cause_ids
    assert "vertex_evaluator" in cause_ids
    assert payload["timings"]["slowest_workflow_stages"][0]["stage"] == "sense.memory_retrieval"
    assert payload["timings"]["vertex_sweep_scenarios"][0]["scenario_key"] == "ride_down"


def test_latency_probe_snapshot_returns_cached_background_result(monkeypatch):
    monkeypatch.setattr(latency_diagnostics, "_PROBES", {"fake": lambda: {"status": "ok", "mode": "unit"}})
    latency_diagnostics._PROBE_CACHE.clear()
    latency_diagnostics._PROBE_FUTURES.clear()
    latency_diagnostics._PROBE_FAILURES.clear()
    latency_diagnostics._PROBE_CIRCUIT_OPENED_AT.clear()

    trigger = latency_diagnostics.trigger_latency_probes(force=True, probe_names=["fake"])
    assert trigger["started"] == ["fake"]
    future = latency_diagnostics._PROBE_FUTURES["fake"]
    future.result(timeout=2)

    snapshot = latency_diagnostics.latency_probe_snapshot()
    assert snapshot["probes"]["fake"]["status"] == "ok"
    assert snapshot["probes"]["fake"]["mode"] == "unit"
    assert snapshot["probes"]["fake"]["fresh"] is True


def test_latency_diagnostics_failure_env_and_clear_paths(monkeypatch):
    assert latency_diagnostics._number(None, 4) == 4
    assert latency_diagnostics._number("bad", 5) == 5
    assert latency_diagnostics._receipt_payloads(None) == []
    assert latency_diagnostics._workflow_slow_points([{"run_telemetry": {"agent_workflow": {"stages": ["bad"]}}}]) == []
    assert latency_diagnostics._latest_sweep_slow_points({"scenarios": ["bad", {"elapsed_ms": 0}]}) == []

    monkeypatch.delenv("ENABLE_VERTEX_GENAI_EVAL", raising=False)
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("MONGODB_DIRECT_URI", raising=False)
    monkeypatch.delenv("PARKPULSE_LIVE_BIGQUERY", raising=False)
    monkeypatch.delenv("PARKPULSE_COLLABORATION_LIVE_BIGQUERY", raising=False)
    payload = build_latency_diagnostics(
        full_runtime={"status": "failed", "load_error": "import exploded", "timeout_tiers": {}},
        include_env=True,
    )
    assert payload["status"] == "attention"
    assert payload["summary"]["top_cause"]["status"] == "failed"
    assert payload["env_flags"]["mongo_configured"] is False

    monkeypatch.setenv("ENABLE_VERTEX_GENAI_EVAL", "true")
    monkeypatch.setenv("MONGODB_URI", "mongodb://unit")
    monkeypatch.setenv("PARKPULSE_LIVE_BIGQUERY", "yes")
    env_payload = build_latency_diagnostics(full_runtime={"status": "loaded", "timeout_tiers": {}}, include_env=True)
    cause_ids = {cause["id"] for cause in env_payload["causes"]}
    assert {"vertex_evaluator", "mongo_initialization", "bigquery_export"} <= cause_ids
    assert env_payload["env_flags"] == {
        "vertex_eval_enabled": True,
        "live_bigquery_enabled": True,
        "mongo_configured": True,
    }

    monkeypatch.delenv("ENABLE_VERTEX_GENAI_EVAL", raising=False)
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("MONGODB_DIRECT_URI", raising=False)
    monkeypatch.delenv("PARKPULSE_LIVE_BIGQUERY", raising=False)
    monkeypatch.delenv("PARKPULSE_COLLABORATION_LIVE_BIGQUERY", raising=False)
    clear = build_latency_diagnostics(full_runtime={"status": "loaded", "timeout_tiers": {}})
    assert clear["status"] == "ok"
    assert clear["summary"]["top_cause"]["id"] == "no_slow_cause_observed"
    assert clear["gate"]["status"] == "passed"


def test_latency_history_payload_summarizes_persisted_samples():
    history = latency_history_payload(
        [
            {
                "_id": "latency_diag_1",
                "documentType": "latency_diagnostics",
                "createdAt": "2026-01-01T00:00:00Z",
                "status": "attention",
                "summary": {
                    "full_runtime_status": "loading",
                    "top_cause": {"id": "full_runtime_import", "label": "Full runtime import/load", "severity": "warning"},
                },
                "timings": {
                    "dependency_probes": {
                        "mongo": {"status": "ok", "duration_ms": 45},
                        "vertex": {"status": "ok", "duration_ms": 120},
                    }
                },
            },
            {"_id": "eval_1", "documentType": "eval_result"},
        ]
    )

    assert history["sample_count"] == 1
    assert history["summary"]["recurring_top_cause_id"] == "full_runtime_import"
    assert history["summary"]["max_probe_name"] == "vertex"
    assert history["rows"][0]["probe_durations_ms"]["vertex"] == 120


def test_latency_persist_is_scheduled_in_background():
    saved = []

    def persist(payload):
        saved.append(payload)
        return "latency_diag_unit"

    result = latency_diagnostics.schedule_latency_diagnostics_persist({"status": "ok"}, persist)
    assert result["status"] in {"queued", "skipped"}
    if result["status"] == "queued":
        latency_diagnostics._PERSIST_FUTURE.result(timeout=2)
        assert saved == [{"status": "ok"}]


def test_latency_gate_strict_blocks_warnings_and_import_profile_parser():
    parsed = latency_diagnostics._parse_importtime(
        "\n".join(
            [
                "import time:       100 |        200 | json",
                "import time:      3000 |       5000 | slow.module",
            ]
        )
    )
    assert parsed["module_count"] == 2
    assert parsed["top_cumulative"][0]["module"] == "slow.module"

    diagnostics = build_latency_diagnostics(
        full_runtime={"status": "loaded", "timeout_tiers": {}},
        probe_snapshot={"probes": {"mongo": {"status": "degraded", "duration_ms": 25}}},
    )
    assert diagnostics["gate"]["status"] == "passed"
    strict_gate = latency_diagnostics.latency_acceptance_gate(diagnostics, fail_on_warning=True)
    assert strict_gate["status"] == "blocked"
    assert any(item.startswith("probe:mongo:degraded") for item in strict_gate["warnings"])


def test_latency_probe_import_and_persist_edge_cases(monkeypatch):
    latency_diagnostics._PROBE_CACHE.clear()
    latency_diagnostics._PROBE_FUTURES.clear()
    latency_diagnostics._PROBE_FAILURES.clear()
    latency_diagnostics._PROBE_CIRCUIT_OPENED_AT.clear()

    failed = latency_diagnostics._run_probe("broken", lambda: (_ for _ in ()).throw(RuntimeError("probe failed")))
    assert failed["status"] == "failed"
    assert latency_diagnostics._probe_circuit_state("broken") == "closed"

    failed_again = latency_diagnostics._run_probe("broken", lambda: (_ for _ in ()).throw(RuntimeError("probe failed again")))
    assert failed_again["status"] == "failed"
    assert latency_diagnostics._probe_circuit_state("broken") == "open"
    assert latency_diagnostics.trigger_latency_probes(probe_names=["broken", "unknown"])["skipped"]["broken"] == "unknown_probe"

    monkeypatch.setattr(latency_diagnostics, "_PROBES", {"broken": lambda: {"status": "ok"}})
    assert latency_diagnostics.trigger_latency_probes(probe_names=["missing"])["skipped"]["missing"] == "unknown_probe"
    assert latency_diagnostics.trigger_latency_probes(probe_names=["broken"])["skipped"]["broken"] == "circuit_open"

    latency_diagnostics._PROBE_CIRCUIT_OPENED_AT["broken"] = 0
    half_open = latency_diagnostics.trigger_latency_probes(force=True, probe_names=["broken"])
    assert half_open["started"] == ["broken"]
    latency_diagnostics._PROBE_FUTURES["broken"].result(timeout=2)
    assert latency_diagnostics.latency_probe_snapshot()["probes"]["broken"]["status"] == "ok"

    class TimeoutRun:
        stderr = "import time: 1 | 2 | slow"

    def timeout_run(*_args, **_kwargs):
        import subprocess

        raise subprocess.TimeoutExpired("python", 1, stderr=TimeoutRun.stderr)

    monkeypatch.setattr(latency_diagnostics.subprocess, "run", timeout_run)
    timed_out = latency_diagnostics._run_import_profile("slow_module")
    assert timed_out["status"] == "timeout"

    monkeypatch.setattr(latency_diagnostics.subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("spawn failed")))
    assert latency_diagnostics._run_import_profile("bad_module")["status"] == "failed"

    monkeypatch.setattr(latency_diagnostics, "_IMPORT_PROFILE_FUTURE", None)
    monkeypatch.setattr(latency_diagnostics, "_IMPORT_PROFILE_CACHE", {"status": "ok", "finished_epoch": latency_diagnostics.time.time()})
    assert latency_diagnostics.trigger_import_profile(force=False)["skipped"] == "fresh"

    latency_diagnostics._PERSIST_FUTURE = None
    result = latency_diagnostics.schedule_latency_diagnostics_persist(
        {"status": "attention"},
        lambda _payload: (_ for _ in ()).throw(RuntimeError("persist failed")),
    )
    assert result["status"] == "queued"
    assert latency_diagnostics._PERSIST_FUTURE.result(timeout=2)["status"] == "failed"

    latency_diagnostics._PERSIST_FUTURE = type("RunningFuture", (), {"done": lambda self: False})()
    skipped = latency_diagnostics.schedule_latency_diagnostics_persist({"status": "ok"}, lambda payload: "unused")
    assert skipped["reason"] == "persist_in_flight"
    latency_diagnostics._PERSIST_FUTURE = None


def test_latency_dependency_probe_branches(monkeypatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("MONGODB_DIRECT_URI", raising=False)
    assert latency_diagnostics._probe_mongo()["status"] == "disabled"
    monkeypatch.setenv("MONGODB_URI", "mongodb://unit")
    monkeypatch.setitem(
        sys.modules,
        "mongo_memory",
        SimpleNamespace(init_operational_memory=lambda: {"connected": False, "mode": "fallback", "errors": ["down", "slow", "extra"]}),
    )
    mongo = latency_diagnostics._probe_mongo()
    assert mongo["status"] == "degraded"
    assert mongo["errors"] == ["down", "slow"]

    monkeypatch.delenv("PARKPULSE_LIVE_BIGQUERY", raising=False)
    monkeypatch.delenv("PARKPULSE_COLLABORATION_LIVE_BIGQUERY", raising=False)
    assert latency_diagnostics._probe_bigquery()["status"] == "disabled"
    monkeypatch.setenv("PARKPULSE_COLLABORATION_LIVE_BIGQUERY", "true")
    monkeypatch.setitem(
        sys.modules,
        "bigquery_analytics",
        SimpleNamespace(bigquery_status=lambda: {"ready": True, "mode": "unit", "dataset": "dataset", "readiness_issues": ["a", "b", "c", "d"]}),
    )
    bigquery = latency_diagnostics._probe_bigquery()
    assert bigquery["status"] == "ok"
    assert bigquery["readiness_issues"] == ["a", "b", "c"]

    monkeypatch.delenv("ENABLE_VERTEX_GENAI_EVAL", raising=False)
    assert latency_diagnostics._probe_vertex()["status"] == "disabled"
    monkeypatch.setenv("ENABLE_VERTEX_GENAI_EVAL", "true")
    monkeypatch.delenv("PARKPULSE_LATENCY_PROBE_VERTEX_LIVE", raising=False)
    monkeypatch.setitem(
        sys.modules,
        "evaluator_loop",
        SimpleNamespace(
            evaluator_loop_status=lambda: {"status": "configured", "provider": "vertex", "hosted_configured": True, "hosted_trigger_enabled": False, "readiness_issues": ["ok"]},
            run_vertex_hosted_evaluation=lambda payload: {"status": "completed", "transport": "rest", "provider": "vertex"},
        ),
    )
    vertex_status = latency_diagnostics._probe_vertex()
    assert vertex_status["mode"] == "status_probe"
    monkeypatch.setenv("PARKPULSE_LATENCY_PROBE_VERTEX_LIVE", "true")
    vertex_live = latency_diagnostics._probe_vertex()
    assert vertex_live["status"] == "ok"
    assert vertex_live["mode"] == "live_evaluate_instances_probe"


def test_latency_probe_skip_snapshot_and_gate_edges(monkeypatch):
    latency_diagnostics._PROBE_CACHE.clear()
    latency_diagnostics._PROBE_FUTURES.clear()
    latency_diagnostics._PROBE_FAILURES.clear()
    latency_diagnostics._PROBE_CIRCUIT_OPENED_AT.clear()
    monkeypatch.setattr(latency_diagnostics, "_PROBES", {"cached": lambda: {"status": "ok"}})
    latency_diagnostics._PROBE_CACHE["cached"] = {"probe": "cached", "status": "ok", "finished_epoch": latency_diagnostics.time.time()}
    assert latency_diagnostics.trigger_latency_probes(probe_names=["cached"])["skipped"]["cached"] == "fresh"

    class RunningFuture:
        def done(self):
            return False

    latency_diagnostics._PROBE_CACHE.clear()
    latency_diagnostics._PROBE_FUTURES["cached"] = RunningFuture()
    assert latency_diagnostics.trigger_latency_probes(force=True, probe_names=["cached"])["skipped"]["cached"] == "already_running"
    snapshot = latency_diagnostics.latency_probe_snapshot()
    assert snapshot["probes"]["cached"]["status"] == "running"

    monkeypatch.setattr(latency_diagnostics, "_IMPORT_PROFILE_FUTURE", RunningFuture())
    monkeypatch.setattr(latency_diagnostics, "_IMPORT_PROFILE_CACHE", {"status": "running", "started_epoch": latency_diagnostics.time.time()})
    assert latency_diagnostics.import_profile_snapshot()["status"] == "running"
    monkeypatch.setattr(latency_diagnostics, "_IMPORT_PROFILE_FUTURE", None)

    diagnostics = {
        "causes": [{"id": "critical_cause", "severity": "critical"}, {"id": "warn_cause", "severity": "warning"}],
        "timings": {
            "full_runtime": {"status": "failed"},
            "slowest_workflow_stages": [{"stage": "slow", "stage_ms": 5000}],
            "vertex_sweep_scenarios": [{"scenario_key": "ride_down", "elapsed_ms": 20000}],
            "dependency_probes": {"mongo": {"status": "failed", "duration_ms": 9000}, "vertex": {"status": "running", "duration_ms": 6000}},
            "import_profile_detail": {"status": "timeout", "duration_ms": 40000},
        },
        "thresholds": {"slow_stage_warning_ms": 2000, "vertex_sweep_warning_ms": 10000},
    }
    gate = latency_diagnostics.latency_acceptance_gate(diagnostics, fail_on_warning=True)
    assert gate["status"] == "blocked"
    assert "critical:critical_cause" in gate["blockers"]
    assert "full_runtime:failed" in gate["blockers"]
    assert any(item.startswith("probe:mongo:failed") for item in gate["blockers"])
    assert any(item.startswith("stage:slow") for item in gate["warnings"])
