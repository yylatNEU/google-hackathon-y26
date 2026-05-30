# ParkPulse Agent REST Contract

ParkPulse exposes park-native routes for the demo surface.

## State

```http
GET /api/park/state
```

Returns the live park operations state, including:

* `product`
* `parkOps`
* `guestFlow`
* `weather`
* `energy`
* `staffing`
* `facilities`
* `alerts`

Legacy compatibility fields may also be present while the old simulator contract is being retired.

## Action

```http
POST /api/park/action
Content-Type: application/json
```

```json
{
  "target": "traffic",
  "action": "redirect_food"
}
```

The response includes a `park_action` record that can be stored in `agent_decisions` and evaluated in `eval_results`.

## Codex Review Snapshot

```http
GET /api/park/replay
```

Returns the current SQLite-backed simulation replay: recent scenario switches, injected shocks, operator/agent actions, and closed-loop outcomes. Each replay event includes:

* trigger details
* before and after state digests
* numeric deltas
* cause/effect narrative

```http
POST /api/park/replay/start
Content-Type: application/json
```

```json
{
  "seed": "dragon-rain-001",
  "scenario_key": "ride_down"
}
```

Starts a persistent SQLite-backed replay run. The run receives a stable `run_id`, stores the seed, resets the scenario state, and records a `run_started` replay event. Later events in the same run are persisted to the replay database.

```http
GET /api/park/review-snapshot
```

Returns a deterministic simulation-review packet for Codex or another evaluator. It includes:

* current scenario and sim time
* state digest and physical-map counts
* realism scorecard
* recent injected events, sim actions, dispatches, signals, policy gates, and replay events
* known missing capabilities
* next implementation fixes
* a review prompt plus the raw `snapshot_state`

## Scenario Output Shape

```json
{
  "situation": "Dragon Coaster is down for estimated 60 minutes",
  "risk_level": "HIGH",
  "recommended_actions": [
    {
      "action": "Pause new queue intake at Dragon Coaster",
      "owner": "Ride Ops",
      "deadline_minutes": 5,
      "expected_impact": "Prevent 300 additional guests from joining a dead queue"
    }
  ],
  "tradeoffs": {
    "guest_satisfaction": "Short-term frustration, better recovery if messaging is fast",
    "staff_stress": "Requires 2 extra crowd-control staff",
    "energy_cost": "Neutral",
    "revenue": "Possible recovery-offer cost"
  },
  "confidence": 0.82,
  "needs_human_approval": true
}
```

## GCP Trace/Eval Shape

```json
{
  "groundedness_score": 0.91,
  "safety_score": 0.96,
  "staff_stress_score": 0.74,
  "guest_experience_score": 0.81,
  "actionability_score": 0.88,
  "policy_violation": false
}
```
