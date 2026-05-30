from __future__ import annotations

import asyncio
import json
import os
from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Any

from gemini_hard_timeout import generate_gemini_json_hard_timeout
from gemini_provider import get_gemini_agent_properties


class _NoopSpan:
    def set_attribute(self, *_args, **_kwargs) -> None:
        return None


class _NoopTracer:
    def start_as_current_span(self, *_args, **_kwargs):
        return nullcontext(_NoopSpan())


def _get_tracer(name: str):
    if str(os.getenv("PARKPULSE_ENABLE_OTEL_SPANS", "")).strip().lower() not in {"1", "true", "yes", "on"}:
        return _NoopTracer()
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except Exception:
        return _NoopTracer()


_tracer = _get_tracer("parkpulse.proactive_agent")


def _tone(score: int) -> str:
    if score >= 85:
        return "risk"
    if score >= 65:
        return "watch"
    return "ok"


def _top_zone(zones: list[dict[str, Any]], process_type: str | None = None) -> dict[str, Any]:
    rows = [zone for zone in zones if not process_type or zone.get("processType") == process_type]
    if not rows:
        rows = zones
    return max(rows or [{}], key=lambda zone: int(zone.get("density", 0) or 0))


def _top_path(paths: list[dict[str, Any]]) -> dict[str, Any]:
    return max(paths or [{}], key=lambda path: int(path.get("congestionLevel", 0) or 0))


def _top_ride(rides: list[dict[str, Any]]) -> dict[str, Any]:
    return max(
        rides or [{}],
        key=lambda ride: (
            100 if ride.get("status") == "down" else 40 if ride.get("status") == "constrained" else 0,
            int(ride.get("downtimeRisk", 0) or 0),
            int(ride.get("waitMins", 0) or 0),
            int(ride.get("queueGuests", 0) or 0),
        ),
    )


def _forecast_blocks(busiest_zone: dict[str, Any], busiest_path: dict[str, Any], insights: list[dict[str, Any]]) -> list[dict[str, Any]]:
    density = int(busiest_zone.get("density", 72) or 72)
    congestion = int(busiest_path.get("congestionLevel", 65) or 65)
    risk_count = sum(1 for item in insights if item.get("urgency") == "risk")
    mitigation = min(18, 6 + risk_count * 4)
    return [
        {
            "time": "6:00 PM",
            "baseline_risk": min(100, round(density * 0.55 + congestion * 0.45)),
            "with_proactive_actions": max(0, min(100, round(density * 0.55 + congestion * 0.45) - mitigation)),
            "expected_change": f"-{mitigation} bottleneck risk",
            "reason": "Pre-stage signage, staff, and no-static-queue constraints before arrivals build.",
        },
        {
            "time": "8:00 PM",
            "baseline_risk": min(100, round(density * 0.62 + congestion * 0.5 + 8)),
            "with_proactive_actions": max(0, min(100, round(density * 0.62 + congestion * 0.5 + 8) - mitigation - 4)),
            "expected_change": f"-{mitigation + 4} maze/food spillback risk",
            "reason": "Maze queue, food pop-up, and crowd-control setup are active before peak demand.",
        },
        {
            "time": "10:00 PM",
            "baseline_risk": min(100, round(density * 0.58 + congestion * 0.55 + 12)),
            "with_proactive_actions": max(0, min(100, round(density * 0.58 + congestion * 0.55 + 12) - mitigation - 2)),
            "expected_change": f"-{mitigation + 2} exit-wave risk",
            "reason": "Earlier pre-diversion lowers pressure on the same corridor during the late wave.",
        },
    ]


