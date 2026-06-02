from __future__ import annotations

import json
import os

os.environ.setdefault("MONGODB_DISABLE_DRIVER_IMPORT", "1")

import main
from review_label_pipeline import auto_label_recommended_candidates, build_review_label_pipeline, record_review_label_decision, review_label_decision_ledger


def _customer_details() -> dict:
    return {
        "data_quality": {"status": "production_ready", "score": 100},
        "feed_contract": {"production_publishable": True, "customer_safe": True},
        "recommended_public_options": {
            "best_ride": {"name": "Theater B"},
            "best_food": {"name": "Food Court B"},
        },
    }


def _training_readiness() -> dict:
    return {
        "agents": {
            "customer_agent": {
                "status": "ready_for_eval_generation",
                "model_training_ready": False,
                "eval_generation_ready": True,
                "recommended_training_mode": "customer_llm_eval_and_supervised_examples",
                "blockers": ["Need reviewed labels."],
            },
            "rl_action_policy": {
                "status": "not_ready",
                "model_training_ready": False,
                "eval_generation_ready": False,
                "recommended_training_mode": "observed_outcome_batch_rl_or_contextual_bandit_only",
                "blockers": ["Need observed outcome rows."],
            },
        }
    }


def _review_ledger() -> dict:
    return {
        "open_reviews": [
            {
                "id": "review-1",
                "case_id": "case-1",
                "priority": "critical",
                "reason": "Low confidence operator report.",
                "event": {"source": "operator_signal", "signal_type": "guest_care", "entity_id": "care"},
            }
        ]
    }


def _live_health() -> dict:
    return {
        "feeds": [
            {
                "source": "food_ops",
                "status": "weak",
                "confidence": 0.5,
                "age_seconds": 400,
                "readiness_issues": ["stale"],
            }
        ]
    }


