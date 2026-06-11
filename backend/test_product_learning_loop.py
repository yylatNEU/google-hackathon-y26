import asyncio
import json
import os
import types

import main
import product_learning_loop as loop
import park_staff_roleplay as roleplay
from park_role_access import sign_role_session


def reset_loop(monkeypatch, tmp_path):
    monkeypatch.setenv("PARKPULSE_PRODUCT_LEARNING_LOG_PATH", str(tmp_path / "product_learning_loop.jsonl"))
    monkeypatch.setenv("PARKPULSE_PRODUCT_LEARNING_DB_PATH", str(tmp_path / "product_learning_loop.sqlite"))
    monkeypatch.setenv("PARKPULSE_STAFF_TRAINING_LOG_PATH", str(tmp_path / "staff_training_sessions.jsonl"))
    roleplay._SESSIONS.clear()
    try:
        import mongo_memory

        mongo_memory._memory._fallback["guest_messages"] = []
    except Exception:
        pass


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


def test_guest_triage_persists_guest_message_memory_for_training_recommendations(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)
    try:
        import mongo_memory

        mongo_memory._memory._fallback["guest_messages"] = []
    except Exception:
        pass

    triage = loop.triage_guest_message(
        message="My child is missing near the carousel. I need help right now.",
        location="Carousel",
        channel="guest_app",
        create_ticket=True,
    )
    memory = loop.guest_triage_training_memory("lost_child_report")
    recommendations = loop.recommended_training_scenarios_from_guest_triage()

    assert triage["memory_persistence"]["collection"] == "guest_messages"
    assert triage["memory_persistence"]["scenario_id"] == "lost_child_report"
    assert triage["memory_impact"]["stored"] is True
    assert triage["memory_impact"]["training_scenario_id"] == "lost_child_report"
    assert triage["memory_impact"]["historical_ticket_frequency"]["ticket_count"] >= 1
    assert triage["llm_response"]["reply"]
    assert triage["llm_response"]["llm_controls_live_ops"] is False
    assert memory["status"] == "ready"
    assert memory["patterns"][0]["scenario_id"] == "lost_child_report"
    assert memory["patterns"][0]["count"] >= 1
    assert recommendations[0]["scenario_id"] == "lost_child_report"
    assert recommendations[0]["requires_manager_review"] is True


