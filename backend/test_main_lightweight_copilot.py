import asyncio
import sys
import time
import types

import main


def run(coro):
    return asyncio.run(coro)


def test_fast_state_mongo_sync_schedules_background_writer(monkeypatch):
    calls = []

    def fake_sync_park_state(state):
        calls.append(state)
        return {"status": "stored", "collection": "park_state", "updatedAt": "2026-06-06T00:00:00Z"}

    monkeypatch.setitem(sys.modules, "mongo_memory", types.SimpleNamespace(sync_park_state=fake_sync_park_state))
    monkeypatch.setenv("PARKPULSE_FAST_STATE_MONGO_SYNC_ENABLED", "true")
    monkeypatch.setenv("PARKPULSE_FAST_STATE_MONGO_SYNC_INTERVAL_SECONDS", "5")
    with main._fast_state_sync_lock:
        main._fast_state_sync_inflight = False
        main._last_fast_state_sync_at = 0.0
        main._fast_state_sync_status = {"status": "not_started", "mode": "fast_state_mongo_sync", "enabled": True}

    result = main._schedule_fast_state_mongo_sync(
        {"guestFlow": {"activeScenario": {"key": "ride_down"}}, "operationsAudit": {"ready": True}},
        reason="unit_test",
        force=True,
    )

    assert result["status"] == "queued"
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        status = main._fast_state_mongo_sync_status()
        if status["status"] == "stored":
            break
        time.sleep(0.02)

    status = main._fast_state_mongo_sync_status()
    assert calls and calls[0]["guestFlow"]["activeScenario"]["key"] == "ride_down"
    assert status["status"] == "stored"
    assert status["result"]["collection"] == "park_state"
    assert status["result"]["sync_reason"] == "unit_test"


def test_cached_hot_state_hit_schedules_background_sync(monkeypatch):
    calls = []

    def fake_schedule(state, *, reason="fast_state", force=False):
        calls.append({"state": state, "reason": reason, "force": force})
        return {"status": "queued"}

    async def fail_builder():
        raise AssertionError("fresh cache should not call builder")

    monkeypatch.setattr(main, "_schedule_fast_state_mongo_sync", fake_schedule)
    main._hot_endpoint_cache.clear()
    main._hot_endpoint_cache["park_state_lite"] = (
        time.monotonic() + 60,
        {"guestFlow": {"activeScenario": {"key": "ride_down"}}, "operationsAudit": {"ready": True}},
    )

    payload = run(main._cached_hot_endpoint("park_state_lite", 60, fail_builder))

    assert payload["guestFlow"]["activeScenario"]["key"] == "ride_down"
    assert calls == [
        {
            "state": {"guestFlow": {"activeScenario": {"key": "ride_down"}}, "operationsAudit": {"ready": True}},
            "reason": "park_state_lite_cache_hit",
            "force": False,
        }
    ]


