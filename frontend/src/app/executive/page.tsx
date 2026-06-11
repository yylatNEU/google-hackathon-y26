"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParkPulseState } from "@/hooks/useParkPulseState";
import { fetchParkPulseApi } from "@/lib/api";

type AgentMode = "auto" | "scan" | "react" | "proact";

type EnterpriseDomain = {
  id?: string;
  label?: string;
  score?: number;
  status?: string;
  agent?: string;
  current?: string;
  target?: string;
  recommendedMove?: string;
  ticketsOpen?: number;
  leadingSignals?: string[];
};

type BacklogIssue = {
  id?: string;
  executiveDomain?: string;
  domain?: string;
  title?: string;
  severity?: string;
  current?: string;
  target?: string;
  businessImpact?: string;
  recommendedNext?: string;
  evidence?: string[];
};

type BacklogPayload = {
  status?: string;
  unresolvedCount?: number;
  enterpriseDomains?: EnterpriseDomain[];
  enterpriseSummary?: {
    weakestDomain?: EnterpriseDomain;
    executiveQuestion?: string;
    answer?: string;
  };
  issues?: BacklogIssue[];
};

type IncidentTicket = {
  id?: string;
  source?: string;
  domain?: string;
  title?: string;
  severity?: string;
  status?: string;
  summary?: string;
  recommendedHumanCall?: string;
  evidence?: string[];
};

type IncidentPayload = {
  summary?: {
    ticketCount?: number;
    humanReviewCount?: number;
    topDomains?: Array<[string, number]>;
  };
  tickets?: IncidentTicket[];
  mongoPersistence?: {
    status?: string;
    mode?: string;
    connected?: boolean;
    ticketCount?: number;
    operatorBriefId?: string | null;
  };
};

type ExecutiveDayBrief = {
  status?: string;
  headline?: string;
  primaryIssue?: {
    title?: string;
    severity?: string;
    rootCause?: string;
    businessImpact?: string;
    recommendedDecision?: string;
    owner?: string;
    decisionDeadlineMinutes?: number;
    confidence?: number;
    selectionScore?: {
      total?: number;
      severityScore?: number;
      guestImpact?: number;
      safetyAccessRisk?: number;
      unresolvedAge?: number;
      confidence?: number;
    };
    selectionRationale?: string[];
  };
  recommendedDecision?: {
    action?: string;
    owner?: string;
    deadlineMinutes?: number;
    approveIf?: string[];
    holdIf?: string[];
    tradeoff?: string;
    confidence?: number;
  };
  daySummary?: {
    openedAt?: string;
    currentTime?: string;
    whatChanged?: string;
    unresolvedRisk?: string;
    watchNext?: string;
  };
  mitigations?: {
    attempted?: string[];
    observedEffect?: string;
    remainingGap?: string;
  };
  evidence?: Array<{ claim?: string; metric?: string; source?: string; id?: string; sourceId?: string; timestamp?: string }>;
  issueTimeline?: Array<{ phase?: string; label?: string; at?: string; detail?: string; source?: string; sourceId?: string }>;
  decisionAlternatives?: Array<{ id?: string; label?: string; expectedImpact?: string; risk?: string; tradeoff?: string; score?: number; recommended?: boolean }>;
  impactModel?: {
    guestMinutesAtRisk?: number;
    complaintEscalationRiskPct?: number;
    safetyAccessRiskPct?: number;
    revenueExposureUsd?: number;
    staffingLoadRiskPct?: number;
    confidencePct?: number;
  };
  learningMemory?: {
    status?: string;
    matchedCases?: number;
    latestLesson?: string;
    takeRatePriorPct?: number;
    nextBias?: string;
  };
  productStructure?: {
    executiveQuestion?: string;
    decisionThesis?: string;
    successMetric?: string;
    reviewCadence?: string;
    northStar?: string;
    workflowStages?: Array<{ stage?: string; question?: string; answer?: string; metric?: string; status?: string }>;
    ownerResponsibilities?: Array<{ owner?: string; role?: string; responsibility?: string; proofNeeded?: string }>;
    productGaps?: Array<{ gap?: string; whyItMatters?: string; nextBuild?: string }>;
  };
  evidenceRollup?: Array<{ label?: string; value?: number; detail?: string }>;
  charts?: {
    pressureCurve?: Array<{ label: string; expected?: number; controlled?: number; density?: number; operations?: number }>;
    driverBreakdown?: Array<{ label: string; value: number; max?: number }>;
    domainBreakdown?: Array<{ label: string; value: number; max?: number }>;
  };
  priorityQueue?: Array<{ id?: string; title?: string; severity?: string; detail?: string; selectionScore?: { total?: number } }>;
};

type RoleRoute = {
  selected_role?: string;
  why?: string;
  required_tools?: string[];
  policy_gates?: string[];
  expected_receipt?: string[];
};

type HumanRun = {
  status?: string;
  selected_role?: string;
  route?: RoleRoute;
  role_route?: RoleRoute;
  operator_response?: {
    headline?: string;
    summary?: string;
    next_step?: string;
  };
  run_telemetry?: {
    decision_id?: string;
    planner?: {
      runtime?: string;
      model?: string;
      selected_action?: { label?: string; target?: string; action?: string; owner?: string };
    };
    governance?: { allowed?: boolean; gate_status?: string; findings?: string[] };
    eval?: { scorecard?: { overall?: number; response_score?: number; policy_gate_status?: string; needs_human_approval?: boolean } };
    delivery?: {
      summary?: { total?: number; sent?: number; acknowledged?: number; pending_operator_approval?: number };
      dispatches?: Array<{
        id?: string;
        channel?: string;
        target?: string;
        status?: string;
        message?: string;
        payload?: { message?: string; task?: string; command?: string };
      }>;
    };
  };
  digital_twin_tools?: {
    tool_count?: number;
    tool_calls?: Array<{ tool?: string; capability?: string; status?: string; output?: unknown }>;
    summary?: { policy_gates?: string[]; receipt_artifacts?: string[] };
  };
  scan?: {
    top_risk?: string;
    confidence?: number;
    recommended_next_role?: string;
    signals?: Array<{ summary?: string; confidence?: number; risk_level?: string }>;
  };
};

type SignalIntake = {
  status?: string;
  signal?: {
    text?: string;
    source?: string;
    categories?: string[];
    risk_level?: string;
    confidence?: number;
    human_approval_required?: boolean;
    recommended_actions?: Array<{ owner?: string; action?: string; deadline_minutes?: number }>;
    missing_info?: string[];
  };
};

const AGENT_MODES: Array<{ id: AgentMode; label: string; detail: string }> = [
  { id: "auto", label: "Auto route", detail: "Runtime router chooses scan, react, or proact." },
  { id: "scan", label: "Scan", detail: "Classify live signals before planning." },
  { id: "react", label: "React", detail: "Respond to a known operator incident." },
  { id: "proact", label: "Proact", detail: "Forecast weak signals before escalation." },
];

function clamp(value: number, min = 0, max = 100) {
  return Math.max(min, Math.min(max, value));
}

function score(value?: number) {
  return typeof value === "number" ? `${Math.round(value)}/100` : "--";
}

function pct(value?: number) {
  return typeof value === "number" ? `${Math.round(value)}%` : "--";
}

function confidencePct(value?: number) {
  return typeof value === "number" ? `${Math.round(value * 100)}%` : "--";
}

function compactNumber(value?: number) {
  return typeof value === "number" ? Math.round(value).toLocaleString() : "--";
}

function signedNumber(value?: number) {
  if (typeof value !== "number") return "--";
  const rounded = Math.round(value);
  return rounded > 0 ? `+${rounded}` : String(rounded);
}