def test_guest_triage_parsing_acknowledgement_and_learning_version_branches(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)

    monkeypatch.delenv("PARKPULSE_PRODUCT_LEARNING_DB_PATH", raising=False)
    monkeypatch.setenv("PARKPULSE_PRODUCT_LEARNING_LOG_PATH", str(tmp_path / "fallback-ledger.jsonl"))
    assert loop._event_db_path().endswith("fallback-ledger.sqlite")
    assert loop._event_storage_id({"event": "no-explicit-id"}).startswith("event-")
    assert loop._read_events_jsonl(limit=1) == []

    ledger = tmp_path / "fallback-ledger.jsonl"
    ledger.write_text(
        "\n".join(
            [
                "{bad json}",
                json.dumps(["not", "a", "dict"]),
                json.dumps({"id": "event-1", "event": "guest_message_triaged", "created_at": "2026-06-10T12:00:00Z"}),
            ]
        ),
        encoding="utf-8",
    )
    assert [row["id"] for row in loop._read_events_jsonl(limit=10)] == ["event-1"]

    monkeypatch.setattr(loop.sqlite3, "connect", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db unavailable")))
    assert loop._read_events_sqlite(limit=2) == []

    assert loop._first_json_object("") is None
    assert loop._first_json_object("[1, 2]") is None
    assert loop._first_json_object("prefix {\"reply\":\"ok\", \"nested\":{\"a\":\"}\"}} suffix") == {"reply": "ok", "nested": {"a": "}"}}
    assert loop._first_json_object("prefix {\"reply\":\"unterminated\"") is None
    assert loop._first_json_object("prefix {bad json}") is None
    assert loop._first_json_object("no object here") is None

    assert loop._sanitize_guest_triage_llm_reply("", "fallback") == "fallback"
    assert loop._sanitize_guest_triage_llm_reply("As an AI trainer, refund approved.", "fallback") == "fallback"
    assert loop._sanitize_guest_triage_llm_reply("Safe reply. " * 80, "fallback") == ("Safe reply. " * 80)[:520]
    assert loop._conversational_guest_reply("refund", "refund_request", "", {}) == "I hear that you want help with a refund review."
    assert loop._conversational_guest_reply(
        "refund",
        "refund_request",
        "I hear that you want help with a refund review. Please visit Guest Services.",
        {},
    ).endswith("Guest Services.")

    assert loop._guest_message_acknowledgement("Where is vegetarian food?", "profile_information_request", {"category": "food_dietary"}) == "You are looking for vegetarian food options in the park."
    assert loop._guest_message_acknowledgement("Where is vegetarian food near the coaster?", "profile_information_request", {"category": "food_dietary"}) == "You are looking for vegetarian food near the coaster."
    assert loop._guest_message_acknowledgement("Need water", "profile_information_request", {"category": "water_cooling_quiet"}).startswith("You are looking")
    assert loop._guest_message_acknowledgement("Need map", "profile_information_request", {"category": "accessibility_map"}).startswith("You are asking")
    assert loop._guest_message_acknowledgement("Need info", "profile_information_request", {"category": "unknown"}).startswith("You are asking")
    assert loop._guest_message_acknowledgement("refund please", "refund_request", {}) == "I hear that you want help with a refund review."
    assert loop._guest_message_acknowledgement("missing child", "lost_child_report", {}) == "I understand you cannot find your child."
    assert loop._guest_message_acknowledgement("dizzy", "heat_exhaustion_concern", {}).startswith("I understand")
    assert loop._guest_message_acknowledgement("line cut", "line_cutting_conflict", {}).startswith("I hear")
    assert loop._guest_message_acknowledgement("storm", "weather_evacuation_confusion", {}).startswith("I hear")
    assert loop._guest_message_acknowledgement("translate", "language_barrier", {}).startswith("I hear")
    assert loop._guest_message_acknowledgement("custom", "unclear_guest_request", {}) == "I hear what you are asking for."

    version_events = [
        {"event": "learning_version_promoted", "version_id": "v1", "scenario_id": "refund_request", "target_surface": "staff_training"},
        {"event": "learning_version_promoted", "version_id": "v2", "scenario_id": "refund_request", "target_surface": "staff_training"},
    ]
    assert loop._active_version_for_scope(version_events, "refund_request", "staff_training") == "v2"
    assert loop._active_version_for_scope(version_events, "refund_request", "staff_training", exclude_version_id="v2") is None
    rolled_back_events = [
        *version_events,
        {"event": "learning_version_rolled_back", "version_id": "v2", "scenario_id": "refund_request", "target_surface": "staff_training"},
        {"event": "learning_version_promoted", "version_id": "", "scenario_id": "refund_request", "target_surface": "staff_training"},
        {"event": "learning_version_promoted", "version_id": "other", "scenario_id": "lost_child_report", "target_surface": "staff_training"},
    ]
    assert loop._active_version_for_scope(rolled_back_events, "refund_request", "staff_training") is None
    assert loop._learning_version_outcome_metrics("v-empty", [])["measurement_status"] == "pending"
    improving = loop._learning_version_outcome_metrics(
        "v-good",
        [
            {"event": "learning_version_outcome_recorded", "version_id": "v-good", "overall": 86, "critical_miss": False, "training_gap_created": False, "session_id": "s1"},
            {"event": "learning_version_outcome_recorded", "version_id": "v-good", "overall": 80, "critical_miss": False, "training_gap_created": False, "session_id": "s2"},
        ],
    )
    assert improving["measurement_status"] == "improving"
    regressed = loop._learning_version_outcome_metrics(
        "v-bad",
        [
            {"event": "learning_version_outcome_recorded", "version_id": "v-bad", "overall": 50, "critical_miss": True, "training_gap_created": True, "session_id": "s3"},
        ],
    )
    assert regressed["measurement_status"] == "regressed_auto_rollback"


def test_product_learning_gemini_worker_timeout_and_error_branches(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)
    calls = []

    def run_success(args, **kwargs):
        calls.append((args, kwargs))
        return types.SimpleNamespace(returncode=0, stdout=json.dumps({"ok": True, "reply": "ready"}), stderr="")

    monkeypatch.setattr(loop.subprocess, "run", run_success)
    payload = loop._generate_gemini_json_sync_hard_timeout(
        {"task": "triage"},
        timeout_seconds=0.1,
        max_output_tokens=32,
        temperature=0.0,
    )
    assert payload["reply"] == "ready"
    assert calls[0][1]["check"] is False
    assert json.loads(calls[0][1]["input"])["timeout_seconds"] == 0.1

    monkeypatch.setattr(
        loop.subprocess,
        "run",
        lambda *args, **kwargs: types.SimpleNamespace(returncode=2, stdout="", stderr="worker failed"),
    )
    try:
        loop._generate_gemini_json_sync_hard_timeout({}, timeout_seconds=0.1, max_output_tokens=8, temperature=0.0)
        assert False, "expected nonzero worker exit to raise"
    except RuntimeError as error:
        assert "worker failed" in str(error)

    monkeypatch.setattr(
        loop.subprocess,
        "run",
        lambda *args, **kwargs: types.SimpleNamespace(returncode=0, stdout="{bad", stderr=""),
    )
    try:
        loop._generate_gemini_json_sync_hard_timeout({}, timeout_seconds=0.1, max_output_tokens=8, temperature=0.0)
        assert False, "expected invalid worker JSON to raise"
    except RuntimeError as error:
        assert "invalid JSON" in str(error)

    monkeypatch.setattr(
        loop.subprocess,
        "run",
        lambda *args, **kwargs: types.SimpleNamespace(returncode=0, stdout=json.dumps({"ok": False, "error": "provider down"}), stderr=""),
    )
    try:
        loop._generate_gemini_json_sync_hard_timeout({}, timeout_seconds=0.1, max_output_tokens=8, temperature=0.0)
        assert False, "expected provider failure payload to raise"
    except RuntimeError as error:
        assert "provider down" in str(error)

    def run_timeout(*args, **kwargs):
        raise loop.subprocess.TimeoutExpired(cmd=["gemini-worker"], timeout=0.6)

    monkeypatch.setattr(loop.subprocess, "run", run_timeout)
    try:
        loop._generate_gemini_json_sync_hard_timeout({}, timeout_seconds=0.1, max_output_tokens=8, temperature=0.0)
        assert False, "expected timeout to raise"
    except TimeoutError as error:
        assert "hard timeout" in str(error)


def test_historical_park_ticket_source_dedupes_and_feeds_training_frequency(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)
    try:
        import mongo_memory

        monkeypatch.setattr(mongo_memory, "get_latest_memory_documents", lambda *args, **kwargs: [])
    except Exception:
        pass

    first = loop.create_park_issue_ticket(
        source="historical_park_data",
        issue_type="refund_request",
        summary="Historical pattern: refund desk backed up after ride closure.",
        severity="high",
        location="Guest Services",
        source_batch_id="audit-load-2026-06",
        historical_window="last_30_operating_days",
        observed_at="2026-06-01T18:00:00Z",
        stable_key="historical-refund-closure-wave",
    )
    second = loop.create_park_issue_ticket(
        source="historical_park_data",
        issue_type="refund_request",
        summary="Edited wording should not duplicate the same historical pattern.",
        severity="high",
        location="Guest Services",
        source_batch_id="audit-load-2026-06",
        historical_window="last_30_operating_days",
        observed_at="2026-06-01T18:00:00Z",
        stable_key="historical-refund-closure-wave",
    )
    status = loop.product_learning_loop_status()
    memory = loop.guest_triage_training_memory("refund_request")

    assert first["status"] == "created"
    assert first["ticket"]["id"] == second["ticket"]["id"]
    assert first["ticket"]["source"] == "historical_park_data"
    assert first["ticket"]["dedupe_key"] == first["ticket"]["id"]
    assert status["park_issue_ticket_count"] == 1
    assert memory["scenario_frequencies"][0]["scenario_id"] == "refund_request"
    assert memory["scenario_frequencies"][0]["ticket_count"] == 1
    assert memory["scenario_frequencies"][0]["sources"]["local_historical_park_data_ticket"] == 1


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


def test_low_attendance_suppresses_crowd_congestion_tickets(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)
    state = {
        "guestFlow": {
            "representedGuests": 181,
            "zones": [
                {"id": "entrancePlaza", "name": "Entrance Plaza", "currentGuests": 90, "density": 5},
                {"id": "coveredPlaza", "name": "Covered Plaza", "currentGuests": 91, "density": 5},
            ],
            "paths": [
                {
                    "from": "entrancePlaza",
                    "to": "coveredPlaza",
                    "fromName": "Entrance Plaza",
                    "toName": "Parade Route",
                    "widthM": 4.2,
                    "currentGuests": 181,
                    "congestionLevel": 91,
                }
            ],
        },
        "weather": {"stormRisk": 8, "heatIndexF": 78},
        "operatingClock": {
            "eventSchedule": {
                "activeWave": "parade_release",
                "eventTrafficRiskPct": 92,
                "nextEvent": {"name": "Afternoon parade"},
            }
        },
        "planningAgent": {"readinessPct": 90},
    }

    candidates = loop.generate_park_issue_tickets_from_park_state(state, seed="low-attendance-parade")
    assert candidates == []

    import agent_ops_ledger

    backlog = agent_ops_ledger.build_operational_backlog(state)
    issue_ids = {issue["id"] for issue in backlog["issues"]}
    assert "showtime-traffic-wave" not in issue_ids
    assert "safety-access-readiness" not in issue_ids
    assert "planning-horizon-risk" not in issue_ids


def test_supplied_place_risk_graph_cannot_bypass_low_attendance_gate(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)
    state = {
        "guestFlow": {"representedGuests": 181},
        "placeRiskGraph": {
            "places": [
                {
                    "id": "parade_pinch",
                    "name": "Parade Pinch",
                    "type": "path",
                    "currentLoad": 94,
                    "current_guests": 181,
                    "riskFactors": ["narrow_path", "crowd_bottleneck", "queue_merge_conflict"],
                    "evidence": ["pathCongestion=94", "currentGuests=181"],
                }
            ]
        },
    }

    graph = loop.build_place_risk_graph(state)
    tickets = loop.generate_park_issue_tickets_from_park_state(state, seed="configured-low-attendance")

    assert graph["places"][0]["risk_factors"] == []
    assert "crowdRiskSuppressedByAttendance=true" in graph["places"][0]["evidence"]
    assert tickets == []


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
    assert "requires_review_at:guest_services_refund_policy" in exceptions["refund_request"]["exception_reasons"]
    assert "requires_review_at:first_aid_station" in exceptions["heat_exhaustion_concern"]["exception_reasons"]
    assert exceptions["heat_exhaustion_concern"]["shadow_deployment"]["status"] == "blocked"
    assert status["auto_learning_governance"]["eval_contract"]["auto_promote_live_ops"] is False


def test_specific_review_places_block_only_named_exception_scopes(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)
    state = {
        "placeRiskGraph": {
            "places": [
                {
                    "id": "queue_merge_a",
                    "name": "Queue Merge A",
                    "currentLoad": 94,
                    "riskFactors": ["queue_merge_conflict"],
                    "evidence": ["pathCongestion=94", "mergeComplaints=4"],
                },
                {
                    "id": "queue_merge_b",
                    "name": "Queue Merge B",
                    "currentLoad": 91,
                    "riskFactors": ["queue_merge_conflict"],
                    "evidence": ["pathCongestion=91", "mergeComplaints=5"],
                },
                {
                    "id": "accessibility_detour",
                    "name": "Accessibility Detour",
                    "currentLoad": 83,
                    "riskFactors": ["misplaced_accessibility_route"],
                    "evidence": ["accessibleRouteBlocked=true"],
                },
            ]
        },
        "simTime": {"day": 1, "hour": 15, "minute": 20},
    }

    status = loop.product_learning_loop_status(park_state=state, incident_seed="review-place-test")
    auto = {candidate["scenario_id"]: candidate for candidate in status["auto_learning_candidates"]}
    exceptions = {candidate["scenario_id"]: candidate for candidate in status["human_exception_queue"]}

    assert "line_cutting_conflict" in auto
    assert auto["line_cutting_conflict"]["shadow_deployment"]["status"] == "shadow_ready"
    assert "accessibility_accommodation" in exceptions
    assert "requires_review_at:accessibility_lead" in exceptions["accessibility_accommodation"]["exception_reasons"]


def test_ticket_lifecycle_dedupes_repeated_backend_generated_tickets(monkeypatch, tmp_path):
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
                "id": "queue-merge-watch-a",
                "domain": "Ride Ops",
                "title": "Queue merge conflict complaints at mild threshold",
                "severity": "medium",
                "status": "unresolved",
                "current": "merge complaint cluster",
                "recommendedNext": "Clarify merge signage and staff script.",
                "evidence": ["mergeComplaints=3"],
            },
        ]
    }

    status = loop.product_learning_loop_status(operational_backlog=backlog)
    line_lifecycle = [item for item in status["ticket_lifecycle"] if item["issue_type"] == "line_cutting_conflict"]

    assert status["park_issue_ticket_count"] == 2
    assert status["deduped_park_issue_ticket_count"] == 1
    assert len(line_lifecycle) == 1
    assert line_lifecycle[0]["open_ticket_count"] == 2
    assert line_lifecycle[0]["lifecycle_status"] == "auto_evolve_ready"
    assert line_lifecycle[0]["dedupe_window_minutes"] == 120


