"use client";

import type { DemoScenario, RunTelemetry } from "@/types/platform";
import { gateClass, humanize } from "./style";

export function PolicyGatePanel({
  scenario,
  gate,
  governance,
}: {
  scenario: DemoScenario;
  gate?: string;
  governance?: RunTelemetry["governance"];
}) {
  const findings = governance?.findings ?? [];

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-950 p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Policy gate</div>
          <h2 className="mt-1 text-xl font-black text-slate-100">Constraints before dispatch</h2>
        </div>
        <span className={`w-fit rounded border px-3 py-2 text-xs font-black uppercase ${gateClass(gate)}`}>{humanize(gate)}</span>
      </div>

      {!!findings.length && (
        <div className="mt-4 rounded border border-amber-500/40 bg-amber-950/20 p-3">
          <div className="text-[10px] font-black uppercase tracking-widest text-amber-200">Runtime findings</div>
          <ul className="mt-2 space-y-1 text-xs leading-relaxed text-amber-100">
            {findings.slice(0, 4).map((finding) => (
              <li key={finding}>{finding}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {scenario.policies.map((policy) => (
          <div key={`${policy.area}-${policy.rule}`} className="rounded border border-slate-800 bg-slate-900 p-3">
            <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">{policy.area}</div>
            <div className="mt-2 text-sm font-black text-slate-100">{policy.rule}</div>
            <div className="mt-2 text-xs leading-relaxed text-slate-400">{policy.enforcement}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

