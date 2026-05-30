"use client";

import type { DemoScenario, RunTelemetry } from "@/types/platform";

export function DecisionPlanPanel({
  scenario,
  selectedAction,
}: {
  scenario: DemoScenario;
  selectedAction?: RunTelemetry["planner"] extends infer Planner ? Planner extends { selected_action?: infer Action } ? Action : never : never;
}) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-950 p-4">
      <div className="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Recommended action</div>
          <h2 className="mt-1 text-xl font-black text-slate-100">{selectedAction?.label ?? scenario.actions[0]?.action ?? "Run the agent to select an action."}</h2>
        </div>
        <div className="rounded border border-slate-800 bg-slate-900 px-3 py-2 text-xs font-black text-slate-300">
          Confidence {Math.round(scenario.confidence * 100)}%
        </div>
      </div>

      <div className="mt-4 grid gap-3">
        {scenario.actions.map((action, index) => (
          <div key={action.action} className="grid gap-3 rounded-lg border border-slate-800 bg-slate-900 p-3 md:grid-cols-[36px_1fr_auto] md:items-start">
            <div className="flex h-8 w-8 items-center justify-center rounded bg-slate-950 text-xs font-black text-cyan-200">{index + 1}</div>
            <div>
              <div className="text-sm font-black text-slate-100">{action.action}</div>
              <div className="mt-1 text-xs leading-relaxed text-slate-400">{action.expectedImpact}</div>
            </div>
            <div className="grid gap-1 text-left text-xs md:text-right">
              <span className="font-black text-slate-100">{action.owner}</span>
              <span className="text-slate-500">{action.deadline}</span>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-4 grid gap-2 md:grid-cols-2">
        {scenario.tradeoffs.map((tradeoff) => (
          <div key={tradeoff.label} className="rounded border border-slate-800 bg-slate-900 p-3">
            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{tradeoff.label}</div>
            <div className="mt-1 text-xs leading-relaxed text-slate-300">{tradeoff.value}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

