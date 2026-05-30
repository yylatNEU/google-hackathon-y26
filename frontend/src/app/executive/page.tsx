"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchParkPulseApi } from "@/lib/api";
import { useParkPulseState } from "@/hooks/useParkPulseState";
import type { ParkState } from "@/types/park";
import type { SimulationKind } from "@/types/platform";

type DomainId = "operations" | "safety" | "finance" | "planning" | "customer_experience";

type EnterpriseDomain = {
  id: string;
  label: string;
  score: number;
  status: string;
  agent: string;
  current: string;
  target: string;
  recommendedMove: string;
  ticketsOpen: number;
  leadingSignals?: string[];
};

type BacklogIssue = {
  id: string;
  executiveDomain?: string;
  domain: string;
  title: string;
  severity: string;
  current: string;
  target: string;
  businessImpact?: string;
  recommendedNext: string;
  evidence?: string[];
};

type MultiAgentCouncilRound = {
  step: number;
  agent: string;
  role: string;
  stance: string;
  finding: string;
  evidence?: string[];
};

type MultiAgentCouncilPayload = {
  leadAgent?: string;
  leadDomain?: string;
  selectedAction?: string;
  whyMultiAgent?: string;
  councilScore?: number;
  singleAgentBaseline?: {
    agent?: string;
    expectedScore?: number;
    recommendedAction?: string;
    missedRisks?: string[];
  };
  advantage?: {
    scoreLift?: number;
    hiddenRisksFound?: number;
    conflictsResolved?: number;
    policyBlocks?: number;
    handoffCount?: number;
  };
  rounds?: MultiAgentCouncilRound[];
};

type BacklogPayload = {
  status: string;
  unresolvedCount: number;
  enterpriseDomains?: EnterpriseDomain[];
  multiAgentCouncil?: MultiAgentCouncilPayload;
  enterpriseSummary?: {
    weakestDomain?: EnterpriseDomain;
    executiveQuestion?: string;
    answer?: string;
  };
  issues?: BacklogIssue[];
};