def test_review_place_queues_group_specific_human_review_places(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)
    state = {
        "placeRiskGraph": {
            "places": [
                {
                    "id": "west_plaza",
                    "name": "West Plaza",
                    "currentLoad": 92,
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
                    "evidence": ["accessibleRouteBlocked=true"],
                },
            ]
        }
    }

    status = loop.product_learning_loop_status(park_state=state, incident_seed="review-queue-test")
    queues = {queue["review_place"]: queue for queue in status["review_place_queues"]}

    assert status["review_place_queue_count"] >= 3
    assert queues["first_aid_station"]["queue_status"] == "needs_human_review"
    assert "heat_exhaustion_concern" in queues["first_aid_station"]["issue_types"]
    assert queues["safety_command"]["auto_evolve_blocked"] is True
    assert "injury_or_safety_incident" in queues["safety_command"]["issue_types"]
    assert queues["accessibility_lead"]["required_action"].startswith("Review accommodation language")


def test_auto_draft_registry_and_promotion_queue_use_shadow_ready_candidates(monkeypatch, tmp_path):
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
    registry = {item["scenario_id"]: item for item in status["auto_draft_registry"]}
    metrics = {item["scenario_id"]: item for item in status["shadow_metrics"]}
    promotions = {item["scenario_id"]: item for item in status["promotion_queue"]}

    assert status["auto_draft_count"] >= 1
    assert registry["line_cutting_conflict"]["registry_status"] == "shadow_registered"
    assert registry["line_cutting_conflict"]["version_id"]
    assert metrics["line_cutting_conflict"]["promotion_eligible"] is True
    assert promotions["line_cutting_conflict"]["promotion_status"] == "ready_for_auto_promotion"
    assert promotions["line_cutting_conflict"]["can_promote_live_ops"] is False
    assert status["rollback_watchlist"][0]["watch_status"] == "armed"


