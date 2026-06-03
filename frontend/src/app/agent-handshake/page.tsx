"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchParkPulseApi, getApiUrls } from "@/lib/api";

type DelegationToken = Record<string, unknown> & {
  sub?: string;
  agent_id?: string;
  scope?: string[];
  cannot_do?: string[];
  sig?: string;
};

type DelegationProof = {
  status?: string;
  signature_status?: string;
  scope_status?: string;
  missing_scope?: string[];
  required_scope?: string[];
  subject?: string;
  agent_id?: string;
  expires_at?: number;
  reason?: string;
  operation?: string;
};

type PolicyDecision = {
  id: string;
  action: string;
  status: string;
  allowed: boolean;
  requires_user_approval: boolean;
  reason: string;
};

type CaseEvaluation = {
  id: string;
  at: string;
  case: string;
  status: "passed" | "failed";
  score: number;
  passed_criteria: number;
  total_criteria: number;
  criteria: Record<string, boolean>;
};

type InternalHandoff = {
  id: string;
  internal_agent_id: string;
  internal_agent: string;
  trigger: string;
  authority: string;
  decision: string;
  action: string;
  source: string;
};

type HandshakeSession = {
  session_id: string;
  state: string;
  client_agent: { agent_id: string; represents: string; requested_session: string };
  park_agent: { agent_id: string; represents: string };
  identity: { status: string; guest_role: string; trust_level: string };
  delegation?: {
    token?: DelegationToken;
    proof?: DelegationProof;
    last_verification?: DelegationProof;
    issuer_mode?: string;
  };
  permissions?: {
    client_agent: { can_share: string[]; can_receive: string[]; cannot_do: string[]; expires_at: string };
    park_agent: { can_offer: string[]; requires_approval_for: string[] };
  } | null;
  intent?: {
    client_agent: { goal: string; time_window: string; constraints: Record<string, unknown> };
    park_agent: { accepted_goal: boolean; optimization_targets: string[]; conflict_notice: string };
  } | null;
  proposal?: {
    proposal_id: string;
    plan: string[];
    expected_wait_saved: string;
    estimated_walking_distance: string;
    confidence: number;
    rationale: string;
    requires_user_approval: boolean;
    state_evidence?: {
      source?: string;
      family_start_zone?: string;
      selected_rides?: Array<{ id?: string; name?: string; status?: string; waitMins?: number }>;
      selected_food?: { name?: string; pickupEtaMinutes?: number };
      active_alerts?: Array<{ severity?: string; title?: string }>;
    };
  } | null;
  monitoring?: {
    event: string;
    park_agent_offer: string;
    park_agent_revision?: string;
    accepted_resolution: string;
    policy_gate: Record<string, string>;
  } | null;
  policy_gates: Array<{ action: string; approval: string; reason: string }>;
  policy_decisions?: PolicyDecision[];
  internal_handoffs?: InternalHandoff[];
  case_evaluations?: CaseEvaluation[];
  conversation: Array<{ at: string; actor: string; action: string; payload: Record<string, unknown> }>;
  persistence?: { status: string; collection: string; id?: string; updated_at?: string; error?: string };
};

type AgentContract = {
  status: string;
  protocol_version: string;
  routes: string[];
  state_machine: string[];
  internal_agents?: Array<{ agent_id: string; label: string; authority: string; cannot_do: string[] }>;
  policy_gates: Array<{ action: string; approval: string; reason: string }>;
  requires_approval_for: string[];
  trust_issuer?: {
    issuer?: string;
    signing?: { alg?: string; kid?: string; mode?: string; version?: string };
    trust_store?: { mode?: string; partners?: number; revocations?: number; keys?: number; audit_events?: number };
    verification_endpoint?: string;
    revocation_endpoint?: string;
  };
};

type SimulatorStep = {
  id: string;
  label: string;
  path: string;
  request: Record<string, unknown>;
  response?: Record<string, unknown>;
  state?: string;
  status: "pending" | "running" | "done" | "error";
  caseEvaluation?: CaseEvaluation;
};

type OnboardingCertification = {
  certification_id: string;
  status: "approved" | "blocked";
  approval: string;
  score: number;
  required_cases: Record<string, { status: string; score: number; criteria?: Record<string, boolean> }>;
  passed_cases: string[];
  allowed_scopes: string[];
  readiness_issues: string[];
  session_id?: string | null;
  credential?: CertificationCredential | null;
};

type CertificationCredential = Record<string, unknown> & {
  agent_id?: string;
  certification_id?: string;
  kid?: string;
  approval?: string;
  scope?: string[];
  exp?: number;
  sig?: string;
};

type CredentialVerification = {
  status: string;
  signature_status?: string;
  reason?: string;
  agent_id?: string;
  certification_id?: string;
  kid?: string;
  approval?: string;
  scope?: string[];
  expires_at?: number;
};

type TrustAdminProbe = {
  status: "idle" | "running" | "passed" | "blocked" | "error";
  unauthStatus?: number;
  opsStatus?: number;
  adminStatus?: number;
  partnerStatus?: number;
  adminRole?: string;
  activeKey?: string;
  storeMode?: string;
  authMode?: string;
  productionReady?: boolean;
  externalIdentityReady?: boolean;
  devIssuerEnabled?: boolean;
  reason?: string;
};

type OnboardedAgent = {
  agent_id: string;
  display_name: string;
  status: string;
  approval: string;
  requested_scopes: string[];
  allowed_scopes: string[];
  cannot_do: string[];
  certification?: OnboardingCertification | null;
};

const jsonHeaders = { "content-type": "application/json" };
const states = ["verified", "scoped", "intent_accepted", "negotiating", "committed", "monitoring", "closed"];
const fullAgentScopes = ["location", "party_size", "preferences", "accessibility_needs", "budget", "ride_preference", "route_plan", "wait_time_alert", "food_recommendation", "safety_notice", "compensation_offer", "policy_check", "session_commit"];
const stateLabels: Record<string, string> = {
  verified: "Identity",
  scoped: "Capability",
  intent_accepted: "Intent",
  negotiating: "Negotiate",
  committed: "Commit",
  monitoring: "Monitor",
  closed: "Close",
};
const protocolPhases = [
  { id: "identity", label: "Identity", purpose: "Prove which agent is speaking and who it represents.", artifact: "signed delegation token" },
  { id: "capability", label: "Capability", purpose: "Declare what may be shared, received, and never automated.", artifact: "permission envelope" },
  { id: "intent", label: "Intent", purpose: "Turn user preference into an explicit objective and constraints.", artifact: "goal contract" },
  { id: "negotiation", label: "Negotiation", purpose: "Exchange proposal, counterproposal, confidence, and tradeoffs.", artifact: "plan revision" },
  { id: "commit", label: "Commit", purpose: "Accept a bounded plan without granting extra authority.", artifact: "commitment receipt" },
  { id: "monitor", label: "Monitor", purpose: "Watch the outcome and revise or escalate only when policy requires it.", artifact: "outcome loop" },
];
const protocolScenarios = [
  {
    id: "visit_planning",
    mode: "Visit planning",
    clientIntent: "Best 3-hour family plan with low waits, peanut-safe food, and low walking.",
    parkOffer: "Lazy River, Arcade, allergy-safe Pizza Garden, Parade Zone.",
    negotiation: "Client agent raises walking distance; Park agent trades wait savings for a tighter route.",
    handoffs: ["Queue Agent", "Food Agent", "Guest Experience Agent"],
    allowed: ["route_change", "wait_alert", "food_recommendation"],
    blocked: ["auto_purchase", "share_health_data"],
    outcome: "42 minutes saved with safe-food constraint preserved.",
  },
  {
    id: "incident_response",
    mode: "Incident response",
    clientIntent: "Keep the family experience intact after Wave Pool enters safety delay.",
    parkOffer: "Indoor Surf Simulator plus priority Lazy River return window.",
    negotiation: "Client agent declines food credit and asks for time-first alternative.",
    handoffs: ["Safety Agent", "Queue Agent", "Commerce Agent"],
    allowed: ["safety_notice", "priority_access", "route_change"],
    blocked: ["override_safety_delay", "refund_acceptance"],
    outcome: "Safety delay respected while experience is rerouted in real time.",
  },
  {
    id: "accessibility_support",
    mode: "Accessibility support",
    clientIntent: "Minimize walking and avoid sensory overload while keeping kid-friendly stops.",
    parkOffer: "Covered route, quiet dining window, parade viewing zone with lower crowd density.",
    negotiation: "Client agent asks to prioritize rest points over wait-time savings.",
    handoffs: ["Guest Experience Agent", "Queue Agent", "Food Agent"],
    allowed: ["accessibility_needs", "low_walking_route", "restaurant_timing"],
    blocked: ["medical_escalation", "health_data_sharing"],
    outcome: "Plan adapts to accessibility constraints without exposing health data.",
  },
  {
    id: "commerce_resolution",
    mode: "Commerce resolution",
    clientIntent: "Resolve a closed attraction without wasting guest time.",
    parkOffer: "$5 food credit or priority return to Lazy River.",
    negotiation: "Client agent values time more than compensation and selects priority access.",
    handoffs: ["Commerce Agent", "Queue Agent", "Guest Experience Agent"],
    allowed: ["compensation_offer", "priority_access", "notify_user"],
    blocked: ["payment", "refund_acceptance", "compensation_settlement"],
    outcome: "Offer is proposed, but financial settlement remains user-approved.",
  },
  {
    id: "group_coordination",
    mode: "Group coordination",
    clientIntent: "Coordinate three family agents with different wait, thrill, and food preferences.",
    parkOffer: "Shared anchor stops plus optional split-path windows.",
    negotiation: "Agents align on common parade time and negotiate separate ride branches.",
    handoffs: ["Queue Agent", "Food Agent", "Guest Experience Agent"],
    allowed: ["shared_route_plan", "group_wait_alert", "split_itinerary"],
    blocked: ["cross_guest_data_sharing", "identity_sensitive_action"],
    outcome: "Multiple personal agents converge on one bounded group plan.",
  },
];
const extensionMarkets = [
  { market: "Airlines", example: "Passenger agent negotiates delay handling, lounge access, and rebooking options." },
  { market: "Hotels", example: "Guest agent negotiates allergy, room, accessibility, and late-checkout preferences." },
  { market: "Hospitals", example: "Patient agent coordinates appointment flow while protecting health-data scope." },
  { market: "Conferences", example: "Attendee agent negotiates agenda, networking slots, and session changes." },
  { market: "Retail", example: "Shopper agent negotiates pickup, inventory alternatives, returns, and offers." },
];

