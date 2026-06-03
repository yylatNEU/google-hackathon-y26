from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from executive_experience_evidence import executive_evidence_source_summary


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _num(value: Any, fallback: float = 0) -> float:
    if isinstance(value, bool):
        return fallback
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _clamp(value: float, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, round(value)))


def _severity_label(score: int) -> str:
    if score >= 82:
        return "critical"
    if score >= 64:
        return "watch"
    return "stable"


def _top_ride(state: dict[str, Any]) -> dict[str, Any]:
    flow = _as_dict(state.get("guestFlow"))
    rides = [ride for ride in _as_list(flow.get("rides")) if isinstance(ride, dict)]
    if not rides:
        return {}
    return max(rides, key=lambda ride: _num(ride.get("waitMins")) + _num(ride.get("downtimeRisk")))


def _top_zone(state: dict[str, Any]) -> dict[str, Any]:
    flow = _as_dict(state.get("guestFlow"))
    zones = [zone for zone in _as_list(flow.get("zones")) if isinstance(zone, dict)]
    if not zones:
        return {}
    return max(zones, key=lambda zone: _num(zone.get("density")) + _num(zone.get("waitMins")) * 0.4)


def _issue_titles(backlog: dict[str, Any], domain: str | None = None, limit: int = 3) -> list[str]:
    rows: list[str] = []
    for issue in _as_list(backlog.get("issues")):
        if not isinstance(issue, dict):
            continue
        if domain and str(issue.get("executiveDomain") or issue.get("domain") or "").lower() != domain.lower():
            continue
        title = str(issue.get("title") or issue.get("id") or "").strip()
        if title:
            rows.append(title)
        if len(rows) >= limit:
            break
    return rows


def _recent_action_summaries(ledger: dict[str, Any], limit: int = 3) -> list[str]:
    rows: list[str] = []
    for item in _as_list(ledger.get("items")):
        if not isinstance(item, dict):
            continue
        action = str(item.get("selectedAction") or "").strip()
        score = item.get("evalScore")
        if action:
            rows.append(f"{action} ({score if score is not None else 'unscored'})")
        if len(rows) >= limit:
            break
    return rows


