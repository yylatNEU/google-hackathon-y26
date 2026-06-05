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


def test_autodream_run_is_retired_without_cache_replay(monkeypatch, tmp_path):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.setenv("PARKPULSE_RUNTIME_DIR", str(tmp_path))

    import mongo_memory
    import park_autodream_agent

    memory = mongo_memory.OperationalMemory()
    monkeypatch.setattr(mongo_memory, "_memory", memory)
    monkeypatch.setattr(park_autodream_agent, "export_analytics_rows", lambda rows: {"status": "preview", "row_counts": {key: len(value) for key, value in rows.items()}})
    mongo_memory.init_operational_memory()

    result = park_autodream_agent.run_autodream("ride_down", max_cases=1, persist=False)

    assert result["status"] == "retired"
    assert result["summary"]["learnings_generated"] == 0
    assert result["cache_replay_audit"]["status"] == "disabled"
    assert result["storage"]["dream_learning_ids"] == []
    assert "retired" in result["operator_review"]["note"]


def test_autodream_promotion_is_retired(monkeypatch, tmp_path):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.setenv("PARKPULSE_RUNTIME_DIR", str(tmp_path))

    import mongo_memory
    import park_autodream_agent

    memory = mongo_memory.OperationalMemory()
    monkeypatch.setattr(mongo_memory, "_memory", memory)
    monkeypatch.setattr(park_autodream_agent, "export_analytics_rows", lambda rows: {"status": "preview", "row_counts": {key: len(value) for key, value in rows.items()}})
    mongo_memory.init_operational_memory()

    promoted = park_autodream_agent.promote_autodream_learning("dream-retired")

    assert promoted["status"] == "retired"
    readiness = promoted["promotion_readiness"]
    assert readiness["promotion_ready"] is False
    assert readiness["blockers"] == ["autodream_retired"]
    assert promoted["promotion"]["status"] == "retired"
    status = park_autodream_agent.autodream_status(4)
    assert status["status"] == "retired"
    assert status["summary"]["promotion_ready"] == 0


def test_autodream_review_and_status_are_retired(monkeypatch, tmp_path):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.setenv("PARKPULSE_RUNTIME_DIR", str(tmp_path))

    import mongo_memory
    import park_autodream_agent

    memory = mongo_memory.OperationalMemory()
    monkeypatch.setattr(mongo_memory, "_memory", memory)
    monkeypatch.setattr(park_autodream_agent, "export_analytics_rows", lambda rows: {"status": "preview", "row_counts": {key: len(value) for key, value in rows.items()}})
    mongo_memory.init_operational_memory()

    review = park_autodream_agent.review_autodream_learning("dream-retired", "approved", reviewer="qa")
    status = park_autodream_agent.autodream_status(4)

    assert review["status"] == "retired"
    assert review["review"]["review_status"] == "approved"
    assert status["latest_dream_runs"] == []
    assert status["latest_dream_learnings"] == []
    assert status["summary"]["rollback_watch"] == 0


def test_retired_autodream_promotions_do_not_enter_live_context(monkeypatch, tmp_path):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.setenv("PARKPULSE_RUNTIME_DIR", str(tmp_path))

    import mongo_memory

    memory = mongo_memory.OperationalMemory()
    monkeypatch.setattr(mongo_memory, "_memory", memory)
    mongo_memory.init_operational_memory()

    state = {"guestFlow": {"activeScenario": {"key": "ride_down"}}, "alerts": []}
    old_learning = {
        "_id": "learning_autodream_old",
        "documentType": "agent_learning",
        "scenarioKey": "ride_down",
        "lesson": "autodream legacy rule",
        "rule": "legacy autodream rule must not guide live operations",
        "sourceDreamLearningId": "dream-old",
        "tags": ["ride_down", "autodream_promoted"],
    }
    safe_learning = {
        "_id": "learning_live_safe",
        "documentType": "agent_learning",
        "scenarioKey": "ride_down",
        "lesson": "live safe rule",
        "rule": "use current ride downtime dispatch protocol",
        "tags": ["ride_down", "live"],
    }
    old_playbook = {
        "_id": "pb_autodream_old",
        "documentType": "playbook",
        "incidentType": "ride_down",
        "title": "AutoDream Playbook",
        "summary": "legacy autodream playbook",
        "sourceDreamLearningId": "dream-old",
        "tags": ["autodream_promoted"],
    }
    safe_playbook = {
        "_id": "pb_live_safe",
        "documentType": "playbook",
        "incidentType": "ride_down",
        "title": "Live Ride Down Playbook",
        "summary": "dispatch maintenance and guest recovery",
        "tags": ["ride_down", "live"],
    }
    memory._fallback["agent_learnings"].extend([old_learning, safe_learning])
    memory._fallback["playbooks"].extend([old_playbook, safe_playbook])

    fresh = mongo_memory.retrieve_operational_context(
        "ride_down legacy autodream rule",
        state,
        limit=6,
        agent_role="react_agent",
        cache_policy="fresh_retrieval",
        persist_trace=False,
    )
    assert {row.get("_id") for row in fresh["retrieved"]["learnings"]}.isdisjoint({"learning_autodream_old"})
    assert {row.get("_id") for row in fresh["retrieved"]["playbooks"]}.isdisjoint({"pb_autodream_old"})

    memory._fallback["role_context_cache"].append(
        {
            "_id": "role_context_ride_down_react_agent",
            "documentType": "role_context_cache",
            "scenarioKey": "ride_down",
            "agentRole": "react_agent",
            "freshUntil": mongo_memory._utc_after(60),
            "usableUntil": mongo_memory._utc_after(120),
            "stateFingerprint": mongo_memory._state_fingerprint(state),
            "stateSemanticSummary": mongo_memory._state_semantic_summary(state),
            "trustLevel": "fresh",
            "retrieved": {
                "playbooks": [old_playbook, safe_playbook],
                "incidents": [],
                "learnings": [old_learning, safe_learning],
            },
            "roleSpecific": {"candidateRules": [old_learning, safe_learning]},
            "rollup": {"rollbackState": "active"},
        }
    )
    cached = mongo_memory.retrieve_operational_context(
        "ride_down legacy autodream rule",
        state,
        limit=6,
        agent_role="react_agent",
        cache_policy="normal",
        persist_trace=False,
    )
    assert cached["retrieved"]["method"] == "role_context_cache"
    assert {row.get("_id") for row in cached["retrieved"]["learnings"]}.isdisjoint({"learning_autodream_old"})
    assert {row.get("_id") for row in cached["retrieved"]["playbooks"]}.isdisjoint({"pb_autodream_old"})
    assert {row.get("_id") for row in cached["role_context"]["roleSpecific"]["candidateRules"]}.isdisjoint({"learning_autodream_old"})
