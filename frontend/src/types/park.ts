export type RiskTone = "risk" | "watch" | "ok";

export type ParkAlert = {
  severity: "critical" | "warning" | "info";
  title: string;
  detail: string;
};

export type ParkWeather = {
  condition: string;
  temperatureF: number;
  heatIndexF: number;
  humidity: number;
  windMph: number;
  stormRisk: number;
};

export type ParkEnergy = {
  gridLoadPercent: number;
  disruptionLoadMw: number;
  demandChargeRisk: "normal" | "elevated" | "critical";
  utilityPricePerMwh: number;
  carbonIntensity: number;
};

export type ParkStaffing = {
  scheduled: number;
  checkedIn: number;
  openCallouts: number;
  medicalTeams: number;
  securityTeams: number;
};

export type ParkMaintenance = {
  openWorkOrders: Array<{
    id: string;
    rideId: string;
    rideName: string;
    status: string;
    clearance: string;
    faultCode: string;
    etaMinutes: number;
    requiredSignoff: string[];
  }>;
  clearanceRequiredCount: number;
  sensorAnomalyCount: number;
  lastInspectionMinutesAgo: number;
  blockedAutomation: string[];
};

export type ParkFoodInventory = {
  locations: Array<{
    id: string;
    name: string;
    mobileOrderBacklog: number;
    pickupEtaMinutes: number;
    lowInventoryItems: string[];
    availableItems: string[];
  }>;
  suppressedItems: string[];
  policy: string;
};

export type ParkIncidentReadiness = {
  medicalPostsOpen: number;
  securityPostsOpen: number;
  accessibilityRoutesOpen: boolean;
  emergencyAccessBlocked: boolean;
  highestZoneDensity: number;
  shelterMode: boolean;
  operatorEscalation: string;
};

export type ParkChaosEngine = {
  mode: string;
  usesSeedData: boolean;
  activeUnexpectedEvents: Array<{
    kind?: string;
    targetId?: string;
    intensity?: number;
    createdAt?: string;
    source?: string;
    reason?: string;
  }>;
  activeCount: number;
  ruleCount: number;
  rules: Array<{
    id: string;
    if?: string;
    then?: string;
    condition?: string;
    effect?: string;
  }>;
};

export type ParkGuestCare = {
  openCases: number;
  complaintRatePct: number;
  topDrivers: string[];
  accessFairness?: {
    status: string;
    publicComplaintRiskPct: number;
    standbyDelayDeltaMins: number;
    topDriver: string;
    mitigationControls: string[];
  };
  recoveryQueue: Array<{
    segment: string;
    safeAction: string;
    approval: string;
  }>;
  policy: string;
};

export type ParkOperationsAudit = {
  auditAgent: {
    name: string;
    status: "critical" | "watch" | "stable";
    lastScanAt: string;
    lookaheadMinutes: number;
    confidence: number;
    method: string;
  };
  summary: {
    criticalAnomalies: number;
    watchItems: number;
    earliestReactionMinutes: number;
    scheduleRiskPct: number;
    openWorkLogs: number;
    scheduleItems: number;
  };
  workLogs: Array<{
    id: string;
    at: string;
    source: string;
    zoneId: string;
    assetId: string;
    message: string;
    signal: string;
    abnormalityScore: number;
    correlatedBy: string[];
  }>;
  schedule: Array<{
    id: string;
    startsAt: string;
    endsAt: string;
    owner: string;
    zoneId: string;
    task: string;
    status: string;
    risk: number;
    dependency: string;
    expectedNext: string;
  }>;
  anomalies: Array<{
    id: string;
    severity: "critical" | "warning" | "watch";
    domain: string;
    zoneId: string;
    title: string;
    evidence: string[];
    detectedAt: string;
    leadTimeMinutes: number;
    recommendedAction: string;
    linkedLogs: string[];
    owner: string;
    status: string;
  }>;
  reactionTimeline: Array<{
    at: string;
    label: string;
    expected: string;
    observed: string;
    delta: string;
    auditRead: string;
  }>;
};

