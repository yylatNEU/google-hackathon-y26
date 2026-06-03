import asyncio
import os
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

os.environ.setdefault("MONGODB_DISABLE_DRIVER_IMPORT", "1")

import digital_twin_tools
import bigquery_analytics
import gcp_training_seed
import governance
import memory_ops_agent
import mongo_memory
import park_audit_agent
import park_autodream_benchmark
import park_autodream_agent
import park_simulation
import park_twin_engine
import park_governance_runtime
import policy_loader
from policy_engine import get_policy_engine
import reliability
import run_autodream
import simulation
from park_simulation import ParkSimulation


def run(coro):
    return asyncio.run(coro)


def sample_state():
    state = run(ParkSimulation().get_state())
    state["guestFlow"]["zones"].append({"id": "packed", "name": "Packed Zone", "density": 105})
    state["weather"]["stormRisk"] = 80
    state["guestCare"] = {"openCases": 4}
    state["maintenance"] = {"blockedAutomation": ["reopen"]}
    return state


def test_reliability_helpers_and_async_retries(monkeypatch):
    monkeypatch.setenv("PARKPULSE_RETRY_ATTEMPTS", "bad")
    monkeypatch.setenv("PARKPULSE_RETRY_BASE_DELAY_SECONDS", "bad")
    monkeypatch.setenv("PARKPULSE_DISABLE_RELIABILITY", "yes")
    assert reliability._env_int("PARKPULSE_RETRY_ATTEMPTS", 3) == 3
    assert reliability._env_float("PARKPULSE_RETRY_BASE_DELAY_SECONDS", 0.5) == 0.5
    assert reliability._truthy("on") is True
    assert reliability.reliability_status()["enabled"] is False

    breaker = reliability.CircuitBreaker("half", failure_threshold=1, recovery_seconds=0)
    breaker.record_failure(RuntimeError("down"))
    assert breaker.state == "half_open"
    breaker.record_success()
    assert breaker.snapshot()["state"] == "closed"

    class ResponseError(RuntimeError):
        response = SimpleNamespace(status_code=503)

    class BadRequest(RuntimeError):
        response = SimpleNamespace(status_code=400)

    assert reliability._default_retryable(ResponseError("retry")) is True
    assert reliability._default_retryable(BadRequest("no")) is False
    assert reliability._sleep_seconds(2, 0, 0) == 0

    calls = {"count": 0}

    async def flaky_async():
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary")
        return "ok"

    assert run(reliability.async_call_with_retries("async.tail", flaky_async, attempts=2, base_delay=0, max_delay=0)) == "ok"
    reliability.registry.breakers["async.open"] = reliability.CircuitBreaker("async.open", opened_at=time.monotonic())
    with pytest.raises(reliability.CircuitOpenError):
        run(reliability.async_call_with_retries("async.open", lambda: asyncio.sleep(0, result="no"), attempts=1))
    with pytest.raises(RuntimeError):
        run(reliability.async_call_with_retries("async.fail", lambda: asyncio.sleep(0, result=(_ for _ in ()).throw(RuntimeError("boom"))), attempts=1))


