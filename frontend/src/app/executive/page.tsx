"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParkPulseState } from "@/hooks/useParkPulseState";
import { fetchParkPulseApi } from "@/lib/api";

type EnterpriseDomain = {
  id?: string;
  label?: string;
  score?: number;
  status?: string;
  agent?: string;
  current?: string;
  target?: string;
  recommendedMove?: string;
  ticketsOpen?: number;
  leadingSignals?: string[];
};

type BacklogIssue = {
  id?: string;
  executiveDomain?: string;
  domain?: string;
  title?: string;
  severity?: string;
  current?: string;
  target?: string;
  businessImpact?: string;
  recommendedNext?: string;
  evidence?: string[];
};

type BacklogPayload = {
  status?: string;
  unresolvedCount?: number;
  enterpriseDomains?: EnterpriseDomain[];
  enterpriseSummary?: {
    weakestDomain?: EnterpriseDomain;
    executiveQuestion?: string;
    answer?: string;
  };
  issues?: BacklogIssue[];
};

type IncidentTicket = {
  id?: string;
  source?: string;
  domain?: string;
  title?: string;
  severity?: string;
  status?: string;
  summary?: string;
  recommendedHumanCall?: string;
  evidence?: string[];
};

type IncidentPayload = {
  summary?: {
    ticketCount?: number;
    humanReviewCount?: number;
    topDomains?: Array<[string, number]>;
  };
  tickets?: IncidentTicket[];
  mongoPersistence?: {
    status?: string;
    mode?: string;
    connected?: boolean;
    ticketCount?: number;
    operatorBriefId?: string | null;
  };
};

function score(value?: number) {
  return typeof value === "number" ? `${Math.round(value)}/100` : "--";
}

function pct(value?: number) {
  return typeof value === "number" ? `${Math.round(value)}%` : "--";
}

function StatusPill({ value }: { value?: string }) {
  const lower = (value ?? "").toLowerCase();
  const tone = lower.includes("block") || lower.includes("critical")
    ? "border-red-400/40 bg-red-950/25 text-red-100"
    : lower.includes("review") || lower.includes("degraded") || lower.includes("watch")
      ? "border-amber-400/40 bg-amber-950/20 text-amber-100"
      : "border-emerald-400/35 bg-emerald-950/20 text-emerald-100";
  return <span className={`rounded border px-2 py-1 text-[10px] font-black uppercase tracking-widest ${tone}`}>{value ?? "--"}</span>;
}