export type ParkCounterfactualForecast = {
  forecastId: string;
  generatedAt: string;
  mode: string;
  headline: string;
  leadTimeMinutes: number;
  horizonMinutes: number;
  focus: {
    zoneId: string;
    zoneName: string;
    rideId: string;
    rideName: string;
    path: string;
    queueId?: string;
    queueName?: string;
    topAnomalyId: string;
    topAnomalyTitle: string;
    response: string;
  };
  metrics: Array<{
    id: string;
    label: string;
    unit: string;
    withoutAudit: number;
    withAudit: number;
    improvement: number;
    tone: "critical" | "warning" | "watch";
  }>;
  horizons: Array<{
    minutes: number;
    withoutAudit: {
      densityPct: number;
      serviceLaneRiskPct: number;
      staffConflictRiskPct: number;
      guestComplaintCases: number;
      heatMedicalRiskPct: number;
      guestMinutesLost: number;
      risk: "critical" | "warning" | "watch";
    };
    withAudit: {
      densityPct: number;
      serviceLaneRiskPct: number;
      staffConflictRiskPct: number;
      guestComplaintCases: number;
      heatMedicalRiskPct: number;
      guestMinutesLost: number;
      risk: "critical" | "warning" | "watch";
      actionEffectivenessPct?: number;
    };
    delta: {
      densityPct: number;
      serviceLaneRiskPct: number;
      staffConflictRiskPct: number;
      guestComplaintCases: number;
      heatMedicalRiskPct: number;
      guestMinutesSaved: number;
    };
  }>;
  spillback?: {
    queueId: string;
    queueName: string;
    rideId: string;
    currentGuests: number;
    currentWaitMins: number;
    shadePct: number;
    currentSpillbackRisk: string;
    geometry: {
      points: Array<[number, number]>;
      switchbackCapacityGuests: number;
      walkwayCapacityGuests: number;
      serviceLaneCapacityGuests: number;
      metersPerOverflowGuest: number;
      currentOverflowGuests: number;
      currentOverflowMeters: number;
    };
    thresholds: {
      withoutAuditWalkwayBlockedInMinutes: number | null;
      withoutAuditServiceLaneBlockedInMinutes: number | null;
      withAuditWalkwayBlockedInMinutes: number | null;
      withAuditServiceLaneBlockedInMinutes: number | null;
    };
    segments: Array<{
      id: string;
      label: string;
      capacityGuests: number;
      statusWithoutAudit: string;
      statusWithAudit: string;
    }>;
    horizons: Array<{
      minutes: number;
      withoutAudit: {
        queueGuests: number;
        overflowGuests: number;
        overflowMeters: number;
        walkwayBlocked: boolean;
        serviceLaneBlocked: boolean;
        spillbackRiskPct: number;
      };
      withAudit: {
        queueGuests: number;
        overflowGuests: number;
        overflowMeters: number;
        walkwayBlocked: boolean;
        serviceLaneBlocked: boolean;
        spillbackRiskPct: number;
      };
      delta: {
        guestsKeptInside: number;
        overflowMetersAvoided: number;
        spillbackRiskReducedPct: number;
      };
    }>;
    summary: string;
  };
  actionExecution?: {
    mode: string;
    finalTakeRatePct: number;
    workerDelayMinutes: number;
    guestAppDelayMinutes: number;
    signageDelayMinutes: number;
    primaryFriction: string;
    responseCurve: Array<{
      minutes: number;
      effectivenessPct: number;
      takeRatePct: number;
    }>;
    capacityChain: Array<{
      link: string;
      effect: string;
    }>;
    timeline: Array<{
      minute: number;
      stage: string;
      channel: string;
      label: string;
      cumulativeTakeRatePct: number;
      movedGuests: number;
      effectivenessPct: number;
      friction: string;
    }>;
  };
  causalChain: Array<{
    id: string;
    label: string;
    withoutAudit: string;
    withAudit: string;
    evidence: string[];
  }>;
  impact: {
    densityPointsAvoided: number;
    serviceLaneRiskReducedPct: number;
    staffConflictRiskReducedPct: number;
    guestCareCasesAvoided: number;
    guestMinutesSaved: number;
    summary: string;
  };
  assumptions: string[];
};

