from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit


LABEL_DECISIONS = {"approve_label", "edit_label", "reject_label", "needs_more_evidence"}
DEFAULT_AUTO_LABEL_CONFIDENCE_THRESHOLD = 0.70
_MONGO_CLIENT_LOCK = threading.Lock()
_MONGO_CLIENT: Any | None = None


def build_review_label_pipeline(
    *,
    customer_details: dict[str, Any],
    training_readiness: dict[str, Any],
    review_ledger: dict[str, Any],
    live_feed_health: dict[str, Any],
    limit: int = 40,
) -> dict[str, Any]:
    candidates = _candidate_rows(customer_details, training_readiness, review_ledger, live_feed_health)
    decisions = _latest_decisions()
    rows = [_attach_decision(candidate, decisions) for candidate in candidates]
    open_rows = [row for row in rows if row.get("review_status") == "pending_review"]
    decided_rows = [row for row in rows if row.get("review_status") != "pending_review"]
    approved = [row for row in decided_rows if row.get("decision", {}).get("decision") in {"approve_label", "edit_label"}]
    return {
        "status": "ready",
        "mode": "review_label_pipeline",
        "created_at": _now_iso(),
        "summary": {
            "candidate_count": len(rows),
            "open_count": len(open_rows),
            "decided_count": len(decided_rows),
            "approved_label_count": len(approved),
            "training_candidate_count": len(approved),
        },
        "candidates": open_rows[: max(1, min(200, int(limit or 40)))],
        "decided": decided_rows[:20],
        "label_options": sorted(LABEL_DECISIONS),
        "auto_label_rule": {
            "enabled": True,
            "confidence_threshold": DEFAULT_AUTO_LABEL_CONFIDENCE_THRESHOLD,
            "decision": "approve_label",
            "low_confidence_action": "leave_pending_for_human_review",
        },
        "training_rule": "Approved review labels become supervised label evidence only. They do not set reward, promote policies, dispatch actions, or override measured outcomes.",
        "boundary": "Review labels are role-scoped, human-reviewed, and stored separately from RL reward/outcome attribution.",
        "uses_seed_data": False,
        "labels_or_reward_changed": False,
        "llm_used_for_reward_or_label": False,
    }


def auto_label_recommended_candidates(pipeline: dict[str, Any], *, reviewer: str = "parkpulse-auto-labeler", confidence_threshold: float = DEFAULT_AUTO_LABEL_CONFIDENCE_THRESHOLD) -> dict[str, Any]:
    threshold = max(0.0, min(1.0, float(confidence_threshold)))
    candidates = pipeline.get("candidates", []) if isinstance(pipeline.get("candidates"), list) else []
    recorded: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        confidence = _recommendation_confidence(candidate)
        if confidence < threshold:
            skipped.append(
                {
                    "candidate_id": candidate.get("id"),
                    "proposed_label": candidate.get("proposed_label"),
                    "recommendation_confidence": confidence,
                    "reason": "Recommendation confidence is below the auto-label threshold.",
                }
            )
            continue
        result = record_review_label_decision(
            {
                "candidate_id": candidate.get("id"),
                "candidate": candidate,
                "decision": "approve_label",
                "final_label": candidate.get("proposed_label"),
                "reviewer": reviewer,
                "reason": f"Auto-labeled recommended supervised label because recommendation confidence {confidence:.2f} >= threshold {threshold:.2f}.",
            }
        )
        if result.get("status") == "recorded":
            recorded.append(result.get("decision", {}))
        else:
            skipped.append(
                {
                    "candidate_id": candidate.get("id"),
                    "proposed_label": candidate.get("proposed_label"),
                    "recommendation_confidence": confidence,
                    "reason": (result.get("readiness_issues") or ["Unable to record label decision."])[0],
                }
            )
    return {
        "status": "recorded" if recorded else "no_high_confidence_candidates",
        "mode": "review_label_auto_label",
        "created_at": _now_iso(),
        "confidence_threshold": threshold,
        "recorded_count": len(recorded),
        "skipped_count": len(skipped),
        "recorded": recorded,
        "skipped": skipped,
        "training_rule": "Auto-label only approves the proposed supervised label when recommendation confidence meets threshold. It never sets reward or promotes policies.",
        "uses_seed_data": False,
        "labels_or_reward_changed": False,
        "llm_used_for_reward_or_label": False,
    }


