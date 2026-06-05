import asyncio
from copy import deepcopy
import json
import os
import time

os.environ.setdefault("MONGODB_DISABLE_DRIVER_IMPORT", "1")

from agent_role_skills import build_agent_role_product_readiness_report, build_deliberate_role_eval_report, build_deliberate_role_negative_fixtures, evaluate_agent_role_trace, list_agent_role_skills, route_agent_role
from agent_role_trace_samples import build_adversarial_sampled_role_trace_eval_report, build_sampled_agent_role_trace_eval_report, latest_agent_role_trace_samples
from prod_reliability_qa_agent import run_production_reliability_qa

import main
import parkpulse_api


def test_production_reliability_qa_contract_is_read_only():
    report = run_production_reliability_qa("pre-deploy reliability qa")

    assert report["role"] == "qa"
    assert report["agent"]["permissions"]["dispatch"] is False
    assert report["go_no_go_recommendation"]["decision"] == "GO WITH CONDITIONS"
    assert {item["mode"] for item in report["failure_mode_matrix"]} >= {
        "unavailable_llm",
        "policy_validation_failure",
        "dispatch_failure",
        "stream_interruption",
    }


def test_role_registry_routes_production_reliability_qa():
    registry = list_agent_role_skills()
    roles = {role["mode"]: role for role in registry["roles"]}

    assert "qa" in roles
    assert roles["qa"]["permissions"]["dispatch"] is False
    assert ".agents/skills/parkpulse-production-reliability-qa-agent/SKILL.md" in registry["proof"]["skill_paths"]
    assert route_agent_role("production reliability QA go/no-go", "auto")["selected_role"] == "qa"
    assert route_agent_role("anything", "qa")["selected_role"] == "qa"
    assert all(role.get("understanding_contract", {}).get("must_understand") for role in roles.values())
    assert all(role.get("deliberate_tool_use", {}).get("required_sequence") for role in roles.values())
    assert registry["deliberate_eval"]["applies_to"] == ["scan", "react", "proact", "customer", "qa"]


def test_every_agent_role_has_passing_deliberate_tool_eval():
    for mode in ("scan", "react", "proact", "customer", "qa"):
        route = route_agent_role("role eval", mode)
        trace = main._role_tool_trace(route, selected_role=mode, scenario_key=f"{mode}_unit")
        eval_result = trace["deliberate_eval"]

        assert eval_result["role"] == mode
        assert eval_result["status"] == "passed"
        assert eval_result["score"] >= 88
        assert eval_result["ordered"] is True
        assert eval_result["forbidden_present"] == []
        assert eval_result["required_without_output"] == []
        assert eval_result["critical_failures"] == []
        assert eval_result["policy_evidence_ok"] is True
        assert eval_result["dispatch_receipts_ok"] is True


def test_deliberate_role_eval_report_covers_all_roles():
    report = build_deliberate_role_eval_report()

    assert report["status"] == "passed"
    assert report["decision"] == "allow_role_agent_deliberate_tool_use_claim"
    assert report["passed_role_count"] == 5
    assert {row["role"] for row in report["roles"]} == {"scan", "react", "proact", "customer", "qa"}
    assert all(row["trace"]["deliberate_eval"]["status"] == "passed" for row in report["roles"])


def test_real_role_eval_report_uses_actual_role_payloads():
    report = asyncio.run(main._real_agent_role_eval_report())

    assert report["status"] == "passed"
    assert report["decision"] == "allow_real_trace_role_agent_tool_use_claim"
    assert report["release_gate"]["status"] == "passed"
    assert report["negative_fixtures"]["status"] == "passed"
    assert report["product_readiness"]["status"] == "passed"
    assert report["product_readiness"]["product_ready_role_count"] == 5
    assert report["average_score"] >= 88
    assert {row["role"] for row in report["roles"]} == {"scan", "react", "proact", "customer", "qa"}
    assert all(row["trace_eval"]["status"] == "passed" for row in report["roles"])
    assert all(row["output_eval"]["status"] == "passed" for row in report["roles"])
    assert all(row["trace_eval"]["required_without_output"] == [] for row in report["roles"])
    assert all(row["trace_eval"]["critical_failures"] == [] for row in report["roles"])


def test_product_readiness_report_marks_each_role_ready():
    synthetic = build_deliberate_role_eval_report()
    real = asyncio.run(main._real_agent_role_eval_report())
    product = build_agent_role_product_readiness_report(
        real,
        synthetic_report=synthetic,
        adversarial_report=real["adversarial_sampled"],
        negative_report=real["negative_fixtures"],
    )

    assert product["status"] == "passed"
    assert product["decision"] == "all_agent_roles_product_ready"
    assert product["product_ready_role_count"] == 5
    assert {row["role"] for row in product["roles"] if row["status"] == "product_ready"} == {"scan", "react", "proact", "customer", "qa"}
    assert all(not row["failed_checks"] for row in product["roles"])
    for row in real["roles"]:
        depth = row["output_eval"]["role_work_depth_checks"]
        assert all(depth.values()), row["role"]


