from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


MAX_LEDGER_ROWS = 250
LOW_ATTENDANCE_CROWD_BACKLOG_FLOOR = 500
MIN_PATH_GUESTS_FOR_CROWD_BACKLOG = 250


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _runtime_dir() -> Path:
    return Path(os.getenv("PARKPULSE_RUNTIME_DIR", "/tmp/parkpulse"))


def _ledger_path() -> Path:
    configured = os.getenv("PARKPULSE_AGENT_OPS_LEDGER")
    if configured:
        return Path(configured)
    return _runtime_dir() / "agent_ops_ledger.jsonl"


def _compact_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _stable_id(prefix: str, payload: Any) -> str:
    return f"{prefix}_{hashlib.sha1(_compact_json(payload).encode('utf-8')).hexdigest()[:16]}"


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _represented_guests(state: dict[str, Any]) -> int:
    flow = _as_dict(state.get("guestFlow"))
    explicit = flow.get("representedGuests")
    if explicit is not None:
        return int(_number(explicit) or 0)
    zones = [zone for zone in _as_list(flow.get("zones")) if isinstance(zone, dict)]
    if zones:
        return sum(max(0, int(_number(zone.get("currentGuests")) or 0)) for zone in zones)
    groups = _as_list(_as_dict(state.get("physicalMap")).get("guestGroups"))
    if groups:
        return sum(max(0, int(_number(group.get("count") or group.get("guestCount")) or 0)) for group in groups if isinstance(group, dict))
    return -1


def _validated_path_congestion(path: dict[str, Any], represented_guests: int) -> int:
    congestion = int(_number(path.get("congestionLevel")) or 0)
    if represented_guests < 0:
        return congestion
    raw_current = int(_number(path.get("currentGuests")) or 0)
    current_guests = min(raw_current, represented_guests)
    if represented_guests < LOW_ATTENDANCE_CROWD_BACKLOG_FLOOR or current_guests < MIN_PATH_GUESTS_FOR_CROWD_BACKLOG:
        return 0
    return congestion


_CASE_INFERENCE_STOPWORDS = {
    "case",
    "park",
    "guest",
    "guests",
    "action",
    "actions",
    "agent",
    "review",
    "state",
    "ready",
    "recorded",
    "completed",
    "dispatch",
    "receiver",
    "policy",
    "before",
    "after",
    "near",
    "with",
    "from",
    "that",
    "this",
    "while",
    "into",
    "queue",
}


def _case_tokens(*values: Any) -> set[str]:
    blob = " ".join(str(value or "") for value in values).lower()
    return {
        term
        for term in re.split(r"[^a-z0-9]+", blob)
        if len(term) >= 4 and term not in _CASE_INFERENCE_STOPWORDS
    }


def _infer_case_from_doctrine(row: dict[str, Any]) -> dict[str, Any]:
    text_terms = _case_tokens(
        row.get("scenarioName"),
        row.get("selectedAction"),
        row.get("summary"),
        " ".join(str(item) for item in _as_list(row.get("receiverActions"))),
        " ".join(str(item) for item in _as_list(row.get("failureReasons"))),
        " ".join(str(item) for item in _as_list(row.get("retrievalTags"))),
    )
    if not text_terms:
        return {}
    try:
        from policy_loader import operational_doctrine_index

        cases = operational_doctrine_index().get("action_cases", [])
    except Exception:
        return {}
    best: tuple[int, dict[str, Any]] = (0, {})
    for case in cases:
        if not isinstance(case, dict):
            continue
        case_terms = _case_tokens(
            case.get("id"),
            case.get("title"),
            " ".join(str(item) for item in _as_list(case.get("triggers"))),
            " ".join(str(item) for item in _as_list(case.get("state_signals"))),
            " ".join(str(item) for item in _as_list(case.get("recommended_primitives"))),
        )
        overlap = len(text_terms & case_terms)
        if overlap > best[0]:
            best = (overlap, case)
    if best[0] < 2 or not best[1]:
        return {}
    case = best[1]
    return {
        "caseId": case.get("id"),
        "case_id": case.get("id"),
        "caseLinkSource": "doctrine_inferred",
        "caseLinkConfidence": min(0.95, round(0.45 + best[0] * 0.12, 2)),
        "policyRefs": [str(item) for item in _as_list(case.get("policy_refs"))[:12]],
    }


def _policy_cases() -> list[dict[str, Any]]:
    try:
        from policy_loader import operational_doctrine_index

        return [case for case in operational_doctrine_index().get("action_cases", []) if isinstance(case, dict)]
    except Exception:
        return []


def _unique_strings(values: list[Any], limit: int = 12) -> list[str]:
    seen: set[str] = set()
    rows: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            rows.append(text)
        if len(rows) >= limit:
            break
    return rows


def _runtime_case_binding(row: dict[str, Any], explicit_policy_refs: list[str] | None = None) -> dict[str, Any]:
    explicit_refs = set(explicit_policy_refs or [])
    text_fields = [
        row.get("id"),
        row.get("scenarioName"),
        row.get("mode"),
        row.get("selectedAction"),
        row.get("summary"),
        " ".join(str(item) for item in _as_list(row.get("receiverActions"))),
        " ".join(str(item) for item in _as_list(row.get("failureReasons"))),
        " ".join(str(item) for item in _as_list(row.get("retrievalTags"))),
    ]
    blob = " ".join(str(item or "") for item in text_fields).replace("_", " ").replace("-", " ").lower()
    text_terms = _case_tokens(*text_fields)
    if not blob.strip() or not text_terms:
        return {}
    best: tuple[int, int, int, int, dict[str, Any]] = (0, 0, 0, 0, {})
    for case in _policy_cases():
        case_refs = {str(item) for item in _as_list(case.get("policy_refs"))}
        triggers = [str(item).strip().lower() for item in _as_list(case.get("triggers")) if str(item).strip()]
        title = str(case.get("title") or "").strip().lower()
        case_id = str(case.get("id") or "").strip().lower()
        phrase_hits = sum(1 for trigger in triggers if trigger and trigger in blob)
        title_hit = 1 if title and title in blob else 0
        id_hit = 1 if case_id and case_id.lower() in blob else 0
        ref_overlap = len(explicit_refs & case_refs)
        case_terms = _case_tokens(
            case.get("id"),
            case.get("title"),
            " ".join(str(item) for item in _as_list(case.get("triggers"))),
            " ".join(str(item) for item in _as_list(case.get("state_signals"))),
            " ".join(str(item) for item in _as_list(case.get("recommended_primitives"))),
            " ".join(str(item) for item in _as_list(case.get("blocked_actions"))),
        )
        token_overlap = len(text_terms & case_terms)
        score = id_hit * 18 + title_hit * 14 + phrase_hits * 7 + ref_overlap * 5 + token_overlap
        candidate = (score, phrase_hits + title_hit + id_hit, ref_overlap, token_overlap, case)
        if candidate[:4] > best[:4]:
            best = candidate
    score, strong_hits, ref_overlap, token_overlap, case = best
    if not case:
        return {}
    has_binding_proof = strong_hits >= 1 or ref_overlap >= 2 or (score >= 9 and token_overlap >= 3)
    if not has_binding_proof:
        return {}
    confidence = min(0.99, round(0.7 + min(score, 12) * 0.025 + min(ref_overlap, 3) * 0.02, 2))
    case_id = case.get("id")
    return {
        "caseId": case_id,
        "case_id": case_id,
        "caseLinkSource": "runtime_case_binding",
        "caseLinkConfidence": confidence,
        "caseLinkEvidence": {
            "score": score,
            "strongHits": strong_hits,
            "policyRefOverlap": ref_overlap,
            "tokenOverlap": token_overlap,
        },
        "policyRefs": [str(item) for item in _as_list(case.get("policy_refs"))[:12]],
    }


def _review_ids_for_case(case_id: str | None, limit: int = 12) -> list[str]:
    if not case_id:
        return []
    try:
        from live_feedback_loop import review_training_ledger

        payload = review_training_ledger(limit=160)
    except Exception:
        return []
    rows = [*_as_list(payload.get("open_reviews")), *_as_list(payload.get("rows"))]
    return _unique_strings(
        [
            row.get("id")
            for row in rows
            if isinstance(row, dict) and str(row.get("case_id") or row.get("caseId") or "") == case_id
        ],
        limit=limit,
    )


