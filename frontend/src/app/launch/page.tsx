"use client";

const launchStats = [
  { value: "540", label: "guests still near a down ride" },
  { value: "44m", label: "current downtime estimate" },
  { value: "55m", label: "nearby indoor ride wait" },
  { value: "3", label: "actions gated before dispatch" },
];

const chapterLinks = [
  { href: "#venue", label: "Venue" },
  { href: "#signals", label: "Signals" },
  { href: "#architecture", label: "Architecture" },
  { href: "#loop", label: "Loop" },
  { href: "#governance", label: "Governance" },
  { href: "#proof", label: "Proof" },
  { href: "#trust", label: "Trust" },
];

const incidentPressure = [
  { label: "Ride intake", value: "paused", tone: "bg-rose-500 text-neutral-950" },
  { label: "Food Court 2", value: "understaffed", tone: "bg-amber-300 text-neutral-950" },
  { label: "Coaster Plaza", value: "88% density", tone: "bg-cyan-300 text-neutral-950" },
  { label: "Indoor Ride B", value: "55m wait", tone: "bg-white text-neutral-950" },
];

const signalRows = [
  { label: "Ride ops", source: "downtime estimate, intake pause, queue hold", status: "critical" },
  { label: "Guest flow", source: "zone density, app routing, walking load", status: "rising" },
  { label: "Staffing", source: "training tags, break windows, fatigue", status: "constrained" },
  { label: "Food ops", source: "mobile backlog, inventory, kitchen load", status: "watch" },
  { label: "Weather", source: "heat index, lightning window, shelter load", status: "watch" },
];

const operatingLoop = [
  {
    label: "Observe",
    owner: "Scan agent",
    body: "Collects live state, operator notes, and weak signals before a decision is made.",
  },
  {
    label: "Structure",
    owner: "Feature pipeline",
    body: "Turns noisy text and telemetry into comparable operational features.",
  },
  {
    label: "Simulate",
    owner: "Digital twin",
    body: "Tests reroutes, food capacity, staffing moves, and downstream pressure.",
  },
  {
    label: "Optimize",
    owner: "Decision bridge",
    body: "Selects the bounded action with the best guest, safety, staff, and capacity tradeoff.",
  },
  {
    label: "Gate",
    owner: "Policy engine",
    body: "Blocks unsafe authority, labor, privacy, accessibility, procurement, or dispatch violations.",
  },
  {
    label: "Learn",
    owner: "Eval and memory",
    body: "Writes the decision receipt, outcome score, and training signal for the next incident.",
  },
];

const gcpTools = [
  {
    name: "Cloud Run",
    role: "Private API runtime",
    detail: "Runs the ParkPulse backend behind authenticated access so demos can use production-like pressure without making the API public.",
  },
  {
    name: "Vertex AI Gemini",
    role: "Context interpreter",
    detail: "Interprets operator notes, explains tradeoffs, drafts payloads, and supports role-specific agent reasoning without owning final authority.",
  },
  {
    name: "Pub/Sub + Eventarc",
    role: "Signal intake",
    detail: "Moves live park events into the operating loop and fans delivery events into downstream systems.",
  },
  {
    name: "Cloud Workflows",
    role: "Approval handoff",
    detail: "Creates explicit operator-review executions for actions that require human approval before dispatch.",
  },
  {
    name: "Firebase Cloud Messaging",
    role: "Guest and worker delivery",
    detail: "Targets guest-app and worker-device topics, with a pseudo-FCM outbox for demo-safe local validation.",
  },
  {
    name: "Dataflow + BigQuery",
    role: "Analytics and learning",
    detail: "Normalizes event envelopes into BigQuery rows for outcome analytics, evaluator backtests, and training signals.",
  },
];

const mongoMemory = [
  {
    collection: "park_state",
    purpose: "Current ride, guest-flow, weather, staff, food, and energy state.",
  },
  {
    collection: "playbooks + incidents",
    purpose: "Grounding memory for SOPs, historical disruptions, lessons, and response procedures.",
  },
  {
    collection: "agent_decisions",
    purpose: "Decision history with retrieved evidence, selected action, policy result, and usefulness gate.",
  },
  {
    collection: "guest_messages",
    purpose: "Reviewed outbound drafts tied back to the decision that produced them.",
  },
  {
    collection: "eval_results",
    purpose: "Groundedness, safety, capacity, staff-stress, and actionability scorecards linked to runs.",
  },
  {
    collection: "Atlas Vector Search",
    purpose: "Semantic retrieval over playbooks, incidents, and agent learnings using model embeddings.",
  },
];

