"use client";

import { LLM_INTERPRETER_STAGES, PRIMARY_OPERATING_STAGES, PRODUCT_POSITIONING, productToneClass, type ProductLoopStage } from "@/lib/productOperatingModel";
import type { EvalScore, RunTelemetry } from "@/types/platform";
import type { ParkState } from "@/types/park";
import type { DispatchView } from "./useCommandCenter";
import { humanize } from "./style";

type ProductLoopPanelProps = {
  parkState: ParkState | null;
  runTelemetry: RunTelemetry | null;
  dispatches: DispatchView[];
  evals: EvalScore[];
  selectedAction?: RunTelemetry["planner"] extends infer Planner ? Planner extends { selected_action?: infer Action } ? Action : never : never;
  policyGate?: string;
  memoryMode: string;
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
