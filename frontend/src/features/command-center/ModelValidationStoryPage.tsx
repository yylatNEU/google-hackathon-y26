"use client";

import { useMemo, useState } from "react";
import { fetchParkPulseApi } from "@/lib/api";

type LivePark = {
  scenario: string;
  scenarioName: string;
  topZone: string;
  topZoneDensity: number;
  topZoneWaitMins: number;
  operatorEscalation: string;
  emergencyAccessBlocked: boolean;
  maintenanceClearanceRequired: number;
  alertTitles: string[];
  evidenceSources: Record<string, string>;
};

type RewardStatus = {
  status: string;
  hardDecisionEnabled: boolean;
  rewardField: string;
  compositeWeight: number;
  weights: Record<string, number>;
};

type RoleRun = {
  role: string;
  status: string;
  dispatchCount: number;
  calledToolCount: number;
  headline?: string | null;
  policyGates?: string[] | null;
};

type ModelRow = {
  model: string;
  evidence: string;
  hardDecision: number | string;
  dispatch: string;
  policy: string;
  score: string;
  boundary: string;
};

type TimelineStep = {
  phase: string;
  owner: string;
  evidence: string;
  decision: string;
  toolUse: string;
  result: string;
};

type TradeoffRow = {
  pressure: string;
  wants: string;
  conflict: string;
  resolution: string;
  owner: string;
};

type ImpactMetric = {
  label: string;
  value: string;
  detail: string;
  tone: "cyan" | "amber" | "lime" | "white";
};

type MatrixCase = {
  caseKey: string;
  issue: string;
  target: string;
  before: number;
  latestAfter: number;
  baselineAfter: number;
  executed: number;
  held: number;
  memory: number;
  hardDecision: number;
  lift: string;
};

type AnalysisDelta = {
  label: string;
  old: string;
  now: string;
  proof: string;
  status: "improved" | "partial" | "gap";
};

const validationGeneratedAt = "2026-06-06T21:01:46.660754+00:00";

const initialLivePark: LivePark = {
  scenario: "ride_down",
  scenarioName: "Ride Down + Crowd Redistribution",
  topZone: "coasterPlaza",
  topZoneDensity: 118,
  topZoneWaitMins: 61,
  operatorEscalation: "required",
  emergencyAccessBlocked: false,
  maintenanceClearanceRequired: 1,
  alertTitles: ["Dragon Coaster downtime", "Food Court 2 staffing gap"],
  evidenceSources: {
    food_ops: "simulated_state",
    guest_flow: "simulated_state",
    operator_signal: "simulated_state",
    ride_ops: "simulated_state",
    staffing: "simulated_state",
    weather: "simulated_state",
  },
};

const initialRewardStatus: RewardStatus = {
  status: "ready",
  hardDecisionEnabled: true,
  rewardField: "hard_decision_activation_reward",
  compositeWeight: 0.1,
  weights: {
    trace_reward: 0.1,
    policy_reward: 0.18,
    execution_reward: 0.17,
    operational_reward: 0.35,
    learning_reward: 0.1,
    hard_decision_activation_reward: 0.1,
  },
};

const roleRuns: RoleRun[] = [
  {
    role: "Scan",
    status: "complete",
    dispatchCount: 0,
    calledToolCount: 8,
    headline: "Scan Agent found early park signals.",
    policyGates: null,
  },
  {
    role: "React",
    status: "complete",
    dispatchCount: 3,
    calledToolCount: 13,
    headline: "Redirect Food Court A demand to available food capacity",
    policyGates: ["ride_safety_authority", "labor_break_protection", "medical_no_diagnosis", "equipment_bounds"],
  },
  {
    role: "Proact",
    status: "complete",
    dispatchCount: 3,
    calledToolCount: 10,
    headline: "Forecasted follow-on bottleneck and prepared bounded receiver payloads.",
    policyGates: ["false_alarm_risk", "medical_no_diagnosis", "equipment_bounds", "learning_requires_observed_response"],
  },
];

const modelRows: ModelRow[] = [
  {
    model: "Latest deployed model on live park",
    evidence: "Cloud Run live state + agent-role-run POSTs",
    hardDecision: "scorer active; per-turn score not emitted yet",
    dispatch: "scan 0, react 3, proact 3",
    policy: "role policy gates present on react/proact",
    score: "live behavior validated",
    boundary: "same live park state, latest model only",
  },
  {
    model: "Latest v2 scored batch",
    evidence: "Fresh v2 live-feed operating-cycle report",
    hardDecision: 0.946,
    dispatch: "42 executed / 88 held",
    policy: "risk_lift_success: 8",
    score: "spread 0.063",
    boundary: "scored batch, not the Cloud Run state snapshot",
  },
  {
    model: "Intermediate scored model",
    evidence: "Archived scored checkpoint",
    hardDecision: 1,
    dispatch: "41 executed / 88 held",
    policy: "risk_lift_success: 8",
    score: "spread 0.0",
    boundary: "scoring existed but saturated",
  },
  {
    model: "Previous policy replay",
    evidence: "Counterfactual replay matrix",
    hardDecision: 78.738,
    dispatch: "replay factor only",
    policy: "average replay factor 0.833",
    score: "congestion 60.99",
    boundary: "deterministic replay, not deployed live",
  },
  {
    model: "Monitor-only baseline",
    evidence: "No-action baseline",
    hardDecision: 0,
    dispatch: "0 executed / all held",
    policy: "not_attempted",
    score: "congestion 46.5",
    boundary: "no hard-decision activation",
  },
];

const evidenceBoundary = [
  "Latest deployed model was validated against the live Cloud Run park state through /api/park/state-lite and /api/park/agent-role-run.",
  "The deployed reward scorer is active, but /api/park/agent-role-run does not emit per-turn hard_decision_activation_reward yet.",
  "Intermediate and previous model rows are archived scored/replay benchmarks, not live actors on the current Cloud Run state.",
  "Monitor-only baseline means no action and no hard-decision activation.",
];