def test_lightweight_copilot_returns_complete_contract(monkeypatch):
    async def fake_state():
        return {
            "guestFlow": {
                "rides": [
                    {
                        "id": "dragonCoaster",
                        "name": "Dragon Coaster",
                        "waitMins": 72,
                        "queueGuests": 410,
                        "status": "constrained",
                        "staffAvailable": 3,
                        "staffRequired": 4,
                    }
                ],
                "zones": [{"id": "paradePlaza", "name": "Parade Plaza", "density": 88, "waitMins": 12}],
                "paths": [{"fromName": "Coaster Gate", "toName": "Parade Plaza", "walkMinutes": 4, "congestionLevel": 91}],
            },
            "weather": {"condition": "clear", "heatIndexF": 83, "stormRisk": 5},
            "foodInventory": {"mode": "normal", "risk": "low"},
            "operationsAudit": {"ready": True},
        }

    async def fake_model_response(**kwargs):
        return {
            "source": "test_lightweight_model",
            "provider_ready": True,
            "answer": "Split flow away from Dragon Coaster, keep the parade pinch point staffed, and wait for approval before dispatch.",
            "reasoning_bullets": ["Dragon Coaster has the top wait.", "Parade Plaza is crowded."],
            "operator_next": "Confirm staff at the pinch point.",
            "confidence": 0.81,
            "semantic_memory": {"status": "configured_deferred", "model_api_key_configured": True},
        }

    monkeypatch.setenv("MONGODB_MODEL_API_KEY", "configured")
    main._hot_endpoint_cache.clear()
    monkeypatch.setattr(main, "_fast_park_state_lite", fake_state)
    monkeypatch.setattr(main, "_lightweight_copilot_model_response", fake_model_response)

    payload = run(
        main._build_lightweight_copilot_payload(
            {
                "message": "The coaster queue is too long and families are stuck near the parade. What should we do?",
                "mode": "auto",
                "turn_mode": "propose",
                "allow_action": False,
            }
        )
    )

    assert payload["status"] == "complete"
    assert payload["mode"] == "propose"
    assert payload["selected_role"] in {"react", "proact", "scan"}
    assert payload["conversation_response"]["source"] == "test_lightweight_model"
    assert payload["semantic_memory_context"]["model_api_key_configured"] is True
    assert payload["recommended_action"]["dispatch_count"] == 0
    assert payload["turn_contract"]["state_mutation"] is False
    assert payload["latency_diagnostics"]["status"] == "complete"


def test_copilot_wrapper_uses_lightweight_hot_path_when_full_runtime_loaded(monkeypatch):
    async def fake_lightweight(request_payload):
        return {
            "status": "complete",
            "mode": "answer",
            "message": request_payload.get("message"),
            "answer": "Fast hot-path answer.",
            "turn_contract": {"state_mutation": False, "dispatch_count": 0},
            "latency_diagnostics": {"status": "complete", "stages": []},
        }

    async def fail_full_module(timeout=None):
        raise AssertionError("full runtime should not be called on the copilot hot path")

    monkeypatch.setenv("PARKPULSE_COPILOT_HOT_PATH_LOCAL_ONLY", "true")
    monkeypatch.setenv("PARKPULSE_COPILOT_LIGHTWEIGHT_PATH", "true")
    monkeypatch.setattr(main, "_parkpulse_app", object())
    monkeypatch.setattr(main, "_parkpulse_module", object())
    monkeypatch.setattr(main, "_build_lightweight_copilot_payload", fake_lightweight)
    monkeypatch.setattr(main, "_get_full_module_for_first_response", fail_full_module)

    payload = run(main._build_copilot_payload_with_runtime({"message": "What is the biggest risk?", "mode": "auto"}))

    assert payload["status"] == "complete"
    assert payload["answer"] == "Fast hot-path answer."
    assert payload["turn_contract"]["state_mutation"] is False
    assert payload["latency_diagnostics"]["wrapper"]["path"] == "lightweight_hot_path_local_only"


