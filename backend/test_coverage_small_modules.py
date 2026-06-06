import asyncio
import builtins
import json

import park_ops_chat_quality
import park_ops_mcp
import training_run_receipts
import executive_experience_evidence
import weather_live_feed
from executive_experience_intelligence import build_executive_experience_intelligence


def test_training_run_receipt_records_ledger_and_dedupes_readiness(monkeypatch, tmp_path):
    receipt_path = tmp_path / "training_receipts.jsonl"
    monkeypatch.setenv("PARKPULSE_TRAINING_RUN_RECEIPT_LOG_PATH", str(receipt_path))
    monkeypatch.setattr(
        training_run_receipts,
        "latest_controlled_training_eval",
        lambda: {
            "id": "eval-1",
            "status": "failed",
            "decision": "block",
            "summary": {"passed_role_count": 1, "role_count": 2},
            "artifacts": {"paths": {"report": "/tmp/report.json"}},
            "readiness_issues": ["eval missing", "shared issue"],
        },
    )
    monkeypatch.setattr(
        training_run_receipts,
        "latest_controlled_training_pack",
        lambda: {"id": "pack-1", "status": "ready", "artifacts": {"paths": {"pack": "/tmp/pack.json"}}},
    )

    result = training_run_receipts.record_training_run_receipt(
        attempt_type="dry_run",
        request={"runGcpTraining": True, "exportLiveEpisodes": True, "minRows": 25},
        actual_training={
            "status": "blocked",
            "sample_count": 8,
            "min_sample_count": 25,
            "uses_generated_data": False,
            "source": "controlled",
            "debug": {"readiness_issues": ["training blocked", "shared issue"]},
            "gcp_ml": {
                "bigquery": {"ready": False, "dataset": "parkpulse"},
                "bigquery_ml_training": {
                    "status": "bqml_blocked",
                    "model_id": "model-1",
                    "job_id": "job-1",
                    "readiness_issues": ["bqml blocked"],
                },
            },
            "model_ops": {
                "promotion_gate": {"status": "blocked", "decision": "hold", "blockers": ["low rows"], "warnings": ["watch"]},
                "slice_rollback_ledger": {"status": "ready", "row_count": 3},
            },
        },
        live_feed_preflight={
            "status": "blocked",
            "mode": "preflight",
            "refresh_status": "skipped",
            "requested_sources": ["weather"],
            "refreshed_sources": [],
            "result_count": 0,
            "before": {"ready": 1},
            "after": {"ready": 0},
            "remaining_issues": ["weather"],
            "readiness_issues": ["preflight blocked", "shared issue"],
        },
    )

    receipt = result["receipt"]
    assert result["status"] == "recorded"
    assert receipt["status"] == "blocked"
    assert receipt["request"]["run_gcp_training"] is True
    assert receipt["controlled_pack"]["id"] == "pack-1"
    assert receipt["controlled_eval_gate"]["passed_role_count"] == 1
    assert receipt["gcp_ml"]["bqml_status"] == "bqml_blocked"
    assert receipt["promotion"]["rollback_rows"] == 3
    assert receipt["live_feed_preflight"]["requested_sources"] == ["weather"]
    assert receipt["readiness_issues"] == ["eval missing", "shared issue", "training blocked", "bqml blocked", "preflight blocked"]

    ledger = training_run_receipts.training_run_receipt_ledger(limit=10)
    assert ledger["status"] == "ready"
    assert ledger["summary"]["blocked_count"] == 1
    assert ledger["receipts"][0]["id"] == receipt["id"]


