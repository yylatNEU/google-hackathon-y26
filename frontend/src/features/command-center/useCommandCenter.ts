"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParkPulseState } from "@/hooks/useParkPulseState";
import { fetchParkPulseApi, longRunningRequestTimeoutMs } from "@/lib/api";
import { agentBriefsFromRuntime } from "@/lib/parkPulseAgents";
import type { AgentBrief, DeliveryDispatch, EvalScore, IntegrationStatus, RunTelemetry } from "@/types/platform";

type RunPayload = RunTelemetry & {
  run_telemetry?: RunTelemetry;
  operator_response?: RunTelemetry["operator_response"];
};

export type DispatchView = {
  id: string;
  channel: string;
  target: string;
  body: string;
  guardrail?: string;
  status?: string;
  source: "runtime";
  dispatch?: DeliveryDispatch;
};

export type ActualTrainingStatus = {
  status?: string;
  mode?: string;
  uses_generated_data?: boolean;
  source?: string;
  sample_count?: number;
  min_sample_count?: number;
  model?: {
    type?: string;
    update_rule?: string;
    best_policy_id?: string | null;
    ranked_policies?: Array<{ policy_id?: string; sample_count?: number; average_reward?: number; best_reward?: number; latest_reward?: number }>;
    context_values?: Array<{ context?: string; ranked_policies?: Array<{ policy_id?: string; q_value?: number; sample_count?: number }> }>;
    authority?: string;
  };
  gcp_ml?: {
    online_improvement?: { ready?: boolean; mode?: string; readiness_issues?: string[] };
    bigquery?: { ready?: boolean; project?: string; dataset?: string; readiness_issues?: string[] };
    bigquery_ml_training?: {
      status?: string;
      enabled?: boolean;
      tool?: string;
      model_id?: string | null;
      job_id?: string | null;
      start_condition?: string;
      readiness_issues?: string[];
    };
  };
  episode_fitness?: {
    status?: string;
    mode?: string;
    uses_generated_data?: boolean;
    sample_count?: number;
    average_reward_delta?: number;
    average_pressure_reduction?: number;
    improvement_rate?: number;
    latest_episode?: {
      id?: string;
      source?: string;
      scenario_key?: string;
      action?: { target?: string; action?: string };
      scores?: { actual?: number; baseline?: number; reward_delta?: number; fitness?: number };
      pressure?: { reduction_vs_baseline?: number; reduced_pressure?: boolean };
      active_random_incidents?: Array<{ kind?: string; intensity?: number }>;
    } | null;
  };
  debug?: {
    readiness_issues?: string[];
    memory_rows_available?: number;
    bigquery_rows_available?: number;
  };
};

export type LiveFeedHealth = {
  status?: string;
  mode?: string;
  cache?: { status?: string; ttl_seconds?: number };
  summary?: {
    required_feed_count?: number;
    ready_feed_count?: number;
    missing_or_weak_feed_count?: number;
    open_review_count?: number;
  };
  feeds?: Array<{
    source?: string;
    label?: string;
    owner?: string;
    status?: string;
    age_seconds?: number | null;
    max_stale_seconds?: number;
    confidence?: number;
    latest_signal_type?: string;
    readiness_issues?: string[];
    value?: unknown;
  }>;
  open_reviews?: ReviewTrainingLedger["rows"];
  growth_loop?: string[];
  readiness_issues?: string[];
};

export type ReviewTrainingLedger = {
  status?: string;
  mode?: string;
  summary?: {
    open_count?: number;
    closed_count?: number;
    training_candidate_count?: number;
  };
  rows?: Array<{
    id?: string;
    status?: string;
    reason?: string;
    priority?: string;
    owner?: string;
    training_effect?: string;
    event?: { source?: string; signal_type?: string };
    disposition?: { decision?: string };
  }>;
  open_reviews?: ReviewTrainingLedger["rows"];
  closed_reviews?: ReviewTrainingLedger["rows"];
  training_rule?: string;
  readiness_issues?: string[];
};

export type LiveWeatherLoadResult = {
  status?: string;
  mode?: string;
  provider?: string;
  event_count?: number;
  loaded_at?: string;
  fetch?: { fetched_at?: string; config?: { location_label?: string; source?: string } };
  readiness_issues?: string[];
};

