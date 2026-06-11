import asyncio
import copy
import json
import sys
import types

import main
import product_learning_loop as loop
import park_staff_roleplay as roleplay
from park_role_access import sign_role_session


def reset_roleplay(monkeypatch, tmp_path):
    roleplay._SESSIONS.clear()
    monkeypatch.setenv("PARKPULSE_STAFF_TRAINING_LOG_PATH", str(tmp_path / "staff_training_sessions.jsonl"))
    monkeypatch.setenv("PARKPULSE_PRODUCT_LEARNING_LOG_PATH", str(tmp_path / "product_learning_loop.jsonl"))
    monkeypatch.setenv("PARKPULSE_PRODUCT_LEARNING_DB_PATH", str(tmp_path / "product_learning_loop.sqlite"))
    monkeypatch.delenv("PARKPULSE_STAFF_TRAINING_LLM_GUEST", raising=False)


def test_scenario_catalog_exposes_training_boundaries(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)

    payload = roleplay.list_staff_training_scenarios()

    assert payload["status"] == "ready"
    assert payload["scenario_count"] >= 10
    assert "lost_child_report" in {scenario["id"] for scenario in payload["scenarios"]}
    assert payload["feeds_actual_reward_model"] is False
    assert payload["llm_guest_mode"]["llm_controls_score"] is False
    assert payload["llm_guest_mode"]["provider_status"]["llm_controls_score"] is False
    assert "platform" in payload["llm_guest_mode"]["provider_status"]
    assert "use_llm_guest" in payload["llm_guest_mode"]["request_fields"]


