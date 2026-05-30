export type OperatingLoopStageId = "observe" | "reason" | "simulate" | "decide" | "execute" | "evaluate" | "learn";

export type OperatingLoopStageStatus = "complete" | "active" | "ready" | "blocked";

export type OperatingLoopStage = {
  id: OperatingLoopStageId;
  label: string;
  owner: string;
  status: OperatingLoopStageStatus;
  metric: string;
  title: string;
  body: string;
  evidenceTab: string;
  evidenceCount: number;
};

export type OperatingLoopViewModel = {
  headline: string;
  subtitle: string;
  selectedAction: string;
  gate: string;
  dispatchCount: number;
  evalScore: number | null;
  memoryId: string | null;
  activeStageId: OperatingLoopStageId;
  openLoop: string;
  stages: OperatingLoopStage[];
};

type AnyRecord = Record<string, any>;

export type OperatingLoopInputs = {
  parkState?: AnyRecord | null;
  activeCase?: AnyRecord | null;
  latestCopilotReceipt?: AnyRecord | null;
  activeTelemetry?: AnyRecord | null;
  operatorCommandResult?: AnyRecord | null;
  causalImpactReceipt?: AnyRecord | null;
  causalImpactTotals?: { actions?: number; guestMinutesSaved?: number; waitMinutesAvoided?: number } | null;
  runTraceEvents?: Array<AnyRecord>;
  runProgress?: string | null;
  isBusy?: boolean;
};

