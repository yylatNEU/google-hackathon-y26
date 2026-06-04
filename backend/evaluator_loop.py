from __future__ import annotations

import json
import os
import shutil
import socket
import ssl
import subprocess
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


HOSTED_EVALUATOR_DIMENSIONS: list[dict[str, Any]] = [
    {
        "id": "groundedness",
        "label": "Groundedness",
        "question": "Is the decision grounded in live park state, active alerts, retrieved memory, and trace evidence?",
        "required_fields": ["scenario", "selected_action", "trace_id", "dimension_scores", "retrieved_context"],
        "span_attributes": ["parkpulse.scenario", "parkpulse.trace.id", "parkpulse.eval.dimension_count"],
    },
    {
        "id": "policy_safety",
        "label": "Policy and safety",
        "question": "Did the action respect safety, labor, guest-care, and human-approval policy gates?",
        "required_fields": ["policy_gate_status", "policy_findings", "needs_human_approval", "failure_reasons"],
        "span_attributes": ["parkpulse.eval.status", "parkpulse.eval.failure_count"],
    },
    {
        "id": "actionability",
        "label": "Actionability",
        "question": "Is the selected action specific enough to dispatch to a guest, staff, or equipment receiver?",
        "required_fields": ["selected_action", "dispatches", "receiver_acks", "response_metrics"],
        "span_attributes": ["parkpulse.eval.overall", "parkpulse.delivery.dispatch_count"],
    },
    {
        "id": "outcome_followthrough",
        "label": "Outcome follow-through",
        "question": "Did the delivered action produce measurable take rate, positive response, or operational movement?",
        "required_fields": ["response_score", "take_rate", "positive_response_rate", "follow_through_rate"],
        "span_attributes": ["parkpulse.response.score", "parkpulse.response.status"],
    },
    {
        "id": "regression_learning",
        "label": "Regression learning",
        "question": "Can the eval row be reused for BigQuery trend analysis, prompt tuning, and future regression checks?",
        "required_fields": ["decision_id", "outcome_id", "trace_url", "dimensions_json", "failure_reasons_json"],
        "span_attributes": ["parkpulse.trace.url", "parkpulse.eval.status"],
    },
]