def test_learning_version_promotion_and_rollback_persist_to_registry(monkeypatch, tmp_path):
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
    version_id = next(item["version_id"] for item in status["promotion_queue"] if item["scenario_id"] == "line_cutting_conflict")

    promoted = loop.promote_learning_version(version_id, operational_backlog=backlog, promoted_by="test-worker")
    promoted_status = loop.product_learning_loop_status(operational_backlog=backlog)
    active = {item["version_id"]: item for item in promoted_status["active_learning_versions"]}

    assert promoted["status"] == "promoted"
    assert promoted["version"]["live_ops_authority"] is False
    assert promoted["version"]["can_promote_live_ops"] is False
    assert version_id in active
    assert active[version_id]["registry_status"] == "active"
    assert active[version_id]["promotion_status"] == "active"
    assert promoted_status["active_learning_version_count"] == 1

    rolled_back = loop.rollback_learning_version(version_id, reason="staff score regression in shadow monitor")
    rollback_status = loop.product_learning_loop_status(operational_backlog=backlog)
    registry = {item["version_id"]: item for item in rollback_status["learning_version_registry"]}

    assert rolled_back["status"] == "rolled_back"
    assert rolled_back["version"]["can_rollback_live_ops"] is False
    assert registry[version_id]["registry_status"] == "rolled_back"
    assert registry[version_id]["rollback_reason"] == "staff score regression in shadow monitor"
    assert rollback_status["active_learning_version_count"] == 0
    assert rollback_status["rolled_back_learning_version_count"] == 1


