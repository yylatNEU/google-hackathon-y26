from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Policy:
    id: str
    label: str
    notification_minute: int | None = None
    backup_food_minute: int | None = None
    staff_move_minute: int | None = None
    staff_arrival_delay: int = 15
    delay_parade_minute: int | None = None


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
    parade_delayed: bool = False


ACTIVE_GUESTS = 18_000
TICK_MINUTES = 5
HORIZON_MINUTES = 180
INDOOR_CAPACITY_PER_HOUR = 5_100
FOOD_CAPACITY_PER_HOUR = 3_200
SHOW_ABSORPTION_PER_TICK = 420


POLICIES = [
    Policy("do_nothing", "Policy A: Do nothing"),
    Policy("notify", "Policy B: Send guest rerouting notification", notification_minute=30),
    Policy(
        "full_intervention",
        "Policy C: Reroute + backup food + move staff + delay parade",
        notification_minute=20,
        backup_food_minute=55,
        staff_move_minute=35,
        staff_arrival_delay=15,
        delay_parade_minute=45,
    ),
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
            "decision_intervention",
        ],
        "policies": runs,
        "comparison": {
            "lowestIndoorPressurePolicy": best["policyId"],
            "highestSatisfactionPolicy": satisfaction_best["policyId"],
            "headline": (
                "The full intervention branch absorbs the storm displacement earlier: "
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
    staff_arrival_minute = (
        policy.staff_move_minute + policy.staff_arrival_delay
        if policy.staff_move_minute is not None
        else None
    )

    for minute in range(0, horizon_minutes + tick_minutes, tick_minutes):
        state.minute = minute
        weather = _weather_state(minute)
        closure_risk = _closure_risk(weather)
        lightning_closed = weather["lightning"] or closure_risk >= 92

        if policy.notification_minute is not None and minute >= policy.notification_minute and not state.notifications_sent:
            state.notifications_sent = True
            interventions.append({"minute": minute, "label": "Targeted guest rerouting notification sent", "effect": "More displaced guests choose shows, retail, and lower-pressure food paths."})
        if policy.backup_food_minute is not None and minute >= policy.backup_food_minute and not state.backup_food_open:
            state.backup_food_open = True
            interventions.append({"minute": minute, "label": "Backup food stand opened", "effect": "Food service capacity increases after storm migration begins."})
        if policy.delay_parade_minute is not None and minute >= policy.delay_parade_minute and not state.parade_delayed:
            state.parade_delayed = True
            interventions.append({"minute": minute, "label": "Parade delayed and indoor show window extended", "effect": "Show venue absorbs guest overflow instead of pushing demand into rides."})
        if staff_arrival_minute is not None and minute == policy.staff_move_minute:
            interventions.append({"minute": minute, "label": "Staff transfer started", "effect": f"Transferred staff become available at +{policy.staff_arrival_delay} minutes."})
        if staff_arrival_minute is not None and minute >= staff_arrival_minute:
            state.staff_available = 132.0

        if minute > 0:
            _advance_tick(state, policy, weather, closure_risk, lightning_closed, tick_minutes)

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
            }
        )

    summary = _summary(points)
    return {
        "policyId": policy.id,
        "policyLabel": policy.label,
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
    full_policy = 1.0 if policy.id == "full_intervention" else 0.0
    show_share = 0.13 + 0.19 * notification + 0.14 * full_policy + (0.08 if state.parade_delayed else 0.0)
    food_share = 0.22 + 0.05 * risk_factor - 0.05 * full_policy
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
        return "Guest messaging helps, but without delayed capacity and staff effects, food and staff stress remain the binding constraints."
    return (
        "Combined rerouting, delayed staff arrival, backup food capacity, and parade timing produce the lowest peak pressure "
        "while keeping satisfaction from sliding late in the storm."
    )


def _time_label(minute: int) -> str:
    hour = 13 + minute // 60
    label_minute = minute % 60
    return f"{hour:02d}:{label_minute:02d}"
