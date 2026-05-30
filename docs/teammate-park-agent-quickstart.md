# Teammate Park Agent Quickstart

This is the shortest integration path for teammate-owned ParkPulse specialist agents.

Specialist agents may send aggregate operational constraints only.

## Example Inbound Constraint

```json
{
  "agent": "Food Agent",
  "scenario": "food_spike",
  "request_type": "MENU_SUPPRESSION",
  "requested_resource": "Food Court A",
  "reason": "Mobile order backlog and low inventory",
  "constraints": {
    "low_stock_items": ["chicken_tenders", "bottled_drinks"],
    "pickup_eta_minutes": 34,
    "nearby_capacity_location": "Food Court B"
  },
  "aggregate_metrics": {
    "open_mobile_orders": 143,
    "guest_density_nearby": 78,
    "staff_gap": 1
  }
}
```

## Blocked Payload

```json
{
  "guest_name": "Sample Guest",
  "guest_id": "private-id",
  "compensation_promise": "Free meal guaranteed"
}
```

ParkPulse must block guest PII and individualized compensation promises unless a human-approved workflow explicitly authorizes them.

## Pull Park State

```http
GET /api/park/state
```

## Execute Park Action

```http
POST /api/park/action
```

Use ParkPulse action payloads such as:

```json
{
  "target": "traffic",
  "action": "redirect_food"
}
```

The action is recorded for `agent_decisions` and evaluated through the GCP trace/eval scorecard.
