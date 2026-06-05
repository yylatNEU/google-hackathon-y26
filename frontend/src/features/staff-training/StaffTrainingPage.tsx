"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { fetchParkPulseApi } from "@/lib/api";

type Scenario = {
  id: string;
  title: string;
  category: string;
  difficulty: string;
  guest_role: string;
  opening_message: string;
  context: string;
  objectives: string[];
};

type TranscriptTurn = {
  speaker?: string;
  message?: string;
  source?: string;
};

type Scorecard = {
  overall?: number;
  turn_count?: number;
  dimensions?: Record<string, number>;
};

type GuestSimulator = {
  mode?: string;
  llm_requested?: boolean;
  llm_status?: string;
  llm_controls_score?: boolean;
  source?: string;
  model?: string;
};

type MasteryTracker = {
  status?: string;
  mastery_level?: string;
  turn_count?: number;
  open_gaps?: Array<{ key?: string; type?: string; label?: string; severity?: string; first_seen_turn?: number; last_seen_turn?: number }>;
  repaired_gaps?: Array<{ key?: string; type?: string; label?: string; severity?: string; first_seen_turn?: number; repaired_at_turn?: number }>;
  latest_repairs?: Array<{ key?: string; type?: string; label?: string; severity?: string; repaired_at_turn?: number }>;
  repair_count?: number;
  unrepaired_critical_count?: number;
  summary?: string;
};

type ShadowEvaluator = {
  status?: string;
  alignment?: string;
  summary?: string;
  coaching_focus?: string[];
  rubric_disagreement?: string;
  suggested_human_review?: boolean;
  score_authority?: boolean;
  provider?: string;
  platform?: string;
  transport?: string;
  llm_controls_score?: boolean;
};

type Debrief = {
  result?: string;
  summary?: string;
  overall?: number;
  weakest_dimensions?: Array<{ dimension?: string; score?: number }>;
  missing_objectives?: string[];
  critical_miss?: boolean;
  recommended_retry?: string | null;
};

type ProductLearningTicket = {
  id?: string;
  source?: string;
  issue_type?: string;
  scenario_id?: string;
  gap_type?: string;
  severity?: string;
  location?: string | null;
  summary?: string;
  status?: string;
  live_ops_authority?: boolean;
  requires_human_ack?: boolean;
  boundary?: string;
};

type ProductLearningTicketResult = {
  status?: string;
  mode?: string;
  ticket?: ProductLearningTicket;
  reason?: string;
  feeds_training_model?: string;
  feeds_ops_model?: string;
  readiness_issues?: string[];
};

type TrainingSession = {
  id?: string;
  assignment_id?: string;
  retry_of_session_id?: string;
  status?: string;
  scenario?: Scenario;
  trainee_name?: string;
  turn_count?: number;
  transcript?: TranscriptTurn[];
  scorecard?: Scorecard;
  critical_miss?: boolean;
  completed_objectives?: string[];
  missing_objectives?: string[];
  guest_simulator?: GuestSimulator;
  mastery_tracker?: MasteryTracker;
  debrief?: Debrief;
  training_gap_ticket?: ProductLearningTicketResult | null;
};

type TurnScore = {
  overall?: number;
  dimensions?: Record<string, number>;
  coaching_notes?: string[];
  critical_miss?: boolean;
  turn_coaching?: {
    verdict?: string;
    headline?: string;
    priority?: string;
    strengths?: string[];
    misses?: Array<{ type?: string; label?: string }>;
    weak_dimensions?: Array<{ dimension?: string; label?: string; score?: number }>;
    next_response?: string;
    scoring_basis?: string;
  };
};

type Analytics = {
  status?: string;
  session_count?: number;
  scenario_summary?: Array<{ scenario_id?: string; title?: string; session_count?: number; average_overall?: number; critical_miss_count?: number }>;
  weakest_dimensions?: Array<{ dimension?: string; average?: number }>;
};

type Assignment = {
  id?: string;
  trainee_name?: string;
  staff_role?: string;
  scenario_ids?: string[];
  scenarios?: Scenario[];
  status?: string;
  completed_count?: number;
  required_count?: number;
  last_score?: number | null;
  critical_miss_count?: number;
};

type ReadinessRow = {
  assignment_id?: string;
  trainee_name?: string;
  staff_role?: string;
  status?: string;
  required_count?: number;
  completed_count?: number;
  required_scenarios?: string[];
  completed_scenarios?: string[];
  needs_retry_scenarios?: string[];
  last_score?: number | null;
  average_score?: number | null;
  critical_miss_count?: number;
  review_hold_count?: number;
  live_shadowing_gate?: string;
};

type Receipt = {
  id?: string;
  session_id?: string;
  assignment_id?: string;
  trainee_name?: string;
  scenario_title?: string;
  overall?: number;
  critical_miss?: boolean;
  result?: string;
  manager_review_required?: boolean;
  review_status?: string;
  manager_review?: {
    decision?: string;
    reviewer?: string;
    notes?: string;
  } | null;
};

type CertificationPacket = {
  id?: string;
  packet_status?: string;
  assignment?: Assignment;
  readiness?: ReadinessRow;
  receipts?: Receipt[];
  next_actions?: Array<{ type?: string; scenario_id?: string; label?: string; severity?: string }>;
  gate_contract?: {
    minimum_live_shadowing_gate?: string;
    manager_review_can_override_score?: boolean;
    manager_review_can_hold_or_require_retry?: boolean;
  };
  boundary?: string;
};

type ProductLearningLoop = {
  status?: string;
  park_issue_ticket_count?: number;
  dynamic_park_issue_ticket_count?: number;
  training_gap_ticket_count?: number;
  learning_signal_count?: number;
  park_issue_tickets?: ProductLearningTicket[];
  training_gap_tickets?: ProductLearningTicket[];
  product_learning_signals?: Array<{
    id?: string;
    source?: string;
    pattern?: string;
    affected_scenarios?: string[];
    evidence_count?: number;
    recommendation?: string;
    proposed_change_type?: string;
    status?: string;
    requires_review?: boolean;
  }>;
  loop_contract?: {
    live_tickets_improve_training?: string;
    training_gaps_help_ops?: string;
    training_gaps_create_live_issues?: boolean;
    llm_guest_controls_score?: boolean;
    simulated_data_feeds_reward_model?: boolean;
  };
};

const dimensionLabels: Record<string, string> = {
  empathy: "Empathy",
  policy_correctness: "Policy",
  escalation_decision: "Escalation",
  clarity: "Clarity",
  safety_awareness: "Safety",
  de_escalation: "De-escalation",
  brand_tone: "Brand tone",
};

const difficultyClass: Record<string, string> = {
  medium: "border-cyan-300 bg-cyan-300 text-slate-950",
  high: "border-amber-300 bg-amber-300 text-slate-950",
  critical: "border-rose-300 bg-rose-300 text-slate-950",
};

