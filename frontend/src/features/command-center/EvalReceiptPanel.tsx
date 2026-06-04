"use client";

import type { EvalScore, GcpLiveReadinessStatus, IntegrationStatus, RunTelemetry } from "@/types/platform";
import { humanize } from "./style";

export function EvalReceiptPanel({
  evals,
  telemetry,
  integrationStatus,
  gcpLiveReadiness,
  evalScore,
  memoryMode,
}: {
  evals: EvalScore[];
  telemetry: RunTelemetry | null;
  integrationStatus: IntegrationStatus | null;
  gcpLiveReadiness: GcpLiveReadinessStatus | null;
  evalScore?: number;
  memoryMode: string;
}) {
  const decisionId = telemetry?.decision_id ?? telemetry?.trace_contract?.memory_write?.decision_id ?? telemetry?.trace_contract?.run_id ?? telemetry?.run_receipt?.id;
  const traceState = telemetry?.eval?.gcp_trace_eval?.trace_state ?? integrationStatus?.gcp_trace_eval?.trace?.runtime ?? "local";
  const mongoState = integrationStatus?.mongo?.connected ? "connected" : memoryMode;
  const readinessStatus = gcpLiveReadiness?.status ?? "unknown";
  const readinessSummary = gcpLiveReadiness?.summary;
  const readinessTone =
    readinessStatus === "live_ready"
      ? "border-emerald-400 bg-emerald-400 text-slate-950"
      : readinessStatus === "wired_not_live"
        ? "border-amber-300 bg-amber-300 text-slate-950"
        : "border-slate-700 bg-slate-900 text-slate-200";

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-950 p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Outcome, eval, and training receipt</div>
          <h2 className="mt-1 text-xl font-black text-slate-100">Proof and learning record</h2>
        </div>
        <div className="rounded border border-slate-800 bg-slate-900 px-4 py-3 text-right">
          <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Overall</div>
          <div className="text-3xl font-black text-cyan-100">{typeof evalScore === "number" ? Math.round(evalScore) : "--"}</div>
        </div>
      </div>

      <div className="mt-4 grid gap-2 sm:grid-cols-4">
        <ReceiptMetric label="Decision" value={decisionId ?? "--"} />
        <ReceiptMetric label="Trace" value={humanize(traceState)} />
        <ReceiptMetric label="Memory" value={humanize(mongoState)} />
        <div className={`rounded border p-3 ${readinessTone}`}>
          <div className="text-[10px] font-black uppercase tracking-widest opacity-70">GCP proof</div>
          <div className="mt-1 text-xs font-black">{humanize(readinessStatus)}</div>
          <div className="mt-1 text-[11px] font-bold opacity-80">
            {readinessSummary ? `${readinessSummary.live ?? 0} live / ${readinessSummary.mocked ?? 0} mocked / ${readinessSummary.skipped ?? 0} skipped` : "--"}
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {evals.slice(0, 9).map((item) => (
          <div key={item.label} className="rounded border border-slate-800 bg-slate-900 p-3">
            <div className="flex items-start justify-between gap-3">
              <div className="text-sm font-black text-slate-100">{item.label}</div>
              <div className="text-lg font-black text-cyan-100">{item.score}</div>
            </div>
            <div className="mt-2 h-1.5 overflow-hidden rounded bg-slate-800">
              <div className="h-full rounded bg-cyan-300" style={{ width: `${Math.max(0, Math.min(100, item.score))}%` }} />
            </div>
            <p className="mt-2 text-xs leading-relaxed text-slate-400">{item.detail}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function ReceiptMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-slate-800 bg-slate-900 p-3">
      <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
      <div className="mt-1 truncate text-xs font-black text-slate-100">{value}</div>
    </div>
  );
}
