"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParkPulseState } from "@/hooks/useParkPulseState";
import { fetchParkPulseApi, longRunningRequestTimeoutMs } from "@/lib/api";
import { agentBriefsFromRuntime } from "@/lib/parkPulseAgents";
import { DEMO_SCENARIOS, dispatchBody } from "@/lib/parkPulseDemoContent";
import type { AgentBrief, DeliveryDispatch, EvalScore, IntegrationStatus, RunTelemetry, ScenarioKey } from "@/types/platform";

type RunPayload = RunTelemetry & {
  run_telemetry?: RunTelemetry;
  operator_response?: RunTelemetry["operator_response"];
};

export type DispatchView = {
  id: string;
  channel: string;
  target: string;
  body: string;
  guardrail?: string;
  status?: string;
  source: "runtime" | "scenario";
  dispatch?: DeliveryDispatch;
};

function scenarioActionTarget(scenarioKey: ScenarioKey) {
  if (scenarioKey === "food_spike") return { target: "food", action: "suppress_item" };
  if (scenarioKey === "staff_shortage") return { target: "staff", action: "redeploy" };
  if (scenarioKey === "storm_response") return { target: "weather", action: "shelter_routing" };
  return { target: "ride", action: "reroute" };
}

function normalizeRunTelemetry(payload: RunPayload): RunTelemetry {
  return payload.run_telemetry ?? payload;
}

function normalizeDispatch(dispatch: DeliveryDispatch, index: number): DispatchView {
  return {
    id: dispatch.id ?? `runtime-dispatch-${index}`,
    channel: dispatch.channel ?? dispatch.targetSystem ?? "receiver",
    target: dispatch.payload?.targetZone ?? dispatch.targetSystem ?? dispatch.endpoint ?? "operations receiver",
    body: dispatchBody(dispatch) ?? "Dispatch payload prepared.",
    status: dispatch.approvalDecision?.decision ?? dispatch.lastAcknowledgement?.choice ?? dispatch.status,
    source: "runtime",
    dispatch,
  };
}

