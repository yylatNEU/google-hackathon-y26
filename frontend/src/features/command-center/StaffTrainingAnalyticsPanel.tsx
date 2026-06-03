"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchParkPulseApi } from "@/lib/api";

type TrainingAnalytics = {
  status?: string;
  session_count?: number;
  scenario_summary?: Array<{
    scenario_id?: string;
    title?: string;
    session_count?: number;
    average_overall?: number;
    critical_miss_count?: number;
  }>;
  weakest_dimensions?: Array<{ dimension?: string; average?: number }>;
  boundary?: string;
};

type TrainingPolicyPack = {
  status?: string;
  scenario_count?: number;
  critical_scenarios?: string[];
  scoring_contract?: {
    authority?: string;
    llm_controls_score?: boolean;
    fatal_miss_caps_score?: boolean;
  };
  data_boundary?: {
    uses_generated_data?: boolean;
    feeds_actual_reward_model?: boolean;
    writes_live_dispatch?: boolean;
  };
  manager_review?: {
    minimum_live_shadowing_gate?: string;
  };
};

type TrainingReadiness = {
  trainee_count?: number;
  status_counts?: Record<string, number>;
  readiness?: Array<{
    assignment_id?: string;
    trainee_name?: string;
    staff_role?: string;
    status?: string;
    average_score?: number | null;
    critical_miss_count?: number;
    review_hold_count?: number;
  }>;
};

const staffTrainingRequestTimeoutMs = 16000;

function fmt(value?: string | number | boolean | null) {
  if (value === undefined || value === null || value === "") return "--";
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value).replaceAll("_", " ");
}

function dimensionLabel(value?: string) {
  const labels: Record<string, string> = {
    empathy: "Empathy",
    policy_correctness: "Policy",
    escalation_decision: "Escalation",
    clarity: "Clarity",
    safety_awareness: "Safety",
    de_escalation: "De-escalation",
    brand_tone: "Brand tone",
  };
  return labels[value ?? ""] ?? fmt(value);
}

function scoreTone(value?: number) {
  const score = Number(value ?? 0);
  if (score >= 80) return "text-emerald-200";
  if (score >= 60) return "text-amber-200";
  return "text-rose-200";
}

