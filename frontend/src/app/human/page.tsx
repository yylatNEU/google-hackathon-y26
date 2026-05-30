"use client";

import { useMemo, useState } from "react";
import { useParkPulseState } from "@/hooks/useParkPulseState";
import { fetchParkPulseApi } from "@/lib/api";
import { DEMO_SCENARIOS } from "@/lib/parkPulseDemoContent";
import { VisualParkBoard } from "@/components/ParkPulseMap";
import type { MapLayer, MapSelection } from "@/components/ParkPulseMap";

type AgentMode = "auto" | "scan" | "react" | "proact";

type HumanRun = {
  status?: string;
  selected_role?: string;
  skill?: string;
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
    scenario_key?: string;
    planner?: {
      runtime?: string;
      model?: string;
      gemini_ready?: boolean;
      selected_action?: { label?: string; target?: string; action?: string };
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
  execution?: unknown;
};

const EXAMPLES = [
  "Food Court A pickup line is spilling into the midway and mobile orders are getting angry.",
  "Smoke smell near the fog machine by the maze exit, guests are still walking past it.",
  "A guest fainted near Food Court A and wheelchair access is getting blocked.",
  "Dragon Coaster queue is not moving and guests are pushing toward the shade path.",
];

const AGENT_MODES: Array<{ id: AgentMode; label: string; detail: string }> = [
  { id: "auto", label: "Auto route", detail: "LLM chooses scan, react, or proact" },
  { id: "scan", label: "Scan", detail: "Read state and classify risk" },
  { id: "react", label: "React", detail: "Turn incident into bounded action" },
  { id: "proact", label: "Proact", detail: "Look ahead and prevent escalation" },
];

function pct(value?: number) {
  if (typeof value !== "number") return "--";
  return `${Math.round(value * 100)}%`;
}

function score(value?: number) {
  return typeof value === "number" ? `${Math.round(value)}/100` : "--";
}

function dispatchMessage(dispatch: any) {
  const item = dispatch as { message?: string; action?: string; payload?: { message?: string; task?: string; command?: string } };
  return item.message ?? item.payload?.message ?? item.payload?.task ?? item.payload?.command ?? item.action ?? "Bounded action prepared.";
}

function scenarioForText(text: string): keyof typeof DEMO_SCENARIOS {
  const value = text.toLowerCase();
  if (/(food|kitchen|mobile order|pickup|restaurant)/.test(value)) return "food_spike";
  if (/(staff|worker|break|callout|called out|coverage)/.test(value)) return "staff_shortage";
  if (/(storm|lightning|heat|shelter|hvac|weather|indoor)/.test(value)) return "storm_response";
  return "ride_down";
}

function short(value?: string | null, fallback = "--") {
  const text = value?.trim();
  if (!text) return fallback;
  return text.length > 120 ? `${text.slice(0, 117)}...` : text;
}

export default function HumanEnhancementPage() {
  const { parkState, isConnected } = useParkPulseState();
  const [employeeText, setEmployeeText] = useState(EXAMPLES[0]);
  const [agentMode, setAgentMode] = useState<AgentMode>("auto");
  const [selectedMapItem, setSelectedMapItem] = useState<MapSelection | null>(null);
  const [mapLayer, setMapLayer] = useState<MapLayer>("overview");
  const [showMapLabels, setShowMapLabels] = useState(true);
  const [showMapDetails, setShowMapDetails] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [run, setRun] = useState<HumanRun | null>(null);
  const [signal, setSignal] = useState<SignalIntake | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [operatorDecision, setOperatorDecision] = useState<"approved" | "held" | "edited" | null>(null);

  const flow = parkState.guestFlow;
  const topRide = [...(flow.rides ?? [])].sort((left, right) => right.waitMins + right.queueGuests / 20 - (left.waitMins + left.queueGuests / 20))[0];
  const topZone = [...(flow.zones ?? [])].sort((left, right) => right.density - left.density)[0];
  const scenario = DEMO_SCENARIOS[scenarioForText(employeeText)];
  const route = run?.role_route ?? run?.route;
  const telemetry = run?.run_telemetry;
  const dispatches = telemetry?.delivery?.dispatches ?? [];
  const fallbackActions = signal?.signal?.recommended_actions ?? [];
  const actions = dispatches.length ? dispatches : fallbackActions;
  const toolCalls = run?.digital_twin_tools?.tool_calls ?? [];
  const selectedAction = telemetry?.planner?.selected_action;
  const evalScore = telemetry?.eval?.scorecard?.overall;
  const selectedPlaceActions = selectedMapItem?.actions.slice(0, 3) ?? ["Reduce pressure", "Send staff", "Message guests"];

  const reasoningRows = useMemo(() => {
    const place = selectedMapItem ? `${selectedMapItem.title} (${selectedMapItem.kind})` : topZone ? `${topZone.name} live pressure` : "whole park";
    const categories = signal?.signal?.categories?.join(", ");
    const risk = signal?.signal?.risk_level ?? run?.scan?.top_risk ?? "not classified";
    const options = actions.length
      ? `${actions.length} bounded action${actions.length === 1 ? "" : "s"} prepared`
      : selectedPlaceActions.join(" / ");
    return [
      {
        label: "Interpret",
        body: categories ? `${risk}: ${categories}` : `Read plain text against ${place}.`,
        status: signal ? "done" : isRunning ? "active" : "ready",
      },
      {
        label: "Context",
        body: selectedMapItem
          ? `${selectedMapItem.status}; ${selectedMapItem.guests ?? "--"} guests; ${selectedMapItem.waitMins ?? "--"}m wait.`
          : `${topRide?.name ?? "Top ride"} ${topRide?.waitMins ?? "--"}m; ${topZone?.name ?? "peak zone"} ${topZone?.density ?? "--"}%.`,
        status: "ready",
      },
      {
        label: "Compare",
        body: options,
        status: run ? "done" : isRunning ? "active" : "ready",
      },
      {
        label: "Gate",
        body: telemetry?.governance?.gate_status ?? signal?.signal?.human_approval_required ? "human approval path" : "policy gate pending",
        status: telemetry?.governance ? "done" : isRunning ? "active" : "ready",
      },
      {
        label: "Emit",
        body: selectedAction?.label ?? selectedAction?.action ?? route?.selected_role ?? "waiting for final role/action",
        status: actions.length ? "done" : isRunning ? "active" : "ready",
      },
    ];
  }, [actions.length, isRunning, route?.selected_role, run?.scan?.top_risk, selectedAction?.action, selectedAction?.label, selectedMapItem, selectedPlaceActions, signal, telemetry?.governance, topRide, topZone]);

  const receiptStats = [
    ["Mode", AGENT_MODES.find((mode) => mode.id === agentMode)?.label ?? "Auto"],
    ["Role", run?.selected_role ?? route?.selected_role ?? "--"],
    ["Gate", telemetry?.governance?.gate_status ?? "--"],
    ["Eval", score(evalScore)],
    ["Actions", String(actions.length || "--")],
    ["Trace", telemetry?.decision_id ? "saved" : toolCalls.length ? `${toolCalls.length} tools` : "--"],
  ];

  const runHumanAgent = async () => {
    setIsRunning(true);
    setError(null);
    setOperatorDecision(null);
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
      setError(err instanceof Error ? err.message : "Unable to convert employee text into actions.");
    } finally {
      setIsRunning(false);
    }
  };

  const useMapSelection = (selection: MapSelection) => {
    setSelectedMapItem(selection);
    setEmployeeText(selection.prompt);
  };

  return (
    <main className="min-h-screen bg-slate-950 px-4 py-4 font-sans text-slate-200 lg:px-6">
      <div className="mx-auto max-w-[1800px] space-y-4">
        <header className="flex flex-col gap-3 border-b border-slate-800 pb-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Human enhancement</div>
            <h1 className="mt-1 text-2xl font-black text-slate-100">Map-aware LLM operator console</h1>
            <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-400">
              This is the human side of the same ParkPulse story: employees describe what they see, the agent turns text and map context into traceable actions, and managers approve or hold the receipt.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {[
              ["Feed", isConnected ? "live" : "offline"],
              ["Peak", topZone ? `${topZone.name} ${topZone.density}%` : "--"],
              ["Staff", `${parkState.staffing.checkedIn}/${parkState.staffing.scheduled}`],
            ].map(([label, value]) => (
              <div key={label} className="rounded border border-slate-800 bg-slate-900 px-3 py-2 text-xs">
                <span className="font-black uppercase tracking-widest text-slate-500">{label}</span>
                <span className="ml-2 font-black text-cyan-100">{value}</span>
              </div>
            ))}
            <a href="/" className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-300 hover:text-cyan-100">
              Automated ops
            </a>
            <a href="/monitor" className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-300 hover:text-cyan-100">
              Policy monitor
            </a>
            <a href="/executive" className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-300 hover:text-cyan-100">
              Executive view
            </a>
          </div>
        </header>

        <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_27rem]">
          <div className="overflow-hidden rounded-lg border border-slate-800 bg-slate-900">
            <div className="flex flex-col gap-2 border-b border-slate-800 p-3 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">1. Place</div>
                <div className="mt-1 text-sm font-black text-slate-100">
                  {selectedMapItem ? `${selectedMapItem.title} selected` : "Click a ride, queue, food area, guest group, or support point"}
                </div>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {(["overview", "queues", "guests", "support", "signals"] as MapLayer[]).map((layer) => (
                  <button
                    key={layer}
                    type="button"
                    onClick={() => setMapLayer(layer)}
                    className={`rounded px-2.5 py-1.5 text-[10px] font-black uppercase tracking-widest transition ${
                      mapLayer === layer ? "bg-cyan-300 text-slate-950" : "bg-slate-950 text-slate-400 hover:text-slate-100"
                    }`}
                  >
                    {layer}
                  </button>
                ))}
                <button
                  type="button"
                  onClick={() => setShowMapLabels((value) => !value)}
                  className={`rounded px-2.5 py-1.5 text-[10px] font-black uppercase tracking-widest transition ${
                    showMapLabels ? "bg-emerald-300 text-slate-950" : "bg-slate-950 text-slate-400 hover:text-slate-100"
                  }`}
                >
                  Labels
                </button>
                <button
                  type="button"
                  onClick={() => setShowMapDetails((value) => !value)}
                  className={`rounded px-2.5 py-1.5 text-[10px] font-black uppercase tracking-widest transition ${
                    showMapDetails ? "bg-amber-300 text-slate-950" : "bg-slate-950 text-slate-400 hover:text-slate-100"
                  }`}
                >
                  Detail
                </button>
              </div>
            </div>
            <div className="h-[calc(100vh-13.5rem)] min-h-[42rem] bg-[#8fbc72]">
              <VisualParkBoard
                flow={flow}
                scenario={scenario}
                isConnected={isConnected}
                isRunning={isRunning}
                runTelemetry={(telemetry as any) ?? null}
                parkState={parkState}
                proactiveRunTelemetry={null}
                signalTriage={null}
                operatorCommand={employeeText}
                operatorCommandResult={null}
                isRunningProactive={false}
                visualStepIndex={run ? 5 : isRunning ? 2 : 0}
                compact
                showCompactPanels={false}
                showOverlayControls={false}
                mapLayer={mapLayer}
                onMapLayerChange={setMapLayer}
                showLabels={showMapLabels}
                onShowLabelsChange={setShowMapLabels}
                showDetails={showMapDetails}
                onShowDetailsChange={setShowMapDetails}
                selectedMapItem={selectedMapItem}
                onMapSelectionChange={useMapSelection}
              />
            </div>
          </div>

          <aside className="grid content-start gap-3">
            <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
              <div className="text-[10px] font-black uppercase tracking-widest text-emerald-300">2. Flexible request</div>
              <h2 className="mt-1 text-lg font-black text-slate-100">{selectedMapItem?.title ?? "Whole park request"}</h2>
              <p className="mt-1 text-xs leading-relaxed text-slate-500">
                {short(selectedMapItem?.detail, topRide ? `${topRide.name}: ${topRide.waitMins}m wait, ${topRide.queueGuests.toLocaleString()} queued.` : "Live state ready.")}
              </p>

              <textarea
                value={employeeText}
                onChange={(event) => setEmployeeText(event.target.value)}
                className="mt-3 h-32 w-full resize-none rounded border border-slate-700 bg-slate-950 p-3 text-sm leading-relaxed text-slate-100 outline-none transition placeholder:text-slate-600 focus:border-cyan-300"
              />

              <div className="mt-3 grid grid-cols-2 gap-2">
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
                {selectedPlaceActions.map((action) => (
                  <button
                    key={action}
                    type="button"
                    onClick={() => {
                      const base = selectedMapItem?.prompt ?? employeeText;
                      setEmployeeText(`${action}. ${base}`);
                    }}
                    className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-[11px] font-black text-slate-300 transition hover:border-emerald-300 hover:text-emerald-100"
                  >
                    {action}
                  </button>
                ))}
              </div>

              <details className="mt-3 rounded border border-slate-800 bg-slate-950 p-2">
                <summary className="cursor-pointer text-[10px] font-black uppercase tracking-widest text-slate-400">Example reports</summary>
                <div className="mt-2 grid gap-1.5">
                  {EXAMPLES.map((example) => (
                    <button
                      key={example}
                      type="button"
                      onClick={() => setEmployeeText(example)}
                      className="rounded border border-slate-800 bg-slate-900 px-3 py-2 text-left text-[11px] font-bold text-slate-300 transition hover:border-cyan-400 hover:text-cyan-100"
                    >
                      {example}
                    </button>
                  ))}
                </div>
              </details>

              {error && <div className="mt-3 rounded border border-red-500/30 bg-red-950/20 p-3 text-xs text-red-100">{error}</div>}
              <button
                type="button"
                onClick={() => void runHumanAgent()}
                disabled={isRunning || !employeeText.trim()}
                className="mt-3 w-full rounded bg-emerald-300 px-5 py-3 text-sm font-black text-slate-950 transition hover:bg-emerald-200 disabled:bg-slate-700 disabled:text-slate-400"
              >
                {isRunning ? "Reasoning..." : "Reason and prepare action"}
              </button>
            </section>

            <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
              <div className="text-[10px] font-black uppercase tracking-widest text-violet-300">3. LLM reasoning</div>
              <div className="mt-3 grid gap-2">
                {reasoningRows.map((row, index) => (
                  <div key={row.label} className="grid grid-cols-[1.4rem_1fr] gap-2 rounded border border-slate-800 bg-slate-950 p-2">
                    <div className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-black ${
                      row.status === "done" ? "bg-emerald-300 text-slate-950" : row.status === "active" ? "bg-cyan-300 text-slate-950" : "bg-slate-800 text-slate-500"
                    }`}>
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
          </aside>
        </section>

        <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(26rem,0.7fr)]">
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">4. Manager receipt</div>
                <h2 className="mt-1 text-xl font-black text-slate-100">{run?.operator_response?.headline ?? "No action receipt yet"}</h2>
                <p className="mt-2 max-w-4xl text-sm leading-relaxed text-slate-400">
                  {run?.operator_response?.summary ?? "The receipt appears after the LLM interprets the human report, checks context, and chooses a bounded operating action."}
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

            <div className="mt-4 grid gap-3 md:grid-cols-3">
              {(actions.length ? actions : [{ owner: "Action", action: "Run reasoning to prepare receiver actions.", status: "waiting" }]).slice(0, 6).map((action: any, index) => (
                <div key={action.id ?? `${action.owner ?? action.channel}-${index}`} className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="truncate text-sm font-black text-slate-100">{action.channel ?? action.owner ?? "Action"}</div>
                    <div className="rounded bg-slate-900 px-2 py-1 text-[10px] font-black uppercase text-emerald-300">{action.status ?? "draft"}</div>
                  </div>
                  <p className="mt-2 line-clamp-4 text-xs leading-relaxed text-slate-400">{dispatchMessage(action)}</p>
                  <div className="mt-2 truncate text-[10px] font-black uppercase tracking-widest text-slate-500">{action.target ?? `${action.deadline_minutes ?? "--"} min`}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="grid gap-4">
            <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Signal and policy</div>
              <div className="mt-3 grid gap-2">
                {[
                  ["Risk", signal?.signal?.risk_level ?? "--"],
                  ["Confidence", pct(signal?.signal?.confidence)],
                  ["Categories", signal?.signal?.categories?.join(", ") ?? "--"],
                  ["Missing info", signal?.signal?.missing_info?.slice(0, 2).join("; ") ?? "none"],
                ].map(([label, value]) => (
                  <div key={label} className="grid grid-cols-[6rem_1fr] gap-2 rounded border border-slate-800 bg-slate-950 px-3 py-2 text-xs">
                    <div className="font-black uppercase tracking-widest text-slate-500">{label}</div>
                    <div className="font-bold text-slate-100">{value}</div>
                  </div>
                ))}
              </div>
            </section>

            <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
              <div className="text-[10px] font-black uppercase tracking-widest text-violet-300">Trace</div>
              <div className="mt-3 grid gap-2">
                {(toolCalls.length ? toolCalls : route?.required_tools?.map((tool) => ({ tool, status: "planned" })) ?? []).slice(0, 7).map((call, index) => (
                  <div key={`${call.tool}-${index}`} className="grid grid-cols-[1fr_auto] gap-3 rounded border border-slate-800 bg-slate-950 px-3 py-2 text-xs">
                    <div className="truncate font-black text-slate-100">{call.tool?.replaceAll("_", " ") ?? "tool"}</div>
                    <div className="text-slate-500">{call.status ?? ("capability" in call ? call.capability : undefined) ?? "ok"}</div>
                  </div>
                ))}
                {!toolCalls.length && !route?.required_tools?.length && <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs text-slate-500">Waiting for a run.</div>}
              </div>
              <div className="mt-3 rounded border border-slate-800 bg-slate-950 p-3 text-xs leading-relaxed text-slate-400">
                Decision ID: <span className="font-mono text-slate-200">{telemetry?.decision_id ?? "--"}</span>
                {" / "}Response: <span className="font-black text-cyan-200">{score(telemetry?.eval?.scorecard?.response_score)}</span>
              </div>
            </section>
          </div>
        </section>
      </div>
    </main>
  );
}
