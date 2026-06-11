"use client";

import type { RoleAgentProposal, RunTelemetry } from "@/types/platform";
import type { ParkState } from "@/types/park";
import type { ActualTrainingStatus, AutopilotDecision, DispatchView, FeedReliabilityGate, LiveFeedHealth } from "./useCommandCenter";
import { gateClass, humanize, toneClass } from "./style";

type OperationsStoryPanelProps = {
  parkState: ParkState;
  runTelemetry: RunTelemetry | null;
  selectedAction?: RunTelemetry["planner"] extends infer Planner ? Planner extends { selected_action?: infer Action } ? Action : never : never;
  policyGate?: string;
  evalScore?: number;
  dispatches: DispatchView[];
  actualTraining: ActualTrainingStatus | null;
  liveFeedHealth: LiveFeedHealth | null;
  feedReliabilityGate: FeedReliabilityGate;
  autopilotDecision: AutopilotDecision;
  isAutopilotEnabled: boolean;
  isAutopilotRunning: boolean;
  isRunning: boolean;
  onSetAutopilotEnabled: (enabled: boolean) => void;
  onRunAutopilot: () => void;
  onRunIncidentReview: () => void;
  onRunLiveFeedCase: () => void;
  onRunNegotiationCase: () => void;
};

function percent(value?: number) {
  if (typeof value !== "number" || Number.isNaN(value)) return "--";
  return `${Math.round(value)}%`;
}

