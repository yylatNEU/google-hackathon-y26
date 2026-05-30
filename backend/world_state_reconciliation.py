from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from park_signal_intake import classify_unstructured_signal, realistic_signal_batch


_latest_reconciliation: dict[str, Any] | None = None

SOURCE_RELIABILITY = {
    "ride_telemetry": 0.88,
    "crowd_camera": 0.82,
    "pos_inventory": 0.8,
    "weather_alert": 0.78,
    "worker_quick_tap": 0.74,
    "staff_radio": 0.72,
    "first_aid_dispatch": 0.86,
    "accessibility_request": 0.75,
    "guest_health_report": 0.7,
    "guest_app": 0.62,
    "guest_complaint": 0.58,
    "social_snippet": 0.4,
}

DOMAIN_BY_CATEGORY = {
    "medical": "safety",
    "panic_evacuation": "crowd",
    "crowd_pressure": "crowd",
    "child_care": "guest_care",
    "accessibility": "accessibility",
    "equipment_safety": "equipment",
    "guest_complaint": "guest_care",
    "rumor": "verification",
}


def reconcile_world_state(
    park_state: dict[str, Any],
    raw_signals: list[dict[str, Any]] | None = None,
    preset: str = "crowd_care_conflict",
) -> dict[str, Any]:
    signals = raw_signals if raw_signals is not None else realistic_signal_batch(park_state, preset)
    triaged = [_normalize_signal(signal, park_state) for signal in signals]
    live_claims = _live_state_claims(park_state)
    claims = _claims_from_signals(triaged) + live_claims
    clusters = _cluster_claims(claims)
    beliefs = [_belief_from_cluster(cluster) for cluster in clusters]
    conflicts = _conflicts_from_beliefs(beliefs)
    uncertainty = _uncertainty_from_beliefs(beliefs, conflicts)
    receipts = _action_receipts(beliefs, conflicts, uncertainty)
    result = {
        "status": "complete",
        "mode": "world_state_reconciliation",
        "reconciliation_id": _reconciliation_id(triaged, park_state),
        "created_at": _now(),
        "source_count": len(triaged),
        "claim_count": len(claims),
        "beliefs": beliefs,
        "conflicts": conflicts,
        "uncertainty": uncertainty,
        "action_receipts": receipts,
        "agent_input": {
            "belief_state": _agent_belief_state(beliefs),
            "blocked_assumptions": [item["assumption"] for item in conflicts],
            "requires_operator_review": uncertainty["level"] in {"high", "critical"} or bool(conflicts),
        },
        "signals": triaged,
    }
    global _latest_reconciliation
    _latest_reconciliation = deepcopy(result)
    return result


def latest_reconciliation() -> dict[str, Any]:
    return deepcopy(_latest_reconciliation) if _latest_reconciliation else {"status": "empty", "mode": "world_state_reconciliation"}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _reconciliation_id(signals: list[dict[str, Any]], park_state: dict[str, Any]) -> str:
    raw = "|".join(str(signal.get("id") or signal.get("text", "")) for signal in signals)
    scenario = park_state.get("guestFlow", {}).get("activeScenario", {}).get("key", "unknown")
    return f"reconcile_{hashlib.sha1(f'{scenario}:{raw}'.encode('utf-8')).hexdigest()[:12]}"


def _normalize_signal(signal: dict[str, Any], park_state: dict[str, Any]) -> dict[str, Any]:
    if "categories" in signal and "risk_level" in signal:
        triaged = deepcopy(signal)
    else:
        triaged = classify_unstructured_signal(
            text=str(signal.get("text") or signal.get("body") or signal.get("message") or ""),
            source=str(signal.get("source") or "external_signal"),
            zone_id=signal.get("zoneId") or signal.get("zone_id"),
            reporter_role=signal.get("reporterRole") or signal.get("reporter_role"),
            park_state=park_state,
        )
    source = str(triaged.get("source") or "unknown")
    reliability = float(signal.get("reliability") or SOURCE_RELIABILITY.get(source, 0.55))
    confidence = float(triaged.get("confidence") or signal.get("confidence") or 0.55)
    triaged["source_reliability"] = round(max(0.1, min(0.98, reliability)), 2)
    triaged["belief_weight"] = round(max(0.05, min(0.99, reliability * confidence)), 3)
    return triaged


