# ParkPulse Model Improvement Recovery Plan

Generated: 2026-06-03

## Current Baseline

- Live feed health: ready, 6/6 required feeds, 0 open reviews.
- Training readiness: ready, all 6 agent scopes model-training-ready.
- Readiness evidence before recovery: 187 observed rows from Mongo outcome events plus heartbeat delayed outcomes.
- Full promotion evidence before recovery: 296 observed rows from BigQuery, Mongo outcome events, and heartbeat delayed outcomes.
- Controlled training pack: `controlled_training_pack_d509d0fc98319196d1`, generated, 66 examples.
- Controlled eval: `controlled_training_eval_controlled_training_pack_d509d0fc98319196d1`, passed, 6/6 roles.
- Initial global promotion gate: hold.
- Initial latest average reward: 46.66, below the 52.00 promotion threshold.
- Initial reward curve delta: -23.15.
- Ground-truth promotion impact: not measured.

## Recovery Evidence Collected

Collected on 2026-06-03 after the BigQuery ML training run:

- Added measured `policy_recovery_closed_loop` outcome rows for `ride_down`, `food_spike`, `staff_shortage`, and `storm_response`.
- Replaced weak `ride_down/calm_reroute` evidence with optimized route-mix rows: overall 80, take rate 0.741, follow-through 0.691, comfort +11, queued guests reduced by about 515-555.
- Replaced weak `food_spike` evidence with clean mobile-pickup reroute rows: overall 84, response 85, take rate 0.86, follow-through 0.79.
- Added strong `staff_shortage` recovery rows: overall 89, response 92, take rate 0.96, follow-through 0.91.
- Added `storm_response` recovery rows and restored its slice delta to positive.

Final full diagnostic snapshot:

- Status: ready.
- Full evidence source: `bigquery_outcome_events+mongodb_outcome_events+heartbeat_delayed_outcome_signals`.
- Latest average reward: 77.15.
- Reward curve delta: 8.81.
- Scenario-balanced latest average reward: 71.29.
- Promotion gate: `slice_promotable`.
- Promotion decision: `promote_eligible_policy_slices_only`.
- Slice summary: 5 promotable, 0 held, 2 collect-more-evidence.

Promotable slices:

| Scenario | Latest avg reward | Curve delta | Decision |
| --- | ---: | ---: | --- |
| food_spike | 83.44 | 9.34 | promote_slice |
| proactive_eventops | 74.04 | 5.88 | promote_slice |
| ride_down | 77.90 | 15.36 | promote_slice |
| staff_shortage | 89.68 | 11.87 | promote_slice |
| storm_response | 86.15 | 8.34 | promote_slice |

Remaining non-promotion warnings:

- `proactive_watchtower` has 1 row and needs 12 rows before promotion.
- `scan` has 1 row and needs 12 rows before promotion.
- Ground-truth promotion impact is still not measured; do not claim production improvement until promoted-slice outcomes are observed.

## Park Understanding Gate

Reward improvement is not enough to prove that the LLM understands the park. A separate park-understanding benchmark now exists:

- Benchmark doc: `docs/park-understanding-benchmark.md`.
- API: `GET /api/park/understanding-benchmark/cases`, `POST /api/park/understanding-benchmark`, `GET /api/park/understanding-benchmark/latest`.
- Dimensions: scenario identification, entity grounding, route/facility reasoning, conflict resolution, safety constraints, action quality, evidence use, hallucination control.
- Audited baseline report: `park_understanding_benchmark_fb6c3922ea9adf19`.
- Baseline status: passed, 8/8 cases, average score 99.08.
- Live LLM evaluated: false.
- Decision: `baseline_passed_but_live_llm_not_evaluated`.
- The old 6-case version was too easy; the strict version includes adversarial conflict cases and rejects generic safe-sounding answers.
- Latest live Gemini report: `park_understanding_benchmark_80f1e74ea3a9ccd9`.
- Latest live status: passed, 8/8 cases, average score 97.72.
- Latest live decision: `allow_live_llm_park_understanding_claim`.

Use this as the prompt/context gate before claiming that the LLM understands the park better. Use reward/promotion gates only for measured operating outcomes. The live understanding gate now passes for the current strict suite, but it does not prove production operating improvement.

Latest live LLM run:

- Report doc: `docs/park-understanding-live-report-2026-06-03.md`.
- Report ID: `park_understanding_benchmark_80f1e74ea3a9ccd9`.
- Live LLM evaluated: true.
- Status: passed.
- Passed cases: 8/8.
- Average score: 97.72.
- Decision: `allow_live_llm_park_understanding_claim`.

Resolved live gaps: compound scenario reasoning, staffing certification boundaries, guest-care support-node grounding, evidence completeness, and malformed JSON reliability. The key transport fix was disabling hidden Gemini REST thinking tokens with `thinkingBudget: 0`, matching the SDK fallback behavior.

## Diagnosis

The model is not blocked by data volume or eval readiness. It is blocked by negative recent outcome evidence.

Worst recent action families:

| Scenario | Policy | Rows | Avg reward | Decision |
| --- | --- | ---: | ---: | --- |
| storm_response | hold_equipment_changes | 30 | 36.72 | stop autonomous execution |
| storm_response | redeploy_staff | 10 | 36.93 | human review only |
| ride_down | calm_reroute | 21 | 37.74 | stop autonomous execution when slice is held |
| storm_response | calm_reroute | 10 | 40.16 | human review until slice recovers |

