from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any, Callable


FetchDocuments = Callable[[str, int], list[dict[str, Any]]]


DATA_PRODUCTS = [
    {
        "id": "guest_feedback_monthly",
        "collection": "executive_guest_feedback_monthly",
        "coverageKey": "guestFeedbackMonths",
        "requiredFields": ["month", "channel", "theme", "sentiment", "volume", "representative_summary", "source_count"],
        "purpose": "Monthly feedback and sentiment rollup.",
    },
    {
        "id": "guest_feedback_events",
        "collection": "executive_event_sentiment",
        "coverageKey": "eventSentimentWindows",
        "requiredFields": ["event_id", "event_name", "window_start", "window_end", "before_sentiment", "after_sentiment", "top_negative_themes"],
        "purpose": "Before/after guest sentiment around named events.",
    },
    {
        "id": "refund_reason_rollup",
        "collection": "executive_refund_reason_rollup",
        "coverageKey": "refundReasonRows",
        "requiredFields": ["month", "reason_code", "reason_label", "count", "linked_operational_signal"],
        "purpose": "Refund and recovery reason analysis without private guest data.",
    },
    {
        "id": "guest_recovery_actions",
        "collection": "executive_guest_recovery_actions",
        "coverageKey": "guestRecoveryActionRows",
        "requiredFields": ["action_id", "incident_id", "message_type", "approved_by_role", "sent_at", "outcome_summary"],
        "purpose": "Whether recovery messages and offers were clear, timely, and approved.",
    },
    {
        "id": "policy_exception_rollup",
        "collection": "executive_policy_exception_rollup",
        "coverageKey": "policyExceptionRows",
        "requiredFields": ["policy_area", "case_type", "exception_count", "approval_path", "inconsistency_summary", "recommended_fix"],
        "purpose": "Policy inconsistency detection across similar guest-care cases.",
    },
    {
        "id": "competitor_review_themes",
        "collection": "executive_competitor_review_themes",
        "coverageKey": "competitorThemeRows",
        "requiredFields": ["competitor", "review_month", "theme", "sentiment", "sample_count", "source", "summary"],
        "purpose": "External benchmark for guest expectations.",
    },
    {
        "id": "staff_training_outcomes",
        "collection": "executive_staff_training_outcomes",
        "coverageKey": "trainingOutcomeRows",
        "requiredFields": ["team", "training_topic", "completion_rate", "guest_theme_link", "post_training_delta"],
        "purpose": "Connect guest themes to staff training needs and outcomes.",
    },
]

DATA_PRODUCT_BY_COLLECTION = {str(item["collection"]): item for item in DATA_PRODUCTS}

ARTIFACT_REQUIRED_FIELDS = [
    "artifactId",
    "artifactType",
    "status",
    "reviewerStatus",
    "generatedAt",
    "requestedByRole",
    "sourceCoverage",
    "privacyBoundary",
    "policyBoundary",
]

SENSITIVE_FIELD_PATTERNS = [
    "guest_name",
    "customer_name",
    "child_name",
    "minor_name",
    "patient_name",
    "email",
    "phone",
    "home_address",
    "payment",
    "card_number",
    "credit_card",
    "medical_detail",
    "diagnosis",
    "employee_private_note",
    "raw_text",
    "raw_transcript",
    "transcript",
]

SENSITIVE_VALUE_PATTERNS = [
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
    re.compile(r"\b(?:child|minor|patient|diagnosis|credit card|payment card|passport)\s*[:=]", re.IGNORECASE),
]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _has_field(row: dict[str, Any], field: str) -> bool:
    value = row.get(field)
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    if isinstance(value, list) and not value:
        return False
    return True


