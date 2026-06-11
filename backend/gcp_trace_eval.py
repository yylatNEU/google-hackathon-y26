from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any

from trace_context import current_trace_context
from trace_helpers import finish_span, traced_span


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


_gcp_trace_startup_error: str | None = None
_gcp_trace_provider: Any | None = None
_gcp_trace_exporter: Any | None = None


@dataclass(frozen=True)
class GcpTraceEvalStatus:
    platform: str
    provider: str
    project: str | None
    dataset: str
    trace_project: str | None
    trace_enabled: bool
    bigquery_ready: bool
    vertex_eval_enabled: bool
    mode: str
    primary_path: str
    readiness_issues: list[str]
    trace_export_configured: bool
    hosted_evaluator_configured: bool
    hosted_evaluator_id: str | None
    trace_export_ready: bool
    trace_export_error: str | None

    @property
    def ready(self) -> bool:
        return self.trace_enabled and (self.bigquery_ready or self.mode.endswith("preview"))

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ready"] = self.ready
        data["evaluation"] = {
            "local_scorecards_enabled": True,
            "hosted_judge_configured": self.hosted_evaluator_configured,
            "hosted_judge_status": "vertex_enabled" if self.vertex_eval_enabled else "local_runtime_judge",
            "hosted_evaluator_id": self.hosted_evaluator_id,
            "judge_runtime": "vertex_genai_eval_batch" if self.vertex_eval_enabled else "app_local_scorecard",
            "note": (
                "Request-time decisions use the local scorecard; BigQuery stores rows for learning and Vertex Gen AI Evaluation can run batch/regression checks."
            ),
            "continuous_monitoring": {
                "configured": _env_bool("ENABLE_VERTEX_CONTINUOUS_EVAL") and self.hosted_evaluator_configured,
                "sampling_rate": os.getenv("VERTEX_EVAL_SAMPLING_RATE", "not_configured"),
                "status": "configured" if _env_bool("ENABLE_VERTEX_CONTINUOUS_EVAL") and self.hosted_evaluator_configured else "not_configured",
            },
        }
        data["trace"] = {
            "runtime": "opentelemetry_context",
            "sink": "gcp_cloud_trace" if self.trace_export_ready else "gcp_cloud_trace_configured_uninitialized" if self.trace_export_configured else "local_otel_context_only",
            "url_template": os.getenv("GCP_TRACE_URL_TEMPLATE", ""),
            "export_configured": self.trace_export_configured,
            "export_ready": self.trace_export_ready,
            "startup_error": self.trace_export_error,
        }
        return data


