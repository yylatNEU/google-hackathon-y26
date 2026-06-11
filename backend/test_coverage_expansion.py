import asyncio
import copy
import json
import os
import sys
from types import SimpleNamespace

os.environ.setdefault("MONGODB_DISABLE_DRIVER_IMPORT", "1")
os.environ.setdefault("ENABLE_BIGQUERY_ANALYTICS", "false")
os.environ.setdefault("PARKPULSE_ENABLE_OTEL_SPANS", "false")
os.environ.setdefault("PARKPULSE_MONGO_MODEL_EMBEDDINGS", "false")
os.environ.setdefault("PARKPULSE_COPILOT_SEMANTIC_MEMORY", "false")

import pytest

import bigquery_analytics
import gcp_training_seed
import park_episode_learning
import park_signal_intake
from park_simulation import ParkSimulation


def run(coro):
    return asyncio.run(coro)


def state():
    sim = ParkSimulation()
    park_state = run(sim.get_state())
    park_state["simTime"] = {"day": 1, "hour": 17, "minute": 50}
    park_state["weather"]["heatIndexF"] = 101
    park_state["energy"]["gridLoadPercent"] = 96
    park_state["staffing"]["openCallouts"] = 23
    return park_state


def context():
    return {
        "status": {"mode": "demo_fallback", "connected": False},
        "retrieved": {
            "playbooks": [{"_id": "pb", "title": "Ride", "summary": "Split demand"}],
            "incidents": [{"_id": "inc", "summary": "Crowd issue", "lesson": "Send staff"}],
            "learnings": [{"_id": "learn", "lesson": "Use specific routing", "takeRateSignal": "ok"}],
        },
    }


def test_signal_intake_classifies_fuses_and_tracks_inbox():
    park_signal_intake._signal_inbox.clear()
    park_state = state()

    reports = [
        ("A child is lost and crying near the coaster queue.", "guest_app", None, "guest"),
        ("People are running, pushing, and yelling fire near the maze exit.", "worker_quick_tap", "coveredPlaza", "zone_lead"),
        ("Someone fainted by Food Court A and medical is needed.", "guest_health_report", "foodCourt1", "guest"),
        ("Lighting controller has smoke and missed heartbeat near the covered plaza.", "equipment_telemetry", None, "maintenance"),
        ("Wheelchair assistance needed by the stroller corridor.", "accessibility_request", None, "guest_services"),
        ("Angry guest complaint about a long wait and unfair refund.", "guest_complaint", "entrancePlaza", None),
        ("Heard a rumor maybe someone said the line is blocked.", "social_snippet", None, None),
    ]
    signals = [
        park_signal_intake.classify_unstructured_signal(
            text=text,
            source=source,
            zone_id=zone_id,
            reporter_role=role,
            park_state=park_state,
        )
        for text, source, zone_id, role in reports
    ]

    assert any("child_care" in signal["categories"] for signal in signals)
    assert any(signal["risk_level"] == "CRITICAL" for signal in signals)
    assert any(payload["channel"] == "equipment_controller" for signal in signals for payload in signal["dispatch_payloads"])
    assert park_signal_intake.latest_signals(3)["count"] == 3
    assert park_signal_intake._missing_info(["rumor", "equipment_safety"], 0.5)
    assert park_signal_intake._risk_from_categories(["crowd_pressure"], {"density": 80}, "crowd")[0] == "MEDIUM"
    assert park_signal_intake._risk_from_categories(["unusual_situation"], {"density": 20}, "watch")[0] == "WATCH"

    health_batch = park_signal_intake.realistic_signal_batch(park_state, "health_accessibility")
    crowd_batch = park_signal_intake.realistic_signal_batch(park_state, "crowd_care_conflict")
    fused_health = park_signal_intake.fuse_signal_batch(health_batch, park_state)
    fused_crowd = park_signal_intake.fuse_signal_batch(crowd_batch, park_state)

    assert fused_health["fusion"]["source_count"] >= 6
    assert "medical" in fused_health["categories"]
    assert fused_crowd["fusion"]["disagreement"] is True
    assert any(item["channel"] == "equipment_controller" for item in fused_crowd["dispatch_payloads"])


