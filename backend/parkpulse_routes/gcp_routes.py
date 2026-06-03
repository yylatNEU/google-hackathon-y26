from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field


class EvalScenarioSweepRequest(BaseModel):
    scenario_keys: list[str] | None = Field(default=None)
    execute: bool = Field(default=False)
    timeout_seconds: float = Field(default=45.0, ge=5.0, le=180.0)


class GcpParkEventRequest(BaseModel):
    event_type: str = Field(default="parkpulse.manual.signal")
    payload: dict[str, Any] = Field(default_factory=dict)
    attributes: dict[str, str] = Field(default_factory=dict)


class GcpWorkflowRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


def _trace_eval_judge_payload() -> dict[str, Any]:
    from park_multi_agent import get_judge_trace_eval_contract

    contract = get_judge_trace_eval_contract()
    return {
        "agent_id": contract["owner_agent"],
        "department": contract["owner_department"],
        "department_agent": contract["owner_department_agent"],
        "owned_tools": contract["owned_tools"],
        "exclusive_tools": contract["exclusive_tools"],
        "routing_rule": contract["routing_rule"],
    }


def _gcp_trace_eval_status_for_route() -> dict[str, Any]:
    from gcp_trace_eval import get_gcp_trace_eval_status
    from park_multi_agent import get_judge_trace_eval_contract

    return {
        **get_gcp_trace_eval_status().public_dict(),
        "judge_agent": _trace_eval_judge_payload(),
        "judge_contract": get_judge_trace_eval_contract(),
    }


def _evaluator_loop_status_for_route() -> dict[str, Any]:
    from evaluator_loop import evaluator_loop_status

    return {
        **evaluator_loop_status(),
        "judge_agent": _trace_eval_judge_payload(),
    }


