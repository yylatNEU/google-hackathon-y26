"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchParkPulseApi, longRunningRequestTimeoutMs } from "@/lib/api";

type ScopePayload = {
  status?: string;
  version?: string;
  default_safety_banner?: string;
  supported_needs?: Array<{ id?: string; label?: string; examples?: string[] }>;
  customer_copy_rules?: string[];
  startLocationOptions?: Array<{
    id?: string;
    name?: string;
    zoneId?: string;
    kind?: string;
    indoor?: boolean;
    covered?: boolean;
    stepFree?: boolean;
  }>;
  llmTools?: Array<{
    name?: string;
    description?: string;
    requiredInputs?: string[];
    guardrails?: string[];
    llmControlAuthority?: boolean;
  }>;
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
  liveState?: {
    source?: string;
    updatedAt?: string;
    zoneCount?: number;
    rideCount?: number;
    foodLocationCount?: number;
    weather?: { condition?: string; stormRisk?: number; heatIndexF?: number };
    readiness?: { accessibilityRoutesOpen?: boolean; firstAidReady?: boolean };
  };
  llmContract?: {
    llmRole?: string;
    plannerAuthority?: string;
    llmControlsRoute?: boolean;
    mayGenerate?: string[];
    mustNotGenerate?: string[];
    availableTools?: string[];
  };
  guestCopy?: {
    status?: string;
    provider?: string;
    model?: string;
    llmStatus?: string;
    llmControlsRoute?: boolean;
    headline?: string;
    message?: string;
    safetyNote?: string;
  };
  memoryPersistence?: {
    status?: string;
    targetCollection?: string;
    memoryId?: string;
    mongoWritePerformedBySpring?: boolean;
    mongoBoundary?: string;
    durablePath?: string;
    requiresHumanReviewBeforeLearning?: boolean;
  };
  clientPackage?: {
    status?: string;
    title?: string;
    subtitle?: string;
    routeSummary?: string;
    startLocation?: string;
    durationMinutes?: number;
    confidenceLabel?: string;
    requiresStaffReview?: boolean;
    reviewReason?: string | null;
    safeLanguage?: string;
    itinerary?: Array<{
      label?: string;
      title?: string;
      location?: string;
      time?: string;
      walk?: string;
      reason?: string;
      accessibilitySummary?: string[];
      needsStaffConfirmation?: boolean;
    }>;
    confirmationChecklist?: Array<{ label?: string; status?: string; owner?: string }>;
    liveContext?: { weather?: string; heatIndexF?: number; routesOpen?: boolean; foodLocations?: number };
    technicalProof?: { planner?: string; llmRole?: string; llmControlsRoute?: boolean; memoryTarget?: string };
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
const fallbackStartLocation = { id: "entrance-plaza", name: "Entrance Plaza", zoneId: "entrancePlaza", kind: "arrival", stepFree: true };

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

function normalizeList(value: string) {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function clampedDuration(value: number) {
  if (!Number.isFinite(value)) return 180;
  return Math.max(45, Math.min(360, Math.round(value)));
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
  const [feedbackStatus, setFeedbackStatus] = useState("");
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
  const startLocationOptions = useMemo(() => {
    const options = (scope?.startLocationOptions ?? []).filter((option) => option.name);
    return options.length ? options : [fallbackStartLocation];
  }, [scope]);
  const selectedStartLocation = startLocationOptions.find((option) => option.name === currentLocation) ?? startLocationOptions[0];
  const clientPackage = journey?.clientPackage;
  const clientItinerary = clientPackage?.itinerary?.length
    ? clientPackage.itinerary
    : (journey?.planSteps ?? []).map((step, index) => ({
      label: `Stop ${index + 1}`,
      title: step.title,
      location: step.location,
      time: step.durationMinutes ? `${step.durationMinutes} min` : "--",
      walk: step.walkMinutes ? `${step.walkMinutes} min walk` : "0 min walk",
      reason: step.why,
      accessibilitySummary: step.accessibility,
      needsStaffConfirmation: Boolean(step.risks?.length),
    }));

  function journeyRequestPayload(locationOverride = currentLocation) {
    const selectedNeeds = Array.from(new Set(needs)).filter(Boolean);
    const location = locationOverride || startLocationOptions[0]?.name || fallbackStartLocation.name;
    return {
      request: request.trim() || defaultRequest,
      needs: selectedNeeds,
      allergies: normalizeList(allergies),
      durationMinutes: clampedDuration(durationMinutes),
      currentLocation: location,
      avoidStairs: selectedNeeds.includes("mobility"),
      indoorBreaks: selectedNeeds.includes("low_sensory"),
      nearRestrooms: true,
      avoidLoudShows: selectedNeeds.includes("low_sensory"),
      minimalWalking: selectedNeeds.includes("mobility"),
    };
  }

  async function refreshScope() {
    try {
      const response = await fetchParkPulseApi("/api/park/accessibility/scope", { timeoutMs: longRunningRequestTimeoutMs });
      const payload = (await response.json()) as ScopePayload;
      setScope(payload);
      const options = (payload.startLocationOptions ?? []).filter((option) => option.name);
      const nextStart = options.find((option) => option.name === currentLocation)?.name ?? options[0]?.name ?? fallbackStartLocation.name;
      setCurrentLocation(nextStart);
      return { payload, currentLocation: nextStart };
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Unable to load accessibility scope.");
      return null;
    }
  }

  async function buildJourney(locationOverride = currentLocation) {
    setIsLoading(true);
    setError("");
    try {
      const response = await fetchParkPulseApi("/api/park/accessibility/journey", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(journeyRequestPayload(locationOverride)),
        timeoutMs: longRunningRequestTimeoutMs,
      });
      setJourney((await response.json()) as JourneyPayload);
      setFeedbackStatus("");
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Unable to build accessibility journey.");
    } finally {
      setIsLoading(false);
    }
  }

  async function recordFeedback(feedbackLabel: string) {
    const memoryId = journey?.memoryPersistence?.memoryId;
    if (!memoryId) {
      setFeedbackStatus("Build a journey before recording feedback.");
      return;
    }
    setFeedbackStatus("Recording feedback");
    try {
      const response = await fetchParkPulseApi("/api/park/accessibility/feedback", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          memoryId,
          feedbackLabel,
          humanReviewed: true,
          reviewer: "accessibility-demo",
        }),
        timeoutMs: longRunningRequestTimeoutMs,
      });
      const payload = (await response.json()) as { status?: string; feedback?: { feedback_label?: string } };
      setFeedbackStatus(payload.status === "recorded" ? `Recorded ${fmt(payload.feedback?.feedback_label)}` : fmt(payload.status));
    } catch (nextError) {
      setFeedbackStatus(nextError instanceof Error ? nextError.message : "Unable to record feedback.");
    }
  }

  useEffect(() => {
    void (async () => {
      const loadedScope = await refreshScope();
      if (loadedScope) {
        await buildJourney(loadedScope.currentLocation);
      }
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

        <section className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[390px_minmax(0,1fr)]">
          <form
            className="min-w-0 space-y-4 rounded border border-slate-800 bg-slate-900 p-4"
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
                <select
                  value={currentLocation}
                  onChange={(event) => setCurrentLocation(event.target.value)}
                  className="mt-2 w-full rounded border border-slate-700 bg-slate-950 p-2 text-sm text-slate-100 outline-none focus:border-teal-300"
                >
                  {startLocationOptions.map((option) => (
                    <option key={option.id ?? option.name} value={option.name}>
                      {option.name}{option.kind ? ` - ${fmt(option.kind)}` : ""}
                    </option>
                  ))}
                </select>
                <span className="mt-1 block text-[11px] font-semibold text-slate-500">
                  {selectedStartLocation?.zoneId ? `Zone ${fmt(selectedStartLocation.zoneId)}` : "Venue Profile start point"}
                </span>
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

          <div className="min-w-0 space-y-4">
            <section className="min-w-0 rounded border border-teal-300/30 bg-slate-900 p-4">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0 max-w-3xl">
                  <div className="text-[10px] font-black uppercase tracking-widest text-teal-300">Client route brief</div>
                  <h2 className="mt-2 text-2xl font-black text-white">{clientPackage?.title ?? journey?.summary?.headline ?? "Accessible route package"}</h2>
                  <p className="mt-3 text-sm leading-relaxed text-slate-300">
                    {clientPackage?.routeSummary ?? journey?.guestCopy?.message ?? "Build a journey to generate a client-ready route brief."}
                  </p>
                </div>
                <div className="grid w-full min-w-0 grid-cols-2 gap-2 text-xs lg:w-auto lg:min-w-72">
                  {[
                    ["Start", fmt(clientPackage?.startLocation ?? journey?.profile?.currentLocation ?? currentLocation)],
                    ["Duration", clientPackage?.durationMinutes ? `${clientPackage.durationMinutes}m` : journey?.summary?.durationMinutes ? `${journey.summary.durationMinutes}m` : "--"],
                    ["Confidence", fmt(clientPackage?.confidenceLabel ?? pct(journey?.summary?.confidence))],
                    ["Staff review", fmt(clientPackage?.requiresStaffReview ?? journey?.summary?.requiresHumanReview)],
                  ].map(([label, value]) => (
                    <div key={label} className="rounded border border-slate-800 bg-slate-950 p-3">
                      <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                      <div className="mt-1 font-black text-slate-100">{value}</div>
                    </div>
                  ))}
                </div>
              </div>

              {(clientPackage?.reviewReason ?? journey?.summary?.reviewReason) ? (
                <div className="mt-4 rounded border border-amber-300/40 bg-amber-300/10 p-3 text-sm font-bold text-amber-100">
                  {clientPackage?.reviewReason ?? journey?.summary?.reviewReason}
                </div>
              ) : null}

              <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(280px,0.8fr)]">
                <div className="space-y-2">
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">Guest itinerary</div>
                  {clientItinerary.slice(0, 5).map((step, index) => (
                    <article key={`${step.label}-${step.location}-${index}`} className="rounded border border-slate-800 bg-slate-950 p-3">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{step.label}</div>
                          <h3 className="mt-1 font-black text-slate-100">{step.title}</h3>
                          <div className="mt-1 text-sm font-bold text-teal-200">{step.location}</div>
                        </div>
                        <div className="text-right text-xs font-bold text-slate-400">{step.time} / {step.walk}</div>
                      </div>
                      <p className="mt-2 text-sm leading-relaxed text-slate-400">{step.reason}</p>
                      <div className="mt-3 flex flex-wrap gap-2">
                        {(step.accessibilitySummary ?? []).slice(0, 3).map((item) => (
                          <span key={item} className="rounded border border-slate-700 px-2 py-1 text-xs font-bold text-slate-300">{item}</span>
                        ))}
                      </div>
                    </article>
                  ))}
                  {!clientItinerary.length ? <div className="rounded border border-slate-800 bg-slate-950 p-4 text-sm text-slate-500">Build a journey to generate the client itinerary.</div> : null}
                </div>

                <div className="space-y-4">
                  <div>
                    <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">Confirmation checklist</div>
                    <div className="mt-2 space-y-2">
                      {(clientPackage?.confirmationChecklist ?? []).map((item) => (
                        <div key={`${item.label}-${item.owner}`} className="rounded border border-slate-800 bg-slate-950 p-3 text-xs">
                          <div className="font-black text-slate-100">{item.label}</div>
                          <div className="mt-1 font-bold text-amber-100">{item.status}</div>
                          <div className="mt-1 text-slate-500">{item.owner}</div>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div>
                    <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">Live context</div>
                    <div className="mt-2 grid gap-2 text-xs">
                      {[
                        ["Weather", clientPackage?.liveContext?.weather ?? fmt(journey?.liveState?.weather?.condition)],
                        ["Routes open", fmt(clientPackage?.liveContext?.routesOpen ?? journey?.liveState?.readiness?.accessibilityRoutesOpen)],
                        ["Food rows", clientPackage?.liveContext?.foodLocations ?? journey?.liveState?.foodLocationCount ?? "--"],
                      ].map(([label, value]) => (
                        <div key={label} className="grid grid-cols-[6rem_1fr] gap-2 rounded border border-slate-800 bg-slate-950 p-2">
                          <div className="font-black uppercase tracking-widest text-slate-500">{label}</div>
                          <div className="font-bold text-slate-300">{value}</div>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs leading-relaxed text-slate-400">
                    {clientPackage?.safeLanguage ?? journey?.guestCopy?.safetyNote ?? scope?.default_safety_banner}
                  </div>
                </div>
              </div>
            </section>

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

            <section className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-2">
              <div className="min-w-0 rounded border border-slate-800 bg-slate-900 p-4">
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

              <div className="min-w-0 rounded border border-slate-800 bg-slate-900 p-4">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">Guardrails</div>
                <div className="mt-3 space-y-2">
                  {(journey?.guardrails ?? scope?.customer_copy_rules ?? []).slice(0, 5).map((rule) => (
                    <div key={rule} className="rounded border border-slate-800 bg-slate-950 p-3 text-sm leading-relaxed text-slate-400">{rule}</div>
                  ))}
                </div>
              </div>
            </section>

            <section className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-2">
              <div className="min-w-0 rounded border border-slate-800 bg-slate-900 p-4">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">Evidence</div>
                <div className="mt-3 space-y-2">
                  {(journey?.evidence ?? []).map((item) => (
                    <div key={item.id ?? item.label} className="min-w-0 overflow-hidden rounded border border-slate-800 bg-slate-950 p-3">
                      <div className="break-words font-black text-slate-100">{item.label ?? item.id}</div>
                      <div className="mt-1 break-all text-xs font-bold text-cyan-200">{item.source}</div>
                      <div className="mt-2 break-words text-xs leading-relaxed text-slate-500">{item.detail}</div>
                    </div>
                  ))}
                  {!journey?.evidence?.length ? <p className="text-sm text-slate-500">No evidence attached yet.</p> : null}
                </div>
              </div>

              <div className="min-w-0 rounded border border-slate-800 bg-slate-900 p-4">
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

            <section className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-2">
              <div className="min-w-0 rounded border border-slate-800 bg-slate-900 p-4">
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

              <div className="min-w-0 rounded border border-slate-800 bg-slate-900 p-4">
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

            <section className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-3">
              <div className="min-w-0 rounded border border-slate-800 bg-slate-900 p-4">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">Live state</div>
                <div className="mt-3 grid gap-2 text-xs">
                  {[
                    ["Source", fmt(journey?.liveState?.source)],
                    ["Zones", journey?.liveState?.zoneCount ?? 0],
                    ["Rides", journey?.liveState?.rideCount ?? 0],
                    ["Food rows", journey?.liveState?.foodLocationCount ?? 0],
                    ["Storm", journey?.liveState?.weather?.stormRisk !== undefined ? `${journey.liveState.weather.stormRisk}%` : "--"],
                    ["Routes open", fmt(journey?.liveState?.readiness?.accessibilityRoutesOpen)],
                  ].map(([label, value]) => (
                    <div key={label} className="grid grid-cols-[6rem_1fr] gap-2 rounded border border-slate-800 bg-slate-950 p-2">
                      <div className="font-black uppercase tracking-widest text-slate-500">{label}</div>
                      <div className="font-bold text-slate-300">{value}</div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="min-w-0 rounded border border-slate-800 bg-slate-900 p-4">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">LLM boundary</div>
                <div className="mt-3 space-y-2 text-xs">
                  <div className="rounded border border-slate-800 bg-slate-950 p-3">
                    <div className="font-black text-slate-100">{fmt(journey?.llmContract?.llmRole)}</div>
                    <div className="mt-1 font-bold text-cyan-200">{fmt(journey?.llmContract?.plannerAuthority)}</div>
                  </div>
                  <div className="rounded border border-slate-800 bg-slate-950 p-3 text-slate-400">Controls route: {fmt(journey?.llmContract?.llmControlsRoute)}</div>
                  <div className="rounded border border-slate-800 bg-slate-950 p-3">
                    <div className="font-black text-slate-100">Tool layer</div>
                    <div className="mt-1 font-bold text-cyan-200">{compact(journey?.llmContract?.availableTools ?? scope?.llmTools?.map((tool) => tool.name ?? "").filter(Boolean), 2)}</div>
                    <div className="mt-2 space-y-1 text-slate-500">
                      {(scope?.llmTools ?? []).slice(0, 4).map((tool) => (
                        <div key={tool.name}>{fmt(tool.name)} / route control {fmt(tool.llmControlAuthority)}</div>
                      ))}
                    </div>
                  </div>
                  <div className="rounded border border-slate-800 bg-slate-950 p-3">
                    <div className="font-black text-slate-100">{fmt(journey?.guestCopy?.provider)}</div>
                    <div className="mt-1 font-bold text-cyan-200">{fmt(journey?.guestCopy?.llmStatus)}</div>
                    <p className="mt-2 text-slate-400">{journey?.guestCopy?.message ?? "Guest copy appears after route generation."}</p>
                    <p className="mt-2 text-slate-500">{journey?.guestCopy?.safetyNote}</p>
                  </div>
                  <div className="rounded border border-slate-800 bg-slate-950 p-3 text-slate-400">May generate: {compact(journey?.llmContract?.mayGenerate, 3)}</div>
                </div>
              </div>

              <div className="min-w-0 rounded border border-slate-800 bg-slate-900 p-4">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">Mongo memory</div>
                <div className="mt-3 space-y-2 text-xs">
                  <div className="rounded border border-slate-800 bg-slate-950 p-3">
                    <div className="font-black text-slate-100">{fmt(journey?.memoryPersistence?.status)}</div>
                    <div className="mt-1 font-bold text-emerald-200">{fmt(journey?.memoryPersistence?.targetCollection)}</div>
                  </div>
                  <div className="rounded border border-slate-800 bg-slate-950 p-3 text-slate-400">Spring wrote Mongo: {fmt(journey?.memoryPersistence?.mongoWritePerformedBySpring)}</div>
                  <div className="rounded border border-slate-800 bg-slate-950 p-3 text-slate-400">Memory id: {fmt(journey?.memoryPersistence?.memoryId)}</div>
                  <div className="rounded border border-slate-800 bg-slate-950 p-3 text-slate-400">Store: {fmt(journey?.memoryPersistence?.durablePath)}</div>
                  <div className="rounded border border-slate-800 bg-slate-950 p-3 text-slate-400">{journey?.memoryPersistence?.mongoBoundary ?? "No memory receipt yet."}</div>
                  <div className="grid grid-cols-2 gap-2">
                    <button
                      type="button"
                      onClick={() => void recordFeedback("guest_completed_route")}
                      className="rounded border border-emerald-300/60 bg-emerald-300/10 px-3 py-2 font-black text-emerald-100 transition hover:bg-emerald-300/20"
                    >
                      Completed
                    </button>
                    <button
                      type="button"
                      onClick={() => void recordFeedback("rerouted_for_accessibility")}
                      className="rounded border border-cyan-300/60 bg-cyan-300/10 px-3 py-2 font-black text-cyan-100 transition hover:bg-cyan-300/20"
                    >
                      Rerouted
                    </button>
                  </div>
                  {feedbackStatus ? <div className="rounded border border-slate-800 bg-slate-950 p-3 font-bold text-slate-300">{feedbackStatus}</div> : null}
                </div>
              </div>
            </section>
          </div>
        </section>
      </div>
    </main>
  );
}
