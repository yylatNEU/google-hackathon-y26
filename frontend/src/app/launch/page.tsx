"use client";

import { useState } from "react";

const launchStats = [
  { value: "540", label: "guests still near a down ride" },
  { value: "44m", label: "current downtime estimate" },
  { value: "55m", label: "nearby indoor ride wait" },
  { value: "3", label: "actions gated before dispatch" },
];

const chapterLinks = [
  { href: "#system", label: "System" },
  { href: "#advantage", label: "Advantage" },
  { href: "#foundation", label: "Foundation" },
  { href: "#signals", label: "Signals" },
  { href: "#architecture", label: "Architecture" },
  { href: "#decision", label: "Decision" },
  { href: "#proof", label: "Proof" },
  { href: "#demo", label: "Demo" },
];

const incidentPressure = [
  { label: "Ride intake", value: "paused", tone: "bg-rose-500 text-neutral-950" },
  { label: "Food Court 2", value: "understaffed", tone: "bg-amber-300 text-neutral-950" },
  { label: "Coaster Plaza", value: "88% density", tone: "bg-cyan-300 text-neutral-950" },
  { label: "Indoor Ride B", value: "55m wait", tone: "bg-white text-neutral-950" },
];

const lifecycleStages = [
  {
    id: "foundation",
    label: "Foundation",
    title: "Start with a venue model the agents are allowed to trust.",
    body: "ParkPulse first defines the park: locations, zones, paths, accessibility notes, sensory context, brand rules, safety instructions, and approved guest-facing claims.",
    modules: [
      {
        name: "Venue Profile",
        route: "/venue-profile",
        proof: "Validates the park identity, location graph, channel owners, dining constraints, accessibility notes, and module policy rules.",
      },
      {
        name: "Experience Studio",
        route: "/experience-studio",
        proof: "Drafts seasonal routes, attraction copy, signage, VIP tours, and guest experiences from approved venue data only.",
      },
      {
        name: "Accessibility Journey",
        route: "/accessibility-journey",
        proof: "Builds low-walking, sensory-aware, allergy-aware, and cooling plans while keeping sensitive details and human-review reasons explicit.",
      },
    ],
  },
  {
    id: "signals",
    label: "Sense",
    title: "Turn live noise into operational pressure.",
    body: "A park incident is never a single alert. Ride status, queues, food load, guest messages, weather, staff coverage, and operator notes all shape the safe answer.",
    modules: [
      {
        name: "Command Center",
        route: "/",
        proof: "Shows the live park state, current incident pressure, selected action, policy gate, dispatch state, and eval receipt.",
      },
      {
        name: "Guest Triage",
        route: "/guest-triage",
        proof: "Classifies guest text, scores urgency, drafts a safe first reply, and creates a routed human-acknowledged issue ticket.",
      },
    ],
  },
  {
    id: "decision",
    label: "Decide",
    title: "Make a bounded recommendation, not a generic answer.",
    body: "The operating loop structures signals, simulates alternatives, optimizes tradeoffs, and keeps the LLM in the role of interpreter and explainer.",
    modules: [
      {
        name: "Ops Agent",
        route: "/ops-agent",
        proof: "Routes between scan, react, proact, customer, and QA modes while preserving conversation memory, tool traces, and policy-aware apply mode.",
      },
      {
        name: "Policy Gate",
        route: "/",
        proof: "Blocks ride reopening, break-policy violations, unsafe queue dumping, sensitive guest-data exposure, and unsupported dispatch.",
      },
    ],
  },
  {
    id: "action",
    label: "Act",
    title: "Move the right payload to the right human or system.",
    body: "Approved recommendations become guest messages, worker notifications, signage updates, operator approval workflows, and external-agent handoffs.",
    modules: [
      {
        name: "Agent Handshake",
        route: "/agent-handshake",
        proof: "Verifies identity, capability, delegation scope, policy challenges, external-agent negotiation, and signed protocol receipts.",
      },
      {
        name: "GCP Delivery",
        route: "#architecture",
        proof: "Uses Workflows for approval, FCM or pseudo-FCM for guest and worker delivery, and Pub/Sub/Eventarc for operations fanout.",
      },
    ],
  },
  {
    id: "proof",
    label: "Prove",
    title: "Record why the decision was safe, grounded, and useful.",
    body: "The result is inspectable: policy refs, source signals, rejected alternatives, dispatch payloads, eval dimensions, memory writes, and review queues.",
    modules: [
      {
        name: "Monitor",
        route: "/monitor",
        proof: "Exposes policy integrity, trace/eval readiness, supervised actions, runtime governance, review ledgers, and evidence packets.",
      },
      {
        name: "Staff Training",
        route: "/staff-training",
        proof: "Turns hard guest-care scenarios into roleplay, rubric evaluation, mastery gaps, review queues, and training-gap tickets.",
      },
    ],
  },
];

const signalRows = [
  { label: "Ride ops", source: "downtime estimate, intake pause, queue hold", status: "critical" },
  { label: "Guest flow", source: "zone density, app routing, walking load", status: "rising" },
  { label: "Staffing", source: "training tags, break windows, fatigue", status: "constrained" },
  { label: "Food ops", source: "mobile backlog, inventory, kitchen load", status: "watch" },
  { label: "Weather", source: "heat index, lightning window, shelter load", status: "watch" },
];

