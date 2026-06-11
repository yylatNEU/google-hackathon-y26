from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("MONGODB_DISABLE_DRIVER_IMPORT", "1")
os.environ.setdefault("ENABLE_BIGQUERY_ANALYTICS", "false")
os.environ.setdefault("PARKPULSE_ENABLE_OTEL_SPANS", "false")
os.environ.setdefault("PARKPULSE_MONGO_MODEL_EMBEDDINGS", "false")
os.environ.setdefault("PARKPULSE_COPILOT_SEMANTIC_MEMORY", "false")

import main


def _reset_full_runtime_state(monkeypatch):
    monkeypatch.setattr(main, "_parkpulse_app", None)
    monkeypatch.setattr(main, "_parkpulse_module", None)
    monkeypatch.setattr(main, "_load_error", None)
    monkeypatch.setattr(main, "_load_task", None)
    monkeypatch.setattr(main, "_load_started_at", None)
    monkeypatch.setattr(main, "_load_completed_at", None)
    monkeypatch.setattr(main, "_load_duration_ms", None)
    main._load_profile_events.clear()
    main._hot_endpoint_cache.clear()
    main._hot_endpoint_refreshing.clear()
    main._refinement_receipts.clear()
    main._run_receipts.clear()
    main._run_receipt_order.clear()


