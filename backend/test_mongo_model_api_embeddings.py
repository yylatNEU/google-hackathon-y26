import json
import os

os.environ.setdefault("MONGODB_DISABLE_DRIVER_IMPORT", "1")

import mongo_memory
import memory_ops_agent


def test_model_api_status_requires_key_when_enabled(monkeypatch):
    monkeypatch.setenv("PARKPULSE_MONGO_MODEL_EMBEDDINGS", "true")
    monkeypatch.delenv("MONGODB_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("MONGODB_VOYAGE_API_KEY", raising=False)
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)

    status = mongo_memory._mongo_model_api_status()

    assert status["provider"] == "voyage"
    assert status["configured"] is False
    assert status["enabled"] is False
    assert status["readinessIssues"]


def test_embedding_update_attaches_model_embedding_without_storing_key(monkeypatch):
    monkeypatch.setenv("PARKPULSE_MONGO_MODEL_EMBEDDINGS", "true")
    monkeypatch.setenv("MONGODB_MODEL_API_KEY", "secret-model-key")
    monkeypatch.setenv("MONGODB_MODEL_EMBEDDING_MODEL", "voyage-4-lite")
    monkeypatch.setenv("MONGODB_MODEL_EMBEDDING_PATH", "modelEmbedding")
    monkeypatch.setenv("MONGODB_MODEL_EMBEDDING_DIMENSIONS", "3")
    monkeypatch.setattr(
        mongo_memory,
        "_voyage_embedding_request",
        lambda text, *, input_type, timeout_seconds: [0.25, -0.5, 0.75],
    )

    update = mongo_memory._embedding_update("coaster queue pressure near parade", input_type="document")

    assert update["embeddingMetadata"]["provider"] == "local_hash"
    assert update["modelEmbedding"] == [0.25, -0.5, 0.75]
    assert update["modelEmbeddingMetadata"]["provider"] == "voyage"
    assert update["modelEmbeddingMetadata"]["dimensions"] == 3
    assert "secret-model-key" not in json.dumps(update)


def test_query_embedding_uses_model_path_when_enabled(monkeypatch):
    monkeypatch.setenv("PARKPULSE_MONGO_MODEL_EMBEDDINGS", "true")
    monkeypatch.setenv("MONGODB_MODEL_API_KEY", "secret-model-key")
    monkeypatch.setenv("MONGODB_MODEL_EMBEDDING_PATH", "modelEmbedding")
    monkeypatch.setattr(
        mongo_memory,
        "_voyage_embedding_request",
        lambda text, *, input_type, timeout_seconds: [0.1, 0.2, 0.3],
    )

    vector, path, metadata = mongo_memory._query_embedding("missing child near food court")

    assert vector == [0.1, 0.2, 0.3]
    assert path == "modelEmbedding"
    assert metadata["provider"] == "voyage"
    assert metadata["inputType"] == "query"


def test_memory_ops_model_api_readiness_blocks_missing_coverage():
    status = {
        "modelApi": {
            "provider": "voyage",
            "configured": True,
            "enabled": True,
            "model": "voyage-4-lite",
            "dimensions": 3,
            "vectorPath": "modelEmbedding",
        }
    }
    checks = [
        {
            "collection": "playbooks",
            "vector_field": "modelEmbedding",
            "total_docs": 4,
            "coverage_pct": 50,
            "dimensions": [3],
        },
        {
            "collection": "incidents",
            "vector_field": "modelEmbedding",
            "total_docs": 0,
            "coverage_pct": 0,
            "dimensions": [],
        },
    ]

    readiness = memory_ops_agent._model_api_readiness(status, checks)

    assert readiness["status"] == "blocked"
    assert "playbooks model embedding coverage is 50%" in readiness["blockers"][0]


def test_memory_ops_model_api_readiness_passes_matching_embeddings():
    status = {
        "modelApi": {
            "provider": "voyage",
            "configured": True,
            "enabled": True,
            "model": "voyage-4-lite",
            "dimensions": 3,
            "vectorPath": "modelEmbedding",
        }
    }
    checks = [
        {
            "collection": "playbooks",
            "vector_field": "modelEmbedding",
            "total_docs": 4,
            "coverage_pct": 100,
            "dimensions": [3],
        }
    ]

    readiness = memory_ops_agent._model_api_readiness(status, checks)

    assert readiness["status"] == "ready"
    assert readiness["blockers"] == []
