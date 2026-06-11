"use client";

import { useMemo, useState } from "react";
import { fetchParkPulseApi } from "@/lib/api";
import { buildOperatingLoopViewModel } from "@/lib/operatingLoop";
import { useParkPulseState } from "@/hooks/useParkPulseState";

type ChatRole = "user" | "assistant";
type TurnMode = "auto" | "answer" | "propose" | "apply";
type AgentMode = "auto" | "scan" | "react" | "proact" | "customer" | "qa";

type ChatMessage = {
  role: ChatRole;
  content: string;
};

type CopilotReceipt = {
  status?: string;
  mode?: string;
  selected_role?: string;
  message?: string;
  answer?: string;
  conversation_response?: {
    answer?: string;
    source?: string;
    operator_next?: string;
    confidence?: number;
    reasoning_bullets?: string[];
  };
  conversation_memory?: {
    turn_count?: number;
    conversation_intent?: string;
    followup_of_previous_run?: boolean;
    chat_brain_source?: string;
  };
  chat_brain?: {
    intent?: string;
    planner_message?: string;
    confidence?: number;
    source?: string;
  };
  recommended_action?: {
    role?: string;
    label?: string;
    action?: string;
    gate?: string;
    dispatch_count?: number;
    matched_case_id?: string;
    matched_case_title?: string;
    object_action_plan_id?: string;
    policy_selected_action?: string | null;
  };
  turn_contract?: {
    mode?: string;
    label?: string;
    state_mutation?: boolean;
    dispatch_count?: number;
    map_effect?: string;
    reason?: string;
  };
  reasoning_summary?: string[];
  options_considered?: Array<{ label?: string; verdict?: string; reason?: string; projected_effect?: string }>;
  object_action_plan?: {
    overall_gate?: string;
    will_execute?: boolean;
    operator_approval?: string;
    actions?: Array<{
      object_name?: string;
      object_type?: string;
      action?: string;
      gate_status?: string;
      reason?: string;
      will_execute?: boolean;
    }>;
  };
  tool_call_timeline?: Array<{ id?: string; tool?: string; label?: string; status?: string; output?: string }>;
  tool_trace?: {
    tool_calls?: Array<{ tool?: string; status?: string; capability?: string; output?: string }>;
  };
  agent_runtime?: {
    status?: string;
    summary?: { completed_stages?: number; waiting_stages?: number; blocked_stages?: number };
    lifecycle?: { state?: string; owner?: string; next_check?: string; close_condition?: string };
    critic_report?: { verdict?: string; confidence?: number; risks?: Array<{ risk?: string; severity?: string; mitigation?: string }> };
  };
  map_grounding?: Record<string, unknown> | null;
  impact_replay?: Record<string, unknown> | null;
  reasoning_evaluation?: { overall?: number; verdict?: string };
  run_telemetry?: Record<string, unknown> | null;
  semantic_memory_context?: {
    status?: string;
    model_api_key_configured?: boolean;
    reason?: string;
  };
  latency_diagnostics?: {
    mode?: string;
    status?: string;
    total_ms?: number;
    stages?: Array<{ stage?: string; total_ms?: number; delta_ms?: number }>;
    wrapper?: {
      total_ms?: number;
      stages?: Array<{ stage?: string; total_ms?: number }>;
    };
  };
};

type ToolRow = {
  id?: string;
  tool?: string;
  label?: string;
  status?: string;
  output?: string;
};

const starterPrompts = [
  "What is the biggest park risk right now?",
  "The coaster queue is too long and families are stuck near the parade. What should we do?",
  "Why that plan?",
  "Change it to avoid the parade crowd.",
];

const agentModes: Array<{ id: AgentMode; label: string }> = [
  { id: "auto", label: "Auto" },
  { id: "scan", label: "Scan" },
  { id: "react", label: "React" },
  { id: "proact", label: "Proact" },
  { id: "customer", label: "Customer" },
  { id: "qa", label: "QA" },
];

