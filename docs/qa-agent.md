# Routine QA Agent

The project-level QA agent lives at `scripts/qa_agent.py`. It runs deterministic checks across the Python backend and Next.js frontend, then writes Markdown and JSON reports to `output/qa`.

The deployed Production Reliability QA Engineer lives in the backend role system as `parkpulse.production_reliability_qa`. It is a read-only ParkPulse agent for go/no-go reliability review, failure-mode coverage, policy-gate safety, fallback behavior, dispatch idempotency, observability, and load readiness.

## Commands

```bash
make qa
make qa-quick
make qa-backend
make qa-frontend
```

## Production Reliability QA Agent

Invoke the deployed agent through either endpoint:

```bash
curl -s -X POST http://127.0.0.1:8000/api/park/reliability-qa-run \
  -H 'content-type: application/json' \
  -d '{"message":"production reliability QA go/no-go for ParkPulse"}'

curl -s -X POST http://127.0.0.1:8000/api/park/agent-role-run \
  -H 'content-type: application/json' \
  -d '{"mode":"qa","message":"pre-deploy failure mode matrix"}'
```

The agent contract is available at:

```bash
curl -s http://127.0.0.1:8000/api/park/reliability-qa-agent
```

Skill definition: `.agents/skills/parkpulse-production-reliability-qa-agent/SKILL.md`.

Use `make qa` before demos, merges, or deploys. Use `make qa-quick` during active iteration when a production build is too slow.

For strict test coverage enforcement, run the coverage engineer:

```bash
make coverage
```

That gate requires every selected scope to report at least 98% line coverage. See `docs/coverage-engineer.md`.

## Gates

- Project inventory: verifies required backend/frontend files and scripts are present.
- Static hygiene: scans text files for merge conflicts, high-confidence secrets, and open task markers.
- Backend compile: compiles every backend Python file outside virtual environments and caches.
- Backend smoke: loads policy books, simulation state, and governance status without calling external LLM APIs.
- Frontend lint: runs the existing `npm run lint` command.
- Frontend TypeScript: runs `npx tsc --noEmit --pretty false`.
- Frontend build: runs `npm run build` unless `--quick` is used.
- Production Reliability QA role: verifies a read-only go/no-go report contract for scan/react/proact reliability, dependency degradation, policy gates, and observability expectations.

Failures exit non-zero. Warnings are reported but do not fail the run unless `--fail-on-warning` is passed.