def test_lightweight_copilot_retrieves_semantic_memory_on_hot_path(monkeypatch):
    async def fake_model_response(**kwargs):
        return {
            "source": "test_lightweight_model",
            "provider_ready": True,
            "answer": "Use the prior queue-split playbook and keep dispatch gated.",
            "reasoning_bullets": ["Semantic memory found a matching playbook."],
            "operator_next": "Review the prior playbook.",
            "confidence": 0.86,
            "semantic_memory": kwargs["semantic_memory_context"],
        }

    def fake_retrieve(query, state, limit, agent_role, cache_policy):
        assert limit == 3
        assert agent_role in {"react", "proact", "scan"}
        assert cache_policy == "fresh_retrieval"
        return {
            "status": {
                "modelApi": {
                    "provider": "voyage",
                    "configured": True,
                    "enabled": True,
                    "model": "voyage-4-lite",
                    "dimensions": 256,
                    "vectorPath": "modelEmbedding",
                }
            },
            "query": query,
            "scenario_key": "unknown",
            "agent_role": agent_role,
            "cache_policy": cache_policy,
            "retrieved": {
                "method": "mongodb_vector_search_voyage",
                "playbooks": [{"_id": "pb-1", "title": "Split coaster queue", "score": 0.91}],
                "incidents": [{"_id": "inc-1", "summary": "Parade edge crowding", "score": 0.88}],
                "learnings": [{"_id": "learn-1", "lesson": "Avoid routing families through parade edge."}],
            },
            "summary": "Retrieved 1 playbook, 1 incident, and 1 learning.",
        }

    monkeypatch.setenv("PARKPULSE_COPILOT_SEMANTIC_MEMORY", "true")
    monkeypatch.setenv("PARKPULSE_MONGO_MODEL_EMBEDDINGS", "true")
    monkeypatch.setenv("MONGODB_MODEL_API_KEY", "configured")
    main._hot_endpoint_cache.clear()
    main._lightweight_semantic_memory_cache.clear()
    monkeypatch.setattr(main, "_lightweight_retrieve_operational_context", fake_retrieve)
    monkeypatch.setattr(main, "_lightweight_copilot_model_response", fake_model_response)

    payload = run(
        main._build_lightweight_copilot_payload(
            {
                "message": "The coaster queue is too long near the parade. What should we do?",
                "mode": "auto",
                "turn_mode": "answer",
                "allow_action": False,
            }
        )
    )

    semantic = payload["semantic_memory_context"]
    assert semantic["status"] == "ready"
    assert semantic["retrieval_method"] == "mongodb_vector_search_voyage"
    assert semantic["model_api"]["provider"] == "voyage"
    assert semantic["counts"] == {"playbooks": 1, "incidents": 1, "learnings": 1}
    assert payload["conversation_memory"]["semantic_memory_status"] == "ready"
    assert any(item["tool"] == "memory.retrieve_semantic_context" for item in payload["tool_call_timeline"])


def test_scan_semantic_memory_uses_role_cache_on_hot_path(monkeypatch):
    seen = {}

    def fake_retrieve(query, state, limit, agent_role, cache_policy):
        seen["agent_role"] = agent_role
        seen["cache_policy"] = cache_policy
        return {
            "status": {"modelApi": {"enabled": True, "provider": "voyage"}},
            "query": query,
            "scenario_key": "ride_down",
            "agent_role": agent_role,
            "cache_policy": cache_policy,
            "retrieved": {
                "method": "role_context_cache",
                "playbooks": [{"_id": "pb-scan", "title": "Watch weak queue signal"}],
                "incidents": [{"_id": "inc-scan", "summary": "Prior weak signal"}],
                "learnings": [{"_id": "learn-scan", "lesson": "Escalate only after confirmation."}],
            },
            "summary": "Retrieved cached scan context.",
        }

    monkeypatch.setenv("PARKPULSE_COPILOT_SEMANTIC_MEMORY", "true")
    monkeypatch.setenv("PARKPULSE_MONGO_MODEL_EMBEDDINGS", "true")
    monkeypatch.setenv("PARKPULSE_COPILOT_LIGHTWEIGHT_SEMANTIC_MEMORY_CACHE_POLICY", "fresh_retrieval")
    monkeypatch.setattr(main, "_lightweight_retrieve_operational_context", fake_retrieve)

    payload = run(
        main._lightweight_copilot_semantic_memory_context(
            "What weak signal should we watch right now?",
            {"guestFlow": {"activeScenario": {"key": "ride_down"}}},
            {"top_rides": [], "crowded_zones": [], "constrained_paths": [], "weather": {}},
            {"selected_role": "scan"},
        )
    )

    assert seen == {"agent_role": "scan", "cache_policy": "role_cache_only"}
    assert payload["status"] == "ready"
    assert payload["retrieval_method"] == "role_context_cache"


