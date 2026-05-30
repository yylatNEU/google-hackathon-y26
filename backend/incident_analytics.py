from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _severity_rank(severity: str) -> int:
    return {"critical": 4, "high": 3, "warning": 2, "medium": 2, "watch": 1, "review": 1}.get(severity.lower(), 1)


def _ticket(
    *,
    source: str,
    domain: str,
    title: str,
    severity: str,
    status: str,
    summary: str,
    recommended_human_call: str,
    evidence: list[str],
    requires_human_review: bool = True,
    owner: str = "Ops lead",
    created_at: str | None = None,
    source_id: str | None = None,
) -> dict[str, Any]:
    ticket_id = f"{source}:{source_id or title}".lower().replace(" ", "-")[:120]
    return {
        "id": ticket_id,
        "source": source,
        "sourceId": source_id,
        "domain": domain,
        "title": title,
        "severity": severity.lower(),
        "status": status,
        "summary": summary,
        "recommendedHumanCall": recommended_human_call,
        "requiresHumanReview": requires_human_review,
        "owner": owner,
        "createdAt": created_at or _utc_now(),
        "evidence": [str(item) for item in evidence if item][:6],
    }


def _tickets_from_backlog(backlog: dict[str, Any]) -> list[dict[str, Any]]:
    tickets = []
    for issue in _as_list(backlog.get("issues")):
        if not isinstance(issue, dict):
            continue
        tickets.append(
            _ticket(
                source="operational_backlog",
                source_id=str(issue.get("id") or issue.get("title")),
                domain=str(issue.get("domain") or "Operations"),
                title=str(issue.get("title") or "Open operating risk"),
                severity=str(issue.get("severity") or "warning"),
                status=str(issue.get("status") or "unresolved"),
                summary=str(issue.get("current") or "Open risk remains unresolved."),
                recommended_human_call=str(issue.get("recommendedNext") or "Decide whether to hold, escalate, or change action strategy."),
                evidence=_as_list(issue.get("evidence")),
                owner="Operations lead",
            )
        )
    return tickets


def _tickets_from_audit(audit: dict[str, Any]) -> list[dict[str, Any]]:
    tickets = []
    for finding in _as_list(audit.get("anomalies")):
        if not isinstance(finding, dict):
            continue
        tickets.append(
            _ticket(
                source="audit_agent",
                source_id=str(finding.get("id") or finding.get("title")),
                domain=str(finding.get("domain") or "Audit"),
                title=str(finding.get("title") or "Audit anomaly"),
                severity=str(finding.get("severity") or "watch"),
                status=str(finding.get("status") or "open"),
                summary=str(finding.get("description") or finding.get("detail") or finding.get("recommendedAction") or "Audit anomaly needs review."),
                recommended_human_call=str(finding.get("recommendedAction") or "Review the anomaly and approve the safest bounded response."),
                evidence=[
                    f"abnormalityScore={finding.get('abnormalityScore', '--')}",
                    f"leadTimeMinutes={finding.get('leadTimeMinutes', '--')}",
                    f"owner={finding.get('owner', '--')}",
                ],
                owner=str(finding.get("owner") or "Audit lead"),
                created_at=str(finding.get("detectedAt") or finding.get("updatedAt") or _utc_now()),
            )
        )
    return tickets


def _tickets_from_signals(signals: dict[str, Any]) -> list[dict[str, Any]]:
    tickets = []
    for signal in _as_list(signals.get("signals")):
        if not isinstance(signal, dict):
            continue
        severity = str(signal.get("risk_level") or "watch").lower()
        zone = _as_dict(signal.get("zone"))
        title = f"{severity.upper()} signal near {zone.get('name') or zone.get('id') or 'park'}"
        tickets.append(
            _ticket(
                source="signal_inbox",
                source_id=str(signal.get("id") or title),
                domain="Signal triage",
                title=title,
                severity="critical" if severity == "critical" else "warning" if severity in {"high", "medium"} else "watch",
                status="needs_confirmation" if signal.get("missing_info") else "triaged",
                summary=str(signal.get("text") or signal.get("triage_explanation") or "Signal triaged."),
                recommended_human_call="Confirm missing facts before broad guest messaging." if signal.get("missing_info") else "Review recommended actions and choose whether to dispatch.",
                evidence=[
                    f"source={signal.get('source', '--')}",
                    f"confidence={signal.get('confidence', '--')}",
                    f"categories={', '.join(str(item) for item in _as_list(signal.get('categories')))}",
                    *[f"missing: {item}" for item in _as_list(signal.get("missing_info"))[:3]],
                ],
                requires_human_review=bool(signal.get("human_approval_required") or signal.get("missing_info")),
                owner=str(signal.get("reporterRole") or "Signal triage lead"),
                created_at=str(signal.get("createdAt") or _utc_now()),
            )
        )
    return tickets


