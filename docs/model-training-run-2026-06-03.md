# ParkPulse Offline Training Run

Run timestamp: 2026-06-03T05:19:38Z

## Result

Offline BigQuery ML training completed successfully.

- Training job ID: `80e9b875-3388-4a45-957d-855e70e6f617`
- Job state: `DONE`
- Statement type: `CREATE_MODEL`
- Error result: none
- Model: `crypto-song-496607-d7.parkpulse_analytics.parkpulse_policy_reward_model`
- Model type: `LINEAR_REGRESSION`
- Model created: `2026-06-03 05:19:59.362000+00:00`
- Training receipt: `training_run_f317410b8179b82254`

## Training Gate

- Controlled training pack: `controlled_training_pack_d509d0fc98319196d1`
- Controlled eval: `controlled_training_eval_controlled_training_pack_d509d0fc98319196d1`
- Controlled eval status: passed, 6/6 roles.
- Readiness sample count used by guarded training path: 187 observed rows.
- Evidence source: `mongodb_outcome_events+heartbeat_delayed_outcome_signals`
- BigQuery table validation: ready.
- Generated, seed, synthetic, demo, and validation rows excluded by SQL.

## Model Evaluation

BigQuery `ML.EVALUATE` returned:

- Mean absolute error: `0.42127201694605826`
- Mean squared error: `0.3662420001228985`
- Median absolute error: `0.35708349109278004`
- R2 score: `0.9942149784257723`
- Explained variance: `0.9942152103047442`

## Promotion Status

No model promotion was started.

Immediate post-training full diagnostics still held promotion:

- Latest average reward: `46.66`
- Promotion threshold: `52.00`
- Reward curve delta: `-23.15`
- Slice summary: 1 promotable, 4 held, 2 collect-more-evidence.

The trained BQML model is available for offline scoring/analysis. Live heartbeat execution and model promotion remain governed by the promoted-slice and rollback gates.

## Recovery Evidence After Training

After training, controlled recovery outcomes were collected for the held slices. Final full diagnostics:

- Latest average reward: `77.15`
- Reward curve delta: `8.81`
- Scenario-balanced latest average reward: `71.29`
- Promotion gate: `slice_promotable`
- Promotion decision: `promote_eligible_policy_slices_only`
- Slice summary: 5 promotable, 0 held, 2 collect-more-evidence.

Promotable slices: `food_spike`, `proactive_eventops`, `ride_down`, `staff_shortage`, `storm_response`.

Thin slices still requiring evidence: `proactive_watchtower`, `scan`.

## Next Step

Use the recovery plan in `docs/model-improvement-recovery-plan.md` to promote eligible slices and measure ground-truth impact:

1. Promote eligible slices only.
2. Keep thin slices in evidence-collection mode.
3. Require post-promotion outcome measurements before claiming production improvement.
4. Continue collecting scan/watchtower rows until each reaches at least 12 measured outcomes.
