# ParkPulse Park Understanding Benchmark

Generated: 2026-06-03

## Purpose

This benchmark measures whether the LLM understands the park itself, not just whether reward curves improved.

It checks whether an answer or plan is grounded in known park facts:

- Scenario identification.
- Named ride, zone, route, facility, and landmark grounding.
- Route and facility reasoning.
- Conflict resolution when live constraints contradict the normal best route.
- Safety and policy constraints.
- Operational action quality.
- Evidence use: the answer must explicitly carry forward live facts from the prompt.
- Hallucination control.

This benchmark does not train, dispatch, set reward, or promote policies. It is a context/prompt understanding gate.

## API

- `GET /api/park/understanding-benchmark/cases`
- `POST /api/park/understanding-benchmark`
- `GET /api/park/understanding-benchmark/latest`

Request body for a custom LLM response run:

```json
{
  "case_id": "unknown_facility_hallucination_trap",
  "candidate_responses": {
    "unknown_facility_hallucination_trap": "The public venue map does not list a monorail station. Use Guest Services near the Front Gate for help finding known destinations."
  },
  "write_artifact": true
}
```

If `candidate_responses` is omitted, the benchmark runs the built-in ParkPulse grounded-context baseline. To evaluate the actual live Gemini path, use:

```json
{
  "provider": "gemini",
  "timeout_seconds": 14,
  "write_artifact": true
}
```

## Cases

| Case | What it tests |
| --- | --- |
| `ride_down_family_reroute` | Dragon Coaster downtime, Coaster Plaza, route mix, Food Court A overload avoidance, maintenance clearance. |
| `food_spike_mobile_pickup` | Food Court A backlog, Food Court B redirect, mobile pickup, invented restaurant avoidance. |
| `storm_shelter_comfort` | Indoor Hub, Theater B, Arcade Zone, Covered Plaza, Sky Drop avoidance, HVAC comfort protection. |
| `staff_shortage_certification_boundary` | Coaster Plaza staffing, cross-trained staff, break protection, uncertified-role boundary. |
| `guest_care_first_aid_boundary` | Care Lagoon First Aid, Guest Services, Family Reunification Point, medical privacy. |
| `unknown_facility_hallucination_trap` | Unknown monorail request, uncertainty, no invented facility or route. |
| `conflicting_ride_food_capacity` | Dragon Coaster downtime with Food Court A backlog, Theater B capacity, Arcade Zone comfort, Covered Plaza water/shade, and Food Court B routing. |
| `storm_accessibility_privacy_tradeoff` | Storm routing with mobility needs, Covered Plaza filling, Indoor Hub accessibility, First Aid, Guest Services, and privacy. |

## Current Audited Baseline Run

- Report ID: `park_understanding_benchmark_fb6c3922ea9adf19`
- Status: passed.
- Evaluation target: `grounded_context_baseline_only`.
- Live LLM evaluated: false.
- Case count: 8.
- Passed cases: 8.
- Failed cases: 0.
- Average score: 99.08.
- Minimum average score: 85.
- Decision: `baseline_passed_but_live_llm_not_evaluated`.
- Artifact: `/tmp/parkpulse/understanding_benchmark/park_understanding_benchmark_fb6c3922ea9adf19.json`

Investigation finding: the strict baseline report is not proof that the live LLM understands the park. It proves that the grounded ParkPulse context baseline can satisfy the benchmark. A live LLM claim is blocked until actual LLM responses are supplied through `candidate_responses`.

## Latest Live LLM Run

- Report doc: `docs/park-understanding-live-report-2026-06-03.md`
- Report ID: `park_understanding_benchmark_80f1e74ea3a9ccd9`
- Evaluation target: `live_gemini_responses`
- Live LLM evaluated: true.
- Status: passed.
- Passed cases: 8/8.
- Average score: 97.72.
- Decision: `allow_live_llm_park_understanding_claim`.
- Artifact: `/tmp/parkpulse/understanding_benchmark/park_understanding_benchmark_80f1e74ea3a9ccd9.json`.

The live LLM now passes the strict park-understanding gate for the current suite. This allows the understanding claim, but it remains separate from production reward promotion and ground-truth impact measurement.

The old 6-case baseline was too easy because it mostly checked whether the answer mentioned the right park facts. The strict version adds:

- Conflict-resolution scoring.
- Evidence-use scoring.
- Higher grounding requirements in adversarial cases.
- Explicit failure tests for generic safe-sounding answers.
- Explicit failure tests for static favorite-route advice that ignores live constraints.

The audited scorer also now:

- Scores only the candidate answer text, not structured metadata such as `grounded_entities`.
- Marks dimensions as not applicable when a case has no rule for that dimension, instead of auto-awarding 100.
- Records `evaluation_target`, `live_llm_evaluated`, and baseline/provided response counts.
- Blocks the live-understanding decision when all responses came from the grounded baseline.
- Records Gemini finish reasons, usage metadata, and malformed-output retry reasons during live generation.

The live generation path also now disables Gemini REST thinking with `thinkingBudget: 0`; this fixed incomplete JSON caused by hidden thinking tokens consuming output budget.

## Release Rule

Before claiming that the LLM understands the park better:

1. Run this benchmark against the actual LLM output, not only the baseline expected answer.
2. Require average score >= 85.
3. Require every critical dimension to pass:
   - `scenario_identification`
   - `entity_grounding`
   - `conflict_resolution`
   - `safety_constraints`
   - `evidence_use`
   - `hallucination_control`
4. Require zero forbidden hallucinated park facts.
5. Keep reward/promotion decisions separate from this understanding score.
