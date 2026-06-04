"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { fetchParkPulseApi } from "@/lib/api";

type VenueIssue = {
  id?: string;
  severity?: string;
  field?: string;
  detail?: string;
};

type VenueReadiness = {
  status?: string;
  autofillAllowed?: boolean;
  handoffReady?: boolean;
  loadedFrom?: string | null;
  counts?: Record<string, number>;
  issues?: VenueIssue[];
};

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
  dietaryTags?: string[];
  mobileOrder?: boolean;
  seating?: string;
  bestFor?: string[];
  accessible?: boolean;
  familyRoom?: boolean;
  guestInstruction?: string;
  services?: string[];
  guestTip?: string;
  sourceIds?: string[];
};

type ProfileIntelligence = {
  source?: string;
  coverage?: Record<string, number>;
  qualityGaps?: string[];
  experienceStudioPolicy?: {
    mayDraft?: string[];
    mustReview?: string[];
    neverClaim?: string[];
  };
  modulePolicy?: Record<string, {
    mayDraft?: string[];
    mustReview?: string[];
    neverClaim?: string[];
  }>;
  brandBible?: {
    tone?: string[];
    bannedClaims?: string[];
    supportedLocales?: string[];
  };
  learningLabels?: string[];
  learningSchema?: {
    feedbackLabels?: string[];
  };
  experienceRules?: Record<string, string[]>;
};

type VenueDataPayload = {
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
  readiness?: VenueReadiness;
  validation?: {
    status?: string;
    issues?: VenueIssue[];
    customerValidation?: {
      status?: string;
      critical_count?: number;
      high_count?: number;
    };
  };
  venueExperienceData?: VenueDataPayload;
  venueProfile?: VenueDataPayload;
  sourceIntegrity?: {
    usesSeedData?: boolean;
    usesSampleData?: boolean;
    usesApprovedSyntheticProfile?: boolean;
    realVenueFeedConnected?: boolean;
    profileType?: string;
    customerValidationStatus?: string;
  };
  realInputs?: {
    source?: string;
    locations?: string[];
    indoorLocations?: string[];
    quietLocations?: string[];
    attractionLocations?: string[];
    accessibleRoutes?: string[];
    safetyInstructions?: string[];
    channelOwners?: Record<string, string>;
    locationDetails?: Record<string, VenueLocationDetail>;
    profileIntelligence?: ProfileIntelligence;
  };
};

type ExperienceTemplateId =
  | "halloween-route"
  | "rainy-day"
  | "low-sensory"
  | "kid-quest"
  | "scavenger-hunt"
  | "attraction-copy"
  | "safety-signage"
  | "vip-tour";

type DraftStatus = "draft" | "in_review" | "needs_changes" | "approved" | "ready_for_publish";

type DraftStop = {
  stop: string;
  purpose: string;
  guestCopy: string;
  staffNote: string;
  accessibilityNote: string;
  profileIntelligenceNote?: string;
  source?: string;
};

type ExperienceDraft = {
  title: string;
  audience: string;
  intent: string;
  creativeBrief?: {
    creativeDirection?: string;
    storyArc?: string;
    sensoryLevel?: string;
    walkingPace?: string;
    outputPackage?: string;
    seasonalTheme?: string;
    tone?: string;
    constraints?: string;
  };
  route: DraftStop[];
  messages: Array<{ channel: string; copy: string; owner?: string }>;
  productionNotes: string[];
  studioReview?: Array<{
    agentId?: string;
    agentName?: string;
    status?: string;
    finding?: string;
    nextStep?: string;
  }>;
  profileIntelligence?: ProfileIntelligence;
  sourceIntegrity?: {
    realInputCount?: number;
    missingRealInputs?: string[];
    readyForHandoff?: boolean;
    usesSeedData?: boolean;
    usesSimulatedParkState?: boolean;
    usesInventedLocations?: boolean;
    profileIntelligenceAttached?: boolean;
    profileIntelligenceQualityGaps?: string[];
  };
};

type DraftPayload = {
  status?: string;
  mode?: string;
  draft?: ExperienceDraft;
  venueExperienceData?: VenueDataPayload;
  sourceIntegrity?: {
    venueExperienceDataAttached?: boolean;
    usesSeedData?: boolean;
    usesSimulatedParkState?: boolean;
  };
};

type SavedDraft = {
  id: string;
  title?: string;
  templateId?: ExperienceTemplateId;
  audience?: string;
  status?: DraftStatus;
  createdAt?: string;
  updatedAt?: string;
  latestNote?: string | null;
  routeStopCount?: number;
  messageCount?: number;
  handoffCount?: number;
  latestHandoffStatus?: string | null;
  draft?: ExperienceDraft;
};

type HandoffPackage = {
  id?: string;
  draftId?: string;
  status?: string;
  createdAt?: string;
  requiresCommandCenterReview?: boolean;
  operationalReviewReasons?: string[];
  channels?: Array<{ id: string; label: string; owner: string; artifact: unknown }>;
};

const draftTemplates: Array<{ id: ExperienceTemplateId; label: string; audience: string; tone: string; detail: string }> = [
  { id: "halloween-route", label: "Halloween route", audience: "families with older kids", tone: "spooky, playful, never graphic", detail: "Story route with themed transitions." },
  { id: "rainy-day", label: "Rainy-day journey", audience: "mixed family groups", tone: "calm, helpful, upbeat", detail: "Indoor-first comfort journey." },
  { id: "low-sensory", label: "Low-sensory path", audience: "guests who prefer lower stimulation", tone: "plain, respectful, reassuring", detail: "Quiet route with predictable opt-outs." },
  { id: "kid-quest", label: "Kid quest", audience: "kids ages 6 to 10 with caregivers", tone: "curious, warm, adventurous", detail: "Simple quest with small wins." },
  { id: "scavenger-hunt", label: "Scavenger hunt", audience: "families and friend groups", tone: "clever, visual, concise", detail: "Clue-based guest journey." },
  { id: "attraction-copy", label: "Attraction copy", audience: "first-time guests planning their day", tone: "vivid, specific, accurate", detail: "Expectation-setting attraction text." },
  { id: "safety-signage", label: "Safety signage", audience: "all guests", tone: "direct, calm, simple", detail: "Clearer safety language." },
  { id: "vip-tour", label: "VIP tour", audience: "VIP guests and high-value groups", tone: "polished, personal, confident", detail: "Host script and flexible pacing." },
];

const requiredFields = [
  "approved public locations",
  "indoor or sheltered locations",
  "accessibility map facts",
  "safety or first-aid guest instructions",
  "channel owners for guest_app, signage, email, staff_cue",
];

const workflowStates: Array<{ id: DraftStatus; label: string; detail: string }> = [
  { id: "draft", label: "Draft", detail: "Working copy saved by the experience team." },
  { id: "in_review", label: "In review", detail: "Creative, accessibility, and channel owners are checking it." },
  { id: "needs_changes", label: "Needs changes", detail: "Review found issues before approval." },
  { id: "approved", label: "Approved", detail: "Approved by Studio, ready for handoff attempt." },
  { id: "ready_for_publish", label: "Ready for publish", detail: "Handoff package has been staged, not published by Studio." },
];

const creativeDirections = [
  { value: "story-rich", label: "Story-rich", detail: "More narrative beats and guest-facing atmosphere." },
  { value: "comfort-first", label: "Comfort-first", detail: "Practical journey design with calm copy." },
  { value: "playful mission", label: "Playful", detail: "Quest language, clues, small wins, and caregiver clarity." },
  { value: "premium host-led", label: "Premium", detail: "Hosted pacing, polish, and graceful alternates." },
];

const storyArcs = [
  "Invitation -> clue -> reveal -> choice -> finale",
  "Arrival reset -> dry discovery -> warm pause -> flexible choice -> covered close",
  "Mission start -> clue -> discovery -> reward -> celebration",
  "Welcome -> insider reveal -> signature moment -> relaxed pause -> closing keepsake",
];

const sensoryLevels = ["low", "balanced", "high energy"];
const walkingPaces = ["compact", "moderate", "exploratory"];
const outputPackages = ["route storyboard", "channel copy", "full package", "host script"];

