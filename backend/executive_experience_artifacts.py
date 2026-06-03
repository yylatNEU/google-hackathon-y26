from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any, Callable

from executive_experience_evidence import build_executive_experience_evidence, evidence_hash


FetchDocuments = Callable[[str, int], list[dict[str, Any]]]
RecordDocuments = Callable[[str, list[dict[str, Any]]], dict[str, Any]]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


SIMULATION_SCENARIOS = {
    "downtime_communication_gap": {
        "eventName": "Memorial Weekend Fireworks",
        "primaryTheme": "unclear downtime recovery",
        "secondaryTheme": "late app update cadence",
        "positiveTheme": "staff empathy during disruption",
        "refundCode": "UNCLEAR_RECOVERY",
        "refundLabel": "Unclear downtime recovery",
        "operationalSignal": "ride_down_recovery_pressure",
        "policyArea": "refund_and_recovery",
        "caseType": "ride_downtime_after_event",
        "policySummary": "Similar ride downtime cases used different recovery thresholds across evening shifts.",
        "recommendedFix": "Publish one recovery table for downtime duration, update cadence, and offer eligibility.",
        "competitorTheme": "transparent downtime expectations",
        "trainingTeam": "Guest Care",
        "trainingTopic": "Downtime recovery explanation",
    },
    "refund_policy_inconsistency": {
        "eventName": "Spring Festival",
        "primaryTheme": "inconsistent refund handling",
        "secondaryTheme": "unclear recovery eligibility",
        "positiveTheme": "manager callback clarity",
        "refundCode": "POLICY_EXCEPTION",
        "refundLabel": "Inconsistent policy exception",
        "operationalSignal": "guest_care_exception_pressure",
        "policyArea": "refund_policy",
        "caseType": "similar_guest_recovery_cases",
        "policySummary": "Comparable refund requests received different approval paths and recovery amounts.",
        "recommendedFix": "Standardize refund exception tiers and require reason-code audit notes.",
        "competitorTheme": "clear recovery guarantees",
        "trainingTeam": "Guest Services",
        "trainingTopic": "Refund exception consistency",
    },
    "event_crowding_recovery_failure": {
        "eventName": "Summer Night Market",
        "primaryTheme": "event crowding recovery failure",
        "secondaryTheme": "exit route confusion",
        "positiveTheme": "show quality",
        "refundCode": "EVENT_CROWDING",
        "refundLabel": "Event crowding recovery",
        "operationalSignal": "event_exit_crowding_pressure",
        "policyArea": "event_guest_recovery",
        "caseType": "crowding_after_headliner",
        "policySummary": "Crowding cases were escalated inconsistently when route guidance and recovery offers differed by zone.",
        "recommendedFix": "Pre-approve event crowding recovery scripts and zone-specific response thresholds.",
        "competitorTheme": "clear post-event crowd flow",
        "trainingTeam": "Event Operations",
        "trainingTopic": "Crowding recovery scripts",
    },
    "competitor_service_gap": {
        "eventName": "Holiday Preview",
        "primaryTheme": "competitor service gap",
        "secondaryTheme": "unclear value recovery",
        "positiveTheme": "clean venue presentation",
        "refundCode": "VALUE_GAP",
        "refundLabel": "Perceived value gap",
        "operationalSignal": "competitor_expectation_gap",
        "policyArea": "guest_value_recovery",
        "caseType": "public_review_comparison",
        "policySummary": "Guest-care responses did not consistently address competitor comparisons around proactive recovery.",
        "recommendedFix": "Add competitor benchmark prompts to executive review and recovery playbooks.",
        "competitorTheme": "proactive service recovery",
        "trainingTeam": "Guest Experience",
        "trainingTopic": "Competitor-aware service recovery",
    },
    "training_improves_recovery": {
        "eventName": "Fall Family Weekend",
        "primaryTheme": "recovery quality improving after training",
        "secondaryTheme": "clearer frontline explanation",
        "positiveTheme": "fast recovery follow-up",
        "refundCode": "RECOVERY_IMPROVED",
        "refundLabel": "Recovery issue trending down",
        "operationalSignal": "training_recovery_improvement",
        "policyArea": "training_to_recovery",
        "caseType": "post_training_guest_care",
        "policySummary": "Teams using the new explanation script produced fewer escalations than teams without completion.",
        "recommendedFix": "Require completion for all guest-facing leads before peak events.",
        "competitorTheme": "staff recovery confidence",
        "trainingTeam": "Guest Care",
        "trainingTopic": "Recovery communication certification",
    },
}