def test_product_readiness_report_blocks_specific_role_gap():
    synthetic = build_deliberate_role_eval_report()
    real = deepcopy(asyncio.run(main._real_agent_role_eval_report()))
    for row in real["roles"]:
        if row["role"] == "customer":
            row["output_eval"]["checks"]["public_actions_only"] = False

    product = build_agent_role_product_readiness_report(
        real,
        synthetic_report=synthetic,
        adversarial_report=real["adversarial_sampled"],
        negative_report=real["negative_fixtures"],
    )
    customer = next(row for row in product["roles"] if row["role"] == "customer")

    assert product["status"] == "failed"
    assert product["decision"] == "block_until_each_agent_role_is_product_ready"
    assert customer["status"] == "not_ready"
    assert "public_actions_only" in customer["failed_checks"]


def test_product_readiness_report_blocks_missing_role_work_contract():
    synthetic = build_deliberate_role_eval_report()
    real = deepcopy(asyncio.run(main._real_agent_role_eval_report()))
    for row in real["roles"]:
        if row["role"] == "react":
            row["output_eval"]["checks"]["role_setup_complete"] = False
            row["output_eval"]["checks"]["role_work_depth_passed"] = False

    product = build_agent_role_product_readiness_report(
        real,
        synthetic_report=synthetic,
        adversarial_report=real["adversarial_sampled"],
        negative_report=real["negative_fixtures"],
    )
    react = next(row for row in product["roles"] if row["role"] == "react")

    assert product["status"] == "failed"
    assert react["status"] == "not_ready"
    assert "role_setup_complete" in react["failed_checks"]
    assert "role_work_depth_passed" in react["failed_checks"]


def test_customer_role_run_uses_customer_contract_not_scan():
    payload = asyncio.run(main._agent_role_run_payload("where should my family go next", "customer"))

    assert payload["selected_role"] == "customer"
    assert payload["role_run"]["dispatch_allowed"] is False
    assert payload["digital_twin_tools"]["deliberate_eval"]["status"] == "passed"
    assert payload["role_receipt"]["read_only"] is True
    assert payload["role_work_contract"]["role"] == "customer"
    assert payload["role_work_contract"]["role_specific_work"]["privacy_boundary"]


def test_customer_role_run_uses_bounded_hot_path(monkeypatch):
    async def fail_customer_provider_path(payload):
        raise AssertionError("agent-role-run customer path should not wait on the provider-backed customer agent")

    monkeypatch.setattr(main, "_customer_support_agent_payload", fail_customer_provider_path)

    payload = asyncio.run(main._agent_role_run_payload("where should my family go next", "customer"))

    assert payload["selected_role"] == "customer"
    assert payload["mode"] == "bounded_customer_role_hot_path"
    assert payload["runtime"]["live"] is False
    assert payload["role_run"]["dispatch_allowed"] is False
    assert payload["run_telemetry"]["governance"]["gate_status"] == "customer_read_only"