function numberOrNull(value: unknown): number | null {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function formatCount(value: unknown, suffix = "") {
  const numeric = numberOrNull(value);
  if (numeric == null) return "--";
  return `${numeric.toLocaleString()}${suffix}`;
}

function asArray<T = AnyRecord>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function humanize(value: unknown, fallback = "--") {
  return String(value ?? fallback).replaceAll("_", " ");
}

function getRunDelivery(telemetry?: AnyRecord | null): AnyRecord | undefined {
  return telemetry?.delivery;
}

function getRunDispatches(telemetry?: AnyRecord | null): AnyRecord[] {
  return asArray(getRunDelivery(telemetry)?.dispatches);
}

function getRunEvalScore(telemetry?: AnyRecord | null): number | null {
  const evalPayload = telemetry?.eval ?? {};
  const score = evalPayload.overall ?? evalPayload.scorecard?.overall ?? telemetry?.reasoning_evaluation?.overall;
  return numberOrNull(score);
}

function getRunGate(telemetry?: AnyRecord | null): string | undefined {
  return telemetry?.governance?.gate_status ?? telemetry?.governance?.ledger_entry?.gateStatus ?? telemetry?.eval?.scorecard?.policy_gate_status;
}

function getSelectedAction(telemetry?: AnyRecord | null): string | undefined {
  if (!telemetry) return undefined;
  const selected = telemetry.planner?.selected_action;
  return (
    telemetry.learning_proof?.after?.strategy ??
    telemetry.learned_run?.status ??
    telemetry.brief?.operator_brief ??
    telemetry.operator_response?.headline ??
    selected?.label ??
    (selected?.target || selected?.action ? `${selected?.target ?? "park"}/${selected?.action ?? "action"}` : undefined) ??
    telemetry.outcome?.state_impact?.headline
  );
}

function stageStatus(done: boolean, active: boolean, blocked = false): OperatingLoopStageStatus {
  if (blocked) return "blocked";
  if (done) return "complete";
  if (active) return "active";
  return "ready";
}

export function buildOperatingLoopViewModel({
  parkState,
  activeCase,
  latestCopilotReceipt,
  activeTelemetry,
  operatorCommandResult,
  causalImpactReceipt,
  causalImpactTotals,
  runTraceEvents = [],
  runProgress,
  isBusy = false,
}: OperatingLoopInputs): OperatingLoopViewModel {
  const displayTelemetry = latestCopilotReceipt?.run_telemetry ?? operatorCommandResult?.run_telemetry ?? activeTelemetry ?? null;
  const rides = asArray(parkState?.guestFlow?.rides);
  const zones = asArray(parkState?.guestFlow?.zones);
  const topRide = [...rides].sort((left, right) => (numberOrNull(right?.waitMins) ?? 0) - (numberOrNull(left?.waitMins) ?? 0))[0];
  const topZone = [...zones].sort((left, right) => (numberOrNull(right?.density ?? right?.densityPct) ?? 0) - (numberOrNull(left?.density ?? left?.densityPct) ?? 0))[0];
  const representedGuests = numberOrNull(parkState?.guestFlow?.representedGuests) ?? 0;
  const toolTimeline = latestCopilotReceipt?.tool_call_timeline?.length
    ? latestCopilotReceipt.tool_call_timeline
    : asArray(latestCopilotReceipt?.tool_trace?.tool_calls ?? displayTelemetry?.digital_twin_tools?.tool_calls);
  const dispatches = getRunDispatches(displayTelemetry);
  const evalScore = getRunEvalScore(displayTelemetry);
  const resolvedGate =
    latestCopilotReceipt?.recommended_action?.gate ??
    getRunGate(displayTelemetry) ??
    operatorCommandResult?.run_telemetry?.governance?.gate_status ??
    causalImpactReceipt?.selected_action?.policy_gate?.gate_status ??
    activeCase?.gate ??
    (operatorCommandResult?.route?.requires_human_review ? "human_review" : "read_only");
  const selectedAction =
    latestCopilotReceipt?.recommended_action?.label ??
    latestCopilotReceipt?.recommended_action?.action ??
    getSelectedAction(displayTelemetry) ??
    operatorCommandResult?.operator_response?.headline ??
    causalImpactReceipt?.selected_action?.label ??
    "No action selected";
  const memoryId =
    latestCopilotReceipt?.ontology_context?.audit_trail?.object_action_plan_id ??
    displayTelemetry?.trace_contract?.memory_write?.outcome_id ??
    displayTelemetry?.outcome_id ??
    causalImpactReceipt?.memory?.outcome_id ??
    null;
  const reasoningRows = latestCopilotReceipt?.reasoning_summary?.length
    ? latestCopilotReceipt.reasoning_summary
    : runTraceEvents.map((event) => event.message ?? event.label).filter(Boolean);
  const hasReasoning = Boolean(latestCopilotReceipt || operatorCommandResult || reasoningRows.length || displayTelemetry);
  const hasSimulation = Boolean(causalImpactReceipt || displayTelemetry?.digital_twin_tools || latestCopilotReceipt?.impact_replay || toolTimeline.length);
  const hasDecision = Boolean(latestCopilotReceipt || operatorCommandResult || displayTelemetry || causalImpactReceipt?.selected_action);
  const executeBlocked = humanize(resolvedGate).toLowerCase().includes("human") && dispatches.length === 0;
  const hasEvaluation = evalScore != null || Boolean(latestCopilotReceipt?.reasoning_evaluation || causalImpactReceipt?.comparison);
  const activeStageId: OperatingLoopStageId =
    isBusy
      ? hasDecision
        ? "execute"
        : hasSimulation
          ? "decide"
          : hasReasoning
            ? "simulate"
            : "reason"
      : !hasReasoning
        ? "reason"
        : !hasSimulation
          ? "simulate"
          : !hasDecision
            ? "decide"
            : !dispatches.length && !executeBlocked
              ? "execute"
              : !hasEvaluation
                ? "evaluate"
                : !memoryId
                  ? "learn"
                  : "learn";
  const isActive = (id: OperatingLoopStageId) => isBusy && activeStageId === id;

  const stages: OperatingLoopStage[] = [
    {
      id: "observe",
      label: "Observe",
      owner: "Scan agent",
      status: "complete",
      metric: representedGuests ? `${representedGuests.toLocaleString()} guests` : "live",
      title: topRide ? `${topRide.name ?? topRide.id}: ${formatCount(topRide.waitMins, "m")} wait` : "Live park state",
      body: topZone
        ? `${topZone.name ?? topZone.id} is at ${formatCount(topZone.density ?? topZone.densityPct, "%")} density.`
        : "Live park telemetry is loaded and waiting for a focused question.",
      evidenceTab: "signals",
      evidenceCount: rides.length + zones.length,
    },
    {
      id: "reason",
      label: "Reason",
      owner: "Orchestrator",
      status: stageStatus(hasReasoning, isActive("reason")),
      metric: latestCopilotReceipt?.chat_brain?.intent ?? latestCopilotReceipt?.mode ?? operatorCommandResult?.mode ?? "freeform",
      title: hasReasoning ? "Intent routed" : "Waiting for request",
      body: latestCopilotReceipt?.chat_brain?.planner_message ?? reasoningRows[0] ?? runProgress ?? "The agent has not reasoned over a fresh operator request yet.",
      evidenceTab: "trace",
      evidenceCount: reasoningRows.length,
    },
    {
      id: "simulate",
      label: "Simulate",
      owner: "Digital twin",
      status: stageStatus(hasSimulation, isActive("simulate")),
      metric: causalImpactReceipt ? `${causalImpactTotals?.guestMinutesSaved ?? 0} min saved` : `${toolTimeline.length} tools`,
      title: hasSimulation ? "Alternatives checked" : "Replay needed",
      body: latestCopilotReceipt?.impact_replay
        ? "Map replay is available for the recommended action."
        : causalImpactReceipt
          ? `${causalImpactTotals?.actions ?? 0} actions compared against baseline with ${causalImpactTotals?.waitMinutesAvoided ?? 0} wait minutes avoided.`
          : "Run an impact replay or tool-backed plan before treating the recommendation as proven.",
      evidenceTab: "twin",
      evidenceCount: toolTimeline.length,
    },
    {
      id: "decide",
      label: "Decide",
      owner: "Policy gate",
      status: stageStatus(hasDecision, isActive("decide")),
      metric: humanize(resolvedGate),
      title: selectedAction,
      body: selectedAction,
      evidenceTab: "governance",
      evidenceCount: resolvedGate ? 1 : 0,
    },
    {
      id: "execute",
      label: "Execute",
      owner: "Receivers",
      status: stageStatus(dispatches.length > 0, isActive("execute"), executeBlocked),
      metric: `${dispatches.length} dispatches`,
      title: dispatches.length ? "Receiver tasks emitted" : executeBlocked ? "Human review needed" : "No mutation yet",
      body: dispatches.length
        ? dispatches.slice(0, 2).map((item) => `${item.targetSystem ?? item.channel ?? "receiver"}: ${item.status ?? "sent"}`).join("; ")
        : executeBlocked
          ? "The loop is intentionally stopped at the review gate until an operator approves the bounded action."
          : "No receiver mutation has been sent from this loop yet.",
      evidenceTab: "approvals",
      evidenceCount: dispatches.length,
    },
    {
      id: "evaluate",
      label: "Evaluate",
      owner: "Eval layer",
      status: stageStatus(hasEvaluation, isActive("evaluate")),
      metric: evalScore != null ? `${evalScore}/100` : latestCopilotReceipt?.reasoning_evaluation?.overall ?? "pending",
      title: hasEvaluation ? "Outcome measured" : "Measurement pending",
      body:
        latestCopilotReceipt?.reasoning_evaluation?.checks?.[0]?.evidence ??
        latestCopilotReceipt?.reasoning_evaluation?.improvement_hints?.[0] ??
        causalImpactReceipt?.comparison?.impact?.headline ??
        "Evaluation appears after the action has a measurable effect or reasoning score.",
      evidenceTab: "proof",
      evidenceCount: hasEvaluation ? 1 : 0,
    },
    {
      id: "learn",
      label: "Learn",
      owner: "Memory",
      status: stageStatus(Boolean(memoryId), isActive("learn")),
      metric: memoryId ? "written" : "pending",
      title: memoryId ? "Outcome stored" : "Learning open",
      body: memoryId ? `Outcome memory ${memoryId} is available for later cases.` : "No durable outcome memory has been written by the current loop.",
      evidenceTab: "memory",
      evidenceCount: memoryId ? 1 : 0,
    },
  ];
  const current = stages.find((stage) => stage.id === activeStageId) ?? stages[0];
  const firstOpen = stages.find((stage) => stage.status !== "complete");
  const openLoop = firstOpen
    ? `${firstOpen.label}: ${firstOpen.body}`
    : "The loop is closed: live state, reasoning, action, receiver evidence, eval, and memory are connected.";

  return {
    headline: "Live park to governed action",
    subtitle: "Map first. Ask the agent. Prove the action. Measure the outcome. Carry the lesson forward.",
    selectedAction,
    gate: humanize(resolvedGate),
    dispatchCount: dispatches.length,
    evalScore,
    memoryId,
    activeStageId: current.id,
    openLoop,
    stages,
  };
}
