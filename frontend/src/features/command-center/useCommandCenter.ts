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

export type RoleId = "customer" | "onsite_worker" | "ops_team" | "ml_ops_admin" | "read_only";

export type RoleAuthStatus = {
  status?: string;
  mode?: string;
  identity?: {
    status?: string;
    authenticated?: boolean;
    auth_method?: string;
    role?: RoleId | string;
    subject?: string;
    issuer?: string;
    expires_at?: number;
    token_status?: string;
    reason?: string;
  };
  dev_issuer_enabled?: boolean;
  trusted_issuer_enabled?: boolean;
  signed_role_required?: boolean;
  boundary?: string;
};

export type RoleUiCapabilities = {
  authenticated: boolean;
  role: RoleId;
  roleLabel: string;
  canManageFeeds: boolean;
  canRunOperatingLoop: boolean;
  canAcknowledgeDispatch: boolean;
  canReviewLabels: boolean;
  canStartTraining: boolean;
  canViewOpsEvidence: boolean;
};

function roleLabel(role: RoleId) {
  return {
    customer: "Customer / Guest",
    onsite_worker: "Onsite Worker",
    ops_team: "Ops Team",
    ml_ops_admin: "ML / Ops Admin",
    read_only: "Read-only",
  }[role];
}

function normalizeRole(value?: string): RoleId {
  if (value === "customer" || value === "onsite_worker" || value === "ops_team" || value === "ml_ops_admin") return value;
  return "read_only";
}

function capabilitiesForAuth(auth: RoleAuthStatus | null): RoleUiCapabilities {
  const authenticated = auth?.identity?.authenticated === true;
  const role = authenticated ? normalizeRole(auth?.identity?.role) : "read_only";
  return {
    authenticated,
    role,
    roleLabel: roleLabel(role),
    canManageFeeds: authenticated && (role === "ops_team" || role === "ml_ops_admin"),
    canRunOperatingLoop: authenticated && role === "ops_team",
    canAcknowledgeDispatch: authenticated && (role === "onsite_worker" || role === "ops_team"),
    canReviewLabels: authenticated && role === "ml_ops_admin",
    canStartTraining: authenticated && role === "ml_ops_admin",
    canViewOpsEvidence: authenticated && (role === "ops_team" || role === "ml_ops_admin"),
  };
}

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

export type ReviewLabelDecision = "approve_label" | "edit_label" | "reject_label" | "needs_more_evidence";

export type ReviewLabelCandidate = {
  id?: string;
  agent_id?: string;
  training_scope?: string;
  source?: string;
  priority?: string;
  input_summary?: string;
  proposed_label?: string;
  label_options?: string[];
  evidence?: Record<string, unknown>;
  recommendation?: {
    proposed_label?: string;
    confidence?: number;
    confidence_status?: string;
    auto_label_eligible?: boolean;
  };
  safety_notes?: string[];
  review_status?: string;
  boundary?: string;
  decision?: {
    decision?: ReviewLabelDecision;
    final_label?: string;
    eligible_for_supervised_training?: boolean;
  };
};

export type ReviewLabelPipeline = {
  status?: string;
  mode?: string;
  summary?: {
    candidate_count?: number;
    open_count?: number;
    decided_count?: number;
    approved_label_count?: number;
    training_candidate_count?: number;
  };
  candidates?: ReviewLabelCandidate[];
  decided?: ReviewLabelCandidate[];
  label_options?: ReviewLabelDecision[];
  auto_label_rule?: {
    enabled?: boolean;
    confidence_threshold?: number;
  };
  training_rule?: string;
  boundary?: string;
  uses_seed_data?: boolean;
  labels_or_reward_changed?: boolean;
  llm_used_for_reward_or_label?: boolean;
  readiness_issues?: string[];
};

export type RoleAccessContracts = {
  status?: string;
  mode?: string;
  principle?: string;
  roles?: Array<{
    id?: string;
    label?: string;
    surface?: string;
    primary_users?: string[];
    can_read?: string[];
    can_do?: string[];
    cannot_read?: string[];
    cannot_do?: string[];
    evidence_products?: string[];
    ui_contract?: string;
    llm_contract?: string;
  }>;
  role_count?: number;
  global_boundaries?: string[];
  route_matrix?: Record<string, string>;
  data_products?: string[];
  uses_seed_data?: boolean;
  loads_bigquery_per_tick?: boolean;
  llm_control_authority?: boolean;
  readiness_issues?: string[];
};