def _tickets_from_dispatches(dispatches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tickets = []
    for dispatch in dispatches:
        if not isinstance(dispatch, dict):
            continue
        status = str(dispatch.get("status") or "")
        payload = _as_dict(dispatch.get("payload"))
        if status != "pending_operator_approval" and not payload.get("requiresHumanApproval"):
            continue
        tickets.append(
            _ticket(
                source="action_approval",
                source_id=str(dispatch.get("id") or payload.get("decisionId") or "dispatch"),
                domain=str(dispatch.get("channel") or "Action bus"),
                title=f"Approval needed: {payload.get('command') or payload.get('task') or payload.get('message') or dispatch.get('channel')}",
                severity="warning",
                status="pending_operator_approval",
                summary=str(payload.get("reason") or payload.get("task") or payload.get("message") or "Receiver action is waiting for approval."),
                recommended_human_call="Approve, hold, or modify this receiver action before equipment or staff-visible execution.",
                evidence=[
                    f"channel={dispatch.get('channel', '--')}",
                    f"target={payload.get('targetZone') or payload.get('zones') or '--'}",
                    f"endpoint={dispatch.get('endpoint', '--')}",
                ],
                owner="Shift commander",
                created_at=str(dispatch.get("createdAt") or _utc_now()),
            )
        )
    return tickets


def _tickets_from_ledger(ledger: dict[str, Any], backlog: dict[str, Any]) -> list[dict[str, Any]]:
    effectiveness = _as_dict(backlog.get("effectiveness"))
    repeated = _as_dict(effectiveness.get("repeatedActionStreak"))
    if repeated.get("status") != "repetitive":
        return []
    return [
        _ticket(
            source="agent_eval",
            source_id="repeated-action-streak",
            domain="Agent evaluation",
            title="Agent action is repeating while risk remains open",
            severity="warning",
            status="human_review",
            summary=str(effectiveness.get("adaptiveFinding") or "Repeated action pattern detected."),
            recommended_human_call="Decide whether to override with a capacity intervention, hold automation, or request more ground truth.",
            evidence=[
                f"repeatStreak={repeated.get('count', 0)}",
                f"latestEval={effectiveness.get('latestEvalScore', '--')}",
                f"ledgerRows={ledger.get('count', '--')}",
            ],
            owner="Ops lead",
        )
    ]


def build_incident_analytics(
    *,
    state: dict[str, Any],
    audit: dict[str, Any],
    signals: dict[str, Any],
    dispatches: list[dict[str, Any]],
    backlog: dict[str, Any],
    ledger: dict[str, Any],
) -> dict[str, Any]:
    tickets = [
        *_tickets_from_backlog(backlog),
        *_tickets_from_audit(audit),
        *_tickets_from_signals(signals),
        *_tickets_from_dispatches(dispatches),
        *_tickets_from_ledger(ledger, backlog),
    ]
    deduped: dict[str, dict[str, Any]] = {}
    for ticket in tickets:
        key = ticket["id"]
        existing = deduped.get(key)
        if not existing or _severity_rank(ticket["severity"]) > _severity_rank(existing["severity"]):
            deduped[key] = ticket
    sorted_tickets = sorted(
        deduped.values(),
        key=lambda item: (_severity_rank(str(item.get("severity"))), bool(item.get("requiresHumanReview")), str(item.get("createdAt"))),
        reverse=True,
    )
    domain_counts = Counter(str(ticket.get("domain") or "Operations") for ticket in sorted_tickets)
    source_counts = Counter(str(ticket.get("source") or "unknown") for ticket in sorted_tickets)
    human_queue = [ticket for ticket in sorted_tickets if ticket.get("requiresHumanReview")][:8]
    critical_count = sum(1 for ticket in sorted_tickets if ticket.get("severity") == "critical")
    warning_count = sum(1 for ticket in sorted_tickets if ticket.get("severity") in {"warning", "high"})
    top_ticket = human_queue[0] if human_queue else sorted_tickets[0] if sorted_tickets else None
    if critical_count:
        recommended_call = "Human lead should review critical safety/care tickets before broad guest-facing automation."
    elif human_queue:
        recommended_call = "Human lead should clear the review queue and choose which bounded action to approve."
    elif sorted_tickets:
        recommended_call = "Human lead can monitor; no critical approval is waiting."
    else:
        recommended_call = "No incident ticket is currently open."

    return {
        "status": "ready",
        "mode": "incident_analytics_human_review",
        "generatedAt": _utc_now(),
        "scenario": _as_dict(_as_dict(state.get("guestFlow")).get("activeScenario")),
        "summary": {
            "ticketCount": len(sorted_tickets),
            "criticalCount": critical_count,
            "warningCount": warning_count,
            "humanReviewCount": len(human_queue),
            "pendingApprovalCount": sum(1 for ticket in sorted_tickets if ticket.get("status") == "pending_operator_approval"),
            "topDomains": domain_counts.most_common(5),
            "sourceMix": source_counts.most_common(5),
            "recommendedCall": recommended_call,
        },
        "operatorBrief": {
            "headline": top_ticket["title"] if top_ticket else "No open incident tickets",
            "whatChanged": top_ticket["summary"] if top_ticket else "The park has no ticket requiring operator judgement right now.",
            "humanDecision": top_ticket["recommendedHumanCall"] if top_ticket else "Keep monitoring.",
            "confidence": "high" if critical_count or len(human_queue) >= 2 else "medium" if sorted_tickets else "low",
        },
        "humanReviewQueue": human_queue,
        "tickets": sorted_tickets[:24],
        "analytics": {
            "byDomain": [{"domain": domain, "count": count} for domain, count in domain_counts.most_common()],
            "bySource": [{"source": source, "count": count} for source, count in source_counts.most_common()],
            "reviewPosture": "active_human_review" if human_queue else "monitor_only",
            "agentRole": "gather, correlate, summarize, and prepare options; human decides sensitive calls.",
        },
        "decisionSupport": {
            "humanShouldDecide": [
                "Whether to approve guest-visible messaging for vague or sensitive reports.",
                "Whether to dispatch staff/equipment actions that affect safety, labor, or access lanes.",
                "Whether repeated agent actions should be overridden by a different operating strategy.",
            ],
            "agentShouldPrepare": [
                "Collect related audit findings, signals, receiver actions, and current operating pressure.",
                "Summarize evidence and missing facts.",
                "Draft bounded options with policy constraints and expected operational impact.",
            ],
        },
    }
