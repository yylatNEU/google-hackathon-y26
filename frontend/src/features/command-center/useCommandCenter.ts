"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParkPulseState } from "@/hooks/useParkPulseState";
import { fetchParkPulseApi, longRunningRequestTimeoutMs } from "@/lib/api";
import { agentBriefsFromRuntime } from "@/lib/parkPulseAgents";
import type { AgentBrief, DeliveryDispatch, EvalScore, GcpLiveReadinessStatus, IntegrationStatus, OperatingLoopResilienceStatus, RunTelemetry } from "@/types/platform";

type RunPayload = RunTelemetry & {
  run_telemetry?: RunTelemetry;
  operator_response?: RunTelemetry["operator_response"];
};

function commandCenterIssue(error: unknown, fallback: string) {
  const message = error instanceof Error ? error.message : fallback;
  if (/ParkPulse API did not respond|within the request budget|Checked http/i.test(message)) {
    return "Command Center deferred this live panel while the API finishes a slower refresh. Retry from the panel or run the full loop.";
  }
  return message;
}

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

export type StartupLoadTiming = {
  id: string;
  label: string;
  elapsedMs: number;
  status: "complete" | "deferred";
  completedAtMs: number;
};

type SelectedRuntimeAction = NonNullable<RunTelemetry["planner"]>["selected_action"];

export type AutopilotMode = "off" | "watching" | "executing" | "executed" | "held_for_review" | "blocked";

export type AutopilotDecision = {
  mode: AutopilotMode;
  enabled: boolean;
  action?: SelectedRuntimeAction;
  gate?: string;
  reason: string;
  executedAt?: string;
  executionStatus?: string;
  allowlistMatched?: boolean;
};

