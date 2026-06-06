import asyncio

import main


def run(coro):
    return asyncio.run(coro)


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
            "scenario_key": "ride_down",
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
