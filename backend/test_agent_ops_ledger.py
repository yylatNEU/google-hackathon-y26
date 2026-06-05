from __future__ import annotations

from agent_ops_ledger import (
    build_ledger_record_from_run,
    build_operational_backlog,
    read_agent_ops_ledger,
    record_agent_ops_record,
    retrieve_agent_ops_context,
)


def stressed_state():
    return {
        "guestFlow": {
            "activeScenario": {"key": "showtime_wave", "name": "Showtime Wave"},
            "avgSatisfaction": 58,
            "paths": [
                {"fromName": "Coaster", "toName": "Plaza", "congestionLevel": 92},
                {"fromName": "Food", "toName": "Exit", "congestionLevel": 71},
            ],
            "rides": [
                {"name": "Dragon", "throughputGap": 650},
                {"name": "Sky", "throughputGap": 430},
            ],
        },
        "foodInventory": {
            "locations": [
                {"id": "foodCourt1", "mobileOrderBacklog": 460, "pickupEtaMinutes": 52},
                {"id": "other", "mobileOrderBacklog": 10, "pickupEtaMinutes": 5},
            ]
        },
        "operatingClock": {
            "foodRetailLifecycle": {"mobileOrderBacklogPressurePct": 94},
            "accessFairness": {
                "publicComplaintRiskPct": 78,
                "perceivedFairnessScore": 41,
                "premiumLaneSharePct": 66,
                "standbyLaneSharePct": 34,
                "standbyDelayDeltaMins": 31,
            },
            "eventSchedule": {
                "eventTrafficRiskPct": 88,
                "activeWave": "fireworks_exit",
                "nextEvent": {"name": "Fireworks"},
            },
            "guestFeedbackLoop": {"careCaseAccumulationPct": 85, "sentimentMomentum": "falling"},
            "staffLifecycle": {"breakPressurePct": 91},
        },
        "planningAgent": {
            "readinessPct": 54,
            "plannerHorizonMinutes": 180,
            "activePlan": {"nextDecisionDeadlineMinutes": 9},
        },
        "parkOps": {"guestRecoveryPressure": 92},
        "weather": {"stormRisk": 89},
        "energy": {"gridLoadPercent": 97, "utilityPricePerMwh": 340},
        "staffing": {"openCallouts": 25, "medicalTeams": 2, "securityTeams": 3},
        "guestCare": {"complaintRatePct": 19, "openCases": 130},
    }


def test_agent_ops_ledger_persists_and_retrieves_prior_action(monkeypatch, tmp_path):
    monkeypatch.setenv("PARKPULSE_AGENT_OPS_LEDGER", str(tmp_path / "agent_ops.jsonl"))

    result = record_agent_ops_record(
        {
            "signature": "fireworks-fairness-1",
            "scenarioName": "fireworks release",
            "selectedAction": "Meter Fast Lane and split public exit paths",
            "gate": "passed",
            "evalScore": 91,
            "dispatchCount": 3,
            "summary": "Reduced public crowd complaints while preserving bounded premium access.",
            "toolCalls": [{"tool": "validate_policy", "status": "called"}],
            "traceEvents": [{"label": "Policy gate", "message": "Fairness gate passed."}],
        }
    )

    assert result["status"] == "stored"
    listed = read_agent_ops_ledger(limit=5)
    assert listed["count"] == 1
    assert listed["items"][0]["selectedAction"] == "Meter Fast Lane and split public exit paths"

    retrieved = retrieve_agent_ops_context("fireworks Fast Lane fairness", limit=2)
    assert retrieved["status"] == "retrieved"
    assert retrieved["summary"][0]["evalScore"] == 91


def test_agent_ops_ledger_builds_record_from_run_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("PARKPULSE_AGENT_OPS_LEDGER", str(tmp_path / "agent_ops.jsonl"))

    record = build_ledger_record_from_run(
        {
            "run_receipt": {"id": "receipt_1"},
            "trace_contract": {"trace_id": "trace-1", "memory_write": {"outcome_id": "outcome-1"}},
            "run_telemetry": {
                "planner": {"selected_action": {"label": "Open overflow route"}},
                "governance": {"gate_status": "passed"},
                "eval": {"scorecard": {"overall": 88, "failure_reasons": []}},
                "delivery": {
                    "summary": {"total": 2},
                    "response": {"takeRate": 0.42, "reactiveFollowThroughRate": 0.36},
                    "dispatches": [{"channel": "guest_app", "message": "Use Theater B route."}],
                },
                "digital_twin_tools": {"tool_calls": [{"tool": "simulate_action", "status": "called"}]},
            },
        },
        message="showtime route split",
        mode="proact",
        kind="proactive_run",
    )

    assert record["selectedAction"] == "Open overflow route"
    assert record["evalScore"] == 88
    assert record["dispatchCount"] == 2
    assert record["takeRatePct"] == 42
    assert record["memoryId"] == "outcome-1"