const advantageOutcomes = [
  {
    metric: "From alert to plan",
    before: "Static dashboards show ride downtime, queue length, staffing, and food backlog as separate panels.",
    after: "ParkPulse fuses them into one bounded action: pause intake, reroute guests, protect breaks, adjust food capacity, and draft approved messages.",
  },
  {
    metric: "From memoryless to adaptive",
    before: "The next incident starts cold, with operators searching old notes and repeating the same failure patterns.",
    after: "MongoDB retrieves prior incidents, playbooks, eval results, guest-message outcomes, and agent decisions before the next recommendation is made.",
  },
  {
    metric: "From generic advice to proof",
    before: "A chatbot can suggest a plausible plan without proving whether it is safe, grounded, or executable.",
    after: "The system returns policy gates, rejected alternatives, dispatch payloads, eval dimensions, and memory receipts alongside the recommendation.",
  },
];

const comparisonModes = [
  {
    id: "dashboard",
    label: "Dashboard",
    title: "Separate alerts, no operating judgment.",
    summary: "Ride downtime, queue pressure, staff coverage, and food backlog appear as separate facts. The operator still has to infer the safest combined move.",
    cards: [
      ["Ride ops", "Dragon Coaster down for 44 minutes"],
      ["Guest flow", "540 guests still clustered nearby"],
      ["Food ops", "Food Court 2 understaffed"],
      ["Staffing", "Break window at risk"],
    ],
    verdict: "Useful visibility, but no bounded cross-domain action.",
  },
  {
    id: "chatbot",
    label: "Generic chatbot",
    title: "Plausible advice, weak proof.",
    summary: "A generic assistant can suggest rerouting guests and notifying staff, but it does not know the venue graph, previous incidents, policy books, or dispatch authority.",
    cards: [
      ["Suggestion", "Move guests to another ride"],
      ["Missing", "Indoor Ride B is already 55 minutes"],
      ["Missing", "Protected staff breaks are constrained"],
      ["Missing", "No signed dispatch or eval receipt"],
    ],
    verdict: "Sounds reasonable, but cannot prove it is safe or executable.",
  },
  {
    id: "parkpulse",
    label: "ParkPulse + Mongo",
    title: "Memory-backed action with proof.",
    summary: "ParkPulse retrieves venue facts, prior incidents, playbooks, eval rows, and useful decisions before selecting a bounded action and writing the result back to memory.",
    cards: [
      ["Retrieve", "Similar ride-down cases and response playbooks"],
      ["Decide", "Pause intake, protect breaks, route away from Coaster Plaza"],
      ["Gate", "Human review required; ride reopening blocked"],
      ["Write back", "Decision, payloads, eval score, review label"],
    ],
    verdict: "One grounded action plan, with policy proof and reusable memory.",
  },
];

const memoryCycle = [
  { label: "Retrieve", detail: "Find similar incidents, playbooks, prior decisions, and agent learnings with Atlas Vector Search." },
  { label: "Ground", detail: "Attach venue facts, safety rules, staff constraints, and guest-care boundaries before the model reasons." },
  { label: "Decide", detail: "Score alternatives against guest impact, capacity, labor stress, safety, and actionability." },
  { label: "Write back", detail: "Store the selected action, dispatch result, eval score, review label, and useful learning signal." },
];

const gcpTools = [
  { name: "Cloud Run", role: "Private runtime", detail: "Runs the backend behind authenticated access for production-like pressure without public API exposure." },
  { name: "Vertex AI Gemini", role: "Interpreter", detail: "Explains tradeoffs, drafts payloads, and supports role-specific reasoning without owning final authority." },
  { name: "Pub/Sub + Eventarc", role: "Signal intake", detail: "Moves live park events into the operating loop and fans delivery events into downstream systems." },
  { name: "Cloud Workflows", role: "Approval", detail: "Creates explicit operator-review executions before human-gated dispatch." },
  { name: "Firebase Cloud Messaging", role: "Delivery", detail: "Targets guest-app and worker-device topics, with pseudo-FCM for demo-safe validation." },
  { name: "Dataflow + BigQuery", role: "Analytics", detail: "Normalizes event envelopes into rows for outcome analytics, evaluator backtests, and training signals." },
];

const mongoMemory = [
  { collection: "park_state", purpose: "Current ride, guest-flow, weather, staff, food, and energy state." },
  { collection: "playbooks + incidents", purpose: "SOPs, historical disruptions, lessons, and response procedures." },
  { collection: "agent_decisions", purpose: "Decision history with evidence, selected action, policy result, and usefulness gate." },
  { collection: "guest_messages", purpose: "Reviewed outbound drafts tied back to the decision that produced them." },
  { collection: "eval_results", purpose: "Groundedness, safety, capacity, staff-stress, and actionability scorecards." },
  { collection: "Atlas Vector Search", purpose: "Semantic retrieval over playbooks, incidents, and agent learnings using model embeddings." },
];