const fallbackScenarios: Scenario[] = [
  {
    id: "lost_child_report",
    title: "Lost Child Report",
    category: "Safety",
    difficulty: "critical",
    guest_role: "panicked guardian",
    opening_message: "I cannot find my six-year-old. She was next to me near the carousel and now she is gone.",
    context: "A guardian reports a missing child. Staff must show empathy, collect key details, keep the guardian reachable, and escalate immediately to security/ops.",
    objectives: ["Reassure without minimizing", "Collect child description and last seen location", "Keep guardian at a meeting point", "Escalate to security immediately"],
  },
  {
    id: "heat_exhaustion_concern",
    title: "Heat Exhaustion Concern",
    category: "Safety",
    difficulty: "critical",
    guest_role: "concerned friend",
    opening_message: "My friend is dizzy and looks pale. We have been in the sun for an hour and she says she might faint.",
    context: "Possible heat exhaustion. Staff must prioritize safety, move to shade if safe, call first aid/medical, and avoid medical diagnosis.",
    objectives: ["Treat as urgent", "Call first aid or medical", "Move to shade/cooling if safe", "Avoid diagnosis or delay"],
  },
  {
    id: "safety_rule_refusal",
    title: "Guest Refusing Safety Rule",
    category: "Ride Safety",
    difficulty: "critical",
    guest_role: "defiant ride guest",
    opening_message: "I am not taking off my loose backpack strap. I have ridden like this before. Just start the ride.",
    context: "Guest refuses a ride safety rule. Staff must stay firm, explain safety requirement, avoid bargaining, and escalate to ride lead/security if refusal continues.",
    objectives: ["State rule clearly", "Do not start ride unless compliant", "Explain safety reason", "Escalate persistent refusal"],
  },
  {
    id: "angry_parent",
    title: "Angry Parent At Guest Services",
    category: "Guest Recovery",
    difficulty: "medium",
    guest_role: "angry parent",
    opening_message: "This is ridiculous. My kid has been crying for twenty minutes because your staff sent us to a closed ride.",
    context: "A parent is angry after a ride closure reroute failed. They want acknowledgement, a clear next step, and a supervisor if compensation is requested.",
    objectives: ["Acknowledge the impact", "Confirm what happened", "Offer a concrete next step", "Escalate refund or compensation decisions"],
  },
  {
    id: "ride_closure_complaint",
    title: "Ride Closure Complaint",
    category: "Ride Ops",
    difficulty: "medium",
    guest_role: "disappointed coaster fan",
    opening_message: "We paid for tickets mostly for Dragon Coaster, and now it is closed. Nobody told us before we waited.",
    context: "Guest complains about a closure. Staff should acknowledge, avoid unsafe reopen promises, explain available updates, and offer alternatives.",
    objectives: ["Acknowledge wait impact", "Avoid promising reopen time", "Offer live alternatives", "Direct refund/compensation to approved channel"],
  },
  {
    id: "accessibility_accommodation",
    title: "Accessibility Accommodation Request",
    category: "Accessibility",
    difficulty: "high",
    guest_role: "guest requesting mobility accommodation",
    opening_message: "My father cannot stand in this sun for the whole queue. We need help, but I do not want to explain his medical history in public.",
    context: "A party requests accessibility support. Staff must preserve dignity, avoid medical probing, explain available assistance, and escalate to accessibility/guest services.",
    objectives: ["Respect privacy", "Offer accessible route or waiting support", "Avoid asking for diagnosis", "Escalate to accessibility support"],
  },
  {
    id: "language_barrier",
    title: "Language Barrier At Entry",
    category: "Guest Support",
    difficulty: "medium",
    guest_role: "confused multilingual family",
    opening_message: "No English good. Ticket problem. Family inside? We do not understand where to go.",
    context: "A guest has a language barrier and possible party separation. Staff should simplify, use translation resources, confirm safety, and guide one step at a time.",
    objectives: ["Use simple language", "Offer translation support", "Confirm party status", "Give one clear next step"],
  },
  {
    id: "refund_request",
    title: "Refund Request",
    category: "Guest Recovery",
    difficulty: "medium",
    guest_role: "upset purchaser",
    opening_message: "I want a refund now. The ride was closed, the food line was terrible, and this day is not what we paid for.",
    context: "Guest requests refund. Staff should empathize, avoid unauthorized promises, gather context, and route to Guest Services or supervisor.",
    objectives: ["Acknowledge frustration", "Avoid promising refund", "Collect issue summary", "Escalate through approved channel"],
  },
  {
    id: "line_cutting_conflict",
    title: "Line-Cutting Conflict",
    category: "Crowd Conflict",
    difficulty: "high",
    guest_role: "angry guest in queue",
    opening_message: "Those people cut the entire line. If you do not do something, I am going to handle it myself.",
    context: "Queue conflict with possible escalation. Staff should acknowledge, separate tension, avoid blame, call lead/security if needed, and keep the queue moving safely.",
    objectives: ["Acknowledge concern", "Discourage confrontation", "Call lead/security if threat escalates", "Investigate without public blame"],
  },
  {
    id: "weather_evacuation_confusion",
    title: "Weather Evacuation Confusion",
    category: "Weather Response",
    difficulty: "high",
    guest_role: "confused family during storm hold",
    opening_message: "The alert says move to shelter, but everyone is walking different directions. We have a stroller and do not know where to go.",
    context: "Storm shelter movement. Staff should give calm clear route, preserve accessibility, avoid panic language, and direct to assigned shelter/lead.",
    objectives: ["Use calm evacuation language", "Give specific shelter route", "Preserve accessible/stroller route", "Escalate blocked-route or lightning risk"],
  },
];

function label(value?: string) {
  if (!value) return "--";
  return dimensionLabels[value] ?? value.replaceAll("_", " ");
}

function scoreClass(value?: number) {
  const score = Number(value ?? 0);
  if (score >= 80) return "text-emerald-200";
  if (score >= 60) return "text-amber-200";
  return "text-rose-200";
}

function verdictClass(value?: string) {
  if (value === "strong") return "border-emerald-300 bg-emerald-300 text-slate-950";
  if (value === "passing") return "border-teal-300 bg-teal-300 text-slate-950";
  if (value === "critical_miss") return "border-rose-300 bg-rose-300 text-slate-950";
  return "border-amber-300 bg-amber-300 text-slate-950";
}

function barWidth(value?: number) {
  return `${Math.max(0, Math.min(100, (Number(value ?? 0) / 5) * 100))}%`;
}