def test_active_learning_version_feeds_roleplay_outcome_and_auto_rollback(monkeypatch, tmp_path):
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
                "id": "guest-recovery-pressure",
                "domain": "Guest Recovery",
                "title": "Guest recovery trust complaints repeated",
                "severity": "warning",
                "status": "unresolved",
                "current": "complaint risk 78%",
                "recommendedNext": "Use clearer family recovery script.",
                "evidence": ["complaintRiskPct=78"],
            },
        ]
    }
    status = loop.product_learning_loop_status(operational_backlog=backlog)
    version_id = next(item["version_id"] for item in status["promotion_queue"] if item["scenario_id"] == "angry_parent")

    promoted = loop.promote_learning_version(version_id, operational_backlog=backlog)
    assert promoted["status"] == "promoted"

    session = roleplay.start_staff_training_session("angry_parent", "Outcome QA")
    assert version_id in session["active_learning_version_ids"]
    assert session["scenario"]["learning_version_guidance"]

    finished = roleplay.finish_staff_training_session(session["id"])
    outcome = finished["learning_version_outcome"]
    rollback_status = loop.product_learning_loop_status(operational_backlog=backlog)
    registry = {item["version_id"]: item for item in rollback_status["learning_version_registry"]}

    assert outcome["status"] == "recorded"
    assert outcome["outcome_count"] == 1
    assert outcome["outcomes"][0]["outcome_metrics"]["measurement_status"] == "regressed_auto_rollback"
    assert outcome["auto_rollbacks"][0]["status"] == "rolled_back"
    assert registry[version_id]["registry_status"] == "rolled_back"
    assert registry[version_id]["outcome_metrics"]["session_count"] == 1
    assert registry[version_id]["outcome_metrics"]["average_overall"] == 0


