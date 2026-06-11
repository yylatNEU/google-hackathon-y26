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
  | "festival-plan"
  | "seasonal-overlay"
  | "food-festival"
  | "photo-moment-route"
  | "accessibility-family-day"
  | "teen-night-out"
  | "first-time-visitor"
  | "date-night"
  | "education-field-trip"
  | "post-incident-recovery-copy"
  | "retail-merch-quest"
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

type PlannerReasonedPlan = {
  status?: string;
  basis?: string;
  plannerRequest?: string;
  planName?: string;
  selectedToolIds?: string[];
  strategy?: {
    objective?: string;
    audienceReasoning?: string;
    routeStrategy?: string;
    channelStrategy?: string;
    riskTradeoffs?: string[];
  };
  programPhases?: Array<{
    name?: string;
    duration?: string;
    guestJob?: string;
    heroMoment?: string;
    channels?: string[];
    reviewGate?: string;
  }>;
  signatureMoments?: Array<{ name?: string; venueEvidence?: string; guestAction?: string; reviewNeed?: string }>;
  evidenceUse?: Array<{ evidenceId?: string; usedFor?: string }>;
  agentStageNotes?: Array<{ stageId?: string; decision?: string }>;
  contentPillars?: string[];
  ownerQuestions?: string[];
  retrievalEvidence?: RetrievalEvidenceContext;
  agentWorkflow?: AgentWorkflowReceipt;
  productReadiness?: ProductReadinessGate;
  toolRouter?: ToolRouterReceipt;
  strategyOrchestration?: StrategyOrchestrationReceipt;
  llmReasoningStatus?: string;
  llmTransport?: string;
  guardrails?: string[];
};

type ToolRouterReceipt = {
  mode?: string;
  status?: string;
  templateId?: string;
  selectedToolIds?: string[];
  availableToolIds?: string[];
  routingPrinciple?: string;
  routedTools?: Array<{ id?: string; type?: string; role?: string; status?: string; why?: string }>;
};

type StrategyOrchestrationReceipt = {
  mode?: string;
  status?: string;
  candidateCount?: number;
  toolRouter?: ToolRouterReceipt;
  candidates?: Array<{
    id?: string;
    label?: string;
    totalScore?: number;
    maxScore?: number;
    normalizedScore?: number;
    rationale?: string;
    risk?: string;
    dimensions?: Array<{ id?: string; label?: string; score?: number; why?: string }>;
  }>;
  selectedStrategy?: {
    id?: string;
    label?: string;
    totalScore?: number;
    maxScore?: number;
    normalizedScore?: number;
    rationale?: string;
    risk?: string;
    dimensions?: Array<{ id?: string; label?: string; score?: number; why?: string }>;
  };
  evaluationCoverage?: {
    dimensions?: string[];
    venueAspectCoverage?: Record<string, boolean>;
  };
  decisiveEvidence?: Array<{ id?: string; kind?: string; score?: number; why?: string[] }>;
  handoffNotes?: string[];
};

type RetrievalEvidenceItem = {
  id?: string;
  source?: string;
  kind?: string;
  score?: number;
  why?: string[];
  data?: Record<string, unknown>;
};

type RetrievalEvidenceContext = {
  mode?: string;
  status?: string;
  query?: Record<string, unknown>;
  retrievedEvidence?: RetrievalEvidenceItem[];
  evidenceSummary?: {
    locationCount?: number;
    ruleCount?: number;
    learningRuleCount?: number;
    memoryCount?: number;
    topSources?: string[];
  };
  memoryGate?: {
    status?: string;
    accepted?: Array<{ id?: string; title?: string; selectedConceptName?: string; status?: string; why?: string[] }>;
    rejected?: Array<{ id?: string; reason?: string }>;
    authority?: string;
    boundary?: string;
  };
  retrievalBoundary?: string[];
};

type AgentWorkflowReceipt = {
  mode?: string;
  status?: string;
  stages?: Array<{
    id?: string;
    agent?: string;
    status?: string;
    input?: string;
    output?: string;
    risk?: string;
  }>;
  handoffContract?: {
    draftAuthority?: boolean;
    publishAuthority?: boolean;
    operationsAuthority?: boolean;
    requiresHumanOwners?: string[];
  };
};

type ProductReadinessGate = {
  mode?: string;
  status?: string;
  score?: number;
  checks?: Array<{ id?: string; label?: string; status?: string; evidence?: string }>;
  nextBestAction?: string;
};

