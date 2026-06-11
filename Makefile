PERF_BASE_URL ?= http://127.0.0.1:8000
PERF_DURATION ?= 30
PERF_CONCURRENCY ?= 50
PERF_TARGET_P95_MS ?= 250
TEST_PYTHON ?= /tmp/parkpulse_backend_venv/bin/python

.PHONY: qa qa-fast qa-release qa-live qa-quick qa-backend qa-frontend qa-spring agent-role-eval-gate loop-resilience loop-resilience-monitor live-agents-smoke live-feed-agent-smoke live-feed-training-closure live-feed-agent-report live-feed-learning-loop-validation weekly-budget-prune one-day-timelapse-cost-probe one-day-timelapse-candidate-ranking-probe timelapse-policy-scorecard timelapse-frozen-benchmark timelapse-model-improvement timelapse-model-eval timelapse-memory-influence ranked-reasoning-action-report llm-policy-interpreter experience-studio-dev experience-studio-demo-verify test-unit test-integration-collect coverage coverage-backend coverage-frontend perf-smoke gcp-bootstrap gcp-local gcp-judge-smoke gcp-judge-smoke-strict gcp-build-ops-agent-release gcp-deploy-private gcp-deploy-private-diagnostics gcp-deploy-frontend gcp-dev-private gcp-proxy-private gcp-smoke-private gcp-validate-private gcp-verify-agent-roles gcp-preflight-mongo-model gcp-schedule-loop-resilience

qa:
	python3 scripts/qa_agent.py

qa-fast:
	python3 scripts/qa_agent.py --quick

qa-release:
	python3 scripts/qa_agent.py --source-stability --fail-on-warning

qa-live:
	python3 scripts/qa_agent.py --live-only

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

loop-resilience:
	PYTHONPATH=backend python3 scripts/validate_operating_loop_resilience.py

loop-resilience-monitor:
	PYTHONPATH=backend python3 scripts/monitor_operating_loop_resilience.py

live-agents-smoke:
	PARKPULSE_GEMINI_TIMEOUT_SECONDS=$${PARKPULSE_GEMINI_TIMEOUT_SECONDS:-6} PARKPULSE_GEMINI_REACTION_TIMEOUT_SECONDS=$${PARKPULSE_GEMINI_REACTION_TIMEOUT_SECONDS:-3} PARKPULSE_PROACTIVE_GEMINI_TIMEOUT_SECONDS=$${PARKPULSE_PROACTIVE_GEMINI_TIMEOUT_SECONDS:-2} PARKPULSE_PROACTIVE_BRIEF_TIMEOUT_SECONDS=$${PARKPULSE_PROACTIVE_BRIEF_TIMEOUT_SECONDS:-2.5} PARKPULSE_PROACTIVE_ROLE_TIMEOUT_SECONDS=$${PARKPULSE_PROACTIVE_ROLE_TIMEOUT_SECONDS:-20} PARKPULSE_PROACTIVE_ROLE_HOT_PATH_ONLY=$${PARKPULSE_PROACTIVE_ROLE_HOT_PATH_ONLY:-true} PYTHONPATH=backend python3 scripts/live_all_agents_smoke.py

live-feed-agent-smoke:
	PARKPULSE_GEMINI_TIMEOUT_SECONDS=$${PARKPULSE_GEMINI_TIMEOUT_SECONDS:-6} PARKPULSE_GEMINI_REACTION_TIMEOUT_SECONDS=$${PARKPULSE_GEMINI_REACTION_TIMEOUT_SECONDS:-3} PARKPULSE_PROACTIVE_GEMINI_TIMEOUT_SECONDS=$${PARKPULSE_PROACTIVE_GEMINI_TIMEOUT_SECONDS:-2} PARKPULSE_PROACTIVE_BRIEF_TIMEOUT_SECONDS=$${PARKPULSE_PROACTIVE_BRIEF_TIMEOUT_SECONDS:-2.5} PARKPULSE_PROACTIVE_ROLE_TIMEOUT_SECONDS=$${PARKPULSE_PROACTIVE_ROLE_TIMEOUT_SECONDS:-20} PARKPULSE_PROACTIVE_ROLE_HOT_PATH_ONLY=$${PARKPULSE_PROACTIVE_ROLE_HOT_PATH_ONLY:-true} PYTHONPATH=backend python3 scripts/live_feed_agent_smoke.py

live-feed-training-closure:
	PYTHONPATH=backend python3 scripts/live_feed_training_closure.py

live-feed-agent-report:
	python3 scripts/render_live_feed_agent_report.py

live-feed-learning-loop-validation:
	PYTHONPATH=backend:. python3 scripts/live_feed_learning_loop_validation.py

weekly-budget-prune:
	python3 scripts/prune_parkpulse_weekly_data.py

one-day-timelapse-cost-probe:
	PYTHONPATH=backend python3 scripts/run_one_day_timelapse_cost_probe.py

