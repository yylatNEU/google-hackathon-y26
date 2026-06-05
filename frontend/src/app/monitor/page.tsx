"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchParkPulseApi } from "@/lib/api";

type MonitorData = {
  monitoring_id?: string;
  created_at?: string;
  mode?: string;
  status?: string;
  overall_status?: string;
  summary?: {
    action_count?: number;
    review_count?: number;
    blocked_count?: number;
    policy_book_count?: number;
    gcp_trace_eval_ready?: boolean;
    arize_ready?: boolean;
    overall_eval_score?: number;
    needs_human_approval?: boolean;
  };
  gcp_trace_eval?: {
    status?: string;
    project?: string;
    dataset?: string;
    trace_lookup_query?: string;
    trace_url?: string;
    dimensions?: string[];
  };
  arize_monitor?: {
    status?: string;
    project_name?: string;
    trace_lookup_query?: string;
    trace_url?: string;
    dimensions?: string[];
  };
  policy_index?: {
    policy_book_id?: string;
    version?: string;
    active_policy_books?: string[];
    absolute_prohibitions?: string[];
  };
  policy_integrity?: {
    status?: string;
    issues?: string[];
    policy_ref_count?: number;
  };
  runtime_governance?: {
    decision_ledger?: Array<{
      id?: string;
      createdAt?: string;
      title?: string;
      gateStatus?: string;
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
  };
  supervised_actions?: Array<{
    action_id?: string;
    title?: string;
    owner?: string;
    policy_status?: string;
    park_action?: { target?: string; action?: string };
  }>;
  deep_monitoring?: { status?: string; error?: string };
};

type CaseRow = {
  id?: string;
  title?: string;
  domain?: string;
  severity?: string;
  quality?: { status?: string; score?: number };
  priority?: { rank?: number; score?: number; rationale?: string };
  governance?: {
    allowedSurface?: string;
    blockerClasses?: string[];
    nextOwnerAction?: string;
  };
  productionEvidence?: {
    state?: string;
    feedCount?: number;
    packetHash?: string;
  };
};

type CaseIndex = {
  status?: string;
  summary?: { caseCount?: number; productionReady?: boolean };
  rows?: CaseRow[];
};

type AgentOpsItem = {
  id?: string;
  timestamp?: string;
  status?: string;
  mode?: string;
  source?: string;
  scenarioName?: string;
  summary?: string;
  selectedAction?: string;
  gate?: string;
  evalScore?: number | null;
  evalDimensions?: Array<{ label?: string; score?: number; detail?: string }>;
  failureReasons?: string[];
  dispatchCount?: number;
  receiverActions?: string[];
  toolCalls?: Array<{ tool?: string; status?: string; agent?: string | null }>;
  traceEvents?: unknown[];
  traceId?: string | null;
  signature?: string;
};

type AgentOpsLedger = {
  status?: string;
  count?: number;
  items?: AgentOpsItem[];
};

type ReviewLedger = {
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
    priority?: string;
    owner?: string;
    reason?: string;
    training_effect?: string;
    event?: { source?: string; signal_type?: string };
    disposition?: { decision?: string };
  }>;
  open_reviews?: ReviewLedger["rows"];
  readiness_issues?: string[];
  authorization?: { reason?: string };
};

type PolicyDoctrine = {
  policy_book_count?: number;
  action_case_count?: number;
  action_primitive_count?: number;
  action_cases?: Array<{
    id?: string;
    title?: string;
    triggers?: string[];
    state_signals?: string[];
    policy_refs?: string[];
    recommended_primitives?: string[];
    action_plan?: string[];
    blocked_actions?: string[];
    success_metric?: string;
    rollback_condition?: string;
  }>;
  policy_refs?: Array<{
    policy_ref?: string;
    policy_book_id?: string;
    title?: string;
    summary?: string;
    severity?: string;
  }>;
};

type ApiRequestInit = RequestInit & { timeoutMs?: number };
type PolicyRefRow = NonNullable<PolicyDoctrine["policy_refs"]>[number];

function fmt(value?: string | number | boolean | null) {
  if (value === undefined || value === null || value === "") return "--";
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value).replaceAll("_", " ");
}

function score(value?: number | null, max = 100) {
  if (typeof value !== "number") return "--";
  const normalized = max === 1 ? value * 100 : value;
  return `${Math.round(normalized)}/100`;
}