function compact(value: unknown) {
  if (value === undefined || value === null || value === "") return "--";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

function confidence(value?: number) {
  if (typeof value !== "number" || Number.isNaN(value)) return "--";
  return value > 1 ? `${Math.round(value)}%` : `${Math.round(value * 100)}%`;
}

function activeProblem(parkState: ParkState, runTelemetry: RunTelemetry | null) {
  const operationEvent = runTelemetry?.operation_event?.event;
  const chaos = parkState.chaosEngine;
  const event = operationEvent ?? chaos?.activeUnexpectedEvents?.[0];
  if (event?.kind) {
    return {
      label: humanize(event.kind),
      detail: event.reason ?? `Target ${event.targetId ?? "park"} at ${event.intensity ?? "--"} intensity.`,
      source: event.source ?? (operationEvent ? "agent run" : "live chaos engine"),
      intensity: event.intensity,
    };
  }
  const topAlert = parkState.alerts?.[0];
  if (topAlert) {
    return { label: topAlert.title, detail: topAlert.detail, source: topAlert.severity, intensity: undefined };
  }
  return {
    label: "No acute incident yet",
    detail: `${chaos?.ruleCount ?? 0} random rules armed; ${chaos?.activeCount ?? 0} active unexpected events.`,
    source: "live park",
    intensity: undefined,
  };
}

function strongestSignals(parkState: ParkState, liveFeedHealth: LiveFeedHealth | null) {
  const rides = [...(parkState.guestFlow.rides ?? [])]
    .sort((left, right) => (right.waitMins ?? 0) - (left.waitMins ?? 0))
    .slice(0, 1)
    .map((ride) => `${ride.name ?? ride.id} wait ${ride.waitMins ?? "--"}m`);
  const zones = [...(parkState.guestFlow.zones ?? [])]
    .sort((left, right) => (right.density ?? 0) - (left.density ?? 0))
    .slice(0, 1)
    .map((zone) => `${zone.name ?? zone.id} density ${percent(zone.density)}`);
  const food = [...(parkState.foodInventory?.locations ?? [])]
    .sort((left, right) => (right.pickupEtaMinutes ?? 0) - (left.pickupEtaMinutes ?? 0))
    .slice(0, 1)
    .map((location) => `${location.name} ETA ${location.pickupEtaMinutes ?? "--"}m`);
  const feeds = liveFeedHealth?.summary ? [`${liveFeedHealth.summary.ready_feed_count ?? 0}/${liveFeedHealth.summary.required_feed_count ?? 0} feeds ready`] : [];
  return [...rides, ...zones, ...food, ...feeds].filter(Boolean).slice(0, 4);
}

function reasoningLines(runTelemetry: RunTelemetry | null) {
  const negotiationTrace = runTelemetry?.negotiation_trace as
    | (NonNullable<RunTelemetry["negotiation_trace"]> & {
        executive_adjudication?: {
          model_version?: string;
          decision_policy?: string;
          status?: string;
          reason?: string;
        };
        final_executive_decision?: {
          status?: string;
          reason?: string;
        };
      })
    | undefined;
  return [
    negotiationTrace?.final_executive_decision?.reason,
    negotiationTrace?.executive_adjudication?.reason,
    runTelemetry?.policy_regulation_judgment?.findings?.[0],
    runTelemetry?.policy_regulation_judgment?.human_review_reasons?.[0],
    ...(runTelemetry?.live_feed_case?.reasoning ?? []),
    runTelemetry?.operator_response?.summary,
    runTelemetry?.governance?.findings?.[0],
  ]
    .filter((item): item is string => Boolean(item))
    .slice(0, 3);
}

function outcomeLine(runTelemetry: RunTelemetry | null, training: ActualTrainingStatus | null) {
  const impact = runTelemetry?.live_feed_simulated_ops_impact?.state_impact;
  if (impact?.before_after_line) return impact.before_after_line;
  const episode = training?.episode_fitness?.latest_episode;
  if (episode?.scores?.reward_delta !== undefined) return `Latest RL reward delta ${compact(episode.scores.reward_delta)} from ${episode.scenario_key ?? "recent episode"}.`;
  return "Outcome and RL fitness update after executed or acknowledged actions.";
}

function statusTone(value?: string) {
  const normalized = String(value ?? "").toLowerCase();
  if (normalized.includes("block")) return "risk";
  if (normalized.includes("review") || normalized.includes("hold") || normalized.includes("pending")) return "watch";
  return "ok";
}

type EvidenceRow = {
  label: string;
  value: string;
  detail: string;
  tone?: string;
};

function proposalAgentName(proposal: RoleAgentProposal) {
  return proposal.department_agent ?? proposal.department_label ?? proposal.department ?? proposal.role ?? proposal.agent_id ?? "Agent";
}

function proposalDecision(proposal: RoleAgentProposal) {
  return proposal.action_disposition?.decision ?? proposal.proposal_envelope?.executor_status ?? proposal.executor_status ?? proposal.proposal_envelope?.approval_status ?? "proposed";
}

function negotiationRows(runTelemetry: RunTelemetry | null): EvidenceRow[] {
  const trace = runTelemetry?.negotiation_trace as
    | (NonNullable<RunTelemetry["negotiation_trace"]> & {
        executive_adjudication?: {
          model_version?: string;
          decision_policy?: string;
          status?: string;
          reason?: string;
          initial_candidate_id?: string;
          final_candidate_id?: string;
          score_gap_vs_initial?: number;
          conflict_count?: number;
          challenger_ledgers?: Array<{
            candidate_id?: string;
            source?: string;
            score?: number;
            agent_id?: string;
            role?: string;
            recommendation?: string;
          }>;
        };
        final_executive_decision?: {
          status?: string;
          reason?: string;
          initial_candidate_id?: string;
          final_candidate_id?: string;
          rejected_candidates?: Array<{ candidate_id?: string; score?: number; reason?: string }>;
        };
      })
    | undefined;
  const adjudication = trace?.executive_adjudication;
  const finalDecision = trace?.final_executive_decision;
  const backendDecisionRows: EvidenceRow[] = [];
  if (finalDecision?.reason || adjudication?.reason) {
    backendDecisionRows.push({
      label: adjudication?.model_version ?? "Executive mediator",
      value: humanize(finalDecision?.status ?? adjudication?.status ?? "decided"),
      detail: finalDecision?.reason ?? adjudication?.reason ?? "Backend executive mediation selected the final plan.",
      tone: statusTone(finalDecision?.status ?? adjudication?.status),
    });
  }
  if (adjudication?.decision_policy || adjudication?.final_candidate_id) {
    backendDecisionRows.push({
      label: "Candidate adjudication",
      value: adjudication.final_candidate_id ?? "final candidate",
      detail: [
        adjudication.decision_policy ? `Policy ${humanize(adjudication.decision_policy)}` : "",
        adjudication.initial_candidate_id ? `Initial ${adjudication.initial_candidate_id}` : "",
        adjudication.score_gap_vs_initial !== undefined ? `Score gap ${compact(adjudication.score_gap_vs_initial)}` : "",
        adjudication.conflict_count !== undefined ? `${adjudication.conflict_count} conflict(s)` : "",
      ]
        .filter(Boolean)
        .join(" / "),
      tone: statusTone(adjudication.status),
    });
  }
  const challengerRows =
    adjudication?.challenger_ledgers?.slice(0, 2).map((candidate) => ({
      label: candidate.role ?? candidate.agent_id ?? candidate.source ?? "Candidate",
      value: candidate.candidate_id ?? "challenger",
      detail: [candidate.recommendation, candidate.score !== undefined ? `Score ${candidate.score}` : ""].filter(Boolean).join(" / ") || "Candidate was scored by backend mediation.",
      tone: candidate.candidate_id === adjudication.final_candidate_id ? "ok" : "watch",
    })) ?? [];
  if (backendDecisionRows.length || challengerRows.length) {
    return [...backendDecisionRows, ...challengerRows].slice(0, 4);
  }

  const artifact = runTelemetry?.role_agent_proposals;
  const proposalRows =
    artifact?.proposals?.slice(0, 3).map((proposal) => ({
      label: proposalAgentName(proposal),
      value: humanize(proposalDecision(proposal)),
      detail:
        proposal.department_reasoning?.selected_rationale ??
        proposal.department_reasoning?.diagnosis ??
        proposal.recommendation ??
        proposal.proposal_envelope?.intent ??
        "Agent proposal recorded.",
      tone: statusTone(proposalDecision(proposal)),
    })) ?? [];

  const roundRows =
    artifact?.negotiation_rounds?.slice(0, 2).map((round) => ({
      label: round.name ?? `Round ${round.round ?? "--"}`,
      value: humanize(round.decision ?? "negotiated"),
      detail: round.rationale ?? round.challenges?.[0]?.resolution ?? round.claims?.[0]?.wants ?? "Negotiation round recorded.",
      tone: statusTone(round.decision),
    })) ?? [];

  const executive = artifact?.executive_tradeoff;
  const executiveRow = executive
    ? [
        {
          label: "Executive tradeoff",
          value: humanize(executive.decision ?? "reviewed"),
          detail: executive.rationale ?? `Approved ${executive.approved_departments?.length ?? 0}; held ${executive.held_departments?.length ?? 0}.`,
          tone: statusTone(executive.decision),
        },
      ]
    : [];

  const rows = [...proposalRows, ...roundRows, ...executiveRow].slice(0, 4);
  if (rows.length) return rows;

  const agentFindingRows =
    runTelemetry?.agent_findings?.slice(0, 4).map((finding) => ({
      label: finding.department_agent ?? finding.department_label ?? finding.agent ?? finding.name ?? finding.role ?? "Runtime agent",
      value: finding.recommendation ?? finding.finding ?? "Finding recorded",
      detail: [
        finding.finding,
        finding.input_signals?.length ? `Signals: ${finding.input_signals.slice(0, 2).join(", ")}` : "",
        finding.policy_refs?.length ? `Policy: ${finding.policy_refs.slice(0, 2).join(", ")}` : "",
        finding.confidence !== undefined ? `Confidence ${confidence(finding.confidence)}` : "",
      ]
        .filter(Boolean)
        .join(" / "),
      tone: finding.urgency ?? "watch",
    })) ?? [];
  if (agentFindingRows.length) return agentFindingRows;

  const traceRows =
    runTelemetry?.trace_contract?.phases?.slice(0, 4).map((phase) => ({
      label: phase.label ?? phase.id ?? "Trace phase",
      value: humanize(phase.status ?? phase.gate_status ?? "recorded"),
      detail: phase.evidence ?? phase.selected ?? phase.findings?.[0] ?? "Trace phase recorded.",
      tone: statusTone(phase.status ?? phase.gate_status),
    })) ?? [];
  if (traceRows.length) return traceRows;

  if (runTelemetry) {
    const selected = runTelemetry.planner?.selected_action;
    return [
      {
        label: "Signal interpreter",
        value: runTelemetry.operator_response?.headline ?? runTelemetry.live_feed_case?.lead_signal_type ?? "Live state interpreted",
        detail: runTelemetry.operator_response?.summary ?? runTelemetry.live_feed_case?.operator_message ?? "Runtime state was converted into a bounded operating problem.",
        tone: "ok",
      },
      {
        label: "RL optimizer",
        value: selected?.label ?? runTelemetry.planner?.runtime ?? "Action scored",
        detail: selected?.expected_effect ?? `Planner confidence ${confidence(runTelemetry.planner?.confidence_score)}.`,
        tone: selected ? "ok" : "watch",
      },
      {
        label: "Policy judge",
        value: humanize(runTelemetry.governance?.gate_status ?? "checked"),
        detail: runTelemetry.governance?.findings?.[0] ?? "Policy gate evaluated the selected action before execution.",
        tone: statusTone(runTelemetry.governance?.gate_status),
      },
      {
        label: "Executor",
        value: humanize(runTelemetry.execution?.status ?? "policy routed"),
        detail: runTelemetry.execution?.message ?? "Executor disposition is reflected by the autopilot and backend action response.",
        tone: statusTone(runTelemetry.execution?.status),
      },
    ];
  }

  return [
    {
      label: "Agent negotiation pending",
      value: "Waiting",
      detail: "Run a random incident, live-feed, or department case to populate agent findings, proposals, and tradeoff resolution.",
      tone: "watch",
    },
  ];
}

function policyRows(runTelemetry: RunTelemetry | null, gate: string, autopilotDecision: AutopilotDecision, autopilotDetail: string): EvidenceRow[] {
  const policyJudgment = runTelemetry?.policy_regulation_judgment ?? runTelemetry?.trace_contract?.policy_regulation_judgment;
  const judgmentRows =
    policyJudgment
      ? [
          {
            label: policyJudgment.interpreted_policy?.primary_case_id ?? "Policybook judgment",
            value: humanize(policyJudgment.status ?? gate),
            detail:
              policyJudgment.human_review_reasons?.[0] ??
              policyJudgment.findings?.[0] ??
              policyJudgment.alignment_rule ??
              "Policybook alignment judged the selected bounded action.",
            tone: statusTone(policyJudgment.status ?? gate),
          },
          ...(policyJudgment.policy_refs?.slice(0, 2).map((ref) => ({
            label: ref,
            value: policyJudgment.interpreted_policy?.approval_required ? "approval standard" : "policy reference",
            detail:
              policyJudgment.required_evidence?.[0] ??
              policyJudgment.interpreted_policy?.primary_case_title ??
              "Referenced by backend policy alignment.",
            tone: statusTone(policyJudgment.status ?? gate),
          })) ?? []),
        ]
      : [];

  const policyRules =
    runTelemetry?.trace_contract?.policy_rules?.slice(0, 3).map((rule) => ({
      label: rule.policy_ref ?? rule.policy_book_id ?? "Policy rule",
      value: humanize(rule.gate_status ?? gate),
      detail: rule.finding ?? "Policy rule checked against selected action.",
      tone: statusTone(rule.gate_status ?? gate),
    })) ?? [];

  const proposalPolicy =
    runTelemetry?.role_agent_proposals?.tradeoff_matrix?.slice(0, 3).map((row) => ({
      label: humanize(row.department ?? row.agent ?? "department"),
      value: humanize(row.policy_status ?? row.verdict ?? row.decision ?? "checked"),
      detail: row.rationale ?? `${humanize(row.requested_tool ?? "proposal")} safety ${compact(row.safety_risk_weight)} / confidence ${confidence(row.confidence)}.`,
      tone: statusTone(row.policy_status ?? row.verdict ?? row.decision),
    })) ?? [];

  const governanceRows =
    runTelemetry?.governance?.findings?.slice(0, 2).map((finding) => ({
      label: "Governance gate",
      value: humanize(gate),
      detail: finding,
      tone: statusTone(gate),
    })) ?? [];

  const rows = [...judgmentRows, ...policyRules, ...proposalPolicy, ...governanceRows].slice(0, 4);
  if (rows.length) return rows;
  return [
    {
      label: "Autopilot boundary",
      value: humanize(gate),
      detail: autopilotDetail || autopilotDecision.reason,
      tone: statusTone(gate),
    },
  ];
}

function finalDecisionRows(runTelemetry: RunTelemetry | null, selectedAction: OperationsStoryPanelProps["selectedAction"], autopilotDecision: AutopilotDecision): EvidenceRow[] {
  const trace = runTelemetry?.negotiation_trace as
    | (NonNullable<RunTelemetry["negotiation_trace"]> & {
        executive_adjudication?: {
          model_version?: string;
          status?: string;
          reason?: string;
          final_candidate_id?: string;
          score_gap_vs_initial?: number;
          rejected_candidates?: Array<{ candidate_id?: string; score?: number; reason?: string }>;
        };
        final_executive_decision?: {
          status?: string;
          reason?: string;
          final_candidate_id?: string;
          rejected_candidates?: Array<{ candidate_id?: string; score?: number; reason?: string }>;
        };
      })
    | undefined;
  const adjudication = trace?.executive_adjudication;
  const backendDecision = trace?.final_executive_decision;
  const backendSelectedRow = backendDecision || adjudication
    ? {
        label: adjudication?.model_version ?? "Backend final decision",
        value: selectedAction?.label ?? backendDecision?.final_candidate_id ?? adjudication?.final_candidate_id ?? "Final action",
        detail:
          backendDecision?.reason ??
          adjudication?.reason ??
          selectedAction?.expected_effect ??
          autopilotDecision.reason,
        tone: statusTone(backendDecision?.status ?? adjudication?.status),
      }
    : null;
  const backendRejectedRows =
    (backendDecision?.rejected_candidates ?? adjudication?.rejected_candidates)?.slice(0, 3).map((item, index) => ({
      label: index === 0 ? "Rejected candidate" : "Held candidate",
      value: item.candidate_id ?? "not selected",
      detail: [item.reason, item.score !== undefined ? `Score ${item.score}` : ""].filter(Boolean).join(" / ") || "Backend mediation kept this option out of the final plan.",
      tone: "watch",
    })) ?? [];
  if (backendSelectedRow) {
    return [backendSelectedRow, ...backendRejectedRows].slice(0, 4);
  }

  const rejected = runTelemetry?.trace_contract?.phases?.flatMap((phase) => phase.rejected ?? []) ?? [];
  const rejectedRows = rejected.slice(0, 2).map((item, index) => ({
    label: index === 0 ? "Rejected alternative" : "Held alternative",
    value: "Not selected",
    detail: compact(item),
    tone: "watch",
  }));

  const candidateRows =
    runTelemetry?.trace_contract?.candidate_actions?.slice(0, 2).map((candidate) => ({
      label: candidate.label ?? candidate.id ?? "Candidate",
      value: humanize(candidate.status ?? "scored"),
      detail: candidate.reason ?? `Projected ${compact(candidate.projected_impact)}`,
      tone: statusTone(candidate.status),
    })) ?? [];

  const selectedRow = {
    label: "Final recommendation",
    value: selectedAction?.label ?? "No final action",
    detail: selectedAction?.expected_effect ?? autopilotDecision.reason,
    tone: selectedAction ? "ok" : "watch",
  };

  return [selectedRow, ...rejectedRows, ...candidateRows].slice(0, 4);
}

function EvidenceColumn({ title, rows }: { title: string; rows: EvidenceRow[] }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
      <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">{title}</div>
      <div className="mt-3 space-y-2">
        {rows.map((row, index) => (
          <div key={`${title}-${row.label}-${row.value}-${index}`} className={`rounded border p-3 ${toneClass(row.tone)}`}>
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate text-[10px] font-black uppercase tracking-widest opacity-70">{row.label}</div>
                <div className="mt-1 line-clamp-2 text-sm font-black">{row.value}</div>
              </div>
            </div>
            <p className="mt-2 line-clamp-4 text-xs leading-relaxed opacity-85">{row.detail}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

export function OperationsStoryPanel(props: OperationsStoryPanelProps) {
  const problem = activeProblem(props.parkState, props.runTelemetry);
  const signals = strongestSignals(props.parkState, props.liveFeedHealth);
  const reasoning = reasoningLines(props.runTelemetry);
  const selectedAction = props.selectedAction;
  const rlFitness = props.actualTraining?.episode_fitness;
  const rewardDelta = rlFitness?.latest_episode?.scores?.reward_delta ?? props.runTelemetry?.live_feed_simulated_ops_impact?.episode_fitness?.rewardDelta;
  const pressureReduction = rlFitness?.latest_episode?.pressure?.reduction_vs_baseline ?? props.runTelemetry?.live_feed_simulated_ops_impact?.episode_fitness?.pressure?.reduction_vs_baseline;
  const gate = props.policyGate ?? props.autopilotDecision.gate ?? "pending";
  const dispatchCount = props.dispatches.length || props.runTelemetry?.live_feed_receiver_delivery?.delivered_count || 0;
  const executed = props.autopilotDecision.mode === "executed" || props.runTelemetry?.execution?.status === "executed";
  const negotiation = negotiationRows(props.runTelemetry);
  const finalDecision = finalDecisionRows(props.runTelemetry, selectedAction, props.autopilotDecision);
  const reasoningArtifactCount =
    props.runTelemetry?.role_agent_proposals?.proposal_count ??
    props.runTelemetry?.role_agent_proposals?.proposals?.length ??
    props.runTelemetry?.agent_findings?.length ??
    props.runTelemetry?.trace_contract?.phases?.length ??
    (props.runTelemetry ? negotiation.length : undefined) ??
    0;
  const actionOwner = selectedAction?.owner ?? props.dispatches[0]?.target ?? "operator";
  const actionRisk =
    (selectedAction as { risk_level?: string } | undefined)?.risk_level ??
    (props.runTelemetry?.governance as { risk_level?: string } | undefined)?.risk_level ??
    "bounded";
  const actionConfidence = confidence(props.runTelemetry?.planner?.confidence_score ?? props.evalScore);
  const decisionHeadline = selectedAction?.label ?? (props.isAutopilotRunning ? "autopilot evaluation" : "bounded decision pending");
  const decisionDetail =
    selectedAction?.expected_effect ??
    reasoning[0] ??
    "Run an incident review to produce a policy-gated mitigation, or arm autopilot for autonomous low-risk operation.";
  const autopilotHeldOnPriorFeedGate =
    props.autopilotDecision.mode === "held_for_review" &&
    /feed gate|live-feed|live feed|feed reliability/i.test(props.autopilotDecision.reason) &&
    props.feedReliabilityGate.status === "clear";
  const autopilotStateDetail = autopilotHeldOnPriorFeedGate
    ? "The last autopilot cycle held on a pre-refresh feed gate. Current feeds are clear; rerun autopilot to use the recovered evidence contract."
    : props.autopilotDecision.reason;
  const evidenceGateDetail = autopilotHeldOnPriorFeedGate
    ? "Current feeds are clear. The held autopilot receipt is older than the recovered feed contract."
    : props.feedReliabilityGate.reasons[0] ?? reasoning[0] ?? signals[0] ?? "Live park signals are still collecting.";
  const policyAlignment = policyRows(props.runTelemetry, gate, props.autopilotDecision, autopilotStateDetail);

  const storyline = [
    { label: "1. Random problem", value: problem.label, detail: problem.detail, tone: problem.intensity && problem.intensity > 80 ? "risk" : "watch" },
    {
      label: "2. Evidence gate",
      value: `${props.feedReliabilityGate.status} ${props.feedReliabilityGate.score}/100`,
      detail: evidenceGateDetail,
      tone: props.feedReliabilityGate.status === "clear" ? "ok" : props.feedReliabilityGate.status === "blocked" ? "risk" : "watch",
    },
    { label: "3. RL decision", value: selectedAction?.label ?? "No action selected", detail: selectedAction?.expected_effect ?? `Policy model ${props.actualTraining?.model?.best_policy_id ?? "pending"}.`, tone: selectedAction ? "ok" : "watch" },
    { label: "4. Low-risk gate", value: humanize(gate), detail: props.runTelemetry?.governance?.findings?.[0] ?? autopilotStateDetail, tone: statusTone(gate) },
    { label: "5. Operate", value: executed ? "Mitigation executed" : dispatchCount ? `${dispatchCount} payloads ready` : "No dispatch yet", detail: autopilotStateDetail, tone: executed ? "ok" : "watch" },
    { label: "6. Learn", value: rewardDelta !== undefined ? `Reward ${compact(rewardDelta)}` : "Outcome pending", detail: pressureReduction !== undefined ? `Pressure reduction ${compact(pressureReduction)}` : outcomeLine(props.runTelemetry, props.actualTraining), tone: rewardDelta !== undefined || pressureReduction !== undefined ? "ok" : "watch" },
  ];

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-950 p-4">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <div className="text-[10px] font-black uppercase tracking-widest text-lime-300">Operating decision</div>
          <h2 className="mt-2 max-w-5xl text-2xl font-black tracking-normal text-slate-100">
            {problem.label} to {decisionHeadline}
          </h2>
          <p className="mt-2 max-w-5xl text-sm leading-relaxed text-slate-400">
            Live pressure, feed trust, agent negotiation, policy alignment, final action, dispatch, and learning are shown in that order.
          </p>
        </div>
        <div className={`w-full rounded-lg border p-3 xl:max-w-md ${toneClass(props.autopilotDecision.mode === "blocked" ? "risk" : props.autopilotDecision.mode === "executed" ? "ok" : "watch")}`}>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest opacity-70">Autopilot state</div>
              <div className="mt-1 text-lg font-black">{props.isAutopilotEnabled ? "Armed" : "Off"} / {humanize(props.autopilotDecision.mode)}</div>
            </div>
            <div className={`w-fit rounded border px-2.5 py-1 text-[10px] font-black uppercase tracking-widest ${gateClass(gate)}`}>Gate {humanize(gate)}</div>
          </div>
          <p className="mt-2 line-clamp-3 text-xs leading-relaxed opacity-85">{autopilotStateDetail}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <label className="flex min-h-[36px] items-center gap-2 rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-white">
              <input
                type="checkbox"
                checked={props.isAutopilotEnabled}
                onChange={(event) => props.onSetAutopilotEnabled(event.target.checked)}
                disabled={props.isAutopilotRunning}
                className="h-4 w-4 accent-lime-300"
              />
              Autopilot
            </label>
            <button
              type="button"
              onClick={props.onRunAutopilot}
              disabled={!props.isAutopilotEnabled || props.isRunning || props.isAutopilotRunning}
              className="rounded border border-lime-300 bg-lime-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-lime-200 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {props.isAutopilotRunning ? "Autopilot running" : "Run autopilot"}
            </button>
            <button
              type="button"
              onClick={props.onRunIncidentReview}
              disabled={props.isAutopilotRunning || props.isRunning}
              className="rounded border border-amber-300 bg-amber-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-amber-200 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Run incident review
            </button>
            <button
              type="button"
              onClick={props.onRunLiveFeedCase}
              disabled={props.isRunning || props.isAutopilotRunning}
              className="rounded border border-emerald-300 bg-emerald-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-emerald-200 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Live-feed case
            </button>
            <button
              type="button"
              onClick={props.onRunNegotiationCase}
              disabled={props.isRunning || props.isAutopilotRunning}
              className="rounded border border-cyan-300 bg-cyan-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Negotiation case
            </button>
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-3 xl:grid-cols-[0.95fr_1.1fr_0.95fr]">
        <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
          <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">1. Live park pressure</div>
          <div className="mt-2 text-lg font-black text-slate-100">{problem.label}</div>
          <p className="mt-2 text-xs leading-relaxed text-slate-400">{problem.detail}</p>
          <div className="mt-3 space-y-2">
            {signals.map((signal) => (
              <div key={signal} className="rounded border border-slate-800 bg-slate-950 px-3 py-2 text-xs font-bold text-slate-300">
                {signal}
              </div>
            ))}
          </div>
          <div className={`mt-3 rounded border p-3 ${toneClass(props.feedReliabilityGate.status === "clear" ? "ok" : props.feedReliabilityGate.status === "blocked" ? "risk" : "watch")}`}>
            <div className="text-[10px] font-black uppercase tracking-widest opacity-70">2. Evidence trust gate</div>
            <div className="mt-1 text-sm font-black">
              {humanize(props.feedReliabilityGate.status)} / {props.feedReliabilityGate.score}/100 / {humanize(props.feedReliabilityGate.action)}
            </div>
            <p className="mt-2 line-clamp-3 text-xs leading-relaxed opacity-85">{evidenceGateDetail}</p>
          </div>
        </div>

        <div className="rounded-lg border border-cyan-400/20 bg-cyan-950/10 p-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">3. Agent reasoning and policy alignment</div>
              <div className="mt-1 text-sm font-black text-slate-100">Proposals are challenged before a final action is allowed.</div>
            </div>
            <div className="shrink-0 rounded bg-slate-950 px-2.5 py-1 text-[10px] font-black uppercase tracking-widest text-cyan-100">
              {reasoningArtifactCount} artifacts
            </div>
          </div>
          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            <EvidenceColumn title="Agent negotiation" rows={negotiation.slice(0, 3)} />
            <EvidenceColumn title="Policy alignment" rows={policyAlignment.slice(0, 3)} />
          </div>
        </div>

        <div className={`rounded-lg border p-3 ${toneClass(selectedAction ? "ok" : "watch")}`}>
          <div className="text-[10px] font-black uppercase tracking-widest opacity-70">4. Final operating decision</div>
          <div className="mt-2 text-xl font-black">{decisionHeadline}</div>
          <p className="mt-2 text-xs leading-relaxed opacity-85">{decisionDetail}</p>
          <div className="mt-3 grid grid-cols-2 gap-2">
            {[
              ["Owner", actionOwner],
              ["Risk", humanize(String(actionRisk))],
              ["Confidence", actionConfidence],
              ["Dispatch", executed ? "executed" : dispatchCount ? `${dispatchCount} ready` : "pending"],
            ].map(([label, value]) => (
              <div key={label} className="rounded border border-slate-950/30 bg-slate-950/35 px-3 py-2">
                <div className="text-[10px] font-black uppercase opacity-65">{label}</div>
                <div className="mt-1 truncate text-xs font-black">{value}</div>
              </div>
            ))}
          </div>
          <div className={`mt-3 rounded border p-3 ${toneClass(rewardDelta !== undefined || pressureReduction !== undefined ? "ok" : "watch")}`}>
            <div className="text-[10px] font-black uppercase tracking-widest opacity-70">5. Learn from outcome</div>
            <div className="mt-1 text-sm font-black">{rewardDelta !== undefined ? `Reward ${compact(rewardDelta)}` : "Outcome pending"}</div>
            <p className="mt-2 line-clamp-3 text-xs leading-relaxed opacity-85">
              {pressureReduction !== undefined ? `Pressure reduction ${compact(pressureReduction)}` : outcomeLine(props.runTelemetry, props.actualTraining)}
            </p>
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-6">
        {storyline.map((item) => (
          <div key={item.label} className={`rounded border p-3 ${toneClass(item.tone)}`}>
            <div className="text-[10px] font-black uppercase tracking-widest opacity-70">{item.label}</div>
            <div className="mt-2 line-clamp-2 min-h-[2.25rem] text-sm font-black">{item.value}</div>
            <p className="mt-2 line-clamp-4 text-xs leading-relaxed opacity-85">{item.detail}</p>
          </div>
        ))}
      </div>

      <div className="mt-4 rounded-lg border border-slate-800 bg-slate-900 p-3">
        <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Decision audit trail</div>
            <div className="mt-1 text-sm font-black text-slate-100">Rejected options, final rationale, and gate evidence behind the operating decision.</div>
          </div>
          <div className="w-fit rounded bg-slate-950 px-2.5 py-1 text-[10px] font-black uppercase tracking-widest text-cyan-100">
            {reasoningArtifactCount} reasoning artifacts
          </div>
        </div>

        <div className="mt-3 grid gap-3 xl:grid-cols-3">
          <EvidenceColumn title="Agent negotiation" rows={negotiation} />
          <EvidenceColumn title="Policy alignment" rows={policyAlignment} />
          <EvidenceColumn title="Decision rationale" rows={finalDecision} />
        </div>
      </div>
    </section>
  );
}
