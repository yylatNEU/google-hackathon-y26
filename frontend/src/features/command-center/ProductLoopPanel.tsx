"use client";

import { LLM_INTERPRETER_STAGES, PRIMARY_OPERATING_STAGES, PRODUCT_POSITIONING, productToneClass, type ProductLoopStage } from "@/lib/productOperatingModel";
import type { EvalScore, RoleAgentProposal, RunTelemetry } from "@/types/platform";
import type { ParkState } from "@/types/park";
import type { DispatchView, LiveAgentsSmokeReport } from "./useCommandCenter";
import { humanize } from "./style";

type ProductLoopPanelProps = {
  parkState: ParkState | null;
  runTelemetry: RunTelemetry | null;
  dispatches: DispatchView[];
  evals: EvalScore[];
  selectedAction?: RunTelemetry["planner"] extends infer Planner ? Planner extends { selected_action?: infer Action } ? Action : never : never;
  policyGate?: string;
  memoryMode: string;
  liveAgentsSmoke?: LiveAgentsSmokeReport | null;
};

function signalSummary(parkState: ParkState | null) {
  if (!parkState) return ["Waiting for live park state"];
  const chaos = parkState.chaosEngine;
  const latestChaos = chaos?.activeUnexpectedEvents?.[0];
  return [
    `Rides observed: ${parkState.guestFlow?.rides?.length ?? 0}`,
    `Zones observed: ${parkState.guestFlow?.zones?.length ?? 0}`,
    latestChaos?.kind ? `Chaos ${latestChaos.kind} ${latestChaos.intensity ?? ""}%` : `Chaos rules ${chaos?.ruleCount ?? 0}`,
  ];
}

function featureSummary(runTelemetry: RunTelemetry | null) {
  const metrics = runTelemetry?.runtime_proof?.full_runtime?.metrics;
  if (!metrics) return ["Waiting for runtime feature extraction"];
  return Object.entries(metrics)
    .slice(0, 4)
    .map(([key, value]) => `${humanize(key)} ${value}`);
}

function predictionSummary(runTelemetry: RunTelemetry | null) {
  const optimization = runTelemetry?.optimization;
  const confidence = runTelemetry?.planner?.confidence_score;
  if (!optimization && confidence === undefined) return ["Waiting for ML predictor output"];
  return [
    optimization?.mode ? `Optimization ${optimization.mode}` : "Optimization complete",
    confidence === undefined ? "Confidence pending" : `Confidence ${Math.round(confidence * 100)}%`,
    runTelemetry?.planner?.runtime ? `Planner ${runTelemetry.planner.runtime}` : "Planner runtime recorded",
  ];
}

function optimizerSummary(selectedAction: ProductLoopPanelProps["selectedAction"]) {
  if (!selectedAction) return ["Waiting for optimizer selection"];
  return [selectedAction.label ?? "Selected action", selectedAction.target ?? "Target recorded", selectedAction.expected_effect ?? "Expected effect recorded"];
}

function candidateSummary(runTelemetry: RunTelemetry | null, selectedAction: ProductLoopPanelProps["selectedAction"]) {
  if (!runTelemetry && !selectedAction) return ["Waiting for candidate actions"];
  return [selectedAction?.label ?? "Candidate selected", selectedAction?.action ?? "Action recorded", selectedAction?.owner ?? "Owner recorded"];
}

function gateSummary(gate?: string, governance?: RunTelemetry["governance"]) {
  return [humanize(gate), ...(governance?.findings?.slice(0, 2) ?? ["Waiting for policy findings"])];
}

function evalSummary(runTelemetry: RunTelemetry | null) {
  const overall = runTelemetry?.eval?.scorecard?.overall;
  if (overall === undefined) return ["Waiting for runtime eval receipt"];
  return [`Overall ${overall}`, runTelemetry?.eval?.scorecard?.status ?? "Eval complete"];
}

function outcomeSummary(runTelemetry: RunTelemetry | null, memoryMode: string) {
  return [
    runTelemetry?.outcome_id ? `Outcome ${runTelemetry.outcome_id}` : "Outcome pending until dispatch or review is acknowledged",
    `Memory ${memoryMode}`,
    "Writes trace, eval, and training rows",
  ];
}

function proposalStatusClass(status?: string) {
  const normalized = String(status ?? "").toLowerCase();
  if (normalized.includes("block")) return "border-rose-500/40 bg-rose-950/25 text-rose-100";
  if (normalized.includes("executive")) return "border-amber-400/40 bg-amber-950/25 text-amber-100";
  if (normalized.includes("compliance") || normalized.includes("await")) return "border-sky-400/40 bg-sky-950/20 text-sky-100";
  return "border-emerald-400/40 bg-emerald-950/20 text-emerald-100";
}

function proposalLabel(proposal: RoleAgentProposal) {
  return proposal.department_agent ?? proposal.role ?? proposal.agent_id ?? "Department agent";
}

function proposalStatus(proposal: RoleAgentProposal) {
  return proposal.proposal_envelope?.executor_status ?? proposal.executor_status ?? proposal.proposal_envelope?.approval_status ?? "pending";
}

function liveAgentsStatusClass(status?: string) {
  const normalized = String(status ?? "").toLowerCase();
  if (normalized === "passed") return "border-emerald-400/40 bg-emerald-950/20 text-emerald-100";
  if (normalized === "missing") return "border-amber-400/40 bg-amber-950/20 text-amber-100";
  return "border-rose-500/40 bg-rose-950/25 text-rose-100";
}

function compactValue(value: unknown) {
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string" && value.trim()) return value;
  return "--";
}

