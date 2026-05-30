"use client";

import { ActualTrainingPanel } from "./ActualTrainingPanel";
import { DispatchApprovalPanel } from "./DispatchApprovalPanel";
import { EvalReceiptPanel } from "./EvalReceiptPanel";
import { ParkStateStrip } from "./ParkStateStrip";
import { ProductLoopPanel } from "./ProductLoopPanel";
import { useCommandCenter } from "./useCommandCenter";

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
              <a href="/human" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-100">
                Human view
              </a>
              <a href="/monitor" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-100">
                Monitor
              </a>
              <a href="/executive" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-100">
                Executive
              </a>
              <a href="/labs" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-400 transition hover:border-amber-400 hover:text-amber-100">
                Labs
              </a>
            </div>
          </div>
        </header>

        <ParkStateStrip
          parkState={command.parkState}
          isConnected={command.isConnected}
          isRefreshing={command.isRefreshing}
          lastUpdatedAt={command.lastUpdatedAt}
          livePollMs={command.livePollMs}
          connectionError={command.connectionError}
          onRefresh={() => void command.refreshParkState()}
        />

        {(command.statusMessage || command.errorMessage || command.connectionError) && (
          <section className="rounded-lg border border-slate-800 bg-slate-950 p-3">
            {command.statusMessage && <div className="text-sm font-bold text-cyan-100">{command.statusMessage}</div>}
            {(command.errorMessage || command.connectionError) && <div className="mt-1 text-sm font-bold text-amber-200">{command.errorMessage ?? command.connectionError}</div>}
          </section>
        )}

        <div className="space-y-5">
          <section className="rounded-lg border border-slate-800 bg-slate-950 p-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Operating loop</div>
                <h2 className="mt-1 text-xl font-black text-slate-100">Signals, features, predictors, optimizer, gate, execute or review, learn</h2>
              </div>
              <button
                type="button"
                onClick={() => void command.runAgent()}
                disabled={command.isRunning}
                className="w-fit rounded border border-cyan-300 bg-cyan-300 px-5 py-3 text-sm font-black text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {command.isRunning ? "Running loop" : "Run operating loop"}
              </button>
            </div>
          </section>

          <ProductLoopPanel
            parkState={command.parkState}
            runTelemetry={command.runTelemetry}
            dispatches={command.dispatches}
            evals={command.activeEvalScores}
            selectedAction={command.selectedAction}
            policyGate={command.policyGate}
            memoryMode={command.memoryMode}
          />
          <ActualTrainingPanel
            training={command.actualTraining}
            isLoading={command.isTrainingLoading}
            isStartingGcpTraining={command.isStartingGcpTraining}
            onRefresh={() => void command.refreshActualTraining()}
            onStartGcpTraining={() => void command.refreshActualTraining({ runGcpTraining: true })}
          />
          <DispatchApprovalPanel
            dispatches={command.dispatches}
            humanApproval={command.policyGate?.toLowerCase().includes("review") ?? false}
            isDispatching={command.isDispatching}
            isApproving={command.isApproving}
            onExecute={() => void command.executeSelectedAction()}
            onAcknowledge={(dispatch, choice) => void command.acknowledgeDispatch(dispatch, choice)}
          />
          <EvalReceiptPanel
            evals={command.activeEvalScores}
            telemetry={command.runTelemetry}
            integrationStatus={command.integrationStatus}
            evalScore={command.evalScore}
            memoryMode={command.memoryMode}
          />
        </div>
      </div>
    </main>
  );
}
