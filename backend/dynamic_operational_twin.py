from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Policy:
    id: str
    label: str
    decision_mode: str


@dataclass
class TwinState:
    minute: int
    outdoor_guest_pool: float
    indoor_queue: float
    food_queue: float
    show_buffer: float
    staff_available: float
    satisfaction: float
    notifications_sent: bool = False
    backup_food_open: bool = False
    staff_transfer_started: bool = False
    staff_arrival_minute: int | None = None
    parade_delayed: bool = False


ACTIVE_GUESTS = 18_000
TICK_MINUTES = 5
HORIZON_MINUTES = 180
INDOOR_CAPACITY_PER_HOUR = 5_100
FOOD_CAPACITY_PER_HOUR = 3_200
SHOW_ABSORPTION_PER_TICK = 420


POLICIES = [
    Policy("do_nothing", "Policy A: No decision rules", "none"),
    Policy("notify", "Policy B: Weather-risk guest nudge rule", "guest_nudge_rules"),
    Policy("full_intervention", "Policy C: Operations rule stack", "operations_rules"),
]


def run_thunderstorm_mvp(tick_minutes: int = TICK_MINUTES, horizon_minutes: int = HORIZON_MINUTES) -> dict[str, Any]:
    """Run the discrete-time dynamic twin MVP for the thunderstorm scenario."""

    safe_tick = max(1, min(15, int(tick_minutes or TICK_MINUTES)))
    safe_horizon = max(safe_tick, min(360, int(horizon_minutes or HORIZON_MINUTES)))
    runs = [_simulate_policy(policy, safe_tick, safe_horizon) for policy in POLICIES]
    best = min(runs, key=lambda run: run["summary"]["peakIndoorQueuePressure"])
    satisfaction_best = max(runs, key=lambda run: run["summary"]["finalGuestSatisfaction"])

    return {
        "status": "success",
        "mode": "dynamic_operational_twin_mvp",
        "scenario": {
            "id": "thunderstorm_90_min",
            "title": "Thunderstorm in 90 minutes",
            "totalGuests": ACTIVE_GUESTS,
            "tickMinutes": safe_tick,
            "horizonMinutes": safe_horizon,
            "initialConditions": {
                "outdoorRideDemandPct": 35,
                "indoorRideCapacityPct": 70,
                "foodCourtCapacityPct": 80,
            },
        },
        "engines": [
            "guest_flow",
            "queue",
            "capacity",
            "staff_constraint",
            "weather",
            "rule_derived_decision_intervention",
        ],
        "decisionModel": {
            "mode": "simple_rules_derived",
            "llmRole": "The LLM should explain the rule trace and tradeoffs. It is not the physics engine.",
            "rules": _decision_rules_catalog(),
        },
        "policies": runs,
        "comparison": {
            "lowestIndoorPressurePolicy": best["policyId"],
            "highestSatisfactionPolicy": satisfaction_best["policyId"],
            "headline": (
                "The rule-derived operations branch absorbs storm displacement earlier: "
                f"peak indoor pressure {best['summary']['peakIndoorQueuePressure']}% "
                f"and final satisfaction {satisfaction_best['summary']['finalGuestSatisfaction']}."
            ),
        },
    }


