from __future__ import annotations

import asyncio

import live_feedback_loop
from live_feedback_loop import ingest_live_feed_event, live_feed_health, live_feed_storage_status, normalize_live_feed_event, record_review_decision, review_training_ledger


def test_normalize_live_feed_event_has_stable_contract():
    event = normalize_live_feed_event(
        {
            "source": "ride",
            "source_event_id": "ride-1",
            "observed_at": "2026-05-31T12:00:00Z",
            "received_at": "2026-05-31T12:00:15Z",
            "entity_type": "ride",
            "entity_id": "dragon",
            "signal_type": "wait_time",
            "value": 72,
            "confidence": 0.92,
            "raw_payload_ref": "ride-api/ride-1",
        }
    )

    assert event["source"] == "ride_ops"
    assert event["freshness_seconds"] == 15
    assert event["status"] == "accepted"
    assert event["normalized_by"] == "parkpulse_live_feedback_loop_v1"


def test_low_confidence_safety_event_creates_review_case(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_LIVE_FEED_EVENT_LOG_PATH", str(tmp_path / "feeds.jsonl"))
    monkeypatch.setenv("PARKPULSE_REVIEW_LEDGER_LOG_PATH", str(tmp_path / "reviews.jsonl"))

    result = ingest_live_feed_event(
        {
            "source": "operator",
            "source_event_id": "note-1",
            "entity_type": "zone",
            "entity_id": "foodCourt1",
            "signal_type": "medical_staff_note",
            "value": {"note": "Guest fainted near first aid corridor."},
            "confidence": 0.61,
            "raw_payload_ref": "operator-note/note-1",
        }
    )
    ledger = review_training_ledger()

    assert result["review_case"]["priority"] == "critical"
    assert ledger["summary"]["open_count"] == 1
    assert ledger["rows"][0]["review_type"] == "feed_event_review"


def test_live_feed_health_uses_state_derived_events_when_no_persisted_feeds(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_LIVE_FEED_EVENT_LOG_PATH", str(tmp_path / "feeds.jsonl"))
    monkeypatch.setenv("PARKPULSE_REVIEW_LEDGER_LOG_PATH", str(tmp_path / "reviews.jsonl"))

    state = {
        "weather": {"heatIndexF": 91, "stormRisk": 0.2},
        "guestFlow": {
            "rides": [{"id": "dragon", "name": "Dragon Coaster", "waitMins": 54, "queueGuests": 620}],
            "zones": [{"id": "coasterPlaza", "name": "Coaster Plaza", "density": 82, "currentGuests": 2100}],
        },
        "staffing": {"scheduled": 140, "checkedIn": 132, "openCallouts": 3},
        "foodInventory": {
            "locations": [{"id": "pizza", "name": "Pizza Pier", "mobileOrderBacklog": 88, "pickupEtaMinutes": 24}]
        },
    }
    health = live_feed_health(state)

    assert health["summary"]["ready_feed_count"] == 5
    assert any(row["source"] == "ride_ops" and row["status"] == "ready" for row in health["feeds"])
    assert any(row["source"] == "operator_signal" and row["status"] == "missing" for row in health["feeds"])


def test_record_review_decision_keeps_reward_boundary(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_REVIEW_LEDGER_LOG_PATH", str(tmp_path / "reviews.jsonl"))

    result = record_review_decision({"case_id": "review_1", "decision": "approved", "reviewer": "ops_lead"})
    ledger = review_training_ledger()

    assert result["review"]["status"] == "closed"
    assert ledger["summary"]["training_candidate_count"] == 1
    assert ledger["rows"][0]["llm_used_for_reward_or_label"] is False


def test_review_decision_closes_feed_review_case(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_LIVE_FEED_EVENT_LOG_PATH", str(tmp_path / "feeds.jsonl"))
    monkeypatch.setenv("PARKPULSE_REVIEW_LEDGER_LOG_PATH", str(tmp_path / "reviews.jsonl"))

    result = ingest_live_feed_event(
        {
            "source": "operator",
            "source_event_id": "note-2",
            "entity_type": "zone",
            "entity_id": "entrancePlaza",
            "signal_type": "security_staff_note",
            "value": {"note": "Security needs another check near the entrance."},
            "confidence": 0.8,
            "raw_payload_ref": "operator-note/note-2",
        }
    )
    case_id = result["review_case"]["id"]
    assert review_training_ledger()["summary"]["open_count"] == 1

    result = record_review_decision({"case_id": case_id, "decision": "escalate", "reviewer": "ops_lead"})
    ledger = review_training_ledger()

    assert result["review"]["status"] == "closed"
    assert ledger["summary"]["open_count"] == 0
    assert ledger["summary"]["closed_count"] == 1
    assert ledger["closed_reviews"][0]["disposition"]["decision"] == "escalate"


def test_operator_policy_boilerplate_does_not_create_sensitive_review(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_LIVE_FEED_EVENT_LOG_PATH", str(tmp_path / "feeds.jsonl"))
    monkeypatch.setenv("PARKPULSE_REVIEW_LEDGER_LOG_PATH", str(tmp_path / "reviews.jsonl"))

    result = ingest_live_feed_event(
        {
            "source": "operator_signal",
            "source_event_id": "guest-care-boilerplate",
            "entity_type": "guest_care",
            "entity_id": "park_guest_care",
            "signal_type": "guest_care",
            "value": {
                "open_cases": 7,
                "complaint_rate_pct": 4.5,
                "policy": "Aggregate only; no named guests, payment data, medical details, or compensation promises.",
                "sensitive_report": False,
                "top_drivers": ["queue exit confusion"],
            },
            "confidence": 0.88,
            "raw_payload_ref": "runtime://park_state/guestCare",
        }
    )

    assert result.get("review_case") is None
    assert review_training_ledger()["summary"]["open_count"] == 0


def test_live_feed_storage_uses_mongo_when_forced(tmp_path, monkeypatch):
    monkeypatch.delenv("PARKPULSE_LIVE_FEED_EVENT_LOG_PATH", raising=False)
    monkeypatch.delenv("PARKPULSE_REVIEW_LEDGER_LOG_PATH", raising=False)
    monkeypatch.setenv("PARKPULSE_LIVE_FEED_STORAGE", "mongodb")
    monkeypatch.setenv("MONGODB_URI", "mongodb://example.test/parkpulse")
    rows = {"live_feed_events": [], "live_review_ledger": []}

    def fake_write(collection, row):
        rows[collection].insert(0, row)
        return True

    def fake_read(collection, limit=500):
        return rows[collection][:limit]

    monkeypatch.setattr(live_feedback_loop, "_write_mongo_document", fake_write)
    monkeypatch.setattr(live_feedback_loop, "_read_mongo_documents", fake_read)

    ingest_live_feed_event(
        {
            "source": "operator_signal",
            "source_event_id": "mongo-signal-1",
            "entity_type": "guest_care",
            "entity_id": "park_guest_care",
            "signal_type": "guest_care",
            "value": {"open_cases": 3, "sensitive_report": False},
            "confidence": 0.9,
            "raw_payload_ref": "test://mongo",
        }
    )

    health = live_feed_health({"weather": {}, "guestFlow": {}, "staffing": {}, "foodInventory": {}})

    assert rows["live_feed_events"]
    assert live_feed_storage_status()["shared_across_instances"] is True
    assert health["storage"]["mode"] == "mongodb"
    assert any(row["source"] == "operator_signal" and row["status"] == "ready" for row in health["feeds"])


def test_full_runtime_refresh_stale_supervisor_loads_missing_operator_signal(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_LIVE_FEED_EVENT_LOG_PATH", str(tmp_path / "feeds.jsonl"))
    monkeypatch.setenv("PARKPULSE_REVIEW_LEDGER_LOG_PATH", str(tmp_path / "reviews.jsonl"))

    import parkpulse_api

    parkpulse_api._live_feed_health_cache.clear()
    assert any(getattr(route, "path", "") == "/api/park/live-feeds/refresh-stale" for route in parkpulse_api.app.routes)

    state = {
        "weather": {"heatIndexF": 91, "stormRisk": 0.15},
        "guestFlow": {
            "rides": [{"id": "dragon", "name": "Dragon Coaster", "waitMins": 54, "queueGuests": 620}],
            "zones": [{"id": "coasterPlaza", "name": "Coaster Plaza", "density": 82, "currentGuests": 2100}],
        },
        "staffing": {"scheduled": 140, "checkedIn": 132, "openCallouts": 3},
        "foodInventory": {
            "locations": [{"id": "pizza", "name": "Pizza Pier", "mobileOrderBacklog": 88, "pickupEtaMinutes": 24}]
        },
        "guestCare": {
            "openCases": 7,
            "complaintRatePct": 4.5,
            "topDrivers": ["queue_exit_confusion"],
            "policy": "Aggregate only; no named guests or compensation promises.",
        },
    }

    class FakeParkSimulation:
        async def get_state_lite(self):
            return state

    monkeypatch.setattr(parkpulse_api, "park_simulation", FakeParkSimulation())

    result = asyncio.run(
        parkpulse_api.park_live_feeds_refresh_stale(
            {"sources": ["operator_signal"], "stale_only": True, "refresh_margin_seconds": 20}
        )
    )

    assert result["status"] == "refreshed"
    assert result["mode"] == "live_feed_refresh_supervisor"
    assert result["refreshed_sources"] == ["operator_signal"]
    assert result["result_count"] == 1
    assert result["readiness_issues"] == []
    assert any(row["source"] == "operator_signal" and row["status"] == "ready" for row in result["after_feeds"])


def test_full_runtime_refresh_stale_supervisor_queues_weather(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_LIVE_FEED_EVENT_LOG_PATH", str(tmp_path / "feeds.jsonl"))
    monkeypatch.setenv("PARKPULSE_REVIEW_LEDGER_LOG_PATH", str(tmp_path / "reviews.jsonl"))

    import parkpulse_api

    parkpulse_api._live_feed_health_cache.clear()

    class FakeParkSimulation:
        async def get_state(self):
            return {"weather": {"heatIndexF": 91, "stormRisk": 0.15}}

        async def get_state_lite(self):
            return {"weather": {"heatIndexF": 91, "stormRisk": 0.15}}

    queued = []
    monkeypatch.setattr(parkpulse_api, "park_simulation", FakeParkSimulation())
    monkeypatch.setattr(parkpulse_api, "_queue_live_weather_refresh", lambda reason="test": queued.append(reason) or {"status": "queued", "mode": "live_weather_feed_background_refresh"})

    result = asyncio.run(
        parkpulse_api.park_live_feeds_refresh_stale(
            {"sources": ["weather"], "stale_only": False, "refresh_margin_seconds": 20}
        )
    )

    assert result["status"] == "queued"
    assert result["refreshed_sources"] == []
    assert result["queued_sources"] == ["weather"]
    assert result["results"]["weather"]["status"] == "queued"
    assert queued == ["stale_feed_supervisor"]


def test_full_runtime_live_feed_health_uses_short_ttl_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_LIVE_FEED_EVENT_LOG_PATH", str(tmp_path / "feeds.jsonl"))
    monkeypatch.setenv("PARKPULSE_REVIEW_LEDGER_LOG_PATH", str(tmp_path / "reviews.jsonl"))
    monkeypatch.setenv("PARKPULSE_LIVE_FEED_HEALTH_CACHE_TTL_SECONDS", "3")

    import parkpulse_api

    calls = {"count": 0}

    class FakeParkSimulation:
        async def get_state(self):
            calls["count"] += 1
            return {"weather": {"heatIndexF": 91, "stormRisk": 0.15}}

    parkpulse_api._live_feed_health_cache.clear()
    monkeypatch.setattr(parkpulse_api, "park_simulation", FakeParkSimulation())

    first = asyncio.run(parkpulse_api.park_live_feed_health(limit=500))
    second = asyncio.run(parkpulse_api.park_live_feed_health(limit=500))

    assert first["cache"]["status"] == "miss"
    assert second["cache"]["status"] == "hit"
    assert calls["count"] == 1


def test_live_feed_orchestration_enriches_department_tool_proposals():
    import parkpulse_api

    role_agent_proposals = {
        "proposals": [
            {
                "agent_id": "ride_ops_agent",
                "department": "operations",
                "requested_tool": "recommend_route_change",
                "recommendation": "Move guests away from the blocked ride path.",
                "evidence": ["scenario=ride_down"],
                "proposal_envelope": {
                    "requested_tool": "recommend_route_change",
                    "executor_agent": "tool_executor_agent",
                    "executor_status": "awaiting_executive",
                },
            }
        ]
    }
    live_feed_case = {
        "evidence": [
            {
                "source": "ride_ops",
                "signal_type": "capacity",
                "event_id": "feed-ride-1",
                "confidence": 0.91,
                "age_seconds": 3,
                "summary": "Dragon Coaster capacity pressure rising.",
            },
            {
                "source": "guest_flow",
                "signal_type": "crowd_density",
                "event_id": "feed-flow-1",
                "confidence": 0.87,
                "age_seconds": 5,
                "summary": "Coaster Plaza density elevated.",
            },
        ]
    }

    enriched = parkpulse_api._enrich_role_proposals_with_live_feed(role_agent_proposals, live_feed_case)
    proposal = enriched["proposals"][0]
    envelope = proposal["proposal_envelope"]

    assert enriched["orchestration_source"] == "live_feed"
    assert enriched["live_feed_grounded_proposal_count"] == 1
    assert enriched["cooperation_graph"]["mode"] == "live_feed_department_cooperation"
    assert proposal["live_feed_grounding"]["event_ids"] == ["feed-ride-1", "feed-flow-1"]
    assert envelope["live_feed_event_ids"] == ["feed-ride-1", "feed-flow-1"]
    assert envelope["policy_check"] == "pending_policy_gate"
    assert envelope["evidence"][0].startswith("live_feed:ride_ops:capacity:event=feed-ride-1")


def test_live_feed_native_department_proposals_cover_enterprise_departments():
    from park_multi_agent import build_role_agent_proposals
    from venue_profile import build_venue_profile

    state = {
        "weather": {"heatIndexF": 88, "stormRisk": 0.1},
        "guestFlow": {
            "activeScenario": {"key": "ride_down"},
            "rides": [{"id": "dragon", "name": "Dragon Coaster", "status": "delayed", "waitMins": 64}],
            "zones": [{"id": "coasterPlaza", "name": "Coaster Plaza", "density": 82, "processType": "ride"}],
            "paths": [{"id": "mainPath", "congestionLevel": 74}],
        },
        "staffing": {"scheduled": 140, "checkedIn": 134, "openCallouts": 4},
    }
    live_feed_case = {
        "lead_source": "ride_ops",
        "lead_signal_type": "capacity",
        "evidence": [
            {"source": "ride_ops", "signal_type": "capacity", "event_id": "feed-ride", "confidence": 0.91, "age_seconds": 2, "summary": "Ride pressure rising."},
            {"source": "guest_flow", "signal_type": "density", "event_id": "feed-flow", "confidence": 0.89, "age_seconds": 4, "summary": "Density elevated."},
            {"source": "staffing", "signal_type": "coverage", "event_id": "feed-staff", "confidence": 0.88, "age_seconds": 5, "summary": "Staff coverage stable."},
            {"source": "food_ops", "signal_type": "inventory", "event_id": "feed-food", "confidence": 0.87, "age_seconds": 6, "summary": "Food demand increasing."},
            {"source": "operator_signal", "signal_type": "guest_care", "event_id": "feed-ops", "confidence": 0.86, "age_seconds": 7, "summary": "Guest care reports confusion."},
            {"source": "weather", "signal_type": "heat_index", "event_id": "feed-weather", "confidence": 0.85, "age_seconds": 8, "summary": "Heat normal."},
        ],
    }

    result = build_role_agent_proposals(
        state,
        {"route": "live_feed_department_cooperation", "orchestration_source": "live_feed", "scenario_key": "ride_down"},
        None,
        {"live_feed_case": live_feed_case, "orchestration_source": "live_feed", "park_profile": build_venue_profile()},
    )

    assert result["mode"] == "live_feed_native_department_proposals"
    assert result["proposal_count"] >= 12
    assert {"security", "finance", "marketing", "compliance", "qa_judge"} <= set(result["active_departments"])
    assert result["live_feed_grounded_proposal_count"] == result["proposal_count"]
    assert result["deep_reasoning_proposal_count"] == result["proposal_count"]
    assert result["park_profile_context_status"] == "attached"
    assert result["profile_context_proposal_count"] == result["proposal_count"]
    assert len(result["negotiation_rounds"]) >= 4
    assert len(result["tradeoff_matrix"]) == result["proposal_count"]
    assert result["negotiation_turns"]
    assert result["executive_tradeoff"]["decision"] == "approved_with_exclusions"
    assert len(result["executive_tradeoff"]["tradeoff_matrix"]) == result["proposal_count"]
    assert all(proposal["generated_from"] == "live_feed_case" for proposal in result["proposals"])
    assert all(not proposal["proposal_envelope"]["policy_check"].startswith("pending") for proposal in result["proposals"])
    for proposal in result["proposals"]:
        reasoning = proposal["department_reasoning"]
        disposition = proposal["action_disposition"]
        profile_context = proposal["park_profile_context"]
        assert reasoning["diagnosis"]["evidence_count"] >= 1
        assert reasoning["evidence_argument"]
        assert "event" in reasoning["evidence_argument"]
        assert reasoning["evidence_snapshot"]
        assert len(reasoning["candidate_actions"]) >= 2
        assert all(candidate.get("evidence_basis") for candidate in reasoning["candidate_actions"])
        assert all("profile_counterfactual" in candidate for candidate in reasoning["candidate_actions"])
        assert reasoning["profile_counterfactual_summary"]["candidate_count"] >= 2
        assert reasoning["profile_counterfactual_summary"]["precedence"] == "live_feed_over_profile_policy_over_both"
        assert reasoning["forecast"]["expected_outcome"]
        assert len(reasoning["failure_modes"]) >= 2
        assert reasoning["selected_rationale"]
        assert disposition["decision"]
        assert disposition["next_owner"]
        assert disposition["exit_condition"]
        assert disposition["why_not_undecided"]
        assert disposition["evidence_argument"]
        assert disposition["live_feed_event_ids"]
        assert profile_context["status"] == "attached"
        assert profile_context["profile_fields_used"]
        assert profile_context["precedence"] == "live_feed_over_profile_policy_over_both"
        assert reasoning["park_profile_context"]["reasoning_effect"]
        assert set(["observe", "interpret", "predict", "recommend", "justify", "trace"]) <= set(proposal["agent_loop"])
    assert all(row.get("profile_counterfactual_score") is not None for row in result["tradeoff_matrix"])
    assert all(row.get("evidence_argument") for row in result["tradeoff_matrix"])
    assert all(row.get("live_feed_event_ids") for row in result["tradeoff_matrix"])


def test_controlled_live_feed_tool_executor_executes_only_approved_low_risk():
    import parkpulse_api
    from park_multi_agent import build_role_agent_proposals

    live_feed_case = {
        "lead_source": "ride_ops",
        "lead_signal_type": "capacity",
        "evidence": [
            {"source": "ride_ops", "signal_type": "capacity", "event_id": "feed-ride", "confidence": 0.91, "age_seconds": 2, "summary": "Ride pressure rising."},
            {"source": "guest_flow", "signal_type": "density", "event_id": "feed-flow", "confidence": 0.89, "age_seconds": 4, "summary": "Density elevated."},
            {"source": "staffing", "signal_type": "coverage", "event_id": "feed-staff", "confidence": 0.88, "age_seconds": 5, "summary": "Staff coverage stable."},
            {"source": "food_ops", "signal_type": "inventory", "event_id": "feed-food", "confidence": 0.87, "age_seconds": 6, "summary": "Food demand increasing."},
        ],
    }
    proposals = build_role_agent_proposals(
        {"guestFlow": {"activeScenario": {"key": "ride_down"}, "rides": [], "zones": [], "paths": []}, "staffing": {"openCallouts": 1}},
        {"route": "live_feed_department_cooperation", "orchestration_source": "live_feed", "scenario_key": "ride_down"},
        None,
        {"live_feed_case": live_feed_case, "orchestration_source": "live_feed"},
    )

    result = parkpulse_api._controlled_live_feed_tool_executor_run(
        {"role_agent_proposals": proposals, "decision_id": "decision-test"},
        execute=True,
    )
    follow = parkpulse_api._build_live_feed_hard_decision_follow_through(
        {"tool_executor_live_test": result, "decision_id": "decision-test"}
    )

    assert result["status"] == "executed"
    assert result["executed_count"] > 0
    assert result["held_count"] > 0
    assert result["held_disposition_count"] == result["held_count"]
    assert all(
        row["department"] not in {"safety", "security", "guest_experience", "maintenance"}
        for row in result["receipts"]
        if row["approved_for_controlled_executor"]
    )
    assert all(
        (row["action_disposition"]["next_owner"] and row["action_disposition"]["exit_condition"])
        for row in result["receipts"]
        if row["result"]["status"] == "held"
    )
    assert follow["status"] == "routed"
    assert follow["task_count"] == result["held_count"]
    assert follow["unresolved_without_owner_count"] == 0
    assert follow["active_follow_up_count"] > 0
    assert all(task["next_owner"] and task["exit_condition"] and task["fallback"] for task in follow["tasks"])
    assert all(task["review_inputs"]["live_feed_event_ids"] for task in follow["tasks"])
    assert all(row["live_feed_event_ids"] for row in result["receipts"])


def test_controlled_live_feed_receiver_delivery_proof_acknowledges_only_executed(monkeypatch):
    import parkpulse_api

    dispatch_payloads = []

    def fake_send_worker_notification(payload):
        dispatch_payloads.append(payload)
        return {
            "id": f"dispatch-{payload['department']}",
            "channel": "worker_device",
            "status": "delivered",
            "durable": True,
            "idempotencyKey": f"idem-{payload['department']}",
        }

    def fake_acknowledge(dispatch_id, *, actor, choice, channel=None):
        return {
            "id": dispatch_id,
            "status": "acknowledged",
            "lastAcknowledgement": {"actor": actor, "choice": choice, "channel": channel},
        }

    monkeypatch.setattr(parkpulse_api, "send_worker_notification", fake_send_worker_notification)
    monkeypatch.setattr(parkpulse_api, "acknowledge_dispatch", fake_acknowledge)
    monkeypatch.setattr(parkpulse_api, "delivery_outbox_status", lambda: {"ready": True, "durable_count": 1})

    result = parkpulse_api._controlled_live_feed_receiver_delivery_proof(
        {
            "decision_id": "decision-live-feed",
            "live_feed_case": {"live_feed_event_ids": ["feed-food"]},
            "tool_executor_live_test": {
                "receipts": [
                    {
                        "agent": "food_demand_agent",
                        "department": "food_retail",
                        "source_tool": "pause_launch_promo",
                        "policy_check": "passed_food_inventory_no_unavailable_promo",
                        "policy_status": "passed",
                        "result": {"status": "executed_controlled", "idempotency_key": "exec-food"},
                    },
                    {
                        "agent": "safety_policy_agent",
                        "department": "safety",
                        "source_tool": "require_human_approval",
                        "policy_check": "requires_human_approval_safety",
                        "policy_status": "requires_human_approval",
                        "result": {"status": "held", "reason": "Safety approval required."},
                    },
                ]
            },
        }
    )

    assert result["status"] == "proven_controlled"
    assert result["executed_count"] == 1
    assert result["delivered_count"] == 1
    assert result["acknowledged_count"] == 1
    assert result["held_count"] == 1
    assert result["public_guest_messages_sent"] == 0
    assert result["material_state_mutation"] is False
    assert len(dispatch_payloads) == 1
    assert dispatch_payloads[0]["department"] == "food_retail"
    assert dispatch_payloads[0]["publicGuestMessage"] is False
    assert any(row["status"] == "not_dispatched_policy_hold" for row in result["receipts"])


def test_live_feed_outcome_measurement_builds_reward_candidate_from_post_action_snapshot():
    import parkpulse_api

    result = parkpulse_api._build_live_feed_outcome_measurement(
        {
            "decision_id": "decision-live-feed",
            "live_feed_health": {
                "feeds": [
                    {
                        "source": "food_ops",
                        "latest_event_id": "before-food",
                        "latest_signal_type": "kitchen_load",
                        "age_seconds": 8,
                        "value": {"kitchen_load_pct": 99, "low_inventory_items": ["bottled_drinks"]},
                    },
                    {
                        "source": "guest_flow",
                        "latest_event_id": "before-flow",
                        "latest_signal_type": "routing_take_rate",
                        "age_seconds": 8,
                        "value": {"routing_take_rate_pct": 82, "avg_satisfaction": 70},
                    },
                    {
                        "source": "staffing",
                        "latest_event_id": "before-staff",
                        "latest_signal_type": "training_tag",
                        "age_seconds": 8,
                        "value": {"guard_team_count": 8, "health_team_count": 4},
                    },
                    {
                        "source": "ride_ops",
                        "latest_event_id": "before-ride",
                        "latest_signal_type": "capacity",
                        "age_seconds": 8,
                        "value": {"capacity_pressure_pct": 22, "down_ride_count": 1},
                    },
                    {
                        "source": "operator_signal",
                        "latest_event_id": "before-ops",
                        "latest_signal_type": "incident_report",
                        "age_seconds": 8,
                        "value": {"open_cases": 47},
                    },
                ]
            },
            "tool_executor_live_test": {
                "receipts": [
                    {"department": "food_retail", "result": {"status": "executed_controlled"}},
                    {"department": "hr_labor", "result": {"status": "executed_controlled"}},
                    {"department": "marketing", "result": {"status": "executed_controlled"}},
                    {"department": "safety", "result": {"status": "held"}},
                ]
            },
            "live_feed_receiver_delivery": {"status": "proven_controlled"},
        },
        {
            "status": "refreshed",
            "refreshed_sources": ["food_ops", "guest_flow", "staffing", "ride_ops", "operator_signal"],
            "after_feeds": [
                {
                    "source": "food_ops",
                    "latest_event_id": "after-food",
                    "latest_signal_type": "kitchen_load",
                    "age_seconds": 0,
                    "value": {"kitchen_load_pct": 97, "low_inventory_items": []},
                },
                {
                    "source": "guest_flow",
                    "latest_event_id": "after-flow",
                    "latest_signal_type": "routing_take_rate",
                    "age_seconds": 0,
                    "value": {"routing_take_rate_pct": 83, "avg_satisfaction": 71},
                },
                {
                    "source": "staffing",
                    "latest_event_id": "after-staff",
                    "latest_signal_type": "training_tag",
                    "age_seconds": 0,
                    "value": {"guard_team_count": 8, "health_team_count": 4},
                },
                {
                    "source": "ride_ops",
                    "latest_event_id": "after-ride",
                    "latest_signal_type": "capacity",
                    "age_seconds": 0,
                    "value": {"capacity_pressure_pct": 22, "down_ride_count": 1},
                },
                {
                    "source": "operator_signal",
                    "latest_event_id": "after-ops",
                    "latest_signal_type": "incident_report",
                    "age_seconds": 0,
                    "value": {"open_cases": 47},
                },
            ],
        },
    )

    assert result["status"] == "measured"
    assert result["measured_outcome_available"] is True
    assert result["eligible_for_reward"] is True
    assert result["reward_value"] is not None
    assert result["attribution_confidence"] >= 0.7
    assert result["source_coverage"] == 1
    assert result["department_coverage"] == 1
    assert {row["source"] for row in result["measurement_rows"]} >= {"food_ops", "guest_flow", "staffing"}


def test_live_feed_memory_priors_enrich_proposals_without_execution_rights():
    import parkpulse_api

    proposals = {
        "proposals": [
            {
                "agent_id": "food_demand_agent",
                "department": "food_retail",
                "evidence": ["live_feed:food_ops"],
                "department_reasoning": {
                    "candidate_actions": [{"action": "pause_launch_promo", "score": 0.81}],
                    "forecast": {"expected_outcome": "avoid stockout"},
                },
                "proposal_envelope": {"requested_tool": "pause_launch_promo"},
            },
            {
                "agent_id": "safety_policy_agent",
                "department": "safety",
                "evidence": ["live_feed:ride_ops"],
                "department_reasoning": {
                    "candidate_actions": [{"action": "require_human_approval", "score": 0.93}],
                    "forecast": {"expected_outcome": "protect safety gate"},
                },
                "proposal_envelope": {"requested_tool": "require_human_approval"},
            },
        ],
        "negotiation_turns": [],
    }
    memory_priors = {
        "status": "retrieved",
        "prior_count": 1,
        "priors": [
            {
                "outcome_id": "outcome-prior",
                "measurement_id": "measurement-prior",
                "executed_departments": ["food_retail"],
                "executed_tools": ["pause_launch_promo"],
                "reward_value": 0.91,
                "attribution_confidence": 0.88,
            }
        ],
        "latest_outcome_ids": ["outcome-prior"],
    }

    enriched = parkpulse_api._apply_live_feed_memory_priors_to_proposals(proposals, memory_priors)

    food = enriched["proposals"][0]
    safety = enriched["proposals"][1]
    assert enriched["memory_prior_use"]["status"] == "applied"
    assert enriched["memory_prior_use"]["applied_count"] == 1
    assert enriched["memory_prior_use"]["blocked_count"] == 1
    assert enriched["memory_prior_use"]["accepted_departments"] == ["food_retail"]
    assert enriched["memory_prior_use"]["blocked_departments"] == ["safety"]
    assert enriched["memory_prior_use"]["prior_outcome_ids"] == ["outcome-prior"]
    assert food["memory_use"]["prior_outcome_id"] == "outcome-prior"
    assert food["memory_use"]["status"] == "accepted"
    assert food["memory_use"]["used_for"] == "low_risk_execution_bias"
    assert food["memory_decision_delta"]["effect"] == "reinforced_selected_candidate"
    assert food["department_reasoning"]["memory_decision_delta"]["effect"] == "reinforced_selected_candidate"
    assert food["memory_relevance_judge"]["accepted_by_judge"] is True
    assert food["proposal_envelope"]["memory_prior_outcome_id"] == "outcome-prior"
    assert "memory_prior:outcome-prior:reward=0.91:confidence=0.88" in food["evidence"]
    assert safety["memory_use"]["prior_outcome_id"] == "outcome-prior"
    assert safety["memory_use"]["status"] == "blocked_policy_boundary"
    assert safety["memory_decision_delta"]["effect"] == "blocked_from_execution_bias"
    assert safety["memory_relevance_judge"]["accepted_by_judge"] is False
    assert "memory_prior:outcome-prior:reward=0.91:confidence=0.88" not in safety["evidence"]
    assert "memory_prior_outcome_id" not in safety["proposal_envelope"]
    assert enriched["negotiation_turns"][0]["agent"] == "memory_ops_agent"
    assert enriched["memory_decision_deltas"]


def test_live_feed_controlled_outcome_memory_records_existing_memory_shape(monkeypatch):
    import parkpulse_api

    recorded = {}

    def fake_record(outcome, decision_id, live_state=None):
        recorded["outcome"] = outcome
        recorded["decision_id"] = decision_id
        recorded["live_state"] = live_state
        return "outcome-live-feed"

    monkeypatch.setattr(parkpulse_api, "record_mongo_outcome_event", fake_record)

    result = parkpulse_api._record_live_feed_controlled_outcome_memory(
        {
            "decision_id": "decision-live-feed",
            "live_feed_case": {"lead_source": "ride_ops", "lead_signal_type": "capacity", "evidence": [{"event_id": "feed-1"}]},
            "role_agent_proposals": {
                "proposal_count": 2,
                "live_feed_grounded_proposal_count": 2,
                "live_feed_event_ids": ["feed-1"],
                "proposals": [{"policy_judge": {"status": "passed"}}, {"policy_judge": {"status": "requires_human_approval"}}],
            },
            "tool_executor_live_test": {
                "status": "executed",
                "executed_count": 1,
                "held_count": 1,
                "receipts": [
                    {"department": "food_retail", "source_tool": "pause_launch_promo", "result": {"status": "executed_controlled"}},
                    {"department": "safety", "source_tool": "require_human_approval", "result": {"status": "held"}},
                ],
            },
            "live_feed_receiver_delivery": {
                "status": "proven_controlled",
                "proof_id": "receiver-proof",
                "delivered_count": 1,
                "acknowledged_count": 1,
                "receipts": [
                    {
                        "department": "food_retail",
                        "source_tool": "pause_launch_promo",
                        "status": "delivered_and_acknowledged",
                        "dispatch_id": "dispatch-food",
                        "delivered": True,
                        "acknowledged": True,
                        "material_state_mutation": False,
                    }
                ],
            },
            "hard_decision_follow_through": {
                "status": "routed",
                "task_count": 1,
                "active_follow_up_count": 1,
                "unresolved_without_owner_count": 0,
                "tasks": [
                    {
                        "task_id": "hard-follow-safety",
                        "department": "safety",
                        "source_tool": "require_human_approval",
                        "status": "routed_to_owner",
                        "next_owner": "safety_lead",
                        "exit_condition": "Authorized safety lead approves.",
                        "fallback": "Keep blocked.",
                    }
                ],
            },
            "live_feed_outcome_measurement": {
                "status": "measured",
                "measurement_id": "measurement-proof",
                "measured_outcome_available": True,
                "eligible_for_reward": True,
                "reward_value": 0.82,
                "reward_label": "safe_controlled_handoff_with_measured_live_state",
                "attribution_confidence": 0.9,
                "measurement_rows": [{"source": "food_ops", "post_action_snapshot_captured": True, "metrics": []}],
            },
        }
    )

    assert result["status"] == "recorded"
    assert result["outcome_id"] == "outcome-live-feed"
    assert result["mongo_collection"] == "outcome_events"
    assert recorded["decision_id"] == "decision-live-feed"
    assert recorded["live_state"] is None
    assert recorded["outcome"]["mode"] == "live_feed_controlled_executor_outcome"
    assert recorded["outcome"]["response_metrics"]["receiverDeliveryProven"] is True
    assert recorded["outcome"]["response_metrics"]["measuredOutcomeAvailable"] is True
    assert recorded["outcome"]["response_metrics"]["rewardValue"] == 0.82
    assert recorded["outcome"]["state_impact"]["executed_departments"] == ["food_retail"]
    assert recorded["outcome"]["state_impact"]["held_departments"] == ["safety"]
    assert recorded["outcome"]["state_impact"]["hard_decision_follow_through_status"] == "routed"
    assert recorded["outcome"]["state_impact"]["active_follow_up_count"] == 1
    assert recorded["outcome"]["state_impact"]["hard_decision_follow_through_tasks"][0]["task_id"] == "hard-follow-safety"
    assert recorded["outcome"]["state_impact"]["receiver_delivery_proof_id"] == "receiver-proof"
    assert recorded["outcome"]["state_impact"]["post_action_measurement_id"] == "measurement-proof"
    assert recorded["outcome"]["scorecard"]["receiver_delivery"] == 100
    assert recorded["outcome"]["scorecard"]["post_action_measurement"] == 100
    assert recorded["outcome"]["learning"]["eligible_for_reward"] is True


def test_live_feed_training_closure_materializes_supervised_eval_only_and_dedupes_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_REVIEW_LEDGER_LOG_PATH", str(tmp_path / "reviews.jsonl"))

    from scripts.live_feed_training_closure import close_live_feed_training_loop

    payload = {
        "summary": {
            "status": "passed",
            "proposal_count": 2,
            "active_departments": ["food_retail", "safety"],
            "proposal_mode": "live_feed_native_department_proposals",
            "live_feed_grounded_proposal_count": 2,
            "concrete_policy_count": 2,
            "missing_policy_check_count": 0,
            "judge": {"trace_contract_present": True},
        },
        "live_feed_case": {"lead_source": "ride_ops", "lead_signal_type": "capacity"},
        "live_feed_cooperation": {"nodes": [{"id": "feed:ride_ops"}], "edges": [{"from": "feed:ride_ops", "to": "department:food_retail"}]},
        "role_agent_proposals": {
            "executive_tradeoff": {
                "decision": "approved_with_exclusions",
                "approved_departments": ["food_retail"],
                "held_departments": ["safety"],
                "reason": "Approve low-risk food action and hold safety approval.",
            },
            "conflicts": [],
            "negotiation_turns": [{"turn": 1, "agent": "decision_bridge_agent", "decision": "approved_with_exclusions"}],
            "proposals": [
                {
                    "agent_id": "food_demand_agent",
                    "department": "food_retail",
                    "recommendation": "Pause constrained promo.",
                    "proposal_envelope": {
                        "requested_tool": "pause_launch_promo",
                        "intent": "Pause constrained promo.",
                        "risk_level": "medium",
                        "policy_check": "passed_food_inventory_no_unavailable_promo",
                        "expected_outcome": "avoid stockout",
                        "rollback": "resume promo",
                        "executor_status": "ready_for_executor",
                    },
                    "policy_judge": {"status": "passed", "reason": "Food action is low risk."},
                    "live_feed_grounding": {"event_ids": ["feed-food"], "sources": ["food_ops"]},
                },
                {
                    "agent_id": "safety_policy_agent",
                    "department": "safety",
                    "recommendation": "Require approval.",
                    "proposal_envelope": {
                        "requested_tool": "require_human_approval",
                        "intent": "Require approval.",
                        "risk_level": "medium",
                        "policy_check": "requires_human_approval_safety",
                        "expected_outcome": "hold unsafe action",
                        "rollback": "release hold after lead approval",
                        "executor_status": "awaiting_human_approval",
                    },
                    "policy_judge": {"status": "requires_human_approval", "reason": "Safety-sensitive action."},
                    "live_feed_grounding": {"event_ids": ["feed-ride"], "sources": ["ride_ops"]},
                },
            ],
        },
        "tool_executor_live_test": {
            "status": "executed",
            "executed_count": 1,
            "held_count": 1,
            "receipts": [
                {
                    "agent": "food_demand_agent",
                    "department": "food_retail",
                    "source_tool": "pause_launch_promo",
                    "approved_for_controlled_executor": True,
                    "result": {"status": "executed_controlled", "executed": True, "idempotency_key": "idem-food"},
                },
                {
                    "agent": "safety_policy_agent",
                    "department": "safety",
                    "source_tool": "require_human_approval",
                    "approved_for_controlled_executor": False,
                    "result": {"status": "held", "executed": False, "reason": "Safety-sensitive action."},
                },
            ],
        },
        "live_feed_receiver_delivery": {
            "status": "proven_controlled",
            "proof_id": "receiver-proof",
            "executed_count": 1,
            "delivered_count": 1,
            "acknowledged_count": 1,
            "public_guest_messages_sent": 0,
            "material_state_mutation": False,
            "receipts": [
                {
                    "agent": "food_demand_agent",
                    "department": "food_retail",
                    "source_tool": "pause_launch_promo",
                    "status": "delivered_and_acknowledged",
                    "dispatch_id": "dispatch-food",
                    "delivered": True,
                    "acknowledged": True,
                    "material_state_mutation": False,
                }
            ],
        },
        "live_feed_outcome_measurement": {
            "status": "measured",
            "measurement_id": "measurement-proof",
            "measured_outcome_available": True,
            "attribution_confidence": 0.9,
            "eligible_for_reward": True,
            "reward_value": 0.82,
            "measurement_rows": [
                {
                    "source": "food_ops",
                    "before_event_id": "before-food",
                    "after_event_id": "after-food",
                    "post_action_snapshot_captured": True,
                    "metrics": [{"metric": "kitchen_load_pct", "before": 99, "after": 97, "delta": -2, "impact": "improved"}],
                }
            ],
        },
        "live_feed_outcome_memory": {
            "status": "recorded",
            "decision_id": "decision-live-feed",
            "outcome_id": "outcome-live-feed",
            "mongo_collection": "outcome_events",
            "outcome": {
                "mode": "live_feed_controlled_executor_outcome",
                "state_impact": {"controlled_executor_only": True},
                "response_metrics": {"receiverDeliveryProven": True, "measuredOutcomeAvailable": True, "rewardValue": 0.82},
                "scorecard": {"overall": 86, "receiver_delivery": 100, "post_action_measurement": 100},
                "learning": {
                    "eligible_for_reward": True,
                    "reward_label": "safe_controlled_handoff_with_measured_live_state",
                    "reward_value": 0.82,
                },
            },
        },
    }
    input_path = tmp_path / "smoke.json"
    input_path.write_text(__import__("json").dumps(payload), encoding="utf-8")

    first = close_live_feed_training_loop(input_path, tmp_path / "out", record_ledger=True, reviewer="test-closure")
    second = close_live_feed_training_loop(input_path, tmp_path / "out", record_ledger=True, reviewer="test-closure")
    ledger = review_training_ledger(limit=20)

    assert first["status"] == "closed_loop_materialized"
    assert first["summary"]["example_count"] == 5
    assert first["summary"]["supervised_example_count"] == 3
    assert first["summary"]["eval_example_count"] == 1
    assert first["summary"]["reward_example_count"] == 1
    assert first["summary"]["outcome_memory_status"] == "recorded"
    assert first["summary"]["outcome_memory_id"] == "outcome-live-feed"
    assert first["summary"]["receiver_delivery_status"] == "proven_controlled"
    assert first["summary"]["receiver_delivery_delivered_count"] == 1
    assert first["summary"]["receiver_delivery_acknowledged_count"] == 1
    assert first["summary"]["outcome_measurement_status"] == "measured"
    assert first["summary"]["outcome_measurement_reward_value"] == 0.82
    assert first["labels_or_reward_changed"] is False
    assert first["eligible_for_reward_training"] is True
    assert first["gcp_training_started"] is False
    assert first["model_promotion_started"] is False
    assert second["summary"]["review_disposition_count"] == 2
    assert all(row.get("deduped_existing_review") for row in second["review_dispositions"])
    assert ledger["summary"]["training_candidate_count"] == 2
    assert (tmp_path / "out/live-feed-training-examples.jsonl").read_text(encoding="utf-8").count("\n") == 5
    assert (tmp_path / "out/live-feed-reward-examples.jsonl").read_text(encoding="utf-8").count("\n") == 1