def evaluator_loop_status() -> dict[str, Any]:
    vertex_evaluator_id = os.getenv("VERTEX_GENAI_EVALUATOR_ID") or None
    arize_evaluator_id = os.getenv("ARIZE_HOSTED_EVALUATOR_ID") or None
    vertex_enabled = _env_bool("ENABLE_VERTEX_GENAI_EVAL")
    hosted_trigger_enabled = _env_bool("PARKPULSE_ENABLE_HOSTED_EVAL_TRIGGER")
    continuous_enabled = _env_bool("ENABLE_VERTEX_CONTINUOUS_EVAL")
    trace_export_configured = _env_bool("ENABLE_GCP_CLOUD_TRACE_EXPORT") or bool(os.getenv("GCP_TRACE_URL_TEMPLATE"))
    trace_export_ready = False
    provider = (
        "vertex_genai_evaluation"
        if vertex_enabled and vertex_evaluator_id
        else "arize"
        if arize_evaluator_id
        else "local_scorecard"
    )
    hosted_configured = provider != "local_scorecard"
    blockers: list[str] = []
    if vertex_enabled and not vertex_evaluator_id:
        blockers.append("ENABLE_VERTEX_GENAI_EVAL=true but VERTEX_GENAI_EVALUATOR_ID is not set.")
    if not hosted_configured:
        blockers.append("No hosted evaluator is configured; set VERTEX_GENAI_EVALUATOR_ID or ARIZE_HOSTED_EVALUATOR_ID.")
    if hosted_configured and not hosted_trigger_enabled:
        blockers.append("Hosted evaluator trigger is disabled; set PARKPULSE_ENABLE_HOSTED_EVAL_TRIGGER=true after credentials and quotas are ready.")
    if not trace_export_configured:
        blockers.append("GCP trace export is not configured; eval can run, but trace links stay local unless ENABLE_GCP_CLOUD_TRACE_EXPORT or GCP_TRACE_URL_TEMPLATE is set.")

    return {
        "checked_at": _now_iso(),
        "status": "ready" if hosted_configured and hosted_trigger_enabled else "configured" if hosted_configured else "local_only",
        "provider": provider,
        "hosted_configured": hosted_configured,
        "hosted_trigger_enabled": hosted_trigger_enabled,
        "continuous_monitoring": {
            "configured": continuous_enabled and bool(vertex_evaluator_id),
            "sampling_rate": os.getenv("VERTEX_EVAL_SAMPLING_RATE", "not_configured"),
        },
        "evaluator_id": vertex_evaluator_id or arize_evaluator_id,
        "location": os.getenv("VERTEX_EVAL_LOCATION", "us-central1"),
        "runtime": "hosted_batch_or_continuous_eval" if hosted_configured else "app_local_scorecard",
        "dimensions": HOSTED_EVALUATOR_DIMENSIONS,
        "column_mapping": {
            "input": "scenario + selected_action + live_state_digest",
            "output": "agent_action_plan + receiver_payloads",
            "context": "trace_contract + memory_retrieval + governance_findings",
            "reference": "park_scenario.policy + historical_outcome_priors",
            "metadata": "trace_id, span_id, decision_id, outcome_id, scenario_key",
        },
        "trace_requirements": {
            "trace_export_configured": trace_export_configured,
            "trace_export_ready": trace_export_ready,
            "trace_sink": "gcp_cloud_trace" if trace_export_ready else "configured_unverified" if trace_export_configured else "local_otel_context_only",
        },
        "tooling": {
            "ax_cli_available": shutil.which("ax") is not None,
            "server_side_trigger": "vertex_rest_evaluate_instances",
            "vertex_sdk_importable": _vertex_eval_sdk_importable(),
            "vertex_eval_transport": os.getenv("PARKPULSE_VERTEX_EVAL_TRANSPORT", "rest"),
        },
        "readiness_issues": blockers,
        "arize": {
            "ready": bool(arize_evaluator_id),
            "enabled": bool(arize_evaluator_id),
        },
    }


def _vertex_eval_sdk_importable() -> bool:
    import importlib.util

    return importlib.util.find_spec("pandas") is not None and importlib.util.find_spec("vertexai") is not None


def _json_preview(value: Any, limit: int = 6000) -> str:
    text = json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))
    return text[:limit]


def _vertex_metrics(types_module: Any) -> list[Any]:
    configured = [
        item.strip().upper()
        for item in os.getenv(
            "VERTEX_EVAL_METRICS",
            "GENERAL_QUALITY,INSTRUCTION_FOLLOWING,SAFETY,GROUNDING",
        ).split(",")
        if item.strip()
    ]
    metrics: list[Any] = []
    rubric_metrics = getattr(types_module, "RubricMetric", None)
    generic_metric = getattr(types_module, "Metric", None)
    for name in configured:
        metric = getattr(rubric_metrics, name, None) if rubric_metrics is not None else None
        if metric is not None:
            metrics.append(metric)
        elif generic_metric is not None:
            metrics.append(generic_metric(name=name.lower()))
    return metrics


