from __future__ import annotations

from typing import Any

AUTODREAM_RETIREMENT_REASON = "AutoDream has been retired; paired replay benchmarks are disabled."


def run_autodream_benchmark(
    state: dict[str, Any],
    *,
    scenario_key: str | None = None,
    promoted_rule_id: str | None = None,
    seeds: int = 5,
) -> dict[str, Any]:
    flow = state.get("guestFlow", {}) if isinstance(state.get("guestFlow"), dict) else {}
    active = flow.get("activeScenario", {}) if isinstance(flow.get("activeScenario"), dict) else {}
    scenario = scenario_key or str(active.get("key") or "ride_down")
    safe_seeds = max(1, min(20, int(seeds or 5)))
    return {
        "status": "retired",
        "mode": "retired_autodream_benchmark",
        "scenario_key": scenario,
        "promoted_rule_id": promoted_rule_id,
        "sample_size": 0,
        "requested_seeds": safe_seeds,
        "confidence": "disabled",
        "summary": {
            "retired": True,
            "reason": AUTODREAM_RETIREMENT_REASON,
            "win_rate": 0,
            "take_rate_lift": 0,
        },
        "pairs": [],
        "recommendation": AUTODREAM_RETIREMENT_REASON,
    }