const copilotCacheTtlMs = 45_000;
const copilotRequestTimeoutMs = 9000;
const copilotCacheStorageKey = "parkpulse.opsAgent.copilotCache.v1";
const copilotMemoryCache = new Map<string, { expiresAt: number; receipt: CopilotReceipt }>();
const copilotInflight = new Map<string, Promise<CopilotReceipt>>();

type CacheStatus = "idle" | "hit" | "miss" | "refresh" | "error";

function humanize(value: unknown, empty = "--") {
  return String(value ?? empty).replaceAll("_", " ");
}

function compact(value: string | undefined, max = 180) {
  const text = value?.trim();
  if (!text) return "--";
  return text.length > max ? `${text.slice(0, max - 3)}...` : text;
}

function statusClass(value?: string) {
  const normalized = String(value ?? "").toLowerCase();
  if (normalized.includes("block") || normalized.includes("required")) return "border-amber-400/40 bg-amber-950/20 text-amber-100";
  if (normalized.includes("pass") || normalized.includes("complete") || normalized.includes("follow")) return "border-emerald-400/40 bg-emerald-950/20 text-emerald-100";
  if (normalized.includes("read")) return "border-sky-400/40 bg-sky-950/20 text-sky-100";
  return "border-slate-800 bg-slate-950 text-slate-300";
}

function answerFromReceipt(receipt: CopilotReceipt) {
  return receipt.conversation_response?.answer ?? receipt.answer ?? "The ops agent returned a receipt without an answer body.";
}

function requestMessage(input: string, turnMode: TurnMode) {
  const trimmed = input.trim();
  if (trimmed) return trimmed;
  if (turnMode === "apply") return "apply";
  if (turnMode === "propose") return "What should we do next?";
  return "What is the biggest park risk right now?";
}

