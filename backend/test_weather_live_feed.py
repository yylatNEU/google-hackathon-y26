from __future__ import annotations

from datetime import UTC, datetime

from live_feedback_loop import apply_live_weather_to_state, ingest_live_feed_event, live_weather_policy_gate, live_weather_state_evidence, live_weather_training_gate
from weather_live_feed import build_weather_live_feed_events


def _fresh_at() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def test_build_weather_live_feed_events_maps_open_meteo_current_payload():
    fetch_result = {
        "status": "fetched",
        "fetched_at": "2026-06-01T12:00:00Z",
        "url": "https://api.open-meteo.com/v1/forecast?example=1",
        "config": {"location_label": "Test Park"},
        "payload": {
            "current": {
                "time": "2026-06-01T11:45",
                "temperature_2m": 91.0,
                "relative_humidity_2m": 67,
                "apparent_temperature": 101.5,
                "precipitation": 0.01,
                "rain": 0.01,
                "weather_code": 95,
                "cloud_cover": 80,
                "wind_speed_10m": 16,
                "wind_gusts_10m": 31,
                "is_day": 1,
            },
            "current_units": {"temperature_2m": "F"},
        },
    }

    events = build_weather_live_feed_events(fetch_result)

    assert [event["signal_type"] for event in events] == ["weather_state", "storm_risk", "heat_index"]
    assert all(event["source"] == "weather" for event in events)
    assert events[0]["value"]["location"] == "Test Park"
    assert events[0]["value"]["weather_label"] == "thunderstorm"
    assert events[0]["value"]["lightning_window"] is True
    assert events[1]["value"]["storm_risk_pct"] == 92
    assert events[2]["value"]["heat_risk"] == "high"


def test_apply_live_weather_to_state_uses_trusted_weather_feed(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_LIVE_FEED_EVENT_LOG_PATH", str(tmp_path / "feeds.jsonl"))
    monkeypatch.setenv("PARKPULSE_REVIEW_LEDGER_LOG_PATH", str(tmp_path / "reviews.jsonl"))
    observed_at = _fresh_at()

    ingest_live_feed_event(
        {
            "source": "weather",
            "source_event_id": "weather-state-1",
            "observed_at": observed_at,
            "received_at": observed_at,
            "entity_type": "park",
            "entity_id": "weather",
            "signal_type": "weather_state",
            "value": {
                "provider": "open_meteo",
                "temperature_f": 92,
                "humidity_pct": 70,
                "heat_index_f": 101,
                "storm_risk_pct": 72,
                "weather_label": "rain",
                "wind_speed_mph": 18,
                "wind_gust_mph": 29,
                "lightning_window": False,
                "outdoor_ride_review_required": True,
                "heat_risk": "high",
            },
            "confidence": 0.91,
            "raw_payload_ref": "test-weather",
        }
    )

    state = {
        "weather": {"condition": "simulated", "temperatureF": 70, "heatIndexF": 70, "humidity": 30, "windMph": 3, "stormRisk": 2},
        "incidentReadiness": {"shelterMode": False, "operatorEscalation": "normal"},
        "parkOps": {"outdoorCapacityCutPct": 0},
        "alerts": [],
    }
    patched = apply_live_weather_to_state(state)
    evidence = live_weather_state_evidence()

    assert evidence["trusted"] is True
    assert patched["weather"]["source"] == "live_feed"
    assert patched["weather"]["condition"] == "rain"
    assert patched["weather"]["stormRisk"] == 72
    assert patched["incidentReadiness"]["shelterMode"] is True
    assert patched["policyGates"]["liveWeather"]["weatherRequiresOutdoorReview"] is True
    assert patched["alerts"][0]["title"] == "Live weather review required"


def test_live_weather_policy_gate_forces_review_for_outdoor_action(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_LIVE_FEED_EVENT_LOG_PATH", str(tmp_path / "feeds.jsonl"))
    monkeypatch.setenv("PARKPULSE_REVIEW_LEDGER_LOG_PATH", str(tmp_path / "reviews.jsonl"))
    observed_at = _fresh_at()

    result = ingest_live_feed_event(
        {
            "source": "weather",
            "source_event_id": "storm-weather",
            "observed_at": observed_at,
            "received_at": observed_at,
            "entity_type": "park",
            "entity_id": "weather",
            "signal_type": "weather_state",
            "value": {
                "provider": "open_meteo",
                "temperature_f": 84,
                "humidity_pct": 80,
                "heat_index_f": 90,
                "storm_risk_pct": 92,
                "weather_label": "thunderstorm",
                "wind_speed_mph": 22,
                "wind_gust_mph": 41,
                "lightning_window": True,
                "outdoor_ride_review_required": True,
                "heat_risk": "watch",
            },
            "confidence": 0.95,
            "raw_payload_ref": "test-weather",
        }
    )
    assert result["review_case"] is None

    gate = live_weather_policy_gate({"target": "ride", "action": "reroute_down_ride"})

    assert gate["allowed"] is False
    assert gate["gate_status"] == "review"
    assert gate["weather_gate_status"] == "outdoor_review_required"


def test_live_weather_training_gate_blocks_unresolved_weather_review(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_LIVE_FEED_EVENT_LOG_PATH", str(tmp_path / "feeds.jsonl"))
    monkeypatch.setenv("PARKPULSE_REVIEW_LEDGER_LOG_PATH", str(tmp_path / "reviews.jsonl"))
    observed_at = _fresh_at()

    result = ingest_live_feed_event(
        {
            "source": "weather",
            "source_event_id": "low-confidence-weather",
            "observed_at": observed_at,
            "received_at": observed_at,
            "entity_type": "park",
            "entity_id": "weather",
            "signal_type": "weather_state",
            "value": {"weather_label": "rain", "storm_risk_pct": 60, "outdoor_ride_review_required": False},
            "confidence": 0.55,
            "raw_payload_ref": "test-weather",
        }
    )

    assert result["review_case"]["status"] == "open"
    training_gate = live_weather_training_gate()
    policy_gate = live_weather_policy_gate({"target": "crowd_safety", "action": "calm_reroute"})

    assert training_gate["eligible"] is False
    assert training_gate["status"] == "blocked"
    assert policy_gate["allowed"] is False
    assert policy_gate["weather_gate_status"] == "review_blocked"