def test_agent_role_trace_sample_timeout_degrades(monkeypatch):
    def slow_trace_sample(*args, **kwargs):
        time.sleep(0.1)
        return {"status": "recorded"}

    monkeypatch.setenv("PARKPULSE_AGENT_ROLE_TRACE_SAMPLE_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setattr(main, "record_agent_role_trace_sample", slow_trace_sample)

    receipt = asyncio.run(
        main._record_agent_role_trace_sample_bounded(
            {"selected_role": "scan", "digital_twin_tools": {}},
            message="scan",
            mode="scan",
            source="test",
        )
    )

    assert receipt["status"] == "deferred"
    assert "hot response path" in receipt["readiness_issues"][0]


def test_agent_role_eval_api_surface_returns_report():
    report = asyncio.run(parkpulse_api.park_agent_role_eval())

    assert report["status"] == "passed"
    assert report["role_count"] == 5
    assert report["roles"][0]["trace"]["deliberate_eval"]["mode"] == "deliberate_role_tool_use_eval"


def test_agent_role_real_eval_api_surface_returns_release_gate():
    report = asyncio.run(parkpulse_api.park_agent_role_eval(real=True))

    assert report["status"] == "passed"
    assert report["release_gate"]["status"] == "passed"
    assert report["negative_fixtures"]["decision"] == "negative_fixtures_caught"


def test_parkpulse_api_role_traces_pass_strict_eval_for_all_roles():
    for mode in ("scan", "react", "proact", "customer", "qa"):
        route = route_agent_role("strict api role trace", mode)
        trace = parkpulse_api._agent_role_tool_trace_for_api(route)
        eval_result = trace["deliberate_eval"]

        assert eval_result["status"] == "passed"
        assert eval_result["score"] >= 88
        assert eval_result["required_without_output"] == []
        assert eval_result["critical_failures"] == []


def test_parkpulse_api_role_run_preserves_customer_and_qa_roles():
    customer = asyncio.run(parkpulse_api.park_agent_role_run(parkpulse_api.OperatorCommandRequest(message="where should my family go next", mode="customer")))
    qa = asyncio.run(parkpulse_api.park_agent_role_run(parkpulse_api.OperatorCommandRequest(message="pre-deploy reliability QA", mode="qa")))

    assert customer["selected_role"] == "customer"
    assert customer["role_run"]["dispatch_count"] == 0
    assert customer["digital_twin_tools"]["deliberate_eval"]["status"] == "passed"
    assert qa["selected_role"] == "qa"
    assert qa["role_run"]["dispatch_count"] == 0
    assert qa["digital_twin_tools"]["deliberate_eval"]["status"] == "passed"


def test_parkpulse_api_role_run_persists_replayable_trace_samples(monkeypatch, tmp_path):
    monkeypatch.setenv("PARKPULSE_AGENT_ROLE_TRACE_SAMPLE_LOG_PATH", str(tmp_path / "role_samples.jsonl"))

    react = asyncio.run(parkpulse_api.park_agent_role_run(parkpulse_api.OperatorCommandRequest(message="food court is overloaded", mode="react")))
    customer = asyncio.run(parkpulse_api.park_agent_role_run(parkpulse_api.OperatorCommandRequest(message="where should my family go next", mode="customer")))

    assert react["role_trace_sample"]["status"] == "recorded"
    assert customer["role_trace_sample"]["status"] == "recorded"
    ledger = latest_agent_role_trace_samples(limit=10)
    assert ledger["count"] == 2
    report = build_sampled_agent_role_trace_eval_report(limit=10)
    assert report["status"] == "passed"
    assert report["sample_count"] == 2
    assert {row["role"] for row in report["samples"]} == {"react", "customer"}
    assert all(row["critical_failures"] == [] for row in report["samples"])


def test_role_trace_sample_ledger_redacts_and_trims(monkeypatch, tmp_path):
    sample_path = tmp_path / "trimmed_role_samples.jsonl"
    monkeypatch.setenv("PARKPULSE_AGENT_ROLE_TRACE_SAMPLE_LOG_PATH", str(sample_path))
    monkeypatch.setenv("PARKPULSE_AGENT_ROLE_TRACE_SAMPLE_MAX_ROWS", "2")

    for index in range(3):
        asyncio.run(
            parkpulse_api.park_agent_role_run(
                parkpulse_api.OperatorCommandRequest(message=f"guest{index}@example.com phone 5551234 where next", mode="customer")
            )
        )

    ledger = latest_agent_role_trace_samples(limit=10)

    assert ledger["count"] == 2
    assert all("@example.com" not in row["message"] for row in ledger["samples"])
    assert all("5551234" not in row["message"] for row in ledger["samples"])
    assert all("[redacted]" in row["message"] for row in ledger["samples"])


def test_lazy_main_role_run_persists_replayable_trace_sample(monkeypatch, tmp_path):
    monkeypatch.setenv("PARKPULSE_AGENT_ROLE_TRACE_SAMPLE_LOG_PATH", str(tmp_path / "lazy_role_samples.jsonl"))

    async def call_role_run():
        sent = []
        body = b'{"message":"where should my family go next","mode":"customer"}'
        received = False

        async def receive():
            nonlocal received
            if received:
                return {"type": "http.disconnect"}
            received = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            sent.append(message)

        await main.app({"type": "http", "method": "POST", "path": "/api/park/agent-role-run", "query_string": b"", "headers": []}, receive, send)
        response_body = b"".join(item.get("body", b"") for item in sent if item["type"] == "http.response.body")
        return json.loads(response_body or b"{}")

    payload = asyncio.run(call_role_run())

    assert payload["selected_role"] == "customer"
    assert payload["role_trace_sample"]["status"] == "recorded"
    report = build_sampled_agent_role_trace_eval_report(limit=10)
    assert report["status"] == "passed"
    assert report["sample_count"] == 1
    assert report["samples"][0]["role"] == "customer"


def test_lazy_operator_command_blocks_spoofed_unsigned_mutation(monkeypatch):
    monkeypatch.setenv("PARKPULSE_REQUIRE_SIGNED_ROLE_TOKEN", "true")

    async def call_operator_command():
        sent = []
        body = b'{"message":"dispatch crowd staff","execute":true}'
        received = False

        async def receive():
            nonlocal received
            if received:
                return {"type": "http.disconnect"}
            received = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            sent.append(message)

        await main.app(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/park/operator-command",
                "query_string": b"",
                "headers": [
                    (b"authorization", b"Bear" + b"er unsigned-cloud-run-identity"),
                    (b"x-parkpulse-role", b"ops_team"),
                    (b"content-type", b"application/json"),
                ],
            },
            receive,
            send,
        )
        status = next(item["status"] for item in sent if item["type"] == "http.response.start")
        response_body = b"".join(item.get("body", b"") for item in sent if item["type"] == "http.response.body")
        return status, json.loads(response_body or b"{}")

    status, payload = asyncio.run(call_operator_command())

    assert status == 401
    assert payload["mode"] == "role_authorization_gate"
    assert payload["authorization"]["allowed"] is False
    assert payload["authorization"]["identity"]["auth_method"] == "signed_role_session_required"