def test_sqlite_event_store_indexes_product_learning_events(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)
    loop.create_park_issue_ticket(source="employee", issue_type="angry_parent", summary="Parent complaint near merge.", severity="medium")

    store = loop.product_learning_event_store_status()

    assert store["mode"] == "sqlite_event_store_with_jsonl_compatibility"
    assert os.path.exists(store["sqlite_path"])
    assert store["sqlite_event_count"] == 1
    assert "event_type" in store["indexes"]
    assert store["event_type_counts"]["park_issue_ticket_created"] == 1


def test_guest_message_triage_scores_urgency_and_creates_gated_ticket(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)

    result = loop.triage_guest_message(
        message="I cannot find my six-year-old. She was beside me near the carousel and now she is gone.",
        guest_name="Parent",
        location="Carousel",
        channel="sms",
    )
    status = loop.product_learning_loop_status()

    assert result["status"] == "triaged"
    assert result["classification"]["issue_type"] == "lost_child_report"
    assert result["classification"]["urgency"] == "critical"
    assert result["classification"]["urgency_score"] >= 90
    assert result["routing"]["assigned_team"] == "security"
    assert result["routing"]["human_ack_required"] is True
    assert result["ticket_result"]["ticket"]["live_ops_authority"] is True
    assert result["reaction"]["guest_reply_draft"].startswith("I understand your child is missing near the carousel.")
    assert "Stay with me" in result["reaction"]["guest_reply_draft"]
    assert any(ticket["issue_type"] == "lost_child_report" for ticket in status["park_issue_tickets"])
    assert any(event.get("event") == "guest_message_triaged" for event in loop._read_events(20))


def test_guest_message_triage_keeps_accessibility_context_out_of_injury(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)

    result = loop.triage_guest_message(
        message="My father cannot stand in this sun for the queue. We need accessibility help but do not want to explain medical history in public.",
        location="Coaster queue",
    )

    assert result["classification"]["issue_type"] == "accessibility_accommodation"
    assert result["classification"]["urgency"] == "high"
    assert result["routing"]["assigned_team"] == "accessibility"
    assert result["reaction"]["guest_reply_draft"].startswith("I hear that your group needs accessibility help without sharing private medical details.")
    assert "You do not need to share private medical details" in result["reaction"]["guest_reply_draft"]


def test_guest_message_triage_answers_park_profile_questions(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)
    monkeypatch.setattr(
        loop,
        "_load_guest_triage_venue_profile",
        lambda: {
            "venueIdentity": {"name": "Demo Park", "profileType": "test_profile"},
            "readiness": {"status": "studio_ready"},
            "realInputs": {
                "locationDetails": {
                    "Food Court A": {"name": "Food Court A", "kind": "food", "dietaryTags": ["vegetarian options", "kids meals"]},
                    "Coaster Plaza": {"name": "Coaster Plaza", "kind": "attraction"},
                },
                "agentContext": {"knownGaps": ["live restaurant inventory not connected"]},
            },
        },
    )

    result = loop.triage_guest_message(message="Where is the closest vegetarian food near the coaster?")

    assert result["classification"]["issue_type"] == "profile_information_request"
    assert result["understanding"]["status"] == "profile_grounded"
    assert result["profile_context"]["status"] == "answered_from_profile"
    assert result["profile_context"]["category"] == "food_dietary"
    assert result["profile_context"]["matched_locations"][0]["name"] == "Food Court A"
    assert result["reaction"]["guest_reply_draft"].startswith("You are looking for vegetarian food near the coaster.")
    assert "Food Court A" in result["reaction"]["guest_reply_draft"]
    assert result["routing"]["human_ack_required"] is False
    assert result["llm_response"]["reply"]
    assert result["llm_response"]["llm_controls_live_ops"] is False


