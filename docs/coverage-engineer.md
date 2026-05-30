# Coverage Engineer

The project-level coverage engineer lives at `scripts/coverage_engineer.py`. It runs backend and frontend coverage checks and fails unless every selected scope reaches at least 98% line coverage.

## Commands

```bash
make coverage
make coverage-backend
make coverage-frontend
python3 scripts/coverage_engineer.py --threshold 98
```

Reports are written to `output/coverage/latest.md` and `output/coverage/latest.json`.

## Gate Rules

- Backend coverage uses `coverage run --source backend -m pytest` against discovered `test_*.py` or `*_test.py` files under `backend/` or `tests/`.
- Frontend coverage uses an npm `coverage`, `test:coverage`, or coverage-enabled `test` script and expects a coverage summary in `frontend/coverage/coverage-summary.json`.
- The default threshold is 98%. Lower thresholds are for local diagnosis only.
- Missing tests or missing coverage tooling are failures, not skips.

## Current Project State

At the time this engineer was added, no backend or frontend test files were present. The coverage gate is intentionally strict and will fail until real tests and frontend coverage tooling are added.