def test_review_label_pipeline_builds_role_scoped_candidates(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_REVIEW_LABEL_DECISION_LOG_PATH", str(tmp_path / "labels.jsonl"))

    pipeline = build_review_label_pipeline(
        customer_details=_customer_details(),
        training_readiness=_training_readiness(),
        review_ledger=_review_ledger(),
        live_feed_health=_live_health(),
    )

    assert pipeline["status"] == "ready"
    assert pipeline["summary"]["candidate_count"] >= 4
    assert pipeline["summary"]["open_count"] == pipeline["summary"]["candidate_count"]
    assert any(row["agent_id"] == "customer_agent" for row in pipeline["candidates"])
    assert any(row["source"] == "review_training_ledger" for row in pipeline["candidates"])
    assert pipeline["labels_or_reward_changed"] is False


def test_review_label_decision_persists_without_reward(tmp_path, monkeypatch):
    log_path = tmp_path / "labels.jsonl"
    monkeypatch.setenv("PARKPULSE_REVIEW_LABEL_DECISION_LOG_PATH", str(log_path))
    pipeline = build_review_label_pipeline(
        customer_details=_customer_details(),
        training_readiness=_training_readiness(),
        review_ledger=_review_ledger(),
        live_feed_health=_live_health(),
    )
    candidate = pipeline["candidates"][0]

    result = record_review_label_decision(
        {
            "candidate": candidate,
            "candidate_id": candidate["id"],
            "decision": "approve_label",
            "final_label": candidate["proposed_label"],
            "reviewer": "test-reviewer",
            "reason": "Looks correct.",
        }
    )
    ledger = review_label_decision_ledger()

    assert result["status"] == "recorded"
    assert result["decision"]["eligible_for_supervised_training"] is True
    assert result["decision"]["eligible_for_reward"] is False
    assert ledger["summary"]["approved_label_count"] == 1
    assert json.loads(log_path.read_text().splitlines()[0])["labels_or_reward_changed"] is False


def test_auto_label_records_high_confidence_and_skips_low_confidence(tmp_path, monkeypatch):
    log_path = tmp_path / "labels.jsonl"
    monkeypatch.setenv("PARKPULSE_REVIEW_LABEL_DECISION_LOG_PATH", str(log_path))
    pipeline = build_review_label_pipeline(
        customer_details=_customer_details(),
        training_readiness=_training_readiness(),
        review_ledger={
            "open_reviews": [
                {
                    "id": "review-low",
                    "priority": "critical",
                    "reason": "Low confidence operator report.",
                    "event": {"source": "operator_signal", "signal_type": "guest_care", "entity_id": "care", "confidence": 0.42},
                }
            ]
        },
        live_feed_health=_live_health(),
    )

    result = auto_label_recommended_candidates(pipeline, confidence_threshold=0.7, reviewer="test-auto")
    ledger = review_label_decision_ledger()

    assert result["recorded_count"] >= 1
    assert result["skipped_count"] >= 1
    assert all(row["eligible_for_reward"] is False for row in ledger["rows"])
    assert any(item["reason"] == "Recommendation confidence is below the auto-label threshold." for item in result["skipped"])


def test_repeated_live_reviews_get_distinct_label_candidates(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_REVIEW_LABEL_DECISION_LOG_PATH", str(tmp_path / "labels.jsonl"))

    pipeline = build_review_label_pipeline(
        customer_details=_customer_details(),
        training_readiness={"agents": {}},
        review_ledger={
            "open_reviews": [
                {
                    "id": "review-a",
                    "priority": "critical",
                    "reason": "sensitive trigger: medical",
                    "event": {"id": "feed-a", "source": "operator_signal", "signal_type": "guest_care", "entity_id": "care", "confidence": 0.88},
                },
                {
                    "id": "review-b",
                    "priority": "critical",
                    "reason": "sensitive trigger: medical",
                    "event": {"id": "feed-b", "source": "operator_signal", "signal_type": "guest_care", "entity_id": "care", "confidence": 0.88},
                },
            ]
        },
        live_feed_health={"feeds": []},
    )
    live_candidates = [row for row in pipeline["candidates"] if row["source"] == "review_training_ledger"]

    assert len(live_candidates) == 2
    assert len({row["id"] for row in live_candidates}) == 2
    assert {row["evidence_key"] for row in live_candidates} == {"review-a", "review-b"}


async def _call_lazy_app(method: str, path: str, body: dict | None = None, query: bytes = b"") -> tuple[int, dict]:
    payload = json.dumps(body or {}).encode("utf-8")
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    async def send(message):
        sent.append(message)

    await main.app(
        {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": query,
            "headers": [(b"content-type", b"application/json")],
        },
        receive,
        send,
    )
    status = next(item["status"] for item in sent if item["type"] == "http.response.start")
    response_body = b"".join(item.get("body", b"") for item in sent if item["type"] == "http.response.body")
    return status, json.loads(response_body.decode("utf-8") or "{}")


def test_lazy_review_label_pipeline_routes_existing_review_to_candidate(tmp_path, monkeypatch):
    monkeypatch.setenv("PARKPULSE_REVIEW_LABEL_DECISION_LOG_PATH", str(tmp_path / "labels.jsonl"))
    monkeypatch.setenv("PARKPULSE_REVIEW_LEDGER_LOG_PATH", str(tmp_path / "review-ledger.jsonl"))
    monkeypatch.setenv("PARKPULSE_LIVE_FEED_LOG_PATH", str(tmp_path / "live-feed.jsonl"))

    import asyncio

    event_payload = {
        "id": "event-route-1",
        "source": "operator_signal",
        "signal_type": "guest_care",
        "entity_id": "first_aid",
        "confidence": 0.42,
        "value": "Medical team requested near first aid.",
    }
    post_status, post_payload = asyncio.run(_call_lazy_app("POST", "/api/park/live-feed-events", event_payload))
    get_status, pipeline = asyncio.run(_call_lazy_app("GET", "/api/park/review-label-pipeline", query=b"limit=20"))

    assert post_status == 200
    assert post_payload["status"] == "accepted_with_warnings"
    assert get_status == 200
    assert pipeline["status"] == "ready"
    assert pipeline["labels_or_reward_changed"] is False
    assert any(row["source"] == "review_training_ledger" for row in pipeline["candidates"])
