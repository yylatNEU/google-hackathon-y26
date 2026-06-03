import asyncio
import copy
import importlib
import json
import os
import sys
from types import SimpleNamespace

os.environ.setdefault("MONGODB_DISABLE_DRIVER_IMPORT", "1")

import pytest

pytestmark = pytest.mark.integration


class LazyModule:
    def __init__(self, module_name: str):
        object.__setattr__(self, "_module_name", module_name)
        object.__setattr__(self, "_module", None)

    def _load(self):
        module = object.__getattribute__(self, "_module")
        if module is None:
            module = importlib.import_module(object.__getattribute__(self, "_module_name"))
            object.__setattr__(self, "_module", module)
        return module

    def __getattr__(self, name: str):
        return getattr(self._load(), name)

    def __setattr__(self, name: str, value):
        setattr(self._load(), name, value)


arize_config = LazyModule("arize_config")
bigquery_analytics = LazyModule("bigquery_analytics")
memory_ops_agent = LazyModule("memory_ops_agent")
mongo_memory = LazyModule("mongo_memory")
park_action_result = LazyModule("park_action_result")
park_action_bridge = LazyModule("park_action_bridge")
park_agent_monitoring = LazyModule("park_agent_monitoring")
park_autodream_agent = LazyModule("park_autodream_agent")
park_delivery = LazyModule("park_delivery")
park_event_planner = LazyModule("park_event_planner")
park_gemini_agent = LazyModule("park_gemini_agent")
park_optimizer = LazyModule("park_optimizer")
park_outcome_loop = LazyModule("park_outcome_loop")
park_proactive_agent = LazyModule("park_proactive_agent")
park_replay_store = LazyModule("park_replay_store")
park_simulation = LazyModule("park_simulation")
park_multi_agent = LazyModule("park_multi_agent")
parkpulse_api = LazyModule("parkpulse_api")
run_autodream = LazyModule("run_autodream")
lazy_main = LazyModule("main")


def OperationalMemory(*args, **kwargs):
    from mongo_memory import OperationalMemory as _OperationalMemory

    return _OperationalMemory(*args, **kwargs)


def ParkSimulation(*args, **kwargs):
    from park_simulation import ParkSimulation as _ParkSimulation

    return _ParkSimulation(*args, **kwargs)


def run(coro):
    return asyncio.run(coro)


def sample_state():
    sim = ParkSimulation()
    state = run(sim.get_state())
    state["simTime"] = {"day": 1, "hour": 17, "minute": 45}
    state["staffing"]["openCallouts"] = 22
    state["energy"]["gridLoadPercent"] = 95
    state["weather"]["heatIndexF"] = 99
    return state


def sample_context():
    return {
        "status": {"mode": "demo_fallback", "connected": False},
        "retrieved": {
            "method": "keyword_similarity",
            "playbooks": [{"_id": "pb_ride_breakdown", "title": "Ride split", "summary": "Split demand"}],
            "incidents": [{"_id": "inc_dragon", "summary": "One destination overload", "lesson": "Split routes"}],
            "learnings": [
                {
                    "_id": "learn_low_take",
                    "scenarioKey": "ride_down",
                    "lesson": "Use stronger offers",
                    "rule": "Prefer visible control actions",
                    "confidence": 88,
                    "useCount": 2,
                    "adjustment": {
                        "takeRateMultiplier": 1.1,
                        "preferComfortProtection": True,
                        "requireEquipmentOrStaffAction": True,
                        "promotionStrengthBias": "increase",
                    },
                }
            ],
        },
    }


class FakeBigQueryJob:
    def __init__(self, rows):
        self.rows = rows

    def result(self):
        return self.rows


class FakeBigQueryClient:
    def __init__(self, project=None):
        self.project = project
        self.queries = []

    def query(self, query, job_config=None):
        self.queries.append((query, job_config))
        return FakeBigQueryJob(
            [
                {
                    "action_cohort": "guest_app",
                    "prior_take_rate": 0.68,
                    "prior_follow_through": 0.57,
                    "avg_response_score": 82.5,
                    "run_count": 12,
                },
                {
                    "action_cohort": "generic_broadcast",
                    "prior_take_rate": 0.24,
                    "prior_follow_through": 0.18,
                    "avg_response_score": 41,
                    "run_count": 4,
                },
            ]
        )


class FakeBigQueryModule:
    class QueryJobConfig:
        def __init__(self, query_parameters=None):
            self.query_parameters = query_parameters or []

    class ScalarQueryParameter:
        def __init__(self, name, field_type, value):
            self.name = name
            self.field_type = field_type
            self.value = value

    Client = FakeBigQueryClient


def ready_props():
    from gemini_provider import GeminiAgentProperties

    return GeminiAgentProperties(
        provider="Gemini Developer API",
        platform="gemini_api",
        model="gemini-test",
        use_gemini_enterprise=False,
        use_vertex_ai=False,
        project=None,
        location=None,
        enterprise_collection_id="default",
        enterprise_engine_id=None,
        enterprise_assistant_id=None,
        api_version="v1beta",
        credentials_mode="api_key",
        has_api_key=True,
        has_project=False,
        has_location=False,
        has_cloud_runtime_credentials=False,
        phoenix_project="parkpulse-ai",
        phoenix_configured=False,
        phoenix_tracing_enabled=False,
        phoenix_collector_endpoint=None,
        has_application_credentials_env=False,
        has_adc_file=False,
    )


def unready_props():
    from gemini_provider import GeminiAgentProperties

    props = ready_props()
    return GeminiAgentProperties(**{**props.__dict__, "has_api_key": False})


class FakeModels:
    def __init__(self, text=None, error=None):
        self.text = text
        self.error = error
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(text=self.text)


class FakeClient:
    def __init__(self, text=None, error=None):
        self.models = FakeModels(text, error)


