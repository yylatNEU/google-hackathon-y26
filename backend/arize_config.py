import os
from dataclasses import asdict, dataclass
from typing import Any


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _gcp_improvement_is_primary() -> bool:
    return os.getenv("PARKPULSE_ONLINE_IMPROVEMENT_PROVIDER", "").strip().lower() == "gcp"


def _optional_arize_allowed() -> bool:
    return _truthy(os.getenv("PARKPULSE_ENABLE_OPTIONAL_ARIZE"))


@dataclass(frozen=True)
class ArizeAxStatus:
    platform: str
    project_name: str
    space_id: str | None
    collector_endpoint: str | None
    has_api_key: bool
    tracing_enabled: bool
    configured: bool
    instrumentation: str
    export_policy: str
    export_background_spans: bool
    startup_error: str | None = None

    @property
    def readiness_issues(self) -> list[str]:
        issues: list[str] = []
        if self.tracing_enabled and not self.space_id:
            issues.append("ENABLE_ARIZE_TRACING=true but ARIZE_SPACE_ID is missing.")
        if self.tracing_enabled and not self.collector_endpoint:
            issues.append("ENABLE_ARIZE_TRACING=true but ARIZE_COLLECTOR_ENDPOINT is missing.")
        if self.tracing_enabled and not self.has_api_key:
            issues.append("ENABLE_ARIZE_TRACING=true but ARIZE_API_KEY is missing.")
        if self.startup_error:
            issues.append(self.startup_error)
        return issues

    def public_dict(self) -> dict:
        data = asdict(self)
        data["ready"] = self.tracing_enabled and self.configured and not self.readiness_issues
        data["readiness_issues"] = self.readiness_issues
        hosted_evaluator_id = os.getenv("ARIZE_HOSTED_EVALUATOR_ID", "").strip()
        data["evaluation"] = {
            "local_scorecards_enabled": True,
            "hosted_judge_configured": bool(hosted_evaluator_id),
            "hosted_judge_status": "configured" if hosted_evaluator_id else "not_configured",
            "hosted_evaluator_id": hosted_evaluator_id or None,
            "judge_runtime": "hosted_arize" if hosted_evaluator_id else "app_local_scorecard",
            "note": (
                "Hosted Arize judge is configured."
                if hosted_evaluator_id
                else "External Arize export is optional. The default demo path uses GCP internal trace/eval with local request-time scorecards."
            ),
        }
        return data


_startup_error: str | None = None


def get_arize_status() -> ArizeAxStatus:
    endpoint = os.getenv("ARIZE_COLLECTOR_ENDPOINT") or "https://otlp.arize.com/v1/traces"
    space_id = os.getenv("ARIZE_SPACE_ID")
    has_api_key = bool(os.getenv("ARIZE_API_KEY"))
    tracing_enabled = _truthy(os.getenv("ENABLE_ARIZE_TRACING"))
    if _gcp_improvement_is_primary() and not _optional_arize_allowed():
        tracing_enabled = False
    export_policy = os.getenv("ARIZE_EXPORT_POLICY", "useful").strip().lower() or "useful"
    export_background_spans = _truthy(os.getenv("ARIZE_EXPORT_BACKGROUND_SPANS"))
    return ArizeAxStatus(
        platform="Arize AX",
        project_name=os.getenv("ARIZE_PROJECT_NAME") or os.getenv("PHOENIX_PROJECT_NAME", "parkpulse-ai"),
        space_id=space_id,
        collector_endpoint=endpoint,
        has_api_key=has_api_key,
        tracing_enabled=tracing_enabled,
        configured=bool(endpoint and space_id and has_api_key),
        instrumentation="manual OpenTelemetry OTLP HTTP spans for Arize AX with usefulness filtering",
        export_policy=export_policy,
        export_background_spans=export_background_spans,
        startup_error=_startup_error,
    )


def _trace_endpoint(endpoint: str) -> str:
    clean_endpoint = endpoint.rstrip("/")
    if clean_endpoint.endswith("/v1/traces"):
        return clean_endpoint
    return f"{clean_endpoint}/v1/traces"


def _arize_headers(space_id: str | None, api_key: str) -> dict[str, str]:
    return {
        "authorization": api_key,
        "api_key": api_key,
        "arize-space-id": space_id or "",
        "space_id": space_id or "",
        "arize-interface": "otel",
    }


def _span_attr(span: Any, key: str, default: Any = None) -> Any:
    attributes = getattr(span, "attributes", None) or {}
    return attributes.get(key, default)


def _span_int_attr(span: Any, key: str) -> int:
    value = _span_attr(span, key, 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _span_is_useful(span: Any, status: ArizeAxStatus) -> bool:
    if status.export_policy in {"all", "raw"}:
        return True

    source = str(_span_attr(span, "parkpulse.telemetry.source", "") or "")
    if source != "background_loop":
        return True

    if status.export_background_spans:
        return True

    if bool(_span_attr(span, "parkpulse.telemetry.keep", False)):
        return True

    return _span_int_attr(span, "parkpulse.signal.new_count") > 0


class UsefulSpanExporter:
    def __init__(self, exporter: Any, status: ArizeAxStatus) -> None:
        self.exporter = exporter
        self.status = status

    def export(self, spans):
        useful_spans = [span for span in spans if _span_is_useful(span, self.status)]
        if not useful_spans:
            try:
                from opentelemetry.sdk.trace.export import SpanExportResult

                return SpanExportResult.SUCCESS
            except Exception:
                return None
        return self.exporter.export(useful_spans)

    def shutdown(self):
        return self.exporter.shutdown()

    def force_flush(self, timeout_millis: int = 30000):
        force_flush = getattr(self.exporter, "force_flush", None)
        if force_flush is None:
            return True
        return force_flush(timeout_millis=timeout_millis)


def setup_arize_tracing():
    global _startup_error

    status = get_arize_status()
    if not status.tracing_enabled:
        return None

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(
            resource=Resource.create(
                {
                    "service.name": "parkpulse-ai",
                    "openinference.project.name": status.project_name,
                    "model_id": status.project_name,
                }
            )
        )
        exporter = OTLPSpanExporter(
            endpoint=_trace_endpoint(status.collector_endpoint or ""),
            headers=_arize_headers(status.space_id, os.getenv("ARIZE_API_KEY", "")),
        )
        provider.add_span_processor(BatchSpanProcessor(UsefulSpanExporter(exporter, status)))
        trace.set_tracer_provider(provider)
        return provider
    except Exception as error:
        _startup_error = f"Arize AX tracing startup failed: {error}"
        print(_startup_error)
        return None


def get_arize_phoenix_status() -> ArizeAxStatus:
    return get_arize_status()


def setup_phoenix_tracing():
    return setup_arize_tracing()