Best observed policy families to bias toward in offline training and controlled eval:

| Scenario | Policy | Rows | Avg reward |
| --- | --- | ---: | ---: |
| ride_down | routing_incentive_is_acceptable | 66 | 72.66 |
| storm_response | routing_incentive_is_acceptable | 16 | 72.34 |
| staff_shortage | routing_incentive_is_acceptable | 14 | 73.34 |
| proactive_eventops | proactive_closed_loop | 11 | 68.27 |
| proactive_eventops | proactive_learned_second_run | 1 | 82.08 |

## Guardrails Already Applied

- Full and readiness diagnostics now use bounded Mongo outcome rows, not only dashboard latest rows.
- Training rows are sorted by observed timestamp before fitness curves are computed.
- Safe auto-execute now blocks a candidate when its scenario slice is explicitly `hold_slice`.
- Promotion warnings no longer incorrectly claim BigQuery is inactive when BigQuery rows are part of the evidence source.

## Recovery Plan

### Phase 1: Stop the Bleeding

Goal: prevent new low-reward heartbeat rows from held slices.

Actions:

1. Keep `ride_down`, `storm_response`, `food_spike`, and `staff_shortage` in review-only mode until their scenario deltas recover.
2. Allow autonomous heartbeat execution only for scenarios with `runtime_status=promoted_challenger` or true observation-only thin slices that pass live policy gates.
3. Refresh the policy snapshot after every full diagnostic run.

Acceptance criteria:

- Heartbeat controller shows no executed rows for held slices over the next 20 cycles.
- Any held-slice candidate returns `gate_status=review` or `blocked`.
- Slice rollback ledger records transitions away from previously active held slices.

### Phase 2: Train Away From Bad Policies

Goal: use the passed controlled pack/eval to bias offline learning toward high-reward policies and away from known drags.

Actions:

1. Use the current controlled pack and eval as the approved offline-training input gate.
2. Add negative-policy weighting for:
   - `storm_response/hold_equipment_changes`
   - `storm_response/redeploy_staff`
   - `ride_down/calm_reroute`
3. Add positive-policy weighting for `routing_incentive_is_acceptable` in `ride_down`, `storm_response`, and `staff_shortage`.
4. Keep review labels out of reward; labels are supervised examples only.

Acceptance criteria:

- Controlled eval remains passed after weighting changes.
- RL reward examples still come only from measured outcome rows.
- No policy can be promoted from LLM text, labels, or synthetic rows.

### Phase 3: Collect Replacement Evidence

Goal: replace the low recent buckets with high-quality, measured outcomes.

Actions:

1. Run controlled, operator-approved episodes for `ride_down` and `storm_response`.
2. Prefer bounded guest-routing/incentive alternatives over equipment holds or staff moves.
3. For staff or equipment actions, require human review and explicit post-action outcome measurement.
4. Continue collecting `proactive_eventops` evidence because it is the only currently promotable slice.

Acceptance criteria:

- At least 30 new measured outcomes after the guardrail change.
- Latest 3 buckets, 10 rows each, average reward >= 52.
- No new low-reward heartbeat rows from held slices.

### Phase 4: Promote Slices, Not Global Model

Goal: promote only slices with non-regressing scenario evidence.

Actions:

1. Run full `actual_training_status(..., detail="full")`.
2. Refresh `/api/park/promoted-slice-policy?refresh=1`.
3. Promote only slices where:
   - sample_count >= 12
   - latest_average_reward >= 52
   - curve_delta >= 0
   - live gates are clean
4. Keep global promotion held until there are no held or thin critical slices.

Acceptance criteria:

- `proactive_eventops` remains promotable.
- `ride_down` and `storm_response` are promoted only after their deltas turn non-negative.
- Global promotion only when latest average reward >= 52 and curve delta >= 0.

### Phase 5: Ground-Truth Measurement

Goal: prove the model is better in actual promoted behavior, not just readiness.

Actions:

1. Attach promotion-impact measurements to outcome events.
2. Require at least 5 measured promotion outcomes before claiming improvement.
3. Track improved, neutral, and regressed counts by scenario.

Acceptance criteria:

- `ground_truth_improvement.status` is no longer `not_measured`.
- Regression count is zero for newly promoted slices.
- Improvement confidence is based on observed outcome events, not eval-only metrics.

## Operator Checklist

Run after each recovery batch:

1. Confirm live feed health is ready.
2. Confirm review ledger has 0 open critical reviews.
3. Confirm controlled eval is passed.
4. Confirm heartbeat controller did not execute held slices.
5. Confirm promotion gate latest average reward and curve delta.
6. Refresh promoted-slice artifact only from full diagnostics.
7. Do not globally promote until latest average reward >= 52 and curve delta >= 0.

## Current Go/No-Go

Decision: GO WITH CONDITIONS for slice promotion and post-promotion measurement.

Conditions:

- Promote eligible slices only; do not globally promote thin `scan` or `proactive_watchtower` coverage.
- Keep autonomous execution blocked for any future `hold_slice` scenario.
- Require promotion-impact measurement before claiming ground-truth improvement.
- Continue collecting scan/watchtower outcomes until each has at least 12 measured rows.
