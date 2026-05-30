"use client";

import { useEffect, useState } from "react";
import type { GuestFlow, ParkState } from "@/types/park";
import type { AgentRoleSkillsRegistry, DeliveryDispatch, DemoScenario, DigitalTwinToolTrace, IntegrationStatus, OperatorCommandResponse, ProactiveInsights, ProactiveRunTelemetry, RoleAgentProposalArtifact, RunTelemetry, ScenarioKey, SignalTriageResult, UnifiedOperatingReceipt } from "@/types/platform";
import { DEFAULT_PHYSICAL_MAP, VisualParkBoard, ZONE_LAYOUT, aiPhaseForMap, buildAiDemoSteps, scenarioProof } from "@/components/ParkPulseMap";
import type { AgentImpactReplay, AgentMapGrounding, AiDemoStep, AiStepStatus, MapLayer, MapSelection } from "@/components/ParkPulseMap";
import { fetchParkPulseApi } from "@/lib/api";
import { dispatchBody, formatTime, pct, pressureTone, ratePct, toneClass } from "@/lib/parkPulseDemoContent";
import { sortedByRisk } from "@/lib/parkPulseAgents";

export function riskBadgeClass(risk?: string) {
  if (risk === "CRITICAL") return "bg-red-400 text-slate-950";
  if (risk === "HIGH") return "bg-orange-300 text-slate-950";
  if (risk === "MEDIUM") return "bg-amber-300 text-slate-950";
  return "bg-slate-800 text-slate-300";
}

export function timelineStatusClass(status?: string) {
  if (status === "done") return "border-emerald-400/30 bg-emerald-950/20 text-emerald-100";
  if (status === "pending") return "border-amber-400/30 bg-amber-950/20 text-amber-100";
  return "border-slate-800 bg-slate-950 text-slate-300";
}

function receiverStatus(dispatch?: DeliveryDispatch, isRunning?: boolean) {
  if (dispatch?.response?.applied) return "applied";
  if (dispatch?.response?.acknowledgedCount || dispatch?.response?.state === "observed") return "observed";
  if (dispatch?.status) return dispatch.status;
  return isRunning ? "listening" : "waiting";
}

function provenanceToneClass(tone: "ml" | "agent" | "human" | "automation") {
  if (tone === "ml") return "border-violet-400/30 bg-violet-950/20 text-violet-100";
  if (tone === "agent") return "border-cyan-400/30 bg-cyan-950/20 text-cyan-100";
  if (tone === "human") return "border-amber-400/30 bg-amber-950/20 text-amber-100";
  return "border-emerald-400/30 bg-emerald-950/20 text-emerald-100";
}

