import asyncio
import json

import main
import product_learning_loop as loop
import park_staff_roleplay as roleplay
from park_role_access import sign_role_session


def reset_loop(monkeypatch, tmp_path):
    monkeypatch.setenv("PARKPULSE_PRODUCT_LEARNING_LOG_PATH", str(tmp_path / "product_learning_loop.jsonl"))
    monkeypatch.setenv("PARKPULSE_STAFF_TRAINING_LOG_PATH", str(tmp_path / "staff_training_sessions.jsonl"))
    roleplay._SESSIONS.clear()


async def _call_app(method: str, path: str, body: dict | None = None, token: str | None = None, role: str | None = None):
    sent = []
    body_bytes = json.dumps(body or {}).encode("utf-8")
    received = False
    route_path, _, query = path.partition("?")
    headers = []
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode("utf-8")))
    if role:
        headers.append((b"x-parkpulse-role", role.encode("utf-8")))
    if body is not None:
        headers.append((b"content-type", b"application/json"))

    async def receive():
        nonlocal received
        if received:
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    async def send(message):
        sent.append(message)

    await main.app({"type": "http", "method": method, "path": route_path, "query_string": query.encode("utf-8"), "headers": headers}, receive, send)
    status = next(item["status"] for item in sent if item["type"] == "http.response.start")
    response_body = b"".join(item.get("body", b"") for item in sent if item["type"] == "http.response.body")
    return status, json.loads(response_body or b"{}")


def test_live_issue_and_training_gap_feed_learning_signals_with_boundaries(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)

    issue = loop.create_park_issue_ticket(
        source="guest",
        issue_type="lost_child_report",
        summary="Guardian reports missing child near carousel.",
        severity="critical",
        location="carousel",
    )
    gap = loop.create_training_gap_ticket(
        scenario_id="lost_child_report",
        gap_type="escalation",
        severity="critical_training_gap",
        evidence={"score": 49, "critical_miss": True, "open_gaps": ["Missing escalation path: Security."]},
        trainee_name="QA trainee",
        session_id="session-1",
    )
    status = loop.product_learning_loop_status()

    assert issue["ticket"]["live_ops_authority"] is True
    assert issue["ticket"]["requires_human_ack"] is True
    assert gap["ticket"]["live_ops_authority"] is False
    assert status["park_issue_ticket_count"] == 1
    assert status["training_gap_ticket_count"] == 1
    assert status["learning_signal_count"] >= 3
    assert status["loop_contract"]["training_gaps_create_live_issues"] is False
    assert any(signal["source"] == "park_issue_ticket" for signal in status["product_learning_signals"])
    assert any(signal["source"] == "training_gap_ticket" for signal in status["product_learning_signals"])
    assert any(signal["source"] == "manager_review" for signal in status["product_learning_signals"])


def test_failed_roleplay_finish_creates_training_gap_not_live_issue(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)
    session = roleplay.start_staff_training_session("lost_child_report", "Training Loop QA")
    roleplay.advance_staff_training_turn(session["id"], "Go look around and come back if you cannot find her.")

    finished = roleplay.finish_staff_training_session(session["id"])
    status = loop.product_learning_loop_status()

    assert finished["training_gap_ticket"]["status"] == "created"
    assert finished["training_gap_ticket"]["ticket"]["live_ops_authority"] is False
    assert status["park_issue_ticket_count"] == 0
    assert status["training_gap_ticket_count"] == 1
    assert status["product_learning_signals"][0]["requires_review"] is True


def test_dynamic_operational_backlog_generates_live_issue_tickets(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)
    backlog = {
        "issues": [
            {
                "id": "safety-access-readiness",
                "domain": "Safety",
                "title": "Safety and access readiness needs active supervision",
                "severity": "critical",
                "status": "unresolved",
                "current": "storm 90% / path congestion 84%",
                "recommendedNext": "Pre-stage safety leads and keep access routes clear.",
                "evidence": ["stormRisk=90", "maxPathCongestion=84"],
            }
        ]
    }

    status = loop.product_learning_loop_status(operational_backlog=backlog)

    assert status["park_issue_ticket_count"] == 1
    assert status["dynamic_park_issue_ticket_count"] == 1
    ticket = status["park_issue_tickets"][0]
    assert ticket["source"] == "dynamic_park"
    assert ticket["event"] == "park_issue_ticket_generated"
    assert ticket["live_ops_authority"] is True
    assert ticket["requires_human_ack"] is True
    assert ticket["issue_type"] == "weather_evacuation_confusion"
    assert any(signal["source"] == "park_issue_ticket" for signal in status["product_learning_signals"])


