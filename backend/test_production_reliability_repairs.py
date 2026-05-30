from __future__ import annotations

import asyncio
import json
import os

os.environ.setdefault("MONGODB_DISABLE_DRIVER_IMPORT", "1")

import main
import gcp_operations
import park_delivery
import reliability
from policy_engine import get_policy_engine


def test_policy_gate_blocks_safety_sensitive_actions():
    engine = get_policy_engine()
    park_state = {
        "guestFlow": {
            "activeScenario": {"key": "ride_down"},
            "rides": [{"name": "Dragon Coaster", "status": "down"}],
            "zones": [{"name": "Coaster Plaza", "density": 88}],
        }
    }

    unsafe_actions = [
        {"title": "Reopen Dragon Coaster now", "park_action": {"target": "ride", "action": "reopen"}},
        {"title": "Diagnose guest fainting as dehydration", "park_action": {"target": "medical", "action": "dispatch"}},
        {"title": "Use emergency evacuation path as overflow queue", "park_action": {"target": "queue_gate", "action": "hold_intake"}},
        {"title": "Move uncertified staff into ride operation", "park_action": {"target": "staff", "action": "redeploy"}},
        {"title": "Clear fault and reopen ride safety system", "park_action": {"target": "maintenance", "action": "clear_fault"}},
    ]

    results = [engine.evaluate_action(action, park_state, scenario="ride_down") for action in unsafe_actions]

    assert results[0]["status"] == "blocked"
    assert results[1]["status"] == "blocked"
    assert results[2]["status"] == "blocked"
    assert results[3]["status"] == "blocked"
    assert results[4]["status"] == "blocked"


def test_delivery_outbox_deduplicates_same_payload(tmp_path, monkeypatch):
    outbox = tmp_path / "delivery.jsonl"
    monkeypatch.setenv("PARKPULSE_DELIVERY_OUTBOX", str(outbox))
    park_delivery._outbox.clear()

    payload = {"decisionId": "same-decision", "scenarioKey": "ride_down", "message": "go"}
    first = park_delivery.send_guest_promotion(payload)
    duplicate = park_delivery.send_guest_promotion(payload)

    assert duplicate["id"] == first["id"]
    assert duplicate["idempotencyKey"] == first["idempotencyKey"]
    assert duplicate["deduplicated"] is True
    assert len(park_delivery.latest_dispatches()) == 1
    assert park_delivery.delivery_outbox_status()["durable_count"] == 1


def test_delivery_outbox_recovers_after_open_persist_circuit(tmp_path, monkeypatch):
    outbox = tmp_path / "delivery.jsonl"
    monkeypatch.setenv("PARKPULSE_DELIVERY_OUTBOX", str(outbox))
    monkeypatch.setenv("PARKPULSE_CIRCUIT_FAILURE_THRESHOLD", "1")
    for name in [
        "delivery_outbox.persist",
        "delivery_outbox.persist_ack",
        "delivery_outbox.persist_approval",
    ]:
        reliability.registry.breakers.pop(name, None)
    park_delivery._outbox.clear()
    original_persist = park_delivery._persist_dispatch

    monkeypatch.setattr(park_delivery, "_persist_dispatch", lambda document: (_ for _ in ()).throw(RuntimeError("disk full")))
    failed = park_delivery.send_guest_promotion({"decisionId": "recover-1", "scenarioKey": "ride_down", "message": "first"})

    assert failed["durable"] is False
    assert park_delivery.delivery_outbox_status()["ready"] is False
    assert reliability.registry.breaker("delivery_outbox.persist").state == "open"

    monkeypatch.setattr(park_delivery, "_persist_dispatch", original_persist)
    recovered = park_delivery.send_guest_promotion({"decisionId": "recover-2", "scenarioKey": "ride_down", "message": "second"})
    status = park_delivery.delivery_outbox_status()

    assert recovered["durable"] is True
    assert status["durable_count"] == 1
    assert status["ready"] is True
    assert status["circuit_breakers"]["delivery_outbox.persist"]["state"] == "closed"


def test_approval_delivery_keeps_local_proof_envelope_when_live_publish_fails(tmp_path, monkeypatch):
    outbox = tmp_path / "delivery.jsonl"
    monkeypatch.setenv("PARKPULSE_DELIVERY_OUTBOX", str(outbox))
    monkeypatch.setenv("ENABLE_PARKPULSE_FIRESTORE", "true")
    park_delivery._outbox.clear()
    monkeypatch.setattr(gcp_operations, "publish_approval_decision", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("pubsub down")))

    gated = park_delivery.send_equipment_command(
        {
            "decisionId": "approval-proof",
            "scenarioKey": "ride_down",
            "command": "hold fog",
            "requiresHumanApproval": True,
        }
    )
    approved = park_delivery.record_approval_decision(gated["id"], actor="operator", decision="approved", reason="clear")

    assert approved["status"] == "approved_for_execution"
    assert approved["approvalDelivery"]["status"] == "degraded"
    assert approved["approvalDelivery"]["pubsub"]["event_type"] == "parkpulse.delivery.approval_decision"
    assert approved["approvalDelivery"]["live_error"] == "pubsub down"


def test_lazy_operator_fallback_receipt_has_observability_and_idempotency(monkeypatch):
    async def unavailable_full_module():
        raise RuntimeError("full runtime unavailable")

    monkeypatch.setattr(main, "_get_full_module", unavailable_full_module)
    payload = asyncio.run(
        main._build_operator_payload_with_runtime(
            "Food court is down, redirect mobile orders and protect staff breaks.",
            "auto",
            True,
            "test",
        )
    )

    assert payload["status"] == "bounded_fallback"
    assert payload["run_receipt"]["available"] is True
    assert payload["observability"]["status"] == "complete"
    assert payload["run_telemetry"]["delivery"]["summary"]["total"] >= 1
    for dispatch in payload["run_telemetry"]["delivery"]["dispatches"]:
        assert dispatch["idempotencyKey"]
        assert dispatch["incidentFingerprint"] == payload["run_receipt"]["incident_fingerprint"]


def test_readyz_reports_degraded_dependencies():
    response = main._readiness_payload()

    assert response["service"] == "parkpulse-api"
    assert response["status"] in {"ok", "degraded", "not_ready"}
    assert "dependency_status" in response
    assert {"gemini", "mongo", "bigquery", "delivery_outbox"}.issubset(response["dependency_status"])


def test_run_receipt_endpoint_returns_stored_final_payload(monkeypatch):
    async def unavailable_full_module():
        raise RuntimeError("full runtime unavailable")

    monkeypatch.setattr(main, "_get_full_module", unavailable_full_module)
    payload = asyncio.run(
        main._build_operator_payload_with_runtime(
            "Guest fainted near Food Court A. Medical team and wheelchair assistance needed.",
            "auto",
            True,
            "test",
        )
    )
    receipt_id = payload["run_receipt"]["id"]

    async def call_receipt():
        sent = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        await main.app(
            {
                "type": "http",
                "method": "GET",
                "path": f"/api/park/run-receipt/{receipt_id}",
                "query_string": b"",
                "headers": [],
            },
            receive,
            send,
        )
        body = b"".join(item.get("body", b"") for item in sent if item["type"] == "http.response.body")
        return json.loads(body)

    stored = asyncio.run(call_receipt())

    assert stored["status"] == "found"
    assert stored["receipt"]["id"] == receipt_id
    assert stored["receipt"]["payload"]["run_receipt"]["id"] == receipt_id