function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, entry]) => `${JSON.stringify(key)}:${stableJson(entry)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function copilotCacheKey(payload: Record<string, unknown>) {
  return stableJson({
    message: payload.message,
    messages: payload.messages,
    mode: payload.mode,
    turn_mode: payload.turn_mode,
    allow_action: payload.allow_action,
    last_mode: (payload.selected_map_context as { last_copilot?: CopilotReceipt } | undefined)?.last_copilot?.mode,
    last_action: (payload.selected_map_context as { last_copilot?: CopilotReceipt } | undefined)?.last_copilot?.recommended_action?.label,
  });
}

function readCopilotCache(key: string) {
  const now = Date.now();
  const memory = copilotMemoryCache.get(key);
  if (memory && memory.expiresAt > now) return memory.receipt;
  if (memory) copilotMemoryCache.delete(key);
  try {
    const raw = globalThis.sessionStorage?.getItem(copilotCacheStorageKey);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Record<string, { expiresAt?: number; receipt?: CopilotReceipt }>;
    const entry = parsed[key];
    if (!entry?.receipt || Number(entry.expiresAt ?? 0) <= now) return null;
    copilotMemoryCache.set(key, { expiresAt: Number(entry.expiresAt), receipt: entry.receipt });
    return entry.receipt;
  } catch {
    return null;
  }
}

function writeCopilotCache(key: string, receipt: CopilotReceipt) {
  const expiresAt = Date.now() + copilotCacheTtlMs;
  copilotMemoryCache.set(key, { expiresAt, receipt });
  try {
    const raw = globalThis.sessionStorage?.getItem(copilotCacheStorageKey);
    const parsed = raw ? (JSON.parse(raw) as Record<string, { expiresAt?: number; receipt?: CopilotReceipt }>) : {};
    const compactEntries = Object.fromEntries(
      Object.entries({ ...parsed, [key]: { expiresAt, receipt } })
        .filter(([, entry]) => Number(entry.expiresAt ?? 0) > Date.now())
        .slice(-12),
    );
    globalThis.sessionStorage?.setItem(copilotCacheStorageKey, JSON.stringify(compactEntries));
  } catch {
    // Session cache is an optimization only.
  }
}

async function fetchCopilotReceipt(payload: Record<string, unknown>, cacheKey: string, cacheable: boolean) {
  if (cacheable) {
    const cached = readCopilotCache(cacheKey);
    if (cached) return { receipt: cached, cacheStatus: "hit" as CacheStatus };
    const inflight = copilotInflight.get(cacheKey);
    if (inflight) return { receipt: await inflight, cacheStatus: "refresh" as CacheStatus };
  }

  const requestPromise = (async () => {
    const response = await fetchParkPulseApi("/api/park/copilot-chat", {
      method: "POST",
      headers: { "content-type": "application/json", "x-parkpulse-role": "ops_team" },
      body: JSON.stringify(payload),
      timeoutMs: copilotRequestTimeoutMs,
    });
    const receipt = (await response.json()) as CopilotReceipt;
    if (cacheable && receipt.status === "complete") writeCopilotCache(cacheKey, receipt);
    return receipt;
  })();

  if (cacheable) copilotInflight.set(cacheKey, requestPromise);
  try {
    return { receipt: await requestPromise, cacheStatus: cacheable ? ("miss" as CacheStatus) : ("refresh" as CacheStatus) };
  } finally {
    if (cacheable) copilotInflight.delete(cacheKey);
  }
}

export default function OpsAgentPage() {
  const { parkState, isConnected, connectionError, refreshParkState } = useParkPulseState();
  const [input, setInput] = useState("What is the biggest park risk right now?");
  const [agentMode, setAgentMode] = useState<AgentMode>("auto");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [latestReceipt, setLatestReceipt] = useState<CopilotReceipt | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cacheStatus, setCacheStatus] = useState<CacheStatus>("idle");

  const loop = useMemo(
    () =>
      buildOperatingLoopViewModel({
        parkState,
        latestCopilotReceipt: latestReceipt,
        isBusy: isRunning,
      }),
    [isRunning, latestReceipt, parkState],
  );

  const toolRows: ToolRow[] = latestReceipt?.tool_call_timeline?.length ? latestReceipt.tool_call_timeline : latestReceipt?.tool_trace?.tool_calls ?? [];
  const objectActions = latestReceipt?.object_action_plan?.actions ?? [];
  const risks = latestReceipt?.agent_runtime?.critic_report?.risks ?? [];

  const sendTurn = async (turnMode: TurnMode) => {
    const message = requestMessage(input, turnMode);
    const nextMessages: ChatMessage[] = [...messages, { role: "user", content: message }];
    setMessages(nextMessages);
    setInput("");
    setIsRunning(true);
    setError(null);
    setCacheStatus("refresh");
    try {
      const payload = {
        message,
        messages: nextMessages,
        mode: agentMode,
        turn_mode: turnMode,
        allow_action: turnMode === "apply",
        selected_map_context: latestReceipt ? { last_copilot: latestReceipt } : {},
      };
      const cacheable = turnMode !== "apply";
      const { receipt, cacheStatus: nextCacheStatus } = await fetchCopilotReceipt(payload, copilotCacheKey(payload), cacheable);
      const answer = answerFromReceipt(receipt);
      setCacheStatus(nextCacheStatus);
      setLatestReceipt(receipt);
      setMessages([...nextMessages, { role: "assistant", content: answer }]);
      if (receipt.turn_contract?.state_mutation) {
        globalThis.setTimeout(() => void refreshParkState(), 300);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to reach the ops agent.");
      setCacheStatus("error");
      setMessages(nextMessages);
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <main className="min-h-screen bg-slate-950 px-4 py-5 font-sans text-slate-200 lg:px-8">
      <div className="mx-auto max-w-[1500px] space-y-5">
        <header className="rounded-lg border border-cyan-400/20 bg-slate-900 p-5">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Ops agent</div>
              <h1 className="mt-2 text-3xl font-black text-slate-100 lg:text-5xl">Ask the park operations agent</h1>
              <p className="mt-3 max-w-3xl text-sm leading-relaxed text-slate-400">
                Ask for status, request a bounded plan, follow up on the receipt, or explicitly apply a gated plan.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <a href="/ops" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-100">
                Command Center
              </a>
              <a href="/human" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-100">
                Human view
              </a>
              <a href="/monitor" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-100">
                Monitor
              </a>
            </div>
          </div>
        </header>

        <section className="grid gap-2 md:grid-cols-5">
          {[
            ["Connection", isConnected ? "live" : "offline"],
            ["Agent", latestReceipt?.selected_role ?? latestReceipt?.recommended_action?.role],
            ["Intent", latestReceipt?.chat_brain?.intent ?? latestReceipt?.conversation_memory?.conversation_intent],
            ["Mode", latestReceipt?.mode ?? "--"],
            ["Gate", latestReceipt?.recommended_action?.gate ?? latestReceipt?.object_action_plan?.overall_gate],
          ].map(([label, value]) => (
            <div key={label} className="rounded border border-slate-800 bg-slate-900 p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">{label}</div>
              <div className="mt-1 truncate text-sm font-black text-cyan-100">{humanize(value)}</div>
            </div>
          ))}
        </section>

        {(error || connectionError) && (
          <section className="rounded border border-amber-400/30 bg-amber-950/15 p-3 text-sm font-bold text-amber-100">
            {error ?? connectionError}
          </section>
        )}

        <section className="grid gap-5 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <div className="space-y-5">
            <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Conversation</div>
                  <h2 className="mt-1 text-xl font-black text-slate-100">Operator turn</h2>
                </div>
                <div className="grid w-full grid-cols-3 gap-1 rounded border border-slate-800 bg-slate-950 p-1 sm:w-auto sm:grid-cols-6">
                  {agentModes.map((mode) => (
                    <button
                      key={mode.id}
                      type="button"
                      onClick={() => setAgentMode(mode.id)}
                      className={`rounded px-2 py-1.5 text-xs font-black uppercase transition sm:px-3 ${
                        agentMode === mode.id ? "bg-cyan-300 text-slate-950" : "text-slate-400 hover:text-cyan-100"
                      }`}
                    >
                      {mode.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="mt-4 max-h-[520px] min-h-[320px] space-y-3 overflow-y-auto rounded border border-slate-800 bg-slate-950 p-3">
                {messages.length ? (
                  messages.map((message, index) => (
                    <div key={`${message.role}-${index}-${message.content.slice(0, 16)}`} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                      <div
                        className={`max-w-[88%] rounded border px-3 py-2 text-sm leading-relaxed ${
                          message.role === "user"
                            ? "border-cyan-400/40 bg-cyan-950/30 text-cyan-50"
                            : "border-slate-700 bg-slate-900 text-slate-200"
                        }`}
                      >
                        <div className="mb-1 text-[10px] font-black uppercase tracking-widest opacity-60">{message.role === "user" ? "Operator" : "Ops agent"}</div>
                        {message.content}
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="flex h-full min-h-[280px] items-center justify-center text-center text-sm font-bold leading-relaxed text-slate-500">
                    Start with a status question or describe a current park problem.
                  </div>
                )}
              </div>

              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {starterPrompts.map((prompt) => (
                  <button
                    key={prompt}
                    type="button"
                    onClick={() => setInput(prompt)}
                    className="rounded border border-slate-800 bg-slate-950 px-3 py-2 text-left text-xs font-bold leading-relaxed text-slate-300 transition hover:border-cyan-400 hover:text-cyan-100"
                  >
                    {prompt}
                  </button>
                ))}
              </div>

              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") void sendTurn("auto");
                }}
                placeholder="Ask what is happening, request a plan, or ask why the previous plan was selected."
                className="mt-3 h-28 w-full resize-none rounded border border-slate-700 bg-slate-950 p-3 text-sm leading-relaxed text-slate-100 outline-none transition placeholder:text-slate-600 focus:border-cyan-300"
              />

              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => void sendTurn("auto")}
                  disabled={isRunning}
                  className="rounded border border-cyan-300 bg-cyan-300 px-4 py-2 text-sm font-black text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {isRunning ? "Thinking" : "Ask"}
                </button>
                <button
                  type="button"
                  onClick={() => void sendTurn("propose")}
                  disabled={isRunning}
                  className="rounded border border-emerald-300 bg-emerald-300 px-4 py-2 text-sm font-black text-slate-950 transition hover:bg-emerald-200 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Propose Plan
                </button>
                <button
                  type="button"
                  onClick={() => void sendTurn("apply")}
                  disabled={isRunning || !latestReceipt}
                  className="rounded border border-amber-300 bg-amber-300 px-4 py-2 text-sm font-black text-slate-950 transition hover:bg-amber-200 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Apply Prior Plan
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setMessages([]);
                    setLatestReceipt(null);
                    setError(null);
                    setCacheStatus("idle");
                    setInput("What is the biggest park risk right now?");
                  }}
                  disabled={isRunning}
                  className="rounded border border-slate-700 bg-slate-950 px-4 py-2 text-sm font-black text-slate-300 transition hover:border-slate-500 hover:text-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Reset
                </button>
              </div>
            </section>

            <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Loop stages</div>
              <h2 className="mt-1 text-xl font-black text-slate-100">{loop.headline}</h2>
              <p className="mt-2 text-xs leading-relaxed text-slate-400">{loop.openLoop}</p>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {loop.stages.map((stage) => (
                  <div key={stage.id} className={`rounded border p-3 ${statusClass(stage.status)}`}>
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-[10px] font-black uppercase opacity-65">{stage.owner}</div>
                      <div className="rounded bg-slate-950/45 px-2 py-1 text-[10px] font-black uppercase">{humanize(stage.status)}</div>
                    </div>
                    <div className="mt-2 text-sm font-black">{stage.label}: {stage.metric}</div>
                    <p className="mt-1 line-clamp-2 text-xs leading-relaxed opacity-85">{stage.body}</p>
                  </div>
                ))}
              </div>
            </section>
          </div>

          <div className="space-y-5">
            <section className={`rounded-lg border p-4 ${statusClass(latestReceipt?.recommended_action?.gate ?? latestReceipt?.object_action_plan?.overall_gate)}`}>
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <div className="text-[10px] font-black uppercase tracking-widest opacity-70">Current receipt</div>
                  <h2 className="mt-1 text-xl font-black">{latestReceipt?.recommended_action?.label ?? latestReceipt?.recommended_action?.action ?? "No receipt yet"}</h2>
                  <p className="mt-2 max-w-3xl text-xs leading-relaxed opacity-85">
                    {latestReceipt?.turn_contract?.reason ?? latestReceipt?.conversation_response?.operator_next ?? "Ask the agent to produce the first receipt."}
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {[
                    ["Gate", latestReceipt?.recommended_action?.gate ?? latestReceipt?.object_action_plan?.overall_gate],
                    ["Dispatch", latestReceipt?.turn_contract?.dispatch_count ?? latestReceipt?.recommended_action?.dispatch_count],
                    ["Latency", latestReceipt?.latency_diagnostics?.total_ms ? `${Math.round(latestReceipt.latency_diagnostics.total_ms)}ms` : undefined],
                    ["Cache", cacheStatus],
                  ].map(([label, value]) => (
                    <div key={label} className="rounded border border-slate-950/40 bg-slate-950/35 px-3 py-2 text-center">
                      <div className="text-[10px] font-black uppercase opacity-60">{label}</div>
                      <div className="mt-1 truncate text-sm font-black">{humanize(value)}</div>
                    </div>
                  ))}
                </div>
              </div>
            </section>

            <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
              <div className="text-[10px] font-black uppercase tracking-widest text-emerald-300">Action plan</div>
              <div className="mt-3 grid gap-2 xl:grid-cols-2">
                {objectActions.length ? (
                  objectActions.map((action, index) => (
                    <div key={`${action.object_name ?? action.object_type}-${action.action}-${index}`} className={`rounded border p-3 ${statusClass(action.gate_status)}`}>
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <div className="text-[10px] font-black uppercase opacity-65">{humanize(action.object_type)}</div>
                          <div className="mt-1 text-sm font-black">{action.object_name ?? "Park object"}</div>
                        </div>
                        <div className="rounded bg-slate-950/45 px-2 py-1 text-[10px] font-black uppercase">{humanize(action.gate_status)}</div>
                      </div>
                      <div className="mt-3 text-xs font-black uppercase opacity-80">{humanize(action.action)}</div>
                      <p className="mt-2 line-clamp-3 text-xs leading-relaxed opacity-85">{action.reason}</p>
                    </div>
                  ))
                ) : (
                  <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs leading-relaxed text-slate-400 xl:col-span-2">
                    No object-bound actions have been proposed yet.
                  </div>
                )}
              </div>
            </section>

            <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Reasoning</div>
              <div className="mt-3 space-y-2">
                {(latestReceipt?.reasoning_summary ?? []).slice(0, 6).map((row) => (
                  <div key={row} className="rounded border border-slate-800 bg-slate-950 px-3 py-2 text-xs leading-relaxed text-slate-300">
                    {row}
                  </div>
                ))}
                {!(latestReceipt?.reasoning_summary ?? []).length && (
                  <div className="rounded border border-slate-800 bg-slate-950 p-3 text-xs leading-relaxed text-slate-400">
                    Reasoning appears after the first agent response.
                  </div>
                )}
              </div>
            </section>

            <section className="grid gap-5 xl:grid-cols-2">
              <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
                <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Tool trace</div>
                <div className="mt-3 space-y-2">
                  {toolRows.slice(0, 8).map((tool, index) => (
                    <div key={`${tool.tool}-${tool.id ?? index}`} className="rounded border border-slate-800 bg-slate-950 px-3 py-2">
                      <div className="flex items-center justify-between gap-2">
                        <div className="truncate text-xs font-black text-slate-100">{tool.label ?? humanize(tool.tool)}</div>
                        <div className="rounded bg-slate-900 px-2 py-1 text-[10px] font-black uppercase text-slate-400">{humanize(tool.status)}</div>
                      </div>
                      <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-slate-500">{compact(tool.output)}</p>
                    </div>
                  ))}
                  {!toolRows.length && <p className="text-xs leading-relaxed text-slate-400">No tools have been selected yet.</p>}
                </div>
              </div>

              <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
                <div className="text-[10px] font-black uppercase tracking-widest text-amber-300">Critic</div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  <span className="rounded bg-slate-950 px-2 py-1 text-[10px] font-black uppercase text-slate-300">
                    {humanize(latestReceipt?.agent_runtime?.critic_report?.verdict)}
                  </span>
                  <span className="rounded bg-slate-950 px-2 py-1 text-[10px] font-black uppercase text-slate-300">
                    Confidence {humanize(latestReceipt?.agent_runtime?.critic_report?.confidence)}
                  </span>
                </div>
                <div className="mt-3 space-y-2">
                  {risks.slice(0, 4).map((risk, index) => (
                    <div key={`${risk.risk ?? "risk"}-${index}`} className="rounded border border-slate-800 bg-slate-950 px-3 py-2">
                      <div className="text-xs font-black text-slate-100">{risk.risk ?? "Residual risk"}</div>
                      <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-slate-500">{risk.mitigation}</p>
                    </div>
                  ))}
                  {!risks.length && <p className="text-xs leading-relaxed text-slate-400">Critic findings appear on proposal or apply turns.</p>}
                </div>
              </div>
            </section>
          </div>
        </section>
      </div>
    </main>
  );
}