function constraintText(constraint: unknown) {
  if (typeof constraint === "string") return constraint;
  if (!constraint || typeof constraint !== "object") return "Profile constraint";
  const record = constraint as { policy?: string; rule?: string; summary?: string; constraint?: string };
  return record.summary ?? record.rule ?? record.policy ?? record.constraint ?? "Profile constraint";
}

function bestProfileCandidate(proposal: RoleAgentProposal) {
  const summary = proposal.department_reasoning?.profile_counterfactual_summary;
  const selected =
    proposal.department_reasoning?.candidate_actions?.find((candidate) => candidate.selected) ??
    proposal.department_reasoning?.candidate_actions?.[0];
  return {
    action: summary?.best_profile_adjusted_action ?? selected?.action ?? proposal.requested_tool ?? "Candidate pending",
    score: summary?.best_profile_adjusted_score ?? selected?.profile_adjusted_score ?? selected?.profile_counterfactual?.score,
    effect: selected?.profile_counterfactual?.profile_effect ?? "profile checked",
    reasons: selected?.profile_counterfactual?.reasons ?? [],
  };
}

function profileZoneNames(proposal: RoleAgentProposal) {
  return (proposal.park_profile_context?.relevant_zones ?? [])
    .slice(0, 3)
    .map((zone) => zone.name ?? zone.id)
    .filter(Boolean)
    .join(", ");
}

function profileLocationNames(proposal: RoleAgentProposal) {
  return (proposal.park_profile_context?.relevant_locations ?? [])
    .slice(0, 3)
    .map((location) => location.name ?? location.id)
    .filter(Boolean)
    .join(", ");
}

function profileConstraintSummary(proposal: RoleAgentProposal) {
  return (proposal.park_profile_context?.profile_constraints ?? []).slice(0, 2).map(constraintText).join(" | ");
}

type DepartmentConversationTurn = {
  id: string;
  speaker: string;
  department: string;
  status: string;
  opening: string;
  recommendation: string;
  evidence: string[];
  handoff?: string;
};

function departmentConversationTurns(proposals: RoleAgentProposal[], proposalArtifact: RunTelemetry["role_agent_proposals"]): DepartmentConversationTurn[] {
  const proposalTurns = proposals.slice(0, 8).map((proposal, index) => {
    const envelope = proposal.proposal_envelope;
    const reasoning = proposal.department_reasoning;
    const department = proposal.department_label ?? humanize(proposal.department ?? envelope?.department ?? "department");
    const speaker = proposal.department_agent ?? envelope?.department_agent ?? proposal.role ?? proposal.agent_id ?? "Department agent";
    const diagnosis = reasoning?.diagnosis ?? proposal.recommendation ?? envelope?.intent ?? "I have a department proposal ready for review.";
    const forecast = reasoning?.forecast ? ` Forecast: ${reasoning.forecast}` : "";
    const selectedRationale = reasoning?.selected_rationale ?? envelope?.expected_outcome ?? proposal.action_disposition?.reason;
    return {
      id: `${proposal.agent_id ?? proposal.role ?? speaker}-${proposal.requested_tool ?? envelope?.requested_tool ?? index}`,
      speaker,
      department,
      status: proposalStatus(proposal),
      opening: `${diagnosis}${forecast}`,
      recommendation: selectedRationale ?? proposal.recommendation ?? envelope?.intent ?? "Hold until compliance, executive, or executor disposition is clear.",
      evidence: [...(proposal.evidence ?? []), ...(envelope?.evidence ?? []), ...(proposal.policy_refs ?? [])].slice(0, 4),
      handoff: proposal.handoff_to ?? envelope?.executor_agent ?? proposal.action_disposition?.next_owner,
    };
  });

  const executive = proposalArtifact?.executive_tradeoff;
  if (executive?.decision || executive?.rationale) {
    proposalTurns.push({
      id: "executive-tradeoff",
      speaker: "Executive Agent",
      department: "Executive",
      status: executive.decision ?? "review",
      opening: executive.rationale ?? "I am resolving cross-department tradeoffs.",
      recommendation: [
        executive.approved_departments?.length ? `Approve ${executive.approved_departments.map(humanize).join(", ")}.` : "",
        executive.held_departments?.length ? `Hold ${executive.held_departments.map(humanize).join(", ")}.` : "",
      ]
        .filter(Boolean)
        .join(" ") || "Executive tradeoff recorded.",
      evidence: (executive.tradeoff_matrix ?? []).slice(0, 3).map((row) => `${humanize(row.department)}: ${humanize(row.verdict ?? row.decision)}`),
      handoff: "tool_executor_agent",
    });
  }

  if (proposalArtifact?.mediator_summary) {
    proposalTurns.push({
      id: "mediator-summary",
      speaker: "Decision Bridge Agent",
      department: "Mediation",
      status: "resolved",
      opening: proposalArtifact.mediator_summary,
      recommendation: "Route approved work to the executor and keep held work in review with owner and exit condition.",
      evidence: (proposalArtifact.conflicts ?? []).slice(0, 3).map((conflict) => conflict.summary ?? conflict.resolution ?? humanize(conflict.kind)),
      handoff: "operator_review",
    });
  }

  return proposalTurns;
}

function stageEvidence(stageId: string, props: ProductLoopPanelProps) {
  if (stageId === "signals") return signalSummary(props.parkState);
  if (stageId === "feature_pipeline") return featureSummary(props.runTelemetry);
  if (stageId === "predictors") return predictionSummary(props.runTelemetry);
  if (stageId === "optimizer") return optimizerSummary(props.selectedAction);
  if (stageId === "candidate_actions") return candidateSummary(props.runTelemetry, props.selectedAction);
  if (stageId === "policy_gate") return gateSummary(props.policyGate, props.runTelemetry?.governance);
  if (stageId === "eval_judges") return evalSummary(props.runTelemetry);
  if (stageId === "outcome_tracker") return outcomeSummary(props.runTelemetry, props.memoryMode);
  return [];
}

