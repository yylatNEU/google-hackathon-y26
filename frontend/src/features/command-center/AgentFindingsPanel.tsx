"use client";

import type { AgentBrief } from "@/types/platform";
import { toneClass } from "./style";

export function AgentFindingsPanel({ agentBriefs }: { agentBriefs: AgentBrief[] }) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-950 p-4">
      <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Specialist findings</div>
      <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {agentBriefs.slice(0, 6).map((agent) => (
          <div key={`${agent.name}-${agent.signal}`} className={`rounded-lg border p-3 ${toneClass(agent.tone)}`}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-sm font-black">{agent.name}</div>
                <div className="mt-1 text-[10px] font-black uppercase tracking-widest opacity-70">{agent.signal}</div>
              </div>
              {typeof agent.confidence === "number" && <div className="rounded bg-slate-950/40 px-2 py-1 text-xs font-black">{Math.round(agent.confidence * 100)}%</div>}
            </div>
            <p className="mt-3 text-xs leading-relaxed opacity-85">{agent.finding}</p>
            {agent.recommendation && <p className="mt-2 text-xs font-bold">{agent.recommendation}</p>}
          </div>
        ))}
      </div>
    </section>
  );
}

