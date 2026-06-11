"use client";

import { useState } from "react";

type Tone = {
  badge: string;
  text: string;
  border: string;
  wash: string;
};

const tones: Record<string, Tone> = {
  cyan: { badge: "bg-cyan-300 text-neutral-950", text: "text-cyan-300", border: "border-cyan-300/25", wash: "bg-cyan-300/10" },
  emerald: { badge: "bg-emerald-300 text-neutral-950", text: "text-emerald-300", border: "border-emerald-300/25", wash: "bg-emerald-300/10" },
  violet: { badge: "bg-violet-300 text-neutral-950", text: "text-violet-300", border: "border-violet-300/25", wash: "bg-violet-300/10" },
  teal: { badge: "bg-teal-300 text-neutral-950", text: "text-teal-300", border: "border-teal-300/25", wash: "bg-teal-300/10" },
  amber: { badge: "bg-amber-300 text-neutral-950", text: "text-amber-300", border: "border-amber-300/25", wash: "bg-amber-300/10" },
  rose: { badge: "bg-rose-300 text-neutral-950", text: "text-rose-300", border: "border-rose-300/25", wash: "bg-rose-300/10" },
  blue: { badge: "bg-blue-300 text-neutral-950", text: "text-blue-300", border: "border-blue-300/25", wash: "bg-blue-300/10" },
};

const chapterLinks = [
  { href: "#foundation", label: "Foundation" },
  { href: "#ops", label: "Ops" },
  { href: "#event-agent", label: "Event" },
  { href: "#guest-care", label: "Guest Care" },
  { href: "#training", label: "Training" },
  { href: "#trust", label: "Trust" },
  { href: "#proof", label: "Proof" },
  { href: "#architecture", label: "Architecture" },
  { href: "#depth", label: "Depth" },
  { href: "#demo", label: "Demo" },
];

const launchStats = [
  { value: "4", label: "agent surfaces" },
  { value: "10", label: "demo stops" },
  { value: "6", label: "GCP roles" },
  { value: "1", label: "memory loop" },
];

const capabilityMap = [
  {
    id: "foundation",
    label: "Venue Memory",
    route: "/venue-profile",
    tone: "emerald",
    headline: "The park model every agent shares.",
    body: "Venue facts, paths, policies, and accessibility rules.",
    proof: ["Venue Profile", "MongoDB park_state", "Module bindings"],
  },
  {
    id: "event",
    label: "Event Agent",
    route: "/experience-studio",
    tone: "violet",
    headline: "Event plans grounded in venue memory.",
    body: "Routes, signage, scripts, claims, and review history.",
    proof: ["Experience Studio", "Creative memory", "Review gates"],
  },
  {
    id: "guest",
    label: "Guest Care",
    route: "/guest-triage",
    tone: "cyan",
    headline: "Guest needs become reviewable action.",
    body: "Urgency, reply, route, ticket, and review boundary.",
    proof: ["Guest Triage", "Accessibility Journey", "Human review"],
  },
  {
    id: "ops",
    label: "Ops Control",
    route: "/ops",
    tone: "amber",
    headline: "Live pressure becomes an approved plan.",
    body: "Signals, simulation, policy gates, dispatch, and evals.",
    proof: ["Command Center", "Ops Agent", "Policy Gate"],
  },
  {
    id: "training",
    label: "Employee Training",
    route: "/staff-training",
    tone: "teal",
    headline: "Incidents become staff readiness.",
    body: "Roleplay, scoring, readiness holds, and gap tickets.",
    proof: ["Staff Training", "Readiness packets", "Learning boundary"],
  },
  {
    id: "trust",
    label: "Agent Trust",
    route: "/agent-handshake",
    tone: "blue",
    headline: "Agent handoffs carry scoped authority.",
    body: "Identity, delegation, challenge, handoff, receipt.",
    proof: ["Agent Handshake", "Delegation scope", "Signed receipt"],
  },
];

const foundationRows = [
  ["Venue graph", "Zones, paths, owners, dining, accessibility"],
  ["Policy memory", "Safety, labor, privacy, dispatch boundaries"],
  ["Experience rules", "Brand, season, route, sensory context"],
  ["Retrieval layer", "MongoDB plus Atlas Vector Search"],
];

const eventFlow = [
  ["Brief", "Audience, route, sensory profile, channels."],
  ["Ground", "Retrieve approved venue memory."],
  ["Generate", "Draft copy, signage, cues, scripts."],
  ["Review", "Hold risky claims for approval."],
  ["Publish", "Ship the approved event package."],
];

const eventReceiptRows = [
  ["Selected", "Family route with indoor rest stops."],
  ["Rejected", "Blackout overlay; sensory and staffing risk."],
  ["Review", "Wait-time and accessibility claims held."],
  ["Memory", "Drafts, feedback, revisions, rules updated."],
];

const guestCareCards = [
  {
    title: "Guest Triage",
    route: "/guest-triage",
    body: "Classify urgency, draft reply, route ticket.",
    checks: ["Urgency", "Safe reply", "Ticket route", "Escalation"],
  },
  {
    title: "Accessibility Journey",
    route: "/accessibility-journey",
    body: "Build low-walking, sensory, allergy, cooling plans.",
    checks: ["Mobility", "Sensory", "Allergy", "Cooling"],
  },
  {
    title: "Guest Memory",
    route: "#architecture",
    body: "Keep reviewed patterns without leaking sensitive details.",
    checks: ["PII scoped", "Review label", "Outcome", "Retrieval"],
  },
];

const guestCareReceiptRows = [
  ["Message", "Overwhelmed child; quiet route; peanut-safe food."],
  ["Triage", "Urgency 82; accessibility and allergy flags."],
  ["Route", "Low-walking path, cooling break, restroom stop."],
  ["Review", "Medical and guarantee language held."],
];