def test_governance_runtime_policy_gates_cover_hard_violations():
    state = sample_state()
    actions = [
        ("ride", "reopen", "Reopen the down ride", {"key": "ride_down"}),
        ("staff", "delay_breaks", "Delay breaks", {"key": "staff_shortage"}),
        ("energy", "reduce_hvac", "Reduce HVAC", {"key": "storm_response"}),
        ("traffic", "route_all", "Route all guests", {"key": "ride_down"}),
        ("guest", "pii_message", "Named guest message", {"key": "ride_down"}),
        ("food", "suppress_item", "Food recovery message", {"key": "food_spike"}),
    ]
    policy_engine = get_policy_engine()
    active_scenario = state["guestFlow"]["activeScenario"]
    for target, operation, title, scenario in actions:
        doc = park_governance_runtime.build_runtime_action(target, operation, title=title, scenario=scenario)
        result = policy_engine.evaluate_action(doc, state, {"evals": [{"label": "Safety", "score": 95}]}, scenario)
        if target != "food":
            assert result["status"] == "blocked"

    blocked_doc = park_governance_runtime.build_runtime_action("ride", "reopen", title="Reopen ride", scenario=active_scenario)
    remediation = park_governance_runtime._create_remediation_task("blocked", blocked_doc, ["blocked"], state)
    review_remediation = park_governance_runtime._create_remediation_task("review", blocked_doc, ["review"], state)
    assert remediation["severity"] == "critical"
    assert review_remediation["severity"] == "review"
    assert park_governance_runtime._create_customer_care_case("clear", {"park_action": {"target": "staff"}, "title": "Internal"}, state, []) is None
    care = park_governance_runtime._create_customer_care_case("review", blocked_doc, state, ["review"])
    ledger = park_governance_runtime._record_ledger({"id": "ledger-tail", "gateStatus": "blocked"})
    assert care and ledger["id"] == "ledger-tail"
    created = park_governance_runtime.create_customer_care_case({"severity": "high", "reason": "care"}, state)
    assert created["status"] == "queued"
    assert park_governance_runtime.list_runtime_governance(3)["summary"]["ledger_count"] >= 1


def test_memory_ops_edge_states(monkeypatch):
    original_documents_for_embedding_check = memory_ops_agent._documents_for_embedding_check
    assert memory_ops_agent._parse_time(None) is None
    assert memory_ops_agent._parse_time("not-a-date") is None
    assert memory_ops_agent._parse_time("2026-05-24T10:00:00").tzinfo is not None
    assert memory_ops_agent._collection_count([{"name": "x", "count": "bad"}], "x") == 0

    stale_dashboard = {
        "status": {"connected": True, "vectorSearch": {"index": "idx"}},
        "collections": [{"name": "playbooks", "count": 20}, {"name": "incidents", "count": 20}, {"name": "agent_learnings", "count": 20}],
        "retrieved": {"method": "mongodb_vector_search"},
        "current_state": {"updatedAt": (datetime.now(UTC) - timedelta(seconds=1000)).isoformat()},
        "latest_decisions": [{"retrievedPlaybooks": ["pb"], "retrievedIncidents": ["inc"]}],
    }
    monkeypatch.setattr(memory_ops_agent, "get_operational_memory_dashboard", lambda query: stale_dashboard)
    monkeypatch.setattr(memory_ops_agent, "_documents_for_embedding_check", lambda name: [{"_id": f"{name}-1", "embedding": [0.1], "embeddingText": "ok"}])
    report = memory_ops_agent.build_memory_ops_report("ride")
    assert report["overall_status"] == "action_required"

    monkeypatch.setattr(memory_ops_agent, "_documents_for_embedding_check", lambda name: [{"_id": "missing"}])
    poor = memory_ops_agent._embedding_coverage([{"name": "playbooks", "count": 1}], "playbooks")
    assert poor["status"] == "action_required"

    class BadCollection:
        def find(self, *args, **kwargs):
            raise RuntimeError("find failed")

    class BadMemory:
        errors = []

        def _collection(self, name):
            return BadCollection()

    monkeypatch.setattr(mongo_memory, "_memory", BadMemory())
    assert original_documents_for_embedding_check("playbooks") == []