def _month_sequence(end_month: str = "2026-05", count: int = 6) -> list[str]:
    safe_count = max(3, min(12, int(count or 6)))
    try:
        year, month = [int(part) for part in str(end_month or "2026-05").split("-", 1)]
    except Exception:
        year, month = 2026, 5
    months = []
    for offset in range(safe_count - 1, -1, -1):
        total = year * 12 + month - 1 - offset
        months.append(f"{total // 12:04d}-{(total % 12) + 1:02d}")
    return months


def simulated_executive_experience_documents(
    *,
    scenario: str = "downtime_communication_gap",
    months: int = 6,
    end_month: str = "2026-05",
) -> dict[str, list[dict[str, Any]]]:
    scenario_id = str(scenario or "downtime_communication_gap").strip().lower().replace("-", "_")
    template = SIMULATION_SCENARIOS.get(scenario_id, SIMULATION_SCENARIOS["downtime_communication_gap"])
    selected_months = _month_sequence(end_month, months)
    shock_index = max(1, len(selected_months) - 2)
    simulation_id = f"sim_{scenario_id}_{selected_months[0].replace('-', '')}_{selected_months[-1].replace('-', '')}"

    documents: dict[str, list[dict[str, Any]]] = {
        "executive_guest_feedback_monthly": [],
        "executive_event_sentiment": [],
        "executive_refund_reason_rollup": [],
        "executive_guest_recovery_actions": [],
        "executive_policy_exception_rollup": [],
        "executive_competitor_review_themes": [],
        "executive_staff_training_outcomes": [],
    }

    for index, month in enumerate(selected_months):
        pressure = 1.0 if index < shock_index else 1.55 if index == shock_index else 1.25
        improvement = scenario_id == "training_improves_recovery" and index > shock_index
        negative_volume = int((84 + index * 9) * (0.7 if improvement else pressure))
        secondary_volume = int((42 + index * 5) * (0.75 if improvement else pressure))
        positive_volume = int((36 + index * 7) * (1.55 if improvement else 1.0))
        event_id = f"{scenario_id}_{month.replace('-', '_')}"

        documents["executive_guest_feedback_monthly"].extend(
            [
                {
                    "_id": f"{simulation_id}_feedback_primary_{month}",
                    "simulationId": simulation_id,
                    "scenario": scenario_id,
                    "month": month,
                    "channel": "synthetic_guest_feedback_rollup",
                    "theme": template["primaryTheme"],
                    "sentiment": "mixed" if improvement else "negative",
                    "volume": negative_volume,
                    "representative_summary": f"Simulated guests link {template['primaryTheme']} to management communication and recovery follow-through.",
                    "source_count": negative_volume,
                    "sourceType": "demo",
                },
                {
                    "_id": f"{simulation_id}_feedback_secondary_{month}",
                    "simulationId": simulation_id,
                    "scenario": scenario_id,
                    "month": month,
                    "channel": "synthetic_support_ticket_rollup",
                    "theme": template["secondaryTheme"],
                    "sentiment": "negative" if not improvement else "mixed",
                    "volume": secondary_volume,
                    "representative_summary": f"Simulated support rollup shows {template['secondaryTheme']} alongside the primary executive theme.",
                    "source_count": secondary_volume,
                    "sourceType": "demo",
                },
                {
                    "_id": f"{simulation_id}_feedback_positive_{month}",
                    "simulationId": simulation_id,
                    "scenario": scenario_id,
                    "month": month,
                    "channel": "synthetic_survey_rollup",
                    "theme": template["positiveTheme"],
                    "sentiment": "positive",
                    "volume": positive_volume,
                    "representative_summary": f"Simulated positive feedback credits {template['positiveTheme']} when teams explain next steps clearly.",
                    "source_count": positive_volume,
                    "sourceType": "demo",
                },
            ]
        )
        documents["executive_refund_reason_rollup"].append(
            {
                "_id": f"{simulation_id}_refund_{month}",
                "simulationId": simulation_id,
                "scenario": scenario_id,
                "month": month,
                "event_id": event_id,
                "reason_code": template["refundCode"],
                "reason_label": template["refundLabel"],
                "count": max(8, int(negative_volume * (0.38 if not improvement else 0.18))),
                "estimated_cost": max(1200, int(negative_volume * (95 if not improvement else 42))),
                "linked_operational_signal": template["operationalSignal"],
                "sourceType": "demo",
            }
        )
        documents["executive_guest_recovery_actions"].append(
            {
                "_id": f"{simulation_id}_recovery_{month}",
                "simulationId": simulation_id,
                "scenario": scenario_id,
                "action_id": f"recovery_{scenario_id}_{month.replace('-', '_')}",
                "incident_id": f"incident_{scenario_id}_{month.replace('-', '_')}",
                "message_type": "executive_simulated_guest_recovery",
                "approved_by_role": "guest_recovery_lead",
                "sent_at": f"{month}-24T22:18:00Z",
                "outcome_summary": "Simulated recovery was timely and clearer after training." if improvement else "Simulated recovery lagged guest complaints and left eligibility unclear.",
                "sourceType": "demo",
            }
        )
        documents["executive_policy_exception_rollup"].append(
            {
                "_id": f"{simulation_id}_policy_{month}",
                "simulationId": simulation_id,
                "scenario": scenario_id,
                "policy_area": template["policyArea"],
                "case_type": template["caseType"],
                "exception_count": max(3, int((negative_volume / 14) * (0.65 if improvement else 1.0))),
                "approval_path": "manager_review",
                "inconsistency_summary": template["policySummary"],
                "recommended_fix": template["recommendedFix"],
                "sourceType": "demo",
            }
        )
        documents["executive_competitor_review_themes"].append(
            {
                "_id": f"{simulation_id}_competitor_{month}",
                "simulationId": simulation_id,
                "scenario": scenario_id,
                "competitor": "Regional peer parks",
                "review_month": month,
                "theme": template["competitorTheme"],
                "sentiment": "positive",
                "sample_count": 24 + index * 6,
                "source": "synthetic_public_review_theme_rollup",
                "summary": f"Simulated competitor review themes reward parks that handle {template['primaryTheme']} with clearer guest communication.",
                "sourceType": "demo",
            }
        )
        documents["executive_staff_training_outcomes"].append(
            {
                "_id": f"{simulation_id}_training_{month}",
                "simulationId": simulation_id,
                "scenario": scenario_id,
                "team": template["trainingTeam"],
                "training_topic": template["trainingTopic"],
                "completion_rate": round(min(0.96, 0.48 + index * 0.07), 2),
                "guest_theme_link": template["primaryTheme"],
                "post_training_delta": "negative escalation down 18 percent" if improvement or index > shock_index else "not_measured_yet",
                "sourceType": "demo",
            }
        )

        if index in {max(0, shock_index - 1), shock_index, len(selected_months) - 1}:
            documents["executive_event_sentiment"].append(
                {
                    "_id": f"{simulation_id}_event_{month}",
                    "simulationId": simulation_id,
                    "scenario": scenario_id,
                    "event_id": event_id,
                    "event_name": template["eventName"],
                    "window_start": f"{month}-24T17:00:00Z",
                    "window_end": f"{month}-25T02:00:00Z",
                    "before_sentiment": "stable" if index < shock_index else "mixed",
                    "after_sentiment": "mixed" if improvement else "negative",
                    "top_positive_themes": [template["positiveTheme"]],
                    "top_negative_themes": [template["primaryTheme"], template["secondaryTheme"]],
                    "sourceType": "demo",
                }
            )

    return documents


