import asyncio
import json

import main
import park_staff_roleplay as roleplay
from park_role_access import sign_role_session


def reset_roleplay(monkeypatch, tmp_path):
    roleplay._SESSIONS.clear()
    monkeypatch.setenv("PARKPULSE_STAFF_TRAINING_LOG_PATH", str(tmp_path / "staff_training_sessions.jsonl"))
    monkeypatch.delenv("PARKPULSE_STAFF_TRAINING_LLM_GUEST", raising=False)


def test_scenario_catalog_exposes_training_boundaries(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)

    payload = roleplay.list_staff_training_scenarios()

    assert payload["status"] == "ready"
    assert payload["scenario_count"] >= 10
    assert "lost_child_report" in {scenario["id"] for scenario in payload["scenarios"]}
    assert payload["feeds_actual_reward_model"] is False
    assert payload["llm_guest_mode"]["llm_controls_score"] is False
    assert "use_llm_guest" in payload["llm_guest_mode"]["request_fields"]


def test_policy_pack_exposes_governed_training_contract(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)

    pack = roleplay.staff_training_policy_pack()

    assert pack["status"] == "ready"
    assert pack["scoring_contract"]["llm_controls_score"] is False
    assert pack["data_boundary"]["feeds_actual_reward_model"] is False
    assert "lost_child_report" in pack["critical_scenarios"]
    assert "critical_miss_rate" in pack["manager_review"]["recommended_metrics"]


def test_lost_child_missing_escalation_is_critical_miss(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)
    session = roleplay.start_staff_training_session("lost_child_report", "QA trainee")

    turn = roleplay.advance_staff_training_turn(
        session["id"],
        "I am sorry, that sounds scary. Please look around near the carousel and come back if you still cannot find her.",
    )

    assert turn["status"] == "complete"
    assert turn["critical_miss"] is True
    assert turn["turn_score"]["overall"] <= 55
    assert turn["session"]["critical_miss"] is True
    assert "Critical miss" in " ".join(turn["coaching_notes"])


def test_good_lost_child_response_passes_debrief(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)
    session = roleplay.start_staff_training_session("lost_child_report", "QA trainee")

    turn = roleplay.advance_staff_training_turn(
        session["id"],
        (
            "I am sorry, I will help right now. Please stay here at this meeting point while I radio security "
            "and operations. What is her name, age, what is she wearing, and where was she last seen near the carousel?"
        ),
    )
    finished = roleplay.finish_staff_training_session(session["id"])

    assert turn["critical_miss"] is False
    assert turn["turn_score"]["overall"] >= 80
    assert finished["debrief"]["result"] == "pass"
    assert finished["session"]["feeds_actual_reward_model"] is False


def test_analytics_summarizes_finished_sessions_only(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)
    failed = roleplay.start_staff_training_session("heat_exhaustion_concern", "One")
    roleplay.advance_staff_training_turn(failed["id"], "She can probably walk it off after drinking something.")
    roleplay.finish_staff_training_session(failed["id"])

    active = roleplay.start_staff_training_session("refund_request", "Two")
    roleplay.advance_staff_training_turn(active["id"], "I understand. I can collect details and bring Guest Services into the review.")

    analytics = roleplay.staff_training_analytics()

    assert analytics["status"] == "ready"
    assert analytics["session_count"] == 1
    assert analytics["feeds_actual_reward_model"] is False
    assert analytics["scenario_summary"][0]["scenario_id"] == "heat_exhaustion_concern"
    assert analytics["scenario_summary"][0]["critical_miss_count"] == 1


def test_assignment_readiness_and_receipts_track_manager_workflow(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)
    assignment_payload = roleplay.create_staff_training_assignment("Sam Rivera", "ride_ops", ["safety_rule_refusal"])
    assignment = assignment_payload["assignment"]

    session = roleplay.start_staff_training_session("safety_rule_refusal", "Sam Rivera", assignment_id=assignment["id"])
    roleplay.advance_staff_training_turn(
        session["id"],
        "For safety this ride cannot start until the loose strap is secured or placed in a locker. I can call my lead if you need help.",
    )
    roleplay.finish_staff_training_session(session["id"])

    readiness = roleplay.staff_training_readiness()
    receipts = roleplay.staff_training_receipts()

    assert readiness["status"] == "ready"
    assert readiness["readiness"][0]["assignment_id"] == assignment["id"]
    assert readiness["readiness"][0]["status"] == "ready_for_shadowing"
    assert readiness["readiness"][0]["live_shadowing_gate"] == "pass"
    assert receipts["receipts"][0]["assignment_id"] == assignment["id"]
    assert receipts["receipts"][0]["manager_review_required"] is False
    assert receipts["feeds_actual_reward_model"] is False