def test_staff_roleplay_session_persistence_helpers_and_assignment_reads(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)

    assert roleplay._iso_timestamp("") == 0.0
    assert roleplay._iso_timestamp("bad") == 0.0
    assert roleplay._iso_timestamp("2026-06-10T12:00:00Z") > 0
    assert roleplay._read_jsonl() == []
    assert roleplay._get_staff_training_session("") is None

    roleplay._persist_staff_training_session({"id": ""})
    persisted_documents = []

    class FakeCollection:
        def replace_one(self, query, document, upsert=False):
            persisted_documents.append((query, document, upsert))

    monkeypatch.setitem(
        sys.modules,
        "mongo_memory",
        types.SimpleNamespace(
            _clean_for_bson=lambda value: value,
            _ensure_memory_initialized=lambda: None,
            _memory=types.SimpleNamespace(_collection=lambda name: FakeCollection()),
        ),
    )
    roleplay._persist_staff_training_session({"id": "mongo-session", "scenario_id": "refund_request", "trainee_name": "Mongo QA"})
    assert persisted_documents[0][0] == {"_id": "mongo-session"}
    assert persisted_documents[0][2] is True

    monkeypatch.setitem(
        sys.modules,
        "mongo_memory",
        types.SimpleNamespace(
            _clean_for_bson=lambda value: value,
            _ensure_memory_initialized=lambda: (_ for _ in ()).throw(RuntimeError("mongo down")),
            _memory=types.SimpleNamespace(_collection=lambda name: FakeCollection()),
        ),
    )
    roleplay._persist_staff_training_session({"id": "ignored-session", "scenario_id": "refund_request"})

    log_path = tmp_path / "staff_training_sessions.jsonl"
    log_path.write_text(
        "\n".join(
            [
                "{bad json}",
                json.dumps({"event": "assignment_created", "id": "assign-1", "scenario_ids": ["refund_request"], "staff_role": "guest_services"}),
                json.dumps({"event": "session_finished", "assignment_id": "assign-1", "scenario_id": "refund_request", "scorecard": {"overall": 88}, "critical_miss": False}),
            ]
        ),
        encoding="utf-8",
    )
    rows = roleplay._read_jsonl()
    assert [row["event"] for row in rows] == ["assignment_created", "session_finished"]
    assignments = roleplay.list_staff_training_assignments()
    assert assignments["status"] == "ready"
    assert assignments["assignments"][0]["status"] in {"ready_for_shadowing", "complete", "assigned"}
    assert roleplay.staff_training_certification_packet(assignment_id="missing")["status"] == "not_found"
    assert roleplay.review_staff_training_receipt(decision="bad")["status"] == "invalid"
    assert roleplay.review_staff_training_receipt(session_id="missing", decision="hold")["status"] == "not_found"
    assert roleplay.finish_staff_training_session("missing")["status"] == "not_found"
    empty_analytics_path = tmp_path / "empty_staff_training_sessions.jsonl"
    monkeypatch.setenv("PARKPULSE_STAFF_TRAINING_LOG_PATH", str(empty_analytics_path))
    assert roleplay.staff_training_analytics()["status"] == "empty"
    monkeypatch.setenv("PARKPULSE_STAFF_TRAINING_LOG_PATH", str(log_path))

    normalized = roleplay._normalize_staff_training_session({"id": "session-1", "scenario_id": "missing", "trainee_name": "A" * 200})
    assert normalized["scenario_id"] == "lost_child_report"
    assert normalized["status"] == "active"
    assert normalized["transcript"][0]["speaker"] == "guest"
    assert len(normalized["trainee_name"]) == 80

    monkeypatch.setitem(
        sys.modules,
        "mongo_memory",
        types.SimpleNamespace(
            get_memory_document=lambda collection, session_id: {
                "session": {
                    "id": session_id,
                    "scenario_id": "refund_request",
                    "trainee_name": "Persisted QA",
                    "status": "active",
                }
            }
        ),
    )
    loaded = roleplay._load_persisted_staff_training_session("persisted-session")
    assert loaded["id"] == "persisted-session"
    assert roleplay._SESSIONS["persisted-session"]["scenario_id"] == "refund_request"
    assert roleplay._load_persisted_staff_training_session("") is None

    monkeypatch.setitem(sys.modules, "mongo_memory", types.SimpleNamespace(get_memory_document=lambda collection, session_id: None))
    log_path.write_text(
        "\n".join(
            [
                json.dumps({"event": "session_started", "id": "other-session", "scenario_id": "refund_request"}),
                json.dumps(
                    {
                        "event": "session_finished",
                        "session_id": "fallback-session",
                        "scenario_id": "refund_request",
                        "trainee_name": "Fallback QA",
                        "assignment_id": "assign-2",
                        "status": "finished",
                        "turn_count": 2,
                        "scorecard": {"overall": 84},
                        "critical_miss": False,
                        "active_learning_versions": [{"version_id": "v2", "summary": "refund escalation"}],
                        "active_learning_version_ids": ["v2"],
                        "learning_version_guidance": ["Escalate refund policy review."],
                        "retrieved_training_context": {"counts": {"prior_sessions": 1}},
                        "agent_contract": {"mode": "training_only"},
                        "agent_tool_manifest": [{"id": "staff_training.retrieve_context"}],
                        "tool_trace": [{"tool": "staff_training.retrieve_context"}],
                        "completed_objectives": ["Acknowledge"],
                        "missing_objectives": [],
                        "created_at": "2026-06-10T12:30:00Z",
                        "transcript": [{"speaker": "guest", "message": "The ride closed and I want a refund."}],
                        "scores": [{"overall": 84}],
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    fallback = roleplay._load_persisted_staff_training_session("fallback-session")
    assert fallback["id"] == "fallback-session"
    assert fallback["scenario_id"] == "refund_request"
    assert fallback["scorecard"]["overall"] == 84
    assert fallback["agent_tool_manifest"][0]["id"] == "staff_training.retrieve_context"
    assert roleplay._SESSIONS["fallback-session"]["assignment_id"] == "assign-2"


def test_staff_roleplay_optional_dependency_error_fallbacks(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)

    monkeypatch.setitem(
        sys.modules,
        "product_learning_loop",
        types.SimpleNamespace(
            active_learning_versions_for_scenario=lambda scenario_id, target_surface=None: (_ for _ in ()).throw(RuntimeError("version lookup failed")),
            guest_triage_training_memory=lambda scenario_id, limit=80: (_ for _ in ()).throw(RuntimeError("memory lookup failed")),
            recommended_training_scenarios_from_guest_triage=lambda limit=12: (_ for _ in ()).throw(RuntimeError("recommendation failed")),
        ),
    )
    assert roleplay._active_learning_versions_for_scenario("refund_request") == []
    memory = roleplay._guest_triage_training_memory("refund_request")
    assert memory["status"] == "error"
    assert "memory lookup failed" in memory["readiness_issues"][0]
    assert roleplay._guest_triage_assignment_recommendations("guest_services") == []

    monkeypatch.setitem(
        sys.modules,
        "gemini_provider",
        types.SimpleNamespace(
            get_gemini_agent_properties=lambda: (_ for _ in ()).throw(RuntimeError("provider config failed")),
            get_gemini_model=lambda: "unused",
        ),
    )
    provider = roleplay._llm_guest_provider_status()
    assert provider["ready"] is False
    assert provider["provider"] == "unknown"
    assert "provider config failed" in provider["readiness_issues"][0]


def test_staff_roleplay_json_sanitize_and_gemini_worker_branches(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)

    assert roleplay._first_json_object("") is None
    assert roleplay._first_json_object("[1]") is None
    assert roleplay._first_json_object("prefix {\"x\": 1} suffix") == {"x": 1}
    assert roleplay._first_json_object("prefix {bad} suffix") is None
    assert roleplay._first_json_object("no object") is None

    assert roleplay._sanitize_llm_guest_reply("", "fallback") == "fallback"
    assert roleplay._sanitize_llm_guest_reply("As an AI trainer, your score needs work.", "fallback") == "fallback"
    long_reply = "Safe guest reply. " * 40
    assert roleplay._sanitize_llm_guest_reply(long_reply, "fallback") == ("Safe guest reply. " * 40)[:420]

    calls = []

    def run_success(args, **kwargs):
        calls.append((args, kwargs))
        return types.SimpleNamespace(returncode=0, stdout=json.dumps({"ok": True, "guest_reply": "Thanks"}), stderr="")

    monkeypatch.setattr(roleplay.subprocess, "run", run_success)
    payload = roleplay._generate_gemini_json_sync_hard_timeout(
        {"task": "guest-reply"},
        timeout_seconds=0.1,
        max_output_tokens=32,
        temperature=0.0,
    )
    assert payload["guest_reply"] == "Thanks"
    assert calls[0][1]["check"] is False
    assert json.loads(calls[0][1]["input"])["max_output_tokens"] == 32

    monkeypatch.setattr(
        roleplay.subprocess,
        "run",
        lambda *args, **kwargs: types.SimpleNamespace(returncode=7, stdout="", stderr="worker stderr"),
    )
    try:
        roleplay._generate_gemini_json_sync_hard_timeout({}, timeout_seconds=0.1, max_output_tokens=8, temperature=0.0)
        assert False, "expected nonzero worker exit to raise"
    except RuntimeError as error:
        assert "worker stderr" in str(error)

    monkeypatch.setattr(
        roleplay.subprocess,
        "run",
        lambda *args, **kwargs: types.SimpleNamespace(returncode=0, stdout="not-json", stderr=""),
    )
    try:
        roleplay._generate_gemini_json_sync_hard_timeout({}, timeout_seconds=0.1, max_output_tokens=8, temperature=0.0)
        assert False, "expected invalid worker JSON to raise"
    except RuntimeError as error:
        assert "invalid JSON" in str(error)

    monkeypatch.setattr(
        roleplay.subprocess,
        "run",
        lambda *args, **kwargs: types.SimpleNamespace(returncode=0, stdout=json.dumps({"ok": False, "error": "provider unavailable"}), stderr=""),
    )
    try:
        roleplay._generate_gemini_json_sync_hard_timeout({}, timeout_seconds=0.1, max_output_tokens=8, temperature=0.0)
        assert False, "expected provider failure payload to raise"
    except RuntimeError as error:
        assert "provider unavailable" in str(error)

    def run_timeout(*args, **kwargs):
        raise roleplay.subprocess.TimeoutExpired(cmd=["gemini-worker"], timeout=0.6)

    monkeypatch.setattr(roleplay.subprocess, "run", run_timeout)
    try:
        roleplay._generate_gemini_json_sync_hard_timeout({}, timeout_seconds=0.1, max_output_tokens=8, temperature=0.0)
        assert False, "expected timeout to raise"
    except TimeoutError as error:
        assert "hard timeout" in str(error)


def test_policy_pack_exposes_governed_training_contract(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)

    pack = roleplay.staff_training_policy_pack()

    assert pack["status"] == "ready"
    assert pack["scoring_contract"]["llm_controls_score"] is False
    assert pack["scoring_contract"]["golden_eval_case_count"] >= 40
    assert pack["llm_guest_contract"]["provider_status"]["llm_controls_score"] is False
    assert pack["data_boundary"]["feeds_actual_reward_model"] is False
    assert "lost_child_report" in pack["critical_scenarios"]
    assert "critical_miss_rate" in pack["manager_review"]["recommended_metrics"]
    assert pack["agent_contract"]["rag_contract"]["llm_controls_score"] is False
    assert "staff_training.retrieve_context" in {tool["id"] for tool in pack["tool_manifest"]}
    assert "live_dispatch.execute" in pack["blocked_tools"]


def test_training_context_retrieves_prior_session_memory_and_tool_manifest(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)
    prior = roleplay.start_staff_training_session("lost_child_report", "Memory trainee")
    roleplay.advance_staff_training_turn(prior["id"], "I am sorry. What is she wearing?")
    roleplay.finish_staff_training_session(prior["id"])
    roleplay.review_staff_training_receipt(prior["id"], decision="require_retry", reviewer="QA lead", notes="Escalation and safety wording were still unclear.")

    context = roleplay.retrieve_staff_training_context("lost_child_report", trainee_name="Memory trainee")

    assert context["mode"] == "staff_training_rag_context"
    assert context["retrieved"]["prior_sessions"]
    assert context["retrieved"]["prior_sessions"][0]["critical_miss"] is True
    assert context["retrieved"]["training_gap_patterns"]
    assert context["retrieved"]["policy_snippets"]
    assert context["retrieved"]["manager_reviews"][0]["decision"] == "require_retry"
    assert context["retrieved"]["trainee_profile"]["coaching_priority"]
    assert "staff_training.score_turn" in context["tool_manifest_ids"]
    assert "reward_model.write_label" in context["blocked_tools"]


def test_guest_triage_memory_enriches_training_context_and_assignment_priority(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)
    try:
        import mongo_memory

        mongo_memory._memory._fallback["guest_messages"] = []
    except Exception:
        pass

    triage = loop.triage_guest_message(
        message="I paid for tickets and the ride closed. I want a refund or someone who can explain compensation.",
        guest_name="Test Guest",
        location="Guest Services",
        create_ticket=True,
    )

    context = roleplay.retrieve_staff_training_context("refund_request", trainee_name="Guest Services QA")
    assignment = roleplay.create_staff_training_assignment("Guest Services QA", "guest_services", [])

    assert triage["memory_persistence"]["collection"] == "guest_messages"
    assert triage["memory_persistence"]["scenario_id"] == "refund_request"
    assert context["counts"]["guest_triage_patterns"] >= 1
    assert context["counts"]["historical_ticket_frequency"] >= 1
    assert context["retrieved"]["guest_triage_patterns"][0]["issue_type"] == "refund_request"
    assert context["retrieved"]["historical_ticket_frequency"][0]["scenario_id"] == "refund_request"
    assert context["retrieved"]["scenario_recommendation"]["scenario_id"] == "refund_request"
    assert roleplay._llm_context_excerpt(context)["historical_ticket_frequency"][0]["ticket_count"] >= 1
    assert assignment["assignment"]["source"] == "guest_triage_memory_prioritized"
    assert assignment["assignment"]["scenario_ids"][0] == "refund_request"
    assert assignment["assignment"]["source_signals"][0]["source"] == "guest_triage_memory"


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
    assert turn["turn_score"]["turn_coaching"]["verdict"] == "critical_miss"
    assert "Security" in turn["turn_score"]["turn_coaching"]["next_response"]
    assert turn["turn_score"]["turn_coaching"]["misses"]


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
    assert turn["turn_score"]["turn_coaching"]["verdict"] in {"passing", "strong"}
    assert turn["turn_score"]["turn_coaching"]["strengths"]
    assert finished["debrief"]["result"] == "pass"
    assert finished["session"]["feeds_actual_reward_model"] is False


def test_multi_turn_mastery_tracks_repaired_gaps(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)
    session = roleplay.start_staff_training_session("lost_child_report", "Repair trainee")

    first = roleplay.advance_staff_training_turn(session["id"], "I am sorry. What is she wearing?")
    assert first["critical_miss"] is True
    assert first["mastery_tracker"]["unrepaired_critical_count"] > 0
    assert first["mastery_tracker"]["mastery_level"] == "blocked"

    second = roleplay.advance_staff_training_turn(
        session["id"],
        "I am sorry. Stay with me at this meeting point while I radio Security and Operations now. What is her name, age, clothing, and last seen location?",
    )

    assert second["turn_score"]["critical_miss"] is False
    assert second["mastery_tracker"]["repair_count"] > 0
    assert second["mastery_tracker"]["latest_repairs"]
    assert second["mastery_tracker"]["mastery_level"] in {"repaired", "repairing", "on_track"}
    assert second["session"]["mastery_tracker"]["repair_count"] == second["mastery_tracker"]["repair_count"]


def test_common_policy_correct_responses_clear_shadowing_threshold(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)
    examples = {
        "angry_parent": (
            "I am sorry this happened. I will listen, confirm what was communicated, show you the nearest open alternatives, "
            "and bring Guest Services into any compensation review."
        ),
        "ride_closure_complaint": (
            "I am sorry for the wait. I cannot promise a reopen time until clearance, but I can show open alternatives "
            "and connect Guest Services for refund questions."
        ),
        "accessibility_accommodation": (
            "I can help without asking for medical details. Let me get shade or seating and contact Accessibility or "
            "Guest Services to confirm the accommodation route."
        ),
        "refund_request": (
            "I understand. I cannot promise a refund myself, but I can collect the ticket details and bring Guest Services "
            "or a supervisor into the policy review."
        ),
    }

    for scenario_id, message in examples.items():
        session = roleplay.start_staff_training_session(scenario_id, "Policy QA")
        turn = roleplay.advance_staff_training_turn(session["id"], message)
        assert turn["critical_miss"] is False
        assert turn["turn_score"]["overall"] >= 75, (scenario_id, turn["turn_score"])
        assert turn["turn_score"]["turn_coaching"]["verdict"] in {"passing", "strong"}


def test_golden_eval_passes_all_calibration_cases(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)

    payload = roleplay.staff_training_golden_eval()

    assert payload["status"] == "pass"
    assert payload["case_count"] >= 40
    assert payload["scenario_count"] == 10
    assert payload["fail_count"] == 0
    assert payload["scoring_contract"]["llm_controls_score"] is False
    assert payload["feeds_actual_reward_model"] is False
    assert {row["label"] for row in payload["label_summary"]} == {"bad", "excellent", "partial", "passing"}


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


def test_shadow_evaluator_comments_without_score_authority(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)

    import gemini_provider

    fake_props = types.SimpleNamespace(
        ready=True,
        provider="Vertex AI Gemini",
        platform="vertex_ai",
        use_vertex_ai=True,
        readiness_issues=[],
        required_env=[],
    )
    captured = {}

    def fake_generate(prompt, *, timeout_seconds, max_output_tokens, temperature):
        captured["prompt"] = prompt
        return {
            "ok": True,
            "transport": "vertex_ai_rest",
            "text": json.dumps(
                {
                    "alignment": "aligned",
                    "summary": "The deterministic rubric is aligned with the response.",
                    "coaching_focus": ["Keep escalation explicit."],
                    "rubric_disagreement": "",
                    "suggested_human_review": False,
                    "score_authority": False,
                }
            ),
        }

    monkeypatch.setattr(gemini_provider, "get_gemini_agent_properties", lambda: fake_props)
    monkeypatch.setattr(gemini_provider, "get_gemini_model", lambda: "gemini-2.5-flash")
    monkeypatch.setattr(roleplay, "_generate_gemini_json_sync_hard_timeout", fake_generate)

    session = roleplay.start_staff_training_session("lost_child_report", "Shadow trainee", use_llm_guest=False)
    turn = roleplay.advance_staff_training_turn(
        session["id"],
        "I am sorry. Stay with me while I call Security now. What is her name, age, clothing, and last seen location?",
        use_shadow_eval=True,
    )

    assert turn["turn_score"]["overall"] >= 75
    assert turn["shadow_evaluator"]["status"] == "generated"
    assert turn["shadow_evaluator"]["score_authority"] is False
    assert turn["shadow_evaluator"]["llm_controls_score"] is False
    assert turn["shadow_evaluator"]["transport"] == "vertex_ai_rest"
    assert captured["prompt"]["deterministic_score"]["overall"] == turn["turn_score"]["overall"]
    assert captured["prompt"]["response_schema"]["score_authority"] is False


def test_vertex_guest_generator_uses_provider_without_changing_score(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)

    fake_props = types.SimpleNamespace(
        ready=True,
        provider="Vertex AI Gemini",
        platform="vertex_ai",
        use_vertex_ai=True,
        readiness_issues=[],
        required_env=[],
    )
    captured = {}

    def fake_generate(prompt, *, timeout_seconds, max_output_tokens, temperature):
        captured["prompt"] = prompt
        captured["timeout_seconds"] = timeout_seconds
        captured["max_output_tokens"] = max_output_tokens
        captured["temperature"] = temperature
        return {
            "ok": True,
            "transport": "google_genai_sdk",
            "text": json.dumps(
                {
                    "guest_reply": "I am scared, but I hear you calling Security. She is wearing a pink shirt and light-up shoes.",
                    "emotion": "worried",
                    "pressure_level": "high",
                }
            ),
        }

    import gemini_provider

    monkeypatch.setattr(gemini_provider, "get_gemini_agent_properties", lambda: fake_props)
    monkeypatch.setattr(gemini_provider, "get_gemini_model", lambda: "gemini-2.5-flash")
    monkeypatch.setattr(roleplay, "_generate_gemini_json_sync_hard_timeout", fake_generate)

    session = roleplay.start_staff_training_session("lost_child_report", "Vertex trainee", use_llm_guest=True)
    turn = roleplay.advance_staff_training_turn(
        session["id"],
        "I am sorry, I will help right now. Please stay here while I radio security. What is she wearing and where was she last seen?",
        use_llm_guest=True,
    )

    assert turn["turn_score"]["overall"] >= 80
    assert turn["guest_reply_source"] == "llm_guest"
    assert turn["llm_guest"]["provider"] == "Vertex AI Gemini"
    assert turn["llm_guest"]["platform"] == "vertex_ai"
    assert turn["llm_guest"]["vertex_ai_ready"] is True
    assert turn["llm_guest"]["transport"] == "google_genai_sdk"
    assert turn["llm_guest"]["emotion"] == "worried"
    assert turn["session"]["guest_simulator"]["llm_controls_score"] is False
    assert captured["timeout_seconds"] == 4
    assert captured["prompt"]["vertex_ai_contract"]["never_controls_score"] is True
    assert captured["prompt"]["scenario"]["id"] == "lost_child_report"


def test_vertex_guest_generator_timeout_falls_back_without_changing_score(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)

    import gemini_provider

    fake_props = types.SimpleNamespace(
        ready=True,
        provider="Vertex AI Gemini",
        platform="vertex_ai",
        use_vertex_ai=True,
        readiness_issues=[],
        required_env=[],
    )
    monkeypatch.setattr(gemini_provider, "get_gemini_agent_properties", lambda: fake_props)
    monkeypatch.setattr(gemini_provider, "get_gemini_model", lambda: "gemini-2.5-flash")
    monkeypatch.setattr(roleplay, "_generate_gemini_json_sync_hard_timeout", lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("Gemini provider exceeded hard timeout of 1s")))

    session = roleplay.start_staff_training_session("lost_child_report", "Vertex timeout", use_llm_guest=True)
    turn = roleplay.advance_staff_training_turn(
        session["id"],
        "I am sorry. Stay here while I call security now. What is she wearing and where was she last seen?",
        use_llm_guest=True,
    )

    assert turn["turn_score"]["overall"] >= 80
    assert turn["guest_reply_source"] == "deterministic"
    assert turn["llm_guest"]["status"] == "fallback_timeout"
    assert turn["llm_guest"]["platform"] == "vertex_ai"
    assert turn["llm_guest"]["vertex_ai_ready"] is True
    assert turn["session"]["guest_simulator"]["llm_controls_score"] is False


def test_vertex_guest_generator_falls_back_when_not_configured(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)

    import gemini_provider

    fake_props = types.SimpleNamespace(
        ready=False,
        provider="Vertex AI Gemini",
        platform="vertex_ai",
        use_vertex_ai=True,
        readiness_issues=["GOOGLE_CLOUD_PROJECT is missing."],
        required_env=["GOOGLE_GENAI_USE_VERTEXAI=true", "GOOGLE_CLOUD_PROJECT"],
    )
    monkeypatch.setattr(gemini_provider, "get_gemini_agent_properties", lambda: fake_props)

    session = roleplay.start_staff_training_session("lost_child_report", "Vertex fallback", use_llm_guest=True)
    turn = roleplay.advance_staff_training_turn(
        session["id"],
        "I am sorry. Please stay here while I call security. What is she wearing?",
        use_llm_guest=True,
    )

    assert turn["guest_reply_source"] == "deterministic"
    assert turn["llm_guest"]["status"] == "fallback_not_configured"
    assert turn["llm_guest"]["platform"] == "vertex_ai"
    assert turn["llm_guest"]["vertex_ai_ready"] is False
    assert "GOOGLE_CLOUD_PROJECT is missing." in turn["llm_guest"]["readiness_issues"]


def test_llm_sanitizer_blocks_meta_or_authoritative_replies():
    assert roleplay._sanitize_llm_guest_reply("As an AI, your score is 5 on the rubric.", "fallback") == "fallback"
    assert roleplay._sanitize_llm_guest_reply("Needs a clearer answer.", "fallback") == "fallback"
    assert roleplay._sanitize_llm_guest_reply("The employee response is not clear enough.", "fallback") == "fallback"
    assert roleplay._sanitize_llm_guest_reply("Refund approved and the ride is now safe.", "fallback") == "fallback"
    assert roleplay._sanitize_llm_guest_reply("I am worried. Can you stay with me until help arrives?", "fallback").startswith("I am worried")


def test_llm_guest_meta_feedback_falls_back_to_interactive_guest_reply(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)

    import gemini_provider

    fake_props = types.SimpleNamespace(
        ready=True,
        provider="Vertex AI Gemini",
        platform="vertex_ai",
        use_vertex_ai=True,
        readiness_issues=[],
        required_env=[],
    )

    def fake_generate(prompt, *, timeout_seconds, max_output_tokens, temperature):
        return {
            "ok": True,
            "transport": "google_genai_sdk",
            "text": json.dumps({"guest_reply": "Needs a clearer answer.", "emotion": "confused", "pressure_level": "medium"}),
        }

    monkeypatch.setattr(gemini_provider, "get_gemini_agent_properties", lambda: fake_props)
    monkeypatch.setattr(gemini_provider, "get_gemini_model", lambda: "gemini-2.5-flash")
    monkeypatch.setattr(roleplay, "_generate_gemini_json_sync_hard_timeout", fake_generate)

    session = roleplay.start_staff_training_session("lost_child_report", "Meta trainee", use_llm_guest=True)
    turn = roleplay.advance_staff_training_turn(
        session["id"],
        "I am sorry. What is she wearing?",
        use_llm_guest=True,
    )

    assert turn["guest_reply_source"] == "deterministic"
    assert turn["llm_guest"]["status"] == "fallback_sanitized"
    assert turn["guest_reply"] != "Needs a clearer answer."
    assert "Security" in turn["guest_reply"]
    assert turn["session"]["transcript"][-1]["source"] == "deterministic"


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
    assert session["retrieved_training_context"]["mode"] == "staff_training_rag_context"
    assert session["retrieved_training_context"]["retrieved"]["policy_snippets"]
    assert "staff_training.generate_guest_turn" in {tool["id"] for tool in session["agent_tool_manifest"]}
    assert session["tool_trace"][0]["tool"] == "staff_training.retrieve_context"

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
    assert [item["tool"] for item in turn["tool_trace"]][:4] == [
        "staff_training.retrieve_context",
        "staff_training.score_turn",
        "staff_training.update_mastery_memory",
        "staff_training.generate_guest_turn",
    ]


def test_staff_training_turn_recovers_persisted_session_after_instance_cache_miss(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)
    persisted: dict[str, dict] = {}

    def persist(session):
        persisted[str(session["id"])] = copy.deepcopy(session)

    def load(session_id):
        session = persisted.get(str(session_id))
        return copy.deepcopy(session) if session else None

    monkeypatch.setattr(roleplay, "_persist_staff_training_session", persist)
    monkeypatch.setattr(roleplay, "_load_persisted_staff_training_session", load)

    session = roleplay.start_staff_training_session("lost_child_report", "Cloud Run QA", use_llm_guest=False)
    roleplay._SESSIONS.clear()

    turn = roleplay.advance_staff_training_turn(
        session["id"],
        "I am sorry, I will help right now. Please stay here while I call security. What is she wearing and where was she last seen?",
        use_llm_guest=False,
    )

    assert turn["status"] == "complete"
    assert turn["session"]["id"] == session["id"]
    assert turn["session"]["turn_count"] == 1
    assert turn["session"]["transcript"][1]["speaker"] == "employee"


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
    assert pack["rag_contract"]["retrieval_method"] == "scenario_and_trainee_lexical_jsonl_plus_product_learning_versions"

    context_status, context = asyncio.run(_call_app("GET", "/api/park/staff-training/agent-context?scenario_id=lost_child_report&trainee_name=Ops", token=ops_token))
    assert context_status == 200
    assert context["mode"] == "staff_training_rag_context"
    assert "staff_training.retrieve_context" in context["tool_manifest_ids"]


def test_staff_training_golden_eval_api_requires_ops_scope(monkeypatch, tmp_path):
    reset_roleplay(monkeypatch, tmp_path)
    worker_token = sign_role_session("test-worker", "onsite_worker", main._role_auth_secret())
    ops_token = sign_role_session("test-ops", "ops_team", main._role_auth_secret())

    blocked_status, blocked = asyncio.run(_call_app("GET", "/api/park/staff-training/golden-eval", token=worker_token))
    assert blocked_status == 403
    assert blocked["mode"] == "role_authorization_gate"

    status, payload = asyncio.run(_call_app("GET", "/api/park/staff-training/golden-eval", token=ops_token))
    assert status == 200
    assert payload["status"] == "pass"
    assert payload["case_count"] >= 40
    assert payload["fail_count"] == 0
    assert payload["scoring_contract"]["llm_controls_score"] is False


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
