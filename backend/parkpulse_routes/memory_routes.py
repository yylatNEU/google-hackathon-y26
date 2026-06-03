from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from park_role_access import authorize_role_action, normalize_role, verify_role_session


class MemoryOpsRepairRequest(BaseModel):
    query: str = Field(default="ride down crowd staff food")
    collections: list[str] = Field(default_factory=lambda: ["playbooks", "incidents", "agent_learnings"])
    limit: int = Field(default=250, ge=1, le=1000)


class AutoDreamRunRequest(BaseModel):
    scenario_key: str = Field(default="proactive_eventops")
    max_cases: int = Field(default=8, ge=1, le=25)
    persist: bool = Field(default=True)


class AutoDreamPromoteRequest(BaseModel):
    dream_learning_id: str
    target: str = Field(default="agent_learnings")
    reviewer: str = Field(default="operator")


class AutoDreamReviewRequest(BaseModel):
    dream_learning_id: str
    review_status: str = Field(default="rejected")
    reviewer: str = Field(default="operator")
    reason: str = Field(default="")


class AutoDreamBenchmarkRequest(BaseModel):
    scenario_key: str | None = Field(default=None)
    promoted_rule_id: str | None = Field(default=None)
    seeds: int = Field(default=5, ge=1, le=20)


class CacheAccuracyReplayRequest(BaseModel):
    scenario_key: str | None = Field(default=None)
    agent_role: str = Field(default="react_agent")
    persist: bool = Field(default=True)


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _role_auth_secret() -> str:
    return os.getenv("PARKPULSE_ROLE_AUTH_SECRET") or "parkpulse-local-dev-secret-change-before-production"


def _signed_role_required_for_mutation() -> bool:
    return _truthy(os.getenv("PARKPULSE_REQUIRE_SIGNED_ROLE_FOR_MUTATION"), False)


def _extract_role_token(request: Request) -> str | None:
    explicit = request.headers.get("x-parkpulse-role-token")
    if explicit:
        return explicit
    authorization = request.headers.get("authorization") or ""
    if authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None


def _role_identity_from_request(request: Request) -> dict[str, Any]:
    token_status = verify_role_session(_extract_role_token(request), _role_auth_secret())
    if token_status.get("authenticated"):
        return {
            "status": "authenticated",
            "authenticated": True,
            "auth_method": "signed_role_session",
            "role": token_status.get("role"),
            "subject": token_status.get("subject"),
            "token_status": token_status.get("status"),
        }
    role_header = request.headers.get("x-parkpulse-role") or request.headers.get("x-role")
    return {
        "status": "unauthenticated",
        "authenticated": False,
        "auth_method": "role_header_fallback",
        "role": normalize_role(role_header, default="ops_team"),
        "token_status": token_status.get("status"),
        "reason": token_status.get("reason"),
    }


def _enforce_role_capability(request: Request, capability: str, resource: str) -> dict[str, Any]:
    identity = _role_identity_from_request(request)
    authorization = authorize_role_action(str(identity.get("role") or "ops_team"), capability, resource=resource, default_role="ops_team")
    authorization["identity"] = identity
    if _signed_role_required_for_mutation() and not identity.get("authenticated"):
        authorization["allowed"] = False
        authorization["status"] = "blocked"
        authorization["reason"] = "Signed ParkPulse role session is required for this mutation."
    if authorization.get("allowed") is not True:
        raise HTTPException(status_code=403, detail={"status": "blocked", "mode": "role_access_enforcement", "authorization": authorization})
    return authorization