def test_dynamic_live_ticket_generation_backtest_matrix(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)
    backlog = {
        "issues": [
            {
                "id": "fast-lane-fairness-risk",
                "domain": "Guest Recovery",
                "title": "Fast lane fairness complaints rising",
                "severity": "warning",
                "status": "unresolved",
                "current": "complaint risk 76%",
                "recommendedNext": "Move a guest services lead to the fast lane merge.",
                "evidence": ["complaintRiskPct=76"],
            },
            {
                "id": "food-court-a-backlog",
                "domain": "Food",
                "title": "Food pickup backlog driving refund pressure",
                "severity": "medium",
                "status": "unresolved",
                "current": "mobile backlog 180 orders / ETA 32m",
                "recommendedNext": "Open mobile-order recovery desk.",
                "evidence": ["mobileOrderBacklog=180", "pickupEtaMinutes=32"],
            },
            {
                "id": "mobility-accommodation-gap",
                "domain": "Accessibility",
                "title": "Mobility accommodation queue needs privacy-aware support",
                "severity": "high",
                "status": "unresolved",
                "current": "accessibility party wait 28m",
                "recommendedNext": "Send Accessibility lead with quiet routing options.",
                "evidence": ["mobilityWaitMinutes=28"],
            },
            {
                "id": "first-aid-heat-watch",
                "domain": "First Aid",
                "title": "Heat concern reports increasing near west plaza",
                "severity": "critical",
                "status": "unresolved",
                "current": "heat index 104F",
                "recommendedNext": "Pre-stage first aid and water at west plaza.",
                "evidence": ["heatIndexF=104"],
            },
        ]
    }

    status = loop.product_learning_loop_status(operational_backlog=backlog)
    tickets = {ticket["dynamic_park_issue_id"]: ticket for ticket in status["park_issue_tickets"]}

    assert status["park_issue_ticket_count"] == 4
    assert status["dynamic_park_issue_ticket_count"] == 4
    assert tickets["fast-lane-fairness-risk"]["issue_type"] == "angry_parent"
    assert tickets["fast-lane-fairness-risk"]["severity"] == "high"
    assert tickets["food-court-a-backlog"]["issue_type"] == "refund_request"
    assert tickets["food-court-a-backlog"]["requires_human_ack"] is False
    assert tickets["mobility-accommodation-gap"]["issue_type"] == "accessibility_accommodation"
    assert tickets["mobility-accommodation-gap"]["assigned_team"] == "accessibility"
    assert tickets["first-aid-heat-watch"]["issue_type"] == "heat_exhaustion_concern"
    assert tickets["first-aid-heat-watch"]["requires_human_ack"] is True
    assert all(ticket["source"] == "dynamic_park" for ticket in tickets.values())
    assert all(ticket["live_ops_authority"] is True for ticket in tickets.values())


def test_place_risk_generates_accident_complaint_and_accessibility_tickets(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)
    state = {
        "placeRiskGraph": {
            "places": [
                {
                    "id": "west_plaza",
                    "name": "West Plaza",
                    "currentLoad": 92,
                    "waitMinutes": 31,
                    "riskFactors": ["poor_shade", "long_wait"],
                    "evidence": ["heatIndexF=104", "shadeCoverage=18", "queueWaitMinutes=31"],
                },
                {
                    "id": "coaster_exit_merge",
                    "name": "Coaster Exit Merge",
                    "currentLoad": 94,
                    "riskFactors": ["narrow_path", "crowd_bottleneck"],
                    "evidence": ["pathCongestion=94", "widthM=3.8"],
                },
                {
                    "id": "accessibility_detour",
                    "name": "Accessibility Detour",
                    "currentLoad": 83,
                    "riskFactors": ["misplaced_accessibility_route"],
                    "evidence": ["accessibleRouteBlocked=true", "privacyRisk=high"],
                },
            ]
        },
        "simTime": {"day": 1, "hour": 15, "minute": 20},
    }

    candidates = loop.generate_place_risk_ticket_candidates(state)
    tickets = loop.product_learning_loop_status(park_state=state, incident_seed="place-risk-backtest")["park_issue_tickets"]
    issue_types = {candidate["issue_type"] for candidate in candidates}

    assert {"heat_exhaustion_concern", "injury_or_safety_incident", "accessibility_accommodation"} <= issue_types
    assert any(ticket["source"] == "place_risk" and ticket["issue_type"] == "injury_or_safety_incident" for ticket in tickets)
    assert any(ticket["ticket_generation_trace"]["matched_rule"] == "narrow_congested_path_injury_risk" for ticket in tickets)
    assert any("shadeCoverage=18" in ticket["ticket_generation_trace"]["causal_chain"] for ticket in tickets)
    assert all(ticket["live_ops_authority"] is True for ticket in tickets)
    assert any(ticket["requires_human_ack"] is True for ticket in tickets if ticket["issue_type"] == "injury_or_safety_incident")