def _simulate_policy(policy: Policy, tick_minutes: int, horizon_minutes: int) -> dict[str, Any]:
    state = TwinState(
        minute=0,
        outdoor_guest_pool=ACTIVE_GUESTS * 0.35,
        indoor_queue=1_190.0,
        food_queue=1_280.0,
        show_buffer=600.0,
        staff_available=118.0,
        satisfaction=84.0,
    )
    points: list[dict[str, Any]] = []
    interventions: list[dict[str, Any]] = []

    for minute in range(0, horizon_minutes + tick_minutes, tick_minutes):
        state.minute = minute
        weather = _weather_state(minute)
        closure_risk = _closure_risk(weather)
        lightning_closed = weather["lightning"] or closure_risk >= 92

        if state.staff_arrival_minute is not None and minute >= state.staff_arrival_minute:
            state.staff_available = 132.0

        if minute > 0:
            _advance_tick(state, policy, weather, closure_risk, lightning_closed, tick_minutes)

        indoor_pressure = _pressure_pct(state.indoor_queue, INDOOR_CAPACITY_PER_HOUR)
        food_wait = _wait_minutes(state.food_queue, _food_capacity_per_hour(state))
        staff_stress = _staff_stress(state, indoor_pressure, food_wait, weather)
        rule_firings = _apply_policy_rules(
            policy=policy,
            state=state,
            weather=weather,
            closure_risk=closure_risk,
            indoor_pressure=indoor_pressure,
            food_wait=food_wait,
            staff_stress=staff_stress,
        )
        interventions.extend(rule_firings)

        if rule_firings:
            indoor_pressure = _pressure_pct(state.indoor_queue, INDOOR_CAPACITY_PER_HOUR)
            food_wait = _wait_minutes(state.food_queue, _food_capacity_per_hour(state))
            staff_stress = _staff_stress(state, indoor_pressure, food_wait, weather)

        points.append(
            {
                "minute": minute,
                "label": _time_label(minute),
                "weatherRisk": round(weather["stormRisk"]),
                "indoorQueuePressure": indoor_pressure,
                "foodWaitMinutes": round(food_wait, 1),
                "staffStress": round(staff_stress, 2),
                "guestSatisfaction": round(state.satisfaction, 1),
                "outdoorClosureRisk": round(closure_risk),
                "outdoorRidesClosed": lightning_closed,
                "indoorQueueGuests": round(state.indoor_queue),
                "foodQueueGuests": round(state.food_queue),
                "showBufferGuests": round(state.show_buffer),
                "activeRuleIds": [rule["ruleId"] for rule in rule_firings],
            }
        )

    summary = _summary(points)
    return {
        "policyId": policy.id,
        "policyLabel": policy.label,
        "decisionMode": policy.decision_mode,
        "interventions": interventions,
        "series": points,
        "summary": summary,
        "analystReadout": _analyst_readout(policy, summary),
    }


def _advance_tick(state: TwinState, policy: Policy, weather: dict[str, Any], closure_risk: float, lightning_closed: bool, tick_minutes: int) -> None:
    risk_factor = weather["stormRisk"] / 100.0
    closure_factor = 1.0 if lightning_closed else max(0.0, (closure_risk - 55.0) / 45.0)
    displaced = min(state.outdoor_guest_pool, (260 + 720 * closure_factor + 120 * risk_factor) * (tick_minutes / TICK_MINUTES))
    state.outdoor_guest_pool = max(0.0, state.outdoor_guest_pool - displaced)

    notification = 1.0 if state.notifications_sent else 0.0
    backup_food = 1.0 if state.backup_food_open else 0.0
    show_share = 0.13 + 0.19 * notification + 0.08 * backup_food + (0.08 if state.parade_delayed else 0.0)
    food_share = 0.22 + 0.05 * risk_factor - 0.05 * backup_food
    indoor_share = max(0.18, 1.0 - show_share - food_share - 0.14)

    show_arrivals = displaced * show_share
    food_arrivals = displaced * food_share + 138 + 95 * risk_factor
    indoor_arrivals = displaced * indoor_share + 395 + 180 * risk_factor

    state.show_buffer = max(0.0, state.show_buffer + show_arrivals - SHOW_ABSORPTION_PER_TICK * (1.25 if state.parade_delayed else 1.0))
    indoor_arrivals += max(0.0, state.show_buffer - 1_200) * 0.08

    indoor_processed = INDOOR_CAPACITY_PER_HOUR * tick_minutes / 60.0
    if state.staff_available < 124:
        indoor_processed *= 0.95
    state.indoor_queue = max(0.0, state.indoor_queue + indoor_arrivals - indoor_processed)

    food_processed = _food_capacity_per_hour(state) * tick_minutes / 60.0
    state.food_queue = max(0.0, state.food_queue + food_arrivals - food_processed)

    indoor_wait = _wait_minutes(state.indoor_queue, INDOOR_CAPACITY_PER_HOUR)
    food_wait = _wait_minutes(state.food_queue, _food_capacity_per_hour(state))
    abandoned = _abandonment_guests(indoor_wait, state.indoor_queue) + _abandonment_guests(food_wait, state.food_queue) * 0.45
    if abandoned:
        state.indoor_queue = max(0.0, state.indoor_queue - abandoned * 0.62)
        state.food_queue = max(0.0, state.food_queue - abandoned * 0.18)
        state.show_buffer += abandoned * (0.32 + 0.15 * notification)

    satisfaction_delta = -0.10 - indoor_wait * 0.012 - food_wait * 0.018 - risk_factor * 0.32
    if state.notifications_sent:
        satisfaction_delta += 0.16
    if state.backup_food_open:
        satisfaction_delta += 0.12
    if state.parade_delayed:
        satisfaction_delta += 0.10
    if state.staff_available >= 132:
        satisfaction_delta += 0.08
    state.satisfaction = max(35.0, min(90.0, state.satisfaction + satisfaction_delta))


