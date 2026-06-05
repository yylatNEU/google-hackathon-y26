import os

os.environ.setdefault("MONGODB_DISABLE_DRIVER_IMPORT", "1")
os.environ.setdefault("ENABLE_BIGQUERY_ANALYTICS", "false")


def test_cache_accuracy_replay_exercises_cache_modes(monkeypatch, tmp_path):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.setenv("PARKPULSE_RUNTIME_DIR", str(tmp_path))

    import cache_accuracy_replay
    import mongo_memory
    from park_simulation import ParkSimulation

    memory = mongo_memory.OperationalMemory()
    monkeypatch.setattr(mongo_memory, "_memory", memory)
    monkeypatch.setattr(cache_accuracy_replay.mongo_memory, "_memory", memory)
    mongo_memory.init_operational_memory()

    result = cache_accuracy_replay.run_cache_accuracy_replay(ParkSimulation()._state(), persist=True)
    by_mode = {row["mode"]: row for row in result["results"]}

    assert result["status"] == "passed"
    assert result["summary"]["failures"] == []
    assert by_mode["fresh_retrieval"]["retrievalMethod"] == "keyword_similarity"
    assert by_mode["fresh_role_cache"]["retrievalMethod"] == "role_context_cache"
    assert by_mode["stale_usable_cache"]["retrievalMethod"] == "role_context_cache_stale_usable"
    assert by_mode["stale_usable_cache"]["confidence"]["adjusted"] < by_mode["stale_usable_cache"]["confidence"]["original"]
    assert by_mode["dangerous_drift_blocked"]["mustRevalidate"] is True
    assert by_mode["dangerous_drift_blocked"]["policyGate"]["status"] == "blocked"
    assert result["storage"]["status"] == "stored"
    assert mongo_memory._memory._fallback["cache_accuracy_replays"]

    scorecards = mongo_memory.get_agent_performance_scorecards("ride_down")
    react = next(row for row in scorecards["scorecards"] if row["agentRole"] == "react_agent")
    assert react["metrics"]["cacheReplay"]["passRate"] == 1.0
    assert react["metrics"]["cacheReplay"]["dangerousDriftBlockRate"] == 1.0
    assert react["metrics"]["cacheReplay"]["staleUsableServeRate"] == 1.0


def test_autodream_preview_runs_cache_replay_audit(monkeypatch, tmp_path):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.setenv("PARKPULSE_RUNTIME_DIR", str(tmp_path))

    import mongo_memory
    import park_autodream_agent

    memory = mongo_memory.OperationalMemory()
    monkeypatch.setattr(mongo_memory, "_memory", memory)
    monkeypatch.setattr(park_autodream_agent, "export_analytics_rows", lambda rows: {"status": "preview", "row_counts": {key: len(value) for key, value in rows.items()}})
    mongo_memory.init_operational_memory()

    result = park_autodream_agent.run_autodream("ride_down", max_cases=1, persist=False)

    assert result["status"] == "complete"
    assert result["summary"]["cache_replay_status"] == "failed"
    assert result["summary"]["cache_replay_pass_rate"] < 1.0
    assert result["cache_replay_audit"]["summary"]["roles_checked"] == len(park_autodream_agent.AUTODREAM_CACHE_REPLAY_ROLES)
    assert result["dream_run"]["cacheReplayAudit"]["status"] == "failed"
    assert any("stale_usable_cache_not_served" in failure for failure in result["cache_replay_audit"]["summary"]["failures"])


def test_autodream_promotion_requires_readiness_contract(monkeypatch, tmp_path):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.setenv("PARKPULSE_RUNTIME_DIR", str(tmp_path))

    import mongo_memory
    import park_autodream_agent

    memory = mongo_memory.OperationalMemory()
    monkeypatch.setattr(mongo_memory, "_memory", memory)
    monkeypatch.setattr(park_autodream_agent, "export_analytics_rows", lambda rows: {"status": "preview", "row_counts": {key: len(value) for key, value in rows.items()}})
    mongo_memory.init_operational_memory()

    dream = park_autodream_agent.run_autodream("ride_down", max_cases=1, persist=True)
    dream_learning_id = dream["storage"]["dream_learning_ids"][0]
    initial_readiness = mongo_memory.get_autodream_promotion_readiness(dream_learning_id)
    assert initial_readiness["promotion_ready"] is False
    assert "paired_benchmark_not_passed" in initial_readiness["blockers"]

    promoted = park_autodream_agent.promote_autodream_learning(dream_learning_id)

    assert promoted["status"] == "promoted"
    readiness = promoted["promotion_readiness"]
    assert readiness["promotion_ready"] is True
    assert readiness["cache_replay_passed"] is True
    assert readiness["paired_benchmark_passed"] is True
    assert readiness["regression_risk"] is False
    assert readiness["ground_truth_lift"] >= 0
    assert promoted["promotion"]["promotion_readiness"]["promotion_ready"] is True
    status = park_autodream_agent.autodream_status(4)
    assert status["summary"]["promotion_ready"] >= 1


def test_autodream_regression_triggers_rollback_watch(monkeypatch, tmp_path):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.setenv("PARKPULSE_RUNTIME_DIR", str(tmp_path))

    import mongo_memory
    import park_autodream_agent
    from park_simulation import ParkSimulation

    memory = mongo_memory.OperationalMemory()
    monkeypatch.setattr(mongo_memory, "_memory", memory)
    monkeypatch.setattr(park_autodream_agent, "export_analytics_rows", lambda rows: {"status": "preview", "row_counts": {key: len(value) for key, value in rows.items()}})
    mongo_memory.init_operational_memory()

    dream = park_autodream_agent.run_autodream("ride_down", max_cases=1, persist=True)
    dream_learning_id = dream["storage"]["dream_learning_ids"][0]
    promoted = park_autodream_agent.promote_autodream_learning(dream_learning_id)
    promoted_id = promoted["promotion"]["promoted_document_id"]
    state = ParkSimulation()._state()
    mongo_memory.record_outcome_event(
        {
            "loop_id": "rollback-watch-test",
            "response_metrics": {"takeRate": 0.1, "reactiveFollowThroughRate": 0.1, "positiveResponseRate": 0.15},
            "state_impact": {"queued_guest_delta": 40, "density_delta": 8, "comfort_delta": -3},
            "scorecard": {"overall": 42},
            "learning": {"take_rate_signal": "regression"},
        },
        "decision-rollback-watch",
        state,
    )

    rollback = mongo_memory.get_rollback_watch_documents("ride_down")
    readiness = mongo_memory.get_autodream_promotion_readiness(dream_learning_id)
    context = mongo_memory.retrieve_operational_context("ride_down autodream promoted learning", state, agent_role="react_agent", cache_policy="fresh_retrieval")
    retrieved_learning_ids = {row.get("_id") for row in context["retrieved"]["learnings"]}
    status = park_autodream_agent.autodream_status(4)

    assert rollback["count"] >= 1
    assert any(row["_id"] == promoted_id for row in rollback["documents"])
    assert readiness["promotion_ready"] is False
    assert readiness["regression_risk"] is True
    assert "rollback_watch" in readiness["blockers"]
    assert promoted_id not in retrieved_learning_ids
    assert status["summary"]["rollback_watch"] >= 1
