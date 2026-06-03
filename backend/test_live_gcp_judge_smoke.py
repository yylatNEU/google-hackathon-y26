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

    assert result["status"] == "complete"
    assert result["readiness"]["judge_agent"]["agent_id"] == "gcp_eval_judge_agent"
    assert result["smoke"]["eval_present"] is True
    assert result["smoke"]["proof"]["local_scorecard"]["proof_mode"] == "live"