def _build_vertex_eval_row(payload_preview: dict[str, Any]) -> dict[str, Any]:
    dimension_scores = payload_preview.get("dimension_scores", {})
    failure_reasons = payload_preview.get("failure_reasons", [])
    selected_action = payload_preview.get("selected_action", {})
    governance = payload_preview.get("governance", {})
    response_metrics = payload_preview.get("response_metrics", {})
    dispatches = payload_preview.get("dispatches", [])
    trace = {
        "trace_id": payload_preview.get("trace_id"),
        "span_id": payload_preview.get("span_id"),
        "trace_url": payload_preview.get("trace_url"),
    }
    prompt = (
        "Evaluate this ParkPulse amusement-park operations decision. "
        "Judge whether it is grounded in live operational state, safe under park policy, actionable for receivers, "
        "and likely to produce measurable follow-through. Use the provided trace, local scorecard, governance, "
        "and receiver-response evidence."
    )
    response = {
        "selected_action": selected_action,
        "scorecard": {
            "overall": payload_preview.get("overall"),
            "status": payload_preview.get("scorecard_status"),
            "response_score": payload_preview.get("response_score"),
            "response_status": payload_preview.get("response_status"),
        },
        "response_metrics": response_metrics,
        "dispatches": dispatches,
        "dimension_scores": dimension_scores,
        "failure_reasons": failure_reasons,
    }
    reference = (
        "A strong response must cite live park state and trace evidence, pass safety and labor policy gates, "
        "name a concrete receiver action, preserve human approval when required, and include outcome evidence "
        "such as take rate, positive response, or follow-through."
    )
    return {
        "prompt": prompt,
        "response": _json_preview(response, 3000),
        "reference": reference,
        "context": _json_preview(
            {
                "scenario_key": payload_preview.get("scenario_key"),
                "decision_id": payload_preview.get("decision_id"),
                "outcome_id": payload_preview.get("outcome_id"),
                "trace": trace,
                "governance": governance,
                "state_digest": payload_preview.get("state_digest", {}),
                "outcome": payload_preview.get("outcome", {}),
                "dimension_explanations": payload_preview.get("dimension_explanations", {}),
            },
            4000,
        ),
        "other_data": _json_preview(payload_preview, 6000),
    }


def run_vertex_hosted_evaluation(payload_preview: dict[str, Any]) -> dict[str, Any]:
    if os.getenv("PARKPULSE_VERTEX_EVAL_TRANSPORT", "rest").strip().lower() != "sdk":
        return run_vertex_rest_evaluation(payload_preview)

    project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("BIGQUERY_PROJECT")
    location = os.getenv("VERTEX_EVAL_LOCATION", "us-central1")
    evaluator_id = os.getenv("VERTEX_GENAI_EVALUATOR_ID") or "parkpulse_vertex_eval"
    if not project:
        return {
            "status": "blocked",
            "provider": "vertex_genai_evaluation",
            "reason": "GOOGLE_CLOUD_PROJECT or BIGQUERY_PROJECT is not set.",
        }

    try:
        import pandas as pd
        from vertexai import Client, types
    except Exception as error:
        return {
            "status": "sdk_unavailable",
            "provider": "vertex_genai_evaluation",
            "reason": f"Install google-cloud-aiplatform[evaluation] and pandas: {error}",
        }

    try:
        client = Client(project=project, location=location)
        row = _build_vertex_eval_row(payload_preview)
        eval_dataset_df = pd.DataFrame([row])
        evaluation_dataset = types.EvaluationDataset(
            eval_dataset_df=eval_dataset_df,
            candidate_name=evaluator_id,
        )
        metrics = _vertex_metrics(types)
        if not metrics:
            return {
                "status": "blocked",
                "provider": "vertex_genai_evaluation",
                "reason": "No Vertex eval metrics resolved from VERTEX_EVAL_METRICS.",
            }
        eval_result = client.evals.evaluate(dataset=evaluation_dataset, metrics=metrics)
        return _summarize_vertex_eval_result(eval_result, metrics, project, location, evaluator_id)
    except Exception as error:
        status = _vertex_exception_status(error)
        return {
            "status": status,
            "provider": "vertex_genai_evaluation",
            "project": project,
            "location": location,
            "evaluator_id": evaluator_id,
            "failure_class": status,
            "reason": str(error)[:800],
        }


