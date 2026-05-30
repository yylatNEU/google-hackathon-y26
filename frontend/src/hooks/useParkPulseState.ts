"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchParkPulseApi } from "@/lib/api";
import type { GuestFlow, ParkPath, ParkRide, ParkState, ParkZone } from "@/types/park";

type ApiRecord = Record<string, unknown>;

const LIVE_PARK_POLL_MS = 1500;

function asRecord(value: unknown): ApiRecord {
  return value && typeof value === "object" ? (value as ApiRecord) : {};
}

function numberOrFallback(value: unknown, fallback: number): number {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

function stringOrFallback(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function enumOrFallback<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return typeof value === "string" && allowed.includes(value as T) ? (value as T) : fallback;
}

const fallbackParkState: ParkState = {
  product: {
    name: "ParkPulse AI",
    domain: "amusement_park_operations",
    one_liner: "Multi-agent operations copilot for ride downtime, staffing stress, food demand spikes, guest flow, energy, and incident response.",
    primary_collections: ["park_state", "rides", "staff_shifts", "food_inventory", "incidents", "agent_decisions", "playbooks", "guest_messages", "eval_results"],
  },
  simTime: { hour: 15, minute: 15, day: 1, seasonIndex: 0 },
  weather: {
    condition: "Ride downtime response",
    temperatureF: 91,
    heatIndexF: 99,
    humidity: 74,
    windMph: 18,
    stormRisk: 72,
  },
  energy: {
    gridLoadPercent: 96,
    disruptionLoadMw: 5.4,
    demandChargeRisk: "critical",
    utilityPricePerMwh: 238,
    carbonIntensity: 612,
  },
  staffing: {
    scheduled: 214,
    checkedIn: 196,
    openCallouts: 18,
    medicalTeams: 4,
    securityTeams: 8,
  },
  operatingClock: {
    mode: "day_in_the_life_operating_clock",
    phase: {
      id: "afternoon_heat",
      label: "Afternoon heat and parade pressure",
      minuteOfDay: 915,
      demandPressurePct: 91,
      weatherVolatilityPct: 74,
      eventWave: "parade_release",
      nextPhaseInMinutes: 45,
    },
    guestIntent: {
      dominantIntent: "shade, indoor rides, parade crossing",
      rideSeekingPct: 86,
      foodSeekingPct: 30,
      restSeekingPct: 44,
      exitSeekingPct: 22,
      offerSensitivityPct: 40,
    },
    staffLifecycle: {
      shiftBlock: "midday",
      breakPressurePct: 70,
      fatiguePressurePct: 73,
      redeployDelayMinutes: 8,
      certificationConstraint: "ride_console_and_crowd_lead",
    },
    rideLifecycle: {
      dispatchFrictionPct: 52,
      minorFaultRiskPct: 50,
      reopenRampMinutes: 18,
      maintenanceClearance: "blocked",
    },
    foodRetailLifecycle: {
      prepPressurePct: 30,
      mobileOrderBacklogPressurePct: 46,
      restockDelayMinutes: 15,
      merchandiseWavePct: 22,
    },
    eventSchedule: {
      activeWave: "parade_release",
      showReleaseInMinutes: 18,
      paradeRoutePressurePct: 78,
      frontGateExitPressurePct: 22,
      eventTrafficRiskPct: 88,
      showtimes: [
        {
          id: "afternoon_parade",
          name: "Royal Street Parade",
          kind: "parade",
          startMinute: 900,
          startTime: "3:00 PM",
          endTime: "3:22 PM",
          durationMinutes: 22,
          buildMinutes: 35,
          releaseMinutes: 26,
          minutesUntilStart: -15,
          status: "release",
          phase: "release",
          primaryZoneIds: ["coveredPlaza", "coasterPlaza"],
          affectedPathIds: ["coasterPlaza->coveredPlaza", "entrancePlaza->coveredPlaza"],
          crowdDirection: "route preload then cross-park release",
          trafficRiskPct: 88,
          solvedByPolicy: false,
          solution: "Hold static queue spillback off the parade route, pre-stage crowd leads at both crossings, and split post-parade guests toward Theater B, Arcade, and Main Street.",
          controlActions: ["freeze static queues at crossings", "send crowd leads to parade rope points", "split release to Theater B and Arcade"],
        },
        {
          id: "fireworks_release",
          name: "Fireworks Release",
          kind: "fireworks_release",
          startMinute: 1260,
          startTime: "9:00 PM",
          endTime: "9:12 PM",
          durationMinutes: 12,
          buildMinutes: 8,
          releaseMinutes: 36,
          minutesUntilStart: 345,
          status: "scheduled",
          phase: "scheduled",
          primaryZoneIds: ["coveredPlaza", "entrancePlaza", "foodCourt1"],
          affectedPathIds: ["coveredPlaza->entrancePlaza", "foodCourt1->entrancePlaza"],
          crowdDirection: "lake crowd releases toward exit, lockers, restrooms, and transit",
          trafficRiskPct: 92,
          solvedByPolicy: false,
          solution: "Meter front-gate egress, hold last-ride promotions near low-exit-pressure zones, and push transit/locker guidance before the crowd moves.",
          controlActions: ["meter front-gate egress", "send transit guidance early", "hold last-ride promos away from exit paths"],
        },
      ],
      activeEvents: [
        {
          id: "afternoon_parade",
          name: "Royal Street Parade",
          kind: "parade",
          startMinute: 900,
          startTime: "3:00 PM",
          endTime: "3:22 PM",
          durationMinutes: 22,
          buildMinutes: 35,
          releaseMinutes: 26,
          minutesUntilStart: -15,
          status: "release",
          phase: "release",
          primaryZoneIds: ["coveredPlaza", "coasterPlaza"],
          affectedPathIds: ["coasterPlaza->coveredPlaza", "entrancePlaza->coveredPlaza"],
          crowdDirection: "route preload then cross-park release",
          trafficRiskPct: 88,
          solvedByPolicy: false,
          solution: "Hold static queue spillback off the parade route, pre-stage crowd leads at both crossings, and split post-parade guests toward Theater B, Arcade, and Main Street.",
          controlActions: ["freeze static queues at crossings", "send crowd leads to parade rope points", "split release to Theater B and Arcade"],
        },
      ],
      nextEvent: {
        id: "afternoon_parade",
        name: "Royal Street Parade",
        kind: "parade",
        startMinute: 900,
        startTime: "3:00 PM",
        endTime: "3:22 PM",
        durationMinutes: 22,
        buildMinutes: 35,
        releaseMinutes: 26,
        minutesUntilStart: -15,
        status: "release",
        phase: "release",
        primaryZoneIds: ["coveredPlaza", "coasterPlaza"],
        affectedPathIds: ["coasterPlaza->coveredPlaza", "entrancePlaza->coveredPlaza"],
        crowdDirection: "route preload then cross-park release",
        trafficRiskPct: 88,
        solvedByPolicy: false,
        solution: "Hold static queue spillback off the parade route, pre-stage crowd leads at both crossings, and split post-parade guests toward Theater B, Arcade, and Main Street.",
        controlActions: ["freeze static queues at crossings", "send crowd leads to parade rope points", "split release to Theater B and Arcade"],
      },
      trafficPlan: {
        mode: "closed_loop_showtime_congestion_control",
        status: "watch",
        lookaheadMinutes: 45,
        solves: [
          "predict show/parade/fireworks release waves before density peaks",
          "pre-stage crowd leads and guest messaging before guests move",
          "split routes so one event does not overload food, indoor rides, lockers, or front gate",
        ],
      },
    },
    guestFeedbackLoop: {
      complaintLagMinutes: 15,
      sentimentMomentum: "deteriorating",
      careCaseAccumulationPct: 58,
      recoveryOfferEffectPct: 22,
    },
    accessFairness: {
      mode: "vip_fast_lane_public_fairness",
      status: "critical",
      premiumLaneSharePct: 38,
      standbyLaneSharePct: 62,
      standbyDelayDeltaMins: 19,
      publicComplaintRiskPct: 82,
      perceivedFairnessScore: 18,
      ridePressurePct: 86,
      solvedByPolicy: false,
      activeBottlenecks: ["Dragon Coaster merge point", "Indoor Launch priority return window", "Main Street guest-care desk"],
      mitigationControls: [
        "cap Fast Lane merge ratio when standby exceeds threshold",
        "publish honest standby delay reason in guest app",
        "offer low-wait alternatives without compensation promises",
        "send guest-care lead to explain queue split at merge point",
      ],
      policyBoundary: "No individual guest profiling; fairness is measured with aggregate lane mix, standby delay, and complaint signals.",
    },
  },
  showtimeLearningLoop: {
    mode: "closed_loop_showtime_learning",
    headline: "Scheduled entertainment waves are forecast, acted on, observed, and carried into the next wave.",
    summary: {
      eventsModeled: 5,
      activePolicy: "normal",
      totalGuestMinutesAvoided: 3510,
      averageCongestionAvoidedPct: 9,
      carryoverRiskPct: 18,
      proofStatus: "closed_loop",
    },
    rows: [
      {
        id: "showtime-loop-afternoon_parade",
        eventId: "afternoon_parade",
        name: "Royal Street Parade",
        startTime: "3:00 PM",
        status: "release",
        forecast: { baselinePeakCongestionPct: 96, carryoverRiskPct: 4, affectedPaths: ["coasterPlaza->coveredPlaza", "entrancePlaza->coveredPlaza"], primaryZones: ["coveredPlaza", "coasterPlaza"] },
        action: { policy: "normal", label: "Recommended mitigation: route split and crossing hold", controls: ["freeze static queues at crossings", "send crowd leads to parade rope points", "split release to Theater B and Arcade"], leadTimeMinutes: 0 },
        observed: { peakCongestionPct: 87, congestionAvoidedPct: 9, guestMinutesAvoided: 648, takeRatePct: 46, followThroughPct: 40 },
        learning: { status: "applied_to_later_wave", lesson: "directional evidence: crossing holds must start before route preload, not at parade release.", nextWaveBias: "carry parade crossing load into theater and fireworks routing" },
      },
      {
        id: "showtime-loop-fireworks_release",
        eventId: "fireworks_release",
        name: "Fireworks Release",
        startTime: "9:00 PM",
        status: "scheduled",
        forecast: { baselinePeakCongestionPct: 100, carryoverRiskPct: 16, affectedPaths: ["coveredPlaza->entrancePlaza", "foodCourt1->entrancePlaza"], primaryZones: ["coveredPlaza", "entrancePlaza", "foodCourt1"] },
        action: { policy: "normal", label: "Recommended mitigation: front-gate egress metering", controls: ["meter front-gate egress", "send transit guidance early", "hold last-ride promos away from exit paths"], leadTimeMinutes: 345 },
        observed: { peakCongestionPct: 96, congestionAvoidedPct: 4, guestMinutesAvoided: 504, takeRatePct: 38, followThroughPct: 33 },
        learning: { status: "applied_to_later_wave", lesson: "weak evidence: fireworks crowds need exit messaging before the visual finale ends.", nextWaveBias: "raise front-gate and locker pre-stage before closing" },
      },
    ],
    scenarioLab: [
      { id: "bad_parade_route_split", label: "Bad parade route split", risk: "One crossing releases into Coaster Plaza and blocks the parade route.", agentFix: "Hold static queues at crossings and split families toward Theater B, Arcade, and Main Street." },
      { id: "show_unload_food_backlog", label: "Show unload into food backlog", risk: "Theater exit sends hungry guests into an already constrained pickup queue.", agentFix: "Suppress food-only nudges and open Arcade/Main Street overflow first." },
      { id: "fireworks_exit_crush", label: "Fireworks exit crush", risk: "Lake crowd releases toward lockers, transit, restrooms, and the same front-gate path.", agentFix: "Meter front-gate egress and send transit/locker guidance before the crowd starts moving." },
      { id: "closing_gate_bottleneck", label: "Closing gate bottleneck", risk: "Final rides, retail close, guest services, and fireworks exits collide.", agentFix: "Sequence retail close, split final-ride exits, and pre-stage care teams at the gate edge." },
    ],
    proof: ["operatingClock.eventSchedule.showtimes", "guestFlow.paths.congestionLevel", "guestFlow.zones.density", "showtimeLearningLoop.rows.observed", "showtimeLearningLoop.rows.learning"],
  },
  planningAgent: {
    mode: "online_multi_wave_planning_agent",
    agentId: "planning_agent",
    name: "Park Planning Agent",
    status: "online",
    readinessPct: 82,
    plannerHorizonMinutes: 180,
    activePlan: {
      id: "plan-afternoon-parade",
      name: "Royal Street Parade multi-wave plan",
      policy: "normal",
      stage: "rehearsing_and_recommending",
      nextDecisionDeadlineMinutes: 0,
    },
    evidenceInputs: [
      "physicalMap.landmarks/queues/paths",
      "operatingClock.eventSchedule.showtimes",
      "showtimeLearningLoop.rows.learning",
      "guestFlow.paths.congestionLevel",
      "guestFlow.zones.density",
      "policy_engine.boundaries",
      "MongoDB prior incidents and take-rate memory",
    ],
    rehearsal: {
      scenarioCount: 5,
      cases: ["bad_parade_route_split", "show_unload_food_backlog", "fireworks_exit_crush", "closing_gate_bottleneck", "ride_down_during_show_release"],
      currentWeakPoint: "Coaster Plaza to Covered Plaza",
      primaryConstraint: "Coaster Plaza density 89%; Dragon Coaster wait 60m",
    },
    recommendedPlan: [
      { step: "pre_stage", owner: "staffing_agent", action: "pre-stage crowd leads and guest-care support before the next timed wave", deadlineMinutes: 0 },
      { step: "route_split", owner: "guest_flow_agent", action: "split route recommendations across lower-pressure zones instead of one attractive destination", deadlineMinutes: 0 },
      { step: "policy_gate", owner: "safety_policy_agent", action: "gate public messaging, staff tasks, queue controls, and equipment changes before dispatch", deadlineMinutes: 0 },
      { step: "measure", owner: "gcp_eval_judge_agent", action: "score observed path pressure, take rate, follow-through, and lesson carryover", deadlineMinutes: 22 },
    ],
    handoff: {
      to: "decision_bridge_agent",
      status: "ready_for_policy_gated_commit",
      blockedFrom: ["direct receiver dispatch", "unsafe ride-control claims", "public promises without policy gate"],
    },
  },
  agentOperations: {
    mode: "agent_operations_board",
    headline: "Specialist agents contribute through role-scoped findings, gates, proof, and learning around the online ops surface.",
    summary: {
      onlineCallable: 5,
      online: 1,
      activeCurrentRun: 4,
      standby: 6,
      proofEvalOnly: 2,
      offlineLearning: 1,
      showtimeRows: 2,
      activePolicy: "normal",
    },
    agents: [
      { id: "decision_bridge_agent", name: "Decision Bridge Agent", role: "Resolves specialist disagreement into one executable plan with owners and tradeoffs.", status: "online", currentRole: "online runtime surface", lastContribution: "Owns the online ops surface and converts specialist findings into one policy-gated candidate.", activationTrigger: "Always online for operator-facing decisions.", nextExpectedWork: "Select a policy-gated candidate when specialists disagree.", handoffTo: "delivery_proof_agent", executionMode: "can recommend and hand off; dispatch still policy gated" },
      { id: "planning_agent", name: "Park Planning Agent", role: "Turns the learned digital twin, showtime waves, map constraints, memory, and policy into an executable multi-wave operating plan.", status: "online_callable", currentRole: "online callable service", lastContribution: "Rehearsed 5 scenarios and prepared a 180m multi-wave plan.", activationTrigger: "Online when digital twin, showtimes, or multi-wave planning evidence exists.", nextExpectedWork: "Answer direct service calls and refresh evidence when invoked.", handoffTo: "decision_bridge_agent", executionMode: "callable service endpoint; bounded by agent tool contract" },
      { id: "traffic_flow_agent", name: "Traffic Flow Agent", role: "Models time-block movement, queue spillback, path pressure, and before/after congestion risk.", status: "online_callable", currentRole: "online callable service", lastContribution: "Read timed waves and path pressure; current max path congestion is 91%.", activationTrigger: "Path congestion, showtime waves, spillback, or route split needed.", nextExpectedWork: "Answer direct service calls and refresh evidence when invoked.", handoffTo: "decision_bridge_agent", executionMode: "callable service endpoint; bounded by agent tool contract" },
      { id: "guest_flow_agent", name: "Guest Flow Agent", role: "Balances crowd density, paths, routing targets, guest nudges, and take-rate assumptions.", status: "active_current_run", currentRole: "active in current park frame", lastContribution: "Read zone density and guest intent; current max zone density is 89%.", activationTrigger: "High density, guest movement, app nudge, or route split needed.", nextExpectedWork: "Update recommendation if pressure, policy, or response telemetry changes.", handoffTo: "decision_bridge_agent", executionMode: "advisory specialist contribution" },
      { id: "safety_policy_agent", name: "Safety/Policy Agent", role: "Applies safety, privacy, labor, customer-care, and event policy before execution.", status: "online_callable", currentRole: "online callable service", lastContribution: "Policy gate is ready before guest messages, worker tasks, equipment control, or queue gates.", activationTrigger: "Any dispatch, public message, staff task, equipment control, or sensitive boundary.", nextExpectedWork: "Answer direct service calls and refresh evidence when invoked.", handoffTo: "decision_bridge_agent", executionMode: "callable service endpoint; bounded by agent tool contract" },
      { id: "delivery_proof_agent", name: "Delivery Proof Agent", role: "Verifies Pub/Sub, Firestore, FCM, Dataflow, and receiver acknowledgement evidence.", status: "online_callable", currentRole: "online callable service", lastContribution: "Callable proof service verifies dispatch receipts, receiver acknowledgement, and stream evidence.", activationTrigger: "Callable after dispatch, acknowledgement, or stream evidence needs proof.", nextExpectedWork: "Answer direct service calls and refresh evidence when invoked.", handoffTo: "operator_evidence_dock", executionMode: "callable service endpoint; bounded by agent tool contract" },
      { id: "memory_ops_agent", name: "MongoDB MemoryOps Agent", role: "Audits MongoDB operational memory quality, retrieval depth, embedding coverage, stale state, and vector-search readiness.", status: "online_callable", currentRole: "online callable service", lastContribution: "Callable diagnostic service checks retrieval quality, stale memory, and vector-search readiness.", activationTrigger: "Callable memory quality or retrieval readiness check.", nextExpectedWork: "Answer direct service calls and refresh evidence when invoked.", handoffTo: "operator_evidence_dock", executionMode: "callable service endpoint; bounded by agent tool contract" },
      { id: "autodream_agent", name: "AutoDream Off-Hours Agent", role: "Replays historical outcomes offline, generates counterfactual lessons, and writes review-required dream learnings.", status: "offline_learning", currentRole: "offline learning", lastContribution: "Runs off-hours counterfactual learning; cannot affect live park state.", activationTrigger: "Off-hours replay or counterfactual learning window.", nextExpectedWork: "Review outcomes after the operating window closes.", handoffTo: "operator_evidence_dock", executionMode: "offline only; no live dispatch" },
    ],
    handoffChain: ["Park Understanding", "Traffic/Planning/Specialists", "Safety Policy", "Decision Bridge", "Delivery Proof", "GCP Eval Judge", "Memory/Learning"],
  },
  operationsAudit: {
    auditAgent: {
      name: "Micro-Ops Audit Agent",
      status: "critical",
      lastScanAt: "15:15",
      lookaheadMinutes: 30,
      confidence: 0.91,
      method: "Correlates work logs, shift schedules, ride telemetry, queue deltas, POS/inventory, weather, and incident readiness.",
    },
    summary: {
      criticalAnomalies: 2,
      watchItems: 2,
      earliestReactionMinutes: 4,
      scheduleRiskPct: 91,
      openWorkLogs: 4,
      scheduleItems: 4,
    },
    workLogs: [
      {
        id: "WL-RIDE-1042",
        at: "15:04",
        source: "ride_ops_console",
        zoneId: "coasterPlaza",
        assetId: "dragonCoaster",
        message: "Dispatch interval stopped after lift sensor fault; queue intake still has guests entering from west switchback.",
        signal: "ride_dispatch_log",
        abnormalityScore: 96,
        correlatedBy: ["maintenance_work_order", "queue_camera", "operator_note"],
      },
      {
        id: "WL-CROWD-219",
        at: "15:08",
        source: "queue_camera_density",
        zoneId: "coasterPlaza",
        assetId: "path:coasterPlaza-coveredPlaza",
        message: "Coaster Plaza density is 89% and Coaster Plaza to Covered Plaza path is congested.",
        signal: "crowd_flow_delta",
        abnormalityScore: 91,
        correlatedBy: ["wait_time_delta", "guest_app_location", "path_counter"],
      },
      {
        id: "WL-STAFF-087",
        at: "15:10",
        source: "shift_roster",
        zoneId: "coasterPlaza",
        assetId: "break_block:C",
        message: "Two ride operators and one crowd-control lead are scheduled for break inside the next 20 minutes.",
        signal: "schedule_collision",
        abnormalityScore: 84,
        correlatedBy: ["staff_badge_checkin", "ride_minimum_staffing", "break_policy"],
      },
    ],
    schedule: [
      {
        id: "SCH-RIDE-DRAGON-CLEAR",
        startsAt: "15:11",
        endsAt: "15:41",
        owner: "Maintenance Lead",
        zoneId: "coasterPlaza",
        task: "Dragon Coaster fault isolation and safety signoff",
        status: "late",
        risk: 94,
        dependency: "Cannot reopen or test dispatch until maintenance and ride-safety supervisors sign off.",
        expectedNext: "Technician confirms lift sensor state and posts reopen/no-reopen decision.",
      },
      {
        id: "SCH-STAFF-BREAK-C",
        startsAt: "15:27",
        endsAt: "15:47",
        owner: "Zone C Supervisor",
        zoneId: "coasterPlaza",
        task: "Ride operator protected break block",
        status: "conflict",
        risk: 82,
        dependency: "Minimum staffing must remain satisfied before staff can leave console positions.",
        expectedNext: "Stagger breaks or pull trained floater from Arcade Zone.",
      },
    ],
    anomalies: [
      {
        id: "ANOM-RIDE-MICROSTOP",
        severity: "critical",
        domain: "ride_reliability",
        zoneId: "coasterPlaza",
        title: "Ride downtime is still coupled to active queue intake",
        evidence: ["Dragon Coaster throughput gap is 720 guests/hour.", "Queue still has 540 guests with a 44 minute wait.", "Maintenance signoff is not cleared."],
        detectedAt: "15:09",
        leadTimeMinutes: 4,
        recommendedAction: "Pause new queue intake, publish realistic downtime, and split guests across indoor capacity before spillback reaches the service lane.",
        linkedLogs: ["WL-RIDE-1042", "WL-CROWD-219"],
        owner: "Ride Reliability Agent",
        status: "open",
      },
    ],
    reactionTimeline: [
      {
        at: "15:03",
        label: "Ride dispatch degraded",
        expected: "Dispatch every 75 seconds with steady queue movement.",
        observed: "Dispatch stopped and fault code appeared before a guest-visible closure message.",
        delta: "+720 guests/hour lost capacity",
        auditRead: "Maintenance and guest-flow agents correlate the ride log with queue growth.",
      },
      {
        at: "15:10",
        label: "Schedule conflict detected",
        expected: "Breaks start after queue split stabilizes.",
        observed: "Protected break block starts inside the response window.",
        delta: "12 minute lead time",
        auditRead: "Schedule audit agent recommends a trained floater before the break becomes a staffing violation.",
      },
    ],
  },
  counterfactualForecast: {
    forecastId: "CF-local",
    generatedAt: "2026-05-26T15:15:00Z",
    mode: "counterfactual_audit_intervention",
    headline: "Audit lead time is 4m; acting now prevents the 15-minute forecast from reaching critical risk.",
    leadTimeMinutes: 4,
    horizonMinutes: 15,
    focus: {
      zoneId: "coasterPlaza",
      zoneName: "Coaster Plaza",
      rideId: "dragonCoaster",
      rideName: "Dragon Coaster",
      path: "Coaster Plaza -> Covered Plaza",
      queueId: "dragonQueue",
      queueName: "Dragon Coaster queue",
      topAnomalyId: "ANOM-RIDE-MICROSTOP",
      topAnomalyTitle: "Ride downtime is still coupled to active queue intake",
      response: "pause intake + capacity-aware reroute",
    },
    metrics: [
      { id: "density", label: "Coaster Plaza density in 15m", unit: "%", withoutAudit: 100, withAudit: 82, improvement: 18, tone: "critical" },
      { id: "service_lane", label: "Service lane blockage risk", unit: "%", withoutAudit: 100, withAudit: 90, improvement: 10, tone: "critical" },
      { id: "staff_conflict", label: "Staff break conflict risk", unit: "%", withoutAudit: 98, withAudit: 75, improvement: 23, tone: "critical" },
      { id: "complaints", label: "Expected guest-care cases", unit: "cases", withoutAudit: 58, withAudit: 35, improvement: 23, tone: "critical" },
      { id: "guest_minutes", label: "Guest-minutes lost", unit: "min", withoutAudit: 3150, withAudit: 1910, improvement: 1240, tone: "warning" },
    ],
    horizons: [
      {
        minutes: 5,
        withoutAudit: { densityPct: 96, serviceLaneRiskPct: 98, staffConflictRiskPct: 94, guestComplaintCases: 42, heatMedicalRiskPct: 57, guestMinutesLost: 2360, risk: "critical" },
        withAudit: { densityPct: 86, serviceLaneRiskPct: 91, staffConflictRiskPct: 76, guestComplaintCases: 31, heatMedicalRiskPct: 43, guestMinutesLost: 1750, risk: "critical" },
        delta: { densityPct: 10, serviceLaneRiskPct: 7, staffConflictRiskPct: 18, guestComplaintCases: 11, heatMedicalRiskPct: 14, guestMinutesSaved: 610 },
      },
      {
        minutes: 15,
        withoutAudit: { densityPct: 100, serviceLaneRiskPct: 100, staffConflictRiskPct: 98, guestComplaintCases: 58, heatMedicalRiskPct: 63, guestMinutesLost: 3150, risk: "critical" },
        withAudit: { densityPct: 82, serviceLaneRiskPct: 90, staffConflictRiskPct: 75, guestComplaintCases: 35, heatMedicalRiskPct: 48, guestMinutesLost: 1910, risk: "critical" },
        delta: { densityPct: 18, serviceLaneRiskPct: 10, staffConflictRiskPct: 23, guestComplaintCases: 23, heatMedicalRiskPct: 15, guestMinutesSaved: 1240 },
      },
    ],
    spillback: {
      queueId: "dragonQueue",
      queueName: "Dragon Coaster queue",
      rideId: "dragonCoaster",
      currentGuests: 540,
      currentWaitMins: 44,
      shadePct: 18,
      currentSpillbackRisk: "critical",
      geometry: {
        points: [[650, 242], [612, 272], [665, 307], [733, 310], [790, 288]],
        switchbackCapacityGuests: 475,
        walkwayCapacityGuests: 605,
        serviceLaneCapacityGuests: 720,
        metersPerOverflowGuest: 0.42,
        currentOverflowGuests: 65,
        currentOverflowMeters: 27,
      },
      thresholds: {
        withoutAuditWalkwayBlockedInMinutes: 4,
        withoutAuditServiceLaneBlockedInMinutes: 12,
        withAuditWalkwayBlockedInMinutes: null,
        withAuditServiceLaneBlockedInMinutes: null,
      },
      segments: [
        { id: "switchback", label: "Switchback", capacityGuests: 475, statusWithoutAudit: "overflow", statusWithAudit: "overflow" },
        { id: "walkway", label: "Main walkway", capacityGuests: 605, statusWithoutAudit: "blocked", statusWithAudit: "clear" },
        { id: "service_lane", label: "Service lane", capacityGuests: 720, statusWithoutAudit: "watch", statusWithAudit: "clear" },
      ],
      horizons: [
        {
          minutes: 15,
          withoutAudit: { queueGuests: 752, overflowGuests: 277, overflowMeters: 116, walkwayBlocked: true, serviceLaneBlocked: true, spillbackRiskPct: 100 },
          withAudit: { queueGuests: 458, overflowGuests: 0, overflowMeters: 0, walkwayBlocked: false, serviceLaneBlocked: false, spillbackRiskPct: 64 },
          delta: { guestsKeptInside: 294, overflowMetersAvoided: 116, spillbackRiskReducedPct: 36 },
        },
      ],
      summary: "Dragon Coaster queue is 65 guests beyond switchback capacity now. Without action, walkway blockage is projected in 4 minutes and service-lane blockage in 12 minutes.",
    },
    actionExecution: {
      mode: "delayed_action_guest_response_model",
      finalTakeRatePct: 42,
      workerDelayMinutes: 6,
      guestAppDelayMinutes: 1,
      signageDelayMinutes: 2,
      primaryFriction: "guest hesitation + path merge friction + destination capacity",
      responseCurve: [
        { minutes: 5, effectivenessPct: 52, takeRatePct: 22 },
        { minutes: 10, effectivenessPct: 86, takeRatePct: 36 },
        { minutes: 15, effectivenessPct: 100, takeRatePct: 42 },
        { minutes: 30, effectivenessPct: 100, takeRatePct: 42 },
      ],
      capacityChain: [
        { link: "origin_queue", effect: "227 guests expected to leave pressure queue by 15m." },
        { link: "walkway", effect: "Path friction is 12 points from congestion and food backlog." },
        { link: "workers", effect: "Physical merge control starts after 6m." },
        { link: "destination", effect: "Indoor, food, and lower-wait ride capacity absorb demand gradually instead of instantly." },
      ],
      timeline: [
        { minute: 0, stage: "decision_locked", channel: "agent", label: "Policy-checked action selected", cumulativeTakeRatePct: 0, movedGuests: 0, effectivenessPct: 0, friction: "approval and payload fan-out" },
        { minute: 1, stage: "guest_app_sent", channel: "guest_app", label: "Targeted guest guidance reaches affected queue", cumulativeTakeRatePct: 8, movedGuests: 43, effectivenessPct: 18, friction: "guests read, discuss, and orient before moving" },
        { minute: 3, stage: "signage_visible", channel: "digital_signage", label: "Signs and map prompts reinforce the alternate route", cumulativeTakeRatePct: 18, movedGuests: 101, effectivenessPct: 42, friction: "groups near the front hesitate because ride status may change" },
        { minute: 6, stage: "worker_path_opened", channel: "worker_app", label: "Crowd lead opens the alternate path and protects merge points", cumulativeTakeRatePct: 29, movedGuests: 162, effectivenessPct: 68, friction: "staff travel time and guest flow at the first merge" },
        { minute: 10, stage: "destination_absorbing", channel: "destination_capacity", label: "Destination rides, food, and indoor zones absorb redirected demand", cumulativeTakeRatePct: 36, movedGuests: 203, effectivenessPct: 86, friction: "secondary queue and food backlog determine final capacity fit" },
        { minute: 15, stage: "stabilized_flow", channel: "digital_twin", label: "Flow stabilizes enough to verify spillback avoidance", cumulativeTakeRatePct: 42, movedGuests: 227, effectivenessPct: 100, friction: "late movers and families with fixed ride preference remain" },
      ],
    },
    causalChain: [
      {
        id: "signal",
        label: "Weak signal",
        withoutAudit: "First symptom remains isolated in logs.",
        withAudit: "Ride Reliability Agent correlates logs and schedule.",
        evidence: ["Dispatch interval stopped after lift sensor fault.", "Maintenance signoff is not cleared."],
      },
      {
        id: "propagation",
        label: "Risk propagation",
        withoutAudit: "Dragon Coaster wait pushes guests into Covered Plaza.",
        withAudit: "Pause Intake + Capacity-Aware Reroute reduces pressure before the path locks.",
        evidence: ["Dragon Coaster wait 44m, queue 540.", "Coaster Plaza to Covered Plaza congestion 91%."],
      },
      {
        id: "operational_effect",
        label: "Operational effect",
        withoutAudit: "Density, schedule conflict, complaints, and heat risk compound in the same window.",
        withAudit: "15-minute forecast saves 1240 guest-minutes and reduces complaints by 23 cases.",
        evidence: ["18 density points reduced.", "23 staff-conflict risk points reduced."],
      },
    ],
    impact: {
      densityPointsAvoided: 18,
      serviceLaneRiskReducedPct: 10,
      staffConflictRiskReducedPct: 23,
      guestCareCasesAvoided: 23,
      guestMinutesSaved: 1240,
      summary: "Compared with waiting, the audit intervention saves 1240 guest-minutes, avoids 23 expected guest-care cases, and lowers service-lane risk by 10 points in the 15-minute window.",
    },
    assumptions: [
      "Forecast uses deterministic micro-simulation from current queues, path congestion, staffing risk, food backlog, weather, and audit findings.",
      "With-audit path assumes the selected audit response starts now and has partial effect over the next 30 minutes.",
    ],
  },
  digitalTwinCalibration: {
    mode: "compact_digital_twin_calibration_ledger",
    generatedAt: "2026-05-26T15:15:00Z",
    storagePolicy: {
      detailRetentionHours: 72,
      maxDetailRows: 1200,
      maxPendingRows: 300,
      fullStateSnapshots: false,
      estimatedHotStorageKb: 9.6,
    },
    summary: {
      resolvedRows: 4,
      recentWindow: 4,
      accuracyScore: 84,
      confidence: "medium",
      driftStatus: "stable",
      missCount: 0,
      lowestAccuracyTargets: [
        { target: "Dragon Coaster queue", samples: 4, averageAccuracy: 84, latestAccuracy: 87 },
      ],
    },
    pendingCount: 3,
    pendingPreview: [
      {
        id: "CF-local:5",
        target: { zoneName: "Coaster Plaza", rideName: "Dragon Coaster", queueName: "Dragon Coaster queue" },
        horizonMinutes: 5,
        dueInSimMinutes: 5,
        predicted: {
          withoutAudit: { densityPct: 96, serviceLaneRiskPct: 98, guestComplaintCases: 42, queueGuests: 604, overflowMeters: 54 },
          withAudit: { densityPct: 86, serviceLaneRiskPct: 91, guestComplaintCases: 31, queueGuests: 512, overflowMeters: 16 },
        },
      },
    ],
    latestResolved: [
      {
        id: "CF-prev:15",
        forecastId: "CF-prev",
        horizonMinutes: 15,
        target: { zoneName: "Coaster Plaza", rideName: "Dragon Coaster", queueName: "Dragon Coaster queue" },
        actual: { densityPct: 88, serviceLaneRiskPct: 91, guestComplaintCases: 36, queueGuests: 548, overflowMeters: 31 },
        error: { densityPct: 6, serviceLaneRiskPct: 1, guestComplaintCases: 1, queueGuests: 36, overflowMeters: 15 },
        accuracyScore: 87,
        closestBranch: "withAudit",
        branchScores: { withoutAudit: 63, withAudit: 87 },
      },
    ],
    method: [
      "Store only target metrics, predictions, actuals, absolute error, and branch score.",
      "Resolve forecast rows when the simulation clock reaches the forecast horizon.",
    ],
  },
  missionReplay: {
    mode: "mission_replay",
    generatedAt: "2026-05-26T15:15:00Z",
    headline: "From ride downtime signal to bounded action, outcome, and learning in one operating thread.",
    status: "learning",
    progressPct: 100,
    scenario: {
      key: "ride_down",
      name: "Ride Down + Crowd Redistribution",
      description: "Dragon Coaster is down and queue spillback risk is rising.",
      condition: "Ride downtime response",
    },
    primaryTarget: {
      zoneName: "Coaster Plaza",
      rideName: "Dragon Coaster",
      queueName: "Dragon Coaster queue",
    },
    summary: {
      leadTimeMinutes: 4,
      finalTakeRatePct: 42,
      guestMinutesSaved: 1240,
      accuracyScore: 84,
      driftStatus: "stable",
    },
    steps: [
      {
        id: "signal",
        time: "11:39",
        label: "Signal detected",
        title: "Ride downtime is coupled to active queue intake",
        detail: "Dispatch interval stopped after lift sensor fault; maintenance signoff is not cleared.",
        tone: "critical",
        proof: ["operationsAudit", "ANOM-RIDE-MICROSTOP"],
      },
      {
        id: "forecast",
        time: "11:41",
        label: "Twin forecast",
        title: "Dragon Coaster queue spillback forecast",
        detail: "Walkway blocks in 4m; service lane in 12m if the park waits.",
        tone: "critical",
        proof: ["counterfactualForecast", "CF-local"],
      },
      {
        id: "decision",
        time: "11:42",
        label: "Decision",
        title: "Pause Intake + Capacity-Aware Reroute",
        detail: "Agent chooses the bounded operating move with 4m early-warning lead time.",
        tone: "ok",
        proof: ["actionExecution", "delayed_action_guest_response_model"],
      },
      {
        id: "governance",
        time: "11:43",
        label: "Governance",
        title: "Unsafe ride control stays blocked",
        detail: "Guest, signage, and worker tasks are bounded; ride reopening and sensitive actions remain approval boundaries.",
        tone: "watch",
        proof: ["policy", "bounded_action_only"],
      },
      {
        id: "execution",
        time: "11:51",
        label: "Execution",
        title: "Crowd lead opens the alternate path and protects merge points",
        detail: "162 guests moving by minute 6; final take-rate projected at 42%.",
        tone: "ok",
        proof: ["actionExecution.timeline", "worker_path_opened"],
      },
      {
        id: "outcome",
        time: "12:00",
        label: "Outcome",
        title: "Spillback avoided and service access protected",
        detail: "1240 guest-minutes saved; 23 guest-care cases avoided; 227 guests moved by stabilization.",
        tone: "ok",
        proof: ["counterfactualForecast.impact", "spillback.delta"],
      },
      {
        id: "learning",
        time: "12:01",
        label: "Learning",
        title: "Forecast logged for calibration",
        detail: "84% accuracy; drift status is stable.",
        tone: "ok",
        proof: ["digitalTwinCalibration", "CF-prev:15"],
      },
    ],
  },
  scenarioLab: {
    mode: "scenario_lab",
    generatedAt: "2026-05-26T15:15:00Z",
    headline: "ParkPulse generalization check across five park-day conditions using Dragon Coaster queue as the current pressure anchor.",
    summary: {
      scenarioCount: 5,
      averageScore: 76,
      totalGuestMinutesSaved: 3574,
      averageSpillbackAvoidedPct: 25,
      averageStaffOverloadReducedPct: 31,
      strongestScenario: "Ride cascade day",
      weakestScenario: "High-anomaly day",
      gap: "Noisy weak-signal days still need the clearest evidence of restraint and false-positive control.",
    },
    scoreboard: [
      {
        id: "normal_busy_day",
        label: "Normal busy day",
        condition: "High demand, normal ride reliability",
        stressors: ["queue growth", "food peaks", "guest routing"],
        score: 80,
        baseline: { guestMinutesAtRisk: 905, spillbackRiskPct: 69, staffOverloadPct: 25 },
        parkpulse: { guestMinutesAtRisk: 434, guestMinutesSaved: 471, spillbackAvoidedPct: 21, staffOverloadReducedPct: 27, takeRatePct: 44, predictionAccuracyPct: 89, policyBlocks: 0, learningSignal: "Baseline routing prior strengthened for busy-but-stable days." },
        proof: ["operationsAudit", "counterfactualForecast", "digitalTwinCalibration"],
      },
      {
        id: "ride_cascade_day",
        label: "Ride cascade day",
        condition: "One ride slowdown threatens nearby paths and alternates",
        stressors: ["ride downtime", "queue spillback", "alternate capacity"],
        score: 82,
        baseline: { guestMinutesAtRisk: 1885, spillbackRiskPct: 77, staffOverloadPct: 42 },
        parkpulse: { guestMinutesAtRisk: 792, guestMinutesSaved: 1093, spillbackAvoidedPct: 31, staffOverloadReducedPct: 34, takeRatePct: 42, predictionAccuracyPct: 85, policyBlocks: 1, learningSignal: "Queue spillback threshold and alternate-capacity priors updated." },
        proof: ["operationsAudit", "counterfactualForecast", "digitalTwinCalibration"],
      },
      {
        id: "weather_shock_day",
        label: "Weather shock day",
        condition: "Rain or heat pushes guests toward indoor and covered zones",
        stressors: ["storm routing", "shelter capacity", "comfort load"],
        score: 77,
        baseline: { guestMinutesAtRisk: 1724, spillbackRiskPct: 75, staffOverloadPct: 39 },
        parkpulse: { guestMinutesAtRisk: 793, guestMinutesSaved: 931, spillbackAvoidedPct: 29, staffOverloadReducedPct: 32, takeRatePct: 46, predictionAccuracyPct: 82, policyBlocks: 2, learningSignal: "Shelter split-routing and HVAC protection priors updated." },
        proof: ["operationsAudit", "counterfactualForecast", "digitalTwinCalibration"],
      },
      {
        id: "low_staff_day",
        label: "Low-staff day",
        condition: "Same crowd with fewer available operators and food workers",
        stressors: ["break windows", "role compatibility", "worker overload"],
        score: 72,
        baseline: { guestMinutesAtRisk: 1548, spillbackRiskPct: 74, staffOverloadPct: 36 },
        parkpulse: { guestMinutesAtRisk: 851, guestMinutesSaved: 697, spillbackAvoidedPct: 27, staffOverloadReducedPct: 30, takeRatePct: 39, predictionAccuracyPct: 84, policyBlocks: 3, learningSignal: "Constraint-aware dispatch learned where action must be throttled." },
        proof: ["operationsAudit", "counterfactualForecast", "digitalTwinCalibration"],
      },
      {
        id: "high_anomaly_day",
        label: "High-anomaly day",
        condition: "Many weak signals, some false positives, limited attention",
        stressors: ["noisy signals", "false positives", "overreaction risk"],
        score: 69,
        baseline: { guestMinutesAtRisk: 1425, spillbackRiskPct: 73, staffOverloadPct: 33 },
        parkpulse: { guestMinutesAtRisk: 812, guestMinutesSaved: 613, spillbackAvoidedPct: 25, staffOverloadReducedPct: 29, takeRatePct: 37, predictionAccuracyPct: 80, policyBlocks: 4, learningSignal: "Noise filter bias updated from blocked and low-confidence actions." },
        proof: ["operationsAudit", "counterfactualForecast", "digitalTwinCalibration"],
      },
    ],
    method: [
      "Runs compact scenario profiles against the current audit, counterfactual, action-response, and calibration outputs.",
      "Stores no full alternate worlds; each row keeps only comparison metrics, proof pointers, and the learning signal.",
    ],
  },
  readinessBrief: {
    mode: "parkpulse_readiness_brief",
    generatedAt: "2026-05-26T15:15:00Z",
    headline: "Executive proof of value, trust, readiness, and deployment posture for a supervised ParkPulse pilot.",
    decision: {
      label: "Needs more telemetry",
      goNoGo: "CONDITIONAL",
      score: 73,
      reason: "The operating loop is useful, but trust evidence is not strong enough for a pilot without more live telemetry and failure testing.",
      conditions: [
        "Keep medical, security, evacuation, accessibility, maintenance reopen, labor exception, and compensation actions behind explicit approval.",
        "Connect at least one real queue, staffing, delivery, and guest-feedback feed before claiming production readiness.",
        "Run failure-injection, duplicate-dispatch, stream-interruption, and load tests before autonomous operation.",
      ],
    },
    operationalValue: [
      { id: "guest_minutes", label: "Guest-minutes saved", value: 3574, unit: "minutes", tone: "ok", detail: "Scenario Lab aggregate compared with baseline operation.", proof: ["scenarioLab.summary.totalGuestMinutesSaved", "counterfactualForecast.impact"] },
      { id: "spillback", label: "Spillback avoided", value: 25, unit: "pct", tone: "watch", detail: "Average service-lane and queue-spillback reduction across scenario rows.", proof: ["scenarioLab.summary.averageSpillbackAvoidedPct", "spillback.delta"] },
      { id: "staff_overload", label: "Staff overload reduced", value: 31, unit: "pct", tone: "ok", detail: "Estimated reduction in staff conflict and overload pressure.", proof: ["scenarioLab.summary.averageStaffOverloadReducedPct", "operationsAudit.schedule"] },
      { id: "guest_care", label: "Guest-care cases avoided", value: 23, unit: "cases", tone: "ok", detail: "Counterfactual estimate for avoided guest-care escalation.", proof: ["counterfactualForecast.impact.guestCareCasesAvoided"] },
    ],
    trust: [
      { id: "prediction_accuracy", label: "Prediction accuracy", value: 84, unit: "pct", tone: "ok", detail: "Latest compact calibration ledger score.", proof: ["digitalTwinCalibration.summary.accuracyScore"] },
      { id: "calibration_drift", label: "Calibration drift", value: "stable", unit: "status", tone: "ok", detail: "Whether recent forecasts are drifting away from observed outcomes.", proof: ["digitalTwinCalibration.summary.driftStatus"] },
      { id: "policy_blocks", label: "Policy-blocked actions", value: 10, unit: "blocks", tone: "ok", detail: "Evidence that risky actions are blocked instead of silently executed.", proof: ["scenarioLab.scoreboard.parkpulse.policyBlocks", "bounded_action_only"] },
      { id: "weakest_scenario", label: "Weakest scenario", value: "High-anomaly day", unit: "scenario", tone: "watch", detail: "Noisy weak-signal days still need the clearest evidence of restraint and false-positive control.", proof: ["scenarioLab.summary.weakestScenario"] },
    ],
    readiness: [
      { id: "live_now", label: "Runs live now", status: "ready", detail: "State scan, audit snapshot, counterfactual forecast, mission replay, scenario lab, and calibration ledger are available through API/UI.", proof: ["api.park_state", "api.park_mission_replay", "api.park_scenario_lab"] },
      { id: "simulated", label: "Still simulated", status: "watch", detail: "Scenario comparisons and guest movement are compact deterministic simulations, not full real-world validation.", proof: ["scenarioLab.method", "park_simulation"] },
      { id: "integration_needed", label: "Needs real integration", status: "watch", detail: "Production proof still needs live queue sensors, staffing systems, delivery receipts, and guest-feedback loops.", proof: ["readiness.conditions"] },
      { id: "storage_cost", label: "Storage/cost posture", status: "ready", detail: "Compact ledger keeps forecast rows only; estimated hot storage is 9.6 KB.", proof: ["digitalTwinCalibration.storagePolicy"] },
    ],
    storageCost: {
      posture: "compact_metric_rows",
      fullStateSnapshots: false,
      estimatedHotStorageKb: 9.6,
      detailRetentionHours: 72,
      method: "Readiness uses existing scenario, forecast, and calibration summaries; it does not store replay video or full alternate worlds.",
    },
    evidence: ["missionReplay", "scenarioLab", "counterfactualForecast", "digitalTwinCalibration"],
  },
  learnedAgentMaturity: {
    mode: "learned_agent_maturity",
    generatedAt: "2026-05-26T15:15:00Z",
    headline: "ParkPulse demonstrates a learned operating agent that improves recommendations from prior incidents, take rates, blocked actions, and forecast calibration.",
    maturity: {
      score: 79,
      level: "supervised_operator_copilot",
      summary: "The agent has learned scenario-specific operating bias, but safety-critical authority stays outside the learned layer.",
      nextBias: "Noisy weak-signal days still need the clearest evidence of restraint and false-positive control.",
    },
    memoryDepth: {
      incidentsLearned: 77,
      recommendationLogs: 188,
      takeRateSamples: 94,
      policyBlockHistory: 10,
      calibrationRows: 4,
      learningWindowDays: 30,
      sources: ["prior_incidents", "agent_decisions", "take_rate_outcomes", "policy_blocks", "calibration_ledger"],
    },
    beforeAfter: {
      scenario: "Ride cascade with queue spillback and staff break conflict",
      oldAgent: {
        label: "Untrained response",
        action: "Generic guest reroute to nearest indoor ride.",
        risk: "Can overload Indoor Launch, ignore staff breaks, and miss food-area constraints.",
        expectedTakeRatePct: 29,
        guestMinutesSaved: 720,
        policyAwareness: "warn_only",
      },
      learnedAgent: {
        label: "Learned response",
        action: "Capacity-aware reroute, intake pause, protected staff breaks, food redirect suppression, and blocked unsafe reopen.",
        risk: "Lower secondary congestion because the plan uses prior queue, staffing, food, and policy outcomes.",
        expectedTakeRatePct: 42,
        guestMinutesSaved: 1240,
        policyAwareness: "block_and_explain",
      },
      delta: {
        takeRateLiftPct: 13,
        additionalGuestMinutesSaved: 520,
        newProtections: ["alternate-capacity check", "break-window protection", "unsafe reopen block"],
      },
    },
    scenarioCoverage: [
      { id: "ride_cascade", label: "Ride failure / cascade", confidence: 82, status: "strong", learnedFrom: "queue spillback, alternate capacity, blocked reopen attempts", handles: "pause intake, split reroute, worker path opening" },
      { id: "weather_shock", label: "Weather shock", confidence: 77, status: "medium", learnedFrom: "shelter load, HVAC pressure, storm routing take rate", handles: "covered-route nudges, shelter split, comfort protection" },
      { id: "food_spike", label: "Food demand spike", confidence: 74, status: "medium", learnedFrom: "mobile-order backlog, item suppression, guest redirect acceptance", handles: "menu suppression, pickup ETA updates, demand redirect" },
      { id: "staff_shortage", label: "Staff shortage", confidence: 72, status: "medium", learnedFrom: "role compatibility, break windows, follow-through lag", handles: "certified floater redeploy, throttled asks, break protection" },
      { id: "high_anomaly", label: "High anomaly / noisy signals", confidence: 69, status: "weak", learnedFrom: "false positives, blocked actions, low-confidence weak signals", handles: "restraint, extra evidence requirement, watch mode" },
      { id: "event_night", label: "Event-night surge", confidence: 71, status: "medium", learnedFrom: "event routing, merchandise/food peaks, exit-wave pressure", handles: "pre-stage staff, route waves, timed demand shaping" },
    ],
    domainConfidence: [
      { domain: "ride_cascade", label: "Ride cascade", confidence: 84, tone: "strong" },
      { domain: "guest_flow", label: "Guest flow", confidence: 82, tone: "strong" },
      { domain: "weather_routing", label: "Weather routing", confidence: 77, tone: "medium" },
      { domain: "food_demand", label: "Food demand", confidence: 74, tone: "medium" },
      { domain: "staff_constraints", label: "Staff constraints", confidence: 72, tone: "medium" },
      { domain: "noisy_signals", label: "Noisy weak signals", confidence: 69, tone: "weak" },
    ],
    fixedBoundaries: [
      "The learned agent can recommend but cannot self-authorize ride reopen, evacuation, medical, security, accessibility, compensation, or labor-exception actions.",
      "Policy gates are fixed guardrails, not learned preferences.",
      "Learning is counted only when tied to observed response, take rate, follow-through, policy outcome, or forecast calibration.",
    ],
    proof: ["scenarioLab.scoreboard", "counterfactualForecast.actionExecution", "digitalTwinCalibration.summary", "readinessBrief.decision"],
  },
  learningEvidenceLedger: {
    mode: "learning_evidence_ledger",
    generatedAt: "2026-05-26T15:15:00Z",
    headline: "Traceable learning provenance: each behavior change is linked to a past incident, observed outcome, extracted lesson, and proof pointer.",
    summary: {
      ledgerEntries: 4,
      appliedToday: 3,
      watchOnly: 1,
      averageLessonConfidencePct: 77,
      memoryBackedDecisions: 188,
      policyBackedLessons: 10,
      calibrationAccuracyPct: 84,
      guestMinutesExplained: 1240,
    },
    entries: [
      {
        id: "learn-ride-cascade-capacity",
        status: "applied_today",
        pastIncident: {
          id: "INC-D12-RIDE-CASCADE",
          day: "Day 12",
          scenario: "Ride cascade",
          whatHappened: "Dragon Coaster downtime pushed guests toward Indoor Launch while the alternate queue was already above 45 minutes.",
          originalRecommendation: "Send most affected guests to the nearest indoor ride.",
          observedOutcome: "Indoor Launch absorbed too much demand and secondary waits rose before staff opened a split route.",
          takeRatePct: 31,
          followThroughPct: 26,
        },
        lesson: {
          id: "LESSON-CAPACITY-AWARE-REROUTE",
          rule: "Do not route the full failed-ride crowd to a single alternate when alternate wait exceeds 45 minutes.",
          confidencePct: 86,
          learnedFrom: ["take_rate_outcome", "queue_spillback", "calibration_error"],
        },
        appliedToday: {
          behaviorChange: "Split reroute across lower-load attractions and pause intake before the queue leaves switchback control.",
          oldAction: "Generic indoor-ride redirect",
          newAction: "Capacity-aware reroute + intake pause",
          takeRateAdjustmentPct: 8,
          confidenceChangePct: 11,
          blockedOrDowngraded: "Downgraded single-destination redirect",
        },
        proof: { incidentId: "INC-D12-RIDE-CASCADE", calibrationRow: "CF-prev:15", policyBlock: "bounded_action_only", scenarioRow: "ride_cascade_day" },
      },
      {
        id: "learn-staff-break-protection",
        status: "applied_today",
        pastIncident: {
          id: "INC-D18-STAFF-BREAK",
          day: "Day 18",
          scenario: "Low staff day",
          whatHappened: "Ride downtime response pulled certified operators through protected break windows.",
          originalRecommendation: "Redeploy all nearby certified operators to the crowded zone.",
          observedOutcome: "Follow-through lagged because the ask conflicted with break policy and certification coverage.",
          takeRatePct: 54,
          followThroughPct: 39,
        },
        lesson: {
          id: "LESSON-BREAK-WINDOW-GUARD",
          rule: "Protect break windows and ask only role-compatible floaters during peak downtime response.",
          confidencePct: 78,
          learnedFrom: ["staff_acknowledgement", "policy_block", "follow_through"],
        },
        appliedToday: {
          behaviorChange: "The learned plan asks for one certified floater and keeps protected breaks out of the dispatch path.",
          oldAction: "Redeploy all nearby operators",
          newAction: "Certified floater only + break protection",
          takeRateAdjustmentPct: 5,
          confidenceChangePct: 9,
          blockedOrDowngraded: "Blocked broad redeploy",
        },
        proof: { incidentId: "INC-D18-STAFF-BREAK", calibrationRow: "CF-prev:15", policyBlock: "staff_break_boundary", scenarioRow: "low_staff_day" },
      },
      {
        id: "learn-food-redirect-suppression",
        status: "applied_today",
        pastIncident: {
          id: "INC-D21-FOOD-BACKLOG",
          day: "Day 21",
          scenario: "Food demand spike",
          whatHappened: "A ride-failure offer redirected guests into a food court whose mobile-order backlog was already high.",
          originalRecommendation: "Offer food voucher near the affected ride.",
          observedOutcome: "Guest sentiment fell because pickup estimates slipped after the redirect.",
          takeRatePct: 31,
          followThroughPct: 24,
        },
        lesson: {
          id: "LESSON-SUPPRESS-BACKLOG-FOOD-OFFER",
          rule: "Suppress food redirects when mobile-order backlog is above threshold or staffed capacity is constrained.",
          confidencePct: 74,
          learnedFrom: ["guest_feedback", "pos_backlog", "take_rate_outcome"],
        },
        appliedToday: {
          behaviorChange: "The current response avoids sending the failed-ride crowd into the constrained food area.",
          oldAction: "Food voucher redirect",
          newAction: "Attraction split + food redirect suppression",
          takeRateAdjustmentPct: 4,
          confidenceChangePct: 7,
          blockedOrDowngraded: "Downgraded food offer",
        },
        proof: { incidentId: "INC-D21-FOOD-BACKLOG", calibrationRow: "CF-prev:15", policyBlock: "capacity_constraint", scenarioRow: "food_spike" },
      },
      {
        id: "learn-noisy-signal-restraint",
        status: "watch_only",
        pastIncident: {
          id: "INC-D24-NOISY-SIGNALS",
          day: "Day 24",
          scenario: "High anomaly day",
          whatHappened: "Multiple weak signals suggested a wider cascade, but two were later resolved as false positives.",
          originalRecommendation: "Escalate all weak signals into dispatch tasks.",
          observedOutcome: "Operations attention fragmented and low-confidence tasks created avoidable worker noise.",
          takeRatePct: 27,
          followThroughPct: 19,
        },
        lesson: {
          id: "LESSON-NOISY-SIGNAL-RESTRAINT",
          rule: "Require extra evidence before dispatching weak-signal clusters with mixed confidence.",
          confidencePct: 69,
          learnedFrom: ["false_positive", "policy_block", "operator_feedback"],
        },
        appliedToday: {
          behaviorChange: "Noisy weak signals remain in watch mode unless they correlate with queue, work-log, or guest-care evidence.",
          oldAction: "Dispatch all anomaly tasks",
          newAction: "Watch mode + evidence threshold",
          takeRateAdjustmentPct: -2,
          confidenceChangePct: -5,
          blockedOrDowngraded: "Downgraded to watch",
        },
        proof: { incidentId: "INC-D24-NOISY-SIGNALS", calibrationRow: "CF-prev:15", policyBlock: "low_confidence_restraint", scenarioRow: "high_anomaly_day" },
      },
    ],
    method: [
      "Learning is credited only when tied to observed take rate, follow-through, policy outcome, operator feedback, or calibration error.",
      "The ledger stores compact provenance rows and proof pointers, not full video replay or full alternate-world snapshots.",
    ],
  },
  parkOps: {
    mode: "ride_downtime_response",
    outdoorCapacityCutPct: 48,
    rideConflictCount: 9,
    atRiskRides: 7,
    guestRecoveryPressure: 82,
    staffReadyPct: 91.6,
  },
  guestFlow: {
    activePolicy: "normal",
    activeScenario: {
      key: "ride_down",
      name: "Ride Down + Crowd Redistribution",
      description: "Dragon Coaster is down with a 44-minute current estimate. Nearby guests need safe, capacity-aware redistribution without overloading food or indoor rides.",
      condition: "Ride downtime response",
    },
    interventions: [],
    representedGuests: 5240,
    avgSatisfaction: 78,
    activeGroups: 620,
    zones: [
      { id: "entrancePlaza", name: "Entrance Plaza", area: "Front Entry", processType: "entry", flowType: "mixed", capacity: 1800, currentGuests: 820, density: 46, comfortScore: 72, dominantIntent: "arriving guests", waitMins: 4 },
      { id: "coasterPlaza", name: "Coaster Plaza", area: "Thrill Zone", processType: "ride_queue", flowType: "outdoor", capacity: 1600, currentGuests: 1420, density: 89, comfortScore: 48, dominantIntent: "outdoor ride queue", waitMins: 54 },
      { id: "indoorHub", name: "Indoor Ride Hub", area: "Indoor", processType: "indoor_attraction", flowType: "indoor", capacity: 2600, currentGuests: 1980, density: 76, comfortScore: 78, dominantIntent: "storm shelter and rides", waitMins: 32 },
      { id: "arcadeZone", name: "Arcade Zone", area: "Indoor", processType: "overflow", flowType: "indoor", capacity: 2200, currentGuests: 1160, density: 53, comfortScore: 84, dominantIntent: "overflow attraction", waitMins: 12 },
      { id: "foodCourt1", name: "Food Court 1", area: "Indoor", processType: "food", flowType: "food", capacity: 1400, currentGuests: 1040, density: 74, comfortScore: 70, dominantIntent: "food pickup", waitMins: 28 },
      { id: "coveredPlaza", name: "Covered Plaza", area: "Shelter", processType: "transfer", flowType: "mixed", capacity: 1900, currentGuests: 1510, density: 79, comfortScore: 76, dominantIntent: "rain-safe route", waitMins: 8 },
    ],
    paths: [
      { from: "coasterPlaza", to: "coveredPlaza", fromName: "Coaster Plaza", toName: "Covered Plaza", walkMinutes: 5, capacity: 900, currentGuests: 820, congestionLevel: 91, status: "congested", forwardTransfers: 180, reverseTransfers: 32 },
      { from: "coveredPlaza", to: "indoorHub", fromName: "Covered Plaza", toName: "Indoor Ride Hub", walkMinutes: 4, capacity: 1200, currentGuests: 980, congestionLevel: 82, status: "congested", forwardTransfers: 240, reverseTransfers: 48 },
      { from: "indoorHub", to: "foodCourt1", fromName: "Indoor Ride Hub", toName: "Food Court 1", walkMinutes: 3, capacity: 850, currentGuests: 610, congestionLevel: 72, status: "busy", forwardTransfers: 140, reverseTransfers: 38 },
      { from: "indoorHub", to: "arcadeZone", fromName: "Indoor Ride Hub", toName: "Arcade Zone", walkMinutes: 3, capacity: 1100, currentGuests: 420, congestionLevel: 38, status: "open", forwardTransfers: 90, reverseTransfers: 22 },
    ],
    rides: [
      { id: "dragonCoaster", name: "Dragon Coaster", zone: "coasterPlaza", zoneName: "Coaster Plaza", capacityPerHour: 720, effectiveThroughput: 0, dispatchIntervalSec: 75, rideDurationMin: 2.5, queueGuests: 540, waitMins: 44, downtimeRisk: 100, status: "down", staffRequired: 7, staffAvailable: 6, throughputGap: 720 },
      { id: "indoorLaunch", name: "Indoor Launch", zone: "indoorHub", zoneName: "Indoor Ride Hub", capacityPerHour: 1180, effectiveThroughput: 1040, dispatchIntervalSec: 40, rideDurationMin: 6, queueGuests: 430, waitMins: 55, downtimeRisk: 8, status: "constrained", staffRequired: 9, staffAvailable: 9, throughputGap: 140 },
      { id: "skyDrop", name: "Sky Drop", zone: "coasterPlaza", zoneName: "Thrill Zone", capacityPerHour: 640, effectiveThroughput: 560, dispatchIntervalSec: 90, rideDurationMin: 4.5, queueGuests: 260, waitMins: 24, downtimeRisk: 12, status: "normal", staffRequired: 8, staffAvailable: 8, throughputGap: 80 },
      { id: "arcade", name: "Arcade Zone", zone: "arcadeZone", zoneName: "Arcade Zone", capacityPerHour: 1500, effectiveThroughput: 1420, dispatchIntervalSec: 0, rideDurationMin: 20, queueGuests: 120, waitMins: 7, downtimeRisk: 4, status: "normal", staffRequired: 5, staffAvailable: 5, throughputGap: 80 },
      { id: "theaterB", name: "Theater B", zone: "indoorHub", zoneName: "Indoor Ride Hub", capacityPerHour: 900, effectiveThroughput: 840, dispatchIntervalSec: 600, rideDurationMin: 18, queueGuests: 260, waitMins: 18, downtimeRisk: 6, status: "normal", staffRequired: 4, staffAvailable: 4, throughputGap: 60 },
    ],
  },
  alerts: [
    { severity: "critical", title: "Dragon Coaster downtime", detail: "Pause new queue intake and reroute guests without overloading Indoor Launch." },
    { severity: "warning", title: "Food Court 2 staffing gap", detail: "Do not send the full ride-downtime crowd into an understaffed food area." },
  ],
};

function cloneFallbackState() {
  return JSON.parse(JSON.stringify(fallbackParkState)) as ParkState;
}

function toParkZone(zone: ApiRecord, fallback: ParkZone): ParkZone {
  return {
    ...fallback,
    id: stringOrFallback(zone.id, fallback.id),
    name: stringOrFallback(zone.name, fallback.name),
    area: stringOrFallback(zone.area, fallback.area),
    processType: stringOrFallback(zone.processType, fallback.processType),
    flowType: stringOrFallback(zone.flowType, fallback.flowType),
    capacity: numberOrFallback(zone.capacity, fallback.capacity),
    currentGuests: numberOrFallback(zone.currentGuests, fallback.currentGuests),
    density: numberOrFallback(zone.density, fallback.density),
    comfortScore: numberOrFallback(zone.comfortScore, fallback.comfortScore),
    dominantIntent: stringOrFallback(zone.dominantIntent, fallback.dominantIntent),
    waitMins: numberOrFallback(zone.waitMins, fallback.waitMins),
  };
}

function toParkPath(path: ApiRecord, fallback: ParkPath): ParkPath {
  return {
    ...fallback,
    from: stringOrFallback(path.from, fallback.from),
    to: stringOrFallback(path.to, fallback.to),
    fromName: stringOrFallback(path.fromName, fallback.fromName),
    toName: stringOrFallback(path.toName, fallback.toName),
    walkMinutes: numberOrFallback(path.walkMinutes, fallback.walkMinutes),
    capacity: numberOrFallback(path.capacity, fallback.capacity),
    currentGuests: numberOrFallback(path.currentGuests ?? path.currentPeople, fallback.currentGuests),
    congestionLevel: numberOrFallback(path.congestionLevel, fallback.congestionLevel),
    status: enumOrFallback(path.status, ["open", "busy", "congested", "blocked"] as const, fallback.status),
    forwardTransfers: numberOrFallback(path.forwardTransfers, fallback.forwardTransfers ?? 0),
    reverseTransfers: numberOrFallback(path.reverseTransfers, fallback.reverseTransfers ?? 0),
  };
}

function toParkRide(ride: ApiRecord, fallback: ParkRide): ParkRide {
  return {
    ...fallback,
    id: stringOrFallback(ride.id, fallback.id),
    name: stringOrFallback(ride.name, fallback.name),
    zone: stringOrFallback(ride.zone, fallback.zone),
    zoneName: stringOrFallback(ride.zoneName, fallback.zoneName),
    capacityPerHour: numberOrFallback(ride.capacityPerHour, fallback.capacityPerHour),
    effectiveThroughput: numberOrFallback(ride.effectiveThroughput, fallback.effectiveThroughput),
    dispatchIntervalSec: numberOrFallback(ride.dispatchIntervalSec, fallback.dispatchIntervalSec),
    rideDurationMin: numberOrFallback(ride.rideDurationMin, fallback.rideDurationMin),
    queueGuests: numberOrFallback(ride.queueGuests ?? ride.queuePeople, fallback.queueGuests),
    waitMins: numberOrFallback(ride.waitMins, fallback.waitMins),
    downtimeRisk: numberOrFallback(ride.downtimeRisk, fallback.downtimeRisk),
    status: enumOrFallback(ride.status, ["down", "constrained", "normal"] as const, fallback.status),
    staffRequired: numberOrFallback(ride.staffRequired, fallback.staffRequired),
    staffAvailable: numberOrFallback(ride.staffAvailable, fallback.staffAvailable),
    throughputGap: numberOrFallback(ride.throughputGap, fallback.throughputGap),
  };
}

function recordByStringKey(rows: ApiRecord[], key: string): Map<string, ApiRecord> {
  const entries: Array<[string, ApiRecord]> = [];
  for (const row of rows) {
    const value = row[key];
    if (typeof value === "string" && value) {
      entries.push([value, row]);
    }
  }
  return new Map(entries);
}

function pathKey(path: ApiRecord | ParkPath) {
  return `${path.from ?? ""}->${path.to ?? ""}`;
}

export function toParkPulseState(data: ApiRecord): ParkState {
  const state = cloneFallbackState();
  const liveOps = asRecord(data.parkOps);
  const liveFlow = asRecord(data.guestFlow);
  const movement = asRecord(liveFlow.movementSummary);
  const weather = asRecord(data.weather);
  const energy = asRecord(data.energy);
  const staffing = asRecord(data.staffing);
  const maintenance = asRecord(data.maintenance);
  const foodInventory = asRecord(data.foodInventory);
  const incidentReadiness = asRecord(data.incidentReadiness);
  const guestCare = asRecord(data.guestCare);
  const physicalMap = asRecord(data.physicalMap);
  const performanceProfile = asRecord(liveFlow.performanceProfile);
  const product = asRecord(data.product);
  const simTime = asRecord(data.simTime);
  const operatingClock = asRecord(data.operatingClock);
  const activeScenario = asRecord(liveFlow.activeScenario);

  if (Object.keys(product).length) {
    state.product = product as ParkState["product"];
  }
  if (Object.keys(simTime).length) {
    state.simTime = simTime as ParkState["simTime"];
  }
  state.weather = { ...state.weather, ...weather, stormRisk: Math.max(state.weather.stormRisk, Number(weather.stormRisk ?? 0)) } as ParkState["weather"];
  state.energy = { ...state.energy, ...energy } as ParkState["energy"];
  state.staffing = { ...state.staffing, ...staffing } as ParkState["staffing"];
  if (Object.keys(maintenance).length) {
    state.maintenance = maintenance as ParkState["maintenance"];
  }
  if (Object.keys(foodInventory).length) {
    state.foodInventory = foodInventory as ParkState["foodInventory"];
  }
  if (Object.keys(incidentReadiness).length) {
    state.incidentReadiness = incidentReadiness as ParkState["incidentReadiness"];
  }
  if (Object.keys(guestCare).length) {
    state.guestCare = guestCare as ParkState["guestCare"];
  }
  if (Object.keys(operatingClock).length) {
    state.operatingClock = operatingClock as ParkState["operatingClock"];
  }
  if (Object.keys(asRecord(data.showtimeLearningLoop)).length) {
    state.showtimeLearningLoop = asRecord(data.showtimeLearningLoop) as ParkState["showtimeLearningLoop"];
  }
  if (Object.keys(asRecord(data.planningAgent)).length) {
    state.planningAgent = asRecord(data.planningAgent) as ParkState["planningAgent"];
  }
  if (Object.keys(asRecord(data.agentOperations)).length) {
    state.agentOperations = asRecord(data.agentOperations) as ParkState["agentOperations"];
  }
  if (Object.keys(asRecord(data.operationsAudit)).length) {
    state.operationsAudit = asRecord(data.operationsAudit) as ParkState["operationsAudit"];
  }
  if (Object.keys(asRecord(data.counterfactualForecast)).length) {
    state.counterfactualForecast = asRecord(data.counterfactualForecast) as ParkState["counterfactualForecast"];
  }
  if (Object.keys(asRecord(data.digitalTwinCalibration)).length) {
    state.digitalTwinCalibration = asRecord(data.digitalTwinCalibration) as ParkState["digitalTwinCalibration"];
  }
  if (Object.keys(asRecord(data.missionReplay)).length) {
    state.missionReplay = asRecord(data.missionReplay) as ParkState["missionReplay"];
  }
  if (Object.keys(asRecord(data.scenarioLab)).length) {
    state.scenarioLab = asRecord(data.scenarioLab) as ParkState["scenarioLab"];
  }
  if (Object.keys(asRecord(data.readinessBrief)).length) {
    state.readinessBrief = asRecord(data.readinessBrief) as ParkState["readinessBrief"];
  }
  if (Object.keys(asRecord(data.learnedAgentMaturity)).length) {
    state.learnedAgentMaturity = asRecord(data.learnedAgentMaturity) as ParkState["learnedAgentMaturity"];
  }
  if (Object.keys(asRecord(data.learningEvidenceLedger)).length) {
    state.learningEvidenceLedger = asRecord(data.learningEvidenceLedger) as ParkState["learningEvidenceLedger"];
  }
  if (Object.keys(physicalMap).length) {
    state.physicalMap = physicalMap as ParkState["physicalMap"];
  }
  if (Array.isArray(data.guestSegments)) {
    state.guestSegments = data.guestSegments as ParkState["guestSegments"];
  }
  for (const key of ["externalSystems", "temporalConsequences", "actionConflictSimulation", "physicalDynamics", "industrialDossiers", "policyDoctrine", "digitalTwin"] as const) {
    const value = asRecord(data[key]);
    if (Object.keys(value).length) {
      state[key] = value as never;
    }
  }
  state.alerts = Array.isArray(data.alerts) && data.alerts.length ? (data.alerts as ParkState["alerts"]) : state.alerts;
  state.parkOps = {
    mode: String(liveOps.opsMode ?? state.parkOps.mode),
    outdoorCapacityCutPct: Math.max(state.parkOps.outdoorCapacityCutPct, Number(liveOps.outdoorCapacityCutPct ?? 0)),
    rideConflictCount: Math.max(state.parkOps.rideConflictCount, Number(liveOps.rideConflictCount ?? 0)),
    atRiskRides: Math.max(state.parkOps.atRiskRides, Number(liveOps.atRiskRides ?? 0)),
    guestRecoveryPressure: Math.max(state.parkOps.guestRecoveryPressure, Number(liveOps.guestRecoveryPressure ?? 0)),
    staffReadyPct: Number(liveOps.staffReadyPct ?? state.parkOps.staffReadyPct),
  };

  const liveZones = Array.isArray(liveFlow.zones) ? liveFlow.zones.map(asRecord) : [];
  const livePaths = Array.isArray(liveFlow.paths) ? liveFlow.paths.map(asRecord) : [];
  const liveRides = Array.isArray(liveFlow.rides) ? liveFlow.rides.map(asRecord) : [];
  const liveZonesById = recordByStringKey(liveZones, "id");
  const livePathEntries: Array<[string, ApiRecord]> = [];
  for (const path of livePaths) {
    const key = pathKey(path);
    if (key !== "->") {
      livePathEntries.push([key, path]);
    }
  }
  const livePathsByKey = new Map(livePathEntries);
  const liveRidesById = recordByStringKey(liveRides, "id");
  const liveInterventions = Array.isArray(liveFlow.interventions) ? liveFlow.interventions : [];
  const guestFlow: GuestFlow = {
    ...state.guestFlow,
    activePolicy: String(liveFlow.activePolicy ?? state.guestFlow.activePolicy),
    activeScenario: Object.keys(activeScenario).length ? (activeScenario as GuestFlow["activeScenario"]) : state.guestFlow.activeScenario,
    interventions: liveInterventions as GuestFlow["interventions"],
    representedGuests: Math.max(state.guestFlow.representedGuests, Number(liveFlow.representedGuests ?? movement.representedGuests ?? performanceProfile.representedGuests ?? 0)),
    avgSatisfaction: Math.min(state.guestFlow.avgSatisfaction, Number(liveFlow.avgSatisfaction ?? movement.avgSatisfaction ?? state.guestFlow.avgSatisfaction)),
    activeGroups: Math.max(state.guestFlow.activeGroups, Number(liveFlow.activeGroups ?? movement.activeGroups ?? 0)),
    zones: state.guestFlow.zones.map((zone, index) => toParkZone(liveZonesById.get(zone.id) ?? liveZones[index] ?? {}, zone)),
    paths: state.guestFlow.paths.map((path, index) => toParkPath(livePathsByKey.get(pathKey(path)) ?? livePaths[index] ?? {}, path)),
    rides: state.guestFlow.rides.map((ride, index) => toParkRide(liveRidesById.get(ride.id) ?? liveRides[index] ?? {}, ride)),
  };
  state.guestFlow = guestFlow;
  return state;
}

export function useParkPulseState() {
  const [parkState, setParkState] = useState<ParkState>(fallbackParkState);
  const [isConnected, setIsConnected] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);
  const [liveTick, setLiveTick] = useState(0);
  const [connectionError, setConnectionError] = useState<string | null>(null);

  const applyParkState = useCallback((data: unknown) => {
    setParkState(toParkPulseState(asRecord(data)));
    setIsConnected(true);
    setLastUpdatedAt(Date.now());
    setLiveTick((value) => value + 1);
    setConnectionError(null);
  }, []);

  const refreshParkState = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const res = await fetchParkPulseApi("/api/park/state-lite");
      const data = await res.json();
      applyParkState(data);
      return data;
    } finally {
      setIsRefreshing(false);
    }
  }, [applyParkState]);

  useEffect(() => {
    let cancelled = false;
    let inFlight = false;
    const fetchState = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        if (!cancelled) {
          await refreshParkState();
        }
      } catch (error) {
        if (!cancelled) {
          setIsConnected(false);
          setConnectionError(error instanceof Error ? error.message : "Park state refresh failed");
        }
      } finally {
        inFlight = false;
      }
    };

    fetchState();
    const interval = window.setInterval(fetchState, LIVE_PARK_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [refreshParkState]);

  return {
    parkState,
    isConnected,
    isRefreshing,
    lastUpdatedAt,
    liveTick,
    livePollMs: LIVE_PARK_POLL_MS,
    connectionError,
    refreshParkState,
    applyParkState,
  };
}