def test_training_run_receipt_defaults_and_bad_json_ledger(monkeypatch, tmp_path):
    receipt_path = tmp_path / "training_receipts.jsonl"
    monkeypatch.setenv("PARKPULSE_TRAINING_RUN_RECEIPT_LOG_PATH", str(receipt_path))
    monkeypatch.setattr(training_run_receipts, "latest_controlled_training_eval", lambda: {"id": "eval-ok", "status": "passed", "decision": "allow"})
    monkeypatch.setattr(training_run_receipts, "latest_controlled_training_pack", lambda: {"id": "pack-ok", "status": "ready"})

    assert training_run_receipts.training_run_receipt_ledger()["status"] == "empty"
    started = training_run_receipts.record_training_run_receipt(
        attempt_type="bqml",
        request=None,
        actual_training={"status": "ready", "gcp_ml": {"bigquery_ml_training": {"status": "started"}}},
        controlled_eval={"id": "eval-override", "status": "passed", "decision": "allow"},
        readiness_issues=[],
    )
    assert started["receipt"]["status"] == "started"
    assert started["receipt"]["request"]["export_live_episodes"] is False

    receipt_path.write_text("{bad json\n" + json.dumps({"id": "manual", "status": "recently_started"}) + "\n", encoding="utf-8")
    ledger = training_run_receipts.training_run_receipt_ledger(limit=2)
    assert ledger["summary"]["started_count"] == 1
    assert ledger["receipts"][0]["id"] == "manual"

    recorded = training_run_receipts.record_training_run_receipt(attempt_type="minimal", actual_training={}, controlled_eval={"status": "passed"})
    assert recorded["receipt"]["status"] == "recorded"

    monkeypatch.setattr(training_run_receipts.os.path, "exists", lambda path: True)
    monkeypatch.setattr(builtins, "open", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("cannot read")))
    assert training_run_receipts._read_jsonl(str(receipt_path), 10) == []


def test_park_ops_mcp_manifest_selection_context_and_prompt_packet():
    manifest = park_ops_mcp.tool_manifest()
    assert manifest["status"] == "ready"
    assert manifest["tool_count"] == len(park_ops_mcp.TOOL_SPECS)
    assert park_ops_mcp.blocked_authority("Please dispatch workers and set reward") == "live_action"
    assert park_ops_mcp.blocked_authority("Can you set reward now?") == "reward"

    selected = park_ops_mcp.select_tools("current status score evidence")
    assert "get_live_park_state" in selected
    assert "get_park_understanding_score" in selected
    assert "get_outcome_ledger" in park_ops_mcp.select_tools("missing memory mongo retrieve case why")
    assert "get_bigquery_training_status" in park_ops_mcp.select_tools("training bigquery bqml")
    assert "get_role_access_contracts" in park_ops_mcp.select_tools("role access customer worker admin")
    assert "get_counterfactual_failures" in park_ops_mcp.select_tools("counterfactual failed uncertainty trap")
    assert park_ops_mcp.select_tools("hi") == ["get_live_park_state", "get_latest_heartbeat_action", "get_llm_boundary_contract"]
    assert park_ops_mcp.select_tools("dispatch now") == ["get_llm_boundary_contract", "get_latest_heartbeat_action", "get_policy_gate_status"]

    tool_results = [
        {"tool": "get_live_park_state", "status": "ready", "elapsed_ms": 1, "data": {"scenario": "ride_down"}},
        {"tool": "get_latest_heartbeat_action", "status": "ready", "elapsed_ms": 1, "data": {"policy_gate": {"status": "allowed"}}},
        {"tool": "get_memory_retrieval", "status": "ready", "elapsed_ms": 1, "data": {"count": 2}},
    ]
    context = park_ops_mcp.compact_context(tool_results)
    assert context["live_state"]["scenario"] == "ride_down"
    assert context["policy_gate"]["status"] == "allowed"
    assert park_ops_mcp.result_data(tool_results, "missing") == {}
    packet = park_ops_mcp.prompt_packet("what is happening?", [{"role": "user", "content": "older"}], tool_results)
    assert packet["mcp"]["compact_context"]["memory_retrieval"]["count"] == 2
    assert "cannot_do" in packet["required_json"]


def test_park_ops_mcp_call_tool_statuses(monkeypatch):
    async def async_handler(args):
        return {"status": "ok", "args": args}

    assert asyncio.run(park_ops_mcp.call_tool("missing", {}, {}))["status"] == "error"
    unavailable = asyncio.run(park_ops_mcp.call_tool("get_live_park_state", {}, {}))
    assert unavailable["status"] == "unavailable"
    ready = asyncio.run(park_ops_mcp.call_tool("get_live_park_state", {"get_live_park_state": lambda args: {"park": "ok"}}, {}))
    assert ready["data"]["park"] == "ok"
    async_ready = asyncio.run(park_ops_mcp.call_tool("get_memory_retrieval", {"get_memory_retrieval": async_handler}, {"limit": 2}))
    assert async_ready["data"]["args"]["limit"] == 2
    error = asyncio.run(park_ops_mcp.call_tool("get_action_log", {"get_action_log": lambda args: (_ for _ in ()).throw(RuntimeError("down"))}, {}))
    assert error["status"] == "error"
    assert "down" in error["readiness_issues"][0]

    async def fake_wait_for(awaitable, timeout):
        awaitable.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr(park_ops_mcp.asyncio, "wait_for", fake_wait_for)
    timeout = asyncio.run(park_ops_mcp.call_tool("get_memory_retrieval", {"get_memory_retrieval": async_handler}, {}))
    assert timeout["status"] == "timeout"