export type ParkPhysicalMap = {
  scale: {
    widthMeters: number;
    heightMeters: number;
    north: string;
  };
  landmarks: Array<{
    id: string;
    name: string;
    type: string;
    x: number;
    y: number;
    w: number;
    h: number;
    guestVisible: boolean;
  }>;
  facilities: Array<{
    id: string;
    name: string;
    type: string;
    x: number;
    y: number;
    waitMins: number;
  }>;
  supportStations: Array<{
    id: string;
    name: string;
    x: number;
    y: number;
    status: "online" | "busy" | "offline";
    waitMins: number;
    agentName: string;
    specialties: string[];
    recommendations: string[];
    sampleQuestions: string[];
  }>;
  queues: Array<{
    id: string;
    name: string;
    rideId: string;
    points: Array<[number, number]>;
    guests: number;
    waitMins: number;
    status: string;
    shadePct: number;
    spillbackRisk: string;
    lengthM?: number;
    guestSpacingM?: number;
    physicalQueueM?: number;
    queueLengthUtilizationPct?: number | null;
  }>;
  guestGroups: Array<{
    id: string;
    segment: string;
    count: number;
    x: number;
    y: number;
    destination: string;
    mood: string;
    pace: string;
  }>;
  serviceRoutes: Array<{
    id: string;
    name: string;
    points: Array<[number, number]>;
    access: string;
    blocked: boolean;
  }>;
  realismNotes: string[];
};

export type ParkDigitalTwinCalibration = {
  mode: string;
  generatedAt: string;
  storagePolicy: {
    detailRetentionHours: number;
    maxDetailRows: number;
    maxPendingRows: number;
    fullStateSnapshots: boolean;
    estimatedHotStorageKb: number;
  };
  summary: {
    resolvedRows: number;
    recentWindow: number;
    accuracyScore: number | null;
    confidence: string;
    driftStatus: string;
    missCount: number;
    lowestAccuracyTargets: Array<{
      target: string;
      samples: number;
      averageAccuracy: number;
      latestAccuracy: number | null;
    }>;
  };
  pendingCount: number;
  pendingPreview: Array<{
    id: string;
    target: {
      zoneId?: string;
      zoneName?: string;
      rideId?: string;
      rideName?: string;
      queueId?: string;
      queueName?: string;
    };
    horizonMinutes: number;
    dueInSimMinutes: number;
    predicted: {
      withoutAudit: Record<string, number>;
      withAudit: Record<string, number>;
    };
  }>;
  latestResolved: Array<{
    id: string;
    forecastId: string;
    horizonMinutes: number;
    target: {
      zoneName?: string;
      rideName?: string;
      queueName?: string;
    };
    actual: Record<string, number>;
    error: Record<string, number>;
    accuracyScore: number;
    closestBranch: string;
    branchScores: {
      withoutAudit: number;
      withAudit: number;
    };
  }>;
  method: string[];
};

export type ParkMissionReplay = {
  mode: string;
  generatedAt: string;
  headline: string;
  status: string;
  progressPct: number;
  scenario: {
    key?: string;
    name?: string;
    description?: string;
    condition?: string;
  };
  primaryTarget: {
    zoneName?: string;
    rideName?: string;
    queueName?: string;
  };
  summary: {
    leadTimeMinutes: number;
    finalTakeRatePct: number;
    guestMinutesSaved: number;
    accuracyScore: number | null;
    driftStatus: string;
  };
  steps: Array<{
    id: string;
    time: string;
    label: string;
    title: string;
    detail: string;
    tone: "critical" | "watch" | "ok" | string;
    proof: string[];
  }>;
};

export type ParkScenarioLab = {
  mode: string;
  generatedAt: string;
  headline: string;
  summary: {
    scenarioCount: number;
    averageScore: number;
    totalGuestMinutesSaved: number;
    averageSpillbackAvoidedPct: number;
    averageStaffOverloadReducedPct: number;
    strongestScenario: string;
    weakestScenario: string;
    gap: string;
  };
  scoreboard: Array<{
    id: string;
    label: string;
    condition: string;
    stressors: string[];
    score: number;
    baseline: {
      guestMinutesAtRisk: number;
      spillbackRiskPct: number;
      staffOverloadPct: number;
    };
    parkpulse: {
      guestMinutesAtRisk: number;
      guestMinutesSaved: number;
      spillbackAvoidedPct: number;
      staffOverloadReducedPct: number;
      takeRatePct: number;
      predictionAccuracyPct: number;
      policyBlocks: number;
      learningSignal: string;
    };
    proof: string[];
  }>;
  method: string[];
};