one-day-timelapse-candidate-ranking-probe:
	PYTHONPATH=backend python3 scripts/run_one_day_timelapse_cost_probe.py --call-gemini --gemini-candidate-ranking --execute-gemini-actions

timelapse-policy-scorecard:
	python3 scripts/evaluate_timelapse_policy_scorecard.py --run-dir "$(RUN_DIR)" $(if $(BASELINE_RUN_DIR),--baseline-run-dir "$(BASELINE_RUN_DIR)")

timelapse-frozen-benchmark:
	PYTHONPATH=backend:scripts python3 scripts/run_timelapse_frozen_benchmark.py $(if $(CALL_GEMINI),--call-gemini) $(if $(SCENARIOS),--scenarios "$(SCENARIOS)") $(if $(SEEDS),--seeds "$(SEEDS)") $(if $(SIM_MINUTES),--sim-minutes "$(SIM_MINUTES)") $(if $(GEMINI_RETRIES),--gemini-retries "$(GEMINI_RETRIES)") $(if $(COUNTERFACTUAL_HORIZON_MINUTES),--counterfactual-horizon-minutes "$(COUNTERFACTUAL_HORIZON_MINUTES)") $(if $(SCORE_GAP_OVERRIDE),--score-gap-override "$(SCORE_GAP_OVERRIDE)") $(if $(SCORE_CALIBRATION_REPORT),--score-calibration-report "$(SCORE_CALIBRATION_REPORT)") $(if $(USE_MONGODB_MEMORY),--use-mongodb-memory) $(if $(MEMORY_LIMIT),--memory-limit "$(MEMORY_LIMIT)")

timelapse-model-improvement:
	PYTHONPATH=backend python3 scripts/materialize_timelapse_model_improvement.py --benchmark-report "$(BENCHMARK_REPORT)" $(if $(PERSIST_MONGODB),--persist-mongodb)

timelapse-model-eval:
	PYTHONPATH=backend python3 scripts/evaluate_timelapse_model_improvement.py --eval-jsonl "$(EVAL_JSONL)" $(if $(CALL_GEMINI),--call-gemini) $(if $(USE_MONGODB_MEMORY),--use-mongodb-memory) $(if $(MEMORY_LIMIT),--memory-limit "$(MEMORY_LIMIT)")

timelapse-memory-influence:
	PYTHONPATH=backend:scripts python3 scripts/analyze_memory_influence.py --memory-report "$(MEMORY_REPORT)" $(if $(CONTROL_REPORT),--control-report "$(CONTROL_REPORT)")

ranked-reasoning-action-report:
	python3 scripts/render_ranked_reasoning_action_report.py $(if $(BASELINE_REPORT),--baseline-report "$(BASELINE_REPORT)") $(if $(EXPANDED_REPORT),--expanded-report "$(EXPANDED_REPORT)") $(if $(OUTPUT_ROOT),--output-root "$(OUTPUT_ROOT)")

llm-policy-interpreter:
	PYTHONPATH=backend python3 scripts/evaluate_llm_policy_interpreter.py $(if $(CALL_GEMINI),--call-gemini)

experience-studio-dev:
	scripts/dev_experience_studio.sh

experience-studio-demo-verify:
	python3 scripts/verify_experience_studio_demo.py --base-url $(PERF_BASE_URL) --html-output output/qa/experience-studio-demo-verification.html

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

gcp-judge-smoke:
	PYTHONPATH=backend python3 scripts/gcp_judge_smoke.py

gcp-judge-smoke-strict:
	ENABLE_GCP_CLOUD_TRACE_EXPORT=$${ENABLE_GCP_CLOUD_TRACE_EXPORT:-true} PARKPULSE_ENABLE_OTEL_SPANS=$${PARKPULSE_ENABLE_OTEL_SPANS:-true} PARKPULSE_LIVE_BIGQUERY=$${PARKPULSE_LIVE_BIGQUERY:-true} PYTHONPATH=backend python3 scripts/gcp_judge_smoke.py --strict --blocking-hosted-eval

gcp-build-ops-agent-release:
	scripts/build_ops_agent_backend_release_source.sh

gcp-deploy-private:
	scripts/deploy_private_cloud_run.sh

gcp-deploy-private-diagnostics:
	scripts/deploy_private_cloud_run_diagnostics.sh

gcp-deploy-frontend:
	scripts/deploy_frontend_cloud_run.sh

gcp-dev-private:
	scripts/dev_private_gcp.sh

gcp-proxy-private:
	scripts/proxy_private_cloud_run.sh

gcp-smoke-private:
	scripts/cloud_run_private_curl.sh

gcp-validate-private:
	scripts/validate_private_gcp_demo.sh

gcp-verify-agent-roles:
	scripts/verify_private_cloud_run_agent_roles.sh

gcp-preflight-mongo-model:
	python3 scripts/preflight_mongodb_model_api.py

gcp-schedule-loop-resilience:
	scripts/schedule_operating_loop_resilience.sh