def record_review_label_decision(payload: dict[str, Any]) -> dict[str, Any]:
    candidate = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else {}
    candidate_id = str(payload.get("candidate_id") or payload.get("candidateId") or candidate.get("id") or "").strip()
    decision = str(payload.get("decision") or "").strip()
    if not candidate_id:
        return {"status": "error", "mode": "review_label_decision", "readiness_issues": ["candidate_id is required."]}
    if decision not in LABEL_DECISIONS:
        return {"status": "error", "mode": "review_label_decision", "readiness_issues": [f"decision must be one of {sorted(LABEL_DECISIONS)}."]}
    final_label = str(payload.get("final_label") or payload.get("finalLabel") or candidate.get("proposed_label") or "").strip()
    if decision in {"approve_label", "edit_label"} and not final_label:
        return {"status": "error", "mode": "review_label_decision", "readiness_issues": ["final_label is required for approved or edited labels."]}
    row = {
        "id": _hash_id("review_label", {"candidate_id": candidate_id, "decision": decision, "at": time.time()}),
        "created_at": _now_iso(),
        "candidate_id": candidate_id,
        "decision": decision,
        "reviewer": str(payload.get("reviewer") or "parkpulse-reviewer")[:120],
        "reason": str(payload.get("reason") or payload.get("note") or "")[:500],
        "final_label": final_label,
        "training_scope": str(payload.get("training_scope") or payload.get("trainingScope") or candidate.get("training_scope") or "unknown")[:120],
        "agent_id": str(payload.get("agent_id") or payload.get("agentId") or candidate.get("agent_id") or "unknown")[:120],
        "candidate_snapshot": _public_candidate_snapshot(candidate),
        "eligible_for_supervised_training": decision in {"approve_label", "edit_label"},
        "eligible_for_reward": False,
        "labels_or_reward_changed": False,
        "llm_used_for_reward_or_label": False,
        "boundary": "This records a human supervised-label disposition only. Reward still requires measured outcome attribution.",
    }
    _append_jsonl(_decision_log_path(), row)
    return {"status": "recorded", "mode": "review_label_decision", "decision": row}


def review_label_decision_ledger(limit: int = 120) -> dict[str, Any]:
    rows = _read_jsonl(_decision_log_path(), limit=limit)
    approved = [row for row in rows if row.get("eligible_for_supervised_training") is True]
    return {
        "status": "ready" if rows else "empty",
        "mode": "review_label_decision_ledger",
        "created_at": _now_iso(),
        "summary": {
            "row_count": len(rows),
            "approved_label_count": len(approved),
            "rejected_or_needs_evidence_count": len(rows) - len(approved),
        },
        "rows": rows[:limit],
        "training_rule": "Only approved/edit decisions are supervised-label evidence; none are reward.",
        "uses_seed_data": False,
        "labels_or_reward_changed": False,
        "llm_used_for_reward_or_label": False,
    }


def _candidate_rows(
    customer_details: dict[str, Any],
    training_readiness: dict[str, Any],
    review_ledger: dict[str, Any],
    live_feed_health: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rows.extend(_customer_candidates(customer_details))
    rows.extend(_training_readiness_candidates(training_readiness))
    rows.extend(_live_review_candidates(review_ledger, live_feed_health))
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        deduped[str(row["id"])] = row
    return sorted(deduped.values(), key=lambda row: (_priority_rank(row.get("priority")), str(row.get("id"))))


def _customer_candidates(details: dict[str, Any]) -> list[dict[str, Any]]:
    if not details:
        return []
    quality = details.get("data_quality", {}) if isinstance(details.get("data_quality"), dict) else {}
    feed = details.get("feed_contract", {}) if isinstance(details.get("feed_contract"), dict) else {}
    picks = details.get("recommended_public_options", {}) if isinstance(details.get("recommended_public_options"), dict) else {}
    if not quality and not feed and not picks:
        return []
    best_ride = picks.get("best_ride", {}) if isinstance(picks.get("best_ride"), dict) else {}
    best_food = picks.get("best_food", {}) if isinstance(picks.get("best_food"), dict) else {}
    return [
        _candidate(
            agent_id="customer_agent",
            training_scope="customer_llm_supervised",
            source="customer_public_data_feed",
            priority="high" if quality.get("status") == "production_ready" else "medium",
            input_summary=f"Best public recommendation: {best_ride.get('name') or 'unknown'}; food backup: {best_food.get('name') or 'unknown'}.",
            proposed_label="customer_recommendation_grounded" if quality.get("status") == "production_ready" else "customer_feed_not_training_ready",
            label_options=["customer_recommendation_grounded", "customer_feed_not_training_ready", "needs_reviewer_edit"],
                evidence={
                    "quality_status": quality.get("status"),
                    "quality_score": quality.get("score"),
                    "production_publishable": feed.get("production_publishable"),
                    "best_ride": best_ride.get("name"),
                    "best_food": best_food.get("name"),
                },
                recommendation_confidence=_customer_confidence(quality, feed),
                safety_notes=["Customer labels must not include private guest data or internal ops policy."],
            )
        ]


def _training_readiness_candidates(training: dict[str, Any]) -> list[dict[str, Any]]:
    agents = training.get("agents", {}) if isinstance(training.get("agents"), dict) else {}
    rows: list[dict[str, Any]] = []
    for agent_id, row in agents.items():
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "unknown")
        blockers = row.get("blockers", []) if isinstance(row.get("blockers"), list) else []
        proposed = "training_ready" if row.get("model_training_ready") else "blocked_needs_more_evidence"
        rows.append(
            _candidate(
                agent_id=str(agent_id),
                training_scope=str(row.get("recommended_training_mode") or "role_scoped_training"),
                source="training_readiness",
                priority="high" if blockers else "medium",
                input_summary=f"{agent_id}: {status}; blockers={len(blockers)}.",
                proposed_label=proposed,
                label_options=["training_ready", "eval_generation_ready", "blocked_needs_more_evidence", "reject_training_candidate"],
                evidence={"status": status, "blockers": blockers[:6], "model_training_ready": row.get("model_training_ready"), "eval_generation_ready": row.get("eval_generation_ready")},
                recommendation_confidence=_training_confidence(row),
                safety_notes=["Training readiness labels do not override source quality, review gates, or measured outcome requirements."],
            )
        )
    return rows