def simulate_executive_experience_evidence(
    record_documents: RecordDocuments | None = None,
    fetch_documents: FetchDocuments | None = None,
    *,
    scenario: str = "downtime_communication_gap",
    months: int = 6,
    end_month: str = "2026-05",
) -> dict[str, Any]:
    if record_documents is None:
        from mongo_memory import record_executive_experience_documents

        record_documents = record_executive_experience_documents

    documents_by_collection = simulated_executive_experience_documents(scenario=scenario, months=months, end_month=end_month)
    persistence = [record_documents(collection, documents) for collection, documents in documents_by_collection.items()]
    evidence = build_executive_experience_evidence(fetch_documents)
    stored_count = sum(_safe_int(row.get("storedCount")) for row in persistence)
    return {
        "status": "simulated",
        "mode": "executive_experience_simulated_import",
        "scenario": str(scenario or "downtime_communication_gap").strip().lower().replace("-", "_"),
        "months": _month_sequence(end_month, months),
        "simulatedAt": _utc_now(),
        "collections": list(documents_by_collection),
        "storedCount": stored_count,
        "persistence": persistence,
        "evidence": evidence,
        "sourceType": "demo",
        "policyBoundary": "Simulated evidence is scenario-shaped demo data only. It is useful for testing analysis, but it cannot support final executive approval.",
    }


