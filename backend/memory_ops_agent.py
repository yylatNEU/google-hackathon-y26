from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import mongo_memory
from mongo_memory import backfill_memory_embeddings, get_operational_memory_dashboard


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _documents_for_embedding_check(collection_name: str, limit: int = 100) -> list[dict[str, Any]]:
    memory = mongo_memory._memory
    collection = memory._collection(collection_name)
    projection = {
        "_id": 1,
        "embedding": 1,
        "embeddingText": 1,
        "embeddingMetadata": 1,
        "modelEmbedding": 1,
        "modelEmbeddingMetadata": 1,
        "updatedAt": 1,
        "createdAt": 1,
    }
    if collection is not None:
        try:
            return [dict(row) for row in collection.find({}, projection).limit(limit)]
        except Exception as error:
            memory.errors.append(f"MemoryOps sample failed for {collection_name}: {error}")
            return []
    return [dict(row) for row in memory._fallback.get(collection_name, [])[:limit]]


def _collection_count(collections: list[dict[str, Any]], name: str) -> int:
    for item in collections:
        if item.get("name") == name:
            try:
                return int(item.get("count", 0) or 0)
            except (TypeError, ValueError):
                return 0
    return 0


def _embedding_coverage(
    collections: list[dict[str, Any]],
    collection_name: str,
    *,
    vector_field: str = "embedding",
    metadata_field: str = "embeddingMetadata",
) -> dict[str, Any]:
    total = _collection_count(collections, collection_name)
    sampled = _documents_for_embedding_check(collection_name)
    embedded = [
        row
        for row in sampled
        if isinstance(row.get(vector_field), list)
        and len(row.get(vector_field, [])) > 0
        and bool(str(row.get("embeddingText", "")).strip())
    ]
    dimensions = sorted({len(row.get(vector_field, [])) for row in embedded if isinstance(row.get(vector_field), list)})
    providers = sorted(
        {
            str((row.get(metadata_field) or {}).get("provider"))
            for row in embedded
            if isinstance(row.get(metadata_field), dict) and (row.get(metadata_field) or {}).get("provider")
        }
    )
    sample_count = len(sampled)
    coverage = round((len(embedded) / sample_count) * 100) if sample_count else 0
    missing_ids = [str(row.get("_id")) for row in sampled if row not in embedded][:8]
    status = "clear" if coverage >= 95 and (total == 0 or sample_count > 0) else "watch" if coverage >= 70 else "action_required"
    return {
        "collection": collection_name,
        "vector_field": vector_field,
        "status": status,
        "total_docs": total,
        "sampled_docs": sample_count,
        "embedded_docs": len(embedded),
        "coverage_pct": coverage,
        "dimensions": dimensions,
        "providers": providers,
        "missing_sample_ids": missing_ids,
    }


def _retrieval_depth_score(dashboard: dict[str, Any]) -> dict[str, Any]:
    collections = dashboard.get("collections", []) if isinstance(dashboard.get("collections"), list) else []
    retrieved = dashboard.get("retrieved", {}) if isinstance(dashboard.get("retrieved"), dict) else {}
    method = str(retrieved.get("method", "unknown"))
    playbook_count = _collection_count(collections, "playbooks")
    incident_count = _collection_count(collections, "incidents")
    learning_count = _collection_count(collections, "agent_learnings")
    latest_decisions = dashboard.get("latest_decisions", []) if isinstance(dashboard.get("latest_decisions"), list) else []
    grounded_decisions = [
        row
        for row in latest_decisions
        if isinstance(row, dict) and (row.get("retrievedPlaybooks") or row.get("retrievedIncidents"))
    ]

    score = 0
    score += min(25, playbook_count * 3)
    score += min(25, incident_count * 4)
    score += min(20, learning_count * 6)
    uses_vector_search = method.startswith("mongodb_vector_search")
    score += 15 if uses_vector_search else 8 if "text" in method else 3
    score += min(15, len(grounded_decisions) * 3)
    score = max(0, min(100, score))

    if score >= 80:
        status = "deep"
    elif score >= 55:
        status = "medium"
    else:
        status = "shallow"
    return {
        "status": status,
        "score": score,
        "retrieval_method": method,
        "playbook_count": playbook_count,
        "incident_count": incident_count,
        "learning_count": learning_count,
        "grounded_latest_decisions": len(grounded_decisions),
        "latest_decisions_sampled": len(latest_decisions),
    }