type PlannerLlmReasoning = {
  status?: string;
  planner?: string;
  planName?: string;
  selectedTemplateId?: string;
  selectedToolIds?: string[];
  acceptedPayloadFields?: string[];
  rejectedFields?: Array<{ field?: string; reason?: string }>;
  strategy?: PlannerReasonedPlan["strategy"];
  programPhases?: PlannerReasonedPlan["programPhases"];
  signatureMoments?: PlannerReasonedPlan["signatureMoments"];
  contentPillars?: string[];
  ownerQuestions?: string[];
  reviewBoundaries?: string[];
  transport?: string;
  error?: string;
  fallbackBasis?: string;
  guardrails?: string[];
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
    plannerReasonedPlan?: PlannerReasonedPlan;
    retrievalEvidence?: RetrievalEvidenceContext;
    agentWorkflow?: AgentWorkflowReceipt;
    productReadiness?: ProductReadinessGate;
    designIterationStrategy?: DesignIterationPayload["designIterationStrategy"];
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
    visualAssetStudio?: VisualAssetStudio;
    eventTeamMarketingPackage?: {
      status?: string;
      mode?: string;
      audience?: string;
      publishAuthority?: boolean;
      eventBrief?: {
        eventName?: string;
        venue?: string;
        format?: string;
        targetAudience?: string;
        runShape?: string;
        route?: string[];
        guestPromise?: string;
        successMetric?: string;
      };
      programPhases?: Array<{ name?: string; duration?: string; guestJob?: string; heroMoment?: string; reviewGate?: string }>;
      presentationSections?: Array<{ title?: string; talkTrack?: string; show?: string[] }>;
      deliverables?: Array<{ id?: string; owner?: string; asset?: string; source?: string; status?: string }>;
      workstreams?: Array<{ team?: string; job?: string; decisionNeeded?: string }>;
      teamDecisionLog?: string[];
      reasoningBrief?: {
        status?: string;
        basis?: string;
        planName?: string;
        llmReasoningStatus?: string;
        objective?: string;
        routeStrategy?: string;
        channelStrategy?: string;
        riskTradeoffs?: string[];
        selectedRouteReason?: string;
        selectedRouteScore?: number;
        decisiveEvidence?: string[];
        guestLenses?: Array<{ guest?: string; likelyExperience?: string; designResponse?: string }>;
        weakPointsFound?: string[];
        revisionsApplied?: string[];
        signatureMoments?: Array<{ name?: string; venueEvidence?: string; guestAction?: string; reviewNeed?: string }>;
        evidenceUse?: Array<{ evidenceId?: string; usedFor?: string }>;
        agentStageNotes?: Array<{ stageId?: string; decision?: string }>;
        selectedToolIds?: string[];
        toolRouter?: {
          status?: string;
          selectedToolIds?: string[];
          routingPrinciple?: string;
        };
        selectedStrategy?: {
          id?: string;
          label?: string;
          score?: number;
          rationale?: string;
          risk?: string;
          dimensions?: Array<{ id?: string; label?: string; score?: number; why?: string }>;
        };
        candidateScores?: Array<{ id?: string; label?: string; score?: number; risk?: string }>;
        evaluationCoverage?: {
          dimensions?: string[];
          venueAspectCoverage?: Record<string, boolean>;
        };
        orchestrationHandoff?: string[];
        selectedConcept?: {
          id?: string;
          name?: string;
          positioning?: string;
          guestPromise?: string;
          contentDepthPlan?: string[];
          reviewRisks?: string[];
        };
        conceptCandidateScores?: Array<{ id?: string; name?: string; score?: number; critique?: string }>;
        conceptCritique?: {
          status?: string;
          weakPointsFound?: string[];
          revisionsApplied?: string[];
          reviewers?: Array<{ id?: string; decision?: string }>;
        };
      };
      assetPlan?: {
        visualPromptCount?: number;
        visualModel?: string;
        visualStatus?: string;
        copyChannels?: string[];
        signagePlacements?: string[];
        staffCueReady?: boolean;
      };
      executionBoundary?: string[];
    };
    craftArtifacts?: {
      status?: string;
      purpose?: string;
      samples?: Array<{ id?: string; label?: string; channel?: string; copy?: string; whyItHelps?: string; reviewGate?: string }>;
      craftNotes?: string[];
    };
    productionDetail?: {
      guestChoiceModel?: string[];
      reasonedProgramPhases?: PlannerReasonedPlan["programPhases"];
      plannerEvidence?: {
        selectedToolIds?: string[];
        llmReasoningStatus?: string;
        basis?: string;
        retrievalSummary?: RetrievalEvidenceContext["evidenceSummary"];
        agentWorkflowStatus?: string;
        productReadinessScore?: number;
      };
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
  plannerContext?: {
    source?: string;
    designerRequest?: string;
    generatedAt?: string;
    recommendedPlanLabel?: string;
    recommendedPlanWhy?: string;
    recommendedPayload?: Partial<Record<string, unknown>>;
    parsedBrief?: ConversationPlanPayload["parsedBrief"];
    plannerIntelligence?: ConversationPlanPayload["plannerIntelligence"];
    planningTools?: ConversationPlanPayload["planningTools"];
    reasonedPlan?: PlannerReasonedPlan;
    llmReasoning?: PlannerLlmReasoning;
    retrievalEvidence?: RetrievalEvidenceContext;
    agentWorkflow?: AgentWorkflowReceipt;
    productReadiness?: ProductReadinessGate;
    planStatus?: string;
  };
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

type VisualAssetPrompt = {
  id?: string;
  label?: string;
  format?: string;
  aspectRatio?: string;
  prompt?: string;
  negativePrompt?: string;
  copyOverlay?: Record<string, unknown>;
  reviewGate?: string;
};

type VisualAssetStudio = {
  status?: string;
  mode?: string;
  model?: string;
  promptCount?: number;
  prompts?: VisualAssetPrompt[];
  posterCreation?: {
    recommendedPrimaryPromptId?: string;
    safeForDemo?: boolean;
    publishAuthority?: boolean;
    outputUse?: string;
  };
  providerReadiness?: {
    provider?: string;
    platform?: string;
    ready?: boolean;
    readinessIssues?: string[];
  };
  guardrails?: string[];
};

type VisualAssetResult = {
  status?: string;
  mode?: string;
  providerReadiness?: VisualAssetStudio["providerReadiness"];
  visualAssetStudio?: VisualAssetStudio;
  selectedPrompts?: VisualAssetPrompt[];
  results?: Array<{
    status?: string;
    model?: string;
    promptId?: string;
    imageCount?: number;
    images?: Array<{ id?: string; mimeType?: string; dataUrl?: string; assetPath?: string; reviewStatus?: string }>;
    detail?: string;
    readinessIssues?: string[];
  }>;
  persistence?: {
    status?: string;
    assetCount?: number;
    receiptPath?: string;
    assets?: Array<{ id?: string; promptId?: string; path?: string; reviewStatus?: string }>;
  };
  imageCount?: number;
  message?: string;
  boundary?: string;
};

type EventTeamPdfResult = {
  status?: string;
  mode?: string;
  pdfPath?: string;
  fileName?: string;
  pageCount?: number;
  sizeBytes?: number;
  pdfDataUrl?: string;
  message?: string;
  boundary?: string;
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

type DesignIterationPayload = {
  status?: string;
  mode?: string;
  command?: string;
  sections?: string[];
  draft?: ExperienceDraft;
  designIterationStrategy?: {
    mode?: string;
    intentTags?: string[];
    guestJob?: string;
    routeArc?: string[];
    copyRules?: string[];
    lockedFacts?: {
      routeStops?: string[];
      venueSource?: string;
      profileType?: string;
      llmMayChangeStops?: boolean;
      llmMayPublish?: boolean;
    };
    reviewFocus?: string[];
  };
  iterationSummary?: {
    appliedCount?: number;
    applied?: Array<{ sectionId?: string; qaDelta?: SectionRevisionPayload["qaDelta"]; reviewAgentStatus?: string }>;
    reviewAgentStatus?: string;
    strategyTags?: string[];
    routeArc?: string[];
    lockedRouteStops?: string[];
    boundary?: string;
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
  planningTools?: Array<{ id?: string; type?: string; label?: string; instruction?: string; data?: unknown; items?: unknown[] }>;
  reasonedPlan?: PlannerReasonedPlan;
  llmReasoning?: PlannerLlmReasoning;
  retrievalEvidence?: RetrievalEvidenceContext;
  agentWorkflow?: AgentWorkflowReceipt;
  productReadiness?: ProductReadinessGate;
  toolRouter?: ToolRouterReceipt;
  strategyOrchestration?: StrategyOrchestrationReceipt;
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
  { id: "festival-plan", label: "Festival plan", audience: "families, friend groups, and multigenerational guests", tone: "festive, respectful, warm, culturally careful", detail: "Month-long seasonal programming package." },
  { id: "seasonal-overlay", label: "Seasonal overlay", audience: "families, friend groups, and seasonal visitors", tone: "seasonal, warm, specific, reviewable", detail: "Temporary overlay with story and channel copy." },
  { id: "food-festival", label: "Food festival", audience: "food-curious families and friend groups", tone: "appetizing, careful, menu-safe", detail: "Dining trail with menu-safe boundaries." },
  { id: "photo-moment-route", label: "Photo route", audience: "social guests, families, and photo-focused groups", tone: "visual, concise, upbeat", detail: "Photo spot route with app and signage prompts." },
  { id: "accessibility-family-day", label: "Accessible family day", audience: "families planning around accessibility needs", tone: "plain, respectful, choice-forward", detail: "Family journey with access choices and rest points." },
  { id: "teen-night-out", label: "Teen night", audience: "teen friend groups and older kids with caregivers", tone: "social, energetic, safe, not childish", detail: "Evening social path with regroup cues." },
  { id: "first-time-visitor", label: "First visit", audience: "first-time visitors and mixed family groups", tone: "clear, welcoming, orientation-first", detail: "Orientation journey for new guests." },
  { id: "date-night", label: "Date night", audience: "adult couples and evening guests", tone: "warm, relaxed, tasteful", detail: "Relaxed evening route with scenic moments." },
  { id: "education-field-trip", label: "Field trip", audience: "student groups, teachers, and chaperones", tone: "curious, clear, chaperone-friendly", detail: "Learning journey with group pacing." },
  { id: "post-incident-recovery-copy", label: "Recovery copy", audience: "affected guests and guest-care teams", tone: "empathetic, calm, accountable", detail: "Post-disruption messaging, not operations." },
  { id: "retail-merch-quest", label: "Merch quest", audience: "families, collectors, and retail-curious guests", tone: "playful, collectible, non-purchase-pressure", detail: "Retail-linked quest with non-purchase options." },
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
  { id: "experience_studio_approved_work", label: "approved work" },
  { id: "experience_studio_feedback", label: "feedback" },
  { id: "experience_studio_revision_events", label: "revisions" },
  { id: "experience_studio_learning_rules", label: "learning rules" },
  { id: "experience_studio_venue_snapshots", label: "venue snapshots" },
  { id: "experience_studio_eval_examples", label: "eval examples" },
];

const defaultCnyFestivalPrompt =
  "Create a Chinese New Year festival plan that runs for a month with food, craft, signage, email, and staff cues.";

function downloadDataUrl(dataUrl: string, fileName: string) {
  const [metadata, encoded] = dataUrl.split(",");
  if (!metadata?.startsWith("data:") || !encoded) return false;
  const mimeType = metadata.match(/^data:([^;]+)/)?.[1] ?? "application/octet-stream";
  const binary = globalThis.atob(encoded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  const objectUrl = URL.createObjectURL(new Blob([bytes], { type: mimeType }));
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = fileName;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  return true;
}

const creativeDefaultsByTemplate: Record<ExperienceTemplateId, {
  creativeDirection: string;
  storyArc: string;
  sensoryLevel: string;
  walkingPace: string;
  outputPackage: string;
  seasonalTheme: string;
}> = {
  "festival-plan": {
    creativeDirection: "seasonal festival programming",
    storyArc: "Launch weekend -> discovery weeks -> food and craft moments -> performance spotlight -> lantern finale",
    sensoryLevel: "balanced",
    walkingPace: "flexible",
    outputPackage: "full festival package",
    seasonalTheme: "Chinese New Year festival month",
  },
  "halloween-route": {
    creativeDirection: "story-rich",
    storyArc: "Invitation -> clue -> reveal -> choice -> finale",
    sensoryLevel: "balanced",
    walkingPace: "moderate",
    outputPackage: "full package",
    seasonalTheme: "family-safe Halloween mystery",
  },
  "seasonal-overlay": {
    creativeDirection: "seasonal overlay",
    storyArc: "Arrival signal -> themed discovery -> photo pause -> flexible choice -> seasonal close",
    sensoryLevel: "balanced",
    walkingPace: "flexible",
    outputPackage: "full seasonal overlay package",
    seasonalTheme: "seasonal park overlay",
  },
  "food-festival": {
    creativeDirection: "food-forward discovery",
    storyArc: "Taste invite -> sample stop -> seated reset -> craft or retail pairing -> flavor finale",
    sensoryLevel: "balanced",
    walkingPace: "moderate",
    outputPackage: "food trail package",
    seasonalTheme: "food festival trail",
  },
  "photo-moment-route": {
    creativeDirection: "visual story route",
    storyArc: "Photo invite -> landmark shot -> scenic transition -> group moment -> shareable close",
    sensoryLevel: "balanced",
    walkingPace: "flexible",
    outputPackage: "photo route package",
    seasonalTheme: "photo moment route",
  },
  "accessibility-family-day": {
    creativeDirection: "accessibility-first family journey",
    storyArc: "Plain arrival -> step-free choice -> rest point -> flexible activity -> supported close",
    sensoryLevel: "low",
    walkingPace: "flexible",
    outputPackage: "accessible family journey",
    seasonalTheme: "accessible family day",
  },
  "teen-night-out": {
    creativeDirection: "social evening path",
    storyArc: "Meet-up -> photo beat -> food or hangout -> thrill or show choice -> regroup close",
    sensoryLevel: "balanced",
    walkingPace: "moderate",
    outputPackage: "teen night route package",
    seasonalTheme: "teen night out",
  },
  "first-time-visitor": {
    creativeDirection: "orientation-first journey",
    storyArc: "Arrival confidence -> park landmark -> first signature choice -> comfort reset -> next-step close",
    sensoryLevel: "balanced",
    walkingPace: "moderate",
    outputPackage: "first visit journey package",
    seasonalTheme: "first-time visitor path",
  },
  "date-night": {
    creativeDirection: "relaxed evening path",
    storyArc: "Warm welcome -> scenic pause -> food or show beat -> quiet choice -> photo close",
    sensoryLevel: "balanced",
    walkingPace: "relaxed",
    outputPackage: "date night route package",
    seasonalTheme: "date night route",
  },
  "education-field-trip": {
    creativeDirection: "learning journey",
    storyArc: "Group arrival -> observation prompt -> learning stop -> lunch or reset -> reflection close",
    sensoryLevel: "balanced",
    walkingPace: "structured",
    outputPackage: "field trip guide package",
    seasonalTheme: "education field trip",
  },
  "post-incident-recovery-copy": {
    creativeDirection: "empathetic recovery messaging",
    storyArc: "Acknowledge -> orient -> support option -> current source -> follow-up close",
    sensoryLevel: "low",
    walkingPace: "compact",
    outputPackage: "recovery copy package",
    seasonalTheme: "post-incident recovery",
  },
  "retail-merch-quest": {
    creativeDirection: "collectible story quest",
    storyArc: "Quest invite -> display clue -> shop or story beat -> non-purchase option -> collectible close",
    sensoryLevel: "balanced",
    walkingPace: "moderate",
    outputPackage: "retail quest package",
    seasonalTheme: "retail merch quest",
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

const _parkedExperienceStudioReferenceBindings = [
  requiredFields,
  workflowStates,
  creativeDirections,
  storyArcs,
  sensoryLevels,
  walkingPaces,
  outputPackages,
  studioMemoryCollectionMeta,
  statusClass,
  workflowClass,
  issueLabel,
  compactList,
  formatTimestamp,
];

export function ExperienceStudio() {
  const [readiness, setReadiness] = useState<VenueDataPayload | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isDrafting, setIsDrafting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [lastGeneratedAt, setLastGeneratedAt] = useState<string | null>(null);
  const [generationCount, setGenerationCount] = useState(0);
  const draftResultRef = useRef<HTMLDivElement | null>(null);
  const [templateId, setTemplateId] = useState<ExperienceTemplateId>("festival-plan");
  const selectedTemplate = draftTemplates.find((item) => item.id === templateId) ?? draftTemplates[0];
  const [audience, setAudience] = useState(selectedTemplate.audience);
  const [tone, setTone] = useState(selectedTemplate.tone);
  const [constraints, setConstraints] = useState("Use verified venue facts only. Keep movement guidance optional and send operational impacts to Command Center review.");
  const defaultFestivalDefaults = creativeDefaultsByTemplate["festival-plan"];
  const [creativeDirection, setCreativeDirection] = useState(defaultFestivalDefaults.creativeDirection);
  const [storyArc, setStoryArc] = useState(defaultFestivalDefaults.storyArc);
  const [sensoryLevel, setSensoryLevel] = useState(defaultFestivalDefaults.sensoryLevel);
  const [walkingPace, setWalkingPace] = useState(defaultFestivalDefaults.walkingPace);
  const [outputPackage, setOutputPackage] = useState(defaultFestivalDefaults.outputPackage);
  const [seasonalTheme, setSeasonalTheme] = useState(defaultFestivalDefaults.seasonalTheme);
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
  const [designCommand, setDesignCommand] = useState("Make this shorter, more kid-friendly, and lower sensory while preserving the same verified stops.");
  const [isIteratingDesign, setIsIteratingDesign] = useState(false);
  const [latestDesignIteration, setLatestDesignIteration] = useState<DesignIterationPayload | null>(null);
  const [showAdvancedReview, setShowAdvancedReview] = useState(false);
  const [studioMemory, setStudioMemory] = useState<StudioMemoryPayload | null>(null);
  const [isLoadingMemory, setIsLoadingMemory] = useState(false);
  const [isInjectingSyntheticMemory, setIsInjectingSyntheticMemory] = useState(false);
  const [visualAssetResult, setVisualAssetResult] = useState<VisualAssetResult | null>(null);
  const [isGeneratingVisuals, setIsGeneratingVisuals] = useState(false);
  const [eventTeamPdfResult, setEventTeamPdfResult] = useState<EventTeamPdfResult | null>(null);
  const [isBuildingEventPdf, setIsBuildingEventPdf] = useState(false);
  const [conversationInput, setConversationInput] = useState(defaultCnyFestivalPrompt);
  const [conversationPlan, setConversationPlan] = useState<ConversationPlanPayload | null>(null);
  const [plannedConversationInput, setPlannedConversationInput] = useState("");
  const [isPlanningConversation, setIsPlanningConversation] = useState(false);
  const [isGeneratingFromPlan, setIsGeneratingFromPlan] = useState(false);
  const [plannerTurns, setPlannerTurns] = useState<PlannerTurn[]>([]);
  const [plannerReply, setPlannerReply] = useState("Success metric is repeat visits, cultural-care review readiness, and event-team execution clarity. Guest commitment is an optional festival path guests can sample once or revisit across the month. Reward and red-envelope-style mechanics are placeholders until owner approval. Review owners are brand, cultural review, CRM, signage, accessibility, and event programming.");

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

  const injectSyntheticMemory = async () => {
    setIsInjectingSyntheticMemory(true);
    setMessage(null);
    try {
      const response = await fetchParkPulseApi("/api/park/experience-studio/memory/synthetic-inject", {
        method: "POST",
        body: JSON.stringify({ actor: "experience_studio_demo", templateId: "festival-plan" }),
        timeoutMs: 8000,
      });
      const payload = await response.json() as { status?: string; memory?: StudioMemoryPayload; boundary?: string };
      if (payload.status !== "injected") throw new Error("Synthetic memory injection failed");
      setStudioMemory(payload.memory ?? null);
      setMessage("Synthetic demo memory injected and labeled");
    } catch {
      setMessage("Synthetic memory injection unavailable");
    } finally {
      setIsInjectingSyntheticMemory(false);
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

  const applyRecommendedPlan = (plan: ConversationPlanPayload | null = conversationPlan, options: { silent?: boolean } = {}) => {
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
    if (!options.silent) setMessage("Recommended plan applied to the generator inputs");
    return true;
  };

  const plannerContextFromPlan = (plan: ConversationPlanPayload | null, designerRequest: string) => {
    if (!plan?.recommendedPlan?.payload) return undefined;
    return {
      source: "conversation_plan",
      designerRequest,
      generatedAt: new Date().toISOString(),
      recommendedPlanLabel: plan.recommendedPlan.label,
      recommendedPlanWhy: plan.recommendedPlan.why,
      recommendedPayload: plan.recommendedPlan.payload,
      parsedBrief: plan.parsedBrief,
      plannerIntelligence: plan.plannerIntelligence,
      planningTools: plan.planningTools,
      reasonedPlan: plan.reasonedPlan,
      llmReasoning: plan.llmReasoning,
      retrievalEvidence: plan.retrievalEvidence,
      agentWorkflow: plan.agentWorkflow,
      productReadiness: plan.productReadiness,
      toolRouter: plan.toolRouter,
      strategyOrchestration: plan.strategyOrchestration,
      planStatus: plan.status,
    };
  };

  const generateDraft = async (overridePayload?: Partial<Record<string, unknown>>, sourcePlan?: ConversationPlanPayload | null) => {
    setIsDrafting(true);
    setMessage(null);
    const plannerContext = plannerContextFromPlan(sourcePlan ?? null, plannedConversationInput || conversationInput.trim());
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
        headers: { "Content-Type": "application/json", "x-parkpulse-role": "ops_team" },
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
          ...(plannerContext ? { plannerContext } : {}),
          useLlm: useCreativeReasoning,
          useCreativeReasoning,
          useRealParkContext: false,
          useVenueExperienceData: true,
        }),
        timeoutMs: longRunningRequestTimeoutMs,
      });
      const payload = await response.json() as DraftPayload;
      setDraftPayload(payload);
      setVisualAssetResult(null);
      setEventTeamPdfResult(null);
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

  const runConversationPlanner = async (nextTurns: PlannerTurn[]): Promise<ConversationPlanPayload | null> => {
    setIsPlanningConversation(true);
    setMessage(null);
    const primaryMessage = nextTurns.find((turn) => turn.role === "designer")?.content.trim() || conversationInput.trim();
    try {
      const response = await fetchParkPulseApi("/api/park/experience-studio/conversation-plan", {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-parkpulse-role": "ops_team" },
        body: JSON.stringify({
          message: primaryMessage,
          audience,
          tone,
          constraints,
          history: nextTurns.map((turn) => ({ role: turn.role, content: turn.content })),
          useVenueExperienceData: true,
          useLlmPlanner: useCreativeReasoning,
          useCreativeReasoning,
        }),
        timeoutMs: longRunningRequestTimeoutMs,
      });
      const payload = await response.json() as ConversationPlanPayload;
      setConversationPlan(payload);
      setPlannedConversationInput(primaryMessage);
      applyRecommendedPlan(payload, { silent: true });
      setPlannerTurns([...nextTurns, { role: "studio", content: studioTurnFromPlan(payload), at: new Date().toISOString() }]);
      if (payload.venueExperienceData) setReadiness(payload.venueExperienceData);
      setMessage(payload.missingInputs?.length ? "Plan shaped with profile questions to resolve" : "Plan shaped and ready to generate");
      void refreshStudioMemory();
      return payload;
    } catch {
      setMessage("Conversation planning failed");
      return null;
    } finally {
      setIsPlanningConversation(false);
    }
  };

  const shapeConversationPlan = async () => {
    const request = conversationInput.trim();
    if (!request) {
      setMessage("Add a designer request before generating a plan");
      return;
    }
    const firstTurn: PlannerTurn = { role: "designer", content: request, at: new Date().toISOString() };
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
    if (plannedConversationInput && plannedConversationInput !== conversationInput.trim()) {
      setMessage("The designer request changed after the plan was generated. Regenerate the plan before creating the package.");
      return;
    }
    setIsGeneratingFromPlan(true);
    applyRecommendedPlan(conversationPlan, { silent: true });
    try {
      await generateDraft(payload, conversationPlan);
    } finally {
      setIsGeneratingFromPlan(false);
    }
  };

  const generatePlanAndPackage = async () => {
    const request = conversationInput.trim();
    if (!request) {
      setMessage("Add a designer request before generating");
      return;
    }
    const firstTurn: PlannerTurn = { role: "designer", content: request, at: new Date().toISOString() };
    const plan = await runConversationPlanner([firstTurn]);
    const payload = plan?.recommendedPlan?.payload;
    if (!payload) return;
    setIsGeneratingFromPlan(true);
    try {
      await generateDraft(payload, plan);
    } finally {
      setIsGeneratingFromPlan(false);
    }
  };

  const generateVisualAssets = async () => {
    if (!draft || !creativePackage) {
      setMessage("Generate a package before creating visuals");
      return;
    }
    setIsGeneratingVisuals(true);
    setMessage(null);
    try {
      const response = await fetchParkPulseApi("/api/park/experience-studio/visual-assets", {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-parkpulse-role": "ops_team" },
        body: JSON.stringify({
          draft,
          creativePackage,
          promptIds: ["poster_hero", "app_tile", "signage_mockup", "social_story"],
          generateImages: true,
          persistImages: true,
        }),
        timeoutMs: longRunningRequestTimeoutMs,
      });
      const payload = await response.json() as VisualAssetResult;
      setVisualAssetResult(payload);
      setMessage(payload.imageCount ? `Generated ${payload.imageCount} visual draft${payload.imageCount === 1 ? "" : "s"}` : "Vertex image prompts ready; provider is not configured for live image generation");
    } catch {
      setMessage("Visual generation failed");
    } finally {
      setIsGeneratingVisuals(false);
    }
  };

  const downloadEventTeamPdf = (result: EventTeamPdfResult | null = eventTeamPdfResult) => {
    if (!result?.pdfDataUrl) {
      setMessage("Build the PDF before downloading");
      return false;
    }
    const downloaded = downloadDataUrl(result.pdfDataUrl, result.fileName ?? "event-team-marketing-package.pdf");
    setMessage(downloaded ? `Downloaded ${result.fileName ?? "event-team-marketing-package.pdf"}` : "PDF download is unavailable for this file");
    return downloaded;
  };

  const copyEventTeamPdfPath = async () => {
    if (!eventTeamPdfResult?.pdfPath) {
      setMessage("Build the PDF before copying the file path");
      return;
    }
    try {
      await navigator.clipboard.writeText(eventTeamPdfResult.pdfPath);
      setMessage("Copied PDF file path");
    } catch {
      setMessage(eventTeamPdfResult.pdfPath);
    }
  };

  const buildEventTeamPdf = async (downloadAfterBuild = false) => {
    if (!draft || !creativePackage?.eventTeamMarketingPackage) {
      setMessage("Generate an event-team package before building the PDF");
      return null;
    }
    setIsBuildingEventPdf(true);
    setMessage(null);
    try {
      const response = await fetchParkPulseApi("/api/park/experience-studio/event-team-pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-parkpulse-role": "ops_team" },
        body: JSON.stringify({
          draft,
          creativePackage,
        }),
        timeoutMs: longRunningRequestTimeoutMs,
      });
      const payload = await response.json() as EventTeamPdfResult;
      setEventTeamPdfResult(payload);
      if (payload.status !== "generated") {
        setMessage(payload.message ?? `PDF generation did not complete (${payload.status ?? "unknown"})`);
        return payload;
      }
      if (downloadAfterBuild) {
        try {
          downloadEventTeamPdf(payload);
        } catch (error) {
          setMessage(error instanceof Error ? `PDF built, but browser download failed: ${error.message}` : "PDF built, but browser download failed");
        }
      } else {
        setMessage(`Built event-team PDF${payload.pageCount ? ` (${payload.pageCount} pages)` : ""}`);
      }
      return payload;
    } catch (error) {
      setMessage(error instanceof Error ? `Event-team PDF generation failed: ${error.message}` : "Event-team PDF generation failed");
      return null;
    } finally {
      setIsBuildingEventPdf(false);
    }
  };

  const saveDraftRecord = async (): Promise<SavedDraft> => {
    if (!draft) {
      throw new Error("Generate a draft before saving");
    }
    const response = await fetchParkPulseApi("/api/park/experience-studio/drafts", {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-parkpulse-role": "ops_team" },
      body: JSON.stringify({
        templateId: conversationPlan?.parsedBrief?.templateId ?? templateId,
        draft,
        sourceMode: draftPayload?.mode ?? "experience_studio_gated_draft",
        actor: "experience_designer",
        brief: { audience, tone, constraints, creativeDirection, storyArc, sensoryLevel, walkingPace, outputPackage, seasonalTheme, venueReadiness: readiness?.readiness },
      }),
      timeoutMs: 6000,
    });
    const payload = await response.json() as { draftRecord?: SavedDraft; summary?: SavedDraft; message?: string };
    const saved = (payload.draftRecord ?? payload.summary) as SavedDraft | undefined;
    if (!saved?.id) throw new Error(payload.message ?? "Save response missing draft id.");
    setActiveDraftId(saved.id);
    setWorkflowStatus(saved.status ?? "draft");
    setSavedDrafts((current) => [saved, ...current.filter((item) => item.id !== saved.id)]);
    return saved;
  };

  const saveDraft = async () => {
    setIsSavingDraft(true);
    setMessage(null);
    try {
      await saveDraftRecord();
      setMessage("Draft saved");
      void refreshStudioMemory();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Draft save failed");
    } finally {
      setIsSavingDraft(false);
    }
  };

  const approveCurrentPackageForMemory = async () => {
    if (!draft) {
      setMessage("Generate a package before approving memory");
      return;
    }
    setIsWorkflowBusy(true);
    setMessage(null);
    try {
      const saved = await saveDraftRecord();
      const response = await fetchParkPulseApi(`/api/park/experience-studio/drafts/${encodeURIComponent(saved.id)}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-parkpulse-role": "ops_team" },
        body: JSON.stringify({
          status: "approved",
          note: "Approved by demo reviewer for bounded finished-work memory retrieval.",
          actor: "experience_reviewer",
        }),
        timeoutMs: 7000,
      });
      const payload = await response.json() as { summary?: SavedDraft; draftRecord?: SavedDraft; status?: string; message?: string };
      if (payload.status && payload.status !== "updated") throw new Error(payload.message ?? "Approval failed.");
      const updated = payload.summary ?? payload.draftRecord ?? { ...saved, status: "approved" as DraftStatus };
      setWorkflowStatus("approved");
      setActiveDraftId(saved.id);
      setSavedDrafts((current) => current.map((item) => item.id === saved.id ? { ...item, ...updated, status: "approved" } : item));
      setMessage("Approved for future Studio memory");
      void refreshStudioMemory();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Memory approval failed");
    } finally {
      setIsWorkflowBusy(false);
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
        headers: { "Content-Type": "application/json", "x-parkpulse-role": "ops_team" },
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
        headers: { "Content-Type": "application/json", "x-parkpulse-role": "ops_team" },
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
        headers: { "Content-Type": "application/json", "x-parkpulse-role": "ops_team" },
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
        headers: { "Content-Type": "application/json", "x-parkpulse-role": "ops_team" },
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
        headers: { "Content-Type": "application/json", "x-parkpulse-role": "ops_team" },
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

  const runDesignIteration = async () => {
    if (!draft) {
      setMessage("Generate an experience before iterating on it");
      return;
    }
    const command = designCommand.trim();
    if (!command) {
      setMessage("Add a design direction before iterating");
      return;
    }
    setIsIteratingDesign(true);
    setMessage(null);
    try {
      const response = await fetchParkPulseApi("/api/park/experience-studio/design-iteration", {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-parkpulse-role": "ops_team" },
        body: JSON.stringify({
          draft,
          command,
          actor: "experience_designer",
        }),
        timeoutMs: 12000,
      });
      const payload = await response.json() as DesignIterationPayload;
      if (payload.status !== "revised" || !payload.draft) throw new Error("Design iteration failed");
      setDraftPayload((current) => ({ ...(current ?? { status: "ready", mode: "design_iteration" }), status: "ready", mode: "design_iteration", draft: payload.draft }));
      setLatestDesignIteration(payload);
      setLatestSectionRevision(null);
      setVisualAssetResult(null);
      setEventTeamPdfResult(null);
      const sections = payload.sections?.length ? payload.sections.map(formatStatus).join(", ") : "experience";
      setMessage(`Iterated ${sections}`);
      void refreshStudioMemory();
      window.setTimeout(() => draftResultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Design iteration failed");
    } finally {
      setIsIteratingDesign(false);
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
  const normalizedConversationInput = conversationInput.trim();
  const planIsCurrent = Boolean(conversationPlan && plannedConversationInput && plannedConversationInput === normalizedConversationInput);
  const planStateLabel = !conversationPlan ? "no plan yet" : planIsCurrent ? "plan bound to request" : "request changed";
  const plannerReasoning = creativePackage?.plannerReasonedPlan ?? conversationPlan?.reasonedPlan ?? null;
  const plannerStrategy = plannerReasoning?.strategy ?? {};
  const plannerPhases = plannerReasoning?.programPhases ?? conversationPlan?.reasonedPlan?.programPhases ?? [];
  const plannerToolCount = conversationPlan?.planningTools?.length ?? plannerReasoning?.selectedToolIds?.length ?? 0;
  const retrievalEvidence = creativePackage?.retrievalEvidence ?? plannerReasoning?.retrievalEvidence ?? conversationPlan?.retrievalEvidence;
  const retrievedItems = retrievalEvidence?.retrievedEvidence ?? [];
  const retrievalSummary = retrievalEvidence?.evidenceSummary;
  const memoryGate = retrievalEvidence?.memoryGate;
  const agentWorkflow = creativePackage?.agentWorkflow ?? plannerReasoning?.agentWorkflow ?? conversationPlan?.agentWorkflow;
  const agentStages = agentWorkflow?.stages ?? [];
  const productReadiness = creativePackage?.productReadiness ?? plannerReasoning?.productReadiness ?? conversationPlan?.productReadiness;
  const designIterationStrategy = latestDesignIteration?.designIterationStrategy ?? creativePackage?.designIterationStrategy;
  const designIterationTags = latestDesignIteration?.iterationSummary?.strategyTags ?? designIterationStrategy?.intentTags ?? [];
  const designIterationArc = latestDesignIteration?.iterationSummary?.routeArc ?? designIterationStrategy?.routeArc ?? [];
  const designIterationLockedStops = latestDesignIteration?.iterationSummary?.lockedRouteStops ?? designIterationStrategy?.lockedFacts?.routeStops ?? [];
  const packageName = creativePackage?.executiveConcept?.name ?? draft?.title ?? "No package generated";
  const packageOneLine = creativePackage?.executiveConcept?.oneLine ?? draft?.intent ?? "Enter a creative request and generate a plan.";
  const packagePromise = creativePackage?.executiveConcept?.guestPromise ?? "The final package will appear here with route, channel copy, and review gates.";
  const eventTeamPackage = creativePackage?.eventTeamMarketingPackage;
  const eventBrief = eventTeamPackage?.eventBrief;
  const eventWorkstreams = eventTeamPackage?.workstreams ?? [];
  const eventDeliverables = eventTeamPackage?.deliverables ?? [];
  const eventDecisionLog = eventTeamPackage?.teamDecisionLog ?? [];
  const eventProgramPhases = eventTeamPackage?.programPhases ?? [];
  const eventExecutionBoundaries = eventTeamPackage?.executionBoundary ?? [];
  const eventReasoningBrief = eventTeamPackage?.reasoningBrief;
  const eventReasoningEvidence = eventReasoningBrief?.decisiveEvidence ?? [];
  const eventReasoningRevisions = eventReasoningBrief?.revisionsApplied ?? [];
  const eventReasoningTradeoffs = eventReasoningBrief?.riskTradeoffs ?? [];
  const eventSelectedStrategy = eventReasoningBrief?.selectedStrategy;
  const eventCandidateScores = eventReasoningBrief?.candidateScores ?? [];
  const eventSelectedConcept = eventReasoningBrief?.selectedConcept;
  const conceptCandidateScores = eventReasoningBrief?.conceptCandidateScores ?? [];
  const conceptRevisions = eventReasoningBrief?.conceptCritique?.revisionsApplied ?? [];
  const selectedToolCount = eventReasoningBrief?.toolRouter?.selectedToolIds?.length ?? eventReasoningBrief?.selectedToolIds?.length ?? 0;
  const routeStops = (eventBrief?.route?.length ? eventBrief.route : (draft?.route ?? []).map((stop) => stop.stop)).filter(Boolean).slice(0, 6);
  const eventBriefOutline = [
    eventReasoningBrief ? "reasoning receipts" : null,
    eventSelectedStrategy?.label ? `${eventSelectedStrategy.label} selected` : null,
    eventSelectedConcept?.name ? `${eventSelectedConcept.name} concept` : null,
    eventProgramPhases.length ? `${eventProgramPhases.length} program phases` : null,
    eventWorkstreams.length ? `${eventWorkstreams.length} team workstreams` : null,
    eventDeliverables.length ? `${eventDeliverables.length} draft assets` : null,
    eventDecisionLog.length ? `${eventDecisionLog.length} owner decisions` : null,
  ].filter(Boolean) as string[];
  const channelNames = (creativePackage?.channelMatrix ?? draft?.messages ?? []).map((item) => ("channel" in item ? item.channel : "")).filter(Boolean).slice(0, 4);
  const primaryEmail = creativePackage?.preArrivalEmail;
  const primaryStaffLine = creativePackage?.staffScript?.openingLine ?? creativePackage?.staffScript?.transitionLine;
  const primarySignage = creativePackage?.signageSet?.[0];
  const eventCopyPreview = [
    primaryEmail?.subject ? `Email: ${primaryEmail.subject}` : null,
    primaryStaffLine ? `Staff: ${primaryStaffLine}` : null,
    primarySignage?.headline ? `Signage: ${primarySignage.headline}` : null,
  ].filter(Boolean) as string[];
  const visualAssetStudio = visualAssetResult?.visualAssetStudio ?? creativePackage?.visualAssetStudio;
  const posterPrompt = visualAssetResult?.selectedPrompts?.[0] ?? visualAssetStudio?.prompts?.find((prompt) => prompt.id === visualAssetStudio?.posterCreation?.recommendedPrimaryPromptId) ?? visualAssetStudio?.prompts?.[0];
  const generatedVisualImages = (visualAssetResult?.results ?? []).flatMap((result) => result.images ?? []).filter((image) => Boolean(image.dataUrl));
  const qaScore = creativePackage?.studioQualityEval?.demoScore ?? creativePackage?.studioQualityEval?.score;
  const productScore = productReadiness?.score ?? creativePackage?.productionDetail?.plannerEvidence?.productReadinessScore;
  const venueName = readiness?.venueIdentity?.name ?? "Active Venue Profile";
  const evidenceChips = [
    conversationPlan?.parsedBrief?.templateId ? `Template: ${formatStatus(conversationPlan.parsedBrief.templateId)}` : null,
    conversationPlan?.llmReasoning?.status ? `Planner: ${formatStatus(conversationPlan.llmReasoning.status)}` : null,
    retrievedItems.length ? `Evidence ${retrievedItems.length}` : null,
    agentStages.length ? `Agent ${formatStatus(agentWorkflow?.status ?? "ready")}` : null,
    productScore ? `Readiness ${productScore}` : qaScore ? `QA ${qaScore}` : null,
    readiness?.readiness?.autofillAllowed ? "Venue facts on" : "Venue review needed",
  ].filter(Boolean) as string[];

  const _parkedExperienceStudioWorkflowBindings = [
    isLoading,
    lastGeneratedAt,
    generationCount,
    setUseCreativeReasoning,
    savedDrafts,
    setReviewNote,
    latestHandoff,
    isUpdatingDraft,
    isSendingHandoff,
    isPromotingRule,
    isRevisingSection,
    setRevisionSection,
    setRevisionFeedback,
    latestSectionRevision,
    isLoadingMemory,
    selectDraftTemplate,
    sendPlannerReply,
    generateFromConversationPlan,
    updateRouteStop,
    updateMessage,
    updateProductionNote,
    addProductionNote,
    removeProductionNote,
    updateSavedDraftContent,
    openSavedDraft,
    updateWorkflowStatus,
    sendHandoff,
    promoteLearningRule,
    runSectionRevision,
    readinessStatus,
    venueIdentity,
    readinessCounts,
    profileSourceMode,
    profileGroups,
    channelOwnerEntries,
    safetyInstructions,
    issues,
    draftMissing,
    hasAdvancedReview,
    experienceReasoning,
    creativeSynthesis,
    coverageEntries,
    profileQualityGaps,
    studioPolicy,
    brandTone,
    bannedClaims,
    studioReview,
    studioCore,
    studioMemoryCounts,
    retentionEntries,
    latestStudioMemoryReceipt,
    recommendedPlanTemplate,
    plannerToolCount,
    eventExecutionBoundaries,
  ];

  return (
    <main className="min-h-screen bg-[#f5f7f3] px-4 py-5 font-sans text-slate-950 lg:px-8">
      <div className="mx-auto max-w-6xl space-y-4">
        <header className="flex flex-col gap-3 border-b border-slate-300 pb-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="text-[11px] font-black uppercase tracking-widest text-emerald-700">Experience Studio</div>
            <h1 className="mt-1 text-3xl font-black tracking-normal text-slate-950 lg:text-5xl">Plan guest experiences from one prompt</h1>
          </div>
          <nav className="flex flex-wrap gap-2">
            <a href="/ops" className="rounded border border-slate-300 bg-white px-3 py-2 text-xs font-black text-slate-700">Command Center</a>
            <a href="/venue-profile" className="rounded border border-slate-300 bg-white px-3 py-2 text-xs font-black text-slate-700">Venue Profile</a>
          </nav>
        </header>

        <section className="grid gap-4 lg:grid-cols-[minmax(0,1.1fr)_22rem]">
          <div className="rounded-lg border border-slate-300 bg-white p-4 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="text-[11px] font-black uppercase tracking-widest text-slate-500">Creative request</div>
                <h2 className="mt-1 text-xl font-black text-slate-950">Describe the experience</h2>
              </div>
              <div className={`rounded border px-2 py-1 text-[10px] font-black uppercase tracking-widest ${planIsCurrent ? "border-emerald-300 bg-emerald-50 text-emerald-800" : "border-slate-300 bg-slate-50 text-slate-600"}`}>
                {planStateLabel}
              </div>
            </div>
            <textarea
              aria-label="Designer request"
              value={conversationInput}
              onChange={(event) => setConversationInput(event.target.value)}
              className="mt-4 h-32 w-full resize-none rounded border border-slate-300 bg-slate-50 p-4 text-base leading-relaxed text-slate-950 outline-none transition focus:border-emerald-500 focus:bg-white"
            />
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => void generatePlanAndPackage()}
                disabled={isPlanningConversation || isGeneratingFromPlan || isDrafting || !normalizedConversationInput}
                className="rounded bg-emerald-500 px-5 py-3 text-sm font-black text-slate-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-500"
              >
                {isPlanningConversation ? "Planning..." : isGeneratingFromPlan || isDrafting ? "Generating..." : "Generate plan"}
              </button>
              <button
                type="button"
                onClick={() => void shapeConversationPlan()}
                disabled={isPlanningConversation || !normalizedConversationInput}
                className="rounded border border-slate-300 bg-white px-4 py-3 text-sm font-black text-slate-700 transition hover:border-emerald-500 disabled:opacity-50"
              >
                Plan only
              </button>
              {message ? <span className="text-sm font-bold text-slate-500">{message}</span> : null}
            </div>
          </div>

          <aside className="rounded-lg border border-slate-300 bg-slate-950 p-4 text-white shadow-sm">
            <div className="text-[11px] font-black uppercase tracking-widest text-emerald-300">Grounding</div>
            <div className="mt-2 text-lg font-black">{venueName}</div>
            <div className="mt-3 grid grid-cols-2 gap-2">
              {[
                ["Template", conversationPlan?.parsedBrief?.templateId ? formatStatus(conversationPlan.parsedBrief.templateId) : "waiting"],
                ["LLM", formatStatus(conversationPlan?.llmReasoning?.status ?? "not run")],
                ["Evidence", retrievedItems.length ? String(retrievedItems.length) : "0"],
                ["Memory", formatStatus(memoryGate?.status ?? "gated")],
              ].map(([label, value]) => (
                <div key={label} className="rounded border border-white/10 bg-white/5 p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">{label}</div>
                  <div className="mt-1 text-sm font-black text-white">{value}</div>
                </div>
              ))}
            </div>
          </aside>
        </section>

        <section className="grid gap-4 lg:grid-cols-[22rem_minmax(0,1fr)]">
          <aside className="rounded-lg border border-slate-300 bg-white p-4 shadow-sm">
            <div className="flex items-center justify-between gap-2">
              <div>
                <div className="text-[11px] font-black uppercase tracking-widest text-emerald-700">Plan</div>
                <h2 className="mt-1 text-lg font-black text-slate-950">{conversationPlan?.recommendedPlan?.label ?? "No plan yet"}</h2>
              </div>
              {conversationPlan ? <span className="rounded bg-emerald-100 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-emerald-800">ready</span> : null}
            </div>
            <p className="mt-3 text-sm leading-relaxed text-slate-600">
              {plannerStrategy.objective ?? conversationPlan?.recommendedPlan?.why ?? "The planner will pick the right experience type and bind the generator payload."}
            </p>
            <div className="mt-4 space-y-2">
              {(plannerPhases.length ? plannerPhases.slice(0, 3) : [
                { name: "Interpret", guestJob: "Pick the right template and evidence." },
                { name: "Compose", guestJob: "Build the route and channel package." },
                { name: "Review", guestJob: "Show gates before handoff." },
              ]).map((phase, index) => (
                <div key={`${phase.name ?? "phase"}-${index}`} className="rounded border border-slate-200 bg-slate-50 p-3">
                  <div className="text-sm font-black text-slate-950">{phase.name ?? `Step ${index + 1}`}</div>
                  <div className="mt-1 text-xs leading-relaxed text-slate-600">{phase.guestJob ?? phase.heroMoment ?? "Reviewable planning step."}</div>
                </div>
              ))}
            </div>
          </aside>

          <div ref={draftResultRef} className="rounded-lg border border-slate-300 bg-white p-4 shadow-sm">
            <div className="flex flex-col gap-3 border-b border-slate-200 pb-4 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <div className="text-[11px] font-black uppercase tracking-widest text-emerald-700">Generated package</div>
                <h2 className="mt-1 text-2xl font-black text-slate-950">{packageName}</h2>
                <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-600">{packageOneLine}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => void buildEventTeamPdf(true)}
                  disabled={isBuildingEventPdf || !creativePackage?.eventTeamMarketingPackage}
                  className="rounded border border-slate-900 bg-slate-950 px-3 py-2 text-xs font-black uppercase tracking-widest text-white disabled:cursor-not-allowed disabled:border-slate-300 disabled:bg-slate-200 disabled:text-slate-500"
                >
                  {isBuildingEventPdf ? "Building PDF" : creativePackage?.eventTeamMarketingPackage ? "Download package" : "Generate first"}
                </button>
                {evidenceChips.map((chip) => (
                  <span key={chip} className="rounded bg-slate-100 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-700">{chip}</span>
                ))}
              </div>
            </div>

            <div className="mt-4 grid gap-3 lg:grid-cols-3">
              <div className="rounded border border-slate-200 bg-slate-50 p-3 lg:col-span-2">
                <div className="text-[11px] font-black uppercase tracking-widest text-slate-500">Guest promise</div>
                <div className="mt-2 text-sm leading-relaxed text-slate-800">{packagePromise}</div>
              </div>
              <div className="rounded border border-slate-200 bg-slate-50 p-3">
                <div className="text-[11px] font-black uppercase tracking-widest text-slate-500">Route</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {routeStops.length ? routeStops.map((stop) => (
                    <span key={stop} className="rounded bg-white px-2 py-1 text-xs font-bold text-slate-700">{stop}</span>
                  )) : <span className="text-sm text-slate-500">Route appears after generation.</span>}
                </div>
              </div>
            </div>

            <div className="mt-4 border-t border-slate-200 pt-4">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="text-[11px] font-black uppercase tracking-widest text-emerald-700">Iterate</div>
                  <textarea
                    aria-label="Design iteration command"
                    value={designCommand}
                    onChange={(event) => setDesignCommand(event.target.value)}
                    className="mt-2 h-20 w-full resize-none rounded border border-slate-300 bg-slate-50 p-3 text-sm leading-relaxed text-slate-900 outline-none transition focus:border-emerald-500 focus:bg-white"
                  />
                  {latestDesignIteration ? (
                    <div className="mt-2 rounded border border-emerald-200 bg-emerald-50 p-3 text-xs leading-relaxed text-slate-700">
                      <div className="font-black text-emerald-900">
                        Last iteration: {(latestDesignIteration.sections ?? []).map(formatStatus).join(", ") || "experience"} / {latestDesignIteration.iterationSummary?.appliedCount ?? 0} update{latestDesignIteration.iterationSummary?.appliedCount === 1 ? "" : "s"}
                      </div>
                      <div className="mt-1 font-bold">
                        Strategy: {designIterationTags.length ? designIterationTags.map(formatStatus).join(", ") : "experience design"}{designIterationArc.length ? ` / ${designIterationArc.slice(0, 5).join(" -> ")}` : ""}
                      </div>
                      <div className="mt-1 text-slate-500">
                        Locked stops: {designIterationLockedStops.length ? designIterationLockedStops.slice(0, 5).join(" -> ") : "verified route preserved"}
                      </div>
                    </div>
                  ) : null}
                </div>
                <button
                  type="button"
                  onClick={() => void runDesignIteration()}
                  disabled={isIteratingDesign || !draft || !designCommand.trim()}
                  className="rounded border border-slate-900 bg-slate-950 px-4 py-3 text-xs font-black uppercase tracking-widest text-white disabled:cursor-not-allowed disabled:border-slate-300 disabled:bg-slate-200 disabled:text-slate-500"
                >
                  {isIteratingDesign ? "Iterating" : "Apply revision"}
                </button>
              </div>
            </div>

            <div className="mt-4 border-t border-emerald-200 pt-4">
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div className="max-w-3xl">
                  <div className="text-[11px] font-black uppercase tracking-widest text-emerald-700">Event brief PDF</div>
                  <h3 className="mt-1 text-xl font-black text-slate-950">{eventBrief?.eventName ?? packageName}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-slate-600">
                    {eventBrief?.format ?? "Narrative event-team brief"}{eventBrief?.runShape ? ` / ${eventBrief.runShape}` : ""}. The export is a review draft for the event team, not a public launch approval.
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => void buildEventTeamPdf()}
                    disabled={isBuildingEventPdf || !creativePackage?.eventTeamMarketingPackage}
                    className="rounded border border-emerald-700 bg-emerald-700 px-3 py-2 text-xs font-black uppercase tracking-widest text-white disabled:cursor-not-allowed disabled:border-slate-300 disabled:bg-slate-200 disabled:text-slate-500"
                  >
                    {isBuildingEventPdf ? "Building" : "Build brief PDF"}
                  </button>
                  {eventTeamPdfResult?.pdfDataUrl ? (
                    <>
                      <a
                        href={eventTeamPdfResult.pdfDataUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="rounded border border-slate-300 bg-white px-3 py-2 text-xs font-black uppercase tracking-widest text-slate-700"
                      >
                        Preview
                      </a>
                      <button
                        type="button"
                        onClick={() => downloadEventTeamPdf()}
                        className="rounded border border-slate-300 bg-white px-3 py-2 text-xs font-black uppercase tracking-widest text-slate-700"
                      >
                        Download
                      </button>
                      {eventTeamPdfResult.pdfPath ? (
                        <button
                          type="button"
                          onClick={() => void copyEventTeamPdfPath()}
                          className="rounded border border-slate-300 bg-white px-3 py-2 text-xs font-black uppercase tracking-widest text-slate-700"
                        >
                          Copy path
                        </button>
                      ) : null}
                    </>
                  ) : null}
                </div>
              </div>

              <div className="mt-4 space-y-3">
                <div>
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Brief includes</div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {(eventBriefOutline.length ? eventBriefOutline : ["summary", "route", "copy", "owner review"]).map((item) => (
                      <span key={item} className="rounded bg-slate-100 px-2 py-1 text-xs font-bold text-slate-700">{item}</span>
                    ))}
                  </div>
                </div>

                {eventReasoningBrief ? (
                  <div className="border-t border-slate-200 pt-3">
                    <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Why this plan</div>
                    {eventSelectedStrategy?.label ? (
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <span className="rounded bg-emerald-100 px-2 py-1 text-xs font-black text-emerald-800">
                          {eventSelectedStrategy.label}{typeof eventSelectedStrategy.score === "number" ? ` / ${eventSelectedStrategy.score}` : ""}
                        </span>
                        {selectedToolCount ? <span className="rounded bg-slate-100 px-2 py-1 text-xs font-bold text-slate-600">{selectedToolCount} tools routed</span> : null}
                        {eventCandidateScores.slice(0, 2).map((item) => (
                          <span key={item.id ?? item.label} className="rounded bg-slate-100 px-2 py-1 text-xs font-bold text-slate-600">
                            {item.label ?? item.id}: {item.score ?? "scored"}
                          </span>
                        ))}
                      </div>
                    ) : null}
                    <p className="mt-2 max-w-4xl text-sm leading-relaxed text-slate-700">
                      {eventSelectedStrategy?.rationale ?? eventReasoningBrief.selectedRouteReason ?? eventReasoningBrief.objective ?? "The package was selected from planner reasoning, venue facts, and review constraints."}
                    </p>
                    {eventSelectedConcept?.name ? (
                      <div className="mt-3">
                        <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">Selected concept</div>
                        <p className="mt-1 text-sm font-black text-slate-900">{eventSelectedConcept.name}</p>
                        <p className="mt-1 max-w-4xl text-xs leading-relaxed text-slate-600">{eventSelectedConcept.positioning ?? eventSelectedConcept.guestPromise}</p>
                        <div className="mt-2 flex flex-wrap gap-2">
                          {conceptCandidateScores.slice(0, 3).map((item) => (
                            <span key={item.id ?? item.name} className="rounded bg-slate-100 px-2 py-1 text-xs font-bold text-slate-600">
                              {item.name ?? item.id}: {item.score ?? "reviewed"}
                            </span>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    <div className="mt-2 grid gap-3 lg:grid-cols-3">
                      <div>
                        <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">Evidence</div>
                        <div className="mt-1 space-y-1">
                          {(eventReasoningEvidence.length ? eventReasoningEvidence.slice(0, 2) : ["Evidence appears after the planner runs."]).map((item) => (
                            <p key={item} className="text-xs leading-relaxed text-slate-600">{item}</p>
                          ))}
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">Revision</div>
                        <div className="mt-1 space-y-1">
                          {([...(conceptRevisions.slice(0, 1)), ...(eventReasoningRevisions.slice(0, 1))].length ? [...(conceptRevisions.slice(0, 1)), ...(eventReasoningRevisions.slice(0, 1))] : ["Review-driven revision appears after generation."]).map((item) => (
                            <p key={item} className="text-xs leading-relaxed text-slate-600">{item}</p>
                          ))}
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">Tradeoff</div>
                        <div className="mt-1 space-y-1">
                          {(eventReasoningTradeoffs.length ? eventReasoningTradeoffs.slice(0, 2) : ["Tradeoffs appear after generation."]).map((item) => (
                            <p key={item} className="text-xs leading-relaxed text-slate-600">{item}</p>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>
                ) : null}

                <div className="grid gap-4 lg:grid-cols-2">
                  <div>
                    <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Route</div>
                    <p className="mt-2 text-sm leading-relaxed text-slate-700">
                      {routeStops.length ? routeStops.join(" > ") : "Route appears after generation."}
                    </p>
                  </div>
                  <div>
                    <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Copy preview</div>
                    <div className="mt-2 space-y-1">
                      {(eventCopyPreview.length ? eventCopyPreview : ["Email, staff, and signage copy appear after generation."]).map((item) => (
                        <p key={item} className="text-sm leading-relaxed text-slate-700">{item}</p>
                      ))}
                    </div>
                  </div>
                </div>

                {eventTeamPdfResult?.pdfPath ? (
                  <div className="truncate border-t border-slate-200 pt-3 text-[11px] font-bold text-slate-500">
                    {eventTeamPdfResult.pageCount ?? "PDF"} pages / {eventTeamPdfResult.pdfPath}
                  </div>
                ) : null}
              </div>
            </div>

            <div className="mt-4 grid gap-3 md:grid-cols-2">
              <div className="rounded border border-slate-200 p-3">
                <div className="text-[11px] font-black uppercase tracking-widest text-slate-500">Pre-arrival email</div>
                <div className="mt-2 text-sm font-black text-slate-950">{primaryEmail?.subject ?? "Generated email subject"}</div>
                <div className="mt-1 text-xs leading-relaxed text-slate-600">{primaryEmail?.previewText ?? "Email copy appears after generation."}</div>
              </div>
              <div className="rounded border border-slate-200 p-3">
                <div className="text-[11px] font-black uppercase tracking-widest text-slate-500">Signage</div>
                <div className="mt-2 text-sm font-black text-slate-950">{primarySignage?.headline ?? "Generated sign headline"}</div>
                <div className="mt-1 text-xs leading-relaxed text-slate-600">{primarySignage?.body ?? "Sign copy appears after generation."}</div>
              </div>
              <div className="rounded border border-slate-200 p-3">
                <div className="text-[11px] font-black uppercase tracking-widest text-slate-500">Staff cue</div>
                <div className="mt-2 text-sm leading-relaxed text-slate-700">{primaryStaffLine ?? "Staff cue appears after generation."}</div>
              </div>
              <div className="rounded border border-slate-200 p-3">
                <div className="text-[11px] font-black uppercase tracking-widest text-slate-500">Channels</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {channelNames.length ? channelNames.map((channel) => (
                    <span key={channel} className="rounded bg-slate-100 px-2 py-1 text-xs font-bold text-slate-700">{formatStatus(channel)}</span>
                  )) : <span className="text-sm text-slate-500">App, signage, email, staff.</span>}
                </div>
              </div>
            </div>

            <div className="mt-4 rounded border border-slate-200 bg-slate-50 p-3">
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div className="min-w-0">
                  <div className="text-[11px] font-black uppercase tracking-widest text-slate-500">Visuals</div>
                  <div className="mt-1 text-sm font-black text-slate-950">{posterPrompt?.label ?? "Visual prompts appear after generation"}</div>
                  <div className="mt-1 line-clamp-3 text-xs leading-relaxed text-slate-600">{posterPrompt?.prompt ?? "Vertex Imagen prompt and poster direction will be attached to the package."}</div>
                  {visualAssetStudio?.model ? <div className="mt-2 text-[10px] font-black uppercase tracking-widest text-slate-500">Model {visualAssetStudio.model} / {formatStatus(visualAssetResult?.status ?? visualAssetStudio.status ?? "prompt ready")}</div> : null}
                  {visualAssetResult?.persistence?.receiptPath ? <div className="mt-1 truncate text-[10px] font-bold text-slate-500">{visualAssetResult.persistence.assetCount ?? 0} saved / {visualAssetResult.persistence.receiptPath}</div> : null}
                </div>
                <button
                  type="button"
                  onClick={() => void generateVisualAssets()}
                  disabled={isGeneratingVisuals || !draft}
                  className="shrink-0 rounded border border-slate-900 bg-slate-950 px-3 py-2 text-xs font-black text-white disabled:cursor-not-allowed disabled:border-slate-300 disabled:bg-slate-200 disabled:text-slate-500"
                >
                  {isGeneratingVisuals ? "Creating..." : "Create visuals"}
                </button>
              </div>
              {generatedVisualImages.length ? (
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  {generatedVisualImages.slice(0, 4).map((image) => (
                    <img key={image.id ?? image.dataUrl} src={image.dataUrl} alt="Generated visual draft" className="aspect-[4/3] w-full rounded border border-slate-200 object-cover" />
                  ))}
                </div>
              ) : visualAssetResult?.providerReadiness?.readinessIssues?.length ? (
                <div className="mt-2 text-xs font-bold text-slate-500">{visualAssetResult.providerReadiness.readinessIssues.slice(0, 2).join(" ")}</div>
              ) : null}
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => setShowAdvancedReview((value) => !value)}
                className="rounded border border-slate-300 bg-white px-3 py-2 text-xs font-black text-slate-700"
              >
                {showAdvancedReview ? "Hide details" : "Show details"}
              </button>
              <button
                type="button"
                onClick={() => void injectSyntheticMemory()}
                disabled={isInjectingSyntheticMemory}
                className="rounded border border-sky-300 bg-sky-50 px-3 py-2 text-xs font-black text-sky-800 disabled:cursor-not-allowed disabled:border-slate-300 disabled:bg-slate-100 disabled:text-slate-500"
              >
                {isInjectingSyntheticMemory ? "Injecting" : "Inject memory"}
              </button>
              <button
                type="button"
                onClick={() => void saveDraft()}
                disabled={isSavingDraft || !draft}
                className="rounded border border-emerald-500 bg-emerald-500 px-3 py-2 text-xs font-black text-slate-950 disabled:cursor-not-allowed disabled:border-slate-300 disabled:bg-slate-200 disabled:text-slate-500"
              >
                {isSavingDraft ? "Saving" : "Save draft"}
              </button>
              <button
                type="button"
                onClick={() => void approveCurrentPackageForMemory()}
                disabled={isWorkflowBusy || isSavingDraft || !draft}
                className="rounded border border-slate-900 bg-slate-950 px-3 py-2 text-xs font-black text-white disabled:cursor-not-allowed disabled:border-slate-300 disabled:bg-slate-200 disabled:text-slate-500"
              >
                {isWorkflowBusy ? "Approving" : "Approve memory"}
              </button>
            </div>

            {showAdvancedReview ? (
              <div className="mt-4 grid gap-3 rounded border border-slate-200 bg-slate-50 p-3 md:grid-cols-4">
                <div>
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Reasoning</div>
                  <div className="mt-1 text-xs leading-relaxed text-slate-600">{plannerStrategy.routeStrategy ?? "No route strategy yet."}</div>
                </div>
                <div>
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Evidence</div>
                  <div className="mt-1 text-xs leading-relaxed text-slate-600">
                    {retrievedItems.length ? `${retrievedItems.length} facts: ${retrievedItems.slice(0, 2).map((item) => item.id ?? item.kind).filter(Boolean).join(", ")}` : "No retrieval receipt yet."}
                  </div>
                  {retrievalSummary?.topSources?.length ? <div className="mt-1 text-[10px] font-bold text-slate-500">{retrievalSummary.topSources.slice(0, 2).map(formatStatus).join(" / ")}</div> : null}
                </div>
                <div>
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Agent</div>
                  <div className="mt-1 text-xs leading-relaxed text-slate-600">
                    {agentStages.length ? `${agentStages.length} stages: ${agentStages.slice(0, 2).map((stage) => formatStatus(stage.id ?? "")).join(", ")}` : "Agent receipt appears after planning."}
                  </div>
                </div>
                <div>
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Review</div>
                  <div className="mt-1 text-xs leading-relaxed text-slate-600">
                    {productReadiness?.status ? `${formatStatus(productReadiness.status)}${productScore ? `, ${productScore}` : ""}` : creativePackage?.studioQualityEval?.status ? formatStatus(creativePackage.studioQualityEval.status) : "Review appears after generation."}
                  </div>
                  <div className="mt-1 text-[10px] font-bold text-slate-500">{memoryGate?.status ? `Memory: ${formatStatus(memoryGate.status)}` : "Memory gated"}</div>
                </div>
              </div>
            ) : null}
          </div>
        </section>
      </div>
    </main>
  );
}