def demo_executive_experience_documents() -> dict[str, list[dict[str, Any]]]:
    return {
        "executive_guest_feedback_monthly": [
            {
                "_id": "exec_demo_feedback_2026_05_app_recovery",
                "month": "2026-05",
                "channel": "app_feedback",
                "theme": "unclear downtime recovery",
                "sentiment": "negative",
                "volume": 184,
                "representative_summary": "Guests understood the ride was down, but did not know when the next update or recovery option would arrive.",
                "source_count": 184,
                "sourceType": "demo",
            },
            {
                "_id": "exec_demo_feedback_2026_05_food_eta",
                "month": "2026-05",
                "channel": "support_tickets",
                "theme": "mobile food ETA trust",
                "sentiment": "negative",
                "volume": 96,
                "representative_summary": "Pickup promises missed expectations during peak demand.",
                "source_count": 96,
                "sourceType": "demo",
            },
            {
                "_id": "exec_demo_feedback_2026_05_staff_help",
                "month": "2026-05",
                "channel": "survey",
                "theme": "staff empathy during disruption",
                "sentiment": "positive",
                "volume": 73,
                "representative_summary": "Guests gave credit when frontline staff explained next steps clearly.",
                "source_count": 73,
                "sourceType": "demo",
            },
        ],
        "executive_event_sentiment": [
            {
                "_id": "exec_demo_event_fireworks_2026_05_24",
                "event_id": "fireworks_2026_05_24",
                "event_name": "Memorial Weekend Fireworks",
                "window_start": "2026-05-24T17:00:00Z",
                "window_end": "2026-05-25T02:00:00Z",
                "before_sentiment": "mixed",
                "after_sentiment": "negative",
                "top_positive_themes": ["staff empathy", "show quality"],
                "top_negative_themes": ["unclear downtime recovery", "food ETA drift", "exit crowding"],
                "sourceType": "demo",
            },
            {
                "_id": "exec_demo_event_spring_festival_2026_05_10",
                "event_id": "spring_festival_2026_05_10",
                "event_name": "Spring Festival",
                "window_start": "2026-05-10T15:00:00Z",
                "window_end": "2026-05-11T01:00:00Z",
                "before_sentiment": "stable",
                "after_sentiment": "mixed",
                "top_positive_themes": ["entertainment", "clear route signage"],
                "top_negative_themes": ["food ETA drift"],
                "sourceType": "demo",
            },
        ],
        "executive_refund_reason_rollup": [
            {
                "_id": "exec_demo_refund_2026_05_recovery",
                "month": "2026-05",
                "event_id": "fireworks_2026_05_24",
                "reason_code": "UNCLEAR_RECOVERY",
                "reason_label": "Unclear downtime recovery",
                "count": 141,
                "estimated_cost": 18200,
                "linked_operational_signal": "ride_down_recovery_pressure",
                "sourceType": "demo",
            },
            {
                "_id": "exec_demo_refund_2026_05_food_eta",
                "month": "2026-05",
                "event_id": "spring_festival_2026_05_10",
                "reason_code": "FOOD_PICKUP_DELAY",
                "reason_label": "Food pickup delay",
                "count": 84,
                "estimated_cost": 7600,
                "linked_operational_signal": "mobile_order_backlog",
                "sourceType": "demo",
            },
        ],
        "executive_guest_recovery_actions": [
            {
                "_id": "exec_demo_recovery_ride_2026_05_24",
                "action_id": "recovery_ride_2026_05_24",
                "incident_id": "ride_down_fireworks_2026_05_24",
                "message_type": "downtime_update",
                "approved_by_role": "guest_recovery_lead",
                "sent_at": "2026-05-24T22:18:00Z",
                "audience_segment": "affected_ride_guests",
                "outcome_summary": "Message was approved but sent after complaints had already increased.",
                "sourceType": "demo",
            }
        ],
        "executive_policy_exception_rollup": [
            {
                "_id": "exec_demo_policy_refund_threshold_2026_05",
                "policy_area": "refund_and_recovery",
                "case_type": "ride_downtime_after_event",
                "exception_count": 18,
                "approval_path": "manager_review",
                "inconsistency_summary": "Similar ride downtime cases used different recovery thresholds across two evening shifts.",
                "recommended_fix": "Publish one recovery decision table for downtime duration, update cadence, and offer eligibility.",
                "sourceType": "demo",
            }
        ],
        "executive_competitor_review_themes": [
            {
                "_id": "exec_demo_competitor_downtime_clarity_2026_05",
                "competitor": "Regional peer parks",
                "review_month": "2026-05",
                "theme": "transparent downtime expectations",
                "sentiment": "positive",
                "sample_count": 67,
                "source": "public_review_theme_rollup",
                "summary": "Peer parks receive better reviews when downtime messages include cause, next update time, and recovery path.",
                "sourceType": "demo",
            }
        ],
        "executive_staff_training_outcomes": [
            {
                "_id": "exec_demo_training_guest_care_2026_05",
                "team": "Guest Care",
                "training_topic": "Downtime recovery explanation",
                "completion_rate": 0.64,
                "guest_theme_link": "unclear downtime recovery",
                "post_training_delta": "not_measured_yet",
                "sourceType": "demo",
            }
        ],
    }


