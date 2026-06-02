# ParkPulse Product Shift Prune Report - 2026-06-02

## Scope

Current ParkPulse goal: a production-reliable amusement-park operations platform focused on scan/react/proact workflows, live-feed ingestion, MongoDB-backed operational memory, policy-gated dispatch, delivery idempotency, observability, and operator trust.

Baseline for this prune: deployed `origin/main` at `0f7d282`.

Safety snapshot branch: `codex/local-product-shift-snapshot` at `1218e09`.

Reduced branch: `codex/product-shift-pruned`.

## Decision

Keep the reduced branch based on deployed `main`. Do not carry the full product-shift snapshot forward as-is.

The snapshot adds 118 changed files and about 40k net lines beyond deployed `main`. The biggest risk is not individual compile failure; it is product drift. Restoring the snapshot wholesale would mix customer-facing emergency chat, executive intelligence, experience-studio authoring, accessibility journey pages, staff-training roleplay, agent handshake protocol, role access, ops chat, training generation, and platform maturity dashboards into the same release surface.

That broad merge would weaken the current reliability goal by increasing route count, import cost, authorization complexity, QA scope, demo risk, and latency exposure before each feature has a narrow production contract.

## Kept In The Reduced Platform

These are already present on deployed `main` and remain in `codex/product-shift-pruned`:

- MongoDB-backed live-feed storage and health checks.
- Six live-feed loaders: weather, ride ops, guest flow, staffing, food ops, and operator signal.
- Stale-feed refresh supervisor.
- Normalized live-feed event ingestion.
- Review training ledger.
- Command-center live-feed controls.
- Production reliability QA surfaces for scan/react/proact, delivery receipts, policy gates, and observability.
- Cloud Run deployment scripts with MongoDB live-feed storage configuration.

## Pruned For Now

These snapshot areas are not reattached to the reduced branch:

- Customer emergency chatbot and public customer park knowledge.
- Executive experience intelligence and artifact review.
- Experience Studio and venue data authoring.
- Staff training roleplay pages.
- Accessibility journey page.
- Agent handshake protocol pages and routes.
- Frontpage visual demo rewrite.
- Broad `backend/main.py` and `backend/parkpulse_api.py` route expansion.

Reason: these can be valuable, but they are separate product surfaces. They require separate acceptance criteria, identity/authorization policy, live-data boundaries, load tests, and user-flow QA before they belong in the production reliability platform.

## Conditionally Useful Reliability Features

These snapshot features still look aligned, but should be reattached only as narrow, focused PRs:

1. Role access contracts
   - Source: `backend/park_role_access.py`, `backend/test_role_access_contracts.py`, `frontend/src/features/command-center/RoleAccessPanel.tsx`.
   - Why useful: improves operator trust and protects privileged actions.
   - Required before merge: production identity provider boundary, no default dev issuer in production, authorization audit persistence, tests proving protected dispatch/read routes cannot bypass the gate.

2. Review label pipeline
   - Source: `backend/review_label_pipeline.py`, `backend/test_review_label_pipeline.py`, `frontend/src/features/command-center/ReviewLabelPipelinePanel.tsx`.
   - Why useful: helps convert operator review decisions into controlled training evidence.
   - Required before merge: no LLM-generated labels accepted as truth, explicit human final-label flow, Mongo persistence contract, training-readiness tests.

3. Ops chat quality monitor
   - Source: `backend/park_ops_chat_quality.py`, `backend/test_park_ops_chat_live_quality.py`, `frontend/src/features/command-center/ParkOpsChatQualityPanel.tsx`.
   - Why useful: supports operator trust for natural-language ops requests.
   - Required before merge: bounded answer contract, policy refusal coverage, no direct dispatch authority, latency budget test.

4. Platform maturity / decision trace panels
   - Source: `frontend/src/features/command-center/PlatformMaturityPanel.tsx`, `frontend/src/features/command-center/DecisionTracePanel.tsx`, related backend snapshot routes.
   - Why useful: improves observability.
   - Required before merge: backend endpoints must be small and cached; no broad `main.py` restore.

## Comparison

Reduced branch:

- Starts from deployed `main`.
- Keeps the validated live-feed package.
- Avoids broad route expansion and product-surface drift.
- Has smaller QA and deployment blast radius.

Snapshot branch:

- Preserves all local product-shift work for future extraction.
- Contains valuable prototypes, but they are not release-ready as one combined merge.
- Requires feature-by-feature narrowing before production QA can produce a meaningful go/no-go.

## Next Repair Order

1. Run full QA on `codex/product-shift-pruned` to confirm the deployed platform remains green.
2. Reattach `review_label_pipeline` as the first focused reliability PR.
3. Reattach `park_role_access` as the second focused reliability PR.
4. Reattach ops chat quality only after role access exists.
5. Leave customer, executive, experience-studio, accessibility journey, and staff-training surfaces in the snapshot until the product goal explicitly expands beyond ops reliability.

## Go / No-Go

Recommendation: GO WITH CONDITIONS for the reduced branch.

Conditions:

- Do not merge the snapshot wholesale.
- Treat each conditionally useful feature as a separate PR with its own API contract, tests, typecheck, and latency check.
- Preserve `codex/local-product-shift-snapshot` until all useful pieces have either been extracted or intentionally retired.

## Verification

Run on `codex/product-shift-pruned` after the prune decision:

- `backend/venv/bin/python -m pytest backend/test_production_reliability_repairs.py backend/test_live_feedback_loop.py backend/test_weather_live_feed.py backend/test_ride_ops_live_feed.py backend/test_guest_flow_live_feed.py backend/test_remaining_live_feeds.py backend/test_production_reliability_qa_agent.py`
  - Result: 34 passed in 42.99s.
- `frontend/node_modules/.bin/tsc --noEmit -p frontend/tsconfig.typecheck.json`
  - Result: passed.

Note: `npm exec tsc -- --noEmit -p frontend/tsconfig.typecheck.json` was not used for final verification because it attempted a registry lookup in the restricted network environment. The local compiler binary passed.