const creativeDefaultsByTemplate: Record<ExperienceTemplateId, {
  creativeDirection: string;
  storyArc: string;
  sensoryLevel: string;
  walkingPace: string;
  outputPackage: string;
  seasonalTheme: string;
}> = {
  "halloween-route": {
    creativeDirection: "story-rich",
    storyArc: "Invitation -> clue -> reveal -> choice -> finale",
    sensoryLevel: "balanced",
    walkingPace: "moderate",
    outputPackage: "full package",
    seasonalTheme: "family-safe Halloween mystery",
  },
  "rainy-day": {
    creativeDirection: "comfort-first",
    storyArc: "Arrival reset -> dry discovery -> warm pause -> flexible choice -> covered close",
    sensoryLevel: "low",
    walkingPace: "compact",
    outputPackage: "full package",
    seasonalTheme: "rainy-day comfort route",
  },
  "low-sensory": {
    creativeDirection: "comfort-first",
    storyArc: "Arrival reset -> dry discovery -> warm pause -> flexible choice -> covered close",
    sensoryLevel: "low",
    walkingPace: "compact",
    outputPackage: "route storyboard",
    seasonalTheme: "predictable low-sensory path",
  },
  "kid-quest": {
    creativeDirection: "playful mission",
    storyArc: "Mission start -> clue -> discovery -> reward -> celebration",
    sensoryLevel: "balanced",
    walkingPace: "moderate",
    outputPackage: "full package",
    seasonalTheme: "kid-friendly quest",
  },
  "scavenger-hunt": {
    creativeDirection: "playful mission",
    storyArc: "Invitation -> clue -> reveal -> choice -> finale",
    sensoryLevel: "balanced",
    walkingPace: "moderate",
    outputPackage: "full package",
    seasonalTheme: "visual scavenger hunt",
  },
  "attraction-copy": {
    creativeDirection: "story-rich",
    storyArc: "Hook -> expectation -> accessibility -> nearby pairing -> decision",
    sensoryLevel: "balanced",
    walkingPace: "moderate",
    outputPackage: "channel copy",
    seasonalTheme: "attraction planning copy",
  },
  "safety-signage": {
    creativeDirection: "comfort-first",
    storyArc: "Notice -> action -> reason -> support -> reminder",
    sensoryLevel: "low",
    walkingPace: "compact",
    outputPackage: "channel copy",
    seasonalTheme: "clear safety language",
  },
  "vip-tour": {
    creativeDirection: "premium host-led",
    storyArc: "Welcome -> insider reveal -> signature moment -> relaxed pause -> closing keepsake",
    sensoryLevel: "balanced",
    walkingPace: "exploratory",
    outputPackage: "host script",
    seasonalTheme: "VIP hosted route",
  },
};

function formatStatus(value?: string) {
  return (value || "unknown").replaceAll("_", " ");
}

function statusClass(status?: string) {
  if (status === "studio_ready" || status === "imported") return "border-emerald-400/40 bg-emerald-950/25 text-emerald-100";
  if (status === "blocked") return "border-amber-400/40 bg-amber-950/25 text-amber-100";
  return "border-slate-700 bg-[#11161a] text-slate-200";
}

function workflowClass(status?: DraftStatus | string) {
  if (status === "approved" || status === "ready_for_publish") return "border-emerald-400/40 bg-emerald-950/25 text-emerald-100";
  if (status === "in_review") return "border-cyan-400/40 bg-cyan-950/25 text-cyan-100";
  if (status === "needs_changes") return "border-red-400/40 bg-red-950/25 text-red-100";
  return "border-slate-700 bg-[#11161a] text-slate-200";
}

function issueLabel(issue: VenueIssue) {
  const id = issue.id ? issue.id.replaceAll("_", " ") : "issue";
  return `${id}${issue.field ? ` / ${issue.field}` : ""}`;
}

function kindLabel(value?: string) {
  return formatStatus(value || "location");
}

function compactList(items?: string[], limit = 3) {
  const list = items?.filter(Boolean) ?? [];
  if (!list.length) return "";
  return `${list.slice(0, limit).join(", ")}${list.length > limit ? ` +${list.length - limit}` : ""}`;
}

function collectIssues(payload: VenueDataPayload | null) {
  return payload?.readiness?.issues ?? payload?.validation?.issues ?? [];
}

