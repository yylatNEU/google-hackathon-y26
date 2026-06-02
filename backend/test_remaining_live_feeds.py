from __future__ import annotations

from live_feedback_loop import (
    apply_live_food_ops_to_state,
    apply_live_operator_signal_to_state,
    apply_live_staffing_to_state,
    ingest_live_feed_event,
    live_food_ops_training_gate,
    live_operator_signal_training_gate,
    live_staffing_training_gate,
)
from ops_remaining_live_feeds import build_food_ops_live_feed_events, build_operator_signal_live_feed_events, build_staffing_live_feed_events


def _state():
    return {
        "staffing": {"scheduled": 140, "checkedIn": 126, "openCallouts": 7, "medicalTeams": 4, "securityTeams": 5},
        "foodInventory": {
            "locations": [
                {"id": "pizza", "name": "Pizza Pier", "mobileOrderBacklog": 72, "pickupEtaMinutes": 24, "lowInventoryItems": ["dough"], "availableItems": ["pizza"]},
                {"id": "tacos", "name": "Taco Stand", "mobileOrderBacklog": 22, "pickupEtaMinutes": 11, "lowInventoryItems": [], "availableItems": ["tacos"]},
            ],
            "suppressedItems": ["dough"],
            "policy": "do_not_sell_unavailable_items",
        },
        "guestCare": {
            "openCases": 18,
            "complaintRatePct": 7.5,
            "topDrivers": ["wait_time", "food_delay"],
            "recoveryQueue": [{"segment": "families", "safeAction": "route_to_indoor_show", "approval": "operator"}],
            "policy": "guest_recovery_requires_operator_review",
        },
        "alerts": [],
    }


def test_remaining_feed_builders_emit_required_signals():
    state = _state()
    staffing = build_staffing_live_feed_events(state, observed_at="2026-06-01T12:00:00Z")
    food = build_food_ops_live_feed_events(state, observed_at="2026-06-01T12:00:00Z")
    reports = build_operator_signal_live_feed_events(state, observed_at="2026-06-01T12:00:00Z")

    assert [event["signal_type"] for event in staffing] == ["coverage", "fatigue", "break_window", "training_tag"]
    assert [event["signal_type"] for event in food] == ["inventory", "mobile_backlog", "prep_eta", "kitchen_load"]
    assert [event["signal_type"] for event in reports] == ["guest_care", "staff_note", "incident_report"]


def test_remaining_feeds_patch_state_and_training_gates(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_LIVE_FEED_EVENT_LOG_PATH", str(tmp_path / "feeds.jsonl"))
    monkeypatch.setenv("PARKPULSE_REVIEW_LEDGER_LOG_PATH", str(tmp_path / "reviews.jsonl"))
    state = _state()

    for event in [*build_staffing_live_feed_events(state), *build_food_ops_live_feed_events(state), *build_operator_signal_live_feed_events(state)]:
        ingest_live_feed_event(event)

    patched = apply_live_operator_signal_to_state(apply_live_food_ops_to_state(apply_live_staffing_to_state({"alerts": []})))

    assert patched["liveFeedEvidence"]["staffing"]["trusted"] is True
    assert patched["liveFeedEvidence"]["food_ops"]["trusted"] is True
    assert patched["liveFeedEvidence"]["operator_signal"]["trusted"] is True
    assert patched["staffing"]["checkedIn"] == 126
    assert patched["foodInventory"]["locations"][0]["id"] == "pizza"
    assert patched["guestCare"]["openCases"] == 18
    assert live_staffing_training_gate()["status"] == "eligible_live_staffing"
    assert live_food_ops_training_gate()["status"] == "eligible_live_food_ops"
    assert live_operator_signal_training_gate()["status"] == "eligible_live_operator_signal"