function statusForStage(stageId: string, props: ProductLoopPanelProps) {
  if (stageId === "optimizer") return props.selectedAction ? "runtime" : "waiting";
  if (stageId === "policy_gate") return humanize(props.policyGate);
  if (stageId === "outcome_tracker") return props.runTelemetry?.outcome_id ? "recorded" : "pending";
  return "ready";
}

function StageCard({
  label,
  owner,
  role,
  evidence,
  tone,
  status,
}: {
  label: string;
  owner: string;
  role: string;
  evidence: string[];
  tone: ProductLoopStage["tone"];
  status: string;
}) {
  return (
    <div className={`rounded border p-3 ${productToneClass(tone)}`}>
      <div className="flex items-center justify-between gap-2">
        <div className="text-[10px] font-black uppercase tracking-widest opacity-70">{owner}</div>
        <div className="rounded bg-slate-950/40 px-2 py-1 text-[10px] font-black uppercase opacity-80">{status}</div>
      </div>
      <div className="mt-2 text-sm font-black">{label}</div>
      <p className="mt-2 text-xs leading-relaxed opacity-85">{role}</p>
      <div className="mt-3 space-y-1">
        {evidence.slice(0, 3).map((item) => (
          <div key={item} className="truncate rounded bg-slate-950/35 px-2 py-1 text-[11px] font-bold opacity-90">
            {item}
          </div>
        ))}
      </div>
    </div>
  );
}