const opsArchitectureNodes = [
  { id: "live", label: "Live Signals", tag: "Pub/Sub", x: 90, y: 105, tone: "intake" },
  { id: "operator", label: "Operator Intent", tag: "Human", x: 90, y: 235, tone: "intake" },
  { id: "venue", label: "Venue Memory", tag: "MongoDB", x: 90, y: 365, tone: "memory" },
  { id: "packet", label: "Incident Packet", tag: "Normalize", x: 270, y: 235, tone: "intake" },
  { id: "features", label: "Feature Builder", tag: "Dataflow", x: 450, y: 145, tone: "structure" },
  { id: "candidates", label: "Candidate Actions", tag: "Planner", x: 450, y: 325, tone: "structure" },
  { id: "safety", label: "Safety Gate", tag: "Reject", x: 630, y: 80, tone: "reject" },
  { id: "privacy", label: "Privacy Gate", tag: "Reject", x: 630, y: 190, tone: "reject" },
  { id: "labor", label: "Labor Gate", tag: "Reject", x: 630, y: 300, tone: "reject" },
  { id: "sim", label: "Capacity Twin", tag: "Vertex", x: 630, y: 410, tone: "reject" },
  { id: "ride", label: "Ride Agent", tag: "Negotiate", x: 810, y: 80, tone: "negotiate" },
  { id: "guest", label: "Guest Flow Agent", tag: "Negotiate", x: 810, y: 190, tone: "negotiate" },
  { id: "food", label: "Food + Staff Agent", tag: "Negotiate", x: 810, y: 300, tone: "negotiate" },
  { id: "compliance", label: "Compliance Agent", tag: "Policy", x: 810, y: 410, tone: "policy" },
  { id: "arbiter", label: "Tradeoff Arbiter", tag: "Resolve", x: 990, y: 245, tone: "negotiate" },
  { id: "policy", label: "Policy Alignment", tag: "IAM + Rules", x: 990, y: 430, tone: "policy" },
  { id: "approval", label: "Human Approval", tag: "Review", x: 1160, y: 155, tone: "decide" },
  { id: "dispatch", label: "Dispatch Plan", tag: "Workflows", x: 1160, y: 315, tone: "decide" },
  { id: "memory", label: "Eval + Memory", tag: "Mongo + BQ", x: 1160, y: 505, tone: "memory" },
];

const opsArchitectureEdges = [
  ["live", "packet"], ["operator", "packet"], ["venue", "packet"],
  ["live", "features"], ["operator", "features"], ["venue", "features"],
  ["packet", "features"], ["packet", "candidates"],
  ["features", "candidates"], ["features", "safety"], ["features", "privacy"], ["features", "labor"], ["features", "sim"],
  ["candidates", "safety"], ["candidates", "privacy"], ["candidates", "labor"], ["candidates", "sim"],
  ["venue", "safety"], ["venue", "privacy"], ["venue", "labor"], ["venue", "compliance"], ["venue", "policy"],
  ["safety", "ride"], ["privacy", "guest"], ["labor", "food"], ["sim", "ride"], ["sim", "guest"], ["sim", "food"],
  ["safety", "compliance"], ["privacy", "compliance"], ["labor", "compliance"], ["sim", "compliance"],
  ["candidates", "ride"], ["candidates", "guest"], ["candidates", "food"], ["candidates", "compliance"],
  ["ride", "arbiter"], ["guest", "arbiter"], ["food", "arbiter"], ["compliance", "arbiter"],
  ["ride", "guest"], ["guest", "ride"], ["ride", "food"], ["food", "ride"], ["guest", "food"], ["food", "guest"],
  ["compliance", "ride"], ["compliance", "guest"], ["compliance", "food"],
  ["arbiter", "policy"], ["policy", "arbiter"],
  ["safety", "policy"], ["privacy", "policy"], ["labor", "policy"], ["sim", "policy"], ["compliance", "policy"],
  ["policy", "approval"], ["approval", "dispatch"], ["dispatch", "memory"], ["memory", "features"],
];

const opsNodeTones = {
  intake: { fill: "#082f49", stroke: "#67e8f9", text: "#ecfeff", tag: "#a5f3fc" },
  structure: { fill: "#1c1917", stroke: "#facc15", text: "#fff7ed", tag: "#fde68a" },
  reject: { fill: "#4c0519", stroke: "#fda4af", text: "#fff1f2", tag: "#fecdd3" },
  negotiate: { fill: "#312e81", stroke: "#c4b5fd", text: "#f5f3ff", tag: "#ddd6fe" },
  policy: { fill: "#052e16", stroke: "#86efac", text: "#f0fdf4", tag: "#bbf7d0" },
  decide: { fill: "#022c22", stroke: "#5eead4", text: "#f0fdfa", tag: "#99f6e4" },
  memory: { fill: "#2e1065", stroke: "#d8b4fe", text: "#faf5ff", tag: "#e9d5ff" },
};

const opsArchitectureNodeById = Object.fromEntries(opsArchitectureNodes.map((node) => [node.id, node]));

const opsArchitectureDetailRows = [
  {
    label: "Intake layer",
    headline: "Turn noisy inputs into one case.",
    body: "Events, operator intent, and venue memory become one packet.",
    proof: ["Live Signals", "Operator Intent", "Venue Memory", "Incident Packet"],
  },
  {
    label: "Reject layer",
    headline: "Remove unsafe options early.",
    body: "Safety, privacy, labor, and capacity gates block bad moves.",
    proof: ["Safety Gate", "Privacy Gate", "Labor Gate", "Capacity Twin"],
  },
  {
    label: "Negotiation layer",
    headline: "Departments negotiate the tradeoff.",
    body: "Ride, flow, food, staff, and compliance trade constraints.",
    proof: ["Ride Agent", "Guest Flow Agent", "Food + Staff Agent", "Tradeoff Arbiter"],
  },
  {
    label: "Policy alignment",
    headline: "Policy decides what can move.",
    body: "IAM, venue policy, and review rules decide authority.",
    proof: ["Compliance Agent", "Policy Alignment", "Human Approval"],
  },
  {
    label: "Decision writeback",
    headline: "The outcome becomes memory.",
    body: "Workflows executes; MongoDB and BigQuery remember.",
    proof: ["Dispatch Plan", "Eval + Memory", "Mongo + BQ"],
  },
];

const opsArchitectureArtifacts = [
  ["Candidates", "All plausible actions before gates."],
  ["Rejected", "Blocked options with reasons."],
  ["Negotiation", "Department counterproposals."],
  ["Policy", "Approval, IAM, dispatch boundary."],
  ["Memory", "Decision, eval, reviewer label."],
];

const opsLiveProofRows = [
  ["Run", "Trigger an incident review."],
  ["Inspect", "See rejects, policy, dispatch, eval."],
  ["Ask why", "Question the selected plan."],
  ["Verify", "Audit evidence and review ledgers."],
];

const opsMemoryReplayRows = [
  ["Run 01", "Unsafe candidates are rejected."],
  ["Mongo write", "agent_decisions stores the receipt."],
  ["Run 02", "Prior outcome changes the next plan."],
];

const opsArtifactRows = [
  ["Selected action", "Pause intake, route guests away from Coaster Plaza, protect breaks, add Food Court 2 capacity, and hold ride reopening."],
  ["Rejected alternative", "Dump all coaster guests into Indoor Ride B; rejected because the nearby queue is already 55 minutes and accessibility walking load rises."],
  ["Policy result", "Human review required for dispatch; safety clearance required for reopening; sensitive guest details removed from worker payloads."],
  ["Memory write", "agent_decisions stores evidence, selected action, rejected options, policy gate, dispatch payloads, eval score, and outcome label."],
];