export type ParkReadinessBrief = {
  mode: string;
  generatedAt: string;
  headline: string;
  decision: {
    label: string;
    goNoGo: string;
    score: number;
    reason: string;
    conditions: string[];
  };
  operationalValue: Array<{
    id: string;
    label: string;
    value: number;
    unit: string;
    tone: "critical" | "watch" | "ok" | string;
    detail: string;
    proof: string[];
  }>;
  trust: Array<{
    id: string;
    label: string;
    value: number | string;
    unit: string;
    tone: "critical" | "watch" | "ok" | string;
    detail: string;
    proof: string[];
  }>;
  readiness: Array<{
    id: string;
    label: string;
    status: "ready" | "watch" | "blocked" | string;
    detail: string;
    proof: string[];
  }>;
  storageCost: {
    posture: string;
    fullStateSnapshots: boolean;
    estimatedHotStorageKb?: number;
    detailRetentionHours?: number;
    method: string;
  };
  evidence: string[];
};

export type ParkLearnedAgentMaturity = {
  mode: string;
  generatedAt: string;
  headline: string;
  maturity: {
    score: number;
    level: string;
    summary: string;
    nextBias: string;
  };
  memoryDepth: {
    incidentsLearned: number;
    recommendationLogs: number;
    takeRateSamples: number;
    policyBlockHistory: number;
    calibrationRows: number;
    learningWindowDays: number;
    sources: string[];
  };
  beforeAfter: {
    scenario: string;
    oldAgent: {
      label: string;
      action: string;
      risk: string;
      expectedTakeRatePct: number;
      guestMinutesSaved: number;
      policyAwareness: string;
    };
    learnedAgent: {
      label: string;
      action: string;
      risk: string;
      expectedTakeRatePct: number;
      guestMinutesSaved: number;
      policyAwareness: string;
    };
    delta: {
      takeRateLiftPct: number;
      additionalGuestMinutesSaved: number;
      newProtections: string[];
    };
  };
  scenarioCoverage: Array<{
    id: string;
    label: string;
    confidence: number;
    status: "strong" | "medium" | "weak" | string;
    learnedFrom: string;
    handles: string;
  }>;
  domainConfidence: Array<{
    domain: string;
    label: string;
    confidence: number;
    tone: "strong" | "medium" | "weak" | string;
  }>;
  fixedBoundaries: string[];
  proof: string[];
};

export type ParkLearningEvidenceLedger = {
  mode: string;
  generatedAt: string;
  headline: string;
  summary: {
    ledgerEntries: number;
    appliedToday: number;
    watchOnly: number;
    averageLessonConfidencePct: number;
    memoryBackedDecisions: number;
    policyBackedLessons: number;
    calibrationAccuracyPct: number;
    guestMinutesExplained: number;
  };
  entries: Array<{
    id: string;
    status: "applied_today" | "watch_only" | string;
    pastIncident: {
      id: string;
      day: string;
      scenario: string;
      whatHappened: string;
      originalRecommendation: string;
      observedOutcome: string;
      takeRatePct: number;
      followThroughPct: number;
    };
    lesson: {
      id: string;
      rule: string;
      confidencePct: number;
      learnedFrom: string[];
    };
    appliedToday: {
      behaviorChange: string;
      oldAction: string;
      newAction: string;
      takeRateAdjustmentPct: number;
      confidenceChangePct: number;
      blockedOrDowngraded: string;
    };
    proof: {
      incidentId: string;
      calibrationRow: string;
      policyBlock: string;
      scenarioRow: string;
    };
  }>;
  method: string[];
};

export type ParkShowtimeLearningLoop = {
  mode: string;
  headline: string;
  summary: {
    eventsModeled: number;
    activePolicy: string;
    totalGuestMinutesAvoided: number;
    averageCongestionAvoidedPct: number;
    carryoverRiskPct: number;
    proofStatus: string;
  };
  rows: Array<{
    id: string;
    eventId: string;
    name: string;
    startTime: string;
    status: string;
    forecast: {
      baselinePeakCongestionPct: number;
      carryoverRiskPct: number;
      affectedPaths: string[];
      primaryZones: string[];
    };
    action: {
      policy: string;
      label: string;
      controls: string[];
      leadTimeMinutes: number;
    };
    observed: {
      peakCongestionPct: number;
      congestionAvoidedPct: number;
      guestMinutesAvoided: number;
      takeRatePct: number;
      followThroughPct: number;
    };
    learning: {
      status: string;
      lesson: string;
      nextWaveBias: string;
    };
  }>;
  scenarioLab: Array<{
    id: string;
    label: string;
    risk: string;
    agentFix: string;
  }>;
  proof: string[];
};

