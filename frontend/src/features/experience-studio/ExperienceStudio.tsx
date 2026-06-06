"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { fetchParkPulseApi, longRunningRequestTimeoutMs } from "@/lib/api";

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

type ExperienceReasoning = {
  status?: string;
  mode?: string;
  selectedConceptId?: string;
  selectedConceptLabel?: string;
  qualityScores?: Record<string, number>;
  decision?: {
    whySelected?: string;
    route?: string[];
    totalScore?: number;
    decisiveEvidence?: string[];
    rejectedAlternatives?: Array<{ id?: string; label?: string; whyNot?: string; scoreDelta?: number }>;
  };
  conceptRoutes?: Array<{
    id?: string;
    label?: string;
    positioning?: string;
    route?: string[];
    scores?: Record<string, number>;
    totalScore?: number;
    decisiveEvidence?: string[];
    riskFlags?: string[];
  }>;
  critiqueAndRevision?: {
    weakPointsFound?: string[];
    revisionsApplied?: string[];
  };
  guestLenses?: Array<{ guest?: string; likelyExperience?: string; designResponse?: string }>;
};

type CreativeConcept = {
  id?: string;
  name?: string;
  positioning?: string;
  guestPromise?: string;
  storyArc?: string[];
  heroTerms?: string[];
  route?: string[];
  channelFocus?: string[];
  reviewRisks?: string[];
  whyItWorks?: string;
  scores?: Record<string, number>;
  totalScore?: number;
};

type CreativeSynthesis = {
  status?: string;
  mode?: string;
  selectedConceptId?: string;
  selectedConceptName?: string;
  selectedConcept?: CreativeConcept;
  concepts?: CreativeConcept[];
  decision?: {
    whySelected?: string;
    rejectedAlternatives?: Array<{ id?: string; name?: string; whyNot?: string; scoreDelta?: number }>;
  };
  copyVariants?: {
    guestApp?: { headline?: string; body?: string; microcopy?: string };
    signage?: Array<{ placement?: string; headline?: string; body?: string }>;
    email?: { subject?: string; previewText?: string; body?: string };
    staffCue?: { opening?: string; transition?: string; boundary?: string };
  };
  rewriteStrategy?: {
    useMoreOf?: string[];
    preserve?: string[];
    avoid?: string[];
  };
  llmPolish?: {
    status?: string;
    acceptedFields?: number;
    rejectedFields?: Array<{ field?: string; reason?: string }>;
    guardrails?: string[];
  };
};

type ExperienceDraft = {
  title: string;
  audience: string;
  intent: string;
  studioCore?: StudioCore;
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
  creativePackage?: {
    version?: string;
    executiveConcept?: {
      name?: string;
      oneLine?: string;
      guestPromise?: string;
      whyNow?: string;
      successMetric?: string;
    };
    journeyMap?: Array<{
      order?: number;
      stop?: string;
      emotionalBeat?: string;
      guestNeed?: string;
      guestCopy?: string;
      staffCue?: string;
      accessibilityCheck?: string;
      guestDecision?: string;
      proofNeeded?: string[];
    }>;
    routeBlueprint?: Array<{
      order?: number;
      stop?: string;
      storyBeat?: string;
      guestAction?: string;
      hostAction?: string;
      contentJob?: string;
      accessibilityCheck?: string;
      proofNeeded?: string[];
      fallbackIfBusy?: string;
    }>;
    experienceBeats?: Array<{ beat?: string; detail?: string }>;
    sectionDossiers?: Array<{ section?: string; purpose?: string; details?: string[]; reviewGate?: string }>;
    sectionCreativeDetails?: {
      conceptBoard?: Record<string, unknown>;
      routeStoryCards?: Array<{
        order?: number;
        stop?: string;
        beat?: string;
        guestFacingMoment?: string;
        designerIntent?: string;
        staffCue?: string;
        transitionLine?: string;
        choiceArchitecture?: string;
        proofBeforePublish?: string[];
      }>;
      channelArtifactBriefs?: Array<{
        channel?: string;
        owner?: string;
        jobToBeDone?: string;
        draftArtifact?: unknown;
        headline?: string;
        microcopy?: string;
        reviewQuestion?: string;
        productionRisk?: string;
      }>;
      signageProductionCards?: Array<{ placement?: string; headline?: string; body?: string; format?: string; readabilityCheck?: string }>;
      emailModules?: Record<string, unknown>;
      staffRehearsalNotes?: string[];
    };
    channelMatrix?: Array<{ channel?: string; owner?: string; objective?: string; headline?: string; microcopy?: string; primaryCopy?: unknown; rules?: string[]; reviewQuestion?: string }>;
    staffScript?: Record<string, string>;
    staffRunOfShow?: Array<{ phase?: string; who?: string; detail?: string; reviewGate?: string }>;
    signageSet?: Array<{ placement?: string; headline?: string; body?: string }>;
    preArrivalEmail?: { subject?: string; previewText?: string; body?: string };
    craftArtifacts?: {
      status?: string;
      purpose?: string;
      samples?: Array<{ id?: string; label?: string; channel?: string; copy?: string; whyItHelps?: string; reviewGate?: string }>;
      craftNotes?: string[];
    };
    productionDetail?: {
      guestChoiceModel?: string[];
      contentCompletenessChecklist?: string[];
      measurementPlan?: Array<{ metric?: string; signal?: string; learningUse?: string }>;
      localizationNotes?: string[];
    };
    accessibilityReviewPacket?: {
      mustVerify?: string[];
      profileQualityGaps?: string[];
      routeChecks?: Array<{ stop?: string; accessibilityNote?: string; source?: string }>;
    };
    ownerQuestions?: Array<{ owner?: string; question?: string }>;
    copyVoice?: {
      tone?: string;
      brandTone?: string[];
      avoid?: string[];
      approvedPhrases?: string[];
      thematicLexicon?: Record<string, string[]>;
    };
    venuePattern?: {
      id?: string;
      recommendedArc?: string[];
      mustInclude?: string[];
      avoidClaims?: string[];
      channelRules?: Record<string, string[]>;
    };
    creativePackageVariants?: Array<{
      id?: string;
      name?: string;
      status?: string;
      positioning?: string;
      guestPromise?: string;
      routeFrame?: string;
      channelEmphasis?: string[];
      strengths?: string[];
      reviewRisks?: string[];
      whenToUse?: string;
    }>;
    memoryInfluence?: {
      status?: string;
      mode?: string;
      usedForGeneration?: boolean;
      authority?: string;
      matchedCount?: number;
      reusablePatterns?: string[];
      avoidPatterns?: string[];
      matchedExamples?: Array<{ draftId?: string; status?: string; selectedConceptName?: string; updatedAt?: string; route?: string[] }>;
      learningBoundary?: string;
    };
    memoryApplication?: {
      status?: string;
      usedForGeneration?: boolean;
      visibleChanges?: string[];
      preservedPatterns?: string[];
      avoidedPatterns?: string[];
      approvedRulesApplied?: string[];
      reviewBoundary?: string;
      matchedDrafts?: Array<{ draftId?: string; status?: string; selectedConceptName?: string; route?: string[] }>;
    };
    approvedRuleInfluence?: {
      status?: string;
      mode?: string;
      usedForGeneration?: boolean;
      authority?: string;
      ruleCount?: number;
      appliedRules?: string[];
      guardrails?: string[];
      learningBoundary?: string;
    };
    venueDataGapAnalysis?: {
      status?: string;
      profileType?: string;
      creativeReady?: boolean;
      productionRealVenueReady?: boolean;
      missingForProduction?: string[];
      nextProfileImports?: string[];
      routeChecks?: Array<{ stop?: string; hasAccessibilityNote?: boolean; hasProfileFact?: boolean; stillNeeds?: string[] }>;
    };
    vertexModelOrchestration?: {
      status?: string;
      mode?: string;
      slotCount?: number;
      readyOrPlannedSlotCount?: number;
      providerReadiness?: {
        provider?: string;
        platform?: string;
        ready?: boolean;
        projectConfigured?: boolean;
        locationConfigured?: boolean;
        credentialsMode?: string;
        readinessIssues?: string[];
        requiredEnv?: string[];
      };
      slots?: Array<{
        id?: string;
        label?: string;
        model?: string;
        status?: string;
        purpose?: string;
        expectedOutputs?: string[];
        guardrails?: string[];
        llmControlsPublishOrOperations?: boolean;
      }>;
      activation?: {
        useLiveTextWriter?: string;
        vertexEnv?: string[];
        mediaEnv?: string[];
      };
      boundary?: string;
    };
    studioQualityEval?: {
      status?: string;
      score?: number;
      demoScore?: number;
      productionScore?: number;
      scores?: Record<string, number>;
      gateSummary?: { passed?: number; review?: number; blocked?: number };
      gateResults?: Array<{ id?: string; status?: string; severity?: string; evidence?: string }>;
      reviewerPanel?: {
        status?: string;
        consensusScore?: number;
        summary?: string;
        reviewers?: Array<{ reviewerId?: string; role?: string; score?: number; gateStatus?: string; finding?: string; requiredRevision?: string }>;
        revisionQueue?: Array<{ reviewerId?: string; role?: string; status?: string; requiredRevision?: string }>;
      };
      venueReflection?: {
        status?: string;
        score?: number;
        summary?: string;
        profileType?: string;
        gateSummary?: { passed?: number; review?: number; blocked?: number };
        dimensions?: Array<{ id?: string; label?: string; score?: number; evidence?: string; missing?: string[] }>;
        routeCoverage?: Record<string, unknown>;
        productionBoundary?: { status?: string; reason?: string; missingForProduction?: string[] };
      };
      reviewLoop?: {
        status?: string;
        consensusScore?: number;
        revisionQueue?: Array<{ reviewerId?: string; role?: string; status?: string; requiredRevision?: string }>;
        learningUse?: string;
      };
      findings?: string[];
      qaChecklist?: Array<{ check?: string; status?: string }>;
      recommendedNextActions?: string[];
    };
    reviewAgentReview?: ExperienceReviewAgent;
    designReasoning?: ExperienceReasoning;
    creativeSynthesis?: CreativeSynthesis;
  };
  experienceReasoning?: ExperienceReasoning;
  creativeSynthesis?: CreativeSynthesis;
  productionNotes: string[];
  reasoningTrace?: Array<{
    step?: string;
    summary?: string;
    inputs?: Record<string, unknown>;
  }>;
  llmCreativePass?: {
    status?: string;
    routeAccepted?: boolean;
    synthesisAcceptedFields?: number;
    synthesisRejectedFields?: Array<{ field?: string; reason?: string }>;
    creativeRationale?: string[];
    reviewQuestions?: string[];
    guardrails?: string[];
  };
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
    profileIntelligenceStatus?: string;
    usesApprovedSyntheticProfile?: boolean;
    profileType?: string;
    realVenueReady?: boolean;
    productionRealVenueReady?: boolean;
    missingProductionRealVenueInputs?: string[];
  };
  experienceReviewAgent?: ExperienceReviewAgent;
};

type ExperienceReviewAgent = {
  agentId?: string;
  agentName?: string;
  status?: string;
  score?: number;
  reviewMode?: string;
  findings?: string[];
  sectionTargets?: Array<{ section?: string; reason?: string }>;
  approvalRecommendation?: string;
  memoryJudgment?: {
    memoryUsed?: boolean;
    rulesUsed?: boolean;
    boundary?: string;
  };
  nextActions?: string[];
};

type SectionRevisionPayload = {
  status?: string;
  mode?: string;
  sectionId?: string;
  feedback?: string;
  draft?: ExperienceDraft;
  beforeSection?: unknown;
  afterSection?: unknown;
  qaDelta?: {
    before?: number;
    after?: number;
    delta?: number;
    scores?: Record<string, { before?: number; after?: number; delta?: number }>;
  };
  reviewAgent?: ExperienceReviewAgent;
};

type StudioCore = {
  id?: string;
  version?: string;
  source?: string;
  mission?: string;
  coreValues?: string[];
  creativePrinciples?: string[];
  reasoningPriorities?: string[];
  voiceDefaults?: string[];
  antiPatterns?: string[];
};

type DraftPayload = {
  status?: string;
  mode?: string;
  draft?: ExperienceDraft;
  studioCore?: StudioCore;
  llm?: {
    status?: string;
    error?: string;
    mergeStatus?: string;
    creative_rationale?: string[];
    review_questions?: string[];
  };
  venueExperienceData?: VenueDataPayload;
  sourceIntegrity?: {
    venueExperienceDataAttached?: boolean;
    usesSeedData?: boolean;
    usesSimulatedParkState?: boolean;
  };
  memoryPersistence?: {
    status?: string;
    mode?: string;
    connected?: boolean;
    collection?: string;
    memoryId?: string | null;
    learningEligible?: boolean;
    learningSource?: string;
    error?: string;
  };
};