export type LiveRideOpsLoadResult = LiveWeatherLoadResult;
export type LiveGuestFlowLoadResult = LiveWeatherLoadResult;
export type LiveStaffingLoadResult = LiveWeatherLoadResult;
export type LiveFoodOpsLoadResult = LiveWeatherLoadResult;
export type LiveOperatorSignalLoadResult = LiveWeatherLoadResult;

export type LiveFeedRefreshSupervisorResult = {
  status?: string;
  mode?: string;
  refreshed_sources?: string[];
  queued_sources?: string[];
  readiness_issues?: string[];
  remaining_issues?: string[];
  before?: LiveFeedHealth["summary"];
  after?: LiveFeedHealth["summary"];
  after_feeds?: LiveFeedHealth["feeds"];
};

export type LiveAgentsSmokeReport = {
  status?: string;
  mode?: string;
  report_path?: string;
  summary?: {
    status?: string;
    activated_role_count?: number;
    activated_roles?: string[];
    activated_department_count?: number;
    activated_departments?: string[];
    boundary_failed?: boolean;
    real_eval_failed?: boolean;
    role_failures?: unknown[];
    scenario_failures?: unknown[];
  };
  role_runs?: Array<{
    mode?: string;
    status?: string;
    trace_eval_status?: string;
    dispatch_total?: number;
    elapsed_ms?: number;
    latency_budget_status?: string;
  }>;
  real_role_eval?: {
    status?: string;
    decision?: string;
    average_score?: number;
    elapsed_ms?: number;
  };
  registry_boundary?: {
    status?: string;
    agent_count?: number;
    passed?: number;
    failed?: number;
  };
  readiness_issues?: string[];
};

function normalizeRunTelemetry(payload: RunPayload): RunTelemetry {
  return payload.run_telemetry ?? payload;
}

function runtimeDispatchBody(dispatch: DeliveryDispatch) {
  const payload = dispatch.payload;
  if (!payload || typeof payload !== "object") return "Runtime payload body missing.";
  if (typeof payload.message === "string") return payload.message;
  if (typeof payload.task === "string") return payload.task;
  if (typeof payload.command === "string") return payload.command;
  if (typeof payload.promotion?.offer === "string") return payload.promotion.offer;
  return JSON.stringify(payload);
}

function normalizeDispatch(dispatch: DeliveryDispatch, index: number): DispatchView {
  return {
    id: dispatch.id ?? `runtime-dispatch-${index}`,
    channel: dispatch.channel ?? dispatch.targetSystem ?? "receiver",
    target: dispatch.payload?.targetZone ?? dispatch.targetSystem ?? dispatch.endpoint ?? "operations receiver",
    body: runtimeDispatchBody(dispatch),
    status: dispatch.approvalDecision?.decision ?? dispatch.lastAcknowledgement?.choice ?? dispatch.status,
    source: "runtime",
    dispatch,
  };
}

