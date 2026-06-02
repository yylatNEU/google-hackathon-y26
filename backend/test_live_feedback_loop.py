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
