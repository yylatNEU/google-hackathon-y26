PERF_BASE_URL ?= http://127.0.0.1:8000
PERF_DURATION ?= 30
PERF_CONCURRENCY ?= 50
PERF_TARGET_P95_MS ?= 250
TEST_PYTHON ?= /tmp/parkpulse_backend_venv/bin/python

.PHONY: qa qa-quick qa-backend qa-frontend qa-spring agent-role-eval-gate live-agents-smoke live-feed-agent-smoke test-unit test-integration-collect coverage coverage-backend coverage-frontend perf-smoke gcp-bootstrap gcp-local gcp-deploy-private gcp-dev-private gcp-proxy-private gcp-smoke-private gcp-validate-private

qa:
	python3 scripts/qa_agent.py

qa-quick:
	python3 scripts/qa_agent.py --quick

qa-backend:
	python3 scripts/qa_agent.py --backend-only

qa-frontend:
	python3 scripts/qa_agent.py --frontend-only

qa-spring:
	cd spring-backend && ./mvnw test

agent-role-eval-gate:
	python3 scripts/agent_role_eval_gate.py

live-agents-smoke:
	PYTHONPATH=backend python3 scripts/live_all_agents_smoke.py

live-feed-agent-smoke:
	PYTHONPATH=backend python3 scripts/live_feed_agent_smoke.py

test-unit:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=backend $(TEST_PYTHON) -m pytest backend/test_policy_engine.py backend/test_policy_loader.py -q

test-integration-collect:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=backend $(TEST_PYTHON) -m pytest --collect-only -q backend/test_parkpulse_completion.py

coverage:
	python3 scripts/coverage_engineer.py

coverage-backend:
	python3 scripts/coverage_engineer.py --backend-only

coverage-frontend:
	python3 scripts/coverage_engineer.py --frontend-only

perf-smoke:
	python3 scripts/load_test_parkpulse.py --base-url $(PERF_BASE_URL) --duration $(PERF_DURATION) --concurrency $(PERF_CONCURRENCY) --target-p95-ms $(PERF_TARGET_P95_MS)

gcp-bootstrap:
	scripts/gcp_bootstrap_private.sh

gcp-local:
	scripts/run_local_gcp.sh

gcp-deploy-private:
	scripts/deploy_private_cloud_run.sh

gcp-dev-private:
	scripts/dev_private_gcp.sh

gcp-proxy-private:
	scripts/proxy_private_cloud_run.sh

gcp-smoke-private:
	scripts/cloud_run_private_curl.sh

gcp-validate-private:
	scripts/validate_private_gcp_demo.sh
