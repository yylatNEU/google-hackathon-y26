# ParkPulse AI: Product Roadmap

ParkPulse AI demonstrates an ML-first operations copilot for amusement parks. It does not replace ride safety systems, maintenance sign-off, security command, labor policy, POS, inventory, or human operators. Prediction, simulation, optimization, and deterministic policy gates operate the loop; LLMs interpret messy context, explain choices, draft receiver payloads, and convert outcomes into training signals.

## MVP Spine

The current product center is defined in [`docs/mvp-architecture-extraction.md`](docs/mvp-architecture-extraction.md). The first demo route should stay focused on one loop:

> Something changed in the park. What should operations do now, and can we prove the recommendation is grounded, safe, and balanced?

Anything outside scenario selection, current state, agent findings, recommended action, policy gate, dispatch approval, eval receipt, and memory/proof belongs in a secondary or labs surface until the MVP is coherent.

## Phase 1: Park Operations Source Data

**Goal: Make the park state believable and traceable.**

* Weather and safety feeds: storm risk, heat index, lightning window, ride closure rules.
* Ride operations feeds: ride status, capacity, dispatch rate, downtime estimate, queue size, operator minimums.
* Guest-flow feeds: zone density, path congestion, app routing, guest segment mix, satisfaction risk.
* Staffing feeds: shift availability, training tags, break windows, fatigue/stress scores.
* Food feeds: inventory, mobile-order backlog, prep time, kitchen load, nearby capacity.
* Energy feeds: demand charge risk, HVAC load, lighting/show load, comfort-sensitive zones.

## Phase 2: Specialist Agents

**Goal: Show that ParkPulse is not a chatbot.**

* `WeatherAgent`: Predicts weather and outdoor ride disruption.
* `RideOpsAgent`: Checks ride capacity, downtime, dispatch rates, and maintenance constraints.
* `GuestFlowAgent`: Detects crowding, queue pressure, and behavioral routing opportunities.
* `StaffingAgent`: Balances coverage, training, breaks, and worker stress.
* `FoodAgent`: Uses demand, inventory, POS history, and kitchen load.
* `EnergyAgent`: Reduces cost without harming shelter comfort or safety.
* `DecisionBridgeAgent`: Produces the final action plan with tradeoffs and human-review flags.
* `ArizeJudgeLayer`: Scores groundedness, safety, staff stress, guest impact, actionability, and policy compliance.

## Phase 2B: Lifecycle Agent Groups

**Goal: Make the agent swarm adapt to the event lifecycle instead of using one flat group for every moment.**

* Pre-event group: simulates policy impact, forecasts crowd/staff/equipment pressure, and commits prevention work before an event or disruption peaks.
* During-event group: supervises live signals, reacts through policy-gated actions, and routes guest, worker, or equipment payloads through the action bus.
* Post-event group: analyzes response telemetry, scores the decision, writes learnings to operational memory, and improves the next plan or threshold.

## Phase 3: Three Demo Scenarios

**Goal: Prove tradeoff reasoning across multiple data sources.**

* Ride Down: Dragon Coaster is down for 60 minutes and 700 guests need redistribution.
* Staff Shortage: Callouts create conflict between ride waits, food lines, and protected breaks.
* Food Demand Spike: Mobile-order backlog and inventory shortage require menu, routing, staffing, and ETA changes.

## Phase 4: MongoDB Operational Memory

**Goal: Make MongoDB part of the agent architecture, not just storage.**

* `park_state`: Current ride status, wait times, weather, crowd density, staff load, and energy state.
* `rides`: Ride metadata, capacity, indoor/outdoor status, energy use, staffing need, safety constraints.
* `staff_shifts`: Availability, training tags, break windows, fatigue/stress scores.
* `food_inventory`: Menu item availability, prep time, kitchen load, mobile-order backlog.
* `incidents`: Ride downtime, weather events, guest complaints, lost-child incidents, maintenance risk.
* `agent_decisions`: Every recommendation, evidence set, tradeoff, confidence, and approval status.
* `playbooks`: Vector-searchable operating procedures and incident responses.
* `guest_messages`: Draft app notifications and reviewed outbound copy.
* `eval_results`: Arize/Phoenix scores and failure reasons for each decision.

## Phase 5: Arize/Phoenix Quality Layer

**Goal: Sell Arize as decision quality control, not logging.**

Trace and evaluate:

* Which agent ran and what data it retrieved.
* Which MongoDB documents or playbooks grounded the decision.
* Whether the action overloaded rides, food, or staff.
* Whether safety, privacy, labor, or accessibility rules were violated.
* Whether the plan over-optimized cost at the expense of guests or workers.
* Whether the recommendation was specific enough to execute.

Core evals:

* Groundedness
* Safety compliance
* Capacity awareness
* Staff stress
* Guest impact
* Inventory groundedness
* Revenue balance
* Actionability
* Conflict resolution

## Phase 6: Demo Contract

**Goal: Keep the hackathon story simple.**

The first screen should always answer:

> Something changed in the park. What should operations do now, and can we prove the agent made a grounded, safe, balanced decision?

The demo should show three scenario buttons, a specialist-agent panel, a concrete action plan, MongoDB memory, and an Arize scorecard.