export type FeedReliabilityGate = {
  status: "clear" | "degraded" | "blocked";
  score: number;
  trustedForDecision: boolean;
  readyCount: number;
  requiredCount: number;
  weakCount: number;
  staleCount: number;
  lowConfidenceCount: number;
  openReviewCount: number;
  action: "trust" | "refresh" | "hold_for_review";
  reasons: string[];
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
  cache?: { status?: string; ttl_seconds?: number; source?: string };
  summary?: {
    required_feed_count?: number;
    ready_feed_count?: number;
    missing_or_weak_feed_count?: number;
    stale_feed_count?: number;
    low_confidence_feed_count?: number;
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

type ApiRecord = Record<string, unknown>;
type ReviewTrainingRow = NonNullable<ReviewTrainingLedger["rows"]>[number];
type LiveFeedRow = NonNullable<LiveFeedHealth["feeds"]>[number];
const liveFeedHealthSummaryPath = "/api/park/live-feed-health/summary?limit=120";
const liveFeedHealthDeepPath = "/api/park/live-feed-health?limit=500";
const liveFeedReviewLedgerPath = "/api/park/review-training-ledger?limit=80";
const liveFeedSummaryTimeoutMs = 5000;
const liveParkAdvancePollMs = 30000;
const liveParkAdvanceTickMinutes = 5;
const liveLoopAutoStopMs = 15 * 60 * 1000;

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

function isRecord(value: unknown): value is ApiRecord {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function formatApiValue(value: unknown) {
  if (value === undefined || value === null || value === "") return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function normalizedStringArray(value: unknown, field: string, issues: string[]) {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) {
    issues.push(`${field} expected array; received ${typeof value}.`);
    return [];
  }
  return value.map(formatApiValue).filter(Boolean);
}

function normalizedRecordArray<T>(value: unknown, field: string, issues: string[], normalize: (record: ApiRecord, index: number) => T) {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) {
    issues.push(`${field} expected array; received ${typeof value}.`);
    return [];
  }
  return value.flatMap((item, index) => {
    if (!isRecord(item)) {
      issues.push(`${field}[${index}] expected object; received ${typeof item}.`);
      return [];
    }
    return [normalize(item, index)];
  });
}

function normalizedSummary(value: unknown): LiveFeedHealth["summary"] | ReviewTrainingLedger["summary"] | undefined {
  if (!isRecord(value)) return undefined;
  return value as LiveFeedHealth["summary"] & ReviewTrainingLedger["summary"];
}

function normalizeReviewRow(record: ApiRecord, index: number): ReviewTrainingRow {
  const event = isRecord(record.event) ? record.event : undefined;
  const disposition = isRecord(record.disposition) ? record.disposition : undefined;
  return {
    id: formatApiValue(record.id) || `review-${index}`,
    status: formatApiValue(record.status),
    reason: formatApiValue(record.reason),
    priority: formatApiValue(record.priority),
    owner: formatApiValue(record.owner),
    training_effect: formatApiValue(record.training_effect),
    event: event ? { source: formatApiValue(event.source), signal_type: formatApiValue(event.signal_type) } : undefined,
    disposition: disposition ? { decision: formatApiValue(disposition.decision) } : undefined,
  };
}

function normalizeFeedRow(record: ApiRecord, index: number): LiveFeedRow {
  const readinessIssues: string[] = [];
  const rowReadinessIssues = normalizedStringArray(record.readiness_issues, `feeds[${index}].readiness_issues`, readinessIssues);
  return {
    source: formatApiValue(record.source) || `feed-${index}`,
    label: formatApiValue(record.label),
    owner: formatApiValue(record.owner),
    status: formatApiValue(record.status),
    age_seconds: typeof record.age_seconds === "number" || record.age_seconds === null ? record.age_seconds : undefined,
    max_stale_seconds: typeof record.max_stale_seconds === "number" ? record.max_stale_seconds : undefined,
    confidence: typeof record.confidence === "number" ? record.confidence : undefined,
    latest_signal_type: formatApiValue(record.latest_signal_type),
    readiness_issues: [...rowReadinessIssues, ...readinessIssues],
    value: record.value,
  };
}

function normalizeReviewTrainingLedger(payload: unknown): ReviewTrainingLedger {
  const issues: string[] = [];
  if (!isRecord(payload)) {
    return { status: "error", mode: "review_training_ledger", rows: [], open_reviews: [], closed_reviews: [], readiness_issues: ["review ledger response expected object."] };
  }
  const rows = normalizedRecordArray(payload.rows, "review ledger rows", issues, normalizeReviewRow);
  const openReviews = normalizedRecordArray(payload.open_reviews, "review ledger open_reviews", issues, normalizeReviewRow);
  const closedReviews = normalizedRecordArray(payload.closed_reviews, "review ledger closed_reviews", issues, normalizeReviewRow);
  return {
    ...payload,
    status: formatApiValue(payload.status),
    mode: formatApiValue(payload.mode),
    summary: normalizedSummary(payload.summary) as ReviewTrainingLedger["summary"],
    rows,
    open_reviews: openReviews,
    closed_reviews: closedReviews,
    training_rule: formatApiValue(payload.training_rule),
    readiness_issues: [...normalizedStringArray(payload.readiness_issues, "review ledger readiness_issues", issues), ...issues],
  };
}

function normalizeLiveFeedHealth(payload: unknown): LiveFeedHealth {
  const issues: string[] = [];
  if (!isRecord(payload)) {
    return {
      status: "error",
      mode: "live_feed_health_and_review_contract",
      feeds: [],
      open_reviews: [],
      growth_loop: [],
      summary: { required_feed_count: 0, ready_feed_count: 0, missing_or_weak_feed_count: 0, open_review_count: 0 },
      readiness_issues: ["live feed health response expected object."],
    };
  }
  const feeds = normalizedRecordArray(payload.feeds, "live feed health feeds", issues, normalizeFeedRow);
  const openReviews = normalizedRecordArray(payload.open_reviews, "live feed health open_reviews", issues, normalizeReviewRow);
  return {
    ...payload,
    status: formatApiValue(payload.status),
    mode: formatApiValue(payload.mode),
    cache: isRecord(payload.cache) ? (payload.cache as LiveFeedHealth["cache"]) : undefined,
    summary: (normalizedSummary(payload.summary) as LiveFeedHealth["summary"]) ?? { required_feed_count: 0, ready_feed_count: 0, missing_or_weak_feed_count: 0, open_review_count: 0 },
    feeds,
    open_reviews: openReviews,
    growth_loop: normalizedStringArray(payload.growth_loop, "live feed health growth_loop", issues),
    readiness_issues: [...normalizedStringArray(payload.readiness_issues, "live feed health readiness_issues", issues), ...issues],
  };
}

function normalizeLiveFeedRefreshSupervisor(payload: unknown): LiveFeedRefreshSupervisorResult {
  const issues: string[] = [];
  if (!isRecord(payload)) {
    return { status: "error", mode: "live_feed_refresh_supervisor", refreshed_sources: [], queued_sources: [], readiness_issues: ["refresh supervisor response expected object."] };
  }
  return {
    ...payload,
    status: formatApiValue(payload.status),
    mode: formatApiValue(payload.mode),
    refreshed_sources: normalizedStringArray(payload.refreshed_sources, "refresh supervisor refreshed_sources", issues),
    queued_sources: normalizedStringArray(payload.queued_sources, "refresh supervisor queued_sources", issues),
    readiness_issues: [...normalizedStringArray(payload.readiness_issues, "refresh supervisor readiness_issues", issues), ...issues],
    remaining_issues: normalizedStringArray(payload.remaining_issues, "refresh supervisor remaining_issues", issues),
    before: normalizedSummary(payload.before) as LiveFeedHealth["summary"],
    after: normalizedSummary(payload.after) as LiveFeedHealth["summary"],
    after_feeds: normalizedRecordArray(payload.after_feeds, "refresh supervisor after_feeds", issues, normalizeFeedRow),
  };
}

export function assessLiveFeedReliability(health: LiveFeedHealth | null): FeedReliabilityGate {
  if (!health) {
    return {
      status: "degraded",
      score: 0,
      trustedForDecision: false,
      readyCount: 0,
      requiredCount: 0,
      weakCount: 0,
      staleCount: 0,
      lowConfidenceCount: 0,
      openReviewCount: 0,
      action: "refresh",
      reasons: ["Refreshing live-feed evidence summary before decision gating."],
    };
  }
  const feeds = health?.feeds ?? [];
  const summary = health?.summary;
  const requiredCount = summary?.required_feed_count ?? feeds.length;
  const readyCount = summary?.ready_feed_count ?? feeds.filter((feed) => /ready|ok|healthy|fresh/i.test(String(feed.status ?? ""))).length;
  const weakCount =
    summary?.missing_or_weak_feed_count ??
    feeds.filter((feed) => /missing|weak|stale|error|review/i.test(String(feed.status ?? "")) || (feed.readiness_issues?.length ?? 0) > 0).length;
  const staleFeeds = feeds.filter((feed) => typeof feed.age_seconds === "number" && typeof feed.max_stale_seconds === "number" && feed.max_stale_seconds > 0 && feed.age_seconds > feed.max_stale_seconds);
  const lowConfidenceFeeds = feeds.filter((feed) => typeof feed.confidence === "number" && feed.confidence < 0.6);
  const staleCount = summary?.stale_feed_count ?? staleFeeds.length;
  const lowConfidenceCount = summary?.low_confidence_feed_count ?? lowConfidenceFeeds.length;
  const openReviewCount = summary?.open_review_count ?? health?.open_reviews?.length ?? 0;
  const coverage = requiredCount > 0 ? readyCount / requiredCount : 0;
  const penalty = weakCount * 12 + staleCount * 14 + lowConfidenceCount * 8 + Math.min(openReviewCount, 4) * 3;
  const score = Math.max(0, Math.min(100, Math.round(coverage * 100 - penalty)));
  const reasons: string[] = [];
  const isSummaryOnly = /summary/i.test(String(health.mode ?? "")) || /summary/i.test(String(health.cache?.source ?? ""));
  const isRefreshingSummary = /refreshing/i.test(String(health.status ?? health.mode ?? ""));

  if (isRefreshingSummary) reasons.push("Refreshing live-feed evidence summary before decision gating.");
  if (requiredCount > 0 && readyCount < Math.min(4, requiredCount)) reasons.push(`${readyCount}/${requiredCount} required feeds are ready.`);
  if (weakCount > 0) reasons.push(`${weakCount} feeds are missing, weak, stale, or in review.`);
  if (staleCount > 0) reasons.push(`${staleCount} feeds exceed their stale-age budget.`);
  if (lowConfidenceCount > 0) reasons.push(`${lowConfidenceCount} feeds are below 60% confidence.`);
  if (openReviewCount > 0) reasons.push(`${openReviewCount} feed review cases are open.`);
  if (!reasons.length && isSummaryOnly) reasons.push("Fast live-feed summary is clear; deep evidence rows are refreshing in the background.");
  if (!reasons.length) reasons.push("Required live feeds are fresh enough for bounded decisions.");

  const blocked = !isRefreshingSummary && (readyCount < Math.min(3, Math.max(requiredCount, 1)) || score < 45 || staleCount >= 3);
  const degraded = !blocked && (isRefreshingSummary || weakCount > 0 || staleCount > 0 || lowConfidenceCount > 0 || score < 75);
  return {
    status: blocked ? "blocked" : degraded ? "degraded" : "clear",
    score,
    trustedForDecision: !blocked && !isRefreshingSummary,
    readyCount,
    requiredCount,
    weakCount,
    staleCount,
    lowConfidenceCount,
    openReviewCount,
    action: blocked ? "hold_for_review" : degraded ? "refresh" : "trust",
    reasons,
  };
}

function isFeedReliabilityHardHold(reliability: FeedReliabilityGate) {
  return reliability.status === "blocked";
}

function degradedFeedPlanningReason(reliability: FeedReliabilityGate) {
  return `Live-feed reliability is ${reliability.status} (${reliability.score}/100). Continuing with bounded planning while stale or weak feeds refresh; weather-sensitive execution remains policy-gated. ${reliability.reasons[0]}`;
}

function normalizeRunTelemetry(payload: RunPayload): RunTelemetry {
  if (!payload.run_telemetry) return payload;
  const { run_telemetry: runTelemetry, ...topLevelTelemetry } = payload;
  return { ...topLevelTelemetry, ...runTelemetry };
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

function dispatchIdentity(dispatch: DeliveryDispatch | DispatchView, fallbackId?: string) {
  if ("dispatch" in dispatch && dispatch.dispatch) return dispatch.dispatch.id ?? dispatch.id ?? fallbackId;
  return dispatch.id ?? fallbackId;
}

function withDispatchAcknowledgement(
  dispatch: DeliveryDispatch,
  selectedId: string,
  channel: string,
  choice: "approved" | "held_for_review" | "acknowledged",
  serverDispatch?: DeliveryDispatch,
): DeliveryDispatch {
  const dispatchId = dispatchIdentity(dispatch);
  if (dispatchId !== selectedId) return dispatch;
  const baseDispatch = serverDispatch ? { ...dispatch, ...serverDispatch } : dispatch;
  const acknowledgedAt = new Date().toISOString();
  return {
    ...baseDispatch,
    status: choice,
    approvalDecision:
      choice === "acknowledged"
        ? baseDispatch.approvalDecision
        : {
            ...baseDispatch.approvalDecision,
            approved: choice === "approved",
            held_for_review: choice === "held_for_review",
            decision: choice,
            actor: "operator",
            channel,
            decidedAt: acknowledgedAt,
          },
    lastAcknowledgement: {
      ...baseDispatch.lastAcknowledgement,
      actor: "operator",
      choice,
      channel,
      at: acknowledgedAt,
      acknowledgedAt,
    },
  };
}

const autopilotAllowlist: Array<{ target: string; actions: string[] }> = [
  { target: "food", actions: ["redirect_food_demand", "adjust_food_capacity", "update_food_pickup_estimates"] },
  { target: "guest_flow", actions: ["reroute_guests", "redirect_guest_flow", "update_guest_routing"] },
  { target: "signage", actions: ["update_signage", "post_wayfinding_update"] },
  { target: "staff", actions: ["notify_staff"] },
];
const autopilotLoopIntervalMs = 60_000;
const liveFeedAutoRecoveryCooldownMs = 60_000;

function normalizeActionKey(value?: string) {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replaceAll("-", "_")
    .replaceAll(" ", "_");
}

function isAutopilotAllowed(action?: SelectedRuntimeAction) {
  const target = normalizeActionKey(action?.target);
  const actionName = normalizeActionKey(action?.action);
  if (!target || !actionName) return false;
  return autopilotAllowlist.some((rule) => rule.target === target && rule.actions.includes(actionName));
}

function isHardBlockedGate(gate?: string) {
  return /block|unsafe|violation|deny/i.test(String(gate ?? ""));
}

function normalizedConfidenceScore(value?: number) {
  if (typeof value !== "number" || Number.isNaN(value)) return undefined;
  return value > 1 ? value / 100 : value;
}

function autopilotActionLabel(action?: SelectedRuntimeAction) {
  return action?.label ?? ([action?.target, action?.action].filter(Boolean).join(" / ") || "No selected action");
}

export function useCommandCenter(options?: { loadProofData?: boolean }) {
  const loadProofData = options?.loadProofData === true;
  const [isLiveLoopRunning, setIsLiveLoopRunning] = useState(false);
  const park = useParkPulseState({ advanceLivePark: isLiveLoopRunning, tickMinutes: liveParkAdvanceTickMinutes, pollMs: liveParkAdvancePollMs, autoPoll: isLiveLoopRunning });
  const [runTelemetry, setRunTelemetry] = useState<RunTelemetry | null>(null);
  const [integrationStatus, setIntegrationStatus] = useState<IntegrationStatus | null>(null);
  const [gcpLiveReadiness, setGcpLiveReadiness] = useState<GcpLiveReadinessStatus | null>(null);
  const [operatingLoopResilience, setOperatingLoopResilience] = useState<OperatingLoopResilienceStatus | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [isDispatching, setIsDispatching] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [isTrainingLoading, setIsTrainingLoading] = useState(false);
  const [isStartingGcpTraining, setIsStartingGcpTraining] = useState(false);
  const [isLiveFeedHealthLoading, setIsLiveFeedHealthLoading] = useState(false);
  const [isRefreshingStaleFeeds, setIsRefreshingStaleFeeds] = useState(false);
  const [isAutoRecoveringLiveFeeds, setIsAutoRecoveringLiveFeeds] = useState(false);
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
  const [reviewLabelPipeline, setReviewLabelPipeline] = useState<ReviewLabelPipeline | null>(null);
  const [roleAccess, setRoleAccess] = useState<RoleAccessContracts | null>(null);
  const [isReviewLabelPipelineLoading, setIsReviewLabelPipelineLoading] = useState(false);
  const [isAutoLabelingReviewLabels, setIsAutoLabelingReviewLabels] = useState(false);
  const [isRoleAccessLoading, setIsRoleAccessLoading] = useState(false);
  const [startupLoadTimings, setStartupLoadTimings] = useState<StartupLoadTiming[]>([]);
  const [isAutopilotEnabled, setIsAutopilotEnabled] = useState(false);
  const [isAutopilotRunning, setIsAutopilotRunning] = useState(false);
  const [autopilotNextRunAt, setAutopilotNextRunAt] = useState<string | null>(null);
  const autopilotCycleInFlightRef = useRef(false);
  const runAutopilotCycleRef = useRef<(options?: { injectUnexpectedEvent?: boolean }) => Promise<void>>(async () => undefined);
  const lastLiveFeedAutoRecoveryAtRef = useRef(0);
  const [autopilotDecision, setAutopilotDecision] = useState<AutopilotDecision>({
    mode: "off",
    enabled: false,
    reason: "Autopilot is off.",
  });

  const startLiveLoop = useCallback(() => {
    setIsLiveLoopRunning(true);
    setStatusMessage("Live loop started. Park state will advance every 30 seconds.");
  }, []);

  const stopLiveLoop = useCallback(() => {
    setIsLiveLoopRunning(false);
    setStatusMessage("Live loop stopped. Command Center is in snapshot mode.");
  }, []);

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

  const feedReliabilityGate = useMemo(() => assessLiveFeedReliability(liveFeedHealth), [liveFeedHealth]);
  const selectedAction = runTelemetry?.planner?.selected_action;
  const policyGate = runTelemetry?.governance?.gate_status;
  const evalScore = runTelemetry?.eval?.scorecard?.overall;
  const memoryMode = runTelemetry?.memory?.mode ?? integrationStatus?.mongo?.mode ?? "unavailable";
  const canManageFeeds = true;
  const canReviewCases = true;
  const canReviewLabels = true;
  const canStartTraining = true;
  const canExecute = true;
  const canAcknowledge = true;

  const refreshIntegrationStatus = useCallback(async () => {
    try {
      const response = await fetchParkPulseApi("/api/park/integration-status", { timeoutMs: 5000 });
      setIntegrationStatus((await response.json()) as IntegrationStatus);
    } catch {
      setIntegrationStatus(null);
    }
  }, []);

  const refreshGcpLiveReadiness = useCallback(async () => {
    try {
      const response = await fetchParkPulseApi("/api/gcp/live-readiness", { timeoutMs: 5000 });
      setGcpLiveReadiness((await response.json()) as GcpLiveReadinessStatus);
    } catch {
      setGcpLiveReadiness(null);
    }
  }, []);

  const refreshOperatingLoopResilience = useCallback(async () => {
    try {
      const response = await fetchParkPulseApi("/api/gcp/operating-loop-resilience", { timeoutMs: longRunningRequestTimeoutMs });
      setOperatingLoopResilience((await response.json()) as OperatingLoopResilienceStatus);
    } catch {
      setOperatingLoopResilience(null);
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
        timeoutMs: Math.max(longRunningRequestTimeoutMs, 180_000),
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
      void refreshOperatingLoopResilience();
    }
  }, [refreshOperatingLoopResilience]);

  const loadLiveFeedReliabilitySummary = useCallback(async () => {
    const response = await fetchParkPulseApi(liveFeedHealthSummaryPath, { headers: { "x-parkpulse-role": "ops_team" }, timeoutMs: liveFeedSummaryTimeoutMs });
    const health = normalizeLiveFeedHealth(await response.json());
    setLiveFeedHealth(health);
    return assessLiveFeedReliability(health);
  }, []);

  const refreshDeepLiveFeedEvidence = useCallback(async () => {
    try {
      const [healthResponse, ledgerResponse] = await Promise.all([
        fetchParkPulseApi(liveFeedHealthDeepPath, { headers: { "x-parkpulse-role": "ops_team" }, timeoutMs: longRunningRequestTimeoutMs }),
        fetchParkPulseApi(liveFeedReviewLedgerPath, { headers: { "x-parkpulse-role": "ops_team" }, timeoutMs: longRunningRequestTimeoutMs }),
      ]);
      setLiveFeedHealth(normalizeLiveFeedHealth(await healthResponse.json()));
      setReviewTrainingLedger(normalizeReviewTrainingLedger(await ledgerResponse.json()));
    } catch (error) {
      const message = error instanceof Error ? error.message : "Live feed health failed.";
      setLiveFeedHealth((current) =>
        current
          ? { ...current, readiness_issues: [...(current.readiness_issues ?? []), `Deep live-feed evidence refresh deferred: ${message}`] }
          : {
              status: "refreshing",
              mode: "live_feed_health_summary_refreshing",
              feeds: [],
              summary: { required_feed_count: 0, ready_feed_count: 0, missing_or_weak_feed_count: 0, stale_feed_count: 0, low_confidence_feed_count: 0, open_review_count: 0 },
              readiness_issues: [`Deep live-feed evidence refresh deferred: ${message}`],
            },
      );
    }
  }, []);

  const refreshLiveFeedHealth = useCallback(async () => {
    setIsLiveFeedHealthLoading(true);
    try {
      await loadLiveFeedReliabilitySummary();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Live feed health summary failed.";
      setLiveFeedHealth({
        status: "refreshing",
        mode: "live_feed_health_summary_refreshing",
        feeds: [],
        summary: { required_feed_count: 0, ready_feed_count: 0, missing_or_weak_feed_count: 0, stale_feed_count: 0, low_confidence_feed_count: 0, open_review_count: 0 },
        readiness_issues: [`Refreshing evidence summary: ${message}`],
      });
    } finally {
      setIsLiveFeedHealthLoading(false);
    }
  }, [loadLiveFeedReliabilitySummary]);

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

  const refreshReviewLabelPipeline = useCallback(async () => {
    setIsReviewLabelPipelineLoading(true);
    try {
      const response = await fetchParkPulseApi("/api/park/review-label-pipeline?limit=40", { headers: { "x-parkpulse-role": "ml_ops_admin" }, timeoutMs: 12000 });
      setReviewLabelPipeline((await response.json()) as ReviewLabelPipeline);
    } catch (error) {
      const message = commandCenterIssue(error, "Review label pipeline failed.");
      setReviewLabelPipeline({
        status: "deferred",
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
        status: "error",
        mode: "role_access_contracts",
        roles: [],
        readiness_issues: [message],
      });
    } finally {
      setIsRoleAccessLoading(false);
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
        timeoutMs: Math.max(longRunningRequestTimeoutMs, 180_000),
      });
      const payload = normalizeLiveFeedRefreshSupervisor(await response.json());
      setLiveFeedRefreshSupervisor(payload);
      const refreshedCount = payload.refreshed_sources?.length ?? 0;
      const queuedCount = payload.queued_sources?.length ?? 0;
      setStatusMessage(`Live feed refresh ${payload.status ?? "complete"}: ${refreshedCount} refreshed / ${queuedCount} queued.`);
      await refreshLiveFeedHealth();
      if (loadProofData) {
        void refreshReviewLabelPipeline();
        void refreshActualTraining();
        void refreshOperatingLoopResilience();
      }
    } catch (error) {
      const message = commandCenterIssue(error, "Unable to refresh stale live feeds.");
      setStatusMessage(message);
      setLiveFeedRefreshSupervisor({ status: "deferred", mode: "live_feed_refresh_supervisor", readiness_issues: [message] });
    } finally {
      setIsRefreshingStaleFeeds(false);
    }
  }, [loadProofData, refreshActualTraining, refreshLiveFeedHealth, refreshOperatingLoopResilience, refreshReviewLabelPipeline]);

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
        if (loadProofData) {
          void refreshReviewLabelPipeline();
          void refreshActualTraining();
          void refreshOperatingLoopResilience();
        }
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : "Unable to record review decision.");
      } finally {
        setIsLiveFeedHealthLoading(false);
      }
    },
    [loadProofData, refreshActualTraining, refreshLiveFeedHealth, refreshOperatingLoopResilience, refreshReviewLabelPipeline],
  );

  const recordReviewLabelDecision = useCallback(
    async (candidate: ReviewLabelCandidate, decision: ReviewLabelDecision, finalLabel?: string) => {
      setIsReviewLabelPipelineLoading(true);
      setErrorMessage(null);
      try {
        const response = await fetchParkPulseApi("/api/park/review-label-pipeline/decision", {
          method: "POST",
          headers: { "content-type": "application/json", "x-parkpulse-role": "ml_ops_admin" },
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
        void refreshOperatingLoopResilience();
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : "Unable to record review label decision.");
      } finally {
        setIsReviewLabelPipelineLoading(false);
      }
    },
    [refreshActualTraining, refreshOperatingLoopResilience, refreshReviewLabelPipeline],
  );

  const autoLabelHighConfidenceReviewLabels = useCallback(async () => {
    setIsAutoLabelingReviewLabels(true);
    setErrorMessage(null);
    try {
      const response = await fetchParkPulseApi("/api/park/review-label-pipeline/auto-label", {
        method: "POST",
        headers: { "content-type": "application/json", "x-parkpulse-role": "ml_ops_admin" },
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
      void refreshOperatingLoopResilience();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Auto-label failed.");
    } finally {
      setIsAutoLabelingReviewLabels(false);
    }
  }, [refreshActualTraining, refreshOperatingLoopResilience, refreshReviewLabelPipeline]);

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
        void refreshOperatingLoopResilience();
      } catch (error) {
        const message = error instanceof Error ? error.message : `Unable to load ${label} feed.`;
        setErrorMessage(message);
        setResult({ status: "error", mode: `${label.replaceAll(" ", "_")}_feed_load`, readiness_issues: [message] } as T);
      } finally {
        setLoading(false);
      }
    },
    [park, refreshLiveFeedHealth, refreshOperatingLoopResilience],
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

  const autoRecoverLiveFeeds = useCallback(async (reason: string) => {
    const now = Date.now();
    if (isAutoRecoveringLiveFeeds || now - lastLiveFeedAutoRecoveryAtRef.current < liveFeedAutoRecoveryCooldownMs) return;
    lastLiveFeedAutoRecoveryAtRef.current = now;
    setIsAutoRecoveringLiveFeeds(true);
    setErrorMessage(null);
    setStatusMessage(`Auto-refreshing operation data feeds: ${reason}`);

    const loadSource = async <T extends LiveWeatherLoadResult>(
      path: string,
      setResult: (value: T | null) => void,
    ) => {
      const response = await fetchParkPulseApi(path, {
        method: "POST",
        headers: { "content-type": "application/json", "x-parkpulse-role": "ops_team" },
        timeoutMs: longRunningRequestTimeoutMs,
      });
      const payload = (await response.json()) as T;
      setResult(payload);
      return payload;
    };

    try {
      const results = await Promise.allSettled([
        loadSource<LiveWeatherLoadResult>("/api/park/live-feeds/weather/load", setLiveWeatherLoad),
        loadSource<LiveRideOpsLoadResult>("/api/park/live-feeds/ride-ops/load", setLiveRideOpsLoad),
        loadSource<LiveGuestFlowLoadResult>("/api/park/live-feeds/guest-flow/load", setLiveGuestFlowLoad),
        loadSource<LiveStaffingLoadResult>("/api/park/live-feeds/staffing/load", setLiveStaffingLoad),
        loadSource<LiveFoodOpsLoadResult>("/api/park/live-feeds/food-ops/load", setLiveFoodOpsLoad),
        loadSource<LiveOperatorSignalLoadResult>("/api/park/live-feeds/operator-signal/load", setLiveOperatorSignalLoad),
      ]);
      const loaded = results.filter((result) => result.status === "fulfilled").length;
      const failed = results.length - loaded;
      setStatusMessage(`Operation data auto-refresh complete: ${loaded} loaded / ${failed} failed.`);
      await refreshLiveFeedHealth();
      if (loadProofData) {
        void refreshReviewLabelPipeline();
        void refreshOperatingLoopResilience();
      }
    } catch (error) {
      const message = commandCenterIssue(error, "Operation data auto-refresh failed.");
      setStatusMessage(message);
      setLiveFeedRefreshSupervisor({ status: "deferred", mode: "live_feed_refresh_supervisor", readiness_issues: [message] });
    } finally {
      setIsAutoRecoveringLiveFeeds(false);
    }
  }, [isAutoRecoveringLiveFeeds, loadProofData, refreshLiveFeedHealth, refreshOperatingLoopResilience, refreshReviewLabelPipeline]);

  useEffect(() => {
    let cancelled = false;
    let smokeTimeoutId: number | undefined;
    let trainingTimeoutId: number | undefined;
    const startedAt = Date.now();

    const timeInitialLoad = async (id: string, label: string, load: () => Promise<void>) => {
      const requestStartedAt = Date.now();
      let status: StartupLoadTiming["status"] = "complete";
      try {
        await load();
      } catch {
        status = "deferred";
      } finally {
        if (!cancelled) {
          const timing: StartupLoadTiming = {
            id,
            label,
            elapsedMs: Date.now() - requestStartedAt,
            status,
            completedAtMs: Date.now() - startedAt,
          };
          setStartupLoadTimings((current) => [...current.filter((item) => item.id !== id), timing].sort((left, right) => left.completedAtMs - right.completedAtMs));
        }
      }
    };

    const refreshInitialCommandCenterState = async () => {
      setStartupLoadTimings([]);
      const initialLoads = [timeInitialLoad("live_feeds", "Live feeds", refreshLiveFeedHealth)];

      if (loadProofData) {
        initialLoads.push(
          timeInitialLoad("integration", "Integration", refreshIntegrationStatus),
          timeInitialLoad("gcp_readiness", "GCP readiness", refreshGcpLiveReadiness),
          timeInitialLoad("loop_resilience", "Loop health", refreshOperatingLoopResilience),
          timeInitialLoad("review_labels", "Review labels", refreshReviewLabelPipeline),
          timeInitialLoad("role_access", "Role access", refreshRoleAccess),
        );

        trainingTimeoutId = window.setTimeout(() => {
          if (!cancelled) void timeInitialLoad("actual_training", "Outcome learning", refreshActualTraining);
        }, 250);
        smokeTimeoutId = window.setTimeout(() => {
          if (!cancelled) void timeInitialLoad("agent_smoke", "Agent proof", refreshLiveAgentsSmoke);
        }, 500);
      }

      await Promise.allSettled(initialLoads);
    };

    void refreshInitialCommandCenterState();
    return () => {
      cancelled = true;
      if (trainingTimeoutId !== undefined) window.clearTimeout(trainingTimeoutId);
      if (smokeTimeoutId !== undefined) window.clearTimeout(smokeTimeoutId);
    };
  }, [loadProofData, refreshActualTraining, refreshGcpLiveReadiness, refreshIntegrationStatus, refreshLiveAgentsSmoke, refreshLiveFeedHealth, refreshOperatingLoopResilience, refreshReviewLabelPipeline, refreshRoleAccess]);

  useEffect(() => {
    if (!liveFeedHealth) return;
    if (!loadProofData && !isAutopilotEnabled) return;
    if (feedReliabilityGate.status === "clear") return;
    if (isRefreshingStaleFeeds || isLiveFeedHealthLoading) return;
    void autoRecoverLiveFeeds(`${feedReliabilityGate.status} feed gate (${feedReliabilityGate.score}/100)`);
  }, [autoRecoverLiveFeeds, feedReliabilityGate.score, feedReliabilityGate.status, isAutopilotEnabled, isLiveFeedHealthLoading, isRefreshingStaleFeeds, liveFeedHealth, loadProofData]);

  const runAgent = useCallback(async (options?: { injectUnexpectedEvent?: boolean }) => {
    const injectUnexpectedEvent = options?.injectUnexpectedEvent === true;
    setIsRunning(true);
    setErrorMessage(null);
    setStatusMessage(
      injectUnexpectedEvent
        ? "Injecting a live park incident, then running feature extraction, prediction, policy gate, dispatch draft, and eval receipt."
        : "Running feature extraction, prediction, optimization, policy gate, explanation, dispatch draft, and eval receipt.",
    );
    try {
      const loadFeedReliabilityPreflight = async () => {
        return loadLiveFeedReliabilitySummary();
      };

      let reliability = await loadFeedReliabilityPreflight();
      if (isFeedReliabilityHardHold(reliability)) {
        setAutopilotDecision({
          mode: "watching",
          enabled: true,
          gate: reliability.status,
          reason: `Live-feed reliability is ${reliability.status}. Refreshing stale evidence before planner execution.`,
        });
        const refreshResponse = await fetchParkPulseApi("/api/park/live-feeds/refresh-stale", {
          method: "POST",
          headers: { "content-type": "application/json", "x-parkpulse-role": "ops_team" },
          body: JSON.stringify({ stale_only: true, refresh_margin_seconds: 20 }),
          timeoutMs: Math.max(longRunningRequestTimeoutMs, 180_000),
        });
        setLiveFeedRefreshSupervisor(normalizeLiveFeedRefreshSupervisor(await refreshResponse.json()));
        reliability = await loadFeedReliabilityPreflight();
      }

      if (isFeedReliabilityHardHold(reliability)) {
        setAutopilotDecision({
          mode: "held_for_review",
          enabled: true,
          gate: reliability.status,
          reason: `Autopilot held: feed reliability must be clear before execution. Current score ${reliability.score}/100. ${reliability.reasons[0]}`,
        });
        setStatusMessage("Autopilot held because live-feed evidence is too fragile for downstream decisions.");
        return;
      }

      if (reliability.status === "degraded") {
        setAutopilotDecision({
          mode: "watching",
          enabled: true,
          gate: reliability.status,
          reason: degradedFeedPlanningReason(reliability),
        });
        setStatusMessage("Running the ops loop with degraded feed evidence; stale weather stays visible and weather-sensitive actions remain review-gated.");
      }

      const activeScenario = park.parkState.guestFlow.activeScenario;
      const response = await fetchParkPulseApi("/api/park/agent-run", {
        method: "POST",
        headers: { "content-type": "application/json", "x-parkpulse-role": "ops_team" },
        body: JSON.stringify({
          scenario_key: activeScenario.key || undefined,
          operation_mode: false,
          auto_unexpected_event: injectUnexpectedEvent,
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
      if (loadProofData) {
        void refreshIntegrationStatus();
        void refreshGcpLiveReadiness();
        void refreshOperatingLoopResilience();
        void refreshActualTraining();
        void refreshLiveAgentsSmoke();
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Unable to run the ParkPulse agent.");
      setStatusMessage(null);
    } finally {
      setIsRunning(false);
    }
  }, [loadLiveFeedReliabilitySummary, loadProofData, park, refreshActualTraining, refreshGcpLiveReadiness, refreshIntegrationStatus, refreshLiveAgentsSmoke, refreshOperatingLoopResilience]);

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
      if (loadProofData) {
        void refreshIntegrationStatus();
        void refreshGcpLiveReadiness();
        void refreshOperatingLoopResilience();
        void refreshActualTraining();
        void refreshLiveAgentsSmoke();
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Unable to run the department negotiation demo.");
      setStatusMessage(null);
    } finally {
      setIsRunning(false);
    }
  }, [loadProofData, refreshActualTraining, refreshGcpLiveReadiness, refreshIntegrationStatus, refreshLiveAgentsSmoke, refreshOperatingLoopResilience]);

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
          controlled_executor_execute: true,
          allow_risk_escalation: true,
          measure_post_action: true,
          min_ready_feeds: 4,
          require_persisted_events: true,
        }),
        timeoutMs: Math.max(longRunningRequestTimeoutMs, 180_000),
      });
      const payload = (await response.json()) as RunPayload;
      const telemetry = normalizeRunTelemetry(payload);
      if (telemetry.status === "blocked") {
        setRunTelemetry(telemetry);
        setErrorMessage(telemetry.readiness_issues?.[0] ?? "Live-feed case is blocked until feed evidence is ready.");
        setStatusMessage(null);
        await refreshLiveFeedHealth();
        if (loadProofData) void refreshOperatingLoopResilience();
        return;
      }
      setRunTelemetry(telemetry);
      setStatusMessage("Live-feed case complete. Review feed evidence, department reasoning, and tool-use clarity.");
      await park.refreshParkState();
      await refreshLiveFeedHealth();
      if (loadProofData) {
        void refreshIntegrationStatus();
        void refreshGcpLiveReadiness();
        void refreshOperatingLoopResilience();
        void refreshActualTraining();
        void refreshLiveAgentsSmoke();
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Unable to run the live-feed agent case.");
      setStatusMessage(null);
    } finally {
      setIsRunning(false);
    }
  }, [loadProofData, park, refreshActualTraining, refreshGcpLiveReadiness, refreshIntegrationStatus, refreshLiveAgentsSmoke, refreshLiveFeedHealth, refreshOperatingLoopResilience]);

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
        headers: { "content-type": "application/json", "x-parkpulse-role": "ops_team" },
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
      if (loadProofData) {
        void refreshActualTraining();
        void refreshOperatingLoopResilience();
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Unable to execute the selected action.");
    } finally {
      setIsDispatching(false);
    }
  }, [loadProofData, park, refreshActualTraining, refreshOperatingLoopResilience, selectedAction?.action, selectedAction?.target]);

  const setAutopilotEnabled = useCallback((enabled: boolean) => {
    setIsAutopilotEnabled(enabled);
    setAutopilotDecision((current) => ({
      ...current,
      enabled,
      mode: enabled ? "watching" : "off",
      reason: enabled ? "Autopilot is armed for allowlisted, policy-gated actions only." : "Autopilot is off.",
    }));
    setStatusMessage(enabled ? "Autopilot armed for low-risk policy-gated actions." : "Autopilot turned off.");
  }, []);

  const runAutopilotCycle = useCallback(async (options?: { injectUnexpectedEvent?: boolean }) => {
    if (autopilotCycleInFlightRef.current) return;
    const injectUnexpectedEvent = options?.injectUnexpectedEvent === true;
    if (!isAutopilotEnabled && !injectUnexpectedEvent) {
      setAutopilotDecision({
        mode: "off",
        enabled: false,
        reason: "Turn on autopilot before running an automated tick.",
      });
      setStatusMessage("Autopilot is off. Turn it on before running a tick.");
      return;
    }
    if (injectUnexpectedEvent && !isAutopilotEnabled) {
      setIsAutopilotEnabled(true);
    }

    autopilotCycleInFlightRef.current = true;
    setIsAutopilotRunning(true);
    setIsRunning(true);
    setErrorMessage(null);
    setStatusMessage(injectUnexpectedEvent ? "Autopilot injecting a random park problem, then evaluating a bounded mitigation." : "Autopilot scanning live park state and evaluating a bounded action.");
    setAutopilotDecision({
      mode: "watching",
      enabled: true,
      reason: injectUnexpectedEvent
        ? "Creating an unexpected live incident, then checking planner output, policy gate, and action allowlist."
        : "Scanning live state, planner output, policy gate, and action allowlist.",
    });

    try {
      let reliability: FeedReliabilityGate;
      try {
        reliability = await loadLiveFeedReliabilitySummary();
        void refreshDeepLiveFeedEvidence();
      } catch (error) {
        const message = error instanceof Error ? error.message : "Live-feed evidence summary is still refreshing.";
        setAutopilotDecision({
          mode: "held_for_review",
          enabled: true,
          gate: "refreshing",
          reason: `Autopilot waiting before planning: refreshing live-feed evidence summary. ${message}`,
        });
        setStatusMessage("Autopilot is refreshing live-feed evidence before planning.");
        return;
      }

      if (isFeedReliabilityHardHold(reliability)) {
        setAutopilotDecision({
          mode: "held_for_review",
          enabled: true,
          gate: reliability.status,
          reason: `Autopilot held before planning: fast feed gate is ${reliability.status} (${reliability.score}/100). ${reliability.reasons[0]}`,
        });
        setStatusMessage("Autopilot held before planning because live-feed evidence is not clear.");
        return;
      }

      if (reliability.status === "degraded") {
        setAutopilotDecision({
          mode: "watching",
          enabled: true,
          gate: reliability.status,
          reason: degradedFeedPlanningReason(reliability),
        });
        setStatusMessage("Autopilot is continuing with degraded feed evidence; stale weather remains review-gated for weather-sensitive execution.");
      }

      const activeScenario = park.parkState.guestFlow.activeScenario;
      const response = await fetchParkPulseApi("/api/park/agent-run", {
        method: "POST",
        headers: { "content-type": "application/json", "x-parkpulse-role": "ops_team" },
        body: JSON.stringify({
          scenario_key: activeScenario.key || undefined,
          operation_mode: true,
          auto_unexpected_event: injectUnexpectedEvent,
          operator_message: injectUnexpectedEvent
            ? "Random incident autopilot drill: introduce one unexpected park problem, reason over noisy signals, and prefer a reversible low-risk mitigation such as guest routing, signage, food demand redirect, or staff notification. Avoid direct ride control unless no safer alternative exists. Execute only if policy clears it."
            : activeScenario.description || activeScenario.name || "Autopilot tick: scan current park state and select one bounded operating action.",
          execute: false,
        }),
        timeoutMs: longRunningRequestTimeoutMs,
      });
      const payload = (await response.json()) as RunPayload;
      const telemetry = normalizeRunTelemetry(payload);
      setRunTelemetry(telemetry);

      const action = telemetry.planner?.selected_action;
      const gate = telemetry.governance?.gate_status;
      const confidence = normalizedConfidenceScore(telemetry.planner?.confidence_score);
      const allowlistMatched = isAutopilotAllowed(action);
      const baseDecision = { enabled: true, action, gate, allowlistMatched };

      if (!action?.target || !action.action) {
        setAutopilotDecision({
          ...baseDecision,
          mode: "blocked",
          reason: "Planner did not produce a concrete target/action pair for automation.",
        });
        setStatusMessage("Autopilot stopped: no concrete action was selected.");
        return;
      }

      if (isHardBlockedGate(gate)) {
        setAutopilotDecision({
          ...baseDecision,
          mode: "blocked",
          reason: `Policy gate blocked ${autopilotActionLabel(action)} before execution.`,
        });
        setStatusMessage("Autopilot stopped: policy gate blocked the selected action.");
        return;
      }

      if (!allowlistMatched) {
        setAutopilotDecision({
          ...baseDecision,
          mode: "held_for_review",
          reason: `${autopilotActionLabel(action)} is outside the low-risk autopilot allowlist.`,
        });
        setStatusMessage("Autopilot held the selected action for operator review.");
        return;
      }

      if (confidence !== undefined && confidence < 0.55) {
        setAutopilotDecision({
          ...baseDecision,
          mode: "held_for_review",
          reason: `Planner confidence is ${Math.round(confidence * 100)}%, below the 55% autopilot threshold.`,
        });
        setStatusMessage("Autopilot held the selected action because confidence is too low.");
        return;
      }

      setAutopilotDecision({
        ...baseDecision,
        mode: "executing",
        reason: `${autopilotActionLabel(action)} matched the low-risk allowlist. Sending through backend policy gate.`,
      });

      const actionResponse = await fetchParkPulseApi("/api/park/action", {
        method: "POST",
        headers: { "content-type": "application/json", "x-parkpulse-role": "ops_team" },
        body: JSON.stringify({ target: action.target, action: action.action }),
        timeoutMs: 12000,
      });
      const actionPayload = (await actionResponse.json()) as { status?: string; message?: string; governance?: RunTelemetry["governance"]; state?: unknown };
      const backendGate = actionPayload.governance?.gate_status ?? gate;
      const executionStatus = actionPayload.status ?? actionPayload.governance?.gate_status ?? "unknown";
      setRunTelemetry((current) => ({
        ...(current ?? telemetry),
        governance: actionPayload.governance ?? current?.governance ?? telemetry.governance,
      }));

      if (isHardBlockedGate(backendGate) || /blocked/i.test(executionStatus)) {
        setAutopilotDecision({
          ...baseDecision,
          gate: backendGate,
          mode: "blocked",
          executionStatus,
          reason: actionPayload.message ?? "Backend policy gate blocked execution.",
        });
        setStatusMessage("Autopilot blocked by backend policy gate.");
        return;
      }

      if (/pending|review|approval/i.test(executionStatus) || /review|approval/i.test(String(backendGate ?? ""))) {
        setAutopilotDecision({
          ...baseDecision,
          gate: backendGate,
          mode: "held_for_review",
          executionStatus,
          reason: actionPayload.message ?? "Backend policy requires operator approval before execution.",
        });
        setStatusMessage("Autopilot held by backend policy gate for operator review.");
        return;
      }

      setAutopilotDecision({
        ...baseDecision,
        gate: backendGate,
        mode: "executed",
        executionStatus,
        executedAt: new Date().toISOString(),
        reason: actionPayload.message ?? `${autopilotActionLabel(action)} executed through the policy-gated action path.`,
      });
      setStatusMessage(`Autopilot executed ${autopilotActionLabel(action)}.`);
      await park.refreshParkState();
      if (loadProofData) {
        void refreshActualTraining();
        void refreshOperatingLoopResilience();
        void refreshLiveAgentsSmoke();
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unable to run autopilot tick.";
      setErrorMessage(message);
      setStatusMessage(null);
      setAutopilotDecision({
        mode: "blocked",
        enabled: true,
        reason: message,
      });
    } finally {
      autopilotCycleInFlightRef.current = false;
      setIsAutopilotRunning(false);
      setIsRunning(false);
    }
  }, [isAutopilotEnabled, loadLiveFeedReliabilitySummary, loadProofData, park, refreshActualTraining, refreshDeepLiveFeedEvidence, refreshLiveAgentsSmoke, refreshOperatingLoopResilience]);

  useEffect(() => {
    if (!isLiveLoopRunning) return undefined;
    const timeoutId = window.setTimeout(() => {
      setIsLiveLoopRunning(false);
      setStatusMessage("Live loop auto-stopped after 15 minutes.");
    }, liveLoopAutoStopMs);
    return () => window.clearTimeout(timeoutId);
  }, [isLiveLoopRunning]);

  useEffect(() => {
    runAutopilotCycleRef.current = runAutopilotCycle;
  }, [runAutopilotCycle]);

  useEffect(() => {
    if (!isAutopilotEnabled) {
      setAutopilotNextRunAt(null);
      return undefined;
    }

    let cancelled = false;
    let timerId: number | undefined;
    const scheduleNext = (delayMs: number) => {
      setAutopilotNextRunAt(new Date(Date.now() + delayMs).toISOString());
      timerId = window.setTimeout(async () => {
        if (cancelled) return;
        await runAutopilotCycleRef.current();
        if (!cancelled) scheduleNext(autopilotLoopIntervalMs);
      }, delayMs);
    };

    scheduleNext(750);
    return () => {
      cancelled = true;
      setAutopilotNextRunAt(null);
      if (timerId !== undefined) window.clearTimeout(timerId);
    };
  }, [isAutopilotEnabled]);

  const acknowledgeDispatch = useCallback(
    async (dispatch: DispatchView, choice: "approved" | "held_for_review" | "acknowledged") => {
      setIsApproving(true);
      setErrorMessage(null);
      try {
        const selectedId = dispatch.dispatch?.id ?? dispatch.id;
        const isApprovalDecision = choice === "approved" || choice === "held_for_review";
        setRunTelemetry((current) => {
          const currentDelivery = current?.delivery;
          const currentDispatches = currentDelivery?.dispatches ?? [];
          if (!currentDispatches.length) return current;
          return {
            ...(current ?? {}),
            delivery: {
              ...(currentDelivery ?? {}),
              dispatches: currentDispatches.map((item) => withDispatchAcknowledgement(item, selectedId, dispatch.channel, choice)),
            },
          };
        });
        const response = await fetchParkPulseApi(isApprovalDecision ? "/api/park/delivery/approval-decision" : "/api/park/delivery/acknowledge", {
          method: "POST",
          headers: { "content-type": "application/json", "x-parkpulse-role": "ops_team" },
          body: JSON.stringify(
            isApprovalDecision
              ? {
                  dispatch_id: selectedId,
                  id: selectedId,
                  actor: "operator",
                  decision: choice,
                  reason: choice === "approved" ? "Operator approved this receiver payload." : "Operator held this receiver payload for review.",
                  channel: dispatch.channel,
                }
              : {
                  dispatch_id: selectedId,
                  id: selectedId,
                  actor: "operator",
                  choice,
                  channel: dispatch.channel,
                },
          ),
          timeoutMs: 12000,
        });
        const payload = (await response.json()) as { status?: string; state?: unknown; dispatch?: DeliveryDispatch; delivery?: RunTelemetry["delivery"] };
        if (payload.state) park.applyParkState(payload.state);
        setRunTelemetry((current) => {
          const currentDelivery = current?.delivery;
          const currentDispatches = currentDelivery?.dispatches ?? [];
          const nextDispatches = currentDispatches.length
            ? currentDispatches.map((item) => withDispatchAcknowledgement(item, selectedId, dispatch.channel, choice, payload.dispatch))
            : payload.delivery?.dispatches ?? [];
          return {
            ...(current ?? {}),
            delivery: {
              ...(currentDelivery ?? {}),
              ...(payload.delivery ?? {}),
              dispatches: nextDispatches,
            },
          };
        });
        setStatusMessage(isApprovalDecision ? `Receiver payload ${choice.replaceAll("_", " ")}.` : `Receiver ${payload.status ?? choice}.`);
        if (loadProofData) {
          void refreshActualTraining();
          void refreshOperatingLoopResilience();
        }
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : "Unable to update receiver acknowledgement.");
      } finally {
        setIsApproving(false);
      }
    },
    [loadProofData, park, refreshActualTraining, refreshOperatingLoopResilience],
  );

  return {
    ...park,
    runAgent,
    runDepartmentNegotiationDemo,
    runLiveFeedAgent,
    runAutopilotCycle,
    executeSelectedAction,
    acknowledgeDispatch,
    runTelemetry,
    agentBriefs,
    dispatches,
    activeEvalScores,
    integrationStatus,
    gcpLiveReadiness,
    operatingLoopResilience,
    canManageFeeds,
    canReviewCases,
    canReviewLabels,
    canStartTraining,
    canExecute,
    canAcknowledge,
    actualTraining,
    reviewLabelPipeline,
    roleAccess,
    selectedAction,
    policyGate,
    evalScore,
    memoryMode,
    isRunning,
    isDispatching,
    isApproving,
    isTrainingLoading,
    isStartingGcpTraining,
    isReviewLabelPipelineLoading: isReviewLabelPipelineLoading || isAutoLabelingReviewLabels,
    isAutoLabelingReviewLabels,
    isRoleAccessLoading,
    isLiveFeedHealthLoading: isLiveFeedHealthLoading || isRefreshingStaleFeeds || isAutoRecoveringLiveFeeds,
    isAutoRecoveringLiveFeeds,
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
    startupLoadTimings,
    isAutopilotEnabled,
    isAutopilotRunning,
    autopilotNextRunAt,
    autopilotDecision,
    feedReliabilityGate,
    isLiveLoopRunning,
    setAutopilotEnabled,
    startLiveLoop,
    stopLiveLoop,
    refreshActualTraining,
    refreshGcpLiveReadiness,
    refreshOperatingLoopResilience,
    refreshLiveAgentsSmoke,
    refreshReviewLabelPipeline,
    refreshRoleAccess,
    refreshLiveFeedHealth,
    refreshStaleLiveFeeds,
    recordReviewDecision,
    recordReviewLabelDecision,
    autoLabelHighConfidenceReviewLabels,
    loadLiveWeatherFeed,
    loadLiveRideOpsFeed,
    loadLiveGuestFlowFeed,
    loadLiveStaffingFeed,
    loadLiveFoodOpsFeed,
    loadLiveOperatorSignalFeed,
  };
}
