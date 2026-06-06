from __future__ import annotations

import asyncio
import builtins
import json
from datetime import UTC, datetime, timedelta

import live_feedback_loop
from live_feedback_loop import (
    _append_jsonl_many,
    _feed_event_ready_now,
    _feed_log_path,
    _fold_review_state,
    _int_env,
    _mongo_collection_name_for_path,
    _mongo_database_name,
    _read_jsonl,
    _read_mongo_documents,
    _review_disposition_for_event,
    _review_log_path,
    _strip_secret,
    _write_mongo_document,
    ingest_live_feed_event,
    ingest_live_feed_events,
    live_feed_health,
    live_feed_storage_status,
    normalize_live_feed_event,
    record_review_decision,
    review_training_ledger,
    warm_live_feed_storage,
)


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


def test_live_feed_storage_helpers_cover_mongo_and_jsonl_edges(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_LIVE_FEED_STORAGE", "mongo")
    monkeypatch.setenv("MONGODB_URI", "'mongodb://example.test/venue_ops'")
    monkeypatch.delenv("MONGODB_DATABASE", raising=False)
    monkeypatch.setenv("PARKPULSE_LIVE_FEED_EVENT_LOG_PATH", str(tmp_path / "feeds.jsonl"))
    monkeypatch.setenv("PARKPULSE_REVIEW_LEDGER_LOG_PATH", str(tmp_path / "reviews.jsonl"))
    monkeypatch.setenv("BAD_INT", "not-a-number")

    assert _strip_secret("'mongodb://example.test/db'") == "mongodb://example.test/db"
    assert _int_env("BAD_INT", 12) == 12
    assert _mongo_database_name() == "venue_ops"
    assert _mongo_collection_name_for_path(_feed_log_path()) == "live_feed_events"
    assert _mongo_collection_name_for_path(_review_log_path()) == "live_review_ledger"
    assert _mongo_collection_name_for_path(str(tmp_path / "other.jsonl")) is None

    writes = []

    class FakeCursor:
        def sort(self, *args):
            return self

        def limit(self, limit):
            return [{"_id": "hidden", "id": "row-1"}, "bad"][:limit]

    class FakeCollection:
        def replace_one(self, query, document, upsert=False):
            writes.append((query, document, upsert))

        def find(self, *args, **kwargs):
            return FakeCursor()

    class FakeDb:
        def __getitem__(self, collection):
            return FakeCollection()

    class FakeClient:
        def __getitem__(self, name):
            assert name == "venue_ops"
            return FakeDb()

    monkeypatch.setattr(live_feedback_loop, "_mongo_client", lambda: FakeClient())
    assert _write_mongo_document("live_feed_events", {"id": "row-1"}) is True
    assert writes[0][0] == {"_id": "row-1"}
    assert _read_mongo_documents("live_feed_events", limit=0) == [{"id": "row-1"}]

    monkeypatch.setattr(live_feedback_loop, "_write_mongo_document", lambda collection, row: row.get("id") == "ok")
    _append_jsonl_many(_feed_log_path(), [])
    _append_jsonl_many(_feed_log_path(), [{"id": "ok"}, {"id": "fallback"}])
    monkeypatch.setenv("PARKPULSE_LIVE_FEED_STORAGE", "jsonl")
    assert _read_jsonl(_feed_log_path())[0]["id"] == "fallback"

    def broken_open(*args, **kwargs):
        raise OSError("cannot read")

    monkeypatch.setattr(builtins, "open", broken_open)
    assert _read_jsonl(_feed_log_path()) == []


def test_live_feed_storage_warm_paths(monkeypatch):
    monkeypatch.setenv("PARKPULSE_LIVE_FEED_STORAGE", "jsonl")
    assert warm_live_feed_storage()["warm"] is False

    monkeypatch.setenv("PARKPULSE_LIVE_FEED_STORAGE", "mongodb")
    monkeypatch.setenv("MONGODB_URI", "mongodb://example.test/parkpulse")
    monkeypatch.setattr(live_feedback_loop, "_mongo_client", lambda: None)
    assert warm_live_feed_storage()["readiness_issues"]

    class WarmCollection:
        def __init__(self, fail=False):
            self.fail = fail

        def find_one(self, *args, **kwargs):
            if self.fail:
                raise RuntimeError("warm failed")
            return {"_id": "ok"}

    class WarmDb:
        def __init__(self, fail=False):
            self.live_feed_events = WarmCollection(fail=fail)
            self.live_review_ledger = WarmCollection()

    class WarmClient:
        def __init__(self, fail=False):
            self.fail = fail

        def __getitem__(self, name):
            return WarmDb(fail=self.fail)

    monkeypatch.setattr(live_feedback_loop, "_mongo_client", lambda: WarmClient())
    assert warm_live_feed_storage()["warm"] is True
    monkeypatch.setattr(live_feedback_loop, "_mongo_client", lambda: WarmClient(fail=True))
    assert warm_live_feed_storage()["warm"] is False


def test_live_feed_batch_and_review_auto_recovery(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_LIVE_FEED_STORAGE", "jsonl")
    monkeypatch.setenv("PARKPULSE_LIVE_FEED_EVENT_LOG_PATH", str(tmp_path / "feeds.jsonl"))
    monkeypatch.setenv("PARKPULSE_REVIEW_LEDGER_LOG_PATH", str(tmp_path / "reviews.jsonl"))

    assert ingest_live_feed_events([None, "bad"])["status"] == "empty"
    loaded = ingest_live_feed_events(
        [
            {
                "source": "unknown-feed",
                "source_event_id": "unknown-1",
                "observed_at": "bad-time",
                "received_at": 0,
                "signal_type": "security",
                "confidence": "bad",
                "freshness_seconds": "bad",
                "value": "security note",
            },
            {
                "source": "ride_status",
                "source_event_id": "ride-2",
                "observed_at": datetime.now(UTC).isoformat(),
                "signal_type": "wait_time",
                "value": {"wait": 10},
                "confidence": 0.9,
                "raw_payload_ref": "unit://ride",
            },
        ]
    )
    assert loaded["status"] == "loaded"
    assert loaded["review_case_count"] == 1

    stale_event = normalize_live_feed_event(
        {
            "source": "ride_ops",
            "source_event_id": "old",
            "observed_at": (datetime.now(UTC) - timedelta(minutes=10)).isoformat(),
            "received_at": datetime.now(UTC).isoformat(),
            "signal_type": "wait_time",
            "confidence": 0.95,
            "freshness_seconds": 600,
            "raw_payload_ref": "unit://old",
        }
    )
    stale_case = live_feedback_loop.review_case_for_event(stale_event)
    fresh_event = normalize_live_feed_event(
        {
            "source": "ride_ops",
            "source_event_id": "new",
            "observed_at": datetime.now(UTC).isoformat(),
            "signal_type": "wait_time",
            "confidence": 0.95,
            "raw_payload_ref": "unit://new",
        }
    )

    assert _feed_event_ready_now(fresh_event) is True
    assert _feed_event_ready_now(None) is False
    folded = _fold_review_state([stale_case], {"ride_ops": fresh_event})
    assert folded["closed_reviews"][0]["disposition"]["decision"] == "auto_closed_fresh_feed_recovered"

    open_state = _review_disposition_for_event(stale_event["id"], [stale_case])
    assert open_state["status"] == "open_review"
    approved = _review_disposition_for_event(
        stale_event["id"],
        [
            stale_case,
            {"review_type": "operator_disposition", "case_id": stale_case["id"], "decision": "approve_for_state"},
        ],
    )
    assert approved["status"] == "approved"
    rejected = _review_disposition_for_event(
        stale_event["id"],
        [
            stale_case,
            {"review_type": "operator_disposition", "case_id": stale_case["id"], "decision": "hold_for_review"},
        ],
    )
    assert rejected["status"] == "hold_for_review"


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
    ops_proposal = next(proposal for proposal in result["proposals"] if proposal["department"] == "operations")
    ride_down_board = ops_proposal["department_reasoning"]["ride_down_recovery_board"]
    assert ride_down_board["mode"] == "ride_down_recovery_decision_board"
    assert ride_down_board["selected_branch_id"] == "split_route_hold_reopen"
    assert ride_down_board["branch_count"] >= 5
    assert "No ride reopening from an operations recommendation." in ride_down_board["explicit_rejections"]
    ops_tradeoff = next(row for row in result["tradeoff_matrix"] if row["department"] == "operations")
    assert ops_tradeoff["ride_down_selected_branch"] == "split_route_hold_reopen"
    assert ops_tradeoff["ride_down_branch_count"] >= 5
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


def test_actual_training_quarantines_unresolved_unknown_scenario_rows():
    from park_actual_training import _scenario_balanced_fitness

    rows = [
        {
            "row_id": "unknown-1",
            "scenario_key": "unknown",
            "policy_key": "observed_policy",
            "reward": 30.96,
            "created_at": "2026-06-04T17:00:00Z",
        },
        {
            "row_id": "ride-1",
            "scenario_key": "unknown",
            "policy_key": "ride route capacity recovery",
            "reward": 58.0,
            "created_at": "2026-06-04T17:01:00Z",
        },
        {
            "row_id": "food-1",
            "scenario_key": "food_spike",
            "policy_key": "pause promo",
            "reward": 62.0,
            "created_at": "2026-06-04T17:02:00Z",
        },
    ]

    result = _scenario_balanced_fitness(rows)
    scenarios = {row["scenario_key"] for row in result["scenarios"]}

    assert "unknown" not in scenarios
    assert {"ride_down", "food_spike"} <= scenarios
    assert result["label_quality"]["unknown_quarantined_count"] == 1
    assert result["label_quality"]["unknown_quarantined_row_ids"] == ["unknown-1"]


def test_actual_training_exports_live_feed_case_bank_reward_vectors(monkeypatch, tmp_path):
    from park_actual_training import _live_feed_case_bank_training_rows

    case_bank = tmp_path / "case-bank.jsonl"
    case_bank.write_text(
        json.dumps(
            {
                "case_id": "live_feed_case:outcome_test_storm",
                "outcome_id": "outcome_test_storm",
                "decision_id": "decision_test_storm",
                "created_at": "2026-06-04T17:05:20Z",
                "issue": {"kind": "lightning_delay", "target_id": "outdoor_park"},
                "actions": {
                    "executed_count": 2,
                    "risk_escalation_requested_count": 1,
                    "risk_escalation_approved_count": 1,
                    "risk_escalated_executed_count": 1,
                    "risk_escalation_delivery_status": "proven_escalated",
                    "risk_escalation_impact_status": "applied",
                    "risk_escalation_material_state_mutation": True,
                    "risk_escalation_validation_mode": "normal",
                },
                "measurement": {
                    "attribution_confidence": 0.95,
                    "eligible_for_reward": True,
                    "promotion_eligible": True,
                    "reward_label": "operational_lift_with_policy_safe_execution",
                    "reward_layers": {
                        "operational_reward": 0.577,
                        "risk_lift_label": "risk_lift_success",
                        "branch_rewards": {
                            "controlled_low_risk": {"reward": 0.74, "executed_count": 2},
                            "risk_lift": {
                                "reward": 0.91,
                                "label": "risk_lift_success",
                                "requested_count": 1,
                                "approved_count": 1,
                                "executed_count": 1,
                                "delivery_status": "proven_escalated",
                                "impact_status": "applied",
                                "material_state_mutation": True,
                                "effect_score": 0.8,
                            },
                        },
                    },
                    "controlled_effect_projection": {
                        "status": "applied",
                        "executed_tools": ["pause_launch_promo", "shift_adjustment_recommendation"],
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PARKPULSE_LIVE_FEED_CASE_BANK_PATH", str(case_bank))

    rows = _live_feed_case_bank_training_rows()

    assert len(rows) == 2
    row = next(row for row in rows if row["source"] == "live_feed_case_bank_reward_vectors")
    assert row["row_id"] == "live_feed_case_bank:outcome_test_storm"
    assert row["source"] == "live_feed_case_bank_reward_vectors"
    assert row["scenario_key"] == "storm_response"
    assert row["reward"] == 57.7
    assert row["normalized_from"] == "operational_reward_0_1_to_training_0_100"
    assert row["take_rate"] == 1.0
    assert row["follow_through_rate"] == 0.95
    assert row["promotion_eligible"] is True
    assert row["promotion_eval_eligible"] is True
    assert row["training_partition"] == "operational_policy"
    assert row["executed_tools"] == ["pause_launch_promo", "shift_adjustment_recommendation"]
    assert row["reasoning_context"] == "storm_response|controlled_low_risk"
    assert row["risk_lift_label"] == "risk_lift_success"
    risk_row = next(row for row in rows if row["source"] == "live_feed_case_bank_risk_lift_reward_vectors")
    assert risk_row["row_id"] == "live_feed_case_bank_risk_lift:outcome_test_storm"
    assert risk_row["scenario_key"] == "storm_response"
    assert risk_row["policy_key"] == "live_feed_risk_lift_approve_lightning_delay"
    assert risk_row["reward"] == 91.0
    assert risk_row["reward_label"] == "risk_lift_success"
    assert risk_row["promotion_eval_eligible"] is True
    assert risk_row["training_partition"] == "operational_policy"
    assert risk_row["reasoning_context"] == "storm_response|risk_lift_success"
    assert {"risk_lift_success", "risk_controls_approved", "risk_lift_executed", "impact:applied"} <= set(risk_row["reasoning_feature_tags"])
    assert risk_row["reasoning_feature_source"] == "live_feed_case_bank_llm_trace"


def test_progress_reconciliation_holds_source_conflicted_slice():
    import importlib.util
    from pathlib import Path

    script_path = Path(__file__).resolve().parents[1] / "scripts" / "record_live_feed_improvement_curve.py"
    spec = importlib.util.spec_from_file_location("record_live_feed_improvement_curve", script_path)
    recorder = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(recorder)

    case_rows = [
        {
            "issue": {"kind": "storm_risk", "target_id": "outdoor_park"},
            "measurement": {"promotion_eligible": True, "reward_layers": {"operational_reward": 0.58}},
        }
        for _ in range(8)
    ]
    report = {
        "actual_training": {
            "source": "heartbeat_delayed_outcome_signals",
            "model_ops": {
                "scenario_fitness": {
                    "scenarios": [
                        {
                            "scenario_key": "storm_response",
                            "decision": "hold_slice",
                            "sample_count": 20,
                            "latest_average_reward": 36.0,
                            "curve_delta": 0.1,
                        }
                    ]
                }
            },
        },
        "source_reconciliation": {
            "operating_report_actual_training": {
                "source": "bigquery_outcome_events",
                "model_ops": {
                    "scenario_fitness": {
                        "scenarios": [
                            {
                                "scenario_key": "storm_response",
                                "decision": "promote_slice",
                                "sample_count": 85,
                                "latest_average_reward": 86.0,
                                "curve_delta": 28.0,
                            }
                        ]
                    }
                },
            },
            "refreshed_actual_training": {
                "source": "heartbeat_delayed_outcome_signals",
                "model_ops": {
                    "scenario_fitness": {
                        "scenarios": [
                            {
                                "scenario_key": "storm_response",
                                "decision": "hold_slice",
                                "sample_count": 20,
                                "latest_average_reward": 36.0,
                                "curve_delta": 0.1,
                            }
                        ]
                    }
                },
            },
        },
    }

    reconciliation = recorder._source_reconciliation(report, case_rows)
    row = reconciliation["rows"][0]

    assert reconciliation["conflict_count"] == 1
    assert row["scenario_key"] == "storm_response"
    assert row["conflict"] is True
    assert row["reconciled_decision"] == "hold_source_conflicted_slice"
    assert row["conflict_priority"] == 3


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


def _risk_lift_task(**overrides):
    task = {
        "task_id": "hard-follow-ops-route",
        "agent": "ride_ops_agent",
        "department": "operations",
        "source_tool": "recommend_route_change",
        "status": "routed_to_owner",
        "policy_status": "requires_executive",
        "next_owner": "ops_lead",
        "exit_condition": "Congestion returns below threshold or route change is cancelled.",
        "fallback": "Cancel route recommendation and return to staffed hold points.",
        "review_inputs": {"live_feed_event_ids": ["event-ride-1", "event-flow-1"]},
    }
    task.update(overrides)
    return task


def test_risk_escalation_disabled_keeps_gate_closed():
    import parkpulse_api

    result = parkpulse_api._build_live_feed_risk_escalation_approval(
        {"hard_decision_follow_through": {"tasks": [_risk_lift_task()]}},
        enabled=False,
    )

    assert result["status"] == "disabled"
    assert result["stage"] == "gate_closed"
    assert result["requested_count"] == 0
    assert result["approved_count"] == 0
    assert result["approvals"] == []


def test_risk_escalation_blocks_missing_controls():
    import parkpulse_api

    task = _risk_lift_task(exit_condition="", fallback="", review_inputs={"live_feed_event_ids": []})
    result = parkpulse_api._build_live_feed_risk_escalation_approval(
        {"decision_id": "decision-risk-test", "hard_decision_follow_through": {"tasks": [task]}},
        enabled=True,
    )

    assert result["status"] == "blocked"
    assert result["requested_count"] == 1
    assert result["approved_count"] == 0
    approval = result["approvals"][0]
    assert approval["status"] == "blocked"
    assert set(approval["missing_controls"]) == {"live_feed_event_ids", "exit_condition", "rollback"}
    assert {row["status"] for row in approval["approvers"]} == {"blocked"}


def test_risk_escalation_rejects_out_of_scope_action():
    import parkpulse_api

    result = parkpulse_api._build_live_feed_risk_escalation_approval(
        {
            "hard_decision_follow_through": {
                "tasks": [
                    _risk_lift_task(
                        task_id="hard-follow-security",
                        agent="security_agent",
                        department="security",
                        source_tool="zone_control_recommendation",
                    )
                ]
            }
        },
        enabled=True,
    )

    assert result["status"] == "not_requested"
    assert result["requested_count"] == 0
    assert result["approved_count"] == 0
    assert result["approvals"] == []


def test_risk_escalated_executor_requires_approval(monkeypatch):
    import parkpulse_api

    calls = []
    monkeypatch.setattr(
        parkpulse_api,
        "run_agent_tool",
        lambda *args, **kwargs: calls.append(args) or {"status": "should_not_execute"},
    )

    result = parkpulse_api._risk_escalated_live_feed_tool_executor_run(
        {
            "risk_escalation_approval": {
                "status": "blocked",
                "approvals": [
                    {
                        "status": "blocked",
                        "department": "operations",
                        "source_tool": "recommend_route_change",
                        "approval_id": "risk_lift_blocked",
                    }
                ],
            }
        },
        execute=True,
    )

    assert result["status"] == "not_executed"
    assert result["executed_count"] == 0
    assert result["receipts"] == []
    assert calls == []


def test_risk_lift_reward_is_separate_from_controlled_reward():
    import parkpulse_api

    result = parkpulse_api._live_feed_reward_layers(
        {
            "role_agent_proposals": {
                "negotiation_rounds": [{"round": 1}, {"round": 2}, {"round": 3}, {"round": 4}],
                "proposals": [
                    {
                        "proposal_envelope": {"policy_check": "passed"},
                        "department_reasoning": {"evidence_argument": "event-flow supports route relief"},
                    }
                ],
            },
            "tool_executor_live_test": {
                "executed_count": 1,
                "held_count": 1,
                "held_disposition_count": 1,
                "receipts": [
                    {"department": "food_retail", "source_tool": "pause_launch_promo", "result": {"status": "executed_controlled"}},
                    {"department": "operations", "source_tool": "recommend_route_change", "result": {"status": "held"}},
                ],
            },
            "live_feed_receiver_delivery": {
                "status": "proven_controlled",
                "delivered_count": 1,
                "acknowledged_count": 1,
                "public_guest_messages_sent": 0,
                "material_state_mutation": False,
            },
            "hard_decision_follow_through": {"status": "routed", "unresolved_without_owner_count": 0},
            "risk_escalation_approval": {"status": "approved", "requested_count": 1, "approved_count": 1},
            "risk_escalated_tool_executor": {"status": "executed", "executed_count": 1},
            "risk_escalation_receiver_delivery": {
                "status": "proven_escalated",
                "delivered_count": 1,
                "acknowledged_count": 1,
            },
            "risk_escalation_simulated_ops_impact": {
                "status": "applied",
                "material_state_mutation": True,
                "state_impact": {"congestion_delta": -30, "queued_guest_delta": -120},
                "episode_fitness": {"fitness": 70},
            },
        },
        rows=[],
        executed_departments={"food_retail"},
        receiver_delivery_proven=True,
        measurement_available=True,
        source_coverage=1,
        department_coverage=1,
        attribution_confidence=0.9,
        improvement_points=2,
        regression_points=0,
        stable_points=1,
    )

    branch_rewards = result["branch_rewards"]
    assert result["risk_lift_label"] == "risk_lift_success"
    assert branch_rewards["controlled_low_risk"]["reward"] > 0
    assert branch_rewards["risk_lift"]["reward"] > 0
    assert branch_rewards["risk_lift"]["executed_count"] == 1
    assert branch_rewards["risk_lift"]["material_state_mutation"] is True
    assert branch_rewards["hard_decision_activation"]["label"] == "hard_decision_lifted_success"
    assert branch_rewards["hard_decision_activation"]["reward"] >= 0.7
    assert result["metrics"]["risk_escalation_effect_score"] > 0
    assert result["metrics"]["hard_decision_required"] is True
    assert result["hard_decision_activation_label"] == "hard_decision_lifted_success"
    assert branch_rewards["risk_lift"]["reward"] != branch_rewards["controlled_low_risk"]["reward"]


def test_risk_lift_regression_is_not_promoted_by_process_completion():
    import parkpulse_api

    result = parkpulse_api._live_feed_reward_layers(
        {
            "role_agent_proposals": {
                "negotiation_rounds": [{"round": 1}, {"round": 2}, {"round": 3}, {"round": 4}],
                "proposals": [
                    {
                        "proposal_envelope": {"policy_check": "passed"},
                        "department_reasoning": {"evidence_argument": "event-flow supports route relief"},
                    }
                ],
            },
            "tool_executor_live_test": {
                "executed_count": 1,
                "held_count": 1,
                "held_disposition_count": 1,
                "receipts": [
                    {"department": "food_retail", "source_tool": "pause_launch_promo", "result": {"status": "executed_controlled"}},
                    {"department": "operations", "source_tool": "recommend_route_change", "result": {"status": "held"}},
                ],
            },
            "live_feed_receiver_delivery": {
                "status": "proven_controlled",
                "delivered_count": 1,
                "acknowledged_count": 1,
                "public_guest_messages_sent": 0,
                "material_state_mutation": False,
            },
            "hard_decision_follow_through": {"status": "routed", "unresolved_without_owner_count": 0},
            "risk_escalation_approval": {"status": "approved", "requested_count": 1, "approved_count": 1},
            "risk_escalated_tool_executor": {"status": "executed", "executed_count": 1},
            "risk_escalation_receiver_delivery": {
                "status": "proven_escalated",
                "delivered_count": 1,
                "acknowledged_count": 1,
            },
            "risk_escalation_simulated_ops_impact": {
                "status": "applied",
                "material_state_mutation": True,
                "state_impact": {"congestion_delta": 24, "queued_guest_delta": 90},
                "episode_fitness": {"fitness": 0},
            },
        },
        rows=[],
        executed_departments={"food_retail"},
        receiver_delivery_proven=True,
        measurement_available=True,
        source_coverage=1,
        department_coverage=1,
        attribution_confidence=0.9,
        improvement_points=2,
        regression_points=0,
        stable_points=1,
    )

    assert result["risk_lift_label"] == "risk_lift_regression"
    assert result["risk_lift_reward"] <= 0.45
    assert result["hard_decision_activation_label"] == "hard_decision_lifted_regression"
    assert result["hard_decision_activation_reward"] <= 0.45
    assert result["branch_rewards"]["risk_lift"]["label"] == "risk_lift_regression"
    assert result["branch_rewards"]["hard_decision_activation"]["label"] == "hard_decision_lifted_regression"
    assert "risk_lift_regression_detected" in result["promotion_blockers"]


def test_risk_escalation_validation_mode_removes_required_controls():
    import parkpulse_api

    payload = {"hard_decision_follow_through": {"tasks": [_risk_lift_task()]}}
    result = parkpulse_api._apply_risk_escalation_validation_mode(payload, "missing_controls")
    approval = parkpulse_api._build_live_feed_risk_escalation_approval(result, enabled=True)

    assert result["risk_escalation_validation_fault"]["mutated_task_count"] == 1
    assert approval["status"] == "blocked"
    assert set(approval["approvals"][0]["missing_controls"]) == {"live_feed_event_ids", "exit_condition", "rollback"}


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
                    "value": {"capacity_pressure_pct": 22, "down_ride_count": 1, "ride_count": 5},
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
                "executed_count": 3,
                "held_count": 1,
                "held_disposition_count": 1,
                "receipts": [
                    {"department": "food_retail", "source_tool": "pause_launch_promo", "result": {"status": "executed_controlled", "executed": True}},
                    {"department": "hr_labor", "source_tool": "shift_adjustment_recommendation", "result": {"status": "executed_controlled", "executed": True}},
                    {"department": "marketing", "source_tool": "redirect_offer", "result": {"status": "executed_controlled", "executed": True}},
                    {"department": "safety", "result": {"status": "held"}},
                ]
            },
            "live_feed_receiver_delivery": {"status": "proven_controlled", "delivered_count": 3, "acknowledged_count": 3, "public_guest_messages_sent": 0, "material_state_mutation": False},
            "hard_decision_follow_through": {"status": "routed", "unresolved_without_owner_count": 0},
            "role_agent_proposals": {
                "negotiation_rounds": [{"round": 1}, {"round": 2}, {"round": 3}, {"round": 4}],
                "alternative_action_negotiation": {
                    "status": "negotiated",
                    "substitute_count": 1,
                    "safe_executable_substitute_count": 1,
                    "unresolved_without_safe_substitute_count": 0,
                    "rows": [
                        {
                            "alternative_id": "alt-test-ops-marketing",
                            "held_agent": "ride_ops_agent",
                            "held_department": "operations",
                            "held_tool": "recommend_route_change",
                            "held_policy_status": "requires_executive",
                            "substitute_agent": "event_creative_agent",
                            "substitute_department": "marketing",
                            "substitute_tool": "redirect_offer",
                            "substitute_executable_if_approved": True,
                            "tradeoff_reason": "Redirect demand without changing crowd-routing authority.",
                            "execution_boundary": "Use the substitute only through its own policy-passed envelope; never convert the held action into execution.",
                        }
                    ],
                },
                "proposals": [
                    {
                        "proposal_envelope": {"policy_check": "passed"},
                        "department_reasoning": {"evidence_argument": "event before-food supports food action"},
                    },
                    {
                        "proposal_envelope": {"policy_check": "requires_human_approval"},
                        "department_reasoning": {"evidence_argument": "event before-ops supports safety hold"},
                    },
                ],
            },
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
                    "value": {"capacity_pressure_pct": 22, "down_ride_count": 1, "ride_count": 5},
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
    assert result["reward_layers"]["trace_reward"] > 0
    assert result["reward_layers"]["policy_reward"] > 0
    assert result["reward_layers"]["execution_reward"] > 0
    assert result["reward_layers"]["operational_reward"] == result["reward_value"]
    assert result["reward_layers"]["learning_reward"] >= 0
    assert result["reward_layers"]["metrics"]["stability_watch_points"] >= 1
    assert result["reward_layers"]["metrics"]["actionable_metric_points"] < (
        result["reward_layers"]["metrics"]["improvement_points"]
        + result["reward_layers"]["metrics"]["regression_points"]
        + result["reward_layers"]["metrics"]["stable_points"]
    )
    assert result["promotion_eligible"] == result["reward_layers"]["promotion_eligible"]
    assert result["attribution_confidence"] >= 0.7
    assert result["source_coverage"] == 1
    assert result["department_coverage"] == 1
    assert {row["source"] for row in result["measurement_rows"]} >= {"food_ops", "guest_flow", "staffing"}
    commerce = result["reward_layers"]["commerce_action_attribution"]
    assert commerce["status"] == "scored"
    assert commerce["mode"] == "commerce_action_level_outcome_attribution"
    assert commerce["average_action_score"] > 0
    by_family = {row["action_family"]: row for row in commerce["rows"]}
    assert by_family["promo_pause_or_load_relief"]["executed"] is True
    assert by_family["inventory_or_restock"]["score"] > 0
    assert by_family["demand_redirect"]["executed"] is True
    assert by_family["labor_support"]["executed"] is True
    substitute = result["substitute_outcome_attribution"]
    assert substitute["status"] == "scored"
    assert substitute["branch_count"] == 1
    assert substitute["executed_branch_count"] == 1
    assert substitute["average_lift_vs_monitor"] > 0
    assert substitute["bundle"]["decision"] == "prefer_safe_substitute_bundle"
    assert substitute["selected_bundle"]["bundle_id"] == "pressure_relief_bundle"
    assert len(substitute["bundle_candidates"]) == 4
    assert substitute["bundle"]["rejected_bundles"]
    branch = substitute["rows"][0]
    assert branch["held_department"] == "operations"
    assert branch["substitute_department"] == "marketing"
    assert branch["best_branch"] == "safe_substitute"
    assert branch["held_action_counterfactual"]["status"] == "not_scored_policy_blocked"
    assert result["reward_layers"]["metrics"]["substitute_executed_branch_count"] == 1


def test_demand_spike_maps_to_food_spike_for_case_bank_and_reports():
    import park_actual_training
    from scripts import live_feed_operating_cycle, record_live_feed_improvement_curve

    row = {"issue": {"kind": "demand_spike", "target_id": "mainStreet"}}

    assert park_actual_training._case_bank_issue_scenario(row) == "food_spike"
    assert record_live_feed_improvement_curve._scenario_from_issue(row) == "food_spike"
    assert live_feed_operating_cycle._scenario_key_from_issue_kind("demand_spike") == "food_spike"


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


def test_live_feed_semantic_learning_priors_adjust_low_risk_reasoning(monkeypatch):
    import parkpulse_api

    outcome = {
        "_id": "outcome-semantic",
        "decisionId": "decision-semantic",
        "loopId": "loop-semantic",
        "mode": "policy_recovery_closed_loop",
        "responseMetrics": {"score": 46, "status": "watch"},
        "stateImpact": {},
        "learning": {},
    }
    monkeypatch.setattr(
        parkpulse_api,
        "get_operational_memory_dashboard",
        lambda _query: {
            "status": {"mode": "mongodb", "connected": True},
            "retrieved": {
                "method": "mongodb_vector_search_voyage",
                "learnings": [
                    {
                        "_id": "learning-semantic",
                        "score": 0.82,
                        "sourceOutcomeId": "outcome-semantic",
                        "lesson": "Low guest take-rate: use stronger or more personalized offers.",
                        "rule": "Increase promotion strength, split routing, and cap overloaded indoor targets.",
                        "department": "operations",
                        "learning_type": "incident",
                        "scope": "ride_ops",
                    }
                ],
            },
            "latest_outcomes": [],
        },
    )
    monkeypatch.setattr(parkpulse_api, "get_memory_document", lambda collection, document_id: outcome)

    priors = parkpulse_api._live_feed_memory_priors_from_dashboard(
        {"scenario_key": "ride_down", "lead_source": "ride_ops", "lead_signal_type": "capacity"},
        limit=3,
    )
    proposals = {
        "proposals": [
            {
                "agent_id": "event_creative_agent",
                "department": "marketing",
                "evidence": ["live_feed:guest_flow"],
                "department_reasoning": {
                    "candidate_actions": [{"action": "redirect_offer", "score": 0.78}],
                    "forecast": {"expected_outcome": "redirect demand"},
                    "memory_carry_forward": {"carry": [], "do_better_next_time": []},
                },
                "proposal_envelope": {"requested_tool": "redirect_offer"},
            },
            {
                "agent_id": "ride_ops_agent",
                "department": "operations",
                "evidence": ["live_feed:ride_ops"],
                "department_reasoning": {
                    "candidate_actions": [{"action": "recommend_route_change", "score": 0.9}],
                    "forecast": {"expected_outcome": "reduce queue"},
                    "memory_carry_forward": {"carry": [], "do_better_next_time": []},
                },
                "proposal_envelope": {"requested_tool": "recommend_route_change"},
            },
        ],
        "negotiation_turns": [],
    }

    enriched = parkpulse_api._apply_live_feed_memory_priors_to_proposals(proposals, priors)

    assert priors["semantic_prior_count"] == 1
    assert priors["retrieval_method"] == "mongodb_vector_search_voyage"
    assert priors["semantic_learning_ids"] == ["learning-semantic"]
    marketing = enriched["proposals"][0]
    operations = enriched["proposals"][1]
    assert marketing["memory_use"]["status"] == "accepted_semantic_learning"
    assert marketing["memory_decision_delta"]["effect"] == "semantic_learning_adjusted_candidate"
    assert marketing["department_reasoning"]["candidate_actions"][0]["semantic_memory_learning_id"] == "learning-semantic"
    assert marketing["proposal_envelope"]["semantic_action_parameters"]["routing_strategy"] == "split_across_low_wait_destinations"
    assert marketing["proposal_envelope"]["proposal_payload"]["offer_action"] == "redirect_to_multiple_lower_pressure_destinations"
    assert "semantic_memory:learning-semantic:score=0.82:source_outcome=outcome-semantic" in marketing["evidence"]
    assert operations["memory_use"]["status"] == "semantic_context_only"
    assert operations["memory_relevance_judge"]["accepted_by_judge"] is False


def test_live_feed_training_closure_preserves_semantic_payload_material(tmp_path):
    from scripts.live_feed_training_closure import close_live_feed_training_loop

    semantic_params = {
        "source": "semantic_agent_learning",
        "learning_id": "learning-semantic",
        "source_outcome_id": "outcome-semantic",
        "routing_strategy": "split_across_low_wait_destinations",
        "traffic_cap_policy": "cap_overloaded_indoor_targets",
        "tool_payload_delta": {"offer_action": "redirect_to_multiple_lower_pressure_destinations"},
        "policy": "Parameters refine only low-risk receiver payloads; they do not grant new execution authority.",
    }
    payload = {
        "summary": {"proposal_count": 1, "active_departments": ["marketing"], "status": "passed"},
        "live_feed_memory_priors": {
            "status": "retrieved",
            "retrieval_method": "mongodb_vector_search_voyage",
            "semantic_prior_count": 1,
            "semantic_learning_ids": ["learning-semantic"],
            "latest_outcome_ids": ["outcome-semantic"],
            "prior_count": 1,
        },
        "role_agent_proposals": {
            "memory_prior_use": {
                "rows": [{"department": "marketing", "status": "accepted_semantic_learning"}],
                "weak_context_rows": [{"department": "operations", "status": "semantic_context_only"}],
            },
            "proposals": [
                {
                    "agent_id": "event_creative_agent",
                    "department": "marketing",
                    "requested_tool": "redirect_offer",
                    "proposal_envelope": {
                        "requested_tool": "redirect_offer",
                        "semantic_action_parameters": semantic_params,
                        "proposal_payload": {"offer_action": "redirect_to_multiple_lower_pressure_destinations"},
                    },
                    "policy_judge": {"status": "passed"},
                    "department_reasoning": {"memory_carry_forward": {"carry": [], "do_better_next_time": []}},
                    "agent_loop": {"trace": "observe_interpret_predict_recommend"},
                    "live_feed_grounding": {"event_ids": ["feed-1"], "sources": ["guest_flow"]},
                }
            ],
        },
        "tool_executor_live_test": {
            "semantic_action_parameter_count": 1,
            "receipts": [
                {
                    "agent": "event_creative_agent",
                    "department": "marketing",
                    "source_tool": "redirect_offer",
                    "approved_for_controlled_executor": True,
                    "semantic_action_parameters": semantic_params,
                    "result": {"status": "executed", "executed": True, "semantic_action_parameters": semantic_params},
                }
            ],
        },
        "live_feed_outcome_measurement": {
            "semantic_parameters_applied": True,
            "measurement_rows": [
                {
                    "source": "guest_flow",
                    "before_event_id": "feed-before",
                    "after_event_id": "feed-after",
                    "metrics": [{"metric": "routing_take_rate_pct", "before": 82, "after": 90, "impact": "improved"}],
                }
            ],
            "reward_layers": {
                "operational_reward": 0.62,
                "composite_reward": 0.8,
                "promotion_eligible": True,
                "metrics": {
                    "semantic_action_parameter_count": 1,
                    "semantic_action_quality_reward": 0.04,
                    "commerce_action_average_score": 0.5,
                },
            },
            "controlled_effect_projection": {
                "semantic_parameters_applied": True,
                "semantic_parameter_rows": [semantic_params],
            },
        },
    }
    input_path = tmp_path / "smoke.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    manifest = close_live_feed_training_loop(input_path, tmp_path / "out", record_ledger=False, reviewer="unit")

    summary = manifest["summary"]
    assert summary["semantic_retrieval_method"] == "mongodb_vector_search_voyage"
    assert summary["semantic_prior_accepted_departments"] == ["marketing"]
    assert summary["semantic_context_only_departments"] == ["operations"]
    assert summary["semantic_action_parameter_count"] == 1
    assert summary["semantic_parameters_applied"] is True
    assert summary["semantic_measurement_delta_count"] == 1
    assert summary["semantic_action_quality_reward"] == 0.04
    material = manifest["semantic_memory_training_material"]
    assert material["semantic_parameter_rows"][0]["tool_payload_delta"]["offer_action"] == "redirect_to_multiple_lower_pressure_destinations"
    assert material["measurement_deltas"][0]["metric"] == "routing_take_rate_pct"


def test_live_feed_executor_runs_semantic_companion_inventory_action():
    import parkpulse_api

    result = parkpulse_api._controlled_live_feed_tool_executor_run(
        {
            "decision_id": "decision-semantic-companion",
            "role_agent_proposals": {
                "proposals": [
                    {
                        "agent_id": "food_demand_agent",
                        "department": "food_retail",
                        "recommendation": "Control constrained promo and alert inventory.",
                        "proposal_envelope": {
                            "requested_tool": "pause_launch_promo",
                            "intent": "Control constrained promo and alert inventory.",
                            "policy_check": "passed_food_inventory_no_unavailable_promo",
                            "executor_status": "ready_for_executor",
                            "policy_judge": {"status": "passed"},
                            "semantic_action_parameters": {
                                "source": "semantic_agent_learning",
                                "learning_id": "learning-semantic",
                                "companion_tools": ["inventory_alert"],
                                "tool_payload_delta": {"inventory_guard": "prevent stockout"},
                            },
                        },
                        "action_disposition": {
                            "decision": "execute_controlled_internal",
                            "next_owner": "tool_executor_agent",
                            "exit_condition": "Receiver acknowledges handoff.",
                            "fallback": "Cancel if feed normalizes.",
                            "live_feed_event_ids": ["feed-food"],
                        },
                    }
                ]
            },
        },
        execute=True,
    )

    executed_tools = [
        row["source_tool"]
        for row in result["receipts"]
        if isinstance(row, dict) and (row.get("result", {}) if isinstance(row.get("result"), dict) else {}).get("executed")
    ]
    assert result["executed_count"] == 2
    assert executed_tools == ["pause_launch_promo", "inventory_alert"]
    companion = result["receipts"][1]
    assert companion["companion_action"] is True
    assert companion["companion_parent_tool"] == "pause_launch_promo"
    assert companion["result"]["companion_source"] == "semantic_agent_learning"


def test_live_feed_alternative_negotiation_names_safe_substitute_for_held_ops_action():
    import parkpulse_api

    proposals = {
        "proposals": [
            {
                "agent_id": "ride_ops_agent",
                "department": "operations",
                "proposal_envelope": {
                    "requested_tool": "recommend_route_change",
                    "executor_status": "awaiting_executive",
                    "policy_judge": {"status": "requires_executive"},
                },
                "policy_judge": {"status": "requires_executive"},
                "live_feed_grounding": {"event_ids": ["feed-ride"]},
                "action_disposition": {
                    "decision": "reject_execution_hold_recommendation",
                    "next_owner": "operations_lead_with_executive",
                },
            },
            {
                "agent_id": "event_creative_agent",
                "department": "marketing",
                "proposal_envelope": {
                    "requested_tool": "redirect_offer",
                    "executor_status": "ready_for_executor",
                    "policy_judge": {"status": "passed"},
                },
                "policy_judge": {"status": "passed"},
                "action_disposition": {"decision": "execute_controlled_internal"},
            },
        ],
        "executive_tradeoff": {},
        "negotiation_rounds": [{"round": 1, "name": "local_department_positions"}],
        "negotiation_turns": [],
    }

    board = parkpulse_api._build_live_feed_alternative_action_negotiation(proposals)

    assert board["status"] == "negotiated"
    assert board["substitute_count"] == 1
    assert board["safe_executable_substitute_count"] == 1
    assert board["unresolved_without_safe_substitute_count"] == 0
    row = board["rows"][0]
    assert row["held_department"] == "operations"
    assert row["substitute_department"] == "marketing"
    assert row["substitute_tool"] == "redirect_offer"
    assert row["substitute_executable_if_approved"] is True
    assert row["execution_boundary"].startswith("Use the substitute only through its own policy-passed envelope")
    assert proposals["executive_tradeoff"]["alternative_action_negotiation"]["substitute_count"] == 1
    assert any(turn["turn"] == "alternative_actions" for turn in proposals["negotiation_turns"])


def test_live_feed_memory_priors_fall_back_to_case_bank_when_mongo_empty(tmp_path, monkeypatch):
    import parkpulse_api

    case_bank = tmp_path / "index.jsonl"
    case_bank.write_text(
        json.dumps(
            {
                "case_id": "live_feed_case:outcome-prior",
                "closed_case": True,
                "created_at": "2026-06-04T12:00:00Z",
                "decision_id": "decision-prior",
                "outcome_id": "outcome-prior",
                "issue": {"kind": "staff_callout", "target_id": "zone-b"},
                "actions": {"receiver_delivery_status": "proven_controlled"},
                "agent_decision": {"held_departments": ["operations", "safety"]},
                "measurement": {
                    "status": "measured",
                    "eligible_for_reward": True,
                    "reward_value": 0.77,
                    "attribution_confidence": 0.91,
                    "controlled_effect_projection": {
                        "executed_departments": ["food_retail", "hr_labor", "marketing"],
                        "executed_tools": ["pause_launch_promo", "shift_adjustment_recommendation", "redirect_offer"],
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(parkpulse_api, "LIVE_FEED_CASE_BANK_INDEX", case_bank)
    monkeypatch.setattr(
        parkpulse_api,
        "get_operational_memory_dashboard",
        lambda _query: {"status": {"mode": "demo_fallback", "connected": False}, "latest_outcomes": []},
    )

    priors = parkpulse_api._live_feed_memory_priors_from_dashboard(
        {"scenario_key": "staff_shortage", "lead_source": "staffing", "lead_signal_type": "callout"},
        limit=3,
    )

    assert priors["status"] == "retrieved"
    assert priors["source"] == "case_bank_memory_fallback"
    assert priors["fallback_reason"] == "mongodb_memory_empty"
    assert priors["prior_count"] == 1
    assert priors["latest_outcome_ids"] == ["outcome-prior"]
    prior = priors["priors"][0]
    assert prior["scenario_key"] == "staff_shortage"
    assert prior["executed_tools"] == ["pause_launch_promo", "shift_adjustment_recommendation", "redirect_offer"]
    assert prior["executed_departments"] == ["food_retail", "hr_labor", "marketing"]
    assert prior["reward_value"] == 0.77
    assert prior["attribution_confidence"] == 0.91


def test_live_feed_ml_policy_evidence_shapes_reasoning_without_execution_rights():
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
                    "memory_carry_forward": {"carry": [], "do_better_next_time": []},
                },
                "proposal_envelope": {"requested_tool": "pause_launch_promo"},
            },
            {
                "agent_id": "ride_ops_agent",
                "department": "operations",
                "evidence": ["live_feed:ride_ops"],
                "department_reasoning": {
                    "candidate_actions": [{"action": "recommend_route_change", "score": 0.9}],
                    "forecast": {"expected_outcome": "reduce queue pressure"},
                    "memory_carry_forward": {"carry": [], "do_better_next_time": []},
                },
                "proposal_envelope": {"requested_tool": "recommend_route_change"},
            },
        ],
        "executive_tradeoff": {},
        "negotiation_rounds": [{"round": 1, "name": "local_department_positions"}],
        "negotiation_turns": [],
    }
    ml_evidence = {
        "status": "matched",
        "scenario_key": "food_spike",
        "slice_decision": "promote_slice",
        "slice_sample_count": 18,
        "latest_average_reward": 58.4,
        "curve_delta": 4.2,
        "actual_training_source": "heartbeat_delayed_outcome_signals+live_feed_case_bank_reward_vectors",
        "policy": "ML evidence is guidance only.",
    }

    enriched = parkpulse_api._apply_live_feed_ml_policy_evidence_to_proposals(proposals, ml_evidence)
    food = enriched["proposals"][0]
    ops = enriched["proposals"][1]

    assert enriched["ml_policy_evidence_use"]["status"] == "applied"
    assert enriched["ml_policy_evidence_use"]["accepted_low_risk_count"] == 1
    assert enriched["ml_policy_evidence_use"]["context_only_count"] == 1
    assert food["ml_policy_evidence_use"]["accepted_by_judge"] is True
    assert food["ml_policy_decision_delta"]["effect"] == "reinforced_low_risk_candidate"
    assert food["department_reasoning"]["learned_policy_evidence"]["slice_decision"] == "promote_slice"
    assert food["department_reasoning"]["counterfactual_learning_comparison"]["compare_against"] == ["hold_action", "current_live_feed_only", "memory_prior_only"]
    assert food["department_reasoning"]["candidate_actions"][0]["ml_policy_adjusted_score"] == 0.84
    assert "ml_slice:food_spike:decision=promote_slice:reward=58.4:delta=4.2" in food["evidence"]
    assert ops["ml_policy_evidence_use"]["accepted_by_judge"] is False
    assert ops["ml_policy_evidence_use"]["used_for"] == "tradeoff_context_no_execution_bias"
    assert ops["ml_policy_decision_delta"]["decision_boundary"].startswith("ML evidence cannot grant execution rights")
    assert enriched["negotiation_rounds"][1]["name"] == "actual_training_slice_challenge"
    assert enriched["negotiation_turns"][0]["agent"] == "actual_training_policy_gate"


def test_live_feed_ml_policy_evidence_prefers_explicit_scenario_hint():
    import parkpulse_api

    live_case = {
        "scenario_key": "staff_shortage",
        "lead_source": "food_ops",
        "lead_signal_type": "mobile_order_backlog",
        "operator_message": "food_ops mobile order backlog is noisy but injected issue is staff_callout",
        "evidence": [{"source": "food_ops", "signal_type": "mobile_order_backlog", "summary": "food backlog 20"}],
    }

    assert parkpulse_api._infer_live_feed_training_scenario(live_case) == "staff_shortage"


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
                "ml_policy_evidence_use": {
                    "accepted_low_risk_count": 1,
                    "context_only_count": 1,
                    "warning_count": 0,
                },
                "ml_policy_decision_deltas": [
                    {"department": "food_retail", "status": "accepted_low_risk_policy_guidance"}
                ],
                "proposals": [{"policy_judge": {"status": "passed"}}, {"policy_judge": {"status": "requires_human_approval"}}],
            },
            "live_feed_ml_policy_evidence": {
                "status": "matched",
                "scenario_key": "food_spike",
                "slice_decision": "promote_slice",
                "latest_average_reward": 58.4,
                "curve_delta": 4.2,
                "actual_training_source": "heartbeat_delayed_outcome_signals+live_feed_case_bank_reward_vectors",
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
            "risk_escalation_approval": {
                "status": "disabled",
                "stage": "gate_closed",
                "requested_count": 0,
                "approved_count": 0,
            },
            "risk_escalated_tool_executor": {"status": "not_executed", "executed_count": 0, "preview_count": 0},
            "risk_escalation_receiver_delivery": {"status": "not_dispatched", "delivered_count": 0, "acknowledged_count": 0},
            "risk_escalation_simulated_ops_impact": {"status": "not_applied", "material_state_mutation": False},
            "live_feed_outcome_measurement": {
                "status": "measured",
                "measurement_id": "measurement-proof",
                "measured_outcome_available": True,
                "eligible_for_reward": True,
                "reward_value": 0.82,
                "reward_label": "safe_controlled_handoff_with_measured_live_state",
                "reward_layers": {
                    "trace_reward": 1.0,
                    "policy_reward": 1.0,
                    "execution_reward": 0.95,
                    "operational_reward": 0.82,
                    "learning_reward": 0.6,
                    "composite_reward": 0.85,
                    "risk_lift_label": "risk_lift_blocked",
                    "branch_rewards": {
                        "controlled_low_risk": {"reward": 0.72},
                        "risk_lift": {"reward": 0.0, "label": "risk_lift_blocked", "executed_count": 0},
                    },
                    "promotion_eligible": True,
                },
                "promotion_eligible": True,
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
    assert recorded["outcome"]["response_metrics"]["rewardLayers"]["operational_reward"] == 0.82
    assert recorded["outcome"]["response_metrics"]["promotionEligible"] is True
    assert recorded["outcome"]["state_impact"]["executed_departments"] == ["food_retail"]
    assert recorded["outcome"]["state_impact"]["held_departments"] == ["safety"]
    assert recorded["outcome"]["state_impact"]["hard_decision_follow_through_status"] == "routed"
    assert recorded["outcome"]["state_impact"]["active_follow_up_count"] == 1
    assert recorded["outcome"]["state_impact"]["hard_decision_follow_through_tasks"][0]["task_id"] == "hard-follow-safety"
    assert recorded["outcome"]["state_impact"]["risk_escalation_approval"]["status"] == "disabled"
    assert recorded["outcome"]["state_impact"]["risk_escalated_tool_executor"]["executed_count"] == 0
    assert recorded["outcome"]["state_impact"]["receiver_delivery_proof_id"] == "receiver-proof"
    assert recorded["outcome"]["state_impact"]["post_action_measurement_id"] == "measurement-proof"
    assert recorded["outcome"]["state_impact"]["ml_policy_evidence"]["scenario_key"] == "food_spike"
    assert recorded["outcome"]["state_impact"]["ml_policy_evidence_use"]["accepted_low_risk_count"] == 1
    assert recorded["outcome"]["state_impact"]["ml_policy_decision_deltas"][0]["department"] == "food_retail"
    assert recorded["outcome"]["scorecard"]["receiver_delivery"] == 100
    assert recorded["outcome"]["scorecard"]["post_action_measurement"] == 100
    assert recorded["outcome"]["learning"]["eligible_for_reward"] is True
    assert recorded["outcome"]["learning"]["reward_layers"]["operational_reward"] == 0.82
    assert recorded["outcome"]["learning"]["branch_rewards"]["risk_lift"]["label"] == "risk_lift_blocked"
    assert recorded["outcome"]["learning"]["risk_lift_label"] == "risk_lift_blocked"
    assert {"controlled_low_risk", "risk_lift_blocked", "risk_gate_disabled"} <= set(recorded["outcome"]["learning"]["training_tags"])
    assert recorded["outcome"]["learning"]["risk_lift_learning_context"]["status"] == "disabled"
    assert recorded["outcome"]["learning"]["promotion_eligible"] is True
    assert recorded["outcome"]["learning"]["ml_policy_learning_context"]["slice_decision"] == "promote_slice"
    assert recorded["outcome"]["learning"]["ml_policy_learning_context"]["accepted_low_risk_count"] == 1


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
            "reward_layers": {
                "trace_reward": 1.0,
                "policy_reward": 1.0,
                "execution_reward": 0.95,
                "operational_reward": 0.82,
                "learning_reward": 0.6,
                "composite_reward": 0.85,
                "promotion_eligible": True,
            },
            "promotion_eligible": True,
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
                    "reward_layers": {
                        "trace_reward": 1.0,
                        "policy_reward": 1.0,
                        "execution_reward": 0.95,
                        "operational_reward": 0.82,
                        "learning_reward": 0.6,
                        "composite_reward": 0.85,
                        "promotion_eligible": True,
                    },
                    "promotion_eligible": True,
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
