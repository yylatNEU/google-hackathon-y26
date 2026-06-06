"use client";

import type {
  LiveFeedHealth,
  LiveFeedRefreshSupervisorResult,
  LiveFoodOpsLoadResult,
  LiveGuestFlowLoadResult,
  LiveOperatorSignalLoadResult,
  LiveRideOpsLoadResult,
  LiveStaffingLoadResult,
  LiveWeatherLoadResult,
  ReviewTrainingLedger,
} from "./useCommandCenter";
import { humanize, toneClass } from "./style";

function fmt(value: unknown) {
  if (value === undefined || value === null || value === "") return "--";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value).replaceAll("_", " ");
}

function statusTone(status?: string) {
  const value = String(status ?? "").toLowerCase();
  if (value.includes("missing") || value.includes("weak") || value.includes("stale") || value.includes("error")) return "risk";
  if (value.includes("review") || value.includes("open")) return "watch";
  return "ok";
}

function ageLabel(seconds?: number | null) {
  if (seconds === undefined || seconds === null) return "--";
  if (seconds < 60) return `${seconds}s`;
  return `${Math.round(seconds / 60)}m`;
}

export function LiveFeedReviewPanel({
  health,
  ledger,
  isLoading,
  isLoadingWeather,
  isLoadingRideOps,
  isLoadingGuestFlow,
  isLoadingStaffing,
  isLoadingFoodOps,
  isLoadingOperatorSignal,
  weatherLoad,
  rideOpsLoad,
  guestFlowLoad,
  staffingLoad,
  foodOpsLoad,
  operatorSignalLoad,
  refreshSupervisor,
  onRefresh,
  onRefreshStale,
  onLoadWeather,
  onLoadRideOps,
  onLoadGuestFlow,
  onLoadStaffing,
  onLoadFoodOps,
  onLoadOperatorSignal,
  onReviewDecision,
  canManageFeeds,
  canReviewCases,
}: {
  health: LiveFeedHealth | null;
  ledger: ReviewTrainingLedger | null;
  isLoading: boolean;
  isLoadingWeather: boolean;
  isLoadingRideOps: boolean;
  isLoadingGuestFlow: boolean;
  isLoadingStaffing: boolean;
  isLoadingFoodOps: boolean;
  isLoadingOperatorSignal: boolean;
  weatherLoad: LiveWeatherLoadResult | null;
  rideOpsLoad: LiveRideOpsLoadResult | null;
  guestFlowLoad: LiveGuestFlowLoadResult | null;
  staffingLoad: LiveStaffingLoadResult | null;
  foodOpsLoad: LiveFoodOpsLoadResult | null;
  operatorSignalLoad: LiveOperatorSignalLoadResult | null;
  refreshSupervisor: LiveFeedRefreshSupervisorResult | null;
  onRefresh: () => void;
  onRefreshStale: () => void;
  onLoadWeather: () => void;
  onLoadRideOps: () => void;
  onLoadGuestFlow: () => void;
  onLoadStaffing: () => void;
  onLoadFoodOps: () => void;
  onLoadOperatorSignal: () => void;
  onReviewDecision: (caseId: string, decision: "approve_for_state" | "request_corroboration" | "hold_for_review" | "escalate") => void;
  canManageFeeds: boolean;
  canReviewCases: boolean;
}) {
  const feeds = health?.feeds ?? [];
  const reviews = health?.open_reviews?.length ? health.open_reviews : ledger?.open_reviews?.length ? ledger.open_reviews : ledger?.rows?.filter((row) => row.status !== "closed").slice(0, 6) ?? [];
  const closedReviews = ledger?.closed_reviews ?? [];
  const refreshedSources = refreshSupervisor?.refreshed_sources ?? [];
  const queuedSources = refreshSupervisor?.queued_sources ?? [];
  const growthLoop = health?.growth_loop ?? [];
  const healthReadinessIssues = health?.readiness_issues ?? [];
  const ledgerReadinessIssues = ledger?.readiness_issues ?? [];
  const summary = health?.summary;
  const ledgerSummary = ledger?.summary;
  const additionalLoads: Array<[string, LiveWeatherLoadResult | null, string]> = [
    ["Latest staffing load", staffingLoad, "text-violet-100"],
    ["Latest food ops load", foodOpsLoad, "text-orange-100"],
    ["Latest operator signal load", operatorSignalLoad, "text-rose-100"],
  ];

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-950 p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Live feeds and review</div>
          <h2 className="mt-1 text-xl font-black text-slate-100">Operational data contract</h2>
          <div className="mt-2 max-w-4xl text-sm leading-relaxed text-slate-400">
            Each feed is normalized before it reaches the decision loop. Stale, sensitive, or low-confidence facts create review cases before they can become trusted training evidence.
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onLoadWeather}
            disabled={isLoadingWeather || !canManageFeeds}
            className="w-fit rounded border border-cyan-300 bg-cyan-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-cyan-200 disabled:opacity-50"
          >
            {isLoadingWeather ? "Loading weather" : "Load weather"}
          </button>
          <button
            type="button"
            onClick={onLoadRideOps}
            disabled={isLoadingRideOps || !canManageFeeds}
            className="w-fit rounded border border-emerald-300 bg-emerald-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-emerald-200 disabled:opacity-50"
          >
            {isLoadingRideOps ? "Loading rides" : "Load rides"}
          </button>
          <button
            type="button"
            onClick={onLoadGuestFlow}
            disabled={isLoadingGuestFlow || !canManageFeeds}
            className="w-fit rounded border border-sky-300 bg-sky-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-sky-200 disabled:opacity-50"
          >
            {isLoadingGuestFlow ? "Loading flow" : "Load flow"}
          </button>
          <button type="button" onClick={onLoadStaffing} disabled={isLoadingStaffing || !canManageFeeds} className="w-fit rounded border border-violet-300 bg-violet-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-violet-200 disabled:opacity-50">
            {isLoadingStaffing ? "Loading staffing" : "Load staffing"}
          </button>
          <button type="button" onClick={onLoadFoodOps} disabled={isLoadingFoodOps || !canManageFeeds} className="w-fit rounded border border-orange-300 bg-orange-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-orange-200 disabled:opacity-50">
            {isLoadingFoodOps ? "Loading food" : "Load food"}
          </button>
          <button type="button" onClick={onLoadOperatorSignal} disabled={isLoadingOperatorSignal || !canManageFeeds} className="w-fit rounded border border-rose-300 bg-rose-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-rose-200 disabled:opacity-50">
            {isLoadingOperatorSignal ? "Loading reports" : "Load reports"}
          </button>
          <button
            type="button"
            onClick={onRefresh}
            disabled={isLoading}
            className="w-fit rounded border border-slate-700 bg-slate-900 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-300 hover:text-cyan-100 disabled:opacity-50"
          >
            {isLoading ? "Refreshing" : "Refresh feeds"}
          </button>
          <button
            type="button"
            onClick={onRefreshStale}
            disabled={isLoading || !canManageFeeds}
            className="w-fit rounded border border-lime-300 bg-lime-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-lime-200 disabled:opacity-50"
          >
            Refresh stale
          </button>
        </div>
      </div>
      {!canManageFeeds && (
        <div className="mt-3 rounded border border-slate-700 bg-slate-900 p-3 text-xs font-bold text-slate-300">
          Signed Ops Team or ML / Ops Admin role is required to load or refresh live feeds.
        </div>
      )}

      <div className="mt-4 grid gap-2 md:grid-cols-5">
        {[
          ["Status", health?.status],
          ["Ready feeds", `${summary?.ready_feed_count ?? 0}/${summary?.required_feed_count ?? 0}`],
          ["Weak feeds", summary?.missing_or_weak_feed_count ?? 0],
          ["Open reviews", summary?.open_review_count ?? ledgerSummary?.open_count ?? 0],
          ["Training candidates", ledgerSummary?.training_candidate_count ?? 0],
        ].map(([label, value]) => (
          <div key={label} className="rounded border border-slate-800 bg-slate-900 p-3">
            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
            <div className="mt-1 truncate text-sm font-black text-cyan-100">{fmt(value)}</div>
          </div>
        ))}
      </div>

      <div className="mt-4 overflow-hidden rounded border border-slate-800">
        <div className="grid grid-cols-[1.1fr_0.7fr_0.7fr_0.7fr_1.4fr] gap-0 bg-slate-900 px-3 py-2 text-[10px] font-black uppercase tracking-widest text-slate-500">
          <div>Feed</div>
          <div>Status</div>
          <div>Age</div>
          <div>Confidence</div>
          <div>Latest signal</div>
        </div>
        <div className="divide-y divide-slate-800">
          {feeds.map((feed, index) => (
            <div key={`${feed.source ?? feed.label ?? "feed"}-${index}`} className="grid grid-cols-[1.1fr_0.7fr_0.7fr_0.7fr_1.4fr] gap-0 bg-slate-950 px-3 py-3 text-xs leading-relaxed">
              <div className="min-w-0 pr-3">
                <div className="truncate font-black text-slate-100">{feed.label ?? humanize(feed.source)}</div>
                <div className="mt-1 truncate text-slate-500">{feed.owner ?? "--"}</div>
              </div>
              <div className="pr-3">
                <span className={`rounded border px-2 py-1 font-black uppercase tracking-widest ${toneClass(statusTone(feed.status))}`}>{fmt(feed.status)}</span>
              </div>
              <div className="pr-3 font-bold text-slate-300">{ageLabel(feed.age_seconds)}</div>
              <div className="pr-3 font-bold text-slate-300">{fmt(feed.confidence)}</div>
              <div className="min-w-0 pr-3">
                <div className="truncate font-bold text-slate-200">{humanize(feed.latest_signal_type)}</div>
                <div className="mt-1 line-clamp-2 text-slate-500">{feed.readiness_issues?.[0] ?? fmt(feed.value)}</div>
              </div>
            </div>
          ))}
          {!feeds.length && <div className="bg-slate-950 p-4 text-sm text-slate-500">No live feed health rows are available yet.</div>}
        </div>
      </div>

      {weatherLoad && (
        <div className="mt-4 rounded border border-slate-800 bg-slate-900 p-3 text-xs leading-relaxed">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Latest weather load</div>
              <div className="mt-1 font-black text-cyan-100">
                {fmt(weatherLoad.status)} / {fmt(weatherLoad.event_count)} events / {fmt(weatherLoad.provider)}
              </div>
            </div>
            <div className={`w-fit rounded border px-2 py-1 font-black uppercase tracking-widest ${toneClass(statusTone(weatherLoad.status))}`}>{fmt(weatherLoad.status)}</div>
          </div>
          <div className="mt-2 text-slate-400">
            {fmt(weatherLoad.fetch?.config?.location_label)} / {fmt(weatherLoad.fetch?.fetched_at ?? weatherLoad.loaded_at)}
          </div>
          {weatherLoad.readiness_issues?.length ? <div className="mt-2 text-amber-100">{weatherLoad.readiness_issues.slice(0, 2).join(" / ")}</div> : null}
        </div>
      )}

      {refreshSupervisor && (
        <div className="mt-4 rounded border border-lime-500/30 bg-lime-950/10 p-3 text-xs leading-relaxed">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Latest stale-feed refresh</div>
              <div className="mt-1 font-black text-lime-100">
                {fmt(refreshSupervisor.status)} / {fmt(refreshedSources.length)} refreshed / {fmt(queuedSources.length)} queued
              </div>
            </div>
            <div className={`w-fit rounded border px-2 py-1 font-black uppercase tracking-widest ${toneClass(statusTone(refreshSupervisor.status))}`}>{fmt(refreshSupervisor.status)}</div>
          </div>
          <div className="mt-2 text-slate-400">
            Before {fmt(refreshSupervisor.before?.ready_feed_count)}/{fmt(refreshSupervisor.before?.required_feed_count)} ready / After {fmt(refreshSupervisor.after?.ready_feed_count)}/{fmt(refreshSupervisor.after?.required_feed_count)} ready
          </div>
          {refreshedSources.length ? <div className="mt-2 text-lime-100">{refreshedSources.map(humanize).join(" / ")}</div> : null}
          {queuedSources.length ? <div className="mt-2 text-sky-100">Queued: {queuedSources.map(humanize).join(" / ")}</div> : null}
          {refreshSupervisor.readiness_issues?.length ? <div className="mt-2 text-amber-100">{refreshSupervisor.readiness_issues.slice(0, 2).join(" / ")}</div> : null}
          {refreshSupervisor.remaining_issues?.length ? <div className="mt-2 text-amber-100">{refreshSupervisor.remaining_issues.slice(0, 3).join(" / ")}</div> : null}
        </div>
      )}

      {rideOpsLoad && (
        <div className="mt-4 rounded border border-slate-800 bg-slate-900 p-3 text-xs leading-relaxed">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Latest ride ops load</div>
              <div className="mt-1 font-black text-emerald-100">
                {fmt(rideOpsLoad.status)} / {fmt(rideOpsLoad.event_count)} events / {fmt(rideOpsLoad.provider)}
              </div>
            </div>
            <div className={`w-fit rounded border px-2 py-1 font-black uppercase tracking-widest ${toneClass(statusTone(rideOpsLoad.status))}`}>{fmt(rideOpsLoad.status)}</div>
          </div>
          <div className="mt-2 text-slate-400">{fmt(rideOpsLoad.fetch?.config?.source ?? rideOpsLoad.fetch?.fetched_at ?? rideOpsLoad.loaded_at)}</div>
          {rideOpsLoad.readiness_issues?.length ? <div className="mt-2 text-amber-100">{rideOpsLoad.readiness_issues.slice(0, 2).join(" / ")}</div> : null}
        </div>
      )}

      {guestFlowLoad && (
        <div className="mt-4 rounded border border-slate-800 bg-slate-900 p-3 text-xs leading-relaxed">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Latest guest flow load</div>
              <div className="mt-1 font-black text-sky-100">
                {fmt(guestFlowLoad.status)} / {fmt(guestFlowLoad.event_count)} events / {fmt(guestFlowLoad.provider)}
              </div>
            </div>
            <div className={`w-fit rounded border px-2 py-1 font-black uppercase tracking-widest ${toneClass(statusTone(guestFlowLoad.status))}`}>{fmt(guestFlowLoad.status)}</div>
          </div>
          <div className="mt-2 text-slate-400">{fmt(guestFlowLoad.fetch?.config?.source ?? guestFlowLoad.fetch?.fetched_at ?? guestFlowLoad.loaded_at)}</div>
          {guestFlowLoad.readiness_issues?.length ? <div className="mt-2 text-amber-100">{guestFlowLoad.readiness_issues.slice(0, 2).join(" / ")}</div> : null}
        </div>
      )}

      {additionalLoads.map(([label, load, color]) =>
        load ? (
          <div key={String(label)} className="mt-4 rounded border border-slate-800 bg-slate-900 p-3 text-xs leading-relaxed">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                <div className={`mt-1 font-black ${color}`}>
                  {fmt(load.status)} / {fmt(load.event_count)} events / {fmt(load.provider)}
                </div>
              </div>
              <div className={`w-fit rounded border px-2 py-1 font-black uppercase tracking-widest ${toneClass(statusTone(load.status))}`}>
                {fmt(load.status)}
              </div>
            </div>
            <div className="mt-2 text-slate-400">{fmt(load.fetch?.config?.source ?? load.fetch?.fetched_at ?? load.loaded_at)}</div>
          </div>
        ) : null,
      )}

      <div className="mt-4 grid gap-3 lg:grid-cols-[1.2fr_0.8fr]">
        <div className="rounded border border-slate-800 bg-slate-900 p-3">
          <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Open review queue</div>
          <div className="mt-3 space-y-2">
            {reviews.slice(0, 5).map((review, index) => (
              <div key={`${review.id ?? review.reason ?? "review"}-${index}`} className="rounded border border-slate-800 bg-slate-950 p-3 text-xs leading-relaxed">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <div className="truncate font-black text-slate-100">{fmt(review.reason)}</div>
                    <div className="mt-1 text-slate-500">
                      {humanize(review.event?.source)} / {humanize(review.event?.signal_type)} / {fmt(review.owner)}
                    </div>
                  </div>
                  <span className={`w-fit rounded border px-2 py-1 font-black uppercase tracking-widest ${toneClass(statusTone(review.priority ?? review.status))}`}>
                    {fmt(review.priority ?? review.status)}
                  </span>
                </div>
                <div className="mt-2 text-slate-400">{review.training_effect ?? "Reviewer disposition is evidence; measured outcomes set reward."}</div>
                {review.id && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {[
                      ["approve_for_state", "Approve"],
                      ["request_corroboration", "Corroborate"],
                      ["hold_for_review", "Hold"],
                      ["escalate", "Escalate"],
                    ].map(([decision, label]) => (
                      <button
                        key={decision}
                        type="button"
                        disabled={isLoading || !canReviewCases}
                        onClick={() => onReviewDecision(review.id ?? "", decision as "approve_for_state" | "request_corroboration" | "hold_for_review" | "escalate")}
                        className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-200 transition hover:border-cyan-300 hover:text-cyan-100 disabled:opacity-50"
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ))}
            {!reviews.length && <div className="rounded border border-slate-800 bg-slate-950 p-3 text-sm text-slate-500">No open review cases from live feed health.</div>}
          </div>
          {closedReviews.length > 0 && (
            <div className="mt-3 rounded border border-slate-800 bg-slate-950 p-3 text-xs leading-relaxed text-slate-400">
              Last closed: {fmt(closedReviews[0]?.reason)} / {fmt(closedReviews[0]?.disposition?.decision)}
            </div>
          )}
        </div>

        <div className="rounded border border-slate-800 bg-slate-900 p-3">
          <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Systematic growth loop</div>
          <div className="mt-3 space-y-2">
            {growthLoop.map((step, index) => (
              <div key={`${index}-${fmt(step)}`} className="flex gap-2 rounded border border-slate-800 bg-slate-950 p-2 text-xs leading-relaxed text-slate-300">
                <span className="font-black text-cyan-200">{index + 1}</span>
                <span>{fmt(step)}</span>
              </div>
            ))}
          </div>
          <div className="mt-3 rounded border border-slate-800 bg-slate-950 p-3 text-xs leading-relaxed text-slate-400">
            {ledger?.training_rule ? fmt(ledger.training_rule) : "Review evidence is collected separately from measured reward."}
          </div>
        </div>
      </div>

      {(healthReadinessIssues.length || ledgerReadinessIssues.length) && (
        <div className="mt-3 rounded border border-amber-400/30 bg-amber-950/15 p-3 text-xs leading-relaxed text-amber-100">
          Debug: {[...healthReadinessIssues, ...ledgerReadinessIssues].slice(0, 3).join(" / ")}
        </div>
      )}
    </section>
  );
}