def _staleness_check(dashboard: dict[str, Any]) -> dict[str, Any]:
    state = dashboard.get("current_state", {}) if isinstance(dashboard.get("current_state"), dict) else {}
    updated_at = _parse_time(state.get("updatedAt"))
    if updated_at is None:
        return {
            "status": "watch",
            "updated_at": None,
            "age_seconds": None,
            "detail": "No live park_state timestamp is available.",
        }
    age_seconds = max(0, round((datetime.now(UTC) - updated_at).total_seconds()))
    if age_seconds <= 300:
        status = "clear"
    elif age_seconds <= 900:
        status = "watch"
    else:
        status = "action_required"
    return {
        "status": status,
        "updated_at": state.get("updatedAt"),
        "age_seconds": age_seconds,
        "detail": "Live park_state is current." if status == "clear" else "Live park_state is stale; run a simulation/state sync before judging retrieval quality.",
    }


def _model_api_readiness(status: dict[str, Any], model_embedding_checks: list[dict[str, Any]]) -> dict[str, Any]:
    model_api = status.get("modelApi", {}) if isinstance(status.get("modelApi"), dict) else {}
    enabled = bool(model_api.get("enabled"))
    configured = bool(model_api.get("configured"))
    expected_dimensions = model_api.get("dimensions")
    blockers: list[str] = []
    warnings: list[str] = []

    if not enabled:
        if not configured:
            blockers.append("Mongo/Voyage model API key is not configured.")
        if model_api.get("readinessIssues"):
            blockers.extend(str(item) for item in model_api.get("readinessIssues", [])[:4])
        return {
            "status": "not_enabled" if not blockers else "blocked",
            "enabled": enabled,
            "configured": configured,
            "provider": model_api.get("provider"),
            "model": model_api.get("model"),
            "vector_field": model_api.get("vectorPath"),
            "expected_dimensions": expected_dimensions,
            "blockers": blockers,
            "warnings": warnings,
        }

    for check in model_embedding_checks:
        if check["total_docs"] > 0 and check["coverage_pct"] < 95:
            blockers.append(
                f"{check['collection']} model embedding coverage is {check['coverage_pct']}% for {check['vector_field']}."
            )
        dimensions = check.get("dimensions") or []
        if expected_dimensions and dimensions and int(expected_dimensions) not in {int(value) for value in dimensions}:
            blockers.append(
                f"{check['collection']} model embedding dimensions {dimensions} do not match configured {expected_dimensions}."
            )
        if not dimensions and check["total_docs"] > 0:
            warnings.append(f"{check['collection']} has no sampled model embedding dimensions yet.")

    return {
        "status": "ready" if not blockers else "blocked",
        "enabled": enabled,
        "configured": configured,
        "provider": model_api.get("provider"),
        "model": model_api.get("model"),
        "vector_field": model_api.get("vectorPath"),
        "expected_dimensions": expected_dimensions,
        "blockers": blockers,
        "warnings": warnings,
    }