export type ParkPlanningAgent = {
  mode: string;
  agentId: string;
  name: string;
  status: string;
  readinessPct: number;
  plannerHorizonMinutes: number;
  activePlan: {
    id: string;
    name: string;
    policy: string;
    stage: string;
    nextDecisionDeadlineMinutes: number;
  };
  evidenceInputs: string[];
  rehearsal: {
    scenarioCount: number;
    cases: string[];
    currentWeakPoint: string;
    primaryConstraint: string;
  };
  recommendedPlan: Array<{
    step: string;
    owner: string;
    action: string;
    deadlineMinutes: number;
  }>;
  handoff: {
    to: string;
    status: string;
    blockedFrom: string[];
  };
};

export type ParkAgentOperations = {
  mode: string;
  headline: string;
  summary: {
    onlineCallable: number;
    online: number;
    activeCurrentRun: number;
    standby: number;
    proofEvalOnly: number;
    offlineLearning: number;
    showtimeRows: number;
    activePolicy: string;
  };
  agents: Array<{
    id: string;
    name: string;
    role: string;
    status: "online_callable" | "online" | "active_current_run" | "standby" | "proof_eval_only" | "offline_learning" | string;
    currentRole: string;
    lastContribution: string;
    activationTrigger: string;
    nextExpectedWork: string;
    handoffTo: string;
    executionMode: string;
  }>;
  handoffChain: string[];
};

export type ParkOperatingClock = {
  mode: string;
  phase: {
    id: string;
    label: string;
    minuteOfDay: number;
    demandPressurePct: number;
    weatherVolatilityPct: number;
    eventWave: string;
    nextPhaseInMinutes: number;
    expectedHotspots?: string[];
    isOpenToGuests?: boolean;
  };
  heartbeat?: {
    tickLabel: string;
    minuteOfDay: number;
    isOpenToGuests: boolean;
    isOvernight: boolean;
    activeWave: string;
    currentHotspots: string[];
    nextHotspot: string | null;
    reason: string;
  };
  guestIntent: {
    dominantIntent: string;
    rideSeekingPct: number;
    foodSeekingPct: number;
    restSeekingPct: number;
    exitSeekingPct: number;
    offerSensitivityPct: number;
  };
  staffLifecycle: {
    shiftBlock: string;
    breakPressurePct: number;
    fatiguePressurePct: number;
    redeployDelayMinutes: number;
    certificationConstraint: string;
  };
  rideLifecycle: {
    dispatchFrictionPct: number;
    minorFaultRiskPct: number;
    reopenRampMinutes: number;
    maintenanceClearance: string;
  };
  foodRetailLifecycle: {
    prepPressurePct: number;
    mobileOrderBacklogPressurePct: number;
    restockDelayMinutes: number;
    merchandiseWavePct: number;
  };
  eventSchedule: {
    activeWave: string;
    showReleaseInMinutes: number | null;
    paradeRoutePressurePct: number;
    frontGateExitPressurePct: number;
    eventTrafficRiskPct?: number;
    showtimes?: Array<{
      id: string;
      name: string;
      kind: string;
      startMinute: number;
      startTime: string;
      endTime: string;
      durationMinutes: number;
      buildMinutes: number;
      releaseMinutes: number;
      minutesUntilStart: number;
      status: string;
      phase: string;
      primaryZoneIds: string[];
      affectedPathIds: string[];
      crowdDirection: string;
      trafficRiskPct: number;
      solvedByPolicy: boolean;
      solution: string;
      controlActions: string[];
    }>;
    activeEvents?: Array<{
      id: string;
      name: string;
      kind: string;
      startMinute: number;
      startTime: string;
      endTime: string;
      durationMinutes: number;
      buildMinutes: number;
      releaseMinutes: number;
      minutesUntilStart: number;
      status: string;
      phase: string;
      primaryZoneIds: string[];
      affectedPathIds: string[];
      crowdDirection: string;
      trafficRiskPct: number;
      solvedByPolicy: boolean;
      solution: string;
      controlActions: string[];
    }>;
    nextEvent?: {
      id: string;
      name: string;
      kind: string;
      startMinute: number;
      startTime: string;
      endTime: string;
      durationMinutes: number;
      buildMinutes: number;
      releaseMinutes: number;
      minutesUntilStart: number;
      status: string;
      phase: string;
      primaryZoneIds: string[];
      affectedPathIds: string[];
      crowdDirection: string;
      trafficRiskPct: number;
      solvedByPolicy: boolean;
      solution: string;
      controlActions: string[];
    };
    trafficPlan?: {
      mode: string;
      status: string;
      lookaheadMinutes: number;
      solves: string[];
    };
  };
  guestFeedbackLoop: {
    complaintLagMinutes: number;
    sentimentMomentum: string;
    careCaseAccumulationPct: number;
    recoveryOfferEffectPct: number;
  };
  accessFairness?: {
    mode: string;
    status: string;
    premiumLaneSharePct: number;
    standbyLaneSharePct: number;
    standbyDelayDeltaMins: number;
    publicComplaintRiskPct: number;
    perceivedFairnessScore: number;
    ridePressurePct: number;
    solvedByPolicy: boolean;
    activeBottlenecks: string[];
    mitigationControls: string[];
    policyBoundary: string;
  };
};