export default function ExecutivePage() {
  const { parkState, isConnected, isRefreshing, connectionError, refreshParkState } = useParkPulseState();
  const [backlog, setBacklog] = useState<BacklogPayload | null>(null);
  const [incidents, setIncidents] = useState<IncidentPayload | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadExecutiveData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [backlogResponse, incidentResponse] = await Promise.all([
        fetchParkPulseApi("/api/park/operational-backlog", { timeoutMs: 8000 }),
        fetchParkPulseApi("/api/park/incident-analytics", { timeoutMs: 8000 }),
      ]);
      setBacklog((await backlogResponse.json()) as BacklogPayload);
      setIncidents((await incidentResponse.json()) as IncidentPayload);
    } catch (err) {
      setBacklog(null);
      setIncidents(null);
      setError(err instanceof Error ? err.message : "Unable to load executive runtime data.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadExecutiveData();
  }, [loadExecutiveData]);

  const domains = backlog?.enterpriseDomains ?? [];
  const issues = backlog?.issues ?? [];
  const tickets = incidents?.tickets ?? [];

  const livePressure = useMemo(() => {
    const topZone = [...parkState.guestFlow.zones].sort((left, right) => right.density - left.density)[0];
    const topRide = [...parkState.guestFlow.rides].sort((left, right) => right.waitMins - left.waitMins)[0];
    return { topZone, topRide };
  }, [parkState.guestFlow.rides, parkState.guestFlow.zones]);

  const kpis = [
    ["Runtime", isConnected ? "live" : "disconnected"],
    ["Guests", parkState.guestFlow.representedGuests ? parkState.guestFlow.representedGuests.toLocaleString() : "--"],
    ["Satisfaction", pct(parkState.guestFlow.avgSatisfaction)],
    ["Staff ready", pct(parkState.parkOps.staffReadyPct)],
    ["Open tickets", String(incidents?.summary?.ticketCount ?? "--")],
    ["Backlog", String(backlog?.unresolvedCount ?? "--")],
  ];

  return (
    <main className="min-h-screen bg-slate-950 px-4 py-5 font-sans text-slate-200 lg:px-8">
      <div className="mx-auto max-w-[1500px] space-y-5">
        <header className="rounded-lg border border-slate-800 bg-slate-900 p-5">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Executive runtime</div>
              <h1 className="mt-2 text-3xl font-black text-slate-100 lg:text-4xl">Business view of the operating loop</h1>
              <p className="mt-3 max-w-4xl text-sm leading-relaxed text-slate-400">
                This view reads live park state, operational backlog, and incident analytics. Missing backend data is shown as a debug state, not replaced with local business content.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => {
                  void refreshParkState();
                  void loadExecutiveData();
                }}
                disabled={isRefreshing || isLoading}
                className="rounded border border-cyan-400/60 bg-cyan-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-cyan-200 disabled:opacity-50"
              >
                {isRefreshing || isLoading ? "Refreshing" : "Refresh runtime"}
              </button>
              <a href="/" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-100">
                Operating loop
              </a>
              <a href="/monitor" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-100">
                Monitor
              </a>
            </div>
          </div>
        </header>

        {(error || connectionError) && (
          <section className="rounded border border-amber-400/30 bg-amber-950/15 p-3 text-sm font-bold text-amber-100">
            Runtime debug: {error ?? connectionError}
          </section>
        )}

        <section className="grid gap-2 md:grid-cols-6">
          {kpis.map(([label, value]) => (
            <div key={label} className="rounded border border-slate-800 bg-slate-900 p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
              <div className="mt-1 truncate text-sm font-black text-cyan-100">{value}</div>
            </div>
          ))}
        </section>

        <section className="grid gap-5 xl:grid-cols-[1fr_1fr]">
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="text-[10px] font-black uppercase tracking-widest text-emerald-300">Live operating pressure</div>
            <h2 className="mt-1 text-xl font-black text-slate-100">{livePressure.topZone?.name ?? "No zone payload returned"}</h2>
            <div className="mt-4 grid gap-2 md:grid-cols-2">
              {[
                ["Top zone density", pct(livePressure.topZone?.density)],
                ["Top zone wait", livePressure.topZone?.waitMins === undefined ? "--" : `${livePressure.topZone.waitMins}m`],
                ["Top ride", livePressure.topRide?.name ?? "--"],
                ["Top ride wait", livePressure.topRide?.waitMins === undefined ? "--" : `${livePressure.topRide.waitMins}m`],
                ["Storm risk", pct(parkState.weather.stormRisk)],
                ["Grid load", pct(parkState.energy.gridLoadPercent)],
              ].map(([label, value]) => (
                <div key={label} className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                  <div className="mt-1 truncate text-sm font-black text-slate-100">{value}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Executive answer</div>
            <h2 className="mt-1 text-xl font-black text-slate-100">{backlog?.enterpriseSummary?.executiveQuestion ?? "No executive summary returned"}</h2>
            <p className="mt-3 text-sm leading-relaxed text-slate-400">{backlog?.enterpriseSummary?.answer ?? "The backend has not returned an executive answer for the current operating state."}</p>
            <div className="mt-4 rounded border border-slate-800 bg-slate-950 p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Weakest domain</div>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <span className="text-sm font-black text-slate-100">{backlog?.enterpriseSummary?.weakestDomain?.label ?? "--"}</span>
                <StatusPill value={backlog?.enterpriseSummary?.weakestDomain?.status} />
                <span className="text-xs font-bold text-slate-500">{score(backlog?.enterpriseSummary?.weakestDomain?.score)}</span>
              </div>
            </div>
          </div>
        </section>

        <section className="grid gap-5 xl:grid-cols-3">
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4 xl:col-span-2">
            <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Enterprise domains</div>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              {domains.length ? (
                domains.map((domain) => (
                  <div key={domain.id ?? domain.label} className="rounded border border-slate-800 bg-slate-950 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="truncate text-sm font-black text-slate-100">{domain.label ?? domain.id ?? "domain"}</div>
                      <StatusPill value={domain.status} />
                    </div>
                    <div className="mt-2 grid gap-1 text-xs text-slate-500">
                      <div>Agent: <span className="font-bold text-slate-300">{domain.agent ?? "--"}</span></div>
                      <div>Score: <span className="font-bold text-slate-300">{score(domain.score)}</span></div>
                      <div>Tickets: <span className="font-bold text-slate-300">{domain.ticketsOpen ?? "--"}</span></div>
                    </div>
                    <p className="mt-2 line-clamp-3 text-xs leading-relaxed text-slate-400">{domain.recommendedMove ?? "No runtime recommendation returned."}</p>
                  </div>
                ))
              ) : (
                <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs text-slate-500 md:col-span-2">No enterprise domain payload returned.</div>
              )}
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="text-[10px] font-black uppercase tracking-widest text-violet-300">Persistence</div>
            <div className="mt-3 grid gap-2">
              {[
                ["Mongo status", incidents?.mongoPersistence?.status ?? "--"],
                ["Mongo mode", incidents?.mongoPersistence?.mode ?? "--"],
                ["Connected", incidents?.mongoPersistence?.connected === undefined ? "--" : incidents.mongoPersistence.connected ? "yes" : "no"],
                ["Ticket count", String(incidents?.mongoPersistence?.ticketCount ?? "--")],
                ["Operator brief", incidents?.mongoPersistence?.operatorBriefId ?? "--"],
              ].map(([label, value]) => (
                <div key={label} className="grid grid-cols-[7rem_1fr] gap-3 rounded border border-slate-800 bg-slate-950 px-3 py-2 text-xs">
                  <div className="font-black uppercase tracking-widest text-slate-500">{label}</div>
                  <div className="truncate font-bold text-slate-100">{value}</div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="grid gap-5 xl:grid-cols-[1fr_1fr]">
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="text-[10px] font-black uppercase tracking-widest text-amber-300">Open backlog</div>
            <div className="mt-3 grid gap-2">
              {issues.length ? (
                issues.slice(0, 7).map((issue) => (
                  <div key={issue.id} className="rounded border border-slate-800 bg-slate-950 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="truncate text-sm font-black text-slate-100">{issue.title ?? issue.id}</div>
                      <StatusPill value={issue.severity} />
                    </div>
                    <p className="mt-2 line-clamp-2 text-xs text-slate-500">{issue.recommendedNext ?? issue.businessImpact ?? "No issue detail returned."}</p>
                  </div>
                ))
              ) : (
                <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs text-slate-500">No backlog issues returned.</div>
              )}
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="text-[10px] font-black uppercase tracking-widest text-red-300">Incident tickets</div>
            <div className="mt-3 grid gap-2">
              {tickets.length ? (
                tickets.slice(0, 7).map((ticket) => (
                  <div key={ticket.id} className="rounded border border-slate-800 bg-slate-950 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="truncate text-sm font-black text-slate-100">{ticket.title ?? ticket.id}</div>
                      <StatusPill value={ticket.severity ?? ticket.status} />
                    </div>
                    <p className="mt-2 line-clamp-2 text-xs text-slate-500">{ticket.recommendedHumanCall ?? ticket.summary ?? "No ticket detail returned."}</p>
                  </div>
                ))
              ) : (
                <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs text-slate-500">No incident tickets returned.</div>
              )}
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