def test_manager_review_can_hold_readiness_without_overriding_score(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)
    assignment = roleplay.create_staff_training_assignment("Sam Rivera", "ride_ops", ["safety_rule_refusal"])["assignment"]

    session = roleplay.start_staff_training_session("safety_rule_refusal", "Sam Rivera", assignment_id=assignment["id"])
    roleplay.advance_staff_training_turn(
        session["id"],
        "For safety this ride cannot start until the strap is secured. I can call my lead or security and help you use a locker.",
    )
    roleplay.finish_staff_training_session(session["id"])
    assert roleplay.staff_training_readiness()["readiness"][0]["status"] == "ready_for_shadowing"

    review = roleplay.review_staff_training_receipt(session_id=session["id"], decision="require_retry", reviewer="QA lead", notes="Practice firmer de-escalation.")
    readiness = roleplay.staff_training_readiness()
    receipt = roleplay.staff_training_receipts()["receipts"][0]

    assert review["status"] == "recorded"
    assert review["review"]["decision"] == "require_retry"
    assert readiness["readiness"][0]["status"] == "needs_coaching"
    assert readiness["readiness"][0]["review_hold_count"] == 1
    assert receipt["review_status"] == "require_retry"
    assert receipt["manager_review"]["notes"] == "Practice firmer de-escalation."
    assert review["feeds_actual_reward_model"] is False


def test_certification_packet_collects_assignment_receipts_and_next_actions(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)
    assignment = roleplay.create_staff_training_assignment("Packet Trainee", "entry", ["language_barrier"])["assignment"]
    session = roleplay.start_staff_training_session("language_barrier", "Packet Trainee", assignment_id=assignment["id"])
    roleplay.advance_staff_training_turn(session["id"], "I can help with translation. Please stay here while I bring Guest Services and confirm where your family is.")
    roleplay.finish_staff_training_session(session["id"])

    packet = roleplay.staff_training_certification_packet(assignment_id=assignment["id"])

    assert packet["status"] == "ready"
    assert packet["assignment"]["id"] == assignment["id"]
    assert packet["receipts"][0]["session_id"] == session["id"]
    assert packet["gate_contract"]["manager_review_can_override_score"] is False
    assert packet["feeds_actual_reward_model"] is False
    assert packet["writes_live_dispatch"] is False
    assert packet["next_actions"]


def test_demo_seed_creates_manager_dashboard_records_once(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)

    seeded = roleplay.seed_staff_training_demo_data()
    repeated = roleplay.seed_staff_training_demo_data()

    assert seeded["status"] == "seeded"
    assert seeded["assignment_count"] >= 3
    assert seeded["readiness"]["trainee_count"] >= 3
    assert seeded["readiness"]["status_counts"]["needs_coaching"] >= 1
    assert repeated["status"] == "already_seeded"
    assert seeded["feeds_actual_reward_model"] is False


def test_llm_guest_mode_uses_mocked_guest_reply_without_changing_score(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)

    def fake_llm_guest_reply(scenario, session, employee_message, score, missing, fallback_reply):
        return {
            "status": "generated",
            "source": "llm_guest",
            "reply": "I am still upset, but I hear you calling security. Please keep me here while they start looking.",
            "model": "gemini-test",
            "llm_controls_score": False,
        }

    monkeypatch.setattr(roleplay, "_generate_llm_guest_reply", fake_llm_guest_reply)
    session = roleplay.start_staff_training_session("lost_child_report", "QA trainee", use_llm_guest=True)

    turn = roleplay.advance_staff_training_turn(
        session["id"],
        (
            "I am sorry, I will help right now. Please stay here while I radio security. "
            "What is her name, age, what is she wearing, and where was she last seen near the carousel?"
        ),
    )

    assert turn["guest_reply_source"] == "llm_guest"
    assert turn["llm_guest"]["model"] == "gemini-test"
    assert turn["turn_score"]["overall"] >= 80
    assert turn["session"]["guest_simulator"]["llm_controls_score"] is False
    assert turn["session"]["transcript"][-1]["message"].startswith("I am still upset")


def test_llm_sanitizer_blocks_meta_or_authoritative_replies():
    assert roleplay._sanitize_llm_guest_reply("As an AI, your score is 5 on the rubric.", "fallback") == "fallback"
    assert roleplay._sanitize_llm_guest_reply("Refund approved and the ride is now safe.", "fallback") == "fallback"
    assert roleplay._sanitize_llm_guest_reply("I am worried. Can you stay with me until help arrives?", "fallback").startswith("I am worried")


async def _call_app(method: str, path: str, body: dict | None = None, token: str | None = None):
    sent = []
    body_bytes = json.dumps(body or {}).encode("utf-8")
    received = False
    route_path, _, query = path.partition("?")
    headers = []
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode("utf-8")))
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