function CompactStageCard({
  label,
  owner,
  role,
  evidence,
  tone,
}: {
  label: string;
  owner: string;
  role: string;
  evidence: string[];
  tone: Parameters<typeof productToneClass>[0];
}) {
  return (
    <div className={`rounded border p-3 ${productToneClass(tone)}`}>
      <div className="text-[10px] font-black uppercase tracking-widest opacity-70">{owner}</div>
      <div className="mt-2 text-sm font-black">{label}</div>
      <p className="mt-2 text-xs leading-relaxed opacity-85">{role}</p>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {evidence.slice(0, 3).map((item) => (
          <span key={item} className="rounded bg-slate-950/40 px-2 py-1 text-[10px] font-black uppercase opacity-90">
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

export function ProductLoopPanel(props: ProductLoopPanelProps) {
  const requiresReview = props.policyGate?.toLowerCase().includes("review") ?? false;
  const dispatchPath = requiresReview ? "Review" : "Gate pending";
  const dispatchTarget = requiresReview ? "Human Review" : "Runtime Dispatch";
  const topDispatches = props.dispatches.slice(0, 3);
  const reviewMode = requiresReview ? "Human review required" : "Waiting for gate result";
  const proposalArtifact = props.runTelemetry?.role_agent_proposals;
  const proposalSummary = proposalArtifact?.proposal_envelope_summary;
  const topProposals = proposalArtifact?.proposals?.slice(0, 4) ?? [];
  const departmentTurns = departmentConversationTurns(proposalArtifact?.proposals ?? [], proposalArtifact);
  const smokeSummary = props.liveAgentsSmoke?.summary;
  const proactRun = props.liveAgentsSmoke?.role_runs?.find((row) => row.mode === "proact");
  const liveFeedCase = props.runTelemetry?.live_feed_case;
  const toolUseClarity = props.runTelemetry?.tool_use_clarity;
  const profileSummary = props.runTelemetry?.park_profile_summary ?? proposalArtifact?.park_profile_summary;
  const profileProposals = proposalArtifact?.proposals?.filter((proposal) => proposal.park_profile_context?.status === "attached").slice(0, 6) ?? [];
  const tradeoffRows = proposalArtifact?.tradeoff_matrix?.slice(0, 6) ?? [];
  const negotiationRounds = proposalArtifact?.negotiation_rounds?.slice(0, 4) ?? [];
  const memoryDeltas =
    proposalArtifact?.memory_decision_deltas?.slice(0, 5) ??
    proposalArtifact?.proposals
      ?.map((proposal) => proposal.memory_decision_delta)
      .filter((delta): delta is NonNullable<RoleAgentProposal["memory_decision_delta"]> => Boolean(delta))
      .slice(0, 5) ??
    [];
  const executorProof = props.runTelemetry?.tool_executor_live_test;
  const receiverProof = props.runTelemetry?.live_feed_receiver_delivery;
  const followThrough = props.runTelemetry?.hard_decision_follow_through;
  const outcomeMeasurement = props.runTelemetry?.live_feed_outcome_measurement;
  const outcomeMemory = props.runTelemetry?.live_feed_outcome_memory;
  const memoryPriors = props.runTelemetry?.live_feed_memory_priors;

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-950 p-4">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Core story</div>
          <h2 className="mt-1 text-2xl font-black text-slate-100">Live park state becomes a controlled operating decision</h2>
          <p className="mt-2 max-w-5xl text-sm leading-relaxed text-slate-400">{PRODUCT_POSITIONING}</p>
        </div>
        <div className="rounded border border-amber-400/30 bg-amber-950/20 px-3 py-2 text-xs font-black text-amber-100">
          LLM creates structured scenario, not final control
        </div>
      </div>

      <div className="mt-5 grid gap-3 lg:grid-cols-4">
        <div className="rounded border border-slate-800 bg-slate-900 p-3">
          <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Operating contract</div>
          <div className="mt-2 text-sm font-black text-slate-100">Runtime data only</div>
          <p className="mt-2 text-xs leading-relaxed text-slate-400">The product surface should reflect live feeds, operator input, retrieved memory, and runtime receipts.</p>
        </div>
        <div className="rounded border border-slate-800 bg-slate-900 p-3">
          <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Decision boundary</div>
          <div className="mt-2 text-sm font-black text-slate-100">{reviewMode}</div>
          <p className="mt-2 text-xs leading-relaxed text-slate-400">Execution is determined by policy and eval gates, not by language generation.</p>
        </div>
        <div className="rounded border border-slate-800 bg-slate-900 p-3">
          <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Memory role</div>
          <div className="mt-2 text-sm font-black text-slate-100">{props.memoryMode}</div>
          <p className="mt-2 text-xs leading-relaxed text-slate-400">Memory informs interpretation and learning; it should not appear as hardcoded scenario content.</p>
        </div>
        <div className="rounded border border-slate-800 bg-slate-900 p-3">
          <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Learning loop</div>
          <div className="mt-2 text-sm font-black text-slate-100">Outcome-backed</div>
          <p className="mt-2 text-xs leading-relaxed text-slate-400">Trace, eval, and training rows are written from actual decisions and observed outcomes.</p>
        </div>
      </div>

      {liveFeedCase && (
        <div className="mt-5 rounded-lg border border-emerald-400/30 bg-emerald-950/15 p-4">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-emerald-200">Live-feed case</div>
              <h3 className="mt-1 text-lg font-black text-slate-100">
                {humanize(liveFeedCase.lead_source ?? "live feed")} {humanize(liveFeedCase.lead_signal_type ?? "evidence")}
              </h3>
              <p className="mt-2 max-w-4xl text-xs leading-relaxed text-slate-300">
                {liveFeedCase.operator_message ?? "Current feed evidence is attached to this run."}
              </p>
            </div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {[
                ["Events", liveFeedCase.persisted_event_count],
                ["Ready", liveFeedCase.ready_feed_count],
                ["Weak", liveFeedCase.missing_or_weak_feed_count],
                ["Reviews", liveFeedCase.open_review_count],
              ].map(([label, value]) => (
                <div key={label} className="rounded border border-emerald-300/20 bg-slate-950 px-3 py-2 text-center">
                  <div className="text-[10px] font-black uppercase text-slate-500">{label}</div>
                  <div className="mt-1 text-lg font-black text-emerald-100">{value ?? "--"}</div>
                </div>
              ))}
            </div>
          </div>
          <div className="mt-4 grid gap-3 xl:grid-cols-[1.2fr_.8fr]">
            <div className="rounded border border-slate-800 bg-slate-950 p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-emerald-200">Evidence</div>
              <div className="mt-3 grid gap-2 md:grid-cols-2">
                {(liveFeedCase.evidence ?? []).slice(0, 6).map((row, index) => (
                  <div key={`${row.source ?? "feed"}-${row.event_id ?? index}`} className="rounded border border-slate-800 bg-slate-900 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-xs font-black text-slate-100">{humanize(row.source ?? "feed")}</div>
                      <div className="text-[10px] font-black uppercase text-slate-500">{row.confidence ?? "--"} conf</div>
                    </div>
                    <div className="mt-1 text-[10px] font-black uppercase text-emerald-200">{humanize(row.signal_type ?? "signal")}</div>
                    <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-slate-400">{row.summary}</p>
                  </div>
                ))}
              </div>
            </div>
            <div className="rounded border border-slate-800 bg-slate-950 p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-emerald-200">Reasoning</div>
              <div className="mt-3 space-y-2">
                {(liveFeedCase.reasoning ?? []).slice(0, 6).map((step) => (
                  <div key={step} className="rounded border border-slate-800 bg-slate-900 px-3 py-2 text-xs leading-relaxed text-slate-300">
                    {step}
                  </div>
                ))}
              </div>
            </div>
          </div>
          {toolUseClarity && (
            <div className="mt-3 rounded border border-slate-800 bg-slate-950 p-3">
              <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                <div>
                  <div className="text-[10px] font-black uppercase tracking-widest text-emerald-200">Tool use</div>
                  <div className="mt-1 text-sm font-black text-slate-100">
                    {toolUseClarity.proposal_count ?? 0} department proposals, judge {humanize(toolUseClarity.judge?.eval_status ?? toolUseClarity.judge?.policy_gate ?? "pending")}
                  </div>
                </div>
                <div className="rounded border border-slate-800 bg-slate-900 px-3 py-2 text-[10px] font-black uppercase text-slate-400">
                  Executor only
                </div>
              </div>
              <div className="mt-3 grid gap-2 xl:grid-cols-4">
                {(toolUseClarity.tools ?? []).slice(0, 4).map((tool, index) => (
                  <div key={`${tool.agent ?? "agent"}-${tool.tool ?? index}`} className="rounded border border-slate-800 bg-slate-900 p-3">
                    <div className="text-[10px] font-black uppercase text-slate-500">{humanize(tool.department ?? "department")}</div>
                    <div className="mt-1 text-sm font-black text-slate-100">{humanize(tool.tool ?? "tool")}</div>
                    <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-slate-400">{tool.intent}</p>
                    <div className="mt-2 text-[10px] font-black uppercase text-emerald-200">{humanize(tool.executor_agent ?? "tool_executor_agent")}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      <div className={`mt-5 rounded-lg border p-4 ${liveAgentsStatusClass(smokeSummary?.status)}`}>
        <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <div className="text-[10px] font-black uppercase opacity-75">Live all-agent proof</div>
            <h3 className="mt-1 text-lg font-black">Latest smoke: {humanize(smokeSummary?.status ?? props.liveAgentsSmoke?.status ?? "missing")}</h3>
            <p className="mt-2 max-w-3xl text-xs leading-relaxed opacity-85">
              Shows the last local proof for role agents, department scenarios, Eval Judge, Tool Executor, and registry boundaries.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {[
              ["Roles", smokeSummary?.activated_role_count],
              ["Departments", smokeSummary?.activated_department_count],
              ["Boundary", props.liveAgentsSmoke?.registry_boundary?.failed ?? "--"],
              ["Eval", props.liveAgentsSmoke?.real_role_eval?.average_score ?? "--"],
            ].map(([label, value]) => (
              <div key={label} className="rounded border border-slate-950/40 bg-slate-950/35 px-3 py-2 text-center">
                <div className="text-[10px] font-black uppercase opacity-65">{label}</div>
                <div className="mt-1 text-lg font-black">{value}</div>
              </div>
            ))}
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {(smokeSummary?.activated_departments ?? []).slice(0, 12).map((department) => (
            <span key={department} className="rounded bg-slate-950/40 px-2 py-1 text-[10px] font-black uppercase opacity-90">
              {humanize(department)}
            </span>
          ))}
          {proactRun?.elapsed_ms !== undefined && (
            <span className="rounded bg-slate-950/40 px-2 py-1 text-[10px] font-black uppercase opacity-90">
              Proact {Math.round(proactRun.elapsed_ms / 1000)}s
            </span>
          )}
          {props.liveAgentsSmoke?.readiness_issues?.slice(0, 1).map((issue) => (
            <span key={issue} className="rounded bg-slate-950/40 px-2 py-1 text-[10px] font-black uppercase opacity-90">
              {issue}
            </span>
          ))}
        </div>
      </div>

      <div className="mt-5 rounded-lg border border-slate-800 bg-slate-900 p-4">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <div className="text-[10px] font-black uppercase text-cyan-300">Department proposals</div>
            <h3 className="mt-1 text-lg font-black text-slate-100">Propose, check, approve, execute, trace</h3>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {[
              ["Proposed", proposalSummary?.proposed],
              ["Compliance", proposalSummary?.requires_compliance],
              ["Executive", proposalSummary?.requires_executive],
              ["Ready", proposalSummary?.ready_for_executor],
            ].map(([label, value]) => (
              <div key={label} className="rounded border border-slate-800 bg-slate-950 px-3 py-2 text-center">
                <div className="text-[10px] font-black uppercase text-slate-500">{label}</div>
                <div className="mt-1 text-lg font-black text-slate-100">{value ?? "--"}</div>
              </div>
            ))}
          </div>
        </div>
        <div className="mt-3 grid gap-2 xl:grid-cols-4">
          {topProposals.length ? (
            topProposals.map((proposal, index) => {
              const envelope = proposal.proposal_envelope;
              const status = proposalStatus(proposal);
              return (
                <div key={`${proposal.agent_id ?? "proposal"}-${proposal.requested_tool ?? index}`} className={`rounded border p-3 ${proposalStatusClass(status)}`}>
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="text-[10px] font-black uppercase opacity-70">{proposal.department_label ?? humanize(proposal.department)}</div>
                      <div className="mt-1 text-sm font-black">{proposalLabel(proposal)}</div>
                    </div>
                    <div className="rounded bg-slate-950/45 px-2 py-1 text-[10px] font-black uppercase">{humanize(status)}</div>
                  </div>
                  <div className="mt-3 text-xs font-black uppercase opacity-80">{humanize(envelope?.requested_tool ?? proposal.requested_tool)}</div>
                  <p className="mt-2 line-clamp-2 text-xs leading-relaxed opacity-85">{proposal.recommendation ?? envelope?.intent ?? "Proposal pending."}</p>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    <span className="rounded bg-slate-950/40 px-2 py-1 text-[10px] font-black uppercase">
                      {envelope?.requires_compliance || proposal.requires_compliance ? "Compliance" : "Department"}
                    </span>
                    <span className="rounded bg-slate-950/40 px-2 py-1 text-[10px] font-black uppercase">
                      {envelope?.requires_executive || proposal.requires_executive ? "Executive" : "No exec"}
                    </span>
                    <span className="rounded bg-slate-950/40 px-2 py-1 text-[10px] font-black uppercase">{humanize(envelope?.executor_agent ?? "tool_executor_agent")}</span>
                  </div>
                </div>
              );
            })
          ) : (
            <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs leading-relaxed text-slate-400 xl:col-span-4">
              Department proposal envelopes will appear after the operating loop emits role-agent proposals.
            </div>
          )}
        </div>
      </div>

      <div className="mt-5 rounded-lg border border-cyan-400/25 bg-slate-900 p-4">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Department agent conversation</div>
            <h3 className="mt-1 text-lg font-black text-slate-100">Specialists speak in proposals, challenges, and handoffs</h3>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {[
              ["Turns", departmentTurns.length || "--"],
              ["Departments", proposalArtifact?.proposal_count ?? proposalSummary?.total],
              ["Mediation", proposalArtifact?.conflicts?.length ?? "--"],
              ["Executor", proposalSummary?.ready_for_executor],
            ].map(([label, value]) => (
              <div key={label} className="rounded border border-slate-800 bg-slate-950 px-3 py-2 text-center">
                <div className="text-[10px] font-black uppercase text-slate-500">{label}</div>
                <div className="mt-1 text-sm font-black text-cyan-100">{compactValue(value)}</div>
              </div>
            ))}
          </div>
        </div>
        <div className="mt-4 grid gap-3 xl:grid-cols-2">
          {departmentTurns.length ? (
            departmentTurns.map((turn) => (
              <div key={turn.id} className={`rounded border p-3 ${proposalStatusClass(turn.status)}`}>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <div className="text-[10px] font-black uppercase opacity-70">{turn.department}</div>
                    <div className="mt-1 text-sm font-black">{turn.speaker}</div>
                  </div>
                  <div className="rounded bg-slate-950/45 px-2 py-1 text-[10px] font-black uppercase">{humanize(turn.status)}</div>
                </div>
                <div className="mt-3 rounded border border-slate-950/35 bg-slate-950/35 px-3 py-2">
                  <div className="text-[10px] font-black uppercase opacity-65">Says</div>
                  <p className="mt-1 line-clamp-3 text-xs leading-relaxed opacity-90">{turn.opening}</p>
                </div>
                <div className="mt-2 rounded border border-slate-950/35 bg-slate-950/25 px-3 py-2">
                  <div className="text-[10px] font-black uppercase opacity-65">Asks</div>
                  <p className="mt-1 line-clamp-3 text-xs leading-relaxed opacity-90">{turn.recommendation}</p>
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {turn.handoff && <span className="rounded bg-slate-950/40 px-2 py-1 text-[10px] font-black uppercase">To {humanize(turn.handoff)}</span>}
                  {turn.evidence.length ? (
                    turn.evidence.map((item) => (
                      <span key={item} className="max-w-full truncate rounded bg-slate-950/40 px-2 py-1 text-[10px] font-black uppercase">
                        {item}
                      </span>
                    ))
                  ) : (
                    <span className="rounded bg-slate-950/40 px-2 py-1 text-[10px] font-black uppercase">Evidence pending</span>
                  )}
                </div>
              </div>
            ))
          ) : (
            <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs leading-relaxed text-slate-400 xl:col-span-2">
              Run the department negotiation or live-feed agent case to populate department conversation turns.
            </div>
          )}
        </div>
      </div>

      <div className="mt-5 rounded-lg border border-cyan-400/25 bg-cyan-950/10 p-4">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <div className="text-[10px] font-black uppercase tracking-widest text-cyan-200">Park profile decision board</div>
            <h3 className="mt-1 text-lg font-black text-slate-100">{profileSummary?.venue_name ?? "Park profile not attached"}</h3>
            <p className="mt-2 max-w-4xl text-xs leading-relaxed text-slate-400">
              {profileSummary?.contract ??
                "Profile facts should constrain reasoning while live-feed evidence defines the current operating state."}
            </p>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {[
              ["Status", profileSummary?.status ?? proposalArtifact?.park_profile_context_status],
              ["Profiled agents", proposalArtifact?.profile_context_proposal_count],
              ["Candidates scored", proposalArtifact?.profile_counterfactual_candidate_count],
              ["Precedence", proposalArtifact?.precedence ?? profileSummary?.precedence],
            ].map(([label, value]) => (
              <div key={label} className="rounded border border-cyan-300/20 bg-slate-950 px-3 py-2 text-center">
                <div className="text-[10px] font-black uppercase text-slate-500">{label}</div>
                <div className="mt-1 truncate text-sm font-black text-cyan-100">{compactValue(value)}</div>
              </div>
            ))}
          </div>
        </div>
        <div className="mt-3 grid gap-2 xl:grid-cols-3">
          {profileProposals.length ? (
            profileProposals.map((proposal) => {
              const candidate = bestProfileCandidate(proposal);
              return (
                <div key={`${proposal.agent_id ?? proposal.department}-profile`} className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="text-[10px] font-black uppercase text-cyan-200">{proposal.department_label ?? humanize(proposal.department)}</div>
                      <div className="mt-1 text-sm font-black text-slate-100">{proposalLabel(proposal)}</div>
                    </div>
                    <div className="rounded bg-cyan-950 px-2 py-1 text-[10px] font-black uppercase text-cyan-100">
                      {compactValue(candidate.score)}
                    </div>
                  </div>
                  <div className="mt-3 text-xs font-black text-slate-100">{humanize(candidate.action)}</div>
                  <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-slate-400">
                    {candidate.reasons[0] ?? proposal.department_reasoning?.selected_rationale ?? "Profile counterfactual recorded."}
                  </p>
                  <div className="mt-3 space-y-1 text-[11px] font-bold text-slate-300">
                    <div className="truncate">Zones: {profileZoneNames(proposal) || "profile zones pending"}</div>
                    <div className="truncate">Locations: {profileLocationNames(proposal) || "profile locations pending"}</div>
                    <div className="truncate">Constraint: {profileConstraintSummary(proposal) || "policy constraint pending"}</div>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    <span className="rounded bg-slate-900 px-2 py-1 text-[10px] font-black uppercase text-cyan-100">{humanize(candidate.effect)}</span>
                    <span className="rounded bg-slate-900 px-2 py-1 text-[10px] font-black uppercase text-slate-300">
                      {humanize(proposal.profile_precedence ?? proposal.park_profile_context?.precedence)}
                    </span>
                  </div>
                </div>
              );
            })
          ) : (
            <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs leading-relaxed text-slate-400 xl:col-span-3">
              Profile-aware proposal slices will appear after the live-feed agent run attaches the full park profile.
            </div>
          )}
        </div>
      </div>

      <div className="mt-5 grid gap-3 xl:grid-cols-[.9fr_1.1fr]">
        <div className="rounded-lg border border-violet-400/25 bg-violet-950/10 p-4">
          <div className="text-[10px] font-black uppercase tracking-widest text-violet-200">Department negotiation</div>
          <h3 className="mt-1 text-lg font-black text-slate-100">Claims, challenges, and tradeoff selection</h3>
          <div className="mt-3 space-y-2">
            {negotiationRounds.length ? (
              negotiationRounds.map((round) => {
                const firstClaim = round.claims?.[0];
                const firstChallenge = round.challenges?.[0];
                return (
                  <div key={`${round.round ?? "round"}-${round.name ?? "negotiation"}`} className="rounded border border-slate-800 bg-slate-950 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-xs font-black text-slate-100">
                        Round {round.round ?? "--"}: {humanize(round.name ?? "negotiation")}
                      </div>
                      <div className="rounded bg-violet-950 px-2 py-1 text-[10px] font-black uppercase text-violet-100">
                        {(round.claims?.length ?? 0) + (round.challenges?.length ?? 0)} turns
                      </div>
                    </div>
                    <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-slate-400">
                      {firstChallenge?.issue ?? firstClaim?.wants ?? round.rationale ?? "Negotiation evidence recorded."}
                    </p>
                    <div className="mt-2 text-[10px] font-black uppercase text-violet-200">{humanize(round.decision ?? firstClaim?.disposition ?? "review")}</div>
                  </div>
                );
              })
            ) : (
              <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs leading-relaxed text-slate-400">
                Negotiation rounds will appear after department agents disagree or Executive weighs tradeoffs.
              </div>
            )}
          </div>
        </div>

        <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Executive tradeoff matrix</div>
              <h3 className="mt-1 text-lg font-black text-slate-100">Utility is ranked after safety, policy, and profile fit</h3>
            </div>
            <div className="rounded border border-slate-800 bg-slate-950 px-3 py-2 text-[10px] font-black uppercase text-slate-400">
              {tradeoffRows.length || "--"} rows
            </div>
          </div>
          <div className="mt-3 space-y-2">
            {tradeoffRows.length ? (
              tradeoffRows.map((row) => (
                <div key={`${row.department ?? "dept"}-${row.requested_tool ?? "tool"}`} className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="text-xs font-black text-slate-100">
                      {humanize(row.department)} / {humanize(row.requested_tool)}
                    </div>
                    <div className="rounded bg-slate-900 px-2 py-1 text-[10px] font-black uppercase text-slate-300">{humanize(row.verdict ?? row.decision)}</div>
                  </div>
                  <div className="mt-2 grid grid-cols-4 gap-1.5 text-center">
                    {[
                      ["Safety", row.safety_risk_weight],
                      ["Guest", row.guest_value],
                      ["Revenue", row.revenue_value],
                      ["Labor", row.labor_value],
                    ].map(([label, value]) => (
                      <div key={label} className="rounded bg-slate-900 px-2 py-1">
                        <div className="text-[9px] font-black uppercase text-slate-500">{label}</div>
                        <div className="text-xs font-black text-slate-100">{compactValue(value)}</div>
                      </div>
                    ))}
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <span className="rounded bg-cyan-950 px-2 py-1 text-[10px] font-black uppercase text-cyan-100">
                      Profile {humanize(row.profile_counterfactual_action)} {compactValue(row.profile_counterfactual_score)}
                    </span>
                    <span className="rounded bg-slate-900 px-2 py-1 text-[10px] font-black uppercase text-slate-300">{humanize(row.policy_status)}</span>
                  </div>
                  <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-slate-400">{row.rationale}</p>
                </div>
              ))
            ) : (
              <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs leading-relaxed text-slate-400">
                Executive tradeoff rows will appear after proposals are judged.
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="mt-5 rounded-lg border border-emerald-400/25 bg-emerald-950/10 p-4">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <div className="text-[10px] font-black uppercase tracking-widest text-emerald-200">Learning and execution closure</div>
            <h3 className="mt-1 text-lg font-black text-slate-100">No hard decision is left without owner, exit condition, and memory effect</h3>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {[
              ["Executor", executorProof?.status],
              ["Executed", executorProof?.executed_count],
              ["Held", executorProof?.held_count],
              ["Follow-up", followThrough?.task_count],
            ].map(([label, value]) => (
              <div key={label} className="rounded border border-emerald-300/20 bg-slate-950 px-3 py-2 text-center">
                <div className="text-[10px] font-black uppercase text-slate-500">{label}</div>
                <div className="mt-1 text-sm font-black text-emerald-100">{compactValue(value)}</div>
              </div>
            ))}
          </div>
        </div>
        <div className="mt-3 grid gap-3 xl:grid-cols-3">
          <div className="rounded border border-slate-800 bg-slate-950 p-3">
            <div className="text-[10px] font-black uppercase tracking-widest text-emerald-200">Memory influence</div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <span className="rounded bg-slate-900 px-2 py-1 text-[10px] font-black uppercase text-slate-300">Priors {compactValue(memoryPriors?.prior_count)}</span>
              <span className="rounded bg-slate-900 px-2 py-1 text-[10px] font-black uppercase text-slate-300">Applied {compactValue(memoryPriors?.applied_count)}</span>
              <span className="rounded bg-slate-900 px-2 py-1 text-[10px] font-black uppercase text-slate-300">Blocked {compactValue(memoryPriors?.blocked_count)}</span>
            </div>
            <div className="mt-3 space-y-2">
              {memoryDeltas.length ? (
                memoryDeltas.map((delta, index) => (
                  <div key={`${delta.requested_tool ?? "memory"}-${index}`} className="rounded border border-slate-800 bg-slate-900 px-3 py-2">
                    <div className="text-xs font-black text-slate-100">{humanize(delta.requested_tool ?? "decision")}</div>
                    <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-slate-400">
                      {delta.decision_delta?.after ?? delta.decision_delta?.effect ?? delta.usage_scope ?? "Prior outcome evaluated."}
                    </p>
                  </div>
                ))
              ) : (
                <p className="mt-3 text-xs leading-relaxed text-slate-400">No reusable prior has been applied to this run yet.</p>
              )}
            </div>
          </div>

          <div className="rounded border border-slate-800 bg-slate-950 p-3">
            <div className="text-[10px] font-black uppercase tracking-widest text-emerald-200">Action disposition</div>
            <div className="mt-2 grid grid-cols-2 gap-2">
              {[
                ["Delivered", receiverProof?.delivered_count],
                ["Acked", receiverProof?.acknowledged_count],
                ["Receiver exec", receiverProof?.executed_count],
                ["Public msgs", receiverProof?.public_guest_messages_sent],
              ].map(([label, value]) => (
                <div key={label} className="rounded bg-slate-900 px-2 py-2 text-center">
                  <div className="text-[9px] font-black uppercase text-slate-500">{label}</div>
                  <div className="text-sm font-black text-slate-100">{compactValue(value)}</div>
                </div>
              ))}
            </div>
            <p className="mt-3 text-xs leading-relaxed text-slate-400">
              {receiverProof?.status
                ? `${humanize(receiverProof.status)}. Material mutation: ${compactValue(receiverProof.material_state_mutation)}.`
                : "Receiver delivery proof appears after Tool Executor produces receipts."}
            </p>
          </div>

          <div className="rounded border border-slate-800 bg-slate-950 p-3">
            <div className="text-[10px] font-black uppercase tracking-widest text-emerald-200">Hard-decision follow-through</div>
            <div className="mt-3 space-y-2">
              {(followThrough?.tasks ?? []).slice(0, 4).map((task) => (
                <div key={task.task_id ?? `${task.department}-${task.source_tool}`} className="rounded border border-slate-800 bg-slate-900 px-3 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-xs font-black text-slate-100">{humanize(task.department)} / {humanize(task.source_tool)}</div>
                    <div className="rounded bg-slate-950 px-2 py-1 text-[10px] font-black uppercase text-slate-300">{humanize(task.status)}</div>
                  </div>
                  <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-slate-400">{task.why_not_undecided ?? task.exit_condition}</p>
                  <div className="mt-2 text-[10px] font-black uppercase text-emerald-200">{humanize(task.next_owner ?? "owner pending")}</div>
                </div>
              ))}
              {!(followThrough?.tasks ?? []).length && (
                <p className="text-xs leading-relaxed text-slate-400">Held actions will appear here with owner, exit condition, and fallback.</p>
              )}
            </div>
          </div>
        </div>
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs leading-relaxed text-slate-400">
            Measurement: {humanize(outcomeMeasurement?.status)} / reward {compactValue(outcomeMeasurement?.reward_value)} / confidence {compactValue(outcomeMeasurement?.attribution_confidence)}
          </div>
          <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs leading-relaxed text-slate-400">
            Memory write: {humanize(outcomeMemory?.status)} / {outcomeMemory?.mongo_collection ?? "collection pending"} / {outcomeMemory?.outcome_id ?? "outcome pending"}
          </div>
        </div>
      </div>

      <div className="mt-5 grid gap-3 lg:grid-cols-4">
        {PRIMARY_OPERATING_STAGES.slice(0, 8).map((stage) => (
          <StageCard
            key={stage.id}
            label={stage.label}
            owner={stage.owner}
            role={stage.role}
            evidence={stageEvidence(stage.id, props)}
            tone={stage.tone}
            status={statusForStage(stage.id, props)}
          />
        ))}
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-[1fr_220px_1fr] lg:items-stretch">
        <div className="rounded border border-emerald-400/30 bg-emerald-950/15 p-3">
          <div className="text-[10px] font-black uppercase tracking-widest text-emerald-200">{dispatchPath}</div>
          <div className="mt-2 text-lg font-black text-emerald-100">{dispatchTarget}</div>
          <p className="mt-2 text-xs leading-relaxed text-emerald-100/80">
            {requiresReview
              ? "The recommendation needs operator review before receiver systems are touched."
              : "Runtime dispatch becomes eligible only after policy and eval checks pass."}
          </p>
        </div>

        <div className="flex items-center justify-center rounded border border-slate-800 bg-slate-900 p-3 text-center text-xs font-black uppercase tracking-widest text-slate-400">
          both paths write outcome
        </div>

        <div className="rounded border border-teal-400/30 bg-teal-950/15 p-3">
          <div className="text-[10px] font-black uppercase tracking-widest text-teal-200">Outcome Tracker</div>
          <div className="mt-2 text-lg font-black text-teal-100">Trace, eval, memory, training</div>
          <p className="mt-2 text-xs leading-relaxed text-teal-100/80">
            Dispatch acknowledgements and review decisions become trace rows, eval rows, MongoDB memory, and ML training labels.
          </p>
        </div>
      </div>

      <div className="mt-4 grid gap-3 xl:grid-cols-[1fr_1fr]">
        <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">LLM interpreter path</div>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            {LLM_INTERPRETER_STAGES.map((stage) => (
              <CompactStageCard key={stage.id} label={stage.label} owner={stage.owner} role={stage.role} evidence={stage.evidence} tone={stage.tone} />
            ))}
          </div>
        </div>

        <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Current receiver payloads</div>
          <div className="mt-3 space-y-2">
            {topDispatches.length ? (
              topDispatches.map((dispatch) => (
              <div key={dispatch.id} className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="text-xs font-black uppercase text-cyan-200">{humanize(dispatch.channel)}</div>
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{dispatch.status ?? "status missing"}</div>
                </div>
                <div className="mt-1 text-sm font-black text-slate-100">{dispatch.target}</div>
                <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-slate-400">{dispatch.body}</p>
              </div>
              ))
            ) : (
              <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs leading-relaxed text-slate-400">
                Runtime receiver payloads will appear after the operating loop produces a delivery receipt.
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
