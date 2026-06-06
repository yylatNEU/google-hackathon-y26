"use client";

import type { EvalScore, RunTelemetry } from "@/types/platform";
import type { DispatchView, LiveFeedHealth, StartupLoadTiming } from "./useCommandCenter";
import { gateClass, humanize, toneClass } from "./style";

type DecisionBriefPanelProps = {
  runTelemetry: RunTelemetry | null;
  selectedAction?: RunTelemetry["planner"] extends infer Planner ? Planner extends { selected_action?: infer Action } ? Action : never : never;
  policyGate?: string;
  evalScore?: number;
  evals: EvalScore[];
  dispatches: DispatchView[];
  liveFeedHealth: LiveFeedHealth | null;
  isRunning: boolean;
  statusMessage: string | null;
  errorMessage: string | null;
  startupLoadTimings: StartupLoadTiming[];
};

function confidenceLabel(confidence?: number, evalScore?: number) {
  const value = typeof confidence === "number" ? confidence * 100 : evalScore;
  if (typeof value !== "number" || Number.isNaN(value)) return "Pending";
  return `${Math.round(Math.max(0, Math.min(100, value)))}%`;
}

function decisionTone(policyGate?: string, errorMessage?: string | null) {
  const normalized = String(policyGate ?? "").toLowerCase();
  if (errorMessage || normalized.includes("block")) return "risk";
  if (normalized.includes("review") || normalized.includes("pending")) return "watch";
  return "ok";
}

function nextActionLabel({
  selectedAction,
  policyGate,
  isRunning,
  liveFeedHealth,
}: Pick<DecisionBriefPanelProps, "selectedAction" | "policyGate" | "isRunning" | "liveFeedHealth">) {
  if (isRunning) return "Wait for the loop receipt";
  if (selectedAction && String(policyGate ?? "").toLowerCase().includes("review")) return "Review dispatch payloads";
  if (selectedAction) return "Send through gate";
  if ((liveFeedHealth?.summary?.missing_or_weak_feed_count ?? 0) > 0) return "Refresh or review weak feeds";
  return "Run operating loop";
}

function evidenceItems(props: DecisionBriefPanelProps) {
  const items = [
    props.runTelemetry?.operator_response?.summary,
    props.selectedAction?.expected_effect,
    props.runTelemetry?.governance?.findings?.[0],
    props.evals[0] ? `${props.evals[0].label}: ${props.evals[0].score}` : undefined,
    props.liveFeedHealth?.summary
      ? `${props.liveFeedHealth.summary.ready_feed_count ?? 0}/${props.liveFeedHealth.summary.required_feed_count ?? 0} feeds ready`
      : undefined,
    props.dispatches.length ? `${props.dispatches.length} receiver payload${props.dispatches.length === 1 ? "" : "s"} drafted` : undefined,
  ];
  return items.filter((item): item is string => Boolean(item)).slice(0, 4);
}