def test_agent_ops_run_binds_runtime_case_and_policy_refs(monkeypatch, tmp_path):
    monkeypatch.setenv("PARKPULSE_AGENT_OPS_LEDGER", str(tmp_path / "agent_ops.jsonl"))

    record = build_ledger_record_from_run(
        {
            "run_receipt": {"id": "receipt_case_binding"},
            "run_telemetry": {
                "planner": {"selected_action": {"label": "Pause intake and split affected coaster guests"}},
                "governance": {"gate_status": "review"},
                "eval": {"scorecard": {"overall": 78, "failure_reasons": []}},
                "delivery": {
                    "summary": {"total": 2},
                    "response": {"takeRate": 0.5},
                    "dispatches": [{"channel": "guest_app", "message": "Use signed alternate route away from parade spillback."}],
                },
            },
        },
        message="ride down near parade with families stuck in the coaster queue",
        mode="react",
        kind="agent_run",
    )

    assert record["caseId"] == "CASE-RIDE-DOWN-PARADE-001"
    assert record["caseLinkSource"] == "runtime_case_binding"
    assert record["caseLinkConfidence"] >= 0.7
    assert "PARK-SAFE-001" in record["policyRefs"]
    assert "PARK-ACT-001" in record["policyRefs"]


def test_agent_ops_upgrades_old_doctrine_inferred_case_when_runtime_binding_is_clear(monkeypatch, tmp_path):
    monkeypatch.setenv("PARKPULSE_AGENT_OPS_LEDGER", str(tmp_path / "agent_ops.jsonl"))

    result = record_agent_ops_record(
        {
            "id": "old-receipt",
            "signature": "old-sig",
            "scenarioName": "ride_down",
            "selectedAction": "React Agent created an observed receiver outcome for ride_down.",
            "summary": "Coaster is down while parade releases nearby and queue spillback is rising.",
            "caseId": "CASE-RIDE-DOWN-PARADE-001",
            "caseLinkSource": "doctrine_inferred",
            "policyRefs": ["PARK-SAFE-001"],
            "evalScore": 78,
        }
    )

    row = result["record"]
    assert row["caseId"] == "CASE-RIDE-DOWN-PARADE-001"
    assert row["caseLinkSource"] == "runtime_case_binding"
    assert "PARK-OPS-002" in row["policyRefs"]
    assert row["caseLinkEvidence"]["strongHits"] >= 1


def test_agent_ops_backlog_covers_enterprise_pressure_and_decision_market(monkeypatch, tmp_path):
    monkeypatch.setenv("PARKPULSE_AGENT_OPS_LEDGER", str(tmp_path / "agent_ops.jsonl"))
    for index in range(3):
        record_agent_ops_record(
            {
                "id": f"repeat-{index}",
                "signature": f"repeat-sig-{index}",
                "timestamp": f"2026-05-27T20:0{index}:00Z",
                "scenarioName": "showtime_wave",
                "selectedAction": "Broad operations reroute",
                "gate": "blocked" if index == 0 else "passed",
                "evalScore": 52 + index,
                "dispatchCount": 3,
                "takeRatePct": 0.25,
                "followThroughPct": 0.2,
                "memoryId": "outcome-repeat",
                "traceId": "trace-repeat",
                "summary": "food fairness showtime congestion guest recovery",
                "receiverActions": ["guest_app: reroute", "worker_device: stage staff"],
                "toolCalls": [{"tool": "simulate_action", "status": "called", "agent": "ops"}],
                "traceEvents": [{"label": "Policy", "message": "blocked"}],
                "evalDimensions": [{"label": "Safety", "value": 52}],
                "failureReasons": ["access lane risk"],
            }
        )

    backlog = build_operational_backlog(stressed_state(), limit=10)

    issue_ids = {issue["id"] for issue in backlog["issues"]}
    assert {
        "food-court-a-backlog",
        "fast-lane-fairness-risk",
        "showtime-traffic-wave",
        "guest-recovery-pressure",
        "safety-access-readiness",
        "finance-exposure-watch",
        "planning-horizon-risk",
        "customer-experience-trust-risk",
    } <= issue_ids
    assert backlog["overallStatus"] == "needs_strategy_shift"
    assert backlog["effectiveness"]["repeatedActionStreak"]["status"] == "repetitive"
    assert backlog["evalBreakdown"]["verdict"] == "Needs strategy shift"
    assert backlog["multiAgentCouncil"]["leadAgent"] == "Safety/Policy Agent"
    assert backlog["agentDecisionMarket"]["winningCandidate"]["feasible"] is True
    assert backlog["agentDecisionMarket"]["regretAnalysis"]["avoidedVetoes"] >= 1
    assert backlog["enterpriseSummary"]["weakestDomain"]["id"] in {"safety", "customer_experience", "finance", "planning", "operations"}


