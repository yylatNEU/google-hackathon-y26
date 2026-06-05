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