def test_episode_learning_retrieval_training_and_dataset_status():
    park_episode_learning._TRAINING_EPISODE_LOG.clear()
    signal = {
        "id": "signal-1",
        "source": "guest_health_report",
        "source_signals": [
            {"source": "worker_quick_tap", "categories": ["medical", "accessibility"]},
            {"source": "first_aid_dispatch", "categories": ["medical"]},
        ],
        "zone": {"id": "foodCourt1", "name": "Food Court 1"},
        "categories": ["medical", "accessibility", "crowd_pressure"],
        "risk_level": "CRITICAL",
        "confidence": 0.9,
        "human_approval_required": True,
        "recommended_actions": [
            {"operation": "dispatch_medical", "target": "staff"},
            {"operation": "accessibility_support", "target": "staff"},
        ],
        "fusion": {"corroboration_count": 3},
    }
    delivery = {
        "summary": {"total": 2},
        "response": {"takeRate": 0.6, "positiveResponseRate": 0.9, "reactiveFollowThroughRate": 0.5, "sampleSize": 8, "status": "healthy"},
        "dispatches": [{"channel": "worker_device"}],
    }
    governance = {"summary": {"allowed": 2, "review": 0, "blocked": 0}}
    before_count = park_episode_learning.episode_dataset_status()["generated_episode_count"]
    learning = park_episode_learning.build_learning_context(signal, delivery, governance, state())

    assert learning["persistence"]["status"] == "stored"
    assert learning["promotion_gate"]["trusted_for_planning"] is True
    assert learning["retrieval_quality"]["status"] in {"strong_match", "usable_match"}
    assert learning["priors"]["confirmed_incident_count"] >= 1
    assert park_episode_learning.episode_dataset_status()["generated_episode_count"] == before_count + 1

    rumor_signal = {
        "id": "signal-2",
        "source": "social_snippet",
        "zone": {"id": "entrancePlaza"},
        "categories": ["rumor", "guest_complaint"],
        "risk_level": "WATCH",
        "confidence": 0.4,
        "recommended_actions": [],
        "fusion": {"corroboration_count": 1},
    }
    weak = park_episode_learning.build_learning_context(rumor_signal, {"summary": {}, "response": {}}, {"summary": {}}, state())
    assert weak["persistence"]["status"] == "blocked"
    assert weak["promotion_gate"]["trusted_for_planning"] is False
    assert "no receiver response or outcome metric has been observed" in weak["promotion_gate"]["reasons"]
    assert park_episode_learning.episode_dataset_status()["generated_episode_count"] == before_count + 1
    assert weak["retrieval_quality"]["status"] in {"weak_match", "usable_match"}
    assert park_episode_learning._infer_incident_type({"categories": ["equipment_safety"]}) == "equipment_safety"
    assert park_episode_learning._infer_incident_type({"categories": ["guest_complaint"]}) == "guest_recovery"
    assert park_episode_learning._expected_response([])["median_ack_seconds"] is None


class FakeDataset:
    def __init__(self, dataset_id):
        self.dataset_id = dataset_id
        self.location = None


class FakeSchemaField:
    def __init__(self, name, field_type, mode="NULLABLE"):
        self.name = name
        self.field_type = field_type
        self.mode = mode


class FakeTable:
    def __init__(self, table_id, schema=None):
        self.table_id = table_id
        self.schema = schema


class FakeQueryJobConfig:
    def __init__(self, query_parameters=None):
        self.query_parameters = query_parameters or []


class FakeScalarQueryParameter:
    def __init__(self, name, field_type, value):
        self.name = name
        self.field_type = field_type
        self.value = value


class FakeQueryResult:
    def __init__(self, rows):
        self._rows = rows

    def result(self):
        return self._rows


class FakeBigQueryClient:
    inserted = []

    def __init__(self, project=None):
        self.project = project
        self.datasets = []
        self.tables = []

    def create_dataset(self, dataset, exists_ok=True):
        self.datasets.append(dataset)
        return dataset

    def create_table(self, table, exists_ok=True):
        self.tables.append(table)
        return table

    def insert_rows_json(self, table_id, rows):
        FakeBigQueryClient.inserted.append((table_id, rows))
        return [] if "eval_results" not in table_id else [{"index": 0, "errors": ["bad"]}]

    def query(self, query, job_config=None):
        return FakeQueryResult(
            [
                {
                    "action_cohort": "guest_app",
                    "prior_take_rate": 0.64,
                    "prior_follow_through": 0.58,
                    "avg_response_score": 82,
                    "run_count": 3,
                }
            ]
        )