def test_audit_agent_helpers_and_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_AUDIT_DB", str(tmp_path / "audit.db"))
    assert park_audit_agent._db_path() == tmp_path / "audit.db"
    assert park_audit_agent._safe_int("bad", 7) == 7
    assert park_audit_agent._severity_for_score(95) == "critical"
    assert park_audit_agent._severity_for_score(75) == "warning"
    assert park_audit_agent._severity_for_score(20) == "watch"
    assert park_audit_agent._json_row("{bad") == {}
    assert park_audit_agent._event_finding({"abnormalityScore": 30}) is None

    signals = ["ride_dispatch_log", "schedule_collision", "food_backlog", "crowd_flow_delta", "other"]
    for signal in signals:
        finding = park_audit_agent._event_finding({"id": signal, "signal": signal, "abnormalityScore": 90, "message": "m"})
        assert finding and finding["recommendedAction"]
        candidate = park_audit_agent._candidate_for_domain(finding["domain"], finding)
        assert candidate["park_action"]["target"]

    event = park_audit_agent.record_audit_event({"id": "evt-1", "signal": "ride_dispatch_log", "abnormalityScore": 95})
    assert event["severity"] == "critical"
    snapshot = park_audit_agent.build_audit_snapshot({"operationsAudit": {"summary": {}, "anomalies": []}})
    assert snapshot["summary"]["ingestedEvents"] >= 1
    candidate = park_audit_agent.build_audit_action_candidate(snapshot, sample_state())
    assert candidate["status"] == "ready"
    assert park_audit_agent.build_audit_action_candidate({"anomalies": []}, sample_state())["status"] == "noop"
    park_audit_agent.record_audit_response(candidate["finding"]["id"], {"status": "done"})
    assert park_audit_agent.audit_store_status()["ready"] is True

    monkeypatch.setattr(park_audit_agent, "init_audit_store", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    assert park_audit_agent.audit_store_status()["ready"] is False


def test_digital_twin_tool_tail_branches():
    state = sample_state()
    context = {"status": {"mode": "demo"}, "retrieved": {"playbooks": [{"_id": "pb"}], "incidents": [{"_id": "inc"}], "learnings": [{"_id": "learn"}]}}
    assert digital_twin_tools._as_int("bad", 4) == 4
    assert digital_twin_tools._as_float("bad", 1.5) == 1.5
    assert digital_twin_tools._primary_ride({"guestFlow": {"rides": []}})["id"] == "dragonCoaster"
    calls = [
        ("get_zone_density", {"zone_id": "packed"}),
        ("get_ride_status", {"ride_id": "missing"}),
        ("get_staff_constraints", {"zone_id": "packed"}),
        ("get_food_capacity", {"location_id": "missing"}),
        ("simulate_action", {"target": "ride", "action": "reopen"}),
        ("compare_action_candidates", {"candidates": [{"id": "a", "target": "ride", "action": "reopen"}, {"id": "b", "target": "food", "action": "suppress_item"}]}),
        ("validate_policy", {"action": {"target": "ride", "action": "reopen"}}),
        ("retrieve_similar_incidents", {}),
        ("score_decision_quality", {"decision": {"selected_action": {"target": "staff", "action": "redeploy"}}}),
        ("dispatch_guest_message", {"payload": {"message": "go"}, "requires_operator_approval": True}),
        ("dispatch_worker_task", {"payload": {"task": "go"}}),
        ("dispatch_equipment_command", {"payload": {"command": "hold"}}),
        ("write_decision_memory", {"decision_id": "d", "evidence": ["x"], "outcome_id": "o"}),
        ("unknown", {}),
    ]
    for name, args in calls:
        assert digital_twin_tools.run_digital_twin_tool(name, state, args, context)["tool"] == name
    assert digital_twin_tools.build_digital_twin_tool_trace(state, "ride_down", context, None, None)["tool_calls"]


def test_gcp_bigquery_autodream_and_wrapper_tail_branches(monkeypatch, capsys):
    fake_bq = SimpleNamespace(
        QueryJobConfig=lambda query_parameters=None: SimpleNamespace(query_parameters=query_parameters or []),
        ScalarQueryParameter=lambda name, field_type, value: (name, field_type, value),
    )

    class FakeClient:
        def __init__(self, project=None):
            self.project = project

        def query(self, query, job_config=None):
            return SimpleNamespace(result=lambda: [{"exists": 1}])

    fake_bq.Client = FakeClient
    monkeypatch.setitem(__import__("sys").modules, "google", SimpleNamespace(cloud=SimpleNamespace(bigquery=fake_bq)))
    monkeypatch.setitem(__import__("sys").modules, "google.cloud", SimpleNamespace(bigquery=fake_bq))
    monkeypatch.setitem(__import__("sys").modules, "google.cloud.bigquery", fake_bq)
    monkeypatch.setenv("BIGQUERY_PROJECT", "project")
    monkeypatch.setenv("BIGQUERY_DATASET", "dataset")
    assert gcp_training_seed._bigquery_outcome_exists("outcome-1") is True
    monkeypatch.delenv("BIGQUERY_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    assert gcp_training_seed._bigquery_outcome_exists("outcome-1") is False

    monkeypatch.setattr(bigquery_analytics, "_load_bigquery_module", lambda: None)
    monkeypatch.setattr(bigquery_analytics, "_bigquery_import_error", "missing")
    assert bigquery_analytics._client_status()[1] == ["missing"]
    monkeypatch.setattr(bigquery_analytics, "_load_bigquery_module", lambda: fake_bq)
    monkeypatch.delenv("BIGQUERY_PROJECT", raising=False)
    assert "BIGQUERY_PROJECT" in bigquery_analytics._client_status()[1][0]
    monkeypatch.setenv("BIGQUERY_PROJECT", "project")
    monkeypatch.setenv("BIGQUERY_DATASET", "")
    assert "BIGQUERY_DATASET" in bigquery_analytics._client_status()[1][0]
    monkeypatch.setenv("BIGQUERY_DATASET", "dataset")
    assert bigquery_analytics._client_status()[0].project == "project"

    priors = {"best_prior": {"cohort": "best"}, "weakest_prior": {"cohort": "weak"}}
    weak = park_autodream_agent._counterfactual_for_signal("ride_down", {"take_rate": "bad", "follow_through": 0.2, "overall_score": "bad"}, priors)
    success = park_autodream_agent._counterfactual_for_signal("ride_down", {"take_rate": 0.8, "follow_through": 0.7, "overall_score": 90, "density_delta": -4}, priors)
    limited = park_autodream_agent._counterfactual_for_signal("ride_down", {"take_rate": 0.8, "follow_through": 0.7, "overall_score": 60}, priors)
    assert weak["outcomeLabel"] == "counterfactual_low_response"
    assert success["outcomeLabel"] == "counterfactual_success_pattern"
    assert limited["outcomeLabel"] == "counterfactual_limited_movement"

    assert governance.governance_status()["status"] == "ready"
    assert simulation.parkpulse_simulation is not None
    assert run_autodream._selected_scenarios(SimpleNamespace(all_scenarios=False, scenario=None)) == ["proactive_eventops"]

    monkeypatch.setattr(gcp_training_seed, "online_improvement_status", lambda: {"ready": True})
    monkeypatch.setattr(gcp_training_seed, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(gcp_training_seed, "run_synthetic_training", lambda cases, allow_duplicates=False: asyncio.sleep(0, result=[{"case_id": "synthetic"}]))
    monkeypatch.setattr(__import__("sys"), "argv", ["gcp_training_seed.py", "--synthetic", "--max-cases", "1"])
    gcp_training_seed.main()
    assert '"runs": 1' in capsys.readouterr().out


def test_autodream_benchmark_and_mongo_measurement_paths(monkeypatch, capsys):
    state = sample_state()
    rule = {
        "_id": "rule-1",
        "sourceDreamLearningId": "dream-1",
        "scenarioKey": "ride_down",
        "incidentType": "ride_down",
        "outcomeLabel": "counterfactual_low_response",
        "confidence": 80,
        "promotionImpact": {"status": "pending_measurement"},
    }
    monkeypatch.setattr(park_autodream_benchmark, "get_latest_memory_documents", lambda collection, limit: [rule] if collection == "agent_learnings" else [])
    assert park_autodream_benchmark._number("bad", 2.0) == 2.0
    assert park_autodream_benchmark._active_scenario({}) == "ride_down"
    assert park_autodream_benchmark._primary_ride({"guestFlow": {"rides": []}})["id"] == "dragonCoaster"
    assert park_autodream_benchmark._find_ride(state, "missing") == {}
    assert park_autodream_benchmark._promoted_rule("ride_down", "missing") is None
    assert park_autodream_benchmark.run_autodream_benchmark(state, scenario_key="food_spike")["status"] == "no_promoted_rule"

    def fake_optimize(current_state, scenario_key, context=None):
        learned = bool((context or {}).get("retrieved", {}).get("learnings"))
        return {
            "selected_plan": {
                "id": "learned" if learned else "baseline",
                "name": "Learned" if learned else "Baseline",
                "scorecard": {"overall": 88 if learned else 80, "take_rate_likelihood": 58 if learned else 42},
                "action_mix": {"guest_reroute": {"target_mix": [{"destinationId": "theaterB", "share": 0.5}]}},
                "selected_action": {"label": "Split route"},
            }
        }

    def fake_simulate(current_state, selected, horizon_minutes=30, seed=""):
        learned = selected.get("id") == "learned"
        projected = sample_state()
        projected["guestFlow"]["rides"][0]["queueGuests"] = 360 if learned else 520
        projected["guestFlow"]["rides"][0]["waitMins"] = 28 if learned else 45
        return {
            "projected_state": projected,
            "projected_impact": {"movedGuests": 340 if learned else 180},
            "scorecard": {"overall": 90 if learned else 80},
            "source": "unit",
        }

    monkeypatch.setattr(park_autodream_benchmark, "optimize_park_response", fake_optimize)
    monkeypatch.setattr(park_autodream_benchmark, "simulate_action_plan", fake_simulate)
    benchmark = park_autodream_benchmark.run_autodream_benchmark(state, scenario_key="ride_down", seeds=5)
    assert benchmark["status"] == "complete"
    assert benchmark["confidence"] == "validated"
    assert benchmark["summary"]["learned_wins"] == 5
    assert park_autodream_benchmark._confidence(0, 0, 0) == "no_signal"
    assert park_autodream_benchmark._confidence(2, 0.8, 0.1) == "early_signal"
    assert park_autodream_benchmark._confidence(4, 0.8, 0.1) == "directional"
    assert park_autodream_benchmark._confidence(5, 0.3, 0.1) == "regression_risk"
    assert park_autodream_benchmark._confidence(5, 0.8, 0.01) == "directional"
    assert park_autodream_benchmark._confidence(5, 0.5, 0.01) == "mixed"

    memory = mongo_memory.OperationalMemory()
    memory.initialize()
    assert memory.ground_truth_improvement()["status"] == "not_measured"
    measurement = {
        "status": "improved",
        "scenarioKey": "ride_down",
        "sourceOutcomeId": "outcome-1",
        "baseline": {"takeRate": 0.4, "followThroughRate": 0.3},
        "observed": {"takeRate": 0.52, "followThroughRate": 0.44, "overallOutcomeScore": 88},
        "lift": {"takeRate": 0.12, "followThroughRate": 0.14, "queuedGuestsAvoided": 80},
    }
    memory._fallback["outcome_events"].append({"_id": "outcome-1", "createdAt": "2026-05-24T00:00:00Z", "promotionImpactMeasurements": [measurement] * 5})
    measured = memory.ground_truth_improvement()
    assert measured["status"] == "measured"
    assert measured["confidence"] == "validated"
    stored = memory.record_autodream_benchmark(benchmark)
    assert stored["status"] == "stored"
    assert memory.latest_documents("autodream_benchmarks", 1)[0]["documentType"] == "autodream_benchmark"
    monkeypatch.setattr(mongo_memory, "_memory", memory)
    assert mongo_memory.record_autodream_benchmark(benchmark)["status"] == "stored"

    monkeypatch.setattr(gcp_training_seed, "online_improvement_status", lambda: {"ready": True})
    monkeypatch.setattr(gcp_training_seed, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(gcp_training_seed, "run_training_seed", lambda rounds, scenarios, allow_duplicates=False: asyncio.sleep(0, result=[{"scenario": scenarios[0]}]))
    monkeypatch.setattr(__import__("sys"), "argv", ["gcp_training_seed.py", "--rounds", "1", "--scenarios", "ride_down"])
    gcp_training_seed.main()
    assert '"runs": 1' in capsys.readouterr().out


def test_policy_loader_invalid_schema_branches():
    books = {
        "policy_books": [
            {
                "source": "book-a.json",
                "content": {
                    "policy_book_id": "duplicate",
                    "decision_rules": [
                        "not-a-rule",
                        {
                            "id": "rule.bad",
                            "applies_to": "bad",
                            "block_conditions": "bad",
                            "review_conditions": [
                                "bad-condition",
                                {
                                    "extra": True,
                                    "message": "",
                                    "targets": "ride",
                                    "actions": "reroute",
                                    "text_contains": "queue",
                                    "unless_policy_status": "allowed",
                                    "state": "bad",
                                },
                                {
                                    "message": "bad state fields",
                                    "state": {
                                        "unknown": True,
                                        "any_zone_density_gte": "high",
                                        "weather_storm_risk_gte": "stormy",
                                        "any_ride_status": ["down"],
                                    },
                                },
                            ],
                        },
                    ],
                    "judges": {"safety": {"policy_ref": "KNOWN-REF"}},
                },
            },
            {"source": "book-b.json", "content": {"policy_book_id": "duplicate", "decision_rules": []}},
            {
                "source": "governance.json",
                "content": {
                    "policy_book_id": "parkpulse_governance_index",
                    "active_policy_books": ["missing-book"],
                    "default_action_policy_refs": "BAD",
                    "monitoring_lanes": [
                        "bad-lane",
                        {"primary_policy_ref": ""},
                        {"primary_policy_ref": "MISSING-REF"},
                    ],
                },
            },
        ]
    }
    validation = policy_loader.validate_policy_books(books)
    issues = "\n".join(validation["issues"])
    assert validation["status"] == "needs_cleanup"
    assert "Duplicate policy_book_id values" in issues
    assert "rule.bad.applies_to must be an object" in issues
    assert "rule.bad.block_conditions must be a list" in issues
    assert "review_conditions[0] must be an object" in issues
    assert "review_conditions[1].targets must be a list of strings" in issues
    assert "review_conditions[1].state must be an object" in issues
    assert "review_conditions[2].state.any_ride_status must be a string" in issues
    assert "default_action_policy_refs must be a list of strings" in issues
    assert "monitoring_lanes[0] must be an object" in issues
    assert "monitoring_lanes[1].primary_policy_ref is required" in issues


def test_digital_twin_helpers_and_simulation_tail_paths():
    state = sample_state()
    assert park_twin_engine._as_int("bad", 7) == 7
    assert park_twin_engine._as_float("bad", 2.5) == 2.5
    assert park_twin_engine._primary_ride({"guestFlow": {"rides": []}})["id"] == "dragonCoaster"
    assert len(park_twin_engine._default_target_mix({"guestFlow": {"rides": []}})) == 3

    ride = {
        "status": "normal",
        "queueGuests": 120,
        "effectiveThroughput": 300,
        "capacityPerHour": 600,
        "staffRequired": 4,
        "staffAvailable": 2,
    }
    park_twin_engine._recompute_ride(ride, 5)
    assert ride["status"] == "constrained"

    projected_plan = {
        "target": "traffic",
        "action": "reroute",
        "projected_impact": {"movedGuests": 300},
        "action_mix": {},
    }
    rerouted = park_twin_engine.transition_state(state, projected_plan, minutes=6, seed="tail", stochastic=False)
    assert rerouted["guestFlow"]["activePolicy"] == "reroute"
    food = park_twin_engine.transition_state(state, {"target": "food", "action": "suppress_item"}, minutes=3, seed="food", stochastic=False)
    assert "chicken_tenders" in food["foodInventory"]["suppressedItems"]
    energy = park_twin_engine.transition_state(state, {"target": "energy", "action": "protect_hvac"}, minutes=3, seed="energy", stochastic=False)
    assert energy["guestFlow"]["activePolicy"] == "protect_hvac"

    unsafe_after = sample_state()
    unsafe_after["guestFlow"]["rides"][0]["status"] = "down"
    unsafe_after["guestFlow"]["rides"][0]["effectiveThroughput"] = 100
    unsafe_after["incidentReadiness"]["emergencyAccessBlocked"] = True
    scored = park_twin_engine.score_outcome(state, unsafe_after, {"target": "ride", "action": "reopen"})
    assert scored["metrics"]["safety_violations"] >= 2

    assert digital_twin_tools._bounded(120, 0, 100) == 100
    assert digital_twin_tools._zones({"guestFlow": {"zones": "bad"}}) == []
    assert digital_twin_tools._rides({"guestFlow": {"rides": "bad"}}) == []
    assert digital_twin_tools._find_by_id([{"id": "a"}], None) == {}
    sim_tool = digital_twin_tools.run_digital_twin_tool(
        "simulate_action",
        state,
        {
            "target": "ride",
            "action": "reroute",
            "projected_impact": {"movedGuests": 120},
            "scorecard": {"overall": 80},
        },
    )
    assert sim_tool["output"]["optimizer_prior"]["projected_impact"]["movedGuests"] == 120
    assert digital_twin_tools.run_digital_twin_tool("tick_simulation", state, {"minutes": 99})["output"]["minutes"] == 30
    assert digital_twin_tools.run_digital_twin_tool("get_noisy_observation", state, {"seed": "tail"})["output"]["mode"] == "noisy_partial_observation"
    assert digital_twin_tools.run_digital_twin_tool("score_outcome", state, {"target": "energy", "action": "protect_hvac"})["output"]["status"] == "ok"

    seeded_hour, seeded_minute = park_simulation._seeded_time("tail")
    assert (seeded_hour, seeded_minute) == park_simulation._seeded_time("tail")
    assert 0 <= seeded_hour < 24
    assert 0 <= seeded_minute < 60
    assert park_simulation._top_by([], "density") == {}
    assert park_simulation._audit_tone(90) == "critical"
    assert park_simulation._audit_tone(70) == "warning"
    assert park_simulation._audit_tone(10) == "watch"
    assert park_simulation._zone_name([], "missing") == "missing"
    proactive_rides = park_simulation._rides("ride_down", "proactive_commit")
    assert proactive_rides[0]["waitMins"] == 38
    audit = park_simulation._operations_audit(
        12,
        30,
        "food_spike",
        "redeploy",
        proactive_rides,
        state["guestFlow"]["zones"],
        state["guestFlow"]["paths"],
        [{"createdAt": "2026-05-24T12:29:00Z", "targetId": "coasterPlaza", "message": "operator note"}],
        70,
    )
    assert audit["workLogs"][0]["source"] == "operator_injected_signal"


def test_mongo_ground_truth_confidence_branches():
    def measured_status(items):
        memory = mongo_memory.OperationalMemory()
        memory.initialize()
        memory._fallback["outcome_events"] = [{"_id": "outcome", "createdAt": "2026-05-24T00:00:00Z", "promotionImpactMeasurements": items}]
        return memory.ground_truth_improvement(limit=10)

    base = {
        "scenarioKey": "ride_down",
        "sourceOutcomeId": "outcome",
        "baseline": {"takeRate": 0.5, "followThroughRate": 0.4},
        "observed": {"takeRate": 0.51, "followThroughRate": 0.41, "overallOutcomeScore": 74},
        "lift": {"takeRate": 0.01, "followThroughRate": 0.01, "queuedGuestsAvoided": 5},
    }
    regressed = measured_status([{**base, "status": "regressed", "lift": {"takeRate": -0.1, "followThroughRate": -0.1, "queuedGuestsAvoided": -30}}])
    assert regressed["confidence"] == "regression_risk"
    assert "Regression risk" in regressed["recommendation"]

    early = measured_status([{**base, "status": "improved"}])
    assert early["confidence"] == "early_signal"
    assert "Early signal" in early["recommendation"]

    directional = measured_status([{**base, "status": "improved", "lift": {"takeRate": 0.06, "followThroughRate": 0.02, "queuedGuestsAvoided": 15}}] * 3)
    assert directional["confidence"] == "directional"
    assert "Directional signal" in directional["recommendation"]

    mixed = measured_status([{**base, "status": "neutral"}] * 5)
    assert mixed["confidence"] == "mixed"
    assert "Mixed results" in mixed["recommendation"]
