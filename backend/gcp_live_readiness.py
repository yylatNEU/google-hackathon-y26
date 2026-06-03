from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable


ScenarioRunner = Callable[[str, bool], Awaitable[dict[str, Any]]]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _nested(value: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return current if current is not None else default


def _mode(*, live: bool = False, mocked: bool = False, skipped: bool = False) -> str:
    if live:
        return "live"
    if mocked:
        return "mocked"
    if skipped:
        return "skipped"
    return "skipped"


def _check(
    *,
    name: str,
    ready: bool,
    proof_mode: str,
    details: dict[str, Any] | None = None,
    readiness_issues: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "ready": ready,
        "proof_mode": proof_mode,
        "details": details or {},
        "readiness_issues": readiness_issues or [],
    }


def build_gcp_live_readiness() -> dict[str, Any]:
    from bigquery_analytics import bigquery_status
    from evaluator_loop import evaluator_loop_status
    from gcp_operations import gcp_operations_status
    from gcp_trace_eval import get_gcp_trace_eval_status
    from park_multi_agent import get_judge_trace_eval_contract

    trace_eval = get_gcp_trace_eval_status().public_dict()
    evaluator = evaluator_loop_status()
    operations = gcp_operations_status()
    bigquery = bigquery_status()
    judge_contract = get_judge_trace_eval_contract()

    trace = _as_dict(trace_eval.get("trace"))
    fcm = _as_dict(operations.get("fcm"))
    firestore = _as_dict(operations.get("firestore"))
    dataflow = _as_dict(operations.get("dataflow"))
    pubsub = _as_dict(operations.get("pubsub"))
    workflows = _as_dict(operations.get("workflows"))
    agent_builder = _as_dict(operations.get("agent_builder"))

    checks = {
        "cloud_trace_export": _check(
            name="Cloud Trace exporter",
            ready=bool(trace.get("export_ready")),
            proof_mode=_mode(live=bool(trace.get("export_ready")), skipped=not bool(trace.get("export_configured")), mocked=bool(trace.get("export_configured"))),
            details={
                "sink": trace.get("sink"),
                "export_configured": bool(trace.get("export_configured")),
                "trace_project": trace_eval.get("trace_project"),
                "startup_error": trace.get("startup_error"),
            },
            readiness_issues=[] if trace.get("export_ready") else [str(item) for item in trace_eval.get("readiness_issues", []) if "trace" in str(item).lower()],
        ),
        "vertex_eval_trigger": _check(
            name="Vertex Gen AI evaluation trigger",
            ready=bool(evaluator.get("provider") == "vertex_genai_evaluation" and evaluator.get("hosted_trigger_enabled")),
            proof_mode=_mode(live=bool(evaluator.get("provider") == "vertex_genai_evaluation" and evaluator.get("hosted_trigger_enabled")), skipped=evaluator.get("provider") != "vertex_genai_evaluation", mocked=bool(evaluator.get("hosted_configured"))),
            details={
                "provider": evaluator.get("provider"),
                "status": evaluator.get("status"),
                "evaluator_id": evaluator.get("evaluator_id"),
                "location": evaluator.get("location"),
                "transport": _nested(evaluator, "tooling", "vertex_eval_transport"),
                "trigger_enabled": bool(evaluator.get("hosted_trigger_enabled")),
            },
            readiness_issues=[str(item) for item in evaluator.get("readiness_issues", [])],
        ),
        "bigquery": _check(
            name="BigQuery analytics export",
            ready=bool(bigquery.get("ready") or bigquery.get("insert_ready")),
            proof_mode=_mode(live=bool(bigquery.get("ready") or bigquery.get("insert_ready")), skipped=not bool(bigquery.get("ready") or bigquery.get("insert_ready"))),
            details={
                "project": bigquery.get("project") or trace_eval.get("project"),
                "dataset": bigquery.get("dataset") or trace_eval.get("dataset"),
                "mode": bigquery.get("mode"),
                "primary_path": trace_eval.get("primary_path"),
            },
            readiness_issues=[str(item) for item in bigquery.get("readiness_issues", [])],
        ),
        "pubsub": _check(
            name="Pub/Sub park events",
            ready=bool(pubsub.get("ready")),
            proof_mode=_mode(live=bool(pubsub.get("ready")), skipped=not bool(pubsub.get("ready"))),
            details={"enabled": bool(pubsub.get("enabled")), "topic": pubsub.get("topic")},
            readiness_issues=[] if pubsub.get("ready") else ["Pub/Sub is not live; set ENABLE_PARKPULSE_PUBSUB, PARKPULSE_PUBSUB_TOPIC, and GOOGLE_CLOUD_PROJECT."],
        ),
        "firestore": _check(
            name="Firestore operations state",
            ready=bool(firestore.get("ready")),
            proof_mode=_mode(live=bool(firestore.get("ready")), mocked=bool(_nested(firestore, "mirror", "ready")), skipped=not bool(firestore.get("ready") or _nested(firestore, "mirror", "ready"))),
            details={
                "enabled": bool(firestore.get("enabled")),
                "project": firestore.get("project"),
                "mirror": firestore.get("mirror"),
            },
            readiness_issues=[] if firestore.get("ready") else ["Firestore is using local mirror or is disabled."],
        ),
        "fcm": _check(
            name="Firebase Cloud Messaging",
            ready=bool(fcm.get("ready") and fcm.get("mode") == "firebase_cloud_messaging"),
            proof_mode=_mode(live=bool(fcm.get("ready") and fcm.get("mode") == "firebase_cloud_messaging"), mocked=bool(_nested(fcm, "pseudo", "ready")), skipped=not bool(fcm.get("ready") or _nested(fcm, "pseudo", "ready"))),
            details={
                "mode": fcm.get("mode"),
                "guest_topic": fcm.get("guest_topic"),
                "worker_topic": fcm.get("worker_topic"),
                "pseudo": fcm.get("pseudo"),
            },
            readiness_issues=[] if fcm.get("ready") else ["FCM is disabled; pseudo Firebase may still capture proof locally."],
        ),
        "dataflow": _check(
            name="Dataflow telemetry stream",
            ready=bool(dataflow.get("ready")),
            proof_mode=_mode(live=bool(dataflow.get("ready")), mocked=bool(_nested(dataflow, "mirror", "ready")), skipped=not bool(dataflow.get("ready") or _nested(dataflow, "mirror", "ready"))),
            details={
                "enabled": bool(dataflow.get("enabled")),
                "job_name": dataflow.get("job_name"),
                "template": dataflow.get("template"),
                "mirror": dataflow.get("mirror"),
            },
            readiness_issues=[] if dataflow.get("ready") else ["Dataflow is using local mirror or is missing template/project configuration."],
        ),
        "workflows": _check(
            name="Workflows operator approval",
            ready=bool(workflows.get("ready")),
            proof_mode=_mode(live=bool(workflows.get("ready")), skipped=not bool(workflows.get("ready"))),
            details={
                "enabled": bool(workflows.get("enabled")),
                "workflow_id": workflows.get("workflow_id"),
                "location": workflows.get("location"),
            },
            readiness_issues=[] if workflows.get("ready") else ["Workflows is disabled or missing workflow/project configuration."],
        ),
        "vertex_agent_builder": _check(
            name="Vertex Agent Builder / Agent Engine",
            ready=bool(agent_builder.get("ready")),
            proof_mode=_mode(live=bool(agent_builder.get("ready")), mocked=agent_builder.get("runtime") == "local contract", skipped=not bool(agent_builder.get("ready") or agent_builder.get("runtime") == "local contract")),
            details={
                "enabled": bool(agent_builder.get("enabled")),
                "runtime": agent_builder.get("runtime"),
                "resource": agent_builder.get("resource"),
                "agent_count": agent_builder.get("agent_count"),
                "tool_count": agent_builder.get("tool_count"),
            },
            readiness_issues=[] if agent_builder.get("ready") else ["Agent Builder is represented by the local boundary contract unless a resource is configured."],
        ),
    }

    live_count = sum(1 for item in checks.values() if item["proof_mode"] == "live")
    mocked_count = sum(1 for item in checks.values() if item["proof_mode"] == "mocked")
    skipped_count = sum(1 for item in checks.values() if item["proof_mode"] == "skipped")
    live_blockers = [
        issue
        for item in checks.values()
        if item["proof_mode"] != "live"
        for issue in item.get("readiness_issues", [])
    ]
    required_live = ("cloud_trace_export", "vertex_eval_trigger", "bigquery")
    required_live_ready = all(checks[name]["proof_mode"] == "live" for name in required_live)

    return {
        "status": "live_ready" if required_live_ready else "wired_not_live",
        "checked_at": _now_iso(),
        "summary": {
            "live": live_count,
            "mocked": mocked_count,
            "skipped": skipped_count,
            "required_live_ready": required_live_ready,
            "required_live_checks": list(required_live),
        },
        "judge_agent": {
            "agent_id": judge_contract["owner_agent"],
            "department": judge_contract["owner_department"],
            "exclusive_tools": judge_contract["exclusive_tools"],
            "routing_rule": judge_contract["routing_rule"],
        },
        "checks": checks,
        "readiness_issues": live_blockers,
        "env_gates": {
            "ENABLE_GCP_CLOUD_TRACE_EXPORT": _env_bool("ENABLE_GCP_CLOUD_TRACE_EXPORT"),
            "ENABLE_VERTEX_GENAI_EVAL": _env_bool("ENABLE_VERTEX_GENAI_EVAL"),
            "PARKPULSE_ENABLE_HOSTED_EVAL_TRIGGER": _env_bool("PARKPULSE_ENABLE_HOSTED_EVAL_TRIGGER"),
            "ENABLE_BIGQUERY_ANALYTICS": _env_bool("ENABLE_BIGQUERY_ANALYTICS"),
            "ENABLE_PARKPULSE_PUBSUB": _env_bool("ENABLE_PARKPULSE_PUBSUB"),
            "ENABLE_PARKPULSE_FIRESTORE": _env_bool("ENABLE_PARKPULSE_FIRESTORE"),
            "ENABLE_PARKPULSE_FCM": _env_bool("ENABLE_PARKPULSE_FCM"),
            "ENABLE_PARKPULSE_DATAFLOW": _env_bool("ENABLE_PARKPULSE_DATAFLOW"),
        },
    }


def _extract_eval(run_result: dict[str, Any]) -> dict[str, Any]:
    eval_result = run_result.get("eval")
    return eval_result if isinstance(eval_result, dict) else {}


def _extract_analytics(run_result: dict[str, Any]) -> dict[str, Any]:
    analytics = run_result.get("analytics")
    return analytics if isinstance(analytics, dict) else {}


def _proof_from_eval(eval_result: dict[str, Any]) -> dict[str, Any]:
    trace = _as_dict(eval_result.get("gcp_trace_eval") or eval_result.get("arize_trace"))
    hosted_eval = _as_dict(eval_result.get("hosted_eval"))
    trigger = _as_dict(hosted_eval.get("trigger"))
    vertex_result = _as_dict(hosted_eval.get("vertex_result"))
    scorecard = _as_dict(eval_result.get("scorecard"))
    vertex_status = str(vertex_result.get("status") or "")
    trigger_status = str(trigger.get("status") or "")
    hosted_vertex_mode = (
        "live"
        if vertex_status == "completed"
        else "skipped"
        if not hosted_eval or trigger_status == "not_triggered" or vertex_status in {"failed", "auth_unavailable", "blocked", "sdk_unavailable"}
        else "mocked"
    )
    return {
        "local_scorecard": {
            "proof_mode": "live" if scorecard else "skipped",
            "overall": scorecard.get("overall"),
            "status": scorecard.get("status"),
            "decision_id": scorecard.get("decision_id"),
        },
        "trace_artifact": {
            "proof_mode": "live" if trace.get("trace_state") == "export_configured" else "mocked" if trace.get("trace_id") else "skipped",
            "trace_state": trace.get("trace_state"),
            "trace_id": trace.get("trace_id"),
            "span_id": trace.get("span_id"),
            "trace_url": trace.get("trace_url"),
            "ready": bool(trace.get("ready")),
        },
        "hosted_vertex_eval": {
            "proof_mode": hosted_vertex_mode,
            "status": hosted_eval.get("status"),
            "provider": hosted_eval.get("provider"),
            "evaluator_id": hosted_eval.get("evaluator_id"),
            "trigger": trigger,
            "vertex_result": vertex_result,
        },
    }


async def run_gcp_judge_trace_eval_smoke(
    *,
    scenario_key: str = "ride_down",
    execute: bool = False,
    scenario_runner: ScenarioRunner | None = None,
) -> dict[str, Any]:
    readiness = build_gcp_live_readiness()
    if scenario_runner is None:
        return {
            "status": "readiness_only",
            "scenario_key": scenario_key,
            "execute": execute,
            "checked_at": _now_iso(),
            "readiness": readiness,
            "smoke": {
                "proof_mode": "skipped",
                "reason": "No scenario runner was supplied; only readiness was checked.",
            },
        }

    run_result = await scenario_runner(scenario_key, execute)
    eval_result = _extract_eval(run_result)
    analytics = _extract_analytics(run_result)
    proof = _proof_from_eval(eval_result)
    analytics_inserted = bool(analytics.get("inserted"))
    analytics_mocked = bool(analytics) and not analytics_inserted
    return {
        "status": "complete" if eval_result else "missing_eval",
        "scenario_key": scenario_key,
        "execute": execute,
        "checked_at": _now_iso(),
        "readiness": readiness,
        "smoke": {
            "proof_mode": "live" if eval_result else "skipped",
            "agent_run_status": run_result.get("status"),
            "decision_id": run_result.get("decision_id"),
            "outcome_id": run_result.get("outcome_id"),
            "eval_present": bool(eval_result),
            "proof": {
                **proof,
                "analytics_export": {
                    "proof_mode": "live" if analytics_inserted else "mocked" if analytics_mocked else "skipped",
                    "inserted": analytics.get("inserted"),
                    "row_counts": analytics.get("row_counts"),
                    "status": analytics.get("status") or analytics.get("mode"),
                },
            },
        },
    }
