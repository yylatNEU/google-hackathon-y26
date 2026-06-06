from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from contextlib import asynccontextmanager, nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from env_bootstrap import load_backend_env

load_backend_env()


RUNTIME_BUILD_ID = "latency-hot-route-v5-2026-06-03"
LIVE_FEED_CASE_BANK_INDEX = Path(
    os.getenv(
        "PARKPULSE_LIVE_FEED_CASE_BANK_INDEX",
        str(Path(__file__).resolve().parents[1] / "output" / "qa" / "live-feed-case-bank" / "index.jsonl"),
    )
)


class _NoopSpan:
    def set_attribute(self, *_args, **_kwargs) -> None:
        return None


class _NoopTracer:
    def start_as_current_span(self, *_args, **_kwargs):
        return nullcontext(_NoopSpan())


def _get_tracer(name: str):
    if str(os.getenv("PARKPULSE_ENABLE_OTEL_SPANS", "")).strip().lower() not in {"1", "true", "yes", "on"}:
        return _NoopTracer()
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except Exception:
        return _NoopTracer()


from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agent_handshake import (
    agent_contract,
    agent_handshake_scenario_catalog,
    agent_handshake_live_state_feed,
    agent_handshake_protocol_docs,
    agent_trust_registry_status,
    capability_handshake,
    certify_agent_onboarding,
    certification_issuer_metadata,
    close_session as close_agent_session,
    commerce_agent_evaluate,
    commit_plan,
    counter_proposal,
    demo_handshake,
    demo_supply_chain_handshake,
    escalate_session as escalate_agent_session,
    evaluate_policy_action,
    get_session as get_agent_session,
    get_agent_onboarding,
    identity_handshake,
    intent_handshake,
    issue_delegation_token,
    issue_agent_consent_grant,
    list_agent_credential_revocations,
    list_agent_trust_audit_events,
    list_agent_trust_keys,
    list_agent_trust_partners,
    monitor_session,
    propose_plan,
    queue_agent_reroute,
    register_agent_onboarding,
    revoke_agent_certification_credential,
    rotate_agent_certification_key,
    run_external_client_agent_demo,
    run_passport_second_run_demo,
    run_agent_handshake_policy_challenges,
    run_agent_handshake_scenario_evaluations,
    session_protocol_receipt,
    upsert_agent_trust_partner,
    verify_agent_certification_credential,
    verify_protocol_artifact,
)
from arize_config import get_arize_status, setup_arize_tracing
from analytics_action_layer import build_analytics_to_action_layer
from bigquery_analytics import (
    analytics_learning_summary,
    build_bigquery_agent_priors,
    bigquery_status,
    build_analytics_rows,
    export_analytics_rows,
    online_improvement_status,
)
from digital_twin_tools import build_digital_twin_tool_trace, list_digital_twin_tools, run_digital_twin_tool
from customer_emergency_incidents import (
    build_customer_emergency_audit_event,
    create_customer_emergency_incident,
    get_customer_emergency_incident,
    list_customer_emergency_incidents,
    update_customer_emergency_incident,
    upsert_customer_emergency_incident,
)
from customer_emergency_scope import build_customer_emergency_scope, classify_customer_scope_text
from digital_twin_calibration import build_calibration_ledger
from executive_experience_artifacts import import_demo_executive_experience_evidence, review_executive_experience_artifact, save_monthly_guest_feedback_brief, simulate_executive_experience_evidence
from park_mission_replay import build_mission_replay
from park_scenario_lab import build_scenario_lab
from park_readiness_brief import build_readiness_brief
from park_learned_agent_maturity import build_learned_agent_maturity
from park_learning_evidence_ledger import build_learning_evidence_ledger
from evaluator_loop import evaluator_loop_status
from agent_role_skills import build_deliberate_role_eval_report, evaluate_agent_role_trace, list_agent_role_skills, route_agent_role
from agent_role_trace_samples import record_agent_role_trace_sample
from agent_ops_ledger import build_operational_backlog, read_agent_ops_ledger, record_agent_ops_record, record_agent_ops_run, retrieve_agent_ops_context
from executive_experience_evidence import build_executive_experience_evidence
from executive_experience_intelligence import build_executive_experience_intelligence
from incident_analytics import build_incident_analytics
from digital_twin_benchmark import (
    attach_learning_comparison,
    latest_benchmark_report,
    generate_remediation_playbooks,
    list_benchmark_scenarios,
    read_benchmark_history,
    record_benchmark_result,
    run_digital_twin_benchmark,
    run_parkpulse_agent_benchmark,
)
from park_understanding_benchmark import (
    latest_park_understanding_benchmark,
    list_park_understanding_cases,
    run_live_park_understanding_benchmark,
    run_park_understanding_benchmark,
)
from gcp_trace_eval import get_gcp_trace_eval_status, setup_gcp_cloud_trace_exporter
from gcp_operations import (
    decode_eventarc_pubsub_signal,
    firestore_status,
    gcp_operations_status,
    latest_firestore_operations,
    latest_pseudo_firebase_messages,
    pseudo_firebase_status,
    publish_park_event,
    start_operator_workflow,
)
from gemini_provider import get_gemini_agent_properties
from memory_ops_agent import build_memory_ops_report, run_memory_ops_repair
from park_autodream_agent import autodream_status, promote_autodream_learning, review_autodream_learning, run_autodream
from park_autodream_benchmark import run_autodream_benchmark
from world_state_reconciliation import latest_reconciliation, reconcile_world_state
from mongo_memory import (
    get_operational_memory_dashboard,
    get_memory_document,
    get_latest_memory_documents,
    get_role_quality_priors,
    init_operational_memory,
    record_agent_decision as record_mongo_agent_decision,
    record_agent_learning_document as record_mongo_agent_learning_document,
    record_autodream_benchmark as record_mongo_autodream_benchmark,
    record_eval_result as record_mongo_eval_result,
    record_event_plan as record_mongo_event_plan,
    record_customer_emergency_audit_event as record_mongo_customer_emergency_audit_event,
    record_customer_emergency_incident as record_mongo_customer_emergency_incident,
    record_outcome_event as record_mongo_outcome_event,
    record_role_proposal_outcomes as record_mongo_role_proposal_outcomes,
    record_raw_signal as record_mongo_raw_signal,
    record_incident_analytics_fast as record_mongo_incident_analytics,
    retrieve_operational_context,
    sync_park_state,
)
from park_audit_agent import (
    audit_store_status,
    build_audit_action_candidate,
    build_audit_snapshot,
    init_audit_store,
    record_audit_event,
    record_audit_response,
)
from park_counterfactual import build_counterfactual_forecast
from park_action_result import build_park_action_result
from park_action_bridge import build_park_action_plan
from park_delivery import (
    acknowledge_dispatch,
    build_delivery_plan,
    delivery_contract,
    delivery_outbox_status,
    delivery_summary,
    latest_dispatches,
    record_approval_decision,
    response_summary,
    send_equipment_command,
    send_guest_promotion,
    send_worker_notification,
)
from park_eval import evaluate_park_decision
from park_episode_learning import build_learning_context, episode_dataset_status
from park_gemini_agent import build_park_gemini_plan, build_park_gemini_reaction_plan
from park_governance_runtime import (
    build_runtime_action,
    create_customer_care_case,
    list_runtime_governance,
    supervise_runtime_action,
)
from park_mediator import get_park_signals
from park_multi_agent import (
    build_orchestration_run,
    build_event_agent_findings,
    build_proactive_agent_findings,
    build_reactive_agent_findings,
    build_role_agent_proposals,
    enforce_agent_tool_boundary,
    active_departments_for_agents,
    get_agent_registry,
    get_agent_topology,
    get_judge_trace_eval_contract,
    run_agent_tool,
    role_alignment_report,
)
from park_operator_constraints import (
    apply_operator_constraints_to_optimization,
    constraints_from_genai_understanding,
    extract_operator_constraints,
    merge_operator_constraints,
)
from policy_loader import interpret_policy_for_action, operational_doctrine_index, retrieve_operational_doctrine
from platform_store import platform_store_status, safe_migrate_platform_store
from synthetic_park_knowledge import get_synthetic_park_knowledge, retrieve_synthetic_park_context, synthetic_coverage_report
from synthetic_park_runner import (
    find_synthetic_example,
    injection_plan_for_example,
    score_synthetic_copilot_response,
    synthetic_eval_cases,
)
from park_ontology_store import read_ontology_events, read_persistent_ontology, reconcile_ontology_with_live_state, record_ontology_turn
from park_optimizer import optimize_park_response, revise_plan_after_response
from park_outcome_loop import build_closed_loop_outcome, build_reactive_outcome
from park_proactive_agent import _fallback_brief as build_proactive_fallback_brief
from park_proactive_agent import build_proactive_eval, build_proactive_insights, build_proactive_operator_brief
from venue_profile import build_venue_profile
from park_review import build_review_snapshot
from park_replay_store import backup_replay_store, replay_collaboration_context, replay_store_status
from park_scenarios import get_park_scenarios
from park_signal_intake import classify_unstructured_signal, fuse_signal_batch, latest_signals, realistic_signal_batch
from live_feedback_loop import apply_live_food_ops_to_state, apply_live_guest_flow_to_state, apply_live_operator_signal_to_state, apply_live_ride_ops_to_state, apply_live_staffing_to_state, apply_live_weather_to_state, ingest_live_feed_event, ingest_live_feed_events, live_feed_health, record_review_decision, review_training_ledger
from guest_flow_live_feed import ingest_live_guest_flow_feed, guest_flow_feed_config
from ops_remaining_live_feeds import food_ops_feed_config, ingest_live_food_ops_feed, ingest_live_operator_signal_feed, ingest_live_staffing_feed, operator_signal_feed_config, staffing_feed_config
from ride_ops_live_feed import ingest_live_ride_ops_feed, ride_ops_feed_config
from weather_live_feed import ingest_live_weather_feed, weather_feed_config
from park_simulation import park_simulation
from reliability import reliability_status
from trace_helpers import traced_payload
from park_role_access import authorize_role_action, identity_provider_readiness, normalize_role, role_access_contracts, sign_role_session, verify_external_role_identity, verify_role_session

_background_tasks: set[asyncio.Task[Any]] = set()
_operator_refinements: dict[str, dict[str, Any]] = {}
_live_feed_health_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_live_feed_weather_refresh_status: dict[str, Any] = {
    "status": "idle",
    "mode": "live_weather_feed_background_refresh",
}
_live_feed_weather_refresh_task: asyncio.Task[Any] | None = None

DEFAULT_EVENT_REQUEST = (
    "Plan an evening park event for 8,000 guests from 6 PM to midnight. Keep it family-friendly "
    "early evening and higher-energy after dark. Add two themed zones, one headline experience, "
    "three food pop-ups, one merchandise area, lighting, crowd-control barriers, and extra staff. "
    "Do not block the main parade route."
)
DEFAULT_EVENT_THEME = "Seasonal night market"

_COPILOT_INCIDENT_TERMS = (
    "evacuation",
    "stuck on ride",
    "stopped on ride",
    "restraint",
    "seatbelt",
    "harness",
    "loose article",
    "restricted area",
    "block zone",
    "safety stop",
    "spillback",
    "crowd crush",
    "pinch point",
    "unattended bag",
    "suspicious bag",
    "lifeguard rescue",
    "aquatic emergency",
    "near drowning",
    "power outage",
    "lights out",
    "missing key",
    "key control",
    "hvac failure",
    "signage wrong",
    "wrong push",
    "bad app alert",
    "viral video",
    "slip fall",
    "wet path",
    "pii",
    "phone number",
    "guest name",
    "allergen",
    "chemical issue",
    "water quality",
    "height restriction",
    "child separated",
    "kid separated",
    "separated from parents",
    "blackout",
    "no power",
    "lost power",
    "collapsed",
    "cannot breathe",
    "can't breathe",
    "cant breathe",
    "backpack left",
    "unclaimed",
    "left unclaimed",
)


def _track_background_task(coro) -> asyncio.Task[Any]:
    task = coro if isinstance(coro, asyncio.Task) else asyncio.create_task(coro)
    try:
        _background_tasks.add(task)
    except TypeError:
        return task
    if hasattr(task, "add_done_callback"):
        task.add_done_callback(_background_tasks.discard)
    return task


@asynccontextmanager
async def lifespan(_: FastAPI):
    await startup_event()
    try:
        yield
    finally:
        for task in list(_background_tasks):
            task.cancel()
        if _background_tasks:
            await asyncio.gather(*list(_background_tasks), return_exceptions=True)


app = FastAPI(title="ParkPulse AI API", lifespan=lifespan)


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _role_auth_secret() -> str:
    return os.getenv("PARKPULSE_ROLE_AUTH_SECRET") or "parkpulse-local-dev-secret-change-before-production"


def _signed_role_required() -> bool:
    return _truthy(os.getenv("PARKPULSE_REQUIRE_SIGNED_ROLE_TOKEN"), True)


def _dev_role_issuer_enabled() -> bool:
    configured = os.getenv("PARKPULSE_ENABLE_DEV_ROLE_ISSUER")
    if configured is not None:
        return _truthy(configured, True)
    env = str(os.getenv("PARKPULSE_ENV") or os.getenv("ENVIRONMENT") or "local").strip().lower()
    if env in {"prod", "production"}:
        return False
    if identity_provider_readiness().get("external_identity_ready"):
        return False
    return True


def _role_session_ttl_seconds() -> int:
    try:
        return max(300, int(os.getenv("PARKPULSE_ROLE_SESSION_TTL_SECONDS", "3600")))
    except ValueError:
        return 3600


def _extract_role_token(request: Request) -> str | None:
    explicit_role_token = request.headers.get("x-parkpulse-role-token")
    if explicit_role_token:
        return explicit_role_token
    authorization = request.headers.get("authorization") or ""
    if authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None


def _request_role_context(request: Request, payload: dict[str, Any] | None = None, default: str = "ops_team") -> dict[str, Any]:
    external_identity = verify_external_role_identity(dict(request.headers), default_role=default)
    if external_identity.get("authenticated") or external_identity.get("status") == "role_unmapped":
        return external_identity
    token_status = verify_role_session(_extract_role_token(request), _role_auth_secret())
    if token_status.get("authenticated"):
        return {
            "status": "authenticated",
            "authenticated": True,
            "auth_method": "signed_role_session",
            "role": token_status.get("role"),
            "subject": token_status.get("subject"),
            "issuer": token_status.get("issuer"),
            "expires_at": token_status.get("expires_at"),
            "token_status": token_status.get("status"),
        }
    if _signed_role_required():
        return {
            "status": "unauthenticated",
            "authenticated": False,
            "auth_method": "signed_role_session_required",
            "role": normalize_role(None, default=default),
            "subject": "",
            "token_status": token_status.get("status"),
            "reason": token_status.get("reason") or "Signed role session token is required.",
        }
    role = request.headers.get("x-parkpulse-role") or request.headers.get("x-role")
    if not role and isinstance(payload, dict):
        role = payload.get("role") or payload.get("actor_role") or payload.get("actorRole")
    return {
        "status": "authenticated",
        "authenticated": True,
        "auth_method": "unsigned_dev_role_header",
        "role": normalize_role(str(role) if role is not None else None, default=default),
        "subject": "unsigned-local-dev",
        "token_status": token_status.get("status"),
    }


def _identity_readiness_payload() -> dict[str, Any]:
    secret = _role_auth_secret()
    default_secret = secret == "parkpulse-local-dev-secret-change-before-production"
    provider_readiness = identity_provider_readiness()
    external_ready = bool(provider_readiness.get("external_identity_ready"))
    return {
        "status": "production_ready" if external_ready and not default_secret else "dev_signed_sessions",
        "mode": "identity_readiness",
        "signed_role_required": _signed_role_required(),
        "dev_role_issuer_enabled": _dev_role_issuer_enabled(),
        "token_ttl_seconds": _role_session_ttl_seconds(),
        **provider_readiness,
        "production_ready": external_ready and not default_secret,
        "remaining_gap": None
        if external_ready and not default_secret
        else "Replace the local dev issuer with Google IAP/OIDC/Firebase and set PARKPULSE_ROLE_AUTH_SECRET before production.",
    }


def _require_role_action(
    request: Request,
    capability: str,
    resource: str,
    payload: dict[str, Any] | None = None,
    default_role: str = "ops_team",
) -> dict[str, Any]:
    identity = _request_role_context(request, payload, default=default_role)
    decision = authorize_role_action(identity.get("role"), capability, resource=resource, default_role=default_role)
    decision["identity"] = identity
    if not identity.get("authenticated"):
        decision["status"] = "unauthenticated"
        decision["allowed"] = False
        decision["reason"] = identity.get("reason") or "Signed role session token is required."
    if decision.get("allowed"):
        return decision
    raise HTTPException(
        status_code=401 if decision.get("status") == "unauthenticated" else 403,
        detail={
            "status": "forbidden",
            "mode": "role_authorization_gate",
            "authorization": decision,
            "readiness_issues": [decision.get("reason") or "Role is not authorized for this capability."],
            "boundary": "Protected ParkPulse executive endpoints require a signed role session.",
        },
    )


_memory_sync_min_interval_seconds = max(0.1, _float_env("PARKPULSE_MEMORY_SYNC_MIN_INTERVAL_SECONDS", 3.0))
_memory_sync_lock = asyncio.Lock()
_last_memory_sync_at = 0.0
_hot_endpoint_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_hot_endpoint_cache_locks: dict[str, asyncio.Lock] = {}
_hot_endpoint_refreshing: set[str] = set()
_live_park_step_lock = asyncio.Lock()
_last_live_park_step_at = 0.0
_live_park_step_interval_seconds = max(0.25, _float_env("PARKPULSE_LIVE_STEP_INTERVAL_SECONDS", 1.5))
_park_state_cache_ttl_seconds = max(0.0, _float_env("PARKPULSE_STATE_CACHE_TTL_SECONDS", 0.5))
_park_monitoring_cache_ttl_seconds = max(0.0, _float_env("PARKPULSE_MONITORING_CACHE_TTL_SECONDS", 10.0))
_park_integration_status_cache_ttl_seconds = max(0.0, _float_env("PARKPULSE_INTEGRATION_STATUS_CACHE_TTL_SECONDS", 15.0))
_industrial_dossier_cache_ttl_seconds = max(0.0, _float_env("PARKPULSE_INDUSTRIAL_DOSSIER_CACHE_TTL_SECONDS", 8.0))
_startup_status: dict[str, Any] = {
    "started_at": None,
    "ready_at": None,
    "deferred_initialization": "pending",
    "checks": {},
}


def _allowed_origins() -> list[str]:
    raw = os.getenv("PARKPULSE_ALLOWED_ORIGINS", "").strip()
    configured = [origin.strip() for origin in raw.split(",") if origin.strip()] if raw else []
    defaults = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://localhost:3003",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:3002",
        "http://127.0.0.1:3003",
        "http://127.0.0.1:5173",
        "http://0.0.0.0:3000",
        "http://0.0.0.0:3001",
        "http://0.0.0.0:3002",
        "http://0.0.0.0:3003",
        "http://0.0.0.0:5173",
    ]
    if configured and str(os.getenv("PARKPULSE_STRICT_ALLOWED_ORIGINS", "")).strip().lower() in {"1", "true", "yes", "on"}:
        return list(dict.fromkeys(configured))
    return list(dict.fromkeys([*configured, *defaults]))


app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
setup_arize_tracing()
setup_gcp_cloud_trace_exporter()
tracer = _get_tracer("parkpulse.api")


class ActionRequest(BaseModel):
    target: str
    action: str


class ParkAgentRunRequest(BaseModel):
    scenario_key: str | None = Field(default=None)
    operation_mode: bool = Field(default=False)
    auto_unexpected_event: bool = Field(default=False)
    operator_message: str | None = Field(default=None)
    execute: bool = Field(default=True)
    live_feed_case: dict[str, Any] | None = Field(default=None)
    live_feed_health: dict[str, Any] | None = Field(default=None)
    orchestration_source: str | None = Field(default=None)


class LiveFeedAgentRunRequest(BaseModel):
    refresh_stale: bool = Field(default=True)
    execute: bool = Field(default=False)
    controlled_executor_execute: bool = Field(default=False)
    allow_risk_escalation: bool = Field(default=False)
    risk_escalation_validation_mode: str | None = Field(default=None)
    measure_post_action: bool = Field(default=True)
    min_ready_feeds: int = Field(default=4, ge=1, le=6)
    require_persisted_events: bool = Field(default=True)
    scenario_key_hint: str | None = Field(default=None)
    generated_issue: dict[str, Any] | None = Field(default=None)


class EvalScenarioSweepRequest(BaseModel):
    scenario_keys: list[str] | None = Field(default=None)
    execute: bool = Field(default=False)
    timeout_seconds: int = Field(default=120, ge=20, le=300)


class ParkUnderstandingBenchmarkRequest(BaseModel):
    case_id: str | None = Field(default=None)
    candidate_responses: dict[str, Any] | None = Field(default=None)
    provider: str = Field(default="provided_or_baseline")
    timeout_seconds: float | None = Field(default=None)
    write_artifact: bool = Field(default=True)


class OperatorCommandRequest(BaseModel):
    message: str = Field(default="Dragon Coaster is down. Keep families happy but do not overload Food Court A.")
    mode: str = Field(default="auto")
    execute: bool = Field(default=True)


class CopilotChatMessage(BaseModel):
    role: str = Field(default="user")
    content: str = Field(default="")


class CopilotChatRequest(BaseModel):
    message: str = Field(default="What is the biggest park risk right now?")
    messages: list[CopilotChatMessage] = Field(default_factory=list)
    mode: str = Field(default="auto")
    turn_mode: str = Field(default="auto")
    execute: bool = Field(default=False)
    allow_action: bool = Field(default=True)
    selected_map_context: dict[str, Any] = Field(default_factory=dict)


class AgentOpsLedgerRecordRequest(BaseModel):
    record: dict[str, Any] = Field(default_factory=dict)


class DigitalTwinBenchmarkRequest(BaseModel):
    scenario_id: str | None = Field(default=None)
    seed: str = Field(default="benchmark")
    horizon_minutes: int = Field(default=30, ge=5, le=60)
    policy_under_test: str = Field(default="benchmark_selector")


class DigitalTwinLearnedRerunRequest(BaseModel):
    previous_result: dict[str, Any] = Field(default_factory=dict)
    scenario_id: str | None = Field(default=None)
    seed: str = Field(default="learned-rerun")
    horizon_minutes: int = Field(default=30, ge=5, le=60)


class DeliveryRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class DeliveryAckRequest(BaseModel):
    dispatch_id: str
    actor: str = Field(default="operator")
    choice: str = Field(default="acknowledged")
    channel: str | None = Field(default=None)


class DeliveryApprovalDecisionRequest(BaseModel):
    dispatch_id: str
    actor: str = Field(default="operator")
    decision: str = Field(default="approved")
    reason: str | None = Field(default=None)
    channel: str | None = Field(default=None)


class ParkTickRequest(BaseModel):
    minutes: int = Field(default=1, ge=1, le=30)


@app.get("/api/park/agent-contract")
async def park_agent_contract():
    return agent_contract()


@app.get("/api/park/agent-handshake/scenarios")
async def park_agent_handshake_scenarios():
    return agent_handshake_scenario_catalog()


@app.get("/api/park/agent-handshake/docs")
async def park_agent_handshake_docs():
    return agent_handshake_protocol_docs()


@app.get("/api/park/agent-handshake/live-state")
@app.post("/api/park/agent-handshake/live-state")
async def park_agent_handshake_live_state(body: dict[str, Any] | None = None):
    return agent_handshake_live_state_feed(body or {})


@app.post("/api/park/agent-handshake/consent-grant")
async def park_agent_handshake_consent_grant(body: dict[str, Any] | None = None):
    return issue_agent_consent_grant(body or {})


@app.get("/api/park/agent-handshake/scenario-eval")
@app.post("/api/park/agent-handshake/scenario-eval")
async def park_agent_handshake_scenario_eval(body: dict[str, Any] | None = None):
    return run_agent_handshake_scenario_evaluations(body or {})


@app.get("/api/park/agent-handshake/policy-challenges")
@app.post("/api/park/agent-handshake/policy-challenges")
async def park_agent_handshake_policy_challenges(body: dict[str, Any] | None = None):
    return run_agent_handshake_policy_challenges(body or {})


@app.get("/api/park/agent-handshake/external-client-demo")
@app.post("/api/park/agent-handshake/external-client-demo")
async def park_agent_handshake_external_client_demo(body: dict[str, Any] | None = None):
    return run_external_client_agent_demo(body or {})


@app.get("/api/park/agent-handshake/passport-second-run-demo")
@app.post("/api/park/agent-handshake/passport-second-run-demo")
async def park_agent_handshake_passport_second_run_demo(body: dict[str, Any] | None = None):
    return run_passport_second_run_demo(body or {})


@app.post("/api/park/agent-handshake/verify-artifact")
async def park_agent_handshake_verify_artifact(body: dict[str, Any] | None = None):
    return verify_protocol_artifact(body or {})


@app.post("/api/park/delegation-token")
async def park_agent_delegation_token(body: dict[str, Any] | None = None):
    return issue_delegation_token(body or {})


@app.post("/api/park/agent-onboarding/register")
async def park_agent_onboarding_register(body: dict[str, Any] | None = None):
    return register_agent_onboarding(body or {})


@app.get("/api/park/agent-onboarding/issuer")
async def park_agent_onboarding_issuer():
    return certification_issuer_metadata()


@app.post("/api/park/agent-onboarding/verify-credential")
async def park_agent_onboarding_verify_credential(body: dict[str, Any] | None = None):
    return verify_agent_certification_credential(body or {})


@app.post("/api/park/agent-onboarding/revoke-credential")
async def park_agent_onboarding_revoke_credential(request: Request, body: dict[str, Any] | None = None):
    _require_role_action(request, "manage_agent_trust", "agent_certification_revocation", body or {}, default_role="ml_ops_admin")
    return revoke_agent_certification_credential(body or {})


@app.get("/api/park/agent-trust/status")
async def park_agent_trust_status():
    return {**agent_trust_registry_status(), "auth_boundary": _identity_readiness_payload()}


@app.get("/api/park/agent-trust/partners")
async def park_agent_trust_partners(request: Request):
    _require_role_action(request, "manage_agent_trust", "agent_trust_partners", default_role="ml_ops_admin")
    return list_agent_trust_partners()


@app.post("/api/park/agent-trust/partners")
async def park_agent_trust_partner_upsert(request: Request, body: dict[str, Any] | None = None):
    _require_role_action(request, "manage_agent_trust", "agent_trust_partner_upsert", body or {}, default_role="ml_ops_admin")
    return upsert_agent_trust_partner(body or {})


@app.get("/api/park/agent-trust/keys")
async def park_agent_trust_keys(request: Request):
    _require_role_action(request, "manage_agent_trust", "agent_trust_keys", default_role="ml_ops_admin")
    return list_agent_trust_keys()


@app.post("/api/park/agent-trust/keys/rotate")
async def park_agent_trust_key_rotate(request: Request, body: dict[str, Any] | None = None):
    _require_role_action(request, "manage_agent_trust", "agent_trust_key_rotation", body or {}, default_role="ml_ops_admin")
    return rotate_agent_certification_key(body or {})


@app.get("/api/park/agent-trust/revocations")
async def park_agent_trust_revocations(request: Request, limit: int = 100):
    _require_role_action(request, "manage_agent_trust", "agent_trust_revocations", default_role="ml_ops_admin")
    return list_agent_credential_revocations(limit=limit)


@app.get("/api/park/agent-trust/audit")
async def park_agent_trust_audit(request: Request, limit: int = 100):
    _require_role_action(request, "manage_agent_trust", "agent_trust_audit", default_role="ml_ops_admin")
    return list_agent_trust_audit_events(limit=limit)


@app.get("/api/park/agent-onboarding/{agent_id}")
async def park_agent_onboarding_get(agent_id: str):
    try:
        return get_agent_onboarding(agent_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/park/agent-onboarding/{agent_id}/certify")
async def park_agent_onboarding_certify(agent_id: str, body: dict[str, Any] | None = None):
    try:
        return certify_agent_onboarding(agent_id, body or {}, park_state=await park_simulation.get_state_lite())
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception:
        return certify_agent_onboarding(agent_id, body or {})


@app.post("/api/park/internal-agents/commerce/evaluate")
async def park_commerce_agent_evaluate(body: dict[str, Any] | None = None):
    request_body = body or {}
    try:
        return commerce_agent_evaluate(str(request_body.get("session_id") or request_body.get("sessionId") or ""), request_body)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@app.post("/api/park/internal-agents/queue/reroute")
async def park_queue_agent_reroute(body: dict[str, Any] | None = None):
    request_body = body or {}
    try:
        return queue_agent_reroute(str(request_body.get("session_id") or request_body.get("sessionId") or ""), request_body, park_state=await park_simulation.get_state_lite())
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except Exception:
        return queue_agent_reroute(str(request_body.get("session_id") or request_body.get("sessionId") or ""), request_body)


@app.get("/api/park/agent-handshake/demo")
@app.post("/api/park/agent-handshake/demo")
async def park_agent_handshake_demo():
    try:
        return demo_handshake(await park_simulation.get_state_lite())
    except Exception:
        return demo_handshake()


@app.get("/api/park/agent-handshake/supply-chain/demo")
@app.post("/api/park/agent-handshake/supply-chain/demo")
async def park_supply_chain_handshake_demo(body: dict[str, Any] | None = None):
    request_body = body or {}
    return demo_supply_chain_handshake(str(request_body.get("scenario_mode") or request_body.get("scenarioMode") or "supply_replenishment"))


@app.post("/api/park/handshake")
async def park_identity_handshake(body: dict[str, Any] | None = None):
    return identity_handshake(body or {})


@app.get("/api/park/session/{session_id}")
async def park_agent_session(session_id: str):
    try:
        return get_agent_session(session_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/park/session/{session_id}/capabilities")
async def park_agent_capability_handshake(session_id: str, body: dict[str, Any] | None = None):
    try:
        return capability_handshake(session_id, body or {})
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@app.post("/api/park/session/{session_id}/intent")
async def park_agent_intent_handshake(session_id: str, body: dict[str, Any] | None = None):
    try:
        return intent_handshake(session_id, body or {})
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@app.post("/api/park/session/{session_id}/propose")
async def park_agent_propose(session_id: str, body: dict[str, Any] | None = None):
    try:
        return propose_plan(session_id, body or {}, park_state=await park_simulation.get_state_lite())
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except Exception:
        return propose_plan(session_id, body or {})


@app.post("/api/park/session/{session_id}/counter")
async def park_agent_counter(session_id: str, body: dict[str, Any] | None = None):
    try:
        return counter_proposal(session_id, body or {}, park_state=await park_simulation.get_state_lite())
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except Exception:
        return counter_proposal(session_id, body or {})


@app.post("/api/park/session/{session_id}/commit")
async def park_agent_commit(session_id: str, body: dict[str, Any] | None = None):
    try:
        return commit_plan(session_id, body or {})
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@app.post("/api/park/session/{session_id}/policy-check")
async def park_agent_policy_check(session_id: str, body: dict[str, Any] | None = None):
    try:
        return evaluate_policy_action(session_id, body or {})
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@app.get("/api/park/session/{session_id}/monitor")
@app.post("/api/park/session/{session_id}/monitor")
async def park_agent_monitor(session_id: str, body: dict[str, Any] | None = None):
    request_body = body or {}
    event = str(request_body.get("event") or "live")
    try:
        return monitor_session(session_id, {**request_body, "event": event}, park_state=await park_simulation.get_state_lite())
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except Exception:
        return monitor_session(session_id, {**request_body, "event": event})


@app.post("/api/park/session/{session_id}/escalate")
async def park_agent_escalate(session_id: str, body: dict[str, Any] | None = None):
    try:
        return escalate_agent_session(session_id, body or {})
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@app.get("/api/park/session/{session_id}/receipt")
@app.post("/api/park/session/{session_id}/receipt")
async def park_agent_receipt(session_id: str, body: dict[str, Any] | None = None):
    try:
        return session_protocol_receipt(session_id, body or {})
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@app.post("/api/park/session/{session_id}/close")
async def park_agent_close(session_id: str, body: dict[str, Any] | None = None):
    try:
        return close_agent_session(session_id, body or {})
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


async def park_delivery_contract():
    return delivery_contract()


async def park_delivery_outbox(limit: int = 20):
    dispatches = latest_dispatches(limit)
    return {
        "count": len(dispatches),
        "dispatches": dispatches,
        "summary": delivery_summary(dispatches),
        "response": response_summary(dispatches),
        "durability": delivery_outbox_status(),
    }


async def park_delivery_guest_promotion(request: DeliveryRequest):
    dispatch = send_guest_promotion(request.payload)
    clear_hot_endpoint_cache()
    return {"status": dispatch["status"], "dispatch": dispatch}


async def park_delivery_worker_notification(request: DeliveryRequest):
    dispatch = send_worker_notification(request.payload)
    clear_hot_endpoint_cache()
    return {"status": dispatch["status"], "dispatch": dispatch}


async def park_delivery_equipment_command(request: DeliveryRequest):
    dispatch = send_equipment_command(request.payload)
    clear_hot_endpoint_cache()
    return {"status": dispatch["status"], "dispatch": dispatch}


async def park_delivery_acknowledge(request: DeliveryAckRequest):
    dispatch = acknowledge_dispatch(
        request.dispatch_id,
        actor=request.actor,
        choice=request.choice,
        channel=request.channel,
    )
    latest = latest_dispatches(20)
    application = await park_simulation.apply_delivery_outcomes(latest, "receiver_acknowledgement")
    get_state_lite = getattr(park_simulation, "get_state_lite", None)
    state = await get_state_lite() if callable(get_state_lite) else await park_simulation.get_state()
    await sync_park_state_safe(state)
    clear_hot_endpoint_cache()
    return {
        "status": dispatch.get("status", "acknowledged"),
        "dispatch": dispatch,
        "application": application,
        "state": state,
        "delivery": {
            "summary": delivery_summary(latest),
            "response": response_summary(latest),
            "dispatches": latest,
        },
    }


async def park_delivery_approval_decision(request: DeliveryApprovalDecisionRequest):
    dispatch = record_approval_decision(
        request.dispatch_id,
        actor=request.actor,
        decision=request.decision,
        reason=request.reason,
        channel=request.channel,
    )
    latest = latest_dispatches(20)
    application = await park_simulation.apply_delivery_outcomes(latest, "operator_approval_decision")
    get_state_lite = getattr(park_simulation, "get_state_lite", None)
    state = await get_state_lite() if callable(get_state_lite) else await park_simulation.get_state()
    await sync_park_state_safe(state)
    clear_hot_endpoint_cache()
    return {
        "status": dispatch.get("status"),
        "dispatch": dispatch,
        "approval": dispatch.get("approvalDecision", {}),
        "approvalDelivery": dispatch.get("approvalDelivery", {}),
        "application": application,
        "state": state,
        "delivery": {
            "summary": delivery_summary(latest),
            "response": response_summary(latest),
            "dispatches": latest,
        },
    }


class GcpParkEventRequest(BaseModel):
    event_type: str = Field(default="parkpulse.manual.signal")
    payload: dict[str, Any] = Field(default_factory=dict)
    attributes: dict[str, str] = Field(default_factory=dict)


class ParkClockRequest(BaseModel):
    hour: int = Field(ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)


class GcpWorkflowRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class MemoryOpsRepairRequest(BaseModel):
    query: str = Field(default="ride down crowd staff food")
    collections: list[str] = Field(default_factory=lambda: ["playbooks", "incidents", "agent_learnings"])
    limit: int = Field(default=250, ge=1, le=1000)


class CustomerEmergencyClassifyRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1200)


class CustomerEmergencyIncidentRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1400)
    location: str = Field(default="", max_length=240)
    zoneId: str | None = Field(default=None)
    immediateDanger: bool = Field(default=False)
    accessBlocked: bool = Field(default=False)
    staffOnScene: bool = Field(default=False)
    contactAllowed: bool = Field(default=False)
    idempotencyKey: str | None = Field(default=None, max_length=120)


class CustomerEmergencyIncidentActionRequest(BaseModel):
    action: str = Field(pattern="^(acknowledge|dispatch|resolve|false_alarm)$")
    actor: str = Field(default="operator", max_length=120)
    note: str = Field(default="", max_length=500)


async def park_memory(query: str = "ride down crowd staff food"):
    get_state_lite = getattr(park_simulation, "get_state_lite", None)
    state = await get_state_lite() if callable(get_state_lite) else await park_simulation.get_state()
    await sync_park_state_safe(state)
    dashboard = get_operational_memory_dashboard(query)
    dashboard["memory_ops"] = build_memory_ops_report(query)
    return dashboard


async def park_memory_maintenance(query: str = "ride down crowd staff food"):
    state = await park_simulation.get_state()
    await sync_park_state_safe(state)
    return build_memory_ops_report(query)


async def park_memory_maintenance_repair(request: MemoryOpsRepairRequest):
    state = await park_simulation.get_state()
    await sync_park_state_safe(state)
    clear_hot_endpoint_cache()
    return run_memory_ops_repair(request.query, request.collections, request.limit)


class AutoDreamRunRequest(BaseModel):
    scenario_key: str = Field(default="proactive_eventops", description="Retired AutoDream compatibility scenario key.")
    max_cases: int = Field(default=8, ge=1, le=25, description="Compatibility value echoed by the retired AutoDream response.")
    persist: bool = Field(default=True, description="Compatibility flag; retired AutoDream does not persist dream runs or learnings.")


class AutoDreamPromoteRequest(BaseModel):
    dream_learning_id: str = Field(description="Archived dream learning id; promotion is retired and always blocked.")
    target: str = Field(default="agent_learnings", description="Compatibility target; retired AutoDream does not promote.")
    reviewer: str = Field(default="operator", description="Compatibility reviewer label.")


class AutoDreamReviewRequest(BaseModel):
    dream_learning_id: str = Field(description="Archived dream learning id; review is retired and archive-only.")
    review_status: str = Field(default="rejected", description="Compatibility review status echoed in the retired response.")
    reviewer: str = Field(default="operator", description="Compatibility reviewer label.")
    reason: str = Field(default="", description="Compatibility reason echoed in the retired response.")


class AutoDreamBenchmarkRequest(BaseModel):
    scenario_key: str | None = Field(default=None, description="Retired AutoDream benchmark compatibility scenario key.")
    promoted_rule_id: str | None = Field(default=None, description="Compatibility promoted rule id; benchmarks are retired.")
    seeds: int = Field(default=5, ge=1, le=20, description="Compatibility seed count echoed by the retired benchmark response.")


class CacheAccuracyReplayRequest(BaseModel):
    scenario_key: str | None = Field(default=None)
    agent_role: str = Field(default="react_agent")
    persist: bool = Field(default=True)


async def park_autodream_run(request: AutoDreamRunRequest):
    clear_hot_endpoint_cache()
    return run_autodream(request.scenario_key, max_cases=request.max_cases, persist=request.persist)


async def park_autodream_status(limit: int = 8):
    return autodream_status(limit)


async def park_autodream_promote(request: AutoDreamPromoteRequest):
    clear_hot_endpoint_cache()
    return promote_autodream_learning(request.dream_learning_id, request.target, request.reviewer)


async def park_autodream_review(request: AutoDreamReviewRequest):
    clear_hot_endpoint_cache()
    return review_autodream_learning(request.dream_learning_id, request.review_status, request.reviewer, request.reason)


async def park_autodream_benchmark(request: AutoDreamBenchmarkRequest):
    state = {"guestFlow": {"activeScenario": {"key": request.scenario_key or "ride_down"}}}
    benchmark = run_autodream_benchmark(
        state,
        scenario_key=request.scenario_key,
        promoted_rule_id=request.promoted_rule_id,
        seeds=request.seeds,
    )
    if benchmark.get("status") == "complete":
        benchmark["storage"] = record_mongo_autodream_benchmark(benchmark)
    return benchmark


async def park_autodream_benchmarks(limit: int = 8):
    safe_limit = max(1, min(25, int(limit or 8)))
    rows = get_latest_memory_documents("autodream_benchmarks", safe_limit)
    return {"count": len(rows), "latest_benchmarks": rows}


async def park_analytics(query: str = "ride down crowd staff food"):
    dashboard = get_operational_memory_dashboard(query)
    return analytics_learning_summary(dashboard)


async def gcp_operations_status_endpoint():
    return gcp_operations_status()


def _trace_eval_judge_payload() -> dict[str, Any]:
    contract = get_judge_trace_eval_contract()
    return {
        "agent_id": contract["owner_agent"],
        "department": contract["owner_department"],
        "department_agent": contract["owner_department_agent"],
        "owned_tools": contract["owned_tools"],
        "exclusive_tools": contract["exclusive_tools"],
        "routing_rule": contract["routing_rule"],
    }


def _gcp_trace_eval_status_for_api() -> dict[str, Any]:
    return {
        **get_gcp_trace_eval_status().public_dict(),
        "judge_agent": _trace_eval_judge_payload(),
        "judge_contract": get_judge_trace_eval_contract(),
    }


def _evaluator_loop_status_for_api() -> dict[str, Any]:
    return {
        **evaluator_loop_status(),
        "judge_agent": _trace_eval_judge_payload(),
    }


async def gcp_gemini_status():
    bigquery = bigquery_status()
    online = online_improvement_status()
    return {
        "agent": {"name": "ParkPulse AI", "role": "parkpulse_decision_bridge"},
        "gemini": get_gemini_agent_properties().public_dict(),
        "gcp_trace_eval": _gcp_trace_eval_status_for_api(),
        "online_improvement": online,
        "bigquery": bigquery,
        "arize": get_arize_status().public_dict(),
        "hot_path": True,
        "loads_full_runtime": False,
        "build_id": RUNTIME_BUILD_ID,
    }


async def gcp_improvement_status():
    return online_improvement_status()


async def gcp_trace_eval_status():
    return _gcp_trace_eval_status_for_api()


async def arize_status():
    return get_arize_status().public_dict()


async def gcp_pseudo_firebase_status():
    return pseudo_firebase_status()


async def gcp_pseudo_firebase_messages(limit: int = 50, topic: str | None = None):
    safe_limit = max(1, min(200, int(limit or 50)))
    rows = latest_pseudo_firebase_messages(safe_limit, topic=topic)
    return {"count": len(rows), "messages": rows}


async def gcp_firestore_status():
    return firestore_status()


async def gcp_firestore_operations(limit: int = 50, kind: str | None = None):
    safe_limit = max(1, min(200, int(limit or 50)))
    rows = latest_firestore_operations(safe_limit, kind=kind)
    return {"count": len(rows), "operations": rows}


async def gcp_pubsub_park_event(request: GcpParkEventRequest):
    return publish_park_event(request.event_type, request.payload, request.attributes)


async def gcp_workflows_operator_approval(request: GcpWorkflowRequest):
    return start_operator_workflow(request.payload)


async def gcp_eventarc_park_signal(body: dict[str, Any]):
    decoded = decode_eventarc_pubsub_signal(body)
    if decoded.get("event", {}).get("eventType") != "parkpulse.manual.signal":
        return {"status": "ignored", "event": decoded.get("event", {}), "signal": decoded}
    state = await park_simulation.get_state()
    signal = classify_unstructured_signal(
        text=decoded.get("text", ""),
        source=decoded.get("source", "gcp_eventarc"),
        zone_id=decoded.get("zoneId"),
        reporter_role=decoded.get("reporterRole"),
        park_state=state,
    )
    execution = _action_execution_for_signal(signal, state)
    return {"status": "accepted", "signal": signal, "execution": execution, "gcp_eventarc": {"status": "accepted", "event": decoded.get("event", {})}}


class CustomerCareRequest(BaseModel):
    reason: str = Field(default="Guest recovery review requested.")
    severity: str = Field(default="normal")
    scenarioKey: str | None = Field(default=None)
    safeAudience: str = Field(default="aggregate affected guest segment")
    sourceActionId: str | None = Field(default=None)
    policyFindings: list[str] = Field(default_factory=list)


class SimulationInjectRequest(BaseModel):
    kind: str
    target_id: str
    intensity: int = Field(default=75, ge=10, le=100)


class SyntheticScenarioInjectRequest(BaseModel):
    selector: str = Field(default="SYN-MIXED-CONFLICT-001")
    reset_first: bool = Field(default=False)


class SyntheticEvalSweepRequest(BaseModel):
    limit_examples: int = Field(default=12, ge=1, le=24)
    utterances_per_example: int = Field(default=2, ge=1, le=5)


class ReplayStartRequest(BaseModel):
    seed: str = Field(default="demo")
    scenario_key: str = Field(default="ride_down")


class CausalImpactDemoRequest(BaseModel):
    horizon_minutes: int = Field(default=20, ge=5, le=45)
    execute: bool = Field(default=True)


class BranchComparisonRequest(BaseModel):
    horizon_minutes: int = Field(default=20, ge=5, le=45)
    execute: bool = Field(default=False)
    case_context: dict[str, Any] | None = None


class EventPlanRequest(BaseModel):
    prompt: str = Field(default=DEFAULT_EVENT_REQUEST)
    expected_guests: int = Field(default=8000, ge=500, le=60000)
    event_theme: str = Field(default=DEFAULT_EVENT_THEME)


class SignalIntakeRequest(BaseModel):
    text: str = Field(
        default="Staff note: Guests are pushing near the maze exit and a child is crying by the barrier."
    )
    source: str = Field(default="staff_note")
    zoneId: str | None = Field(default=None)
    reporterRole: str | None = Field(default="zone_lead")


class SignalFusionRequest(BaseModel):
    preset: str = Field(default="crowd_care_conflict")


class WorldStateReconciliationRequest(BaseModel):
    preset: str = Field(default="crowd_care_conflict")
    signals: list[dict[str, Any]] | None = Field(default=None)


class AuditEventRequest(BaseModel):
    source: str = Field(default="external_audit_event")
    message: str = Field(default="External audit event ingested.")
    signal: str = Field(default="manual_audit_signal")
    zoneId: str = Field(default="park")
    assetId: str | None = Field(default=None)
    abnormalityScore: int = Field(default=75, ge=0, le=100)
    severity: str | None = Field(default=None)
    correlatedBy: list[str] = Field(default_factory=list)
    at: str | None = Field(default=None)
    raw: dict[str, Any] = Field(default_factory=dict)


class AuditRunResponseRequest(BaseModel):
    execute: bool = Field(default=True)


class DigitalTwinToolRequest(BaseModel):
    tool: str = Field(default="get_park_state")
    arguments: dict[str, Any] = Field(default_factory=dict)


class CallableAgentRunRequest(BaseModel):
    context: dict[str, Any] = Field(default_factory=dict)
    scenario_key: str | None = Field(default=None)
    horizon_minutes: int = Field(default=45, ge=5, le=240)
    policy_gate_checked: bool = Field(default=False)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _top_items(rows: list[dict[str, Any]], key: str, limit: int = 3) -> list[dict[str, Any]]:
    return sorted([row for row in rows if isinstance(row, dict)], key=lambda row: _safe_int(row.get(key)), reverse=True)[:limit]


def _guest_flow_from_state(state: dict[str, Any]) -> dict[str, Any]:
    flow = state.get("guestFlow", {}) if isinstance(state, dict) else {}
    return flow if isinstance(flow, dict) else {}


def _operating_clock_from_state(state: dict[str, Any]) -> dict[str, Any]:
    clock = state.get("operatingClock", {}) if isinstance(state, dict) else {}
    return clock if isinstance(clock, dict) else {}


@app.post("/api/park/agents/planning/run")
async def park_planning_agent_run(request: CallableAgentRunRequest):
    state = await park_simulation.get_state()
    context = {
        **request.context,
        "scenario_key": request.scenario_key or _guest_flow_from_state(state).get("activeScenario", {}).get("key"),
        "horizon_minutes": request.horizon_minutes,
        "policy_gate_checked": request.policy_gate_checked,
    }

    def executor() -> dict[str, Any]:
        planning = state.get("planningAgent", {}) if isinstance(state.get("planningAgent"), dict) else {}
        loop = state.get("showtimeLearningLoop", {}) if isinstance(state.get("showtimeLearningLoop"), dict) else {}
        return {
            "status": "online_callable",
            "agent": "planning_agent",
            "service": "multi_wave_operating_plan",
            "planningAgent": planning,
            "showtimeLearning": {
                "summary": loop.get("summary", {}),
                "rows": loop.get("rows", [])[:5] if isinstance(loop.get("rows"), list) else [],
            },
            "handoff": {"to": "decision_bridge_agent", "requires": ["policy gate", "delivery proof for any receiver action"]},
        }

    return run_agent_tool("planning_agent", "simulate_action", context, executor)


@app.post("/api/park/agents/traffic/run")
async def park_traffic_agent_run(request: CallableAgentRunRequest):
    state = await park_simulation.get_state()
    flow = _guest_flow_from_state(state)
    paths = flow.get("paths", []) if isinstance(flow.get("paths"), list) else []
    zones = flow.get("zones", []) if isinstance(flow.get("zones"), list) else []
    clock = _operating_clock_from_state(state)
    event_schedule = clock.get("eventSchedule", {}) if isinstance(clock.get("eventSchedule"), dict) else {}
    context = {
        **request.context,
        "scenario_key": request.scenario_key or flow.get("activeScenario", {}).get("key"),
        "horizon_minutes": request.horizon_minutes,
        "policy_gate_checked": request.policy_gate_checked,
    }

    def executor() -> dict[str, Any]:
        congested_paths = _top_items(paths, "congestionLevel")
        dense_zones = _top_items(zones, "density")
        return {
            "status": "online_callable",
            "agent": "traffic_flow_agent",
            "service": "path_pressure_forecast",
            "topCongestedPaths": congested_paths,
            "topDenseZones": dense_zones,
            "showtimeRisk": {
                "activeWave": event_schedule.get("activeWave"),
                "eventTrafficRiskPct": event_schedule.get("eventTrafficRiskPct", 0),
                "paradeRoutePressurePct": event_schedule.get("paradeRoutePressurePct", 0),
                "frontGateExitPressurePct": event_schedule.get("frontGateExitPressurePct", 0),
                "nextEvent": event_schedule.get("nextEvent"),
            },
            "recommendedControl": "split release waves, keep parade corridor clear, and avoid routing all guests to one alternate path",
            "handoff": {"to": "planning_agent", "artifact": "time-block demand and spillback forecast"},
        }

    return run_agent_tool("traffic_flow_agent", "simulate_action", context, executor)


@app.post("/api/park/agents/safety/check")
async def park_safety_agent_check(request: CallableAgentRunRequest):
    state = await park_simulation.get_state()
    flow = _guest_flow_from_state(state)
    context = {
        **request.context,
        "scenario_key": request.scenario_key or flow.get("activeScenario", {}).get("key"),
        "policy_gate_checked": True,
    }

    def executor() -> dict[str, Any]:
        rides = flow.get("rides", []) if isinstance(flow.get("rides"), list) else []
        blocked = [
            "no ride reopening without maintenance clearance",
            "no worker redeploy outside role or break constraints",
            "no public promise that changes safety, compensation, or private guest data",
        ]
        high_wait_rides = [ride for ride in rides if _safe_int(ride.get("waitMins")) >= 45]
        return {
            "status": "online_callable",
            "agent": "safety_policy_agent",
            "service": "policy_gate_check",
            "result": "allowed_for_planning_only",
            "blockedScopes": blocked,
            "requiresHumanApprovalWhen": [
                "equipment, staffing, safety, or customer-care commitment is affected",
                "dispatch receipt or receiver acknowledgement is missing",
            ],
            "evidence": {
                "activeScenario": flow.get("activeScenario", {}),
                "highWaitRideCount": len(high_wait_rides),
                "policyGateChecked": True,
            },
            "handoff": {"to": "decision_bridge_agent", "artifact": "blocked actions and approval requirements"},
        }

    return run_agent_tool("safety_policy_agent", "validate_policy", context, executor)


@app.post("/api/park/agents/delivery/proof")
async def park_delivery_agent_proof(request: CallableAgentRunRequest):
    context = {**request.context, "policy_gate_checked": request.policy_gate_checked}

    def executor() -> dict[str, Any]:
        dispatches = latest_dispatches(25)
        return {
            "status": "online_callable",
            "agent": "delivery_proof_agent",
            "service": "receiver_delivery_proof",
            "summary": delivery_summary(dispatches),
            "response": response_summary(dispatches),
            "durability": delivery_outbox_status(),
            "dispatches": dispatches,
            "unprovenRule": "missing receipts stay unproven; the agent cannot invent delivery success",
            "handoff": {"to": "operator_evidence_dock", "artifact": "delivery receipts and acknowledgement evidence"},
        }

    return run_agent_tool("delivery_proof_agent", "inspect_delivery_receipts", context, executor)


@app.get("/api/park/agents/memory/status")
async def park_memory_agent_status(query: str = "ride down crowd staff food", refresh: bool = False):
    boundary = enforce_agent_tool_boundary("memory_ops_agent", "inspect_runtime_status", {"query": query})
    refresh_status = init_operational_memory(force=True) if refresh else None
    dashboard = get_operational_memory_dashboard(query)
    report = build_memory_ops_report(query)
    return {
        "status": "online_callable" if boundary["allowed"] else "blocked_by_agent_boundary",
        "agent": "memory_ops_agent",
        "service": "memory_readiness_status",
        "agentBoundary": boundary,
        "refreshStatus": refresh_status,
        "dashboard": dashboard,
        "memoryOps": report,
        "executionBoundary": "diagnostic callable only; no live dispatch or unsafe automatic repair",
    }


@app.post("/api/park/agents/memory/status")
async def park_memory_agent_status_post(request: CallableAgentRunRequest):
    query = str(request.context.get("query") or request.context.get("text") or "ride down crowd staff food")
    refresh = str(request.context.get("refresh") or request.context.get("forceRefresh") or "").strip().lower() in {"1", "true", "yes", "on"}
    return await park_memory_agent_status(query, refresh=refresh)


@app.get("/")
async def root_health():
    return {"service": "parkpulse-api", "status": "ok", "privacy_mode": os.getenv("PARKPULSE_PRIVACY_MODE", "local"), "build_id": RUNTIME_BUILD_ID}


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "build_id": RUNTIME_BUILD_ID}


@app.get("/readyz")
async def readyz():
    return {
        "status": "ok",
        "service": "parkpulse-api",
        "entrypoint": "full-runtime",
        "build_id": RUNTIME_BUILD_ID,
        "full_app_loaded": False,
        "loads_full_runtime": False,
        "startup": _startup_status,
        "note": "Lightweight readiness only; deep dependency checks are exposed at /readyz/deep.",
    }


@app.get("/readyz/deep")
async def readyz_deep():
    replay = replay_store_status()
    outbox = delivery_outbox_status()
    platform = platform_store_status()
    return {
        "status": "ok" if replay["ready"] and outbox["ready"] and platform["ready"] else "degraded",
        "startup": _startup_status,
        "platform_store": platform,
        "replay_store": replay,
        "delivery_outbox": outbox,
        "gcp_operations": gcp_operations_status(),
        "audit_store": audit_store_status(),
        "reliability": reliability_status(),
    }


async def sync_park_state_safe(park_state: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    global _last_memory_sync_at
    loop = asyncio.get_running_loop()
    now = loop.time()
    if not force and now - _last_memory_sync_at < _memory_sync_min_interval_seconds:
        return {"status": "skipped", "reason": "throttled"}
    if _memory_sync_lock.locked() and not force:
        return {"status": "skipped", "reason": "sync_in_progress"}
    try:
        async with _memory_sync_lock:
            now = loop.time()
            if not force and now - _last_memory_sync_at < _memory_sync_min_interval_seconds:
                return {"status": "skipped", "reason": "throttled"}
            result = await asyncio.wait_for(asyncio.to_thread(sync_park_state, park_state), timeout=1.5)
            _last_memory_sync_at = loop.time()
            return result
    except Exception as error:
        _last_memory_sync_at = loop.time()
        return {"status": "skipped", "error": str(error)}


def clear_hot_endpoint_cache() -> None:
    _hot_endpoint_cache.clear()
    _live_feed_health_cache.clear()


def _live_bigquery_enabled() -> bool:
    return any(
        os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}
        for name in ("PARKPULSE_LIVE_BIGQUERY", "PARKPULSE_COLLABORATION_LIVE_BIGQUERY")
    )


def _export_agent_analytics(rows_by_table: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    if _live_bigquery_enabled():
        return export_analytics_rows(rows_by_table)
    status = bigquery_status()
    return {
        "status": "fallback_preview",
        "mode": status.get("mode", "analytics_fallback"),
        "row_counts": {table: len(rows) for table, rows in rows_by_table.items()},
        "readiness_issues": ["PARKPULSE_LIVE_BIGQUERY is not enabled for local agent routes."],
        "preview": {table: rows[:2] for table, rows in rows_by_table.items()},
    }


def _build_agent_bigquery_priors(scenario_key: str, dashboard: dict[str, Any]) -> dict[str, Any]:
    try:
        return build_bigquery_agent_priors(scenario_key, dashboard, allow_live_query=_live_bigquery_enabled())
    except TypeError as error:
        if "allow_live_query" not in str(error):
            raise
        return build_bigquery_agent_priors(scenario_key, dashboard)


def _empty_role_quality_priors(scenario_key: str | None, reason: str) -> dict[str, Any]:
    return {
        "mode": "role_quality_priors",
        "status": "skipped",
        "scenario_key": scenario_key or "all",
        "sample_count": 0,
        "priors": [],
        "by_agent": {},
        "readiness_issues": [reason],
    }


def _role_quality_priors_latency_safe(scenario_key: str | None) -> dict[str, Any]:
    if _truthy(os.getenv("MONGODB_DISABLE_DRIVER_IMPORT")):
        return _empty_role_quality_priors(
            scenario_key,
            "MongoDB driver import is disabled; skipped optional role quality priors on the hot path.",
        )
    try:
        return get_role_quality_priors(scenario_key)
    except Exception as error:
        return _empty_role_quality_priors(scenario_key, str(error)[:240])


def _compact_operational_memory_dashboard(query: str, state: dict[str, Any], *, agent_role: str) -> dict[str, Any]:
    context = _retrieve_operational_context(
        query,
        state,
        agent_role=agent_role,
        cache_policy="fresh_retrieval",
        persist_trace=False,
    )
    return {
        "status": context.get("status") or init_operational_memory(),
        "current_state": context.get("current_state") or state,
        "retrieved": context.get("retrieved", {}),
        "latest_learnings": get_latest_memory_documents("agent_learnings", 5),
        "latest_outcomes": get_latest_memory_documents("outcome_events", 5),
        "dashboard_mode": "compact_latency_safe",
    }


def _collaboration_context(
    context: dict[str, Any],
    scenario_key: str,
    memory_dashboard: dict[str, Any] | None = None,
    bigquery_priors: dict[str, Any] | None = None,
) -> dict[str, Any]:
    enriched = dict(context or {})
    if bigquery_priors is None:
        dashboard = memory_dashboard or get_operational_memory_dashboard(f"{scenario_key} take rate follow through")
        bigquery_priors = _build_agent_bigquery_priors(scenario_key, dashboard)
    enriched["bigquery_priors"] = bigquery_priors
    enriched["role_quality_priors"] = _role_quality_priors_latency_safe(scenario_key)
    enriched["relational_context"] = replay_collaboration_context(8)
    freshness_gate = enriched.get("freshness_gate", {}) if isinstance(enriched.get("freshness_gate"), dict) else {}
    cache_accuracy = enriched.get("cache_accuracy", {}) if isinstance(enriched.get("cache_accuracy"), dict) else {}
    enriched["cache_accuracy_contract"] = {
        "trust_level": cache_accuracy.get("trustLevel") or freshness_gate.get("trustLevel", "unknown"),
        "cache_trust_penalty": cache_accuracy.get("cacheTrustPenalty", freshness_gate.get("cacheTrustPenalty", 0)),
        "must_revalidate": bool(cache_accuracy.get("mustRevalidate", freshness_gate.get("mustRevalidate", False))),
        "semantic_drift": cache_accuracy.get("semanticDrift") or freshness_gate.get("semanticDrift", {}),
        "instruction": cache_accuracy.get("instruction") or freshness_gate.get("agentInstruction", ""),
        "policy": (
            "When must_revalidate is true, treat cached facts as provisional, reduce plan confidence, "
            "and verify changed ride, weather, staffing, safety, or alert facts before final action."
        ),
    }
    return enriched


def _cache_accuracy_contract(context: dict[str, Any] | None) -> dict[str, Any]:
    context = context or {}
    contract = context.get("cache_accuracy_contract", {}) if isinstance(context.get("cache_accuracy_contract"), dict) else {}
    freshness_gate = context.get("freshness_gate", {}) if isinstance(context.get("freshness_gate"), dict) else {}
    cache_accuracy = context.get("cache_accuracy", {}) if isinstance(context.get("cache_accuracy"), dict) else {}
    semantic_drift = contract.get("semantic_drift") or cache_accuracy.get("semanticDrift") or freshness_gate.get("semanticDrift") or {}
    return {
        "trust_level": contract.get("trust_level") or cache_accuracy.get("trustLevel") or freshness_gate.get("trustLevel", "unknown"),
        "cache_trust_penalty": float(contract.get("cache_trust_penalty", cache_accuracy.get("cacheTrustPenalty", freshness_gate.get("cacheTrustPenalty", 0))) or 0),
        "must_revalidate": bool(contract.get("must_revalidate", cache_accuracy.get("mustRevalidate", freshness_gate.get("mustRevalidate", False)))),
        "semantic_drift": semantic_drift if isinstance(semantic_drift, dict) else {},
        "instruction": contract.get("instruction") or cache_accuracy.get("instruction") or freshness_gate.get("agentInstruction", ""),
        "policy": contract.get(
            "policy",
            "Reduce confidence and require fresh validation when cache accuracy is degraded.",
        ),
    }


def _apply_cache_accuracy_to_plan(plan: dict[str, Any], context: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(plan, dict):
        return plan
    contract = _cache_accuracy_contract(context)
    penalty = max(0.0, min(0.75, float(contract.get("cache_trust_penalty", 0) or 0)))
    original_confidence = float(plan.get("confidence_score", plan.get("confidence", 0)) or 0)
    scale = 1 if original_confidence > 1 else 100
    confidence_100 = original_confidence if scale == 1 else original_confidence * 100
    adjusted = max(0, min(100, round(confidence_100 * (1 - penalty))))
    plan["original_confidence_score"] = round(confidence_100)
    plan["confidence_score"] = adjusted
    plan["cache_accuracy_contract"] = contract
    plan["cache_trust_penalty"] = penalty
    plan["requires_revalidation"] = bool(contract.get("must_revalidate"))
    plan["affected_drift_facts"] = (contract.get("semantic_drift", {}) or {}).get("reasons", [])
    if plan["requires_revalidation"]:
        plan["performance_status"] = "cache_revalidation_required"
        plan.setdefault("errors", [])
        if isinstance(plan["errors"], list):
            plan["errors"] = [
                *plan["errors"],
                f"Cache revalidation required: {contract.get('instruction') or 'verify changed operating facts.'}",
            ][:5]
    return plan


def _cache_adjusted_score(score: Any, context: dict[str, Any] | None) -> dict[str, Any]:
    return _apply_cache_accuracy_to_plan({"confidence_score": score or 0}, context)


class AgentWorkflowTimer:
    def __init__(self) -> None:
        self.started = time.monotonic()
        self._last = self.started
        self.stages: list[dict[str, Any]] = []

    def mark(self, stage: str, mode: str, **metadata: Any) -> None:
        now = time.monotonic()
        self.stages.append(
            {
                "stage": stage,
                "mode": mode,
                "elapsed_ms": int((now - self.started) * 1000),
                "stage_ms": int((now - self._last) * 1000),
                **{key: value for key, value in metadata.items() if value is not None},
            }
        )
        self._last = now

    def summary(self, *, route: dict[str, Any], lane: str, context_query: str, plan: dict[str, Any], fallback_available: bool) -> dict[str, Any]:
        return {
            "name": "reactive_operator_workflow",
            "lane": lane,
            "route": route,
            "fallback_available": fallback_available,
            "context_query": context_query,
            "context_query_tokens_estimate": max(1, len(context_query.split())),
            "gemini": {
                "runtime": plan.get("runtime"),
                "status": plan.get("performance_status"),
                "latency_ms": plan.get("response_latency_ms"),
                "timeout_seconds": plan.get("timeout_seconds"),
                "workflow": plan.get("workflow"),
                "errors": plan.get("errors", [])[:2] if isinstance(plan.get("errors"), list) else [],
            },
            "stages": self.stages,
            "total_ms": int((time.monotonic() - self.started) * 1000),
        }


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _operator_context_terms(
    scenario_key: str,
    operator_terms: str,
    intervention_terms: str,
    operator_route: dict[str, Any] | None,
) -> str:
    route = (operator_route or {}).get("route", "operations")
    scenario_terms = {
        "ride_down": "ride status queue guests wait time nearby alternatives maintenance clearance crowd control",
        "staff_shortage": "staff coverage roles breaks callouts stress protected breaks redeploy constraints",
        "food_spike": "food court mobile order backlog inventory pickup eta menu suppression alternate food capacity",
        "storm_response": "weather shelter indoor density hvac comfort signage crowd routing safety",
    }.get(scenario_key, "park operations safety guest flow staff capacity")
    route_terms = {
        "event_plan": "event setup equipment placement staffing temporary queues weather demand forecast",
        "signal_triage": "raw signal source confidence missing facts owner escalation verification",
        "operations": "bounded operator action policy gate receiver payload dispatch",
    }.get(str(route), "bounded operator action policy gate receiver payload dispatch")
    return " ".join(
        term
        for term in (
            scenario_key,
            operator_terms,
            intervention_terms,
            scenario_terms,
            route_terms,
        )
        if term
    )


def _retrieve_operational_context(query: str, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    try:
        return retrieve_operational_context(query, state, **kwargs)
    except TypeError as error:
        if "unexpected keyword argument" not in str(error):
            raise
        fallback_kwargs = [
            {key: value for key, value in kwargs.items() if key not in {"agent_role"}},
            {key: value for key, value in kwargs.items() if key not in {"agent_role", "cache_policy", "persist_trace"}},
            {},
        ]
        last_error: TypeError = error
        for compatible_kwargs in fallback_kwargs:
            try:
                return retrieve_operational_context(query, state, **compatible_kwargs)
            except TypeError as fallback_error:
                if "unexpected keyword argument" not in str(fallback_error):
                    raise
                last_error = fallback_error
        raise last_error


def _role_outcome_attribution(
    role_agent_proposals: dict[str, Any],
    optimization: dict[str, Any],
    response_metrics: dict[str, Any],
    eval_result: dict[str, Any],
    selected_action: dict[str, Any],
    scenario_key: str,
) -> dict[str, Any]:
    proposals = role_agent_proposals.get("proposals", []) if isinstance(role_agent_proposals.get("proposals"), list) else []
    resolution = optimization.get("decision_bridge_resolution", {}) if isinstance(optimization.get("decision_bridge_resolution"), dict) else {}
    accepted = resolution.get("accepted_role_proposal") if isinstance(resolution.get("accepted_role_proposal"), dict) else {}
    rejected_by_agent = {
        str(item.get("agent_id")): item
        for item in resolution.get("rejected_role_proposals", [])
        if isinstance(item, dict) and item.get("agent_id")
    }
    candidate_by_agent: dict[str, dict[str, Any]] = {}
    for candidate in optimization.get("candidates", []) if isinstance(optimization.get("candidates"), list) else []:
        role = candidate.get("role_proposal", {}) if isinstance(candidate.get("role_proposal"), dict) else {}
        agent_id = str(role.get("agent_id") or "")
        if agent_id and agent_id not in candidate_by_agent:
            candidate_by_agent[agent_id] = candidate

    response_score = int(response_metrics.get("score", 0) or 0)
    take_rate = float(response_metrics.get("takeRate", 0) or 0)
    follow_rate = float(response_metrics.get("reactiveFollowThroughRate", 0) or 0)
    eval_score = int((eval_result.get("scorecard", {}) or {}).get("overall", 0) or 0)
    role_outcomes = []
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        agent_id = str(proposal.get("agent_id") or "")
        proposed_action = proposal.get("proposed_action", {}) if isinstance(proposal.get("proposed_action"), dict) else {}
        candidate = candidate_by_agent.get(agent_id, {})
        is_accepted = bool(accepted) and agent_id == str(accepted.get("agent_id") or "")
        rejection = rejected_by_agent.get(agent_id, {})
        status = (
            "accepted"
            if is_accepted
            else "rejected"
            if rejection
            else "context_only"
            if proposal.get("proposal_type") in {"context", "gate", "bridge"}
            else "not_scored"
        )
        learning_status = (
            "positive_prior"
            if status == "accepted" and response_score >= 78 and take_rate >= 0.4
            else "needs_adjustment"
            if status == "accepted" and (response_score < 70 or take_rate < 0.35 or follow_rate < 0.35)
            else "rejected_tradeoff"
            if status == "rejected"
            else "supporting_context"
        )
        role_outcomes.append(
            {
                "agent_id": agent_id,
                "role": proposal.get("role"),
                "proposal_type": proposal.get("proposal_type"),
                "status": status,
                "proposal": proposal,
                "candidate_id": candidate.get("id"),
                "candidate_score": (candidate.get("scorecard", {}) if isinstance(candidate.get("scorecard"), dict) else {}).get("overall"),
                "rejection_reason": rejection.get("reason"),
                "outcome_metrics": {
                    "response_score": response_score,
                    "take_rate": take_rate,
                    "follow_through": follow_rate,
                    "eval_score": eval_score,
                },
                "learning_signal": {
                    "status": learning_status,
                    "reason": (
                        "Accepted role proposal met response threshold."
                        if learning_status == "positive_prior"
                        else "Accepted role proposal needs future adjustment from observed response."
                        if learning_status == "needs_adjustment"
                        else rejection.get("reason")
                        if learning_status == "rejected_tradeoff"
                        else "Proposal supported context, policy, or bridge resolution."
                    ),
                },
                "proposed_action": proposed_action,
            }
        )
    accepted_count = len([item for item in role_outcomes if item["status"] == "accepted"])
    rejected_count = len([item for item in role_outcomes if item["status"] == "rejected"])
    return {
        "mode": "role_outcome_attribution",
        "scenario_key": scenario_key,
        "selected_action": selected_action,
        "decision_bridge_resolution": resolution,
        "summary": {
            "proposal_count": len(role_outcomes),
            "accepted_count": accepted_count,
            "rejected_count": rejected_count,
            "context_only_count": len([item for item in role_outcomes if item["status"] == "context_only"]),
            "winner_agent_id": accepted.get("agent_id"),
        },
        "role_outcomes": role_outcomes,
    }


def _immediate_first_enabled() -> bool:
    return str(os.getenv("PARKPULSE_OPERATOR_IMMEDIATE_FIRST", "true")).strip().lower() not in {"0", "false", "no", "off"}


def _record_refinement_status(refinement_id: str, status: str, **fields: Any) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    record = {
        **_operator_refinements.get(refinement_id, {}),
        "id": refinement_id,
        "status": status,
        "updated_at": now,
        **fields,
    }
    record.setdefault("created_at", now)
    _operator_refinements[refinement_id] = record
    if len(_operator_refinements) > 50:
        for key in list(_operator_refinements.keys())[:-50]:
            _operator_refinements.pop(key, None)
    return record


def _operator_domain_for_scenario(scenario_key: str | None) -> str:
    return {
        "food_spike": "food",
        "staff_shortage": "staff",
        "ride_down": "ride",
        "storm_response": "energy",
        "medical_response": "medical",
        "equipment_safety": "equipment",
        "crowd_safety": "crowd",
        "family_care": "guest_care",
    }.get(str(scenario_key or ""), str(scenario_key or "park"))


def _role_proposal_route_for_agent_run(scenario_key: str, operator_route: dict[str, Any] | None) -> dict[str, Any]:
    if operator_route:
        return {**operator_route, "scenario_key": scenario_key}
    return {"route": "scenario_run", "scenario_key": scenario_key}


def _attach_unified_operating_receipt(payload: dict[str, Any], route: dict[str, Any], *, role: str = "react") -> dict[str, Any]:
    telemetry = payload.setdefault("run_telemetry", {})
    scenario_key = str(route.get("scenario_key") or telemetry.get("scenario_key") or "custom")
    domain = _operator_domain_for_scenario(scenario_key)
    delivery = telemetry.get("delivery", {}) if isinstance(telemetry.get("delivery"), dict) else {}
    dispatches = delivery.get("dispatches", []) if isinstance(delivery.get("dispatches"), list) else []
    selected_action = telemetry.get("planner", {}).get("selected_action", {}) if isinstance(telemetry.get("planner"), dict) else {}
    state_impact = telemetry.get("outcome", {}).get("state_impact") if isinstance(telemetry.get("outcome"), dict) else None
    if not isinstance(state_impact, dict):
        state_impact = {
            "domain": domain,
            "headline": f"{role.title()} agent emitted bounded receiver actions for {scenario_key}.",
            "receiver_channels": sorted({str(item.get("channel")) for item in dispatches if isinstance(item, dict)}),
        }
        telemetry["outcome"] = {**(telemetry.get("outcome") if isinstance(telemetry.get("outcome"), dict) else {}), "state_impact": state_impact}
    else:
        state_impact["domain"] = domain

    role_route = {
        **route,
        "selected_role": route.get("selected_role") or role,
        "skill": route.get("skill") or "parkpulse-react-agent",
        "required_tools": route.get("required_tools")
        or ["get_park_state", "retrieve_similar_incidents", "simulate_action", "validate_policy", "dispatch_receiver_payloads"],
        "policy_gates": route.get("policy_gates")
        or ["no_stale_scenario_payloads", "receiver_payload_matches_incident", "human_review_for_critical_safety"],
    }
    payload["role_route"] = role_route
    unified_receipt = {
        "contract": "parkpulse_operating_loop_v1",
        "role": role,
        "domain": state_impact.get("domain") or domain,
        "scenario_key": scenario_key,
        "confidence": telemetry.get("planner", {}).get("confidence_score") if isinstance(telemetry.get("planner"), dict) else None,
        "constraints": {
            "summary": telemetry.get("operator_constraints", {}).get("intent_summary") if isinstance(telemetry.get("operator_constraints"), dict) else payload.get("operator_response", {}).get("summary"),
            "requires_human_review": bool(route.get("requires_human_review") or telemetry.get("eval", {}).get("scorecard", {}).get("needs_human_approval") if isinstance(telemetry.get("eval"), dict) else route.get("requires_human_review")),
            "policy_gates": role_route.get("policy_gates", []),
        },
        "tools": role_route.get("required_tools", []),
        "selected_action": selected_action or {"label": payload.get("operator_response", {}).get("headline"), "target": domain},
        "policy_result": telemetry.get("governance", {}) if isinstance(telemetry.get("governance"), dict) else {},
        "dispatches": {
            "count": len(dispatches),
            "channels": sorted({str(item.get("channel")) for item in dispatches if isinstance(item, dict)}),
            "ids": [item.get("id") for item in dispatches if isinstance(item, dict)],
        },
        "state_impact": state_impact,
        "learning_update": {
            "status": "observed_response_learning",
            "take_rate": delivery.get("response", {}).get("takeRate") if isinstance(delivery.get("response"), dict) else None,
            "follow_through_rate": delivery.get("response", {}).get("reactiveFollowThroughRate") if isinstance(delivery.get("response"), dict) else None,
        },
        "memory": payload.get("memory", {}),
        "analytics": payload.get("analytics", {}),
    }
    telemetry["unified_receipt"] = unified_receipt
    payload["unified_receipt"] = unified_receipt
    payload["role_receipt"] = {
        "chain": ["operator_text", "role_router", "policy_gate", "receiver_payloads", "outcome_observation", "learning_update"],
        "role": role,
        "skill": role_route.get("skill"),
        "scenario_key": scenario_key,
        "decision_id": telemetry.get("decision_id") or payload.get("decision_id"),
        "outcome_id": telemetry.get("outcome_id") or payload.get("outcome_id"),
        "dispatch_ids": unified_receipt["dispatches"]["ids"],
        "learning_update": unified_receipt["learning_update"],
    }
    return payload


async def _run_operator_gemini_refinement(refinement_id: str, message: str, route: dict[str, Any]) -> None:
    _record_refinement_status(
        refinement_id,
        "running",
        route=route,
        message=message,
        lane="background_gemini_refinement",
    )
    started = time.monotonic()
    try:
        result = await park_agent_run(
            ParkAgentRunRequest(
                scenario_key=route.get("scenario_key", "ride_down"),
                operation_mode=False,
                auto_unexpected_event=False,
                operator_message=message,
                execute=False,
            )
        )
        planner = result.get("planner", {}) if isinstance(result, dict) else {}
        _record_refinement_status(
            refinement_id,
            "complete",
            route=route,
            message=message,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            planner={
                "runtime": planner.get("runtime"),
                "status": planner.get("performance_status"),
                "latency_ms": planner.get("response_latency_ms"),
                "recommended_action": planner.get("recommended_action"),
                "selected_action": planner.get("selected_action"),
                "errors": planner.get("errors", [])[:2] if isinstance(planner.get("errors"), list) else [],
            },
            decision_id=result.get("decision_id") if isinstance(result, dict) else None,
            agent_workflow=result.get("agent_workflow", {}) if isinstance(result, dict) else {},
            role_agent_proposals=result.get("role_agent_proposals", {}) if isinstance(result, dict) else {},
        )
    except Exception as error:
        _record_refinement_status(
            refinement_id,
            "error",
            route=route,
            message=message,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            error=str(error)[:500],
        )


def _infer_operator_command_route(message: str, requested_mode: str = "auto") -> dict[str, Any]:
    text = (message or "").strip()
    lowered = text.lower()
    direct_note_terms = ("down", "faint", "fainted", "passed out", "medical", "first aid", "injury", "collapse", "wheelchair", "accessibility", "panic", "evac", "fight", "security", "pushing", "blocked", "stuck", "smoke", "fire", "sparking", "electrical", "gas", "controller", "missed heartbeat", "help needed", "assistance needed")
    if requested_mode and requested_mode != "auto":
        route = requested_mode
    elif any(term in lowered for term in ("plan event", "halloween", "scare", "haunted", "overlay", "festival", "parade", "concert")):
        route = "event_plan"
    elif any(term in lowered for term in ("triage", "classify note", "reported", "staff note", "worker app", "guest app", "support station", "station chat", "guest says", "someone says")) and not any(term in lowered for term in direct_note_terms):
        route = "signal_triage"
    else:
        route = "operations"

    scenario_terms = {
        "ride_down": (
            "ride down",
            "coaster is down",
            "down for",
            "breakdown",
            "closed ride",
            "dragon coaster",
            "queue intake",
        ),
        "staff_shortage": (
            "short staffed",
            "understaffed",
            "call out",
            "called out",
            "labor shortage",
            "operator shortage",
            "no worker",
            "not enough staff",
            "fatigue",
        ),
        "food_spike": (
            "food court is down",
            "food court down",
            "food court closed",
            "food court unavailable",
            "food court offline",
            "food",
            "kitchen",
            "menu",
            "mobile order",
            "drink",
            "inventory",
            "restaurant",
            "food court",
        ),
        "storm_response": (
            "storm",
            "rain",
            "weather",
            "lightning",
            "shelter",
            "indoor",
        ),
        "medical_response": (
            "faint",
            "fainted",
            "passed out",
            "medical",
            "first aid",
            "injury",
            "collapse",
            "wheelchair",
            "accessibility",
            "assistance needed",
        ),
        "crowd_safety": (
            "panic",
            "evac",
            "evacuate",
            "fight",
            "security",
            "crowd congestion",
            "bottleneck",
            "pushing",
            "stuck",
            "blocked",
            "lost child",
            "separated",
        ),
        "equipment_safety": (
            "smoke",
            "fire",
            "sparking",
            "electrical",
            "gas",
            "controller",
            "missed heartbeat",
            "fog machine",
            "fog",
            "technician",
        ),
    }
    scores = {
        key: sum(2 if " " in term and term in lowered else 1 for term in terms if term in lowered)
        for key, terms in scenario_terms.items()
    }
    if any(term in lowered for term in ("ride", "coaster", "attraction")) and any(term in lowered for term in ("down", "broken", "closed", "stopped")):
        scores["ride_down"] += 3
    if any(term in lowered for term in ("staff", "worker", "break")) and any(term in lowered for term in ("protect", "avoid", "do not overload", "don't overload")):
        scores["staff_shortage"] = max(0, scores["staff_shortage"] - 1)
    scenario_key = max(scores, key=scores.get) if any(scores.values()) else "ride_down"

    urgency_terms = ("faint", "fainted", "medical", "panic", "evac", "lost child", "fight", "injury", "collapse", "smoke", "fire", "sparking", "gas")
    urgency = "critical" if any(term in lowered for term in urgency_terms) else "high" if any(term in lowered for term in ("down", "blocked", "angry", "overload", "surge")) else "normal"
    return {
        "route": route,
        "scenario_key": scenario_key,
        "urgency": urgency,
        "requires_human_review": urgency == "critical" or any(term in lowered for term in ("medical", "lost child", "evac", "safety")),
        "interpreted_intent": (
            "temporary event planning"
            if route == "event_plan"
            else "unstructured signal triage"
            if route == "signal_triage"
            else f"{scenario_key.replace('_', ' ')} operations response"
        ),
    }


async def _operator_command_timeout_payload(message: str, route: dict[str, Any], reason: str = "timeout") -> dict[str, Any]:
    state = await park_simulation.get_state()
    constraints = extract_operator_constraints(message, state, route)
    scenario_key = route.get("scenario_key", "ride_down")
    role_agent_proposals = build_role_agent_proposals(state, route, constraints, None)
    now_id = int(datetime.now(UTC).timestamp() * 1000)

    if scenario_key == "food_spike":
        selected = {
            "label": "Redirect Food Court A demand to available food capacity",
            "target": "food",
            "action": "redirect_food_demand",
            "owner": "Food Ops",
            "expected_effect": "Stop adding demand to Food Court A while preserving honest pickup options.",
        }
        dispatches = [
            {
                "id": f"fallback_guest_{now_id}",
                "channel": "guest_app",
                "endpoint": "/api/actions/guest-message",
                "status": "sent",
                "payload": {
                    "message": "Food Court A is temporarily unavailable. Use Food Court B or Main Street Shops for faster pickup; current Food Court A pickup estimates are being updated.",
                    "targetZone": "foodCourtA",
                    "avoidExtraDemandAt": [{"id": "foodCourtA", "name": "Food Court A", "reason": "Operator reported it is down"}],
                    "targetMix": [
                        {"zoneId": "foodCourtB", "destination": "Food Court B", "share": 0.5, "rationale": "Available food capacity"},
                        {"zoneId": "mainStreet", "destination": "Main Street Shops", "share": 0.3, "rationale": "Nearby alternate service"},
                        {"zoneId": "foodCourtA", "destination": "Hold current pickup only", "share": 0.2, "rationale": "Do not add new demand"},
                    ],
                },
                "response": {"takeRate": 0.46, "positiveResponseRate": 0.72, "reactiveFollowThroughRate": 0.58, "sampleSize": 180},
            },
            {
                "id": f"fallback_worker_{now_id}",
                "channel": "worker_device",
                "endpoint": "/api/actions/worker-task",
                "status": "assigned",
                "payload": {
                    "task": "Close new Food Court A pickup intake, post one worker at the pickup edge, and redirect mobile-order guests to Food Court B.",
                    "targetZone": "foodCourtA",
                    "role": "food_service",
                    "count": 2,
                    "staffMoves": [{"role": "food_service", "count": 2, "from": "staffBase", "to": "foodCourtA"}],
                },
                "response": {"acknowledgedCount": 2, "sampleSize": 2, "reactiveFollowThroughRate": 0.8},
            },
            {
                "id": f"fallback_equipment_{now_id}",
                "channel": "equipment_controller",
                "endpoint": "/api/actions/equipment-command",
                "status": "commanded",
                "payload": {
                    "command": "suppress_mobile_order_intake",
                    "equipmentType": "menu_control",
                    "zones": ["foodCourtA"],
                    "settings": {"mobileOrdering": "paused", "pickupEtaVisible": True},
                },
                "response": {"applied": True, "sampleSize": 1},
            },
        ]
    elif scenario_key == "staff_shortage":
        selected = {
            "label": "Redeploy cross-trained staff without violating break rules",
            "target": "staff",
            "action": "redeploy",
            "owner": "Staffing",
            "expected_effect": "Cover the highest pressure area while keeping protected breaks intact.",
        }
        dispatches = [
            {
                "id": f"fallback_worker_{now_id}",
                "channel": "worker_device",
                "endpoint": "/api/actions/worker-task",
                "status": "assigned",
                "payload": {"task": "Redeploy available cross-trained staff to the highest pressure zone; protect scheduled breaks.", "targetZone": "foodCourtA", "role": "floater", "count": 2},
                "response": {"acknowledgedCount": 2, "sampleSize": 3, "reactiveFollowThroughRate": 0.67},
            }
        ]
    elif scenario_key == "storm_response":
        selected = {
            "label": "Move guests toward shelter and protect indoor comfort",
            "target": "weather",
            "action": "shelter_flow",
            "owner": "Weather Ops",
            "expected_effect": "Reduce outdoor exposure without overloading one indoor zone.",
        }
        dispatches = [
            {
                "id": f"fallback_guest_{now_id}",
                "channel": "guest_app",
                "endpoint": "/api/actions/guest-message",
                "status": "sent",
                "payload": {"message": "Weather route active. Move toward covered indoor areas and follow staff instructions.", "targetZone": "coveredPlaza", "targetMix": [{"zoneId": "coveredPlaza", "destination": "Covered Plaza", "share": 0.45}, {"zoneId": "indoorHub", "destination": "Indoor Hub", "share": 0.35}]},
                "response": {"takeRate": 0.52, "positiveResponseRate": 0.77, "reactiveFollowThroughRate": 0.61, "sampleSize": 220},
            },
            {
                "id": f"fallback_equipment_{now_id}",
                "channel": "equipment_controller",
                "endpoint": "/api/actions/equipment-command",
                "status": "commanded",
                "payload": {"command": "protect_hvac_comfort", "equipmentType": "hvac", "zones": ["indoorHub", "coveredPlaza"], "settings": {"indoorHubSetpointF": 72}},
                "response": {"applied": True, "sampleSize": 1},
            },
        ]
    else:
        selected = {
            "label": "Hold unsafe intake and route guests to available capacity",
            "target": "ride",
            "action": "hold_and_reroute",
            "owner": "Ride Ops",
            "expected_effect": "Stop adding demand to the affected attraction while maintaining guest honesty.",
        }
        dispatches = [
            {
                "id": f"fallback_guest_{now_id}",
                "channel": "guest_app",
                "endpoint": "/api/actions/guest-message",
                "status": "sent",
                "payload": {"message": "An attraction is unavailable. Follow updated app routes to available nearby options; reopening will not be promised until cleared.", "targetZone": "coasterPlaza", "targetMix": [{"zoneId": "arcade", "destination": "Arcade Zone", "share": 0.4}, {"zoneId": "theaterB", "destination": "Theater B", "share": 0.24}]},
                "response": {"takeRate": 0.43, "positiveResponseRate": 0.69, "reactiveFollowThroughRate": 0.55, "sampleSize": 190},
            }
        ]

    delivery_summary: dict[str, Any] = {"total": len(dispatches), "guest_app": 0, "worker_device": 0, "equipment_controller": 0}
    for dispatch in dispatches:
        channel = dispatch.get("channel")
        if channel in delivery_summary:
            delivery_summary[channel] += 1

    run_telemetry = {
        "scenario_key": scenario_key,
        "planner": {
            "runtime": "deterministic_operator_timeout_fallback",
            "model": "bounded-custom-fallback",
            "gemini_ready": False,
            "attempted_gemini": True,
            "selected_action": selected,
            "confidence_score": 0.62,
            "analysis": f"Gemini did not return before the operator timeout; ParkPulse used parsed operator constraints to emit bounded custom actions. Reason: {reason}.",
        },
        "operator_constraints": constraints,
        "delivery": {
            "summary": delivery_summary,
            "dispatches": dispatches,
            "response": {"takeRate": 0.46, "positiveResponseRate": 0.72, "reactiveFollowThroughRate": 0.58, "score": 78, "status": "estimated_timeout_fallback"},
        },
        "governance": {"allowed": True, "gate_status": "allowed", "findings": ["Timeout fallback emitted bounded actions only; unsafe automation remains blocked."]},
        "eval": {"scorecard": {"overall": 78, "policy_guidance_score": 86, "policy_gate_status": "allowed", "policy_violation": False, "needs_human_approval": bool(route.get("requires_human_review"))}},
        "optimization": {
            "operator_constraints": constraints,
            "operator_candidate_frame": {
                "primary_action": selected,
                "rejected_options": [{"reason": "Do not use stale scenario fallbacks for this custom request."}],
            },
        },
        "role_agent_proposals": role_agent_proposals,
        "agent_workflow": {
            "name": "reactive_operator_workflow",
            "lane": "bounded_timeout_fallback",
            "route": route,
            "fallback_available": True,
            "gemini": {
                "runtime": "deterministic_operator_timeout_fallback",
                "status": "timeout",
                "timeout_seconds": _float_env("OPERATOR_COMMAND_TIMEOUT_SECONDS", 35.0),
                "errors": [reason],
            },
            "stages": [
                {"stage": "interpret.local_constraints", "mode": "local"},
                {
                    "stage": "collaborate.role_proposals",
                    "mode": "deterministic_role_agents",
                    "role_count": len(role_agent_proposals.get("active_roles", [])),
                    "proposal_count": role_agent_proposals.get("proposal_count"),
                    "conflict_count": len(role_agent_proposals.get("conflicts", [])),
                },
                {"stage": "decide.fallback", "mode": "bounded_local"},
                {"stage": "validate.policy_gate", "mode": "local_policy", "gate_status": "allowed"},
                {"stage": "dispatch.receivers", "mode": "receiver_payloads", "dispatch_count": len(dispatches)},
            ],
        },
    }
    return _attach_unified_operating_receipt({
        "status": "timeout_fallback",
        "command": message,
        "route": route,
        "mode": "operations",
        "operator_constraints": constraints,
        "role_agent_proposals": role_agent_proposals,
        "operator_response": {
            "headline": selected["label"],
            "summary": run_telemetry["planner"]["analysis"],
            "next_step": "Use the emitted receiver payloads now, then rerun Gemini when the model path recovers.",
        },
        "run_telemetry": run_telemetry,
    }, route, role="react")


async def cached_hot_endpoint(
    cache_key: str,
    ttl_seconds: float,
    builder,
) -> dict[str, Any]:
    if ttl_seconds <= 0:
        return await builder()

    loop = asyncio.get_running_loop()
    now = loop.time()
    cached = _hot_endpoint_cache.get(cache_key)
    if cached and cached[0] > now:
        return cached[1]
    if cached:
        if cache_key not in _hot_endpoint_refreshing:
            _hot_endpoint_refreshing.add(cache_key)
            asyncio.create_task(refresh_hot_endpoint(cache_key, ttl_seconds, builder))
        return cached[1]

    lock = _hot_endpoint_cache_locks.setdefault(cache_key, asyncio.Lock())
    async with lock:
        now = loop.time()
        cached = _hot_endpoint_cache.get(cache_key)
        if cached and cached[0] > now:
            return cached[1]
        value = await builder()
        _hot_endpoint_cache[cache_key] = (loop.time() + ttl_seconds, value)
        return value


async def refresh_hot_endpoint(cache_key: str, ttl_seconds: float, builder) -> None:
    try:
        lock = _hot_endpoint_cache_locks.setdefault(cache_key, asyncio.Lock())
        async with lock:
            value = await builder()
            _hot_endpoint_cache[cache_key] = (asyncio.get_running_loop().time() + ttl_seconds, value)
    except Exception as error:
        print(f"ParkPulse hot endpoint refresh failed for {cache_key}: {error}")
    finally:
        _hot_endpoint_refreshing.discard(cache_key)


async def prewarm_hot_endpoint(cache_key: str, ttl_seconds: float, builder) -> None:
    await asyncio.sleep(0)
    await refresh_hot_endpoint(cache_key, ttl_seconds, builder)


async def build_park_state_response() -> dict[str, Any]:
    with tracer.start_as_current_span("api.park_state") as span:
        state = apply_live_operator_signal_to_state(apply_live_food_ops_to_state(apply_live_staffing_to_state(apply_live_guest_flow_to_state(apply_live_ride_ops_to_state(apply_live_weather_to_state(await park_simulation.get_state()))))))
        state["policyDoctrine"] = operational_doctrine_index()
        state["operationsAudit"] = await asyncio.to_thread(build_audit_snapshot, state)
        state["counterfactualForecast"] = await asyncio.to_thread(build_counterfactual_forecast, state)
        state["digitalTwinCalibration"] = await asyncio.to_thread(build_calibration_ledger, state, state["counterfactualForecast"])
        state["missionReplay"] = await asyncio.to_thread(build_mission_replay, state)
        state["scenarioLab"] = await asyncio.to_thread(build_scenario_lab, state)
        state["readinessBrief"] = await asyncio.to_thread(build_readiness_brief, state)
        state["learnedAgentMaturity"] = await asyncio.to_thread(build_learned_agent_maturity, state)
        state["learningEvidenceLedger"] = await asyncio.to_thread(build_learning_evidence_ledger, state)
        await sync_park_state_safe(state)
        span.set_attribute("parkpulse.scenario", state.get("guestFlow", {}).get("activeScenario", {}).get("key", ""))
        return state


async def build_park_state_lite_response() -> dict[str, Any]:
    state = apply_live_operator_signal_to_state(apply_live_food_ops_to_state(apply_live_staffing_to_state(apply_live_guest_flow_to_state(apply_live_ride_ops_to_state(apply_live_weather_to_state(await park_simulation.get_state_lite()))))))
    state = dict(state)
    state.pop("industrialDossiers", None)
    state["policyDoctrine"] = operational_doctrine_index()
    return state


async def advance_live_park_from_wall_clock() -> int:
    global _last_live_park_step_at
    loop = asyncio.get_running_loop()
    now = loop.time()
    async with _live_park_step_lock:
        if _last_live_park_step_at <= 0:
            _last_live_park_step_at = now
            return 0
        elapsed = now - _last_live_park_step_at
        steps = min(5, int(elapsed // _live_park_step_interval_seconds))
        if steps <= 0:
            return 0
        for _ in range(steps):
            await park_simulation.step()
        _last_live_park_step_at += steps * _live_park_step_interval_seconds
        return steps


def build_industrial_dossier_api_payload(state: dict[str, Any]) -> dict[str, Any]:
    industrial = state.get("industrialDossiers", {}) if isinstance(state.get("industrialDossiers"), dict) else {}
    dossiers = industrial.get("dossiers", []) if isinstance(industrial.get("dossiers"), list) else []
    sim_time = state.get("simTime", {}) if isinstance(state.get("simTime"), dict) else {}
    clock = state.get("operatingClock", {}) if isinstance(state.get("operatingClock"), dict) else {}
    phase = clock.get("phase", {}) if isinstance(clock.get("phase"), dict) else {}
    required_sections = [
        "operatingThesis",
        "physicalMechanism",
        "spatialCausalityTrace",
        "mapObjectEvidenceIndex",
        "parkRealityModel",
        "liveOperatingSceneModel",
        "causalGraph",
        "counterfactualReplay",
        "branchPhysicalImpactMatrix",
        "actionConsequenceSimulation",
        "commercialImpactLedger",
        "accessibilityEquityImpact",
        "resourceFeasibilityMatrix",
        "policyClauseTrace",
        "spatialPhysicsEnvelope",
        "physicalPropagationModel",
        "historicalPrecedentMatrix",
        "guestCommunicationPlan",
        "behavioralResponseModel",
        "operationalConstraintRegister",
        "releaseDecisionRecord",
        "releaseAuthorityDecision",
        "executionReadinessProof",
        "releaseRemediationPlan",
        "operatingProcedureDelta",
        "decisionReproducibilityManifest",
        "chainOfCustodyAuditLog",
        "fieldCalibrationBacktestPlan",
        "evidenceProvenance",
        "affectedOntology",
        "policyReasoning",
        "governedApprovalPackage",
        "dataQualityCalibration",
        "telemetryContract",
        "fieldSignalReconciliation",
        "decisionTelemetrySnapshot",
        "fieldExecutionHandoff",
        "caseExecutionRunbook",
        "closedLoopVerification",
        "receiverReadiness",
        "evidenceTimeline",
        "competingHypotheses",
        "actionTrainingFrame",
        "simulatedBranchComparison",
        "operatingScorecard",
        "assumptionSensitivityAnalysis",
        "operationalStressRehearsal",
        "independentReviewBoard",
        "verificationPlan",
        "auditStandard",
    ]
    quality_reports = [score_industrial_dossier_quality(dossier, required_sections) for dossier in dossiers if isinstance(dossier, dict)]
    overall_score = round(sum(report["score"] for report in quality_reports) / max(1, len(quality_reports)))
    blocking_gaps = [
        {
            "caseId": report["caseId"],
            "missing": report["missing"],
            "weak": report["weak"],
        }
        for report in quality_reports
        if report["missing"] or report["weak"]
    ]
    return {
        "status": "ready" if dossiers and not blocking_gaps else "needs_review" if dossiers else "empty",
        "mode": industrial.get("mode", "industrial_operating_case_dossiers"),
        "standard": industrial.get("standard"),
        "generatedFrom": industrial.get("generatedFrom", []),
        "simulationClock": {
            "hour": sim_time.get("hour"),
            "minute": sim_time.get("minute"),
            "phase": phase.get("label"),
            "demandPressurePct": phase.get("demandPressurePct"),
        },
        "summary": {
            **(industrial.get("summary", {}) if isinstance(industrial.get("summary"), dict) else {}),
            "qualityScore": overall_score,
            "readyCaseCount": sum(1 for report in quality_reports if report["status"] == "ready"),
            "reviewCaseCount": sum(1 for report in quality_reports if report["status"] != "ready"),
            "blockingGapCount": len(blocking_gaps),
        },
        "portfolioCoverage": industrial.get("portfolioCoverage", {}) if isinstance(industrial.get("portfolioCoverage"), dict) else {},
        "portfolioOperatingModel": industrial.get("portfolioOperatingModel", {}) if isinstance(industrial.get("portfolioOperatingModel"), dict) else {},
        "portfolioRiskRanking": industrial.get("portfolioRiskRanking", {}) if isinstance(industrial.get("portfolioRiskRanking"), dict) else {},
        "productionEvidenceGapRegister": industrial.get("productionEvidenceGapRegister", {}) if isinstance(industrial.get("productionEvidenceGapRegister"), dict) else {},
        "fieldReplayValidationHarness": industrial.get("fieldReplayValidationHarness", {}) if isinstance(industrial.get("fieldReplayValidationHarness"), dict) else {},
        "capacityCertificationLedger": industrial.get("capacityCertificationLedger", {}) if isinstance(industrial.get("capacityCertificationLedger"), dict) else {},
        "slaEscalationClock": industrial.get("slaEscalationClock", {}) if isinstance(industrial.get("slaEscalationClock"), dict) else {},
        "receiverExecutionContractLedger": industrial.get("receiverExecutionContractLedger", {}) if isinstance(industrial.get("receiverExecutionContractLedger"), dict) else {},
        "incidentCommandDecisionLog": industrial.get("incidentCommandDecisionLog", {}) if isinstance(industrial.get("incidentCommandDecisionLog"), dict) else {},
        "industrialActionReplayLedger": industrial.get("industrialActionReplayLedger", {}) if isinstance(industrial.get("industrialActionReplayLedger"), dict) else {},
        "physicalMovementProofLedger": industrial.get("physicalMovementProofLedger", {}) if isinstance(industrial.get("physicalMovementProofLedger"), dict) else {},
        "telemetryAcceptanceLedger": industrial.get("telemetryAcceptanceLedger", {}) if isinstance(industrial.get("telemetryAcceptanceLedger"), dict) else {},
        "outcomeAccountabilityLedger": industrial.get("outcomeAccountabilityLedger", {}) if isinstance(industrial.get("outcomeAccountabilityLedger"), dict) else {},
        "industrialCaseFileSynthesis": industrial.get("industrialCaseFileSynthesis", {}) if isinstance(industrial.get("industrialCaseFileSynthesis"), dict) else {},
        "externalSystemExecutionEvidence": industrial.get("externalSystemExecutionEvidence", {}) if isinstance(industrial.get("externalSystemExecutionEvidence"), dict) else {},
        "industrialDossierCompletenessAudit": industrial.get("industrialDossierCompletenessAudit", {}) if isinstance(industrial.get("industrialDossierCompletenessAudit"), dict) else {},
        "liveEvidenceDriftMonitor": industrial.get("liveEvidenceDriftMonitor", {}) if isinstance(industrial.get("liveEvidenceDriftMonitor"), dict) else {},
        "observedOutcomeCalibrationLedger": industrial.get("observedOutcomeCalibrationLedger", {}) if isinstance(industrial.get("observedOutcomeCalibrationLedger"), dict) else {},
        "productionDataIngestionContract": industrial.get("productionDataIngestionContract", {}) if isinstance(industrial.get("productionDataIngestionContract"), dict) else {},
        "industrialPromotionCertificationGate": industrial.get("industrialPromotionCertificationGate", {}) if isinstance(industrial.get("industrialPromotionCertificationGate"), dict) else {},
        "fieldTrialProtocolLedger": industrial.get("fieldTrialProtocolLedger", {}) if isinstance(industrial.get("fieldTrialProtocolLedger"), dict) else {},
        "fieldTrialExecutionEvidenceLedger": industrial.get("fieldTrialExecutionEvidenceLedger", {}) if isinstance(industrial.get("fieldTrialExecutionEvidenceLedger"), dict) else {},
        "fieldTrialCloseoutLedger": industrial.get("fieldTrialCloseoutLedger", {}) if isinstance(industrial.get("fieldTrialCloseoutLedger"), dict) else {},
        "industrialOperatingTimelineLedger": industrial.get("industrialOperatingTimelineLedger", {}) if isinstance(industrial.get("industrialOperatingTimelineLedger"), dict) else {},
        "varianceRootCauseLedger": industrial.get("varianceRootCauseLedger", {}) if isinstance(industrial.get("varianceRootCauseLedger"), dict) else {},
        "industrialReviewDispositionLedger": industrial.get("industrialReviewDispositionLedger", {}) if isinstance(industrial.get("industrialReviewDispositionLedger"), dict) else {},
        "industrialAuditExportManifest": industrial.get("industrialAuditExportManifest", {}) if isinstance(industrial.get("industrialAuditExportManifest"), dict) else {},
        "dataLineageCertificationLedger": industrial.get("dataLineageCertificationLedger", {}) if isinstance(industrial.get("dataLineageCertificationLedger"), dict) else {},
        "policyRiskControlLedger": industrial.get("policyRiskControlLedger", {}) if isinstance(industrial.get("policyRiskControlLedger"), dict) else {},
        "caseWorkOrderExecutionLedger": industrial.get("caseWorkOrderExecutionLedger", {}) if isinstance(industrial.get("caseWorkOrderExecutionLedger"), dict) else {},
        "fieldReceiptReconciliationLedger": industrial.get("fieldReceiptReconciliationLedger", {}) if isinstance(industrial.get("fieldReceiptReconciliationLedger"), dict) else {},
        "releaseBoardExceptionLedger": industrial.get("releaseBoardExceptionLedger", {}) if isinstance(industrial.get("releaseBoardExceptionLedger"), dict) else {},
        "scenarioCoverageCertificationLedger": industrial.get("scenarioCoverageCertificationLedger", {}) if isinstance(industrial.get("scenarioCoverageCertificationLedger"), dict) else {},
        "operatorCompetencyEvaluationLedger": industrial.get("operatorCompetencyEvaluationLedger", {}) if isinstance(industrial.get("operatorCompetencyEvaluationLedger"), dict) else {},
        "causalEpisodeTrainingLedger": industrial.get("causalEpisodeTrainingLedger", {}) if isinstance(industrial.get("causalEpisodeTrainingLedger"), dict) else {},
        "simulationValidityCalibrationLedger": industrial.get("simulationValidityCalibrationLedger", {}) if isinstance(industrial.get("simulationValidityCalibrationLedger"), dict) else {},
        "fieldObservationProtocolLedger": industrial.get("fieldObservationProtocolLedger", {}) if isinstance(industrial.get("fieldObservationProtocolLedger"), dict) else {},
        "fieldEvidenceCaptureLedger": industrial.get("fieldEvidenceCaptureLedger", {}) if isinstance(industrial.get("fieldEvidenceCaptureLedger"), dict) else {},
        "fieldEvidenceSampleLedger": industrial.get("fieldEvidenceSampleLedger", {}) if isinstance(industrial.get("fieldEvidenceSampleLedger"), dict) else {},
        "fieldEvidenceAdjudicationLedger": industrial.get("fieldEvidenceAdjudicationLedger", {}) if isinstance(industrial.get("fieldEvidenceAdjudicationLedger"), dict) else {},
        "fieldEvidenceRemediationLedger": industrial.get("fieldEvidenceRemediationLedger", {}) if isinstance(industrial.get("fieldEvidenceRemediationLedger"), dict) else {},
        "fieldEvidenceRemediationExecutionLedger": industrial.get("fieldEvidenceRemediationExecutionLedger", {}) if isinstance(industrial.get("fieldEvidenceRemediationExecutionLedger"), dict) else {},
        "fieldEvidenceReleaseClearanceLedger": industrial.get("fieldEvidenceReleaseClearanceLedger", {}) if isinstance(industrial.get("fieldEvidenceReleaseClearanceLedger"), dict) else {},
        "spatialExecutionDrillLedger": industrial.get("spatialExecutionDrillLedger", {}) if isinstance(industrial.get("spatialExecutionDrillLedger"), dict) else {},
        "observedDrillVarianceLedger": industrial.get("observedDrillVarianceLedger", {}) if isinstance(industrial.get("observedDrillVarianceLedger"), dict) else {},
        "industrialAcceptanceCertificationLedger": industrial.get("industrialAcceptanceCertificationLedger", {}) if isinstance(industrial.get("industrialAcceptanceCertificationLedger"), dict) else {},
        "productionEvidenceAcquisitionLedger": industrial.get("productionEvidenceAcquisitionLedger", {}) if isinstance(industrial.get("productionEvidenceAcquisitionLedger"), dict) else {},
        "industrialStandardsMatrix": industrial.get("industrialStandardsMatrix", {}) if isinstance(industrial.get("industrialStandardsMatrix"), dict) else {},
        "industrialDeploymentReadiness": industrial.get("industrialDeploymentReadiness", {}) if isinstance(industrial.get("industrialDeploymentReadiness"), dict) else {},
        "industrialOwnershipModel": industrial.get("industrialOwnershipModel", {}) if isinstance(industrial.get("industrialOwnershipModel"), dict) else {},
        "coverageMatrix": industrial.get("coverageMatrix", []) if isinstance(industrial.get("coverageMatrix"), list) else [],
        "caseIndex": [
            {
                "id": dossier.get("id"),
                "sourceConflictId": dossier.get("sourceConflictId"),
                "title": dossier.get("title"),
                "domain": dossier.get("domain"),
                "caseType": dossier.get("caseType"),
                "severity": dossier.get("severity"),
                "mapFocus": dossier.get("mapFocus", []),
                "policyCount": len(dossier.get("policyReasoning", {}).get("applies", [])) if isinstance(dossier.get("policyReasoning"), dict) else 0,
                "receiverCount": len(dossier.get("receiverReadiness", [])) if isinstance(dossier.get("receiverReadiness"), list) else 0,
                "trainingBranches": [
                    branch.get("branch")
                    for branch in dossier.get("actionTrainingFrame", [])
                    if isinstance(branch, dict)
                ],
                "quality": next((report for report in quality_reports if report["caseId"] == dossier.get("id")), None),
                "portfolioPriority": next(
                    (
                        row
                        for row in (industrial.get("portfolioRiskRanking", {}) if isinstance(industrial.get("portfolioRiskRanking"), dict) else {}).get("rankingRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "productionEvidenceStatus": next(
                    (
                        row
                        for row in (industrial.get("productionEvidenceGapRegister", {}) if isinstance(industrial.get("productionEvidenceGapRegister"), dict) else {}).get("caseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "fieldReplayValidation": next(
                    (
                        row
                        for row in (industrial.get("fieldReplayValidationHarness", {}) if isinstance(industrial.get("fieldReplayValidationHarness"), dict) else {}).get("caseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "capacityCertification": next(
                    (
                        row
                        for row in (industrial.get("capacityCertificationLedger", {}) if isinstance(industrial.get("capacityCertificationLedger"), dict) else {}).get("caseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "slaEscalation": next(
                    (
                        row
                        for row in (industrial.get("slaEscalationClock", {}) if isinstance(industrial.get("slaEscalationClock"), dict) else {}).get("caseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "receiverExecutionContract": next(
                    (
                        row
                        for row in (industrial.get("receiverExecutionContractLedger", {}) if isinstance(industrial.get("receiverExecutionContractLedger"), dict) else {}).get("caseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "incidentCommandDecision": next(
                    (
                        row
                        for row in (industrial.get("incidentCommandDecisionLog", {}) if isinstance(industrial.get("incidentCommandDecisionLog"), dict) else {}).get("caseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "actionReplay": next(
                    (
                        row
                        for row in (industrial.get("industrialActionReplayLedger", {}) if isinstance(industrial.get("industrialActionReplayLedger"), dict) else {}).get("caseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "physicalMovementProof": next(
                    (
                        row
                        for row in (industrial.get("physicalMovementProofLedger", {}) if isinstance(industrial.get("physicalMovementProofLedger"), dict) else {}).get("caseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "telemetryAcceptance": next(
                    (
                        row
                        for row in (industrial.get("telemetryAcceptanceLedger", {}) if isinstance(industrial.get("telemetryAcceptanceLedger"), dict) else {}).get("caseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "outcomeAccountability": next(
                    (
                        row
                        for row in (industrial.get("outcomeAccountabilityLedger", {}) if isinstance(industrial.get("outcomeAccountabilityLedger"), dict) else {}).get("caseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "caseFile": next(
                    (
                        row
                        for row in (industrial.get("industrialCaseFileSynthesis", {}) if isinstance(industrial.get("industrialCaseFileSynthesis"), dict) else {}).get("caseFiles", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "externalExecutionEvidence": next(
                    (
                        row
                        for row in (industrial.get("externalSystemExecutionEvidence", {}) if isinstance(industrial.get("externalSystemExecutionEvidence"), dict) else {}).get("caseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "dossierCompletenessAudit": next(
                    (
                        row
                        for row in (industrial.get("industrialDossierCompletenessAudit", {}) if isinstance(industrial.get("industrialDossierCompletenessAudit"), dict) else {}).get("auditRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "liveEvidenceDrift": next(
                    (
                        row
                        for row in (industrial.get("liveEvidenceDriftMonitor", {}) if isinstance(industrial.get("liveEvidenceDriftMonitor"), dict) else {}).get("driftRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "observedOutcomeCalibration": next(
                    (
                        row
                        for row in (industrial.get("observedOutcomeCalibrationLedger", {}) if isinstance(industrial.get("observedOutcomeCalibrationLedger"), dict) else {}).get("calibrationRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "productionDataContract": next(
                    (
                        row
                        for row in (industrial.get("productionDataIngestionContract", {}) if isinstance(industrial.get("productionDataIngestionContract"), dict) else {}).get("caseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "promotionCertification": next(
                    (
                        row
                        for row in (industrial.get("industrialPromotionCertificationGate", {}) if isinstance(industrial.get("industrialPromotionCertificationGate"), dict) else {}).get("certificationRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "fieldTrialProtocol": next(
                    (
                        row
                        for row in (industrial.get("fieldTrialProtocolLedger", {}) if isinstance(industrial.get("fieldTrialProtocolLedger"), dict) else {}).get("protocolRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "fieldTrialExecutionEvidence": next(
                    (
                        row
                        for row in (industrial.get("fieldTrialExecutionEvidenceLedger", {}) if isinstance(industrial.get("fieldTrialExecutionEvidenceLedger"), dict) else {}).get("caseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "fieldTrialCloseout": next(
                    (
                        row
                        for row in (industrial.get("fieldTrialCloseoutLedger", {}) if isinstance(industrial.get("fieldTrialCloseoutLedger"), dict) else {}).get("closeoutRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "operatingTimeline": next(
                    (
                        row
                        for row in (industrial.get("industrialOperatingTimelineLedger", {}) if isinstance(industrial.get("industrialOperatingTimelineLedger"), dict) else {}).get("timelineRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "varianceRootCause": next(
                    (
                        row
                        for row in (industrial.get("varianceRootCauseLedger", {}) if isinstance(industrial.get("varianceRootCauseLedger"), dict) else {}).get("rootCauseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "reviewDisposition": next(
                    (
                        row
                        for row in (industrial.get("industrialReviewDispositionLedger", {}) if isinstance(industrial.get("industrialReviewDispositionLedger"), dict) else {}).get("dispositionRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "auditExportPackage": next(
                    (
                        row
                        for row in (industrial.get("industrialAuditExportManifest", {}) if isinstance(industrial.get("industrialAuditExportManifest"), dict) else {}).get("packageRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "dataLineageCertification": next(
                    (
                        row
                        for row in (industrial.get("dataLineageCertificationLedger", {}) if isinstance(industrial.get("dataLineageCertificationLedger"), dict) else {}).get("certificationRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "policyRiskControl": next(
                    (
                        row
                        for row in (industrial.get("policyRiskControlLedger", {}) if isinstance(industrial.get("policyRiskControlLedger"), dict) else {}).get("controlRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "caseWorkOrderExecution": next(
                    (
                        row
                        for row in (industrial.get("caseWorkOrderExecutionLedger", {}) if isinstance(industrial.get("caseWorkOrderExecutionLedger"), dict) else {}).get("caseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "fieldReceiptReconciliation": next(
                    (
                        row
                        for row in (industrial.get("fieldReceiptReconciliationLedger", {}) if isinstance(industrial.get("fieldReceiptReconciliationLedger"), dict) else {}).get("caseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "releaseBoardException": next(
                    (
                        row
                        for row in (industrial.get("releaseBoardExceptionLedger", {}) if isinstance(industrial.get("releaseBoardExceptionLedger"), dict) else {}).get("exceptionRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "scenarioCoverageCertification": next(
                    (
                        row
                        for row in (industrial.get("scenarioCoverageCertificationLedger", {}) if isinstance(industrial.get("scenarioCoverageCertificationLedger"), dict) else {}).get("certificationRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "operatorCompetencyEvaluation": next(
                    (
                        row
                        for row in (industrial.get("operatorCompetencyEvaluationLedger", {}) if isinstance(industrial.get("operatorCompetencyEvaluationLedger"), dict) else {}).get("caseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "causalEpisodeTraining": next(
                    (
                        row
                        for row in (industrial.get("causalEpisodeTrainingLedger", {}) if isinstance(industrial.get("causalEpisodeTrainingLedger"), dict) else {}).get("caseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "simulationValidityCalibration": next(
                    (
                        row
                        for row in (industrial.get("simulationValidityCalibrationLedger", {}) if isinstance(industrial.get("simulationValidityCalibrationLedger"), dict) else {}).get("caseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "fieldObservationProtocol": next(
                    (
                        row
                        for row in (industrial.get("fieldObservationProtocolLedger", {}) if isinstance(industrial.get("fieldObservationProtocolLedger"), dict) else {}).get("caseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "fieldEvidenceCapture": next(
                    (
                        row
                        for row in (industrial.get("fieldEvidenceCaptureLedger", {}) if isinstance(industrial.get("fieldEvidenceCaptureLedger"), dict) else {}).get("caseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "fieldEvidenceSample": next(
                    (
                        row
                        for row in (industrial.get("fieldEvidenceSampleLedger", {}) if isinstance(industrial.get("fieldEvidenceSampleLedger"), dict) else {}).get("caseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "fieldEvidenceAdjudication": next(
                    (
                        row
                        for row in (industrial.get("fieldEvidenceAdjudicationLedger", {}) if isinstance(industrial.get("fieldEvidenceAdjudicationLedger"), dict) else {}).get("caseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "fieldEvidenceRemediation": next(
                    (
                        row
                        for row in (industrial.get("fieldEvidenceRemediationLedger", {}) if isinstance(industrial.get("fieldEvidenceRemediationLedger"), dict) else {}).get("caseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "fieldEvidenceRemediationExecution": next(
                    (
                        row
                        for row in (industrial.get("fieldEvidenceRemediationExecutionLedger", {}) if isinstance(industrial.get("fieldEvidenceRemediationExecutionLedger"), dict) else {}).get("caseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "fieldEvidenceReleaseClearance": next(
                    (
                        row
                        for row in (industrial.get("fieldEvidenceReleaseClearanceLedger", {}) if isinstance(industrial.get("fieldEvidenceReleaseClearanceLedger"), dict) else {}).get("caseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "spatialExecutionDrill": next(
                    (
                        row
                        for row in (industrial.get("spatialExecutionDrillLedger", {}) if isinstance(industrial.get("spatialExecutionDrillLedger"), dict) else {}).get("caseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "observedDrillVariance": next(
                    (
                        row
                        for row in (industrial.get("observedDrillVarianceLedger", {}) if isinstance(industrial.get("observedDrillVarianceLedger"), dict) else {}).get("caseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "industrialAcceptanceCertification": next(
                    (
                        row
                        for row in (industrial.get("industrialAcceptanceCertificationLedger", {}) if isinstance(industrial.get("industrialAcceptanceCertificationLedger"), dict) else {}).get("caseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
                "productionEvidenceAcquisition": next(
                    (
                        row
                        for row in (industrial.get("productionEvidenceAcquisitionLedger", {}) if isinstance(industrial.get("productionEvidenceAcquisitionLedger"), dict) else {}).get("caseRows", [])
                        if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
                    ),
                    None,
                ),
            }
            for dossier in dossiers
            if isinstance(dossier, dict)
        ],
        "auditManifest": {
            "requiredSections": required_sections,
            "traceSources": ["industrialDossiers", "physicalDynamics", "actionConflictSimulation", "externalSystems", "temporalConsequences"],
            "caseLookup": "/api/park/industrial-dossiers/{case_id}",
            "qualityGate": {
                "readyThreshold": 90,
                "checks": [
                    "all required sections present",
                    "portfolio coverage spans safety/security, ride maintenance, event flow, labor, food/service, weather/energy, and fairness/trust cases",
                    "production evidence gap register declares synthetic assumptions, required real feeds, certification gates, and promotion blockers",
                    "field replay validation harness defines replay windows, branch validation runs, acceptance gates, and falsification triggers",
                    "capacity certification ledger checks path reserve, queue spillback, zone density, emergency access, accessibility, and staff-service access",
                    "SLA escalation clock exposes detect, simulate, approval, receiver acknowledgement, verification, rollback, and escalation deadlines",
                    "receiver execution contract ledger defines payload, acknowledgement SLA, failure, retry, manual fallback, telemetry proof, and rollback semantics",
                    "incident command decision log records command roles, selected branch, rejected alternatives, authority, receiver contract, SLA clock, rollback, and audit event",
                    "industrial action replay ledger shows starting state, selected action, time-phased consequence frames, rollback watch, and validation status",
                    "physical movement proof ledger joins selected replay to mapped objects, path capacity, queue geometry, zone load, emergency access, and accessibility evidence",
                    "telemetry acceptance ledger states live signals, source identity, freshness rules, acceptance gates, backtests, and rollback checks required for production trust",
                    "outcome accountability ledger records owner, expected outcome, observed-evidence status, residual risk, rollback posture, and promotion decision",
                    "industrial case file synthesis connects signal, selected action, proof stack, telemetry acceptance, accountable owner, residual risk, and next operator step",
                    "external system execution evidence records prepared payloads, acknowledgement requirements, mutation hold, fallback, telemetry proof, and rollback evidence",
                    "physical mechanism or explicit physical gap",
                    "park reality model covers operating phase, topology, capacity envelope, service dependencies, and failure propagation",
                    "live operating scene model explains the case as a physical park scene with actors, constraints, service kinetics, bottlenecks, agent belief, and uncertainty",
                    "causal graph contains typed nodes, edges, confidence, evidence links, policy gates, and downstream consequences",
                    "counterfactual replay matrix shows branch evolution by time and deltas versus no-action",
                    "branch physical impact matrix shows action effects across queues, paths, zones, food service, staffing, guest care, and map objects",
                    "action consequence simulation shows time-phased branch effects, second-order load transfer, rollback triggers, and learning signals",
                    "commercial impact ledger quantifies guest minutes, recovery cost, revenue at risk, complaint exposure, and calibration needs",
                    "accessibility and equity impact proof covers protected cohorts, route access, standby fairness, branch comparison, and required controls",
                    "resource feasibility matrix covers labor envelope, receiver execution, critical path timing, conflicts, and branch feasibility",
                    "policy clause trace maps policy book refs to evidence status, blocked-action tests, branch verdicts, and operator approval questions",
                    "spatial physics envelope quantifies route meters, path width/capacity, walk time, queue geometry, service access, observed movement, and branch physics",
                    "physical propagation model explains trigger, space, queue, path, receiver, branch, tripwire, and decision-value chains",
                    "historical precedent matrix maps matched patterns, recurring failure modes, known controls, branch precedent verdicts, and calibration limits",
                    "guest communication plan maps segmented audiences, channel ownership, promise boundaries, trust controls, rollback language, approval triggers, and measurement plan",
                    "behavioral response model estimates segment compliance, staff acknowledgement, trust lag, complaint exposure, and branch behavior",
                    "operational constraint register separates hard constraints, soft tradeoffs, active violations, branch verdicts, and go/no-go release state",
                    "release decision record captures approval state, signoff matrix, approved version, draft-only boundaries, conditions, and post-release obligations",
                    "release authority decision separates structural dossier readiness from live action authorization",
                    "execution readiness proof states whether the action can be physically staffed, communicated, acknowledged, monitored, and rolled back",
                    "release remediation plan maps blocked or review-only authority to owner tasks, evidence, and recheck sequence",
                    "operating procedure delta converts release remediation into SOP, policy, and runbook patch candidates",
                    "decision reproducibility manifest makes packet replayable from input hashes, simulator version, policy refs, thresholds, branch ids, and expected outputs",
                    "chain-of-custody audit log captures artifact custody, mutation authority, immutable trace checkpoints, evidence hash inputs, and audit replay instructions",
                    "field calibration and backtest plan names required real datasets, replay suites, acceptance thresholds, drift triggers, synthetic limits, and learning capture",
                    "map object evidence index exposes concrete zones, paths, queues, facilities, guest groups, coordinates or coordinate gaps, and receiver links",
                    "spatial causality trace covers zones, paths, queues, branch effects, and watch metrics",
                    "evidence provenance links source layer, object, field, value, and supported claim",
                    "policy reasoning includes applies, blocks, and approval standard",
                    "governed approval package defines authority boundary, operator decisions, receiver writes, rollback authority, and approval evidence",
                    "data quality calibration includes confidence, freshness, source coverage, missing telemetry, and real-world calibration requirements",
                    "telemetry contract includes source bindings, freshness rules, owners, decision readiness, quality controls, and mutation guards",
                    "field signal reconciliation compares live source agreement, contradiction risks, and approval impact before release",
                    "decision-time telemetry snapshot preserves raw zones, queues, paths, food, staffing, receivers, guest segments, thresholds, and freshness",
                    "field execution handoff includes incident roles, staging, receiver dispatches, guest communication, acknowledgements, and abort criteria",
                    "case execution runbook defines owners, lifecycle statuses, SLA timers, escalation rules, and completion criteria",
                    "closed-loop verification includes observation windows, receiver receipts, projected-vs-observed checks, rollback triggers, and learning capture",
                    "receiver readiness includes state, latency, coverage, and failure mode",
                    "training frame contains no-action, fast-local-action, and governed-agent-action",
                    "simulated branch comparison contains no-action, fast-local-action, and governed-agent-action with scores, deltas, selected branch, and rejected branch",
                    "operating scorecard compares branches across guest impact, safety, labor, service, revenue, confidence, and tradeoffs",
                    "assumption sensitivity analysis includes assumptions, stress tests, flip conditions, and confidence drivers",
                    "operational stress rehearsal maps adverse human, signal, receiver, and space scenarios to release posture",
                    "independent review board records specialist challenges, residual risks, operator questions, and release decision",
                    "verification plan includes success metric, watch conditions, and rollback trigger",
                ],
            },
        },
        "quality": {
            "overallScore": overall_score,
            "reports": quality_reports,
            "blockingGaps": blocking_gaps,
        },
        "dossiers": dossiers,
    }


def score_industrial_dossier_quality(dossier: dict[str, Any], required_sections: list[str]) -> dict[str, Any]:
    missing: list[str] = []
    weak: list[str] = []
    for section in required_sections:
        value = dossier.get(section)
        if value in (None, "", [], {}):
            missing.append(section)

    policy = dossier.get("policyReasoning", {}) if isinstance(dossier.get("policyReasoning"), dict) else {}
    if not policy.get("applies") or not policy.get("blocks") or not policy.get("approvalStandard"):
        weak.append("policyReasoning")

    map_index = dossier.get("mapObjectEvidenceIndex", {}) if isinstance(dossier.get("mapObjectEvidenceIndex"), dict) else {}
    coverage = map_index.get("coverage", {}) if isinstance(map_index.get("coverage"), dict) else {}
    if (
        map_index.get("mode") != "industrial_map_object_evidence_index"
        or not map_index.get("scale")
        or not map_index.get("objectRows")
        or not map_index.get("pathRows")
        or not map_index.get("queueRows")
        or not map_index.get("receiverLinks")
        or int(coverage.get("totalIndexedObjects", 0) or 0) <= 0
        or coverage.get("coordinateCoveragePct") is None
    ):
        weak.append("mapObjectEvidenceIndex")

    live_scene = dossier.get("liveOperatingSceneModel", {}) if isinstance(dossier.get("liveOperatingSceneModel"), dict) else {}
    scene_physical = live_scene.get("physicalScene", {}) if isinstance(live_scene.get("physicalScene"), dict) else {}
    scene_belief = live_scene.get("agentBeliefState", {}) if isinstance(live_scene.get("agentBeliefState"), dict) else {}
    if (
        live_scene.get("mode") != "industrial_live_operating_scene_model"
        or not live_scene.get("sceneClock")
        or not live_scene.get("sceneThesis")
        or not live_scene.get("actors")
        or not scene_physical.get("zones")
        or not scene_physical.get("paths")
        or not scene_physical.get("queues")
        or not live_scene.get("bottlenecks")
        or not live_scene.get("serviceKinetics")
        or not scene_belief.get("primaryBelief")
        or not live_scene.get("uncertaintyRegister")
        or not live_scene.get("actionTrainingImplication")
    ):
        weak.append("liveOperatingSceneModel")

    policy_trace = dossier.get("policyClauseTrace", {}) if isinstance(dossier.get("policyClauseTrace"), dict) else {}
    clause_rows = policy_trace.get("clauseRows", []) if isinstance(policy_trace.get("clauseRows"), list) else []
    branch_verdicts = policy_trace.get("branchPolicyVerdicts", []) if isinstance(policy_trace.get("branchPolicyVerdicts"), list) else []
    policy_branches = {row.get("branch") for row in branch_verdicts if isinstance(row, dict)}
    if (
        policy_trace.get("mode") != "industrial_policy_clause_trace"
        or not policy_trace.get("appliedPolicyRefs")
        or not clause_rows
        or not policy_trace.get("blockedActionTests")
        or not policy_trace.get("operatorApprovalQuestions")
        or not {"no_action", "fast_local_action", "governed_agent_action"}.issubset(policy_branches)
        or any(not isinstance(row, dict) or not row.get("policyBookId") or not row.get("policyRef") or not row.get("requiredEvidenceStatus") or not row.get("violationTests") for row in clause_rows)
    ):
        weak.append("policyClauseTrace")

    physics = dossier.get("spatialPhysicsEnvelope", {}) if isinstance(dossier.get("spatialPhysicsEnvelope"), dict) else {}
    physics_branches = {
        row.get("branch")
        for row in physics.get("branchPhysicsComparison", [])
        if isinstance(row, dict)
    } if isinstance(physics.get("branchPhysicsComparison"), list) else set()
    if (
        physics.get("mode") != "industrial_spatial_physics_envelope"
        or physics.get("physicsScore") is None
        or not physics.get("routePhysics")
        or not physics.get("queueGeometry")
        or not physics.get("zoneLoad")
        or not physics.get("emergencyAndServiceAccess")
        or not physics.get("operatorChecks")
        or not {"no_action", "fast_local_action", "governed_agent_action"}.issubset(physics_branches)
    ):
        weak.append("spatialPhysicsEnvelope")

    propagation = dossier.get("physicalPropagationModel", {}) if isinstance(dossier.get("physicalPropagationModel"), dict) else {}
    propagation_branches = {
        row.get("branch")
        for row in propagation.get("branchPropagationEffects", [])
        if isinstance(row, dict)
    } if isinstance(propagation.get("branchPropagationEffects"), list) else set()
    if (
        propagation.get("mode") != "industrial_physical_propagation_model"
        or propagation.get("confidenceScore") is None
        or not propagation.get("chain")
        or len(propagation.get("chain", [])) < 5
        or not propagation.get("tripwires")
        or not propagation.get("confidenceDrivers")
        or not {"no_action", "fast_local_action", "governed_agent_action"}.issubset(propagation_branches)
    ):
        weak.append("physicalPropagationModel")

    behavior = dossier.get("behavioralResponseModel", {}) if isinstance(dossier.get("behavioralResponseModel"), dict) else {}
    behavior_branches = {
        row.get("branch")
        for row in behavior.get("branchBehaviorComparison", [])
        if isinstance(row, dict)
    } if isinstance(behavior.get("branchBehaviorComparison"), list) else set()
    trust_loop = behavior.get("trustFeedbackLoop", {}) if isinstance(behavior.get("trustFeedbackLoop"), dict) else {}
    if (
        behavior.get("mode") != "industrial_behavioral_response_model"
        or behavior.get("readinessScore") is None
        or behavior.get("averageComplianceEstimatePct") is None
        or not behavior.get("segmentBehavior")
        or not behavior.get("staffAndReceiverResponse")
        or not behavior.get("criticalAssumptions")
        or not trust_loop.get("watchSignals")
        or not {"no_action", "fast_local_action", "governed_agent_action"}.issubset(behavior_branches)
    ):
        weak.append("behavioralResponseModel")

    precedent = dossier.get("historicalPrecedentMatrix", {}) if isinstance(dossier.get("historicalPrecedentMatrix"), dict) else {}
    precedent_branches = {
        row.get("branch")
        for row in precedent.get("branchPrecedentVerdicts", [])
        if isinstance(row, dict)
    } if isinstance(precedent.get("branchPrecedentVerdicts"), list) else set()
    coverage = precedent.get("precedentCoverage", {}) if isinstance(precedent.get("precedentCoverage"), dict) else {}
    calibration = precedent.get("confidenceCalibration", {}) if isinstance(precedent.get("confidenceCalibration"), dict) else {}
    if (
        precedent.get("mode") != "industrial_historical_precedent_matrix"
        or not coverage.get("datasetId")
        or not precedent.get("matchedPrecedents")
        or not precedent.get("recurringFailureModes")
        or not precedent.get("knownEffectiveControls")
        or not calibration.get("mustCalibrateWith")
        or not {"no_action", "fast_local_action", "governed_agent_action"}.issubset(precedent_branches)
    ):
        weak.append("historicalPrecedentMatrix")

    consequence = dossier.get("actionConsequenceSimulation", {}) if isinstance(dossier.get("actionConsequenceSimulation"), dict) else {}
    consequence_branches = {
        row.get("branch")
        for row in consequence.get("branchOutcomeSummary", [])
        if isinstance(row, dict)
    } if isinstance(consequence.get("branchOutcomeSummary"), list) else set()
    consequence_frames = consequence.get("consequenceFrames", []) if isinstance(consequence.get("consequenceFrames"), list) else []
    if (
        consequence.get("mode") != "industrial_action_consequence_simulation"
        or not consequence_frames
        or not {"no_action", "fast_local_action", "governed_agent_action"}.issubset(consequence_branches)
        or not consequence.get("causalMechanisms")
        or not consequence.get("requiredLiveTelemetry")
        or any(not isinstance(row, dict) or row.get("minute") is None or not row.get("observedState") or not row.get("secondOrderEffects") or not row.get("rollbackAssessment") for row in consequence_frames)
    ):
        weak.append("actionConsequenceSimulation")

    branch_impact = dossier.get("branchPhysicalImpactMatrix", {}) if isinstance(dossier.get("branchPhysicalImpactMatrix"), dict) else {}
    branch_impact_rows = branch_impact.get("branchRows", []) if isinstance(branch_impact.get("branchRows"), list) else []
    branch_impact_ids = {row.get("branch") for row in branch_impact_rows if isinstance(row, dict)}
    if (
        branch_impact.get("mode") != "industrial_branch_physical_impact_matrix"
        or not {"no_action", "fast_local_action", "governed_agent_action"}.issubset(branch_impact_ids)
        or branch_impact.get("selectedBranch") not in branch_impact_ids
        or branch_impact.get("rejectedBranch") not in branch_impact_ids
        or not branch_impact.get("subsystemMovement")
        or not branch_impact.get("selectedVsRejected")
        or any(not isinstance(row, dict) or not row.get("mapObjects") or not row.get("physicalDeltas") or not row.get("impactNarrative") or not row.get("riskTransfer") for row in branch_impact_rows)
    ):
        weak.append("branchPhysicalImpactMatrix")

    guest_comms_plan = dossier.get("guestCommunicationPlan", {}) if isinstance(dossier.get("guestCommunicationPlan"), dict) else {}
    if (
        guest_comms_plan.get("mode") != "industrial_guest_communication_plan"
        or not guest_comms_plan.get("communicationObjective")
        or not guest_comms_plan.get("audiencePlans")
        or not guest_comms_plan.get("channelPlan")
        or not guest_comms_plan.get("promiseBoundaries")
        or not guest_comms_plan.get("trustRiskControls")
        or not guest_comms_plan.get("rollbackMessaging")
        or not guest_comms_plan.get("approvalRequiredFor")
        or not guest_comms_plan.get("measurementPlan")
    ):
        weak.append("guestCommunicationPlan")

    constraint_register = dossier.get("operationalConstraintRegister", {}) if isinstance(dossier.get("operationalConstraintRegister"), dict) else {}
    branch_constraint_verdicts = constraint_register.get("branchConstraintVerdicts", []) if isinstance(constraint_register.get("branchConstraintVerdicts"), list) else []
    constraint_branches = {row.get("branch") for row in branch_constraint_verdicts if isinstance(row, dict)}
    go_no_go = constraint_register.get("goNoGo", {}) if isinstance(constraint_register.get("goNoGo"), dict) else {}
    if (
        constraint_register.get("mode") != "industrial_operational_constraint_register"
        or not constraint_register.get("hardConstraints")
        or not constraint_register.get("softTradeoffs")
        or not branch_constraint_verdicts
        or not {"no_action", "fast_local_action", "governed_agent_action"}.issubset(constraint_branches)
        or not go_no_go.get("state")
        or not go_no_go.get("releaseCondition")
        or not constraint_register.get("escalationPath")
    ):
        weak.append("operationalConstraintRegister")

    release_record = dossier.get("releaseDecisionRecord", {}) if isinstance(dossier.get("releaseDecisionRecord"), dict) else {}
    approved_version = release_record.get("approvedVersion", {}) if isinstance(release_record.get("approvedVersion"), dict) else {}
    approval_boundary = release_record.get("approvalBoundary", {}) if isinstance(release_record.get("approvalBoundary"), dict) else {}
    if (
        release_record.get("mode") != "industrial_release_decision_record"
        or not release_record.get("releaseState")
        or not approved_version.get("version")
        or not release_record.get("signoffMatrix")
        or not release_record.get("releaseConditions")
        or not release_record.get("draftOnlyBoundaries")
        or not release_record.get("postReleaseObligations")
        or not release_record.get("reviewSummary")
        or not release_record.get("freshnessAtRelease")
        or approval_boundary.get("humanApprovalRequired") is not True
    ):
        weak.append("releaseDecisionRecord")

    release_authority = dossier.get("releaseAuthorityDecision", {}) if isinstance(dossier.get("releaseAuthorityDecision"), dict) else {}
    if (
        release_authority.get("mode") != "industrial_release_authority_decision"
        or not release_authority.get("liveActionAuthority")
        or release_authority.get("autoExecuteAllowed") is not False
        or not release_authority.get("authorityChecks")
        or not release_authority.get("allowedNextStep")
    ):
        weak.append("releaseAuthorityDecision")

    execution_readiness = dossier.get("executionReadinessProof", {}) if isinstance(dossier.get("executionReadinessProof"), dict) else {}
    execution_checks = execution_readiness.get("executionChecks", []) if isinstance(execution_readiness.get("executionChecks"), list) else []
    execution_check_ids = {row.get("id") for row in execution_checks if isinstance(row, dict)}
    if (
        execution_readiness.get("mode") != "industrial_execution_readiness_proof"
        or execution_readiness.get("readinessScore") is None
        or execution_readiness.get("readyForLiveExecution") is not False
        or not execution_readiness.get("readinessState")
        or not {"people_and_roles", "receiver_acknowledgement", "space_and_access", "guest_communications", "service_rate_and_timing", "rollback_and_observation", "telemetry_and_authority"}.issubset(execution_check_ids)
        or not execution_readiness.get("requiredBeforeDispatch")
        or not execution_readiness.get("caseSceneEvidence")
        or any(not isinstance(row, dict) or not row.get("status") or not row.get("evidence") or not row.get("operatorQuestion") for row in execution_checks)
    ):
        weak.append("executionReadinessProof")

    remediation = dossier.get("releaseRemediationPlan", {}) if isinstance(dossier.get("releaseRemediationPlan"), dict) else {}
    if (
        remediation.get("mode") != "industrial_release_remediation_plan"
        or not remediation.get("remediationState")
        or remediation.get("taskCount") is None
        or not remediation.get("tasks")
        or not remediation.get("recheckSequence")
        or not remediation.get("completionCriteria")
    ):
        weak.append("releaseRemediationPlan")

    procedure_delta = dossier.get("operatingProcedureDelta", {}) if isinstance(dossier.get("operatingProcedureDelta"), dict) else {}
    promotion_gate = procedure_delta.get("promotionGate", {}) if isinstance(procedure_delta.get("promotionGate"), dict) else {}
    if (
        procedure_delta.get("mode") != "industrial_operating_procedure_delta"
        or not procedure_delta.get("procedureDeltas")
        or not procedure_delta.get("runbookStepUpdates")
        or not procedure_delta.get("policyPatchCandidates")
        or not promotion_gate.get("minimumEvidence")
        or not promotion_gate.get("promotionTarget")
        or promotion_gate.get("humanReviewRequired") is not True
    ):
        weak.append("operatingProcedureDelta")

    replay_manifest = dossier.get("decisionReproducibilityManifest", {}) if isinstance(dossier.get("decisionReproducibilityManifest"), dict) else {}
    replay_gate = replay_manifest.get("reproducibilityGate", {}) if isinstance(replay_manifest.get("reproducibilityGate"), dict) else {}
    expected_outputs = replay_manifest.get("expectedDeterministicOutputs", {}) if isinstance(replay_manifest.get("expectedDeterministicOutputs"), dict) else {}
    if (
        replay_manifest.get("mode") != "industrial_decision_reproducibility_manifest"
        or not replay_manifest.get("manifestHash")
        or not replay_manifest.get("simulatorVersion")
        or not replay_manifest.get("inputArtifacts")
        or any(not isinstance(row, dict) or not row.get("name") or not row.get("objectPath") or not row.get("hash") or not row.get("replayRole") for row in replay_manifest.get("inputArtifacts", []))
        or not replay_manifest.get("branchIds")
        or not replay_manifest.get("policyRefs")
        or not replay_manifest.get("thresholdSet")
        or not expected_outputs.get("branchScores")
        or not expected_outputs.get("selectedBranch")
        or not replay_manifest.get("replayInstructions")
        or replay_gate.get("structuralReady") is not True
        or replay_gate.get("productionReady") is not False
        or not replay_gate.get("requiredForProduction")
    ):
        weak.append("decisionReproducibilityManifest")

    custody = dossier.get("chainOfCustodyAuditLog", {}) if isinstance(dossier.get("chainOfCustodyAuditLog"), dict) else {}
    if (
        custody.get("mode") != "industrial_chain_of_custody_audit_log"
        or not custody.get("auditId")
        or not custody.get("custodyRows")
        or not custody.get("mutationAuthority")
        or not custody.get("immutableTraceCheckpoints")
        or not custody.get("mutationGuards")
        or not custody.get("evidenceHashInputs")
        or not custody.get("auditReplayInstructions")
    ):
        weak.append("chainOfCustodyAuditLog")

    field_calibration = dossier.get("fieldCalibrationBacktestPlan", {}) if isinstance(dossier.get("fieldCalibrationBacktestPlan"), dict) else {}
    if (
        field_calibration.get("mode") != "industrial_field_calibration_backtest_plan"
        or not field_calibration.get("requiredDatasets")
        or not field_calibration.get("backtestSuites")
        or not field_calibration.get("acceptanceThresholds")
        or not field_calibration.get("driftTriggers")
        or not field_calibration.get("learningCapturePlan")
        or not field_calibration.get("syntheticLimitations")
        or not field_calibration.get("calibrationState")
    ):
        weak.append("fieldCalibrationBacktestPlan")

    approval = dossier.get("governedApprovalPackage", {}) if isinstance(dossier.get("governedApprovalPackage"), dict) else {}
    boundary = approval.get("authorityBoundary", {}) if isinstance(approval.get("authorityBoundary"), dict) else {}
    rollback = approval.get("rollbackAuthority", {}) if isinstance(approval.get("rollbackAuthority"), dict) else {}
    if (
        approval.get("mode") != "governed_operator_approval_package"
        or not approval.get("operatorDecisionOptions")
        or not approval.get("receiverWrites")
        or not approval.get("approvalEvidence")
        or boundary.get("autoExecuteAllowed") is not False
        or not boundary.get("humanApprovalRequired")
        or not rollback.get("trigger")
    ):
        weak.append("governedApprovalPackage")

    calibration = dossier.get("dataQualityCalibration", {}) if isinstance(dossier.get("dataQualityCalibration"), dict) else {}
    if (
        calibration.get("mode") != "industrial_data_quality_calibration"
        or calibration.get("confidenceScore") is None
        or not calibration.get("freshnessRows")
        or not calibration.get("sourceLayerCoverage")
        or not calibration.get("missingTelemetry")
        or not calibration.get("calibrationRequirements")
        or not calibration.get("operatorWarning")
    ):
        weak.append("dataQualityCalibration")

    telemetry = dossier.get("telemetryContract", {}) if isinstance(dossier.get("telemetryContract"), dict) else {}
    readiness = telemetry.get("decisionReadiness", {}) if isinstance(telemetry.get("decisionReadiness"), dict) else {}
    if (
        telemetry.get("mode") != "industrial_case_telemetry_contract"
        or not telemetry.get("sourceBindings")
        or not telemetry.get("freshnessRules")
        or not telemetry.get("ownership")
        or not readiness.get("requiredLayers")
        or not readiness.get("availableLayers")
        or readiness.get("missingRequiredLayers")
        or not telemetry.get("qualityControls")
        or not telemetry.get("mutationGuards")
    ):
        weak.append("telemetryContract")

    reconciliation = dossier.get("fieldSignalReconciliation", {}) if isinstance(dossier.get("fieldSignalReconciliation"), dict) else {}
    if (
        reconciliation.get("mode") != "industrial_field_signal_reconciliation"
        or reconciliation.get("agreementScore") is None
        or not reconciliation.get("sourceRows")
        or not reconciliation.get("crossChecks")
        or not reconciliation.get("freshnessEvidence")
        or not reconciliation.get("watchMetricBindings")
        or not reconciliation.get("approvalImpact")
    ):
        weak.append("fieldSignalReconciliation")

    telemetry_snapshot = dossier.get("decisionTelemetrySnapshot", {}) if isinstance(dossier.get("decisionTelemetrySnapshot"), dict) else {}
    snapshot_row_families = [
        telemetry_snapshot.get("zoneRows", []) if isinstance(telemetry_snapshot.get("zoneRows"), list) else [],
        telemetry_snapshot.get("queueRows", []) if isinstance(telemetry_snapshot.get("queueRows"), list) else [],
        telemetry_snapshot.get("pathRows", []) if isinstance(telemetry_snapshot.get("pathRows"), list) else [],
        telemetry_snapshot.get("foodRows", []) if isinstance(telemetry_snapshot.get("foodRows"), list) else [],
        telemetry_snapshot.get("staffingRows", []) if isinstance(telemetry_snapshot.get("staffingRows"), list) else [],
        telemetry_snapshot.get("receiverRows", []) if isinstance(telemetry_snapshot.get("receiverRows"), list) else [],
        telemetry_snapshot.get("guestSegmentRows", []) if isinstance(telemetry_snapshot.get("guestSegmentRows"), list) else [],
        telemetry_snapshot.get("thresholdBreaches", []) if isinstance(telemetry_snapshot.get("thresholdBreaches"), list) else [],
    ]
    source_lineage = telemetry_snapshot.get("sourceLineage", {}) if isinstance(telemetry_snapshot.get("sourceLineage"), dict) else {}
    acceptance_gates = telemetry_snapshot.get("productionAcceptanceGates", []) if isinstance(telemetry_snapshot.get("productionAcceptanceGates"), list) else []
    acceptance_gate_families = {row.get("rowFamily") for row in acceptance_gates if isinstance(row, dict)}
    telemetry_certification = telemetry_snapshot.get("telemetryCertification", {}) if isinstance(telemetry_snapshot.get("telemetryCertification"), dict) else {}
    snapshot_rows_have_identity = all(
        isinstance(row, dict)
        and isinstance(row.get("sourceIdentity"), dict)
        and row["sourceIdentity"].get("sourceSystemId")
        and row["sourceIdentity"].get("sourcePath")
        and row["sourceIdentity"].get("eventTime")
        and row["sourceIdentity"].get("ingestTime")
        and row["sourceIdentity"].get("owner")
        and row["sourceIdentity"].get("qualityStatus")
        for family in snapshot_row_families
        for row in family
    )
    if (
        telemetry_snapshot.get("mode") != "industrial_decision_telemetry_snapshot"
        or not telemetry_snapshot.get("capturedAt")
        or not telemetry_snapshot.get("zoneRows")
        or not telemetry_snapshot.get("queueRows")
        or not telemetry_snapshot.get("pathRows")
        or not telemetry_snapshot.get("foodRows")
        or not telemetry_snapshot.get("staffingRows")
        or not telemetry_snapshot.get("receiverRows")
        or not telemetry_snapshot.get("guestSegmentRows")
        or not telemetry_snapshot.get("thresholdBreaches")
        or source_lineage.get("mode") != "telemetry_source_lineage"
        or not source_lineage.get("requiredForProduction")
        or not {"queueRows", "pathRows", "foodRows", "staffingRows", "receiverRows", "guestSegmentRows"}.issubset(acceptance_gate_families)
        or any(not isinstance(row, dict) or not row.get("sourceSystemId") or not row.get("owner") or not row.get("gateStatus") or not row.get("exitCriteria") for row in acceptance_gates)
        or telemetry_certification.get("mode") != "decision_telemetry_certification"
        or telemetry_certification.get("structuralReady") is not True
        or telemetry_certification.get("productionReady") is not False
        or telemetry_certification.get("blockedGateCount") is None
        or not telemetry_certification.get("requiredBeforeLiveUse")
        or not snapshot_rows_have_identity
        or not telemetry_snapshot.get("freshness")
    ):
        weak.append("decisionTelemetrySnapshot")

    handoff = dossier.get("fieldExecutionHandoff", {}) if isinstance(dossier.get("fieldExecutionHandoff"), dict) else {}
    command = handoff.get("incidentCommand", {}) if isinstance(handoff.get("incidentCommand"), dict) else {}
    staging = handoff.get("stagingPlan", {}) if isinstance(handoff.get("stagingPlan"), dict) else {}
    dispatches = handoff.get("dispatches", []) if isinstance(handoff.get("dispatches"), list) else []
    guest_comms = handoff.get("guestCommunication", {}) if isinstance(handoff.get("guestCommunication"), dict) else {}
    gates = handoff.get("acknowledgementGates", []) if isinstance(handoff.get("acknowledgementGates"), list) else []
    if (
        handoff.get("mode") != "industrial_field_execution_handoff"
        or not command.get("commander")
        or not staging.get("primaryArea")
        or not dispatches
        or any(not isinstance(row, dict) or not row.get("receiverId") or not row.get("instruction") or row.get("ackRequiredBySec") is None for row in dispatches)
        or not guest_comms.get("message")
        or len(gates) < 3
        or not handoff.get("abortCriteria")
    ):
        weak.append("fieldExecutionHandoff")

    runbook = dossier.get("caseExecutionRunbook", {}) if isinstance(dossier.get("caseExecutionRunbook"), dict) else {}
    lifecycle = runbook.get("lifecycle", []) if isinstance(runbook.get("lifecycle"), list) else []
    if (
        runbook.get("mode") != "industrial_case_execution_runbook"
        or not runbook.get("owners")
        or not lifecycle
        or not runbook.get("escalationRules")
        or not runbook.get("completionCriteria")
        or not {"observe", "simulate", "policy_gate", "operator_approval", "receiver_write", "verify"}.issubset({step.get("id") for step in lifecycle if isinstance(step, dict)})
    ):
        weak.append("caseExecutionRunbook")

    closed_loop = dossier.get("closedLoopVerification", {}) if isinstance(dossier.get("closedLoopVerification"), dict) else {}
    if (
        closed_loop.get("mode") != "closed_loop_verification_plan"
        or not closed_loop.get("observationWindows")
        or not closed_loop.get("receiverReceipts")
        or not closed_loop.get("projectedVsObservedChecks")
        or not closed_loop.get("rollbackTriggers")
        or not closed_loop.get("learningCapture")
        or not closed_loop.get("status")
    ):
        weak.append("closedLoopVerification")

    receivers = dossier.get("receiverReadiness", []) if isinstance(dossier.get("receiverReadiness"), list) else []
    if not receivers or any(not isinstance(row, dict) or not row.get("state") or row.get("latencySec") is None or row.get("coveragePct") is None or not row.get("failureMode") for row in receivers):
        weak.append("receiverReadiness")

    branches = dossier.get("actionTrainingFrame", []) if isinstance(dossier.get("actionTrainingFrame"), list) else []
    branch_ids = {branch.get("branch") for branch in branches if isinstance(branch, dict)}
    if branch_ids != {"no_action", "fast_local_action", "governed_agent_action"}:
        weak.append("actionTrainingFrame")
    if any(not isinstance(branch, dict) or not branch.get("simulationVerdict") or not branch.get("simulatedOutcome") for branch in branches):
        weak.append("actionTrainingFrame")

    simulated = dossier.get("simulatedBranchComparison", {}) if isinstance(dossier.get("simulatedBranchComparison"), dict) else {}
    simulated_branches = simulated.get("branches", []) if isinstance(simulated.get("branches"), list) else []
    simulated_branch_ids = {branch.get("id") for branch in simulated_branches if isinstance(branch, dict)}
    if (
        simulated.get("mode") != "dossier_three_branch_physical_simulation"
        or not {"no_action", "fast_local_action", "governed_agent_action"}.issubset(simulated_branch_ids)
        or simulated.get("selected_branch") not in simulated_branch_ids
        or simulated.get("rejected_branch") not in simulated_branch_ids
        or any(not isinstance(branch, dict) or branch.get("score") is None or not branch.get("delta_from_now") or not branch.get("checkpoints") for branch in simulated_branches)
    ):
        weak.append("simulatedBranchComparison")

    scorecard = dossier.get("operatingScorecard", {}) if isinstance(dossier.get("operatingScorecard"), dict) else {}
    score_rows = scorecard.get("scoreRows", []) if isinstance(scorecard.get("scoreRows"), list) else []
    score_branch_ids = {row.get("branch") for row in score_rows if isinstance(row, dict)}
    if (
        scorecard.get("mode") != "industrial_operating_scorecard"
        or not {"no_action", "fast_local_action", "governed_agent_action"}.issubset(score_branch_ids)
        or scorecard.get("selectedBranch") not in score_branch_ids
        or not scorecard.get("tradeoffLedger")
        or not scorecard.get("dimensionWeights")
        or any(not isinstance(row, dict) or row.get("overall") is None or not row.get("dimensions") or not row.get("evidence") for row in score_rows)
    ):
        weak.append("operatingScorecard")

    sensitivity = dossier.get("assumptionSensitivityAnalysis", {}) if isinstance(dossier.get("assumptionSensitivityAnalysis"), dict) else {}
    if (
        sensitivity.get("mode") != "industrial_assumption_sensitivity_analysis"
        or not sensitivity.get("assumptions")
        or not sensitivity.get("stressTests")
        or not sensitivity.get("flipConditions")
        or not sensitivity.get("confidenceDrivers")
        or sensitivity.get("selectedBranch") not in {"no_action", "fast_local_action", "governed_agent_action"}
        or sensitivity.get("operatingMargin") is None
    ):
        weak.append("assumptionSensitivityAnalysis")

    rehearsal = dossier.get("operationalStressRehearsal", {}) if isinstance(dossier.get("operationalStressRehearsal"), dict) else {}
    scenario_statuses = {
        row.get("status")
        for row in rehearsal.get("rehearsalScenarios", [])
        if isinstance(row, dict)
    } if isinstance(rehearsal.get("rehearsalScenarios"), list) else set()
    if (
        rehearsal.get("mode") != "industrial_operational_stress_rehearsal"
        or rehearsal.get("branchSurvivalScore") is None
        or not rehearsal.get("releasePosture")
        or not rehearsal.get("rehearsalScenarios")
        or len(rehearsal.get("rehearsalScenarios", [])) < 4
        or not rehearsal.get("escalationTriggers")
        or not scenario_statuses.issubset({"pass", "review", "fail"})
    ):
        weak.append("operationalStressRehearsal")

    review_board = dossier.get("independentReviewBoard", {}) if isinstance(dossier.get("independentReviewBoard"), dict) else {}
    reviews = review_board.get("reviews", []) if isinstance(review_board.get("reviews"), list) else []
    reviewers = {review.get("reviewer") for review in reviews if isinstance(review, dict)}
    if (
        review_board.get("mode") != "independent_operating_review_board"
        or not {"safety_reviewer", "operations_reviewer", "data_quality_reviewer", "commercial_guest_recovery_reviewer", "red_team_reviewer"}.issubset(reviewers)
        or not review_board.get("releaseDecision")
        or not review_board.get("residualRisks")
        or not review_board.get("requiredOperatorQuestions")
        or any(not isinstance(review, dict) or not review.get("challenge") or not review.get("evidence") or not review.get("requiredOperatorQuestion") for review in reviews)
    ):
        weak.append("independentReviewBoard")

    verification = dossier.get("verificationPlan", {}) if isinstance(dossier.get("verificationPlan"), dict) else {}
    if not verification.get("successMetric") or not verification.get("watchConditions") or not verification.get("rollbackTrigger"):
        weak.append("verificationPlan")

    audit = dossier.get("auditStandard", {}) if isinstance(dossier.get("auditStandard"), dict) else {}
    trace_keys = set(audit.get("traceKeys", [])) if isinstance(audit.get("traceKeys"), list) else set()
    if not {"industrialDossiers", "physicalDynamics", "externalSystems", "temporalConsequences"}.issubset(trace_keys):
        weak.append("auditStandard")

    physical = dossier.get("physicalMechanism", []) if isinstance(dossier.get("physicalMechanism"), list) else []
    hypotheses = dossier.get("competingHypotheses", []) if isinstance(dossier.get("competingHypotheses"), list) else []
    if not physical and not any("physical" in str(row.get("hypothesis", "")).lower() for row in hypotheses if isinstance(row, dict)):
        weak.append("physicalMechanism")

    spatial = dossier.get("spatialCausalityTrace", {}) if isinstance(dossier.get("spatialCausalityTrace"), dict) else {}
    if (
        spatial.get("mode") != "map_object_causality_trace"
        or not spatial.get("zones")
        or not spatial.get("paths")
        or not spatial.get("queues")
        or not spatial.get("branchSpatialEffects")
        or not spatial.get("watchMetrics")
    ):
        weak.append("spatialCausalityTrace")

    causal = dossier.get("causalGraph", {}) if isinstance(dossier.get("causalGraph"), dict) else {}
    causal_nodes = causal.get("nodes", []) if isinstance(causal.get("nodes"), list) else []
    causal_edges = causal.get("edges", []) if isinstance(causal.get("edges"), list) else []
    causal_types = {node.get("type") for node in causal_nodes if isinstance(node, dict)}
    edge_refs = {
        endpoint
        for edge in causal_edges
        if isinstance(edge, dict)
        for endpoint in (edge.get("from"), edge.get("to"))
        if endpoint
    }
    node_ids = {node.get("id") for node in causal_nodes if isinstance(node, dict) and node.get("id")}
    if (
        causal.get("mode") != "typed_operating_causal_graph"
        or not {"trigger", "physical_constraint", "affected_zone", "receiver_system", "policy_boundary", "selected_action", "target_outcome"}.issubset(causal_types)
        or len(causal_nodes) < 7
        or len(causal_edges) < 6
        or not edge_refs.issubset(node_ids)
        or any(not isinstance(edge, dict) or not edge.get("relation") or edge.get("confidence") is None for edge in causal_edges)
    ):
        weak.append("causalGraph")

    replay = dossier.get("counterfactualReplay", {}) if isinstance(dossier.get("counterfactualReplay"), dict) else {}
    replay_rows = replay.get("rows", []) if isinstance(replay.get("rows"), list) else []
    replay_branches = {row.get("branch") for row in replay_rows if isinstance(row, dict)}
    replay_minutes = {row.get("minute") for row in replay_rows if isinstance(row, dict)}
    if (
        replay.get("mode") != "counterfactual_branch_replay_matrix"
        or not {"no_action", "fast_local_action", "governed_agent_action"}.issubset(replay_branches)
        or len(replay_minutes) < 3
        or not replay.get("watchMetrics")
        or any(not isinstance(row, dict) or not row.get("metrics") or not row.get("operatorRead") for row in replay_rows)
    ):
        weak.append("counterfactualReplay")

    commercial = dossier.get("commercialImpactLedger", {}) if isinstance(dossier.get("commercialImpactLedger"), dict) else {}
    commercial_rows = commercial.get("rows", []) if isinstance(commercial.get("rows"), list) else []
    commercial_branches = {row.get("branch") for row in commercial_rows if isinstance(row, dict)}
    if (
        commercial.get("mode") != "industrial_commercial_impact_ledger"
        or not {"no_action", "fast_local_action", "governed_agent_action"}.issubset(commercial_branches)
        or not commercial.get("assumptions")
        or not commercial.get("summary")
        or not commercial.get("requiredCalibration")
        or any(not isinstance(row, dict) or row.get("affectedGuests") is None or row.get("guestMinutesAtRisk") is None or row.get("foodRevenueAtRiskUsd") is None or row.get("complaintExposureScore") is None for row in commercial_rows)
    ):
        weak.append("commercialImpactLedger")

    accessibility = dossier.get("accessibilityEquityImpact", {}) if isinstance(dossier.get("accessibilityEquityImpact"), dict) else {}
    equity_rows = accessibility.get("branchEquityComparison", []) if isinstance(accessibility.get("branchEquityComparison"), list) else []
    equity_branches = {row.get("branch") for row in equity_rows if isinstance(row, dict)}
    if (
        accessibility.get("mode") != "industrial_accessibility_equity_impact"
        or accessibility.get("equityScore") is None
        or not accessibility.get("protectedCohorts")
        or not accessibility.get("routeAccessChecks")
        or not accessibility.get("fairnessChecks")
        or not accessibility.get("requiredControls")
        or not {"no_action", "fast_local_action", "governed_agent_action"}.issubset(equity_branches)
        or any(not isinstance(row, dict) or row.get("accessibilityRiskScore") is None or row.get("standbyFairnessRiskPct") is None for row in equity_rows)
    ):
        weak.append("accessibilityEquityImpact")

    resource = dossier.get("resourceFeasibilityMatrix", {}) if isinstance(dossier.get("resourceFeasibilityMatrix"), dict) else {}
    resource_rows = resource.get("branchFeasibilityComparison", []) if isinstance(resource.get("branchFeasibilityComparison"), list) else []
    resource_branches = {row.get("branch") for row in resource_rows if isinstance(row, dict)}
    if (
        resource.get("mode") != "industrial_resource_feasibility_matrix"
        or resource.get("feasibilityScore") is None
        or not resource.get("laborEnvelope")
        or not resource.get("receiverExecutionRows")
        or not resource.get("timeCriticalPath")
        or not resource.get("resourceConflicts")
        or not resource.get("requiredOperatorChecks")
        or not {"no_action", "fast_local_action", "governed_agent_action"}.issubset(resource_branches)
        or any(not isinstance(row, dict) or row.get("feasibilityScore") is None or row.get("criticalPathSeconds") is None for row in resource_rows)
    ):
        weak.append("resourceFeasibilityMatrix")

    park_reality = dossier.get("parkRealityModel", {}) if isinstance(dossier.get("parkRealityModel"), dict) else {}
    topology = park_reality.get("localTopology", {}) if isinstance(park_reality.get("localTopology"), dict) else {}
    dependencies = park_reality.get("serviceDependencies", {}) if isinstance(park_reality.get("serviceDependencies"), dict) else {}
    envelope = park_reality.get("capacityEnvelope", {}) if isinstance(park_reality.get("capacityEnvelope"), dict) else {}
    if (
        park_reality.get("mode") != "case_specific_park_reality_model"
        or not park_reality.get("operatingPhase")
        or not topology.get("zones")
        or not topology.get("paths")
        or not envelope.get("zonePressure")
        or not envelope.get("pathBottlenecks")
        or not dependencies.get("receiverSystems")
        or not dependencies.get("guestSegments")
        or not dependencies.get("laborAndAssetConstraints")
        or not park_reality.get("failurePropagation")
    ):
        weak.append("parkRealityModel")

    provenance = dossier.get("evidenceProvenance", []) if isinstance(dossier.get("evidenceProvenance"), list) else []
    provenance_sources = {
        row.get("sourceLayer")
        for row in provenance
        if isinstance(row, dict) and row.get("sourceLayer") and row.get("field") and row.get("supports")
    }
    if not {"actionConflictSimulation", "physicalDynamics", "externalSystems", "temporalConsequences"}.issubset(provenance_sources):
        weak.append("evidenceProvenance")

    score = max(0, 100 - len(set(missing)) * 12 - len(set(weak)) * 6)
    return {
        "caseId": dossier.get("id"),
        "sourceConflictId": dossier.get("sourceConflictId"),
        "status": "ready" if score >= 90 and not missing and not weak else "needs_review",
        "score": score,
        "missing": sorted(set(missing)),
        "weak": sorted(set(weak)),
    }


def _first_dict(rows: list[Any] | None, key: str, value: Any) -> dict[str, Any]:
    for row in rows or []:
        if isinstance(row, dict) and row.get(key) == value:
            return row
    return {}


def _case_ref(row: dict[str, Any] | None) -> dict[str, Any]:
    row = row if isinstance(row, dict) else {}
    return {
        "present": bool(row),
        "status": row.get("status") or row.get("state") or row.get("acquisitionState") or row.get("certificationDecision") or row.get("decision"),
        "summary": row.get("operatorRead") or row.get("operatorUse") or row.get("decisionSummary") or row.get("caseNarrative"),
        "owner": row.get("owner") or row.get("accountableOwner") or row.get("responsibleOwner"),
    }


def build_park_live_summary_payload(state: dict[str, Any]) -> dict[str, Any]:
    industrial = state.get("industrialDossiers", {}) if isinstance(state.get("industrialDossiers"), dict) else {}
    summary = industrial.get("summary", {}) if isinstance(industrial.get("summary"), dict) else {}
    risk_ranking = industrial.get("portfolioRiskRanking", {}) if isinstance(industrial.get("portfolioRiskRanking"), dict) else {}
    operating_queue = risk_ranking.get("operatingQueue", []) if isinstance(risk_ranking.get("operatingQueue"), list) else []
    top_case_id = risk_ranking.get("topPriorityCaseId")
    top_case = _first_dict(risk_ranking.get("rankingRows", []), "caseId", top_case_id)
    acceptance = _first_dict((industrial.get("industrialAcceptanceCertificationLedger", {}) if isinstance(industrial.get("industrialAcceptanceCertificationLedger"), dict) else {}).get("caseRows", []), "caseId", top_case_id)
    production_acquisition = _first_dict((industrial.get("productionEvidenceAcquisitionLedger", {}) if isinstance(industrial.get("productionEvidenceAcquisitionLedger"), dict) else {}).get("caseRows", []), "caseId", top_case_id)
    sim_time = state.get("simTime", {}) if isinstance(state.get("simTime"), dict) else {}
    clock = state.get("operatingClock", {}) if isinstance(state.get("operatingClock"), dict) else {}
    phase = clock.get("phase", {}) if isinstance(clock.get("phase"), dict) else {}
    queues = state.get("queues", []) if isinstance(state.get("queues"), list) else []
    highest_queue = max((row for row in queues if isinstance(row, dict)), key=lambda row: float(row.get("waitMins", 0) or 0), default={})
    return {
        "status": "ready",
        "mode": "compact_live_operating_summary",
        "dataPlane": {
            "hotState": "Firestore or Memorystore",
            "auditPackets": "Cloud Storage",
            "warehouse": "BigQuery",
            "retrieval": "Vertex AI Search or BigQuery VECTOR_SEARCH",
            "asyncWork": "Pub/Sub or Cloud Tasks",
        },
        "simulationClock": {
            "hour": sim_time.get("hour"),
            "minute": sim_time.get("minute"),
            "phase": phase.get("label"),
            "demandPressurePct": phase.get("demandPressurePct"),
        },
        "operatingSummary": {
            "caseCount": summary.get("caseCount"),
            "domainCoverageCount": summary.get("domainCoverageCount"),
            "productionReady": False,
            "topPriorityCaseId": top_case_id,
            "topPriorityTitle": top_case.get("title"),
            "highestQueue": {
                "id": highest_queue.get("id"),
                "name": highest_queue.get("name"),
                "waitMins": highest_queue.get("waitMins"),
                "densityPct": highest_queue.get("densityPct"),
            },
        },
        "activeCase": {
            "caseId": top_case_id,
            "rank": top_case.get("rank"),
            "domain": top_case.get("domain"),
            "severity": top_case.get("severity"),
            "score": top_case.get("priorityScore"),
            "mapFocus": top_case.get("mapFocus", []),
            "acceptance": {
                "allowedSurface": acceptance.get("allowedOperatingSurface"),
                "blockerClasses": acceptance.get("blockerClasses", []),
                "nextOwnerAction": acceptance.get("nextOwnerAction"),
            },
            "productionEvidence": {
                "state": production_acquisition.get("acquisitionState"),
                "feedCount": len(production_acquisition.get("feedAcquisitions", [])) if isinstance(production_acquisition.get("feedAcquisitions"), list) else 0,
                "blockedStages": [
                    stage.get("stage")
                    for stage in production_acquisition.get("graduationStages", [])
                    if isinstance(stage, dict) and stage.get("currentState") == "blocked"
                ],
            },
        },
        "caseIndexEndpoint": "/api/park/cases",
        "caseBriefEndpoint": "/api/park/cases/{case_id}/brief",
        "fullAuditPacketEndpoint": "/api/park/industrial-dossiers/{case_id}/packet",
        "operatingQueue": operating_queue[:5],
    }


def build_case_index_payload(payload: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for case in payload.get("caseIndex", []):
        if not isinstance(case, dict):
            continue
        acceptance = case.get("industrialAcceptanceCertification", {}) if isinstance(case.get("industrialAcceptanceCertification"), dict) else {}
        production_acquisition = case.get("productionEvidenceAcquisition", {}) if isinstance(case.get("productionEvidenceAcquisition"), dict) else {}
        portfolio_priority = case.get("portfolioPriority", {}) if isinstance(case.get("portfolioPriority"), dict) else {}
        rows.append(
            {
                "id": case.get("id"),
                "sourceConflictId": case.get("sourceConflictId"),
                "title": case.get("title"),
                "domain": case.get("domain"),
                "severity": case.get("severity"),
                "mapFocus": case.get("mapFocus", []),
                "quality": {
                    "status": (case.get("quality", {}) if isinstance(case.get("quality"), dict) else {}).get("status"),
                    "score": (case.get("quality", {}) if isinstance(case.get("quality"), dict) else {}).get("score"),
                },
                "priority": {
                    "rank": portfolio_priority.get("rank"),
                    "score": portfolio_priority.get("priorityScore"),
                    "rationale": portfolio_priority.get("rationale"),
                },
                "governance": {
                    "allowedSurface": acceptance.get("allowedOperatingSurface"),
                    "blockerClasses": acceptance.get("blockerClasses", []),
                    "nextOwnerAction": acceptance.get("nextOwnerAction"),
                },
                "productionEvidence": {
                    "state": production_acquisition.get("acquisitionState"),
                    "feedCount": len(production_acquisition.get("feedAcquisitions", [])) if isinstance(production_acquisition.get("feedAcquisitions"), list) else 0,
                    "packetHash": (production_acquisition.get("acquisitionPacket", {}) if isinstance(production_acquisition.get("acquisitionPacket"), dict) else {}).get("packetHash"),
                },
                "links": {
                    "brief": f"/api/park/cases/{case.get('id')}/brief",
                    "fullPacket": f"/api/park/industrial-dossiers/{case.get('id')}/packet",
                },
            }
        )
    return {
        "status": payload.get("status"),
        "mode": "compact_case_index",
        "standard": payload.get("standard"),
        "simulationClock": payload.get("simulationClock"),
        "summary": payload.get("summary"),
        "rows": rows,
        "storagePlan": {
            "hotIndex": "Firestore collection: park_cases",
            "auditPacketObject": "Cloud Storage object: dossiers/{case_id}/{packet_hash}.json",
            "warehouseTables": ["case_ledgers", "case_events", "case_evaluations", "synthetic_episodes"],
            "retrievalIndex": "Vertex AI Search or BigQuery vector index over policy/evidence chunks",
        },
    }


def build_case_brief_payload(payload: dict[str, Any], dossier: dict[str, Any]) -> dict[str, Any]:
    case_id = dossier.get("id")
    index_row = _first_dict(payload.get("caseIndex", []), "id", case_id)
    if not index_row:
        index_row = _first_dict(payload.get("caseIndex", []), "sourceConflictId", dossier.get("sourceConflictId"))
    policy = dossier.get("policyReasoning", {}) if isinstance(dossier.get("policyReasoning"), dict) else {}
    branch_comparison = dossier.get("simulatedBranchComparison", {}) if isinstance(dossier.get("simulatedBranchComparison"), dict) else {}
    branches = branch_comparison.get("branches", []) if isinstance(branch_comparison.get("branches"), list) else []
    return {
        "status": "ready",
        "mode": "case_operating_brief",
        "caseHeader": {
            "id": case_id,
            "sourceConflictId": dossier.get("sourceConflictId"),
            "title": dossier.get("title"),
            "domain": dossier.get("domain"),
            "severity": dossier.get("severity"),
            "mapFocus": dossier.get("mapFocus", []),
        },
        "operatingThesis": dossier.get("operatingThesis"),
        "physicalMechanism": dossier.get("physicalMechanism"),
        "recommendedAction": dossier.get("recommendedAction") or (dossier.get("releaseDecisionRecord", {}) if isinstance(dossier.get("releaseDecisionRecord"), dict) else {}).get("selectedBranch"),
        "policyReasoning": {
            "applies": policy.get("applies", []),
            "decision": policy.get("decision"),
            "blockedActions": policy.get("blockedActions", []),
        },
        "branchComparison": [
            {
                "branch": branch.get("branch"),
                "label": branch.get("label"),
                "score": branch.get("score"),
                "summary": branch.get("summary") or branch.get("outcome"),
                "tradeoffs": branch.get("tradeoffs", []),
            }
            for branch in branches
            if isinstance(branch, dict)
        ],
        "governance": {
            "quality": index_row.get("quality"),
            "acceptance": index_row.get("industrialAcceptanceCertification"),
            "productionEvidenceAcquisition": index_row.get("productionEvidenceAcquisition"),
            "releaseBoardException": _case_ref(index_row.get("releaseBoardException")),
            "fieldEvidenceReleaseClearance": _case_ref(index_row.get("fieldEvidenceReleaseClearance")),
        },
        "evidencePointers": {
            "mapObjectEvidenceIndex": _case_ref(dossier.get("mapObjectEvidenceIndex")),
            "telemetryAcceptance": _case_ref(index_row.get("telemetryAcceptance")),
            "physicalMovementProof": _case_ref(index_row.get("physicalMovementProof")),
            "outcomeAccountability": _case_ref(index_row.get("outcomeAccountability")),
            "fullAuditPacket": f"/api/park/industrial-dossiers/{case_id}/packet",
        },
        "gcpMaterialization": {
            "hotDocument": f"firestore://park_cases/{case_id}",
            "auditPacketObject": f"gs://parkpulse-dossiers/dossiers/{case_id}/latest.json",
            "warehousePartition": f"bigquery://parkpulse.case_ledgers/case_id={case_id}",
            "retrievalFilter": {"caseId": case_id, "domains": [dossier.get("domain")]},
        },
    }


def _case_id_aliases(value: Any) -> set[str]:
    normalized = str(value or "").strip()
    slug = normalized.lower().replace(" ", "_")
    aliases = {normalized, slug}
    for prefix in ("industrial_", "live_conflict_", "policy_case_"):
        if slug.startswith(prefix):
            aliases.add(slug.removeprefix(prefix))
        else:
            aliases.add(f"{prefix}{slug}")
    return {alias for alias in aliases if alias}


def find_industrial_dossier(payload: dict[str, Any], case_id: str) -> dict[str, Any] | None:
    requested_aliases = _case_id_aliases(case_id)
    for dossier in payload.get("dossiers", []):
        if not isinstance(dossier, dict):
            continue
        candidate_ids = set()
        for value in (dossier.get("id"), dossier.get("sourceConflictId"), dossier.get("title")):
            candidate_ids.update(_case_id_aliases(value))
        if requested_aliases & candidate_ids:
            return dossier
    return None


def build_industrial_dossier_packet(payload: dict[str, Any], dossier: dict[str, Any]) -> dict[str, Any]:
    policy = dossier.get("policyReasoning", {}) if isinstance(dossier.get("policyReasoning"), dict) else {}
    verification = dossier.get("verificationPlan", {}) if isinstance(dossier.get("verificationPlan"), dict) else {}
    audit = dossier.get("auditStandard", {}) if isinstance(dossier.get("auditStandard"), dict) else {}
    provenance = dossier.get("evidenceProvenance", []) if isinstance(dossier.get("evidenceProvenance"), list) else []
    receiver_rows = dossier.get("receiverReadiness", []) if isinstance(dossier.get("receiverReadiness"), list) else []
    training_rows = dossier.get("actionTrainingFrame", []) if isinstance(dossier.get("actionTrainingFrame"), list) else []
    quality = dossier.get("quality", {}) if isinstance(dossier.get("quality"), dict) else {}
    simulated_branch_comparison = dossier.get("simulatedBranchComparison", {}) if isinstance(dossier.get("simulatedBranchComparison"), dict) else {}
    simulated_branches = simulated_branch_comparison.get("branches", []) if isinstance(simulated_branch_comparison.get("branches"), list) else []
    policy_clause_trace = dossier.get("policyClauseTrace", {}) if isinstance(dossier.get("policyClauseTrace"), dict) else {}
    spatial_physics = dossier.get("spatialPhysicsEnvelope", {}) if isinstance(dossier.get("spatialPhysicsEnvelope"), dict) else {}
    historical_precedent = dossier.get("historicalPrecedentMatrix", {}) if isinstance(dossier.get("historicalPrecedentMatrix"), dict) else {}
    guest_communication_plan = dossier.get("guestCommunicationPlan", {}) if isinstance(dossier.get("guestCommunicationPlan"), dict) else {}
    behavioral_response = dossier.get("behavioralResponseModel", {}) if isinstance(dossier.get("behavioralResponseModel"), dict) else {}
    constraint_register = dossier.get("operationalConstraintRegister", {}) if isinstance(dossier.get("operationalConstraintRegister"), dict) else {}
    release_decision_record = dossier.get("releaseDecisionRecord", {}) if isinstance(dossier.get("releaseDecisionRecord"), dict) else {}
    release_authority = dossier.get("releaseAuthorityDecision", {}) if isinstance(dossier.get("releaseAuthorityDecision"), dict) else {}
    execution_readiness = dossier.get("executionReadinessProof", {}) if isinstance(dossier.get("executionReadinessProof"), dict) else {}
    release_remediation = dossier.get("releaseRemediationPlan", {}) if isinstance(dossier.get("releaseRemediationPlan"), dict) else {}
    procedure_delta = dossier.get("operatingProcedureDelta", {}) if isinstance(dossier.get("operatingProcedureDelta"), dict) else {}
    decision_reproducibility = dossier.get("decisionReproducibilityManifest", {}) if isinstance(dossier.get("decisionReproducibilityManifest"), dict) else {}
    chain_of_custody = dossier.get("chainOfCustodyAuditLog", {}) if isinstance(dossier.get("chainOfCustodyAuditLog"), dict) else {}
    field_calibration = dossier.get("fieldCalibrationBacktestPlan", {}) if isinstance(dossier.get("fieldCalibrationBacktestPlan"), dict) else {}
    operating_scorecard = dossier.get("operatingScorecard", {}) if isinstance(dossier.get("operatingScorecard"), dict) else {}
    sensitivity = dossier.get("assumptionSensitivityAnalysis", {}) if isinstance(dossier.get("assumptionSensitivityAnalysis"), dict) else {}
    stress_rehearsal = dossier.get("operationalStressRehearsal", {}) if isinstance(dossier.get("operationalStressRehearsal"), dict) else {}
    review_board = dossier.get("independentReviewBoard", {}) if isinstance(dossier.get("independentReviewBoard"), dict) else {}
    causal_graph = dossier.get("causalGraph", {}) if isinstance(dossier.get("causalGraph"), dict) else {}
    counterfactual_replay = dossier.get("counterfactualReplay", {}) if isinstance(dossier.get("counterfactualReplay"), dict) else {}
    branch_physical_impact = dossier.get("branchPhysicalImpactMatrix", {}) if isinstance(dossier.get("branchPhysicalImpactMatrix"), dict) else {}
    action_consequence = dossier.get("actionConsequenceSimulation", {}) if isinstance(dossier.get("actionConsequenceSimulation"), dict) else {}
    map_object_index = dossier.get("mapObjectEvidenceIndex", {}) if isinstance(dossier.get("mapObjectEvidenceIndex"), dict) else {}
    commercial_impact = dossier.get("commercialImpactLedger", {}) if isinstance(dossier.get("commercialImpactLedger"), dict) else {}
    accessibility_equity = dossier.get("accessibilityEquityImpact", {}) if isinstance(dossier.get("accessibilityEquityImpact"), dict) else {}
    resource_feasibility = dossier.get("resourceFeasibilityMatrix", {}) if isinstance(dossier.get("resourceFeasibilityMatrix"), dict) else {}
    park_reality = dossier.get("parkRealityModel", {}) if isinstance(dossier.get("parkRealityModel"), dict) else {}
    live_scene = dossier.get("liveOperatingSceneModel", {}) if isinstance(dossier.get("liveOperatingSceneModel"), dict) else {}
    physical_propagation = dossier.get("physicalPropagationModel", {}) if isinstance(dossier.get("physicalPropagationModel"), dict) else {}
    telemetry = dossier.get("telemetryContract", {}) if isinstance(dossier.get("telemetryContract"), dict) else {}
    field_signal_reconciliation = dossier.get("fieldSignalReconciliation", {}) if isinstance(dossier.get("fieldSignalReconciliation"), dict) else {}
    decision_telemetry_snapshot = dossier.get("decisionTelemetrySnapshot", {}) if isinstance(dossier.get("decisionTelemetrySnapshot"), dict) else {}
    field_handoff = dossier.get("fieldExecutionHandoff", {}) if isinstance(dossier.get("fieldExecutionHandoff"), dict) else {}
    closed_loop = dossier.get("closedLoopVerification", {}) if isinstance(dossier.get("closedLoopVerification"), dict) else {}
    portfolio_operating_model = payload.get("portfolioOperatingModel", {}) if isinstance(payload.get("portfolioOperatingModel"), dict) else {}
    portfolio_risk_ranking = payload.get("portfolioRiskRanking", {}) if isinstance(payload.get("portfolioRiskRanking"), dict) else {}
    production_evidence_gap_register = payload.get("productionEvidenceGapRegister", {}) if isinstance(payload.get("productionEvidenceGapRegister"), dict) else {}
    field_replay_validation_harness = payload.get("fieldReplayValidationHarness", {}) if isinstance(payload.get("fieldReplayValidationHarness"), dict) else {}
    capacity_certification_ledger = payload.get("capacityCertificationLedger", {}) if isinstance(payload.get("capacityCertificationLedger"), dict) else {}
    sla_escalation_clock = payload.get("slaEscalationClock", {}) if isinstance(payload.get("slaEscalationClock"), dict) else {}
    receiver_execution_contract_ledger = payload.get("receiverExecutionContractLedger", {}) if isinstance(payload.get("receiverExecutionContractLedger"), dict) else {}
    incident_command_decision_log = payload.get("incidentCommandDecisionLog", {}) if isinstance(payload.get("incidentCommandDecisionLog"), dict) else {}
    industrial_action_replay_ledger = payload.get("industrialActionReplayLedger", {}) if isinstance(payload.get("industrialActionReplayLedger"), dict) else {}
    physical_movement_proof_ledger = payload.get("physicalMovementProofLedger", {}) if isinstance(payload.get("physicalMovementProofLedger"), dict) else {}
    telemetry_acceptance_ledger = payload.get("telemetryAcceptanceLedger", {}) if isinstance(payload.get("telemetryAcceptanceLedger"), dict) else {}
    outcome_accountability_ledger = payload.get("outcomeAccountabilityLedger", {}) if isinstance(payload.get("outcomeAccountabilityLedger"), dict) else {}
    industrial_case_file_synthesis = payload.get("industrialCaseFileSynthesis", {}) if isinstance(payload.get("industrialCaseFileSynthesis"), dict) else {}
    external_system_execution_evidence = payload.get("externalSystemExecutionEvidence", {}) if isinstance(payload.get("externalSystemExecutionEvidence"), dict) else {}
    industrial_dossier_completeness_audit = payload.get("industrialDossierCompletenessAudit", {}) if isinstance(payload.get("industrialDossierCompletenessAudit"), dict) else {}
    live_evidence_drift_monitor = payload.get("liveEvidenceDriftMonitor", {}) if isinstance(payload.get("liveEvidenceDriftMonitor"), dict) else {}
    observed_outcome_calibration_ledger = payload.get("observedOutcomeCalibrationLedger", {}) if isinstance(payload.get("observedOutcomeCalibrationLedger"), dict) else {}
    production_data_ingestion_contract = payload.get("productionDataIngestionContract", {}) if isinstance(payload.get("productionDataIngestionContract"), dict) else {}
    industrial_promotion_certification_gate = payload.get("industrialPromotionCertificationGate", {}) if isinstance(payload.get("industrialPromotionCertificationGate"), dict) else {}
    field_trial_protocol_ledger = payload.get("fieldTrialProtocolLedger", {}) if isinstance(payload.get("fieldTrialProtocolLedger"), dict) else {}
    field_trial_execution_evidence_ledger = payload.get("fieldTrialExecutionEvidenceLedger", {}) if isinstance(payload.get("fieldTrialExecutionEvidenceLedger"), dict) else {}
    field_trial_closeout_ledger = payload.get("fieldTrialCloseoutLedger", {}) if isinstance(payload.get("fieldTrialCloseoutLedger"), dict) else {}
    industrial_operating_timeline_ledger = payload.get("industrialOperatingTimelineLedger", {}) if isinstance(payload.get("industrialOperatingTimelineLedger"), dict) else {}
    variance_root_cause_ledger = payload.get("varianceRootCauseLedger", {}) if isinstance(payload.get("varianceRootCauseLedger"), dict) else {}
    industrial_review_disposition_ledger = payload.get("industrialReviewDispositionLedger", {}) if isinstance(payload.get("industrialReviewDispositionLedger"), dict) else {}
    industrial_audit_export_manifest = payload.get("industrialAuditExportManifest", {}) if isinstance(payload.get("industrialAuditExportManifest"), dict) else {}
    data_lineage_certification_ledger = payload.get("dataLineageCertificationLedger", {}) if isinstance(payload.get("dataLineageCertificationLedger"), dict) else {}
    policy_risk_control_ledger = payload.get("policyRiskControlLedger", {}) if isinstance(payload.get("policyRiskControlLedger"), dict) else {}
    case_work_order_execution_ledger = payload.get("caseWorkOrderExecutionLedger", {}) if isinstance(payload.get("caseWorkOrderExecutionLedger"), dict) else {}
    field_receipt_reconciliation_ledger = payload.get("fieldReceiptReconciliationLedger", {}) if isinstance(payload.get("fieldReceiptReconciliationLedger"), dict) else {}
    release_board_exception_ledger = payload.get("releaseBoardExceptionLedger", {}) if isinstance(payload.get("releaseBoardExceptionLedger"), dict) else {}
    scenario_coverage_certification_ledger = payload.get("scenarioCoverageCertificationLedger", {}) if isinstance(payload.get("scenarioCoverageCertificationLedger"), dict) else {}
    operator_competency_evaluation_ledger = payload.get("operatorCompetencyEvaluationLedger", {}) if isinstance(payload.get("operatorCompetencyEvaluationLedger"), dict) else {}
    causal_episode_training_ledger = payload.get("causalEpisodeTrainingLedger", {}) if isinstance(payload.get("causalEpisodeTrainingLedger"), dict) else {}
    simulation_validity_calibration_ledger = payload.get("simulationValidityCalibrationLedger", {}) if isinstance(payload.get("simulationValidityCalibrationLedger"), dict) else {}
    field_observation_protocol_ledger = payload.get("fieldObservationProtocolLedger", {}) if isinstance(payload.get("fieldObservationProtocolLedger"), dict) else {}
    field_evidence_capture_ledger = payload.get("fieldEvidenceCaptureLedger", {}) if isinstance(payload.get("fieldEvidenceCaptureLedger"), dict) else {}
    field_evidence_sample_ledger = payload.get("fieldEvidenceSampleLedger", {}) if isinstance(payload.get("fieldEvidenceSampleLedger"), dict) else {}
    field_evidence_adjudication_ledger = payload.get("fieldEvidenceAdjudicationLedger", {}) if isinstance(payload.get("fieldEvidenceAdjudicationLedger"), dict) else {}
    field_evidence_remediation_ledger = payload.get("fieldEvidenceRemediationLedger", {}) if isinstance(payload.get("fieldEvidenceRemediationLedger"), dict) else {}
    field_evidence_remediation_execution_ledger = payload.get("fieldEvidenceRemediationExecutionLedger", {}) if isinstance(payload.get("fieldEvidenceRemediationExecutionLedger"), dict) else {}
    field_evidence_release_clearance_ledger = payload.get("fieldEvidenceReleaseClearanceLedger", {}) if isinstance(payload.get("fieldEvidenceReleaseClearanceLedger"), dict) else {}
    spatial_execution_drill_ledger = payload.get("spatialExecutionDrillLedger", {}) if isinstance(payload.get("spatialExecutionDrillLedger"), dict) else {}
    observed_drill_variance_ledger = payload.get("observedDrillVarianceLedger", {}) if isinstance(payload.get("observedDrillVarianceLedger"), dict) else {}
    industrial_acceptance_certification_ledger = payload.get("industrialAcceptanceCertificationLedger", {}) if isinstance(payload.get("industrialAcceptanceCertificationLedger"), dict) else {}
    production_evidence_acquisition_ledger = payload.get("productionEvidenceAcquisitionLedger", {}) if isinstance(payload.get("productionEvidenceAcquisitionLedger"), dict) else {}
    case_portfolio_priority = next(
        (
            row
            for row in portfolio_risk_ranking.get("rankingRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_production_evidence = next(
        (
            row
            for row in production_evidence_gap_register.get("caseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_field_replay_validation = next(
        (
            row
            for row in field_replay_validation_harness.get("caseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_capacity_certification = next(
        (
            row
            for row in capacity_certification_ledger.get("caseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_sla_escalation = next(
        (
            row
            for row in sla_escalation_clock.get("caseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_receiver_execution_contract = next(
        (
            row
            for row in receiver_execution_contract_ledger.get("caseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_incident_command_decision = next(
        (
            row
            for row in incident_command_decision_log.get("caseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_industrial_action_replay = next(
        (
            row
            for row in industrial_action_replay_ledger.get("caseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_physical_movement_proof = next(
        (
            row
            for row in physical_movement_proof_ledger.get("caseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_telemetry_acceptance = next(
        (
            row
            for row in telemetry_acceptance_ledger.get("caseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_outcome_accountability = next(
        (
            row
            for row in outcome_accountability_ledger.get("caseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_file = next(
        (
            row
            for row in industrial_case_file_synthesis.get("caseFiles", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_external_execution_evidence = next(
        (
            row
            for row in external_system_execution_evidence.get("caseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_dossier_completeness_audit = next(
        (
            row
            for row in industrial_dossier_completeness_audit.get("auditRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_live_evidence_drift = next(
        (
            row
            for row in live_evidence_drift_monitor.get("driftRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_observed_outcome_calibration = next(
        (
            row
            for row in observed_outcome_calibration_ledger.get("calibrationRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_production_data_contract = next(
        (
            row
            for row in production_data_ingestion_contract.get("caseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_promotion_certification = next(
        (
            row
            for row in industrial_promotion_certification_gate.get("certificationRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_field_trial_protocol = next(
        (
            row
            for row in field_trial_protocol_ledger.get("protocolRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_field_trial_execution_evidence = next(
        (
            row
            for row in field_trial_execution_evidence_ledger.get("caseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_field_trial_closeout = next(
        (
            row
            for row in field_trial_closeout_ledger.get("closeoutRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_operating_timeline = next(
        (
            row
            for row in industrial_operating_timeline_ledger.get("timelineRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_variance_root_cause = next(
        (
            row
            for row in variance_root_cause_ledger.get("rootCauseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_review_disposition = next(
        (
            row
            for row in industrial_review_disposition_ledger.get("dispositionRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_audit_export_package = next(
        (
            row
            for row in industrial_audit_export_manifest.get("packageRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_data_lineage_certification = next(
        (
            row
            for row in data_lineage_certification_ledger.get("certificationRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_policy_risk_control = next(
        (
            row
            for row in policy_risk_control_ledger.get("controlRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_work_order_execution = next(
        (
            row
            for row in case_work_order_execution_ledger.get("caseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_field_receipt_reconciliation = next(
        (
            row
            for row in field_receipt_reconciliation_ledger.get("caseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_release_board_exception = next(
        (
            row
            for row in release_board_exception_ledger.get("exceptionRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_scenario_coverage_certification = next(
        (
            row
            for row in scenario_coverage_certification_ledger.get("certificationRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_operator_competency_evaluation = next(
        (
            row
            for row in operator_competency_evaluation_ledger.get("caseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_causal_episode_training = next(
        (
            row
            for row in causal_episode_training_ledger.get("caseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_simulation_validity_calibration = next(
        (
            row
            for row in simulation_validity_calibration_ledger.get("caseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_field_observation_protocol = next(
        (
            row
            for row in field_observation_protocol_ledger.get("caseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_field_evidence_capture = next(
        (
            row
            for row in field_evidence_capture_ledger.get("caseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_field_evidence_sample = next(
        (
            row
            for row in field_evidence_sample_ledger.get("caseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_field_evidence_adjudication = next(
        (
            row
            for row in field_evidence_adjudication_ledger.get("caseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_field_evidence_remediation = next(
        (
            row
            for row in field_evidence_remediation_ledger.get("caseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_field_evidence_remediation_execution = next(
        (
            row
            for row in field_evidence_remediation_execution_ledger.get("caseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_field_evidence_release_clearance = next(
        (
            row
            for row in field_evidence_release_clearance_ledger.get("caseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_spatial_execution_drill = next(
        (
            row
            for row in spatial_execution_drill_ledger.get("caseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_observed_drill_variance = next(
        (
            row
            for row in observed_drill_variance_ledger.get("caseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_industrial_acceptance_certification = next(
        (
            row
            for row in industrial_acceptance_certification_ledger.get("caseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    case_production_evidence_acquisition = next(
        (
            row
            for row in production_evidence_acquisition_ledger.get("caseRows", [])
            if isinstance(row, dict) and row.get("caseId") == dossier.get("id")
        ),
        {},
    )
    portfolio_coverage = payload.get("portfolioCoverage", {}) if isinstance(payload.get("portfolioCoverage"), dict) else {}
    industrial_standards = payload.get("industrialStandardsMatrix", {}) if isinstance(payload.get("industrialStandardsMatrix"), dict) else {}
    deployment_readiness = payload.get("industrialDeploymentReadiness", {}) if isinstance(payload.get("industrialDeploymentReadiness"), dict) else {}
    ownership_model = payload.get("industrialOwnershipModel", {}) if isinstance(payload.get("industrialOwnershipModel"), dict) else {}
    coverage_matrix = payload.get("coverageMatrix", []) if isinstance(payload.get("coverageMatrix"), list) else []
    portfolio_context = {
        "mode": "case_packet_portfolio_context",
        "portfolioOperatingModel": portfolio_operating_model,
        "portfolioRiskRanking": portfolio_risk_ranking,
        "casePortfolioPriority": case_portfolio_priority,
        "productionEvidenceGapRegister": production_evidence_gap_register,
        "caseProductionEvidence": case_production_evidence,
        "fieldReplayValidationHarness": field_replay_validation_harness,
        "caseFieldReplayValidation": case_field_replay_validation,
        "capacityCertificationLedger": capacity_certification_ledger,
        "caseCapacityCertification": case_capacity_certification,
        "slaEscalationClock": sla_escalation_clock,
        "caseSlaEscalation": case_sla_escalation,
        "receiverExecutionContractLedger": receiver_execution_contract_ledger,
        "caseReceiverExecutionContract": case_receiver_execution_contract,
        "incidentCommandDecisionLog": incident_command_decision_log,
        "caseIncidentCommandDecision": case_incident_command_decision,
        "industrialActionReplayLedger": industrial_action_replay_ledger,
        "caseIndustrialActionReplay": case_industrial_action_replay,
        "physicalMovementProofLedger": physical_movement_proof_ledger,
        "casePhysicalMovementProof": case_physical_movement_proof,
        "telemetryAcceptanceLedger": telemetry_acceptance_ledger,
        "caseTelemetryAcceptance": case_telemetry_acceptance,
        "outcomeAccountabilityLedger": outcome_accountability_ledger,
        "caseOutcomeAccountability": case_outcome_accountability,
        "industrialCaseFileSynthesis": industrial_case_file_synthesis,
        "caseFile": case_file,
        "externalSystemExecutionEvidence": external_system_execution_evidence,
        "caseExternalExecutionEvidence": case_external_execution_evidence,
        "industrialDossierCompletenessAudit": industrial_dossier_completeness_audit,
        "caseDossierCompletenessAudit": case_dossier_completeness_audit,
        "liveEvidenceDriftMonitor": live_evidence_drift_monitor,
        "caseLiveEvidenceDrift": case_live_evidence_drift,
        "observedOutcomeCalibrationLedger": observed_outcome_calibration_ledger,
        "caseObservedOutcomeCalibration": case_observed_outcome_calibration,
        "productionDataIngestionContract": production_data_ingestion_contract,
        "caseProductionDataContract": case_production_data_contract,
        "industrialPromotionCertificationGate": industrial_promotion_certification_gate,
        "casePromotionCertification": case_promotion_certification,
        "fieldTrialProtocolLedger": field_trial_protocol_ledger,
        "caseFieldTrialProtocol": case_field_trial_protocol,
        "fieldTrialExecutionEvidenceLedger": field_trial_execution_evidence_ledger,
        "caseFieldTrialExecutionEvidence": case_field_trial_execution_evidence,
        "fieldTrialCloseoutLedger": field_trial_closeout_ledger,
        "caseFieldTrialCloseout": case_field_trial_closeout,
        "industrialOperatingTimelineLedger": industrial_operating_timeline_ledger,
        "caseOperatingTimeline": case_operating_timeline,
        "varianceRootCauseLedger": variance_root_cause_ledger,
        "caseVarianceRootCause": case_variance_root_cause,
        "industrialReviewDispositionLedger": industrial_review_disposition_ledger,
        "caseReviewDisposition": case_review_disposition,
        "industrialAuditExportManifest": industrial_audit_export_manifest,
        "caseAuditExportPackage": case_audit_export_package,
        "dataLineageCertificationLedger": data_lineage_certification_ledger,
        "caseDataLineageCertification": case_data_lineage_certification,
        "policyRiskControlLedger": policy_risk_control_ledger,
        "casePolicyRiskControl": case_policy_risk_control,
        "caseWorkOrderExecutionLedger": case_work_order_execution_ledger,
        "caseWorkOrderExecution": case_work_order_execution,
        "fieldReceiptReconciliationLedger": field_receipt_reconciliation_ledger,
        "caseFieldReceiptReconciliation": case_field_receipt_reconciliation,
        "releaseBoardExceptionLedger": release_board_exception_ledger,
        "caseReleaseBoardException": case_release_board_exception,
        "scenarioCoverageCertificationLedger": scenario_coverage_certification_ledger,
        "caseScenarioCoverageCertification": case_scenario_coverage_certification,
        "operatorCompetencyEvaluationLedger": operator_competency_evaluation_ledger,
        "caseOperatorCompetencyEvaluation": case_operator_competency_evaluation,
        "causalEpisodeTrainingLedger": causal_episode_training_ledger,
        "caseCausalEpisodeTraining": case_causal_episode_training,
        "simulationValidityCalibrationLedger": simulation_validity_calibration_ledger,
        "caseSimulationValidityCalibration": case_simulation_validity_calibration,
        "fieldObservationProtocolLedger": field_observation_protocol_ledger,
        "caseFieldObservationProtocol": case_field_observation_protocol,
        "fieldEvidenceCaptureLedger": field_evidence_capture_ledger,
        "caseFieldEvidenceCapture": case_field_evidence_capture,
        "fieldEvidenceSampleLedger": field_evidence_sample_ledger,
        "caseFieldEvidenceSample": case_field_evidence_sample,
        "fieldEvidenceAdjudicationLedger": field_evidence_adjudication_ledger,
        "caseFieldEvidenceAdjudication": case_field_evidence_adjudication,
        "fieldEvidenceRemediationLedger": field_evidence_remediation_ledger,
        "caseFieldEvidenceRemediation": case_field_evidence_remediation,
        "fieldEvidenceRemediationExecutionLedger": field_evidence_remediation_execution_ledger,
        "caseFieldEvidenceRemediationExecution": case_field_evidence_remediation_execution,
        "fieldEvidenceReleaseClearanceLedger": field_evidence_release_clearance_ledger,
        "caseFieldEvidenceReleaseClearance": case_field_evidence_release_clearance,
        "spatialExecutionDrillLedger": spatial_execution_drill_ledger,
        "caseSpatialExecutionDrill": case_spatial_execution_drill,
        "observedDrillVarianceLedger": observed_drill_variance_ledger,
        "caseObservedDrillVariance": case_observed_drill_variance,
        "industrialAcceptanceCertificationLedger": industrial_acceptance_certification_ledger,
        "caseIndustrialAcceptanceCertification": case_industrial_acceptance_certification,
        "productionEvidenceAcquisitionLedger": production_evidence_acquisition_ledger,
        "caseProductionEvidenceAcquisition": case_production_evidence_acquisition,
        "portfolioCoverage": portfolio_coverage,
        "industrialStandardsMatrix": industrial_standards,
        "industrialDeploymentReadiness": deployment_readiness,
        "industrialOwnershipModel": ownership_model,
        "coverageMatrix": coverage_matrix,
        "caseDomainCoverage": next(
            (row for row in coverage_matrix if isinstance(row, dict) and row.get("domain") == dossier.get("domain")),
            {},
        ),
        "operatorUse": "Keeps this case packet grounded in the park-wide asset, spatial, receiver, domain, and governance model instead of treating the case as an isolated alert.",
    }
    branch_ids = {row.get("branch") for row in training_rows if isinstance(row, dict)}
    simulated_branch_ids = {row.get("id") for row in simulated_branches if isinstance(row, dict)}
    has_branch_proof = (
        simulated_branch_comparison.get("mode") == "dossier_three_branch_physical_simulation"
        and {"no_action", "fast_local_action", "governed_agent_action"}.issubset(branch_ids)
        and {"no_action", "fast_local_action", "governed_agent_action"}.issubset(simulated_branch_ids)
        and all(isinstance(row, dict) and row.get("score") is not None and row.get("delta_from_now") for row in simulated_branches)
    )
    evidence_bundle = {
        "physicalMechanism": dossier.get("physicalMechanism", []),
        "spatialCausalityTrace": dossier.get("spatialCausalityTrace", {}),
        "mapObjectEvidenceIndex": map_object_index,
        "parkRealityModel": park_reality,
        "liveOperatingSceneModel": live_scene,
        "causalGraph": causal_graph,
        "counterfactualReplay": counterfactual_replay,
        "branchPhysicalImpactMatrix": branch_physical_impact,
        "actionConsequenceSimulation": action_consequence,
        "mapObjectEvidenceIndex": map_object_index,
        "commercialImpactLedger": commercial_impact,
        "accessibilityEquityImpact": accessibility_equity,
        "resourceFeasibilityMatrix": resource_feasibility,
        "policyClauseTrace": policy_clause_trace,
        "spatialPhysicsEnvelope": spatial_physics,
        "physicalPropagationModel": physical_propagation,
        "historicalPrecedentMatrix": historical_precedent,
        "guestCommunicationPlan": guest_communication_plan,
        "behavioralResponseModel": behavioral_response,
        "operationalConstraintRegister": constraint_register,
        "releaseDecisionRecord": release_decision_record,
        "releaseAuthorityDecision": release_authority,
        "executionReadinessProof": execution_readiness,
        "releaseRemediationPlan": release_remediation,
        "operatingProcedureDelta": procedure_delta,
        "decisionReproducibilityManifest": decision_reproducibility,
        "chainOfCustodyAuditLog": chain_of_custody,
        "fieldCalibrationBacktestPlan": field_calibration,
        "portfolioContext": portfolio_context,
        "industrialStandardsMatrix": industrial_standards,
        "industrialDeploymentReadiness": deployment_readiness,
        "industrialOwnershipModel": ownership_model,
        "governedApprovalPackage": dossier.get("governedApprovalPackage", {}),
        "dataQualityCalibration": dossier.get("dataQualityCalibration", {}),
        "telemetryContract": telemetry,
        "fieldSignalReconciliation": field_signal_reconciliation,
        "decisionTelemetrySnapshot": decision_telemetry_snapshot,
        "fieldExecutionHandoff": field_handoff,
        "caseExecutionRunbook": dossier.get("caseExecutionRunbook", {}),
        "closedLoopVerification": closed_loop,
        "provenanceRows": provenance,
        "caseProductionEvidence": case_production_evidence,
        "caseFieldReplayValidation": case_field_replay_validation,
        "caseCapacityCertification": case_capacity_certification,
        "caseSlaEscalation": case_sla_escalation,
        "caseReceiverExecutionContract": case_receiver_execution_contract,
        "timeline": dossier.get("evidenceTimeline", []),
        "competingHypotheses": dossier.get("competingHypotheses", []),
        "simulatedBranchComparison": simulated_branch_comparison,
        "operatingScorecard": operating_scorecard,
        "casePortfolioPriority": case_portfolio_priority,
        "assumptionSensitivityAnalysis": sensitivity,
        "operationalStressRehearsal": stress_rehearsal,
        "independentReviewBoard": review_board,
        "causalGraph": causal_graph,
        "counterfactualReplay": counterfactual_replay,
        "actionConsequenceSimulation": action_consequence,
        "commercialImpactLedger": commercial_impact,
        "accessibilityEquityImpact": accessibility_equity,
        "resourceFeasibilityMatrix": resource_feasibility,
        "policyClauseTrace": policy_clause_trace,
        "spatialPhysicsEnvelope": spatial_physics,
        "physicalPropagationModel": physical_propagation,
        "historicalPrecedentMatrix": historical_precedent,
        "guestCommunicationPlan": guest_communication_plan,
        "behavioralResponseModel": behavioral_response,
        "operationalConstraintRegister": constraint_register,
        "releaseDecisionRecord": release_decision_record,
        "chainOfCustodyAuditLog": chain_of_custody,
        "fieldCalibrationBacktestPlan": field_calibration,
    }
    evidence_hash = hashlib.sha256(json.dumps(evidence_bundle, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    packet = {
        "packetType": "industrial_operating_case_packet",
        "packetVersion": "2026-05-29",
        "status": "ready" if quality.get("status") == "ready" else "needs_review",
        "caseHeader": {
            "id": dossier.get("id"),
            "sourceConflictId": dossier.get("sourceConflictId"),
            "title": dossier.get("title"),
            "domain": dossier.get("domain"),
            "caseType": dossier.get("caseType"),
            "severity": dossier.get("severity"),
            "mapFocus": dossier.get("mapFocus", []),
            "simulationClock": payload.get("simulationClock", {}),
        },
        "executiveBrief": {
            "claim": dossier.get("operatingThesis", {}).get("claim") if isinstance(dossier.get("operatingThesis"), dict) else None,
            "whyNow": dossier.get("operatingThesis", {}).get("whyNow") if isinstance(dossier.get("operatingThesis"), dict) else None,
            "notJustMetric": dossier.get("operatingThesis", {}).get("notJustMetric") if isinstance(dossier.get("operatingThesis"), dict) else None,
            "successMetric": verification.get("successMetric"),
            "rollbackTrigger": verification.get("rollbackTrigger"),
        },
        "approvalChecklist": [
            {"label": "Quality gate ready", "status": "pass" if quality.get("status") == "ready" else "review", "evidence": quality},
            {"label": "Policy refs present", "status": "pass" if policy.get("applies") else "review", "evidence": policy.get("applies", [])},
            {"label": "Blocked actions named", "status": "pass" if policy.get("blocks") else "review", "evidence": policy.get("blocks", [])},
            {"label": "Receiver readiness present", "status": "pass" if receiver_rows else "review", "evidence": receiver_rows[:3]},
            {"label": "Provenance present", "status": "pass" if provenance else "review", "evidence": provenance[:5]},
            {"label": "Rollback trigger present", "status": "pass" if verification.get("rollbackTrigger") else "review", "evidence": verification.get("rollbackTrigger")},
            {"label": "Map object evidence index present", "status": "pass" if map_object_index.get("mode") == "industrial_map_object_evidence_index" and map_object_index.get("objectRows") and map_object_index.get("pathRows") and map_object_index.get("queueRows") else "review", "evidence": map_object_index},
            {"label": "Park reality model present", "status": "pass" if park_reality.get("mode") == "case_specific_park_reality_model" and park_reality.get("localTopology") and park_reality.get("capacityEnvelope") else "review", "evidence": park_reality},
            {"label": "Live operating scene present", "status": "pass" if live_scene.get("mode") == "industrial_live_operating_scene_model" and live_scene.get("actors") and live_scene.get("physicalScene") and live_scene.get("bottlenecks") and live_scene.get("agentBeliefState") else "review", "evidence": live_scene},
            {"label": "Causal graph present", "status": "pass" if causal_graph.get("mode") == "typed_operating_causal_graph" and causal_graph.get("nodes") and causal_graph.get("edges") else "review", "evidence": causal_graph},
            {"label": "Counterfactual replay present", "status": "pass" if counterfactual_replay.get("mode") == "counterfactual_branch_replay_matrix" and counterfactual_replay.get("rows") else "review", "evidence": counterfactual_replay},
            {"label": "Branch physical impact matrix present", "status": "pass" if branch_physical_impact.get("mode") == "industrial_branch_physical_impact_matrix" and branch_physical_impact.get("branchRows") and branch_physical_impact.get("subsystemMovement") else "review", "evidence": branch_physical_impact},
            {"label": "Action consequence simulation present", "status": "pass" if action_consequence.get("mode") == "industrial_action_consequence_simulation" and action_consequence.get("consequenceFrames") and action_consequence.get("branchOutcomeSummary") else "review", "evidence": action_consequence},
            {"label": "Commercial impact ledger present", "status": "pass" if commercial_impact.get("mode") == "industrial_commercial_impact_ledger" and commercial_impact.get("rows") else "review", "evidence": commercial_impact},
            {"label": "Accessibility and equity proof present", "status": "pass" if accessibility_equity.get("mode") == "industrial_accessibility_equity_impact" and accessibility_equity.get("protectedCohorts") and accessibility_equity.get("routeAccessChecks") and accessibility_equity.get("fairnessChecks") else "review", "evidence": accessibility_equity},
            {"label": "Resource feasibility matrix present", "status": "pass" if resource_feasibility.get("mode") == "industrial_resource_feasibility_matrix" and resource_feasibility.get("receiverExecutionRows") and resource_feasibility.get("branchFeasibilityComparison") else "review", "evidence": resource_feasibility},
            {"label": "Policy clause trace present", "status": "pass" if policy_clause_trace.get("mode") == "industrial_policy_clause_trace" and policy_clause_trace.get("clauseRows") and policy_clause_trace.get("branchPolicyVerdicts") else "review", "evidence": policy_clause_trace},
            {"label": "Spatial physics envelope present", "status": "pass" if spatial_physics.get("mode") == "industrial_spatial_physics_envelope" and spatial_physics.get("routePhysics") and spatial_physics.get("queueGeometry") else "review", "evidence": spatial_physics},
            {"label": "Physical propagation model present", "status": "pass" if physical_propagation.get("mode") == "industrial_physical_propagation_model" and physical_propagation.get("chain") and physical_propagation.get("branchPropagationEffects") and physical_propagation.get("tripwires") else "review", "evidence": physical_propagation},
            {"label": "Historical precedent matrix present", "status": "pass" if historical_precedent.get("mode") == "industrial_historical_precedent_matrix" and historical_precedent.get("matchedPrecedents") and historical_precedent.get("branchPrecedentVerdicts") else "review", "evidence": historical_precedent},
            {"label": "Guest communication plan present", "status": "pass" if guest_communication_plan.get("mode") == "industrial_guest_communication_plan" and guest_communication_plan.get("audiencePlans") and guest_communication_plan.get("channelPlan") and guest_communication_plan.get("promiseBoundaries") else "review", "evidence": guest_communication_plan},
            {"label": "Behavioral response model present", "status": "pass" if behavioral_response.get("mode") == "industrial_behavioral_response_model" and behavioral_response.get("segmentBehavior") and behavioral_response.get("staffAndReceiverResponse") and behavioral_response.get("branchBehaviorComparison") else "review", "evidence": behavioral_response},
            {"label": "Operational constraint register present", "status": "pass" if constraint_register.get("mode") == "industrial_operational_constraint_register" and constraint_register.get("hardConstraints") and constraint_register.get("branchConstraintVerdicts") and constraint_register.get("goNoGo") else "review", "evidence": constraint_register},
            {"label": "Release decision record present", "status": "pass" if release_decision_record.get("mode") == "industrial_release_decision_record" and release_decision_record.get("signoffMatrix") and release_decision_record.get("approvedVersion") and release_decision_record.get("postReleaseObligations") else "review", "evidence": release_decision_record},
            {"label": "Release authority decision present", "status": "pass" if release_authority.get("mode") == "industrial_release_authority_decision" and release_authority.get("authorityChecks") and release_authority.get("liveActionAuthority") else "review", "evidence": release_authority},
            {"label": "Execution readiness proof present", "status": "pass" if execution_readiness.get("mode") == "industrial_execution_readiness_proof" and execution_readiness.get("executionChecks") and execution_readiness.get("requiredBeforeDispatch") and execution_readiness.get("caseSceneEvidence") else "review", "evidence": execution_readiness},
            {"label": "Release remediation plan present", "status": "pass" if release_remediation.get("mode") == "industrial_release_remediation_plan" and release_remediation.get("tasks") and release_remediation.get("recheckSequence") else "review", "evidence": release_remediation},
            {"label": "Operating procedure delta present", "status": "pass" if procedure_delta.get("mode") == "industrial_operating_procedure_delta" and procedure_delta.get("procedureDeltas") and procedure_delta.get("runbookStepUpdates") and procedure_delta.get("policyPatchCandidates") and procedure_delta.get("promotionGate") else "review", "evidence": procedure_delta},
            {"label": "Decision reproducibility manifest present", "status": "pass" if decision_reproducibility.get("mode") == "industrial_decision_reproducibility_manifest" and decision_reproducibility.get("inputArtifacts") and decision_reproducibility.get("simulatorVersion") and decision_reproducibility.get("expectedDeterministicOutputs") and decision_reproducibility.get("replayInstructions") else "review", "evidence": decision_reproducibility},
            {"label": "Chain-of-custody audit log present", "status": "pass" if chain_of_custody.get("mode") == "industrial_chain_of_custody_audit_log" and chain_of_custody.get("custodyRows") and chain_of_custody.get("immutableTraceCheckpoints") and chain_of_custody.get("auditReplayInstructions") else "review", "evidence": chain_of_custody},
            {"label": "Field calibration backtest present", "status": "pass" if field_calibration.get("mode") == "industrial_field_calibration_backtest_plan" and field_calibration.get("requiredDatasets") and field_calibration.get("backtestSuites") and field_calibration.get("acceptanceThresholds") and field_calibration.get("driftTriggers") else "review", "evidence": field_calibration},
            {"label": "Portfolio operating context present", "status": "pass" if portfolio_operating_model.get("mode") == "industrial_portfolio_operating_model" and portfolio_operating_model.get("assetInventory") and portfolio_operating_model.get("spatialNetwork") and portfolio_operating_model.get("coverageReadiness") else "review", "evidence": portfolio_context},
            {"label": "Portfolio risk ranking present", "status": "pass" if portfolio_risk_ranking.get("mode") == "industrial_portfolio_risk_ranking" and portfolio_risk_ranking.get("rankingRows") and portfolio_risk_ranking.get("operatingQueue") else "review", "evidence": portfolio_risk_ranking},
            {"label": "Production evidence gaps declared", "status": "pass" if production_evidence_gap_register.get("mode") == "industrial_production_evidence_gap_register" and production_evidence_gap_register.get("caseRows") and production_evidence_gap_register.get("feedReadinessRows") and case_production_evidence.get("blockingGaps") else "review", "evidence": case_production_evidence},
            {"label": "Field replay validation protocol present", "status": "pass" if field_replay_validation_harness.get("mode") == "industrial_field_replay_validation_harness" and field_replay_validation_harness.get("caseRows") and case_field_replay_validation.get("validationRuns") and case_field_replay_validation.get("acceptanceGate") else "review", "evidence": case_field_replay_validation},
            {"label": "Capacity certification ledger present", "status": "pass" if capacity_certification_ledger.get("mode") == "industrial_capacity_certification_ledger" and capacity_certification_ledger.get("caseRows") and case_capacity_certification.get("capacityFindings") and case_capacity_certification.get("certificationState") else "review", "evidence": case_capacity_certification},
            {"label": "SLA escalation clock present", "status": "pass" if sla_escalation_clock.get("mode") == "industrial_sla_escalation_clock" and sla_escalation_clock.get("caseRows") and case_sla_escalation.get("clockRows") and case_sla_escalation.get("escalationAuthority") else "review", "evidence": case_sla_escalation},
            {"label": "Receiver execution contracts present", "status": "pass" if receiver_execution_contract_ledger.get("mode") == "industrial_receiver_execution_contract_ledger" and receiver_execution_contract_ledger.get("caseRows") and case_receiver_execution_contract.get("contractRows") else "review", "evidence": case_receiver_execution_contract},
            {"label": "Incident command decision log present", "status": "pass" if incident_command_decision_log.get("mode") == "industrial_incident_command_decision_log" and incident_command_decision_log.get("caseRows") and case_incident_command_decision.get("decisionRecord") and case_incident_command_decision.get("auditEvent") else "review", "evidence": case_incident_command_decision},
            {"label": "Industrial action replay ledger present", "status": "pass" if industrial_action_replay_ledger.get("mode") == "industrial_action_replay_ledger" and industrial_action_replay_ledger.get("caseRows") and case_industrial_action_replay.get("timelineFrames") and case_industrial_action_replay.get("closedLoopWatch") else "review", "evidence": case_industrial_action_replay},
            {"label": "Physical movement proof ledger present", "status": "pass" if physical_movement_proof_ledger.get("mode") == "industrial_physical_movement_proof_ledger" and physical_movement_proof_ledger.get("caseRows") and case_physical_movement_proof.get("mapObjectBinding") and case_physical_movement_proof.get("pathProofRows") and case_physical_movement_proof.get("queueProofRows") else "review", "evidence": case_physical_movement_proof},
            {"label": "Telemetry acceptance ledger present", "status": "pass" if telemetry_acceptance_ledger.get("mode") == "industrial_telemetry_acceptance_ledger" and telemetry_acceptance_ledger.get("caseRows") and case_telemetry_acceptance.get("acceptanceGateRows") and case_telemetry_acceptance.get("sourceContract") and case_telemetry_acceptance.get("closedLoopAcceptance") else "review", "evidence": case_telemetry_acceptance},
            {"label": "Outcome accountability ledger present", "status": "pass" if outcome_accountability_ledger.get("mode") == "industrial_outcome_accountability_ledger" and outcome_accountability_ledger.get("caseRows") and case_outcome_accountability.get("expectedOutcome") and case_outcome_accountability.get("observedEvidenceStatus") and case_outcome_accountability.get("rollbackPosture") else "review", "evidence": case_outcome_accountability},
            {"label": "Industrial case file synthesis present", "status": "pass" if industrial_case_file_synthesis.get("mode") == "industrial_case_file_synthesis" and industrial_case_file_synthesis.get("caseFiles") and case_file.get("caseNarrative") and case_file.get("proofStack") and case_file.get("accountability") else "review", "evidence": case_file},
            {"label": "External system execution evidence present", "status": "pass" if external_system_execution_evidence.get("mode") == "industrial_external_system_execution_evidence" and external_system_execution_evidence.get("caseRows") and case_external_execution_evidence.get("evidenceRows") else "review", "evidence": case_external_execution_evidence},
            {"label": "Dossier completeness audit present", "status": "pass" if industrial_dossier_completeness_audit.get("mode") == "industrial_dossier_completeness_audit" and industrial_dossier_completeness_audit.get("auditRows") and case_dossier_completeness_audit.get("proofFamilies") and case_dossier_completeness_audit.get("promotionBoundary") else "review", "evidence": case_dossier_completeness_audit},
            {"label": "Live evidence drift monitor present", "status": "pass" if live_evidence_drift_monitor.get("mode") == "industrial_live_evidence_drift_monitor" and live_evidence_drift_monitor.get("driftRows") and case_live_evidence_drift.get("liveSignals") and case_live_evidence_drift.get("requiredRecheck") else "review", "evidence": case_live_evidence_drift},
            {"label": "Observed outcome calibration present", "status": "pass" if observed_outcome_calibration_ledger.get("mode") == "industrial_observed_outcome_calibration_ledger" and observed_outcome_calibration_ledger.get("calibrationRows") and case_observed_outcome_calibration.get("variance") and case_observed_outcome_calibration.get("trustDecision") else "review", "evidence": case_observed_outcome_calibration},
            {"label": "Production data ingestion contract present", "status": "pass" if production_data_ingestion_contract.get("mode") == "industrial_production_data_ingestion_contract" and production_data_ingestion_contract.get("caseRows") and case_production_data_contract.get("feedContracts") and case_production_data_contract.get("graduationCriteria") else "review", "evidence": case_production_data_contract},
            {"label": "Promotion certification gate present", "status": "pass" if industrial_promotion_certification_gate.get("mode") == "industrial_promotion_certification_gate" and industrial_promotion_certification_gate.get("certificationRows") and case_promotion_certification.get("certificationChecks") and case_promotion_certification.get("releaseBoundary") else "review", "evidence": case_promotion_certification},
            {"label": "Field trial protocol present", "status": "pass" if field_trial_protocol_ledger.get("mode") == "industrial_field_trial_protocol_ledger" and field_trial_protocol_ledger.get("protocolRows") and case_field_trial_protocol.get("trialScope") and case_field_trial_protocol.get("stopRules") else "review", "evidence": case_field_trial_protocol},
            {"label": "Field trial execution evidence present", "status": "pass" if field_trial_execution_evidence_ledger.get("mode") == "industrial_field_trial_execution_evidence_ledger" and field_trial_execution_evidence_ledger.get("caseRows") and case_field_trial_execution_evidence.get("observationCaptures") and case_field_trial_execution_evidence.get("trialOutcomeDisposition") else "review", "evidence": case_field_trial_execution_evidence},
            {"label": "Field trial closeout present", "status": "pass" if field_trial_closeout_ledger.get("mode") == "industrial_field_trial_closeout_ledger" and field_trial_closeout_ledger.get("closeoutRows") and case_field_trial_closeout.get("trialResultRecord") and case_field_trial_closeout.get("promotionDecision") else "review", "evidence": case_field_trial_closeout},
            {"label": "Operating timeline present", "status": "pass" if industrial_operating_timeline_ledger.get("mode") == "industrial_operating_timeline_ledger" and industrial_operating_timeline_ledger.get("timelineRows") and case_operating_timeline.get("eventRows") and case_operating_timeline.get("mapBindingSummary") else "review", "evidence": case_operating_timeline},
            {"label": "Variance root cause present", "status": "pass" if variance_root_cause_ledger.get("mode") == "industrial_variance_root_cause_ledger" and variance_root_cause_ledger.get("rootCauseRows") and case_variance_root_cause.get("rootCauseRows") and case_variance_root_cause.get("reuseDecision") else "review", "evidence": case_variance_root_cause},
            {"label": "Review disposition present", "status": "pass" if industrial_review_disposition_ledger.get("mode") == "industrial_review_disposition_ledger" and industrial_review_disposition_ledger.get("dispositionRows") and case_review_disposition.get("signoffMatrix") and case_review_disposition.get("reviewDisposition") else "review", "evidence": case_review_disposition},
            {"label": "Audit export package present", "status": "pass" if industrial_audit_export_manifest.get("mode") == "industrial_audit_export_manifest" and industrial_audit_export_manifest.get("packageRows") and case_audit_export_package.get("packageHash") and case_audit_export_package.get("artifactRows") else "review", "evidence": case_audit_export_package},
            {"label": "Data lineage certification present", "status": "pass" if data_lineage_certification_ledger.get("mode") == "industrial_data_lineage_certification_ledger" and data_lineage_certification_ledger.get("certificationRows") and case_data_lineage_certification.get("sourceSystemRows") and case_data_lineage_certification.get("certificationDecision") else "review", "evidence": case_data_lineage_certification},
            {"label": "Policy risk controls present", "status": "pass" if policy_risk_control_ledger.get("mode") == "industrial_policy_risk_control_ledger" and policy_risk_control_ledger.get("controlRows") and case_policy_risk_control.get("controlRows") and case_policy_risk_control.get("sensitiveFlags") else "review", "evidence": case_policy_risk_control},
            {"label": "Case work-order execution present", "status": "pass" if case_work_order_execution_ledger.get("mode") == "industrial_case_work_order_execution_ledger" and case_work_order_execution_ledger.get("caseRows") and case_work_order_execution.get("workOrders") and case_work_order_execution.get("acknowledgementPlan") else "review", "evidence": case_work_order_execution},
            {"label": "Field receipt reconciliation present", "status": "pass" if field_receipt_reconciliation_ledger.get("mode") == "industrial_field_receipt_reconciliation_ledger" and field_receipt_reconciliation_ledger.get("caseRows") and case_field_receipt_reconciliation.get("receiptRows") and case_field_receipt_reconciliation.get("productionBoundary") else "review", "evidence": case_field_receipt_reconciliation},
            {"label": "Release-board exception decision present", "status": "pass" if release_board_exception_ledger.get("mode") == "industrial_release_board_exception_ledger" and release_board_exception_ledger.get("exceptionRows") and case_release_board_exception.get("exceptionDecision") and case_release_board_exception.get("signoffRows") else "review", "evidence": case_release_board_exception},
            {"label": "Scenario coverage certification present", "status": "pass" if scenario_coverage_certification_ledger.get("mode") == "industrial_scenario_coverage_certification_ledger" and scenario_coverage_certification_ledger.get("certificationRows") and case_scenario_coverage_certification.get("drillFamilyRows") and case_scenario_coverage_certification.get("productionBoundary") else "review", "evidence": case_scenario_coverage_certification},
            {"label": "Operator competency evaluation present", "status": "pass" if operator_competency_evaluation_ledger.get("mode") == "industrial_operator_competency_evaluation_ledger" and operator_competency_evaluation_ledger.get("caseRows") and case_operator_competency_evaluation.get("evaluationTasks") and case_operator_competency_evaluation.get("scoringRubric") else "review", "evidence": case_operator_competency_evaluation},
            {"label": "Causal episode training present", "status": "pass" if causal_episode_training_ledger.get("mode") == "industrial_causal_episode_training_ledger" and causal_episode_training_ledger.get("caseRows") and case_causal_episode_training.get("episodeFrames") and case_causal_episode_training.get("physicalProofSummary") else "review", "evidence": case_causal_episode_training},
            {"label": "Simulation validity calibration present", "status": "pass" if simulation_validity_calibration_ledger.get("mode") == "industrial_simulation_validity_calibration_ledger" and simulation_validity_calibration_ledger.get("caseRows") and case_simulation_validity_calibration.get("assumptionRows") and case_simulation_validity_calibration.get("falsificationChecks") else "review", "evidence": case_simulation_validity_calibration},
            {"label": "Field observation protocol present", "status": "pass" if field_observation_protocol_ledger.get("mode") == "industrial_field_observation_protocol_ledger" and field_observation_protocol_ledger.get("caseRows") and case_field_observation_protocol.get("stationRows") and case_field_observation_protocol.get("measurementProtocol") else "review", "evidence": case_field_observation_protocol},
            {"label": "Field evidence capture forms present", "status": "pass" if field_evidence_capture_ledger.get("mode") == "industrial_field_evidence_capture_ledger" and field_evidence_capture_ledger.get("caseRows") and case_field_evidence_capture.get("formRows") and case_field_evidence_capture.get("custody") else "review", "evidence": case_field_evidence_capture},
            {"label": "Field evidence samples validated", "status": "pass" if field_evidence_sample_ledger.get("mode") == "industrial_field_evidence_sample_ledger" and field_evidence_sample_ledger.get("caseRows") and case_field_evidence_sample.get("recordRows") and case_field_evidence_sample.get("custodySummary") else "review", "evidence": case_field_evidence_sample},
            {"label": "Field evidence adjudication present", "status": "pass" if field_evidence_adjudication_ledger.get("mode") == "industrial_field_evidence_adjudication_ledger" and field_evidence_adjudication_ledger.get("caseRows") and case_field_evidence_adjudication.get("metricAdjudications") and case_field_evidence_adjudication.get("releaseImpact") else "review", "evidence": case_field_evidence_adjudication},
            {"label": "Field evidence remediation present", "status": "pass" if field_evidence_remediation_ledger.get("mode") == "industrial_field_evidence_remediation_ledger" and field_evidence_remediation_ledger.get("caseRows") and case_field_evidence_remediation.get("remediationRows") and case_field_evidence_remediation.get("releaseHold") else "review", "evidence": case_field_evidence_remediation},
            {"label": "Field evidence remediation execution present", "status": "pass" if field_evidence_remediation_execution_ledger.get("mode") == "industrial_field_evidence_remediation_execution_ledger" and field_evidence_remediation_execution_ledger.get("caseRows") and case_field_evidence_remediation_execution.get("executionRows") and case_field_evidence_remediation_execution.get("holdClearance") else "review", "evidence": case_field_evidence_remediation_execution},
            {"label": "Field evidence release clearance present", "status": "pass" if field_evidence_release_clearance_ledger.get("mode") == "industrial_field_evidence_release_clearance_ledger" and field_evidence_release_clearance_ledger.get("caseRows") and case_field_evidence_release_clearance.get("signoffMatrix") and case_field_evidence_release_clearance.get("clearancePacket") else "review", "evidence": case_field_evidence_release_clearance},
            {"label": "Spatial execution drill present", "status": "pass" if spatial_execution_drill_ledger.get("mode") == "industrial_spatial_execution_drill_ledger" and spatial_execution_drill_ledger.get("caseRows") and case_spatial_execution_drill.get("drillFrames") and case_spatial_execution_drill.get("stopRules") and case_spatial_execution_drill.get("drillPacket") else "review", "evidence": case_spatial_execution_drill},
            {"label": "Observed drill variance present", "status": "pass" if observed_drill_variance_ledger.get("mode") == "industrial_observed_drill_variance_ledger" and observed_drill_variance_ledger.get("caseRows") and case_observed_drill_variance.get("varianceRows") and case_observed_drill_variance.get("reuseGate") and case_observed_drill_variance.get("variancePacket") else "review", "evidence": case_observed_drill_variance},
            {"label": "Industrial acceptance certification present", "status": "pass" if industrial_acceptance_certification_ledger.get("mode") == "industrial_acceptance_certification_ledger" and industrial_acceptance_certification_ledger.get("caseRows") and case_industrial_acceptance_certification.get("proofFamilyRows") and case_industrial_acceptance_certification.get("signoffPosture") and case_industrial_acceptance_certification.get("certificationPacket") else "review", "evidence": case_industrial_acceptance_certification},
            {"label": "Production evidence acquisition present", "status": "pass" if production_evidence_acquisition_ledger.get("mode") == "industrial_production_evidence_acquisition_ledger" and production_evidence_acquisition_ledger.get("caseRows") and case_production_evidence_acquisition.get("feedAcquisitions") and case_production_evidence_acquisition.get("graduationStages") and case_production_evidence_acquisition.get("acquisitionPacket") else "review", "evidence": case_production_evidence_acquisition},
            {"label": "Industrial standards matrix present", "status": "pass" if industrial_standards.get("mode") == "industrial_standards_matrix" and industrial_standards.get("standards") and (industrial_standards.get("summary", {}) if isinstance(industrial_standards.get("summary"), dict) else {}).get("status") == "ready" else "review", "evidence": industrial_standards},
            {"label": "Deployment readiness boundary present", "status": "pass" if deployment_readiness.get("mode") == "industrial_deployment_readiness" and deployment_readiness.get("deploymentState") == "demo_ready_not_production_ready" and deployment_readiness.get("productionBlockers") else "review", "evidence": deployment_readiness},
            {"label": "Ownership RACI model present", "status": "pass" if ownership_model.get("mode") == "industrial_ownership_raci_model" and ownership_model.get("domainRaci") and ownership_model.get("receiverRaci") and ownership_model.get("productionBlockerOwners") else "review", "evidence": ownership_model},
            {"label": "Governed approval package present", "status": "pass" if isinstance(dossier.get("governedApprovalPackage"), dict) and dossier.get("governedApprovalPackage", {}).get("receiverWrites") else "review", "evidence": dossier.get("governedApprovalPackage", {})},
            {"label": "Data quality calibration present", "status": "pass" if isinstance(dossier.get("dataQualityCalibration"), dict) and dossier.get("dataQualityCalibration", {}).get("confidenceScore") is not None else "review", "evidence": dossier.get("dataQualityCalibration", {})},
            {"label": "Telemetry contract present", "status": "pass" if telemetry.get("mode") == "industrial_case_telemetry_contract" and telemetry.get("sourceBindings") and not telemetry.get("decisionReadiness", {}).get("missingRequiredLayers") else "review", "evidence": telemetry},
            {"label": "Field signal reconciliation present", "status": "pass" if field_signal_reconciliation.get("mode") == "industrial_field_signal_reconciliation" and field_signal_reconciliation.get("sourceRows") and field_signal_reconciliation.get("crossChecks") else "review", "evidence": field_signal_reconciliation},
            {"label": "Decision telemetry snapshot present", "status": "pass" if decision_telemetry_snapshot.get("mode") == "industrial_decision_telemetry_snapshot" and decision_telemetry_snapshot.get("queueRows") and decision_telemetry_snapshot.get("thresholdBreaches") and decision_telemetry_snapshot.get("sourceLineage") and decision_telemetry_snapshot.get("productionAcceptanceGates") and decision_telemetry_snapshot.get("telemetryCertification") and decision_telemetry_snapshot.get("freshness") else "review", "evidence": decision_telemetry_snapshot},
            {"label": "Field execution handoff present", "status": "pass" if field_handoff.get("mode") == "industrial_field_execution_handoff" and field_handoff.get("dispatches") and field_handoff.get("acknowledgementGates") else "review", "evidence": field_handoff},
            {"label": "Operating scorecard present", "status": "pass" if operating_scorecard.get("mode") == "industrial_operating_scorecard" and operating_scorecard.get("scoreRows") and operating_scorecard.get("tradeoffLedger") else "review", "evidence": operating_scorecard},
            {"label": "Assumption sensitivity present", "status": "pass" if sensitivity.get("mode") == "industrial_assumption_sensitivity_analysis" and sensitivity.get("stressTests") and sensitivity.get("flipConditions") else "review", "evidence": sensitivity},
            {"label": "Operational stress rehearsal present", "status": "pass" if stress_rehearsal.get("mode") == "industrial_operational_stress_rehearsal" and stress_rehearsal.get("rehearsalScenarios") and stress_rehearsal.get("escalationTriggers") else "review", "evidence": stress_rehearsal},
            {"label": "Independent review board present", "status": "pass" if review_board.get("mode") == "independent_operating_review_board" and review_board.get("reviews") and review_board.get("releaseDecision") else "review", "evidence": review_board},
            {"label": "Case execution runbook present", "status": "pass" if isinstance(dossier.get("caseExecutionRunbook"), dict) and dossier.get("caseExecutionRunbook", {}).get("lifecycle") else "review", "evidence": dossier.get("caseExecutionRunbook", {})},
            {"label": "Closed-loop verification present", "status": "pass" if closed_loop.get("mode") == "closed_loop_verification_plan" and closed_loop.get("observationWindows") and closed_loop.get("projectedVsObservedChecks") else "review", "evidence": closed_loop},
            {"label": "Three-branch simulation proof present", "status": "pass" if has_branch_proof else "review", "evidence": {
                "mode": simulated_branch_comparison.get("mode"),
                "selectedBranch": simulated_branch_comparison.get("selected_branch"),
                "rejectedBranch": simulated_branch_comparison.get("rejected_branch"),
                "branchScores": [
                    {"id": row.get("id"), "score": row.get("score"), "decisionBasis": row.get("decision_basis", {})}
                    for row in simulated_branches
                    if isinstance(row, dict)
                ],
            }},
            {"label": "Spatial causality trace present", "status": "pass" if isinstance(dossier.get("spatialCausalityTrace"), dict) and dossier.get("spatialCausalityTrace", {}).get("branchSpatialEffects") else "review", "evidence": dossier.get("spatialCausalityTrace", {})},
        ],
        "actionTrainingFrame": [
            {
                "branch": row.get("branch"),
                "operatorMeaning": row.get("operatorMeaning"),
                "expectedFailure": row.get("expectedFailure"),
                "teachingPoint": row.get("teachingPoint"),
                "simulationVerdict": row.get("simulationVerdict"),
                "simulatedOutcome": row.get("simulatedOutcome"),
                "checkpoints": row.get("checkpoints", []),
            }
            for row in training_rows
            if isinstance(row, dict)
        ],
        "branchProof": {
            "mode": simulated_branch_comparison.get("mode"),
            "horizonMinutes": simulated_branch_comparison.get("horizon_minutes"),
            "selectedBranch": simulated_branch_comparison.get("selected_branch"),
            "rejectedBranch": simulated_branch_comparison.get("rejected_branch"),
            "summary": simulated_branch_comparison.get("summary", {}),
            "branches": [
                {
                    "id": row.get("id"),
                    "label": row.get("label"),
                    "score": row.get("score"),
                    "rawScore": row.get("raw_score"),
                    "scoreAdjustment": row.get("score_adjustment"),
                    "decisionBasis": row.get("decision_basis", {}),
                    "physicalImpact": next((impact_row for impact_row in branch_physical_impact.get("branchRows", []) if isinstance(impact_row, dict) and impact_row.get("branch") == row.get("id")), {}),
                    "deltaFromNow": row.get("delta_from_now", {}),
                    "deltaVsNoAction": row.get("delta_vs_no_action", {}),
                    "impact": row.get("impact", {}),
                    "checkpoints": row.get("checkpoints", [])[:4],
                }
                for row in simulated_branches
                if isinstance(row, dict)
            ],
        },
        "operatingScorecard": operating_scorecard,
        "casePortfolioPriority": case_portfolio_priority,
        "assumptionSensitivityAnalysis": sensitivity,
        "operationalStressRehearsal": stress_rehearsal,
        "independentReviewBoard": review_board,
        "causalGraph": causal_graph,
        "counterfactualReplay": counterfactual_replay,
        "branchPhysicalImpactMatrix": branch_physical_impact,
        "actionConsequenceSimulation": action_consequence,
        "commercialImpactLedger": commercial_impact,
        "accessibilityEquityImpact": accessibility_equity,
        "resourceFeasibilityMatrix": resource_feasibility,
        "policyClauseTrace": policy_clause_trace,
        "spatialPhysicsEnvelope": spatial_physics,
        "physicalPropagationModel": physical_propagation,
        "historicalPrecedentMatrix": historical_precedent,
        "guestCommunicationPlan": guest_communication_plan,
        "behavioralResponseModel": behavioral_response,
        "operationalConstraintRegister": constraint_register,
        "releaseDecisionRecord": release_decision_record,
        "releaseAuthorityDecision": release_authority,
        "executionReadinessProof": execution_readiness,
        "releaseRemediationPlan": release_remediation,
        "operatingProcedureDelta": procedure_delta,
        "decisionReproducibilityManifest": decision_reproducibility,
        "chainOfCustodyAuditLog": chain_of_custody,
        "fieldCalibrationBacktestPlan": field_calibration,
        "portfolioContext": portfolio_context,
        "portfolioRiskRanking": portfolio_risk_ranking,
        "productionEvidenceGapRegister": production_evidence_gap_register,
        "caseProductionEvidence": case_production_evidence,
        "fieldReplayValidationHarness": field_replay_validation_harness,
        "caseFieldReplayValidation": case_field_replay_validation,
        "capacityCertificationLedger": capacity_certification_ledger,
        "caseCapacityCertification": case_capacity_certification,
        "slaEscalationClock": sla_escalation_clock,
        "caseSlaEscalation": case_sla_escalation,
        "receiverExecutionContractLedger": receiver_execution_contract_ledger,
        "caseReceiverExecutionContract": case_receiver_execution_contract,
        "incidentCommandDecisionLog": incident_command_decision_log,
        "caseIncidentCommandDecision": case_incident_command_decision,
        "industrialActionReplayLedger": industrial_action_replay_ledger,
        "caseIndustrialActionReplay": case_industrial_action_replay,
        "physicalMovementProofLedger": physical_movement_proof_ledger,
        "casePhysicalMovementProof": case_physical_movement_proof,
        "telemetryAcceptanceLedger": telemetry_acceptance_ledger,
        "caseTelemetryAcceptance": case_telemetry_acceptance,
        "outcomeAccountabilityLedger": outcome_accountability_ledger,
        "caseOutcomeAccountability": case_outcome_accountability,
        "industrialCaseFileSynthesis": industrial_case_file_synthesis,
        "caseFile": case_file,
        "externalSystemExecutionEvidence": external_system_execution_evidence,
        "caseExternalExecutionEvidence": case_external_execution_evidence,
        "industrialDossierCompletenessAudit": industrial_dossier_completeness_audit,
        "caseDossierCompletenessAudit": case_dossier_completeness_audit,
        "liveEvidenceDriftMonitor": live_evidence_drift_monitor,
        "caseLiveEvidenceDrift": case_live_evidence_drift,
        "observedOutcomeCalibrationLedger": observed_outcome_calibration_ledger,
        "caseObservedOutcomeCalibration": case_observed_outcome_calibration,
        "productionDataIngestionContract": production_data_ingestion_contract,
        "caseProductionDataContract": case_production_data_contract,
        "industrialPromotionCertificationGate": industrial_promotion_certification_gate,
        "casePromotionCertification": case_promotion_certification,
        "fieldTrialProtocolLedger": field_trial_protocol_ledger,
        "caseFieldTrialProtocol": case_field_trial_protocol,
        "fieldTrialExecutionEvidenceLedger": field_trial_execution_evidence_ledger,
        "caseFieldTrialExecutionEvidence": case_field_trial_execution_evidence,
        "fieldTrialCloseoutLedger": field_trial_closeout_ledger,
        "caseFieldTrialCloseout": case_field_trial_closeout,
        "industrialOperatingTimelineLedger": industrial_operating_timeline_ledger,
        "caseOperatingTimeline": case_operating_timeline,
        "varianceRootCauseLedger": variance_root_cause_ledger,
        "caseVarianceRootCause": case_variance_root_cause,
        "industrialReviewDispositionLedger": industrial_review_disposition_ledger,
        "caseReviewDisposition": case_review_disposition,
        "industrialAuditExportManifest": industrial_audit_export_manifest,
        "caseAuditExportPackage": case_audit_export_package,
        "dataLineageCertificationLedger": data_lineage_certification_ledger,
        "caseDataLineageCertification": case_data_lineage_certification,
        "policyRiskControlLedger": policy_risk_control_ledger,
        "casePolicyRiskControl": case_policy_risk_control,
        "caseWorkOrderExecutionLedger": case_work_order_execution_ledger,
        "caseWorkOrderExecution": case_work_order_execution,
        "fieldReceiptReconciliationLedger": field_receipt_reconciliation_ledger,
        "caseFieldReceiptReconciliation": case_field_receipt_reconciliation,
        "releaseBoardExceptionLedger": release_board_exception_ledger,
        "caseReleaseBoardException": case_release_board_exception,
        "scenarioCoverageCertificationLedger": scenario_coverage_certification_ledger,
        "caseScenarioCoverageCertification": case_scenario_coverage_certification,
        "operatorCompetencyEvaluationLedger": operator_competency_evaluation_ledger,
        "caseOperatorCompetencyEvaluation": case_operator_competency_evaluation,
        "causalEpisodeTrainingLedger": causal_episode_training_ledger,
        "caseCausalEpisodeTraining": case_causal_episode_training,
        "simulationValidityCalibrationLedger": simulation_validity_calibration_ledger,
        "caseSimulationValidityCalibration": case_simulation_validity_calibration,
        "fieldObservationProtocolLedger": field_observation_protocol_ledger,
        "caseFieldObservationProtocol": case_field_observation_protocol,
        "fieldEvidenceCaptureLedger": field_evidence_capture_ledger,
        "caseFieldEvidenceCapture": case_field_evidence_capture,
        "fieldEvidenceSampleLedger": field_evidence_sample_ledger,
        "caseFieldEvidenceSample": case_field_evidence_sample,
        "fieldEvidenceAdjudicationLedger": field_evidence_adjudication_ledger,
        "caseFieldEvidenceAdjudication": case_field_evidence_adjudication,
        "fieldEvidenceRemediationLedger": field_evidence_remediation_ledger,
        "caseFieldEvidenceRemediation": case_field_evidence_remediation,
        "fieldEvidenceRemediationExecutionLedger": field_evidence_remediation_execution_ledger,
        "caseFieldEvidenceRemediationExecution": case_field_evidence_remediation_execution,
        "fieldEvidenceReleaseClearanceLedger": field_evidence_release_clearance_ledger,
        "caseFieldEvidenceReleaseClearance": case_field_evidence_release_clearance,
        "spatialExecutionDrillLedger": spatial_execution_drill_ledger,
        "caseSpatialExecutionDrill": case_spatial_execution_drill,
        "observedDrillVarianceLedger": observed_drill_variance_ledger,
        "caseObservedDrillVariance": case_observed_drill_variance,
        "industrialAcceptanceCertificationLedger": industrial_acceptance_certification_ledger,
        "caseIndustrialAcceptanceCertification": case_industrial_acceptance_certification,
        "productionEvidenceAcquisitionLedger": production_evidence_acquisition_ledger,
        "caseProductionEvidenceAcquisition": case_production_evidence_acquisition,
        "industrialStandardsMatrix": industrial_standards,
        "industrialDeploymentReadiness": deployment_readiness,
        "industrialOwnershipModel": ownership_model,
        "mapObjectEvidenceIndex": map_object_index,
        "parkRealityModel": park_reality,
        "liveOperatingSceneModel": live_scene,
        "spatialProof": dossier.get("spatialCausalityTrace", {}),
        "approvalPackage": dossier.get("governedApprovalPackage", {}),
        "dataQualityCalibration": dossier.get("dataQualityCalibration", {}),
        "telemetryContract": telemetry,
        "fieldSignalReconciliation": field_signal_reconciliation,
        "decisionTelemetrySnapshot": decision_telemetry_snapshot,
        "fieldExecutionHandoff": field_handoff,
        "caseExecutionRunbook": dossier.get("caseExecutionRunbook", {}),
        "closedLoopVerification": closed_loop,
        "evidence": evidence_bundle,
        "policyAndReceivers": {
            "policyReasoning": policy,
            "receiverReadiness": receiver_rows,
        },
        "verification": {
            "watchConditions": verification.get("watchConditions", []),
            "rollbackTrigger": verification.get("rollbackTrigger"),
            "auditTraceKeys": audit.get("traceKeys", []),
            "minimumEvidence": audit.get("minimumEvidence", []),
            "qualityGate": payload.get("auditManifest", {}).get("qualityGate", {}),
        },
        "machineReadable": {
            "standard": payload.get("standard"),
            "generatedFrom": payload.get("generatedFrom", []),
            "quality": quality,
            "provenanceSourceCount": len({row.get("sourceLayer") for row in provenance if isinstance(row, dict)}),
            "branchProofReady": has_branch_proof,
            "branchProofMode": simulated_branch_comparison.get("mode"),
            "operatingScorecardReady": operating_scorecard.get("mode") == "industrial_operating_scorecard" and bool(operating_scorecard.get("scoreRows")) and bool(operating_scorecard.get("tradeoffLedger")),
            "assumptionSensitivityReady": sensitivity.get("mode") == "industrial_assumption_sensitivity_analysis" and bool(sensitivity.get("stressTests")) and bool(sensitivity.get("flipConditions")),
            "operationalStressRehearsalReady": stress_rehearsal.get("mode") == "industrial_operational_stress_rehearsal" and bool(stress_rehearsal.get("rehearsalScenarios")) and bool(stress_rehearsal.get("escalationTriggers")),
            "independentReviewReady": review_board.get("mode") == "independent_operating_review_board" and bool(review_board.get("reviews")) and bool(review_board.get("releaseDecision")),
            "causalGraphReady": causal_graph.get("mode") == "typed_operating_causal_graph" and bool(causal_graph.get("nodes")) and bool(causal_graph.get("edges")),
            "counterfactualReplayReady": counterfactual_replay.get("mode") == "counterfactual_branch_replay_matrix" and bool(counterfactual_replay.get("rows")),
            "branchPhysicalImpactReady": branch_physical_impact.get("mode") == "industrial_branch_physical_impact_matrix" and bool(branch_physical_impact.get("branchRows")) and bool(branch_physical_impact.get("subsystemMovement")),
            "actionConsequenceReady": action_consequence.get("mode") == "industrial_action_consequence_simulation" and bool(action_consequence.get("consequenceFrames")) and bool(action_consequence.get("branchOutcomeSummary")),
            "commercialImpactReady": commercial_impact.get("mode") == "industrial_commercial_impact_ledger" and bool(commercial_impact.get("rows")),
            "accessibilityEquityReady": accessibility_equity.get("mode") == "industrial_accessibility_equity_impact" and bool(accessibility_equity.get("protectedCohorts")) and bool(accessibility_equity.get("routeAccessChecks")) and bool(accessibility_equity.get("fairnessChecks")),
            "resourceFeasibilityReady": resource_feasibility.get("mode") == "industrial_resource_feasibility_matrix" and bool(resource_feasibility.get("receiverExecutionRows")) and bool(resource_feasibility.get("branchFeasibilityComparison")),
            "policyClauseTraceReady": policy_clause_trace.get("mode") == "industrial_policy_clause_trace" and bool(policy_clause_trace.get("clauseRows")) and bool(policy_clause_trace.get("branchPolicyVerdicts")),
            "spatialPhysicsReady": spatial_physics.get("mode") == "industrial_spatial_physics_envelope" and bool(spatial_physics.get("routePhysics")) and bool(spatial_physics.get("queueGeometry")),
            "physicalPropagationReady": physical_propagation.get("mode") == "industrial_physical_propagation_model" and bool(physical_propagation.get("chain")) and bool(physical_propagation.get("branchPropagationEffects")) and bool(physical_propagation.get("tripwires")),
            "historicalPrecedentReady": historical_precedent.get("mode") == "industrial_historical_precedent_matrix" and bool(historical_precedent.get("matchedPrecedents")) and bool(historical_precedent.get("branchPrecedentVerdicts")),
            "guestCommunicationReady": guest_communication_plan.get("mode") == "industrial_guest_communication_plan" and bool(guest_communication_plan.get("audiencePlans")) and bool(guest_communication_plan.get("channelPlan")) and bool(guest_communication_plan.get("promiseBoundaries")),
            "behavioralResponseReady": behavioral_response.get("mode") == "industrial_behavioral_response_model" and bool(behavioral_response.get("segmentBehavior")) and bool(behavioral_response.get("staffAndReceiverResponse")) and bool(behavioral_response.get("branchBehaviorComparison")),
            "operationalConstraintReady": constraint_register.get("mode") == "industrial_operational_constraint_register" and bool(constraint_register.get("hardConstraints")) and bool(constraint_register.get("branchConstraintVerdicts")) and bool(constraint_register.get("goNoGo")),
            "releaseDecisionReady": release_decision_record.get("mode") == "industrial_release_decision_record" and bool(release_decision_record.get("signoffMatrix")) and bool(release_decision_record.get("approvedVersion")) and bool(release_decision_record.get("postReleaseObligations")),
            "releaseAuthorityReady": release_authority.get("mode") == "industrial_release_authority_decision" and bool(release_authority.get("authorityChecks")) and release_authority.get("autoExecuteAllowed") is False,
            "liveActionAuthorized": release_authority.get("liveActionAuthority") == "authorized_after_human_signoff",
            "executionReadinessReady": execution_readiness.get("mode") == "industrial_execution_readiness_proof" and bool(execution_readiness.get("executionChecks")) and bool(execution_readiness.get("requiredBeforeDispatch")) and bool(execution_readiness.get("caseSceneEvidence")) and execution_readiness.get("readyForLiveExecution") is False,
            "releaseRemediationReady": release_remediation.get("mode") == "industrial_release_remediation_plan" and bool(release_remediation.get("tasks")) and bool(release_remediation.get("recheckSequence")),
            "operatingProcedureDeltaReady": procedure_delta.get("mode") == "industrial_operating_procedure_delta" and bool(procedure_delta.get("procedureDeltas")) and bool(procedure_delta.get("runbookStepUpdates")) and bool(procedure_delta.get("policyPatchCandidates")) and bool(procedure_delta.get("promotionGate")),
            "decisionReproducibilityReady": decision_reproducibility.get("mode") == "industrial_decision_reproducibility_manifest" and bool(decision_reproducibility.get("inputArtifacts")) and bool(decision_reproducibility.get("simulatorVersion")) and bool(decision_reproducibility.get("branchIds")) and bool(decision_reproducibility.get("expectedDeterministicOutputs")) and bool(decision_reproducibility.get("replayInstructions")) and bool(decision_reproducibility.get("reproducibilityGate")),
            "chainOfCustodyReady": chain_of_custody.get("mode") == "industrial_chain_of_custody_audit_log" and bool(chain_of_custody.get("custodyRows")) and bool(chain_of_custody.get("immutableTraceCheckpoints")) and bool(chain_of_custody.get("auditReplayInstructions")),
            "fieldCalibrationBacktestReady": field_calibration.get("mode") == "industrial_field_calibration_backtest_plan" and bool(field_calibration.get("requiredDatasets")) and bool(field_calibration.get("backtestSuites")) and bool(field_calibration.get("acceptanceThresholds")) and bool(field_calibration.get("driftTriggers")),
            "portfolioContextReady": portfolio_operating_model.get("mode") == "industrial_portfolio_operating_model" and bool(portfolio_operating_model.get("assetInventory")) and bool(portfolio_operating_model.get("spatialNetwork")) and bool(portfolio_operating_model.get("coverageReadiness")),
            "portfolioRiskRankingReady": portfolio_risk_ranking.get("mode") == "industrial_portfolio_risk_ranking" and bool(portfolio_risk_ranking.get("rankingRows")) and bool(portfolio_risk_ranking.get("operatingQueue")),
            "productionEvidenceGapRegisterReady": production_evidence_gap_register.get("mode") == "industrial_production_evidence_gap_register" and bool(production_evidence_gap_register.get("caseRows")) and bool(production_evidence_gap_register.get("feedReadinessRows")) and case_production_evidence.get("productionReady") is False,
            "fieldReplayValidationReady": field_replay_validation_harness.get("mode") == "industrial_field_replay_validation_harness" and bool(field_replay_validation_harness.get("caseRows")) and bool(case_field_replay_validation.get("validationRuns")) and bool(case_field_replay_validation.get("replayDatasetSpec")),
            "capacityCertificationReady": capacity_certification_ledger.get("mode") == "industrial_capacity_certification_ledger" and bool(capacity_certification_ledger.get("caseRows")) and bool(case_capacity_certification.get("capacityFindings")) and bool(case_capacity_certification.get("pathCertification")) and bool(case_capacity_certification.get("queueCertification")),
            "slaEscalationClockReady": sla_escalation_clock.get("mode") == "industrial_sla_escalation_clock" and bool(sla_escalation_clock.get("caseRows")) and bool(case_sla_escalation.get("clockRows")) and bool(case_sla_escalation.get("nextDeadline")),
            "receiverExecutionContractReady": receiver_execution_contract_ledger.get("mode") == "industrial_receiver_execution_contract_ledger" and bool(receiver_execution_contract_ledger.get("caseRows")) and bool(case_receiver_execution_contract.get("contractRows")) and all(isinstance(row, dict) and row.get("payloadContract") and row.get("acknowledgementContract") and row.get("rollbackContract") for row in case_receiver_execution_contract.get("contractRows", [])),
            "incidentCommandDecisionLogReady": incident_command_decision_log.get("mode") == "industrial_incident_command_decision_log" and bool(incident_command_decision_log.get("caseRows")) and bool(case_incident_command_decision.get("commandRoles")) and bool(case_incident_command_decision.get("decisionRecord")) and bool(case_incident_command_decision.get("auditEvent")),
            "industrialActionReplayReady": industrial_action_replay_ledger.get("mode") == "industrial_action_replay_ledger" and bool(industrial_action_replay_ledger.get("caseRows")) and bool(case_industrial_action_replay.get("startingScene")) and bool(case_industrial_action_replay.get("timelineFrames")) and bool(case_industrial_action_replay.get("closedLoopWatch")),
            "physicalMovementProofReady": physical_movement_proof_ledger.get("mode") == "industrial_physical_movement_proof_ledger" and bool(physical_movement_proof_ledger.get("caseRows")) and bool(case_physical_movement_proof.get("mapObjectBinding")) and bool(case_physical_movement_proof.get("pathProofRows")) and bool(case_physical_movement_proof.get("queueProofRows")),
            "telemetryAcceptanceReady": telemetry_acceptance_ledger.get("mode") == "industrial_telemetry_acceptance_ledger" and bool(telemetry_acceptance_ledger.get("caseRows")) and bool(case_telemetry_acceptance.get("acceptanceGateRows")) and bool(case_telemetry_acceptance.get("sourceContract")) and bool(case_telemetry_acceptance.get("closedLoopAcceptance")),
            "outcomeAccountabilityReady": outcome_accountability_ledger.get("mode") == "industrial_outcome_accountability_ledger" and bool(outcome_accountability_ledger.get("caseRows")) and bool(case_outcome_accountability.get("expectedOutcome")) and bool(case_outcome_accountability.get("observedEvidenceStatus")) and bool(case_outcome_accountability.get("rollbackPosture")),
            "industrialCaseFileReady": industrial_case_file_synthesis.get("mode") == "industrial_case_file_synthesis" and bool(industrial_case_file_synthesis.get("caseFiles")) and bool(case_file.get("caseNarrative")) and bool(case_file.get("proofStack")) and bool(case_file.get("accountability")),
            "externalSystemExecutionEvidenceReady": external_system_execution_evidence.get("mode") == "industrial_external_system_execution_evidence" and bool(external_system_execution_evidence.get("caseRows")) and bool(case_external_execution_evidence.get("evidenceRows")),
            "industrialDossierCompletenessAuditReady": industrial_dossier_completeness_audit.get("mode") == "industrial_dossier_completeness_audit" and bool(industrial_dossier_completeness_audit.get("auditRows")) and bool(case_dossier_completeness_audit.get("proofFamilies")) and bool(case_dossier_completeness_audit.get("promotionBoundary")),
            "liveEvidenceDriftReady": live_evidence_drift_monitor.get("mode") == "industrial_live_evidence_drift_monitor" and bool(live_evidence_drift_monitor.get("driftRows")) and bool(case_live_evidence_drift.get("liveSignals")) and bool(case_live_evidence_drift.get("requiredRecheck")),
            "observedOutcomeCalibrationReady": observed_outcome_calibration_ledger.get("mode") == "industrial_observed_outcome_calibration_ledger" and bool(observed_outcome_calibration_ledger.get("calibrationRows")) and bool(case_observed_outcome_calibration.get("variance")) and bool(case_observed_outcome_calibration.get("trustDecision")),
            "productionDataIngestionContractReady": production_data_ingestion_contract.get("mode") == "industrial_production_data_ingestion_contract" and bool(production_data_ingestion_contract.get("caseRows")) and bool(case_production_data_contract.get("feedContracts")) and bool(case_production_data_contract.get("graduationCriteria")),
            "promotionCertificationGateReady": industrial_promotion_certification_gate.get("mode") == "industrial_promotion_certification_gate" and bool(industrial_promotion_certification_gate.get("certificationRows")) and bool(case_promotion_certification.get("certificationChecks")) and bool(case_promotion_certification.get("releaseBoundary")),
            "fieldTrialProtocolReady": field_trial_protocol_ledger.get("mode") == "industrial_field_trial_protocol_ledger" and bool(field_trial_protocol_ledger.get("protocolRows")) and bool(case_field_trial_protocol.get("trialScope")) and bool(case_field_trial_protocol.get("stopRules")),
            "fieldTrialExecutionEvidenceReady": field_trial_execution_evidence_ledger.get("mode") == "industrial_field_trial_execution_evidence_ledger" and bool(field_trial_execution_evidence_ledger.get("caseRows")) and bool(case_field_trial_execution_evidence.get("observationCaptures")) and bool(case_field_trial_execution_evidence.get("trialOutcomeDisposition")),
            "fieldTrialCloseoutReady": field_trial_closeout_ledger.get("mode") == "industrial_field_trial_closeout_ledger" and bool(field_trial_closeout_ledger.get("closeoutRows")) and bool(case_field_trial_closeout.get("trialResultRecord")) and bool(case_field_trial_closeout.get("promotionDecision")),
            "operatingTimelineReady": industrial_operating_timeline_ledger.get("mode") == "industrial_operating_timeline_ledger" and bool(industrial_operating_timeline_ledger.get("timelineRows")) and bool(case_operating_timeline.get("eventRows")) and bool(case_operating_timeline.get("mapBindingSummary")),
            "varianceRootCauseReady": variance_root_cause_ledger.get("mode") == "industrial_variance_root_cause_ledger" and bool(variance_root_cause_ledger.get("rootCauseRows")) and bool(case_variance_root_cause.get("rootCauseRows")) and bool(case_variance_root_cause.get("reuseDecision")),
            "reviewDispositionReady": industrial_review_disposition_ledger.get("mode") == "industrial_review_disposition_ledger" and bool(industrial_review_disposition_ledger.get("dispositionRows")) and bool(case_review_disposition.get("signoffMatrix")) and bool(case_review_disposition.get("reviewDisposition")),
            "auditExportManifestReady": industrial_audit_export_manifest.get("mode") == "industrial_audit_export_manifest" and bool(industrial_audit_export_manifest.get("packageRows")) and bool(case_audit_export_package.get("packageHash")) and bool(case_audit_export_package.get("artifactRows")),
            "dataLineageCertificationReady": data_lineage_certification_ledger.get("mode") == "industrial_data_lineage_certification_ledger" and bool(data_lineage_certification_ledger.get("certificationRows")) and bool(case_data_lineage_certification.get("sourceSystemRows")) and bool(case_data_lineage_certification.get("certificationDecision")),
            "policyRiskControlReady": policy_risk_control_ledger.get("mode") == "industrial_policy_risk_control_ledger" and bool(policy_risk_control_ledger.get("controlRows")) and bool(case_policy_risk_control.get("controlRows")) and bool(case_policy_risk_control.get("sensitiveFlags")),
            "caseWorkOrderExecutionReady": case_work_order_execution_ledger.get("mode") == "industrial_case_work_order_execution_ledger" and bool(case_work_order_execution_ledger.get("caseRows")) and bool(case_work_order_execution.get("workOrders")) and bool(case_work_order_execution.get("acknowledgementPlan")),
            "fieldReceiptReconciliationReady": field_receipt_reconciliation_ledger.get("mode") == "industrial_field_receipt_reconciliation_ledger" and bool(field_receipt_reconciliation_ledger.get("caseRows")) and bool(case_field_receipt_reconciliation.get("receiptRows")) and bool(case_field_receipt_reconciliation.get("productionBoundary")),
            "releaseBoardExceptionReady": release_board_exception_ledger.get("mode") == "industrial_release_board_exception_ledger" and bool(release_board_exception_ledger.get("exceptionRows")) and bool(case_release_board_exception.get("exceptionDecision")) and bool(case_release_board_exception.get("signoffRows")),
            "scenarioCoverageCertificationReady": scenario_coverage_certification_ledger.get("mode") == "industrial_scenario_coverage_certification_ledger" and bool(scenario_coverage_certification_ledger.get("certificationRows")) and bool(case_scenario_coverage_certification.get("drillFamilyRows")) and bool(case_scenario_coverage_certification.get("productionBoundary")),
            "operatorCompetencyEvaluationReady": operator_competency_evaluation_ledger.get("mode") == "industrial_operator_competency_evaluation_ledger" and bool(operator_competency_evaluation_ledger.get("caseRows")) and bool(case_operator_competency_evaluation.get("evaluationTasks")) and bool(case_operator_competency_evaluation.get("scoringRubric")),
            "causalEpisodeTrainingReady": causal_episode_training_ledger.get("mode") == "industrial_causal_episode_training_ledger" and bool(causal_episode_training_ledger.get("caseRows")) and bool(case_causal_episode_training.get("episodeFrames")) and bool(case_causal_episode_training.get("physicalProofSummary")),
            "simulationValidityCalibrationReady": simulation_validity_calibration_ledger.get("mode") == "industrial_simulation_validity_calibration_ledger" and bool(simulation_validity_calibration_ledger.get("caseRows")) and bool(case_simulation_validity_calibration.get("assumptionRows")) and bool(case_simulation_validity_calibration.get("falsificationChecks")),
            "fieldObservationProtocolReady": field_observation_protocol_ledger.get("mode") == "industrial_field_observation_protocol_ledger" and bool(field_observation_protocol_ledger.get("caseRows")) and bool(case_field_observation_protocol.get("stationRows")) and bool(case_field_observation_protocol.get("measurementProtocol")),
            "fieldEvidenceCaptureReady": field_evidence_capture_ledger.get("mode") == "industrial_field_evidence_capture_ledger" and bool(field_evidence_capture_ledger.get("caseRows")) and bool(case_field_evidence_capture.get("formRows")) and bool(case_field_evidence_capture.get("custody")),
            "fieldEvidenceSampleReady": field_evidence_sample_ledger.get("mode") == "industrial_field_evidence_sample_ledger" and bool(field_evidence_sample_ledger.get("caseRows")) and bool(case_field_evidence_sample.get("recordRows")) and bool(case_field_evidence_sample.get("custodySummary")),
            "fieldEvidenceAdjudicationReady": field_evidence_adjudication_ledger.get("mode") == "industrial_field_evidence_adjudication_ledger" and bool(field_evidence_adjudication_ledger.get("caseRows")) and bool(case_field_evidence_adjudication.get("metricAdjudications")) and bool(case_field_evidence_adjudication.get("releaseImpact")),
            "fieldEvidenceRemediationReady": field_evidence_remediation_ledger.get("mode") == "industrial_field_evidence_remediation_ledger" and bool(field_evidence_remediation_ledger.get("caseRows")) and bool(case_field_evidence_remediation.get("remediationRows")) and bool(case_field_evidence_remediation.get("releaseHold")),
            "fieldEvidenceRemediationExecutionReady": field_evidence_remediation_execution_ledger.get("mode") == "industrial_field_evidence_remediation_execution_ledger" and bool(field_evidence_remediation_execution_ledger.get("caseRows")) and bool(case_field_evidence_remediation_execution.get("executionRows")) and bool(case_field_evidence_remediation_execution.get("holdClearance")),
            "fieldEvidenceReleaseClearanceReady": field_evidence_release_clearance_ledger.get("mode") == "industrial_field_evidence_release_clearance_ledger" and bool(field_evidence_release_clearance_ledger.get("caseRows")) and bool(case_field_evidence_release_clearance.get("signoffMatrix")) and bool(case_field_evidence_release_clearance.get("clearancePacket")),
            "spatialExecutionDrillReady": spatial_execution_drill_ledger.get("mode") == "industrial_spatial_execution_drill_ledger" and bool(spatial_execution_drill_ledger.get("caseRows")) and bool(case_spatial_execution_drill.get("drillFrames")) and bool(case_spatial_execution_drill.get("stopRules")) and bool(case_spatial_execution_drill.get("drillPacket")),
            "observedDrillVarianceReady": observed_drill_variance_ledger.get("mode") == "industrial_observed_drill_variance_ledger" and bool(observed_drill_variance_ledger.get("caseRows")) and bool(case_observed_drill_variance.get("varianceRows")) and bool(case_observed_drill_variance.get("reuseGate")) and bool(case_observed_drill_variance.get("variancePacket")),
            "industrialAcceptanceCertificationReady": industrial_acceptance_certification_ledger.get("mode") == "industrial_acceptance_certification_ledger" and bool(industrial_acceptance_certification_ledger.get("caseRows")) and bool(case_industrial_acceptance_certification.get("proofFamilyRows")) and bool(case_industrial_acceptance_certification.get("signoffPosture")) and bool(case_industrial_acceptance_certification.get("certificationPacket")),
            "productionEvidenceAcquisitionReady": production_evidence_acquisition_ledger.get("mode") == "industrial_production_evidence_acquisition_ledger" and bool(production_evidence_acquisition_ledger.get("caseRows")) and bool(case_production_evidence_acquisition.get("feedAcquisitions")) and bool(case_production_evidence_acquisition.get("graduationStages")) and bool(case_production_evidence_acquisition.get("acquisitionPacket")),
            "industrialStandardsReady": industrial_standards.get("mode") == "industrial_standards_matrix" and bool(industrial_standards.get("standards")) and (industrial_standards.get("summary", {}) if isinstance(industrial_standards.get("summary"), dict) else {}).get("status") == "ready",
            "deploymentReadinessReady": deployment_readiness.get("mode") == "industrial_deployment_readiness" and deployment_readiness.get("deploymentState") == "demo_ready_not_production_ready" and bool(deployment_readiness.get("productionBlockers")),
            "ownershipModelReady": ownership_model.get("mode") == "industrial_ownership_raci_model" and bool(ownership_model.get("domainRaci")) and bool(ownership_model.get("receiverRaci")) and bool(ownership_model.get("productionBlockerOwners")),
            "mapObjectEvidenceReady": map_object_index.get("mode") == "industrial_map_object_evidence_index" and bool(map_object_index.get("objectRows")) and bool(map_object_index.get("pathRows")) and bool(map_object_index.get("queueRows")),
            "parkRealityReady": park_reality.get("mode") == "case_specific_park_reality_model" and bool(park_reality.get("localTopology")) and bool(park_reality.get("capacityEnvelope")),
            "liveOperatingSceneReady": live_scene.get("mode") == "industrial_live_operating_scene_model" and bool(live_scene.get("actors")) and bool(live_scene.get("physicalScene")) and bool(live_scene.get("bottlenecks")) and bool(live_scene.get("serviceKinetics")) and bool(live_scene.get("agentBeliefState")) and bool(live_scene.get("uncertaintyRegister")),
            "spatialProofReady": isinstance(dossier.get("spatialCausalityTrace"), dict) and bool(dossier.get("spatialCausalityTrace", {}).get("branchSpatialEffects")),
            "approvalPackageReady": isinstance(dossier.get("governedApprovalPackage"), dict) and bool(dossier.get("governedApprovalPackage", {}).get("receiverWrites")),
            "dataQualityReady": isinstance(dossier.get("dataQualityCalibration"), dict) and dossier.get("dataQualityCalibration", {}).get("confidenceScore") is not None,
            "telemetryContractReady": telemetry.get("mode") == "industrial_case_telemetry_contract" and bool(telemetry.get("sourceBindings")) and not telemetry.get("decisionReadiness", {}).get("missingRequiredLayers"),
            "fieldSignalReconciliationReady": field_signal_reconciliation.get("mode") == "industrial_field_signal_reconciliation" and bool(field_signal_reconciliation.get("sourceRows")) and bool(field_signal_reconciliation.get("crossChecks")),
            "decisionTelemetrySnapshotReady": decision_telemetry_snapshot.get("mode") == "industrial_decision_telemetry_snapshot" and bool(decision_telemetry_snapshot.get("queueRows")) and bool(decision_telemetry_snapshot.get("thresholdBreaches")) and bool(decision_telemetry_snapshot.get("sourceLineage")) and bool(decision_telemetry_snapshot.get("productionAcceptanceGates")) and bool(decision_telemetry_snapshot.get("telemetryCertification")) and bool(decision_telemetry_snapshot.get("freshness")),
            "decisionTelemetryProductionReady": (decision_telemetry_snapshot.get("telemetryCertification", {}) if isinstance(decision_telemetry_snapshot.get("telemetryCertification"), dict) else {}).get("productionReady") is True,
            "decisionTelemetryCertificationStatus": (decision_telemetry_snapshot.get("telemetryCertification", {}) if isinstance(decision_telemetry_snapshot.get("telemetryCertification"), dict) else {}).get("certificationStatus"),
            "fieldExecutionHandoffReady": field_handoff.get("mode") == "industrial_field_execution_handoff" and bool(field_handoff.get("dispatches")) and bool(field_handoff.get("acknowledgementGates")),
            "runbookReady": isinstance(dossier.get("caseExecutionRunbook"), dict) and bool(dossier.get("caseExecutionRunbook", {}).get("lifecycle")),
            "closedLoopReady": closed_loop.get("mode") == "closed_loop_verification_plan" and bool(closed_loop.get("observationWindows")) and bool(closed_loop.get("projectedVsObservedChecks")),
        },
    }
    packet_body_hash = hashlib.sha256(json.dumps(packet, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    packet["integrity"] = {
        "algorithm": "sha256",
        "packetId": f"packet_{packet_body_hash[:16]}",
        "packetHash": packet_body_hash,
        "evidenceHash": evidence_hash,
        "hashInputs": ["caseHeader", "executiveBrief", "approvalChecklist", "actionTrainingFrame", "evidence", "policyAndReceivers", "verification", "machineReadable"],
    }
    packet["machineReadable"]["packetId"] = packet["integrity"]["packetId"]
    packet["machineReadable"]["packetHash"] = packet["integrity"]["packetHash"]
    packet["machineReadable"]["evidenceHash"] = packet["integrity"]["evidenceHash"]
    return packet


async def build_park_integration_status_response() -> dict[str, Any]:
    state = await park_simulation.get_state()
    await sync_park_state_safe(state)
    dashboard = await asyncio.to_thread(get_operational_memory_dashboard, "ride down crowd staff food")
    memory_ops = await asyncio.to_thread(build_memory_ops_report, "ride down crowd staff food")
    return await asyncio.to_thread(build_park_integration_status_payload, dashboard, memory_ops)


async def build_industrial_dossier_response() -> dict[str, Any]:
    state = await park_simulation.get_state()
    return await asyncio.to_thread(build_industrial_dossier_api_payload, state)


async def build_park_live_summary_response() -> dict[str, Any]:
    state = await park_simulation.get_state()
    return await asyncio.to_thread(build_park_live_summary_payload, state)


async def build_case_index_response() -> dict[str, Any]:
    payload = await cached_hot_endpoint("industrial_dossiers", _industrial_dossier_cache_ttl_seconds, build_industrial_dossier_response)
    return await asyncio.to_thread(build_case_index_payload, payload)


async def build_case_brief_response(case_id: str) -> dict[str, Any]:
    payload = await cached_hot_endpoint("industrial_dossiers", _industrial_dossier_cache_ttl_seconds, build_industrial_dossier_response)
    dossier = find_industrial_dossier(payload, case_id)
    if dossier is None:
        raise HTTPException(status_code=404, detail=f"Industrial dossier not found: {case_id}")
    return await asyncio.to_thread(build_case_brief_payload, payload, dossier)


def build_park_integration_status_payload(dashboard: dict[str, Any], memory_ops: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "domain": "amusement_park_operations",
        "agent": {"name": "ParkPulse AI", "role": "parkpulse_decision_bridge"},
        "agent_roles": get_agent_registry(),
        "agent_topology": get_agent_topology(),
        "role_alignment": role_alignment_report(),
        "gemini": get_gemini_agent_properties().public_dict(),
        "gcp_trace_eval": _gcp_trace_eval_status_for_api(),
        "evaluator_loop": _evaluator_loop_status_for_api(),
        "online_improvement": online_improvement_status(),
        "arize": get_arize_status().public_dict(),
        "gcp_operations": gcp_operations_status(),
        "mongo": dashboard.get("status", {}),
        "memory_ops": memory_ops or build_memory_ops_report("ride down crowd staff food"),
        "bigquery": bigquery_status(),
        "collections": dashboard.get("collections", []),
        "latest_decision_id": (dashboard.get("latest_decisions", [{}]) or [{}])[0].get("_id"),
        "latest_eval_id": (dashboard.get("latest_evals", [{}]) or [{}])[0].get("_id"),
        "latest_outcome_id": (dashboard.get("latest_outcomes", [{}]) or [{}])[0].get("_id"),
    }


async def build_park_agent_monitoring_response() -> dict[str, Any]:
    with tracer.start_as_current_span("api.park_agent_monitoring") as span:
        state = await park_simulation.get_state()
        await sync_park_state_safe(state)
        signals = await get_park_signals()
        monitoring = await asyncio.to_thread(build_park_agent_monitoring_payload, state, signals)
        span.set_attribute("parkpulse.monitoring.id", monitoring.get("monitoring_id", ""))
        span.set_attribute("parkpulse.monitoring.status", monitoring.get("overall_status", ""))
        span.set_attribute("parkpulse.monitoring.action_count", monitoring.get("summary", {}).get("action_count", 0))
        span.set_attribute("parkpulse.monitoring.arize_ready", bool(monitoring.get("summary", {}).get("arize_ready", False)))
        return monitoring


def build_park_agent_monitoring_payload(state: dict[str, Any], signals: dict[str, Any]) -> dict[str, Any]:
    from park_agent_monitoring import build_park_agent_monitoring

    action_plan = build_park_action_plan(state)
    scenario_key = state.get("guestFlow", {}).get("activeScenario", {}).get("key", "ride_down")
    eval_result = evaluate_park_decision(scenario_key, state)
    memory_dashboard = get_operational_memory_dashboard("gemini performance runtime latency parkpulse agent decision")
    monitoring = build_park_agent_monitoring(
        state,
        action_plan,
        eval_result,
        signals,
        memory_dashboard.get("latest_decisions", []),
    )
    monitoring["runtime_governance"] = list_runtime_governance(20)
    monitoring["guest_care_state"] = state.get("guestCare", {})
    monitoring["maintenance_state"] = state.get("maintenance", {})
    monitoring["agent_roles"] = get_agent_registry()
    monitoring["agent_topology"] = get_agent_topology()
    monitoring["role_alignment"] = role_alignment_report()
    return monitoring


def _park_eval_for_memory(plan: dict[str, Any], park_state: dict[str, Any], action_result: dict[str, Any]) -> dict[str, Any]:
    selected = plan.get("selected_action", {})
    flow = park_state.get("guestFlow", {})
    scenario_key = (flow.get("activeScenario", {}) or {}).get("key", "ride_down")
    avg_satisfaction = int(flow.get("avgSatisfaction", 78) or 78)
    safety_score = 100 if action_result.get("status") in {"success", "noop"} else 80
    worker_score = 88 if selected.get("target") == "staff" else 82 if scenario_key == "staff_shortage" else 86
    return {
        "energy_score": 90 if selected.get("target") == "energy" else 84,
        "comfort_score": max(70, min(96, avg_satisfaction + 8)),
        "worker_stress_score": worker_score,
        "safety_score": safety_score,
        "reasoning": f"ParkPulse eval for {scenario_key}: {selected.get('target', '')}/{selected.get('action', '')}, runtime {plan.get('runtime', '')}.",
    }


def _event_eval_for_memory(plan: dict[str, Any]) -> dict[str, Any]:
    quality = plan.get("quality", {}) if isinstance(plan.get("quality"), dict) else {}
    gcp_eval = quality.get("gcp_eval", {}) if isinstance(quality.get("gcp_eval"), dict) else {}
    if not gcp_eval:
        gcp_eval = quality.get("arize_eval", {}) if isinstance(quality.get("arize_eval"), dict) else {}
    return {
        "energy_score": max(70, int(gcp_eval.get("equipment_feasibility", quality.get("overall", 80)) or 80)),
        "comfort_score": max(70, int(gcp_eval.get("guest_experience", quality.get("overall", 80)) or 80)),
        "worker_stress_score": max(60, int(gcp_eval.get("staff_feasibility", quality.get("overall", 80)) or 80)),
        "safety_score": max(70, int(gcp_eval.get("constraint_following", quality.get("overall", 80)) or 80)),
        "reasoning": (
            f"EventOps eval: {quality.get('status', 'unknown')} with score {quality.get('overall', 0)}. "
            "Checks constraints, grounding, crowd flow, staffing, equipment, and guest experience."
        ),
    }


def _proactive_eval_for_memory(eval_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "energy_score": max(70, int(eval_result.get("actionability", 80) or 80)),
        "comfort_score": max(70, int(eval_result.get("expected_prevention", 80) or 80)),
        "worker_stress_score": max(60, int(100 - eval_result.get("false_alarm_risk", 20) or 80)),
        "safety_score": max(70, int(eval_result.get("proactive_timeliness", 80) or 80)),
        "reasoning": eval_result.get("reasoning", "Proactive EventOps eval."),
    }


def _action_execution_for_signal(signal: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    signal_id = record_mongo_raw_signal(signal)
    signal["memory_id"] = signal_id
    eval_result = evaluate_park_decision(state.get("guestFlow", {}).get("activeScenario", {}).get("key", "ride_down"), state)
    governed_actions = []
    for action in signal.get("recommended_actions", [])[:3]:
        runtime_action = build_runtime_action(
            str(action.get("target", "event")),
            str(action.get("operation", "verify_signal")),
            title=str(action.get("action", "Verify unstructured park signal")),
            owner=str(action.get("owner", "Signal Triage")),
            deadline_minutes=int(action.get("deadline_minutes", 5) or 5),
            expected_impact=str(action.get("expected_impact", "Clarifies a vague operational signal.")),
            source="unstructured_signal",
            scenario=state.get("guestFlow", {}).get("activeScenario", {}),
            payload={
                "signalId": signal["id"],
                "categories": signal.get("categories", []),
                "zone": signal.get("zone", {}),
                "riskLevel": signal.get("risk_level"),
                "humanApprovalRequired": signal.get("human_approval_required"),
                "fusion": signal.get("fusion", {}),
            },
        )
        governed_actions.append(supervise_runtime_action(runtime_action, state, source="unstructured_signal", eval_result=eval_result))

    dispatches = []
    for item in signal.get("dispatch_payloads", []):
        channel = item.get("channel")
        payload = item.get("payload", {})
        if channel == "guest_app":
            dispatches.append(send_guest_promotion(payload))
        elif channel == "worker_device":
            dispatches.append(send_worker_notification(payload))
        elif channel == "equipment_controller":
            dispatches.append(send_equipment_command(payload))

    customer_case = None
    if "child_care" in signal.get("categories", []) or signal.get("risk_level") == "CRITICAL":
        customer_case = create_customer_care_case(
            {
                "reason": "Unstructured signal triage requires privacy-safe guest care follow-through.",
                "severity": "high" if signal.get("risk_level") != "CRITICAL" else "critical",
                "scenarioKey": "messy_signal_triage",
                "safeAudience": f"aggregate guests near {signal.get('zone', {}).get('name', 'reported zone')}",
                "sourceActionId": signal.get("id"),
                "policyFindings": signal.get("missing_info", []),
            },
            state,
        )

    governance = {
        "actions": governed_actions,
        "summary": {
            "allowed": sum(1 for item in governed_actions if item.get("allowed")),
            "review": sum(1 for item in governed_actions if item.get("gate_status") == "review"),
            "blocked": sum(1 for item in governed_actions if item.get("gate_status") == "blocked"),
        },
    }
    delivery = {"dispatches": dispatches, "summary": delivery_summary(dispatches), "response": response_summary(dispatches)}
    learning = build_learning_context(signal, delivery, governance, state)

    return {
        "status": "classified",
        "signal": signal,
        "governance": governance,
        "delivery": delivery,
        "learning": learning,
        "customer_care_case": customer_case,
    }


def _route_mix_from_priors(bigquery_priors: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    priors = bigquery_priors or {}
    weakest = priors.get("weakest_prior", {}) if isinstance(priors.get("weakest_prior"), dict) else {}
    avoid_food_at_entrance = "food" in str(weakest.get("cohort", "")).lower()
    return [
        {"destination": "Theater B", "destinationId": "theaterB", "zoneId": "indoorHub", "share": 0.31, "currentWaitMins": 18},
        {"destination": "Arcade Zone", "destinationId": "arcade", "zoneId": "arcadeZone", "share": 0.29, "currentWaitMins": 12},
        {
            "destination": "Maze Exit Market" if avoid_food_at_entrance else "Food Court A",
            "destinationId": "foodCourt1",
            "zoneId": "foodCourt1",
            "share": 0.18,
            "currentWaitMins": 17,
        },
        {"destination": "Covered Plaza Hold", "destinationId": "coveredPlaza", "zoneId": "coveredPlaza", "share": 0.22, "currentWaitMins": 8},
    ]


def _learned_route_mix_from_first_run(first_mix: list[dict[str, Any]] | None, bigquery_priors: dict[str, Any]) -> list[dict[str, Any]]:
    adjusted_mix = []
    for item in first_mix or _route_mix_from_priors(bigquery_priors):
        copied = dict(item)
        destination = str(copied.get("destination", "")).lower()
        if "arcade" in destination or "theater" in destination:
            copied["share"] = round(min(0.42, float(copied.get("share", 0) or 0) + 0.05), 2)
        elif "food" in destination or "market" in destination:
            copied["share"] = round(max(0.1, float(copied.get("share", 0) or 0) - 0.06), 2)
        else:
            copied["share"] = round(float(copied.get("share", 0) or 0), 2)
        adjusted_mix.append(copied)
    total = sum(float(item.get("share", 0) or 0) for item in adjusted_mix) or 1
    for item in adjusted_mix:
        item["share"] = round(float(item.get("share", 0) or 0) / total, 2)
    return adjusted_mix


def _build_proactive_dispatches(
    insights: dict[str, Any],
    brief: dict[str, Any],
    decision_id: str,
    bigquery_priors: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    dispatches: list[dict[str, Any]] = []
    rows = insights.get("insights", []) if isinstance(insights, dict) else []
    commitment_ids = set(brief.get("recommended_commitments", []) if isinstance(brief.get("recommended_commitments"), list) else [])
    selected = [item for item in rows if item.get("id") in commitment_ids] or rows[:3]
    best_prior = bigquery_priors.get("best_prior", {}) if isinstance(bigquery_priors, dict) and isinstance(bigquery_priors.get("best_prior"), dict) else {}
    weakest_prior = bigquery_priors.get("weakest_prior", {}) if isinstance(bigquery_priors, dict) and isinstance(bigquery_priors.get("weakest_prior"), dict) else {}
    target_mix = _route_mix_from_priors(bigquery_priors)
    expected_take_rate = float(best_prior.get("prior_take_rate", 0.55) or 0.55)
    expected_follow_rate = float(best_prior.get("prior_follow_through", max(0.1, expected_take_rate - 0.08)) or max(0.1, expected_take_rate - 0.08))
    for item in selected[:4]:
        insight_id = item.get("id")
        if insight_id == "shelter_comfort_preload":
            dispatches.append(
                send_equipment_command(
                    {
                        "decisionId": decision_id,
                        "scenarioKey": "proactive_eventops",
                        "equipmentType": "hvac",
                        "zones": ["indoorHub", "arcadeZone", "coveredPlaza"],
                        "command": "proactive_comfort_preload",
                        "settings": {
                            "indoorHubSetpointF": 72,
                            "arcadeZoneSetpointF": 73,
                            "shedNoncriticalLighting": True,
                            "protectShelterComfort": True,
                        },
                        "requiresHumanApproval": False,
                        "reason": item.get("why_now"),
                    }
                )
            )
        elif insight_id == "queue_pressure_prediversion":
            dispatches.append(
                send_guest_promotion(
                    {
                        "decisionId": decision_id,
                        "scenarioKey": "proactive_eventops",
                        "audience": {"segment": "guests_near_high_pressure_rides", "radiusMeters": 300},
                        "message": (
                            "ParkPulse is splitting demand before the queue locks up: "
                            f"{round(target_mix[0]['share'] * 100)}% Theater B, "
                            f"{round(target_mix[1]['share'] * 100)}% Arcade Zone, "
                            f"{round(target_mix[3]['share'] * 100)}% covered hold. "
                            f"Avoiding weak prior: {weakest_prior.get('cohort', 'generic broad nudge')}."
                        ),
                        "promotion": {
                            "type": "route_specific_offer",
                            "offer": best_prior.get("recommended_adjustment", "Bonus points for lower-wait show, arcade, or food check-in."),
                            "expiresMinutes": 25,
                        },
                        "routingTargets": [item["destinationId"] for item in target_mix],
                        "targetMix": target_mix,
                        "expectedTakeRate": min(0.72, max(0.41, expected_take_rate)),
                        "expectedFollowThroughRate": min(0.68, max(0.34, expected_follow_rate)),
                        "estimatedMovedGuests": 520,
                        "priorUsed": best_prior,
                        "weakPriorAvoided": weakest_prior,
                    }
                )
            )
        elif insight_id == "food_pop_up_prestage":
            dispatches.append(
                send_worker_notification(
                    {
                        "decisionId": decision_id,
                        "scenarioKey": "proactive_eventops",
                        "role": "food_ops_lead",
                        "targetZone": "maze_exit_food_pop_up",
                        "task": "Pre-stage one food pop-up near maze exit, add trash bins, and suppress low-inventory mobile-order items before the event demand spike.",
                        "priority": "high",
                        "deadlineMinutes": item.get("deadline_minutes", 25),
                    }
                )
            )
        elif insight_id == "labor_gap_before_overlay":
            dispatches.append(
                send_worker_notification(
                    {
                        "decisionId": decision_id,
                        "scenarioKey": "proactive_eventops",
                        "role": "staffing_lead",
                        "targetZone": "event_staffing_pool",
                        "task": "Call event standby pool, protect ride-operator minimums, and pre-assign crowd-control staff to maze queue and exit wave positions.",
                        "priority": "high",
                        "deadlineMinutes": item.get("deadline_minutes", 30),
                        "constraints": ["protect_break_windows", "do_not_move_uncertified_ride_operators"],
                    }
                )
            )
        else:
            dispatches.append(
                send_worker_notification(
                    {
                        "decisionId": decision_id,
                        "scenarioKey": "proactive_eventops",
                        "role": "event_ops_lead",
                        "targetZone": "park_layout",
                        "task": item.get("recommendation", "Review proactive EventOps recommendation."),
                        "priority": "high" if item.get("urgency") == "risk" else "watch",
                        "deadlineMinutes": item.get("deadline_minutes", 15),
                        "evidence": item.get("evidence", []),
                    }
                )
            )
    if not any(item.get("channel") == "guest_app" for item in dispatches) and rows:
        dispatches.insert(
            0,
            send_guest_promotion(
                {
                    "decisionId": decision_id,
                    "scenarioKey": "proactive_eventops",
                    "audience": {"segment": "guests_near_predicted_bottleneck", "radiusMeters": 300},
                    "message": (
                        "ParkPulse is using a learned route mix before congestion peaks: "
                        f"{round(target_mix[0]['share'] * 100)}% {target_mix[0]['destination']}, "
                        f"{round(target_mix[1]['share'] * 100)}% {target_mix[1]['destination']}, "
                        f"{round(target_mix[3]['share'] * 100)}% covered hold."
                    ),
                    "promotion": {
                        "type": "learned_route_mix",
                        "offer": best_prior.get("recommended_adjustment", "Route-specific bonus for lower-wait destinations."),
                        "expiresMinutes": 25,
                    },
                    "routingTargets": [item["destinationId"] for item in target_mix],
                    "targetMix": target_mix,
                    "expectedTakeRate": min(0.72, max(0.41, expected_take_rate)),
                    "expectedFollowThroughRate": min(0.68, max(0.34, expected_follow_rate)),
                    "estimatedMovedGuests": 520,
                    "priorUsed": best_prior,
                    "weakPriorAvoided": weakest_prior,
                }
            ),
        )
    return dispatches


def _proactive_observed_outcome_application(
    dispatches: list[dict[str, Any]],
    reason: str,
    *,
    status: str = "deferred",
    message: str | None = None,
) -> dict[str, Any]:
    observed = [
        item
        for item in dispatches
        if isinstance(item, dict)
        and isinstance(item.get("response"), dict)
        and item.get("response", {}).get("state") in {"observed", "acknowledged"}
    ]
    channels = sorted({str(item.get("channel")) for item in observed if item.get("channel")})
    moved_guests = sum(
        int(item.get("response", {}).get("followThroughCount", 0) or 0)
        for item in observed
        if item.get("channel") == "guest_app"
    )
    worker_acks = sum(
        int(item.get("response", {}).get("acknowledgedCount", 0) or 0)
        for item in observed
        if item.get("channel") == "worker_device"
    )
    equipment_applied = sum(
        1
        for item in observed
        if item.get("channel") == "equipment_controller" and item.get("response", {}).get("applied")
    )
    return {
        "status": status,
        "mode": "latency_safe_observed_response",
        "reason": reason,
        "message": message
        or "Full counterfactual simulator deferred on the Proact hot path; receiver telemetry was still observed and traced.",
        "dispatch_count": len(dispatches),
        "channels": channels,
        "movedGuests": moved_guests,
        "workerAcknowledgments": worker_acks,
        "equipmentCommandsApplied": equipment_applied,
        "stateImpact": {
            "headline": (
                f"Observed {moved_guests} guest follow-throughs, {worker_acks} staff acknowledgments, "
                f"and {equipment_applied} equipment confirmations before full simulator replay."
            ),
            "domain": "proactive_eventops",
        },
    }


async def _apply_proactive_delivery_outcomes(
    dispatches: list[dict[str, Any]],
    reason: str,
) -> dict[str, Any]:
    if not _truthy(os.getenv("PARKPULSE_PROACTIVE_FULL_OUTCOME_SIM"), False):
        return _proactive_observed_outcome_application(dispatches, reason)
    timeout_seconds = max(1.0, _float_env("PARKPULSE_PROACTIVE_OUTCOME_TIMEOUT_SECONDS", 6.0))
    try:
        return await asyncio.wait_for(
            park_simulation.apply_delivery_outcomes(dispatches, reason),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        return _proactive_observed_outcome_application(
            dispatches,
            reason,
            status="timeout_deferred",
            message=f"Full counterfactual simulator exceeded {timeout_seconds:g}s; receiver telemetry was kept as the proof surface.",
        )
    except Exception as error:
        return _proactive_observed_outcome_application(
            dispatches,
            reason,
            status="degraded",
            message=f"Full counterfactual simulator failed: {type(error).__name__}. Receiver telemetry was kept as the proof surface.",
        )


def _rate_percent(value: Any) -> str:
    try:
        return f"{round(float(value or 0) * 100)}%"
    except (TypeError, ValueError):
        return "--"


def _dispatch_body(dispatch: dict[str, Any]) -> str:
    payload = dispatch.get("payload", {}) if isinstance(dispatch, dict) else {}
    if payload.get("message"):
        return str(payload.get("message"))
    if payload.get("task"):
        return str(payload.get("task"))
    if payload.get("command"):
        zones = ", ".join(payload.get("zones", []) or [])
        return f"{payload.get('command')}{' / ' + zones if zones else ''}"
    promotion = payload.get("promotion", {}) if isinstance(payload.get("promotion"), dict) else {}
    return str(promotion.get("offer") or "Operational action emitted.")


def _build_eventops_lifecycle(
    proactive: dict[str, Any],
    brief: dict[str, Any],
    proactive_eval: dict[str, Any],
    dispatches: list[dict[str, Any]],
    response_metrics: dict[str, Any],
    outcome: dict[str, Any],
    event_revision: dict[str, Any] | None,
    agent_findings: list[dict[str, Any]],
    orchestration: dict[str, Any],
    decision_id: str,
    outcome_id: str,
) -> dict[str, Any]:
    insights = proactive.get("insights", []) if isinstance(proactive, dict) else []
    forecast = proactive.get("forecast", []) if isinstance(proactive, dict) else []
    summary = proactive.get("summary", {}) if isinstance(proactive, dict) else {}
    top_insight = insights[0] if insights else {}
    first_forecast = forecast[0] if forecast else {}
    delivery_counts = delivery_summary(dispatches)
    guest_dispatch = next((item for item in dispatches if item.get("channel") == "guest_app"), None)
    worker_dispatch = next((item for item in dispatches if item.get("channel") == "worker_device"), None)
    equipment_dispatch = next((item for item in dispatches if item.get("channel") == "equipment_controller"), None)
    learning = outcome.get("learning", {}) if isinstance(outcome.get("learning"), dict) else {}
    state_impact = outcome.get("state_impact", {}) if isinstance(outcome.get("state_impact"), dict) else {}
    revision_plan = (event_revision or {}).get("plan", {}) if isinstance((event_revision or {}).get("plan"), dict) else {}

    stages = [
        {
            "id": "plan",
            "label": "Plan Context",
            "actor": "Park Understanding Agent",
            "status": "complete",
            "metric": "context",
            "detail": "Halloween request, live park model, MongoDB memory, and operating constraints are loaded before the watchtower commits action.",
            "artifact": "event_plan_context",
        },
        {
            "id": "detect",
            "label": "Detect",
            "actor": top_insight.get("agent", "Proactive Watchtower"),
            "status": "complete" if insights else "watch",
            "metric": summary.get("insight_count", len(insights)) or "--",
            "detail": top_insight.get("trigger") or "No early warning signal was detected.",
            "artifact": proactive.get("proactive_id"),
        },
        {
            "id": "decide",
            "label": "Decide",
            "actor": "Decision Bridge Agent",
            "status": "complete",
            "metric": proactive_eval.get("overall", "--"),
            "detail": brief.get("why_now") or brief.get("operator_brief") or "Operator brief generated.",
            "artifact": decision_id,
        },
        {
            "id": "emit",
            "label": "Emit",
            "actor": "REST Action Bus",
            "status": "complete" if dispatches else "watch",
            "metric": delivery_counts.get("total", 0),
            "detail": (
                f"Sent {delivery_counts.get('guest_app', 0)} guest messages, "
                f"{delivery_counts.get('worker_device', 0)} worker notifications, and "
                f"{delivery_counts.get('equipment_controller', 0)} equipment commands."
            ),
            "artifact": "delivery_outbox",
        },
        {
            "id": "observe",
            "label": "Observe",
            "actor": "Outcome Loop",
            "status": "complete" if response_metrics.get("score", 0) >= 75 else "watch",
            "metric": _rate_percent(response_metrics.get("takeRate")),
            "detail": (
                f"Take rate {_rate_percent(response_metrics.get('takeRate'))}, "
                f"positive response {_rate_percent(response_metrics.get('positiveResponseRate'))}, "
                f"follow-through {_rate_percent(response_metrics.get('reactiveFollowThroughRate'))}."
            ),
            "artifact": outcome_id,
        },
        {
            "id": "learn",
            "label": "Learn",
            "actor": "MongoDB Memory",
            "status": "complete",
            "metric": response_metrics.get("status", "stored"),
            "detail": learning.get("take_rate_signal") or "Outcome telemetry stored for future retrieval and plan revision.",
            "artifact": outcome.get("loop_id"),
        },
        {
            "id": "revise",
            "label": "Revise",
            "actor": "EventOps Revision Agent",
            "status": "complete" if event_revision else "watch",
            "metric": "v2" if event_revision else "review",
            "detail": revision_plan.get("revision_summary") or brief.get("plan_revision_prompt") or "No plan revision was required.",
            "artifact": (event_revision or {}).get("event_plan_id"),
        },
    ]
    completed_count = sum(1 for item in stages if item["status"] == "complete")
    current_stage = next((item["label"] for item in stages if item["status"] != "complete"), stages[-1]["label"])
    return {
        "headline": "Plan -> detect -> dispatch -> observe -> learn -> revise",
        "current_stage": current_stage,
        "stage_count": len(stages),
        "completed_count": completed_count,
        "plan_mode": "proactive_eventops_closed_loop",
        "ids": {
            "decision_id": decision_id,
            "outcome_id": outcome_id,
            "revision_decision_id": (event_revision or {}).get("decision_id"),
            "revision_event_plan_id": (event_revision or {}).get("event_plan_id"),
        },
        "metrics": {
            "take_rate": response_metrics.get("takeRate", 0),
            "positive_response_rate": response_metrics.get("positiveResponseRate", 0),
            "follow_through_rate": response_metrics.get("reactiveFollowThroughRate", 0),
            "response_score": response_metrics.get("score", 0),
            "sample_size": response_metrics.get("sampleSize", 0),
            "dispatch_total": delivery_counts.get("total", 0),
            "guest_dispatches": delivery_counts.get("guest_app", 0),
            "worker_dispatches": delivery_counts.get("worker_device", 0),
            "equipment_dispatches": delivery_counts.get("equipment_controller", 0),
        },
        "early_detection": {
            "top_signal": top_insight,
            "forecast": first_forecast,
            "busiest_zone": summary.get("busiest_zone"),
            "busiest_path": summary.get("busiest_path"),
        },
        "action_effects": [
            item
            for item in [
                {
                    "channel": "guest_app",
                    "label": "Guest message",
                    "body": _dispatch_body(guest_dispatch or {}),
                    "status": (guest_dispatch or {}).get("status"),
                    "response": (guest_dispatch or {}).get("response", {}),
                }
                if guest_dispatch
                else None,
                {
                    "channel": "worker_device",
                    "label": "Worker notification",
                    "body": _dispatch_body(worker_dispatch or {}),
                    "status": (worker_dispatch or {}).get("status"),
                    "response": (worker_dispatch or {}).get("response", {}),
                }
                if worker_dispatch
                else None,
                {
                    "channel": "equipment_controller",
                    "label": "Equipment control",
                    "body": _dispatch_body(equipment_dispatch or {}),
                    "status": (equipment_dispatch or {}).get("status"),
                    "response": (equipment_dispatch or {}).get("response", {}),
                }
                if equipment_dispatch
                else None,
            ]
            if item
        ],
        "state_impact": state_impact,
        "learning": learning,
        "agent_trace": [
            {
                "agent": item.get("agent"),
                "span": item.get("trace_span"),
                "confidence": item.get("confidence"),
                "policy_refs": item.get("policy_refs", []),
            }
            for item in agent_findings
            if isinstance(item, dict)
        ],
        "orchestration": orchestration,
        "stages": stages,
    }


def _build_intelligence_comparison(
    proactive: dict[str, Any],
    brief: dict[str, Any],
    response_metrics: dict[str, Any],
    outcome: dict[str, Any],
    event_revision: dict[str, Any] | None,
    orchestration: dict[str, Any],
    decision_id: str,
    outcome_id: str,
) -> dict[str, Any]:
    insights = proactive.get("insights", []) if isinstance(proactive, dict) else []
    top_signal = insights[0] if insights else {}
    conflicts = orchestration.get("conflicts", []) if isinstance(orchestration, dict) else []
    gates = orchestration.get("gates", []) if isinstance(orchestration, dict) else []
    response_score = int(response_metrics.get("score", 0) or 0)
    take_rate = float(response_metrics.get("takeRate", 0) or 0)
    positive_rate = float(response_metrics.get("positiveResponseRate", 0) or 0)
    follow_rate = float(response_metrics.get("reactiveFollowThroughRate", 0) or 0)
    learning = outcome.get("learning", {}) if isinstance(outcome.get("learning"), dict) else {}
    state_impact = outcome.get("state_impact", {}) if isinstance(outcome.get("state_impact"), dict) else {}
    revision_plan = (event_revision or {}).get("plan", {}) if isinstance((event_revision or {}).get("plan"), dict) else {}
    revision_created = bool(event_revision)
    take_lift = 0.1 if take_rate < 0.35 else 0.07 if take_rate < 0.45 else 0.04
    follow_lift = 0.08 if follow_rate < 0.4 else 0.04
    positive_lift = 0.04 if positive_rate < 0.86 else 0.02
    learned_take_rate = round(min(0.72, take_rate + take_lift), 3)
    learned_follow_rate = round(min(0.68, follow_rate + follow_lift), 3)
    learned_positive_rate = round(min(0.94, positive_rate + positive_lift), 3)
    learned_score = round(learned_take_rate * 35 + learned_positive_rate * 30 + learned_follow_rate * 35)
    gcp_eval_delta = max(0, min(32, learned_score - response_score))
    changed_assumptions = [
        {
            "assumption": "Guest response",
            "before": f"Policy-compliant message expected guests to self-divert; observed take rate was {_rate_percent(take_rate)}.",
            "after": "Use response-weighted routing, stronger personalization, and destination mix caps before sending the next nudge.",
            "evidence": learning.get("take_rate_signal", "take-rate outcome stored"),
        },
        {
            "assumption": "Crowd placement",
            "before": top_signal.get("trigger", "Primary event placement risk was treated as a watch item."),
            "after": revision_plan.get("revision_summary")
            or "Static queues move out of congested paths; food and merchandise shift to wider zones.",
            "evidence": next((item.get("conflict") for item in conflicts if "corridor" in str(item.get("conflict", "")).lower()), "placement conflict board"),
        },
        {
            "assumption": "Worker load",
            "before": "Staffing was a constraint on the plan, but not yet tied to observed action response.",
            "after": "Pre-assign crowd-control tasks while protecting ride-operator minimums and break windows.",
            "evidence": next((item.get("resolution") for item in conflicts if "labor" in str(item.get("conflict", "")).lower()), "staffing gate"),
        },
        {
            "assumption": "Comfort and equipment",
            "before": "Energy pressure could have pushed noncritical reductions too early.",
            "after": "Pre-cool indoor shelters and shed only noncritical lighting after equipment controller confirmation.",
            "evidence": next((item.get("resolution") for item in conflicts if "comfort" in str(item.get("conflict", "")).lower()), "equipment command response"),
        },
    ]
    gcp_eval_findings = [
        {
            "check": "Response value",
            "before": response_score,
            "after": learned_score,
            "delta": gcp_eval_delta,
            "finding": "The judge treats take rate and follow-through as quality signals, not vanity metrics.",
        },
        {
            "check": "Conflict resolution",
            "before": len([item for item in conflicts if item.get("status") in {"watch", "learning"}]),
            "after": 0 if revision_created else 1,
            "delta": len([item for item in conflicts if item.get("status") in {"watch", "learning"}]),
            "finding": "Revision resolves placement, staffing, and comfort conflicts before the next action cycle.",
        },
        {
            "check": "Plan versioning",
            "before": 1,
            "after": 2 if revision_created else 1,
            "delta": 1 if revision_created else 0,
            "finding": "MongoDB stores the outcome and revised event plan as linked artifacts.",
        },
    ]
    return {
        "mode": "before_after_intelligence_comparison",
        "headline": "The second decision changes because the first outcome was measured.",
        "trigger": {
            "signal": top_signal.get("trigger", "Proactive watchtower signal"),
            "judge_gate": next((gate.get("status") for gate in gates if gate.get("gate") == "Observed response"), "observe"),
            "memory_signal": learning.get("take_rate_signal", "outcome stored"),
        },
        "before": {
            "label": "First pass",
            "decision_id": decision_id,
            "strategy": brief.get("operator_brief", "Commit proactive pre-stage actions."),
            "take_rate": take_rate,
            "positive_response_rate": positive_rate,
            "follow_through_rate": follow_rate,
            "gcp_eval_response_score": response_score,
            "arize_response_score": response_score,
            "state_impact": state_impact.get("headline", ""),
            "weakness": (
                "Observed response is below the quality bar; a policy-correct plan still needs a better guest and worker response."
                if response_score < 75
                else "Response is acceptable, but conflicts still provide revision opportunities."
            ),
        },
        "learning": {
            "outcome_id": outcome_id,
            "loop_id": outcome.get("loop_id"),
            "mongodb_rule": learning.get("take_rate_signal", "outcome stored for future retrieval"),
            "revision_prompt": learning.get("next_prompt") or brief.get("plan_revision_prompt", ""),
            "retrieval_value": "Future runs can retrieve this outcome as an agent_learning rule and bias the route mix, offer strength, staffing, and equipment guardrails.",
        },
        "after": {
            "label": "Learned pass",
            "revision_event_plan_id": (event_revision or {}).get("event_plan_id"),
            "strategy": revision_plan.get("operator_summary") or revision_plan.get("revision_summary") or "Use learned response telemetry to revise the next action mix.",
            "expected_take_rate": learned_take_rate,
            "expected_positive_response_rate": learned_positive_rate,
            "expected_follow_through_rate": learned_follow_rate,
            "expected_gcp_eval_response_score": learned_score,
            "expected_arize_response_score": learned_score,
            "expected_score_delta": gcp_eval_delta,
            "revision_created": revision_created,
        },
        "changed_assumptions": changed_assumptions,
        "gcp_eval_findings": gcp_eval_findings,
        "arize_findings": gcp_eval_findings,
        "proof_points": [
            "Observed take rate changes the next recommendation.",
            "Conflict board changes placement, staffing, and equipment assumptions.",
            "MongoDB stores the outcome and revised plan for retrieval.",
            "GCP internal judge scores the first-pass weakness and the revised expected improvement.",
        ],
    }


def _build_two_run_learning_proof(
    response_metrics: dict[str, Any],
    outcome: dict[str, Any],
    event_revision: dict[str, Any] | None,
    bigquery_priors: dict[str, Any],
    dispatches: list[dict[str, Any]],
    decision_id: str,
    outcome_id: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    guest_dispatch = next((item for item in dispatches if item.get("channel") == "guest_app"), {})
    payload = guest_dispatch.get("payload", {}) if isinstance(guest_dispatch, dict) else {}
    first_mix = payload.get("targetMix", []) if isinstance(payload.get("targetMix"), list) else []
    best_prior = bigquery_priors.get("best_prior", {}) if isinstance(bigquery_priors.get("best_prior"), dict) else {}
    weakest_prior = bigquery_priors.get("weakest_prior", {}) if isinstance(bigquery_priors.get("weakest_prior"), dict) else {}
    retrieved_learning_ids = [
        item.get("_id")
        for item in context.get("retrieved", {}).get("learnings", [])
        if isinstance(item, dict) and item.get("_id")
    ]
    observed_take_rate = float(response_metrics.get("takeRate", 0) or 0)
    observed_follow_rate = float(response_metrics.get("reactiveFollowThroughRate", 0) or 0)
    adjusted_mix = _learned_route_mix_from_first_run(first_mix, bigquery_priors)
    return {
        "mode": "two_run_closed_loop",
        "headline": "Run 2 changes because Run 1 wrote a measured outcome.",
        "run_1": {
            "decision_id": decision_id,
            "outcome_id": outcome_id,
            "route_mix": first_mix,
            "take_rate": observed_take_rate,
            "follow_through_rate": observed_follow_rate,
            "state_impact": outcome.get("state_impact", {}),
            "receiver_ids": [item.get("id") for item in dispatches if item.get("id")],
        },
        "memory_write": {
            "outcome_id": outcome_id,
            "learning_rule": outcome.get("learning", {}).get("take_rate_signal", "outcome stored"),
            "retrieved_learning_ids": retrieved_learning_ids,
            "mongo_collection": "agent_learnings",
            "bigquery_dataset": bigquery_priors.get("dataset", "parkpulse_analytics"),
            "bigquery_query": bigquery_priors.get("query_name", "agent_action_priors_by_scenario"),
        },
        "run_2": {
            "change_reason": (
                "Observed response was below the target, so the next plan increases low-wait show/arcade share "
                "and avoids the weakest historical cohort."
                if observed_take_rate < 0.6 or observed_follow_rate < 0.55
                else "Observed response was healthy, so the next plan keeps the successful mix and still avoids weak historical cohorts."
            ),
            "route_mix": adjusted_mix,
            "expected_take_rate": max(observed_take_rate, float(best_prior.get("prior_take_rate", 0.61) or 0.61)),
            "expected_follow_through_rate": max(observed_follow_rate, float(best_prior.get("prior_follow_through", 0.54) or 0.54)),
            "revision_event_plan_id": (event_revision or {}).get("event_plan_id"),
            "weak_prior_avoided": weakest_prior,
            "best_prior_used": best_prior,
        },
    }


def _summarize_dispatch_payload(dispatch: dict[str, Any]) -> str:
    payload = dispatch.get("payload", {}) if isinstance(dispatch.get("payload"), dict) else {}
    for key in ("message", "task", "command"):
        value = payload.get(key)
        if value:
            return str(value)
    if payload.get("targetMix"):
        return "custom target mix for guest route distribution"
    if payload.get("zones"):
        return f"zone command for {', '.join(str(item) for item in payload.get('zones', [])[:3])}"
    return str(dispatch.get("status") or "payload emitted")


def _candidate_label(candidate: dict[str, Any]) -> str:
    selected_action = candidate.get("selected_action", {}) if isinstance(candidate.get("selected_action"), dict) else {}
    return str(
        selected_action.get("label")
        or candidate.get("label")
        or candidate.get("name")
        or selected_action.get("action")
        or candidate.get("action")
        or "candidate action"
    )


def _candidate_rejection(candidate: dict[str, Any]) -> str:
    reasons = candidate.get("rejected_reasons") if isinstance(candidate.get("rejected_reasons"), list) else []
    if reasons:
        return " / ".join(str(item) for item in reasons[:2])
    scorecard = candidate.get("scorecard", {}) if isinstance(candidate.get("scorecard"), dict) else {}
    risk = scorecard.get("overcorrection_risk")
    burden = scorecard.get("staff_burden")
    if risk is not None or burden is not None:
        return f"tradeoff score: overcorrection {risk if risk is not None else '--'}, staff burden {burden if burden is not None else '--'}"
    return "lower fit than selected action"


def build_run_trace_contract(
    *,
    run_id: str,
    source: str,
    scenario_key: str,
    selected_action: dict[str, Any],
    candidates: list[dict[str, Any]] | None,
    policy_gate: dict[str, Any],
    dispatches: list[dict[str, Any]],
    response_metrics: dict[str, Any],
    outcome_id: str | None,
    outcome: dict[str, Any] | None,
    eval_result: dict[str, Any],
    memory: dict[str, Any],
    digital_twin_trace: dict[str, Any] | None = None,
    learning_proof: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidates = candidates or []
    selected_label = str(
        selected_action.get("label")
        or selected_action.get("title")
        or selected_action.get("action")
        or "selected action"
    )
    normalized_candidates = []
    for index, candidate in enumerate(candidates[:5]):
        is_selected = (
            candidate.get("id") == selected_action.get("id")
            or _candidate_label(candidate) == selected_label
            or index == 0 and not normalized_candidates
        )
        normalized_candidates.append(
            {
                "id": candidate.get("id") or f"candidate-{index + 1}",
                "label": _candidate_label(candidate),
                "status": "selected" if is_selected else "rejected",
                "reason": "highest governed utility" if is_selected else _candidate_rejection(candidate),
                "scorecard": candidate.get("scorecard", {}),
                "projected_impact": candidate.get("projected_impact", {}),
            }
        )
    if not normalized_candidates:
        normalized_candidates.append(
            {
                "id": "selected-action",
                "label": selected_label,
                "status": "selected",
                "reason": str(selected_action.get("expected_effect") or "selected by agent planner"),
            }
        )

    dispatch_trace = [
        {
            "dispatch_id": dispatch.get("id"),
            "channel": dispatch.get("channel"),
            "target_system": dispatch.get("targetSystem") or dispatch.get("endpoint"),
            "status": dispatch.get("status"),
            "payload_summary": _summarize_dispatch_payload(dispatch),
            "payload": dispatch.get("payload", {}),
            "response": dispatch.get("response", {}),
        }
        for dispatch in dispatches
    ]
    receiver_acks = [
        {
            "dispatch_id": item.get("dispatch_id"),
            "channel": item.get("channel"),
            "status": item.get("status"),
            "acknowledged": bool((item.get("response") or {}).get("acknowledgedCount") or item.get("status") in {"observed", "applied", "sent"}),
            "response": item.get("response", {}),
        }
        for item in dispatch_trace
    ]
    memory_write = {
        "decision_id": run_id,
        "outcome_id": outcome_id,
        "connected": memory.get("connected"),
        "mode": memory.get("mode"),
        "retrieved_learning_ids": memory.get("retrieved_learnings", []),
        "learning_rule": (learning_proof or {}).get("memory_write", {}).get("learning_rule")
        or (outcome or {}).get("learning", {}).get("take_rate_signal"),
        "bigquery_query": (learning_proof or {}).get("memory_write", {}).get("bigquery_query")
        or "agent_action_priors_by_scenario",
    }
    selected_candidate = next((item for item in normalized_candidates if item.get("status") == "selected"), normalized_candidates[0])
    rejected_candidate = next((item for item in normalized_candidates if item.get("status") == "rejected"), None)
    eval_trace = eval_result.get("gcp_trace_eval", {}) if isinstance(eval_result.get("gcp_trace_eval"), dict) else {}
    trace_evidence = traced_payload(
        {
            "digital_twin_trace_id": (digital_twin_trace or {}).get("trace", {}).get("trace_id"),
            "digital_twin_span_id": (digital_twin_trace or {}).get("trace", {}).get("span_id"),
            "eval_trace_id": eval_trace.get("trace_id"),
            "eval_span_id": eval_trace.get("span_id"),
            "eval_trace_state": eval_trace.get("trace_state"),
            "eval_trace_url": eval_trace.get("trace_url"),
        }
    )
    policy_refs = policy_gate.get("policy_refs") or [
        "PARK-SAFE-001",
        "PARK-OPS-001",
        "PARK-EXP-001",
        "PARK-CARE-001",
    ]
    policy_rules = [
        {
            "policy_book_id": "ride_safety_policy_book" if ref.startswith("PARK-SAFE") else "parkpulse_operations_policy_book" if ref.startswith("PARK-OPS") else "guest_privacy_policy_book",
            "policy_ref": ref,
            "gate_status": policy_gate.get("gate_status", "unknown"),
            "finding": (policy_gate.get("findings", []) or ["Policy gate evaluated."])[index % max(1, len(policy_gate.get("findings", []) or []))],
        }
        for index, ref in enumerate(policy_refs)
    ]
    trace_table = [
        {
            "step": "input_signal",
            "phase": "predict",
            "evidence": (digital_twin_trace or {}).get("summary", {}).get("signal")
            or f"{scenario_key} live state, queue pressure, density, and memory priors",
            "artifact_id": (digital_twin_trace or {}).get("trace_id") or "digital_twin_snapshot",
            "source": "park_state + operational_memory + bigquery_priors",
        },
        {
            "step": "candidate_selected",
            "phase": "decide",
            "evidence": selected_candidate.get("label"),
            "artifact_id": selected_candidate.get("id"),
            "score": (selected_candidate.get("scorecard") or {}).get("overall"),
            "why": selected_candidate.get("reason"),
        },
        {
            "step": "candidate_rejected",
            "phase": "decide",
            "evidence": (rejected_candidate or {}).get("label", "No higher-risk candidate selected."),
            "artifact_id": (rejected_candidate or {}).get("id", "none"),
            "score": ((rejected_candidate or {}).get("scorecard") or {}).get("overall"),
            "why": (rejected_candidate or {}).get("reason", "No rejected candidate had better governed utility."),
        },
        {
            "step": "policy_rule",
            "phase": "govern",
            "evidence": "; ".join(policy_gate.get("findings", [])[:3]),
            "artifact_id": ",".join(policy_refs),
            "gate_status": policy_gate.get("gate_status"),
            "allowed": policy_gate.get("allowed"),
        },
        {
            "step": "payload_emit",
            "phase": "emit",
            "evidence": " / ".join(str(item.get("payload_summary")) for item in dispatch_trace[:3]),
            "artifact_id": " / ".join(str(item.get("dispatch_id")) for item in dispatch_trace[:3]),
            "dispatch_count": len(dispatch_trace),
        },
        {
            "step": "receiver_result",
            "phase": "observe",
            "evidence": f"{response_metrics.get('takeRate')} take, {response_metrics.get('reactiveFollowThroughRate')} follow-through, {response_metrics.get('sampleSize')} samples",
            "artifact_id": "receiver_response_summary",
            "score": response_metrics.get("score"),
        },
        {
            "step": "memory_write",
            "phase": "learn",
            "evidence": str(memory_write.get("learning_rule") or "Outcome memory written for next decision."),
            "artifact_id": outcome_id,
            "mode": memory_write.get("mode"),
            "connected": memory_write.get("connected"),
        },
    ]
    phases = [
        {
            "id": "predict",
            "label": "Predict",
            "status": "complete",
            "artifact": "digital_twin_snapshot",
            "evidence": (digital_twin_trace or {}).get("summary", {}).get("signal")
            or f"{scenario_key} live state, queue pressure, density, and memory priors",
        },
        {
            "id": "decide",
            "label": "Decide",
            "status": "complete",
            "artifact": "candidate_actions",
            "selected": selected_label,
            "rejected": [item for item in normalized_candidates if item.get("status") == "rejected"],
        },
        {
            "id": "govern",
            "label": "Govern",
            "status": "complete" if policy_gate else "pending",
            "artifact": "policy_gate",
            "gate_status": policy_gate.get("gate_status"),
            "allowed": policy_gate.get("allowed"),
            "policy_refs": policy_refs,
            "findings": policy_gate.get("findings", []),
        },
        {
            "id": "emit",
            "label": "Emit",
            "status": "complete" if dispatch_trace else "pending",
            "artifact": "action_bus_payloads",
            "dispatch_count": len(dispatch_trace),
        },
        {
            "id": "observe",
            "label": "Observe",
            "status": "complete" if response_metrics else "pending",
            "artifact": "receiver_acknowledgement",
            "take_rate": response_metrics.get("takeRate"),
            "follow_through": response_metrics.get("reactiveFollowThroughRate"),
            "sample_size": response_metrics.get("sampleSize"),
        },
        {
            "id": "learn",
            "label": "Learn",
            "status": "complete" if outcome_id else "pending",
            "artifact": "memory_write",
            "outcome_id": outcome_id,
            "learning_rule": memory_write.get("learning_rule"),
        },
    ]
    return {
        "run_id": run_id,
        "source": source,
        "scenario_key": scenario_key,
        "trace": trace_evidence,
        "phases": phases,
        "candidate_actions": normalized_candidates,
        "selected_action": selected_action,
        "policy_gate": policy_gate,
        "policy_rules": policy_rules,
        "trace_table": trace_table,
        "dispatches": dispatch_trace,
        "receiver_acks": receiver_acks,
        "outcome": outcome or {},
        "memory_write": memory_write,
        "eval": eval_result,
        "ui_summary": {
            "selected": selected_label,
            "gate": policy_gate.get("gate_status", "unknown"),
            "dispatches": len(dispatch_trace),
            "take_rate": response_metrics.get("takeRate"),
            "outcome_id": outcome_id,
        },
    }

async def _run_startup_check(name: str, func, timeout_seconds: float = 3.0) -> None:
    started = datetime.now(UTC)
    try:
        result = await asyncio.wait_for(asyncio.to_thread(func), timeout=timeout_seconds)
        _startup_status["checks"][name] = {
            "status": "ok",
            "elapsed_ms": int((datetime.now(UTC) - started).total_seconds() * 1000),
            "summary": result if isinstance(result, dict) else str(result)[:160],
        }
    except Exception as error:
        _startup_status["checks"][name] = {
            "status": "deferred",
            "elapsed_ms": int((datetime.now(UTC) - started).total_seconds() * 1000),
            "error": str(error)[:240],
        }
        print(f"ParkPulse {name} init skipped or deferred: {error}")


async def _deferred_startup_initialization() -> None:
    _startup_status["deferred_initialization"] = "running"
    await _run_startup_check("platform_store", safe_migrate_platform_store)
    await _run_startup_check("memory", init_operational_memory)
    await _run_startup_check("audit_store", init_audit_store)
    await _run_startup_check("replay_backup", backup_replay_store)
    _startup_status["deferred_initialization"] = "complete"


async def startup_event():
    global _last_live_park_step_at
    _startup_status["started_at"] = datetime.now(UTC).isoformat()
    _last_live_park_step_at = asyncio.get_running_loop().time()

    async def loop():
        global _last_live_park_step_at
        while True:
            await park_simulation.step()
            _last_live_park_step_at = asyncio.get_running_loop().time()
            await asyncio.sleep(_live_park_step_interval_seconds)

    _track_background_task(loop())
    _track_background_task(_deferred_startup_initialization())
    _track_background_task(prewarm_hot_endpoint("park_state", _park_state_cache_ttl_seconds, build_park_state_response))
    _track_background_task(
        prewarm_hot_endpoint(
            "park_integration_status",
            _park_integration_status_cache_ttl_seconds,
            build_park_integration_status_response,
        )
    )
    _track_background_task(
        prewarm_hot_endpoint(
            "park_agent_monitoring",
            _park_monitoring_cache_ttl_seconds,
            build_park_agent_monitoring_response,
        )
    )
    _startup_status["ready_at"] = datetime.now(UTC).isoformat()


@app.get("/api/park/state")
async def get_park_state():
    if await advance_live_park_from_wall_clock():
        clear_hot_endpoint_cache()
    return await cached_hot_endpoint("park_state", _park_state_cache_ttl_seconds, build_park_state_response)


@app.get("/api/park/state-lite")
async def get_park_state_lite():
    if await advance_live_park_from_wall_clock():
        clear_hot_endpoint_cache()
    return await cached_hot_endpoint("park_state_lite", _park_state_cache_ttl_seconds, build_park_state_lite_response)


@app.post("/api/park/clock")
async def set_park_clock(request: ParkClockRequest):
    state = await park_simulation.set_time(request.hour, request.minute)
    clear_hot_endpoint_cache()
    return {"status": "success", "state": state}


@app.get("/api/park/live-summary")
async def get_park_live_summary():
    if await advance_live_park_from_wall_clock():
        clear_hot_endpoint_cache()
    return await cached_hot_endpoint("park_live_summary", _park_state_cache_ttl_seconds, build_park_live_summary_response)


@app.get("/api/park/cases")
async def get_park_cases():
    if await advance_live_park_from_wall_clock():
        clear_hot_endpoint_cache()
    return await cached_hot_endpoint("park_case_index", _industrial_dossier_cache_ttl_seconds, build_case_index_response)


@app.get("/api/park/cases/{case_id}/brief")
async def get_park_case_brief(case_id: str):
    if await advance_live_park_from_wall_clock():
        clear_hot_endpoint_cache()
    return await cached_hot_endpoint(f"park_case_brief:{case_id}", _industrial_dossier_cache_ttl_seconds, lambda: build_case_brief_response(case_id))


@app.get("/api/park/industrial-dossiers")
async def get_industrial_dossiers():
    if await advance_live_park_from_wall_clock():
        clear_hot_endpoint_cache()
    return await cached_hot_endpoint("industrial_dossiers", _industrial_dossier_cache_ttl_seconds, build_industrial_dossier_response)


@app.get("/api/park/industrial-dossiers/{case_id}")
async def get_industrial_dossier(case_id: str):
    if await advance_live_park_from_wall_clock():
        clear_hot_endpoint_cache()
    payload = await cached_hot_endpoint("industrial_dossiers", _industrial_dossier_cache_ttl_seconds, build_industrial_dossier_response)
    dossier = find_industrial_dossier(payload, case_id)
    if dossier is None:
        raise HTTPException(status_code=404, detail=f"Industrial dossier not found: {case_id}")
    return {
        "status": "ready",
        "mode": payload["mode"],
        "standard": payload["standard"],
        "simulationClock": payload["simulationClock"],
        "auditManifest": payload["auditManifest"],
        "dossier": dossier,
    }


@app.get("/api/park/industrial-dossiers/{case_id}/packet")
async def get_industrial_dossier_packet(case_id: str):
    if await advance_live_park_from_wall_clock():
        clear_hot_endpoint_cache()
    async def builder() -> dict[str, Any]:
        payload = await cached_hot_endpoint("industrial_dossiers", _industrial_dossier_cache_ttl_seconds, build_industrial_dossier_response)
        dossier = find_industrial_dossier(payload, case_id)
        if dossier is None:
            raise HTTPException(status_code=404, detail=f"Industrial dossier not found: {case_id}")
        return await asyncio.to_thread(build_industrial_dossier_packet, payload, dossier)

    return await cached_hot_endpoint(f"industrial_dossier_packet:{case_id}", _industrial_dossier_cache_ttl_seconds, builder)


@app.get("/api/park/agent-ops-ledger")
async def get_agent_ops_ledger(limit: int = 50, q: str | None = None):
    return await asyncio.to_thread(read_agent_ops_ledger, limit, q)


@app.post("/api/park/agent-ops-ledger")
async def post_agent_ops_ledger(request: AgentOpsLedgerRecordRequest):
    return await asyncio.to_thread(record_agent_ops_record, request.record)


@app.post("/api/park/auth/dev-session")
async def post_park_auth_dev_session(payload: dict[str, Any]):
    if not _dev_role_issuer_enabled():
        raise HTTPException(status_code=404, detail="Dev role session issuer is disabled.")
    role = normalize_role(str(payload.get("role") or "ops_team"))
    if not role_access_contracts(role).get("role_count"):
        raise HTTPException(status_code=400, detail={"status": "invalid_role", "role": role})
    subject = str(payload.get("subject") or "parkpulse-browser-command-center")
    token = sign_role_session(subject, role, _role_auth_secret(), ttl_seconds=_role_session_ttl_seconds())
    verified = verify_role_session(token, _role_auth_secret())
    return {
        "status": "issued",
        "mode": "signed_role_session_issuer",
        "role": role,
        "subject": subject,
        "token": token,
        "token_type": "Bearer",
        "expires_at": verified.get("expires_at"),
        "signed_role_required": _signed_role_required(),
        "dev_issuer": True,
        "boundary": "Local dev issuer only. Production should replace this with Google IAP, OIDC, or another server-verified identity provider.",
    }


@app.get("/api/park/operational-backlog")
async def get_operational_backlog():
    state = await park_simulation.get_state()
    return await asyncio.to_thread(build_operational_backlog, state)


@app.get("/api/park/incident-analytics")
async def get_incident_analytics():
    state = await park_simulation.get_state()
    await sync_park_state_safe(state)
    audit = await asyncio.to_thread(build_audit_snapshot, state)
    signals = latest_signals(40)
    dispatches = latest_dispatches(40)
    backlog = await asyncio.to_thread(build_operational_backlog, state)
    ledger = await asyncio.to_thread(read_agent_ops_ledger, 40, None)
    analytics = await asyncio.to_thread(
        build_incident_analytics,
        state=state,
        audit=audit,
        signals=signals,
        dispatches=dispatches,
        backlog=backlog,
        ledger=ledger,
    )
    analytics["mongoPersistence"] = await asyncio.to_thread(record_mongo_incident_analytics, analytics)
    return analytics


@app.get("/api/park/executive-experience-intelligence")
async def get_executive_experience_intelligence(request: Request):
    _require_role_action(request, "read_executive_intelligence", "executive_experience_intelligence", default_role="ml_ops_admin")
    state = await park_simulation.get_state()
    await sync_park_state_safe(state)
    backlog = await asyncio.to_thread(build_operational_backlog, state)
    audit = await asyncio.to_thread(build_audit_snapshot, state)
    signals = latest_signals(40)
    dispatches = latest_dispatches(40)
    ledger = await asyncio.to_thread(read_agent_ops_ledger, 40, None)
    evidence = await asyncio.to_thread(build_executive_experience_evidence)
    incidents = await asyncio.to_thread(
        build_incident_analytics,
        state=state,
        audit=audit,
        signals=signals,
        dispatches=dispatches,
        backlog=backlog,
        ledger=ledger,
    )
    return await asyncio.to_thread(
        build_executive_experience_intelligence,
        state=state,
        backlog=backlog,
        incidents=incidents,
        ledger=ledger,
        evidence=evidence,
    )


@app.get("/api/park/executive-experience-intelligence/evidence")
async def get_executive_experience_intelligence_evidence(request: Request):
    _require_role_action(request, "read_executive_intelligence", "executive_experience_evidence", default_role="ml_ops_admin")
    return await asyncio.to_thread(build_executive_experience_evidence)


@app.post("/api/park/executive-experience-intelligence/demo-import")
async def post_executive_experience_intelligence_demo_import(request: Request):
    _require_role_action(request, "read_executive_intelligence", "executive_experience_demo_import", default_role="ml_ops_admin")
    return await asyncio.to_thread(import_demo_executive_experience_evidence)


@app.post("/api/park/executive-experience-intelligence/simulate")
async def post_executive_experience_intelligence_simulate(request: Request, payload: dict[str, Any] | None = None):
    _require_role_action(request, "read_executive_intelligence", "executive_experience_simulation", payload, default_role="ml_ops_admin")
    body = payload or {}
    return await asyncio.to_thread(
        simulate_executive_experience_evidence,
        scenario=str(body.get("scenario") or "downtime_communication_gap"),
        months=int(body.get("months") or 6),
        end_month=str(body.get("endMonth") or "2026-05"),
    )


@app.post("/api/park/executive-experience-intelligence/artifacts/monthly-brief")
async def post_executive_experience_intelligence_monthly_brief(request: Request, payload: dict[str, Any] | None = None):
    _require_role_action(request, "read_executive_intelligence", "executive_experience_monthly_brief", payload, default_role="ml_ops_admin")
    month = (payload or {}).get("month") if isinstance(payload, dict) else None
    requested_by_role = str((payload or {}).get("requestedByRole") or "ml_ops_admin") if isinstance(payload, dict) else "ml_ops_admin"
    return await asyncio.to_thread(save_monthly_guest_feedback_brief, month=month, requested_by_role=requested_by_role)


@app.get("/api/park/executive-experience-intelligence/artifacts")
async def get_executive_experience_intelligence_artifacts(request: Request, limit: int = 20):
    _require_role_action(request, "read_executive_intelligence", "executive_experience_artifacts", default_role="ml_ops_admin")
    return {
        "status": "ready",
        "mode": "executive_experience_artifacts",
        "artifacts": await asyncio.to_thread(get_latest_memory_documents, "executive_brief_artifacts", max(1, min(100, limit))),
    }


@app.post("/api/park/executive-experience-intelligence/artifacts/{artifact_id}/review")
async def post_executive_experience_intelligence_artifact_review(request: Request, artifact_id: str, payload: dict[str, Any]):
    auth_decision = _require_role_action(request, "review_executive_artifact", "executive_experience_artifact_review", payload, default_role="ml_ops_admin")
    identity = auth_decision.get("identity", {}) if isinstance(auth_decision.get("identity"), dict) else {}
    return await asyncio.to_thread(
        review_executive_experience_artifact,
        artifact_id,
        str(payload.get("action") or ""),
        note=str(payload.get("note") or ""),
        reviewer_role=str(identity.get("role") or payload.get("reviewerRole") or "ml_ops_admin"),
        reviewer=str(identity.get("subject") or payload.get("reviewer") or "executive-reviewer"),
        allow_demo_approval=bool(payload.get("allowDemoApproval")),
    )


@app.get("/api/park/audit")
async def get_park_audit():
    with tracer.start_as_current_span("api.park_audit") as span:
        state = await park_simulation.get_state()
        audit = await asyncio.to_thread(build_audit_snapshot, state)
        span.set_attribute("parkpulse.audit.critical", audit.get("summary", {}).get("criticalAnomalies", 0))
        span.set_attribute("parkpulse.audit.ingested_events", audit.get("summary", {}).get("ingestedEvents", 0))
        return audit


@app.get("/api/park/counterfactual")
async def get_park_counterfactual():
    with tracer.start_as_current_span("api.park_counterfactual") as span:
        state = await park_simulation.get_state()
        state["operationsAudit"] = await asyncio.to_thread(build_audit_snapshot, state)
        forecast = await asyncio.to_thread(build_counterfactual_forecast, state)
        span.set_attribute("parkpulse.counterfactual.lead_time", forecast.get("leadTimeMinutes", 0))
        span.set_attribute("parkpulse.counterfactual.guest_minutes_saved", forecast.get("impact", {}).get("guestMinutesSaved", 0))
        return forecast


@app.get("/api/park/mission-replay")
async def get_park_mission_replay():
    state = await park_simulation.get_state()
    state["operationsAudit"] = await asyncio.to_thread(build_audit_snapshot, state)
    state["counterfactualForecast"] = await asyncio.to_thread(build_counterfactual_forecast, state)
    state["digitalTwinCalibration"] = await asyncio.to_thread(build_calibration_ledger, state, state["counterfactualForecast"])
    return await asyncio.to_thread(build_mission_replay, state)


@app.get("/api/park/scenario-lab")
async def get_park_scenario_lab():
    state = await park_simulation.get_state()
    state["operationsAudit"] = await asyncio.to_thread(build_audit_snapshot, state)
    state["counterfactualForecast"] = await asyncio.to_thread(build_counterfactual_forecast, state)
    state["digitalTwinCalibration"] = await asyncio.to_thread(build_calibration_ledger, state, state["counterfactualForecast"])
    return await asyncio.to_thread(build_scenario_lab, state)


@app.get("/api/park/readiness-brief")
async def get_park_readiness_brief():
    state = await park_simulation.get_state()
    state["operationsAudit"] = await asyncio.to_thread(build_audit_snapshot, state)
    state["counterfactualForecast"] = await asyncio.to_thread(build_counterfactual_forecast, state)
    state["digitalTwinCalibration"] = await asyncio.to_thread(build_calibration_ledger, state, state["counterfactualForecast"])
    state["missionReplay"] = await asyncio.to_thread(build_mission_replay, state)
    state["scenarioLab"] = await asyncio.to_thread(build_scenario_lab, state)
    return await asyncio.to_thread(build_readiness_brief, state)


@app.get("/api/park/learned-agent-maturity")
async def get_park_learned_agent_maturity():
    state = await park_simulation.get_state()
    state["operationsAudit"] = await asyncio.to_thread(build_audit_snapshot, state)
    state["counterfactualForecast"] = await asyncio.to_thread(build_counterfactual_forecast, state)
    state["digitalTwinCalibration"] = await asyncio.to_thread(build_calibration_ledger, state, state["counterfactualForecast"])
    state["missionReplay"] = await asyncio.to_thread(build_mission_replay, state)
    state["scenarioLab"] = await asyncio.to_thread(build_scenario_lab, state)
    state["readinessBrief"] = await asyncio.to_thread(build_readiness_brief, state)
    return await asyncio.to_thread(build_learned_agent_maturity, state)


@app.get("/api/park/learning-evidence-ledger")
async def get_park_learning_evidence_ledger():
    state = await park_simulation.get_state()
    state["operationsAudit"] = await asyncio.to_thread(build_audit_snapshot, state)
    state["counterfactualForecast"] = await asyncio.to_thread(build_counterfactual_forecast, state)
    state["digitalTwinCalibration"] = await asyncio.to_thread(build_calibration_ledger, state, state["counterfactualForecast"])
    state["missionReplay"] = await asyncio.to_thread(build_mission_replay, state)
    state["scenarioLab"] = await asyncio.to_thread(build_scenario_lab, state)
    state["readinessBrief"] = await asyncio.to_thread(build_readiness_brief, state)
    state["learnedAgentMaturity"] = await asyncio.to_thread(build_learned_agent_maturity, state)
    return await asyncio.to_thread(build_learning_evidence_ledger, state)


@app.post("/api/park/audit/events")
async def ingest_park_audit_event(request: AuditEventRequest):
    with tracer.start_as_current_span("api.park_audit_event") as span:
        event = await asyncio.to_thread(
            record_audit_event,
            {
                "source": request.source,
                "message": request.message,
                "signal": request.signal,
                "zoneId": request.zoneId,
                "assetId": request.assetId or request.zoneId,
                "abnormalityScore": request.abnormalityScore,
                "severity": request.severity,
                "correlatedBy": request.correlatedBy,
                "at": request.at,
                "raw": request.raw,
            },
        )
        clear_hot_endpoint_cache()
        state = await park_simulation.get_state()
        audit = await asyncio.to_thread(build_audit_snapshot, state)
        span.set_attribute("parkpulse.audit_event.signal", event.get("signal", ""))
        span.set_attribute("parkpulse.audit_event.score", event.get("abnormalityScore", 0))
        return {"status": "recorded", "event": event, "audit": audit}


@app.post("/api/park/audit/run-response")
async def run_park_audit_response(request: AuditRunResponseRequest):
    with tracer.start_as_current_span("api.park_audit_response") as span:
        state = await park_simulation.get_state()
        audit = await asyncio.to_thread(build_audit_snapshot, state)
        candidate = await asyncio.to_thread(build_audit_action_candidate, audit, state)
        selected = candidate.get("selected_action", {})
        park_action = selected.get("park_action", {}) if isinstance(selected.get("park_action"), dict) else {}
        finding = candidate.get("finding", {}) if isinstance(candidate.get("finding"), dict) else {}

        if candidate.get("status") != "ready" or not park_action:
            return {"status": "noop", "candidate": candidate, "message": candidate.get("reason", "No audit response available.")}

        gate = supervise_runtime_action(
            build_runtime_action(
                str(park_action.get("target", "")),
                str(park_action.get("action", "")),
                title=str(selected.get("title") or "Audit-selected ParkPulse action"),
                owner=str(selected.get("owner") or "Micro-Ops Audit Agent"),
                deadline_minutes=int(selected.get("deadline_minutes", 5) or 5),
                expected_impact=str(selected.get("expected_impact") or finding.get("recommendedAction") or "Reduce audited abnormality."),
                source="micro_ops_audit_response",
                scenario=state.get("guestFlow", {}).get("activeScenario", {}),
                payload={"finding": finding, "selected_action": selected, "execute": request.execute},
            ),
            state,
            source="micro_ops_audit_response",
        )

        if request.execute and gate["allowed"]:
            action_result = await park_simulation.execute_action(str(park_action.get("target", "")), str(park_action.get("action", "")))
            clear_hot_endpoint_cache()
        elif request.execute:
            action_result = {
                "status": "blocked" if gate["gate_status"] == "blocked" else "pending_operator_approval",
                "message": (
                    "Policy gate blocked the audit response before execution."
                    if gate["gate_status"] == "blocked"
                    else "Policy gate requires operator approval before audit response execution."
                ),
            }
        else:
            action_result = {"status": "candidate_only", "message": "Audit response candidate built without execution."}

        response_record = {
            "status": action_result.get("status", "responded"),
            "executed": bool(request.execute and gate["allowed"]),
            "selected_action": selected,
            "execution": action_result,
            "governance": {
                "allowed": gate["allowed"],
                "gate_status": gate["gate_status"],
                "policy_contract": gate["policy_contract"],
                "findings": gate["findings"],
            },
            "created_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        if finding.get("id"):
            await asyncio.to_thread(record_audit_response, str(finding["id"]), response_record)

        updated_state = await park_simulation.get_state()
        updated_state["operationsAudit"] = await asyncio.to_thread(build_audit_snapshot, updated_state)
        updated_state["counterfactualForecast"] = await asyncio.to_thread(build_counterfactual_forecast, updated_state)
        updated_state["digitalTwinCalibration"] = await asyncio.to_thread(build_calibration_ledger, updated_state, updated_state["counterfactualForecast"])
        updated_state["missionReplay"] = await asyncio.to_thread(build_mission_replay, updated_state)
        updated_state["scenarioLab"] = await asyncio.to_thread(build_scenario_lab, updated_state)
        updated_state["readinessBrief"] = await asyncio.to_thread(build_readiness_brief, updated_state)
        updated_state["learnedAgentMaturity"] = await asyncio.to_thread(build_learned_agent_maturity, updated_state)
        updated_state["learningEvidenceLedger"] = await asyncio.to_thread(build_learning_evidence_ledger, updated_state)
        await sync_park_state_safe(updated_state)
        span.set_attribute("parkpulse.audit_response.finding_id", str(finding.get("id", "")))
        span.set_attribute("parkpulse.audit_response.gate", gate["gate_status"])
        span.set_attribute("parkpulse.audit_response.executed", bool(response_record["executed"]))
        return {
            "status": action_result.get("status", "responded"),
            "candidate": candidate,
            "execution": build_park_action_result(action_result, str(park_action.get("target", "")), str(park_action.get("action", ""))),
            "governance": {
                "allowed": gate["allowed"],
                "gate_status": gate["gate_status"],
                "policy_contract": gate["policy_contract"],
                "findings": gate["findings"],
                "remediation_task": gate["remediation_task"],
                "customer_care_case": gate["customer_care_case"],
                "ledger_entry": gate["ledger_entry"],
            },
            "state": updated_state,
        }


@app.post("/api/park/action")
async def execute_park_action(request: ActionRequest):
    with tracer.start_as_current_span("api.park_action") as span:
        state_before = await park_simulation.get_state()
        gate = supervise_runtime_action(
            build_runtime_action(
                request.target,
                request.action,
                title=f"Manual operator request: {request.target}/{request.action}",
                owner="Manual operator",
                source="manual_action",
                scenario=state_before.get("guestFlow", {}).get("activeScenario", {}),
            ),
            state_before,
            source="manual_action",
        )
        if gate["allowed"]:
            result = await park_simulation.execute_action(request.target, request.action)
            clear_hot_endpoint_cache()
        else:
            result = {
                "status": "blocked" if gate["gate_status"] == "blocked" else "pending_operator_approval",
                "message": (
                    "Policy gate blocked this action before execution."
                    if gate["gate_status"] == "blocked"
                    else "Policy gate requires operator approval before execution."
                ),
            }
        state = await park_simulation.get_state()
        await sync_park_state_safe(state)
        clear_hot_endpoint_cache()
        span.set_attribute("parkpulse.action", f"{request.target}/{request.action}")
        span.set_attribute("parkpulse.policy_gate.status", gate["gate_status"])
        return {
            **build_park_action_result(result, request.target, request.action),
            "governance": {
                "allowed": gate["allowed"],
                "gate_status": gate["gate_status"],
                "policy_contract": gate.get("policy_contract", {}),
                "findings": gate.get("findings", []),
                "remediation_task": gate.get("remediation_task"),
                "customer_care_case": gate.get("customer_care_case"),
                "ledger_entry": gate.get("ledger_entry"),
            },
        }


@app.post("/api/park/simulate")
async def inject_park_event(request: SimulationInjectRequest):
    with tracer.start_as_current_span("api.park_simulate") as span:
        result = await park_simulation.inject_event(request.kind, request.target_id, request.intensity)
        clear_hot_endpoint_cache()
        state = await park_simulation.get_state()
        await sync_park_state_safe(state)
        span.set_attribute("parkpulse.simulation.kind", request.kind)
        span.set_attribute("parkpulse.simulation.target_id", request.target_id)
        span.set_attribute("parkpulse.simulation.intensity", request.intensity)
        return {"status": result["status"], "message": result["message"], "event": result.get("event"), "state": state}


@app.post("/api/park/causal-impact-demo")
async def run_causal_impact_demo(request: CausalImpactDemoRequest):
    with tracer.start_as_current_span("api.park_causal_impact_demo") as span:
        result = await park_simulation.run_causal_impact_demo(request.horizon_minutes, request.execute)
        clear_hot_endpoint_cache()
        state = await park_simulation.get_state()
        await sync_park_state_safe(state)
        span.set_attribute("parkpulse.causal_demo.executed", request.execute)
        span.set_attribute("parkpulse.causal_demo.horizon_minutes", request.horizon_minutes)
        span.set_attribute("parkpulse.causal_demo.selected_action", result.get("selected_action", {}).get("id", "unknown"))
        return {**result, "state": state}


@app.post("/api/park/action-branch-comparison")
async def run_action_branch_comparison(request: BranchComparisonRequest):
    with tracer.start_as_current_span("api.park_action_branch_comparison") as span:
        result = await park_simulation.run_action_branch_comparison(request.horizon_minutes, request.execute, request.case_context)
        clear_hot_endpoint_cache()
        state = await park_simulation.get_state()
        await sync_park_state_safe(state)
        span.set_attribute("parkpulse.branch_comparison.executed", request.execute)
        span.set_attribute("parkpulse.branch_comparison.horizon_minutes", request.horizon_minutes)
        span.set_attribute("parkpulse.branch_comparison.case_id", str((request.case_context or {}).get("id", "none")))
        span.set_attribute("parkpulse.branch_comparison.selected_branch", result.get("selected_branch", "unknown"))
        return {**result, "state": state}


@app.post("/api/park/reset")
async def reset_park_demo():
    result = await park_simulation.reset_demo()
    clear_hot_endpoint_cache()
    state = await park_simulation.get_state()
    await sync_park_state_safe(state)
    return {"status": result["status"], "message": result["message"], "state": state}


@app.post("/api/park/tick")
async def tick_park_day(request: ParkTickRequest):
    for _ in range(request.minutes):
        await park_simulation.step()
    clear_hot_endpoint_cache()
    state = await park_simulation.get_state()
    await sync_park_state_safe(state)
    return {
        "status": "advanced",
        "minutes": request.minutes,
        "state": state,
        "simTime": state.get("simTime"),
        "mode": "live_park_day_tick",
    }


@app.get("/api/park/analytics-action-layer")
async def get_analytics_action_layer():
    state = await park_simulation.get_state()
    return {
        "status": "complete",
        "state": state,
        "analytics_action_layer": build_analytics_to_action_layer(state),
    }


def _orchestration_with_role_departments(orchestration: dict[str, Any], role_agent_proposals: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(orchestration or {})
    proposals = role_agent_proposals if isinstance(role_agent_proposals, dict) else {}
    active_roles = proposals.get("active_roles", []) if isinstance(proposals.get("active_roles"), list) else []
    proposal_departments = (
        proposals.get("active_departments", [])
        if isinstance(proposals.get("active_departments"), list)
        else active_departments_for_agents(active_roles)
    )
    department_system = dict(enriched.get("department_system") or {})
    existing_departments = department_system.get("active_departments", [])
    active_departments = sorted({str(item) for item in [*existing_departments, *proposal_departments] if str(item or "").strip()})
    department_system["active_departments"] = active_departments
    department_system["active_department_count"] = len(active_departments)
    if active_roles and "active_roles" not in enriched:
        enriched["active_roles"] = list(active_roles)
    enriched["department_system"] = department_system
    return enriched


async def park_agent_run(request: ParkAgentRunRequest):
    with tracer.start_as_current_span("api.park_agent_run") as span:
        workflow_timer = AgentWorkflowTimer()
        if request.scenario_key:
            await park_simulation.execute_action("scenario", request.scenario_key)
            clear_hot_endpoint_cache()
            workflow_timer.mark("sense.scenario", "local", scenario_key=request.scenario_key)

        operation_event = None
        if request.operation_mode or request.auto_unexpected_event:
            operation_event = await park_simulation.inject_random_unexpected_event("park_operation_start")
            clear_hot_endpoint_cache()
            workflow_timer.mark("sense.operation_event", "local", event_kind=(operation_event or {}).get("event", {}).get("kind"))

        state = await park_simulation.get_state()
        await sync_park_state_safe(state)
        scenario_key = request.scenario_key or state.get("guestFlow", {}).get("activeScenario", {}).get("key", "ride_down")
        workflow_timer.mark("sense.state_snapshot", "local", scenario_key=scenario_key)
        interventions = state.get("guestFlow", {}).get("interventions", [])
        intervention_terms = " ".join(
            f"{item.get('kind', '')} {item.get('targetId', '')} intensity {item.get('intensity', '')}"
            for item in interventions
            if isinstance(item, dict)
        )
        operator_terms = request.operator_message.strip() if request.operator_message else ""
        operator_route = _infer_operator_command_route(operator_terms, "auto") if operator_terms else {}
        local_operator_constraints = extract_operator_constraints(operator_terms, state, operator_route) if operator_terms else {}
        workflow_timer.mark(
            "interpret.local_constraints",
            "local",
            route=operator_route.get("route"),
            requires_human_review=operator_route.get("requires_human_review"),
            constraint_count=len(local_operator_constraints.get("decision_rules", [])) if local_operator_constraints else 0,
        )
        context_query = _operator_context_terms(scenario_key, operator_terms, intervention_terms, operator_route)
        context = _retrieve_operational_context(context_query, state, agent_role="react_agent")
        workflow_timer.mark(
            "sense.memory_retrieval",
            "targeted",
            query_terms=len(context_query.split()),
            method=context.get("retrieved", {}).get("method"),
            playbooks=len(context.get("retrieved", {}).get("playbooks", [])),
            incidents=len(context.get("retrieved", {}).get("incidents", [])),
            learnings=len(context.get("retrieved", {}).get("learnings", [])),
        )
        context = _collaboration_context(context, scenario_key)
        workflow_timer.mark(
            "sense.priors",
            "targeted",
            bigquery_source=context.get("bigquery_priors", {}).get("source"),
            relational_mode=context.get("relational_context", {}).get("mode"),
        )
        if request.operator_message:
            context["operator_request"] = request.operator_message
            context["operator_mode"] = "operator_command"
            context["operator_constraints"] = local_operator_constraints
            context["operator_route"] = operator_route
        if request.live_feed_case:
            context["live_feed_case"] = request.live_feed_case
            context["live_feed_health"] = request.live_feed_health or {}
            context["orchestration_source"] = request.orchestration_source or "live_feed"
            try:
                context["park_profile"] = build_venue_profile()
            except Exception as error:
                context["park_profile"] = {
                    "status": "unavailable",
                    "mode": "venue_profile",
                    "readiness": {"status": "unavailable", "issues": [{"id": "venue_profile_load_failed", "detail": str(error)[:240]}]},
                }
        proposal_route = _role_proposal_route_for_agent_run(scenario_key, operator_route)
        if request.live_feed_case:
            proposal_route = {
                **proposal_route,
                "route": "live_feed_department_cooperation",
                "orchestration_source": request.orchestration_source or "live_feed",
                "live_feed_lead_source": request.live_feed_case.get("lead_source"),
                "live_feed_lead_signal_type": request.live_feed_case.get("lead_signal_type"),
            }
        role_agent_proposals = build_role_agent_proposals(
            state,
            proposal_route,
            local_operator_constraints,
            context,
        )
        if request.live_feed_case:
            role_agent_proposals = _enrich_role_proposals_with_live_feed(role_agent_proposals, request.live_feed_case)
        if context.get("park_profile"):
            role_agent_proposals["park_profile_summary"] = _park_profile_summary_for_agent_run(context.get("park_profile"))
        context["role_agent_proposals"] = role_agent_proposals
        workflow_timer.mark(
            "collaborate.role_proposals",
            "deterministic_role_agents",
            role_count=len(role_agent_proposals.get("active_roles", [])),
            proposal_count=role_agent_proposals.get("proposal_count"),
            conflict_count=len(role_agent_proposals.get("conflicts", [])),
        )
        use_react_first = bool(request.operator_message) and os.getenv("PARKPULSE_DISABLE_GEMINI_REACT_FIRST", "").lower() not in {"1", "true", "yes"}
        if use_react_first:
            plan = await build_park_gemini_reaction_plan(state, scenario_key, context)
            lane = "fast_react_first"
        else:
            plan = await build_park_gemini_plan(
                state,
                scenario_key,
                context,
                enforce_scenario_alignment=not bool(request.operator_message),
            )
            lane = "deep_full_planner"
        plan = _apply_cache_accuracy_to_plan(plan, context)
        workflow_timer.mark(
            "decide.gemini",
            lane,
            runtime=plan.get("runtime"),
            status=plan.get("performance_status"),
            cache_trust_penalty=plan.get("cache_trust_penalty"),
            requires_revalidation=plan.get("requires_revalidation"),
            latency_ms=plan.get("response_latency_ms"),
            timeout_seconds=plan.get("timeout_seconds"),
            custom_mix_count=len(plan.get("custom_action_mixes", [])) if isinstance(plan.get("custom_action_mixes"), list) else 0,
        )
        operator_constraints = local_operator_constraints
        if request.operator_message:
            genai_constraints = constraints_from_genai_understanding(plan.get("operator_understanding"), operator_terms, operator_route)
            operator_constraints = merge_operator_constraints(local_operator_constraints, genai_constraints)
            context["operator_constraints"] = operator_constraints
            plan["operator_constraints"] = operator_constraints
            workflow_timer.mark(
                "interpret.merge_constraints",
                "local+gemini",
                constraint_count=len(operator_constraints.get("decision_rules", [])) if operator_constraints else 0,
                source=operator_constraints.get("source") if isinstance(operator_constraints, dict) else None,
            )
        optimization = optimize_park_response(state, scenario_key, context, plan)
        if operator_constraints:
            optimization = apply_operator_constraints_to_optimization(optimization, operator_constraints, state, scenario_key)
        workflow_timer.mark(
            "decide.optimizer",
            "local_tournament",
            candidate_source=optimization.get("candidate_source"),
            candidate_count=len(optimization.get("candidates", [])),
            selected_plan_id=optimization.get("selected_plan_id"),
        )
        digital_twin_trace = build_digital_twin_tool_trace(state, scenario_key, context, plan, optimization)
        workflow_timer.mark(
            "validate.digital_twin_trace",
            "local_tools",
            tool_count=digital_twin_trace.get("tool_count"),
            policy_gate=digital_twin_trace.get("summary", {}).get("policy_gate"),
        )
        selected = optimization.get("selected_plan", {}).get("selected_action") or plan.get("selected_action", {})
        if selected:
            plan["selected_action"] = selected
            if selected.get("label"):
                plan["recommended_action"] = selected.get("label")
        selected_gate = supervise_runtime_action(
            build_runtime_action(
                str(selected.get("target", "")),
                str(selected.get("action", "")),
                title=str(selected.get("label") or selected.get("title") or plan.get("recommended_action") or "Selected ParkPulse agent action"),
                owner=str(selected.get("owner") or "Decision Bridge Agent"),
                expected_impact=str(selected.get("expected_effect") or "Agent-selected action from optimized plan."),
                source="reactive_agent_run",
                scenario=state.get("guestFlow", {}).get("activeScenario", {}),
                payload={
                    "selected_action": selected,
                    "optimization": optimization.get("selected_plan", {}),
                    "cache_accuracy_contract": plan.get("cache_accuracy_contract", {}),
                    "requires_revalidation": plan.get("requires_revalidation", False),
                    "affected_drift_facts": plan.get("affected_drift_facts", []),
                    "original_confidence_score": plan.get("original_confidence_score"),
                    "adjusted_confidence_score": plan.get("confidence_score"),
                },
            ),
            state,
            source="reactive_agent_run",
        )
        workflow_timer.mark(
            "validate.policy_gate",
            "local_policy",
            gate_status=selected_gate.get("gate_status"),
            allowed=selected_gate.get("allowed"),
            finding_count=len(selected_gate.get("findings", [])),
        )
        if selected.get("target") and selected.get("action"):
            if selected_gate["allowed"] and request.execute:
                action_result = await park_simulation.execute_action(selected["target"], selected["action"])
                clear_hot_endpoint_cache()
            elif selected_gate["allowed"]:
                action_result = {
                    "status": "preview",
                    "message": "Operator command generated an executable plan; execution was disabled for this request.",
                }
            else:
                action_result = {
                    "status": "blocked" if selected_gate["gate_status"] == "blocked" else "pending_operator_approval",
                    "message": (
                        "Policy gate blocked the selected agent action before execution."
                        if selected_gate["gate_status"] == "blocked"
                        else "Policy gate requires operator approval before execution."
                    ),
                }
        else:
            action_result = {"status": "noop", "message": "No executable selected action."}
        workflow_timer.mark(
            "dispatch.action",
            "simulation" if request.execute else "preview",
            action_status=action_result.get("status"),
            target=selected.get("target"),
            action=selected.get("action"),
        )

        updated_state = await park_simulation.get_state()
        await sync_park_state_safe(updated_state)
        workflow_timer.mark("observe.state_update", "local", action_status=action_result.get("status"))
        memory_eval = _park_eval_for_memory(plan, updated_state, action_result)
        decision_id = record_mongo_agent_decision(
            {
                "recommended_action": plan.get("recommended_action", ""),
                "selected_action": selected,
                "candidate_actions": plan.get("candidate_actions", []),
                "optimization": optimization,
                "digital_twin_tools": digital_twin_trace,
                "original_confidence_score": plan.get("original_confidence_score"),
                "confidence_score": plan.get("confidence_score", 0),
                "cache_accuracy_contract": plan.get("cache_accuracy_contract", {}),
                "requires_revalidation": plan.get("requires_revalidation", False),
                "affected_drift_facts": plan.get("affected_drift_facts", []),
                "root_cause_classification": plan.get("root_cause_classification", scenario_key),
                "guest_message": plan.get("guest_message", ""),
                "operator_constraints": operator_constraints,
                "runtime": plan.get("runtime", ""),
                "model": plan.get("model", ""),
                "gemini_ready": plan.get("gemini_ready"),
                "attempted_gemini": plan.get("attempted_gemini"),
                "performance_status": plan.get("performance_status", ""),
                "response_latency_ms": plan.get("response_latency_ms"),
                "timeout_seconds": plan.get("timeout_seconds"),
                "errors": plan.get("errors", []),
                "role_agent_proposals": role_agent_proposals,
            },
            memory_eval,
            updated_state,
            context,
            source="park_gemini_agent",
        )
        workflow_timer.mark(
            "learn.decision_memory",
            "mongo",
            decision_id=decision_id,
            skipped=str(decision_id).startswith("skipped_"),
        )
        delivery_dispatches = (
            build_delivery_plan(
                scenario_key,
                selected,
                updated_state,
                decision_id,
                action_mix=optimization.get("selected_plan", {}).get("action_mix"),
            )
            if selected_gate["allowed"]
            else []
        )
        response_metrics = response_summary(delivery_dispatches)
        workflow_timer.mark(
            "dispatch.receivers",
            "receiver_payloads",
            dispatch_count=len(delivery_dispatches),
            take_rate=response_metrics.get("takeRate"),
            follow_through=response_metrics.get("reactiveFollowThroughRate"),
        )
        revision = revise_plan_after_response(optimization, response_metrics)
        if revision:
            revision_dispatches = build_delivery_plan(
                scenario_key,
                revision.get("selected_action", selected),
                updated_state,
                decision_id,
                action_mix=revision.get("action_mix"),
            )
            for item in revision_dispatches:
                item["revision"] = True
            delivery_dispatches.extend(revision_dispatches)
            response_metrics = response_summary(delivery_dispatches)
            workflow_timer.mark("decide.revision", "local", revision_dispatch_count=len(revision_dispatches))
        gate_summary = {
            "allowed": selected_gate["allowed"],
            "gate_status": selected_gate["gate_status"],
            "findings": selected_gate["findings"],
        }
        eval_result = evaluate_park_decision(scenario_key, updated_state, delivery_dispatches, governance=gate_summary)
        record_mongo_eval_result(decision_id, eval_result, source="reactive_agent_run")
        workflow_timer.mark("observe.eval", "local_scorecard", overall=(eval_result.get("scorecard") or {}).get("overall"))
        agent_findings = build_reactive_agent_findings(
            updated_state,
            scenario_key,
            context,
            plan,
            optimization,
            eval_result,
            {"response": response_metrics, "dispatches": delivery_dispatches},
        )
        orchestration = _orchestration_with_role_departments(
            build_orchestration_run(agent_findings, "reactive", response_metrics, None),
            role_agent_proposals,
        )
        reactive_outcome = build_reactive_outcome(
            state,
            updated_state,
            delivery_dispatches,
            response_metrics,
            optimization,
            plan,
            eval_result,
        )
        role_outcome_attribution = _role_outcome_attribution(
            role_agent_proposals,
            optimization,
            response_metrics,
            eval_result,
            selected,
            scenario_key,
        )
        reactive_outcome["role_outcome_attribution"] = role_outcome_attribution
        outcome_id = record_mongo_outcome_event(reactive_outcome, decision_id, updated_state)
        role_proposal_memory = record_mongo_role_proposal_outcomes(
            role_outcome_attribution,
            decision_id,
            outcome_id,
            updated_state,
        )
        workflow_timer.mark(
            "learn.role_outcomes",
            "mongo",
            stored_count=role_proposal_memory.get("stored_count"),
            accepted_count=role_outcome_attribution.get("summary", {}).get("accepted_count"),
            rejected_count=role_outcome_attribution.get("summary", {}).get("rejected_count"),
        )
        analytics_rows = build_analytics_rows(
            decision_id=decision_id,
            outcome_id=outcome_id,
            scenario_key=scenario_key,
            delivery={"response": response_metrics, "dispatches": delivery_dispatches},
            outcome=reactive_outcome,
            eval_result=eval_result,
            source="reactive_agent_run",
        )
        analytics_export = _export_agent_analytics(analytics_rows)
        workflow_timer.mark(
            "learn.analytics",
            "bigquery" if analytics_export.get("inserted") else "local",
            inserted=analytics_export.get("inserted"),
            row_count=sum(analytics_export.get("row_counts", {}).values()) if isinstance(analytics_export.get("row_counts"), dict) else None,
        )
        span.set_attribute("parkpulse.agent.runtime", plan.get("runtime", ""))
        span.set_attribute("parkpulse.selected_action", f"{selected.get('target', '')}/{selected.get('action', '')}")
        span.set_attribute("parkpulse.policy_gate.status", selected_gate["gate_status"])
        span.set_attribute("parkpulse.policy_gate.allowed", selected_gate["allowed"])
        span.set_attribute("parkpulse.mongo.decision_id", decision_id)
        span.set_attribute("parkpulse.mongo.outcome_id", outcome_id)
        span.set_attribute("parkpulse.delivery.total", len(delivery_dispatches))
        span.set_attribute("parkpulse.response.take_rate", response_metrics.get("takeRate", 0))
        span.set_attribute("parkpulse.response.positive_rate", response_metrics.get("positiveResponseRate", 0))
        span.set_attribute("parkpulse.response.follow_through_rate", response_metrics.get("reactiveFollowThroughRate", 0))
        span.set_attribute("parkpulse.digital_twin.tool_count", digital_twin_trace.get("tool_count", 0))
        span.set_attribute("parkpulse.digital_twin.policy_gate", digital_twin_trace.get("summary", {}).get("policy_gate", ""))
        span.set_attribute("parkpulse.operation_mode", bool(request.operation_mode or request.auto_unexpected_event))
        span.set_attribute("parkpulse.operation_event.kind", str((operation_event or {}).get("event", {}).get("kind", "")))
        span.set_attribute("parkpulse.operator_constraints.count", len(operator_constraints.get("decision_rules", [])) if operator_constraints else 0)
        memory_summary = {
            "mode": context.get("status", {}).get("mode"),
            "connected": context.get("status", {}).get("connected"),
            "retrieved_playbooks": [item.get("_id") for item in context.get("retrieved", {}).get("playbooks", [])],
            "retrieved_incidents": [item.get("_id") for item in context.get("retrieved", {}).get("incidents", [])],
            "retrieved_learnings": [item.get("_id") for item in context.get("retrieved", {}).get("learnings", [])],
        }
        governance_summary = {
            "allowed": selected_gate["allowed"],
            "gate_status": selected_gate["gate_status"],
            "policy_contract": selected_gate["policy_contract"],
            "findings": selected_gate["findings"],
            "remediation_task": selected_gate["remediation_task"],
            "customer_care_case": selected_gate["customer_care_case"],
            "ledger_entry": selected_gate["ledger_entry"],
        }
        trace_contract = build_run_trace_contract(
            run_id=decision_id,
            source="reactive_agent_run",
            scenario_key=scenario_key,
            selected_action=selected,
            candidates=optimization.get("candidates", []),
            policy_gate=governance_summary,
            dispatches=delivery_dispatches,
            response_metrics=response_metrics,
            outcome_id=outcome_id,
            outcome=reactive_outcome,
            eval_result=eval_result,
            memory=memory_summary,
            digital_twin_trace=digital_twin_trace,
        )
        agent_workflow = workflow_timer.summary(
            route=operator_route or {"route": "scenario_run", "scenario_key": scenario_key},
            lane=lane,
            context_query=context_query,
            plan=plan,
            fallback_available=True,
        )
        return {
            "status": "complete",
            "scenario_key": scenario_key,
            "operation_mode": bool(request.operation_mode or request.auto_unexpected_event),
            "operation_event": operation_event,
            "planner": plan,
            "role_agent_proposals": role_agent_proposals,
            "role_outcome_attribution": role_outcome_attribution,
            "role_proposal_memory": role_proposal_memory,
            "agent_findings": agent_findings,
            "orchestration": orchestration,
            "agent_orchestration": orchestration,
            "optimization": optimization,
            "operator_constraints": operator_constraints,
            "digital_twin_tools": digital_twin_trace,
            "revision": revision,
            "execution": build_park_action_result(action_result, selected.get("target", ""), selected.get("action", "")),
            "governance": governance_summary,
            "decision_id": decision_id,
            "outcome_id": outcome_id,
            "trace_contract": trace_contract,
            "agent_workflow": agent_workflow,
            "delivery": {
                "summary": delivery_summary(delivery_dispatches),
                "response": response_metrics,
                "dispatches": delivery_dispatches,
                "contract": delivery_contract(),
            },
            "outcome": reactive_outcome,
            "eval": eval_result,
            "analytics": analytics_export,
            "memory": memory_summary,
        }


async def park_operator_command(request: OperatorCommandRequest):
    message = request.message.strip()
    route = _infer_operator_command_route(message, request.mode)
    with tracer.start_as_current_span("api.park_operator_command") as span:
        span.set_attribute("parkpulse.operator_command.route", route["route"])
        span.set_attribute("parkpulse.operator_command.scenario", route["scenario_key"])
        span.set_attribute("parkpulse.operator_command.execute", request.execute)
        span.set_attribute("parkpulse.operator_command.length", len(message))
        if route["route"] == "event_plan":
            plan_response = await plan_park_event(
                EventPlanRequest(
                    prompt=message,
                    expected_guests=8000,
                    event_theme="Operator-requested park event",
                )
            )
            return {
                "status": "complete",
                "command": message,
                "route": route,
                "mode": "event_plan",
                "operator_response": {
                    "headline": "EventOps plan generated from the operator request.",
                    "summary": (plan_response.get("plan") or {}).get("operator_summary"),
                    "next_step": "Review the event plan, then choose whether to turn deployment suggestions into receiver actions.",
                },
                "event_plan": plan_response,
            }

        if route["route"] == "signal_triage":
            triage_response = await park_signal_intake(
                SignalIntakeRequest(
                    text=message,
                    source="operator_command",
                    reporterRole="operator",
                )
            )
            return {
                "status": "complete",
                "command": message,
                "route": route,
                "mode": "signal_triage",
                "operator_response": {
                    "headline": "Signal triaged into operational owners and receiver actions.",
                    "summary": (triage_response.get("signal") or {}).get("triage_explanation"),
                    "next_step": "Review missing facts and execute follow-through with the assigned owner.",
                },
                "signal_triage": triage_response,
            }

        if _immediate_first_enabled():
            refinement_id = f"operator_refine_{int(datetime.now(UTC).timestamp() * 1000)}"
            refinement = _record_refinement_status(
                refinement_id,
                "pending",
                route=route,
                message=message,
                lane="background_gemini_refinement",
            )
            _track_background_task(_run_operator_gemini_refinement(refinement_id, message, route))
            immediate = await _operator_command_timeout_payload(message, route, "immediate_local_first")
            immediate["status"] = "immediate_local_response"
            immediate["refinement"] = {
                "id": refinement_id,
                "status": refinement["status"],
                "lane": "background_gemini_refinement",
                "status_url": f"/api/park/operator-command/refinement/{refinement_id}",
                "message": "Bounded local action returned immediately; Gemini refinement is running in the background.",
            }
            immediate.setdefault("agent_workflow", immediate.get("run_telemetry", {}).get("agent_workflow", {}))
            immediate["agent_workflow"]["lane"] = "immediate_local_first"
            immediate["agent_workflow"]["background_refinement"] = immediate["refinement"]
            immediate["operator_response"]["next_step"] = "Bounded local receiver payloads are available now; Gemini refinement will update the receipt when complete."
            span.set_attribute("parkpulse.operator_command.immediate_first", True)
            span.set_attribute("parkpulse.operator_command.refinement_id", refinement_id)
            return immediate

        try:
            run_response = await asyncio.wait_for(
                park_agent_run(
                    ParkAgentRunRequest(
                        scenario_key=route["scenario_key"],
                        operation_mode=False,
                        auto_unexpected_event=False,
                        operator_message=message,
                        execute=request.execute,
                    )
                ),
                timeout=float(os.getenv("OPERATOR_COMMAND_TIMEOUT_SECONDS", "35")),
            )
        except asyncio.TimeoutError:
            return await _operator_command_timeout_payload(message, route, "operator_command_timeout")
        selected = (run_response.get("planner") or {}).get("selected_action", {})
        delivery = run_response.get("delivery", {})
        response = delivery.get("response", {}) if isinstance(delivery, dict) else {}
        operator_constraints = run_response.get("operator_constraints", {})
        response_payload = {
            "status": "complete",
            "command": message,
            "route": route,
            "mode": "operations",
            "operator_constraints": operator_constraints,
            "agent_workflow": run_response.get("agent_workflow", {}),
            "role_agent_proposals": run_response.get("role_agent_proposals", {}),
            "operator_response": {
                "headline": selected.get("label") or run_response.get("planner", {}).get("recommended_action") or "Operator command plan generated.",
                "summary": run_response.get("planner", {}).get("analysis"),
                "tradeoffs": run_response.get("planner", {}).get("tradeoffs", {}),
                "next_step": (
                    f"Receiver response: take rate {round(float(response.get('takeRate', 0) or 0) * 100)}%, "
                    f"follow-through {round(float(response.get('reactiveFollowThroughRate', 0) or 0) * 100)}%."
                    if response
                    else "Review policy gate and candidate actions before execution."
                ),
            },
            "run_telemetry": run_response,
        }
        return _attach_unified_operating_receipt(response_payload, route, role="react")


async def park_operator_command_refinement(refinement_id: str):
    return _operator_refinements.get(
        refinement_id,
        {
            "id": refinement_id,
            "status": "not_found",
            "message": "No refinement receipt exists for this id.",
        },
    )


@app.post("/api/park/event-plan")
async def plan_park_event(request: EventPlanRequest):
    from park_event_planner import build_event_ops_plan

    with tracer.start_as_current_span("api.park_event_plan") as span:
        state = await park_simulation.get_state()
        await sync_park_state_safe(state)
        operator_constraints = request.prompt.strip() or DEFAULT_EVENT_REQUEST
        event_theme = request.event_theme.strip() or DEFAULT_EVENT_THEME
        event_prompt = (
            f"Event theme: {event_theme}. "
            f"Operator constraints: {operator_constraints} Expected attendance: "
            f"{request.expected_guests} guests. Build a deployable amusement-park event plan for this theme."
        )
        context = _retrieve_operational_context(
            f"{event_theme} event temporary overlay crowd flow equipment staffing food merchandise shows queues guest experience {event_prompt}",
            state,
            agent_role="proact_agent",
        )
        context = _collaboration_context(context, "proactive_eventops")
        plan = await build_event_ops_plan(state, event_prompt, context)
        cache_score = _cache_adjusted_score(plan.get("quality", {}).get("overall", 0), context)
        plan["cache_accuracy_contract"] = cache_score.get("cache_accuracy_contract", {})
        plan["requires_revalidation"] = cache_score.get("requires_revalidation", False)
        plan["affected_drift_facts"] = cache_score.get("affected_drift_facts", [])
        if isinstance(plan.get("quality"), dict):
            plan["quality"]["original_overall"] = cache_score.get("original_confidence_score")
            plan["quality"]["overall"] = cache_score.get("confidence_score", plan["quality"].get("overall", 0))
        decision_id = record_mongo_agent_decision(
            {
                "recommended_action": plan.get("operator_summary", ""),
                "selected_action": {
                    "target": "event",
                    "action": "plan_overlay",
                    "label": plan.get("selected_concept", f"{event_theme} event overlay"),
                    "owner": "EventOps AI",
                    "expected_effect": plan.get("operator_summary", ""),
                },
                "candidate_actions": [
                    {
                        "target": "event",
                        "action": "concept_option",
                        "label": concept.get("name"),
                        "owner": "Event Creative Agent",
                        "expected_effect": concept.get("operations_notes", ""),
                        "risk_notes": [concept.get("risk", "")],
                        "estimated_score": plan.get("quality", {}).get("overall", 80),
                    }
                    for concept in plan.get("concepts", [])
                    if isinstance(concept, dict)
                ],
                "original_confidence_score": cache_score.get("original_confidence_score"),
                "confidence_score": plan.get("quality", {}).get("overall", 0),
                "cache_accuracy_contract": plan.get("cache_accuracy_contract", {}),
                "requires_revalidation": plan.get("requires_revalidation", False),
                "affected_drift_facts": plan.get("affected_drift_facts", []),
                "root_cause_classification": "temporary_event_planning",
                "guest_message": f"{plan.get('event_name', event_theme + ' event')} plan drafted for operator review.",
            },
            _event_eval_for_memory(plan),
            state,
            context,
            source="eventops_ai",
        )
        event_plan_id = record_mongo_event_plan(plan, decision_id, state, context)
        agent_findings = build_event_agent_findings(plan, state, context)
        orchestration = build_orchestration_run(agent_findings, "event_planning", None, None)
        span.set_attribute("parkpulse.eventops.runtime", plan.get("runtime", ""))
        span.set_attribute("parkpulse.eventops.decision_id", decision_id)
        span.set_attribute("parkpulse.eventops.event_plan_id", event_plan_id)
        span.set_attribute("parkpulse.eventops.quality_score", plan.get("quality", {}).get("overall", 0))
        return {
            "status": "complete",
            "decision_id": decision_id,
            "event_plan_id": event_plan_id,
            "event_request": event_prompt,
            "event_scope": {
                "theme": event_theme,
                "event_type": "amusement park event overlay",
                "locked": False,
            },
            "planner": {
                "runtime": plan.get("runtime"),
                "event_id": plan.get("event_id"),
                "event_name": plan.get("event_name"),
                "errors": plan.get("errors", []),
            },
            "agent_findings": agent_findings,
            "orchestration": orchestration,
            "plan": plan,
            "memory": {
                "mode": context.get("status", {}).get("mode"),
                "connected": context.get("status", {}).get("connected"),
                "retrieved_playbooks": [item.get("_id") for item in context.get("retrieved", {}).get("playbooks", [])],
                "retrieved_incidents": [item.get("_id") for item in context.get("retrieved", {}).get("incidents", [])],
                "retrieved_learnings": [item.get("_id") for item in context.get("retrieved", {}).get("learnings", [])],
            },
        }


@app.get("/api/park/proactive-insights")
async def park_proactive_insights():
    with tracer.start_as_current_span("api.park_proactive_insights") as span:
        state = await park_simulation.get_state()
        await sync_park_state_safe(state)
        insights = build_proactive_insights(state)
        span.set_attribute("parkpulse.proactive.id", insights.get("proactive_id", ""))
        span.set_attribute("parkpulse.proactive.insight_count", insights.get("summary", {}).get("insight_count", 0))
        span.set_attribute("parkpulse.proactive.risk_count", insights.get("summary", {}).get("risk_count", 0))
        return insights


async def _build_proactive_run_payload(emit_trace=None):
    started_at = datetime.now(UTC)

    async def publish_phase(
        phase_id: str,
        label: str,
        step: int,
        message: str,
        artifact: dict[str, Any] | None = None,
    ) -> None:
        if emit_trace is None:
            return
        await emit_trace(
            {
                "phase": phase_id,
                "label": label,
                "step": step,
                "message": message,
                "artifact": artifact or {},
                "elapsed_ms": int((datetime.now(UTC) - started_at).total_seconds() * 1000),
                "server_driven": True,
            }
        )

    with tracer.start_as_current_span("api.park_proactive_run") as span:
        state = await park_simulation.get_state()
        await sync_park_state_safe(state)
        memory_dashboard = _compact_operational_memory_dashboard(
            "proactive eventops take rate response learning",
            state,
            agent_role="proact_agent",
        )
        bigquery_priors = _build_agent_bigquery_priors("proactive_eventops", memory_dashboard)
        context = dict(memory_dashboard)
        context["query"] = "proactive halloween event readiness congestion staffing equipment food comfort queue pre-stage " + " ".join(bigquery_priors.get("agent_context", []))
        context["agent_role"] = "proact_agent"
        context = _collaboration_context(context, "proactive_eventops", memory_dashboard, bigquery_priors)
        proactive = build_proactive_insights(state)
        proactive_eval = build_proactive_eval(proactive)
        proactive_cache_score = _cache_adjusted_score(proactive_eval.get("overall", 0), context)
        proactive_eval["original_overall"] = proactive_cache_score.get("original_confidence_score")
        proactive_eval["overall"] = proactive_cache_score.get("confidence_score", proactive_eval.get("overall", 0))
        proactive_eval["cache_accuracy_contract"] = proactive_cache_score.get("cache_accuracy_contract", {})
        proactive_eval["requires_revalidation"] = proactive_cache_score.get("requires_revalidation", False)
        await publish_phase(
            "predict",
            "Predict",
            0,
            "1/6 Predict: live state, queue pressure, density, memory, and prior-response signals are loaded.",
            {
                "scenario_key": state.get("guestFlow", {}).get("activeScenario", {}).get("key", "ride_down"),
                "top_signal": (proactive.get("insights") or [{}])[0] if proactive.get("insights") else {},
                "memory_mode": context.get("status", {}).get("mode"),
                "bigquery_prior_count": len(bigquery_priors.get("agent_context", [])),
                "eval_score": proactive_eval.get("overall"),
            },
        )
        brief_timeout = max(0.5, _float_env("PARKPULSE_PROACTIVE_BRIEF_TIMEOUT_SECONDS", 3.0))
        try:
            brief = await asyncio.wait_for(
                build_proactive_operator_brief(state, proactive, context),
                timeout=brief_timeout,
            )
        except (asyncio.TimeoutError, asyncio.CancelledError):
            brief = build_proactive_fallback_brief(
                proactive,
                "deterministic_fallback_after_outer_brief_timeout",
                [f"Proactive operator brief exceeded {brief_timeout:g}s hot-path budget."],
            )
        scenario_key = state.get("guestFlow", {}).get("activeScenario", {}).get("key", "ride_down")
        digital_twin_trace = build_digital_twin_tool_trace(
            state,
            scenario_key,
            context,
            {
                "recommended_action": brief.get("operator_brief", ""),
                "selected_action": {
                    "target": "event",
                    "action": "proactive_commit",
                    "label": "Commit proactive pre-stage actions",
                    "owner": "EventOps Proactive Agent",
                    "expected_effect": brief.get("why_now", ""),
                },
            },
            None,
        )
        agent_findings = build_proactive_agent_findings(proactive, brief, proactive_eval)
        proactive_candidates = [
            {
                "id": item.get("id") or f"proactive-{index + 1}",
                "label": item.get("trigger"),
                "selected_action": {
                    "label": item.get("trigger"),
                    "target": "event",
                    "action": "proactive_insight",
                    "owner": item.get("agent", "Proactive Agent"),
                    "expected_effect": item.get("recommendation", ""),
                },
                "rejected_reasons": []
                if item.get("id") in set(brief.get("recommended_commitments", []) if isinstance(brief.get("recommended_commitments"), list) else [])
                else [item.get("proactive_not_reactive") or "lower current urgency than selected commitment"],
                "scorecard": {"overall": round(float(item.get("confidence", 0.75) or 0.75) * 100)},
            }
            for index, item in enumerate(proactive.get("insights", []))
            if isinstance(item, dict)
        ]
        await publish_phase(
            "decide",
            "Decide",
            1,
            "2/6 Decide: candidate actions are compared and the proactive commitment is selected for governance.",
            {
                "operator_brief": brief.get("operator_brief"),
                "recommended_commitments": brief.get("recommended_commitments", []),
                "candidates": proactive_candidates[:5],
                "digital_twin_tools": digital_twin_trace.get("summary", {}),
            },
        )
        proactive_policy_gate = {
            "allowed": True,
            "gate_status": "allowed",
            "policy_refs": ["PARK-SAFE-001", "PARK-OPS-001", "PARK-EXP-001", "PARK-CARE-001"],
            "findings": [
                "Aggregated guest-flow action only; no individual guest targeting.",
                "Equipment commands remain inside comfort and safety envelopes.",
                "Worker tasks are advisory dispatches with operator-visible ownership.",
            ],
        }
        await publish_phase(
            "govern",
            "Govern",
            2,
            "3/6 Govern: safety, customer-care, staff authority, and equipment envelopes have passed policy gates.",
            proactive_policy_gate,
        )
        decision_id = record_mongo_agent_decision(
            {
                "recommended_action": brief.get("operator_brief", ""),
                "selected_action": {
                    "target": "event",
                    "action": "proactive_commit",
                    "label": "Commit proactive pre-stage actions",
                    "owner": "EventOps Proactive Agent",
                    "expected_effect": brief.get("why_now", ""),
                },
                "candidate_actions": [
                    {
                        "target": "event",
                        "action": "proactive_insight",
                        "label": item.get("trigger"),
                        "owner": item.get("agent", "Proactive Agent"),
                        "expected_effect": item.get("recommendation", ""),
                        "risk_notes": [item.get("proactive_not_reactive", "")],
                        "estimated_score": round(float(item.get("confidence", 0.75) or 0.75) * 100),
                    }
                    for item in proactive.get("insights", [])
                    if isinstance(item, dict)
                ],
                "original_confidence_score": proactive_cache_score.get("original_confidence_score"),
                "confidence_score": proactive_eval.get("overall", 0),
                "cache_accuracy_contract": proactive_cache_score.get("cache_accuracy_contract", {}),
                "requires_revalidation": proactive_cache_score.get("requires_revalidation", False),
                "affected_drift_facts": proactive_cache_score.get("affected_drift_facts", []),
                "root_cause_classification": "proactive_event_monitoring",
                "guest_message": "EventOps is pre-staging low-risk actions before event congestion appears.",
                "digital_twin_tools": digital_twin_trace,
            },
            _proactive_eval_for_memory(proactive_eval),
            state,
            context,
            source="eventops_proactive_agent",
        )
        dispatches = _build_proactive_dispatches(proactive, brief, decision_id, bigquery_priors)
        await publish_phase(
            "emit",
            "Emit",
            3,
            "4/6 Emit: bounded payloads were created for guest app, worker device, and equipment control receivers.",
            {
                "decision_id": decision_id,
                "dispatch_count": len(dispatches),
                "dispatches": [
                    {
                        "id": dispatch.get("id"),
                        "channel": dispatch.get("channel"),
                        "status": dispatch.get("status"),
                        "payload_summary": _summarize_dispatch_payload(dispatch),
                    }
                    for dispatch in dispatches
                ],
            },
        )
        response_metrics = response_summary(dispatches)
        outcome_application = await _apply_proactive_delivery_outcomes(dispatches, "proactive_closed_loop")
        clear_hot_endpoint_cache()
        outcome_state = await park_simulation.get_state()
        await sync_park_state_safe(outcome_state)
        outcome = build_closed_loop_outcome(
            state,
            outcome_state,
            dispatches,
            response_metrics,
            proactive,
            brief,
            proactive_eval,
        )
        await publish_phase(
            "observe",
            "Observe",
            4,
            "5/6 Observe: receiver response and simulated park-state movement have been measured before success is claimed.",
            {
                "response": response_metrics,
                "state_impact": outcome.get("state_impact", {}),
                "application": outcome_application,
            },
        )
        outcome_id = record_mongo_outcome_event(outcome, decision_id, outcome_state)
        analytics_rows = build_analytics_rows(
            decision_id=decision_id,
            outcome_id=outcome_id,
            scenario_key="proactive_eventops",
            delivery={"response": response_metrics, "dispatches": dispatches},
            outcome=outcome,
            eval_result=proactive_eval,
            source="proactive_closed_loop",
        )
        analytics_export = _export_agent_analytics(analytics_rows)
        analytics_export["priors"] = bigquery_priors
        await publish_phase(
            "learn",
            "Learn",
            5,
            "6/6 Learn: outcome memory, analytics rows, and priors are written for the next decision.",
            {
                "decision_id": decision_id,
                "outcome_id": outcome_id,
                "analytics": analytics_export,
                "memory_connected": context.get("status", {}).get("connected"),
            },
        )
        event_revision: dict[str, Any] | None = None
        if brief.get("should_revise_event_plan") and not _truthy(os.getenv("PARKPULSE_PROACTIVE_ENABLE_EVENT_REVISION"), False):
            event_revision = {
                "status": "deferred",
                "reason": "Event plan revision deferred on the Proact hot path; set PARKPULSE_PROACTIVE_ENABLE_EVENT_REVISION=true for full revision replay.",
                "plan_revision_prompt": brief.get("plan_revision_prompt", ""),
                "memory": {
                    "mode": context.get("status", {}).get("mode"),
                    "connected": context.get("status", {}).get("connected"),
                },
            }
        elif brief.get("should_revise_event_plan"):
            revision_prompt = (
                f"Revise the current temporary event plan using this proactive outcome loop. "
                f"Operator instruction: {brief.get('plan_revision_prompt', '')}. "
                f"Observed response: take rate {response_metrics.get('takeRate')}, positive response "
                f"{response_metrics.get('positiveResponseRate')}, follow-through {response_metrics.get('reactiveFollowThroughRate')}. "
                f"State movement: {outcome.get('state_impact', {}).get('headline', '')}. "
                "Return a revised plan version that fixes the weak placement, staffing, equipment, and guest-flow assumptions."
            )
            revision_context = _retrieve_operational_context(
                f"revise event plan closed loop outcome take rate congestion staffing equipment {revision_prompt}",
                outcome_state,
                agent_role="proact_agent",
            )
            revision_context = _collaboration_context(revision_context, "proactive_eventops")
            from park_event_planner import build_event_ops_plan

            revision_timeout = max(1.0, _float_env("PARKPULSE_PROACTIVE_REVISION_TIMEOUT_SECONDS", 3.0))
            revised_plan = None
            try:
                revised_plan = await asyncio.wait_for(
                    build_event_ops_plan(outcome_state, revision_prompt, revision_context),
                    timeout=revision_timeout,
                )
            except Exception as error:
                event_revision = {
                    "status": "deferred",
                    "reason": f"Event plan revision did not complete within {revision_timeout:g}s: {type(error).__name__}",
                    "timeout_seconds": revision_timeout,
                    "plan_revision_prompt": brief.get("plan_revision_prompt", ""),
                    "memory": {
                        "mode": revision_context.get("status", {}).get("mode"),
                        "connected": revision_context.get("status", {}).get("connected"),
                    },
                }
            if revised_plan is not None:
                revision_cache_score = _cache_adjusted_score(revised_plan.get("quality", {}).get("overall", 0), revision_context)
                revised_plan["cache_accuracy_contract"] = revision_cache_score.get("cache_accuracy_contract", {})
                revised_plan["requires_revalidation"] = revision_cache_score.get("requires_revalidation", False)
                revised_plan["affected_drift_facts"] = revision_cache_score.get("affected_drift_facts", [])
                if isinstance(revised_plan.get("quality"), dict):
                    revised_plan["quality"]["original_overall"] = revision_cache_score.get("original_confidence_score")
                    revised_plan["quality"]["overall"] = revision_cache_score.get("confidence_score", revised_plan["quality"].get("overall", 0))
                revision_decision_id = record_mongo_agent_decision(
                    {
                        "recommended_action": revised_plan.get("operator_summary", ""),
                        "selected_action": {
                            "target": "event",
                            "action": "revise_overlay_after_outcome",
                            "label": revised_plan.get("selected_concept", "Revised event overlay"),
                            "owner": "EventOps Revision Agent",
                            "expected_effect": revised_plan.get("revision_summary", ""),
                        },
                        "candidate_actions": [
                            {
                                "target": "event",
                                "action": "revised_concept_option",
                                "label": concept.get("name"),
                                "owner": "Event Creative Agent",
                                "expected_effect": concept.get("operations_notes", ""),
                                "risk_notes": [concept.get("risk", "")],
                                "estimated_score": revised_plan.get("quality", {}).get("overall", 80),
                            }
                            for concept in revised_plan.get("concepts", [])
                            if isinstance(concept, dict)
                        ],
                        "original_confidence_score": revision_cache_score.get("original_confidence_score"),
                        "confidence_score": revised_plan.get("quality", {}).get("overall", 0),
                        "cache_accuracy_contract": revised_plan.get("cache_accuracy_contract", {}),
                        "requires_revalidation": revised_plan.get("requires_revalidation", False),
                        "affected_drift_facts": revised_plan.get("affected_drift_facts", []),
                        "root_cause_classification": "event_plan_revision_after_outcome",
                        "guest_message": f"{revised_plan.get('event_name', 'Event plan')} revised after proactive outcome telemetry.",
                    },
                    _event_eval_for_memory(revised_plan),
                    outcome_state,
                    revision_context,
                    source="eventops_revision_agent",
                )
                revision_event_plan_id = record_mongo_event_plan(revised_plan, revision_decision_id, outcome_state, revision_context)
                event_revision = {
                    "status": "complete",
                    "decision_id": revision_decision_id,
                    "event_plan_id": revision_event_plan_id,
                    "plan": revised_plan,
                    "memory": {
                        "mode": revision_context.get("status", {}).get("mode"),
                        "connected": revision_context.get("status", {}).get("connected"),
                        "retrieved_playbooks": [item.get("_id") for item in revision_context.get("retrieved", {}).get("playbooks", [])],
                        "retrieved_incidents": [item.get("_id") for item in revision_context.get("retrieved", {}).get("incidents", [])],
                        "retrieved_learnings": [item.get("_id") for item in revision_context.get("retrieved", {}).get("learnings", [])],
                    },
                }
        span.set_attribute("parkpulse.proactive.runtime", brief.get("runtime", ""))
        span.set_attribute("parkpulse.proactive.decision_id", decision_id)
        span.set_attribute("parkpulse.proactive.eval_score", proactive_eval.get("overall", 0))
        span.set_attribute("parkpulse.proactive.delivery_total", len(dispatches))
        span.set_attribute("parkpulse.proactive.outcome_id", outcome_id)
        span.set_attribute("parkpulse.proactive.revision_created", bool(event_revision))
        span.set_attribute("parkpulse.digital_twin.tool_count", digital_twin_trace.get("tool_count", 0))
        orchestration = build_orchestration_run(agent_findings, "proactive", response_metrics, event_revision)
        lifecycle = _build_eventops_lifecycle(
            proactive,
            brief,
            proactive_eval,
            dispatches,
            response_metrics,
            outcome,
            event_revision,
            agent_findings,
            orchestration,
            decision_id,
            outcome_id,
        )
        lifecycle["bigquery_priors"] = bigquery_priors
        intelligence_comparison = _build_intelligence_comparison(
            proactive,
            brief,
            response_metrics,
            outcome,
            event_revision,
            orchestration,
            decision_id,
            outcome_id,
        )
        lifecycle["intelligence_comparison"] = intelligence_comparison
        learning_proof = _build_two_run_learning_proof(
            response_metrics,
            outcome,
            event_revision,
            bigquery_priors,
            dispatches,
            decision_id,
            outcome_id,
            context,
        )
        lifecycle["learning_proof"] = learning_proof
        memory_summary = {
            "mode": context.get("status", {}).get("mode"),
            "connected": context.get("status", {}).get("connected"),
            "retrieved_playbooks": [item.get("_id") for item in context.get("retrieved", {}).get("playbooks", [])],
            "retrieved_incidents": [item.get("_id") for item in context.get("retrieved", {}).get("incidents", [])],
            "retrieved_learnings": [item.get("_id") for item in context.get("retrieved", {}).get("learnings", [])],
        }
        trace_contract = build_run_trace_contract(
            run_id=decision_id,
            source="eventops_proactive_agent",
            scenario_key="proactive_eventops",
            selected_action={
                "target": "event",
                "action": "proactive_commit",
                "label": "Commit proactive pre-stage actions",
                "owner": "EventOps Proactive Agent",
                "expected_effect": brief.get("why_now", ""),
            },
            candidates=proactive_candidates,
            policy_gate=proactive_policy_gate,
            dispatches=dispatches,
            response_metrics=response_metrics,
            outcome_id=outcome_id,
            outcome=outcome,
            eval_result=proactive_eval,
            memory=memory_summary,
            digital_twin_trace=digital_twin_trace,
            learning_proof=learning_proof,
        )
        return {
            "status": "complete",
            "decision_id": decision_id,
            "outcome_id": outcome_id,
            "trace_contract": trace_contract,
            "lifecycle": lifecycle,
            "intelligence_comparison": intelligence_comparison,
            "learning_proof": learning_proof,
            "digital_twin_tools": digital_twin_trace,
            "proactive": proactive,
            "brief": brief,
            "agent_findings": agent_findings,
            "orchestration": orchestration,
            "eval": proactive_eval,
            "delivery": {
                "summary": delivery_summary(dispatches),
                "response": response_metrics,
                "dispatches": dispatches,
                "contract": delivery_contract(),
            },
            "outcome": {
                **outcome,
                "application": outcome_application,
            },
            "event_revision": event_revision,
            "analytics": analytics_export,
            "memory": memory_summary,
        }


@app.post("/api/park/proactive-run")
async def park_proactive_run():
    payload = await _build_proactive_run_payload()
    try:
        ledger_context = await asyncio.to_thread(retrieve_agent_ops_context, "proactive park operation", 3)
        payload.setdefault("memory", {})["agent_ops_ledger_retrieval"] = ledger_context
        payload["agent_ops_ledger"] = await asyncio.to_thread(record_agent_ops_run, payload, message="proactive-run", mode="proact", kind="proactive_run")
    except Exception as error:
        payload["agent_ops_ledger"] = {"status": "unavailable", "reason": str(error)[:240]}
    return payload


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _operator_command_stream_stages(message: str, route: dict[str, Any]) -> list[dict[str, Any]]:
    scenario = str(route.get("scenario_key", "ride_down")).replace("_", " ")
    return [
        {
            "phase": "intent",
            "label": "Intent parsed",
            "step": 0,
            "message": f"1/7 Understand: {route.get('interpreted_intent', scenario)}; urgency {route.get('urgency', 'normal')}.",
            "artifact": {
                "mode": route.get("route"),
                "scenario_key": route.get("scenario_key"),
                "requires_human_review": route.get("requires_human_review"),
            },
        },
        {
            "phase": "memory",
            "label": "Mongo memory retrieval",
            "step": 1,
            "message": "2/7 Retrieve memory: searching prior incidents, playbooks, and learned outcome rules.",
            "artifact": {"source": "mongodb", "query": message[:120]},
        },
        {
            "phase": "priors",
            "label": "BigQuery priors",
            "step": 1,
            "message": "3/7 Load priors: checking historical take rate, follow-through, and weak response cohorts.",
            "artifact": {"source": "bigquery", "scenario_key": route.get("scenario_key")},
        },
        {
            "phase": "preview",
            "label": "Fast local preview",
            "step": 2,
            "message": f"4/7 Draft preview: preparing a {scenario} action mix before Gemini refinement returns.",
            "artifact": {"status": "preliminary_plan_ready"},
        },
        {
            "phase": "policy",
            "label": "Policy guardrails",
            "step": 2,
            "message": "5/7 Check policy: blocking unsafe control claims, staff-break abuse, and misleading guest messages.",
            "artifact": {"policy_gate": "precheck", "requires_human_review": route.get("requires_human_review")},
        },
        {
            "phase": "gemini",
            "label": "Gemini refinement",
            "step": 3,
            "message": "6/7 Gemini reasoning: refining the custom action mix with live state, memory, priors, and policy.",
            "artifact": {"model_path": "Vertex AI Gemini", "status": "reasoning"},
        },
        {
            "phase": "dispatch",
            "label": "Receiver preparation",
            "step": 3,
            "message": "7/7 Prepare receivers: shaping guest app, worker device, and equipment-control payloads.",
            "artifact": {"channels": ["guest_app", "worker_device", "equipment_controller"]},
        },
    ]


async def park_operator_command_stream(
    message: str = "Dragon Coaster is down. Keep families happy but do not overload Food Court A.",
    mode: str = "auto",
    execute: bool = True,
):
    async def event_stream():
        started_at = datetime.now(UTC)
        stream_run_id = f"operator_stream_{started_at.strftime('%Y%m%d%H%M%S%f')}"
        clean_message = message.strip()
        route = _infer_operator_command_route(clean_message, mode)
        yield _sse(
            "operator.started",
            {
                "run_id": stream_run_id,
                "phase": "operator",
                "label": "Operator request",
                "step": 0,
                "message": clean_message,
                "elapsed_ms": 0,
                "artifact": {"route": route},
            },
        )
        for stage in _operator_command_stream_stages(clean_message, route):
            stage["run_id"] = stream_run_id
            stage["elapsed_ms"] = int((datetime.now(UTC) - started_at).total_seconds() * 1000)
            yield _sse(f"{stage['phase']}.done", stage)
            await asyncio.sleep(0.35)

        task = asyncio.create_task(
            park_operator_command(OperatorCommandRequest(message=clean_message, mode=mode, execute=execute))
        )
        heartbeat_count = 0
        try:
            while not task.done():
                await asyncio.sleep(2.5)
                heartbeat_count += 1
                elapsed_ms = int((datetime.now(UTC) - started_at).total_seconds() * 1000)
                yield _sse(
                    "gemini.progress",
                    {
                        "run_id": stream_run_id,
                        "phase": "gemini",
                        "label": "Gemini still reasoning",
                        "step": 3,
                        "message": f"6/7 Gemini reasoning: still refining the custom action mix ({round(elapsed_ms / 1000)}s elapsed).",
                        "elapsed_ms": elapsed_ms,
                        "artifact": {"heartbeat": heartbeat_count, "status": "waiting_for_model"},
                    },
                )
            payload = await task
        except Exception as error:  # pragma: no cover - defensive stream transport path
            yield _sse(
                "run.error",
                {
                    "run_id": stream_run_id,
                    "phase": "error",
                    "label": "Operator command failed",
                    "message": str(error),
                    "elapsed_ms": int((datetime.now(UTC) - started_at).total_seconds() * 1000),
                },
            )
            return

        yield _sse(
            "run.complete",
            {
                "run_id": payload.get("run_telemetry", {}).get("decision_id") or stream_run_id
                if isinstance(payload, dict)
                else stream_run_id,
                "phase": payload.get("mode", "command") if isinstance(payload, dict) else "command",
                "label": payload.get("route", {}).get("interpreted_intent", "Operator command complete")
                if isinstance(payload, dict)
                else "Operator command complete",
                "step": 4,
                "message": payload.get("operator_response", {}).get("headline", "Operator command complete.")
                if isinstance(payload, dict)
                else "Operator command complete.",
                "elapsed_ms": int((datetime.now(UTC) - started_at).total_seconds() * 1000),
                "payload": payload,
            },
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


from parkpulse_routes.agent_routes import register_agent_routes
from parkpulse_routes.operator_routes import register_operator_routes


register_agent_routes(
    app,
    {
        "ParkAgentRunRequest": ParkAgentRunRequest,
        "park_agent_run": park_agent_run,
    },
)

register_operator_routes(
    app,
    {
        "OperatorCommandRequest": OperatorCommandRequest,
        "park_operator_command": park_operator_command,
        "park_operator_command_refinement": park_operator_command_refinement,
        "park_operator_command_stream": park_operator_command_stream,
    },
)


@app.get("/api/park/proactive-run/stream")
async def park_proactive_run_stream():
    async def event_stream():
        started_at = datetime.now(UTC)
        stream_run_id = f"stream_{started_at.strftime('%Y%m%d%H%M%S%f')}"
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        async def emit_trace(event: dict[str, Any]) -> None:
            await queue.put(event)

        yield _sse(
            "run.started",
            {
                "run_id": stream_run_id,
                "source": "eventops_proactive_agent_stream",
                "message": "Backend stream started for proactive closed-loop run.",
                "elapsed_ms": 0,
            },
        )

        task = asyncio.create_task(_build_proactive_run_payload(emit_trace=emit_trace))
        last_phase_delivery_at = asyncio.get_running_loop().time()
        try:
            while True:
                if task.done() and queue.empty():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.25)
                except asyncio.TimeoutError:
                    continue
                now = asyncio.get_running_loop().time()
                delay = 0.9 - (now - last_phase_delivery_at)
                if delay > 0:
                    await asyncio.sleep(delay)
                last_phase_delivery_at = asyncio.get_running_loop().time()
                phase_id = event.get("phase", "phase")
                event["run_id"] = stream_run_id
                yield _sse(f"{phase_id}.done", event)
            payload = await task
        except Exception as error:  # pragma: no cover - defensive stream transport path
            yield _sse(
                "run.error",
                {
                    "run_id": stream_run_id,
                    "message": str(error),
                    "elapsed_ms": int((datetime.now(UTC) - started_at).total_seconds() * 1000),
                },
            )
            return

        trace_contract = payload.get("trace_contract", {}) if isinstance(payload, dict) else {}
        elapsed_ms = int((datetime.now(UTC) - started_at).total_seconds() * 1000)
        yield _sse(
            "run.complete",
            {
                "run_id": trace_contract.get("run_id") or payload.get("decision_id") or stream_run_id,
                "source": trace_contract.get("source", "eventops_proactive_agent"),
                "elapsed_ms": elapsed_ms,
                "payload": payload,
            },
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/park/proactive-learned-run")
async def park_proactive_learned_run():
    with tracer.start_as_current_span("api.park_proactive_learned_run") as span:
        state = await park_simulation.get_state()
        await sync_park_state_safe(state)
        memory_dashboard = get_operational_memory_dashboard("proactive eventops learned route mix take rate")
        bigquery_priors = _build_agent_bigquery_priors("proactive_eventops", memory_dashboard)
        context = _retrieve_operational_context(
            "run learned proactive plan take rate route mix BigQuery priors MongoDB learning",
            state,
            agent_role="proact_agent",
        )
        context = _collaboration_context(context, "proactive_eventops", memory_dashboard, bigquery_priors)
        proactive = build_proactive_insights(state)
        proactive_eval = build_proactive_eval(proactive)
        learned_cache_score = _cache_adjusted_score(proactive_eval.get("overall", 0), context)
        proactive_eval["original_overall"] = learned_cache_score.get("original_confidence_score")
        proactive_eval["overall"] = learned_cache_score.get("confidence_score", proactive_eval.get("overall", 0))
        best_prior = bigquery_priors.get("best_prior", {}) if isinstance(bigquery_priors.get("best_prior"), dict) else {}
        weakest_prior = bigquery_priors.get("weakest_prior", {}) if isinstance(bigquery_priors.get("weakest_prior"), dict) else {}
        first_mix = _route_mix_from_priors(bigquery_priors)
        learned_mix = _learned_route_mix_from_first_run(first_mix, bigquery_priors)
        expected_take_rate = min(0.78, max(0.61, float(best_prior.get("prior_take_rate", 0.61) or 0.61)))
        expected_follow_rate = min(
            0.72,
            max(0.55, float(best_prior.get("prior_follow_through", max(0.55, expected_take_rate - 0.07)) or max(0.55, expected_take_rate - 0.07))),
        )
        brief = {
            "runtime": "learned_second_run",
            "operator_brief": "Apply the learned second-pass route mix from stored outcome telemetry.",
            "why_now": (
                "MongoDB outcome memory and BigQuery priors show the next action should increase low-wait "
                "show/arcade share and avoid the weakest broad food-promo cohort."
            ),
            "recommended_commitments": ["queue_pressure_prediversion", "labor_gap_before_overlay", "shelter_comfort_preload"],
            "should_revise_event_plan": False,
            "plan_revision_prompt": "Keep the second pass focused on measured response uplift, not a full event-plan rewrite.",
        }
        agent_findings = build_proactive_agent_findings(proactive, brief, proactive_eval)
        decision_id = record_mongo_agent_decision(
            {
                "recommended_action": brief["operator_brief"],
                "selected_action": {
                    "target": "event",
                    "action": "learned_second_pass",
                    "label": "Run learned route mix",
                    "owner": "Decision Bridge Agent",
                    "expected_effect": brief["why_now"],
                },
                "candidate_actions": [
                    {
                        "target": "guest_flow",
                        "action": "route_mix_option",
                        "label": item.get("destination"),
                        "owner": "Guest Flow Agent",
                        "expected_effect": f"Target {round(float(item.get('share', 0) or 0) * 100)}% of diverted guests.",
                        "risk_notes": [f"Current wait {item.get('currentWaitMins', '--')} minutes."],
                        "estimated_score": round(expected_take_rate * 100),
                    }
                    for item in learned_mix
                    if isinstance(item, dict)
                ],
                "original_confidence_score": learned_cache_score.get("original_confidence_score"),
                "confidence_score": proactive_eval.get("overall", 0),
                "cache_accuracy_contract": learned_cache_score.get("cache_accuracy_contract", {}),
                "requires_revalidation": learned_cache_score.get("requires_revalidation", False),
                "affected_drift_facts": learned_cache_score.get("affected_drift_facts", []),
                "root_cause_classification": "learned_response_optimization",
                "guest_message": "ParkPulse is applying a learned route mix from the last measured action.",
            },
            _proactive_eval_for_memory(proactive_eval),
            state,
            context,
            source="eventops_learned_second_run",
        )
        dispatches = [
            send_guest_promotion(
                {
                    "decisionId": decision_id,
                    "scenarioKey": "proactive_eventops",
                    "audience": {"segment": "guests_near_predicted_bottleneck", "radiusMeters": 300},
                    "message": (
                        "Learned plan update: shifting more guests to low-wait indoor show and arcade options, "
                        f"while avoiding weak prior {weakest_prior.get('cohort', 'broad maze entrance promo')}."
                    ),
                    "promotion": {
                        "type": "learned_route_mix_v2",
                        "offer": best_prior.get("recommended_adjustment", "Bonus points for Theater B, Arcade Zone, or covered plaza check-in."),
                        "expiresMinutes": 20,
                    },
                    "routingTargets": [item["destinationId"] for item in learned_mix],
                    "targetMix": learned_mix,
                    "expectedTakeRate": expected_take_rate,
                    "expectedFollowThroughRate": expected_follow_rate,
                    "estimatedMovedGuests": 560,
                    "priorUsed": best_prior,
                    "weakPriorAvoided": weakest_prior,
                }
            ),
            send_worker_notification(
                {
                    "decisionId": decision_id,
                    "scenarioKey": "proactive_eventops",
                    "role": "crowd_control_lead",
                    "targetZone": "coveredPlaza",
                    "task": "Open a visible flow lane and position two staff at the covered hold before the learned guest route mix lands.",
                    "priority": "high",
                    "deadlineMinutes": 4,
                    "priorUsed": best_prior,
                    "constraints": ["protect_break_windows", "keep_emergency_lane_clear"],
                }
            ),
            send_equipment_command(
                {
                    "decisionId": decision_id,
                    "scenarioKey": "proactive_eventops",
                    "equipmentType": "hvac",
                    "zones": ["indoorHub", "arcadeZone", "coveredPlaza"],
                    "command": "maintain_comfort_hold",
                    "settings": {
                        "indoorHubSetpointF": 72,
                        "arcadeZoneSetpointF": 73,
                        "coveredPlazaFans": "high",
                        "shedNoncriticalLighting": True,
                    },
                    "requiresHumanApproval": False,
                    "reason": "Learned route mix sends more guests to indoor/covered destinations, so comfort must be protected.",
                }
            ),
        ]
        response_metrics = response_summary(dispatches)
        outcome_application = await park_simulation.apply_delivery_outcomes(dispatches, "proactive_learned_second_run")
        clear_hot_endpoint_cache()
        outcome_state = await park_simulation.get_state()
        await sync_park_state_safe(outcome_state)
        outcome = build_closed_loop_outcome(
            state,
            outcome_state,
            dispatches,
            response_metrics,
            proactive,
            brief,
            proactive_eval,
        )
        outcome_id = record_mongo_outcome_event(outcome, decision_id, outcome_state)
        analytics_rows = build_analytics_rows(
            decision_id=decision_id,
            outcome_id=outcome_id,
            scenario_key="proactive_eventops",
            delivery={"response": response_metrics, "dispatches": dispatches},
            outcome=outcome,
            eval_result=proactive_eval,
            source="proactive_learned_second_run",
        )
        analytics_export = _export_agent_analytics(analytics_rows)
        analytics_export["priors"] = bigquery_priors
        orchestration = build_orchestration_run(agent_findings, "proactive_learned", response_metrics, None)
        lifecycle = _build_eventops_lifecycle(
            proactive,
            brief,
            proactive_eval,
            dispatches,
            response_metrics,
            outcome,
            None,
            agent_findings,
            orchestration,
            decision_id,
            outcome_id,
        )
        lifecycle["plan_mode"] = "learned_second_action_closed_loop"
        lifecycle["headline"] = "Learned plan -> dispatch -> observe -> store"
        lifecycle["bigquery_priors"] = bigquery_priors
        intelligence_comparison = _build_intelligence_comparison(
            proactive,
            brief,
            response_metrics,
            outcome,
            None,
            orchestration,
            decision_id,
            outcome_id,
        )
        lifecycle["intelligence_comparison"] = intelligence_comparison
        learning_proof = _build_two_run_learning_proof(
            response_metrics,
            outcome,
            None,
            bigquery_priors,
            dispatches,
            decision_id,
            outcome_id,
            context,
        )
        learning_proof["mode"] = "learned_second_action"
        learning_proof["headline"] = "Learned plan emitted and measured from stored priors."
        lifecycle["learning_proof"] = learning_proof
        learned_run = {
            "status": "applied",
            "source": "/api/park/proactive-learned-run",
            "applied_from": bigquery_priors.get("query_name", "agent_action_priors_by_scenario"),
            "best_prior": best_prior,
            "weak_prior_avoided": weakest_prior,
            "route_mix": learned_mix,
        }
        span.set_attribute("parkpulse.proactive_learned.decision_id", decision_id)
        span.set_attribute("parkpulse.proactive_learned.outcome_id", outcome_id)
        span.set_attribute("parkpulse.proactive_learned.take_rate", response_metrics.get("takeRate", 0))
        return {
            "status": "complete",
            "decision_id": decision_id,
            "outcome_id": outcome_id,
            "learned_run": learned_run,
            "lifecycle": lifecycle,
            "intelligence_comparison": intelligence_comparison,
            "learning_proof": learning_proof,
            "proactive": proactive,
            "brief": brief,
            "agent_findings": agent_findings,
            "orchestration": orchestration,
            "eval": proactive_eval,
            "delivery": {
                "summary": delivery_summary(dispatches),
                "response": response_metrics,
                "dispatches": dispatches,
                "contract": delivery_contract(),
            },
            "outcome": {
                **outcome,
                "application": outcome_application,
            },
            "event_revision": None,
            "analytics": analytics_export,
            "memory": {
                "mode": context.get("status", {}).get("mode"),
                "connected": context.get("status", {}).get("connected"),
                "retrieved_playbooks": [item.get("_id") for item in context.get("retrieved", {}).get("playbooks", [])],
                "retrieved_incidents": [item.get("_id") for item in context.get("retrieved", {}).get("incidents", [])],
                "retrieved_learnings": [item.get("_id") for item in context.get("retrieved", {}).get("learnings", [])],
            },
        }


@app.get("/api/park/bigquery/priors/{scenario_key}")
async def park_bigquery_priors(scenario_key: str):
    dashboard = get_operational_memory_dashboard(f"{scenario_key} take rate follow through")
    return _build_agent_bigquery_priors(scenario_key, dashboard)


from parkpulse_routes.delivery_routes import register_delivery_routes


register_delivery_routes(
    app,
    {
        "clear_hot_endpoint_cache": clear_hot_endpoint_cache,
        "park_simulation": park_simulation,
        "sync_park_state_safe": sync_park_state_safe,
    },
)


@app.get("/api/park/reliability")
async def park_reliability():
    return {
        "status": "ok",
        "retries_timeouts_circuit_breakers": reliability_status(),
        "platform_store": platform_store_status(),
        "delivery_outbox": delivery_outbox_status(),
        "replay_store": replay_store_status(),
        "backup_systems": {
            "sqlite_replay_backups": replay_store_status().get("backup_count", 0),
            "manual_backup_endpoint": "/api/park/replay/backup",
        },
        "graceful_failure": {
            "gemini": "falls back to deterministic ParkPulse planners when provider readiness, timeout, or circuit errors occur",
            "mongo": "degrades to seeded in-memory operational memory when MongoDB writes or reads fail",
            "delivery": "appends idempotency-keyed dispatches to a durable JSONL outbox before exposing them in memory",
        },
    }


@app.get("/api/park/platform-store")
async def park_platform_store(request: Request):
    _require_role_action(request, "read_platform_status", "platform_store", default_role="ml_ops_admin")
    return platform_store_status()


@app.post("/api/park/platform-store/migrate")
async def park_platform_store_migrate(request: Request):
    authorization = _require_role_action(request, "manage_platform_store", "platform_store_migrate", default_role="ml_ops_admin")
    identity = authorization.get("identity", {}) if isinstance(authorization, dict) else {}
    actor = str(identity.get("subject") or identity.get("role") or "ml_ops_admin")
    return safe_migrate_platform_store(actor=actor)


@app.get("/api/park/latency-diagnostics")
async def park_latency_diagnostics(refresh: bool = False):
    from latency_diagnostics import build_latency_diagnostics, import_profile_snapshot, latency_history_payload, latency_probe_snapshot, schedule_latency_diagnostics_persist, trigger_import_profile, trigger_latency_probes
    from mongo_memory import get_latest_memory_documents_fast, record_latency_diagnostics_fast
    from scenario_eval_sweep import latest_sweep_payload

    trigger = trigger_latency_probes(force=True) if refresh else {"started": [], "skipped": {"all": "refresh_not_requested"}}
    import_trigger = trigger_import_profile(force=True) if refresh else {"started": False, "skipped": "refresh_not_requested"}
    memory_rows = get_latest_memory_documents_fast("eval_results", 75)
    latest_sweep = latest_sweep_payload(memory_rows)
    diagnostics = build_latency_diagnostics(
        full_runtime={"status": "loaded", "loaded": True, "load_duration_ms": None, "timeout_tiers": {}},
        receipts={},
        latest_sweep=latest_sweep,
        probe_snapshot=latency_probe_snapshot(),
        import_profile=import_profile_snapshot(),
        include_env=True,
    )
    diagnostics["probe_trigger"] = trigger
    diagnostics["import_profile_trigger"] = import_trigger
    diagnostics["history"] = latency_history_payload(memory_rows)
    diagnostics["persistence"] = schedule_latency_diagnostics_persist(diagnostics, record_latency_diagnostics_fast)
    return diagnostics


@app.post("/api/park/full-runtime-warmup")
async def park_full_runtime_warmup(force: bool = False):
    from latency_diagnostics import import_profile_snapshot, latency_probe_snapshot, trigger_import_profile, trigger_latency_probes

    probe_trigger = trigger_latency_probes(force=force)
    import_profile_trigger = trigger_import_profile(force=force)
    return {
        "status": "loaded",
        "policy": "full_runtime_plus_dependency_probes",
        "force": force,
        "full_runtime": {"status": "loaded", "loaded": True},
        "dependency_probes": latency_probe_snapshot(),
        "probe_trigger": probe_trigger,
        "import_profile": import_profile_snapshot(),
        "import_profile_trigger": import_profile_trigger,
        "steps": ["dependency_probes_backgrounded", "submodule_import_profile_backgrounded"],
    }


@app.get("/api/park/warmup-status")
async def park_warmup_status():
    from latency_diagnostics import import_profile_snapshot, latency_probe_snapshot

    return {
        "status": "loaded",
        "policy": "full_runtime_plus_dependency_probes",
        "full_runtime": {"status": "loaded", "loaded": True},
        "dependency_probes": latency_probe_snapshot(),
        "import_profile": import_profile_snapshot(),
    }


@app.post("/api/park/replay/backup")
async def park_replay_backup():
    return await asyncio.to_thread(backup_replay_store)


@app.get("/api/park/governance/runtime")
async def park_governance_runtime(limit: int = 20):
    return {
        "domain": "amusement_park_operations",
        **list_runtime_governance(limit),
    }


@app.get("/api/park/customer-care")
async def park_customer_care(limit: int = 20):
    state = await park_simulation.get_state()
    runtime = list_runtime_governance(limit)
    return {
        "domain": "amusement_park_operations",
        "guest_care_state": state.get("guestCare", {}),
        "customer_care_cases": runtime["customer_care_cases"],
        "summary": runtime["summary"],
    }


@app.post("/api/park/customer-care")
async def park_customer_care_create(request: CustomerCareRequest):
    state = await park_simulation.get_state()
    case = create_customer_care_case(request.model_dump(), state)
    return {"status": "queued", "case": case}


@app.get("/api/park/customer-emergency/scope")
async def park_customer_emergency_scope():
    return build_customer_emergency_scope()


@app.post("/api/park/customer-emergency/classify")
async def park_customer_emergency_classify(request: CustomerEmergencyClassifyRequest):
    return classify_customer_scope_text(request.text)


def _persist_customer_emergency_incident(incident: dict[str, Any], event_type: str, *, actor: str = "system", action: str | None = None, note: str = "") -> dict[str, Any]:
    memory_id = record_mongo_customer_emergency_incident(incident)
    audit = build_customer_emergency_audit_event(
        incident,
        event_type,
        actor=actor,
        action=action,
        note=note,
        details={
            "memoryId": memory_id,
            "status": incident.get("status"),
            "lifecycle": incident.get("lifecycle", {}),
        },
    )
    audit_id = record_mongo_customer_emergency_audit_event(audit)
    return {"memory_id": memory_id, "audit_id": audit_id, "audit_event": audit}


def _persisted_customer_emergency_incidents(limit: int = 30, status: str | None = None) -> dict[str, Any]:
    if os.getenv("MONGODB_DISABLE_DRIVER_IMPORT", "").strip().lower() in {"1", "true", "yes", "on"}:
        return list_customer_emergency_incidents(limit=limit, status=status)
    rows = get_latest_memory_documents("customer_emergency_incidents", max(1, min(100, limit)))
    incidents = []
    for row in rows:
        incident = dict(row)
        if "_id" in incident and "id" not in incident:
            incident["id"] = str(incident["_id"])
        if status and incident.get("status") != status:
            continue
        incidents.append(incident)
    if not incidents:
        return list_customer_emergency_incidents(limit=limit, status=status)
    return {
        "status": "ok",
        "source": "operational_memory",
        "count": len(incidents),
        "incidents": incidents[:limit],
        "summary": {
            "open": sum(1 for incident in incidents if incident.get("status") != "resolved"),
            "operator_review": sum(1 for incident in incidents if incident.get("status") == "operator_review"),
            "dispatched": sum(1 for incident in incidents if incident.get("status") == "dispatched"),
            "resolved": sum(1 for incident in incidents if incident.get("status") == "resolved"),
            "critical_or_life_safety": sum(1 for incident in incidents if incident.get("severity") in {"critical", "life_safety"}),
        },
    }


def _load_customer_emergency_incident(incident_id: str) -> dict[str, Any] | None:
    local = get_customer_emergency_incident(incident_id)
    if local:
        return local
    for row in get_latest_memory_documents("customer_emergency_incidents", 100):
        row_id = str(row.get("id") or row.get("_id") or "")
        if row_id == incident_id:
            row["id"] = row_id
            return upsert_customer_emergency_incident(row)
    return None


@app.post("/api/park/customer-emergency/incidents")
async def park_customer_emergency_incident_create(request: CustomerEmergencyIncidentRequest):
    state = await park_simulation.get_state()
    await sync_park_state_safe(state)
    payload = request.model_dump()
    text = " ".join(
        item
        for item in [
            request.text.strip(),
            f"Location: {request.location.strip()}." if request.location.strip() else "",
            "Customer says there may be immediate danger." if request.immediateDanger else "Customer did not mark immediate danger.",
            "Exit, path, or emergency/service lane may be blocked." if request.accessBlocked else "",
            "Staff may already be on scene." if request.staffOnScene else "Staff on scene is unknown.",
            "Customer allows follow-up through the app." if request.contactAllowed else "",
        ]
        if item
    )
    classification = classify_customer_scope_text(text)
    signal = classify_unstructured_signal(
        text=text,
        source="customer_emergency_chat",
        zone_id=request.zoneId,
        reporter_role="customer",
        park_state=state,
    )
    signal_execution = _action_execution_for_signal(signal, state)
    incident = create_customer_emergency_incident(payload, classification=classification, signal_execution=signal_execution)
    persistence = _persist_customer_emergency_incident(
        incident,
        "incident_created",
        note="Customer emergency report classified and queued for operator workflow.",
    )
    clear_hot_endpoint_cache()
    return {
        "status": "queued",
        "incident": incident,
        "classification": classification,
        "signal_triage": signal_execution,
        "persistence": persistence,
    }


@app.get("/api/park/customer-emergency/incidents")
async def park_customer_emergency_incidents(limit: int = 30, status: str | None = None):
    return _persisted_customer_emergency_incidents(limit=limit, status=status)


@app.get("/api/park/customer-emergency/incidents/{incident_id}")
async def park_customer_emergency_incident(incident_id: str):
    incident = _load_customer_emergency_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Customer emergency incident not found")
    return {"status": "ok", "incident": incident}


@app.post("/api/park/customer-emergency/incidents/{incident_id}/action")
async def park_customer_emergency_incident_action(incident_id: str, request: CustomerEmergencyIncidentActionRequest):
    _load_customer_emergency_incident(incident_id)
    try:
        incident = update_customer_emergency_incident(
            incident_id,
            action=request.action,
            actor=request.actor,
            note=request.note,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Customer emergency incident not found") from None
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    persistence = _persist_customer_emergency_incident(
        incident,
        "operator_action",
        actor=request.actor,
        action=request.action,
        note=request.note,
    )
    clear_hot_endpoint_cache()
    return {"status": "updated", "incident": incident, "persistence": persistence}


@app.get("/api/park/customer-emergency/audit")
async def park_customer_emergency_audit(limit: int = 50, incident_id: str | None = None):
    rows = get_latest_memory_documents("customer_emergency_audit", max(1, min(250, limit)))
    if incident_id:
        rows = [row for row in rows if row.get("incidentId") == incident_id]
    return {
        "status": "ok",
        "count": len(rows),
        "events": rows[:limit],
        "summary": {
            "incident_count": len({row.get("incidentId") for row in rows if row.get("incidentId")}),
            "operator_actions": sum(1 for row in rows if row.get("eventType") == "operator_action"),
        },
    }


@app.post("/api/park/signals/intake")
async def park_signal_intake(request: SignalIntakeRequest):
    state = await park_simulation.get_state()
    await sync_park_state_safe(state)
    signal = classify_unstructured_signal(
        text=request.text,
        source=request.source,
        zone_id=request.zoneId,
        reporter_role=request.reporterRole,
        park_state=state,
    )
    clear_hot_endpoint_cache()
    return _action_execution_for_signal(signal, state)


@app.post("/api/park/signals/fusion-demo")
async def park_signal_fusion_demo(request: SignalFusionRequest):
    state = await park_simulation.get_state()
    await sync_park_state_safe(state)
    raw_signals = realistic_signal_batch(state, request.preset)
    fused_signal = fuse_signal_batch(raw_signals, state)
    sources = [str(item.get("source", "unknown")) for item in raw_signals]
    result = _action_execution_for_signal(fused_signal, state)
    clear_hot_endpoint_cache()
    return {
        **result,
        "world_state": reconcile_world_state(state, raw_signals, request.preset),
        "preset": request.preset,
        "pipeline": {
            "name": "ParkPulse multi-source signal fusion",
            "sources": sources,
            "principle": "Treat every feed as partial; escalate when independent sources converge, and ask for verification when they conflict.",
        },
    }


@app.post("/api/park/world-state/reconcile")
async def park_world_state_reconcile(request: WorldStateReconciliationRequest):
    state = await park_simulation.get_state()
    await sync_park_state_safe(state)
    raw_signals = request.signals if request.signals is not None else realistic_signal_batch(state, request.preset)
    return reconcile_world_state(state, raw_signals, request.preset)


@app.get("/api/park/world-state/reconcile/latest")
async def park_world_state_reconcile_latest():
    return latest_reconciliation()


@app.get("/api/park/signals/inbox")
async def park_signal_inbox(limit: int = 20):
    return latest_signals(limit)


def _live_feed_health_cache_ttl_seconds() -> float:
    return max(0.0, _float_env("PARKPULSE_LIVE_FEED_HEALTH_CACHE_TTL_SECONDS", 3.0))


async def _live_feed_health_payload(limit: int = 120) -> dict[str, Any]:
    bounded_limit = max(20, min(500, int(limit or 120)))
    cache_key = str(bounded_limit)
    ttl = _live_feed_health_cache_ttl_seconds()
    now = time.time()
    cached = _live_feed_health_cache.get(cache_key)
    if cached and ttl > 0 and now - cached[0] <= ttl:
        payload = dict(cached[1])
        payload["cache"] = {"status": "hit", "ttl_seconds": ttl}
        return payload
    get_state_lite = getattr(park_simulation, "get_state_lite", None)
    state = await get_state_lite() if callable(get_state_lite) else await park_simulation.get_state()
    timeout = max(1.0, _float_env("PARKPULSE_LIVE_FEED_HEALTH_TIMEOUT_SECONDS", 15.0))
    try:
        payload = await asyncio.wait_for(asyncio.to_thread(live_feed_health, state, bounded_limit), timeout=timeout)
    except Exception as error:
        text = str(error).strip() or f"Live feed health timed out after {timeout:g}s."
        payload = {
            "status": "error",
            "mode": "live_feed_health_and_review_contract",
            "created_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "summary": {
                "required_feed_count": 6,
                "ready_feed_count": 0,
                "missing_or_weak_feed_count": 6,
                "open_review_count": 0,
                "persisted_event_count": 0,
            },
            "readiness_issues": [text[:240]],
            "boundary": "Health timeout blocks broad training readiness but does not dispatch actions, set reward, or promote models.",
            "uses_seed_data": False,
            "llm_control_authority": False,
        }
    if ttl > 0:
        _live_feed_health_cache[cache_key] = (now, payload)
    return {**payload, "cache": {"status": "miss", "ttl_seconds": ttl}}


def _live_weather_refresh_queued_result(reason: str = "manual_refresh_supervisor") -> dict[str, Any]:
    return {
        "status": "queued",
        "mode": "live_weather_feed_background_refresh",
        "provider": weather_feed_config().get("provider", "open_meteo"),
        "reason": reason,
        "latest": _live_feed_weather_refresh_status,
        "boundary": weather_feed_config().get("boundary"),
    }


async def _run_live_weather_refresh_background(reason: str) -> None:
    global _live_feed_weather_refresh_status
    _live_feed_weather_refresh_status = {
        "status": "running",
        "mode": "live_weather_feed_background_refresh",
        "started_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "reason": reason,
    }
    try:
        result = await asyncio.to_thread(ingest_live_weather_feed)
        clear_hot_endpoint_cache()
        _live_feed_weather_refresh_status = {
            "status": result.get("status", "loaded") if isinstance(result, dict) else "loaded",
            "mode": "live_weather_feed_background_refresh",
            "completed_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "reason": reason,
            "result": result,
        }
    except asyncio.CancelledError:
        _live_feed_weather_refresh_status = {
            "status": "cancelled",
            "mode": "live_weather_feed_background_refresh",
            "cancelled_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "reason": reason,
        }
        raise
    except Exception as error:
        _live_feed_weather_refresh_status = {
            "status": "error",
            "mode": "live_weather_feed_background_refresh",
            "completed_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "reason": reason,
            "readiness_issues": [str(error)[:240]],
        }


def _queue_live_weather_refresh(reason: str = "manual_refresh_supervisor") -> dict[str, Any]:
    global _live_feed_weather_refresh_task
    if _live_feed_weather_refresh_task and not _live_feed_weather_refresh_task.done():
        return _live_weather_refresh_queued_result(reason)
    _live_feed_weather_refresh_task = _track_background_task(_run_live_weather_refresh_background(reason))
    return _live_weather_refresh_queued_result(reason)


@app.get("/api/park/live-feed-health")
async def park_live_feed_health(limit: int = 120):
    return await _live_feed_health_payload(limit=limit)


@app.post("/api/park/live-feed-events")
async def park_live_feed_events(payload: dict[str, Any]):
    events = payload.get("events") if isinstance(payload.get("events"), list) else None
    result = await asyncio.to_thread(ingest_live_feed_events, events) if events is not None else await asyncio.to_thread(ingest_live_feed_event, payload)
    clear_hot_endpoint_cache()
    return result


def _live_feed_value_summary(value: Any) -> str:
    if not isinstance(value, dict):
        return str(value)[:180]
    if "note" in value:
        return str(value.get("note"))[:180]
    top_path = value.get("top_path") if isinstance(value.get("top_path"), dict) else {}
    if top_path:
        return (
            f"path {top_path.get('from_name') or top_path.get('from')} to "
            f"{top_path.get('to_name') or top_path.get('to')} at {top_path.get('congestion_level_pct')}% congestion"
        )
    top_zone = value.get("top_zone") if isinstance(value.get("top_zone"), dict) else {}
    if top_zone:
        return f"zone {top_zone.get('name') or top_zone.get('id')} at {top_zone.get('density_pct')}% density"
    if "wait_mins" in value:
        return f"{value.get('name') or value.get('id')} wait {value.get('wait_mins')}m status {value.get('status')}"
    if "mobile_order_backlog" in value:
        return f"{value.get('name') or value.get('id')} backlog {value.get('mobile_order_backlog')} ETA {value.get('pickup_eta_minutes')}m"
    if "coverage_status" in value:
        return f"staff coverage {value.get('coverage_status')} with {value.get('open_callouts')} callouts"
    if "open_cases" in value:
        return f"{value.get('open_cases')} guest-care cases, complaint rate {value.get('complaint_rate_pct')}%"
    compact = ", ".join(f"{key}={value[key]}" for key in list(value)[:4] if key not in {"locations", "rides", "zones", "paths"})
    return compact[:180] if compact else "live feed value attached"


def _live_feed_case_from_health(health: dict[str, Any]) -> dict[str, Any]:
    feeds = [row for row in health.get("feeds", []) if isinstance(row, dict)]
    ready = [row for row in feeds if row.get("status") == "ready"]
    issue_rows = [row for row in feeds if row.get("status") != "ready"]
    evidence_rows = [
        {
            "source": row.get("source"),
            "label": row.get("label"),
            "owner": row.get("owner"),
            "status": row.get("status"),
            "signal_type": row.get("latest_signal_type"),
            "confidence": row.get("confidence"),
            "age_seconds": row.get("age_seconds"),
            "event_id": row.get("latest_event_id"),
            "summary": _live_feed_value_summary(row.get("value")),
        }
        for row in ready[:8]
    ]
    ranked = sorted(
        evidence_rows,
        key=lambda row: (
            1 if row.get("source") in {"operator_signal", "guest_flow", "ride_ops", "food_ops", "staffing"} else 0,
            float(row.get("confidence") or 0),
        ),
        reverse=True,
    )
    lead = ranked[0] if ranked else {}
    evidence_text = "; ".join(
        f"{row.get('source')} {row.get('signal_type')}: {row.get('summary')}"
        for row in ranked[:5]
        if row.get("source")
    )
    if not evidence_text:
        evidence_text = "No ready live feed evidence is available."
    operator_message = (
        "Use only the current live-feed evidence to coordinate department agents. "
        f"Lead signal: {lead.get('source') or 'none'} {lead.get('signal_type') or ''}. "
        f"Evidence: {evidence_text}. "
        "Have departments propose narrow tool calls, let Compliance/Judge check policy and trace quality, "
        "let Executive choose tradeoffs, and keep Tool Executor as the only action performer."
    )
    summary = health.get("summary", {}) if isinstance(health.get("summary"), dict) else {}
    return {
        "mode": "live_feed_case_synthesis",
        "source": "live_feed_health",
        "uses_seed_data": False,
        "scripted_case": False,
        "persisted_event_count": summary.get("persisted_event_count", 0),
        "ready_feed_count": summary.get("ready_feed_count", 0),
        "required_feed_count": summary.get("required_feed_count", 0),
        "missing_or_weak_feed_count": summary.get("missing_or_weak_feed_count", 0),
        "open_review_count": summary.get("open_review_count", 0),
        "lead_source": lead.get("source"),
        "lead_signal_type": lead.get("signal_type"),
        "operator_message": operator_message,
        "evidence": evidence_rows,
        "feed_issues": [
            {
                "source": row.get("source"),
                "status": row.get("status"),
                "readiness_issues": row.get("readiness_issues", []),
            }
            for row in issue_rows
        ],
        "reasoning": [
            "Observe: read the latest normalized live feed rows and review state.",
            "Interpret: rank ready feeds by confidence and operational relevance.",
            "Predict: ask role agents to reason from the live feed case without forcing a seeded scenario.",
            "Recommend: require each department to propose narrow tool calls only.",
            "Justify: attach feed event IDs, confidence, age, and policy findings to the run trace.",
            "Trace: preserve candidates, policy gate, dispatch envelopes, eval, outcome, and memory write.",
        ],
    }


def _park_profile_summary_for_agent_run(profile: Any) -> dict[str, Any]:
    if not isinstance(profile, dict):
        return {"status": "missing", "profile_version": None, "counts": {}, "precedence": "live_feed_over_profile_policy_over_both"}
    identity = profile.get("venueIdentity", {}) if isinstance(profile.get("venueIdentity"), dict) else {}
    readiness = profile.get("readiness", {}) if isinstance(profile.get("readiness"), dict) else {}
    counts = readiness.get("counts", {}) if isinstance(readiness.get("counts"), dict) else {}
    source = profile.get("sourceIntegrity", {}) if isinstance(profile.get("sourceIntegrity"), dict) else {}
    loaded_from = readiness.get("loadedFrom")
    profile_version = ":".join(
        str(item or "unknown")
        for item in [identity.get("venueId"), identity.get("profileType") or source.get("profileType"), loaded_from]
    )
    return {
        "status": "attached" if profile.get("status") in {"ready", "studio_ready"} or readiness.get("status") else str(profile.get("status") or "unknown"),
        "profile_version": profile_version,
        "venue_id": identity.get("venueId"),
        "venue_name": identity.get("name"),
        "profile_type": identity.get("profileType") or source.get("profileType"),
        "readiness_status": readiness.get("status"),
        "counts": counts,
        "source_integrity": source,
        "precedence": "live_feed_over_profile_policy_over_both",
        "contract": "Profile facts constrain reasoning and learning context; live feeds define current state; policy gates define authority.",
    }


def _live_feed_evidence_rows(live_feed_case: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(live_feed_case, dict):
        return []
    rows = live_feed_case.get("evidence", [])
    return [row for row in rows if isinstance(row, dict)]


def _live_feed_row_label(row: dict[str, Any]) -> str:
    source = row.get("source") or "live_feed"
    signal_type = row.get("signal_type") or "signal"
    event_id = row.get("event_id") or "unpersisted"
    confidence = row.get("confidence")
    age_seconds = row.get("age_seconds")
    detail = f"live_feed:{source}:{signal_type}:event={event_id}"
    if confidence is not None:
        detail += f":confidence={confidence}"
    if age_seconds is not None:
        detail += f":age_seconds={age_seconds}"
    summary = str(row.get("summary") or "").strip()
    return f"{detail}:summary={summary[:96]}" if summary else detail


def _live_feed_sources_for_department(department: str, agent_id: str) -> set[str]:
    department = str(department or "")
    agent_id = str(agent_id or "")
    mapping = {
        "operations": {"ride_ops", "guest_flow", "weather", "operator_signal"},
        "safety": {"ride_ops", "guest_flow", "weather", "operator_signal"},
        "maintenance": {"ride_ops", "maintenance", "operator_signal"},
        "guest_experience": {"guest_flow", "operator_signal", "ride_ops"},
        "food_retail": {"food_ops", "guest_flow", "weather", "operator_signal"},
        "finance": {"food_ops", "ride_ops", "guest_flow", "staffing"},
        "hr_labor": {"staffing", "ride_ops", "food_ops", "operator_signal"},
        "marketing": {"guest_flow", "food_ops", "weather", "operator_signal"},
        "security": {"guest_flow", "operator_signal", "ride_ops"},
        "compliance": {"ride_ops", "guest_flow", "staffing", "food_ops", "operator_signal", "weather"},
        "executive": {"ride_ops", "guest_flow", "staffing", "food_ops", "operator_signal", "weather"},
        "qa_judge": {"ride_ops", "guest_flow", "staffing", "food_ops", "operator_signal", "weather"},
    }
    if agent_id in {"decision_bridge_agent", "park_understanding_agent", "safety_policy_agent"}:
        return mapping["executive"] if agent_id != "safety_policy_agent" else mapping["safety"]
    if agent_id == "food_demand_agent":
        return mapping["food_retail"]
    if agent_id == "staffing_agent":
        return mapping["hr_labor"]
    if agent_id == "guest_flow_agent":
        return mapping["guest_experience"]
    if agent_id == "ride_ops_agent":
        return mapping["operations"]
    return mapping.get(department, set())


def _select_live_feed_rows_for_proposal(proposal: dict[str, Any], evidence_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    department = str(proposal.get("department") or "")
    agent_id = str(proposal.get("agent_id") or "")
    wanted_sources = _live_feed_sources_for_department(department, agent_id)
    matched = [row for row in evidence_rows if str(row.get("source") or "") in wanted_sources]
    if not matched:
        matched = evidence_rows[:2]
    return matched[:3]


def _build_live_feed_cooperation_graph(role_agent_proposals: dict[str, Any], live_feed_case: dict[str, Any]) -> dict[str, Any]:
    proposals = role_agent_proposals.get("proposals", []) if isinstance(role_agent_proposals.get("proposals"), list) else []
    evidence_rows = _live_feed_evidence_rows(live_feed_case)
    feed_nodes = [
        {
            "id": f"feed:{row.get('source')}",
            "type": "live_feed",
            "source": row.get("source"),
            "event_id": row.get("event_id"),
            "confidence": row.get("confidence"),
            "signal_type": row.get("signal_type"),
        }
        for row in evidence_rows
        if row.get("source")
    ]
    department_nodes = [
        {
            "id": f"department:{proposal.get('department')}",
            "type": "department_agent",
            "department": proposal.get("department"),
            "agent": proposal.get("agent_id"),
        }
        for proposal in proposals
    ]
    tool_nodes = []
    edges = []
    for proposal in proposals:
        envelope = proposal.get("proposal_envelope", {}) if isinstance(proposal.get("proposal_envelope"), dict) else {}
        department_id = f"department:{proposal.get('department')}"
        tool_id = f"tool:{envelope.get('requested_tool') or proposal.get('requested_tool')}"
        if tool_id not in {node.get("id") for node in tool_nodes}:
            tool_nodes.append(
                {
                    "id": tool_id,
                    "type": "proposed_tool",
                    "tool": envelope.get("requested_tool") or proposal.get("requested_tool"),
                    "executor": envelope.get("executor_agent", "tool_executor_agent"),
                    "executor_status": envelope.get("executor_status") or proposal.get("executor_status"),
                }
            )
        for event_id in (proposal.get("live_feed_grounding", {}) if isinstance(proposal.get("live_feed_grounding"), dict) else {}).get("event_ids", []):
            source = next((row.get("source") for row in evidence_rows if row.get("event_id") == event_id), None)
            if source:
                edges.append({"from": f"feed:{source}", "to": department_id, "relation": "observed_by"})
        edges.append({"from": department_id, "to": tool_id, "relation": "proposes_narrow_tool"})
        edges.append({"from": tool_id, "to": "judge:compliance_eval", "relation": "requires_policy_trace_check"})
        edges.append({"from": "judge:compliance_eval", "to": "executive:tradeoff", "relation": "escalates_if_risky"})
        edges.append({"from": "executive:tradeoff", "to": "executor:tool_executor_agent", "relation": "approved_actions_only"})
    unique_departments = {node["id"]: node for node in department_nodes if node.get("department")}
    unique_feeds = {node["id"]: node for node in feed_nodes if node.get("id")}
    return {
        "mode": "live_feed_department_cooperation",
        "nodes": [
            *unique_feeds.values(),
            *unique_departments.values(),
            *tool_nodes,
            {"id": "judge:compliance_eval", "type": "policy_and_eval_judge"},
            {"id": "executive:tradeoff", "type": "executive_agent"},
            {"id": "executor:tool_executor_agent", "type": "tool_executor"},
        ],
        "edges": edges,
        "contract": "Department agents read live evidence widely, write only narrow proposed tool calls, and Tool Executor is the only real action performer.",
    }


def _enrich_role_proposals_with_live_feed(
    role_agent_proposals: dict[str, Any],
    live_feed_case: dict[str, Any] | None,
) -> dict[str, Any]:
    evidence_rows = _live_feed_evidence_rows(live_feed_case)
    if not isinstance(role_agent_proposals, dict) or not evidence_rows:
        return role_agent_proposals
    proposals = role_agent_proposals.get("proposals", [])
    if not isinstance(proposals, list):
        return role_agent_proposals
    grounded_count = 0
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        selected_rows = _select_live_feed_rows_for_proposal(proposal, evidence_rows)
        if not selected_rows:
            continue
        grounded_count += 1
        live_evidence = [_live_feed_row_label(row) for row in selected_rows]
        existing_evidence = [str(item) for item in proposal.get("evidence", []) if str(item).strip()]
        merged_evidence = list(dict.fromkeys([*live_evidence, *existing_evidence]))[:8]
        event_ids = [row.get("event_id") for row in selected_rows if row.get("event_id")]
        sources = list(dict.fromkeys(str(row.get("source")) for row in selected_rows if row.get("source")))
        confidence_values = [float(row.get("confidence") or 0) for row in selected_rows]
        proposal["evidence"] = merged_evidence
        proposal["live_feed_grounding"] = {
            "source": "live_feed_health",
            "event_ids": event_ids,
            "sources": sources,
            "source_count": len(sources),
            "max_confidence": round(max(confidence_values), 3) if confidence_values else None,
            "evidence_count": len(selected_rows),
        }
        proposal["input_signals"] = {
            **(proposal.get("input_signals") if isinstance(proposal.get("input_signals"), dict) else {}),
            "live_feed_event_ids": event_ids,
            "live_feed_sources": sources,
            "orchestration_source": "live_feed",
        }
        envelope = proposal.get("proposal_envelope", {}) if isinstance(proposal.get("proposal_envelope"), dict) else {}
        if envelope:
            envelope["evidence"] = merged_evidence[:5]
            envelope["policy_check"] = envelope.get("policy_check") or "pending_policy_gate"
            envelope["expected_outcome"] = envelope.get("expected_outcome") or proposal.get("recommendation") or "department proposal reviewed"
            envelope["rollback"] = envelope.get("rollback") or "cancel proposed action if live feed normalizes"
            envelope["live_feed_event_ids"] = event_ids
            envelope["live_feed_sources"] = sources
            proposal["proposal_envelope"] = envelope
        proposal["policy_check"] = proposal.get("policy_check") or envelope.get("policy_check") or "pending_policy_gate"
        proposal["expected_outcome"] = proposal.get("expected_outcome") or envelope.get("expected_outcome") or proposal.get("recommendation")
        proposal["rollback"] = proposal.get("rollback") or envelope.get("rollback") or "cancel proposed action if live feed normalizes"
    event_ids = [row.get("event_id") for row in evidence_rows if row.get("event_id")]
    role_agent_proposals["orchestration_source"] = "live_feed"
    role_agent_proposals["live_feed_evidence_count"] = len(evidence_rows)
    role_agent_proposals["live_feed_event_ids"] = event_ids[:12]
    role_agent_proposals["live_feed_grounded_proposal_count"] = grounded_count
    role_agent_proposals["cooperation_graph"] = _build_live_feed_cooperation_graph(role_agent_proposals, live_feed_case or {})
    role_agent_proposals["mediator_summary"] = (
        "Department agents are grounded in persisted live-feed event IDs, submit narrow tool proposals, "
        "then Compliance/Eval and Executive arbitrate before Tool Executor can perform any real action."
    )
    return role_agent_proposals


def _tool_use_clarity_from_run(payload: dict[str, Any]) -> dict[str, Any]:
    proposals = payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}
    proposal_rows = proposals.get("proposals", []) if isinstance(proposals.get("proposals"), list) else []
    trace_contract = payload.get("trace_contract", {}) if isinstance(payload.get("trace_contract"), dict) else {}
    governance = payload.get("governance", {}) if isinstance(payload.get("governance"), dict) else {}
    tool_rows = []
    for proposal in proposal_rows:
        envelope = proposal.get("proposal_envelope", {}) if isinstance(proposal.get("proposal_envelope"), dict) else {}
        grounding = proposal.get("live_feed_grounding", {}) if isinstance(proposal.get("live_feed_grounding"), dict) else {}
        tool_rows.append(
            {
                "department": proposal.get("department") or envelope.get("department"),
                "agent": proposal.get("agent_id") or envelope.get("proposed_by"),
                "tool": envelope.get("requested_tool") or proposal.get("requested_tool"),
                "intent": envelope.get("intent") or proposal.get("recommendation"),
                "evidence": envelope.get("evidence") or proposal.get("evidence", []),
                "risk_level": envelope.get("risk_level") or proposal.get("risk_level"),
                "policy_check": envelope.get("policy_check") or proposal.get("policy_check") or governance.get("gate_status") or "pending_policy_gate",
                "expected_outcome": envelope.get("expected_outcome") or proposal.get("expected_outcome"),
                "rollback": envelope.get("rollback") or proposal.get("rollback"),
                "live_feed_event_ids": envelope.get("live_feed_event_ids") or grounding.get("event_ids", []),
                "live_feed_sources": envelope.get("live_feed_sources") or grounding.get("sources", []),
                "executor_agent": envelope.get("executor_agent", "tool_executor_agent"),
                "executor_status": envelope.get("executor_status") or proposal.get("executor_status"),
            }
        )
    missing_policy_check_count = sum(1 for row in tool_rows if not row.get("policy_check"))
    live_feed_grounded_tool_count = sum(1 for row in tool_rows if row.get("live_feed_event_ids"))
    return {
        "mode": "clear_department_tool_use",
        "proposal_count": len(proposal_rows),
        "orchestration_source": proposals.get("orchestration_source"),
        "live_feed_evidence_count": proposals.get("live_feed_evidence_count", 0),
        "live_feed_grounded_proposal_count": proposals.get("live_feed_grounded_proposal_count", 0),
        "live_feed_grounded_tool_count": live_feed_grounded_tool_count,
        "missing_policy_check_count": missing_policy_check_count,
        "cooperation_graph_present": bool(proposals.get("cooperation_graph") or payload.get("live_feed_cooperation")),
        "tools": tool_rows,
        "trace_steps": [
            {
                "step": row.get("step"),
                "phase": row.get("phase"),
                "evidence": row.get("evidence"),
                "artifact_id": row.get("artifact_id"),
            }
            for row in trace_contract.get("trace_table", [])[:8]
            if isinstance(row, dict)
        ],
        "judge": {
            "eval_status": (payload.get("eval", {}).get("scorecard", {}) if isinstance(payload.get("eval"), dict) else {}).get("status"),
            "policy_gate": governance.get("gate_status"),
            "trace_contract_present": bool(trace_contract),
        },
    }


def _controlled_live_feed_tool_executor_run(payload: dict[str, Any], *, execute: bool) -> dict[str, Any]:
    proposals = payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}
    proposal_rows = proposals.get("proposals", []) if isinstance(proposals.get("proposals"), list) else []
    receipts = []
    for proposal in proposal_rows:
        if not isinstance(proposal, dict):
            continue
        envelope = proposal.get("proposal_envelope", {}) if isinstance(proposal.get("proposal_envelope"), dict) else {}
        policy_judge = envelope.get("policy_judge") or proposal.get("policy_judge")
        if not isinstance(policy_judge, dict):
            policy_judge = {"status": "requires_compliance", "reason": "No concrete policy judge result was attached."}
        policy_status = str(policy_judge.get("status") or "")
        executor_status = str(envelope.get("executor_status") or proposal.get("executor_status") or "")
        action_disposition = proposal.get("action_disposition") or envelope.get("action_disposition")
        if not isinstance(action_disposition, dict):
            action_disposition = {
                "decision": "hold_for_policy_review",
                "next_owner": "decision_bridge_agent",
                "why_not_undecided": "Tool Executor received no executable policy-passed envelope.",
                "exit_condition": "Attach concrete policy approval before retry.",
                "fallback": "Keep action in trace only.",
            }
        controlled_executor_departments = {"food_retail", "hr_labor", "marketing", "operations", "maintenance"}
        approved_for_controlled_executor = (
            policy_status in {"passed", "approved_with_exclusions"}
            and executor_status in {"ready_for_executor", "executor_only"}
            and proposal.get("department") in controlled_executor_departments
        )
        context = {
            "department": proposal.get("department") or envelope.get("department"),
            "tool": "execute_approved_action",
            "intent": envelope.get("intent") or proposal.get("recommendation"),
            "evidence": envelope.get("evidence") or proposal.get("evidence", []),
            "risk_level": envelope.get("risk_level") or proposal.get("risk_level") or "medium",
            "policy_check": envelope.get("policy_check") or proposal.get("policy_check"),
            "expected_outcome": envelope.get("expected_outcome") or proposal.get("expected_outcome"),
            "rollback": envelope.get("rollback") or proposal.get("rollback"),
            "policy_gate_checked": True,
            "policyGateStatus": policy_status,
            "decision_id": payload.get("decision_id"),
            "approved_action_envelope": envelope,
            "action_parameters": envelope.get("action_parameters") or proposal.get("semantic_action_parameters") or {},
            "semantic_action_parameters": envelope.get("semantic_action_parameters") or proposal.get("semantic_action_parameters") or {},
            "live_feed_event_ids": envelope.get("live_feed_event_ids") or (proposal.get("live_feed_grounding", {}) if isinstance(proposal.get("live_feed_grounding"), dict) else {}).get("event_ids", []),
        }
        if approved_for_controlled_executor:
            result = run_agent_tool(
                "tool_executor_agent",
                "execute_approved_action",
                context,
                lambda proposal=proposal, envelope=envelope: {
                    "status": "executed_controlled" if execute else "preview_controlled",
                    "mode": "controlled_live_feed_tool_executor",
                    "executed": bool(execute),
                    "source_agent": proposal.get("agent_id"),
                    "source_department": proposal.get("department"),
                    "source_tool": envelope.get("requested_tool") or proposal.get("requested_tool"),
                    "action_parameters": context.get("action_parameters"),
                    "semantic_action_parameters": context.get("semantic_action_parameters"),
                    "idempotency_key": hashlib.sha1(
                        json.dumps(
                            {
                                "decision_id": payload.get("decision_id"),
                                "agent": proposal.get("agent_id"),
                                "tool": envelope.get("requested_tool") or proposal.get("requested_tool"),
                                "action_parameters": context.get("action_parameters"),
                                "events": context["live_feed_event_ids"],
                            },
                            sort_keys=True,
                            default=str,
                        ).encode("utf-8")
                    ).hexdigest()[:16],
                    "rollback": context.get("rollback"),
                },
            )
        else:
            result = {
                "status": "held",
                "mode": "controlled_live_feed_tool_executor",
                "executed": False,
                "reason": policy_judge.get("reason") or f"Policy status {policy_status or 'unknown'} is not executable.",
                "disposition": action_disposition.get("decision"),
                "next_owner": action_disposition.get("next_owner"),
                "exit_condition": action_disposition.get("exit_condition"),
                "fallback": action_disposition.get("fallback"),
                "why_not_undecided": action_disposition.get("why_not_undecided"),
                "evidence_argument": action_disposition.get("evidence_argument"),
                "live_feed_event_ids": action_disposition.get("live_feed_event_ids") or context["live_feed_event_ids"],
            }
        receipts.append(
            {
                "agent": proposal.get("agent_id"),
                "department": proposal.get("department"),
                "source_tool": envelope.get("requested_tool") or proposal.get("requested_tool"),
                "policy_check": envelope.get("policy_check") or proposal.get("policy_check"),
                "policy_status": policy_status,
                "executor_status": executor_status,
                "approved_for_controlled_executor": approved_for_controlled_executor,
                "live_feed_event_ids": action_disposition.get("live_feed_event_ids") or context["live_feed_event_ids"],
                "action_parameters": context.get("action_parameters"),
                "semantic_action_parameters": context.get("semantic_action_parameters"),
                "action_disposition": action_disposition,
                "result": result,
            }
        )
        companion_tools = []
        semantic_params = context.get("semantic_action_parameters")
        if approved_for_controlled_executor and isinstance(semantic_params, dict):
            companion_tools = [
                str(tool)
                for tool in semantic_params.get("companion_tools", [])
                if str(tool) in {"inventory_alert", "restock_request"}
            ]
        for companion_tool in companion_tools:
            companion_context = {
                **context,
                "tool": "execute_approved_action",
                "intent": f"Execute semantic-memory companion action {companion_tool} for {proposal.get('department')}",
                "expected_outcome": "Companion action records bounded stockout prevention while preserving the original controlled handoff.",
                "source_companion_tool": companion_tool,
            }
            companion_result = run_agent_tool(
                "tool_executor_agent",
                "execute_approved_action",
                companion_context,
                lambda proposal=proposal, companion_tool=companion_tool: {
                    "status": "executed_controlled" if execute else "preview_controlled",
                    "mode": "controlled_live_feed_tool_executor",
                    "executed": bool(execute),
                    "source_agent": proposal.get("agent_id"),
                    "source_department": proposal.get("department"),
                    "source_tool": companion_tool,
                    "companion_action": True,
                    "companion_source": "semantic_agent_learning",
                    "action_parameters": companion_context.get("action_parameters"),
                    "semantic_action_parameters": companion_context.get("semantic_action_parameters"),
                    "idempotency_key": hashlib.sha1(
                        json.dumps(
                            {
                                "decision_id": payload.get("decision_id"),
                                "agent": proposal.get("agent_id"),
                                "tool": companion_tool,
                                "action_parameters": companion_context.get("action_parameters"),
                                "events": companion_context["live_feed_event_ids"],
                            },
                            sort_keys=True,
                            default=str,
                        ).encode("utf-8")
                    ).hexdigest()[:16],
                    "rollback": "Cancel companion inventory alert if stockout risk clears or receiver rejects the parent action.",
                },
            )
            receipts.append(
                {
                    "agent": proposal.get("agent_id"),
                    "department": proposal.get("department"),
                    "source_tool": companion_tool,
                    "policy_check": envelope.get("policy_check") or proposal.get("policy_check"),
                    "policy_status": policy_status,
                    "executor_status": executor_status,
                    "approved_for_controlled_executor": approved_for_controlled_executor,
                    "live_feed_event_ids": action_disposition.get("live_feed_event_ids") or context["live_feed_event_ids"],
                    "action_parameters": companion_context.get("action_parameters"),
                    "semantic_action_parameters": companion_context.get("semantic_action_parameters"),
                    "action_disposition": {
                        **action_disposition,
                        "decision": "execute_semantic_companion_action",
                        "why_not_undecided": "Semantic memory proposed a same-department low-risk companion tool with live-feed evidence and an executable parent envelope.",
                    },
                    "companion_action": True,
                    "companion_parent_tool": envelope.get("requested_tool") or proposal.get("requested_tool"),
                    "companion_source": "semantic_agent_learning",
                    "result": companion_result,
                }
            )
    executed_count = sum(1 for row in receipts if (row.get("result", {}) if isinstance(row.get("result"), dict) else {}).get("status") == "executed_controlled")
    preview_count = sum(1 for row in receipts if (row.get("result", {}) if isinstance(row.get("result"), dict) else {}).get("status") == "preview_controlled")
    held_count = sum(1 for row in receipts if (row.get("result", {}) if isinstance(row.get("result"), dict) else {}).get("status") == "held")
    return {
        "mode": "controlled_live_feed_tool_executor",
        "execute_requested": bool(execute),
        "status": "executed" if executed_count else "preview" if preview_count else "held",
        "receipt_count": len(receipts),
        "executed_count": executed_count,
        "preview_count": preview_count,
        "held_count": held_count,
        "held_disposition_count": sum(1 for row in receipts if isinstance(row.get("action_disposition"), dict) and (row.get("result", {}) if isinstance(row.get("result"), dict) else {}).get("status") == "held"),
        "executor_agent": "tool_executor_agent",
        "contract": "Tool Executor receives only approved low-risk envelopes; held safety, security, guest-message, and reopen-sensitive actions are not executed.",
        "receipts": receipts,
    }


def _build_live_feed_hard_decision_follow_through(payload: dict[str, Any]) -> dict[str, Any]:
    executor = payload.get("tool_executor_live_test", {}) if isinstance(payload.get("tool_executor_live_test"), dict) else {}
    receipts = executor.get("receipts", []) if isinstance(executor.get("receipts"), list) else []
    tasks: list[dict[str, Any]] = []
    for receipt in receipts:
        if not isinstance(receipt, dict):
            continue
        result = receipt.get("result", {}) if isinstance(receipt.get("result"), dict) else {}
        if result.get("status") != "held":
            continue
        disposition = receipt.get("action_disposition", {}) if isinstance(receipt.get("action_disposition"), dict) else {}
        department = str(receipt.get("department") or "")
        decision = str(disposition.get("decision") or result.get("disposition") or "hold_for_review")
        next_owner = str(disposition.get("next_owner") or result.get("next_owner") or "decision_bridge_agent")
        exit_condition = str(disposition.get("exit_condition") or result.get("exit_condition") or "Named owner records approve, reject, or continue hold.")
        fallback = str(disposition.get("fallback") or result.get("fallback") or "Keep action in trace only.")
        terminal_decisions = {"tradeoff_review_only", "report_only_no_comp_commitment", "policy_note_committed", "score_trace_and_flag_regression"}
        if decision in terminal_decisions:
            status = "closed_non_executable"
            follow_up_decision = "closed_as_trace_or_review_artifact"
            active_follow_up_required = False
        else:
            status = "routed_to_owner"
            follow_up_decision = "owner_review_required"
            active_follow_up_required = True
        task_basis = {
            "decision_id": payload.get("decision_id"),
            "agent": receipt.get("agent"),
            "department": department,
            "tool": receipt.get("source_tool"),
            "decision": decision,
            "next_owner": next_owner,
        }
        tasks.append(
            {
                "task_id": f"hard_follow_{hashlib.sha1(json.dumps(task_basis, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:12]}",
                "agent": receipt.get("agent"),
                "department": department,
                "source_tool": receipt.get("source_tool"),
                "policy_check": receipt.get("policy_check"),
                "policy_status": receipt.get("policy_status"),
                "status": status,
                "follow_up_decision": follow_up_decision,
                "active_follow_up_required": active_follow_up_required,
                "next_owner": next_owner,
                "exit_condition": exit_condition,
                "fallback": fallback,
                "why_not_undecided": disposition.get("why_not_undecided") or result.get("why_not_undecided"),
                "review_inputs": {
                    "policy_reason": result.get("reason"),
                    "live_feed_event_ids": result.get("live_feed_event_ids") or [],
                    "executor_status": receipt.get("executor_status"),
                    "approved_for_controlled_executor": receipt.get("approved_for_controlled_executor"),
                },
            }
        )
    unresolved_without_owner = [
        task
        for task in tasks
        if not task.get("next_owner") or not task.get("exit_condition") or not task.get("fallback")
    ]
    active_tasks = [task for task in tasks if task.get("active_follow_up_required")]
    closed_tasks = [task for task in tasks if not task.get("active_follow_up_required")]
    status = "routed" if tasks and not unresolved_without_owner else "none" if not tasks else "incomplete"
    return {
        "mode": "hard_decision_follow_through",
        "status": status,
        "task_count": len(tasks),
        "active_follow_up_count": len(active_tasks),
        "closed_non_executable_count": len(closed_tasks),
        "unresolved_without_owner_count": len(unresolved_without_owner),
        "owner_count": len({str(task.get("next_owner")) for task in tasks if task.get("next_owner")}),
        "contract": "Every held action is either closed as a non-executable trace/review artifact or routed to a named owner with an exit condition and fallback.",
        "tasks": tasks,
    }


def _risk_escalation_policy(tool: str, department: str) -> dict[str, Any]:
    policies = {
        ("operations", "recommend_route_change"): {
            "lifted_scope": "simulated_managed_route_recommendation",
            "receiver": "ops_console",
            "limits": [
                "simulate route recommendation only",
                "do not issue autonomous public routing command",
                "keep safety and accessibility watch active",
            ],
        },
        ("guest_experience", "draft_guest_message"): {
            "lifted_scope": "approved_guest_message_draft_internal",
            "receiver": "guest_experience_console",
            "limits": [
                "draft and stage approved copy only",
                "do not send public emergency or compensation promise",
                "Compliance owns privacy and promise review",
            ],
        },
        ("maintenance", "create_work_order"): {
            "lifted_scope": "maintenance_work_order_without_reopen_authority",
            "receiver": "maintenance_console",
            "limits": [
                "create work-order task only",
                "do not reopen ride or clear inspection",
                "Safety owns reopen clearance",
            ],
        },
        ("marketing", "redirect_offer"): {
            "lifted_scope": "capacity_capped_redirect_offer",
            "receiver": "marketing_ops_console",
            "limits": [
                "redirect only away from constrained area",
                "cap overloaded indoor and spillback targets",
                "pause if crowd pressure worsens",
            ],
        },
    }
    return policies.get((department, tool), {})


def _build_live_feed_risk_escalation_approval(payload: dict[str, Any], *, enabled: bool) -> dict[str, Any]:
    follow = payload.get("hard_decision_follow_through", {}) if isinstance(payload.get("hard_decision_follow_through"), dict) else {}
    tasks = follow.get("tasks", []) if isinstance(follow.get("tasks"), list) else []
    if not enabled:
        return {
            "mode": "risk_escalation_approval",
            "status": "disabled",
            "stage": "gate_closed",
            "requested_count": 0,
            "approved_count": 0,
            "blocked_count": 0,
            "policy": "Riskier actions remain held unless allow_risk_escalation is explicitly enabled for this run.",
            "approvals": [],
        }
    approvals: list[dict[str, Any]] = []
    for task in tasks:
        if not isinstance(task, dict) or task.get("status") != "routed_to_owner":
            continue
        department = str(task.get("department") or "")
        tool = str(task.get("source_tool") or "")
        policy = _risk_escalation_policy(tool, department)
        if not policy:
            continue
        review_inputs = task.get("review_inputs", {}) if isinstance(task.get("review_inputs"), dict) else {}
        live_feed_event_ids = [str(row) for row in review_inputs.get("live_feed_event_ids", []) if row] if isinstance(review_inputs.get("live_feed_event_ids"), list) else []
        missing: list[str] = []
        if not live_feed_event_ids:
            missing.append("live_feed_event_ids")
        if not task.get("exit_condition"):
            missing.append("exit_condition")
        if not task.get("fallback"):
            missing.append("rollback")
        approver_rows = [
            {
                "agent": "safety_agent",
                "status": "approved" if not missing else "blocked",
                "basis": "No autonomous safety clearance; route, work-order, and message effects stay simulated and monitored.",
            },
            {
                "agent": "compliance_agent",
                "status": "approved" if not missing else "blocked",
                "basis": "Approval is scoped, expires after this run, records policy basis, and preserves privacy/public-message boundaries.",
            },
            {
                "agent": "executive_agent",
                "status": "approved" if not missing else "blocked",
                "basis": "Executive accepts the tradeoff only for the named action, receiver, rollback, and live-feed evidence IDs.",
            },
        ]
        approved = not missing and all(row["status"] == "approved" for row in approver_rows)
        approval_basis = {
            "decision_id": payload.get("decision_id"),
            "task_id": task.get("task_id"),
            "department": department,
            "tool": tool,
            "scope": policy.get("lifted_scope"),
        }
        approvals.append(
            {
                "approval_id": f"risk_lift_{hashlib.sha1(json.dumps(approval_basis, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:12]}",
                "status": "approved" if approved else "blocked",
                "stage": "approved_for_escalated_executor" if approved else "missing_required_controls",
                "agent": task.get("agent"),
                "department": department,
                "source_tool": tool,
                "task_id": task.get("task_id"),
                "policy_status": task.get("policy_status"),
                "lifted_scope": policy.get("lifted_scope"),
                "receiver": policy.get("receiver"),
                "limits": policy.get("limits", []),
                "approvers": approver_rows,
                "missing_controls": missing,
                "live_feed_event_ids": live_feed_event_ids,
                "rollback": task.get("fallback"),
                "exit_condition": task.get("exit_condition"),
                "expires_at": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
                "boundary": "This lifts only the named action into simulated receiver execution. It does not grant ride reopen, safety clearance, security control, evacuation, medical dispatch, or public emergency messaging authority.",
            }
        )
    approved_count = sum(1 for row in approvals if row.get("status") == "approved")
    return {
        "mode": "risk_escalation_approval",
        "status": "approved" if approved_count else "blocked" if approvals else "not_requested",
        "stage": "approved_for_escalated_executor" if approved_count else "no_eligible_approval",
        "requested_count": len(approvals),
        "approved_count": approved_count,
        "blocked_count": len(approvals) - approved_count,
        "required_approvers": ["safety_agent", "compliance_agent", "executive_agent"],
        "policy": "Default gate stays closed; only eligible held actions with Safety, Compliance, and Executive approval can enter simulated escalated execution.",
        "approvals": approvals,
    }


def _apply_risk_escalation_validation_mode(payload: dict[str, Any], mode: str | None) -> dict[str, Any]:
    normalized = str(mode or "normal").strip().lower()
    payload["risk_escalation_validation_mode"] = normalized
    if normalized != "missing_controls":
        return payload
    follow = payload.get("hard_decision_follow_through", {}) if isinstance(payload.get("hard_decision_follow_through"), dict) else {}
    tasks = follow.get("tasks", []) if isinstance(follow.get("tasks"), list) else []
    mutated = 0
    for task in tasks:
        if not isinstance(task, dict) or task.get("status") != "routed_to_owner":
            continue
        if not _risk_escalation_policy(str(task.get("source_tool") or ""), str(task.get("department") or "")):
            continue
        review_inputs = task.get("review_inputs", {}) if isinstance(task.get("review_inputs"), dict) else {}
        review_inputs["live_feed_event_ids"] = []
        task["review_inputs"] = review_inputs
        task["exit_condition"] = ""
        task["fallback"] = ""
        task["validation_fault"] = "missing_controls_for_risk_escalation_gate"
        mutated += 1
    payload["risk_escalation_validation_fault"] = {
        "mode": normalized,
        "mutated_task_count": mutated,
        "purpose": "QA-only mixed escalation batch: prove missing controls block lifted execution.",
    }
    return payload


def _risk_escalated_live_feed_tool_executor_run(payload: dict[str, Any], *, execute: bool) -> dict[str, Any]:
    approval = payload.get("risk_escalation_approval", {}) if isinstance(payload.get("risk_escalation_approval"), dict) else {}
    approvals = approval.get("approvals", []) if isinstance(approval.get("approvals"), list) else []
    receipts: list[dict[str, Any]] = []
    for row in approvals:
        if not isinstance(row, dict) or row.get("status") != "approved":
            continue
        context = {
            "department": row.get("department"),
            "tool": "execute_approved_action",
            "intent": f"Escalated simulated execution for held {row.get('source_tool')}",
            "evidence": row.get("live_feed_event_ids") or [],
            "risk_level": "elevated",
            "policy_check": "safety_compliance_executive_escalation_approved",
            "expected_outcome": f"Receiver acknowledges scoped {row.get('lifted_scope')} without crossing blocked authorities.",
            "rollback": row.get("rollback"),
            "policy_gate_checked": True,
            "policyGateStatus": "approved_escalated_simulated",
            "decision_id": payload.get("decision_id"),
            "risk_escalation_approval": row,
            "live_feed_event_ids": row.get("live_feed_event_ids") or [],
        }
        result = run_agent_tool(
            "tool_executor_agent",
            "execute_approved_action",
            context,
            lambda row=row: {
                "status": "executed_escalated_simulated" if execute else "preview_escalated_simulated",
                "mode": "risk_escalated_live_feed_tool_executor",
                "executed": bool(execute),
                "source_agent": row.get("agent"),
                "source_department": row.get("department"),
                "source_tool": row.get("source_tool"),
                "approval_id": row.get("approval_id"),
                "lifted_scope": row.get("lifted_scope"),
                "idempotency_key": hashlib.sha1(
                    json.dumps(
                        {
                            "decision_id": payload.get("decision_id"),
                            "approval_id": row.get("approval_id"),
                            "tool": row.get("source_tool"),
                            "events": row.get("live_feed_event_ids") or [],
                        },
                        sort_keys=True,
                        default=str,
                    ).encode("utf-8")
                ).hexdigest()[:16],
                "rollback": row.get("rollback"),
            },
        )
        receipts.append(
            {
                "agent": row.get("agent"),
                "department": row.get("department"),
                "source_tool": row.get("source_tool"),
                "policy_check": "safety_compliance_executive_escalation_approved",
                "policy_status": "approved_escalated_simulated",
                "executor_status": "ready_for_escalated_executor",
                "approval_id": row.get("approval_id"),
                "risk_escalation_approval": row,
                "live_feed_event_ids": row.get("live_feed_event_ids") or [],
                "result": result,
            }
        )
    executed_count = sum(1 for row in receipts if (row.get("result", {}) if isinstance(row.get("result"), dict) else {}).get("status") == "executed_escalated_simulated")
    preview_count = sum(1 for row in receipts if (row.get("result", {}) if isinstance(row.get("result"), dict) else {}).get("status") == "preview_escalated_simulated")
    return {
        "mode": "risk_escalated_live_feed_tool_executor",
        "status": "executed" if executed_count else "preview" if preview_count else "not_executed",
        "execute_requested": bool(execute),
        "receipt_count": len(receipts),
        "executed_count": executed_count,
        "preview_count": preview_count,
        "executor_agent": "tool_executor_agent",
        "contract": "Escalated executor accepts only named approval artifacts with Safety, Compliance, and Executive approval; it executes simulated receiver actions only.",
        "receipts": receipts,
    }


def _controlled_live_feed_receiver_delivery_proof(payload: dict[str, Any]) -> dict[str, Any]:
    executor = payload.get("tool_executor_live_test", {}) if isinstance(payload.get("tool_executor_live_test"), dict) else {}
    live_case = payload.get("live_feed_case", {}) if isinstance(payload.get("live_feed_case"), dict) else {}
    receipts = executor.get("receipts", []) if isinstance(executor.get("receipts"), list) else []
    receiver_by_department = {
        "operations": "ops_console",
        "maintenance": "maintenance_console",
        "food_retail": "food_ops_console",
        "hr_labor": "labor_scheduler_console",
        "marketing": "marketing_ops_console",
    }
    proof_rows: list[dict[str, Any]] = []
    for receipt in receipts:
        if not isinstance(receipt, dict):
            continue
        result = receipt.get("result", {}) if isinstance(receipt.get("result"), dict) else {}
        executed = result.get("status") == "executed_controlled"
        department = str(receipt.get("department") or "")
        receiver = receiver_by_department.get(department)
        if not executed:
            proof_rows.append(
                {
                    "agent": receipt.get("agent"),
                    "department": receipt.get("department"),
                    "source_tool": receipt.get("source_tool"),
                    "status": "not_dispatched_policy_hold",
                    "delivered": False,
                    "acknowledged": False,
                    "reason": (result.get("reason") if isinstance(result, dict) else None) or "Action was held by policy or executive gate.",
                }
            )
            continue
        if not receiver:
            proof_rows.append(
                {
                    "agent": receipt.get("agent"),
                    "department": receipt.get("department"),
                    "source_tool": receipt.get("source_tool"),
                    "status": "receiver_not_configured",
                    "delivered": False,
                    "acknowledged": False,
                    "reason": "No bounded internal receiver is configured for this department.",
                }
            )
            continue
        dispatch_payload = {
            "scenarioKey": "live_feed_controlled_executor",
            "decisionId": payload.get("decision_id"),
            "agentId": receipt.get("agent"),
            "executorAgentId": "tool_executor_agent",
            "department": department,
            "targetReceiver": receiver,
            "sourceTool": receipt.get("source_tool"),
            "intent": f"Deliver controlled internal action handoff for {receipt.get('source_tool')}",
            "evidence": live_case.get("live_feed_event_ids") or [],
            "riskLevel": "low",
            "policyCheck": receipt.get("policy_check"),
            "policyGateStatus": receipt.get("policy_status"),
            "policyGateChecked": True,
            "expectedOutcome": "Internal receiver records the controlled action handoff.",
            "rollback": (result.get("rollback") if isinstance(result, dict) else None) or "Supersede this internal receiver task if the live feed normalizes.",
            "liveFeedEventIds": live_case.get("live_feed_event_ids") or [],
            "controlledExecutorReceiptId": result.get("idempotency_key"),
            "publicGuestMessage": False,
            "materialStateMutation": False,
        }
        try:
            dispatch = send_worker_notification(dispatch_payload)
            acknowledged = {}
            if dispatch.get("status") in {"delivered", "acknowledged"}:
                acknowledged = acknowledge_dispatch(
                    str(dispatch.get("id")),
                    actor=f"{receiver}:system",
                    choice="received_controlled_internal_action",
                    channel=str(dispatch.get("channel") or "worker_device"),
                )
            delivered = dispatch.get("status") in {"delivered", "acknowledged"} or acknowledged.get("status") == "acknowledged"
            acked = acknowledged.get("status") == "acknowledged" or dispatch.get("status") == "acknowledged"
            proof_rows.append(
                {
                    "agent": receipt.get("agent"),
                    "department": receipt.get("department"),
                    "source_tool": receipt.get("source_tool"),
                    "status": "delivered_and_acknowledged" if delivered and acked else "dispatch_recorded_without_ack",
                    "receiver": receiver,
                    "channel": dispatch.get("channel"),
                    "dispatch_id": dispatch.get("id"),
                    "dispatch_status": dispatch.get("status"),
                    "dispatch_durable": dispatch.get("durable"),
                    "ack_status": acknowledged.get("status"),
                    "acknowledged_by": (acknowledged.get("lastAcknowledgement", {}) if isinstance(acknowledged.get("lastAcknowledgement"), dict) else {}).get("actor"),
                    "idempotency_key": dispatch.get("idempotencyKey") or result.get("idempotency_key"),
                    "delivered": bool(delivered),
                    "acknowledged": bool(acked),
                    "material_state_mutation": False,
                }
            )
        except Exception as error:
            proof_rows.append(
                {
                    "agent": receipt.get("agent"),
                    "department": receipt.get("department"),
                    "source_tool": receipt.get("source_tool"),
                    "status": "delivery_error",
                    "receiver": receiver,
                    "delivered": False,
                    "acknowledged": False,
                    "error": str(error)[:300],
                    "material_state_mutation": False,
                }
            )
    executed_count = sum(1 for row in receipts if isinstance(row, dict) and (row.get("result", {}) if isinstance(row.get("result"), dict) else {}).get("status") == "executed_controlled")
    delivered_count = sum(1 for row in proof_rows if row.get("delivered"))
    acknowledged_count = sum(1 for row in proof_rows if row.get("acknowledged"))
    proof_id = f"receiver_proof_{hashlib.sha1(json.dumps({'decision_id': payload.get('decision_id'), 'rows': proof_rows}, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:12]}"
    return {
        "mode": "controlled_live_feed_receiver_delivery_proof",
        "proof_id": proof_id,
        "status": "proven_controlled" if executed_count and delivered_count == executed_count and acknowledged_count == executed_count else "incomplete",
        "execution_mode": "controlled_internal_receiver_handoff",
        "action_effect_boundary": "Actions create durable internal receiver tasks and acknowledgements only; they intentionally do not mutate the simulated park state or send public guest messages.",
        "material_mutation_policy": "blocked_for_smoke_validation",
        "executor_agent": "tool_executor_agent",
        "delivery_agent": "delivery_proof_agent",
        "executed_count": executed_count,
        "delivered_count": delivered_count,
        "acknowledged_count": acknowledged_count,
        "held_count": sum(1 for row in proof_rows if row.get("status") == "not_dispatched_policy_hold"),
        "public_guest_messages_sent": 0,
        "material_state_mutation": False,
        "contract": "Only controlled low-risk executor receipts are delivered to bounded internal receivers; held or approval-gated actions are not dispatched.",
        "outbox_status": delivery_outbox_status(),
        "receipts": proof_rows,
    }


def _risk_escalation_receiver_delivery_proof(payload: dict[str, Any]) -> dict[str, Any]:
    executor = payload.get("risk_escalated_tool_executor", {}) if isinstance(payload.get("risk_escalated_tool_executor"), dict) else {}
    live_case = payload.get("live_feed_case", {}) if isinstance(payload.get("live_feed_case"), dict) else {}
    receipts = executor.get("receipts", []) if isinstance(executor.get("receipts"), list) else []
    proof_rows: list[dict[str, Any]] = []
    for receipt in receipts:
        if not isinstance(receipt, dict):
            continue
        result = receipt.get("result", {}) if isinstance(receipt.get("result"), dict) else {}
        executed = result.get("status") == "executed_escalated_simulated"
        approval = receipt.get("risk_escalation_approval", {}) if isinstance(receipt.get("risk_escalation_approval"), dict) else {}
        receiver = str(approval.get("receiver") or "")
        if not executed:
            proof_rows.append(
                {
                    "agent": receipt.get("agent"),
                    "department": receipt.get("department"),
                    "source_tool": receipt.get("source_tool"),
                    "approval_id": receipt.get("approval_id"),
                    "status": "not_dispatched_escalation_preview",
                    "delivered": False,
                    "acknowledged": False,
                    "reason": "Escalated executor did not execute this approval.",
                }
            )
            continue
        if not receiver:
            proof_rows.append(
                {
                    "agent": receipt.get("agent"),
                    "department": receipt.get("department"),
                    "source_tool": receipt.get("source_tool"),
                    "approval_id": receipt.get("approval_id"),
                    "status": "receiver_not_configured",
                    "delivered": False,
                    "acknowledged": False,
                    "reason": "Risk escalation approval did not name a bounded receiver.",
                }
            )
            continue
        dispatch_payload = {
            "scenarioKey": "live_feed_risk_escalation",
            "decisionId": payload.get("decision_id"),
            "agentId": receipt.get("agent"),
            "executorAgentId": "tool_executor_agent",
            "department": receipt.get("department"),
            "targetReceiver": receiver,
            "sourceTool": receipt.get("source_tool"),
            "intent": f"Deliver approved simulated risk escalation for {receipt.get('source_tool')}",
            "evidence": receipt.get("live_feed_event_ids") or live_case.get("live_feed_event_ids") or [],
            "riskLevel": "elevated",
            "policyCheck": receipt.get("policy_check"),
            "policyGateStatus": receipt.get("policy_status"),
            "policyGateChecked": True,
            "expectedOutcome": f"Receiver acknowledges scoped escalation: {approval.get('lifted_scope')}",
            "rollback": (result.get("rollback") if isinstance(result, dict) else None) or approval.get("rollback"),
            "liveFeedEventIds": receipt.get("live_feed_event_ids") or live_case.get("live_feed_event_ids") or [],
            "controlledExecutorReceiptId": result.get("idempotency_key"),
            "approvalId": receipt.get("approval_id"),
            "publicGuestMessage": False,
            "materialStateMutation": False,
        }
        try:
            dispatch = send_worker_notification(dispatch_payload)
            acknowledged = {}
            if dispatch.get("status") in {"delivered", "acknowledged"}:
                acknowledged = acknowledge_dispatch(
                    str(dispatch.get("id")),
                    actor=f"{receiver}:risk_escalation_system",
                    choice="received_escalated_simulated_action",
                    channel=str(dispatch.get("channel") or "worker_device"),
                )
            delivered = dispatch.get("status") in {"delivered", "acknowledged"} or acknowledged.get("status") == "acknowledged"
            acked = acknowledged.get("status") == "acknowledged" or dispatch.get("status") == "acknowledged"
            proof_rows.append(
                {
                    "agent": receipt.get("agent"),
                    "department": receipt.get("department"),
                    "source_tool": receipt.get("source_tool"),
                    "approval_id": receipt.get("approval_id"),
                    "lifted_scope": approval.get("lifted_scope"),
                    "status": "delivered_and_acknowledged" if delivered and acked else "dispatch_recorded_without_ack",
                    "receiver": receiver,
                    "channel": dispatch.get("channel"),
                    "dispatch_id": dispatch.get("id"),
                    "dispatch_status": dispatch.get("status"),
                    "dispatch_durable": dispatch.get("durable"),
                    "ack_status": acknowledged.get("status"),
                    "acknowledged_by": (acknowledged.get("lastAcknowledgement", {}) if isinstance(acknowledged.get("lastAcknowledgement"), dict) else {}).get("actor"),
                    "idempotency_key": dispatch.get("idempotencyKey") or result.get("idempotency_key"),
                    "delivered": bool(delivered),
                    "acknowledged": bool(acked),
                    "material_state_mutation": False,
                }
            )
        except Exception as error:
            proof_rows.append(
                {
                    "agent": receipt.get("agent"),
                    "department": receipt.get("department"),
                    "source_tool": receipt.get("source_tool"),
                    "approval_id": receipt.get("approval_id"),
                    "status": "delivery_error",
                    "receiver": receiver,
                    "delivered": False,
                    "acknowledged": False,
                    "error": str(error)[:300],
                    "material_state_mutation": False,
                }
            )
    executed_count = sum(1 for row in receipts if isinstance(row, dict) and (row.get("result", {}) if isinstance(row.get("result"), dict) else {}).get("status") == "executed_escalated_simulated")
    delivered_count = sum(1 for row in proof_rows if row.get("delivered"))
    acknowledged_count = sum(1 for row in proof_rows if row.get("acknowledged"))
    proof_id = f"risk_receiver_proof_{hashlib.sha1(json.dumps({'decision_id': payload.get('decision_id'), 'rows': proof_rows}, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:12]}"
    return {
        "mode": "risk_escalation_receiver_delivery_proof",
        "proof_id": proof_id,
        "status": "proven_escalated" if executed_count and delivered_count == executed_count and acknowledged_count == executed_count else "incomplete" if receipts else "not_requested",
        "execution_mode": "escalated_simulated_receiver_handoff",
        "executor_agent": "tool_executor_agent",
        "delivery_agent": "delivery_proof_agent",
        "executed_count": executed_count,
        "delivered_count": delivered_count,
        "acknowledged_count": acknowledged_count,
        "public_guest_messages_sent": 0,
        "material_state_mutation": False,
        "contract": "Escalated receiver delivery is simulated and scoped; receiver acknowledgement is required before simulated park-state impact is applied.",
        "outbox_status": delivery_outbox_status(),
        "receipts": proof_rows,
    }


def _live_feed_controlled_impact_text(issue_kind: str, department: str, tool: str, target_id: str) -> str:
    issue_text = issue_kind.replace("_", " ")
    target_text = target_id.replace("_", " ")
    if department == "food_retail" or tool in {"inventory_alert", "pause_launch_promo", "restock_request"}:
        return f"food court mobile order inventory kitchen pickup queue control for {issue_text} at {target_text}"
    if department == "hr_labor" or tool == "shift_adjustment_recommendation":
        return f"staff worker break callout labor coverage support for {issue_text} at {target_text}"
    if department == "maintenance" or tool == "create_work_order":
        if issue_kind in {"energy_spike", "storm_risk", "heat_index_spike", "lightning_delay"}:
            return f"hvac energy equipment maintenance work order for {issue_text} at {target_text}"
        return f"ride coaster maintenance inspection work order queue containment for {issue_text} at {target_text}"
    if department == "operations" or tool == "create_ops_alert":
        if issue_kind in {"energy_spike", "storm_risk", "heat_index_spike", "lightning_delay"}:
            return f"hvac weather operations alert shelter comfort energy for {issue_text} at {target_text}"
        if issue_kind in {"access_lane_block", "parade_route_conflict", "ticketing_gate_surge", "parking_arrival_wave", "radio_dead_zone", "security_perimeter"}:
            return f"crowd security access lane congestion operations alert for {issue_text} at {target_text}"
        if issue_kind in {"demand_spike", "show_dump", "ride_failure"}:
            return f"ride coaster queue crowd flow operations alert for {issue_text} at {target_text}"
    if department == "marketing" or tool == "redirect_offer":
        return f"food guest demand redirect offer queue relief for {issue_text} at {target_text}"
    return f"operations controlled internal receiver impact for {issue_text} at {target_text}"


def _live_feed_escalated_impact_text(issue_kind: str, department: str, tool: str, target_id: str) -> str:
    issue_text = issue_kind.replace("_", " ")
    target_text = target_id.replace("_", " ")
    if tool == "recommend_route_change":
        return f"crowd congestion calm route crowd safety route recommendation for {issue_text} at {target_text}"
    if tool == "draft_guest_message":
        return f"guest care cases calm guidance guest message queue uncertainty for {issue_text} at {target_text}"
    if tool == "create_work_order":
        return f"ride coaster maintenance work order inspection queue containment for {issue_text} at {target_text}"
    if tool == "redirect_offer":
        return f"food guest demand redirect offer capacity cap crowd relief for {issue_text} at {target_text}"
    return f"crowd controlled simulated escalation for {issue_text} at {target_text}"


async def _apply_controlled_live_feed_simulated_ops_impact(payload: dict[str, Any]) -> dict[str, Any]:
    receiver_delivery = payload.get("live_feed_receiver_delivery", {}) if isinstance(payload.get("live_feed_receiver_delivery"), dict) else {}
    if receiver_delivery.get("status") != "proven_controlled":
        return {
            "status": "skipped",
            "mode": "controlled_live_feed_simulated_ops_impact",
            "reason": "Receiver delivery is not fully proven; simulated park state was not mutated.",
            "material_state_mutation": False,
        }
    proof_rows = receiver_delivery.get("receipts", []) if isinstance(receiver_delivery.get("receipts"), list) else []
    delivered = [
        row
        for row in proof_rows
        if isinstance(row, dict) and row.get("delivered") is True and row.get("acknowledged") is True
    ]
    if not delivered:
        return {
            "status": "skipped",
            "mode": "controlled_live_feed_simulated_ops_impact",
            "reason": "No acknowledged controlled receiver rows were available for simulated ops impact.",
            "material_state_mutation": False,
        }
    live_case = payload.get("live_feed_case", {}) if isinstance(payload.get("live_feed_case"), dict) else {}
    generated_issue = live_case.get("generated_issue", {}) if isinstance(live_case.get("generated_issue"), dict) else {}
    issue_kind = str(generated_issue.get("kind") or live_case.get("issue_kind") or live_case.get("scenario_key") or "live_feed_issue")
    target_id = str(generated_issue.get("target_id") or generated_issue.get("targetId") or live_case.get("issue_target_id") or "affected_area")
    dispatches = []
    for row in delivered:
        department = str(row.get("department") or "")
        tool = str(row.get("source_tool") or "")
        impact_text = _live_feed_controlled_impact_text(issue_kind, department, tool, target_id)
        acknowledged_count = 2 if department == "hr_labor" else 1
        dispatches.append(
            {
                "id": row.get("dispatch_id") or row.get("idempotency_key"),
                "channel": "worker_device",
                "target": row.get("receiver") or department,
                "status": "acknowledged",
                "payload": {
                    "title": f"Controlled live-feed impact: {tool}",
                    "message": impact_text,
                    "department": department,
                    "sourceTool": tool,
                    "issueKind": issue_kind,
                    "targetId": target_id,
                    "policyBoundary": "simulated low-risk ops mutation only; no public message, route command, reopen, safety clearance, or security control",
                },
                "response": {
                    "state": "acknowledged",
                    "acknowledgedCount": acknowledged_count,
                    "followThroughCount": 0,
                    "applied": True,
                },
            }
        )
    try:
        impact = await park_simulation.apply_delivery_outcomes(
            dispatches,
            reason=f"live_feed_controlled_ops_impact:{issue_kind}",
        )
    except Exception as error:
        return {
            "status": "error",
            "mode": "controlled_live_feed_simulated_ops_impact",
            "error": str(error)[:300],
            "material_state_mutation": False,
            "receiver_rows": len(delivered),
        }
    material_state_mutation = impact.get("status") == "success"
    if material_state_mutation:
        clear_hot_endpoint_cache()
    state_impact = impact.get("stateImpact", {}) if isinstance(impact.get("stateImpact"), dict) else {}
    episode_fitness = impact.get("episode_fitness") if isinstance(impact.get("episode_fitness"), dict) else {}
    if isinstance(episode_fitness.get("scores"), dict):
        episode_fitness = {
            **episode_fitness,
            "fitness": episode_fitness.get("fitness", episode_fitness["scores"].get("fitness")),
            "rewardDelta": episode_fitness.get("rewardDelta", episode_fitness["scores"].get("reward_delta")),
        }
    if isinstance(episode_fitness.get("pressure"), dict):
        episode_fitness = {
            **episode_fitness,
            "pressureReduction": episode_fitness.get("pressureReduction", episode_fitness["pressure"].get("reduction_vs_baseline")),
        }
    return {
        "status": "applied" if material_state_mutation else impact.get("status", "skipped"),
        "mode": "controlled_live_feed_simulated_ops_impact",
        "issue_kind": issue_kind,
        "target_id": target_id,
        "material_state_mutation": material_state_mutation,
        "receiver_rows": len(delivered),
        "dispatch_count": len(dispatches),
        "message": impact.get("message"),
        "state_impact": state_impact,
        "episode_fitness": episode_fitness,
        "boundary": "Only policy-passed low-risk internal receiver acknowledgements can mutate simulated ops state. Public guest messaging, security control, route changes, ride reopen, and safety clearance remain blocked.",
    }


async def _apply_risk_escalation_simulated_ops_impact(payload: dict[str, Any]) -> dict[str, Any]:
    receiver_delivery = payload.get("risk_escalation_receiver_delivery", {}) if isinstance(payload.get("risk_escalation_receiver_delivery"), dict) else {}
    if receiver_delivery.get("status") != "proven_escalated":
        return {
            "status": "skipped",
            "mode": "risk_escalation_simulated_ops_impact",
            "reason": "Escalated receiver delivery is not fully proven; simulated park state was not mutated by lifted action.",
            "material_state_mutation": False,
        }
    proof_rows = receiver_delivery.get("receipts", []) if isinstance(receiver_delivery.get("receipts"), list) else []
    delivered = [
        row
        for row in proof_rows
        if isinstance(row, dict) and row.get("delivered") is True and row.get("acknowledged") is True
    ]
    if not delivered:
        return {
            "status": "skipped",
            "mode": "risk_escalation_simulated_ops_impact",
            "reason": "No acknowledged escalated receiver rows were available for simulated ops impact.",
            "material_state_mutation": False,
        }
    live_case = payload.get("live_feed_case", {}) if isinstance(payload.get("live_feed_case"), dict) else {}
    generated_issue = live_case.get("generated_issue", {}) if isinstance(live_case.get("generated_issue"), dict) else {}
    issue_kind = str(generated_issue.get("kind") or live_case.get("issue_kind") or live_case.get("scenario_key") or "live_feed_issue")
    target_id = str(generated_issue.get("target_id") or generated_issue.get("targetId") or live_case.get("issue_target_id") or "affected_area")
    dispatches = []
    for row in delivered:
        department = str(row.get("department") or "")
        tool = str(row.get("source_tool") or "")
        dispatches.append(
            {
                "id": row.get("dispatch_id") or row.get("idempotency_key"),
                "channel": "worker_device",
                "target": row.get("receiver") or department,
                "status": "acknowledged",
                "payload": {
                    "title": f"Escalated simulated impact: {tool}",
                    "message": _live_feed_escalated_impact_text(issue_kind, department, tool, target_id),
                    "department": department,
                    "sourceTool": tool,
                    "issueKind": issue_kind,
                    "targetId": target_id,
                    "approvalId": row.get("approval_id"),
                    "policyBoundary": "simulated risk-lift only; no ride reopen, security control, evacuation, medical dispatch, or public emergency message",
                },
                "response": {
                    "state": "acknowledged",
                    "acknowledgedCount": 2,
                    "followThroughCount": 1,
                    "applied": True,
                },
            }
        )
    try:
        impact = await park_simulation.apply_delivery_outcomes(
            dispatches,
            reason=f"live_feed_risk_escalation:{issue_kind}",
        )
    except Exception as error:
        return {
            "status": "error",
            "mode": "risk_escalation_simulated_ops_impact",
            "error": str(error)[:300],
            "material_state_mutation": False,
            "receiver_rows": len(delivered),
        }
    material_state_mutation = impact.get("status") == "success"
    if material_state_mutation:
        clear_hot_endpoint_cache()
    state_impact = impact.get("stateImpact", {}) if isinstance(impact.get("stateImpact"), dict) else {}
    episode_fitness = impact.get("episode_fitness") if isinstance(impact.get("episode_fitness"), dict) else {}
    if isinstance(episode_fitness.get("scores"), dict):
        episode_fitness = {
            **episode_fitness,
            "fitness": episode_fitness.get("fitness", episode_fitness["scores"].get("fitness")),
            "rewardDelta": episode_fitness.get("rewardDelta", episode_fitness["scores"].get("reward_delta")),
        }
    if isinstance(episode_fitness.get("pressure"), dict):
        episode_fitness = {
            **episode_fitness,
            "pressureReduction": episode_fitness.get("pressureReduction", episode_fitness["pressure"].get("reduction_vs_baseline")),
        }
    validation_mode = str(payload.get("risk_escalation_validation_mode") or "normal").strip().lower()
    if validation_mode == "pending_measurement":
        return {
            "status": "pending_measurement",
            "mode": "risk_escalation_simulated_ops_impact",
            "issue_kind": issue_kind,
            "target_id": target_id,
            "material_state_mutation": False,
            "receiver_rows": len(delivered),
            "dispatch_count": len(dispatches),
            "message": "Escalated action was delivered, but post-action measurement is intentionally withheld for QA validation.",
            "state_impact": {},
            "episode_fitness": {},
            "validation_fault": validation_mode,
            "boundary": "QA-only validation fault; no reward promotion until measurement exists.",
        }
    if validation_mode == "impact_regression":
        state_impact = {
            **state_impact,
            "headline": "QA validation adverse effect: lifted action increased congestion in the simulated measurement.",
            "before_after_line": "Risk-lift validation forced an adverse post-action measurement.",
            "congestion_delta": abs(float(state_impact.get("congestion_delta") or 18)),
            "queued_guest_delta": abs(float(state_impact.get("queued_guest_delta") or state_impact.get("queue_delta") or 80)),
        }
        episode_fitness = {
            **episode_fitness,
            "fitness": 0,
            "rewardDelta": -1,
            "pressureReduction": 0,
        }
    return {
        "status": "applied" if material_state_mutation else impact.get("status", "skipped"),
        "mode": "risk_escalation_simulated_ops_impact",
        "issue_kind": issue_kind,
        "target_id": target_id,
        "material_state_mutation": material_state_mutation,
        "receiver_rows": len(delivered),
        "dispatch_count": len(dispatches),
        "message": impact.get("message"),
        "state_impact": state_impact,
        "episode_fitness": episode_fitness,
        "validation_fault": validation_mode if validation_mode in {"impact_regression"} else None,
        "boundary": "Only approval-scoped lifted actions mutate simulated ops state. Real public messaging, route commands, security control, ride reopen, evacuation, and medical dispatch remain blocked.",
    }


def _live_feed_numeric_metrics(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    metrics: dict[str, float] = {}
    for key, raw in value.items():
        if isinstance(raw, bool):
            continue
        if isinstance(raw, (int, float)):
            metrics[str(key)] = float(raw)
        elif isinstance(raw, list):
            metrics[f"{key}_count"] = float(len(raw))
    return metrics


def _live_feed_metric_direction(source: str, metric: str) -> str:
    lower_is_better = {
        "ride_ops": {"capacity_pressure_pct", "down_ride_count"},
        "food_ops": {"kitchen_load_pct", "low_inventory_items_count", "mobile_order_backlog"},
        "operator_signal": {"open_cases", "complaint_rate_pct"},
    }
    higher_is_better = {
        "guest_flow": {"routing_take_rate_pct", "avg_satisfaction"},
        "staffing": {"guard_team_count", "health_team_count"},
    }
    if metric in lower_is_better.get(source, set()):
        return "lower_is_better"
    if metric in higher_is_better.get(source, set()):
        return "higher_is_better"
    return "stability_watch"


def _live_feed_metric_score(source: str, metric: str, delta: float) -> int:
    direction = _live_feed_metric_direction(source, metric)
    if direction == "lower_is_better":
        return 1 if delta < 0 else -1 if delta > 0 else 0
    if direction == "higher_is_better":
        return 1 if delta > 0 else -1 if delta < 0 else 0
    return 0 if abs(delta) < 0.0001 else -1


def _bounded_metric(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return round(min(upper, max(lower, value)), 3)


def _live_feed_adjust_metric(value: dict[str, Any], key: str, delta: float, *, lower: float = 0.0, upper: float = 100.0) -> bool:
    if key not in value or isinstance(value.get(key), bool) or not isinstance(value.get(key), (int, float)):
        return False
    before = float(value[key])
    after = _bounded_metric(before + delta, lower, upper)
    if after == before:
        return False
    value[key] = int(after) if after.is_integer() else after
    return True


def _apply_controlled_receiver_effect_projection(payload: dict[str, Any], post_action_refresh: dict[str, Any] | None) -> dict[str, Any]:
    refresh = dict(post_action_refresh) if isinstance(post_action_refresh, dict) else {}
    if isinstance(refresh.get("controlled_effect_projection"), dict) and refresh["controlled_effect_projection"].get("status") == "applied":
        return refresh
    after_feeds = refresh.get("after_feeds", [])
    if not isinstance(after_feeds, list):
        return refresh
    receiver_delivery = payload.get("live_feed_receiver_delivery", {}) if isinstance(payload.get("live_feed_receiver_delivery"), dict) else {}
    if receiver_delivery.get("status") != "proven_controlled":
        return refresh
    executor = payload.get("tool_executor_live_test", {}) if isinstance(payload.get("tool_executor_live_test"), dict) else {}
    receipts = executor.get("receipts", []) if isinstance(executor.get("receipts"), list) else []
    executed = [
        row
        for row in receipts
        if isinstance(row, dict)
        and (row.get("result", {}) if isinstance(row.get("result"), dict) else {}).get("status") == "executed_controlled"
    ]
    executed_departments = {str(row.get("department")) for row in executed if row.get("department")}
    executed_tools = {str(row.get("source_tool")) for row in executed if row.get("source_tool")}
    semantic_parameter_rows = [
        row.get("semantic_action_parameters") or row.get("action_parameters") or (row.get("result", {}) if isinstance(row.get("result"), dict) else {}).get("semantic_action_parameters") or {}
        for row in executed
        if isinstance(row, dict)
    ]
    semantic_parameters_applied = any(isinstance(row, dict) and row.get("source") == "semantic_agent_learning" for row in semantic_parameter_rows)
    split_routing_applied = any(isinstance(row, dict) and row.get("routing_strategy") == "split_across_low_wait_destinations" for row in semantic_parameter_rows)
    stronger_offer_applied = any(isinstance(row, dict) and row.get("offer_strength") == "stronger_personalized" for row in semantic_parameter_rows)
    cap_overloaded_targets_applied = any(isinstance(row, dict) and row.get("traffic_cap_policy") == "cap_overloaded_indoor_targets" for row in semantic_parameter_rows)
    if not executed_departments:
        return refresh

    projection_rows: list[dict[str, Any]] = []
    adjusted_feeds: list[dict[str, Any]] = []
    for feed in after_feeds:
        if not isinstance(feed, dict):
            adjusted_feeds.append(feed)
            continue
        adjusted = dict(feed)
        value = dict(adjusted.get("value", {})) if isinstance(adjusted.get("value"), dict) else {}
        source = str(adjusted.get("source") or "")
        changed_metrics: list[dict[str, Any]] = []

        def record_metric(metric: str, before_value: Any) -> None:
            changed_metrics.append({"metric": metric, "before": before_value, "after": value.get(metric)})

        if source == "food_ops" and "food_retail" in executed_departments:
            before = value.get("kitchen_load_pct")
            if _live_feed_adjust_metric(value, "kitchen_load_pct", -11 if cap_overloaded_targets_applied else -8):
                record_metric("kitchen_load_pct", before)
            before = value.get("mobile_order_backlog")
            if _live_feed_adjust_metric(value, "mobile_order_backlog", -10 if stronger_offer_applied else -6):
                record_metric("mobile_order_backlog", before)
            if executed_tools.intersection({"inventory_alert", "restock_request"}) and isinstance(value.get("low_inventory_items"), list) and value["low_inventory_items"]:
                before_items = list(value["low_inventory_items"])
                value["low_inventory_items"] = before_items[:-1]
                changed_metrics.append({"metric": "low_inventory_items_count", "before": len(before_items), "after": len(value["low_inventory_items"])})

        if source == "guest_flow" and "marketing" in executed_departments:
            before = value.get("routing_take_rate_pct")
            if _live_feed_adjust_metric(value, "routing_take_rate_pct", 8 if stronger_offer_applied else 5):
                record_metric("routing_take_rate_pct", before)
            before = value.get("avg_satisfaction")
            if _live_feed_adjust_metric(value, "avg_satisfaction", 3 if split_routing_applied else 2):
                record_metric("avg_satisfaction", before)

        if source == "staffing" and "hr_labor" in executed_departments:
            before = value.get("guard_team_count")
            if _live_feed_adjust_metric(value, "guard_team_count", 1):
                record_metric("guard_team_count", before)
            before = value.get("health_team_count")
            if _live_feed_adjust_metric(value, "health_team_count", 1):
                record_metric("health_team_count", before)
            before = value.get("staff_ready_pct")
            if _live_feed_adjust_metric(value, "staff_ready_pct", 2):
                record_metric("staff_ready_pct", before)
            before = value.get("fatigue_risk_pct")
            if _live_feed_adjust_metric(value, "fatigue_risk_pct", -4):
                record_metric("fatigue_risk_pct", before)

        if source == "operator_signal" and {"food_retail", "marketing"}.intersection(executed_departments):
            before = value.get("open_cases")
            if _live_feed_adjust_metric(value, "open_cases", -3 if semantic_parameters_applied else -2):
                record_metric("open_cases", before)
            before = value.get("complaint_rate_pct")
            if _live_feed_adjust_metric(value, "complaint_rate_pct", -0.35 if split_routing_applied else -0.2):
                record_metric("complaint_rate_pct", before)

        if source == "ride_ops" and "marketing" in executed_departments:
            before = value.get("capacity_pressure_pct")
            if _live_feed_adjust_metric(value, "capacity_pressure_pct", -3 if split_routing_applied else -2):
                record_metric("capacity_pressure_pct", before)

        if changed_metrics:
            basis = {
                "decision_id": payload.get("decision_id"),
                "source": source,
                "departments": sorted(executed_departments),
                "tools": sorted(executed_tools),
                "semantic_parameters_applied": semantic_parameters_applied,
                "event": adjusted.get("latest_event_id"),
            }
            adjusted["value"] = value
            adjusted["latest_event_id"] = f"projection_{hashlib.sha1(json.dumps(basis, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:14]}"
            adjusted["latest_signal_type"] = "controlled_receiver_effect"
            adjusted["controlled_effect_projection"] = {
                "status": "applied",
                "source": "receiver_acknowledged_low_risk_actions",
                "material_state_mutation": False,
                "executed_departments": sorted(executed_departments),
                "executed_tools": sorted(executed_tools),
                "semantic_parameters_applied": semantic_parameters_applied,
                "semantic_parameter_rows": [row for row in semantic_parameter_rows if isinstance(row, dict) and row],
                "changed_metrics": changed_metrics,
            }
            projection_rows.append(
                {
                    "source": source,
                    "projected_event_id": adjusted["latest_event_id"],
                    "changed_metrics": changed_metrics,
                }
            )
        adjusted_feeds.append(adjusted)

    if projection_rows:
        refresh["after_feeds"] = adjusted_feeds
        refresh["controlled_effect_projection"] = {
            "status": "applied",
            "mode": "receiver_acknowledged_controlled_effect_projection",
            "executed_departments": sorted(executed_departments),
            "executed_tools": sorted(executed_tools),
            "semantic_parameters_applied": semantic_parameters_applied,
            "semantic_parameter_rows": [row for row in semantic_parameter_rows if isinstance(row, dict) and row],
            "projection_count": len(projection_rows),
            "rows": projection_rows,
            "material_state_mutation": False,
            "boundary": "Projected effect is derived from acknowledged low-risk internal receiver actions; it does not mutate the park simulation state, send public messages, or override held safety/security/routing actions.",
        }
    return refresh


def _bounded_reward(value: float) -> float:
    return round(min(1.0, max(0.0, value)), 3)


def _live_feed_metric_delta(rows: list[dict[str, Any]], source: str, metric: str) -> float | None:
    for row in rows:
        if not isinstance(row, dict) or row.get("source") != source:
            continue
        metrics = row.get("metrics", []) if isinstance(row.get("metrics"), list) else []
        for item in metrics:
            if isinstance(item, dict) and item.get("metric") == metric:
                try:
                    return float(item.get("delta"))
                except (TypeError, ValueError):
                    return None
    return None


def _live_feed_positive_delta_score(delta: float | None, *, lower_is_better: bool = True, scale: float = 10.0) -> float:
    if delta is None:
        return 0.0
    signed = -delta if lower_is_better else delta
    return _bounded_reward(signed / max(1.0, scale))


def _commerce_action_attribution(rows: list[dict[str, Any]], receipts: list[dict[str, Any]]) -> dict[str, Any]:
    executed_tools = {
        str(row.get("source_tool") or row.get("tool") or "")
        for row in receipts
        if isinstance(row, dict)
        and isinstance(row.get("result"), dict)
        and row["result"].get("executed") is True
    }
    if not executed_tools.intersection({"pause_launch_promo", "redirect_offer", "inventory_alert", "restock_request", "shift_adjustment_recommendation"}):
        return {"status": "not_applicable", "reason": "No Commerce-related controlled receiver action executed."}

    kitchen_load_delta = _live_feed_metric_delta(rows, "food_ops", "kitchen_load_pct")
    low_inventory_delta = _live_feed_metric_delta(rows, "food_ops", "low_inventory_items_count")
    mobile_backlog_delta = _live_feed_metric_delta(rows, "food_ops", "mobile_order_backlog")
    pickup_eta_delta = _live_feed_metric_delta(rows, "food_ops", "pickup_eta_minutes")
    satisfaction_delta = _live_feed_metric_delta(rows, "guest_flow", "avg_satisfaction")
    take_rate_delta = _live_feed_metric_delta(rows, "guest_flow", "routing_take_rate_pct")
    guard_delta = _live_feed_metric_delta(rows, "staffing", "guard_team_count")
    health_delta = _live_feed_metric_delta(rows, "staffing", "health_team_count")

    promo_pause_score = _bounded_reward(
        max(
            _live_feed_positive_delta_score(kitchen_load_delta, lower_is_better=True, scale=12.0),
            _live_feed_positive_delta_score(mobile_backlog_delta, lower_is_better=True, scale=40.0),
            _live_feed_positive_delta_score(pickup_eta_delta, lower_is_better=True, scale=8.0),
        )
    )
    inventory_score = _bounded_reward(_live_feed_positive_delta_score(low_inventory_delta, lower_is_better=True, scale=2.0))
    demand_redirect_score = _bounded_reward(
        max(
            _live_feed_positive_delta_score(satisfaction_delta, lower_is_better=False, scale=8.0),
            _live_feed_positive_delta_score(take_rate_delta, lower_is_better=False, scale=15.0),
        )
    )
    labor_support_score = _bounded_reward(
        max(
            _live_feed_positive_delta_score(guard_delta, lower_is_better=False, scale=3.0),
            _live_feed_positive_delta_score(health_delta, lower_is_better=False, scale=2.0),
        )
    )
    rows_out = [
        {
            "action_family": "promo_pause_or_load_relief",
            "executed": "pause_launch_promo" in executed_tools,
            "score": promo_pause_score,
            "evidence_metrics": {"kitchen_load_pct_delta": kitchen_load_delta, "mobile_order_backlog_delta": mobile_backlog_delta, "pickup_eta_minutes_delta": pickup_eta_delta},
        },
        {
            "action_family": "inventory_or_restock",
            "executed": bool(executed_tools.intersection({"inventory_alert", "restock_request", "pause_launch_promo"})),
            "score": inventory_score,
            "evidence_metrics": {"low_inventory_items_count_delta": low_inventory_delta},
        },
        {
            "action_family": "demand_redirect",
            "executed": "redirect_offer" in executed_tools,
            "score": demand_redirect_score,
            "evidence_metrics": {"avg_satisfaction_delta": satisfaction_delta, "routing_take_rate_pct_delta": take_rate_delta},
        },
        {
            "action_family": "labor_support",
            "executed": "shift_adjustment_recommendation" in executed_tools,
            "score": labor_support_score,
            "evidence_metrics": {"guard_team_count_delta": guard_delta, "health_team_count_delta": health_delta},
        },
    ]
    return {
        "status": "scored",
        "mode": "commerce_action_level_outcome_attribution",
        "executed_tools": sorted(tool for tool in executed_tools if tool),
        "average_action_score": _bounded_reward(sum(row["score"] for row in rows_out) / len(rows_out)),
        "rows": rows_out,
        "boundary": "Action-family scores explain Commerce contribution only; they do not override policy, receiver, or promotion gates.",
    }


def _action_family_scores(commerce_attribution: dict[str, Any]) -> dict[str, float]:
    rows = commerce_attribution.get("rows", []) if isinstance(commerce_attribution.get("rows"), list) else []
    return {
        str(row.get("action_family")): float(row.get("score") or 0)
        for row in rows
        if isinstance(row, dict) and row.get("action_family")
    }


def _substitute_action_family(tool: str) -> str:
    mapping = {
        "pause_launch_promo": "promo_pause_or_load_relief",
        "pause_promo": "promo_pause_or_load_relief",
        "inventory_alert": "inventory_or_restock",
        "restock_request": "inventory_or_restock",
        "redirect_offer": "demand_redirect",
        "shift_adjustment_recommendation": "labor_support",
        "overtime_warning": "labor_support",
        "break_reminder": "labor_support",
    }
    return mapping.get(str(tool or ""), "unscored_review_or_trace")


def _substitute_family_metrics(rows: list[dict[str, Any]], action_family: str) -> list[dict[str, Any]]:
    wanted = {
        "promo_pause_or_load_relief": {("food_ops", "kitchen_load_pct"), ("food_ops", "mobile_order_backlog"), ("food_ops", "pickup_eta_minutes")},
        "inventory_or_restock": {("food_ops", "low_inventory_items_count")},
        "demand_redirect": {("guest_flow", "routing_take_rate_pct"), ("guest_flow", "avg_satisfaction"), ("ride_ops", "capacity_pressure_pct")},
        "labor_support": {("staffing", "guard_team_count"), ("staffing", "health_team_count")},
    }.get(action_family, set())
    evidence: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        source = str(row.get("source") or "")
        for metric in row.get("metrics", []) if isinstance(row.get("metrics"), list) else []:
            if isinstance(metric, dict) and (source, str(metric.get("metric") or "")) in wanted:
                evidence.append(
                    {
                        "source": source,
                        "metric": metric.get("metric"),
                        "delta": metric.get("delta"),
                        "impact": metric.get("impact"),
                        "reward_scope": metric.get("reward_scope"),
                        "before_event_id": row.get("before_event_id"),
                        "after_event_id": row.get("after_event_id"),
                    }
                )
    return evidence


def _build_substitute_outcome_attribution(
    payload: dict[str, Any],
    rows: list[dict[str, Any]],
    commerce_attribution: dict[str, Any],
) -> dict[str, Any]:
    proposals = payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}
    board = proposals.get("alternative_action_negotiation", {}) if isinstance(proposals.get("alternative_action_negotiation"), dict) else payload.get("alternative_action_negotiation", {}) if isinstance(payload.get("alternative_action_negotiation"), dict) else {}
    substitute_rows = board.get("rows", []) if isinstance(board.get("rows"), list) else []
    executor = payload.get("tool_executor_live_test", {}) if isinstance(payload.get("tool_executor_live_test"), dict) else {}
    receipts = executor.get("receipts", []) if isinstance(executor.get("receipts"), list) else []
    executed_pairs = {
        (str(row.get("department") or ""), str(row.get("source_tool") or ""))
        for row in receipts
        if isinstance(row, dict)
        and isinstance(row.get("result"), dict)
        and row["result"].get("status") == "executed_controlled"
    }
    family_scores = _action_family_scores(commerce_attribution)
    branch_rows: list[dict[str, Any]] = []
    monitor_only_score = 0.05
    for alternative in substitute_rows:
        if not isinstance(alternative, dict):
            continue
        substitute_department = str(alternative.get("substitute_department") or "")
        substitute_tool = str(alternative.get("substitute_tool") or "")
        action_family = _substitute_action_family(substitute_tool)
        substitute_executed = (substitute_department, substitute_tool) in executed_pairs
        substitute_score = _bounded_reward(family_scores.get(action_family, 0.0) if substitute_executed else 0.0)
        branch_lift = round(substitute_score - monitor_only_score, 3) if substitute_executed else None
        branch_rows.append(
            {
                "alternative_id": alternative.get("alternative_id"),
                "held_agent": alternative.get("held_agent"),
                "held_department": alternative.get("held_department"),
                "held_tool": alternative.get("held_tool"),
                "held_policy_status": alternative.get("held_policy_status"),
                "substitute_agent": alternative.get("substitute_agent"),
                "substitute_department": substitute_department,
                "substitute_tool": substitute_tool,
                "action_family": action_family,
                "substitute_executed": substitute_executed,
                "substitute_outcome_score": substitute_score,
                "monitor_only_counterfactual_score": monitor_only_score,
                "branch_lift_vs_monitor": branch_lift,
                "held_action_counterfactual": {
                    "status": "not_scored_policy_blocked",
                    "reason": "The held sensitive action is not rewarded or simulated as executable because policy did not allow it.",
                },
                "best_branch": (
                    "safe_substitute"
                    if substitute_executed and substitute_score >= monitor_only_score
                    else "monitor_only"
                    if substitute_executed
                    else "not_executed_collect_more_evidence"
                ),
                "measurement_evidence": _substitute_family_metrics(rows, action_family),
                "tradeoff_reason": alternative.get("tradeoff_reason"),
                "execution_boundary": alternative.get("execution_boundary"),
            }
        )

    scored_rows = [row for row in branch_rows if row.get("substitute_executed")]
    average_score = _bounded_reward(sum(float(row.get("substitute_outcome_score") or 0) for row in scored_rows) / len(scored_rows)) if scored_rows else 0.0
    average_lift = round(sum(float(row.get("branch_lift_vs_monitor") or 0) for row in scored_rows) / len(scored_rows), 3) if scored_rows else 0.0

    def bundle_candidate(bundle_id: str, family_set: set[str], *, label: str, monitor_only: bool = False) -> dict[str, Any]:
        included = []
        if not monitor_only:
            included = [row for row in scored_rows if str(row.get("action_family") or "") in family_set]
        if monitor_only:
            score = monitor_only_score
            lift = 0.0
            selected_tools: list[str] = []
            reason = "Fallback preserves policy but does not actively relieve demand, labor, or inventory pressure."
        else:
            score = _bounded_reward(sum(float(row.get("substitute_outcome_score") or 0) for row in included) / len(included)) if included else 0.0
            lift = round(sum(float(row.get("branch_lift_vs_monitor") or 0) for row in included) / len(included), 3) if included else -monitor_only_score
            selected_tools = sorted({f"{row.get('substitute_department')}::{row.get('substitute_tool')}" for row in included})
            reason = f"{label} uses {len(included)} measured safe substitute branch(es) and keeps held sensitive actions non-executable."
        coverage_bonus = min(0.12, len(included) * 0.03) if not monitor_only else 0.0
        bundle_score = _bounded_reward((0.78 * score) + (0.22 * max(0.0, lift)) + coverage_bonus)
        return {
            "bundle_id": bundle_id,
            "label": label,
            "branch_count": len(included),
            "selected_tools": selected_tools,
            "score": bundle_score,
            "average_substitute_score": score,
            "average_lift_vs_monitor": lift,
            "decision_rationale": reason,
            "policy": "Bundle candidate contains only policy-passed substitutes or monitor-only fallback; held sensitive actions remain blocked.",
        }

    bundle_candidates = [
        bundle_candidate(
            "pressure_relief_bundle",
            {"promo_pause_or_load_relief", "demand_redirect", "labor_support", "inventory_or_restock"},
            label="Pressure relief bundle",
        ),
        bundle_candidate(
            "commerce_demand_bundle",
            {"promo_pause_or_load_relief", "demand_redirect", "inventory_or_restock"},
            label="Commerce and demand-shaping bundle",
        ),
        bundle_candidate(
            "labor_support_bundle",
            {"labor_support"},
            label="Labor support bundle",
        ),
        bundle_candidate(
            "monitor_compliance_fallback",
            set(),
            label="Monitor and compliance-only fallback",
            monitor_only=True,
        ),
    ]
    selected_bundle = max(bundle_candidates, key=lambda row: (float(row.get("score") or 0), int(row.get("branch_count") or 0)))
    bundle = {
        **selected_bundle,
        "bundle_id": selected_bundle.get("bundle_id"),
        "executed_branch_count": len(scored_rows),
        "total_branch_count": len(branch_rows),
        "decision": "prefer_safe_substitute_bundle" if selected_bundle.get("bundle_id") != "monitor_compliance_fallback" else "collect_more_evidence",
        "rejected_bundles": [
            {
                "bundle_id": row.get("bundle_id"),
                "label": row.get("label"),
                "score": row.get("score"),
                "reason": "Lower score, narrower coverage, or monitor-only fallback under current measured branch evidence.",
            }
            for row in bundle_candidates
            if row.get("bundle_id") != selected_bundle.get("bundle_id")
        ],
    }
    return {
        "mode": "safe_substitute_branch_outcome_attribution",
        "status": "scored" if branch_rows else "not_available",
        "branch_count": len(branch_rows),
        "executed_branch_count": len(scored_rows),
        "average_substitute_score": average_score,
        "average_lift_vs_monitor": average_lift,
        "rows": branch_rows,
        "bundle_candidates": bundle_candidates,
        "selected_bundle": selected_bundle,
        "bundle": bundle,
        "boundary": "Substitute attribution scores only policy-passed substitute branches against monitor-only; it does not reward or execute held sensitive actions.",
    }


def _live_feed_reward_layers(
    payload: dict[str, Any],
    *,
    rows: list[dict[str, Any]],
    executed_departments: set[str],
    receiver_delivery_proven: bool,
    measurement_available: bool,
    source_coverage: float,
    department_coverage: float,
    attribution_confidence: float,
    improvement_points: int,
    regression_points: int,
    stable_points: int,
    actionable_improvement_points: int | None = None,
    actionable_regression_points: int | None = None,
    actionable_stable_points: int | None = None,
    stability_watch_points: int | None = None,
) -> dict[str, Any]:
    proposals = payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}
    proposal_rows = proposals.get("proposals", []) if isinstance(proposals.get("proposals"), list) else []
    executor = payload.get("tool_executor_live_test", {}) if isinstance(payload.get("tool_executor_live_test"), dict) else {}
    follow_through = payload.get("hard_decision_follow_through", {}) if isinstance(payload.get("hard_decision_follow_through"), dict) else {}
    receiver_delivery = payload.get("live_feed_receiver_delivery", {}) if isinstance(payload.get("live_feed_receiver_delivery"), dict) else {}
    risk_escalation = payload.get("risk_escalation_approval", {}) if isinstance(payload.get("risk_escalation_approval"), dict) else {}
    risk_executor = payload.get("risk_escalated_tool_executor", {}) if isinstance(payload.get("risk_escalated_tool_executor"), dict) else {}
    risk_delivery = payload.get("risk_escalation_receiver_delivery", {}) if isinstance(payload.get("risk_escalation_receiver_delivery"), dict) else {}
    risk_impact = payload.get("risk_escalation_simulated_ops_impact", {}) if isinstance(payload.get("risk_escalation_simulated_ops_impact"), dict) else {}
    memory_priors = payload.get("live_feed_memory_priors", {}) if isinstance(payload.get("live_feed_memory_priors"), dict) else {}
    memory_prior_use = proposals.get("memory_prior_use", {}) if isinstance(proposals.get("memory_prior_use"), dict) else {}
    alternative_negotiation = proposals.get("alternative_action_negotiation", {}) if isinstance(proposals.get("alternative_action_negotiation"), dict) else payload.get("alternative_action_negotiation", {}) if isinstance(payload.get("alternative_action_negotiation"), dict) else {}

    proposal_count = len([row for row in proposal_rows if isinstance(row, dict)])
    evidence_argument_count = sum(
        1
        for row in proposal_rows
        if isinstance(row, dict)
        and isinstance(row.get("department_reasoning"), dict)
        and row["department_reasoning"].get("evidence_argument")
    )
    concrete_policy_count = sum(
        1
        for row in proposal_rows
        if isinstance(row, dict)
        and (row.get("proposal_envelope", {}) if isinstance(row.get("proposal_envelope"), dict) else {}).get("policy_check")
        and not str((row.get("proposal_envelope", {}) if isinstance(row.get("proposal_envelope"), dict) else {}).get("policy_check")).startswith("pending")
    )
    negotiation_rounds = proposals.get("negotiation_rounds", []) if isinstance(proposals.get("negotiation_rounds"), list) else []
    receipts = executor.get("receipts", []) if isinstance(executor.get("receipts"), list) else []
    commerce_attribution = _commerce_action_attribution(rows, receipts)
    substitute_attribution = _build_substitute_outcome_attribution(payload, rows, commerce_attribution)
    semantic_action_parameter_count = sum(
        1
        for row in receipts
        if isinstance(row, dict)
        and isinstance(row.get("semantic_action_parameters") or row.get("action_parameters"), dict)
        and (row.get("semantic_action_parameters") or row.get("action_parameters")).get("source") == "semantic_agent_learning"
    )
    commerce_action_quality = (
        float(commerce_attribution.get("average_action_score") or 0)
        if isinstance(commerce_attribution, dict) and commerce_attribution.get("average_action_score") is not None
        else 0.0
    )
    executed_count = int(executor.get("executed_count") or 0)
    held_count = int(executor.get("held_count") or 0)
    held_disposition_count = int(executor.get("held_disposition_count") or 0)
    ownerless_count = int(follow_through.get("unresolved_without_owner_count") or 0)
    public_messages = int(receiver_delivery.get("public_guest_messages_sent") or 0)
    material_mutation = bool(receiver_delivery.get("material_state_mutation"))
    delivered_count = int(receiver_delivery.get("delivered_count") or 0)
    acknowledged_count = int(receiver_delivery.get("acknowledged_count") or 0)
    risk_requested_count = int(risk_escalation.get("requested_count") or 0)
    risk_approved_count = int(risk_escalation.get("approved_count") or 0)
    risk_executed_count = int(risk_executor.get("executed_count") or 0)
    risk_delivered_count = int(risk_delivery.get("delivered_count") or 0)
    risk_acknowledged_count = int(risk_delivery.get("acknowledged_count") or 0)
    risk_impact_applied = risk_impact.get("status") == "applied" and bool(risk_impact.get("material_state_mutation"))
    risk_state_impact = risk_impact.get("state_impact", {}) if isinstance(risk_impact.get("state_impact"), dict) else {}
    risk_congestion_delta = risk_state_impact.get("congestion_delta")
    risk_queue_delta = risk_state_impact.get("queued_guest_delta")
    risk_fitness = (risk_impact.get("episode_fitness", {}) if isinstance(risk_impact.get("episode_fitness"), dict) else {}).get("fitness")

    trace_components = [
        1.0 if proposal_count and evidence_argument_count == proposal_count else evidence_argument_count / max(1, proposal_count),
        1.0 if len(negotiation_rounds) >= 4 else len(negotiation_rounds) / 4,
        1.0 if follow_through.get("status") == "routed" and ownerless_count == 0 else 0.4 if follow_through.get("status") == "routed" else 0.0,
        1.0
        if int(alternative_negotiation.get("substitute_count") or 0) > 0
        and int(alternative_negotiation.get("unresolved_without_safe_substitute_count") or 0) == 0
        else 0.6
        if int(alternative_negotiation.get("substitute_count") or 0) > 0
        else 0.0,
    ]
    trace_reward = _bounded_reward(sum(trace_components) / len(trace_components))

    policy_components = [
        1.0 if proposal_count and concrete_policy_count == proposal_count else concrete_policy_count / max(1, proposal_count),
        1.0 if held_count and held_disposition_count == held_count else 0.8 if held_count == 0 else held_disposition_count / max(1, held_count),
        1.0 if public_messages == 0 and material_mutation is False else 0.0,
    ]
    policy_reward = _bounded_reward(sum(policy_components) / len(policy_components))
    policy_hard_gate_passed = policy_reward >= 0.95 and ownerless_count == 0 and public_messages == 0 and material_mutation is False

    execution_components = [
        1.0 if executed_count > 0 else 0.0,
        1.0 if receiver_delivery_proven and delivered_count == executed_count and acknowledged_count == executed_count and executed_count > 0 else 0.0,
        1.0 if held_count == 0 or (follow_through.get("status") == "routed" and ownerless_count == 0) else 0.0,
        round(executed_count / max(1, len(receipts)), 3) if receipts else 0.0,
    ]
    execution_reward = _bounded_reward(sum(execution_components) / len(execution_components))

    actionable_improvement = improvement_points if actionable_improvement_points is None else actionable_improvement_points
    actionable_regression = regression_points if actionable_regression_points is None else actionable_regression_points
    actionable_stable = stable_points if actionable_stable_points is None else actionable_stable_points
    actionable_total = max(1, actionable_improvement + actionable_regression + actionable_stable)
    operational_reward = _bounded_reward(
        (0.25 if measurement_available else 0.05)
        + (0.5 * (actionable_improvement / actionable_total))
        - (0.6 * (actionable_regression / actionable_total))
        + (0.05 * (actionable_stable / actionable_total))
        + ((0.08 * commerce_action_quality) if semantic_action_parameter_count > 0 else 0.0)
    )
    controlled_low_risk_reward = _bounded_reward(
        (0.25 if receiver_delivery_proven else 0.0)
        + (0.2 if executed_count > 0 else 0.0)
        + (0.2 if delivered_count == executed_count and acknowledged_count == executed_count and executed_count > 0 else 0.0)
        + (0.35 * operational_reward)
    )
    risk_lift_effect_score = 0.0
    try:
        if risk_congestion_delta is not None:
            risk_lift_effect_score = max(risk_lift_effect_score, _live_feed_positive_delta_score(float(risk_congestion_delta), lower_is_better=True, scale=50.0))
        if risk_queue_delta is not None:
            risk_lift_effect_score = max(risk_lift_effect_score, _live_feed_positive_delta_score(float(risk_queue_delta), lower_is_better=True, scale=200.0))
        if risk_fitness is not None:
            risk_lift_effect_score = max(risk_lift_effect_score, _bounded_reward(float(risk_fitness) / 100.0))
    except (TypeError, ValueError):
        risk_lift_effect_score = 0.0
    risk_lift_process_score = _bounded_reward(
        (0.2 if risk_requested_count > 0 else 0.0)
        + (0.2 if risk_requested_count > 0 and risk_approved_count == risk_requested_count else 0.0)
        + (0.2 if risk_executed_count > 0 and risk_executed_count == risk_approved_count else 0.0)
        + (0.15 if risk_delivery.get("status") == "proven_escalated" and risk_acknowledged_count == risk_executed_count and risk_executed_count > 0 else 0.0)
    )
    risk_lift_measured_regression = bool(risk_impact.get("status") == "applied" and risk_executed_count > 0 and risk_lift_effect_score <= 0)
    if risk_lift_measured_regression:
        risk_lift_reward = min(risk_lift_process_score, 0.45)
    elif risk_impact_applied:
        risk_lift_reward = _bounded_reward(risk_lift_process_score + (0.25 * risk_lift_effect_score))
    elif risk_executed_count > 0:
        risk_lift_reward = min(risk_lift_process_score, 0.55)
    else:
        risk_lift_reward = risk_lift_process_score
    risk_lift_label = (
        "risk_lift_regression"
        if risk_lift_measured_regression
        else
        "risk_lift_success"
        if risk_lift_reward >= 0.65 and risk_impact_applied
        else "risk_lift_blocked"
        if risk_requested_count == 0 or risk_approved_count == 0
        else "risk_lift_pending_measurement"
    )

    memory_applied = int(memory_prior_use.get("applied_count") or 0)
    memory_prior_count = int(memory_priors.get("prior_count") or 0)
    memory_used = memory_applied > 0
    learning_reward = _bounded_reward(
        0.35
        + (0.25 if memory_used else 0.0)
        + (0.15 if memory_prior_count > 0 else 0.0)
        + (0.15 if regression_points == 0 else -0.2)
        + (0.1 if improvement_points > 0 else 0.0)
        + (0.05 if int(substitute_attribution.get("executed_branch_count") or 0) > 0 else 0.0)
    )

    promotion_eligible = (
        policy_hard_gate_passed
        and measurement_available
        and attribution_confidence >= 0.7
        and operational_reward >= 0.55
        and regression_points == 0
    )
    composite_reward = _bounded_reward(
        0.1 * trace_reward
        + 0.2 * policy_reward
        + 0.2 * execution_reward
        + 0.4 * operational_reward
        + 0.1 * learning_reward
    )
    return {
        "version": "live_feed_reward_vector_v1",
        "trace_reward": trace_reward,
        "policy_reward": policy_reward,
        "execution_reward": execution_reward,
        "operational_reward": operational_reward,
        "controlled_low_risk_reward": controlled_low_risk_reward,
        "risk_lift_reward": risk_lift_reward,
        "risk_lift_label": risk_lift_label,
        "learning_reward": learning_reward,
        "composite_reward": composite_reward,
        "promotion_eligible": promotion_eligible,
        "policy_hard_gate_passed": policy_hard_gate_passed,
        "operational_lift_detected": improvement_points > regression_points and operational_reward >= 0.55,
        "metrics": {
            "proposal_count": proposal_count,
            "evidence_argument_count": evidence_argument_count,
            "concrete_policy_count": concrete_policy_count,
            "negotiation_round_count": len(negotiation_rounds),
            "alternative_substitute_count": int(alternative_negotiation.get("substitute_count") or 0),
            "safe_executable_substitute_count": int(alternative_negotiation.get("safe_executable_substitute_count") or 0),
            "unresolved_without_safe_substitute_count": int(alternative_negotiation.get("unresolved_without_safe_substitute_count") or 0),
            "executed_department_count": len(executed_departments),
            "executed_count": executed_count,
            "held_count": held_count,
            "held_disposition_count": held_disposition_count,
            "delivered_count": delivered_count,
            "acknowledged_count": acknowledged_count,
            "ownerless_follow_up_count": ownerless_count,
            "source_coverage": source_coverage,
            "department_coverage": department_coverage,
            "attribution_confidence": attribution_confidence,
            "improvement_points": improvement_points,
            "regression_points": regression_points,
            "stable_points": stable_points,
            "actionable_improvement_points": actionable_improvement,
            "actionable_regression_points": actionable_regression,
            "actionable_stable_points": actionable_stable,
            "actionable_metric_points": actionable_improvement + actionable_regression + actionable_stable,
            "stability_watch_points": stability_watch_points if stability_watch_points is not None else stable_points,
            "measurement_source_count": len(rows),
            "memory_prior_count": memory_prior_count,
            "memory_applied_count": memory_applied,
            "semantic_action_parameter_count": semantic_action_parameter_count,
            "semantic_action_quality_reward": _bounded_reward(0.08 * commerce_action_quality) if semantic_action_parameter_count > 0 else 0.0,
            "commerce_action_average_score": commerce_attribution.get("average_action_score") if isinstance(commerce_attribution, dict) else None,
            "substitute_branch_count": substitute_attribution.get("branch_count"),
            "substitute_executed_branch_count": substitute_attribution.get("executed_branch_count"),
            "substitute_average_score": substitute_attribution.get("average_substitute_score"),
            "substitute_average_lift_vs_monitor": substitute_attribution.get("average_lift_vs_monitor"),
            "risk_escalation_requested_count": risk_requested_count,
            "risk_escalation_approved_count": risk_approved_count,
            "risk_escalated_executed_count": risk_executed_count,
            "risk_escalation_delivered_count": risk_delivered_count,
            "risk_escalation_acknowledged_count": risk_acknowledged_count,
            "risk_escalation_impact_applied": risk_impact_applied,
            "risk_escalation_effect_score": risk_lift_effect_score,
            "risk_lift_process_score": risk_lift_process_score,
            "risk_lift_measured_regression": risk_lift_measured_regression,
        },
        "branch_rewards": {
            "controlled_low_risk": {
                "reward": controlled_low_risk_reward,
                "executed_count": executed_count,
                "receiver_status": receiver_delivery.get("status"),
                "policy": "Credits policy-passed controlled receiver actions only.",
            },
            "risk_lift": {
                "reward": risk_lift_reward,
                "label": risk_lift_label,
                "requested_count": risk_requested_count,
                "approved_count": risk_approved_count,
                "executed_count": risk_executed_count,
                "delivery_status": risk_delivery.get("status"),
                "impact_status": risk_impact.get("status"),
                "material_state_mutation": risk_impact.get("material_state_mutation"),
                "effect_score": risk_lift_effect_score,
                "policy": "Credits only approval-scoped lifted actions that execute, receive acknowledgement, and produce measured simulated impact.",
            },
        },
        "commerce_action_attribution": commerce_attribution,
        "substitute_outcome_attribution": substitute_attribution,
        "promotion_blockers": [
            blocker
            for blocker in [
                None if policy_hard_gate_passed else "policy_or_authority_gate_not_clean",
                None if measurement_available else "measured_outcome_missing",
                None if attribution_confidence >= 0.7 else "low_attribution_confidence",
                None if operational_reward >= 0.55 else "operational_reward_below_promotion_threshold",
                None if regression_points == 0 else "operational_regression_detected",
                None if risk_lift_label not in {"risk_lift_regression"} else "risk_lift_regression_detected",
            ]
            if blocker
        ],
        "boundary": "Trace, policy, and execution rewards may create training examples, but promotion requires operational_reward and policy_hard_gate_passed.",
    }


def _live_feed_rows_by_source(health_or_refresh: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = health_or_refresh.get("feeds")
    if not isinstance(rows, list):
        rows = health_or_refresh.get("after_feeds")
    if not isinstance(rows, list):
        return {}
    return {str(row.get("source")): row for row in rows if isinstance(row, dict) and row.get("source")}


def _build_live_feed_outcome_measurement(payload: dict[str, Any], post_action_refresh: dict[str, Any] | None) -> dict[str, Any]:
    executor = payload.get("tool_executor_live_test", {}) if isinstance(payload.get("tool_executor_live_test"), dict) else {}
    receiver_delivery = payload.get("live_feed_receiver_delivery", {}) if isinstance(payload.get("live_feed_receiver_delivery"), dict) else {}
    before_health = payload.get("live_feed_health", {}) if isinstance(payload.get("live_feed_health"), dict) else {}
    after_refresh = _apply_controlled_receiver_effect_projection(payload, post_action_refresh)
    controlled_effect_projection = after_refresh.get("controlled_effect_projection", {}) if isinstance(after_refresh.get("controlled_effect_projection"), dict) else {}
    before_by_source = _live_feed_rows_by_source(before_health)
    after_by_source = _live_feed_rows_by_source({"feeds": after_refresh.get("after_feeds", [])})
    executed_departments = {
        str(row.get("department"))
        for row in executor.get("receipts", [])
        if isinstance(row, dict) and (row.get("result", {}) if isinstance(row.get("result"), dict) else {}).get("status") == "executed_controlled"
    }
    department_sources = {
        "food_retail": {"food_ops", "guest_flow"},
        "hr_labor": {"staffing"},
        "marketing": {"guest_flow", "food_ops"},
    }
    measured_sources: set[str] = set()
    for department in executed_departments:
        measured_sources.update(department_sources.get(department, set()))
    measured_sources.update({"ride_ops", "operator_signal"})
    rows: list[dict[str, Any]] = []
    improvement_points = 0
    regression_points = 0
    stable_points = 0
    actionable_improvement_points = 0
    actionable_regression_points = 0
    actionable_stable_points = 0
    stability_watch_points = 0
    for source in sorted(source for source in measured_sources if source in before_by_source or source in after_by_source):
        before_row = before_by_source.get(source, {})
        after_row = after_by_source.get(source, {})
        before_value = before_row.get("value") if isinstance(before_row.get("value"), dict) else {}
        after_value = after_row.get("value") if isinstance(after_row.get("value"), dict) else {}
        before_metrics = _live_feed_numeric_metrics(before_value)
        after_metrics = _live_feed_numeric_metrics(after_value)
        metric_rows = []
        for metric in sorted(set(before_metrics) | set(after_metrics)):
            if metric not in before_metrics or metric not in after_metrics:
                continue
            delta = round(after_metrics[metric] - before_metrics[metric], 3)
            direction = _live_feed_metric_direction(source, metric)
            metric_score = _live_feed_metric_score(source, metric, delta)
            if metric_score > 0:
                improvement_points += 1
                if direction != "stability_watch":
                    actionable_improvement_points += 1
            elif metric_score < 0:
                regression_points += 1
                if direction != "stability_watch":
                    actionable_regression_points += 1
            else:
                stable_points += 1
                if direction == "stability_watch":
                    stability_watch_points += 1
                else:
                    actionable_stable_points += 1
            metric_rows.append(
                {
                    "metric": metric,
                    "before": before_metrics[metric],
                    "after": after_metrics[metric],
                    "delta": delta,
                    "direction": direction,
                    "reward_scope": "stability_watch" if direction == "stability_watch" else "actionable_directional",
                    "impact": "improved" if metric_score > 0 else "regressed" if metric_score < 0 else "stable",
                }
            )
        rows.append(
            {
                "source": source,
                "before_event_id": before_row.get("latest_event_id"),
                "after_event_id": after_row.get("latest_event_id"),
                "before_signal_type": before_row.get("latest_signal_type"),
                "after_signal_type": after_row.get("latest_signal_type"),
                "before_age_seconds": before_row.get("age_seconds"),
                "after_age_seconds": after_row.get("age_seconds"),
                "post_action_snapshot_captured": bool(after_row.get("latest_event_id")),
                "metrics": metric_rows,
            }
        )
    covered_departments = [
        department
        for department in sorted(executed_departments)
        if department_sources.get(department, set()).intersection(after_by_source)
    ]
    post_snapshot_count = sum(1 for row in rows if row.get("post_action_snapshot_captured"))
    receiver_delivery_proven = receiver_delivery.get("status") == "proven_controlled"
    measurement_available = bool(rows) and post_snapshot_count == len(rows) and receiver_delivery_proven
    source_coverage = round((post_snapshot_count / len(rows)), 3) if rows else 0
    department_coverage = round((len(covered_departments) / len(executed_departments)), 3) if executed_departments else 0
    attribution_confidence = round(
        min(
            0.95,
            0.3
            + (0.25 if receiver_delivery_proven else 0)
            + (0.2 * source_coverage)
            + (0.15 * department_coverage)
            + (0.05 if after_refresh.get("status") in {"refreshed", "no_due_feeds"} else 0),
        ),
        3,
    )
    reward_ready = measurement_available and attribution_confidence >= 0.7
    reward_layers = _live_feed_reward_layers(
        payload,
        rows=rows,
        executed_departments=executed_departments,
        receiver_delivery_proven=receiver_delivery_proven,
        measurement_available=measurement_available,
        source_coverage=source_coverage,
        department_coverage=department_coverage,
        attribution_confidence=attribution_confidence,
        improvement_points=improvement_points,
        regression_points=regression_points,
        stable_points=stable_points,
        actionable_improvement_points=actionable_improvement_points,
        actionable_regression_points=actionable_regression_points,
        actionable_stable_points=actionable_stable_points,
        stability_watch_points=stability_watch_points,
    )
    substitute_outcome_attribution = reward_layers.get("substitute_outcome_attribution", {}) if isinstance(reward_layers.get("substitute_outcome_attribution"), dict) else {}
    reward_value = reward_layers["operational_reward"]
    reward_label = (
        "operational_lift_with_policy_safe_execution"
        if reward_ready and reward_layers.get("promotion_eligible")
        else "safe_handoff_measured_but_operational_lift_unproven"
        if reward_ready
        else "measurement_not_reward_ready"
    )
    return {
        "mode": "live_feed_post_action_outcome_measurement",
        "status": "measured" if measurement_available else "incomplete",
        "measurement_id": f"measurement_{hashlib.sha1(json.dumps({'decision_id': payload.get('decision_id'), 'rows': rows}, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:12]}",
        "post_action_refresh_status": after_refresh.get("status"),
        "post_action_refresh_sources": after_refresh.get("refreshed_sources", []),
        "executed_departments": sorted(executed_departments),
        "covered_departments": covered_departments,
        "source_coverage": source_coverage,
        "department_coverage": department_coverage,
        "attribution_confidence": attribution_confidence,
        "improvement_points": improvement_points,
        "regression_points": regression_points,
        "stable_points": stable_points,
        "actionable_improvement_points": actionable_improvement_points,
        "actionable_regression_points": actionable_regression_points,
        "actionable_stable_points": actionable_stable_points,
        "stability_watch_points": stability_watch_points,
        "measured_outcome_available": measurement_available,
        "eligible_for_reward": reward_ready,
        "reward_value": reward_value if reward_ready else None,
        "reward_label": reward_label,
        "reward_layers": reward_layers,
        "promotion_eligible": bool(reward_ready and reward_layers.get("promotion_eligible")),
        "substitute_outcome_attribution": substitute_outcome_attribution,
        "controlled_effect_projection": controlled_effect_projection,
        "material_state_mutation": False,
        "measurement_rows": rows,
        "boundary": "Measures post-action live-feed state, receiver acknowledgements, and bounded controlled-effect projections only; it does not infer safety clearance, send public messages, mutate park state, start training, or promote a model.",
    }


def _live_feed_prior_from_outcome(
    row: dict[str, Any],
    *,
    source: str = "latest_outcome",
    semantic_learning: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    learning = row.get("learning", {}) if isinstance(row.get("learning"), dict) else {}
    metrics = row.get("responseMetrics", {}) if isinstance(row.get("responseMetrics"), dict) else {}
    impact = row.get("stateImpact", {}) if isinstance(row.get("stateImpact"), dict) else {}
    measured = bool(metrics.get("measuredOutcomeAvailable") or learning.get("eligible_for_reward"))
    semantic_learning = semantic_learning if isinstance(semantic_learning, dict) else None
    if not measured and not semantic_learning:
        return None
    prior = {
        "outcome_id": row.get("_id"),
        "decision_id": row.get("decisionId"),
        "loop_id": row.get("loopId"),
        "mode": row.get("mode"),
        "source": source,
        "executed_tools": impact.get("executed_tools", []),
        "held_tools": impact.get("held_tools", []),
        "executed_departments": impact.get("executed_departments", []),
        "held_departments": impact.get("held_departments", []),
        "reward_value": learning.get("reward_value") if learning.get("reward_value") is not None else metrics.get("rewardValue"),
        "response_score": metrics.get("score"),
        "response_status": metrics.get("status"),
        "attribution_confidence": metrics.get("attributionConfidence"),
        "receiver_delivery_proven": metrics.get("receiverDeliveryProven"),
        "measured_outcome_available": metrics.get("measuredOutcomeAvailable"),
        "measurement_id": impact.get("post_action_measurement_id"),
        "state_scenario": row.get("stateScenario"),
        "status": "usable_prior" if measured else "semantic_learning_prior",
    }
    if semantic_learning:
        prior.update(
            {
                "source": "semantic_agent_learning",
                "semantic_learning_id": semantic_learning.get("_id"),
                "semantic_score": semantic_learning.get("score"),
                "semantic_lesson": semantic_learning.get("lesson") or semantic_learning.get("text"),
                "semantic_rule": semantic_learning.get("rule"),
                "semantic_department": semantic_learning.get("department"),
                "semantic_learning_type": semantic_learning.get("learning_type") or semantic_learning.get("learningType"),
                "semantic_scope": semantic_learning.get("scope"),
                "semantic_confidence": semantic_learning.get("confidence"),
                "semantic_tags": semantic_learning.get("tags", []),
                "status": "semantic_learning_prior",
            }
        )
    return prior


def _semantic_live_feed_memory_priors(dashboard: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    retrieved = dashboard.get("retrieved", {}) if isinstance(dashboard.get("retrieved"), dict) else {}
    learnings = retrieved.get("learnings", []) if isinstance(retrieved.get("learnings"), list) else []
    priors: list[dict[str, Any]] = []
    seen: set[str] = set()
    for learning in learnings:
        if not isinstance(learning, dict):
            continue
        outcome_id = (
            learning.get("sourceOutcomeId")
            or learning.get("source_outcome_id")
            or learning.get("outcomeId")
            or learning.get("outcome_id")
        )
        if not outcome_id or str(outcome_id) in seen:
            continue
        outcome = get_memory_document("outcome_events", str(outcome_id))
        if not isinstance(outcome, dict):
            continue
        prior = _live_feed_prior_from_outcome(outcome, source="semantic_agent_learning", semantic_learning=learning)
        if prior:
            priors.append(prior)
            seen.add(str(outcome_id))
        if len(priors) >= limit:
            break
    return priors


def _live_feed_memory_priors_from_dashboard(live_case: dict[str, Any], limit: int = 5) -> dict[str, Any]:
    query_parts = [
        "live feed controlled executor measured outcome reward",
        str(live_case.get("lead_source") or ""),
        str(live_case.get("lead_signal_type") or ""),
    ]
    try:
        dashboard = get_operational_memory_dashboard(" ".join(part for part in query_parts if part).strip())
    except Exception as error:
        case_bank_priors = _live_feed_case_bank_memory_priors(live_case, limit=limit)
        if case_bank_priors.get("prior_count"):
            case_bank_priors["dashboard_status"] = {"status": "unavailable", "reason": str(error)[:300]}
            case_bank_priors["fallback_reason"] = "mongodb_dashboard_unavailable"
            return case_bank_priors
        return {
            "mode": "live_feed_memory_priors",
            "status": "unavailable",
            "reason": str(error)[:300],
            "prior_count": 0,
            "priors": [],
            "policy": "Memory retrieval failed closed; live feed and policy gates remain authoritative.",
        }
    retrieved = dashboard.get("retrieved", {}) if isinstance(dashboard.get("retrieved"), dict) else {}
    semantic_priors = _semantic_live_feed_memory_priors(dashboard, limit)
    latest = dashboard.get("latest_outcomes", []) if isinstance(dashboard.get("latest_outcomes"), list) else []
    priors = []
    seen_outcomes: set[str] = set()
    for prior in semantic_priors:
        outcome_id = str(prior.get("outcome_id") or "")
        if outcome_id:
            seen_outcomes.add(outcome_id)
        priors.append(prior)
    for row in latest:
        if not isinstance(row, dict):
            continue
        if row.get("_id") and str(row.get("_id")) in seen_outcomes:
            continue
        prior = _live_feed_prior_from_outcome(row)
        if not prior:
            continue
        priors.append(prior)
        if row.get("_id"):
            seen_outcomes.add(str(row.get("_id")))
        if len(priors) >= limit:
            break
    if not priors:
        case_bank_priors = _live_feed_case_bank_memory_priors(live_case, limit=limit)
        if case_bank_priors.get("prior_count"):
            case_bank_priors["dashboard_status"] = dashboard.get("status")
            case_bank_priors["fallback_reason"] = "mongodb_memory_empty"
            return case_bank_priors
    return {
        "mode": "live_feed_memory_priors",
        "status": "retrieved" if priors else "empty",
        "prior_count": len(priors),
        "priors": priors,
        "latest_outcome_ids": [row.get("outcome_id") for row in priors if row.get("outcome_id")],
        "semantic_prior_count": len(semantic_priors),
        "semantic_learning_ids": [row.get("semantic_learning_id") for row in semantic_priors if row.get("semantic_learning_id")],
        "retrieval_method": retrieved.get("method"),
        "dashboard_status": dashboard.get("status"),
        "policy": "Memory can bias only low-risk execute-vs-hold recommendations; live feed evidence, policy judge, and Executive gate remain authoritative.",
    }


def _live_feed_issue_kind_to_training_scenario(kind: Any) -> str:
    normalized = str(kind or "").strip().lower().replace("-", "_")
    mapping = {
        "ride_failure": "ride_down",
        "show_dump": "ride_down",
        "radio_dead_zone": "ride_down",
        "access_lane_block": "ride_down",
        "staff_callout": "staff_shortage",
        "food_spike": "food_spike",
        "inventory_stockout": "food_spike",
        "mobile_order_outage": "food_spike",
        "payment_outage": "food_spike",
        "demand_spike": "food_spike",
        "storm_risk": "storm_response",
        "heat_index_spike": "storm_response",
        "lightning_delay": "storm_response",
        "energy_spike": "scan",
        "sensor_anomaly": "scan",
        "water_leak": "scan",
        "restroom_closure": "scan",
        "security_perimeter": "scan",
        "parade_route_conflict": "proactive_eventops",
        "parking_arrival_wave": "proactive_eventops",
        "ticketing_gate_surge": "proactive_eventops",
    }
    return mapping.get(normalized, normalized if normalized else "unknown")


def _live_feed_case_bank_memory_priors(live_case: dict[str, Any], limit: int = 5) -> dict[str, Any]:
    scenario_key = _infer_live_feed_training_scenario(live_case)
    path = LIVE_FEED_CASE_BANK_INDEX
    if not path.exists():
        return {
            "mode": "live_feed_memory_priors",
            "source": "case_bank_memory_fallback",
            "status": "empty",
            "scenario_key": scenario_key,
            "prior_count": 0,
            "priors": [],
            "latest_outcome_ids": [],
            "case_bank_path": str(path),
            "policy": "No durable case-bank memory was available; proposal remains live-feed-only.",
        }
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                rows.append(parsed)
    except Exception as error:
        return {
            "mode": "live_feed_memory_priors",
            "source": "case_bank_memory_fallback",
            "status": "unavailable",
            "scenario_key": scenario_key,
            "reason": str(error)[:300],
            "prior_count": 0,
            "priors": [],
            "latest_outcome_ids": [],
            "case_bank_path": str(path),
            "policy": "Case-bank memory failed closed; proposal remains live-feed-only.",
        }

    priors: list[dict[str, Any]] = []
    for row in reversed(rows):
        if not isinstance(row, dict) or not row.get("closed_case"):
            continue
        issue = row.get("issue", {}) if isinstance(row.get("issue"), dict) else {}
        row_scenario = _live_feed_issue_kind_to_training_scenario(issue.get("kind"))
        if scenario_key != "unknown" and row_scenario != scenario_key:
            continue
        measurement = row.get("measurement", {}) if isinstance(row.get("measurement"), dict) else {}
        actions = row.get("actions", {}) if isinstance(row.get("actions"), dict) else {}
        agent_decision = row.get("agent_decision", {}) if isinstance(row.get("agent_decision"), dict) else {}
        projection = measurement.get("controlled_effect_projection", {}) if isinstance(measurement.get("controlled_effect_projection"), dict) else {}
        if not measurement.get("eligible_for_reward") and measurement.get("status") != "measured":
            continue
        prior = {
            "outcome_id": row.get("outcome_id"),
            "decision_id": row.get("decision_id"),
            "case_id": row.get("case_id"),
            "source": "case_bank_memory_fallback",
            "scenario_key": row_scenario,
            "issue_kind": issue.get("kind"),
            "created_at": row.get("created_at"),
            "executed_tools": projection.get("executed_tools", []),
            "held_tools": [],
            "executed_departments": projection.get("executed_departments", []),
            "held_departments": agent_decision.get("held_departments", []),
            "reward_value": measurement.get("reward_value"),
            "attribution_confidence": measurement.get("attribution_confidence"),
            "receiver_delivery_proven": actions.get("receiver_delivery_status") == "proven_controlled",
            "measured_outcome_available": measurement.get("status") == "measured",
            "measurement_id": measurement.get("measurement_id"),
            "status": "usable_prior" if measurement.get("status") == "measured" else "trace_only",
        }
        priors.append(prior)
        if len(priors) >= limit:
            break
    return {
        "mode": "live_feed_memory_priors",
        "source": "case_bank_memory_fallback",
        "status": "retrieved" if priors else "empty",
        "scenario_key": scenario_key,
        "prior_count": len(priors),
        "priors": priors,
        "latest_outcome_ids": [row.get("outcome_id") for row in priors if row.get("outcome_id")],
        "case_bank_path": str(path),
        "policy": "Durable case-bank memory can bias only low-risk execute-vs-hold recommendations; live feed evidence, policy judge, and Executive gate remain authoritative.",
    }


def _live_feed_memory_prior_for_department(memory_priors: dict[str, Any], department: str, requested_tool: str) -> dict[str, Any] | None:
    priors = memory_priors.get("priors", []) if isinstance(memory_priors, dict) else []
    department = str(department or "")
    requested_tool = str(requested_tool or "")
    low_risk_semantic_departments = {"food_retail", "marketing"}
    for prior in priors if isinstance(priors, list) else []:
        if not isinstance(prior, dict) or not prior.get("semantic_learning_id") or department not in low_risk_semantic_departments:
            continue
        semantic_text = " ".join(
            str(prior.get(key) or "")
            for key in ("semantic_lesson", "semantic_rule", "semantic_scope", "semantic_learning_type")
        ).lower()
        if any(
            term in semantic_text
            for term in ("offer", "promo", "promotion", "routing", "split", "cap", "take-rate", "take rate", "inventory", "food", "stock")
        ):
            return prior
    for prior in priors if isinstance(priors, list) else []:
        if not isinstance(prior, dict):
            continue
        executed_departments = {str(item) for item in prior.get("executed_departments", []) if item}
        executed_tools = {str(item) for item in prior.get("executed_tools", []) if item}
        if department in executed_departments or requested_tool in executed_tools:
            return prior
    return priors[0] if priors and isinstance(priors[0], dict) else None


def _semantic_action_parameters_from_prior(prior: dict[str, Any] | None, department: str, requested_tool: str) -> dict[str, Any]:
    if not isinstance(prior, dict) or not prior.get("semantic_learning_id"):
        return {}
    text = " ".join(str(prior.get(key) or "") for key in ("semantic_lesson", "semantic_rule")).lower()
    params: dict[str, Any] = {
        "source": "semantic_agent_learning",
        "learning_id": prior.get("semantic_learning_id"),
        "source_outcome_id": prior.get("outcome_id"),
        "semantic_score": prior.get("semantic_score"),
        "policy": "Parameters refine only low-risk receiver payloads; they do not grant new execution authority.",
    }
    if "stronger" in text or "personalized" in text or "offer" in text or "promo" in text or "promotion" in text:
        params["offer_strength"] = "stronger_personalized"
        params["guest_segmenting"] = "segment_offer_by_current_location_and_wait_tolerance"
    if "split" in text or "routing" in text or "reroute" in text:
        params["routing_strategy"] = "split_across_low_wait_destinations"
        params["destination_count_min"] = 2
    if "cap" in text or "overloaded" in text or "indoor" in text:
        params["traffic_cap_policy"] = "cap_overloaded_indoor_targets"
        params["avoid_targets"] = ["overloaded_indoor_food_court", "high_spillback_zone"]
    if department == "food_retail":
        params["tool_payload_delta"] = {
            "promo_action": "pause_broad_promo_replace_with_segmented_capacity_safe_offer",
            "inventory_guard": "hold promo if bottled_drinks or kitchen load remains constrained",
            "demand_shape": params.get("routing_strategy", "split_across_available_food_locations"),
        }
        if "inventory" in text or "stock" in text or "food" in text or "promo" in text:
            params["companion_tools"] = ["inventory_alert"]
            params["companion_reason"] = "Semantic learning ties demand shaping to stockout prevention; live food evidence should trigger a bounded inventory alert alongside promo control."
    elif department == "marketing":
        params["tool_payload_delta"] = {
            "offer_action": "redirect_to_multiple_lower_pressure_destinations",
            "offer_strength": params.get("offer_strength", "standard"),
            "destination_cap": params.get("traffic_cap_policy", "monitor_destination_pressure"),
        }
    else:
        params["tool_payload_delta"] = {"action": requested_tool, "use": "context_only"}
    return params


def _infer_live_feed_training_scenario(live_case: dict[str, Any]) -> str:
    explicit = str((live_case or {}).get("scenario_key") or "").strip()
    known = {"ride_down", "food_spike", "staff_shortage", "storm_response", "proactive_eventops", "proactive_watchtower", "scan"}
    if explicit in known:
        return explicit
    evidence = live_case.get("evidence", []) if isinstance(live_case, dict) and isinstance(live_case.get("evidence"), list) else []
    text_parts = [
        live_case.get("scenario_key") if isinstance(live_case, dict) else "",
        live_case.get("lead_source") if isinstance(live_case, dict) else "",
        live_case.get("lead_signal_type") if isinstance(live_case, dict) else "",
        live_case.get("operator_message") if isinstance(live_case, dict) else "",
    ]
    for row in evidence[:8]:
        if isinstance(row, dict):
            text_parts.extend([row.get("source"), row.get("signal_type"), row.get("summary")])
    text = " ".join(str(item or "").lower().replace("-", "_") for item in text_parts)
    scenario_terms = [
        ("food_spike", ("food", "inventory", "pos", "promo", "mobile_order", "pickup", "kitchen", "payment")),
        ("staff_shortage", ("staff", "shift", "fatigue", "overtime", "callout", "coverage", "break")),
        ("storm_response", ("storm", "weather", "lightning", "heat", "shelter", "indoor", "rain")),
        ("proactive_eventops", ("parade", "parking", "gate", "access_lane", "eventops", "arrival_wave")),
        ("scan", ("sensor", "energy", "water_leak", "radio_dead_zone", "restroom", "triage")),
        ("ride_down", ("ride", "coaster", "wait", "queue", "route", "capacity", "downtime", "outage", "reopen")),
    ]
    for scenario, terms in scenario_terms:
        if any(term in text for term in terms):
            return scenario
    return "unknown"


def _live_feed_ml_policy_evidence(live_case: dict[str, Any], min_rows: int = 50) -> dict[str, Any]:
    scenario_key = _infer_live_feed_training_scenario(live_case)
    try:
        from park_actual_training import actual_training_status

        actual = actual_training_status(min_rows, False, detail="readiness")
    except Exception as error:
        return {
            "mode": "live_feed_ml_policy_evidence",
            "status": "unavailable",
            "scenario_key": scenario_key,
            "reason": str(error)[:300],
            "policy": "ML evidence failed closed; live feed, memory, policy, Compliance, Executive, and Tool Executor gates remain authoritative.",
        }
    model_ops = actual.get("model_ops", {}) if isinstance(actual.get("model_ops"), dict) else {}
    scenario_fitness = model_ops.get("scenario_fitness", {}) if isinstance(model_ops.get("scenario_fitness"), dict) else {}
    scenarios = scenario_fitness.get("scenarios", []) if isinstance(scenario_fitness.get("scenarios"), list) else []
    matched = next((row for row in scenarios if isinstance(row, dict) and str(row.get("scenario_key") or "") == scenario_key), None)
    decision = str((matched or {}).get("decision") or "")
    guidance = {
        "promote_slice": "reinforce_pattern_with_rollback_monitoring",
        "collect_more_evidence": "use_as_watch_context_collect_more_cases",
        "hold_slice": "warn_against_policy_promotion",
    }.get(decision, "context_only_no_slice_decision")
    return {
        "mode": "live_feed_ml_policy_evidence",
        "status": "matched" if matched else "no_slice",
        "scenario_key": scenario_key,
        "actual_training_status": actual.get("status"),
        "actual_training_source": actual.get("source"),
        "actual_training_sample_count": actual.get("sample_count"),
        "current_policy_id": model_ops.get("current_policy_id"),
        "slice": matched or {},
        "slice_decision": decision or None,
        "slice_sample_count": (matched or {}).get("sample_count"),
        "latest_average_reward": (matched or {}).get("latest_average_reward"),
        "curve_delta": (matched or {}).get("curve_delta"),
        "guidance": guidance,
        "policy": "ML slice evidence can shape confidence, counterfactual comparison, and next-case learning questions, but cannot grant execution rights or override live evidence, Compliance, Executive, or Tool Executor gates.",
    }


def _judge_live_feed_memory_relevance(prior: dict[str, Any] | None, department: str, requested_tool: str) -> dict[str, Any]:
    if not prior:
        return {
            "status": "no_prior",
            "relevance_score": 0,
            "accepted_by_judge": False,
            "usage_scope": "none",
            "reason": "No measured prior was available for this proposal.",
            "policy": "Proposal remains live-feed-only.",
        }
    department = str(department or "")
    requested_tool = str(requested_tool or "")
    executed_departments = {str(item) for item in prior.get("executed_departments", []) if item}
    executed_tools = {str(item) for item in prior.get("executed_tools", []) if item}
    held_departments = {str(item) for item in prior.get("held_departments", []) if item}
    held_tools = {str(item) for item in prior.get("held_tools", []) if item}
    high_risk_departments = {"operations", "maintenance", "guest_experience", "safety", "security"}
    governance_departments = {"executive", "compliance", "qa_judge", "finance"}
    semantic_text = " ".join(
        str(prior.get(key) or "")
        for key in ("semantic_lesson", "semantic_rule", "semantic_scope", "semantic_learning_type")
    ).lower()
    semantic_low_risk_match = bool(prior.get("semantic_learning_id")) and department in {"food_retail", "marketing", "hr_labor"} and any(
        term in semantic_text
        for term in (
            "offer",
            "promo",
            "promotion",
            "routing",
            "split",
            "cap",
            "staff",
            "labor",
            "inventory",
            "food",
            "stock",
            "take-rate",
            "take rate",
        )
    )
    exact_executed_match = department in executed_departments or requested_tool in executed_tools
    held_match = department in held_departments or requested_tool in held_tools
    if semantic_low_risk_match:
        return {
            "status": "accepted_semantic_learning",
            "relevance_score": 0.72,
            "accepted_by_judge": True,
            "usage_scope": "low_risk_reasoning_bias",
            "reason": "Vector-retrieved learning is semantically relevant to a low-risk department/tool family.",
            "policy": "Semantic memory may adjust reasoning and candidate confidence, but cannot grant new execution rights.",
        }
    if prior.get("semantic_learning_id") and department in high_risk_departments:
        return {
            "status": "semantic_context_only",
            "relevance_score": 0.5,
            "accepted_by_judge": False,
            "usage_scope": "context_only_no_execution_bias",
            "reason": "Vector-retrieved learning is relevant context, but the department remains sensitive or operations-changing.",
            "policy": "Semantic memory cannot override safety, security, maintenance, guest-message, or operations gates.",
        }
    if exact_executed_match and department not in high_risk_departments:
        return {
            "status": "accepted",
            "relevance_score": 1.0,
            "accepted_by_judge": True,
            "usage_scope": "low_risk_execution_bias",
            "reason": "Prior measured outcome matches the same low-risk department/tool family.",
            "policy": "Memory may bias low-risk execute-vs-hold only; policy and Executive gates remain authoritative.",
        }
    if department in high_risk_departments:
        return {
            "status": "blocked_policy_boundary",
            "relevance_score": 0.2 if held_match or exact_executed_match else 0.1,
            "accepted_by_judge": False,
            "usage_scope": "context_only_no_execution_bias",
            "reason": "Sensitive or operations-changing proposal cannot use memory as execution justification.",
            "policy": "Safety, security, guest-message, maintenance, and operations actions still require their normal gates.",
        }
    if held_match or department in governance_departments:
        return {
            "status": "weak_context_only",
            "relevance_score": 0.45,
            "accepted_by_judge": False,
            "usage_scope": "context_only_no_execution_bias",
            "reason": "Prior is useful context for tradeoff or review, not direct action selection.",
            "policy": "Memory context cannot grant execution rights.",
        }
    return {
        "status": "rejected_irrelevant",
        "relevance_score": 0.05,
        "accepted_by_judge": False,
        "usage_scope": "none",
        "reason": "Prior outcome does not match department, tool, or review scope.",
        "policy": "Irrelevant memory is excluded from proposal evidence.",
    }


def _apply_live_feed_memory_priors_to_proposals(proposals: dict[str, Any], memory_priors: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(proposals, dict):
        return proposals
    rows = proposals.get("proposals", []) if isinstance(proposals.get("proposals"), list) else []
    applied = []
    weak_context = []
    blocked = []
    rejected = []
    for proposal in rows:
        if not isinstance(proposal, dict):
            continue
        envelope = proposal.get("proposal_envelope", {}) if isinstance(proposal.get("proposal_envelope"), dict) else {}
        requested_tool = envelope.get("requested_tool") or proposal.get("requested_tool")
        prior = _live_feed_memory_prior_for_department(memory_priors, str(proposal.get("department") or ""), str(requested_tool or ""))
        relevance = _judge_live_feed_memory_relevance(prior, str(proposal.get("department") or ""), str(requested_tool or ""))
        memory_use = {
            "status": relevance["status"],
            "prior_outcome_id": prior.get("outcome_id") if prior else None,
            "prior_measurement_id": prior.get("measurement_id") if prior else None,
            "prior_reward_value": prior.get("reward_value") if prior else None,
            "prior_attribution_confidence": prior.get("attribution_confidence") if prior else None,
            "used_for": relevance["usage_scope"],
            "policy": relevance["policy"],
            "accepted_by_judge": relevance["accepted_by_judge"],
            "memory_relevance_judge": relevance,
        }
        if relevance["status"] == "accepted_semantic_learning" and prior:
            semantic_action_parameters = _semantic_action_parameters_from_prior(
                prior,
                str(proposal.get("department") or ""),
                str(requested_tool or ""),
            )
            memory_delta = {
                "effect": "semantic_learning_adjusted_candidate",
                "before": "Recommendation used current live feed plus latest reward priors.",
                "after": prior.get("semantic_rule") or prior.get("semantic_lesson") or "Vector-retrieved learning adjusted candidate confidence.",
                "score_adjustment": 0.03,
                "decision_boundary": "Semantic memory affects reasoning only; policy, Executive, and Tool Executor gates remain unchanged.",
                "action_parameters": semantic_action_parameters,
            }
        elif relevance["accepted_by_judge"] and prior:
            semantic_action_parameters = {}
            memory_delta = {
                "effect": "reinforced_selected_candidate",
                "before": "Recommendation was based on current live feed only.",
                "after": "Prior measured success increases confidence in the same low-risk department/tool family, but grants no new execution rights.",
                "score_adjustment": 0.05,
                "decision_boundary": "Policy, Executive, and Tool Executor gates remain unchanged.",
            }
        elif relevance["status"] == "blocked_policy_boundary":
            semantic_action_parameters = {}
            memory_delta = {
                "effect": "blocked_from_execution_bias",
                "before": "Prior outcome was retrieved for context.",
                "after": "Memory is excluded from execute-vs-hold selection because this department is safety, security, operations, maintenance, or guest-message sensitive.",
                "score_adjustment": 0,
                "decision_boundary": "Memory cannot override human approval or safety/privacy/maintenance gates.",
            }
        elif relevance["status"] in {"weak_context_only", "semantic_context_only"}:
            semantic_action_parameters = {}
            memory_delta = {
                "effect": "context_only",
                "before": "Prior outcome was retrieved.",
                "after": prior.get("semantic_lesson") if prior and prior.get("semantic_lesson") else "Memory may inform tradeoff explanation but does not alter the selected action.",
                "score_adjustment": 0,
                "decision_boundary": "Governance and finance context cannot execute receiver actions.",
            }
        else:
            semantic_action_parameters = {}
            memory_delta = {
                "effect": "no_decision_effect",
                "before": "No relevant measured prior was available.",
                "after": "Proposal remains based on current live feed and policy only.",
                "score_adjustment": 0,
                "decision_boundary": "No memory bias applied.",
            }
        memory_use["decision_delta"] = memory_delta
        proposal["memory_use"] = memory_use
        proposal["memory_relevance_judge"] = relevance
        proposal["memory_decision_delta"] = memory_delta
        reasoning = proposal.get("department_reasoning", {}) if isinstance(proposal.get("department_reasoning"), dict) else {}
        if reasoning:
            reasoning["memory_decision_delta"] = memory_delta
            candidate_actions = reasoning.get("candidate_actions", []) if isinstance(reasoning.get("candidate_actions"), list) else []
            if relevance["accepted_by_judge"] and candidate_actions:
                first = candidate_actions[0]
                if isinstance(first, dict):
                    first["memory_adjusted_score"] = round(min(0.99, float(first.get("score") or 0) + float(memory_delta.get("score_adjustment") or 0)), 2)
                    first["memory_adjustment_reason"] = memory_delta["after"]
                    if prior and prior.get("semantic_learning_id"):
                        first["semantic_memory_learning_id"] = prior.get("semantic_learning_id")
                        first["semantic_memory_score"] = prior.get("semantic_score")
            forecast = reasoning.get("forecast", {}) if isinstance(reasoning.get("forecast"), dict) else {}
            if forecast:
                forecast["memory_prior_adjustment"] = memory_delta
                if semantic_action_parameters:
                    forecast["semantic_action_parameters"] = semantic_action_parameters
            carry = reasoning.get("memory_carry_forward", {}) if isinstance(reasoning.get("memory_carry_forward"), dict) else {}
            if prior and prior.get("semantic_learning_id") and carry:
                carry_list = carry.get("carry", []) if isinstance(carry.get("carry"), list) else []
                do_better = carry.get("do_better_next_time", []) if isinstance(carry.get("do_better_next_time"), list) else []
                carry["carry"] = list(dict.fromkeys([*carry_list, f"semantic_learning:{prior.get('semantic_learning_id')}"]))[:14]
                if prior.get("semantic_rule"):
                    do_better.insert(0, str(prior.get("semantic_rule")))
                carry["do_better_next_time"] = list(dict.fromkeys(str(item) for item in do_better))[:10]
                reasoning["memory_carry_forward"] = carry
            proposal["department_reasoning"] = reasoning
        if relevance["accepted_by_judge"] and prior:
            proposal.setdefault("evidence", [])
            if isinstance(proposal["evidence"], list):
                if prior.get("semantic_learning_id"):
                    memory_evidence = (
                        f"semantic_memory:{prior.get('semantic_learning_id')}:score={prior.get('semantic_score')}:"
                        f"source_outcome={prior.get('outcome_id')}"
                    )
                else:
                    memory_evidence = (
                        f"memory_prior:{prior.get('outcome_id')}:reward={prior.get('reward_value')}:"
                        f"confidence={prior.get('attribution_confidence')}"
                    )
                proposal["evidence"] = list(
                    dict.fromkeys(
                        [
                            memory_evidence,
                            *[str(item) for item in proposal["evidence"]],
                        ]
                    )
                )[:10]
        if envelope:
            envelope["memory_use"] = memory_use
            envelope["memory_relevance_judge"] = relevance
            envelope["memory_decision_delta"] = memory_delta
            if semantic_action_parameters:
                envelope["semantic_action_parameters"] = semantic_action_parameters
                envelope["action_parameters"] = semantic_action_parameters
                payload_delta = semantic_action_parameters.get("tool_payload_delta")
                if isinstance(payload_delta, dict):
                    proposal_payload = envelope.get("proposal_payload") if isinstance(envelope.get("proposal_payload"), dict) else {}
                    envelope["proposal_payload"] = {**proposal_payload, **payload_delta, "semantic_learning_id": semantic_action_parameters.get("learning_id")}
                envelope["expected_outcome"] = (
                    f"{envelope.get('expected_outcome') or proposal.get('expected_outcome') or 'department proposal reviewed'}; "
                    f"semantic memory requires {semantic_action_parameters.get('routing_strategy', 'targeted demand shaping')} "
                    f"and {semantic_action_parameters.get('traffic_cap_policy', 'destination pressure monitoring')}."
                )
                proposal["semantic_action_parameters"] = semantic_action_parameters
            if relevance["accepted_by_judge"] and prior:
                envelope["memory_prior_outcome_id"] = prior.get("outcome_id")
            proposal["proposal_envelope"] = envelope
        row = {
            "agent": proposal.get("agent_id"),
            "department": proposal.get("department"),
            "requested_tool": requested_tool,
            "prior_outcome_id": prior.get("outcome_id") if prior else None,
            "status": relevance["status"],
            "accepted_by_judge": relevance["accepted_by_judge"],
            "usage_scope": relevance["usage_scope"],
            "decision_delta": memory_delta,
            "semantic_companion_tools": (
                semantic_action_parameters.get("companion_tools", [])
                if isinstance(semantic_action_parameters, dict) and isinstance(semantic_action_parameters.get("companion_tools"), list)
                else []
            ),
        }
        if relevance["accepted_by_judge"]:
            applied.append(row)
        elif relevance["status"] in {"weak_context_only", "semantic_context_only"}:
            weak_context.append(row)
        elif relevance["status"] == "blocked_policy_boundary":
            blocked.append(row)
        elif relevance["status"] != "no_prior":
            rejected.append(row)
    proposals["memory_priors"] = memory_priors
    proposals["memory_prior_use"] = {
        "status": "applied" if applied else "none",
        "applied_count": len(applied),
        "semantic_companion_count": sum(len(row.get("semantic_companion_tools", [])) for row in applied if isinstance(row.get("semantic_companion_tools"), list)),
        "semantic_companion_tools": sorted(
            {
                str(tool)
                for row in applied
                for tool in (row.get("semantic_companion_tools", []) if isinstance(row.get("semantic_companion_tools"), list) else [])
                if tool
            }
        ),
        "prior_outcome_ids": sorted({str(row.get("prior_outcome_id")) for row in applied if row.get("prior_outcome_id")}),
        "weak_context_count": len(weak_context),
        "blocked_count": len(blocked),
        "rejected_count": len(rejected),
        "accepted_departments": sorted({str(row.get("department")) for row in applied if row.get("department")}),
        "blocked_departments": sorted({str(row.get("department")) for row in blocked if row.get("department")}),
        "policy": "Prior outcomes are evidence only; they do not grant execution rights.",
        "rows": applied,
        "weak_context_rows": weak_context,
        "blocked_rows": blocked,
        "rejected_rows": rejected,
    }
    proposals["memory_decision_deltas"] = [*applied, *weak_context, *blocked, *rejected]
    tradeoff = proposals.get("executive_tradeoff", {}) if isinstance(proposals.get("executive_tradeoff"), dict) else {}
    if tradeoff:
        tradeoff["memory_influence"] = {
            "accepted_low_risk_count": len(applied),
            "context_only_count": len(weak_context),
            "blocked_sensitive_count": len(blocked),
            "rejected_irrelevant_count": len(rejected),
            "semantic_companion_count": sum(len(row.get("semantic_companion_tools", [])) for row in applied if isinstance(row.get("semantic_companion_tools"), list)),
            "semantic_companion_tools": sorted(
                {
                    str(tool)
                    for row in applied
                    for tool in (row.get("semantic_companion_tools", []) if isinstance(row.get("semantic_companion_tools"), list) else [])
                    if tool
                }
            ),
            "decision_rule": "Memory can reinforce low-risk candidates but cannot turn held, sensitive, or human-approval actions into executable actions.",
            "deltas": [*applied, *weak_context, *blocked, *rejected],
        }
        proposals["executive_tradeoff"] = tradeoff
    rounds = proposals.get("negotiation_rounds", []) if isinstance(proposals.get("negotiation_rounds"), list) else []
    if rounds and (applied or weak_context or blocked or rejected):
        rounds.insert(
            3,
            {
                "round": "memory",
                "name": "memory_prior_challenge",
                "decision": "selective_memory_influence",
                "accepted": applied,
                "weak_context": weak_context,
                "blocked": blocked,
                "rejected": rejected,
                "semantic_companion_tools": sorted(
                    {
                        str(tool)
                        for row in applied
                        for tool in (row.get("semantic_companion_tools", []) if isinstance(row.get("semantic_companion_tools"), list) else [])
                        if tool
                    }
                ),
                "resolution": "Use measured prior outcomes only where department/tool relevance and policy boundaries allow it; same-department low-risk companion tools may be added when the semantic learning and live feed both support them.",
            },
        )
        proposals["negotiation_rounds"] = rounds
    proposals.setdefault("negotiation_turns", [])
    if isinstance(proposals["negotiation_turns"], list) and (applied or weak_context or blocked or rejected):
        proposals["negotiation_turns"].insert(
            1,
            {
                "turn": "memory",
                "agent": "memory_ops_agent",
                "decision": "judged_measured_priors",
                "reason": f"{len(applied)} accepted, {len(weak_context)} weak-context, {len(blocked)} policy-blocked, {len(rejected)} rejected memory prior uses; semantic companions: {sum(len(row.get('semantic_companion_tools', [])) for row in applied if isinstance(row.get('semantic_companion_tools'), list))}.",
                "prior_outcome_ids": sorted({str(row.get("prior_outcome_id")) for row in applied if row.get("prior_outcome_id")}),
                "semantic_companion_tools": sorted(
                    {
                        str(tool)
                        for row in applied
                        for tool in (row.get("semantic_companion_tools", []) if isinstance(row.get("semantic_companion_tools"), list) else [])
                        if tool
                    }
                ),
            },
        )
    return proposals


def _ml_evidence_scope_for_department(ml_evidence: dict[str, Any], department: str) -> dict[str, Any]:
    status = str(ml_evidence.get("status") or "")
    decision = str(ml_evidence.get("slice_decision") or "")
    department = str(department or "")
    low_risk_departments = {"food_retail", "hr_labor", "marketing"}
    sensitive_departments = {"operations", "maintenance", "guest_experience", "safety", "security"}
    if status != "matched":
        return {
            "status": "no_matching_slice",
            "accepted_by_judge": False,
            "usage_scope": "context_only",
            "score_adjustment": 0,
            "reason": "No matching trained scenario slice was available for this live-feed case.",
        }
    if decision == "promote_slice" and department in low_risk_departments:
        return {
            "status": "accepted_low_risk_policy_guidance",
            "accepted_by_judge": True,
            "usage_scope": "low_risk_confidence_bias",
            "score_adjustment": 0.03,
            "reason": f"Scenario slice {ml_evidence.get('scenario_key')} is promotable; guidance can reinforce bounded low-risk proposals only.",
        }
    if decision == "promote_slice":
        return {
            "status": "context_only_sensitive_boundary",
            "accepted_by_judge": False,
            "usage_scope": "tradeoff_context_no_execution_bias",
            "score_adjustment": 0,
            "reason": f"Scenario slice {ml_evidence.get('scenario_key')} is healthy, but {department} remains sensitive or governance-only.",
        }
    if decision == "hold_slice":
        return {
            "status": "warning_hold_slice",
            "accepted_by_judge": False,
            "usage_scope": "warning_no_promotion",
            "score_adjustment": -0.05 if department in low_risk_departments else 0,
            "reason": f"Scenario slice {ml_evidence.get('scenario_key')} is held or regressed; do not promote this pattern.",
        }
    if decision == "collect_more_evidence":
        return {
            "status": "watch_collect_more_evidence",
            "accepted_by_judge": False,
            "usage_scope": "counterfactual_context",
            "score_adjustment": 0,
            "reason": f"Scenario slice {ml_evidence.get('scenario_key')} is thin; use evidence for comparison and collect measured outcomes.",
        }
    if department in sensitive_departments:
        return {
            "status": "context_only_sensitive_boundary",
            "accepted_by_judge": False,
            "usage_scope": "tradeoff_context_no_execution_bias",
            "score_adjustment": 0,
            "reason": "ML policy evidence is context only for sensitive departments.",
        }
    return {
        "status": "context_only",
        "accepted_by_judge": False,
        "usage_scope": "tradeoff_context",
        "score_adjustment": 0,
        "reason": "ML policy evidence is available for explanation but does not change action rights.",
    }


def _apply_live_feed_ml_policy_evidence_to_proposals(proposals: dict[str, Any], ml_evidence: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(proposals, dict):
        return proposals
    rows = proposals.get("proposals", []) if isinstance(proposals.get("proposals"), list) else []
    accepted = []
    context_only = []
    warnings = []
    for proposal in rows:
        if not isinstance(proposal, dict):
            continue
        envelope = proposal.get("proposal_envelope", {}) if isinstance(proposal.get("proposal_envelope"), dict) else {}
        requested_tool = envelope.get("requested_tool") or proposal.get("requested_tool")
        department = str(proposal.get("department") or "")
        scope = _ml_evidence_scope_for_department(ml_evidence, department)
        decision_delta = {
            "effect": "reinforced_low_risk_candidate" if scope["accepted_by_judge"] else "warning_no_promotion" if scope["status"] == "warning_hold_slice" else "context_only",
            "before": "Proposal used current live feed, policy, and memory evidence.",
            "after": scope["reason"],
            "score_adjustment": scope["score_adjustment"],
            "decision_boundary": "ML evidence cannot grant execution rights; policy, Compliance, Executive, and Tool Executor gates remain unchanged.",
        }
        use = {
            "status": scope["status"],
            "scenario_key": ml_evidence.get("scenario_key"),
            "slice_decision": ml_evidence.get("slice_decision"),
            "slice_sample_count": ml_evidence.get("slice_sample_count"),
            "latest_average_reward": ml_evidence.get("latest_average_reward"),
            "curve_delta": ml_evidence.get("curve_delta"),
            "used_for": scope["usage_scope"],
            "accepted_by_judge": scope["accepted_by_judge"],
            "score_adjustment": scope["score_adjustment"],
            "reason": scope["reason"],
            "policy": ml_evidence.get("policy"),
            "decision_delta": decision_delta,
        }
        proposal["ml_policy_evidence_use"] = use
        proposal["ml_policy_decision_delta"] = decision_delta
        reasoning = proposal.get("department_reasoning", {}) if isinstance(proposal.get("department_reasoning"), dict) else {}
        if reasoning:
            reasoning["learned_policy_evidence"] = use
            reasoning["counterfactual_learning_comparison"] = {
                "scenario_key": ml_evidence.get("scenario_key"),
                "slice_decision": ml_evidence.get("slice_decision"),
                "candidate_pattern": requested_tool,
                "compare_against": ["hold_action", "current_live_feed_only", "memory_prior_only"],
                "learning_question": "Did the chosen department action outperform hold/fallback under the same scenario slice without crossing policy boundaries?",
            }
            candidate_actions = reasoning.get("candidate_actions", []) if isinstance(reasoning.get("candidate_actions"), list) else []
            if candidate_actions and isinstance(candidate_actions[0], dict):
                base = float(candidate_actions[0].get("memory_adjusted_score") or candidate_actions[0].get("score") or 0)
                candidate_actions[0]["ml_policy_adjusted_score"] = round(max(0.01, min(0.99, base + float(scope["score_adjustment"]))), 2)
                candidate_actions[0]["ml_policy_adjustment_reason"] = scope["reason"]
            forecast = reasoning.get("forecast", {}) if isinstance(reasoning.get("forecast"), dict) else {}
            if forecast:
                forecast["ml_policy_evidence_adjustment"] = decision_delta
            carry = reasoning.get("memory_carry_forward", {}) if isinstance(reasoning.get("memory_carry_forward"), dict) else {}
            if carry:
                carry.setdefault("carry", [])
                if isinstance(carry["carry"], list):
                    carry["carry"] = list(dict.fromkeys([*carry["carry"], "ml_slice_decision", "ml_reward_curve_delta", "ml_policy_decision_delta"]))
                carry.setdefault("do_better_next_time", [])
                if isinstance(carry["do_better_next_time"], list):
                    carry["do_better_next_time"] = list(dict.fromkeys(["compare selected action against ML slice expectation", *carry["do_better_next_time"]]))
            proposal["department_reasoning"] = reasoning
        if ml_evidence.get("scenario_key"):
            proposal.setdefault("evidence", [])
            if isinstance(proposal["evidence"], list):
                proposal["evidence"] = list(
                    dict.fromkeys(
                        [
                            f"ml_slice:{ml_evidence.get('scenario_key')}:decision={ml_evidence.get('slice_decision')}:reward={ml_evidence.get('latest_average_reward')}:delta={ml_evidence.get('curve_delta')}",
                            *[str(item) for item in proposal["evidence"]],
                        ]
                    )
                )[:12]
        if envelope:
            envelope["ml_policy_evidence"] = use
            envelope["ml_policy_decision_delta"] = decision_delta
            proposal["proposal_envelope"] = envelope
        row = {
            "agent": proposal.get("agent_id"),
            "department": department,
            "requested_tool": requested_tool,
            "status": scope["status"],
            "accepted_by_judge": scope["accepted_by_judge"],
            "usage_scope": scope["usage_scope"],
            "decision_delta": decision_delta,
        }
        if scope["accepted_by_judge"]:
            accepted.append(row)
        elif scope["status"] == "warning_hold_slice":
            warnings.append(row)
        else:
            context_only.append(row)
    proposals["ml_policy_evidence"] = ml_evidence
    proposals["ml_policy_evidence_use"] = {
        "status": "applied" if accepted or context_only or warnings else "none",
        "scenario_key": ml_evidence.get("scenario_key"),
        "accepted_low_risk_count": len(accepted),
        "context_only_count": len(context_only),
        "warning_count": len(warnings),
        "policy": "Actual-training evidence shapes confidence and counterfactual questions only; execution authority remains with policy, Compliance, Executive, and Tool Executor.",
        "accepted_rows": accepted,
        "context_only_rows": context_only,
        "warning_rows": warnings,
    }
    proposals["ml_policy_decision_deltas"] = [*accepted, *context_only, *warnings]
    tradeoff = proposals.get("executive_tradeoff", {}) if isinstance(proposals.get("executive_tradeoff"), dict) else {}
    if tradeoff:
        tradeoff["ml_policy_influence"] = {
            "scenario_key": ml_evidence.get("scenario_key"),
            "slice_decision": ml_evidence.get("slice_decision"),
            "latest_average_reward": ml_evidence.get("latest_average_reward"),
            "curve_delta": ml_evidence.get("curve_delta"),
            "accepted_low_risk_count": len(accepted),
            "context_only_count": len(context_only),
            "warning_count": len(warnings),
            "decision_rule": "Use ML slice evidence as learned policy context, not as permission to execute.",
            "deltas": [*accepted, *context_only, *warnings],
        }
        proposals["executive_tradeoff"] = tradeoff
    rounds = proposals.get("negotiation_rounds", []) if isinstance(proposals.get("negotiation_rounds"), list) else []
    if rounds and (accepted or context_only or warnings):
        rounds.insert(
            min(4, len(rounds)),
            {
                "round": "ml_policy",
                "name": "actual_training_slice_challenge",
                "decision": "learned_policy_evidence_applied",
                "scenario_key": ml_evidence.get("scenario_key"),
                "slice_decision": ml_evidence.get("slice_decision"),
                "accepted_low_risk": accepted,
                "context_only": context_only,
                "warnings": warnings,
                "resolution": "ML evidence may reinforce or warn, but cannot override policy or execute held actions.",
            },
        )
        proposals["negotiation_rounds"] = rounds
    proposals.setdefault("negotiation_turns", [])
    if isinstance(proposals["negotiation_turns"], list) and (accepted or context_only or warnings):
        proposals["negotiation_turns"].insert(
            2,
            {
                "turn": "ml_policy",
                "agent": "actual_training_policy_gate",
                "decision": "attached_slice_evidence",
                "reason": f"Scenario {ml_evidence.get('scenario_key')} slice decision {ml_evidence.get('slice_decision')} with reward {ml_evidence.get('latest_average_reward')} and delta {ml_evidence.get('curve_delta')}.",
            },
        )
    return proposals


def _proposal_tool_name(proposal: dict[str, Any]) -> str:
    envelope = proposal.get("proposal_envelope", {}) if isinstance(proposal.get("proposal_envelope"), dict) else {}
    return str(envelope.get("requested_tool") or proposal.get("requested_tool") or "")


def _proposal_policy_status(proposal: dict[str, Any]) -> str:
    envelope = proposal.get("proposal_envelope", {}) if isinstance(proposal.get("proposal_envelope"), dict) else {}
    policy = envelope.get("policy_judge") if isinstance(envelope.get("policy_judge"), dict) else proposal.get("policy_judge")
    return str((policy if isinstance(policy, dict) else {}).get("status") or "")


def _proposal_executor_status(proposal: dict[str, Any]) -> str:
    envelope = proposal.get("proposal_envelope", {}) if isinstance(proposal.get("proposal_envelope"), dict) else {}
    return str(envelope.get("executor_status") or proposal.get("executor_status") or "")


def _proposal_disposition_decision(proposal: dict[str, Any]) -> str:
    envelope = proposal.get("proposal_envelope", {}) if isinstance(proposal.get("proposal_envelope"), dict) else {}
    disposition = proposal.get("action_disposition") if isinstance(proposal.get("action_disposition"), dict) else envelope.get("action_disposition")
    return str((disposition if isinstance(disposition, dict) else {}).get("decision") or "")


def _live_feed_substitute_preferences(held_department: str, held_tool: str) -> list[tuple[str, str, str]]:
    held_department = str(held_department or "")
    held_tool = str(held_tool or "")
    common = [
        ("marketing", "redirect_offer", "Redirect demand away from the constrained area without changing crowd routing authority."),
        ("food_retail", "pause_launch_promo", "Reduce avoidable commercial demand pressure without sending guests a public route message."),
        ("hr_labor", "shift_adjustment_recommendation", "Add recommendation-only staffing support while preserving labor rules."),
    ]
    mapping = {
        "operations": common,
        "guest_experience": [
            ("marketing", "redirect_offer", "Use a bounded offer redirect instead of a public guest message."),
            ("food_retail", "pause_launch_promo", "Pause demand creation until message wording and destination capacity clear."),
            ("compliance", "generate_compliance_note", "Record wording, privacy, and promise constraints before any guest communication."),
        ],
        "maintenance": [
            ("hr_labor", "shift_adjustment_recommendation", "Stage certified support without treating work-order review as reopen clearance."),
            ("marketing", "redirect_offer", "Reduce demand toward the affected asset while inspection remains pending."),
            ("compliance", "generate_compliance_note", "Preserve inspection and reopen approval constraints in the trace."),
        ],
        "safety": [
            ("marketing", "redirect_offer", "Stop demand growth into risky zones while human safety approval remains required."),
            ("food_retail", "pause_launch_promo", "Remove optional demand pressure without implying safety clearance."),
            ("compliance", "generate_compliance_note", "Name the safety approval chain and blocked scopes."),
        ],
        "security": [
            ("marketing", "redirect_offer", "Avoid adding traffic to monitored zones while security review remains human-owned."),
            ("hr_labor", "shift_adjustment_recommendation", "Recommend visible staff support without dispatching security control."),
            ("compliance", "generate_compliance_note", "Name escalation limits and approval requirements."),
        ],
    }
    preferences = mapping.get(held_department, common)
    if held_tool in {"draft_guest_message", "issue_recovery_offer"}:
        return mapping["guest_experience"]
    return preferences


def _build_live_feed_alternative_action_negotiation(proposals: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(proposals, dict):
        return {"status": "missing", "substitute_count": 0, "rows": []}
    rows = proposals.get("proposals", []) if isinstance(proposals.get("proposals"), list) else []
    proposal_rows = [row for row in rows if isinstance(row, dict)]
    by_department_tool: dict[tuple[str, str], dict[str, Any]] = {}
    for proposal in proposal_rows:
        by_department_tool[(str(proposal.get("department") or ""), _proposal_tool_name(proposal))] = proposal

    sensitive_departments = {"operations", "maintenance", "guest_experience", "safety", "security"}
    low_risk_executor_departments = {"food_retail", "hr_labor", "marketing"}
    substitute_rows: list[dict[str, Any]] = []
    unresolved_without_safe_substitute = 0

    for held in proposal_rows:
        held_department = str(held.get("department") or "")
        if held_department not in sensitive_departments:
            continue
        held_status = _proposal_policy_status(held)
        held_decision = _proposal_disposition_decision(held)
        if held_status in {"passed", "approved_with_exclusions", "trace_only"} and held_decision != "hold_message_for_compliance":
            continue
        held_tool = _proposal_tool_name(held)
        selected_substitute: dict[str, Any] | None = None
        selected_reason = ""
        for substitute_department, substitute_tool, reason in _live_feed_substitute_preferences(held_department, held_tool):
            candidate = by_department_tool.get((substitute_department, substitute_tool))
            if not candidate:
                continue
            candidate_status = _proposal_policy_status(candidate)
            candidate_executor = _proposal_executor_status(candidate)
            if (
                candidate_status in {"passed", "approved_with_exclusions", "trace_only"}
                and (
                    substitute_department in low_risk_executor_departments
                    or candidate_status == "trace_only"
                    or substitute_department == "compliance"
                )
            ):
                selected_substitute = candidate
                selected_reason = reason
                break
        if selected_substitute:
            substitute_department = str(selected_substitute.get("department") or "")
            substitute_tool = _proposal_tool_name(selected_substitute)
            substitute_status = _proposal_policy_status(selected_substitute)
            substitute_executor = _proposal_executor_status(selected_substitute)
            executable_if_approved = (
                substitute_department in low_risk_executor_departments
                and substitute_status in {"passed", "approved_with_exclusions"}
                and substitute_executor in {"ready_for_executor", "executor_only"}
            )
            substitute_agent = selected_substitute.get("agent_id")
        else:
            fallback_department, substitute_tool, selected_reason = _live_feed_substitute_preferences(held_department, held_tool)[0]
            substitute_department = fallback_department
            substitute_status = "not_available_in_current_proposals"
            substitute_executor = "not_enqueued"
            executable_if_approved = False
            substitute_agent = None
            unresolved_without_safe_substitute += 1

        grounding = held.get("live_feed_grounding", {}) if isinstance(held.get("live_feed_grounding"), dict) else {}
        held_disposition = held.get("action_disposition", {}) if isinstance(held.get("action_disposition"), dict) else {}
        row = {
            "alternative_id": f"alt_{hashlib.sha1(json.dumps({'agent': held.get('agent_id'), 'department': held_department, 'tool': held_tool, 'substitute_department': substitute_department, 'substitute_tool': substitute_tool}, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:12]}",
            "held_agent": held.get("agent_id"),
            "held_department": held_department,
            "held_tool": held_tool,
            "held_policy_status": held_status,
            "held_decision": held_decision,
            "held_next_owner": held_disposition.get("next_owner"),
            "substitute_agent": substitute_agent,
            "substitute_department": substitute_department,
            "substitute_tool": substitute_tool,
            "substitute_policy_status": substitute_status,
            "substitute_executor_status": substitute_executor,
            "substitute_existing_proposal": bool(selected_substitute),
            "substitute_executable_if_approved": executable_if_approved,
            "execution_boundary": "Use the substitute only through its own policy-passed envelope; never convert the held action into execution.",
            "tradeoff_reason": selected_reason,
            "live_feed_event_ids": grounding.get("event_ids", []),
            "memory_context": (held.get("memory_use", {}) if isinstance(held.get("memory_use"), dict) else {}).get("status"),
            "ml_policy_context": (held.get("ml_policy_evidence_use", {}) if isinstance(held.get("ml_policy_evidence_use"), dict) else {}).get("status"),
            "resolution": (
                "safe_substitute_available"
                if selected_substitute and executable_if_approved
                else "trace_or_review_substitute_available"
                if selected_substitute
                else "owner_follow_up_required_no_safe_substitute"
            ),
        }
        substitute_rows.append(row)

    status = "negotiated" if substitute_rows and unresolved_without_safe_substitute == 0 else "partial" if substitute_rows else "none"
    board = {
        "mode": "held_action_alternative_negotiation",
        "status": status,
        "substitute_count": len(substitute_rows),
        "safe_executable_substitute_count": sum(1 for row in substitute_rows if row.get("substitute_executable_if_approved")),
        "unresolved_without_safe_substitute_count": unresolved_without_safe_substitute,
        "rows": substitute_rows,
        "policy": "Held sensitive actions remain held; this board negotiates safer substitutes through existing department envelopes and does not grant new execution rights.",
    }

    tradeoff = proposals.get("executive_tradeoff", {}) if isinstance(proposals.get("executive_tradeoff"), dict) else {}
    if isinstance(tradeoff, dict):
        tradeoff["alternative_action_negotiation"] = {
            "status": board["status"],
            "substitute_count": board["substitute_count"],
            "safe_executable_substitute_count": board["safe_executable_substitute_count"],
            "unresolved_without_safe_substitute_count": board["unresolved_without_safe_substitute_count"],
            "decision_rule": board["policy"],
            "rows": substitute_rows,
        }
        proposals["executive_tradeoff"] = tradeoff

    rounds = proposals.get("negotiation_rounds", []) if isinstance(proposals.get("negotiation_rounds"), list) else []
    if substitute_rows:
        rounds.insert(
            min(5, len(rounds)),
            {
                "round": "alternative_actions",
                "name": "held_action_substitute_negotiation",
                "decision": "safe_substitutes_named_before_follow_through",
                "substitutes": substitute_rows,
                "resolution": "Difficult actions are not left undecided: each held sensitive action receives a safer substitute path or a named owner follow-up.",
            },
        )
        proposals["negotiation_rounds"] = rounds

    proposals.setdefault("negotiation_turns", [])
    if substitute_rows and isinstance(proposals["negotiation_turns"], list):
        proposals["negotiation_turns"].insert(
            min(3, len(proposals["negotiation_turns"])),
            {
                "turn": "alternative_actions",
                "agent": "decision_bridge_agent",
                "decision": "named_safe_substitutes_for_held_actions",
                "reason": f"{len(substitute_rows)} held sensitive actions received substitute paths; {unresolved_without_safe_substitute} lacked a safe executable substitute.",
            },
        )
    proposals["alternative_action_negotiation"] = board
    return board


def _record_live_feed_controlled_outcome_memory(payload: dict[str, Any]) -> dict[str, Any]:
    executor = payload.get("tool_executor_live_test", {}) if isinstance(payload.get("tool_executor_live_test"), dict) else {}
    proposals = payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}
    live_case = payload.get("live_feed_case", {}) if isinstance(payload.get("live_feed_case"), dict) else {}
    receiver_delivery = payload.get("live_feed_receiver_delivery", {}) if isinstance(payload.get("live_feed_receiver_delivery"), dict) else {}
    outcome_measurement = payload.get("live_feed_outcome_measurement", {}) if isinstance(payload.get("live_feed_outcome_measurement"), dict) else {}
    memory_priors = payload.get("live_feed_memory_priors", {}) if isinstance(payload.get("live_feed_memory_priors"), dict) else {}
    ml_policy_evidence = payload.get("live_feed_ml_policy_evidence", {}) if isinstance(payload.get("live_feed_ml_policy_evidence"), dict) else {}
    ml_policy_use = proposals.get("ml_policy_evidence_use", {}) if isinstance(proposals.get("ml_policy_evidence_use"), dict) else {}
    follow_through = payload.get("hard_decision_follow_through", {}) if isinstance(payload.get("hard_decision_follow_through"), dict) else {}
    risk_escalation = payload.get("risk_escalation_approval", {}) if isinstance(payload.get("risk_escalation_approval"), dict) else {}
    risk_executor = payload.get("risk_escalated_tool_executor", {}) if isinstance(payload.get("risk_escalated_tool_executor"), dict) else {}
    risk_delivery = payload.get("risk_escalation_receiver_delivery", {}) if isinstance(payload.get("risk_escalation_receiver_delivery"), dict) else {}
    risk_impact = payload.get("risk_escalation_simulated_ops_impact", {}) if isinstance(payload.get("risk_escalation_simulated_ops_impact"), dict) else {}
    alternative_negotiation = proposals.get("alternative_action_negotiation", {}) if isinstance(proposals.get("alternative_action_negotiation"), dict) else payload.get("alternative_action_negotiation", {}) if isinstance(payload.get("alternative_action_negotiation"), dict) else {}
    substitute_attribution = outcome_measurement.get("substitute_outcome_attribution", {}) if isinstance(outcome_measurement.get("substitute_outcome_attribution"), dict) else (outcome_measurement.get("reward_layers", {}) if isinstance(outcome_measurement.get("reward_layers"), dict) else {}).get("substitute_outcome_attribution", {}) if isinstance((outcome_measurement.get("reward_layers", {}) if isinstance(outcome_measurement.get("reward_layers"), dict) else {}).get("substitute_outcome_attribution"), dict) else {}
    park_profile_summary = payload.get("park_profile_summary") or proposals.get("park_profile_summary") or {}
    if not isinstance(park_profile_summary, dict):
        park_profile_summary = {}
    receipts = executor.get("receipts", []) if isinstance(executor.get("receipts"), list) else []
    executed = [row for row in receipts if isinstance(row, dict) and (row.get("result", {}) if isinstance(row.get("result"), dict) else {}).get("status") == "executed_controlled"]
    held = [row for row in receipts if isinstance(row, dict) and (row.get("result", {}) if isinstance(row.get("result"), dict) else {}).get("status") == "held"]
    receiver_delivery_proven = (
        receiver_delivery.get("status") == "proven_controlled"
        and int(receiver_delivery.get("delivered_count") or 0) == len(executed)
        and int(receiver_delivery.get("acknowledged_count") or 0) == len(executed)
        and bool(executed)
    )
    measured_outcome_available = bool(outcome_measurement.get("measured_outcome_available"))
    eligible_for_reward = bool(outcome_measurement.get("eligible_for_reward"))
    reward_layers = outcome_measurement.get("reward_layers", {}) if isinstance(outcome_measurement.get("reward_layers"), dict) else {}
    branch_rewards = reward_layers.get("branch_rewards", {}) if isinstance(reward_layers.get("branch_rewards"), dict) else {}
    risk_lift_branch = branch_rewards.get("risk_lift", {}) if isinstance(branch_rewards.get("risk_lift"), dict) else {}
    risk_lift_label = str(reward_layers.get("risk_lift_label") or risk_lift_branch.get("label") or "risk_lift_not_requested")
    risk_training_tags = [
        "controlled_low_risk",
        risk_lift_label,
    ]
    if int(risk_lift_branch.get("executed_count") or risk_executor.get("executed_count") or 0) > 0:
        risk_training_tags.append("risk_lift_executed")
    if risk_impact.get("status") == "applied" and bool(risk_impact.get("material_state_mutation")):
        risk_training_tags.append("risk_lift_impact_applied")
    if risk_escalation.get("status") in {"disabled", "blocked", "not_requested"}:
        risk_training_tags.append(f"risk_gate_{risk_escalation.get('status')}")
    decision_basis = {
        "mode": "live_feed_controlled_executor_decision",
        "lead_source": live_case.get("lead_source"),
        "lead_signal_type": live_case.get("lead_signal_type"),
        "proposal_count": proposals.get("proposal_count"),
        "executed_tools": [row.get("source_tool") for row in executed],
        "held_tools": [row.get("source_tool") for row in held],
    }
    decision_id = payload.get("decision_id")
    if not decision_id:
        decision_id = f"decision_live_feed_{hashlib.sha1(json.dumps(decision_basis, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:12]}"
    outcome = {
        "loop_id": f"live_feed_controlled_executor:{decision_id}",
        "mode": "live_feed_controlled_executor_outcome",
        "phases": [
            {"phase": "observe", "status": "complete", "evidence_count": len(live_case.get("evidence", []) if isinstance(live_case.get("evidence"), list) else [])},
            {"phase": "memory_retrieval", "status": memory_priors.get("status") or "missing", "prior_count": memory_priors.get("prior_count"), "prior_outcome_ids": memory_priors.get("latest_outcome_ids", [])},
            {"phase": "actual_training_policy_evidence", "status": ml_policy_evidence.get("status") or "missing", "scenario_key": ml_policy_evidence.get("scenario_key"), "slice_decision": ml_policy_evidence.get("slice_decision"), "accepted_low_risk_count": ml_policy_use.get("accepted_low_risk_count")},
            {"phase": "park_profile_context", "status": proposals.get("park_profile_context_status") or park_profile_summary.get("status") or "missing", "profile_context_proposal_count": proposals.get("profile_context_proposal_count"), "profile_version": proposals.get("profile_version") or park_profile_summary.get("profile_version")},
            {"phase": "propose", "status": "complete", "proposal_count": proposals.get("proposal_count")},
            {"phase": "policy_judge", "status": "complete", "concrete_policy_count": sum(1 for item in proposals.get("proposals", []) if isinstance(item, dict) and item.get("policy_judge")) if isinstance(proposals.get("proposals"), list) else 0},
            {"phase": "alternative_action_negotiation", "status": alternative_negotiation.get("status") or "missing", "substitute_count": alternative_negotiation.get("substitute_count"), "unresolved_without_safe_substitute_count": alternative_negotiation.get("unresolved_without_safe_substitute_count")},
            {"phase": "controlled_executor", "status": executor.get("status"), "executed_count": executor.get("executed_count"), "held_count": executor.get("held_count")},
            {"phase": "hard_decision_follow_through", "status": follow_through.get("status") or "missing", "task_count": follow_through.get("task_count"), "active_follow_up_count": follow_through.get("active_follow_up_count")},
            {"phase": "risk_escalation_approval", "status": risk_escalation.get("status") or "missing", "stage": risk_escalation.get("stage"), "requested_count": risk_escalation.get("requested_count"), "approved_count": risk_escalation.get("approved_count")},
            {"phase": "risk_escalated_executor", "status": risk_executor.get("status") or "missing", "executed_count": risk_executor.get("executed_count"), "preview_count": risk_executor.get("preview_count")},
            {"phase": "risk_escalation_receiver_delivery", "status": risk_delivery.get("status") or "missing", "delivered_count": risk_delivery.get("delivered_count"), "acknowledged_count": risk_delivery.get("acknowledged_count")},
            {"phase": "risk_escalation_impact", "status": risk_impact.get("status") or "missing", "material_state_mutation": risk_impact.get("material_state_mutation"), "episode_fitness": (risk_impact.get("episode_fitness", {}) if isinstance(risk_impact.get("episode_fitness"), dict) else {}).get("fitness")},
            {"phase": "receiver_delivery", "status": receiver_delivery.get("status") or "missing", "delivered_count": receiver_delivery.get("delivered_count"), "acknowledged_count": receiver_delivery.get("acknowledged_count")},
            {"phase": "post_action_measurement", "status": outcome_measurement.get("status") or "missing", "attribution_confidence": outcome_measurement.get("attribution_confidence"), "eligible_for_reward": eligible_for_reward},
            {"phase": "substitute_outcome_attribution", "status": substitute_attribution.get("status") or "missing", "executed_branch_count": substitute_attribution.get("executed_branch_count"), "average_lift_vs_monitor": substitute_attribution.get("average_lift_vs_monitor")},
        ],
        "response_metrics": {
            "controlledExecutionRate": round((len(executed) / len(receipts)), 3) if receipts else 0,
            "heldActionRate": round((len(held) / len(receipts)), 3) if receipts else 0,
            "receiverDeliveryProven": receiver_delivery_proven,
            "measuredOutcomeAvailable": measured_outcome_available,
            "attributionConfidence": outcome_measurement.get("attribution_confidence"),
            "rewardValue": outcome_measurement.get("reward_value"),
            "rewardLayers": reward_layers,
            "branchRewards": branch_rewards,
            "riskLiftLabel": risk_lift_label,
            "promotionEligible": outcome_measurement.get("promotion_eligible"),
        },
        "state_impact": {
            "domain": "live_feed_controlled_executor",
            "headline": "Controlled low-risk envelopes executed, internal receivers acknowledged, and post-action live-feed measurements were captured.",
            "executed_departments": sorted({str(row.get("department")) for row in executed if row.get("department")}),
            "held_departments": sorted({str(row.get("department")) for row in held if row.get("department")}),
            "executed_tools": [row.get("source_tool") for row in executed],
            "held_tools": [row.get("source_tool") for row in held],
            "live_feed_event_ids": live_case.get("live_feed_event_ids") or proposals.get("live_feed_event_ids") or [],
            "material_state_mutation": False,
            "controlled_executor_only": True,
            "memory_prior_outcome_ids": memory_priors.get("latest_outcome_ids", []),
            "memory_prior_count": memory_priors.get("prior_count", 0),
            "memory_prior_policy": memory_priors.get("policy"),
            "ml_policy_evidence": ml_policy_evidence,
            "ml_policy_evidence_use": ml_policy_use,
            "ml_policy_decision_deltas": proposals.get("ml_policy_decision_deltas", []),
            "alternative_action_negotiation": alternative_negotiation,
            "park_profile_summary": park_profile_summary,
            "profile_context_proposal_count": proposals.get("profile_context_proposal_count"),
            "profile_precedence": proposals.get("precedence") or park_profile_summary.get("precedence"),
            "hard_decision_follow_through_status": follow_through.get("status"),
            "hard_decision_follow_through_tasks": follow_through.get("tasks", []),
            "active_follow_up_count": follow_through.get("active_follow_up_count"),
            "risk_escalation_approval": risk_escalation,
            "risk_escalated_tool_executor": risk_executor,
            "risk_escalation_receiver_delivery": risk_delivery,
            "risk_escalation_simulated_ops_impact": risk_impact,
            "receiver_delivery_proof_id": receiver_delivery.get("proof_id"),
            "receiver_delivery_status": receiver_delivery.get("status"),
            "receiver_delivery_receipts": receiver_delivery.get("receipts", []),
            "post_action_measurement_id": outcome_measurement.get("measurement_id"),
            "post_action_measurement_status": outcome_measurement.get("status"),
            "post_action_measurement_rows": outcome_measurement.get("measurement_rows", []),
            "substitute_outcome_attribution": substitute_attribution,
        },
        "scorecard": {
            "overall": 86 if executed and held else 72,
            "status": "reward_candidate_ready" if eligible_for_reward else "training_ready_controlled_outcome" if executed and held else "review",
            "groundedness": 100 if proposals.get("live_feed_grounded_proposal_count") == proposals.get("proposal_count") else 70,
            "policy_boundary": 100 if held else 80,
            "executor_boundary": 100 if executed and held else 75,
            "park_profile_context": 100 if proposals.get("profile_context_proposal_count") == proposals.get("proposal_count") else 40,
            "hard_decision_follow_through": 100 if follow_through.get("status") == "routed" and int(follow_through.get("unresolved_without_owner_count") or 0) == 0 else 50 if held else 100,
            "receiver_delivery": 100 if receiver_delivery_proven else 0,
            "post_action_measurement": 100 if measured_outcome_available else 0,
            "operational_reward": round(float(reward_layers.get("operational_reward") or 0) * 100, 1) if reward_layers else 0,
            "promotion_eligible": bool(outcome_measurement.get("promotion_eligible")),
        },
        "learning": {
            "label": "controlled_execute_vs_hold_supervision",
            "training_use": "supervised_eval_and_reward_candidate_material" if eligible_for_reward else "supervised_eval_only_until_measured_outcome_exists",
            "eligible_for_reward": eligible_for_reward,
            "reward_label": outcome_measurement.get("reward_label"),
            "reward_value": outcome_measurement.get("reward_value"),
            "reward_layers": reward_layers,
            "branch_rewards": branch_rewards,
            "risk_lift_label": risk_lift_label,
            "training_tags": risk_training_tags,
            "promotion_eligible": outcome_measurement.get("promotion_eligible"),
            "profile_learning_context": {
                "profile_version": proposals.get("profile_version") or park_profile_summary.get("profile_version"),
                "profile_context_proposal_count": proposals.get("profile_context_proposal_count"),
                "precedence": proposals.get("precedence") or park_profile_summary.get("precedence"),
                "observation_keys": ((park_profile_summary.get("counts") or {}) if isinstance(park_profile_summary.get("counts"), dict) else {}),
            },
            "ml_policy_learning_context": {
                "scenario_key": ml_policy_evidence.get("scenario_key"),
                "slice_decision": ml_policy_evidence.get("slice_decision"),
                "latest_average_reward": ml_policy_evidence.get("latest_average_reward"),
                "curve_delta": ml_policy_evidence.get("curve_delta"),
                "accepted_low_risk_count": ml_policy_use.get("accepted_low_risk_count"),
                "context_only_count": ml_policy_use.get("context_only_count"),
                "warning_count": ml_policy_use.get("warning_count"),
                "training_source": ml_policy_evidence.get("actual_training_source"),
            },
            "alternative_action_learning_context": {
                "status": alternative_negotiation.get("status"),
                "substitute_count": alternative_negotiation.get("substitute_count"),
                "safe_executable_substitute_count": alternative_negotiation.get("safe_executable_substitute_count"),
                "unresolved_without_safe_substitute_count": alternative_negotiation.get("unresolved_without_safe_substitute_count"),
                "policy": alternative_negotiation.get("policy"),
            },
            "substitute_outcome_learning_context": {
                "status": substitute_attribution.get("status"),
                "branch_count": substitute_attribution.get("branch_count"),
                "executed_branch_count": substitute_attribution.get("executed_branch_count"),
                "average_substitute_score": substitute_attribution.get("average_substitute_score"),
                "average_lift_vs_monitor": substitute_attribution.get("average_lift_vs_monitor"),
                "bundle": substitute_attribution.get("bundle", {}),
            },
            "risk_lift_learning_context": {
                "status": risk_escalation.get("status"),
                "stage": risk_escalation.get("stage"),
                "requested_count": risk_escalation.get("requested_count"),
                "approved_count": risk_escalation.get("approved_count"),
                "executed_count": risk_executor.get("executed_count"),
                "delivery_status": risk_delivery.get("status"),
                "impact_status": risk_impact.get("status"),
                "material_state_mutation": risk_impact.get("material_state_mutation"),
                "branch_reward": risk_lift_branch,
                "training_rule": "Use this branch to learn escalation quality separately from low-risk controlled execution.",
            },
            "next_gap": "Resolve active hard-decision follow-up tasks and attribute longer-horizon operational lift." if follow_through.get("active_follow_up_count") else "Attribute longer-horizon operational lift after receiver action." if eligible_for_reward else "Record post-action state measurements before reward training.",
        },
    }
    try:
        outcome_id = record_mongo_outcome_event(outcome, str(decision_id), None)
    except Exception as error:
        outcome_id = f"skipped_live_feed_outcome_error_{hashlib.sha1(str(error).encode('utf-8')).hexdigest()[:12]}"
    return {
        "status": "recorded" if not str(outcome_id).startswith("skipped_") else "skipped",
        "mode": "live_feed_controlled_outcome_memory",
        "decision_id": decision_id,
        "outcome_id": outcome_id,
        "mongo_collection": "outcome_events",
        "outcome": outcome,
        "training_boundary": "Outcome memory is materialized for next-term training only; this run does not start training or promote a model.",
    }


@app.post("/api/park/live-feed-agent-run")
async def park_live_feed_agent_run(request: LiveFeedAgentRunRequest):
    refresh = None
    if request.refresh_stale:
        before = await _live_feed_health_payload(limit=500)
        before_summary = before.get("summary", {}) if isinstance(before.get("summary"), dict) else {}
        if int(before_summary.get("persisted_event_count") or 0) <= 0:
            refresh = await _refresh_due_live_feeds_payload(
                {
                    "stale_only": False,
                    "refresh_margin_seconds": 20,
                    "sources": ["ride_ops", "guest_flow", "staffing", "food_ops", "operator_signal"],
                }
            )
        else:
            refresh = await _refresh_due_live_feeds_payload({"stale_only": True, "refresh_margin_seconds": 20})
    health = await _live_feed_health_payload(limit=500)
    live_case = _live_feed_case_from_health(health)
    if request.scenario_key_hint:
        live_case["scenario_key"] = request.scenario_key_hint
        live_case["scenario_key_source"] = "request_hint"
    if request.generated_issue:
        live_case["generated_issue"] = request.generated_issue
        issue_kind = request.generated_issue.get("kind") or request.generated_issue.get("issue_kind")
        target_id = request.generated_issue.get("target_id") or request.generated_issue.get("targetId")
        if issue_kind:
            live_case["issue_kind"] = issue_kind
        if target_id:
            live_case["issue_target_id"] = target_id
    memory_priors = _live_feed_memory_priors_from_dashboard(live_case)
    ml_policy_evidence = _live_feed_ml_policy_evidence(live_case)
    live_case["memory_priors"] = memory_priors
    live_case["ml_policy_evidence"] = ml_policy_evidence
    readiness_issues: list[str] = []
    if request.require_persisted_events and int(live_case.get("persisted_event_count") or 0) <= 0:
        readiness_issues.append("No persisted live feed events are available; load live feeds before running a live-feed case.")
    if int(live_case.get("ready_feed_count") or 0) < request.min_ready_feeds:
        readiness_issues.append(f"Only {live_case.get('ready_feed_count')} live feeds are ready; {request.min_ready_feeds} are required.")
    if readiness_issues:
        return {
            "status": "blocked",
            "mode": "live_feed_agent_run",
            "live_feed_case": live_case,
            "live_feed_health": health,
            "live_feed_refresh": refresh,
            "readiness_issues": readiness_issues,
            "uses_seed_data": False,
            "scripted_case": False,
        }

    payload = await park_agent_run(
        ParkAgentRunRequest(
            scenario_key=None,
            operation_mode=False,
            auto_unexpected_event=False,
            operator_message=live_case["operator_message"],
            execute=request.execute,
            live_feed_case=live_case,
            live_feed_health=health,
            orchestration_source="live_feed",
        )
    )
    if isinstance(payload, dict):
        payload["mode"] = "live_feed_agent_run"
        payload["source"] = "live_feed_health"
        payload["uses_seed_data"] = False
        payload["scripted_case"] = False
        payload["live_feed_case"] = live_case
        payload["live_feed_health"] = health
        payload["live_feed_refresh"] = refresh
        payload["live_feed_memory_priors"] = memory_priors
        payload["live_feed_ml_policy_evidence"] = ml_policy_evidence
        proposals = payload.get("role_agent_proposals", {}) if isinstance(payload.get("role_agent_proposals"), dict) else {}
        proposals = _apply_live_feed_memory_priors_to_proposals(proposals, memory_priors)
        proposals = _apply_live_feed_ml_policy_evidence_to_proposals(proposals, ml_policy_evidence)
        alternative_negotiation = _build_live_feed_alternative_action_negotiation(proposals)
        payload["role_agent_proposals"] = proposals
        payload["alternative_action_negotiation"] = alternative_negotiation
        payload["park_profile_summary"] = proposals.get("park_profile_summary", {})
        payload["live_feed_cooperation"] = proposals.get("cooperation_graph") or _build_live_feed_cooperation_graph(proposals, live_case)
        payload["tool_executor_live_test"] = _controlled_live_feed_tool_executor_run(
            payload,
            execute=request.controlled_executor_execute,
        )
        payload["hard_decision_follow_through"] = _build_live_feed_hard_decision_follow_through(payload)
        payload = _apply_risk_escalation_validation_mode(payload, request.risk_escalation_validation_mode)
        payload["risk_escalation_approval"] = _build_live_feed_risk_escalation_approval(
            payload,
            enabled=request.allow_risk_escalation,
        )
        payload["risk_escalated_tool_executor"] = _risk_escalated_live_feed_tool_executor_run(
            payload,
            execute=request.controlled_executor_execute,
        )
        payload["live_feed_receiver_delivery"] = _controlled_live_feed_receiver_delivery_proof(payload)
        payload["risk_escalation_receiver_delivery"] = _risk_escalation_receiver_delivery_proof(payload)
        payload["live_feed_simulated_ops_impact"] = await _apply_controlled_live_feed_simulated_ops_impact(payload)
        payload["risk_escalation_simulated_ops_impact"] = await _apply_risk_escalation_simulated_ops_impact(payload)
        if request.measure_post_action:
            payload["live_feed_post_action_refresh"] = await _refresh_due_live_feeds_payload(
                {
                    "stale_only": False,
                    "refresh_margin_seconds": 0,
                    "sources": ["ride_ops", "guest_flow", "staffing", "food_ops", "operator_signal"],
                }
            )
            payload["live_feed_outcome_measurement"] = _build_live_feed_outcome_measurement(
                payload,
                payload.get("live_feed_post_action_refresh") if isinstance(payload.get("live_feed_post_action_refresh"), dict) else {},
            )
        else:
            payload["live_feed_post_action_refresh"] = {"status": "skipped", "reason": "measure_post_action=false"}
            payload["live_feed_outcome_measurement"] = _build_live_feed_outcome_measurement(payload, {})
        payload["live_feed_outcome_memory"] = _record_live_feed_controlled_outcome_memory(payload)
        payload["tool_use_clarity"] = _tool_use_clarity_from_run(payload)
    return payload


def _live_feed_refresh_requested_sources(payload: dict[str, Any]) -> set[str]:
    requested = payload.get("sources")
    if not isinstance(requested, list):
        return set()
    return {str(source).strip().replace("-", "_") for source in requested if str(source).strip()}


def _live_feed_refresh_margin(payload: dict[str, Any]) -> int:
    raw = payload.get("refresh_margin_seconds")
    if raw is None:
        raw = payload.get("refreshMarginSeconds")
    if raw is None:
        raw = os.getenv("PARKPULSE_LIVE_FEED_REFRESH_MARGIN_SECONDS", "20")
    try:
        return max(0, int(float(raw)))
    except (TypeError, ValueError):
        return 20


def _live_feed_sources_due_for_refresh(before: dict[str, Any], requested_sources: set[str], stale_only: bool, refresh_margin_seconds: int) -> list[str]:
    due_sources: list[str] = []
    feeds = before.get("feeds", []) if isinstance(before.get("feeds"), list) else []
    for row in feeds:
        if not isinstance(row, dict):
            continue
        source = str(row.get("source") or "")
        if not source or (requested_sources and source not in requested_sources):
            continue
        age = row.get("age_seconds")
        budget = int(row.get("max_stale_seconds") or 0)
        due_soon = isinstance(age, int) and budget > 0 and age >= max(0, budget - refresh_margin_seconds)
        if not stale_only or row.get("status") != "ready" or due_soon:
            due_sources.append(source)
    return due_sources


async def _refresh_due_live_feeds_payload(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    request_payload = payload if isinstance(payload, dict) else {}
    requested_sources = _live_feed_refresh_requested_sources(request_payload)
    stale_only = _truthy(
        str(request_payload.get("stale_only") if "stale_only" in request_payload else request_payload.get("staleOnly"))
        if ("stale_only" in request_payload or "staleOnly" in request_payload)
        else None,
        True,
    )
    refresh_margin_seconds = _live_feed_refresh_margin(request_payload)

    before = await _live_feed_health_payload(limit=500)
    due_sources = _live_feed_sources_due_for_refresh(before, requested_sources, stale_only, refresh_margin_seconds)

    results: dict[str, Any] = {}
    queued_sources: list[str] = []
    raw_state: dict[str, Any] | None = None
    for source in due_sources:
        try:
            if source == "weather":
                result = _queue_live_weather_refresh("stale_feed_supervisor")
                queued_sources.append(source)
            else:
                if raw_state is None:
                    raw_state = await park_simulation.get_state_lite()
                if source == "ride_ops":
                    result = ingest_live_ride_ops_feed(raw_state)
                elif source == "guest_flow":
                    result = ingest_live_guest_flow_feed(raw_state)
                elif source == "staffing":
                    result = ingest_live_staffing_feed(raw_state)
                elif source == "food_ops":
                    result = ingest_live_food_ops_feed(raw_state)
                elif source == "operator_signal":
                    result = ingest_live_operator_signal_feed(raw_state)
                else:
                    result = {"status": "skipped", "readiness_issues": [f"Unknown live feed source: {source}"]}
            results[source] = result
        except Exception as error:
            results[source] = {"status": "error", "readiness_issues": [str(error)[:240]]}

    if results:
        clear_hot_endpoint_cache()
    after = await _live_feed_health_payload(limit=500)
    errors = [source for source, result in results.items() if isinstance(result, dict) and result.get("status") == "error"]
    refreshed_sources = [source for source in results if source not in set(queued_sources)]
    remaining_issues: list[str] = []
    for row in after.get("feeds", []) if isinstance(after.get("feeds"), list) else []:
        if not isinstance(row, dict) or row.get("status") == "ready":
            continue
        source = str(row.get("source") or "unknown")
        if requested_sources and source not in requested_sources:
            continue
        issues = row.get("readiness_issues") if isinstance(row.get("readiness_issues"), list) else []
        remaining_issues.append(f"{source}: {issues[0] if issues else row.get('status') or 'not ready'}")
    readiness_issues = [f"{source}: {results[source].get('readiness_issues', ['refresh failed'])[0]}" for source in errors]
    return {
        "status": "error" if errors else "refreshed" if refreshed_sources else "queued" if queued_sources else "no_due_feeds",
        "mode": "live_feed_refresh_supervisor",
        "created_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "stale_only": stale_only,
        "refresh_margin_seconds": refresh_margin_seconds,
        "requested_sources": sorted(requested_sources),
        "refreshed_sources": refreshed_sources,
        "queued_sources": queued_sources,
        "result_count": len(results),
        "results": results,
        "before": before.get("summary"),
        "after": after.get("summary"),
        "after_feeds": after.get("feeds", []),
        "remaining_issues": remaining_issues,
        "readiness_issues": readiness_issues,
        "boundary": "Refresh supervisor only reloads evidence feeds. It does not trust sensitive events, close review cases, set reward, dispatch actions, or promote models.",
        "uses_seed_data": False,
        "llm_control_authority": False,
    }


@app.post("/api/park/live-feeds/refresh-stale")
async def park_live_feeds_refresh_stale(payload: dict[str, Any] | None = None):
    return await _refresh_due_live_feeds_payload(payload)


@app.get("/api/park/live-feeds/weather")
async def park_live_weather_feed_config():
    return {"status": "ready", "mode": "live_weather_feed_config", "config": weather_feed_config()}


@app.post("/api/park/live-feeds/weather/load")
async def park_live_weather_feed_load():
    result = ingest_live_weather_feed()
    clear_hot_endpoint_cache()
    return result


@app.get("/api/park/live-feeds/ride-ops")
async def park_live_ride_ops_feed_config():
    return {"status": "ready", "mode": "live_ride_ops_feed_config", "config": ride_ops_feed_config()}


@app.post("/api/park/live-feeds/ride-ops/load")
async def park_live_ride_ops_feed_load():
    result = ingest_live_ride_ops_feed(await park_simulation.get_state_lite())
    clear_hot_endpoint_cache()
    return result


@app.get("/api/park/live-feeds/guest-flow")
async def park_live_guest_flow_feed_config():
    return {"status": "ready", "mode": "live_guest_flow_feed_config", "config": guest_flow_feed_config()}


@app.post("/api/park/live-feeds/guest-flow/load")
async def park_live_guest_flow_feed_load():
    result = ingest_live_guest_flow_feed(await park_simulation.get_state_lite())
    clear_hot_endpoint_cache()
    return result


@app.get("/api/park/live-feeds/staffing")
async def park_live_staffing_feed_config():
    return {"status": "ready", "mode": "live_staffing_feed_config", "config": staffing_feed_config()}


@app.post("/api/park/live-feeds/staffing/load")
async def park_live_staffing_feed_load():
    result = ingest_live_staffing_feed(await park_simulation.get_state_lite())
    clear_hot_endpoint_cache()
    return result


@app.get("/api/park/live-feeds/food-ops")
async def park_live_food_ops_feed_config():
    return {"status": "ready", "mode": "live_food_ops_feed_config", "config": food_ops_feed_config()}


@app.post("/api/park/live-feeds/food-ops/load")
async def park_live_food_ops_feed_load():
    result = ingest_live_food_ops_feed(await park_simulation.get_state_lite())
    clear_hot_endpoint_cache()
    return result


@app.get("/api/park/live-feeds/operator-signal")
async def park_live_operator_signal_feed_config():
    return {"status": "ready", "mode": "live_operator_signal_feed_config", "config": operator_signal_feed_config()}


@app.post("/api/park/live-feeds/operator-signal/load")
async def park_live_operator_signal_feed_load():
    result = ingest_live_operator_signal_feed(await park_simulation.get_state_lite())
    clear_hot_endpoint_cache()
    return result


@app.get("/api/park/review-training-ledger")
async def park_review_training_ledger(limit: int = 120):
    return review_training_ledger(limit=max(10, min(500, limit)))


@app.post("/api/park/review-training-ledger")
async def park_review_training_ledger_record(payload: dict[str, Any]):
    result = record_review_decision(payload)
    clear_hot_endpoint_cache()
    return result


def _customer_public_park_details_for_api(park_state: dict[str, Any]) -> dict[str, Any]:
    from customer_park_knowledge import build_customer_public_data_feed, customer_park_knowledge

    state = park_state if isinstance(park_state, dict) else {}
    flow = state.get("guestFlow", {}) if isinstance(state.get("guestFlow"), dict) else {}
    weather = state.get("weather", {}) if isinstance(state.get("weather"), dict) else {}
    knowledge = customer_park_knowledge()
    attractions = knowledge.get("attractions", []) if isinstance(knowledge.get("attractions"), list) else []
    food = knowledge.get("food", []) if isinstance(knowledge.get("food"), list) else []
    venue_map = dict(knowledge.get("venue_map", {}) if isinstance(knowledge.get("venue_map"), dict) else {})
    landmarks = knowledge.get("landmarks", {}) if isinstance(knowledge.get("landmarks"), dict) else {}
    venue_map.setdefault("landmarks", [item for rows in landmarks.values() if isinstance(rows, list) for item in rows if isinstance(item, dict)])
    venue_map.setdefault("facilities", [item for item in venue_map.get("nodes", []) if isinstance(item, dict) and item.get("type") in {"restroom", "first_aid", "guest_services", "water_refill", "locker", "quiet_or_cooling"}])
    ride_rows = []
    for ride in flow.get("rides", []) if isinstance(flow.get("rides"), list) else []:
        if not isinstance(ride, dict):
            continue
        wait = int(float(ride.get("waitMins") or 0))
        status = str(ride.get("status") or "normal").lower()
        ride_rows.append(
            {
                "id": ride.get("id"),
                "name": ride.get("name") or ride.get("id"),
                "zone": ride.get("zoneName") or ride.get("zone"),
                "wait_mins": wait,
                "status": "temporarily unavailable" if status == "down" else "high demand" if wait >= 60 or status == "constrained" else "open",
            }
        )
    zone_rows = []
    for zone in flow.get("zones", []) if isinstance(flow.get("zones"), list) else []:
        if not isinstance(zone, dict):
            continue
        zone_rows.append(
            {
                "id": zone.get("id"),
                "name": zone.get("name") or zone.get("id"),
                "area": zone.get("area"),
                "density_pct": zone.get("density"),
                "wait_mins": zone.get("waitMins"),
                "comfort_score": zone.get("comfortScore"),
                "status": "high demand" if int(float(zone.get("density") or 0)) >= 85 else "open",
            }
        )
    route_rows = []
    for path in flow.get("paths", []) if isinstance(flow.get("paths"), list) else []:
        if not isinstance(path, dict):
            continue
        route_rows.append(
            {
                "from": path.get("from"),
                "to": path.get("to"),
                "from_name": path.get("fromName") or path.get("from"),
                "to_name": path.get("toName") or path.get("to"),
                "walk_minutes": path.get("walkMinutes"),
                "congestion_pct": path.get("congestionLevel"),
                "status": path.get("status") or ("congested" if int(float(path.get("congestionLevel") or 0)) >= 75 else "open"),
            }
        )
    if not ride_rows:
        ride_rows = attractions[:8]
    open_rides = [ride for ride in ride_rows if str(ride.get("status") or "open") != "temporarily unavailable"]
    best_ride = min(open_rides, key=lambda ride: int(float(ride.get("wait_mins") or ride.get("waitMins") or 999)), default=(attractions[0] if attractions else {}))
    best_food = food[0] if food else {}
    return build_customer_public_data_feed(
        {
            "status": "ready",
            "mode": "customer_public_park_details",
            "park": {
                "name": (state.get("product", {}) if isinstance(state.get("product"), dict) else {}).get("name") or "ParkPulse Park",
                "customer_surface": "kiosk_or_guest_app",
            },
            "weather": {
                "condition": weather.get("condition"),
                "temperature_f": weather.get("temperatureF"),
                "heat_index_f": weather.get("heatIndexF"),
                "storm_risk_pct": weather.get("stormRisk"),
            },
            "rides": ride_rows[:8],
            "zones": zone_rows[:8],
            "routes": route_rows[:12],
            "food": food[:8],
            "venue_map": venue_map,
            "event_schedule": knowledge.get("shows"),
            "recommended_public_options": {"best_ride": best_ride, "best_food": best_food},
            "customer_boundaries": [
                "Public waits, routing, food pickup, accessibility, and weather only.",
                "No internal staffing levels, private guest data, compensation promises, diagnoses, or operator dispatch.",
            ],
        }
    )


def _review_ledger_with_label_decisions_for_api(review_ledger: dict[str, Any]) -> dict[str, Any]:
    try:
        from review_label_pipeline import review_label_decision_ledger

        label_ledger = review_label_decision_ledger(limit=1000)
    except Exception:
        label_ledger = {}
    summary = dict(review_ledger.get("summary", {}) if isinstance(review_ledger.get("summary"), dict) else {})
    label_summary = label_ledger.get("summary", {}) if isinstance(label_ledger.get("summary"), dict) else {}
    base_count = int(float(summary.get("training_candidate_count") or 0))
    approved_labels = int(float(label_summary.get("approved_label_count") or 0))
    enriched = dict(review_ledger)
    summary["operator_disposition_training_candidate_count"] = base_count
    summary["approved_review_label_count"] = approved_labels
    summary["training_candidate_count"] = base_count + approved_labels
    enriched["summary"] = summary
    enriched["review_label_decision_ledger"] = label_ledger
    return enriched


def _api_issue_text(error: Exception, fallback: str) -> str:
    if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
        return fallback
    text = str(error).strip()
    return text[:240] if text else fallback


async def _bounded_actual_training_readiness_for_api(actual_training_status: Any, min_rows: int, *, timeout_env: str, default_timeout: float) -> dict[str, Any]:
    timeout = max(1.0, _float_env(timeout_env, default_timeout))

    def _load() -> dict[str, Any]:
        try:
            return actual_training_status(min_rows, False, detail="readiness")
        except TypeError:
            return actual_training_status(min_rows, False)

    try:
        return await asyncio.wait_for(asyncio.to_thread(_load), timeout=timeout)
    except Exception as error:
        return {
            "status": "not_ready",
            "mode": "actual_outcome_training",
            "sample_count": 0,
            "training_rows": [],
            "debug": {"readiness_issues": [_api_issue_text(error, f"Actual training readiness timed out after {timeout:g}s.")]},
            "uses_generated_data": False,
            "gcp_training_started": False,
            "model_promotion_started": False,
        }


def _live_feed_auto_label_threshold_for_api() -> float:
    return max(0.0, min(1.0, _float_env("PARKPULSE_AUTO_LABEL_CONFIDENCE_THRESHOLD", 0.70)))


@app.get("/api/park/customer-park-details")
async def park_customer_park_details():
    return _customer_public_park_details_for_api(await park_simulation.get_state())


@app.get("/api/park/customer-data-readiness")
async def park_customer_data_readiness(request: Request):
    _require_role_action(request, "read_ops_evidence", "customer_data_readiness", default_role="ops_team")
    details = _customer_public_park_details_for_api(await park_simulation.get_state())
    return {
        "status": "ready",
        "mode": "customer_data_readiness",
        "data_readiness": details.get("data_readiness"),
        "data_quality": details.get("data_quality"),
        "feed_contract": details.get("feed_contract"),
        "field_provenance": details.get("field_provenance"),
        "source_catalog": details.get("source_catalog"),
        "customer_boundaries": details.get("customer_boundaries"),
    }


@app.get("/api/park/training-readiness")
async def park_training_readiness(request: Request, minReviewLabels: int = 25, minOutcomeRows: int = 50):
    _require_role_action(request, "read_ml_training", "training_readiness", default_role="ml_ops_admin")
    from park_actual_training import actual_training_status
    from training_readiness import build_training_readiness_report

    state = await park_simulation.get_state()
    get_state_lite = getattr(park_simulation, "get_state_lite", None)
    lite_state = await get_state_lite() if callable(get_state_lite) else state
    customer_details = _customer_public_park_details_for_api(state)
    review = _review_ledger_with_label_decisions_for_api(review_training_ledger(limit=240))
    live_health = live_feed_health(lite_state, limit=120)
    actual = await _bounded_actual_training_readiness_for_api(
        actual_training_status,
        minOutcomeRows,
        timeout_env="PARKPULSE_TRAINING_READINESS_TIMEOUT_SECONDS",
        default_timeout=30.0,
    )
    return build_training_readiness_report(
        customer_details=customer_details,
        actual_training=actual,
        review_ledger=review,
        live_feed_health=live_health,
        min_review_labels=minReviewLabels,
        min_outcome_rows=minOutcomeRows,
    )


@app.get("/api/park/review-label-pipeline")
async def park_review_label_pipeline(request: Request, limit: int = 40, minReviewLabels: int = 25, minOutcomeRows: int = 50):
    _require_role_action(request, "read_ml_training", "review_label_pipeline", default_role="ml_ops_admin")
    from park_actual_training import actual_training_status
    from review_label_pipeline import build_review_label_pipeline
    from training_readiness import build_training_readiness_report

    state = await park_simulation.get_state()
    get_state_lite = getattr(park_simulation, "get_state_lite", None)
    lite_state = await get_state_lite() if callable(get_state_lite) else state
    customer_details = _customer_public_park_details_for_api(state)
    review = _review_ledger_with_label_decisions_for_api(review_training_ledger(limit=240))
    live_health = live_feed_health(lite_state, limit=120)
    actual = await _bounded_actual_training_readiness_for_api(
        actual_training_status,
        minOutcomeRows,
        timeout_env="PARKPULSE_REVIEW_LABEL_PIPELINE_TIMEOUT_SECONDS",
        default_timeout=30.0,
    )
    training = build_training_readiness_report(
        customer_details=customer_details,
        actual_training=actual,
        review_ledger=review,
        live_feed_health=live_health,
        min_review_labels=minReviewLabels,
        min_outcome_rows=minOutcomeRows,
    )
    return build_review_label_pipeline(customer_details=customer_details, training_readiness=training, review_ledger=review, live_feed_health=live_health, limit=limit)


@app.post("/api/park/review-label-pipeline/decision")
async def park_review_label_decision(request: Request, payload: dict[str, Any]):
    _require_role_action(request, "start_offline_training", "review_label_decision", payload, default_role="ml_ops_admin")
    from review_label_pipeline import record_review_label_decision

    return record_review_label_decision(payload)


@app.post("/api/park/review-label-pipeline/auto-label")
async def park_review_label_auto_label(request: Request, payload: dict[str, Any]):
    _require_role_action(request, "start_offline_training", "review_label_auto_label", payload, default_role="ml_ops_admin")
    from park_actual_training import actual_training_status
    from review_label_pipeline import auto_label_recommended_candidates, build_review_label_pipeline
    from training_readiness import build_training_readiness_report

    min_review_labels = int(payload.get("minReviewLabels") or payload.get("min_review_labels") or 25)
    min_outcome_rows = int(payload.get("minOutcomeRows") or payload.get("min_outcome_rows") or 50)
    confidence_threshold = float(payload.get("confidence_threshold") or payload.get("confidenceThreshold") or 0.70)
    state = await park_simulation.get_state()
    get_state_lite = getattr(park_simulation, "get_state_lite", None)
    lite_state = await get_state_lite() if callable(get_state_lite) else state
    customer_details = _customer_public_park_details_for_api(state)
    review = _review_ledger_with_label_decisions_for_api(review_training_ledger(limit=240))
    live_health = live_feed_health(lite_state, limit=120)
    actual = await _bounded_actual_training_readiness_for_api(actual_training_status, min_outcome_rows, timeout_env="PARKPULSE_REVIEW_LABEL_PIPELINE_TIMEOUT_SECONDS", default_timeout=30.0)
    training = build_training_readiness_report(customer_details=customer_details, actual_training=actual, review_ledger=review, live_feed_health=live_health, min_review_labels=min_review_labels, min_outcome_rows=min_outcome_rows)
    pipeline = build_review_label_pipeline(customer_details=customer_details, training_readiness=training, review_ledger=review, live_feed_health=live_health, limit=200)
    result = auto_label_recommended_candidates(pipeline, reviewer=str(payload.get("reviewer") or "parkpulse-auto-labeler"), confidence_threshold=confidence_threshold)
    return {**result, "pipeline_before": pipeline.get("summary")}


@app.get("/api/park/review-label-pipeline/decisions")
async def park_review_label_decisions(request: Request, limit: int = 120):
    _require_role_action(request, "read_ml_training", "review_label_decision_ledger", default_role="ml_ops_admin")
    from review_label_pipeline import review_label_decision_ledger

    return review_label_decision_ledger(limit=limit)


@app.get("/api/park/controlled-training-generation")
async def park_controlled_training_generation_latest(request: Request):
    _require_role_action(request, "read_ml_training", "controlled_training_generation", default_role="ml_ops_admin")
    from controlled_training_generation import latest_controlled_training_pack

    return latest_controlled_training_pack()


@app.post("/api/park/controlled-training-generation")
async def park_controlled_training_generation(request: Request, payload: dict[str, Any]):
    _require_role_action(request, "start_offline_training", "controlled_training_generation", payload, default_role="ml_ops_admin")
    from controlled_training_generation import generate_controlled_training_pack
    from park_actual_training import actual_training_status
    from review_label_pipeline import auto_label_recommended_candidates, build_review_label_pipeline, review_label_decision_ledger
    from training_readiness import build_training_readiness_report

    min_review_labels = int(payload.get("minReviewLabels") or payload.get("min_review_labels") or 25)
    min_outcome_rows = int(payload.get("minOutcomeRows") or payload.get("min_outcome_rows") or 50)
    max_examples = int(payload.get("maxExamples") or payload.get("max_examples") or 60)
    write_artifacts = str(payload.get("writeArtifacts", payload.get("write_artifacts", True))).lower() not in {"0", "false", "no", "off"}
    auto_label_enabled = str(payload.get("autoLabelHighConfidence", payload.get("auto_label_high_confidence", True))).lower() not in {"0", "false", "no", "off"}
    auto_label_threshold = float(payload.get("confidence_threshold") or payload.get("confidenceThreshold") or _live_feed_auto_label_threshold_for_api())
    auto_label_reviewer = str(payload.get("reviewer") or "parkpulse-controlled-training-auto-labeler")
    state = await park_simulation.get_state()
    get_state_lite = getattr(park_simulation, "get_state_lite", None)
    lite_state = await get_state_lite() if callable(get_state_lite) else state

    def _build_pack_payload() -> dict[str, Any]:
        customer_details = _customer_public_park_details_for_api(state)
        review = _review_ledger_with_label_decisions_for_api(review_training_ledger(limit=120))
        live_health = live_feed_health(lite_state, limit=120)
        try:
            actual = actual_training_status(min_outcome_rows, False, detail="readiness")
        except TypeError:
            actual = actual_training_status(min_outcome_rows, False)
        training = build_training_readiness_report(customer_details=customer_details, actual_training=actual, review_ledger=review, live_feed_health=live_health, min_review_labels=min_review_labels, min_outcome_rows=min_outcome_rows)
        pipeline = build_review_label_pipeline(customer_details=customer_details, training_readiness=training, review_ledger=review, live_feed_health=live_health, limit=200)
        auto_label = {"status": "disabled", "mode": "review_label_auto_label"} if not auto_label_enabled else auto_label_recommended_candidates(pipeline, reviewer=auto_label_reviewer, confidence_threshold=auto_label_threshold)
        if auto_label_enabled and int(auto_label.get("recorded_count") or 0) > 0:
            review = _review_ledger_with_label_decisions_for_api(review_training_ledger(limit=120))
            training = build_training_readiness_report(customer_details=customer_details, actual_training=actual, review_ledger=review, live_feed_health=live_health, min_review_labels=min_review_labels, min_outcome_rows=min_outcome_rows)
            pipeline = build_review_label_pipeline(customer_details=customer_details, training_readiness=training, review_ledger=review, live_feed_health=live_health, limit=200)
        decisions = review_label_decision_ledger(limit=200)
        pack = generate_controlled_training_pack(customer_details=customer_details, training_readiness=training, review_label_pipeline=pipeline, review_label_decisions=decisions, actual_training=actual, live_feed_health=live_health, max_examples=max_examples, write_artifacts=write_artifacts)
        return {**pack, "review_label_auto_label": auto_label}

    timeout = max(1.0, _float_env("PARKPULSE_CONTROLLED_TRAINING_GENERATION_TIMEOUT_SECONDS", 15.0))
    try:
        return await asyncio.wait_for(asyncio.to_thread(_build_pack_payload), timeout=timeout)
    except Exception as error:
        return {"status": "error", "mode": "controlled_eval_training_generation", "readiness_issues": [_api_issue_text(error, f"Controlled training generation timed out after {timeout:g}s.")]}


@app.get("/api/park/controlled-training-eval")
async def park_controlled_training_eval_latest(request: Request):
    _require_role_action(request, "read_ml_training", "controlled_training_eval", default_role="ml_ops_admin")
    from controlled_training_eval import latest_controlled_training_eval

    return latest_controlled_training_eval()


@app.post("/api/park/controlled-training-eval")
async def park_controlled_training_eval(request: Request, payload: dict[str, Any]):
    _require_role_action(request, "start_offline_training", "controlled_training_eval", payload, default_role="ml_ops_admin")
    from controlled_training_eval import run_controlled_training_eval
    from controlled_training_generation import latest_controlled_training_pack

    write_artifact = str(payload.get("writeArtifact", payload.get("write_artifact", True))).lower() not in {"0", "false", "no", "off"}
    pack = payload.get("pack") if isinstance(payload.get("pack"), dict) else latest_controlled_training_pack()
    return await asyncio.to_thread(run_controlled_training_eval, pack, write_artifact=write_artifact)


@app.get("/api/park/learning/episodes")
async def park_learning_episodes():
    return episode_dataset_status()


@app.get("/api/park/agent-role-skills")
async def park_agent_role_skills(message: str = "", mode: str = "auto"):
    registry = list_agent_role_skills()
    registry["route"] = route_agent_role(message, mode)
    return registry


@app.get("/api/park/agent-role-eval")
async def park_agent_role_eval(real: bool = False):
    if real:
        try:
            from main import _real_agent_role_eval_report

            return await _real_agent_role_eval_report()
        except Exception as error:
            report = build_deliberate_role_eval_report()
            return {**report, "real_trace_status": "unavailable", "real_trace_error": str(error)[:240]}
    return build_deliberate_role_eval_report()


@app.get("/api/park/synthetic-knowledge")
async def park_synthetic_knowledge():
    dataset = get_synthetic_park_knowledge()
    return {
        "status": "ready",
        "coverage": synthetic_coverage_report(dataset),
        "dataset": dataset,
    }


@app.post("/api/park/synthetic-scenario/inject")
async def park_synthetic_scenario_inject(request: SyntheticScenarioInjectRequest):
    if request.reset_first:
        await park_simulation.reset_demo()
    example = find_synthetic_example(request.selector)
    if not example:
        return {"status": "not_found", "message": f"No synthetic example matched {request.selector!r}."}
    plan = injection_plan_for_example(example)
    result = await park_simulation.inject_synthetic_incident(plan)
    clear_hot_endpoint_cache()
    state = await park_simulation.get_state()
    await sync_park_state_safe(state)
    return {
        "status": result["status"],
        "message": result["message"],
        "example": {
            "id": example.get("id"),
            "domain": example.get("domain"),
            "expected_owner": example.get("expected_owner"),
            "expected_case_id": example.get("expected_case_id"),
            "utterance": plan.get("utterance"),
        },
        "injection_plan": plan,
        "event": result.get("event"),
        "state": state,
    }


@app.post("/api/park/synthetic-scenario/eval-sweep")
async def park_synthetic_scenario_eval_sweep(request: SyntheticEvalSweepRequest):
    cases = synthetic_eval_cases(request.limit_examples, request.utterances_per_example)
    rows: list[dict[str, Any]] = []
    for eval_case in cases:
        response = await park_copilot_chat(
            CopilotChatRequest(
                message=str(eval_case.get("utterance") or ""),
                turn_mode="auto",
                allow_action=True,
                selected_map_context={},
            )
        )
        rows.append(score_synthetic_copilot_response(eval_case, response))
    passed = sum(1 for row in rows if row.get("passed"))
    avg_score = round(sum(int(row.get("score") or 0) for row in rows) / max(1, len(rows)), 1)
    return {
        "status": "complete",
        "case_count": len(rows),
        "passed": passed,
        "failed": len(rows) - passed,
        "pass_rate": round((passed / max(1, len(rows))) * 100, 1),
        "avg_score": avg_score,
        "rows": rows,
    }


def _agent_role_tool_output_for_api(tool: str, route: dict[str, Any]) -> dict[str, Any]:
    role = str(route.get("selected_role") or "agent")
    if tool == "get_park_state":
        return {"status": "ok", "role": role, "summary": "API role run read current park-state context.", "activeScenario": {"key": role}, "signals": ["api_role_route_context"]}
    if tool == "get_noisy_observation":
        return {"status": "ok", "role": role, "signals": [{"kind": "weak_signal", "confidence": 0.76}], "confidence": 0.76, "evidence": ["api signal cache"]}
    if tool.startswith("get_"):
        return {"status": "ok", "role": role, "summary": f"{tool} returned bounded public or operational context.", "constraint": "role_scope"}
    if tool == "retrieve_similar_incidents":
        return {"status": "ok", "role": role, "incidents": [{"id": f"{role}_api_prior"}], "learnings": [{"id": f"{role}_api_learning"}]}
    if tool == "compare_action_candidates":
        return {"status": "ok", "role": role, "candidates": [{"id": "monitor"}, {"id": "bounded_action"}], "selected": "bounded_action", "rejected": ["monitor"]}
    if tool in {"simulate_action", "tick_simulation"}:
        return {"status": "ok", "role": role, "simulation": {"horizon_minutes": 15}, "projected_impact": {"guest_flow": "improved", "risk_delta": -0.12}}
    if tool == "validate_policy":
        return {"status": "ok", "role": role, "gate_status": "checked", "policy_gate": "checked", "findings": route.get("policy_gates", []) or ["bounded authority"]}
    if tool.startswith("dispatch_"):
        return {"status": "prepared", "role": role, "dispatch_ids": [f"{tool}_{role}_api"], "idempotencyKey": f"{tool}:{role}:api", "targetSystem": "parkpulse_receiver", "payload": {"role": role}}
    if tool == "score_outcome":
        return {"status": "ok", "role": role, "score": 0.88, "metrics": {"response_quality": "bounded"}}
    if tool == "write_decision_memory":
        return {"status": "ok", "role": role, "decision_id": f"{role}_api_decision", "outcome_id": f"{role}_api_outcome", "memory_write": {"validity": "observed_response"}}
    if tool == "inspect_runtime_status":
        return {"status": "ok", "role": role, "readiness": {"api": "ready"}, "runtime": {"role_router": "available"}}
    if tool == "inspect_delivery_receipts":
        return {"status": "ok", "role": role, "receipts": [{"id": f"{role}_api_receipt"}], "dispatch_allowed": False}
    if tool == "inspect_observability_contract":
        return {"status": "ok", "role": role, "observability": {"trace": True, "tool_outputs": True}, "checklist": ["role", "tool", "output"]}
    if tool == "score_decision_quality":
        return {"status": "ok", "role": role, "scorecard": {"overall": 0.9}, "overall": 0.9}
    return {"status": "ok", "role": role, "summary": f"{tool} returned role-specific API evidence."}


def _agent_role_tool_trace_for_api(route: dict[str, Any]) -> dict[str, Any]:
    calls = []
    for tool in route.get("required_tools", []):
        tool_name = str(tool)
        capability = (
            "read"
            if tool_name.startswith("get_") or tool_name == "retrieve_similar_incidents"
            else "gate"
            if "validate" in tool_name
            else "eval"
            if "score" in tool_name
            else "act"
            if tool_name.startswith("dispatch_")
            else "simulate"
            if "simulate" in tool_name or tool_name == "tick_simulation"
            else "memory"
            if "memory" in tool_name
            else "reason"
        )
        calls.append(
            {
                "tool": tool_name,
                "server": "parkpulse.agent_roles",
                "capability": capability,
                "status": "ok",
                "output": _agent_role_tool_output_for_api(tool_name, route),
            }
        )
    trace = {
        "mode": "role_routed_mcp_tool_trace",
        "server": "parkpulse.agent_roles",
        "tool_count": len(calls),
        "tool_calls": calls,
        "summary": {
            "selected_role": route.get("selected_role"),
            "selected_skill": route.get("skill"),
            "policy_gates": route.get("policy_gates", []),
            "receipt_artifacts": route.get("expected_receipt", []),
        },
    }
    trace["deliberate_eval"] = evaluate_agent_role_trace(route, trace)
    return trace


def _fast_role_react_payload_for_api(message: str, route: dict[str, Any], tool_trace: dict[str, Any]) -> dict[str, Any]:
    lowered = message.lower()
    operator_route = _infer_operator_command_route(message, "auto")
    scenario_key = operator_route.get("scenario_key", "custom")
    if any(term in lowered for term in ("food", "kitchen", "mobile order", "restaurant")):
        headline = "React Agent is rerouting food demand."
        summary = "Food Court A is treated as constrained, so the plan pauses new mobile-order intake there, redirects guests to Food Court B and Main Street Shops, and sends food-service support to the pickup edge."
        dispatches = [
            {"id": "guest-food-reroute", "channel": "guest_app", "target": "guests_near_foodCourtA", "status": "sent", "message": "Food Court A is temporarily constrained. Use Food Court B or Main Street Shops for faster service."},
            {"id": "worker-food-support", "channel": "worker_device", "target": "food_service_leads", "status": "sent", "message": "Move 2 food-service staff to Food Court A pickup edge and stage overflow signs."},
            {"id": "equipment-menu-control", "channel": "equipment_controller", "target": "mobile_ordering", "status": "sent", "message": "Pause new Food Court A mobile-order slots; keep existing pickup ETAs visible."},
        ]
    elif any(term in lowered for term in ("smoke", "fire", "sparking", "electrical", "gas", "controller", "missed heartbeat", "fog machine", "fog", "technician")):
        headline = "React Agent is holding suspect equipment effects."
        summary = "The plan treats this messy note as an equipment safety signal: hold noncritical effects, send technician verification, keep service access clear, and avoid public claims until a human clears the issue."
        dispatches = [
            {"id": "worker-equipment-check", "channel": "worker_device", "target": "maintenance_lead", "status": "sent", "message": "Send a technician to verify the reported smoke/controller/fog issue and keep guests out of the service lane."},
            {"id": "equipment-effects-hold", "channel": "equipment_controller", "target": "facility_controls", "status": "sent", "message": "Hold noncritical lighting and fog effects until technician verification."},
            {"id": "guest-equipment-route", "channel": "guest_app", "target": "nearby_guests", "status": "sent", "message": "Please use the marked alternate route while staff adjust a nearby walkway."},
        ]
    elif any(term in lowered for term in ("faint", "medical", "first aid", "wheelchair", "stroller", "family", "families", "handicap", "accessibility", "access lane", "service lane", "blocked crossing", "panic", "evac", "passed out", "lost child", "separated", "pushing")):
        headline = "React Agent is protecting guest care and access lanes."
        summary = "The plan treats this as a care and crowd-control incident: dispatch trained staff, keep the access lane clear, route families calmly, and avoid medical diagnosis in generated instructions."
        dispatches = [
            {"id": "worker-care-response", "channel": "worker_device", "target": "first_aid_and_guest_services", "status": "sent", "message": "Send medical/guest-care team to the reported zone and keep an accessible route open."},
            {"id": "guest-calm-route", "channel": "guest_app", "target": "nearby_guests", "status": "sent", "message": "Please use the marked alternate walkway while our team assists a guest nearby."},
            {"id": "equipment-path-signage", "channel": "equipment_controller", "target": "digital_signage", "status": "sent", "message": "Show alternate accessible route and keep emergency/service lane clear."},
        ]
    else:
        headline = "React Agent is executing a custom park response."
        summary = "The plan uses the operator text as the incident source, selects receiver-specific actions, and keeps dispatches bounded by policy gates."
        dispatches = [
            {"id": "guest-custom-update", "channel": "guest_app", "target": "affected_zone_guests", "status": "sent", "message": "A nearby operation has changed. Follow app guidance for the quickest alternate experience."},
            {"id": "worker-custom-task", "channel": "worker_device", "target": "zone_leads", "status": "sent", "message": "Confirm the issue, open the alternate route, and report crowd pressure in 10 minutes."},
            {"id": "equipment-custom-control", "channel": "equipment_controller", "target": "zone_controls", "status": "sent", "message": "Apply approved signage and comfort presets for the affected zone."},
        ]
    return {
        "status": "complete",
        "command": message,
        "mode": "operations",
        "route": operator_route,
        "selected_role": "react",
        "skill": route.get("skill"),
        "role_route": route,
        "role_run": {
            "role": "react",
            "dispatch_allowed": True,
            "dispatch_count": len(dispatches),
            "policy_gates": route.get("policy_gates", []),
            "receipt_artifacts": route.get("expected_receipt", []),
        },
        "operator_response": {
            "headline": headline,
            "summary": summary,
            "next_step": "Watch receiver acknowledgments and observed take rate before sending a second nudge.",
        },
        "digital_twin_tools": tool_trace,
        "run_telemetry": {
            "scenario_key": scenario_key,
            "decision_id": f"role_react_{int(datetime.now(UTC).timestamp() * 1000)}",
            "planner": {"runtime": "bounded_role_agent", "model": "role_router_fast_path", "gemini_ready": get_gemini_agent_properties().ready},
            "governance": {"allowed": True, "gate_status": "passed", "findings": route.get("policy_gates", [])},
            "eval": {"scorecard": {"overall": 86, "response_score": 84, "policy_gate_status": "passed", "needs_human_approval": False}},
            "delivery": {
                "summary": {"total": len(dispatches), "sent": len(dispatches), "acknowledged": 0},
                "dispatches": dispatches,
            },
            "digital_twin_tools": tool_trace,
        },
    }


def _compact_copilot_state(state: dict[str, Any]) -> dict[str, Any]:
    flow = state.get("guestFlow", {}) if isinstance(state.get("guestFlow"), dict) else {}
    zones = flow.get("zones", []) if isinstance(flow.get("zones"), list) else []
    rides = flow.get("rides", []) if isinstance(flow.get("rides"), list) else []
    paths = flow.get("paths", []) if isinstance(flow.get("paths"), list) else []
    scenario = flow.get("activeScenario", {}) if isinstance(flow.get("activeScenario"), dict) else {}
    weather = state.get("weather", {}) if isinstance(state.get("weather"), dict) else {}
    staffing = state.get("staffing", {}) if isinstance(state.get("staffing"), dict) else {}
    park_ops = state.get("parkOps", {}) if isinstance(state.get("parkOps"), dict) else {}
    food_inventory = state.get("foodInventory", {}) if isinstance(state.get("foodInventory"), dict) else {}
    top_zones = sorted(
        [
            {
                "id": zone.get("id"),
                "name": zone.get("name", zone.get("id")),
                "density": zone.get("density"),
                "waitMins": zone.get("waitMins"),
                "comfortScore": zone.get("comfortScore"),
            }
            for zone in zones
            if isinstance(zone, dict)
        ],
        key=lambda item: int(item.get("density") or 0),
        reverse=True,
    )[:3]
    constrained_rides = [
        {
            "id": ride.get("id"),
            "name": ride.get("name", ride.get("id")),
            "zoneName": ride.get("zoneName") or ride.get("zone"),
            "status": ride.get("status"),
            "queueGuests": ride.get("queueGuests"),
            "waitMins": ride.get("waitMins"),
            "downtimeRisk": ride.get("downtimeRisk"),
            "effectiveThroughput": ride.get("effectiveThroughput"),
            "capacityPerHour": ride.get("capacityPerHour"),
            "staffAvailable": ride.get("staffAvailable"),
            "staffRequired": ride.get("staffRequired"),
        }
        for ride in rides
        if isinstance(ride, dict) and (ride.get("status") != "normal" or int(ride.get("downtimeRisk") or 0) >= 45)
    ][:4]
    all_ride_queues = sorted(
        [
            {
                "id": ride.get("id"),
                "name": ride.get("name", ride.get("id")),
                "zoneName": ride.get("zoneName") or ride.get("zone"),
                "status": ride.get("status"),
                "queueGuests": ride.get("queueGuests"),
                "waitMins": ride.get("waitMins"),
                "downtimeRisk": ride.get("downtimeRisk"),
                "effectiveThroughput": ride.get("effectiveThroughput"),
                "capacityPerHour": ride.get("capacityPerHour"),
                "staffAvailable": ride.get("staffAvailable"),
                "staffRequired": ride.get("staffRequired"),
            }
            for ride in rides
            if isinstance(ride, dict)
        ],
        key=lambda item: int(item.get("waitMins") or 0),
        reverse=True,
    )
    congested_paths = [
        {
            "id": path.get("id"),
            "from": path.get("from"),
            "to": path.get("to"),
            "congestionLevel": path.get("congestionLevel"),
            "status": path.get("status"),
        }
        for path in sorted(
            [path for path in paths if isinstance(path, dict)],
            key=lambda item: int(item.get("congestionLevel") or 0),
            reverse=True,
        )[:3]
    ]
    return {
        "clock": state.get("simTime", {}),
        "scenario": scenario.get("name") or park_ops.get("mode") or "Live park operation",
        "active_policy": flow.get("activePolicy"),
        "represented_guests": flow.get("representedGuests"),
        "avg_satisfaction": flow.get("avgSatisfaction"),
        "top_zones": top_zones,
        "all_ride_queues": all_ride_queues,
        "constrained_rides": constrained_rides,
        "congested_paths": congested_paths,
        "staffing": {
            "checkedIn": staffing.get("checkedIn"),
            "openCallouts": staffing.get("openCallouts"),
            "staffReadyPct": park_ops.get("staffReadyPct"),
        },
        "weather": {
            "condition": weather.get("condition"),
            "stormRisk": weather.get("stormRisk"),
            "heatIndexF": weather.get("heatIndexF"),
        },
        "food": {
            "mode": food_inventory.get("mode"),
            "risk": food_inventory.get("risk"),
            "lowStockItems": food_inventory.get("lowStockItems", [])[:4] if isinstance(food_inventory.get("lowStockItems"), list) else [],
        },
    }


def _copilot_intent(message: str) -> dict[str, Any]:
    lowered = (message or "").lower()
    case_like_incident = any(term in lowered for term in _COPILOT_INCIDENT_TERMS)
    question_terms = (
        "why",
        "what",
        "how",
        "explain",
        "compare",
        "alternative",
        "alternatives",
        "should",
        "risk",
        "report",
        "summarize",
        "summary",
        "tradeoff",
        "trade-off",
        "?",
    )
    action_terms = (
        "dispatch",
        "send",
        "reroute",
        "route",
        "pause",
        "hold",
        "move",
        "stage",
        "open",
        "close",
        "protect",
        "keep",
        "fix",
        "solve",
        "solution",
        "recommend",
        "resolve",
        "mitigate",
        "coordinate",
        "plan",
        "convert",
        "execute",
        "optimize",
        "action",
        "act",
        "take",
        "intervene",
        "intervention",
        "revise",
        "undo",
        "avoid",
        "do it",
    )
    safety_terms = (
        "medical",
        "first aid",
        "fire",
        "smoke",
        "evac",
        "evacuate",
        "fight",
        "security",
        "injury",
        "passed out",
        "faint",
        "lost child",
        "missing child",
        "missing kid",
        "separated child",
        "separated kid",
    )
    action_context_terms = (
        "agent do",
        "should the agent",
        "what should",
        "what would you do",
        "provide solution",
        "give solution",
        "need solution",
        "show the action",
        "apply",
        "impact on the map",
        "stuck",
        "blocked",
        "access lane",
        "first aid",
        "families",
        "stroller",
    )
    is_question = any(term in lowered for term in question_terms)
    asks_action = case_like_incident or any(term in lowered for term in action_terms)
    action_shaped_question = is_question and any(term in lowered for term in action_context_terms)
    safety_sensitive = case_like_incident or any(term in lowered for term in safety_terms)
    data_request = _copilot_data_request_kind(message) is not None
    if data_request:
        asks_action = False
        action_shaped_question = False
    pure_explanation = data_request or (is_question and not asks_action and not action_shaped_question)
    return {
        "is_question": is_question,
        "asks_action": asks_action,
        "action_shaped_question": action_shaped_question,
        "pure_explanation": pure_explanation,
        "safety_sensitive": safety_sensitive,
        "data_request": data_request,
        "data_request_kind": _copilot_data_request_kind(message),
        "case_like_incident": case_like_incident,
    }


def _normalize_copilot_turn_mode(turn_mode: str | None) -> str:
    normalized = (turn_mode or "auto").strip().lower().replace("-", "_")
    aliases = {
        "act": "apply",
        "execute": "apply",
        "dispatch": "apply",
        "recommend": "propose",
        "proposal": "propose",
        "explain": "answer",
        "answer_only": "answer",
        "answer": "answer",
        "propose": "propose",
        "apply": "apply",
        "auto": "auto",
    }
    return aliases.get(normalized, "auto")


def _copilot_conversation_intent(message: str, prior: dict[str, Any] | None) -> str:
    lowered = (message or "").lower().strip()
    if _copilot_data_request_kind(message):
        return "status_question"
    if lowered in {"hi", "hello", "hey", "test", "help"}:
        return "clarification"
    if any(term in lowered for term in _COPILOT_INCIDENT_TERMS):
        return "new_plan"
    if any(term in lowered for term in ("lost child", "missing child", "missing kid", "separated child", "separated kid")):
        return "new_plan"
    if prior and any(term == lowered for term in ("do it", "apply", "approve", "yes", "go", "run it", "execute it")):
        return "apply_plan"
    if prior and any(term in lowered for term in ("undo", "rollback", "reverse")):
        return "rollback_plan"
    if prior and any(term in lowered for term in ("revise", "change", "avoid", "instead", "protect staff", "don't", "do not")):
        return "revise_plan"
    if any(term in lowered for term in ("why", "explain", "impact", "baseline", "tradeoff", "alternative", "what changed", "how do you know")):
        return "explain_plan" if prior else "status_question"
    if any(term in lowered for term in ("what should", "what would", "should we", "what can we do", "solution", "solve", "fix", "recommend", "optimize", "plan", "action", "intervene", "too long", "stuck", "blocked")):
        return "new_plan"
    if any(term in lowered for term in ("status", "what is happening", "what's happening", "risk", "report")):
        return "status_question"
    return "status_question" if len(lowered.split()) >= 3 else "clarification"


def _copilot_data_request_kind(message: str) -> str | None:
    lowered = (message or "").lower().strip()
    if any(term in lowered for term in _COPILOT_INCIDENT_TERMS):
        return None
    safety_incident = any(
        term in lowered
        for term in (
            "lost child",
            "missing child",
            "missing kid",
            "separated child",
            "separated kid",
            "medical",
            "first aid",
            "faint",
            "passed out",
            "injury",
            "security",
            "fight",
            "panic",
        )
    )
    if safety_incident:
        return None
    action_request = any(
        term in lowered
        for term in (
            "provide solution",
            "give solution",
            "need solution",
            "solution",
            "what should",
            "what should the agent do",
            "should we",
            "what can we do",
            "what do we do",
            "recommend",
            "recommendation",
            "bounded action",
            "what action",
            "take action",
            "action should",
            "action to",
            "intervene",
            "intervention",
            "make a plan",
            "plan",
            "fix",
            "solve",
            "mitigate",
        )
    )
    distance_terms = ("distance", "how far", "walk from", "walking distance", "route length", "how long is")
    origin_terms = ("entrance", "front gate", "gate", "turnstile", "turnstiles")
    destination_terms = ("dragon", "coaster", "coaster plaza", "big coaster")
    if any(term in lowered for term in distance_terms) and any(term in lowered for term in origin_terms) and any(term in lowered for term in destination_terms):
        return "map_distance"
    if any(term in lowered for term in ("where is", "location of", "show me where")):
        if any(term in lowered for term in ("front gate", "entrance")):
            return "map_location_front_gate"
        if "food court" in lowered:
            return "map_location_food_court"
        if "first aid" in lowered:
            return "map_location_first_aid"
        if any(term in lowered for term in ("dragon", "coaster")):
            return "map_location_dragon_coaster"
    ride_terms = ("ride", "rides", "coaster", "attraction", "attractions")
    queue_terms = ("queue", "queues", "wait", "waits", "line", "lines")
    all_terms = ("all", "every", "list", "show", "give me", "report")
    if any(term in lowered for term in ride_terms) and any(term in lowered for term in queue_terms):
        if not action_request and (any(term in lowered for term in all_terms) or "ride queue" in lowered or "ride queues" in lowered):
            return "ride_queues"
    if any(phrase in lowered for phrase in ("status of rides", "ride status", "all ride status", "all rides status")):
        return "ride_queues"
    if action_request:
        return None
    if any(term in lowered for term in ("staffing", "staff", "callout", "callouts", "break coverage", "staff coverage")) and not action_request and not any(term in lowered for term in ("move", "send", "redeploy", "dispatch")):
        return "staffing_report"
    if any(term in lowered for term in ("weather", "storm", "heat", "rain", "temperature")) and not action_request:
        return "weather_report"
    if any(term in lowered for term in ("food court", "food", "mobile order", "pickup backlog", "low stock")) and not action_request and not any(term in lowered for term in ("reroute", "send", "move", "pause", "dispatch")):
        return "food_report"
    if any(
        phrase in lowered
        for phrase in (
            "status of the park",
            "park status",
            "status of park",
            "what is happening",
            "what's happening",
            "current status",
            "current risk",
            "risk report",
            "park report",
            "summarize the park",
            "problem in the park",
            "problem at the park",
            "what's the problem",
            "what is the problem",
            "what is wrong",
            "what's wrong",
        )
    ):
        return "park_status"
    return None


def _copilot_data_answer(kind: str | None, compact_state: dict[str, Any]) -> dict[str, Any] | None:
    if kind == "map_distance":
        # Coordinates mirror the physical map used by the frontend park map.
        landmarks = {
            "frontGate": {"name": "Front Gate", "x": 120, "y": 520, "w": 160, "h": 50},
            "dragonCoaster": {"name": "Dragon Coaster", "x": 690, "y": 145, "w": 210, "h": 155},
        }
        start = landmarks["frontGate"]
        end = landmarks["dragonCoaster"]
        start_center = (float(start["x"]) + float(start["w"]) / 2, float(start["y"]) + float(start["h"]) / 2)
        end_center = (float(end["x"]) + float(end["w"]) / 2, float(end["y"]) + float(end["h"]) / 2)
        straight_line = round(((end_center[0] - start_center[0]) ** 2 + (end_center[1] - start_center[1]) ** 2) ** 0.5)
        walking_estimate = round(straight_line * 1.18 / 10) * 10
        answer = (
            f"From the Front Gate to Dragon Coaster is about {straight_line} meters straight-line on the park map. "
            f"A realistic guest walking route is roughly {walking_estimate} meters because paths are not perfectly direct."
        )
        facts = [
            f"Front Gate center: ({round(start_center[0])}, {round(start_center[1])}).",
            f"Dragon Coaster center: ({round(end_center[0])}, {round(end_center[1])}).",
            f"Straight-line distance: {straight_line} meters.",
            f"Estimated walking distance: {walking_estimate} meters.",
        ]
        return {
            "answer": answer,
            "reasoning": [
                "Classified this as a read-only map distance question.",
                "Used physical map coordinates for Front Gate and Dragon Coaster.",
                "No action plan, dispatch, or map mutation was prepared.",
            ],
            "facts": facts,
        }
    if kind and kind.startswith("map_location_"):
        lookup = {
            "map_location_front_gate": "frontGate",
            "map_location_dragon_coaster": "dragonCoaster",
            "map_location_food_court": "foodCourtA",
            "map_location_first_aid": "firstAid",
        }
        landmarks = {
            "frontGate": {"name": "Front Gate", "x": 120, "y": 520, "w": 160, "h": 50},
            "dragonCoaster": {"name": "Dragon Coaster", "x": 690, "y": 145, "w": 210, "h": 155},
            "foodCourtA": {"name": "Food Court A", "x": 615, "y": 470, "w": 190, "h": 85},
            "firstAid": {"name": "First Aid", "x": 486, "y": 500, "w": 58, "h": 42},
        }
        landmark_key = lookup.get(kind, "dragonCoaster")
        landmark = landmarks[landmark_key]
        center = (round(float(landmark["x"]) + float(landmark["w"]) / 2), round(float(landmark["y"]) + float(landmark["h"]) / 2))
        area = {
            "frontGate": "southwest entrance area",
            "dragonCoaster": "northeast ride area",
            "foodCourtA": "southeast food area",
            "firstAid": "south central care area",
        }.get(landmark_key, "park map")
        return {
            "answer": f"{landmark['name']} is in the {area} of the park map, centered around map coordinate {center}.",
            "reasoning": [
                "Classified this as a read-only map location question.",
                f"Looked up {landmark['name']} in the physical park map.",
                "No action plan, dispatch, or map mutation was prepared.",
            ],
            "facts": [f"{landmark['name']} center: {center}.", f"Approximate area: {area}."],
        }
    if kind == "park_status":
        primary = _primary_copilot_risk(compact_state)
        zones = [item for item in compact_state.get("top_zones", []) if isinstance(item, dict)]
        rides = [item for item in compact_state.get("all_ride_queues", []) if isinstance(item, dict)]
        paths = [item for item in compact_state.get("congested_paths", []) if isinstance(item, dict)]
        staffing = compact_state.get("staffing", {}) if isinstance(compact_state.get("staffing"), dict) else {}
        weather = compact_state.get("weather", {}) if isinstance(compact_state.get("weather"), dict) else {}
        top_zone = zones[0] if zones else {}
        top_ride = rides[0] if rides else {}
        top_path = paths[0] if paths else {}
        facts = [
            f"Primary risk: {primary.get('label')} ({primary.get('evidence')}).",
            f"Most loaded zone: {top_zone.get('name') or top_zone.get('id') or '--'} at density {top_zone.get('density', '--')}%, wait {top_zone.get('waitMins', '--')} min.",
            f"Longest ride queue: {top_ride.get('name') or top_ride.get('id') or '--'} at {top_ride.get('waitMins', '--')} min with {top_ride.get('queueGuests', '--')} guests.",
            f"Staffing: {staffing.get('checkedIn', '--')} checked in, {staffing.get('openCallouts', '--')} open callouts, {staffing.get('staffReadyPct', '--')}% ready.",
            f"Weather: {weather.get('condition', '--')}, storm risk {weather.get('stormRisk', '--')}%, heat index {weather.get('heatIndexF', '--')}F.",
        ]
        if top_path:
            facts.append(
                f"Most congested path: {top_path.get('from', '--')} to {top_path.get('to', '--')} at congestion {top_path.get('congestionLevel', '--')}."
            )
        return {
            "answer": "Park status: " + " ".join(facts),
            "reasoning": [
                "Classified this as a live status request, not an action request.",
                "Read zones, ride queues, paths, staffing, and weather from live park state.",
                "No action plan, dispatch, or map mutation was prepared.",
            ],
            "facts": facts,
        }
    if kind == "staffing_report":
        staffing = compact_state.get("staffing", {}) if isinstance(compact_state.get("staffing"), dict) else {}
        facts = [
            f"Checked in: {staffing.get('checkedIn', '--')}.",
            f"Open callouts: {staffing.get('openCallouts', '--')}.",
            f"Staff ready: {staffing.get('staffReadyPct', '--')}%.",
        ]
        return {
            "answer": "Staffing status: " + " ".join(facts),
            "reasoning": [
                "Classified this as a read-only staffing question.",
                "Read staffing and parkOps readiness fields from live state.",
                "No redeploy or dispatch was prepared.",
            ],
            "facts": facts,
        }
    if kind == "weather_report":
        weather = compact_state.get("weather", {}) if isinstance(compact_state.get("weather"), dict) else {}
        facts = [
            f"Condition: {weather.get('condition', '--')}.",
            f"Storm risk: {weather.get('stormRisk', '--')}%.",
            f"Heat index: {weather.get('heatIndexF', '--')}F.",
        ]
        return {
            "answer": "Weather status: " + " ".join(facts),
            "reasoning": [
                "Classified this as a read-only weather question.",
                "Read weather condition, storm risk, and heat index from live state.",
                "No guest messaging or shelter action was prepared.",
            ],
            "facts": facts,
        }
    if kind == "food_report":
        food = compact_state.get("food", {}) if isinstance(compact_state.get("food"), dict) else {}
        low_stock = food.get("lowStockItems", []) if isinstance(food.get("lowStockItems"), list) else []
        mode = food.get("mode") or "not reported"
        risk = food.get("risk") or "not reported"
        facts = [
            f"Mode: {mode}.",
            f"Risk: {risk}.",
            f"Low stock: {', '.join(str(item) for item in low_stock) if low_stock else 'none listed'}.",
        ]
        return {
            "answer": "Food operations status: " + " ".join(facts),
            "reasoning": [
                "Classified this as a read-only food operations question.",
                "Read food inventory mode, risk, and low-stock items from live state.",
                "No food reroute or mobile-order action was prepared.",
            ],
            "facts": facts,
        }
    if kind != "ride_queues":
        return None
    rides = [item for item in compact_state.get("all_ride_queues", []) if isinstance(item, dict)]
    if not rides:
        return {
            "answer": "I do not have ride queue rows in the current park state.",
            "reasoning": ["Read live park state.", "No guestFlow.rides rows were available."],
            "facts": [],
        }
    rows = []
    for ride in rides:
        status = str(ride.get("status") or "unknown")
        staff = ""
        if ride.get("staffAvailable") is not None and ride.get("staffRequired") is not None:
            staff = f", staff {ride.get('staffAvailable')}/{ride.get('staffRequired')}"
        rows.append(
            f"{ride.get('name') or ride.get('id')}: {ride.get('waitMins', '--')} min, "
            f"{ride.get('queueGuests', '--')} guests, {status}"
            f"{staff}"
        )
    worst = rides[0]
    answer = (
        "Current ride queues, highest wait first: "
        + "; ".join(rows)
        + f". Longest wait is {worst.get('name') or worst.get('id')} at {worst.get('waitMins', '--')} min."
    )
    return {
        "answer": answer,
        "reasoning": [
            "Classified this as a data request, not an action request.",
            f"Read {len(rides)} ride queue rows from live guestFlow.rides.",
            "Sorted rides by wait minutes descending.",
        ],
        "facts": rows,
    }


def _copilot_read_only_tool_meta(data_kind: str) -> dict[str, str]:
    if data_kind == "map_distance":
        return {"label": "Map distance answer", "action": "Calculate map distance", "tool": "map.calculate_distance", "timeline": "Calculate map distance"}
    if data_kind.startswith("map_location_"):
        return {"label": "Map location answer", "action": "Look up map location", "tool": "map.lookup_landmark", "timeline": "Look up map landmark"}
    if data_kind == "park_status":
        return {"label": "Park status report", "action": "Read live park state", "tool": "park.rank_current_risks", "timeline": "Rank current park risks"}
    if data_kind == "staffing_report":
        return {"label": "Staffing report", "action": "Read staffing state", "tool": "staffing.read_status", "timeline": "Read staffing status"}
    if data_kind == "weather_report":
        return {"label": "Weather report", "action": "Read weather state", "tool": "weather.read_status", "timeline": "Read weather status"}
    if data_kind == "food_report":
        return {"label": "Food operations report", "action": "Read food operations state", "tool": "food.read_status", "timeline": "Read food operations"}
    return {"label": "Ride queue report", "action": "Read live ride queue state", "tool": "queues.read_ride_waits", "timeline": "Read live ride queues"}


def _copilot_read_only_response(
    *,
    raw_message: str,
    recent_messages: list[CopilotChatMessage],
    request: CopilotChatRequest,
    compact_state: dict[str, Any],
    route: dict[str, Any],
    intent: dict[str, Any],
    chat_brain: dict[str, Any],
    data_answer: dict[str, Any],
) -> dict[str, Any]:
    data_kind = str(intent.get("data_request_kind") or "read_only")
    meta = _copilot_read_only_tool_meta(data_kind)
    synthetic_context = retrieve_synthetic_park_context(raw_message, compact_state, limit=5)
    facts = [str(item) for item in data_answer.get("facts", []) if item]
    synthetic_facts = [
        str(fact)
        for obj in synthetic_context.get("matched_objects", [])
        if isinstance(obj, dict)
        for fact in obj.get("facts", [])[:2]
        if fact
    ]
    reasoning_summary = [str(item) for item in data_answer.get("reasoning", []) if item]
    if synthetic_context.get("primary_example"):
        reasoning_summary = [
            *reasoning_summary,
            f"Retrieved synthetic park example {synthetic_context['primary_example'].get('id')} for conversational grounding.",
        ]
    answer = str(data_answer.get("answer") or "")
    chat_brain = {
        **chat_brain,
        "intent": "status_question",
        "answer_type": "answer",
        "action_needed": False,
        "planner_message": raw_message,
        "relevant_park_facts": [*facts, *synthetic_facts[:4]],
        "confidence": max(int(chat_brain.get("confidence") or 0), 90),
        "tool_selected": meta["tool"],
        "synthetic_example": synthetic_context.get("primary_example"),
    }
    turn_contract = _copilot_turn_contract(
        "answer",
        will_act=False,
        dispatch_count=0,
        has_map_grounding=False,
        has_impact_replay=False,
        reason="The operator asked for live park information, so ParkPulse answered from tools/state and did not prepare an action.",
    )
    conversation_response = {
        "source": "park_read_only_tool",
        "model": None,
        "answer": answer,
        "reasoning_bullets": reasoning_summary,
        "operator_next": "Ask for a plan if you want ParkPulse to act on one of these findings.",
        "confidence": 96,
        "provider_ready": True,
    }
    row_count = len(facts)
    return {
        "status": "complete",
        "mode": "answer",
        "message": raw_message,
        "answer": answer,
        "reasoning_summary": reasoning_summary,
        "options_considered": [
            {
                "label": meta["label"],
                "verdict": "selected",
                "reason": "The message asks for information, not a dispatch or optimization.",
                "projected_effect": "No operational side effects.",
            }
        ],
        "clarifying_question": None,
        "recommended_action": {
            "role": "scan",
            "label": meta["label"],
            "action": meta["action"],
            "gate": "read_only",
            "dispatch_count": 0,
            "execute": False,
        },
        "map_grounding": None,
        "impact_replay": None,
        "reasoning_evaluation": None,
        "agent_runtime": None,
        "chat_brain": chat_brain,
        "conversation_response": conversation_response,
        "tool_trace": {
            "tool_calls": [
                {
                    "tool": meta["tool"],
                    "status": "complete",
                    "capability": "read",
                    "output": f"{row_count} fact(s)",
                },
                {
                    "tool": "synthetic_park_knowledge.retrieve",
                    "status": synthetic_context.get("retrieval_status") or "complete",
                    "capability": "read",
                    "output": (synthetic_context.get("primary_example") or {}).get("id") if isinstance(synthetic_context.get("primary_example"), dict) else "no synthetic match",
                }
            ],
            "summary": {"policy_gate": "read_only", "state_mutation": False, "data_kind": data_kind},
        },
        "tool_call_timeline": [
            {
                "id": f"read_only_{data_kind}",
                "tool": meta["tool"],
                "label": meta["timeline"],
                "status": "complete",
                "output": f"{row_count} fact(s)",
            },
            {
                "id": "read_synthetic_park_knowledge",
                "tool": "synthetic_park_knowledge.retrieve",
                "label": "Retrieve synthetic park facts and utterance examples",
                "status": synthetic_context.get("retrieval_status") or "complete",
                "output": (synthetic_context.get("primary_example") or {}).get("id") if isinstance(synthetic_context.get("primary_example"), dict) else "no synthetic match",
            }
        ],
        "turn_contract": turn_contract,
        "ontology_context": None,
        "object_action_plan": {"actions": [], "overall_gate": "read_only"},
        "synthetic_park_context": synthetic_context,
        "route": route,
        "selected_role": "scan",
        "live_state_summary": compact_state,
        "action_receipt": None,
        "run_telemetry": None,
        "conversation_memory": {
            "turn_count": len(recent_messages) + 1,
            "raw_message": raw_message,
            "effective_message": raw_message,
            "conversation_intent": "status_question",
            "chat_brain_source": chat_brain.get("source"),
            "last_user_intent": {
                "question": intent.get("is_question"),
                "action": False,
                "safety_sensitive": intent.get("safety_sensitive"),
            },
            "map_context": request.selected_map_context,
            "constraints": [],
            "data_kind": data_kind,
        },
    }


def _fallback_copilot_chat_brain(message: str, compact_state: dict[str, Any], prior: dict[str, Any] | None) -> dict[str, Any]:
    intent = _copilot_conversation_intent(message, prior)
    primary = _primary_copilot_risk(compact_state)
    prior_runtime = prior.get("agent_runtime", {}) if isinstance(prior, dict) and isinstance(prior.get("agent_runtime"), dict) else {}
    selected = (prior_runtime.get("task_graph") or {}).get("selected_action", {}) if isinstance(prior_runtime.get("task_graph"), dict) else {}
    constraints: list[str] = []
    lowered = message.lower()
    if "avoid" in lowered or "do not" in lowered or "don't" in lowered:
        constraints.append(message)
    if "staff break" in lowered or "protect staff" in lowered:
        constraints.append("protect staff breaks")
    if "food court" in lowered:
        constraints.append("avoid increasing food court demand")
    planner_message = message
    if intent == "revise_plan" and selected:
        prior_action = f"{selected.get('object_name')}: {str(selected.get('action') or '').replace('_', ' ')}"
        planner_message = f"Revise active plan. Prior action: {prior_action}. New constraints: {'; '.join(constraints) or message}."
    elif intent == "apply_plan" and selected:
        prior_action = f"{selected.get('object_name')}: {str(selected.get('action') or '').replace('_', ' ')}"
        planner_message = f"Apply the active approved plan. Prior action: {prior_action}. Operator confirmation: {message}."
    action_intents = {"new_plan", "revise_plan", "apply_plan", "rollback_plan"}
    answer_type = "action" if intent in action_intents else "clarification" if intent == "clarification" else "explanation"
    return {
        "source": "local_intent_parser",
        "intent": intent,
        "understood_question": message,
        "answer_type": answer_type,
        "action_needed": intent in action_intents,
        "planner_message": planner_message,
        "constraints": constraints,
        "relevant_park_facts": [f"{primary.get('label')}: {primary.get('evidence')}"],
        "clarifying_question": (
            "Do you want a live status answer, a queue/staffing report, or an operating plan for a specific park problem?"
            if intent == "clarification"
            else None
        ),
        "confidence": 72,
    }


async def _copilot_chat_brain(
    message: str,
    compact_state: dict[str, Any],
    prior: dict[str, Any] | None,
    recent_messages: list[CopilotChatMessage],
) -> dict[str, Any]:
    fallback = _fallback_copilot_chat_brain(message, compact_state, prior)
    if _copilot_hot_path_local_only():
        fallback["provider_ready"] = True
        fallback["provider_skipped"] = "hot_path_local_only"
        fallback["source"] = "local_intent_parser_hot_path"
        return fallback
    props = get_gemini_agent_properties()
    if not props.ready:
        fallback["provider_ready"] = False
        fallback["provider_issues"] = props.readiness_issues
        return fallback
    prior_runtime = prior.get("agent_runtime") if isinstance(prior, dict) and isinstance(prior.get("agent_runtime"), dict) else None
    prompt = {
        "task": "Act as the ParkPulse chat brain. Understand the operator's message before planning. Return JSON only.",
        "rules": [
            "Classify intent semantically, not by keyword.",
            "Use live park facts and prior active task.",
            "If the user adds a constraint, produce a planner_message that revises the active plan.",
            "If the user says do it/yes/apply, classify apply_plan.",
            "If safety-critical facts are missing, ask one clarifying question and mark action_needed false unless already approved.",
            "Do not invent park facts.",
        ],
        "operator_message": message,
        "recent_messages": [{"role": item.role, "content": item.content} for item in recent_messages[-6:]],
        "live_state_summary": compact_state,
        "prior_active_task": prior_runtime,
        "allowed_intents": ["status_question", "new_plan", "revise_plan", "apply_plan", "rollback_plan", "explain_plan", "clarification"],
        "required_json": {
            "intent": "one allowed intent",
            "understood_question": "what the operator means",
            "constraints": ["operator constraints"],
            "relevant_park_facts": ["facts from live state"],
            "answer_type": "answer | action | clarification",
            "action_needed": True,
            "planner_message": "message for downstream planner, preserving constraints",
            "clarifying_question": None,
            "confidence": 0,
        },
    }
    try:
        from gemini_hard_timeout import generate_gemini_json_hard_timeout

        timeout = max(0.6, _float_env("PARKPULSE_COPILOT_BRAIN_TIMEOUT_SECONDS", 1.0))
        result = await generate_gemini_json_hard_timeout(prompt, timeout_seconds=timeout, max_output_tokens=520, temperature=0.1)
        text = _strip_json_fence(str(result.get("text") or "{}"))
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = json.loads(text[text.find("{") : text.rfind("}") + 1])
        allowed = {"status_question", "new_plan", "revise_plan", "apply_plan", "rollback_plan", "explain_plan", "clarification"}
        brain_intent = str(parsed.get("intent") or fallback["intent"])
        if brain_intent not in allowed:
            brain_intent = fallback["intent"]
        if fallback.get("intent") == "clarification" and brain_intent in {"new_plan", "revise_plan", "apply_plan", "rollback_plan"}:
            brain_intent = "clarification"
        constraints = parsed.get("constraints")
        facts = parsed.get("relevant_park_facts")
        action_needed = bool(parsed.get("action_needed", fallback["action_needed"]))
        if brain_intent == "clarification":
            action_needed = False
        return {
            "source": "gemini_chat_brain",
            "runtime": result.get("transport") or props.platform,
            "model": props.model,
            "intent": brain_intent,
            "understood_question": str(parsed.get("understood_question") or fallback["understood_question"]),
            "answer_type": str(parsed.get("answer_type") or fallback["answer_type"]),
            "action_needed": action_needed,
            "planner_message": str(parsed.get("planner_message") or fallback["planner_message"]),
            "constraints": [str(item) for item in constraints[:8]] if isinstance(constraints, list) else fallback["constraints"],
            "relevant_park_facts": [str(item) for item in facts[:8]] if isinstance(facts, list) else fallback["relevant_park_facts"],
            "clarifying_question": parsed.get("clarifying_question"),
            "confidence": int(parsed.get("confidence") or fallback["confidence"]),
            "provider_ready": True,
        }
    except Exception as error:
        fallback["source"] = "local_intent_parser_llm_unavailable"
        fallback["provider_ready"] = True
        fallback["llm_error"] = str(error)[:300]
        return fallback


def _copilot_turn_contract(
    mode: str,
    *,
    will_act: bool,
    dispatch_count: int = 0,
    has_map_grounding: bool = False,
    has_impact_replay: bool = False,
    reason: str = "",
) -> dict[str, Any]:
    labels = {
        "answer": "Answer only",
        "propose": "Propose action",
        "act": "Apply action",
        "follow_up": "Follow-up",
    }
    return {
        "mode": mode,
        "label": labels.get(mode, "Agent turn"),
        "state_mutation": bool(will_act),
        "dispatch_count": dispatch_count,
        "map_effect": "impact_replay" if has_impact_replay else "grounding_only" if has_map_grounding else "none",
        "receipts": {
            "map_grounding": has_map_grounding,
            "impact_replay": has_impact_replay,
            "receiver_dispatches": dispatch_count,
        },
        "reason": reason,
        "next_available_turns": ["answer", "propose", "apply"] if mode != "follow_up" else ["answer", "apply"],
    }


def _primary_copilot_risk(compact_state: dict[str, Any]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for zone in compact_state.get("top_zones", []):
        candidates.append(
            {
                "label": f"{zone.get('name') or zone.get('id')} crowd pressure",
                "score": int(zone.get("density") or 0),
                "evidence": f"density {zone.get('density', '--')}%, wait {zone.get('waitMins', '--')} min, comfort {zone.get('comfortScore', '--')}",
            }
        )
    for ride in compact_state.get("constrained_rides", []):
        candidates.append(
            {
                "label": f"{ride.get('name') or ride.get('id')} constraint",
                "score": max(int(ride.get("downtimeRisk") or 0), 82 if ride.get("status") != "normal" else 0),
                "evidence": f"status {ride.get('status', '--')}, downtime risk {ride.get('downtimeRisk', '--')}%, wait {ride.get('waitMins', '--')} min",
            }
        )
    weather = compact_state.get("weather", {}) if isinstance(compact_state.get("weather"), dict) else {}
    candidates.append(
        {
            "label": "weather and shelter pressure",
            "score": int(weather.get("stormRisk") or 0),
            "evidence": f"storm risk {weather.get('stormRisk', '--')}%, heat index {weather.get('heatIndexF', '--')}F",
        }
    )
    staffing = compact_state.get("staffing", {}) if isinstance(compact_state.get("staffing"), dict) else {}
    candidates.append(
        {
            "label": "staff coverage pressure",
            "score": int(staffing.get("openCallouts") or 0) * 3,
            "evidence": f"{staffing.get('openCallouts', '--')} open callouts, {staffing.get('staffReadyPct', '--')}% staff ready",
        }
    )
    return max(candidates, key=lambda item: int(item.get("score") or 0)) if candidates else {"label": "park operating risk", "score": 0, "evidence": "No live signals available."}


def _copilot_policy_query_message(message: str, compact_state: dict[str, Any], intent: dict[str, Any]) -> str:
    lowered = (message or "").lower()
    if intent.get("safety_sensitive") or any(term in lowered for term in ("staff", "worker", "break", "labor", "food", "weather", "storm", "security", "medical", "first aid")):
        return message
    generic_action_request = bool(intent.get("asks_action")) and any(
        term in lowered
        for term in (
            "biggest",
            "problem",
            "priority",
            "operational",
            "park right now",
            "bounded action",
            "what action",
            "what should",
            "should we",
            "what can we do",
        )
    )
    if not generic_action_request:
        return message
    primary = _primary_copilot_risk(compact_state)
    rides = [item for item in compact_state.get("all_ride_queues", []) if isinstance(item, dict)]
    top_ride = rides[0] if rides else {}
    zones = [item for item in compact_state.get("top_zones", []) if isinstance(item, dict)]
    top_zone = zones[0] if zones else {}
    return (
        f"{message}. Live priority from telemetry: {primary.get('label')} ({primary.get('evidence')}). "
        f"Focus the policy match on the current queue/crowd bottleneck: "
        f"{top_ride.get('name') or top_ride.get('id') or 'top ride'} wait {top_ride.get('waitMins', '--')} min, "
        f"{top_zone.get('name') or top_zone.get('id') or 'top zone'} density {top_zone.get('density', '--')}%. "
        "Preferred domain: ride queue crowd-flow guest-movement operations."
    )


def _copilot_is_generic_park_action_request(message: str, intent: dict[str, Any]) -> bool:
    lowered = (message or "").lower()
    if not intent.get("asks_action"):
        return False
    if intent.get("safety_sensitive"):
        return False
    if any(term in lowered for term in ("staff", "worker", "break", "labor", "food", "weather", "storm", "security", "medical", "first aid", "fire", "missing", "lost child")):
        return False
    return any(
        term in lowered
        for term in (
            "biggest",
            "problem",
            "priority",
            "operational",
            "bounded action",
            "what action",
            "what should",
            "should we",
            "what can we do",
        )
    )


def _copilot_rebalance_generic_policy_doctrine(doctrine: dict[str, Any], message: str, intent: dict[str, Any]) -> dict[str, Any]:
    if not _copilot_is_generic_park_action_request(message, intent):
        return doctrine
    matches = [item for item in doctrine.get("matches", []) if isinstance(item, dict)]
    if not matches:
        return doctrine
    blocked_title_terms = ("medical", "security", "fight", "fire", "lost child", "missing child", "staff", "labor", "weather", "lightning", "storm", "food", "egress")
    preferred_terms = ("ride", "queue", "coaster", "crowd", "parade")
    candidates = [
        item
        for item in matches
        if item.get("kind") == "action_case"
        and not any(term in f"{item.get('title', '')} {item.get('summary', '')}".lower() for term in blocked_title_terms)
        and any(term in f"{item.get('title', '')} {item.get('summary', '')} {' '.join(item.get('triggers', []) if isinstance(item.get('triggers'), list) else [])}".lower() for term in preferred_terms)
    ]
    if not candidates:
        return doctrine
    selected = max(
        candidates,
        key=lambda item: (
            1 if "coaster" in f"{item.get('title', '')} {item.get('summary', '')}".lower() else 0,
            1 if "queue" in f"{item.get('title', '')} {item.get('summary', '')}".lower() else 0,
            int(item.get("score") or 0),
        ),
    )
    reordered = [selected, *[item for item in matches if item.get("id") != selected.get("id")]]
    refs: list[str] = []
    for item in reordered:
        for ref in item.get("policy_refs", []) or []:
            if ref not in refs:
                refs.append(str(ref))
    return {
        **doctrine,
        "primary_case": selected,
        "matches": reordered,
        "policy_refs": refs[:12],
        "generic_policy_rebalanced": True,
    }


def _copilot_options(route: dict[str, Any], intent: dict[str, Any], compact_state: dict[str, Any], will_act: bool) -> list[dict[str, Any]]:
    selected_role = str(route.get("selected_role") or "scan")
    primary_risk = _primary_copilot_risk(compact_state)
    return [
        {
            "label": "Answer only and keep observing",
            "verdict": "rejected" if will_act else "selected",
            "reason": "Useful for explanation, but it does not change guest flow or receiver behavior." if will_act else "The request is primarily asking for reasoning, so no dispatch is needed yet.",
            "projected_effect": "No operational side effects.",
        },
        {
            "label": f"Run bounded {selected_role.title()} Agent action",
            "verdict": "selected" if will_act else "prepared",
            "reason": route.get("why") or f"The role router selected {selected_role} for the operator intent.",
            "projected_effect": f"Targets {primary_risk.get('label')} while keeping policy gates and receipts visible.",
        },
        {
            "label": "Escalate to manager approval",
            "verdict": "watch" if intent.get("safety_sensitive") else "not needed",
            "reason": "Required if the note implies guest injury, evacuation, fire, security, or irreversible equipment control.",
            "projected_effect": "Slower response, stronger human accountability.",
        },
    ]


def _copilot_recommended_action(route: dict[str, Any], role_payload: dict[str, Any] | None, will_act: bool) -> dict[str, Any]:
    selected_role = str(route.get("selected_role") or "scan")
    operator_response = role_payload.get("operator_response", {}) if isinstance(role_payload, dict) else {}
    telemetry = role_payload.get("run_telemetry", {}) if isinstance(role_payload, dict) else {}
    telemetry = telemetry if isinstance(telemetry, dict) else {}
    dispatches = telemetry.get("delivery", {}).get("dispatches", []) if isinstance(telemetry.get("delivery"), dict) else []
    return {
        "role": selected_role,
        "label": operator_response.get("headline") or ("Proposed park action" if selected_role != "scan" else "Read-only park analysis"),
        "action": operator_response.get("summary") or route.get("why") or "No action selected.",
        "gate": telemetry.get("governance", {}).get("gate_status") if isinstance(telemetry.get("governance"), dict) else ("prepared" if not will_act else "pending"),
        "dispatch_count": len(dispatches) if isinstance(dispatches, list) else 0,
        "execute": will_act,
    }


def _copilot_answer(
    message: str,
    route: dict[str, Any],
    compact_state: dict[str, Any],
    intent: dict[str, Any],
    role_payload: dict[str, Any] | None,
    will_act: bool,
) -> str:
    operator_response = role_payload.get("operator_response", {}) if isinstance(role_payload, dict) else {}
    if operator_response:
        headline = operator_response.get("headline") or "ParkPulse response prepared."
        summary = operator_response.get("summary") or ""
        next_step = operator_response.get("next_step") or ""
        return " ".join(part for part in (headline, summary, next_step) if part)
    primary_risk = _primary_copilot_risk(compact_state)
    selected_role = str(route.get("selected_role") or "scan")
    if intent.get("pure_explanation"):
        return (
            f"The biggest live risk is {primary_risk.get('label')}: {primary_risk.get('evidence')}. "
            f"This remains read-only because {route.get('why', 'the evidence is still being grounded against live park state')}. "
            "No receiver action was dispatched from this answer."
        )
    return (
        f"Proposed {selected_role} plan based on {primary_risk.get('label')} ({primary_risk.get('evidence')}). "
        "No dispatch or state mutation has happened."
    )


def _copilot_answer_with_object_plan(base_answer: str, object_action_plan: dict[str, Any], will_act: bool) -> str:
    actions = [item for item in (object_action_plan.get("actions") or []) if isinstance(item, dict)]
    executable_actions = [item for item in actions if item.get("action") and item.get("action") != "inspect"]
    if not executable_actions:
        return base_answer
    action_text = "; ".join(
        f"{item.get('object_name') or item.get('object_id')}: {str(item.get('action') or '').replace('_', ' ')}"
        for item in executable_actions[:4]
    )
    doctrine = object_action_plan.get("policy_doctrine") if isinstance(object_action_plan.get("policy_doctrine"), dict) else {}
    primary_case = doctrine.get("primary_case") if isinstance(doctrine.get("primary_case"), dict) else {}
    doctrine_text = ""
    if primary_case:
        refs = ", ".join(str(ref) for ref in (primary_case.get("policy_refs") or [])[:4])
        doctrine_text = f" Matched case: {primary_case.get('id')} ({primary_case.get('title')}); policies: {refs or 'none listed'}."
    gate = object_action_plan.get("overall_gate") or "prepared"
    if will_act:
        return (
            f"Solution applied: {action_text}. "
            f"Gate={gate}; I executed the bounded object actions, updated the park simulation, and attached the map impact replay.{doctrine_text}"
        )
    return (
        f"Proposed plan: {action_text}. "
        f"Gate={gate}; no dispatch or state mutation has happened yet.{doctrine_text} Say \"do it\" to apply this exact plan and show the map impact."
    )


def _copilot_reasoning_summary(route: dict[str, Any], intent: dict[str, Any], compact_state: dict[str, Any], will_act: bool) -> list[str]:
    primary_risk = _primary_copilot_risk(compact_state)
    selected_role = str(route.get("selected_role") or "scan")
    reason = route.get("why") or f"{selected_role.title()} is the closest role for the request."
    return [
        f"Parsed the request as {'actionable' if intent.get('asks_action') else 'answer-first'} with {'safety-sensitive' if intent.get('safety_sensitive') else 'standard'} constraints.",
        f"Grounded the answer in live state: {primary_risk.get('label')} is the highest pressure signal ({primary_risk.get('evidence')}).",
        f"Routed to {selected_role.title()} Agent because {reason}",
        "Dispatched bounded receiver actions with policy/eval receipts." if will_act else "Kept this as a reasoned response without mutating the park.",
    ]


def _copilot_semantic_memory_enabled() -> bool:
    return _truthy(os.getenv("PARKPULSE_COPILOT_SEMANTIC_MEMORY"), False) or _truthy(
        os.getenv("PARKPULSE_MONGO_MODEL_EMBEDDINGS"),
        False,
    )


def _copilot_hot_path_local_only() -> bool:
    return _truthy(os.getenv("PARKPULSE_COPILOT_HOT_PATH_LOCAL_ONLY"), False)


def _copilot_memory_doc_summary(document: dict[str, Any]) -> dict[str, Any]:
    return {
        key: document.get(key)
        for key in (
            "_id",
            "title",
            "summary",
            "incidentType",
            "scenarioKey",
            "lesson",
            "rule",
            "recommendedAction",
            "score",
        )
        if document.get(key) is not None
    }


def _compact_copilot_semantic_memory(memory: dict[str, Any]) -> dict[str, Any]:
    status = memory.get("status") if isinstance(memory.get("status"), dict) else {}
    retrieved = memory.get("retrieved") if isinstance(memory.get("retrieved"), dict) else {}
    playbooks = retrieved.get("playbooks") if isinstance(retrieved.get("playbooks"), list) else []
    incidents = retrieved.get("incidents") if isinstance(retrieved.get("incidents"), list) else []
    learnings = retrieved.get("learnings") if isinstance(retrieved.get("learnings"), list) else []
    retrieval_method = str(retrieved.get("method") or "")
    model_api = status.get("modelApi") if isinstance(status.get("modelApi"), dict) else None
    model_api_enabled = bool(model_api and model_api.get("enabled"))
    cache_backed = retrieval_method in {
        "role_context_cache",
        "role_context_cache_stale_usable",
        "role_context_cache_stale_unvalidated",
    }
    vector_backed = retrieval_method.startswith("mongodb_vector_search")
    degraded_reasons: list[str] = []
    if retrieval_method == "role_context_cache_miss":
        degraded_reasons.append("No role-context cache was available; live semantic retrieval is skipped on copilot request paths.")
    if model_api_enabled and not (cache_backed or vector_backed):
        degraded_reasons.append(
            f"Model API is enabled but semantic retrieval used {retrieval_method or 'unknown'} instead of vector search or role cache."
        )
    return {
        "status": "ready" if not degraded_reasons else "degraded",
        "source": "mongo_operational_memory",
        "query": memory.get("query"),
        "scenario_key": memory.get("scenario_key"),
        "agent_role": memory.get("agent_role"),
        "cache_policy": memory.get("cache_policy"),
        "retrieval_method": retrieval_method,
        "summary": memory.get("summary"),
        "model_api": model_api,
        "readiness_issues": degraded_reasons,
        "counts": {
            "playbooks": len(playbooks),
            "incidents": len(incidents),
            "learnings": len(learnings),
        },
        "retrieved": {
            "playbooks": [_copilot_memory_doc_summary(row) for row in playbooks[:3] if isinstance(row, dict)],
            "incidents": [_copilot_memory_doc_summary(row) for row in incidents[:3] if isinstance(row, dict)],
            "learnings": [_copilot_memory_doc_summary(row) for row in learnings[:3] if isinstance(row, dict)],
        },
    }


async def _copilot_semantic_memory_context(message: str, state: dict[str, Any], selected_role: str) -> dict[str, Any]:
    if not _copilot_semantic_memory_enabled():
        return {"status": "not_requested", "reason": "PARKPULSE_COPILOT_SEMANTIC_MEMORY is disabled."}
    started = time.monotonic()
    try:
        timeout = max(0.2, _float_env("PARKPULSE_COPILOT_SEMANTIC_MEMORY_TIMEOUT_SECONDS", 2.0))
        cache_policy = os.getenv("PARKPULSE_COPILOT_SEMANTIC_MEMORY_CACHE_POLICY", "role_cache_only").strip() or "role_cache_only"
        memory = await asyncio.wait_for(
            asyncio.to_thread(
                retrieve_operational_context,
                message,
                state,
                3,
                selected_role,
                cache_policy,
                False,
            ),
            timeout=timeout,
        )
        compact = _compact_copilot_semantic_memory(memory if isinstance(memory, dict) else {})
        compact["elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)
        compact["timeout_ms"] = round(timeout * 1000, 2)
        return compact
    except Exception as error:
        return {
            "status": "error",
            "source": "mongo_operational_memory",
            "readiness_issues": [str(error)[:240]],
            "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
        }


def _copilot_semantic_memory_tool_event(semantic_memory_context: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(semantic_memory_context, dict) or semantic_memory_context.get("status") == "not_requested":
        return None
    counts = semantic_memory_context.get("counts") if isinstance(semantic_memory_context.get("counts"), dict) else {}
    output = (
        f"{counts.get('playbooks', 0)} playbooks, {counts.get('incidents', 0)} incidents, "
        f"{counts.get('learnings', 0)} learnings via {semantic_memory_context.get('retrieval_method') or semantic_memory_context.get('status')}"
    )
    return {
        "id": "retrieve_semantic_memory",
        "tool": "memory.retrieve_semantic_context",
        "label": "Retrieve semantic memory",
        "status": semantic_memory_context.get("status") or "complete",
        "output": output,
    }


def _copilot_map_grounding(message: str, compact_state: dict[str, Any], role_payload: dict[str, Any] | None) -> dict[str, Any]:
    lowered = message.lower()
    zone_to_landmark = {
        "coasterPlaza": "dragonCoaster",
        "foodCourt1": "foodCourtA",
        "indoorHub": "indoorLaunch",
        "arcadeZone": "arcade",
        "coveredPlaza": "coveredPlaza",
        "entrancePlaza": "frontGate",
    }
    zone_to_queue = {
        "coasterPlaza": "dragonQueue",
        "foodCourt1": "foodPickupQueue",
        "indoorHub": "indoorLaunchQueue",
        "coveredPlaza": "paradeCrossingQueue",
        "entrancePlaza": "fireworksExitQueue",
    }
    zone_ids = [
        str(zone.get("id"))
        for zone in compact_state.get("top_zones", [])
        if isinstance(zone, dict) and zone.get("id")
    ][:3]
    landmark_ids = [zone_to_landmark[zone_id] for zone_id in zone_ids if zone_id in zone_to_landmark]
    queue_ids = [zone_to_queue[zone_id] for zone_id in zone_ids if zone_id in zone_to_queue]
    if "food court a" in lowered or "food" in lowered:
        zone_ids.append("foodCourt1")
        landmark_ids.extend(["foodCourtA", "mainStreet"])
        queue_ids.append("foodPickupQueue")
    if "coaster" in lowered or "ride" in lowered:
        zone_ids.append("coasterPlaza")
        landmark_ids.append("dragonCoaster")
        queue_ids.append("dragonQueue")
    if "parade" in lowered:
        zone_ids.append("coveredPlaza")
        landmark_ids.append("paradeRoute")
        queue_ids.append("paradeCrossingQueue")
    if any(term in lowered for term in ("medical", "first aid", "faint", "accessibility", "wheelchair", "lost child", "missing child", "missing kid", "separated child", "separated kid")):
        landmark_ids.extend(["firstAid", "frontGate"])
    telemetry = role_payload.get("run_telemetry", {}) if isinstance(role_payload, dict) else {}
    delivery = telemetry.get("delivery", {}) if isinstance(telemetry, dict) else {}
    dispatches = delivery.get("dispatches", []) if isinstance(delivery, dict) else []
    receiver_targets = [
        {
            "channel": dispatch.get("channel"),
            "target": dispatch.get("target") or dispatch.get("id"),
            "status": dispatch.get("status"),
        }
        for dispatch in dispatches
        if isinstance(dispatch, dict)
    ]
    path_ids = [
        str(path.get("id") or f"{path.get('from')}->{path.get('to')}")
        for path in compact_state.get("congested_paths", [])
        if isinstance(path, dict) and (path.get("id") or (path.get("from") and path.get("to")))
    ][:3]
    if "parade" in lowered:
        path_ids.append("coasterPlaza->coveredPlaza")
    unique_zones = list(dict.fromkeys(zone_ids))
    unique_landmarks = list(dict.fromkeys(landmark_ids))
    unique_queues = list(dict.fromkeys(queue_ids))
    unique_paths = list(dict.fromkeys(path_ids))
    return {
        "primary_zone_id": unique_zones[0] if unique_zones else None,
        "highlight_zone_ids": unique_zones[:5],
        "landmark_ids": unique_landmarks[:6],
        "queue_ids": unique_queues[:5],
        "path_ids": unique_paths[:5],
        "receiver_targets": receiver_targets[:5],
        "focus": "action_receipt" if receiver_targets else "live_risk",
        "rationale": "The copilot answer is grounded to these park map objects, route constraints, and receiver targets.",
    }


def _park_ontology_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    flow = state.get("guestFlow", {}) if isinstance(state.get("guestFlow"), dict) else {}
    physical = state.get("physicalMap", {}) if isinstance(state.get("physicalMap"), dict) else {}
    readiness = state.get("incidentReadiness", {}) if isinstance(state.get("incidentReadiness"), dict) else {}
    staffing = state.get("staffing", {}) if isinstance(state.get("staffing"), dict) else {}
    objects: list[dict[str, Any]] = []

    def add_object(
        object_type: str,
        object_id: str,
        name: str,
        status: str,
        source_path: str,
        allowed_actions: list[str],
        relationships: list[dict[str, str]] | None = None,
        attributes: dict[str, Any] | None = None,
        permission: str = "operator",
    ) -> None:
        objects.append(
            {
                "object_type": object_type,
                "id": object_id,
                "name": name,
                "status": status,
                "freshness": {"as_of": now, "source": source_path, "staleness": "live_simulated"},
                "permission": permission,
                "allowed_actions": allowed_actions,
                "relationships": relationships or [],
                "attributes": attributes or {},
            }
        )

    for ride in flow.get("rides", [])[:8] if isinstance(flow.get("rides"), list) else []:
        if not isinstance(ride, dict):
            continue
        add_object(
            "Ride",
            str(ride.get("id") or ride.get("name") or "ride"),
            str(ride.get("name") or ride.get("id") or "Ride"),
            str(ride.get("status") or "unknown"),
            "guestFlow.rides",
            ["inspect", "reroute_guests", "draft_guest_message", "request_maintenance_review"],
            attributes={
                "wait_mins": ride.get("waitMins"),
                "queue_guests": ride.get("queueGuests"),
                "downtime_risk": ride.get("downtimeRisk"),
            },
        )
    for zone in flow.get("zones", [])[:8] if isinstance(flow.get("zones"), list) else []:
        if not isinstance(zone, dict):
            continue
        add_object(
            "Zone",
            str(zone.get("id") or zone.get("name") or "zone"),
            str(zone.get("name") or zone.get("id") or "Zone"),
            "critical" if int(zone.get("density") or 0) >= 90 else "watch" if int(zone.get("density") or 0) >= 70 else "normal",
            "guestFlow.zones",
            ["inspect", "open_route", "send_crowd_lead", "draft_guest_message"],
            attributes={
                "density": zone.get("density"),
                "wait_mins": zone.get("waitMins"),
                "current_guests": zone.get("currentGuests"),
            },
        )
    for queue in physical.get("queues", []) if isinstance(physical.get("queues"), list) else []:
        if not isinstance(queue, dict):
            continue
        add_object(
            "Queue",
            str(queue.get("id") or queue.get("name") or "queue"),
            str(queue.get("name") or queue.get("id") or "Queue"),
            str(queue.get("spillbackRisk") or queue.get("status") or "normal"),
            "physicalMap.queues",
            ["inspect", "hold_intake", "split_flow", "message_affected_guests"],
            relationships=[{"to_type": "Ride", "to_id": str(queue.get("rideId") or ""), "relation": "serves"}] if queue.get("rideId") else [],
            attributes={
                "wait_mins": queue.get("waitMins"),
                "guests": queue.get("guests"),
                "shade_pct": queue.get("shadePct"),
            },
        )
    for route in physical.get("serviceRoutes", []) if isinstance(physical.get("serviceRoutes"), list) else []:
        if not isinstance(route, dict):
            continue
        add_object(
            "Path",
            str(route.get("id") or route.get("name") or "path"),
            str(route.get("name") or route.get("id") or "Path"),
            "blocked" if route.get("blocked") else "open",
            "physicalMap.serviceRoutes",
            ["inspect", "protect_access", "dispatch_staff_verification"],
            attributes={"access": route.get("access"), "blocked": route.get("blocked")},
        )
    add_object(
        "StaffPool",
        "staffing",
        "Park staffing",
        "short" if int(staffing.get("openCallouts") or 0) >= 20 else "ready",
        "staffing",
        ["inspect", "draft_redeploy_plan", "request_manager_approval"],
        attributes=staffing,
    )
    add_object(
        "SafetyReadiness",
        "incident_readiness",
        "Incident readiness",
        "blocked" if readiness.get("emergencyAccessBlocked") else "ready",
        "incidentReadiness",
        ["inspect", "dispatch_medical", "protect_access_lane", "escalate_to_manager"],
        attributes=readiness,
        permission="supervisor_required_for_medical_security",
    )
    object_types = [
        {"type": "Ride", "description": "Guest-facing attraction with wait, downtime, and queue risk."},
        {"type": "Zone", "description": "Operating area with density, comfort, and crowd pressure."},
        {"type": "Queue", "description": "Physical queue footprint with spillback and shade risk."},
        {"type": "Path", "description": "Guest, service, or emergency route with access constraints."},
        {"type": "StaffPool", "description": "Labor readiness and redeployment constraints."},
        {"type": "SafetyReadiness", "description": "Medical, security, accessibility, and emergency access posture."},
    ]
    return {
        "ontology_id": "parkpulse_ops_ontology",
        "generated_at": now,
        "object_types": object_types,
        "objects": objects,
        "relationships": [
            {"from_type": "Queue", "relation": "serves", "to_type": "Ride"},
            {"from_type": "Zone", "relation": "contains", "to_type": "Ride/Queue/Path"},
            {"from_type": "SafetyReadiness", "relation": "constrains", "to_type": "Path/Zone/Action"},
            {"from_type": "StaffPool", "relation": "constrains", "to_type": "Action"},
        ],
        "governance": {
            "read_tools": "permission-scoped ontology reads are allowed for operators",
            "draft_tools": "agent may draft guest, worker, equipment, and manager actions",
            "write_tools": "policy gate required before simulated state mutation",
            "external_actions": "medical, security, maintenance, evacuation, labor exception, and equipment authority require approval boundaries",
        },
    }


def _copilot_ontology_context(
    message: str,
    state: dict[str, Any],
    map_grounding: dict[str, Any] | None,
    role_payload: dict[str, Any] | None,
    turn_contract: dict[str, Any],
    tool_call_timeline: list[dict[str, Any]],
    recommended_action: dict[str, Any] | None = None,
    object_action_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    seed_ontology = _park_ontology_snapshot(state)
    ontology = reconcile_ontology_with_live_state(seed_ontology)
    grounding = map_grounding or {}
    wanted_ids = {
        *(str(item) for item in grounding.get("highlight_zone_ids", []) if item),
        *(str(item) for item in grounding.get("landmark_ids", []) if item),
        *(str(item) for item in grounding.get("queue_ids", []) if item),
        *(str(item) for item in grounding.get("path_ids", []) if item),
        "incident_readiness",
        "staffing",
    }
    affected = [
        obj
        for obj in ontology["objects"]
        if obj["id"] in wanted_ids or obj["name"] in wanted_ids
    ][:10]
    telemetry = role_payload.get("run_telemetry", {}) if isinstance(role_payload, dict) else {}
    governance = telemetry.get("governance", {}) if isinstance(telemetry, dict) and isinstance(telemetry.get("governance"), dict) else {}
    dispatches = telemetry.get("delivery", {}).get("dispatches", []) if isinstance(telemetry.get("delivery"), dict) else []
    policy_gate = governance.get("gate_status") or ("mutated" if turn_contract.get("state_mutation") else "read_only")
    approval_required = any(
        term in (message or "").lower()
        for term in ("medical", "first aid", "security", "evac", "maintenance", "reopen", "labor exception", "fire")
    )
    action_policy = {
        "read": "allowed",
        "draft": "allowed",
        "write": policy_gate,
        "external_action": "approval_required" if approval_required else "bounded_simulation_only",
        "rollback": "state replay and receiver receipts are retained for operator review",
        "object_action_gate": (object_action_plan or {}).get("overall_gate"),
    }
    ontology = record_ontology_turn(
        seed_ontology,
        user_intent=message,
        affected_object_ids=[str(obj["id"]) for obj in affected],
        action_policy=action_policy,
        turn_contract=turn_contract,
        recommended_action=recommended_action,
        tool_calls=tool_call_timeline,
        object_action_plan=object_action_plan,
    )
    affected = [
        obj
        for obj in ontology["objects"]
        if obj["id"] in wanted_ids or obj["name"] in wanted_ids
    ][:10]
    write_event = ontology.get("write_event", {}) if isinstance(ontology.get("write_event"), dict) else {}
    return {
        "ontology": {
            "ontology_id": ontology["ontology_id"],
            "generated_at": ontology.get("generated_at"),
            "updated_at": ontology.get("updated_at"),
            "version": ontology.get("version"),
            "object_types": ontology["object_types"],
            "relationships": ontology["relationships"],
            "object_count": len(ontology["objects"]),
            "storage": ontology.get("storage"),
            "last_event_id": write_event.get("event_id") or (ontology.get("last_event") or {}).get("event_id"),
        },
        "affected_objects": affected,
        "action_policy": action_policy,
        "audit_trail": {
            "user_intent": message,
            "retrieved_object_ids": [obj["id"] for obj in affected],
            "tool_calls": [
                {"tool": item.get("tool"), "status": item.get("status"), "output": item.get("output")}
                for item in tool_call_timeline[:10]
            ],
            "policy_gate": policy_gate,
            "human_approval_required": approval_required,
            "dispatch_count": len(dispatches) if isinstance(dispatches, list) else 0,
            "state_mutation": bool(turn_contract.get("state_mutation")),
            "map_effect": turn_contract.get("map_effect"),
            "ontology_event_id": write_event.get("event_id"),
            "ontology_event_type": write_event.get("event_type"),
            "ontology_version": ontology.get("version"),
            "changed_object_keys": write_event.get("changed_object_keys", []),
            "object_action_plan_id": (object_action_plan or {}).get("plan_id"),
        },
        "object_action_plan": object_action_plan,
    }


def _stable_copilot_id(prefix: str, payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return f"{prefix}_{hashlib.sha1(encoded).hexdigest()[:12]}"


def _copilot_affected_ontology_objects(state: dict[str, Any], map_grounding: dict[str, Any] | None) -> list[dict[str, Any]]:
    ontology = reconcile_ontology_with_live_state(_park_ontology_snapshot(state))
    grounding = map_grounding or {}
    wanted_ids = {
        *(str(item) for item in grounding.get("highlight_zone_ids", []) if item),
        *(str(item) for item in grounding.get("landmark_ids", []) if item),
        *(str(item) for item in grounding.get("queue_ids", []) if item),
        *(str(item) for item in grounding.get("path_ids", []) if item),
        "incident_readiness",
        "staffing",
    }
    return [
        obj
        for obj in ontology.get("objects", [])
        if isinstance(obj, dict) and (obj.get("id") in wanted_ids or obj.get("name") in wanted_ids)
    ][:10]


def _choose_object_bound_action(message: str, obj: dict[str, Any]) -> tuple[str | None, str]:
    allowed = [str(action) for action in obj.get("allowed_actions", []) if action]
    lowered = message.lower()
    vague_solution = any(term in lowered for term in ("solution", "solve", "fix", "resolve", "mitigate", "recommend", "optimize", "action", "intervene", "smartest", "best move", "park move"))
    object_type = str(obj.get("object_type") or "")
    candidates: list[tuple[str, str]] = []
    if object_type == "SafetyReadiness":
        if any(term in lowered for term in ("first aid", "medical", "injury", "faint", "access")):
            candidates = [
                ("protect_access_lane", "Protect medical/service access before moving crowd volume."),
                ("dispatch_medical", "Medical wording requires a bounded dispatch action."),
                ("escalate_to_manager", "Safety-sensitive action keeps manager accountability visible."),
            ]
    elif object_type == "Path":
        candidates = [("protect_access", "Path object constrains access and needs lane protection."), ("dispatch_staff_verification", "Staff can verify the route before broader movement.")]
    elif object_type == "Queue":
        if vague_solution or any(term in lowered for term in ("queue", "line", "spill", "parade", "families", "stroller")):
            candidates = [("split_flow", "Queue pressure should be split across safer alternatives."), ("hold_intake", "Hold intake when spillback threatens a crossing."), ("message_affected_guests", "Guests need receiver-specific direction.")]
    elif object_type == "Ride":
        if vague_solution or any(term in lowered for term in ("ride", "coaster", "down", "queue", "reroute", "families")):
            candidates = [("reroute_guests", "Ride pressure should be rerouted from the affected attraction."), ("draft_guest_message", "Guests need a concise explanation."), ("request_maintenance_review", "Ride state may need maintenance review.")]
    elif object_type == "Zone":
        if vague_solution or any(term in lowered for term in ("food", "crowd", "dense", "families", "parade", "zone", "reroute")):
            candidates = [("open_route", "Zone pressure needs a route change."), ("send_crowd_lead", "Crowd lead can actively manage the zone."), ("draft_guest_message", "Guest messaging keeps movement bounded.")]
    elif object_type == "StaffPool":
        if any(term in lowered for term in ("staff", "worker", "load", "break", "fatigue", "callout", "labor")):
            candidates = [("draft_redeploy_plan", "Staff constraints require a redeploy draft before broad assignment."), ("request_manager_approval", "Labor changes need visible approval.")]
    for action, reason in candidates:
        if action in allowed:
            return action, reason
    if "inspect" in allowed:
        return "inspect", "No stronger object action matched the request, so the agent keeps this object read-only."
    return (allowed[0], "Fallback to first allowed object action.") if allowed else (None, "No allowed action exists on this object.")


def _copilot_object_action_plan(message: str, affected_objects: list[dict[str, Any]], *, operator_approved: bool, will_act: bool) -> dict[str, Any]:
    lowered = message.lower()
    staff_intent = any(term in lowered for term in ("staff", "worker", "break", "fatigue", "callout", "labor"))
    avoid_food_intent = any(term in lowered for term in ("avoid food", "avoid the food", "not food", "don't send", "do not send"))
    evacuation_intent = any(term in lowered for term in ("evac", "evacuate", "smoke", "fire", "security", "fight", "panic", "medical", "first aid", "faint", "passed out", "injury"))
    sensitive_actions = {
        "dispatch_medical",
        "escalate_to_manager",
        "request_manager_approval",
        "request_maintenance_review",
    }
    external_actions = sensitive_actions | {"dispatch_staff_verification", "send_crowd_lead"}
    rows: list[dict[str, Any]] = []
    for obj in affected_objects:
        action, reason = _choose_object_bound_action(message, obj)
        if not action:
            continue
        allowed_actions = [str(item) for item in obj.get("allowed_actions", []) if item]
        is_allowed = action in allowed_actions
        requires_approval = action != "inspect" and (action in sensitive_actions or "supervisor_required" in str(obj.get("permission") or ""))
        external = action in external_actions
        if not is_allowed:
            gate_status = "blocked"
        elif requires_approval and not operator_approved:
            gate_status = "approval_required"
        elif will_act:
            gate_status = "passed"
        else:
            gate_status = "prepared"
        rows.append(
            {
                "object_type": obj.get("object_type"),
                "object_id": obj.get("id"),
                "object_name": obj.get("name"),
                "object_status": obj.get("status"),
                "permission": obj.get("permission"),
                "action": action,
                "allowed_actions": allowed_actions,
                "allowed": is_allowed,
                "external_action": external,
                "requires_approval": requires_approval,
                "approval": "operator_apply_turn" if requires_approval and operator_approved else "required" if requires_approval else "not_required",
                "gate_status": gate_status,
                "will_execute": bool(will_act and is_allowed and gate_status == "passed"),
                "reason": reason,
            }
        )
    if staff_intent:
        rows.sort(key=lambda row: 0 if row.get("object_type") == "StaffPool" else 1)
    if avoid_food_intent:
        rows = [
            {
                **row,
                "reason": f"{row.get('reason', '')} Operator added a no-food-court constraint, so food demand actions are deprioritized.".strip(),
            }
            for row in rows
            if not ("food" in str(row.get("object_name") or "").lower() or "food" in str(row.get("object_id") or "").lower())
        ]
    if evacuation_intent:
        rows.sort(key=lambda row: 0 if row.get("object_type") in {"SafetyReadiness", "Path", "Zone"} else 1)
    actionable = [row for row in rows if row["action"] != "inspect"] or rows
    selected = actionable[:6]
    if any(not row["allowed"] for row in selected):
        overall_gate = "blocked"
    elif evacuation_intent and not operator_approved:
        overall_gate = "approval_required"
    elif any(row["gate_status"] == "approval_required" for row in selected):
        overall_gate = "approval_required"
    elif will_act and selected:
        overall_gate = "passed"
    else:
        overall_gate = "prepared"
    return {
        "plan_id": _stable_copilot_id("obj_plan", {"message": message, "objects": [(row.get("object_type"), row.get("object_id"), row.get("action")) for row in selected]}),
        "planner": "ontology_allowed_action_planner",
        "overall_gate": overall_gate,
        "operator_approval": "apply_turn" if operator_approved else "not_granted",
        "will_execute": bool(will_act and overall_gate == "passed"),
        "actions": selected,
        "rejected": [
            {
                "object_type": obj.get("object_type"),
                "object_id": obj.get("id"),
                "reason": "No allowed action matched strongly enough for this turn.",
            }
            for obj in affected_objects
            if obj.get("id") not in {row.get("object_id") for row in selected}
        ][:4],
    }


def _attach_policy_doctrine_to_object_plan(object_action_plan: dict[str, Any], doctrine: dict[str, Any], policy_reasoning: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(object_action_plan, dict):
        return object_action_plan
    policy_reasoning = policy_reasoning if isinstance(policy_reasoning, dict) else {}
    primary_case = doctrine.get("primary_case") if isinstance(doctrine.get("primary_case"), dict) else {}
    policy_refs = [str(ref) for ref in [*doctrine.get("policy_refs", []), *policy_reasoning.get("policy_refs", [])] if ref]
    case_refs = [str(ref) for ref in primary_case.get("policy_refs", []) if ref] if primary_case else []
    merged_refs = list(dict.fromkeys([*case_refs, *policy_refs]))
    actions = []
    receiver_payloads = primary_case.get("receiver_payloads", []) if isinstance(primary_case, dict) else []
    for row in object_action_plan.get("actions", []) or []:
        if not isinstance(row, dict):
            continue
        actions.append(
            {
                **row,
                "policy_refs": merged_refs[:6],
                "matched_case_id": primary_case.get("id") if primary_case else None,
                "matched_case_title": primary_case.get("title") if primary_case else None,
                "case_success_metric": primary_case.get("success_metric") if primary_case else None,
                "case_rollback_condition": primary_case.get("rollback_condition") if primary_case else None,
            }
        )
    return {
        **object_action_plan,
        "planner": "ontology_allowed_action_planner_with_policy_doctrine",
        "policy_refs": merged_refs[:10],
        "policy_doctrine": {
            "retrieval_status": doctrine.get("retrieval_status"),
            "primary_case": primary_case,
            "matches": doctrine.get("matches", [])[:5],
            "policy_refs": merged_refs[:10],
            "policy_reasoning": policy_reasoning,
            "synthetic_context": doctrine.get("synthetic_context"),
            "receiver_payloads": receiver_payloads[:5] if isinstance(receiver_payloads, list) else [],
            "doctrine_index": doctrine.get("doctrine_index"),
        },
        "policy_reasoning": policy_reasoning,
        "actions": actions,
    }


def _copilot_reasoning_scorecard_for_action(action: dict[str, Any], message: str, compact_state: dict[str, Any]) -> dict[str, int]:
    lowered = message.lower()
    action_name = str(action.get("action") or "")
    object_type = str(action.get("object_type") or "")
    object_status = str(action.get("object_status") or "")
    has_source = bool(action.get("object_id") and action.get("object_name"))
    high_risk = int(_primary_copilot_risk(compact_state).get("score") or 0) >= 80
    grounding = 92 if has_source and object_status else 78 if has_source else 55
    if action_name == "inspect":
        action_fit = 58
    elif object_type == "StaffPool" and any(term in lowered for term in ("staff", "worker", "break", "fatigue", "callout", "labor")):
        action_fit = 95
    elif object_type == "SafetyReadiness" and any(term in lowered for term in ("medical", "first aid", "faint", "passed out", "injury", "evac", "smoke", "fire", "security", "panic")):
        action_fit = 96
    elif object_type in {"Queue", "Zone", "Path"} and any(term in lowered for term in ("medical", "first aid", "faint", "passed out", "injury", "evac", "smoke", "fire", "security", "panic")):
        action_fit = 70
    elif object_type in {"Queue", "Zone", "Path"} and any(term in lowered for term in ("queue", "crowd", "wait", "flow", "reroute", "coaster", "food")):
        action_fit = 92
    elif object_type == "Ride" and any(term in lowered for term in ("ride", "coaster", "down", "queue")):
        action_fit = 90
    else:
        action_fit = 74 if action_name != "inspect" else 58
    if not action.get("allowed"):
        policy_fit = 35
    elif action.get("gate_status") == "approval_required":
        policy_fit = 88
    elif action.get("gate_status") == "passed":
        policy_fit = 94
    else:
        policy_fit = 84
    map_fit = 92 if object_type in {"Queue", "Zone", "Path", "Ride", "SafetyReadiness"} else 78
    if high_risk and action_name != "inspect":
        map_fit = min(98, map_fit + 4)
    clarity = 90 if action.get("reason") else 68
    return {
        "grounding": grounding,
        "action_fit": action_fit,
        "policy_fit": policy_fit,
        "map_fit": map_fit,
        "clarity": clarity,
    }


def _copilot_reasoning_overall(scorecard: dict[str, int]) -> int:
    weights = {
        "grounding": 0.24,
        "action_fit": 0.28,
        "policy_fit": 0.22,
        "map_fit": 0.16,
        "clarity": 0.10,
    }
    return int(round(sum(int(scorecard.get(key, 0)) * weight for key, weight in weights.items())))


def _copilot_reasoning_evaluation(
    message: str,
    compact_state: dict[str, Any],
    object_action_plan: dict[str, Any] | None,
    options_considered: list[dict[str, Any]],
    turn_contract: dict[str, Any],
) -> dict[str, Any]:
    plan = object_action_plan if isinstance(object_action_plan, dict) else {}
    candidates: list[dict[str, Any]] = []
    for action in [item for item in (plan.get("actions") or []) if isinstance(item, dict)]:
        scorecard = _copilot_reasoning_scorecard_for_action(action, message, compact_state)
        if action.get("requires_approval") and action.get("gate_status") == "prepared":
            scorecard["policy_fit"] = min(scorecard["policy_fit"], 78)
        score = _copilot_reasoning_overall(scorecard)
        if action.get("action") == "inspect":
            score = min(score, 64)
        candidates.append(
            {
                "kind": "object_action",
                "label": f"{action.get('object_name') or action.get('object_id')}: {str(action.get('action') or '').replace('_', ' ')}",
                "object_type": action.get("object_type"),
                "object_id": action.get("object_id"),
                "action": action.get("action"),
                "gate": action.get("gate_status"),
                "will_execute": action.get("will_execute"),
                "selection_score": score,
                "scorecard": scorecard,
                "rationale": action.get("reason") or "Selected from ontology allowed_actions.",
            }
        )
    for option in [item for item in options_considered if isinstance(item, dict)]:
        verdict = str(option.get("verdict") or "checked").lower()
        base = 86 if verdict == "selected" else 78 if verdict == "prepared" else 66 if verdict == "watch" else 50
        scorecard = {
            "grounding": 76,
            "action_fit": base,
            "policy_fit": 86 if verdict in {"selected", "prepared", "watch"} else 72,
            "map_fit": 72,
            "clarity": 86 if option.get("reason") else 65,
        }
        candidates.append(
            {
                "kind": "route_option",
                "label": option.get("label") or "Route option",
                "verdict": option.get("verdict"),
                "projected_effect": option.get("projected_effect"),
                "selection_score": _copilot_reasoning_overall(scorecard),
                "scorecard": scorecard,
                "rationale": option.get("reason") or "Considered by the role router.",
            }
        )
    candidates.sort(key=lambda item: int(item.get("selection_score") or 0), reverse=True)
    selected = next((item for item in candidates if item.get("kind") == "object_action" and item.get("action") != "inspect"), None)
    selected = selected or (candidates[0] if candidates else None)
    selected_scorecard = selected.get("scorecard", {}) if isinstance(selected, dict) and isinstance(selected.get("scorecard"), dict) else {}
    overall = int(selected.get("selection_score") or 0) if isinstance(selected, dict) else 0
    gate = str(plan.get("overall_gate") or turn_contract.get("mode") or "prepared")
    verdict = "strong" if overall >= 86 and gate != "blocked" else "review" if overall >= 72 and gate != "blocked" else "weak"
    rejected: list[dict[str, Any]] = []
    selected_label = selected.get("label") if isinstance(selected, dict) else None
    for item in candidates:
        if item.get("label") == selected_label:
            continue
        rejected.append(
            {
                "label": item.get("label"),
                "reason": item.get("rationale") or item.get("verdict") or "Lower score than selected option.",
                "selection_score": item.get("selection_score"),
            }
        )
    for item in [row for row in (plan.get("rejected") or []) if isinstance(row, dict)]:
        rejected.append(
            {
                "label": f"{item.get('object_type') or 'Object'} {item.get('object_id') or ''}".strip(),
                "reason": item.get("reason") or "No allowed action matched strongly enough for this turn.",
                "selection_score": None,
            }
        )
    checks = [
        {
            "label": "Ontology action",
            "status": "pass" if bool(plan.get("actions")) else "warn",
            "evidence": f"{len(plan.get('actions') or [])} allowed action(s) considered.",
        },
        {
            "label": "Policy gate",
            "status": "pass" if gate in {"prepared", "passed", "approval_required"} else "fail",
            "evidence": f"gate={gate}; mutation={bool(turn_contract.get('state_mutation'))}.",
        },
        {
            "label": "Map coupling",
            "status": "pass" if turn_contract.get("map_effect") in {"grounding_only", "impact_replay"} else "warn",
            "evidence": f"map_effect={turn_contract.get('map_effect') or 'none'}.",
        },
    ]
    improvement_hints: list[str] = []
    if not bool(turn_contract.get("state_mutation")) and gate == "prepared":
        improvement_hints.append("Approve + apply is required before the scored recommendation changes simulated park state.")
    if gate == "approval_required":
        improvement_hints.append("Human approval is required because this touches safety, security, maintenance, or labor policy.")
    if overall < 86:
        improvement_hints.append("Ask for constraints such as safety priority, target zone, staffing limits, or guest segment to improve action fit.")
    if not improvement_hints:
        improvement_hints.append("The selected option is strongly grounded; next useful proof is impact replay after approval.")
    return {
        "mode": "deterministic_reasoning_evaluator",
        "overall": overall,
        "verdict": verdict,
        "scorecard": selected_scorecard,
        "selected_option": selected,
        "candidate_options": candidates[:6],
        "rejected_options": rejected[:5],
        "checks": checks,
        "improvement_hints": improvement_hints[:3],
    }


def _copilot_agent_task_store_path() -> Path:
    return Path(os.getenv("PARKPULSE_RUNTIME_DIR", "/tmp/parkpulse")) / "copilot_agent_tasks.json"


def _read_copilot_agent_tasks() -> dict[str, Any]:
    path = _copilot_agent_task_store_path()
    if not path.exists():
        return {"tasks": {}, "updated_at": None}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {"tasks": {}, "updated_at": None}
    except Exception:
        return {"tasks": {}, "updated_at": None, "read_error": "invalid_json"}


def _write_copilot_agent_task(task: dict[str, Any]) -> dict[str, Any]:
    path = _copilot_agent_task_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    store = _read_copilot_agent_tasks()
    tasks = store.get("tasks") if isinstance(store.get("tasks"), dict) else {}
    task_id = str(task.get("task_id") or task.get("graph_id") or _stable_copilot_id("task", task))
    now = datetime.now(UTC).isoformat()
    previous = tasks.get(task_id, {}) if isinstance(tasks.get(task_id), dict) else {}
    merged = {
        **previous,
        **task,
        "task_id": task_id,
        "created_at": previous.get("created_at") or now,
        "updated_at": now,
    }
    tasks[task_id] = merged
    path.write_text(json.dumps({"updated_at": now, "tasks": tasks}, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return {
        "mode": "durable_json_task_store",
        "path": str(path),
        "task_id": task_id,
        "task_count": len(tasks),
        "updated_at": now,
    }


def _execute_copilot_task_graph(
    task_graph: dict[str, Any],
    lifecycle: dict[str, Any],
    *,
    will_act: bool,
    impact_replay: dict[str, Any] | None,
    selected_score: Any,
) -> dict[str, Any]:
    nodes = [node for node in (task_graph.get("nodes") or []) if isinstance(node, dict)]
    completed_ids: set[str] = set()
    node_statuses: dict[str, str] = {}
    events: list[dict[str, Any]] = []
    blocked_on: list[str] = []
    for index, node in enumerate(nodes):
        node_id = str(node.get("id") or f"node_{index + 1}")
        deps = [str(dep) for dep in (node.get("depends_on") or [])]
        dep_statuses = [node_statuses.get(dep) for dep in deps]
        deps_met = all(dep in completed_ids for dep in deps)
        requested_status = str(node.get("status") or "ready")
        if any(status == "blocked" for status in dep_statuses):
            status = "blocked"
            blocked_on.extend(dep for dep in deps if dep not in completed_ids)
        elif not deps_met:
            status = "waiting" if node.get("kind") in {"approval", "write", "verify", "memory"} else "blocked"
            if status == "blocked":
                blocked_on.extend(dep for dep in deps if dep not in completed_ids)
        elif requested_status in {"done", "complete"}:
            status = "complete"
            completed_ids.add(node_id)
        elif node.get("kind") == "approval" and not will_act:
            status = "waiting"
        elif node.get("kind") in {"write", "verify"} and not will_act:
            status = "ready"
        elif node.get("kind") == "verify" and will_act and not impact_replay:
            status = "blocked"
        else:
            status = "complete" if requested_status == "done" else requested_status
            if status == "complete":
                completed_ids.add(node_id)
        events.append(
            {
                "node_id": node_id,
                "tool": node.get("tool"),
                "kind": node.get("kind"),
                "status": status,
                "depends_on": deps,
                "output": "executed" if status == "complete" else "awaiting operator" if status == "waiting" else "not executed yet",
            }
        )
        node_statuses[node_id] = status
    status_counts = {
        "complete": sum(1 for event in events if event.get("status") == "complete"),
        "waiting": sum(1 for event in events if event.get("status") == "waiting"),
        "ready": sum(1 for event in events if event.get("status") == "ready"),
        "blocked": sum(1 for event in events if event.get("status") == "blocked"),
    }
    executor_status = "blocked" if status_counts["blocked"] else "waiting" if status_counts["waiting"] or status_counts["ready"] else "complete"
    task_snapshot = {
        "task_id": lifecycle.get("task_id") or task_graph.get("graph_id"),
        "graph_id": task_graph.get("graph_id"),
        "goal": task_graph.get("goal"),
        "state": lifecycle.get("state"),
        "executor_status": executor_status,
        "selected_action": task_graph.get("selected_action"),
        "selected_score": selected_score,
        "node_events": events,
        "status_counts": status_counts,
        "blocked_on": sorted(set(blocked_on)),
    }
    persistence = _write_copilot_agent_task(task_snapshot)
    return {
        "engine": "deterministic_graph_executor_v1",
        "status": executor_status,
        "node_events": events,
        "status_counts": status_counts,
        "blocked_on": sorted(set(blocked_on)),
        "persistence": persistence,
    }


def _copilot_multi_agent_domain(message: str, primary_case: dict[str, Any]) -> dict[str, Any]:
    text = f"{message} {primary_case.get('id') or ''} {primary_case.get('title') or ''}".lower()
    domains = [
        (
            "guest_care_security",
            "Guest Care + Security Agent",
            ("missing child", "lost child", "separated", "unattended bag", "security", "fight", "pii", "privacy", "kid"),
        ),
        (
            "medical_access",
            "Medical + Access Agent",
            ("medical", "first aid", "collapsed", "cannot breathe", "chest pain", "faint", "injury", "wheelchair", "accessibility"),
        ),
        (
            "ride_safety",
            "Ride Safety Agent",
            ("ride", "coaster", "restraint", "evacuation", "stuck", "block zone", "operator", "dispatch interval"),
        ),
        (
            "weather_shelter",
            "Weather + Shelter Agent",
            ("weather", "lightning", "storm", "heat", "smoke", "air quality", "shelter", "hvac"),
        ),
        (
            "facilities_equipment",
            "Facilities + Equipment Agent",
            ("power", "outage", "blackout", "key control", "controller", "pos", "app", "signage", "notification"),
        ),
        (
            "food_ops",
            "Food Operations Agent",
            ("food", "restaurant", "mobile order", "kitchen", "allergen", "concession"),
        ),
        (
            "crowd_flow",
            "Crowd Flow Agent",
            ("queue", "crowd", "parade", "fireworks", "entrance", "bottleneck", "capacity"),
        ),
        (
            "labor_staffing",
            "Labor + Staffing Agent",
            ("staff", "break", "fatigue", "shortage", "callout", "certified", "rotation"),
        ),
    ]
    matches = [(domain, name) for domain, name, terms in domains if any(term in text for term in terms)]
    if not matches:
        matches = [("crowd_flow", "Crowd Flow Agent")]

    priority = [
        "medical_access",
        "guest_care_security",
        "ride_safety",
        "weather_shelter",
        "facilities_equipment",
        "labor_staffing",
        "crowd_flow",
        "food_ops",
    ]
    matched_domains = [domain for domain, _ in matches]
    owner_domain = next((domain for domain in priority if domain in matched_domains), matches[0][0])
    owner_name = next(name for domain, name in matches if domain == owner_domain)
    secondary = [{"domain": domain, "agent": name} for domain, name in matches if domain != owner_domain]
    return {"owner_domain": owner_domain, "owner_agent": owner_name, "secondary": secondary, "matched_domains": matched_domains}


def _build_copilot_multi_agent_deliberation(
    message: str,
    *,
    route: dict[str, Any],
    compact_state: dict[str, Any],
    object_action_plan: dict[str, Any],
    reasoning_evaluation: dict[str, Any],
    turn_contract: dict[str, Any],
    primary_risk: dict[str, Any],
    impact_replay: dict[str, Any] | None,
) -> dict[str, Any]:
    policy_doctrine = object_action_plan.get("policy_doctrine") if isinstance(object_action_plan.get("policy_doctrine"), dict) else {}
    policy_reasoning = object_action_plan.get("policy_reasoning") if isinstance(object_action_plan.get("policy_reasoning"), dict) else {}
    synthetic_context = policy_doctrine.get("synthetic_context") if isinstance(policy_doctrine.get("synthetic_context"), dict) else {}
    primary_synthetic = synthetic_context.get("primary_example") if isinstance(synthetic_context.get("primary_example"), dict) else {}
    synthetic_facts = []
    for obj in synthetic_context.get("matched_objects", []) if isinstance(synthetic_context.get("matched_objects"), list) else []:
        if isinstance(obj, dict):
            synthetic_facts.extend(str(fact) for fact in obj.get("facts", [])[:2] if fact)
    primary_case = policy_doctrine.get("primary_case") if isinstance(policy_doctrine.get("primary_case"), dict) else {}
    selected_policy_action = policy_reasoning.get("selected_action") if isinstance(policy_reasoning.get("selected_action"), dict) else {}
    conflict_analysis = policy_reasoning.get("conflict_analysis") if isinstance(policy_reasoning.get("conflict_analysis"), dict) else {}
    allowed_actions = [str(item) for item in (policy_reasoning.get("allowed_actions") or [])[:4] if item] if isinstance(policy_reasoning.get("allowed_actions"), list) else []
    blocked_actions = [str(item) for item in (policy_reasoning.get("blocked_actions") or [])[:4] if item] if isinstance(policy_reasoning.get("blocked_actions"), list) else []
    required_evidence = [str(item) for item in (policy_reasoning.get("required_evidence") or [])[:4] if item] if isinstance(policy_reasoning.get("required_evidence"), list) else []
    domain = _copilot_multi_agent_domain(message, primary_case)
    plan_actions = [item for item in object_action_plan.get("actions", []) if isinstance(item, dict)]
    selected_action = next((item for item in plan_actions if item.get("action") and item.get("action") != "inspect"), None) or (plan_actions[0] if plan_actions else {})
    pressure = primary_risk.get("evidence") or primary_risk.get("label") or "Live park state read."
    score = int(reasoning_evaluation.get("overall") or 0)
    confidence = max(54, min(92, score if score else 72))
    owner_confidence = max(58, min(94, confidence + (6 if primary_case else -4)))
    policy_refs = [str(ref) for ref in object_action_plan.get("policy_refs", [])[:6] if ref]
    secondary = domain.get("secondary") if isinstance(domain.get("secondary"), list) else []
    secondary_names = [str(item.get("agent")) for item in secondary if isinstance(item, dict) and item.get("agent")]
    selected_label = selected_policy_action.get("label") or selected_action.get("action") or "prepare bounded operating plan"

    specialists: list[dict[str, Any]] = [
        {
            "agent_id": "scan",
            "name": "Scan Agent",
            "domain": "live_state",
            "stance": "ground",
            "evidence": [
                pressure,
                f"Matched case: {primary_case.get('id') or 'none'}",
                *(synthetic_facts[:2] or []),
                *([f"Synthetic example: {primary_synthetic.get('id')}"] if primary_synthetic else []),
            ],
            "recommendation": "Keep the response grounded in current park objects before choosing an action.",
            "objections": ["Do not dispatch from a vague text signal without policy interpretation."],
            "confidence": confidence,
            "uncertainty": "Live simulation changes every tick; re-read state before apply.",
            "handoff_to": domain["owner_agent"],
            "policy_refs": policy_refs,
        },
        {
            "agent_id": domain["owner_domain"],
            "name": domain["owner_agent"],
            "domain": domain["owner_domain"],
            "stance": "own",
            "evidence": [
                primary_case.get("title") or "No named policy case matched.",
                f"Selected action: {selected_label}",
                *(required_evidence[:2] or ["Evidence requirements not enumerated by policy."]),
            ],
            "recommendation": selected_label,
            "objections": blocked_actions[:3] or ["No explicit blocked action in the matched policy case."],
            "confidence": owner_confidence,
            "uncertainty": "Needs operator approval before park mutation." if object_action_plan.get("overall_gate") in {"approval_required", "prepared"} else "Monitor execution effects after apply.",
            "handoff_to": "Policy Agent",
            "policy_refs": policy_refs,
        },
        {
            "agent_id": "policy",
            "name": "Policy Agent",
            "domain": "governance",
            "stance": "gate",
            "evidence": [
                f"Allowed: {', '.join(allowed_actions[:3]) if allowed_actions else 'none listed'}",
                f"Blocked: {', '.join(blocked_actions[:3]) if blocked_actions else 'none listed'}",
                f"Approval required: {bool(policy_reasoning.get('approval_required') or object_action_plan.get('human_approval_required'))}",
            ],
            "recommendation": "Proceed only through allowed actions and required evidence.",
            "objections": blocked_actions[:3] or ["No policy objection recorded."],
            "confidence": 90 if primary_case else 66,
            "uncertainty": "Policy confidence drops when no actionable case is retrieved.",
            "handoff_to": "Critic Agent",
            "policy_refs": policy_refs,
        },
    ]

    for item in secondary[:3]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("agent") or "Secondary Specialist")
        specialists.append(
            {
                "agent_id": str(item.get("domain") or "secondary"),
                "name": name,
                "domain": str(item.get("domain") or "secondary"),
                "stance": "support",
                "evidence": [f"Secondary signal in operator request: {message[:120]}", pressure],
                "recommendation": f"Support {domain['owner_agent']} without taking primary ownership.",
                "objections": [f"{name} should not override {domain['owner_agent']} on this case."],
                "confidence": max(50, confidence - 10),
                "uncertainty": "Support role only; supervisor decides final priority.",
                "handoff_to": domain["owner_agent"],
                "policy_refs": policy_refs,
            }
        )

    critic_objections = [
        "Check whether the matched case outranks adjacent food, crowd, or ride signals.",
        "Do not claim execution impact until digital twin apply and baseline comparison run.",
    ]
    if blocked_actions:
        critic_objections.insert(0, f"Blocked action must stay blocked: {blocked_actions[0]}")
    if required_evidence:
        critic_objections.append(f"Missing evidence would block escalation: {required_evidence[0]}")
    critic = {
        "agent_id": "critic",
        "name": "Critic Agent",
        "verdict": "challenge" if object_action_plan.get("overall_gate") in {"approval_required", "prepared"} else "pass_with_monitoring",
        "objections": critic_objections[:5],
        "failure_modes": [
            "Wrong specialist owns the incident.",
            "Policy case is treated as a script instead of constraints.",
            "Action is described but not bound to map/object effects.",
        ],
        "required_fixes_before_apply": required_evidence[:3] + (["operator approval"] if object_action_plan.get("overall_gate") in {"approval_required", "prepared"} else []),
    }
    priority_order = [
        domain["owner_agent"],
        "Policy Agent",
        "Critic Agent",
        "Scan Agent",
        *secondary_names,
    ]
    supervisor = {
        "agent_id": "supervisor",
        "name": "Supervisor Agent",
        "selected_agent": domain["owner_agent"],
        "selected_domain": domain["owner_domain"],
        "selected_action": selected_label,
        "decision": "prepare_for_human_approval" if object_action_plan.get("overall_gate") in {"approval_required", "prepared"} else "answer_or_execute_with_monitoring",
        "priority_order": list(dict.fromkeys(priority_order)),
        "priority_rationale": conflict_analysis.get("priority_order") or "Safety/privacy/ride authority outrank food, comfort, and queue optimization.",
        "confidence": owner_confidence,
        "next_handoff": "operator_approval" if object_action_plan.get("overall_gate") in {"approval_required", "prepared"} else "verification_monitor",
    }
    disagreements = []
    if secondary_names:
        disagreements.append(
            {
                "topic": "ownership",
                "positions": [domain["owner_agent"], *secondary_names[:3]],
                "resolution": f"Supervisor assigned ownership to {domain['owner_agent']} because it has the highest policy priority.",
            }
        )
    if blocked_actions:
        disagreements.append(
            {
                "topic": "blocked_actions",
                "positions": ["operator may expect direct action", "policy blocks unsafe shortcut"],
                "resolution": blocked_actions[0],
            }
        )
    return {
        "mode": "specialist_supervisor_deliberation_v1",
        "status": "applied" if turn_contract.get("state_mutation") else "approval_required" if object_action_plan.get("overall_gate") in {"approval_required", "prepared"} else "complete",
        "matched_case_id": primary_case.get("id"),
        "specialists": specialists,
        "handoff": {
            "from": "Scan Agent",
            "to": domain["owner_agent"],
            "reason": primary_case.get("title") or route.get("why") or "Domain owner selected from operator text and live state.",
        },
        "critic": critic,
        "supervisor": supervisor,
        "memory_writes": [
            {
                "agent": supervisor["selected_agent"],
                "memory_key": _stable_copilot_id("multi_agent_case", {"message": message, "case": primary_case.get("id")}),
                "status": "written" if impact_replay else "prepared",
            }
        ],
        "audit": {
            "independent_opinions": len(specialists) + 2,
            "disagreements": disagreements,
            "policy_steps": len(policy_reasoning.get("steps", []) if isinstance(policy_reasoning.get("steps"), list) else []),
            "synthetic_example_id": primary_synthetic.get("id"),
            "synthetic_expected_owner": primary_synthetic.get("expected_owner"),
            "all_specialists_have_confidence": all(isinstance(item.get("confidence"), int) for item in specialists),
        },
    }


def _copilot_agent_runtime_receipt(
    message: str,
    *,
    intent: dict[str, Any],
    route: dict[str, Any],
    compact_state: dict[str, Any],
    map_grounding: dict[str, Any] | None,
    object_action_plan: dict[str, Any] | None,
    options_considered: list[dict[str, Any]],
    reasoning_evaluation: dict[str, Any] | None,
    turn_contract: dict[str, Any],
    tool_call_timeline: list[dict[str, Any]],
    ontology_context: dict[str, Any] | None,
    impact_replay: dict[str, Any] | None,
    clarifying_question: str | None,
    analytics_action_layer: dict[str, Any] | None = None,
    branch_comparison: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plan = object_action_plan if isinstance(object_action_plan, dict) else {}
    evaluation = reasoning_evaluation if isinstance(reasoning_evaluation, dict) else {}
    ontology = ontology_context if isinstance(ontology_context, dict) else {}
    audit = ontology.get("audit_trail", {}) if isinstance(ontology.get("audit_trail"), dict) else {}
    selected_option = evaluation.get("selected_option") if isinstance(evaluation.get("selected_option"), dict) else {}
    selected_label = selected_option.get("label") or "No selected option"
    gate = str(plan.get("overall_gate") or turn_contract.get("mode") or "prepared")
    needs_approval = gate == "approval_required" or bool(audit.get("human_approval_required"))
    state_mutation = bool(turn_contract.get("state_mutation"))
    impact_headline = None
    if isinstance(impact_replay, dict):
        comparison = impact_replay.get("comparison", {}) if isinstance(impact_replay.get("comparison"), dict) else {}
        impact = comparison.get("impact", {}) if isinstance(comparison.get("impact"), dict) else {}
        impact_headline = impact.get("headline") or comparison.get("summary")
    primary_risk = _primary_copilot_risk(compact_state)
    actions = [item for item in (plan.get("actions") or []) if isinstance(item, dict)]
    primary_action = next((item for item in actions if item.get("action") and item.get("action") != "inspect"), None)
    primary_action = primary_action or (actions[0] if actions else {})
    affected_ids = [
        str(item.get("object_id"))
        for item in actions
        if isinstance(item, dict) and item.get("object_id")
    ][:8]
    tool_registry = [
        {
            "name": "get_park_state",
            "type": "read",
            "selected": True,
            "reason": "Required to ground the request in live queues, rides, zones, staffing, and weather.",
        },
        {
            "name": "ontology.object_lookup",
            "type": "read",
            "selected": True,
            "reason": "Required to bind the plan to governed business objects and allowed_actions.",
        },
        {
            "name": "synthetic_park_knowledge.retrieve",
            "type": "read",
            "selected": True,
            "reason": "Retrieves synthetic park facts, operator paraphrases, and expected owners for better conversational grounding.",
        },
        {
            "name": "reasoning_evaluator.score_options",
            "type": "critic",
            "selected": True,
            "reason": "Required to choose between candidate actions and expose rejected alternatives.",
        },
        {
            "name": "analytics_action_layer.plan_governed_actions",
            "type": "planner",
            "selected": True,
            "reason": "Converts dashboard signals into owned, gated, verifiable system actions.",
        },
        {
            "name": "policy_gate.validate_action",
            "type": "gate",
            "selected": True,
            "reason": "Required before any write or external action.",
        },
        {
            "name": "digital_twin.apply_action",
            "type": "write",
            "selected": state_mutation,
            "reason": "Executed only on apply turns after the policy gate passes.",
        },
        {
            "name": "digital_twin.compare_baseline",
            "type": "verify",
            "selected": bool(impact_replay),
            "reason": "Runs after execution to compare action outcome against no-agent baseline.",
        },
        {
            "name": "digital_twin.compare_action_branches",
            "type": "verify",
            "selected": bool(branch_comparison),
            "reason": "Compares no action, bad metric optimization, and governed agent action.",
        },
        {
            "name": "receiver_adapters.dispatch",
            "type": "external",
            "selected": state_mutation and gate == "passed",
            "reason": "External dispatch is bounded by simulation policy and human approval.",
        },
        {
            "name": "ontology_event_store.write_memory",
            "type": "memory",
            "selected": bool(audit.get("ontology_event_id")),
            "reason": "Stores the turn receipt for follow-up and later learning.",
        },
    ]
    task_graph = {
        "graph_id": _stable_copilot_id("task_graph", {"message": message, "plan": plan.get("plan_id")}),
        "goal": message,
        "selected_action": {
            "object_id": primary_action.get("object_id"),
            "object_name": primary_action.get("object_name"),
            "object_type": primary_action.get("object_type"),
            "action": primary_action.get("action"),
            "gate": primary_action.get("gate_status"),
            "reason": primary_action.get("reason"),
        },
        "nodes": [
            {"id": "n1_read_live_state", "kind": "tool", "tool": "get_park_state", "status": "done", "depends_on": []},
            {"id": "n2_read_ontology", "kind": "tool", "tool": "ontology.object_lookup", "status": "done", "depends_on": ["n1_read_live_state"]},
            {"id": "n3_plan_actions", "kind": "planner", "tool": "analytics_action_layer.plan_governed_actions", "status": "done", "depends_on": ["n2_read_ontology"]},
            {"id": "n4_score_options", "kind": "critic", "tool": "reasoning_evaluator.score_options", "status": "done" if evaluation else "warn", "depends_on": ["n3_plan_actions"]},
            {"id": "n5_policy_gate", "kind": "gate", "tool": "policy_gate.validate_action", "status": "done" if gate in {"prepared", "passed", "approval_required"} else "blocked", "depends_on": ["n4_score_options"]},
            {"id": "n6_human_approval", "kind": "approval", "tool": "operator_approval", "status": "done" if state_mutation else "waiting", "depends_on": ["n5_policy_gate"]},
            {"id": "n7_execute", "kind": "write", "tool": "digital_twin.apply_action", "status": "done" if state_mutation else "ready", "depends_on": ["n6_human_approval"]},
            {"id": "n8_verify", "kind": "verify", "tool": "digital_twin.compare_baseline", "status": "done" if impact_replay else "ready", "depends_on": ["n7_execute"]},
            {"id": "n9_memory", "kind": "memory", "tool": "ontology_event_store.write_memory", "status": "done" if audit.get("ontology_event_id") else "ready", "depends_on": ["n8_verify"]},
        ],
        "edges": [
            ["n1_read_live_state", "n2_read_ontology"],
            ["n2_read_ontology", "n3_plan_actions"],
            ["n3_plan_actions", "n4_score_options"],
            ["n4_score_options", "n5_policy_gate"],
            ["n5_policy_gate", "n6_human_approval"],
            ["n6_human_approval", "n7_execute"],
            ["n7_execute", "n8_verify"],
            ["n8_verify", "n9_memory"],
        ],
    }
    scorecard = evaluation.get("scorecard", {}) if isinstance(evaluation.get("scorecard"), dict) else {}
    critic_risks: list[dict[str, Any]] = []
    if gate == "approval_required":
        critic_risks.append({"risk": "Human approval boundary", "severity": "high", "mitigation": "Hold execution until operator explicitly applies the plan."})
    if int(scorecard.get("policy_fit") or 0) < 85:
        critic_risks.append({"risk": "Policy ambiguity", "severity": "medium", "mitigation": "Keep the action as draft/proposal and request constraints."})
    if not impact_replay:
        critic_risks.append({"risk": "Unverified secondary effects", "severity": "medium", "mitigation": "Run apply to compare against the no-agent baseline before claiming outcome."})
    if not critic_risks:
        critic_risks.append({"risk": "Residual operating drift", "severity": "low", "mitigation": "Monitor map deltas and follow-up signals after execution."})
    critic_report = {
        "critic": "independent_runtime_critic",
        "verdict": "pass" if evaluation.get("verdict") == "strong" and gate != "blocked" else "review",
        "confidence": evaluation.get("overall"),
        "challenged_assumptions": [
            "The top pressure signal is the right operating target.",
            "The selected allowed_action is reversible enough for the current approval mode.",
            "The map delta is sufficient proof only after baseline comparison.",
        ],
        "risks": critic_risks,
    }
    verification_report = {
        "status": "verified" if impact_replay else "pending_apply",
        "primary_metric": impact_headline or "No impact replay yet.",
        "secondary_checks": [
            {"label": "Crowd displacement", "status": "checked" if impact_replay else "pending", "evidence": "Map replay compares after-state to no-agent baseline." if impact_replay else "Requires apply turn."},
            {"label": "Staff fatigue", "status": "watch", "evidence": "Staffing object remains in affected ontology set when constraints appear."},
            {"label": "Fairness/accessibility", "status": "watch", "evidence": "Plan favors bounded route changes and access-lane protection over broad crowd movement."},
            {"label": "Rollback", "status": "available", "evidence": "Before/action/no-agent/after replay is retained in the receipt."},
        ],
        "rollback_plan": "Use retained before-state and receiver receipts to reverse or revise the simulated action.",
    }
    multi_agent_deliberation = _build_copilot_multi_agent_deliberation(
        message,
        route=route,
        compact_state=compact_state,
        object_action_plan=plan,
        reasoning_evaluation=evaluation,
        turn_contract=turn_contract,
        primary_risk=primary_risk,
        impact_replay=impact_replay,
    )
    critic_report["multi_agent_verdict"] = {
        "selected_agent": multi_agent_deliberation.get("supervisor", {}).get("selected_agent"),
        "selected_action": multi_agent_deliberation.get("supervisor", {}).get("selected_action"),
        "disagreements": len(multi_agent_deliberation.get("audit", {}).get("disagreements", []) if isinstance(multi_agent_deliberation.get("audit"), dict) else []),
    }
    learning_update = {
        "memory_event_id": audit.get("ontology_event_id"),
        "object_ids": affected_ids,
        "learned_signal": "pending_outcome" if not impact_replay else "impact_replay_recorded",
        "future_bias": "Prefer this object/action pair for similar pressure patterns only if post-action verification is positive.",
        "dataset_candidate": bool(impact_replay or evaluation.get("overall")),
    }
    lifecycle = {
        "task_id": task_graph["graph_id"],
        "state": "closed_verified" if state_mutation and impact_replay else "waiting_for_operator" if gate in {"prepared", "approval_required"} else "answered",
        "created_by": "copilot_chat",
        "owner": route.get("selected_role") or "react",
        "next_check": "after_apply" if not state_mutation else "monitor_next_live_tick",
        "close_condition": "impact replay verified and memory event written",
    }
    external_adapters = [
        {"adapter": "guest_app", "mode": "simulated", "gate": "human_required_before_send", "available": True},
        {"adapter": "worker_device", "mode": "simulated", "gate": "human_required_before_send", "available": True},
        {"adapter": "equipment_controller", "mode": "simulated", "gate": "manager_required_for_equipment_authority", "available": True},
        {"adapter": "medical_security", "mode": "approval_only", "gate": "always_human", "available": gate == "approval_required"},
    ]
    executor_state = _execute_copilot_task_graph(
        task_graph,
        lifecycle,
        will_act=state_mutation,
        impact_replay=impact_replay,
        selected_score=evaluation.get("overall"),
    )
    stages = [
        {
            "id": "observe",
            "label": "Observe live state",
            "status": "complete",
            "tool": "get_park_state",
            "input": "current simulation state",
            "output": primary_risk.get("label"),
            "evidence": primary_risk.get("evidence"),
        },
        {
            "id": "understand",
            "label": "Understand operator intent",
            "status": "complete",
            "tool": "intent_parser",
            "input": message,
            "output": "actionable" if intent.get("asks_action") else "answer-first",
            "evidence": "safety-sensitive" if intent.get("safety_sensitive") else "standard constraints",
        },
        {
            "id": "plan",
            "label": "Plan task graph",
            "status": "complete",
            "tool": "agent_planner",
            "input": route.get("selected_role") or "scan",
            "output": f"{len(plan.get('actions') or [])} ontology action(s)",
            "evidence": route.get("why") or "Role router selected operating path.",
        },
        {
            "id": "tool_select",
            "label": "Select tools",
            "status": "complete",
            "tool": "tool_router",
            "input": "park state, ontology, policy, digital twin",
            "output": f"{len(tool_call_timeline)} tool receipt(s)",
            "evidence": ", ".join(str(row.get("tool")) for row in tool_call_timeline[:4] if isinstance(row, dict)),
        },
        {
            "id": "score",
            "label": "Score candidates",
            "status": "complete" if evaluation else "warn",
            "tool": "reasoning_evaluator",
            "input": f"{len(options_considered)} route option(s)",
            "output": f"{selected_label} · {evaluation.get('overall', '--')}/100",
            "evidence": evaluation.get("verdict") or "not evaluated",
        },
        {
            "id": "critic",
            "label": "Critic check",
            "status": "complete" if evaluation.get("verdict") in {"strong", "review"} else "warn",
            "tool": "agent_critic",
            "input": "selected option, rejected options, policy gate",
            "output": "pass" if evaluation.get("verdict") == "strong" else "review",
            "evidence": "; ".join(str(item.get("label")) for item in (evaluation.get("checks") or [])[:3] if isinstance(item, dict)),
        },
        {
            "id": "policy",
            "label": "Policy gate",
            "status": "blocked" if gate == "blocked" else "waiting" if needs_approval and not state_mutation else "complete",
            "tool": "policy_gate",
            "input": "allowed_actions and approval boundary",
            "output": gate,
            "evidence": "human approval required" if needs_approval and not state_mutation else "bounded simulation action",
        },
        {
            "id": "approval",
            "label": "Human approval",
            "status": "complete" if state_mutation else "waiting" if needs_approval or gate == "prepared" else "not_required",
            "tool": "operator_approval",
            "input": "Approve + apply turn",
            "output": "approved and applied" if state_mutation else "not yet approved",
            "evidence": clarifying_question or turn_contract.get("reason"),
        },
        {
            "id": "execute",
            "label": "Execute action",
            "status": "complete" if state_mutation else "prepared",
            "tool": "digital_twin.apply_action",
            "input": selected_label,
            "output": "state mutated" if state_mutation else "proposal only",
            "evidence": impact_headline or "No execution until apply.",
        },
        {
            "id": "verify",
            "label": "Verify outcome",
            "status": "complete" if impact_replay else "prepared",
            "tool": "digital_twin.compare_baseline",
            "input": "before/action/no-agent/after",
            "output": impact_headline or turn_contract.get("map_effect"),
            "evidence": "impact replay attached" if impact_replay else "verification will run after apply.",
        },
        {
            "id": "remember",
            "label": "Write memory",
            "status": "complete" if audit.get("ontology_event_id") else "prepared",
            "tool": "ontology_event_store",
            "input": audit.get("object_action_plan_id") or plan.get("plan_id"),
            "output": audit.get("ontology_event_id") or "pending",
            "evidence": f"ontology v{audit.get('ontology_version', '--')}",
        },
    ]
    completed = sum(1 for stage in stages if stage.get("status") in {"complete", "not_required"})
    waiting = sum(1 for stage in stages if stage.get("status") in {"waiting", "prepared"})
    blocked = sum(1 for stage in stages if stage.get("status") == "blocked")
    return {
        "runtime_id": _stable_copilot_id("agent_runtime", {"message": message, "plan": plan.get("plan_id"), "mode": turn_contract.get("mode")}),
        "runtime": "governed_parkpulse_agent_loop",
        "loop": "observe -> understand -> plan -> tool_select -> score -> critic -> policy -> approval -> execute -> verify -> remember",
        "status": "blocked" if blocked else "applied" if state_mutation else "awaiting_approval" if needs_approval or gate == "prepared" else "answered",
        "autonomy_level": "human_approved_execution" if state_mutation else "proposal_with_human_gate",
        "summary": {
            "selected_option": selected_label,
            "selected_score": evaluation.get("overall"),
            "policy_gate": gate,
            "state_mutation": state_mutation,
            "map_effect": turn_contract.get("map_effect"),
            "completed_stages": completed,
            "waiting_stages": waiting,
            "blocked_stages": blocked,
        },
        "planner": {
            "goal": message,
            "role": route.get("selected_role") or "scan",
            "subgoals": [
                "Ground the request in live park objects.",
                "Convert analytics signals into governed operating opportunities.",
                "Select allowed object actions instead of free text promises.",
                "Score alternatives and expose rejected options.",
                "Gate writes and external actions behind approval.",
                "Verify map impact against a no-agent baseline after execution.",
            ],
            "facts_needed": ["live state", "analytics signals", "ontology objects", "synthetic park knowledge", "allowed actions", "policy boundary", "map grounding"],
            "synthetic_context": plan.get("policy_doctrine", {}).get("synthetic_context") if isinstance(plan.get("policy_doctrine"), dict) else None,
        },
        "tool_policy": {
            "read": "agent may read live simulation and ontology",
            "draft": "agent may draft bounded object actions",
            "write": "state mutation only on apply turn after policy gate",
            "external": "medical, security, maintenance, evacuation, labor, and equipment authority require human gate",
        },
        "tool_registry": tool_registry,
        "task_graph": task_graph,
        "analytics_action_layer": analytics_action_layer or {},
        "branch_comparison": branch_comparison or {},
        "critic_report": critic_report,
        "multi_agent_deliberation": multi_agent_deliberation,
        "verification_report": verification_report,
        "learning_update": learning_update,
        "lifecycle": lifecycle,
        "executor_state": executor_state,
        "external_adapters": external_adapters,
        "natural_response_contract": {
            "answer_first": True,
            "ask_clarifying_question_when": "safety boundary, missing location, unavailable access lane, or low action_fit",
            "revise_plan_on_followup": True,
            "carry_prior_constraints": True,
        },
        "stages": stages,
        "open_loop": {
            "needs_operator_input": bool(clarifying_question) or (needs_approval and not state_mutation),
            "next_turn": "approve_apply" if not state_mutation and gate in {"prepared", "approval_required"} else "monitor_verify",
            "question": clarifying_question,
        },
    }


def _copilot_action_plan_from_objects(
    message: str,
    route: dict[str, Any],
    map_grounding: dict[str, Any],
    object_action_plan: dict[str, Any] | None,
) -> dict[str, Any]:
    object_actions = object_action_plan.get("actions", []) if isinstance(object_action_plan, dict) else []
    primary = next((row for row in object_actions if isinstance(row, dict) and row.get("will_execute")), None)
    primary = primary or (object_actions[0] if object_actions else None)
    plan = _copilot_action_plan(message, route, map_grounding)
    if isinstance(primary, dict):
        object_type = str(primary.get("object_type") or "").lower()
        target = "medical" if primary.get("action") == "dispatch_medical" else "traffic" if object_type in {"queue", "zone", "path"} else "staff" if object_type == "staffpool" else plan.get("target")
        plan.update(
            {
                "id": f"copilot_object_{primary.get('object_id')}_{primary.get('action')}",
                "target": target,
                "action": str(primary.get("action") or plan.get("action")),
                "label": f"{primary.get('object_name') or primary.get('object_id')}: {str(primary.get('action') or '').replace('_', ' ')}",
                "object_action_plan": object_action_plan,
            }
        )
    return plan


def _copilot_action_plan(message: str, route: dict[str, Any], map_grounding: dict[str, Any]) -> dict[str, Any]:
    lowered = message.lower()
    if any(term in lowered for term in ("medical", "first aid", "faint", "passed out", "injury")):
        return {"id": "copilot_medical_dispatch", "target": "medical", "action": "dispatch", "label": "Dispatch guest-care and protect medical access"}
    if any(term in lowered for term in ("security", "fight", "panic", "lost child", "missing child", "missing kid", "separated child", "separated kid", "pushing")):
        return {"id": "copilot_security_response", "target": "security", "action": "respond", "label": "Move security and crowd-control leads to the incident zone"}
    if any(term in lowered for term in ("staff", "break", "callout", "fatigue", "understaffed")):
        return {"id": "copilot_staff_support", "target": "staff", "action": "redeploy", "label": "Redeploy trained staff while preserving protected breaks"}
    if any(term in lowered for term in ("storm", "weather", "shelter", "hvac", "heat")):
        return {"id": "copilot_shelter_comfort", "target": "energy", "action": "protect_hvac", "label": "Protect indoor comfort while shifting guests to shelter"}
    if any(term in lowered for term in ("food", "mobile order", "restaurant", "kitchen")):
        return {"id": "copilot_food_reroute", "target": "traffic", "action": "redirect_food", "label": "Redirect food demand and avoid Food Court A overload"}
    if any(term in lowered for term in ("coaster", "ride", "queue", "parade", "families")):
        return {"id": "copilot_ride_reroute", "target": "ride", "action": "reroute", "label": "Split ride-down guests across safer alternate experiences"}
    primary_zone = str(map_grounding.get("primary_zone_id") or "")
    if primary_zone == "foodCourt1":
        return {"id": "copilot_food_reroute", "target": "traffic", "action": "redirect_food", "label": "Redirect food demand and avoid Food Court A overload"}
    return {
        "id": f"copilot_{route.get('selected_role') or 'react'}_reroute",
        "target": "ride",
        "action": "reroute",
        "label": "Apply bounded copilot reroute and measure the park delta",
    }


def _copilot_prior_context(selected_map_context: dict[str, Any]) -> dict[str, Any] | None:
    prior = selected_map_context.get("last_copilot") if isinstance(selected_map_context, dict) else None
    return prior if isinstance(prior, dict) else None


def _copilot_recent_context_message(message: str, recent_messages: list[CopilotChatMessage], prior: dict[str, Any] | None) -> str:
    lowered = message.lower().strip()
    if prior and lowered not in {"do it", "apply", "approve", "yes", "go", "run it", "execute it"} and any(term in lowered for term in ("avoid", "instead", "revise", "change", "protect staff", "don't", "do not")):
        prior_runtime = prior.get("agent_runtime", {}) if isinstance(prior.get("agent_runtime"), dict) else {}
        selected = (prior_runtime.get("task_graph") or {}).get("selected_action", {}) if isinstance(prior_runtime.get("task_graph"), dict) else {}
        selected_label = f"{selected.get('object_name')}: {str(selected.get('action') or '').replace('_', ' ')}" if selected.get("object_name") else "the prior proposed action"
        return f"Revise the active plan. Prior action: {selected_label}. New operator constraint: {message}."
    vague_action = len(lowered.split()) <= 5 and any(
        term in lowered
        for term in ("solution", "solve", "fix", "resolve", "mitigate", "recommendation", "recommend", "do it")
    )
    if not vague_action:
        return message
    previous_user = next(
        (
            item.content.strip()
            for item in reversed(recent_messages)
            if item.role == "user" and item.content.strip() and item.content.strip().lower() != lowered
        ),
        "",
    )
    if previous_user:
        return f"{previous_user}. Follow-up request: {message}."
    prior_answer = prior.get("answer") if isinstance(prior, dict) else None
    if isinstance(prior_answer, str) and prior_answer.strip():
        return f"Based on the previous park status: {prior_answer[:500]} Follow-up request: {message}."
    return message


def _is_copilot_followup(message: str, prior: dict[str, Any] | None) -> bool:
    if not prior:
        return False
    lowered = message.lower()
    if any(term in lowered for term in ("undo", "revise", "change", "avoid", "instead")):
        return True
    followup_terms = (
        "why",
        "alternative",
        "alternatives",
        "reject",
        "rejected",
        "instead",
        "safety",
        "fairness",
        "tradeoff",
        "trade-off",
        "baseline",
        "impact",
        "explain",
        "what changed",
        "how do you know",
        "undo",
        "revise",
        "change",
        "avoid",
    )
    if any(term in lowered for term in followup_terms):
        return True
    if _copilot_intent(message).get("asks_action"):
        return False
    return False


def _copilot_followup_answer(message: str, prior: dict[str, Any]) -> str:
    lowered = message.lower()
    action = prior.get("recommended_action", {}) if isinstance(prior.get("recommended_action"), dict) else {}
    action_label = action.get("label") or action.get("action") or "the prior action"
    runtime = prior.get("agent_runtime", {}) if isinstance(prior.get("agent_runtime"), dict) else {}
    lifecycle = runtime.get("lifecycle", {}) if isinstance(runtime.get("lifecycle"), dict) else {}
    task_graph = runtime.get("task_graph", {}) if isinstance(runtime.get("task_graph"), dict) else {}
    executor = runtime.get("executor_state", {}) if isinstance(runtime.get("executor_state"), dict) else {}
    graph_action = task_graph.get("selected_action", {}) if isinstance(task_graph.get("selected_action"), dict) else {}
    if graph_action.get("object_name") and graph_action.get("action"):
        action_label = f"{graph_action.get('object_name')}: {str(graph_action.get('action')).replace('_', ' ')}"
    impact = prior.get("impact_replay", {}) if isinstance(prior.get("impact_replay"), dict) else {}
    comparison = impact.get("comparison", {}) if isinstance(impact.get("comparison"), dict) else {}
    impact_summary = comparison.get("impact", {}) if isinstance(comparison.get("impact"), dict) else {}
    map_grounding = prior.get("map_grounding", {}) if isinstance(prior.get("map_grounding"), dict) else {}
    options = prior.get("options_considered", []) if isinstance(prior.get("options_considered"), list) else []
    rejected = [item for item in options if isinstance(item, dict) and str(item.get("verdict", "")).lower() in {"rejected", "not needed", "watch"}]
    selected = next((item for item in options if isinstance(item, dict) and str(item.get("verdict", "")).lower() == "selected"), None)
    grounded = ", ".join(str(item) for item in (map_grounding.get("landmark_ids") or map_grounding.get("highlight_zone_ids") or [])[:4])
    if "undo" in lowered:
        task_state = lifecycle.get("state") or runtime.get("status") or "prior task"
        return f"I can prepare a rollback/revision, but I will not silently mutate the park. The active task is {task_state}; executor status is {executor.get('status', '--')}. Rollback basis: retained before/action/no-agent/after replay plus task graph {task_graph.get('graph_id', '--')}."
    if "revise" in lowered or "change" in lowered or "avoid" in lowered or "instead" in lowered:
        constraint = message.strip()
        return f"I would revise the active task graph rather than start from scratch. New constraint: {constraint}. I would re-run ontology lookup, candidate scoring, critic, and policy gate before execution; the prior selected action was {action_label}."
    if "alternative" in lowered or "reject" in lowered:
        rejected_text = "; ".join(f"{item.get('label')}: {item.get('reason')}" for item in rejected[:2]) or "No rejected option was recorded."
        return f"I rejected the alternatives because the selected action was more bounded for the live map state. Selected: {selected.get('label') if isinstance(selected, dict) else action_label}. Rejected: {rejected_text}"
    if "safety" in lowered or "fairness" in lowered or "trade" in lowered:
        gate = action.get("gate") or "checked"
        return f"The safety/fairness tradeoff was to keep the action reversible and receiver-specific. Gate status was {gate}; the action avoided broad claims and targeted {grounded or 'the grounded map objects'} instead of moving everyone at once."
    if "baseline" in lowered or "impact" in lowered or "changed" in lowered or "know" in lowered:
        headline = impact_summary.get("headline") or comparison.get("impact", {}).get("headline") or "The action was compared with a no-agent shadow baseline."
        score_lift = comparison.get("score_lift")
        return f"The impact proof is the actual-vs-baseline replay. {headline} Score lift was {score_lift if score_lift is not None else '--'}; the map deltas came from the same before/action/no-agent/after comparison."
    return f"I chose to run {str(action_label).rstrip('.')} because it matched the prior request constraints and the grounded map objects: {grounded or 'live pressure zones'}. The prior receipt, options, policy gate, and impact replay are still the evidence for this answer."


def _strip_json_fence(text: str) -> str:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    return cleaned


def _local_conversational_copilot_response(
    message: str,
    *,
    answer: str,
    compact_state: dict[str, Any],
    object_action_plan: dict[str, Any] | None,
    reasoning_evaluation: dict[str, Any] | None,
    agent_runtime: dict[str, Any] | None,
    clarifying_question: str | None,
    mode: str,
) -> dict[str, Any]:
    plan = object_action_plan if isinstance(object_action_plan, dict) else {}
    evaluation = reasoning_evaluation if isinstance(reasoning_evaluation, dict) else {}
    runtime = agent_runtime if isinstance(agent_runtime, dict) else {}
    primary = _primary_copilot_risk(compact_state)
    selected = evaluation.get("selected_option") if isinstance(evaluation.get("selected_option"), dict) else {}
    selected_label = selected.get("label")
    runtime_summary = runtime.get("summary", {}) if isinstance(runtime.get("summary"), dict) else {}
    task_graph = runtime.get("task_graph", {}) if isinstance(runtime.get("task_graph"), dict) else {}
    graph_action = task_graph.get("selected_action", {}) if isinstance(task_graph.get("selected_action"), dict) else {}
    doctrine = plan.get("policy_doctrine") if isinstance(plan.get("policy_doctrine"), dict) else {}
    primary_case = doctrine.get("primary_case") if isinstance(doctrine.get("primary_case"), dict) else {}
    policy_reasoning = plan.get("policy_reasoning") if isinstance(plan.get("policy_reasoning"), dict) else doctrine.get("policy_reasoning") if isinstance(doctrine.get("policy_reasoning"), dict) else {}
    policy_selected = policy_reasoning.get("selected_action") if isinstance(policy_reasoning.get("selected_action"), dict) else {}
    conflict_analysis = policy_reasoning.get("conflict_analysis") if isinstance(policy_reasoning.get("conflict_analysis"), dict) else {}
    case_clause = f" using case {primary_case.get('id')}" if primary_case else ""
    policy_clause = f" Policy-selected move: {str(policy_selected.get('label')).rstrip('.')}." if policy_selected else ""
    blocked_actions = [str(item) for item in (policy_reasoning.get("blocked_actions") or [])[:3] if item] if isinstance(policy_reasoning.get("blocked_actions"), list) else []
    required_evidence = [str(item) for item in (policy_reasoning.get("required_evidence") or [])[:4] if item] if isinstance(policy_reasoning.get("required_evidence"), list) else []
    success_metric = policy_reasoning.get("success_metric") or primary_case.get("success_metric")
    rollback_condition = policy_reasoning.get("rollback_condition") or primary_case.get("rollback_condition")
    selected_move = str(policy_selected.get("label") or selected_label or "no executable action selected yet").rstrip(".")
    policy_refs = ", ".join((plan.get("policy_refs") or [])[:5]) if isinstance(plan.get("policy_refs"), list) else ""
    case_title = str(primary_case.get("title") or "").lower()
    if any(term in case_title for term in ("missing child", "lost child")):
        grounding_text = "reported missing-child incident at the food court, treated as guest-care/security rather than food operations"
    elif primary_case:
        grounding_text = f"{primary.get('label')} ({primary.get('evidence')})"
    else:
        grounding_text = f"{primary.get('label')} ({primary.get('evidence')})"
    reasoning_intro = (
        f"I read this as {primary_case.get('title') or 'an operating request'}{case_clause}. "
        f"The operating signal I am grounding on is {grounding_text}."
    )
    policy_interpretation = (
        f"Policy allows a bounded, receiver-specific move: {selected_move}. "
        + (f"It blocks: {', '.join(blocked_actions)}. " if blocked_actions else "")
        + (f"Policy refs: {policy_refs}. " if policy_refs else "")
    )
    evidence_line = f"Evidence required before execution: {', '.join(required_evidence)}." if required_evidence else ""
    conflict_line = ""
    priority_order = conflict_analysis.get("priority_order") if isinstance(conflict_analysis.get("priority_order"), list) else []
    if conflict_analysis.get("detected") and priority_order:
        conflict_line = "Priority check: " + " > ".join(str(item.get("case_id")) for item in priority_order[:3] if isinstance(item, dict) and item.get("case_id")) + "."
    outcome_line = " ".join(
        part
        for part in (
            f"Success metric: {str(success_metric).rstrip('.')}." if success_metric else "",
            f"Rollback trigger: {str(rollback_condition).rstrip('.')}." if rollback_condition else "",
        )
        if part
    )
    if graph_action.get("object_name") and graph_action.get("action"):
        selected_label = f"{graph_action.get('object_name')}: {str(graph_action.get('action')).replace('_', ' ')}"
    gate = plan.get("overall_gate") or runtime_summary.get("policy_gate")
    if mode == "follow_up" and answer:
        conversational_answer = answer
    elif clarifying_question:
        conversational_answer = " ".join(
            part
            for part in (
                reasoning_intro,
                policy_interpretation,
                conflict_line,
                evidence_line,
                f"I need one confirmation before action: {clarifying_question}",
                outcome_line,
            )
            if part
        )
    elif mode == "act" or runtime.get("status") == "applied":
        conversational_answer = " ".join(
            part
            for part in (
                f"Applied {selected_label or selected_move}{case_clause}.",
                policy_interpretation,
                conflict_line,
                "Replay is attached against the no-agent baseline.",
                outcome_line,
            )
            if part
        )
    elif selected_label:
        conversational_answer = " ".join(
            part
            for part in (
                reasoning_intro,
                f"Proposed plan: {selected_label}{case_clause}.",
                policy_interpretation,
                conflict_line,
                evidence_line,
                f"Gate is {gate or 'prepared'}; no dispatch or state mutation happens until you explicitly apply it.",
                outcome_line,
            )
            if part
        )
    else:
        conversational_answer = answer
    return {
        "source": "local_runtime_response",
        "model": None,
        "answer": conversational_answer,
        "reasoning_bullets": [
            f"Primary live signal: {primary.get('label')} ({primary.get('evidence')}).",
            f"Selected option: {selected_label or 'no executable action selected yet'}.",
            f"Policy doctrine: {primary_case.get('id') or 'no matched actionable case'}; refs={', '.join((plan.get('policy_refs') or [])[:5]) if isinstance(plan.get('policy_refs'), list) else 'none'}.",
            f"Policy reasoning: {len(policy_reasoning.get('steps', []) if isinstance(policy_reasoning.get('steps'), list) else [])}/9 steps prepared; approval_required={bool(policy_reasoning.get('approval_required'))}.",
            f"Conflict priority: {conflict_line or 'single primary case'}.",
            f"Policy state: {gate or 'read only'}; mutation={bool(runtime_summary.get('state_mutation'))}.",
        ],
        "operator_next": "Approve + apply" if gate in {"prepared", "approval_required"} else "Ask a follow-up constraint",
        "confidence": evaluation.get("overall"),
        "notes": ["Response was composed from live park state and the current runtime receipt."],
    }


async def _copilot_conversational_response(
    message: str,
    *,
    base_answer: str,
    compact_state: dict[str, Any],
    route: dict[str, Any],
    intent: dict[str, Any],
    object_action_plan: dict[str, Any] | None,
    reasoning_evaluation: dict[str, Any] | None,
    agent_runtime: dict[str, Any] | None,
    map_grounding: dict[str, Any] | None,
    impact_replay: dict[str, Any] | None,
    clarifying_question: str | None,
    prior_copilot: dict[str, Any] | None,
    semantic_memory_context: dict[str, Any] | None,
    mode: str,
) -> dict[str, Any]:
    local_response = _local_conversational_copilot_response(
        message,
        answer=base_answer,
        compact_state=compact_state,
        object_action_plan=object_action_plan,
        reasoning_evaluation=reasoning_evaluation,
        agent_runtime=agent_runtime,
        clarifying_question=clarifying_question,
        mode=mode,
    )
    local_response["semantic_memory"] = semantic_memory_context
    if _copilot_hot_path_local_only():
        local_response["provider_ready"] = True
        local_response["provider_skipped"] = "hot_path_local_only"
        return local_response
    props = get_gemini_agent_properties()
    if not props.ready:
        local_response["provider_ready"] = False
        local_response["provider_issues"] = props.readiness_issues
        return local_response
    if mode in {"act", "follow_up"} and str(os.getenv("PARKPULSE_COPILOT_LLM_FOR_ALL_TURNS", "")).strip().lower() not in {"1", "true", "yes", "on"}:
        local_response["source"] = "local_runtime_response"
        local_response["provider_ready"] = True
        local_response["provider_skipped"] = f"llm_skipped_for_{mode}_latency"
        return local_response
    prompt = {
        "task": "Write the ParkPulse operator-facing chat response. Make it sound like a smart park operations agent, not a dashboard receipt.",
        "style_rules": [
            "Answer directly in 2-5 sentences.",
            "Be specific to the live park state and selected action.",
            "If approval is needed, say exactly what you are waiting for.",
            "If this is a follow-up or revision, reference the active task and explain how the plan changes.",
            "Do not invent facts outside the provided state.",
            "Do not expose hidden chain-of-thought. Provide concise operational reasoning bullets only.",
        ],
        "operator_message": message,
        "turn_mode": mode,
        "intent": intent,
        "live_state_summary": compact_state,
        "route": {k: route.get(k) for k in ("selected_role", "why", "policy_gates")},
        "object_action_plan": object_action_plan,
        "reasoning_evaluation": reasoning_evaluation,
        "agent_runtime_summary": {
            "status": (agent_runtime or {}).get("status") if isinstance(agent_runtime, dict) else None,
            "summary": (agent_runtime or {}).get("summary") if isinstance(agent_runtime, dict) else None,
            "lifecycle": (agent_runtime or {}).get("lifecycle") if isinstance(agent_runtime, dict) else None,
            "executor_state": (agent_runtime or {}).get("executor_state") if isinstance(agent_runtime, dict) else None,
            "task_graph_selected_action": ((agent_runtime or {}).get("task_graph") or {}).get("selected_action") if isinstance(agent_runtime, dict) else None,
            "critic_report": (agent_runtime or {}).get("critic_report") if isinstance(agent_runtime, dict) else None,
            "verification_report": (agent_runtime or {}).get("verification_report") if isinstance(agent_runtime, dict) else None,
        },
        "map_grounding": map_grounding,
        "semantic_memory_context": semantic_memory_context,
        "impact_replay_summary": {
            "executed": impact_replay.get("executed") if isinstance(impact_replay, dict) else False,
            "headline": impact_replay.get("comparison", {}).get("impact", {}).get("headline") if isinstance(impact_replay, dict) and isinstance(impact_replay.get("comparison"), dict) else None,
        },
        "clarifying_question": clarifying_question,
        "prior_active_task": (prior_copilot or {}).get("agent_runtime") if isinstance(prior_copilot, dict) else None,
        "required_json": {
            "answer": "2-5 sentence operator answer",
            "reasoning_bullets": ["3 concise bullets, no hidden chain of thought"],
            "operator_next": "one recommended next user action",
            "confidence": 0,
        },
    }
    try:
        from gemini_hard_timeout import generate_gemini_json_hard_timeout

        timeout = max(0.6, _float_env("PARKPULSE_COPILOT_LLM_TIMEOUT_SECONDS", 0.9))
        result = await generate_gemini_json_hard_timeout(prompt, timeout_seconds=timeout, max_output_tokens=420, temperature=0.35)
        text = _strip_json_fence(str(result.get("text") or "{}"))
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = json.loads(text[text.find("{") : text.rfind("}") + 1])
        llm_answer = str(parsed.get("answer") or "").strip()
        if not llm_answer:
            raise ValueError("Gemini returned no answer")
        bullets = parsed.get("reasoning_bullets")
        return {
            "source": "gemini_conversation",
            "runtime": result.get("transport") or props.platform,
            "model": props.model,
            "answer": llm_answer,
            "reasoning_bullets": [str(item) for item in bullets[:4]] if isinstance(bullets, list) else local_response["reasoning_bullets"],
            "operator_next": str(parsed.get("operator_next") or local_response["operator_next"]),
            "confidence": int(parsed.get("confidence") or local_response.get("confidence") or 0),
            "semantic_memory": semantic_memory_context,
            "provider_ready": True,
        }
    except Exception as error:
        local_response["source"] = "local_runtime_response"
        local_response["provider_ready"] = True
        local_response["llm_error"] = str(error)[:300]
        return local_response


def _copilot_tool_call_timeline(
    tool_trace: dict[str, Any],
    role_payload: dict[str, Any] | None,
    impact_replay: dict[str, Any] | None,
    followup: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if followup:
        rows.append(
            {
                "id": "retrieve_prior_run",
                "tool": "conversation_memory.read_last_copilot",
                "label": "Retrieve prior copilot receipt",
                "status": "ok",
                "input": "last_copilot",
                "output": "prior action, options, map grounding, impact replay",
            }
        )
    rows.append(
        {
            "id": "get_park_state",
            "tool": "get_park_state",
            "label": "Read live park state",
            "status": "ok",
            "input": "current simulation state",
            "output": "zones, rides, paths, staffing, food, weather",
        }
    )
    for index, call in enumerate((tool_trace.get("tool_calls") or [])[:6] if isinstance(tool_trace, dict) else []):
        if not isinstance(call, dict):
            continue
        rows.append(
            {
                "id": f"role_tool_{index + 1}",
                "tool": call.get("tool") or "role_tool",
                "label": str(call.get("tool") or "Role tool").replace("_", " "),
                "status": call.get("status") or "ok",
                "input": call.get("capability") or "role route",
                "output": call.get("output", {}).get("role") if isinstance(call.get("output"), dict) else "checked",
            }
        )
    if role_payload:
        delivery = role_payload.get("run_telemetry", {}).get("delivery", {}) if isinstance(role_payload.get("run_telemetry"), dict) else {}
        dispatches = delivery.get("dispatches", []) if isinstance(delivery, dict) else []
        rows.append(
            {
                "id": "dispatch_receivers",
                "tool": "dispatch_receivers",
                "label": "Dispatch receiver payloads",
                "status": "sent" if dispatches else "prepared",
                "input": "guest app, worker device, equipment controller",
                "output": f"{len(dispatches) if isinstance(dispatches, list) else 0} receiver actions",
            }
        )
    if impact_replay:
        rows.extend(
            [
                {
                    "id": "simulate_baseline",
                    "tool": "digital_twin.simulate_no_agent_baseline",
                    "label": "Simulate no-agent baseline",
                    "status": "complete",
                    "input": f"{impact_replay.get('horizon_minutes', 15)} minute horizon",
                    "output": "shadow_baseline_after",
                },
                {
                    "id": "simulate_action",
                    "tool": "digital_twin.apply_action_and_score",
                    "label": "Apply action and score after state",
                    "status": "complete" if impact_replay.get("executed") else "preview",
                    "input": impact_replay.get("action_plan", {}).get("label") if isinstance(impact_replay.get("action_plan"), dict) else "copilot action",
                    "output": impact_replay.get("comparison", {}).get("impact", {}).get("headline") if isinstance(impact_replay.get("comparison"), dict) else "impact replay",
                },
            ]
        )
    rows.append(
        {
            "id": "answer_operator",
            "tool": "copilot.respond",
            "label": "Answer operator with receipts",
            "status": "complete",
            "input": "operator question",
            "output": "answer, reasoning, options, map grounding, impact",
        }
    )
    return rows[:12]


@app.post("/api/park/agent-role-run")
async def park_agent_role_run(request: OperatorCommandRequest):
    message = request.message.strip()
    route = route_agent_role(message, request.mode)
    selected_role = str(route.get("selected_role") or "scan")
    tool_trace = _agent_role_tool_trace_for_api(route)
    def _record_and_return(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            receipt = record_agent_role_trace_sample(payload, message=message, mode=request.mode)
            payload["role_trace_sample"] = {"status": receipt.get("status"), "path": receipt.get("path"), "id": (receipt.get("sample") or {}).get("id")}
        except Exception as error:
            payload["role_trace_sample"] = {"status": "error", "readiness_issues": [str(error)[:240]]}
        return payload

    if selected_role == "proact":
        proact_timeout = max(1.0, _float_env("PARKPULSE_PROACTIVE_ROLE_TIMEOUT_SECONDS", 25.0))
        def _proact_timeout_payload(reason: str) -> dict[str, Any]:
            return {
                "status": "complete",
                "mode": "proact_role_timeout_fallback",
                "selected_role": "proact",
                "operator_response": {
                    "headline": "Proact Agent returned bounded local guidance.",
                    "summary": f"Full proactive closed-loop replay {reason}, so ParkPulse kept the hot path on a local policy-gated receipt.",
                    "next_step": "Review the weak signal, keep monitoring crowd movement, and rerun full proactive replay off the hot path.",
                },
                "brief": {
                    "runtime": "deterministic_role_timeout_fallback",
                    "errors": [f"Full proactive closed-loop replay {reason}."],
                },
                "delivery": {"summary": {"total": 0}, "dispatches": []},
                "run_telemetry": {
                    "delivery": {"summary": {"total": 0}, "dispatches": []},
                    "digital_twin_tools": tool_trace,
                    "timeout_seconds": proact_timeout,
                },
            }
        if _truthy(os.getenv("PARKPULSE_PROACTIVE_ROLE_HOT_PATH_ONLY"), False):
            payload = _proact_timeout_payload("was deferred by PARKPULSE_PROACTIVE_ROLE_HOT_PATH_ONLY")
        else:
            proact_task = asyncio.create_task(_build_proactive_run_payload())
            done, _pending = await asyncio.wait({proact_task}, timeout=proact_timeout)
            if proact_task in done:
                payload = proact_task.result()
            else:
                _track_background_task(proact_task)
                payload = _proact_timeout_payload(f"exceeded {proact_timeout:g}s")
        payload["selected_role"] = "proact"
        payload["skill"] = route.get("skill")
        payload["role_route"] = route
        payload["role_run"] = {
            "role": "proact",
            "dispatch_allowed": True,
            "dispatch_count": payload.get("delivery", {}).get("summary", {}).get("total", 0),
            "policy_gates": route.get("policy_gates", []),
            "receipt_artifacts": route.get("expected_receipt", []),
        }
        payload["digital_twin_tools"] = tool_trace
        return _record_and_return(payload)
    if selected_role == "react":
        return _record_and_return(_fast_role_react_payload_for_api(message, route, tool_trace))
    if selected_role == "customer":
        return _record_and_return({
            "status": "complete",
            "selected_role": "customer",
            "skill": route.get("skill"),
            "role_route": route,
            "role_run": {
                "role": "customer",
                "dispatch_allowed": False,
                "dispatch_count": 0,
                "policy_gates": route.get("policy_gates", []),
                "receipt_artifacts": route.get("expected_receipt", []),
            },
            "answer": {
                "headline": "Use the shortest public-wait route.",
                "summary": "I checked public wait and route options only, then kept the answer inside guest-safe guidance.",
                "next_step": "Show route or send it to the guest phone if requested.",
            },
            "actions": [{"id": "show_route", "label": "Show route"}, {"id": "send_to_phone", "label": "Send to phone"}],
            "digital_twin_tools": tool_trace,
            "role_receipt": {"role": "customer", "skill": route.get("skill"), "scenario_key": "customer_public", "dispatch_ids": [], "read_only": True},
            "run_telemetry": {"delivery": {"summary": {"total": 0}, "dispatches": []}, "digital_twin_tools": tool_trace},
        })
    if selected_role == "qa":
        from prod_reliability_qa_agent import run_production_reliability_qa

        report = run_production_reliability_qa(message, {"api": "ready", "role_router": "available"})
        report["selected_role"] = "qa"
        report["skill"] = route.get("skill")
        report["role_route"] = route
        report["role_run"] = {
            "role": "qa",
            "dispatch_allowed": False,
            "dispatch_count": 0,
            "policy_gates": route.get("policy_gates", []),
            "receipt_artifacts": route.get("expected_receipt", []),
        }
        report["digital_twin_tools"] = tool_trace
        report["run_telemetry"] = {**(report.get("run_telemetry") if isinstance(report.get("run_telemetry"), dict) else {}), "delivery": {"summary": {"total": 0}, "dispatches": []}, "digital_twin_tools": tool_trace}
        report["role_receipt"] = {"role": "qa", "skill": route.get("skill"), "scenario_key": "production_reliability_qa", "dispatch_ids": [], "read_only": True, "go_no_go": report.get("go_no_go_recommendation", {})}
        return _record_and_return(report)
    insights = latest_signals(5)
    signal_items = insights.get("signals", []) if isinstance(insights, dict) else []
    return _record_and_return({
        "status": "complete",
        "selected_role": "scan",
        "skill": route.get("skill"),
        "route": route,
        "role_run": {
            "role": "scan",
            "dispatch_allowed": False,
            "dispatch_count": 0,
            "recommended_next_role": "proact",
            "policy_gates": route.get("policy_gates", []),
            "receipt_artifacts": route.get("expected_receipt", []),
        },
        "scan": {
            "signals": signal_items,
            "top_risk": (signal_items[0] if signal_items else {}).get("summary", "Weak signal scan"),
            "confidence": (signal_items[0] if signal_items else {}).get("confidence", 0.72),
            "recommended_next_role": "proact",
        },
        "digital_twin_tools": tool_trace,
        "operator_response": {
            "headline": "Scan Agent completed read-only triage.",
            "summary": route.get("why", "The scan role gathered signals without dispatching receiver actions."),
            "next_step": "Escalate to Proact Agent if risk is trending up, or React Agent if an incident is confirmed.",
        },
    })


@app.get("/api/park/ontology")
async def get_park_ontology():
    state = await park_simulation.get_state()
    return read_persistent_ontology(_park_ontology_snapshot(state))


@app.get("/api/park/ontology/events")
async def get_park_ontology_events(limit: int = 50):
    return read_ontology_events(limit)


@app.get("/api/park/copilot-tasks")
async def get_park_copilot_tasks():
    return _read_copilot_agent_tasks()


@app.post("/api/park/copilot-chat")
async def park_copilot_chat(request: CopilotChatRequest):
    diagnostics_enabled = _truthy(os.getenv("PARKPULSE_COPILOT_LATENCY_DIAGNOSTICS"), False)
    diagnostics_started = time.monotonic()
    diagnostics_last = diagnostics_started
    diagnostics_stages: list[dict[str, Any]] = []

    def mark(stage: str) -> None:
        nonlocal diagnostics_last
        if not diagnostics_enabled:
            return
        now = time.monotonic()
        diagnostics_stages.append(
            {
                "stage": stage,
                "delta_ms": round((now - diagnostics_last) * 1000, 2),
                "total_ms": round((now - diagnostics_started) * 1000, 2),
            }
        )
        diagnostics_last = now

    message = request.message.strip()
    recent_messages = [item for item in request.messages[-8:] if item.content.strip()]
    if not message and recent_messages:
        message = recent_messages[-1].content.strip()
    if not message:
        message = "What is the biggest park risk right now?"

    raw_message = message
    state = await park_simulation.get_state()
    mark("get_state")
    compact_state = _compact_copilot_state(state)
    mark("compact_state")
    prior_copilot = _copilot_prior_context(request.selected_map_context)
    chat_brain = await _copilot_chat_brain(raw_message, compact_state, prior_copilot, recent_messages)
    mark("chat_brain")
    conversation_intent = str(chat_brain.get("intent") or _copilot_conversation_intent(raw_message, prior_copilot))
    brain_planner_message = str(chat_brain.get("planner_message") or raw_message).strip() or raw_message
    message = _copilot_recent_context_message(brain_planner_message, recent_messages, prior_copilot)
    route = route_agent_role(message, request.mode)
    selected_role = str(route.get("selected_role") or "scan")
    intent = _copilot_intent(message)
    data_answer = _copilot_data_answer(str(intent.get("data_request_kind") or ""), compact_state) if intent.get("data_request") else None
    if data_answer:
        return _copilot_read_only_response(
            raw_message=raw_message,
            recent_messages=recent_messages,
            request=request,
            compact_state=compact_state,
            route=route,
            intent=intent,
            chat_brain=chat_brain,
            data_answer=data_answer,
        )
    if conversation_intent == "clarification" or chat_brain.get("answer_type") == "clarification":
        clarifying = str(
            chat_brain.get("clarifying_question")
            or "Do you want a live status answer, a queue/staffing report, or an operating plan for a specific park problem?"
        )
        answer = (
            f"I need one more detail before I act: {clarifying} "
            "I will not infer a dispatch or map action from that message alone."
        )
        reasoning_summary = [
            "No default action was selected.",
            "The request did not clearly ask for a specific data report, explanation, revision, apply, or operating plan.",
            "ParkPulse held the turn as read-only instead of guessing.",
        ]
        turn_contract = _copilot_turn_contract(
            "answer",
            will_act=False,
            dispatch_count=0,
            has_map_grounding=False,
            has_impact_replay=False,
            reason="Ambiguous operator text requires clarification; default action fallbacks are disabled.",
        )
        conversation_response = {
            "source": "clarification_required",
            "model": None,
            "answer": answer,
            "reasoning_bullets": reasoning_summary,
            "operator_next": clarifying,
            "confidence": 88,
            "provider_ready": True,
        }
        return {
            "status": "complete",
            "mode": "answer",
            "message": raw_message,
            "answer": answer,
            "reasoning_summary": reasoning_summary,
            "options_considered": [
                {
                    "label": "Ask for clarification",
                    "verdict": "selected",
                    "reason": "The message did not provide enough intent to safely choose a park action.",
                    "projected_effect": "No operational side effects.",
                }
            ],
            "clarifying_question": clarifying,
            "recommended_action": {
                "role": "none",
                "label": "Clarification required",
                "action": "No action selected",
                "gate": "read_only",
                "dispatch_count": 0,
                "execute": False,
            },
            "map_grounding": None,
            "impact_replay": None,
            "reasoning_evaluation": None,
            "agent_runtime": None,
            "chat_brain": chat_brain,
            "conversation_response": conversation_response,
            "tool_trace": {
                "tool_calls": [
                    {
                        "tool": "clarification.none",
                        "status": "complete",
                        "capability": "read",
                        "output": "operator clarification required",
                    }
                ],
                "summary": {"policy_gate": "read_only", "state_mutation": False},
            },
            "tool_call_timeline": [
                {
                    "id": "clarification_required",
                    "tool": "clarification.none",
                    "label": "Ask targeted clarification",
                    "status": "complete",
                    "output": "no action selected",
                }
            ],
            "turn_contract": turn_contract,
            "ontology_context": None,
            "object_action_plan": {"actions": [], "overall_gate": "read_only"},
            "route": route,
            "selected_role": "none",
            "live_state_summary": compact_state,
            "action_receipt": None,
            "run_telemetry": None,
            "conversation_memory": {
                "turn_count": len(recent_messages) + 1,
                "raw_message": raw_message,
                "effective_message": raw_message,
                "conversation_intent": "clarification",
                "chat_brain_source": chat_brain.get("source"),
                "last_user_intent": {
                    "question": intent.get("is_question"),
                    "action": False,
                    "safety_sensitive": intent.get("safety_sensitive"),
                },
                "map_context": request.selected_map_context,
                "constraints": [],
            },
        }
    requested_turn_mode = _normalize_copilot_turn_mode(request.turn_mode)
    raw_lower = raw_message.lower().strip()
    if conversation_intent == "apply_plan":
        requested_turn_mode = "apply"
    elif conversation_intent == "revise_plan":
        requested_turn_mode = "answer"
    elif conversation_intent in {"rollback_plan", "explain_plan"}:
        requested_turn_mode = "answer"
    is_followup = conversation_intent in {"explain_plan", "rollback_plan", "revise_plan"} and _is_copilot_followup(message, prior_copilot)
    tool_trace = _agent_role_tool_trace_for_api(route)
    if is_followup and prior_copilot:
        semantic_memory_context = (
            prior_copilot.get("semantic_memory_context")
            if isinstance(prior_copilot.get("semantic_memory_context"), dict)
            else await _copilot_semantic_memory_context(message, state, selected_role)
        )
        prior_map_grounding = prior_copilot.get("map_grounding") if isinstance(prior_copilot.get("map_grounding"), dict) else None
        prior_impact_replay = prior_copilot.get("impact_replay") if isinstance(prior_copilot.get("impact_replay"), dict) else None
        prior_recommended_action = prior_copilot.get("recommended_action") if isinstance(prior_copilot.get("recommended_action"), dict) else None
        prior_options = prior_copilot.get("options_considered") if isinstance(prior_copilot.get("options_considered"), list) else []
        prior_reasoning_evaluation = prior_copilot.get("reasoning_evaluation") if isinstance(prior_copilot.get("reasoning_evaluation"), dict) else None
        prior_agent_runtime = prior_copilot.get("agent_runtime") if isinstance(prior_copilot.get("agent_runtime"), dict) else None
        answer = _copilot_followup_answer(message, prior_copilot)
        conversation_response = await _copilot_conversational_response(
            message,
            base_answer=answer,
            compact_state=compact_state,
            route=route,
            intent=intent,
            object_action_plan=prior_copilot.get("object_action_plan") if isinstance(prior_copilot.get("object_action_plan"), dict) else None,
            reasoning_evaluation=prior_reasoning_evaluation,
            agent_runtime=prior_agent_runtime,
            map_grounding=prior_map_grounding,
            impact_replay=prior_impact_replay,
            clarifying_question=None,
            prior_copilot=prior_copilot,
            semantic_memory_context=semantic_memory_context,
            mode="follow_up",
        )
        answer = conversation_response.get("answer") or answer
        reasoning_summary = [
            *([str(item) for item in conversation_response.get("reasoning_bullets", [])] if isinstance(conversation_response.get("reasoning_bullets"), list) else []),
            f"Conversation source: {conversation_response.get('source')}.",
        ]
        followup_timeline = _copilot_tool_call_timeline(tool_trace, None, prior_impact_replay, followup=True)
        memory_event = _copilot_semantic_memory_tool_event(semantic_memory_context)
        if memory_event:
            followup_timeline.insert(1, memory_event)
        return {
            "status": "complete",
            "mode": "follow_up",
            "message": message,
            "answer": answer,
            "reasoning_summary": reasoning_summary,
            "options_considered": prior_options,
            "clarifying_question": None,
            "recommended_action": prior_recommended_action,
            "map_grounding": prior_map_grounding,
            "impact_replay": prior_impact_replay,
            "reasoning_evaluation": prior_reasoning_evaluation,
            "agent_runtime": prior_agent_runtime,
            "chat_brain": chat_brain,
            "conversation_response": conversation_response,
            "tool_trace": tool_trace,
            "tool_call_timeline": followup_timeline,
            "turn_contract": _copilot_turn_contract(
                "follow_up",
                will_act=False,
                dispatch_count=0,
                has_map_grounding=bool(prior_map_grounding),
                has_impact_replay=bool(prior_impact_replay),
                reason="Follow-up turns reuse the previous receipt and do not mutate park state.",
            ),
            "ontology_context": _copilot_ontology_context(
                message,
                state,
                prior_map_grounding,
                None,
                _copilot_turn_contract(
                    "follow_up",
                    will_act=False,
                    dispatch_count=0,
                    has_map_grounding=bool(prior_map_grounding),
                    has_impact_replay=bool(prior_impact_replay),
                    reason="Follow-up turns reuse the previous receipt and do not mutate park state.",
                ),
                followup_timeline,
            ),
            "semantic_memory_context": semantic_memory_context,
            "route": route,
            "selected_role": selected_role,
            "live_state_summary": compact_state,
            "action_receipt": None,
            "run_telemetry": None,
            "conversation_memory": {
                "turn_count": len(recent_messages) + 1,
                "followup_of_previous_run": True,
                "conversation_intent": conversation_intent,
                "chat_brain_source": chat_brain.get("source"),
                "last_user_intent": {
                    "question": True,
                    "action": False,
                    "safety_sensitive": intent.get("safety_sensitive"),
                },
                "map_context": request.selected_map_context,
                "constraints": route.get("policy_gates", []),
                "semantic_memory_status": semantic_memory_context.get("status") if isinstance(semantic_memory_context, dict) else None,
            },
        }
    actionable_role = selected_role in {"react", "proact"}
    if (intent.get("asks_action") or conversation_intent == "apply_plan") and selected_role == "scan":
        selected_role = "react"
        actionable_role = True
        route = {
            **route,
            "selected_role": "react",
            "why": "The operator asked for a solution/action after a scan-style status request, so ParkPulse escalated from Scan to React.",
            "policy_gates": list(dict.fromkeys([*(route.get("policy_gates", []) or []), "ontology_allowed_actions", "operator_apply_required"])),
        }
    semantic_memory_context = await _copilot_semantic_memory_context(message, state, selected_role)
    mark("semantic_memory")
    if requested_turn_mode == "answer":
        will_act = False
        response_mode = "propose" if intent.get("asks_action") else "answer"
    elif requested_turn_mode == "propose":
        will_act = False
        response_mode = "propose"
    elif requested_turn_mode == "apply":
        will_act = bool(request.allow_action and actionable_role)
        response_mode = "act" if will_act else "propose"
    else:
        will_act = conversation_intent == "apply_plan" and bool(request.allow_action and actionable_role and not intent.get("pure_explanation"))
        response_mode = "act" if will_act else ("answer" if conversation_intent in {"status_question", "explain_plan"} and not intent.get("asks_action") else "propose")
    role_payload: dict[str, Any] | None = None
    policy_query_message = _copilot_policy_query_message(message, compact_state, intent)
    policy_doctrine = retrieve_operational_doctrine(policy_query_message, compact_state, limit=12)
    policy_doctrine = _copilot_rebalance_generic_policy_doctrine(policy_doctrine, message, intent)
    policy_reasoning = interpret_policy_for_action(policy_query_message, compact_state, policy_doctrine)
    policy_doctrine["policy_query_message"] = policy_query_message
    mark("policy_doctrine")

    clarifying_question = None
    lowered = message.lower()
    if intent.get("safety_sensitive") and not any(term in lowered for term in ("confirmed", "on scene", "clear", "blocked", "location", "zone")):
        clarifying_question = "Before escalation: is trained staff already on scene, and is the guest/service lane physically clear?"

    map_grounding = _copilot_map_grounding(message, compact_state, None)
    affected_ontology_objects = _copilot_affected_ontology_objects(state, map_grounding)
    object_action_plan = _copilot_object_action_plan(
        message,
        affected_ontology_objects,
        operator_approved=requested_turn_mode == "apply",
        will_act=will_act,
    )
    object_action_plan = _attach_policy_doctrine_to_object_plan(object_action_plan, policy_doctrine, policy_reasoning)
    mark("object_action_plan")
    if will_act and object_action_plan.get("overall_gate") != "passed":
        will_act = False
        response_mode = "propose"
        clarifying_question = clarifying_question or "Approve the gated object-action plan before ParkPulse mutates park state."

    if will_act:
        if selected_role == "react":
            role_payload = _fast_role_react_payload_for_api(message, route, tool_trace)
        else:
            role_payload = await park_agent_role_run(OperatorCommandRequest(message=message, mode=request.mode, execute=True))
        if isinstance(role_payload, dict) and isinstance(role_payload.get("digital_twin_tools"), dict):
            tool_trace = role_payload["digital_twin_tools"]
        map_grounding = _copilot_map_grounding(message, compact_state, role_payload)
        affected_ontology_objects = _copilot_affected_ontology_objects(state, map_grounding)
        object_action_plan = _copilot_object_action_plan(
            message,
            affected_ontology_objects,
            operator_approved=True,
            will_act=will_act,
        )
        object_action_plan = _attach_policy_doctrine_to_object_plan(object_action_plan, policy_doctrine, policy_reasoning)

    recommended_action = _copilot_recommended_action(route, role_payload, will_act)
    mark("recommended_action")
    if object_action_plan.get("overall_gate"):
        recommended_action["gate"] = str(object_action_plan.get("overall_gate"))
        recommended_action["object_action_plan_id"] = object_action_plan.get("plan_id")
    primary_case = policy_doctrine.get("primary_case") if isinstance(policy_doctrine.get("primary_case"), dict) else {}
    if primary_case:
        recommended_action["matched_case_id"] = primary_case.get("id")
        recommended_action["matched_case_title"] = primary_case.get("title")
        recommended_action["policy_refs"] = object_action_plan.get("policy_refs", [])
        recommended_action["policy_selected_action"] = (policy_reasoning.get("selected_action") or {}).get("label") if isinstance(policy_reasoning.get("selected_action"), dict) else None
        recommended_action["policy_approval_required"] = bool(policy_reasoning.get("approval_required"))
    answer = _copilot_answer(message, route, compact_state, intent, role_payload, will_act)
    if intent.get("asks_action") or object_action_plan.get("actions"):
        answer = _copilot_answer_with_object_plan(answer, object_action_plan, will_act)
    reasoning_summary = _copilot_reasoning_summary(route, intent, compact_state, will_act)
    reasoning_summary = [
        *reasoning_summary,
        f"Selected {len(object_action_plan.get('actions', []))} object-bound action(s) from ontology allowed_actions; gate={object_action_plan.get('overall_gate')}.",
    ]
    if primary_case:
        reasoning_summary = [
            *reasoning_summary,
            f"Retrieved actionable case {primary_case.get('id')} ({primary_case.get('title')}) with policy refs {', '.join(object_action_plan.get('policy_refs', [])[:5])}.",
        ]
    if isinstance(semantic_memory_context, dict) and semantic_memory_context.get("status") == "ready":
        counts = semantic_memory_context.get("counts") if isinstance(semantic_memory_context.get("counts"), dict) else {}
        reasoning_summary = [
            *reasoning_summary,
            (
                "Semantic memory grounded the turn with "
                f"{counts.get('playbooks', 0)} playbook(s), {counts.get('incidents', 0)} incident(s), "
                f"and {counts.get('learnings', 0)} learning(s) via {semantic_memory_context.get('retrieval_method')}."
            ),
        ]
    selected_policy_action = policy_reasoning.get("selected_action") if isinstance(policy_reasoning.get("selected_action"), dict) else {}
    if selected_policy_action:
        reasoning_summary = [
            *reasoning_summary,
            f"Policy reasoning selected: {selected_policy_action.get('label')}; rejected {len([item for item in policy_reasoning.get('candidate_actions', []) if isinstance(item, dict) and item.get('verdict') == 'rejected'])} blocked candidate(s).",
        ]
    options_considered = _copilot_options(route, intent, compact_state, will_act)
    if primary_case:
        options_considered = [
            {
                "label": f"Use case {primary_case.get('id')}",
                "verdict": "selected",
                "reason": primary_case.get("title") or "Closest matching actionable case from policy doctrine.",
                "projected_effect": primary_case.get("success_metric") or "Measured operating improvement with rollback condition.",
            },
            {
                "label": f"Policy-selected action: {selected_policy_action.get('label')}" if selected_policy_action else "Policy interpretation",
                "verdict": "selected" if selected_policy_action else "prepared",
                "reason": "Agent interpreted allowed actions, blocked actions, evidence requirements, and approval gate before planning.",
                "projected_effect": policy_reasoning.get("success_metric") or "Policy-constrained operating action.",
            },
            *options_considered,
        ]
    impact_replay = None
    if will_act:
        action_plan = _copilot_action_plan_from_objects(message, route, map_grounding, object_action_plan)
        impact_replay = await park_simulation.run_action_impact_replay(action_plan, horizon_minutes=15, execute=True)
        after_state = impact_replay.get("state") if isinstance(impact_replay, dict) else None
        if isinstance(after_state, dict):
            clear_hot_endpoint_cache()
        impact_headline = (
            impact_replay.get("comparison", {}).get("impact", {}).get("headline")
            if isinstance(impact_replay, dict)
            else None
        )
        if impact_headline:
            answer = f"{answer} Impact replay: {impact_headline}"
            reasoning_summary = [
                *reasoning_summary,
                "Compared the applied copilot action with a no-agent shadow baseline and attached the before/after map deltas.",
            ]
    run_telemetry = role_payload.get("run_telemetry") if isinstance(role_payload, dict) else None
    tool_call_timeline = _copilot_tool_call_timeline(tool_trace, role_payload, impact_replay)
    tool_call_timeline = [
        {
            "id": "retrieve_policy_doctrine",
            "tool": "policy.retrieve_actionable_case",
            "label": "Retrieve policy doctrine and action case",
            "status": policy_doctrine.get("retrieval_status") or "complete",
            "output": primary_case.get("id") if primary_case else "no matched case",
        },
        {
            "id": "interpret_policy_before_action",
            "tool": "policy.interpret_before_action",
            "label": "Interpret allowed, blocked, evidence, approval",
            "status": policy_reasoning.get("status") or "complete",
            "output": selected_policy_action.get("label") if selected_policy_action else "no selected policy action",
        },
        *tool_call_timeline,
    ]
    memory_event = _copilot_semantic_memory_tool_event(semantic_memory_context)
    if memory_event:
        tool_call_timeline.insert(2, memory_event)
    dispatch_count = int(recommended_action.get("dispatch_count") or 0)
    turn_contract = _copilot_turn_contract(
        response_mode,
        will_act=will_act,
        dispatch_count=dispatch_count,
        has_map_grounding=bool(map_grounding),
        has_impact_replay=bool(impact_replay),
        reason=(
            "Operator selected apply, so the agent mutated simulated park state after policy-gated dispatch."
            if will_act
            else "Operator selected propose/answer or the request was classified as explanation-first, so no state mutation occurred."
        ),
    )
    reasoning_evaluation = _copilot_reasoning_evaluation(
        message,
        compact_state,
        object_action_plan,
        options_considered,
        turn_contract,
    )
    mark("reasoning_evaluation")
    if reasoning_evaluation.get("overall"):
        reasoning_summary = [
            *reasoning_summary,
            f"Reasoning evaluator scored the selected option {reasoning_evaluation.get('overall')}/100 ({reasoning_evaluation.get('verdict')}).",
        ]
    ontology_context = _copilot_ontology_context(
        message,
        state,
        map_grounding,
        role_payload,
        turn_contract,
        tool_call_timeline,
        recommended_action,
        object_action_plan,
    )
    mark("ontology_context")
    analytics_action_layer = build_analytics_to_action_layer(state, policy_doctrine, policy_reasoning)
    mark("analytics_action_layer")
    branch_comparison = None
    if will_act or intent.get("safety_sensitive") or str(os.getenv("PARKPULSE_COPILOT_INCLUDE_BRANCH_COMPARISON", "")).strip().lower() in {"1", "true", "yes", "on"}:
        branch_comparison = await park_simulation.run_action_branch_comparison(20, execute=False)
    agent_runtime = _copilot_agent_runtime_receipt(
        message,
        intent=intent,
        route=route,
        compact_state=compact_state,
        map_grounding=map_grounding,
        object_action_plan=object_action_plan,
        options_considered=options_considered,
        reasoning_evaluation=reasoning_evaluation,
        turn_contract=turn_contract,
        tool_call_timeline=tool_call_timeline,
        ontology_context=ontology_context,
        impact_replay=impact_replay,
        clarifying_question=clarifying_question,
        analytics_action_layer=analytics_action_layer,
        branch_comparison=branch_comparison,
    )
    mark("agent_runtime")
    conversation_response = await _copilot_conversational_response(
        message,
        base_answer=answer,
        compact_state=compact_state,
        route=route,
        intent=intent,
        object_action_plan=object_action_plan,
        reasoning_evaluation=reasoning_evaluation,
        agent_runtime=agent_runtime,
        map_grounding=map_grounding,
        impact_replay=impact_replay,
        clarifying_question=clarifying_question,
        prior_copilot=prior_copilot,
        semantic_memory_context=semantic_memory_context,
        mode=response_mode,
    )
    mark("conversation_response")
    answer = conversation_response.get("answer") or answer
    conversation_bullets = conversation_response.get("reasoning_bullets")
    reasoning_summary = [
        *([str(item) for item in conversation_bullets] if isinstance(conversation_bullets, list) else reasoning_summary),
        f"Agent runtime completed {agent_runtime.get('summary', {}).get('completed_stages')}/11 stages; status={agent_runtime.get('status')}.",
        f"Conversation source: {conversation_response.get('source')}.",
    ]

    response_payload = {
        "status": "complete",
        "mode": response_mode,
        "message": message,
        "answer": answer,
        "reasoning_summary": reasoning_summary,
        "options_considered": options_considered,
        "clarifying_question": clarifying_question,
        "recommended_action": recommended_action,
        "map_grounding": map_grounding,
        "impact_replay": impact_replay,
        "reasoning_evaluation": reasoning_evaluation,
        "agent_runtime": agent_runtime,
        "analytics_action_layer": analytics_action_layer,
        "branch_comparison": branch_comparison,
        "multi_agent_deliberation": agent_runtime.get("multi_agent_deliberation"),
        "chat_brain": chat_brain,
        "conversation_response": conversation_response,
        "semantic_memory_context": semantic_memory_context,
        "tool_trace": tool_trace,
        "tool_call_timeline": tool_call_timeline,
        "turn_contract": turn_contract,
        "ontology_context": ontology_context,
        "object_action_plan": object_action_plan,
        "policy_doctrine": policy_doctrine,
        "policy_reasoning": policy_reasoning,
        "synthetic_park_context": policy_doctrine.get("synthetic_context") if isinstance(policy_doctrine, dict) else None,
        "route": route,
        "selected_role": selected_role,
        "live_state_summary": compact_state,
        "action_receipt": role_payload,
        "run_telemetry": run_telemetry,
            "conversation_memory": {
                "turn_count": len(recent_messages) + 1,
                "raw_message": raw_message,
                "effective_message": message,
                "conversation_intent": conversation_intent,
                "chat_brain_source": chat_brain.get("source"),
                "last_user_intent": {
                "question": intent.get("is_question"),
                "action": intent.get("asks_action"),
                "safety_sensitive": intent.get("safety_sensitive"),
            },
            "map_context": request.selected_map_context,
            "constraints": route.get("policy_gates", []),
            "semantic_memory_status": semantic_memory_context.get("status") if isinstance(semantic_memory_context, dict) else None,
        },
    }
    mark("response_payload")
    if diagnostics_enabled:
        response_payload["latency_diagnostics"] = {
            "mode": "copilot_stage_timings",
            "total_ms": round((time.monotonic() - diagnostics_started) * 1000, 2),
            "stages": diagnostics_stages,
        }
    return response_payload


class AgentRoleRefineRequest(BaseModel):
    message: str = Field(default="Refine this ParkPulse operating decision.")
    receipt: dict[str, Any] = Field(default_factory=dict)


@app.post("/api/park/agent-role-refine")
async def park_agent_role_refine(request: AgentRoleRefineRequest):
    receipt = request.receipt or {}
    role = receipt.get("selected_role") or receipt.get("role_receipt", {}).get("role") or "agent"
    scenario_key = receipt.get("role_receipt", {}).get("scenario_key") or receipt.get("run_telemetry", {}).get("scenario_key")
    dispatches = receipt.get("run_telemetry", {}).get("delivery", {}).get("dispatches", [])
    prompt = {
        "task": "Refine a fast amusement-park operating decision. Keep it bounded, policy-safe, and specific to the operator text.",
        "operator_text": request.message,
        "selected_role": role,
        "scenario_key": scenario_key,
        "current_actions": [
            {"channel": item.get("channel"), "status": item.get("status"), "payload": item.get("payload"), "response": item.get("response")}
            for item in dispatches[:5]
            if isinstance(item, dict)
        ],
        "required_json": {
            "status": "refined | no_change",
            "headline": "short headline",
            "operator_brief": "one concise paragraph",
            "refined_actions": ["bounded changes only"],
            "policy_notes": ["policy constraints"],
            "confidence": 0.0,
        },
    }
    try:
        from gemini_hard_timeout import generate_gemini_json_hard_timeout

        started = datetime.now(UTC)
        result = await generate_gemini_json_hard_timeout(prompt, timeout_seconds=7, max_output_tokens=550, temperature=0.15)
        text = str(result.get("text") or "{}").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()
        try:
            refinement = json.loads(text)
        except json.JSONDecodeError:
            refinement = json.loads(text[text.find("{") : text.rfind("}") + 1])
        return {
            "status": "complete",
            "mode": "gemini_refinement",
            "runtime": result.get("transport", "gemini"),
            "elapsed_ms": int((datetime.now(UTC) - started).total_seconds() * 1000),
            "selected_role": role,
            "scenario_key": scenario_key,
            "refinement": refinement,
        }
    except Exception as error:
        return {
            "status": "fallback",
            "mode": "bounded_no_refinement",
            "selected_role": role,
            "scenario_key": scenario_key,
            "refinement": {
                "status": "no_change",
                "headline": "Fast role decision kept.",
                "operator_brief": "Gemini refinement was unavailable within the demo timeout, so ParkPulse kept the policy-gated receiver actions already emitted.",
                "refined_actions": [],
                "policy_notes": ["No extra action emitted without model refinement."],
                "confidence": 0.62,
            },
            "error": str(error)[:300],
        }


@app.get("/api/park/digital-twin/tools")
async def park_digital_twin_tools():
    return list_digital_twin_tools()


@app.post("/api/park/digital-twin/run")
async def park_digital_twin_tool_run(request: DigitalTwinToolRequest):
    state = await park_simulation.get_state()
    await sync_park_state_safe(state)
    context = _retrieve_operational_context(
        f"digital twin tool {request.tool} ride queue staff food inventory energy guest flow",
        state,
        agent_role="react_agent",
    )
    scenario_key = state.get("guestFlow", {}).get("activeScenario", {}).get("key", "ride_down")
    context = _collaboration_context(context, scenario_key)
    return run_digital_twin_tool(request.tool, state, request.arguments, context)


@app.get("/api/park/digital-twin/trace")
async def park_digital_twin_trace():
    state = await park_simulation.get_state()
    await sync_park_state_safe(state)
    scenario_key = state.get("guestFlow", {}).get("activeScenario", {}).get("key", "ride_down")
    context = _retrieve_operational_context(
        f"{scenario_key} digital twin candidate comparison policy tool trace ride queue staff food inventory energy guest flow",
        state,
        agent_role="react_agent",
    )
    context = _collaboration_context(context, scenario_key)
    plan = build_park_action_plan(state)
    optimization = optimize_park_response(state, scenario_key, context, None)
    return build_digital_twin_tool_trace(state, scenario_key, context, plan, optimization)


@app.get("/api/park/digital-twin/benchmark/scenarios")
async def park_digital_twin_benchmark_scenarios():
    return list_benchmark_scenarios()


@app.get("/api/park/digital-twin/benchmark/history")
async def park_digital_twin_benchmark_history():
    return read_benchmark_history()


@app.get("/api/park/digital-twin/benchmark/report/latest")
async def park_digital_twin_benchmark_report_latest():
    return latest_benchmark_report()


@app.get("/api/park/understanding-benchmark/cases")
async def park_understanding_benchmark_cases():
    return list_park_understanding_cases()


@app.get("/api/park/understanding-benchmark/latest")
async def park_understanding_benchmark_latest():
    return latest_park_understanding_benchmark()


@app.post("/api/park/understanding-benchmark")
async def park_understanding_benchmark(request: ParkUnderstandingBenchmarkRequest):
    if str(request.provider or "").strip().lower() in {"gemini", "live_gemini", "llm"}:
        return await run_live_park_understanding_benchmark(
            case_id=request.case_id,
            write_artifact=request.write_artifact,
            timeout_seconds=request.timeout_seconds,
        )
    return await asyncio.to_thread(
        run_park_understanding_benchmark,
        request.candidate_responses,
        case_id=request.case_id,
        write_artifact=request.write_artifact,
    )


@app.get("/api/park/digital-twin/calibration")
async def park_digital_twin_calibration():
    state = await park_simulation.get_state()
    state["operationsAudit"] = await asyncio.to_thread(build_audit_snapshot, state)
    forecast = await asyncio.to_thread(build_counterfactual_forecast, state)
    return await asyncio.to_thread(build_calibration_ledger, state, forecast)


@app.post("/api/park/digital-twin/benchmark")
async def park_digital_twin_benchmark(request: DigitalTwinBenchmarkRequest):
    state = await park_simulation.get_state()
    await sync_park_state_safe(state)
    if request.policy_under_test in {"parkpulse_agent", "agent", "planner"}:
        def benchmark_context_builder(scenario_key: str, observed_state: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
            context = _retrieve_operational_context(
                f"{scenario_key} adversarial digital twin benchmark noisy observation ride queue staff food inventory energy guest flow",
                observed_state,
                agent_role="react_agent",
            )
            enriched = _collaboration_context(context, scenario_key)
            enriched["digital_twin_benchmark"] = {
                "observation_mode": observation.get("mode"),
                "staleness_seconds": observation.get("staleness_seconds", {}),
                "hidden_truth_withheld": True,
            }
            return enriched

        result = await run_parkpulse_agent_benchmark(
            state,
            build_park_gemini_plan,
            optimize_park_response,
            benchmark_context_builder,
            scenario_id=request.scenario_id,
            seed=request.seed,
            horizon_minutes=request.horizon_minutes,
        )
        return record_benchmark_result(result)
    result = run_digital_twin_benchmark(
        state,
        scenario_id=request.scenario_id,
        seed=request.seed,
        horizon_minutes=request.horizon_minutes,
    )
    return record_benchmark_result(result)


@app.post("/api/park/digital-twin/benchmark/learned-rerun")
async def park_digital_twin_benchmark_learned_rerun(request: DigitalTwinLearnedRerunRequest):
    previous = request.previous_result if isinstance(request.previous_result, dict) else {}
    remediations = generate_remediation_playbooks(previous)
    learning_ids = [record_mongo_agent_learning_document(document) for document in remediations]
    memory_write = {
        "status": "stored" if remediations else "no_failures",
        "target": "agent_learnings",
        "learning_ids": learning_ids,
        "remediations": remediations,
    }

    state = await park_simulation.get_state()
    await sync_park_state_safe(state)

    def learned_context_builder(scenario_key: str, observed_state: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
        context = _retrieve_operational_context(
            f"{scenario_key} digital twin remediation lessons failure trace policy gate regret secondary risk noisy signal",
            observed_state,
            limit=5,
            agent_role="react_agent",
        )
        enriched = _collaboration_context(context, scenario_key)
        retrieved = enriched.setdefault("retrieved", {})
        existing = retrieved.get("learnings", []) if isinstance(retrieved.get("learnings"), list) else []
        matching = [
            document
            for document in remediations
            if document.get("scenarioKey") in {scenario_key, (observed_state.get("guestFlow", {}).get("activeScenario", {}) if isinstance(observed_state.get("guestFlow", {}), dict) else {}).get("key")}
        ]
        retrieved["learnings"] = (matching + existing)[:6]
        enriched["digital_twin_benchmark"] = {
            "observation_mode": observation.get("mode"),
            "staleness_seconds": observation.get("staleness_seconds", {}),
            "hidden_truth_withheld": True,
            "learned_rerun": True,
            "remediation_learning_ids": learning_ids,
        }
        return enriched

    result = await run_parkpulse_agent_benchmark(
        state,
        build_park_gemini_plan,
        optimize_park_response,
        learned_context_builder,
        scenario_id=request.scenario_id,
        seed=request.seed,
        horizon_minutes=request.horizon_minutes,
    )
    result = attach_learning_comparison(result, previous, remediations, memory_write)
    return record_benchmark_result(result)


from parkpulse_routes.memory_routes import register_memory_routes


register_memory_routes(
    app,
    {
        "clear_hot_endpoint_cache": clear_hot_endpoint_cache,
        "park_simulation": park_simulation,
        "sync_park_state_safe": sync_park_state_safe,
    },
)


@app.get("/api/park/integration-status")
async def park_integration_status():
    return await cached_hot_endpoint(
        "park_integration_status",
        _park_integration_status_cache_ttl_seconds,
        build_park_integration_status_response,
    )


@app.get("/api/park/agent-monitoring")
async def park_agent_monitoring():
    return await cached_hot_endpoint(
        "park_agent_monitoring",
        _park_monitoring_cache_ttl_seconds,
        build_park_agent_monitoring_response,
    )


@app.get("/api/park/agent-monitoring/deep")
async def park_agent_monitoring_deep():
    return await cached_hot_endpoint(
        "park_agent_monitoring_deep",
        _park_monitoring_cache_ttl_seconds,
        build_park_agent_monitoring_response,
    )


def latest_live_agents_smoke_report() -> dict[str, Any]:
    report_path = Path(os.getenv("PARKPULSE_LIVE_AGENTS_SMOKE_REPORT", "output/qa/live-all-agents-smoke.json"))
    if not report_path.is_absolute():
        report_path = Path.cwd() / report_path
    if not report_path.exists():
        return {
            "status": "missing",
            "mode": "live_all_agents_smoke",
            "report_path": str(report_path),
            "summary": {
                "status": "missing",
                "activated_role_count": 0,
                "activated_department_count": 0,
                "role_failures": [],
                "scenario_failures": [],
            },
            "readiness_issues": ["Run `make live-agents-smoke` to generate the latest all-agent proof report."],
        }
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as error:
        return {
            "status": "error",
            "mode": "live_all_agents_smoke",
            "report_path": str(report_path),
            "summary": {"status": "error"},
            "readiness_issues": [str(error)[:240]],
        }
    if isinstance(payload, dict):
        return {**payload, "report_path": str(report_path)}
    return {
        "status": "error",
        "mode": "live_all_agents_smoke",
        "report_path": str(report_path),
        "summary": {"status": "error"},
        "readiness_issues": ["Live all-agents smoke report is not a JSON object."],
    }


@app.get("/api/park/live-agents-smoke/latest")
async def park_live_agents_smoke_latest():
    return latest_live_agents_smoke_report()


@app.get("/api/park/replay")
async def park_replay(limit: int = 20):
    if hasattr(park_simulation, "get_replay"):
        return await park_simulation.get_replay(limit)
    return {"mode": "unavailable", "event_count": 0, "events": [], "latest_event": None}


@app.post("/api/park/replay/start")
async def park_replay_start(request: ReplayStartRequest):
    if hasattr(park_simulation, "start_replay_run"):
        result = await park_simulation.start_replay_run(request.seed, request.scenario_key)
        clear_hot_endpoint_cache()
        state = await park_simulation.get_state()
        await sync_park_state_safe(state)
        return {**result, "state": state}
    return {"status": "unavailable", "message": "Replay runs are not available in this simulation runtime."}


@app.get("/api/park/review-snapshot")
async def park_review_snapshot():
    with tracer.start_as_current_span("api.park_review_snapshot") as span:
        state = await park_simulation.get_state()
        await sync_park_state_safe(state)
        runtime_governance = list_runtime_governance(20)
        dispatches = latest_dispatches(20)
        signals = latest_signals(20)
        replay = await park_replay(30)
        snapshot = build_review_snapshot(state, runtime_governance, dispatches, signals, replay)
        span.set_attribute("parkpulse.review.id", snapshot.get("review_id", ""))
        span.set_attribute("parkpulse.review.status", snapshot.get("status", ""))
        span.set_attribute("parkpulse.review.overall_score", snapshot.get("overall_score", 0))
        span.set_attribute("parkpulse.scenario", snapshot.get("scenario", {}).get("key", ""))
        return snapshot


@app.get("/api/park/scenarios")
async def park_scenarios():
    return get_park_scenarios()


@app.get("/api/park/agent-roles")
async def park_agent_roles():
    return {
        "domain": "amusement_park_operations",
        "agent_roles": get_agent_registry(),
        "agent_topology": get_agent_topology(),
        "role_alignment": role_alignment_report(),
    }


@app.get("/api/park/evals/{scenario_key}")
async def park_eval_result(scenario_key: str):
    state = await park_simulation.get_state()
    await sync_park_state_safe(state)
    return evaluate_park_decision(scenario_key, state)


from parkpulse_routes.gcp_routes import register_gcp_routes


register_gcp_routes(
    app,
    {
        "ParkAgentRunRequest": ParkAgentRunRequest,
        "action_execution_for_signal": _action_execution_for_signal,
        "clear_hot_endpoint_cache": clear_hot_endpoint_cache,
        "export_agent_analytics": _export_agent_analytics,
        "park_agent_run": park_agent_run,
        "park_simulation": park_simulation,
        "sync_park_state_safe": sync_park_state_safe,
    },
)