function titleize(value: string) {
  return value.replace(/_/g, " ");
}

function caseLabel(caseId: string) {
  return (
    {
      identity_trust: "Trust verified",
      capability_scope: "Permission scope accepted",
      delegation_scope_rejection: "Bad scope rejected",
      commerce_payment_probe: "Payment blocked",
      queue_reroute: "Reroute executed",
    }[caseId] ?? titleize(caseId)
  );
}

function caseDescription(caseId: string) {
  return (
    {
      identity_trust: "Client agent represents the expected guest with a valid signed delegation token.",
      capability_scope: "Shared and received data are narrowed to the contract scope.",
      delegation_scope_rejection: "Under-scoped agents are stopped before negotiation advances.",
      commerce_payment_probe: "Commerce actions route to Commerce Agent and require user approval.",
      queue_reroute: "Queue Agent can act inside route and wait-alert scope.",
    }[caseId] ?? "Protocol case evaluated against deterministic pass/fail criteria."
  );
}

function caseGroup(caseId: string) {
  if (caseId.includes("identity") || caseId.includes("trust")) return "Trust";
  if (caseId.includes("capability") || caseId.includes("delegation")) return "Authority";
  if (caseId.includes("commerce") || caseId.includes("payment")) return "Policy";
  if (caseId.includes("queue") || caseId.includes("reroute")) return "Action";
  return "Protocol";
}

function badgeClass(status?: string) {
  if (status === "passed" || status === "done" || status === "recommended" || status === "verified" || status === "accepted") return "border-emerald-300 bg-emerald-300 text-slate-950";
  if (status === "failed" || status === "blocked" || status === "rejected" || status === "error") return "border-rose-300 bg-rose-300 text-slate-950";
  if (status === "running" || status?.includes("approval")) return "border-amber-300 bg-amber-300 text-slate-950";
  return "border-slate-700 text-slate-300";
}

function scoreClass(score: number) {
  if (score >= 1) return "text-emerald-200";
  if (score >= 0.75) return "text-amber-200";
  return "text-rose-200";
}

async function readJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetchParkPulseApi(path, init);
  return (await response.json()) as T;
}