def _claims_from_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for signal in signals:
        zone = signal.get("zone", {}) if isinstance(signal.get("zone"), dict) else {}
        zone_id = str(zone.get("id") or "unknown")
        for category in signal.get("categories", []) if isinstance(signal.get("categories"), list) else []:
            domain = DOMAIN_BY_CATEGORY.get(str(category), "operations")
            claims.append(
                {
                    "domain": domain,
                    "zone_id": zone_id,
                    "claim": str(category),
                    "polarity": "uncertain" if category == "rumor" else "asserts",
                    "risk_level": signal.get("risk_level"),
                    "weight": signal.get("belief_weight", 0.4),
                    "source": signal.get("source"),
                    "signal_id": signal.get("id"),
                    "detail": signal.get("text") or signal.get("triage_explanation"),
                    "observed_at": signal.get("created_at") or signal.get("createdAt") or _now(),
                }
            )
    return claims


def _live_state_claims(park_state: dict[str, Any]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for zone in park_state.get("guestFlow", {}).get("zones", []) if isinstance(park_state.get("guestFlow", {}).get("zones"), list) else []:
        if not isinstance(zone, dict):
            continue
        density = int(zone.get("density") or 0)
        if density >= 85:
            claims.append(
                {
                    "domain": "crowd",
                    "zone_id": zone.get("id"),
                    "claim": "crowd_pressure",
                    "polarity": "asserts",
                    "risk_level": "HIGH" if density >= 95 else "MEDIUM",
                    "weight": 0.78,
                    "source": "live_crowd_model",
                    "signal_id": f"live_zone_{zone.get('id')}",
                    "detail": f"{zone.get('name', zone.get('id'))} density {density}%",
                    "observed_at": _now(),
                }
            )
    for ride in park_state.get("guestFlow", {}).get("rides", []) if isinstance(park_state.get("guestFlow", {}).get("rides"), list) else []:
        if not isinstance(ride, dict):
            continue
        wait = int(ride.get("waitMins") or 0)
        status = str(ride.get("status") or "open")
        if status != "open" or wait >= 60:
            claims.append(
                {
                    "domain": "ride",
                    "zone_id": ride.get("zoneId") or "coasterPlaza",
                    "claim": "ride_pressure",
                    "polarity": "asserts",
                    "risk_level": "HIGH" if status != "open" else "MEDIUM",
                    "weight": 0.86,
                    "source": "ride_telemetry",
                    "signal_id": f"live_ride_{ride.get('id')}",
                    "detail": f"{ride.get('name', ride.get('id'))} status {status}, wait {wait}m",
                    "observed_at": _now(),
                }
            )
    return claims


def _cluster_claims(claims: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    clusters: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for claim in claims:
        key = (str(claim.get("domain") or "operations"), str(claim.get("zone_id") or "unknown"))
        clusters.setdefault(key, []).append(claim)
    return list(clusters.values())


def _belief_from_cluster(cluster: list[dict[str, Any]]) -> dict[str, Any]:
    total_weight = round(sum(float(item.get("weight") or 0) for item in cluster), 3)
    source_count = len({item.get("source") for item in cluster})
    strongest = sorted(cluster, key=lambda item: float(item.get("weight") or 0), reverse=True)[0]
    risk_rank = {"WATCH": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
    risk = max((str(item.get("risk_level") or "WATCH") for item in cluster), key=lambda item: risk_rank.get(item, 1))
    confidence = min(0.98, 0.34 + min(0.4, total_weight / 4) + min(0.18, source_count * 0.06))
    rumor_weight = sum(float(item.get("weight") or 0) for item in cluster if item.get("polarity") == "uncertain")
    uncertainty = max(0.02, min(0.95, 1 - confidence + rumor_weight * 0.12))
    return {
        "domain": strongest.get("domain"),
        "zone_id": strongest.get("zone_id"),
        "claim": strongest.get("claim"),
        "risk_level": risk,
        "confidence": round(confidence, 2),
        "uncertainty": round(uncertainty, 2),
        "source_count": source_count,
        "evidence_count": len(cluster),
        "evidence": sorted(cluster, key=lambda item: float(item.get("weight") or 0), reverse=True)[:5],
        "agent_read": _agent_read(strongest, risk, confidence, uncertainty),
    }


def _agent_read(strongest: dict[str, Any], risk: str, confidence: float, uncertainty: float) -> str:
    if uncertainty >= 0.45:
        return f"Treat {strongest.get('domain')} signal in {strongest.get('zone_id')} as unresolved; verify before broad automation."
    if risk in {"HIGH", "CRITICAL"}:
        return f"Act on {strongest.get('domain')} risk in {strongest.get('zone_id')} with bounded human-visible controls."
    return f"Monitor {strongest.get('domain')} condition in {strongest.get('zone_id')} and keep evidence attached."


def _conflicts_from_beliefs(beliefs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conflicts = []
    for belief in beliefs:
        sources = {item.get("source") for item in belief.get("evidence", [])}
        has_rumor = any(item.get("polarity") == "uncertain" for item in belief.get("evidence", []))
        live_disagrees = any(str(item.get("source", "")).startswith("live_") for item in belief.get("evidence", [])) and has_rumor
        if belief["uncertainty"] >= 0.42 or live_disagrees:
            conflicts.append(
                {
                    "domain": belief["domain"],
                    "zone_id": belief["zone_id"],
                    "assumption": f"{belief['domain']} state in {belief['zone_id']} is settled",
                    "status": "conflicted" if live_disagrees else "uncertain",
                    "sources": sorted(str(source) for source in sources if source),
                    "resolution": "send worker verification and avoid public messaging until corroborated",
                }
            )
    return conflicts


def _uncertainty_from_beliefs(beliefs: list[dict[str, Any]], conflicts: list[dict[str, Any]]) -> dict[str, Any]:
    max_uncertainty = max((float(item.get("uncertainty") or 0) for item in beliefs), default=0)
    if conflicts and max_uncertainty >= 0.5:
        level = "critical"
    elif conflicts or max_uncertainty >= 0.35:
        level = "high"
    elif max_uncertainty >= 0.2:
        level = "medium"
    else:
        level = "low"
    return {
        "level": level,
        "score": round(max_uncertainty, 2),
        "drivers": [f"{item['domain']}:{item['zone_id']}" for item in sorted(beliefs, key=lambda row: row.get("uncertainty", 0), reverse=True)[:3]],
    }


def _action_receipts(beliefs: list[dict[str, Any]], conflicts: list[dict[str, Any]], uncertainty: dict[str, Any]) -> list[dict[str, Any]]:
    receipts = []
    for belief in sorted(beliefs, key=lambda item: (item["risk_level"] in {"HIGH", "CRITICAL"}, item["confidence"]), reverse=True)[:4]:
        blocked_by_conflict = any(conflict["domain"] == belief["domain"] and conflict["zone_id"] == belief["zone_id"] for conflict in conflicts)
        receipts.append(
            {
                "belief": belief["agent_read"],
                "evidence": [item.get("signal_id") for item in belief.get("evidence", [])],
                "uncertainty": belief["uncertainty"],
                "policy": "bounded_action" if not blocked_by_conflict else "verify_before_broadcast",
                "allowed_action": "dispatch_staff_verification" if blocked_by_conflict else "bounded_operations_response",
                "blocked_action": "broad_guest_messaging" if blocked_by_conflict or uncertainty["level"] in {"high", "critical"} else None,
            }
        )
    return receipts


def _agent_belief_state(beliefs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "top_beliefs": [
            {
                "domain": belief["domain"],
                "zone_id": belief["zone_id"],
                "risk_level": belief["risk_level"],
                "confidence": belief["confidence"],
                "uncertainty": belief["uncertainty"],
                "agent_read": belief["agent_read"],
            }
            for belief in beliefs[:6]
        ]
    }
