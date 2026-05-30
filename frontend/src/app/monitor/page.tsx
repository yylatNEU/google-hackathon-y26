"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchParkPulseApi } from "@/lib/api";

type LaneDecision = {
  area: "Safety" | "Operations" | "Experience" | "Customer Care";
  decision: "clear" | "review" | "block";
  rule: string;
  policy_refs: string[];
  matched_action_refs: string[];
  unknown_action_refs?: string[];
  violations: string[];
  warnings: string[];
};

type SupervisedAction = {
  action_id: string;
  title: string;
  owner: string;
  deadline_minutes?: number;
  park_action: { target?: string; action?: string };
  policy_status: "clear" | "review" | "blocked";
  lanes: LaneDecision[];
};

type RuntimeGovernance = {
  decision_ledger: Array<{
    id: string;
    createdAt: string;
    source: string;
    title?: string;
    gateStatus: "clear" | "review" | "blocked";
    allowed: boolean;
    policyFindings: string[];
    remediationTaskId?: string;
    customerCareCaseId?: string;
  }>;
  remediation_tasks: Array<{
    id: string;
    status: string;
    severity: string;
    owner: string;
    action: string;
    title: string;
    requiredAction: string;
    policyFindings: string[];
  }>;
  customer_care_cases: Array<{
    id: string;
    status: string;
    severity: string;
    reason: string;
    safeAudience: string;
    openCasePressure?: number;
    policyFindings: string[];
  }>;
  summary: {
    ledger_count: number;
    open_remediation_count: number;
    open_customer_care_count: number;
  };
};

type MonitorData = {
  monitoring_id: string;
  created_at: string;
  entrypoint?: string;
  mode?: string;
  status?: string;
  overall_status: "clear" | "review" | "blocked";
  scenario: { key: string; name: string };
  summary: {
    action_count: number;
    clear_count: number;
    review_count: number;
    blocked_count: number;
    policy_book_count: number;
    arize_ready: boolean;
    gcp_trace_eval_ready?: boolean;
    gcp_improvement_ready?: boolean;
    primary_improvement_loop?: string;
    overall_eval_score: number;
    needs_human_approval: boolean;
    open_signal_count: number;
  };
  gcp_trace_eval?: {
    status: string;
    platform: string;
    mode: string;
    project?: string;
    dataset?: string;
    readiness_issues: string[];
    eval_subject: string;
    dimensions: string[];
    trace_state?: string;
    evidence_depth?: string;
    evaluation_status?: string;
    trace_lookup_query?: string;
    trace_url?: string;
  };
  gemini_performance?: {
    status: string;
    provider: string;
    platform: string;
    model: string;
    project?: string;
    location?: string;
    ready: boolean;
    runtime: string;
    attempted_gemini: boolean;
    latency_ms?: number | null;
    timeout_seconds?: number | null;
    latency_status: string;
    budget_used_pct?: number | null;
    confidence_score: number;
    candidate_count: number;
    custom_mix_count: number;
    readiness_issues: string[];
    errors: string[];
    latest_decision?: {
      decision_id?: string;
      created_at?: string;
      recommended_action?: string;
      selected_action?: { label?: string; target?: string; action?: string };
    };
    gcp_monitor?: {
      trace_eval_ready?: boolean;
      trace_project?: string;
      dataset?: string;
      primary_path?: string;
    };
  };
  arize_monitor: {
    status: string;
    project_name: string;
    collector_endpoint: string;
    readiness_issues: string[];
    eval_subject: string;
    dimensions: string[];
    trace_lookup_query?: string;
    trace_url?: string;
  };
  policy_index: {
    policy_book_id: string;
    version: string;
    product_thesis: string;
    active_policy_books: string[];
    decision_order: string[];
    human_operators_own: string[];
    absolute_prohibitions: string[];
  };
  policy_integrity?: {
    status: "clean" | "needs_cleanup";
    issues: string[];
    book_count: number;
    policy_ref_count: number;
    stale_terms: string[];
    missing_active_books: string[];
    missing_required_refs: string[];
  };
  runtime_governance?: RuntimeGovernance;
  guest_care_state?: {
    openCases?: number;
    complaintRatePct?: number;
    topDrivers?: string[];
    policy?: string;
  };
  maintenance_state?: {
    clearanceRequiredCount?: number;
    sensorAnomalyCount?: number;
    blockedAutomation?: string[];
    openWorkOrders?: Array<{ id?: string; rideName?: string; clearance?: string; etaMinutes?: number; faultCode?: string }>;
  };
  supervised_actions: SupervisedAction[];
  operator_checklist: string[];
};