export function StaffTrainingPage() {
  const liveRoleplayRef = useRef<HTMLElement | null>(null);
  const [activeView, setActiveView] = useState<"roleplay" | "manager">("roleplay");
  const [managerLoaded, setManagerLoaded] = useState(false);
  const [scenarios, setScenarios] = useState<Scenario[]>(fallbackScenarios);
  const [selectedScenarioId, setSelectedScenarioId] = useState("lost_child_report");
  const [traineeName, setTraineeName] = useState("Seasonal staff trainee");
  const [useLlmGuest, setUseLlmGuest] = useState(true);
  const [useShadowEval, setUseShadowEval] = useState(false);
  const [session, setSession] = useState<TrainingSession | null>(null);
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [readiness, setReadiness] = useState<ReadinessRow[]>([]);
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [activePacket, setActivePacket] = useState<CertificationPacket | null>(null);
  const [productLearning, setProductLearning] = useState<ProductLearningLoop | null>(null);
  const [manualGapScenarioId, setManualGapScenarioId] = useState("lost_child_report");
  const [manualGapType, setManualGapType] = useState("escalation_decision");
  const [manualGapSeverity, setManualGapSeverity] = useState("coaching");
  const [manualGapEvidence, setManualGapEvidence] = useState("Manager observed repeated misses in the roleplay debrief.");
  const [newAssignmentName, setNewAssignmentName] = useState("New seasonal hire");
  const [newAssignmentRole, setNewAssignmentRole] = useState("guest_services");
  const [activeAssignmentId, setActiveAssignmentId] = useState("");
  const [employeeMessage, setEmployeeMessage] = useState("");
  const [lastTurnScore, setLastTurnScore] = useState<TurnScore | null>(null);
  const [lastShadowEval, setLastShadowEval] = useState<ShadowEvaluator | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isStartingSession, setIsStartingSession] = useState(false);
  const [isSendingTurn, setIsSendingTurn] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  const selectedScenario = useMemo(
    () => scenarios.find((scenario) => scenario.id === selectedScenarioId) ?? scenarios[0],
    [scenarios, selectedScenarioId],
  );
  const transcript = session?.transcript ?? [];
  const scorecard = session?.scorecard;
  const turnCoaching = lastTurnScore?.turn_coaching;
  const masteryTracker = session?.mastery_tracker;
  const objectives = session?.scenario?.objectives ?? selectedScenario?.objectives ?? [];
  const completedObjectives = new Set(session?.completed_objectives ?? []);
  const activeAssignment = assignments.find((assignment) => assignment.id === activeAssignmentId);
  const readinessByAssignment = useMemo(() => new Map(readiness.map((row) => [row.assignment_id, row])), [readiness]);

  async function loadScenarios() {
    const response = await fetchParkPulseApi("/api/park/staff-training/scenarios", {
      headers: { "x-parkpulse-role": "onsite_worker" },
      timeoutMs: 8000,
    });
    const payload = (await response.json()) as { scenarios?: Scenario[] };
    const nextScenarios = payload.scenarios ?? [];
    if (nextScenarios.length) setScenarios(nextScenarios);
    if (nextScenarios.length && !nextScenarios.some((scenario) => scenario.id === selectedScenarioId)) {
      setSelectedScenarioId(nextScenarios[0].id);
    }
  }

  async function loadAnalytics() {
    const response = await fetchParkPulseApi("/api/park/staff-training/analytics?limit=120", {
      headers: { "x-parkpulse-role": "ops_team" },
      timeoutMs: 8000,
    });
    setAnalytics((await response.json()) as Analytics);
  }

  async function loadProductLearningLoop() {
    const response = await fetchParkPulseApi("/api/park/product-learning/loop?limit=120", {
      headers: { "x-parkpulse-role": "ops_team" },
      timeoutMs: 8000,
    });
    setProductLearning((await response.json()) as ProductLearningLoop);
  }

  async function loadManagerWorkflow() {
    await loadProductLearningLoop();
    const [assignmentResponse, readinessResponse, receiptResponse] = await Promise.all([
      fetchParkPulseApi("/api/park/staff-training/assignments?limit=120", {
        headers: { "x-parkpulse-role": "ops_team" },
        timeoutMs: 8000,
      }),
      fetchParkPulseApi("/api/park/staff-training/readiness?limit=120", {
        headers: { "x-parkpulse-role": "ops_team" },
        timeoutMs: 8000,
      }),
      fetchParkPulseApi("/api/park/staff-training/receipts?limit=20", {
        headers: { "x-parkpulse-role": "ops_team" },
        timeoutMs: 8000,
      }),
    ]);
    const assignmentPayload = (await assignmentResponse.json()) as { assignments?: Assignment[] };
    const readinessPayload = (await readinessResponse.json()) as { readiness?: ReadinessRow[] };
    const receiptPayload = (await receiptResponse.json()) as { receipts?: Receipt[] };
    setAssignments(assignmentPayload.assignments ?? []);
    setReadiness(readinessPayload.readiness ?? []);
    setReceipts(receiptPayload.receipts ?? []);
  }

  async function createManualTrainingGapTicket() {
    setIsLoading(true);
    setError("");
    setStatus("");
    try {
      const response = await fetchParkPulseApi("/api/park/product-learning/training-gap-ticket", {
        method: "POST",
        headers: { "content-type": "application/json", "x-parkpulse-role": "ops_team" },
        body: JSON.stringify({
          scenarioId: manualGapScenarioId,
          gapType: manualGapType,
          severity: manualGapSeverity,
          evidence: {
            summary: manualGapEvidence,
            source: "manager_manual_entry",
          },
        }),
        timeoutMs: 8000,
      });
      const payload = (await response.json()) as ProductLearningTicketResult;
      if (payload.readiness_issues?.length) {
        setError(payload.readiness_issues.join(" "));
      } else {
        setStatus(`Training gap ticket created${payload.ticket?.id ? `: ${payload.ticket.id}` : "."}`);
      }
      await loadProductLearningLoop();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Unable to create training gap ticket.");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    loadScenarios()
      .catch((nextError: Error) => {
        if (!cancelled) setError(nextError.message);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (activeView !== "manager" || managerLoaded) return;
    let cancelled = false;
    setIsLoading(true);
    Promise.all([loadAnalytics(), loadManagerWorkflow()])
      .then(() => {
        if (!cancelled) setManagerLoaded(true);
      })
      .catch((nextError: Error) => {
        if (!cancelled) setError(nextError.message);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeView, managerLoaded]);

  async function startSession(scenarioId = selectedScenarioId, options?: { assignment?: Assignment; retryOfSessionId?: string }) {
    setIsStartingSession(true);
    setError("");
    setStatus("");
    setLastTurnScore(null);
    setLastShadowEval(null);
    try {
      const assignment = options?.assignment;
      const nextTraineeName = assignment?.trainee_name ?? traineeName;
      const response = await fetchParkPulseApi("/api/park/staff-training/sessions", {
        method: "POST",
        headers: { "content-type": "application/json", "x-parkpulse-role": "onsite_worker" },
        body: JSON.stringify({
          scenario_id: scenarioId,
          trainee_name: nextTraineeName,
          assignment_id: assignment?.id,
          retry_of_session_id: options?.retryOfSessionId,
          useLlmGuest: useLlmGuest,
        }),
        timeoutMs: 9000,
      });
      const payload = (await response.json()) as TrainingSession;
      setSession(payload);
      setSelectedScenarioId(payload.scenario?.id ?? scenarioId);
      setTraineeName(payload.trainee_name ?? nextTraineeName);
      setActiveAssignmentId(payload.assignment_id ?? assignment?.id ?? "");
      setStatus("Roleplay session active.");
      window.setTimeout(() => {
        liveRoleplayRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 0);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Unable to start roleplay.");
    } finally {
      setIsStartingSession(false);
    }
  }

  async function sendTurn(event: FormEvent) {
    event.preventDefault();
    const outbound = employeeMessage.trim();
    if (!session?.id || !outbound || session.status === "finished") return;
    setIsSendingTurn(true);
    setError("");
    setEmployeeMessage("");
    try {
      const response = await fetchParkPulseApi("/api/park/staff-training/turn", {
        method: "POST",
        headers: { "content-type": "application/json", "x-parkpulse-role": "onsite_worker" },
        body: JSON.stringify({ session_id: session.id, employee_message: outbound, useLlmGuest: useLlmGuest, useShadowEval: useShadowEval }),
        timeoutMs: useLlmGuest || useShadowEval ? 16000 : 8000,
      });
      const payload = (await response.json()) as { session?: TrainingSession; turn_score?: TurnScore; shadow_evaluator?: ShadowEvaluator; coaching_notes?: string[]; readiness_issues?: string[] };
      if (payload.session) setSession(payload.session);
      if (payload.turn_score) setLastTurnScore(payload.turn_score);
      setLastShadowEval(payload.shadow_evaluator ?? null);
      if (payload.readiness_issues?.length) setError(payload.readiness_issues.join(" "));
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Unable to score response.");
    } finally {
      setIsSendingTurn(false);
    }
  }

  async function finishSession() {
    if (!session?.id) return;
    setIsLoading(true);
    setError("");
    try {
      const response = await fetchParkPulseApi("/api/park/staff-training/finish", {
        method: "POST",
        headers: { "content-type": "application/json", "x-parkpulse-role": "onsite_worker" },
        body: JSON.stringify({ session_id: session.id }),
        timeoutMs: 8000,
      });
      const payload = (await response.json()) as { session?: TrainingSession; readiness_issues?: string[] };
      if (payload.session) setSession(payload.session);
      if (payload.readiness_issues?.length) setError(payload.readiness_issues.join(" "));
      await loadAnalytics();
      await loadManagerWorkflow();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Unable to finish session.");
    } finally {
      setIsLoading(false);
    }
  }

  async function createAssignment() {
    setIsLoading(true);
    setError("");
    setStatus("");
    try {
      const response = await fetchParkPulseApi("/api/park/staff-training/assignments", {
        method: "POST",
        headers: { "content-type": "application/json", "x-parkpulse-role": "ops_team" },
        body: JSON.stringify({ traineeName: newAssignmentName, staffRole: newAssignmentRole }),
        timeoutMs: 8000,
      });
      const payload = (await response.json()) as { assignment?: Assignment; readiness_issues?: string[] };
      if (payload.assignment?.id) {
        setActiveAssignmentId(payload.assignment.id);
        setTraineeName(payload.assignment.trainee_name ?? newAssignmentName);
        setSelectedScenarioId(payload.assignment.scenario_ids?.[0] ?? selectedScenarioId);
      }
      if (payload.readiness_issues?.length) setError(payload.readiness_issues.join(" "));
      await loadManagerWorkflow();
      setStatus("Training assignment created.");
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Unable to create assignment.");
    } finally {
      setIsLoading(false);
    }
  }

  async function seedDemoData() {
    setIsLoading(true);
    setError("");
    setStatus("");
    try {
      await fetchParkPulseApi("/api/park/staff-training/demo-seed", {
        method: "POST",
        headers: { "content-type": "application/json", "x-parkpulse-role": "ops_team" },
        body: JSON.stringify({}),
        timeoutMs: 8000,
      });
      await Promise.all([loadAnalytics(), loadManagerWorkflow()]);
      setStatus("Demo training assignments and receipts loaded.");
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Unable to seed demo training data.");
    } finally {
      setIsLoading(false);
    }
  }

  async function reviewReceipt(receipt: Receipt, decision: "approve_shadowing" | "require_retry" | "hold") {
    if (!receipt.session_id && !receipt.id) return;
    setIsLoading(true);
    setError("");
    setStatus("");
    try {
      const response = await fetchParkPulseApi("/api/park/staff-training/receipt-review", {
        method: "POST",
        headers: { "content-type": "application/json", "x-parkpulse-role": "ops_team" },
        body: JSON.stringify({
          sessionId: receipt.session_id,
          receiptId: receipt.id,
          decision,
          reviewer: "Training manager",
          notes: decision === "approve_shadowing" ? "Approved for the next shadowing step." : decision === "require_retry" ? "Retry required before shadowing." : "Held for manager follow-up.",
        }),
        timeoutMs: 8000,
      });
      const payload = (await response.json()) as { status?: string; readiness_issues?: string[] };
      if (payload.readiness_issues?.length) setError(payload.readiness_issues.join(" "));
      await Promise.all([loadAnalytics(), loadManagerWorkflow()]);
      if (receipt.assignment_id) await loadCertificationPacket(receipt.assignment_id);
      setStatus(payload.status === "recorded" ? "Manager review recorded." : "Manager review updated.");
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Unable to record manager review.");
    } finally {
      setIsLoading(false);
    }
  }

  async function loadCertificationPacket(assignmentId?: string) {
    const targetAssignmentId = assignmentId || activeAssignmentId;
    if (!targetAssignmentId) return;
    setError("");
    try {
      const response = await fetchParkPulseApi(`/api/park/staff-training/certification-packet?assignment_id=${encodeURIComponent(targetAssignmentId)}`, {
        headers: { "x-parkpulse-role": "ops_team" },
        timeoutMs: 8000,
      });
      const payload = (await response.json()) as CertificationPacket & { status?: string; readiness_issues?: string[] };
      if (payload.readiness_issues?.length) {
        setError(payload.readiness_issues.join(" "));
        return;
      }
      setActivePacket(payload);
      setActiveAssignmentId(targetAssignmentId);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Unable to load certification packet.");
    }
  }

  function startAssignmentRoleplay(assignment: Assignment) {
    const status = readinessByAssignment.get(assignment.id);
    const scenarioId = status?.needs_retry_scenarios?.[0] ?? assignment.scenario_ids?.find((id) => !(status?.completed_scenarios ?? []).includes(id)) ?? assignment.scenario_ids?.[0] ?? selectedScenarioId;
    setActiveAssignmentId(assignment.id ?? "");
    void startSession(scenarioId, { assignment });
  }

  return (
    <main className="min-h-screen bg-[#071014] px-4 py-5 font-sans text-slate-100 lg:px-8">
      <div className="mx-auto max-w-[1500px] space-y-5">
        <header className="rounded-lg border border-teal-400/30 bg-[#0d171b] p-5 shadow-xl shadow-teal-950/20">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-teal-300">ParkPulse Staff</div>
              <h1 className="mt-2 text-3xl font-black tracking-normal text-slate-50 lg:text-5xl">Roleplay Trainer</h1>
              <p className="mt-3 max-w-3xl text-sm leading-relaxed text-slate-400">
                Practice difficult guest interactions with optional LLM guest simulation, deterministic scoring, and manager-visible coaching signals.
              </p>
            </div>
            <nav className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => setActiveView("roleplay")}
                className={`rounded border px-3 py-2 text-xs font-black transition ${activeView === "roleplay" ? "border-teal-300 bg-teal-300 text-slate-950" : "border-slate-700 bg-slate-950 text-slate-200 hover:border-teal-300"}`}
              >
                Trainer
              </button>
              <button
                type="button"
                onClick={() => setActiveView("manager")}
                className={`rounded border px-3 py-2 text-xs font-black transition ${activeView === "manager" ? "border-amber-300 bg-amber-300 text-slate-950" : "border-slate-700 bg-slate-950 text-slate-200 hover:border-amber-300"}`}
              >
                Manager review
              </button>
              <a href="/" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-teal-300">Command</a>
              <a href="/human" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-teal-300">Human view</a>
            </nav>
          </div>
        </header>

        {(status || error) && (
          <section className="rounded-lg border border-slate-800 bg-[#0d171b] p-3">
            {status && <div className="text-sm font-bold text-teal-100">{status}</div>}
            {error && <div className="mt-1 text-sm font-bold text-amber-200">{error}</div>}
          </section>
        )}

        {activeView === "manager" && <section className="grid gap-4 rounded-lg border border-teal-400/20 bg-[#0d171b] p-4 xl:grid-cols-[360px_minmax(0,1fr)_360px]">
          <div>
            <div className="text-[10px] font-black uppercase tracking-widest text-teal-300">Manager assignments</div>
            <h2 className="mt-1 text-xl font-black text-slate-50">Seasonal onboarding queue</h2>
            <div className="mt-4 grid gap-2">
              <label className="text-[10px] font-black uppercase tracking-widest text-slate-500" htmlFor="assignment-name">Staff member</label>
              <input
                id="assignment-name"
                value={newAssignmentName}
                onChange={(event) => setNewAssignmentName(event.target.value)}
                className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm font-bold text-slate-100 outline-none focus:border-teal-300"
              />
              <label className="text-[10px] font-black uppercase tracking-widest text-slate-500" htmlFor="assignment-role">Role track</label>
              <select
                id="assignment-role"
                value={newAssignmentRole}
                onChange={(event) => setNewAssignmentRole(event.target.value)}
                className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm font-bold text-slate-100 outline-none focus:border-teal-300"
              >
                <option value="guest_services">Guest services</option>
                <option value="ride_ops">Ride ops</option>
                <option value="entry">Entry</option>
                <option value="security">Security</option>
                <option value="food">Food</option>
              </select>
              <div className="grid grid-cols-2 gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => void createAssignment()}
                  disabled={isLoading || !newAssignmentName.trim()}
                  className="rounded border border-teal-300 bg-teal-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-teal-200 disabled:opacity-50"
                >
                  Assign
                </button>
                <button
                  type="button"
                  onClick={() => void seedDemoData()}
                  disabled={isLoading}
                  className="rounded border border-amber-300 bg-amber-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-amber-200 disabled:opacity-50"
                >
                  Seed demo
                </button>
              </div>
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between gap-2">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">Readiness dashboard</div>
              <button type="button" onClick={() => void loadManagerWorkflow()} className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-[10px] font-black text-slate-300 hover:border-teal-300">Refresh</button>
            </div>
            <div className="mt-3 grid gap-2 md:grid-cols-2">
              {readiness.slice(0, 6).map((row) => (
                <div key={row.assignment_id} className={`rounded border p-3 ${row.status === "ready_for_shadowing" ? "border-emerald-300/40 bg-emerald-300/10" : row.status === "needs_coaching" ? "border-amber-300/40 bg-amber-300/10" : "border-slate-800 bg-slate-950"}`}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-black text-slate-100">{row.trainee_name}</div>
                      <div className="mt-1 text-xs font-bold text-slate-500">{label(row.staff_role)} / {row.completed_count ?? 0} of {row.required_count ?? 0}</div>
                    </div>
                    <div className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-[10px] font-black uppercase text-slate-300">{label(row.status)}</div>
                  </div>
                  <div className="mt-3 flex items-center justify-between gap-2 text-xs font-bold text-slate-400">
                    <span>Last {row.last_score ?? "--"}</span>
                    <span>{row.critical_miss_count ?? 0} misses</span>
                    <span>{label(row.live_shadowing_gate)}</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => void loadCertificationPacket(row.assignment_id)}
                    className="mt-3 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-200 transition hover:border-teal-300"
                  >
                    Open packet
                  </button>
                </div>
              ))}
              {!readiness.length && <div className="rounded border border-slate-800 bg-slate-950 p-3 text-sm font-bold text-slate-500">No staff assignments yet.</div>}
            </div>
          </div>

          <div>
            <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">Recent receipts</div>
            <div className="mt-3 space-y-2">
              {receipts.slice(0, 4).map((receipt) => (
                <div key={receipt.id} className="rounded border border-slate-800 bg-slate-950 p-3 text-xs">
                  <div className="flex items-start justify-between gap-2 font-black text-slate-100">
                    <span className="min-w-0 truncate">{receipt.trainee_name}</span>
                    <span className={scoreClass(receipt.overall)}>{receipt.overall ?? "--"}</span>
                  </div>
                  <div className="mt-1 truncate font-bold text-slate-500">{receipt.scenario_title}</div>
                  <div className="mt-2 flex flex-wrap items-center gap-2 font-bold text-slate-400">
                    <span>{label(receipt.result)}</span>
                    <span className="rounded border border-slate-700 bg-[#0d171b] px-2 py-1 text-[10px] uppercase">{label(receipt.review_status)}</span>
                  </div>
                  {receipt.manager_review?.notes && <div className="mt-2 rounded border border-slate-800 bg-[#0d171b] p-2 font-semibold text-slate-400">{receipt.manager_review.notes}</div>}
                  <div className="mt-2 grid grid-cols-3 gap-1">
                    <button
                      type="button"
                      onClick={() => void reviewReceipt(receipt, "approve_shadowing")}
                      disabled={isLoading || receipt.review_status === "approve_shadowing"}
                      className="rounded border border-emerald-300/50 bg-emerald-300/10 px-2 py-1 text-[10px] font-black text-emerald-100 transition hover:bg-emerald-300/20 disabled:opacity-40"
                    >
                      Approve
                    </button>
                    <button
                      type="button"
                      onClick={() => void reviewReceipt(receipt, "require_retry")}
                      disabled={isLoading || receipt.review_status === "require_retry"}
                      className="rounded border border-amber-300/50 bg-amber-300/10 px-2 py-1 text-[10px] font-black text-amber-100 transition hover:bg-amber-300/20 disabled:opacity-40"
                    >
                      Retry
                    </button>
                    <button
                      type="button"
                      onClick={() => void reviewReceipt(receipt, "hold")}
                      disabled={isLoading || receipt.review_status === "hold"}
                      className="rounded border border-slate-700 bg-[#0d171b] px-2 py-1 text-[10px] font-black text-slate-200 transition hover:border-slate-500 disabled:opacity-40"
                    >
                      Hold
                    </button>
                  </div>
                </div>
              ))}
              {!receipts.length && <div className="rounded border border-slate-800 bg-slate-950 p-3 text-sm font-bold text-slate-500">No manager receipts yet.</div>}
            </div>
          </div>

          <div className="rounded border border-teal-300/30 bg-slate-950 p-4 xl:col-span-3">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-teal-300">Product learning loop</div>
                <h3 className="mt-1 text-lg font-black text-slate-100">Dynamic park issues improve training. Training gaps improve ops guidance.</h3>
                <p className="mt-2 max-w-4xl text-sm font-semibold leading-relaxed text-slate-500">
                  Live issue tickets are generated from backend operational backlog signals. Staff roleplay gaps stay simulated and reviewed.
                </p>
              </div>
              <button
                type="button"
                onClick={() => void loadProductLearningLoop()}
                className="rounded border border-slate-700 bg-[#0d171b] px-3 py-2 text-[10px] font-black uppercase tracking-widest text-slate-200 transition hover:border-teal-300"
              >
                Refresh loop
              </button>
            </div>

            <div className="mt-4 grid gap-2 md:grid-cols-3">
              <div className="rounded border border-slate-800 bg-[#0d171b] p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Live issue tickets</div>
                <div className="mt-2 text-2xl font-black text-slate-50">{productLearning?.park_issue_ticket_count ?? 0}</div>
                <div className="mt-1 text-xs font-bold text-slate-500">{productLearning?.dynamic_park_issue_ticket_count ?? 0} generated from dynamic park backlog.</div>
              </div>
              <div className="rounded border border-slate-800 bg-[#0d171b] p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Training gap tickets</div>
                <div className="mt-2 text-2xl font-black text-slate-50">{productLearning?.training_gap_ticket_count ?? 0}</div>
                <div className="mt-1 text-xs font-bold text-slate-500">Roleplay evidence with no live ops authority.</div>
              </div>
              <div className="rounded border border-slate-800 bg-[#0d171b] p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Learning signals</div>
                <div className="mt-2 text-2xl font-black text-slate-50">{productLearning?.learning_signal_count ?? 0}</div>
                <div className="mt-1 text-xs font-bold text-slate-500">Reviewed candidates for prompts, scenarios, policy cards, and ops checklists.</div>
              </div>
            </div>

            <div className="mt-4 grid gap-3 lg:grid-cols-[1fr_1fr]">
              <div className="rounded border border-slate-800 bg-[#0d171b] p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-teal-300">Dynamic park live issues</div>
                <div className="mt-3 space-y-2">
                  {(productLearning?.park_issue_tickets ?? []).filter((ticket) => ticket.source === "dynamic_park").slice(0, 4).map((ticket) => (
                    <div key={ticket.id} className="rounded border border-slate-800 bg-slate-950 p-2 text-xs">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="truncate font-black text-slate-100">{label(ticket.issue_type)}</div>
                          <div className="mt-1 text-slate-500">{ticket.summary}</div>
                        </div>
                        <span className="shrink-0 rounded border border-rose-300/40 bg-rose-300/10 px-2 py-1 text-[10px] font-black text-rose-100">{label(ticket.severity)}</span>
                      </div>
                      <div className="mt-2 text-[10px] font-black uppercase tracking-widest text-slate-500">{ticket.id}</div>
                    </div>
                  ))}
                  {!(productLearning?.park_issue_tickets ?? []).some((ticket) => ticket.source === "dynamic_park") && (
                    <div className="rounded border border-dashed border-slate-700 bg-slate-950 p-3 text-sm font-bold text-slate-500">
                      No dynamic park backlog issue is currently above threshold.
                    </div>
                  )}
                </div>
              </div>

              <div className="rounded border border-slate-800 bg-[#0d171b] p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-amber-300">Create training gap ticket</div>
                <div className="mt-3 grid gap-2 md:grid-cols-2">
                  <label className="grid gap-1 text-[10px] font-black uppercase tracking-widest text-slate-500">
                    Scenario
                    <select value={manualGapScenarioId} onChange={(event) => setManualGapScenarioId(event.target.value)} className="rounded border border-slate-700 bg-slate-950 px-2 py-2 text-xs font-bold normal-case tracking-normal text-slate-100 outline-none focus:border-teal-300">
                      {scenarios.map((scenario) => <option key={scenario.id} value={scenario.id}>{scenario.title}</option>)}
                    </select>
                  </label>
                  <label className="grid gap-1 text-[10px] font-black uppercase tracking-widest text-slate-500">
                    Gap
                    <select value={manualGapType} onChange={(event) => setManualGapType(event.target.value)} className="rounded border border-slate-700 bg-slate-950 px-2 py-2 text-xs font-bold normal-case tracking-normal text-slate-100 outline-none focus:border-teal-300">
                      <option value="empathy">Empathy</option>
                      <option value="policy_correctness">Policy</option>
                      <option value="escalation_decision">Escalation</option>
                      <option value="clarity">Clarity</option>
                      <option value="safety_awareness">Safety</option>
                      <option value="de_escalation">De-escalation</option>
                      <option value="brand_tone">Brand tone</option>
                    </select>
                  </label>
                  <label className="grid gap-1 text-[10px] font-black uppercase tracking-widest text-slate-500 md:col-span-2">
                    Severity
                    <select value={manualGapSeverity} onChange={(event) => setManualGapSeverity(event.target.value)} className="rounded border border-slate-700 bg-slate-950 px-2 py-2 text-xs font-bold normal-case tracking-normal text-slate-100 outline-none focus:border-teal-300">
                      <option value="coaching">Coaching</option>
                      <option value="critical_training_gap">Critical training gap</option>
                    </select>
                  </label>
                </div>
                <label className="mt-2 grid gap-1 text-[10px] font-black uppercase tracking-widest text-slate-500">
                  Evidence
                  <textarea value={manualGapEvidence} onChange={(event) => setManualGapEvidence(event.target.value)} rows={3} className="resize-y rounded border border-slate-700 bg-slate-950 px-2 py-2 text-xs font-semibold normal-case tracking-normal text-slate-100 outline-none focus:border-teal-300" />
                </label>
                <button
                  type="button"
                  onClick={() => void createManualTrainingGapTicket()}
                  disabled={isLoading || !manualGapEvidence.trim()}
                  className="mt-3 w-full rounded border border-amber-300 bg-amber-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-amber-200 disabled:opacity-50"
                >
                  Create training gap
                </button>
              </div>
            </div>

            <div className="mt-4 grid gap-3 lg:grid-cols-[1fr_340px]">
              <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                {(productLearning?.product_learning_signals ?? []).slice(0, 6).map((signal) => (
                  <div key={signal.id ?? `${signal.source}-${signal.pattern}`} className="rounded border border-slate-800 bg-[#0d171b] p-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-black text-slate-100">{signal.pattern ?? "Learning signal"}</div>
                        <div className="mt-1 text-[10px] font-black uppercase tracking-widest text-slate-500">{label(signal.source)} / {label(signal.proposed_change_type)}</div>
                      </div>
                      {signal.requires_review && <span className="shrink-0 rounded border border-amber-300/50 bg-amber-300/10 px-2 py-1 text-[10px] font-black text-amber-100">Review</span>}
                    </div>
                    <div className="mt-3 text-xs font-semibold leading-relaxed text-slate-400">{signal.recommendation ?? "No recommendation recorded."}</div>
                    <div className="mt-3 flex flex-wrap gap-2 text-[10px] font-black uppercase tracking-widest text-slate-500">
                      <span>{signal.evidence_count ?? 0} evidence</span>
                      <span>{label(signal.status)}</span>
                    </div>
                  </div>
                ))}
                {!(productLearning?.product_learning_signals ?? []).length && (
                  <div className="rounded border border-dashed border-slate-700 bg-[#0d171b] p-4 text-sm font-bold text-slate-500 md:col-span-2 xl:col-span-3">
                    No product-learning signals yet. Finish failed roleplays or wait for dynamic park backlog issues to cross threshold.
                  </div>
                )}
              </div>
              <div className="rounded border border-slate-800 bg-[#0d171b] p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Loop contract</div>
                <div className="mt-3 space-y-2 text-xs font-semibold leading-relaxed text-slate-400">
                  <div>Live tickets to training: {productLearning?.loop_contract?.live_tickets_improve_training ?? "reviewed signal only"}</div>
                  <div>Training gaps to ops: {productLearning?.loop_contract?.training_gaps_help_ops ?? "reviewed guidance only"}</div>
                  <div>Training gaps create live issues: {productLearning?.loop_contract?.training_gaps_create_live_issues ? "yes" : "no"}</div>
                  <div>LLM guest controls score: {productLearning?.loop_contract?.llm_guest_controls_score ? "yes" : "no"}</div>
                  <div>Simulated data feeds reward model: {productLearning?.loop_contract?.simulated_data_feeds_reward_model ? "yes" : "no"}</div>
                </div>
              </div>
            </div>
          </div>

          <div className="rounded border border-slate-800 bg-slate-950 p-4 xl:col-span-3">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-teal-300">Certification packet</div>
                <h3 className="mt-1 text-lg font-black text-slate-100">{activePacket?.assignment?.trainee_name ?? "Select a readiness row"}</h3>
                <p className="mt-2 max-w-3xl text-sm font-semibold leading-relaxed text-slate-500">
                  {activePacket?.boundary ?? "Packets summarize assignment readiness, receipts, and manager review decisions for shadowing signoff."}
                </p>
              </div>
              <div className="rounded border border-slate-800 bg-[#0d171b] px-3 py-2 text-xs font-black uppercase tracking-widest text-slate-300">
                {label(activePacket?.packet_status)}
              </div>
            </div>
            {activePacket ? (
              <div className="mt-4 grid gap-3 lg:grid-cols-[0.8fr_1.2fr_1fr]">
                <div className="rounded border border-slate-800 bg-[#0d171b] p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Gate</div>
                  <div className="mt-2 text-sm font-black text-slate-100">{label(activePacket.readiness?.status)}</div>
                  <div className="mt-2 text-xs font-bold text-slate-500">
                    {activePacket.readiness?.completed_count ?? 0} of {activePacket.readiness?.required_count ?? 0} scenarios / {activePacket.readiness?.review_hold_count ?? 0} review holds
                  </div>
                  <div className="mt-3 rounded border border-slate-800 bg-slate-950 p-2 text-xs font-semibold leading-relaxed text-slate-400">
                    Manager overrides score: {activePacket.gate_contract?.manager_review_can_override_score ? "yes" : "no"}
                  </div>
                </div>
                <div className="rounded border border-slate-800 bg-[#0d171b] p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Next actions</div>
                  <div className="mt-2 space-y-2">
                    {(activePacket.next_actions ?? []).map((action) => (
                      <div key={`${action.type}-${action.scenario_id}-${action.label}`} className="rounded border border-slate-800 bg-slate-950 p-2 text-sm font-semibold text-slate-300">
                        {action.label}
                      </div>
                    ))}
                  </div>
                </div>
                <div className="rounded border border-slate-800 bg-[#0d171b] p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Receipts</div>
                  <div className="mt-2 space-y-2">
                    {(activePacket.receipts ?? []).slice(-4).map((receipt) => (
                      <div key={receipt.id} className="rounded border border-slate-800 bg-slate-950 p-2 text-xs">
                        <div className="flex justify-between gap-2 font-black text-slate-100">
                          <span className="truncate">{receipt.scenario_title}</span>
                          <span className={scoreClass(receipt.overall)}>{receipt.overall ?? "--"}</span>
                        </div>
                        <div className="mt-1 font-bold text-slate-500">{label(receipt.review_status)}</div>
                      </div>
                    ))}
                    {!activePacket.receipts?.length && <div className="rounded border border-slate-800 bg-slate-950 p-2 text-xs font-bold text-slate-500">No receipts yet.</div>}
                  </div>
                </div>
              </div>
            ) : (
              <div className="mt-4 rounded border border-dashed border-slate-700 bg-[#0d171b] p-4 text-sm font-bold text-slate-500">
                Open a trainee packet from the readiness dashboard.
              </div>
            )}
          </div>
        </section>}

        {activeView === "roleplay" && <section className="grid gap-5 xl:grid-cols-[300px_minmax(0,1fr)_340px]">
          <div className="rounded-lg border border-teal-300/40 bg-[#0d171b] p-4 xl:col-span-3">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-teal-300">Training workspace</div>
                <h2 className="mt-1 text-2xl font-black text-slate-50">{session?.scenario?.title ?? selectedScenario?.title ?? "Lost Child Report"}</h2>
                <p className="mt-2 max-w-4xl text-sm font-semibold leading-relaxed text-slate-400">
                  {session?.id ? "Roleplay is active. Read the guest message, answer in the employee response box, then use the coaching feedback to improve the next turn." : selectedScenario?.context}
                </p>
              </div>
              <div className="grid gap-2 sm:grid-cols-[220px_180px_180px]">
                <input
                  value={traineeName}
                  onChange={(event) => setTraineeName(event.target.value)}
                  className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm font-bold text-slate-100 outline-none focus:border-teal-300"
                  aria-label="Trainee name"
                />
                <label className="flex min-h-10 items-center gap-2 rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200">
                  <input type="checkbox" checked={useLlmGuest} onChange={(event) => setUseLlmGuest(event.target.checked)} />
                  Vertex AI guest
                </label>
                <label className="flex min-h-10 items-center gap-2 rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200">
                  <input type="checkbox" checked={useShadowEval} onChange={(event) => setUseShadowEval(event.target.checked)} />
                  Shadow evaluator
                </label>
                <button
                  type="button"
                  onClick={() => void startSession()}
                  disabled={!selectedScenario || isStartingSession}
                  className="rounded border border-teal-300 bg-teal-300 px-4 py-2 text-sm font-black text-slate-950 transition hover:bg-teal-200 disabled:cursor-not-allowed disabled:opacity-50 sm:col-span-3"
                >
                  {isStartingSession ? "Starting..." : session?.id && session.status !== "finished" ? "Restart roleplay" : "Start roleplay"}
                </button>
              </div>
            </div>
          </div>
          <aside className="space-y-4">
            <div className="rounded-lg border border-slate-800 bg-[#0d171b] p-4">
              <div className="text-[10px] font-black uppercase tracking-widest text-teal-300">Scenario queue</div>
              <div className="mt-3 space-y-2">
                {scenarios.map((scenario) => (
                  <button
                    key={scenario.id}
                    type="button"
                    onClick={() => {
                      setSelectedScenarioId(scenario.id);
                      setLastTurnScore(null);
                      setLastShadowEval(null);
                    }}
                    className={`w-full rounded border p-3 text-left transition ${
                      selectedScenarioId === scenario.id ? "border-teal-300 bg-teal-300/10" : "border-slate-800 bg-slate-950 hover:border-teal-400"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="min-w-0 truncate text-sm font-black text-slate-100">{scenario.title}</span>
                      <span className={`shrink-0 rounded border px-2 py-1 text-[10px] font-black ${difficultyClass[scenario.difficulty] ?? "border-slate-600 bg-slate-700 text-slate-100"}`}>
                        {scenario.difficulty}
                      </span>
                    </div>
                    <div className="mt-1 text-xs font-bold text-slate-500">{scenario.category} / {scenario.guest_role}</div>
                  </button>
                ))}
                {!scenarios.length && <div className="rounded border border-slate-800 bg-slate-950 p-3 text-sm font-bold text-slate-500">{isLoading ? "Loading scenarios..." : "No scenarios loaded."}</div>}
              </div>
            </div>

            <div className="hidden rounded-lg border border-slate-800 bg-[#0d171b] p-4" style={{ display: "none" }}>
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">Assignment launcher</div>
              <div className="mt-3 space-y-2">
                {assignments.slice(-6).reverse().map((assignment) => {
                  const row = readinessByAssignment.get(assignment.id);
                  return (
                    <button
                      key={assignment.id}
                      type="button"
                      onClick={() => startAssignmentRoleplay(assignment)}
                      className={`w-full rounded border p-3 text-left transition ${activeAssignmentId === assignment.id ? "border-teal-300 bg-teal-300/10" : "border-slate-800 bg-slate-950 hover:border-teal-300"}`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="min-w-0 truncate text-sm font-black text-slate-100">{assignment.trainee_name}</span>
                        <span className="shrink-0 rounded border border-slate-700 bg-[#0d171b] px-2 py-1 text-[10px] font-black uppercase text-slate-300">{label(row?.status ?? assignment.status)}</span>
                      </div>
                      <div className="mt-1 text-xs font-bold text-slate-500">{label(assignment.staff_role)} / {row?.completed_count ?? assignment.completed_count ?? 0} of {row?.required_count ?? assignment.required_count ?? assignment.scenario_ids?.length ?? 0}</div>
                    </button>
                  );
                })}
                {!assignments.length && <div className="rounded border border-slate-800 bg-slate-950 p-3 text-sm font-bold text-slate-500">Create or seed assignments first.</div>}
              </div>
            </div>

          </aside>

          <section ref={liveRoleplayRef} className="rounded-lg border border-slate-800 bg-[#0d171b] p-4">
            <div className="flex flex-col gap-3 border-b border-slate-800 pb-4 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-teal-300">Live roleplay</div>
                <h2 className="mt-1 text-2xl font-black text-slate-50">{session?.scenario?.title ?? selectedScenario?.title ?? "Select a scenario"}</h2>
                <p className="mt-2 max-w-3xl text-sm font-semibold leading-relaxed text-slate-400">{session?.scenario?.context ?? selectedScenario?.context ?? "Start a session to open the transcript."}</p>
                {session?.id && session.status !== "finished" && (
                  <div className="mt-3 rounded border border-teal-300/40 bg-teal-300/10 px-3 py-2 text-sm font-black text-teal-100">
                    Session active. Read the guest message below, then reply as the employee.
                  </div>
                )}
              </div>
              <div className="flex flex-wrap gap-2">
                <span className={`rounded border px-2 py-1 text-[10px] font-black uppercase tracking-widest ${session?.status === "active" ? "border-teal-300 bg-teal-300 text-slate-950" : "border-slate-700 bg-slate-950 text-slate-300"}`}>
                  {session?.status ?? "not started"}
                </span>
                {session?.critical_miss && <span className="rounded border border-rose-300 bg-rose-300 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-950">critical miss</span>}
              </div>
            </div>

            <div className="mt-4 grid gap-4 2xl:grid-cols-[1fr_240px]">
              <div className="min-h-[430px] space-y-3 rounded border border-slate-800 bg-slate-950 p-3">
                {transcript.length ? (
                  transcript.map((turn, index) => (
                    <div key={`${index}-${turn.speaker}`} className={`flex ${turn.speaker === "employee" ? "justify-end" : "justify-start"}`}>
                      <div className={`max-w-[92%] rounded-lg border px-3 py-2 sm:max-w-[82%] ${turn.speaker === "employee" ? "border-teal-300/40 bg-teal-300/10 text-teal-50" : "border-slate-700 bg-[#111b20] text-slate-100"}`}>
                        <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">
                          {turn.speaker === "employee" ? "Employee" : `Guest${turn.source === "llm_guest" ? " / LLM" : ""}`}
                        </div>
                        <div className="mt-1 text-sm font-semibold leading-relaxed">{turn.message}</div>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="flex h-full min-h-[360px] items-center justify-center rounded border border-dashed border-slate-700 text-center text-sm font-bold text-slate-500">
                    {session?.id ? "Loading the guest opening message..." : "Select a scenario to open the roleplay transcript."}
                  </div>
                )}
              </div>

              <div className="space-y-3">
                <div className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">Objectives</div>
                  <div className="mt-3 space-y-2">
                    {objectives.map((objective) => (
                      <div key={objective} className={`rounded border px-2 py-2 text-xs font-bold ${completedObjectives.has(objective) ? "border-emerald-300 bg-emerald-300/10 text-emerald-100" : "border-slate-800 bg-[#0d171b] text-slate-400"}`}>
                        {objective}
                      </div>
                    ))}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => void finishSession()}
                  disabled={!session?.id || session.status === "finished"}
                  className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm font-black text-slate-200 transition hover:border-teal-300 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Finish and debrief
                </button>
              </div>
            </div>

            <form onSubmit={sendTurn} className="mt-4 rounded border border-slate-800 bg-slate-950 p-3">
              <label className="text-[10px] font-black uppercase tracking-widest text-teal-300" htmlFor="staff-training-employee-response">
                Employee response
              </label>
              <div className="mt-2 flex flex-col gap-3 xl:flex-row xl:items-end">
                <textarea
                  id="staff-training-employee-response"
                  value={employeeMessage}
                  onChange={(event) => setEmployeeMessage(event.target.value)}
                  disabled={!session?.id || session.status === "finished"}
                  placeholder={session?.id ? "Type what the employee would say to the guest..." : "Start a roleplay to unlock the response box."}
                  rows={4}
                  className="min-h-[104px] flex-1 resize-y rounded border border-slate-700 bg-[#0d171b] px-3 py-2 text-sm font-semibold leading-relaxed text-slate-100 outline-none transition placeholder:text-slate-600 focus:border-teal-300 disabled:cursor-not-allowed disabled:opacity-50"
                />
                <button
                  type="submit"
                  disabled={!session?.id || !employeeMessage.trim() || session.status === "finished" || isSendingTurn}
                  className="min-h-11 rounded border border-teal-300 bg-teal-300 px-4 py-2 text-sm font-black text-slate-950 transition hover:bg-teal-200 disabled:cursor-not-allowed disabled:opacity-50 xl:w-44"
                >
                  {isSendingTurn ? "Scoring..." : "Send reply"}
                </button>
              </div>
            </form>

            <div className="mt-4 rounded border border-slate-800 bg-slate-950 p-4">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <div className="text-[10px] font-black uppercase tracking-widest text-teal-300">Turn coaching</div>
                  <div className="mt-2 text-xl font-black text-slate-50">
                    {turnCoaching?.headline ?? "Awaiting employee response."}
                  </div>
                  <div className="mt-2 text-sm font-semibold leading-relaxed text-slate-400">
                    {turnCoaching?.priority ?? "Start the exchange, then respond to the guest's first message."}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <div className={`text-4xl font-black ${scoreClass(lastTurnScore?.overall)}`}>{lastTurnScore?.overall ?? "--"}</div>
                  <div className={`rounded border px-2 py-1 text-[10px] font-black uppercase tracking-widest ${verdictClass(turnCoaching?.verdict)}`}>
                    {turnCoaching?.verdict?.replaceAll("_", " ") ?? "not scored"}
                  </div>
                </div>
              </div>

              <div className="mt-4 grid gap-3 xl:grid-cols-2">
                <div className="rounded border border-slate-800 bg-[#0d171b] p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-emerald-300">What worked</div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {(turnCoaching?.strengths?.length ? turnCoaching.strengths : ["No scored turn yet"]).map((item) => (
                      <span key={item} className="rounded border border-emerald-300/30 bg-emerald-300/10 px-2 py-1 text-xs font-black text-emerald-100">
                        {item}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="rounded border border-slate-800 bg-[#0d171b] p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-amber-300">Fix now</div>
                  <div className="mt-3 space-y-2">
                    {(turnCoaching?.misses?.length ? turnCoaching.misses : [{ label: "No misses to review yet." }]).map((item) => (
                      <div key={item.label} className="rounded border border-amber-300/25 bg-amber-300/10 p-2 text-sm font-semibold leading-relaxed text-amber-100">
                        {item.label}
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {turnCoaching?.next_response && (
                <div className="mt-3 rounded border border-teal-300/30 bg-teal-300/10 p-3">
                  <div className="text-[10px] font-black uppercase tracking-widest text-teal-300">Say next</div>
                  <div className="mt-2 text-sm font-semibold leading-relaxed text-teal-50">{turnCoaching.next_response}</div>
                </div>
              )}
            </div>

            <div className="mt-4 grid gap-4 xl:grid-cols-2">
              <div className="rounded border border-slate-800 bg-slate-950 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-[10px] font-black uppercase tracking-widest text-emerald-300">Mastery tracker</div>
                    <div className="mt-2 text-lg font-black text-slate-50">{masteryTracker?.mastery_level?.replaceAll("_", " ") ?? "not started"}</div>
                    <p className="mt-2 text-sm font-semibold leading-relaxed text-slate-400">{masteryTracker?.summary ?? "Repair tracking appears after scored turns."}</p>
                  </div>
                  <div className="rounded border border-slate-700 bg-[#0d171b] px-2 py-1 text-xs font-black text-slate-300">
                    {masteryTracker?.repair_count ?? 0} repairs
                  </div>
                </div>
                <div className="mt-3 grid gap-3 lg:grid-cols-2">
                  <div>
                    <div className="text-[10px] font-black uppercase tracking-widest text-amber-300">Open gaps</div>
                    <div className="mt-2 space-y-2">
                      {(masteryTracker?.open_gaps?.length ? masteryTracker.open_gaps : [{ label: "No open gaps." }]).slice(0, 4).map((item) => (
                        <div key={item.key ?? item.label} className="rounded border border-slate-800 bg-[#0d171b] p-2 text-xs font-bold leading-relaxed text-slate-300">
                          {item.label}
                        </div>
                      ))}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] font-black uppercase tracking-widest text-emerald-300">Latest repairs</div>
                    <div className="mt-2 space-y-2">
                      {(masteryTracker?.latest_repairs?.length ? masteryTracker.latest_repairs : [{ label: "No repaired gaps yet." }]).slice(0, 4).map((item) => (
                        <div key={item.key ?? item.label} className="rounded border border-emerald-300/20 bg-emerald-300/10 p-2 text-xs font-bold leading-relaxed text-emerald-100">
                          {item.label}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              <div className="rounded border border-slate-800 bg-slate-950 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-[10px] font-black uppercase tracking-widest text-sky-300">Shadow evaluator</div>
                    <div className="mt-2 text-lg font-black text-slate-50">{lastShadowEval?.alignment?.replaceAll("_", " ") ?? "not requested"}</div>
                    <p className="mt-2 text-sm font-semibold leading-relaxed text-slate-400">{lastShadowEval?.summary ?? "Enable Shadow evaluator before sending a reply to get a second-pass rubric comment."}</p>
                  </div>
                  <div className="rounded border border-slate-700 bg-[#0d171b] px-2 py-1 text-xs font-black text-slate-300">
                    {lastShadowEval?.score_authority === false ? "no score authority" : "--"}
                  </div>
                </div>
                <div className="mt-3 space-y-2">
                  {(lastShadowEval?.coaching_focus?.length ? lastShadowEval.coaching_focus : ["No shadow notes yet."]).map((item) => (
                    <div key={item} className="rounded border border-slate-800 bg-[#0d171b] p-2 text-xs font-bold leading-relaxed text-slate-300">
                      {item}
                    </div>
                  ))}
                </div>
                {lastShadowEval?.rubric_disagreement && (
                  <div className="mt-3 rounded border border-sky-300/25 bg-sky-300/10 p-2 text-xs font-bold leading-relaxed text-sky-100">
                    {lastShadowEval.rubric_disagreement}
                  </div>
                )}
              </div>
            </div>
          </section>

          <aside className="space-y-4">
            <div className="hidden rounded-lg border border-slate-800 bg-[#0d171b] p-4" style={{ display: "none" }}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-[10px] font-black uppercase tracking-widest text-teal-300">Scorecard</div>
                  <div className={`mt-1 text-4xl font-black ${scoreClass(scorecard?.overall)}`}>{scorecard?.overall ?? 0}</div>
                </div>
                <div className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs font-black text-slate-300">{scorecard?.turn_count ?? 0} turns</div>
              </div>
              <div className="mt-4 space-y-3">
                {Object.entries(scorecard?.dimensions ?? {}).map(([dimension, value]) => (
                  <div key={dimension}>
                    <div className="flex items-center justify-between gap-2 text-xs font-bold">
                      <span className="text-slate-300">{label(dimension)}</span>
                      <span className="text-slate-500">{value}/5</span>
                    </div>
                    <div className="mt-1 h-2 overflow-hidden rounded bg-slate-900">
                      <div className="h-full rounded bg-teal-300" style={{ width: barWidth(value) }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-lg border border-slate-800 bg-[#0d171b] p-4">
              <div className="text-[10px] font-black uppercase tracking-widest text-amber-300">Weakest scoring signals</div>
              <div className="mt-3 space-y-2">
                {(turnCoaching?.weak_dimensions?.length ? turnCoaching.weak_dimensions : []).map((item) => (
                  <div key={item.dimension ?? item.label} className="rounded border border-slate-800 bg-slate-950 p-2">
                    <div className="flex items-center justify-between gap-2 text-xs font-bold">
                      <span className="text-slate-300">{item.label ?? label(item.dimension)}</span>
                      <span className="text-slate-500">{item.score}/5</span>
                    </div>
                    <div className="mt-1 h-2 overflow-hidden rounded bg-slate-900">
                      <div className="h-full rounded bg-amber-300" style={{ width: barWidth(item.score) }} />
                    </div>
                  </div>
                ))}
                {!turnCoaching?.weak_dimensions?.length && (
                  <div className="rounded border border-slate-800 bg-slate-950 p-2 text-sm font-semibold leading-relaxed text-slate-400">
                    Weak signals appear after the first scored response.
                  </div>
                )}
              </div>
            </div>

            <div className="rounded-lg border border-slate-800 bg-[#0d171b] p-4">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">Guest simulator</div>
              <div className="mt-3 grid grid-cols-2 gap-2 text-xs font-bold text-slate-300">
                <div className="rounded border border-slate-800 bg-slate-950 p-2">Mode: {session?.guest_simulator?.mode?.replaceAll("_", " ") ?? "--"}</div>
                <div className="rounded border border-slate-800 bg-slate-950 p-2">Source: {session?.guest_simulator?.source ?? "--"}</div>
                <div className="rounded border border-slate-800 bg-slate-950 p-2">LLM: {session?.guest_simulator?.llm_status ?? "--"}</div>
                <div className="rounded border border-slate-800 bg-slate-950 p-2">Scores: {session?.guest_simulator?.llm_controls_score === false ? "deterministic" : "--"}</div>
              </div>
            </div>

            {session?.debrief && (
              <div className="rounded-lg border border-slate-800 bg-[#0d171b] p-4">
                <div className="text-[10px] font-black uppercase tracking-widest text-emerald-300">Debrief</div>
                <div className={`mt-2 text-2xl font-black ${session.debrief.result === "pass" ? "text-emerald-200" : "text-amber-200"}`}>{session.debrief.result?.replaceAll("_", " ")}</div>
                <p className="mt-2 text-sm font-semibold leading-relaxed text-slate-300">{session.debrief.summary}</p>
                {session.training_gap_ticket && (
                  <div className="mt-3 rounded border border-slate-800 bg-slate-950 p-3 text-xs font-semibold leading-relaxed text-slate-400">
                    <div className="text-[10px] font-black uppercase tracking-widest text-amber-300">Training gap ticket</div>
                    <div className="mt-1 text-slate-200">{session.training_gap_ticket.status === "created" ? session.training_gap_ticket.ticket?.id : label(session.training_gap_ticket.status)}</div>
                    <div className="mt-1">{session.training_gap_ticket.ticket?.boundary ?? "Passed sessions without open gaps do not create training tickets."}</div>
                  </div>
                )}
                {session.debrief.recommended_retry && (
                  <button
                    type="button"
                    onClick={() => void startSession(session.debrief?.recommended_retry ?? selectedScenarioId, { assignment: activeAssignment, retryOfSessionId: session.id })}
                    className="mt-3 w-full rounded border border-amber-300 bg-amber-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-amber-200"
                  >
                    Retry scenario
                  </button>
                )}
              </div>
            )}

          </aside>
        </section>}
      </div>
    </main>
  );
}
