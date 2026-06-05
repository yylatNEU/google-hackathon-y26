"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchParkPulseApi } from "@/lib/api";
import type { GuestFlow, ParkOps, ParkPath, ParkRide, ParkState, ParkZone } from "@/types/park";

type ApiRecord = Record<string, unknown>;

const LIVE_PARK_POLL_MS = 5000;
const OFFLINE_RETRY_MS = 15000;
const STALE_RUNTIME_GRACE_MS = 30000;
const TRANSIENT_FAILURE_LIMIT = 2;
const PARK_STATE_REQUEST_TIMEOUT_MS = 5000;

function asRecord(value: unknown): ApiRecord {
  return value && typeof value === "object" ? (value as ApiRecord) : {};
}

function objectOrUnavailable<T>(value: unknown, unavailable: T): T {
  return value && typeof value === "object" ? (value as T) : unavailable;
}

function arrayOrEmpty<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

const emptyParkState: ParkState = {
  product: {
    name: "",
    domain: "",
    one_liner: "",
    primary_collections: [],
  },
  simTime: {
    hour: 0,
    minute: 0,
    day: 0,
    seasonIndex: 0,
  },
  weather: {
    condition: "unavailable",
    temperatureF: 0,
    heatIndexF: 0,
    humidity: 0,
    windMph: 0,
    stormRisk: 0,
  },
  energy: {
    gridLoadPercent: 0,
    disruptionLoadMw: 0,
    demandChargeRisk: "normal",
    utilityPricePerMwh: 0,
    carbonIntensity: 0,
  },
  staffing: {
    scheduled: 0,
    checkedIn: 0,
    openCallouts: 0,
    medicalTeams: 0,
    securityTeams: 0,
  },
  parkOps: {
    mode: "unavailable",
    outdoorCapacityCutPct: 0,
    rideConflictCount: 0,
    atRiskRides: 0,
    guestRecoveryPressure: 0,
    staffReadyPct: 0,
  },
  guestFlow: {
    activePolicy: "",
    activeScenario: {
      key: "",
      name: "",
      description: "",
      condition: "",
    },
    interventions: [],
    representedGuests: 0,
    avgSatisfaction: 0,
    activeGroups: 0,
    zones: [],
    paths: [],
    rides: [],
  },
  alerts: [],
};

export function toParkPulseState(data: ApiRecord): ParkState {
  const liveFlow = asRecord(data.guestFlow);

  return {
    ...emptyParkState,
    product: objectOrUnavailable(data.product, emptyParkState.product),
    simTime: objectOrUnavailable(data.simTime, emptyParkState.simTime),
    weather: objectOrUnavailable(data.weather, emptyParkState.weather),
    energy: objectOrUnavailable(data.energy, emptyParkState.energy),
    staffing: objectOrUnavailable(data.staffing, emptyParkState.staffing),
    maintenance: objectOrUnavailable(data.maintenance, undefined),
    foodInventory: objectOrUnavailable(data.foodInventory, undefined),
    incidentReadiness: objectOrUnavailable(data.incidentReadiness, undefined),
    chaosEngine: objectOrUnavailable(data.chaosEngine, undefined),
    guestCare: objectOrUnavailable(data.guestCare, undefined),
    operatingClock: objectOrUnavailable(data.operatingClock, undefined),
    showtimeLearningLoop: objectOrUnavailable(data.showtimeLearningLoop, undefined),
    planningAgent: objectOrUnavailable(data.planningAgent, undefined),
    agentOperations: objectOrUnavailable(data.agentOperations, undefined),
    operationsAudit: objectOrUnavailable(data.operationsAudit, undefined),
    counterfactualForecast: objectOrUnavailable(data.counterfactualForecast, undefined),
    digitalTwinCalibration: objectOrUnavailable(data.digitalTwinCalibration, undefined),
    missionReplay: objectOrUnavailable(data.missionReplay, undefined),
    scenarioLab: objectOrUnavailable(data.scenarioLab, undefined),
    readinessBrief: objectOrUnavailable(data.readinessBrief, undefined),
    learnedAgentMaturity: objectOrUnavailable(data.learnedAgentMaturity, undefined),
    learningEvidenceLedger: objectOrUnavailable(data.learningEvidenceLedger, undefined),
    physicalMap: objectOrUnavailable(data.physicalMap, undefined),
    guestSegments: arrayOrEmpty<Record<string, unknown>>(data.guestSegments),
    externalSystems: objectOrUnavailable(data.externalSystems, undefined),
    temporalConsequences: objectOrUnavailable(data.temporalConsequences, undefined),
    actionConflictSimulation: objectOrUnavailable(data.actionConflictSimulation, undefined),
    physicalDynamics: objectOrUnavailable(data.physicalDynamics, undefined),
    industrialDossiers: objectOrUnavailable(data.industrialDossiers, undefined),
    policyDoctrine: objectOrUnavailable(data.policyDoctrine, undefined),
    digitalTwin: objectOrUnavailable(data.digitalTwin, undefined),
    parkOps: {
      ...emptyParkState.parkOps,
      ...objectOrUnavailable<Partial<ParkOps>>(data.parkOps, {}),
    } as ParkOps,
    guestFlow: {
      ...emptyParkState.guestFlow,
      ...objectOrUnavailable<Partial<GuestFlow>>(data.guestFlow, {}),
      zones: arrayOrEmpty<ParkZone>(liveFlow.zones),
      paths: arrayOrEmpty<ParkPath>(liveFlow.paths),
      rides: arrayOrEmpty<ParkRide>(liveFlow.rides),
    } as GuestFlow,
    alerts: arrayOrEmpty(data.alerts),
  };
}