def test_guest_message_triage_returns_mocked_llm_response(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)
    fake_props = types.SimpleNamespace(
        ready=True,
        provider="Vertex AI Gemini",
        platform="vertex_ai",
        readiness_issues=[],
        required_env=[],
    )

    monkeypatch.setattr(
        loop,
        "_load_guest_triage_venue_profile",
        lambda: {
            "venueIdentity": {"name": "Demo Park", "profileType": "test_profile"},
            "readiness": {"status": "studio_ready"},
            "realInputs": {
                "locationDetails": {
                    "Food Court A": {"name": "Food Court A", "kind": "food", "dietaryTags": ["vegetarian options"]},
                },
            },
        },
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "gemini_provider",
        types.SimpleNamespace(
            get_gemini_agent_properties=lambda: fake_props,
            get_gemini_model=lambda: "gemini-test",
        ),
    )
    captured = {}

    def fake_generate(prompt, *args, **kwargs):
        captured["prompt"] = prompt
        return {
            "text": json.dumps(
                {
                    "guest_reply": "You are looking for vegetarian food near the coaster. Food Court A has vegetarian options listed in the park profile. Please confirm live availability with a nearby team member.",
                    "tone": "calm",
                    "used_profile": True,
                    "next_step": "direct guest to Food Court A",
                    "confidence": 0.86,
                }
            ),
            "transport": "mocked_gemini",
        }

    monkeypatch.setattr(
        loop,
        "_generate_gemini_json_sync_hard_timeout",
        fake_generate,
    )

    result = loop.triage_guest_message(message="Where is the closest vegetarian food near the coaster?", create_ticket=False)

    assert result["llm_response"]["status"] == "generated"
    assert result["llm_response"]["source"] == "llm_guest_triage"
    assert result["llm_response"]["reply"].startswith("You are looking for vegetarian food near the coaster.")
    assert result["llm_response"]["used_profile"] is True
    assert result["llm_response"]["transport"] == "mocked_gemini"
    assert captured["prompt"]["guest_message"] == "Where is the closest vegetarian food near the coaster?"
    assert "guest's actual message" in " ".join(captured["prompt"]["hard_rules"])
    assert captured["prompt"]["required_conversational_opening"] == "You are looking for vegetarian food near the coaster."


def test_guest_message_triage_routes_unclear_niche_questions_to_human(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)
    monkeypatch.setattr(
        loop,
        "_load_guest_triage_venue_profile",
        lambda: {
            "venueIdentity": {"name": "Demo Park", "profileType": "test_profile"},
            "readiness": {"status": "studio_ready"},
            "realInputs": {"locationDetails": {}},
        },
    )

    result = loop.triage_guest_message(message="Can I bring a drone for filming behind the theater?")

    assert result["classification"]["issue_type"] == "unclear_guest_request"
    assert result["understanding"]["status"] == "needs_human_review"
    assert result["profile_context"]["status"] == "needs_human_review"
    assert result["profile_context"]["matched_locations"] == []
    assert result["routing"]["human_review_place"] == "guest_services_information_desk"
    assert result["routing"]["human_ack_required"] is True
    assert result["ticket_result"]["ticket"]["requires_human_ack"] is True
    assert result["reaction"]["guest_reply_draft"].startswith("I hear what you are asking for.")
    assert "I am not fully certain" in result["reaction"]["guest_reply_draft"]


def test_review_place_resolution_updates_human_review_queue(monkeypatch, tmp_path):
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
            }
        ]
    }
    before = loop.product_learning_loop_status(operational_backlog=backlog)
    assert next(queue for queue in before["review_place_queues"] if queue["review_place"] == "guest_services_refund_policy")["queue_status"] == "needs_human_review"

    resolution = loop.resolve_review_place_queue(
        "guest_services_refund_policy",
        decision="approve",
        notes="Approved for reviewed training/checklist learning only.",
        reviewer="QA manager",
        issue_types=["refund_request"],
    )
    after = loop.product_learning_loop_status(operational_backlog=backlog)
    queue = next(item for item in after["review_place_queues"] if item["review_place"] == "guest_services_refund_policy")

    assert resolution["status"] == "recorded"
    assert queue["queue_status"] == "resolved_approve"
    assert queue["auto_evolve_blocked"] is False
    assert queue["review_resolution"]["reviewer"] == "QA manager"
    assert after["human_review_resolutions"][0]["decision"] == "approve"


