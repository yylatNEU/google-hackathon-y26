"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { fetchParkPulseApi } from "@/lib/api";

type TriageResult = {
  status?: string;
  readiness_issues?: string[];
  classification?: {
    issue_type?: string;
    urgency?: string;
    urgency_score?: number;
    severity?: string;
    matched_terms?: string[];
    confidence?: number;
  };
  understanding?: {
    status?: string;
    category?: string;
    confidence?: number;
  };
  profile_context?: {
    status?: string;
    venue_name?: string;
    profile_type?: string;
    readiness_status?: string;
    category?: string | null;
    matched_locations?: Array<{
      name?: string;
      kind?: string;
      zone_id?: string;
      services?: string[];
      dietary_tags?: string[];
      accessibility_note?: string | null;
      sensory_note?: string | null;
    }>;
    evidence?: string[];
    limitations?: string[];
    human_review_required?: boolean;
    human_review_place?: string | null;
  };
  routing?: {
    assigned_team?: string;
    human_review_place?: string | null;
    human_ack_required?: boolean;
    sla_minutes?: number;
  };
  reaction?: {
    guest_reply_draft?: string;
    staff_checklist?: string[];
    forbidden_auto_actions?: string[];
  };
  llm_response?: {
    status?: string;
    source?: string;
    reply?: string;
    model?: string;
    provider?: string;
    platform?: string;
    transport?: string;
    tone?: string;
    used_profile?: boolean;
    next_step?: string;
    confidence?: number;
    readiness_issues?: string[];
    llm_controls_live_ops?: boolean;
  };
  ticket_result?: {
    status?: string;
    ticket?: {
      id?: string;
      issue_type?: string;
      severity?: string;
      assigned_team?: string;
      requires_human_ack?: boolean;
      live_ops_authority?: boolean;
    };
  };
  memory_impact?: {
    stored?: boolean;
    storage_mode?: string | null;
    collection?: string | null;
    document_id?: string | null;
    training_scenario_id?: string;
    recommended_action?: string;
    memory_count?: number;
    visible_benefit?: string;
    historical_ticket_frequency?: {
      ticket_count?: number;
      highest_severity?: string;
      frequency_label?: string;
      sources?: Record<string, number>;
      issue_types?: Record<string, number>;
    };
    top_patterns?: Array<{ issue_type?: string; scenario_id?: string; count?: number; highest_severity?: string; latest_summary?: string }>;
    recent_examples?: Array<{ id?: string; source?: string; scenario_id?: string; issue_type?: string; severity?: string; summary?: string }>;
    boundary?: string;
  };
  boundary?: string;
};

const examples = [
  "Where is the closest vegetarian food near the coaster?",
  "I want a refund. The ride was closed and nobody told us before we waited.",
  "I cannot find my six-year-old. She was next to me near the carousel and now she is gone.",
  "My friend is dizzy and looks pale. We have been in the sun for an hour and she says she might faint.",
  "A group cut the line and now people are yelling near the coaster merge.",
  "My father cannot stand in this sun for the queue. We need accessibility help but do not want to explain medical history in public.",
  "Where can we find a quiet cooling place and water refill?",
  "Can I bring a drone for filming behind the theater?",
];

function label(value?: string | null) {
  return String(value || "--").replace(/_/g, " ").replace(/\b\w/g, (match) => match.toUpperCase());
}

function urgencyClass(value?: string) {
  if (value === "critical") return "border-rose-300 bg-rose-300 text-slate-950";
  if (value === "high") return "border-amber-300 bg-amber-300 text-slate-950";
  if (value === "medium") return "border-cyan-300 bg-cyan-300 text-slate-950";
  return "border-slate-600 bg-slate-800 text-slate-100";
}