def test_seeded_random_incident_generation_is_repeatable(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)
    state = {
        "placeRiskGraph": {
            "places": [
                {
                    "id": "covered_plaza_leak",
                    "name": "Covered Plaza Leak",
                    "currentLoad": 98,
                    "riskFactors": ["wet_surface", "crowd_bottleneck"],
                    "evidence": ["waterLeak=true", "currentLoad=98"],
                }
            ]
        },
        "simTime": {"day": 1, "hour": 16, "minute": 5},
    }

    first = loop.generate_random_incident_ticket_candidates(state, seed="wet-surface-backtest")
    second = loop.generate_random_incident_ticket_candidates(state, seed="wet-surface-backtest")

    assert first == second
    assert first
    assert first[0]["source"] == "random_incident"
    assert first[0]["issue_type"] == "injury_or_safety_incident"
    assert first[0]["matched_rule"] == "seeded_slip_trip_or_collision"


def test_auto_learning_governance_auto_drafts_low_risk_shadow_candidate(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)
    backlog = {
        "issues": [
            {
                "id": "queue-merge-watch-a",
                "domain": "Ride Ops",
                "title": "Queue merge conflict complaints at mild threshold",
                "severity": "medium",
                "status": "unresolved",
                "current": "merge complaint cluster",
                "recommendedNext": "Clarify merge signage and staff script.",
                "evidence": ["mergeComplaints=3"],
            },
            {
                "id": "queue-merge-watch-b",
                "domain": "Ride Ops",
                "title": "Queue merge conflict repeated after show wave",
                "severity": "medium",
                "status": "unresolved",
                "current": "merge complaint cluster repeated",
                "recommendedNext": "Clarify merge signage and staff script.",
                "evidence": ["mergeComplaints=4"],
            },
        ]
    }

    status = loop.product_learning_loop_status(operational_backlog=backlog)
    candidates = status["auto_learning_candidates"]

    assert status["auto_learning_candidate_count"] >= 1
    assert status["shadow_ready_candidate_count"] >= 1
    candidate = next(item for item in candidates if item["scenario_id"] == "line_cutting_conflict")
    assert candidate["governance_status"] == "candidate_auto_drafted"
    assert candidate["shadow_deployment"]["status"] == "shadow_ready"
    assert candidate["shadow_deployment"]["live_active"] is False
    assert all(gate["status"] == "pass" for gate in candidate["automated_eval_gates"])


def test_auto_learning_governance_blocks_high_risk_and_refund_exceptions(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)
    backlog = {
        "issues": [
            {
                "id": "food-court-a-backlog",
                "domain": "Food",
                "title": "Food pickup backlog driving refund pressure",
                "severity": "medium",
                "status": "unresolved",
                "current": "mobile backlog 180 orders / ETA 32m",
                "recommendedNext": "Open mobile-order recovery desk.",
                "evidence": ["mobileOrderBacklog=180", "pickupEtaMinutes=32"],
            },
            {
                "id": "first-aid-heat-watch",
                "domain": "First Aid",
                "title": "Heat concern reports increasing near west plaza",
                "severity": "critical",
                "status": "unresolved",
                "current": "heat index 104F",
                "recommendedNext": "Pre-stage first aid and water at west plaza.",
                "evidence": ["heatIndexF=104"],
            },
        ]
    }

    status = loop.product_learning_loop_status(operational_backlog=backlog)
    exceptions = {item["scenario_id"]: item for item in status["human_exception_queue"]}

    assert "refund_request" in exceptions
    assert "heat_exhaustion_concern" in exceptions
    assert exceptions["refund_request"]["governance_status"] == "human_exception_required"
    assert "protected_or_high_risk_issue_type" in exceptions["refund_request"]["exception_reasons"]
    assert exceptions["heat_exhaustion_concern"]["shadow_deployment"]["status"] == "blocked"
    assert status["auto_learning_governance"]["eval_contract"]["auto_promote_live_ops"] is False


