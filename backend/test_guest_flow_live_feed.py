from __future__ import annotations

from datetime import UTC, datetime

from guest_flow_live_feed import build_guest_flow_live_feed_events
from live_feedback_loop import (
    apply_live_guest_flow_to_state,
    ingest_live_feed_event,
    live_guest_flow_policy_gate,
    live_guest_flow_state_evidence,
    live_guest_flow_training_gate,
)


def _fresh_at() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _state(density: int = 84, congestion: int = 72):
    return {
        "guestFlow": {
            "representedGuests": 42000,
            "activeGroups": 8100,
            "avgSatisfaction": 82.5,
            "interventions": [{"kind": "reroute", "targetId": "coasterPlaza", "intensity": 25, "createdAt": "2026-06-01T12:00:00Z"}],
            "zones": [
                {
                    "id": "coasterPlaza",
                    "name": "Coaster Plaza",
                    "area": "north",
                    "processType": "queue",
                    "flowType": "standing",
                    "capacity": 2600,
                    "currentGuests": 2200,
                    "density": density,
                    "densityGuestsPerSqM": 1.8,
                    "comfortScore": 62,
                    "dominantIntent": "ride",
                    "waitMins": 24,
                },
                {
                    "id": "arcade",
                    "name": "Arcade Zone",
                    "area": "indoor",
                    "processType": "dwell",
                    "flowType": "free_flow",
                    "capacity": 1800,
                    "currentGuests": 740,
                    "density": 41,
                    "comfortScore": 88,
                    "dominantIntent": "play",
                    "waitMins": 4,
                },
            ],
            "paths": [
                {
                    "from": "coasterPlaza",
                    "to": "arcade",
                    "fromName": "Coaster Plaza",
                    "toName": "Arcade Zone",
                    "walkMinutes": 5,
                    "capacity": 950,
                    "currentGuests": 720,
                    "congestionLevel": congestion,
                    "widthUtilizationPct": 76,
                    "status": "busy",
                    "forwardTransfers": 160,
                    "reverseTransfers": 90,
                }
            ],
        },
        "alerts": [],
    }


def test_build_guest_flow_events_from_runtime_state():
    events = build_guest_flow_live_feed_events(_state(), observed_at="2026-06-01T12:00:00Z")

    assert [event["signal_type"] for event in events] == ["zone_density", "path_congestion", "routing_take_rate"]
    assert all(event["source"] == "guest_flow" for event in events)
    assert events[0]["value"]["zone_count"] == 2
    assert events[0]["value"]["top_zone"]["id"] == "coasterPlaza"
    assert events[1]["value"]["top_path"]["from"] == "coasterPlaza"


def test_apply_live_guest_flow_to_state_uses_trusted_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_LIVE_FEED_EVENT_LOG_PATH", str(tmp_path / "feeds.jsonl"))
    monkeypatch.setenv("PARKPULSE_REVIEW_LEDGER_LOG_PATH", str(tmp_path / "reviews.jsonl"))

    for event in build_guest_flow_live_feed_events(_state(), observed_at=_fresh_at()):
        ingest_live_feed_event(event)

    patched = apply_live_guest_flow_to_state({"guestFlow": {"zones": [], "paths": []}, "alerts": []})
    evidence = live_guest_flow_state_evidence()

    assert evidence["trusted"] is True
    assert patched["liveFeedEvidence"]["guest_flow"]["status"] == "trusted"
    assert patched["guestFlow"]["zones"][0]["id"] == "coasterPlaza"
    assert patched["guestFlow"]["guestFlowSource"] == "live_feed"
    assert patched["policyGates"]["liveGuestFlow"]["topZoneDensityPct"] == 84


def test_live_guest_flow_policy_gate_forces_review_for_crowd_safety(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_LIVE_FEED_EVENT_LOG_PATH", str(tmp_path / "feeds.jsonl"))
    monkeypatch.setenv("PARKPULSE_REVIEW_LEDGER_LOG_PATH", str(tmp_path / "reviews.jsonl"))

    for event in build_guest_flow_live_feed_events(_state(density=94, congestion=91), observed_at=_fresh_at()):
        ingest_live_feed_event(event)

    gate = live_guest_flow_policy_gate({"target": "crowd_safety", "action": "calm_reroute", "label": "Reroute guests out of Coaster Plaza"})

    assert gate["allowed"] is False
    assert gate["guest_flow_gate_status"] == "crowd_safety_review_required"


def test_live_guest_flow_training_gate_requires_loaded_guest_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_LIVE_FEED_EVENT_LOG_PATH", str(tmp_path / "feeds.jsonl"))
    monkeypatch.setenv("PARKPULSE_REVIEW_LEDGER_LOG_PATH", str(tmp_path / "reviews.jsonl"))

    missing = live_guest_flow_training_gate()
    assert missing["eligible"] is False

    for event in build_guest_flow_live_feed_events(_state(), observed_at=_fresh_at()):
        ingest_live_feed_event(event)

    loaded = live_guest_flow_training_gate()
    assert loaded["eligible"] is True
    assert loaded["status"] == "eligible_live_guest_flow"