const operatingLoop = [
  {
    label: "Observe",
    owner: "Scan agent",
    body: "Collect live state, operator notes, guest messages, and weak signals.",
    input: "Ride telemetry, queues, weather, food backlog, staff coverage, guest text",
    output: "One incident packet with source confidence and missing context",
  },
  {
    label: "Structure",
    owner: "Feature pipeline",
    body: "Turn noisy text and telemetry into comparable operational features.",
    input: "Raw signals plus MongoDB venue profile, playbooks, incidents, and prior decisions",
    output: "Capacity pressure, guest impact, labor stress, safety risk, and action constraints",
  },
  {
    label: "Simulate",
    owner: "Digital twin",
    body: "Test reroutes, food capacity, staffing moves, and downstream pressure.",
    input: "Candidate actions from the planner and operational memory",
    output: "Rejected options, projected wait shift, staffing effect, and crowd-spillover risk",
  },
  {
    label: "Optimize",
    owner: "Decision bridge",
    body: "Select the bounded action with the best safety, guest, staff, and capacity tradeoff.",
    input: "Simulation scores, policy constraints, venue facts, and operator intent",
    output: "Selected action, rationale, receiver payloads, and alternatives considered",
  },
  {
    label: "Gate",
    owner: "Policy engine",
    body: "Block unsafe authority, labor, privacy, accessibility, procurement, or dispatch violations.",
    input: "Selected action, receiver payloads, role authority, and policy books",
    output: "Allowed, blocked, or human-review-required gate with policy references",
  },
  {
    label: "Learn",
    owner: "Eval and memory",
    body: "Write the receipt, outcome score, review label, and training signal.",
    input: "Dispatch result, acknowledgements, eval scorecard, and reviewer decisions",
    output: "MongoDB decision memory, BigQuery analytics row, and staff-training gap when needed",
  },
];

const decisionArtifacts = [
  {
    label: "Selected action",
    value: "Pause intake, route guests away from Coaster Plaza, protect breaks, add food capacity",
  },
  {
    label: "Rejected option",
    value: "Dump all coaster guests into Indoor Ride B; blocked because nearby queue is already 55 minutes",
  },
  {
    label: "Human gate",
    value: "Dispatch allowed only after operator approval; ride reopening remains blocked without safety clearance",
  },
  {
    label: "Memory write",
    value: "Store evidence, selected action, receiver payloads, eval score, review label, and outcome metrics",
  },
];

const policyGates = [
  { rule: "No ride reopening", result: "blocked without safety clearance" },
  { rule: "No staff break violation", result: "requires protected coverage" },
  { rule: "No queue dumping", result: "reroute capped by capacity" },
  { rule: "No sensitive guest data", result: "PII removed from payloads" },
];

const receiptRows = [
  { label: "Groundedness", score: "97/100" },
  { label: "Capacity awareness", score: "93/100" },
  { label: "Staff stress", score: "91/100" },
  { label: "Actionability", score: "96/100" },
  { label: "Policy compliance", score: "pass" },
];