const topVerdict = [
  {
    label: "Visible behavior changed",
    value: "6 live dispatches",
    detail: "React and Proact each executed 3 bounded actions; Scan correctly stayed read-only.",
    tone: "lime" as const,
  },
  {
    label: "Scoring changed",
    value: "partial",
    detail: "Hard-decision scorer is deployed, but same-turn role-run receipts still do not emit the reward vector.",
    tone: "amber" as const,
  },
  {
    label: "Learning changed",
    value: "not fully closed",
    detail: "Proact exposes an outcome_events memory target; React/Scan still report deferred hot-path persistence.",
    tone: "amber" as const,
  },
  {
    label: "Report changed",
    value: "case file",
    detail: "The page now separates evidence, negotiation, tool execution, impact, model comparison, and gaps.",
    tone: "cyan" as const,
  },
];

const analysisDeltas: AnalysisDelta[] = [
  {
    label: "Decision evidence",
    old: "Old report mostly said a result happened and listed model rows.",
    now: "New report reconstructs state evidence: crowd, ride clearance, fairness, staff pressure, food backlog, and sentiment.",
    proof: "Park-state evidence cards plus live state-lite source paths.",
    status: "improved",
  },
  {
    label: "Agent negotiation",
    old: "Old report did not make departmental conflict visible.",
    now: "New report shows what Ops, Safety, Food, Labor, Guest, Compliance, Finance, and Tool Executor each constrained.",
    proof: "Agent negotiation board with conflict and final owner per trade-off.",
    status: "improved",
  },
  {
    label: "Hard decision",
    old: "Old report could imply the model was simply holding or summarizing.",
    now: "New report shows the latest path selected a safe substitute instead of reopening the ride or leaving the problem unresolved.",
    proof: "Decision loop steps 3-5 and live dispatch count: guest app, worker task, equipment command.",
    status: "improved",
  },
  {
    label: "Park impact",
    old: "Old report did not make action impact easy to see.",
    now: "New report calls out food backlog -18, congestion -25, density -16, queued guests -180, take rate 52%, staff ack 3/3.",
    proof: "Material park impact panel.",
    status: "improved",
  },
  {
    label: "Model result",
    old: "Old report and new report both still lack exact same-turn reward scoring for the deployed role-run.",
    now: "New report states that limitation up front instead of hiding it in a footnote.",
    proof: "Remaining gap: /api/park/agent-role-run must emit hard_decision_activation_reward on the live receipt.",
    status: "partial",
  },
  {
    label: "Closed learning loop",
    old: "Old report did not clearly separate memory target, deferred persistence, and train-later boundary.",
    now: "New report separates training material from actual retraining and calls out deferred Mongo/write paths.",
    proof: "Memory and learning section plus instrumentation gaps.",
    status: "gap",
  },
];

const liveStateDetails = [
  { label: "Operating wave", value: "11:45 / morning ride chase", detail: "Demand pressure 83%, ride-seeking intent 90%, next hotspot coveredPlaza in 15 min." },
  { label: "Ride boundary", value: "maintenance clearance blocked", detail: "Dragon Coaster WO-DRAGON-1042 requires maintenance lead and ride safety supervisor signoff." },
  { label: "Crowd fairness", value: "critical", detail: "Fast Lane mix created 24 min standby delta and 100% aggregate public complaint risk." },
  { label: "Staff pressure", value: "6 min redeploy delay", detail: "Midday break pressure 38%, fatigue pressure 40%, certification constraint ride_console_and_crowd_lead." },
  { label: "Food pressure", value: "48.94% mobile-order backlog", detail: "Food Court load is not failed yet, but it is a bad receiver for unrestricted coaster overflow." },
  { label: "Guest care", value: "deteriorating sentiment", detail: "Complaint lag 11 min and care-case accumulation 64.52% mean recovery should happen before guests flood support." },
];

const decisionTimeline: TimelineStep[] = [
  {
    phase: "1. Observe",
    owner: "Scan Agent",
    evidence: "Coaster Plaza 118% density, 61 min wait, ride-down scenario, maintenance clearance blocked, food backlog rising.",
    decision: "Do not dispatch. Produce evidence and recommend escalation into an acting role.",
    toolUse: "get_noisy_observation, get_park_state, get_zone_density, get_ride_status, score_decision_quality",
    result: "0 dispatches by design; read-only proof created before action.",
  },
  {
    phase: "2. Interpret",
    owner: "React Agent",
    evidence: "Operator asked for safest bounded action without reopening the ride or overloading food areas.",
    decision: "Treat this as a constrained redistribution problem, not a ride-reopen problem.",
    toolUse: "get_park_state, get_ride_status, get_food_capacity, get_staff_constraints, retrieve_similar_incidents",
    result: "Rejected stale scenario copy and avoided routing new demand into Food Court A.",
  },
  {
    phase: "3. Negotiate",
    owner: "Ops + Safety + Food + Labor",
    evidence: "Ride safety authority blocks reopen; food and crowd data make Food Court A a bad sink; staffing has break/fatigue constraints.",
    decision: "Use a bounded substitute: redirect to Food Court B/Main Street, pause constrained mobile intake, assign staff at pickup edge.",
    toolUse: "compare_action_candidates, simulate_action",
    result: "A lower-risk action replaced the harder unsafe option instead of leaving the case unresolved.",
  },
  {
    phase: "4. Govern",
    owner: "Compliance / Policy Judge",
    evidence: "Policy gates: ride_safety_authority, labor_break_protection, medical_no_diagnosis, equipment_bounds.",
    decision: "Allow only guest guidance, worker tasking, and bounded equipment/menu control.",
    toolUse: "validate_policy",
    result: "Human approval was not required because no ride safety override, medical diagnosis, or labor-rule breach was attempted.",
  },
  {
    phase: "5. Execute",
    owner: "Tool Executor",
    evidence: "Three receiver payloads matched the incident and policy boundary.",
    decision: "Send guest app message, assign worker task, command menu-control equipment.",
    toolUse: "dispatch_guest_message, dispatch_worker_task, dispatch_equipment_command",
    result: "3 dispatches: guest message sent, 2 workers acknowledged, mobile-order intake suppressed.",
  },
  {
    phase: "6. Learn",
    owner: "Proact Agent + Memory",
    evidence: "Observed take rate 0.52, follow-through 0.61, 146 guests followed proactive routing, 3 staff acknowledgments.",
    decision: "Carry forward the rule that family-safe cooling route plus nearby food alternative beats generic rerouting.",
    toolUse: "score_outcome, write_decision_memory",
    result: "Memory write target exists, but some hot-path persistence was deferred; this is still a reportable gap.",
  },
];

