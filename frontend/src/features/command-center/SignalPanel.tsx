"use client";

import type { DemoScenario } from "@/types/platform";
import type { ParkState } from "@/types/park";
import { toneClass } from "./style";

export function SignalPanel({ scenario, parkState }: { scenario: DemoScenario; parkState: ParkState }) {
  const topRides = [...parkState.guestFlow.rides]
    .sort((left, right) => right.waitMins + right.queueGuests / 20 - (left.waitMins + left.queueGuests / 20))
    .slice(0, 3);

  return (
    <section className="grid gap-4 xl:grid-cols-[1fr_0.9fr]">
      <div className="rounded-lg border border-slate-800 bg-slate-950 p-4">
        <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">What changed</div>
        <h2 className="mt-1 text-2xl font-black text-slate-100">{scenario.title}</h2>
        <p className="mt-2 text-sm leading-relaxed text-slate-400">{scenario.situation}</p>

        <div className="mt-4 grid gap-2 sm:grid-cols-2">
          {scenario.metrics.map((metric) => (
            <div key={metric.label} className={`rounded border p-3 ${toneClass(metric.tone)}`}>
              <div className="text-[10px] font-black uppercase tracking-widest opacity-80">{metric.label}</div>
              <div className="mt-1 text-xl font-black">{metric.value}</div>
              <div className="mt-1 text-xs leading-relaxed opacity-80">{metric.detail}</div>
            </div>
          ))}
        </div>

        <div className="mt-4 grid gap-2">
          {(scenario.experienceModel?.connectedData ?? []).map((item) => (
            <div key={item.source} className="grid gap-2 rounded border border-slate-800 bg-slate-900 p-3 md:grid-cols-[180px_1fr_auto] md:items-center">
              <div className="text-xs font-black text-slate-100">{item.source}</div>
              <div className="text-xs text-slate-400">{item.signal}</div>
              <span className={`w-fit rounded border px-2 py-1 text-[10px] font-black uppercase ${toneClass(item.status === "live" ? "ok" : "watch")}`}>{item.status}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border border-slate-800 bg-slate-950">
        <div className="relative min-h-[280px] bg-slate-900">
          <img src="/park-reference-map.png" alt="Park operating map" className="h-full min-h-[280px] w-full object-cover opacity-80" />
          <div className="absolute inset-x-0 bottom-0 bg-slate-950/85 p-4 backdrop-blur">
            <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Spatial pressure</div>
            <div className="mt-2 grid gap-2">
              {topRides.map((ride) => (
                <div key={ride.id} className="flex items-center justify-between gap-3 rounded border border-slate-800 bg-slate-900/90 px-3 py-2">
                  <div>
                    <div className="text-xs font-black text-slate-100">{ride.name}</div>
                    <div className="text-[11px] text-slate-500">{ride.zoneName}</div>
                  </div>
                  <div className="text-right text-xs font-black text-cyan-100">{ride.waitMins}m / {ride.queueGuests} guests</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

