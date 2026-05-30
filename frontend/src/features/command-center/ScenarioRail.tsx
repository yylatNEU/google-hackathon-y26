"use client";

import type { DemoScenario, ScenarioKey } from "@/types/platform";
import { toneClass } from "./style";

export function ScenarioRail({
  scenarios,
  selectedScenarioKey,
  onSelect,
}: {
  scenarios: Record<ScenarioKey, DemoScenario>;
  selectedScenarioKey: ScenarioKey;
  onSelect: (scenarioKey: ScenarioKey) => void;
}) {
  return (
    <aside className="rounded-lg border border-slate-800 bg-slate-950 p-3">
      <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">MVP scenarios</div>
      <div className="mt-3 grid gap-2">
        {Object.values(scenarios).slice(0, 3).map((scenario) => {
          const selected = scenario.key === selectedScenarioKey;
          return (
            <button
              key={scenario.key}
              type="button"
              onClick={() => onSelect(scenario.key)}
              className={`rounded-lg border p-3 text-left transition ${
                selected ? "border-cyan-300 bg-cyan-300 text-slate-950" : "border-slate-800 bg-slate-900 text-slate-200 hover:border-cyan-400"
              }`}
            >
              <div className="flex items-center justify-between gap-3">
                <div className="text-xs font-black uppercase tracking-widest opacity-80">{scenario.label}</div>
                <span className={`rounded border px-2 py-1 text-[10px] font-black ${selected ? "border-slate-950/30 bg-slate-950/10" : toneClass(scenario.riskLevel)}`}>
                  {scenario.riskLevel}
                </span>
              </div>
              <div className="mt-2 text-lg font-black">{scenario.title}</div>
              <p className={`mt-2 text-xs leading-relaxed ${selected ? "text-slate-800" : "text-slate-400"}`}>{scenario.situation}</p>
            </button>
          );
        })}
      </div>
    </aside>
  );
}