export type ParkOps = {
  mode: string;
  outdoorCapacityCutPct: number;
  rideConflictCount: number;
  atRiskRides: number;
  guestRecoveryPressure: number;
  staffReadyPct: number;
};

export type ParkZone = {
  id: string;
  name: string;
  area: string;
  processType: string;
  flowType: string;
  areaSqM?: number;
  capacity: number;
  currentGuests: number;
  density: number;
  densityGuestsPerSqM?: number;
  comfortScore: number;
  dominantIntent: string;
  waitMins: number;
};

export type ParkPath = {
  from: string;
  to: string;
  fromName: string;
  toName: string;
  walkMinutes: number;
  lengthM?: number;
  widthM?: number;
  maxFlowPerMinute?: number;
  flowCapacityThisTick?: number;
  densityGuestsPerMeter?: number;
  widthUtilizationPct?: number;
  capacity: number;
  currentGuests: number;
  congestionLevel: number;
  status: "open" | "busy" | "congested" | "blocked";
  forwardTransfers?: number;
  reverseTransfers?: number;
};

export type ParkRide = {
  id: string;
  name: string;
  zone: string;
  zoneName: string;
  capacityPerHour: number;
  effectiveThroughput: number;
  dispatchIntervalSec: number;
  rideDurationMin: number;
  queueGuests: number;
  waitMins: number;
  downtimeRisk: number;
  status: "down" | "constrained" | "normal";
  staffRequired: number;
  staffAvailable: number;
  throughputGap: number;
};

export type GuestFlow = {
  activePolicy: string;
  activeScenario: {
    key: string;
    name: string;
    description: string;
    condition: string;
  };
  interventions?: Array<{
    kind: string;
    targetId: string;
    intensity: number;
    createdAt: string;
  }>;
  representedGuests: number;
  avgSatisfaction: number;
  activeGroups: number;
  zones: ParkZone[];
  paths: ParkPath[];
  rides: ParkRide[];
};

export type ParkState = {
  product: {
    name: string;
    domain: string;
    one_liner: string;
    primary_collections: string[];
  };
  simTime: {
    hour: number;
    minute: number;
    day: number;
    seasonIndex: number;
  };
  weather: ParkWeather;
  energy: ParkEnergy;
  staffing: ParkStaffing;
  maintenance?: ParkMaintenance;
  foodInventory?: ParkFoodInventory;
  incidentReadiness?: ParkIncidentReadiness;
  chaosEngine?: ParkChaosEngine;
  guestCare?: ParkGuestCare;
  operatingClock?: ParkOperatingClock;
  showtimeLearningLoop?: ParkShowtimeLearningLoop;
  planningAgent?: ParkPlanningAgent;
  agentOperations?: ParkAgentOperations;
  operationsAudit?: ParkOperationsAudit;
  counterfactualForecast?: ParkCounterfactualForecast;
  digitalTwinCalibration?: ParkDigitalTwinCalibration;
  missionReplay?: ParkMissionReplay;
  scenarioLab?: ParkScenarioLab;
  readinessBrief?: ParkReadinessBrief;
  learnedAgentMaturity?: ParkLearnedAgentMaturity;
  learningEvidenceLedger?: ParkLearningEvidenceLedger;
  physicalMap?: ParkPhysicalMap;
  guestSegments?: Array<Record<string, unknown>>;
  externalSystems?: Record<string, unknown>;
  temporalConsequences?: Record<string, unknown>;
  actionConflictSimulation?: Record<string, unknown>;
  physicalDynamics?: Record<string, unknown>;
  industrialDossiers?: Record<string, unknown>;
  policyDoctrine?: Record<string, unknown>;
  digitalTwin?: Record<string, unknown>;
  parkOps: ParkOps;
  guestFlow: GuestFlow;
  alerts: ParkAlert[];
};
