"use client";

import type { DispatchView } from "./useCommandCenter";
import { humanize } from "./style";

export function DispatchApprovalPanel({
  dispatches,
  humanApproval,
  isDispatching,
  isApproving,
  onExecute,
  onAcknowledge,
  canExecute,
  canAcknowledge,
}: {
  dispatches: DispatchView[];
  humanApproval: boolean;
  isDispatching: boolean;
  isApproving: boolean;
  onExecute: () => void;
  onAcknowledge: (dispatch: DispatchView, choice: "approved" | "held_for_review" | "acknowledged") => void;
  canExecute: boolean;
  canAcknowledge: boolean;
}) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-950 p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">LLM-drafted receiver payloads</div>
          <h2 className="mt-1 text-xl font-black text-slate-100">{humanApproval ? "Human approval required" : "Bounded dispatch ready"}</h2>
        </div>
        <button
          type="button"
          onClick={onExecute}
          disabled={isDispatching || !canExecute}
          className="w-fit rounded border border-cyan-300 bg-cyan-300 px-4 py-2 text-xs font-black text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isDispatching ? "Sending" : "Send through gate"}
        </button>
      </div>
      {!canExecute && (
        <div className="mt-3 rounded border border-slate-700 bg-slate-900 p-3 text-xs font-bold text-slate-300">
          Signed Ops Team role is required to send live actions through the dispatch gate.
        </div>
      )}

      <div className="mt-4 grid gap-3">
        {dispatches.map((dispatch) => (
          <div key={dispatch.id} className="rounded-lg border border-slate-800 bg-slate-900 p-3">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded bg-slate-950 px-2 py-1 text-[10px] font-black uppercase text-cyan-200">{humanize(dispatch.channel)}</span>
                  <span className="rounded bg-slate-950 px-2 py-1 text-[10px] font-black uppercase text-slate-400">{dispatch.source}</span>
                  {dispatch.status && <span className="rounded bg-slate-950 px-2 py-1 text-[10px] font-black uppercase text-amber-200">{humanize(dispatch.status)}</span>}
                </div>
                <div className="mt-2 text-sm font-black text-slate-100">{dispatch.target}</div>
                <p className="mt-1 text-xs leading-relaxed text-slate-400">{dispatch.body}</p>
                {dispatch.guardrail && <p className="mt-2 text-xs font-bold text-amber-200">{dispatch.guardrail}</p>}
              </div>
              <div className="flex shrink-0 gap-2">
                <button
                  type="button"
                  onClick={() => onAcknowledge(dispatch, "approved")}
                  disabled={isApproving || !canAcknowledge}
                  className="rounded border border-emerald-400 bg-emerald-400 px-3 py-2 text-xs font-black text-slate-950 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Approve
                </button>
                <button
                  type="button"
                  onClick={() => onAcknowledge(dispatch, "held_for_review")}
                  disabled={isApproving || !canAcknowledge}
                  className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-amber-300 hover:text-amber-100 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Hold
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