def test_adversarial_sampled_role_traces_are_caught_for_exact_reasons():
    report = build_adversarial_sampled_role_trace_eval_report()

    assert report["status"] == "passed"
    assert report["fixture_count"] == 6
    assert report["missed_count"] == 0
    assert report["wrong_reason_count"] == 0
    assert all(row["status"] != "passed" for row in report["fixtures"])
    assert all(row["expected_failures_met"] is True for row in report["fixtures"])


def test_deliberate_negative_fixtures_are_caught():
    report = build_deliberate_role_negative_fixtures()

    assert report["status"] == "passed"
    assert report["missed_count"] == 0
    assert report["wrong_reason_count"] == 0
    assert all(row["eval"]["status"] != "passed" for row in report["fixtures"])
    assert all(row["expected_failures_met"] is True for row in report["fixtures"])


def test_deliberate_tool_eval_catches_boundary_and_policy_failures():
    route = route_agent_role("scan the park", "scan")
    bad_trace = {
        "tool_calls": [
            {"tool": "get_park_state", "status": "ok"},
            {"tool": "dispatch_guest_message", "status": "ok"},
        ]
    }

    eval_result = evaluate_agent_role_trace(route, bad_trace)

    assert eval_result["status"] == "failed"
    assert "dispatch_guest_message" in eval_result["forbidden_present"]
    assert eval_result["boundary_ok"] is False
    assert eval_result["readiness_issues"]


def test_deliberate_tool_eval_rejects_shallow_ordered_tool_names():
    route = route_agent_role("react to food spike", "react")
    shallow_trace = {
        "tool_calls": [
            {"tool": tool, "status": "ok", "output": {"status": "ok"}}
            for tool in route["deliberate_tool_use"]["required_sequence"]
        ],
        "summary": {"selected_role": "react"},
    }

    eval_result = evaluate_agent_role_trace(route, shallow_trace)

    assert eval_result["status"] == "failed"
    assert eval_result["ordered"] is True
    assert eval_result["missing_required"] == []
    assert set(eval_result["required_without_output"]) == set(route["deliberate_tool_use"]["required_sequence"])
    assert "policy_evidence_missing" in eval_result["critical_failures"]


def test_deliberate_tool_eval_rejects_policy_name_without_gate_evidence():
    route = route_agent_role("react to food spike", "react")
    trace = main._role_tool_trace(route, selected_role="react", scenario_key="policy_gap")
    for call in trace["tool_calls"]:
        if call["tool"] == "validate_policy":
            call["output"] = {"status": "ok"}

    eval_result = evaluate_agent_role_trace(route, trace)

    assert eval_result["status"] == "failed"
    assert eval_result["policy_ok"] is True
    assert eval_result["policy_evidence_ok"] is False
    assert "missing_output:validate_policy" in eval_result["critical_failures"]


def test_agent_role_run_invokes_qa_without_dispatch():
    payload = asyncio.run(main._agent_role_run_payload("pre-deploy failure mode matrix", "qa"))

    assert payload["selected_role"] == "qa"
    assert payload["role_run"]["dispatch_allowed"] is False
    assert payload["run_telemetry"]["delivery"]["summary"]["total"] == 0
    assert payload["role_receipt"]["read_only"] is True
    assert payload["digital_twin_tools"]["summary"]["selected_role"] == "qa"
    assert payload["digital_twin_tools"]["deliberate_eval"]["status"] == "passed"
