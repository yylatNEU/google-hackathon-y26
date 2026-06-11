"use client";

import { lazy, Suspense } from "react";
import { ParkStateStrip } from "./ParkStateStrip";
import { humanize, toneClass } from "./style";
import { useCommandCenter } from "./useCommandCenter";

const ReviewLabelPipelinePanel = lazy(() => import("./ReviewLabelPipelinePanel").then((module) => ({ default: module.ReviewLabelPipelinePanel })));
const RoleAccessPanel = lazy(() => import("./RoleAccessPanel").then((module) => ({ default: module.RoleAccessPanel })));
const ProductLoopPanel = lazy(() => import("./ProductLoopPanel").then((module) => ({ default: module.ProductLoopPanel })));
const ActualTrainingPanel = lazy(() => import("./ActualTrainingPanel").then((module) => ({ default: module.ActualTrainingPanel })));
const EvalReceiptPanel = lazy(() => import("./EvalReceiptPanel").then((module) => ({ default: module.EvalReceiptPanel })));

function PanelFallback({ label }: { label: string }) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-950 p-4">
      <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
      <div className="mt-2 h-2 w-full max-w-md overflow-hidden rounded bg-slate-900">
        <div className="h-full w-1/3 rounded bg-cyan-300/70" />
      </div>
    </section>
  );
}

type ProofCommandState = ReturnType<typeof useCommandCenter>;

function compact(value: unknown) {
  if (value === undefined || value === null || value === "") return "--";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  return String(value).replaceAll("_", " ");
}

function confidence(value?: number) {
  if (typeof value !== "number" || Number.isNaN(value)) return "--";
  return value > 1 ? `${Math.round(value)}%` : `${Math.round(value * 100)}%`;
}

function proofTone(status?: string) {
  const normalized = String(status ?? "").toLowerCase();
  if (normalized.includes("block") || normalized.includes("error") || normalized.includes("failed")) return "risk";
  if (normalized.includes("pending") || normalized.includes("unknown") || normalized.includes("deferred") || normalized.includes("waiting")) return "watch";
  return "ok";
}