def test_park_ops_chat_quality_scores_pass_fail_and_report():
    safe_payload = {
        "status": "ready",
        "answer": {
            "headline": "Park status",
            "answer": "The park is under pressure but the answer is grounded in current evidence and notes uncertainty clearly.",
            "evidence": ["state", "policy"],
            "uncertainty": ["weather stale"],
            "cannot_do": [
                "dispatch",
                "set_reward",
                "write_label",
                "promote_model",
                "rollback_policy",
                "load_bigquery_per_tick",
            ],
        },
        "mcp": {"selected_tools": ["get_live_park_state", "get_latest_heartbeat_action", "get_llm_boundary_contract", "get_policy_gate_status", "get_action_log"]},
        "uses_seed_data": False,
        "loads_bigquery_per_tick": False,
        "llm_used_for_reward_or_label": False,
        "labels_or_reward_changed": False,
    }
    safe = park_ops_chat_quality.score_chat_payload("what is current status?", safe_payload, latency_ms=20)
    assert safe["score"] >= 90
    assert safe["checks"]["boundary_safe"] is True

    blocked_payload = {
        **safe_payload,
        "answer": {**safe_payload["answer"], "headline": "I cannot take that authority."},
        "mcp": {"selected_tools": ["get_llm_boundary_contract", "get_latest_heartbeat_action", "get_policy_gate_status"]},
        "readiness_issues": ["Gemini is offline"],
    }
    blocked = park_ops_chat_quality.score_chat_payload("dispatch and promote model", blocked_payload, latency_ms=9001, max_latency_ms=100)
    assert blocked["checks"]["blocked_refused"] is True
    assert blocked["checks"]["gemini_offline_declared"] is False

    complex_expected = park_ops_chat_quality.score_chat_payload(
        "status score failed training bigquery",
        safe_payload,
        latency_ms=10,
    )
    assert "get_counterfactual_failures" in complex_expected["expected_tools"]
    assert "get_bigquery_training_status" in complex_expected["expected_tools"]

    report = park_ops_chat_quality.build_quality_report([safe, blocked], min_average_score=95, min_prompt_score=95)
    assert report["status"] == "review"
    assert report["prompt_count"] == 2
    assert report["failures"]
    assert report["boundary"].startswith("Quality report is read-only")


def test_executive_experience_intelligence_high_risk_briefing():
    state = {
        "guestFlow": {
            "avgSatisfaction": 42,
            "rides": [{"id": "dragon", "name": "Dragon Coaster", "waitMins": 70, "downtimeRisk": 88}],
            "zones": [{"id": "plaza", "name": "Coaster Plaza", "density": 91, "waitMins": 35}],
        },
        "guestCare": {"complaintRatePct": 31, "openCases": 14, "sentimentMomentum": "worsening"},
        "parkOps": {"guestRecoveryPressure": 86},
        "operatingClock": {
            "guestFeedbackLoop": {"careCaseAccumulationPct": 79, "sentimentMomentum": "fragile"},
            "accessFairness": {"publicComplaintRiskPct": 76, "perceivedFairnessScore": 41},
            "eventSchedule": {"eventTrafficRiskPct": 67, "nextEvent": {"name": "Parade"}},
            "foodRetailLifecycle": {"mobileOrderBacklogPressurePct": 84},
        },
        "foodInventory": {"locations": [{"id": "foodCourt1", "pickupEtaMinutes": 29, "mobileOrderBacklog": 120}]},
    }
    report = build_executive_experience_intelligence(
        state=state,
        backlog={"issues": [{"title": "Care script mismatch", "executiveDomain": "customer_experience"}]},
        incidents={"tickets": [{"id": "case-1"}]},
        ledger={"items": [{"selectedAction": "Reroute guests", "evalScore": 82}]},
        evidence={"mode": "demo", "sources": [{"id": "feedback"}]},
    )

    assert report["status"] == "ready"
    assert report["scores"]["status"] == "critical"
    assert "recovery story" in report["executiveBriefing"]["headline"]
    assert report["beforeAfterEventSentiment"]["event"] == "Parade"
    assert report["sourceCoverage"]["backlogIssues"] == 1
    assert report["sourceCoverage"]["recentActions"] == ["Reroute guests (82)"]
    assert report["agentLayer"]["blockedActions"]
    assert report["refundReasonAnalysis"][0]["sharePct"] >= report["refundReasonAnalysis"][-1]["sharePct"]


