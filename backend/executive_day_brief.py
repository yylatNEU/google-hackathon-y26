from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _num(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _clamp(value: float, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, round(value)))


def _severity_rank(value: Any) -> int:
    return {
        "critical": 5,
        "high": 4,
        "warning": 3,
        "medium": 2,
        "watch": 1,
        "review": 1,
    }.get(str(value or "").lower(), 1)


def _top_by(rows: list[Any], key: str) -> dict[str, Any]:
    dict_rows = [row for row in rows if isinstance(row, dict)]
    return max(dict_rows, key=lambda row: _num(row.get(key)), default={})


def _issue_id(row: dict[str, Any], index: int) -> str:
    return str(row.get("id") or row.get("sourceId") or row.get("title") or f"issue-{index}")


def _timestamp(row: dict[str, Any], fallback: str = "") -> str:
    for key in ("createdAt", "detectedAt", "timestamp", "generatedAt", "updatedAt", "at"):
        if row.get(key):
            return str(row.get(key))
    return fallback


def _minute_label(minute_of_day: float) -> str:
    minute = max(0, min(24 * 60 - 1, round(minute_of_day)))
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _operating_demand(minute_of_day: float) -> float:
    if minute_of_day < 9 * 60:
        return 0
    if minute_of_day < 10 * 60:
        return 38 + ((minute_of_day - 9 * 60) / 60) * 22
    if minute_of_day < 12 * 60:
        return 62 + ((minute_of_day - 10 * 60) / 120) * 20
    if minute_of_day < 15 * 60:
        return 84
    if minute_of_day < 18 * 60:
        return 80 + ((minute_of_day - 15 * 60) / 180) * 10
    if minute_of_day < 21 * 60:
        return 84
    if minute_of_day < 23 * 60:
        return 76 - ((minute_of_day - 21 * 60) / 120) * 18
    return 0


def _pressure_curve(*, state: dict[str, Any], composite: int, ops_effect: int, density: int) -> list[dict[str, Any]]:
    clock = _as_dict(state.get("operatingClock"))
    heartbeat = _as_dict(clock.get("heartbeat"))
    phase = _as_dict(clock.get("phase"))
    sim_time = _as_dict(state.get("simTime"))
    current_minute = _num(heartbeat.get("minuteOfDay"), _num(phase.get("minuteOfDay"), _num(sim_time.get("hour")) * 60 + _num(sim_time.get("minute"))))
    opening = 9 * 60
    current = max(opening, min(23 * 60, current_minute or opening))
    points = max(5, min(9, round((current - opening) / 120) + 1))
    rows: list[dict[str, Any]] = []
    for index in range(points):
        ratio = 1 if points == 1 else index / (points - 1)
        minute = opening + (current - opening) * ratio
        demand = _operating_demand(minute)
        snapshot_pull = 1 if index == points - 1 else ratio * 0.35
        expected = _clamp(demand * (1 - snapshot_pull) + (composite + ops_effect) * snapshot_pull)
        controlled = composite if index == points - 1 else _clamp(expected - ops_effect * max(0, ratio - 0.55))
        rows.append(
            {
                "label": _minute_label(minute),
                "expected": expected,
                "controlled": controlled,
                "density": density if index == points - 1 else _clamp(demand + (density - demand) * ratio),
            }
        )
    return rows