const architectureFlow = [
  "Park signal enters Pub/Sub or local live-feed intake.",
  "Cloud Run normalizes the event and updates MongoDB operational memory.",
  "MongoDB retrieves relevant playbooks, incidents, and prior decisions.",
  "Vertex AI Gemini interprets context and drafts human-readable reasoning.",
  "Simulation and optimizer score bounded actions against capacity and policy.",
  "Workflows, FCM, BigQuery, and memory receive the approved dispatch receipt.",
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

const trustBoundaries = [
  "Personal agents negotiate routes, but cannot accept refunds or share health data.",
  "Supplier agents can provide ETA and inventory, but cannot release vendor payment.",
  "Internal agents receive delegated handoffs only inside signed scope.",
  "Every session can produce a verifiable protocol receipt.",
];

const learningStages = [
  "Operator review closes the case.",
  "Outcome metrics compare actual impact against baseline.",
  "Review labels become supervised training candidates.",
  "Policy thresholds improve without expanding model authority.",
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
              A live amusement park is a dense physical system: rides, guests, weather, food, staff, safety, accessibility, and revenue all move at once. ParkPulse turns those signals into safe, evaluated, human-approved action.
            </p>
            <div className="mt-9 flex flex-wrap gap-3">
              <a href="/" className="rounded-full bg-white px-5 py-3 text-sm font-black text-neutral-950 transition hover:bg-cyan-100">
                Open live demo
              </a>
              <a href="#proof" className="rounded-full border border-white/20 px-5 py-3 text-sm font-black text-white transition hover:border-cyan-200 hover:text-cyan-100">
                See the proof
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

      <section id="venue" className="px-5 pt-24 pb-20">
        <div className="mx-auto max-w-7xl">
          <div className="grid gap-10 lg:grid-cols-[0.9fr_1.1fr] lg:items-end">
            <div>
              <SectionLabel tone="text-emerald-300">Chapter 1 / Live Venue</SectionLabel>
              <h2 className="mt-4 text-4xl font-black leading-tight text-white sm:text-6xl">
                One ride goes down. The whole park feels it.
              </h2>
            </div>
            <p className="text-lg leading-8 text-neutral-300">
              Dragon Coaster closes during peak demand. Nearby queues are saturated, a food court is understaffed, and weather risk is rising. A naive reroute creates a second incident. ParkPulse starts with the full venue state, not a single alert.
            </p>
          </div>

          <div className="mt-12 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            {incidentPressure.map((item) => (
              <div key={item.label} className="border-t border-white/15 pt-5">
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
            <SectionLabel tone="text-cyan-700">Chapter 2 / Signal Fusion</SectionLabel>
            <h2 className="mt-4 text-4xl font-black leading-tight sm:text-6xl">
              Messy context becomes operational features.
            </h2>
            <p className="mt-5 text-lg leading-8 text-neutral-600">
              The operator sees a simple incident. The system sees correlated pressure across ride ops, guest movement, staffing, food throughput, weather, and policy. That structure is what keeps the agent from giving generic advice.
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
              <SectionLabel tone="text-blue-300">Chapter 3 / Tech Architecture</SectionLabel>
              <h2 className="mt-4 text-4xl font-black leading-tight text-white sm:text-6xl">
                GCP runs the control plane. MongoDB remembers the park.
              </h2>
            </div>
            <p className="text-lg leading-8 text-neutral-300">
              The architecture is built around separation of concerns: Google Cloud moves, executes, evaluates, and analyzes the operating loop; MongoDB stores the live operational memory the agents retrieve from and write back to.
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

          <div className="mt-6 rounded-[32px] border border-white/10 bg-white/[0.04] p-6 sm:p-8">
            <div className="grid gap-8 lg:grid-cols-[0.6fr_1.4fr] lg:items-start">
              <div>
                <div className="text-xs font-black uppercase tracking-[0.24em] text-neutral-500">Runtime path</div>
                <h3 className="mt-3 text-3xl font-black leading-tight text-white">From event to receipt</h3>
              </div>
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {architectureFlow.map((step, index) => (
                  <div key={step} className="rounded-2xl border border-white/10 bg-neutral-950 p-5">
                    <div className="text-3xl font-black text-white">{String(index + 1).padStart(2, "0")}</div>
                    <p className="mt-4 text-sm font-bold leading-6 text-neutral-300">{step}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="loop" className="px-5 py-20">
        <div className="mx-auto max-w-7xl">
          <div className="max-w-4xl">
            <SectionLabel tone="text-amber-300">Chapter 4 / Operating Loop</SectionLabel>
            <h2 className="mt-4 text-4xl font-black leading-tight text-white sm:text-6xl">
              Not a chatbot. A controlled decision loop.
            </h2>
            <p className="mt-5 text-lg leading-8 text-neutral-300">
              ParkPulse keeps the language model where it belongs: interpreting context, explaining tradeoffs, drafting payloads, and helping label outcomes. Prediction, simulation, optimization, policy, and approval own the action.
            </p>
          </div>

          <div className="mt-12 grid gap-px overflow-hidden rounded-[28px] border border-white/10 bg-white/10 md:grid-cols-2 xl:grid-cols-3">
            {operatingLoop.map((step, index) => (
              <article key={step.label} className="bg-neutral-950 p-6">
                <div className="flex items-center justify-between gap-4">
                  <div className="text-4xl font-black text-white">{String(index + 1).padStart(2, "0")}</div>
                  <div className="rounded-full border border-white/15 px-3 py-1.5 text-xs font-black uppercase tracking-[0.14em] text-neutral-300">{step.owner}</div>
                </div>
                <h3 className="mt-8 text-2xl font-black text-white">{step.label}</h3>
                <p className="mt-3 text-sm leading-6 text-neutral-300">{step.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="governance" className="bg-neutral-100 px-5 py-20 text-neutral-950">
        <div className="mx-auto grid max-w-7xl gap-12 lg:grid-cols-[0.95fr_1.05fr] lg:items-center">
          <div>
            <SectionLabel tone="text-rose-700">Chapter 5 / Governance</SectionLabel>
            <h2 className="mt-4 text-4xl font-black leading-tight sm:text-6xl">
              The safest recommendation may be the one the system refuses to execute.
            </h2>
            <p className="mt-5 text-lg leading-8 text-neutral-600">
              ParkPulse can draft an action plan, but it cannot silently expand authority. Safety clearance, break rules, queue capacity, privacy, and procurement boundaries are checked before dispatch.
            </p>
          </div>

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
        </div>
      </section>

      <section id="proof" className="px-5 py-20">
        <div className="mx-auto max-w-7xl">
          <div className="grid gap-10 lg:grid-cols-[1fr_1fr] lg:items-end">
            <div>
              <SectionLabel tone="text-emerald-300">Chapter 6 / Proof</SectionLabel>
              <h2 className="mt-4 text-4xl font-black leading-tight text-white sm:text-6xl">
                Every recommendation ships with receipts.
              </h2>
            </div>
            <p className="text-lg leading-8 text-neutral-300">
              Judges and operators can inspect source signals, rejected alternatives, policy results, dispatch payloads, eval scores, and memory writes. The proof layer is the product, not a log file.
            </p>
          </div>

          <div className="mt-12 grid gap-8 lg:grid-cols-[0.9fr_1.1fr]">
            <div className="rounded-[28px] border border-white/10 bg-neutral-900 p-6">
              <div className="text-xs font-black uppercase tracking-[0.24em] text-neutral-500">Dispatch package</div>
              <h3 className="mt-4 text-3xl font-black leading-tight text-white">Three payloads. One approval boundary.</h3>
              <div className="mt-8 space-y-3">
                {["Guest message", "Worker notification", "Signage update"].map((item) => (
                  <div key={item} className="flex items-center justify-between gap-4 rounded-2xl border border-white/10 bg-neutral-950 p-4">
                    <div className="text-sm font-black text-white">{item}</div>
                    <div className="rounded-full bg-cyan-300 px-3 py-1.5 text-xs font-black text-neutral-950">queued</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-[28px] border border-white/10 bg-neutral-900 p-6">
              <div className="text-xs font-black uppercase tracking-[0.24em] text-neutral-500">Eval receipt</div>
              <div className="mt-5 space-y-4">
                {receiptRows.map((row) => (
                  <div key={row.label}>
                    <div className="flex items-center justify-between gap-4 text-sm font-black">
                      <span className="text-neutral-300">{row.label}</span>
                      <span className="text-white">{row.score}</span>
                    </div>
                    <div className="mt-2 h-2 overflow-hidden rounded-full bg-neutral-950">
                      <div className="h-full w-[88%] rounded-full bg-emerald-300" />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="trust" className="bg-white px-5 py-20 text-neutral-950">
        <div className="mx-auto grid max-w-7xl gap-12 lg:grid-cols-[0.9fr_1.1fr] lg:items-start">
          <div>
            <SectionLabel tone="text-cyan-700">Chapter 7 / Agent Trust</SectionLabel>
            <h2 className="mt-4 text-4xl font-black leading-tight sm:text-6xl">
              Outside agents negotiate. ParkPulse enforces the boundary.
            </h2>
            <p className="mt-5 text-lg leading-8 text-neutral-600">
              Personal agents, supplier agents, and internal agents can participate without becoming invisible operators. Identity, capability, intent, proposal, counterproposal, commit, and monitor phases are explicit.
            </p>
            <div className="mt-8">
              <a href="/agent-handshake" className="rounded-full bg-neutral-950 px-5 py-3 text-sm font-black text-white transition hover:bg-neutral-800">
                Open Agent Trust
              </a>
            </div>
          </div>

          <div className="space-y-3">
            {trustBoundaries.map((point, index) => (
              <div key={point} className="grid grid-cols-[44px_1fr] items-center gap-4 border-b border-neutral-200 py-5">
                <div className="flex h-11 w-11 items-center justify-center rounded-full bg-neutral-950 text-sm font-black text-white">{index + 1}</div>
                <div className="text-lg font-black leading-7 tracking-normal">{point}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="px-5 py-20">
        <div className="mx-auto max-w-7xl">
          <div className="rounded-[32px] border border-white/10 bg-neutral-900 p-6 sm:p-10">
            <div className="grid gap-10 lg:grid-cols-[0.9fr_1.1fr] lg:items-center">
              <div>
                <SectionLabel tone="text-lime-300">Chapter 8 / Learning</SectionLabel>
                <h2 className="mt-4 text-4xl font-black leading-tight text-white sm:text-6xl">
                  The loop gets better without giving the model more power.
                </h2>
                <p className="mt-5 text-lg leading-8 text-neutral-300">
                  ParkPulse learns from reviewed outcomes, not unbounded autonomy. The system improves thresholds, playbooks, labels, and routing while keeping policy authority deterministic.
                </p>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                {learningStages.map((stage) => (
                  <div key={stage} className="rounded-2xl border border-white/10 bg-neutral-950 p-5 text-sm font-bold leading-6 text-neutral-200">
                    {stage}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="bg-neutral-100 px-5 py-20 text-neutral-950">
        <div className="mx-auto max-w-5xl text-center">
          <SectionLabel tone="text-cyan-700">Demo path</SectionLabel>
          <h2 className="mt-4 text-4xl font-black leading-tight sm:text-6xl">
            Run one incident. Inspect the machinery underneath.
          </h2>
          <p className="mx-auto mt-5 max-w-3xl text-lg leading-8 text-neutral-600">
            Start with the Ride Down scenario, watch the operating loop produce a bounded plan, then open the proof panels for policy, dispatch, eval, memory, and agent trust.
          </p>
          <div className="mt-9 flex flex-wrap justify-center gap-3">
            <a href="/" className="rounded-full bg-neutral-950 px-6 py-3 text-sm font-black text-white transition hover:bg-neutral-800">
              Launch Command Center
            </a>
            <a href="/ops-agent" className="rounded-full border border-neutral-300 px-6 py-3 text-sm font-black text-neutral-950 transition hover:border-neutral-950">
              Open Ops Agent
            </a>
          </div>
        </div>
      </section>
    </main>
  );
}
