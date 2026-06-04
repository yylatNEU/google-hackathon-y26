import os

import pytest


@pytest.mark.skipif(
    os.getenv("PARKPULSE_RUN_LIVE_GCP_TESTS", "").strip().lower() not in {"1", "true", "yes", "on"},
    reason="Set PARKPULSE_RUN_LIVE_GCP_TESTS=true to run live GCP judge trace/eval smoke checks.",
)
def test_live_gcp_judge_trace_eval_smoke():
    import asyncio

    from gcp_live_readiness import run_gcp_judge_trace_eval_smoke
    from parkpulse_api import ParkAgentRunRequest, park_agent_run

    async def run_scenario(scenario_key: str, execute: bool):
        return await park_agent_run(ParkAgentRunRequest(scenario_key=scenario_key, execute=execute))

    result = asyncio.run(
        run_gcp_judge_trace_eval_smoke(
            scenario_key=os.getenv("PARKPULSE_LIVE_GCP_TEST_SCENARIO", "ride_down"),
            execute=False,
            scenario_runner=run_scenario,
        )
    )

    strict_gate = result["strict_gate"]
    if strict_gate["required"]:
        assert strict_gate["passed"], strict_gate["failures"]
    assert result["status"] == "complete"
    assert result["readiness"]["judge_agent"]["agent_id"] == "gcp_eval_judge_agent"
    assert result["smoke"]["eval_present"] is True
    assert result["smoke"]["proof"]["local_scorecard"]["proof_mode"] == "live"
    assert result["artifact"]["status"] == "written"

    allowed_modes = {"live", "mocked", "skipped"}
    readiness = result["readiness"]
    checks = readiness["checks"]
    required_live_checks = readiness["summary"]["required_live_checks"]
    assert {"cloud_trace_export", "vertex_eval_trigger", "bigquery"} <= set(required_live_checks)
    assert all(check["proof_mode"] in allowed_modes for check in checks.values())
    assert readiness["status"] in {"live_ready", "wired_not_live"}
    assert readiness["summary"]["required_live_ready"] is all(
        checks[name]["proof_mode"] == "live" for name in required_live_checks
    )
    assert (readiness["status"] == "live_ready") is readiness["summary"]["required_live_ready"]

    proof = result["smoke"]["proof"]
    assert {"local_scorecard", "trace_artifact", "hosted_vertex_eval", "analytics_export"} <= set(proof)
    assert all(proof[item]["proof_mode"] in allowed_modes for item in proof)