def test_executive_experience_intelligence_empty_state_fallbacks():
    report = build_executive_experience_intelligence(state={}, backlog=None, incidents=None, ledger={"items": [{"selectedAction": ""}]}, evidence=None)

    assert report["status"] == "ready"
    assert report["scores"]["status"] in {"stable", "watch"}
    assert report["beforeAfterEventSentiment"]["event"] == "next timed event"
    assert "Top zone" in report["beforeAfterEventSentiment"]["before"]["leadingSignal"]
    assert report["sourceCoverage"]["backlogIssues"] == 0
    assert report["sourceCoverage"]["recentActions"] == []
    assert report["monthlyGuestFeedback"]["sentimentMomentum"] == "watch"


def test_executive_experience_evidence_validation_readiness_and_summary():
    first = executive_experience_evidence.DATA_PRODUCTS[0]
    valid_doc = {field: f"value-{field}" for field in first["requiredFields"]}
    valid_doc.update({"sourceType": "curated"})
    invalid_doc = {
        "month": "2026-06",
        "sourceType": "private",
        "email": "guest@example.com",
        "theme": "payment card: 4111111111111111",
    }

    valid = executive_experience_evidence.validate_executive_experience_documents(first["collection"], [valid_doc])
    assert valid["status"] == "pass"
    invalid = executive_experience_evidence.validate_executive_experience_documents(first["collection"], [invalid_doc, "bad"])
    assert invalid["status"] == "blocked"
    assert {error["reason"] for error in invalid["errors"]} >= {
        "Missing required field.",
        "sourceType must be demo, curated, live, or imported.",
        "Sensitive field name is not allowed in executive evidence.",
        "Document is not an object.",
    }
    unknown = executive_experience_evidence.validate_executive_experience_documents("not_approved", [{}])
    assert unknown["valid"] is False

    artifact = executive_experience_evidence.validate_executive_experience_documents(
        "executive_brief_artifacts",
        [
            {
                "artifactId": "a1",
                "artifactType": "brief",
                "status": "ready",
                "reviewerStatus": "approved",
                "generatedAt": "now",
                "requestedByRole": "ml_ops_admin",
                "sourceCoverage": {"rows": 1},
                "privacyBoundary": "aggregate",
                "policyBoundary": "read_only",
            }
        ],
    )
    assert artifact["status"] == "pass"
    assert executive_experience_evidence.evidence_hash({"b": 2, "a": 1}) == executive_experience_evidence.evidence_hash({"a": 1, "b": 2})

    def fetch_documents(collection, limit):
        spec = executive_experience_evidence.DATA_PRODUCT_BY_COLLECTION[collection]
        if spec["id"] == "guest_feedback_events":
            raise RuntimeError("offline")
        if spec["id"] == "refund_reason_rollup":
            return [{"month": "2026-06", "sourceType": "demo"}]
        row = {field: f"{field}-value" for field in spec["requiredFields"]}
        row["sourceType"] = "demo"
        return [row, dict(row), dict(row)]

    evidence = executive_experience_evidence.build_executive_experience_evidence(fetch_documents, limit_per_product=999)
    assert evidence["status"] == "partial"
    assert evidence["summary"]["readyDataProducts"] >= 5
    assert "guest_feedback_events" in evidence["missingDataProducts"]
    assert "refund_reason_rollup" in evidence["partialDataProducts"]
    assert evidence["readinessIssues"]
    summary = executive_experience_evidence.executive_evidence_source_summary(evidence)
    assert summary["findingBasis"] == "longitudinal_evidence"
    assert executive_experience_evidence.executive_evidence_source_summary({"summary": {"partialDataProducts": 1}})["findingBasis"] == "mixed_proxy_and_partial_evidence"
    assert executive_experience_evidence.executive_evidence_source_summary(None)["findingBasis"] == "live_operational_proxies_only"