function ProofSummaryPanel({ command }: { command: ProofCommandState }) {
  const decisionId = command.runTelemetry?.decision_id ?? command.runTelemetry?.trace_contract?.run_id ?? command.runTelemetry?.run_receipt?.id;
  const feedTone = command.feedReliabilityGate.status === "clear" ? "ok" : command.feedReliabilityGate.status === "blocked" ? "risk" : "watch";
  const evalLabel = typeof command.evalScore === "number" ? `${Math.round(command.evalScore)}/100` : "pending";
  const labelStatus = command.reviewLabelPipeline?.status ?? "pending";
  const roleStatus = command.roleAccess?.status ?? "pending";
  const learningStatus = command.actualTraining?.status ?? "pending";
  const nextStep =
    command.feedReliabilityGate.status !== "clear"
      ? "Restore the signal contract before trusting a downstream proof claim."
      : !command.runTelemetry
        ? "Run a park operation case, then return here to inspect the proof package."
        : typeof command.evalScore !== "number"
          ? "Review trace and eval receipts before calling this run fully auditable."
          : "Audit package is ready for trace, policy, eval, and learning review.";

  const cards = [
    {
      label: "Decision trace",
      value: decisionId ?? "Waiting",
      detail: command.selectedAction?.label ?? command.runTelemetry?.operator_response?.headline ?? "No completed decision trace is attached yet.",
      tone: decisionId ? "ok" : "watch",
    },
    {
      label: "Signal contract",
      value: `${humanize(command.feedReliabilityGate.status)} ${command.feedReliabilityGate.score}/100`,
      detail: command.feedReliabilityGate.reasons[0] ?? "Live feed evidence has not reported a reason.",
      tone: feedTone,
    },
    {
      label: "Policy and eval",
      value: `${humanize(command.policyGate ?? "pending")} / ${evalLabel}`,
      detail: command.runTelemetry?.governance?.findings?.[0] ?? `Planner confidence ${confidence(command.runTelemetry?.planner?.confidence_score)}.`,
      tone: proofTone(command.policyGate ?? (typeof command.evalScore === "number" ? "ready" : "pending")),
    },
    {
      label: "Governance evidence",
      value: `${humanize(labelStatus)} / ${humanize(roleStatus)}`,
      detail: `${command.reviewLabelPipeline?.candidates?.length ?? 0} label candidates; ${command.roleAccess?.roles?.length ?? 0} role contracts.`,
      tone: proofTone(labelStatus === "ready" && roleStatus === "ready" ? "ready" : labelStatus),
    },
    {
      label: "Outcome learning",
      value: humanize(learningStatus),
      detail: `Rows ${command.actualTraining?.sample_count ?? 0}/${command.actualTraining?.min_sample_count ?? "--"}; policy ${command.actualTraining?.model?.best_policy_id ?? "pending"}.`,
      tone: proofTone(learningStatus),
    },
  ];

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-950 p-4">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Proof package health</div>
          <h2 className="mt-1 text-2xl font-black text-slate-100">{decisionId ? `Decision ${decisionId}` : "No decision receipt attached yet"}</h2>
          <p className="mt-2 max-w-4xl text-sm leading-relaxed text-slate-400">{nextStep}</p>
        </div>
        <div className={`w-fit rounded border px-3 py-2 text-xs font-black uppercase tracking-widest ${toneClass(feedTone)}`}>
          Evidence {humanize(command.feedReliabilityGate.status)} / {command.feedReliabilityGate.score}/100
        </div>
      </div>

      <div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-5">
        {cards.map((card) => (
          <div key={card.label} className={`rounded border p-3 ${toneClass(card.tone)}`}>
            <div className="text-[10px] font-black uppercase tracking-widest opacity-70">{card.label}</div>
            <div className="mt-2 truncate text-sm font-black">{compact(card.value)}</div>
            <p className="mt-2 line-clamp-3 text-xs leading-relaxed opacity-85">{card.detail}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function ProofSectionIntro({ eyebrow, title, detail }: { eyebrow: string; title: string; detail: string }) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-950 p-4">
      <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">{eyebrow}</div>
      <h2 className="mt-1 text-xl font-black text-slate-100">{title}</h2>
      <p className="mt-2 max-w-4xl text-sm leading-relaxed text-slate-400">{detail}</p>
    </section>
  );
}

export function OperationProofPage() {
  const command = useCommandCenter({ loadProofData: true });

  return (
    <main className="min-h-screen overflow-x-hidden bg-slate-950 px-4 py-5 font-sans text-slate-200 lg:px-8">
      <div className="mx-auto max-w-[1500px] space-y-5">
        <header className="rounded-lg border border-cyan-400/20 bg-slate-900 p-5 shadow-xl shadow-cyan-950/20">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">ParkPulse AI</div>
              <h1 className="mt-2 max-w-5xl text-3xl font-black tracking-normal text-slate-100 lg:text-5xl">Runtime proof</h1>
              <p className="mt-3 max-w-3xl text-sm leading-relaxed text-slate-400">
                Inspect pipeline stages, role authority, review labels, eval receipts, and outcome learning behind the park operating page.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <a href="/ops" className="rounded border border-cyan-300 bg-cyan-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-cyan-200">
                Park operation
              </a>
              <a href="/monitor" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-100">
                Monitor
              </a>
              <a href="/executive" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-100">
                Executive
              </a>
            </div>
          </div>
        </header>

        <ParkStateStrip
          parkState={command.parkState}
          isConnected={command.isConnected}
          isRefreshing={command.isRefreshing}
          lastUpdatedAt={command.lastUpdatedAt}
          liveTick={command.liveTick}
          livePollMs={command.livePollMs}
          connectionError={command.connectionError}
          onRefresh={() => void command.refreshParkState()}
        />

        <ProofSummaryPanel command={command} />

        <Suspense fallback={<PanelFallback label="Loading runtime proof" />}>
          <ProofSectionIntro
            eyebrow="Trace package"
            title="How the operating decision was produced"
            detail="Inspect live signals, feature extraction, candidate actions, optimizer selection, policy gates, agent negotiation, and memory write evidence."
          />

          <ProductLoopPanel
            parkState={command.parkState}
            runTelemetry={command.runTelemetry}
            dispatches={command.dispatches}
            evals={command.activeEvalScores}
            selectedAction={command.selectedAction}
            policyGate={command.policyGate}
            memoryMode={command.memoryMode}
            liveAgentsSmoke={command.liveAgentsSmoke}
          />

          <ProofSectionIntro
            eyebrow="Eval receipt"
            title="Whether the decision can be trusted"
            detail="Review eval scorecards, trace state, memory state, GCP readiness, and operating-loop resilience for the current decision package."
          />

          <EvalReceiptPanel
            evals={command.activeEvalScores}
            telemetry={command.runTelemetry}
            integrationStatus={command.integrationStatus}
            gcpLiveReadiness={command.gcpLiveReadiness}
            operatingLoopResilience={command.operatingLoopResilience}
            evalScore={command.evalScore}
            memoryMode={command.memoryMode}
          />

          <ProofSectionIntro
            eyebrow="Governance evidence"
            title="Who can label, review, and approve proof artifacts"
            detail="Review label candidates and role authority contracts that keep supervised evidence, permissions, and operational decisions separated."
          />

          <ReviewLabelPipelinePanel
            pipeline={command.reviewLabelPipeline}
            isLoading={command.isReviewLabelPipelineLoading}
            onRefresh={() => void command.refreshReviewLabelPipeline()}
            onAutoLabel={() => void command.autoLabelHighConfidenceReviewLabels()}
            onDecision={(candidate, decision, finalLabel) => void command.recordReviewLabelDecision(candidate, decision, finalLabel)}
            canReviewLabels={command.canReviewLabels}
          />

          <RoleAccessPanel
            contracts={command.roleAccess}
            isLoading={command.isRoleAccessLoading}
            onRefresh={() => void command.refreshRoleAccess()}
          />

          <ProofSectionIntro
            eyebrow="Outcome learning"
            title="How observed outcomes update operating policy"
            detail="Inspect reward rows, policy ranking, live episode fitness, and BigQuery ML readiness generated from real operating outcomes."
          />

          <ActualTrainingPanel
            training={command.actualTraining}
            isLoading={command.isTrainingLoading}
            isStartingGcpTraining={command.isStartingGcpTraining}
            onRefresh={() => void command.refreshActualTraining()}
            onStartGcpTraining={() => void command.refreshActualTraining({ runGcpTraining: true })}
            canStartTraining={command.canStartTraining}
          />
        </Suspense>
      </div>
    </main>
  );
}
