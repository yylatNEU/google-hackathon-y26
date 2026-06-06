"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchParkPulseApi } from "@/lib/api";

type VenueLocationDetail = {
  name?: string;
  kind?: string;
  zoneId?: string;
  category?: string;
  thrillLevel?: string;
  durationMinutes?: number;
  heightRequirementInches?: number | null;
  indoor?: boolean;
  covered?: boolean;
  familyFit?: string;
  accessibilityNote?: string;
  sensoryNote?: string;
  cuisine?: string;
  seating?: string;
  dietaryTags?: string[];
  bestFor?: string[];
  accessible?: boolean;
  familyRoom?: boolean;
  guestInstruction?: string;
  services?: string[];
};

type VenueProfilePayload = {
  mode?: string;
  status?: string;
  message?: string;
  venueIdentity?: {
    venueId?: string;
    name?: string;
    profileType?: string;
    description?: string;
    primaryAudiences?: string[];
    publicZones?: Array<{ id?: string; name?: string; position?: string }>;
  } | null;
  readiness?: {
    status?: string;
    autofillAllowed?: boolean;
    handoffReady?: boolean;
    loadedFrom?: string | null;
    counts?: Record<string, number>;
    issues?: VenueProfileIssue[];
  };
  realInputs?: {
    source?: string;
    safetyInstructions?: string[];
    channelOwners?: Record<string, string>;
    locationDetails?: Record<string, VenueLocationDetail>;
    zoneDetails?: Record<string, {
      id?: string;
      name?: string;
      role?: string;
      publicLocationCount?: number;
      indoorOrSheltered?: boolean;
      quietOrCooling?: boolean;
      sensoryBaseline?: string;
      agentReasoningHints?: string[];
      locations?: string[];
    }>;
    spatialModel?: {
      paths?: Array<{
        id?: string;
        fromZoneId?: string;
        toZoneId?: string;
        estimatedWalkMinutes?: number;
        covered?: boolean;
        stepFree?: boolean;
        crowdSensitivity?: string;
        source?: string;
      }>;
      routingAssumptions?: string[];
    };
    guestSegments?: Array<{
      id?: string;
      label?: string;
      decisionDrivers?: string[];
      preferredZones?: string[];
      handoffTriggers?: string[];
    }>;
    operatingPriors?: {
      zoneDemandPriors?: Array<{
        zoneId?: string;
        role?: string;
        typicalPressureDrivers?: string[];
        watchSignals?: string[];
      }>;
      crossModuleRules?: string[];
    };
    learningContext?: {
      scenarioTaxonomy?: string[];
      observationKeys?: string[];
      feedbackLabels?: string[];
      privacyBoundary?: string[];
      coverageTargets?: Record<string, number>;
    };
    agentContext?: {
      groundingFields?: string[];
      capabilitiesBacked?: string[];
      humanReviewTriggers?: string[];
      moduleBindings?: Record<string, string[]>;
      knownGaps?: string[];
    };
    profileIntelligence?: {
      source?: string;
      coverage?: Record<string, number>;
      qualityGaps?: string[];
      certifiedPaths?: Array<{
        id?: string;
        fromZoneId?: string;
        toZoneId?: string;
        estimatedWalkMinutes?: number;
        certificationStatus?: string;
        allowedUses?: string[];
        blockedClaims?: string[];
      }>;
      capacityModel?: {
        status?: string;
        zoneComfort?: Array<{
          zoneId?: string;
          comfortCapacityEstimate?: number;
          dwellMinutesTypical?: number;
          spillbackRisk?: string;
          confidence?: string;
        }>;
        blockedClaims?: string[];
      };
      experienceRules?: {
        eventReadyZones?: string[];
        halloweenCandidateLocations?: string[];
        kidFriendlyAnchors?: string[];
        rainyDayAnchors?: string[];
        vipRouteAnchors?: string[];
        noGoPairings?: Array<{ rule?: string; severity?: string }>;
      };
      segmentNeeds?: Record<string, {
        label?: string;
        preferredPace?: string;
        needs?: string[];
        avoid?: string[];
        requiredHandoff?: string[];
      }>;
      timingModel?: {
        status?: string;
        showDurationModel?: Array<{ id?: string; name?: string; zoneId?: string; typicalDurationMinutes?: number }>;
        knownPulses?: Array<{ id?: string; when?: string; affectedZoneRoles?: string[] }>;
        missingForExactScheduling?: string[];
      };
      modulePolicy?: Record<string, Record<string, string[]>>;
      fieldSourceLedger?: {
        status?: string;
        rows?: Array<{
          field?: string;
          sourceId?: string;
          reviewStatus?: string;
          lastVerifiedAt?: string;
          maxAgeSeconds?: number;
          staleBehavior?: string;
        }>;
        staleFieldPolicy?: string[];
      };
      learningSchema?: {
        version?: string;
        successMetrics?: string[];
        failureMetrics?: string[];
        updateTargets?: Record<string, string[]>;
        reviewOwners?: Record<string, string>;
      };
      brandBible?: {
        brandName?: string;
        tone?: string[];
        audiences?: string[];
        copyRules?: string[];
        bannedClaims?: string[];
        supportedLocales?: string[];
      };
      liveFeedBindings?: Record<string, unknown>;
    };
  };
  sourceIntegrity?: {
    profileType?: string;
    realVenueFeedConnected?: boolean;
    usesSampleData?: boolean;
    usesSeedData?: boolean;
    usesApprovedSyntheticProfile?: boolean;
  };
  globalProfile?: {
    scope?: string;
    tenantId?: string;
    venueId?: string;
    profileType?: string;
    consumers?: string[];
    ownership?: string;
    reasoningContract?: {
      profileFacts?: string;
      liveFacts?: string;
      learningBoundary?: string;
      humanAuthority?: string[];
    };
  };
  validation?: {
    status?: string;
    issues?: VenueProfileIssue[];
    criticalCount?: number;
    highCount?: number;
    loadedFrom?: string | null;
  };
  venueProfile?: VenueProfilePayload;
  venueExperienceData?: VenueProfilePayload;
  export?: Record<string, unknown>;
};