async def _call_lazy_app(path: str, method: str = "GET"):
    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await main.app(
        {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": b"",
            "headers": [],
        },
        receive,
        send,
    )
    status = next(message["status"] for message in messages if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    import json

    return status, json.loads(body.decode("utf-8"))


def test_full_runtime_load_timeout_does_not_cancel_background(monkeypatch):
    _reset_full_runtime_state(monkeypatch)
    module = SimpleNamespace(app=object())

    def fake_load_full_module():
        time.sleep(0.05)
        return module

    monkeypatch.setattr(main, "_load_full_module", fake_load_full_module)

    async def exercise():
        with pytest.raises(asyncio.TimeoutError):
            await main._get_full_module(timeout=0.001)

        assert main._full_runtime_status()["status"] in {"loading", "loaded"}
        return await main._get_full_module(timeout=1)

    loaded = asyncio.run(exercise())

    assert loaded is module
    status = main._full_runtime_status()
    assert status["status"] == "loaded"
    assert status["loaded"] is True
    assert isinstance(status["load_duration_ms"], int)
    assert [event["phase"] for event in status["import_profile"]][-2:] == ["app_resolved", "load_finished"]


def test_agent_monitoring_summary_does_not_load_full_runtime(monkeypatch):
    _reset_full_runtime_state(monkeypatch)
    called = []

    async def fail_if_loaded(*args, **kwargs):
        called.append((args, kwargs))
        raise AssertionError("summary monitoring must stay on the lazy fast path")

    async def fake_fast_monitoring():
        return {
            "entrypoint": "lazy-main",
            "mode": "stale_while_revalidate_fast_monitoring",
            "overall_status": "clear",
        }

    monkeypatch.setattr(main, "_get_full_module", fail_if_loaded)
    monkeypatch.setattr(main, "_fast_agent_monitoring", fake_fast_monitoring)

    status, payload = asyncio.run(_call_lazy_app("/api/park/agent-monitoring"))

    assert status == 200
    assert payload["entrypoint"] == "lazy-main"
    assert payload["mode"] == "stale_while_revalidate_fast_monitoring"
    assert "policy_index" not in payload
    assert called == []


def test_agent_monitoring_deep_uses_explicit_full_runtime(monkeypatch):
    _reset_full_runtime_state(monkeypatch)
    called = []

    class FakeModule:
        async def build_park_agent_monitoring_response(self):
            return {"overall_status": "clear", "policy_index": {"gate": "clear"}}

    async def fake_get_full_module(*args, **kwargs):
        called.append((args, kwargs))
        return FakeModule()

    monkeypatch.setattr(main, "_get_full_module", fake_get_full_module)

    status, payload = asyncio.run(_call_lazy_app("/api/park/agent-monitoring/deep"))

    assert status == 200
    assert payload["entrypoint"] == "full-runtime"
    assert payload["mode"] == "deep_monitoring"
    assert payload["policy_index"] == {"gate": "clear"}
    assert called


def test_agent_monitoring_deep_failure_returns_renderable_fallback(monkeypatch):
    _reset_full_runtime_state(monkeypatch)

    async def fail_deep_monitoring():
        raise TimeoutError("deep monitor timed out")

    async def fake_fast_monitoring():
        return {
            "entrypoint": "lazy-main",
            "mode": "stale_while_revalidate_fast_monitoring",
            "overall_status": "review",
        }

    monkeypatch.setattr(main, "_deep_agent_monitoring", fail_deep_monitoring)
    monkeypatch.setattr(main, "_fast_agent_monitoring", fake_fast_monitoring)

    status, payload = asyncio.run(_call_lazy_app("/api/park/agent-monitoring/deep"))

    assert status == 200
    assert payload["entrypoint"] == "lazy-main"
    assert payload["status"] == "deep_monitoring_unavailable"
    assert payload["deep_monitoring"]["status"] == "unavailable"
    assert "deep monitor timed out" in payload["deep_monitoring"]["error"]


def test_live_agents_smoke_latest_stays_on_lazy_fast_path(monkeypatch, tmp_path):
    _reset_full_runtime_state(monkeypatch)
    report_path = tmp_path / "live-all-agents-smoke.json"
    report_path.write_text(
        '{"summary":{"status":"passed","activated_role_count":10,"activated_department_count":11}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("PARKPULSE_LIVE_AGENTS_SMOKE_REPORT", str(report_path))

    async def fail_if_loaded(*args, **kwargs):
        raise AssertionError("live-agents smoke report should not load full runtime")

    monkeypatch.setattr(main, "_get_full_module", fail_if_loaded)

    status, payload = asyncio.run(_call_lazy_app("/api/park/live-agents-smoke/latest"))

    assert status == 200
    assert payload["summary"]["status"] == "passed"
    assert payload["summary"]["activated_department_count"] == 11


def test_lazy_main_import_budget():
    backend_dir = Path(__file__).resolve().parent
    env = {**os.environ, "PYTHONPATH": str(backend_dir)}
    script = "import time; s=time.perf_counter(); import main; print(time.perf_counter()-s)"
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(backend_dir.parent),
        env=env,
        text=True,
        capture_output=True,
        timeout=12,
        check=True,
    )
    elapsed = float(result.stdout.strip().splitlines()[-1])
    assert elapsed < 10.0


def test_agent_run_fallback_receipt_is_upgraded_by_background_refinement(monkeypatch):
    _reset_full_runtime_state(monkeypatch)

    class FakeModule:
        app = object()

        class ParkAgentRunRequest:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        async def park_agent_run(self, request):
            return {
                "status": "complete",
                "scenario_key": request.kwargs["scenario_key"],
                "operator_response": {"headline": "Full refined action", "summary": "Refined.", "next_step": "Done."},
                "run_telemetry": {
                    "scenario_key": request.kwargs["scenario_key"],
                    "planner": {"runtime": "full_runtime", "selected_action": {"label": "Full refined action"}},
                    "delivery": {"summary": {"total": 0}, "dispatches": [], "response": {}},
                    "governance": {"allowed": True, "gate_status": "clear", "findings": []},
                    "analytics": {"status": "test"},
                    "memory": {"retrieved_learnings": []},
                },
            }

    module = FakeModule()

    def fake_load_full_module():
        time.sleep(0.03)
        return module

    monkeypatch.setattr(main, "_load_full_module", fake_load_full_module)
    monkeypatch.setenv("PARKPULSE_AGENT_RUN_FULL_LOAD_TIMEOUT_SECONDS", "0.001")
    monkeypatch.setenv("PARKPULSE_AGENT_RUN_REFINEMENT_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("PARKPULSE_MAX_BACKGROUND_REFINEMENTS", "1")

    payload = asyncio.run(
        main._build_agent_run_payload_with_runtime(
            {
                "scenario_key": "food_spike",
                "operator_message": "Food Court A is down; redirect mobile orders.",
                "execute": False,
            },
            "test",
        )
    )
    receipt_id = payload["run_receipt"]["id"]

    assert payload["status"] == "bounded_fallback"
    assert payload["run_receipt"]["upgrade_status"] == "pending"

    deadline = time.time() + 2
    stored = None
    while time.time() < deadline:
        stored = main._run_receipts.get(receipt_id)
        if stored and stored["receipt"].get("upgrade_status") == "upgraded":
            break
        time.sleep(0.02)

    assert stored is not None
    assert stored["receipt"]["upgrade_status"] == "upgraded"
    assert stored["payload"]["operator_response"]["headline"] == "Full refined action"
    assert stored["payload"]["runtime_proof"]["receipt_upgrade_status"] == "upgraded"
