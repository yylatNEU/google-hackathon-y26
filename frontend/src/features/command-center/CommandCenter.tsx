"use client";

import { lazy, Suspense } from "react";
import { DecisionBriefPanel } from "./DecisionBriefPanel";
import { OperationsStoryPanel } from "./OperationsStoryPanel";
import { ParkStateStrip } from "./ParkStateStrip";
import { useCommandCenter } from "./useCommandCenter";

const LiveFeedReviewPanel = lazy(() => import("./LiveFeedReviewPanel").then((module) => ({ default: module.LiveFeedReviewPanel })));
const DispatchApprovalPanel = lazy(() => import("./DispatchApprovalPanel").then((module) => ({ default: module.DispatchApprovalPanel })));

function PanelFallback({ label }: { label: string }) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-950 p-4">
      <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
      <div className="mt-2 h-2 w-full max-w-md overflow-hidden rounded bg-slate-900">
        <div className="h-full w-1/3 rounded bg-cyan-300/70" />
      </div>
    </section>
  );
}

export function CommandCenter() {
  const command = useCommandCenter();

  return (
    <main className="min-h-screen overflow-x-hidden bg-slate-950 px-4 py-5 font-sans text-slate-200 lg:px-8">
      <div className="mx-auto max-w-[1500px] space-y-5">
        <header className="rounded-lg border border-cyan-400/20 bg-slate-900 p-5 shadow-xl shadow-cyan-950/20">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">ParkPulse AI</div>
              <h1 className="mt-2 max-w-5xl text-3xl font-black tracking-normal text-slate-100 lg:text-5xl">Park operating loop</h1>
              <p className="mt-3 max-w-3xl text-sm leading-relaxed text-slate-400">
                Watch live runtime signals become features, let ML predictors and an optimizer propose actions, then route the result through policy, eval, dispatch, review, and outcome learning.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <a href="/ops-agent" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-cyan-100 transition hover:border-cyan-300">
                Ops Agent
              </a>
              <a href="/monitor" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-100">
                Monitor
              </a>
              <a href="/operation-proof" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-cyan-100 transition hover:border-cyan-300">
                Runtime proof
              </a>
              <a href="/executive" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-100">
                Executive
              </a>
              <a href="/" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-300 transition hover:border-white hover:text-cyan-100">
                All modules
              </a>
            </div>
          </div>
        </header>

        <ParkStateStrip
          parkState={command.parkState}
          isConnected={command.isConnected}
          isRefreshing={command.isRefreshing}
          lastUpdatedAt={command.lastUpdatedAt}
          liveTick={command.liveTick}
          livePollMs={command.livePollMs}
          connectionError={command.connectionError}
          isLiveLoopRunning={command.isLiveLoopRunning}
          onRefresh={() => void command.refreshParkState()}
          onStartLiveLoop={command.startLiveLoop}
          onStopLiveLoop={command.stopLiveLoop}
        />

        <OperationsStoryPanel
          parkState={command.parkState}
          runTelemetry={command.runTelemetry}
          selectedAction={command.selectedAction}
          policyGate={command.policyGate}
          evalScore={command.evalScore}
          dispatches={command.dispatches}
          actualTraining={command.actualTraining}
          liveFeedHealth={command.liveFeedHealth}
          feedReliabilityGate={command.feedReliabilityGate}
          autopilotDecision={command.autopilotDecision}
          isAutopilotEnabled={command.isAutopilotEnabled}
          isAutopilotRunning={command.isAutopilotRunning}
          isRunning={command.isRunning}
          onSetAutopilotEnabled={command.setAutopilotEnabled}
          onRunAutopilot={() => void command.runAutopilotCycle()}
          onRunIncidentReview={() => void command.runAgent({ injectUnexpectedEvent: true })}
          onRunLiveFeedCase={() => void command.runLiveFeedAgent()}
          onRunNegotiationCase={() => void command.runDepartmentNegotiationDemo()}
        />

        <Suspense fallback={<PanelFallback label="Loading live feed review" />}>
          <LiveFeedReviewPanel
            health={command.liveFeedHealth}
            ledger={command.reviewTrainingLedger}
            isLoading={command.isLiveFeedHealthLoading}
            isAutoRecovering={command.isAutoRecoveringLiveFeeds}
            weatherLoad={command.liveWeatherLoad}
            rideOpsLoad={command.liveRideOpsLoad}
            guestFlowLoad={command.liveGuestFlowLoad}
            staffingLoad={command.liveStaffingLoad}
            foodOpsLoad={command.liveFoodOpsLoad}
            operatorSignalLoad={command.liveOperatorSignalLoad}
            refreshSupervisor={command.liveFeedRefreshSupervisor}
            reliabilityGate={command.feedReliabilityGate}
            onRefresh={() => void command.refreshLiveFeedHealth()}
            onRefreshStale={() => void command.refreshStaleLiveFeeds()}
            onReviewDecision={(caseId, decision) => void command.recordReviewDecision(caseId, decision)}
            canManageFeeds={command.canManageFeeds}
            canReviewCases={command.canReviewCases}
          />
        </Suspense>

        <DecisionBriefPanel
          runTelemetry={command.runTelemetry}
          selectedAction={command.selectedAction}
          policyGate={command.policyGate}
          evalScore={command.evalScore}
          evals={command.activeEvalScores}
          dispatches={command.dispatches}
          liveFeedHealth={command.liveFeedHealth}
          isRunning={command.isRunning}
          statusMessage={command.statusMessage}
          errorMessage={command.errorMessage ?? command.connectionError}
          autopilotDecision={command.autopilotDecision}
          isAutopilotEnabled={command.isAutopilotEnabled}
          isAutopilotRunning={command.isAutopilotRunning}
          feedReliabilityGate={command.feedReliabilityGate}
        />

        {(command.statusMessage || command.errorMessage || command.connectionError) && (
          <section className="rounded-lg border border-slate-800 bg-slate-950 p-3">
            {command.statusMessage && <div className="text-sm font-bold text-cyan-100">{command.statusMessage}</div>}
            {(command.errorMessage || command.connectionError) && <div className="mt-1 text-sm font-bold text-amber-200">{command.errorMessage ?? command.connectionError}</div>}
          </section>
        )}

        <div className="space-y-5">
          <Suspense fallback={<PanelFallback label="Loading dispatch controls" />}>
            <DispatchApprovalPanel
              dispatches={command.dispatches}
              humanApproval={command.policyGate?.toLowerCase().includes("review") ?? false}
              isDispatching={command.isDispatching}
              isApproving={command.isApproving}
              onExecute={() => void command.executeSelectedAction()}
              onAcknowledge={(dispatch, choice) => void command.acknowledgeDispatch(dispatch, choice)}
              canExecute={command.canExecute}
              canAcknowledge={command.canAcknowledge}
            />
          </Suspense>
        </div>
      </div>
    </main>
  );
}