def _contains_sensitive_value(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_contains_sensitive_key(str(key)) or _contains_sensitive_value(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_sensitive_value(item) for item in value)
    if not isinstance(value, str):
        return False
    return any(pattern.search(value) for pattern in SENSITIVE_VALUE_PATTERNS)


def _contains_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(pattern in lowered for pattern in SENSITIVE_FIELD_PATTERNS)


def _validation_error(collection_name: str, index: int, reason: str, field: str | None = None) -> dict[str, Any]:
    return {
        "collection": collection_name,
        "index": index,
        "reason": reason,
        "field": field,
    }


def validate_executive_experience_documents(collection_name: str, documents: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    spec = DATA_PRODUCT_BY_COLLECTION.get(collection_name)
    if collection_name == "executive_brief_artifacts":
        required_fields = ARTIFACT_REQUIRED_FIELDS
    elif spec:
        required_fields = [*spec["requiredFields"], "sourceType"]
    else:
        return {
            "status": "blocked",
            "collection": collection_name,
            "valid": False,
            "errors": [_validation_error(collection_name, 0, "Collection is not approved for Executive Experience Intelligence writes.")],
        }

    for index, document in enumerate(documents):
        if not isinstance(document, dict):
            errors.append(_validation_error(collection_name, index, "Document is not an object."))
            continue
        for field in required_fields:
            if not _has_field(document, field):
                errors.append(_validation_error(collection_name, index, "Missing required field.", field))
        source_type = str(document.get("sourceType") or "").strip().lower()
        if collection_name != "executive_brief_artifacts" and source_type not in {"demo", "curated", "live", "imported"}:
            errors.append(_validation_error(collection_name, index, "sourceType must be demo, curated, live, or imported.", "sourceType"))
        for key, value in document.items():
            if _contains_sensitive_key(str(key)):
                errors.append(_validation_error(collection_name, index, "Sensitive field name is not allowed in executive evidence.", str(key)))
            elif _contains_sensitive_value(value):
                errors.append(_validation_error(collection_name, index, "Sensitive-looking value is not allowed in executive evidence.", str(key)))

    return {
        "status": "pass" if not errors else "blocked",
        "collection": collection_name,
        "valid": not errors,
        "checkedCount": len(documents),
        "errors": errors,
    }


def evidence_hash(value: Any) -> str:
    import hashlib

    compact = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(compact.encode("utf-8")).hexdigest()[:16]


def _readiness_for_product(spec: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    required = [str(field) for field in spec["requiredFields"]]
    row_count = len(rows)
    complete_rows = [row for row in rows if isinstance(row, dict) and all(_has_field(row, field) for field in required)]
    observed_fields = sorted({field for row in rows if isinstance(row, dict) for field in required if _has_field(row, field)})
    missing_fields = [field for field in required if field not in observed_fields]
    minimum_fields_present = bool(complete_rows)
    if row_count == 0:
        status = "missing"
        confidence = "none"
        blocking_gap = f"No curated {spec['id']} evidence is connected."
    elif minimum_fields_present:
        status = "ready"
        confidence = "high" if len(complete_rows) >= 3 else "medium"
        blocking_gap = None
    else:
        status = "partial"
        confidence = "low"
        blocking_gap = f"Rows exist, but no row contains all minimum fields: {', '.join(missing_fields)}."

    return {
        "dataProduct": spec["id"],
        "collection": spec["collection"],
        "purpose": spec["purpose"],
        "status": status,
        "confidence": confidence,
        "rowCount": row_count,
        "completeRowCount": len(complete_rows),
        "minimumFieldsPresent": minimum_fields_present,
        "requiredFields": required,
        "missingFields": missing_fields,
        "blockingGap": blocking_gap,
        "sourceTypes": sorted({str(row.get("sourceType") or "unknown") for row in rows if isinstance(row, dict)}),
    }


def build_executive_experience_evidence(
    fetch_documents: FetchDocuments | None = None,
    *,
    limit_per_product: int = 50,
) -> dict[str, Any]:
    if fetch_documents is None:
        from mongo_memory import get_latest_memory_documents_fast

        fetch_documents = get_latest_memory_documents_fast

    safe_limit = max(1, min(250, int(limit_per_product or 50)))
    source_coverage: dict[str, int] = {}
    readiness: list[dict[str, Any]] = []
    retrieval_errors: list[str] = []
    source_type_counts: dict[str, int] = {}

    for spec in DATA_PRODUCTS:
        rows: list[dict[str, Any]] = []
        try:
            rows = [row for row in fetch_documents(str(spec["collection"]), safe_limit) if isinstance(row, dict)]
        except Exception as error:
            retrieval_errors.append(f"{spec['collection']}: {str(error)[:180]}")
        source_coverage[str(spec["coverageKey"])] = len(rows)
        for row in rows:
            source_type = str(row.get("sourceType") or "unknown")
            source_type_counts[source_type] = source_type_counts.get(source_type, 0) + 1
        readiness.append(_readiness_for_product(spec, rows))

    ready_count = sum(1 for item in readiness if item["status"] == "ready")
    partial_count = sum(1 for item in readiness if item["status"] == "partial")
    missing_count = sum(1 for item in readiness if item["status"] == "missing")
    total = len(readiness)
    overall_confidence = "high" if ready_count >= total - 1 else "medium" if ready_count >= 3 else "low" if ready_count or partial_count else "none"
    status = "ready" if ready_count == total else "partial" if ready_count or partial_count else "missing"

    return {
        "status": status,
        "mode": "executive_experience_evidence",
        "generatedAt": _utc_now(),
        "authorizationCapability": "read_executive_intelligence",
        "sourceCoverage": source_coverage,
        "summary": {
            "totalDataProducts": total,
            "readyDataProducts": ready_count,
            "partialDataProducts": partial_count,
            "missingDataProducts": missing_count,
            "overallConfidence": overall_confidence,
            "basis": "longitudinal_evidence" if ready_count >= 3 else "mixed_proxy_and_partial_evidence" if ready_count or partial_count else "live_operational_proxies_only",
            "sourceTypeCounts": source_type_counts,
            "containsDemoEvidence": source_type_counts.get("demo", 0) > 0,
        },
        "evidenceReadiness": readiness,
        "missingDataProducts": [item["dataProduct"] for item in readiness if item["status"] == "missing"],
        "partialDataProducts": [item["dataProduct"] for item in readiness if item["status"] == "partial"],
        "readyDataProducts": [item["dataProduct"] for item in readiness if item["status"] == "ready"],
        "privacyBoundary": "Aggregate or redacted data only. No private guest identifiers, payment data, medical details, child identity details, or raw free-text records in executive summaries.",
        "policyBoundary": "Executive agent can summarize, compare, audit, brief, and recommend. It cannot dispatch, approve refunds, write labels or rewards, promote models, or override policy.",
        "readinessIssues": retrieval_errors,
    }


def executive_evidence_source_summary(evidence: dict[str, Any] | None) -> dict[str, Any]:
    evidence = evidence if isinstance(evidence, dict) else {}
    summary = evidence.get("summary", {}) if isinstance(evidence.get("summary"), dict) else {}
    ready_count = int(summary.get("readyDataProducts") or 0)
    partial_count = int(summary.get("partialDataProducts") or 0)
    if ready_count >= 3:
        finding_basis = "longitudinal_evidence"
    elif ready_count or partial_count:
        finding_basis = "mixed_proxy_and_partial_evidence"
    else:
        finding_basis = "live_operational_proxies_only"
    return {
        "findingBasis": finding_basis,
        "overallConfidence": summary.get("overallConfidence") or "none",
        "readyDataProducts": evidence.get("readyDataProducts", []) if isinstance(evidence.get("readyDataProducts"), list) else [],
        "partialDataProducts": evidence.get("partialDataProducts", []) if isinstance(evidence.get("partialDataProducts"), list) else [],
        "missingDataProducts": evidence.get("missingDataProducts", []) if isinstance(evidence.get("missingDataProducts"), list) else [],
    }