def test_product_learning_api_backtests_dynamic_park_live_ticket_generation(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)
    main._hot_endpoint_cache.pop("park_state_lite", None)

    async def fake_state_lite():
        return {"operatingClock": {"accessFairness": {"complaintRiskPct": 81}}}

    def fake_backlog(state):
        assert state["operatingClock"]["accessFairness"]["complaintRiskPct"] == 81
        return {
            "issues": [
                {
                    "id": "fast-lane-fairness-risk",
                    "domain": "Guest Recovery",
                    "title": "Fast lane fairness complaints rising",
                    "severity": "warning",
                    "status": "unresolved",
                    "current": "complaint risk 81%",
                    "recommendedNext": "Move a guest services lead to the fast lane merge.",
                    "evidence": ["complaintRiskPct=81"],
                }
            ]
        }

    monkeypatch.setattr(main, "_fast_park_state_lite", fake_state_lite)
    import agent_ops_ledger

    monkeypatch.setattr(agent_ops_ledger, "build_operational_backlog", fake_backlog)
    ops_token = sign_role_session("test-ops", "ops_team", main._role_auth_secret())

    loop_status, payload = asyncio.run(_call_app("GET", "/api/park/product-learning/loop?limit=20", token=ops_token))

    assert loop_status == 200
    assert payload["dynamic_park_issue_ticket_count"] == 1
    assert payload["park_issue_ticket_count"] == 1
    ticket = payload["park_issue_tickets"][0]
    assert ticket["event"] == "park_issue_ticket_generated"
    assert ticket["source"] == "dynamic_park"
    assert ticket["issue_type"] == "angry_parent"
    assert ticket["severity"] == "high"
    assert ticket["derived_from"] == "operational_backlog"
    assert payload["loop_contract"]["training_gaps_create_live_issues"] is False


def test_passed_roleplay_does_not_create_training_gap_ticket(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)
    session = roleplay.start_staff_training_session("lost_child_report", "Pass QA")
    roleplay.advance_staff_training_turn(
        session["id"],
        "I am sorry. Stay with me at this meeting point while I radio Security and Operations now. What is her name, age, clothing, and last seen location?",
    )

    finished = roleplay.finish_staff_training_session(session["id"])
    status = loop.product_learning_loop_status()

    assert finished["training_gap_ticket"]["status"] == "skipped"
    assert status["training_gap_ticket_count"] == 0


def test_product_learning_api_routes_and_role_gates(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)
    worker_token = sign_role_session("test-worker", "onsite_worker", main._role_auth_secret())
    ops_token = sign_role_session("test-ops", "ops_team", main._role_auth_secret())

    issue_status, issue = asyncio.run(
        _call_app(
            "POST",
            "/api/park/product-learning/issue-ticket",
            {"source": "employee", "issueType": "heat_exhaustion_concern", "summary": "Guest looks pale in the sun."},
            token=worker_token,
        )
    )
    assert issue_status == 200
    assert issue["ticket"]["live_ops_authority"] is True

    blocked_status, blocked = asyncio.run(
        _call_app(
            "POST",
            "/api/park/product-learning/training-gap-ticket",
            {"scenarioId": "heat_exhaustion_concern", "gapType": "safety_awareness"},
            token=worker_token,
        )
    )
    assert blocked_status == 403
    assert blocked["mode"] == "role_authorization_gate"

    gap_status, gap = asyncio.run(
        _call_app(
            "POST",
            "/api/park/product-learning/training-gap-ticket",
            {"scenarioId": "heat_exhaustion_concern", "gapType": "safety_awareness", "evidence": {"score": 61}},
            token=ops_token,
        )
    )
    assert gap_status == 200
    assert gap["ticket"]["live_ops_authority"] is False

    loop_status, payload = asyncio.run(_call_app("GET", "/api/park/product-learning/loop", token=ops_token))
    assert loop_status == 200
    assert payload["park_issue_ticket_count"] >= 1
    assert any(
        ticket.get("issue_type") == "heat_exhaustion_concern"
        for ticket in payload["park_issue_tickets"]
    )
    assert payload["training_gap_ticket_count"] == 1
    assert payload["learning_signal_count"] >= 1
