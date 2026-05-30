"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchParkPulseApi } from "@/lib/api";

type RuntimeGovernance = {
  decision_ledger?: Array<{
    id?: string;
    createdAt?: string;
    source?: string;
    title?: string;
    gateStatus?: string;
    allowed?: boolean;
    policyFindings?: string[];
  }>;
  remediation_tasks?: Array<{
    id?: string;
    status?: string;
    severity?: string;
    owner?: string;
    title?: string;
    requiredAction?: string;
    policyFindings?: string[];
  }>;
  customer_care_cases?: Array<{
    id?: string;
    status?: string;
    severity?: string;
    reason?: string;
    safeAudience?: string;
    policyFindings?: string[];
  }>;
  summary?: {
    ledger_count?: number;
    open_remediation_count?: number;
    open_customer_care_count?: number;
  };
};

type MonitorData = {
  monitoring_id?: string;
  created_at?: string;
  entrypoint?: string;
  mode?: string;
  status?: string;
  overall_status?: string;
  summary?: {
    action_count?: number;
    clear_count?: number;
    review_count?: number;
    blocked_count?: number;
    policy_book_count?: number;
    arize_ready?: boolean;
    gcp_trace_eval_ready?: boolean;
    overall_eval_score?: number;
    needs_human_approval?: boolean;
    open_signal_count?: number;
  };
  gcp_trace_eval?: {
    status?: string;
    platform?: string;
    project?: string;
    dataset?: string;
    readiness_issues?: string[];
    trace_url?: string;
  };
  gemini_performance?: {
    status?: string;
    provider?: string;
    model?: string;
    ready?: boolean;
    runtime?: string;
    latency_ms?: number | null;
    confidence_score?: number;
    errors?: string[];
  };
  arize_monitor?: {
    status?: string;
    project_name?: string;
    readiness_issues?: string[];
    trace_url?: string;
  };
  policy_index?: {
    policy_book_id?: string;
    version?: string;
    active_policy_books?: string[];
    decision_order?: string[];
    absolute_prohibitions?: string[];
  };
  policy_integrity?: {
    status?: string;
    issues?: string[];
    book_count?: number;
    policy_ref_count?: number;
    stale_terms?: string[];
    missing_active_books?: string[];
    missing_required_refs?: string[];
  };
  runtime_governance?: RuntimeGovernance;
  supervised_actions?: Array<{
    action_id?: string;
    title?: string;
    owner?: string;
    policy_status?: string;
    park_action?: { target?: string; action?: string };
  }>;
  operator_checklist?: string[];
};

function score(value?: number) {
  return typeof value === "number" ? `${Math.round(value)}/100` : "--";
}

function bool(value?: boolean) {
  if (value === undefined) return "--";
  return value ? "ready" : "not ready";
}

function StatusPill({ value }: { value?: string }) {
  const lower = (value ?? "").toLowerCase();
  const tone = lower.includes("block")
    ? "border-red-400/40 bg-red-950/25 text-red-100"
    : lower.includes("review") || lower.includes("error") || lower.includes("not")
      ? "border-amber-400/40 bg-amber-950/20 text-amber-100"
      : "border-emerald-400/35 bg-emerald-950/20 text-emerald-100";
  return <span className={`rounded border px-2 py-1 text-[10px] font-black uppercase tracking-widest ${tone}`}>{value ?? "--"}</span>;
}

