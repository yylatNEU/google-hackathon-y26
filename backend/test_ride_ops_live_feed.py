from __future__ import annotations

from datetime import UTC, datetime

from live_feedback_loop import (
    apply_live_ride_ops_to_state,
    ingest_live_feed_event,
    live_ride_ops_policy_gate,
    live_ride_ops_state_evidence,
    live_ride_ops_training_gate,
)
from ride_ops_live_feed import build_ride_ops_live_feed_events


def _fresh_at() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _state():
    return {
        "guestFlow": {
            "rides": [
                {
                    "id": "dragon",
                    "name": "Dragon Coaster",
                    "zoneName": "Coaster Plaza",
                    "status": "normal",
                    "queueGuests": 920,
                    "waitMins": 76,
                    "downtimeRisk": 28,
                    "capacityPerHour": 1100,
                    "effectiveThroughput": 880,
                    "staffAvailable": 5,
                    "staffRequired": 5,
                },
                {
                    "id": "rapids",
                    "name": "River Rapids",
                    "zoneName": "West Loop",
                    "status": "down",
                    "queueGuests": 0,
                    "waitMins": 0,
                    "downtimeRisk": 88,
                    "capacityPerHour": 700,
                    "effectiveThroughput": 0,
                    "staffAvailable": 2,
                    "staffRequired": 4,
                },
            ]
        },
        "alerts": [],
    }


def test_build_ride_ops_events_from_runtime_state():
    events = build_ride_ops_live_feed_events(_state(), observed_at="2026-06-01T12:00:00Z")

    assert [event["signal_type"] for event in events] == ["ride_status", "wait_time", "downtime", "capacity"]
    assert all(event["source"] == "ride_ops" for event in events)
    assert events[0]["value"]["ride_count"] == 2
    assert events[0]["value"]["down_ride_count"] == 1
    assert events[1]["entity_id"] == "dragon"
    assert events[2]["entity_id"] == "rapids"


def test_apply_live_ride_ops_to_state_uses_trusted_roster(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_LIVE_FEED_EVENT_LOG_PATH", str(tmp_path / "feeds.jsonl"))
    monkeypatch.setenv("PARKPULSE_REVIEW_LEDGER_LOG_PATH", str(tmp_path / "reviews.jsonl"))

    for event in build_ride_ops_live_feed_events(_state(), observed_at=_fresh_at()):
        ingest_live_feed_event(event)

    patched = apply_live_ride_ops_to_state({"guestFlow": {"rides": []}, "alerts": []})
    evidence = live_ride_ops_state_evidence()

    assert evidence["trusted"] is True
    assert patched["liveFeedEvidence"]["ride_ops"]["status"] == "trusted"
    assert patched["guestFlow"]["rides"][0]["id"] == "dragon"
    assert patched["guestFlow"]["rideOpsSource"] == "live_feed"
    assert patched["policyGates"]["liveRideOps"]["downRideCount"] == 1
    assert patched["alerts"][0]["title"] == "Live ride operations pressure"


def test_live_ride_ops_policy_gate_blocks_reopen_without_clearance(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_LIVE_FEED_EVENT_LOG_PATH", str(tmp_path / "feeds.jsonl"))
    monkeypatch.setenv("PARKPULSE_REVIEW_LEDGER_LOG_PATH", str(tmp_path / "reviews.jsonl"))

    for event in build_ride_ops_live_feed_events(_state(), observed_at=_fresh_at()):
        ingest_live_feed_event(event)

    gate = live_ride_ops_policy_gate({"target": "ride", "action": "reopen_ride", "label": "Reopen River Rapids"})
    reroute_gate = live_ride_ops_policy_gate({"target": "ride", "action": "reroute_down_ride", "label": "Reroute around River Rapids"})

    assert gate["allowed"] is False
    assert gate["ride_ops_gate_status"] == "maintenance_clearance_required"
    assert reroute_gate["allowed"] is True


def test_live_ride_ops_training_gate_requires_loaded_ride_feed(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_LIVE_FEED_EVENT_LOG_PATH", str(tmp_path / "feeds.jsonl"))
    monkeypatch.setenv("PARKPULSE_REVIEW_LEDGER_LOG_PATH", str(tmp_path / "reviews.jsonl"))

    missing = live_ride_ops_training_gate()
    assert missing["eligible"] is False

    for event in build_ride_ops_live_feed_events(_state(), observed_at=_fresh_at()):
        ingest_live_feed_event(event)

    loaded = live_ride_ops_training_gate()
    assert loaded["eligible"] is True
    assert loaded["status"] == "eligible_live_ride_ops"