def get_gcp_trace_eval_status() -> GcpTraceEvalStatus:
    project = os.getenv("BIGQUERY_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT")
    dataset = os.getenv("BIGQUERY_DATASET", "parkpulse_analytics")
    provider = os.getenv("PARKPULSE_ONLINE_IMPROVEMENT_PROVIDER", "gcp").strip().lower() or "gcp"
    trace_project = os.getenv("GCP_TRACE_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT") or project
    trace_enabled = _env_bool("ENABLE_GCP_TRACE_EVAL", True)
    analytics_enabled = _env_bool("ENABLE_BIGQUERY_ANALYTICS")
    vertex_eval_enabled = _env_bool("ENABLE_VERTEX_GENAI_EVAL")
    hosted_evaluator_id = os.getenv("VERTEX_GENAI_EVALUATOR_ID") or None
    trace_export_configured = _env_bool("ENABLE_GCP_CLOUD_TRACE_EXPORT") or bool(os.getenv("GCP_TRACE_URL_TEMPLATE"))
    readiness_issues: list[str] = []
    if not project:
        readiness_issues.append("BIGQUERY_PROJECT or GOOGLE_CLOUD_PROJECT is not set; analytics export stays in preview mode.")
    if not trace_project:
        readiness_issues.append("GCP_TRACE_PROJECT or GOOGLE_CLOUD_PROJECT is not set; trace links stay local-only.")
    if trace_enabled and not trace_export_configured:
        readiness_issues.append("GCP trace export is not configured; spans are local/Arize-only unless ENABLE_GCP_CLOUD_TRACE_EXPORT or GCP_TRACE_URL_TEMPLATE is set.")
    if trace_export_configured and _gcp_trace_startup_error:
        readiness_issues.append(_gcp_trace_startup_error)
    if vertex_eval_enabled and not hosted_evaluator_id:
        readiness_issues.append("ENABLE_VERTEX_GENAI_EVAL=true but VERTEX_GENAI_EVALUATOR_ID is not set; request-time eval remains local.")
    bigquery_configured = provider == "gcp" and analytics_enabled and bool(project and dataset)
    return GcpTraceEvalStatus(
        platform="GCP internal trace/eval",
        provider=provider,
        project=project,
        dataset=dataset,
        trace_project=trace_project,
        trace_enabled=trace_enabled,
        bigquery_ready=bigquery_configured,
        vertex_eval_enabled=vertex_eval_enabled,
        mode="online_gcp" if bigquery_configured else "local_scorecard_with_gcp_export_preview",
        primary_path="gcp_bigquery",
        readiness_issues=readiness_issues,
        trace_export_configured=trace_export_configured,
        hosted_evaluator_configured=vertex_eval_enabled and bool(hosted_evaluator_id),
        hosted_evaluator_id=hosted_evaluator_id,
        trace_export_ready=_gcp_trace_exporter is not None,
        trace_export_error=_gcp_trace_startup_error,
    )


def setup_gcp_cloud_trace_exporter() -> Any | None:
    global _gcp_trace_exporter, _gcp_trace_provider, _gcp_trace_startup_error

    status = get_gcp_trace_eval_status()
    if not status.trace_export_configured:
        return None
    if _gcp_trace_exporter is not None:
        return _gcp_trace_provider

    project = status.trace_project or status.project or os.getenv("GOOGLE_CLOUD_PROJECT")
    if not project:
        _gcp_trace_startup_error = "GCP Cloud Trace export requested but no GCP_TRACE_PROJECT, GOOGLE_CLOUD_PROJECT, or BIGQUERY_PROJECT is set."
        return None

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        exporter = CloudTraceSpanExporter(project_id=project)
        processor = BatchSpanProcessor(exporter)
        provider = trace.get_tracer_provider()
        add_processor = getattr(provider, "add_span_processor", None)
        if add_processor is None:
            provider = TracerProvider(
                resource=Resource.create(
                    {
                        "service.name": "parkpulse-ai",
                        "gcp.project.id": project,
                        "openinference.project.name": os.getenv("ARIZE_PROJECT_NAME") or "parkpulse-ai",
                    }
                )
            )
            trace.set_tracer_provider(provider)
            add_processor = provider.add_span_processor
        add_processor(processor)
        _gcp_trace_exporter = exporter
        _gcp_trace_provider = provider
        _gcp_trace_startup_error = None
        return provider
    except Exception as error:
        _gcp_trace_startup_error = f"GCP Cloud Trace exporter startup failed: {error}"
        print(_gcp_trace_startup_error)
        return None