const tradeoffs: TradeoffRow[] = [
  {
    pressure: "Ride throughput",
    wants: "Reopen or recover Dragon Coaster capacity.",
    conflict: "Maintenance clearance is blocked and reopen automation is explicitly forbidden.",
    resolution: "Do not reopen; shift demand and keep work order signoff with maintenance and safety.",
    owner: "Maintenance + Safety",
  },
  {
    pressure: "Crowd congestion",
    wants: "Move guests away from Coaster Plaza.",
    conflict: "Indoor hub and food locations can become secondary bottlenecks.",
    resolution: "Split demand to Food Court B, Main Street, Theater B cooling, and hold constrained Food Court A intake.",
    owner: "Ops + Food",
  },
  {
    pressure: "Guest satisfaction",
    wants: "Give clear guidance quickly.",
    conflict: "Overpromising compensation or medical/accommodation language creates compliance risk.",
    resolution: "Send factual route guidance only; keep sensitive recovery language under review.",
    owner: "Guest + Compliance",
  },
  {
    pressure: "Labor coverage",
    wants: "Move enough staff to prevent breakdown.",
    conflict: "Break pressure and fatigue constraints prevent unlimited redeployment.",
    resolution: "Assign two food-service workers and three care/crowd staff with bounded tasks, not open-ended coverage.",
    owner: "Labor + Food",
  },
  {
    pressure: "Revenue",
    wants: "Keep food throughput and mobile order sales moving.",
    conflict: "Pushing demand into a strained pickup point increases guest frustration and safety crowding.",
    resolution: "Pause constrained mobile intake while steering demand to capacity that can absorb it.",
    owner: "Finance + Commerce",
  },
];

const impactMetrics: ImpactMetric[] = [
  { label: "Food backlog", value: "-18", detail: "React projected mobile-order pressure routed away from Food Court A.", tone: "lime" },
  { label: "Congestion", value: "-25", detail: "Proact projected crowd-care congestion reduced after preventive action.", tone: "lime" },
  { label: "Density", value: "-16", detail: "Projected Food Court A crowd-care density after proactive split.", tone: "cyan" },
  { label: "Queued guests", value: "-180", detail: "Estimated guests removed from the worsening receiver path.", tone: "cyan" },
  { label: "Guest take rate", value: "52%", detail: "Observed proactive guest-app route take rate from 240-sample response.", tone: "white" },
  { label: "Staff ack", value: "3/3", detail: "Care/crowd staff acknowledged proactive staging task.", tone: "amber" },
];

const caseMatrix: MatrixCase[] = [
  { caseKey: "cycle_1", issue: "radio_dead_zone", target: "coasterPlaza", before: 118, latestAfter: 74, baselineAfter: 115, executed: 5, held: 11, memory: 3, hardDecision: 99.8, lift: "risk_lift_success" },
  { caseKey: "cycle_2", issue: "mobile_order_outage", target: "foodCourt1", before: 119, latestAfter: 102, baselineAfter: 125, executed: 6, held: 11, memory: 4, hardDecision: 94.3, lift: "risk_lift_success" },
  { caseKey: "cycle_3", issue: "sensor_anomaly", target: "riverRafts", before: 120, latestAfter: 105, baselineAfter: 125, executed: 5, held: 11, memory: 3, hardDecision: 93.7, lift: "risk_lift_success" },
  { caseKey: "cycle_4", issue: "heat_index_spike", target: "outdoor_park", before: 118, latestAfter: 109, baselineAfter: 123, executed: 5, held: 11, memory: 3, hardDecision: 93.9, lift: "risk_lift_success" },
  { caseKey: "cycle_5", issue: "inventory_stockout", target: "foodCourt1", before: 119, latestAfter: 102, baselineAfter: 125, executed: 6, held: 11, memory: 4, hardDecision: 94.1, lift: "risk_lift_success" },
  { caseKey: "cycle_6", issue: "lightning_delay", target: "outdoor_park", before: 118, latestAfter: 109, baselineAfter: 123, executed: 5, held: 11, memory: 3, hardDecision: 93.9, lift: "risk_lift_success" },
  { caseKey: "cycle_7", issue: "ticketing_gate_surge", target: "mainGate", before: 118, latestAfter: 112, baselineAfter: 120, executed: 5, held: 11, memory: 3, hardDecision: 93.5, lift: "risk_lift_success" },
  { caseKey: "cycle_8", issue: "parking_arrival_wave", target: "mainGate", before: 118, latestAfter: 113, baselineAfter: 121, executed: 5, held: 11, memory: 3, hardDecision: 93.5, lift: "risk_lift_success" },
];

const modelBehaviorRows = [
  {
    model: "Current challenger",
    reward: "77.15",
    hardDecision: "94.59",
    safety: "90",
    congestion: "64.12",
    satisfaction: "75",
    action: "42 executed / 88 held",
    explanation: "Reads fresh feeds, retrieves memory, negotiates tradeoffs, executes policy-passed controlled actions, and lifts approved risky substitutes through Tool Executor.",
  },
  {
    model: "Previous after guardrail split",
    reward: "73.30",
    hardDecision: "not same-case",
    safety: "not same-case",
    congestion: "not same-case",
    satisfaction: "not same-case",
    action: "blocked by 5 feed gates",
    explanation: "Had better reward math after guardrail separation, but live-feed freshness gates were stale, so promotion stayed held.",
  },
  {
    model: "Earlier mixed-guardrail model",
    reward: "40.75",
    hardDecision: "not same-case",
    safety: "not same-case",
    congestion: "not same-case",
    satisfaction: "not same-case",
    action: "4 risk-lift slices held",
    explanation: "Mixed QA guardrail failures into promotion math, so operationally useful risk-lift behavior was hidden by unrelated guardrail penalties.",
  },
  {
    model: "Monitor-only baseline",
    reward: "46.50",
    hardDecision: "0",
    safety: "80",
    congestion: "46.50",
    satisfaction: "75.38",
    action: "0 executed / all held",
    explanation: "Does not learn, lift risk, or execute relief actions; it watches the issue while path pressure remains high.",
  },
];