def build_memory_ops_report(query: str = "ride down crowd staff food") -> dict[str, Any]:
    dashboard = get_operational_memory_dashboard(query)
    status = dashboard.get("status", {}) if isinstance(dashboard.get("status"), dict) else {}
    collections = dashboard.get("collections", []) if isinstance(dashboard.get("collections"), list) else []
    retrieval_depth = _retrieval_depth_score(dashboard)
    embedding_checks = [
        _embedding_coverage(collections, "playbooks"),
        _embedding_coverage(collections, "incidents"),
        _embedding_coverage(collections, "agent_learnings"),
    ]
    model_embedding_checks = [
        _embedding_coverage(collections, "playbooks", vector_field="modelEmbedding", metadata_field="modelEmbeddingMetadata"),
        _embedding_coverage(collections, "incidents", vector_field="modelEmbedding", metadata_field="modelEmbeddingMetadata"),
        _embedding_coverage(collections, "agent_learnings", vector_field="modelEmbedding", metadata_field="modelEmbeddingMetadata"),
    ]
    model_api_readiness = _model_api_readiness(status, model_embedding_checks)
    staleness = _staleness_check(dashboard)

    findings: list[dict[str, Any]] = []
    recommendations: list[str] = []

    if not status.get("connected"):
        findings.append(
            {
                "severity": "critical",
                "area": "connection",
                "finding": "MongoDB is not connected; the agent is using fallback memory.",
            }
        )
        recommendations.append("Restore MONGODB_URI connectivity before relying on stored operational memory.")

    if retrieval_depth["status"] == "shallow":
        findings.append(
            {
                "severity": "warning",
                "area": "retrieval_depth",
                "finding": "Memory corpus or grounded decision history is too thin for deep retrieval.",
            }
        )
        recommendations.append("Seed more scenario-specific playbooks, incidents, and outcome learnings.")

    if not str(retrieval_depth["retrieval_method"]).startswith("mongodb_vector_search"):
        findings.append(
            {
                "severity": "warning",
                "area": "vector_search",
                "finding": f"Current retrieval method is {retrieval_depth['retrieval_method']}, not mongodb_vector_search.",
            }
        )
        recommendations.append("Verify the Atlas vector index and embedding fields before the demo.")

    for check in embedding_checks:
        if check["status"] != "clear" and check["total_docs"] > 0:
            findings.append(
                {
                    "severity": "warning" if check["status"] == "watch" else "critical",
                    "area": f"{check['collection']}_embedding",
                    "finding": f"{check['collection']} embedding coverage is {check['coverage_pct']}% in the sampled documents.",
                }
            )
            recommendations.append(f"Backfill embedding and embeddingText for {check['collection']} documents.")

    if model_api_readiness["status"] == "blocked":
        for blocker in model_api_readiness["blockers"]:
            findings.append(
                {
                    "severity": "critical",
                    "area": "model_api_grounding",
                    "finding": blocker,
                }
            )
        recommendations.append("Store the model API key, create matching Atlas vector indexes, then backfill modelEmbedding.")
    elif model_api_readiness["status"] == "not_enabled":
        findings.append(
            {
                "severity": "info",
                "area": "model_api_grounding",
                "finding": "Mongo model API grounding is not enabled; conversations use local/vector fallback memory.",
            }
        )
        recommendations.append("Enable PARKPULSE_COPILOT_SEMANTIC_MEMORY and PARKPULSE_MONGO_MODEL_EMBEDDINGS after key/index/backfill are ready.")

    if staleness["status"] != "clear":
        findings.append(
            {
                "severity": "warning" if staleness["status"] == "watch" else "critical",
                "area": "park_state_staleness",
                "finding": staleness["detail"],
            }
        )
        recommendations.append("Sync live park state before running the planner.")

    if not recommendations:
        recommendations.append("MemoryOps found no blocking MongoDB memory issue.")

    severity_order = {"critical": 3, "warning": 2, "info": 1}
    max_severity = max((severity_order.get(item["severity"], 0) for item in findings), default=0)
    overall_status = "action_required" if max_severity >= 3 else "watch" if max_severity == 2 else "clear"

    return {
        "agent_id": "memory_ops_agent",
        "name": "MongoDB MemoryOps Agent",
        "role": "Audits MongoDB operational memory quality, retrieval depth, embedding coverage, and stale state before agent planning.",
        "implemented": True,
        "mcp_mode": "not_configured",
        "runtime_path": "PyMongo operational memory inspection",
        "created_at": _utc_now(),
        "overall_status": overall_status,
        "summary": {
            "retrieval_depth": retrieval_depth["status"],
            "retrieval_depth_score": retrieval_depth["score"],
            "mongo_connected": bool(status.get("connected")),
            "vector_index": (status.get("vectorSearch", {}) if isinstance(status.get("vectorSearch"), dict) else {}).get("index"),
            "model_api_status": model_api_readiness["status"],
            "finding_count": len(findings),
            "blocking_findings": sum(1 for item in findings if item.get("severity") == "critical"),
        },
        "retrieval_depth": retrieval_depth,
        "embedding_coverage": embedding_checks,
        "model_api_readiness": model_api_readiness,
        "model_embedding_coverage": model_embedding_checks,
        "staleness": staleness,
        "findings": findings,
        "recommended_actions": sorted(set(recommendations)),
        "future_mcp_fit": [
            "Use MongoDB MCP for interactive collection/index inspection when the connector is available.",
            "Keep backend runtime reads and writes on PyMongo for request-time reliability.",
            "Use MCP for admin repair workflows such as embedding backfill, corpus seeding, and schema drift checks.",
        ],
    }


def run_memory_ops_repair(
    query: str = "ride down crowd staff food",
    collections: list[str] | None = None,
    limit: int = 250,
) -> dict[str, Any]:
    selected = collections or ["playbooks", "incidents", "agent_learnings"]
    before = build_memory_ops_report(query)
    repair = backfill_memory_embeddings(selected, limit)
    after = build_memory_ops_report(query)
    return {
        "agent_id": "memory_ops_agent",
        "name": "MongoDB MemoryOps Agent",
        "mode": "operator_triggered_repair",
        "status": repair.get("status", "unknown"),
        "created_at": _utc_now(),
        "repair": repair,
        "before": {
            "overall_status": before.get("overall_status"),
            "summary": before.get("summary", {}),
            "embedding_coverage": before.get("embedding_coverage", []),
        },
        "after": {
            "overall_status": after.get("overall_status"),
            "summary": after.get("summary", {}),
            "embedding_coverage": after.get("embedding_coverage", []),
        },
        "next_steps": after.get("recommended_actions", []),
    }