def _weather_state(minute: int) -> dict[str, Any]:
    if minute <= 90:
        risk = 30 + (minute / 90) * 60
    elif minute <= 120:
        risk = 92 + ((minute - 90) / 30) * 6
    elif minute <= 150:
        risk = 98 - ((minute - 120) / 30) * 6
    else:
        risk = max(38, 92 - ((minute - 150) / 30) * 36)
    return {
        "stormRisk": risk,
        "rain": minute >= 75,
        "lightning": 90 <= minute <= 150,
    }


def _decision_rules_catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": "weather_guest_nudge",
            "policyIds": ["notify", "full_intervention"],
            "condition": "stormRisk >= 45 and no guest notification has been sent",
            "action": "send targeted guest rerouting notification",
        },
        {
            "id": "closure_show_absorber",
            "policyIds": ["full_intervention"],
            "condition": "outdoorClosureRisk >= 58 and parade/show absorber is not active",
            "action": "delay parade and extend indoor show capacity",
        },
        {
            "id": "food_capacity_trigger",
            "policyIds": ["full_intervention"],
            "condition": "foodWaitMinutes >= 22 and backup food stand is closed",
            "action": "open backup food stand",
        },
        {
            "id": "staff_stress_transfer",
            "policyIds": ["full_intervention"],
            "condition": "staffStress >= 1.08 and transferred staff are not already moving",
            "action": "start staff transfer with a 15-minute delayed effect",
        },
    ]


def _apply_policy_rules(
    *,
    policy: Policy,
    state: TwinState,
    weather: dict[str, Any],
    closure_risk: float,
    indoor_pressure: int,
    food_wait: float,
    staff_stress: float,
) -> list[dict[str, Any]]:
    if policy.decision_mode == "none":
        return []

    fired: list[dict[str, Any]] = []

    if policy.decision_mode in {"guest_nudge_rules", "operations_rules"} and weather["stormRisk"] >= 45 and not state.notifications_sent:
        state.notifications_sent = True
        fired.append(
            _rule_firing(
                state.minute,
                "weather_guest_nudge",
                "Targeted guest rerouting notification sent",
                f"stormRisk={round(weather['stormRisk'])} crossed 45; indoorQueuePressure={indoor_pressure}%.",
                "More displaced guests choose shows, retail, and lower-pressure food paths on later ticks.",
            )
        )

    if policy.decision_mode != "operations_rules":
        return fired

    if closure_risk >= 58 and not state.parade_delayed:
        state.parade_delayed = True
        fired.append(
            _rule_firing(
                state.minute,
                "closure_show_absorber",
                "Parade delayed and indoor show window extended",
                f"outdoorClosureRisk={round(closure_risk)} crossed 58.",
                "Show venue absorbs guest overflow instead of pushing demand into rides.",
            )
        )

    if food_wait >= 22 and not state.backup_food_open:
        state.backup_food_open = True
        fired.append(
            _rule_firing(
                state.minute,
                "food_capacity_trigger",
                "Backup food stand opened",
                f"foodWaitMinutes={round(food_wait, 1)} crossed 22.",
                "Food service capacity increases before storm migration peaks.",
            )
        )

    if staff_stress >= 1.08 and not state.staff_transfer_started:
        state.staff_transfer_started = True
        state.staff_arrival_minute = state.minute + 15
        fired.append(
            _rule_firing(
                state.minute,
                "staff_stress_transfer",
                "Staff transfer started",
                f"staffStress={round(staff_stress, 2)} crossed 1.08; staff become available at +15 minutes.",
                "Transferred staff do not help immediately, preserving the delayed-action behavior.",
            )
        )

    return fired


