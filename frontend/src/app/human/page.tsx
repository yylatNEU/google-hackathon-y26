"use client";

import { useMemo, useState } from "react";
import { useParkPulseState } from "@/hooks/useParkPulseState";
import { fetchParkPulseApi } from "@/lib/api";

type AgentMode = "auto" | "scan" | "react" | "proact";

type HumanRun = {
  status?: string;
  selected_role?: string;
  route?: {
    selected_role?: string;
    why?: string;
    required_tools?: string[];
    policy_gates?: string[];
    expected_receipt?: string[];
  };
  role_route?: HumanRun["route"];
  operator_response?: {
    headline?: string;
    summary?: string;
    next_step?: string;
  };
  run_telemetry?: {
    decision_id?: string;
    planner?: {
      runtime?: string;
      model?: string;
      selected_action?: { label?: string; target?: string; action?: string; owner?: string };
    };
    governance?: { allowed?: boolean; gate_status?: string; findings?: string[] };
    eval?: { scorecard?: { overall?: number; response_score?: number; policy_gate_status?: string; needs_human_approval?: boolean } };
    delivery?: {
      summary?: { total?: number; sent?: number; acknowledged?: number; pending_operator_approval?: number };
      dispatches?: Array<{
        id?: string;
        channel?: string;
        target?: string;
        status?: string;
        message?: string;
        payload?: { message?: string; task?: string; command?: string };
      }>;
    };
  };
  digital_twin_tools?: {
    tool_count?: number;
    tool_calls?: Array<{ tool?: string; capability?: string; status?: string; output?: unknown }>;
    summary?: { policy_gates?: string[]; receipt_artifacts?: string[] };
  };
  scan?: {
    top_risk?: string;
    confidence?: number;
    recommended_next_role?: string;
    signals?: Array<{ summary?: string; confidence?: number; risk_level?: string }>;
  };
};

type SignalIntake = {
  status?: string;
  signal?: {
    text?: string;
    source?: string;
    categories?: string[];
    risk_level?: string;
    confidence?: number;
    human_approval_required?: boolean;
    recommended_actions?: Array<{ owner?: string; action?: string; deadline_minutes?: number }>;
    missing_info?: string[];
  };
};

const AGENT_MODES: Array<{ id: AgentMode; label: string; detail: string }> = [
  { id: "auto", label: "Auto route", detail: "Let the runtime router choose scan, react, or proact." },
  { id: "scan", label: "Scan", detail: "Classify live signals before planning." },
  { id: "react", label: "React", detail: "Respond to a known operator incident." },
  { id: "proact", label: "Proact", detail: "Look ahead for weak signals before escalation." },
];

function pct(value?: number) {
  if (typeof value !== "number") return "--";
  return `${Math.round(value * 100)}%`;
}

function score(value?: number) {
  return typeof value === "number" ? `${Math.round(value)}/100` : "--";
}

function short(value?: string | null) {
  const text = value?.trim();
  if (!text) return "--";
  return text.length > 130 ? `${text.slice(0, 127)}...` : text;
}

function dispatchMessage(dispatch: NonNullable<HumanRun["run_telemetry"]>["delivery"] extends infer Delivery ? Delivery extends { dispatches?: Array<infer Dispatch> } ? Dispatch : never : never) {
  return dispatch.message ?? dispatch.payload?.message ?? dispatch.payload?.task ?? dispatch.payload?.command ?? "Runtime payload body missing.";
}