def _first_json_object(text: str) -> dict[str, Any] | None:
    clean = (text or "").strip()
    if not clean:
        return None
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass
    start = clean.find("{")
    end = clean.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(clean[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def _compact_insights(proactive: dict[str, Any]) -> dict[str, Any]:
    insights = proactive.get("insights", []) if isinstance(proactive, dict) else []
    return {
        "summary": proactive.get("summary", {}),
        "forecast": proactive.get("forecast", [])[:3],
        "insights": [
            {
                "id": item.get("id"),
                "agent": item.get("agent"),
                "kind": item.get("kind"),
                "urgency": item.get("urgency"),
                "trigger": item.get("trigger"),
                "why_now": item.get("why_now"),
                "recommendation": item.get("recommendation"),
                "deadline_minutes": item.get("deadline_minutes"),
                "confidence": item.get("confidence"),
            }
            for item in insights[:4]
            if isinstance(item, dict)
        ],
    }


async def _generate_proactive_json(prompt: dict[str, Any], timeout_seconds: float) -> str:
    result = await generate_gemini_json_hard_timeout(
        prompt,
        timeout_seconds=timeout_seconds,
        max_output_tokens=int(os.getenv("PARKPULSE_PROACTIVE_GEMINI_MAX_OUTPUT_TOKENS", "520")),
        temperature=0.2,
    )
    return str(result.get("text") or "")


def build_proactive_insights(park_state: dict[str, Any]) -> dict[str, Any]:
    flow = park_state.get("guestFlow", {}) if isinstance(park_state, dict) else {}
    zones = flow.get("zones", []) if isinstance(flow, dict) else []
    rides = flow.get("rides", []) if isinstance(flow, dict) else []
    paths = flow.get("paths", []) if isinstance(flow, dict) else []
    weather = park_state.get("weather", {})
    energy = park_state.get("energy", {})
    staffing = park_state.get("staffing", {})
    sim_time = park_state.get("simTime", {})

    busiest_zone = _top_zone(zones)
    food_zone = _top_zone(zones, "food")
    busiest_path = _top_path(paths)
    riskiest_ride = _top_ride(rides)
    hour = int(sim_time.get("hour", 17) or 17)
    minute = int(sim_time.get("minute", 0) or 0)
    minutes_to_event = max(0, (18 * 60) - (hour * 60 + minute))

    insights: list[dict[str, Any]] = []

    if minutes_to_event <= 180:
        insights.append(
            {
                "id": "event_setup_window",
                "agent": "Event Setup Agent",
                "kind": "proactive_event_readiness",
                "urgency": "watch" if minutes_to_event > 45 else "risk",
                "trigger": f"Halloween overlay setup window opens in {minutes_to_event} minutes.",
                "why_now": "Equipment and queue-control moves have long setup dependencies and should not wait for guest congestion.",
                "recommendation": "Pre-stage barricades, portable POS, trash bins, fog, and signage before opening scare-zone queues.",
                "deadline_minutes": max(15, min(90, minutes_to_event)),
                "evidence": ["event starts at 6 PM", "temporary maze needs marked queue", "food and merch need POS/network checks"],
                "proactive_not_reactive": "Acts before the operator reports crowd spillback.",
                "confidence": 0.86,
            }
        )

    heat_index = int(weather.get("heatIndexF", 0) or 0)
    indoor_density = max(
        [int(zone.get("density", 0) or 0) for zone in zones if "indoor" in str(zone.get("name", "")).lower()] or [0]
    )
    if heat_index >= 94 or int(energy.get("gridLoadPercent", 0) or 0) >= 90:
        insights.append(
            {
                "id": "shelter_comfort_preload",
                "agent": "Facilities Agent",
                "kind": "proactive_comfort_guardrail",
                "urgency": _tone(max(heat_index - 10, int(energy.get("gridLoadPercent", 0) or 0))),
                "trigger": f"Heat index {heat_index}F, grid load {energy.get('gridLoadPercent')}%, indoor density {indoor_density}%.",
                "why_now": "Guests will drift indoors during event setup; pre-cooling avoids a later comfort-versus-cost conflict.",
                "recommendation": "Pre-cool indoor hub and arcade shelter zones, shed only noncritical lighting, and block HVAC reductions in active shelter areas.",
                "deadline_minutes": 20,
                "evidence": ["weather.heatIndexF", "energy.gridLoadPercent", "indoor zone density"],
                "proactive_not_reactive": "Prevents comfort degradation before guests complain or shelter demand spikes.",
                "confidence": 0.83,
            }
        )

    open_callouts = int(staffing.get("openCallouts", 0) or 0)
    if open_callouts >= 14:
        insights.append(
            {
                "id": "labor_gap_before_overlay",
                "agent": "Staffing Agent",
                "kind": "proactive_labor_plan",
                "urgency": "risk" if open_callouts >= 20 else "watch",
                "trigger": f"{open_callouts} open callouts before temporary event staffing is added.",
                "why_now": "Scare zones, maze queues, food pop-ups, and guest services all compete for the same flexible labor pool.",
                "recommendation": "Call event standby pool, protect ride-operator minimums, and pre-assign crowd-control staff to maze queue and exit waves.",
                "deadline_minutes": 30,
                "evidence": ["staffing.openCallouts", "event staffing plan", "protected break policy"],
                "proactive_not_reactive": "Avoids discovering the labor shortfall after maze demand peaks.",
                "confidence": 0.88,
            }
        )

    ride_wait = int(riskiest_ride.get("waitMins", 0) or 0)
    ride_queue = int(riskiest_ride.get("queueGuests", 0) or 0)
    if ride_wait >= 45 or riskiest_ride.get("status") != "normal":
        insights.append(
            {
                "id": "queue_pressure_prediversion",
                "agent": "Guest Flow Agent",
                "kind": "proactive_queue_relief",
                "urgency": "risk" if riskiest_ride.get("status") == "down" else "watch",
                "trigger": f"{riskiest_ride.get('name', 'Attraction')} is {riskiest_ride.get('status', 'busy')} with {ride_wait}m wait and {ride_queue} queued.",
                "why_now": "Event overlays add new movement patterns; existing ride pressure will amplify maze and food queues.",
                "recommendation": "Start soft nudges toward low-wait shows, arcade, and food before announcing a hard reroute.",
                "deadline_minutes": 15,
                "evidence": ["ride.status", "ride.waitMins", "ride.queueGuests"],
                "proactive_not_reactive": "Moves a portion of demand before a queue becomes a dead-end crowd.",
                "confidence": 0.81,
            }
        )

    path_congestion = int(busiest_path.get("congestionLevel", 0) or 0)
    if path_congestion >= 65 or int(busiest_zone.get("density", 0) or 0) >= 78:
        insights.append(
            {
                "id": "placement_risk_warning",
                "agent": "Placement Agent",
                "kind": "proactive_layout_constraint",
                "urgency": _tone(max(path_congestion, int(busiest_zone.get("density", 0) or 0))),
                "trigger": f"{busiest_path.get('fromName', 'Path')} to {busiest_path.get('toName', 'next zone')} is {path_congestion}% congested; {busiest_zone.get('name', 'busiest zone')} is {busiest_zone.get('density')}% dense.",
                "why_now": "A scare zone or food queue placed on this corridor would turn a flow-through path into a bottleneck.",
                "recommendation": "Mark this corridor as no-static-queue; use it only for signage, roaming actors, or short photo moments.",
                "deadline_minutes": 10,
                "evidence": ["path.congestionLevel", "zone.density", "temporary placement rules"],
                "proactive_not_reactive": "Flags bad placement before the event plan is executed.",
                "confidence": 0.84,
            }
        )

    if int(food_zone.get("density", 0) or 0) >= 70:
        insights.append(
            {
                "id": "food_pop_up_prestage",
                "agent": "Food Demand Agent",
                "kind": "proactive_food_capacity",
                "urgency": "watch",
                "trigger": f"{food_zone.get('name', 'Food zone')} is already {food_zone.get('density')}% dense before event food demand.",
                "why_now": "Halloween overlays create synchronized food demand after maze exits and scare-zone breaks.",
                "recommendation": "Move one pop-up food station near maze exit, add trash bins, and suppress low-inventory mobile-order items before demand spikes.",
                "deadline_minutes": 25,
                "evidence": ["food zone density", "mobile-order playbook", "event food pop-up plan"],
                "proactive_not_reactive": "Prevents accepting orders the kitchen cannot fulfill.",
                "confidence": 0.79,
            }
        )

    ranked = sorted(
        insights,
        key=lambda item: (0 if item["urgency"] == "risk" else 1 if item["urgency"] == "watch" else 2, item["deadline_minutes"]),
    )
    forecast = _forecast_blocks(busiest_zone, busiest_path, ranked)
    with _tracer.start_as_current_span("parkpulse.proactive_agent.scan") as span:
        span.set_attribute("parkpulse.proactive.insight_count", len(ranked))
        span.set_attribute("parkpulse.proactive.risk_count", sum(1 for item in ranked if item.get("urgency") == "risk"))
        span.set_attribute("parkpulse.proactive.watch_count", sum(1 for item in ranked if item.get("urgency") == "watch"))
        return {
            "proactive_id": f"PP-PRO-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
            "created_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "mode": "proactive_watchtower",
            "lookahead_minutes": 180,
            "summary": {
                "insight_count": len(ranked),
                "risk_count": sum(1 for item in ranked if item.get("urgency") == "risk"),
                "watch_count": sum(1 for item in ranked if item.get("urgency") == "watch"),
                "minutes_to_event": minutes_to_event,
                "busiest_zone": busiest_zone.get("name"),
                "busiest_path": f"{busiest_path.get('fromName', busiest_path.get('from', 'path'))} -> {busiest_path.get('toName', busiest_path.get('to', 'zone'))}",
            },
            "forecast": forecast,
            "insights": ranked[:6],
        }


def build_proactive_eval(proactive: dict[str, Any]) -> dict[str, Any]:
    insights = proactive.get("insights", []) if isinstance(proactive, dict) else []
    risk_count = sum(1 for item in insights if item.get("urgency") == "risk")
    watch_count = sum(1 for item in insights if item.get("urgency") == "watch")
    deadlines = [int(item.get("deadline_minutes", 60) or 60) for item in insights]
    avg_deadline = round(sum(deadlines) / len(deadlines)) if deadlines else 60
    actionability = min(100, 62 + len(insights) * 5 + sum(1 for item in insights if item.get("evidence")) * 3)
    timeliness = max(55, min(100, 105 - avg_deadline + risk_count * 8))
    expected_prevention = min(100, 65 + risk_count * 9 + watch_count * 4)
    false_alarm_risk = max(5, min(45, 32 - risk_count * 5 + max(0, avg_deadline - 45) // 5))
    overall = round(actionability * 0.28 + timeliness * 0.24 + expected_prevention * 0.3 + (100 - false_alarm_risk) * 0.18)
    return {
        "overall": overall,
        "status": "commit_pre_stage_actions" if overall >= 78 and insights else "operator_review" if insights else "no_action",
        "proactive_timeliness": timeliness,
        "actionability": actionability,
        "expected_prevention": expected_prevention,
        "false_alarm_risk": false_alarm_risk,
        "insight_count": len(insights),
        "risk_count": risk_count,
        "watch_count": watch_count,
        "reasoning": (
            f"Proactive eval scored {overall}: {risk_count} risk and {watch_count} watch signals, "
            f"average deadline {avg_deadline} minutes, false-alarm risk {false_alarm_risk}."
        ),
    }


def _fallback_brief(proactive: dict[str, Any], runtime: str, errors: list[str] | None = None) -> dict[str, Any]:
    insights = proactive.get("insights", []) if isinstance(proactive, dict) else []
    top = insights[0] if insights else {}
    commitments = [item.get("id") for item in insights[:3] if item.get("id")]
    return {
        "runtime": runtime,
        "operator_brief": (
            top.get("recommendation")
            or "No urgent proactive action is required. Continue monitoring park event readiness."
        ),
        "why_now": top.get("why_now", "The proactive scan found early signals before an operator-reported incident."),
        "recommended_commitments": commitments,
        "should_revise_event_plan": any(item.get("kind") == "proactive_layout_constraint" for item in insights),
        "plan_revision_prompt": (
            "Revise the Halloween overlay to avoid static queues on congested corridors, protect ride operator minimums, "
            "pre-stage event equipment, and split demand across low-density zones."
        ),
        "errors": errors or [],
    }


async def build_proactive_operator_brief(
    park_state: dict[str, Any],
    proactive: dict[str, Any],
    retrieved_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    props = get_gemini_agent_properties()
    try:
        provider_timeout = float(os.getenv("PARKPULSE_PROACTIVE_GEMINI_TIMEOUT_SECONDS", "8"))
    except ValueError:
        provider_timeout = 8.0
    if not props.ready:
        return _fallback_brief(proactive, "deterministic_fallback", props.readiness_issues)

    prompt = {
        "role": "EventOps proactive planning bridge",
        "task": "Return a compact JSON operator brief from proactive park signals.",
        "constraints": [
            "Use only supplied signals and memory.",
            "Do not automate safety-critical ride controls.",
            "Prefer pre-stage actions that prevent congestion before guests complain.",
            "Keep operator_brief under 45 words.",
            "Return JSON only.",
        ],
        "park_snapshot": {
            "weather": park_state.get("weather", {}),
            "energy": {"gridLoadPercent": park_state.get("energy", {}).get("gridLoadPercent")},
            "staffing": {"openCallouts": park_state.get("staffing", {}).get("openCallouts")},
            "scenario": {
                "key": park_state.get("guestFlow", {}).get("activeScenario", {}).get("key"),
                "name": park_state.get("guestFlow", {}).get("activeScenario", {}).get("name"),
            },
        },
        "proactive_signals": _compact_insights(proactive),
        "mongodb_memory": {
            "playbooks": [
                item.get("_id")
                for item in (retrieved_context or {}).get("retrieved", {}).get("playbooks", [])[:3]
                if isinstance(item, dict)
            ],
            "incidents": [
                item.get("_id")
                for item in (retrieved_context or {}).get("retrieved", {}).get("incidents", [])[:3]
                if isinstance(item, dict)
            ],
        },
        "bigquery_priors": {
            "best_prior": (retrieved_context or {}).get("bigquery_priors", {}).get("best_prior", {})
            if isinstance((retrieved_context or {}).get("bigquery_priors"), dict)
            else {},
            "weakest_prior": (retrieved_context or {}).get("bigquery_priors", {}).get("weakest_prior", {})
            if isinstance((retrieved_context or {}).get("bigquery_priors"), dict)
            else {},
        },
        "relational_context": {
            "latest_run": (retrieved_context or {}).get("relational_context", {}).get("latest_run")
            if isinstance((retrieved_context or {}).get("relational_context"), dict)
            else None,
            "recent_events": (retrieved_context or {}).get("relational_context", {}).get("recent_events", [])[:5]
            if isinstance((retrieved_context or {}).get("relational_context"), dict)
            and isinstance((retrieved_context or {}).get("relational_context", {}).get("recent_events"), list)
            else [],
        },
        "output_contract": {
            "operator_brief": "one paragraph",
            "why_now": "one sentence",
            "recommended_commitments": ["insight_id"],
            "should_revise_event_plan": True,
            "plan_revision_prompt": "specific instruction for the EventOps planner",
        },
    }

    with _tracer.start_as_current_span("parkpulse.proactive_agent.gemini_brief") as span:
        span.set_attribute("parkpulse.proactive.gemini.ready", props.ready)
        span.set_attribute("gen_ai.system", "google_gemini")
        span.set_attribute("gen_ai.request.model", props.model)
        try:
            raw_text = await _generate_proactive_json(prompt, provider_timeout)
            raw = _first_json_object(raw_text) or {}
            brief = _fallback_brief(proactive, props.platform)
            brief.update({key: value for key, value in raw.items() if value not in (None, "", [])})
            brief["runtime"] = props.platform
            brief["latency_strategy"] = "subprocess_hard_timeout_compact_prompt"
            insights = proactive.get("insights", []) if isinstance(proactive, dict) else []
            layout_constraint = any(item.get("kind") == "proactive_layout_constraint" for item in insights if isinstance(item, dict))
            weak_response_risk = any(item.get("kind") in {"proactive_queue_relief", "proactive_food_capacity"} for item in insights if isinstance(item, dict))
            brief["should_revise_event_plan"] = bool(brief.get("should_revise_event_plan")) or layout_constraint or weak_response_risk
            if brief["should_revise_event_plan"] and not brief.get("plan_revision_prompt"):
                brief["plan_revision_prompt"] = (
                    "Revise the Halloween overlay using the early warning signals: avoid static queues on congested paths, "
                    "rebalance food and crowd-control staffing, and update equipment pre-stage assumptions."
                )
            brief["errors"] = []
            span.set_attribute("parkpulse.proactive.brief_runtime", brief["runtime"])
            span.set_attribute("parkpulse.proactive.should_revise_event_plan", bool(brief.get("should_revise_event_plan")))
            return brief
        except Exception as error:
            message = f"Gemini provider timed out after {provider_timeout:g}s" if isinstance(error, asyncio.TimeoutError) else str(error)
            span.set_attribute("parkpulse.proactive.error", message[:500])
            return _fallback_brief(proactive, "deterministic_fallback_after_gemini_error", [message])