function DecisionProvenancePanel({
  scenario,
  telemetry,
  dispatches,
  signalTriage,
}: {
  scenario: DemoScenario;
  telemetry: ProactiveRunTelemetry | RunTelemetry | null;
  dispatches: DeliveryDispatch[];
  signalTriage: SignalTriageResult | null;
}) {
  const digitalTwin = telemetry ? scenario.experienceModel?.digitalTwin : undefined;
  const optimizer = telemetry?.optimization;
  const selectedPlan = optimizer?.selected_plan;
  const candidateCount = optimizer?.candidates?.length ?? 0;
  const dispatchCount = dispatches.length || telemetry?.delivery?.summary?.total || signalTriage?.delivery?.summary?.total || 0;
  const approvalText = telemetry?.governance?.allowed === false
    ? "Safety check stopped execution and requires operator review."
    : "Human authority remains in the loop for safety, labor exceptions, and sensitive guest-care actions.";
  const agentDecision =
    selectedPlan?.label ??
    optimizer?.decision_summary ??
    telemetry?.planner?.selected_action?.label ??
    "Waiting for the next custom agent decision.";

  const rows = [
    {
      label: "ML forecast",
      owner: "Prediction",
      tone: "ml" as const,
      output: digitalTwin?.prediction ?? "Estimates operating risk from live park signals.",
      boundary: "Scores likely outcomes. It does not choose policy or approve action.",
      proof: digitalTwin ? `${digitalTwin.horizon} / ${digitalTwin.confidence}% confidence` : telemetry ? "runtime forecast" : "waiting for run",
    },
    {
      label: "Agent decision",
      owner: "Reasoning + tools",
      tone: "agent" as const,
      output: agentDecision ?? "Selects a policy-checked action plan from specialist findings.",
      boundary: "Compares options, calls tools, records evidence, and creates a recommended operating move.",
      proof: candidateCount ? `${candidateCount} candidates compared` : telemetry ? "runtime specialists read" : "waiting for run",
    },
    {
      label: "Human authority",
      owner: "Operator gate",
      tone: "human" as const,
      output: approvalText,
      boundary: "Ride reopening, safety clearance, labor exceptions, and sensitive guest-care cases stay with humans.",
      proof: telemetry?.governance?.gate_status ?? "review model",
    },
    {
      label: "Action bus",
      owner: "Execution",
      tone: "automation" as const,
      output: dispatchCount ? `${dispatchCount} payloads prepared or sent to guest, worker, and equipment channels.` : "Waiting for approved plan before dispatch.",
      boundary: "Executes only bounded payloads; policy blocks or review flags prevent unsafe automation.",
      proof: signalTriage?.delivery?.summary?.pending_operator_approval
        ? `${signalTriage.delivery.summary.pending_operator_approval} pending approval`
        : dispatchCount
          ? "observable dispatch"
          : "not dispatched",
    },
  ];

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Decision provenance</div>
          <h2 className="mt-1 text-sm font-black text-slate-100">What is ML, what is agentic, what stays human</h2>
        </div>
        <span className="rounded bg-slate-950 px-2 py-1 text-[9px] font-black uppercase text-slate-300">audit trail</span>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        {rows.map((row) => (
          <div key={row.label} className={`rounded border p-2.5 ${provenanceToneClass(row.tone)}`}>
            <div className="flex items-center justify-between gap-2">
              <div className="text-[10px] font-black uppercase tracking-widest">{row.label}</div>
            </div>
            <div className="mt-1 text-[9px] font-black uppercase tracking-widest opacity-70">{row.owner}</div>
            <div className="mt-1 line-clamp-2 text-[10px] font-bold leading-relaxed">{row.output}</div>
            <div className="mt-1 line-clamp-2 text-[9px] leading-relaxed opacity-75">{row.boundary}</div>
            <div className="mt-1 text-[8px] font-black uppercase tracking-widest opacity-80">{row.proof}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function toolToneClass(tool?: string) {
  if (!tool) return "border-slate-800 bg-slate-950 text-slate-300";
  if (tool.startsWith("get_")) return "border-violet-400/30 bg-violet-950/20 text-violet-100";
  if (tool.includes("simulate") || tool.includes("compare")) return "border-cyan-400/30 bg-cyan-950/20 text-cyan-100";
  if (tool.includes("validate")) return "border-amber-400/30 bg-amber-950/20 text-amber-100";
  if (tool.includes("score")) return "border-emerald-400/30 bg-emerald-950/20 text-emerald-100";
  return "border-slate-700 bg-slate-950 text-slate-200";
}

function roleToneClass(role?: string) {
  if (role === "scan") return "border-violet-400/35 bg-violet-950/30 text-violet-50";
  if (role === "react") return "border-amber-400/35 bg-amber-950/30 text-amber-50";
  if (role === "proact") return "border-emerald-400/35 bg-emerald-950/30 text-emerald-50";
  return "border-slate-700 bg-slate-950/70 text-slate-200";
}

function humanizeId(value?: string | number | null) {
  if (value === undefined || value === null || value === "") return "--";
  return String(value)
    .replace(/^[a-z]+[_-][a-z0-9]+[_-]/i, "")
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function compactStatus(value?: string | number | null) {
  const text = String(value ?? "").toLowerCase();
  if (!text) return "--";
  if (text.includes("full_runtime") || text.includes("gemini") || text.includes("vertex")) return "Live AI";
  if (text.includes("bounded_action") || text.includes("fast_operating") || text.includes("fallback") || text.includes("local")) return "Fast policy";
  if (text.includes("allowed") || text.includes("passed") || text.includes("complete") || text.includes("success")) return "Clear";
  if (text.includes("review") || text.includes("pending") || text.includes("queued")) return "Review";
  if (text.includes("blocked") || text.includes("failed")) return "Blocked";
  return humanizeId(value);
}

function savedLessonLabel(value?: string | number | null, fallback = "waiting") {
  return value ? "lesson saved" : fallback;
}

function analyticsProofLabel(value?: string | number | null, fallback = "waiting") {
  if (!value) return fallback;
  const text = String(value).toLowerCase();
  if (text.includes("prior") || text.includes("bigquery") || text.includes("bq")) return "response priors ready";
  return compactStatus(value);
}

function plannerRuntimeLabel(telemetry?: RunTelemetry | null) {
  const planner = telemetry?.planner;
  if (!planner) return "Ready";
  if (planner.gemini_ready || String(planner.runtime ?? "").toLowerCase().includes("vertex")) return "Gemini live";
  if (String(planner.runtime ?? "").toLowerCase().includes("bounded_action") || String(planner.model ?? "").toLowerCase().includes("fast_operating")) return "Fast policy";
  return compactStatus(planner.runtime ?? planner.model ?? "ready");
}

function toolDisplayName(tool: string) {
  const clean = tool.replace(/^get_/, "").replace(/^score_/, "").replace(/^validate_/, "");
  const names: Record<string, string> = {
    noisy_observation: "Guest/staff reports",
    park_state: "Live park state",
    zone_density: "Crowd density",
    ride_status: "Ride status",
    staff_constraints: "Staff constraints",
    policy: "Policy check",
    decision_quality: "Decision quality",
  };
  return names[clean] ?? humanizeId(clean);
}

function RoleRouterPanel({ registry, isActive }: { registry?: AgentRoleSkillsRegistry | null; isActive?: boolean }) {
  const route = registry?.route;
  const selectedRole = route?.selected_role ?? "scan";
  const roles = registry?.roles ?? [];
  const selected = roles.find((role) => role.mode === selectedRole);
  const tools = route?.required_tools ?? selected?.mcp_tools ?? [];
  const gates = route?.policy_gates ?? selected?.policy_gates ?? [];
  const receipts = route?.expected_receipt ?? selected?.output_artifacts ?? [];
  const roleLabel =
    selectedRole === "scan"
      ? "Watching for risk"
      : selectedRole === "react"
        ? "Responding now"
        : selectedRole === "proact"
          ? "Preventing escalation"
          : selected?.name ?? "Park assistant";
  const roleSummary =
    selectedRole === "scan"
      ? "Reading live signals before taking action."
      : selectedRole === "react"
        ? "Preparing a bounded response for the current issue."
        : selectedRole === "proact"
          ? "Looking for early intervention before guests feel the problem."
          : route?.why ?? selected?.purpose ?? "Choosing the right operating mode.";

  return (
    <div className={`rounded-lg border p-2 ${roleToneClass(selectedRole)}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[8px] font-black uppercase tracking-widest opacity-75">Operating mode</div>
          <div className="mt-0.5 truncate text-sm font-black">{roleLabel}</div>
        </div>
        <span className={`rounded px-1.5 py-0.5 text-[8px] font-black uppercase ${isActive ? "bg-cyan-300 text-slate-950" : "bg-slate-950/80 text-slate-300"}`}>
          {isActive ? "working" : selectedRole === "scan" ? "watching" : humanizeId(selectedRole)}
        </span>
      </div>
      <div className="mt-1 line-clamp-2 text-[10px] leading-relaxed opacity-80">
        {roleSummary}
      </div>
      <div className="mt-2 grid grid-cols-3 gap-1 text-center">
        {[
          ["Inputs", tools.length || "--"],
          ["Checks", gates.length || "--"],
          ["Proof", receipts.length || "--"],
        ].map(([label, value]) => (
          <div key={label} className="rounded bg-slate-950/70 px-2 py-1">
            <div className="text-[7px] font-black uppercase tracking-widest opacity-60">{label}</div>
            <div className="text-xs font-black">{value}</div>
          </div>
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        {tools.slice(0, 5).map((tool) => (
          <span key={tool} className="rounded bg-slate-950/70 px-1.5 py-0.5 text-[8px] font-black uppercase tracking-wide opacity-90">
            {toolDisplayName(tool)}
          </span>
        ))}
      </div>
      {!!gates.length && (
        <div className="mt-1 line-clamp-1 text-[8px] font-black uppercase tracking-widest opacity-70">
          Safety checks active
        </div>
      )}
    </div>
  );
}

function receiptRoleLabel(role?: string) {
  if (role === "scan") return "Scan";
  if (role === "react") return "React";
  if (role === "proact") return "Proact";
  return role ? humanizeId(role) : "Ready";
}

function receiptDomainLabel(domain?: string) {
  if (!domain) return "park";
  if (domain === "energy") return "HVAC";
  return humanizeId(domain);
}

function buildUnifiedReceipt({
  operatorCommandResult,
  telemetry,
  signalTriage,
  registry,
  operatorCommand,
}: {
  operatorCommandResult?: OperatorCommandResponse | null;
  telemetry?: ProactiveRunTelemetry | RunTelemetry | null;
  signalTriage?: SignalTriageResult | null;
  registry?: AgentRoleSkillsRegistry | null;
  operatorCommand?: string;
}): UnifiedOperatingReceipt {
  const backendReceipt = operatorCommandResult?.unified_receipt ?? operatorCommandResult?.run_telemetry?.unified_receipt ?? telemetry?.unified_receipt;
  if (backendReceipt) return backendReceipt;

  const route = operatorCommandResult?.role_route ?? registry?.route;
  const role =
    operatorCommandResult?.role_receipt?.role ??
    route?.selected_role ??
    (telemetry?.delivery?.summary?.total ? "proact" : signalTriage ? "scan" : "scan");
  const impact = operatorCommandResult?.run_telemetry?.outcome?.state_impact ?? telemetry?.outcome?.state_impact;
  const delivery = signalTriage?.delivery ?? operatorCommandResult?.run_telemetry?.delivery ?? telemetry?.delivery;
  const dispatches = delivery?.dispatches ?? [];
  const action = operatorCommandResult?.run_telemetry?.planner?.selected_action ?? telemetry?.planner?.selected_action;
  const policy = operatorCommandResult?.run_telemetry?.governance ?? telemetry?.governance;
  const constraints = operatorCommandResult?.operator_constraints ?? operatorCommandResult?.run_telemetry?.operator_constraints ?? telemetry?.operator_constraints;
  const inferredDomain =
    impact?.domain ??
    constraints?.inferred_incident_type ??
    operatorCommandResult?.role_receipt?.scenario_key ??
    operatorCommandResult?.route?.scenario_key ??
    telemetry?.scenario_key ??
    signalTriage?.signal?.categories?.[0];

  return {
    contract: "parkpulse_operating_loop_v1",
    role,
    domain: String(inferredDomain ?? "").replace("_response", "").replace("_safety", "") || "park",
    scenario_key: operatorCommandResult?.role_receipt?.scenario_key ?? String(operatorCommandResult?.route?.scenario_key ?? telemetry?.scenario_key ?? "custom"),
    confidence: operatorCommandResult?.run_telemetry?.planner?.confidence_score ?? telemetry?.planner?.confidence_score ?? signalTriage?.signal?.confidence,
    constraints: {
      summary: constraints?.intent_summary ?? signalTriage?.signal?.text ?? operatorCommandResult?.operator_response?.summary ?? operatorCommand,
      requires_human_review: Boolean(constraints?.requires_human_review ?? signalTriage?.signal?.human_approval_required ?? operatorCommandResult?.route?.requires_human_review),
      policy_gates: route?.policy_gates ?? [],
    },
    tools: route?.required_tools ?? [],
    selected_action: action ?? { label: operatorCommandResult?.operator_response?.headline ?? "Awaiting recommended action", target: inferredDomain },
    policy_result: policy,
    dispatches: {
      count: delivery?.summary?.total ?? dispatches.length,
      channels: Array.from(new Set(dispatches.map((dispatch) => dispatch.channel).filter(Boolean) as string[])),
      ids: dispatches.map((dispatch) => dispatch.id).filter(Boolean) as string[],
    },
    state_impact: impact,
    learning_update: operatorCommandResult?.role_receipt?.learning_update,
    memory: operatorCommandResult?.role_receipt?.mongo ?? telemetry?.memory,
    analytics: operatorCommandResult?.role_receipt?.bigquery ?? telemetry?.analytics,
  };
}

function UnifiedOperatingLoop({
  receipt,
  isActive,
}: {
  receipt: UnifiedOperatingReceipt;
  isActive?: boolean;
}) {
  const dispatchCount = receipt.dispatches?.count ?? 0;
  const policyStatus = receipt.policy_result?.gate_status ?? (receipt.policy_result?.allowed === false ? "review" : "checked");
  const learned = receipt.learning_update && typeof receipt.learning_update === "object" && "validity" in receipt.learning_update
    ? String((receipt.learning_update as { validity?: string }).validity)
    : receipt.memory ? "memory ready" : "waiting";
  const steps = [
    { id: "signal", label: "Signal", value: receiptDomainLabel(receipt.domain), tone: receipt.domain ? "done" : "pending" },
    { id: "role", label: "Role", value: receiptRoleLabel(receipt.role), tone: receipt.role ? "done" : "pending" },
    { id: "tools", label: "Tools", value: `${receipt.tools?.length ?? 0}`, tone: (receipt.tools?.length ?? 0) ? "done" : "pending" },
    { id: "policy", label: "Policy", value: compactStatus(policyStatus), tone: policyStatus === "blocked" ? "risk" : "done" },
    { id: "emit", label: "Emit", value: `${dispatchCount}`, tone: dispatchCount ? "done" : receipt.role === "scan" ? "pending" : "watch" },
    { id: "learn", label: "Learn", value: compactStatus(learned), tone: learned.includes("observed") || learned.includes("ready") ? "done" : "pending" },
  ] as const;

  return (
    <div className="rounded-lg border border-cyan-300/30 bg-slate-950/82 p-2.5 text-slate-100">
      <div className="flex items-center justify-between gap-2">
        <div>
          <div className="text-[8px] font-black uppercase tracking-widest text-cyan-300">Unified operating loop</div>
          <div className="mt-0.5 truncate text-xs font-black">
            {receiptRoleLabel(receipt.role)} assistant · {receiptDomainLabel(receipt.domain)} response
          </div>
        </div>
        <span className={`rounded px-2 py-1 text-[8px] font-black uppercase ${isActive ? "bg-cyan-300 text-slate-950" : "bg-slate-800 text-slate-300"}`}>
          {isActive ? "live" : "ready"}
        </span>
      </div>
      <div className="mt-2 grid grid-cols-6 gap-1">
        {steps.map((step) => (
          <div key={step.id} className={`rounded px-1.5 py-1 text-center ${step.tone === "risk" ? "bg-red-950/60 text-red-100" : step.tone === "watch" ? "bg-amber-950/50 text-amber-100" : step.tone === "done" ? "bg-emerald-950/55 text-emerald-100" : "bg-slate-900 text-slate-500"}`}>
            <div className="text-[7px] font-black uppercase tracking-widest opacity-70">{step.label}</div>
            <div className="mt-0.5 truncate text-[9px] font-black">{step.value}</div>
          </div>
        ))}
      </div>
      <div className="mt-2 grid gap-1 text-[10px] leading-snug text-slate-300">
        <div className="line-clamp-1">
          <span className="font-black uppercase tracking-widest text-slate-500">Understood </span>
          {receipt.constraints?.summary ?? receipt.selected_action?.label ?? "Waiting for operator text or park signal."}
        </div>
        <div className="line-clamp-1">
          <span className="font-black uppercase tracking-widest text-slate-500">Action </span>
          {receipt.selected_action?.label ?? "No action selected yet."}
        </div>
        <div className="line-clamp-1">
          <span className="font-black uppercase tracking-widest text-slate-500">Impact </span>
          {receipt.state_impact?.before_after_line ?? receipt.state_impact?.headline ?? "State impact appears after receiver action."}
        </div>
      </div>
    </div>
  );
}

function AgentBoundaryPanel({
  artifact,
  telemetry,
  isActive,
}: {
  artifact?: RoleAgentProposalArtifact | null;
  telemetry?: ProactiveRunTelemetry | RunTelemetry | null;
  isActive?: boolean;
}) {
  const proposals = artifact?.proposals ?? [];
  const resolution = telemetry?.optimization?.decision_bridge_resolution ?? telemetry?.role_outcome_attribution?.decision_bridge_resolution;
  const acceptedAgent = resolution?.accepted_role_proposal?.agent_id;
  const visible = proposals.length
    ? proposals.filter((proposal) => proposal.agent_id !== "park_understanding_agent").slice(0, 5)
    : [];

  if (!visible.length) {
    return (
      <div className="rounded-lg border border-slate-800 bg-slate-950/82 p-2.5">
        <div className="flex items-center justify-between gap-2">
          <div>
            <div className="text-[8px] font-black uppercase tracking-widest text-slate-500">Specialist agents</div>
            <div className="mt-0.5 text-xs font-black text-slate-300">Waiting for role proposals</div>
          </div>
          <span className="rounded bg-slate-900 px-2 py-1 text-[8px] font-black uppercase text-slate-500">bounded</span>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-violet-300/30 bg-slate-950/82 p-2.5 text-slate-100">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-[8px] font-black uppercase tracking-widest text-violet-300">Specialist agents + boundaries</div>
          <div className="mt-0.5 line-clamp-1 text-xs font-black">
            {artifact?.mediator_summary ?? "Specialists recommend; Decision Bridge selects one bounded action."}
          </div>
        </div>
        <span className={`rounded px-2 py-1 text-[8px] font-black uppercase ${isActive ? "bg-violet-300 text-slate-950" : "bg-slate-800 text-slate-300"}`}>
          {visible.length} roles
        </span>
      </div>
      <div className="mt-2 grid gap-1.5">
        {visible.map((proposal) => {
          const accepted = acceptedAgent ? proposal.agent_id === acceptedAgent : proposal.proposal_type === "action";
          const boundary = proposal.boundary ?? {};
          return (
            <div
              key={`${proposal.agent_id}-${proposal.proposal_type}`}
              className={`rounded border p-2 ${
                accepted
                  ? "border-emerald-300/45 bg-emerald-950/20"
                  : proposal.proposal_type === "gate"
                    ? "border-red-300/35 bg-red-950/15"
                    : proposal.proposal_type === "bridge"
                      ? "border-cyan-300/35 bg-cyan-950/15"
                      : "border-slate-800 bg-slate-900/80"
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-[11px] font-black text-slate-100">{proposal.role ?? humanizeId(proposal.agent_id)}</div>
                  <div className="mt-0.5 text-[8px] font-black uppercase tracking-widest text-slate-500">
                    {proposal.proposal_type ?? "proposal"} / {boundary.can_dispatch ? "can emit bounded payload" : "advisory only"}
                  </div>
                </div>
                <span className={`shrink-0 rounded px-1.5 py-0.5 text-[8px] font-black uppercase ${accepted ? "bg-emerald-300 text-slate-950" : "bg-slate-950 text-slate-400"}`}>
                  {accepted ? "bridge pick" : "bounded"}
                </span>
              </div>
              <div className="mt-1 line-clamp-2 text-[10px] leading-relaxed text-slate-300">{proposal.recommendation}</div>
              <div className="mt-1 grid grid-cols-2 gap-1 text-[9px] leading-snug">
                <div className="rounded bg-slate-950/75 p-1.5">
                  <div className="font-black uppercase tracking-widest text-emerald-300/80">Allowed</div>
                  <div className="mt-0.5 line-clamp-1 text-slate-300">{(boundary.decision_rights ?? []).slice(0, 2).join(", ") || "read context"}</div>
                </div>
                <div className="rounded bg-slate-950/75 p-1.5">
                  <div className="font-black uppercase tracking-widest text-red-300/80">Blocked</div>
                  <div className="mt-0.5 line-clamp-1 text-slate-300">{(boundary.blocked_actions ?? []).slice(0, 2).join(", ") || "unsafe authority"}</div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-2 rounded border border-slate-800 bg-slate-950/80 p-2 text-[10px] leading-relaxed text-slate-300">
        <span className="font-black uppercase tracking-widest text-cyan-300">Decision Bridge </span>
        {resolution?.summary ?? "chooses the final action only after specialist boundaries and policy gates are visible."}
      </div>
    </div>
  );
}

function selectionToneClass(tone?: MapSelection["tone"]) {
  if (tone === "risk") return "border-orange-300/50 bg-orange-950/35 text-orange-50";
  if (tone === "watch") return "border-amber-300/50 bg-amber-950/30 text-amber-50";
  return "border-cyan-300/45 bg-cyan-950/25 text-cyan-50";
}

function SelectedPlacePanel({
  selection,
  onAction,
}: {
  selection: MapSelection | null;
  onAction: (action: string) => void;
}) {
  const [customerQuestion, setCustomerQuestion] = useState("");
  const [customerResponse, setCustomerResponse] = useState<string | null>(null);
  const [customerAction, setCustomerAction] = useState<string | null>(null);
  const [customerRuntime, setCustomerRuntime] = useState<string | null>(null);
  const [customerAgentBuilder, setCustomerAgentBuilder] = useState<{
    name?: string;
    requested_tool?: string;
    execution_boundary?: string;
    allowed_tools?: string[];
  } | null>(null);
  const [isCustomerAgentRunning, setIsCustomerAgentRunning] = useState(false);

  if (!selection) {
    return (
      <div className="rounded-lg border border-slate-800 bg-slate-950/80 p-3 text-sm text-slate-400">
        Click a ride, queue, food area, facility, guest cluster, or customer support station on the park map to inspect it here.
      </div>
    );
  }

  const isSupportStation = selection.kind === "support-station";
  const supportQuestions = selection.actions.filter((action) => action !== "Ask a question" && action !== "Get recommendation");
  const answerCustomer = async (mode: "question" | "recommendation" | "route" | "phone", question?: string) => {
    const topic = question?.trim() || customerQuestion.trim() || supportQuestions[0] || "What should I do next?";
    setCustomerQuestion(topic);
    setCustomerAction("Customer agent thinking");
    setCustomerRuntime("LLM request in progress");
    setCustomerResponse(null);
    setCustomerAgentBuilder(null);
    setIsCustomerAgentRunning(true);
    try {
      const response = await fetchParkPulseApi("/api/park/customer-support-agent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        timeoutMs: 12000,
        body: JSON.stringify({
          mode,
          question: topic,
          station: {
            id: selection.id,
            title: selection.title,
            status: selection.status,
            waitMins: selection.waitMins,
            detail: selection.detail,
            prompt: selection.prompt,
          },
        }),
      });
      const payload = (await response.json()) as {
        answer?: string;
        status?: string;
        mode?: string;
        customer_action?: { label?: string };
        runtime?: { provider?: string; model?: string; live?: boolean; fallbackReason?: string };
        agent_builder?: {
          name?: string;
          requested_tool?: string;
          execution_boundary?: string;
          allowed_tools?: string[];
        };
      };
      setCustomerResponse(payload.answer ?? "The customer agent returned no answer. Please try again.");
      setCustomerAction(payload.customer_action?.label ?? (mode === "recommendation" ? "Recommendation ready" : mode === "route" ? "Route shown" : mode === "phone" ? "Sent to phone" : "Answered at station"));
      setCustomerAgentBuilder(payload.agent_builder ?? null);
      setCustomerRuntime(
        payload.runtime?.live
          ? `${payload.runtime.provider ?? "Gemini"} / ${payload.runtime.model ?? "model"}`
          : `Fallback: ${payload.runtime?.fallbackReason ?? payload.mode ?? payload.status ?? "customer agent unavailable"}`,
      );
    } catch (error) {
      setCustomerAction("Local fallback");
      setCustomerRuntime(error instanceof Error ? `API unavailable: ${error.message}` : "API unavailable");
      setCustomerAgentBuilder(null);
      setCustomerResponse(
        mode === "route"
          ? "Route ready: head toward Theater B through the covered path, then reassess waits before joining another ride queue."
          : mode === "phone"
            ? "Sent to phone: recommendation, route notes, and the station wait estimate are ready for the guest app."
            : mode === "recommendation"
              ? "Recommendation: start with Theater B or Arcade Zone, then check Food Court Guide after the pickup rush eases."
              : `Answer: ${selection.title} can help with "${topic}". Choose a lower-crowd indoor option first and avoid adding pressure to delayed queues.`,
      );
    } finally {
      setIsCustomerAgentRunning(false);
    }
  };

  return (
    <div className={`rounded-lg border p-3 ${selectionToneClass(selection.tone)}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[9px] font-black uppercase tracking-widest opacity-70">{humanizeId(selection.kind)}</div>
          <div className="mt-1 text-base font-black leading-tight">{selection.title}</div>
          <div className="mt-1 text-[11px] font-bold opacity-80">{selection.subtitle}</div>
        </div>
        <span className="shrink-0 rounded bg-slate-950/75 px-2 py-1 text-[9px] font-black uppercase">{humanizeId(selection.status)}</span>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 text-center text-[10px] font-black">
        <div className="rounded bg-slate-950/65 p-2">
          <div className="uppercase tracking-widest opacity-60">Wait</div>
          <div className="mt-1 text-sm">{typeof selection.waitMins === "number" ? `${selection.waitMins}m` : "--"}</div>
        </div>
        <div className="rounded bg-slate-950/65 p-2">
          <div className="uppercase tracking-widest opacity-60">Guests</div>
          <div className="mt-1 text-sm">{typeof selection.guests === "number" ? selection.guests.toLocaleString() : "--"}</div>
        </div>
      </div>
      <div className="mt-3 rounded border border-white/10 bg-slate-950/55 p-2 text-[11px] leading-relaxed opacity-90">
        {selection.detail}
      </div>
      {isSupportStation ? (
        <div className="mt-3 grid gap-2 rounded-lg border border-cyan-300/25 bg-slate-950/70 p-2">
          <div className="flex items-center justify-between gap-2">
            <div>
              <div className="text-[9px] font-black uppercase tracking-widest text-cyan-300">Customer support kiosk</div>
              <div className="mt-1 text-[11px] leading-relaxed text-cyan-50/85">
                Ask a question, get a wait-aware recommendation, or send a route to the guest app without entering the operator console.
              </div>
            </div>
            <span className="shrink-0 rounded bg-cyan-300 px-2 py-1 text-[8px] font-black uppercase text-slate-950">
              customer
            </span>
          </div>
          <textarea
            value={customerQuestion}
            onChange={(event) => setCustomerQuestion(event.target.value)}
            className="h-16 w-full resize-none rounded border border-cyan-300/20 bg-slate-950 p-2 text-[11px] leading-relaxed text-slate-100 outline-none transition placeholder:text-slate-600 focus:border-cyan-300"
            placeholder="Ask this station for a route, food idea, short wait, accessibility help..."
          />
          <div className="grid grid-cols-2 gap-1">
            <button
              type="button"
              disabled={isCustomerAgentRunning}
              onClick={() => void answerCustomer("question")}
              className="rounded bg-cyan-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-cyan-200 disabled:bg-slate-700 disabled:text-slate-400"
            >
              {isCustomerAgentRunning ? "Asking..." : "Ask station"}
            </button>
            <button
              type="button"
              disabled={isCustomerAgentRunning}
              onClick={() => void answerCustomer("recommendation")}
              className="rounded border border-cyan-300/50 bg-cyan-950/60 px-3 py-2 text-xs font-black text-cyan-100 transition hover:bg-cyan-900/70 disabled:border-slate-800 disabled:bg-slate-900 disabled:text-slate-500"
            >
              Recommend
            </button>
            <button
              type="button"
              disabled={isCustomerAgentRunning}
              onClick={() => void answerCustomer("route")}
              className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-100 transition hover:border-cyan-300 hover:text-cyan-100 disabled:border-slate-800 disabled:text-slate-600"
            >
              Show route
            </button>
            <button
              type="button"
              disabled={isCustomerAgentRunning}
              onClick={() => void answerCustomer("phone")}
              className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-100 transition hover:border-cyan-300 hover:text-cyan-100 disabled:border-slate-800 disabled:text-slate-600"
            >
              Send to phone
            </button>
          </div>
          {!!supportQuestions.length && (
            <div className="grid gap-1">
              {supportQuestions.slice(0, 2).map((question) => (
                <button
                  key={question}
                  type="button"
                  disabled={isCustomerAgentRunning}
                  onClick={() => {
                    setCustomerQuestion(question);
                    void answerCustomer("question", question);
                  }}
                  className="rounded border border-white/10 bg-slate-900/80 px-2 py-1.5 text-left text-[10px] font-bold text-slate-200 transition hover:border-cyan-300 hover:text-cyan-100 disabled:border-slate-800 disabled:text-slate-600"
                >
                  {question}
                </button>
              ))}
            </div>
          )}
          <div className="min-h-20 rounded border border-cyan-300/20 bg-cyan-950/25 p-2 text-[11px] leading-relaxed text-cyan-50">
            <div className="text-[8px] font-black uppercase tracking-widest text-cyan-300">
              {customerAction ?? "Station ready"}
            </div>
            <div className="mt-1">
              {isCustomerAgentRunning ? "The customer agent is grounding the answer in current park waits, crowd flow, food pressure, and weather." : customerResponse ?? "Ask the station for directions, recommendations, food options, accessibility help, or recovery support."}
            </div>
            {customerRuntime && <div className="mt-2 truncate text-[9px] font-black uppercase tracking-widest text-cyan-200/70">{customerRuntime}</div>}
            {customerAgentBuilder && (
              <div className="mt-2 rounded border border-cyan-300/15 bg-slate-950/60 p-2">
                <div className="text-[8px] font-black uppercase tracking-widest text-cyan-300/80">Agent Builder boundary</div>
                <div className="mt-1 text-[10px] font-bold text-cyan-50/90">
                  {customerAgentBuilder.name ?? "Customer Support Agent"} / {customerAgentBuilder.requested_tool ?? "customer tool"}
                </div>
                <div className="mt-1 line-clamp-2 text-[9px] leading-relaxed text-cyan-50/65">
                  {customerAgentBuilder.execution_boundary ?? "Customer self-service only; no operator dispatch."}
                </div>
                {!!customerAgentBuilder.allowed_tools?.length && (
                  <div className="mt-1 truncate text-[8px] font-black uppercase tracking-widest text-cyan-200/60">
                    Tools: {customerAgentBuilder.allowed_tools.slice(0, 4).join(", ")}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="mt-3 grid gap-2">
          {selection.actions.map((action) => (
            <button
              key={action}
              type="button"
              onClick={() => onAction(action)}
              className="rounded border border-white/15 bg-slate-950/60 px-3 py-2 text-left text-xs font-black transition hover:border-cyan-300 hover:text-cyan-100"
            >
              {action}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ReceiverActionsPanel({
  dispatches,
  isRunning,
  onReceiverAck,
}: {
  dispatches: DeliveryDispatch[];
  isRunning: boolean;
  onReceiverAck?: (dispatch: DeliveryDispatch | undefined, actor: string, choice: string) => void;
}) {
  const channels = [
    { key: "guest_app", label: "Guest message", fallback: "No guest message prepared yet.", actions: ["Preview", "Send", "Hold"] },
    { key: "worker_device", label: "Staff task", fallback: "No staff task prepared yet.", actions: ["Preview", "Acknowledge", "Request detail"] },
    { key: "equipment_controller", label: "Equipment command", fallback: "No equipment command prepared yet.", actions: ["Preview", "Approve", "Hold"] },
  ] as const;

  return (
    <div className="grid gap-2">
      {channels.map((channel) => {
        const dispatch = dispatches.find((item) => item.channel === channel.key);
        return (
          <div key={channel.key} className="rounded-lg border border-slate-800 bg-slate-950/80 p-3">
            <div className="flex items-center justify-between gap-2">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">{channel.label}</div>
              <span className="rounded bg-slate-900 px-2 py-1 text-[9px] font-black uppercase text-slate-300">{humanizeId(receiverStatus(dispatch, isRunning))}</span>
            </div>
            <div className="mt-2 line-clamp-2 text-xs font-bold leading-relaxed text-slate-200">
              {dispatch ? dispatchBody(dispatch) : channel.fallback}
            </div>
            <div className="mt-3 grid grid-cols-3 gap-1">
              {channel.actions.map((action) => (
                <button
                  key={action}
                  type="button"
                  disabled={!dispatch && action !== "Preview"}
                  onClick={() => onReceiverAck?.(dispatch, channel.key, action)}
                  className="rounded border border-slate-700 px-2 py-1.5 text-[10px] font-black text-slate-200 transition hover:border-cyan-300 hover:text-cyan-100 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {action}
                </button>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function DigitalTwinToolsPanel({ trace }: { trace?: DigitalTwinToolTrace }) {
  const calls = trace?.tool_calls ?? [];
  const visibleCalls = calls.filter((call) =>
    ["get_park_state", "get_ride_status", "simulate_action", "compare_action_candidates", "validate_policy", "score_decision_quality"].includes(call.tool ?? ""),
  );

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Digital twin MCP tools</div>
          <h2 className="mt-1 text-sm font-black text-slate-100">Agent tool trace, not a static recommendation</h2>
        </div>
        <span className="rounded bg-slate-950 px-2 py-1 text-[9px] font-black uppercase text-slate-300">
          {trace?.tool_count ?? 0} calls
        </span>
      </div>
      <div className="mt-2 text-[10px] leading-relaxed text-slate-500">
        {trace?.summary?.boundary ?? "Run the AI response to show the agent reading, simulating, comparing, gating, and scoring through the digital twin."}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        {(visibleCalls.length ? visibleCalls : [
          { tool: "get_park_state", output: { status: "waiting" } },
          { tool: "simulate_action", output: { status: "waiting" } },
          { tool: "validate_policy", output: { status: "waiting" } },
          { tool: "score_decision_quality", output: { status: "waiting" } },
        ]).slice(0, 6).map((call, index) => {
          const output = call.output ?? {};
          const metric =
            output.gate_status ??
            output.overall ??
            output.selected ??
            output.status ??
            output.capacity_read ??
            "ready";
          return (
            <div key={`${call.tool}-${index}`} className={`rounded border p-2 ${toolToneClass(call.tool)}`}>
              <div className="truncate text-[9px] font-black uppercase tracking-widest">{call.tool?.replaceAll("_", " ")}</div>
              <div className="mt-1 truncate text-xs font-black">{String(metric)}</div>
            </div>
          );
        })}
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2 text-center text-[10px] font-black">
        {[
          ["Ride", trace?.summary?.selected_ride ?? "--"],
          ["Gate", trace?.summary?.policy_gate ?? "--"],
          ["Score", trace?.summary?.quality_score ?? "--"],
        ].map(([label, value]) => (
          <div key={label} className="rounded bg-slate-950 p-2">
            <div className="text-slate-500">{label}</div>
            <div className="mt-1 truncate text-slate-100">{value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function MessySignalConsole({
  signalText,
  triage,
  isTriaging,
  isFusingSignals,
  onSignalTextChange,
  onTriageSignal,
  onRunSignalFusion,
  onRunHealthSignal,
}: {
  signalText: string;
  triage: SignalTriageResult | null;
  isTriaging: boolean;
  isFusingSignals: boolean;
  onSignalTextChange: (value: string) => void;
  onTriageSignal: () => void;
  onRunSignalFusion: () => void;
  onRunHealthSignal: () => void;
}) {
  const signal = triage?.signal;
  const response = triage?.delivery?.response;
  const actions = signal?.recommended_actions ?? [];
  const sourceSignals = signal?.source_signals ?? [];
  const learning = triage?.learning;
  const similarEpisodes = learning?.similar_episodes ?? [];
  const timeline = learning?.operational_timeline ?? [];

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[10px] font-black uppercase tracking-widest text-amber-300">Signal intake</div>
          <div className="mt-1 text-sm font-black text-slate-100">Unstructured report</div>
        </div>
        <span className={`rounded px-2 py-1 text-[9px] font-black uppercase ${riskBadgeClass(signal?.risk_level)}`}>
          {signal?.risk_level ?? "untriaged"}
        </span>
      </div>

      <textarea
        value={signalText}
        onChange={(event) => onSignalTextChange(event.target.value)}
        className="mt-3 h-20 w-full resize-none rounded border border-slate-700 bg-slate-950 p-3 text-xs leading-relaxed text-slate-200 outline-none transition focus:border-amber-300"
      />
      <button
        type="button"
        onClick={onTriageSignal}
        disabled={isTriaging || isFusingSignals || signalText.trim().length < 6}
        className="mt-2 w-full rounded bg-amber-300 px-4 py-2.5 text-xs font-black text-slate-950 transition hover:bg-amber-200 disabled:bg-slate-700 disabled:text-slate-400"
      >
        {isTriaging ? "Triaging..." : "Triage report"}
      </button>
      <button
        type="button"
        onClick={onRunSignalFusion}
        disabled={isTriaging || isFusingSignals}
        className="mt-2 w-full rounded border border-cyan-400/40 bg-cyan-950/30 px-4 py-2.5 text-xs font-black text-cyan-100 transition hover:bg-cyan-900/40 disabled:border-slate-700 disabled:bg-slate-900 disabled:text-slate-500"
      >
        {isFusingSignals ? "Fusing feeds..." : "Run signal fusion"}
      </button>
      <button
        type="button"
        onClick={onRunHealthSignal}
        disabled={isTriaging || isFusingSignals}
        className="mt-2 w-full rounded border border-red-400/40 bg-red-950/25 px-4 py-2.5 text-xs font-black text-red-100 transition hover:bg-red-900/35 disabled:border-slate-700 disabled:bg-slate-900 disabled:text-slate-500"
      >
        Run health/accessibility signal
      </button>

      {signal ? (
        <div className="mt-3 grid gap-2">
          <div className="grid grid-cols-3 gap-2 text-center">
            <div className="rounded border border-slate-800 bg-slate-950 p-2">
              <div className="text-[9px] font-black uppercase text-slate-500">Zone</div>
              <div className="mt-1 truncate text-xs font-black text-slate-100">{signal.zone?.name ?? "Unknown"}</div>
            </div>
            <div className="rounded border border-slate-800 bg-slate-950 p-2">
              <div className="text-[9px] font-black uppercase text-slate-500">Confidence</div>
              <div className="mt-1 text-xs font-black text-slate-100">{ratePct(signal.confidence)}</div>
            </div>
            <div className="rounded border border-slate-800 bg-slate-950 p-2">
              <div className="text-[9px] font-black uppercase text-slate-500">Escalate</div>
              <div className="mt-1 text-xs font-black text-slate-100">L{signal.escalation_level ?? 1}</div>
            </div>
          </div>

          {signal.fusion && (
            <div className="rounded border border-cyan-400/30 bg-cyan-950/20 p-3">
              <div className="flex items-center justify-between gap-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-cyan-200">Signal fusion</div>
                <div className="text-[10px] font-black uppercase text-cyan-100">
                  {signal.fusion.corroboration_count ?? 0}/{signal.fusion.source_count ?? 0} agree
                </div>
              </div>
              <div className="mt-2 text-[11px] leading-relaxed text-cyan-100">{signal.fusion.agent_read}</div>
              <div className="mt-2 text-[10px] font-black uppercase text-amber-200">
                {signal.fusion.disagreement ? "Conflict present: verify before public messaging" : "Sources directionally consistent"}
              </div>
            </div>
          )}

          {!!sourceSignals.length && (
            <div className="rounded border border-slate-800 bg-slate-950 p-3">
              <div className="flex items-center justify-between gap-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Evidence feeds</div>
                <div className="text-[10px] font-black text-slate-400">{sourceSignals.length} sources</div>
              </div>
              <div className="mt-2 grid max-h-40 gap-2 overflow-y-auto pr-1">
                {sourceSignals.map((item) => (
                  <div key={`${item.source}-${item.id}`} className="rounded border border-slate-800 bg-slate-900 p-2">
                    <div className="flex items-center justify-between gap-2">
                      <div className="truncate text-[11px] font-black text-slate-100">{item.source_label ?? item.source}</div>
                      <span className={`shrink-0 rounded px-1.5 py-0.5 text-[8px] font-black uppercase ${riskBadgeClass(item.risk_level)}`}>{item.risk_level ?? "watch"}</span>
                    </div>
                    <div className="mt-1 line-clamp-2 text-[10px] leading-relaxed text-slate-500">{item.text}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {learning && (
            <div className="rounded border border-violet-400/30 bg-violet-950/20 p-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-[10px] font-black uppercase tracking-widest text-violet-200">Episode learning</div>
                  <div className="mt-1 text-[11px] font-black text-slate-100">{learning.dataset ?? "parkpulse_training_episodes"}</div>
                </div>
                <div className="text-right text-[10px] font-black uppercase text-violet-100">
                  {learning.priors?.confirmed_incident_count ?? 0} confirmed / {learning.priors?.false_alarm_count ?? 0} false
                </div>
              </div>
              {!!timeline.length && (
                <div className="mt-3 grid gap-2">
                  {timeline.map((item, index) => (
                    <div key={`${item.step}-${index}`} className={`grid grid-cols-[1.5rem_1fr] gap-2 rounded border p-2 ${timelineStatusClass(item.status)}`}>
                      <div className="flex h-6 w-6 items-center justify-center rounded bg-slate-950/80 text-[10px] font-black">{index + 1}</div>
                      <div>
                        <div className="text-[10px] font-black uppercase tracking-widest">{item.label}</div>
                        <div className="mt-1 line-clamp-2 text-[10px] leading-relaxed opacity-80">{item.detail}</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              <div className="mt-2 grid grid-cols-2 gap-2 text-[10px]">
                <div className="rounded bg-slate-950/70 p-2">
                  <div className="font-black uppercase text-slate-500">Best prior</div>
                  <div className="mt-1 line-clamp-2 font-bold text-slate-200">{learning.priors?.best_action?.replaceAll("_", " ") ?? "No prior"}</div>
                </div>
                <div className="rounded bg-slate-950/70 p-2">
                  <div className="font-black uppercase text-slate-500">Expected response</div>
                  <div className="mt-1 font-bold text-slate-200">
                    {learning.priors?.expected_response?.median_ack_seconds ? `${learning.priors.expected_response.median_ack_seconds}s ack` : "pending"} / {learning.priors?.expected_response?.typical_density_delta_10min ?? "--"}% density
                  </div>
                </div>
              </div>
              <div className="mt-2 grid max-h-40 gap-2 overflow-y-auto pr-1">
                {similarEpisodes.map((episode) => (
                  <div key={episode.episode_id} className="rounded border border-violet-400/20 bg-slate-950/80 p-2">
                    <div className="flex items-center justify-between gap-2">
                      <div className="truncate text-[11px] font-black text-slate-100">{episode.incident_type?.replaceAll("_", " ")}</div>
                      <span className="rounded bg-violet-300 px-1.5 py-0.5 text-[8px] font-black text-slate-950">{Math.round((episode.match ?? 0) * 100)}%</span>
                    </div>
                    <div className="mt-1 line-clamp-2 text-[10px] leading-relaxed text-slate-400">{episode.lesson}</div>
                    <div className="mt-1 text-[9px] font-black uppercase text-violet-200">
                      {(episode.why_match ?? []).slice(0, 2).join(" / ")} {episode.memory_source ? `/ ${episode.memory_source.replaceAll("_", " ")}` : ""}
                    </div>
                  </div>
                ))}
              </div>
              <div className="mt-2 rounded border border-violet-400/20 bg-slate-950/70 p-2 text-[10px] leading-relaxed text-slate-400">
                New training row: {learning.current_training_episode?.episode_id ?? "pending"} / {learning.current_training_episode?.incident_type?.replaceAll("_", " ")}
                <span className="ml-2 font-black text-violet-200">
                  {learning.persistence?.status ?? "pending"} {learning.persistence?.stored_episode_count ? `/ ${learning.persistence.stored_episode_count} stored` : ""}
                </span>
              </div>
              {learning.retrieval_quality && (
                <div className="mt-2 rounded border border-violet-400/20 bg-slate-950/70 p-2 text-[10px] leading-relaxed text-violet-100">
                  Retrieval quality: {learning.retrieval_quality.status?.replaceAll("_", " ")} / {learning.retrieval_quality.judge_note}
                </div>
              )}
            </div>
          )}

          <div className="rounded border border-slate-800 bg-slate-950 p-3">
            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Next actions</div>
            <div className="mt-2 grid gap-2">
              {actions.slice(0, 2).map((action, index) => (
                <div key={`${action.owner}-${action.operation}-${index}`} className="grid grid-cols-[1.5rem_1fr] gap-2 text-xs">
                  <div className="flex h-6 w-6 items-center justify-center rounded bg-amber-300 text-[10px] font-black text-slate-950">{index + 1}</div>
                  <div>
                    <div className="font-black text-slate-200">{action.owner}</div>
                    <div className="mt-1 line-clamp-2 leading-relaxed text-slate-400">{action.action}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2 text-xs">
            <div className="rounded border border-slate-800 bg-slate-950 p-3">
              <div className="text-[10px] font-black uppercase text-slate-500">Receivers</div>
              <div className="mt-1 font-black text-slate-100">{triage?.delivery?.summary?.total ?? 0} payloads</div>
            </div>
            <div className="rounded border border-slate-800 bg-slate-950 p-3">
              <div className="text-[10px] font-black uppercase text-slate-500">Response</div>
              <div className="mt-1 font-black text-slate-100">{response ? `${ratePct(response.takeRate)} take` : "pending"}</div>
            </div>
          </div>
        </div>
      ) : (
        <div className="mt-2 rounded border border-slate-800 bg-slate-950 p-3 text-xs leading-relaxed text-slate-500">
          Triage guest complaints or staff notes, then the map and policy gates update from the result.
        </div>
      )}
    </div>
  );
}

export type LiveIssue = {
  id: string;
  title: string;
  location: string;
  detail: string;
  metric: string;
  tone: "risk" | "watch" | "ok";
};

export type StreamTraceEvent = {
  phase?: string;
  label?: string;
  step?: number;
  message?: string;
  elapsed_ms?: number;
  artifact?: Record<string, unknown>;
};

export function issueBadgeClass(tone: LiveIssue["tone"]) {
  if (tone === "risk") return "border-red-400/40 bg-red-950/25 text-red-100";
  if (tone === "watch") return "border-amber-400/40 bg-amber-950/25 text-amber-100";
  return "border-emerald-400/40 bg-emerald-950/20 text-emerald-100";
}

export function buildLiveIssues(flow: GuestFlow, state: ParkState, signal?: SignalTriageResult["signal"]): LiveIssue[] {
  const physicalMap = state.physicalMap ?? DEFAULT_PHYSICAL_MAP;
  const rides = sortedByRisk(flow.rides, (ride) => ride.waitMins + ride.queueGuests / 20 + ride.downtimeRisk / 3, 1);
  const zones = sortedByRisk(flow.zones, (zone) => zone.density + zone.waitMins, 1);
  const queue = sortedByRisk(physicalMap.queues, (item) => item.waitMins + item.guests / 25 + (item.spillbackRisk === "critical" ? 60 : item.spillbackRisk === "watch" ? 20 : 0), 1);
  const food = sortedByRisk(state.foodInventory?.locations ?? [], (item) => item.pickupEtaMinutes + item.mobileOrderBacklog / 8 + item.lowInventoryItems.length * 10, 1);
  const foodZone = flow.zones.find((zone) => zone.processType === "food");
  const care = state.guestCare;
  const readiness = state.incidentReadiness;
  const guestTone = flow.avgSatisfaction < 72 ? "risk" : flow.avgSatisfaction < 80 ? "watch" : "ok";
  const liveSignalIssue = signal
    ? [{
        id: "signal",
        title: signal.zone?.name ? `Guest report near ${signal.zone.name}` : "Guest report needs operator review",
        location: signal.zone?.name ?? "Reported zone",
        detail: signal.text ?? signal.triage_explanation ?? "Unstructured signal has been classified against the policy book.",
        metric: signal.risk_level ?? "review",
        tone: signal.risk_level === "CRITICAL" || signal.risk_level === "HIGH" ? "risk" : "watch",
      } satisfies LiveIssue]
    : [];

  return [
    ...liveSignalIssue,
    rides[0] && {
      id: "ride",
      title: `${rides[0].name} demand pressure`,
      location: "Attraction footprint",
      detail: `${rides[0].queueGuests.toLocaleString()} guests in queue with ${rides[0].status} operating state.`,
      metric: `${rides[0].waitMins}m`,
      tone: rides[0].waitMins >= 45 || rides[0].status !== "normal" ? "risk" : "watch",
    },
    queue[0] && {
      id: "queue",
      title: `${queue[0].name} spillback`,
      location: "Queue layer",
      detail: `${queue[0].shadePct}% shade coverage, ${queue[0].guests.toLocaleString()} guests, ${queue[0].spillbackRisk} spillback.`,
      metric: `${queue[0].guests}`,
      tone: queue[0].spillbackRisk === "critical" ? "risk" : "watch",
    },
    zones[0] && {
      id: "zone",
      title: `${zones[0].name} crowd density`,
      location: "Signal layer",
      detail: `${zones[0].currentGuests.toLocaleString()} guests with ${zones[0].waitMins}m local wait.`,
      metric: pct(zones[0].density),
      tone: zones[0].density >= 80 ? "risk" : "watch",
    },
    food[0] && {
      id: "food",
      title: `${food[0].name} pickup backlog`,
      location: "Food service",
      detail: `${food[0].mobileOrderBacklog} mobile orders, ${food[0].lowInventoryItems.length ? `${food[0].lowInventoryItems.join(", ")} low` : "inventory stable"}.`,
      metric: `${food[0].pickupEtaMinutes}m`,
      tone: food[0].pickupEtaMinutes >= 18 || food[0].lowInventoryItems.length > 0 ? "watch" : "ok",
    },
    !food[0] && foodZone && {
      id: "food-zone",
      title: `${foodZone.name} service wait`,
      location: "Food service",
      detail: `${foodZone.currentGuests.toLocaleString()} guests in the food zone with ${foodZone.waitMins}m local wait.`,
      metric: `${foodZone.waitMins}m`,
      tone: foodZone.waitMins >= 20 ? "watch" : "ok",
    },
    care ? {
      id: "care",
      title: "Guest care case pressure",
      location: "Customer care",
      detail: `${care.openCases} open cases with ${care.complaintRatePct}% complaint rate.`,
      metric: `${care.openCases}`,
      tone: care.openCases >= 12 || care.complaintRatePct >= 8 ? "watch" : "ok",
    } : {
      id: "care",
      title: "Guest experience watch",
      location: "Customer care",
      detail: `Average satisfaction is ${pct(flow.avgSatisfaction)} while operators monitor complaints and recovery offers.`,
      metric: pct(flow.avgSatisfaction),
      tone: guestTone,
    },
    readiness ? {
      id: "readiness",
      title: "Incident access readiness",
      location: "Operations layer",
      detail: readiness.emergencyAccessBlocked ? "Emergency access route is blocked and must be cleared." : "Emergency and accessibility routes are open.",
      metric: readiness.operatorEscalation ?? "watch",
      tone: readiness.emergencyAccessBlocked ? "risk" : readiness.operatorEscalation === "monitor" ? "watch" : "ok",
    } : {
      id: "readiness",
      title: "Medical access corridor",
      location: "Operations layer",
      detail: "Emergency route, backstage service road, and guest-visible paths are separated on the operations layer.",
      metric: "open",
      tone: "ok",
    },
  ].filter(Boolean).slice(0, 6) as LiveIssue[];
}

export function scenarioLeadIssue(scenario: DemoScenario, fallback?: LiveIssue): LiveIssue {
  return fallback ?? {
    id: "waiting_for_custom_input",
    title: "Waiting for a custom park signal",
    location: "Live park",
    detail: "ParkPulse will frame the issue from live data, operator text, and returned agent telemetry.",
    metric: "ready",
    tone: "ok",
  };
}

export function LiveIssueTimeline({ issues }: { issues: LiveIssue[] }) {
  return (
    <div className="grid gap-2 border-t border-slate-800 bg-slate-950 p-3 md:grid-cols-3 xl:grid-cols-6">
      {issues.map((issue) => (
        <article key={issue.id} className={`rounded-lg border p-3 ${issueBadgeClass(issue.tone)}`}>
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="truncate text-[10px] font-black uppercase tracking-widest opacity-70">{issue.location}</div>
              <div className="mt-1 line-clamp-2 text-sm font-black">{issue.title}</div>
            </div>
            <span className="shrink-0 rounded bg-slate-950/70 px-2 py-1 text-[10px] font-black uppercase">{issue.metric}</span>
          </div>
          <div className="mt-2 line-clamp-2 text-[11px] leading-relaxed opacity-80">{issue.detail}</div>
        </article>
      ))}
    </div>
  );
}

export function aiStepClass(status: AiStepStatus) {
  if (status === "done") return "border-emerald-400/35 bg-emerald-950/20 text-emerald-100";
  if (status === "active") return "border-cyan-300/60 bg-cyan-950/40 text-cyan-50";
  return "border-slate-800 bg-slate-950 text-slate-400";
}

export function AiStepTimeline({ steps }: { steps: AiDemoStep[] }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">AI operation timeline</div>
        <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">live state</div>
      </div>
      <div className="mt-3 grid gap-2">
        {steps.map((step, index) => (
          <div key={step.id} className={`grid grid-cols-[1.6rem_1fr_3.2rem] items-start gap-2 rounded border p-2 ${aiStepClass(step.status)}`}>
            <div className={`flex h-6 w-6 items-center justify-center rounded text-[10px] font-black ${step.status === "active" ? "bg-cyan-300 text-slate-950 park-command-pulse" : step.status === "done" ? "bg-emerald-300 text-slate-950" : "bg-slate-800 text-slate-300"}`}>
              {index + 1}
            </div>
            <div className="min-w-0">
              <div className="text-xs font-black">{step.label}</div>
              <div className="mt-1 line-clamp-2 text-[10px] leading-relaxed opacity-75">{step.detail}</div>
            </div>
            <div className="truncate rounded bg-slate-950/70 px-2 py-1 text-center text-[9px] font-black uppercase">{step.metric}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function AiReasoningReceipt({ proof, scenario }: { proof: ReturnType<typeof scenarioProof>; scenario: DemoScenario }) {
  const rows = [
    ["Signal read", proof.signal],
    ["Safety check", proof.policy],
    ["Selected action", proof.action],
    ["Measured result", proof.result],
  ] as const;

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="text-[10px] font-black uppercase tracking-widest text-violet-300">AI reasoning receipt</div>
        <div className={scenario.humanApproval ? "rounded bg-amber-300 px-2 py-1 text-[9px] font-black uppercase text-slate-950" : "rounded bg-emerald-300 px-2 py-1 text-[9px] font-black uppercase text-slate-950"}>
          {scenario.humanApproval ? "approval gate" : "auto safe"}
        </div>
      </div>
      <div className="mt-3 grid gap-2">
        {rows.map(([label, value]) => (
          <div key={label} className="rounded border border-slate-800 bg-slate-950 p-2">
            <div className="text-[9px] font-black uppercase tracking-widest text-slate-500">{label}</div>
            <div className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-slate-200">{value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

type RouteMixTarget = { destination?: string; share?: number; currentWaitMins?: number };

function getRouteMix(telemetry: ProactiveRunTelemetry | RunTelemetry | null, dispatches: DeliveryDispatch[]): RouteMixTarget[] {
  const dispatchMix = dispatches.find((dispatch) => dispatch.channel === "guest_app")?.payload?.targetMix;
  const runTelemetry = telemetry as RunTelemetry | null;
  const optimizedMix =
    runTelemetry?.optimization?.selected_plan?.action_mix?.guest_reroute?.target_mix ??
    runTelemetry?.revision?.action_mix?.guest_reroute?.target_mix;
  const mix = dispatchMix?.length ? dispatchMix : optimizedMix?.length ? optimizedMix : [];
  return mix.slice(0, 4);
}

function AgentTradeoffPanel({
  scenario: _scenario,
  telemetry,
  isActive,
}: {
  scenario: DemoScenario;
  telemetry: ProactiveRunTelemetry | RunTelemetry | null;
  isActive: boolean;
}) {
  const findings = (telemetry as RunTelemetry | null)?.agent_findings ?? [];
  const runtimeRows = findings.slice(0, 4).map((finding) => ({
    agent: finding.name ?? finding.agent ?? "Runtime agent",
    want: finding.recommendation ?? finding.finding ?? "Use live park state.",
    constraint: finding.input_signals?.[0] ?? finding.policy_refs?.[0] ?? finding.mode ?? "trace evidence",
    tone: finding.urgency ?? "watch",
  }));
  const fallbackRows = [
    { agent: "Signal", want: "Waiting for custom park input", constraint: "No canned incident loaded", tone: "watch" },
    { agent: "Policy", want: "Ready to gate the next action", constraint: "Safety, labor, privacy, and guest honesty rules", tone: "ok" },
    { agent: "Execution", want: "Ready to emit receiver payloads", constraint: "Guest, worker, and equipment channels need a live plan", tone: "watch" },
  ];
  const rows = runtimeRows.length ? runtimeRows : fallbackRows;

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Agent debate</div>
          <div className="mt-1 text-xs font-black text-slate-100">Conflict before action</div>
        </div>
        <div className={isActive ? "rounded bg-cyan-950 px-2 py-1 text-[9px] font-black uppercase text-cyan-300" : "rounded bg-slate-950 px-2 py-1 text-[9px] font-black uppercase text-slate-500"}>
          {isActive ? "reasoning" : "ready"}
        </div>
      </div>
      <div className="mt-3 grid gap-2">
        {rows.map((row) => (
          <div key={row.agent} className={`rounded border p-2 ${toneClass(row.tone as "risk" | "watch" | "ok")}`}>
            <div className="flex items-center justify-between gap-2">
              <div className="text-[10px] font-black uppercase tracking-widest opacity-80">{row.agent}</div>
              <div className="h-2 w-2 rounded-full bg-current opacity-70" />
            </div>
            <div className="mt-1 line-clamp-1 text-xs font-black">{row.want}</div>
            <div className="mt-1 line-clamp-1 text-[10px] opacity-70">{row.constraint}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function CustomRoutingMixPanel({
  telemetry,
  dispatches,
  isActive,
}: {
  telemetry: ProactiveRunTelemetry | RunTelemetry | null;
  dispatches: DeliveryDispatch[];
  isActive: boolean;
}) {
  const mix = getRouteMix(telemetry, dispatches);
  const totalShare = mix.reduce((sum, item) => sum + (item.share ?? 0), 0);
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <div className="text-[10px] font-black uppercase tracking-widest text-emerald-300">Custom decision</div>
          <div className="mt-1 text-xs font-black text-slate-100">Not one hard-coded reroute</div>
        </div>
        <div className={isActive ? "rounded bg-emerald-950 px-2 py-1 text-[9px] font-black uppercase text-emerald-300" : "rounded bg-slate-950 px-2 py-1 text-[9px] font-black uppercase text-slate-500"}>
          {Math.round(totalShare * 100)}% mix
        </div>
      </div>
      <div className="mt-3 grid gap-2">
        {mix.length ? mix.map((target, index) => {
          const share = Math.round((target.share ?? 0) * 100);
          return (
            <div key={`${target.destination}-${index}`} className="rounded border border-slate-800 bg-slate-950 p-2">
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="line-clamp-1 font-black text-slate-200">{target.destination ?? "Target"}</span>
                <span className="font-black text-emerald-300">{share}%</span>
              </div>
              <div className="mt-2 h-1.5 rounded bg-slate-800">
                <div className={`h-1.5 rounded ${index === 0 ? "bg-emerald-300" : index === 1 ? "bg-cyan-300" : index === 2 ? "bg-amber-300" : "bg-violet-300"}`} style={{ width: `${Math.max(6, share)}%` }} />
              </div>
              <div className="mt-1 text-[10px] text-slate-500">{target.currentWaitMins ? `${target.currentWaitMins}m current wait` : "hold or recovery buffer"}</div>
            </div>
          );
        }) : (
          <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs leading-relaxed text-slate-400">
            No reroute mix is shown until Gemini emits a route payload for this specific request.
          </div>
        )}
      </div>
    </div>
  );
}

function BeforeAfterImpactPanel({
  flow,
  scenario: _scenario,
  telemetry,
  response,
  isRunning,
  floating = true,
}: {
  flow: GuestFlow;
  scenario: DemoScenario;
  telemetry: ProactiveRunTelemetry | RunTelemetry | null;
  response?: { takeRate?: number; positiveResponseRate?: number; reactiveFollowThroughRate?: number };
  isRunning: boolean;
  floating?: boolean;
}) {
  const hottestZone = sortedByRisk(flow.zones, (zone) => zone.density + zone.waitMins, 1)[0];
  const highestQueue = sortedByRisk(flow.rides, (ride) => ride.queueGuests + ride.waitMins * 8, 1)[0];
  const impact = (telemetry as ProactiveRunTelemetry | null)?.lifecycle?.state_impact ?? (telemetry as RunTelemetry | null)?.outcome?.state_impact;
  const densityDelta = impact?.density_delta ?? 0;
  const queueDelta = impact?.queued_guest_delta ?? 0;
  const beforeDensity = hottestZone?.density ?? 0;
  const afterDensity = Math.max(0, Math.min(100, beforeDensity + densityDelta));
  const beforeQueue = highestQueue?.queueGuests ?? 0;
  const afterQueue = Math.max(0, beforeQueue + queueDelta);
  const status = isRunning ? "measuring" : telemetry ? "measured" : "waiting";
  const rows = [
    { label: hottestZone?.name ?? "Hot zone", before: `${beforeDensity}%`, after: telemetry || isRunning ? `${afterDensity}%` : "waiting", good: telemetry ? afterDensity < beforeDensity : false },
    { label: highestQueue?.name ?? "Queue", before: beforeQueue.toLocaleString(), after: telemetry || isRunning ? afterQueue.toLocaleString() : "waiting", good: telemetry ? afterQueue < beforeQueue : false },
    { label: "Guest take", before: "unknown", after: response ? ratePct(response.takeRate) : "waiting", good: Boolean(response?.takeRate && response.takeRate >= 0.4) },
  ];

  return (
    <div
      className={
        floating
          ? "pointer-events-none absolute bottom-4 left-4 z-40 w-[min(34rem,calc(100%-2rem))] rounded-lg border border-white/70 bg-slate-950/88 p-3 text-slate-100 shadow-2xl backdrop-blur"
          : "rounded-lg border border-slate-800 bg-slate-900 p-3 text-slate-100"
      }
    >
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Before -&gt; after impact</div>
          <div className="mt-1 text-xs font-black text-slate-200">Visible state movement, not just advice</div>
        </div>
        <div className={status === "measured" ? "rounded bg-emerald-300 px-2 py-1 text-[9px] font-black uppercase text-slate-950" : status === "measuring" ? "rounded bg-cyan-300 px-2 py-1 text-[9px] font-black uppercase text-slate-950 park-command-pulse" : "rounded bg-slate-800 px-2 py-1 text-[9px] font-black uppercase text-slate-300"}>
          {status}
        </div>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-3">
        {rows.map((row) => (
          <div key={row.label} className="rounded border border-slate-700 bg-slate-900/90 p-2">
            <div className="text-[9px] font-black uppercase tracking-widest text-slate-500">{row.label}</div>
            <div className="mt-1 flex items-center justify-between gap-2 text-xs font-black">
              <span className="text-red-200">{row.before}</span>
              <span className="text-slate-500">-&gt;</span>
              <span className={row.good ? "text-emerald-300" : "text-amber-300"}>{row.after}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function LearningMemoryPanel({
  telemetry,
  response,
}: {
  telemetry: ProactiveRunTelemetry | RunTelemetry | null;
  response?: { takeRate?: number; positiveResponseRate?: number; reactiveFollowThroughRate?: number };
}) {
  const comparison = (telemetry as ProactiveRunTelemetry | null)?.lifecycle?.intelligence_comparison ?? (telemetry as ProactiveRunTelemetry | null)?.intelligence_comparison;
  const proof = (telemetry as ProactiveRunTelemetry | null)?.learning_proof ?? (telemetry as ProactiveRunTelemetry | null)?.lifecycle?.learning_proof;
  const priors = (telemetry as ProactiveRunTelemetry | null)?.lifecycle?.bigquery_priors ?? telemetry?.analytics?.priors;
  const learning = comparison?.learning ?? (telemetry as ProactiveRunTelemetry | null)?.lifecycle?.learning ?? (telemetry as RunTelemetry | null)?.outcome?.learning;
  const before = proof?.run_1?.take_rate ?? comparison?.before?.take_rate ?? response?.takeRate;
  const after = proof?.run_2?.expected_take_rate ?? comparison?.after?.expected_take_rate;
  const weakPrior = proof?.run_2?.weak_prior_avoided ?? priors?.weakest_prior;
  const bestPrior = proof?.run_2?.best_prior_used ?? priors?.best_prior;
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <div className="text-[10px] font-black uppercase tracking-widest text-violet-300">Learning loop</div>
          <div className="mt-1 text-xs font-black text-slate-100">Memory changes the next plan</div>
        </div>
        <div className={telemetry ? "rounded bg-violet-950 px-2 py-1 text-[9px] font-black uppercase text-violet-300" : "rounded bg-slate-950 px-2 py-1 text-[9px] font-black uppercase text-slate-500"}>
          {proof ? "2-run proof" : telemetry ? "updated" : "waiting"}
        </div>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <div className="rounded border border-slate-800 bg-slate-950 p-2">
          <div className="text-[9px] font-black uppercase tracking-widest text-slate-500">Run 1 observed</div>
          <div className="mt-1 text-sm font-black text-amber-300">{before ? ratePct(before) : "--"} take</div>
        </div>
        <div className="rounded border border-slate-800 bg-slate-950 p-2">
          <div className="text-[9px] font-black uppercase tracking-widest text-slate-500">Run 2 expected</div>
          <div className="mt-1 text-sm font-black text-emerald-300">{after ? ratePct(after) : "--"} take</div>
        </div>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2">
        <div className="rounded border border-slate-800 bg-slate-950 p-2">
          <div className="text-[9px] font-black uppercase tracking-widest text-slate-500">BigQuery uses</div>
          <div className="mt-1 line-clamp-1 text-[11px] font-black text-cyan-300">{bestPrior?.cohort ?? "best prior pending"}</div>
        </div>
        <div className="rounded border border-slate-800 bg-slate-950 p-2">
          <div className="text-[9px] font-black uppercase tracking-widest text-slate-500">Avoids</div>
          <div className="mt-1 line-clamp-1 text-[11px] font-black text-red-300">{weakPrior?.cohort ?? "weak prior pending"}</div>
        </div>
      </div>
      <div className="mt-2 line-clamp-3 rounded border border-slate-800 bg-slate-950 p-2 text-[11px] leading-relaxed text-slate-400">
        {proof?.run_2?.change_reason ?? learning?.mongodb_rule ?? learning?.take_rate_signal ?? "MongoDB stores the episode and BigQuery/GCP eval turns the outcome into a future planning prior."}
      </div>
      <div className="mt-2 rounded border border-slate-800 bg-slate-950 p-2 text-[10px] leading-relaxed text-slate-500">
        Memory: {savedLessonLabel(proof?.memory_write?.outcome_id ?? learning?.outcome_id, telemetry ? "stored" : "waiting")} / Analytics: {analyticsProofLabel(proof?.memory_write?.bigquery_query ?? priors?.query_name, telemetry ? "ready" : "waiting")}
      </div>
    </div>
  );
}

function directorStepClass(status: "complete" | "active" | "watch") {
  if (status === "complete") return "border-emerald-400/60 bg-emerald-950/40 text-emerald-100";
  if (status === "active") return "border-cyan-300/70 bg-cyan-950/50 text-cyan-100";
  return "border-slate-800 bg-slate-950 text-slate-400";
}

function runStageFromProgress(runProgress: string | null, fallbackStep: number) {
  const match = runProgress?.match(/^(\d)\/(?:6|7)/);
  if (match) return Math.max(0, Math.min(5, Number(match[1]) - 1));
  return Math.max(0, Math.min(5, fallbackStep));
}

function DemoDirectorRail({
  telemetry,
  isRunningProactive,
  isRunningLearnedPlan,
  visualStepIndex,
}: {
  telemetry: ProactiveRunTelemetry | RunTelemetry | null;
  isRunningProactive: boolean;
  isRunningLearnedPlan: boolean;
  visualStepIndex: number;
}) {
  const proactiveTelemetry = telemetry as ProactiveRunTelemetry | null;
  const dispatches = telemetry?.delivery?.dispatches ?? [];
  const guestDispatch = dispatches.find((item) => item.channel === "guest_app");
  const workerDispatch = dispatches.find((item) => item.channel === "worker_device");
  const equipmentDispatch = dispatches.find((item) => item.channel === "equipment_controller");
  const response = telemetry?.delivery?.response;
  const stages = proactiveTelemetry?.lifecycle?.stages ?? [];
  const learnedApplied = proactiveTelemetry?.learned_run?.status === "applied" || proactiveTelemetry?.learning_proof?.mode === "learned_second_action";
  const proof = proactiveTelemetry?.learning_proof ?? proactiveTelemetry?.lifecycle?.learning_proof;
  const priors = proactiveTelemetry?.lifecycle?.bigquery_priors ?? proactiveTelemetry?.analytics?.priors;
  const stepRows = [
    {
      label: "Detect",
      detail: proactiveTelemetry?.lifecycle?.early_detection?.top_signal?.trigger ?? "early signal watch",
      done: Boolean(proactiveTelemetry?.proactive?.insights?.length || stages.find((item) => item.id === "detect")?.status === "complete"),
    },
    {
      label: "Agents",
      detail: `${proactiveTelemetry?.agent_findings?.length ?? 0} findings`,
      done: Boolean(proactiveTelemetry?.agent_findings?.length),
    },
    {
      label: "Policy",
      detail: proactiveTelemetry?.orchestration?.gates?.[0]?.status ?? proactiveTelemetry?.lifecycle?.orchestration?.gates?.[0]?.status ?? "gate pending",
      done: Boolean(proactiveTelemetry?.orchestration?.gates?.length || proactiveTelemetry?.lifecycle?.orchestration?.gates?.length),
    },
    {
      label: "Dispatch",
      detail: guestDispatch?.id ?? "payload pending",
      done: Boolean(dispatches.length),
    },
    {
      label: "React",
      detail: response ? `${ratePct(response.takeRate)} take / ${ratePct(response.reactiveFollowThroughRate)} follow` : "waiting",
      done: Boolean(response?.sampleSize),
    },
    {
      label: "Memory",
      detail: savedLessonLabel(proof?.memory_write?.outcome_id ?? proactiveTelemetry?.outcome_id, telemetry ? "stored" : "waiting"),
      done: Boolean(proof?.memory_write?.outcome_id || proactiveTelemetry?.outcome_id),
    },
    {
      label: "BQ Prior",
      detail: analyticsProofLabel(priors?.query_name, "response priors"),
      done: Boolean(priors?.best_prior || proactiveTelemetry?.analytics?.priors),
    },
    {
      label: "Run 2",
      detail: learnedApplied ? "applied" : proof?.run_2?.expected_take_rate ? `${ratePct(proof.run_2.expected_take_rate)} expected` : "ready after run",
      done: learnedApplied,
    },
  ];

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Demo director</div>
          <div className="mt-1 text-sm font-black text-slate-100">Watch the loop move</div>
        </div>
        <span className="rounded bg-slate-950 px-2 py-1 text-[9px] font-black uppercase text-slate-400">
          {isRunningLearnedPlan ? "run 2" : isRunningProactive ? "running" : learnedApplied ? "learned" : "ready"}
        </span>
      </div>
      <div className="mt-3 grid gap-1.5">
        {stepRows.map((step, index) => {
          const status: "complete" | "active" | "watch" = step.done
            ? "complete"
            : isRunningLearnedPlan && step.label === "Run 2"
              ? "active"
              : isRunningProactive && index === Math.min(stepRows.length - 1, visualStepIndex)
                ? "active"
                : "watch";
          return (
            <div key={step.label} className={`grid grid-cols-[1.3rem_4.5rem_1fr] items-center gap-2 rounded border px-2 py-1.5 ${directorStepClass(status)}`}>
              <div className="flex h-5 w-5 items-center justify-center rounded-full bg-slate-950 text-[10px] font-black">{index + 1}</div>
              <div className="text-[10px] font-black uppercase tracking-widest">{step.label}</div>
              <div className="truncate text-[10px] font-bold opacity-85">{step.detail}</div>
            </div>
          );
        })}
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2 text-[10px] font-black">
        <div className="rounded bg-slate-950 p-2">
          <div className="text-slate-500">Guest</div>
          <div className="mt-1 truncate text-slate-200">{guestDispatch?.id ?? "pending"}</div>
        </div>
        <div className="rounded bg-slate-950 p-2">
          <div className="text-slate-500">Worker</div>
          <div className="mt-1 truncate text-slate-200">{workerDispatch?.status ?? "pending"}</div>
        </div>
        <div className="rounded bg-slate-950 p-2">
          <div className="text-slate-500">Control</div>
          <div className="mt-1 truncate text-slate-200">{equipmentDispatch?.status ?? "pending"}</div>
        </div>
      </div>
    </div>
  );
}

export function LiveParkCommandStage({
  flow,
  scenario,
  scenarios,
  selectedScenarioKey,
  isConnected,
  isRunning,
  isInjecting,
  isResetting,
  runTelemetry,
  parkState,
  proactiveInsights,
  proactiveRunTelemetry,
  isRunningProactive,
  isRunningLearnedPlan,
  isRunningOperatorCommand,
  integrationStatus,
  agentRoleSkills,
  operatorCommand,
  operatorCommandResult,
  signalText,
  signalTriage,
  isTriagingSignal,
  isFusingSignals,
  visualStepIndex,
  onSignalTextChange,
  onScenarioChange,
  onInjectFailure,
  onReset,
  onTriageSignal,
  onRunSignalFusion,
  onRunHealthSignal,
  onRunProactive,
  onOperatorCommandChange,
  onRunOperatorCommand,
  onReceiverAck,
  runProgress,
  runTraceId,
  runTraceEvents,
  agentMapGrounding,
  agentImpactReplay,
}: {
  flow: GuestFlow;
  scenario: DemoScenario;
  scenarios: Record<ScenarioKey, DemoScenario>;
  selectedScenarioKey: ScenarioKey;
  isConnected: boolean;
  isRunning: boolean;
  isInjecting: boolean;
  isResetting: boolean;
  runTelemetry: RunTelemetry | null;
  parkState: ParkState;
  proactiveInsights: ProactiveInsights | null;
  proactiveRunTelemetry: ProactiveRunTelemetry | null;
  isRunningProactive: boolean;
  isRunningLearnedPlan: boolean;
  isRunningOperatorCommand: boolean;
  integrationStatus: IntegrationStatus | null;
  agentRoleSkills: AgentRoleSkillsRegistry | null;
  operatorCommand: string;
  operatorCommandResult: OperatorCommandResponse | null;
  signalText: string;
  signalTriage: SignalTriageResult | null;
  isTriagingSignal: boolean;
  isFusingSignals: boolean;
  visualStepIndex: number;
  onSignalTextChange: (value: string) => void;
  onScenarioChange: (key: ScenarioKey) => void;
  onInjectFailure: () => void;
  onReset: () => void;
  onTriageSignal: () => void;
  onRunSignalFusion: () => void;
  onRunHealthSignal: () => void;
  onRunProactive: () => void;
  onOperatorCommandChange: (value: string) => void;
  onRunOperatorCommand: (message?: string) => void;
  onReceiverAck?: (dispatch: DeliveryDispatch | undefined, actor: string, choice: string) => void;
  runProgress: string | null;
  runTraceId: string | null;
  runTraceEvents?: StreamTraceEvent[];
  agentMapGrounding?: AgentMapGrounding | null;
  agentImpactReplay?: AgentImpactReplay | null;
}) {
  const telemetry = proactiveRunTelemetry ?? runTelemetry;
  const hasBackendTrace = Boolean(telemetry?.trace_contract);
  const backendStatusLive = isConnected || hasBackendTrace;
  const messySignal = signalTriage?.signal;
  const dispatches = signalTriage?.delivery?.dispatches?.length ? signalTriage.delivery.dispatches : telemetry?.delivery?.dispatches ?? [];
  const topSignal = proactiveRunTelemetry?.lifecycle?.early_detection?.top_signal ?? proactiveInsights?.insights?.[0];
  const comparison = proactiveRunTelemetry?.lifecycle?.intelligence_comparison ?? proactiveRunTelemetry?.intelligence_comparison;
  const analytics = telemetry?.analytics;
  const rowCounts = analytics?.inserted ?? analytics?.row_counts ?? {};
  const response = signalTriage?.delivery?.response ?? telemetry?.delivery?.response;
  const operatorConstraints = operatorCommandResult?.operator_constraints ?? operatorCommandResult?.run_telemetry?.operator_constraints ?? operatorCommandResult?.run_telemetry?.optimization?.operator_constraints;
  const unifiedReceipt = buildUnifiedReceipt({ operatorCommandResult, telemetry, signalTriage, registry: agentRoleSkills, operatorCommand });
  const roleAgentArtifact = operatorCommandResult?.role_agent_proposals ?? operatorCommandResult?.run_telemetry?.role_agent_proposals ?? telemetry?.role_agent_proposals;
  const operatorConstraintChips = [
    ...(operatorConstraints?.avoid_zones?.slice(0, 2).map((item) => `Avoid ${humanizeId(item.name ?? item.id)}`) ?? []),
    ...(operatorConstraints?.preferred_destinations?.slice(0, 2).map((item) => `Route to ${humanizeId(item.name ?? item.id)}`) ?? []),
    ...(operatorConstraints?.required_staff_moves?.slice(0, 2).map((item) => `${humanizeId(item.role ?? "staff")} to ${humanizeId(item.to ?? "zone")}`) ?? []),
    ...(operatorConstraints?.equipment_controls?.slice(0, 1).map((item) => `${humanizeId(item.equipmentType ?? "control")} ready`) ?? []),
  ].slice(0, 5);
  const receiverChannels = [
    ["guest_app", "Guest", "mobile"],
    ["worker_device", "Worker", "staff"],
    ["equipment_controller", "HVAC", "control"],
  ] as const;
  const issues = buildLiveIssues(flow, parkState, messySignal);
  const runtimeLeadIssue: LiveIssue | undefined = operatorConstraints?.intent_summary
    ? {
        id: "operator_request",
        title: operatorCommandResult?.operator_response?.headline ?? runTelemetry?.planner?.selected_action?.label ?? "Custom operator request",
        location: operatorConstraints.safety_escalations?.[0]?.target ?? operatorConstraints.preferred_destinations?.[0]?.name ?? operatorConstraints.avoid_zones?.[0]?.name ?? "Live park",
        detail: operatorConstraints.intent_summary,
        metric: operatorConstraints.inferred_incident_type ?? operatorCommandResult?.route?.urgency ?? "custom",
        tone: operatorConstraints.requires_human_review ? "risk" : operatorCommandResult?.route?.urgency === "critical" ? "risk" : "watch",
      }
    : operatorCommandResult?.operator_response?.summary
      ? {
          id: "operator_response",
          title: operatorCommandResult.operator_response.headline ?? "Custom operator response",
          location: "Live park",
          detail: operatorCommandResult.operator_response.summary,
          metric: operatorCommandResult.route?.urgency ?? "custom",
          tone: operatorCommandResult.route?.requires_human_review ? "risk" : "watch",
      }
      : undefined;
  const hasRuntimeIssue = Boolean(runtimeLeadIssue || operatorCommandResult || runTelemetry || proactiveRunTelemetry || signalTriage);
  const proactiveWatchIssue: LiveIssue | undefined = topSignal
    ? {
        id: "proactive_watch",
        title: "Agent detected an early park risk",
        location: proactiveRunTelemetry?.lifecycle?.early_detection?.busiest_zone ?? proactiveInsights?.summary?.busiest_zone ?? "Live park",
        detail: topSignal.trigger ?? topSignal.recommendation ?? "ParkPulse is watching a weak signal before it becomes an operator-reported incident.",
        metric: topSignal.deadline_minutes ? `${topSignal.deadline_minutes}m` : topSignal.urgency ?? "watch",
        tone: topSignal.urgency === "risk" ? "risk" : "watch",
      }
    : undefined;
  const leadIssue = messySignal ? issues[0] : runtimeLeadIssue ?? proactiveWatchIssue ?? (hasRuntimeIssue ? issues[0] : undefined) ?? {
    id: "waiting_for_request",
    title: "Ask ParkPulse to operate the park",
    location: "Live park",
    detail: "Type any incident, demand shift, guest-care need, or equipment instruction and Gemini will produce a custom action path.",
    metric: "ready",
    tone: "ok",
  };
  const timelineIssues = messySignal || (hasRuntimeIssue && !proactiveRunTelemetry)
    ? issues
    : [proactiveWatchIssue, ...issues.filter((issue) => ["food", "care", "readiness"].includes(issue.id))].filter(Boolean) as LiveIssue[];
  const guardrailCounts = signalTriage?.governance?.summary;
  const signalLayout = messySignal?.map_overlay?.zoneId ? ZONE_LAYOUT[messySignal.map_overlay.zoneId] : undefined;
  const expectedResponse = signalTriage?.learning?.priors?.expected_response;
  const isStageBusy = isRunning || isRunningProactive || isRunningLearnedPlan || isRunningOperatorCommand || isInjecting || isResetting;
  const aiPhase = aiPhaseForMap(isRunning || isRunningOperatorCommand, isRunningProactive || isRunningLearnedPlan, Boolean(proactiveRunTelemetry || runTelemetry || signalTriage));
  const proof = scenarioProof(scenario, proactiveRunTelemetry, runTelemetry);
  const aiSteps = buildAiDemoSteps({ scenario, phase: aiPhase, activeStep: visualStepIndex, telemetry: proactiveRunTelemetry, runTelemetry });
  const learningProof = proactiveRunTelemetry?.learning_proof ?? proactiveRunTelemetry?.lifecycle?.learning_proof;
  const storyMode = aiPhase === "running" ? "AI dispatch" : aiPhase === "complete" ? "After" : "Incident";
  const storySteps = ["Incident", "AI dispatch", "After"] as const;
  const samplePrompts: Record<ScenarioKey, string> = {
    ride_down: "A major ride is down and guests are clustering near the exit. Stop new queue intake, message guests honestly, and send staff without overloading indoor rides.",
    staff_shortage: "Several workers called out. Protect staff breaks, keep certified coverage safe, and rebalance food and ride support.",
    food_spike: "Food Court A is down. Stop sending guests there, redirect mobile orders to other food locations, notify workers, and adjust kitchen equipment.",
    storm_response: "Lightning risk is rising. Close outdoor queue intake early, route guests to shelter, protect HVAC comfort, and keep emergency paths clear.",
  };
  const demoPrompts: Array<{ id: string; label: string; scenarioKey?: ScenarioKey; prompt: string; tone: string }> = [
    { id: "ride", label: "Inject ride fault", scenarioKey: "ride_down", prompt: samplePrompts.ride_down, tone: "border-rose-400/40 bg-rose-950/30 text-rose-100 hover:bg-rose-900/40" },
    { id: "food", label: "Inject food disruption", scenarioKey: "food_spike", prompt: samplePrompts.food_spike, tone: "border-amber-300/40 bg-amber-950/30 text-amber-100 hover:bg-amber-900/40" },
    { id: "staff", label: "Inject labor gap", scenarioKey: "staff_shortage", prompt: samplePrompts.staff_shortage, tone: "border-emerald-300/40 bg-emerald-950/30 text-emerald-100 hover:bg-emerald-900/40" },
    { id: "medical", label: "Inject care signal", prompt: "Someone fainted near Food Court A. Send medical support, keep guest details private, keep the access lane clear, and avoid alarming public messages.", tone: "border-cyan-300/40 bg-cyan-950/30 text-cyan-100 hover:bg-cyan-900/40" },
    { id: "crowd", label: "Inject crowd pressure", prompt: "There is panic crowd congestion near Covered Plaza. Open calm routes, move crowd-control staff, keep service access clear, and use non-alarming guest messaging.", tone: "border-violet-300/40 bg-violet-950/30 text-violet-100 hover:bg-violet-900/40" },
    { id: "hvac", label: "Inject comfort load", scenarioKey: "storm_response", prompt: "Indoor areas are too hot and guests are crowding shelter zones. Adjust HVAC comfort, shed only noncritical load, and send facilities to verify.", tone: "border-sky-300/40 bg-sky-950/30 text-sky-100 hover:bg-sky-900/40" },
  ];
  const messyNoteSources: Array<{ id: string; label: string; source: string; prompt: string; tone: string }> = [
    {
      id: "guest_app",
      label: "Guest app",
      source: "guest_app_complaint",
      prompt: "Guest app note: Someone says a person passed out near Food Court A pickup. The area is getting crowded and they need medical help.",
      tone: "border-cyan-300/35 bg-cyan-950/25 text-cyan-100 hover:bg-cyan-900/35",
    },
    {
      id: "worker_app",
      label: "Worker app",
      source: "worker_quick_tap",
      prompt: "Worker app note: Smell of smoke near Covered Plaza fog controller. Guests are stopping and service lane may get blocked.",
      tone: "border-amber-300/35 bg-amber-950/25 text-amber-100 hover:bg-amber-900/35",
    },
    {
      id: "support_station",
      label: "Support station",
      source: "support_station_agent",
      prompt: "Support station chat: Visitor needs wheelchair assistance near the maze exit. Kids are crying and the family needs a calm accessible route.",
      tone: "border-emerald-300/35 bg-emerald-950/25 text-emerald-100 hover:bg-emerald-900/35",
    },
  ];
  const loadSamplePrompt = (key: ScenarioKey) => {
    onScenarioChange(key);
    onOperatorCommandChange(samplePrompts[key]);
  };
  const runDemoPrompt = (prompt: string, key?: ScenarioKey) => {
    if (key) onScenarioChange(key);
    onOperatorCommandChange(prompt);
    onRunOperatorCommand(prompt);
  };
  const activeReasoningStep = runStageFromProgress(runProgress, visualStepIndex);
  const traceContract = proactiveRunTelemetry?.trace_contract ?? runTelemetry?.trace_contract;
  const policyBookRule = proof.policy ?? scenario.policies[0]?.rule;
  const policyGateSummary = guardrailCounts
    ? `Allowed ${guardrailCounts.allowed ?? "--"} / review ${guardrailCounts.review ?? "--"} / blocked ${guardrailCounts.blocked ?? "--"}.`
    : traceContract?.policy_gate
      ? `${traceContract.policy_gate.gate_status ?? "checked"}: ${(traceContract.policy_gate.findings ?? []).slice(0, 2).join(" / ")}`
    : "Safety gate blocks reopening; staff gate limits authority; customer-care gate requires targeted recovery.";
  const dispatchSummary = dispatches.length
    ? `${dispatches.length} receiver payloads: guest app, worker task, and equipment control.`
    : "Receiver payloads are being prepared for guest app, worker task, and equipment control.";
  const responseSummary = response
    ? `${ratePct(response.takeRate)} take / ${ratePct(response.reactiveFollowThroughRate)} follow-through / ${response.sampleSize ?? "--"} samples.`
    : expectedResponse?.median_ack_seconds
      ? `Awaiting receiver reaction; prior median ack is ${expectedResponse.median_ack_seconds}s.`
      : "Awaiting receiver acknowledgement, take rate, and state movement.";
  const memorySummary =
    learningProof?.memory_write?.outcome_id || proactiveRunTelemetry?.outcome_id
      ? "Lesson saved for the next plan."
      : rowCounts.outcome_events
        ? `${rowCounts.outcome_events} learning update${rowCounts.outcome_events === 1 ? "" : "s"} saved.`
        : "Waiting for receiver results before saving a lesson.";
  const reasoningPhases = [
    {
      label: "Predict",
      lane: "Evidence",
      body: topSignal?.trigger ?? proof.signal,
      constraint: "Uses aggregate wait, density, ride, and prior-response signals before selecting an action.",
      output: leadIssue?.title ?? scenario.title,
    },
    {
      label: "Decide",
      lane: "Choice",
      body: proof.action,
      constraint: "Compares candidate actions against capacity, guest impact, and operational feasibility.",
      output: comparison?.after?.strategy ?? comparison?.before?.strategy ?? "Candidate action selected for policy review.",
    },
    {
      label: "Govern",
      lane: "Policy book",
      body: policyBookRule,
      constraint: policyGateSummary,
      output: proof.policy,
    },
    {
      label: "Emit",
      lane: "Action bus",
      body: dispatchSummary,
      constraint: "Each receiver gets a bounded command, not a free-form instruction.",
      output: dispatches[0]?.status ?? "payloads staged",
    },
    {
      label: "Observe",
      lane: "Receivers",
      body: responseSummary,
      constraint: "Result waits for receiver acknowledgement and state movement before claiming success.",
      output: proof.result,
    },
    {
      label: "Learn",
      lane: "Memory",
      body: memorySummary,
      constraint: "Writes outcome memory and eval telemetry so the next decision is informed by measured response.",
      output: learningProof?.run_2?.change_reason ?? "Prior ready for the learned follow-up run.",
    },
  ] as const;
  const activeReasoning = reasoningPhases[activeReasoningStep];
  const traceRunId =
    traceContract?.run_id ??
    proactiveRunTelemetry?.decision_id ??
    runTelemetry?.decision_id ??
    proactiveRunTelemetry?.outcome_id ??
    runTelemetry?.outcome_id ??
    runTraceId ??
    "pending";
  const runLedger = runTraceEvents?.length
    ? runTraceEvents
    : runProgress
      ? [{ phase: "active", label: activeReasoning.label, step: activeReasoningStep, message: runProgress }]
      : [];
  const proactiveRuntime = proactiveRunTelemetry?.runtime_proof;
  const proactiveRuntimeLabel =
    proactiveRuntime?.mode === "full_runtime"
      ? "Live AI"
      : proactiveRuntime?.mode === "bounded_fallback"
        ? "Backup plan"
        : isRunningProactive
          ? "Thinking"
          : "--";
  const runtimeGateForStage =
    compactStatus(
      runTelemetry?.governance?.gate_status ??
        runTelemetry?.eval?.scorecard?.policy_gate_status ??
        proactiveRunTelemetry?.eval?.status ??
        traceContract?.policy_gate?.gate_status ??
        "checked",
    );
  const operatorThinkingLedger = (runTraceEvents ?? [])
    .filter((event) =>
      ["role", "tool", "operator", "intent", "memory", "priors", "preview", "policy", "gemini", "dispatch", "operations", "event_plan", "signal_triage", "command"].includes(
        event.phase ?? "",
      ),
    )
    .slice(-7);
  const streamedEvidence = (runTraceEvents ?? [])
    .filter((event) => event.phase && event.phase !== "started")
    .map((event) => ({
      step: event.phase === "ack" ? "receiver_ack" : `${event.phase}_artifact`,
      phase: event.phase,
      evidence:
        event.message ??
        (event.artifact ? Object.entries(event.artifact).slice(0, 2).map(([key, value]) => `${key}: ${String(value)}`).join(" / ") : "Backend phase artifact received."),
      artifact_id:
        typeof event.artifact?.dispatch_id === "string"
          ? event.artifact.dispatch_id
          : typeof event.artifact?.decision_id === "string"
            ? event.artifact.decision_id
            : event.phase,
      score: typeof event.artifact?.eval_score === "number" ? event.artifact.eval_score : undefined,
      gate_status: typeof event.artifact?.gate_status === "string" ? event.artifact.gate_status : undefined,
      dispatch_count: typeof event.artifact?.dispatch_count === "number" ? event.artifact.dispatch_count : undefined,
    }));
  const evidenceChain = traceContract?.trace_table?.length ? traceContract.trace_table : streamedEvidence;
  const [selectedMapItem, setSelectedMapItem] = useState<MapSelection | null>(null);
  const [activeRailTab, setActiveRailTab] = useState<"command" | "selected" | "actions" | "proof">("command");
  const [mapLayer, setMapLayer] = useState<MapLayer>("attractions");
  const [showMapLabels, setShowMapLabels] = useState(false);
  const [showMapDetails, setShowMapDetails] = useState(false);
  useEffect(() => {
    if (!agentMapGrounding) return;
    setMapLayer("attractions");
    setShowMapLabels(false);
    setShowMapDetails(false);
  }, [agentMapGrounding]);
  const mapFocusLabels = agentMapGrounding
    ? [
        ...(agentMapGrounding.highlight_zone_ids ?? []).map((id) => `Zone: ${humanizeId(id)}`),
        ...(agentMapGrounding.landmark_ids ?? []).map((id) => `Place: ${humanizeId(id)}`),
        ...(agentMapGrounding.queue_ids ?? []).map((id) => `Queue: ${humanizeId(id)}`),
      ].slice(0, 5)
    : [];
  const receiverTargetLabels = agentMapGrounding?.receiver_targets?.length
    ? agentMapGrounding.receiver_targets
        .map((target) => `${humanizeId(target.channel ?? "receiver")} -> ${humanizeId(target.target ?? "target")}`)
        .slice(0, 3)
    : [];
  const mapTurnLabel = agentImpactReplay ? "Applied to map" : agentMapGrounding ? "Grounded only" : "No agent turn";
  const mapTurnDetail = agentImpactReplay
    ? "The latest copilot turn dispatched bounded actions and attached a before/baseline/after replay."
    : agentMapGrounding
      ? "The latest copilot turn highlighted relevant map objects, but did not mutate state."
      : "Ask the agent to apply an action to see map grounding and replay.";
  const audienceMapState = agentImpactReplay
    ? "Action applied"
    : agentMapGrounding
      ? "Map grounded"
      : isRunningOperatorCommand
        ? "Agent reading"
        : "Before run";
  const audienceMapSummary = agentImpactReplay
    ? "The green and cyan marks are the chosen action path and receiver handoff. They are the result of the run."
    : agentMapGrounding
      ? "The cyan marks are the places the agent used as evidence for this decision. They are not new incidents."
      : isRunningOperatorCommand
        ? "The agent is reading live park state, policy, map constraints, and receiver options."
        : "This is the live park before the hero story runs. Red and orange areas are current pressure.";
  const handleMapSelection = (selection: MapSelection) => {
    setSelectedMapItem(selection);
    setActiveRailTab("selected");
  };
  const handleSelectedAction = (action: string) => {
    if (!selectedMapItem) return;
    if (selectedMapItem.kind === "support-station") {
      setActiveRailTab("selected");
      return;
    }
    onOperatorCommandChange(`${action} at ${selectedMapItem.title}. ${selectedMapItem.prompt}`);
    setActiveRailTab("command");
  };
  const runProactiveFromRail = () => {
    setSelectedMapItem(null);
    setMapLayer("attractions");
    setShowMapDetails(false);
    onRunProactive();
  };
  const railTabs = [
    { key: "command", label: "Command" },
    { key: "selected", label: "Selected" },
    { key: "actions", label: "Actions" },
    { key: "proof", label: "Proof" },
  ] as const;

  return (
    <section id="live-map-stage" className="overflow-hidden rounded-lg border border-slate-800 bg-slate-950 shadow-2xl shadow-slate-950/40">
      <div className="hidden">
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(32rem,42rem)] xl:items-start">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded bg-cyan-300 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-950">Live park command</span>
              <span className={`rounded px-2 py-1 text-[10px] font-black uppercase ${backendStatusLive ? "bg-emerald-300 text-slate-950" : "bg-amber-300 text-slate-950"}`}>
                {backendStatusLive ? "backend live" : "local demo"}
              </span>
              <span className="rounded border border-slate-700 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-400">
                {formatTime(parkState.simTime.hour, parkState.simTime.minute)} / {parkState.weather.condition}
              </span>
            </div>
            <h1 className="mt-3 max-w-4xl text-2xl font-black leading-tight text-slate-100 sm:text-3xl">
              {leadIssue.title}
            </h1>
            <p className="mt-2 max-w-5xl text-sm leading-relaxed text-slate-400">
              {leadIssue.detail}
            </p>
            <div className="mt-3 grid max-w-xl grid-cols-3 gap-2 text-center">
              {[
                ["Detect", messySignal ? "triaged" : topSignal ? "live" : "watch"],
                ["Act", dispatches.length || "--"],
                ["Learn", rowCounts.outcome_events ?? 0],
              ].map(([label, value]) => (
                <div key={label} className="rounded border border-slate-800 bg-slate-900 px-3 py-2">
                  <div className="text-[9px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                  <div className="mt-1 text-sm font-black text-slate-100">{value}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
            <div className="grid gap-2">
              <button
                type="button"
                onClick={runProactiveFromRail}
                disabled={isStageBusy}
                className="rounded-lg bg-emerald-300 px-5 py-3 text-sm font-black text-slate-950 transition hover:bg-emerald-200 disabled:bg-slate-700 disabled:text-slate-400"
              >
                {isRunningProactive ? "Running visual loop..." : proactiveRunTelemetry ? "Replay visual loop" : "Run visual loop"}
              </button>
            </div>
            <details className="mt-2 rounded-lg border border-slate-800 bg-slate-950/60 p-2">
              <summary className="cursor-pointer text-[10px] font-black uppercase tracking-widest text-slate-400">Sample prompts and tools</summary>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {Object.values(scenarios).map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => loadSamplePrompt(item.key)}
                    disabled={isStageBusy}
                    className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-left text-xs font-black text-slate-100 transition hover:border-cyan-400 hover:text-cyan-200 disabled:opacity-50"
                  >
                    {item.title}
                  </button>
                ))}
              </div>
            </details>
            <div className="mt-2 grid grid-cols-2 gap-2">
              <button type="button" onClick={onInjectFailure} disabled={isStageBusy} className="rounded-lg border border-slate-700 px-3 py-2.5 text-xs font-black text-slate-100 transition hover:border-cyan-400 hover:text-cyan-200 disabled:opacity-50">
                {isInjecting ? "Injecting..." : "Inject failure"}
              </button>
              <button type="button" onClick={onReset} disabled={isStageBusy} className="rounded-lg border border-slate-700 px-3 py-2.5 text-xs font-black text-slate-100 transition hover:border-cyan-400 hover:text-cyan-200 disabled:opacity-50">
                {isResetting ? "Resetting..." : "Reset"}
              </button>
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              <a href="/monitor" className="rounded border border-cyan-400/50 px-3 py-2 text-xs font-black text-cyan-100 transition hover:bg-cyan-950/60">Policy monitor</a>
              <a href="#signal-test" className="rounded border border-slate-700 px-3 py-2 text-xs font-black text-slate-100 transition hover:border-cyan-400">Test signal</a>
            </div>
            {(runProgress || isStageBusy) && (
              <div className="mt-3 rounded border border-cyan-400/30 bg-cyan-950/30 p-3 text-xs leading-relaxed text-cyan-100">
                <div className="text-[9px] font-black uppercase tracking-widest text-cyan-300">Live run progress</div>
                <div className="mt-1">{runProgress ?? "Working through the live backend loop..."}</div>
              </div>
            )}
          </div>
        </div>

        <div className="mt-4 rounded-lg border border-slate-800 bg-slate-950/70 p-3 text-xs leading-relaxed text-slate-400">
          Samples are optional prompts. The main path is free text: the receiver phones and map should change only from the returned action payloads.
        </div>
      </div>

      <div className="grid min-h-[calc(100vh-2.5rem)] border-b border-slate-800 bg-slate-950 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="relative min-h-[calc(100vh-2.5rem)] overflow-hidden bg-[#8fbc72]">
          <VisualParkBoard
            flow={flow}
            scenario={scenario}
            isConnected={isConnected}
            isRunning={isRunning || isRunningOperatorCommand}
            runTelemetry={runTelemetry}
            parkState={parkState}
            proactiveRunTelemetry={proactiveRunTelemetry}
            signalTriage={signalTriage}
            operatorCommand={operatorCommand}
            operatorCommandResult={operatorCommandResult}
            isRunningProactive={isRunningProactive || isRunningLearnedPlan}
            visualStepIndex={visualStepIndex}
            selectedMapItem={selectedMapItem}
            agentMapGrounding={agentMapGrounding}
            agentImpactReplay={agentImpactReplay}
            onMapSelectionChange={handleMapSelection}
            onReceiverAck={onReceiverAck}
            compact
            showCompactPanels={false}
            showOverlayControls={false}
            mapLayer={mapLayer}
            onMapLayerChange={setMapLayer}
            showLabels={showMapLabels}
            onShowLabelsChange={setShowMapLabels}
            showDetails={showMapDetails}
            onShowDetailsChange={setShowMapDetails}
          />
          <div className="pointer-events-none absolute left-4 top-4 z-30 max-w-md rounded-lg border border-slate-900/20 bg-white/95 p-3 text-slate-950 shadow-2xl">
            <div className="flex items-center justify-between gap-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">What the map means</div>
              <div className={`rounded px-2 py-1 text-[9px] font-black uppercase ${
                agentImpactReplay ? "bg-emerald-200 text-emerald-950" : agentMapGrounding ? "bg-cyan-200 text-cyan-950" : isRunningOperatorCommand ? "bg-amber-200 text-amber-950" : "bg-slate-200 text-slate-700"
              }`}>
                {audienceMapState}
              </div>
            </div>
            <div className="mt-1 text-sm font-black leading-tight">{leadIssue?.title ?? scenario.title}</div>
            <div className="mt-1 text-xs font-bold leading-relaxed text-slate-700">{audienceMapSummary}</div>
            <div className="mt-2 grid grid-cols-3 gap-1 text-[9px] font-black uppercase tracking-wide">
              <div className="rounded bg-red-100 px-2 py-1 text-red-900">Risk</div>
              <div className="rounded bg-cyan-100 px-2 py-1 text-cyan-900">Agent focus</div>
              <div className="rounded bg-emerald-100 px-2 py-1 text-emerald-900">Action</div>
            </div>
          </div>
        </div>
        <aside className="max-h-[calc(100vh-2.5rem)] overflow-y-auto border-t border-slate-800 bg-slate-950 p-3 xl:border-l xl:border-t-0">
        <div className="rounded-lg border border-white/10 bg-slate-900/90 p-2.5 text-slate-100 shadow-xl">
          <div className="grid gap-2">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded bg-cyan-300 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-950">Park command</span>
                <span className={`rounded px-2 py-1 text-[10px] font-black uppercase ${backendStatusLive ? "bg-emerald-300 text-slate-950" : "bg-amber-300 text-slate-950"}`}>
                  {backendStatusLive ? "live feed" : "demo feed"}
                </span>
                <span className="rounded border border-slate-700 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-300">
                  {formatTime(parkState.simTime.hour, parkState.simTime.minute)}
                </span>
              </div>
              <div className="mt-1.5 grid gap-2">
                <h1 className="min-w-0 truncate text-base font-black leading-tight text-slate-100">{leadIssue?.title ?? scenario.title}</h1>
                <div className="rounded-lg border border-cyan-300/30 bg-cyan-950/25 p-2">
                  <div className="text-[8px] font-black uppercase tracking-widest text-cyan-300">Audience read</div>
                  <div className="mt-1 text-[11px] font-bold leading-relaxed text-cyan-50">
                    {agentImpactReplay
                      ? "The run selected an action, changed the map overlay, and produced receiver/proof cards."
                      : agentMapGrounding
                        ? "The run found the relevant places. The marks show evidence, not random activity."
                        : isRunningOperatorCommand
                          ? "The agent is turning the story prompt into map evidence and bounded actions."
                          : "Start here: run one hero story, watch the map marks, then read the action/proof cards."}
                  </div>
                </div>
                <div className="rounded-lg border border-slate-800 bg-slate-950/80 p-1.5">
                  <div className="mb-1 flex items-center justify-between gap-2 px-1">
                    <div className="text-[8px] font-black uppercase tracking-widest text-slate-500">Map view</div>
                    <div className="text-[8px] font-black uppercase tracking-widest text-slate-600">click park objects</div>
                  </div>
                  <div className="grid grid-cols-3 gap-1">
                    {(["attractions", "queues", "support", "signals"] as MapLayer[]).map((layer) => (
                      <button
                        key={layer}
                        type="button"
                        onClick={() => setMapLayer(layer)}
                        className={`rounded px-2 py-1.5 text-[8px] font-black uppercase tracking-widest transition ${
                          mapLayer === layer ? "bg-cyan-300 text-slate-950" : "bg-slate-900 text-slate-400 hover:bg-slate-800 hover:text-slate-100"
                        }`}
                      >
                        {layer === "attractions" ? "Park" : layer}
                      </button>
                    ))}
                    <button
                      type="button"
                      onClick={() => setShowMapLabels((value) => !value)}
                      className={`rounded px-2 py-1.5 text-[8px] font-black uppercase tracking-widest transition ${
                        showMapLabels ? "bg-emerald-300 text-slate-950" : "bg-slate-900 text-slate-400 hover:bg-slate-800 hover:text-slate-100"
                      }`}
                    >
                      Labels
                    </button>
                    <button
                      type="button"
                      onClick={() => setShowMapDetails((value) => !value)}
                      className={`rounded px-2 py-1.5 text-[8px] font-black uppercase tracking-widest transition ${
                        showMapDetails ? "bg-amber-300 text-slate-950" : "bg-slate-900 text-slate-400 hover:bg-slate-800 hover:text-slate-100"
                      }`}
                    >
                      Details
                    </button>
                  </div>
                </div>
                <div className="flex rounded border border-slate-700 bg-slate-950/70 p-0.5">
                  {storySteps.map((step) => (
                    <span
                      key={step}
                      className={`flex-1 rounded px-2 py-1 text-center text-[9px] font-black uppercase tracking-widest ${
                        storyMode === step ? "bg-cyan-300 text-slate-950" : "text-slate-500"
                      }`}
                    >
                      {step}
                    </span>
                  ))}
                </div>
                <div className="grid grid-cols-4 gap-1 rounded-lg border border-slate-800 bg-slate-950/80 p-1">
                  {railTabs.map((tab) => (
                    <button
                      key={tab.key}
                      type="button"
                      onClick={() => setActiveRailTab(tab.key)}
                      className={`rounded px-2 py-1.5 text-[9px] font-black uppercase tracking-widest transition ${
                        activeRailTab === tab.key ? "bg-cyan-300 text-slate-950" : "text-slate-500 hover:bg-slate-800 hover:text-slate-200"
                      }`}
                    >
                      {tab.label}
                    </button>
                  ))}
                </div>
                <div className={`rounded-lg border p-2 ${
                  agentImpactReplay
                    ? "border-emerald-400/30 bg-emerald-950/20"
                    : agentMapGrounding
                      ? "border-cyan-400/30 bg-cyan-950/20"
                      : "border-slate-800 bg-slate-950/80"
                }`}>
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-[8px] font-black uppercase tracking-widest text-slate-400">Turn contract</div>
                    <span className={`rounded px-1.5 py-0.5 text-[8px] font-black uppercase ${
                      agentImpactReplay ? "bg-emerald-300 text-slate-950" : agentMapGrounding ? "bg-cyan-300 text-slate-950" : "bg-slate-800 text-slate-400"
                    }`}>
                      {mapTurnLabel}
                    </span>
                  </div>
                  <div className="mt-1 text-[9px] leading-relaxed text-slate-400">{mapTurnDetail}</div>
                </div>
                {(agentMapGrounding || agentImpactReplay || isRunningOperatorCommand) && (
                  <div className="rounded-lg border border-slate-700 bg-slate-950/85 p-2">
                    <div className="text-[8px] font-black uppercase tracking-widest text-cyan-300">What happened when you clicked run</div>
                    <div className="mt-1 grid gap-1.5 text-[10px] leading-snug text-slate-300">
                      <div>
                        <span className="font-black text-slate-100">1. Read the situation: </span>
                        the agent used the current park state and your hero prompt.
                      </div>
                      <div>
                        <span className="font-black text-slate-100">2. Chose the bounded move: </span>
                        it highlighted the map objects tied to the decision, not random alerts.
                      </div>
                      <div>
                        <span className="font-black text-slate-100">3. Sent or staged receivers: </span>
                        guest app, worker task, and ops channels appear only if the backend returned them.
                      </div>
                    </div>
                    <div className="mt-2 grid gap-1">
                      {(mapFocusLabels.length ? mapFocusLabels : ["Map focus appears after a completed run."]).map((label) => (
                        <div key={label} className="rounded bg-slate-900 px-2 py-1 text-[9px] font-black uppercase tracking-wide text-cyan-100">{label}</div>
                      ))}
                      {receiverTargetLabels.map((label) => (
                        <div key={label} className="rounded bg-emerald-950/60 px-2 py-1 text-[9px] font-black uppercase tracking-wide text-emerald-100">{label}</div>
                      ))}
                    </div>
                  </div>
                )}
                {agentMapGrounding && (
                  <div className="rounded-lg border border-cyan-400/30 bg-cyan-950/20 p-2">
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-[8px] font-black uppercase tracking-widest text-cyan-300">Agent map focus</div>
                      <span className="rounded bg-cyan-300 px-1.5 py-0.5 text-[8px] font-black uppercase text-slate-950">
                        {agentMapGrounding.focus?.replaceAll("_", " ") ?? "grounded"}
                      </span>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {mapFocusLabels.map((label) => (
                        <span key={label} className="rounded bg-slate-950 px-1.5 py-0.5 text-[8px] font-black uppercase tracking-wide text-cyan-100">
                          {label}
                        </span>
                      ))}
                    </div>
                    <div className="mt-1 line-clamp-2 text-[9px] leading-relaxed text-cyan-100/70">
                      {agentMapGrounding.rationale ?? "The agent response is linked to the highlighted map objects."}
                    </div>
                  </div>
                )}
                {agentImpactReplay && (
                  <div className="rounded-lg border border-emerald-400/30 bg-emerald-950/20 p-2">
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-[8px] font-black uppercase tracking-widest text-emerald-300">Impact replay</div>
                      <span className="rounded bg-emerald-300 px-1.5 py-0.5 text-[8px] font-black uppercase text-slate-950">
                        vs baseline
                      </span>
                    </div>
                    <div className="mt-1 line-clamp-2 text-[10px] font-black leading-relaxed text-emerald-50">
                      {agentImpactReplay.comparison?.impact?.headline ?? agentImpactReplay.map_delta?.primary_metric ?? "Action measured against no-agent baseline."}
                    </div>
                    <div className="mt-2 grid grid-cols-4 gap-1">
                      {[
                        ["Score", agentImpactReplay.comparison?.score_lift],
                        ["Wait", agentImpactReplay.map_delta?.wait_minutes_avoided],
                        ["Queue", agentImpactReplay.map_delta?.queue_guests_avoided],
                        ["Dense", agentImpactReplay.map_delta?.density_points_reduced],
                      ].map(([label, value]) => (
                        <div key={String(label)} className="rounded bg-slate-950 px-1.5 py-1">
                          <div className="text-[7px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                          <div className="font-black text-emerald-100">{typeof value === "number" ? (value > 0 ? `+${value}` : value) : "--"}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {activeRailTab === "command" && <div className="grid gap-2">
              <div className="rounded-lg border border-cyan-300/35 bg-slate-950/80 p-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-[9px] font-black uppercase tracking-widest text-cyan-300">Ask the park agent</div>
                  <span className="rounded bg-slate-900 px-2 py-0.5 text-[8px] font-black uppercase text-slate-400">
                    {operatorCommandResult ? "ready" : "plain language"}
                  </span>
                </div>
                <textarea
                  value={operatorCommand}
                  onChange={(event) => onOperatorCommandChange(event.target.value)}
                  className="mt-2 h-20 w-full resize-none rounded border border-slate-700 bg-slate-950 p-2 text-[11px] leading-relaxed text-slate-100 outline-none transition placeholder:text-slate-600 focus:border-cyan-300"
                  placeholder="Ask: keep families away from scary zones, reduce food lines, protect staff breaks..."
                />
                <button
                  type="button"
                  onClick={() => onRunOperatorCommand()}
                  disabled={isStageBusy || operatorCommand.trim().length < 6}
                  className="mt-2 w-full rounded-lg bg-cyan-300 px-4 py-2.5 text-xs font-black text-slate-950 transition hover:bg-cyan-200 disabled:bg-slate-700 disabled:text-slate-400"
                >
                  {isRunningOperatorCommand ? "Agent reading request..." : "Ask and act"}
                </button>
                <details className="mt-2 rounded-lg border border-slate-800 bg-slate-950/70 p-2">
                  <summary className="cursor-pointer text-[9px] font-black uppercase tracking-widest text-slate-400">
                    Test scenarios
                  </summary>
                  <div className="mt-2 grid grid-cols-2 gap-1">
                    {demoPrompts.map((demo) => (
                      <button
                        key={demo.id}
                        type="button"
                        onClick={() => runDemoPrompt(demo.prompt, demo.scenarioKey)}
                        disabled={isStageBusy}
                        className={`rounded border px-2 py-1.5 text-left text-[9px] font-black uppercase tracking-wide transition disabled:border-slate-800 disabled:bg-slate-900 disabled:text-slate-600 ${demo.tone}`}
                      >
                        {demo.label}
                      </button>
                    ))}
                  </div>
                  <div className="mt-2 grid grid-cols-3 gap-1">
                    {messyNoteSources.map((note) => (
                      <button
                        key={note.id}
                        type="button"
                        onClick={() => runDemoPrompt(`[${note.source}] ${note.prompt}`)}
                        disabled={isStageBusy}
                        className={`rounded border px-2 py-1.5 text-left text-[9px] font-black uppercase tracking-wide transition disabled:border-slate-800 disabled:bg-slate-900 disabled:text-slate-600 ${note.tone}`}
                      >
                        {note.label}
                      </button>
                    ))}
                  </div>
                  <button
                    type="button"
                    onClick={runProactiveFromRail}
                    disabled={isStageBusy}
                    className="mt-2 w-full rounded-lg border border-emerald-300/70 bg-emerald-950/70 px-4 py-2 text-xs font-black text-emerald-100 transition hover:bg-emerald-900/80 disabled:border-slate-800 disabled:bg-slate-900 disabled:text-slate-500"
                  >
                    {isRunningProactive ? "Scanning park..." : proactiveRunTelemetry ? "Run proactive scan again" : "Run proactive scan"}
                  </button>
                </details>
                <details className="mt-2 rounded-lg border border-slate-800 bg-slate-950/70 p-2">
                  <summary className="cursor-pointer text-[9px] font-black uppercase tracking-widest text-slate-400">
                    Agent trace
                  </summary>
                  <div className="mt-2">
                    <RoleRouterPanel registry={agentRoleSkills} isActive={isStageBusy} />
                  </div>
                  <div className="mt-2">
                    <UnifiedOperatingLoop receipt={unifiedReceipt} isActive={isStageBusy || Boolean(operatorCommandResult || signalTriage || proactiveRunTelemetry)} />
                  </div>
                  <div className="mt-2">
                    <AgentBoundaryPanel artifact={roleAgentArtifact} telemetry={telemetry} isActive={isStageBusy} />
                  </div>
                  {(proactiveRunTelemetry || isRunningProactive) && !operatorCommandResult && (
                    <div className="mt-2 rounded border border-emerald-400/30 bg-emerald-950/25 p-2 text-[10px] leading-relaxed text-emerald-50">
                      <div className="flex items-center justify-between gap-2">
                        <div className="font-black text-emerald-100">
                          {proactiveRunTelemetry?.lifecycle?.headline ?? "Detect -> forecast -> proact -> observe -> learn"}
                        </div>
                        <span className="rounded bg-emerald-300 px-1.5 py-0.5 text-[8px] font-black uppercase text-slate-950">
                          {isRunningProactive ? "live" : "complete"}
                        </span>
                      </div>
                      <div className="mt-1 line-clamp-2 text-emerald-100/75">
                        {topSignal?.trigger ?? runProgress ?? "Scanning park state, weak signals, memory, and BigQuery priors before a visible failure."}
                      </div>
                      <div className="mt-2 grid grid-cols-3 gap-1 border-t border-emerald-400/20 pt-2">
                        <div>
                          <div className="text-[8px] font-black uppercase tracking-widest text-emerald-300/80">Actions</div>
                          <div className="font-black text-emerald-50">{dispatches.length || proactiveRunTelemetry?.delivery?.summary?.total || "--"}</div>
                        </div>
                        <div>
                          <div className="text-[8px] font-black uppercase tracking-widest text-emerald-300/80">Take</div>
                          <div className="font-black text-emerald-50">{ratePct(response?.takeRate)}</div>
                        </div>
                        <div>
                          <div className="text-[8px] font-black uppercase tracking-widest text-emerald-300/80">Memory</div>
                          <div className="truncate font-black text-emerald-50">{proactiveRunTelemetry?.outcome_id ? "saved" : isRunningProactive ? "watching" : "--"}</div>
                        </div>
                      </div>
                      <div className="mt-1 line-clamp-2 text-[9px] text-emerald-200/80">
                        {proactiveRuntime?.fallback_reason
                          ? `Fallback marked: ${proactiveRuntime.fallback_reason}`
                          : proactiveRunTelemetry?.lifecycle?.learning?.take_rate_signal ?? "Waiting for receiver reaction and measured take rate."}
                      </div>
                    </div>
                  )}
                </details>
                {(operatorCommandResult || isRunningOperatorCommand) && (
                  <div className="mt-2 rounded border border-slate-700 bg-slate-900/80 p-2 text-[10px] leading-relaxed text-slate-300">
                    <div className="font-black text-slate-100">
                      {operatorCommandResult?.operator_response?.headline ?? "Interpreting operator request..."}
                    </div>
                    <div className="mt-1 line-clamp-2 text-slate-400">
                      {operatorCommandResult?.operator_response?.next_step ?? operatorCommandResult?.operator_response?.summary ?? runProgress ?? "Reading current park state, prior lessons, and safety rules."}
                    </div>
                    {operatorConstraints?.intent_summary && (
                      <div className="mt-2 rounded border border-cyan-400/20 bg-cyan-950/30 px-2 py-1 text-[9px] leading-snug text-cyan-100">
                        <span className="font-black uppercase tracking-widest text-cyan-300">Request understood </span>
                        {operatorConstraints.intent_summary}
                      </div>
                    )}
                    {operatorConstraintChips.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {operatorConstraintChips.map((chip) => (
                          <span key={chip} className="rounded bg-cyan-950/80 px-1.5 py-0.5 text-[8px] font-black uppercase tracking-wide text-cyan-200">
                            {chip}
                          </span>
                        ))}
                      </div>
                    )}
                    {operatorConstraints?.rejected_option && (
                      <div className="mt-1 line-clamp-2 text-[9px] text-amber-200">
                        Rejected: {operatorConstraints.rejected_option}
                      </div>
                    )}
                    {operatorThinkingLedger.length > 0 && (
                      <div className="mt-2 border-t border-slate-700 pt-2">
                        <div className="flex items-center justify-between gap-2">
                          <div className="text-[8px] font-black uppercase tracking-widest text-cyan-300">Action progress</div>
                          <div className="rounded bg-slate-950 px-1.5 py-0.5 text-[8px] font-black uppercase text-slate-500">
                            {isRunningOperatorCommand ? "live" : "complete"}
                          </div>
                        </div>
                        <div className="mt-1.5 grid gap-1">
                          {operatorThinkingLedger.map((event, index) => {
                            const isLatest = index === operatorThinkingLedger.length - 1;
                            const elapsed = typeof event.elapsed_ms === "number" ? `${Math.round(event.elapsed_ms / 1000)}s` : "--";
                            return (
                              <div key={`${event.phase}-${index}-${event.elapsed_ms ?? 0}`} className="grid grid-cols-[0.6rem_minmax(0,1fr)_2.2rem] items-start gap-1.5">
                                <span className={`mt-1 h-2 w-2 rounded-full ${isRunningOperatorCommand && isLatest ? "animate-pulse bg-cyan-300" : "bg-emerald-300"}`} />
                                <div className="min-w-0">
                                  <div className="truncate font-black text-slate-100">{event.label ?? event.phase ?? "Agent step"}</div>
                                  <div className="line-clamp-1 text-slate-500">{event.message ?? "Working through the command."}</div>
                                </div>
                                <div className="text-right font-black text-slate-500">{elapsed}</div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}
                    {(operatorCommandResult?.run_telemetry || operatorCommandResult?.role_receipt) && (
                      <div className="mt-2 grid grid-cols-2 gap-1 border-t border-slate-700 pt-2">
                        <div>
                          <div className="text-[8px] font-black uppercase tracking-widest text-slate-500">AI</div>
                          <div className="truncate font-black text-cyan-200">
                            {plannerRuntimeLabel(operatorCommandResult.run_telemetry)}
                          </div>
                        </div>
                        <div>
                          <div className="text-[8px] font-black uppercase tracking-widest text-slate-500">Actions</div>
                          <div className="font-black text-emerald-200">
                            {operatorCommandResult.run_telemetry?.delivery?.summary?.total ?? operatorCommandResult.role_receipt?.dispatch_ids?.length ?? 0} sent
                          </div>
                        </div>
                        <div>
                          <div className="text-[8px] font-black uppercase tracking-widest text-slate-500">Safety</div>
                          <div className="font-black text-amber-200">
                            {compactStatus(operatorCommandResult.run_telemetry?.governance?.gate_status ?? operatorCommandResult.run_telemetry?.eval?.scorecard?.policy_gate_status)}
                          </div>
                        </div>
                        <div>
                          <div className="text-[8px] font-black uppercase tracking-widest text-slate-500">Lesson</div>
                          <div className="truncate font-black text-slate-200">
                            {operatorCommandResult.role_receipt?.mongo?.decision_id || operatorCommandResult.run_telemetry?.decision_id ? "saved" : "waiting"}
                          </div>
                        </div>
                        <div>
                          <div className="text-[8px] font-black uppercase tracking-widest text-slate-500">History</div>
                          <div className="truncate font-black text-slate-200">
                            {compactStatus(operatorCommandResult.role_receipt?.bigquery?.status ?? "queued")}
                          </div>
                        </div>
                        <div>
                          <div className="text-[8px] font-black uppercase tracking-widest text-slate-500">Guest take</div>
                          <div className="font-black text-emerald-200">
                            {typeof operatorCommandResult.role_receipt?.learning_update?.take_rate === "number"
                              ? `${Math.round(operatorCommandResult.role_receipt.learning_update.take_rate * 100)}%`
                              : "--"}
                          </div>
                        </div>
                      </div>
                    )}
                    {operatorCommandResult?.role_receipt?.learning_update?.next_plan_bias && (
                      <div className="mt-2 rounded border border-emerald-400/20 bg-emerald-950/30 p-2 text-[10px] text-emerald-100">
                        <span className="font-black uppercase tracking-widest text-emerald-300">Next time: </span>
                        {operatorCommandResult.role_receipt.learning_update.next_plan_bias}
                      </div>
                    )}
                    {operatorCommandResult?.gemini_refinement && (
                      <div className="mt-2 rounded border border-cyan-400/25 bg-cyan-950/25 p-2 text-[10px] text-cyan-50">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-black uppercase tracking-widest text-cyan-300">Plan review</span>
                          <span className="rounded bg-slate-950 px-1.5 py-0.5 text-[8px] font-black uppercase text-cyan-200">
                            {operatorCommandResult.gemini_refinement.status ?? "queued"}
                          </span>
                        </div>
                        <div className="mt-1 line-clamp-2 text-cyan-100/85">
                          {operatorCommandResult.gemini_refinement.operator_brief ??
                            operatorCommandResult.gemini_refinement.headline ??
                            "Gemini is checking whether the fast emitted actions need a bounded correction."}
                        </div>
                        {!!operatorCommandResult.gemini_refinement.refined_actions?.length && (
                          <div className="mt-1 line-clamp-1 text-[9px] text-cyan-200/80">
                            Refined: {operatorCommandResult.gemini_refinement.refined_actions[0]}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>}

            {activeRailTab === "selected" && (
              <SelectedPlacePanel selection={selectedMapItem} onAction={handleSelectedAction} />
            )}

            {activeRailTab === "actions" && (
              <ReceiverActionsPanel
                dispatches={dispatches}
                isRunning={isStageBusy}
                onReceiverAck={onReceiverAck}
              />
            )}
          </div>
        </div>
        {activeRailTab === "proof" && (telemetry || isStageBusy || dispatches.length > 0) && (
          <div className="mt-3 rounded-lg border border-white/10 bg-slate-900/90 p-2 text-slate-100 shadow-xl">
            <div className="grid grid-cols-4 gap-1.5 text-center">
              {[
                ["AI", proactiveRuntimeLabel, proactiveRuntime?.mode === "full_runtime" ? "bg-emerald-300 text-slate-950" : isStageBusy ? "bg-cyan-300 text-slate-950" : "bg-amber-300 text-slate-950"],
                ["Safety", runtimeGateForStage, "bg-amber-300 text-slate-950"],
                ["Messages", dispatches.length ? `${dispatches.length} sent` : isStageBusy ? "preparing" : "waiting", "bg-cyan-300 text-slate-950"],
                ["Learning", memorySummary.includes("Waiting") ? (isStageBusy ? "watching" : "--") : "saved", "bg-violet-300 text-slate-950"],
              ].map(([label, value, tone]) => (
                <div key={label} className="rounded border border-slate-700 bg-slate-950/80 p-1.5">
                  <div className="text-[8px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                  <div className={`mt-1 truncate rounded px-1.5 py-1 text-[9px] font-black uppercase ${tone}`}>{value}</div>
                </div>
              ))}
            </div>
          </div>
        )}
        {activeRailTab === "proof" && (runProgress || isStageBusy || telemetry || evidenceChain.length > 0) && (
          <div className="mt-3 rounded-lg border border-cyan-300/35 bg-slate-900/90 p-2 text-xs text-slate-100 shadow-xl">
            <div className="flex items-center justify-between gap-2">
              <div>
                <div className="text-[9px] font-black uppercase tracking-widest text-cyan-300">Action loop</div>
                <div className="mt-0.5 truncate text-sm font-black text-slate-50">{activeReasoning.label}: {activeReasoning.output}</div>
              </div>
              <div className="shrink-0 rounded bg-slate-950/80 px-2 py-1 text-[9px] font-black uppercase text-slate-400">
                {traceRunId === "pending" ? "waiting" : "proof ready"}
              </div>
            </div>
            <div className="mt-2 grid grid-cols-6 gap-1">
              {reasoningPhases.map((phase, index) => {
                const status = index < activeReasoningStep ? "past" : index === activeReasoningStep ? "active" : "next";
                return (
                  <div
                    key={phase.label}
                    className={`rounded border px-1.5 py-1 text-center text-[8px] font-black uppercase tracking-widest ${
                      status === "active"
                        ? "border-cyan-200 bg-cyan-300 text-slate-950"
                        : status === "past"
                          ? "border-slate-500 bg-slate-800 text-slate-200"
                          : "border-slate-800 bg-slate-950 text-slate-500"
                    }`}
                  >
                    {index + 1}. {phase.label}
                  </div>
                );
              })}
            </div>
            <div className="mt-2 rounded border border-slate-700/70 bg-slate-950/70 p-2">
              <div className="text-[9px] font-black uppercase tracking-widest text-slate-400">{activeReasoning.lane}</div>
              <div className="mt-1 line-clamp-2 text-[11px] font-bold leading-snug text-slate-100">{activeReasoning.body}</div>
              <div className="mt-1 line-clamp-1 text-[10px] font-black text-cyan-100">{runProgress ?? activeReasoning.constraint}</div>
            </div>
            {!!runLedger.length && (
              <div className="mt-2 rounded border border-slate-700/70 bg-slate-950/70 p-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-[9px] font-black uppercase tracking-widest text-slate-400">Latest steps</div>
                  <div className="text-[9px] font-black uppercase text-slate-500">{evidenceChain.length} checks</div>
                </div>
                <div className="mt-1 grid max-h-20 gap-1 overflow-y-auto pr-1">
                  {runLedger.slice(-3).map((event, index) => (
                    <div key={`${event.phase ?? "event"}-${event.elapsed_ms ?? index}`} className="grid grid-cols-[3.6rem_1fr] gap-2 rounded bg-slate-900/90 px-2 py-1.5">
                      <div className="text-[9px] font-black uppercase text-cyan-300">
                        {typeof event.elapsed_ms === "number" ? `${Math.round(event.elapsed_ms / 100) / 10}s` : event.label ?? event.phase ?? "step"}
                      </div>
                      <div className="min-w-0">
                        <div className="truncate text-[10px] font-black uppercase tracking-widest text-slate-200">{event.label ?? event.phase ?? "Event"}</div>
                        <div className="line-clamp-1 text-[10px] leading-snug text-slate-400">{event.message ?? "Step completed."}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
        {messySignal && signalLayout && (
          <div
            className="mt-3 rounded-lg border border-violet-200/80 bg-white/95 p-3 text-stone-950 shadow-xl"
          >
            <div className="text-[10px] font-black uppercase tracking-widest text-violet-700">After action forecast</div>
            <div className="mt-1 text-sm font-black">{messySignal.zone?.name ?? "Reported zone"} stabilizing</div>
            <div className="mt-2 grid grid-cols-2 gap-2 text-[10px] font-black">
              <div className="rounded bg-violet-50 p-2">
                <div className="text-stone-500">Prior ack</div>
                <div className="mt-1 text-stone-950">{expectedResponse?.median_ack_seconds ? `${expectedResponse.median_ack_seconds}s` : "--"}</div>
              </div>
              <div className="rounded bg-emerald-50 p-2">
                <div className="text-stone-500">Density</div>
                <div className="mt-1 text-emerald-700">{expectedResponse?.typical_density_delta_10min ?? "--"}%</div>
              </div>
            </div>
          </div>
        )}
        </aside>
      </div>

      <LiveIssueTimeline issues={timelineIssues} />

      {telemetry ? (
        <div className="grid gap-3 border-t border-slate-800 bg-slate-950 p-3 xl:grid-cols-2">
          <BeforeAfterImpactPanel
            flow={flow}
            scenario={scenario}
            telemetry={telemetry}
            response={response}
            isRunning={isRunning || isRunningProactive || isRunningLearnedPlan}
            floating={false}
          />

          <DecisionProvenancePanel
            scenario={scenario}
            telemetry={telemetry}
            dispatches={dispatches}
            signalTriage={signalTriage}
          />
        </div>
      ) : (
        <div className="border-t border-slate-800 bg-slate-950 p-3">
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Run-gated proof</div>
            <div className="mt-1 text-sm font-black text-slate-100">No receiver, policy, or outcome proof is shown until the simulation runs.</div>
          </div>
        </div>
      )}

      <details className="border-t border-slate-800 bg-slate-950 p-3">
        <summary className="cursor-pointer rounded-lg border border-slate-800 bg-slate-900 px-4 py-3 text-sm font-black text-slate-100">
          Action logic, policy, receivers, and trace proof
        </summary>
        {telemetry ? <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <AiStepTimeline steps={aiSteps} />
          <AgentTradeoffPanel scenario={scenario} telemetry={telemetry} isActive={Boolean(telemetry) || isRunning || isRunningProactive || isRunningLearnedPlan} />
          <CustomRoutingMixPanel telemetry={telemetry} dispatches={dispatches} isActive={Boolean(telemetry) || isRunning || isRunningProactive || isRunningLearnedPlan} />
          <LearningMemoryPanel telemetry={telemetry} response={response} />
          <AiReasoningReceipt proof={proof} scenario={scenario} />
          <DigitalTwinToolsPanel trace={telemetry?.digital_twin_tools} />
          <DemoDirectorRail
            telemetry={telemetry}
            isRunningProactive={isRunningProactive}
            isRunningLearnedPlan={isRunningLearnedPlan}
            visualStepIndex={visualStepIndex}
          />
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Policy guardrails</div>
            <div className="mt-3 grid gap-2">
              {scenario.policies.map((policy) => (
                <div key={policy.area} className="grid grid-cols-[5.5rem_1fr] gap-2 rounded border border-slate-800 bg-slate-950 p-2">
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{policy.area}</div>
                  <div className="line-clamp-2 text-[11px] leading-relaxed text-slate-300">{policy.rule}</div>
                </div>
              ))}
            </div>
            <div className="mt-3 grid grid-cols-3 gap-2 text-center text-[10px] font-black">
              {[
                ["Allowed", guardrailCounts?.allowed ?? "--"],
                ["Review", guardrailCounts?.review ?? "--"],
                ["Blocked", guardrailCounts?.blocked ?? "--"],
              ].map(([label, value]) => (
                <div key={label} className="rounded bg-slate-950 p-2">
                  <div className="text-slate-500">{label}</div>
                  <div className="mt-1 text-xs text-slate-100">{value}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4 md:col-span-2 xl:col-span-4">
            <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Receiver alignment</div>
            <div className="mt-3 grid gap-2 md:grid-cols-3">
              {receiverChannels.map(([channel, label, system]) => {
                const dispatch = dispatches.find((item) => item.channel === channel);
                return (
                  <div key={channel} className="rounded border border-slate-800 bg-slate-950 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <div>
                        <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                        <div className="mt-1 text-xs font-black text-slate-200">{system}</div>
                      </div>
                      <span className="rounded bg-slate-800 px-2 py-1 text-[9px] font-black uppercase text-slate-200">{receiverStatus(dispatch, isRunningProactive || isRunningLearnedPlan)}</span>
                    </div>
                    <div className="mt-2 line-clamp-1 text-[11px] text-slate-500">{dispatch ? dispatchBody(dispatch) : "Waiting for action bus payload."}</div>
                  </div>
                );
              })}
            </div>
            <div className="mt-3 text-[11px] text-slate-500">
              GCP trace/eval: {comparison?.headline ?? topSignal?.proactive_not_reactive ?? "Actions are checked against safety, operations, experience, and customer-care rules."}
            </div>
          </div>
        </div> : (
          <div className="mt-3 rounded-lg border border-slate-800 bg-slate-900 p-4 text-sm text-slate-400">
            Run the visual loop to populate action logic, policy gates, receiver alignment, and trace proof from the current simulation.
          </div>
        )}
      </details>
    </section>
  );
}