def test_incident_analytics_combines_human_review_sources(monkeypatch, tmp_path):
    monkeypatch.setenv("PARKPULSE_AGENT_OPS_LEDGER", str(tmp_path / "agent_ops.jsonl"))
    record_agent_ops_record(
        {
            "signature": "incident-repeat",
            "timestamp": "2026-05-27T20:10:00Z",
            "scenarioName": "showtime_wave",
            "selectedAction": "Repeat crowd reroute",
            "gate": "passed",
            "evalScore": 60,
            "summary": "repeated action",
        }
    )
    backlog = build_operational_backlog(stressed_state(), limit=10)
    ledger = read_agent_ops_ledger(limit=5)

    from incident_analytics import build_incident_analytics

    analytics = build_incident_analytics(
        state=stressed_state(),
        audit={
            "anomalies": [
                {
                    "id": "audit-1",
                    "domain": "Safety",
                    "title": "Access lane anomaly",
                    "severity": "critical",
                    "status": "open",
                    "description": "Access lane blocked",
                    "recommendedAction": "Hold broad reroutes",
                    "abnormalityScore": 91,
                    "leadTimeMinutes": 5,
                    "owner": "Safety lead",
                    "detectedAt": "2026-05-27T20:11:00Z",
                }
            ]
        },
        signals={
            "signals": [
                {
                    "id": "signal-1",
                    "risk_level": "CRITICAL",
                    "zone": {"id": "foodCourt1", "name": "Food Court A"},
                    "text": "guest fainted near food court",
                    "source": "guest_health_report",
                    "confidence": 0.9,
                    "categories": ["medical", "crowd_pressure"],
                    "missing_info": ["exact location"],
                    "human_approval_required": True,
                    "reporterRole": "guest",
                    "createdAt": "2026-05-27T20:12:00Z",
                },
                "bad",
            ]
        },
        dispatches=[
            {
                "id": "dispatch-1",
                "status": "pending_operator_approval",
                "channel": "equipment_controller",
                "endpoint": "/equipment",
                "payload": {
                    "command": "hold_hvac",
                    "requiresHumanApproval": True,
                    "reason": "safety check",
                    "zones": ["foodCourt1"],
                },
                "createdAt": "2026-05-27T20:13:00Z",
            },
            {"status": "delivered", "payload": {}},
        ],
        backlog=backlog,
        ledger=ledger,
    )

    assert analytics["summary"]["ticketCount"] >= len(backlog["issues"])
    assert analytics["summary"]["criticalCount"] >= 1
    assert analytics["summary"]["humanReviewCount"] >= 1
    assert analytics["operatorBrief"]["confidence"] == "high"
    assert analytics["analytics"]["reviewPosture"] == "active_human_review"
    assert any(ticket["source"] == "audit_agent" for ticket in analytics["tickets"])
    assert any(ticket["source"] == "signal_inbox" for ticket in analytics["tickets"])
    assert any(ticket["source"] == "action_approval" for ticket in analytics["tickets"])