function formatMinuteOfDay(minuteOfDay: number) {
  const safeMinute = Math.max(0, Math.min(24 * 60 - 1, Math.round(minuteOfDay)));
  const hour = Math.floor(safeMinute / 60);
  const minute = safeMinute % 60;
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

function operatingDemandEstimate(minuteOfDay: number) {
  if (minuteOfDay < 9 * 60) return 0;
  if (minuteOfDay < 10 * 60) return 38 + ((minuteOfDay - 9 * 60) / 60) * 22;
  if (minuteOfDay < 12 * 60) return 62 + ((minuteOfDay - 10 * 60) / 120) * 20;
  if (minuteOfDay < 15 * 60) return 84 + Math.sin(((minuteOfDay - 12 * 60) / 180) * Math.PI) * 8;
  if (minuteOfDay < 18 * 60) return 80 + ((minuteOfDay - 15 * 60) / 180) * 10;
  if (minuteOfDay < 21 * 60) return 84 + Math.sin(((minuteOfDay - 18 * 60) / 180) * Math.PI) * 8;
  if (minuteOfDay < 23 * 60) return 76 - ((minuteOfDay - 21 * 60) / 120) * 18;
  return 0;
}

function dispatchMessage(dispatch: { message?: string; payload?: { message?: string; task?: string; command?: string } }) {
  return dispatch.message ?? dispatch.payload?.message ?? dispatch.payload?.task ?? dispatch.payload?.command ?? "Runtime payload body missing.";
}

function StatusPill({ value }: { value?: string }) {
  const lower = (value ?? "").toLowerCase();
  const tone = lower.includes("block") || lower.includes("critical") || lower.includes("high")
    ? "border-red-400/40 bg-red-950/25 text-red-100"
    : lower.includes("review") || lower.includes("degraded") || lower.includes("watch") || lower.includes("medium")
      ? "border-amber-400/40 bg-amber-950/20 text-amber-100"
      : "border-emerald-400/35 bg-emerald-950/20 text-emerald-100";
  return <span className={`rounded border px-2 py-1 text-[10px] font-black uppercase tracking-widest ${tone}`}>{value ?? "--"}</span>;
}

function MetricTile({ label, value, accent = "text-cyan-100" }: { label: string; value: string; accent?: string }) {
  return (
    <div className="rounded border border-slate-800 bg-slate-900 p-3">
      <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
      <div className={`mt-1 truncate text-sm font-black ${accent}`}>{value}</div>
    </div>
  );
}

function Gauge({ label, value, max = 100, suffix = "%", tone = "cyan" }: { label: string; value?: number; max?: number; suffix?: string; tone?: "cyan" | "emerald" | "amber" | "red" }) {
  const percent = typeof value === "number" ? clamp((value / max) * 100) : 0;
  const color = tone === "emerald" ? "#34d399" : tone === "amber" ? "#fbbf24" : tone === "red" ? "#f87171" : "#22d3ee";
  return (
    <div className="rounded border border-slate-800 bg-slate-950 p-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
          <div className="mt-2 text-lg font-black text-slate-100">{typeof value === "number" ? `${Math.round(value)}${suffix}` : "--"}</div>
        </div>
        <div className="grid h-16 w-16 place-items-center rounded-full" style={{ background: `conic-gradient(${color} ${percent}%, #1e293b ${percent}% 100%)` }}>
          <div className="grid h-11 w-11 place-items-center rounded-full bg-slate-950 text-[10px] font-black text-slate-300">{Math.round(percent)}%</div>
        </div>
      </div>
    </div>
  );
}

function BarChart({ rows, empty }: { rows: Array<{ label: string; value: number; max?: number; tone?: string }>; empty: string }) {
  if (!rows.length) {
    return <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs text-slate-500">{empty}</div>;
  }
  return (
    <div className="grid gap-3">
      {rows.map((row) => {
        const percent = clamp((row.value / (row.max ?? 100)) * 100);
        return (
          <div key={row.label} className="grid gap-1">
            <div className="flex items-center justify-between gap-3 text-xs">
              <span className="truncate font-black text-slate-200">{row.label}</span>
              <span className="font-mono text-slate-500">{Math.round(row.value)}</span>
            </div>
            <div className="h-2 overflow-hidden rounded bg-slate-800">
              <div className={`h-full rounded ${row.tone ?? "bg-cyan-300"}`} style={{ width: `${percent}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Sparkline({ values, label }: { values: number[]; label: string }) {
  const clean = values.filter((value) => Number.isFinite(value));
  const max = Math.max(...clean, 1);
  const points = clean
    .map((value, index) => {
      const x = clean.length === 1 ? 0 : (index / (clean.length - 1)) * 100;
      const y = 34 - (value / max) * 28;
      return `${x},${y}`;
    })
    .join(" ");
  return (
    <div className="rounded border border-slate-800 bg-slate-950 p-3">
      <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
      <svg viewBox="0 0 100 38" className="mt-2 h-20 w-full" role="img" aria-label={`${label} sparkline`}>
        <path d="M0 34H100" stroke="#334155" strokeWidth="1" />
        <polyline points={points} fill="none" stroke="#22d3ee" strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" />
        {clean.map((value, index) => {
          const x = clean.length === 1 ? 0 : (index / (clean.length - 1)) * 100;
          const y = 34 - (value / max) * 28;
          return <circle key={`${value}-${index}`} cx={x} cy={y} r="2" fill="#a7f3d0" />;
        })}
      </svg>
    </div>
  );
}

function TimeLapseChart({
  title,
  subtitle,
  rows,
  series,
  empty,
}: {
  title: string;
  subtitle?: string;
  rows: Array<{ label: string; [key: string]: string | number }>;
  series: Array<{ key: string; label: string; color: string }>;
  empty: string;
}) {
  if (!rows.length) {
    return <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs text-slate-500">{empty}</div>;
  }

  const values = rows.flatMap((row) => series.map((item) => Number(row[item.key] ?? 0))).filter((value) => Number.isFinite(value));
  const max = Math.max(...values, 1);
  const width = 320;
  const height = 150;
  const left = 34;
  const right = 10;
  const top = 14;
  const bottom = 24;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;

  const point = (value: number, index: number) => {
    const x = left + (rows.length === 1 ? 0 : (index / (rows.length - 1)) * plotWidth);
    const y = top + plotHeight - (clamp(value / max) * plotHeight);
    return { x, y };
  };

  return (
    <div className="rounded border border-slate-800 bg-slate-950 p-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">{title}</div>
          {subtitle ? <div className="mt-1 text-xs font-bold leading-relaxed text-slate-500">{subtitle}</div> : null}
        </div>
        <div className="flex flex-wrap gap-2">
          {series.map((item) => (
            <div key={item.key} className="flex items-center gap-1 text-[10px] font-black uppercase tracking-widest text-slate-500">
              <span className="h-2 w-2 rounded-full" style={{ background: item.color }} />
              {item.label}
            </div>
          ))}
        </div>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="mt-3 h-64 w-full" role="img" aria-label={`${title} analytics chart`}>
        {[0.25, 0.5, 0.75, 1].map((tick) => (
          <g key={tick}>
            <path d={`M${left} ${top + plotHeight - tick * plotHeight}H${width - right}`} stroke="#1e293b" strokeWidth="1" />
            <text x="0" y={top + plotHeight - tick * plotHeight + 4} fill="#64748b" fontSize="9" fontWeight="700">
              {Math.round(max * tick)}
            </text>
          </g>
        ))}
        {series.map((item) => {
          const points = rows
            .map((row, index) => point(Number(row[item.key] ?? 0), index))
            .map(({ x, y }) => `${x},${y}`)
            .join(" ");
          return <polyline key={item.key} points={points} fill="none" stroke={item.color} strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" />;
        })}
        {rows.map((row, index) => {
          const x = left + (rows.length === 1 ? 0 : (index / (rows.length - 1)) * plotWidth);
          return (
            <text key={`${row.label}-${index}`} x={x} y={height - 6} fill="#94a3b8" fontSize="9" fontWeight="700" textAnchor={index === 0 ? "start" : index === rows.length - 1 ? "end" : "middle"}>
              {row.label}
            </text>
          );
        })}
      </svg>
    </div>
  );
}

function DivergenceChart({
  rows,
  empty,
}: {
  rows: Array<{ label: string; baseline: number; controlled: number; saved: number }>;
  empty: string;
}) {
  if (!rows.length) {
    return <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs text-slate-500">{empty}</div>;
  }
  const max = Math.max(...rows.flatMap((row) => [row.baseline, row.controlled]), 1);
  return (
    <div className="grid gap-3">
      {rows.map((row) => (
        <div key={row.label} className="rounded border border-slate-800 bg-slate-950 p-3">
          <div className="mb-2 flex items-center justify-between gap-3 text-xs">
            <span className="font-black text-slate-100">{row.label}</span>
            <span className={`font-mono ${row.saved >= 0 ? "text-emerald-200" : "text-red-200"}`}>{signedNumber(row.saved)} pts</span>
          </div>
          <div className="grid gap-1">
            <div className="h-2 overflow-hidden rounded bg-slate-800">
              <div className="h-full rounded bg-red-300" style={{ width: `${clamp((row.baseline / max) * 100)}%` }} />
            </div>
            <div className="h-2 overflow-hidden rounded bg-slate-800">
              <div className="h-full rounded bg-emerald-300" style={{ width: `${clamp((row.controlled / max) * 100)}%` }} />
            </div>
          </div>
          <div className="mt-2 flex justify-between text-[10px] font-black uppercase tracking-widest text-slate-500">
            <span>baseline {Math.round(row.baseline)}</span>
            <span>controlled {Math.round(row.controlled)}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

const _parkedExecutiveAnalyticsBindings = [confidencePct, dispatchMessage, Sparkline, DivergenceChart];

export default function ExecutivePage() {
  const { parkState, isConnected, isRefreshing, connectionError, refreshParkState } = useParkPulseState();
  const [brief, setBrief] = useState<ExecutiveDayBrief | null>(null);
  const [backlog, setBacklog] = useState<BacklogPayload | null>(null);
  const [incidents, setIncidents] = useState<IncidentPayload | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [employeeText, setEmployeeText] = useState("");
  const [agentMode, setAgentMode] = useState<AgentMode>("auto");
  const [isRunning, setIsRunning] = useState(false);
  const [run, setRun] = useState<HumanRun | null>(null);
  const [signal, setSignal] = useState<SignalIntake | null>(null);
  const [humanError, setHumanError] = useState<string | null>(null);
  const [operatorDecision, setOperatorDecision] = useState<"approved" | "held" | "edited" | null>(null);

  const loadExecutiveData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [briefResponse, backlogResponse, incidentResponse] = await Promise.all([
        fetchParkPulseApi("/api/park/executive-day-brief", { timeoutMs: 8000 }),
        fetchParkPulseApi("/api/park/operational-backlog", { timeoutMs: 8000 }),
        fetchParkPulseApi("/api/park/incident-analytics", { timeoutMs: 8000 }),
      ]);
      setBrief((await briefResponse.json()) as ExecutiveDayBrief);
      setBacklog((await backlogResponse.json()) as BacklogPayload);
      setIncidents((await incidentResponse.json()) as IncidentPayload);
    } catch (err) {
      setBrief(null);
      setBacklog(null);
      setIncidents(null);
      setError(err instanceof Error ? err.message : "Unable to load executive runtime data.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadExecutiveData();
  }, [loadExecutiveData]);

  const domains = backlog?.enterpriseDomains ?? [];
  const issues = backlog?.issues ?? [];
  const tickets = incidents?.tickets ?? [];
  const telemetry = run?.run_telemetry;
  const route = run?.role_route ?? run?.route;
  const dispatches = telemetry?.delivery?.dispatches ?? [];
  const selectedAction = telemetry?.planner?.selected_action;
  const evalScore = telemetry?.eval?.scorecard?.overall;
  const toolCalls = run?.digital_twin_tools?.tool_calls ?? [];
  const activePolicy = parkState.guestFlow.activePolicy || "normal";
  const runtimeInterventions = parkState.guestFlow.interventions ?? [];
  const policyRelief = activePolicy && activePolicy !== "normal" ? 12 : 0;
  const interventionRelief = clamp(runtimeInterventions.reduce((total, item) => total + (Number(item.intensity) || 0), 0) * 0.35, 0, 24);
  const dispatchRelief = clamp((telemetry?.delivery?.summary?.sent ?? dispatches.length) * 3 + (telemetry?.delivery?.summary?.acknowledged ?? 0) * 4, 0, 16);
  const forecastRelief = clamp(parkState.counterfactualForecast?.actionExecution?.finalTakeRatePct ? parkState.counterfactualForecast.actionExecution.finalTakeRatePct * 0.28 : 0, 0, 20);
  const mitigationEffect = clamp(policyRelief + interventionRelief + dispatchRelief + forecastRelief, 0, 48);

  const livePressure = useMemo(() => {
    const topZone = [...parkState.guestFlow.zones].sort((left, right) => right.density - left.density)[0];
    const topRide = [...parkState.guestFlow.rides].sort((left, right) => right.waitMins - left.waitMins)[0];
    const highestPath = [...parkState.guestFlow.paths].sort((left, right) => right.congestionLevel - left.congestionLevel)[0];
    return { topZone, topRide, highestPath };
  }, [parkState.guestFlow.paths, parkState.guestFlow.rides, parkState.guestFlow.zones]);
  const currentMinuteOfDay =
    parkState.operatingClock?.heartbeat?.minuteOfDay ??
    parkState.operatingClock?.phase?.minuteOfDay ??
    parkState.simTime.hour * 60 + parkState.simTime.minute;
  const currentDensity = livePressure.topZone?.density ?? 0;
  const currentWait = livePressure.topRide?.waitMins ?? 0;
  const currentStaffRisk = clamp(100 - (parkState.parkOps.staffReadyPct ?? 0));
  const currentIncidentPressure = clamp(((incidents?.summary?.ticketCount ?? 0) * 7) + ((incidents?.summary?.humanReviewCount ?? 0) * 5));
  const currentSatisfactionRisk = clamp(100 - (parkState.guestFlow.avgSatisfaction ?? 0));
  const currentComposite = clamp((currentDensity * 0.28) + (Math.min(currentWait, 120) * 0.24) + (currentStaffRisk * 0.2) + (currentIncidentPressure * 0.16) + (currentSatisfactionRisk * 0.12));

  const kpis = [
    ["Runtime", isConnected ? "live" : "disconnected"],
    ["Guests", parkState.guestFlow.representedGuests ? parkState.guestFlow.representedGuests.toLocaleString() : "--"],
    ["Satisfaction", pct(parkState.guestFlow.avgSatisfaction)],
    ["Staff ready", pct(parkState.parkOps.staffReadyPct)],
    ["Human review", String(incidents?.summary?.humanReviewCount ?? "--")],
    ["Open tickets", String(incidents?.summary?.ticketCount ?? "--")],
    ["Backlog", String(backlog?.unresolvedCount ?? "--")],
    ["Dispatches", String(dispatches.length || telemetry?.delivery?.summary?.total || "--")],
  ];

  const rideWaitRows = parkState.guestFlow.rides
    .slice()
    .sort((left, right) => right.waitMins - left.waitMins)
    .slice(0, 6)
    .map((ride) => ({ label: ride.name, value: ride.waitMins, max: 120, tone: "bg-cyan-300" }));

  const zoneRows = parkState.guestFlow.zones
    .slice()
    .sort((left, right) => right.density - left.density)
    .slice(0, 6)
    .map((zone) => ({ label: zone.name, value: zone.density, max: 100, tone: zone.density > 85 ? "bg-red-300" : zone.density > 70 ? "bg-amber-300" : "bg-emerald-300" }));

  const domainRows = domains
    .slice()
    .sort((left, right) => (left.score ?? 0) - (right.score ?? 0))
    .map((domain) => ({ label: domain.label ?? domain.id ?? "domain", value: domain.score ?? 0, max: 100, tone: (domain.score ?? 0) < 70 ? "bg-amber-300" : "bg-emerald-300" }));

  const incidentDomainRows = (incidents?.summary?.topDomains ?? []).map(([label, value]) => ({ label, value, max: Math.max(...(incidents?.summary?.topDomains ?? []).map((row) => row[1]), 1), tone: "bg-red-300" }));

  const dispatchRows = [
    { label: "sent", value: telemetry?.delivery?.summary?.sent ?? dispatches.filter((dispatch) => dispatch.status?.toLowerCase().includes("sent")).length, tone: "bg-emerald-300" },
    { label: "acknowledged", value: telemetry?.delivery?.summary?.acknowledged ?? dispatches.filter((dispatch) => dispatch.status?.toLowerCase().includes("ack")).length, tone: "bg-cyan-300" },
    { label: "approval pending", value: telemetry?.delivery?.summary?.pending_operator_approval ?? dispatches.filter((dispatch) => dispatch.status?.toLowerCase().includes("approval")).length, tone: "bg-amber-300" },
  ];

  const forecastHorizonRows = (parkState.counterfactualForecast?.horizons ?? []).map((horizon) => ({
    label: `+${horizon.minutes}m`,
    baselineDensity: horizon.withoutAudit.densityPct,
    controlledDensity: horizon.withAudit.densityPct,
    baselineLane: horizon.withoutAudit.serviceLaneRiskPct,
    controlledLane: horizon.withAudit.serviceLaneRiskPct,
    guestMinutesLost: horizon.withoutAudit.guestMinutesLost,
    guestMinutesSaved: horizon.delta.guestMinutesSaved,
  }));

  const forecastDivergenceRows = forecastHorizonRows.slice(0, 5).map((row) => ({
    label: row.label,
    baseline: row.baselineDensity,
    controlled: row.controlledDensity,
    saved: row.baselineDensity - row.controlledDensity,
  }));

  const openingMinuteOfDay = 9 * 60;
  const currentOpenMinute = Math.max(openingMinuteOfDay, Math.min(23 * 60, currentMinuteOfDay || openingMinuteOfDay));
  const dayCurvePointCount = Math.max(5, Math.min(9, Math.ceil((currentOpenMinute - openingMinuteOfDay) / 120) + 1));
  const operatingDayCurveRows = Array.from({ length: dayCurvePointCount }, (_, index) => {
    const ratio = dayCurvePointCount === 1 ? 1 : index / (dayCurvePointCount - 1);
    const minuteOfDay = openingMinuteOfDay + (currentOpenMinute - openingMinuteOfDay) * ratio;
    const demand = operatingDemandEstimate(minuteOfDay);
    const snapshotPull = index === dayCurvePointCount - 1 ? 1 : ratio * 0.35;
    const baseline = clamp(demand * (1 - snapshotPull) + (currentComposite + mitigationEffect) * snapshotPull);
    const mitigationRampStart = Math.max(openingMinuteOfDay + 30, currentOpenMinute - 120);
    const mitigationRamp = minuteOfDay <= mitigationRampStart ? 0 : clamp((minuteOfDay - mitigationRampStart) / Math.max(1, currentOpenMinute - mitigationRampStart));
    const controlled = index === dayCurvePointCount - 1 ? currentComposite : clamp(baseline - mitigationEffect * mitigationRamp);
    return {
      label: formatMinuteOfDay(minuteOfDay),
      expected: baseline,
      controlled,
      operations: baseline - controlled,
      density: index === dayCurvePointCount - 1 ? currentDensity : clamp(demand + (currentDensity - demand) * ratio),
      wait: index === dayCurvePointCount - 1 ? currentWait : clamp(demand * 0.72 + (currentWait - demand * 0.72) * ratio),
    };
  });

  const operatingDayStart = operatingDayCurveRows[0];
  const operatingDayEnd = operatingDayCurveRows.at(-1);
  const operatingDayDelta = operatingDayStart && operatingDayEnd ? operatingDayEnd.controlled - operatingDayStart.controlled : 0;
  const opsEffectAtSnapshot = operatingDayEnd?.operations ?? 0;

  const lapseRows = forecastHorizonRows.length
    ? forecastHorizonRows.map((row) => ({
        label: row.label,
        baseline: row.baselineDensity,
        controlled: row.controlledDensity,
        lane: row.baselineLane,
        saved: row.guestMinutesSaved,
      }))
    : operatingDayCurveRows.map((row) => ({
        label: row.label,
        baseline: row.expected,
        controlled: row.controlled,
        lane: row.density,
        saved: row.operations,
      }));

  const causalRows = [
    { label: "Peak zone density", value: livePressure.topZone?.density ?? 0, max: 130, tone: "bg-red-300" },
    { label: "Queue wait minutes", value: livePressure.topRide?.waitMins ?? 0, max: 120, tone: "bg-amber-300" },
    { label: "Path congestion", value: livePressure.highestPath?.congestionLevel ?? 0, max: 100, tone: "bg-cyan-300" },
    { label: "Staffing gap", value: 100 - (parkState.parkOps.staffReadyPct ?? 0), max: 100, tone: "bg-violet-300" },
    { label: "Incident load", value: Math.min(100, (incidents?.summary?.ticketCount ?? 0) * 8), max: 100, tone: "bg-red-300" },
  ];

  const dominantDriver = causalRows.slice().sort((left, right) => right.value / right.max - left.value / left.max)[0];
  const forecastAvoidance = forecastDivergenceRows.reduce((total, row) => total + Math.max(row.saved, 0), 0);
  const topAnomaly = parkState.operationsAudit?.anomalies?.[0];
  const topTicket = tickets[0];
  const topIssue = issues[0];
  const concludingIssueTitle = brief?.primaryIssue?.title ?? topAnomaly?.title ?? topTicket?.title ?? topIssue?.title ?? livePressure.topZone?.name ?? "No concluding issue yet";
  const concludingIssueDetail =
    brief?.primaryIssue?.recommendedDecision ??
    topAnomaly?.recommendedAction ??
    topTicket?.recommendedHumanCall ??
    topIssue?.recommendedNext ??
    (livePressure.topZone ? `${livePressure.topZone.name} is the highest-density operating constraint in the current day rollup.` : "Refresh analytics after the backend returns incident and backlog payloads.");
  const issueEvidence = [
    topAnomaly?.evidence?.[0],
    parkState.counterfactualForecast?.impact?.summary,
    backlog?.enterpriseSummary?.answer,
    parkState.learningEvidenceLedger?.headline,
  ].filter(Boolean).slice(0, 4) as string[];
  const learningSummary = parkState.learningEvidenceLedger?.summary;
  const scenarioSummary = parkState.scenarioLab?.summary;
  const readinessDecision = parkState.readinessBrief?.decision;
  const evidenceRowCount =
    (incidents?.summary?.ticketCount ?? tickets.length) +
    (backlog?.unresolvedCount ?? issues.length) +
    (learningSummary?.ledgerEntries ?? 0) +
    (parkState.operationsAudit?.summary?.openWorkLogs ?? 0) +
    (parkState.digitalTwinCalibration?.summary?.resolvedRows ?? 0);
  const analysisThesis = {
    verdict: brief?.headline
      ? `Concluding issue: ${brief.headline}`
      : topAnomaly
      ? `Concluding issue: ${topAnomaly.title}`
      : forecastAvoidance > 20
        ? "Concluding issue: intervention is materially changing the forecast."
        : dominantDriver?.value
          ? `Concluding issue: ${dominantDriver.label.toLowerCase()} is concentrating the day risk.`
          : "Concluding issue pending richer backend evidence.",
    whyNow: brief?.primaryIssue?.rootCause ?? (dominantDriver
      ? `${dominantDriver.label} is the strongest contributor at ${Math.round(dominantDriver.value)} against a ${dominantDriver.max} reference ceiling.`
      : "No causal contributor is above the analysis floor yet."),
    changed: brief?.daySummary?.whatChanged ?? (operatingDayStart && operatingDayEnd
      ? `The day rollup spans ${operatingDayStart.label} to ${operatingDayEnd.label}; controlled pressure changed ${signedNumber(operatingDayDelta)} points and the current ops effect is ${Math.round(opsEffectAtSnapshot)} points.`
      : "The operating-day summary is waiting for the park clock snapshot."),
    watch: brief?.daySummary?.watchNext ?? (livePressure.highestPath
      ? `${livePressure.highestPath.fromName ?? livePressure.highestPath.from} to ${livePressure.highestPath.toName ?? livePressure.highestPath.to} is the path to watch next.`
      : parkState.counterfactualForecast?.focus?.response ?? "Watch for the next forecast horizon and operator receipt."),
  };

  const analysisCards = [
    {
      label: "Day conclusion",
      value: concludingIssueTitle,
      detail: concludingIssueDetail,
    },
    {
      label: "Evidence base",
      value: `${compactNumber(evidenceRowCount)} records`,
      detail: `${incidents?.summary?.ticketCount ?? tickets.length} incident tickets, ${backlog?.unresolvedCount ?? issues.length} backlog items, ${learningSummary?.ledgerEntries ?? 0} learning rows, ${parkState.digitalTwinCalibration?.summary?.resolvedRows ?? 0} calibration rows.`,
    },
    {
      label: "Primary constraint",
      value: livePressure.topZone?.name ?? "No zone",
      detail: livePressure.topZone ? `${livePressure.topZone.density}% density, ${livePressure.topZone.waitMins}m local wait, dominant intent ${livePressure.topZone.dominantIntent || "unknown"}.` : "No zone payload returned.",
    },
    {
      label: "Operating window",
      value: operatingDayEnd ? `${operatingDayStart?.label ?? "09:00"} to ${operatingDayEnd.label}` : "warming",
      detail: operatingDayStart && operatingDayEnd ? `Controlled pressure moved from ${Math.round(operatingDayStart.controlled)} to ${Math.round(operatingDayEnd.controlled)} (${signedNumber(operatingDayDelta)} pts).` : "The summary starts at park opening when the operating clock arrives.",
    },
    {
      label: "Forecast value",
      value: parkState.counterfactualForecast?.impact?.guestMinutesSaved ? `${compactNumber(parkState.counterfactualForecast.impact.guestMinutesSaved)} min saved` : "--",
      detail: parkState.counterfactualForecast?.impact?.summary ?? "No counterfactual impact payload returned.",
    },
    {
      label: "Readiness call",
      value: readinessDecision?.goNoGo ?? readinessDecision?.label ?? "--",
      detail: readinessDecision?.reason ?? parkState.operationsAudit?.anomalies?.[0]?.recommendedAction ?? "No readiness or audit recommendation returned.",
    },
    {
      label: "Scenario learning",
      value: scenarioSummary?.totalGuestMinutesSaved ? `${compactNumber(scenarioSummary.totalGuestMinutesSaved)} min saved` : "--",
      detail: scenarioSummary?.gap ?? parkState.scenarioLab?.headline ?? "No scenario lab summary returned.",
    },
  ];

  const bigDataRows = [
    {
      label: "Guest and flow sample",
      value: parkState.guestFlow.representedGuests ?? 0,
      max: Math.max(parkState.guestFlow.representedGuests ?? 0, 1),
      tone: "bg-cyan-300",
      detail: `${parkState.guestFlow.activeGroups ?? 0} active groups, ${parkState.guestFlow.zones.length} zones, ${parkState.guestFlow.paths.length} paths, ${parkState.guestFlow.rides.length} rides.`,
    },
    {
      label: "Issue corpus",
      value: (incidents?.summary?.ticketCount ?? tickets.length) + (backlog?.unresolvedCount ?? issues.length),
      max: Math.max(evidenceRowCount, 1),
      tone: "bg-red-300",
      detail: `${incidents?.summary?.humanReviewCount ?? 0} human-review items and ${(incidents?.summary?.topDomains ?? []).length} incident domains.`,
    },
    {
      label: "Learning memory",
      value: learningSummary?.ledgerEntries ?? 0,
      max: Math.max(evidenceRowCount, 1),
      tone: "bg-violet-300",
      detail: `${learningSummary?.appliedToday ?? 0} applied today, ${learningSummary?.memoryBackedDecisions ?? 0} memory-backed decisions.`,
    },
    {
      label: "Calibration rows",
      value: parkState.digitalTwinCalibration?.summary?.resolvedRows ?? 0,
      max: Math.max(evidenceRowCount, 1),
      tone: "bg-emerald-300",
      detail: `${parkState.digitalTwinCalibration?.summary?.accuracyScore ? Math.round(parkState.digitalTwinCalibration.summary.accuracyScore) : "--"}% accuracy over the recent window.`,
    },
  ];

  const displayedBigDataRows = brief?.evidenceRollup?.length
    ? brief.evidenceRollup.map((row, index) => ({
        label: row.label ?? `Evidence ${index + 1}`,
        value: row.value ?? 0,
        max: Math.max(...(brief.evidenceRollup ?? []).map((item) => item.value ?? 0), 1),
        tone: ["bg-cyan-300", "bg-red-300", "bg-violet-300", "bg-emerald-300"][index % 4],
        detail: row.detail ?? "",
      }))
    : bigDataRows;

  const displayedPressureCurveRows = brief?.charts?.pressureCurve?.length ? brief.charts.pressureCurve : operatingDayCurveRows;
  const displayedDriverRows = brief?.charts?.driverBreakdown?.length
    ? brief.charts.driverBreakdown.map((row) => ({ label: row.label, value: row.value, max: row.max ?? 100, tone: row.value > 80 ? "bg-red-300" : row.value > 55 ? "bg-amber-300" : "bg-cyan-300" }))
    : causalRows;
  const displayedIncidentDomainRows = brief?.charts?.domainBreakdown?.length
    ? brief.charts.domainBreakdown.map((row) => ({ label: row.label, value: row.value, max: row.max ?? Math.max(...(brief.charts?.domainBreakdown ?? []).map((item) => item.value), 1), tone: "bg-red-300" }))
    : incidentDomainRows;
  const displayedPriorityQueue = brief?.priorityQueue?.length
    ? brief.priorityQueue
    : [...tickets.slice(0, 3).map((ticket) => ({
        id: `ticket-${ticket.id}`,
        title: ticket.title ?? ticket.id ?? "Incident",
        severity: ticket.severity ?? ticket.status,
        detail: ticket.recommendedHumanCall ?? ticket.summary ?? "No ticket detail returned.",
        selectionScore: undefined,
      })), ...issues.slice(0, 3).map((issue) => ({
        id: `issue-${issue.id}`,
        title: issue.title ?? issue.id ?? "Backlog",
        severity: issue.severity,
        detail: issue.recommendedNext ?? issue.businessImpact ?? "No issue detail returned.",
        selectionScore: undefined,
      }))].slice(0, 5);
  const selectionScoreRows = [
    { label: "Total score", value: brief?.primaryIssue?.selectionScore?.total ?? 0, max: 100, tone: "bg-red-300" },
    { label: "Severity", value: brief?.primaryIssue?.selectionScore?.severityScore ?? 0, max: 100, tone: "bg-amber-300" },
    { label: "Guest impact", value: brief?.primaryIssue?.selectionScore?.guestImpact ?? 0, max: 100, tone: "bg-cyan-300" },
    { label: "Safety/access", value: brief?.primaryIssue?.selectionScore?.safetyAccessRisk ?? 0, max: 100, tone: "bg-violet-300" },
  ].filter((row) => row.value > 0);
  const decisionCriteria = brief?.recommendedDecision;
  const impactModelRows = [
    { label: "Guest min at risk", value: brief?.impactModel?.guestMinutesAtRisk ?? 0, max: Math.max(brief?.impactModel?.guestMinutesAtRisk ?? 0, 1), tone: "bg-red-300" },
    { label: "Complaint risk", value: brief?.impactModel?.complaintEscalationRiskPct ?? 0, max: 100, tone: "bg-amber-300" },
    { label: "Safety/access", value: brief?.impactModel?.safetyAccessRiskPct ?? 0, max: 100, tone: "bg-violet-300" },
    { label: "Staffing load", value: brief?.impactModel?.staffingLoadRiskPct ?? 0, max: 100, tone: "bg-cyan-300" },
  ].filter((row) => row.value > 0);
  const evidenceProvenance = (brief?.evidence ?? []).filter((item) => item.claim || item.metric || item.sourceId).slice(0, 5);
  const issueTimeline = (brief?.issueTimeline ?? []).filter((item) => item.label || item.detail).slice(0, 5);
  const decisionAlternatives = (brief?.decisionAlternatives ?? []).filter((item) => item.label).slice(0, 4);
  const learningMemory = brief?.learningMemory;
  const productStructure = brief?.productStructure;
  const workflowStages = (productStructure?.workflowStages ?? []).filter((stage) => stage.stage || stage.answer).slice(0, 5);
  const ownerResponsibilities = (productStructure?.ownerResponsibilities ?? []).filter((ownerItem) => ownerItem.owner || ownerItem.role).slice(0, 3);
  const productGaps = (productStructure?.productGaps ?? []).filter((gap) => gap.gap || gap.nextBuild).slice(0, 3);

  const traceEvents = [
    ...(parkState.operationsAudit?.reactionTimeline ?? []).map((event) => ({
      id: event.at,
      label: event.label,
      detail: `${event.expected} / observed ${event.observed}`,
      tone: event.delta.toLowerCase().includes("late") || event.delta.toLowerCase().includes("miss") ? "border-red-400/40 bg-red-950/20 text-red-100" : "border-cyan-400/30 bg-cyan-950/20 text-cyan-100",
      meta: event.auditRead,
    })),
    ...(parkState.missionReplay?.steps ?? []).slice(0, 5).map((step) => ({
      id: step.id,
      label: step.title,
      detail: step.detail,
      tone: step.tone === "critical" ? "border-red-400/40 bg-red-950/20 text-red-100" : step.tone === "watch" ? "border-amber-400/40 bg-amber-950/20 text-amber-100" : "border-emerald-400/35 bg-emerald-950/20 text-emerald-100",
      meta: step.time,
    })),
  ].slice(0, 7);

  const causalChainRows = (parkState.counterfactualForecast?.causalChain ?? []).slice(0, 4);
  const calibrationRows = (parkState.digitalTwinCalibration?.latestResolved ?? []).slice(0, 4);

  const reasoningRows = [
    {
      label: "Interpret",
      body: signal?.signal?.categories?.length ? `${signal.signal.risk_level ?? "risk"}: ${signal.signal.categories.join(", ")}` : "Waiting for signal intake receipt.",
      status: signal ? "done" : isRunning ? "active" : "waiting",
    },
    {
      label: "Snapshot context",
      body: livePressure.topZone || livePressure.topRide ? `${livePressure.topZone?.name ?? "No zone"} ${livePressure.topZone?.density ?? "--"}%; ${livePressure.topRide?.name ?? "no ride"} ${livePressure.topRide?.waitMins ?? "--"}m.` : "Waiting for live park state.",
      status: isConnected ? "done" : "waiting",
    },
    {
      label: "Route",
      body: route?.selected_role ? `${route.selected_role}: ${route.why ?? "runtime route selected"}` : "Waiting for role router.",
      status: route ? "done" : isRunning ? "active" : "waiting",
    },
    {
      label: "Gate",
      body: telemetry?.governance?.gate_status ?? "Waiting for policy gate.",
      status: telemetry?.governance ? "done" : isRunning ? "active" : "waiting",
    },
    {
      label: "Emit",
      body: selectedAction?.label ?? selectedAction?.action ?? "Waiting for selected action.",
      status: selectedAction || dispatches.length ? "done" : isRunning ? "active" : "waiting",
    },
  ];

  const _parkedExecutiveRunAnalysis = [
    toolCalls,
    dispatchRows,
    lapseRows,
    issueEvidence,
    analysisCards,
    traceEvents,
    causalChainRows,
    calibrationRows,
    reasoningRows,
  ];

  const runHumanAgent = async () => {
    setIsRunning(true);
    setHumanError(null);
    setOperatorDecision(null);
    setRun(null);
    setSignal(null);
    try {
      const signalResponse = await fetchParkPulseApi("/api/park/signals/intake", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: employeeText, source: "employee_text", reporterRole: "frontline_employee" }),
        timeoutMs: 8000,
      });
      setSignal((await signalResponse.json()) as SignalIntake);

      const runResponse = await fetchParkPulseApi("/api/park/agent-role-run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: employeeText, mode: agentMode }),
        timeoutMs: 12000,
      });
      setRun((await runResponse.json()) as HumanRun);
    } catch (err) {
      setHumanError(err instanceof Error ? err.message : "Unable to convert operator text into runtime actions.");
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <main className="min-h-screen bg-slate-950 px-4 py-5 font-sans text-slate-200 lg:px-8">
      <div className="mx-auto max-w-[1500px] space-y-5">
        <header className="rounded-lg border border-slate-800 bg-slate-900 p-5">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Executive operations</div>
              <h1 className="mt-2 text-3xl font-black text-slate-100 lg:text-4xl">Decision brief</h1>
              <p className="mt-3 max-w-3xl text-sm leading-relaxed text-slate-400">
                One operating call, the evidence behind it, and the owner responsible for the next checkpoint.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => {
                  void refreshParkState();
                  void loadExecutiveData();
                }}
                disabled={isRefreshing || isLoading}
                className="rounded border border-cyan-400/60 bg-cyan-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-cyan-200 disabled:opacity-50"
              >
                {isRefreshing || isLoading ? "Refreshing" : "Refresh analytics"}
              </button>
              <a href="/ops" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-100">
                Operating loop
              </a>
              <a href="/monitor" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-100">
                Monitor
              </a>
              <a href="/staff-training" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-teal-300">
                Staff trainer
              </a>
            </div>
          </div>
        </header>

        {(error || connectionError) && (
          <section className="rounded border border-amber-400/30 bg-amber-950/15 p-3 text-sm font-bold text-amber-100">
            Runtime debug: {error ?? connectionError}
          </section>
        )}

        <section className="grid gap-2 md:grid-cols-4 xl:grid-cols-8">
          {kpis.map(([label, value]) => (
            <MetricTile key={label} label={label} value={value} />
          ))}
        </section>

        <section className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-5 xl:grid-cols-[1.15fr_0.85fr]">
          <div className="rounded-lg border border-cyan-400/25 bg-slate-900 p-5">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div className="min-w-0">
                <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Decision story</div>
                <h2 className="mt-2 text-2xl font-black leading-tight text-slate-100">{productStructure?.executiveQuestion ?? "What decision needs approval now?"}</h2>
                <p className="mt-3 max-w-4xl text-sm font-bold leading-relaxed text-slate-300">{productStructure?.decisionThesis ?? concludingIssueDetail}</p>
              </div>
              <StatusPill value={brief?.primaryIssue?.severity ?? "watch"} />
            </div>

            <div className="mt-4 grid gap-3 md:grid-cols-4">
              <div className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Why now</div>
                <p className="mt-2 line-clamp-3 text-xs font-bold leading-relaxed text-slate-300">{brief?.primaryIssue?.rootCause ?? analysisThesis.whyNow}</p>
              </div>
              <div className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Owner</div>
                <p className="mt-2 text-sm font-black text-emerald-100">{decisionCriteria?.owner ?? brief?.primaryIssue?.owner ?? "--"}</p>
                <p className="mt-1 text-xs font-bold text-slate-500">{decisionCriteria?.deadlineMinutes !== undefined ? `${decisionCriteria.deadlineMinutes}m deadline` : "--"}</p>
              </div>
              <div className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Success</div>
                <p className="mt-2 line-clamp-3 text-xs font-bold leading-relaxed text-slate-300">{productStructure?.successMetric ?? "--"}</p>
              </div>
              <div className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Next check</div>
                <p className="mt-2 line-clamp-3 text-xs font-bold leading-relaxed text-slate-300">{productStructure?.reviewCadence ?? "--"}</p>
              </div>
            </div>

            <div className="mt-4 grid gap-2 md:grid-cols-5">
              {workflowStages.length ? workflowStages.map((stage) => (
                <div key={stage.stage ?? stage.question} className="rounded border border-slate-800 bg-slate-950 px-3 py-2">
                  <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">{stage.stage ?? "Stage"}</div>
                  <p className="mt-2 text-xs font-black text-slate-200">{stage.question ?? "--"}</p>
                  <div className="mt-2 line-clamp-2 font-mono text-[11px] font-black leading-relaxed text-emerald-100">{stage.metric ?? "--"}</div>
                </div>
              )) : <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs text-slate-500">No workflow structure returned.</div>}
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900 p-5">
            <div className="text-[10px] font-black uppercase tracking-widest text-violet-300">Who does what</div>
            <div className="mt-3 grid gap-3">
              {ownerResponsibilities.length ? ownerResponsibilities.map((item) => (
                <div key={`${item.owner}-${item.role}`} className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                    <div className="truncate text-sm font-black text-slate-100">{item.owner ?? "--"}</div>
                    <div className="truncate text-[10px] font-black uppercase tracking-widest text-violet-300">{item.role ?? "--"}</div>
                  </div>
                  <p className="mt-2 line-clamp-2 text-xs font-bold leading-relaxed text-slate-400">{item.responsibility ?? "--"}</p>
                  <p className="mt-2 line-clamp-2 text-xs font-bold leading-relaxed text-amber-100/80">{item.proofNeeded ?? "--"}</p>
                </div>
              )) : <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs text-slate-500">No owner structure returned.</div>}
            </div>

            <div className="mt-4 rounded border border-slate-800 bg-slate-950 p-3">
              <div className="mb-3 text-[10px] font-black uppercase tracking-widest text-amber-300">Build next</div>
              <div className="grid gap-2">
                {productGaps.length ? productGaps.map((gap) => (
                  <div key={gap.gap} className="rounded border border-slate-800 bg-slate-900 px-3 py-2">
                    <div className="text-xs font-black text-slate-100">{gap.gap ?? "Gap"}</div>
                    <p className="mt-1 line-clamp-2 text-xs font-bold leading-relaxed text-cyan-100/80">{gap.nextBuild ?? "--"}</p>
                  </div>
                )) : <div className="text-xs text-slate-500">No product gaps returned.</div>}
              </div>
            </div>
          </div>
        </section>

        <section className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-5 xl:grid-cols-[1.05fr_0.95fr]">
          <div className="rounded-lg border border-red-400/30 bg-slate-900 p-5">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-red-300">Decision proof</div>
                <h2 className="mt-2 text-2xl font-black leading-tight text-slate-100">{concludingIssueTitle}</h2>
                <p className="mt-3 max-w-3xl text-sm leading-relaxed text-slate-300">{analysisThesis.whyNow}</p>
              </div>
              <StatusPill value={brief?.primaryIssue?.severity ?? backlog?.enterpriseSummary?.weakestDomain?.status ?? parkState.operationsAudit?.auditAgent?.status ?? "watch"} />
            </div>

            <div className="mt-4 grid gap-3 md:grid-cols-3">
              {[
                ["Pressure", analysisThesis.whyNow],
                ["Effect", analysisThesis.changed],
                ["Watch", analysisThesis.watch],
              ].map(([label, detail]) => (
                <div key={label} className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                  <p className="mt-2 line-clamp-3 text-xs font-bold leading-relaxed text-slate-300">{detail}</p>
                </div>
              ))}
            </div>

            {(brief?.primaryIssue?.businessImpact || backlog?.enterpriseSummary?.answer) && (
              <p className="mt-4 rounded border border-slate-800 bg-slate-950 p-3 text-xs font-bold leading-relaxed text-slate-400">
                {brief?.primaryIssue?.businessImpact ?? backlog?.enterpriseSummary?.answer}
              </p>
            )}

            <div className="mt-4 grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
              <div className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="mb-3 text-[10px] font-black uppercase tracking-widest text-red-300">Why this issue</div>
                <BarChart rows={selectionScoreRows} empty="Selection score unavailable." />
                <div className="mt-3 grid gap-2">
                  {(brief?.primaryIssue?.selectionRationale ?? []).slice(0, 4).map((item) => (
                    <div key={item} className="rounded border border-slate-800 bg-slate-900 px-3 py-2 text-xs font-bold leading-relaxed text-slate-400">
                      {item}
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="mb-3 text-[10px] font-black uppercase tracking-widest text-emerald-300">Decision gate</div>
                <div className="grid gap-2 sm:grid-cols-3">
                  <MetricTile label="Owner" value={decisionCriteria?.owner ?? brief?.primaryIssue?.owner ?? "--"} accent="text-emerald-100" />
                  <MetricTile label="Deadline" value={decisionCriteria?.deadlineMinutes !== undefined ? `${decisionCriteria.deadlineMinutes}m` : "--"} accent="text-amber-100" />
                  <MetricTile label="Confidence" value={decisionCriteria?.confidence !== undefined ? `${decisionCriteria.confidence}%` : "--"} accent="text-cyan-100" />
                </div>
                <p className="mt-3 text-xs font-bold leading-relaxed text-slate-400">{decisionCriteria?.tradeoff ?? "Tradeoff unavailable."}</p>
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  <div>
                    <div className="text-[10px] font-black uppercase tracking-widest text-emerald-300">Approve if</div>
                    <div className="mt-2 grid gap-1">
                      {(decisionCriteria?.approveIf ?? []).slice(0, 3).map((item) => (
                        <div key={item} className="text-xs font-bold leading-relaxed text-slate-300">{item}</div>
                      ))}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] font-black uppercase tracking-widest text-amber-300">Hold if</div>
                    <div className="mt-2 grid gap-1">
                      {(decisionCriteria?.holdIf ?? []).slice(0, 3).map((item) => (
                        <div key={item} className="text-xs font-bold leading-relaxed text-slate-300">{item}</div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div className="mt-4 grid gap-3 md:grid-cols-3">
              {[
                ["Attempted", (brief?.mitigations?.attempted ?? []).join(", ") || "No mitigation reported"],
                ["Observed effect", brief?.mitigations?.observedEffect ?? "--"],
                ["Remaining gap", brief?.mitigations?.remainingGap ?? brief?.daySummary?.unresolvedRisk ?? "--"],
              ].map(([label, detail]) => (
                <div key={label} className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                  <p className="mt-2 line-clamp-3 text-xs font-bold leading-relaxed text-slate-300">{detail}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900 p-5">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Evidence rollup</div>
              <div className="font-mono text-xs font-black text-slate-400">{compactNumber(evidenceRowCount)} records</div>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              {displayedBigDataRows.map((row) => (
                <div key={row.label} className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="flex items-center justify-between gap-3 text-xs">
                    <span className="font-black text-slate-100">{row.label}</span>
                    <span className="font-mono text-slate-500">{compactNumber(row.value)}</span>
                  </div>
                  <div className="mt-2 h-2 overflow-hidden rounded bg-slate-800">
                    <div className={`h-full rounded ${row.tone}`} style={{ width: `${clamp((row.value / row.max) * 100)}%` }} />
                  </div>
                  <p className="mt-2 line-clamp-2 text-xs font-bold leading-relaxed text-slate-500">{row.detail}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-5 xl:grid-cols-[0.95fr_1.05fr]">
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Issue lifecycle</div>
                <h2 className="mt-1 text-xl font-black text-slate-100">Open to decision</h2>
              </div>
              <StatusPill value={brief?.daySummary?.openedAt ? `since ${brief.daySummary.openedAt}` : "day rollup"} />
            </div>
            <div className="grid gap-2">
              {issueTimeline.length ? issueTimeline.map((event) => (
                <div key={`${event.phase}-${event.at}-${event.label}`} className="grid gap-2 rounded border border-slate-800 bg-slate-950 p-3 md:grid-cols-[74px_minmax(0,1fr)]">
                  <div className="font-mono text-xs font-black text-cyan-200">{event.at ?? "--"}</div>
                  <div className="min-w-0">
                    <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                      <div className="truncate text-sm font-black text-slate-100">{event.label ?? event.phase ?? "Event"}</div>
                      <div className="truncate text-[10px] font-black uppercase tracking-widest text-slate-600">{event.sourceId ?? event.source ?? "--"}</div>
                    </div>
                    <p className="mt-1 line-clamp-2 text-xs font-bold leading-relaxed text-slate-500">{event.detail ?? "--"}</p>
                  </div>
                </div>
              )) : <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs text-slate-500">No lifecycle proof returned.</div>}
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-emerald-300">Decision alternatives</div>
                <h2 className="mt-1 text-xl font-black text-slate-100">Compared options</h2>
              </div>
              <MetricTile label="Exposure" value={brief?.impactModel?.revenueExposureUsd !== undefined ? `$${compactNumber(brief.impactModel.revenueExposureUsd)}` : "--"} accent="text-amber-100" />
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              {decisionAlternatives.length ? decisionAlternatives.map((option) => (
                <div key={option.id ?? option.label} className={`rounded border p-3 ${option.recommended ? "border-emerald-400/40 bg-emerald-950/15" : "border-slate-800 bg-slate-950"}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-black text-slate-100">{option.label}</div>
                      <p className="mt-2 line-clamp-2 text-xs font-bold leading-relaxed text-slate-500">{option.expectedImpact ?? option.tradeoff ?? "--"}</p>
                    </div>
                    <span className="rounded bg-slate-900 px-2 py-1 font-mono text-xs font-black text-cyan-100">{option.score ?? "--"}</span>
                  </div>
                  <p className="mt-2 line-clamp-2 text-xs font-bold leading-relaxed text-amber-100/80">{option.risk ?? "--"}</p>
                </div>
              )) : <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs text-slate-500">No alternative analysis returned.</div>}
            </div>
          </div>
        </section>

        <section className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-5 xl:grid-cols-[0.9fr_1.1fr_0.8fr]">
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="mb-3 text-[10px] font-black uppercase tracking-widest text-red-300">Impact model</div>
            <BarChart rows={impactModelRows} empty="No quantified impact model returned." />
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              <MetricTile label="Confidence" value={brief?.impactModel?.confidencePct !== undefined ? `${brief.impactModel.confidencePct}%` : "--"} accent="text-cyan-100" />
              <MetricTile label="Revenue exposure" value={brief?.impactModel?.revenueExposureUsd !== undefined ? `$${compactNumber(brief.impactModel.revenueExposureUsd)}` : "--"} accent="text-amber-100" />
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Evidence provenance</div>
              <div className="font-mono text-xs font-black text-slate-500">{evidenceProvenance.length} sources</div>
            </div>
            <div className="grid gap-2">
              {evidenceProvenance.length ? evidenceProvenance.map((item) => (
                <div key={`${item.source}-${item.sourceId}-${item.metric}`} className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                    <div className="truncate text-xs font-black uppercase tracking-widest text-slate-400">{item.source ?? "--"}</div>
                    <div className="truncate font-mono text-[10px] font-black text-slate-600">{item.sourceId ?? item.id ?? "--"} · {item.timestamp ?? "--"}</div>
                  </div>
                  <p className="mt-2 line-clamp-2 text-xs font-bold leading-relaxed text-slate-300">{item.claim ?? "--"}</p>
                  <div className="mt-2 font-mono text-xs font-black text-cyan-100">{item.metric ?? "--"}</div>
                </div>
              )) : <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs text-slate-500">No evidence provenance returned.</div>}
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="mb-3 text-[10px] font-black uppercase tracking-widest text-violet-300">Learning memory</div>
            <div className="grid gap-2">
              <MetricTile label="Status" value={learningMemory?.status ?? "--"} accent={learningMemory?.status === "memory_backed" ? "text-emerald-100" : "text-amber-100"} />
              <MetricTile label="Matched cases" value={learningMemory?.matchedCases !== undefined ? compactNumber(learningMemory.matchedCases) : "--"} accent="text-cyan-100" />
              <MetricTile label="Take-rate prior" value={learningMemory?.takeRatePriorPct !== undefined ? `${learningMemory.takeRatePriorPct}%` : "--"} accent="text-violet-100" />
            </div>
            <p className="mt-3 rounded border border-slate-800 bg-slate-950 p-3 text-xs font-bold leading-relaxed text-slate-400">{learningMemory?.latestLesson ?? "No learning summary returned."}</p>
            <p className="mt-2 rounded border border-slate-800 bg-slate-950 p-3 text-xs font-bold leading-relaxed text-slate-400">{learningMemory?.nextBias ?? "No next-plan bias returned."}</p>
          </div>
        </section>

        <section className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-5 xl:grid-cols-[1.1fr_0.9fr]">
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-emerald-300">Pressure evidence</div>
                <h2 className="mt-1 text-xl font-black text-slate-100">{livePressure.topZone?.name ?? "No zone payload returned"}</h2>
              </div>
              <StatusPill value={isConnected ? "current snapshot" : "disconnected"} />
            </div>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <Gauge label="Zone density" value={livePressure.topZone?.density} tone={(livePressure.topZone?.density ?? 0) > 85 ? "red" : "cyan"} />
              <Gauge label="Top ride wait" value={livePressure.topRide?.waitMins} max={120} suffix="m" tone={(livePressure.topRide?.waitMins ?? 0) > 75 ? "amber" : "emerald"} />
              <Gauge label="Staff ready" value={parkState.parkOps.staffReadyPct} tone="emerald" />
              <Gauge label="Grid load" value={parkState.energy.gridLoadPercent} tone={(parkState.energy.gridLoadPercent ?? 0) > 80 ? "amber" : "cyan"} />
            </div>
            <div className="mt-4 grid gap-4 lg:grid-cols-2">
              <div className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="mb-3 text-[10px] font-black uppercase tracking-widest text-cyan-300">Ride waits</div>
                <BarChart rows={rideWaitRows} empty="No ride wait data." />
              </div>
              <div className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="mb-3 text-[10px] font-black uppercase tracking-widest text-amber-300">Zone density</div>
                <BarChart rows={zoneRows} empty="No zone density data." />
              </div>
            </div>
          </div>

          <div className="grid gap-5">
            <TimeLapseChart
              title="Day pressure curve"
              rows={displayedPressureCurveRows}
              empty="Waiting for park clock snapshot."
              series={[
                { key: "expected", label: "expected", color: "#fb7185" },
                { key: "controlled", label: "controlled", color: "#34d399" },
                { key: "density", label: "density", color: "#e879f9" },
              ]}
            />

            <div className="rounded border border-slate-800 bg-slate-950 p-3">
              <div className="mb-3 text-[10px] font-black uppercase tracking-widest text-fuchsia-300">Main drivers</div>
              <BarChart rows={displayedDriverRows} empty="No causal inputs returned." />
            </div>
          </div>
        </section>

        <section className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <div className="min-w-0 rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div className="min-w-0">
                <div className="text-[10px] font-black uppercase tracking-widest text-violet-300">Operator action</div>
                <h2 className="mt-1 text-xl font-black text-slate-100">{run?.operator_response?.headline ?? "Create a governed response"}</h2>
              </div>
              <div className="flex flex-wrap gap-2">
                {(["approved", "held", "edited"] as const).map((decision) => (
                  <button
                    key={decision}
                    type="button"
                    onClick={() => setOperatorDecision(decision)}
                    disabled={!run}
                    aria-pressed={operatorDecision === decision}
                    className={`min-w-0 rounded border px-3 py-2 text-xs font-black transition ${
                      operatorDecision === decision ? "border-emerald-300 bg-emerald-300 text-slate-950" : "border-slate-700 bg-slate-950 text-slate-300 hover:border-emerald-300"
                    } disabled:opacity-40`}
                  >
                    {decision}
                  </button>
                ))}
              </div>
            </div>

            <textarea
              value={employeeText}
              onChange={(event) => setEmployeeText(event.target.value)}
              aria-label="Operator signal text"
              placeholder="Describe the issue or manager request."
              className="mt-4 h-24 w-full resize-none rounded border border-slate-700 bg-slate-950 p-3 text-sm leading-relaxed text-slate-100 outline-none transition placeholder:text-slate-600 focus:border-cyan-300"
            />
            <div className="mt-3 flex flex-wrap gap-2">
              {AGENT_MODES.map((mode) => (
                <button
                  key={mode.id}
                  type="button"
                  onClick={() => setAgentMode(mode.id)}
                  aria-pressed={agentMode === mode.id}
                  className={`rounded border px-3 py-2 text-xs font-black transition ${
                    agentMode === mode.id ? "border-cyan-300 bg-cyan-300 text-slate-950" : "border-slate-700 bg-slate-950 text-slate-300 hover:border-cyan-400"
                  }`}
                >
                  {mode.label}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={() => void runHumanAgent()}
              disabled={isRunning || !employeeText.trim()}
              className="mt-3 w-full rounded bg-emerald-300 px-5 py-3 text-sm font-black text-slate-950 transition hover:bg-emerald-200 disabled:bg-slate-700 disabled:text-slate-400"
            >
              {isRunning ? "Running" : "Run response"}
            </button>
            {humanError && <div className="mt-3 rounded border border-red-500/30 bg-red-950/20 p-3 text-xs text-red-100">{humanError}</div>}

            <div className="mt-4 grid gap-2 sm:grid-cols-4">
              <MetricTile label="Role" value={run?.selected_role ?? route?.selected_role ?? "--"} accent="text-violet-100" />
              <MetricTile label="Gate" value={telemetry?.governance?.gate_status ?? "--"} accent="text-amber-100" />
              <MetricTile label="Eval" value={score(evalScore)} accent="text-emerald-100" />
              <MetricTile label="Dispatch" value={String((telemetry?.delivery?.summary?.sent ?? dispatches.length) || "--")} accent="text-cyan-100" />
            </div>
            {run?.operator_response?.summary && <p className="mt-3 rounded border border-slate-800 bg-slate-950 p-3 text-xs font-bold leading-relaxed text-slate-400">{run.operator_response.summary}</p>}
          </div>

          <div className="min-w-0 rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="text-[10px] font-black uppercase tracking-widest text-red-300">Priority queue</div>
            <div className="mt-3 grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[0.85fr_1.15fr]">
              <div className="min-w-0 rounded border border-slate-800 bg-slate-950 p-3">
                <div className="mb-3 text-[10px] font-black uppercase tracking-widest text-red-300">Incident domains</div>
                <BarChart rows={displayedIncidentDomainRows} empty="No incident domain summary." />
              </div>
              <div className="grid min-w-0 gap-2">
                {displayedPriorityQueue.map((item) => (
                  <div key={item.id} className="min-w-0 overflow-hidden rounded border border-slate-800 bg-slate-950 p-3">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                      <div className="min-w-0 truncate text-sm font-black text-slate-100">{item.title}</div>
                      <div className="flex shrink-0 items-center gap-2">
                        {item.selectionScore?.total !== undefined ? <span className="rounded bg-slate-900 px-2 py-1 text-[10px] font-black text-cyan-100">{item.selectionScore.total}</span> : null}
                        <StatusPill value={item.severity} />
                      </div>
                    </div>
                    <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-slate-500">{item.detail}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="mt-4 rounded border border-slate-800 bg-slate-950 p-3">
              <div className="mb-3 text-[10px] font-black uppercase tracking-widest text-cyan-300">Domain scorecard</div>
              <BarChart rows={domainRows} empty="No enterprise domain payload." />
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