type ProfileDiff = {
  summary?: {
    totalChanges?: number;
    addedLocations?: number;
    removedLocations?: number;
    changedLocations?: number;
    safetyAdded?: number;
    safetyRemoved?: number;
    ownerChanges?: number;
    zoneChanges?: number;
    identityChanges?: number;
    replacementRisk?: string;
  };
  countDelta?: Record<string, number>;
  locations?: {
    added?: string[];
    removed?: string[];
    changed?: Array<{ name?: string; fields?: string[] }>;
  };
  safetyInstructions?: {
    added?: string[];
    removed?: string[];
  };
  channelOwners?: {
    changed?: Array<{ channel?: string; before?: string; after?: string }>;
  };
  publicZones?: {
    added?: Array<{ id?: string; name?: string }>;
    removed?: Array<{ id?: string; name?: string }>;
    changed?: Array<{ name?: string; fields?: string[] }>;
  };
  identity?: {
    changed?: Array<{ field?: string; before?: unknown; after?: unknown }>;
  };
};

type VenueProfilePreviewPayload = {
  status?: string;
  mode?: string;
  message?: string;
  sourceName?: string;
  validation?: VenueProfilePayload["validation"];
  canActivate?: boolean;
  diff?: ProfileDiff;
};

type VenueProfileIssue = {
  id?: string;
  severity?: string;
  detail?: string;
};

function formatStatus(value?: string) {
  return (value || "unknown").replaceAll("_", " ");
}

function statusClass(status?: string) {
  if (status === "studio_ready" || status === "venue_verified") return "border-emerald-400/40 bg-emerald-950/25 text-emerald-100";
  if (status === "blocked") return "border-amber-400/40 bg-amber-950/25 text-amber-100";
  return "border-slate-700 bg-[#11161a] text-slate-200";
}

function compact(items?: string[], limit = 3) {
  const list = items?.filter(Boolean) ?? [];
  if (!list.length) return "";
  return `${list.slice(0, limit).join(", ")}${list.length > limit ? ` +${list.length - limit}` : ""}`;
}

function collectIssues(payload: VenueProfilePayload | null) {
  return payload?.validation?.issues ?? payload?.readiness?.issues ?? [];
}