def test_active_ops_checklist_version_augments_operational_backlog(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)
    for index in range(4):
        loop.create_training_gap_ticket(
            scenario_id="line_cutting_conflict",
            gap_type="policy_correctness",
            severity="coaching",
            evidence={"score": 68 + index, "source": "ops-checklist-test"},
            trainee_name="Ops QA",
            session_id=f"ops-gap-{index}",
        )
    status = loop.product_learning_loop_status()
    version_id = next(item["version_id"] for item in status["promotion_queue"] if item["scenario_id"] == "line_cutting_conflict" and item["target_surface"] == "ops_checklist")
    promoted = loop.promote_learning_version(version_id)
    assert promoted["status"] == "promoted"

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
            }
        ]
    }
    augmented = loop.apply_active_ops_checklist_guidance(backlog)

    assert augmented["activeOpsChecklistGuidanceCount"] == 1
    issue = augmented["issues"][0]
    assert issue["productLearningIssueType"] == "line_cutting_conflict"
    assert issue["activeOpsChecklistVersions"][0]["version_id"] == version_id
    assert "Product learning checklist" in issue["recommendedNext"]
    assert augmented["productLearningOpsChecklistContract"]["live_ops_authority"] is False


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


def test_product_learning_api_promotes_and_rolls_back_learning_version(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)
    main._hot_endpoint_cache.pop("park_state_lite", None)

    async def fake_state_lite():
        return {"operatingClock": {"accessFairness": {"complaintRiskPct": 81}}}

    def fake_backlog(state):
        return {
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

    monkeypatch.setattr(main, "_fast_park_state_lite", fake_state_lite)
    import agent_ops_ledger

    monkeypatch.setattr(agent_ops_ledger, "build_operational_backlog", fake_backlog)
    ops_token = sign_role_session("test-ops", "ops_team", main._role_auth_secret())

    loop_status, payload = asyncio.run(_call_app("GET", "/api/park/product-learning/loop?limit=20", token=ops_token))
    assert loop_status == 200
    version_id = next(item["version_id"] for item in payload["promotion_queue"] if item["scenario_id"] == "line_cutting_conflict")

    promote_status, promoted = asyncio.run(
        _call_app(
            "POST",
            "/api/park/product-learning/promote-version",
            {"versionId": version_id, "promotedBy": "api-test"},
            token=ops_token,
        )
    )
    assert promote_status == 200
    assert promoted["status"] == "promoted"
    assert promoted["version"]["can_promote_live_ops"] is False

    loop_status, after_promote = asyncio.run(_call_app("GET", "/api/park/product-learning/loop?limit=80", token=ops_token))
    assert loop_status == 200
    assert any(item["version_id"] == version_id for item in after_promote["active_learning_versions"])

    rollback_status, rolled_back = asyncio.run(
        _call_app(
            "POST",
            "/api/park/product-learning/rollback-version",
            {"versionId": version_id, "reason": "api test rollback"},
            token=ops_token,
        )
    )
    assert rollback_status == 200
    assert rolled_back["status"] == "rolled_back"
    assert rolled_back["version"]["can_rollback_live_ops"] is False


def test_guest_message_triage_api_route(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)
    worker_token = sign_role_session("test-worker", "onsite_worker", main._role_auth_secret())

    route_status, payload = asyncio.run(
        _call_app(
            "POST",
            "/api/park/guest-message-triage",
            {"message": "My friend is dizzy and looks pale in the sun. I think she might faint.", "location": "West Plaza"},
            token=worker_token,
        )
    )

    assert route_status == 200
    assert payload["status"] == "triaged"
    assert payload["classification"]["issue_type"] == "heat_exhaustion_concern"
    assert payload["routing"]["human_ack_required"] is True
    assert payload["ticket_result"]["ticket"]["issue_type"] == "heat_exhaustion_concern"
    assert payload["reaction"]["forbidden_auto_actions"]


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

    historical_status, historical = asyncio.run(
        _call_app(
            "POST",
            "/api/park/product-learning/issue-ticket",
            {
                "source": "historical_park_data",
                "issueType": "refund_request",
                "summary": "Historical import: refund request spike after ride downtime.",
                "sourceBatchId": "api-history-load",
                "historicalWindow": "last_30_operating_days",
                "stableKey": "api-history-refund-spike",
            },
            token=worker_token,
        )
    )
    assert historical_status == 200
    assert historical["ticket"]["source"] == "historical_park_data"
    assert historical["ticket"]["dedupe_key"] == historical["ticket"]["id"]

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
    assert payload["park_issue_ticket_count"] >= 2
    assert any(
        ticket.get("issue_type") == "heat_exhaustion_concern"
        for ticket in payload["park_issue_tickets"]
    )
    assert any(
        ticket.get("source") == "historical_park_data" and ticket.get("issue_type") == "refund_request"
        for ticket in payload["park_issue_tickets"]
    )
    assert payload["training_gap_ticket_count"] == 1
    assert payload["learning_signal_count"] >= 1
