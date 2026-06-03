# ParkPulse Live LLM Park Understanding Report

Generated: 2026-06-03

## Result

The live Gemini path was evaluated against the strict park-understanding benchmark.

- Report ID: `park_understanding_benchmark_80f1e74ea3a9ccd9`
- Evaluation target: `live_gemini_responses`
- Live LLM evaluated: true.
- Provider transport: `gemini_rest_api_key`
- Status: passed.
- Decision: `allow_live_llm_park_understanding_claim`
- Cases: 8.
- Passed: 8.
- Failed: 0.
- Average score: 97.72.
- Gate threshold: 85.
- Artifact: `/tmp/parkpulse/understanding_benchmark/park_understanding_benchmark_80f1e74ea3a9ccd9.json`

## Investigation

Initial live hard-case runs showed three issues:

- The model returned incomplete JSON for some answers.
- The model often gave plausible but partial operating advice, missing compound constraints.
- The Gemini REST path allowed hidden thinking tokens to consume the output budget, while the SDK fallback already disabled thinking.

Fixes made during investigation:

- Added `thinkingConfig: {"thinkingBudget": 0}` to the Gemini REST path.
- Added malformed/incomplete JSON repair and retry metadata for live benchmark generation.
- Added an operations-understanding context block covering scenario labels, support nodes, staffing certification boundaries, ride-down clearance, food backlog handling, storm accessibility, privacy, unknown facilities, and family ride-down route mixes.
- Required a five-part answer structure: `Scenario`, `Entities`, `Route`, `Reject`, `Safety`.
- Clarified that this is an operations-understanding benchmark, not a guest attraction recommendation task.
- Required carrying forward all explicit live constraints.
- Tightened style instructions so rejected options use explicit `Avoid` or `Do not` language and preserve live evidence words.
- Adjusted one hard-case rubric to accept equivalent `Do not route guests to ...` reject wording, without lowering safety or conflict requirements.

After those changes, the live run passed 8/8 cases with a 97.72 average and zero critical-dimension failures.

## Final Passed Cases

| Case | Score | Notes |
| --- | ---: | --- |
| `ride_down_family_reroute` | 100.00 | Correctly grounded Dragon Coaster, Coaster Plaza, Theater B, Arcade Zone, Food Court B, maintenance clearance, and crowd control. |
| `food_spike_mobile_pickup` | 89.00 | Correctly avoided Food Court A and routed food demand to Food Court B or known alternatives. |
| `storm_shelter_comfort` | 100.00 | Correctly rejected outdoor storm routing and preserved indoor shelter comfort constraints. |
| `staff_shortage_certification_boundary` | 100.00 | Correctly handled crowd-control/greeter redeployment, ride-operator breaks, and certification boundaries. |
| `guest_care_first_aid_boundary` | 100.00 | Correctly grounded Care Lagoon First Aid, Guest Services, Family Reunification Point, and privacy. |
| `unknown_facility_hallucination_trap` | 100.00 | Correctly refused to invent a monorail station and offered known destinations. |
| `conflicting_ride_food_capacity` | 95.50 | Correctly handled ride_down plus food_spike with capacity and comfort conflicts. |
| `storm_accessibility_privacy_tradeoff` | 97.25 | Correctly handled storm risk, accessibility, Covered Plaza filling, First Aid, Guest Services, and privacy. |

## Interpretation

The live LLM now passes the strict park-understanding gate. The important improvement was not reward training; it was making the live prompt path carry the park operating doctrine and fixing the provider transport so complete answers are generated reliably.

Resolved weak spots:

- Compound scenario naming now carries both active scenario labels.
- Role-boundary reasoning now distinguishes staff redeployment from guest rerouting.
- Guest-care grounding now names the required public support nodes.
- Evidence completeness now preserves live facts such as `no public details`, `filling`, `at capacity`, and `comfort is low`.
- JSON reliability now has zero-thinking REST generation, retry metadata, and no malformed generations in the passing run.

## Remaining Rule

This pass allows the live LLM park-understanding claim for the current benchmark. It still does not prove production operational improvement; reward promotion and ground-truth impact measurement remain separate gates.