type MonitorPayload = Partial<MonitorData> & {
  scenario?: Partial<MonitorData["scenario"]>;
  summary?: Partial<MonitorData["summary"]>;
  gcp_trace_eval?: Partial<NonNullable<MonitorData["gcp_trace_eval"]>>;
  gemini_performance?: Partial<NonNullable<MonitorData["gemini_performance"]>>;
  arize_monitor?: Partial<MonitorData["arize_monitor"]>;
  policy_index?: Partial<MonitorData["policy_index"]>;
  policy_integrity?: Partial<NonNullable<MonitorData["policy_integrity"]>>;
  runtime_governance?: Partial<RuntimeGovernance> & {
    summary?: Partial<RuntimeGovernance["summary"]>;
  };
};

const fallbackMonitor: MonitorData = {
  monitoring_id: "PP-MON-local",
  created_at: "",
  overall_status: "review",
  scenario: { key: "ride_down", name: "Ride Down" },
  summary: {
    action_count: 0,
    clear_count: 0,
    review_count: 0,
    blocked_count: 0,
    policy_book_count: 0,
    arize_ready: false,
    gcp_trace_eval_ready: false,
    gcp_improvement_ready: false,
    primary_improvement_loop: "gcp_bigquery",
    overall_eval_score: 0,
    needs_human_approval: true,
    open_signal_count: 0,
  },
  gcp_trace_eval: {
    status: "unavailable",
    platform: "GCP internal trace/eval",
    mode: "local_scorecard_with_gcp_export_preview",
    project: "",
    dataset: "parkpulse_analytics",
    readiness_issues: ["Backend monitor not reachable."],
    eval_subject: "park_operations_action_plan",
    dimensions: [],
    trace_state: "no_active_span",
    evidence_depth: "fallback_monitor",
    evaluation_status: "local_scorecard_only",
  },
  gemini_performance: {
    status: "monitor_unavailable",
    provider: "Gemini",
    platform: "unknown",
    model: "unknown",
    project: "",
    location: "",
    ready: false,
    runtime: "unknown",
    attempted_gemini: false,
    latency_ms: null,
    timeout_seconds: 90,
    latency_status: "unknown",
    budget_used_pct: null,
    confidence_score: 0,
    candidate_count: 0,
    custom_mix_count: 0,
    readiness_issues: ["Backend monitor not reachable."],
    errors: [],
    latest_decision: {},
    gcp_monitor: { trace_eval_ready: false, dataset: "parkpulse_analytics", primary_path: "gcp_bigquery" },
  },
  arize_monitor: {
    status: "unavailable",
    project_name: "",
    collector_endpoint: "",
    readiness_issues: ["Backend monitor not reachable."],
    eval_subject: "park_operations_action_plan",
    dimensions: [],
  },
  policy_index: {
    policy_book_id: "parkpulse_governance_index",
    version: "",
    product_thesis: "ParkPulse monitor waits for backend policy-book supervision data.",
    active_policy_books: [],
    decision_order: [],
    human_operators_own: [],
    absolute_prohibitions: [],
  },
  policy_integrity: {
    status: "needs_cleanup",
    issues: ["Backend policy integrity check not loaded."],
    book_count: 0,
    policy_ref_count: 0,
    stale_terms: [],
    missing_active_books: [],
    missing_required_refs: [],
  },
  supervised_actions: [],
  operator_checklist: [],
  runtime_governance: {
    decision_ledger: [],
    remediation_tasks: [],
    customer_care_cases: [],
    summary: { ledger_count: 0, open_remediation_count: 0, open_customer_care_count: 0 },
  },
};