export function useParkPulseState() {
  const [parkState, setParkState] = useState<ParkState>(emptyParkState);
  const [isConnected, setIsConnected] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);
  const [liveTick, setLiveTick] = useState(0);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const retryDelayRef = useRef(OFFLINE_RETRY_MS);
  const lastSuccessfulRefreshRef = useRef<number | null>(null);
  const consecutiveFailureRef = useRef(0);

  const applyParkState = useCallback((data: unknown) => {
    const refreshedAt = Date.now();
    setParkState(toParkPulseState(asRecord(data)));
    setIsConnected(true);
    setLastUpdatedAt(refreshedAt);
    setLiveTick((value) => value + 1);
    setConnectionError(null);
    lastSuccessfulRefreshRef.current = refreshedAt;
    consecutiveFailureRef.current = 0;
    retryDelayRef.current = LIVE_PARK_POLL_MS;
  }, []);

  const refreshParkState = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const res = await fetchParkPulseApi("/api/park/state-lite", { timeoutMs: PARK_STATE_REQUEST_TIMEOUT_MS });
      const data = await res.json();
      applyParkState(data);
      return data;
    } catch (error) {
      consecutiveFailureRef.current += 1;
      const lastSuccessfulRefresh = lastSuccessfulRefreshRef.current;
      const isStale =
        !lastSuccessfulRefresh ||
        Date.now() - lastSuccessfulRefresh > STALE_RUNTIME_GRACE_MS ||
        consecutiveFailureRef.current >= TRANSIENT_FAILURE_LIMIT;
      if (isStale) {
        setIsConnected(false);
        setConnectionError(error instanceof Error ? error.message : "Park state refresh failed");
        retryDelayRef.current = OFFLINE_RETRY_MS;
      } else {
        setIsConnected(true);
        setConnectionError(null);
        retryDelayRef.current = LIVE_PARK_POLL_MS;
      }
      return null;
    } finally {
      setIsRefreshing(false);
    }
  }, [applyParkState]);

  useEffect(() => {
    let cancelled = false;
    let timeoutId: number | undefined;

    const poll = async () => {
      await refreshParkState();
      if (!cancelled) {
        timeoutId = window.setTimeout(poll, retryDelayRef.current);
      }
    };

    void poll();
    return () => {
      cancelled = true;
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [refreshParkState]);

  return {
    parkState,
    isConnected,
    isRefreshing,
    lastUpdatedAt,
    liveTick,
    livePollMs: isConnected ? LIVE_PARK_POLL_MS : OFFLINE_RETRY_MS,
    connectionError,
    refreshParkState,
    applyParkState,
  };
}
