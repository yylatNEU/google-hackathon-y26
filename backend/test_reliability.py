from __future__ import annotations

import os

import pytest

import park_delivery
import park_replay_store
import reliability


def test_call_with_retries_recovers_after_transient_error(monkeypatch):
    monkeypatch.setenv("PARKPULSE_RETRY_ATTEMPTS", "2")
    calls = {"count": 0}

    def flaky():
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary")
        return "ok"

    assert reliability.call_with_retries("test.transient", flaky, base_delay=0, max_delay=0) == "ok"
    assert calls["count"] == 2
    assert reliability.registry.breaker("test.transient").snapshot()["state"] == "closed"


def test_circuit_breaker_opens_after_repeated_failures(monkeypatch):
    monkeypatch.setenv("PARKPULSE_CIRCUIT_FAILURE_THRESHOLD", "1")
    name = "test.open_circuit"
    reliability.registry.breakers.pop(name, None)

    with pytest.raises(RuntimeError):
        reliability.call_with_retries(name, lambda: (_ for _ in ()).throw(RuntimeError("down")), attempts=1)

    with pytest.raises(reliability.CircuitOpenError):
        reliability.call_with_retries(name, lambda: "not-called", attempts=1)


def test_circuit_breaker_open_state_and_non_retryable_circuit_error():
    breaker = reliability.CircuitBreaker("open", failure_threshold=1, recovery_seconds=60)
    breaker.record_failure(RuntimeError("down"))

    assert breaker.state == "open"
    assert breaker.allow_request() is False
    assert reliability._default_retryable(reliability.CircuitOpenError("open")) is False


def test_delivery_outbox_persists_idempotent_dispatch(tmp_path, monkeypatch):
    outbox = tmp_path / "delivery.jsonl"
    monkeypatch.setenv("PARKPULSE_DELIVERY_OUTBOX", str(outbox))
    park_delivery._outbox.clear()

    dispatch = park_delivery.send_guest_promotion({"scenarioKey": "ride_down", "message": "go"})
    status = park_delivery.delivery_outbox_status()

    assert dispatch["durable"] is True
    assert dispatch["idempotencyKey"].startswith("dispatch_")
    assert status["ready"] is True
    assert status["durable_count"] == 1
    assert os.path.exists(status["path"])


def test_replay_store_backup_and_status(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_REPLAY_DB", str(tmp_path / "replay.db"))
    monkeypatch.setenv("PARKPULSE_DB_BACKUP_DIR", str(tmp_path / "backups"))

    run = park_replay_store.create_replay_run("seed", "ride_down")
    park_replay_store.append_replay_event(run["run_id"], {"id": "event-1", "kind": "test", "label": "Test"})
    backup = park_replay_store.backup_replay_store()
    status = park_replay_store.replay_store_status()

    assert backup["status"] == "ok"
    assert backup["bytes"] > 0
    assert status["ready"] is True
    assert status["runs"] == 1
    assert status["events"] == 1
    assert status["backup_count"] == 1


def test_delivery_and_replay_degraded_branches(tmp_path, monkeypatch):
    outbox = tmp_path / "missing" / "delivery.jsonl"
    monkeypatch.setenv("PARKPULSE_DELIVERY_OUTBOX", str(outbox))
    assert park_delivery._durable_outbox_count() == 0

    monkeypatch.setattr(park_delivery, "_persist_dispatch", lambda document: (_ for _ in ()).throw(RuntimeError("disk full")))
    dispatch = park_delivery.send_worker_notification({"scenarioKey": "ride_down", "task": "go"})
    assert dispatch["durable"] is False
    assert "disk full" in dispatch["durabilityError"]
    guest = park_delivery.send_guest_promotion({"scenarioKey": "ride_down", "message": "go"})
    worker = park_delivery.send_worker_notification({"scenarioKey": "ride_down", "task": "go"})
    assert park_delivery.acknowledge_dispatch(guest["id"], actor="guest", choice="accepted")["response"]["state"] == "acknowledged"
    assert park_delivery.acknowledge_dispatch(worker["id"], actor="lead", choice="accepted")["response"]["acknowledgedCount"] >= 1
    other = park_delivery.send_equipment_command({"scenarioKey": "ride_down", "command": "hold"})
    assert park_delivery.acknowledge_dispatch(other["id"], actor="system", choice="applied")["status"] == "acknowledged"
    gated = park_delivery.send_equipment_command({"scenarioKey": "ride_down", "command": "hold fog", "requiresHumanApproval": True})
    approved = park_delivery.record_approval_decision(gated["id"], actor="operator", decision="approved", reason="clear")
    assert approved["status"] == "approved_for_execution"
    assert approved["approvalDecision"]["approved"] is True
    assert approved["approvalDelivery"]["pubsub"]["event_type"] == "parkpulse.delivery.approval_decision"
    held = park_delivery.send_equipment_command({"scenarioKey": "ride_down", "command": "hold signage", "requiresHumanApproval": True})
    assert park_delivery.record_approval_decision(held["id"], actor="operator", decision="held_for_review")["status"] == "held_for_review"
    assert park_delivery.acknowledge_dispatch("missing", actor="lead", choice="no")["status"] == "not_found"

    monkeypatch.setattr(park_delivery, "_durable_outbox_count", lambda: (_ for _ in ()).throw(RuntimeError("count failed")))
    assert park_delivery.delivery_outbox_status()["ready"] is False
    assert park_delivery._primary_disrupted_ride([])["id"] == "dragonCoaster"
    assert park_delivery._zone_for_ride({"zone": "missing", "zoneName": "Fallback"}, [])["name"] == "Fallback"
    zero_sample = [{"response": {"state": "observed", "sampleSize": 0, "takeRate": 0.5, "positiveResponseRate": 0.4, "reactiveFollowThroughRate": 0.3}}]
    assert park_delivery.response_summary(zero_sample)["takeRate"] == 0.5

    monkeypatch.setenv("PARKPULSE_REPLAY_DB", str(tmp_path / "replay.db"))
    park_replay_store.append_replay_event("", {"id": "ignored"})
    assert park_replay_store.list_replay_events("", 10) == []
    run = park_replay_store.create_replay_run("seed", "ride_down")
    with park_replay_store._connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO replay_events (run_id, event_id, sequence, at, kind, label, event_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run["run_id"], "bad-json", 1, "now", "bad", "Bad", "{bad"),
        )
    assert park_replay_store.list_replay_events(run["run_id"], 10) == []

    monkeypatch.setattr(park_replay_store, "init_replay_store", lambda: (_ for _ in ()).throw(RuntimeError("sqlite down")))
    degraded = park_replay_store.replay_store_status()
    assert degraded["ready"] is False
    assert park_replay_store.replay_collaboration_context()["ready"] is False