const trainingMaterial = [
  { label: "State context", value: "scenario, zone density, queue pressure, ride clearance, food backlog, staffing, fairness, sentiment" },
  { label: "Decision labels", value: "hard_decision_lifted_success, risk_lift_success, monitor_only_hold, operational_regression_detected" },
  { label: "Tool trace", value: "read tools, candidate comparison, simulation, policy validation, dispatch calls, outcome scoring, memory write" },
  { label: "Outcome signal", value: "take rate, follow-through, staff acknowledgment, applied equipment command, congestion and density deltas" },
  { label: "Counterfactual", value: "same-case monitor-only baseline for current cases; snapshot comparison only for previous models" },
  { label: "Do-not-train boundary", value: "no immediate retrain from one case; collect enough measured cases, then train and promote only policy-safe slices" },
];

const openInstrumentationGaps = [
  "Live /api/park/agent-role-run does not yet attach per-turn hard_decision_activation_reward to the same receipt that dispatched the action.",
  "React and Scan hot paths report memory persistence as deferred/connected=false, even though Proact exposes a Mongo outcome_events target.",
  "Delivery durability fell back to jsonl_outbox on the lazy hot path; it is auditable, but not yet a clean receiver-durability success.",
  "Previous/intermediate comparisons are useful training context, but only current-vs-monitor is same-case ground truth.",
];

function label(value: unknown, fallback = "--") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value).replaceAll("_", " ");
}

function compactList(values: string[], max = 3) {
  if (!values.length) return "--";
  const shown = values.slice(0, max).join(", ");
  return values.length > max ? `${shown} +${values.length - max}` : shown;
}

function barWidth(value: number, max = 1) {
  return `${Math.max(0, Math.min(100, (value / max) * 100)).toFixed(1)}%`;
}

function scoreText(value: ModelRow["hardDecision"]) {
  if (typeof value === "number") return value > 1 ? value.toFixed(1) : value.toFixed(3);
  return value;
}

function Metric({ label: metricLabel, value, detail, tone = "cyan" }: { label: string; value: string | number | boolean; detail: string; tone?: "cyan" | "amber" | "lime" | "white" }) {
  const toneClass = {
    cyan: "border-cyan-400/25 text-cyan-100",
    amber: "border-amber-400/30 text-amber-100",
    lime: "border-lime-400/25 text-lime-100",
    white: "border-slate-700 text-white",
  }[tone];
  return (
    <div className={`min-h-[112px] rounded-lg border bg-slate-950 p-4 ${toneClass}`}>
      <div className="text-[10px] font-black uppercase tracking-[0.24em] text-slate-500">{metricLabel}</div>
      <div className="mt-2 text-3xl font-black tracking-normal">{String(value)}</div>
      <div className="mt-2 text-xs leading-5 text-slate-400">{detail}</div>
    </div>
  );
}

function HardDecisionCell({ value }: { value: ModelRow["hardDecision"] }) {
  if (typeof value !== "number") return <span className="text-slate-300">{value}</span>;
  const max = value > 1 ? 100 : 1;
  return (
    <div>
      <div className="relative h-7 overflow-hidden rounded border border-slate-800 bg-slate-950">
        <div className="h-full bg-gradient-to-r from-cyan-500 to-lime-300" style={{ width: barWidth(value, max) }} />
        <div className="absolute inset-0 flex items-center justify-center text-xs font-black text-white">{scoreText(value)}</div>
      </div>
    </div>
  );
}

function statusClass(status: AnalysisDelta["status"]) {
  if (status === "improved") return "border-lime-300/30 bg-lime-950/20 text-lime-100";
  if (status === "partial") return "border-amber-300/30 bg-amber-950/20 text-amber-100";
  return "border-rose-300/30 bg-rose-950/20 text-rose-100";
}

function parseLivePark(payload: Record<string, unknown>): LivePark {
  const guestFlow = (payload.guestFlow ?? {}) as Record<string, unknown>;
  const scenario = (guestFlow.activeScenario ?? {}) as Record<string, unknown>;
  const zones = Array.isArray(guestFlow.zones) ? (guestFlow.zones as Array<Record<string, unknown>>) : [];
  const topZone = zones.reduce<Record<string, unknown>>((best, zone) => {
    const density = Number(zone.density ?? 0);
    const bestDensity = Number(best.density ?? -1);
    return density > bestDensity ? zone : best;
  }, {});
  const readiness = (payload.incidentReadiness ?? {}) as Record<string, unknown>;
  const maintenance = (payload.maintenance ?? {}) as Record<string, unknown>;
  const alerts = Array.isArray(payload.alerts) ? (payload.alerts as Array<Record<string, unknown>>) : [];
  const evidence = (payload.liveFeedEvidence ?? {}) as Record<string, Record<string, unknown>>;
  return {
    scenario: String(scenario.key ?? initialLivePark.scenario),
    scenarioName: String(scenario.name ?? initialLivePark.scenarioName),
    topZone: String(topZone.id ?? initialLivePark.topZone),
    topZoneDensity: Number(topZone.density ?? initialLivePark.topZoneDensity),
    topZoneWaitMins: Number(topZone.waitMins ?? initialLivePark.topZoneWaitMins),
    operatorEscalation: String(readiness.operatorEscalation ?? initialLivePark.operatorEscalation),
    emergencyAccessBlocked: Boolean(readiness.emergencyAccessBlocked ?? initialLivePark.emergencyAccessBlocked),
    maintenanceClearanceRequired: Number(maintenance.clearanceRequiredCount ?? initialLivePark.maintenanceClearanceRequired),
    alertTitles: alerts.map((alert) => String(alert.title ?? "")).filter(Boolean),
    evidenceSources: Object.fromEntries(Object.entries(evidence).map(([key, row]) => [key, String(row?.source ?? "unknown")])),
  };
}