function timingLabel(ms: number) {
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

function slowestStartupLoads(timings: StartupLoadTiming[]) {
  return [...timings].sort((left, right) => right.elapsedMs - left.elapsedMs).slice(0, 3);
}

function compactValue(value: unknown) {
  if (value === undefined || value === null || value === "") return "--";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function actionSummary(props: DecisionBriefPanelProps) {
  const action = props.selectedAction;
  if (!action) return "Run the operating loop to select a bounded action.";
  const owner = action.owner ? `Owner: ${action.owner}.` : "";
  return [action.action, action.target ? `Target: ${action.target}.` : "", owner, action.expected_effect].filter(Boolean).join(" ");
}

function rejectedSummary(telemetry: RunTelemetry | null) {
  const rejected = telemetry?.trace_contract?.phases?.flatMap((phase) => phase.rejected ?? []) ?? [];
  if (rejected.length) return compactValue(rejected[0]);
  const finding = telemetry?.governance?.findings?.find((item) => /block|reject|unsafe|violation|review/i.test(item));
  return finding ?? "Rejected alternatives appear after the trace contract records them.";
}

function evidenceSummary(props: DecisionBriefPanelProps) {
  const liveEvidence = props.runTelemetry?.live_feed_case?.evidence?.[0]?.summary;
  const phaseEvidence = props.runTelemetry?.trace_contract?.phases?.find((phase) => phase.evidence)?.evidence;
  const evalDetail = props.evals[0] ? `${props.evals[0].label} ${props.evals[0].score}` : undefined;
  return liveEvidence ?? phaseEvidence ?? evalDetail ?? "Evidence appears after feeds load or the operating loop completes.";
}

function dispatchSummary(dispatches: DispatchView[], telemetry: RunTelemetry | null) {
  const acknowledged = telemetry?.live_feed_receiver_delivery?.acknowledged_count;
  const delivered = telemetry?.live_feed_receiver_delivery?.delivered_count;
  if (delivered !== undefined || acknowledged !== undefined) return `${delivered ?? 0} delivered / ${acknowledged ?? 0} acknowledged`;
  if (dispatches.length) return `${dispatches.length} payload${dispatches.length === 1 ? "" : "s"} drafted`;
  return "No receiver payload drafted yet.";
}

function receiptSummary(props: DecisionBriefPanelProps) {
  const id = props.runTelemetry?.decision_id ?? props.runTelemetry?.trace_contract?.run_id ?? props.runTelemetry?.outcome_id;
  const score = typeof props.evalScore === "number" ? `Eval ${Math.round(props.evalScore)}` : "Eval pending";
  const memory = props.runTelemetry?.memory?.mode ? `Memory ${props.runTelemetry.memory.mode}` : "Memory pending";
  return [id ? `Receipt ${id}` : "Receipt pending", score, memory].join(" / ");
}

function reviewSteps(props: DecisionBriefPanelProps) {
  const gate = props.policyGate ?? props.runTelemetry?.governance?.gate_status ?? "pending";
  return [
    { label: "Recommendation", value: props.selectedAction?.label ?? "No selected action yet", detail: actionSummary(props), tone: props.selectedAction ? "ok" : "watch" },
    { label: "Why", value: confidenceLabel(props.runTelemetry?.planner?.confidence_score, props.evalScore), detail: evidenceSummary(props), tone: props.evals.length || props.runTelemetry?.live_feed_case ? "ok" : "watch" },
    { label: "Rejected / blocked", value: humanize(gate), detail: rejectedSummary(props.runTelemetry), tone: String(gate).toLowerCase().includes("block") ? "risk" : "watch" },
    { label: "Gate", value: humanize(gate), detail: props.runTelemetry?.governance?.findings?.[0] ?? "Policy gate appears after a run.", tone: decisionTone(gate, null) },
    { label: "Dispatch", value: dispatchSummary(props.dispatches, props.runTelemetry), detail: props.dispatches[0]?.body ?? "Review receiver payloads before execution.", tone: props.dispatches.length ? "ok" : "watch" },
    { label: "Receipt", value: receiptSummary(props), detail: props.runTelemetry?.eval?.scorecard?.status ?? "Decision, eval, and memory receipt appears after completion.", tone: props.runTelemetry?.decision_id || props.runTelemetry?.outcome_id ? "ok" : "watch" },
  ];
}

export function DecisionBriefPanel(props: DecisionBriefPanelProps) {
  const confidence = confidenceLabel(props.runTelemetry?.planner?.confidence_score, props.evalScore);
  const tone = decisionTone(props.policyGate, props.errorMessage);
  const selectedLabel = props.selectedAction?.label ?? props.runTelemetry?.operator_response?.headline ?? "No controlled action selected yet";
  const target = props.selectedAction?.target ?? props.runTelemetry?.request?.scenario_key ?? "current park state";
  const nextAction = nextActionLabel(props);
  const evidence = evidenceItems(props);
  const slowestLoads = slowestStartupLoads(props.startupLoadTimings);
  const steps = reviewSteps(props);

  return (
    <section className={`rounded-lg border p-4 ${toneClass(tone)}`}>
      <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr] xl:items-start">
        <div>
          <div className="text-[10px] font-black uppercase tracking-widest opacity-75">Decision brief</div>
          <h2 className="mt-2 text-2xl font-black tracking-normal">{props.isRunning ? "Operating loop is running" : selectedLabel}</h2>
          <p className="mt-2 max-w-4xl text-sm leading-relaxed opacity-85">
            {props.errorMessage ?? props.statusMessage ?? props.selectedAction?.action ?? "Run the loop to produce a policy-gated recommendation, evidence, dispatch draft, and eval receipt."}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <span className="rounded bg-slate-950/45 px-2.5 py-1 text-[10px] font-black uppercase tracking-widest">Target: {humanize(String(target))}</span>
            <span className={`rounded border px-2.5 py-1 text-[10px] font-black uppercase tracking-widest ${gateClass(props.policyGate)}`}>
              Gate: {humanize(props.policyGate ?? "pending")}
            </span>
            <span className="rounded bg-slate-950/45 px-2.5 py-1 text-[10px] font-black uppercase tracking-widest">Confidence: {confidence}</span>
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-1">
          <div className="rounded border border-slate-950/30 bg-slate-950/35 p-3">
            <div className="text-[10px] font-black uppercase tracking-widest opacity-65">Next action</div>
            <div className="mt-1 text-lg font-black">{nextAction}</div>
          </div>
          <div className="rounded border border-slate-950/30 bg-slate-950/35 p-3">
            <div className="text-[10px] font-black uppercase tracking-widest opacity-65">Evidence to verify</div>
            <div className="mt-2 space-y-1.5">
              {evidence.length ? (
                evidence.map((item) => (
                  <div key={item} className="truncate rounded bg-slate-950/40 px-2 py-1 text-[11px] font-bold opacity-90">
                    {item}
                  </div>
                ))
              ) : (
                <div className="text-xs font-bold opacity-80">Evidence appears after feeds load or the operating loop completes.</div>
              )}
            </div>
          </div>
          <div className="rounded border border-slate-950/30 bg-slate-950/35 p-3 md:col-span-2 xl:col-span-1">
            <div className="text-[10px] font-black uppercase tracking-widest opacity-65">Startup timing</div>
            <div className="mt-2 space-y-1.5">
              {slowestLoads.length ? (
                slowestLoads.map((item) => (
                  <div key={item.id} className="flex items-center justify-between gap-3 rounded bg-slate-950/40 px-2 py-1 text-[11px] font-bold opacity-90">
                    <span className="truncate">{item.label}</span>
                    <span className="shrink-0">
                      {timingLabel(item.elapsedMs)}
                      {item.status === "deferred" ? " deferred" : ""}
                    </span>
                  </div>
                ))
              ) : (
                <div className="text-xs font-bold opacity-80">Measuring initial panel loads.</div>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="mt-4 rounded border border-slate-950/30 bg-slate-950/30 p-3">
        <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="text-[10px] font-black uppercase tracking-widest opacity-65">Operator review path</div>
            <div className="mt-1 text-sm font-black">Verify recommendation, evidence, gate, dispatch, and receipt before action.</div>
          </div>
          <div className="w-fit rounded bg-slate-950/45 px-2.5 py-1 text-[10px] font-black uppercase tracking-widest opacity-90">
            {props.runTelemetry ? "Receipt loaded" : "Waiting for run"}
          </div>
        </div>

        <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {steps.map((step) => (
            <div key={step.label} className={`rounded border p-3 ${toneClass(step.tone)}`}>
              <div className="flex items-start justify-between gap-2">
                <div className="text-[10px] font-black uppercase tracking-widest opacity-70">{step.label}</div>
                <div className="rounded bg-slate-950/45 px-2 py-1 text-[10px] font-black uppercase opacity-85">{step.tone === "ok" ? "ready" : step.tone}</div>
              </div>
              <div className="mt-2 truncate text-sm font-black">{step.value}</div>
              <p className="mt-2 line-clamp-3 text-xs leading-relaxed opacity-85">{step.detail}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