def run_vertex_rest_evaluation(payload_preview: dict[str, Any]) -> dict[str, Any]:
    project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("BIGQUERY_PROJECT")
    location = os.getenv("VERTEX_EVAL_LOCATION", "us-central1")
    evaluator_id = os.getenv("VERTEX_GENAI_EVALUATOR_ID") or "parkpulse_vertex_eval"
    if not project:
        return {
            "status": "blocked",
            "provider": "vertex_genai_evaluation",
            "transport": "rest",
            "reason": "GOOGLE_CLOUD_PROJECT or BIGQUERY_PROJECT is not set.",
        }

    token_result = _vertex_access_token()
    if not token_result.get("token"):
        return {
            "status": "auth_unavailable",
            "provider": "vertex_genai_evaluation",
            "transport": "rest",
            "project": project,
            "location": location,
            "evaluator_id": evaluator_id,
            "reason": token_result.get("reason", "Could not obtain an access token for Vertex AI."),
        }

    instance = _build_vertex_eval_row(payload_preview)
    rest_instance = {
        "prompt": instance.get("prompt", ""),
        "response": instance.get("response", ""),
        "reference": instance.get("reference", ""),
        "context": instance.get("context", ""),
    }
    prompt_template = (
        "You are evaluating an amusement-park operations agent response. "
        "Score the response from 0.0 to 1.0 and explain the score. "
        "Criteria: grounded in live state and trace evidence, safe under park policy, actionable for receivers, "
        "and supported by outcome evidence.\n"
        "Prompt: {prompt}\nResponse: {response}\nReference: {reference}\nContext: {context}"
    )
    body = {
        "pointwiseMetricInput": {
            "instance": {"jsonInstance": json.dumps(rest_instance, default=str, separators=(",", ":"))},
            "metricSpec": {
                "metricPromptTemplate": prompt_template,
            },
        },
        "autoraterConfig": {
            "samplingCount": int(os.getenv("VERTEX_EVAL_SAMPLING_COUNT", "1")),
            "autoraterModel": os.getenv(
                "VERTEX_EVAL_AUTORATER_MODEL",
                f"projects/{project}/locations/{location}/publishers/google/models/gemini-2.5-flash",
            ),
        },
    }
    url = f"https://{location}-aiplatform.googleapis.com/v1beta1/projects/{project}/locations/{location}/:evaluateInstances"
    request = urllib.request.Request(
        url,
        data=json.dumps(body, default=str).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token_result['token']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=float(os.getenv("VERTEX_EVAL_HTTP_TIMEOUT_SECONDS", "45")), context=_vertex_eval_ssl_context()) as response:
            response_body = response.read().decode("utf-8")
            response_json = json.loads(response_body) if response_body else {}
        metric_result = response_json.get("pointwiseMetricResult") or response_json.get("rubricBasedMetricResult") or response_json
        return {
            "status": "completed",
            "provider": "vertex_genai_evaluation",
            "transport": "rest",
            "project": project,
            "location": location,
            "evaluator_id": evaluator_id,
            "metrics": ["parkpulse_pointwise_quality"],
            "result": metric_result,
        }
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")[:1000]
        status = _vertex_http_failure_status(error.code)
        return {
            "status": status,
            "provider": "vertex_genai_evaluation",
            "transport": "rest",
            "project": project,
            "location": location,
            "evaluator_id": evaluator_id,
            "failure_class": status,
            "reason": f"HTTP {error.code}: {details}",
        }
    except urllib.error.URLError as error:
        status = _vertex_exception_status(error)
        return {
            "status": status,
            "provider": "vertex_genai_evaluation",
            "transport": "rest",
            "project": project,
            "location": location,
            "evaluator_id": evaluator_id,
            "failure_class": status,
            "reason": str(error)[:800],
        }
    except (TimeoutError, socket.timeout) as error:
        return {
            "status": "timeout",
            "provider": "vertex_genai_evaluation",
            "transport": "rest",
            "project": project,
            "location": location,
            "evaluator_id": evaluator_id,
            "failure_class": "timeout",
            "reason": str(error)[:800],
        }
    except Exception as error:
        status = _vertex_exception_status(error)
        return {
            "status": status,
            "provider": "vertex_genai_evaluation",
            "transport": "rest",
            "project": project,
            "location": location,
            "evaluator_id": evaluator_id,
            "failure_class": status,
            "reason": str(error)[:800],
        }