type ConversationPlanPayload = {
  status?: string;
  mode?: string;
  id?: string;
  request?: string;
  planningMode?: string;
  parsedBrief?: {
    templateId?: ExperienceTemplateId;
    templateLabel?: string;
    goal?: string;
    audience?: string;
    tone?: string;
    constraints?: string;
    successMetric?: string;
    guestCommitment?: string;
    approvedComfortClaims?: string[];
    rewardRule?: string;
    reviewOwner?: string;
    targetSegment?: string | null;
    channelTargets?: string[];
    source?: string;
  };
  answeredQuestionIds?: string[];
  missingInputs?: string[];
  clarifyingQuestions?: Array<{ id?: string; question?: string; whyItMatters?: string }>;
  conceptOptions?: Array<{
    id?: string;
    label?: string;
    rationale?: string;
    risk?: string;
    profileFit?: {
      routePatternId?: string;
      mustInclude?: string[];
      preferredStops?: string[];
      segmentNeeds?: string[];
      channelTargets?: string[];
      avoidClaims?: string[];
      channelRules?: Record<string, string[]>;
    };
    payload?: Partial<Record<string, unknown>>;
  }>;
  plannerIntelligence?: {
    targetSegment?: {
      id?: string;
      label?: string;
      decisionDrivers?: string[];
      storyNeeds?: string[];
      avoid?: string[];
    };
    routePattern?: {
      id?: string;
      recommendedArc?: string[];
      preferredStops?: string[];
      mustInclude?: string[];
      avoidClaims?: string[];
    };
    channelTargets?: string[];
    profileEvidence?: {
      experienceRuleKeys?: string[];
      hasRoutePattern?: boolean;
      signatureStoryAnchorCount?: number;
    };
    refinementPrompts?: Array<{ id?: string; question?: string; whyItMatters?: string }>;
  };
  recommendedOptionId?: string;
  recommendedPlan?: {
    label?: string;
    why?: string;
    payload?: Partial<Record<string, unknown>>;
  };
  qualityRubric?: Array<{ id?: string; label?: string; status?: string; check?: string }>;
  studioCore?: StudioCore;
  venueExperienceData?: VenueDataPayload;
  sourceIntegrity?: {
    usesSeedData?: boolean;
    usesInventedLocations?: boolean;
    realInputSource?: string;
    realInputCount?: number;
    missingRealInputs?: string[];
  };
  memoryPersistence?: {
    status?: string;
    mode?: string;
    connected?: boolean;
    collection?: string;
    memoryId?: string | null;
    learningEligible?: boolean;
    learningSource?: string;
  };
};

