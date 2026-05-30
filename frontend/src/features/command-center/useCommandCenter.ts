"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParkPulseState } from "@/hooks/useParkPulseState";
import { fetchParkPulseApi, longRunningRequestTimeoutMs } from "@/lib/api";
import { agentBriefsFromRuntime } from "@/lib/parkPulseAgents";
import type { AgentBrief, DeliveryDispatch, EvalScore, IntegrationStatus, RunTelemetry } from "@/types/platform";

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
  source: "runtime";
  dispatch?: DeliveryDispatch;
};

export type ActualTrainingStatus = {
  status?: string;
  mode?: string;
  uses_generated_data?: boolean;
  source?: string;
  sample_count?: number;
  min_sample_count?: number;
  model?: {
    type?: string;
    update_rule?: string;
    best_policy_id?: string | null;
    ranked_policies?: Array<{ policy_id?: string; sample_count?: number; average_reward?: number; best_reward?: number; latest_reward?: number }>;
    context_values?: Array<{ context?: string; ranked_policies?: Array<{ policy_id?: string; q_value?: number; sample_count?: number }> }>;
    authority?: string;
  };
  gcp_ml?: {
    online_improvement?: { ready?: boolean; mode?: string; readiness_issues?: string[] };
    bigquery?: { ready?: boolean; project?: string; dataset?: string; readiness_issues?: string[] };
    bigquery_ml_training?: {
      status?: string;
      enabled?: boolean;
      tool?: string;
      model_id?: string | null;
      job_id?: string | null;
      start_condition?: string;
      readiness_issues?: string[];
    };
  };
  episode_fitness?: {
    status?: string;
    mode?: string;
    uses_generated_data?: boolean;
    sample_count?: number;
    average_reward_delta?: number;
    average_pressure_reduction?: number;
    improvement_rate?: number;
    latest_episode?: {
      id?: string;
      source?: string;
      scenario_key?: string;
      action?: { target?: string; action?: string };
      scores?: { actual?: number; baseline?: number; reward_delta?: number; fitness?: number };
      pressure?: { reduction_vs_baseline?: number; reduced_pressure?: boolean };
      active_random_incidents?: Array<{ kind?: string; intensity?: number }>;
    } | null;
  };
  debug?: {
    readiness_issues?: string[];
    memory_rows_available?: number;
    bigquery_rows_available?: number;
  };
};

function normalizeRunTelemetry(payload: RunPayload): RunTelemetry {
  return payload.run_telemetry ?? payload;
}

function runtimeDispatchBody(dispatch: DeliveryDispatch) {
  const payload = dispatch.payload;
  if (!payload || typeof payload !== "object") return "Runtime payload body missing.";
  if (typeof payload.message === "string") return payload.message;
  if (typeof payload.task === "string") return payload.task;
  if (typeof payload.command === "string") return payload.command;
  if (typeof payload.promotion?.offer === "string") return payload.promotion.offer;
  return JSON.stringify(payload);
}

function normalizeDispatch(dispatch: DeliveryDispatch, index: number): DispatchView {
  return {
    id: dispatch.id ?? `runtime-dispatch-${index}`,
    channel: dispatch.channel ?? dispatch.targetSystem ?? "receiver",
    target: dispatch.payload?.targetZone ?? dispatch.targetSystem ?? dispatch.endpoint ?? "operations receiver",
    body: runtimeDispatchBody(dispatch),
    status: dispatch.approvalDecision?.decision ?? dispatch.lastAcknowledgement?.choice ?? dispatch.status,
    source: "runtime",
    dispatch,
  };
}

