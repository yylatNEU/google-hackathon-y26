import asyncio
import os

os.environ.setdefault("MONGODB_DISABLE_DRIVER_IMPORT", "1")

from agent_role_skills import list_agent_role_skills, route_agent_role
from prod_reliability_qa_agent import run_production_reliability_qa

import main


def test_production_reliability_qa_contract_is_read_only():
    report = run_production_reliability_qa("pre-deploy reliability qa")

    assert report["role"] == "qa"
    assert report["agent"]["permissions"]["dispatch"] is False
    assert report["go_no_go_recommendation"]["decision"] == "GO WITH CONDITIONS"
    assert {item["mode"] for item in report["failure_mode_matrix"]} >= {
        "unavailable_llm",
        "policy_validation_failure",
        "dispatch_failure",
        "stream_interruption",
    }


def test_role_registry_routes_production_reliability_qa():
    registry = list_agent_role_skills()
    roles = {role["mode"]: role for role in registry["roles"]}

    assert "qa" in roles
    assert roles["qa"]["permissions"]["dispatch"] is False
    assert ".agents/skills/parkpulse-production-reliability-qa-agent/SKILL.md" in registry["proof"]["skill_paths"]
    assert route_agent_role("production reliability QA go/no-go", "auto")["selected_role"] == "qa"
    assert route_agent_role("anything", "qa")["selected_role"] == "qa"


def test_agent_role_run_invokes_qa_without_dispatch():
    payload = asyncio.run(main._agent_role_run_payload("pre-deploy failure mode matrix", "qa"))

    assert payload["selected_role"] == "qa"
    assert payload["role_run"]["dispatch_allowed"] is False
    assert payload["run_telemetry"]["delivery"]["summary"]["total"] == 0
    assert payload["role_receipt"]["read_only"] is True
    assert payload["digital_twin_tools"]["summary"]["selected_role"] == "qa"
