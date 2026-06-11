"use client";

import { useEffect, useState } from "react";
import { getApiUrls } from "@/lib/api";
import type { ParkState } from "@/types/park";
import { compactNumber, percent } from "./style";

export function ParkStateStrip({
  parkState,
  isConnected,
  isRefreshing,
  lastUpdatedAt,
  liveTick,
  livePollMs,
  connectionError,
  isLiveLoopRunning,
  onRefresh,
  onStartLiveLoop,
  onStopLiveLoop,
}: {
  parkState: ParkState;
  isConnected: boolean;
  isRefreshing: boolean;
  lastUpdatedAt: number | null;
  liveTick: number;
  livePollMs: number;
  connectionError: string | null;
  isLiveLoopRunning?: boolean;
  onRefresh: () => void;
  onStartLiveLoop?: () => void;
  onStopLiveLoop?: () => void;
}) {
  const [now, setNow] = useState(() => Date.now());
  const simTime = `${String(parkState.simTime.hour).padStart(2, "0")}:${String(parkState.simTime.minute).padStart(2, "0")}`;
  const updated = lastUpdatedAt ? new Date(lastUpdatedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "--";
  const stateAgeMs = lastUpdatedAt ? Math.max(0, now - lastUpdatedAt) : undefined;
  const stateAgeSeconds = stateAgeMs !== undefined ? Math.floor(stateAgeMs / 1000) : undefined;
  const nextPollSeconds = stateAgeMs !== undefined ? Math.max(0, Math.ceil((livePollMs - stateAgeMs) / 1000)) : Math.round(livePollMs / 1000);
  const checkedInPct = parkState.staffing.scheduled ? (parkState.staffing.checkedIn / parkState.staffing.scheduled) * 100 : undefined;
  const apiTargets = getApiUrls().join(", ");
  const runtimeTargetLabel = apiTargets ? "configured" : "not configured";
  const hasLiveLoopControl = Boolean(onStartLiveLoop && onStopLiveLoop);
  const runtimeLabel = hasLiveLoopControl ? (isLiveLoopRunning ? "Live loop running" : "Snapshot mode") : isConnected ? "Live runtime" : "Runtime disconnected";
  const runtimeToneClass = isConnected ? (hasLiveLoopControl && !isLiveLoopRunning ? "text-cyan-200" : "text-emerald-200") : "text-amber-200";
  const runtimeDotClass = isConnected ? (hasLiveLoopControl && !isLiveLoopRunning ? "bg-cyan-300" : "bg-emerald-300") : "bg-amber-300";
  const chaos = parkState.chaosEngine;
  const latestChaos = chaos?.activeUnexpectedEvents?.[0];

  useEffect(() => {
    const intervalId = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(intervalId);
  }, []);

  const metrics = [
    { label: "Guests", value: compactNumber(parkState.guestFlow.representedGuests), detail: `${parkState.guestFlow.activeGroups} active groups` },
    { label: "Satisfaction", value: percent(parkState.guestFlow.avgSatisfaction), detail: "guest experience" },
    { label: "Staff checked in", value: percent(checkedInPct), detail: `${parkState.staffing.openCallouts} callouts` },
    { label: "Storm risk", value: percent(parkState.weather.stormRisk), detail: `${parkState.weather.condition}` },
    {
      label: "Random incidents",
      value: `${chaos?.activeCount ?? 0} active`,
      detail: latestChaos?.kind ? `${latestChaos.kind} ${latestChaos.intensity ?? ""}%; ${chaos?.ruleCount ?? 0} rules` : `${chaos?.ruleCount ?? 0} rules armed`,
    },
  ];

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-950 p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap items-center gap-2 text-xs font-black uppercase tracking-widest">
          <span className={`h-2.5 w-2.5 rounded-full ${runtimeDotClass}`} />
          <span className={runtimeToneClass}>{runtimeLabel}</span>
          <span className="rounded bg-slate-900 px-2.5 py-1 text-slate-200">Park time {simTime}</span>
          <span className="rounded bg-slate-900 px-2.5 py-1 text-slate-400">Updated {updated}</span>
          <span className="rounded bg-slate-900 px-2.5 py-1 text-slate-400">Age {stateAgeSeconds ?? "--"}s</span>
          <span className="rounded bg-slate-900 px-2.5 py-1 text-slate-400">{hasLiveLoopControl && !isLiveLoopRunning ? "Polling paused" : `Next poll ${nextPollSeconds}s`}</span>
          <span className="rounded bg-slate-900 px-2.5 py-1 text-slate-400">Tick {liveTick}</span>
          <span data-testid="api-targets" data-api-targets={apiTargets} className="hidden" />
        </div>
        <div className="flex flex-wrap gap-2">
          {hasLiveLoopControl && (
            <button
              type="button"
              onClick={isLiveLoopRunning ? onStopLiveLoop : onStartLiveLoop}
              className={`w-fit rounded border px-3 py-2 text-xs font-black transition ${
                isLiveLoopRunning ? "border-amber-300 bg-slate-900 text-amber-100 hover:bg-amber-300 hover:text-slate-950" : "border-cyan-300 bg-cyan-300 text-slate-950 hover:bg-cyan-200"
              }`}
            >
              {isLiveLoopRunning ? "Stop live loop" : "Start live loop"}
            </button>
          )}
          <button
            type="button"
            onClick={onRefresh}
            disabled={isRefreshing}
            className="w-fit rounded border border-slate-700 bg-slate-900 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isRefreshing ? "Refreshing" : "Refresh state"}
          </button>
        </div>
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

      {(!isConnected || connectionError) && (
        <div className="mt-3 rounded border border-amber-400/30 bg-amber-950/15 p-3">
          <div className="text-[10px] font-black uppercase tracking-widest text-amber-200">Runtime debug</div>
          <div className="mt-2 grid gap-2 text-xs text-amber-100 md:grid-cols-3">
            <div className="rounded bg-slate-950/40 px-3 py-2">Runtime target: {runtimeTargetLabel}</div>
            <div className="rounded bg-slate-950/40 px-3 py-2">Retry: {Math.round(livePollMs / 1000)}s</div>
            <div className="rounded bg-slate-950/40 px-3 py-2">{connectionError ?? "Waiting for runtime state"}</div>
          </div>
        </div>
      )}
    </section>
  );
}