const trainingLoop = [
  ["Scenario", "A real issue becomes safe roleplay."],
  ["Roleplay", "The employee practices the response."],
  ["Evaluate", "Policy, empathy, clarity, escalation scored."],
  ["Readiness", "Holds and assignments show readiness."],
  ["Learn", "Gaps become reviewed training signals."],
];

const trainingReceiptRows = [
  ["Scenario", "Safety delay plus walking and food confusion."],
  ["Rubric", "Empathy 88, clarity 82, policy 91."],
  ["Critical miss", "Priority-access promise capped the score."],
  ["Gap", "Ticket for compensation and handoff language."],
];

const handshakeRounds = [
  {
    label: "Verify",
    actor: "Personal agent",
    message: "A guest agent asks ParkPulse to recover a family visit after a safety delay.",
    platform: "ParkPulse verifies identity, party context, delegation scope, and the exact authority the agent does not have.",
    policy: "No purchase, compensation, priority access, or safety override authority.",
    artifact: "verified delegation",
  },
  {
    label: "Offer",
    actor: "Park agent",
    message: "ParkPulse proposes a shaded route, alternate attraction, and food pickup window.",
    platform: "The proposal is grounded in live queue state, venue profile, accessibility constraints, and prior similar outcomes.",
    policy: "Allowed as recommendation; worker and guest delivery remain gated.",
    artifact: "proposal receipt",
  },
  {
    label: "Challenge",
    actor: "External agent",
    message: "The external agent counters with priority access and automatic compensation.",
    platform: "ParkPulse separates negotiable service recovery from requests that exceed delegated authority.",
    policy: "Priority access blocked; compensation routed to manager approval.",
    artifact: "policy challenge",
  },
  {
    label: "Handoff",
    actor: "Policy engine",
    message: "Approved parts become scoped payloads for queue, food, and guest-experience teams.",
    platform: "Internal agents receive only the minimum data needed to execute their part of the plan.",
    policy: "Safety, privacy, commerce, and labor checks pass.",
    artifact: "handoff envelope",
  },
  {
    label: "Sign",
    actor: "ParkPulse",
    message: "ParkPulse signs the final plan, notifies the guest agent, and records the outcome.",
    platform: "Workflows records approval, delivery is tracked, BigQuery receives the row, and MongoDB stores the trust session.",
    policy: "Signed receipt is ready for audit, replay, and revocation review.",
    artifact: "signed receipt",
  },
];

const proofRows = [
  ["Policy gate", "Unsafe authority stops here."],
  ["Eval receipt", "Groundedness, capacity, staff stress, policy."],
  ["Monitor packet", "Evidence, review ledger, runtime state."],
  ["Learning write", "Outcome, label, reusable rule."],
];

const learningLoopRows = [
  ["Outcome", "Did pressure fall?"],
  ["Evaluate", "Score the decision."],
  ["Review", "Accept, edit, block, or label."],
  ["Remember", "Store evidence and outcome."],
  ["Improve", "Retrieve better context next time."],
];

const architectureMatrixRows = [
  ["Event Agent", "Vertex AI Gemini, Cloud Run, Pub/Sub", "experience_studio_*", "Draft, review gate, channel package, learning rule"],
  ["Guest Care", "Cloud Run, Workflows, FCM", "guest_messages, venue_profile", "Urgency score, safe reply, accessibility route, ticket"],
  ["Live Ops", "Pub/Sub, Eventarc, Workflows, BigQuery", "park_state, agent_decisions, eval_results", "Selected action, rejected alternatives, dispatch receipt"],
  ["Employee Training", "Cloud Run, BigQuery-ready analytics", "training_*", "Rubric receipt, readiness hold, training-gap ticket"],
  ["Agent Trust", "Cloud Run, Workflows, FCM", "trust_sessions, agent_decisions", "Delegation scope, policy challenge, signed receipt"],
];

const depthRows = [
  ["Real consequences", "Crowds, labor, privacy, safety, and communication move together."],
  ["Operational authority", "The system prepares actions, not advice."],
  ["Persistent memory", "Every reviewed result shapes the next run."],
  ["Bigger than parks", "The same loop fits campuses, stadiums, resorts, airports, and malls."],
];

const gcpTools = [
  ["Cloud Run", "Runtime", "Private backend execution."],
  ["Vertex AI Gemini", "Reasoning", "Tradeoff explanation and payload drafting."],
  ["Pub/Sub + Eventarc", "Intake", "Live event movement."],
  ["Cloud Workflows", "Approval", "Human-gated execution."],
  ["Firebase Cloud Messaging", "Delivery", "Worker and guest delivery topics."],
  ["Dataflow + BigQuery", "Analytics", "Outcome rows and eval backtests."],
];

const mongoMemory = [
  ["park_state", "Live operating state."],
  ["venue_profile", "Paths, rules, brand, constraints."],
  ["experience_studio_*", "Drafts, revisions, learning rules."],
  ["agent_decisions", "Evidence, action, policy, outcome."],
  ["guest_messages", "Reviewed replies and tickets."],
  ["training_*", "Roleplay, readiness, gap tickets."],
  ["trust_sessions", "Delegation, challenges, signatures."],
  ["eval_results", "Safety and actionability scorecards."],
];

const demoSteps = [
  ["Ground venue memory", "/venue-profile", "Approved graph, rules, accessibility, owners."],
  ["Create an event", "/experience-studio", "Same memory, guest-facing plan, review gate."],
  ["Add guest constraints", "/accessibility-journey", "Mobility, sensory, allergy, cooling."],
  ["Triage live issue", "/guest-triage", "Urgency, reply, ticket, escalation."],
  ["Run ops loop", "/ops", "Reject, approve, dispatch, write receipt."],
  ["Ask why", "/ops-agent", "Selected plan versus blocked options."],
  ["Validate scorer", "/model-validation", "Decision quality under live state."],
  ["Train staff", "/staff-training", "Roleplay, rubric, readiness hold."],
  ["Negotiate safely", "/agent-handshake", "Delegation, challenge, signed receipt."],
  ["Audit runtime", "/monitor", "Evidence, evals, review ledger."],
  ["Map architecture", "#architecture", "GCP control plane plus Mongo memory."],
];

function SectionLabel({ children, tone = "text-cyan-300" }: { children: React.ReactNode; tone?: string }) {
  return <div className={`text-xs font-black uppercase tracking-[0.28em] ${tone}`}>{children}</div>;
}

function MetricStrip() {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {launchStats.map((stat) => (
        <div key={stat.label}>
          <div className="text-2xl font-black text-white">{stat.value}</div>
          <div className="mt-1 text-xs leading-4 text-neutral-400">{stat.label}</div>
        </div>
      ))}
    </div>
  );
}