export function ExperienceStudio() {
  const [readiness, setReadiness] = useState<VenueDataPayload | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isDrafting, setIsDrafting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [lastGeneratedAt, setLastGeneratedAt] = useState<string | null>(null);
  const [generationCount, setGenerationCount] = useState(0);
  const draftResultRef = useRef<HTMLDivElement | null>(null);
  const [templateId, setTemplateId] = useState<ExperienceTemplateId>("rainy-day");
  const selectedTemplate = draftTemplates.find((item) => item.id === templateId) ?? draftTemplates[1];
  const [audience, setAudience] = useState(selectedTemplate.audience);
  const [tone, setTone] = useState(selectedTemplate.tone);
  const [constraints, setConstraints] = useState("Use verified venue facts only. Keep movement guidance optional and send operational impacts to Command Center review.");
  const rainyDayDefaults = creativeDefaultsByTemplate["rainy-day"];
  const [creativeDirection, setCreativeDirection] = useState(rainyDayDefaults.creativeDirection);
  const [storyArc, setStoryArc] = useState(rainyDayDefaults.storyArc);
  const [sensoryLevel, setSensoryLevel] = useState(rainyDayDefaults.sensoryLevel);
  const [walkingPace, setWalkingPace] = useState(rainyDayDefaults.walkingPace);
  const [outputPackage, setOutputPackage] = useState(rainyDayDefaults.outputPackage);
  const [seasonalTheme, setSeasonalTheme] = useState(rainyDayDefaults.seasonalTheme);
  const [draftPayload, setDraftPayload] = useState<DraftPayload | null>(null);
  const [savedDrafts, setSavedDrafts] = useState<SavedDraft[]>([]);
  const [activeDraftId, setActiveDraftId] = useState<string | null>(null);
  const [workflowStatus, setWorkflowStatus] = useState<DraftStatus>("draft");
  const [reviewNote, setReviewNote] = useState("Ready for creative, accessibility, and source-integrity review.");
  const [latestHandoff, setLatestHandoff] = useState<HandoffPackage | null>(null);
  const [isSavingDraft, setIsSavingDraft] = useState(false);
  const [isUpdatingDraft, setIsUpdatingDraft] = useState(false);
  const [isWorkflowBusy, setIsWorkflowBusy] = useState(false);
  const [isSendingHandoff, setIsSendingHandoff] = useState(false);

  const refreshReadiness = async () => {
    setIsLoading(true);
    setMessage(null);
    try {
      const response = await fetchParkPulseApi("/api/park/venue-profile", { timeoutMs: 5000 });
      setReadiness(await response.json() as VenueDataPayload);
    } catch {
      setReadiness({
        readiness: {
          status: "blocked",
          autofillAllowed: false,
          issues: [{ id: "venue_data_api_unavailable", severity: "critical", detail: "Backend venue data readiness endpoint is unavailable." }],
        },
      });
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void refreshReadiness();
  }, []);

  const refreshSavedDrafts = async () => {
    try {
      const response = await fetchParkPulseApi("/api/park/experience-studio/drafts?limit=25", { timeoutMs: 5000 });
      const payload = await response.json() as { drafts?: SavedDraft[] };
      setSavedDrafts(payload.drafts ?? []);
    } catch {
      setMessage("Saved draft list unavailable");
    }
  };

  useEffect(() => {
    void refreshSavedDrafts();
  }, []);

  const selectDraftTemplate = (id: ExperienceTemplateId) => {
    const next = draftTemplates.find((item) => item.id === id) ?? selectedTemplate;
    const creativeDefaults = creativeDefaultsByTemplate[next.id];
    setTemplateId(next.id);
    setAudience(next.audience);
    setTone(next.tone);
    setCreativeDirection(creativeDefaults.creativeDirection);
    setStoryArc(creativeDefaults.storyArc);
    setSensoryLevel(creativeDefaults.sensoryLevel);
    setWalkingPace(creativeDefaults.walkingPace);
    setOutputPackage(creativeDefaults.outputPackage);
    setSeasonalTheme(creativeDefaults.seasonalTheme);
    setDraftPayload(null);
  };

  const generateDraft = async () => {
    setIsDrafting(true);
    setMessage(null);
    const composedConstraints = [
      constraints,
      `Creative direction: ${creativeDirection}.`,
      `Story arc: ${storyArc}.`,
      `Sensory level: ${sensoryLevel}.`,
      `Walking pace: ${walkingPace}.`,
      `Output package: ${outputPackage}.`,
      `Theme: ${seasonalTheme}.`,
    ].join("\n");
    try {
      const response = await fetchParkPulseApi("/api/park/experience-studio/draft", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          templateId,
          audience,
          tone,
          constraints: composedConstraints,
          creativeDirection,
          storyArc,
          sensoryLevel,
          walkingPace,
          outputPackage,
          seasonalTheme,
          useLlm: false,
          useRealParkContext: false,
          useVenueExperienceData: true,
        }),
        timeoutMs: 9000,
      });
      const payload = await response.json() as DraftPayload;
      setDraftPayload(payload);
      setActiveDraftId(null);
      setWorkflowStatus("draft");
      setLatestHandoff(null);
      if (payload.venueExperienceData) setReadiness(payload.venueExperienceData);
      const generatedAt = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      setLastGeneratedAt(generatedAt);
      setGenerationCount((current) => current + 1);
      setMessage(payload.draft?.sourceIntegrity?.readyForHandoff ? `Creative package generated at ${generatedAt}` : `Draft generated at ${generatedAt} with blockers because verified venue data is incomplete`);
      window.setTimeout(() => draftResultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
    } catch {
      setMessage("Draft generation failed");
    } finally {
      setIsDrafting(false);
    }
  };

  const saveDraft = async () => {
    if (!draft) {
      setMessage("Generate a draft before saving");
      return;
    }
    setIsSavingDraft(true);
    setMessage(null);
    try {
      const response = await fetchParkPulseApi("/api/park/experience-studio/drafts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          templateId,
          draft,
          sourceMode: draftPayload?.mode ?? "experience_studio_gated_draft",
          actor: "experience_designer",
          brief: { audience, tone, constraints, creativeDirection, storyArc, sensoryLevel, walkingPace, outputPackage, seasonalTheme, venueReadiness: readiness?.readiness },
        }),
        timeoutMs: 6000,
      });
      const payload = await response.json() as { draftRecord?: SavedDraft; summary?: SavedDraft };
      const saved = (payload.draftRecord ?? payload.summary) as SavedDraft | undefined;
      if (!saved?.id) throw new Error("Save response missing draft id.");
      setActiveDraftId(saved.id);
      setWorkflowStatus(saved.status ?? "draft");
      setSavedDrafts((current) => [saved, ...current.filter((item) => item.id !== saved.id)]);
      setMessage("Draft saved");
    } catch {
      setMessage("Draft save failed");
    } finally {
      setIsSavingDraft(false);
    }
  };

  const updateDraft = (updater: (draft: ExperienceDraft) => ExperienceDraft) => {
    setDraftPayload((current) => {
      if (!current?.draft) return current;
      return { ...current, draft: updater(current.draft) };
    });
  };

  const updateRouteStop = (index: number, field: keyof DraftStop, value: string) => {
    updateDraft((current) => ({
      ...current,
      route: current.route.map((stop, stopIndex) => stopIndex === index ? { ...stop, [field]: value } : stop),
    }));
  };

  const updateMessage = (index: number, field: "channel" | "copy" | "owner", value: string) => {
    updateDraft((current) => ({
      ...current,
      messages: current.messages.map((item, messageIndex) => messageIndex === index ? { ...item, [field]: value } : item),
    }));
  };

  const updateProductionNote = (index: number, value: string) => {
    updateDraft((current) => ({
      ...current,
      productionNotes: current.productionNotes.map((item, noteIndex) => noteIndex === index ? value : item),
    }));
  };

  const addProductionNote = () => {
    updateDraft((current) => ({
      ...current,
      productionNotes: [...current.productionNotes, "New production note"],
    }));
  };

  const removeProductionNote = (index: number) => {
    updateDraft((current) => ({
      ...current,
      productionNotes: current.productionNotes.filter((_, noteIndex) => noteIndex !== index),
    }));
  };

  const updateSavedDraftContent = async () => {
    if (!activeDraftId) {
      setMessage("Save the draft before updating content");
      return;
    }
    if (!draft) {
      setMessage("Open or generate a draft before updating content");
      return;
    }
    setIsUpdatingDraft(true);
    setMessage(null);
    try {
      const response = await fetchParkPulseApi(`/api/park/experience-studio/drafts/${encodeURIComponent(activeDraftId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ draft, note: reviewNote, actor: "experience_designer" }),
        timeoutMs: 7000,
      });
      const payload = await response.json() as { status?: string; message?: string; draftRecord?: SavedDraft; summary?: SavedDraft };
      if (payload.status !== "updated" || !payload.draftRecord?.draft) throw new Error(payload.message ?? "Draft update failed.");
      setDraftPayload({ status: "ready", mode: "saved_draft", draft: payload.draftRecord.draft });
      setWorkflowStatus(payload.draftRecord.status ?? workflowStatus);
      const summary = payload.summary ?? payload.draftRecord;
      if (summary?.id) setSavedDrafts((current) => current.map((item) => item.id === summary.id ? { ...item, ...summary } : item));
      setMessage(payload.draftRecord.draft.sourceIntegrity?.readyForHandoff ? "Draft content updated" : "Draft content updated; source-integrity gate still blocks handoff");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Draft update failed");
    } finally {
      setIsUpdatingDraft(false);
    }
  };

  const openSavedDraft = async (record: SavedDraft) => {
    setIsWorkflowBusy(true);
    setMessage(null);
    try {
      let selected = record;
      if (!selected.draft) {
        const response = await fetchParkPulseApi(`/api/park/experience-studio/drafts/${encodeURIComponent(record.id)}`, { timeoutMs: 5000 });
        const payload = await response.json() as { draftRecord?: SavedDraft };
        if (!payload.draftRecord?.draft) throw new Error("Saved draft body missing.");
        selected = payload.draftRecord;
      }
      setDraftPayload({ status: "ready", mode: "saved_draft", draft: selected.draft });
      setActiveDraftId(selected.id);
      setWorkflowStatus(selected.status ?? "draft");
      if (selected.templateId) setTemplateId(selected.templateId);
      if (selected.draft?.audience) setAudience(selected.draft.audience);
      if (selected.draft?.creativeBrief) {
        setCreativeDirection(selected.draft.creativeBrief.creativeDirection ?? creativeDirection);
        setStoryArc(selected.draft.creativeBrief.storyArc ?? storyArc);
        setSensoryLevel(selected.draft.creativeBrief.sensoryLevel ?? sensoryLevel);
        setWalkingPace(selected.draft.creativeBrief.walkingPace ?? walkingPace);
        setOutputPackage(selected.draft.creativeBrief.outputPackage ?? outputPackage);
        setSeasonalTheme(selected.draft.creativeBrief.seasonalTheme ?? seasonalTheme);
        if (selected.draft.creativeBrief.tone) setTone(selected.draft.creativeBrief.tone);
        if (selected.draft.creativeBrief.constraints) setConstraints(selected.draft.creativeBrief.constraints);
      }
      setLatestHandoff(null);
      setMessage("Saved draft opened");
    } catch {
      setMessage("Unable to open saved draft");
    } finally {
      setIsWorkflowBusy(false);
    }
  };

  const updateWorkflowStatus = async (nextStatus: DraftStatus) => {
    if (!activeDraftId) {
      setMessage("Save the draft before moving review state");
      return;
    }
    setIsWorkflowBusy(true);
    setMessage(null);
    try {
      const response = await fetchParkPulseApi(`/api/park/experience-studio/drafts/${encodeURIComponent(activeDraftId)}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: nextStatus, note: reviewNote, actor: "experience_reviewer" }),
        timeoutMs: 6000,
      });
      const payload = await response.json() as { summary?: SavedDraft; draftRecord?: SavedDraft; status?: string; message?: string };
      if (payload.status && payload.status !== "updated") throw new Error(payload.message ?? "Workflow update failed.");
      const updated = payload.summary ?? payload.draftRecord;
      setWorkflowStatus(nextStatus);
      if (updated?.id) setSavedDrafts((current) => current.map((item) => item.id === updated.id ? { ...item, ...updated } : item));
      setMessage(`Workflow moved to ${nextStatus.replaceAll("_", " ")}`);
    } catch {
      setMessage("Workflow update failed");
    } finally {
      setIsWorkflowBusy(false);
    }
  };

  const sendHandoff = async () => {
    if (!activeDraftId) {
      setMessage("Save the draft before handoff");
      return;
    }
    if (!["approved", "ready_for_publish"].includes(workflowStatus)) {
      setMessage("Approve the draft before handoff");
      return;
    }
    setIsSendingHandoff(true);
    setMessage(null);
    try {
      const response = await fetchParkPulseApi(`/api/park/experience-studio/drafts/${encodeURIComponent(activeDraftId)}/handoff`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ actor: "experience_studio", note: reviewNote }),
        timeoutMs: 6000,
      });
      const payload = await response.json() as { status?: string; message?: string; handoff?: HandoffPackage; draftSummary?: SavedDraft; missingRealInputs?: string[] };
      if (payload.status !== "created" || !payload.handoff) {
        const missing = payload.missingRealInputs?.length ? ` Missing: ${payload.missingRealInputs.join(", ")}` : "";
        throw new Error(`${payload.message ?? "Handoff blocked."}${missing}`);
      }
      setLatestHandoff(payload.handoff);
      setWorkflowStatus("ready_for_publish");
      if (payload.draftSummary?.id) setSavedDrafts((current) => current.map((item) => item.id === payload.draftSummary?.id ? { ...item, ...payload.draftSummary } : item));
      setMessage("Handoff sent to Command Center review");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Handoff failed");
    } finally {
      setIsSendingHandoff(false);
    }
  };

  const readinessStatus = readiness?.readiness?.status;
  const venueIdentity = readiness?.venueIdentity ?? null;
  const readinessCounts = readiness?.readiness?.counts ?? {};
  const profileSourceMode = readiness?.sourceIntegrity?.usesApprovedSyntheticProfile
    ? "approved synthetic"
    : readiness?.sourceIntegrity?.realVenueFeedConnected
      ? "live real feed"
      : "not connected";
  const locationDetails = useMemo(() => {
    const details = readiness?.realInputs?.locationDetails ?? {};
    return Object.values(details)
      .filter((item): item is VenueLocationDetail => Boolean(item?.name))
      .sort((a, b) => `${kindLabel(a.kind)} ${a.name}`.localeCompare(`${kindLabel(b.kind)} ${b.name}`));
  }, [readiness]);
  const profileGroups = useMemo(() => {
    const groups: Record<string, VenueLocationDetail[]> = {
      attractions: [],
      dining: [],
      services: [],
      quiet: [],
      shows: [],
      map: [],
    };
    for (const item of locationDetails) {
      const kind = item.kind ?? "";
      if (kind === "attraction") groups.attractions.push(item);
      else if (kind === "food") groups.dining.push(item);
      else if (kind === "quiet_or_cooling") groups.quiet.push(item);
      else if (kind === "show") groups.shows.push(item);
      else if (["restrooms", "first_aid", "guest_services", "water_refill", "photo_spots", "family_service"].includes(kind)) groups.services.push(item);
      else groups.map.push(item);
    }
    return groups;
  }, [locationDetails]);
  const channelOwnerEntries = Object.entries(readiness?.realInputs?.channelOwners ?? {});
  const safetyInstructions = readiness?.realInputs?.safetyInstructions ?? [];
  const issues = collectIssues(readiness);
  const draft = draftPayload?.draft;
  const draftMissing = draft?.sourceIntegrity?.missingRealInputs ?? [];
  const profileIntelligence = draft?.profileIntelligence ?? readiness?.realInputs?.profileIntelligence ?? null;
  const coverageEntries = Object.entries(profileIntelligence?.coverage ?? {}).filter(([, value]) => typeof value === "number");
  const profileQualityGaps = profileIntelligence?.qualityGaps ?? draft?.sourceIntegrity?.profileIntelligenceQualityGaps ?? [];
  const studioPolicy = (profileIntelligence?.experienceStudioPolicy ?? profileIntelligence?.modulePolicy?.experience_studio ?? {}) as NonNullable<ProfileIntelligence["experienceStudioPolicy"]>;
  const brandTone = profileIntelligence?.brandBible?.tone ?? [];
  const bannedClaims = profileIntelligence?.brandBible?.bannedClaims ?? [];
  const learningLabels = profileIntelligence?.learningLabels ?? profileIntelligence?.learningSchema?.feedbackLabels ?? [];
  const studioReview = draft?.studioReview ?? [];

  return (
    <main className="min-h-screen bg-[#10130f] px-4 py-5 font-sans text-slate-200 lg:px-8">
      <div className="mx-auto max-w-[1380px] space-y-5">
        <header className="rounded-lg border border-lime-300/25 bg-[#151914] p-5 shadow-xl shadow-black/20">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-lime-200">Experience Studio</div>
              <h1 className="mt-2 max-w-5xl text-3xl font-black tracking-normal text-white lg:text-5xl">Creative guest journey workbench</h1>
              <p className="mt-3 max-w-4xl text-sm leading-relaxed text-slate-300">
                Design routes, quests, scripts, signage, and channel copy from the active Venue Profile. Studio can be imaginative about story, pacing, and language, but it stays grounded in approved park facts and sends operational impact to review.
              </p>
            </div>
            <nav className="flex flex-wrap gap-2">
              <a href="/" className="rounded border border-slate-700 bg-[#0d1115] px-3 py-2 text-xs font-black text-slate-200 transition hover:border-lime-300">Command Center</a>
              <a href="/venue-profile" className="rounded border border-slate-700 bg-[#0d1115] px-3 py-2 text-xs font-black text-lime-100 transition hover:border-lime-300">Venue Profile</a>
              <a href="/accessibility-journey" className="rounded border border-slate-700 bg-[#0d1115] px-3 py-2 text-xs font-black text-lime-100 transition hover:border-lime-300">Accessibility Journey</a>
              <a href="/labs" className="rounded border border-slate-700 bg-[#0d1115] px-3 py-2 text-xs font-black text-slate-200 transition hover:border-lime-300">Labs</a>
            </nav>
          </div>
        </header>

        <section className="rounded-lg border border-slate-800 bg-[#151914] p-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-200">Draft workspace</div>
              <h2 className="mt-1 text-2xl font-black text-white">Shape the creative brief, then generate</h2>
              <p className="mt-2 max-w-4xl text-sm leading-relaxed text-slate-400">
                Pick an experience type, steer the story arc and sensory profile, then let the Studio backend synthesize a reviewable package from the active park profile.
              </p>
            </div>
            <div className={`w-fit rounded border px-2 py-1 text-[10px] font-black uppercase tracking-widest ${readiness?.readiness?.autofillAllowed ? "border-emerald-400/40 bg-emerald-950/25 text-emerald-100" : "border-amber-400/40 bg-amber-950/25 text-amber-100"}`}>
              {readiness?.readiness?.autofillAllowed ? "verified data available" : "verified data missing"}
            </div>
          </div>

          <div className="mt-5 grid gap-4 xl:grid-cols-[20rem_minmax(0,1fr)]">
            <div className="grid gap-2">
              {draftTemplates.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => selectDraftTemplate(item.id)}
                  className={`rounded border p-3 text-left transition ${item.id === templateId ? "border-cyan-300 bg-cyan-300 text-slate-950" : "border-slate-800 bg-[#0d1115] text-slate-300 hover:border-cyan-300/70"}`}
                >
                  <div className="text-sm font-black">{item.label}</div>
                  <div className={`mt-1 text-xs leading-relaxed ${item.id === templateId ? "text-slate-800" : "text-slate-500"}`}>{item.detail}</div>
                </button>
              ))}
            </div>

            <div className="rounded border border-slate-800 bg-[#0d1115] p-3">
              <div className="grid gap-3 lg:grid-cols-2">
                <label className="block">
                  <span className="text-[10px] font-black uppercase tracking-widest text-slate-500">Audience</span>
                  <input
                    value={audience}
                    onChange={(event) => setAudience(event.target.value)}
                    className="mt-2 w-full rounded border border-slate-700 bg-[#151914] px-3 py-2 text-sm font-bold text-slate-100 outline-none transition focus:border-cyan-300"
                  />
                </label>
                <label className="block">
                  <span className="text-[10px] font-black uppercase tracking-widest text-slate-500">Tone</span>
                  <input
                    value={tone}
                    onChange={(event) => setTone(event.target.value)}
                    className="mt-2 w-full rounded border border-slate-700 bg-[#151914] px-3 py-2 text-sm font-bold text-slate-100 outline-none transition focus:border-cyan-300"
                  />
                </label>
              </div>
              <div className="mt-4 grid gap-3 xl:grid-cols-[minmax(0,1fr)_18rem]">
                <div className="rounded border border-slate-800 bg-[#151914] p-3">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <div className="text-[10px] font-black uppercase tracking-widest text-cyan-200">Creative direction</div>
                      <div className="mt-1 text-xs leading-relaxed text-slate-500">Controls how the assistant frames each stop, transition, and channel artifact.</div>
                    </div>
                    <div className="rounded border border-slate-700 bg-[#0d1115] px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-400">{outputPackage}</div>
                  </div>
                  <div className="mt-3 grid gap-2 md:grid-cols-2">
                    {creativeDirections.map((item) => (
                      <button
                        key={item.value}
                        type="button"
                        onClick={() => setCreativeDirection(item.value)}
                        className={`rounded border p-3 text-left transition ${creativeDirection === item.value ? "border-cyan-300 bg-cyan-300 text-slate-950" : "border-slate-800 bg-[#0d1115] text-slate-300 hover:border-cyan-300/70"}`}
                      >
                        <div className="text-xs font-black">{item.label}</div>
                        <div className={`mt-1 text-[11px] leading-relaxed ${creativeDirection === item.value ? "text-slate-800" : "text-slate-500"}`}>{item.detail}</div>
                      </button>
                    ))}
                  </div>
                </div>

                <div className="rounded border border-slate-800 bg-[#151914] p-3">
                  <label className="block">
                    <span className="text-[10px] font-black uppercase tracking-widest text-slate-500">Theme</span>
                    <input
                      value={seasonalTheme}
                      onChange={(event) => setSeasonalTheme(event.target.value)}
                      className="mt-2 w-full rounded border border-slate-700 bg-[#0d1115] px-3 py-2 text-xs font-bold text-slate-100 outline-none transition focus:border-cyan-300"
                    />
                  </label>
                  <label className="mt-3 block">
                    <span className="text-[10px] font-black uppercase tracking-widest text-slate-500">Story arc</span>
                    <select
                      value={storyArc}
                      onChange={(event) => setStoryArc(event.target.value)}
                      className="mt-2 w-full rounded border border-slate-700 bg-[#0d1115] px-3 py-2 text-xs font-bold text-slate-100 outline-none transition focus:border-cyan-300"
                    >
                      {storyArcs.map((item) => <option key={item} value={item}>{item}</option>)}
                    </select>
                  </label>
                </div>
              </div>
              <div className="mt-3 grid gap-3 md:grid-cols-3">
                <div className="rounded border border-slate-800 bg-[#151914] p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Sensory level</div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {sensoryLevels.map((item) => (
                      <button
                        key={item}
                        type="button"
                        onClick={() => setSensoryLevel(item)}
                        className={`rounded border px-3 py-2 text-xs font-black transition ${sensoryLevel === item ? "border-lime-300 bg-lime-300 text-slate-950" : "border-slate-700 bg-[#0d1115] text-slate-300 hover:border-lime-300/70"}`}
                      >
                        {item}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="rounded border border-slate-800 bg-[#151914] p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Walking pace</div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {walkingPaces.map((item) => (
                      <button
                        key={item}
                        type="button"
                        onClick={() => setWalkingPace(item)}
                        className={`rounded border px-3 py-2 text-xs font-black transition ${walkingPace === item ? "border-lime-300 bg-lime-300 text-slate-950" : "border-slate-700 bg-[#0d1115] text-slate-300 hover:border-lime-300/70"}`}
                      >
                        {item}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="rounded border border-slate-800 bg-[#151914] p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Package</div>
                  <select
                    value={outputPackage}
                    onChange={(event) => setOutputPackage(event.target.value)}
                    className="mt-2 w-full rounded border border-slate-700 bg-[#0d1115] px-3 py-2 text-xs font-bold text-slate-100 outline-none transition focus:border-cyan-300"
                  >
                    {outputPackages.map((item) => <option key={item} value={item}>{item}</option>)}
                  </select>
                </div>
              </div>
              <label className="mt-3 block">
                <span className="text-[10px] font-black uppercase tracking-widest text-slate-500">Constraints</span>
                <textarea
                  value={constraints}
                  onChange={(event) => setConstraints(event.target.value)}
                  className="mt-2 h-24 w-full resize-none rounded border border-slate-700 bg-[#151914] p-3 text-sm leading-relaxed text-slate-100 outline-none transition focus:border-cyan-300"
                />
              </label>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => void generateDraft()}
                  disabled={isDrafting}
                  className="rounded border border-cyan-300 bg-cyan-300 px-4 py-2 text-sm font-black text-slate-950 transition hover:bg-cyan-200 disabled:opacity-50"
                >
                  {isDrafting ? "Generating" : "Generate creative package"}
                </button>
                <div className={`rounded border px-3 py-2 text-xs font-bold ${isDrafting ? "border-cyan-300/50 bg-cyan-950/25 text-cyan-100" : lastGeneratedAt ? "border-emerald-400/40 bg-emerald-950/25 text-emerald-100" : "border-slate-800 bg-[#151914] text-slate-400"}`}>
                  {isDrafting ? "Building route, copy, and review packet" : lastGeneratedAt ? `Generated ${generationCount} time${generationCount === 1 ? "" : "s"} / ${lastGeneratedAt}` : "No package generated in this session"}
                </div>
                <div className="rounded border border-slate-800 bg-[#151914] px-3 py-2 text-xs font-bold text-slate-400">
                  Venue autofill: {readiness?.readiness?.autofillAllowed ? "available" : "blocked"}
                </div>
                <button
                  type="button"
                  onClick={() => void saveDraft()}
                  disabled={isSavingDraft || !draft}
                  className="rounded border border-emerald-300 bg-emerald-300 px-4 py-2 text-sm font-black text-slate-950 transition hover:bg-emerald-200 disabled:cursor-not-allowed disabled:border-slate-700 disabled:bg-[#151914] disabled:text-slate-500"
                >
                  {isSavingDraft ? "Saving" : "Save draft"}
                </button>
              </div>
              <div className="mt-4 grid gap-3 xl:grid-cols-3">
                <div className="rounded border border-slate-800 bg-[#151914] p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-lime-200">Brand voice</div>
                  <div className="mt-2 text-xs leading-relaxed text-slate-300">{brandTone.length ? compactList(brandTone, 5) : "No brand bible tone connected."}</div>
                  {bannedClaims.length ? <div className="mt-2 text-[11px] leading-relaxed text-amber-100">Avoid: {compactList(bannedClaims, 4)}</div> : null}
                </div>
                <div className="rounded border border-slate-800 bg-[#151914] p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-lime-200">Policy boundary</div>
                  <div className="mt-2 text-xs leading-relaxed text-slate-300">May draft: {compactList(studioPolicy.mayDraft, 4) || "not connected"}</div>
                  <div className="mt-1 text-[11px] leading-relaxed text-slate-500">Review: {compactList(studioPolicy.mustReview, 4) || "movement, safety, access, and availability claims"}</div>
                </div>
                <div className="rounded border border-slate-800 bg-[#151914] p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-lime-200">Learning loop</div>
                  <div className="mt-2 text-xs leading-relaxed text-slate-300">{learningLabels.length ? compactList(learningLabels, 5) : "No feedback labels connected."}</div>
                  <div className="mt-1 text-[11px] leading-relaxed text-slate-500">{profileQualityGaps.length ? `${profileQualityGaps.length} profile gap(s) need review.` : "Profile gaps clear for this view."}</div>
                </div>
              </div>

              {draft ? (
                <div ref={draftResultRef} className="mt-4 scroll-mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
                  <div className="rounded border border-slate-800 bg-[#151914] p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <div className="text-[10px] font-black uppercase tracking-widest text-cyan-200">{draft.title}</div>
                        <div className="mt-1 text-sm text-slate-400">{draft.intent}</div>
                        {lastGeneratedAt ? <div className="mt-2 w-fit rounded border border-emerald-400/40 bg-emerald-950/25 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-emerald-100">Generated at {lastGeneratedAt}</div> : null}
                      </div>
                      <div className={`rounded border px-2 py-1 text-[10px] font-black uppercase tracking-widest ${draft.sourceIntegrity?.readyForHandoff ? "border-emerald-400/40 bg-emerald-950/25 text-emerald-100" : "border-amber-400/40 bg-amber-950/25 text-amber-100"}`}>
                        {draft.sourceIntegrity?.readyForHandoff ? "handoff ready" : "handoff blocked"}
                      </div>
                    </div>
                    {draft.creativeBrief ? (
                      <div className="mt-4 grid gap-2 border-t border-slate-800 pt-3 md:grid-cols-3">
                        {[
                          ["Direction", draft.creativeBrief.creativeDirection],
                          ["Story arc", draft.creativeBrief.storyArc],
                          ["Sensory", draft.creativeBrief.sensoryLevel],
                          ["Pace", draft.creativeBrief.walkingPace],
                          ["Package", draft.creativeBrief.outputPackage],
                          ["Theme", draft.creativeBrief.seasonalTheme],
                        ].map(([label, value]) => (
                          <div key={label} className="rounded border border-slate-800 bg-[#0d1115] px-3 py-2">
                            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                            <div className="mt-1 text-xs font-bold text-slate-200">{value ?? "not set"}</div>
                          </div>
                        ))}
                      </div>
                    ) : null}
                    <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-slate-800 pt-3">
                      <div>
                        <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Draft editor</div>
                        <div className="mt-1 text-xs leading-relaxed text-slate-500">Edits change copy and sequencing only. Source-integrity flags stay server-controlled.</div>
                      </div>
                      <button
                        type="button"
                        onClick={() => void updateSavedDraftContent()}
                        disabled={isUpdatingDraft || !activeDraftId}
                        className="rounded border border-cyan-300 bg-cyan-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:border-slate-700 disabled:bg-[#0d1115] disabled:text-slate-500"
                      >
                        {isUpdatingDraft ? "Updating" : "Update saved draft"}
                      </button>
                    </div>
                    <div className="mt-3 grid gap-3">
                      {draft.route.map((stop, index) => (
                        <div key={`${stop.stop}-${index}`} className="rounded border border-slate-800 bg-[#0d1115] p-3">
                          <label className="block">
                            <span className="text-[10px] font-black uppercase tracking-widest text-slate-500">Stop {index + 1}</span>
                            <input
                              value={stop.stop}
                              onChange={(event) => updateRouteStop(index, "stop", event.target.value)}
                              className="mt-2 w-full rounded border border-slate-700 bg-[#151914] px-3 py-2 text-sm font-black text-white outline-none transition focus:border-cyan-300"
                            />
                          </label>
                          <label className="mt-2 block">
                            <span className="text-[10px] font-black uppercase tracking-widest text-slate-500">Story beat purpose</span>
                            <textarea
                              value={stop.purpose}
                              onChange={(event) => updateRouteStop(index, "purpose", event.target.value)}
                              className="mt-2 h-16 w-full resize-none rounded border border-slate-700 bg-[#151914] p-2 text-xs leading-relaxed text-slate-100 outline-none transition focus:border-cyan-300"
                            />
                          </label>
                          <div className="mt-2 grid gap-2 lg:grid-cols-2">
                            <label className="block">
                              <span className="text-[10px] font-black uppercase tracking-widest text-slate-500">Guest copy</span>
                              <textarea
                                value={stop.guestCopy}
                                onChange={(event) => updateRouteStop(index, "guestCopy", event.target.value)}
                                className="mt-2 h-24 w-full resize-none rounded border border-slate-700 bg-[#151914] p-2 text-xs leading-relaxed text-slate-100 outline-none transition focus:border-cyan-300"
                              />
                            </label>
                            <label className="block">
                              <span className="text-[10px] font-black uppercase tracking-widest text-slate-500">Staff note</span>
                              <textarea
                                value={stop.staffNote}
                                onChange={(event) => updateRouteStop(index, "staffNote", event.target.value)}
                                className="mt-2 h-24 w-full resize-none rounded border border-slate-700 bg-[#151914] p-2 text-xs leading-relaxed text-slate-100 outline-none transition focus:border-cyan-300"
                              />
                            </label>
                          </div>
                          <label className="mt-2 block">
                            <span className="text-[10px] font-black uppercase tracking-widest text-slate-500">Accessibility note</span>
                            <textarea
                              value={stop.accessibilityNote}
                              onChange={(event) => updateRouteStop(index, "accessibilityNote", event.target.value)}
                              className="mt-2 h-20 w-full resize-none rounded border border-slate-700 bg-[#151914] p-2 text-xs leading-relaxed text-slate-100 outline-none transition focus:border-cyan-300"
                            />
                          </label>
                          <label className="mt-2 block">
                            <span className="text-[10px] font-black uppercase tracking-widest text-slate-500">Profile intelligence note</span>
                            <textarea
                              value={stop.profileIntelligenceNote ?? ""}
                              onChange={(event) => updateRouteStop(index, "profileIntelligenceNote", event.target.value)}
                              className="mt-2 h-16 w-full resize-none rounded border border-slate-700 bg-[#151914] p-2 text-xs leading-relaxed text-slate-100 outline-none transition focus:border-cyan-300"
                            />
                          </label>
                        </div>
                      ))}
                    </div>

                    <div className="mt-4 grid gap-3 border-t border-slate-800 pt-3">
                      <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Channel artifacts</div>
                      {draft.messages.map((item, index) => (
                        <div key={`${item.channel}-${index}`} className="rounded border border-slate-800 bg-[#0d1115] p-3">
                          <div className="grid gap-2 lg:grid-cols-[11rem_minmax(0,1fr)]">
                            <label className="block">
                              <span className="text-[10px] font-black uppercase tracking-widest text-slate-500">Channel</span>
                              <input
                                value={item.channel}
                                onChange={(event) => updateMessage(index, "channel", event.target.value)}
                                className="mt-2 w-full rounded border border-slate-700 bg-[#151914] px-3 py-2 text-xs font-black text-slate-100 outline-none transition focus:border-cyan-300"
                              />
                            </label>
                            <label className="block">
                              <span className="text-[10px] font-black uppercase tracking-widest text-slate-500">Owner</span>
                              <input
                                value={item.owner ?? ""}
                                onChange={(event) => updateMessage(index, "owner", event.target.value)}
                                className="mt-2 w-full rounded border border-slate-700 bg-[#151914] px-3 py-2 text-xs font-bold text-slate-100 outline-none transition focus:border-cyan-300"
                              />
                            </label>
                          </div>
                          <label className="mt-2 block">
                            <span className="text-[10px] font-black uppercase tracking-widest text-slate-500">Copy</span>
                            <textarea
                              value={item.copy}
                              onChange={(event) => updateMessage(index, "copy", event.target.value)}
                              className="mt-2 h-24 w-full resize-none rounded border border-slate-700 bg-[#151914] p-2 text-xs leading-relaxed text-slate-100 outline-none transition focus:border-cyan-300"
                            />
                          </label>
                        </div>
                      ))}
                    </div>

                    <div className="mt-4 border-t border-slate-800 pt-3">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Production notes</div>
                        <button
                          type="button"
                          onClick={addProductionNote}
                          className="rounded border border-slate-700 bg-[#0d1115] px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-300 transition hover:border-cyan-300"
                        >
                          Add note
                        </button>
                      </div>
                      <div className="mt-2 grid gap-2">
                        {draft.productionNotes.map((note, index) => (
                          <div key={`${note}-${index}`} className="grid gap-2 lg:grid-cols-[minmax(0,1fr)_6rem]">
                            <textarea
                              value={note}
                              onChange={(event) => updateProductionNote(index, event.target.value)}
                              className="h-20 w-full resize-none rounded border border-slate-700 bg-[#0d1115] p-2 text-xs leading-relaxed text-slate-100 outline-none transition focus:border-cyan-300"
                            />
                            <button
                              type="button"
                              onClick={() => removeProductionNote(index)}
                              className="rounded border border-slate-700 bg-[#0d1115] px-2 py-1 text-xs font-black text-slate-300 transition hover:border-red-300 hover:text-red-100"
                            >
                              Remove
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>

                  <aside className="rounded border border-slate-800 bg-[#151914] p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Workflow</div>
                        <div className={`mt-1 w-fit rounded border px-2 py-1 text-[10px] font-black uppercase tracking-widest ${workflowClass(workflowStatus)}`}>{workflowStatus.replaceAll("_", " ")}</div>
                      </div>
                      <div className="max-w-[9rem] truncate text-right text-[11px] font-bold text-slate-500">{activeDraftId ?? "not saved"}</div>
                    </div>
                    <textarea
                      value={reviewNote}
                      onChange={(event) => setReviewNote(event.target.value)}
                      className="mt-3 h-20 w-full resize-none rounded border border-slate-700 bg-[#0d1115] p-2 text-xs leading-relaxed text-slate-100 outline-none transition focus:border-cyan-300"
                    />
                    <div className="mt-3 grid gap-2">
                      {workflowStates.map((state) => (
                        <button
                          key={state.id}
                          type="button"
                          onClick={() => void updateWorkflowStatus(state.id)}
                          disabled={isWorkflowBusy || !activeDraftId}
                          className={`rounded border p-2 text-left transition disabled:cursor-not-allowed disabled:opacity-50 ${workflowStatus === state.id ? workflowClass(state.id) : "border-slate-800 bg-[#0d1115] text-slate-300 hover:border-cyan-300/70"}`}
                        >
                          <div className="text-xs font-black">{state.label}</div>
                          <div className="mt-1 text-[11px] leading-relaxed opacity-80">{state.detail}</div>
                        </button>
                      ))}
                    </div>
                    <button
                      type="button"
                      onClick={() => void sendHandoff()}
                      disabled={isSendingHandoff || !activeDraftId || !["approved", "ready_for_publish"].includes(workflowStatus)}
                      className="mt-3 w-full rounded border border-violet-300 bg-violet-300 px-3 py-2 text-sm font-black text-slate-950 transition hover:bg-violet-200 disabled:cursor-not-allowed disabled:border-slate-700 disabled:bg-[#0d1115] disabled:text-slate-500"
                    >
                      {isSendingHandoff ? "Sending handoff" : "Send Command Center handoff"}
                    </button>
                    {latestHandoff ? (
                      <div className="mt-3 rounded border border-violet-300/30 bg-violet-950/20 p-2">
                        <div className="text-[10px] font-black uppercase tracking-widest text-violet-200">Latest handoff</div>
                        <div className="mt-1 text-xs font-bold text-slate-200">{latestHandoff.status ?? "created"}</div>
                        <div className="mt-1 text-[11px] leading-relaxed text-slate-400">{latestHandoff.requiresCommandCenterReview ? "Command Center review required" : "Channel owner review"}</div>
                      </div>
                    ) : null}

                    <div className="mt-4 border-t border-slate-800 pt-3">
                    <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Source integrity</div>
                    <div className="mt-2 grid gap-2 text-xs">
                      <div>Real facts: {draft.sourceIntegrity?.realInputCount ?? 0}</div>
                      <div>Seed data: {draft.sourceIntegrity?.usesSeedData ? "detected" : "not used"}</div>
                      <div>Sim state: {draft.sourceIntegrity?.usesSimulatedParkState ? "used" : "not used"}</div>
                      <div>Invented locations: {draft.sourceIntegrity?.usesInventedLocations ? "detected" : "blocked"}</div>
                    </div>
                    <div className="mt-3 text-[10px] font-black uppercase tracking-widest text-slate-500">Missing inputs</div>
                    <div className="mt-2 grid gap-1 text-xs leading-relaxed text-slate-400">
                      {draftMissing.length ? draftMissing.map((item) => <div key={item}>{item.replaceAll("_", " ")}</div>) : <div>No missing input flags.</div>}
                    </div>
                    <div className="mt-3 text-[10px] font-black uppercase tracking-widest text-slate-500">Profile intelligence</div>
                    <div className="mt-2 rounded border border-slate-800 bg-[#0d1115] p-2">
                      <div className="text-xs font-black text-slate-200">{profileIntelligence?.source ?? "not connected"}</div>
                      <div className="mt-2 grid grid-cols-2 gap-2 text-[11px] text-slate-400">
                        {coverageEntries.slice(0, 6).map(([label, value]) => (
                          <div key={label} className="rounded border border-slate-800 bg-[#151914] px-2 py-1">
                            <span className="font-black uppercase tracking-widest text-slate-500">{formatStatus(label)}</span>
                            <span className="ml-2 font-bold text-slate-200">{value}</span>
                          </div>
                        ))}
                        {!coverageEntries.length ? <div className="col-span-2 text-slate-500">No coverage counters attached.</div> : null}
                      </div>
                      <div className="mt-2 grid gap-1 text-[11px] leading-relaxed text-amber-100">
                        {profileQualityGaps.length ? profileQualityGaps.slice(0, 4).map((item) => <div key={item}>Review: {item}</div>) : <div className="text-slate-500">No profile quality gaps reported.</div>}
                      </div>
                    </div>
                    <div className="mt-3 text-[10px] font-black uppercase tracking-widest text-slate-500">Studio reviewers</div>
                    <div className="mt-2 grid gap-2">
                      {studioReview.length ? studioReview.map((item) => (
                        <div key={item.agentId ?? item.agentName} className="rounded border border-slate-800 bg-[#0d1115] p-2">
                          <div className="flex items-center justify-between gap-2">
                            <div className="text-xs font-black text-slate-200">{item.agentName ?? item.agentId}</div>
                            <div className={`rounded border px-2 py-1 text-[9px] font-black uppercase tracking-widest ${item.status === "clear" ? "border-emerald-400/40 bg-emerald-950/25 text-emerald-100" : item.status === "blocked" ? "border-red-400/40 bg-red-950/25 text-red-100" : "border-amber-400/40 bg-amber-950/25 text-amber-100"}`}>
                              {item.status ?? "review"}
                            </div>
                          </div>
                          <div className="mt-1 text-[11px] leading-relaxed text-slate-500">{item.finding}</div>
                        </div>
                      )) : <div className="rounded border border-slate-800 bg-[#0d1115] p-2 text-xs text-slate-500">Generate a draft to see reviewer flags.</div>}
                    </div>
                    <div className="mt-3 text-[10px] font-black uppercase tracking-widest text-slate-500">Messages</div>
                    <div className="mt-2 grid gap-2">
                      {draft.messages.map((item) => (
                        <div key={item.channel} className="rounded border border-slate-800 bg-[#0d1115] p-2">
                          <div className="text-xs font-black text-slate-200">{item.channel}</div>
                          <div className="mt-1 text-[11px] leading-relaxed text-slate-500">{item.owner ?? "real owner needed"}</div>
                        </div>
                      ))}
                    </div>
                    </div>
                  </aside>
                </div>
              ) : null}
            </div>
          </div>
        </section>

        <section className="rounded-lg border border-slate-800 bg-[#151914] p-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-lime-200">Full park profile</div>
              <h2 className="mt-1 text-2xl font-black text-white">{venueIdentity?.name ?? "No active park profile"}</h2>
              <p className="mt-2 max-w-4xl text-sm leading-relaxed text-slate-400">
                {venueIdentity?.description ?? "Activate a venue profile or import a customer venue export to populate park identity, public zones, guest locations, safety facts, and channel ownership."}
              </p>
            </div>
            <div className={`w-fit rounded border px-2 py-1 text-[10px] font-black uppercase tracking-widest ${statusClass(readinessStatus)}`}>
              {formatStatus(venueIdentity?.profileType ?? readinessStatus)}
            </div>
          </div>

          <div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
            <div className="rounded border border-slate-800 bg-[#0d1115] p-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Identity and zones</div>
                  <div className="mt-1 text-sm font-black text-white">{venueIdentity?.venueId ?? "venue not connected"}</div>
                </div>
                <div className="grid grid-cols-5 gap-2 text-center text-[10px] font-black uppercase tracking-widest text-slate-400">
                  <div className="rounded border border-slate-800 bg-[#151914] px-2 py-1">{readinessCounts.locations ?? 0}<br />loc</div>
                  <div className="rounded border border-slate-800 bg-[#151914] px-2 py-1">{readinessCounts.indoorLocations ?? 0}<br />in</div>
                  <div className="rounded border border-slate-800 bg-[#151914] px-2 py-1">{readinessCounts.accessibleRoutes ?? 0}<br />acc</div>
                  <div className="rounded border border-slate-800 bg-[#151914] px-2 py-1">{readinessCounts.safetyInstructions ?? 0}<br />safe</div>
                  <div className="rounded border border-slate-800 bg-[#151914] px-2 py-1">{readinessCounts.channelOwners ?? 0}<br />own</div>
                </div>
              </div>
              <div className="mt-3 grid gap-2 md:grid-cols-2">
                {(venueIdentity?.publicZones ?? []).map((zone) => (
                  <div key={zone.id ?? zone.name} className="rounded border border-slate-800 bg-[#151914] px-3 py-2">
                    <div className="text-sm font-black text-white">{zone.name ?? zone.id}</div>
                    <div className="mt-1 text-[11px] leading-relaxed text-slate-500">{zone.position ?? "public zone"}</div>
                  </div>
                ))}
                {!venueIdentity?.publicZones?.length ? <div className="rounded border border-slate-800 bg-[#151914] p-3 text-xs text-slate-500">No public zones connected.</div> : null}
              </div>
            </div>

            <div className="rounded border border-slate-800 bg-[#0d1115] p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Owners and source</div>
              <div className="mt-3 grid gap-2">
                {channelOwnerEntries.map(([channel, owner]) => (
                  <div key={channel} className="grid grid-cols-[8rem_1fr] gap-2 rounded border border-slate-800 bg-[#151914] px-3 py-2 text-xs">
                    <span className="font-black uppercase tracking-widest text-slate-500">{formatStatus(channel)}</span>
                    <span className="font-bold text-slate-200">{owner}</span>
                  </div>
                ))}
                {!channelOwnerEntries.length ? <div className="rounded border border-slate-800 bg-[#151914] p-3 text-xs text-slate-500">No channel owners connected.</div> : null}
              </div>
              <div className="mt-3 rounded border border-slate-800 bg-[#151914] p-3 text-xs leading-relaxed text-slate-500">
                <div className="font-black uppercase tracking-widest text-slate-400">Source</div>
                <div className="mt-1 break-words">{readiness?.realInputs?.source ?? "not connected"}</div>
              </div>
            </div>
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-3">
            {[
              ["Attractions", profileGroups.attractions],
              ["Dining", profileGroups.dining],
              ["Shows", profileGroups.shows],
              ["Quiet and cooling", profileGroups.quiet],
              ["Services", profileGroups.services],
              ["Map nodes", profileGroups.map],
            ].map(([label, rows]) => {
              const items = rows as VenueLocationDetail[];
              return (
                <div key={label as string} className="rounded border border-slate-800 bg-[#0d1115] p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label as string}</div>
                    <div className="rounded border border-slate-800 bg-[#151914] px-2 py-1 text-[10px] font-black text-slate-400">{items.length}</div>
                  </div>
                  <div className="mt-3 grid gap-2">
                    {items.slice(0, 8).map((item) => (
                      <div key={`${item.kind}-${item.name}`} className="rounded border border-slate-800 bg-[#151914] p-3">
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <div>
                            <div className="text-sm font-black text-white">{item.name}</div>
                            <div className="mt-1 text-[11px] font-bold uppercase tracking-widest text-slate-500">{kindLabel(item.kind)}{item.zoneId ? ` / ${item.zoneId}` : ""}</div>
                          </div>
                          <div className="flex flex-wrap gap-1">
                            {item.indoor ? <span className="rounded border border-cyan-400/30 bg-cyan-950/20 px-2 py-1 text-[9px] font-black uppercase tracking-widest text-cyan-100">Indoor</span> : null}
                            {item.covered ? <span className="rounded border border-lime-400/30 bg-lime-950/20 px-2 py-1 text-[9px] font-black uppercase tracking-widest text-lime-100">Covered</span> : null}
                            {item.accessible ? <span className="rounded border border-emerald-400/30 bg-emerald-950/20 px-2 py-1 text-[9px] font-black uppercase tracking-widest text-emerald-100">Accessible</span> : null}
                          </div>
                        </div>
                        {item.category || item.cuisine || item.familyFit || item.seating ? (
                          <p className="mt-2 text-xs leading-relaxed text-slate-400">{item.category ?? item.cuisine ?? item.familyFit ?? item.seating}</p>
                        ) : null}
                        {item.accessibilityNote ? <p className="mt-2 text-[11px] leading-relaxed text-slate-500">{item.accessibilityNote}</p> : null}
                        {item.sensoryNote ? <p className="mt-1 text-[11px] leading-relaxed text-slate-500">{item.sensoryNote}</p> : null}
                        {item.bestFor?.length ? <p className="mt-1 text-[11px] leading-relaxed text-slate-500">Best for {compactList(item.bestFor, 4)}.</p> : null}
                        {item.services?.length ? <p className="mt-1 text-[11px] leading-relaxed text-slate-500">Services: {compactList(item.services, 4)}.</p> : null}
                        {item.dietaryTags?.length ? <p className="mt-1 text-[11px] leading-relaxed text-slate-500">Tags: {compactList(item.dietaryTags, 4)}.</p> : null}
                      </div>
                    ))}
                    {items.length > 8 ? <div className="rounded border border-slate-800 bg-[#151914] p-2 text-xs text-slate-500">+{items.length - 8} more records in the active export.</div> : null}
                    {!items.length ? <div className="rounded border border-slate-800 bg-[#151914] p-3 text-xs text-slate-500">No records connected.</div> : null}
                  </div>
                </div>
              );
            })}
          </div>

          <div className="mt-4 rounded border border-slate-800 bg-[#0d1115] p-3">
            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Safety and guest instructions</div>
            <div className="mt-3 grid gap-2 lg:grid-cols-2">
              {safetyInstructions.map((instruction) => (
                <div key={instruction} className="rounded border border-slate-800 bg-[#151914] p-3 text-xs leading-relaxed text-slate-300">{instruction}</div>
              ))}
              {!safetyInstructions.length ? <div className="rounded border border-slate-800 bg-[#151914] p-3 text-xs text-slate-500">No safety instructions connected.</div> : null}
            </div>
          </div>
        </section>

        <section className="grid gap-5 xl:grid-cols-[380px_minmax(0,1fr)]">
          <aside className="space-y-5">
            <div className="rounded-lg border border-slate-800 bg-[#151914] p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-[10px] font-black uppercase tracking-widest text-lime-200">Current runtime</div>
                  <h2 className="mt-1 text-lg font-black text-white">Venue data readiness</h2>
                </div>
                <button
                  type="button"
                  onClick={() => void refreshReadiness()}
                  disabled={isLoading}
                  className="rounded border border-slate-700 bg-[#0d1115] px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-300 transition hover:border-lime-300 disabled:opacity-50"
                >
                  Refresh
                </button>
              </div>
              <div className={`mt-3 w-fit rounded border px-2 py-1 text-[10px] font-black uppercase tracking-widest ${statusClass(readinessStatus)}`}>
                {formatStatus(readinessStatus)}
              </div>
              {venueIdentity ? (
                <div className="mt-3 rounded border border-slate-800 bg-[#0d1115] p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-lime-200">Active park</div>
                  <div className="mt-1 text-base font-black text-white">{venueIdentity.name ?? "Unspecified venue"}</div>
                  <div className="mt-1 text-[11px] font-bold uppercase tracking-widest text-slate-500">{formatStatus(venueIdentity.profileType)}</div>
                  {venueIdentity.description ? <p className="mt-2 text-xs leading-relaxed text-slate-400">{venueIdentity.description}</p> : null}
                  {venueIdentity.publicZones?.length ? (
                    <div className="mt-3 grid gap-1 text-xs text-slate-400">
                      {venueIdentity.publicZones.slice(0, 5).map((zone) => (
                        <div key={zone.id ?? zone.name} className="flex justify-between gap-2">
                          <span className="font-bold text-slate-200">{zone.name ?? zone.id}</span>
                          <span className="text-right text-slate-500">{zone.position ?? ""}</span>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}
              <div className="mt-3 grid gap-2 text-xs">
                {[
                  ["Autofill", readiness?.readiness?.autofillAllowed ? "allowed" : "blocked"],
                  ["Handoff", readiness?.readiness?.handoffReady ? "ready" : "blocked"],
                  ["Seed data", readiness?.sourceIntegrity?.usesSeedData ? "detected" : "not used"],
                  ["Sample data", readiness?.sourceIntegrity?.usesSampleData ? "blocked" : "not active"],
                  ["Source", profileSourceMode],
                  ["Profile", formatStatus(readiness?.sourceIntegrity?.profileType)],
                ].map(([label, value]) => (
                  <div key={label} className="grid grid-cols-[7rem_1fr] gap-2 rounded border border-slate-800 bg-[#0d1115] px-3 py-2">
                    <span className="font-black uppercase tracking-widest text-slate-500">{label}</span>
                    <span className="font-bold text-slate-200">{value}</span>
                  </div>
                ))}
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-400">
                <div>Locations: {readinessCounts.locations ?? 0}</div>
                <div>Indoor: {readinessCounts.indoorLocations ?? 0}</div>
                <div>Access: {readinessCounts.accessibleRoutes ?? 0}</div>
                <div>Safety: {readinessCounts.safetyInstructions ?? 0}</div>
                <div>Owners: {readinessCounts.channelOwners ?? 0}</div>
              </div>
            </div>

            <div className="rounded-lg border border-amber-300/25 bg-[#151914] p-4">
              <div className="text-[10px] font-black uppercase tracking-widest text-amber-200">Venue Profile gate</div>
              <h2 className="mt-1 text-lg font-black text-white">Required profile data</h2>
              <div className="mt-3 grid gap-2 text-xs leading-relaxed text-slate-400">
                {requiredFields.map((item) => <div key={item} className="rounded border border-slate-800 bg-[#0d1115] px-3 py-2">{item}</div>)}
              </div>
              <p className="mt-3 text-xs leading-relaxed text-slate-500">
                Venue Profile owns source validation, import preview, activation, and synthetic test loading. Studio only consumes the active approved profile.
              </p>
              <a
                href="/venue-profile"
                className="mt-3 flex w-full justify-center rounded border border-amber-300 bg-amber-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-amber-200"
              >
                Manage Venue Profile
              </a>
              <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
                Active source: {profileSourceMode}. Source names containing sample, demo, seed, test, or fake remain blocked in Venue Profile.
              </p>
            </div>

            <div className="rounded-lg border border-slate-800 bg-[#151914] p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-[10px] font-black uppercase tracking-widest text-cyan-200">Saved drafts</div>
                  <h2 className="mt-1 text-lg font-black text-white">Studio work queue</h2>
                </div>
                <button
                  type="button"
                  onClick={() => void refreshSavedDrafts()}
                  className="rounded border border-slate-700 bg-[#0d1115] px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-300 transition hover:border-cyan-300"
                >
                  Refresh
                </button>
              </div>
              <div className="mt-3 grid gap-2">
                {savedDrafts.length ? (
                  savedDrafts.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => void openSavedDraft(item)}
                      disabled={isWorkflowBusy}
                      className={`rounded border p-3 text-left transition disabled:opacity-50 ${activeDraftId === item.id ? "border-cyan-300 bg-cyan-300 text-slate-950" : "border-slate-800 bg-[#0d1115] text-slate-300 hover:border-cyan-300/70"}`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-sm font-black">{item.title ?? "Untitled draft"}</span>
                        <span className={`rounded border px-2 py-1 text-[9px] font-black uppercase tracking-widest ${workflowClass(item.status)}`}>{(item.status ?? "draft").replaceAll("_", " ")}</span>
                      </div>
                      <div className={`mt-1 text-xs leading-relaxed ${activeDraftId === item.id ? "text-slate-800" : "text-slate-500"}`}>
                        {item.routeStopCount ?? 0} stops / {item.messageCount ?? 0} messages / {item.handoffCount ?? 0} handoffs
                      </div>
                      {item.latestNote ? <div className={`mt-1 truncate text-[11px] ${activeDraftId === item.id ? "text-slate-800" : "text-slate-500"}`}>{item.latestNote}</div> : null}
                    </button>
                  ))
                ) : (
                  <div className="rounded border border-slate-800 bg-[#0d1115] p-3 text-xs leading-relaxed text-slate-500">No saved drafts yet.</div>
                )}
              </div>
            </div>
          </aside>

          <section className="rounded-lg border border-slate-800 bg-[#151914] p-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-lime-200">Profile dependency</div>
                <h2 className="mt-1 text-2xl font-black text-white">Experience Studio reads the active Venue Profile</h2>
                <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-400">
                  Park data changes now happen in the global profile layer. Draft generation, source-integrity gates, channel ownership, accessibility notes, and handoff checks all read from the same active profile.
                </p>
              </div>
              <div className={`w-fit rounded border px-2 py-1 text-[10px] font-black uppercase tracking-widest ${statusClass(readinessStatus)}`}>
                {formatStatus(readinessStatus)}
              </div>
            </div>

            <div className="mt-5 grid gap-3 lg:grid-cols-3">
              {[
                ["Active profile", venueIdentity?.name ?? "Not connected"],
                ["Source mode", profileSourceMode],
                ["Loaded from", readiness?.readiness?.loadedFrom ?? "not connected"],
              ].map(([label, value]) => (
                <div key={label} className="rounded border border-slate-800 bg-[#0d1115] p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                  <div className="mt-2 text-sm font-black text-slate-100">{value}</div>
                </div>
              ))}
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
              <a
                href="/venue-profile"
                className="rounded border border-lime-300 bg-lime-300 px-4 py-2 text-sm font-black text-slate-950 transition hover:bg-lime-200"
              >
                Open Venue Profile
              </a>
              <button
                type="button"
                onClick={() => void refreshReadiness()}
                disabled={isLoading}
                className="rounded border border-slate-700 bg-[#0d1115] px-4 py-2 text-sm font-black text-slate-200 transition hover:border-lime-300 disabled:opacity-50"
              >
                {isLoading ? "Refreshing" : "Refresh profile"}
              </button>
              {message ? <div className="rounded border border-slate-800 bg-[#0d1115] px-3 py-2 text-sm font-bold text-slate-300">{message}</div> : null}
            </div>

            <div className="mt-5 rounded border border-slate-800 bg-[#0d1115] p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Profile readiness findings</div>
              <div className="mt-3 grid gap-2">
                {issues.length ? (
                  issues.map((issue) => (
                    <div key={`${issue.id}-${issue.field}-${issue.detail}`} className="rounded border border-slate-800 bg-[#151914] p-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={`rounded border px-2 py-1 text-[10px] font-black uppercase tracking-widest ${issue.severity === "critical" ? "border-red-400/40 bg-red-950/25 text-red-100" : "border-amber-400/40 bg-amber-950/25 text-amber-100"}`}>
                          {issue.severity ?? "issue"}
                        </span>
                        <span className="text-xs font-black uppercase tracking-widest text-slate-300">{issueLabel(issue)}</span>
                      </div>
                      <div className="mt-2 text-sm leading-relaxed text-slate-400">{issue.detail}</div>
                    </div>
                  ))
                ) : (
                  <div className="text-sm text-slate-400">No readiness findings. Studio can generate from the active profile.</div>
                )}
              </div>
            </div>
          </section>
        </section>
      </div>
    </main>
  );
}