export function VenueProfilePage() {
  const [profile, setProfile] = useState<VenueProfilePayload | null>(null);
  const [sourceName, setSourceName] = useState("");
  const [jsonText, setJsonText] = useState("");
  const [validation, setValidation] = useState<VenueProfilePayload | null>(null);
  const [preview, setPreview] = useState<VenueProfilePreviewPayload | null>(null);
  const [previewKey, setPreviewKey] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isValidating, setIsValidating] = useState(false);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [isActivating, setIsActivating] = useState(false);
  const [isLoadingSyntheticExport, setIsLoadingSyntheticExport] = useState(false);

  const parsedExport = useMemo(() => {
    if (!jsonText.trim()) return null;
    try {
      const parsed = JSON.parse(jsonText) as unknown;
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : null;
    } catch {
      return null;
    }
  }, [jsonText]);
  const importCandidateKey = useMemo(() => (parsedExport ? JSON.stringify({ sourceName, export: parsedExport }) : ""), [parsedExport, sourceName]);

  const refreshProfile = async () => {
    setIsLoading(true);
    setMessage(null);
    try {
      const response = await fetchParkPulseApi("/api/park/venue-profile", { timeoutMs: 6000 });
      setProfile(await response.json() as VenueProfilePayload);
    } catch {
      setMessage("Venue profile service unavailable");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void refreshProfile();
  }, []);

  const handleFile = async (file: File | null) => {
    if (!file) return;
    setSourceName(file.name);
    setJsonText(await file.text());
    setValidation(null);
    setPreview(null);
    setPreviewKey("");
    setMessage("File loaded");
  };

  const loadApprovedSyntheticExport = async () => {
    setIsLoadingSyntheticExport(true);
    setMessage(null);
    try {
      const response = await fetchParkPulseApi("/api/park/venue-profile/synthetic/export", {
        headers: { "x-parkpulse-role": "ml_ops_admin" },
        timeoutMs: 8000,
      });
      const payload = await response.json() as VenueProfilePayload & { sourceName?: string; export?: Record<string, unknown> };
      if (!payload.export) throw new Error("Synthetic export payload missing.");
      setSourceName(payload.sourceName ?? "parkpulse_synthetic_venue_export.approved.json");
      setJsonText(JSON.stringify(payload.export, null, 2));
      setValidation({ status: payload.status, mode: payload.mode, message: payload.message, validation: payload.validation });
      setPreview(null);
      setPreviewKey("");
      setMessage(payload.message ?? "Approved synthetic export loaded into editor");
    } catch {
      setMessage("Unable to load approved synthetic export");
    } finally {
      setIsLoadingSyntheticExport(false);
    }
  };

  const validateExport = async () => {
    if (!parsedExport) {
      setMessage("Paste or upload a valid JSON object first");
      return;
    }
    setIsValidating(true);
    setMessage(null);
    try {
      const response = await fetchParkPulseApi("/api/park/venue-profile/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-parkpulse-role": "ml_ops_admin" },
        body: JSON.stringify({ sourceName, export: parsedExport }),
        timeoutMs: 8000,
      });
      setValidation(await response.json() as VenueProfilePayload);
      setPreview(null);
      setPreviewKey("");
      setMessage("Validation complete");
    } catch {
      setMessage("Validation request failed");
    } finally {
      setIsValidating(false);
    }
  };

  const previewImport = async () => {
    if (!parsedExport) {
      setMessage("Paste or upload a valid JSON object first");
      return;
    }
    setIsPreviewing(true);
    setMessage(null);
    try {
      const response = await fetchParkPulseApi("/api/park/venue-profile/import/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-parkpulse-role": "ml_ops_admin" },
        body: JSON.stringify({ sourceName, export: parsedExport }),
        timeoutMs: 10000,
      });
      const payload = await response.json() as VenueProfilePreviewPayload;
      setPreview(payload);
      setPreviewKey(importCandidateKey);
      setValidation({ status: payload.status, mode: payload.mode, message: payload.message, validation: payload.validation });
      setMessage(payload.message ?? "Profile import preview ready");
    } catch {
      setMessage("Preview request failed");
    } finally {
      setIsPreviewing(false);
    }
  };

  const importExport = async () => {
    if (!parsedExport) {
      setMessage("Paste or upload a valid JSON object first");
      return;
    }
    setIsImporting(true);
    setMessage(null);
    try {
      const response = await fetchParkPulseApi("/api/park/venue-profile/import", {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-parkpulse-role": "ml_ops_admin" },
        body: JSON.stringify({ sourceName, export: parsedExport, actor: "venue_profile_page", previewAccepted: true }),
        timeoutMs: 10000,
      });
      const payload = await response.json() as VenueProfilePayload;
      setValidation(payload);
      setProfile(payload.venueProfile ?? payload.venueExperienceData ?? null);
      setPreview(null);
      setPreviewKey("");
      setMessage(payload.message ?? "Venue profile imported");
    } catch {
      setMessage("Import blocked. Validate the export and source name first.");
    } finally {
      setIsImporting(false);
    }
  };

  const activateSynthetic = async () => {
    setIsActivating(true);
    setMessage(null);
    try {
      const response = await fetchParkPulseApi("/api/park/venue-profile/synthetic/activate", {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-parkpulse-role": "ml_ops_admin" },
        body: JSON.stringify({ actor: "venue_profile_page" }),
        timeoutMs: 9000,
      });
      const payload = await response.json() as { message?: string; venueProfile?: VenueProfilePayload };
      setProfile(payload.venueProfile ?? null);
      setMessage(payload.message ?? "Synthetic venue profile activated");
    } catch {
      setMessage("Synthetic venue profile activation failed");
    } finally {
      setIsActivating(false);
    }
  };

  const details = useMemo(() => Object.values(profile?.realInputs?.locationDetails ?? {}).filter((item): item is VenueLocationDetail => Boolean(item?.name)), [profile]);
  const groups = useMemo(() => {
    const result: Record<string, VenueLocationDetail[]> = {
      Attractions: [],
      Dining: [],
      Shows: [],
      "Quiet/Cooling": [],
      Services: [],
      Other: [],
    };
    for (const item of details) {
      const kind = item.kind ?? "";
      if (kind === "attraction") result.Attractions.push(item);
      else if (kind === "food") result.Dining.push(item);
      else if (kind === "show") result.Shows.push(item);
      else if (kind === "quiet_or_cooling") result["Quiet/Cooling"].push(item);
      else if (["restrooms", "first_aid", "guest_services", "water_refill", "photo_spots", "family_service"].includes(kind)) result.Services.push(item);
      else result.Other.push(item);
    }
    return result;
  }, [details]);

  const identity = profile?.venueIdentity;
  const counts = profile?.readiness?.counts ?? {};
  const owners = Object.entries(profile?.realInputs?.channelOwners ?? {});
  const zoneDetails = Object.values(profile?.realInputs?.zoneDetails ?? {});
  const paths = profile?.realInputs?.spatialModel?.paths ?? [];
  const guestSegments = profile?.realInputs?.guestSegments ?? [];
  const learningContext = profile?.realInputs?.learningContext;
  const agentContext = profile?.realInputs?.agentContext;
  const profileIntelligence = profile?.realInputs?.profileIntelligence;
  const intelligenceCoverage = profileIntelligence?.coverage ?? {};
  const sourceLedgerRows = profileIntelligence?.fieldSourceLedger?.rows ?? [];
  const capacityZones = profileIntelligence?.capacityModel?.zoneComfort ?? [];
  const modulePolicyEntries = Object.entries(profileIntelligence?.modulePolicy ?? {});
  const segmentNeedEntries = Object.entries(profileIntelligence?.segmentNeeds ?? {});
  const moduleBindings = Object.entries(agentContext?.moduleBindings ?? {});
  const operatingPriors = profile?.realInputs?.operatingPriors?.zoneDemandPriors ?? [];
  const validationStatus = validation?.validation?.status ?? validation?.status;
  const validationIssues = collectIssues(validation);
  const diffSummary = preview?.diff?.summary;
  const canImportValidatedProfile = Boolean(parsedExport && validationStatus === "studio_ready" && preview?.canActivate && previewKey === importCandidateKey);
  const sourceMode = profile?.sourceIntegrity?.usesApprovedSyntheticProfile
    ? "approved synthetic"
    : profile?.sourceIntegrity?.realVenueFeedConnected
      ? "live real feed"
      : "not connected";

  return (
    <main className="min-h-screen bg-[#10130f] px-4 py-5 font-sans text-slate-200 lg:px-8">
      <div className="mx-auto max-w-[1380px] space-y-5">
        <header className="rounded-lg border border-lime-300/25 bg-[#151914] p-5 shadow-xl shadow-black/20">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-lime-200">Venue Profile</div>
              <h1 className="mt-2 max-w-5xl text-3xl font-black tracking-normal text-white lg:text-5xl">{identity?.name ?? "Global park profile"}</h1>
              <p className="mt-3 max-w-4xl text-sm leading-relaxed text-slate-300">
                Shared venue knowledge layer for Experience Studio, accessibility journeys, guest copy, signage, VIP tours, and Command Center review.
              </p>
            </div>
            <nav className="flex flex-wrap gap-2">
              <a href="/" className="rounded border border-slate-700 bg-[#0d1115] px-3 py-2 text-xs font-black text-slate-200 transition hover:border-lime-300">Command Center</a>
              <a href="/experience-studio" className="rounded border border-slate-700 bg-[#0d1115] px-3 py-2 text-xs font-black text-slate-200 transition hover:border-lime-300">Experience Studio</a>
              <a href="/accessibility-journey" className="rounded border border-slate-700 bg-[#0d1115] px-3 py-2 text-xs font-black text-lime-100 transition hover:border-lime-300">Accessibility Journey</a>
              <button
                type="button"
                onClick={() => void refreshProfile()}
                disabled={isLoading}
                className="rounded border border-lime-300 bg-lime-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-lime-200 disabled:opacity-50"
              >
                {isLoading ? "Refreshing" : "Refresh"}
              </button>
            </nav>
          </div>
        </header>

        <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="rounded-lg border border-slate-800 bg-[#151914] p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-cyan-200">{identity?.venueId ?? "venue not connected"}</div>
                <h2 className="mt-1 text-2xl font-black text-white">{identity?.description ?? "No active venue profile connected."}</h2>
              </div>
              <div className={`rounded border px-2 py-1 text-[10px] font-black uppercase tracking-widest ${statusClass(profile?.readiness?.status)}`}>
                {formatStatus(profile?.readiness?.status)}
              </div>
            </div>
            <div className="mt-4 grid gap-2 md:grid-cols-3 xl:grid-cols-5">
              {[
                ["Locations", counts.locations ?? 0],
                ["Zones", counts.zones ?? 0],
                ["Paths", counts.paths ?? 0],
                ["Segments", counts.guestSegments ?? 0],
                ["Learning", counts.learningSignals ?? 0],
              ].map(([label, value]) => (
                <div key={label} className="rounded border border-slate-800 bg-[#0d1115] p-3">
                  <div className="text-2xl font-black text-white">{value}</div>
                  <div className="mt-1 text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                </div>
              ))}
            </div>
            <div className="mt-2 grid gap-2 md:grid-cols-3 xl:grid-cols-5">
              {[
                ["Indoor", counts.indoorLocations ?? 0],
                ["Access", counts.accessibleRoutes ?? 0],
                ["Safety", counts.safetyInstructions ?? 0],
                ["Owners", counts.channelOwners ?? 0],
                ["Grounding", counts.agentGroundingFields ?? 0],
              ].map(([label, value]) => (
                <div key={label} className="rounded border border-slate-800 bg-[#0d1115] p-3">
                  <div className="text-2xl font-black text-white">{value}</div>
                  <div className="mt-1 text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                </div>
              ))}
            </div>
            <div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
              {(identity?.publicZones ?? []).map((zone) => (
                <div key={zone.id ?? zone.name} className="rounded border border-slate-800 bg-[#0d1115] p-3">
                  <div className="text-sm font-black text-white">{zone.name ?? zone.id}</div>
                  <div className="mt-1 text-xs leading-relaxed text-slate-500">{zone.position ?? "public zone"}</div>
                </div>
              ))}
            </div>
          </div>

          <aside className="space-y-5">
            <div className="rounded-lg border border-slate-800 bg-[#151914] p-4">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Global contract</div>
              <div className="mt-2 grid gap-2 text-xs">
                {[
                  ["Scope", profile?.globalProfile?.scope],
                  ["Tenant", profile?.globalProfile?.tenantId],
                  ["Type", identity?.profileType],
                  ["Source", sourceMode],
                  ["Sample", profile?.sourceIntegrity?.usesSampleData ? "detected" : "not active"],
                ].map(([label, value]) => (
                  <div key={label} className="grid grid-cols-[6rem_1fr] gap-2 rounded border border-slate-800 bg-[#0d1115] px-3 py-2">
                    <span className="font-black uppercase tracking-widest text-slate-500">{label}</span>
                    <span className="font-bold text-slate-200">{value ?? "unknown"}</span>
                  </div>
                ))}
              </div>
              <button
                type="button"
                onClick={() => void activateSynthetic()}
                disabled={isActivating}
                className="mt-3 w-full rounded border border-amber-300 bg-amber-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-amber-200 disabled:opacity-50"
              >
                {isActivating ? "Activating" : "Activate synthetic profile"}
              </button>
              {message ? <div className="mt-3 rounded border border-slate-800 bg-[#0d1115] p-2 text-xs font-bold text-slate-300">{message}</div> : null}
            </div>

            <div className="rounded-lg border border-slate-800 bg-[#151914] p-4">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Channel owners</div>
              <div className="mt-3 grid gap-2">
                {owners.map(([channel, owner]) => (
                  <div key={channel} className="rounded border border-slate-800 bg-[#0d1115] p-2">
                    <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{formatStatus(channel)}</div>
                    <div className="mt-1 text-xs font-bold text-slate-200">{owner}</div>
                  </div>
                ))}
              </div>
            </div>
          </aside>
        </section>

        <section className="rounded-lg border border-slate-800 bg-[#151914] p-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-amber-200">Profile intelligence</div>
              <h2 className="mt-1 text-2xl font-black text-white">Agent utility contract</h2>
              <p className="mt-2 max-w-4xl text-sm leading-relaxed text-slate-400">
                Structured constraints and mappings for deeper reasoning: certified paths, capacity assumptions, experience rules, module policy, source freshness, learning, brand, and live-feed bindings.
              </p>
            </div>
            <div className="w-fit rounded border border-slate-700 bg-[#0d1115] px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-300">
              {formatStatus(profileIntelligence?.source)}
            </div>
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-3 xl:grid-cols-6">
            {[
              ["Path records", intelligenceCoverage.certifiedPaths ?? counts.certifiedPaths ?? 0],
              ["Capacity zones", intelligenceCoverage.capacityZones ?? counts.capacityZones ?? 0],
              ["Source rows", intelligenceCoverage.fieldSourceRows ?? counts.fieldSourceRows ?? 0],
              ["Policies", intelligenceCoverage.policyModules ?? counts.modulePolicies ?? 0],
              ["Bindings", intelligenceCoverage.liveFeedBindingGroups ?? counts.liveFeedBindingGroups ?? 0],
              ["Overrides", intelligenceCoverage.venueOwnedOverrides ?? 0],
            ].map(([label, value]) => (
              <div key={label} className="rounded border border-slate-800 bg-[#0d1115] p-3">
                <div className="text-2xl font-black text-white">{value}</div>
                <div className="mt-1 text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
              </div>
            ))}
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-3">
            <div className="rounded border border-slate-800 bg-[#0d1115] p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Quality gaps</div>
              <div className="mt-3 grid gap-2">
                {(profileIntelligence?.qualityGaps ?? []).map((gap) => (
                  <div key={gap} className="rounded border border-amber-400/25 bg-amber-950/15 p-2 text-xs leading-relaxed text-amber-100">{gap}</div>
                ))}
                {!profileIntelligence?.qualityGaps?.length ? <div className="rounded border border-slate-800 bg-[#151914] p-2 text-xs text-slate-500">No intelligence quality gaps reported.</div> : null}
              </div>
            </div>

            <div className="rounded border border-slate-800 bg-[#0d1115] p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Capacity model</div>
              <div className="mt-2 text-xs font-bold uppercase tracking-widest text-slate-400">{formatStatus(profileIntelligence?.capacityModel?.status)}</div>
              <div className="mt-3 grid gap-2">
                {capacityZones.slice(0, 5).map((zone) => (
                  <div key={zone.zoneId} className="rounded border border-slate-800 bg-[#151914] p-2 text-xs leading-relaxed text-slate-400">
                    <span className="font-black text-slate-100">{zone.zoneId}</span>: {zone.comfortCapacityEstimate ?? "--"} comfort / {zone.dwellMinutesTypical ?? "--"}m dwell / {formatStatus(zone.spillbackRisk)}
                  </div>
                ))}
                {!capacityZones.length ? <div className="rounded border border-slate-800 bg-[#151914] p-2 text-xs text-slate-500">No capacity assumptions connected.</div> : null}
              </div>
            </div>

            <div className="rounded border border-slate-800 bg-[#0d1115] p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Experience rules</div>
              <div className="mt-3 grid gap-2 text-xs leading-relaxed text-slate-400">
                <div className="rounded border border-slate-800 bg-[#151914] p-2"><span className="font-black text-slate-200">Rain:</span> {compact(profileIntelligence?.experienceRules?.rainyDayAnchors, 4) || "None"}</div>
                <div className="rounded border border-slate-800 bg-[#151914] p-2"><span className="font-black text-slate-200">Kids:</span> {compact(profileIntelligence?.experienceRules?.kidFriendlyAnchors, 4) || "None"}</div>
                <div className="rounded border border-slate-800 bg-[#151914] p-2"><span className="font-black text-slate-200">VIP:</span> {compact(profileIntelligence?.experienceRules?.vipRouteAnchors, 4) || "None"}</div>
              </div>
            </div>
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-2">
            <div className="rounded border border-slate-800 bg-[#0d1115] p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Module policy</div>
              <div className="mt-3 grid gap-2">
                {modulePolicyEntries.map(([module, policy]) => (
                  <div key={module} className="rounded border border-slate-800 bg-[#151914] p-2">
                    <div className="text-xs font-black uppercase tracking-widest text-slate-200">{formatStatus(module)}</div>
                    <div className="mt-1 text-xs leading-relaxed text-slate-500">
                      {Object.entries(policy).map(([key, values]) => `${formatStatus(key)}: ${compact(values, 2)}`).join(" / ")}
                    </div>
                  </div>
                ))}
                {!modulePolicyEntries.length ? <div className="rounded border border-slate-800 bg-[#151914] p-2 text-xs text-slate-500">No module policy connected.</div> : null}
              </div>
            </div>

            <div className="rounded border border-slate-800 bg-[#0d1115] p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Segment needs</div>
              <div className="mt-3 grid gap-2">
                {segmentNeedEntries.slice(0, 5).map(([segmentId, need]) => (
                  <div key={segmentId} className="rounded border border-slate-800 bg-[#151914] p-2">
                    <div className="text-xs font-black text-slate-100">{need.label ?? formatStatus(segmentId)}</div>
                    <div className="mt-1 text-xs leading-relaxed text-slate-500">Pace {formatStatus(need.preferredPace)} / avoid {compact(need.avoid, 2) || "none"} / handoff {compact(need.requiredHandoff, 2) || "none"}</div>
                  </div>
                ))}
                {!segmentNeedEntries.length ? <div className="rounded border border-slate-800 bg-[#151914] p-2 text-xs text-slate-500">No segment needs connected.</div> : null}
              </div>
            </div>
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-3">
            <div className="rounded border border-slate-800 bg-[#0d1115] p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Source freshness</div>
              <div className="mt-3 grid gap-2">
                {sourceLedgerRows.slice(0, 6).map((row) => (
                  <div key={`${row.field}-${row.sourceId}`} className="rounded border border-slate-800 bg-[#151914] p-2 text-xs leading-relaxed text-slate-400">
                    <span className="font-black text-slate-100">{row.field}</span> / {row.sourceId} / {formatStatus(row.reviewStatus)}
                  </div>
                ))}
                {!sourceLedgerRows.length ? <div className="rounded border border-slate-800 bg-[#151914] p-2 text-xs text-slate-500">No source ledger connected.</div> : null}
              </div>
            </div>

            <div className="rounded border border-slate-800 bg-[#0d1115] p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Brand bible</div>
              <div className="mt-3 grid gap-2 text-xs leading-relaxed text-slate-400">
                <div className="rounded border border-slate-800 bg-[#151914] p-2">Tone: {compact(profileIntelligence?.brandBible?.tone, 5) || "None"}</div>
                <div className="rounded border border-slate-800 bg-[#151914] p-2">Locales: {compact(profileIntelligence?.brandBible?.supportedLocales, 5) || "None"}</div>
                <div className="rounded border border-slate-800 bg-[#151914] p-2">Banned: {compact(profileIntelligence?.brandBible?.bannedClaims, 4) || "None"}</div>
              </div>
            </div>

            <div className="rounded border border-slate-800 bg-[#0d1115] p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Learning schema</div>
              <div className="mt-3 grid gap-2 text-xs leading-relaxed text-slate-400">
                <div className="rounded border border-slate-800 bg-[#151914] p-2">Success: {compact(profileIntelligence?.learningSchema?.successMetrics, 3) || "None"}</div>
                <div className="rounded border border-slate-800 bg-[#151914] p-2">Failure: {compact(profileIntelligence?.learningSchema?.failureMetrics, 3) || "None"}</div>
                <div className="rounded border border-slate-800 bg-[#151914] p-2">Live binding groups: {Object.keys(profileIntelligence?.liveFeedBindings ?? {}).length}</div>
              </div>
            </div>
          </div>
        </section>

        <section className="rounded-lg border border-slate-800 bg-[#151914] p-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-200">Agent reasoning substrate</div>
              <h2 className="mt-1 text-2xl font-black text-white">Park profile depth</h2>
              <p className="mt-2 max-w-4xl text-sm leading-relaxed text-slate-400">
                Source-backed park structure for route planning, experience drafting, accessibility support, command review, and learning evaluation.
              </p>
            </div>
            <div className={`w-fit rounded border px-2 py-1 text-[10px] font-black uppercase tracking-widest ${statusClass(profile?.readiness?.status)}`}>
              {formatStatus(sourceMode)}
            </div>
          </div>

          <div className="mt-4 grid gap-3 xl:grid-cols-4">
            {[
              ["Grounding fields", agentContext?.groundingFields?.length ?? 0, compact(agentContext?.groundingFields, 4) || "No grounding fields connected."],
              ["Capabilities", agentContext?.capabilitiesBacked?.length ?? 0, compact(agentContext?.capabilitiesBacked, 2) || "No agent capabilities declared."],
              ["Feedback labels", learningContext?.feedbackLabels?.length ?? 0, compact(learningContext?.feedbackLabels, 4) || "No learning labels connected."],
              ["Observation keys", learningContext?.observationKeys?.length ?? 0, compact(learningContext?.observationKeys, 4) || "No observation keys connected."],
            ].map(([label, value, detail]) => (
              <div key={label} className="rounded border border-slate-800 bg-[#0d1115] p-3">
                <div className="text-2xl font-black text-white">{value}</div>
                <div className="mt-1 text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                <div className="mt-2 text-xs leading-relaxed text-slate-400">{detail}</div>
              </div>
            ))}
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-3">
            <div className="rounded border border-slate-800 bg-[#0d1115] p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-lime-200">Zone intelligence</div>
              <div className="mt-3 grid gap-2">
                {zoneDetails.slice(0, 6).map((zone) => (
                  <div key={zone.id ?? zone.name} className="rounded border border-slate-800 bg-[#151914] p-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="text-sm font-black text-white">{zone.name ?? zone.id}</div>
                      <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{formatStatus(zone.role)}</div>
                    </div>
                    <div className="mt-1 text-xs leading-relaxed text-slate-400">
                      {zone.publicLocationCount ?? 0} locations / sensory {formatStatus(zone.sensoryBaseline)} / {zone.indoorOrSheltered ? "shelter" : "open"} / {zone.quietOrCooling ? "reset" : "active"}
                    </div>
                    {zone.agentReasoningHints?.length ? <div className="mt-1 text-[11px] leading-relaxed text-slate-500">{compact(zone.agentReasoningHints, 2)}</div> : null}
                  </div>
                ))}
                {!zoneDetails.length ? <div className="rounded border border-slate-800 bg-[#151914] p-2 text-xs text-slate-500">No zone intelligence connected.</div> : null}
              </div>
            </div>

            <div className="rounded border border-slate-800 bg-[#0d1115] p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-lime-200">Guest segments</div>
              <div className="mt-3 grid gap-2">
                {guestSegments.slice(0, 6).map((segment) => (
                  <div key={segment.id ?? segment.label} className="rounded border border-slate-800 bg-[#151914] p-2">
                    <div className="text-sm font-black text-white">{segment.label ?? segment.id}</div>
                    <div className="mt-1 text-xs leading-relaxed text-slate-400">{compact(segment.decisionDrivers, 3) || "No drivers connected."}</div>
                    {segment.handoffTriggers?.length ? <div className="mt-1 text-[11px] leading-relaxed text-slate-500">Handoff: {compact(segment.handoffTriggers, 2)}</div> : null}
                  </div>
                ))}
                {!guestSegments.length ? <div className="rounded border border-slate-800 bg-[#151914] p-2 text-xs text-slate-500">No guest segments connected.</div> : null}
              </div>
            </div>

            <div className="rounded border border-slate-800 bg-[#0d1115] p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-lime-200">Agent boundaries</div>
              <div className="mt-3 grid gap-2">
                {(agentContext?.humanReviewTriggers ?? []).slice(0, 6).map((trigger) => (
                  <div key={trigger} className="rounded border border-slate-800 bg-[#151914] p-2 text-xs leading-relaxed text-slate-300">{trigger}</div>
                ))}
                {!agentContext?.humanReviewTriggers?.length ? <div className="rounded border border-slate-800 bg-[#151914] p-2 text-xs text-slate-500">No human review triggers connected.</div> : null}
              </div>
            </div>
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <div className="rounded border border-slate-800 bg-[#0d1115] p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Spatial paths</div>
                <div className="rounded border border-slate-800 bg-[#151914] px-2 py-1 text-[10px] font-black text-slate-400">{paths.length}</div>
              </div>
              <div className="mt-3 grid gap-2 md:grid-cols-2">
                {paths.slice(0, 8).map((path) => (
                  <div key={path.id} className="rounded border border-slate-800 bg-[#151914] p-2 text-xs">
                    <div className="font-black text-slate-100">{path.fromZoneId} to {path.toZoneId}</div>
                    <div className="mt-1 text-slate-500">{path.estimatedWalkMinutes ?? "--"}m / {path.stepFree ? "step-free" : "verify access"} / {formatStatus(path.crowdSensitivity)}</div>
                  </div>
                ))}
                {!paths.length ? <div className="rounded border border-slate-800 bg-[#151914] p-2 text-xs text-slate-500">No path model connected.</div> : null}
              </div>
            </div>

            <div className="rounded border border-slate-800 bg-[#0d1115] p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Module bindings</div>
              <div className="mt-3 grid gap-2">
                {moduleBindings.map(([module, fields]) => (
                  <div key={module} className="rounded border border-slate-800 bg-[#151914] p-2">
                    <div className="text-xs font-black uppercase tracking-widest text-slate-300">{formatStatus(module)}</div>
                    <div className="mt-1 text-xs leading-relaxed text-slate-500">{compact(fields, 6)}</div>
                  </div>
                ))}
                {!moduleBindings.length ? <div className="rounded border border-slate-800 bg-[#151914] p-2 text-xs text-slate-500">No module bindings connected.</div> : null}
              </div>
            </div>
          </div>

          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            <div className="rounded border border-slate-800 bg-[#0d1115] p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Learning privacy boundary</div>
              <div className="mt-2 grid gap-2">
                {(learningContext?.privacyBoundary ?? profile?.globalProfile?.reasoningContract?.humanAuthority ?? []).slice(0, 4).map((item) => (
                  <div key={item} className="rounded border border-slate-800 bg-[#151914] p-2 text-xs leading-relaxed text-slate-400">{item}</div>
                ))}
              </div>
            </div>
            <div className="rounded border border-slate-800 bg-[#0d1115] p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Operating priors</div>
              <div className="mt-2 grid gap-2">
                {operatingPriors.slice(0, 4).map((prior) => (
                  <div key={prior.zoneId} className="rounded border border-slate-800 bg-[#151914] p-2 text-xs leading-relaxed text-slate-400">
                    <span className="font-black text-slate-200">{prior.zoneId}</span>: {compact(prior.watchSignals, 4) || compact(prior.typicalPressureDrivers, 3) || "No watch signals."}
                  </div>
                ))}
                {!operatingPriors.length ? <div className="rounded border border-slate-800 bg-[#151914] p-2 text-xs text-slate-500">No operating priors connected.</div> : null}
              </div>
            </div>
          </div>
        </section>

        <section className="rounded-lg border border-slate-800 bg-[#151914] p-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-200">Profile source management</div>
              <h2 className="mt-1 text-2xl font-black text-white">Validate and import venue export</h2>
              <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-400">
                Use a source-backed `customer_venue_export_v1` package for the active global profile. The backend blocks sample, seed, and incomplete exports.
              </p>
            </div>
            <div className={`w-fit rounded border px-2 py-1 text-[10px] font-black uppercase tracking-widest ${statusClass(validationStatus)}`}>
              {formatStatus(validationStatus ?? "not validated")}
            </div>
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-[18rem_minmax(0,1fr)]">
            <div className="space-y-3">
              <label className="block">
                <span className="text-[10px] font-black uppercase tracking-widest text-slate-500">Source name</span>
                <input
                  value={sourceName}
                  onChange={(event) => {
                    setSourceName(event.target.value);
                    setValidation(null);
                    setPreview(null);
                    setPreviewKey("");
                  }}
                  placeholder="venue_export.json"
                  className="mt-2 w-full rounded border border-slate-700 bg-[#0d1115] px-3 py-2 text-sm font-bold text-slate-100 outline-none transition focus:border-cyan-300"
                />
              </label>
              <label className="block">
                <span className="text-[10px] font-black uppercase tracking-widest text-slate-500">Upload JSON</span>
                <input
                  type="file"
                  accept="application/json,.json"
                  onChange={(event) => void handleFile(event.target.files?.[0] ?? null)}
                  className="mt-2 w-full rounded border border-slate-700 bg-[#0d1115] px-3 py-2 text-xs font-bold text-slate-300 file:mr-3 file:rounded file:border-0 file:bg-slate-700 file:px-2 file:py-1 file:text-xs file:font-black file:text-slate-100"
                />
              </label>
              <div className={`rounded border px-3 py-2 text-xs font-bold ${parsedExport ? "border-emerald-400/30 bg-emerald-950/20 text-emerald-100" : "border-amber-400/30 bg-amber-950/20 text-amber-100"}`}>
                {parsedExport ? "JSON object parsed" : "Waiting for valid JSON object"}
              </div>
              <button
                type="button"
                onClick={() => void loadApprovedSyntheticExport()}
                disabled={isLoadingSyntheticExport}
                className="w-full rounded border border-amber-300 bg-[#0d1115] px-3 py-2 text-xs font-black text-amber-100 transition hover:bg-amber-300 hover:text-slate-950 disabled:cursor-not-allowed disabled:border-slate-700 disabled:text-slate-500"
              >
                {isLoadingSyntheticExport ? "Loading synthetic JSON" : "Load approved synthetic JSON"}
              </button>
              <div className="rounded border border-amber-400/30 bg-amber-950/20 p-2 text-xs font-bold leading-relaxed text-amber-100">
                Test helper only: loads the approved synthetic export into the editor without activating it.
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => void validateExport()}
                  disabled={isValidating || !parsedExport}
                  className="rounded border border-cyan-300 bg-cyan-300 px-4 py-2 text-sm font-black text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:border-slate-700 disabled:bg-[#0d1115] disabled:text-slate-500"
                >
                  {isValidating ? "Validating" : "Validate"}
                </button>
                <button
                  type="button"
                  onClick={() => void previewImport()}
                  disabled={isPreviewing || !parsedExport}
                  className="rounded border border-lime-300 bg-lime-300 px-4 py-2 text-sm font-black text-slate-950 transition hover:bg-lime-200 disabled:cursor-not-allowed disabled:border-slate-700 disabled:bg-[#0d1115] disabled:text-slate-500"
                >
                  {isPreviewing ? "Previewing" : "Preview changes"}
                </button>
                <button
                  type="button"
                  onClick={() => void importExport()}
                  disabled={isImporting || !canImportValidatedProfile}
                  className="rounded border border-emerald-300 bg-emerald-300 px-4 py-2 text-sm font-black text-slate-950 transition hover:bg-emerald-200 disabled:cursor-not-allowed disabled:border-slate-700 disabled:bg-[#0d1115] disabled:text-slate-500"
                >
                  {isImporting ? "Importing" : "Import active profile"}
                </button>
              </div>
              <div className="rounded border border-slate-800 bg-[#0d1115] p-2 text-xs font-bold text-slate-500">
                Import unlocks after a preview returns studio ready for this exact source and JSON.
              </div>
              {message ? <div className="rounded border border-slate-800 bg-[#0d1115] p-2 text-xs font-bold text-slate-300">{message}</div> : null}
            </div>

            <div className="space-y-3">
              <label className="block">
                <span className="text-[10px] font-black uppercase tracking-widest text-slate-500">Venue export JSON</span>
                <textarea
                  value={jsonText}
                  onChange={(event) => {
                    setJsonText(event.target.value);
                    setValidation(null);
                    setPreview(null);
                    setPreviewKey("");
                  }}
                  placeholder="{ ...customer_venue_export_v1... }"
                  className="mt-2 h-64 w-full resize-none rounded border border-slate-700 bg-[#0d1115] p-3 font-mono text-xs leading-relaxed text-slate-100 outline-none transition focus:border-cyan-300"
                />
              </label>
              <div className="rounded border border-slate-800 bg-[#0d1115] p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Validation issues</div>
                    <div className="mt-1 text-xs text-slate-500">{validationIssues.length ? `${validationIssues.length} issue${validationIssues.length === 1 ? "" : "s"}` : "No blocking issues returned."}</div>
                  </div>
                  <div className={`rounded border px-2 py-1 text-[10px] font-black uppercase tracking-widest ${statusClass(validationStatus)}`}>
                    {formatStatus(validationStatus ?? "not validated")}
                  </div>
                </div>
                <div className="mt-3 grid gap-2">
                  {validationIssues.slice(0, 6).map((issue) => (
                    <div key={`${issue.id ?? issue.detail}-${issue.severity}`} className="rounded border border-slate-800 bg-[#151914] p-2">
                      <div className="text-[10px] font-black uppercase tracking-widest text-amber-200">{formatStatus(issue.severity)}</div>
                      <div className="mt-1 text-xs leading-relaxed text-slate-300">{issue.detail ?? issue.id ?? "Issue returned without detail."}</div>
                    </div>
                  ))}
                  {!validationIssues.length ? <div className="rounded border border-slate-800 bg-[#151914] p-2 text-xs text-slate-500">Run validation to see source-integrity results.</div> : null}
                </div>
              </div>
              <div className="rounded border border-slate-800 bg-[#0d1115] p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Activation preview</div>
                    <div className="mt-1 text-xs text-slate-500">{preview ? `${diffSummary?.totalChanges ?? 0} profile change${(diffSummary?.totalChanges ?? 0) === 1 ? "" : "s"}` : "Preview before activating a replacement profile."}</div>
                  </div>
                  <div className={`rounded border px-2 py-1 text-[10px] font-black uppercase tracking-widest ${preview?.canActivate ? "border-emerald-400/40 bg-emerald-950/25 text-emerald-100" : "border-slate-700 bg-[#151914] text-slate-400"}`}>
                    {preview?.canActivate ? "activation ready" : "not previewed"}
                  </div>
                </div>
                {preview ? (
                  <div className="mt-3 grid gap-3">
                    <div className="grid gap-2 md:grid-cols-4">
                      {[
                        ["Risk", diffSummary?.replacementRisk ?? "unknown"],
                        ["Added", diffSummary?.addedLocations ?? 0],
                        ["Removed", diffSummary?.removedLocations ?? 0],
                        ["Changed", diffSummary?.changedLocations ?? 0],
                      ].map(([label, value]) => (
                        <div key={label} className="rounded border border-slate-800 bg-[#151914] p-2">
                          <div className="text-sm font-black text-white">{value}</div>
                          <div className="mt-1 text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                        </div>
                      ))}
                    </div>
                    <div className="grid gap-2 lg:grid-cols-3">
                      <div className="rounded border border-slate-800 bg-[#151914] p-2">
                        <div className="text-[10px] font-black uppercase tracking-widest text-emerald-200">Added locations</div>
                        <div className="mt-2 text-xs leading-relaxed text-slate-400">{compact(preview.diff?.locations?.added, 5) || "None"}</div>
                      </div>
                      <div className="rounded border border-slate-800 bg-[#151914] p-2">
                        <div className="text-[10px] font-black uppercase tracking-widest text-amber-200">Removed locations</div>
                        <div className="mt-2 text-xs leading-relaxed text-slate-400">{compact(preview.diff?.locations?.removed, 5) || "None"}</div>
                      </div>
                      <div className="rounded border border-slate-800 bg-[#151914] p-2">
                        <div className="text-[10px] font-black uppercase tracking-widest text-cyan-200">Changed locations</div>
                        <div className="mt-2 text-xs leading-relaxed text-slate-400">
                          {preview.diff?.locations?.changed?.length ? compact(preview.diff.locations.changed.map((item) => `${item.name}: ${compact(item.fields, 3)}`), 4) : "None"}
                        </div>
                      </div>
                    </div>
                    <div className="grid gap-2 lg:grid-cols-3">
                      <div className="rounded border border-slate-800 bg-[#151914] p-2">
                        <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Safety changes</div>
                        <div className="mt-2 text-xs leading-relaxed text-slate-400">+{preview.diff?.safetyInstructions?.added?.length ?? 0} / -{preview.diff?.safetyInstructions?.removed?.length ?? 0}</div>
                      </div>
                      <div className="rounded border border-slate-800 bg-[#151914] p-2">
                        <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Owner changes</div>
                        <div className="mt-2 text-xs leading-relaxed text-slate-400">{preview.diff?.channelOwners?.changed?.length ?? 0}</div>
                      </div>
                      <div className="rounded border border-slate-800 bg-[#151914] p-2">
                        <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Identity changes</div>
                        <div className="mt-2 text-xs leading-relaxed text-slate-400">{preview.diff?.identity?.changed?.length ?? 0}</div>
                      </div>
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        </section>

        <section className="grid gap-4 xl:grid-cols-3">
          {Object.entries(groups).map(([label, rows]) => (
            <div key={label} className="rounded-lg border border-slate-800 bg-[#151914] p-4">
              <div className="flex items-center justify-between gap-2">
                <div className="text-[10px] font-black uppercase tracking-widest text-lime-200">{label}</div>
                <div className="rounded border border-slate-800 bg-[#0d1115] px-2 py-1 text-[10px] font-black text-slate-400">{rows.length}</div>
              </div>
              <div className="mt-3 grid gap-2">
                {rows.slice(0, 8).map((item) => (
                  <div key={`${label}-${item.name}`} className="rounded border border-slate-800 bg-[#0d1115] p-3">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <div className="text-sm font-black text-white">{item.name}</div>
                        <div className="mt-1 text-[11px] font-bold uppercase tracking-widest text-slate-500">{formatStatus(item.kind)}{item.zoneId ? ` / ${item.zoneId}` : ""}</div>
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {item.indoor ? <span className="rounded border border-cyan-400/30 bg-cyan-950/20 px-2 py-1 text-[9px] font-black uppercase tracking-widest text-cyan-100">Indoor</span> : null}
                        {item.covered ? <span className="rounded border border-lime-400/30 bg-lime-950/20 px-2 py-1 text-[9px] font-black uppercase tracking-widest text-lime-100">Covered</span> : null}
                        {item.accessible ? <span className="rounded border border-emerald-400/30 bg-emerald-950/20 px-2 py-1 text-[9px] font-black uppercase tracking-widest text-emerald-100">Accessible</span> : null}
                      </div>
                    </div>
                    {item.category || item.cuisine || item.familyFit || item.seating ? <p className="mt-2 text-xs leading-relaxed text-slate-400">{item.category ?? item.cuisine ?? item.familyFit ?? item.seating}</p> : null}
                    {item.accessibilityNote ? <p className="mt-2 text-[11px] leading-relaxed text-slate-500">{item.accessibilityNote}</p> : null}
                    {item.sensoryNote ? <p className="mt-1 text-[11px] leading-relaxed text-slate-500">{item.sensoryNote}</p> : null}
                    {item.bestFor?.length ? <p className="mt-1 text-[11px] leading-relaxed text-slate-500">Best for {compact(item.bestFor, 4)}.</p> : null}
                    {item.dietaryTags?.length ? <p className="mt-1 text-[11px] leading-relaxed text-slate-500">Tags: {compact(item.dietaryTags, 4)}.</p> : null}
                    {item.services?.length ? <p className="mt-1 text-[11px] leading-relaxed text-slate-500">Services: {compact(item.services, 4)}.</p> : null}
                  </div>
                ))}
                {!rows.length ? <div className="rounded border border-slate-800 bg-[#0d1115] p-3 text-xs text-slate-500">No records connected.</div> : null}
              </div>
            </div>
          ))}
        </section>

        <section className="rounded-lg border border-slate-800 bg-[#151914] p-4">
          <div className="text-[10px] font-black uppercase tracking-widest text-amber-200">Safety and guest instructions</div>
          <div className="mt-3 grid gap-2 lg:grid-cols-2">
            {(profile?.realInputs?.safetyInstructions ?? []).map((instruction) => (
              <div key={instruction} className="rounded border border-slate-800 bg-[#0d1115] p-3 text-xs leading-relaxed text-slate-300">{instruction}</div>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