def install_fake_bigquery(monkeypatch, client_cls=FakeBigQueryClient):
    fake_bq = SimpleNamespace(
        Client=client_cls,
        Dataset=FakeDataset,
        SchemaField=FakeSchemaField,
        Table=FakeTable,
        QueryJobConfig=FakeQueryJobConfig,
        ScalarQueryParameter=FakeScalarQueryParameter,
    )
    google_module = sys.modules.get("google", SimpleNamespace())
    cloud_module = SimpleNamespace(bigquery=fake_bq)
    setattr(google_module, "cloud", cloud_module)
    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.cloud", cloud_module)
    monkeypatch.setitem(sys.modules, "google.cloud.bigquery", fake_bq)
    monkeypatch.setattr(bigquery_analytics, "bigquery", None)
    monkeypatch.setattr(bigquery_analytics, "_bigquery_import_error", None)
    return fake_bq


def analytics_rows():
    return bigquery_analytics.build_analytics_rows(
        decision_id="decision-1",
        outcome_id="outcome-1",
        scenario_key="ride_down",
        delivery={
            "response": {"takeRate": "0.5", "positiveResponseRate": "0.8", "reactiveFollowThroughRate": "0.4", "score": "70"},
            "dispatches": [
                {"id": "d1", "channel": "guest_app", "targetSystem": "app", "status": "delivered", "response": {"takeRate": 0.5}},
                "bad",
            ],
        },
        outcome={"learning": {"take_rate_signal": "ok"}, "state_impact": {"headline": "better"}},
        eval_result={"scorecard": {"overall": 88, "response_score": 70, "status": "healthy"}},
        source="test",
    )