def test_weather_live_feed_events_fetch_and_ingest(monkeypatch):
    monkeypatch.setenv("PARKPULSE_WEATHER_LATITUDE", "bad")
    monkeypatch.setenv("PARKPULSE_WEATHER_FEED_TIMEOUT_SECONDS", "bad")
    config = weather_live_feed.weather_feed_config()
    assert config["latitude"] == 28.3852
    assert config["timeout_seconds"] == 8

    fetch_result = {
        "status": "fetched",
        "mode": "open_meteo_weather_fetch",
        "fetched_at": "2026-06-05T12:00:00Z",
        "provider": "open_meteo",
        "url": "https://weather.test",
        "config": {"location_label": "Test Park"},
        "payload": {
            "current": {
                "time": "2026-06-05T12:00",
                "temperature_2m": 97,
                "relative_humidity_2m": 70,
                "apparent_temperature": 106,
                "precipitation": 0.1,
                "rain": 0.1,
                "weather_code": 95,
                "cloud_cover": 80,
                "wind_speed_10m": 20,
                "wind_gusts_10m": 42,
                "is_day": 1,
            },
            "current_units": {"temperature_2m": "F"},
        },
    }
    events = weather_live_feed.build_weather_live_feed_events(fetch_result)
    assert len(events) == 3
    assert events[0]["value"]["weather_label"] == "thunderstorm"
    assert events[0]["value"]["outdoor_ride_review_required"] is True
    assert events[1]["value"]["lightning_window"] is True
    assert weather_live_feed.build_weather_live_feed_events({"payload": {}})[0]["confidence"] == 0.35

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"current": {"weather_code": 0}}).encode("utf-8")

    monkeypatch.setattr(weather_live_feed, "_ssl_context", lambda: None)
    monkeypatch.setattr(weather_live_feed, "urlopen", lambda request, timeout, context: FakeResponse())
    fetched = weather_live_feed.fetch_open_meteo_weather({"latitude": 1, "longitude": 2, "variables": ["weather_code"], "timeout_seconds": 1, "location_label": "x"})
    assert fetched["status"] == "fetched"
    assert "latitude=1" in fetched["url"]

    monkeypatch.setattr(weather_live_feed, "fetch_open_meteo_weather", lambda: fetch_result)
    monkeypatch.setattr(
        weather_live_feed,
        "ingest_live_feed_event",
        lambda event: {"event": event, "review_case": {"id": event["source_event_id"]} if event["signal_type"] == "storm_risk" else None},
    )
    ingested = weather_live_feed.ingest_live_weather_feed()
    assert ingested["status"] == "loaded"
    assert ingested["event_count"] == 3
    assert ingested["review_case_count"] == 1


def test_weather_live_feed_risk_labels_and_safe_parsing():
    assert weather_live_feed._weather_code_label(None) == "unknown"
    assert weather_live_feed._weather_code_label(0) == "clear"
    assert weather_live_feed._weather_code_label(2) == "cloud_cover"
    assert weather_live_feed._weather_code_label(45) == "fog"
    assert weather_live_feed._weather_code_label(53) == "drizzle"
    assert weather_live_feed._weather_code_label(73) == "snow"
    assert weather_live_feed._weather_code_label(1234) == "wmo_1234"
    assert weather_live_feed._safe_float("bad", 7.5) == 7.5
    assert weather_live_feed._safe_float(None, 2.5) == 2.5
    assert weather_live_feed._safe_int("bad") is None
    assert weather_live_feed._safe_int("") is None

    showers = weather_live_feed._risk_from_weather({"weather_code": 81, "apparent_temperature": 96, "wind_gusts_10m": 10})
    assert showers["storm_risk_pct"] == 68
    assert showers["heat_risk"] == "high"
    rain = weather_live_feed._risk_from_weather({"weather_code": 63, "apparent_temperature": 89, "wind_gusts_10m": 10})
    assert rain["storm_risk_pct"] == 54
    assert rain["heat_risk"] == "watch"
    wet = weather_live_feed._risk_from_weather({"weather_code": 3, "precipitation": 0.06, "apparent_temperature": 70})
    assert wet["storm_risk_pct"] == 50
    windy = weather_live_feed._risk_from_weather({"weather_code": 3, "rain": 0, "wind_gusts_10m": 36, "apparent_temperature": 70})
    assert windy["storm_risk_pct"] == 45
    normal = weather_live_feed._risk_from_weather({"weather_code": 3, "apparent_temperature": 70})
    assert normal["heat_risk"] == "normal"
