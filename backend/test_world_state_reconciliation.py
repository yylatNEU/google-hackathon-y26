from __future__ import annotations

import asyncio

from park_simulation import ParkSimulation
from world_state_reconciliation import latest_reconciliation, reconcile_world_state


def _state():
    return asyncio.run(ParkSimulation().get_state())


def test_reconciliation_builds_belief_state_from_conflicting_signals():
    state = _state()
    signals = [
        {
            "text": "Crowd camera says Coaster Plaza is calm and lines are moving.",
            "source": "crowd_camera",
            "zoneId": "coasterPlaza",
            "confidence": 0.65,
            "reliability": 0.78,
        },
        {
            "text": "Staff radio: guests are pushing near Dragon Coaster exit and queue is blocked.",
            "source": "staff_radio",
            "zoneId": "coasterPlaza",
            "confidence": 0.86,
            "reliability": 0.74,
        },
        {
            "text": "Social post says maybe the ride area is blocked, unconfirmed.",
            "source": "social_snippet",
            "zoneId": "coasterPlaza",
            "confidence": 0.42,
            "reliability": 0.35,
        },
    ]

    result = reconcile_world_state(state, signals)

    assert result["status"] == "complete"
    assert result["beliefs"]
    assert result["agent_input"]["belief_state"]["top_beliefs"]
    assert result["action_receipts"]
    assert result["uncertainty"]["level"] in {"medium", "high", "critical"}
    assert latest_reconciliation()["reconciliation_id"] == result["reconciliation_id"]


def test_reconciliation_preset_returns_operator_review_contract():
    result = reconcile_world_state(_state(), preset="health_accessibility")

    assert result["source_count"] >= 1
    assert "requires_operator_review" in result["agent_input"]
    assert all("evidence" in receipt for receipt in result["action_receipts"])