def _live_review_candidates(review_ledger: dict[str, Any], live_feed_health: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    open_reviews = review_ledger.get("open_reviews", []) if isinstance(review_ledger.get("open_reviews"), list) else []
    for review in open_reviews[:20]:
        if not isinstance(review, dict):
            continue
        event = review.get("event", {}) if isinstance(review.get("event"), dict) else {}
        rows.append(
            _candidate(
                agent_id="scan_agent",
                training_scope="live_feed_review_supervised",
                source="review_training_ledger",
                priority=str(review.get("priority") or "medium"),
                input_summary=f"{event.get('source') or 'feed'} {event.get('signal_type') or 'signal'} on {event.get('entity_id') or 'entity'}: {review.get('reason') or 'review required'}.",
                proposed_label="needs_corroboration" if review.get("priority") in {"critical", "high"} else "watch_signal",
                label_options=["trusted_signal", "needs_corroboration", "false_positive", "escalate_to_owner"],
                evidence={"review_id": review.get("id"), "case_id": review.get("case_id"), "event": event, "reason": review.get("reason")},
                recommendation_confidence=_live_review_confidence(review, event),
                safety_notes=["Live-feed review labels become supervised evidence only after human disposition."],
            )
        )
    feeds = live_feed_health.get("feeds", []) if isinstance(live_feed_health.get("feeds"), list) else []
    for feed in feeds:
        if not isinstance(feed, dict):
            continue
        if str(feed.get("status") or "") in {"ready", "trusted"}:
            continue
        rows.append(
            _candidate(
                agent_id="scan_agent",
                training_scope="live_feed_quality_supervised",
                source="live_feed_health",
                priority="medium",
                input_summary=f"{feed.get('source')}: {feed.get('status')} / {feed.get('readiness_issues', [''])[0] if isinstance(feed.get('readiness_issues'), list) else ''}",
                proposed_label="weak_or_stale_feed",
                label_options=["weak_or_stale_feed", "acceptable_feed", "needs_source_fix"],
                evidence={"source": feed.get("source"), "status": feed.get("status"), "confidence": feed.get("confidence"), "age_seconds": feed.get("age_seconds"), "readiness_issues": feed.get("readiness_issues")},
                recommendation_confidence=_feed_quality_confidence(feed),
                safety_notes=["Feed quality labels should not mark generated data as real observation."],
            )
        )
    return rows


def _candidate(
    *,
    agent_id: str,
    training_scope: str,
    source: str,
    priority: str,
    input_summary: str,
    proposed_label: str,
    label_options: list[str],
    evidence: dict[str, Any],
    recommendation_confidence: float | None = None,
    safety_notes: list[str],
) -> dict[str, Any]:
    basis = {
        "agent_id": agent_id,
        "training_scope": training_scope,
        "source": source,
        "input_summary": input_summary,
        "proposed_label": proposed_label,
        "evidence_key": _candidate_evidence_key(source, evidence),
    }
    return {
        "id": _hash_id("label_candidate", basis),
        "created_at": _now_iso(),
        **basis,
        "priority": priority,
        "evidence_key": basis["evidence_key"],
        "label_options": label_options,
        "evidence": evidence,
        "recommendation": _recommendation_metadata(recommendation_confidence, proposed_label),
        "safety_notes": safety_notes,
        "review_status": "pending_review",
        "eligible_for_supervised_training_if_approved": True,
        "eligible_for_reward": False,
        "boundary": "Auto-label is allowed only when recommendation confidence meets threshold; low-confidence candidates stay pending for human review.",
    }


def _attach_decision(candidate: dict[str, Any], decisions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    row = dict(candidate)
    decision = decisions.get(str(candidate.get("id")))
    if decision:
        row["review_status"] = "approved_for_supervised_training" if decision.get("eligible_for_supervised_training") else "closed_not_training"
        row["decision"] = decision
    return row


def _public_candidate_snapshot(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": candidate.get("id"),
        "agent_id": candidate.get("agent_id"),
        "training_scope": candidate.get("training_scope"),
        "source": candidate.get("source"),
        "evidence_key": candidate.get("evidence_key"),
        "input_summary": candidate.get("input_summary"),
        "proposed_label": candidate.get("proposed_label"),
        "priority": candidate.get("priority"),
    }


def _candidate_evidence_key(source: str, evidence: dict[str, Any]) -> str:
    if source == "review_training_ledger":
        event = evidence.get("event", {}) if isinstance(evidence.get("event"), dict) else {}
        return str(evidence.get("review_id") or evidence.get("case_id") or event.get("id") or event.get("source_event_id") or "review_unknown")
    if source == "live_feed_health":
        issue = ""
        issues = evidence.get("readiness_issues") if isinstance(evidence.get("readiness_issues"), list) else []
        if issues:
            issue = str(issues[0])
        return f"{evidence.get('source') or 'feed'}:{evidence.get('status') or 'unknown'}:{issue}"
    return "role_scope"


def _recommendation_metadata(confidence: float | None, proposed_label: str) -> dict[str, Any]:
    score = _bounded_confidence(confidence if confidence is not None else 0.0)
    status = "high" if score >= DEFAULT_AUTO_LABEL_CONFIDENCE_THRESHOLD else "medium" if score >= 0.55 else "low"
    return {
        "proposed_label": proposed_label,
        "confidence": score,
        "confidence_status": status,
        "auto_label_eligible": score >= DEFAULT_AUTO_LABEL_CONFIDENCE_THRESHOLD,
        "auto_label_decision": "approve_label" if score >= DEFAULT_AUTO_LABEL_CONFIDENCE_THRESHOLD else None,
        "low_confidence_action": "human_review_required" if score < DEFAULT_AUTO_LABEL_CONFIDENCE_THRESHOLD else None,
    }


def _recommendation_confidence(candidate: dict[str, Any]) -> float:
    recommendation = candidate.get("recommendation", {}) if isinstance(candidate.get("recommendation"), dict) else {}
    return _bounded_confidence(recommendation.get("confidence"))


def _bounded_confidence(value: Any) -> float:
    try:
        return round(max(0.0, min(1.0, float(value))), 3)
    except (TypeError, ValueError):
        return 0.0


def _customer_confidence(quality: dict[str, Any], feed: dict[str, Any]) -> float:
    score = _bounded_confidence((quality.get("score") or 0) / 100)
    if quality.get("status") == "production_ready" and feed.get("production_publishable") is True:
        return max(0.9, score)
    if quality.get("status"):
        return max(0.6, score)
    return 0.4


def _training_confidence(row: dict[str, Any]) -> float:
    blockers = row.get("blockers", []) if isinstance(row.get("blockers"), list) else []
    has_status = bool(row.get("status"))
    has_training_flags = row.get("model_training_ready") is not None or row.get("eval_generation_ready") is not None
    if blockers and has_status and has_training_flags:
        return 0.86
    if has_status and has_training_flags:
        return 0.8
    if has_status:
        return 0.62
    return 0.45


def _live_review_confidence(review: dict[str, Any], event: dict[str, Any]) -> float:
    reason = str(review.get("reason") or "").lower()
    event_confidence = _bounded_confidence(event.get("confidence") if event else 0.0)
    if "low confidence" in reason or event_confidence < 0.7:
        return min(0.55, event_confidence or 0.55)
    if review.get("priority") in {"critical", "high"} and event_confidence >= 0.7:
        return min(0.92, max(0.74, event_confidence))
    return min(0.86, max(0.58, event_confidence))


def _feed_quality_confidence(feed: dict[str, Any]) -> float:
    confidence = _bounded_confidence(feed.get("confidence"))
    if confidence < 0.7:
        return confidence
    if feed.get("status") in {"stale", "weak", "missing"}:
        return max(0.72, confidence)
    return confidence


def _latest_decisions() -> dict[str, dict[str, Any]]:
    rows = _read_jsonl(_decision_log_path(), limit=1000)
    decisions: dict[str, dict[str, Any]] = {}
    for row in rows:
        candidate_id = str(row.get("candidate_id") or "")
        if candidate_id and candidate_id not in decisions:
            decisions[candidate_id] = row
    return decisions


def _decision_log_path() -> str:
    return os.getenv("PARKPULSE_REVIEW_LABEL_DECISION_LOG_PATH", "/tmp/parkpulse/review_label_decisions.jsonl")


def _storage_mode() -> str:
    mode = str(os.getenv("PARKPULSE_REVIEW_LABEL_STORAGE") or os.getenv("PARKPULSE_LIVE_FEED_STORAGE") or "jsonl").strip().lower().replace("-", "_")
    if mode in {"mongo", "mongodb"}:
        return "mongodb"
    return "jsonl"


def _strip_secret(value: str | None) -> str:
    raw = str(value or "").strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        return raw[1:-1].strip()
    return raw


def _int_env(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _mongo_uri() -> str:
    return _strip_secret(os.getenv("MONGODB_DIRECT_URI") or os.getenv("MONGODB_URI") or os.getenv("MONGO_URI"))


def _mongo_database_name() -> str:
    configured = str(os.getenv("MONGODB_DATABASE") or "").strip()
    if configured:
        return configured
    uri = _mongo_uri()
    if uri:
        path = urlsplit(uri).path.strip("/")
        if path:
            return path.split("/")[0]
    return "parkpulse"


def _mongo_client() -> Any | None:
    global _MONGO_CLIENT
    if _MONGO_CLIENT is not None:
        return _MONGO_CLIENT
    uri = _mongo_uri()
    if not uri:
        return None
    with _MONGO_CLIENT_LOCK:
        if _MONGO_CLIENT is not None:
            return _MONGO_CLIENT
        try:
            from mongo_memory import _ensure_mongo_driver, _normalized_mongodb_uri
            import mongo_memory

            if not _ensure_mongo_driver() or mongo_memory.MongoClient is None:
                return None
            timeout_ms = max(250, _int_env("MONGODB_OPERATION_TIMEOUT_MS", 1500))
            _MONGO_CLIENT = mongo_memory.MongoClient(
                _normalized_mongodb_uri(uri),
                serverSelectionTimeoutMS=timeout_ms,
                connectTimeoutMS=timeout_ms,
                socketTimeoutMS=timeout_ms,
                retryWrites=True,
            )
            return _MONGO_CLIENT
        except Exception:
            return None


def _write_mongo_decision(row: dict[str, Any]) -> bool:
    client = _mongo_client()
    if client is None:
        return False
    try:
        document = deepcopy(row)
        if document.get("id"):
            document.setdefault("_id", str(document["id"]))
        client[_mongo_database_name()].review_label_decisions.replace_one(
            {"_id": document.get("_id")} if document.get("_id") else {"id": document.get("id")},
            document,
            upsert=True,
        )
        return True
    except Exception:
        return False


def _read_mongo_decisions(limit: int = 500) -> list[dict[str, Any]]:
    client = _mongo_client()
    if client is None:
        return []
    try:
        safe_limit = max(1, min(5000, int(limit or 500)))
        max_time_ms = max(250, _int_env("PARKPULSE_REVIEW_LABEL_MONGO_QUERY_TIMEOUT_MS", 1000))
        cursor = client[_mongo_database_name()].review_label_decisions.find(
            {},
            {"embedding": 0, "embeddingText": 0},
            max_time_ms=max_time_ms,
        ).sort("created_at", -1).limit(safe_limit)
        rows = []
        for row in cursor:
            if isinstance(row, dict):
                clean = dict(row)
                clean.pop("_id", None)
                rows.append(clean)
        return rows
    except Exception:
        return []


def _append_jsonl(path: str, row: dict[str, Any]) -> None:
    if _storage_mode() == "mongodb" and _mongo_uri() and _write_mongo_decision(row):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def _read_jsonl(path: str, limit: int = 500) -> list[dict[str, Any]]:
    if _storage_mode() == "mongodb" and _mongo_uri():
        rows = _read_mongo_decisions(limit=limit)
        if rows:
            return rows
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()[-max(1, min(5000, int(limit or 500))) :]
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in reversed(lines):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _hash_id(prefix: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return f"{prefix}_{hashlib.sha1(raw).hexdigest()[:14]}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _priority_rank(value: Any) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "watch": 3, "low": 4}.get(str(value or "").lower(), 5)