def register_gcp_routes(app: Any, deps: dict[str, Any]) -> None:
    router = APIRouter()

    @router.get("/api/gcp-gemini/status")
    async def gcp_gemini_status():
        from arize_config import get_arize_status
        from bigquery_analytics import bigquery_status, online_improvement_status
        from gemini_provider import get_gemini_agent_properties

        return {
            "agent": {
                "name": "ParkPulse AI",
                "role": "parkpulse_decision_bridge",
            },
            "gemini": get_gemini_agent_properties().public_dict(),
            "gcp_trace_eval": _gcp_trace_eval_status_for_route(),
            "online_improvement": online_improvement_status(),
            "bigquery": bigquery_status(),
            "arize": get_arize_status().public_dict(),
        }

    @router.get("/api/gcp/improvement-status")
    async def gcp_improvement_status():
        from bigquery_analytics import online_improvement_status

        return online_improvement_status()

    @router.get("/api/gcp/trace-eval-status")
    async def gcp_trace_eval_status():
        return _gcp_trace_eval_status_for_route()

    @router.get("/api/gcp/trace-export-verify")
    async def gcp_trace_export_verify():
        from gcp_trace_eval import verify_gcp_trace_export

        return verify_gcp_trace_export()

    @router.get("/api/gcp/evaluator-loop")
    async def gcp_evaluator_loop_status():
        return _evaluator_loop_status_for_route()

    @router.post("/api/gcp/evaluator-loop/verify")
    async def gcp_evaluator_loop_verify(scenario_key: str = "ride_down"):
        from evaluator_loop import run_vertex_hosted_evaluation

        result = await asyncio.to_thread(
            run_vertex_hosted_evaluation,
            {
                "scenario_key": scenario_key,
                "decision_id": "vertex-evaluator-connectivity-check",
                "outcome_id": None,
                "overall": 91,
                "scorecard_status": "passed",
                "response_score": 88,
                "response_status": "connectivity_check",
                "trace_id": None,
                "span_id": None,
                "trace_url": None,
                "dimension_scores": {"Groundedness": 92, "Safety": 96, "Actionability": 90},
                "dimension_explanations": {
                    "Groundedness": "Connectivity check payload using the ParkPulse eval contract.",
                    "Safety": "Policy gate is present and allowed.",
                    "Actionability": "Selected action has an operational receiver intent.",
                },
                "failure_reasons": [],
                "selected_action": {"label": "Reroute guests and notify staff"},
                "governance": {"gate_status": "checked", "allowed": True, "findings": []},
            },
        )
        return {
            "status": result.get("status", "unknown"),
            "scenario_key": scenario_key,
            "judge_agent": _trace_eval_judge_payload(),
            "hosted_eval": {
                "status": f"vertex_{result.get('status', 'unknown')}",
                "provider": result.get("provider"),
                "evaluator_id": result.get("evaluator_id"),
                "location": result.get("location"),
                "trigger": {"enabled": True, "status": result.get("status"), "reason": result.get("reason")},
                "vertex_result": result,
            },
        }

    @router.post("/api/gcp/evaluator-loop/scenario-sweep")
    async def gcp_evaluator_loop_scenario_sweep(request: EvalScenarioSweepRequest):
        from mongo_memory import get_latest_memory_documents_fast, record_scenario_eval_sweep_fast
        from scenario_eval_sweep import (
            DEFAULT_SWEEP_SCENARIOS,
            build_sweep_analytics_rows,
            latest_sweep_payload,
            run_vertex_eval_scenario_sweep,
        )

        scenario_keys = request.scenario_keys or list(DEFAULT_SWEEP_SCENARIOS)
        park_agent_run = deps["park_agent_run"]
        park_agent_run_request = deps["ParkAgentRunRequest"]

        async def run_scenario(scenario_key: str, execute: bool) -> dict[str, Any]:
            return await park_agent_run(park_agent_run_request(scenario_key=scenario_key, execute=execute))

        result = await run_vertex_eval_scenario_sweep(
            run_scenario,
            scenario_keys=scenario_keys,
            execute=request.execute,
            timeout_seconds=request.timeout_seconds,
        )
        sweep_document_id = record_scenario_eval_sweep_fast(result)
        analytics_export = deps["export_agent_analytics"](build_sweep_analytics_rows(result))
        result["persistence"] = {
            "mongo_eval_document_id": sweep_document_id,
            "analytics": analytics_export,
        }
        result["latest_payload"] = latest_sweep_payload(get_latest_memory_documents_fast("eval_results", 25))
        return result

    @router.get("/api/gcp/evaluator-loop/scenario-sweep/latest")
    async def gcp_evaluator_loop_scenario_sweep_latest():
        from mongo_memory import get_latest_memory_documents_fast
        from scenario_eval_sweep import latest_sweep_payload

        return latest_sweep_payload(get_latest_memory_documents_fast("eval_results", 25))

    @router.get("/api/gcp/operations/status")
    async def gcp_operations_status_endpoint():
        from gcp_operations import gcp_operations_status

        return gcp_operations_status()

    @router.get("/api/gcp/pseudo-firebase/status")
    async def gcp_pseudo_firebase_status():
        from gcp_operations import pseudo_firebase_status

        return pseudo_firebase_status()

    @router.get("/api/gcp/firestore/status")
    async def gcp_firestore_status():
        from gcp_operations import firestore_status

        return firestore_status()

    @router.get("/api/gcp/firestore/operations")
    async def gcp_firestore_operations(limit: int = 50, kind: str | None = None):
        from gcp_operations import firestore_status, latest_firestore_operations

        operations = latest_firestore_operations(limit=max(1, min(limit, 200)), kind=kind)
        status = firestore_status()
        return {
            "status": "ready" if status["ready"] else "mirror",
            "count": len(operations),
            "kind": kind,
            "operations": operations,
            "contract": status,
        }

    @router.get("/api/gcp/agent-builder/status")
    async def gcp_agent_builder_status():
        from gcp_operations import vertex_agent_builder_status

        return vertex_agent_builder_status()

    @router.get("/api/gcp/agent-builder/registry")
    async def gcp_agent_builder_registry():
        from gcp_operations import vertex_agent_builder_registry

        return vertex_agent_builder_registry()

    @router.get("/api/gcp/dataflow/status")
    async def gcp_dataflow_status():
        from gcp_operations import dataflow_status

        return dataflow_status()

    @router.get("/api/gcp/dataflow/contract")
    async def gcp_dataflow_contract():
        from gcp_operations import dataflow_stream_contract

        return dataflow_stream_contract()

    @router.get("/api/gcp/dataflow/events")
    async def gcp_dataflow_events(limit: int = 50, event_type: str | None = None):
        from gcp_operations import dataflow_status, latest_dataflow_events

        events = latest_dataflow_events(limit=max(1, min(limit, 200)), event_type=event_type)
        status = dataflow_status()
        return {
            "status": "ready" if status["ready"] else "mirror",
            "count": len(events),
            "event_type": event_type,
            "events": events,
            "contract": status,
        }

    @router.get("/api/gcp/pseudo-firebase/messages")
    async def gcp_pseudo_firebase_messages(limit: int = 50, topic: str | None = None):
        from gcp_operations import latest_pseudo_firebase_messages, pseudo_firebase_status

        messages = latest_pseudo_firebase_messages(limit=max(1, min(limit, 200)), topic=topic)
        return {
            "status": "ready" if pseudo_firebase_status()["ready"] else "disabled",
            "count": len(messages),
            "topic": topic,
            "messages": messages,
            "contract": {
                "provider": "pseudo_firebase",
                "guest_topic": os.getenv("PARKPULSE_FCM_GUEST_TOPIC", "parkpulse-guest-app"),
                "worker_topic": os.getenv("PARKPULSE_FCM_WORKER_TOPIC", "parkpulse-worker-device"),
            },
        }

    @router.post("/api/gcp/pubsub/park-event")
    async def gcp_pubsub_park_event(request: GcpParkEventRequest):
        from gcp_operations import publish_park_event

        return await asyncio.to_thread(
            publish_park_event,
            request.event_type,
            request.payload,
            request.attributes,
        )

    @router.post("/api/gcp/eventarc/park-signal")
    async def gcp_eventarc_park_signal(body: dict[str, Any]):
        from gcp_operations import decode_eventarc_pubsub_signal
        from park_signal_intake import classify_unstructured_signal

        decoded = decode_eventarc_pubsub_signal(body)
        event_type = str((decoded.get("event") or {}).get("eventType") or "")
        if event_type and event_type != "parkpulse.manual.signal":
            return {
                "status": "ignored",
                "reason": "Eventarc signal intake only handles external park signals.",
                "event_type": event_type,
                "gcp_eventarc": {
                    "status": "accepted",
                    "event": decoded.get("event", {}),
                    "endpoint": "/api/gcp/eventarc/park-signal",
                },
            }
        park_simulation = deps["park_simulation"]
        state = await park_simulation.get_state()
        await deps["sync_park_state_safe"](state)
        signal = classify_unstructured_signal(
            text=decoded["text"],
            source=decoded["source"],
            zone_id=decoded.get("zoneId"),
            reporter_role=decoded.get("reporterRole", "gcp_event"),
            park_state=state,
        )
        result = deps["action_execution_for_signal"](signal, state)
        deps["clear_hot_endpoint_cache"]()
        return {
            **result,
            "gcp_eventarc": {
                "status": "accepted",
                "event": decoded.get("event", {}),
                "endpoint": "/api/gcp/eventarc/park-signal",
            },
        }

    @router.post("/api/gcp/workflows/operator-approval")
    async def gcp_workflows_operator_approval(request: GcpWorkflowRequest):
        from gcp_operations import start_operator_workflow

        return await asyncio.to_thread(start_operator_workflow, request.payload)

    @router.get("/api/arize/status")
    async def arize_status():
        from arize_config import get_arize_status

        return get_arize_status().public_dict()

    app.include_router(router)