def register_memory_routes(app: Any, deps: dict[str, Any]) -> None:
    router = APIRouter()

    async def current_state() -> dict[str, Any]:
        park_simulation = deps["park_simulation"]
        state = await park_simulation.get_state()
        await deps["sync_park_state_safe"](state)
        return state

    @router.get("/api/park/memory")
    async def park_memory(query: str = "ride down crowd staff food"):
        from memory_ops_agent import build_memory_ops_report
        from mongo_memory import get_operational_memory_dashboard

        await current_state()
        dashboard = get_operational_memory_dashboard(query)
        dashboard["memory_ops"] = build_memory_ops_report(query)
        return dashboard

    @router.get("/api/park/memory/maintenance")
    async def park_memory_maintenance(query: str = "ride down crowd staff food"):
        from memory_ops_agent import build_memory_ops_report

        await current_state()
        return build_memory_ops_report(query)

    @router.get("/api/park/memory/intelligence")
    async def park_memory_intelligence(
        query: str = "ride down crowd staff food",
        scenario_key: str | None = None,
        agent_role: str | None = None,
    ):
        from mongo_memory import get_operational_intelligence

        await current_state()
        return get_operational_intelligence(query, scenario_key, agent_role)

    @router.get("/api/park/memory/scorecards")
    async def park_memory_scorecards(scenario_key: str | None = None, limit: int = 50):
        from mongo_memory import get_agent_performance_scorecards

        state = await current_state()
        resolved_scenario = scenario_key or state.get("guestFlow", {}).get("activeScenario", {}).get("key", "ride_down")
        return get_agent_performance_scorecards(resolved_scenario, max(1, min(50, int(limit or 50))))

    @router.post("/api/park/memory/cache-replay")
    async def park_memory_cache_replay(request: CacheAccuracyReplayRequest):
        from cache_accuracy_replay import run_cache_accuracy_replay

        state = await current_state()
        deps["clear_hot_endpoint_cache"]()
        return run_cache_accuracy_replay(
            state,
            scenario_key=request.scenario_key,
            agent_role=request.agent_role,
            persist=request.persist,
        )

    @router.post("/api/park/memory/maintenance/repair")
    async def park_memory_maintenance_repair(request: MemoryOpsRepairRequest):
        from memory_ops_agent import run_memory_ops_repair

        await current_state()
        deps["clear_hot_endpoint_cache"]()
        return run_memory_ops_repair(request.query, request.collections, request.limit)

    @router.post("/api/park/autodream/run")
    async def park_autodream_run(http_request: Request, request: AutoDreamRunRequest):
        from park_autodream_agent import run_autodream

        role_authorization = _enforce_role_capability(http_request, "start_offline_training", "autodream.run")
        await current_state()
        deps["clear_hot_endpoint_cache"]()
        result = run_autodream(request.scenario_key, max_cases=request.max_cases, persist=request.persist)
        if isinstance(result, dict):
            result.setdefault("role_authorization", role_authorization)
        return result

    @router.get("/api/park/autodream/status")
    async def park_autodream_status(limit: int = 8):
        from park_autodream_agent import autodream_status

        return autodream_status(limit)

    @router.post("/api/park/autodream/promote")
    async def park_autodream_promote(http_request: Request, request: AutoDreamPromoteRequest):
        from park_autodream_agent import promote_autodream_learning

        role_authorization = _enforce_role_capability(http_request, "promote_learning", "autodream.promote")
        deps["clear_hot_endpoint_cache"]()
        result = promote_autodream_learning(request.dream_learning_id, request.target, request.reviewer)
        if isinstance(result, dict):
            result.setdefault("role_authorization", role_authorization)
        return result

    @router.post("/api/park/autodream/review")
    async def park_autodream_review(http_request: Request, request: AutoDreamReviewRequest):
        from park_autodream_agent import review_autodream_learning

        role_authorization = _enforce_role_capability(http_request, "review_learning", "autodream.review")
        deps["clear_hot_endpoint_cache"]()
        result = review_autodream_learning(request.dream_learning_id, request.review_status, request.reviewer, request.reason)
        if isinstance(result, dict):
            result.setdefault("role_authorization", role_authorization)
        return result

    @router.post("/api/park/autodream/benchmark")
    async def park_autodream_benchmark(request: AutoDreamBenchmarkRequest):
        from mongo_memory import record_autodream_benchmark
        from park_autodream_benchmark import run_autodream_benchmark

        state = await current_state()
        benchmark = run_autodream_benchmark(
            state,
            scenario_key=request.scenario_key,
            promoted_rule_id=request.promoted_rule_id,
            seeds=request.seeds,
        )
        if benchmark.get("status") == "complete":
            benchmark["storage"] = record_autodream_benchmark(benchmark)
            deps["clear_hot_endpoint_cache"]()
        return benchmark

    @router.get("/api/park/autodream/benchmarks")
    async def park_autodream_benchmarks(limit: int = 8):
        from mongo_memory import get_latest_memory_documents

        safe_limit = max(1, min(25, int(limit or 8)))
        benchmarks = get_latest_memory_documents("autodream_benchmarks", safe_limit)
        return {
            "status": "ready",
            "count": len(benchmarks),
            "latest_benchmarks": benchmarks,
        }

    @router.get("/api/park/analytics")
    async def park_analytics(query: str = "ride down crowd staff food"):
        from bigquery_analytics import analytics_learning_summary
        from mongo_memory import get_operational_memory_dashboard

        await current_state()
        dashboard = get_operational_memory_dashboard(query)
        return analytics_learning_summary(dashboard)

    app.include_router(router)