const demoSteps = [
  { label: "Validate Venue Profile", route: "/venue-profile", detail: "Show the trusted venue model: zones, locations, accessibility notes, dining constraints, paths, channel owners, and policy rules." },
  { label: "Open Experience Studio", route: "/experience-studio", detail: "Show that guest experiences and seasonal routes are generated only from approved venue data and risky claims go to review." },
  { label: "Plan Accessibility Journey", route: "/accessibility-journey", detail: "Show low-walking, low-sensory, allergy-aware, and cooling plans with explicit human-review boundaries." },
  { label: "Run Ride Down", route: "/", detail: "Start the command center incident and watch live pressure become a bounded operating-loop action." },
  { label: "Open Guest Triage", route: "/guest-triage", detail: "Show guest care routed through urgency scoring, venue context, safe reply drafting, and ticket creation." },
  { label: "Ask Ops Agent Why", route: "/ops-agent", detail: "Ask why the plan was selected, what options were rejected, and how policy-aware apply mode preserves the receipt." },
  { label: "Inspect Monitor", route: "/monitor", detail: "Prove policy integrity, eval readiness, evidence packets, review ledgers, and runtime governance after the action." },
  { label: "Run Staff Training", route: "/staff-training", detail: "Show the learning layer: guest-care roleplay, rubric evaluation, mastery gaps, and training-gap tickets." },
  { label: "Verify Agent Trust", route: "/agent-handshake", detail: "Show external-agent negotiation, delegation scope, policy challenges, and signed protocol receipts." },
  { label: "Return To Architecture", route: "#architecture", detail: "Tie the proof back to GCP execution, delivery, analytics, and MongoDB operational memory." },
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
  const [comparisonMode, setComparisonMode] = useState(comparisonModes[2].id);
  const [activeDecisionIndex, setActiveDecisionIndex] = useState(0);
  const activeComparison = comparisonModes.find((mode) => mode.id === comparisonMode) ?? comparisonModes[2];
  const activeDecision = operatingLoop[activeDecisionIndex] ?? operatingLoop[0];

  return (
    <main className="min-h-screen bg-neutral-950 text-white">
      <nav className="sticky top-0 z-30 border-b border-white/10 bg-neutral-950/88 px-5 py-4 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4">
          <a href="/launch" className="text-sm font-black tracking-normal text-white">
            ParkPulse
          </a>
          <div className="hidden items-center gap-1 lg:flex">
            {chapterLinks.map((link) => (
              <a key={link.href} href={link.href} className="rounded-full px-3 py-2 text-xs font-bold text-neutral-400 transition hover:bg-white/10 hover:text-white">
                {link.label}
              </a>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <a href="/" className="rounded-full border border-white/15 px-4 py-2 text-xs font-bold text-neutral-200 transition hover:border-white/40 hover:text-white">
              Command Center
            </a>
            <a href="/agent-handshake" className="hidden rounded-full border border-white/15 px-4 py-2 text-xs font-bold text-neutral-200 transition hover:border-white/40 hover:text-white sm:inline-flex">
              Agent Trust
            </a>
          </div>
        </div>
      </nav>

      <section className="relative overflow-hidden px-5 pt-20 pb-10 lg:pt-28">
        <div className="mx-auto grid max-w-7xl gap-12 lg:grid-cols-[0.82fr_1.18fr] lg:items-center">
          <div>
            <SectionLabel>ParkPulse AI</SectionLabel>
            <h1 className="mt-6 max-w-5xl text-5xl font-black leading-[0.96] tracking-normal text-white sm:text-7xl lg:text-7xl">
              The operating layer for critical park decisions.
            </h1>
            <p className="mt-7 max-w-2xl text-lg leading-8 text-neutral-300 sm:text-xl">
              ParkPulse is not one agent screen. It is a venue operating lifecycle: model the park, sense live pressure, decide through policy, dispatch with approval, prove the result, and train the next response.
            </p>
            <div className="mt-9 flex flex-wrap gap-3">
              <a href="/" className="rounded-full bg-white px-5 py-3 text-sm font-black text-neutral-950 transition hover:bg-cyan-100">
                Open live demo
              </a>
              <a href="#system" className="rounded-full border border-white/20 px-5 py-3 text-sm font-black text-white transition hover:border-cyan-200 hover:text-cyan-100">
                See system map
              </a>
            </div>
          </div>

          <div className="relative">
            <div className="h-[520px] overflow-hidden rounded-[28px] border border-white/15 bg-neutral-900 shadow-2xl shadow-cyan-950/40 sm:h-[660px] lg:h-[760px]">
              <img
                src="/parkpulse-command-center.png"
                alt="ParkPulse command center showing park map, scenario panel, action plan, policy gate, and eval scorecard"
                className="h-full w-full object-cover object-top"
              />
            </div>
            <div className="absolute -bottom-6 left-5 right-5 rounded-2xl border border-cyan-200/30 bg-neutral-950/92 p-4 shadow-2xl shadow-black/40 backdrop-blur">
              <MetricStrip />
            </div>
          </div>
        </div>
      </section>

      <section id="system" className="px-5 pt-24 pb-20">
        <div className="mx-auto max-w-7xl">
          <div className="grid gap-10 lg:grid-cols-[0.95fr_1.05fr] lg:items-end">
            <div>
              <SectionLabel tone="text-emerald-300">System Map</SectionLabel>
              <h2 className="mt-4 text-4xl font-black leading-tight text-white sm:text-6xl">
                Every built module fits one operating lifecycle.
              </h2>
            </div>
            <p className="text-lg leading-8 text-neutral-300">
              The front page is organized by what the platform must do end to end. Each card below is a built surface, but the value is how the surfaces connect.
            </p>
          </div>

          <div className="mt-12 grid gap-4">
            {lifecycleStages.map((stage, index) => (
              <article key={stage.id} id={`stage-${stage.id}`} className="rounded-[28px] border border-white/10 bg-neutral-900 p-6 sm:p-8">
                <div className="grid gap-8 lg:grid-cols-[0.65fr_1.35fr]">
                  <div>
                    <div className="text-5xl font-black text-white">{String(index + 1).padStart(2, "0")}</div>
                    <div className="mt-5 text-xs font-black uppercase tracking-[0.24em] text-cyan-300">{stage.label}</div>
                    <h3 className="mt-4 text-3xl font-black leading-tight text-white">{stage.title}</h3>
                    <p className="mt-4 text-sm leading-6 text-neutral-300">{stage.body}</p>
                  </div>
                  <div className="grid gap-3 md:grid-cols-2">
                    {stage.modules.map((module) => (
                      <a key={module.name} href={module.route} className="rounded-2xl border border-white/10 bg-neutral-950 p-5 transition hover:border-cyan-300/60">
                        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                          <div className="text-xl font-black text-white">{module.name}</div>
                          <div className="w-fit rounded-full bg-cyan-300 px-3 py-1.5 text-xs font-black text-neutral-950">{module.route}</div>
                        </div>
                        <p className="mt-4 text-sm font-bold leading-6 text-neutral-300">{module.proof}</p>
                      </a>
                    ))}
                  </div>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="advantage" className="bg-white px-5 py-20 text-neutral-950">
        <div className="mx-auto max-w-7xl">
          <div className="grid gap-10 lg:grid-cols-[0.9fr_1.1fr] lg:items-end">
            <div>
              <SectionLabel tone="text-cyan-700">AI + Memory Advantage</SectionLabel>
              <h2 className="mt-4 text-4xl font-black leading-tight sm:text-6xl">
                The difference is not more dashboards. It is an operating memory that changes the next decision.
              </h2>
            </div>
            <p className="text-lg leading-8 text-neutral-600">
              ParkPulse uses AI to interpret messy cross-domain pressure and MongoDB to remember what happened, what worked, what failed, and what the system is allowed to reuse.
            </p>
          </div>

          <div className="mt-12 grid gap-4 lg:grid-cols-3">
            {advantageOutcomes.map((item) => (
              <article key={item.metric} className="rounded-[28px] border border-neutral-200 bg-neutral-50 p-6">
                <div className="text-xs font-black uppercase tracking-[0.24em] text-cyan-700">{item.metric}</div>
                <div className="mt-6 rounded-2xl border border-neutral-200 bg-white p-4">
                  <div className="text-xs font-black uppercase tracking-[0.18em] text-neutral-500">Before</div>
                  <p className="mt-3 text-sm font-bold leading-6 text-neutral-600">{item.before}</p>
                </div>
                <div className="mt-3 rounded-2xl bg-neutral-950 p-4 text-white">
                  <div className="text-xs font-black uppercase tracking-[0.18em] text-cyan-300">With ParkPulse</div>
                  <p className="mt-3 text-sm font-bold leading-6 text-neutral-200">{item.after}</p>
                </div>
              </article>
            ))}
          </div>

          <div className="mt-8 rounded-[32px] border border-neutral-200 bg-neutral-50 p-6 sm:p-8">
            <div className="grid gap-8 lg:grid-cols-[0.55fr_1.45fr] lg:items-start">
              <div>
                <div className="text-xs font-black uppercase tracking-[0.24em] text-neutral-500">Interactive replay</div>
                <h3 className="mt-3 text-3xl font-black leading-tight text-neutral-950">Same incident. Three levels of intelligence.</h3>
                <div className="mt-6 grid gap-2">
                  {comparisonModes.map((mode) => {
                    const isActive = mode.id === activeComparison.id;
                    return (
                      <button
                        key={mode.id}
                        type="button"
                        onClick={() => setComparisonMode(mode.id)}
                        className={`rounded-full px-4 py-3 text-left text-sm font-black transition ${
                          isActive ? "bg-neutral-950 text-white" : "border border-neutral-300 bg-white text-neutral-700 hover:border-neutral-950"
                        }`}
                      >
                        {mode.label}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="rounded-[28px] bg-neutral-950 p-6 text-white">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <div className="text-xs font-black uppercase tracking-[0.24em] text-cyan-300">{activeComparison.label}</div>
                    <h4 className="mt-3 text-3xl font-black leading-tight text-white">{activeComparison.title}</h4>
                    <p className="mt-4 max-w-3xl text-sm font-bold leading-6 text-neutral-300">{activeComparison.summary}</p>
                  </div>
                  <div className="w-fit rounded-full bg-cyan-300 px-3 py-1.5 text-xs font-black text-neutral-950">ride down</div>
                </div>
                <div className="mt-6 grid gap-3 md:grid-cols-2">
                  {activeComparison.cards.map(([label, value]) => (
                    <div key={`${activeComparison.id}-${label}`} className="rounded-2xl border border-white/10 bg-white/[0.04] p-4">
                      <div className="text-xs font-black uppercase tracking-[0.18em] text-neutral-500">{label}</div>
                      <p className="mt-3 text-sm font-bold leading-6 text-neutral-200">{value}</p>
                    </div>
                  ))}
                </div>
                <div className="mt-5 rounded-2xl border border-emerald-300/30 bg-emerald-300/10 p-4 text-sm font-black leading-6 text-emerald-100">
                  {activeComparison.verdict}
                </div>
              </div>
            </div>
          </div>

          <div className="mt-8 rounded-[32px] bg-neutral-950 p-6 text-white sm:p-8">
            <div className="grid gap-8 lg:grid-cols-[0.7fr_1.3fr] lg:items-start">
              <div>
                <div className="text-xs font-black uppercase tracking-[0.24em] text-emerald-300">MongoDB memory loop</div>
                <h3 className="mt-4 text-3xl font-black leading-tight sm:text-5xl">Every run becomes better context for the next one.</h3>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                {memoryCycle.map((step, index) => (
                  <div key={step.label} className="rounded-2xl border border-white/10 bg-white/[0.04] p-5">
                    <div className="flex items-center gap-3">
                      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-emerald-300 text-sm font-black text-neutral-950">{index + 1}</div>
                      <div className="text-xl font-black text-white">{step.label}</div>
                    </div>
                    <p className="mt-4 text-sm font-bold leading-6 text-neutral-300">{step.detail}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="foundation" className="bg-neutral-100 px-5 py-20 text-neutral-950">
        <div className="mx-auto max-w-7xl">
          <div className="grid gap-10 lg:grid-cols-[0.9fr_1.1fr] lg:items-end">
            <div>
              <SectionLabel tone="text-cyan-700">Foundation / Live Venue</SectionLabel>
              <h2 className="mt-4 text-4xl font-black leading-tight sm:text-6xl">
                One ride goes down. The whole park feels it.
              </h2>
            </div>
            <p className="text-lg leading-8 text-neutral-600">
              Dragon Coaster closes during peak demand. Nearby queues are saturated, a food court is understaffed, and weather risk is rising. A naive reroute creates a second incident. ParkPulse starts with the full venue state, not a single alert.
            </p>
          </div>

          <div className="mt-12 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            {incidentPressure.map((item) => (
              <div key={item.label} className="border-t border-neutral-300 pt-5">
                <div className="text-xs font-black uppercase tracking-[0.2em] text-neutral-500">{item.label}</div>
                <div className={`mt-4 inline-flex rounded-full px-3 py-2 text-sm font-black ${item.tone}`}>{item.value}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="signals" className="bg-white px-5 py-20 text-neutral-950">
        <div className="mx-auto grid max-w-7xl gap-12 lg:grid-cols-[0.85fr_1.15fr] lg:items-start">
          <div>
            <SectionLabel tone="text-cyan-700">Signals / Intake</SectionLabel>
            <h2 className="mt-4 text-4xl font-black leading-tight sm:text-6xl">
              Messy context becomes operational features.
            </h2>
            <p className="mt-5 text-lg leading-8 text-neutral-600">
              The operator sees a simple incident. The system sees correlated pressure across ride ops, guest movement, staffing, food throughput, weather, and policy.
            </p>
          </div>

          <div className="overflow-hidden rounded-[28px] border border-neutral-200 bg-neutral-50">
            {signalRows.map((row) => (
              <div key={row.label} className="grid gap-3 border-b border-neutral-200 p-5 last:border-b-0 sm:grid-cols-[150px_1fr_110px] sm:items-center">
                <div className="text-sm font-black text-neutral-950">{row.label}</div>
                <div className="text-sm leading-6 text-neutral-600">{row.source}</div>
                <div className="w-fit rounded-full bg-neutral-950 px-3 py-1.5 text-xs font-black uppercase tracking-[0.14em] text-white sm:justify-self-end">{row.status}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="architecture" className="px-5 py-20">
        <div className="mx-auto max-w-7xl">
          <div className="grid gap-10 lg:grid-cols-[0.95fr_1.05fr] lg:items-end">
            <div>
              <SectionLabel tone="text-blue-300">Architecture</SectionLabel>
              <h2 className="mt-4 text-4xl font-black leading-tight text-white sm:text-6xl">
                GCP runs the control plane. MongoDB remembers the park.
              </h2>
            </div>
            <p className="text-lg leading-8 text-neutral-300">
              Google Cloud moves, executes, evaluates, and analyzes the operating loop. MongoDB stores the live operational memory the agents retrieve from and write back to.
            </p>
          </div>

          <div className="mt-12 grid gap-6 xl:grid-cols-[1fr_1fr]">
            <div className="rounded-[32px] border border-white/10 bg-neutral-900 p-6 sm:p-8">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <div className="text-xs font-black uppercase tracking-[0.24em] text-blue-300">Google Cloud Platform</div>
                  <h3 className="mt-3 text-3xl font-black text-white">Execution, delivery, and analytics</h3>
                </div>
                <div className="rounded-full bg-white px-3 py-1.5 text-xs font-black text-neutral-950">GCP</div>
              </div>
              <div className="mt-7 grid gap-3">
                {gcpTools.map((tool) => (
                  <article key={tool.name} className="rounded-2xl border border-white/10 bg-neutral-950 p-4">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                      <h4 className="text-lg font-black text-white">{tool.name}</h4>
                      <div className="w-fit rounded-full bg-blue-300 px-3 py-1.5 text-xs font-black text-neutral-950">{tool.role}</div>
                    </div>
                    <p className="mt-3 text-sm leading-6 text-neutral-300">{tool.detail}</p>
                  </article>
                ))}
              </div>
            </div>

            <div className="rounded-[32px] border border-white/10 bg-neutral-900 p-6 sm:p-8">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <div className="text-xs font-black uppercase tracking-[0.24em] text-emerald-300">MongoDB Atlas</div>
                  <h3 className="mt-3 text-3xl font-black text-white">Operational memory and retrieval</h3>
                </div>
                <div className="rounded-full bg-emerald-300 px-3 py-1.5 text-xs font-black text-neutral-950">Memory</div>
              </div>
              <div className="mt-7 overflow-hidden rounded-2xl border border-white/10">
                {mongoMemory.map((memory) => (
                  <div key={memory.collection} className="grid gap-2 border-b border-white/10 bg-neutral-950 p-4 last:border-b-0 sm:grid-cols-[170px_1fr]">
                    <div className="text-sm font-black text-white">{memory.collection}</div>
                    <div className="text-sm leading-6 text-neutral-300">{memory.purpose}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="decision" className="px-5 py-20">
        <div className="mx-auto max-w-7xl">
          <div className="grid gap-10 lg:grid-cols-[0.85fr_1.15fr] lg:items-end">
            <div>
              <SectionLabel tone="text-amber-300">Decision Loop</SectionLabel>
              <h2 className="mt-4 text-4xl font-black leading-tight text-white sm:text-6xl">
                Not a chatbot. A controlled decision loop.
              </h2>
            </div>
            <p className="text-lg leading-8 text-neutral-300">
              Prediction, simulation, optimization, policy, and approval own the action. Gemini interprets and explains; MongoDB grounds and remembers; the policy engine decides what can actually move.
            </p>
          </div>

          <div className="mt-12 rounded-[32px] border border-white/10 bg-neutral-900 p-6 sm:p-8">
            <div className="grid gap-8 lg:grid-cols-[0.55fr_1.45fr] lg:items-start">
              <div>
                <div className="text-xs font-black uppercase tracking-[0.24em] text-neutral-500">Step through the loop</div>
                <div className="mt-5 grid gap-2">
                  {operatingLoop.map((step, index) => {
                    const isActive = index === activeDecisionIndex;
                    return (
                      <button
                        key={step.label}
                        type="button"
                        onClick={() => setActiveDecisionIndex(index)}
                        className={`rounded-2xl px-4 py-3 text-left transition ${
                          isActive ? "bg-cyan-300 text-neutral-950" : "border border-white/10 bg-neutral-950 text-neutral-300 hover:border-cyan-300/60 hover:text-white"
                        }`}
                      >
                        <div className="flex items-center justify-between gap-4">
                          <span className="text-sm font-black">{String(index + 1).padStart(2, "0")} {step.label}</span>
                          <span className="text-[10px] font-black uppercase tracking-[0.14em]">{step.owner}</span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="rounded-[28px] border border-white/10 bg-neutral-950 p-6">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <div className="text-xs font-black uppercase tracking-[0.24em] text-amber-300">{activeDecision.owner}</div>
                    <h3 className="mt-3 text-4xl font-black leading-tight text-white">{activeDecision.label}</h3>
                    <p className="mt-4 max-w-3xl text-sm font-bold leading-6 text-neutral-300">{activeDecision.body}</p>
                  </div>
                  <div className="w-fit rounded-full bg-white px-3 py-1.5 text-xs font-black text-neutral-950">active step</div>
                </div>

                <div className="mt-7 grid gap-3 md:grid-cols-2">
                  <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-5">
                    <div className="text-xs font-black uppercase tracking-[0.18em] text-cyan-300">Input</div>
                    <p className="mt-3 text-sm font-bold leading-6 text-neutral-300">{activeDecision.input}</p>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-5">
                    <div className="text-xs font-black uppercase tracking-[0.18em] text-emerald-300">Output</div>
                    <p className="mt-3 text-sm font-bold leading-6 text-neutral-300">{activeDecision.output}</p>
                  </div>
                </div>

                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  <div className="rounded-2xl border border-blue-300/20 bg-blue-300/10 p-5">
                    <div className="text-xs font-black uppercase tracking-[0.18em] text-blue-200">GCP role</div>
                    <p className="mt-3 text-sm font-bold leading-6 text-blue-50">
                      {activeDecision.label === "Learn"
                        ? "Dataflow and BigQuery preserve outcome rows for analytics and evaluator backtests."
                        : activeDecision.label === "Gate"
                          ? "Cloud Workflows creates the approval handoff when policy requires human review."
                          : activeDecision.label === "Observe"
                            ? "Pub/Sub and Eventarc carry live operations signals into the private Cloud Run runtime."
                            : "Vertex AI Gemini helps interpret, explain, and draft while Cloud Run keeps the control path private."}
                    </p>
                  </div>
                  <div className="rounded-2xl border border-emerald-300/20 bg-emerald-300/10 p-5">
                    <div className="text-xs font-black uppercase tracking-[0.18em] text-emerald-200">MongoDB role</div>
                    <p className="mt-3 text-sm font-bold leading-6 text-emerald-50">
                      {activeDecision.label === "Learn"
                        ? "Writes the useful decision, eval result, review label, and future retrieval signal."
                        : activeDecision.label === "Observe"
                          ? "Stores the current park state so later steps share the same operational truth."
                          : "Retrieves venue facts, playbooks, incidents, and prior decisions to ground the step."}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="mt-8 grid gap-px overflow-hidden rounded-[28px] border border-white/10 bg-white/10 lg:grid-cols-2">
            {operatingLoop.map((step, index) => (
              <article key={step.label} className="bg-neutral-950 p-6">
                <div className="flex items-center justify-between gap-4">
                  <div className="text-4xl font-black text-white">{String(index + 1).padStart(2, "0")}</div>
                  <div className="rounded-full border border-white/15 px-3 py-1.5 text-xs font-black uppercase tracking-[0.14em] text-neutral-300">{step.owner}</div>
                </div>
                <h3 className="mt-8 text-2xl font-black text-white">{step.label}</h3>
                <p className="mt-3 text-sm leading-6 text-neutral-300">{step.body}</p>
                <div className="mt-5 grid gap-3 sm:grid-cols-2">
                  <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4">
                    <div className="text-[10px] font-black uppercase tracking-[0.18em] text-cyan-300">Input</div>
                    <p className="mt-2 text-xs font-bold leading-5 text-neutral-300">{step.input}</p>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4">
                    <div className="text-[10px] font-black uppercase tracking-[0.18em] text-emerald-300">Output</div>
                    <p className="mt-2 text-xs font-bold leading-5 text-neutral-300">{step.output}</p>
                  </div>
                </div>
              </article>
            ))}
          </div>

          <div className="mt-8 rounded-[32px] border border-white/10 bg-neutral-900 p-6 sm:p-8">
            <div className="grid gap-8 lg:grid-cols-[0.65fr_1.35fr] lg:items-start">
              <div>
                <div className="text-xs font-black uppercase tracking-[0.24em] text-neutral-500">Decision artifact</div>
                <h3 className="mt-3 text-3xl font-black leading-tight text-white">What the loop returns to the operator.</h3>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                {decisionArtifacts.map((artifact) => (
                  <div key={artifact.label} className="rounded-2xl border border-white/10 bg-neutral-950 p-5">
                    <div className="text-sm font-black text-cyan-300">{artifact.label}</div>
                    <p className="mt-3 text-sm font-bold leading-6 text-neutral-300">{artifact.value}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="proof" className="bg-neutral-100 px-5 py-20 text-neutral-950">
        <div className="mx-auto max-w-7xl">
          <div className="grid gap-12 lg:grid-cols-[0.95fr_1.05fr] lg:items-start">
            <div>
              <SectionLabel tone="text-rose-700">Governance / Proof / Learning</SectionLabel>
              <h2 className="mt-4 text-4xl font-black leading-tight sm:text-6xl">
                The safest action is sometimes no automatic action.
              </h2>
              <p className="mt-5 text-lg leading-8 text-neutral-600">
                Every recommendation carries a policy gate, dispatch boundary, eval receipt, memory write, and review path.
              </p>
            </div>

            <div className="grid gap-4">
              <div className="rounded-[28px] bg-neutral-950 p-5 text-white">
                <div className="rounded-2xl border border-amber-300/40 bg-amber-300 px-5 py-4 text-sm font-black uppercase tracking-[0.18em] text-neutral-950">
                  Human review required
                </div>
                <div className="mt-4 space-y-3">
                  {policyGates.map((gate) => (
                    <div key={gate.rule} className="grid gap-2 rounded-2xl border border-white/10 bg-white/[0.04] p-4 sm:grid-cols-[170px_1fr]">
                      <div className="text-sm font-black text-white">{gate.rule}</div>
                      <div className="text-sm leading-6 text-neutral-300">{gate.result}</div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-[28px] border border-neutral-200 bg-white p-6">
                <div className="text-xs font-black uppercase tracking-[0.24em] text-neutral-500">Eval receipt</div>
                <div className="mt-5 space-y-4">
                  {receiptRows.map((row) => (
                    <div key={row.label}>
                      <div className="flex items-center justify-between gap-4 text-sm font-black">
                        <span className="text-neutral-600">{row.label}</span>
                        <span className="text-neutral-950">{row.score}</span>
                      </div>
                      <div className="mt-2 h-2 overflow-hidden rounded-full bg-neutral-100">
                        <div className="h-full w-[88%] rounded-full bg-emerald-500" />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="demo" className="px-5 py-20">
        <div className="mx-auto max-w-7xl">
          <div className="grid gap-10 lg:grid-cols-[0.85fr_1.15fr] lg:items-start">
            <div>
              <SectionLabel tone="text-cyan-300">Demo Path</SectionLabel>
              <h2 className="mt-4 text-4xl font-black leading-tight text-white sm:text-6xl">
                Walk every feature through one coherent story.
              </h2>
              <p className="mt-5 text-lg leading-8 text-neutral-300">
                This is the route I would show judges: foundation data, guest experience generation, accessibility, live operations, guest triage, ops copilot, monitoring, staff learning, external-agent trust, and cloud/memory proof.
              </p>
            </div>

            <div className="grid gap-3">
              {demoSteps.map((step, index) => (
                <a key={step.label} href={step.route} className="rounded-2xl border border-white/10 bg-neutral-900 p-5 transition hover:border-cyan-300/60">
                  <div className="grid gap-4 sm:grid-cols-[58px_1fr_auto] sm:items-center">
                    <div className="flex h-12 w-12 items-center justify-center rounded-full bg-white text-sm font-black text-neutral-950">{index + 1}</div>
                    <div>
                      <div className="text-xl font-black text-white">{step.label}</div>
                      <p className="mt-2 text-sm leading-6 text-neutral-300">{step.detail}</p>
                    </div>
                    <div className="w-fit rounded-full bg-cyan-300 px-3 py-1.5 text-xs font-black text-neutral-950">{step.route}</div>
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