function normalizeMonitor(payload: MonitorPayload): MonitorData {
  return {
    ...fallbackMonitor,
    ...payload,
    monitoring_id: payload.monitoring_id ?? fallbackMonitor.monitoring_id,
    created_at: payload.created_at ?? fallbackMonitor.created_at,
    overall_status: payload.overall_status ?? fallbackMonitor.overall_status,
    scenario: { ...fallbackMonitor.scenario, ...(payload.scenario ?? {}) },
    summary: { ...fallbackMonitor.summary, ...(payload.summary ?? {}) },
    gcp_trace_eval: { ...fallbackMonitor.gcp_trace_eval!, ...(payload.gcp_trace_eval ?? {}) },
    gemini_performance: { ...fallbackMonitor.gemini_performance!, ...(payload.gemini_performance ?? {}) },
    arize_monitor: { ...fallbackMonitor.arize_monitor, ...(payload.arize_monitor ?? {}) },
    policy_index: { ...fallbackMonitor.policy_index, ...(payload.policy_index ?? {}) },
    policy_integrity: { ...fallbackMonitor.policy_integrity!, ...(payload.policy_integrity ?? {}) },
    runtime_governance: {
      ...fallbackMonitor.runtime_governance!,
      ...(payload.runtime_governance ?? {}),
      summary: {
        ...fallbackMonitor.runtime_governance!.summary,
        ...(payload.runtime_governance?.summary ?? {}),
      },
      decision_ledger: payload.runtime_governance?.decision_ledger ?? fallbackMonitor.runtime_governance!.decision_ledger,
      remediation_tasks: payload.runtime_governance?.remediation_tasks ?? fallbackMonitor.runtime_governance!.remediation_tasks,
      customer_care_cases: payload.runtime_governance?.customer_care_cases ?? fallbackMonitor.runtime_governance!.customer_care_cases,
    },
    supervised_actions: payload.supervised_actions ?? fallbackMonitor.supervised_actions,
    operator_checklist: payload.operator_checklist ?? fallbackMonitor.operator_checklist,
  };
}

function statusClass(status: string) {
  if (status === "blocked" || status === "block") return "border-red-500/40 bg-red-950/30 text-red-100";
  if (status === "review") return "border-amber-500/40 bg-amber-950/30 text-amber-100";
  return "border-emerald-500/40 bg-emerald-950/30 text-emerald-100";
}

function statusLabel(status: string) {
  if (status === "block") return "blocked";
  return status;
}

function geminiTone(performance?: MonitorData["gemini_performance"]) {
  if (!performance?.ready || ["error", "timeout", "fallback", "not_ready", "monitor_unavailable"].includes(performance?.status ?? "")) return "review";
  if (performance.latency_status === "slow") return "review";
  return "clear";
}

function latencyLabel(value?: number | null) {
  if (value === null || value === undefined) return "-";
  return `${value}ms`;
}

function Metric({ label, value, tone }: { label: string; value: string | number; tone?: string }) {
  return (
    <div className={`rounded-lg border p-4 ${statusClass(tone ?? "clear")}`}>
      <div className="text-[10px] font-black uppercase tracking-widest opacity-70">{label}</div>
      <div className="mt-2 text-2xl font-black">{value}</div>
    </div>
  );
}