const fallbackRoleAccessContracts: RoleAccessContracts = {
  status: "fallback",
  mode: "role_access_contracts",
  principle: "Rigid authority boundaries with role-specific surfaces.",
  roles: [
    {
      id: "customer",
      label: "Customer / Guest",
      surface: "guest_assistance",
      can_read: ["guest-facing guidance", "route and venue status", "safety notices"],
      can_do: ["ask for help", "view reroute guidance", "submit guest note"],
      cannot_do: ["dispatch worker", "approve action", "set reward or label"],
      llm_contract: "Guest surfaces receive public guidance only, not internal control authority.",
    },
    {
      id: "onsite_worker",
      label: "Onsite Worker",
      surface: "task_execution",
      can_read: ["assigned task", "target zone", "priority"],
      can_do: ["acknowledge task", "mark blocked", "mark done"],
      cannot_do: ["override policy gate", "query BigQuery", "promote model"],
      llm_contract: "Worker surfaces can act on assigned tasks but cannot create or approve live work.",
    },
    {
      id: "ops_team",
      label: "Ops Team",
      surface: "command_center",
      can_read: ["live park state", "candidate actions", "policy gate status"],
      can_do: ["review action", "hold for human review", "acknowledge dispatch receipt"],
      cannot_do: ["bypass policy gate", "set reward or labels from chat", "load BigQuery per tick"],
      llm_contract: "Ops receives evidence, uncertainty, and next checks; policy and eval gates keep control authority bounded.",
    },
    {
      id: "ml_ops_admin",
      label: "ML / Ops Admin",
      surface: "learning_governance",
      can_read: ["training status", "promotion blockers", "BigQuery governed summary"],
      can_do: ["start offline training job", "inspect promotion readiness", "review rollback evidence"],
      cannot_do: ["dispatch live action", "run arbitrary SQL from chat", "promote deteriorating slice"],
      llm_contract: "Learning authority stays governed outside chat and cannot dispatch live park actions.",
    },
  ],
  role_count: 4,
  global_boundaries: [
    "No role can bypass policy gates.",
    "Chat/LLM cannot dispatch, set rewards, write labels, promote models, roll back policies, or run arbitrary BigQuery SQL.",
    "BigQuery is batch/offline evidence; it is not loaded every heartbeat tick.",
  ],
  uses_seed_data: false,
  loads_bigquery_per_tick: false,
  llm_control_authority: false,
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
  const [reviewLabelPipeline, setReviewLabelPipeline] = useState<ReviewLabelPipeline | null>(null);
  const [roleAccess, setRoleAccess] = useState<RoleAccessContracts | null>(null);
  const [roleAuthStatus, setRoleAuthStatus] = useState<RoleAuthStatus | null>(null);
  const [liveWeatherLoad, setLiveWeatherLoad] = useState<LiveWeatherLoadResult | null>(null);
  const [liveRideOpsLoad, setLiveRideOpsLoad] = useState<LiveRideOpsLoadResult | null>(null);
  const [liveGuestFlowLoad, setLiveGuestFlowLoad] = useState<LiveGuestFlowLoadResult | null>(null);
  const [liveStaffingLoad, setLiveStaffingLoad] = useState<LiveStaffingLoadResult | null>(null);
  const [liveFoodOpsLoad, setLiveFoodOpsLoad] = useState<LiveFoodOpsLoadResult | null>(null);
  const [liveOperatorSignalLoad, setLiveOperatorSignalLoad] = useState<LiveOperatorSignalLoadResult | null>(null);
  const [liveFeedRefreshSupervisor, setLiveFeedRefreshSupervisor] = useState<LiveFeedRefreshSupervisorResult | null>(null);
  const [isReviewLabelPipelineLoading, setIsReviewLabelPipelineLoading] = useState(false);
  const [isAutoLabelingReviewLabels, setIsAutoLabelingReviewLabels] = useState(false);
  const [isRoleAccessLoading, setIsRoleAccessLoading] = useState(false);

  const roleCapabilities = useMemo(() => capabilitiesForAuth(roleAuthStatus), [roleAuthStatus]);

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

  const refreshRoleAuthStatus = useCallback(async () => {
    try {
      const response = await fetchParkPulseApi("/api/park/auth/status", { timeoutMs: 8000 });
      setRoleAuthStatus((await response.json()) as RoleAuthStatus);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Role identity status failed.";
      setRoleAuthStatus({
        status: "error",
        mode: "role_identity_status",
        identity: { authenticated: false, role: "read_only", status: "error", reason: message },
        signed_role_required: true,
        trusted_issuer_enabled: false,
      });
    }
  }, []);

  const refreshActualTraining = useCallback(async (options?: { runGcpTraining?: boolean }) => {
    const runGcpTraining = options?.runGcpTraining === true;
    if (runGcpTraining && !roleCapabilities.canStartTraining) {
      setErrorMessage("Signed ML / Ops Admin role is required to start BigQuery ML training.");
      return;
    }
    setIsTrainingLoading(true);
    if (runGcpTraining) {
      setIsStartingGcpTraining(true);
      setErrorMessage(null);
      setStatusMessage("Starting BigQuery ML training from observed outcome rows.");
    }
    try {
      const response = await fetchParkPulseApi(runGcpTraining ? "/api/park/actual-training?runGcpTraining=true" : "/api/park/actual-training", {
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
  }, [roleCapabilities.canStartTraining]);

  const refreshLiveFeedHealth = useCallback(async () => {
    setIsLiveFeedHealthLoading(true);
    try {
      const [healthResponse, ledgerResponse] = await Promise.all([
        fetchParkPulseApi("/api/park/live-feed-health?limit=500", { timeoutMs: 12000 }),
        fetchParkPulseApi("/api/park/review-training-ledger?limit=80", { timeoutMs: 12000 }),
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

  const refreshReviewLabelPipeline = useCallback(async () => {
    setIsReviewLabelPipelineLoading(true);
    try {
      const response = await fetchParkPulseApi("/api/park/review-label-pipeline?limit=40", { timeoutMs: 12000 });
      setReviewLabelPipeline((await response.json()) as ReviewLabelPipeline);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Review label pipeline failed.";
      setReviewLabelPipeline({
        status: "error",
        mode: "review_label_pipeline",
        candidates: [],
        decided: [],
        readiness_issues: [message],
        labels_or_reward_changed: false,
        llm_used_for_reward_or_label: false,
      });
    } finally {
      setIsReviewLabelPipelineLoading(false);
    }
  }, []);

  const refreshRoleAccess = useCallback(async () => {
    setIsRoleAccessLoading(true);
    try {
      const response = await fetchParkPulseApi("/api/park/role-access-contracts", { timeoutMs: 12000 });
      setRoleAccess((await response.json()) as RoleAccessContracts);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Role access contracts failed.";
      setRoleAccess({
        ...fallbackRoleAccessContracts,
        readiness_issues: [message],
      });
    } finally {
      setIsRoleAccessLoading(false);
    }
  }, []);

  const refreshStaleLiveFeeds = useCallback(async () => {
    if (!roleCapabilities.canManageFeeds) {
      setErrorMessage("Signed Ops Team or ML / Ops Admin role is required to refresh live feeds.");
      return;
    }
    setIsRefreshingStaleFeeds(true);
    setErrorMessage(null);
    setStatusMessage("Refreshing stale live feeds without blocking on weather.");
    try {
      const response = await fetchParkPulseApi("/api/park/live-feeds/refresh-stale", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ stale_only: true, refresh_margin_seconds: 20 }),
        timeoutMs: longRunningRequestTimeoutMs,
      });
      const payload = (await response.json()) as LiveFeedRefreshSupervisorResult;
      setLiveFeedRefreshSupervisor(payload);
      const refreshedCount = payload.refreshed_sources?.length ?? 0;
      const queuedCount = payload.queued_sources?.length ?? 0;
      setStatusMessage(`Live feed refresh ${payload.status ?? "complete"}: ${refreshedCount} refreshed / ${queuedCount} queued.`);
      await refreshLiveFeedHealth();
      void refreshReviewLabelPipeline();
      void refreshActualTraining();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unable to refresh stale live feeds.";
      setErrorMessage(message);
      setLiveFeedRefreshSupervisor({ status: "error", mode: "live_feed_refresh_supervisor", readiness_issues: [message] });
    } finally {
      setIsRefreshingStaleFeeds(false);
    }
  }, [refreshActualTraining, refreshLiveFeedHealth, refreshReviewLabelPipeline, roleCapabilities.canManageFeeds]);

  const recordReviewDecision = useCallback(
    async (caseId: string, decision: "approve_for_state" | "request_corroboration" | "hold_for_review" | "escalate") => {
      if (!roleCapabilities.canReviewLabels) {
        setErrorMessage("Signed ML / Ops Admin role is required to record review decisions.");
        return;
      }
      setIsLiveFeedHealthLoading(true);
      setErrorMessage(null);
      try {
        await fetchParkPulseApi("/api/park/review-training-ledger", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ case_id: caseId, decision, reviewer: "ops_lead" }),
          timeoutMs: 12000,
        });
        setStatusMessage(`Review case ${decision.replaceAll("_", " ")}.`);
        await refreshLiveFeedHealth();
        void refreshReviewLabelPipeline();
        void refreshActualTraining();
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : "Unable to record review decision.");
      } finally {
        setIsLiveFeedHealthLoading(false);
      }
    },
    [refreshActualTraining, refreshLiveFeedHealth, refreshReviewLabelPipeline, roleCapabilities.canReviewLabels],
  );

  const recordReviewLabelDecision = useCallback(
    async (candidate: ReviewLabelCandidate, decision: ReviewLabelDecision, finalLabel?: string) => {
      if (!roleCapabilities.canReviewLabels) {
        setErrorMessage("Signed ML / Ops Admin role is required to record review labels.");
        return;
      }
      setIsReviewLabelPipelineLoading(true);
      setErrorMessage(null);
      try {
        const response = await fetchParkPulseApi("/api/park/review-label-pipeline/decision", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            candidate,
            candidate_id: candidate.id,
            decision,
            final_label: finalLabel,
            reviewer: "ops_reviewer",
            reason: "Reviewed from command center.",
          }),
          timeoutMs: 12000,
        });
        const payload = (await response.json()) as { status?: string; readiness_issues?: string[] };
        if (payload.status === "error") {
          setErrorMessage(payload.readiness_issues?.[0] ?? "Unable to record review label decision.");
        } else {
          setStatusMessage(`Review label ${decision.replaceAll("_", " ")}.`);
        }
        await refreshReviewLabelPipeline();
        void refreshActualTraining();
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : "Unable to record review label decision.");
      } finally {
        setIsReviewLabelPipelineLoading(false);
      }
    },
    [refreshActualTraining, refreshReviewLabelPipeline, roleCapabilities.canReviewLabels],
  );

  const autoLabelHighConfidenceReviewLabels = useCallback(async () => {
    if (!roleCapabilities.canReviewLabels) {
      setErrorMessage("Signed ML / Ops Admin role is required to auto-label review candidates.");
      return;
    }
    setIsAutoLabelingReviewLabels(true);
    setErrorMessage(null);
    try {
      const response = await fetchParkPulseApi("/api/park/review-label-pipeline/auto-label", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ reviewer: "parkpulse-command-center", confidence_threshold: 0.7 }),
        timeoutMs: 12000,
      });
      const payload = (await response.json()) as { status?: string; recorded_count?: number; skipped_count?: number; readiness_issues?: string[] };
      if (payload.status === "error") {
        setErrorMessage(payload.readiness_issues?.[0] ?? "Auto-label failed.");
      } else {
        setStatusMessage(`Auto-label ${payload.status ?? "complete"}: ${payload.recorded_count ?? 0} recorded / ${payload.skipped_count ?? 0} skipped.`);
      }
      await refreshReviewLabelPipeline();
      void refreshActualTraining();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Auto-label failed.");
    } finally {
      setIsAutoLabelingReviewLabels(false);
    }
  }, [refreshActualTraining, refreshReviewLabelPipeline, roleCapabilities.canReviewLabels]);

  const loadFeed = useCallback(
    async <T extends LiveWeatherLoadResult>(
      path: string,
      label: string,
      setLoading: (value: boolean) => void,
      setResult: (value: T | null) => void,
    ) => {
      if (!roleCapabilities.canManageFeeds) {
        setErrorMessage(`Signed Ops Team or ML / Ops Admin role is required to load ${label} feed.`);
        return;
      }
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
    [park, refreshLiveFeedHealth, roleCapabilities.canManageFeeds],
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
    void refreshIntegrationStatus();
    void refreshRoleAuthStatus();
    void refreshActualTraining();
    void refreshLiveFeedHealth();
    void refreshReviewLabelPipeline();
    void refreshRoleAccess();
  }, [refreshActualTraining, refreshIntegrationStatus, refreshLiveFeedHealth, refreshReviewLabelPipeline, refreshRoleAccess, refreshRoleAuthStatus]);

  const runAgent = useCallback(async () => {
    if (!roleCapabilities.canRunOperatingLoop) {
      setErrorMessage("Signed Ops Team role is required to run the operating loop.");
      return;
    }
    setIsRunning(true);
    setErrorMessage(null);
    setStatusMessage("Running feature extraction, prediction, optimization, policy gate, explanation, dispatch draft, and eval receipt.");
    try {
      const activeScenario = park.parkState.guestFlow.activeScenario;
      const response = await fetchParkPulseApi("/api/park/agent-run", {
        method: "POST",
        headers: { "content-type": "application/json" },
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
      void refreshReviewLabelPipeline();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Unable to run the ParkPulse agent.");
      setStatusMessage(null);
    } finally {
      setIsRunning(false);
    }
  }, [park, refreshActualTraining, refreshIntegrationStatus, refreshReviewLabelPipeline, roleCapabilities.canRunOperatingLoop]);

  const executeSelectedAction = useCallback(async () => {
    if (!roleCapabilities.canRunOperatingLoop) {
      setErrorMessage("Signed Ops Team role is required to execute selected actions.");
      return;
    }
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
  }, [park, refreshActualTraining, selectedAction?.action, selectedAction?.target, roleCapabilities.canRunOperatingLoop]);

  const acknowledgeDispatch = useCallback(
    async (dispatch: DispatchView, choice: "approved" | "held_for_review" | "acknowledged") => {
      if (!roleCapabilities.canAcknowledgeDispatch) {
        setErrorMessage("Signed Onsite Worker or Ops Team role is required to acknowledge dispatches.");
        return;
      }
      setIsApproving(true);
      setErrorMessage(null);
      try {
        const response = await fetchParkPulseApi("/api/park/delivery/acknowledge", {
          method: "POST",
          headers: { "content-type": "application/json" },
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
    [park, refreshActualTraining, roleCapabilities.canAcknowledgeDispatch],
  );

  return {
    ...park,
    runAgent,
    executeSelectedAction,
    acknowledgeDispatch,
    runTelemetry,
    agentBriefs,
    dispatches,
    activeEvalScores,
    integrationStatus,
    actualTraining,
    reviewLabelPipeline,
    roleAccess,
    roleAuthStatus,
    roleCapabilities,
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
    isReviewLabelPipelineLoading,
    isAutoLabelingReviewLabels,
    isRoleAccessLoading,
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
    refreshActualTraining,
    refreshLiveFeedHealth,
    refreshStaleLiveFeeds,
    recordReviewDecision,
    refreshReviewLabelPipeline,
    recordReviewLabelDecision,
    autoLabelHighConfidenceReviewLabels,
    refreshRoleAccess,
    refreshRoleAuthStatus,
    loadLiveWeatherFeed,
    loadLiveRideOpsFeed,
    loadLiveGuestFlowFeed,
    loadLiveStaffingFeed,
    loadLiveFoodOpsFeed,
    loadLiveOperatorSignalFeed,
  };
}