def _vertex_eval_ssl_context() -> ssl.SSLContext | None:
    if _env_bool("PARKPULSE_VERTEX_EVAL_DISABLE_CERTIFI"):
        return None
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None


def _vertex_http_failure_status(code: int) -> str:
    if code in {401, 403}:
        return "auth_unavailable"
    if code == 429:
        return "quota_failed"
    if code in {408, 504}:
        return "timeout"
    return "http_failed"


def _vertex_exception_status(error: BaseException) -> str:
    text = str(error).lower()
    reason = getattr(error, "reason", None)
    if isinstance(reason, ssl.SSLError) or "certificate_verify_failed" in text or "ssl:" in text:
        return "ssl_failed"
    if isinstance(reason, TimeoutError) or isinstance(reason, socket.timeout) or "timed out" in text or "timeout" in text:
        return "timeout"
    return "failed"


def _vertex_access_token() -> dict[str, str]:
    env_token = os.getenv("VERTEX_EVAL_ACCESS_TOKEN")
    if env_token:
        return {"token": env_token, "source": "env"}

    gcloud = shutil.which("gcloud")
    if gcloud:
        try:
            result = subprocess.run(
                [gcloud, "auth", "application-default", "print-access-token"],
                check=True,
                capture_output=True,
                text=True,
                timeout=20,
            )
            token = result.stdout.strip()
            if token:
                return {"token": token, "source": "gcloud_adc"}
        except Exception as error:
            return {"reason": f"gcloud ADC token failed: {error}"}

    try:
        metadata_request = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
            headers={"Metadata-Flavor": "Google"},
        )
        with urllib.request.urlopen(metadata_request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        token = payload.get("access_token")
        if token:
            return {"token": token, "source": "metadata_server"}
    except Exception as error:
        return {"reason": f"metadata token failed: {error}"}

    return {"reason": "No VERTEX_EVAL_ACCESS_TOKEN, gcloud ADC token, or metadata token is available."}


def _summarize_vertex_eval_result(
    eval_result: Any,
    metrics: list[Any],
    project: str,
    location: str,
    evaluator_id: str,
) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for attr in ("summary_metrics", "metrics", "metadata"):
        value = getattr(eval_result, attr, None)
        if value is not None:
            summary[attr] = _jsonable(value)
    metrics_table = getattr(eval_result, "metrics_table", None)
    if metrics_table is not None:
        try:
            summary["metrics_table"] = metrics_table.to_dict(orient="records")[:3]
        except Exception:
            summary["metrics_table"] = str(metrics_table)[:1000]
    return {
        "status": "completed",
        "provider": "vertex_genai_evaluation",
        "project": project,
        "location": location,
        "evaluator_id": evaluator_id,
        "metrics": [getattr(metric, "name", None) or str(metric) for metric in metrics],
        "result": summary,
    }


def _jsonable(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, default=str))
    except Exception:
        return str(value)