export function useCommandCenter() {
  const park = useParkPulseState();
  const [runTelemetry, setRunTelemetry] = useState<RunTelemetry | null>(null);
  const [integrationStatus, setIntegrationStatus] = useState<IntegrationStatus | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [isDispatching, setIsDispatching] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [isTrainingLoading, setIsTrainingLoading] = useState(false);
  const [isStartingGcpTraining, setIsStartingGcpTraining] = useState(false);
  const [isLiveFeedHealthLoading, setIsLiveFeedHealthLoading] = useState(false);
  const [isRefreshingStaleFeeds, setIsRefreshingStaleFeeds] = useState(false);
  const [isLoadingLiveWeather, setIsLoadingLiveWeather] = useState(false);
  const [isLoadingLiveRideOps, setIsLoadingLiveRideOps] = useState(false);
  const [isLoadingLiveGuestFlow, setIsLoadingLiveGuestFlow] = useState(false);
  const [isLoadingLiveStaffing, setIsLoadingLiveStaffing] = useState(false);
  const [isLoadingLiveFoodOps, setIsLoadingLiveFoodOps] = useState(false);
  const [isLoadingLiveOperatorSignal, setIsLoadingLiveOperatorSignal] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [actualTraining, setActualTraining] = useState<ActualTrainingStatus | null>(null);
  const [liveFeedHealth, setLiveFeedHealth] = useState<LiveFeedHealth | null>(null);
  const [reviewTrainingLedger, setReviewTrainingLedger] = useState<ReviewTrainingLedger | null>(null);
  const [liveWeatherLoad, setLiveWeatherLoad] = useState<LiveWeatherLoadResult | null>(null);
  const [liveRideOpsLoad, setLiveRideOpsLoad] = useState<LiveRideOpsLoadResult | null>(null);
  const [liveGuestFlowLoad, setLiveGuestFlowLoad] = useState<LiveGuestFlowLoadResult | null>(null);
  const [liveStaffingLoad, setLiveStaffingLoad] = useState<LiveStaffingLoadResult | null>(null);
  const [liveFoodOpsLoad, setLiveFoodOpsLoad] = useState<LiveFoodOpsLoadResult | null>(null);
  const [liveOperatorSignalLoad, setLiveOperatorSignalLoad] = useState<LiveOperatorSignalLoadResult | null>(null);
  const [liveFeedRefreshSupervisor, setLiveFeedRefreshSupervisor] = useState<LiveFeedRefreshSupervisorResult | null>(null);
  const [liveAgentsSmoke, setLiveAgentsSmoke] = useState<LiveAgentsSmokeReport | null>(null);

  const activeEvalScores = useMemo<EvalScore[]>(() => {
    const scorecard = runTelemetry?.eval?.scorecard;
    const dimensions = runTelemetry?.eval?.dimension_scores;
    if (dimensions) {
      return Object.entries(dimensions).map(([label, score]) => ({
        label,
        score,
        detail: runTelemetry?.eval?.dimension_explanations?.[label] ?? "Runtime evaluator dimension.",
      }));
    }
    if (scorecard?.overall !== undefined) {
      return [{ label: "Overall runtime eval", score: scorecard.overall, detail: scorecard.status ?? "Runtime scorecard." }];
    }
    return [];
  }, [runTelemetry?.eval]);

  const agentBriefs: AgentBrief[] = useMemo(() => {
    return agentBriefsFromRuntime(runTelemetry?.agent_findings);
  }, [runTelemetry?.agent_findings]);

  const dispatches: DispatchView[] = useMemo(() => {
    const runtimeDispatches = runTelemetry?.delivery?.dispatches ?? [];
    return runtimeDispatches.map(normalizeDispatch);
  }, [runTelemetry?.delivery?.dispatches]);

  const selectedAction = runTelemetry?.planner?.selected_action;
  const policyGate = runTelemetry?.governance?.gate_status;
  const evalScore = runTelemetry?.eval?.scorecard?.overall;
  const memoryMode = runTelemetry?.memory?.mode ?? integrationStatus?.mongo?.mode ?? "unavailable";

  const refreshIntegrationStatus = useCallback(async () => {
    try {
      const response = await fetchParkPulseApi("/api/park/integration-status", { timeoutMs: 5000 });
      setIntegrationStatus((await response.json()) as IntegrationStatus);
    } catch {
      setIntegrationStatus(null);
    }
  }, []);

  const refreshActualTraining = useCallback(async (options?: { runGcpTraining?: boolean }) => {
    const runGcpTraining = options?.runGcpTraining === true;
    setIsTrainingLoading(true);
    if (runGcpTraining) {
      setIsStartingGcpTraining(true);
      setErrorMessage(null);
      setStatusMessage("Starting BigQuery ML training from observed outcome rows.");
    }
    try {
      const response = await fetchParkPulseApi(runGcpTraining ? "/api/park/actual-training?runGcpTraining=true" : "/api/park/actual-training", {
        headers: { "x-parkpulse-role": "ml_ops_admin" },
        timeoutMs: longRunningRequestTimeoutMs,
      });
      const payload = (await response.json()) as ActualTrainingStatus;
      setActualTraining(payload);
      if (runGcpTraining) {
        const bqml = payload.gcp_ml?.bigquery_ml_training;
        setStatusMessage(
          bqml?.status === "started"
            ? `BigQuery ML training started${bqml.job_id ? `: ${bqml.job_id}` : "."}`
            : `BigQuery ML training ${bqml?.status ?? payload.status ?? "not ready"}.`,
        );
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Actual training status failed.";
      setActualTraining({
        status: "error",
        mode: "actual_outcome_training",
        uses_generated_data: false,
        source: "none",
        sample_count: 0,
        debug: { readiness_issues: [message] },
      });
      if (runGcpTraining) setErrorMessage(message);
    } finally {
      setIsTrainingLoading(false);
      if (runGcpTraining) setIsStartingGcpTraining(false);
    }
  }, []);

  const refreshLiveFeedHealth = useCallback(async () => {
    setIsLiveFeedHealthLoading(true);
    try {
      const [healthResponse, ledgerResponse] = await Promise.all([
        fetchParkPulseApi("/api/park/live-feed-health?limit=500", { headers: { "x-parkpulse-role": "ops_team" }, timeoutMs: longRunningRequestTimeoutMs }),
        fetchParkPulseApi("/api/park/review-training-ledger?limit=80", { headers: { "x-parkpulse-role": "ops_team" }, timeoutMs: longRunningRequestTimeoutMs }),
      ]);
      setLiveFeedHealth((await healthResponse.json()) as LiveFeedHealth);
      setReviewTrainingLedger((await ledgerResponse.json()) as ReviewTrainingLedger);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Live feed health failed.";
      setLiveFeedHealth({
        status: "error",
        mode: "live_feed_health_and_review_contract",
        feeds: [],
        summary: { required_feed_count: 0, ready_feed_count: 0, missing_or_weak_feed_count: 0, open_review_count: 0 },
        readiness_issues: [message],
      });
    } finally {
      setIsLiveFeedHealthLoading(false);
    }
  }, []);

  const refreshLiveAgentsSmoke = useCallback(async () => {
    try {
      const response = await fetchParkPulseApi("/api/park/live-agents-smoke/latest", { timeoutMs: longRunningRequestTimeoutMs });
      setLiveAgentsSmoke((await response.json()) as LiveAgentsSmokeReport);
    } catch (error) {
      setLiveAgentsSmoke({
        status: "error",
        mode: "live_all_agents_smoke",
        summary: { status: "error", activated_role_count: 0, activated_department_count: 0 },
        readiness_issues: [error instanceof Error ? error.message : "Unable to load live all-agents smoke report."],
      });
    }
  }, []);

  const refreshStaleLiveFeeds = useCallback(async () => {
    setIsRefreshingStaleFeeds(true);
    setErrorMessage(null);
    setStatusMessage("Refreshing stale live feeds without blocking on weather.");
    try {
      const response = await fetchParkPulseApi("/api/park/live-feeds/refresh-stale", {
        method: "POST",
        headers: { "content-type": "application/json", "x-parkpulse-role": "ops_team" },
        body: JSON.stringify({ stale_only: true, refresh_margin_seconds: 20 }),
        timeoutMs: longRunningRequestTimeoutMs,
      });
      const payload = (await response.json()) as LiveFeedRefreshSupervisorResult;
      setLiveFeedRefreshSupervisor(payload);
      const refreshedCount = payload.refreshed_sources?.length ?? 0;
      const queuedCount = payload.queued_sources?.length ?? 0;
      setStatusMessage(`Live feed refresh ${payload.status ?? "complete"}: ${refreshedCount} refreshed / ${queuedCount} queued.`);
      await refreshLiveFeedHealth();
      void refreshActualTraining();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unable to refresh stale live feeds.";
      setErrorMessage(message);
      setLiveFeedRefreshSupervisor({ status: "error", mode: "live_feed_refresh_supervisor", readiness_issues: [message] });
    } finally {
      setIsRefreshingStaleFeeds(false);
    }
  }, [refreshActualTraining, refreshLiveFeedHealth]);

  const recordReviewDecision = useCallback(
    async (caseId: string, decision: "approve_for_state" | "request_corroboration" | "hold_for_review" | "escalate") => {
      setIsLiveFeedHealthLoading(true);
      setErrorMessage(null);
      try {
        await fetchParkPulseApi("/api/park/review-training-ledger", {
          method: "POST",
          headers: { "content-type": "application/json", "x-parkpulse-role": "ops_team" },
          body: JSON.stringify({ case_id: caseId, decision, reviewer: "ops_lead" }),
          timeoutMs: 12000,
        });
        setStatusMessage(`Review case ${decision.replaceAll("_", " ")}.`);
        await refreshLiveFeedHealth();
        void refreshActualTraining();
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : "Unable to record review decision.");
      } finally {
        setIsLiveFeedHealthLoading(false);
      }
    },
    [refreshActualTraining, refreshLiveFeedHealth],
  );

  const loadFeed = useCallback(
    async <T extends LiveWeatherLoadResult>(
      path: string,
      label: string,
      setLoading: (value: boolean) => void,
      setResult: (value: T | null) => void,
    ) => {
      setLoading(true);
      setErrorMessage(null);
      try {
        const response = await fetchParkPulseApi(path, { method: "POST", timeoutMs: longRunningRequestTimeoutMs });
        const payload = (await response.json()) as T;
        setResult(payload);
        setStatusMessage(`${label} feed ${payload.status ?? "loaded"}.`);
        await refreshLiveFeedHealth();
        void park.refreshParkState();
      } catch (error) {
        const message = error instanceof Error ? error.message : `Unable to load ${label} feed.`;
        setErrorMessage(message);
        setResult({ status: "error", mode: `${label.replaceAll(" ", "_")}_feed_load`, readiness_issues: [message] } as T);
      } finally {
        setLoading(false);
      }
    },
    [park, refreshLiveFeedHealth],
  );

  const loadLiveWeatherFeed = useCallback(
    () => loadFeed<LiveWeatherLoadResult>("/api/park/live-feeds/weather/load", "weather", setIsLoadingLiveWeather, setLiveWeatherLoad),
    [loadFeed],
  );
  const loadLiveRideOpsFeed = useCallback(
    () => loadFeed<LiveRideOpsLoadResult>("/api/park/live-feeds/ride-ops/load", "ride ops", setIsLoadingLiveRideOps, setLiveRideOpsLoad),
    [loadFeed],
  );
  const loadLiveGuestFlowFeed = useCallback(
    () => loadFeed<LiveGuestFlowLoadResult>("/api/park/live-feeds/guest-flow/load", "guest flow", setIsLoadingLiveGuestFlow, setLiveGuestFlowLoad),
    [loadFeed],
  );
  const loadLiveStaffingFeed = useCallback(
    () => loadFeed<LiveStaffingLoadResult>("/api/park/live-feeds/staffing/load", "staffing", setIsLoadingLiveStaffing, setLiveStaffingLoad),
    [loadFeed],
  );
  const loadLiveFoodOpsFeed = useCallback(
    () => loadFeed<LiveFoodOpsLoadResult>("/api/park/live-feeds/food-ops/load", "food ops", setIsLoadingLiveFoodOps, setLiveFoodOpsLoad),
    [loadFeed],
  );
  const loadLiveOperatorSignalFeed = useCallback(
    () => loadFeed<LiveOperatorSignalLoadResult>("/api/park/live-feeds/operator-signal/load", "operator signal", setIsLoadingLiveOperatorSignal, setLiveOperatorSignalLoad),
    [loadFeed],
  );

  useEffect(() => {
    let cancelled = false;

    const refreshInitialCommandCenterState = async () => {
      await refreshIntegrationStatus();
      if (cancelled) return;
      await refreshLiveFeedHealth();
      if (cancelled) return;
      void refreshActualTraining();
      window.setTimeout(() => {
        if (!cancelled) void refreshLiveAgentsSmoke();
      }, 500);
    };

    void refreshInitialCommandCenterState();
    return () => {
      cancelled = true;
    };
  }, [refreshActualTraining, refreshIntegrationStatus, refreshLiveAgentsSmoke, refreshLiveFeedHealth]);

  const runAgent = useCallback(async () => {
    setIsRunning(true);
    setErrorMessage(null);
    setStatusMessage("Running feature extraction, prediction, optimization, policy gate, explanation, dispatch draft, and eval receipt.");
    try {
      const activeScenario = park.parkState.guestFlow.activeScenario;
      const response = await fetchParkPulseApi("/api/park/agent-run", {
        method: "POST",
        headers: { "content-type": "application/json", "x-parkpulse-role": "ops_team" },
        body: JSON.stringify({
          scenario_key: activeScenario.key || undefined,
          operation_mode: false,
          auto_unexpected_event: false,
          operator_message: activeScenario.description || activeScenario.name || "Run the current live park operating loop.",
          execute: true,
        }),
        timeoutMs: longRunningRequestTimeoutMs,
      });
      const payload = (await response.json()) as RunPayload;
      const telemetry = normalizeRunTelemetry(payload);
      setRunTelemetry(telemetry);
      setStatusMessage(telemetry.operator_response?.headline ?? "Operating loop complete. Receipt is ready for review.");
      await park.refreshParkState();
      void refreshIntegrationStatus();
      void refreshActualTraining();
      void refreshLiveAgentsSmoke();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Unable to run the ParkPulse agent.");
      setStatusMessage(null);
    } finally {
      setIsRunning(false);
    }
  }, [park, refreshActualTraining, refreshIntegrationStatus, refreshLiveAgentsSmoke]);

  const runDepartmentNegotiationDemo = useCallback(async () => {
    setIsRunning(true);
    setErrorMessage(null);
    setStatusMessage("Running department negotiation demo: Marketing, Ops, Safety, Finance, Executive, Tool Executor.");
    try {
      const response = await fetchParkPulseApi("/api/park/agent-run", {
        method: "POST",
        headers: { "content-type": "application/json", "x-parkpulse-role": "ops_team" },
        body: JSON.stringify({
          scenario_key: "marketing_promo_conflict",
          operation_mode: false,
          auto_unexpected_event: false,
          operator_message: "Marketing wants to push a discount to Zone B indoor food court, but Zone B is already crowded. Preserve revenue by redirecting the offer to Zone C if policy allows.",
          execute: false,
        }),
        timeoutMs: longRunningRequestTimeoutMs,
      });
      const payload = (await response.json()) as RunPayload;
      const telemetry = normalizeRunTelemetry(payload);
      setRunTelemetry(telemetry);
      setStatusMessage("Department negotiation demo complete. Review proposal envelopes and conflict resolution.");
      void refreshIntegrationStatus();
      void refreshActualTraining();
      void refreshLiveAgentsSmoke();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Unable to run the department negotiation demo.");
      setStatusMessage(null);
    } finally {
      setIsRunning(false);
    }
  }, [refreshActualTraining, refreshIntegrationStatus, refreshLiveAgentsSmoke]);

  const runLiveFeedAgent = useCallback(async () => {
    setIsRunning(true);
    setErrorMessage(null);
    setStatusMessage("Running live-feed case: current feed evidence, department proposals, judge checks, and tool-use trace.");
    try {
      const response = await fetchParkPulseApi("/api/park/live-feed-agent-run", {
        method: "POST",
        headers: { "content-type": "application/json", "x-parkpulse-role": "ops_team" },
        body: JSON.stringify({
          refresh_stale: true,
          execute: false,
          min_ready_feeds: 4,
          require_persisted_events: true,
        }),
        timeoutMs: longRunningRequestTimeoutMs,
      });
      const payload = (await response.json()) as RunPayload;
      const telemetry = normalizeRunTelemetry(payload);
      if (telemetry.status === "blocked") {
        setRunTelemetry(telemetry);
        setErrorMessage(telemetry.readiness_issues?.[0] ?? "Live-feed case is blocked until feed evidence is ready.");
        setStatusMessage(null);
        await refreshLiveFeedHealth();
        return;
      }
      setRunTelemetry(telemetry);
      setStatusMessage("Live-feed case complete. Review feed evidence, department reasoning, and tool-use clarity.");
      await park.refreshParkState();
      await refreshLiveFeedHealth();
      void refreshIntegrationStatus();
      void refreshActualTraining();
      void refreshLiveAgentsSmoke();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Unable to run the live-feed agent case.");
      setStatusMessage(null);
    } finally {
      setIsRunning(false);
    }
  }, [park, refreshActualTraining, refreshIntegrationStatus, refreshLiveAgentsSmoke, refreshLiveFeedHealth]);

  const executeSelectedAction = useCallback(async () => {
    setIsDispatching(true);
    setErrorMessage(null);
    if (!selectedAction?.action || !selectedAction.target) {
      setErrorMessage("No runtime-selected action is available. Run the operating loop first.");
      setIsDispatching(false);
      return;
    }
    const action = { target: selectedAction.target, action: selectedAction.action };
    try {
      const response = await fetchParkPulseApi("/api/park/action", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(action),
        timeoutMs: 12000,
      });
      const payload = (await response.json()) as { message?: string; governance?: RunTelemetry["governance"] };
      setRunTelemetry((current) => ({
        ...(current ?? {}),
        governance: payload.governance ?? current?.governance,
      }));
      setStatusMessage(payload.message ?? "Action sent through the policy-gated action path.");
      await park.refreshParkState();
      void refreshActualTraining();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Unable to execute the selected action.");
    } finally {
      setIsDispatching(false);
    }
  }, [park, refreshActualTraining, selectedAction?.action, selectedAction?.target]);

  const acknowledgeDispatch = useCallback(
    async (dispatch: DispatchView, choice: "approved" | "held_for_review" | "acknowledged") => {
      setIsApproving(true);
      setErrorMessage(null);
      try {
        const response = await fetchParkPulseApi("/api/park/delivery/acknowledge", {
          method: "POST",
          headers: { "content-type": "application/json", "x-parkpulse-role": "ops_team" },
          body: JSON.stringify({
            dispatch_id: dispatch.dispatch?.id ?? dispatch.id,
            id: dispatch.dispatch?.id ?? dispatch.id,
            actor: "operator",
            choice,
            channel: dispatch.channel,
          }),
          timeoutMs: 12000,
        });
        const payload = (await response.json()) as { status?: string; state?: unknown; delivery?: RunTelemetry["delivery"] };
        if (payload.state) park.applyParkState(payload.state);
        if (payload.delivery) {
          setRunTelemetry((current) => ({ ...(current ?? {}), delivery: payload.delivery }));
        }
        setStatusMessage(`Receiver ${payload.status ?? choice}.`);
        void refreshActualTraining();
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : "Unable to update receiver acknowledgement.");
      } finally {
        setIsApproving(false);
      }
    },
    [park, refreshActualTraining],
  );

  return {
    ...park,
    runAgent,
    runDepartmentNegotiationDemo,
    runLiveFeedAgent,
    executeSelectedAction,
    acknowledgeDispatch,
    runTelemetry,
    agentBriefs,
    dispatches,
    activeEvalScores,
    integrationStatus,
    actualTraining,
    selectedAction,
    policyGate,
    evalScore,
    memoryMode,
    isRunning,
    isDispatching,
    isApproving,
    isTrainingLoading,
    isStartingGcpTraining,
    isLiveFeedHealthLoading: isLiveFeedHealthLoading || isRefreshingStaleFeeds,
    isLoadingLiveWeather,
    isLoadingLiveRideOps,
    isLoadingLiveGuestFlow,
    isLoadingLiveStaffing,
    isLoadingLiveFoodOps,
    isLoadingLiveOperatorSignal,
    statusMessage,
    errorMessage,
    liveFeedHealth,
    reviewTrainingLedger,
    liveWeatherLoad,
    liveRideOpsLoad,
    liveGuestFlowLoad,
    liveStaffingLoad,
    liveFoodOpsLoad,
    liveOperatorSignalLoad,
    liveFeedRefreshSupervisor,
    liveAgentsSmoke,
    refreshActualTraining,
    refreshLiveAgentsSmoke,
    refreshLiveFeedHealth,
    refreshStaleLiveFeeds,
    recordReviewDecision,
    loadLiveWeatherFeed,
    loadLiveRideOpsFeed,
    loadLiveGuestFlowFeed,
    loadLiveStaffingFeed,
    loadLiveFoodOpsFeed,
    loadLiveOperatorSignalFeed,
  };
}