def import_demo_executive_experience_evidence(
    record_documents: RecordDocuments | None = None,
    fetch_documents: FetchDocuments | None = None,
) -> dict[str, Any]:
    if record_documents is None:
        from mongo_memory import record_executive_experience_documents

        record_documents = record_executive_experience_documents

    persistence = []
    for collection, documents in demo_executive_experience_documents().items():
        persistence.append(record_documents(collection, documents))

    evidence = build_executive_experience_evidence(fetch_documents)
    return {
        "status": "imported",
        "mode": "executive_experience_demo_import",
        "importedAt": _utc_now(),
        "collections": [row.get("collection") for row in persistence],
        "storedCount": sum(_safe_int(row.get("storedCount")) for row in persistence),
        "persistence": persistence,
        "evidence": evidence,
        "policyBoundary": "Demo import writes curated aggregate evidence only. It does not import raw guest text, private identifiers, payment data, medical details, or staff-private notes.",
    }


def build_monthly_guest_feedback_brief(
    fetch_documents: FetchDocuments | None = None,
    *,
    month: str | None = None,
    requested_by_role: str = "ml_ops_admin",
) -> dict[str, Any]:
    if fetch_documents is None:
        from mongo_memory import get_latest_memory_documents_fast

        fetch_documents = get_latest_memory_documents_fast

    evidence = build_executive_experience_evidence(fetch_documents)
    feedback_rows = fetch_documents("executive_guest_feedback_monthly", 100)
    refund_rows = fetch_documents("executive_refund_reason_rollup", 100)
    event_rows = fetch_documents("executive_event_sentiment", 100)
    policy_rows = fetch_documents("executive_policy_exception_rollup", 50)
    competitor_rows = fetch_documents("executive_competitor_review_themes", 50)
    training_rows = fetch_documents("executive_staff_training_outcomes", 50)
    existing_artifacts = fetch_documents("executive_brief_artifacts", 100)

    months = sorted({str(row.get("month")) for row in feedback_rows + refund_rows if isinstance(row, dict) and row.get("month")})
    selected_month = month or (months[-1] if months else "unknown")
    monthly_feedback = [row for row in feedback_rows if str(row.get("month") or selected_month) == selected_month]
    monthly_refunds = [row for row in refund_rows if str(row.get("month") or selected_month) == selected_month]
    theme_counts = Counter()
    negative_themes: list[str] = []
    positive_themes: list[str] = []
    for row in monthly_feedback:
        theme = str(row.get("theme") or "unknown_theme")
        theme_counts[theme] += _safe_int(row.get("volume") or row.get("source_count"))
        sentiment = str(row.get("sentiment") or "").lower()
        if sentiment == "negative":
            negative_themes.append(theme)
        elif sentiment == "positive":
            positive_themes.append(theme)

    top_theme = theme_counts.most_common(1)[0][0] if theme_counts else "insufficient evidence"
    top_refund = sorted(monthly_refunds, key=lambda row: _safe_int(row.get("count")), reverse=True)[0] if monthly_refunds else {}
    communication_terms = ("communication", "unclear", "recovery", "update", "fairness")
    communication_driven = any(term in top_theme.lower() for term in communication_terms) or any(term in str(top_refund.get("reason_label", "")).lower() for term in communication_terms)
    root_cause = (
        "Negative sentiment is primarily tied to communication and recovery after disruption."
        if communication_driven
        else "Negative sentiment is primarily tied to operational disruption, with limited evidence about recovery quality."
    )

    artifact_base_id = f"exec_monthly_guest_feedback_brief_{selected_month.replace('-', '_')}"
    previous_versions = [
        row
        for row in existing_artifacts
        if str(row.get("artifactBaseId") or "").strip() == artifact_base_id
        or str(row.get("artifactId") or row.get("_id") or "").startswith(artifact_base_id)
    ]
    next_version = max((_safe_int(row.get("version")) for row in previous_versions), default=0) + 1
    previous_artifact_id = sorted(
        (str(row.get("artifactId") or row.get("_id") or "") for row in previous_versions if row.get("artifactId") or row.get("_id")),
        reverse=True,
    )[0] if previous_versions else None
    artifact_id = f"{artifact_base_id}_v{next_version}"
    source_coverage = evidence.get("sourceCoverage", {}) if isinstance(evidence.get("sourceCoverage"), dict) else {}
    evidence_summary = evidence.get("summary", {}) if isinstance(evidence.get("summary"), dict) else {}
    source_type_counts = evidence_summary.get("sourceTypeCounts", {}) if isinstance(evidence_summary.get("sourceTypeCounts"), dict) else {}
    contains_demo_evidence = bool(evidence_summary.get("containsDemoEvidence"))
    generated_from_evidence_hash = evidence_hash(
        {
            "month": selected_month,
            "sourceCoverage": source_coverage,
            "feedback": monthly_feedback,
            "refunds": monthly_refunds,
            "events": event_rows,
            "policy": policy_rows,
            "competitors": competitor_rows,
            "training": training_rows,
        }
    )
    artifact = {
        "_id": artifact_id,
        "artifactId": artifact_id,
        "artifactBaseId": artifact_base_id,
        "version": next_version,
        "previousArtifactId": previous_artifact_id,
        "generatedFromEvidenceHash": generated_from_evidence_hash,
        "artifactType": "monthly_guest_feedback_brief",
        "status": "draft_ready",
        "reviewerStatus": "draft_pending_human_review",
        "generatedAt": _utc_now(),
        "requestedByRole": requested_by_role,
        "month": selected_month,
        "headline": root_cause,
        "boardSafeSummary": [
            f"For {selected_month}, the strongest guest-experience theme is {top_theme}.",
            root_cause,
            f"Top refund reason: {top_refund.get('reason_label') or 'insufficient refund evidence'}.",
            f"Evidence confidence: {evidence_summary.get('overallConfidence', 'none')} ({evidence_summary.get('basis', 'live_operational_proxies_only')}).",
        ],
        "internalSummary": {
            "negativeThemes": sorted(set(negative_themes)),
            "positiveThemes": sorted(set(positive_themes)),
            "topThemeVolumes": [{"theme": theme, "volume": volume} for theme, volume in theme_counts.most_common(5)],
            "refundReasons": [
                {
                    "reasonCode": row.get("reason_code"),
                    "reasonLabel": row.get("reason_label"),
                    "count": row.get("count"),
                    "estimatedCost": row.get("estimated_cost"),
                    "linkedOperationalSignal": row.get("linked_operational_signal"),
                }
                for row in sorted(monthly_refunds, key=lambda item: _safe_int(item.get("count")), reverse=True)[:5]
            ],
            "eventWindows": [{"eventId": row.get("event_id"), "eventName": row.get("event_name"), "before": row.get("before_sentiment"), "after": row.get("after_sentiment")} for row in event_rows[:5]],
            "policyFindings": [{"policyArea": row.get("policy_area"), "summary": row.get("inconsistency_summary"), "recommendedFix": row.get("recommended_fix")} for row in policy_rows[:5]],
            "competitorThemes": [{"theme": row.get("theme"), "summary": row.get("summary")} for row in competitor_rows[:5]],
            "trainingFocus": [{"team": row.get("team"), "topic": row.get("training_topic"), "delta": row.get("post_training_delta")} for row in training_rows[:5]],
        },
        "sourceCoverage": source_coverage,
        "sourceTypeCounts": source_type_counts,
        "containsDemoEvidence": contains_demo_evidence,
        "evidenceGaps": evidence.get("missingDataProducts", []),
        "readyDataProducts": evidence.get("readyDataProducts", []),
        "partialDataProducts": evidence.get("partialDataProducts", []),
        "recommendedOwner": "VP Guest Experience",
        "reviewRequired": True,
        "privacyBoundary": evidence.get("privacyBoundary"),
        "policyBoundary": evidence.get("policyBoundary"),
        "blockedActions": ["dispatch live action", "approve refund", "write training label", "promote model", "override guest-care policy"],
    }
    return artifact


