from __future__ import annotations

from scripts.live_feed_issue_coverage_matrix import _coverage_row


def _proposal(agent: str, department: str, tool: str, *, status: str, policy: str, disposition: str, issue_specific: bool = True) -> dict:
    return {
        "agent_id": agent,
        "department": department,
        "issue_specific": issue_specific,
        "requested_tool": tool,
        "proposal_envelope": {
            "requested_tool": tool,
            "executor_status": status,
        },
        "policy_judge": {"status": policy},
        "action_disposition": {"decision": disposition},
        "recommendation": f"{department} {tool}",
    }


def _result(proposals: list[dict], receipts: list[dict]) -> dict:
    return {
        "summary": {
            "status": "passed",
            "issue": {"kind": "demand_spike", "target_id": "mainStreet", "intensity": 82},
            "issue_action_alignment": {
                "status": "aligned_executed",
                "template_risk": "low",
                "expected_tools": ["create_ops_alert", "draft_guest_message"],
                "executed_tools": ["create_ops_alert"],
                "held_tools": ["draft_guest_message"],
                "executed_match": True,
                "held_match": True,
            },
            "actions": {"executed_count": 1, "held_count": 1, "unresolved_without_owner_count": 0},
            "agents": {"negotiation_round_count": 3},
            "memory": {"applied_count": 1, "outcome_id": "outcome_test"},
            "artifacts": {"run_json": "run.json"},
        },
        "payload": {
            "role_agent_proposals": {"proposals": proposals},
            "tool_executor_live_test": {"receipts": receipts},
        },
    }


def test_coverage_row_requires_issue_specific_execution_receipt() -> None:
    proposals = [
        _proposal("ride_ops_agent", "operations", "create_ops_alert", status="ready_for_executor", policy="passed", disposition="execute_controlled_internal"),
        _proposal("guest_flow_agent", "guest_experience", "draft_guest_message", status="awaiting_compliance", policy="requires_compliance", disposition="hold_message_for_compliance"),
    ]
    receipts = [
        {"agent": "other_ops_agent", "department": "operations", "source_tool": "create_ops_alert", "result": {"status": "executed_controlled"}},
        {"agent": "guest_flow_agent", "department": "guest_experience", "source_tool": "draft_guest_message", "result": {"status": "held"}},
    ]

    row = _coverage_row(_result(proposals, receipts))

    assert row["grade"] == "weak"
    assert row["issue_specific_executed"] == []
    assert "No issue-family bounded action executed." in row["gaps"]


def test_coverage_row_does_not_credit_generic_held_action_as_issue_specific() -> None:
    proposals = [
        _proposal("facilities_energy_agent", "maintenance", "create_work_order", status="ready_for_executor", policy="passed", disposition="execute_controlled_internal"),
        _proposal("facilities_energy_agent", "maintenance", "create_work_order", status="awaiting_executive", policy="requires_compliance", disposition="open_review_do_not_reopen", issue_specific=False),
    ]
    receipts = [
        {"agent": "facilities_energy_agent", "department": "maintenance", "source_tool": "create_work_order", "result": {"status": "executed_controlled"}},
        {"agent": "facilities_energy_agent", "department": "maintenance", "source_tool": "create_work_order", "result": {"status": "held"}},
    ]

    row = _coverage_row(_result(proposals, receipts))

    assert row["grade"] == "strong"
    assert row["issue_specific_executed"] == ["maintenance::create_work_order"]
    assert row["issue_specific_held"] == []


def test_coverage_row_marks_missing_issue_specific_proposals_generic() -> None:
    row = _coverage_row(_result([], [{"agent": "ride_ops_agent", "department": "operations", "source_tool": "create_ops_alert", "result": {"status": "executed_controlled"}}]))

    assert row["grade"] == "generic"
    assert "No first-round issue-specific proposal." in row["gaps"]