def _rule_firing(minute: int, rule_id: str, label: str, evidence: str, effect: str) -> dict[str, Any]:
    return {
        "minute": minute,
        "ruleId": rule_id,
        "label": label,
        "evidence": evidence,
        "effect": effect,
        "source": "simple_rules_derived_decision_engine",
    }


def _closure_risk(weather: dict[str, Any]) -> float:
    risk = weather["stormRisk"] * 0.82
    if weather["rain"]:
        risk += 10
    if weather["lightning"]:
        risk += 16
    return min(100.0, risk)


def _food_capacity_per_hour(state: TwinState) -> float:
    capacity = FOOD_CAPACITY_PER_HOUR
    if state.backup_food_open:
        capacity += 850
    if state.staff_available >= 132:
        capacity += 380
    return capacity


def _pressure_pct(queue_guests: float, capacity_per_hour: float) -> int:
    return round(min(180.0, (queue_guests / capacity_per_hour) * 100.0))


def _wait_minutes(queue_guests: float, capacity_per_hour: float) -> float:
    return queue_guests / capacity_per_hour * 60.0


def _staff_stress(state: TwinState, indoor_pressure: float, food_wait: float, weather: dict[str, Any]) -> float:
    required = 94 + indoor_pressure * 0.42 + food_wait * 0.55 + weather["stormRisk"] * 0.18
    return required / state.staff_available


def _abandonment_guests(wait_minutes: float, queue_guests: float) -> float:
    if wait_minutes < 42:
        return 0.0
    return min(queue_guests * 0.08, (wait_minutes - 42) * 10)


def _summary(points: list[dict[str, Any]]) -> dict[str, Any]:
    peak_indoor = max(point["indoorQueuePressure"] for point in points)
    peak_food = max(point["foodWaitMinutes"] for point in points)
    peak_staff = max(point["staffStress"] for point in points)
    final = points[-1]
    return {
        "peakIndoorQueuePressure": peak_indoor,
        "peakFoodWaitMinutes": round(peak_food, 1),
        "peakStaffStress": round(peak_staff, 2),
        "finalGuestSatisfaction": final["guestSatisfaction"],
        "finalIndoorQueuePressure": final["indoorQueuePressure"],
        "finalFoodWaitMinutes": final["foodWaitMinutes"],
    }


def _analyst_readout(policy: Policy, summary: dict[str, Any]) -> str:
    if policy.id == "do_nothing":
        return "No action lets outdoor displacement land directly on indoor rides and food, so queues stay elevated after lightning closure."
    if policy.id == "notify":
        return "A single weather-risk rule helps, but without capacity and staff rules, food and staff stress remain the binding constraints."
    return (
        "The rule stack fires from thresholds in the simulated state, then delayed staff arrival, backup food capacity, and show absorption "
        "produce the lowest pressure while keeping satisfaction from sliding late in the storm."
    )


def _time_label(minute: int) -> str:
    hour = 13 + minute // 60
    label_minute = minute % 60
    return f"{hour:02d}:{label_minute:02d}"
