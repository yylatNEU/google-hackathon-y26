from __future__ import annotations

import json
import os
from contextlib import contextmanager, nullcontext
from typing import Any, Iterator

from trace_context import current_trace_context


MAX_ATTRIBUTE_CHARS = 12000


class _NoopSpan:
    def set_attribute(self, *_args, **_kwargs) -> None:
        return None

    def record_exception(self, *_args, **_kwargs) -> None:
        return None


def _json_preview(value: Any, limit: int = MAX_ATTRIBUTE_CHARS) -> str:
    try:
        text = json.dumps(value, default=str, sort_keys=True)
    except Exception:
        text = str(value)
    if len(text) <= limit:
        return text
    return text[: limit - 16] + "...[truncated]"


def set_span_attributes(span: Any, attributes: dict[str, Any] | None) -> None:
    if not attributes:
        return
    for key, value in attributes.items():
        if value is None:
            continue
        try:
            if isinstance(value, (str, bool, int, float)):
                span.set_attribute(key, value)
            else:
                span.set_attribute(key, _json_preview(value))
        except Exception:
            continue


@contextmanager
def traced_span(
    name: str,
    *,
    span_kind: str = "CHAIN",
    attributes: dict[str, Any] | None = None,
    input_value: Any = None,
) -> Iterator[Any]:
    if str(os.getenv("PARKPULSE_ENABLE_OTEL_SPANS", "")).strip().lower() in {"1", "true", "yes", "on"}:
        try:
            from opentelemetry import trace

            context = trace.get_tracer("parkpulse.trace_helpers").start_as_current_span(name)
        except Exception:
            context = nullcontext(_NoopSpan())
    else:
        context = nullcontext(_NoopSpan())

    with context as span:
        set_span_attributes(
            span,
            {
                "openinference.span.kind": span_kind,
                "parkpulse.span.kind": span_kind.lower(),
                **(attributes or {}),
            },
        )
        if input_value is not None:
            set_span_attributes(span, {"input.value": _json_preview(input_value)})
        try:
            yield span
        except Exception as error:
            try:
                span.record_exception(error)
                span.set_attribute("error.type", type(error).__name__)
                span.set_attribute("error.message", str(error))
            except Exception:
                pass
            raise


def finish_span(span: Any, output_value: Any = None, attributes: dict[str, Any] | None = None) -> None:
    if output_value is not None:
        set_span_attributes(span, {"output.value": _json_preview(output_value)})
    set_span_attributes(span, attributes)


def traced_payload(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = current_trace_context()
    if extra:
        payload.update(extra)
    return payload