export default function GuestTriagePage() {
  const autoDemoStartedRef = useRef(false);
  const [message, setMessage] = useState(examples[0]);
  const [guestName, setGuestName] = useState("");
  const [location, setLocation] = useState("Coaster");
  const [channel, setChannel] = useState("in_app_guest_message");
  const [createTicket, setCreateTicket] = useState(true);
  const [result, setResult] = useState<TriageResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  const checklist = result?.reaction?.staff_checklist ?? [];
  const forbidden = result?.reaction?.forbidden_auto_actions ?? [];
  const matchedTerms = result?.classification?.matched_terms ?? [];
  const urgency = result?.classification?.urgency;
  const ticket = result?.ticket_result?.ticket;
  const score = result?.classification?.urgency_score ?? 0;
  const confidence = Math.round((result?.classification?.confidence ?? 0) * 100);
  const profileContext = result?.profile_context;
  const profileLocations = profileContext?.matched_locations ?? [];
  const profileLimitations = profileContext?.limitations ?? [];
  const memoryImpact = result?.memory_impact;
  const memoryFrequency = memoryImpact?.historical_ticket_frequency;
  const memorySources = Object.entries(memoryFrequency?.sources ?? {});
  const llmResponse = result?.llm_response;
  const replyText = llmResponse?.reply ?? result?.reaction?.guest_reply_draft ?? "Triage a guest message to generate a response draft.";
  const responseStatus = llmResponse?.status ?? (result ? "deterministic_ready" : "not_run");
  const responseSource = llmResponse?.source ?? (result ? "deterministic" : "waiting");
  const llmIsLive = responseSource === "llm_guest_triage";
  const responseMeta = [
    ["LLM", llmIsLive ? "Generated" : label(responseStatus)],
    ["Source", label(responseSource)],
    ["Provider", label(llmResponse?.provider ?? llmResponse?.platform ?? "not connected")],
    ["Ops authority", llmResponse?.llm_controls_live_ops ? "LLM controls ops" : "Human gated"],
  ];
  const decisionStats = [
    ["Issue", label(result?.classification?.issue_type)],
    ["Urgency", `${label(urgency ?? "not triaged")} ${score ? `${score}/100` : ""}`.trim()],
    ["Owner", label(result?.routing?.assigned_team)],
    ["SLA", result?.routing?.sla_minutes ? `${result.routing.sla_minutes} min` : "--"],
  ];
  const meterStyle = useMemo(() => ({ width: `${Math.max(0, Math.min(100, score))}%` }), [score]);

  async function runTriage(trimmed: string, shouldCreateTicket = createTicket) {
    if (!trimmed) return;
    setIsLoading(true);
    setError("");
    try {
      const response = await fetchParkPulseApi("/api/park/guest-message-triage", {
        method: "POST",
        headers: { "content-type": "application/json", "x-parkpulse-role": "onsite_worker" },
        body: JSON.stringify({ message: trimmed, guestName, location, channel, createTicket: shouldCreateTicket }),
        timeoutMs: 10000,
      });
      const payload = (await response.json()) as TriageResult;
      if (payload.readiness_issues?.length) {
        setError(payload.readiness_issues.join(" "));
      }
      setResult(payload);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Unable to triage guest message.");
    } finally {
      setIsLoading(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    await runTriage(message.trim(), createTicket);
  }

  useEffect(() => {
    if (autoDemoStartedRef.current) return;
    autoDemoStartedRef.current = true;
    void runTriage(examples[0], false);
  }, []);

  return (
    <main className="min-h-screen bg-[#f5f7f3] px-4 py-5 font-sans text-slate-950 lg:px-8">
      <div className="mx-auto max-w-6xl space-y-4">
        <header className="flex flex-col gap-3 border-b border-slate-300 pb-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="text-[11px] font-black uppercase tracking-widest text-teal-700">Guest Triage</div>
            <h1 className="mt-1 text-3xl font-black tracking-normal text-slate-950 lg:text-5xl">Reply, route, and learn</h1>
          </div>
          <nav className="flex flex-wrap gap-2">
            <a href="/staff-training" className="rounded border border-slate-300 bg-white px-3 py-2 text-xs font-black text-slate-700">Staff training</a>
            <a href="/ops" className="rounded border border-slate-300 bg-white px-3 py-2 text-xs font-black text-slate-700">Command Center</a>
          </nav>
        </header>

        <section className="grid gap-4 lg:grid-cols-[minmax(320px,400px)_1fr]">
          <form onSubmit={(event) => void submit(event)} className="rounded-lg border border-slate-300 bg-white p-4 shadow-sm">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Incoming message</div>
                <div className="mt-1 text-lg font-black text-slate-950">Guest text</div>
              </div>
              <span className={`rounded border px-2 py-1 text-[10px] font-black uppercase tracking-widest ${urgencyClass(urgency)}`}>{label(urgency ?? "waiting")}</span>
            </div>

            <textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              rows={7}
              className="mt-3 w-full resize-y rounded border border-slate-300 bg-slate-50 px-3 py-2 text-sm font-semibold leading-relaxed text-slate-950 outline-none focus:border-teal-500"
            />

            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              <label className="grid gap-1 text-[10px] font-black uppercase tracking-widest text-slate-500">
                Guest
                <input value={guestName} onChange={(event) => setGuestName(event.target.value)} placeholder="Optional" className="rounded border border-slate-300 bg-white px-3 py-2 text-xs font-bold normal-case tracking-normal text-slate-950 outline-none focus:border-teal-500" />
              </label>
              <label className="grid gap-1 text-[10px] font-black uppercase tracking-widest text-slate-500">
                Location
                <input value={location} onChange={(event) => setLocation(event.target.value)} className="rounded border border-slate-300 bg-white px-3 py-2 text-xs font-bold normal-case tracking-normal text-slate-950 outline-none focus:border-teal-500" />
              </label>
            </div>

            <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_auto] sm:items-end">
              <label className="grid gap-1 text-[10px] font-black uppercase tracking-widest text-slate-500">
                Channel
                <select value={channel} onChange={(event) => setChannel(event.target.value)} className="rounded border border-slate-300 bg-white px-3 py-2 text-xs font-bold normal-case tracking-normal text-slate-950 outline-none focus:border-teal-500">
                  <option value="in_app_guest_message">In-app guest message</option>
                  <option value="sms">SMS</option>
                  <option value="kiosk">Kiosk</option>
                  <option value="staff_entered">Staff entered</option>
                </select>
              </label>
              <label className="flex min-h-9 items-center gap-2 rounded border border-slate-300 bg-slate-50 px-3 py-2 text-xs font-bold text-slate-700">
                <input type="checkbox" checked={createTicket} onChange={(event) => setCreateTicket(event.target.checked)} className="h-4 w-4 accent-teal-600" />
                Ticket
              </label>
            </div>

            <button
              type="submit"
              disabled={isLoading || !message.trim()}
              className="mt-4 w-full rounded border border-slate-950 bg-slate-950 px-3 py-2 text-xs font-black uppercase tracking-widest text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:border-slate-300 disabled:bg-slate-200 disabled:text-slate-500"
            >
              {isLoading ? "Triaging" : "Generate reply"}
            </button>
            {error ? <div className="mt-3 rounded border border-rose-300 bg-rose-50 p-3 text-sm font-bold text-rose-800">{error}</div> : null}

            <div className="mt-4 border-t border-slate-200 pt-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Try a case</div>
              <div className="mt-2 grid gap-2">
                {examples.slice(0, 5).map((item) => (
                  <button key={item} type="button" onClick={() => setMessage(item)} className="rounded border border-slate-200 bg-slate-50 p-2 text-left text-xs font-semibold leading-relaxed text-slate-600 transition hover:border-teal-500 hover:bg-white hover:text-slate-950">
                    {item}
                  </button>
                ))}
              </div>
            </div>
          </form>

          <div className="space-y-4">
            <section className="rounded-lg border border-slate-300 bg-white p-4 shadow-sm">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0">
                  <div className="text-[10px] font-black uppercase tracking-widest text-teal-700">LLM response</div>
                  <h2 className="mt-1 text-2xl font-black text-slate-950">Suggested guest reply</h2>
                </div>
                <div className="flex flex-wrap gap-2">
                  {responseMeta.map(([key, value]) => (
                    <span key={key} className="rounded border border-slate-300 bg-slate-50 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-600">
                      {key}: {value}
                    </span>
                  ))}
                </div>
              </div>

              <div className="mt-4 rounded border border-teal-200 bg-teal-50 p-4">
                <p className="text-lg font-semibold leading-relaxed text-slate-950">{replyText}</p>
                {llmResponse?.next_step ? <div className="mt-3 text-xs font-black uppercase tracking-widest text-teal-800">Next step: {llmResponse.next_step}</div> : null}
              </div>

              {!llmIsLive && result ? (
                <div className="mt-3 rounded border border-amber-200 bg-amber-50 p-3 text-xs font-semibold leading-relaxed text-amber-900">
                  LLM response object is present, but the provider returned {label(responseStatus)}. The UI is showing the safe deterministic reply from the same triage contract.
                </div>
              ) : null}

              <div className="mt-4 grid gap-2 md:grid-cols-4">
                {decisionStats.map(([key, value]) => (
                  <div key={key} className="rounded border border-slate-200 bg-slate-50 p-3">
                    <div className="text-[9px] font-black uppercase tracking-widest text-slate-500">{key}</div>
                    <div className="mt-1 text-sm font-black text-slate-950">{value}</div>
                  </div>
                ))}
              </div>

              <div className="mt-3 h-2 overflow-hidden rounded bg-slate-100">
                <div style={meterStyle} className="h-full bg-teal-600" />
              </div>
              <div className="mt-2 flex justify-between text-[10px] font-black uppercase tracking-widest text-slate-500">
                <span>Confidence {confidence}%</span>
                <span>{label(result?.understanding?.status ?? "not checked")}</span>
              </div>
              {matchedTerms.length ? (
                <div className="mt-3 flex flex-wrap gap-2">
                  {matchedTerms.slice(0, 6).map((term) => (
                    <span key={term} className="rounded border border-teal-200 bg-white px-2 py-1 text-[10px] font-black uppercase tracking-widest text-teal-800">
                      {label(term)}
                    </span>
                  ))}
                </div>
              ) : null}
            </section>

            <section className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-lg border border-slate-300 bg-white p-4 shadow-sm">
                <div className="text-[10px] font-black uppercase tracking-widest text-amber-700">Human handoff</div>
                <h2 className="mt-1 text-xl font-black text-slate-950">{result?.routing?.human_ack_required ? "Review required" : "Standard route"}</h2>
                <div className="mt-3 rounded border border-slate-200 bg-slate-50 p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Ticket</div>
                  <div className="mt-1 text-sm font-black text-slate-950">{ticket?.id ?? "No ticket created"}</div>
                  <div className="mt-1 text-xs font-bold text-slate-500">{ticket ? `${label(ticket.issue_type)} / ${label(ticket.severity)} / ${label(ticket.assigned_team)}` : "Enable ticket creation and submit to create one."}</div>
                </div>
                <div className="mt-3 grid gap-2">
                  {(checklist.length ? checklist : ["Checklist appears after triage."]).slice(0, 4).map((item, index) => (
                    <div key={`${item}-${index}`} className="rounded border border-slate-200 bg-white p-2 text-xs font-semibold leading-relaxed text-slate-700">{item}</div>
                  ))}
                </div>
              </div>

              <div className="rounded-lg border border-slate-300 bg-white p-4 shadow-sm">
                <div className="text-[10px] font-black uppercase tracking-widest text-rose-700">Boundaries</div>
                <h2 className="mt-1 text-xl font-black text-slate-950">Blocked auto actions</h2>
                <div className="mt-3 grid gap-2">
                  {(forbidden.length ? forbidden : ["High-risk actions stay gated."]).slice(0, 4).map((item) => (
                    <div key={item} className="rounded border border-rose-200 bg-rose-50 p-2 text-xs font-black uppercase tracking-widest text-rose-800">{label(item)}</div>
                  ))}
                </div>
                <div className="mt-3 text-xs font-semibold leading-relaxed text-slate-500">{result?.boundary ?? "Guest triage can draft and route; humans approve high-risk action."}</div>
              </div>
            </section>

            <section className="rounded-lg border border-slate-300 bg-white p-4 shadow-sm">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <div className="text-[10px] font-black uppercase tracking-widest text-emerald-700">Grounding</div>
                  <h2 className="mt-1 text-xl font-black text-slate-950">{profileContext?.venue_name ?? "Venue profile pending"}</h2>
                </div>
                <a href="/venue-profile" className="rounded border border-slate-300 bg-slate-50 px-3 py-2 text-xs font-black text-slate-700">Venue profile</a>
              </div>

              <div className="mt-4 grid gap-3 lg:grid-cols-[1fr_280px]">
                <div className="grid gap-2 md:grid-cols-2">
                  {(profileLocations.length ? profileLocations : [{ name: "No matched profile place yet.", kind: "triage pending" }]).slice(0, 4).map((place, index) => (
                    <div key={`${place.name}-${index}`} className="rounded border border-slate-200 bg-slate-50 p-3">
                      <div className="text-sm font-black text-slate-950">{place.name}</div>
                      <div className="mt-1 text-[10px] font-black uppercase tracking-widest text-slate-500">{label(place.kind)}{place.zone_id ? ` / ${label(place.zone_id)}` : ""}</div>
                      {place.accessibility_note ? <div className="mt-2 text-xs font-semibold leading-relaxed text-slate-600">{place.accessibility_note}</div> : null}
                      {place.sensory_note ? <div className="mt-2 text-xs font-semibold leading-relaxed text-slate-600">{place.sensory_note}</div> : null}
                    </div>
                  ))}
                </div>
                <div className="rounded border border-slate-200 bg-slate-50 p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Memory</div>
                  <div className="mt-1 text-lg font-black text-slate-950">{memoryImpact?.memory_count ?? 0} signals</div>
                  <div className="mt-1 text-xs font-semibold leading-relaxed text-slate-600">{memoryImpact?.visible_benefit ?? "Stored triage memory can feed staff training scenarios."}</div>
                  {memorySources.length ? (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {memorySources.slice(0, 3).map(([source, count]) => (
                        <span key={source} className="rounded border border-slate-300 bg-white px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-600">{label(source)} {count}</span>
                      ))}
                    </div>
                  ) : null}
                  {profileLimitations.length ? <div className="mt-3 text-xs font-semibold leading-relaxed text-slate-500">{profileLimitations.slice(0, 2).join(" ")}</div> : null}
                </div>
              </div>
            </section>
          </div>
        </section>
      </div>
    </main>
  );
}