export function useCommandCenter() {
  const park = useParkPulseState();
  const [selectedScenarioKey, setSelectedScenarioKey] = useState<ScenarioKey>("ride_down");
  const [runTelemetry, setRunTelemetry] = useState<RunTelemetry | null>(null);
  const [backendEvalScores, setBackendEvalScores] = useState<EvalScore[] | null>(null);
  const [integrationStatus, setIntegrationStatus] = useState<IntegrationStatus | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [isDispatching, setIsDispatching] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const scenario = DEMO_SCENARIOS[selectedScenarioKey];
  const activeEvalScores = backendEvalScores?.length ? backendEvalScores : scenario.evals;

  const agentBriefs: AgentBrief[] = useMemo(() => {
    const runtime = agentBriefsFromRuntime(runTelemetry?.agent_findings);
    if (runtime.length) return runtime;
    return scenario.agentBriefs.map((agent) => ({ ...agent, source: "scenario" as const }));
  }, [runTelemetry?.agent_findings, scenario.agentBriefs]);

  const dispatches: DispatchView[] = useMemo(() => {
    const runtimeDispatches = runTelemetry?.delivery?.dispatches ?? [];
    if (runtimeDispatches.length) return runtimeDispatches.map(normalizeDispatch);
    return (scenario.experienceModel?.smartActions ?? []).map((action, index) => ({
      id: `${scenario.key}-${action.channel}-${index}`,
      channel: action.channel,
      target: action.target,
      body: action.payload,
      guardrail: action.guardrail,
      status: scenario.humanApproval ? "pending approval" : "draft ready",
      source: "scenario" as const,
    }));
  }, [runTelemetry?.delivery?.dispatches, scenario]);

  const selectedAction = runTelemetry?.planner?.selected_action;
  const policyGate = runTelemetry?.governance?.gate_status ?? (scenario.humanApproval ? "human_review_required" : "allowed");
  const evalScore = runTelemetry?.eval?.scorecard?.overall;
  const memoryMode = runTelemetry?.memory?.mode ?? integrationStatus?.mongo?.mode ?? "local proof";

  const loadEvalScores = useCallback(async (scenarioKey: ScenarioKey) => {
    try {
      const response = await fetchParkPulseApi(`/api/park/evals/${scenarioKey}`, { timeoutMs: 5000 });
      const payload = (await response.json()) as { evals?: EvalScore[]; scorecard?: Record<string, number> };
      if (Array.isArray(payload.evals)) {
        setBackendEvalScores(payload.evals);
      } else {
        setBackendEvalScores(null);
      }
    } catch {
      setBackendEvalScores(null);
    }
  }, []);

  const refreshIntegrationStatus = useCallback(async () => {
    try {
      const response = await fetchParkPulseApi("/api/park/integration-status", { timeoutMs: 5000 });
      setIntegrationStatus((await response.json()) as IntegrationStatus);
    } catch {
      setIntegrationStatus(null);
    }
  }, []);

  useEffect(() => {
    void loadEvalScores(selectedScenarioKey);
  }, [loadEvalScores, selectedScenarioKey]);

  useEffect(() => {
    void refreshIntegrationStatus();
  }, [refreshIntegrationStatus]);

  const selectScenario = useCallback(
    (scenarioKey: ScenarioKey) => {
      setSelectedScenarioKey(scenarioKey);
      setRunTelemetry(null);
      setStatusMessage(`Loaded ${DEMO_SCENARIOS[scenarioKey].title}. Run the agent to produce the receipt.`);
      setErrorMessage(null);
    },
    [],
  );

  const runAgent = useCallback(async () => {
    setIsRunning(true);
    setErrorMessage(null);
    setStatusMessage("Running state read, specialist findings, policy gate, dispatch draft, and eval receipt.");
    try {
      const response = await fetchParkPulseApi("/api/park/agent-run", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          scenario_key: selectedScenarioKey,
          operation_mode: false,
          auto_unexpected_event: false,
          operator_message: scenario.situation,
          execute: true,
        }),
        timeoutMs: longRunningRequestTimeoutMs,
      });
      const payload = (await response.json()) as RunPayload;
      const telemetry = normalizeRunTelemetry(payload);
      setRunTelemetry(telemetry);
      setStatusMessage(telemetry.operator_response?.headline ?? "Agent run complete. Receipt is ready for review.");
      await park.refreshParkState();
      void loadEvalScores(selectedScenarioKey);
      void refreshIntegrationStatus();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Unable to run the ParkPulse agent.");
      setStatusMessage(null);
    } finally {
      setIsRunning(false);
    }
  }, [loadEvalScores, park, refreshIntegrationStatus, scenario.situation, selectedScenarioKey]);

  const executeSelectedAction = useCallback(async () => {
    setIsDispatching(true);
    setErrorMessage(null);
    const action = selectedAction?.action && selectedAction.target ? { target: selectedAction.target, action: selectedAction.action } : scenarioActionTarget(selectedScenarioKey);
    try {
      const response = await fetchParkPulseApi("/api/park/action", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(action),
        timeoutMs: 12000,
      });
      const payload = (await response.json()) as { message?: string; governance?: RunTelemetry["governance"] };
      setRunTelemetry((current) => ({
        ...(current ?? {}),
        governance: payload.governance ?? current?.governance,
      }));
      setStatusMessage(payload.message ?? "Action sent through the policy-gated action path.");
      await park.refreshParkState();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Unable to execute the selected action.");
    } finally {
      setIsDispatching(false);
    }
  }, [park, selectedAction?.action, selectedAction?.target, selectedScenarioKey]);

  const acknowledgeDispatch = useCallback(
    async (dispatch: DispatchView, choice: "approved" | "held_for_review" | "acknowledged") => {
      setIsApproving(true);
      setErrorMessage(null);
      try {
        const response = await fetchParkPulseApi("/api/park/delivery/acknowledge", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            dispatch_id: dispatch.dispatch?.id ?? dispatch.id,
            id: dispatch.dispatch?.id ?? dispatch.id,
            actor: "operator",
            choice,
            channel: dispatch.channel,
          }),
          timeoutMs: 12000,
        });
        const payload = (await response.json()) as { status?: string; state?: unknown; delivery?: RunTelemetry["delivery"] };
        if (payload.state) park.applyParkState(payload.state);
        if (payload.delivery) {
          setRunTelemetry((current) => ({ ...(current ?? {}), delivery: payload.delivery }));
        }
        setStatusMessage(`Receiver ${payload.status ?? choice}.`);
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : "Unable to update receiver acknowledgement.");
      } finally {
        setIsApproving(false);
      }
    },
    [park],
  );

  return {
    ...park,
    scenario,
    scenarios: DEMO_SCENARIOS,
    selectedScenarioKey,
    selectScenario,
    runAgent,
    executeSelectedAction,
    acknowledgeDispatch,
    runTelemetry,
    agentBriefs,
    dispatches,
    activeEvalScores,
    integrationStatus,
    selectedAction,
    policyGate,
    evalScore,
    memoryMode,
    isRunning,
    isDispatching,
    isApproving,
    statusMessage,
    errorMessage,
  };
}