function compact(items?: Array<string | undefined>, limit = 3) {
  const values = (items ?? []).filter(Boolean) as string[];
  if (!values.length) return "--";
  return `${values.slice(0, limit).join(" / ")}${values.length > limit ? ` +${values.length - limit}` : ""}`;
}

function toneClass(value?: string) {
  const lower = (value ?? "").toLowerCase();
  if (lower.includes("block") || lower.includes("critical") || lower.includes("fail")) return "border-red-400/40 bg-red-950/25 text-red-100";
  if (lower.includes("review") || lower.includes("degraded") || lower.includes("hold") || lower.includes("warning")) return "border-amber-400/40 bg-amber-950/20 text-amber-100";
  if (lower.includes("ready") || lower.includes("clear") || lower.includes("ok") || lower.includes("complete")) return "border-emerald-400/35 bg-emerald-950/20 text-emerald-100";
  return "border-slate-700 bg-slate-950 text-slate-300";
}

function StatusPill({ value }: { value?: string }) {
  return <span className={`rounded border px-2 py-1 text-[10px] font-black uppercase tracking-normal ${toneClass(value)}`}>{fmt(value)}</span>;
}

async function readJson<T>(path: string, init?: ApiRequestInit): Promise<T | null> {
  try {
    const response = await fetchParkPulseApi(path, init);
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

export default function MonitorPage() {
  const [monitor, setMonitor] = useState<MonitorData | null>(null);
  const [cases, setCases] = useState<CaseIndex | null>(null);
  const [agentOps, setAgentOps] = useState<AgentOpsLedger | null>(null);
  const [reviewLedger, setReviewLedger] = useState<ReviewLedger | null>(null);
  const [policyDoctrine, setPolicyDoctrine] = useState<PolicyDoctrine | null>(null);
  const [selectedCaseId, setSelectedCaseId] = useState("");
  const [selectedReceiptId, setSelectedReceiptId] = useState("");
  const [policyQuery, setPolicyQuery] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isDeepLoading, setIsDeepLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadSecondaryEvidence = useCallback(async () => {
    const [nextAgentOps, nextReviewLedger] = await Promise.all([
      readJson<AgentOpsLedger>("/api/park/agent-ops-ledger?limit=30", { timeoutMs: 5000 }),
      readJson<ReviewLedger>("/api/park/review-training-ledger?limit=80", { headers: { "x-parkpulse-role": "ops_team" }, timeoutMs: 5000 }),
    ]);
    if (nextAgentOps) setAgentOps(nextAgentOps);
    if (nextReviewLedger) setReviewLedger(nextReviewLedger);
  }, []);

  const loadWorkspace = useCallback(async (depth: "summary" | "deep" = "summary") => {
    setIsLoading(true);
    setError(null);
    const monitorPath = depth === "deep" ? "/api/park/agent-monitoring/deep" : "/api/park/agent-monitoring";
    try {
      const [nextMonitor, nextCases, nextPolicyDoctrine] = await Promise.all([
        readJson<MonitorData>(monitorPath, { timeoutMs: depth === "deep" ? 15000 : 8000 }),
        readJson<CaseIndex>("/api/park/cases", { timeoutMs: 8000 }),
        readJson<PolicyDoctrine>("/api/park/policy-doctrine", { timeoutMs: 5000 }),
      ]);
      setMonitor(nextMonitor);
      setCases(nextCases);
      setPolicyDoctrine(nextPolicyDoctrine);
      if (!nextMonitor && !nextCases && !nextPolicyDoctrine) setError("Monitor evidence APIs did not return usable payloads.");
      void loadSecondaryEvidence();
    } finally {
      setIsLoading(false);
    }
  }, [loadSecondaryEvidence]);

  const loadDeepMonitor = useCallback(async () => {
    setIsDeepLoading(true);
    try {
      const nextMonitor = await readJson<MonitorData>("/api/park/agent-monitoring/deep", { timeoutMs: 15000 });
      if (nextMonitor) setMonitor(nextMonitor);
    } finally {
      setIsDeepLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadWorkspace("summary");
  }, [loadWorkspace]);

  const caseRows = cases?.rows ?? [];
  const receipts = agentOps?.items ?? [];
  const selectedCase = useMemo(
    () => caseRows.find((item) => item.id === selectedCaseId) ?? caseRows[0],
    [caseRows, selectedCaseId],
  );
  const selectedReceipt = useMemo(
    () => receipts.find((item) => item.id === selectedReceiptId) ?? receipts[0],
    [receipts, selectedReceiptId],
  );

  const reviewRows = reviewLedger?.open_reviews ?? reviewLedger?.rows ?? [];
  const governanceReviews = [
    ...(monitor?.runtime_governance?.decision_ledger ?? []).map((item) => ({
      id: item.id,
      title: item.title ?? item.id,
      status: item.gateStatus,
      owner: "policy gate",
      detail: compact(item.policyFindings),
    })),
    ...(monitor?.runtime_governance?.remediation_tasks ?? []).map((item) => ({
      id: item.id,
      title: item.title ?? item.requiredAction ?? item.id,
      status: item.status,
      owner: item.owner,
      detail: compact(item.policyFindings) || item.severity,
    })),
    ...(monitor?.supervised_actions ?? []).map((item) => ({
      id: item.action_id,
      title: item.title ?? item.action_id,
      status: item.policy_status,
      owner: item.owner,
      detail: item.park_action?.target,
    })),
    ...(monitor?.runtime_governance?.customer_care_cases ?? []).map((item) => ({
      id: item.id,
      title: item.reason ?? item.id,
      status: item.status,
      owner: item.safeAudience,
      detail: item.severity,
    })),
  ];

  const doctrine = policyDoctrine;
  const policyCases = doctrine?.action_cases ?? [];
  const policyRefs = doctrine?.policy_refs ?? [];
  const filteredPolicyCases = policyCases.filter((item) => {
    const query = policyQuery.trim().toLowerCase();
    if (!query) return true;
    return [item.id, item.title, ...(item.triggers ?? []), ...(item.policy_refs ?? [])]
      .filter(Boolean)
      .join(" ")
      .toLowerCase()
      .includes(query);
  });
  const filteredPolicyRefs = policyRefs.filter((item) => {
    const query = policyQuery.trim().toLowerCase();
    if (!query) return true;
    return [item.policy_ref, item.policy_book_id, item.title, item.summary, item.severity]
      .filter(Boolean)
      .join(" ")
      .toLowerCase()
      .includes(query);
  });

  const averageCaseScore = caseRows.length
    ? caseRows.reduce((total, item) => total + (item.quality?.score ?? 0), 0) / caseRows.length
    : undefined;
  const traceCount = receipts.filter((item) => item.traceId || item.signature || item.toolCalls?.length).length;
  const openReviewCount = reviewLedger?.summary?.open_count ?? reviewRows.filter((item) => item?.status !== "closed").length ?? governanceReviews.length;

  return (
    <main className="min-h-screen bg-slate-950 px-4 py-5 font-sans text-slate-200 lg:px-8">
      <div className="mx-auto max-w-[1500px] space-y-5">
        <header className="border-b border-slate-800 pb-5">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Runtime monitor</div>
              <h1 className="mt-2 text-3xl font-black tracking-normal text-slate-100 lg:text-4xl">Evidence workspace</h1>
              <p className="mt-3 max-w-4xl text-sm leading-relaxed text-slate-400">
                Check case eval scores, trace records, human review sessions, and policy doctrine without leaving the operating context.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => void loadWorkspace("summary")}
                disabled={isLoading}
                className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-100 disabled:opacity-50"
              >
                {isLoading ? "Refreshing" : "Refresh"}
              </button>
              <button
                type="button"
                onClick={() => void loadDeepMonitor()}
                disabled={isDeepLoading}
                className="rounded border border-cyan-300 bg-cyan-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-cyan-200 disabled:opacity-50"
              >
                {isDeepLoading ? "Loading trace" : "Load trace links"}
              </button>
              <a href="/" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-100">
                Operating loop
              </a>
            </div>
          </div>
        </header>

        {error ? <section className="rounded border border-amber-400/30 bg-amber-950/15 p-3 text-sm font-bold text-amber-100">Runtime debug: {error}</section> : null}

        <section className="grid gap-2 md:grid-cols-6">
          {[
            ["Cases", String((cases?.summary?.caseCount ?? caseRows.length) || "--")],
            ["Avg eval", score(averageCaseScore, 1)],
            ["Receipts", String(receipts.length || "--")],
            ["Traces", String(traceCount || "--")],
            ["Review", String(openReviewCount || "--")],
            ["Policies", String(doctrine?.policy_book_count ?? monitor?.summary?.policy_book_count ?? "--")],
          ].map(([label, value]) => (
            <div key={label} className="rounded border border-slate-800 bg-slate-900 px-3 py-2">
              <div className="text-[9px] font-black uppercase tracking-widest text-slate-500">{label}</div>
              <div className="mt-1 truncate text-sm font-black text-cyan-100">{value}</div>
            </div>
          ))}
        </section>

        <section className="grid gap-5 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-emerald-300">Case evals</div>
                <h2 className="mt-1 text-xl font-black text-slate-100">Operational cases ranked by eval score</h2>
              </div>
              <StatusPill value={cases?.status ?? monitor?.overall_status} />
            </div>
            <div className="mt-4 overflow-hidden rounded border border-slate-800">
              <div className="grid grid-cols-[1fr_5rem_5rem_5rem] gap-2 border-b border-slate-800 bg-slate-950 px-3 py-2 text-[10px] font-black uppercase tracking-widest text-slate-500">
                <div>Case</div>
                <div>Eval</div>
                <div>Priority</div>
                <div>Gate</div>
              </div>
              <div className="max-h-[420px] overflow-auto">
                {caseRows.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setSelectedCaseId(item.id ?? "")}
                    className={`grid w-full grid-cols-[1fr_5rem_5rem_5rem] gap-2 border-b border-slate-800 px-3 py-3 text-left text-xs transition hover:bg-slate-800/60 ${
                      selectedCase?.id === item.id ? "bg-cyan-950/30" : "bg-slate-900"
                    }`}
                  >
                    <div className="min-w-0">
                      <div className="truncate font-black text-slate-100">{item.title ?? item.id}</div>
                      <div className="mt-1 truncate text-[10px] font-bold text-slate-500">{item.id}</div>
                    </div>
                    <div className="font-black text-cyan-100">{score(item.quality?.score, 1)}</div>
                    <div className="font-black text-slate-300">{item.priority?.score ?? "--"}</div>
                    <div><StatusPill value={item.severity} /></div>
                  </button>
                ))}
                {!caseRows.length ? <div className="p-4 text-sm text-slate-500">No case eval rows returned.</div> : null}
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Selected case</div>
                <h2 className="mt-1 text-xl font-black text-slate-100">{selectedCase?.title ?? "No case selected"}</h2>
              </div>
              <StatusPill value={selectedCase?.governance?.allowedSurface ?? selectedCase?.severity} />
            </div>
            <div className="mt-4 grid gap-2 md:grid-cols-4">
              {[
                ["Eval", score(selectedCase?.quality?.score, 1)],
                ["Quality", fmt(selectedCase?.quality?.status)],
                ["Feeds", fmt(selectedCase?.productionEvidence?.feedCount)],
                ["Rank", fmt(selectedCase?.priority?.rank)],
              ].map(([label, value]) => (
                <div key={label} className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="text-[9px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                  <div className="mt-1 truncate text-sm font-black text-slate-100">{value}</div>
                </div>
              ))}
            </div>
            <div className="mt-4 grid gap-3 lg:grid-cols-2">
              <div className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Next owner action</div>
                <p className="mt-2 text-sm leading-relaxed text-slate-300">{selectedCase?.governance?.nextOwnerAction ?? "No owner action returned."}</p>
              </div>
              <div className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Production evidence</div>
                <p className="mt-2 text-sm leading-relaxed text-slate-300">
                  {selectedCase?.productionEvidence?.state ?? "--"} / {selectedCase?.productionEvidence?.packetHash ?? "packet missing"}
                </p>
              </div>
            </div>
          </div>
        </section>

        <section className="grid gap-5 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-violet-300">Trace records</div>
                <h2 className="mt-1 text-xl font-black text-slate-100">Receipts and tool traces</h2>
              </div>
              <StatusPill value={agentOps?.status} />
            </div>
            <div className="mt-4 grid max-h-[430px] gap-2 overflow-auto">
              {receipts.slice(0, 18).map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setSelectedReceiptId(item.id ?? "")}
                  className={`rounded border p-3 text-left transition hover:border-violet-300 ${
                    selectedReceipt?.id === item.id ? "border-violet-300 bg-violet-950/30" : "border-slate-800 bg-slate-950"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="truncate text-sm font-black text-slate-100">{item.summary ?? item.scenarioName ?? item.id}</div>
                    <StatusPill value={item.gate ?? item.status} />
                  </div>
                  <div className="mt-2 grid grid-cols-4 gap-2 text-[10px] font-bold text-slate-500">
                    <div>{score(item.evalScore)}</div>
                    <div>{fmt(item.mode)}</div>
                    <div>{item.toolCalls?.length ?? 0} tools</div>
                    <div>{item.dispatchCount ?? 0} dispatches</div>
                  </div>
                </button>
              ))}
              {!receipts.length ? <div className="rounded border border-slate-800 bg-slate-950 p-3 text-sm text-slate-500">No trace receipts returned.</div> : null}
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-violet-300">Selected trace</div>
                <h2 className="mt-1 text-xl font-black text-slate-100">{selectedReceipt?.summary ?? selectedReceipt?.id ?? "No receipt selected"}</h2>
              </div>
              <div className="text-right text-[10px] font-bold text-slate-500">{selectedReceipt?.timestamp ?? monitor?.created_at ?? "--"}</div>
            </div>
            <div className="mt-4 grid gap-2 md:grid-cols-5">
              {[
                ["Eval", score(selectedReceipt?.evalScore ?? monitor?.summary?.overall_eval_score)],
                ["Gate", fmt(selectedReceipt?.gate ?? monitor?.overall_status)],
                ["Trace", selectedReceipt?.traceId ?? selectedReceipt?.signature ?? monitor?.gcp_trace_eval?.trace_lookup_query ?? "--"],
                ["GCP", fmt(monitor?.gcp_trace_eval?.status)],
                ["Arize", fmt(monitor?.arize_monitor?.status)],
              ].map(([label, value]) => (
                <div key={label} className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="text-[9px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                  <div className="mt-1 truncate text-xs font-black text-slate-100">{value}</div>
                </div>
              ))}
            </div>
            <div className="mt-4 grid gap-3 lg:grid-cols-2">
              <div className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Tool calls</div>
                <div className="mt-2 grid gap-1">
                  {(selectedReceipt?.toolCalls ?? []).slice(0, 9).map((call, index) => (
                    <div key={`${call.tool}-${index}`} className="grid grid-cols-[1fr_auto] gap-2 rounded bg-slate-900 px-2 py-1 text-xs">
                      <span className="truncate font-bold text-slate-200">{fmt(call.tool)}</span>
                      <span className="text-slate-500">{fmt(call.status)}</span>
                    </div>
                  ))}
                  {!(selectedReceipt?.toolCalls ?? []).length ? <div className="text-xs text-slate-500">No tool trace attached.</div> : null}
                </div>
              </div>
              <div className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Trace links</div>
                <div className="mt-2 space-y-2 text-xs">
                  {monitor?.gcp_trace_eval?.trace_url ? <a className="block truncate font-bold text-cyan-200 hover:text-cyan-100" href={monitor.gcp_trace_eval.trace_url}>GCP trace: {monitor.gcp_trace_eval.project}</a> : <div className="text-slate-500">GCP trace link not loaded.</div>}
                  {monitor?.arize_monitor?.trace_url ? <a className="block truncate font-bold text-cyan-200 hover:text-cyan-100" href={monitor.arize_monitor.trace_url}>Arize trace: {monitor.arize_monitor.project_name}</a> : <div className="text-slate-500">Arize trace link not loaded.</div>}
                  {monitor?.deep_monitoring?.status === "unavailable" ? <div className="rounded border border-amber-400/30 bg-amber-950/20 p-2 font-bold text-amber-100">{monitor.deep_monitoring.error}</div> : null}
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="grid gap-5 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-amber-300">Human review</div>
                <h2 className="mt-1 text-xl font-black text-slate-100">Review sessions and holds</h2>
              </div>
              <StatusPill value={reviewLedger?.status ?? monitor?.overall_status} />
            </div>
            {reviewLedger?.readiness_issues?.length ? (
              <div className="mt-3 rounded border border-amber-400/30 bg-amber-950/15 p-3 text-xs font-bold text-amber-100">
                {reviewLedger.authorization?.reason ?? reviewLedger.readiness_issues[0]}
              </div>
            ) : null}
            <div className="mt-4 grid gap-2">
              {reviewRows.slice(0, 8).map((item) => (
                <div key={item?.id} className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="truncate text-sm font-black text-slate-100">{item?.reason ?? item?.id}</div>
                    <StatusPill value={item?.status ?? item?.disposition?.decision} />
                  </div>
                  <div className="mt-1 text-xs text-slate-500">{item?.owner ?? "--"} / {item?.priority ?? "--"} / {item?.event?.source ?? "--"}</div>
                </div>
              ))}
              {!reviewRows.length ? <div className="rounded border border-slate-800 bg-slate-950 p-3 text-sm text-slate-500">No signed review ledger rows available.</div> : null}
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="text-[10px] font-black uppercase tracking-widest text-amber-300">Governance review queue</div>
            <div className="mt-3 grid gap-2 md:grid-cols-2">
              {governanceReviews.slice(0, 10).map((item) => (
                <div key={item.id} className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="truncate text-sm font-black text-slate-100">{item.title}</div>
                    <StatusPill value={item.status} />
                  </div>
                  <div className="mt-2 line-clamp-2 text-xs leading-relaxed text-slate-500">{item.owner ?? "--"} / {item.detail ?? "--"}</div>
                </div>
              ))}
              {!governanceReviews.length ? <div className="rounded border border-slate-800 bg-slate-950 p-3 text-sm text-slate-500 md:col-span-2">No governance review sessions returned.</div> : null}
            </div>
          </div>
        </section>

        <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-lime-300">Policy lookup</div>
              <h2 className="mt-1 text-xl font-black text-slate-100">Doctrine, refs, blocked actions</h2>
            </div>
            <input
              value={policyQuery}
              onChange={(event) => setPolicyQuery(event.target.value)}
              placeholder="Search policy refs, cases, triggers"
              className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm font-bold text-slate-100 outline-none transition placeholder:text-slate-600 focus:border-lime-300 lg:w-96"
            />
          </div>
          <div className="mt-4 grid gap-5 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
            <div className="grid max-h-[460px] gap-2 overflow-auto">
              {filteredPolicyCases.slice(0, 18).map((item) => (
                <div key={item.id} className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="truncate text-sm font-black text-slate-100">{item.title ?? item.id}</div>
                    <div className="text-[10px] font-black uppercase tracking-widest text-lime-200">{compact(item.policy_refs, 2)}</div>
                  </div>
                  <div className="mt-2 text-xs leading-relaxed text-slate-500">Triggers: {compact(item.triggers, 4)}</div>
                  <div className="mt-2 grid gap-2 md:grid-cols-2">
                    <div className="rounded bg-slate-900 p-2 text-xs text-slate-300">Plan: {compact(item.action_plan, 2)}</div>
                    <div className="rounded bg-slate-900 p-2 text-xs text-amber-100">Blocked: {compact(item.blocked_actions, 2)}</div>
                  </div>
                </div>
              ))}
              {!filteredPolicyCases.length ? <div className="rounded border border-slate-800 bg-slate-950 p-3 text-sm text-slate-500">No policy cases match.</div> : null}
            </div>
            <div className="rounded border border-slate-800 bg-slate-950 p-3">
              <div className="grid gap-2 md:grid-cols-3">
                {[
                  ["Books", fmt(doctrine?.policy_book_count ?? monitor?.summary?.policy_book_count)],
                  ["Cases", fmt(doctrine?.action_case_count ?? policyCases.length)],
                  ["Refs", fmt(monitor?.policy_integrity?.policy_ref_count ?? policyRefs.length)],
                ].map(([label, value]) => (
                  <div key={label} className="rounded bg-slate-900 p-2">
                    <div className="text-[9px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                    <div className="mt-1 text-sm font-black text-slate-100">{value}</div>
                  </div>
                ))}
              </div>
              <div className="mt-3 text-xs leading-relaxed text-slate-400">
                Integrity: <span className="font-black text-slate-200">{fmt(monitor?.policy_integrity?.status)}</span>
              </div>
              <div className="mt-3 grid gap-2">
                {(filteredPolicyRefs.length ? filteredPolicyRefs : (monitor?.policy_index?.absolute_prohibitions ?? []).map<PolicyRefRow>((item) => ({ policy_ref: item, summary: "Absolute prohibition" }))).slice(0, 12).map((item) => (
                  <div key={`${item.policy_ref}-${item.title}`} className="rounded border border-slate-800 bg-slate-900 p-2 text-xs">
                    <div className="font-black text-lime-100">{item.policy_ref ?? item.policy_book_id ?? item.title}</div>
                    <div className="mt-1 line-clamp-2 text-slate-500">{item.summary ?? item.title ?? "--"}</div>
                  </div>
                ))}
                {monitor?.policy_integrity?.issues?.slice(0, 3).map((item) => (
                  <div key={item} className="rounded border border-amber-400/30 bg-amber-950/15 p-2 text-xs font-bold text-amber-100">{item}</div>
                ))}
              </div>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