def build_gcp_eval_trace(
    *,
    span: str,
    eval_subject: str,
    dimensions: list[str],
    decision_id: str | None = None,
) -> dict[str, Any]:
    status = get_gcp_trace_eval_status().public_dict()
    trace_context = current_trace_context()
    has_trace_id = bool(trace_context.get("trace_id"))
    trace_state = (
        "export_configured"
        if has_trace_id and status.get("trace", {}).get("export_configured")
        else "local_otel_context"
        if has_trace_id
        else "no_active_span"
    )
    return {
        "span": span,
        "eval_subject": eval_subject,
        "dimensions": dimensions,
        "decision_id": decision_id,
        "trace_id": trace_context.get("trace_id"),
        "span_id": trace_context.get("span_id"),
        "trace_lookup_query": trace_context.get("trace_lookup_query"),
        "trace_url": trace_context.get("trace_url"),
        "platform": status["platform"],
        "primary_path": status["primary_path"],
        "mode": status["mode"],
        "ready": bool(status["ready"]),
        "trace_state": trace_state,
        "evidence_depth": "span_with_eval_dimensions" if has_trace_id else "eval_payload_without_active_span",
        "bigquery": {
            "project": status.get("project"),
            "dataset": status.get("dataset"),
            "ready": bool(status.get("bigquery_ready")),
        },
        "vertex_genai_evaluation": status.get("evaluation", {}),
        "evaluation_status": (
            "hosted_continuous_configured"
            if status.get("evaluation", {}).get("continuous_monitoring", {}).get("configured")
            else "hosted_batch_configured"
            if status.get("evaluation", {}).get("hosted_judge_configured")
            else "local_scorecard_only"
        ),
    }


def verify_gcp_trace_export() -> dict[str, Any]:
    setup_gcp_cloud_trace_exporter()
    status = get_gcp_trace_eval_status().public_dict()
    if not status.get("trace", {}).get("export_configured"):
        return {
            "status": "not_configured",
            "verified": False,
            "trace": status.get("trace", {}),
            "readiness_issues": status.get("readiness_issues", []),
            "next_step": "Set ENABLE_GCP_CLOUD_TRACE_EXPORT=true and GOOGLE_CLOUD_PROJECT or GCP_TRACE_PROJECT, then restart the backend.",
        }
    if not status.get("trace", {}).get("export_ready"):
        return {
            "status": "exporter_unavailable",
            "verified": False,
            "trace": status.get("trace", {}),
            "readiness_issues": status.get("readiness_issues", []),
            "next_step": "Install opentelemetry-exporter-gcp-trace and ensure Google Cloud credentials can write Cloud Trace spans.",
        }

    with traced_span(
        "parkpulse.gcp_trace.verify_export",
        span_kind="CHAIN",
        attributes={
            "parkpulse.telemetry.keep": True,
            "parkpulse.telemetry.source": "trace_export_verification",
            "parkpulse.verify.target": "gcp_cloud_trace",
        },
        input_value={"verification": "gcp_cloud_trace_export"},
    ) as span:
        trace_context = current_trace_context()
        finish_span(span, {"trace_context": trace_context, "exporter": "gcp_cloud_trace"})

    flushed = _force_flush_gcp_trace()
    trace_url = trace_context.get("trace_url")
    if not trace_url and status.get("trace_project") and trace_context.get("trace_id"):
        trace_url = f"https://console.cloud.google.com/traces/list?project={status.get('trace_project')}&tid={trace_context['trace_id']}"
    return {
        "status": "flush_succeeded" if flushed else "flush_failed",
        "verified": bool(flushed and trace_context.get("trace_id")),
        "trace_id": trace_context.get("trace_id"),
        "span_id": trace_context.get("span_id"),
        "trace_lookup_query": trace_context.get("trace_lookup_query"),
        "trace_url": trace_url,
        "trace": status.get("trace", {}),
        "readiness_issues": status.get("readiness_issues", []),
        "note": "This verifies local span creation and exporter flush. Confirm final arrival in Cloud Trace using the trace URL or lookup query.",
    }


def _force_flush_gcp_trace() -> bool:
    for target in (_gcp_trace_provider, _gcp_trace_exporter):
        force_flush = getattr(target, "force_flush", None)
        if force_flush is None:
            continue
        try:
            result = force_flush(30000)
            if result is False:
                return False
        except TypeError:
            try:
                result = force_flush(timeout_millis=30000)
                if result is False:
                    return False
            except Exception:
                return False
        except Exception:
            return False
    return True
