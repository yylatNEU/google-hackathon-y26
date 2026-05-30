---
name: parkpulse-role-orchestrator
description: Use when deciding which ParkPulse role should handle an amusement-park request: scan for sensing, react for confirmed incidents/operator commands, or proact for weak-signal prevention and learning loops. Use for MCP role routing, agent orchestration, multi-agent control flow, or questions about scan vs react vs proact.
metadata:
  short-description: Route ParkPulse tasks to scan, react, or proact roles
---

# ParkPulse Role Orchestrator

## Routing

- Use `parkpulse-scan-agent` when the request is to inspect, detect, summarize, or assess uncertainty without action.
- Use `parkpulse-react-agent` when there is a confirmed incident or direct operator command.
- Use `parkpulse-proact-agent` when the task is prevention, early warning, future planning, take-rate learning, or continuous improvement.

## Required Flow

For live operations, route through:

```text
scan -> react
scan -> proact
scan -> monitor
```

Never skip policy gates for react/proact actions.

## Decision Examples

- "Food court is down" -> react.
- "Guests are complaining about dizziness near Food Court A" -> scan, then proact if pattern is rising.
- "Prevent crowding before Halloween event starts" -> proact.
- "What is happening in the park?" -> scan.
- "Move workers to the crowded site" -> react with labor policy gate.

## Output Contract

```json
{
  "selected_role": "scan | react | proact",
  "why": "",
  "required_tools": [],
  "policy_gates": [],
  "expected_receipt": []
}
```