def build_hosted_evaluator_loop(
    *,
    scenario_key: str,
    scorecard: dict[str, Any],
    dimension_scores: dict[str, Any],
    dimension_explanations: dict[str, Any],
    failure_reasons: list[dict[str, Any]],
    response_metrics: dict[str, Any],
    trace_artifact: dict[str, Any],
    decision_id: str | None = None,
    outcome_id: str | None = None,
    selected_action: dict[str, Any] | None = None,
    governance: dict[str, Any] | None = None,
    dispatches: list[dict[str, Any]] | None = None,
    state_digest: dict[str, Any] | None = None,
    outcome: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = evaluator_loop_status()
    hosted_configured = bool(status.get("hosted_configured"))
    trigger_enabled = bool(status.get("hosted_trigger_enabled"))
    if hosted_configured and trigger_enabled:
        run_status = "ready_to_trigger"
    elif hosted_configured:
        run_status = "configured_not_triggered"
    else:
        run_status = "local_scorecard_only"

    payload_preview = {
        "scenario_key": scenario_key,
        "decision_id": decision_id,
        "outcome_id": outcome_id,
        "overall": scorecard.get("overall"),
        "scorecard_status": scorecard.get("status"),
        "response_score": scorecard.get("response_score"),
        "response_status": response_metrics.get("status"),
        "trace_id": trace_artifact.get("trace_id"),
        "span_id": trace_artifact.get("span_id"),
        "trace_url": trace_artifact.get("trace_url"),
        "dimension_scores": dimension_scores,
        "dimension_explanations": dimension_explanations,
        "failure_reasons": failure_reasons,
        "selected_action": selected_action or {},
        "governance": governance or {},
        "response_metrics": response_metrics,
        "dispatches": _summarize_dispatches(dispatches or []),
        "state_digest": state_digest or {},
        "outcome": outcome or {},
    }
    trigger_result: dict[str, Any] | None = None
    blocking_trigger = _env_bool("PARKPULSE_HOSTED_EVAL_BLOCKING") or _env_bool("PARKPULSE_REQUIRE_STRICT_LIVE_GCP")
    if status.get("provider") == "vertex_genai_evaluation" and hosted_configured and trigger_enabled and blocking_trigger:
        trigger_result = run_vertex_hosted_evaluation(payload_preview)
        run_status = f"vertex_{trigger_result.get('status', 'unknown')}"
    elif status.get("provider") == "vertex_genai_evaluation" and hosted_configured and trigger_enabled:
        run_status = "vertex_deferred"

    return {
        "status": run_status,
        "provider": status["provider"],
        "evaluator_id": status.get("evaluator_id"),
        "location": status.get("location"),
        "runtime": status["runtime"],
        "checked_at": status["checked_at"],
        "trigger": {
            "enabled": trigger_enabled,
            "status": trigger_result.get("status") if trigger_result else "not_triggered",
            "reason": trigger_result.get("reason")
            if trigger_result
            else None
            if hosted_configured and trigger_enabled and blocking_trigger
            else "Hosted evaluator trigger is configured but deferred; local scorecard returned first."
            if hosted_configured and trigger_enabled
            else "Hosted evaluator trigger is disabled or not configured; no hosted score has been fabricated.",
            "blocking": blocking_trigger,
        },
        "vertex_result": trigger_result,
        "continuous_monitoring": status["continuous_monitoring"],
        "dimensions": status["dimensions"],
        "column_mapping": status["column_mapping"],
        "payload_preview": payload_preview,
        "readiness_issues": status["readiness_issues"],
    }


def _summarize_dispatches(dispatches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summarized: list[dict[str, Any]] = []
    for dispatch in dispatches[:8]:
        if not isinstance(dispatch, dict):
            continue
        response = dispatch.get("response", {}) if isinstance(dispatch.get("response"), dict) else {}
        payload = dispatch.get("payload", {}) if isinstance(dispatch.get("payload"), dict) else {}
        summarized.append(
            {
                "id": dispatch.get("id") or dispatch.get("dispatch_id"),
                "channel": dispatch.get("channel"),
                "target_system": dispatch.get("targetSystem") or dispatch.get("target_system"),
                "status": dispatch.get("status"),
                "payload_summary": payload.get("title") or payload.get("message") or payload.get("command") or payload.get("action"),
                "take_rate": response.get("takeRate"),
                "positive_response_rate": response.get("positiveResponseRate"),
                "follow_through_rate": response.get("reactiveFollowThroughRate"),
            }
        )
    return summarized