def build_executive_experience_intelligence(
    *,
    state: dict[str, Any],
    backlog: dict[str, Any] | None = None,
    incidents: dict[str, Any] | None = None,
    ledger: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an executive agent-layer view with management authorization boundaries."""

    state = _as_dict(state)
    backlog = _as_dict(backlog)
    incidents = _as_dict(incidents)
    ledger = _as_dict(ledger)
    evidence_source = executive_evidence_source_summary(evidence)

    flow = _as_dict(state.get("guestFlow"))
    care = _as_dict(state.get("guestCare"))
    ops = _as_dict(state.get("parkOps"))
    clock = _as_dict(state.get("operatingClock"))
    feedback = _as_dict(clock.get("guestFeedbackLoop"))
    fairness = _as_dict(clock.get("accessFairness"))
    event_schedule = _as_dict(clock.get("eventSchedule"))
    food_lifecycle = _as_dict(clock.get("foodRetailLifecycle"))
    food_inventory = _as_dict(state.get("foodInventory"))
    locations = [item for item in _as_list(food_inventory.get("locations")) if isinstance(item, dict)]
    food_a = next((item for item in locations if item.get("id") == "foodCourt1"), locations[0] if locations else {})

    avg_satisfaction = _clamp(_num(flow.get("avgSatisfaction")))
    complaint_rate = _clamp(_num(care.get("complaintRatePct")))
    open_cases = int(_num(care.get("openCases")))
    recovery_pressure = _clamp(_num(ops.get("guestRecoveryPressure")))
    fairness_risk = _clamp(_num(fairness.get("publicComplaintRiskPct")))
    feedback_pressure = _clamp(_num(feedback.get("careCaseAccumulationPct")))
    event_risk = _clamp(_num(event_schedule.get("eventTrafficRiskPct")))
    food_pressure = _clamp(_num(food_lifecycle.get("mobileOrderBacklogPressurePct")))
    food_eta = int(_num(food_a.get("pickupEtaMinutes")))
    food_backlog = int(_num(food_a.get("mobileOrderBacklog")))
    top_ride = _top_ride(state)
    top_zone = _top_zone(state)
    ride_downtime_risk = _clamp(_num(top_ride.get("downtimeRisk")))

    trust_damage_score = _clamp(
        (100 - avg_satisfaction) * 0.55
        + complaint_rate * 1.7
        + recovery_pressure * 0.28
        + fairness_risk * 0.24
        + feedback_pressure * 0.22
    )
    communication_gap_score = _clamp(
        fairness_risk * 0.34
        + recovery_pressure * 0.28
        + feedback_pressure * 0.2
        + complaint_rate * 1.15
        + max(0, food_eta - 18) * 1.25
    )
    operations_disruption_score = _clamp(
        ride_downtime_risk * 0.36
        + food_pressure * 0.28
        + event_risk * 0.2
        + _num(top_zone.get("density")) * 0.16
    )

    root_cause = (
        "Negative sentiment is being driven more by unclear communication and weak recovery than by ride downtime alone."
        if communication_gap_score >= operations_disruption_score - 5
        else "Negative sentiment is being driven primarily by operational disruption, with communication still amplifying the impact."
    )
    if ride_downtime_risk >= 70 and communication_gap_score >= 60:
        root_cause = "Ride disruption is visible, but the larger executive risk is the recovery story guests hear afterward."

    refund_reasons = [
        {
            "reason": "Unclear downtime recovery",
            "sharePct": _clamp(22 + communication_gap_score * 0.28 + ride_downtime_risk * 0.08),
            "driver": f"{top_ride.get('name') or 'Top ride'} downtime risk {ride_downtime_risk}%, recovery pressure {recovery_pressure}%.",
            "managementAction": "Approve a policy-safe recovery script and manager-review threshold before promising compensation.",
        },
        {
            "reason": "Food pickup delay",
            "sharePct": _clamp(14 + food_pressure * 0.3 + max(0, food_eta - 15) * 0.55),
            "driver": f"Food Court A backlog {food_backlog}, pickup ETA {food_eta} minutes.",
            "managementAction": "Separate refund approval from capacity relief: suppress unavailable items and message ETA confidence.",
        },
        {
            "reason": "Perceived access unfairness",
            "sharePct": _clamp(10 + fairness_risk * 0.42),
            "driver": f"Fast Lane complaint risk {fairness_risk}%.",
            "managementAction": "Publish plain-language lane-mix explanations and audit offer eligibility by segment.",
        },
    ]
    refund_reasons = sorted(refund_reasons, key=lambda item: item["sharePct"], reverse=True)

    monthly_summary = {
        "period": "current operating month",
        "sentimentMomentum": str(feedback.get("sentimentMomentum") or care.get("sentimentMomentum") or "watch"),
        "negativeDrivers": [
            f"Recovery pressure {recovery_pressure}% with {open_cases} open care cases.",
            f"Complaint rate {complaint_rate}% and satisfaction {avg_satisfaction}%.",
            f"Fairness complaint risk {fairness_risk}% around access-lane expectations.",
        ],
        "positiveDrivers": [
            "Live operations are already connected to evidence, policy gates, and post-action evals.",
            "Executive agents can summarize guest-care themes under a different authorization and policy contract.",
        ],
    }

    before_after_event = {
        "event": _as_dict(event_schedule.get("nextEvent")).get("name") or event_schedule.get("activeWave") or "next timed event",
        "before": {
            "sentiment": "fragile" if trust_damage_score >= 64 else "mixed" if trust_damage_score >= 42 else "stable",
            "riskScore": trust_damage_score,
            "leadingSignal": f"{top_zone.get('name') or 'Top zone'} density {_clamp(_num(top_zone.get('density')))}%.",
        },
        "afterForecast": {
            "sentiment": "deteriorates without clearer recovery" if communication_gap_score >= 60 else "holds if message timing stays targeted",
            "riskScore": _clamp(trust_damage_score + event_risk * 0.18 + communication_gap_score * 0.12),
            "leadingSignal": f"Event traffic risk {event_risk}%.",
        },
    }

    policy_inconsistencies = [
        {
            "policyArea": "Refund and recovery",
            "inconsistency": "Guests may hear operational ETAs before manager-approved compensation boundaries are clear.",
            "evidence": [refund_reasons[0]["driver"], f"openCareCases={open_cases}"],
            "recommendedFix": "Create a single recovery decision table for downtime, food delay, and fairness complaints.",
        },
        {
            "policyArea": "VIP / Fast Lane communication",
            "inconsistency": "Lane-mix operations can be correct while guests perceive the result as unfair.",
            "evidence": [f"publicComplaintRiskPct={fairness_risk}", f"perceivedFairnessScore={fairness.get('perceivedFairnessScore', '--')}"],
            "recommendedFix": "Require guest-facing copy to explain cause, expected duration, and who qualifies for recovery.",
        },
    ]

    competitor_reviews = [
        {
            "competitorTheme": "Transparent downtime expectations",
            "whatGuestsCompare": "Other parks get credit when they explain delay cause, next update time, and recovery options in one message.",
            "ParkPulseResponse": "Use operating evidence to draft short board-safe language, then route offers through approval.",
        },
        {
            "competitorTheme": "Mobile food reliability",
            "whatGuestsCompare": "Guests punish pickup promises that miss by more than a few minutes even when the food quality is fine.",
            "ParkPulseResponse": "Treat menu suppression and ETA confidence as brand controls, not only kitchen controls.",
        },
    ]

    seasonal_improvements = [
        "Pre-write weather, showtime, and ride-downtime recovery briefs before peak weekends.",
        "Add after-event sentiment comparison to every fireworks, Halloween, and holiday operating review.",
        "Track refund reason codes against the operational signal that preceded them, not only the final complaint text.",
    ]

    training_focus = [
        {
            "team": "Guest Care",
            "focus": "Explain what happened, when the next update will arrive, and what recovery options require approval.",
            "whyNow": f"Communication gap score {communication_gap_score}/100.",
        },
        {
            "team": "Frontline Leads",
            "focus": "Escalate ambiguous refund and fairness cases without promising compensation on the floor.",
            "whyNow": f"Fairness risk {fairness_risk}% and {open_cases} open care cases.",
        },
        {
            "team": "Food Operations",
            "focus": "Use ETA confidence and item suppression before pickup delay becomes a care case.",
            "whyNow": f"Food pressure {food_pressure}% with {food_eta}m ETA.",
        },
    ]

    board_update = [
        f"Current guest trust risk is {_severity_label(trust_damage_score)} at {trust_damage_score}/100.",
        root_cause,
        f"Top refund driver: {refund_reasons[0]['reason']} ({refund_reasons[0]['sharePct']}% directional share).",
        "Executive Experience Intelligence is part of the agent layer with management-scoped authority: brief, compare, audit, and recommend without dispatching actions or approving refunds.",
    ]

    executive_briefing = {
        "headline": root_cause,
        "decisionNeeded": "Approve the recovery-message standard and refund review thresholds before the next high-pressure event.",
        "boardUpdateDraft": board_update,
        "evidence": [
            f"avgSatisfaction={avg_satisfaction}",
            f"complaintRatePct={complaint_rate}",
            f"recoveryPressure={recovery_pressure}",
            f"communicationGapScore={communication_gap_score}",
            f"operationsDisruptionScore={operations_disruption_score}",
            *_issue_titles(backlog, "customer_experience", 2),
        ],
    }

    return {
        "status": "ready",
        "mode": "executive_experience_intelligence",
        "generatedAt": _utc_now(),
        "scope": "Agent-layer executive intelligence with management authorization: summarize, compare, audit, brief, and recommend. Policy blocks live dispatch, refund approval, training labels, reward changes, and model promotion.",
        "evidenceSource": evidence_source,
        "agentLayer": {
            "agent": "Executive Experience Intelligence Agent",
            "layer": "agent_intelligence",
            "authorizationCapability": "read_executive_intelligence",
            "defaultRole": "ml_ops_admin",
            "allowedActions": [
                "summarize guest feedback by month",
                "compare sentiment before and after events",
                "analyze refund reasons",
                "draft executive and board briefings",
                "identify policy inconsistencies",
                "summarize competitor review themes",
                "propose seasonal improvements",
                "generate staff training focus areas",
            ],
            "blockedActions": [
                "dispatch live action",
                "approve refund or compensation",
                "write training label or reward",
                "promote or roll back model policy",
                "override guest-care or safety policy",
            ],
        },
        "scores": {
            "trustDamage": trust_damage_score,
            "communicationGap": communication_gap_score,
            "operationsDisruption": operations_disruption_score,
            "status": _severity_label(max(trust_damage_score, communication_gap_score)),
        },
        "monthlyGuestFeedback": monthly_summary,
        "beforeAfterEventSentiment": before_after_event,
        "refundReasonAnalysis": refund_reasons,
        "executiveBriefing": executive_briefing,
        "boardUpdateDraft": board_update,
        "policyInconsistencies": policy_inconsistencies,
        "competitorReviewSummary": competitor_reviews,
        "seasonalImprovements": seasonal_improvements,
        "staffTrainingFocusAreas": training_focus,
        "sourceCoverage": {
            "backlogIssues": len(_as_list(backlog.get("issues"))),
            "incidentTickets": len(_as_list(incidents.get("tickets"))),
            "ledgerRows": len(_as_list(ledger.get("items"))),
            "recentActions": _recent_action_summaries(ledger),
        },
    }