class FakeGenerateContentConfig:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeThinkingConfig:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def install_fake_genai_types(monkeypatch):
    fake_types = SimpleNamespace(GenerateContentConfig=FakeGenerateContentConfig, ThinkingConfig=FakeThinkingConfig)
    fake_genai = SimpleNamespace(types=fake_types)
    google_module = sys.modules.get("google", SimpleNamespace())
    setattr(google_module, "genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)


@pytest.fixture(autouse=True)
def clear_delivery_outbox(monkeypatch):
    for name in (
        "PARKPULSE_ENABLE_LIVE_GCP_DELIVERY_ADAPTER",
        "PARKPULSE_ENABLE_FIRESTORE_MIRROR",
        "ENABLE_PARKPULSE_PUBSUB",
        "ENABLE_PARKPULSE_FCM",
        "ENABLE_PARKPULSE_PSEUDO_FCM",
        "ENABLE_PARKPULSE_FIRESTORE",
        "ENABLE_PARKPULSE_DATAFLOW",
        "ENABLE_PARKPULSE_WORKFLOWS",
        "ENABLE_VERTEX_GENAI_EVAL",
        "PARKPULSE_ENABLE_HOSTED_EVAL_TRIGGER",
        "ENABLE_VERTEX_CONTINUOUS_EVAL",
        "ENABLE_GCP_CLOUD_TRACE_EXPORT",
    ):
        monkeypatch.setenv(name, "false")
    for name in (
        "VERTEX_GENAI_EVALUATOR_ID",
        "ARIZE_HOSTED_EVALUATOR_ID",
        "VERTEX_EVAL_ACCESS_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    park_delivery._outbox.clear()
    yield
    park_delivery._outbox.clear()


def test_delivery_outcomes_and_simulation_branches():
    state = sample_state()
    action_mix = {
        "guest_reroute": {
            "enabled": True,
            "target_mix": [
                {"destinationId": "theaterB", "destination": "Theater B", "share": 0.35},
                {"destinationId": "arcade", "destination": "Arcade Zone", "share": 0.25},
            ],
            "offer": "bonus",
            "promotionStrength": "high",
            "expectedTakeRate": 0.43,
            "expectedFollowThroughRate": 0.36,
            "estimatedMovedGuests": 610,
        },
        "staffing": {"move_staff": [{"role": "crowd_control", "count": 3, "from": "Entrance", "to": "Coaster Plaza"}]},
        "facilities": {"hvac": {"protectShelterComfort": True, "indoorHubSetpointF": 72, "arcadeZoneSetpointF": 73}},
        "food": {"suppressItems": ["chicken"], "promoteItems": ["pizza"], "avoidExtraDemandAt": ["foodCourt1"]},
    }
    selected = {"target": "ride", "action": "reroute", "label": "reroute"}

    dispatches = park_delivery.build_delivery_plan("ride_down", selected, state, "decision-1", action_mix)
    assert park_delivery.delivery_summary(dispatches) == {
        "total": 4,
        "guest_app": 2,
        "worker_device": 1,
        "equipment_controller": 1,
        "pending_operator_approval": 0,
    }
    response = park_delivery.response_summary(dispatches)
    assert response["status"] in {"healthy", "watch"}
    assert park_delivery.latest_dispatches(2)[0]["channel"] == "guest_app"
    assert park_delivery.send_equipment_command({"requiresHumanApproval": True})["status"] == "pending_operator_approval"
    assert park_delivery.delivery_contract()["ports"][0]["channel"] == "guest_app"

    empty_response = park_delivery.response_summary([{"channel": "guest_app", "response": {"state": "pending"}}])
    assert empty_response["status"] == "waiting_for_response"

    sim = ParkSimulation()
    run(sim.step())
    for kind, target in [
        ("ride_failure", "dragonCoaster"),
        ("demand_spike", "coasterPlaza"),
        ("food_spike", "foodCourt1"),
        ("staff_callout", "dragonCoaster"),
        ("energy_spike", "indoorHub"),
        ("storm_risk", "coveredPlaza"),
        ("unknown", "gardenLoop"),
    ]:
        assert run(sim.inject_event(kind, target, 130))["event"]["intensity"] == 100
    assert run(sim.execute_action("scenario", "food_spike"))["status"] == "success"
    assert run(sim.execute_action("ride", "reroute"))["status"] == "success"
    assert run(sim.execute_action("unknown", "noop"))["status"] == "noop"
    applied = run(sim.apply_delivery_outcomes(dispatches, "test_loop"))
    assert applied["status"] == "success"
    assert run(sim.apply_delivery_outcomes([], "empty"))["status"] == "noop"
    assert run(sim.reset_demo())["status"] == "success"


def test_optimizer_custom_mixes_learning_and_revision_paths():
    state = sample_state()
    flow = state["guestFlow"]
    failed = park_optimizer._primary_disrupted_ride(flow["rides"])
    destinations = park_optimizer._available_destinations(flow["rides"], failed["id"])
    zones = park_optimizer._zone_by_id(flow["zones"])
    failed_zone = zones[failed["zone"]]
    base_common = {
        "fromRide": failed["name"],
        "fromZone": failed_zone["name"],
        "food": {"avoidExtraDemandAt": ["Food Court 1"], "promoteItems": ["pizza_combo"]},
        "staffing": {"move_staff": [], "protectedBreaks": True},
        "facilities": {"hvac": {"protectShelterComfort": False}},
    }

    assert park_optimizer._bounded(150, 0, 100) == 100
    assert park_optimizer._primary_disrupted_ride([])["id"] == "dragonCoaster"
    assert park_optimizer._strength("wild") == "medium"
    assert park_optimizer._as_float("x", 2.5) == 2.5
    assert park_optimizer._as_int("x", 4) == 4
    assert park_optimizer._candidate_from_custom_mix("bad", state, destinations, failed, failed_zone, base_common) is None
    assert park_optimizer._candidate_from_custom_mix({"target_mix": [{"destinationId": failed["id"], "share": 0.9}]}, state, destinations, failed, failed_zone, base_common) is None

    custom = park_optimizer._candidate_from_custom_mix(
        {
            "name": "High response split",
            "target_mix": [
                {"destination_id": "theaterB", "share": 0.8},
                {"destination_id": "arcade", "share": 0.5},
                {"destination_id": "indoorLaunch", "share": 0.2},
            ],
            "hold_share": 0.02,
            "promotion_strength": "high",
            "staff_moves": [{"role": "greeter", "count": 9, "from": "Entrance", "to": "Indoor Hub"}],
            "suppress_items": ["chicken_tenders"],
            "promote_items": ["pizza_combo"],
            "hvac_setpoints": {"indoorHub": 71, "arcadeZone": 72},
        },
        state,
        destinations,
        failed,
        failed_zone,
        base_common,
    )
    assert custom["source"] == "gemini_custom_mix"
    assert custom["action_mix"]["guest_reroute"]["promotionStrength"] == "high"
    assert custom["action_mix"]["staffing"]["move_staff"][0]["count"] == 6

    learning = park_optimizer._learning_summary(park_optimizer._learning_rules(sample_context(), "ride_down"))
    adjusted = park_optimizer._apply_learning_to_candidates([custom], learning)
    assert adjusted[0]["scorecard"]["learning_adjustment"] > 0

    llm_plan = {
        "custom_action_mixes": [
            {"name": "Mix A", "target_mix": [{"destinationId": "theaterB", "share": 0.4}, {"destinationId": "arcade", "share": 0.25}], "promotionStrength": "high"},
            {"name": "Mix B", "target_mix": [{"destinationId": "skyDrop", "share": 0.3}, {"destinationId": "theaterB", "share": 0.2}], "promotionStrength": "medium"},
        ]
    }
    optimization = park_optimizer.optimize_park_response(state, "ride_down", sample_context(), llm_plan)
    assert optimization["mode"] == "gemini_plan_tournament"
    assert park_optimizer.revise_plan_after_response(optimization, {"score": 90}) is None
    revision = park_optimizer.revise_plan_after_response(optimization, {"score": 41, "takeRate": 0.2, "reactiveFollowThroughRate": 0.12})
    assert revision["selected_action"]["action"] == "reroute"
    assert park_optimizer._offer_for_strength("low").startswith("App guidance")

    hybrid_context = sample_context()
    hybrid_context["role_agent_proposals"] = park_multi_agent.build_role_agent_proposals(
        state,
        {"route": "operations", "scenario_key": "ride_down"},
        {},
        hybrid_context,
    )
    hybrid = park_optimizer.optimize_park_response(state, "ride_down", hybrid_context, {})
    assert hybrid["mode"] == "hybrid_role_tournament"
    assert hybrid["role_proposal_candidate_count"] >= 3
    assert hybrid["decision_bridge_resolution"]["mode"] == "decision_bridge_role_resolution"
    assert any(candidate.get("source") == "role_agent_proposal" for candidate in hybrid["candidates"])
    accepted = hybrid["decision_bridge_resolution"]["accepted_role_proposal"]
    attribution = {
        "mode": "role_outcome_attribution",
        "scenario_key": "ride_down",
        "selected_action": hybrid["selected_plan"]["selected_action"],
        "decision_bridge_resolution": hybrid["decision_bridge_resolution"],
        "summary": {"proposal_count": 1, "accepted_count": 1, "rejected_count": 0, "winner_agent_id": accepted["agent_id"]},
        "role_outcomes": [
            {
                "agent_id": accepted["agent_id"],
                "role": accepted["role"],
                "proposal_type": accepted["proposal_type"],
                "status": "accepted",
                "proposal": accepted,
                "candidate_id": hybrid["selected_plan_id"],
                "candidate_score": hybrid["selected_plan"]["scorecard"]["overall"],
                "outcome_metrics": {"response_score": 82, "take_rate": 0.46, "follow_through": 0.41, "eval_score": 84},
                "learning_signal": {"status": "positive_prior", "reason": "Accepted role proposal met response threshold."},
            }
        ],
    }
    assert attribution["summary"]["accepted_count"] == 1
    memory = OperationalMemory()
    memory.initialize()
    receipt = memory.record_role_proposal_outcomes(attribution, "decision_role_unit", "outcome_role_unit", state)
    assert receipt["stored_count"] == len(attribution["role_outcomes"])
    assert memory.latest_documents("agent_role_proposals", 1)[0]["decisionId"] == "decision_role_unit"
    priors = memory.role_quality_priors("ride_down")
    assert priors["by_agent"][accepted["agent_id"]]["prior_adjustment"] > 0
    hybrid_context["role_quality_priors"] = priors
    learned_hybrid = park_optimizer.optimize_park_response(state, "ride_down", hybrid_context, {})
    assert learned_hybrid["selected_plan"]["role_proposal"]["memory_prior"]["agent_id"] == accepted["agent_id"]
    assert learned_hybrid["selected_plan"]["scorecard"]["role_memory_prior_adjustment"] > 0


def test_event_planner_fallback_scoring_and_gemini_paths(monkeypatch):
    state = sample_state()
    context = sample_context()

    assert park_event_planner._first_json_object("") is None
    assert park_event_planner._first_json_object("prefix {\"a\": 1} suffix") == {"a": 1}
    assert park_event_planner._memory_summary(context)["playbooks"][0]["_id"] == "pb_ride_breakdown"
    prompt = park_event_planner._prompt(state, "Plan summer concert", context)
    assert "operator_request" in prompt
    assert "Plan summer concert" in prompt

    monkeypatch.setattr(park_event_planner, "get_gemini_agent_properties", unready_props)
    fallback = run(park_event_planner.build_event_ops_plan(state, " ", context))
    assert fallback["runtime"] == "deterministic_fallback"
    assert fallback["quality"]["status"] == "approved_for_operator_review"

    raw = {
        "event_id": "event-1",
        "event_name": "Learned Halloween",
        "selected_concept": "Balanced",
        "equipment_moves": [{"equipment": "fog_machines", "quantity": 2}],
        "staffing_plan": [{"role": "crowd_control", "estimated_count": 4}],
        "judge_scorecard": {"overall": 91, "constraint_following": 92},
        "operator_summary": "Run the learned plan.",
    }
    fake_client = FakeClient(json.dumps(raw))
    install_fake_genai_types(monkeypatch)
    monkeypatch.setattr(park_event_planner, "get_gemini_agent_properties", ready_props)
    monkeypatch.setattr(park_event_planner, "get_gemini_client", lambda: fake_client)
    monkeypatch.setattr(park_event_planner, "get_gemini_model", lambda: "gemini-test")
    plan = run(park_event_planner.build_event_ops_plan(state, "Plan a parade", context))
    assert plan["runtime"] == "gemini_api"
    assert plan["event_id"] == "event-1"
    assert fake_client.models.calls

    monkeypatch.setenv("PARKPULSE_EVENT_GEMINI_TIMEOUT_SECONDS", "bad")
    monkeypatch.setattr(park_event_planner, "get_gemini_client", lambda: FakeClient(error=RuntimeError("provider down")))
    errored = run(park_event_planner.build_event_ops_plan(state, "Plan a parade", context))
    assert errored["runtime"] == "deterministic_fallback_after_gemini_error"
    assert "provider down" in errored["errors"][0]

    weak = copy.deepcopy(raw)
    weak["equipment_moves"] = [{"equipment": "fog_machines", "quantity": 99}]
    weak["staffing_plan"] = [{"role": "all", "estimated_count": 300}]
    weak["judge_scorecard"] = {"overall": 82, "equipment_feasibility": 82}
    score = park_event_planner._score_plan(weak, state)
    assert score["status"] in {"needs_revision", "blocked"}


def test_bigquery_priors_and_relational_context_feed_prompts(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_BIGQUERY_ANALYTICS", "true")
    monkeypatch.setenv("BIGQUERY_PROJECT", "parkpulse-test")
    monkeypatch.setenv("BIGQUERY_DATASET", "analytics")
    monkeypatch.setattr(bigquery_analytics, "bigquery", FakeBigQueryModule)
    monkeypatch.setattr(bigquery_analytics, "_bigquery_import_error", None)

    priors = bigquery_analytics.build_bigquery_agent_priors("ride_down", {"latest_outcomes": [{}]})
    assert priors["source"] == "bigquery_query"
    assert priors["best_prior"]["cohort"] == "guest_app"
    assert priors["weakest_prior"]["cohort"] == "generic_broadcast"

    monkeypatch.setenv("PARKPULSE_REPLAY_DB", str(tmp_path / "replay.db"))
    monkeypatch.setenv("PARKPULSE_DB_BACKUP_DIR", str(tmp_path / "backups"))
    run_row = park_replay_store.create_replay_run("seed", "ride_down")
    park_replay_store.append_replay_event(
        run_row["run_id"],
        {"id": "event-1", "kind": "agent_action", "label": "Reroute guests", "result": {"status": "success"}},
    )
    relational = park_replay_store.replay_collaboration_context()
    assert relational["latest_run"]["run_id"] == run_row["run_id"]
    assert relational["recent_events"][0]["event_id"] == "event-1"

    context = sample_context()
    context["bigquery_priors"] = priors
    context["relational_context"] = relational
    prompt = park_gemini_agent._prompt(sample_state(), "ride_down", context)
    assert "bigquery_priors" in prompt
    assert "relational_context" in prompt
    assert "guest_app" in prompt
    assert run_row["run_id"] in prompt


def test_proactive_agent_brief_and_eval_paths(monkeypatch):
    state = sample_state()
    proactive = park_proactive_agent.build_proactive_insights(state)
    assert proactive["summary"]["insight_count"] >= 6
    assert park_proactive_agent._first_json_object("bad") is None

    evaluation = park_proactive_agent.build_proactive_eval(proactive)
    assert evaluation["status"] == "commit_pre_stage_actions"

    monkeypatch.setattr(park_proactive_agent, "get_gemini_agent_properties", unready_props)
    fallback = run(park_proactive_agent.build_proactive_operator_brief(state, proactive, sample_context()))
    assert fallback["runtime"] == "deterministic_fallback"
    assert fallback["should_revise_event_plan"] is True

    async def fake_proactive_json(prompt, timeout_seconds):
        return json.dumps(
            {
                "operator_brief": "Pre-stage equipment and split the queue.",
                "recommended_commitments": ["queue_pressure_prediversion"],
                "should_revise_event_plan": False,
            }
        )

    monkeypatch.setattr(park_proactive_agent, "get_gemini_agent_properties", ready_props)
    monkeypatch.setattr(park_proactive_agent, "_generate_proactive_json", fake_proactive_json)
    brief = run(park_proactive_agent.build_proactive_operator_brief(state, proactive, sample_context()))
    assert brief["runtime"] == "gemini_api"
    assert brief["should_revise_event_plan"] is True
    assert brief["latency_strategy"] == "subprocess_hard_timeout_compact_prompt"

    monkeypatch.setenv("PARKPULSE_PROACTIVE_GEMINI_TIMEOUT_SECONDS", "bad")

    async def failed_proactive_json(prompt, timeout_seconds):
        raise RuntimeError("brief failed")

    monkeypatch.setattr(park_proactive_agent, "_generate_proactive_json", failed_proactive_json)
    errored = run(park_proactive_agent.build_proactive_operator_brief(state, proactive, sample_context()))
    assert errored["runtime"] == "deterministic_fallback_after_gemini_error"
    assert "brief failed" in errored["errors"][0]


def test_agent_monitoring_and_outcome_loop_cover_policy_lanes(monkeypatch):
    state = sample_state()
    action_plan = {
        "scenario": {"key": "ride_down", "name": "Ride Down"},
        "runtime": "gemini_api",
        "model": "gemini-test",
        "attempted_gemini": True,
        "performance_status": "success",
        "response_latency_ms": 432,
        "timeout_seconds": 90,
        "confidence_score": 91,
        "recommended_actions": [
            {
                "action_id": "safe-action",
                "title": "Route guests to lower wait zones",
                "owner": "Ops",
                "park_action": {"target": "ride", "action": "reroute"},
                "policy_compliance": {"status": "ok", "policy_refs": ["PARK-OPS-001"]},
            },
            {
                "action_id": "blocked-action",
                "title": "Reopen without clearance and route all guests",
                "expected_impact": "Use named guest compensation",
                "owner": "Ops",
                "park_action": {"target": "ride", "action": "reopen"},
                "policy_compliance": {"policy_refs": ["UNKNOWN-REF"]},
            },
            {
                "action_id": "review-action",
                "title": "Recovery offer",
                "owner": "Care",
                "policy_compliance": {},
            },
        ],
    }
    eval_result = {
        "scorecard": {"overall": 62, "needs_human_approval": True},
        "evals": [{"label": "Safety", "score": 40}],
        "arize_trace": {"dimensions": ["safety"], "trace_url": "http://trace"},
    }

    class FakeArize:
        def public_dict(self):
            return {"ready": False, "project_name": "", "collector_endpoint": "", "readiness_issues": ["disabled"]}

    monkeypatch.setattr(park_agent_monitoring, "get_arize_status", lambda: FakeArize())
    monkeypatch.setattr(park_agent_monitoring, "get_gemini_agent_properties", ready_props)
    monitoring = park_agent_monitoring.build_park_agent_monitoring(
        state,
        action_plan,
        eval_result,
        {"count": 3},
        [{"_id": "decision-live", "runtimeTelemetry": {"runtime": "gemini_api", "responseLatencyMs": 700}}],
    )
    assert monitoring["overall_status"] == "blocked"
    assert monitoring["summary"]["blocked_count"] >= 1
    assert any(action["policy_status"] == "blocked" for action in monitoring["supervised_actions"])
    assert monitoring["gemini_performance"]["status"] == "success"
    assert monitoring["gemini_performance"]["latency_ms"] == 432
    assert monitoring["gemini_performance"]["gcp_monitor"]["primary_path"] == "gcp_bigquery"

    before = sample_state()
    after = copy.deepcopy(before)
    after["guestFlow"]["zones"][1]["density"] -= 12
    after["guestFlow"]["zones"][1]["comfortScore"] += 8
    dispatches = [
        park_delivery.send_guest_promotion({"expectedTakeRate": 0.2, "expectedFollowThroughRate": 0.15, "estimatedMovedGuests": 400}),
        park_delivery.send_worker_notification({"role": "crowd_control", "priority": "high"}),
        park_delivery.send_equipment_command({"requiresHumanApproval": False}),
    ]
    response = park_delivery.response_summary(dispatches)
    proactive = park_proactive_agent.build_proactive_insights(before)
    brief = {"operator_brief": "commit", "should_revise_event_plan": True, "plan_revision_prompt": "revise"}
    closed = park_outcome_loop.build_closed_loop_outcome(before, after, dispatches, response, proactive, brief, {"expected_prevention": 85})
    reactive = park_outcome_loop.build_reactive_outcome(
        before,
        after,
        dispatches,
        response,
        {"selected_plan": {"name": "Balanced"}, "candidates": [1, 2]},
        {"root_cause_classification": "ride_down"},
        {"scorecard": {"overall": 80}},
    )
    assert closed["scorecard"]["status"] == "learn_and_revise"
    assert reactive["learning"]["should_update_plan"] is True


class FakeApiSimulation:
    def __init__(self):
        self.sim = ParkSimulation()
        run(self.sim.execute_action("scenario", "ride_down"))

    async def step(self):
        await self.sim.step()

    async def get_state(self):
        state = await self.sim.get_state()
        state["simTime"] = {"day": 1, "hour": 17, "minute": 50}
        state["staffing"]["openCallouts"] = 22
        state["energy"]["gridLoadPercent"] = 95
        state["weather"]["heatIndexF"] = 99
        return state

    async def execute_action(self, target, action):
        return await self.sim.execute_action(target, action)

    async def inject_event(self, kind, target_id, intensity):
        return await self.sim.inject_event(kind, target_id, intensity)

    async def reset_demo(self):
        return await self.sim.reset_demo()

    async def apply_delivery_outcomes(self, dispatches, reason="closed_loop_outcome"):
        return await self.sim.apply_delivery_outcomes(dispatches, reason)

    async def get_replay(self, limit=20):
        return await self.sim.get_replay(limit)

    async def start_replay_run(self, seed=None, scenario_key="ride_down"):
        return await self.sim.start_replay_run(seed, scenario_key)


def install_api_fakes(monkeypatch):
    monkeypatch.setattr(parkpulse_api, "park_simulation", FakeApiSimulation())
    monkeypatch.setattr(parkpulse_api, "sync_park_state", lambda state: {"status": "stored"})
    monkeypatch.setattr(parkpulse_api, "retrieve_operational_context", lambda query, state: sample_context())
    monkeypatch.setattr(parkpulse_api, "record_mongo_agent_decision", lambda *args, **kwargs: "decision-1")
    monkeypatch.setattr(parkpulse_api, "record_mongo_event_plan", lambda *args, **kwargs: "event-plan-1")
    monkeypatch.setattr(parkpulse_api, "record_mongo_outcome_event", lambda *args, **kwargs: "outcome-1")
    monkeypatch.setattr(parkpulse_api, "get_operational_memory_dashboard", lambda query: {"status": {"mode": "demo"}, "collections": [], "latest_decisions": [{"_id": "d"}], "latest_evals": [{"_id": "e"}], "latest_outcomes": [{"_id": "o"}]})
    monkeypatch.setattr(
        parkpulse_api,
        "supervise_runtime_action",
        lambda *args, **kwargs: {
            "allowed": True,
            "gate_status": "allowed",
            "policy_contract": {"status": "clean", "issues": [], "expected_policy_refs": ["PARK-SAFE-001"]},
            "findings": [],
            "remediation_task": None,
            "customer_care_case": None,
            "ledger_entry": {"id": "ledger-clean"},
        },
    )


def test_parkpulse_api_routes_and_lifecycle(monkeypatch):
    install_api_fakes(monkeypatch)

    async def fake_gemini_plan(state, scenario_key, context, **_kwargs):
        return {
            "runtime": "test",
            "recommended_action": "Split queue",
            "selected_action": {"target": "ride", "action": "reroute"},
            "candidate_actions": [],
            "custom_action_mixes": [
                {"name": "A", "target_mix": [{"destinationId": "theaterB", "share": 0.4}, {"destinationId": "arcade", "share": 0.25}]},
                {"name": "B", "target_mix": [{"destinationId": "skyDrop", "share": 0.3}, {"destinationId": "theaterB", "share": 0.2}]},
            ],
            "confidence_score": 87,
            "root_cause_classification": scenario_key,
            "guest_message": "Use lower wait attractions.",
        }

    async def fake_event_plan(state, prompt, context):
        plan = park_event_planner._fallback_plan(state, prompt, "test_runtime")
        plan["quality"] = park_event_planner._score_plan(plan, state)
        return plan

    async def fake_brief(state, proactive, context):
        return {
            "runtime": "test",
            "operator_brief": "Commit proactive work.",
            "why_now": "Event setup window is open.",
            "recommended_commitments": [
                "shelter_comfort_preload",
                "queue_pressure_prediversion",
                "food_pop_up_prestage",
                "labor_gap_before_overlay",
                "placement_risk_warning",
            ],
            "should_revise_event_plan": True,
            "plan_revision_prompt": "Revise congestion and staffing assumptions.",
            "errors": [],
        }

    monkeypatch.setattr(parkpulse_api, "build_park_gemini_plan", fake_gemini_plan)
    monkeypatch.setattr(park_event_planner, "build_event_ops_plan", fake_event_plan)
    monkeypatch.setattr(parkpulse_api, "build_proactive_operator_brief", fake_brief)
    monkeypatch.setattr(parkpulse_api, "get_park_signals", lambda: asyncio.sleep(0, result={"count": 1}))

    reset = run(parkpulse_api.reset_park_demo())
    assert reset["status"] == "success"
    state = reset["state"]
    assert state["guestFlow"]["activeScenario"]["key"] == "ride_down"
    action_response = run(parkpulse_api.execute_park_action(parkpulse_api.ActionRequest(target="ride", action="reroute")))
    assert action_response["status"] == "success"
    assert action_response["governance"]["policy_contract"]["status"] == "clean"
    assert run(parkpulse_api.inject_park_event(parkpulse_api.SimulationInjectRequest(kind="food_spike", target_id="foodCourt1", intensity=80)))["status"] == "success"
    assert run(parkpulse_api.reset_park_demo())["status"] == "success"

    agent_run = run(parkpulse_api.park_agent_run(parkpulse_api.ParkAgentRunRequest(scenario_key="ride_down")))
    assert agent_run["status"] == "complete"
    assert agent_run["governance"]["policy_contract"]["status"] == "clean"
    assert agent_run["delivery"]["summary"]["total"] >= 1
    assert agent_run["outcome_id"] == "outcome-1"

    event = run(parkpulse_api.plan_park_event(parkpulse_api.EventPlanRequest(prompt="Plan a summer concert", expected_guests=8000, event_theme="Summer concert")))
    assert event["event_plan_id"] == "event-plan-1"
    assert event["planner"]["runtime"] == "test_runtime"
    assert event["event_scope"] == {
        "theme": "Summer concert",
        "event_type": "amusement park event overlay",
        "locked": False,
    }
    assert "Event theme: Summer concert" in event["event_request"]
    assert event["plan"]["traffic_forecast"]
    assert event["plan"]["deployment_suggestions"]

    proactive = run(parkpulse_api.park_proactive_insights())
    assert proactive["summary"]["insight_count"] >= 1
    proactive_run = run(parkpulse_api.park_proactive_run())
    assert proactive_run["event_revision"]["status"] == "complete"
    assert proactive_run["lifecycle"]["completed_count"] >= 6
    assert proactive_run["intelligence_comparison"]["after"]["revision_created"] is True

    assert run(parkpulse_api.park_delivery_contract())["name"].startswith("ParkPulse")
    assert run(parkpulse_api.park_delivery_guest_promotion(parkpulse_api.DeliveryRequest(payload={"scenarioKey": "ride_down", "decisionId": "decision-1"})))["status"] == "delivered"
    assert run(parkpulse_api.park_delivery_worker_notification(parkpulse_api.DeliveryRequest(payload={"role": "crowd_control", "decisionId": "decision-1"})))["status"] == "delivered"
    assert run(parkpulse_api.park_delivery_equipment_command(parkpulse_api.DeliveryRequest(payload={"requiresHumanApproval": True})))["status"] == "pending_operator_approval"
    assert run(parkpulse_api.park_delivery_outbox(5))["count"] <= 5
    assert run(parkpulse_api.park_memory("ride"))["status"]["mode"] == "demo"
    assert run(parkpulse_api.park_integration_status())["latest_decision_id"] == "d"
    assert run(parkpulse_api.park_agent_monitoring())["summary"]["action_count"] >= 1
    review = run(parkpulse_api.park_review_snapshot())
    assert review["status"] in {"reviewable", "prototype_review", "not_ready"}
    assert "GET /api/park/review-snapshot" in review["observation_surface"]["api"]
    assert run(parkpulse_api.park_replay())["event_count"] >= 1
    replay_start = run(parkpulse_api.park_replay_start(parkpulse_api.ReplayStartRequest(seed="api-seed-1", scenario_key="food_spike")))
    assert replay_start["status"] == "success"
    assert replay_start["run"]["seed"] == "api-seed-1"
    assert review["scorecard"]
    assert run(parkpulse_api.park_scenarios())["scenarios"]
    assert run(parkpulse_api.park_agent_roles())["agent_roles"]
    assert "scorecard" in run(parkpulse_api.park_eval_result("ride_down"))
    assert run(parkpulse_api.gcp_gemini_status())["agent"]["name"] == "ParkPulse AI"
    assert "ready" in run(parkpulse_api.arize_status())

    monkeypatch.setattr(parkpulse_api, "sync_park_state", lambda state: (_ for _ in ()).throw(RuntimeError("offline")))
    skipped = run(parkpulse_api.sync_park_state_safe({"guestFlow": {}}))
    assert skipped["status"] == "skipped"
    assert parkpulse_api._rate_percent("bad") == "--"
    assert "Operational action" in parkpulse_api._dispatch_body({"payload": {"promotion": {"offer": ""}}})


def test_parkpulse_new_api_surfaces_and_cache_branches(monkeypatch):
    install_api_fakes(monkeypatch)
    parkpulse_api.clear_hot_endpoint_cache()
    parkpulse_api._hot_endpoint_refreshing.clear()
    parkpulse_api._hot_endpoint_cache_locks.clear()
    parkpulse_api._last_memory_sync_at = 0.0

    assert run(parkpulse_api.root_health())["service"] == "parkpulse-api"
    assert run(parkpulse_api.healthz())["status"] == "ok"
    assert run(parkpulse_api.readyz())["status"] in {"ok", "degraded"}

    monkeypatch.setenv("PARKPULSE_ALLOWED_ORIGINS", " http://one.test, ,http://two.test ")
    origins = parkpulse_api._allowed_origins()
    assert origins[:2] == ["http://one.test", "http://two.test"]
    assert "http://localhost:3000" in origins
    monkeypatch.setenv("PARKPULSE_BAD_FLOAT", "not-a-number")
    assert parkpulse_api._float_env("PARKPULSE_BAD_FLOAT", 2.5) == 2.5

    built = {"count": 0}

    async def builder():
        built["count"] += 1
        return {"value": built["count"]}

    assert run(parkpulse_api.cached_hot_endpoint("unit", 0, builder)) == {"value": 1}
    assert run(parkpulse_api.cached_hot_endpoint("unit", 10, builder)) == {"value": 2}
    assert run(parkpulse_api.cached_hot_endpoint("unit", 10, builder)) == {"value": 2}
    parkpulse_api._hot_endpoint_cache["unit"] = (0, {"stale": True})
    assert run(parkpulse_api.cached_hot_endpoint("unit", 10, builder)) == {"stale": True}
    run(asyncio.sleep(0))

    async def broken_builder():
        raise RuntimeError("refresh failed")

    parkpulse_api._hot_endpoint_refreshing.add("broken")
    run(parkpulse_api.refresh_hot_endpoint("broken", 1, broken_builder))
    assert "broken" not in parkpulse_api._hot_endpoint_refreshing
    run(parkpulse_api.prewarm_hot_endpoint("warm", 1, builder))

    monkeypatch.setattr(parkpulse_api, "sync_park_state", lambda state: {"status": "stored"})
    first_sync = run(parkpulse_api.sync_park_state_safe({"guestFlow": {}}, force=True))
    assert first_sync["status"] == "stored"
    assert run(parkpulse_api.sync_park_state_safe({"guestFlow": {}}))["reason"] == "throttled"
    monkeypatch.setattr(parkpulse_api, "sync_park_state", lambda state: (_ for _ in ()).throw(RuntimeError("sync offline")))
    assert run(parkpulse_api.sync_park_state_safe({"guestFlow": {}}, force=True))["status"] == "skipped"

    state = sample_state()
    audit = {"summary": {"criticalAnomalies": 1, "ingestedEvents": 2}, "findings": [{"id": "finding-1"}]}
    candidate = {
        "status": "ready",
        "selected_action": {
            "park_action": {"target": "ride", "action": "reroute"},
            "title": "Fix queue",
            "owner": "Audit",
            "deadline_minutes": 4,
            "expected_impact": "reduce abnormality",
        },
        "finding": {"id": "finding-1", "recommendedAction": "reroute"},
    }
    monkeypatch.setattr(parkpulse_api, "build_audit_snapshot", lambda current_state: audit)
    monkeypatch.setattr(parkpulse_api, "record_audit_event", lambda event: {**event, "id": "audit-event-1"})
    monkeypatch.setattr(parkpulse_api, "build_audit_action_candidate", lambda audit_payload, current_state: candidate)
    monkeypatch.setattr(parkpulse_api, "record_audit_response", lambda finding_id, response: {"finding_id": finding_id, **response})
    assert run(parkpulse_api.get_park_audit())["summary"]["criticalAnomalies"] == 1
    audit_event = run(parkpulse_api.ingest_park_audit_event(parkpulse_api.AuditEventRequest(source="unit", message="m", signal="s", zoneId="z")))
    assert audit_event["event"]["id"] == "audit-event-1"
    audit_run = run(parkpulse_api.run_park_audit_response(parkpulse_api.AuditRunResponseRequest(execute=False)))
    assert audit_run["status"] == "candidate_only"
    monkeypatch.setattr(parkpulse_api, "build_audit_action_candidate", lambda audit_payload, current_state: {"status": "empty", "reason": "none"})
    assert run(parkpulse_api.run_park_audit_response(parkpulse_api.AuditRunResponseRequest()))["status"] == "noop"

    def blocked_gate(*args, **kwargs):
        return {
            "allowed": False,
            "gate_status": "blocked",
            "policy_contract": {"status": "invalid", "issues": ["blocked"]},
            "findings": ["blocked"],
            "remediation_task": None,
            "customer_care_case": None,
            "ledger_entry": {"id": "ledger-1"},
        }

    monkeypatch.setattr(parkpulse_api, "supervise_runtime_action", blocked_gate)
    blocked_action = run(parkpulse_api.execute_park_action(parkpulse_api.ActionRequest(target="ride", action="unsafe")))
    assert blocked_action["status"] == "blocked"

    def allowed_gate(*args, **kwargs):
        return {
            "allowed": True,
            "gate_status": "allowed",
            "policy_contract": {"status": "clean", "issues": []},
            "findings": [],
            "remediation_task": None,
            "customer_care_case": None,
            "ledger_entry": {"id": "ledger-2"},
        }

    monkeypatch.setattr(parkpulse_api, "supervise_runtime_action", allowed_gate)
    monkeypatch.setattr(parkpulse_api, "record_mongo_raw_signal", lambda signal: "signal-memory-1")
    monkeypatch.setattr(parkpulse_api, "create_customer_care_case", lambda request, current_state: {"id": "case-1", **request})
    signal = run(
        parkpulse_api.park_signal_intake(
            parkpulse_api.SignalIntakeRequest(
                text="Lost child crying near coaster exit, guests are pushing.",
                source="staff_note",
                zoneId="coasterPlaza",
                reporterRole="lead",
            )
        )
    )
    assert signal["status"] == "classified"
    assert signal["customer_care_case"]["id"] == "case-1"
    fusion = run(parkpulse_api.park_signal_fusion_demo(parkpulse_api.SignalFusionRequest(preset="health_accessibility")))
    assert fusion["pipeline"]["sources"]
    assert run(parkpulse_api.park_signal_inbox(3))
    assert run(parkpulse_api.park_learning_episodes())["episode_count"] >= 0

    assert run(parkpulse_api.park_bigquery_priors("ride_down"))
    assert run(parkpulse_api.park_reliability())["status"] == "ok"
    assert run(parkpulse_api.park_replay_backup())["status"] in {"ok", "degraded", "unavailable"}
    assert run(parkpulse_api.park_governance_runtime(5))["domain"] == "amusement_park_operations"
    assert "customer_care_cases" in run(parkpulse_api.park_customer_care(5))
    assert run(parkpulse_api.park_customer_care_create(parkpulse_api.CustomerCareRequest(reason="follow up")))["status"] == "queued"
    assert run(parkpulse_api.park_digital_twin_tools())["tools"]
    assert run(parkpulse_api.park_digital_twin_tool_run(parkpulse_api.DigitalTwinToolRequest(tool="get_park_state")))["tool"] == "get_park_state"
    assert run(parkpulse_api.park_digital_twin_trace())
    assert run(parkpulse_api.park_digital_twin_benchmark_scenarios())["scenario_count"] >= 5
    benchmark = run(parkpulse_api.park_digital_twin_benchmark(parkpulse_api.DigitalTwinBenchmarkRequest(scenario_id="policy_gate_pressure", seed="api-test")))
    assert benchmark["status"] == "complete"
    assert benchmark["summary"]["episodes"] == 1
    async def fake_benchmark_plan(state, scenario_key, context):
        return {
            "runtime": "api_agent_benchmark",
            "recommended_action": "Reroute with bounded policy",
            "confidence_score": 88,
            "selected_action": {"target": "ride", "action": "reroute", "label": "Bounded reroute"},
            "candidate_actions": [],
        }

    def fake_benchmark_optimize(state, scenario_key, context, plan):
        return {
            "mode": "api_agent_optimizer",
            "selected_plan_id": "api-plan",
            "candidate_source": "api-test",
            "selected_plan": {
                "id": "api-plan",
                "selected_action": {"target": "ride", "action": "reroute", "label": "Bounded reroute"},
                "action_mix": {"guest_reroute": {"expectedTakeRate": 0.42, "target_mix": [{"zoneId": "theaterB", "share": 0.5}]}},
            },
        }

    monkeypatch.setattr(parkpulse_api, "build_park_gemini_plan", fake_benchmark_plan)
    monkeypatch.setattr(parkpulse_api, "optimize_park_response", fake_benchmark_optimize)
    agent_benchmark = run(
        parkpulse_api.park_digital_twin_benchmark(
            parkpulse_api.DigitalTwinBenchmarkRequest(
                scenario_id="sensor_lag_mislead",
                seed="api-agent-test",
                policy_under_test="parkpulse_agent",
            )
        )
    )
    assert agent_benchmark["mode"] == "parkpulse_agent_adversarial_benchmark"
    assert agent_benchmark["episodes"][0]["planner"]["runtime"] == "api_agent_benchmark"
    assert run(parkpulse_api.park_memory_maintenance("ride"))
    assert run(parkpulse_api.park_memory_maintenance_repair(parkpulse_api.MemoryOpsRepairRequest(query="ride", limit=2)))["status"] in {"complete", "skipped", "repaired"}
    assert run(parkpulse_api.park_autodream_run(parkpulse_api.AutoDreamRunRequest(scenario_key="ride_down", max_cases=1, persist=False)))["scenario_key"] == "ride_down"
    assert "summary" in run(parkpulse_api.park_autodream_status(2))
    monkeypatch.setattr(parkpulse_api, "promote_autodream_learning", lambda *args: {"status": "promoted"})
    monkeypatch.setattr(parkpulse_api, "review_autodream_learning", lambda *args: {"status": "reviewed"})
    assert run(parkpulse_api.park_autodream_promote(parkpulse_api.AutoDreamPromoteRequest(dream_learning_id="dream-1")))["status"] == "promoted"
    assert run(parkpulse_api.park_autodream_review(parkpulse_api.AutoDreamReviewRequest(dream_learning_id="dream-1", reason="no")))["status"] == "reviewed"
    assert "status" in run(parkpulse_api.park_analytics("ride"))
    assert run(parkpulse_api.gcp_improvement_status())
    assert "ready" in run(parkpulse_api.gcp_trace_eval_status())

    no_replay = SimpleNamespace(get_state=lambda: asyncio.sleep(0, result=state))
    monkeypatch.setattr(parkpulse_api, "park_simulation", no_replay)
    assert run(parkpulse_api.park_replay())["mode"] == "unavailable"
    assert run(parkpulse_api.park_replay_start(parkpulse_api.ReplayStartRequest()))["status"] == "unavailable"


def test_parkpulse_api_governance_responses_include_policy_contract(monkeypatch):
    state = sample_state()
    state["guestFlow"]["activeScenario"] = {"key": "ride_down", "name": "Ride Down"}
    state["guestFlow"]["rides"] = [{"name": "Dragon Coaster", "status": "down"}]
    state["guestFlow"]["zones"] = [{"id": "coaster-plaza", "density": 72}]

    class FakeParkSimulation:
        async def get_state(self):
            return copy.deepcopy(state)

        async def execute_action(self, target, action):
            return {"status": "success", "message": f"{target}/{action} executed"}

    async def sync_noop(_state):
        return None

    async def fake_gemini_plan(*args, **kwargs):
        return {
            "runtime": "test",
            "recommended_action": "Reroute queue",
            "selected_action": {"target": "ride", "action": "reroute", "label": "Reroute queue"},
            "candidate_actions": [],
            "confidence_score": 0.9,
            "guest_message": "",
        }

    selected_action = {"target": "ride", "action": "reroute", "label": "Reroute queue"}
    monkeypatch.setattr(parkpulse_api, "park_simulation", FakeParkSimulation(), raising=False)
    monkeypatch.setattr(parkpulse_api, "sync_park_state_safe", sync_noop)
    monkeypatch.setattr(parkpulse_api, "clear_hot_endpoint_cache", lambda: None)
    monkeypatch.setattr(parkpulse_api, "retrieve_operational_context", lambda *args, **kwargs: {"status": {"mode": "test", "connected": False}, "retrieved": {"playbooks": [], "incidents": [], "learnings": []}})
    monkeypatch.setattr(parkpulse_api, "build_park_gemini_plan", fake_gemini_plan)
    monkeypatch.setattr(parkpulse_api, "optimize_park_response", lambda *args, **kwargs: {"selected_plan": {"selected_action": selected_action, "action_mix": []}, "candidates": []})
    monkeypatch.setattr(parkpulse_api, "build_digital_twin_tool_trace", lambda *args, **kwargs: {"tool_count": 0, "summary": {}})
    monkeypatch.setattr(parkpulse_api, "record_mongo_agent_decision", lambda *args, **kwargs: "decision-contract")
    monkeypatch.setattr(parkpulse_api, "build_delivery_plan", lambda *args, **kwargs: [{"id": "dispatch-contract"}])
    monkeypatch.setattr(parkpulse_api, "response_summary", lambda dispatches: {"total": len(dispatches), "takeRate": 1, "positiveResponseRate": 1, "reactiveFollowThroughRate": 1})
    monkeypatch.setattr(parkpulse_api, "revise_plan_after_response", lambda *args, **kwargs: None)
    monkeypatch.setattr(parkpulse_api, "evaluate_park_decision", lambda *args, **kwargs: {"evals": [{"label": "Safety", "score": 95}, {"label": "Capacity", "score": 95}]})
    monkeypatch.setattr(parkpulse_api, "build_reactive_agent_findings", lambda *args, **kwargs: [])
    monkeypatch.setattr(parkpulse_api, "build_orchestration_run", lambda *args, **kwargs: {})
    monkeypatch.setattr(parkpulse_api, "build_reactive_outcome", lambda *args, **kwargs: {})
    monkeypatch.setattr(parkpulse_api, "record_mongo_outcome_event", lambda *args, **kwargs: "outcome-contract")
    monkeypatch.setattr(parkpulse_api, "build_analytics_rows", lambda *args, **kwargs: [])
    monkeypatch.setattr(parkpulse_api, "_export_agent_analytics", lambda rows: {"status": "skipped"})

    action_response = run(parkpulse_api.execute_park_action(parkpulse_api.ActionRequest(target="ride", action="reroute")))
    agent_response = run(parkpulse_api.park_agent_run(parkpulse_api.ParkAgentRunRequest(execute=True)))

    assert action_response["governance"]["policy_contract"]["status"] == "clean"
    assert agent_response["governance"]["policy_contract"]["status"] == "clean"
    assert "PARK-SAFE-001" in action_response["governance"]["policy_contract"]["expected_policy_refs"]
    assert "PARK-SAFE-001" in agent_response["governance"]["policy_contract"]["expected_policy_refs"]


def test_parkpulse_proactive_learned_run_and_autodream_cli(monkeypatch, capsys):
    install_api_fakes(monkeypatch)
    monkeypatch.setattr(
        parkpulse_api,
        "build_bigquery_agent_priors",
        lambda scenario_key, dashboard: {
            "status": "ready",
            "query_name": "agent_action_priors_by_scenario",
            "best_prior": {
                "cohort": "show_arcade",
                "prior_take_rate": 0.69,
                "prior_follow_through": 0.62,
                "recommended_adjustment": "Bonus points",
            },
            "weakest_prior": {"cohort": "broad_food", "prior_take_rate": 0.22, "prior_follow_through": 0.18},
            "route_mix": [
                {"destinationId": "theaterB", "destination": "Theater B", "share": 0.35, "currentWaitMins": 10},
                {"destinationId": "arcadeZone", "destination": "Arcade Zone", "share": 0.25, "currentWaitMins": 8},
            ],
            "priors": [],
        },
    )
    learned = run(parkpulse_api.park_proactive_learned_run())
    assert learned["status"] == "complete"
    assert learned["learned_run"]["source"] == "/api/park/proactive-learned-run"
    assert learned["learning_proof"]["mode"] == "learned_second_action"

    monkeypatch.setattr(mongo_memory, "init_operational_memory", lambda: {"status": "ok"})
    monkeypatch.setattr(park_autodream_agent, "run_autodream", lambda scenario, max_cases, persist: {"scenario_key": scenario, "dream_run_id": "dream-run-1", "summary": {"learnings_generated": 1, "prior_source": "unit"}, "persisted": persist, "max_cases": max_cases})
    monkeypatch.setattr(park_autodream_agent, "autodream_status", lambda limit: {"summary": {"pending_review": 1, "promoted": 0, "rejected": 0}, "limit": limit})
    monkeypatch.setattr(sys, "argv", ["run_autodream.py", "--scenario", "ride_down", "--scenario", "ride_down", "--max-cases", "2"])
    assert run_autodream.main() == 0
    assert "AutoDream complete" in capsys.readouterr().out

    monkeypatch.setattr(park_autodream_agent, "run_autodream", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(sys, "argv", ["run_autodream.py", "--all-scenarios", "--preview", "--json"])
    assert run_autodream.main() == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "partial_error"


def test_parkpulse_api_and_memory_last_branch_paths(monkeypatch):
    install_api_fakes(monkeypatch)
    parkpulse_api.clear_hot_endpoint_cache()
    monkeypatch.delenv("PARKPULSE_ALLOWED_ORIGINS", raising=False)
    assert "http://localhost:3000" in parkpulse_api._allowed_origins()

    class FakeTrackedTask:
        def __init__(self):
            self.callbacks = []
            self.cancelled = False

        def add_done_callback(self, callback):
            self.callbacks.append(callback)

        def cancel(self):
            self.cancelled = True

    real_create_task = parkpulse_api.asyncio.create_task
    fake_task = FakeTrackedTask()
    monkeypatch.setattr(parkpulse_api.asyncio, "create_task", lambda coro: fake_task)
    unused_coro = asyncio.sleep(0)
    tracked = parkpulse_api._track_background_task(unused_coro)
    unused_coro.close()
    assert tracked.callbacks
    parkpulse_api._background_tasks.clear()
    monkeypatch.setattr(parkpulse_api.asyncio, "create_task", real_create_task)

    async def fake_startup():
        parkpulse_api._background_tasks.add(real_create_task(asyncio.sleep(10)))

    monkeypatch.setattr(parkpulse_api, "startup_event", fake_startup)

    async def exercise_lifespan():
        manager = parkpulse_api.lifespan(parkpulse_api.app)
        await manager.__aenter__()
        await manager.__aexit__(None, None, None)

    run(exercise_lifespan())

    async def cache_builder():
        return {"fresh": True}

    lock = parkpulse_api._hot_endpoint_cache_locks.setdefault("double", asyncio.Lock())

    async def cache_inside_lock():
        async with lock:
            parkpulse_api._hot_endpoint_cache["double"] = (asyncio.get_running_loop().time() + 10, {"from_lock": True})
        return await parkpulse_api.cached_hot_endpoint("double", 10, cache_builder)

    assert run(cache_inside_lock()) == {"from_lock": True}
    run(parkpulse_api._memory_sync_lock.acquire())
    try:
        parkpulse_api._last_memory_sync_at = 0.0
        assert run(parkpulse_api.sync_park_state_safe({"guestFlow": {}}))["reason"] == "sync_in_progress"
    finally:
        parkpulse_api._memory_sync_lock.release()

    assert parkpulse_api._event_eval_for_memory({"quality": {"arize_eval": {"equipment_feasibility": 81, "guest_experience": 82, "staff_feasibility": 83, "constraint_following": 84}, "status": "ok"}})["energy_score"] == 81

    signal = {
        "id": "signal-tail",
        "categories": [],
        "risk_level": "LOW",
        "recommended_actions": [],
        "dispatch_payloads": [
            {"channel": "guest_app", "payload": {"message": "go"}},
            {"channel": "worker_device", "payload": {"task": "go"}},
            {"channel": "equipment_controller", "payload": {"command": "hold"}},
        ],
    }
    monkeypatch.setattr(parkpulse_api, "record_mongo_raw_signal", lambda payload: "signal-memory-tail")
    executed_signal = parkpulse_api._action_execution_for_signal(signal, sample_state())
    assert executed_signal["delivery"]["summary"]["total"] == 3

    candidate = {
        "status": "ready",
        "selected_action": {"park_action": {"target": "ride", "action": "reroute"}},
        "finding": {"id": "finding-tail"},
    }
    monkeypatch.setattr(parkpulse_api, "build_audit_snapshot", lambda state: {"summary": {}, "anomalies": []})
    monkeypatch.setattr(parkpulse_api, "build_audit_action_candidate", lambda audit, state: candidate)
    monkeypatch.setattr(parkpulse_api, "record_audit_response", lambda *args: {"ok": True})
    audit_allowed = run(parkpulse_api.run_park_audit_response(parkpulse_api.AuditRunResponseRequest(execute=True)))
    assert audit_allowed["status"] == "success"

    monkeypatch.setattr(
        parkpulse_api,
        "build_park_gemini_plan",
        lambda state, scenario_key, context, **_kwargs: asyncio.sleep(0, result={"runtime": "test", "recommended_action": "No op", "candidate_actions": [], "selected_action": {}}),
    )
    monkeypatch.setattr(parkpulse_api.park_simulation, "inject_random_unexpected_event", lambda source: asyncio.sleep(0, result={"source": source}), raising=False)
    monkeypatch.setattr(parkpulse_api, "optimize_park_response", lambda state, scenario_key, context, plan: {"selected_plan": {}})
    no_action = run(parkpulse_api.park_agent_run(parkpulse_api.ParkAgentRunRequest(operation_mode=True, auto_unexpected_event=True)))
    assert no_action["execution"]["status"] == "noop"

    monkeypatch.setattr(parkpulse_api, "init_audit_store", lambda: (_ for _ in ()).throw(RuntimeError("audit offline")))
    monkeypatch.setattr(parkpulse_api, "backup_replay_store", lambda: (_ for _ in ()).throw(RuntimeError("backup offline")))
    monkeypatch.setattr(parkpulse_api, "_track_background_task", lambda coro: coro.close() if hasattr(coro, "close") else None)
    run(parkpulse_api.startup_event())

    memory = OperationalMemory()
    memory.initialize()
    monkeypatch.setattr(mongo_memory, "_memory", memory)
    assert mongo_memory.record_raw_signal({"source": "tail", "text": "x"}).startswith("signal_")
    stored = memory.record_dream_run({"dream_run_id": "dream-wrapper"}, [{"id": "dream-wrapper-learning", "lesson": "L", "rule": "R"}])
    assert mongo_memory.review_dream_learning(stored["dream_learning_ids"][0], "archived")["status"] == "archived"


def test_parkpulse_api_new_operator_stream_and_benchmark_paths(monkeypatch):
    install_api_fakes(monkeypatch)
    monkeypatch.setenv("PARKPULSE_LIVE_BIGQUERY", "true")
    monkeypatch.setattr(parkpulse_api, "export_analytics_rows", lambda rows: {"status": "exported", "row_counts": {key: len(value) for key, value in rows.items()}})
    assert parkpulse_api._live_bigquery_enabled() is True
    assert parkpulse_api._export_agent_analytics({"x": [{"id": 1}]})["status"] == "exported"

    def old_priors_signature(scenario_key, dashboard):
        return {"status": "old", "scenario_key": scenario_key}

    def type_error_priors(scenario_key, dashboard, allow_live_query=False):
        raise TypeError("allow_live_query")

    monkeypatch.setattr(parkpulse_api, "build_bigquery_agent_priors", type_error_priors)
    monkeypatch.setattr(parkpulse_api, "build_bigquery_agent_priors", old_priors_signature)
    assert parkpulse_api._build_agent_bigquery_priors("ride_down", {})["status"] == "old"

    assert parkpulse_api._infer_operator_command_route("Plan event halloween parade")["route"] == "event_plan"
    assert parkpulse_api._infer_operator_command_route("Staff note says lost child needs medical help")["requires_human_review"] is True
    assert parkpulse_api._infer_operator_command_route("coaster is down and queue blocked")["scenario_key"] == "ride_down"
    assert parkpulse_api._summarize_dispatch_payload({"payload": {"targetMix": [1]}}) == "custom target mix for guest route distribution"
    assert "zone command" in parkpulse_api._summarize_dispatch_payload({"payload": {"zones": ["a", "b"]}})
    assert parkpulse_api._candidate_rejection({"rejected_reasons": ["too much", "too late", "extra"]}) == "too much / too late"
    assert "tradeoff score" in parkpulse_api._candidate_rejection({"scorecard": {"overcorrection_risk": 4}})
    trace_contract = parkpulse_api.build_run_trace_contract(
        run_id="run-1",
        source="unit",
        scenario_key="ride_down",
        selected_action={"id": "chosen", "label": "Chosen"},
        candidates=[{"id": "chosen", "selected_action": {"label": "Chosen"}}, {"id": "other", "scorecard": {"staff_burden": 5}}],
        policy_gate={"gate_status": "clear", "findings": ["ok"], "policy_refs": ["PARK-SAFE-001"]},
        dispatches=[{"id": "d1", "channel": "guest_app", "status": "sent", "payload": {"message": "go"}, "response": {"acknowledgedCount": 1}}],
        response_metrics={"takeRate": 0.5},
        outcome_id="outcome-1",
        outcome={"learning": {"take_rate_signal": "good"}},
        eval_result={"overall": 90},
        memory={"connected": False, "mode": "demo", "retrieved_learnings": ["learn"]},
    )
    assert trace_contract["candidate_actions"][0]["status"] == "selected"
    fallback_trace = parkpulse_api.build_run_trace_contract(
        run_id="run-2",
        source="unit",
        scenario_key="ride_down",
        selected_action={"action": "reroute"},
        candidates=[],
        policy_gate={},
        dispatches=[],
        response_metrics={},
        outcome_id=None,
        outcome=None,
        eval_result={},
        memory={},
    )
    assert fallback_trace["candidate_actions"][0]["id"] == "selected-action"

    async def fake_event_plan(request):
        return {"plan": {"operator_summary": "event ok"}}

    async def fake_signal_intake(request):
        return {"signal": {"triage_explanation": "triage ok"}}

    async def fake_agent_run(request):
        return {"planner": {"selected_action": {"label": "reroute"}}, "delivery": {"response": {"takeRate": 0.5}}}

    monkeypatch.setattr(parkpulse_api, "plan_park_event", fake_event_plan)
    monkeypatch.setattr(parkpulse_api, "park_signal_intake", fake_signal_intake)
    monkeypatch.setattr(parkpulse_api, "park_agent_run", fake_agent_run)
    assert run(parkpulse_api.park_operator_command(parkpulse_api.OperatorCommandRequest(message="plan event halloween")))["mode"] == "event_plan"
    assert run(parkpulse_api.park_operator_command(parkpulse_api.OperatorCommandRequest(message="staff note guest says confused near gate")))["mode"] == "signal_triage"
    assert run(parkpulse_api.park_operator_command(parkpulse_api.OperatorCommandRequest(message="coaster is down")))["mode"] == "operations"

    async def fake_stream_payload(emit_trace=None):
        if emit_trace:
            await emit_trace({"phase": "phase_1", "message": "done"})
        return {"trace_contract": {"run_id": "trace-1", "source": "unit"}, "decision_id": "decision-1"}

    monkeypatch.setattr(parkpulse_api, "_build_proactive_run_payload", fake_stream_payload)

    async def collect_stream():
        response = await parkpulse_api.park_proactive_run_stream()
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
        return "".join(chunks)

    stream_body = run(collect_stream())
    assert "run.started" in stream_body
    assert "phase_1.done" in stream_body
    assert "run.complete" in stream_body

    monkeypatch.setattr(parkpulse_api, "run_autodream_benchmark", lambda state, scenario_key=None, promoted_rule_id=None, seeds=5: {"status": "complete", "scenario_key": scenario_key, "promoted_rule": {"_id": "rule-1"}, "sample_size": seeds})
    monkeypatch.setattr(parkpulse_api, "record_mongo_autodream_benchmark", lambda benchmark: {"status": "stored", "benchmark_id": "bench-1"})
    benchmark = run(parkpulse_api.park_autodream_benchmark(parkpulse_api.AutoDreamBenchmarkRequest(scenario_key="ride_down", seeds=2)))
    assert benchmark["storage"]["benchmark_id"] == "bench-1"
    monkeypatch.setattr(parkpulse_api, "get_latest_memory_documents", lambda collection, limit: [{"_id": "bench-1"}])
    assert run(parkpulse_api.park_autodream_benchmarks(50))["count"] == 1


def test_operational_memory_fallback_dashboard_and_learning(monkeypatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    memory = OperationalMemory()
    assert memory.initialize()["mode"] == "demo_fallback"
    state = sample_state()
    stored = memory.upsert_park_state(state)
    assert stored["collection"] == "park_state"

    context = memory.retrieve_context("ride down staff food", state, limit=2)
    assert context["retrieved"]["playbooks"]
    decision = memory.record_agent_decision(
        {
            "recommended_action": "Split queue",
            "selected_action": {"target": "ride", "action": "reroute"},
            "candidate_actions": [{"label": "A"}],
            "confidence_score": 80,
            "root_cause_classification": "operator_action",
            "guest_message": "Use lower wait rides.",
        },
        {"energy_score": 85, "comfort_score": 86, "worker_stress_score": 87, "safety_score": 100, "reasoning": "ok"},
        state,
        context,
        source="test",
    )
    assert decision.startswith("decision_")
    skipped = memory.record_agent_decision({}, {}, state, context)
    assert skipped.startswith("skipped_")

    outcome = {
        "loop_id": "loop-1",
        "mode": "reactive_closed_loop",
        "phases": [],
        "response_metrics": {"takeRate": 0.2, "positiveResponseRate": 0.7, "reactiveFollowThroughRate": 0.2},
        "state_impact": {"density_delta": 2, "congestion_delta": 1, "comfort_delta": 0, "queued_guest_delta": -10},
        "scorecard": {"overall": 62},
        "learning": {"take_rate_signal": "weak"},
    }
    outcome_id = memory.record_outcome_event(outcome, decision, state)
    assert outcome_id.startswith("outcome_")
    positive = copy.deepcopy(outcome)
    positive["loop_id"] = "loop-2"
    positive["response_metrics"]["takeRate"] = 0.5
    positive["response_metrics"]["reactiveFollowThroughRate"] = 0.48
    positive["state_impact"].update({"density_delta": -6, "comfort_delta": 5, "queued_guest_delta": -150})
    memory.record_outcome_event(positive, decision, state)
    limited = copy.deepcopy(outcome)
    limited["loop_id"] = "loop-3"
    limited["response_metrics"]["takeRate"] = 0.45
    limited["response_metrics"]["reactiveFollowThroughRate"] = 0.42
    limited["scorecard"]["overall"] = 80
    memory.record_outcome_event(limited, decision, state)

    event_plan = park_event_planner._fallback_plan(state, "Plan", "test")
    event_plan["quality"] = park_event_planner._score_plan(event_plan, state)
    assert memory.record_event_plan(event_plan, decision, state, context).startswith("event_plan_")
    dashboard = memory.dashboard("ride down")
    assert dashboard["latest_decisions"]
    assert dashboard["latest_event_plans"]
    assert dashboard["latest_learnings"]
    assert memory.collection_summary()
    assert memory.latest_documents("outcome_events", 1)

    monkeypatch.setenv("MONGODB_DISABLE_DECISION_WRITES", "true")
    disabled = OperationalMemory()
    disabled.initialize()
    assert disabled.record_agent_decision({"recommended_action": "x"}, {"safety_score": 100}, state, context).startswith("skipped_")

    assert mongo_memory._clean_for_bson({"x": object()})["x"].startswith("<")
    assert len(mongo_memory._vectorize("ride ride food", dimensions=8)) == 8
    assert mongo_memory._keyword_score({"summary": "ride food", "tags": []}, "ride staff") > 0
    assert mongo_memory._average_eval_score({"energy_score": "bad", "comfort_score": 80, "worker_stress_score": 90, "safety_score": 100}) == 68


def test_park_gemini_agent_success_error_enterprise_and_helpers(monkeypatch):
    state = sample_state()
    context = sample_context()
    assert park_gemini_agent._compact_state(state)["guestFlow"]["rides"]
    assert park_gemini_agent._compact_context(context)["learnings"][0]["_id"] == "learn_low_take"
    assert park_gemini_agent._first_json_object("") is None
    assert park_gemini_agent._first_json_object("prefix {\"x\": 1} suffix") == {"x": 1}
    assert park_gemini_agent._first_json_object("prefix {bad} suffix") is None
    assert park_gemini_agent._first_json_object("bad") is None
    normalized = park_gemini_agent._normalize_candidate(
        {"park_action": {"target": "bad", "action": "bad"}, "estimated_score": 0},
        {"target": "staff", "action": "redeploy", "label": "Fallback"},
    )
    assert normalized["target"] == "staff"

    raw = {
        "analysis": "Ride queue is overloaded.",
        "root_cause_classification": "ride_down",
        "recommended_action": "Reroute guests.",
        "guest_message": "Use nearby attractions.",
        "confidence_score": 91,
        "candidate_actions": [{"target": "food", "action": "suppress_item", "label": "Food", "owner": "Ops", "expected_effect": "reduce food pressure", "estimated_score": 80}],
        "custom_action_mixes": [{"name": "Mix", "target_mix": []}],
        "selected_action": {"target": "food", "action": "suppress_item", "label": "Food", "owner": "Ops", "expected_effect": "reduce food pressure", "estimated_score": 80},
        "tradeoffs": {"guest": "balanced"},
    }
    normalized_plan = park_gemini_agent._normalize_gemini_plan(raw, state, "gemini_api", "ride_down", context)
    aligned = park_gemini_agent._align_selected_action_to_scenario(normalized_plan, state, "ride_down")
    aligned = park_gemini_agent._apply_answer_accuracy_controls(aligned, state, "ride_down", context, raw)
    assert aligned["selected_action"]["action"] == "reroute"
    assert aligned["answer_accuracy"]["status"] == "verified"
    assert "validate_policy" in {item["tool"] for item in aligned["tool_use_plan"]}
    assert aligned["evidence_citations"]
    assert park_gemini_agent._align_selected_action_to_scenario(aligned, state, "unknown") is aligned
    assert "ParkPulse AI" in park_gemini_agent._prompt(state, "ride_down", context)
    assert "tool_use_contract" in park_gemini_agent._prompt(state, "ride_down", context)
    weak_raw = {
        "analysis": "Looks fine.",
        "root_cause_classification": "ride_down",
        "recommended_action": "Do something.",
        "guest_message": "We are helping.",
        "confidence_score": 97,
        "candidate_actions": [{"target": "ride", "action": "reroute", "label": "Route", "owner": "Ops", "expected_effect": "Help", "estimated_score": 97}],
        "selected_action": {"target": "ride", "action": "reroute", "label": "Route", "owner": "Ops", "expected_effect": "Help", "estimated_score": 97},
        "tradeoffs": {},
    }
    weak_plan = park_gemini_agent._normalize_gemini_plan(weak_raw, {"guestFlow": {"activeScenario": {"key": "ride_down"}, "rides": []}}, "gemini_api", "ride_down", {})
    assert weak_plan["answer_accuracy"]["status"] == "needs_evidence"
    assert weak_plan["confidence_score"] < 97

    fake_client = FakeClient(json.dumps(raw))
    install_fake_genai_types(monkeypatch)
    monkeypatch.setattr(park_gemini_agent, "get_gemini_agent_properties", ready_props)
    monkeypatch.setattr(park_gemini_agent, "get_gemini_client", lambda: fake_client)
    monkeypatch.setattr(park_gemini_agent, "get_gemini_model", lambda: "gemini-test")
    monkeypatch.setenv("PARKPULSE_GEMINI_TIMEOUT_SECONDS", "7")
    plan = run(park_gemini_agent.build_park_gemini_plan(state, "ride_down", context))
    assert plan["runtime"] == "gemini_api"
    assert fake_client.models.calls
    config = fake_client.models.calls[0]["config"].kwargs
    assert config["max_output_tokens"] == 5000
    assert config["thinking_config"].kwargs["thinking_budget"] == 0
    assert plan["timeout_seconds"] == 7.0
    assert "ParkAgentResponse" in park_gemini_agent._prompt(state, "ride_down", context)
    assert "model_json_schema" not in park_gemini_agent._prompt(state, "ride_down", context)
    assert plan["answer_accuracy"]["status"] == "verified"
    assert plan["tool_use_plan"]

    reaction_raw = {
        "operator_understanding": {
            "intent_summary": "Move families away from Coaster Plaza while protecting staff breaks.",
            "inferred_incident_type": "ride_down",
            "hard_constraints": ["Do not reopen Dragon Coaster without clearance."],
            "soft_preferences": ["Use family-friendly alternates."],
            "avoid_zones": [],
            "preferred_destinations": [],
            "required_staff_moves": [],
            "equipment_controls": [],
            "guest_segments": ["families near Coaster Plaza"],
            "rejected_option": "Do not send guests to another overloaded queue.",
            "missing_facts": [],
        },
        "analysis": "Dragon Coaster is down and Coaster Plaza should shed demand.",
        "root_cause_classification": "ride_down",
        "selected_action": {"target": "ride", "action": "reroute", "label": "Family-safe reroute", "owner": "Decision Bridge", "expected_effect": "Move families away from Coaster Plaza.", "estimated_score": 86},
        "candidate_actions": [{"target": "ride", "action": "reroute", "label": "Family-safe reroute", "owner": "Decision Bridge", "expected_effect": "Move families away from Coaster Plaza.", "estimated_score": 86}],
        "custom_action_mix": {
            "name": "Family-safe coaster relief",
            "strategy": "Move a bounded share to low-wait family alternates.",
            "guest_reroute_enabled": True,
            "target_mix": [{"destination_id": "skyDrop", "destination": "Sky Drop", "share": 0.25, "rationale": "Lower wait nearby."}],
            "hold_share": 0.3,
            "promotion_strength": "medium",
            "offer": "Bonus points for a family alternate.",
            "staff_moves": [],
            "suppress_items": [],
            "promote_items": [],
            "guest_messages": [],
            "signage_updates": [],
            "queue_gate_controls": [],
            "rationale": "Bounded reroute preserves staff coverage.",
        },
        "guest_message": "Dragon Coaster is temporarily unavailable; use nearby family alternates.",
        "confidence_score": 84,
        "tradeoffs": {"guest": "Specific reroute without unsafe reopening."},
    }
    context["operator_request"] = "Dragon Coaster is down, move families away from Coaster Plaza."
    context["operator_mode"] = "operator_command"
    context["operator_route"] = {"route": "operations", "scenario_key": "ride_down"}
    reaction_calls = []

    async def fake_reaction_json(prompt, **kwargs):
        reaction_calls.append({"prompt": prompt, **kwargs})
        return {"text": json.dumps(reaction_raw)}

    monkeypatch.setattr(park_gemini_agent, "generate_gemini_json_hard_timeout", fake_reaction_json)
    monkeypatch.setenv("PARKPULSE_GEMINI_REACTION_TIMEOUT_SECONDS", "5")
    reaction = run(park_gemini_agent.build_park_gemini_reaction_plan(state, "ride_down", context))
    assert reaction["runtime"] == "gemini_api_fast_reaction"
    assert reaction["workflow"] == "react_first_operator_command"
    assert reaction["custom_action_mixes"][0]["name"] == "Family-safe coaster relief"
    assert reaction["answer_accuracy"]["status"] == "verified"
    assert reaction["tool_use_plan"]
    assert reaction_calls[0]["prompt"]["response_schema"] is park_gemini_agent.FAST_REACTION_RESPONSE_SCHEMA
    assert reaction_calls[0]["max_output_tokens"] == 1800
    assert reaction_calls[0]["timeout_seconds"] == 5.0
    assert reaction["timeout_seconds"] == 5.0

    monkeypatch.setenv("PARKPULSE_GEMINI_TIMEOUT_SECONDS", "bad")
    monkeypatch.setattr(park_gemini_agent, "get_gemini_client", lambda: FakeClient(error=RuntimeError("gemini down")))
    errored = run(park_gemini_agent.build_park_gemini_plan(state, "ride_down", context))
    assert errored["runtime"] == "deterministic_fallback_after_gemini_error"

    from gemini_provider import GeminiAgentProperties

    enterprise = GeminiAgentProperties(**{**ready_props().__dict__, "platform": "gemini_enterprise", "provider": "Gemini Enterprise API", "use_gemini_enterprise": True, "has_project": True, "has_location": True, "enterprise_engine_id": "engine", "enterprise_assistant_id": "assistant", "has_application_credentials_env": True})
    monkeypatch.setattr(park_gemini_agent, "get_gemini_agent_properties", lambda: enterprise)
    import gemini_enterprise_client

    monkeypatch.setattr(gemini_enterprise_client, "stream_assist", lambda *args: {"text": json.dumps(raw), "assistant_name": "assistant", "raw_chunk_count": 2})
    enterprise_plan = run(park_gemini_agent.build_park_gemini_plan(state, "food_spike", context))
    assert enterprise_plan["runtime"] == "gemini_enterprise"


class FakeCursor(list):
    def sort(self, *args, **kwargs):
        return self

    def limit(self, limit):
        return FakeCursor(self[:limit])


class FakeCollection:
    def __init__(self, rows=None, aggregate_error=False, find_error=False):
        self.rows = FakeCursor(rows or [])
        self.aggregate_error = aggregate_error
        self.find_error = find_error
        self.writes = []
        self.indexes = []

    def create_index(self, spec, *args, **kwargs):
        self.indexes.append((spec, args, kwargs))

    def update_one(self, *args, **kwargs):
        self.writes.append(("update_one", args, kwargs))
        if len(args) >= 2 and isinstance(args[0], dict) and isinstance(args[1], dict):
            row_id = args[0].get("_id")
            update = args[1].get("$set", {})
            for row in self.rows:
                if row.get("_id") == row_id and isinstance(update, dict):
                    row.update(update)

    def replace_one(self, *args, **kwargs):
        self.writes.append(("replace_one", args, kwargs))

    def bulk_write(self, ops):
        self.writes.append(("bulk_write", ops))

    def aggregate(self, pipeline):
        if self.aggregate_error:
            raise RuntimeError("aggregate failed")
        return FakeCursor(self.rows)

    def find(self, *args, **kwargs):
        if self.find_error:
            raise RuntimeError("find failed")
        return FakeCursor(self.rows)

    def find_one(self, *args, **kwargs):
        return self.rows[0] if self.rows else None

    def estimated_document_count(self):
        return len(self.rows)


class FakeDb:
    def __init__(self):
        self.park_state = FakeCollection([{"_id": "live", "createdAt": "1", "embedding": [1], "embeddingText": "x"}])
        self.rides = FakeCollection()
        self.staff_shifts = FakeCollection()
        self.food_inventory = FakeCollection()
        self.playbooks = FakeCollection([{"_id": "pb", "title": "Ride", "createdAt": "1"}])
        self.incidents = FakeCollection([{"_id": "inc", "summary": "Incident", "createdAt": "1"}])
        self.agent_learnings = FakeCollection([{"_id": "learn", "scenarioKey": "ride_down", "createdAt": "1", "updatedAt": "2"}])
        self.agent_decisions = FakeCollection()
        self.eval_results = FakeCollection()
        self.guest_messages = FakeCollection()
        self.event_plans = FakeCollection()
        self.raw_signals = FakeCollection()
        self.outcome_events = FakeCollection()
        self.dream_runs = FakeCollection()
        self.dream_learnings = FakeCollection()
        self.autodream_benchmarks = FakeCollection()
        self.scenario_memory_index = FakeCollection()

    def __getitem__(self, name):
        if not hasattr(self, name):
            setattr(self, name, FakeCollection())
        return getattr(self, name)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        collection = FakeCollection()
        setattr(self, name, collection)
        return collection


class FakeMongoClient:
    def __init__(self, uri, serverSelectionTimeoutMS=2500):
        self.uri = uri
        self.admin = SimpleNamespace(command=lambda name: {"ok": 1})
        self.db = FakeDb()

    def __getitem__(self, name):
        return self.db


class FakeUpdateOne:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


def test_operational_memory_connected_branches_and_wrappers(monkeypatch):
    monkeypatch.setenv("MONGODB_URI", "mongodb://example")
    monkeypatch.setenv("MONGODB_MIN_USEFUL_EVAL_SCORE", "bad")
    monkeypatch.setattr(mongo_memory, "MongoClient", FakeMongoClient)
    monkeypatch.setattr(mongo_memory, "UpdateOne", FakeUpdateOne)
    monkeypatch.setattr(mongo_memory, "ASCENDING", 1)
    monkeypatch.setattr(mongo_memory, "DESCENDING", -1)
    monkeypatch.setattr(mongo_memory, "TEXT", "text")

    memory = OperationalMemory()
    status = memory.initialize()
    assert status["mode"] == "mongodb"
    assert memory.min_eval_score == 75
    state = sample_state()
    assert memory.upsert_park_state(state)["mode"] == "mongodb"
    context = memory.retrieve_context("ride_down", state, limit=1)
    assert context["retrieved"]["method"] == "mongodb_vector_search"

    memory.db.playbooks.aggregate_error = True
    assert memory._retrieve_playbooks("ride", 1)[1] == "mongodb_text_search"
    memory.db.playbooks.find_error = True
    assert memory._retrieve_playbooks("ride", 1)[1] == "keyword_similarity"
    memory._fallback["incidents"] = [{"_id": "fallback_inc", "summary": "ride incident", "tags": ["ride"]}]
    memory.db.incidents.find_error = True
    assert memory._retrieve_incidents("ride", 1)
    memory.db.agent_learnings.find_error = True
    assert memory._retrieve_learnings("ride_down", 1)
    memory.db.agent_learnings.aggregate_error = True
    with pytest.raises(RuntimeError):
        memory._retrieve_learnings("ride_down", 1)
    memory.db.agent_learnings.find_error = False
    memory.db.agent_learnings.aggregate_error = False
    assert memory.latest_park_state()["_id"] == "live"

    decision = memory.record_agent_decision(
        {"recommended_action": "x", "selected_action": {"target": "ride", "action": "reroute"}},
        {"energy_score": 80, "comfort_score": 80, "worker_stress_score": 80, "safety_score": 100},
        state,
        context,
    )
    outcome = {"loop_id": "db-loop", "response_metrics": {"takeRate": 0.5}, "state_impact": {}, "scorecard": {"overall": 80}, "learning": {}}
    assert memory.record_outcome_event(outcome, decision, state).startswith("outcome_")
    plan = park_event_planner._fallback_plan(state, "Plan", "test")
    plan["quality"] = {"overall": 85}
    assert memory.record_event_plan(plan, decision, state, context).startswith("event_plan_")
    assert memory.collection_summary()[0]["count"] >= 1
    assert memory.latest_documents("park_state", 1)[0]["_id"] == "live"

    monkeypatch.setattr(mongo_memory, "_memory", memory)
    assert mongo_memory.init_operational_memory()["mode"] == "mongodb"
    assert mongo_memory.sync_park_state(state)["collection"] == "park_state"
    assert mongo_memory.retrieve_operational_context("ride", state)["retrieved"]
    assert mongo_memory.record_agent_decision({"recommended_action": "x"}, {"safety_score": 100}, state).startswith("decision_")
    assert mongo_memory.record_event_plan(plan, decision, state).startswith("event_plan_")
    assert mongo_memory.record_outcome_event(outcome, decision, state).startswith("outcome_")
    assert mongo_memory.get_operational_memory_dashboard("ride")["status"]["mode"] == "mongodb"
    memory.db.playbooks.find_error = False
    memory.db.incidents.find_error = False
    repair = mongo_memory.backfill_memory_embeddings(["playbooks", "incidents", "agent_learnings"], 10)
    assert repair["status"] == "repaired"
    assert repair["collections"]["playbooks"]["updated"] >= 1


def test_mongo_memory_remaining_branch_paths(monkeypatch):
    assert isinstance(mongo_memory._clean_for_bson(("x", object())), list)
    assert mongo_memory._keyword_score({"summary": "tiny"}, "a an") == 0.0
    monkeypatch.setenv("MONGO_FLOAT_BAD", "bad")
    assert mongo_memory._float_env("MONGO_FLOAT_BAD", 1.25) == 1.25
    tags = mongo_memory._decision_quality_tags(
        {"selected_action": {"target": "ride"}, "candidate_actions": [{}], "root_cause_classification": "operator_action"},
        {"energy_score": 100, "comfort_score": 100, "worker_stress_score": 100, "safety_score": "bad"},
        sample_context(),
        75,
    )
    assert "policy_or_safety_review" in tags
    assert mongo_memory._should_store_decision("bad", {}, None, 75)[1] == "invalid_payload"
    assert mongo_memory._should_store_decision({}, {}, None, 75)[1] == "missing_recommendation"

    class BrokenMongoClient:
        def __init__(self, *args, **kwargs):
            self.admin = SimpleNamespace(command=lambda name: (_ for _ in ()).throw(RuntimeError("offline")))

    monkeypatch.setenv("MONGODB_URI", "mongodb://broken")
    monkeypatch.setattr(mongo_memory, "MongoClient", BrokenMongoClient)
    broken = OperationalMemory()
    assert broken.initialize()["mode"] == "demo_fallback"
    monkeypatch.setattr(mongo_memory, "MongoClient", None)
    missing_driver = OperationalMemory()
    assert missing_driver.initialize()["mode"] == "demo_fallback"

    fallback = OperationalMemory()
    fallback.initialize()
    assert fallback._ensure_indexes() is None
    assert fallback.record_raw_signal({"source": "s", "text": "hello", "zone": {"id": "z"}, "categories": ["crowd"], "risk_level": "LOW"}).startswith("signal_")
    assert fallback._record_learning_from_outcome({"responseMetrics": {}, "scorecard": {}}, {}) is None
    fallback.dashboard_cache_ttl_seconds = 10
    for index in range(18):
        fallback.dashboard(f"query-{index}")
    assert len(fallback._dashboard_cache) <= 16
    fallback._fallback["playbooks"].insert(0, {"_id": "empty_playbook"})
    repaired = fallback.backfill_embeddings(["playbooks"], 5)
    assert repaired["collections"]["playbooks"]["skipped"] >= 1
    dream_store = fallback.record_dream_run(
        {"dream_run_id": "dream-run-tail", "scenario_key": "ride_down", "status": "complete"},
        [{"id": "dream-learning-tail", "lesson": "Use split routing", "rule": "Split demand", "scenarioKey": "ride_down"}],
    )
    assert dream_store["status"] == "stored"
    dream_id = dream_store["dream_learning_ids"][0]
    assert fallback.promote_dream_learning("missing")["status"] == "not_found"
    promoted_playbook = fallback.promote_dream_learning(dream_id, target="playbooks", reviewer="qa")
    assert promoted_playbook["target"] == "playbooks"
    assert fallback.review_dream_learning(dream_id, "archived")["status"] == "already_promoted"
    dream_store_2 = fallback.record_dream_run(
        {"dream_run_id": "dream-run-tail-2", "scenario_key": "food_spike", "status": "complete"},
        [{"id": "dream-learning-tail-2", "lesson": "Suppress item", "rule": "Hide constrained stock", "scenarioKey": "food_spike"}],
    )
    dream_id_2 = dream_store_2["dream_learning_ids"][0]
    assert fallback.review_dream_learning("missing", "bad")["status"] == "not_found"
    assert fallback.review_dream_learning(dream_id_2, "needs_more_evidence", reviewer="qa", reason="thin")["status"] == "needs_more_evidence"

    monkeypatch.setenv("MONGODB_URI", "mongodb://example")
    monkeypatch.setattr(mongo_memory, "MongoClient", FakeMongoClient)
    monkeypatch.setattr(mongo_memory, "UpdateOne", FakeUpdateOne)
    monkeypatch.setattr(mongo_memory, "ASCENDING", 1)
    monkeypatch.setattr(mongo_memory, "DESCENDING", -1)
    monkeypatch.setattr(mongo_memory, "TEXT", "text")
    connected = OperationalMemory()
    connected.initialize()
    assert connected.record_raw_signal({"source": "s", "text": "hello", "zone": {"id": "z"}, "categories": ["crowd"], "risk_level": "LOW"}).startswith("signal_")
    connected.db.playbooks.rows.insert(0, {"_id": "empty"})
    connected.db.playbooks.find_error = True
    partial = connected.backfill_embeddings(["playbooks"], 2)
    assert partial["status"] == "partial_error"
    connected.db.playbooks.find_error = False
    connected.db.dream_learnings.rows.append({"_id": "dream-db", "scenarioKey": "ride_down", "lesson": "Lesson", "rule": "Rule", "tags": []})
    assert connected.promote_dream_learning("dream-db")["status"] == "promoted"
    connected.db.dream_learnings.rows = FakeCursor([{"_id": "dream-db-review", "scenarioKey": "ride_down", "lesson": "Lesson", "rule": "Rule", "tags": []}])
    assert connected.review_dream_learning("dream-db-review", "archived")["status"] == "archived"

    class FailingMemory:
        mode = "mongodb"
        errors = []
        connected = True
        db = object()
        client = object()

        def seed_defaults(self):
            self.seeded = True

    failing = FailingMemory()
    monkeypatch.setattr(mongo_memory, "_memory", failing)
    mongo_memory._degrade_memory(RuntimeError("down"))
    assert failing.mode == "demo_fallback_degraded"

    calls = {"count": 0}

    def operation_then_fallback():
        calls["count"] += 1
        raise RuntimeError("still down")

    result = mongo_memory._safe_memory_call("tail.memory", operation_then_fallback, lambda error: {"fallback": str(error)})
    assert result["fallback"] == "still down"


def test_memory_ops_agent_reports_depth_and_embedding_coverage(monkeypatch):
    monkeypatch.setenv("MONGODB_URI", "mongodb://example")
    monkeypatch.setattr(mongo_memory, "MongoClient", FakeMongoClient)
    monkeypatch.setattr(mongo_memory, "UpdateOne", FakeUpdateOne)
    monkeypatch.setattr(mongo_memory, "ASCENDING", 1)
    monkeypatch.setattr(mongo_memory, "DESCENDING", -1)
    monkeypatch.setattr(mongo_memory, "TEXT", "text")

    memory = OperationalMemory()
    memory.initialize()
    monkeypatch.setattr(mongo_memory, "_memory", memory)
    report = memory_ops_agent.build_memory_ops_report("ride_down")
    repair = memory_ops_agent.run_memory_ops_repair("ride_down", ["playbooks"], 10)

    assert report["agent_id"] == "memory_ops_agent"
    assert report["implemented"] is True
    assert report["summary"]["mongo_connected"] is True
    assert report["retrieval_depth"]["retrieval_method"] == "mongodb_vector_search"
    assert any(item["collection"] == "playbooks" for item in report["embedding_coverage"])
    assert report["future_mcp_fit"]
    assert repair["mode"] == "operator_triggered_repair"
    assert repair["repair"]["collections"]["playbooks"]["updated"] >= 1


def test_autodream_agent_generates_offline_review_learnings(monkeypatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    memory = OperationalMemory()
    memory.initialize()
    monkeypatch.setattr(mongo_memory, "_memory", memory)
    result = park_autodream_agent.run_autodream("ride_down", max_cases=2, persist=True)

    assert result["status"] == "complete"
    assert result["offline_only"] is True
    assert result["operator_review"]["required"] is True
    assert result["dream_learnings"]
    assert result["storage"]["status"] == "stored"
    assert memory.latest_documents("dream_runs", 1)[0]["offlineOnly"] is True
    assert memory.latest_documents("dream_learnings", 1)[0]["reviewStatus"] == "pending_operator_review"
    status = park_autodream_agent.autodream_status()
    dream_learning_id = status["latest_dream_learnings"][0]["_id"]
    promotion = park_autodream_agent.promote_autodream_learning(dream_learning_id, "agent_learnings", "test_operator")
    assert promotion["status"] == "promoted"
    assert memory.latest_documents("agent_learnings", 1)[0]["sourceDreamLearningId"] == dream_learning_id
    assert park_autodream_agent.autodream_status()["summary"]["promoted"] >= 1


def test_small_branch_coverage_for_actions_delivery_simulation_and_agents():
    state = sample_state()
    scopes = [
        park_action_result.build_park_action_result({"status": "success"}, "staff", "redeploy")["controlled_scope"],
        park_action_result.build_park_action_result({"status": "success"}, "food", "suppress_item")["controlled_scope"],
        park_action_result.build_park_action_result({"status": "success"}, "traffic", "redirect_food")["controlled_scope"],
        park_action_result.build_park_action_result({"status": "success"}, "energy", "protect_hvac")["controlled_scope"],
        park_action_result.build_park_action_result({"status": "success"}, "x", "y")["controlled_scope"],
    ]
    assert scopes[-1] == "operator-reviewed park operation"
    assert park_delivery._simulate_response("unknown", {}, "delivered")["state"] == "unknown"
    for scenario, selected in [
        ("staff_shortage", {"target": "staff", "action": "redeploy"}),
        ("food_spike", {"target": "food", "action": "suppress_item"}),
        ("storm_response", {"target": "energy", "action": "protect_hvac"}),
        ("unknown", {"target": "unknown", "action": "unknown", "label": "Manual"}),
    ]:
        assert park_delivery.build_delivery_plan(scenario, selected, state, "decision")

    rides = park_simulation._rides("ride_down", "normal")
    zones = park_simulation._zones("ride_down", "normal")
    interventions = [
        {"kind": "ride_failure", "targetId": "skyDrop", "intensity": 80},
        {"kind": "demand_spike", "targetId": "coasterPlaza", "intensity": 80},
        {"kind": "food_spike", "targetId": "foodCourt1", "intensity": 80},
        {"kind": "staff_callout", "targetId": "skyDrop", "intensity": 80},
        {"kind": "energy_spike", "targetId": "indoorHub", "intensity": 80},
    ]
    pressured_rides, pressured_zones = park_simulation._apply_interventions(rides, zones, interventions, "proactive_commit")
    assert any(ride["id"] == "skyDrop" and ride["status"] == "down" for ride in pressured_rides)
    assert park_simulation._intervention_alerts(interventions, pressured_rides, pressured_zones)
    assert park_simulation._zone_for_target("skyDrop", rides) == "coasterPlaza"
    assert park_multi_agent._urgency(50) == "ok"
    assert park_multi_agent._agent_id_from_name("finance cost review") == "finance_agent"
    assert park_multi_agent._agent_id_from_name("ride recovery") == "ride_ops_agent"


def test_arize_exporter_and_status_branches(monkeypatch):
    class NoFlushExporter:
        def __init__(self):
            self.shutdown_called = False

        def export(self, spans):
            return "exported"

        def shutdown(self):
            self.shutdown_called = True
            return "closed"

    class Span:
        def __init__(self, attrs):
            self.attributes = attrs

    status_all = arize_config.ArizeAxStatus("Arize AX", "p", "s", "e", True, True, True, "i", "all", False)
    assert arize_config._span_is_useful(Span({"parkpulse.telemetry.source": "background_loop"}), status_all) is True
    status = arize_config.ArizeAxStatus("Arize AX", "p", "s", "e", True, True, True, "i", "useful", False)
    assert arize_config._span_int_attr(Span({"bad": "x"}), "bad") == 0
    assert arize_config._span_is_useful(Span({"parkpulse.telemetry.source": "background_loop", "parkpulse.telemetry.keep": True}), status) is True

    exporter = NoFlushExporter()
    useful = arize_config.UsefulSpanExporter(exporter, status)
    assert useful.shutdown() == "closed"
    assert useful.force_flush() is True

    monkeypatch.setitem(__import__("sys").modules, "opentelemetry.sdk.trace.export", SimpleNamespace(SpanExportResult=SimpleNamespace(SUCCESS="success")))
    empty_result = useful.export([Span({"parkpulse.telemetry.source": "background_loop", "parkpulse.signal.new_count": 0})])
    assert empty_result == "success"

    monkeypatch.setitem(__import__("sys").modules, "opentelemetry.sdk.trace.export", SimpleNamespace())
    assert useful.export([Span({"parkpulse.telemetry.source": "background_loop", "parkpulse.signal.new_count": 0})]) is None


def test_optimizer_and_action_bridge_remaining_branches():
    empty_plan = park_action_bridge.build_park_action_plan({"guestFlow": {"activeScenario": {"key": "ride_down"}, "rides": [], "zones": []}})
    assert empty_plan["selected_action"]["title"].startswith("Pause")
    for scenario in ("staff_shortage", "food_spike", "storm_response"):
        plan = park_action_bridge.build_park_action_plan({"guestFlow": {"activeScenario": {"key": scenario}, "rides": [], "zones": []}})
        assert plan["scenario"]["key"] == scenario

    assert park_optimizer._learning_rules({"retrieved": {"learnings": ["bad", {"scenarioKey": "other"}]}}, "ride_down") == []
    assert park_optimizer._learning_summary([])["promotion_bias"] == "none"
    candidate = {"scorecard": {"overall": 80, "take_rate_likelihood": 50}, "action_mix": {"guest_reroute": {"promotionStrength": "low", "target_mix": [{"currentWaitMins": 60}]}, "staffing": {}, "facilities": {}}}
    adjusted = park_optimizer._apply_learning_to_candidates(
        [candidate],
        {"rules": [{"_id": "r"}], "promotion_bias": "increase", "require_equipment_or_staff_action": True, "take_rate_multiplier": 1.0},
    )[0]
    assert adjusted["learned_adjustments"]["penalty"] >= 6
    assert park_optimizer._apply_learning_to_candidates([], {"rules": [{"_id": "r"}]}) == []

    state = sample_state()
    flow = state["guestFlow"]
    failed = park_optimizer._primary_disrupted_ride(flow["rides"])
    destinations = park_optimizer._available_destinations(flow["rides"], failed["id"])
    failed_zone = park_optimizer._zone_by_id(flow["zones"])[failed["zone"]]
    base = {"food": {}, "facilities": {"hvac": {}}, "staffing": {}}
    custom = park_optimizer._candidate_from_custom_mix(
        {
            "target_mix": ["bad", {"destination": "Manual Zone", "share": 0.4, "zoneId": "manual"}],
            "staff_moves": ["bad", {"count": 0}],
            "promotion_strength": "medium",
        },
        state,
        destinations,
        failed,
        failed_zone,
        base,
    )
    assert custom["action_mix"]["staffing"]["move_staff"] == []
    assert "Moves too many guests" in park_optimizer._rejection_reasons([], 80, 60, 80)[0]
    assert "Target capacity" in park_optimizer._rejection_reasons([], 80, 10, 40)[0]
    small_state = copy.deepcopy(state)
    small_state["guestFlow"]["rides"] = small_state["guestFlow"]["rides"][:2]
    deterministic = park_optimizer.optimize_park_response(small_state, "food_spike", {}, {"custom_action_mixes": "bad"})
    assert deterministic["candidate_source"] == "deterministic_templates"


def test_agent_monitoring_fallback_lanes_and_statuses(monkeypatch):
    books = {
        "policy_books": [
            {
                "source": "ops",
                "content": {
                    "policy_book_id": "parkpulse_operations_policy_book",
                    "decision_rules": [
                        {
                            "id": "PARK-OPS-001",
                            "allowed_action": "Executable action required.",
                            "blocked_action": "route all guests or delay legally required steps",
                            "required_evidence": ["state"],
                        }
                    ],
                },
            }
        ]
    }
    monkeypatch.setattr(park_agent_monitoring, "get_policy_books", lambda: books)
    monkeypatch.setattr(park_agent_monitoring, "validate_policy_books", lambda loaded: {"status": "ok"})
    monkeypatch.setattr(park_agent_monitoring, "policy_reference_index", lambda loaded: {"policy_refs": ["PARK-OPS-001"]})

    class FakeArize:
        def public_dict(self):
            return {"ready": True, "project_name": "p", "collector_endpoint": "e", "readiness_issues": []}

    monkeypatch.setattr(park_agent_monitoring, "get_arize_status", lambda: FakeArize())
    lanes = park_agent_monitoring._monitoring_lanes(park_agent_monitoring._policy_books_by_id())
    assert lanes[0]["area"] == "Safety"
    action_plan = {
        "scenario": {"key": "ride_down"},
        "recommended_actions": [
            {"action_id": "missing", "title": "No executable target", "policy_compliance": {"policy_refs": ["PARK-OPS-001"]}},
            {"action_id": "care", "title": "Recovery offer compensation", "park_action": {"target": "ride", "action": "reroute"}, "policy_compliance": {}},
        ],
    }
    monitoring = park_agent_monitoring.build_park_agent_monitoring(sample_state(), action_plan, {"scorecard": {"overall": 90}, "evals": []}, {"count": 0})
    assert monitoring["overall_status"] in {"review", "blocked"}
    clear = park_agent_monitoring.build_park_agent_monitoring(sample_state(), {"scenario": {"key": "ride_down"}, "recommended_actions": []}, {"scorecard": {"overall": 95}, "evals": []}, {"count": 0})
    assert clear["overall_status"] == "clear"


def test_parkpulse_startup_loop_and_simulation_rollover(monkeypatch):
    async def failing_init():
        raise RuntimeError("init failed")

    class StartupSimulation:
        async def step(self):
            raise StopAsyncIteration()

    created = []

    def fake_create_task(coro):
        created.append(coro)
        try:
            coro.send(None)
        except StopAsyncIteration:
            pass
        finally:
            coro.close()
        return SimpleNamespace(done=lambda: True)

    monkeypatch.setattr(parkpulse_api, "init_operational_memory", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(parkpulse_api, "park_simulation", StartupSimulation())
    monkeypatch.setattr(parkpulse_api.asyncio, "create_task", fake_create_task)
    run(parkpulse_api.startup_event())
    assert created

    sim = ParkSimulation()
    sim.minute = 59
    sim.hour = 23
    run(sim.step())
    state = run(sim.get_state())
    assert state["simTime"]["hour"] == 0
    assert state["simTime"]["minute"] == 0


def test_agent_role_run_is_custom_and_persists_receipt():
    payload = run(lazy_main._agent_role_run_payload("food court is down and mobile orders are backing up near the west plaza", "auto"))
    assert payload["selected_role"] == "react"
    assert payload["role_receipt"]["scenario_key"] == "food_spike"
    assert payload["role_receipt"]["dispatch_ids"]
    assert payload["role_receipt"]["learning_update"]["validity"] == "observed_response"
    assert payload["role_receipt"]["bigquery"]["row_counts"]["action_dispatches"] >= 1

    serialized = json.dumps(payload).lower()
    assert "food court a" in serialized
    assert "dragon coaster is down" not in serialized

    dispatches = payload["run_telemetry"]["delivery"]["dispatches"]
    assert {item["channel"] for item in dispatches} == {"guest_app", "worker_device", "equipment_controller"}
    assert all(item.get("durable") is True for item in dispatches)


def test_agent_role_scan_never_dispatches_and_medical_stays_bounded():
    scan = run(lazy_main._agent_role_run_payload("scan vague guest complaints and worker taps for early crowd risk", "scan"))
    assert scan["selected_role"] == "scan"
    assert scan["role_run"]["dispatch_allowed"] is False
    assert scan["run_telemetry"]["delivery"]["summary"]["total"] == 0
    assert scan["role_receipt"]["learning_update"]["validity"] == "needs_response_before_policy_change"

    medical = run(lazy_main._agent_role_run_payload("guest fainted near food court, medical team needed and keep access clear", "auto"))
    assert medical["selected_role"] == "react"
    serialized = json.dumps(medical).lower()
    assert "medical" in serialized or "first aid" in serialized
    assert "diagnose medical condition" in serialized
    assert "broadcast sensitive guest details" in serialized
    assert medical["role_receipt"]["learning_update"]["validity"] in {"observed_response", "needs_response_before_policy_change"}


def test_agent_role_routes_vague_signals_to_proact():
    vague = run(lazy_main._agent_role_run_payload("Staff note: kids are crying near the barrier and the crowd stopped moving by the maze exit", "auto"))
    assert vague["selected_role"] == "proact"
    assert vague["role_receipt"]["role"] == "proact"
    assert vague["role_receipt"]["learning_update"]["validity"] == "observed_response"
    assert vague["role_receipt"]["dispatch_ids"]