export default function HumanEnhancementPage() {
  const { parkState, isConnected, isRefreshing, connectionError, refreshParkState } = useParkPulseState();
  const [employeeText, setEmployeeText] = useState("");
  const [agentMode, setAgentMode] = useState<AgentMode>("auto");
  const [isRunning, setIsRunning] = useState(false);
  const [run, setRun] = useState<HumanRun | null>(null);
  const [signal, setSignal] = useState<SignalIntake | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [operatorDecision, setOperatorDecision] = useState<"approved" | "held" | "edited" | null>(null);

  const flow = parkState.guestFlow;
  const telemetry = run?.run_telemetry;
  const route = run?.role_route ?? run?.route;
  const dispatches = telemetry?.delivery?.dispatches ?? [];
  const selectedAction = telemetry?.planner?.selected_action;
  const evalScore = telemetry?.eval?.scorecard?.overall;
  const toolCalls = run?.digital_twin_tools?.tool_calls ?? [];

  const topRide = useMemo(
    () => [...(flow.rides ?? [])].sort((left, right) => right.waitMins + right.queueGuests / 20 - (left.waitMins + left.queueGuests / 20))[0],
    [flow.rides],
  );
  const topZone = useMemo(() => [...(flow.zones ?? [])].sort((left, right) => right.density - left.density)[0], [flow.zones]);
  const highestPath = useMemo(() => [...(flow.paths ?? [])].sort((left, right) => right.congestionLevel - left.congestionLevel)[0], [flow.paths]);

  const runtimeFacts = [
    ["Feed", isConnected ? "live" : "disconnected"],
    ["Peak zone", topZone ? `${topZone.name} ${topZone.density}%` : "--"],
    ["Top ride", topRide ? `${topRide.name} ${topRide.waitMins}m` : "--"],
    ["Path pressure", highestPath ? `${highestPath.from} to ${highestPath.to}` : "--"],
    ["Staff", parkState.staffing.scheduled ? `${parkState.staffing.checkedIn}/${parkState.staffing.scheduled}` : "--"],
  ];

  const reasoningRows = [
    {
      label: "Interpret",
      body: signal?.signal?.categories?.length ? `${signal.signal.risk_level ?? "risk"}: ${signal.signal.categories.join(", ")}` : "Waiting for signal intake receipt.",
      status: signal ? "done" : isRunning ? "active" : "waiting",
    },
    {
      label: "Live context",
      body: topZone || topRide ? `${topZone?.name ?? "No zone"} ${topZone?.density ?? "--"}%; ${topRide?.name ?? "no ride"} ${topRide?.waitMins ?? "--"}m.` : "Waiting for live park state.",
      status: isConnected ? "done" : "waiting",
    },
    {
      label: "Route",
      body: route?.selected_role ? `${route.selected_role}: ${route.why ?? "runtime route selected"}` : "Waiting for role router.",
      status: route ? "done" : isRunning ? "active" : "waiting",
    },
    {
      label: "Gate",
      body: telemetry?.governance?.gate_status ?? "Waiting for policy gate.",
      status: telemetry?.governance ? "done" : isRunning ? "active" : "waiting",
    },
    {
      label: "Emit",
      body: selectedAction?.label ?? selectedAction?.action ?? "Waiting for selected action.",
      status: selectedAction || dispatches.length ? "done" : isRunning ? "active" : "waiting",
    },
  ];

  const receiptStats = [
    ["Mode", AGENT_MODES.find((mode) => mode.id === agentMode)?.label ?? "Auto"],
    ["Role", run?.selected_role ?? route?.selected_role ?? "--"],
    ["Gate", telemetry?.governance?.gate_status ?? "--"],
    ["Eval", score(evalScore)],
    ["Dispatches", String(dispatches.length || "--")],
    ["Trace", telemetry?.decision_id ? "saved" : toolCalls.length ? `${toolCalls.length} tools` : "--"],
  ];

  const runHumanAgent = async () => {
    setIsRunning(true);
    setError(null);
    setOperatorDecision(null);
    setRun(null);
    setSignal(null);
    try {
      const signalResponse = await fetchParkPulseApi("/api/park/signals/intake", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: employeeText, source: "employee_text", reporterRole: "frontline_employee" }),
        timeoutMs: 8000,
      });
      setSignal((await signalResponse.json()) as SignalIntake);

      const runResponse = await fetchParkPulseApi("/api/park/agent-role-run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: employeeText, mode: agentMode }),
        timeoutMs: 12000,
      });
      setRun((await runResponse.json()) as HumanRun);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to convert operator text into runtime actions.");
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <main className="min-h-screen bg-slate-950 px-4 py-5 font-sans text-slate-200 lg:px-8">
      <div className="mx-auto max-w-[1500px] space-y-5">
        <header className="rounded-lg border border-slate-800 bg-slate-900 p-5">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Human review queue</div>
              <h1 className="mt-2 text-3xl font-black text-slate-100 lg:text-4xl">Operator text to policy-gated receipt</h1>
              <p className="mt-3 max-w-4xl text-sm leading-relaxed text-slate-400">
                This view accepts current operator text, reads live park state, routes the request through the runtime agent, and shows only receipts returned by the API.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <a href="/" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-100">
                Operating loop
              </a>
              <a href="/staff-training" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-teal-100 transition hover:border-teal-300">
                Staff trainer
              </a>
              <a href="/monitor" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-100">
                Monitor
              </a>
              <a href="/executive" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-100">
                Executive
              </a>
            </div>
          </div>
        </header>

        <section className="grid gap-2 md:grid-cols-5">
          {runtimeFacts.map(([label, value]) => (
            <div key={label} className="rounded border border-slate-800 bg-slate-900 p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
              <div className="mt-1 truncate text-sm font-black text-cyan-100">{value}</div>
            </div>
          ))}
        </section>

        {connectionError && (
          <section className="rounded border border-amber-400/30 bg-amber-950/15 p-3 text-sm font-bold text-amber-100">
            Runtime debug: {connectionError}
          </section>
        )}

        <section className="grid gap-5 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
          <div className="space-y-5">
            <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
              <div className="text-[10px] font-black uppercase tracking-widest text-emerald-300">1. Operator input</div>
              <textarea
                value={employeeText}
                onChange={(event) => setEmployeeText(event.target.value)}
                placeholder="Describe the live issue, field observation, or manager request."
                className="mt-3 h-36 w-full resize-none rounded border border-slate-700 bg-slate-950 p-3 text-sm leading-relaxed text-slate-100 outline-none transition placeholder:text-slate-600 focus:border-cyan-300"
              />

              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {AGENT_MODES.map((mode) => (
                  <button
                    key={mode.id}
                    type="button"
                    onClick={() => setAgentMode(mode.id)}
                    className={`rounded border px-3 py-2 text-left transition ${
                      agentMode === mode.id ? "border-cyan-300 bg-cyan-300 text-slate-950" : "border-slate-700 bg-slate-950 text-slate-300 hover:border-cyan-400"
                    }`}
                  >
                    <div className="text-xs font-black">{mode.label}</div>
                    <div className={`mt-1 text-[10px] font-bold ${agentMode === mode.id ? "text-slate-700" : "text-slate-500"}`}>{mode.detail}</div>
                  </button>
                ))}
              </div>

              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => void runHumanAgent()}
                  disabled={isRunning || !employeeText.trim()}
                  className="rounded bg-emerald-300 px-5 py-3 text-sm font-black text-slate-950 transition hover:bg-emerald-200 disabled:bg-slate-700 disabled:text-slate-400"
                >
                  {isRunning ? "Running runtime agent" : "Run runtime agent"}
                </button>
                <button
                  type="button"
                  onClick={() => void refreshParkState()}
                  disabled={isRefreshing}
                  className="rounded border border-slate-700 bg-slate-950 px-4 py-3 text-sm font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-100 disabled:opacity-50"
                >
                  {isRefreshing ? "Refreshing" : "Refresh state"}
                </button>
              </div>

              {error && <div className="mt-3 rounded border border-red-500/30 bg-red-950/20 p-3 text-xs text-red-100">{error}</div>}
            </section>

            <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
              <div className="text-[10px] font-black uppercase tracking-widest text-violet-300">2. Runtime path</div>
              <div className="mt-3 grid gap-2">
                {reasoningRows.map((row, index) => (
                  <div key={row.label} className="grid grid-cols-[1.4rem_1fr] gap-2 rounded border border-slate-800 bg-slate-950 p-2">
                    <div
                      className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-black ${
                        row.status === "done" ? "bg-emerald-300 text-slate-950" : row.status === "active" ? "bg-cyan-300 text-slate-950" : "bg-slate-800 text-slate-500"
                      }`}
                    >
                      {index + 1}
                    </div>
                    <div>
                      <div className="text-xs font-black text-slate-100">{row.label}</div>
                      <div className="mt-1 text-[11px] leading-relaxed text-slate-500">{row.body}</div>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          </div>

          <div className="space-y-5">
            <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">3. Manager receipt</div>
                  <h2 className="mt-1 text-xl font-black text-slate-100">{run?.operator_response?.headline ?? "No runtime receipt yet"}</h2>
                  <p className="mt-2 text-sm leading-relaxed text-slate-400">
                    {run?.operator_response?.summary ?? "Run the agent to create a traceable policy-gated receipt from current operator text and live state."}
                  </p>
                </div>
                <div className="flex gap-2">
                  {(["approved", "held", "edited"] as const).map((decision) => (
                    <button
                      key={decision}
                      type="button"
                      onClick={() => setOperatorDecision(decision)}
                      disabled={!run}
                      className={`rounded border px-3 py-2 text-xs font-black transition ${
                        operatorDecision === decision ? "border-emerald-300 bg-emerald-300 text-slate-950" : "border-slate-700 bg-slate-950 text-slate-300 hover:border-emerald-300"
                      } disabled:opacity-40`}
                    >
                      {decision}
                    </button>
                  ))}
                </div>
              </div>

              <div className="mt-4 grid gap-2 md:grid-cols-6">
                {receiptStats.map(([label, value]) => (
                  <div key={label} className="rounded border border-slate-800 bg-slate-950 p-3">
                    <div className="text-[9px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                    <div className="mt-1 truncate text-sm font-black text-cyan-100">{value}</div>
                  </div>
                ))}
              </div>

              <div className="mt-4 grid gap-3 md:grid-cols-2">
                {dispatches.length ? (
                  dispatches.slice(0, 6).map((dispatch, index) => (
                    <div key={dispatch.id ?? `${dispatch.channel}-${index}`} className="rounded border border-slate-800 bg-slate-950 p-3">
                      <div className="flex items-center justify-between gap-2">
                        <div className="truncate text-sm font-black text-slate-100">{dispatch.channel ?? "receiver"}</div>
                        <div className="rounded bg-slate-900 px-2 py-1 text-[10px] font-black uppercase text-emerald-300">{dispatch.status ?? "status missing"}</div>
                      </div>
                      <p className="mt-2 line-clamp-4 text-xs leading-relaxed text-slate-400">{dispatchMessage(dispatch)}</p>
                      <div className="mt-2 truncate text-[10px] font-black uppercase tracking-widest text-slate-500">{dispatch.target ?? "target missing"}</div>
                    </div>
                  ))
                ) : (
                  <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs leading-relaxed text-slate-500 md:col-span-2">
                    Runtime dispatch payloads will appear here after the API returns a delivery receipt.
                  </div>
                )}
              </div>
            </section>

            <section className="grid gap-5 lg:grid-cols-2">
              <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
                <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Signal receipt</div>
                <div className="mt-3 grid gap-2">
                  {[
                    ["Status", signal?.status ?? "--"],
                    ["Risk", signal?.signal?.risk_level ?? "--"],
                    ["Confidence", pct(signal?.signal?.confidence)],
                    ["Categories", signal?.signal?.categories?.join(", ") ?? "--"],
                    ["Missing info", signal?.signal?.missing_info?.slice(0, 2).join("; ") ?? "none"],
                  ].map(([label, value]) => (
                    <div key={label} className="grid grid-cols-[6.5rem_1fr] gap-2 rounded border border-slate-800 bg-slate-950 px-3 py-2 text-xs">
                      <div className="font-black uppercase tracking-widest text-slate-500">{label}</div>
                      <div className="font-bold text-slate-100">{value}</div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
                <div className="text-[10px] font-black uppercase tracking-widest text-violet-300">Trace tools</div>
                <div className="mt-3 grid gap-2">
                  {toolCalls.length ? (
                    toolCalls.slice(0, 7).map((call, index) => (
                      <div key={`${call.tool}-${index}`} className="grid grid-cols-[1fr_auto] gap-3 rounded border border-slate-800 bg-slate-950 px-3 py-2 text-xs">
                        <div className="truncate font-black text-slate-100">{call.tool?.replaceAll("_", " ") ?? "tool missing"}</div>
                        <div className="text-slate-500">{call.status ?? call.capability ?? "status missing"}</div>
                      </div>
                    ))
                  ) : (
                    <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs text-slate-500">No runtime tool trace yet.</div>
                  )}
                </div>
                <div className="mt-3 rounded border border-slate-800 bg-slate-950 p-3 text-xs leading-relaxed text-slate-400">
                  Decision ID: <span className="font-mono text-slate-200">{telemetry?.decision_id ?? "--"}</span>
                  {" / "}Response: <span className="font-black text-cyan-200">{score(telemetry?.eval?.scorecard?.response_score)}</span>
                </div>
              </div>
            </section>
          </div>
        </section>
      </div>
    </main>
  );
}
