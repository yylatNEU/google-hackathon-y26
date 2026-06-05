import asyncio
import json

import main
import product_learning_loop as loop
import park_staff_roleplay as roleplay
from park_role_access import sign_role_session


def reset_loop(monkeypatch, tmp_path):
    monkeypatch.setenv("PARKPULSE_PRODUCT_LEARNING_LOG_PATH", str(tmp_path / "product_learning_loop.jsonl"))
    monkeypatch.setenv("PARKPULSE_STAFF_TRAINING_LOG_PATH", str(tmp_path / "staff_training_sessions.jsonl"))
    roleplay._SESSIONS.clear()


async def _call_app(method: str, path: str, body: dict | None = None, token: str | None = None, role: str | None = None):
    sent = []
    body_bytes = json.dumps(body or {}).encode("utf-8")
    received = False
    route_path, _, query = path.partition("?")
    headers = []
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode("utf-8")))
    if role:
        headers.append((b"x-parkpulse-role", role.encode("utf-8")))
    if body is not None:
        headers.append((b"content-type", b"application/json"))

    async def receive():
        nonlocal received
        if received:
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    async def send(message):
        sent.append(message)

    await main.app({"type": "http", "method": method, "path": route_path, "query_string": query.encode("utf-8"), "headers": headers}, receive, send)
    status = next(item["status"] for item in sent if item["type"] == "http.response.start")
    response_body = b"".join(item.get("body", b"") for item in sent if item["type"] == "http.response.body")
    return status, json.loads(response_body or b"{}")


def test_live_issue_and_training_gap_feed_learning_signals_with_boundaries(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)

    issue = loop.create_park_issue_ticket(
        source="guest",
        issue_type="lost_child_report",
        summary="Guardian reports missing child near carousel.",
        severity="critical",
        location="carousel",
    )
    gap = loop.create_training_gap_ticket(
        scenario_id="lost_child_report",
        gap_type="escalation",
        severity="critical_training_gap",
        evidence={"score": 49, "critical_miss": True, "open_gaps": ["Missing escalation path: Security."]},
        trainee_name="QA trainee",
        session_id="session-1",
    )
    status = loop.product_learning_loop_status()

    assert issue["ticket"]["live_ops_authority"] is True
    assert issue["ticket"]["requires_human_ack"] is True
    assert gap["ticket"]["live_ops_authority"] is False
    assert status["park_issue_ticket_count"] == 1
    assert status["training_gap_ticket_count"] == 1
    assert status["learning_signal_count"] >= 3
    assert status["loop_contract"]["training_gaps_create_live_issues"] is False
    assert any(signal["source"] == "park_issue_ticket" for signal in status["product_learning_signals"])
    assert any(signal["source"] == "training_gap_ticket" for signal in status["product_learning_signals"])
    assert any(signal["source"] == "manager_review" for signal in status["product_learning_signals"])


def test_failed_roleplay_finish_creates_training_gap_not_live_issue(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)
    session = roleplay.start_staff_training_session("lost_child_report", "Training Loop QA")
    roleplay.advance_staff_training_turn(session["id"], "Go look around and come back if you cannot find her.")

    finished = roleplay.finish_staff_training_session(session["id"])
    status = loop.product_learning_loop_status()

    assert finished["training_gap_ticket"]["status"] == "created"
    assert finished["training_gap_ticket"]["ticket"]["live_ops_authority"] is False
    assert status["park_issue_ticket_count"] == 0
    assert status["training_gap_ticket_count"] == 1
    assert status["product_learning_signals"][0]["requires_review"] is True


def test_passed_roleplay_does_not_create_training_gap_ticket(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)
    session = roleplay.start_staff_training_session("lost_child_report", "Pass QA")
    roleplay.advance_staff_training_turn(
        session["id"],
        "I am sorry. Stay with me at this meeting point while I radio Security and Operations now. What is her name, age, clothing, and last seen location?",
    )

    finished = roleplay.finish_staff_training_session(session["id"])
    status = loop.product_learning_loop_status()

    assert finished["training_gap_ticket"]["status"] == "skipped"
    assert status["training_gap_ticket_count"] == 0


def test_product_learning_api_routes_and_role_gates(monkeypatch, tmp_path):
    reset_loop(monkeypatch, tmp_path)
    worker_token = sign_role_session("test-worker", "onsite_worker", main._role_auth_secret())
    ops_token = sign_role_session("test-ops", "ops_team", main._role_auth_secret())

    issue_status, issue = asyncio.run(
        _call_app(
            "POST",
            "/api/park/product-learning/issue-ticket",
            {"source": "employee", "issueType": "heat_exhaustion_concern", "summary": "Guest looks pale in the sun."},
            token=worker_token,
        )
    )
    assert issue_status == 200
    assert issue["ticket"]["live_ops_authority"] is True

    blocked_status, blocked = asyncio.run(
        _call_app(
            "POST",
            "/api/park/product-learning/training-gap-ticket",
            {"scenarioId": "heat_exhaustion_concern", "gapType": "safety_awareness"},
            token=worker_token,
        )
    )
    assert blocked_status == 403
    assert blocked["mode"] == "role_authorization_gate"

    gap_status, gap = asyncio.run(
        _call_app(
            "POST",
            "/api/park/product-learning/training-gap-ticket",
            {"scenarioId": "heat_exhaustion_concern", "gapType": "safety_awareness", "evidence": {"score": 61}},
            token=ops_token,
        )
    )
    assert gap_status == 200
    assert gap["ticket"]["live_ops_authority"] is False

    loop_status, payload = asyncio.run(_call_app("GET", "/api/park/product-learning/loop", token=ops_token))
    assert loop_status == 200
    assert payload["park_issue_ticket_count"] == 1
    assert payload["training_gap_ticket_count"] == 1
    assert payload["learning_signal_count"] >= 1