export function StaffTrainingAnalyticsPanel() {
  const [analytics, setAnalytics] = useState<TrainingAnalytics | null>(null);
  const [policyPack, setPolicyPack] = useState<TrainingPolicyPack | null>(null);
  const [readiness, setReadiness] = useState<TrainingReadiness | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  const weakest = analytics?.weakest_dimensions?.[0];
  const reviewHoldCount = (readiness?.readiness ?? []).reduce((total, row) => total + Number(row.review_hold_count ?? 0), 0);
  const highestRiskScenario = useMemo(() => {
    const rows = analytics?.scenario_summary ?? [];
    return [...rows].sort((left, right) => Number(right.critical_miss_count ?? 0) - Number(left.critical_miss_count ?? 0))[0];
  }, [analytics?.scenario_summary]);

  async function refresh() {
    setIsLoading(true);
    setError("");
    try {
      const analyticsResponse = await fetchParkPulseApi("/api/park/staff-training/analytics?limit=160", {
        headers: { "x-parkpulse-role": "ops_team" },
        timeoutMs: staffTrainingRequestTimeoutMs,
      });
      const policyResponse = await fetchParkPulseApi("/api/park/staff-training/policy-pack", {
        headers: { "x-parkpulse-role": "ops_team" },
        timeoutMs: staffTrainingRequestTimeoutMs,
      });
      const readinessResponse = await fetchParkPulseApi("/api/park/staff-training/readiness?limit=160", {
        headers: { "x-parkpulse-role": "ops_team" },
        timeoutMs: staffTrainingRequestTimeoutMs,
      });
      setAnalytics((await analyticsResponse.json()) as TrainingAnalytics);
      setPolicyPack((await policyResponse.json()) as TrainingPolicyPack);
      setReadiness((await readinessResponse.json()) as TrainingReadiness);
    } catch (nextError) {
      const message = nextError instanceof Error ? nextError.message : "Unable to read staff training analytics.";
      setError(
        /ParkPulse API did not respond/i.test(message)
          ? "Training analytics are still warming. Retry from this panel if metrics stay empty."
          : message,
      );
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      void refresh();
    }, 800);
    return () => window.clearTimeout(timeoutId);
  }, []);

  return (
    <section className="rounded-lg border border-teal-300/20 bg-slate-950 p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="text-[10px] font-black uppercase tracking-widest text-teal-300">Staff roleplay trainer</div>
          <h2 className="mt-1 text-xl font-black text-slate-100">Training readiness and weak spots</h2>
          <p className="mt-2 max-w-4xl text-sm leading-relaxed text-slate-400">
            Simulated guest-service practice is tracked separately from live operations reward learning.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <a href="/staff-training" className="rounded border border-teal-300 bg-teal-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-teal-200">
            Open trainer
          </a>
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={isLoading}
            className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-teal-300 disabled:opacity-50"
          >
            {isLoading ? "Reading" : "Refresh"}
          </button>
        </div>
      </div>

      {error && <div className="mt-3 rounded border border-amber-300/40 bg-amber-300/10 p-3 text-sm font-bold text-amber-100">{error}</div>}

      <div className="mt-4 grid gap-3 md:grid-cols-4">
        {[
          ["Sessions", analytics?.session_count ?? 0],
          ["Weakest dimension", dimensionLabel(weakest?.dimension)],
          ["High-risk scenario", highestRiskScenario?.title ?? "--"],
          ["Ready staff", readiness?.status_counts?.ready_for_shadowing ?? 0],
        ].map(([label, value]) => (
          <div key={label} className="rounded border border-slate-800 bg-slate-900 p-3">
            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
            <div className="mt-1 truncate text-lg font-black text-slate-100">{value}</div>
          </div>
        ))}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
        <div className="rounded border border-slate-800 bg-slate-900 p-3">
          <div className="flex items-center justify-between gap-2">
            <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">Scenario performance</div>
            <div className="text-xs font-bold text-slate-500">{analytics?.status ?? "not loaded"}</div>
          </div>
          <div className="mt-3 space-y-2">
            {(analytics?.scenario_summary ?? []).slice(0, 6).map((row) => (
              <div key={row.scenario_id} className="grid grid-cols-[1fr_auto_auto] gap-2 rounded border border-slate-800 bg-slate-950 px-3 py-2 text-xs">
                <div className="min-w-0">
                  <div className="truncate font-black text-slate-100">{row.title ?? fmt(row.scenario_id)}</div>
                  <div className="mt-1 text-slate-500">{row.session_count ?? 0} sessions</div>
                </div>
                <div className={`font-black ${scoreTone(row.average_overall)}`}>{row.average_overall ?? "--"}</div>
                <div className={Number(row.critical_miss_count ?? 0) ? "font-black text-rose-200" : "font-bold text-slate-500"}>
                  {row.critical_miss_count ?? 0} misses
                </div>
              </div>
            ))}
            {!(analytics?.scenario_summary ?? []).length && (
              <div className="rounded border border-slate-800 bg-slate-950 p-3 text-sm font-bold text-slate-500">No finished staff roleplay sessions yet.</div>
            )}
          </div>
        </div>

        <div className="rounded border border-slate-800 bg-slate-900 p-3">
          <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">Governance contract</div>
          <div className="mt-3 grid grid-cols-2 gap-2 text-xs font-bold text-slate-300">
            <div className="rounded border border-slate-800 bg-slate-950 p-2">Scoring: {fmt(policyPack?.scoring_contract?.authority)}</div>
            <div className="rounded border border-slate-800 bg-slate-950 p-2">LLM scores: {fmt(policyPack?.scoring_contract?.llm_controls_score)}</div>
            <div className="rounded border border-slate-800 bg-slate-950 p-2">Reward feed: {fmt(policyPack?.data_boundary?.feeds_actual_reward_model)}</div>
            <div className="rounded border border-slate-800 bg-slate-950 p-2">Live dispatch: {fmt(policyPack?.data_boundary?.writes_live_dispatch)}</div>
          </div>
          <p className="mt-3 text-sm font-semibold leading-relaxed text-slate-400">
            {policyPack?.manager_review?.minimum_live_shadowing_gate ?? "No critical miss and passing score required before live shadowing."}
          </p>
        </div>

        <div className="rounded border border-slate-800 bg-slate-900 p-3 lg:col-span-2">
          <div className="flex items-center justify-between gap-2">
            <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">Training assignments</div>
            <div className="text-xs font-bold text-slate-500">{readiness?.trainee_count ?? 0} staff</div>
          </div>
          <div className="mt-3 grid gap-2 md:grid-cols-3">
            {[
              ["Not started", readiness?.status_counts?.not_started ?? 0],
              ["Needs coaching", readiness?.status_counts?.needs_coaching ?? 0],
              ["Review holds", reviewHoldCount],
            ].map(([label, value]) => (
              <div key={label} className="rounded border border-slate-800 bg-slate-950 p-2">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                <div className="mt-1 text-lg font-black text-slate-100">{value}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