def test_scan_semantic_memory_cache_miss_serves_static_fallback(monkeypatch):
    warmups = []

    def fake_retrieve(query, state, limit, agent_role, cache_policy):
        return {
            "status": {"modelApi": {"enabled": True, "provider": "voyage"}},
            "query": query,
            "scenario_key": "unknown",
            "agent_role": "scan_agent",
            "cache_policy": cache_policy,
            "retrieved": {
                "method": "role_context_cache_miss",
                "playbooks": [],
                "incidents": [],
                "learnings": [],
            },
            "summary": "No cached scan context.",
        }

    def fake_warmup(message, state, selected_role, scenario_key):
        warmups.append({"message": message, "selected_role": selected_role, "scenario_key": scenario_key})
        return {"status": "queued", "scenario_key": scenario_key, "role": selected_role}

    monkeypatch.setenv("PARKPULSE_COPILOT_SEMANTIC_MEMORY", "true")
    monkeypatch.setenv("PARKPULSE_MONGO_MODEL_EMBEDDINGS", "true")
    monkeypatch.setenv("PARKPULSE_COPILOT_LIGHTWEIGHT_SEMANTIC_MEMORY_CACHE_POLICY", "fresh_retrieval")
    monkeypatch.setattr(main, "_lightweight_retrieve_operational_context", fake_retrieve)
    monkeypatch.setattr(main, "_schedule_lightweight_role_cache_warmup", fake_warmup)
    main._lightweight_semantic_memory_cache.clear()

    payload = run(
        main._lightweight_copilot_semantic_memory_context(
            "What weak signal should we watch right now?",
            {"guestFlow": {"activeScenario": {"key": "ride_down"}}},
            {
                "top_ride": {"id": "dragonCoaster", "name": "Dragon Coaster"},
                "top_zone": {"id": "paradePlaza", "name": "Parade Plaza"},
                "top_path": {"fromName": "Coaster Gate", "toName": "Parade Plaza"},
            },
            {"selected_role": "scan"},
        )
    )

    assert payload["status"] == "ready"
    assert payload["retrieval_method"] == "role_context_cache_static_fallback"
    assert payload["fallback_reason"] == "role_context_cache_miss"
    assert payload["counts"] == {"playbooks": 1, "incidents": 1, "learnings": 1}
    assert warmups == [
        {
            "message": "What weak signal should we watch right now?",
            "selected_role": "scan",
            "scenario_key": "ride_down",
        }
    ]


def test_lightweight_semantic_memory_timeout_does_not_block_answer(monkeypatch):
    async def fake_model_response(**kwargs):
        return {
            "source": "test_lightweight_model",
            "provider_ready": True,
            "answer": "Continue with a bounded non-dispatching answer.",
            "reasoning_bullets": ["Memory timed out but the hot path stayed responsive."],
            "operator_next": "Ask a narrower follow-up.",
            "confidence": 0.7,
            "semantic_memory": kwargs["semantic_memory_context"],
        }

    def slow_retrieve(*args, **kwargs):
        raise TimeoutError("memory budget exceeded")

    monkeypatch.setenv("PARKPULSE_COPILOT_SEMANTIC_MEMORY", "true")
    monkeypatch.setenv("PARKPULSE_MONGO_MODEL_EMBEDDINGS", "true")
    monkeypatch.setenv("MONGODB_MODEL_API_KEY", "configured")
    main._lightweight_semantic_memory_cache.clear()
    monkeypatch.setattr(main, "_lightweight_retrieve_operational_context", slow_retrieve)
    monkeypatch.setattr(main, "_lightweight_copilot_model_response", fake_model_response)

    payload = run(
        main._build_lightweight_copilot_payload(
            {
                "message": "What is the biggest risk?",
                "mode": "auto",
                "turn_mode": "answer",
                "allow_action": False,
            }
        )
    )

    assert payload["status"] == "complete"
    assert payload["answer"] == "Continue with a bounded non-dispatching answer."
    assert payload["semantic_memory_context"]["status"] == "timeout"
    assert payload["turn_contract"]["state_mutation"] is False