type IncidentTicket = {
  id: string;
  source: string;
  domain: string;
  title: string;
  severity: string;
  status: string;
  summary: string;
  recommendedHumanCall: string;
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

type DataEndpointStatus = {
  label: string;
  status: "loading" | "live" | "degraded";
  detail: string;
};

type DomainAgentDecision = {
  posture: "allow" | "review" | "block" | "act" | "observe";
  riskScore: number;
  confidencePct: number;
  recommendation: string;
  rationale: string;
  policyGate: string;
  conflict: string;
  memoryNote: string;
  actionCandidate: string;
  evidence: string[];
};

const DOMAIN_CONFIG: Record<DomainId, {
  label: string;
  agent: string;
  path: string;
  headline: string;
  simulation: { kind: SimulationKind; targetId: string; intensity: number; label: string };
  signalTerms: string[];
  kpis: Array<{ label: string; read: (state: ParkState) => string }>;
}> = {
  operations: {
    label: "Operations",
    agent: "Operations Agent",
    path: "/executive/operations",
    headline: "Run the park through rides, queues, staff, food, and throughput.",
    simulation: { kind: "ride_failure", targetId: "dragonCoaster", intensity: 85, label: "Inject ride/queue operating stress" },
    signalTerms: ["Food", "ride", "staff", "Showtime", "operations", "queue"],
    kpis: [
      { label: "Ride conflicts", read: (state) => `${state.parkOps.rideConflictCount}` },
      { label: "At-risk rides", read: (state) => `${state.parkOps.atRiskRides}` },
      { label: "Staff ready", read: (state) => `${state.parkOps.staffReadyPct}%` },
      { label: "Food pressure", read: (state) => `${state.operatingClock?.foodRetailLifecycle.mobileOrderBacklogPressurePct ?? "--"}%` },
    ],
  },
  safety: {
    label: "Safety",
    agent: "Safety/Policy Agent",
    path: "/executive/safety",
    headline: "Run the park through access routes, storms, medical/security capacity, and policy gates.",
    simulation: { kind: "weather_alert", targetId: "indoorHub", intensity: 88, label: "Inject safety/access stress" },
    signalTerms: ["Safety", "incident_readiness", "crowd_flow", "weather", "storm", "medical"],
    kpis: [
      { label: "Storm risk", read: (state) => `${state.weather.stormRisk}%` },
      { label: "Medical teams", read: (state) => `${state.staffing.medicalTeams}` },
      { label: "Security teams", read: (state) => `${state.staffing.securityTeams}` },
      { label: "Max path", read: (state) => `${Math.max(...state.guestFlow.paths.map((path) => path.congestionLevel), 0)}%` },
    ],
  },
  finance: {
    label: "Finance",
    agent: "Finance Agent",
    path: "/executive/finance",
    headline: "Run the park through refund exposure, lost throughput, labor, food, and energy cost.",
    simulation: { kind: "food_spike", targetId: "foodCourt1", intensity: 82, label: "Inject finance exposure stress" },
    signalTerms: ["Finance", "Food", "Guest Care", "energy", "refund", "revenue", "labor"],
    kpis: [
      { label: "Grid load", read: (state) => `${state.energy.gridLoadPercent}%` },
      { label: "Utility price", read: (state) => `$${state.energy.utilityPricePerMwh}/MWh` },
      { label: "Care cases", read: (state) => `${state.guestCare?.openCases ?? "--"}` },
      { label: "Callouts", read: (state) => `${state.staffing.openCallouts}` },
    ],
  },
  planning: {
    label: "Planning",
    agent: "Planning Agent",
    path: "/executive/planning",
    headline: "Run the park through showtime waves, route capacity, staffing lead time, and 180-minute plans.",
    simulation: { kind: "demand_spike", targetId: "coveredPlaza", intensity: 88, label: "Inject showtime planning stress" },
    signalTerms: ["Planning", "Showtime", "parade", "fireworks", "forecast", "crowd_flow"],
    kpis: [
      { label: "Readiness", read: (state) => `${state.planningAgent?.readinessPct ?? "--"}%` },
      { label: "Horizon", read: (state) => `${state.planningAgent?.plannerHorizonMinutes ?? "--"}m` },
      { label: "Traffic risk", read: (state) => `${state.operatingClock?.eventSchedule.eventTrafficRiskPct ?? "--"}%` },
      { label: "Next event", read: (state) => state.operatingClock?.eventSchedule.nextEvent?.name ?? "--" },
    ],
  },
  customer_experience: {
    label: "Customer Experience",
    agent: "Customer Experience Agent",
    path: "/executive/customer",
    headline: "Run the park through trust, fairness, care queues, sentiment, and guest recovery.",
    simulation: { kind: "demand_spike", targetId: "coasterPlaza", intensity: 84, label: "Inject guest trust stress" },
    signalTerms: ["Customer Experience", "Guest Care", "Fairness", "complaint", "care", "sentiment"],
    kpis: [
      { label: "Satisfaction", read: (state) => `${state.guestFlow.avgSatisfaction}%` },
      { label: "Complaint rate", read: (state) => `${state.guestCare?.complaintRatePct ?? "--"}%` },
      { label: "Fairness risk", read: (state) => `${state.operatingClock?.accessFairness?.publicComplaintRiskPct ?? "--"}%` },
      { label: "Open care", read: (state) => `${state.guestCare?.openCases ?? "--"}` },
    ],
  },
};

function domainFromPath(): DomainId {
  const path = window.location.pathname.toLowerCase();
  if (path.includes("/safety")) return "safety";
  if (path.includes("/finance")) return "finance";
  if (path.includes("/planning")) return "planning";
  if (path.includes("/customer")) return "customer_experience";
  return "operations";
}

function ticketMatchesDomain(ticket: IncidentTicket, config: (typeof DOMAIN_CONFIG)[DomainId]) {
  const haystack = `${ticket.domain} ${ticket.title} ${ticket.summary} ${ticket.source}`.toLowerCase();
  return config.signalTerms.some((term) => haystack.includes(term.toLowerCase()));
}

function issueMatchesDomain(issue: BacklogIssue, domain: DomainId, config: (typeof DOMAIN_CONFIG)[DomainId]) {
  const haystack = `${issue.executiveDomain ?? ""} ${issue.domain} ${issue.title} ${issue.current}`.toLowerCase();
  return issue.executiveDomain === domain || config.signalTerms.some((term) => haystack.includes(term.toLowerCase()));
}

function clampScore(value: number) {
  return Math.max(0, Math.min(100, Math.round(value)));
}

function maxNumber(values: number[]) {
  return values.length ? Math.max(...values) : 0;
}

function endpointErrorDetail(error: unknown) {
  return error instanceof Error ? error.message : "Endpoint unavailable";
}

function severityPressure(items: Array<{ severity?: string }>) {
  return maxNumber(items.map((item) => item.severity === "critical" ? 94 : item.severity === "warning" ? 76 : 52));
}

function buildDomainAgentDecision(
  domain: DomainId,
  state: ParkState,
  domainStatus: EnterpriseDomain | undefined,
  allDomains: EnterpriseDomain[],
  issues: BacklogIssue[],
  tickets: IncidentTicket[],
): DomainAgentDecision {
  const clock = state.operatingClock;
  const maxPathCongestion = maxNumber(state.guestFlow.paths.map((path) => path.congestionLevel));
  const weakestOtherDomain = allDomains
    .filter((item) => item.id !== domain)
    .sort((a, b) => a.score - b.score)[0];
  const baseRisk = 100 - (domainStatus?.score ?? 65);
  const ticketRisk = severityPressure(tickets);
  const issueRisk = severityPressure(issues);

  const shared = {
    operations: {
      signal: maxNumber([
        state.parkOps.rideConflictCount * 18,
        state.parkOps.atRiskRides * 14,
        Number(clock?.foodRetailLifecycle.mobileOrderBacklogPressurePct ?? 0),
        100 - Number(state.parkOps.staffReadyPct ?? 100),
      ]),
      recommendation: "Shift capacity before adding guest incentives: protect ride throughput, reduce food pressure, and avoid sending demand into constrained zones.",
      rationale: "Operations risk is driven by ride conflict, food backlog, and available staff readiness.",
      actionCandidate: "Queue intake hold + targeted capacity reroute + worker task for the highest-pressure bottleneck.",
      policyGate: "review queue gates, staff task load, and guest-message accuracy before dispatch",
      conflict: weakestOtherDomain ? `Must not improve operations by worsening ${weakestOtherDomain.label}.` : "No cross-domain blocker detected.",
      memoryNote: "Store bottleneck, selected capacity move, before/after queue pressure, and whether repeated actions stopped.",
    },
    safety: {
      signal: maxNumber([state.weather.stormRisk, maxPathCongestion, Number(clock?.staffLifecycle.breakPressurePct ?? 0), state.staffing.openCallouts * 4]),
      recommendation: "Safety constrains the next action: preserve access routes, emergency response, and policy gates before optimizing flow or revenue.",
      rationale: "Safety posture is based on weather risk, path congestion, break pressure, and open callouts.",
      actionCandidate: "Pre-stage safety/crowd leads, hold unsafe route pushes, and keep service-lane access clear.",
      policyGate: "block actions that increase service-lane congestion, medical privacy risk, or crowd compression",
      conflict: "May block Planning route splits, Operations throughput moves, or Finance cost-saving actions if access routes degrade.",
      memoryNote: "Store the blocked/allowed action, access-route pressure, staffing coverage, and policy reason for future safety gating.",
    },
    finance: {
      signal: maxNumber([
        state.energy.gridLoadPercent,
        (state.guestCare?.openCases ?? 0) * 2,
        state.staffing.openCallouts * 5,
        Number(clock?.foodRetailLifecycle.mobileOrderBacklogPressurePct ?? 0),
      ]),
      recommendation: "Rank interventions by cost-to-risk reduction before approving broad compensation, extra labor, or energy-heavy changes.",
      rationale: "Finance exposure rises when care cases, staffing gaps, food backlog, and energy load move together.",
      actionCandidate: "Compare targeted care message, menu suppression, labor redeploy, and energy load protection against estimated exposure.",
      policyGate: "review compensation promises, labor overtime, energy demand-charge risk, and revenue leakage",
      conflict: "May resist Customer Experience recovery offers or Operations staffing adds unless risk reduction justifies cost.",
      memoryNote: "Store estimated exposure, chosen intervention cost, avoided care cases, energy/load movement, and guest-trust impact.",
    },
    planning: {
      signal: maxNumber([
        100 - Number(state.planningAgent?.readinessPct ?? 72),
        Number(clock?.eventSchedule.eventTrafficRiskPct ?? 0),
        Number(clock?.eventSchedule.nextEvent?.minutesUntilStart ?? 60) < 15 ? 88 : 0,
        maxPathCongestion,
      ]),
      recommendation: "Operate the day as a connected plan: refresh the 30/90/180-minute route, staff, and showtime forecast before another isolated dispatch.",
      rationale: "Planning pressure combines readiness, event timing, traffic risk, and path congestion.",
      actionCandidate: "Run counterfactual route split for the next showtime wave and set decision deadlines for staff, message, and gate controls.",
      policyGate: "review route split against safety access, staff capacity, and customer fairness before commit",
      conflict: "May delay Operations or Finance quick wins until the plan protects the next showtime and exit wave.",
      memoryNote: "Store plan version, forecast assumption, selected route/staff timing, and whether wave pressure fell after execution.",
    },
    customer_experience: {
      signal: maxNumber([
        100 - state.guestFlow.avgSatisfaction,
        state.guestCare?.complaintRatePct ?? 0,
        state.guestCare?.openCases ?? 0,
        Number(clock?.accessFairness?.publicComplaintRiskPct ?? 0),
        Number(clock?.guestFeedbackLoop.careCaseAccumulationPct ?? 0),
      ]),
      recommendation: "Protect trust with transparent, segment-level messaging and bounded recovery options that do not overpromise.",
      rationale: "Customer experience risk is inferred from satisfaction, complaints, open cases, fairness pressure, and care lag.",
      actionCandidate: "Prepare guest-care summary, fairness explanation, and policy-safe recovery options for human approval.",
      policyGate: "review privacy, payment data, medical details, and compensation language before guest-facing action",
      conflict: "May challenge Finance cost controls and Operations reroutes when they increase complaint risk or perceived unfairness.",
      memoryNote: "Store top complaint drivers, fairness score, message sent, care-case movement, and sentiment response.",
    },
  } satisfies Record<DomainId, Omit<DomainAgentDecision, "posture" | "riskScore" | "confidencePct" | "evidence"> & { signal: number }>;

  const profile = shared[domain];
  const riskScore = clampScore(Math.max(baseRisk, profile.signal, ticketRisk, issueRisk));
  const posture: DomainAgentDecision["posture"] =
    domain === "safety" && riskScore >= 82
      ? "block"
      : riskScore >= 82
        ? "act"
        : riskScore >= 62 || issues.length || tickets.length
          ? "review"
          : riskScore >= 42
            ? "observe"
            : "allow";
  const confidencePct = clampScore(68 + Math.min(18, issues.length * 4 + tickets.length * 2) + (domainStatus ? 8 : 0));

  return {
    posture,
    riskScore,
    confidencePct,
    recommendation: profile.recommendation,
    rationale: domainStatus?.current ?? `Current ${DOMAIN_CONFIG[domain].label.toLowerCase()} pressure is inferred from the shared park twin.`,
    policyGate: profile.policyGate,
    conflict: profile.conflict,
    memoryNote: profile.memoryNote,
    actionCandidate: profile.actionCandidate,
    evidence: [
      ...(domainStatus?.leadingSignals ?? []),
      ...issues.slice(0, 2).map((issue) => `${issue.domain}: ${issue.current}`),
      ...tickets.slice(0, 2).map((ticket) => `${ticket.domain}: ${ticket.status}`),
    ].slice(0, 6),
  };
}

function DomainCouncilPanel({ council, activeAgent }: { council?: MultiAgentCouncilPayload | null; activeAgent: string }) {
  const rounds = council?.rounds ?? [];
  const activeRound = rounds.find((round) => round.agent === activeAgent) ?? rounds.find((round) => activeAgent.includes(round.agent.split("/")[0])) ?? rounds[0];

  return (
    <section className="rounded-lg border border-fuchsia-400/30 bg-slate-900 p-4 shadow-xl shadow-fuchsia-950/10">
      <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        <div>
          <div className="text-[10px] font-black uppercase tracking-widest text-fuchsia-300">Multi-agent council</div>
          <h2 className="mt-1 text-xl font-black text-slate-100">
            {council?.leadAgent ? `${council.leadAgent} is leading this cycle` : "Council is waiting for live backlog"}
          </h2>
          <p className="mt-2 text-sm leading-relaxed text-slate-400">
            {council?.selectedAction ?? "The domain agent is evaluated against other agents before an action can be dispatched."}
          </p>
          <div className="mt-3 grid gap-2 sm:grid-cols-4">
            {[
              ["Council", council?.councilScore ?? "--"],
              ["Lift", council?.advantage?.scoreLift != null ? `+${council.advantage.scoreLift}` : "--"],
              ["Risks", council?.advantage?.hiddenRisksFound ?? "--"],
              ["Blocks", council?.advantage?.policyBlocks ?? "--"],
            ].map(([label, value]) => (
              <div key={label} className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                <div className="mt-1 text-xl font-black text-fuchsia-100">{value}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-lg border border-slate-800 bg-slate-950 p-4">
          <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">This domain's council role</div>
          <h3 className="mt-1 text-lg font-black text-slate-100">{activeRound?.role ?? "pending"} · {activeRound?.stance ?? "pending"}</h3>
          <p className="mt-2 text-sm leading-relaxed text-slate-300">{activeRound?.finding ?? council?.whyMultiAgent ?? "Waiting for council evidence."}</p>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {(activeRound?.evidence ?? council?.singleAgentBaseline?.missedRisks ?? []).slice(0, 4).map((item) => (
              <div key={item} className="rounded border border-slate-800 bg-slate-900 px-3 py-2 text-xs font-bold text-slate-400">
                {item}
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

export default function ExecutivePage() {
  const initialDomain = useMemo(() => domainFromPath(), []);
  const [activeDomain, setActiveDomain] = useState<DomainId>(initialDomain);
  const [backlog, setBacklog] = useState<BacklogPayload | null>(null);
  const [incidents, setIncidents] = useState<IncidentPayload | null>(null);
  const [endpointStatuses, setEndpointStatuses] = useState<Record<"backlog" | "incidents", DataEndpointStatus>>({
    backlog: { label: "Operational backlog", status: "loading", detail: "Checking live executive backlog." },
    incidents: { label: "Incident analytics", status: "loading", detail: "Checking live incident analytics." },
  });
  const [isRunning, setIsRunning] = useState(false);
  const [lastRun, setLastRun] = useState<string>("Domain simulator ready.");
  const { parkState, isConnected, refreshParkState, applyParkState } = useParkPulseState();
  const config = DOMAIN_CONFIG[activeDomain];
  const domainStatus = backlog?.enterpriseDomains?.find((domain) => domain.id === activeDomain);
  const domainIssues = (backlog?.issues ?? []).filter((issue) => issueMatchesDomain(issue, activeDomain, config));
  const domainTickets = (incidents?.tickets ?? []).filter((ticket) => ticketMatchesDomain(ticket, config));
  const domainDecision = buildDomainAgentDecision(
    activeDomain,
    parkState,
    domainStatus,
    backlog?.enterpriseDomains ?? [],
    domainIssues,
    domainTickets,
  );
  const busiestZones = [...parkState.guestFlow.zones].sort((a, b) => b.density - a.density).slice(0, 6);
  const busiestPaths = [...parkState.guestFlow.paths].sort((a, b) => b.congestionLevel - a.congestionLevel).slice(0, 4);

  const loadDomainData = useCallback(async () => {
    setEndpointStatuses((current) => ({
      backlog: current.backlog.status === "live" ? current.backlog : { ...current.backlog, status: "loading", detail: "Checking live executive backlog." },
      incidents: current.incidents.status === "live" ? current.incidents : { ...current.incidents, status: "loading", detail: "Checking live incident analytics." },
    }));

    const [backlogResult, incidentResult] = await Promise.allSettled([
      fetchParkPulseApi("/api/park/operational-backlog", { timeoutMs: 6000 }),
      fetchParkPulseApi("/api/park/incident-analytics", { timeoutMs: 6000 }),
    ]);

    if (backlogResult.status === "fulfilled") {
      setBacklog((await backlogResult.value.json()) as BacklogPayload);
      setEndpointStatuses((current) => ({
        ...current,
        backlog: { label: "Operational backlog", status: "live", detail: "Live backlog is connected." },
      }));
    } else {
      setEndpointStatuses((current) => ({
        ...current,
        backlog: { label: "Operational backlog", status: "degraded", detail: endpointErrorDetail(backlogResult.reason) },
      }));
    }

    if (incidentResult.status === "fulfilled") {
      setIncidents((await incidentResult.value.json()) as IncidentPayload);
      setEndpointStatuses((current) => ({
        ...current,
        incidents: { label: "Incident analytics", status: "live", detail: "Live incident analytics is connected." },
      }));
    } else {
      setEndpointStatuses((current) => ({
        ...current,
        incidents: { label: "Incident analytics", status: "degraded", detail: endpointErrorDetail(incidentResult.reason) },
      }));
    }
  }, []);

  useEffect(() => {
    void loadDomainData();
    const interval = window.setInterval(() => void loadDomainData(), 8000);
    return () => window.clearInterval(interval);
  }, [loadDomainData]);

  const selectDomain = (domain: DomainId) => {
    setActiveDomain(domain);
    window.history.replaceState(null, "", DOMAIN_CONFIG[domain].path);
  };

  const runDomainSimulation = async () => {
    setIsRunning(true);
    setLastRun(`${config.agent} is applying ${config.simulation.kind.replaceAll("_", " ")} to ${config.simulation.targetId}.`);
    try {
      const response = await fetchParkPulseApi("/api/park/simulate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind: config.simulation.kind,
          target_id: config.simulation.targetId,
          intensity: config.simulation.intensity,
        }),
        timeoutMs: 9000,
      });
      const payload = (await response.json()) as { state?: unknown; message?: string };
      if (payload.state) applyParkState(payload.state);
      await loadDomainData();
      setLastRun(payload.message ?? `${config.agent} simulation completed.`);
    } catch (error) {
      setLastRun(error instanceof Error ? error.message : "Domain simulation failed.");
    } finally {
      setIsRunning(false);
    }
  };

  const advancePark = async () => {
    setIsRunning(true);
    setLastRun("Advancing the shared stimulated park clock.");
    try {
      const response = await fetchParkPulseApi("/api/park/tick", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ minutes: 8 }),
        timeoutMs: 9000,
      });
      const payload = (await response.json()) as { state?: unknown; message?: string };
      if (payload.state) applyParkState(payload.state);
      else await refreshParkState();
      await loadDomainData();
      setLastRun(payload.message ?? "Park clock advanced.");
    } catch (error) {
      setLastRun(error instanceof Error ? error.message : "Park tick failed.");
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <main className="min-h-screen bg-slate-950 px-4 py-5 font-sans text-slate-200 lg:px-8">
      <div className="mx-auto max-w-[1800px] space-y-5">
        <header className="rounded-lg border border-cyan-400/30 bg-slate-900 p-4 shadow-xl shadow-cyan-950/20">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Executive domain simulator</div>
              <h1 className="mt-1 text-3xl font-black text-slate-100">{config.label}</h1>
              <p className="mt-2 max-w-4xl text-sm leading-relaxed text-slate-400">
                Executive view of the same ParkPulse operating story: domain leaders see how live park pressure, agent actions, policy gates, and evidence receipts roll up into business decisions. {config.headline}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <a href="/" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-300 hover:border-cyan-400">Main park</a>
              <a href="/human" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-300 hover:border-cyan-400">Human workspace</a>
              <a href="/monitor" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-300 hover:border-cyan-400">Policy monitor</a>
              <button type="button" onClick={advancePark} disabled={isRunning} className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-cyan-200 disabled:opacity-50">
                Advance park
              </button>
              <button type="button" onClick={runDomainSimulation} disabled={isRunning} className="rounded border border-cyan-300 bg-cyan-300 px-3 py-2 text-xs font-black text-slate-950 disabled:opacity-50">
                {config.simulation.label}
              </button>
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            {(Object.keys(DOMAIN_CONFIG) as DomainId[]).map((domain) => (
              <button
                key={domain}
                type="button"
                onClick={() => selectDomain(domain)}
                className={`rounded border px-3 py-2 text-xs font-black ${domain === activeDomain ? "border-emerald-300 bg-emerald-300 text-slate-950" : "border-slate-700 bg-slate-950 text-slate-300 hover:border-emerald-400"}`}
              >
                {DOMAIN_CONFIG[domain].label}
              </button>
            ))}
          </div>
        </header>

        {Object.values(endpointStatuses).some((endpoint) => endpoint.status === "degraded") ? (
          <section className="rounded-lg border border-amber-400/40 bg-amber-500/10 p-4">
            <div className="text-[10px] font-black uppercase tracking-widest text-amber-200">Executive data degraded</div>
            <h2 className="mt-1 text-lg font-black text-amber-50">Some executive evidence is unavailable</h2>
            <div className="mt-3 grid gap-2 md:grid-cols-2">
              {Object.entries(endpointStatuses).map(([id, endpoint]) => (
                <div key={id} className="rounded border border-amber-400/20 bg-slate-950/70 px-3 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-black text-slate-100">{endpoint.label}</span>
                    <span className={`rounded px-2 py-1 text-[10px] font-black uppercase ${endpoint.status === "live" ? "bg-emerald-500/15 text-emerald-200" : endpoint.status === "loading" ? "bg-cyan-500/15 text-cyan-200" : "bg-amber-500/15 text-amber-100"}`}>
                      {endpoint.status}
                    </span>
                  </div>
                  <p className="mt-2 break-words text-xs leading-relaxed text-slate-400">{endpoint.detail}</p>
                </div>
              ))}
            </div>
          </section>
        ) : null}

        <DomainCouncilPanel council={backlog?.multiAgentCouncil} activeAgent={config.agent} />

        <section className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
          <div className="rounded-lg border border-emerald-400/30 bg-slate-900 p-4 shadow-xl shadow-emerald-950/10">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-emerald-300">Domain agent decision</div>
                <h2 className="mt-1 text-2xl font-black text-slate-100">{domainDecision.recommendation}</h2>
                <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-400">{domainDecision.rationale}</p>
              </div>
              <div className={`rounded-lg border px-4 py-3 text-right ${
                domainDecision.posture === "block"
                  ? "border-rose-400/50 bg-rose-500/10 text-rose-100"
                  : domainDecision.posture === "act"
                    ? "border-cyan-400/50 bg-cyan-500/10 text-cyan-100"
                    : domainDecision.posture === "review"
                      ? "border-amber-400/50 bg-amber-500/10 text-amber-100"
                      : "border-emerald-400/50 bg-emerald-500/10 text-emerald-100"
              }`}>
                <div className="text-[10px] font-black uppercase tracking-widest opacity-80">{domainDecision.posture}</div>
                <div className="text-3xl font-black">{domainDecision.riskScore}</div>
                <div className="text-xs font-bold opacity-80">{domainDecision.confidencePct}% confidence</div>
              </div>
            </div>
            <div className="mt-4 grid gap-3 lg:grid-cols-3">
              <div className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Action candidate</div>
                <div className="mt-2 text-xs font-bold leading-relaxed text-slate-300">{domainDecision.actionCandidate}</div>
              </div>
              <div className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Policy gate</div>
                <div className="mt-2 text-xs font-bold leading-relaxed text-slate-300">{domainDecision.policyGate}</div>
              </div>
              <div className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Memory note</div>
                <div className="mt-2 text-xs font-bold leading-relaxed text-slate-300">{domainDecision.memoryNote}</div>
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="text-[10px] font-black uppercase tracking-widest text-amber-300">Cross-domain conflict</div>
            <h2 className="mt-1 text-xl font-black text-slate-100">{domainDecision.conflict}</h2>
            <div className="mt-4 grid gap-2">
              {domainDecision.evidence.length ? domainDecision.evidence.map((item) => (
                <div key={item} className="rounded border border-slate-800 bg-slate-950 px-3 py-2 text-xs font-bold text-slate-300">
                  {item}
                </div>
              )) : (
                <div className="rounded border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-500">
                  No domain-specific evidence yet.
                </div>
              )}
            </div>
          </div>
        </section>

        <section className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-emerald-300">Shared stimulated park</div>
                <h2 className="mt-1 text-xl font-black text-slate-100">
                  {parkState.operatingClock?.phase.label ?? "Live park phase"} · {String(parkState.simTime.hour).padStart(2, "0")}:{String(parkState.simTime.minute).padStart(2, "0")}
                </h2>
                <p className="mt-2 text-sm leading-relaxed text-slate-400">{lastRun}</p>
              </div>
              <div className={`rounded px-3 py-2 text-xs font-black ${isConnected ? "bg-emerald-500/15 text-emerald-200" : "bg-amber-500/15 text-amber-200"}`}>
                {isConnected ? "backend live" : "fallback state"}
              </div>
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {config.kpis.map((kpi) => (
                <div key={kpi.label} className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{kpi.label}</div>
                  <div className="mt-2 text-2xl font-black text-cyan-100">{kpi.read(parkState)}</div>
                </div>
              ))}
            </div>

            <div className="mt-4 grid gap-3 lg:grid-cols-3">
              {busiestZones.map((zone) => (
                <div key={zone.id} className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-sm font-black text-slate-100">{zone.name}</div>
                    <div className="text-sm font-black text-cyan-200">{zone.density}%</div>
                  </div>
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-800">
                    <div className="h-full rounded-full bg-cyan-300" style={{ width: `${Math.max(0, Math.min(100, zone.density))}%` }} />
                  </div>
                  <div className="mt-2 text-[11px] text-slate-500">{zone.dominantIntent} · wait {zone.waitMins}m</div>
                </div>
              ))}
            </div>
          </div>

          <aside className="grid gap-4">
            <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
              <div className="text-[10px] font-black uppercase tracking-widest text-emerald-300">{config.agent}</div>
              <h2 className="mt-1 text-xl font-black text-slate-100">{domainStatus?.status ?? "loading"} · score {domainStatus?.score ?? "--"}</h2>
              <p className="mt-2 text-sm leading-relaxed text-slate-400">
                {domainStatus?.recommendedMove ?? (endpointStatuses.backlog.status === "degraded" ? "Operational backlog is unavailable; showing park-twin fallback context." : "Loading domain recommendation.")}
              </p>
              <div className="mt-3 rounded border border-slate-800 bg-slate-950 p-3 text-xs font-bold text-slate-300">
                {domainStatus?.target ?? (endpointStatuses.backlog.status === "degraded" ? endpointStatuses.backlog.detail : "Waiting for target state.")}
              </div>
            </div>

            <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Route pressure</div>
              <div className="mt-3 grid gap-2">
                {busiestPaths.map((path) => (
                  <div key={`${path.from}-${path.to}`} className="rounded border border-slate-800 bg-slate-950 px-3 py-2">
                    <div className="flex items-center justify-between gap-2 text-xs">
                      <span className="font-bold text-slate-300">{path.fromName} {"->"} {path.toName}</span>
                      <span className="font-black text-cyan-200">{path.congestionLevel}%</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </aside>
        </section>

        <section className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-amber-300">Domain backlog</div>
                <h2 className="mt-1 text-xl font-black text-slate-100">{domainIssues.length} open domain issues</h2>
              </div>
              <div className="rounded bg-slate-950 px-2 py-1 text-[10px] font-black uppercase text-slate-400">{backlog?.unresolvedCount ?? "--"} total</div>
            </div>
            <div className="mt-3 grid gap-3">
              {(domainIssues.length ? domainIssues : backlog?.issues?.slice(0, 3) ?? []).map((issue) => (
                <div key={issue.id} className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{issue.domain} · {issue.severity}</div>
                  <div className="mt-1 text-sm font-black text-slate-100">{issue.title}</div>
                  <div className="mt-2 text-xs font-bold text-amber-100">{issue.current}</div>
                  <p className="mt-2 text-xs leading-relaxed text-slate-400">{issue.recommendedNext}</p>
                </div>
              ))}
              {!domainIssues.length && !backlog?.issues?.length ? (
                <div className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-amber-300">{endpointStatuses.backlog.status}</div>
                  <div className="mt-1 text-sm font-black text-slate-100">Backlog evidence unavailable</div>
                  <p className="mt-2 break-words text-xs leading-relaxed text-slate-400">
                    {endpointStatuses.backlog.status === "degraded" ? endpointStatuses.backlog.detail : "Waiting for live operational backlog."}
                  </p>
                </div>
              ) : null}
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Human-review tickets</div>
                <h2 className="mt-1 text-xl font-black text-slate-100">{domainTickets.length} domain tickets</h2>
              </div>
              <div className="rounded bg-slate-950 px-2 py-1 text-[10px] font-black uppercase text-emerald-300">
                Mongo {incidents?.mongoPersistence?.status ?? "pending"}
              </div>
            </div>
            <div className="mt-3 grid gap-3">
              {(domainTickets.length ? domainTickets : incidents?.tickets?.slice(0, 4) ?? []).map((ticket) => (
                <div key={ticket.id} className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{ticket.domain} · {ticket.source}</div>
                      <div className="mt-1 text-sm font-black text-slate-100">{ticket.title}</div>
                    </div>
                    <div className="rounded bg-slate-900 px-2 py-1 text-[10px] font-black uppercase text-cyan-200">{ticket.status}</div>
                  </div>
                  <p className="mt-2 text-xs leading-relaxed text-slate-400">{ticket.summary}</p>
                  <div className="mt-2 rounded border border-slate-800 bg-slate-900 p-2 text-xs font-bold text-amber-100">{ticket.recommendedHumanCall}</div>
                </div>
              ))}
              {!domainTickets.length && !incidents?.tickets?.length ? (
                <div className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-amber-300">{endpointStatuses.incidents.status}</div>
                  <div className="mt-1 text-sm font-black text-slate-100">Incident evidence unavailable</div>
                  <p className="mt-2 break-words text-xs leading-relaxed text-slate-400">
                    {endpointStatuses.incidents.status === "degraded" ? endpointStatuses.incidents.detail : "Waiting for live incident analytics."}
                  </p>
                </div>
              ) : null}
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
