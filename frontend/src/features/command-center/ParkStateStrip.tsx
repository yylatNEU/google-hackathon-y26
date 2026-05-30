"use client";

import type { ParkState } from "@/types/park";
import { compactNumber, percent } from "./style";

export function ParkStateStrip({
  parkState,
  isConnected,
  isRefreshing,
  lastUpdatedAt,
  onRefresh,
}: {
  parkState: ParkState;
  isConnected: boolean;
  isRefreshing: boolean;
  lastUpdatedAt: number | null;
  onRefresh: () => void;
}) {
  const simTime = `${String(parkState.simTime.hour).padStart(2, "0")}:${String(parkState.simTime.minute).padStart(2, "0")}`;
  const updated = lastUpdatedAt ? new Date(lastUpdatedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "--";
  const checkedInPct = parkState.staffing.scheduled ? (parkState.staffing.checkedIn / parkState.staffing.scheduled) * 100 : undefined;

  const metrics = [
    { label: "Guests", value: compactNumber(parkState.guestFlow.representedGuests), detail: `${parkState.guestFlow.activeGroups} active groups` },
    { label: "Satisfaction", value: percent(parkState.guestFlow.avgSatisfaction), detail: "guest experience" },
    { label: "Staff checked in", value: percent(checkedInPct), detail: `${parkState.staffing.openCallouts} callouts` },
    { label: "Storm risk", value: percent(parkState.weather.stormRisk), detail: `${parkState.weather.condition}` },
    { label: "Grid load", value: percent(parkState.energy.gridLoadPercent), detail: parkState.energy.demandChargeRisk },
  ];

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-950 p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap items-center gap-2 text-xs font-black uppercase tracking-widest">
          <span className={`h-2.5 w-2.5 rounded-full ${isConnected ? "bg-emerald-300" : "bg-amber-300"}`} />
          <span className={isConnected ? "text-emerald-200" : "text-amber-200"}>{isConnected ? "Live simulation" : "Local fallback"}</span>
          <span className="rounded bg-slate-900 px-2.5 py-1 text-slate-200">Park time {simTime}</span>
          <span className="rounded bg-slate-900 px-2.5 py-1 text-slate-400">Updated {updated}</span>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          disabled={isRefreshing}
          className="w-fit rounded border border-slate-700 bg-slate-900 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-100 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isRefreshing ? "Refreshing" : "Refresh state"}
        </button>
      </div>

      <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
        {metrics.map((metric) => (
          <div key={metric.label} className="rounded border border-slate-800 bg-slate-900 p-3">
            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{metric.label}</div>
            <div className="mt-1 text-2xl font-black text-slate-100">{metric.value}</div>
            <div className="mt-1 truncate text-xs text-slate-500">{metric.detail}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