export default function LaunchPage() {
  const [activeHandshakeIndex, setActiveHandshakeIndex] = useState(0);
  const activeHandshake = handshakeRounds[activeHandshakeIndex] ?? handshakeRounds[0];

  return (
    <main className="min-h-screen bg-neutral-950 text-white">
      <nav className="sticky top-0 z-30 border-b border-white/10 bg-neutral-950/90 px-5 py-4 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4">
          <a href="/" className="text-sm font-black text-white">ParkPulse</a>
          <div className="hidden items-center gap-1 xl:flex">
            {chapterLinks.map((link) => (
              <a key={link.href} href={link.href} className="rounded-full px-3 py-2 text-xs font-bold text-neutral-400 transition hover:bg-white/10 hover:text-white">
                {link.label}
              </a>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <a href="/ops" className="rounded-full border border-white/15 px-4 py-2 text-xs font-bold text-neutral-200 transition hover:border-white/40 hover:text-white">Command Center</a>
            <a href="#demo" className="hidden rounded-full bg-white px-4 py-2 text-xs font-black text-neutral-950 transition hover:bg-cyan-100 sm:inline-flex">Demo Path</a>
          </div>
        </div>
      </nav>

      <section className="relative overflow-hidden px-5 pt-20 pb-12 lg:pt-28">
        <div className="mx-auto grid max-w-7xl gap-12 lg:grid-cols-[0.82fr_1.18fr] lg:items-center">
          <div>
            <SectionLabel>ParkPulse Launch</SectionLabel>
            <h1 className="mt-6 max-w-5xl text-5xl font-black leading-[0.96] tracking-normal text-white sm:text-7xl lg:text-7xl">
              The operating memory for a live park.
            </h1>
            <p className="mt-7 max-w-2xl text-lg leading-8 text-neutral-300 sm:text-xl">
              One shared system for events, guests, operations, training, agent trust, and audit.
            </p>
            <div className="mt-9 flex flex-wrap gap-3">
              <a href="#foundation" className="rounded-full bg-white px-5 py-3 text-sm font-black text-neutral-950 transition hover:bg-cyan-100">Start the story</a>
              <a href="#demo" className="rounded-full border border-white/20 px-5 py-3 text-sm font-black text-white transition hover:border-cyan-200 hover:text-cyan-100">Judge demo path</a>
            </div>
          </div>

          <div className="relative">
            <div className="h-[520px] overflow-hidden rounded-[28px] border border-white/15 bg-neutral-900 shadow-2xl shadow-cyan-950/40 sm:h-[660px] lg:h-[760px]">
              <img
                src="/parkpulse-command-center.png"
                alt="ParkPulse command center showing park map, action plan, policy gate, and eval receipt"
                className="h-full w-full object-cover object-top"
              />
            </div>
            <div className="absolute -bottom-6 left-5 right-5 rounded-2xl border border-cyan-200/30 bg-neutral-950/92 p-4 shadow-2xl shadow-black/40 backdrop-blur">
              <MetricStrip />
            </div>
          </div>
        </div>
      </section>

      <section id="foundation" className="bg-neutral-100 px-5 py-20 text-neutral-950">
        <div className="mx-auto max-w-7xl">
          <div className="grid gap-10 lg:grid-cols-[0.9fr_1.1fr] lg:items-end">
            <div>
              <SectionLabel tone="text-emerald-700">1 / Foundation Memory</SectionLabel>
              <h2 className="mt-4 text-4xl font-black leading-tight sm:text-6xl">Start with the park, not the prompt.</h2>
            </div>
            <p className="text-lg leading-8 text-neutral-600">
              Every agent starts from the same approved park facts, rules, and review boundaries.
            </p>
          </div>

          <div className="mt-12 grid gap-4 lg:grid-cols-2">
            {foundationRows.map(([label, value]) => (
              <div key={label} className="rounded-2xl border border-neutral-200 bg-white p-5">
                <div className="text-xs font-black uppercase tracking-[0.2em] text-emerald-700">{label}</div>
                <p className="mt-3 text-sm font-bold leading-6 text-neutral-600">{value}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="capabilities" className="px-5 py-20">
        <div className="mx-auto max-w-7xl">
          <div className="grid gap-10 lg:grid-cols-[0.85fr_1.15fr] lg:items-end">
            <div>
              <SectionLabel tone="text-cyan-300">2 / Built System</SectionLabel>
              <h2 className="mt-4 text-4xl font-black leading-tight text-white sm:text-6xl">Six surfaces, one memory layer.</h2>
            </div>
            <p className="text-lg leading-8 text-neutral-300">
              The built features are not separate demos. They share one GCP workflow and MongoDB memory backbone.
            </p>
          </div>

          <div className="mt-10 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {capabilityMap.map((capability, index) => {
              const tone = tones[capability.tone];
              return (
                <a key={capability.id} href={capability.route} className={`rounded-2xl border ${tone.border} bg-neutral-900 p-4 transition hover:border-white/40`}>
                  <div className="flex items-center justify-between gap-4">
                    <div className="text-3xl font-black text-white">{String(index + 1).padStart(2, "0")}</div>
                    <div className={`w-fit rounded-full px-2.5 py-1 text-[10px] font-black ${tone.badge}`}>{capability.route}</div>
                  </div>
                  <div className={`mt-5 text-xs font-black uppercase tracking-[0.22em] ${tone.text}`}>{capability.label}</div>
                  <h3 className="mt-3 text-2xl font-black leading-tight text-white">{capability.headline}</h3>
                  <p className="mt-3 text-xs font-bold leading-5 text-neutral-300">{capability.body}</p>
                  <div className="mt-4 flex flex-wrap gap-1.5">
                    {capability.proof.map((proof) => (
                      <span key={proof} className="rounded-full border border-white/15 px-2.5 py-1 text-[10px] font-black text-neutral-300">{proof}</span>
                    ))}
                  </div>
                </a>
              );
            })}
          </div>
        </div>
      </section>

      <section id="ops" className="bg-neutral-100 px-5 py-20 text-neutral-950">
        <div className="mx-auto max-w-7xl">
          <div className="grid gap-10 lg:grid-cols-[0.78fr_1.22fr] lg:items-end">
            <div>
              <SectionLabel tone="text-amber-700">3 / Operations Core</SectionLabel>
              <h2 className="mt-4 text-4xl font-black leading-tight sm:text-6xl">From park pressure to approved action.</h2>
            </div>
            <p className="text-lg leading-8 text-neutral-600">
              The moat is the control loop: intake, reject, negotiate, approve, dispatch, evaluate, remember.
            </p>
          </div>

          <div className="mt-12 rounded-[32px] border border-neutral-800 bg-neutral-950 p-5 text-white shadow-2xl shadow-neutral-950/30 sm:p-6">
            <div className="grid gap-6 lg:grid-cols-[1.15fr_0.85fr] lg:items-end">
              <div>
                <div className="text-xs font-black uppercase tracking-[0.24em] text-amber-300">Decision architecture</div>
                <h3 className="mt-3 text-3xl font-black leading-tight text-white">A control graph for real operations.</h3>
                <p className="mt-4 text-sm font-bold leading-6 text-neutral-400">
                  A 19-node graph turns pressure into approved action, not advice.
                </p>
              </div>
              <div>
                <div className="mt-6 grid grid-cols-2 gap-3">
                  <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4">
                    <div className="text-3xl font-black text-amber-300">{opsArchitectureNodes.length}</div>
                    <div className="mt-1 text-[10px] font-black uppercase tracking-[0.18em] text-neutral-500">Nodes</div>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4">
                    <div className="text-3xl font-black text-amber-300">{opsArchitectureEdges.length}</div>
                    <div className="mt-1 text-[10px] font-black uppercase tracking-[0.18em] text-neutral-500">Edges</div>
                  </div>
                </div>
                <div className="mt-5 space-y-2 text-xs font-black uppercase tracking-[0.16em] text-neutral-500">
                  <div>Intake {'->'} Reject</div>
                  <div>Reject {'->'} Negotiate</div>
                  <div>Negotiate {'->'} Align</div>
                  <div>Approve {'->'} Dispatch</div>
                  <div>Dispatch {'->'} Memory</div>
                </div>
              </div>
            </div>

            <div className="mt-6 overflow-hidden rounded-[28px] border border-white/10 bg-black">
              <div className="flex items-center justify-between gap-4 border-b border-white/10 px-5 py-4">
                <div className="text-xs font-black uppercase tracking-[0.24em] text-neutral-500">19 node / 60 edge decision graph</div>
                <div className="rounded-full border border-emerald-300/30 px-3 py-1 text-[10px] font-black uppercase tracking-[0.16em] text-emerald-200">General architecture</div>
              </div>
              <div className="overflow-x-auto">
                <svg viewBox="0 0 1240 620" className="w-full min-w-[980px]">
                  <defs>
                    <pattern id="ops-grid" width="24" height="24" patternUnits="userSpaceOnUse">
                      <path d="M 24 0 L 0 0 0 24" fill="none" stroke="#ffffff" strokeOpacity="0.055" strokeWidth="1" />
                    </pattern>
                    <marker id="ops-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
                      <path d="M0,0 L7,3.5 L0,7 Z" fill="#facc15" fillOpacity="0.72" />
                    </marker>
                  </defs>
                  <rect width="1240" height="620" fill="#050505" />
                  <rect width="1240" height="620" fill="url(#ops-grid)" />
                  {[
                    ["INTAKE", 90, 35],
                    ["STRUCTURE", 450, 35],
                    ["REJECT + SIM", 630, 35],
                    ["NEGOTIATE", 810, 35],
                    ["ALIGN", 990, 35],
                    ["DECIDE + LEARN", 1160, 35],
                  ].map(([label, x, y]) => (
                    <text key={label} x={x} y={y} textAnchor="middle" fill="#a3a3a3" fontSize="11" fontWeight="900" letterSpacing="3">
                      {label}
                    </text>
                  ))}
                  {opsArchitectureEdges.map(([from, to], index) => {
                    const source = opsArchitectureNodeById[from];
                    const target = opsArchitectureNodeById[to];
                    if (!source || !target) return null;
                    const isFeedback = from === "memory" || to === "arbiter" || from === "policy";
                    const isGate = ["safety", "privacy", "labor", "sim", "compliance"].includes(from) && to === "policy";
                    return (
                      <line
                        key={`${from}-${to}-${index}`}
                        x1={source.x}
                        y1={source.y}
                        x2={target.x}
                        y2={target.y}
                        stroke={isGate ? "#fb7185" : isFeedback ? "#c4b5fd" : "#facc15"}
                        strokeWidth={isGate ? 1.6 : 1.2}
                        strokeOpacity={isGate ? 0.52 : 0.32}
                        markerEnd="url(#ops-arrow)"
                      />
                    );
                  })}
                  {opsArchitectureNodes.map((node) => {
                    const tone = opsNodeTones[node.tone as keyof typeof opsNodeTones];
                    return (
                      <g key={node.id}>
                        <rect x={node.x - 70} y={node.y - 29} width="140" height="58" rx="12" fill={tone.fill} stroke={tone.stroke} strokeWidth="1.5" />
                        <text x={node.x} y={node.y - 6} textAnchor="middle" fill={tone.text} fontSize="13" fontWeight="900">
                          {node.label}
                        </text>
                        <text x={node.x} y={node.y + 17} textAnchor="middle" fill={tone.tag} fontSize="9" fontWeight="900" letterSpacing="2">
                          {node.tag}
                        </text>
                      </g>
                    );
                  })}
                </svg>
              </div>
            </div>

            <div className="mt-6 grid gap-3 md:grid-cols-5">
              {opsArchitectureDetailRows.map((row, index) => (
                <article key={row.label} className="rounded-2xl border border-white/10 bg-white/[0.04] p-4">
                  <div className="flex items-center gap-3">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-amber-300 text-xs font-black text-neutral-950">{index + 1}</div>
                    <div className="text-[10px] font-black uppercase tracking-[0.16em] text-amber-300">{row.label}</div>
                  </div>
                  <h4 className="mt-3 text-sm font-black leading-tight text-white">{row.headline}</h4>
                  <p className="mt-2 text-xs font-bold leading-5 text-neutral-400">{row.body}</p>
                </article>
              ))}
            </div>

            <div className="mt-6 grid gap-5 lg:grid-cols-[0.45fr_1.55fr]">
              <div className="rounded-2xl border border-amber-300/25 bg-amber-300/10 p-5">
                <div className="text-xs font-black uppercase tracking-[0.24em] text-amber-300">What the graph proves</div>
                <h4 className="mt-3 text-2xl font-black leading-tight text-white">Every action has a path and a reason.</h4>
                <p className="mt-4 text-sm font-bold leading-6 text-neutral-300">
                  A judge can trace intake, rejection, negotiation, policy, dispatch, and memory.
                </p>
              </div>
              <div className="grid gap-3 md:grid-cols-5">
                {opsArchitectureArtifacts.map(([label, value]) => (
                  <div key={label} className="rounded-2xl border border-white/10 bg-black p-4">
                    <div className="text-xs font-black uppercase tracking-[0.18em] text-emerald-300">{label}</div>
                    <p className="mt-3 text-xs font-bold leading-5 text-neutral-400">{value}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="mt-6 grid gap-5 lg:grid-cols-2">
              <div className="rounded-2xl border border-cyan-300/25 bg-cyan-300/10 p-5">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <div className="text-xs font-black uppercase tracking-[0.24em] text-cyan-300">Live execution bridge</div>
                    <h4 className="mt-3 text-2xl font-black leading-tight text-white">Run the graph in the command center.</h4>
                  </div>
                  <a href="/ops" className="w-fit rounded-full bg-cyan-300 px-4 py-2 text-xs font-black text-neutral-950">Open Command Center</a>
                </div>
                <div className="mt-5 grid gap-3 sm:grid-cols-2">
                  {opsLiveProofRows.map(([label, value]) => (
                    <div key={label} className="rounded-2xl border border-white/10 bg-black p-4">
                      <div className="text-xs font-black uppercase tracking-[0.18em] text-cyan-300">{label}</div>
                      <p className="mt-2 text-xs font-bold leading-5 text-neutral-400">{value}</p>
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-2xl border border-violet-300/25 bg-violet-300/10 p-5">
                <div className="text-xs font-black uppercase tracking-[0.24em] text-violet-300">Mongo memory replay</div>
                <h4 className="mt-3 text-2xl font-black leading-tight text-white">Memory changes the next recommendation.</h4>
                <div className="mt-5 grid gap-3">
                  {opsMemoryReplayRows.map(([label, value]) => (
                    <div key={label} className="grid gap-3 rounded-2xl border border-white/10 bg-black p-4 sm:grid-cols-[90px_1fr] sm:items-start">
                      <div className="text-xs font-black uppercase tracking-[0.18em] text-violet-300">{label}</div>
                      <p className="text-xs font-bold leading-5 text-neutral-400">{value}</p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <div className="mt-8 rounded-[32px] bg-neutral-950 p-6 text-white sm:p-8">
            <div className="grid gap-8 lg:grid-cols-[0.65fr_1.35fr] lg:items-start">
              <div>
                <div className="text-xs font-black uppercase tracking-[0.24em] text-amber-300">Decision receipt</div>
                <h3 className="mt-3 text-3xl font-black leading-tight text-white">The receipt shows the system working.</h3>
                <a href="/ops" className="mt-6 inline-flex rounded-full bg-amber-300 px-4 py-2 text-xs font-black text-neutral-950">Open Command Center</a>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                {opsArtifactRows.map(([label, value]) => (
                  <div key={label} className="rounded-2xl border border-white/10 bg-white/[0.04] p-5">
                    <div className="text-sm font-black text-amber-300">{label}</div>
                    <p className="mt-3 text-sm font-bold leading-6 text-neutral-300">{value}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="event-agent" className="bg-white px-5 py-20 text-neutral-950">
        <div className="mx-auto max-w-7xl">
          <div className="grid gap-10 lg:grid-cols-[0.85fr_1.15fr] lg:items-end">
            <div>
              <SectionLabel tone="text-violet-700">4 / Event Agent</SectionLabel>
              <h2 className="mt-4 text-4xl font-black leading-tight sm:text-6xl">Plan guest experiences from trusted park memory.</h2>
            </div>
            <p className="text-lg leading-8 text-neutral-600">
              The same memory creates guest-facing plans before the park is under pressure.
            </p>
          </div>

          <div className="mt-12 grid gap-3 lg:grid-cols-5">
            {eventFlow.map(([label, detail], index) => (
              <article key={label} className="rounded-2xl border border-neutral-200 bg-neutral-50 p-5">
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-violet-300 text-sm font-black text-neutral-950">{index + 1}</div>
                <h3 className="mt-5 text-xl font-black text-neutral-950">{label}</h3>
                <p className="mt-3 text-sm font-bold leading-6 text-neutral-600">{detail}</p>
              </article>
            ))}
          </div>

          <div className="mt-8 rounded-[32px] bg-neutral-950 p-6 text-white sm:p-8">
            <div className="grid gap-8 lg:grid-cols-[0.65fr_1.35fr] lg:items-start">
              <div>
                <div className="text-xs font-black uppercase tracking-[0.24em] text-violet-300">Event receipt</div>
                <h3 className="mt-3 text-3xl font-black leading-tight text-white">Every event plan leaves a review trail.</h3>
                <a href="/experience-studio" className="mt-6 inline-flex rounded-full bg-violet-300 px-4 py-2 text-xs font-black text-neutral-950">Open Event Agent</a>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                {eventReceiptRows.map(([label, value]) => (
                  <div key={label} className="rounded-2xl border border-white/10 bg-white/[0.04] p-5">
                    <div className="text-sm font-black text-violet-300">{label}</div>
                    <p className="mt-3 text-sm font-bold leading-6 text-neutral-300">{value}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="guest-care" className="px-5 py-20">
        <div className="mx-auto max-w-7xl">
          <div className="grid gap-10 lg:grid-cols-[0.85fr_1.15fr] lg:items-end">
            <div>
              <SectionLabel tone="text-cyan-300">5 / Guest Care</SectionLabel>
              <h2 className="mt-4 text-4xl font-black leading-tight text-white sm:text-6xl">Guest care is part of the operating loop.</h2>
            </div>
            <p className="text-lg leading-8 text-neutral-300">
              ParkPulse optimizes the venue without losing the individual guest.
            </p>
          </div>

          <div className="mt-12 grid gap-4 lg:grid-cols-3">
            {guestCareCards.map((card) => (
              <a key={card.title} href={card.route} className="rounded-[28px] border border-white/10 bg-neutral-900 p-6 transition hover:border-cyan-300/60">
                <div className="flex items-center justify-between gap-4">
                  <h3 className="text-2xl font-black text-white">{card.title}</h3>
                  <div className="rounded-full bg-cyan-300 px-3 py-1.5 text-xs font-black text-neutral-950">{card.route}</div>
                </div>
                <p className="mt-5 text-sm font-bold leading-6 text-neutral-300">{card.body}</p>
                <div className="mt-6 grid grid-cols-2 gap-2">
                  {card.checks.map((check) => (
                    <div key={check} className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-black text-neutral-300">{check}</div>
                  ))}
                </div>
              </a>
            ))}
          </div>

          <div className="mt-8 rounded-[32px] border border-cyan-300/20 bg-cyan-300/10 p-6 sm:p-8">
            <div className="grid gap-8 lg:grid-cols-[0.65fr_1.35fr] lg:items-start">
              <div>
                <div className="text-xs font-black uppercase tracking-[0.24em] text-cyan-300">Guest-care artifact</div>
                <h3 className="mt-3 text-3xl font-black leading-tight text-white">A guest need becomes a bounded response.</h3>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                {guestCareReceiptRows.map(([label, value]) => (
                  <div key={label} className="rounded-2xl border border-white/10 bg-neutral-950 p-5">
                    <div className="text-sm font-black text-cyan-300">{label}</div>
                    <p className="mt-3 text-sm font-bold leading-6 text-neutral-300">{value}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="training" className="px-5 py-20">
        <div className="mx-auto max-w-7xl">
          <div className="grid gap-10 lg:grid-cols-[0.85fr_1.15fr] lg:items-end">
            <div>
              <SectionLabel tone="text-teal-300">6 / Employee Training</SectionLabel>
              <h2 className="mt-4 text-4xl font-black leading-tight text-white sm:text-6xl">Operations become training data.</h2>
            </div>
            <p className="text-lg leading-8 text-neutral-300">
              Incidents become practice, scores, readiness holds, and training signals.
            </p>
          </div>

          <div className="mt-12 grid gap-3 lg:grid-cols-5">
            {trainingLoop.map(([label, detail], index) => (
              <article key={label} className="rounded-2xl border border-white/10 bg-neutral-900 p-5">
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-teal-300 text-sm font-black text-neutral-950">{index + 1}</div>
                <h3 className="mt-5 text-xl font-black text-white">{label}</h3>
                <p className="mt-3 text-sm font-bold leading-6 text-neutral-300">{detail}</p>
              </article>
            ))}
          </div>

          <div className="mt-8 rounded-[32px] border border-teal-300/20 bg-teal-300/10 p-6 sm:p-8">
            <div className="grid gap-8 lg:grid-cols-[0.65fr_1.35fr] lg:items-start">
              <div>
                <div className="text-xs font-black uppercase tracking-[0.24em] text-teal-300">Training receipt</div>
                <h3 className="mt-3 text-3xl font-black leading-tight text-white">Readiness has a receipt.</h3>
                <a href="/staff-training" className="mt-6 inline-flex rounded-full bg-teal-300 px-4 py-2 text-xs font-black text-neutral-950">Open Training</a>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                {trainingReceiptRows.map(([label, value]) => (
                  <div key={label} className="rounded-2xl border border-white/10 bg-neutral-950 p-5">
                    <div className="text-sm font-black text-teal-300">{label}</div>
                    <p className="mt-3 text-sm font-bold leading-6 text-neutral-300">{value}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="trust" className="bg-white px-5 py-20 text-neutral-950">
        <div className="mx-auto max-w-7xl">
          <div className="grid gap-10 lg:grid-cols-[0.85fr_1.15fr] lg:items-end">
            <div>
              <SectionLabel tone="text-blue-700">7 / Agent Trust</SectionLabel>
              <h2 className="mt-4 text-4xl font-black leading-tight sm:text-6xl">Let outside agents help without giving them the park.</h2>
            </div>
            <p className="text-lg leading-8 text-neutral-600">
              ParkPulse verifies delegated authority, handles counteroffers, challenges unsafe requests, and signs the final handoff.
            </p>
          </div>

          <div className="mt-12 rounded-[32px] border border-neutral-200 bg-neutral-50 p-6 sm:p-8">
            <div className="grid gap-8 lg:grid-cols-[0.55fr_1.45fr] lg:items-start">
              <div>
                <div className="text-xs font-black uppercase tracking-[0.24em] text-neutral-500">Negotiation replay</div>
                <h3 className="mt-3 text-3xl font-black leading-tight text-neutral-950">Verify, offer, challenge, handoff, sign.</h3>
                <div className="mt-6 grid gap-2">
                  {handshakeRounds.map((round, index) => {
                    const isActive = index === activeHandshakeIndex;
                    return (
                      <button
                        key={round.label}
                        type="button"
                        onClick={() => setActiveHandshakeIndex(index)}
                        className={`rounded-2xl px-4 py-3 text-left transition ${
                          isActive ? "bg-neutral-950 text-white" : "border border-neutral-300 bg-white text-neutral-700 hover:border-neutral-950"
                        }`}
                      >
                        <div className="flex items-center justify-between gap-4">
                          <span className="text-sm font-black">{String(index + 1).padStart(2, "0")} {round.label}</span>
                          <span className="text-[10px] font-black uppercase tracking-[0.14em]">{round.artifact}</span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="rounded-[28px] bg-neutral-950 p-6 text-white">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <div className="text-xs font-black uppercase tracking-[0.24em] text-blue-300">{activeHandshake.actor}</div>
                    <h4 className="mt-3 text-4xl font-black leading-tight text-white">{activeHandshake.label}</h4>
                    <p className="mt-4 max-w-3xl text-sm font-bold leading-6 text-neutral-300">{activeHandshake.message}</p>
                  </div>
                  <div className="w-fit rounded-full bg-blue-300 px-3 py-1.5 text-xs font-black text-neutral-950">{activeHandshake.artifact}</div>
                </div>
                <div className="mt-7 grid gap-3 md:grid-cols-2">
                  <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-5">
                    <div className="text-xs font-black uppercase tracking-[0.18em] text-cyan-300">Reasoning</div>
                    <p className="mt-3 text-sm font-bold leading-6 text-neutral-300">{activeHandshake.platform}</p>
                  </div>
                  <div className="rounded-2xl border border-emerald-300/25 bg-emerald-300/10 p-5">
                    <div className="text-xs font-black uppercase tracking-[0.18em] text-emerald-200">Policy alignment</div>
                    <p className="mt-3 text-sm font-bold leading-6 text-emerald-50">{activeHandshake.policy}</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="proof" className="bg-neutral-100 px-5 py-20 text-neutral-950">
        <div className="mx-auto max-w-7xl">
          <div className="grid gap-10 lg:grid-cols-[0.85fr_1.15fr] lg:items-end">
            <div>
              <SectionLabel tone="text-rose-700">8 / Safety Proof</SectionLabel>
              <h2 className="mt-4 text-4xl font-black leading-tight sm:text-6xl">The system earns the right to act.</h2>
            </div>
            <p className="text-lg leading-8 text-neutral-600">
              The system is valuable because it knows when not to act.
            </p>
          </div>

          <div className="mt-12 grid gap-4 lg:grid-cols-4">
            {proofRows.map(([label, value]) => (
              <article key={label} className="rounded-2xl border border-neutral-200 bg-white p-5">
                <div className="text-xs font-black uppercase tracking-[0.2em] text-rose-700">{label}</div>
                <p className="mt-3 text-sm font-bold leading-6 text-neutral-600">{value}</p>
              </article>
            ))}
          </div>

          <div className="mt-8 rounded-[32px] bg-neutral-950 p-6 text-white sm:p-8">
            <div className="grid gap-8 lg:grid-cols-[0.65fr_1.35fr] lg:items-start">
              <div>
                <div className="text-xs font-black uppercase tracking-[0.24em] text-emerald-300">Closed learning loop</div>
                <h3 className="mt-3 text-3xl font-black leading-tight text-white">Memory becomes operating improvement.</h3>
                <p className="mt-4 text-sm font-bold leading-6 text-neutral-300">
                  Every reviewed outcome improves the next event, guest reply, ops action, training run, or handshake.
                </p>
              </div>
              <div className="grid gap-3 md:grid-cols-5">
                {learningLoopRows.map(([label, value], index) => (
                  <div key={label} className="rounded-2xl border border-white/10 bg-white/[0.04] p-4">
                    <div className="flex h-9 w-9 items-center justify-center rounded-full bg-emerald-300 text-xs font-black text-neutral-950">{index + 1}</div>
                    <div className="mt-4 text-sm font-black text-emerald-300">{label}</div>
                    <p className="mt-3 text-xs font-bold leading-5 text-neutral-300">{value}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="architecture" className="px-5 py-20">
        <div className="mx-auto max-w-7xl">
          <div className="grid gap-10 lg:grid-cols-[0.95fr_1.05fr] lg:items-end">
            <div>
              <SectionLabel tone="text-blue-300">9 / Architecture</SectionLabel>
              <h2 className="mt-4 text-4xl font-black leading-tight text-white sm:text-6xl">GCP runs the control plane. MongoDB stores the memory.</h2>
            </div>
            <p className="text-lg leading-8 text-neutral-300">
              GCP moves and governs the work. MongoDB keeps the operating memory.
            </p>
          </div>

          <div className="mt-10 grid gap-5 xl:grid-cols-[1fr_1fr]">
            <div className="rounded-[32px] border border-white/10 bg-neutral-900 p-6 sm:p-8">
              <div className="text-xs font-black uppercase tracking-[0.24em] text-blue-300">Google Cloud Platform</div>
              <h3 className="mt-3 text-3xl font-black text-white">Move, approve, deliver, measure.</h3>
              <div className="mt-6 grid gap-2 sm:grid-cols-2">
                {gcpTools.map(([name, role]) => (
                  <div key={name} className="rounded-2xl border border-white/10 bg-neutral-950 p-3">
                    <div className="text-sm font-black text-white">{name}</div>
                    <div className="mt-2 w-fit rounded-full bg-blue-300 px-2.5 py-1 text-[10px] font-black text-neutral-950">{role}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-[32px] border border-white/10 bg-neutral-900 p-6 sm:p-8">
              <div className="text-xs font-black uppercase tracking-[0.24em] text-emerald-300">MongoDB Atlas</div>
              <h3 className="mt-3 text-3xl font-black text-white">The memory every agent reads and writes.</h3>
              <div className="mt-6 overflow-hidden rounded-2xl border border-white/10">
                {mongoMemory.map(([collection, purpose]) => (
                  <div key={collection} className="grid gap-2 border-b border-white/10 bg-neutral-950 px-4 py-3 last:border-b-0 sm:grid-cols-[150px_1fr]">
                    <div className="text-sm font-black text-white">{collection}</div>
                    <div className="text-xs font-bold leading-5 text-neutral-300">{purpose}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="mt-6 rounded-[28px] border border-white/10 bg-neutral-900 p-5 sm:p-6">
            <div className="grid gap-6 lg:grid-cols-[0.45fr_1.55fr] lg:items-start">
              <div>
                <div className="text-xs font-black uppercase tracking-[0.24em] text-blue-300">Tool-to-feature matrix</div>
                <h3 className="mt-3 text-2xl font-black leading-tight text-white">Execution, memory, proof.</h3>
              </div>
              <div className="overflow-hidden rounded-2xl border border-white/10">
                {architectureMatrixRows.map(([feature, gcp, mongo, artifact]) => (
                  <div key={feature} className="grid gap-3 border-b border-white/10 bg-neutral-950 p-3 last:border-b-0 xl:grid-cols-[120px_1fr_1fr_1fr]">
                    <div className="text-sm font-black text-white">{feature}</div>
                    <div>
                      <div className="text-[10px] font-black uppercase tracking-[0.18em] text-blue-300">GCP</div>
                      <p className="mt-1 text-xs font-bold leading-5 text-neutral-300">{gcp}</p>
                    </div>
                    <div>
                      <div className="text-[10px] font-black uppercase tracking-[0.18em] text-emerald-300">MongoDB</div>
                      <p className="mt-1 text-xs font-bold leading-5 text-neutral-300">{mongo}</p>
                    </div>
                    <div>
                      <div className="text-[10px] font-black uppercase tracking-[0.18em] text-cyan-300">Proof</div>
                      <p className="mt-1 text-xs font-bold leading-5 text-neutral-300">{artifact}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="depth" className="bg-neutral-100 px-5 py-20 text-neutral-950">
        <div className="mx-auto max-w-7xl">
          <div className="grid gap-10 lg:grid-cols-[0.85fr_1.15fr] lg:items-end">
            <div>
              <SectionLabel tone="text-neutral-700">10 / Why It Matters</SectionLabel>
              <h2 className="mt-4 text-4xl font-black leading-tight sm:text-6xl">A park is a small city with real operating authority.</h2>
            </div>
            <p className="text-lg leading-8 text-neutral-600">
              A park is a small city: crowds, labor, safety, privacy, food, events, and communication in one live venue.
            </p>
          </div>

          <div className="mt-12 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {depthRows.map(([label, value]) => (
              <article key={label} className="rounded-2xl border border-neutral-200 bg-white p-5">
                <div className="text-xs font-black uppercase tracking-[0.2em] text-neutral-500">{label}</div>
                <p className="mt-3 text-sm font-bold leading-6 text-neutral-600">{value}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="demo" className="bg-white px-5 py-20 text-neutral-950">
        <div className="mx-auto max-w-7xl">
          <div className="grid gap-10 lg:grid-cols-[0.85fr_1.15fr] lg:items-start">
            <div>
              <SectionLabel tone="text-cyan-700">11 / Demo Path</SectionLabel>
              <h2 className="mt-4 text-4xl font-black leading-tight sm:text-6xl">Run the story from memory to audit.</h2>
              <p className="mt-5 text-lg leading-8 text-neutral-600">
                One route through the product: memory, plan, guest, ops, policy, learning, architecture.
              </p>
            </div>

            <div className="grid gap-2 md:grid-cols-2">
              {demoSteps.map(([label, route, detail], index) => (
                <a key={label} href={route} className="rounded-2xl border border-neutral-200 bg-neutral-50 p-3 transition hover:border-neutral-950">
                  <div className="grid gap-3 sm:grid-cols-[40px_1fr] sm:items-start">
                    <div className="flex h-9 w-9 items-center justify-center rounded-full bg-neutral-950 text-xs font-black text-white">{index + 1}</div>
                    <div>
                      <div className="text-base font-black text-neutral-950">{label}</div>
                      <p className="mt-1 text-xs font-bold leading-5 text-neutral-600">{detail}</p>
                      <div className="mt-2 text-[10px] font-black uppercase tracking-[0.12em] text-cyan-700">{route}</div>
                    </div>
                  </div>
                </a>
              ))}
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