def save_monthly_guest_feedback_brief(
    record_documents: RecordDocuments | None = None,
    fetch_documents: FetchDocuments | None = None,
    *,
    month: str | None = None,
    requested_by_role: str = "ml_ops_admin",
) -> dict[str, Any]:
    if record_documents is None:
        from mongo_memory import record_executive_experience_documents

        record_documents = record_executive_experience_documents

    artifact = build_monthly_guest_feedback_brief(fetch_documents, month=month, requested_by_role=requested_by_role)
    persistence = record_documents("executive_brief_artifacts", [artifact])
    return {
        "status": "stored" if persistence.get("status") == "stored" else persistence.get("status", "unknown"),
        "mode": "executive_experience_monthly_brief_artifact",
        "artifact": artifact,
        "persistence": persistence,
    }


def review_executive_experience_artifact(
    artifact_id: str,
    action: str,
    *,
    note: str = "",
    reviewer_role: str = "ml_ops_admin",
    reviewer: str = "executive-reviewer",
    allow_demo_approval: bool = False,
    record_documents: RecordDocuments | None = None,
    fetch_documents: FetchDocuments | None = None,
) -> dict[str, Any]:
    if record_documents is None:
        from mongo_memory import record_executive_experience_documents

        record_documents = record_executive_experience_documents
    if fetch_documents is None:
        from mongo_memory import get_latest_memory_documents_fast

        fetch_documents = get_latest_memory_documents_fast

    normalized_action = str(action or "").strip().lower().replace("-", "_")
    action_status = {
        "approve": ("approved_for_board_use", "approved"),
        "reject": ("rejected", "rejected"),
        "request_revision": ("revision_requested", "revision_requested"),
    }
    if normalized_action not in action_status:
        return {
            "status": "blocked",
            "mode": "executive_experience_artifact_review",
            "artifactId": artifact_id,
            "reason": "Unsupported review action.",
            "allowedActions": sorted(action_status),
        }

    artifacts = fetch_documents("executive_brief_artifacts", 100)
    artifact = next(
        (
            row
            for row in artifacts
            if str(row.get("artifactId") or row.get("_id") or row.get("id")) == str(artifact_id)
        ),
        None,
    )
    if not artifact:
        return {
            "status": "not_found",
            "mode": "executive_experience_artifact_review",
            "artifactId": artifact_id,
            "reason": "Executive artifact was not found.",
        }

    current_review_status = str(artifact.get("reviewerStatus") or "")
    if current_review_status in {"approved", "rejected"}:
        return {
            "status": "blocked",
            "mode": "executive_experience_artifact_review",
            "artifactId": artifact_id,
            "reason": f"Artifact is already final: {current_review_status}.",
            "artifact": artifact,
        }
    if normalized_action == "approve" and artifact.get("containsDemoEvidence") and not allow_demo_approval:
        return {
            "status": "blocked",
            "mode": "executive_experience_artifact_review",
            "artifactId": artifact_id,
            "reason": "Demo-backed executive artifacts cannot be approved for final use. Regenerate with curated live/imported evidence or explicitly allow demo approval in a non-production demo.",
            "artifact": artifact,
        }

    next_status, next_reviewer_status = action_status[normalized_action]
    review_event = {
        "action": normalized_action,
        "reviewerRole": reviewer_role,
        "reviewer": reviewer,
        "note": note,
        "reviewedAt": _utc_now(),
        "fromStatus": current_review_status or artifact.get("status"),
        "toStatus": next_reviewer_status,
    }
    updated_artifact = {
        **artifact,
        "status": next_status,
        "reviewerStatus": next_reviewer_status,
        "reviewRequired": next_reviewer_status == "revision_requested",
        "reviewedAt": review_event["reviewedAt"],
        "reviewedByRole": reviewer_role,
        "reviewedBy": reviewer,
        "reviewNote": note,
        "reviewEvents": [*_as_list(artifact.get("reviewEvents")), review_event],
    }
    persistence = record_documents("executive_brief_artifacts", [updated_artifact])
    return {
        "status": "stored" if persistence.get("status") == "stored" else persistence.get("status", "unknown"),
        "mode": "executive_experience_artifact_review",
        "artifactId": artifact_id,
        "action": normalized_action,
        "artifact": updated_artifact,
        "persistence": persistence,
    }