def test_agent_ops_and_incident_empty_edge_branches(monkeypatch, tmp_path):
    ledger_path = tmp_path / "agent_ops.jsonl"
    monkeypatch.setenv("PARKPULSE_AGENT_OPS_LEDGER", str(ledger_path))

    import agent_ops_ledger
    import incident_analytics
    from incident_analytics import build_incident_analytics

    assert agent_ops_ledger._number(True) is None
    monkeypatch.delenv("PARKPULSE_AGENT_OPS_LEDGER", raising=False)
    monkeypatch.setenv("PARKPULSE_RUNTIME_DIR", str(tmp_path))
    assert str(agent_ops_ledger._ledger_path()).endswith("agent_ops_ledger.jsonl")
    monkeypatch.setenv("PARKPULSE_AGENT_OPS_LEDGER", str(ledger_path))
    assert agent_ops_ledger._dispatch_summary({"dispatches": ["bad", {"channel": "guest_app", "payload": {"message": "hello"}}]}) == (
        2,
        ["guest_app: hello"],
    )
    assert agent_ops_ledger._first_location({"foodInventory": {"locations": [{"id": "fallback"}]}}, "missing")["id"] == "fallback"
    assert agent_ops_ledger._action_streak(
        [{"selectedAction": "A"}, {"selectedAction": "A"}, {"selectedAction": "B"}]
    ) == {"count": 2, "action": "A", "status": "varied"}
    assert agent_ops_ledger._tool_calls({"digital_twin_tools": {"tool_calls": ["bad", {"capability": "cap", "result_status": "ok"}]}}, {}) == [
        {"tool": "cap", "status": "ok", "agent": None}
    ]
    blocked_eval = agent_ops_ledger._build_eval_breakdown(
        rows=[{"gate": "failed", "evalScore": 90}],
        issues=[],
        latest={"gate": "failed", "evalScore": 90},
        repeated_action_warning=False,
        complaint_risk=10,
        traffic_risk=10,
        food_backlog=0,
        food_eta=0,
        food_pressure=0,
        recovery_pressure=0,
    )
    assert blocked_eval["verdict"] == "Unsafe / blocked"
    no_issue_eval = agent_ops_ledger._build_eval_breakdown(
        rows=[{"gate": "passed", "evalScore": 90}],
        issues=[],
        latest={"gate": "passed", "evalScore": 90},
        repeated_action_warning=False,
        complaint_risk=10,
        traffic_risk=10,
        food_backlog=0,
        food_eta=0,
        food_pressure=0,
        recovery_pressure=0,
    )
    assert no_issue_eval["dimensions"][2]["score"] == 88

    empty_backlog = build_operational_backlog(
        {
            "guestFlow": {"avgSatisfaction": 82, "paths": [], "rides": []},
            "operatingClock": {
                "foodRetailLifecycle": {"mobileOrderBacklogPressurePct": 10},
                "accessFairness": {"publicComplaintRiskPct": 5},
                "eventSchedule": {"eventTrafficRiskPct": 5},
                "guestFeedbackLoop": {"careCaseAccumulationPct": 5},
                "staffLifecycle": {"breakPressurePct": 5},
            },
            "foodInventory": {"locations": [{"id": "foodCourt1", "mobileOrderBacklog": 2, "pickupEtaMinutes": 3}]},
            "planningAgent": {"readinessPct": 92},
            "parkOps": {"guestRecoveryPressure": 5},
            "weather": {"stormRisk": 5},
            "energy": {"gridLoadPercent": 40, "utilityPricePerMwh": 100},
            "staffing": {"openCallouts": 0},
            "guestCare": {"complaintRatePct": 1, "openCases": 0},
        },
        limit=1,
    )
    assert empty_backlog["overallStatus"] == "stable"
    assert empty_backlog["evalBreakdown"]["verdict"] == "Pass"
    assert empty_backlog["effectiveness"]["repeatedActionStreak"]["status"] == "empty"

    first = record_agent_ops_record({"signature": "same", "selectedAction": "A", "evalScore": 80})
    second = record_agent_ops_record({"signature": "same", "selectedAction": "A", "evalScore": 81})
    assert first["status"] == "stored"
    assert second["status"] == "deduplicated"
    assert agent_ops_ledger.record_agent_ops_run({"status": "ok"}, message="m", mode="mode", kind="kind")["status"] == "stored"

    with ledger_path.open("a", encoding="utf-8") as file:
        file.write("\nnot-json\n")
    assert read_agent_ops_ledger(limit=10)["count"] >= 2
    assert read_agent_ops_ledger(limit=10, query="no matching terms")["count"] == 0

    no_tickets = build_incident_analytics(
        state={"guestFlow": {"activeScenario": {"key": "quiet"}}},
        audit={"anomalies": ["bad"]},
        signals={"signals": ["bad"]},
        dispatches=["bad", {"status": "delivered", "payload": {}}],
        backlog={"issues": ["bad"], "effectiveness": {"repeatedActionStreak": {"status": "varied"}}},
        ledger={"count": 0},
    )
    assert no_tickets["summary"]["ticketCount"] == 0
    assert no_tickets["summary"]["recommendedCall"] == "No incident ticket is currently open."
    assert no_tickets["operatorBrief"]["confidence"] == "low"
    assert incident_analytics._safe_int("bad", fallback=7) == 7

    human_review = build_incident_analytics(
        state={},
        audit={},
        signals={},
        dispatches=[{"id": "d1", "status": "pending_operator_approval", "channel": "worker_device", "payload": {"task": "review"}}],
        backlog={"issues": [], "effectiveness": {"repeatedActionStreak": {"status": "varied"}}},
        ledger={"count": 1},
    )
    assert human_review["summary"]["recommendedCall"] == "Human lead should clear the review queue and choose which bounded action to approve."

    monitor_only = build_incident_analytics(
        state={},
        audit={},
        signals={"signals": [{"id": "watch-1", "risk_level": "WATCH", "zone": {}, "missing_info": [], "human_approval_required": False}]},
        dispatches=[],
        backlog={"issues": [], "effectiveness": {"repeatedActionStreak": {"status": "varied"}}},
        ledger={"count": 1},
    )
    assert monitor_only["summary"]["recommendedCall"] == "Human lead can monitor; no critical approval is waiting."
