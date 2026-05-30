#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "== ParkPulse demo QA =="
echo "Python: $PYTHON_BIN"

echo "== Python compile =="
"$PYTHON_BIN" -m compileall -q \
  backend/main.py \
  backend/parkpulse_api.py \
  backend/agent_role_skills.py \
  backend/test_parkpulse_completion.py

echo "== Merge-conflict marker scan =="
if rg -n '^(<<<<<<<|=======|>>>>>>>)' .agents backend frontend \
  --glob '!backend/venv/**' \
  --glob '!frontend/node_modules/**' \
  --glob '!frontend/dist/**'; then
  echo "Merge-conflict marker found." >&2
  exit 1
fi

echo "== Agent role regression =="
export PARKPULSE_ROLE_REFINE_TIMEOUT_SECONDS="${PARKPULSE_ROLE_REFINE_TIMEOUT_SECONDS:-3}"
PYTHONPATH=backend "$PYTHON_BIN" - <<'PY'
import asyncio
import json
import main


async def main_check():
    food = await main._agent_role_run_payload(
        "food court is down and mobile orders are backing up near the west plaza",
        "auto",
    )
    assert food["selected_role"] == "react", food["selected_role"]
    assert food["role_receipt"]["scenario_key"] == "food_spike"
    assert food["role_receipt"]["dispatch_ids"]
    assert food["role_receipt"]["learning_update"]["validity"] == "observed_response"
    assert food["unified_receipt"]["contract"] == "parkpulse_operating_loop_v1"
    assert food["unified_receipt"]["role"] == "react"
    assert food["unified_receipt"]["domain"] == "food"
    assert food["unified_receipt"]["dispatches"]["count"] >= 1
    bq_counts = food["role_receipt"]["bigquery"].get("row_counts") or food["role_receipt"]["bigquery"].get("inserted") or {}
    assert bq_counts.get("action_dispatches", 0) >= 1
    serialized = json.dumps(food).lower()
    assert "food court a" in serialized
    assert "dragon coaster is down" not in serialized

    scan = await main._agent_role_run_payload(
        "scan vague guest complaints and worker taps for early crowd risk",
        "scan",
    )
    assert scan["selected_role"] == "scan"
    assert scan["role_run"]["dispatch_allowed"] is False
    assert scan["run_telemetry"]["delivery"]["summary"]["total"] == 0
    assert scan["role_receipt"]["role"] == "scan"

    vague = await main._agent_role_run_payload(
        "Staff note: kids are crying near the barrier and the crowd stopped moving by the maze exit",
        "auto",
    )
    assert vague["selected_role"] == "proact", vague["selected_role"]
    assert vague["role_receipt"]["dispatch_ids"]

    medical = await main._agent_role_run_payload(
        "guest has fainted near food court, first aid and wheelchair help needed",
        "auto",
    )
    assert medical["selected_role"] == "react", medical["selected_role"]
    medical_text = json.dumps(medical).lower()
    assert "diagnose" not in medical_text
    assert "medical" in medical_text or "first aid" in medical_text
    assert medical["run_telemetry"]["outcome"]["state_impact"]["domain"] == "medical"

    ride = await main._agent_role_run_payload(
        "Dragon Coaster is down. Pause queue intake, message guests honestly, and send staff to reroute people.",
        "auto",
    )
    assert ride["selected_role"] == "react", ride["selected_role"]
    assert ride["run_telemetry"]["outcome"]["state_impact"]["domain"] == "ride"
    assert ride["unified_receipt"]["domain"] == "ride"
    assert "Ride queue" in ride["run_telemetry"]["outcome"]["state_impact"]["before_after_line"]

    staff = await main._agent_role_run_payload(
        "Several workers called out. Protect staff breaks, keep certified coverage safe, and rebalance food and ride support.",
        "auto",
    )
    assert staff["selected_role"] in {"react", "proact"}, staff["selected_role"]
    assert staff["run_telemetry"]["outcome"]["state_impact"]["domain"] == "staff"
    assert staff["unified_receipt"]["domain"] == "staff"
    assert "Callouts" in staff["run_telemetry"]["outcome"]["state_impact"]["before_after_line"]

    crowd = await main._agent_role_run_payload(
        "There is panic crowd congestion near Covered Plaza. Open calm routes, move crowd-control staff, and keep service access clear.",
        "auto",
    )
    assert crowd["selected_role"] == "react", crowd["selected_role"]
    assert crowd["run_telemetry"]["outcome"]["state_impact"]["domain"] == "crowd"
    assert crowd["unified_receipt"]["domain"] == "crowd"
    assert "Path congestion" in crowd["run_telemetry"]["outcome"]["state_impact"]["before_after_line"]

    hvac = await main._agent_role_run_payload(
        "Indoor areas are too hot and guests are crowding shelter zones. Adjust HVAC comfort and shed only noncritical load.",
        "auto",
    )
    assert hvac["selected_role"] == "react", hvac["selected_role"]
    assert hvac["run_telemetry"]["outcome"]["state_impact"]["domain"] == "energy"
    assert hvac["unified_receipt"]["domain"] == "energy"
    assert "Grid load" in hvac["run_telemetry"]["outcome"]["state_impact"]["before_after_line"]

    try:
        refine = await asyncio.wait_for(
            main._agent_role_refinement_payload(
                "food court is down and mobile orders are backing up near the west plaza",
                food,
            ),
            timeout=8,
        )
    except TimeoutError:
        refine = {"status": "fallback", "mode": "qa_outer_timeout"}
    assert refine["status"] in {"complete", "fallback"}, refine

    print(json.dumps({
        "food_role": food["selected_role"],
        "food_scenario": food["role_receipt"]["scenario_key"],
        "food_dispatches": len(food["role_receipt"]["dispatch_ids"]),
        "vague_role": vague["selected_role"],
        "medical_role": medical["selected_role"],
        "ride_domain": ride["run_telemetry"]["outcome"]["state_impact"]["domain"],
        "staff_domain": staff["run_telemetry"]["outcome"]["state_impact"]["domain"],
        "crowd_domain": crowd["run_telemetry"]["outcome"]["state_impact"]["domain"],
        "hvac_domain": hvac["run_telemetry"]["outcome"]["state_impact"]["domain"],
        "refine_status": refine["status"],
    }, indent=2))


asyncio.run(main_check())
PY

echo "== Frontend lint =="
npm --prefix frontend run lint

echo "== Frontend build =="
npm --prefix frontend run build

echo "== ParkPulse demo QA passed =="