async function readJsonWithStatus(path: string, init?: RequestInit): Promise<{ ok: boolean; status: number; payload: Record<string, unknown> }> {
  let lastError: unknown;
  for (const apiUrl of getApiUrls()) {
    try {
      const response = await fetch(`${apiUrl}${path}`, init);
      const payload = (await response.json().catch(() => ({}))) as Record<string, unknown>;
      return { ok: response.ok, status: response.status, payload };
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError instanceof Error ? lastError : new Error(`Unable to reach ParkPulse API at ${path}`);
}

function latestEvaluation(payload: Record<string, unknown>, session?: HandshakeSession) {
  const direct = payload.case_evaluation as CaseEvaluation | undefined;
  if (direct) return direct;
  const evaluations = session?.case_evaluations ?? [];
  return evaluations[evaluations.length - 1];
}

function StateRail({ activeState }: { activeState: string }) {
  const activeIndex = Math.max(0, states.indexOf(activeState));
  return (
    <div className="grid gap-2 sm:grid-cols-7">
      {states.map((state, index) => (
        <div key={state} className={`rounded border px-3 py-2 ${index <= activeIndex ? "border-cyan-300 bg-cyan-300 text-slate-950" : "border-slate-800 bg-[#10151a] text-slate-400"}`}>
          <div className="text-[10px] font-black uppercase tracking-normal opacity-70">Step {index + 1}</div>
          <div className="text-sm font-black">{stateLabels[state]}</div>
        </div>
      ))}
    </div>
  );
}

function AgentCard({ title, subtitle, items, accent }: { title: string; subtitle: string; items: string[]; accent: string }) {
  return (
    <section className="rounded-lg border border-slate-800 bg-[#11161a] p-4">
      <div className={`h-1 w-20 rounded-full ${accent}`} />
      <div className="mt-4 text-[11px] font-black uppercase tracking-normal text-slate-500">{subtitle}</div>
      <h2 className="mt-1 text-xl font-black text-slate-100">{title}</h2>
      <div className="mt-4 grid gap-2">
        {items.map((item) => (
          <div key={item} className="rounded border border-slate-800 bg-slate-950 px-3 py-2 text-sm font-bold text-slate-200">
            {item}
          </div>
        ))}
      </div>
    </section>
  );
}

function MiniMap({ activeState }: { activeState: string }) {
  const stops = [
    { label: "Gate", x: "14%", y: "28%", color: "bg-emerald-300" },
    { label: "Water", x: "34%", y: "62%", color: "bg-sky-300" },
    { label: "Arcade", x: "57%", y: "35%", color: "bg-amber-300" },
    { label: "Food", x: "73%", y: "66%", color: "bg-rose-300" },
  ];
  return (
    <div className="relative min-h-[270px] overflow-hidden rounded-lg border border-slate-800 bg-[#10151a]">
      <div className="absolute inset-0 opacity-70 [background-image:linear-gradient(rgba(255,255,255,.05)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,.05)_1px,transparent_1px)] [background-size:38px_38px]" />
      <div className="absolute left-[16%] top-[34%] h-[38%] w-[52%] rounded-full border border-dashed border-cyan-300/80" />
      <div className="absolute left-[33%] top-[41%] h-[25%] w-[38%] rounded-full border border-dashed border-amber-300/80" />
      {stops.map((stop) => (
        <div key={stop.label} className="absolute -translate-x-1/2 -translate-y-1/2" style={{ left: stop.x, top: stop.y }}>
          <div className={`h-4 w-4 rounded-full ${stop.color} shadow-[0_0_26px_rgba(34,211,238,.3)]`} />
          <div className="mt-2 rounded border border-slate-700 bg-slate-950/90 px-2 py-1 text-[10px] font-black uppercase tracking-normal text-slate-200">{stop.label}</div>
        </div>
      ))}
      <div className="absolute bottom-3 left-3 right-3 rounded border border-slate-700 bg-slate-950/90 p-3">
        <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Live contract state</div>
        <div className="mt-1 text-lg font-black text-slate-100">{stateLabels[activeState] ?? titleize(activeState)}</div>
      </div>
    </div>
  );
}

function ProtocolExplorer() {
  const [selectedId, setSelectedId] = useState(protocolScenarios[0].id);
  const selected = protocolScenarios.find((scenario) => scenario.id === selectedId) ?? protocolScenarios[0];
  return (
    <section className="mx-auto max-w-7xl px-4 pb-6 md:px-8">
      <div className="rounded-lg border border-slate-800 bg-[#11161a] p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-[11px] font-black uppercase tracking-normal text-slate-500">Protocol explorer</div>
            <h2 className="mt-1 text-2xl font-black text-slate-100">Handshake protocol as the product</h2>
            <p className="mt-2 max-w-4xl text-sm font-bold leading-6 text-slate-400">
              The same identity, permission, goal, negotiation, policy, and outcome handshakes can power many guest-agent scenarios. ParkPulse is the first vertical demo.
            </p>
          </div>
          <div className="rounded border border-cyan-300/70 px-3 py-2 text-xs font-black uppercase tracking-normal text-cyan-100">Reusable agent contract</div>
        </div>

        <div className="mt-4 grid gap-2 lg:grid-cols-5">
          {protocolScenarios.map((scenario) => (
            <button
              key={scenario.id}
              type="button"
              onClick={() => setSelectedId(scenario.id)}
              className={`rounded border px-3 py-3 text-left text-xs font-black transition ${selected.id === scenario.id ? "border-cyan-300 bg-cyan-300 text-slate-950" : "border-slate-800 bg-slate-950 text-slate-200 hover:border-cyan-300/70"}`}
            >
              <span className="block text-[10px] uppercase tracking-normal opacity-70">Mode</span>
              <span className="mt-1 block">{scenario.mode}</span>
            </button>
          ))}
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-[1.05fr_.95fr]">
          <div className="rounded border border-slate-800 bg-slate-950 p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Selected handshake mode</div>
                <h3 className="mt-1 text-xl font-black text-slate-100">{selected.mode}</h3>
              </div>
              <span className="rounded border border-emerald-300/70 px-2 py-1 text-[10px] font-black uppercase tracking-normal text-emerald-100">Negotiable</span>
            </div>
            <div className="mt-4 grid gap-3">
              {[
                ["Client intent", selected.clientIntent],
                ["Park agent offer", selected.parkOffer],
                ["Negotiation move", selected.negotiation],
                ["Outcome", selected.outcome],
              ].map(([label, value]) => (
                <div key={label} className="rounded border border-slate-800 bg-[#0b1014] p-3">
                  <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">{label}</div>
                  <div className="mt-1 text-sm font-bold leading-6 text-slate-200">{value}</div>
                </div>
              ))}
            </div>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              <div className="rounded border border-slate-800 bg-[#0b1014] p-3">
                <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Internal handoff</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {selected.handoffs.map((agent) => (
                    <span key={agent} className="rounded border border-cyan-300/60 px-2 py-1 text-[10px] font-black uppercase tracking-normal text-cyan-100">{agent}</span>
                  ))}
                </div>
              </div>
              <div className="rounded border border-slate-800 bg-[#0b1014] p-3">
                <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Policy gate</div>
                <div className="mt-2 grid gap-2">
                  <div className="text-[11px] font-bold leading-5 text-emerald-100">Allowed: {selected.allowed.map(titleize).join(", ")}</div>
                  <div className="text-[11px] font-bold leading-5 text-rose-100">Blocked: {selected.blocked.map(titleize).join(", ")}</div>
                </div>
              </div>
            </div>
          </div>

          <div className="rounded border border-slate-800 bg-slate-950 p-4">
            <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Protocol phases</div>
            <div className="mt-3 grid gap-2">
              {protocolPhases.map((phase, index) => (
                <div key={phase.id} className="grid grid-cols-[2rem_1fr] gap-3 rounded border border-slate-800 bg-[#0b1014] p-3">
                  <div className="flex h-8 w-8 items-center justify-center rounded border border-cyan-300 bg-cyan-300 text-xs font-black text-slate-950">{index + 1}</div>
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="text-sm font-black text-slate-100">{phase.label}</div>
                      <span className="rounded border border-slate-700 px-2 py-0.5 text-[9px] font-black uppercase tracking-normal text-slate-400">{phase.artifact}</span>
                    </div>
                    <div className="mt-1 text-[11px] font-bold leading-5 text-slate-400">{phase.purpose}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-[.9fr_1.1fr]">
          <div className="rounded border border-slate-800 bg-slate-950 p-4">
            <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Negotiation primitives</div>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {["proposal", "counterproposal", "priority_change", "tradeoff_explanation", "confidence", "commitment_receipt", "live_revision", "escalation_request"].map((primitive) => (
                <div key={primitive} className="rounded border border-slate-800 bg-[#0b1014] px-3 py-2 text-[11px] font-black text-amber-100">{titleize(primitive)}</div>
              ))}
            </div>
          </div>
          <div className="rounded border border-slate-800 bg-slate-950 p-4">
            <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Extension potential</div>
            <div className="mt-3 grid gap-2 md:grid-cols-2">
              {extensionMarkets.map((item) => (
                <div key={item.market} className="rounded border border-slate-800 bg-[#0b1014] p-3">
                  <div className="text-xs font-black text-slate-100">{item.market}</div>
                  <div className="mt-1 text-[11px] font-bold leading-5 text-slate-400">{item.example}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function ContractPanel({ contract }: { contract: AgentContract | null }) {
  return (
    <section className="mx-auto max-w-7xl px-4 pb-6 md:px-8">
      <div className="rounded-lg border border-slate-800 bg-[#11161a] p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-[11px] font-black uppercase tracking-normal text-slate-500">Agent contract spec</div>
            <h2 className="mt-1 text-xl font-black text-slate-100">{contract?.protocol_version ?? "parkpulse-ahp-0.1"}</h2>
            <p className="mt-2 max-w-3xl text-sm font-bold leading-6 text-slate-400">Outside agents obtain a signed delegation token, prove identity, declare permissions, then negotiate only inside approved scopes.</p>
          </div>
          <div className="rounded border border-cyan-300/70 px-3 py-2 text-xs font-black uppercase tracking-normal text-cyan-100">{contract?.status ?? "loading"}</div>
        </div>
        <div className="mt-4 rounded border border-slate-800 bg-slate-950 p-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Integration kit</div>
              <p className="mt-2 max-w-3xl text-xs font-bold leading-5 text-slate-400">External agents can use the OpenAPI file, copy the Python SDK, run the certified-agent demo, or execute conformance against any ParkPulse API base URL.</p>
            </div>
            <div className="rounded border border-emerald-300/70 px-3 py-2 text-[10px] font-black uppercase tracking-normal text-emerald-100">Reusable contract</div>
          </div>
          <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
            <a href="/agent-handshake-integration-pack.md" target="_blank" rel="noreferrer" className="rounded border border-fuchsia-300/60 bg-[#0b1014] px-3 py-2 text-xs font-black text-fuchsia-100 hover:bg-fuchsia-300 hover:text-slate-950">
              Quickstart
              <span className="mt-1 block text-[10px] font-bold text-slate-500">docs/agent-handshake-integration-pack.md</span>
            </a>
            <a href="/agent-handshake-openapi.yaml" target="_blank" rel="noreferrer" className="rounded border border-cyan-300/60 bg-[#0b1014] px-3 py-2 text-xs font-black text-cyan-100 hover:bg-cyan-300 hover:text-slate-950">
              OpenAPI spec
              <span className="mt-1 block text-[10px] font-bold text-slate-500">docs/agent-handshake-openapi.yaml</span>
            </a>
            <a href="/parkpulse_agent_client.py" target="_blank" rel="noreferrer" className="rounded border border-emerald-300/60 bg-[#0b1014] px-3 py-2 text-xs font-black text-emerald-100 hover:bg-emerald-300 hover:text-slate-950">
              Python SDK
              <span className="mt-1 block text-[10px] font-bold text-slate-500">examples/parkpulse_agent_client.py</span>
            </a>
            <a href="/certified_agent_demo.py" target="_blank" rel="noreferrer" className="rounded border border-rose-300/60 bg-[#0b1014] px-3 py-2 text-xs font-black text-rose-100 hover:bg-rose-300 hover:text-slate-950">
              Certified demo
              <span className="mt-1 block text-[10px] font-bold text-slate-500">examples/certified_agent_demo.py</span>
            </a>
            <a href="/personal-agent-client.ts" target="_blank" rel="noreferrer" className="rounded border border-amber-300/60 bg-[#0b1014] px-3 py-2 text-xs font-black text-amber-100 hover:bg-amber-300 hover:text-slate-950">
              TS reference
              <span className="mt-1 block text-[10px] font-bold text-slate-500">examples/personal-agent-client.ts</span>
            </a>
            <div className="rounded border border-slate-800 bg-[#0b1014] px-3 py-2 text-xs font-black text-slate-200">
              Conformance command
              <code className="mt-1 block break-words text-[10px] font-bold text-slate-500">python3 scripts/run_agent_handshake_conformance.py --api http://127.0.0.1:8001</code>
            </div>
          </div>
        </div>
        <div className="mt-4 grid gap-2 rounded border border-slate-800 bg-slate-950 p-3 md:grid-cols-3 xl:grid-cols-6">
          <div>
            <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Trust issuer</div>
            <div className="mt-1 text-xs font-black text-slate-100">{contract?.trust_issuer?.issuer ?? "parkpulse_agent_onboarding_authority"}</div>
          </div>
          <div>
            <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Signing key</div>
            <div className="mt-1 truncate text-xs font-black text-cyan-100">{contract?.trust_issuer?.signing?.kid ?? "loading"}</div>
          </div>
          <div>
            <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Key version</div>
            <div className="mt-1 truncate text-xs font-black text-amber-100">{contract?.trust_issuer?.signing?.version ?? "v1"}</div>
          </div>
          <div>
            <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Trust store</div>
            <div className="mt-1 truncate text-xs font-black text-fuchsia-100">{contract?.trust_issuer?.trust_store?.mode ?? "sqlite_wal"}</div>
          </div>
          <div>
            <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Verify</div>
            <div className="mt-1 truncate text-xs font-black text-emerald-100">{contract?.trust_issuer?.verification_endpoint ?? "/api/park/agent-onboarding/verify-credential"}</div>
          </div>
          <div>
            <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Revoke</div>
            <div className="mt-1 truncate text-xs font-black text-rose-100">{contract?.trust_issuer?.revocation_endpoint ?? "/api/park/agent-onboarding/revoke-credential"}</div>
          </div>
        </div>
        <div className="mt-2 grid gap-2 rounded border border-slate-800 bg-slate-950 p-3 sm:grid-cols-4">
          {[
            ["Partners", contract?.trust_issuer?.trust_store?.partners],
            ["Keys", contract?.trust_issuer?.trust_store?.keys],
            ["Revocations", contract?.trust_issuer?.trust_store?.revocations],
            ["Audit events", contract?.trust_issuer?.trust_store?.audit_events],
          ].map(([label, value]) => (
            <div key={String(label)} className="rounded border border-slate-800 bg-[#0b1014] px-3 py-2">
              <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">{label}</div>
              <div className="mt-1 text-lg font-black text-slate-100">{typeof value === "number" ? value : "-"}</div>
            </div>
          ))}
        </div>
        <div className="mt-4 grid gap-3 lg:grid-cols-[1fr_.9fr]">
          <div className="rounded border border-slate-800 bg-slate-950 p-3">
            <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Endpoint surface</div>
            <div className="mt-3 grid gap-2 md:grid-cols-2">
              {(contract?.routes ?? []).map((route) => (
                <div key={route} className="rounded border border-slate-800 bg-[#0b1014] px-3 py-2 text-[11px] font-black text-cyan-100">
                  {route}
                </div>
              ))}
            </div>
          </div>
          <div className="rounded border border-slate-800 bg-slate-950 p-3">
            <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Internal agents</div>
            <div className="mt-3 grid gap-2">
              {(contract?.internal_agents ?? []).map((agent) => (
                <div key={agent.agent_id} className="rounded border border-slate-800 bg-[#0b1014] p-3">
                  <div className="text-xs font-black text-slate-100">{agent.label}</div>
                  <div className="mt-1 text-[11px] font-bold leading-5 text-slate-400">{agent.authority}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function EvaluationSummary({ evaluation }: { evaluation?: CaseEvaluation }) {
  if (!evaluation) return null;
  return (
    <div className="mt-3 rounded border border-slate-800 bg-[#0b1014] p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Automatic case evaluation</div>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <div className="text-xs font-black text-slate-100">{caseLabel(evaluation.case)}</div>
            <span className="rounded border border-slate-700 px-2 py-0.5 text-[9px] font-black uppercase tracking-normal text-slate-400">{caseGroup(evaluation.case)}</span>
          </div>
        </div>
        <span className={`rounded border px-2 py-1 text-[10px] font-black uppercase tracking-normal ${badgeClass(evaluation.status)}`}>{evaluation.status} · {Math.round(evaluation.score * 100)}%</span>
      </div>
      <p className="mt-2 text-[11px] font-bold leading-5 text-slate-400">{caseDescription(evaluation.case)}</p>
    </div>
  );
}

function Scorecard({ session }: { session: HandshakeSession }) {
  const evaluations = [...(session.case_evaluations ?? [])].slice(-8).reverse();
  if (!evaluations.length) return null;
  const passed = evaluations.filter((evaluation) => evaluation.status === "passed").length;
  const average = evaluations.reduce((total, evaluation) => total + evaluation.score, 0) / evaluations.length;
  const coverage = ["Trust", "Authority", "Policy", "Action"].map((group) => {
    const groupEvaluations = evaluations.filter((evaluation) => caseGroup(evaluation.case) === group);
    return { group, count: groupEvaluations.length, passed: groupEvaluations.some((evaluation) => evaluation.status === "passed") };
  });
  const required = [
    { case: "identity_trust", label: "Identity" },
    { case: "capability_scope", label: "Scope" },
    { case: "commerce_payment_probe", label: "Commerce" },
    { case: "queue_reroute", label: "Action" },
  ];
  return (
    <section className="rounded-lg border border-slate-800 bg-[#11161a] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[11px] font-black uppercase tracking-normal text-slate-500">Automatic case evaluation</div>
          <h2 className="mt-1 text-xl font-black text-slate-100">Judge scorecard</h2>
          <p className="mt-2 max-w-2xl text-sm font-bold leading-6 text-slate-400">Each protocol case is scored by deterministic criteria from the handshake, policy, and internal-agent audit trail.</p>
        </div>
        <div className="rounded border border-slate-700 bg-slate-950 px-4 py-3 text-right">
          <div className={`text-2xl font-black ${scoreClass(average)}`}>{Math.round(average * 100)}%</div>
          <div className="mt-1 text-[10px] font-black uppercase tracking-normal text-slate-500">{passed}/{evaluations.length} cases passed</div>
        </div>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-4">
        {coverage.map((item) => (
          <div key={item.group} className="rounded border border-slate-800 bg-slate-950 p-3">
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs font-black text-slate-100">{item.group}</div>
              <span className={`rounded border px-2 py-1 text-[9px] font-black uppercase tracking-normal ${badgeClass(item.passed ? "passed" : "failed")}`}>{item.passed ? "covered" : "missing"}</span>
            </div>
            <div className="mt-2 text-[11px] font-bold text-slate-500">{item.count} evaluated case{item.count === 1 ? "" : "s"}</div>
          </div>
        ))}
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-4">
        {required.map((item) => {
          const proven = evaluations.some((evaluation) => evaluation.case === item.case && evaluation.status === "passed");
          return (
            <div key={item.case} className="flex items-center justify-between gap-2 rounded border border-slate-800 bg-[#0b1014] px-3 py-2">
              <span className="text-[11px] font-black uppercase tracking-normal text-slate-400">{item.label}</span>
              <span className={`rounded border px-2 py-1 text-[9px] font-black uppercase tracking-normal ${badgeClass(proven ? "passed" : "failed")}`}>{proven ? "proven" : "open"}</span>
            </div>
          );
        })}
      </div>
      <div className="mt-4 grid gap-3">
        {evaluations.map((evaluation) => (
          <article key={evaluation.id} className="rounded border border-slate-800 bg-slate-950 p-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <div className="text-sm font-black text-slate-100">{caseLabel(evaluation.case)}</div>
                  <span className="rounded border border-slate-700 px-2 py-0.5 text-[9px] font-black uppercase tracking-normal text-slate-400">{caseGroup(evaluation.case)}</span>
                </div>
                <p className="mt-1 text-[11px] font-bold leading-5 text-slate-500">{evaluation.passed_criteria}/{evaluation.total_criteria} criteria · {caseDescription(evaluation.case)}</p>
              </div>
              <span className={`rounded border px-2 py-1 text-[10px] font-black uppercase tracking-normal ${badgeClass(evaluation.status)}`}>{evaluation.status} · {Math.round(evaluation.score * 100)}%</span>
            </div>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {Object.entries(evaluation.criteria ?? {}).map(([criterion, ok]) => (
                <div key={criterion} className="flex items-center justify-between gap-2 rounded border border-slate-800 bg-[#0b1014] px-2 py-1.5">
                  <span className="text-[11px] font-bold text-slate-300">{titleize(criterion)}</span>
                  <span className={`rounded border px-1.5 py-0.5 text-[9px] font-black uppercase tracking-normal ${badgeClass(ok ? "passed" : "failed")}`}>{ok ? "pass" : "fail"}</span>
                </div>
              ))}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function AgentOnboardingPanel({
  agent,
  running,
  onCertifyFull,
  onCertifyUnderScoped,
  credentialVerification,
  onVerifyCredential,
}: {
  agent: OnboardedAgent | null;
  running: boolean;
  onCertifyFull: () => void;
  onCertifyUnderScoped: () => void;
  credentialVerification: CredentialVerification | null;
  onVerifyCredential: () => void;
}) {
  const certification = agent?.certification;
  const credential = certification?.credential;
  const requiredCases = Object.entries(certification?.required_cases ?? {});
  return (
    <section className="mx-auto max-w-7xl px-4 pb-6 md:px-8">
      <div className="rounded-lg border border-slate-800 bg-[#11161a] p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-[11px] font-black uppercase tracking-normal text-slate-500">Agent onboarding</div>
            <h2 className="mt-1 text-xl font-black text-slate-100">External agent certification</h2>
            <p className="mt-2 max-w-3xl text-sm font-bold leading-6 text-slate-400">
              Register an outside personal agent, issue scoped delegation, run conformance, and decide whether it is approved for guest route planning.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={onCertifyFull} disabled={running} className="rounded border border-emerald-300 bg-emerald-300 px-4 py-3 text-sm font-black text-slate-950 hover:bg-emerald-200 disabled:cursor-not-allowed disabled:opacity-50">
              {running ? "Certifying" : "Certify full-scope agent"}
            </button>
            <button type="button" onClick={onCertifyUnderScoped} disabled={running} className="rounded border border-rose-300 px-4 py-3 text-sm font-black text-rose-100 hover:bg-rose-300 hover:text-slate-950 disabled:cursor-not-allowed disabled:opacity-50">
              Test under-scoped agent
            </button>
          </div>
        </div>
        <div className="mt-4 grid gap-3 lg:grid-cols-[.8fr_1.2fr]">
          <div className="rounded border border-slate-800 bg-slate-950 p-3">
            <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Registered agent</div>
            <div className="mt-2 text-lg font-black text-slate-100">{agent?.display_name ?? "No agent certified yet"}</div>
            <div className="mt-3 flex flex-wrap gap-2">
              <span className={`rounded border px-2 py-1 text-[10px] font-black uppercase tracking-normal ${badgeClass(agent?.status)}`}>{agent?.status ?? "idle"}</span>
              <span className="rounded border border-slate-700 px-2 py-1 text-[10px] font-black uppercase tracking-normal text-slate-300">{titleize(agent?.approval ?? "pending")}</span>
            </div>
            {certification ? (
              <div className="mt-4 rounded border border-slate-800 bg-[#0b1014] p-3">
                <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Certification score</div>
                <div className={`mt-1 text-3xl font-black ${scoreClass(certification.score)}`}>{Math.round(certification.score * 100)}%</div>
                <div className="mt-1 text-xs font-bold text-slate-500">{certification.passed_cases.length}/4 required cases passed</div>
              </div>
            ) : null}
          </div>
          <div className="rounded border border-slate-800 bg-slate-950 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Certification cases</div>
              {certification ? <span className={`rounded border px-2 py-1 text-[10px] font-black uppercase tracking-normal ${badgeClass(certification.status)}`}>{certification.status}</span> : null}
            </div>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {(requiredCases.length ? requiredCases : fullAgentScopes.slice(0, 4).map((scope) => [scope, { status: "waiting", score: 0 }] as const)).map(([caseId, result]) => (
                <div key={caseId} className="flex items-center justify-between gap-2 rounded border border-slate-800 bg-[#0b1014] px-3 py-2">
                  <span className="text-xs font-black text-slate-100">{caseLabel(caseId)}</span>
                  <span className={`rounded border px-2 py-1 text-[9px] font-black uppercase tracking-normal ${badgeClass(result.status)}`}>{titleize(result.status)}</span>
                </div>
              ))}
            </div>
            {certification?.readiness_issues.length ? (
              <div className="mt-3 rounded border border-rose-300/50 bg-[#0b1014] p-3 text-xs font-bold leading-5 text-rose-100">
                {certification.readiness_issues.join(" ")}
              </div>
            ) : null}
            {agent?.allowed_scopes.length ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {agent.allowed_scopes.slice(0, 8).map((scope) => (
                  <span key={scope} className="rounded border border-cyan-300/60 px-2 py-1 text-[10px] font-black uppercase tracking-normal text-cyan-100">{titleize(scope)}</span>
                ))}
              </div>
            ) : null}
          </div>
        </div>
        {credential ? (
          <div className="mt-3 rounded border border-slate-800 bg-slate-950 p-3">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Signed certification credential</div>
                <div className="mt-1 text-sm font-black text-slate-100">{credential.certification_id}</div>
                <p className="mt-2 text-xs font-bold leading-5 text-slate-400">This credential can be presented by the external agent later and verified without rerunning onboarding.</p>
              </div>
              <button type="button" onClick={onVerifyCredential} disabled={running} className="rounded border border-cyan-300/80 px-3 py-2 text-xs font-black text-cyan-100 hover:bg-cyan-300 hover:text-slate-950 disabled:cursor-not-allowed disabled:opacity-50">
                Verify credential
              </button>
            </div>
            <div className="mt-3 grid gap-2 md:grid-cols-3">
              <div className="rounded border border-slate-800 bg-[#0b1014] px-3 py-2">
                <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Approval</div>
                <div className="mt-1 text-xs font-black text-emerald-100">{titleize(String(credential.approval ?? "unknown"))}</div>
              </div>
              <div className="rounded border border-slate-800 bg-[#0b1014] px-3 py-2">
                <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Signature</div>
                <div className="mt-1 truncate text-xs font-black text-slate-300">{String(credential.sig ?? "")}</div>
              </div>
              <div className="rounded border border-slate-800 bg-[#0b1014] px-3 py-2">
                <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Verification</div>
                <div className={`mt-1 inline-flex rounded border px-2 py-1 text-[10px] font-black uppercase tracking-normal ${badgeClass(credentialVerification?.status)}`}>{credentialVerification?.status ?? "not verified"}</div>
              </div>
            </div>
            {credentialVerification?.reason ? <p className="mt-2 text-xs font-bold leading-5 text-slate-400">{credentialVerification.reason}</p> : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}

function TrustAdminGatePanel({ probe, running, onRun }: { probe: TrustAdminProbe; running: boolean; onRun: () => void }) {
  const checks = [
    { label: "No token", value: probe.unauthStatus, expected: 401 },
    { label: "Ops token", value: probe.opsStatus, expected: 403 },
    { label: "Admin token", value: probe.adminStatus, expected: 200 },
    { label: "Partner write", value: probe.partnerStatus, expected: 200 },
  ];
  return (
    <section className="mx-auto max-w-7xl px-4 pb-6 md:px-8">
      <div className="rounded-lg border border-slate-800 bg-[#11161a] p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-[11px] font-black uppercase tracking-normal text-slate-500">Trust admin gate</div>
            <h2 className="mt-1 text-xl font-black text-slate-100">Role-token proof</h2>
            <p className="mt-2 max-w-3xl text-sm font-bold leading-6 text-slate-400">Protected trust routes require the manage_agent_trust capability. The probe checks no token, ops token, and ml_ops_admin token behavior.</p>
          </div>
          <button type="button" onClick={onRun} disabled={running} className="rounded border border-fuchsia-300 bg-fuchsia-300 px-4 py-3 text-sm font-black text-slate-950 hover:bg-fuchsia-200 disabled:cursor-not-allowed disabled:opacity-50">
            {running ? "Probing gate" : "Run trust gate proof"}
          </button>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-4">
          {checks.map((check) => {
            const passed = check.value === check.expected;
            return (
              <div key={check.label} className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">{check.label}</div>
                <div className={`mt-1 text-2xl font-black ${passed ? "text-emerald-200" : check.value ? "text-rose-200" : "text-slate-300"}`}>{check.value ?? "-"}</div>
                <div className="mt-1 text-[10px] font-black uppercase tracking-normal text-slate-500">Expected {check.expected}</div>
              </div>
            );
          })}
        </div>
        <div className="mt-3 grid gap-2 rounded border border-slate-800 bg-slate-950 p-3 md:grid-cols-3">
          <div>
            <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Probe status</div>
            <div className={`mt-1 inline-flex rounded border px-2 py-1 text-[10px] font-black uppercase tracking-normal ${badgeClass(probe.status)}`}>{probe.status}</div>
          </div>
          <div>
            <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Admin role</div>
            <div className="mt-1 truncate text-xs font-black text-cyan-100">{probe.adminRole ?? "not issued"}</div>
          </div>
          <div>
            <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Active key</div>
            <div className="mt-1 truncate text-xs font-black text-amber-100">{probe.activeKey ?? "not loaded"}</div>
          </div>
        </div>
        <div className="mt-3 grid gap-2 rounded border border-slate-800 bg-slate-950 p-3 sm:grid-cols-4">
          {[
            ["Auth mode", probe.authMode ?? "unknown"],
            ["Production ready", probe.productionReady ? "yes" : "no"],
            ["External identity", probe.externalIdentityReady ? "ready" : "not ready"],
            ["Dev issuer", probe.devIssuerEnabled ? "enabled" : "disabled"],
          ].map(([label, value]) => (
            <div key={label} className="rounded border border-slate-800 bg-[#0b1014] px-3 py-2">
              <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">{label}</div>
              <div className="mt-1 text-xs font-black text-slate-100">{value}</div>
            </div>
          ))}
        </div>
        {probe.reason ? <p className="mt-3 rounded border border-slate-800 bg-slate-950 p-3 text-xs font-bold leading-5 text-slate-400">{probe.reason}</p> : null}
      </div>
    </section>
  );
}

function Simulator({ steps, running, onRun, onReject }: { steps: SimulatorStep[]; running: boolean; onRun: () => void; onReject: () => void }) {
  return (
    <section className="mx-auto max-w-7xl px-4 pb-6 md:px-8">
      <div className="rounded-lg border border-slate-800 bg-[#11161a] p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-[11px] font-black uppercase tracking-normal text-slate-500">External counterparty</div>
            <h2 className="mt-1 text-xl font-black text-slate-100">Client-agent simulator</h2>
            <p className="mt-2 max-w-3xl text-sm font-bold leading-6 text-slate-400">John&apos;s personal agent calls the ParkPulse contract directly, negotiates a route, commits it, monitors live state, and probes gated commerce.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={onRun} disabled={running} className="rounded border border-cyan-300 bg-cyan-300 px-4 py-3 text-sm font-black text-slate-950 hover:bg-cyan-200 disabled:cursor-not-allowed disabled:opacity-50">
              {running ? "Running protocol" : "Run client agent"}
            </button>
            <button type="button" onClick={onReject} disabled={running} className="rounded border border-rose-300 px-4 py-3 text-sm font-black text-rose-100 hover:bg-rose-300 hover:text-slate-950 disabled:cursor-not-allowed disabled:opacity-50">
              Run rejection demo
            </button>
          </div>
        </div>
        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          {steps.map((step, index) => (
            <article key={step.id} className="rounded border border-slate-800 bg-slate-950 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Call {index + 1}</div>
                  <div className="mt-1 text-sm font-black text-slate-100">{step.label}</div>
                </div>
                <span className={`rounded border px-2 py-1 text-[10px] font-black uppercase tracking-normal ${badgeClass(step.state ?? step.status)}`}>{step.state ?? step.status}</span>
              </div>
              <div className="mt-3 rounded border border-slate-800 bg-[#0b1014] px-3 py-2 text-[11px] font-black text-cyan-200">{step.path}</div>
              <EvaluationSummary evaluation={step.caseEvaluation} />
              <pre className="mt-3 max-h-52 overflow-auto whitespace-pre-wrap break-words rounded bg-[#0b1014] p-3 text-[11px] leading-relaxed text-slate-300">{step.response ? JSON.stringify(step.response, null, 2) : JSON.stringify(step.request, null, 2)}</pre>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function SessionPanels({ session }: { session: HandshakeSession }) {
  const proposal = session.proposal;
  const handoffs = [...(session.internal_handoffs ?? [])].slice(-10).reverse();
  const decisions = [...(session.policy_decisions ?? [])].slice(-8).reverse();
  return (
    <section className="mx-auto grid max-w-7xl gap-4 px-4 pb-10 md:px-8 lg:grid-cols-[1.15fr_.85fr]">
      <div className="space-y-4">
        <Scorecard session={session} />
        {proposal ? (
          <section className="rounded-lg border border-slate-800 bg-[#11161a] p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="text-[11px] font-black uppercase tracking-normal text-slate-500">Active proposal</div>
                <h2 className="mt-1 text-xl font-black text-slate-100">{proposal.proposal_id}</h2>
              </div>
              <div className="rounded border border-emerald-300 bg-emerald-300 px-3 py-2 text-sm font-black text-slate-950">{Math.round(proposal.confidence * 100)}% confidence</div>
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-4">
              {proposal.plan.map((stop, index) => (
                <div key={`${stop}-${index}`} className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Stop {index + 1}</div>
                  <div className="mt-1 text-sm font-black text-slate-100">{stop}</div>
                </div>
              ))}
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-3">
              <div className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Wait saved</div>
                <div className="mt-1 text-lg font-black text-cyan-200">{proposal.expected_wait_saved}</div>
              </div>
              <div className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Walking</div>
                <div className="mt-1 text-lg font-black text-amber-200">{proposal.estimated_walking_distance}</div>
              </div>
              <div className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="text-[10px] font-black uppercase tracking-normal text-slate-500">Evidence</div>
                <div className="mt-1 text-lg font-black text-emerald-200">{titleize(proposal.state_evidence?.source ?? "protocol")}</div>
              </div>
            </div>
            <p className="mt-4 text-sm font-bold leading-6 text-slate-300">{proposal.rationale}</p>
          </section>
        ) : null}
        <section className="rounded-lg border border-slate-800 bg-[#11161a] p-4">
          <div className="text-[11px] font-black uppercase tracking-normal text-slate-500">Internal agent handoff</div>
          <h2 className="mt-1 text-xl font-black text-slate-100">Park agent routing board</h2>
          <div className="mt-4 grid gap-3">
            {handoffs.map((handoff) => (
              <article key={handoff.id} className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <div className="text-sm font-black text-slate-100">{handoff.internal_agent}</div>
                    <p className="mt-1 text-xs font-bold leading-5 text-slate-400">{handoff.trigger}</p>
                  </div>
                  <span className={`rounded border px-2 py-1 text-[10px] font-black uppercase tracking-normal ${badgeClass(handoff.decision)}`}>{titleize(handoff.decision)}</span>
                </div>
              </article>
            ))}
          </div>
        </section>
        <section className="rounded-lg border border-slate-800 bg-[#11161a] p-4">
          <div className="text-[11px] font-black uppercase tracking-normal text-slate-500">Policy boundary</div>
          <h2 className="mt-1 text-xl font-black text-slate-100">Delegated authority</h2>
          <div className="mt-4 grid gap-3">
            {decisions.map((decision) => (
              <article key={decision.id} className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="text-sm font-black text-slate-100">{titleize(decision.action)}</div>
                  <span className={`rounded border px-2 py-1 text-[10px] font-black uppercase tracking-normal ${badgeClass(decision.status)}`}>{titleize(decision.status)}</span>
                </div>
                <p className="mt-2 text-xs font-bold leading-5 text-slate-400">{decision.reason}</p>
              </article>
            ))}
          </div>
        </section>
      </div>
      <section className="rounded-lg border border-slate-800 bg-[#11161a] p-4">
        <div className="flex items-end justify-between gap-3">
          <div>
            <div className="text-[11px] font-black uppercase tracking-normal text-slate-500">Negotiation ledger</div>
            <h2 className="mt-1 text-xl font-black text-slate-100">Agent-to-agent turns</h2>
          </div>
          <div className="rounded border border-slate-700 px-3 py-2 text-xs font-black text-slate-300">{session.conversation.length} events</div>
        </div>
        <div className="mt-4 max-h-[740px] space-y-3 overflow-y-auto pr-1">
          {session.conversation.map((turn, index) => (
            <article key={`${turn.at}-${index}`} className="rounded border border-slate-800 bg-slate-950 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className={`rounded border px-2 py-1 text-[10px] font-black uppercase tracking-normal ${turn.actor === "park_agent" ? "border-cyan-300 bg-cyan-300 text-slate-950" : "border-amber-300 bg-amber-300 text-slate-950"}`}>{titleize(turn.actor)}</span>
                <span className="text-xs font-black uppercase tracking-normal text-slate-500">{titleize(turn.action)}</span>
              </div>
              <pre className="mt-3 max-h-44 overflow-auto whitespace-pre-wrap break-words rounded bg-[#0b1014] p-3 text-xs leading-relaxed text-slate-300">{JSON.stringify(turn.payload, null, 2)}</pre>
            </article>
          ))}
        </div>
      </section>
    </section>
  );
}

export default function AgentHandshakePage() {
  const [contract, setContract] = useState<AgentContract | null>(null);
  const [session, setSession] = useState<HandshakeSession | null>(null);
  const [steps, setSteps] = useState<SimulatorStep[]>([]);
  const [onboardedAgent, setOnboardedAgent] = useState<OnboardedAgent | null>(null);
  const [credentialVerification, setCredentialVerification] = useState<CredentialVerification | null>(null);
  const [trustAdminProbe, setTrustAdminProbe] = useState<TrustAdminProbe>({ status: "idle" });
  const [trustAdminRunning, setTrustAdminRunning] = useState(false);
  const [onboardingRunning, setOnboardingRunning] = useState(false);
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState("ready");
  const [error, setError] = useState<string | null>(null);

  const clientItems = useMemo(() => ["Represents John and family", "Can share location, party size, preferences, accessibility needs", "Cannot purchase, share health data, or accept refunds"], []);
  const parkItems = useMemo(() => ["Represents park operations", "Offers itinerary, queue, food, safety, and compensation options", "Requires approval for payment, refund, medical, and identity-sensitive action"], []);

  async function loadContract() {
    try {
      setContract(await readJson<AgentContract>("/api/park/agent-contract"));
    } catch {
      setContract(null);
    }
  }

  async function loadDemo() {
    try {
      const payload = await readJson<{ session: HandshakeSession }>("/api/park/agent-handshake/demo", { method: "POST", headers: jsonHeaders, body: "{}" });
      setSession(payload.session);
      setStatus("ready");
    } catch (apiError) {
      setError(apiError instanceof Error ? apiError.message : "Unable to load demo.");
      setStatus("error");
    }
  }

  function updateStep(id: string, patch: Partial<SimulatorStep>) {
    setSteps((items) => items.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  }

  async function callStep(id: string, path: string, request: Record<string, unknown>) {
    updateStep(id, { status: "running", path, request });
    const payload = await readJson<Record<string, unknown>>(path, { method: "POST", headers: jsonHeaders, body: JSON.stringify(request) });
    const responseSession = payload.session as HandshakeSession | undefined;
    const evaluation = latestEvaluation(payload, responseSession);
    updateStep(id, { status: "done", response: payload, state: evaluation?.status ?? responseSession?.state ?? String(payload.status ?? "done"), caseEvaluation: evaluation });
    if (responseSession) setSession(responseSession);
    return payload;
  }

  async function certifyAgent(mode: "full" | "under_scoped") {
    setOnboardingRunning(true);
    setError(null);
    setCredentialVerification(null);
    const fullScope = mode === "full";
    const agentId = fullScope ? "certified_family_agent" : "under_scoped_family_agent";
    const requestedScopes = fullScope ? fullAgentScopes : ["location", "party_size", "preferences"];
    try {
      const registered = await readJson<{ agent: OnboardedAgent }>("/api/park/agent-onboarding/register", {
        method: "POST",
        headers: jsonHeaders,
        body: JSON.stringify({
          agent_id: agentId,
          display_name: fullScope ? "Certified Family Agent" : "Under Scoped Family Agent",
          requested_scopes: requestedScopes,
          cannot_do: fullScope ? ["auto_purchase", "share_health_data", "accept_refund_without_user"] : ["auto_purchase"],
          use_case: "guest_route_planning",
        }),
      });
      setOnboardedAgent(registered.agent);
      const certified = await readJson<{ agent: OnboardedAgent; certification: OnboardingCertification; session?: HandshakeSession | null }>(`/api/park/agent-onboarding/${agentId}/certify`, {
        method: "POST",
        headers: jsonHeaders,
        timeoutMs: 90000,
        body: JSON.stringify({ requested_scopes: requestedScopes }),
      } as RequestInit & { timeoutMs: number });
      setOnboardedAgent(certified.agent);
      if (certified.session) setSession(certified.session);
      setStatus("ready");
    } catch (apiError) {
      setError(apiError instanceof Error ? apiError.message : "Unable to certify external agent.");
      setStatus("error");
    } finally {
      setOnboardingRunning(false);
    }
  }

  async function verifyCredential() {
    const credential = onboardedAgent?.certification?.credential;
    if (!credential) return;
    setOnboardingRunning(true);
    setError(null);
    try {
      const verified = await readJson<CredentialVerification>("/api/park/agent-onboarding/verify-credential", {
        method: "POST",
        headers: jsonHeaders,
        body: JSON.stringify({ credential }),
      });
      setCredentialVerification(verified);
    } catch (apiError) {
      setError(apiError instanceof Error ? apiError.message : "Unable to verify certification credential.");
      setStatus("error");
    } finally {
      setOnboardingRunning(false);
    }
  }

  async function runTrustAdminGate() {
    setTrustAdminRunning(true);
    setError(null);
    setTrustAdminProbe({ status: "running" });
    try {
      const unauth = await readJsonWithStatus("/api/park/agent-trust/keys");
      const readiness = await readJsonWithStatus("/api/park/agent-trust/status");
      const authBoundary = readiness.payload.auth_boundary as { mode?: string; production_ready?: boolean; external_identity_ready?: boolean; dev_role_issuer_enabled?: boolean } | undefined;
      const adminIssued = await readJsonWithStatus("/api/park/auth/dev-session", {
        method: "POST",
        headers: jsonHeaders,
        body: JSON.stringify({ role: "ml_ops_admin", subject: "agent-handshake-ui" }),
      });
      if (!adminIssued.ok || typeof adminIssued.payload.token !== "string") {
        setTrustAdminProbe({
          status: "error",
          unauthStatus: unauth.status,
          authMode: authBoundary?.mode,
          productionReady: Boolean(authBoundary?.production_ready),
          externalIdentityReady: Boolean(authBoundary?.external_identity_ready),
          devIssuerEnabled: Boolean(authBoundary?.dev_role_issuer_enabled),
          reason: "Local dev role issuer did not provide an admin token. Enable PARKPULSE_ENABLE_DEV_ROLE_ISSUER for the local demo or use a production identity provider.",
        });
        return;
      }
      const opsIssued = await readJsonWithStatus("/api/park/auth/dev-session", {
        method: "POST",
        headers: jsonHeaders,
        body: JSON.stringify({ role: "ops_team", subject: "agent-handshake-ui-ops" }),
      });
      const adminHeaders = { ...jsonHeaders, "x-parkpulse-role-token": String(adminIssued.payload.token) };
      const opsHeaders = typeof opsIssued.payload.token === "string" ? { ...jsonHeaders, "x-parkpulse-role-token": String(opsIssued.payload.token) } : jsonHeaders;
      const opsProbe = await readJsonWithStatus("/api/park/agent-trust/keys", { headers: opsHeaders });
      const keys = await readJsonWithStatus("/api/park/agent-trust/keys", { headers: adminHeaders });
      const partner = await readJsonWithStatus("/api/park/agent-trust/partners", {
        method: "POST",
        headers: adminHeaders,
        body: JSON.stringify({
          partner_id: "ui_trust_probe_partner",
          partner_name: "UI Trust Probe Partner",
          allowed_scopes: ["location", "party_size", "preferences", "route_plan", "wait_time_alert", "policy_check"],
          actor: "agent-handshake-ui",
        }),
      });
      const activeKey = keys.payload.active_key as { kid?: string } | undefined;
      const passed = unauth.status === 401 && opsProbe.status === 403 && keys.status === 200 && partner.status === 200;
      setTrustAdminProbe({
        status: passed ? "passed" : "blocked",
        unauthStatus: unauth.status,
        opsStatus: opsProbe.status,
        adminStatus: keys.status,
        partnerStatus: partner.status,
        adminRole: String(adminIssued.payload.role ?? "ml_ops_admin"),
        activeKey: activeKey?.kid,
        authMode: authBoundary?.mode,
        productionReady: Boolean(authBoundary?.production_ready),
        externalIdentityReady: Boolean(authBoundary?.external_identity_ready),
        devIssuerEnabled: Boolean(authBoundary?.dev_role_issuer_enabled),
        reason: passed ? "Trust-admin gate is enforced and ml_ops_admin can manage the durable registry." : "One or more role-gate expectations did not match.",
      });
    } catch (apiError) {
      setTrustAdminProbe({ status: "error", reason: apiError instanceof Error ? apiError.message : "Unable to run trust admin gate proof." });
      setError(apiError instanceof Error ? apiError.message : "Unable to run trust admin gate proof.");
    } finally {
      setTrustAdminRunning(false);
    }
  }

  async function runClientAgent() {
    setRunning(true);
    setError(null);
    const tokenRequest = {
      subject: "guest_user_123",
      agent_id: "john_personal_agent",
      scope: ["location", "party_size", "preferences", "accessibility_needs", "budget", "ride_preference", "route_plan", "wait_time_alert", "food_recommendation", "safety_notice", "compensation_offer", "policy_check", "session_commit"],
      cannot_do: ["auto_purchase", "share_health_data", "accept_refund_without_user"],
      ttl_seconds: 10800,
    };
    const baseSteps: SimulatorStep[] = [
      { id: "delegation", label: "Issue delegation token", path: "/api/park/delegation-token", request: tokenRequest, status: "pending" },
      { id: "identity", label: "Identity handshake", path: "/api/park/handshake", request: {}, status: "pending" },
      { id: "capability", label: "Capability handshake", path: "/api/park/session/{session_id}/capabilities", request: {}, status: "pending" },
      { id: "intent", label: "Intent handshake", path: "/api/park/session/{session_id}/intent", request: {}, status: "pending" },
      { id: "propose", label: "Live proposal", path: "/api/park/session/{session_id}/propose", request: {}, status: "pending" },
      { id: "counter", label: "Client counter", path: "/api/park/session/{session_id}/counter", request: {}, status: "pending" },
      { id: "commit", label: "Commit route", path: "/api/park/session/{session_id}/commit", request: {}, status: "pending" },
      { id: "monitor", label: "Monitor live state", path: "/api/park/session/{session_id}/monitor", request: {}, status: "pending" },
      { id: "commerce", label: "Direct Commerce Agent", path: "/api/park/internal-agents/commerce/evaluate", request: {}, status: "pending" },
      { id: "queue", label: "Direct Queue Agent", path: "/api/park/internal-agents/queue/reroute", request: {}, status: "pending" },
    ];
    setSteps(baseSteps);
    try {
      const issued = await callStep("delegation", "/api/park/delegation-token", tokenRequest);
      const token = issued.token as DelegationToken;
      const withToken = (request: Record<string, unknown>) => ({ ...request, delegation_token: token });
      const identity = await callStep(
        "identity",
        "/api/park/handshake",
        withToken({ agent_id: "john_personal_agent", represents: "guest_user_123", proof: "signed_token", requested_session: `park_visit_${Date.now()}` }),
      );
      const sessionId = (identity.session as HandshakeSession).session_id;
      await callStep("capability", `/api/park/session/${sessionId}/capabilities`, withToken({ can_share: ["location", "party_size", "preferences", "accessibility_needs", "budget", "ride_preference"], can_receive: ["route_plan", "wait_time_alert", "food_recommendation", "safety_notice", "compensation_offer"], cannot_do: ["auto_purchase", "share_health_data", "accept_refund_without_user"] }));
      await callStep("intent", `/api/park/session/${sessionId}/intent`, withToken({ goal: "maximize_family_satisfaction", time_window: "3_hours", constraints: { children: 2, avoid_wait_over_minutes: 35, avoid_thrill_rides: true, food_allergy: "peanut" } }));
      await callStep("propose", `/api/park/session/${sessionId}/propose`, withToken({ planner: "live_state", horizon: "3_hours" }));
      await callStep("counter", `/api/park/session/${sessionId}/counter`, withToken({ counter_request: "reduce walking distance", priority_change: { walking_distance: "highest", wait_time: "medium" } }));
      await callStep("commit", `/api/park/session/${sessionId}/commit`, withToken({ accepted: true, notify_user: true }));
      await callStep("monitor", `/api/park/session/${sessionId}/monitor`, withToken({ event: "live" }));
      await callStep("commerce", "/api/park/internal-agents/commerce/evaluate", withToken({ session_id: sessionId, action: "payment", amount: 42, reason: "Direct Commerce Agent charge probe." }));
      await callStep("queue", "/api/park/internal-agents/queue/reroute", withToken({ session_id: sessionId, walking_priority: "highest", reason: "Avoid current congestion and long waits." }));
      setStatus("ready");
    } catch (apiError) {
      setError(apiError instanceof Error ? apiError.message : "Unable to run client-agent simulator.");
      setSteps((items) => items.map((item) => (item.status === "running" ? { ...item, status: "error" } : item)));
      setStatus("error");
    } finally {
      setRunning(false);
    }
  }

  async function runRejectionDemo() {
    setRunning(true);
    setError(null);
    const tokenRequest = { subject: "guest_user_123", agent_id: "john_personal_agent", scope: ["location", "party_size", "preferences"], cannot_do: ["auto_purchase"], ttl_seconds: 10800 };
    const rejectionSteps: SimulatorStep[] = [
      { id: "delegation", label: "Issue under-scoped token", path: "/api/park/delegation-token", request: tokenRequest, status: "pending" },
      { id: "identity", label: "Identity accepted", path: "/api/park/handshake", request: {}, status: "pending" },
      { id: "capability", label: "Capability rejected", path: "/api/park/session/{session_id}/capabilities", request: {}, status: "pending" },
    ];
    setSteps(rejectionSteps);
    try {
      const issued = await callStep("delegation", "/api/park/delegation-token", tokenRequest);
      const token = issued.token as DelegationToken;
      const identity = await callStep("identity", "/api/park/handshake", { agent_id: "john_personal_agent", represents: "guest_user_123", proof: "signed_token", requested_session: `rejected_${Date.now()}`, delegation_token: token });
      const sessionId = (identity.session as HandshakeSession).session_id;
      const request = { can_share: ["location", "party_size", "preferences"], can_receive: ["route_plan", "wait_time_alert"], cannot_do: ["auto_purchase"], delegation_token: token };
      updateStep("capability", { status: "running", path: `/api/park/session/${sessionId}/capabilities`, request });
      const rejected = await readJsonWithStatus(`/api/park/session/${sessionId}/capabilities`, { method: "POST", headers: jsonHeaders, body: JSON.stringify(request) });
      const refreshed = await readJson<{ session: HandshakeSession }>(`/api/park/session/${sessionId}`);
      setSession(refreshed.session);
      updateStep("capability", {
        status: "done",
        response: { http_status: rejected.status, ...rejected.payload, session: refreshed.session },
        state: rejected.status === 403 ? "rejected" : "done",
        caseEvaluation: latestEvaluation(rejected.payload, refreshed.session),
      });
      setStatus("ready");
    } catch (apiError) {
      setError(apiError instanceof Error ? apiError.message : "Unable to run rejection demo.");
      setStatus("error");
    } finally {
      setRunning(false);
    }
  }

  useEffect(() => {
    void loadContract();
  }, []);

  const activeState = session?.state ?? "verified";

  return (
    <main className="min-h-screen bg-[#090d10] text-slate-100">
      <section className="border-b border-slate-800 bg-[#0d1317]">
        <div className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-8 md:px-8">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="text-[11px] font-black uppercase tracking-normal text-cyan-200">ParkPulse agent contract</div>
              <h1 className="mt-2 text-4xl font-black tracking-normal text-slate-100 md:text-6xl">Agent-to-agent handshake</h1>
              <p className="mt-3 max-w-3xl text-base font-bold leading-7 text-slate-400">A personal client agent and the ParkPulse park agent verify identity, scope permissions, negotiate a family plan, commit a route, and monitor outcomes through explicit policy gates.</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={loadDemo} className="rounded border border-cyan-300 px-4 py-3 text-sm font-black text-cyan-100 hover:bg-cyan-300 hover:text-slate-950">Run demo</button>
            </div>
          </div>
          {error ? <div className="rounded border border-rose-300 bg-rose-300 px-4 py-3 text-sm font-black text-slate-950">{error}</div> : null}
          <StateRail activeState={activeState} />
          <div className="text-xs font-black uppercase tracking-normal text-slate-500">Status: {status}</div>
        </div>
      </section>

      <section className="mx-auto grid max-w-7xl gap-4 px-4 py-6 md:px-8 lg:grid-cols-[1fr_1.1fr_1fr]">
        <AgentCard title="User's Personal Agent" subtitle="Client counterparty" items={clientItems} accent="bg-amber-300" />
        <MiniMap activeState={activeState} />
        <AgentCard title="ParkPulse Park Agent" subtitle="Park counterparty" items={parkItems} accent="bg-cyan-300" />
      </section>

      <ProtocolExplorer />
      <ContractPanel contract={contract} />
      <AgentOnboardingPanel agent={onboardedAgent} running={onboardingRunning} credentialVerification={credentialVerification} onVerifyCredential={() => void verifyCredential()} onCertifyFull={() => void certifyAgent("full")} onCertifyUnderScoped={() => void certifyAgent("under_scoped")} />
      <TrustAdminGatePanel probe={trustAdminProbe} running={trustAdminRunning} onRun={() => void runTrustAdminGate()} />
      <Simulator steps={steps} running={running} onRun={runClientAgent} onReject={runRejectionDemo} />
      {session ? <SessionPanels session={session} /> : null}
    </main>
  );
}
