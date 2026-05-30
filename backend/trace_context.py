from __future__ import annotations

import os
from typing import Any


def current_trace_context() -> dict[str, Any]:
    empty = {
        "trace_id": "",
        "span_id": "",
        "trace_lookup_query": "",
        "trace_url": "",
    }
    if str(os.getenv("PARKPULSE_ENABLE_OTEL_SPANS", "")).strip().lower() not in {"1", "true", "yes", "on"}:
        return empty
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
    except Exception:
        return empty
    context = span.get_span_context()
    if not context or not context.is_valid:
        return empty

    trace_id = f"{context.trace_id:032x}"
    span_id = f"{context.span_id:016x}"
    template = os.getenv("GCP_TRACE_URL_TEMPLATE", "").strip() or os.getenv("ARIZE_TRACE_URL_TEMPLATE", "").strip()
    project = os.getenv("GCP_TRACE_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT")
    if template:
        trace_url = template.format(trace_id=trace_id, span_id=span_id, project=project or "")
    elif project:
        trace_url = f"https://console.cloud.google.com/traces/list?project={project}&tid={trace_id}"
    else:
        trace_url = ""
    return {
        "trace_id": trace_id,
        "span_id": span_id,
        "trace_lookup_query": f"trace_id:{trace_id}",
        "trace_url": trace_url,
    }