export function useCommandCenter() {
  const park = useParkPulseState();
  const [runTelemetry, setRunTelemetry] = useState<RunTelemetry | null>(null);
  const [integrationStatus, setIntegrationStatus] = useState<IntegrationStatus | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [isDispatching, setIsDispatching] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [isTrainingLoading, setIsTrainingLoading] = useState(false);
  const [isStartingGcpTraining, setIsStartingGcpTraining] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [actualTraining, setActualTraining] = useState<ActualTrainingStatus | null>(null);

  const activeEvalScores = useMemo<EvalScore[]>(() => {
    const scorecard = runTelemetry?.eval?.scorecard;
    const dimensions = runTelemetry?.eval?.dimension_scores;
    if (dimensions) {
      return Object.entries(dimensions).map(([label, score]) => ({
        label,
        score,
        detail: runTelemetry?.eval?.dimension_explanations?.[label] ?? "Runtime evaluator dimension.",
      }));
    }
    if (scorecard?.overall !== undefined) {
      return [{ label: "Overall runtime eval", score: scorecard.overall, detail: scorecard.status ?? "Runtime scorecard." }];
    }
    return [];
  }, [runTelemetry?.eval]);

  const agentBriefs: AgentBrief[] = useMemo(() => {
    return agentBriefsFromRuntime(runTelemetry?.agent_findings);
  }, [runTelemetry?.agent_findings]);

  const dispatches: DispatchView[] = useMemo(() => {
    const runtimeDispatches = runTelemetry?.delivery?.dispatches ?? [];
    return runtimeDispatches.map(normalizeDispatch);
  }, [runTelemetry?.delivery?.dispatches]);

  const selectedAction = runTelemetry?.planner?.selected_action;
  const policyGate = runTelemetry?.governance?.gate_status;
  const evalScore = runTelemetry?.eval?.scorecard?.overall;
  const memoryMode = runTelemetry?.memory?.mode ?? integrationStatus?.mongo?.mode ?? "unavailable";

  const refreshIntegrationStatus = useCallback(async () => {
    try {
      const response = await fetchParkPulseApi("/api/park/integration-status", { timeoutMs: 5000 });
      setIntegrationStatus((await response.json()) as IntegrationStatus);
    } catch {
      setIntegrationStatus(null);
    }
  }, []);

  const refreshActualTraining = useCallback(async (options?: { runGcpTraining?: boolean }) => {
    const runGcpTraining = options?.runGcpTraining === true;
    setIsTrainingLoading(true);
    if (runGcpTraining) {
      setIsStartingGcpTraining(true);
      setErrorMessage(null);
      setStatusMessage("Starting BigQuery ML training from observed outcome rows.");
    }
    try {
      const response = await fetchParkPulseApi(runGcpTraining ? "/api/park/actual-training?runGcpTraining=true" : "/api/park/actual-training", {
        timeoutMs: longRunningRequestTimeoutMs,
      });
      const payload = (await response.json()) as ActualTrainingStatus;
      setActualTraining(payload);
      if (runGcpTraining) {
        const bqml = payload.gcp_ml?.bigquery_ml_training;
        setStatusMessage(
          bqml?.status === "started"
            ? `BigQuery ML training started${bqml.job_id ? `: ${bqml.job_id}` : "."}`
            : `BigQuery ML training ${bqml?.status ?? payload.status ?? "not ready"}.`,
        );
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Actual training status failed.";
      setActualTraining({
        status: "error",
        mode: "actual_outcome_training",
        uses_generated_data: false,
        source: "none",
        sample_count: 0,
        debug: { readiness_issues: [message] },
      });
      if (runGcpTraining) setErrorMessage(message);
    } finally {
      setIsTrainingLoading(false);
      if (runGcpTraining) setIsStartingGcpTraining(false);
    }
  }, []);

  useEffect(() => {
    void refreshIntegrationStatus();
    void refreshActualTraining();
  }, [refreshActualTraining, refreshIntegrationStatus]);

  const runAgent = useCallback(async () => {
    setIsRunning(true);
    setErrorMessage(null);
    setStatusMessage("Running feature extraction, prediction, optimization, policy gate, explanation, dispatch draft, and eval receipt.");
    try {
      const activeScenario = park.parkState.guestFlow.activeScenario;
      const response = await fetchParkPulseApi("/api/park/agent-run", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          scenario_key: activeScenario.key || undefined,
          operation_mode: false,
          auto_unexpected_event: false,
          operator_message: activeScenario.description || activeScenario.name || "Run the current live park operating loop.",
          execute: true,
        }),
        timeoutMs: longRunningRequestTimeoutMs,
      });
      const payload = (await response.json()) as RunPayload;
      const telemetry = normalizeRunTelemetry(payload);
      setRunTelemetry(telemetry);
      setStatusMessage(telemetry.operator_response?.headline ?? "Operating loop complete. Receipt is ready for review.");
      await park.refreshParkState();
      void refreshIntegrationStatus();
      void refreshActualTraining();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Unable to run the ParkPulse agent.");
      setStatusMessage(null);
    } finally {
      setIsRunning(false);
    }
  }, [park, refreshActualTraining, refreshIntegrationStatus]);

  const executeSelectedAction = useCallback(async () => {
    setIsDispatching(true);
    setErrorMessage(null);
    if (!selectedAction?.action || !selectedAction.target) {
      setErrorMessage("No runtime-selected action is available. Run the operating loop first.");
      setIsDispatching(false);
      return;
    }
    const action = { target: selectedAction.target, action: selectedAction.action };
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
      void refreshActualTraining();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Unable to execute the selected action.");
    } finally {
      setIsDispatching(false);
    }
  }, [park, refreshActualTraining, selectedAction?.action, selectedAction?.target]);

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
        void refreshActualTraining();
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : "Unable to update receiver acknowledgement.");
      } finally {
        setIsApproving(false);
      }
    },
    [park, refreshActualTraining],
  );

  return {
    ...park,
    runAgent,
    executeSelectedAction,
    acknowledgeDispatch,
    runTelemetry,
    agentBriefs,
    dispatches,
    activeEvalScores,
    integrationStatus,
    actualTraining,
    selectedAction,
    policyGate,
    evalScore,
    memoryMode,
    isRunning,
    isDispatching,
    isApproving,
    isTrainingLoading,
    isStartingGcpTraining,
    statusMessage,
    errorMessage,
    refreshActualTraining,
  };
}
