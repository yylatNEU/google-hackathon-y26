# Legacy Quarantine Manifest: Generated Artifacts

Date: 2026-05-24

Scope: low-risk generated local artifacts only. No source modules, configs, runtime databases, database backups, virtual environments, frontend build output, trace exports, or QA reports were moved.

## Post-Quarantine Validation

- Backend compile: passed, 52 Python files compiled.
- Backend tests: passed with explicit local GCP env, 101 passed with 1 Pydantic deprecation warning.
- Frontend build: passed with Vite; JS 501.65 kB / gzip 135.20 kB, CSS 62.96 kB / gzip 11.09 kB. Vite reported the JS chunk-size warning because the minified bundle is just over 500 kB.
- Frontend lint: passed after refreshing `frontend/node_modules` with `npm ci`; 0 errors, 53 warnings.
- Backend startup/API smoke: passed for `/healthz`.
- Frontend route smoke: passed for `/` through Vite preview.

## Moved Artifacts

FILE: `.pytest_cache/`
RISK: SAFE_DELETE candidate
REASON: Pytest runtime cache; no application imports, routes, Docker references, or runtime dependencies.
DEPENDENCY TRACE: Tool-generated cache only.
RUNTIME EVIDENCE: Backend tests and app startup do not require pre-existing cache contents.
RECOMMENDED ACTION: Keep quarantined for one validation cycle, then remove permanently if no regressions.
ROLLBACK PLAN: `mv legacy-quarantine/20260524-generated-artifacts/root/pytest_cache .pytest_cache`

FILE: `backend/.pytest_cache/`
RISK: SAFE_DELETE candidate
REASON: Pytest runtime cache; no application imports, routes, Docker references, or runtime dependencies.
DEPENDENCY TRACE: Tool-generated cache only.
RUNTIME EVIDENCE: Backend tests and app startup do not require pre-existing cache contents.
RECOMMENDED ACTION: Keep quarantined for one validation cycle, then remove permanently if no regressions.
ROLLBACK PLAN: `mv legacy-quarantine/20260524-generated-artifacts/backend/pytest_cache backend/.pytest_cache`

FILE: `backend/__pycache__/`
RISK: SAFE_DELETE candidate
REASON: Python bytecode cache; source `.py` files remain intact and Python recreates bytecode as needed.
DEPENDENCY TRACE: Explicitly excluded by coverage/QA tooling.
RUNTIME EVIDENCE: Backend compile and pytest validation regenerate bytecode when needed.
RECOMMENDED ACTION: Keep quarantined for one validation cycle, then remove permanently if no regressions.
ROLLBACK PLAN: `mv legacy-quarantine/20260524-generated-artifacts/backend/pycache backend/__pycache__`

FILE: `scripts/__pycache__/`
RISK: SAFE_DELETE candidate
REASON: Python bytecode cache for scripts; source `.py` files remain intact.
DEPENDENCY TRACE: Explicitly excluded by QA tooling.
RUNTIME EVIDENCE: Python recreates bytecode as needed.
RECOMMENDED ACTION: Keep quarantined for one validation cycle, then remove permanently if no regressions.
ROLLBACK PLAN: `mv legacy-quarantine/20260524-generated-artifacts/scripts/pycache scripts/__pycache__`

FILE: `.DS_Store`, `backend/.DS_Store`, `frontend/.DS_Store`, `scripts/.DS_Store`
RISK: SAFE_DELETE candidate
REASON: macOS Finder metadata; no application dependency.
DEPENDENCY TRACE: No import/config/runtime references.
RUNTIME EVIDENCE: Not required for build, tests, startup, or route rendering.
RECOMMENDED ACTION: Keep quarantined for one validation cycle, then remove permanently if no regressions.
ROLLBACK PLAN: Move each `DS_Store` file from the matching quarantine subdirectory back to its original `.DS_Store` path.

## Protected And Not Moved

- `backend/park_replay.db`, `backend/park_data.db`, `backend/db_backups/`: runtime data/backups.
- `backend/venv/`, `.venv-smoke/`: dependency environments.
- `frontend/dist/`: current Vite preview/build output.
- `output/`: QA and coverage history.
- `.arize-tmp-traces/`: trace export evidence.
- `frontend/.next-build/`, `frontend/.next-dev/`: legacy Next build dirs referenced by scripts/configs.