export default function MonitorPage() {
  const [monitor, setMonitor] = useState<MonitorData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isDeep, setIsDeep] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadMonitor = useCallback(async (depth: "summary" | "deep" = "summary") => {
    setIsLoading(true);
    setError(null);
    setIsDeep(depth === "deep");
    try {
      const endpoint = depth === "deep" ? "/api/park/agent-monitoring/deep" : "/api/park/agent-monitoring";
      const response = await fetchParkPulseApi(endpoint, { timeoutMs: depth === "deep" ? 20000 : 8000 });
      setMonitor((await response.json()) as MonitorData);
    } catch (err) {
      setMonitor(null);
      setError(err instanceof Error ? err.message : "Unable to load runtime monitor.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadMonitor("summary");
  }, [loadMonitor]);

  const summary = monitor?.summary;
  const governance = monitor?.runtime_governance;
  const ledger = governance?.decision_ledger ?? [];
  const remediations = governance?.remediation_tasks ?? [];
  const careCases = governance?.customer_care_cases ?? [];
  const supervisedActions = monitor?.supervised_actions ?? [];

  return (
    <main className="min-h-screen bg-slate-950 px-4 py-5 font-sans text-slate-200 lg:px-8">
      <div className="mx-auto max-w-[1500px] space-y-5">
        <header className="rounded-lg border border-slate-800 bg-slate-900 p-5">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Runtime monitor</div>
              <h1 className="mt-2 text-3xl font-black text-slate-100 lg:text-4xl">Policy, eval, trace, and governance status</h1>
              <p className="mt-3 max-w-4xl text-sm leading-relaxed text-slate-400">
                This page renders the monitoring payload returned by the backend. If the payload is missing, the page shows the debug error instead of local monitor data.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => void loadMonitor("summary")}
                disabled={isLoading}
                className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-100 disabled:opacity-50"
              >
                Refresh
              </button>
              <button
                type="button"
                onClick={() => void loadMonitor("deep")}
                disabled={isLoading}
                className="rounded border border-cyan-400/60 bg-cyan-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-cyan-200 disabled:opacity-50"
              >
                Deep check
              </button>
              <a href="/" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-100">
                Operating loop
              </a>
            </div>
          </div>
        </header>

        {error && <section className="rounded border border-amber-400/30 bg-amber-950/15 p-3 text-sm font-bold text-amber-100">Runtime debug: {error}</section>}

        <section className="grid gap-2 md:grid-cols-6">
          {[
            ["Status", monitor?.overall_status ?? (isLoading ? "loading" : "--")],
            ["Mode", isDeep ? "deep" : "summary"],
            ["Actions", String(summary?.action_count ?? "--")],
            ["Review", String(summary?.review_count ?? "--")],
            ["Blocked", String(summary?.blocked_count ?? "--")],
            ["Eval", score(summary?.overall_eval_score)],
          ].map(([label, value]) => (
            <div key={label} className="rounded border border-slate-800 bg-slate-900 p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
              <div className="mt-1 truncate text-sm font-black text-cyan-100">{value}</div>
            </div>
          ))}
        </section>

        <section className="grid gap-5 xl:grid-cols-[1fr_1fr]">
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-emerald-300">Provider readiness</div>
                <h2 className="mt-1 text-xl font-black text-slate-100">Trace and model systems</h2>
              </div>
              <StatusPill value={monitor?.status ?? monitor?.overall_status} />
            </div>
            <div className="mt-4 grid gap-2">
              {[
                ["Gemini", `${monitor?.gemini_performance?.status ?? "--"} / ${monitor?.gemini_performance?.model ?? "--"}`],
                ["Gemini ready", bool(monitor?.gemini_performance?.ready)],
                ["Arize", `${monitor?.arize_monitor?.status ?? "--"} / ${monitor?.arize_monitor?.project_name ?? "--"}`],
                ["GCP trace eval", bool(summary?.gcp_trace_eval_ready)],
                ["Latency", monitor?.gemini_performance?.latency_ms === undefined || monitor?.gemini_performance?.latency_ms === null ? "--" : `${monitor.gemini_performance.latency_ms}ms`],
                ["Monitor id", monitor?.monitoring_id ?? "--"],
              ].map(([label, value]) => (
                <div key={label} className="grid grid-cols-[8rem_1fr] gap-3 rounded border border-slate-800 bg-slate-950 px-3 py-2 text-xs">
                  <div className="font-black uppercase tracking-widest text-slate-500">{label}</div>
                  <div className="font-bold text-slate-100">{value}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="text-[10px] font-black uppercase tracking-widest text-amber-300">Policy index</div>
            <h2 className="mt-1 text-xl font-black text-slate-100">{monitor?.policy_index?.policy_book_id ?? "No policy payload"}</h2>
            <div className="mt-4 grid gap-2">
              {[
                ["Version", monitor?.policy_index?.version ?? "--"],
                ["Books", String(monitor?.policy_index?.active_policy_books?.length ?? "--")],
                ["Integrity", monitor?.policy_integrity?.status ?? "--"],
                ["Policy refs", String(monitor?.policy_integrity?.policy_ref_count ?? "--")],
              ].map(([label, value]) => (
                <div key={label} className="grid grid-cols-[8rem_1fr] gap-3 rounded border border-slate-800 bg-slate-950 px-3 py-2 text-xs">
                  <div className="font-black uppercase tracking-widest text-slate-500">{label}</div>
                  <div className="font-bold text-slate-100">{value}</div>
                </div>
              ))}
            </div>
            <div className="mt-3 rounded border border-slate-800 bg-slate-950 p-3 text-xs leading-relaxed text-slate-400">
              {(monitor?.policy_integrity?.issues?.length ? monitor.policy_integrity.issues : monitor?.policy_index?.absolute_prohibitions ?? []).slice(0, 4).join(" / ") || "No policy findings returned."}
            </div>
          </div>
        </section>

        <section className="grid gap-5 xl:grid-cols-3">
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Decision ledger</div>
            <div className="mt-3 grid gap-2">
              {ledger.length ? (
                ledger.slice(0, 6).map((item) => (
                  <div key={item.id} className="rounded border border-slate-800 bg-slate-950 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="truncate text-sm font-black text-slate-100">{item.title ?? item.id ?? "decision"}</div>
                      <StatusPill value={item.gateStatus} />
                    </div>
                    <p className="mt-2 line-clamp-2 text-xs text-slate-500">{item.policyFindings?.join(" / ") || "No findings returned."}</p>
                  </div>
                ))
              ) : (
                <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs text-slate-500">No runtime decisions returned.</div>
              )}
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="text-[10px] font-black uppercase tracking-widest text-amber-300">Remediation</div>
            <div className="mt-3 grid gap-2">
              {remediations.length ? (
                remediations.slice(0, 6).map((item) => (
                  <div key={item.id} className="rounded border border-slate-800 bg-slate-950 p-3">
                    <div className="text-sm font-black text-slate-100">{item.title ?? item.requiredAction ?? item.id}</div>
                    <div className="mt-1 text-xs text-slate-500">{item.owner ?? "--"} / {item.severity ?? "--"} / {item.status ?? "--"}</div>
                  </div>
                ))
              ) : (
                <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs text-slate-500">No remediation tasks returned.</div>
              )}
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="text-[10px] font-black uppercase tracking-widest text-teal-300">Supervised actions</div>
            <div className="mt-3 grid gap-2">
              {supervisedActions.length ? (
                supervisedActions.slice(0, 6).map((item) => (
                  <div key={item.action_id} className="rounded border border-slate-800 bg-slate-950 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="truncate text-sm font-black text-slate-100">{item.title ?? item.action_id}</div>
                      <StatusPill value={item.policy_status} />
                    </div>
                    <div className="mt-1 text-xs text-slate-500">{item.owner ?? "--"} / {item.park_action?.target ?? "--"}</div>
                  </div>
                ))
              ) : (
                <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs text-slate-500">No supervised actions returned.</div>
              )}
            </div>
          </div>
        </section>

        {careCases.length > 0 && (
          <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="text-[10px] font-black uppercase tracking-widest text-violet-300">Customer care cases</div>
            <div className="mt-3 grid gap-2 md:grid-cols-3">
              {careCases.slice(0, 6).map((item) => (
                <div key={item.id} className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="text-sm font-black text-slate-100">{item.reason ?? item.id}</div>
                  <div className="mt-1 text-xs text-slate-500">{item.severity ?? "--"} / {item.status ?? "--"} / {item.safeAudience ?? "--"}</div>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