def _deep_get(value: Any, *path: str) -> Any:
    current = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _number(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct_from_ratio(value: Any) -> int | None:
    number = _number(value)
    if number is None:
        return None
    return round(number * 100) if 0 <= number <= 1 else round(number)


def _selected_action(payload: dict[str, Any], telemetry: dict[str, Any]) -> str:
    planner = _as_dict(telemetry.get("planner") or payload.get("planner"))
    selected = _as_dict(planner.get("selected_action"))
    learned = _as_dict(payload.get("learning_proof") or telemetry.get("learning_proof"))
    brief = _as_dict(payload.get("brief") or telemetry.get("brief"))
    return str(
        selected.get("label")
        or selected.get("action")
        or learned.get("after", {}).get("strategy")
        or _as_dict(payload.get("operator_response")).get("headline")
        or brief.get("operator_brief")
        or payload.get("selected_action")
        or "Agent operating action"
    )


def _eval_payload(payload: dict[str, Any], telemetry: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(telemetry.get("eval") or payload.get("eval"))


def _eval_score(payload: dict[str, Any], telemetry: dict[str, Any]) -> int | float | None:
    eval_payload = _eval_payload(payload, telemetry)
    scorecard = _as_dict(eval_payload.get("scorecard"))
    return _number(eval_payload.get("overall") or scorecard.get("overall"))


def _gate(payload: dict[str, Any], telemetry: dict[str, Any]) -> str:
    governance = _as_dict(telemetry.get("governance") or payload.get("governance") or payload.get("policy_gate"))
    eval_payload = _eval_payload(payload, telemetry)
    scorecard = _as_dict(eval_payload.get("scorecard"))
    return str(
        governance.get("gate_status")
        or _as_dict(governance.get("ledger_entry")).get("gateStatus")
        or scorecard.get("policy_gate_status")
        or eval_payload.get("status")
        or "checked"
    )


def _trace_id(payload: dict[str, Any], telemetry: dict[str, Any]) -> str | None:
    eval_payload = _eval_payload(payload, telemetry)
    trace_eval = _as_dict(eval_payload.get("gcp_trace_eval"))
    trace_contract = _as_dict(telemetry.get("trace_contract") or payload.get("trace_contract"))
    tool_trace = _as_dict(_as_dict(telemetry.get("digital_twin_tools") or payload.get("digital_twin_tools")).get("trace"))
    return trace_eval.get("trace_id") or trace_contract.get("trace_id") or trace_contract.get("eval_trace_id") or tool_trace.get("trace_id")


def _case_id(payload: dict[str, Any], telemetry: dict[str, Any]) -> str | None:
    candidates = [
        payload.get("caseId"),
        payload.get("case_id"),
        payload.get("expected_case_id"),
        telemetry.get("caseId"),
        telemetry.get("case_id"),
        telemetry.get("expected_case_id"),
        _deep_get(payload, "recommended_action", "matched_case_id"),
        _deep_get(telemetry, "recommended_action", "matched_case_id"),
        _deep_get(payload, "policy_reasoning", "primary_case_id"),
        _deep_get(telemetry, "policy_reasoning", "primary_case_id"),
        _deep_get(payload, "branchComparison", "caseId"),
        _deep_get(telemetry, "branchComparison", "caseId"),
    ]
    for candidate in candidates:
        if candidate:
            return str(candidate)
    return None


def _policy_refs(payload: dict[str, Any], telemetry: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for source in [payload, telemetry, _as_dict(payload.get("governance")), _as_dict(telemetry.get("governance"))]:
        values.extend(_as_list(source.get("policyRefs") or source.get("policy_refs") or source.get("policyFindings") or source.get("policy_findings")))
    scorecard = _as_dict(_eval_payload(payload, telemetry).get("scorecard"))
    values.extend(_as_list(scorecard.get("policy_refs") or scorecard.get("policyRefs") or scorecard.get("policyFindings")))
    seen: set[str] = set()
    refs: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            refs.append(text)
    return refs[:12]


def _review_session_ids(payload: dict[str, Any], telemetry: dict[str, Any]) -> list[str]:
    values = [
        payload.get("reviewSessionId"),
        payload.get("review_session_id"),
        payload.get("review_id"),
        telemetry.get("reviewSessionId"),
        telemetry.get("review_session_id"),
        telemetry.get("review_id"),
    ]
    values.extend(_as_list(payload.get("reviewSessionIds") or payload.get("review_session_ids")))
    values.extend(_as_list(telemetry.get("reviewSessionIds") or telemetry.get("review_session_ids")))
    seen: set[str] = set()
    ids: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            ids.append(text)
    return ids[:12]


def _memory_id(payload: dict[str, Any], telemetry: dict[str, Any]) -> str | None:
    trace_contract = _as_dict(telemetry.get("trace_contract") or payload.get("trace_contract"))
    memory_write = _as_dict(trace_contract.get("memory_write"))
    return memory_write.get("outcome_id") or payload.get("outcome_id") or telemetry.get("outcome_id")


def _dispatch_summary(delivery: dict[str, Any]) -> tuple[int, list[str]]:
    dispatches = _as_list(delivery.get("dispatches"))
    receiver_actions: list[str] = []
    for dispatch in dispatches[:12]:
        if not isinstance(dispatch, dict):
            continue
        payload = _as_dict(dispatch.get("payload"))
        label = dispatch.get("title") or dispatch.get("message") or dispatch.get("action") or payload.get("title") or payload.get("message") or "receiver payload"
        receiver_actions.append(f"{dispatch.get('channel', 'receiver')}: {label}")
    summary = _as_dict(delivery.get("summary"))
    count = _number(summary.get("total"))
    return int(count if count is not None else len(dispatches)), receiver_actions


def _tool_calls(payload: dict[str, Any], telemetry: dict[str, Any]) -> list[dict[str, Any]]:
    digital_twin = _as_dict(telemetry.get("digital_twin_tools") or payload.get("digital_twin_tools"))
    rows: list[dict[str, Any]] = []
    for call in _as_list(digital_twin.get("tool_calls"))[:12]:
        if not isinstance(call, dict):
            continue
        rows.append(
            {
                "tool": call.get("tool") or call.get("capability") or "runtime_tool",
                "status": call.get("status") or call.get("result_status") or "called",
                "agent": call.get("agent_id") or call.get("agent"),
            }
        )
    return rows


def _eval_dimensions(payload: dict[str, Any], telemetry: dict[str, Any]) -> list[dict[str, Any]]:
    eval_payload = _eval_payload(payload, telemetry)
    dimensions = _as_dict(eval_payload.get("dimension_scores") or _as_dict(eval_payload.get("hosted_eval")).get("payload_preview", {}).get("dimension_scores"))
    if not dimensions:
        dimensions = _as_dict(_as_dict(eval_payload.get("scorecard")).get("dimensions"))
    return [{"label": str(label), "score": _number(value), "detail": str(value)} for label, value in list(dimensions.items())[:10]]


def normalize_agent_ops_record(record: dict[str, Any]) -> dict[str, Any]:
    row = deepcopy(record)
    timestamp = str(row.get("timestamp") or row.get("createdAt") or _utc_now())
    selected_action = str(row.get("selectedAction") or row.get("selected_action") or "Agent operating action")
    scenario = str(row.get("scenarioName") or row.get("scenario_name") or row.get("scenario_key") or "park operations")
    signature = str(row.get("signature") or _stable_id("sig", {"timestamp": timestamp, "action": selected_action, "scenario": scenario, "eval": row.get("evalScore")}))
    explicit_policy_refs = [str(item) for item in _as_list(row.get("policyRefs") or row.get("policy_refs"))[:12]]
    existing_case_id = row.get("caseId") or row.get("case_id")
    existing_link_source = str(row.get("caseLinkSource") or row.get("case_link_source") or "")
    explicit_case_id = existing_case_id if existing_case_id and existing_link_source != "doctrine_inferred" else None
    runtime_binding = {} if explicit_case_id else _runtime_case_binding(row, explicit_policy_refs)
    inferred_case = {} if explicit_case_id or runtime_binding else _infer_case_from_doctrine(row)
    final_case_id = explicit_case_id or runtime_binding.get("caseId") or inferred_case.get("caseId")
    runtime_policy_refs = [str(item) for item in _as_list(runtime_binding.get("policyRefs"))[:12]]
    inferred_policy_refs = [str(item) for item in _as_list(inferred_case.get("policyRefs"))[:12]]
    explicit_review_ids = [str(item) for item in _as_list(row.get("reviewSessionIds") or row.get("review_session_ids"))[:12]]
    outcome_evidence = _as_dict(row.get("outcomeEvidence") or row.get("outcome_evidence"))
    if not outcome_evidence:
        episode = _as_dict(row.get("marketEpisode") or row.get("foodDemandEpisode") or row.get("episode"))
        actual_delta = _as_dict(row.get("actualDelta") or episode.get("actualDelta"))
        delivery = _as_dict(row.get("delivery") or episode.get("delivery"))
        response = _as_dict(delivery.get("response"))
        if actual_delta or response:
            outcome_evidence = {
                "status": "measured_delta" if actual_delta else "receiver_response",
                "actualDelta": actual_delta,
                "receiverAckCount": row.get("dispatchCount"),
                "takeRatePct": _pct_from_ratio(response.get("takeRate") or row.get("takeRatePct")),
                "followThroughPct": _pct_from_ratio(response.get("reactiveFollowThroughRate") or row.get("followThroughPct")),
                "memoryId": row.get("memoryId"),
            }
    row.update(
        {
            "id": str(row.get("id") or _stable_id("agent_run", signature)),
            "signature": signature,
            "timestamp": timestamp,
            "scenarioName": scenario,
            "mode": str(row.get("mode") or "live runtime"),
            "selectedAction": selected_action,
            "status": str(row.get("status") or "recorded"),
            "gate": str(row.get("gate") or "checked"),
            "evalScore": _number(row.get("evalScore")),
            "dispatchCount": int(_number(row.get("dispatchCount")) or 0),
            "takeRatePct": _pct_from_ratio(row.get("takeRatePct")),
            "followThroughPct": _pct_from_ratio(row.get("followThroughPct")),
            "memoryId": row.get("memoryId"),
            "traceId": row.get("traceId"),
            "caseId": final_case_id,
            "case_id": final_case_id,
            "caseLinkSource": (
                row.get("caseLinkSource")
                or row.get("case_link_source")
                or "explicit_payload"
                if explicit_case_id
                else runtime_binding.get("caseLinkSource")
                or row.get("caseLinkSource")
                or row.get("case_link_source")
                or inferred_case.get("caseLinkSource")
            ),
            "caseLinkConfidence": (
                row.get("caseLinkConfidence")
                or row.get("case_link_confidence")
                or 1
                if explicit_case_id
                else runtime_binding.get("caseLinkConfidence")
                or row.get("caseLinkConfidence")
                or row.get("case_link_confidence")
                or inferred_case.get("caseLinkConfidence")
            ),
            "caseLinkEvidence": row.get("caseLinkEvidence") or row.get("case_link_evidence") or runtime_binding.get("caseLinkEvidence"),
            "policyRefs": _unique_strings([*explicit_policy_refs, *runtime_policy_refs, *inferred_policy_refs], limit=12),
            "reviewSessionIds": explicit_review_ids,
            "reviewSessionIdSource": "explicit_payload" if explicit_review_ids else "not_attached",
            "outcomeEvidence": outcome_evidence,
            "summary": str(row.get("summary") or "Agent action recorded for later trace and eval inspection."),
            "receiverActions": [str(item) for item in _as_list(row.get("receiverActions"))[:12]],
            "toolCalls": [item for item in _as_list(row.get("toolCalls"))[:12] if isinstance(item, dict)],
            "traceEvents": [item for item in _as_list(row.get("traceEvents"))[:20] if isinstance(item, dict)],
            "evalDimensions": [item for item in _as_list(row.get("evalDimensions"))[:10] if isinstance(item, dict)],
            "failureReasons": [str(item) for item in _as_list(row.get("failureReasons"))[:8]],
            "source": str(row.get("source") or "agent_ops_ledger"),
        }
    )
    tags = {
        scenario.lower(),
        selected_action.lower(),
        row["mode"].lower(),
        row["gate"].lower(),
        *(str(item.get("tool", "")).lower() for item in row["toolCalls"]),
        *(reason.lower() for reason in row["failureReasons"]),
    }
    row["retrievalTags"] = sorted(tag for tag in tags if tag)
    return row


def build_ledger_record_from_run(payload: dict[str, Any], *, message: str = "", mode: str = "", kind: str = "agent_run") -> dict[str, Any]:
    telemetry = _as_dict(payload.get("run_telemetry") or payload)
    delivery = _as_dict(telemetry.get("delivery") or payload.get("delivery"))
    response = _as_dict(delivery.get("response"))
    dispatch_count, receiver_actions = _dispatch_summary(delivery)
    selected_action = _selected_action(payload, telemetry)
    eval_payload = _eval_payload(payload, telemetry)
    scorecard = _as_dict(eval_payload.get("scorecard"))
    trace_events = _as_list(payload.get("traceEvents") or payload.get("trace_events") or telemetry.get("traceEvents"))
    row = {
        "id": payload.get("run_receipt", {}).get("id") or payload.get("run_id"),
        "signature": _stable_id(
            "sig",
            {
                "receipt": payload.get("run_receipt", {}).get("id"),
                "outcome": payload.get("outcome_id") or telemetry.get("outcome_id"),
                "trace": _trace_id(payload, telemetry),
                "action": selected_action,
                "eval": _eval_score(payload, telemetry),
                "dispatches": dispatch_count,
            },
        ),
        "timestamp": _utc_now(),
        "scenarioName": payload.get("scenario_key") or telemetry.get("requested_scenario_key") or kind,
        "mode": mode or kind,
        "selectedAction": selected_action,
        "status": response.get("status") or response.get("state") or eval_payload.get("status") or payload.get("status") or "recorded",
        "gate": _gate(payload, telemetry),
        "evalScore": _eval_score(payload, telemetry),
        "dispatchCount": dispatch_count,
        "takeRatePct": _pct_from_ratio(response.get("takeRate")),
        "followThroughPct": _pct_from_ratio(response.get("reactiveFollowThroughRate")),
        "memoryId": _memory_id(payload, telemetry),
        "traceId": _trace_id(payload, telemetry),
        "caseId": _case_id(payload, telemetry),
        "case_id": _case_id(payload, telemetry),
        "caseLinkSource": "explicit_payload" if _case_id(payload, telemetry) else None,
        "caseLinkConfidence": 1 if _case_id(payload, telemetry) else None,
        "policyRefs": _policy_refs(payload, telemetry),
        "reviewSessionIds": _review_session_ids(payload, telemetry),
        "outcomeEvidence": {
            "dispatchStatus": response.get("status") or response.get("state"),
            "receiverAckCount": dispatch_count,
            "takeRatePct": _pct_from_ratio(response.get("takeRate")),
            "followThroughPct": _pct_from_ratio(response.get("reactiveFollowThroughRate")),
            "memoryId": _memory_id(payload, telemetry),
        },
        "summary": payload.get("run_result") or _as_dict(telemetry.get("outcome")).get("state_impact", {}).get("headline") or message or "Agent action recorded for later trace and eval inspection.",
        "receiverActions": receiver_actions,
        "toolCalls": _tool_calls(payload, telemetry),
        "traceEvents": trace_events,
        "evalDimensions": _eval_dimensions(payload, telemetry),
        "failureReasons": _as_list(eval_payload.get("failure_reasons") or scorecard.get("failure_reasons"))[:8],
        "source": f"backend:{kind}",
    }
    return normalize_agent_ops_record(row)


def read_agent_ops_ledger(limit: int = 50, query: str | None = None) -> dict[str, Any]:
    rows = _read_rows()
    if query:
        terms = [term.lower() for term in query.split() if term.strip()]
        if terms:
            rows = [row for row in rows if all(term in _compact_json(row).lower() for term in terms)]
    rows = rows[: max(1, min(limit, MAX_LEDGER_ROWS))]
    return {
        "status": "ready",
        "mode": "backend_agent_ops_ledger",
        "count": len(rows),
        "items": deepcopy(rows),
        "storage": {"path": str(_ledger_path()), "maxRows": MAX_LEDGER_ROWS},
        "agent_memory_contract": {
            "retrievable_by": ["proact", "planning_agent", "memory_ops_agent", "gcp_eval_judge_agent"],
            "fields": ["selectedAction", "gate", "evalScore", "receiverActions", "toolCalls", "traceEvents", "failureReasons"],
        },
    }


def _first_location(state: dict[str, Any], location_id: str) -> dict[str, Any]:
    inventory = _as_dict(state.get("foodInventory"))
    for location in _as_list(inventory.get("locations")):
        if isinstance(location, dict) and str(location.get("id")) == location_id:
            return location
    return _as_dict(_as_list(inventory.get("locations"))[0]) if inventory.get("locations") else {}


def _recent_matching_action(rows: list[dict[str, Any]], terms: list[str]) -> dict[str, Any] | None:
    lowered_terms = [term.lower() for term in terms]
    for row in rows:
        text = _compact_json(
            {
                "action": row.get("selectedAction"),
                "summary": row.get("summary"),
                "receivers": row.get("receiverActions"),
                "scenario": row.get("scenarioName"),
            }
        ).lower()
        if any(term in text for term in lowered_terms):
            return row
    return None


def _action_streak(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"count": 0, "action": None, "status": "empty"}
    latest = str(rows[0].get("selectedAction") or "")
    count = 0
    for row in rows:
        if str(row.get("selectedAction") or "") != latest:
            break
        count += 1
    return {
        "count": count,
        "action": latest or None,
        "status": "repetitive" if count >= 3 else "varied",
    }


def _avg(values: list[float | int]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _clamp(value: float | int, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, round(float(value))))


def _build_eval_breakdown(
    *,
    rows: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    latest: dict[str, Any],
    repeated_action_warning: bool,
    complaint_risk: int,
    traffic_risk: int,
    food_backlog: int,
    food_eta: int,
    food_pressure: int,
    recovery_pressure: int,
) -> dict[str, Any]:
    gate = str(latest.get("gate") or "").lower()
    trace_events = _as_list(latest.get("traceEvents"))
    tool_calls = _as_list(latest.get("toolCalls"))
    receiver_actions = _as_list(latest.get("receiverActions"))
    failure_reasons = _as_list(latest.get("failureReasons"))
    latest_eval = _number(latest.get("evalScore"))
    unresolved_count = len(issues)
    critical_count = sum(1 for issue in issues if issue.get("severity") == "critical")

    safety_score = 92 if gate in {"passed", "allowed", "checked", "recorded"} or "pass" in gate else 72
    if "block" in gate or "fail" in gate:
        safety_score = 48
    if failure_reasons:
        safety_score -= min(24, len(failure_reasons) * 8)

    base_effectiveness = latest_eval if latest_eval is not None else 76
    effectiveness_score = _clamp(base_effectiveness - unresolved_count * 8 - critical_count * 7)
    adaptation_score = 42 if repeated_action_warning else 78 if rows else 55
    if not unresolved_count and rows:
        adaptation_score = 88
    fairness_score = _clamp(100 - complaint_risk + (8 if complaint_risk < 55 else 0))
    trace_score = 30
    if trace_events:
        trace_score += 20
    if tool_calls:
        trace_score += 20
    if receiver_actions:
        trace_score += 15
    if latest.get("memoryId"):
        trace_score += 10
    if latest.get("traceId"):
        trace_score += 5
    trace_score = _clamp(trace_score)

    dimensions = [
        {
            "id": "safety",
            "label": "Safety and policy",
            "score": _clamp(safety_score),
            "status": "pass" if safety_score >= 75 else "blocked" if safety_score < 55 else "watch",
            "why": f"Policy gate is {latest.get('gate') or 'not recorded'}; {len(failure_reasons)} failure reasons attached.",
        },
        {
            "id": "effectiveness",
            "label": "Effectiveness",
            "score": effectiveness_score,
            "status": "pass" if effectiveness_score >= 80 else "watch" if effectiveness_score >= 60 else "needs_action",
            "why": f"{unresolved_count} unresolved risks remain after the latest action.",
        },
        {
            "id": "adaptation",
            "label": "Adaptation",
            "score": _clamp(adaptation_score),
            "status": "needs_strategy_shift" if repeated_action_warning else "pass" if adaptation_score >= 75 else "watch",
            "why": "Same action is repeating while risk remains open." if repeated_action_warning else "No repeated-action failure pattern in the latest window.",
        },
        {
            "id": "fairness",
            "label": "Fairness",
            "score": fairness_score,
            "status": "pass" if fairness_score >= 75 else "watch" if fairness_score >= 55 else "needs_action",
            "why": f"Public complaint risk is {complaint_risk}%.",
        },
        {
            "id": "trace_completeness",
            "label": "Trace completeness",
            "score": trace_score,
            "status": "pass" if trace_score >= 80 else "watch" if trace_score >= 60 else "missing_evidence",
            "why": f"{len(tool_calls)} tool calls, {len(receiver_actions)} receiver actions, {len(trace_events)} trace events stored.",
        },
    ]
    overall = _clamp(sum(item["score"] for item in dimensions) / len(dimensions))
    if repeated_action_warning:
        verdict = "Needs strategy shift"
    elif any(item["status"] == "blocked" for item in dimensions):
        verdict = "Unsafe / blocked"
    elif unresolved_count:
        verdict = "Pass with watch items"
    else:
        verdict = "Pass"

    weakest = sorted(dimensions, key=lambda item: item["score"])[:2]
    return {
        "overallScore": overall,
        "verdict": verdict,
        "pass": verdict == "Pass",
        "dimensions": dimensions,
        "weakestDimensions": weakest,
        "outcomeDelta": {
            "measurementStatus": "inferred_from_current_state",
            "gap": "Before/after snapshots per action are not yet stored, so this eval uses current unresolved risk as the outcome signal.",
            "currentSignals": {
                "foodBacklog": food_backlog,
                "foodEtaMinutes": food_eta,
                "foodPressurePct": food_pressure,
                "fairnessComplaintRiskPct": complaint_risk,
                "eventTrafficRiskPct": traffic_risk,
                "guestRecoveryPressurePct": recovery_pressure,
            },
            "proofLine": f"Current unresolved pressure: food {food_backlog} orders / {food_eta}m ETA, fairness {complaint_risk}%, event traffic {traffic_risk}%, recovery {recovery_pressure}%.",
        },
        "judgeNotes": [
            "Eval is now explainable by dimension instead of a single opaque score.",
            "The main remaining proof gap is measured before/after state delta per action.",
            "Repeated action under unresolved risk lowers adaptation score.",
        ],
    }


def build_operational_backlog(state: dict[str, Any] | None = None, *, limit: int = 16) -> dict[str, Any]:
    state = _as_dict(state)
    rows = read_agent_ops_ledger(limit=limit).get("items", [])
    issues: list[dict[str, Any]] = []
    operating_clock = _as_dict(state.get("operatingClock"))
    food_lifecycle = _as_dict(operating_clock.get("foodRetailLifecycle"))
    fairness = _as_dict(operating_clock.get("accessFairness"))
    event_schedule = _as_dict(operating_clock.get("eventSchedule"))
    guest_feedback = _as_dict(operating_clock.get("guestFeedbackLoop"))
    staff_lifecycle = _as_dict(operating_clock.get("staffLifecycle"))
    planning_agent = _as_dict(state.get("planningAgent"))
    park_ops = _as_dict(state.get("parkOps"))
    weather = _as_dict(state.get("weather"))
    energy = _as_dict(state.get("energy"))
    staffing = _as_dict(state.get("staffing"))
    guest_care = _as_dict(state.get("guestCare"))
    guest_flow = _as_dict(state.get("guestFlow"))
    food_a = _first_location(state, "foodCourt1")
    paths = [path for path in _as_list(guest_flow.get("paths")) if isinstance(path, dict)]
    rides = [ride for ride in _as_list(guest_flow.get("rides")) if isinstance(ride, dict)]
    represented_guests = _represented_guests(state)
    low_attendance = 0 <= represented_guests < LOW_ATTENDANCE_CROWD_BACKLOG_FLOOR
    max_path_congestion = int(max((_validated_path_congestion(path, represented_guests) for path in paths), default=0))
    storm_risk = int(_number(weather.get("stormRisk")) or 0)
    grid_load = int(_number(energy.get("gridLoadPercent")) or 0)
    utility_price = int(_number(energy.get("utilityPricePerMwh")) or 0)
    avg_satisfaction_value = _number(guest_flow.get("avgSatisfaction"))
    avg_satisfaction = int(avg_satisfaction_value if avg_satisfaction_value is not None else 82)
    complaint_rate = int(_number(guest_care.get("complaintRatePct")) or 0)
    open_care_cases = int(_number(guest_care.get("openCases")) or 0)
    planning_readiness_value = _number(planning_agent.get("readinessPct"))
    planning_readiness = int(planning_readiness_value if planning_readiness_value is not None else 82)
    break_pressure = int(_number(staff_lifecycle.get("breakPressurePct")) or 0)
    open_callouts = int(_number(staffing.get("openCallouts")) or 0)
    throughput_gap = int(sum(_number(ride.get("throughputGap")) or 0 for ride in rides))

    def append_issue(
        issue_id: str,
        domain: str,
        title: str,
        severity: str,
        current: str,
        target: str,
        recommended_next: str,
        terms: list[str],
        evidence: list[str],
        *,
        executive_domain: str = "operations",
        business_impact: str | None = None,
    ) -> None:
        action = _recent_matching_action(rows, terms)
        issues.append(
            {
                "id": issue_id,
                "executiveDomain": executive_domain,
                "domain": domain,
                "title": title,
                "severity": severity,
                "status": "unresolved",
                "current": current,
                "target": target,
                "businessImpact": business_impact,
                "lastAction": action.get("selectedAction") if action else None,
                "lastEvalScore": action.get("evalScore") if action else None,
                "lastActionAt": action.get("timestamp") if action else None,
                "recommendedNext": recommended_next,
                "evidence": evidence,
            }
        )

    food_backlog = int(_number(food_a.get("mobileOrderBacklog")) or 0)
    food_eta = int(_number(food_a.get("pickupEtaMinutes")) or 0)
    food_pressure = int(_number(food_lifecycle.get("mobileOrderBacklogPressurePct")) or 0)
    if food_backlog >= 140 or food_eta >= 25 or food_pressure >= 65:
        append_issue(
            "food-court-a-backlog",
            "Food",
            "Food Court A backlog remains unresolved",
            "critical" if food_backlog >= 400 or food_eta >= 45 or food_pressure >= 90 else "warning",
            f"{food_backlog} orders / {food_eta}m ETA / {food_pressure}% pressure",
            "<140 orders, <25m ETA, <65% pressure",
            "Change strategy if repeated proactive food action has not reduced ETA: cap new mobile orders, redirect only eligible items, open secondary pickup, and restock drinks.",
            ["food", "backlog", "mobile", "pickup", "guest-care"],
            [
                f"Food Court A mobileOrderBacklog={food_backlog}",
                f"Food Court A pickupEtaMinutes={food_eta}",
                f"mobileOrderBacklogPressurePct={food_pressure}",
            ],
            executive_domain="operations",
            business_impact="Food backlog is an operations constraint and a finance/customer-experience leak because refunds and complaints rise when ETA slips.",
        )

    complaint_risk = int(_number(fairness.get("publicComplaintRiskPct")) or 0)
    if complaint_risk >= 35:
        append_issue(
            "fast-lane-fairness-risk",
            "Fairness",
            "VIP / Fast Lane complaint risk is still visible",
            "critical" if complaint_risk >= 70 else "warning",
            f"{complaint_risk}% complaint risk / fairness score {fairness.get('perceivedFairnessScore', '--')}",
            "<35% complaint risk with transparent lane-mix explanation",
            "Keep aggregate lane caps active, explain standby delay cause, and watch if complaint risk falls after the next cycle.",
            ["fairness", "vip", "fast lane", "standby", "complaint"],
            [
                f"premiumLaneSharePct={fairness.get('premiumLaneSharePct', '--')}",
                f"standbyLaneSharePct={fairness.get('standbyLaneSharePct', '--')}",
                f"standbyDelayDeltaMins={fairness.get('standbyDelayDeltaMins', '--')}",
            ],
            executive_domain="customer_experience",
            business_impact="Access-lane fairness is a trust and retention risk, not only a queue-balancing problem.",
        )

    raw_traffic_risk = int(_number(event_schedule.get("eventTrafficRiskPct")) or 0)
    traffic_risk = 0 if low_attendance else raw_traffic_risk
    active_wave = str(event_schedule.get("activeWave") or "unknown")
    if traffic_risk >= 50:
        append_issue(
            "showtime-traffic-wave",
            "Showtime",
            "Showtime crowd wave may still create congestion",
            "critical" if traffic_risk >= 80 else "warning",
            f"{traffic_risk}% traffic risk during {active_wave}",
            "<50% event traffic risk after route staggering",
            "Stagger exits, pre-stage staff at merge points, and compare post-wave crowd density before dispatching another broad redirect.",
            ["showtime", "parade", "fireworks", "traffic", "congestion", "crowd"],
            [
                f"activeWave={active_wave}",
                f"nextEvent={_as_dict(event_schedule.get('nextEvent')).get('name', '--')}",
                f"eventTrafficRiskPct={traffic_risk}",
                f"representedGuests={represented_guests}",
            ],
            executive_domain="planning",
            business_impact="Timed show waves stress tomorrow's planning assumptions because crowd release, staffing, and route capacity are coupled.",
        )

    recovery_pressure = int(_number(park_ops.get("guestRecoveryPressure")) or 0)
    if recovery_pressure >= 60:
        append_issue(
            "guest-recovery-pressure",
            "Guest Care",
            "Guest recovery pressure remains elevated",
            "critical" if recovery_pressure >= 85 else "warning",
            f"{recovery_pressure}% recovery pressure",
            "<60% recovery pressure with lower complaint load",
            "Measure whether guest-care messages are reducing support contacts; escalate only if pressure keeps rising.",
            ["guest", "recovery", "care", "complaint"],
            [f"guestRecoveryPressure={recovery_pressure}"],
            executive_domain="customer_experience",
            business_impact="Guest recovery pressure is a service-quality and brand-trust risk that should be summarized for human judgement.",
        )

    safety_pressure = max(storm_risk, max_path_congestion, break_pressure)
    if safety_pressure >= 70:
        append_issue(
            "safety-access-readiness",
            "Safety",
            "Safety and access readiness needs active supervision",
            "critical" if safety_pressure >= 88 or storm_risk >= 85 else "warning",
            f"storm {storm_risk}% / path congestion {max_path_congestion}% / break pressure {break_pressure}%",
            "<70% combined safety pressure with protected access routes and staffed crossings",
            "Pre-stage safety/crowd leads, keep emergency and service lanes clear, and require policy review before broad crowd movement.",
            ["safety", "storm", "access", "medical", "security", "crowd", "path"],
            [
                f"stormRisk={storm_risk}",
                f"maxPathCongestion={max_path_congestion}",
                f"representedGuests={represented_guests}",
                f"breakPressurePct={break_pressure}",
                f"medicalTeams={staffing.get('medicalTeams', '--')}",
                f"securityTeams={staffing.get('securityTeams', '--')}",
            ],
            executive_domain="safety",
            business_impact="Safety posture is the hard gate for all other optimization; finance and satisfaction wins are invalid if access routes degrade.",
        )

    estimated_finance_exposure = int(
        open_care_cases * 22
        + max(0, food_backlog - 120) * 4
        + max(0, grid_load - 85) * max(250, utility_price * 2)
        + max(0, 72 - avg_satisfaction) * 900
        + throughput_gap * 6
        + max(0, open_callouts - 16) * 180
    )
    if estimated_finance_exposure >= 12000:
        append_issue(
            "finance-exposure-watch",
            "Finance",
            "Revenue, labor, energy, and recovery exposure is material",
            "critical" if estimated_finance_exposure >= 30000 else "warning",
            f"${estimated_finance_exposure:,} estimated exposure / grid {grid_load}% / {open_care_cases} care cases",
            "<$12k exposure with lower comp/refund pressure and lower demand-charge risk",
            "Compare lower-cost interventions: targeted care messaging, menu suppression, labor redeploy, and energy load protection before broad incentives.",
            ["finance", "revenue", "refund", "compensation", "labor", "energy", "margin", "cost"],
            [
                f"estimatedExposureUsd={estimated_finance_exposure}",
                f"openCareCases={open_care_cases}",
                f"gridLoadPercent={grid_load}",
                f"utilityPricePerMwh={utility_price}",
                f"throughputGapPerHour={throughput_gap}",
            ],
            executive_domain="finance",
            business_impact="The finance agent should quantify tradeoffs instead of letting every incident default to guest offers or extra labor.",
        )

    if planning_readiness < 82 or traffic_risk >= 65:
        append_issue(
            "planning-horizon-risk",
            "Planning",
            "Multi-wave planning confidence is below executive threshold",
            "critical" if planning_readiness < 65 or traffic_risk >= 85 else "warning",
            f"{planning_readiness}% readiness / {traffic_risk}% event traffic risk",
            ">=82% readiness with a rehearsed plan before the next timed wave",
            "Refresh the 180-minute plan, run a counterfactual against the next showtime wave, and choose the route/staff plan before the decision deadline.",
            ["planning", "showtime", "forecast", "rehearsal", "counterfactual", "capacity"],
            [
                f"plannerHorizonMinutes={planning_agent.get('plannerHorizonMinutes', '--')}",
                f"readinessPct={planning_readiness}",
                f"nextDecisionDeadlineMinutes={_as_dict(planning_agent.get('activePlan')).get('nextDecisionDeadlineMinutes', '--')}",
                f"eventTrafficRiskPct={traffic_risk}",
                f"representedGuests={represented_guests}",
            ],
            executive_domain="planning",
            business_impact="Planning risk is the signal that the park is reacting one incident at a time instead of operating the day as a connected system.",
        )

    customer_pressure = max(recovery_pressure, int(_number(guest_feedback.get("careCaseAccumulationPct")) or 0), complaint_risk)
    if customer_pressure >= 58 or complaint_rate >= 14 or avg_satisfaction < 72:
        append_issue(
            "customer-experience-trust-risk",
            "Customer Experience",
            "Customer trust is deteriorating across care, sentiment, and fairness",
            "critical" if customer_pressure >= 82 or avg_satisfaction < 62 else "warning",
            f"{avg_satisfaction}% satisfaction / {complaint_rate}% complaint rate / {customer_pressure}% pressure",
            ">=72% satisfaction, <14% complaint rate, and lower fairness/recovery pressure",
            "Summarize top drivers, prepare transparent guest messaging, and route only policy-safe care offers for human approval.",
            ["customer", "guest", "sentiment", "complaint", "fairness", "care", "experience"],
            [
                f"avgSatisfaction={avg_satisfaction}",
                f"complaintRatePct={complaint_rate}",
                f"careCaseAccumulationPct={guest_feedback.get('careCaseAccumulationPct', '--')}",
                f"sentimentMomentum={guest_feedback.get('sentimentMomentum', '--')}",
            ],
            executive_domain="customer_experience",
            business_impact="Customer experience turns operational delay into brand damage when messaging, fairness, and recovery are not coordinated.",
        )

    streak = _action_streak(rows)
    scores = [score for score in (_number(row.get("evalScore")) for row in rows) if score is not None]
    latest = rows[0] if rows else {}
    unresolved_count = len(issues)
    repeated_action_warning = streak["status"] == "repetitive" and unresolved_count > 0
    eval_breakdown = _build_eval_breakdown(
        rows=rows,
        issues=issues,
        latest=latest,
        repeated_action_warning=repeated_action_warning,
        complaint_risk=complaint_risk,
        traffic_risk=traffic_risk,
        food_backlog=food_backlog,
        food_eta=food_eta,
        food_pressure=food_pressure,
        recovery_pressure=recovery_pressure,
    )
    issue_counts_by_domain: dict[str, int] = {}
    for issue in issues:
        executive_domain = str(issue.get("executiveDomain") or "operations")
        issue_counts_by_domain[executive_domain] = issue_counts_by_domain.get(executive_domain, 0) + 1

    operations_score = _clamp(100 - issue_counts_by_domain.get("operations", 0) * 14 - max(0, food_pressure - 65) * 0.45)
    safety_score = _clamp(100 - max(0, safety_pressure - 55) * 1.2)
    finance_score = _clamp(100 - min(70, estimated_finance_exposure / 650))
    planning_score = _clamp((planning_readiness or 72) - max(0, traffic_risk - 55) * 0.3)
    customer_score = _clamp(avg_satisfaction - complaint_rate * 0.6 - max(0, complaint_risk - 35) * 0.25)

    def domain_status(score: float, issue_count: int) -> str:
        if score < 55:
            return "critical"
        if score < 72 or issue_count:
            return "watch"
        return "stable"

    enterprise_domains = [
        {
            "id": "operations",
            "label": "Operations",
            "score": round(operations_score),
            "status": domain_status(operations_score, issue_counts_by_domain.get("operations", 0)),
            "agent": "Operations Agent",
            "current": f"{food_pressure}% food pressure, {throughput_gap}/hr ride capacity gap",
            "target": "Keep queues, food, staff, and ride throughput inside operating thresholds.",
            "recommendedMove": "Resolve the highest operational bottleneck before adding incentives or broad reroutes.",
            "ticketsOpen": issue_counts_by_domain.get("operations", 0),
            "leadingSignals": [f"foodPressure={food_pressure}", f"throughputGap={throughput_gap}", f"openCallouts={open_callouts}"],
        },
        {
            "id": "safety",
            "label": "Safety",
            "score": round(safety_score),
            "status": domain_status(safety_score, issue_counts_by_domain.get("safety", 0)),
            "agent": "Safety/Policy Agent",
            "current": f"{storm_risk}% storm risk, {max_path_congestion}% max path congestion",
            "target": "Protect access routes, emergency response, and policy gates before optimization.",
            "recommendedMove": "Pre-stage safety coverage and block actions that increase service-lane or access risk.",
            "ticketsOpen": issue_counts_by_domain.get("safety", 0),
            "leadingSignals": [f"stormRisk={storm_risk}", f"maxPathCongestion={max_path_congestion}", f"breakPressure={break_pressure}"],
        },
        {
            "id": "finance",
            "label": "Finance",
            "score": round(finance_score),
            "status": domain_status(finance_score, issue_counts_by_domain.get("finance", 0)),
            "agent": "Finance Agent",
            "current": f"${estimated_finance_exposure:,} exposure, grid {grid_load}%",
            "target": "Minimize refund, labor, food, energy, and lost-throughput exposure without hurting trust.",
            "recommendedMove": "Rank interventions by cost-to-risk reduction before approving compensation or extra labor.",
            "ticketsOpen": issue_counts_by_domain.get("finance", 0),
            "leadingSignals": [f"exposureUsd={estimated_finance_exposure}", f"careCases={open_care_cases}", f"utilityPrice={utility_price}"],
        },
        {
            "id": "planning",
            "label": "Planning",
            "score": round(planning_score),
            "status": domain_status(planning_score, issue_counts_by_domain.get("planning", 0)),
            "agent": "Planning Agent",
            "current": f"{planning_readiness}% plan readiness, {traffic_risk}% event traffic risk",
            "target": "Run the day as a connected 180-minute plan, not isolated incident responses.",
            "recommendedMove": "Refresh the showtime, staffing, and route plan before the next decision deadline.",
            "ticketsOpen": issue_counts_by_domain.get("planning", 0),
            "leadingSignals": [f"readiness={planning_readiness}", f"trafficRisk={traffic_risk}", f"activeWave={active_wave}"],
        },
        {
            "id": "customer_experience",
            "label": "Customer Experience",
            "score": round(customer_score),
            "status": domain_status(customer_score, issue_counts_by_domain.get("customer_experience", 0)),
            "agent": "Customer Experience Agent",
            "current": f"{avg_satisfaction}% satisfaction, {complaint_rate}% complaint rate",
            "target": "Keep trust high with transparent, policy-safe, segment-level care.",
            "recommendedMove": "Summarize top guest drivers and send only bounded, approved recovery options.",
            "ticketsOpen": issue_counts_by_domain.get("customer_experience", 0),
            "leadingSignals": [f"avgSatisfaction={avg_satisfaction}", f"complaintRate={complaint_rate}", f"fairnessRisk={complaint_risk}"],
        },
    ]
    weakest_domain = min(enterprise_domains, key=lambda item: item["score"])
    domain_by_id = {str(domain["id"]): domain for domain in enterprise_domains}
    safety_is_constraint = safety_score < 55 or safety_pressure >= 88
    planning_is_constraint = planning_score < 60 or traffic_risk >= 70
    customer_is_constraint = customer_score < 58 or complaint_risk >= 55
    finance_is_constraint = finance_score < 68 or estimated_finance_exposure >= 16000
    operations_is_constraint = operations_score < 72 or food_pressure >= 85 or throughput_gap >= 900
    single_agent_score = round(
        _clamp(
            78
            - (16 if safety_is_constraint else 0)
            - (11 if planning_is_constraint else 0)
            - (9 if customer_is_constraint else 0)
            - (7 if finance_is_constraint else 0)
            - (6 if operations_is_constraint else 0)
        )
    )
    council_score = round(
        _clamp(
            single_agent_score
            + 18
            + (7 if safety_is_constraint else 0)
            + (6 if planning_is_constraint else 0)
            + (5 if customer_is_constraint else 0)
        )
    )
    lead_domain_id = "safety" if safety_is_constraint else str(weakest_domain["id"])
    lead_domain = domain_by_id.get(lead_domain_id, weakest_domain)
    agent_council = {
        "mode": "multi_agent_constraint_negotiation",
        "leadAgent": lead_domain.get("agent"),
        "leadDomain": lead_domain.get("label"),
        "selectedAction": (
            "Safety-led constrained route split: protect access lanes, stage crowd leads, throttle broad reroutes, then run targeted guest-care messaging."
            if lead_domain_id == "safety"
            else f"{lead_domain.get('label')} led coordinated action: {lead_domain.get('recommendedMove')}"
        ),
        "whyMultiAgent": "The council exposes hidden constraints before dispatch: safety can veto operations, planning can time the move around show waves, finance can bound compensation, and customer experience can prevent fairness blowback.",
        "singleAgentBaseline": {
            "agent": "Single Operations Agent",
            "recommendedAction": "Reduce the biggest visible queue by pushing guests toward lower-density zones and issuing broad recovery messaging.",
            "expectedScore": single_agent_score,
            "missedRisks": [
                "Could push guests through already constrained access paths.",
                "May collide with parade or fireworks release timing.",
                "May overpromise compensation without finance or policy review.",
                "Does not explain VIP/Fast Lane fairness pressure to standby guests.",
            ],
        },
        "councilScore": council_score,
        "advantage": {
            "scoreLift": max(0, council_score - single_agent_score),
            "hiddenRisksFound": sum(1 for flag in [safety_is_constraint, planning_is_constraint, customer_is_constraint, finance_is_constraint] if flag),
            "conflictsResolved": sum(1 for issue_count in issue_counts_by_domain.values() if issue_count),
            "policyBlocks": 1 if safety_is_constraint else 0,
            "handoffCount": 5,
        },
        "rounds": [
            {
                "step": 1,
                "agent": "Scan Agent",
                "role": "observe",
                "stance": "escalate",
                "finding": f"{unresolved_count} unresolved risks across {len(issue_counts_by_domain)} executive domains.",
                "evidence": [issue["title"] for issue in issues[:3]],
            },
            {
                "step": 2,
                "agent": "Operations Agent",
                "role": "react",
                "stance": "propose",
                "finding": f"Food pressure {food_pressure}% and throughput gap {throughput_gap}/hr need capacity relief.",
                "evidence": [f"foodPressure={food_pressure}", f"throughputGap={throughput_gap}", f"openCallouts={open_callouts}"],
            },
            {
                "step": 3,
                "agent": "Safety/Policy Agent",
                "role": "veto",
                "stance": "block" if safety_is_constraint else "allow",
                "finding": f"Safety pressure {safety_pressure}% sets the hard boundary for route and dispatch decisions.",
                "evidence": [f"stormRisk={storm_risk}", f"maxPathCongestion={max_path_congestion}", f"breakPressure={break_pressure}"],
            },
            {
                "step": 4,
                "agent": "Planning Agent",
                "role": "forecast",
                "stance": "challenge" if planning_is_constraint else "allow",
                "finding": f"Plan readiness {planning_readiness}% and event traffic risk {traffic_risk}% change when the action should run.",
                "evidence": [f"activeWave={active_wave}", f"trafficRisk={traffic_risk}", f"readiness={planning_readiness}"],
            },
            {
                "step": 5,
                "agent": "Finance Agent",
                "role": "tradeoff",
                "stance": "cap" if finance_is_constraint else "allow",
                "finding": f"Estimated exposure is ${estimated_finance_exposure:,}; broad compensation needs a bounded approval path.",
                "evidence": [f"gridLoad={grid_load}", f"utilityPrice={utility_price}", f"careCases={open_care_cases}"],
            },
            {
                "step": 6,
                "agent": "Customer Experience Agent",
                "role": "trust",
                "stance": "revise" if customer_is_constraint else "allow",
                "finding": f"Fairness risk {complaint_risk}% requires transparent standby/Fast Lane messaging before guest-facing action.",
                "evidence": [f"avgSatisfaction={avg_satisfaction}", f"complaintRate={complaint_rate}", f"fairnessRisk={complaint_risk}"],
            },
            {
                "step": 7,
                "agent": "Policy Arbiter",
                "role": "decide",
                "stance": "approve_with_constraints",
                "finding": "Final action is narrowed to reversible moves with explicit safety, timing, cost, and trust constraints.",
                "evidence": ["bounded dispatch", "policy gate", "memory write", "post-action eval"],
            },
        ],
        "traceContract": {
            "beforeDispatch": ["scan signals", "domain objections", "counterfactual score", "policy gate"],
            "afterDispatch": ["receiver acknowledgement", "state delta", "guest response", "eval score", "memory update"],
            "mongoRecord": "agent_council_episode",
        },
    }
    raw_candidates = [
        {
            "id": "ops_broad_reroute",
            "label": "Broad operations reroute",
            "proposedBy": "Operations Agent",
            "action": "Push guests away from the highest queue pressure and publish a broad recovery message.",
            "predictedDeltas": {
                "queueReliefPct": min(32, max(8, food_pressure // 4 + throughput_gap // 240)),
                "accessRiskDelta": 16 if max_path_congestion >= 85 else 7,
                "costUsd": 6800 + max(0, food_backlog - 160) * 8,
                "trustDeltaPct": 3 if complaint_risk < 45 else -6,
                "planRiskDelta": 9 if traffic_risk >= 55 else 2,
                "guestMinutesAvoided": max(900, throughput_gap * 2 + food_backlog * 3),
                "reversible": True,
            },
            "counterfactual": "Fast queue relief, but it can silently move congestion into access paths and create fairness complaints.",
        },
        {
            "id": "safety_constrained_split",
            "label": "Safety-constrained route split",
            "proposedBy": "Safety/Policy Agent",
            "action": "Protect access lanes, split routes in controlled shares, pre-stage crowd leads, and limit guest messaging to affected cohorts.",
            "predictedDeltas": {
                "queueReliefPct": min(24, max(10, food_pressure // 6 + throughput_gap // 360)),
                "accessRiskDelta": -18 if safety_pressure >= 70 else -7,
                "costUsd": 3200 + open_callouts * 45,
                "trustDeltaPct": 7 if complaint_risk >= 35 else 3,
                "planRiskDelta": -12 if traffic_risk >= 50 else -5,
                "guestMinutesAvoided": max(700, throughput_gap + food_backlog * 2),
                "reversible": True,
            },
            "counterfactual": "Slower than a broad reroute, but protects access, showtime timing, and guest trust.",
        },
        {
            "id": "cx_recovery_first",
            "label": "Guest recovery first",
            "proposedBy": "Customer Experience Agent",
            "action": "Send transparent fairness messaging and bounded care options before changing flow.",
            "predictedDeltas": {
                "queueReliefPct": 6,
                "accessRiskDelta": -2,
                "costUsd": 9800 + open_care_cases * 35,
                "trustDeltaPct": 16 if complaint_risk >= 35 else 8,
                "planRiskDelta": 1,
                "guestMinutesAvoided": 350 + open_care_cases * 20,
                "reversible": True,
            },
            "counterfactual": "Good trust repair, weak physical congestion relief, and finance must cap promises.",
        },
        {
            "id": "planning_hold_until_wave",
            "label": "Hold until show wave clears",
            "proposedBy": "Planning Agent",
            "action": "Delay broad movement, run a short showtime counterfactual, then dispatch staff and messages at the decision deadline.",
            "predictedDeltas": {
                "queueReliefPct": 5,
                "accessRiskDelta": -9,
                "costUsd": 1600,
                "trustDeltaPct": -4 if food_eta >= 35 else 2,
                "planRiskDelta": -18 if traffic_risk >= 50 else -8,
                "guestMinutesAvoided": 500,
                "reversible": True,
            },
            "counterfactual": "Avoids a bad timed move, but can look passive if food or care pressure is already high.",
        },
        {
            "id": "finance_cost_cap",
            "label": "Finance cost cap",
            "proposedBy": "Finance Agent",
            "action": "Suppress high-friction offers, avoid broad compensation, and prioritize low-cost operational fixes.",
            "predictedDeltas": {
                "queueReliefPct": 8,
                "accessRiskDelta": 2,
                "costUsd": 900,
                "trustDeltaPct": -8 if complaint_risk >= 40 else -2,
                "planRiskDelta": 0,
                "guestMinutesAvoided": 420,
                "reversible": True,
            },
            "counterfactual": "Protects margin, but can make guest trust and fairness worse during visible stress.",
        },
    ]

    def score_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
        deltas = _as_dict(candidate.get("predictedDeltas"))
        queue_relief = float(_number(deltas.get("queueReliefPct")) or 0)
        access_delta = float(_number(deltas.get("accessRiskDelta")) or 0)
        cost = float(_number(deltas.get("costUsd")) or 0)
        trust_delta = float(_number(deltas.get("trustDeltaPct")) or 0)
        plan_delta = float(_number(deltas.get("planRiskDelta")) or 0)
        reversible = bool(deltas.get("reversible"))
        agent_scores = {
            "operations": round(_clamp(50 + queue_relief * 1.6 - max(0, plan_delta) * 0.7 - max(0, access_delta) * 0.8)),
            "safety": round(_clamp(82 - max(0, access_delta) * 2.8 + max(0, -access_delta) * 0.8 - (0 if reversible else 18))),
            "finance": round(_clamp(88 - cost / 350 - max(0, -trust_delta) * 1.5)),
            "planning": round(_clamp(72 - max(0, plan_delta) * 2.2 + max(0, -plan_delta) * 1.3)),
            "customer_experience": round(_clamp(58 + trust_delta * 2.2 + queue_relief * 0.45 - max(0, access_delta) * 0.6)),
            "qa": round(_clamp(64 + (14 if reversible else -20) - max(0, access_delta) - max(0, plan_delta) * 0.5)),
        }
        vetoes = []
        if access_delta > 12:
            vetoes.append({"agent": "Safety/Policy Agent", "reason": "Access risk increases beyond the safety threshold."})
        if plan_delta > 8 and traffic_risk >= 50:
            vetoes.append({"agent": "Planning Agent", "reason": "Action collides with active showtime traffic pressure."})
        if cost > 9000 and estimated_finance_exposure >= 12000:
            vetoes.append({"agent": "Finance Agent", "reason": "Cost exposure is too high without measured risk reduction."})
        if trust_delta < -5 and complaint_risk >= 35:
            vetoes.append({"agent": "Customer Experience Agent", "reason": "Guest-trust damage is likely during an active fairness issue."})
        total_score = round(
            _clamp(
                agent_scores["operations"] * 0.18
                + agent_scores["safety"] * 0.24
                + agent_scores["finance"] * 0.14
                + agent_scores["planning"] * 0.18
                + agent_scores["customer_experience"] * 0.18
                + agent_scores["qa"] * 0.08
                - len(vetoes) * 12
            )
        )
        scored = dict(candidate)
        scored["agentScores"] = agent_scores
        scored["vetoes"] = vetoes
        scored["totalScore"] = total_score
        scored["feasible"] = not vetoes
        scored["tradeoffSummary"] = (
            f"{round(queue_relief)}% queue relief, {round(access_delta)} access-risk delta, "
            f"${round(cost):,} cost, {round(trust_delta)} trust delta, {round(plan_delta)} plan-risk delta"
        )
        return scored

    market_candidates = [score_candidate(candidate) for candidate in raw_candidates]
    market_candidates.sort(key=lambda item: (bool(item.get("feasible")), item.get("totalScore", 0)), reverse=True)
    winning_candidate = market_candidates[0] if market_candidates else {}
    operations_favorite = next((candidate for candidate in market_candidates if candidate.get("id") == "ops_broad_reroute"), market_candidates[0] if market_candidates else {})
    agent_decision_market = {
        "marketType": "counterfactual_action_auction",
        "businessQuestion": "Which action should run when queue relief, safety access, showtime timing, finance exposure, and guest trust disagree?",
        "whyThisIsNotJustTeamwork": "Agents are not only chatting. Each agent owns an objective function, scores every candidate, can veto unsafe or economically irrational moves, and leaves an auditable regret/counterfactual trail.",
        "objectiveFunctions": [
            {"agent": "Operations Agent", "optimizes": "queue relief and throughput", "hardConstraint": False},
            {"agent": "Safety/Policy Agent", "optimizes": "access-route risk and reversible actions", "hardConstraint": True},
            {"agent": "Finance Agent", "optimizes": "cost-to-risk reduction and revenue leakage", "hardConstraint": False},
            {"agent": "Planning Agent", "optimizes": "showtime timing and 180-minute plan stability", "hardConstraint": False},
            {"agent": "Customer Experience Agent", "optimizes": "trust, fairness, and complaint avoidance", "hardConstraint": False},
            {"agent": "Reliability QA Agent", "optimizes": "observability, fallback, and post-action evaluability", "hardConstraint": True},
        ],
        "winningCandidate": winning_candidate,
        "operationsFavorite": operations_favorite,
        "candidates": market_candidates,
        "regretAnalysis": {
            "ifOperationsOnly": operations_favorite.get("counterfactual"),
            "chosenTradeoff": winning_candidate.get("counterfactual"),
            "avoidedVetoes": sum(len(candidate.get("vetoes", [])) for candidate in market_candidates if candidate.get("id") != winning_candidate.get("id")),
            "scoreDeltaVsOpsFavorite": int(winning_candidate.get("totalScore", 0)) - int(operations_favorite.get("totalScore", 0)),
        },
        "auditHooks": [
            "persist each candidate score vector",
            "store veto reason and triggering metric",
            "record selected candidate before dispatch",
            "compare predicted deltas to post-action state",
            "feed regret into the next decision-market weights",
        ],
    }
    accuracy_gaps = [
        "Synthetic twin is useful for agent rehearsal, policy gating, and regression evals.",
        "It is not production-accurate learning data until calibrated against real park wait times, POS throughput, staff task completion, guest app take rate, and incident outcomes.",
        "Current ledger records decisions and evals; before/after state deltas are inferred from live state unless each action stores measured outcome snapshots.",
    ]
    return {
        "status": "ready",
        "generatedAt": _utc_now(),
        "unresolvedCount": unresolved_count,
        "overallStatus": "needs_strategy_shift" if repeated_action_warning else "watch" if unresolved_count else "stable",
        "issues": issues,
        "enterpriseDomains": enterprise_domains,
        "enterpriseSummary": {
            "mode": "whole_park_agentic_control",
            "domains": ["operations", "safety", "finance", "planning", "customer_experience"],
            "weakestDomain": weakest_domain,
            "executiveQuestion": "Which domain should constrain the next action: safety, finance, planning, customer trust, or operations?",
            "answer": "The app now treats operations as one domain in a wider park-management twin; incidents are summarized as cross-functional tickets and stored to MongoDB.",
        },
        "multiAgentCouncil": agent_council,
        "agentDecisionMarket": agent_decision_market,
        "effectiveness": {
            "ledgerRows": len(rows),
            "latestAction": latest.get("selectedAction"),
            "latestEvalScore": latest.get("evalScore"),
            "latestDispatchCount": latest.get("dispatchCount"),
            "averageEvalScore": _avg(scores),
            "repeatedActionStreak": streak,
            "adaptiveFinding": "Same action is repeating while risk remains unresolved; the agent should shift or escalate strategy."
            if repeated_action_warning
            else "No repeated-action failure pattern detected in the latest ledger window.",
        },
        "evalBreakdown": eval_breakdown,
        "simulationFidelity": {
            "label": "demo-grade synthetic twin",
            "agentLearningReadiness": "suitable_for_policy_rehearsal_not_production_learning",
            "accuracyAnswer": "Accurate enough to train and demo the agent loop shape; not accurate enough to claim real-world optimized operations without calibration data.",
            "missingCalibrationFeeds": ["real wait-time history", "POS order throughput", "staff task acknowledgements", "guest app take-rate", "complaint/refund outcomes", "weather and event attendance actuals"],
            "gaps": accuracy_gaps,
        },
        "storage": {"ledgerPath": str(_ledger_path()), "maxRows": MAX_LEDGER_ROWS},
    }


def retrieve_agent_ops_context(query: str, limit: int = 3) -> dict[str, Any]:
    payload = read_agent_ops_ledger(limit=MAX_LEDGER_ROWS)
    terms = [term.lower() for term in query.split() if len(term.strip()) >= 3]
    scored: list[tuple[int, dict[str, Any]]] = []
    for row in payload["items"]:
        haystack = " ".join([str(row.get("selectedAction", "")), str(row.get("scenarioName", "")), str(row.get("summary", "")), " ".join(row.get("retrievalTags", []))]).lower()
        score = sum(1 for term in terms if term in haystack)
        if score or not terms:
            scored.append((score, row))
    scored.sort(key=lambda item: (item[0], item[1].get("timestamp", "")), reverse=True)
    matches = [deepcopy(row) for _, row in scored[: max(1, limit)]]
    return {
        "status": "retrieved" if matches else "empty",
        "query": query,
        "count": len(matches),
        "items": matches,
        "summary": [
            {
                "id": row.get("id"),
                "selectedAction": row.get("selectedAction"),
                "evalScore": row.get("evalScore"),
                "gate": row.get("gate"),
                "lesson": row.get("summary"),
            }
            for row in matches
        ],
    }


def record_agent_ops_record(record: dict[str, Any]) -> dict[str, Any]:
    row = normalize_agent_ops_record(record)
    rows = _read_rows()
    existing_index = next((index for index, existing in enumerate(rows) if existing.get("signature") == row["signature"] or existing.get("id") == row["id"]), None)
    if existing_index is not None:
        rows.pop(existing_index)
        status = "deduplicated"
    else:
        status = "stored"
    rows.insert(0, row)
    _write_rows(rows[:MAX_LEDGER_ROWS])
    return {"status": status, "record": deepcopy(row), "count": min(len(rows), MAX_LEDGER_ROWS), "storage": {"path": str(_ledger_path())}}


def record_agent_ops_run(payload: dict[str, Any], *, message: str = "", mode: str = "", kind: str = "agent_run") -> dict[str, Any]:
    return record_agent_ops_record(build_ledger_record_from_run(payload, message=message, mode=mode, kind=kind))


def _read_rows() -> list[dict[str, Any]]:
    path = _ledger_path()
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                rows.append(normalize_agent_ops_record(parsed))
    rows.sort(key=lambda row: str(row.get("timestamp", "")), reverse=True)
    return rows[:MAX_LEDGER_ROWS]


def _write_rows(rows: list[dict[str, Any]]) -> None:
    path = _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(_compact_json(normalize_agent_ops_record(row)) + "\n")