def test_staff_training_api_catalog_session_and_turn(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)
    token = sign_role_session("test-worker", "onsite_worker", main._role_auth_secret())

    catalog_status, catalog = asyncio.run(_call_app("GET", "/api/park/staff-training/scenarios", token=token))
    assert catalog_status == 200
    assert catalog["scenario_count"] >= 10

    start_status, session = asyncio.run(
        _call_app(
            "POST",
            "/api/park/staff-training/sessions",
            {"scenario_id": "lost_child_report", "trainee_name": "API QA", "useLlmGuest": False},
            token=token,
        )
    )
    assert start_status == 200
    assert session["scenario"]["id"] == "lost_child_report"
    assert session["guest_simulator"]["llm_requested"] is False

    turn_status, turn = asyncio.run(
        _call_app(
            "POST",
            "/api/park/staff-training/turn",
            {
                "session_id": session["id"],
                "employee_message": (
                    "I am sorry, I will help right now. Please stay here while I radio security. "
                    "What is her name, age, what is she wearing, and where was she last seen near the carousel?"
                ),
            },
            token=token,
        )
    )
    assert turn_status == 200
    assert turn["turn_score"]["overall"] >= 80
    assert turn["guest_reply_source"] == "deterministic"


def test_staff_training_policy_pack_api_requires_ops_scope(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)
    worker_token = sign_role_session("test-worker", "onsite_worker", main._role_auth_secret())
    ops_token = sign_role_session("test-ops", "ops_team", main._role_auth_secret())

    blocked_status, blocked = asyncio.run(_call_app("GET", "/api/park/staff-training/policy-pack", token=worker_token))
    assert blocked_status == 403
    assert blocked["mode"] == "role_authorization_gate"

    status, pack = asyncio.run(_call_app("GET", "/api/park/staff-training/policy-pack", token=ops_token))
    assert status == 200
    assert pack["mode"] == "staff_roleplay_policy_pack"
    assert pack["data_boundary"]["writes_live_dispatch"] is False


def test_staff_training_manager_api_creates_assignment_and_reads_dashboard(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)
    ops_token = sign_role_session("test-ops", "ops_team", main._role_auth_secret())

    assignment_status, assignment_payload = asyncio.run(
        _call_app(
            "POST",
            "/api/park/staff-training/assignments",
            {"traineeName": "API Manager Trainee", "staffRole": "entry", "scenarioIds": ["language_barrier"]},
            token=ops_token,
        )
    )
    assert assignment_status == 200
    assert assignment_payload["assignment"]["staff_role"] == "entry"

    readiness_status, readiness = asyncio.run(_call_app("GET", "/api/park/staff-training/readiness", token=ops_token))
    assert readiness_status == 200
    assert readiness["trainee_count"] == 1
    assert readiness["readiness"][0]["status"] == "not_started"

    seed_status, seeded = asyncio.run(_call_app("POST", "/api/park/staff-training/demo-seed", {}, token=ops_token))
    assert seed_status == 200
    assert seeded["mode"] == "staff_roleplay_demo_seed"
    assert seeded["feeds_actual_reward_model"] is False


def test_staff_training_receipt_review_api_records_manager_disposition(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)
    worker_token = sign_role_session("test-worker", "onsite_worker", main._role_auth_secret())
    ops_token = sign_role_session("test-ops", "ops_team", main._role_auth_secret())
    assignment = roleplay.create_staff_training_assignment("API Review Trainee", "guest_services", ["refund_request"])["assignment"]
    session = roleplay.start_staff_training_session("refund_request", "API Review Trainee", assignment_id=assignment["id"])
    roleplay.advance_staff_training_turn(session["id"], "I understand. I can collect your ticket details and bring Guest Services into the policy review.")
    roleplay.finish_staff_training_session(session["id"])

    blocked_status, blocked = asyncio.run(
        _call_app("POST", "/api/park/staff-training/receipt-review", {"sessionId": session["id"], "decision": "hold"}, token=worker_token)
    )
    assert blocked_status == 403
    assert blocked["mode"] == "role_authorization_gate"

    status, payload = asyncio.run(
        _call_app(
            "POST",
            "/api/park/staff-training/receipt-review",
            {"sessionId": session["id"], "decision": "hold", "reviewer": "Ops QA", "notes": "Needs manager shadowing first."},
            token=ops_token,
        )
    )
    assert status == 200
    assert payload["status"] == "recorded"
    assert payload["review"]["decision"] == "hold"
    assert payload["receipt"]["review_status"] == "hold"
    assert payload["feeds_actual_reward_model"] is False


def test_staff_training_certification_packet_api_requires_ops_scope(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)
    worker_token = sign_role_session("test-worker", "onsite_worker", main._role_auth_secret())
    ops_token = sign_role_session("test-ops", "ops_team", main._role_auth_secret())
    assignment = roleplay.create_staff_training_assignment("Packet API Trainee", "entry", ["language_barrier"])["assignment"]

    blocked_status, blocked = asyncio.run(_call_app("GET", f"/api/park/staff-training/certification-packet?assignment_id={assignment['id']}", token=worker_token))
    assert blocked_status == 403
    assert blocked["mode"] == "role_authorization_gate"

    status, packet = asyncio.run(_call_app("GET", f"/api/park/staff-training/certification-packet?assignment_id={assignment['id']}", token=ops_token))
    assert status == 200
    assert packet["mode"] == "staff_roleplay_certification_packet"
    assert packet["assignment"]["id"] == assignment["id"]
    assert packet["gate_contract"]["manager_review_can_override_score"] is False
