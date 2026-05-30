# ParkPulse Agent Fit

ParkPulse should be positioned as a decision-support copilot for amusement park operations, not as an autonomous safety controller.

Existing source systems calculate operational truth. ParkPulse coordinates, explains, audits, and evaluates decisions across those systems.

| Layer | Owns | ParkPulse stance |
| --- | --- | --- |
| Ride safety / maintenance | safety clearance, inspections, lockout, reopening approval | Read facts and escalate; never override clearance. |
| Ride operations | dispatch rate, operator minimums, queue intake, downtime estimates | Recommend capacity-aware routing and queue actions. |
| Guest flow | zone density, path congestion, app routing, signage | Recommend nudges that avoid new bottlenecks. |
| Staffing | availability, training tags, break windows, fatigue | Recommend redeployment within labor and safety constraints. |
| Food operations | inventory, POS demand, mobile-order backlog, prep time | Recommend menu, routing, staffing, and pickup ETA changes. |
| Security / guest services | incidents, privacy, sensitive communication | Retrieve playbooks and escalate without exposing PII. |
| GCP trace/eval | traces, evals, decision-quality review | Judge whether actions are grounded, safe, balanced, and actionable. |

## Core Agents

### Decision Bridge Agent

Reads specialist findings and produces a structured park action plan.

Allowed:

* ride intake pause recommendations
* guest redistribution plans
* food menu and pickup-time recommendations
* staff redeployment recommendations
* guest-message drafts
* human-review flags

Blocked:

* ride reopening without safety clearance
* individualized compensation promises
* guest PII disclosure
* break-policy violations
* safety or accessibility coverage reductions

### GCP Judge Layer

Checks every recommendation for:

* groundedness
* safety compliance
* capacity awareness
* staff stress
* guest impact
* inventory groundedness
* actionability
* policy violations

## Demo Positioning

Use this line:

> ParkPulse does not just log agent behavior. It evaluates whether the agent made a grounded, safe, balanced operating decision and shows exactly where it failed.
