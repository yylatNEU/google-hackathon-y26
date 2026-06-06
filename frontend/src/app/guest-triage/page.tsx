"use client";

import { FormEvent, useMemo, useState } from "react";
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
  boundary?: string;
};

const examples = [
  "I cannot find my six-year-old. She was next to me near the carousel and now she is gone.",
  "My friend is dizzy and looks pale. We have been in the sun for an hour and she says she might faint.",
  "A group cut the line and now people are yelling near the coaster merge.",
  "My father cannot stand in this sun for the queue. We need accessibility help but do not want to explain medical history in public.",
  "Where is the closest vegetarian food near the coaster?",
  "Where can we find a quiet cooling place and water refill?",
  "Can I bring a drone for filming behind the theater?",
  "I want a refund. The ride was closed and nobody told us before we waited.",
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
  const [message, setMessage] = useState(examples[0]);
  const [guestName, setGuestName] = useState("");
  const [location, setLocation] = useState("Carousel");
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
  const meterStyle = useMemo(() => ({ width: `${Math.max(0, Math.min(100, score))}%` }), [score]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const trimmed = message.trim();
    if (!trimmed) return;
    setIsLoading(true);
    setError("");
    try {
      const response = await fetchParkPulseApi("/api/park/guest-message-triage", {
        method: "POST",
        headers: { "content-type": "application/json", "x-parkpulse-role": "onsite_worker" },
        body: JSON.stringify({ message: trimmed, guestName, location, channel, createTicket }),
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

  return (
    <main className="min-h-screen bg-[#071014] px-4 py-5 font-sans text-slate-100 lg:px-8">
      <div className="mx-auto max-w-[1450px] space-y-4">
        <header className="rounded-lg border border-cyan-300/30 bg-[#0d171b] p-5 shadow-xl shadow-cyan-950/20">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">ParkPulse Guest Triage</div>
              <h1 className="mt-2 text-3xl font-black tracking-normal text-slate-50 lg:text-5xl">Guest Message Triage</h1>
              <p className="mt-3 max-w-4xl text-sm leading-relaxed text-slate-400">
                Classify incoming guest text, score urgency, create a routed live issue ticket, and draft the first safe response. High-risk reactions stay human-acknowledged.
              </p>
            </div>
            <nav className="flex flex-wrap gap-2">
              <a href="/staff-training" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-teal-300">Staff training</a>
              <a href="/" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-300">Command</a>
            </nav>
          </div>
        </header>

        <section className="grid gap-4 xl:grid-cols-[420px_1fr]">
          <form onSubmit={(event) => void submit(event)} className="rounded-lg border border-slate-800 bg-[#0d171b] p-4">
            <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Incoming guest message</div>
            <label className="mt-3 grid gap-1 text-[10px] font-black uppercase tracking-widest text-slate-500">
              Message
              <textarea
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                rows={8}
                className="resize-y rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm font-semibold normal-case leading-relaxed tracking-normal text-slate-100 outline-none focus:border-cyan-300"
              />
            </label>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              <label className="grid gap-1 text-[10px] font-black uppercase tracking-widest text-slate-500">
                Guest
                <input value={guestName} onChange={(event) => setGuestName(event.target.value)} placeholder="Optional" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-bold normal-case tracking-normal text-slate-100 outline-none focus:border-cyan-300" />
              </label>
              <label className="grid gap-1 text-[10px] font-black uppercase tracking-widest text-slate-500">
                Location
                <input value={location} onChange={(event) => setLocation(event.target.value)} className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-bold normal-case tracking-normal text-slate-100 outline-none focus:border-cyan-300" />
              </label>
            </div>
            <label className="mt-3 grid gap-1 text-[10px] font-black uppercase tracking-widest text-slate-500">
              Channel
              <select value={channel} onChange={(event) => setChannel(event.target.value)} className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-bold normal-case tracking-normal text-slate-100 outline-none focus:border-cyan-300">
                <option value="in_app_guest_message">In-app guest message</option>
                <option value="sms">SMS</option>
                <option value="kiosk">Kiosk</option>
                <option value="staff_entered">Staff entered</option>
              </select>
            </label>
            <label className="mt-3 flex items-center gap-2 text-xs font-bold text-slate-300">
              <input type="checkbox" checked={createTicket} onChange={(event) => setCreateTicket(event.target.checked)} className="h-4 w-4 accent-cyan-300" />
              Create routed live issue ticket
            </label>
            <button
              type="submit"
              disabled={isLoading || !message.trim()}
              className="mt-4 w-full rounded border border-cyan-300 bg-cyan-300 px-3 py-2 text-xs font-black uppercase tracking-widest text-slate-950 transition hover:bg-cyan-200 disabled:opacity-50"
            >
              {isLoading ? "Triaging..." : "Triage message"}
            </button>
            {error && <div className="mt-3 rounded border border-rose-300/40 bg-rose-300/10 p-3 text-sm font-bold text-rose-100">{error}</div>}
            <div className="mt-4 grid gap-2">
              {examples.map((item) => (
                <button key={item} type="button" onClick={() => setMessage(item)} className="rounded border border-slate-800 bg-slate-950 p-2 text-left text-xs font-semibold leading-relaxed text-slate-400 transition hover:border-cyan-300 hover:text-slate-100">
                  {item}
                </button>
              ))}
            </div>
          </form>

          <div className="space-y-4">
            <section className="grid gap-3 md:grid-cols-4">
              <div className="rounded-lg border border-slate-800 bg-[#0d171b] p-4 md:col-span-2">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Classification</div>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <span className={`rounded border px-3 py-2 text-xs font-black uppercase tracking-widest ${urgencyClass(urgency)}`}>{label(urgency ?? "not triaged")}</span>
                  <span className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200">{label(result?.classification?.issue_type)}</span>
                  <span className="rounded border border-lime-300/30 bg-lime-300/10 px-3 py-2 text-xs font-black uppercase tracking-widest text-lime-100">{label(result?.understanding?.status ?? "not checked")}</span>
                </div>
                <div className="mt-4 h-2 overflow-hidden rounded bg-slate-950">
                  <div style={meterStyle} className="h-full bg-cyan-300" />
                </div>
                <div className="mt-2 flex justify-between text-[10px] font-black uppercase tracking-widest text-slate-500">
                  <span>Urgency {score}/100</span>
                  <span>Confidence {confidence}%</span>
                </div>
                <div className="mt-3 text-xs font-bold text-slate-500">Category {label(result?.understanding?.category)}</div>
              </div>
              <div className="rounded-lg border border-slate-800 bg-[#0d171b] p-4">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Owner</div>
                <div className="mt-3 text-xl font-black text-slate-50">{label(result?.routing?.assigned_team)}</div>
                <div className="mt-2 text-xs font-bold text-slate-500">{label(result?.routing?.human_review_place ?? "auto route")}</div>
              </div>
              <div className="rounded-lg border border-slate-800 bg-[#0d171b] p-4">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">SLA</div>
                <div className="mt-3 text-xl font-black text-slate-50">{result?.routing?.sla_minutes ?? "--"} min</div>
                <div className="mt-2 text-xs font-bold text-slate-500">Human ack {result?.routing?.human_ack_required ? "required" : "not required"}</div>
              </div>
            </section>

            <section className="rounded-lg border border-lime-300/20 bg-[#0d171b] p-4">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <div className="text-[10px] font-black uppercase tracking-widest text-lime-300">Park profile grounding</div>
                  <h2 className="mt-1 text-xl font-black text-slate-50">{profileContext?.venue_name ?? "No profile answer yet"}</h2>
                  <div className="mt-2 flex flex-wrap gap-2 text-[10px] font-black uppercase tracking-widest">
                    <span className="rounded border border-lime-300/30 bg-lime-300/10 px-2 py-1 text-lime-100">{label(profileContext?.status ?? "pending")}</span>
                    <span className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-slate-300">{label(profileContext?.category)}</span>
                    <span className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-slate-300">{label(profileContext?.readiness_status)}</span>
                    {profileContext?.human_review_required ? <span className="rounded border border-amber-300/40 bg-amber-300/10 px-2 py-1 text-amber-100">Human review</span> : null}
                  </div>
                </div>
                <a href="/venue-profile" className="rounded border border-lime-300/40 bg-slate-950 px-3 py-2 text-xs font-black text-lime-100 transition hover:border-lime-200">Venue profile</a>
              </div>
              <div className="mt-4 grid gap-3 lg:grid-cols-[1fr_340px]">
                <div className="grid gap-2">
                  {(profileLocations.length ? profileLocations : [{ name: "No matched profile place yet.", kind: "triage pending" }]).slice(0, 5).map((place, index) => (
                    <div key={`${place.name}-${index}`} className="rounded border border-slate-800 bg-slate-950 p-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <div className="text-sm font-black text-slate-100">{place.name}</div>
                        <span className="rounded border border-slate-700 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-400">{label(place.kind)}</span>
                        {place.zone_id ? <span className="rounded border border-slate-700 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-400">{label(place.zone_id)}</span> : null}
                      </div>
                      {place.accessibility_note ? <div className="mt-2 text-xs font-semibold leading-relaxed text-slate-400">{place.accessibility_note}</div> : null}
                      {place.sensory_note ? <div className="mt-2 text-xs font-semibold leading-relaxed text-slate-400">{place.sensory_note}</div> : null}
                      {place.services?.length || place.dietary_tags?.length ? (
                        <div className="mt-2 text-[10px] font-black uppercase tracking-widest text-lime-200">{[...(place.services ?? []), ...(place.dietary_tags ?? [])].join(" | ")}</div>
                      ) : null}
                    </div>
                  ))}
                </div>
                <div className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Limits and handoff</div>
                  <div className="mt-2 space-y-2">
                    {(profileLimitations.length ? profileLimitations : ["Profile context appears after triage."]).slice(0, 4).map((item) => (
                      <div key={item} className="text-xs font-semibold leading-relaxed text-slate-400">{item}</div>
                    ))}
                  </div>
                  {profileContext?.human_review_place ? <div className="mt-3 rounded border border-amber-300/30 bg-amber-300/10 p-2 text-xs font-black uppercase tracking-widest text-amber-100">{label(profileContext.human_review_place)}</div> : null}
                </div>
              </div>
            </section>

            <section className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-lg border border-slate-800 bg-[#0d171b] p-4">
                <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Guest reply draft</div>
                <p className="mt-3 text-sm font-semibold leading-relaxed text-slate-200">{result?.reaction?.guest_reply_draft ?? "Triage a guest message to generate a safe first response."}</p>
                <div className="mt-4 flex flex-wrap gap-2">
                  {matchedTerms.map((term) => <span key={term} className="rounded border border-cyan-300/30 bg-cyan-300/10 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-cyan-100">{term}</span>)}
                </div>
              </div>
              <div className="rounded-lg border border-slate-800 bg-[#0d171b] p-4">
                <div className="text-[10px] font-black uppercase tracking-widest text-amber-300">Staff checklist</div>
                <div className="mt-3 space-y-2">
                  {(checklist.length ? checklist : ["Triage a message to generate a checklist."]).map((item, index) => (
                    <div key={`${item}-${index}`} className="rounded border border-slate-800 bg-slate-950 p-2 text-xs font-semibold text-slate-300">{item}</div>
                  ))}
                </div>
              </div>
            </section>

            <section className="grid gap-4 lg:grid-cols-[1fr_320px]">
              <div className="rounded-lg border border-slate-800 bg-[#0d171b] p-4">
                <div className="text-[10px] font-black uppercase tracking-widest text-emerald-300">Live ticket</div>
                {ticket ? (
                  <div className="mt-3 rounded border border-emerald-300/20 bg-emerald-300/5 p-3 text-sm">
                    <div className="font-black text-slate-100">{ticket.id}</div>
                    <div className="mt-2 flex flex-wrap gap-2 text-[10px] font-black uppercase tracking-widest text-emerald-200">
                      <span>{label(ticket.issue_type)}</span>
                      <span>{label(ticket.severity)}</span>
                      <span>{label(ticket.assigned_team)}</span>
                      <span>Live ops ticket {ticket.live_ops_authority ? "yes" : "no"}</span>
                      <span>Human ack {ticket.requires_human_ack ? "yes" : "no"}</span>
                    </div>
                  </div>
                ) : (
                  <div className="mt-3 rounded border border-dashed border-slate-700 bg-slate-950 p-3 text-sm font-bold text-slate-500">No ticket created yet.</div>
                )}
              </div>
              <div className="rounded-lg border border-slate-800 bg-[#0d171b] p-4">
                <div className="text-[10px] font-black uppercase tracking-widest text-rose-300">Blocked auto actions</div>
                <div className="mt-3 space-y-2">
                  {(forbidden.length ? forbidden : ["High-risk actions stay gated."]).map((item) => (
                    <div key={item} className="rounded border border-rose-300/20 bg-rose-300/5 p-2 text-xs font-black uppercase tracking-widest text-rose-100">{label(item)}</div>
                  ))}
                </div>
              </div>
            </section>
          </div>
        </section>
      </div>
    </main>
  );
}
