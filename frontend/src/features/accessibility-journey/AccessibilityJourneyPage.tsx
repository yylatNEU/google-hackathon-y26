"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchParkPulseApi, longRunningRequestTimeoutMs } from "@/lib/api";

type ScopePayload = {
  status?: string;
  version?: string;
  default_safety_banner?: string;
  supported_needs?: Array<{ id?: string; label?: string; examples?: string[] }>;
  customer_copy_rules?: string[];
  venueProfile?: {
    status?: string;
    source?: string;
    venueIdentity?: { name?: string; profileType?: string };
    readiness?: {
      status?: string;
      counts?: Record<string, number>;
      issues?: Array<{ detail?: string; severity?: string }>;
    };
    sourceIntegrity?: {
      usesApprovedSyntheticProfile?: boolean;
      realVenueFeedConnected?: boolean;
    };
    counts?: Record<string, number>;
    issues?: Array<{ detail?: string; severity?: string }>;
  };
};

type JourneyPayload = {
  status?: string;
  summary?: {
    headline?: string;
    durationMinutes?: number;
    needs?: string[];
    confidence?: number;
    requiresHumanReview?: boolean;
    reviewReason?: string | null;
  };
  profile?: {
    request?: string;
    allergies?: string[];
    currentLocation?: string;
    guestSegmentId?: string;
  };
  planSteps?: Array<{
    id?: string;
    title?: string;
    type?: string;
    location?: string;
    durationMinutes?: number;
    walkMinutes?: number;
    why?: string;
    accessibility?: string[];
    nearby?: string[];
    risks?: string[];
  }>;
  diningOptions?: Array<{
    id?: string;
    name?: string;
    pickupEtaMinutes?: number;
    allergensHandled?: string[];
    lowCrowdSeating?: boolean;
    cautions?: string[];
    staffConfirmationRequired?: boolean;
  }>;
  attractionOptions?: Array<{
    id?: string;
    name?: string;
    waitMins?: number;
    sensoryLoad?: string;
    stepFreeQueue?: boolean;
    transferRequired?: boolean;
    cautions?: string[];
  }>;
  breakPlan?: {
    cadenceMinutes?: number;
    plannedBreakCount?: number;
    preferredBreaks?: Array<{ title?: string; location?: string; durationMinutes?: number }>;
  };
  staffHandoff?: { recommended?: boolean; owner?: string; message?: string };
  guardrails?: string[];
  evidence?: Array<{ id?: string; source?: string; label?: string; detail?: string }>;
  profileIntelligence?: {
    source?: string;
    guestSegmentId?: string;
    segmentNeeds?: {
      preferredPace?: string;
      avoid?: string[];
      requiredHandoff?: string[];
    };
    usedPathRecords?: Array<{
      fromZoneId?: string;
      toZoneId?: string;
      estimatedWalkMinutes?: number;
      certificationStatus?: string;
      allowedUses?: string[];
    }>;
    qualityGaps?: string[];
    modulePolicy?: {
      mayRecommend?: string[];
      mustReview?: string[];
      neverClaim?: string[];
    };
  };
  learningReceipt?: {
    schemaVersion?: string;
    scenarioTaxonomy?: string;
    observation?: {
      guestSegmentId?: string;
      needs?: string[];
      routeZoneIds?: string[];
      staffHandoffRecommended?: boolean;
      qualityGapCount?: number;
    };
    eligibleFeedbackLabels?: string[];
    privacyBoundary?: string;
  };
  readinessIssues?: string[];
  venueProfile?: ScopePayload["venueProfile"];
};

const needOptions = [
  { id: "mobility", label: "Mobility" },
  { id: "low_sensory", label: "Low sensory" },
  { id: "family_care", label: "Family care" },
  { id: "allergy", label: "Allergy" },
  { id: "medical", label: "Medical support" },
];

const defaultRequest =
  "Create a lower-walking, low-sensory three hour route for a family with a stroller, peanut allergy, indoor breaks, and restroom access.";

function fmt(value?: string | number | boolean | null) {
  if (value === undefined || value === null || value === "") return "--";
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value).replaceAll("_", " ");
}

function pct(value?: number) {
  if (value === undefined || value === null) return "--";
  return `${Math.round(value)}%`;
}

function compact(items?: string[], limit = 3) {
  const list = items?.filter(Boolean) ?? [];
  if (!list.length) return "--";
  return `${list.slice(0, limit).join(", ")}${list.length > limit ? ` +${list.length - limit}` : ""}`;
}