export default function MonitorPage() {
  const [monitor, setMonitor] = useState<MonitorData>(fallbackMonitor);
  const [lastRefresh, setLastRefresh] = useState<string>("not loaded");
  const [monitorDepth, setMonitorDepth] = useState<"summary" | "deep">("summary");
  const [error, setError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isDeepRefreshing, setIsDeepRefreshing] = useState(false);

  const loadMonitor = useCallback(async (depth: "summary" | "deep" = "summary") => {
    if (depth === "deep") {
      setIsDeepRefreshing(true);
    } else {
      setIsRefreshing(true);
    }
    try {
      const endpoint = depth === "deep" ? "/api/park/agent-monitoring/deep" : "/api/park/agent-monitoring";
      const response = await fetchParkPulseApi(endpoint);
      const data = (await response.json()) as MonitorPayload;
      if (!response.ok) {
        throw new Error(data.status ?? `Monitor request failed with ${response.status}`);
      }
      setMonitor(normalizeMonitor(data));
      setMonitorDepth(depth);
      setLastRefresh(new Date().toLocaleTimeString());
      setError(null);
    } catch (loadError) {
      if (depth === "summary") setMonitor(fallbackMonitor);
      setLastRefresh(new Date().toLocaleTimeString());
      setError(loadError instanceof Error ? loadError.message : "Unable to load monitor.");
    } finally {
      if (depth === "deep") {
        setIsDeepRefreshing(false);
      } else {
        setIsRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    void loadMonitor("summary");
    const interval = window.setInterval(() => {
      if (!cancelled) void loadMonitor("summary");
    }, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [loadMonitor]);

  return (
    <main className="min-h-screen overflow-x-hidden bg-slate-950 px-4 py-5 font-sans text-slate-200 lg:px-8">
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="grid gap-5 border-b border-slate-800 pb-6 lg:grid-cols-[minmax(0,1fr)_24rem] lg:items-end">
          <div>
            <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">GCP trace/eval policy monitor</div>
            <h1 className="mt-2 text-3xl font-black leading-tight text-slate-100 sm:text-5xl">Supervise ParkPulse agent actions</h1>
            <p className="mt-3 max-w-3xl text-sm leading-relaxed text-slate-400">
              Step 4 of the ParkPulse story: after the live park map, agent loop, and human workspace produce action receipts, this monitor verifies every action against policy books, GCP trace/eval, grounding, safety, staff stress, guest impact, and follow-through.
            </p>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Current scenario</div>
                <div className="mt-2 text-lg font-black text-slate-100">{monitor.scenario.name}</div>
                <div className="mt-1 text-xs text-slate-500">Refresh: {lastRefresh} / {monitorDepth}</div>
              </div>
              <span className={`rounded px-3 py-2 text-xs font-black ${statusClass(monitor.overall_status)}`}>{statusLabel(monitor.overall_status)}</span>
            </div>
            <div className="mt-4 grid gap-2 sm:grid-cols-4">
              <a href="/" className="rounded-lg border border-slate-700 px-4 py-3 text-center text-sm font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-200">
                Back to console
              </a>
              <a href="/human" className="rounded-lg border border-slate-700 px-4 py-3 text-center text-sm font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-200">
                Human workspace
              </a>
              <button
                type="button"
                onClick={() => void loadMonitor("summary")}
                disabled={isRefreshing}
                className="rounded-lg bg-cyan-300 px-4 py-3 text-sm font-black text-slate-950 transition hover:bg-cyan-200 disabled:bg-slate-700 disabled:text-slate-400"
              >
                {isRefreshing ? "Refreshing..." : "Refresh summary"}
              </button>
              <button
                type="button"
                onClick={() => void loadMonitor("deep")}
                disabled={isDeepRefreshing}
                className="rounded-lg border border-slate-700 px-4 py-3 text-sm font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-200 disabled:border-slate-800 disabled:text-slate-500"
              >
                {isDeepRefreshing ? "Loading..." : "Deep monitor"}
              </button>
            </div>
          </div>
        </header>

        {error && (
          <div className="rounded-lg border border-amber-500/40 bg-amber-950/20 p-4 text-sm leading-relaxed text-amber-100">
            Backend monitor is unavailable, so this page is showing the local policy-monitor fallback. Last error: {error}
          </div>
        )}

        <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-8">
          <Metric label="Gemini" value={monitor.gemini_performance?.status ?? "unknown"} tone={geminiTone(monitor.gemini_performance)} />
          <Metric label="Gemini ms" value={latencyLabel(monitor.gemini_performance?.latency_ms)} tone={geminiTone(monitor.gemini_performance)} />
          <Metric label="GCP eval" value={monitor.summary.gcp_trace_eval_ready ? "ready" : "preview"} tone={monitor.summary.gcp_trace_eval_ready ? "clear" : "review"} />
          <Metric label="Trace" value={monitor.gcp_trace_eval?.trace_state ?? "local"} tone={monitor.gcp_trace_eval?.trace_state === "export_configured" ? "clear" : "review"} />
          <Metric label="Eval score" value={monitor.summary.overall_eval_score || "-"} tone={monitor.summary.overall_eval_score >= 85 ? "clear" : "review"} />
          <Metric label="Policy book" value={monitor.policy_integrity?.status === "clean" ? "clean" : "review"} tone={monitor.policy_integrity?.status === "clean" ? "clear" : "review"} />
          <Metric label="Clear" value={monitor.summary.clear_count} tone="clear" />
          <Metric label="Review" value={monitor.summary.review_count} tone={monitor.summary.review_count ? "review" : "clear"} />
          <Metric label="Blocked" value={monitor.summary.blocked_count} tone={monitor.summary.blocked_count ? "blocked" : "clear"} />
        </section>

        <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Gemini performance</div>
              <h2 className="mt-1 text-xl font-black text-slate-100">{monitor.gemini_performance?.provider ?? "Gemini"} / {monitor.gemini_performance?.model ?? "model unknown"}</h2>
            </div>
            <span className={`w-fit rounded px-3 py-2 text-xs font-black ${statusClass(geminiTone(monitor.gemini_performance))}`}>
              {monitor.gemini_performance?.ready ? "provider ready" : "provider not ready"}
            </span>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <div className="rounded border border-slate-800 bg-slate-950 p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Runtime path</div>
              <div className="mt-1 truncate text-sm font-black text-slate-100">{monitor.gemini_performance?.runtime || monitor.gemini_performance?.platform || "unknown"}</div>
            </div>
            <div className="rounded border border-slate-800 bg-slate-950 p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Latency budget</div>
              <div className="mt-1 text-sm font-black text-slate-100">
                {latencyLabel(monitor.gemini_performance?.latency_ms)} / {monitor.gemini_performance?.timeout_seconds ?? 90}s
              </div>
            </div>
            <div className="rounded border border-slate-800 bg-slate-950 p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Confidence</div>
              <div className="mt-1 text-sm font-black text-slate-100">{monitor.gemini_performance?.confidence_score || 0}</div>
            </div>
            <div className="rounded border border-slate-800 bg-slate-950 p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">GCP monitor path</div>
              <div className="mt-1 truncate text-sm font-black text-slate-100">
                {monitor.gemini_performance?.gcp_monitor?.trace_eval_ready ? "trace/eval ready" : "trace/eval preview"}
              </div>
            </div>
          </div>
          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs leading-relaxed text-slate-300">
              <span className="font-black text-slate-100">Latest decision:</span>{" "}
              {monitor.gemini_performance?.latest_decision?.decision_id ?? "none observed yet"}
              {monitor.gemini_performance?.latest_decision?.recommended_action ? (
                <div className="mt-2 text-slate-400">{monitor.gemini_performance.latest_decision.recommended_action}</div>
              ) : null}
            </div>
            <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs leading-relaxed text-slate-300">
              <span className="font-black text-slate-100">Diagnostics:</span>{" "}
              {[
                ...(monitor.gemini_performance?.errors ?? []),
                ...(monitor.gemini_performance?.readiness_issues ?? []),
              ].slice(0, 2).join(" ") || "No Gemini runtime errors reported."}
            </div>
          </div>
        </section>

        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <Metric label="Runtime gates" value={monitor.runtime_governance?.summary.ledger_count ?? 0} tone={(monitor.runtime_governance?.summary.ledger_count ?? 0) ? "clear" : "review"} />
          <Metric label="Remediation" value={monitor.runtime_governance?.summary.open_remediation_count ?? 0} tone={(monitor.runtime_governance?.summary.open_remediation_count ?? 0) ? "review" : "clear"} />
          <Metric label="Care queue" value={monitor.runtime_governance?.summary.open_customer_care_count ?? monitor.guest_care_state?.openCases ?? 0} tone={(monitor.runtime_governance?.summary.open_customer_care_count ?? 0) ? "review" : "clear"} />
          <Metric label="Maintenance holds" value={monitor.maintenance_state?.clearanceRequiredCount ?? 0} tone={(monitor.maintenance_state?.clearanceRequiredCount ?? 0) ? "blocked" : "clear"} />
        </section>

        <section className="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
          <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
            <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">GCP supervision</div>
            <h2 className="mt-1 text-xl font-black text-slate-100">{monitor.gcp_trace_eval?.eval_subject ?? "park_operations_action_plan"}</h2>
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              <div className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Status</div>
                <div className="mt-1 text-sm font-black text-slate-100">{monitor.gcp_trace_eval?.status ?? "local_preview"}</div>
              </div>
              <div className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Project</div>
                <div className="mt-1 truncate text-sm font-black text-slate-100">{monitor.gcp_trace_eval?.project || "not configured"}</div>
              </div>
              <div className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Dataset</div>
                <div className="mt-1 truncate text-sm font-black text-slate-100">{monitor.gcp_trace_eval?.dataset || "parkpulse_analytics"}</div>
              </div>
              <div className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Mode</div>
                <div className="mt-1 truncate text-sm font-black text-slate-100">{monitor.gcp_trace_eval?.mode ?? monitor.summary.primary_improvement_loop ?? "gcp_bigquery"}</div>
              </div>
              <div className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Trace state</div>
                <div className="mt-1 truncate text-sm font-black text-slate-100">{monitor.gcp_trace_eval?.trace_state ?? "local_otel_context"}</div>
              </div>
              <div className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Evaluator</div>
                <div className="mt-1 truncate text-sm font-black text-slate-100">{monitor.gcp_trace_eval?.evaluation_status ?? "local_scorecard_only"}</div>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {(monitor.gcp_trace_eval?.dimensions ?? []).map((dimension) => (
                <span key={dimension} className="rounded bg-slate-950 px-3 py-2 text-xs font-bold text-slate-300">
                  {dimension}
                </span>
              ))}
            </div>
            {((monitor.gcp_trace_eval?.readiness_issues.length ?? 0) > 0 || monitor.gcp_trace_eval?.trace_lookup_query) && (
              <div className="mt-4 rounded border border-slate-800 bg-slate-950 p-3 text-xs leading-relaxed text-slate-400">
                {monitor.gcp_trace_eval?.trace_lookup_query || monitor.gcp_trace_eval?.readiness_issues.join(" ")}
                {monitor.gcp_trace_eval?.trace_url ? (
                  <a className="mt-2 block font-black text-cyan-200 underline-offset-4 hover:underline" href={monitor.gcp_trace_eval.trace_url} target="_blank" rel="noreferrer">
                    Open trace
                  </a>
                ) : null}
              </div>
            )}
          </section>

          <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
            <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Policy book</div>
            <h2 className="mt-1 text-xl font-black text-slate-100">
              {monitor.policy_index.policy_book_id} {monitor.policy_index.version}
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-slate-400">{monitor.policy_index.product_thesis}</p>
            <div className="mt-4 grid gap-2 md:grid-cols-2">
              {monitor.policy_index.active_policy_books.map((book) => (
                <div key={book} className="rounded border border-slate-800 bg-slate-950 p-3 text-xs font-bold text-slate-300">
                  {book}
                </div>
              ))}
            </div>
            <div className={`mt-4 rounded border p-3 text-xs leading-relaxed ${statusClass(monitor.policy_integrity?.status === "clean" ? "clear" : "review")}`}>
              <span className="font-black uppercase">Integrity: {monitor.policy_integrity?.status ?? "unknown"}</span>
              <span className="ml-2 opacity-80">
                {monitor.policy_integrity?.book_count ?? 0} books / {monitor.policy_integrity?.policy_ref_count ?? 0} refs
              </span>
              {monitor.policy_integrity?.issues?.length ? <div className="mt-2">{monitor.policy_integrity.issues.join(" ")}</div> : null}
            </div>
          </section>
        </section>

        <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Action supervision</div>
              <h2 className="mt-1 text-xl font-black text-slate-100">Policy decisions by agent action</h2>
            </div>
            <span className="rounded bg-slate-950 px-3 py-2 text-xs font-black text-slate-300">{monitor.summary.action_count} actions watched</span>
          </div>
          <div className="mt-4 grid gap-4">
            {monitor.supervised_actions.map((action) => (
              <article key={action.action_id} className="rounded-lg border border-slate-800 bg-slate-950 p-4">
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div>
                    <div className="text-sm font-black text-slate-100">{action.title}</div>
                    <div className="mt-1 text-xs text-slate-500">
                      {action.owner} / {action.park_action.target}/{action.park_action.action} / {action.deadline_minutes ?? "-"}m
                    </div>
                  </div>
                  <span className={`w-fit rounded px-3 py-2 text-xs font-black ${statusClass(action.policy_status)}`}>{statusLabel(action.policy_status)}</span>
                </div>
                <div className="mt-4 grid gap-3 lg:grid-cols-4">
                  {action.lanes.map((lane) => (
                    <div key={lane.area} className={`rounded border p-3 ${statusClass(lane.decision)}`}>
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-[10px] font-black uppercase tracking-widest opacity-75">{lane.area}</div>
                        <div className="text-[10px] font-black uppercase">{statusLabel(lane.decision)}</div>
                      </div>
                      <p className="mt-2 text-xs leading-relaxed opacity-85">{lane.rule}</p>
                      {[...lane.violations, ...lane.warnings].slice(0, 2).map((item) => (
                        <div key={item} className="mt-2 rounded bg-slate-950/60 px-2 py-1 text-[11px] leading-relaxed">
                          {item}
                        </div>
                      ))}
                    </div>
                  ))}
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
          <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
            <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Runtime enforcement</div>
            <h2 className="mt-1 text-xl font-black text-slate-100">Decision ledger and remediation</h2>
            <div className="mt-4 grid gap-3">
              {(monitor.runtime_governance?.decision_ledger ?? []).slice(0, 4).map((entry) => (
                <div key={entry.id} className={`rounded border p-3 ${statusClass(entry.gateStatus)}`}>
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                    <div>
                      <div className="text-sm font-black">{entry.title || entry.id}</div>
                      <div className="mt-1 text-[11px] uppercase tracking-widest opacity-70">{entry.source} / {entry.createdAt}</div>
                    </div>
                    <span className="w-fit rounded bg-slate-950/50 px-2 py-1 text-[10px] font-black uppercase">{entry.allowed ? "executed" : "held"}</span>
                  </div>
                  {entry.policyFindings.slice(0, 2).map((finding) => (
                    <div key={finding} className="mt-2 rounded bg-slate-950/60 px-2 py-1 text-xs leading-relaxed">{finding}</div>
                  ))}
                </div>
              ))}
              {(monitor.runtime_governance?.decision_ledger.length ?? 0) === 0 && (
                <div className="rounded border border-slate-800 bg-slate-950 p-4 text-sm text-slate-400">No runtime gates have fired in this browser session yet.</div>
              )}
            </div>
          </section>

          <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
            <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Care and maintenance</div>
            <h2 className="mt-1 text-xl font-black text-slate-100">Operational holds</h2>
            <div className="mt-4 space-y-3">
              {(monitor.maintenance_state?.openWorkOrders ?? []).slice(0, 2).map((workOrder) => (
                <div key={workOrder.id} className="rounded border border-red-500/30 bg-red-950/10 p-3 text-xs text-red-100">
                  <div className="font-black">{workOrder.rideName} / {workOrder.clearance}</div>
                  <div className="mt-1 opacity-80">{workOrder.faultCode} / ETA {workOrder.etaMinutes}m</div>
                </div>
              ))}
              <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs leading-relaxed text-slate-300">
                <span className="font-black text-slate-100">Guest care:</span> {monitor.guest_care_state?.openCases ?? 0} open cases, {monitor.guest_care_state?.complaintRatePct ?? 0}% complaint rate.
                {(monitor.guest_care_state?.topDrivers ?? []).length > 0 && (
                  <div className="mt-2 text-slate-400">{monitor.guest_care_state?.topDrivers?.join(" / ")}</div>
                )}
              </div>
              {(monitor.runtime_governance?.remediation_tasks ?? []).slice(0, 3).map((task) => (
                <div key={task.id} className={`rounded border p-3 text-xs leading-relaxed ${statusClass(task.severity === "critical" ? "blocked" : "review")}`}>
                  <div className="font-black">{task.title}</div>
                  <div className="mt-1 opacity-80">{task.owner} / {task.action}</div>
                  <div className="mt-2">{task.requiredAction}</div>
                </div>
              ))}
            </div>
          </section>
        </section>

        <section className="grid gap-6 xl:grid-cols-2">
          <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
            <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Hard blocks</div>
            <div className="mt-4 grid gap-2">
              {monitor.policy_index.absolute_prohibitions.map((item) => (
                <div key={item} className="rounded border border-red-500/30 bg-red-950/10 p-3 text-xs leading-relaxed text-red-100">
                  {item}
                </div>
              ))}
            </div>
          </section>
          <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
            <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Operator checklist</div>
            <div className="mt-4 grid gap-2">
              {monitor.operator_checklist.map((item, index) => (
                <div key={item} className="grid grid-cols-[2rem_1fr] gap-3 rounded border border-slate-800 bg-slate-950 p-3 text-sm text-slate-300">
                  <div className="flex h-6 w-6 items-center justify-center rounded bg-cyan-950 text-xs font-black text-cyan-200">{index + 1}</div>
                  <div>{item}</div>
                </div>
              ))}
            </div>
          </section>
        </section>
      </div>
    </main>
  );
}