function parseRewardStatus(payload: Record<string, unknown>): RewardStatus {
  const hard = (payload.hard_decision_activation ?? {}) as Record<string, unknown>;
  return {
    status: String(payload.status ?? initialRewardStatus.status),
    hardDecisionEnabled: Boolean(hard.enabled ?? initialRewardStatus.hardDecisionEnabled),
    rewardField: String(hard.reward_field ?? initialRewardStatus.rewardField),
    compositeWeight: Number(hard.composite_weight ?? initialRewardStatus.compositeWeight),
    weights: ((payload.composite_reward_weights as Record<string, number> | undefined) ?? initialRewardStatus.weights),
  };
}

export function ModelValidationStoryPage() {
  const [livePark, setLivePark] = useState(initialLivePark);
  const [rewardStatus, setRewardStatus] = useState(initialRewardStatus);
  const [refreshState, setRefreshState] = useState<"idle" | "loading" | "complete" | "error">("idle");
  const [error, setError] = useState("");

  const evidenceMode = useMemo(() => {
    const sources = Object.values(livePark.evidenceSources);
    const simulatedCount = sources.filter((source) => source === "simulated_state").length;
    if (!sources.length) return "unknown";
    return simulatedCount === sources.length ? "simulated state feeds" : `${sources.length - simulatedCount} external feed overlays`;
  }, [livePark.evidenceSources]);

  async function refreshLiveProof() {
    setRefreshState("loading");
    setError("");
    try {
      const [stateResponse, rewardResponse] = await Promise.all([
        fetchParkPulseApi("/api/park/state-lite", { timeoutMs: 20_000 }),
        fetchParkPulseApi("/api/park/reward-model/status", { timeoutMs: 20_000 }),
      ]);
      setLivePark(parseLivePark((await stateResponse.json()) as Record<string, unknown>));
      setRewardStatus(parseRewardStatus((await rewardResponse.json()) as Record<string, unknown>));
      setRefreshState("complete");
    } catch (refreshError) {
      setRefreshState("error");
      setError(refreshError instanceof Error ? refreshError.message : "Unable to refresh live proof.");
    }
  }

  return (
    <main className="min-h-screen bg-slate-950 px-4 py-5 font-sans text-slate-200 lg:px-8">
      <div className="mx-auto max-w-[1500px] space-y-5">
        <header className="rounded-lg border border-cyan-400/20 bg-slate-900 p-5 shadow-xl shadow-cyan-950/20">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Model validation story</div>
              <h1 className="mt-2 max-w-5xl text-3xl font-black tracking-normal text-slate-100 lg:text-5xl">
                Latest model on the live park
              </h1>
              <p className="mt-3 max-w-3xl text-sm leading-relaxed text-slate-400">
                A source-backed view of what the deployed model saw, what it did, and how its hard-decision behavior compares with the intermediate scored model, replayed previous policy, and monitor-only baseline.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <a href="/ops" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-cyan-100 transition hover:border-cyan-300">
                Command Center
              </a>
              <a href="/operation-proof" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-100">
                Runtime proof
              </a>
              <a href="/ops-agent" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-100">
                Ops Agent
              </a>
              <button
                type="button"
                onClick={() => void refreshLiveProof()}
                disabled={refreshState === "loading"}
                className="rounded border border-lime-300 bg-lime-300 px-4 py-2 text-xs font-black text-slate-950 transition hover:bg-lime-200 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {refreshState === "loading" ? "Refreshing" : "Refresh live proof"}
              </button>
            </div>
          </div>
        </header>

        {(error || refreshState === "complete") && (
          <section className={`rounded-lg border p-3 text-sm font-bold ${error ? "border-amber-400/40 bg-amber-950/20 text-amber-100" : "border-emerald-400/30 bg-emerald-950/20 text-emerald-100"}`}>
            {error || "Live scorer and park state refreshed."}
          </section>
        )}

        <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <Metric label="Live scenario" value={livePark.scenario} detail={livePark.scenarioName} tone="cyan" />
          <Metric label="Crowd pressure" value={`${livePark.topZoneDensity}%`} detail={`${label(livePark.topZone)} / ${livePark.topZoneWaitMins} min wait`} tone="amber" />
          <Metric label="Escalation" value={livePark.operatorEscalation} detail={`Emergency access blocked: ${String(livePark.emergencyAccessBlocked)}`} tone="white" />
          <Metric label="Hard-decision scorer" value={String(rewardStatus.hardDecisionEnabled)} detail={`${rewardStatus.rewardField} / weight ${rewardStatus.compositeWeight}`} tone="lime" />
        </section>

        <section className="rounded-lg border border-cyan-400/25 bg-slate-900 p-5 shadow-xl shadow-cyan-950/10">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">What is actually different now</div>
              <h2 className="mt-2 text-3xl font-black text-slate-100">The result is not magically better yet; the decision is now inspectable</h2>
              <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-400">
                The meaningful delta is that the report now proves where the latest model acted, why it avoided unsafe choices, what trade-off it accepted, what changed in the park, and which parts still need instrumentation before claiming same-turn reward improvement.
              </p>
            </div>
            <div className="rounded border border-amber-300/30 bg-amber-950/20 px-4 py-3 text-sm font-black text-amber-100">
              Verdict: partially improved, not fully closed
            </div>
          </div>

          <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {topVerdict.map((item) => (
              <Metric key={item.label} label={item.label} value={item.value} detail={item.detail} tone={item.tone} />
            ))}
          </div>

          <div className="mt-5 grid gap-2 md:grid-cols-2">
            {evidenceBoundary.map((item) => (
              <div key={item} className="rounded border border-slate-800 bg-slate-950 px-3 py-2 text-xs font-semibold leading-5 text-slate-400">
                {item}
              </div>
            ))}
          </div>

          <div className="mt-5 overflow-auto">
            <table className="w-full min-w-[1120px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-slate-800 text-left text-[10px] uppercase tracking-widest text-slate-500">
                  <th className="py-3 pr-4">Analysis area</th>
                  <th className="py-3 pr-4">Before</th>
                  <th className="py-3 pr-4">Now</th>
                  <th className="py-3 pr-4">Proof</th>
                  <th className="py-3 pr-4">Status</th>
                </tr>
              </thead>
              <tbody>
                {analysisDeltas.map((row) => (
                  <tr key={row.label} className="border-b border-slate-800 align-top">
                    <td className="py-3 pr-4 font-black text-slate-100">{row.label}</td>
                    <td className="py-3 pr-4 text-slate-500">{row.old}</td>
                    <td className="py-3 pr-4 text-slate-300">{row.now}</td>
                    <td className="py-3 pr-4 text-cyan-100/80">{row.proof}</td>
                    <td className="py-3 pr-4">
                      <span className={`rounded border px-2 py-1 text-[10px] font-black uppercase tracking-widest ${statusClass(row.status)}`}>
                        {row.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="grid gap-5 xl:grid-cols-[1.05fr_0.95fr]">
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-5">
            <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Live state the model faced</div>
            <h2 className="mt-2 text-2xl font-black text-slate-100">Ride-down pressure with safety and food constraints</h2>
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              <div className="rounded border border-slate-800 bg-slate-950 p-4">
                <div className="text-xs font-black uppercase tracking-widest text-slate-500">Active alerts</div>
                <div className="mt-2 text-sm font-bold leading-6 text-slate-200">{compactList(livePark.alertTitles, 4)}</div>
              </div>
              <div className="rounded border border-slate-800 bg-slate-950 p-4">
                <div className="text-xs font-black uppercase tracking-widest text-slate-500">Maintenance boundary</div>
                <div className="mt-2 text-sm font-bold leading-6 text-slate-200">{livePark.maintenanceClearanceRequired} clearance-required work order</div>
              </div>
              <div className="rounded border border-slate-800 bg-slate-950 p-4 md:col-span-2">
                <div className="text-xs font-black uppercase tracking-widest text-slate-500">Feed basis</div>
                <div className="mt-2 text-sm font-bold leading-6 text-slate-200">{evidenceMode}</div>
                <div className="mt-3 grid gap-2 text-xs text-slate-400 sm:grid-cols-3">
                  {Object.entries(livePark.evidenceSources).map(([source, mode]) => (
                    <div key={source} className="rounded border border-slate-800 bg-slate-900 px-3 py-2">
                      <span className="font-black text-slate-200">{label(source)}</span>: {label(mode)}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900 p-5">
            <div className="text-[10px] font-black uppercase tracking-widest text-lime-300">Scoring contract</div>
            <h2 className="mt-2 text-2xl font-black text-slate-100">The latest model has a hard-decision target</h2>
            <div className="mt-4 space-y-3">
              {Object.entries(rewardStatus.weights).map(([key, value]) => (
                <div key={key}>
                  <div className="flex items-center justify-between text-xs font-black uppercase tracking-widest text-slate-500">
                    <span>{label(key)}</span>
                    <span>{value}</span>
                  </div>
                  <div className="mt-1 h-2 overflow-hidden rounded bg-slate-950">
                    <div className="h-full rounded bg-cyan-300" style={{ width: barWidth(Number(value), 0.35) }} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
          <div className="flex flex-col gap-2 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Park-state evidence</div>
              <h2 className="mt-2 text-2xl font-black text-slate-100">The hard part was not the alert; it was the operating context around it</h2>
            </div>
            <div className="text-xs font-bold text-slate-400">Pulled from the live state-lite snapshot used for validation</div>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {liveStateDetails.map((item) => (
              <article key={item.label} className="rounded-lg border border-slate-800 bg-slate-950 p-4">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{item.label}</div>
                <div className="mt-2 text-lg font-black text-slate-100">{item.value}</div>
                <div className="mt-2 text-sm leading-6 text-slate-400">{item.detail}</div>
              </article>
            ))}
          </div>
        </section>

        <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
          <div className="text-[10px] font-black uppercase tracking-widest text-lime-300">Decision loop reconstruction</div>
          <h2 className="mt-2 text-2xl font-black text-slate-100">What happened turn by turn</h2>
          <div className="mt-4 grid gap-3">
            {decisionTimeline.map((step) => (
              <article key={step.phase} className="grid gap-3 rounded-lg border border-slate-800 bg-slate-950 p-4 lg:grid-cols-[150px_1fr_1fr_1fr]">
                <div>
                  <div className="text-lg font-black text-white">{step.phase}</div>
                  <div className="mt-1 text-xs font-black uppercase tracking-widest text-cyan-300">{step.owner}</div>
                </div>
                <div>
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Evidence</div>
                  <p className="mt-2 text-sm leading-6 text-slate-300">{step.evidence}</p>
                </div>
                <div>
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Decision</div>
                  <p className="mt-2 text-sm leading-6 text-slate-300">{step.decision}</p>
                  <div className="mt-2 rounded border border-slate-800 bg-slate-900 px-3 py-2 text-xs font-bold text-slate-400">{step.toolUse}</div>
                </div>
                <div>
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Result</div>
                  <p className="mt-2 text-sm leading-6 text-slate-300">{step.result}</p>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="grid gap-5 xl:grid-cols-[1fr_0.82fr]">
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-5">
            <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Agent negotiation board</div>
            <h2 className="mt-2 text-2xl font-black text-slate-100">The agents did not all want the same thing</h2>
            <div className="mt-4 overflow-auto">
              <table className="w-full min-w-[860px] border-collapse text-sm">
                <thead>
                  <tr className="border-b border-slate-800 text-left text-[10px] uppercase tracking-widest text-slate-500">
                    <th className="py-3 pr-4">Pressure</th>
                    <th className="py-3 pr-4">Department wants</th>
                    <th className="py-3 pr-4">Conflict</th>
                    <th className="py-3 pr-4">Final resolution</th>
                    <th className="py-3 pr-4">Owner</th>
                  </tr>
                </thead>
                <tbody>
                  {tradeoffs.map((row) => (
                    <tr key={row.pressure} className="border-b border-slate-800 align-top">
                      <td className="py-3 pr-4 font-black text-slate-100">{row.pressure}</td>
                      <td className="py-3 pr-4 text-slate-400">{row.wants}</td>
                      <td className="py-3 pr-4 text-amber-100/80">{row.conflict}</td>
                      <td className="py-3 pr-4 text-lime-100/80">{row.resolution}</td>
                      <td className="py-3 pr-4 text-slate-300">{row.owner}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900 p-5">
            <div className="text-[10px] font-black uppercase tracking-widest text-lime-300">Material park impact</div>
            <h2 className="mt-2 text-2xl font-black text-slate-100">What changed after action</h2>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              {impactMetrics.map((metric) => (
                <Metric key={metric.label} label={metric.label} value={metric.value} detail={metric.detail} tone={metric.tone} />
              ))}
            </div>
          </div>
        </section>

        <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
          <div className="flex flex-col gap-2 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Live agent actions</div>
              <h2 className="mt-2 text-2xl font-black text-slate-100">The latest model acted where action was allowed</h2>
            </div>
            <div className="text-xs font-bold text-slate-400">Validated from deployed Cloud Run agent-role runs</div>
          </div>
          <div className="mt-4 grid gap-3 lg:grid-cols-3">
            {roleRuns.map((run) => (
              <article key={run.role} className="rounded-lg border border-slate-800 bg-slate-950 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-xl font-black text-white">{run.role}</div>
                    <div className="mt-1 text-xs font-black uppercase tracking-widest text-slate-500">{run.status}</div>
                  </div>
                  <div className={`rounded border px-2 py-1 text-xs font-black ${run.dispatchCount ? "border-lime-300/40 bg-lime-950/20 text-lime-100" : "border-sky-300/40 bg-sky-950/20 text-sky-100"}`}>
                    {run.dispatchCount} dispatches
                  </div>
                </div>
                <div className="mt-4 grid grid-cols-2 gap-2 text-sm">
                  <div className="rounded border border-slate-800 bg-slate-900 p-3">
                    <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Tool calls</div>
                    <div className="mt-1 text-2xl font-black text-slate-100">{run.calledToolCount}</div>
                  </div>
                  <div className="rounded border border-slate-800 bg-slate-900 p-3">
                    <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Policy gates</div>
                    <div className="mt-1 text-2xl font-black text-slate-100">{run.policyGates?.length ?? 0}</div>
                  </div>
                </div>
                <div className="mt-4 min-h-[52px] text-sm font-bold leading-6 text-slate-300">{run.headline ?? "Bounded proactive receiver payloads were prepared."}</div>
                {run.policyGates?.length ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {run.policyGates.map((gate) => (
                      <span key={gate} className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-400">
                        {label(gate)}
                      </span>
                    ))}
                  </div>
                ) : (
                  <div className="mt-3 rounded border border-sky-400/30 bg-sky-950/20 px-3 py-2 text-xs font-bold text-sky-100">Read-only scan held dispatch by design.</div>
                )}
              </article>
            ))}
          </div>
        </section>

        <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
          <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Model comparison</div>
          <h2 className="mt-2 text-2xl font-black text-slate-100">What got better, and what is still not directly scored live</h2>
          <div className="mt-4 overflow-auto">
            <table className="w-full min-w-[1120px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-slate-800 text-left text-[10px] uppercase tracking-widest text-slate-500">
                  <th className="py-3 pr-4">Model</th>
                  <th className="py-3 pr-4">Hard decision</th>
                  <th className="py-3 pr-4">Dispatch</th>
                  <th className="py-3 pr-4">Policy / risk</th>
                  <th className="py-3 pr-4">Score note</th>
                  <th className="py-3 pr-4">Boundary</th>
                </tr>
              </thead>
              <tbody>
                {modelRows.map((row) => (
                  <tr key={row.model} className="border-b border-slate-800 align-top">
                    <td className="py-3 pr-4">
                      <div className="font-black text-slate-100">{row.model}</div>
                      <div className="mt-1 text-xs text-slate-500">{row.evidence}</div>
                    </td>
                    <td className="w-[230px] py-3 pr-4"><HardDecisionCell value={row.hardDecision} /></td>
                    <td className="py-3 pr-4 font-bold text-slate-300">{row.dispatch}</td>
                    <td className="py-3 pr-4 text-slate-400">{row.policy}</td>
                    <td className="py-3 pr-4 text-slate-400">{row.score}</td>
                    <td className="py-3 pr-4 text-slate-400">{row.boundary}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
          <div className="text-[10px] font-black uppercase tracking-widest text-lime-300">Ground-truth comparison</div>
          <h2 className="mt-2 text-2xl font-black text-slate-100">How the models act differently in park terms</h2>
          <div className="mt-4 overflow-auto">
            <table className="w-full min-w-[1120px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-slate-800 text-left text-[10px] uppercase tracking-widest text-slate-500">
                  <th className="py-3 pr-4">Model</th>
                  <th className="py-3 pr-4">Reward</th>
                  <th className="py-3 pr-4">Hard decision</th>
                  <th className="py-3 pr-4">Safety</th>
                  <th className="py-3 pr-4">Congestion</th>
                  <th className="py-3 pr-4">Satisfaction</th>
                  <th className="py-3 pr-4">Action posture</th>
                  <th className="py-3 pr-4">Meaning</th>
                </tr>
              </thead>
              <tbody>
                {modelBehaviorRows.map((row) => (
                  <tr key={row.model} className="border-b border-slate-800 align-top">
                    <td className="py-3 pr-4 font-black text-slate-100">{row.model}</td>
                    <td className="py-3 pr-4 text-cyan-100">{row.reward}</td>
                    <td className="py-3 pr-4 text-lime-100">{row.hardDecision}</td>
                    <td className="py-3 pr-4 text-slate-300">{row.safety}</td>
                    <td className="py-3 pr-4 text-slate-300">{row.congestion}</td>
                    <td className="py-3 pr-4 text-slate-300">{row.satisfaction}</td>
                    <td className="py-3 pr-4 font-bold text-slate-300">{row.action}</td>
                    <td className="py-3 pr-4 text-slate-400">{row.explanation}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-4 rounded border border-slate-800 bg-slate-950 p-4 text-sm leading-6 text-slate-400">
            Same-case ground truth exists for current challenger versus monitor-only baseline. Previous and earlier rows are valuable for progression, but they are snapshot comparisons unless the report explicitly says same-case replay.
          </div>
        </section>

        <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
          <div className="flex flex-col gap-2 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Case matrix</div>
              <h2 className="mt-2 text-2xl font-black text-slate-100">Where the latest model took harder action instead of only holding</h2>
            </div>
            <div className="text-xs font-bold text-slate-400">8 scored current cases, same-case monitor baseline available</div>
          </div>
          <div className="mt-4 overflow-auto">
            <table className="w-full min-w-[1180px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-slate-800 text-left text-[10px] uppercase tracking-widest text-slate-500">
                  <th className="py-3 pr-4">Case</th>
                  <th className="py-3 pr-4">Issue / target</th>
                  <th className="py-3 pr-4">Path pressure</th>
                  <th className="py-3 pr-4">Latest after</th>
                  <th className="py-3 pr-4">Monitor after</th>
                  <th className="py-3 pr-4">Actions</th>
                  <th className="py-3 pr-4">Memory</th>
                  <th className="py-3 pr-4">Hard-decision activation</th>
                  <th className="py-3 pr-4">Lift label</th>
                </tr>
              </thead>
              <tbody>
                {caseMatrix.map((row) => (
                  <tr key={row.caseKey} className="border-b border-slate-800 align-top">
                    <td className="py-3 pr-4 font-black text-slate-100">{row.caseKey}</td>
                    <td className="py-3 pr-4">
                      <div className="font-bold text-slate-200">{label(row.issue)}</div>
                      <div className="mt-1 text-xs text-slate-500">{row.target}</div>
                    </td>
                    <td className="py-3 pr-4 text-slate-300">{row.before}</td>
                    <td className="py-3 pr-4 text-lime-100">{row.latestAfter}</td>
                    <td className="py-3 pr-4 text-amber-100">{row.baselineAfter}</td>
                    <td className="py-3 pr-4 text-slate-300">{row.executed} executed / {row.held} held</td>
                    <td className="py-3 pr-4 text-cyan-100">{row.memory} applied</td>
                    <td className="w-[180px] py-3 pr-4">
                      <div className="relative h-7 overflow-hidden rounded border border-slate-800 bg-slate-950">
                        <div className="h-full bg-gradient-to-r from-cyan-500 to-lime-300" style={{ width: `${row.hardDecision}%` }} />
                        <div className="absolute inset-0 flex items-center justify-center text-xs font-black text-white">{row.hardDecision.toFixed(1)}%</div>
                      </div>
                    </td>
                    <td className="py-3 pr-4 text-slate-400">{label(row.lift)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="grid gap-5 xl:grid-cols-[0.92fr_1.08fr]">
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-5">
            <div className="text-[10px] font-black uppercase tracking-widest text-lime-300">Memory and learning</div>
            <h2 className="mt-2 text-2xl font-black text-slate-100">What carries forward</h2>
            <div className="mt-4 space-y-3">
              {trainingMaterial.map((row) => (
                <div key={row.label} className="rounded border border-slate-800 bg-slate-950 p-4">
                  <div className="text-xs font-black uppercase tracking-widest text-slate-500">{row.label}</div>
                  <div className="mt-2 text-sm leading-6 text-slate-300">{row.value}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900 p-5">
            <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Training value</div>
            <h2 className="mt-2 text-2xl font-black text-slate-100">Why LLM reasoning is useful before RL training</h2>
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              <div className="rounded border border-slate-800 bg-slate-950 p-4">
                <div className="text-lg font-black text-slate-100">It creates labels RL can use</div>
                <p className="mt-2 text-sm leading-6 text-slate-400">The useful artifact is not the prose. It is the structured trace: evidence, rejected actions, policy boundary, selected substitute, receiver result, and outcome deltas.</p>
              </div>
              <div className="rounded border border-slate-800 bg-slate-950 p-4">
                <div className="text-lg font-black text-slate-100">It explains why a hold was correct</div>
                <p className="mt-2 text-sm leading-6 text-slate-400">RL should not learn to execute every high-pressure action. The judge trace separates unsafe holds, owner-assigned holds, and safe substitutes that should be rewarded.</p>
              </div>
              <div className="rounded border border-slate-800 bg-slate-950 p-4">
                <div className="text-lg font-black text-slate-100">It prevents reward hacking</div>
                <p className="mt-2 text-sm leading-6 text-slate-400">Safety, labor, privacy, and measurement gates stay outside the reward target. A higher hard-decision score cannot override policy or measured regression.</p>
              </div>
              <div className="rounded border border-slate-800 bg-slate-950 p-4">
                <div className="text-lg font-black text-slate-100">It batches learning</div>
                <p className="mt-2 text-sm leading-6 text-slate-400">The page records one case as training material, but the system should train only after enough measured cases accumulate and slice-level promotion gates pass.</p>
              </div>
            </div>
          </div>
        </section>

        <section className="rounded-lg border border-amber-400/30 bg-amber-950/10 p-5">
          <div className="text-[10px] font-black uppercase tracking-widest text-amber-200">Remaining gap</div>
          <h2 className="mt-2 text-2xl font-black text-amber-50">The live turn should emit the hard-decision score</h2>
          <p className="mt-3 max-w-4xl text-sm leading-6 text-amber-100/80">
            The scorer is deployed and the latest agents acted on the current park state. The missing link is instrumentation: the live role-run endpoint should attach the same hard-decision reward vector to each live decision receipt, so this page can compare latest, intermediate, replay, and baseline on the exact same live turn.
          </p>
          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {openInstrumentationGaps.map((item) => (
              <div key={item} className="rounded border border-amber-400/20 bg-slate-950 px-3 py-3 text-sm font-bold text-amber-100">
                {item}
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
          <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Evidence files</div>
          <div className="mt-3 grid gap-2 text-xs font-bold text-slate-400 md:grid-cols-2">
            <div className="rounded border border-slate-800 bg-slate-950 p-3">Generated: {new Date(validationGeneratedAt).toLocaleString()}</div>
            <div className="rounded border border-slate-800 bg-slate-950 p-3">Report JSON: output/qa/latest-live-park-model-validation-20260606/latest-live-park-model-validation.json</div>
            <div className="rounded border border-slate-800 bg-slate-950 p-3">Live state: output/qa/latest-live-park-model-validation-20260606/live-park-state-lite.json</div>
            <div className="rounded border border-slate-800 bg-slate-950 p-3">Reward model: output/qa/latest-live-park-model-validation-20260606/reward-model-status.json</div>
          </div>
        </section>
      </div>
    </main>
  );
}