export default function AccessibilityJourneyPage() {
  const [scope, setScope] = useState<ScopePayload | null>(null);
  const [journey, setJourney] = useState<JourneyPayload | null>(null);
  const [request, setRequest] = useState(defaultRequest);
  const [durationMinutes, setDurationMinutes] = useState(180);
  const [currentLocation, setCurrentLocation] = useState("Entrance Plaza");
  const [allergies, setAllergies] = useState("peanut");
  const [needs, setNeeds] = useState<string[]>(["mobility", "low_sensory", "family_care", "allergy"]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  const activeNeeds = useMemo(() => new Set(needs), [needs]);
  const activeVenue = journey?.venueProfile ?? scope?.venueProfile;
  const venueStatus = activeVenue?.status ?? activeVenue?.readiness?.status ?? "unknown";
  const venueCounts = activeVenue?.counts ?? activeVenue?.readiness?.counts ?? {};
  const sourceMode = activeVenue?.sourceIntegrity?.usesApprovedSyntheticProfile
    ? "approved synthetic"
    : activeVenue?.sourceIntegrity?.realVenueFeedConnected
      ? "real venue feed"
      : "not connected";

  async function refreshScope() {
    try {
      const response = await fetchParkPulseApi("/api/park/accessibility/scope", { timeoutMs: longRunningRequestTimeoutMs });
      setScope((await response.json()) as ScopePayload);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Unable to load accessibility scope.");
    }
  }

  async function buildJourney() {
    setIsLoading(true);
    setError("");
    try {
      const response = await fetchParkPulseApi("/api/park/accessibility/journey", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          request,
          needs,
          allergies: allergies.split(",").map((item) => item.trim()).filter(Boolean),
          durationMinutes,
          currentLocation,
          avoidStairs: activeNeeds.has("mobility"),
          indoorBreaks: activeNeeds.has("low_sensory"),
          nearRestrooms: true,
          avoidLoudShows: activeNeeds.has("low_sensory"),
          minimalWalking: activeNeeds.has("mobility"),
        }),
        timeoutMs: longRunningRequestTimeoutMs,
      });
      setJourney((await response.json()) as JourneyPayload);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Unable to build accessibility journey.");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void (async () => {
      await refreshScope();
      await buildJourney();
    })();
  }, []);

  return (
    <main className="min-h-screen bg-slate-950 px-4 py-5 text-slate-100 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-7xl space-y-5">
        <header className="grid gap-4 border-b border-slate-800 pb-5 lg:grid-cols-[minmax(0,1fr)_380px] lg:items-end">
          <div>
            <div className="text-[10px] font-black uppercase tracking-widest text-teal-300">ParkPulse guest route planner</div>
            <h1 className="mt-2 text-3xl font-black text-white">Accessibility Journey</h1>
            <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-400">
              Build route suggestions from live park state and the active Venue Profile, with allergy, medical, sensory, and mobility claims gated for staff confirmation.
            </p>
          </div>
          <div className="grid grid-cols-3 gap-2 text-xs">
            {[
              ["Venue", fmt(activeVenue?.venueIdentity?.name ?? venueStatus)],
              ["Locations", venueCounts.locations ?? 0],
              ["Source", sourceMode],
            ].map(([label, value]) => (
              <div key={label} className="rounded border border-slate-800 bg-slate-900 p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                <div className="mt-1 truncate font-black text-slate-100">{value}</div>
              </div>
            ))}
          </div>
        </header>

        {error ? <div className="rounded border border-rose-300/40 bg-rose-300/10 p-3 text-sm font-bold text-rose-100">{error}</div> : null}

        <section className="grid gap-4 lg:grid-cols-[390px_minmax(0,1fr)]">
          <form
            className="space-y-4 rounded border border-slate-800 bg-slate-900 p-4"
            onSubmit={(event) => {
              event.preventDefault();
              void buildJourney();
            }}
          >
            <div>
              <label className="text-[10px] font-black uppercase tracking-widest text-slate-400" htmlFor="journey-request">
                Guest request
              </label>
              <textarea
                id="journey-request"
                value={request}
                onChange={(event) => setRequest(event.target.value)}
                rows={5}
                className="mt-2 w-full rounded border border-slate-700 bg-slate-950 p-3 text-sm leading-relaxed text-slate-100 outline-none transition focus:border-teal-300"
              />
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <label className="text-xs font-bold text-slate-300">
                Start
                <input
                  value={currentLocation}
                  onChange={(event) => setCurrentLocation(event.target.value)}
                  className="mt-2 w-full rounded border border-slate-700 bg-slate-950 p-2 text-sm text-slate-100 outline-none focus:border-teal-300"
                />
              </label>
              <label className="text-xs font-bold text-slate-300">
                Minutes
                <input
                  type="number"
                  min={45}
                  max={360}
                  value={durationMinutes}
                  onChange={(event) => setDurationMinutes(Number(event.target.value))}
                  className="mt-2 w-full rounded border border-slate-700 bg-slate-950 p-2 text-sm text-slate-100 outline-none focus:border-teal-300"
                />
              </label>
            </div>

            <label className="block text-xs font-bold text-slate-300">
              Allergies
              <input
                value={allergies}
                onChange={(event) => setAllergies(event.target.value)}
                className="mt-2 w-full rounded border border-slate-700 bg-slate-950 p-2 text-sm text-slate-100 outline-none focus:border-teal-300"
              />
            </label>

            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">Needs</div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                {needOptions.map((need) => (
                  <label key={need.id} className="flex items-center gap-2 rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-bold text-slate-200">
                    <input
                      type="checkbox"
                      checked={activeNeeds.has(need.id)}
                      onChange={(event) => {
                        setNeeds((current) => event.target.checked ? [...current, need.id] : current.filter((item) => item !== need.id));
                      }}
                      className="h-4 w-4 accent-teal-300"
                    />
                    {need.label}
                  </label>
                ))}
              </div>
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="w-full rounded border border-teal-300 bg-teal-300 px-4 py-3 text-sm font-black text-slate-950 transition hover:bg-teal-200 disabled:opacity-50"
            >
              {isLoading ? "Building route" : "Build accessibility journey"}
            </button>
          </form>

          <div className="space-y-4">
            <section className="rounded border border-slate-800 bg-slate-900 p-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Planner receipt</div>
                  <h2 className="mt-1 text-xl font-black text-white">{journey?.summary?.headline ?? "No journey generated yet"}</h2>
                </div>
                <div className="grid grid-cols-3 gap-2 text-center text-xs">
                  {[
                    ["Confidence", pct(journey?.summary?.confidence)],
                    ["Review", fmt(journey?.summary?.requiresHumanReview)],
                    ["Duration", journey?.summary?.durationMinutes ? `${journey.summary.durationMinutes}m` : "--"],
                  ].map(([label, value]) => (
                    <div key={label} className="rounded border border-slate-800 bg-slate-950 p-2">
                      <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                      <div className="mt-1 font-black text-slate-100">{value}</div>
                    </div>
                  ))}
                </div>
              </div>

              {journey?.summary?.reviewReason ? <p className="mt-3 rounded border border-amber-300/40 bg-amber-300/10 p-3 text-sm font-bold text-amber-100">{journey.summary.reviewReason}</p> : null}

              <div className="mt-4 grid gap-2 text-xs sm:grid-cols-3">
                {[
                  ["Profile", activeVenue?.venueIdentity?.name ?? "--"],
                  ["Readiness", fmt(venueStatus)],
                  ["Feed", sourceMode],
                ].map(([label, value]) => (
                  <div key={label} className="rounded border border-slate-800 bg-slate-950 p-3">
                    <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                    <div className="mt-1 font-black text-slate-100">{value}</div>
                  </div>
                ))}
              </div>

              <div className="mt-4 space-y-3">
                {(journey?.planSteps ?? []).map((step, index) => (
                  <article key={step.id ?? index} className="rounded border border-slate-800 bg-slate-950 p-3">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Step {index + 1}</div>
                        <h3 className="mt-1 font-black text-slate-100">{step.title}</h3>
                        <p className="mt-1 text-sm font-bold text-teal-200">{step.location}</p>
                      </div>
                      <div className="text-right text-xs font-bold text-slate-400">
                        {step.durationMinutes ?? "--"}m plan / {step.walkMinutes ?? "--"}m walk
                      </div>
                    </div>
                    <p className="mt-2 text-sm leading-relaxed text-slate-400">{step.why}</p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {(step.accessibility ?? []).slice(0, 4).map((item) => (
                        <span key={item} className="rounded border border-slate-700 px-2 py-1 text-xs font-bold text-slate-300">{item}</span>
                      ))}
                    </div>
                  </article>
                ))}
                {!journey?.planSteps?.length ? <div className="rounded border border-slate-800 bg-slate-950 p-4 text-sm text-slate-500">Submit a request to generate a venue-bound accessibility journey.</div> : null}
              </div>
            </section>

            <section className="grid gap-4 lg:grid-cols-2">
              <div className="rounded border border-slate-800 bg-slate-900 p-4">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">Dining checks</div>
                <div className="mt-3 space-y-2">
                  {(journey?.diningOptions ?? []).slice(0, 3).map((item) => (
                    <div key={item.id ?? item.name} className="rounded border border-slate-800 bg-slate-950 p-3">
                      <div className="font-black text-slate-100">{item.name}</div>
                      <div className="mt-1 text-xs font-bold text-slate-400">
                        Pickup {item.pickupEtaMinutes ?? "--"}m / Staff confirmation {fmt(item.staffConfirmationRequired)}
                      </div>
                      <div className="mt-2 text-xs text-slate-500">{(item.cautions ?? []).join(" ")}</div>
                    </div>
                  ))}
                  {!journey?.diningOptions?.length ? <p className="text-sm text-slate-500">No dining shortlist yet.</p> : null}
                </div>
              </div>

              <div className="rounded border border-slate-800 bg-slate-900 p-4">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">Guardrails</div>
                <div className="mt-3 space-y-2">
                  {(journey?.guardrails ?? scope?.customer_copy_rules ?? []).slice(0, 5).map((rule) => (
                    <div key={rule} className="rounded border border-slate-800 bg-slate-950 p-3 text-sm leading-relaxed text-slate-400">{rule}</div>
                  ))}
                </div>
              </div>
            </section>

            <section className="grid gap-4 lg:grid-cols-2">
              <div className="rounded border border-slate-800 bg-slate-900 p-4">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">Evidence</div>
                <div className="mt-3 space-y-2">
                  {(journey?.evidence ?? []).map((item) => (
                    <div key={item.id ?? item.label} className="rounded border border-slate-800 bg-slate-950 p-3">
                      <div className="font-black text-slate-100">{item.label ?? item.id}</div>
                      <div className="mt-1 text-xs font-bold text-cyan-200">{item.source}</div>
                      <div className="mt-2 text-xs leading-relaxed text-slate-500">{item.detail}</div>
                    </div>
                  ))}
                  {!journey?.evidence?.length ? <p className="text-sm text-slate-500">No evidence attached yet.</p> : null}
                </div>
              </div>

              <div className="rounded border border-slate-800 bg-slate-900 p-4">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">Staff handoff</div>
                <div className="mt-3 rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="text-sm font-black text-slate-100">{journey?.staffHandoff?.owner ?? "Guest Services"}</div>
                  <div className="mt-1 text-xs font-bold text-slate-400">Recommended {fmt(journey?.staffHandoff?.recommended)}</div>
                  <p className="mt-3 text-sm leading-relaxed text-slate-400">
                    {journey?.staffHandoff?.message ?? "Build a journey to see staff confirmation notes."}
                  </p>
                </div>
              </div>
            </section>

            <section className="grid gap-4 lg:grid-cols-2">
              <div className="rounded border border-slate-800 bg-slate-900 p-4">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">Profile intelligence</div>
                <div className="mt-3 grid gap-2">
                  {[
                    ["Segment", fmt(journey?.profileIntelligence?.guestSegmentId ?? journey?.profile?.guestSegmentId)],
                    ["Pace", fmt(journey?.profileIntelligence?.segmentNeeds?.preferredPace)],
                    ["Avoid", compact(journey?.profileIntelligence?.segmentNeeds?.avoid, 2)],
                    ["Path records", String(journey?.profileIntelligence?.usedPathRecords?.length ?? 0)],
                    ["Quality gaps", String(journey?.profileIntelligence?.qualityGaps?.length ?? 0)],
                    ["Never claim", compact(journey?.profileIntelligence?.modulePolicy?.neverClaim, 2)],
                  ].map(([label, value]) => (
                    <div key={label} className="grid grid-cols-[7rem_1fr] gap-2 rounded border border-slate-800 bg-slate-950 p-2 text-xs">
                      <div className="font-black uppercase tracking-widest text-slate-500">{label}</div>
                      <div className="font-bold text-slate-300">{value}</div>
                    </div>
                  ))}
                </div>
                <div className="mt-3 space-y-2">
                  {(journey?.profileIntelligence?.qualityGaps ?? []).slice(0, 3).map((gap) => (
                    <div key={gap} className="rounded border border-amber-300/30 bg-amber-300/10 p-2 text-xs leading-relaxed text-amber-100">{gap}</div>
                  ))}
                </div>
              </div>

              <div className="rounded border border-slate-800 bg-slate-900 p-4">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">Learning receipt</div>
                <div className="mt-3 rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="text-sm font-black text-slate-100">{fmt(journey?.learningReceipt?.schemaVersion)}</div>
                  <div className="mt-1 text-xs font-bold text-cyan-200">{fmt(journey?.learningReceipt?.scenarioTaxonomy)}</div>
                  <div className="mt-3 grid gap-2 text-xs">
                    <div className="rounded border border-slate-800 p-2 text-slate-400">Route zones: {compact(journey?.learningReceipt?.observation?.routeZoneIds, 5)}</div>
                    <div className="rounded border border-slate-800 p-2 text-slate-400">Feedback labels: {compact(journey?.learningReceipt?.eligibleFeedbackLabels, 4)}</div>
                    <div className="rounded border border-slate-800 p-2 text-slate-400">{journey?.learningReceipt?.privacyBoundary ?? "No learning receipt yet."}</div>
                  </div>
                </div>
              </div>
            </section>
          </div>
        </section>
      </div>
    </main>
  );
}