type PlannerTurn = {
  role: "designer" | "studio";
  content: string;
  at: string;
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

type StudioMemoryReceipt = {
  _id?: string;
  id?: string;
  eventType?: string;
  collection?: string;
  memoryId?: string | null;
  status?: string;
  mode?: string;
  connected?: boolean;
  draftId?: string;
  handoffId?: string;
  reviewStatus?: string;
  learningEligible?: boolean;
  learningSource?: string;
  title?: string;
  templateId?: string;
  updatedAt?: string;
  createdAt?: string;
};

type StudioMemoryPayload = {
  status?: string;
  mode?: string;
  memoryLayer?: string;
  memoryConnection?: {
    connected?: boolean;
    mode?: string;
    database?: string;
    primary?: string;
    fallbackPath?: string | null;
  };
  learningPolicy?: {
    primaryMemory?: string;
    analyticsMirror?: string;
    rule?: string;
    presetCoreId?: string;
    generatedTextLearningEligible?: boolean;
    humanFeedbackLearningEligible?: boolean;
  };
  collectionCounts?: Record<string, number>;
  collections?: Record<string, StudioMemoryReceipt[]>;
  latestReceipts?: StudioMemoryReceipt[];
  retentionPolicy?: Record<string, { collection?: string; retentionDays?: number | null; purpose?: string }>;
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

const studioMemoryCollectionMeta = [
  { id: "experience_studio_generation_runs", label: "generation runs" },
  { id: "experience_studio_drafts", label: "drafts" },
  { id: "experience_studio_feedback", label: "feedback" },
  { id: "experience_studio_revision_events", label: "revisions" },
  { id: "experience_studio_learning_rules", label: "learning rules" },
];

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

function formatTimestamp(value?: string) {
  if (!value) return "time unknown";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
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
  const [useCreativeReasoning, setUseCreativeReasoning] = useState(true);
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
  const [isPromotingRule, setIsPromotingRule] = useState(false);
  const [isRevisingSection, setIsRevisingSection] = useState(false);
  const [revisionSection, setRevisionSection] = useState("staff_script");
  const [revisionFeedback, setRevisionFeedback] = useState("Make this section more magical, but keep accessibility plain and make staff language less operational.");
  const [latestSectionRevision, setLatestSectionRevision] = useState<SectionRevisionPayload | null>(null);
  const [showAdvancedReview, setShowAdvancedReview] = useState(false);
  const [studioMemory, setStudioMemory] = useState<StudioMemoryPayload | null>(null);
  const [isLoadingMemory, setIsLoadingMemory] = useState(false);
  const [conversationInput, setConversationInput] = useState(
    "Create a rainy-day family journey that keeps guests comfortable, uses verified indoor or covered locations, and produces app, signage, email, and staff cue copy.",
  );
  const [conversationPlan, setConversationPlan] = useState<ConversationPlanPayload | null>(null);
  const [isPlanningConversation, setIsPlanningConversation] = useState(false);
  const [isGeneratingFromPlan, setIsGeneratingFromPlan] = useState(false);
  const [plannerTurns, setPlannerTurns] = useState<PlannerTurn[]>([]);
  const [plannerReply, setPlannerReply] = useState("Success metric is guest comfort and pre-arrival clarity. Guest commitment is a short optional moment. Approved comfort claims are indoor stop, covered path, seating, and step-free access. Review owner is CRM.");

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

  const refreshStudioMemory = async () => {
    setIsLoadingMemory(true);
    try {
      const response = await fetchParkPulseApi("/api/park/experience-studio/memory?limit=12", { timeoutMs: 5000 });
      setStudioMemory(await response.json() as StudioMemoryPayload);
    } catch {
      setStudioMemory({
        status: "unavailable",
        mode: "experience_studio_memory",
        memoryLayer: "not connected",
        collectionCounts: {},
        latestReceipts: [],
        collections: {},
        learningPolicy: {
          rule: "Studio memory endpoint unavailable.",
          generatedTextLearningEligible: false,
          humanFeedbackLearningEligible: false,
        },
      });
    } finally {
      setIsLoadingMemory(false);
    }
  };

  useEffect(() => {
    void refreshStudioMemory();
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

  const valueFromPlan = (payload: Partial<Record<string, unknown>> | undefined, key: string, fallback: string) => {
    const value = payload?.[key];
    return typeof value === "string" && value.trim() ? value : fallback;
  };

  const applyRecommendedPlan = (plan: ConversationPlanPayload | null = conversationPlan) => {
    const payload = plan?.recommendedPlan?.payload;
    if (!payload) {
      setMessage("Shape a conversational plan before applying it");
      return false;
    }
    const nextTemplate = valueFromPlan(payload, "templateId", templateId) as ExperienceTemplateId;
    if (draftTemplates.some((item) => item.id === nextTemplate)) setTemplateId(nextTemplate);
    setAudience(valueFromPlan(payload, "audience", audience));
    setTone(valueFromPlan(payload, "tone", tone));
    setConstraints(valueFromPlan(payload, "constraints", constraints));
    setCreativeDirection(valueFromPlan(payload, "creativeDirection", creativeDirection));
    setStoryArc(valueFromPlan(payload, "storyArc", storyArc));
    setSensoryLevel(valueFromPlan(payload, "sensoryLevel", sensoryLevel));
    setWalkingPace(valueFromPlan(payload, "walkingPace", walkingPace));
    setOutputPackage(valueFromPlan(payload, "outputPackage", outputPackage));
    setSeasonalTheme(valueFromPlan(payload, "seasonalTheme", seasonalTheme));
    setMessage("Recommended plan applied to the generator inputs");
    return true;
  };

  const generateDraft = async (overridePayload?: Partial<Record<string, unknown>>) => {
    setIsDrafting(true);
    setMessage(null);
    const currentTemplateId = valueFromPlan(overridePayload, "templateId", templateId) as ExperienceTemplateId;
    const currentAudience = valueFromPlan(overridePayload, "audience", audience);
    const currentTone = valueFromPlan(overridePayload, "tone", tone);
    const currentConstraints = valueFromPlan(overridePayload, "constraints", constraints);
    const currentCreativeDirection = valueFromPlan(overridePayload, "creativeDirection", creativeDirection);
    const currentStoryArc = valueFromPlan(overridePayload, "storyArc", storyArc);
    const currentSensoryLevel = valueFromPlan(overridePayload, "sensoryLevel", sensoryLevel);
    const currentWalkingPace = valueFromPlan(overridePayload, "walkingPace", walkingPace);
    const currentOutputPackage = valueFromPlan(overridePayload, "outputPackage", outputPackage);
    const currentSeasonalTheme = valueFromPlan(overridePayload, "seasonalTheme", seasonalTheme);
    const composedConstraints = [
      currentConstraints,
      `Creative direction: ${currentCreativeDirection}.`,
      `Story arc: ${currentStoryArc}.`,
      `Sensory level: ${currentSensoryLevel}.`,
      `Walking pace: ${currentWalkingPace}.`,
      `Output package: ${currentOutputPackage}.`,
      `Theme: ${currentSeasonalTheme}.`,
    ].join("\n");
    try {
      const response = await fetchParkPulseApi("/api/park/experience-studio/draft", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...overridePayload,
          templateId: currentTemplateId,
          audience: currentAudience,
          tone: currentTone,
          constraints: composedConstraints,
          creativeDirection: currentCreativeDirection,
          storyArc: currentStoryArc,
          sensoryLevel: currentSensoryLevel,
          walkingPace: currentWalkingPace,
          outputPackage: currentOutputPackage,
          seasonalTheme: currentSeasonalTheme,
          useLlm: useCreativeReasoning,
          useCreativeReasoning,
          useRealParkContext: false,
          useVenueExperienceData: true,
        }),
        timeoutMs: longRunningRequestTimeoutMs,
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
      setMessage(payload.draft?.sourceIntegrity?.readyForHandoff ? `Creative package generated at ${generatedAt} for demo handoff review` : `Draft generated at ${generatedAt} with blockers because verified venue data is incomplete`);
      void refreshStudioMemory();
      window.setTimeout(() => draftResultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
    } catch {
      setMessage("Draft generation failed");
    } finally {
      setIsDrafting(false);
    }
  };

  const studioTurnFromPlan = (plan: ConversationPlanPayload) => {
    const openQuestions = plan.clarifyingQuestions?.length ?? 0;
    const answered = plan.answeredQuestionIds?.length ?? 0;
    const recommendation = plan.recommendedPlan?.label ?? "recommended route";
    return `${recommendation}. ${answered} answer${answered === 1 ? "" : "s"} applied. ${openQuestions ? `${openQuestions} open question${openQuestions === 1 ? "" : "s"} remain.` : "Ready to generate."}`;
  };

  const runConversationPlanner = async (nextTurns: PlannerTurn[]) => {
    setIsPlanningConversation(true);
    setMessage(null);
    try {
      const response = await fetchParkPulseApi("/api/park/experience-studio/conversation-plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: conversationInput,
          templateId,
          audience,
          tone,
          constraints,
          history: nextTurns.map((turn) => ({ role: turn.role, content: turn.content })),
          useVenueExperienceData: true,
        }),
        timeoutMs: 8000,
      });
      const payload = await response.json() as ConversationPlanPayload;
      setConversationPlan(payload);
      setPlannerTurns([...nextTurns, { role: "studio", content: studioTurnFromPlan(payload), at: new Date().toISOString() }]);
      if (payload.venueExperienceData) setReadiness(payload.venueExperienceData);
      setMessage(payload.missingInputs?.length ? "Plan shaped with profile questions to resolve" : "Plan shaped and ready to generate");
      void refreshStudioMemory();
    } catch {
      setMessage("Conversation planning failed");
    } finally {
      setIsPlanningConversation(false);
    }
  };

  const shapeConversationPlan = async () => {
    const firstTurn: PlannerTurn = { role: "designer", content: conversationInput, at: new Date().toISOString() };
    await runConversationPlanner([firstTurn]);
  };

  const sendPlannerReply = async () => {
    const answer = plannerReply.trim();
    if (!answer) {
      setMessage("Add an answer before refining the plan");
      return;
    }
    const baseTurns = plannerTurns.length ? plannerTurns : [{ role: "designer" as const, content: conversationInput, at: new Date().toISOString() }];
    const nextTurns = [...baseTurns, { role: "designer" as const, content: answer, at: new Date().toISOString() }];
    setPlannerReply("");
    await runConversationPlanner(nextTurns);
  };

  const generateFromConversationPlan = async () => {
    const payload = conversationPlan?.recommendedPlan?.payload;
    if (!payload) {
      setMessage("Shape a conversational plan before generating from it");
      return;
    }
    setIsGeneratingFromPlan(true);
    applyRecommendedPlan(conversationPlan);
    try {
      await generateDraft(payload);
    } finally {
      setIsGeneratingFromPlan(false);
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
      void refreshStudioMemory();
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
      setMessage(payload.draftRecord.draft.sourceIntegrity?.readyForHandoff ? "Draft content updated for demo handoff review" : "Draft content updated; source-integrity gate still blocks demo handoff");
      void refreshStudioMemory();
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
      void refreshStudioMemory();
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
      void refreshStudioMemory();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Handoff failed");
    } finally {
      setIsSendingHandoff(false);
    }
  };

  const promoteLearningRule = async () => {
    if (!activeDraftId) {
      setMessage("Save and approve a draft before promoting a reusable rule");
      return;
    }
    if (!["approved", "ready_for_publish"].includes(workflowStatus)) {
      setMessage("Approve the draft before promoting a reusable Studio rule");
      return;
    }
    setIsPromotingRule(true);
    setMessage(null);
    try {
      const response = await fetchParkPulseApi(`/api/park/experience-studio/drafts/${encodeURIComponent(activeDraftId)}/promote-rule`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          candidateId: "complete_package_shape",
          actor: "experience_reviewer",
          note: reviewNote || "Promote approved package shape as bounded Studio context.",
        }),
        timeoutMs: 7000,
      });
      const payload = await response.json() as { status?: string; message?: string; rule?: { id?: string; label?: string; rule?: string } };
      if (payload.status !== "promoted") throw new Error(payload.message ?? "Rule promotion failed");
      setMessage("Approved package rule promoted for future Studio drafts");
      void refreshStudioMemory();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Rule promotion failed");
    } finally {
      setIsPromotingRule(false);
    }
  };

  const runSectionRevision = async () => {
    if (!draft) {
      setMessage("Generate or open a draft before revising a section");
      return;
    }
    const feedback = revisionFeedback.trim();
    if (!feedback) {
      setMessage("Add reviewer feedback before running the revision agent");
      return;
    }
    setIsRevisingSection(true);
    setMessage(null);
    try {
      const response = await fetchParkPulseApi("/api/park/experience-studio/section-revision", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          draft,
          sectionId: revisionSection,
          feedback,
          actor: "experience_reviewer",
        }),
        timeoutMs: 9000,
      });
      const payload = await response.json() as SectionRevisionPayload;
      if (payload.status !== "revised" || !payload.draft) throw new Error("Section revision failed");
      setDraftPayload((current) => ({ ...(current ?? { status: "ready", mode: "section_revision" }), status: "ready", mode: "section_revision", draft: payload.draft }));
      setLatestSectionRevision(payload);
      setMessage(`Review Agent revised ${formatStatus(payload.sectionId)}`);
      window.setTimeout(() => draftResultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Section revision failed");
    } finally {
      setIsRevisingSection(false);
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
  const creativePackage = draft?.creativePackage;
  const experienceReviewAgent = draft?.experienceReviewAgent ?? creativePackage?.reviewAgentReview ?? null;
  const hasAdvancedReview = Boolean(experienceReviewAgent || creativePackage?.creativePackageVariants?.length);
  const experienceReasoning = draft?.experienceReasoning ?? creativePackage?.designReasoning ?? null;
  const creativeSynthesis = draft?.creativeSynthesis ?? creativePackage?.creativeSynthesis ?? null;
  const profileIntelligence = draft?.profileIntelligence ?? readiness?.realInputs?.profileIntelligence ?? null;
  const coverageEntries = Object.entries(profileIntelligence?.coverage ?? {}).filter(([, value]) => typeof value === "number");
  const profileQualityGaps = profileIntelligence?.qualityGaps ?? draft?.sourceIntegrity?.profileIntelligenceQualityGaps ?? [];
  const studioPolicy = (profileIntelligence?.experienceStudioPolicy ?? profileIntelligence?.modulePolicy?.experience_studio ?? {}) as NonNullable<ProfileIntelligence["experienceStudioPolicy"]>;
  const brandTone = profileIntelligence?.brandBible?.tone ?? [];
  const bannedClaims = profileIntelligence?.brandBible?.bannedClaims ?? [];
  const studioReview = draft?.studioReview ?? [];
  const studioCore = draft?.studioCore ?? draftPayload?.studioCore ?? null;
  const studioMemoryCounts = studioMemory?.collectionCounts ?? {};
  const retentionEntries = Object.entries(studioMemory?.retentionPolicy ?? {});
  const latestStudioMemoryReceipts = useMemo(() => {
    const collectionReceipts = Object.entries(studioMemory?.collections ?? {}).flatMap(([collection, rows]) =>
      (rows ?? []).map((row) => ({ ...row, collection })),
    );
    const receipts = collectionReceipts.length
      ? collectionReceipts
      : (studioMemory?.latestReceipts ?? []);
    return receipts
      .filter((item) => Boolean(item?._id || item?.id || item?.eventType))
      .sort((a, b) => `${b.updatedAt ?? b.createdAt ?? ""}`.localeCompare(`${a.updatedAt ?? a.createdAt ?? ""}`))
      .slice(0, 6);
  }, [studioMemory]);
  const latestStudioMemoryReceipt = latestStudioMemoryReceipts[0];
  const recommendedPlanPayload = conversationPlan?.recommendedPlan?.payload;
  const recommendedPlanTemplate = recommendedPlanPayload ? valueFromPlan(recommendedPlanPayload, "templateId", templateId) : null;

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

          <div className="mt-5 rounded border border-cyan-300/25 bg-[#0d1115] p-3">
            <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-cyan-200">Conversational planner</div>
                <h3 className="mt-1 text-lg font-black text-white">Turn designer intent into a generator-ready plan</h3>
                <p className="mt-1 max-w-3xl text-xs leading-relaxed text-slate-500">
                  The planner reads the conversation, selects a Studio template, names missing venue facts, compares concepts, and produces the exact payload used by generation.
                </p>
              </div>
              <div className={`w-fit rounded border px-2 py-1 text-[10px] font-black uppercase tracking-widest ${conversationPlan?.status === "ready" ? "border-emerald-400/40 bg-emerald-950/25 text-emerald-100" : "border-slate-700 bg-[#151914] text-slate-400"}`}>
                {conversationPlan?.planningMode ? formatStatus(conversationPlan.planningMode) : "no plan yet"}
              </div>
            </div>
            <label className="mt-3 block">
              <span className="text-[10px] font-black uppercase tracking-widest text-slate-500">Designer request</span>
              <textarea
                value={conversationInput}
                onChange={(event) => setConversationInput(event.target.value)}
                className="mt-2 h-24 w-full resize-none rounded border border-slate-700 bg-[#151914] p-3 text-sm leading-relaxed text-slate-100 outline-none transition focus:border-cyan-300"
              />
            </label>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => void shapeConversationPlan()}
                disabled={isPlanningConversation}
                className="rounded border border-cyan-300 bg-cyan-300 px-4 py-2 text-sm font-black text-slate-950 transition hover:bg-cyan-200 disabled:opacity-50"
              >
                {isPlanningConversation ? "Shaping" : "Shape plan"}
              </button>
              <button
                type="button"
                onClick={() => applyRecommendedPlan()}
                disabled={!recommendedPlanPayload}
                className="rounded border border-lime-300 bg-lime-300 px-4 py-2 text-sm font-black text-slate-950 transition hover:bg-lime-200 disabled:cursor-not-allowed disabled:border-slate-700 disabled:bg-[#151914] disabled:text-slate-500"
              >
                Use plan
              </button>
              <button
                type="button"
                onClick={() => void generateFromConversationPlan()}
                disabled={isGeneratingFromPlan || !recommendedPlanPayload}
                className="rounded border border-emerald-300 bg-emerald-300 px-4 py-2 text-sm font-black text-slate-950 transition hover:bg-emerald-200 disabled:cursor-not-allowed disabled:border-slate-700 disabled:bg-[#151914] disabled:text-slate-500"
              >
                {isGeneratingFromPlan ? "Generating" : "Generate from plan"}
              </button>
              <div className="rounded border border-slate-800 bg-[#151914] px-3 py-2 text-xs font-bold text-slate-400">
                {recommendedPlanTemplate ? `Next input: ${formatStatus(recommendedPlanTemplate)}` : "Shape a plan to bind inputs"}
              </div>
            </div>
            <div className="mt-3 grid gap-3 xl:grid-cols-[minmax(0,1fr)_22rem]">
              <div className="rounded border border-slate-800 bg-[#151914] p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Planning thread</div>
                  <div className="rounded border border-slate-700 bg-[#0d1115] px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-400">{plannerTurns.length} turns</div>
                </div>
                <div className="mt-2 grid max-h-56 gap-2 overflow-auto pr-1">
                  {plannerTurns.length ? plannerTurns.map((turn, index) => (
                    <div key={`${turn.role}-${turn.at}-${index}`} className={`rounded border p-3 ${turn.role === "designer" ? "border-cyan-300/25 bg-cyan-950/10" : "border-lime-300/25 bg-lime-950/10"}`}>
                      <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{turn.role}</div>
                      <div className="mt-1 text-xs leading-relaxed text-slate-300">{turn.content}</div>
                    </div>
                  )) : (
                    <div className="rounded border border-slate-800 bg-[#0d1115] p-3 text-xs leading-relaxed text-slate-500">Shape a plan to start the thread.</div>
                  )}
                </div>
              </div>
              <div className="rounded border border-slate-800 bg-[#151914] p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-amber-200">Answer and refine</div>
                <textarea
                  value={plannerReply}
                  onChange={(event) => setPlannerReply(event.target.value)}
                  className="mt-2 h-28 w-full resize-none rounded border border-slate-700 bg-[#0d1115] p-3 text-xs leading-relaxed text-slate-100 outline-none transition focus:border-cyan-300"
                />
                <button
                  type="button"
                  onClick={() => void sendPlannerReply()}
                  disabled={isPlanningConversation || !conversationPlan}
                  className="mt-2 w-full rounded border border-amber-300 bg-amber-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-amber-200 disabled:cursor-not-allowed disabled:border-slate-700 disabled:bg-[#0d1115] disabled:text-slate-500"
                >
                  {isPlanningConversation ? "Refining" : "Send answer"}
                </button>
                <div className="mt-2 text-[11px] leading-relaxed text-slate-500">
                  Answered: {conversationPlan?.answeredQuestionIds?.length ? conversationPlan.answeredQuestionIds.map(formatStatus).join(", ") : "none yet"}
                </div>
              </div>
            </div>
            {conversationPlan ? (
              <div className="mt-4 grid gap-3 xl:grid-cols-[minmax(0,1fr)_22rem]">
                <div className="grid gap-3">
                  <div className="rounded border border-slate-800 bg-[#151914] p-3">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <div className="text-[10px] font-black uppercase tracking-widest text-cyan-200">Parsed brief</div>
                        <div className="mt-1 text-sm font-black text-white">{conversationPlan.parsedBrief?.templateLabel ?? "Experience package"}</div>
                      </div>
                      <div className="rounded border border-slate-700 bg-[#0d1115] px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-400">{conversationPlan.parsedBrief?.templateId ?? "template"}</div>
                    </div>
                    <div className="mt-3 grid gap-2 md:grid-cols-2">
                      {[
                        ["Goal", conversationPlan.parsedBrief?.goal],
                        ["Audience", conversationPlan.parsedBrief?.audience],
                        ["Tone", conversationPlan.parsedBrief?.tone],
                        ["Success", conversationPlan.parsedBrief?.successMetric],
                        ["Commitment", conversationPlan.parsedBrief?.guestCommitment],
                        ["Segment", conversationPlan.parsedBrief?.targetSegment],
                        ["Channels", compactList(conversationPlan.parsedBrief?.channelTargets ?? [], 4)],
                        ["Source", conversationPlan.parsedBrief?.source],
                      ].map(([label, value]) => (
                        <div key={label} className="rounded border border-slate-800 bg-[#0d1115] p-3">
                          <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                          <div className="mt-1 text-xs leading-relaxed text-slate-300">{value ?? "not set"}</div>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="grid gap-3 lg:grid-cols-3">
                    {(conversationPlan.conceptOptions ?? []).map((option) => (
                      <div key={option.id ?? option.label} className={`rounded border p-3 ${option.id === conversationPlan.recommendedOptionId ? "border-lime-300/50 bg-lime-950/20" : "border-slate-800 bg-[#151914]"}`}>
                        <div className="flex items-start justify-between gap-2">
                          <div className="text-sm font-black text-white">{option.label}</div>
                          {option.id === conversationPlan.recommendedOptionId ? <div className="rounded border border-lime-300/40 bg-lime-300 px-2 py-1 text-[9px] font-black uppercase tracking-widest text-slate-950">Pick</div> : null}
                        </div>
                        <div className="mt-2 text-xs leading-relaxed text-slate-400">{option.rationale}</div>
                        <div className="mt-2 text-[11px] leading-relaxed text-slate-500">Risk: {option.risk}</div>
                        {option.profileFit ? (
                          <div className="mt-3 rounded border border-slate-800 bg-[#0d1115] p-2 text-[11px] leading-relaxed text-slate-400">
                            <div className="font-black uppercase tracking-widest text-slate-500">Profile fit</div>
                            <div className="mt-1">Pattern: {formatStatus(option.profileFit.routePatternId ?? "none")}</div>
                            {option.profileFit.segmentNeeds?.length ? <div className="mt-1">Needs: {compactList(option.profileFit.segmentNeeds, 3)}</div> : null}
                            {option.profileFit.channelTargets?.length ? <div className="mt-1">Channels: {compactList(option.profileFit.channelTargets, 4)}</div> : null}
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                </div>

                <aside className="grid gap-3">
                  <div className="rounded border border-slate-800 bg-[#151914] p-3">
                    <div className="text-[10px] font-black uppercase tracking-widest text-lime-200">Recommended plan</div>
                    <div className="mt-1 text-sm font-black text-white">{conversationPlan.recommendedPlan?.label ?? "not selected"}</div>
                    <div className="mt-2 text-xs leading-relaxed text-slate-400">{conversationPlan.recommendedPlan?.why}</div>
                    <div className="mt-2 rounded border border-slate-800 bg-[#0d1115] p-2 text-[11px] leading-relaxed text-slate-500">
                      Payload: {recommendedPlanPayload ? [
                        valueFromPlan(recommendedPlanPayload, "templateId", "template"),
                        valueFromPlan(recommendedPlanPayload, "creativeDirection", "direction"),
                        valueFromPlan(recommendedPlanPayload, "outputPackage", "package"),
                      ].join(" / ") : "not ready"}
                    </div>
                  </div>

                  {conversationPlan.plannerIntelligence ? (
                    <div className="rounded border border-slate-800 bg-[#151914] p-3">
                      <div className="text-[10px] font-black uppercase tracking-widest text-violet-200">Planner intelligence</div>
                      <div className="mt-2 grid gap-2 text-[11px] leading-relaxed text-slate-400">
                        <div className="rounded border border-slate-800 bg-[#0d1115] p-2">
                          <span className="font-black uppercase tracking-widest text-slate-500">Segment</span>
                          <div className="mt-1 text-slate-300">{conversationPlan.plannerIntelligence.targetSegment?.label ?? "not inferred"}</div>
                        </div>
                        <div className="rounded border border-slate-800 bg-[#0d1115] p-2">
                          <span className="font-black uppercase tracking-widest text-slate-500">Route pattern</span>
                          <div className="mt-1 text-slate-300">{formatStatus(conversationPlan.plannerIntelligence.routePattern?.id ?? "none")}</div>
                          <div className="mt-1 text-slate-500">{compactList(conversationPlan.plannerIntelligence.routePattern?.recommendedArc ?? [], 5)}</div>
                        </div>
                        <div className="rounded border border-slate-800 bg-[#0d1115] p-2">
                          <span className="font-black uppercase tracking-widest text-slate-500">Profile evidence</span>
                          <div className="mt-1">Rules: {conversationPlan.plannerIntelligence.profileEvidence?.experienceRuleKeys?.length ?? 0}</div>
                          <div className="mt-1">Signature anchors: {conversationPlan.plannerIntelligence.profileEvidence?.signatureStoryAnchorCount ?? 0}</div>
                        </div>
                      </div>
                    </div>
                  ) : null}

                  <div className="rounded border border-slate-800 bg-[#151914] p-3">
                    <div className="text-[10px] font-black uppercase tracking-widest text-amber-200">Clarifying questions</div>
                    <div className="mt-2 grid gap-2">
                      {(conversationPlan.clarifyingQuestions ?? []).map((item, index) => (
                        <div key={item.id ?? index} className="rounded border border-slate-800 bg-[#0d1115] p-2">
                          <div className="text-xs font-bold leading-relaxed text-slate-200">{item.question}</div>
                          <div className="mt-1 text-[11px] leading-relaxed text-slate-500">{item.whyItMatters}</div>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="rounded border border-slate-800 bg-[#151914] p-3">
                    <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Quality rubric</div>
                    <div className="mt-2 grid gap-2">
                      {(conversationPlan.qualityRubric ?? []).map((item) => (
                        <div key={item.id ?? item.label} className="grid grid-cols-[5rem_1fr] gap-2 rounded border border-slate-800 bg-[#0d1115] p-2 text-[11px] leading-relaxed">
                          <span className={`font-black uppercase tracking-widest ${item.status === "pass" ? "text-emerald-200" : "text-amber-200"}`}>{formatStatus(item.status)}</span>
                          <span className="text-slate-400"><b className="text-slate-200">{item.label}:</b> {item.check}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </aside>
              </div>
            ) : null}
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
              <label className="mt-3 flex items-start gap-3 rounded border border-slate-800 bg-[#151914] p-3">
                <input
                  type="checkbox"
                  checked={useCreativeReasoning}
                  onChange={(event) => setUseCreativeReasoning(event.target.checked)}
                  className="mt-1 h-4 w-4 accent-cyan-300"
                />
                <span>
                  <span className="block text-[10px] font-black uppercase tracking-widest text-cyan-200">LLM creative reasoning pass</span>
                  <span className="mt-1 block text-xs leading-relaxed text-slate-500">
                    Runs after verified route selection. The backend can polish copy and rationale, but it cannot change verified stops, source receipts, accessibility notes, or reviewer gates.
                  </span>
                </span>
              </label>
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
              {draft ? (
                <div className="mt-3 rounded border border-lime-300/25 bg-[#151914] p-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="text-[10px] font-black uppercase tracking-widest text-lime-200">Review Agent revision</div>
                      <div className="mt-1 text-xs leading-relaxed text-slate-500">Revise one section, keep route/profile locks, then show QA delta.</div>
                    </div>
                    {latestSectionRevision?.qaDelta ? (
                      <div className="rounded border border-lime-300/30 bg-lime-950/20 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-lime-100">
                        QA {latestSectionRevision.qaDelta.before ?? "n/a"} to {latestSectionRevision.qaDelta.after ?? "n/a"} ({latestSectionRevision.qaDelta.delta ?? 0})
                      </div>
                    ) : null}
                  </div>
                  <div className="mt-3 grid gap-2 lg:grid-cols-[12rem_minmax(0,1fr)_12rem]">
                    <select
                      value={revisionSection}
                      onChange={(event) => setRevisionSection(event.target.value)}
                      className="rounded border border-slate-700 bg-[#0d1115] px-3 py-2 text-xs font-bold text-slate-100 outline-none transition focus:border-lime-300"
                    >
                      <option value="staff_script">staff script</option>
                      <option value="signage">signage</option>
                      <option value="email">pre-arrival email</option>
                      <option value="route">route storyboard</option>
                      <option value="section_details">section details</option>
                    </select>
                    <input
                      value={revisionFeedback}
                      onChange={(event) => setRevisionFeedback(event.target.value)}
                      className="rounded border border-slate-700 bg-[#0d1115] px-3 py-2 text-xs text-slate-100 outline-none transition focus:border-lime-300"
                    />
                    <button
                      type="button"
                      onClick={() => void runSectionRevision()}
                      disabled={isRevisingSection}
                      className="rounded border border-lime-300 bg-lime-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-lime-200 disabled:cursor-not-allowed disabled:border-slate-700 disabled:bg-[#0d1115] disabled:text-slate-500"
                    >
                      {isRevisingSection ? "Revising" : "Run revision"}
                    </button>
                  </div>
                </div>
              ) : null}
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
                  <div className="text-[10px] font-black uppercase tracking-widest text-lime-200">LLM core</div>
                  <div className="mt-2 text-xs leading-relaxed text-slate-300">{studioCore?.mission ?? "Preset core values attach when a package is generated."}</div>
                  <div className="mt-1 text-[11px] leading-relaxed text-slate-500">{studioCore?.coreValues?.length ? compactList(studioCore.coreValues, 3) : profileQualityGaps.length ? `${profileQualityGaps.length} profile gap(s) need review.` : "No generated package loaded yet."}</div>
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
                        {draft.sourceIntegrity?.readyForHandoff ? "demo handoff ready" : "demo handoff blocked"}
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
                    {creativePackage ? (
                      <div className="mt-4 rounded border border-cyan-300/25 bg-[#0d1115] p-3">
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <div>
                            <div className="text-[10px] font-black uppercase tracking-widest text-cyan-200">Final package</div>
                            <div className="mt-1 text-lg font-black text-white">{creativePackage.executiveConcept?.name ?? draft.title}</div>
                            <p className="mt-2 max-w-4xl text-xs leading-relaxed text-slate-400">{creativePackage.executiveConcept?.oneLine}</p>
                          </div>
                          <div className="rounded border border-slate-700 bg-[#151914] px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-400">{creativePackage.version ?? "package"}</div>
                        </div>
                        <div className="mt-3 grid gap-3 lg:grid-cols-2">
                          <div className="rounded border border-slate-800 bg-[#151914] p-3">
                            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Guest promise</div>
                            <div className="mt-2 text-xs leading-relaxed text-slate-300">{creativePackage.executiveConcept?.guestPromise ?? "not set"}</div>
                            <div className="mt-2 text-[11px] leading-relaxed text-slate-500">{creativePackage.executiveConcept?.whyNow}</div>
                          </div>
                          {creativePackage.studioQualityEval ? (
                            <div className="rounded border border-cyan-300/20 bg-cyan-950/10 p-3">
                              <div className="flex flex-wrap items-start justify-between gap-2">
                                <div>
                                  <div className="text-[10px] font-black uppercase tracking-widest text-cyan-100">Studio QA eval</div>
                                  <div className="mt-1 text-xs leading-relaxed text-slate-300">{formatStatus(creativePackage.studioQualityEval.status)}</div>
                                </div>
                                <div className="rounded border border-cyan-300/30 bg-cyan-950/20 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-cyan-100">
                                  {creativePackage.studioQualityEval.demoScore ?? creativePackage.studioQualityEval.score ?? "n/a"}
                                </div>
                              </div>
                              <div className="mt-2 grid gap-2 text-[11px] leading-relaxed text-slate-300 sm:grid-cols-2">
                                <div className="rounded border border-cyan-300/15 bg-[#0d1115] p-2">Production score: {creativePackage.studioQualityEval.productionScore ?? "n/a"}</div>
                                <div className="rounded border border-cyan-300/15 bg-[#0d1115] p-2">
                                  Gates: {creativePackage.studioQualityEval.gateSummary?.passed ?? 0} pass / {creativePackage.studioQualityEval.gateSummary?.review ?? 0} review / {creativePackage.studioQualityEval.gateSummary?.blocked ?? 0} blocked
                                </div>
                              </div>
                              <div className="mt-2 grid gap-1 text-[11px] leading-relaxed text-slate-300">
                                {Object.entries(creativePackage.studioQualityEval.scores ?? {}).slice(0, 4).map(([label, value]) => (
                                  <div key={label}>{formatStatus(label)}: {value}</div>
                                ))}
                              </div>
                              {creativePackage.studioQualityEval.reviewerPanel ? (
                                <div className="mt-2 rounded border border-cyan-300/15 bg-[#0d1115] p-2 text-[11px] leading-relaxed text-slate-300">
                                  <div className="text-[10px] font-black uppercase tracking-widest text-cyan-100">Reviewer loop</div>
                                  <div className="mt-1">{formatStatus(creativePackage.studioQualityEval.reviewerPanel.status)} / consensus {creativePackage.studioQualityEval.reviewerPanel.consensusScore ?? "n/a"}</div>
                                  <div className="mt-1 text-slate-400">{compactList((creativePackage.studioQualityEval.reviewerPanel.reviewers ?? []).map((reviewer) => `${reviewer.role}: ${formatStatus(reviewer.gateStatus)} ${reviewer.finding ?? ""}`), 2)}</div>
                                </div>
                              ) : null}
                              {creativePackage.studioQualityEval.venueReflection ? (
                                <div className="mt-2 rounded border border-emerald-300/15 bg-[#0d1115] p-2 text-[11px] leading-relaxed text-slate-300">
                                  <div className="text-[10px] font-black uppercase tracking-widest text-emerald-100">Venue reflection</div>
                                  <div className="mt-1">{formatStatus(creativePackage.studioQualityEval.venueReflection.status)} / score {creativePackage.studioQualityEval.venueReflection.score ?? "n/a"}</div>
                                  <div className="mt-1 text-slate-400">{compactList((creativePackage.studioQualityEval.venueReflection.dimensions ?? []).map((dimension) => `${dimension.label}: ${dimension.score} - ${dimension.evidence ?? ""}`), 3)}</div>
                                </div>
                              ) : null}
                              {creativePackage.studioQualityEval.gateResults?.length ? (
                                <div className="mt-2 text-[11px] leading-relaxed text-slate-300">
                                  {compactList(creativePackage.studioQualityEval.gateResults.map((gate) => `${formatStatus(gate.status)} / ${formatStatus(gate.id)}: ${gate.evidence ?? ""}`), 3)}
                                </div>
                              ) : null}
                              <div className="mt-2 text-[11px] leading-relaxed text-amber-100">{compactList(creativePackage.studioQualityEval.findings ?? [], 2)}</div>
                            </div>
                          ) : (
                          <div className="rounded border border-slate-800 bg-[#151914] p-3">
                            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Staff script</div>
                            <div className="mt-2 grid gap-2">
                              {Object.entries(creativePackage.staffScript ?? {}).slice(0, 4).map(([label, value]) => (
                                <div key={label} className="rounded border border-slate-800 bg-[#0d1115] p-2">
                                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{formatStatus(label)}</div>
                                  <div className="mt-1 text-[11px] leading-relaxed text-slate-300">{value}</div>
                                </div>
                              ))}
                            </div>
                          </div>
                          )}
                        </div>
                        {creativePackage.studioQualityEval ? (
                          <div className="mt-3 rounded border border-slate-800 bg-[#151914] p-3">
                            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Staff script</div>
                            <div className="mt-2 grid gap-2 md:grid-cols-2">
                              {Object.entries(creativePackage.staffScript ?? {}).slice(0, 4).map(([label, value]) => (
                                <div key={label} className="rounded border border-slate-800 bg-[#0d1115] p-2">
                                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{formatStatus(label)}</div>
                                  <div className="mt-1 text-[11px] leading-relaxed text-slate-300">{value}</div>
                                </div>
                              ))}
                            </div>
                          </div>
                        ) : null}
                        {creativePackage.craftArtifacts?.samples?.length ? (
                          <div className="mt-3 rounded border border-fuchsia-300/25 bg-[#151914] p-3">
                            <div className="flex flex-wrap items-start justify-between gap-2">
                              <div>
                                <div className="text-[10px] font-black uppercase tracking-widest text-fuchsia-100">Creative lead samples</div>
                                <div className="mt-1 text-xs leading-relaxed text-slate-400">{creativePackage.craftArtifacts.purpose}</div>
                              </div>
                              <div className="rounded border border-fuchsia-300/30 bg-fuchsia-950/20 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-fuchsia-100">
                                {formatStatus(creativePackage.craftArtifacts.status)}
                              </div>
                            </div>
                            <div className="mt-3 grid gap-2 lg:grid-cols-3">
                              {creativePackage.craftArtifacts.samples.slice(0, 3).map((sample) => (
                                <div key={sample.id ?? sample.label} className="rounded border border-slate-800 bg-[#0d1115] p-2">
                                  <div className="text-xs font-black text-slate-100">{sample.label}</div>
                                  <div className="mt-1 text-[10px] font-black uppercase tracking-widest text-slate-500">{formatStatus(sample.channel)}</div>
                                  <div className="mt-2 text-[11px] leading-relaxed text-slate-300">{sample.copy}</div>
                                  <div className="mt-2 text-[11px] leading-relaxed text-slate-500">{sample.whyItHelps}</div>
                                  <div className="mt-1 text-[11px] leading-relaxed text-amber-100">Review: {sample.reviewGate}</div>
                                </div>
                              ))}
                            </div>
                            {creativePackage.craftArtifacts.craftNotes?.length ? (
                              <div className="mt-2 text-[11px] leading-relaxed text-slate-500">Notes: {compactList(creativePackage.craftArtifacts.craftNotes, 3)}</div>
                            ) : null}
                          </div>
                        ) : null}
                        {creativePackage.vertexModelOrchestration ? (
                          <div className="mt-3 rounded border border-sky-300/25 bg-sky-950/10 p-3">
                            <div className="flex flex-wrap items-start justify-between gap-2">
                              <div>
                                <div className="text-[10px] font-black uppercase tracking-widest text-sky-100">Vertex AI enrichment</div>
                                <div className="mt-1 text-xs leading-relaxed text-slate-300">{creativePackage.vertexModelOrchestration.boundary}</div>
                              </div>
                              <div className="rounded border border-sky-300/30 bg-sky-950/20 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-sky-100">
                                {creativePackage.vertexModelOrchestration.readyOrPlannedSlotCount ?? 0} / {creativePackage.vertexModelOrchestration.slotCount ?? 0} slots
                              </div>
                            </div>
                            <div className="mt-2 grid gap-2 text-[11px] leading-relaxed text-slate-300 md:grid-cols-3">
                              <div className="rounded border border-sky-300/15 bg-[#0d1115] p-2">
                                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Provider</div>
                                <div className="mt-1">{creativePackage.vertexModelOrchestration.providerReadiness?.provider ?? "Vertex AI"}</div>
                                <div className="mt-1 text-slate-500">{formatStatus(creativePackage.vertexModelOrchestration.providerReadiness?.platform)} / {creativePackage.vertexModelOrchestration.providerReadiness?.ready ? "ready" : "not configured"}</div>
                              </div>
                              <div className="rounded border border-sky-300/15 bg-[#0d1115] p-2 md:col-span-2">
                                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Activation</div>
                                <div className="mt-1 text-slate-400">{compactList(creativePackage.vertexModelOrchestration.activation?.vertexEnv ?? [], 3)}</div>
                                <div className="mt-1 text-amber-100">{compactList(creativePackage.vertexModelOrchestration.providerReadiness?.readinessIssues ?? [], 2)}</div>
                              </div>
                            </div>
                            <div className="mt-2 grid gap-2 lg:grid-cols-3">
                              {(creativePackage.vertexModelOrchestration.slots ?? []).map((slot) => (
                                <div key={slot.id ?? slot.label} className="rounded border border-slate-800 bg-[#0d1115] p-2">
                                  <div className="flex items-start justify-between gap-2">
                                    <div className="text-xs font-black text-slate-100">{slot.label ?? formatStatus(slot.id)}</div>
                                    <div className="rounded border border-slate-700 px-2 py-1 text-[9px] font-black uppercase tracking-widest text-slate-400">{formatStatus(slot.status)}</div>
                                  </div>
                                  <div className="mt-1 text-[10px] font-black uppercase tracking-widest text-sky-100">{slot.model}</div>
                                  <div className="mt-2 text-[11px] leading-relaxed text-slate-400">{slot.purpose}</div>
                                  <div className="mt-2 text-[11px] leading-relaxed text-slate-500">Outputs: {compactList(slot.expectedOutputs ?? [], 3)}</div>
                                </div>
                              ))}
                            </div>
                          </div>
                        ) : null}
                        {hasAdvancedReview ? (
                          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded border border-lime-300/20 bg-[#151914] p-3">
                            <div>
                              <div className="text-[10px] font-black uppercase tracking-widest text-lime-100">Advanced review package</div>
                              <div className="mt-1 text-[11px] font-bold text-slate-500">Review-agent findings and creative alternatives render on demand.</div>
                            </div>
                            <button
                              type="button"
                              onClick={() => setShowAdvancedReview((value) => !value)}
                              className="rounded border border-lime-300/40 bg-slate-950 px-3 py-2 text-[10px] font-black uppercase tracking-widest text-lime-100 transition hover:border-lime-200"
                            >
                              {showAdvancedReview ? "Hide review" : "Show review"}
                            </button>
                          </div>
                        ) : null}
                        {showAdvancedReview && experienceReviewAgent ? (
                          <div className="mt-3 rounded border border-lime-300/25 bg-lime-950/10 p-3">
                            <div className="flex flex-wrap items-start justify-between gap-2">
                              <div>
                                <div className="text-[10px] font-black uppercase tracking-widest text-lime-100">Experience Review Agent</div>
                                <div className="mt-1 text-xs font-black text-slate-100">{experienceReviewAgent.agentName ?? "Experience Studio Review Agent"}</div>
                                <div className="mt-1 text-xs leading-relaxed text-slate-400">{formatStatus(experienceReviewAgent.approvalRecommendation)}</div>
                              </div>
                              <div className="rounded border border-lime-300/30 bg-lime-950/20 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-lime-100">
                                {formatStatus(experienceReviewAgent.status)} / {experienceReviewAgent.score ?? "n/a"}
                              </div>
                            </div>
                            <div className="mt-2 grid gap-2 lg:grid-cols-2">
                              <div className="rounded border border-slate-800 bg-[#0d1115] p-2">
                                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Findings</div>
                                <div className="mt-1 text-[11px] leading-relaxed text-slate-300">{compactList(experienceReviewAgent.findings ?? [], 4)}</div>
                              </div>
                              <div className="rounded border border-slate-800 bg-[#0d1115] p-2">
                                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Revision targets</div>
                                <div className="mt-1 text-[11px] leading-relaxed text-amber-100">
                                  {compactList((experienceReviewAgent.sectionTargets ?? []).map((item) => `${item.section}: ${item.reason}`), 4)}
                                </div>
                              </div>
                            </div>
                          </div>
                        ) : null}
                        {showAdvancedReview && creativePackage.creativePackageVariants?.length ? (
                          <div className="mt-3 rounded border border-slate-800 bg-[#151914] p-3">
                            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Creative alternatives</div>
                            <div className="mt-2 grid gap-2 lg:grid-cols-3">
                              {creativePackage.creativePackageVariants.slice(0, 3).map((variant) => (
                                <div key={variant.id ?? variant.name} className={`rounded border p-2 ${variant.status === "selected" ? "border-cyan-300/40 bg-cyan-950/10" : "border-slate-800 bg-[#0d1115]"}`}>
                                  <div className="flex items-start justify-between gap-2">
                                    <div className="text-xs font-black text-slate-100">{variant.name}</div>
                                    <div className="rounded border border-slate-700 px-2 py-1 text-[9px] font-black uppercase tracking-widest text-slate-400">{variant.status}</div>
                                  </div>
                                  <div className="mt-1 text-[11px] leading-relaxed text-slate-400">{variant.positioning}</div>
                                  <div className="mt-2 text-[11px] leading-relaxed text-slate-300">Use: {variant.whenToUse}</div>
                                  <div className="mt-1 text-[11px] leading-relaxed text-amber-100">Risk: {compactList(variant.reviewRisks ?? [], 2)}</div>
                                </div>
                              ))}
                            </div>
                          </div>
                        ) : null}
                        <div className="mt-3 grid gap-3 xl:grid-cols-3">
                          <div className="rounded border border-slate-800 bg-[#151914] p-3">
                            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Experience beats</div>
                            <div className="mt-2 grid gap-2">
                              {(creativePackage.experienceBeats ?? []).map((item) => (
                                <div key={item.beat} className="rounded border border-slate-800 bg-[#0d1115] p-2">
                                  <div className="text-xs font-black text-slate-100">{item.beat}</div>
                                  <div className="mt-1 text-[11px] leading-relaxed text-slate-500">{item.detail}</div>
                                </div>
                              ))}
                            </div>
                          </div>
                          <div className="rounded border border-slate-800 bg-[#151914] p-3">
                            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Signage set</div>
                            <div className="mt-2 grid gap-2">
                              {(creativePackage.signageSet ?? []).map((item) => (
                                <div key={`${item.placement}-${item.headline}`} className="rounded border border-slate-800 bg-[#0d1115] p-2">
                                  <div className="text-xs font-black text-slate-100">{item.headline}</div>
                                  <div className="mt-1 text-[11px] font-bold uppercase tracking-widest text-slate-500">{item.placement}</div>
                                  <div className="mt-1 text-[11px] leading-relaxed text-slate-400">{item.body}</div>
                                </div>
                              ))}
                            </div>
                          </div>
                          <div className="rounded border border-slate-800 bg-[#151914] p-3">
                            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Owner questions</div>
                            <div className="mt-2 grid gap-2">
                              {(creativePackage.ownerQuestions ?? []).slice(0, 5).map((item) => (
                                <div key={`${item.owner}-${item.question}`} className="rounded border border-slate-800 bg-[#0d1115] p-2">
                                  <div className="text-xs font-black text-slate-100">{item.owner}</div>
                                  <div className="mt-1 text-[11px] leading-relaxed text-slate-500">{item.question}</div>
                                </div>
                              ))}
                            </div>
                          </div>
                        </div>
                        {creativePackage.sectionDossiers?.length ? (
                          <div className="mt-3 rounded border border-slate-800 bg-[#151914] p-3">
                            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Section dossiers</div>
                            <div className="mt-2 grid gap-2 lg:grid-cols-2">
                              {creativePackage.sectionDossiers.map((section) => (
                                <div key={section.section} className="rounded border border-slate-800 bg-[#0d1115] p-2">
                                  <div className="text-xs font-black text-slate-100">{formatStatus(section.section)}</div>
                                  <div className="mt-1 text-[11px] leading-relaxed text-slate-400">{section.purpose}</div>
                                  <div className="mt-2 text-[11px] leading-relaxed text-slate-300">{compactList(section.details ?? [], 4)}</div>
                                  <div className="mt-2 text-[11px] leading-relaxed text-amber-100">Review: {section.reviewGate}</div>
                                </div>
                              ))}
                            </div>
                          </div>
                        ) : null}
                        {creativePackage.sectionCreativeDetails ? (
                          <div className="mt-3 rounded border border-slate-800 bg-[#151914] p-3">
                            <div className="flex flex-wrap items-start justify-between gap-2">
                              <div>
                                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Section-level authoring</div>
                                <div className="mt-1 text-xs leading-relaxed text-slate-300">
                                  {String(creativePackage.sectionCreativeDetails.conceptBoard?.workingTitle ?? creativePackage.executiveConcept?.name ?? "Concept board")}
                                </div>
                              </div>
                              <div className="rounded border border-slate-700 bg-[#0d1115] px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-400">
                                {(creativePackage.sectionCreativeDetails.routeStoryCards ?? []).length} cards
                              </div>
                            </div>
                            <div className="mt-3 grid gap-2 lg:grid-cols-2">
                              {(creativePackage.sectionCreativeDetails.routeStoryCards ?? []).slice(0, 4).map((card) => (
                                <div key={`${card.order}-${card.stop}`} className="rounded border border-slate-800 bg-[#0d1115] p-2">
                                  <div className="text-xs font-black text-slate-100">{card.order}. {card.stop}</div>
                                  <div className="mt-1 text-[10px] font-black uppercase tracking-widest text-slate-500">{card.beat}</div>
                                  <div className="mt-2 text-[11px] leading-relaxed text-slate-300">{card.guestFacingMoment}</div>
                                  <div className="mt-1 text-[11px] leading-relaxed text-slate-500">Choice: {card.choiceArchitecture}</div>
                                </div>
                              ))}
                            </div>
                            <div className="mt-2 text-[11px] leading-relaxed text-slate-300">Staff rehearsal: {compactList(creativePackage.sectionCreativeDetails.staffRehearsalNotes ?? [], 3)}</div>
                          </div>
                        ) : null}
                        {creativePackage.routeBlueprint?.length ? (
                          <div className="mt-3 rounded border border-slate-800 bg-[#151914] p-3">
                            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Route blueprint</div>
                            <div className="mt-2 grid gap-2">
                              {creativePackage.routeBlueprint.map((item) => (
                                <div key={`${item.order}-${item.stop}`} className="rounded border border-slate-800 bg-[#0d1115] p-2">
                                  <div className="flex flex-wrap items-center justify-between gap-2">
                                    <div className="text-xs font-black text-slate-100">{item.order}. {item.stop}</div>
                                    <div className="rounded border border-slate-700 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-400">{item.storyBeat}</div>
                                  </div>
                                  <div className="mt-2 grid gap-2 md:grid-cols-2">
                                    <div className="text-[11px] leading-relaxed text-slate-300">Guest: {item.guestAction}</div>
                                    <div className="text-[11px] leading-relaxed text-slate-300">Host: {item.hostAction}</div>
                                    <div className="text-[11px] leading-relaxed text-slate-500">Content job: {item.contentJob}</div>
                                    <div className="text-[11px] leading-relaxed text-amber-100">Proof: {compactList(item.proofNeeded ?? [], 3)}</div>
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        ) : null}
                        {creativePackage.channelMatrix?.length ? (
                          <div className="mt-3 rounded border border-slate-800 bg-[#151914] p-3">
                            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Channel matrix</div>
                            <div className="mt-2 grid gap-2 lg:grid-cols-2">
                              {creativePackage.channelMatrix.map((item) => (
                                <div key={item.channel} className="rounded border border-slate-800 bg-[#0d1115] p-2">
                                  <div className="flex flex-wrap items-center justify-between gap-2">
                                    <div className="text-xs font-black text-slate-100">{formatStatus(item.channel)}</div>
                                    <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{item.owner}</div>
                                  </div>
                                  <div className="mt-1 text-[11px] leading-relaxed text-slate-400">{item.objective}</div>
                                  {item.headline ? <div className="mt-2 text-[11px] font-black text-slate-200">{item.headline}</div> : null}
                                  <div className="mt-1 text-[11px] leading-relaxed text-slate-300">{typeof item.primaryCopy === "string" ? item.primaryCopy : JSON.stringify(item.primaryCopy ?? "")}</div>
                                  <div className="mt-2 text-[11px] leading-relaxed text-slate-500">Rules: {compactList(item.rules ?? [], 3)}</div>
                                  <div className="mt-1 text-[11px] leading-relaxed text-amber-100">Review: {item.reviewQuestion}</div>
                                </div>
                              ))}
                            </div>
                          </div>
                        ) : null}
	                        <div className="mt-3 grid gap-3 lg:grid-cols-2">
	                          <div className="rounded border border-slate-800 bg-[#151914] p-3">
	                            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Pre-arrival email</div>
	                            <div className="mt-2 text-xs font-black text-slate-100">{creativePackage.preArrivalEmail?.subject ?? "not set"}</div>
	                            <div className="mt-1 text-[11px] leading-relaxed text-slate-500">{creativePackage.preArrivalEmail?.previewText}</div>
                            <div className="mt-2 text-xs leading-relaxed text-slate-300">{creativePackage.preArrivalEmail?.body}</div>
                          </div>
                          <div className="rounded border border-slate-800 bg-[#151914] p-3">
                            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Accessibility review packet</div>
                            <div className="mt-2 grid gap-1 text-[11px] leading-relaxed text-slate-300">
                              {(creativePackage.accessibilityReviewPacket?.mustVerify ?? []).map((item) => <div key={item}>Verify: {item}</div>)}
                            </div>
                            {creativePackage.accessibilityReviewPacket?.profileQualityGaps?.length ? (
                              <div className="mt-2 text-[11px] leading-relaxed text-amber-100">
                                Gaps: {compactList(creativePackage.accessibilityReviewPacket.profileQualityGaps, 3)}
	                              </div>
	                            ) : null}
	                          </div>
	                        </div>
                        <div className="mt-3 grid gap-3 lg:grid-cols-2">
                          {creativePackage.staffRunOfShow?.length ? (
                            <div className="rounded border border-slate-800 bg-[#151914] p-3">
                              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Staff run-of-show</div>
                              <div className="mt-2 grid gap-2">
                                {creativePackage.staffRunOfShow.map((item) => (
                                  <div key={item.phase} className="rounded border border-slate-800 bg-[#0d1115] p-2">
                                    <div className="text-xs font-black text-slate-100">{formatStatus(item.phase)}</div>
                                    <div className="mt-1 text-[11px] font-bold uppercase tracking-widest text-slate-500">{item.who}</div>
                                    <div className="mt-1 text-[11px] leading-relaxed text-slate-300">{item.detail}</div>
                                    <div className="mt-1 text-[11px] leading-relaxed text-amber-100">{item.reviewGate}</div>
                                  </div>
                                ))}
                              </div>
                            </div>
                          ) : null}
                          {creativePackage.productionDetail ? (
                            <div className="rounded border border-slate-800 bg-[#151914] p-3">
                              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Production detail</div>
                              <div className="mt-2 text-[11px] leading-relaxed text-slate-300">Choices: {compactList(creativePackage.productionDetail.guestChoiceModel ?? [], 3)}</div>
                              <div className="mt-2 text-[11px] leading-relaxed text-slate-500">Checklist: {compactList(creativePackage.productionDetail.contentCompletenessChecklist ?? [], 6)}</div>
                              <div className="mt-2 grid gap-1">
                                {(creativePackage.productionDetail.measurementPlan ?? []).map((item) => (
                                  <div key={item.metric} className="text-[11px] leading-relaxed text-slate-400">
                                    <span className="font-black text-slate-200">{item.metric}:</span> {item.signal} / {item.learningUse}
                                  </div>
                                ))}
                              </div>
                            </div>
                          ) : null}
                        </div>
	                        {creativePackage.venuePattern ? (
	                          <div className="mt-3 rounded border border-slate-800 bg-[#151914] p-3">
	                            <div className="flex flex-wrap items-start justify-between gap-2">
	                              <div>
	                                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Venue pattern</div>
	                                <div className="mt-1 text-xs font-black text-slate-100">{formatStatus(creativePackage.venuePattern.id ?? "profile pattern")}</div>
	                              </div>
	                              <div className="rounded border border-slate-700 bg-[#0d1115] px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-400">
	                                Profile-backed
	                              </div>
	                            </div>
	                            <div className="mt-3 grid gap-3 lg:grid-cols-3">
	                              <div>
	                                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Arc</div>
	                                <div className="mt-1 text-[11px] leading-relaxed text-slate-300">{compactList(creativePackage.venuePattern.recommendedArc ?? [], 5)}</div>
	                              </div>
	                              <div>
	                                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Must include</div>
	                                <div className="mt-1 text-[11px] leading-relaxed text-slate-300">{compactList(creativePackage.venuePattern.mustInclude ?? [], 4)}</div>
	                              </div>
	                              <div>
	                                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Avoid claims</div>
	                                <div className="mt-1 text-[11px] leading-relaxed text-amber-100">{compactList(creativePackage.venuePattern.avoidClaims ?? [], 4)}</div>
	                              </div>
	                            </div>
	                          </div>
	                        ) : null}
                        {creativePackage.venueDataGapAnalysis ? (
                          <div className="mt-3 rounded border border-amber-300/20 bg-amber-950/10 p-3">
                            <div className="flex flex-wrap items-start justify-between gap-2">
                              <div>
                                <div className="text-[10px] font-black uppercase tracking-widest text-amber-100">Venue data gap analysis</div>
                                <div className="mt-1 text-xs leading-relaxed text-slate-300">{formatStatus(creativePackage.venueDataGapAnalysis.status)}</div>
                              </div>
                              <div className="rounded border border-amber-300/30 bg-amber-950/20 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-amber-100">
                                {creativePackage.venueDataGapAnalysis.productionRealVenueReady ? "real venue ready" : "production gaps"}
                              </div>
                            </div>
                            <div className="mt-2 text-[11px] leading-relaxed text-slate-300">Missing: {compactList(creativePackage.venueDataGapAnalysis.missingForProduction ?? [], 4)}</div>
                            <div className="mt-1 text-[11px] leading-relaxed text-slate-500">Next imports: {compactList(creativePackage.venueDataGapAnalysis.nextProfileImports ?? [], 4)}</div>
                          </div>
                        ) : null}
                        {creativePackage.memoryInfluence ? (
                          <div className="mt-3 rounded border border-emerald-400/20 bg-emerald-950/10 p-3">
                            <div className="flex flex-wrap items-start justify-between gap-2">
                              <div>
                                <div className="text-[10px] font-black uppercase tracking-widest text-emerald-100">Finished-work memory</div>
                                <div className="mt-1 text-xs leading-relaxed text-slate-300">{creativePackage.memoryInfluence.learningBoundary}</div>
                              </div>
                              <div className="rounded border border-emerald-400/30 bg-emerald-950/20 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-emerald-100">
                                {creativePackage.memoryInfluence.usedForGeneration ? `${creativePackage.memoryInfluence.matchedCount ?? 0} matched` : formatStatus(creativePackage.memoryInfluence.status)}
                              </div>
                            </div>
                            <div className="mt-2 text-[11px] leading-relaxed text-slate-300">Reusable: {compactList(creativePackage.memoryInfluence.reusablePatterns ?? [], 3)}</div>
                            <div className="mt-1 text-[11px] leading-relaxed text-amber-100">Avoid: {compactList(creativePackage.memoryInfluence.avoidPatterns ?? [], 3)}</div>
                            {creativePackage.memoryInfluence.matchedExamples?.length ? (
                              <div className="mt-2 grid gap-2 lg:grid-cols-3">
                                {creativePackage.memoryInfluence.matchedExamples.slice(0, 3).map((item) => (
                                  <div key={item.draftId} className="rounded border border-emerald-400/20 bg-[#0d1115] p-2">
                                    <div className="text-xs font-black text-slate-100">{item.selectedConceptName}</div>
                                    <div className="mt-1 text-[10px] font-black uppercase tracking-widest text-slate-500">{item.status} / {item.draftId}</div>
                                    <div className="mt-1 text-[11px] leading-relaxed text-slate-400">{compactList(item.route ?? [], 4)}</div>
                                  </div>
                                ))}
                              </div>
                            ) : null}
                          </div>
                        ) : null}
                        {creativePackage.memoryApplication ? (
                          <div className="mt-3 rounded border border-emerald-400/20 bg-[#151914] p-3">
                            <div className="flex flex-wrap items-start justify-between gap-2">
                              <div>
                                <div className="text-[10px] font-black uppercase tracking-widest text-emerald-100">Memory application</div>
                                <div className="mt-1 text-xs leading-relaxed text-slate-300">{creativePackage.memoryApplication.reviewBoundary}</div>
                              </div>
                              <div className="rounded border border-emerald-400/30 bg-emerald-950/20 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-emerald-100">
                                {creativePackage.memoryApplication.usedForGeneration ? "visible" : formatStatus(creativePackage.memoryApplication.status)}
                              </div>
                            </div>
                            <div className="mt-2 text-[11px] leading-relaxed text-slate-300">Changed: {compactList(creativePackage.memoryApplication.visibleChanges ?? [], 3)}</div>
                            <div className="mt-1 text-[11px] leading-relaxed text-slate-500">Preserved: {compactList(creativePackage.memoryApplication.preservedPatterns ?? [], 3)}</div>
                            <div className="mt-1 text-[11px] leading-relaxed text-amber-100">Avoided: {compactList(creativePackage.memoryApplication.avoidedPatterns ?? [], 3)}</div>
                          </div>
                        ) : null}
                        {creativePackage.approvedRuleInfluence ? (
                          <div className="mt-3 rounded border border-lime-300/20 bg-lime-950/10 p-3">
                            <div className="flex flex-wrap items-start justify-between gap-2">
                              <div>
                                <div className="text-[10px] font-black uppercase tracking-widest text-lime-100">Approved rule influence</div>
                                <div className="mt-1 text-xs leading-relaxed text-slate-300">{creativePackage.approvedRuleInfluence.learningBoundary}</div>
                              </div>
                              <div className="rounded border border-lime-300/30 bg-lime-950/20 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-lime-100">
                                {creativePackage.approvedRuleInfluence.usedForGeneration ? `${creativePackage.approvedRuleInfluence.ruleCount ?? 0} active` : formatStatus(creativePackage.approvedRuleInfluence.status)}
                              </div>
                            </div>
                            <div className="mt-2 text-[11px] leading-relaxed text-slate-300">Rules: {compactList(creativePackage.approvedRuleInfluence.appliedRules ?? [], 3)}</div>
                            <div className="mt-1 text-[11px] leading-relaxed text-amber-100">Guardrails: {compactList(creativePackage.approvedRuleInfluence.guardrails ?? [], 3)}</div>
                            <div className="mt-1 text-[10px] font-black uppercase tracking-widest text-slate-500">{creativePackage.approvedRuleInfluence.authority ?? "human_promoted_rules_only"}</div>
                          </div>
                        ) : null}
	                      </div>
	                    ) : null}
	                    {creativeSynthesis ? (
	                      <div className="mt-4 rounded border border-rose-300/25 bg-[#0d1115] p-3">
	                        <div className="flex flex-wrap items-start justify-between gap-2">
	                          <div>
	                            <div className="text-[10px] font-black uppercase tracking-widest text-rose-200">Creative synthesis</div>
	                            <div className="mt-1 text-lg font-black text-white">{creativeSynthesis.selectedConceptName ?? "Selected creative concept"}</div>
	                            <p className="mt-2 max-w-4xl text-xs leading-relaxed text-slate-400">{creativeSynthesis.decision?.whySelected ?? creativeSynthesis.selectedConcept?.positioning}</p>
	                          </div>
	                          <div className="flex flex-wrap gap-2">
	                            <div className="rounded border border-slate-700 bg-[#151914] px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-400">
	                              {creativeSynthesis.mode ?? "synthesis"}
	                            </div>
	                            {creativeSynthesis.llmPolish ? (
	                              <div className="rounded border border-emerald-400/30 bg-emerald-950/20 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-emerald-100">
	                                LLM polish {formatStatus(creativeSynthesis.llmPolish.status)} / {creativeSynthesis.llmPolish.acceptedFields ?? 0} accepted
	                              </div>
	                            ) : null}
	                          </div>
	                        </div>
	                        <div className="mt-3 grid gap-3 lg:grid-cols-3">
	                          {(creativeSynthesis.concepts ?? []).map((concept) => (
	                            <div
	                              key={concept.id ?? concept.name}
	                              className={`rounded border bg-[#151914] p-3 ${
	                                concept.id === creativeSynthesis.selectedConceptId ? "border-rose-300/45" : "border-slate-800"
	                              }`}
	                            >
	                              <div className="flex items-start justify-between gap-2">
	                                <div>
	                                  <div className="text-xs font-black text-slate-100">{concept.name}</div>
	                                  <div className="mt-1 text-[11px] leading-relaxed text-slate-500">{concept.positioning}</div>
	                                </div>
	                                <div className="rounded border border-slate-700 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-400">{concept.totalScore ?? "n/a"}</div>
	                              </div>
	                              <div className="mt-2 text-[11px] leading-relaxed text-slate-300">{concept.guestPromise}</div>
	                              <div className="mt-2 flex flex-wrap gap-1">
	                                {(concept.heroTerms ?? []).slice(0, 6).map((term) => (
	                                  <span key={term} className="rounded border border-slate-800 bg-[#0d1115] px-2 py-1 text-[10px] font-bold text-slate-400">{term}</span>
	                                ))}
	                              </div>
	                              {concept.reviewRisks?.length ? <div className="mt-2 text-[11px] leading-relaxed text-amber-100">{compactList(concept.reviewRisks, 3)}</div> : null}
	                            </div>
	                          ))}
	                        </div>
	                        <div className="mt-3 grid gap-3 lg:grid-cols-3">
	                          <div className="rounded border border-slate-800 bg-[#151914] p-3">
	                            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Guest app variant</div>
	                            <div className="mt-2 text-xs font-black text-slate-100">{creativeSynthesis.copyVariants?.guestApp?.headline ?? "not set"}</div>
	                            <div className="mt-1 text-[11px] leading-relaxed text-slate-300">{creativeSynthesis.copyVariants?.guestApp?.body}</div>
	                            <div className="mt-1 text-[11px] leading-relaxed text-slate-500">{creativeSynthesis.copyVariants?.guestApp?.microcopy}</div>
	                          </div>
	                          <div className="rounded border border-slate-800 bg-[#151914] p-3">
	                            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Email variant</div>
	                            <div className="mt-2 text-xs font-black text-slate-100">{creativeSynthesis.copyVariants?.email?.subject ?? "not set"}</div>
	                            <div className="mt-1 text-[11px] leading-relaxed text-slate-500">{creativeSynthesis.copyVariants?.email?.previewText}</div>
	                            <div className="mt-1 text-[11px] leading-relaxed text-slate-300">{creativeSynthesis.copyVariants?.email?.body}</div>
	                          </div>
	                          <div className="rounded border border-slate-800 bg-[#151914] p-3">
	                            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Rewrite strategy</div>
	                            <div className="mt-2 text-[11px] leading-relaxed text-slate-300">Use: {compactList(creativeSynthesis.rewriteStrategy?.useMoreOf ?? [], 4)}</div>
	                            <div className="mt-1 text-[11px] leading-relaxed text-slate-500">Preserve: {compactList(creativeSynthesis.rewriteStrategy?.preserve ?? [], 3)}</div>
	                            <div className="mt-1 text-[11px] leading-relaxed text-amber-100">Avoid: {compactList(creativeSynthesis.rewriteStrategy?.avoid ?? [], 3)}</div>
	                          </div>
	                        </div>
	                        {creativeSynthesis.llmPolish?.rejectedFields?.length ? (
	                          <div className="mt-3 rounded border border-amber-400/20 bg-amber-950/10 p-3">
	                            <div className="text-[10px] font-black uppercase tracking-widest text-amber-100">Rejected LLM fields</div>
	                            <div className="mt-2 text-[11px] leading-relaxed text-amber-50">
	                              {compactList(creativeSynthesis.llmPolish.rejectedFields.map((item) => `${item.field}: ${item.reason}`), 4)}
	                            </div>
	                          </div>
	                        ) : null}
	                      </div>
	                    ) : null}
	                    {experienceReasoning ? (
	                      <div className="mt-4 rounded border border-violet-300/25 bg-[#0d1115] p-3">
	                        <div className="flex flex-wrap items-start justify-between gap-2">
	                          <div>
	                            <div className="text-[10px] font-black uppercase tracking-widest text-violet-200">Design reasoning</div>
	                            <div className="mt-1 text-lg font-black text-white">{experienceReasoning.selectedConceptLabel ?? "Selected concept"}</div>
	                            <p className="mt-2 max-w-4xl text-xs leading-relaxed text-slate-400">{experienceReasoning.decision?.whySelected ?? "Reasoning is attached to this generation."}</p>
	                          </div>
	                          <div className="rounded border border-slate-700 bg-[#151914] px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-400">
	                            Score {experienceReasoning.decision?.totalScore ?? "n/a"}
	                          </div>
	                        </div>
	                        <div className="mt-3 grid gap-3 lg:grid-cols-3">
	                          {(experienceReasoning.conceptRoutes ?? []).map((concept) => (
	                            <div
	                              key={concept.id ?? concept.label}
	                              className={`rounded border bg-[#151914] p-3 ${
	                                concept.id === experienceReasoning.selectedConceptId ? "border-violet-300/45" : "border-slate-800"
	                              }`}
	                            >
	                              <div className="flex items-start justify-between gap-2">
	                                <div>
	                                  <div className="text-xs font-black text-slate-100">{concept.label}</div>
	                                  <div className="mt-1 text-[11px] leading-relaxed text-slate-500">{concept.positioning}</div>
	                                </div>
	                                <div className="rounded border border-slate-700 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-400">{concept.totalScore ?? "n/a"}</div>
	                              </div>
	                              <div className="mt-2 flex flex-wrap gap-1">
	                                {Object.entries(concept.scores ?? {}).map(([label, value]) => (
	                                  <span key={label} className="rounded border border-slate-800 bg-[#0d1115] px-2 py-1 text-[10px] font-bold text-slate-400">
	                                    {formatStatus(label)} {value}
	                                  </span>
	                                ))}
	                              </div>
	                              <div className="mt-2 text-[11px] leading-relaxed text-slate-300">{compactList(concept.route ?? [], 4)}</div>
	                              {concept.riskFlags?.length ? <div className="mt-2 text-[11px] leading-relaxed text-amber-100">{compactList(concept.riskFlags, 2)}</div> : null}
	                            </div>
	                          ))}
	                        </div>
	                        <div className="mt-3 grid gap-3 lg:grid-cols-3">
	                          <div className="rounded border border-slate-800 bg-[#151914] p-3">
	                            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Evidence</div>
	                            <div className="mt-2 grid gap-1 text-[11px] leading-relaxed text-slate-300">
	                              {(experienceReasoning.decision?.decisiveEvidence ?? []).map((item) => <div key={item}>{item}</div>)}
	                            </div>
	                          </div>
	                          <div className="rounded border border-slate-800 bg-[#151914] p-3">
	                            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Critique and revision</div>
	                            <div className="mt-2 text-[11px] leading-relaxed text-amber-100">{compactList(experienceReasoning.critiqueAndRevision?.weakPointsFound ?? [], 2)}</div>
	                            <div className="mt-2 text-[11px] leading-relaxed text-slate-300">{compactList(experienceReasoning.critiqueAndRevision?.revisionsApplied ?? [], 3)}</div>
	                          </div>
	                          <div className="rounded border border-slate-800 bg-[#151914] p-3">
	                            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Guest lenses</div>
	                            <div className="mt-2 grid gap-2">
	                              {(experienceReasoning.guestLenses ?? []).map((lens) => (
	                                <div key={lens.guest} className="rounded border border-slate-800 bg-[#0d1115] p-2">
	                                  <div className="text-xs font-black text-slate-100">{lens.guest}</div>
	                                  <div className="mt-1 text-[11px] leading-relaxed text-slate-500">{lens.likelyExperience}</div>
	                                  <div className="mt-1 text-[11px] leading-relaxed text-slate-300">{lens.designResponse}</div>
	                                </div>
	                              ))}
	                            </div>
	                          </div>
	                        </div>
	                      </div>
	                    ) : null}
	                    {studioCore ? (
	                      <div className="mt-4 rounded border border-lime-300/25 bg-[#0d1115] p-3">
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <div>
                            <div className="text-[10px] font-black uppercase tracking-widest text-lime-200">Preset LLM core</div>
                            <div className="mt-1 text-xs leading-relaxed text-slate-300">{studioCore.mission}</div>
                          </div>
                          <div className="rounded border border-slate-700 bg-[#151914] px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-400">{studioCore.version ?? "v1"}</div>
                        </div>
                        {studioCore.source ? <div className="mt-2 truncate text-[11px] leading-relaxed text-slate-500">Source: {studioCore.source}</div> : null}
                        <div className="mt-3 grid gap-2 md:grid-cols-2">
                          <div className="rounded border border-slate-800 bg-[#151914] p-3">
                            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Core values</div>
                            <div className="mt-2 text-xs leading-relaxed text-slate-300">{compactList(studioCore.coreValues, 6)}</div>
                          </div>
                          <div className="rounded border border-slate-800 bg-[#151914] p-3">
                            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Reasoning priorities</div>
                            <div className="mt-2 text-xs leading-relaxed text-slate-300">{compactList(studioCore.reasoningPriorities, 5)}</div>
                          </div>
                        </div>
                      </div>
                    ) : null}
                    {draft.reasoningTrace?.length ? (
                      <div className="mt-4 border-t border-slate-800 pt-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div>
                            <div className="text-[10px] font-black uppercase tracking-widest text-cyan-200">Reasoning trace</div>
                            <div className="mt-1 text-xs leading-relaxed text-slate-500">Deterministic grounding first, optional LLM polish second, gates re-run last.</div>
                          </div>
                          <div className={`rounded border px-2 py-1 text-[10px] font-black uppercase tracking-widest ${draftPayload?.llm?.status === "ready" ? "border-emerald-400/40 bg-emerald-950/25 text-emerald-100" : draftPayload?.llm?.status === "fallback" ? "border-amber-400/40 bg-amber-950/25 text-amber-100" : "border-slate-700 bg-[#0d1115] text-slate-400"}`}>
                            LLM {draftPayload?.llm?.status ?? "not requested"}
                          </div>
                        </div>
                        <div className="mt-3 grid gap-2">
                          {draft.reasoningTrace.map((item, index) => (
                            <div key={`${item.step}-${index}`} className="rounded border border-slate-800 bg-[#0d1115] p-3">
                              <div className="text-xs font-black text-slate-100">{index + 1}. {formatStatus(item.step)}</div>
                              <div className="mt-1 text-xs leading-relaxed text-slate-400">{item.summary}</div>
                            </div>
                          ))}
                        </div>
                        {draft.llmCreativePass ? (
                          <div className="mt-3 rounded border border-slate-800 bg-[#0d1115] p-3">
                            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">LLM merge guard</div>
                            <div className="mt-2 text-xs leading-relaxed text-slate-300">
                              Status: {formatStatus(draft.llmCreativePass.status)} / route accepted: {draft.llmCreativePass.routeAccepted ? "yes" : "no"} / synthesis fields accepted: {draft.llmCreativePass.synthesisAcceptedFields ?? 0}
                            </div>
                            {draft.llmCreativePass.synthesisRejectedFields?.length ? <div className="mt-2 text-[11px] leading-relaxed text-amber-100">Rejected: {compactList(draft.llmCreativePass.synthesisRejectedFields.map((item) => `${item.field}: ${item.reason}`), 3)}</div> : null}
                            {draft.llmCreativePass.creativeRationale?.length ? <div className="mt-2 text-[11px] leading-relaxed text-slate-500">Rationale: {compactList(draft.llmCreativePass.creativeRationale, 3)}</div> : null}
                          </div>
                        ) : null}
                        {draftPayload?.memoryPersistence ? (
                          <div className="mt-3 rounded border border-slate-800 bg-[#0d1115] p-3">
                            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Memory receipt</div>
                            <div className="mt-2 text-xs leading-relaxed text-slate-300">
                              {formatStatus(draftPayload.memoryPersistence.status)} / {draftPayload.memoryPersistence.collection ?? "experience studio memory"} / {draftPayload.memoryPersistence.connected ? "MongoDB" : formatStatus(draftPayload.memoryPersistence.mode)}
                            </div>
                            <div className="mt-1 text-[11px] leading-relaxed text-slate-500">
                              {draftPayload.memoryPersistence.memoryId ? `ID ${draftPayload.memoryPersistence.memoryId}. ` : ""}
                              Generated copy is stored as an audit receipt only; Studio reasoning comes from the preset core and verified profile.
                            </div>
                          </div>
                        ) : null}
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
                    <button
                      type="button"
                      onClick={() => void promoteLearningRule()}
                      disabled={isPromotingRule || !activeDraftId || !["approved", "ready_for_publish"].includes(workflowStatus)}
                      className="mt-2 w-full rounded border border-lime-300 bg-lime-300 px-3 py-2 text-sm font-black text-slate-950 transition hover:bg-lime-200 disabled:cursor-not-allowed disabled:border-slate-700 disabled:bg-[#0d1115] disabled:text-slate-500"
                    >
                      {isPromotingRule ? "Promoting rule" : "Promote approved rule"}
                    </button>
                    <div className="mt-2 text-[11px] leading-relaxed text-slate-500">
                      Promotion uses approved finished work only. It creates reversible rule context for future drafts, not model training.
                    </div>
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

            <div className="rounded-lg border border-lime-300/25 bg-[#151914] p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-[10px] font-black uppercase tracking-widest text-lime-200">Studio memory</div>
                  <h2 className="mt-1 text-lg font-black text-white">Core and receipts</h2>
                </div>
                <button
                  type="button"
                  onClick={() => void refreshStudioMemory()}
                  disabled={isLoadingMemory}
                  className="rounded border border-slate-700 bg-[#0d1115] px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-300 transition hover:border-lime-300 disabled:opacity-50"
                >
                  {isLoadingMemory ? "Loading" : "Refresh"}
                </button>
              </div>
              <div className={`mt-3 w-fit rounded border px-2 py-1 text-[10px] font-black uppercase tracking-widest ${studioMemory?.status === "ready" ? "border-emerald-400/40 bg-emerald-950/25 text-emerald-100" : "border-amber-400/40 bg-amber-950/25 text-amber-100"}`}>
                {studioMemory?.memoryLayer ?? "not loaded"}
              </div>
              <div className="mt-3 grid gap-2 text-xs">
                {[
                  ["Primary", studioMemory?.memoryConnection?.primary ?? "not connected"],
                  ["Connected", studioMemory?.memoryConnection?.connected ? "yes" : "no"],
                  ["Mode", studioMemory?.memoryConnection?.mode ?? "unknown"],
                  ["Database", studioMemory?.memoryConnection?.database ?? "not connected"],
                ].map(([label, value]) => (
                  <div key={label} className="grid grid-cols-[6rem_1fr] gap-2 rounded border border-slate-800 bg-[#0d1115] px-3 py-2">
                    <span className="font-black uppercase tracking-widest text-slate-500">{label}</span>
                    <span className="font-bold text-slate-200">{value}</span>
                  </div>
                ))}
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2">
                {studioMemoryCollectionMeta.map((item) => (
                  <div key={item.id} className="rounded border border-slate-800 bg-[#0d1115] p-3">
                    <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{item.label}</div>
                    <div className="mt-1 text-xl font-black text-slate-100">{studioMemoryCounts[item.id] ?? 0}</div>
                  </div>
                ))}
              </div>
              <div className="mt-3 rounded border border-slate-800 bg-[#0d1115] p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Memory boundary</div>
                <p className="mt-2 text-xs leading-relaxed text-slate-300">
                  {studioMemory?.learningPolicy?.rule ?? "Generated packages and reviews are stored for audit; Studio reasoning comes from the preset core and verified profile."}
                </p>
                <div className="mt-2 grid gap-2 text-[11px] leading-relaxed text-slate-500">
                  <div>No feedback loop: on</div>
                  <div>Generated copy: {studioMemory?.learningPolicy?.generatedTextLearningEligible ? "learning eligible" : "evidence only"}</div>
                  <div>Review receipts: {studioMemory?.learningPolicy?.humanFeedbackLearningEligible ? "learning eligible" : "audit only"}</div>
                </div>
              </div>
              <div className="mt-3 grid gap-2 text-xs">
                <div className="grid grid-cols-[6rem_1fr] gap-2 rounded border border-slate-800 bg-[#0d1115] px-3 py-2">
                  <span className="font-black uppercase tracking-widest text-slate-500">Last write</span>
                  <span className="font-bold text-slate-200">{formatTimestamp(latestStudioMemoryReceipt?.updatedAt ?? latestStudioMemoryReceipt?.createdAt)}</span>
                </div>
                <div className="grid grid-cols-[6rem_1fr] gap-2 rounded border border-slate-800 bg-[#0d1115] px-3 py-2">
                  <span className="font-black uppercase tracking-widest text-slate-500">Receipt ID</span>
                  <span className="truncate font-bold text-slate-200">{latestStudioMemoryReceipt?._id ?? latestStudioMemoryReceipt?.id ?? "not loaded"}</span>
                </div>
                <div className="grid grid-cols-[6rem_1fr] gap-2 rounded border border-slate-800 bg-[#0d1115] px-3 py-2">
                  <span className="font-black uppercase tracking-widest text-slate-500">Retention</span>
                  <span className="font-bold text-slate-200">{retentionEntries.length ? `${retentionEntries.length} policy buckets` : "not loaded"}</span>
                </div>
              </div>
              <div className="mt-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Latest receipts</div>
                <div className="mt-2 grid gap-2">
                  {latestStudioMemoryReceipts.length ? (
                    latestStudioMemoryReceipts.map((item, index) => (
                      <div key={`${item.collection ?? item.eventType ?? "memory"}-${item._id ?? item.id ?? index}`} className="rounded border border-slate-800 bg-[#0d1115] p-3">
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate text-xs font-black text-slate-100">{formatStatus(item.eventType ?? item.status ?? "memory event")}</span>
                          <span className="rounded border border-slate-700 bg-[#11161a] px-2 py-1 text-[9px] font-black uppercase tracking-widest text-slate-400">
                            audit
                          </span>
                        </div>
                        <div className="mt-1 text-[11px] leading-relaxed text-slate-500">
                          {formatStatus(item.collection ?? item.learningSource ?? "receipt")} / {formatTimestamp(item.updatedAt ?? item.createdAt)}
                        </div>
                        {(item.title || item.draftId || item.handoffId || item.memoryId) ? (
                          <div className="mt-1 truncate text-[11px] leading-relaxed text-slate-500">
                            {item.title ?? item.draftId ?? item.handoffId ?? item.memoryId}
                          </div>
                        ) : null}
                      </div>
                    ))
                  ) : (
                    <div className="rounded border border-slate-800 bg-[#0d1115] p-3 text-xs leading-relaxed text-slate-500">
                      No Studio memory receipts loaded yet.
                    </div>
                  )}
                </div>
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