def build_executive_day_brief(
    *,
    state: dict[str, Any],
    backlog: dict[str, Any],
    incidents: dict[str, Any],
    audit: dict[str, Any] | None = None,
    dispatches: list[dict[str, Any]] | None = None,
    ledger: dict[str, Any] | None = None,
) -> dict[str, Any]:
    flow = _as_dict(state.get("guestFlow"))
    ops = _as_dict(state.get("parkOps"))
    zones = _as_list(flow.get("zones"))
    rides = _as_list(flow.get("rides"))
    paths = _as_list(flow.get("paths"))
    clock = _as_dict(state.get("operatingClock"))
    guest_intent = _as_dict(clock.get("guestIntent"))
    staff_lifecycle = _as_dict(clock.get("staffLifecycle"))
    event_schedule = _as_dict(clock.get("eventSchedule"))
    fairness = _as_dict(clock.get("accessFairness"))
    counterfactual = _as_dict(state.get("counterfactualForecast"))
    impact = _as_dict(counterfactual.get("impact"))
    learning = _as_dict(_as_dict(state.get("learningEvidenceLedger")).get("summary"))
    calibration = _as_dict(_as_dict(state.get("digitalTwinCalibration")).get("summary"))
    audit_payload = _as_dict(audit or {})
    audit_summary = _as_dict(audit_payload.get("summary"))
    audit_timeline = [row for row in _as_list(audit_payload.get("reactionTimeline")) if isinstance(row, dict)]
    dispatch_rows = [row for row in _as_list(dispatches or []) if isinstance(row, dict)]
    ledger_items = [row for row in _as_list(_as_dict(ledger or {}).get("items")) if isinstance(row, dict)]
    learning_payload = _as_dict(state.get("learningEvidenceLedger"))
    latest_learning_record = _as_dict(ledger_items[0] if ledger_items else _as_list(learning_payload.get("recentDecisions"))[0] if _as_list(learning_payload.get("recentDecisions")) else {})

    top_zone = _top_by(zones, "density")
    top_ride = _top_by(rides, "waitMins")
    top_path = _top_by(paths, "congestionLevel")
    tickets = [ticket for ticket in _as_list(incidents.get("tickets")) if isinstance(ticket, dict)]
    issues = [issue for issue in _as_list(backlog.get("issues")) if isinstance(issue, dict)]
    top_ticket = max(tickets, key=lambda row: _severity_rank(row.get("severity")), default={})
    top_issue = max(issues, key=lambda row: _severity_rank(row.get("severity")), default={})

    density = _clamp(_num(top_zone.get("density")))
    wait = _clamp(_num(top_ride.get("waitMins")), 0, 120)
    staff_gap = _clamp(100 - _num(ops.get("staffReadyPct")))
    incident_count = int(_num(_as_dict(incidents.get("summary")).get("ticketCount"), len(tickets)))
    human_review = int(_num(_as_dict(incidents.get("summary")).get("humanReviewCount")))
    satisfaction_risk = _clamp(100 - _num(flow.get("avgSatisfaction")))
    composite = _clamp(density * 0.28 + wait * 0.24 + staff_gap * 0.2 + incident_count * 7 * 0.16 + satisfaction_risk * 0.12)
    active_policy = str(flow.get("activePolicy") or "normal")
    interventions = _as_list(flow.get("interventions"))
    ops_effect = _clamp((12 if active_policy != "normal" else 0) + len(interventions) * 4 + _num(_as_dict(counterfactual.get("actionExecution")).get("finalTakeRatePct")) * 0.25, 0, 48)

    def score_issue(row: dict[str, Any], source: str) -> dict[str, Any]:
        title_blob = " ".join(str(row.get(key) or "") for key in ("title", "domain", "summary", "recommendedHumanCall", "recommendedNext")).lower()
        severity_score = _severity_rank(row.get("severity")) * 18
        guest_impact = _clamp(density * 0.35 + wait * 0.25 + incident_count * 3 + satisfaction_risk * 0.25)
        safety_access = _clamp(
            (25 if any(term in title_blob for term in ("safety", "access", "lane", "crowd", "spill", "security")) else 0)
            + _num(fairness.get("publicComplaintRiskPct")) * 0.45
            + _num(event_schedule.get("eventTrafficRiskPct")) * 0.35
            + max(0, density - 70) * 0.5
        )
        unresolved_age = 15 if str(row.get("status") or "").lower() not in {"closed", "resolved", "done"} else 0
        confidence_component = 10 if row.get("evidence") or row.get("source") else 4
        total = _clamp(severity_score + guest_impact * 0.28 + safety_access * 0.22 + unresolved_age + confidence_component, 0, 100)
        return {
            "id": _issue_id(row, 0),
            "source": source,
            "title": str(row.get("title") or "Open issue"),
            "severity": str(row.get("severity") or "watch"),
            "total": total,
            "severityScore": _clamp(severity_score),
            "guestImpact": guest_impact,
            "safetyAccessRisk": safety_access,
            "unresolvedAge": unresolved_age,
            "confidence": confidence_component,
        }

    scored_issues = [
        *[score_issue(ticket, "incident") for ticket in tickets],
        *[score_issue(issue, "backlog") for issue in issues],
    ]
    selected_score = max(scored_issues, key=lambda row: row["total"], default={})
    selected_id = selected_score.get("id")
    primary = next((row for row in [*tickets, *issues] if _issue_id(row, 0) == selected_id), top_ticket if _severity_rank(top_ticket.get("severity")) >= _severity_rank(top_issue.get("severity")) else top_issue)

    title = str(primary.get("title") or top_zone.get("name") or "Operating risk needs review")
    recommended = str(primary.get("recommendedHumanCall") or primary.get("recommendedNext") or "Approve a bounded operating response and keep broad automation held until the gap is visible.")
    root_cause = (
        f"{top_zone.get('name') or 'The busiest zone'} is carrying {density}% density while "
        f"{top_ride.get('name') or 'the top ride'} is at {wait} minutes and incident load is {incident_count} tickets."
    )
    business_impact = (
        impact.get("summary")
        or f"Current exposure is {incident_count} incident tickets, {human_review} human-review items, {staff_gap}% staffing gap, and {satisfaction_risk}% satisfaction risk."
    )
    mitigation_gap = (
        f"Policy posture is {active_policy}; reported controls remove about {ops_effect} pressure points, but the remaining composite risk is {composite}/100."
        if ops_effect
        else f"No material mitigation effect is visible yet; remaining composite risk is {composite}/100."
    )
    owner = str(primary.get("owner") or "Operations lead")
    deadline = int(max(5, min(45, _num(audit_summary.get("earliestReactionMinutes"), 15))))
    confidence = _clamp(
        45
        + min(20, incident_count * 2)
        + (10 if density > 65 else 0)
        + (10 if tickets or issues else 0)
        + (10 if calibration.get("accuracyScore") else 0)
    )
    approve_if = [
        "Crowd lead confirms service and emergency lanes remain clear.",
        "Guest-facing message names the delay cause without promising an exact recovery time.",
        "The next 15-minute snapshot shows density or complaint pressure is flat or improving.",
    ]
    hold_if = [
        "The action would move guests toward the current hotspot.",
        "Staffing gap increases or a safety/access ticket remains unassigned.",
        "The issue lacks enough evidence for broad guest-visible automation.",
    ]
    tradeoff = "Approving keeps pressure from compounding, but over-correcting can move guests into a second bottleneck or worsen perceived fairness."

    evidence = [
        {
            "claim": root_cause,
            "metric": f"{density}% density / {wait}m top wait",
            "source": "guest_flow",
            "id": str(top_zone.get("id") or top_zone.get("name") or "zone-density"),
            "sourceId": str(top_ride.get("id") or top_ride.get("name") or "top-ride-wait"),
            "timestamp": _pressure_curve(state=state, composite=composite, ops_effect=ops_effect, density=density)[-1]["label"],
        },
        {
            "claim": f"{incident_count} incident tickets and {len(issues)} backlog items are still open.",
            "metric": f"{incident_count + len(issues)} issue rows",
            "source": "incident_backlog",
            "id": str(primary.get("id") or selected_id or "primary-issue"),
            "sourceId": str(selected_id or "incident-backlog"),
            "timestamp": _timestamp(primary, _pressure_curve(state=state, composite=composite, ops_effect=ops_effect, density=density)[-1]["label"]),
        },
        {
            "claim": str(backlog.get("enterpriseSummary", {}).get("answer") or "Enterprise backlog identifies the cross-domain operating constraint."),
            "metric": str(backlog.get("enterpriseSummary", {}).get("weakestDomain", {}).get("label") or "domain risk"),
            "source": "enterprise_backlog",
            "id": str(_as_dict(backlog.get("enterpriseSummary", {})).get("id") or "enterprise-summary"),
            "sourceId": str(_as_dict(_as_dict(backlog.get("enterpriseSummary", {})).get("weakestDomain")).get("id") or "weakest-domain"),
            "timestamp": _now_iso(),
        },
    ]
    if impact.get("guestMinutesSaved"):
        evidence.append(
            {
                "claim": str(impact.get("summary") or "Counterfactual branch shows measurable guest-minute value."),
                "metric": f"{int(_num(impact.get('guestMinutesSaved'))):,} guest minutes",
                "source": "counterfactual",
                "id": str(counterfactual.get("id") or "counterfactual-forecast"),
                "sourceId": str(_as_dict(counterfactual.get("focus")).get("id") or _as_dict(counterfactual.get("focus")).get("response") or "forecast-focus"),
                "timestamp": str(counterfactual.get("generatedAt") or _now_iso()),
            }
        )
    if learning:
        evidence.append(
            {
                "claim": f"{int(_num(learning.get('memoryBackedDecisions')))} decisions are memory-backed today.",
                "metric": f"{int(_num(learning.get('ledgerEntries')))} ledger entries",
                "source": "learning_memory",
                "id": str(latest_learning_record.get("id") or "learning-evidence-ledger"),
                "sourceId": "learning-evidence-ledger",
                "timestamp": _timestamp(latest_learning_record, _now_iso()),
            }
        )

    issue_corpus = incident_count + len(issues)
    evidence_rows = issue_corpus + int(_num(learning.get("ledgerEntries"))) + int(_num(calibration.get("resolvedRows")))
    domain_counts = Counter(str(ticket.get("domain") or "Operations") for ticket in tickets)
    driver_rows = [
        {"label": "Incident load", "value": min(100, incident_count * 8), "max": 100},
        {"label": "Zone density", "value": density, "max": 100},
        {"label": "Queue wait", "value": wait, "max": 120},
        {"label": "Staffing gap", "value": staff_gap, "max": 100},
        {"label": "Fairness risk", "value": _clamp(_num(fairness.get("publicComplaintRiskPct"))), "max": 100},
    ]
    current_time = _pressure_curve(state=state, composite=composite, ops_effect=ops_effect, density=density)[-1]["label"]
    first_audit_event = audit_timeline[0] if audit_timeline else {}
    issue_timeline = [
        {
            "phase": "park_open",
            "label": "Operating day opened",
            "at": "09:00",
            "detail": "Daily analytics window starts at park opening, not at the latest browser render.",
            "source": "operating_clock",
            "sourceId": "park-open",
        },
        {
            "phase": "detected",
            "label": "Primary issue selected",
            "at": _timestamp(primary, current_time),
            "detail": title,
            "source": str(selected_score.get("source") or "incident_backlog"),
            "sourceId": str(selected_id or primary.get("id") or "primary-issue"),
        },
        {
            "phase": "ops_attempted",
            "label": "Mitigation attempted",
            "at": str(first_audit_event.get("at") or current_time),
            "detail": f"{active_policy} policy plus {len(interventions)} intervention rows and {len(dispatch_rows)} dispatch receipts.",
            "source": "ops_runtime",
            "sourceId": str(first_audit_event.get("id") or "ops-mitigation"),
        },
        {
            "phase": "observed_effect",
            "label": "Effect measured",
            "at": current_time,
            "detail": f"{ops_effect} pressure points reduced; composite risk remains {composite}/100.",
            "source": "executive_day_brief",
            "sourceId": "impact-model",
        },
        {
            "phase": "decision_due",
            "label": "Decision due",
            "at": f"+{deadline}m",
            "detail": f"{owner} must approve, hold, or edit the bounded response.",
            "source": "decision_gate",
            "sourceId": str(selected_id or "decision-gate"),
        },
    ]

    represented_guests = int(_num(flow.get("representedGuests")))
    guest_minutes_at_risk = int(max(0, represented_guests * composite / 100 * max(10, deadline) / 12))
    complaint_risk = _clamp(satisfaction_risk * 0.45 + _num(fairness.get("publicComplaintRiskPct")) * 0.4 + incident_count * 3)
    safety_access_risk = int(selected_score.get("safetyAccessRisk", _clamp(_num(event_schedule.get("eventTrafficRiskPct")) + max(0, density - 70))))
    revenue_exposure = int(max(0, guest_minutes_at_risk * 0.08 + complaint_risk * 42 + incident_count * 125))
    impact_model = {
        "guestMinutesAtRisk": guest_minutes_at_risk,
        "complaintEscalationRiskPct": complaint_risk,
        "safetyAccessRiskPct": safety_access_risk,
        "revenueExposureUsd": revenue_exposure,
        "staffingLoadRiskPct": staff_gap,
        "confidencePct": confidence,
    }

    alternatives = [
        {
            "id": "approve-bounded-response",
            "label": "Approve bounded response",
            "expectedImpact": f"Reduce {min(48, max(12, ops_effect + 8))} pressure points while preserving operator control.",
            "risk": "Can displace demand if guest routing is too broad.",
            "tradeoff": tradeoff,
            "score": _clamp(70 + confidence * 0.2 - safety_access_risk * 0.08),
            "recommended": True,
        },
        {
            "id": "hold-for-field-confirmation",
            "label": "Hold for field confirmation",
            "expectedImpact": "Avoids a false move, but lets current guest-minute exposure continue.",
            "risk": f"Approximately {guest_minutes_at_risk:,} guest-minutes remain exposed during the hold.",
            "tradeoff": "Best only if lane access or staffing evidence is still ambiguous.",
            "score": _clamp(58 + safety_access_risk * 0.18 - composite * 0.12),
            "recommended": False,
        },
        {
            "id": "reroute-nearby-guests",
            "label": "Reroute nearby guests",
            "expectedImpact": f"Can relieve {top_zone.get('name') or 'the hotspot'} but may overload {top_path.get('toName') or top_path.get('to') or 'the next path'}.",
            "risk": "Second bottleneck risk if staff do not meter arrivals.",
            "tradeoff": "Useful as a narrow follow-up, not as the whole response.",
            "score": _clamp(62 + density * 0.18 - _num(fairness.get("publicComplaintRiskPct")) * 0.12),
            "recommended": False,
        },
        {
            "id": "message-only",
            "label": "Message guests only",
            "expectedImpact": "Improves expectation setting but does not materially change capacity.",
            "risk": "May look performative if queues or access lanes keep degrading.",
            "tradeoff": "Low operational risk, weak pressure reduction.",
            "score": _clamp(45 + satisfaction_risk * 0.12 - composite * 0.08),
            "recommended": False,
        },
    ]

    learning_memory = {
        "status": "memory_backed" if ledger_items or _num(learning.get("memoryBackedDecisions")) else "thin_memory",
        "matchedCases": len(ledger_items) or int(_num(learning.get("memoryBackedDecisions"))),
        "latestLesson": str(
            latest_learning_record.get("lesson")
            or latest_learning_record.get("summary")
            or learning_payload.get("headline")
            or "No comparable prior outcome has been written yet."
        ),
        "takeRatePriorPct": _clamp(_num(_as_dict(counterfactual.get("actionExecution")).get("finalTakeRatePct"))),
        "nextBias": str(
            latest_learning_record.get("nextPlanBias")
            or latest_learning_record.get("selectedAction")
            or "Prefer bounded nudges with observed response before broad automation."
        ),
    }
    success_threshold = max(35, composite - max(8, min(18, ops_effect // 2 + 6)))
    review_window = max(10, deadline)
    product_structure = {
        "executiveQuestion": "What decision needs approval now?",
        "decisionThesis": recommended,
        "successMetric": f"Move risk {composite}/100 -> {success_threshold}/100 within {review_window}m, or hold with cause.",
        "reviewCadence": f"Next review in {review_window}m.",
        "northStar": "Reduce guest-minutes at risk without bypassing safety, access, or operator gates.",
        "workflowStages": [
            {
                "stage": "Sense",
                "question": "Pressure",
                "answer": root_cause,
                "metric": f"{density}% density, {wait}m top wait",
                "status": "ready" if zones or rides else "thin",
            },
            {
                "stage": "Diagnose",
                "question": "Priority",
                "answer": "; ".join([item for item in [
                    f"severity {selected_score.get('severityScore', 0)}",
                    f"guest impact {selected_score.get('guestImpact', 0)}",
                    f"safety/access {selected_score.get('safetyAccessRisk', 0)}",
                ]]),
                "metric": f"{selected_score.get('total', 0)}/100 selection score",
                "status": "ready" if selected_score else "thin",
            },
            {
                "stage": "Decide",
                "question": "Decision",
                "answer": recommended,
                "metric": f"{confidence}% confidence",
                "status": "needs_owner" if confidence < 70 else "ready",
            },
            {
                "stage": "Act",
                "question": "Owner",
                "answer": f"{owner} approves, holds, or edits.",
                "metric": f"{deadline}m decision deadline",
                "status": "gated",
            },
            {
                "stage": "Learn",
                "question": "Learning",
                "answer": learning_memory["nextBias"],
                "metric": f"{learning_memory['matchedCases']} matched cases",
                "status": learning_memory["status"],
            },
        ],
        "ownerResponsibilities": [
            {
                "owner": owner,
                "role": "Decision owner",
                "responsibility": "Approve, hold, or edit.",
                "proofNeeded": "Confirm the action will not feed the hotspot.",
            },
            {
                "owner": "Crowd lead",
                "role": "Field verifier",
                "responsibility": "Verify lanes, queues, and density.",
                "proofNeeded": "Next snapshot is flat or improving.",
            },
            {
                "owner": "Guest comms",
                "role": "Guest messaging",
                "responsibility": "Explain cause and expectation.",
                "proofNeeded": "Message follows the approved posture.",
            },
        ],
        "productGaps": [
            {
                "gap": "Longitudinal evidence",
                "whyItMatters": "The current brief can explain this moment; a stronger product proves the whole day with stored snapshots.",
                "nextBuild": "Persist operating-day snapshots and compare before/after mitigation windows.",
            },
            {
                "gap": "Outcome accountability",
                "whyItMatters": "A decision is only useful if the page later shows whether it worked.",
                "nextBuild": "Attach outcome receipts to each recommendation and close the loop into learning memory.",
            },
            {
                "gap": "Drilldown depth",
                "whyItMatters": "Executives need summary first, but operators need the exact rows behind it.",
                "nextBuild": "Make evidence, incidents, dispatches, and ledger records drillable from the brief.",
            },
        ],
    }

    return {
        "status": "ready",
        "mode": "executive_day_brief",
        "generatedAt": _now_iso(),
        "headline": title,
        "primaryIssue": {
            "title": title,
            "severity": str(primary.get("severity") or "watch"),
            "rootCause": root_cause,
            "businessImpact": business_impact,
            "recommendedDecision": recommended,
            "owner": owner,
            "decisionDeadlineMinutes": deadline,
            "confidence": confidence,
            "selectionScore": selected_score or {},
            "selectionRationale": [
                f"Severity contributed {selected_score.get('severityScore', 0)} points.",
                f"Guest impact contributed {selected_score.get('guestImpact', 0)} points from density, wait, incidents, and satisfaction risk.",
                f"Safety/access risk contributed {selected_score.get('safetyAccessRisk', 0)} points.",
                f"Open status contributed {selected_score.get('unresolvedAge', 0)} points.",
            ] if selected_score else [],
        },
        "recommendedDecision": {
            "action": recommended,
            "owner": owner,
            "deadlineMinutes": deadline,
            "approveIf": approve_if,
            "holdIf": hold_if,
            "tradeoff": tradeoff,
            "confidence": confidence,
        },
        "daySummary": {
            "openedAt": "09:00",
            "currentTime": _pressure_curve(state=state, composite=composite, ops_effect=ops_effect, density=density)[-1]["label"],
            "whatChanged": f"Controlled pressure is {composite}/100 with {ops_effect} points of reported mitigation.",
            "unresolvedRisk": mitigation_gap,
            "watchNext": f"{top_path.get('fromName') or top_path.get('from') or 'Main path'} to {top_path.get('toName') or top_path.get('to') or 'next hotspot'}",
        },
        "mitigations": {
            "attempted": [active_policy, *[str(item.get("kind") or item.get("targetId") or "intervention") for item in interventions if isinstance(item, dict)]],
            "observedEffect": f"{ops_effect} pressure points reduced in the current brief model.",
            "remainingGap": mitigation_gap,
        },
        "evidence": evidence[:5],
        "issueTimeline": issue_timeline,
        "decisionAlternatives": sorted(alternatives, key=lambda row: _num(row.get("score")), reverse=True),
        "impactModel": impact_model,
        "learningMemory": learning_memory,
        "productStructure": product_structure,
        "evidenceRollup": [
            {"label": "Guest sample", "value": int(_num(flow.get("representedGuests"))), "detail": f"{int(_num(flow.get('activeGroups')))} groups across {len(zones)} zones."},
            {"label": "Issue corpus", "value": issue_corpus, "detail": f"{incident_count} tickets and {len(issues)} backlog items."},
            {"label": "Human review", "value": human_review, "detail": "Items needing operator judgement."},
            {"label": "Evidence rows", "value": evidence_rows, "detail": "Tickets, backlog, memory, and calibration rows."},
        ],
        "charts": {
            "pressureCurve": _pressure_curve(state=state, composite=composite, ops_effect=ops_effect, density=density),
            "driverBreakdown": driver_rows,
            "domainBreakdown": [{"label": label, "value": value, "max": max(1, incident_count)} for label, value in domain_counts.most_common(5)],
        },
        "priorityQueue": [
            {
                "id": _issue_id(item, index),
                "title": str(item.get("title") or "Open issue"),
                "severity": str(item.get("severity") or "watch"),
                "detail": str(item.get("recommendedHumanCall") or item.get("recommendedNext") or item.get("summary") or "Review issue."),
                "selectionScore": next((score for score in scored_issues if score.get("id") == _issue_id(item, index)), {}),
            }
            for index, item in enumerate([*tickets[:3], *issues[:3]])
        ][:5],
        "operatingSignals": {
            "dominantIntent": guest_intent.get("dominantIntent"),
            "breakPressurePct": staff_lifecycle.get("breakPressurePct"),
            "activeWave": event_schedule.get("activeWave"),
            "fairnessStatus": fairness.get("status"),
        },
    }