def test_bigquery_analytics_status_export_priors_and_dream_rows(monkeypatch):
    for key in ("ENABLE_BIGQUERY_ANALYTICS", "BIGQUERY_PROJECT", "GOOGLE_CLOUD_PROJECT"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(bigquery_analytics, "bigquery", None)
    monkeypatch.setattr(bigquery_analytics, "_bigquery_import_error", "missing")

    assert bigquery_analytics._env_bool("MISSING", True) is True
    assert bigquery_analytics._flatten_metric("bad") is None
    disabled = bigquery_analytics.bigquery_status()
    assert disabled["ready"] is False
    preview = bigquery_analytics.export_analytics_rows(analytics_rows())
    assert preview["status"] == "fallback_preview"

    install_fake_bigquery(monkeypatch)
    monkeypatch.setenv("ENABLE_BIGQUERY_ANALYTICS", "true")
    monkeypatch.setenv("BIGQUERY_PROJECT", "project-1")
    monkeypatch.setenv("BIGQUERY_DATASET", "dataset_1")
    monkeypatch.setenv("BIGQUERY_AUTO_CREATE_TABLES", "true")

    status = bigquery_analytics.bigquery_status()
    assert status["ready"] is True
    exported = bigquery_analytics.export_analytics_rows(analytics_rows())
    assert exported["status"] == "partial_error"
    assert exported["inserted"]["outcome_events"] == 1

    summary = bigquery_analytics.analytics_learning_summary({"latest_outcomes": [1, 2], "latest_learnings": [1]})
    assert summary["latest_operational_rows_available"]["outcomes"] == 2
    priors = bigquery_analytics.build_bigquery_agent_priors("ride_down", {"latest_outcomes": [1], "latest_learnings": [{"lesson": "learned"}]})
    assert priors["source"] == "bigquery_query"
    assert priors["best_prior"]["cohort"] == "guest_app"
    assert bigquery_analytics._fallback_agent_priors("unknown")

    dream_rows = bigquery_analytics.build_dream_analytics_rows(
        {
            "dream_run_id": "dream-1",
            "dream_run": {"bigqueryPriors": {"source": "bq"}},
            "summary": {"prior_source": "summary"},
            "dream_learnings": [{"_id": "learn-1", "scenarioKey": "ride_down", "confidence": "91", "promoted": True}],
        }
    )
    assert dream_rows["dream_eval_results"][0]["promoted"] is True

    class BrokenClient(FakeBigQueryClient):
        def create_dataset(self, dataset, exists_ok=True):
            raise RuntimeError("dataset denied")

    install_fake_bigquery(monkeypatch, BrokenClient)
    assert "dataset" in bigquery_analytics._ensure_bigquery_tables(BrokenClient("p"), status, ["outcome_events"])


def test_gcp_training_seed_helpers_and_async_orchestration(monkeypatch):
    park_state = state()

    async def fake_reset():
        return {"status": "success"}

    async def fake_execute(target, action):
        return {"status": "success", "target": target, "action": action}

    async def fake_inject(kind, target_id, intensity):
        return {"status": "success", "event": {"kind": kind, "targetId": target_id, "intensity": intensity}}

    async def fake_state():
        return copy.deepcopy(park_state)

    fake_sim = SimpleNamespace(reset_demo=fake_reset, execute_action=fake_execute, inject_event=fake_inject, get_state=fake_state)
    monkeypatch.setattr(gcp_training_seed, "park_simulation", fake_sim)
    monkeypatch.setattr(gcp_training_seed, "init_operational_memory", lambda: {"mode": "test"})
    monkeypatch.setattr(gcp_training_seed, "sync_park_state", lambda s: {"status": "stored"})
    monkeypatch.setattr(gcp_training_seed, "retrieve_operational_context", lambda query, s: context())
    monkeypatch.setattr(gcp_training_seed, "record_agent_decision", lambda *args, **kwargs: "decision-1")
    monkeypatch.setattr(gcp_training_seed, "record_outcome_event", lambda *args, **kwargs: "outcome-1")
    monkeypatch.setattr(gcp_training_seed, "export_analytics_rows", lambda rows: {"status": "exported", "inserted": {k: len(v) for k, v in rows.items()}, "errors": {}})
    monkeypatch.setattr(gcp_training_seed, "_bigquery_outcome_exists", lambda outcome_id: False)

    selected = gcp_training_seed._selected_action({"selected_action": {"park_action": {"target": "food", "action": "suppress_item"}, "title": "Food"}})
    assert selected["target"] == "food"
    assert gcp_training_seed._memory_eval({"risk_counts": {"crowded_zones": 2}, "needs_human_approval": True}, "food_spike")["safety_score"] == 90

    run(gcp_training_seed._prepare_case_state("ride_down", [{"kind": "ride_failure", "target_id": "dragonCoaster", "intensity": 90}]))
    result = run(
        gcp_training_seed._run_training_case(
            round_index=0,
            scenario_key="ride_down",
            source="test_seed",
            case_id="case-1",
            events=[{"kind": "food_spike", "target_id": "foodCourt1", "intensity": 80}],
            allow_duplicates=False,
        )
    )
    assert result["analytics_status"] == "exported"
    assert result["case_id"] == "case-1"
    assert run(gcp_training_seed.run_training_seed(1, ["ride_down"], allow_duplicates=False))[0]["scenario"] == "ride_down"
    assert run(gcp_training_seed.run_synthetic_training(gcp_training_seed.SYNTHETIC_CASES[:1], allow_duplicates=False))[0]["event_count"] >= 1

    monkeypatch.setattr(gcp_training_seed, "_bigquery_outcome_exists", lambda outcome_id: True)
    duplicate = run(
        gcp_training_seed._run_training_case(
            round_index=0,
            scenario_key="ride_down",
            source="test_seed",
            case_id=None,
            events=None,
            allow_duplicates=False,
        )
    )
    assert duplicate["analytics_status"] == "skipped_existing"

    monkeypatch.setattr(gcp_training_seed, "online_improvement_status", lambda: {"ready": False, "readiness_issues": ["missing"]})
    monkeypatch.setattr(sys, "argv", ["gcp_training_seed.py"])
    with pytest.raises(SystemExit) as blocked:
        gcp_training_seed.main()
    assert "blocked" in str(blocked.value)

    monkeypatch.setattr(gcp_training_seed, "online_improvement_status", lambda: {"ready": True})
    monkeypatch.setattr(gcp_training_seed, "run_training_seed", lambda rounds, scenarios, allow_duplicates=False: [{"scenario": scenarios[0]}])
    monkeypatch.setattr(sys, "argv", ["gcp_training_seed.py", "--scenarios", "bad"])
    with pytest.raises(SystemExit) as invalid:
        gcp_training_seed.main()
    assert "No valid scenarios" in str(invalid.value)
