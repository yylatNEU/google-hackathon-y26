"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getApiUrls } from "@/lib/api";

type MonitorData = {
  monitoring_id?: string;
  created_at?: string;
  mode?: string;
  status?: string;
  overall_status?: string;
  summary?: {
    action_count?: number;
    review_count?: number;
    blocked_count?: number;
    policy_book_count?: number;
    gcp_trace_eval_ready?: boolean;
    arize_ready?: boolean;
    overall_eval_score?: number;
    needs_human_approval?: boolean;
  };
  gcp_trace_eval?: {
    status?: string;
    project?: string;
    dataset?: string;
    trace_lookup_query?: string;
    trace_url?: string;
    dimensions?: string[];
  };
  arize_monitor?: {
    status?: string;
    project_name?: string;
    trace_lookup_query?: string;
    trace_url?: string;
    dimensions?: string[];
  };
  policy_index?: {
    policy_book_id?: string;
    version?: string;
    active_policy_books?: string[];
    absolute_prohibitions?: string[];
  };
  policy_integrity?: {
    status?: string;
    issues?: string[];
    policy_ref_count?: number;
  };
  runtime_governance?: {
    decision_ledger?: Array<{
      id?: string;
      createdAt?: string;
      title?: string;
      gateStatus?: string;
      policyFindings?: string[];
    }>;
    remediation_tasks?: Array<{
      id?: string;
      status?: string;
      severity?: string;
      owner?: string;
      title?: string;
      requiredAction?: string;
      policyFindings?: string[];
    }>;
    customer_care_cases?: Array<{
      id?: string;
      status?: string;
      severity?: string;
      reason?: string;
      safeAudience?: string;
      policyFindings?: string[];
    }>;
  };
  supervised_actions?: Array<{
    action_id?: string;
    title?: string;
    owner?: string;
    policy_status?: string;
    park_action?: { target?: string; action?: string };
  }>;
  deep_monitoring?: { status?: string; error?: string };
};

type CaseRow = {
  id?: string;
  title?: string;
  domain?: string;
  severity?: string;
  quality?: { status?: string; score?: number };
  priority?: { rank?: number; score?: number; rationale?: string };
  governance?: {
    allowedSurface?: string;
    blockerClasses?: string[];
    nextOwnerAction?: string;
  };
  productionEvidence?: {
    state?: string;
    feedCount?: number;
    packetHash?: string;
  };
};

type CaseIndex = {
  status?: string;
  summary?: { caseCount?: number; productionReady?: boolean };
  rows?: CaseRow[];
};

type AgentOpsItem = {
  id?: string;
  caseId?: string;
  case_id?: string;
  timestamp?: string;
  status?: string;
  mode?: string;
  source?: string;
  scenarioName?: string;
  summary?: string;
  selectedAction?: string;
  gate?: string;
  evalScore?: number | null;
  evalDimensions?: Array<{ label?: string; score?: number; detail?: string }>;
  failureReasons?: string[];
  retrievalTags?: string[];
  dispatchCount?: number;
  receiverActions?: string[];
  toolCalls?: Array<{ tool?: string; status?: string; agent?: string | null }>;
  traceEvents?: unknown[];
  traceId?: string | null;
  signature?: string;
  policyRefs?: string[];
  reviewSessionIds?: string[];
  outcomeEvidence?: {
    dispatchStatus?: string;
    receiverAckCount?: number;
    takeRatePct?: number | null;
    followThroughPct?: number | null;
    memoryId?: string | null;
  };
};

type AgentOpsLedger = {
  status?: string;
  count?: number;
  items?: AgentOpsItem[];
};

type ReviewLedger = {
  status?: string;
  mode?: string;
  summary?: {
    open_count?: number;
    closed_count?: number;
    training_candidate_count?: number;
  };
  rows?: Array<{
    id?: string;
    case_id?: string;
    caseId?: string;
    status?: string;
    priority?: string;
    owner?: string;
    reason?: string;
    training_effect?: string;
    event?: { source?: string; signal_type?: string };
    disposition?: { decision?: string };
  }>;
  open_reviews?: ReviewLedger["rows"];
  readiness_issues?: string[];
  authorization?: { reason?: string };
};

type MonitorEvidenceCase = {
  case_id?: string;
  caseId?: string;
  policy_case_id?: string;
  policy_refs?: string[];
  policy_ref_rows?: Array<PolicyRefRow & { detail?: PolicyRefDetail }>;
  receipt_ids?: string[];
  trace_ids?: string[];
  review_session_ids?: string[];
  trace_records?: Array<{
    receipt_id?: string;
    case_id?: string;
    policy_case_id?: string;
    policy_refs?: string[];
    receipt_policy_refs?: string[];
    case_policy_refs?: string[];
    policy_ref_rows?: PolicyRefRow[];
    policy_link_source?: string;
    trace_id?: string | null;
    trace_url?: string | null;
    signature?: string;
    relation_type?: string;
    relation_confidence?: string;
    hard_match?: boolean;
    relation_score?: number;
    case_link_source?: string;
    case_link_confidence?: number;
    eval_score?: number | null;
    gate?: string;
    tool_count?: number;
    summary?: string;
  }>;
  review_sessions?: Array<{
    review_session_id?: string;
    case_id?: string;
    status?: string;
    priority?: string;
    owner?: string;
    reason?: string;
    relation_type?: string;
    relation_confidence?: string;
    hard_match?: boolean;
    relation_score?: number;
  }>;
  eval_dimensions?: Array<{ id?: string; label?: string; score?: number; status?: string; detail?: string }>;
  outcome_evidence?: {
    status?: string;
    dispatch_count?: number;
    receiver_actions?: string[];
    latest?: AgentOpsItem["outcomeEvidence"];
  };
  relationship_contract?: {
    case_id?: string;
    trace_id_source?: string;
    review_session_id_source?: string;
    policy_ref_source?: string;
    explicit_receipt_links?: number;
    explicit_review_links?: number;
    inferred_receipt_links?: number;
    inferred_review_links?: number;
    semantic_threshold?: string;
  };
};

type MonitorEvidenceGraph = {
  status?: string;
  summary?: {
    receipt_count?: number;
    trace_record_count?: number;
    distinct_trace_id_count?: number;
    review_session_count?: number;
    linked_review_session_count?: number;
    policy_ref_count?: number;
    cases_with_trace_records?: number;
    cases_with_review_sessions?: number;
    cases_with_policy_refs?: number;
  };
  cases?: MonitorEvidenceCase[];
  source_status?: Record<string, string | undefined>;
  evidence_cache?: {
    key?: string;
    state?: string;
    age_seconds?: number;
    fresh_for_seconds?: number;
    refreshing?: boolean;
    mode?: string;
    snapshot_path?: string;
    source_current?: boolean;
    source_fingerprint?: string;
    current_source_fingerprint?: string;
  };
};

type PolicyDoctrine = {
  policy_book_count?: number;
  action_case_count?: number;
  action_primitive_count?: number;
  action_cases?: Array<{
    id?: string;
    title?: string;
    triggers?: string[];
    state_signals?: string[];
    policy_refs?: string[];
    recommended_primitives?: string[];
    action_plan?: string[];
    blocked_actions?: string[];
    success_metric?: string;
    rollback_condition?: string;
  }>;
  policy_refs?: Array<string | PolicyRefRow>;
};

type PolicyRefDetail = {
  status?: string;
  policy_ref?: string;
  matches?: Array<{
    kind?: string;
    policy_book_id?: string;
    title?: string;
    condition?: string;
    allowed_action?: string;
    blocked_action?: string;
    required_evidence?: string[];
    human_review_if?: string[];
    summary?: string;
  }>;
  related_cases?: Array<{
    id?: string;
    title?: string;
    triggers?: string[];
    blocked_actions?: string[];
    success_metric?: string;
    rollback_condition?: string;
  }>;
};

type ApiRequestInit = RequestInit & { timeoutMs?: number };
type PolicyRefRow = {
  policy_ref?: string;
  policy_book_id?: string;
  title?: string;
  summary?: string;
  severity?: string;
  condition?: string;
  allowed_action?: string;
  blocked_action?: string;
};
type TraceFilter = "all" | "direct" | "inferred" | "review" | "blocked";
type AuditAgentAnswer = {
  status?: string;
  mode?: string;
  llm_used?: boolean;
  conclusion: string;
  answer?: string;
  confidence: "high" | "medium" | "low";
  evidence: string[];
  memory_comparison?: string[];
  memoryComparison?: string[];
  policy_alignment?: string[];
  policyAlignment?: string[];
  confidence_basis?: string[];
  confidenceBasis?: string[];
  audit_gaps?: string[];
  auditGaps?: string[];
  uncertainty: string[];
  nextActions?: string[];
  next_actions?: string[];
  citations?: Array<{ label?: string; id?: string; kind?: string }>;
  scope: string;
  runtime?: { provider?: string; elapsed_ms?: number; readiness_issues?: string[] };
  audit_session?: {
    status?: string;
    primary?: string;
    connected?: boolean;
    mode?: string;
    session_id?: string;
    evidence_packet_hash?: string;
    user_message_id?: string;
    assistant_message_id?: string;
    reason?: string;
  };
};
type AuditAgentMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  answer?: AuditAgentAnswer;
  createdAt: number | string;
  evidencePacketHash?: string;
  sessionId?: string;
};
type StoredAuditConversation = {
  caseId: string;
  sessionId?: string;
  draft?: string;
  messages?: AuditAgentMessage[];
};
type AuditSessionResponse = {
  status?: string;
  session?: {
    session_id?: string;
    case_id?: string;
    selected_trace_id?: string;
    selected_receipt_id?: string;
    updated_at?: string;
  } | null;
  messages?: AuditAgentMessage[];
  persistence?: { primary?: string; connected?: boolean; mode?: string; reason?: string };
};
type TraceTicketCorpus = {
  status?: string;
  count?: number;
  ticket_count?: number;
  retrieval_method?: string;
  case_corpus?: {
    source?: string;
    case_count?: number;
    rich_evidence_case_count?: number;
    policy_only_case_count?: number;
  };
  analysis?: {
    byStatus?: Record<string, number>;
    withTraceCount?: number;
    withPolicyCount?: number;
    withReviewCount?: number;
    riskFlags?: Record<string, number>;
  };
  persistence?: {
    primary?: string;
    connected?: boolean;
    mode?: string;
    count?: number;
  };
};

const AUDIT_CONVERSATION_STORAGE_PREFIX = "parkpulse.monitor.auditConversation.v1";

function auditConversationStorageKey(caseId?: string) {
  return `${AUDIT_CONVERSATION_STORAGE_PREFIX}:${encodeURIComponent(caseId || "selected")}`;
}

function validAuditMessage(item: unknown): item is AuditAgentMessage {
  if (!item || typeof item !== "object") return false;
  const message = item as Partial<AuditAgentMessage>;
  return (message.role === "user" || message.role === "assistant" || message.role === "system") && typeof message.content === "string" && typeof message.id === "string";
}

function readStoredAuditConversation(caseId?: string): StoredAuditConversation | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(auditConversationStorageKey(caseId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredAuditConversation;
    if (parsed.caseId !== caseId || !Array.isArray(parsed.messages)) return null;
    const messages = parsed.messages.filter(validAuditMessage).slice(-20);
    return { caseId: parsed.caseId, sessionId: typeof parsed.sessionId === "string" ? parsed.sessionId : undefined, draft: typeof parsed.draft === "string" ? parsed.draft : undefined, messages };
  } catch {
    return null;
  }
}

function writeStoredAuditConversation(caseId: string | undefined, messages: AuditAgentMessage[], draft: string, sessionId?: string) {
  if (typeof window === "undefined" || !caseId) return;
  try {
    window.sessionStorage.setItem(
      auditConversationStorageKey(caseId),
      JSON.stringify({
        caseId,
        sessionId,
        draft,
        messages: messages.slice(-20),
      } satisfies StoredAuditConversation),
    );
  } catch {
    // Session storage is best-effort; the live conversation still works without it.
  }
}

function caseLoadedAuditMessage(caseId?: string, title?: string): AuditAgentMessage {
  return {
    id: `system-${caseId ?? "case"}-${Date.now()}`,
    role: "system",
    content: `Case context loaded: ${caseId ?? "unknown case"}${title ? `, ${title}` : ""}.`,
    createdAt: Date.now(),
  };
}

function fmt(value?: string | number | boolean | null) {
  if (value === undefined || value === null || value === "") return "--";
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value).replaceAll("_", " ");
}

function score(value?: number | null, max = 100) {
  if (typeof value !== "number") return "--";
  const normalized = max === 1 ? value * 100 : value;
  return `${Math.round(normalized)}/100`;
}

function compact(items?: Array<string | undefined>, limit = 3) {
  const values = (items ?? []).filter(Boolean) as string[];
  if (!values.length) return "--";
  return `${values.slice(0, limit).join(" / ")}${values.length > limit ? ` +${values.length - limit}` : ""}`;
}

function tokensFromText(value?: string | null) {
  return new Set(
    (value ?? "")
      .toLowerCase()
      .replace(/case|park|operations|pressure|during|while|near|with|unsafe|reported|creates|rising|before|after|down|the|and|or|is/g, " ")
      .split(/[^a-z0-9]+/)
      .map((item) => item.trim())
      .filter((item) => item.length >= 4),
  );
}

function sharedTokenCount(terms: Set<string>, value?: string | null) {
  if (!terms.size || !value) return 0;
  const haystack = tokensFromText(value);
  let count = 0;
  terms.forEach((term) => {
    if (haystack.has(term)) count += 1;
  });
  return count;
}

function receiptRelationScore(receipt: AgentOpsItem, terms: Set<string>) {
  return [
    receipt.summary,
    receipt.scenarioName,
    receipt.selectedAction,
    ...(receipt.receiverActions ?? []),
    ...(receipt.retrievalTags ?? []),
    ...(receipt.failureReasons ?? []),
  ].reduce((total, value) => total + sharedTokenCount(terms, value), 0);
}

function dedupeReceipts(items: AgentOpsItem[]) {
  const seen = new Set<string>();
  return items.filter((item) => {
    const key = [
      item.summary,
      item.mode,
      item.gate,
      item.evalScore,
      item.dispatchCount,
      item.receiverActions?.join("|"),
      item.toolCalls?.map((call) => call.tool).join("|"),
    ].join("::");
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function toneClass(value?: string) {
  const lower = (value ?? "").toLowerCase();
  if (lower.includes("block") || lower.includes("critical") || lower.includes("fail")) return "border-red-400/40 bg-red-950/25 text-red-100";
  if (lower.includes("review") || lower.includes("degraded") || lower.includes("hold") || lower.includes("warning")) return "border-amber-400/40 bg-amber-950/20 text-amber-100";
  if (lower.includes("ready") || lower.includes("clear") || lower.includes("ok") || lower.includes("complete")) return "border-emerald-400/35 bg-emerald-950/20 text-emerald-100";
  return "border-slate-700 bg-slate-950 text-slate-300";
}

function StatusPill({ value }: { value?: string }) {
  return <span className={`rounded border px-2 py-1 text-[10px] font-black uppercase tracking-normal ${toneClass(value)}`}>{fmt(value)}</span>;
}

function confidenceTone(confidence: AuditAgentAnswer["confidence"]) {
  if (confidence === "high") return "ok";
  if (confidence === "low") return "risk";
  return "watch";
}

function monitorHeaderEntries(headers?: HeadersInit): Array<[string, string]> {
  if (!headers) return [];
  if (typeof Headers !== "undefined" && headers instanceof Headers) return Array.from(headers.entries());
  if (Array.isArray(headers)) return headers.map(([key, value]) => [key, value]);
  return Object.entries(headers).map(([key, value]) => [key, String(value)]);
}

function readJsonFromUrl<T>(url: string, init?: ApiRequestInit): Promise<T | null> {
  if (typeof XMLHttpRequest === "undefined") return Promise.resolve(null);
  const timeoutMs = init?.timeoutMs ?? 20000;
  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    xhr.open(init?.method ?? "GET", url, true);
    xhr.timeout = timeoutMs;
    for (const [key, value] of monitorHeaderEntries(init?.headers)) {
      xhr.setRequestHeader(key, value);
    }
    xhr.onload = () => {
      const contentType = (xhr.getResponseHeader("content-type") ?? "").toLowerCase();
      if (xhr.status < 200 || xhr.status >= 300 || contentType.includes("text/html")) {
        resolve(null);
        return;
      }
      try {
        resolve(JSON.parse(xhr.responseText || "null") as T);
      } catch {
        resolve(null);
      }
    };
    xhr.onerror = () => resolve(null);
    xhr.ontimeout = () => resolve(null);
    xhr.send((init?.body as XMLHttpRequestBodyInit | null | undefined) ?? null);
  });
}

async function readJson<T>(path: string, init?: ApiRequestInit): Promise<T | null> {
  for (const apiUrl of getApiUrls()) {
    const payload = await readJsonFromUrl<T>(`${apiUrl}${path}`, init);
    if (payload) return payload;
  }
  return null;
}

export default function MonitorPage() {
  const [monitor, setMonitor] = useState<MonitorData | null>(null);
  const [cases, setCases] = useState<CaseIndex | null>(null);
  const [agentOps, setAgentOps] = useState<AgentOpsLedger | null>(null);
  const [reviewLedger] = useState<ReviewLedger | null>(null);
  const [policyDoctrine, setPolicyDoctrine] = useState<PolicyDoctrine | null>(null);
  const [monitorEvidence, setMonitorEvidence] = useState<MonitorEvidenceGraph | null>(null);
  const [selectedPolicyRef, setSelectedPolicyRef] = useState("");
  const [policyRefDetail, setPolicyRefDetail] = useState<PolicyRefDetail | null>(null);
  const [selectedCaseId, setSelectedCaseId] = useState("");
  const [selectedReceiptId, setSelectedReceiptId] = useState("");
  const [traceFilter, setTraceFilter] = useState<TraceFilter>("all");
  const [policyQuery, setPolicyQuery] = useState("");
  const [auditDraft, setAuditDraft] = useState("Can I trust this case?");
  const [auditMessages, setAuditMessages] = useState<AuditAgentMessage[]>([]);
  const [auditSessionId, setAuditSessionId] = useState<string | undefined>(undefined);
  const [auditPersistence, setAuditPersistence] = useState<AuditSessionResponse["persistence"] | undefined>(undefined);
  const [traceTicketCorpus, setTraceTicketCorpus] = useState<TraceTicketCorpus | null>(null);
  const [isAuditAgentLoading, setIsAuditAgentLoading] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isDeepLoading, setIsDeepLoading] = useState(false);
  const [isTraceCorpusSyncing, setIsTraceCorpusSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const workspaceRequestRef = useRef(0);
  const secondaryRequestRef = useRef(0);
  const policyDetailRequestRef = useRef(0);
  const auditAgentRequestRef = useRef(0);
  const auditSessionLoadRef = useRef(0);
  const auditTranscriptRef = useRef<HTMLDivElement | null>(null);
  const auditConversationCaseRef = useRef<string | undefined>(undefined);
  const auditRestoringRef = useRef(false);

  const loadSecondaryEvidence = useCallback(async () => {
    const requestId = secondaryRequestRef.current + 1;
    secondaryRequestRef.current = requestId;
    const nextAgentOps = await readJson<AgentOpsLedger>("/api/park/agent-ops-ledger?limit=30", { timeoutMs: 15000 });
    if (secondaryRequestRef.current !== requestId) return;
    if (nextAgentOps) setAgentOps(nextAgentOps);
  }, []);

  const syncTraceTicketCorpus = useCallback(async (refresh = false) => {
    setIsTraceCorpusSyncing(true);
    try {
      const loaded = await readJson<TraceTicketCorpus>("/api/park/monitor-trace-tickets/load", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ limit: 200, refresh }),
        timeoutMs: 30000,
      });
      if (loaded) {
        setTraceTicketCorpus(loaded);
        return;
      }
      const existing = await readJson<TraceTicketCorpus>("/api/park/monitor-trace-tickets?limit=1", { timeoutMs: 15000 });
      if (existing) setTraceTicketCorpus(existing);
    } finally {
      setIsTraceCorpusSyncing(false);
    }
  }, []);

  const loadWorkspace = useCallback(async (depth: "summary" | "deep" = "summary") => {
    const requestId = workspaceRequestRef.current + 1;
    workspaceRequestRef.current = requestId;
    setIsLoading(true);
    setError(null);
    const monitorPath = depth === "deep" ? "/api/park/agent-monitoring/deep" : "/api/park/agent-monitoring";
    try {
      const [nextMonitor, nextCases, nextPolicyDoctrine, nextMonitorEvidence] = await Promise.all([
        readJson<MonitorData>(monitorPath, { timeoutMs: depth === "deep" ? 20000 : 15000 }),
        readJson<CaseIndex>("/api/park/cases", { timeoutMs: 15000 }),
        readJson<PolicyDoctrine>("/api/park/policy-doctrine", { timeoutMs: 15000 }),
        readJson<MonitorEvidenceGraph>("/api/park/monitor-evidence?limit=40", { timeoutMs: 20000 }),
      ]);
      if (workspaceRequestRef.current !== requestId) return;
      if (nextMonitor) setMonitor(nextMonitor);
      if (nextCases) setCases(nextCases);
      if (nextPolicyDoctrine) setPolicyDoctrine(nextPolicyDoctrine);
      if (nextMonitorEvidence) setMonitorEvidence(nextMonitorEvidence);
      if (!nextMonitor && !nextCases && !nextPolicyDoctrine && !nextMonitorEvidence) setError("Monitor evidence APIs did not return usable payloads.");
      void loadSecondaryEvidence();
      void syncTraceTicketCorpus(false);
    } finally {
      if (workspaceRequestRef.current === requestId) setIsLoading(false);
    }
  }, [loadSecondaryEvidence, syncTraceTicketCorpus]);

  const loadDeepMonitor = useCallback(async () => {
    const requestId = workspaceRequestRef.current + 1;
    workspaceRequestRef.current = requestId;
    setIsDeepLoading(true);
    try {
      const nextMonitor = await readJson<MonitorData>("/api/park/agent-monitoring/deep", { timeoutMs: 15000 });
      if (workspaceRequestRef.current !== requestId) return;
      if (nextMonitor) setMonitor(nextMonitor);
    } finally {
      if (workspaceRequestRef.current === requestId) setIsDeepLoading(false);
    }
  }, []);

  const loadPolicyRef = useCallback(async (policyRef: string) => {
    const requestId = policyDetailRequestRef.current + 1;
    policyDetailRequestRef.current = requestId;
    setSelectedPolicyRef(policyRef);
    const path = `/api/park/policy-doctrine/${encodeURIComponent(policyRef)}`;
    for (const apiUrl of getApiUrls()) {
      try {
        const detail = await new Promise<PolicyRefDetail | null>((resolve) => {
          if (typeof XMLHttpRequest === "undefined") {
            resolve(null);
            return;
          }
          const xhr = new XMLHttpRequest();
          xhr.open("GET", `${apiUrl}${path}`, true);
          xhr.timeout = 5000;
          xhr.onload = () => {
            const contentType = xhr.getResponseHeader("content-type") ?? "";
            if (xhr.status < 200 || xhr.status >= 300 || contentType.includes("text/html")) {
              resolve(null);
              return;
            }
            try {
              resolve(JSON.parse(xhr.responseText || "null") as PolicyRefDetail);
            } catch {
              resolve(null);
            }
          };
          xhr.onerror = () => resolve(null);
          xhr.ontimeout = () => resolve(null);
          xhr.send();
        });
        if (policyDetailRequestRef.current !== requestId) return;
        if (!detail) continue;
        setPolicyRefDetail(detail);
        return;
      } catch {
        continue;
      }
    }
  }, []);

  useEffect(() => {
    void loadWorkspace("summary");
  }, [loadWorkspace]);

  const caseRows = cases?.rows ?? [];
  const receipts = useMemo(() => dedupeReceipts(agentOps?.items ?? []), [agentOps?.items]);
  const selectedCase = useMemo(
    () => caseRows.find((item) => item.id === selectedCaseId) ?? caseRows[0],
    [caseRows, selectedCaseId],
  );
  const selectedEvidence = useMemo(
    () => monitorEvidence?.cases?.find((item) => (item.case_id ?? item.caseId) === selectedCase?.id),
    [monitorEvidence?.cases, selectedCase?.id],
  );
  const selectedCaseTerms = useMemo(() => {
    const terms = tokensFromText(`${selectedCase?.id ?? ""} ${selectedCase?.title ?? ""} ${selectedCase?.priority?.rationale ?? ""}`);
    if (selectedCase?.severity) {
      terms.add(selectedCase.severity.toLowerCase());
    }
    return terms;
  }, [selectedCase?.id, selectedCase?.priority?.rationale, selectedCase?.severity, selectedCase?.title]);
  const graphReceiptIds = useMemo(() => new Set(selectedEvidence?.receipt_ids ?? []), [selectedEvidence?.receipt_ids]);
  const graphReviewIds = useMemo(() => new Set(selectedEvidence?.review_session_ids ?? []), [selectedEvidence?.review_session_ids]);
  const relatedReceipts = useMemo(
    () =>
      receipts
        .map((item) => ({
          item,
          relationScore:
            graphReceiptIds.has(item.id ?? "") || item.caseId === selectedCase?.id || item.case_id === selectedCase?.id
              ? 100
              : receiptRelationScore(item, selectedCaseTerms),
        }))
        .filter((row) => row.relationScore >= 3 || graphReceiptIds.has(row.item.id ?? "") || row.item.caseId === selectedCase?.id || row.item.case_id === selectedCase?.id)
        .sort((left, right) => right.relationScore - left.relationScore || (right.item.evalScore ?? 0) - (left.item.evalScore ?? 0)),
    [graphReceiptIds, receipts, selectedCase?.id, selectedCaseTerms],
  );
  const orderedReceipts = useMemo(() => {
    const relatedIds = new Set(relatedReceipts.map((row) => row.item.id));
    return [...relatedReceipts, ...receipts.filter((item) => !relatedIds.has(item.id)).map((item) => ({ item, relationScore: 0 }))];
  }, [receipts, relatedReceipts]);
  const selectedReceipt = useMemo(
    () => receipts.find((item) => item.id === selectedReceiptId) ?? relatedReceipts[0]?.item ?? receipts[0],
    [receipts, relatedReceipts, selectedReceiptId],
  );
  const selectedGraphTrace = useMemo(() => {
    if (!selectedReceipt) return undefined;
    return (selectedEvidence?.trace_records ?? []).find((item) => {
      const traceKey = item.trace_id ?? item.signature ?? item.receipt_id;
      return item.receipt_id === selectedReceipt.id || traceKey === selectedReceipt.traceId || traceKey === selectedReceipt.signature;
    });
  }, [selectedEvidence?.trace_records, selectedReceipt]);
  const visibleTraceRecords = useMemo(() => {
    const rows = selectedEvidence?.trace_records ?? [];
    return rows.filter((item) => {
      const relation = `${item.relation_type ?? ""} ${item.relation_confidence ?? ""} ${item.case_link_source ?? ""}`.toLowerCase();
      const gate = `${item.gate ?? ""}`.toLowerCase();
      if (traceFilter === "direct") return relation.includes("direct") || relation.includes("explicit") || relation.includes("runtime_case_binding");
      if (traceFilter === "inferred") return relation.includes("inferred") || relation.includes("semantic");
      if (traceFilter === "review") return gate.includes("review") || relation.includes("review");
      if (traceFilter === "blocked") return gate.includes("block") || relation.includes("block");
      return true;
    });
  }, [selectedEvidence?.trace_records, traceFilter]);

  const reviewRows = reviewLedger?.open_reviews ?? reviewLedger?.rows ?? [];
  const graphReviewRows = useMemo(
    () =>
      (selectedEvidence?.review_sessions ?? []).map((item) => ({
        id: item.review_session_id,
        case_id: item.case_id,
        status: item.status,
        priority: item.priority,
        owner: item.owner,
        reason: item.reason,
        event: { source: item.relation_confidence ?? item.relation_type, signal_type: item.hard_match ? "case-token match" : "semantic match" },
        disposition: undefined,
      })),
    [selectedEvidence?.review_sessions],
  );
  const selectedReviewRows = useMemo(() => {
    if (graphReviewRows.length) return graphReviewRows;
    if (!graphReviewIds.size) return reviewRows;
    const linked = reviewRows.filter((item) => graphReviewIds.has(item?.id ?? ""));
    return linked.length ? linked : reviewRows;
  }, [graphReviewIds, graphReviewRows, reviewRows]);
  const governanceReviews = [
    ...(monitor?.runtime_governance?.decision_ledger ?? []).map((item) => ({
      id: item.id,
      title: item.title ?? item.id,
      status: item.gateStatus,
      owner: "policy gate",
      detail: compact(item.policyFindings),
    })),
    ...(monitor?.runtime_governance?.remediation_tasks ?? []).map((item) => ({
      id: item.id,
      title: item.title ?? item.requiredAction ?? item.id,
      status: item.status,
      owner: item.owner,
      detail: compact(item.policyFindings) || item.severity,
    })),
    ...(monitor?.supervised_actions ?? []).map((item) => ({
      id: item.action_id,
      title: item.title ?? item.action_id,
      status: item.policy_status,
      owner: item.owner,
      detail: item.park_action?.target,
    })),
    ...(monitor?.runtime_governance?.customer_care_cases ?? []).map((item) => ({
      id: item.id,
      title: item.reason ?? item.id,
      status: item.status,
      owner: item.safeAudience,
      detail: item.severity,
    })),
  ];

  const doctrine = policyDoctrine;
  const policyCases = doctrine?.action_cases ?? [];
  const policyRefs = useMemo<PolicyRefRow[]>(
    () => (doctrine?.policy_refs ?? []).map((item) => (typeof item === "string" ? { policy_ref: item } : item)),
    [doctrine?.policy_refs],
  );
  const selectedPolicyCase = useMemo(() => {
    const byId = policyCases.find((item) => item.id === selectedCase?.id);
    if (byId) return byId;
    return policyCases.find((item) => sharedTokenCount(selectedCaseTerms, `${item.id ?? ""} ${item.title ?? ""} ${(item.triggers ?? []).join(" ")}`) > 0);
  }, [policyCases, selectedCase?.id, selectedCaseTerms]);
  const selectedPolicyRefs = useMemo(() => {
    const refs = new Set([...(selectedEvidence?.policy_refs ?? []), ...(selectedPolicyCase?.policy_refs ?? [])]);
    return policyRefs.filter((item) => item.policy_ref && refs.has(item.policy_ref));
  }, [policyRefs, selectedEvidence?.policy_refs, selectedPolicyCase?.policy_refs]);
  const firstSelectedPolicyRef = selectedEvidence?.policy_refs?.[0] ?? selectedPolicyCase?.policy_refs?.[0] ?? "";
  const activePolicyRef = selectedPolicyRef || firstSelectedPolicyRef;
  const graphPolicyRefDetail = useMemo(() => {
    if (!activePolicyRef) return null;
    return (selectedEvidence?.policy_ref_rows ?? []).find((item) => item.policy_ref === activePolicyRef)?.detail ?? null;
  }, [activePolicyRef, selectedEvidence?.policy_ref_rows]);
  const activePolicyRefDetail = policyRefDetail?.policy_ref === activePolicyRef ? policyRefDetail : graphPolicyRefDetail;

  useEffect(() => {
    if (firstSelectedPolicyRef && firstSelectedPolicyRef !== selectedPolicyRef) {
      void loadPolicyRef(firstSelectedPolicyRef);
    }
  }, [firstSelectedPolicyRef, loadPolicyRef, selectedPolicyRef]);
  const filteredPolicyCases = policyCases.filter((item) => {
    const query = policyQuery.trim().toLowerCase();
    if (!query) return item.id === selectedPolicyCase?.id;
    return [item.id, item.title, ...(item.triggers ?? []), ...(item.policy_refs ?? [])]
      .filter(Boolean)
      .join(" ")
      .toLowerCase()
      .includes(query);
  });
  const filteredPolicyRefs = policyRefs.filter((item) => {
    const query = policyQuery.trim().toLowerCase();
    if (!query) return selectedPolicyRefs.some((ref) => ref.policy_ref === item.policy_ref);
    return [item.policy_ref, item.policy_book_id, item.title, item.summary, item.severity]
      .filter(Boolean)
      .join(" ")
      .toLowerCase()
      .includes(query);
  });

  const averageCaseScore = caseRows.length
    ? caseRows.reduce((total, item) => total + (item.quality?.score ?? 0), 0) / caseRows.length
    : undefined;
  const traceCount = monitorEvidence?.summary?.distinct_trace_id_count ?? monitorEvidence?.summary?.trace_record_count ?? receipts.filter((item) => item.traceId || item.signature || item.toolCalls?.length).length;
  const auditCorpusCount = traceTicketCorpus?.ticket_count ?? traceTicketCorpus?.count ?? traceTicketCorpus?.persistence?.count;
  const auditCorpusCaseCount = traceTicketCorpus?.case_corpus?.case_count ?? doctrine?.action_case_count ?? policyCases.length;
  const auditCorpusTraceCount = traceTicketCorpus?.analysis?.withTraceCount;
  const auditCorpusReviewCount = traceTicketCorpus?.analysis?.withReviewCount;
  const auditCorpusMissingTraceCount = traceTicketCorpus?.analysis?.riskFlags?.no_trace;
  const auditCorpusStatus = traceTicketCorpus?.persistence?.connected
    ? "mongo synced"
    : traceTicketCorpus?.persistence?.primary
      ? fmt(traceTicketCorpus.persistence.primary)
      : isTraceCorpusSyncing
        ? "syncing"
        : "pending";
  const selectedTraceCount = selectedEvidence?.trace_records?.length ?? selectedEvidence?.trace_ids?.length ?? relatedReceipts.length;
  const selectedPolicyRefCount = selectedEvidence?.policy_refs?.length ?? selectedPolicyCase?.policy_refs?.length ?? 0;
  const selectedReviewCount = selectedEvidence?.review_session_ids?.length ?? selectedReviewRows.length;
  const selectedEvalDimensions = selectedEvidence?.eval_dimensions ?? [];
  const explicitLinkCount = (selectedEvidence?.relationship_contract?.explicit_receipt_links ?? 0) + (selectedEvidence?.relationship_contract?.explicit_review_links ?? 0);
  const inferredLinkCount = (selectedEvidence?.relationship_contract?.inferred_receipt_links ?? 0) + (selectedEvidence?.relationship_contract?.inferred_review_links ?? 0);
  const directReviewLinkCount = selectedEvidence?.relationship_contract?.explicit_review_links ?? 0;
  const inferredReviewLinkCount = selectedEvidence?.relationship_contract?.inferred_review_links ?? 0;
  const relatedGovernanceReviews = governanceReviews.filter((item) => sharedTokenCount(selectedCaseTerms, `${item.title ?? ""} ${item.detail ?? ""} ${item.owner ?? ""}`) > 0);
  const visibleGovernanceReviews = relatedGovernanceReviews.length ? relatedGovernanceReviews : governanceReviews;
  const reviewAccessBlocked = reviewLedger?.status === "blocked" || Boolean(reviewLedger?.readiness_issues?.length);
  const openReviewCount = reviewLedger?.summary?.open_count ?? reviewRows.filter((item) => item?.status !== "closed").length;
  const reviewSummaryValue = reviewAccessBlocked ? "auth gated" : String(monitorEvidence?.summary?.linked_review_session_count ?? monitorEvidence?.summary?.review_session_count ?? (openReviewCount || visibleGovernanceReviews.length || 0));
  const cacheState = monitorEvidence?.evidence_cache?.source_current === false ? "source stale" : monitorEvidence?.evidence_cache?.state ?? "not loaded";
  const sourceStatus = monitorEvidence?.source_status ?? {};
  const auditAnswer = [...auditMessages].reverse().find((message) => message.role === "assistant" && message.answer)?.answer ?? null;
  const fallbackAuditAgentAnswer = useCallback(
    (question: string): AuditAgentAnswer => {
      const lowerQuestion = question.toLowerCase();
      const evalValue = selectedCase?.quality?.score;
      const evalPct = typeof evalValue === "number" ? Math.round(evalValue * 100) : undefined;
      const traceLinks = selectedEvidence?.trace_records?.length ?? selectedEvidence?.trace_ids?.length ?? relatedReceipts.length;
      const reviewLinks = selectedEvidence?.review_sessions?.length ?? selectedEvidence?.review_session_ids?.length ?? selectedReviewRows.length;
      const policyLinks = selectedEvidence?.policy_refs?.length ?? selectedPolicyCase?.policy_refs?.length ?? 0;
      const directLinks = explicitLinkCount;
      const inferredLinks = inferredLinkCount;
      const hasFreshGraph = monitorEvidence?.evidence_cache?.source_current !== false && /fresh|ready|complete/i.test(cacheState);
      const gate = selectedReceipt?.gate ?? selectedGraphTrace?.gate ?? monitor?.overall_status ?? selectedCase?.severity;
      const blockedActions = selectedPolicyCase?.blocked_actions ?? [];
      const requiredEvidence = activePolicyRefDetail?.matches?.flatMap((item) => item.required_evidence ?? []) ?? [];
      const humanReviewRules = activePolicyRefDetail?.matches?.flatMap((item) => item.human_review_if ?? []) ?? [];
      const confidence: AuditAgentAnswer["confidence"] =
        hasFreshGraph && directLinks > 0 && traceLinks > 0 && policyLinks > 0 && typeof evalPct === "number" && evalPct >= 80
          ? "high"
          : traceLinks > 0 && policyLinks > 0
            ? "medium"
            : "low";

      const evidence = [
        selectedCase?.id ? `Selected case: ${selectedCase.id}${selectedCase.title ? `, ${selectedCase.title}` : ""}.` : undefined,
        typeof evalPct === "number" ? `Eval score is ${evalPct}/100 with status ${fmt(selectedCase?.quality?.status)}.` : undefined,
        `Evidence graph is ${fmt(cacheState)}${typeof monitorEvidence?.evidence_cache?.age_seconds === "number" ? `, age ${Math.round(monitorEvidence.evidence_cache.age_seconds)}s` : ""}.`,
        `${traceLinks} trace link${traceLinks === 1 ? "" : "s"}, ${reviewLinks} review link${reviewLinks === 1 ? "" : "s"}, ${policyLinks} policy ref${policyLinks === 1 ? "" : "s"}.`,
        gate ? `Current linked gate/status: ${fmt(gate)}.` : undefined,
        selectedReceipt?.summary ? `Most relevant receipt: ${selectedReceipt.summary}.` : undefined,
        selectedPolicyCase?.title ? `Policy case: ${selectedPolicyCase.title}.` : undefined,
      ].filter((item): item is string => Boolean(item)).slice(0, 7);

      const uncertainty = [
        !hasFreshGraph ? "The monitor graph is not confirmed fresh, so linked evidence may lag current runtime state." : undefined,
        !directLinks && inferredLinks > 0 ? "Some evidence is inferred by semantic overlap rather than direct case IDs." : undefined,
        !traceLinks ? "No trace record is linked to this case yet." : undefined,
        !policyLinks ? "No policy reference is directly linked to this case yet." : undefined,
        reviewAccessBlocked ? "The signed review ledger is auth gated; only governance-derived review evidence is visible." : undefined,
        !selectedEvalDimensions.length ? "No dimension-level eval evidence is attached for this selected case." : undefined,
      ].filter((item): item is string => Boolean(item)).slice(0, 5);

      const policyActions = [
        blockedActions.length ? `Blocked actions to avoid: ${compact(blockedActions, 3)}.` : undefined,
        requiredEvidence.length ? `Required evidence to verify: ${compact(requiredEvidence, 4)}.` : undefined,
        humanReviewRules.length ? `Human review triggers: ${compact(humanReviewRules, 3)}.` : undefined,
      ].filter((item): item is string => Boolean(item));

      const nextActions = lowerQuestion.includes("policy")
        ? [...policyActions, "Open the linked policy ref and compare allowed, blocked, and required-evidence clauses."]
        : lowerQuestion.includes("weak") || lowerQuestion.includes("risk") || lowerQuestion.includes("missing")
          ? [
              directLinks ? "Prefer direct case-ID evidence over inferred links when deciding trust." : "Create or load a direct trace/case binding before treating this as strong proof.",
              traceLinks ? "Inspect the selected trace and tool-call list for missing receiver or policy steps." : "Load trace links or rerun the operating case to create a receipt.",
              policyLinks ? "Verify the policy refs explain both allowed and blocked actions." : "Attach a policy ref before promotion or training use.",
            ]
          : [
              "Use the case score, trace receipt, review state, and policy refs together; do not rely on the score alone.",
              "If dispatch or model training depends on this case, verify direct trace links and policy refs first.",
              selectedCase?.governance?.nextOwnerAction ?? "No owner action is attached; assign an operator review before closing the case.",
            ];

      const conclusion = lowerQuestion.includes("policy")
        ? policyLinks
          ? `The selected case is policy-explainable: ${policyLinks} policy reference${policyLinks === 1 ? "" : "s"} connect the case to allowed and blocked actions.`
          : "The selected case is not policy-explainable yet because no direct policy reference is linked."
        : lowerQuestion.includes("weak") || lowerQuestion.includes("risk") || lowerQuestion.includes("missing")
          ? uncertainty.length
            ? `The main audit risk is evidence completeness: ${uncertainty[0]}`
            : "The case has no obvious evidence gap in the current monitor graph."
          : confidence === "high"
            ? "This case is currently strong enough to explain to an operator: eval, trace, review, and policy evidence are linked."
            : confidence === "medium"
              ? "This case is partially explainable, but the user should inspect link quality before trusting it for promotion or training."
              : "This case is not yet strong enough as audit proof; it needs trace, review, or policy evidence before users should rely on it.";

      return {
        status: "fallback",
        mode: "client_fallback_audit_explainer",
        llm_used: false,
        conclusion,
        answer: conclusion,
        confidence,
        evidence,
        memory_comparison: [
          `Audit corpus has ${auditCorpusCount ?? "--"} tickets; ${auditCorpusTraceCount ?? 0} have trace links and ${auditCorpusReviewCount ?? 0} have review links.`,
          auditCorpusMissingTraceCount !== undefined ? `${auditCorpusMissingTraceCount} remembered cases still lack trace proof.` : "Corpus gap count is not loaded yet.",
        ],
        policy_alignment: policyActions.length ? policyActions : ["No detailed policy negotiation is loaded in the client fallback."],
        confidence_basis: [
          `traceLinks=${traceLinks}`,
          `reviewLinks=${reviewLinks}`,
          `policyLinks=${policyLinks}`,
          `directLinks=${directLinks}`,
          `freshGraph=${hasFreshGraph ? "yes" : "no"}`,
        ],
        audit_gaps: uncertainty.length ? uncertainty : ["No immediate audit gap detected from loaded client context."],
        uncertainty: uncertainty.length ? uncertainty : ["No material uncertainty detected from the loaded monitor graph."],
        next_actions: nextActions.filter(Boolean).slice(0, 4),
        scope: "Read-only audit explainer. It explains loaded monitor evidence and does not dispatch actions, close reviews, or change model training.",
      };
    },
    [
      activePolicyRefDetail?.matches,
      auditCorpusCount,
      auditCorpusMissingTraceCount,
      auditCorpusReviewCount,
      auditCorpusTraceCount,
      cacheState,
      explicitLinkCount,
      inferredLinkCount,
      monitor?.overall_status,
      monitorEvidence?.evidence_cache?.age_seconds,
      monitorEvidence?.evidence_cache?.source_current,
      relatedReceipts.length,
      reviewAccessBlocked,
      selectedCase?.governance?.nextOwnerAction,
      selectedCase?.id,
      selectedCase?.quality?.score,
      selectedCase?.quality?.status,
      selectedCase?.severity,
      selectedCase?.title,
      selectedEvalDimensions.length,
      selectedEvidence?.policy_refs,
      selectedEvidence?.review_session_ids,
      selectedEvidence?.review_sessions,
      selectedEvidence?.trace_ids,
      selectedEvidence?.trace_records,
      selectedGraphTrace?.gate,
      selectedPolicyCase?.blocked_actions,
      selectedPolicyCase?.policy_refs,
      selectedPolicyCase?.title,
      selectedReceipt?.gate,
      selectedReceipt?.summary,
      selectedReviewRows.length,
    ],
  );

  const runAuditAgent = useCallback(
    async (question: string) => {
      const trimmedQuestion = question.trim();
      if (!selectedCase || !trimmedQuestion || isAuditAgentLoading) return;
      const requestId = auditAgentRequestRef.current + 1;
      auditAgentRequestRef.current = requestId;
      setIsAuditAgentLoading(true);
      const now = Date.now();
      const userMessage: AuditAgentMessage = {
        id: `user-${now}`,
        role: "user",
        content: trimmedQuestion,
        createdAt: now,
        sessionId: auditSessionId,
      };
      const history = auditMessages
        .filter((message) => message.role !== "system")
        .slice(-8)
        .map((message) => ({
          role: message.role,
          content: message.role === "assistant" ? message.answer?.answer || message.answer?.conclusion || message.content : message.content,
        }));
      const messagesWithUserTurn = [...auditMessages, userMessage];
      setAuditMessages(messagesWithUserTurn);
      setAuditDraft("");
      writeStoredAuditConversation(selectedCase.id, messagesWithUserTurn, "", auditSessionId);
      const fallback = fallbackAuditAgentAnswer(trimmedQuestion);
      try {
        const answer = await readJson<AuditAgentAnswer>("/api/park/monitor-audit-agent", {
          method: "POST",
          headers: { "content-type": "application/json", "x-parkpulse-role": "ops_team" },
          body: JSON.stringify({
            question: trimmedQuestion,
            session_id: auditSessionId,
            user_message_id: userMessage.id,
            history,
            context: {
              selected_case: selectedCase,
              selected_evidence: selectedEvidence,
              selected_receipt: selectedReceipt,
              selected_graph_trace: selectedGraphTrace,
              selected_policy_case: selectedPolicyCase,
              active_policy_ref_detail: activePolicyRefDetail,
              eval_dimensions: selectedEvalDimensions,
              review_sessions: selectedReviewRows,
              monitor_cache: {
                state: cacheState,
                age_seconds: monitorEvidence?.evidence_cache?.age_seconds,
                source_current: monitorEvidence?.evidence_cache?.source_current,
              },
            },
          }),
          timeoutMs: 15000,
        });
        if (auditAgentRequestRef.current !== requestId) return;
        const finalAnswer = answer?.conclusion ? answer : { ...fallback, runtime: { provider: "client_fallback", readiness_issues: ["Audit agent API did not return a usable answer."] } };
        const nextSessionId = finalAnswer.audit_session?.session_id ?? auditSessionId;
        setAuditSessionId(nextSessionId);
        setAuditPersistence(finalAnswer.audit_session);
        const assistantMessage: AuditAgentMessage = {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          content: finalAnswer.answer || finalAnswer.conclusion,
          answer: finalAnswer,
          createdAt: Date.now(),
          evidencePacketHash: finalAnswer.audit_session?.evidence_packet_hash,
          sessionId: nextSessionId,
        };
        setAuditMessages((current) => {
          const nextMessages = [...current, assistantMessage];
          writeStoredAuditConversation(selectedCase.id, nextMessages, "", nextSessionId);
          return nextMessages;
        });
      } finally {
        if (auditAgentRequestRef.current === requestId) setIsAuditAgentLoading(false);
      }
    },
    [
      activePolicyRefDetail,
      auditSessionId,
      cacheState,
      fallbackAuditAgentAnswer,
      auditMessages,
      isAuditAgentLoading,
      monitorEvidence?.evidence_cache?.age_seconds,
      monitorEvidence?.evidence_cache?.source_current,
      selectedCase,
      selectedEvidence,
      selectedEvalDimensions,
      selectedGraphTrace,
      selectedPolicyCase,
      selectedReceipt,
      selectedReviewRows,
    ],
  );

  useEffect(() => {
    if (!selectedCase) return;
    const caseId = selectedCase.id ?? "selected-case";
    const stored = readStoredAuditConversation(caseId);
    const loadId = auditSessionLoadRef.current + 1;
    auditSessionLoadRef.current = loadId;
    auditConversationCaseRef.current = caseId;
    auditRestoringRef.current = true;
    setAuditMessages(stored?.messages?.length ? stored.messages : [caseLoadedAuditMessage(caseId, selectedCase.title)]);
    setAuditDraft(stored?.draft ?? "Can I trust this case?");
    setAuditSessionId(stored?.sessionId);
    setAuditPersistence(stored?.sessionId ? { primary: "session_storage", connected: false, mode: "local_restore" } : undefined);
    auditAgentRequestRef.current += 1;
    setIsAuditAgentLoading(false);
    void (async () => {
      const response = await readJson<AuditSessionResponse>(
        `/api/park/monitor-audit-agent/session?case_id=${encodeURIComponent(caseId)}&limit=20`,
        { timeoutMs: 10000 },
      );
      if (auditSessionLoadRef.current !== loadId || auditConversationCaseRef.current !== caseId) return;
      setAuditPersistence(response?.persistence);
      const remoteMessages = (response?.messages ?? []).filter(validAuditMessage);
      if (!remoteMessages.length) return;
      const remoteSessionId = response?.session?.session_id;
      setAuditSessionId(remoteSessionId);
      setAuditMessages(remoteMessages);
      writeStoredAuditConversation(caseId, remoteMessages, stored?.draft ?? "Can I trust this case?", remoteSessionId);
    })();
  }, [selectedCase?.id, selectedCase?.title]);

  useEffect(() => {
    const caseId = selectedCase?.id;
    if (!caseId || auditConversationCaseRef.current !== caseId) return;
    if (auditRestoringRef.current) {
      auditRestoringRef.current = false;
      return;
    }
    writeStoredAuditConversation(caseId, auditMessages, auditDraft, auditSessionId);
  }, [auditDraft, auditMessages, auditSessionId, selectedCase?.id]);

  useEffect(() => {
    auditTranscriptRef.current?.scrollTo({ top: auditTranscriptRef.current.scrollHeight, behavior: "smooth" });
  }, [auditMessages, isAuditAgentLoading]);

  return (
    <main className="min-h-screen bg-slate-950 px-4 py-5 font-sans text-slate-200 lg:px-8">
      <div className="mx-auto max-w-[1500px] space-y-5">
        <header className="border-b border-slate-800 pb-5">
          <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Runtime monitor</div>
              <h1 className="mt-2 text-3xl font-black tracking-normal text-slate-100 lg:text-4xl">Evidence workspace</h1>
              <p className="mt-3 max-w-4xl text-sm leading-relaxed text-slate-400">
                Check case eval scores, trace records, human review sessions, and policy doctrine without leaving the operating context.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => void loadWorkspace("summary")}
                disabled={isLoading}
                className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-100 disabled:opacity-50"
              >
                {isLoading ? "Refreshing" : "Refresh"}
              </button>
              <button
                type="button"
                onClick={() => {
                  void syncTraceTicketCorpus(true);
                  void loadDeepMonitor();
                }}
                disabled={isDeepLoading || isTraceCorpusSyncing}
                className="rounded border border-cyan-300 bg-cyan-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-cyan-200 disabled:opacity-50"
              >
                {isDeepLoading || isTraceCorpusSyncing ? "Syncing corpus" : "Refresh corpus"}
              </button>
              <a href="/ops" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-100">
                Operating loop
              </a>
            </div>
          </div>
        </header>

        {error ? <section className="rounded border border-amber-400/30 bg-amber-950/15 p-3 text-sm font-bold text-amber-100">Runtime debug: {error}</section> : null}

        <section className="grid gap-2 md:grid-cols-3 lg:grid-cols-7">
          {[
            ["Live queue", String((cases?.summary?.caseCount ?? caseRows.length) || "--")],
            ["Audit corpus", auditCorpusCount ? `${auditCorpusCount}/${auditCorpusCaseCount || auditCorpusCount}` : isTraceCorpusSyncing ? "syncing" : "--"],
            ["Avg eval", score(averageCaseScore, 1)],
            ["Receipts", String(receipts.length || "--")],
            ["Traces", String(traceCount || "--")],
            ["Review", reviewSummaryValue],
            ["Policies", String(monitorEvidence?.summary?.policy_ref_count ?? doctrine?.policy_book_count ?? monitor?.summary?.policy_book_count ?? "--")],
          ].map(([label, value]) => (
            <div key={label} className="rounded border border-slate-800 bg-slate-900 px-3 py-2">
              <div className="text-[9px] font-black uppercase tracking-widest text-slate-500">{label}</div>
              <div className="mt-1 truncate text-sm font-black text-cyan-100">{value}</div>
            </div>
          ))}
        </section>

        <section className="grid gap-2 rounded-lg border border-slate-800 bg-slate-900 p-3 lg:grid-cols-5">
          {[
            ["Backend graph", fmt(cacheState)],
            ["Age", typeof monitorEvidence?.evidence_cache?.age_seconds === "number" ? `${Math.round(monitorEvidence.evidence_cache.age_seconds)}s` : "--"],
            ["Cases source", fmt(sourceStatus.case_index)],
            ["Trace source", fmt(sourceStatus.agent_ops_ledger)],
            ["Source current", fmt(monitorEvidence?.evidence_cache?.source_current)],
          ].map(([label, value]) => (
            <div key={label} className="rounded border border-slate-800 bg-slate-950 px-3 py-2">
              <div className="text-[9px] font-black uppercase tracking-widest text-slate-500">{label}</div>
              <div className="mt-1 truncate text-xs font-black text-slate-100">{value}</div>
            </div>
          ))}
        </section>

        <section className="grid gap-2 rounded-lg border border-slate-800 bg-slate-900 p-3 lg:grid-cols-4">
          {[
            ["Audit store", auditCorpusStatus],
            ["Corpus traces", auditCorpusTraceCount !== undefined ? `${auditCorpusTraceCount} linked` : "--"],
            ["Corpus review", auditCorpusReviewCount !== undefined ? `${auditCorpusReviewCount} linked` : "--"],
            ["Missing trace", auditCorpusMissingTraceCount !== undefined ? `${auditCorpusMissingTraceCount} cases` : "--"],
          ].map(([label, value]) => (
            <div key={label} className="rounded border border-slate-800 bg-slate-950 px-3 py-2">
              <div className="text-[9px] font-black uppercase tracking-widest text-slate-500">{label}</div>
              <div className="mt-1 truncate text-xs font-black text-slate-100">{value}</div>
            </div>
          ))}
        </section>

        <section className="grid gap-2 rounded-lg border border-slate-800 bg-slate-900 p-3 lg:grid-cols-5">
          {[
            ["1. Case", selectedCase?.id ?? "select case"],
            ["2. Eval", score(selectedCase?.quality?.score, 1)],
            ["3. Trace", selectedTraceCount ? `${selectedTraceCount} linked` : "no direct match"],
            ["4. Review", selectedReviewCount ? `${selectedReviewCount} sessions` : reviewSummaryValue],
            ["5. Policy", selectedPolicyRefCount ? compact(selectedEvidence?.policy_refs ?? selectedPolicyCase?.policy_refs, 2) : "no direct refs"],
          ].map(([label, value]) => (
            <div key={label} className="rounded border border-slate-800 bg-slate-950 px-3 py-2">
              <div className="text-[9px] font-black uppercase tracking-widest text-slate-500">{label}</div>
              <div className="mt-1 truncate text-xs font-black text-slate-100">{value}</div>
            </div>
          ))}
        </section>

        <section className="grid gap-4 rounded-lg border border-violet-400/25 bg-violet-950/10 p-4 xl:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
          <div>
            <div className="text-[10px] font-black uppercase tracking-widest text-violet-300">LLM audit agent</div>
            <h2 className="mt-1 text-xl font-black text-slate-100">Talk through this case</h2>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-slate-400">
              The agent keeps the selected case, trace links, review sessions, eval dimensions, and policy refs in scope while answering follow-up questions.
            </p>
            <div className="mt-4 rounded border border-slate-800 bg-slate-950/70 p-3">
              <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Current case context</div>
              <div className="mt-2 text-sm font-black leading-snug text-slate-100">{selectedCase?.title ?? "No case selected"}</div>
              <div className="mt-2 grid gap-2 text-[10px] font-black uppercase tracking-normal text-slate-400 sm:grid-cols-3">
                <span className="rounded bg-slate-900 px-2 py-1">Trace {selectedTraceCount || 0}</span>
                <span className="rounded bg-slate-900 px-2 py-1">Review {selectedReviewCount || 0}</span>
                <span className="rounded bg-slate-900 px-2 py-1">Policy {selectedPolicyRefCount || 0}</span>
              </div>
            </div>
            <form
              className="mt-4 flex flex-col gap-2 sm:flex-row"
              onSubmit={(event) => {
                event.preventDefault();
                void runAuditAgent(auditDraft);
              }}
            >
              <input
                value={auditDraft}
                onChange={(event) => setAuditDraft(event.target.value)}
                placeholder="Ask a follow-up about trust, evidence, policy, or operator action"
                className="min-h-[40px] flex-1 rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm font-bold text-slate-100 outline-none transition placeholder:text-slate-600 focus:border-violet-300"
              />
              <button
                type="submit"
                disabled={isAuditAgentLoading || !auditDraft.trim() || !selectedCase}
                className="rounded border border-violet-300 bg-violet-300 px-4 py-2 text-xs font-black text-slate-950 transition hover:bg-violet-200"
              >
                {isAuditAgentLoading ? "Thinking" : "Send"}
              </button>
            </form>
            <div className="mt-3 flex flex-wrap gap-2">
              {["Can I trust this case?", "What evidence is weak?", "Which policy matters?", "Challenge your conclusion."].map((question) => (
                <button
                  key={question}
                  type="button"
                  disabled={isAuditAgentLoading || !selectedCase}
                  onClick={() => {
                    void runAuditAgent(question);
                  }}
                  className="rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-[10px] font-black uppercase tracking-normal text-slate-300 transition hover:border-violet-300 hover:text-violet-100"
                >
                  {question}
                </button>
              ))}
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-950/70 p-3">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-violet-300">Conversation</div>
                <div className="mt-1 text-sm font-black text-slate-100">Case-aware audit dialogue</div>
              </div>
              <span className="rounded bg-slate-900 px-2 py-1 text-[10px] font-black uppercase tracking-widest text-slate-400">
                {auditAnswer?.llm_used ? "LLM" : auditAnswer ? "fallback" : "ready"}
              </span>
            </div>
            <div className="mb-3 flex flex-wrap gap-2 text-[10px] font-black uppercase tracking-widest text-slate-500">
              <span className="rounded border border-slate-800 bg-slate-900 px-2 py-1">
                {auditPersistence?.primary ?? "session storage"}
              </span>
              {auditSessionId ? <span className="rounded border border-slate-800 bg-slate-900 px-2 py-1">session {auditSessionId.slice(0, 18)}</span> : null}
              {auditPersistence?.connected !== undefined ? (
                <span className="rounded border border-slate-800 bg-slate-900 px-2 py-1">{auditPersistence.connected ? "mongo connected" : "local fallback"}</span>
              ) : null}
            </div>
            <div ref={auditTranscriptRef} className="max-h-[520px] space-y-3 overflow-auto pr-1">
              {auditMessages.map((message) => {
                if (message.role === "system") {
                  return (
                    <div key={message.id} className="rounded border border-slate-800 bg-slate-900/80 px-3 py-2 text-xs font-bold text-slate-400">
                      {message.content}
                    </div>
                  );
                }
                if (message.role === "user") {
                  return (
                    <div key={message.id} className="ml-auto max-w-[82%] rounded-lg border border-cyan-400/25 bg-cyan-950/30 px-3 py-2 text-sm font-bold leading-relaxed text-cyan-50">
                      {message.content}
                    </div>
                  );
                }
                const answer = message.answer;
                const nextActions = answer?.next_actions ?? answer?.nextActions ?? [];
                const memoryComparison = answer?.memory_comparison ?? answer?.memoryComparison ?? [];
                const policyAlignment = answer?.policy_alignment ?? answer?.policyAlignment ?? [];
                const confidenceBasis = answer?.confidence_basis ?? answer?.confidenceBasis ?? [];
                const auditGaps = answer?.audit_gaps ?? answer?.auditGaps ?? [];
                return (
                  <div key={message.id} className={`max-w-[92%] rounded-lg border p-3 ${toneClass(confidenceTone(answer?.confidence ?? "low"))}`}>
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                      <div>
                        <div className="text-[10px] font-black uppercase tracking-widest opacity-70">Audit agent</div>
                        <p className="mt-1 text-sm font-black leading-relaxed">{answer?.conclusion ?? message.content}</p>
                      </div>
                      <span className="w-fit rounded bg-slate-950/45 px-2 py-1 text-[10px] font-black uppercase tracking-widest">
                        {answer?.llm_used ? "LLM" : "fallback"} / {answer?.confidence ?? "low"}
                      </span>
                    </div>
                    {answer?.runtime ? (
                      <div className="mt-2 flex flex-wrap gap-2 text-[10px] font-black uppercase tracking-widest opacity-80">
                        <span className="rounded bg-slate-950/35 px-2 py-1">{answer.runtime.provider ?? answer.mode ?? "audit agent"}</span>
                        {typeof answer.runtime.elapsed_ms === "number" ? <span className="rounded bg-slate-950/35 px-2 py-1">{answer.runtime.elapsed_ms}ms</span> : null}
                        <span className="rounded bg-slate-950/35 px-2 py-1">{answer.status ?? "ready"}</span>
                      </div>
                    ) : null}
                    {answer?.answer && answer.answer !== answer.conclusion ? <p className="mt-3 text-sm font-bold leading-relaxed opacity-90">{answer.answer}</p> : null}
                    <div className="mt-3 grid gap-2 lg:grid-cols-3">
                      {[
                        ["Evidence", answer?.evidence ?? []],
                        ["Uncertainty", answer?.uncertainty ?? []],
                        ["Next", nextActions],
                      ].map(([label, items]) => (
                        <div key={label as string} className="rounded border border-slate-950/25 bg-slate-950/30 p-2">
                          <div className="text-[10px] font-black uppercase tracking-widest opacity-70">{label as string}</div>
                          <div className="mt-1.5 space-y-1">
                            {(items as string[]).slice(0, 3).map((item) => (
                              <div key={item} className="rounded bg-slate-950/35 px-2 py-1 text-[11px] font-bold leading-relaxed opacity-90">
                                {item}
                              </div>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                    {memoryComparison.length || policyAlignment.length || confidenceBasis.length || auditGaps.length ? (
                      <div className="mt-2 grid gap-2 lg:grid-cols-2">
                        {[
                          ["Memory", memoryComparison],
                          ["Policy", policyAlignment],
                          ["Basis", confidenceBasis],
                          ["Gaps", auditGaps],
                        ].map(([label, items]) => (
                          <div key={label as string} className="rounded border border-slate-950/25 bg-slate-950/25 p-2">
                            <div className="text-[10px] font-black uppercase tracking-widest opacity-70">{label as string}</div>
                            <div className="mt-1.5 space-y-1">
                              {(items as string[]).slice(0, 3).map((item) => (
                                <div key={item} className="rounded bg-slate-950/35 px-2 py-1 text-[11px] font-bold leading-relaxed opacity-90">
                                  {item}
                                </div>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : null}
                    {answer?.citations?.length ? (
                      <div className="mt-2 flex flex-wrap gap-2">
                        {answer.citations.slice(0, 6).map((item) => (
                          <span key={`${item.kind}-${item.id}-${item.label}`} className="rounded border border-slate-950/25 bg-slate-950/30 px-2 py-1 text-[10px] font-black uppercase tracking-normal opacity-80">
                            {item.kind ?? "evidence"}: {item.id ?? item.label ?? "--"}
                          </span>
                        ))}
                      </div>
                    ) : null}
                    <p className="mt-2 text-[10px] font-bold leading-relaxed opacity-70">{answer?.scope}</p>
                  </div>
                );
              })}
              {isAuditAgentLoading ? (
                <div className="max-w-[72%] rounded-lg border border-violet-400/25 bg-violet-950/20 px-3 py-2 text-sm font-bold text-violet-100">
                  Reading the case packet and conversation history...
                </div>
              ) : null}
            </div>
          </div>
        </section>

        <section className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-5 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-emerald-300">Case evals</div>
                <h2 className="mt-1 text-xl font-black text-slate-100">Operational cases ranked by eval score</h2>
              </div>
              <StatusPill value={cases?.status ?? monitor?.overall_status} />
            </div>
            <div className="mt-4 overflow-hidden rounded border border-slate-800">
              <div className="grid grid-cols-[1fr_5rem_5rem_5rem] gap-2 border-b border-slate-800 bg-slate-950 px-3 py-2 text-[10px] font-black uppercase tracking-widest text-slate-500">
                <div>Case</div>
                <div>Eval</div>
                <div>Priority</div>
                <div>Gate</div>
              </div>
              <div className="max-h-[420px] overflow-auto">
                {caseRows.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setSelectedCaseId(item.id ?? "")}
                    className={`grid w-full grid-cols-[1fr_5rem_5rem_5rem] gap-2 border-b border-slate-800 px-3 py-3 text-left text-xs transition hover:bg-slate-800/60 ${
                      selectedCase?.id === item.id ? "bg-cyan-950/30" : "bg-slate-900"
                    }`}
                  >
                    <div className="min-w-0">
                      <div className="truncate font-black text-slate-100">{item.title ?? item.id}</div>
                      <div className="mt-1 truncate text-[10px] font-bold text-slate-500">{item.id}</div>
                    </div>
                    <div className="font-black text-cyan-100">{score(item.quality?.score, 1)}</div>
                    <div className="font-black text-slate-300">{item.priority?.score ?? "--"}</div>
                    <div><StatusPill value={item.severity} /></div>
                  </button>
                ))}
                {!caseRows.length ? <div className="p-4 text-sm text-slate-500">No case eval rows returned.</div> : null}
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-cyan-300">Selected case</div>
                <h2 className="mt-1 text-xl font-black text-slate-100">{selectedCase?.title ?? "No case selected"}</h2>
              </div>
              <StatusPill value={selectedCase?.governance?.allowedSurface ?? selectedCase?.severity} />
            </div>
            <div className="mt-4 grid gap-2 md:grid-cols-4 xl:grid-cols-8">
              {[
                ["Eval", score(selectedCase?.quality?.score, 1)],
                ["Quality", fmt(selectedCase?.quality?.status)],
                ["Feeds", fmt(selectedCase?.productionEvidence?.feedCount)],
                ["Rank", fmt(selectedCase?.priority?.rank)],
                ["Trace IDs", fmt(selectedTraceCount)],
                ["Policy refs", fmt(selectedPolicyRefCount)],
                ["Direct links", fmt(explicitLinkCount)],
                ["Inferred", fmt(inferredLinkCount)],
              ].map(([label, value]) => (
                <div key={label} className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="text-[9px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                  <div className="mt-1 truncate text-sm font-black text-slate-100">{value}</div>
                </div>
              ))}
            </div>
            <div className="mt-4 grid gap-3 lg:grid-cols-2">
              <div className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Next owner action</div>
                <p className="mt-2 text-sm leading-relaxed text-slate-300">{selectedCase?.governance?.nextOwnerAction ?? "No owner action returned."}</p>
              </div>
              <div className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Production evidence</div>
                <p className="mt-2 text-sm leading-relaxed text-slate-300">
                  {selectedCase?.productionEvidence?.state ?? "--"} / {selectedCase?.productionEvidence?.packetHash ?? "packet missing"}
                </p>
              </div>
              <div className="rounded border border-slate-800 bg-slate-950 p-3 lg:col-span-2">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Linked policy evidence</div>
                <p className="mt-2 text-sm leading-relaxed text-slate-300">
                  {selectedEvidence?.policy_refs?.length || selectedPolicyCase
                    ? `${compact(selectedEvidence?.policy_refs ?? selectedPolicyCase?.policy_refs, 4)} / blocked: ${compact(selectedPolicyCase?.blocked_actions, 3)}`
                    : "No direct doctrine case matched this operating case."}
                </p>
              </div>
              <div className="rounded border border-slate-800 bg-slate-950 p-3 lg:col-span-2">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Eval dimensions</div>
                <div className="mt-2 grid gap-2 md:grid-cols-2">
                  {selectedEvalDimensions.slice(0, 6).map((item) => (
                    <div key={item.id ?? item.label} className="rounded bg-slate-900 p-2">
                      <div className="flex items-center justify-between gap-2 text-xs">
                        <span className="truncate font-black text-slate-100">{item.label ?? item.id}</span>
                        <span className="font-black text-cyan-100">{score(item.score)}</span>
                      </div>
                      <div className="mt-1 line-clamp-2 text-[10px] leading-relaxed text-slate-500">{item.detail ?? item.status ?? "--"}</div>
                    </div>
                  ))}
                  {!selectedEvalDimensions.length ? <div className="text-xs text-slate-500 md:col-span-2">No dimension-level eval evidence returned.</div> : null}
                </div>
              </div>
              <div className="rounded border border-slate-800 bg-slate-950 p-3 lg:col-span-2">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Evidence relationship IDs</div>
                <div className="mt-2 grid gap-2 text-xs text-slate-300 md:grid-cols-4">
                  <div className="rounded bg-slate-900 p-2"><span className="text-slate-500">Case</span><br />{selectedEvidence?.case_id ?? selectedCase?.id ?? "--"}</div>
                  <div className="rounded bg-slate-900 p-2"><span className="text-slate-500">Trace</span><br />{compact(selectedEvidence?.trace_ids, 1)}</div>
                  <div className="rounded bg-slate-900 p-2"><span className="text-slate-500">Review</span><br />{compact(selectedEvidence?.review_session_ids, 1)}</div>
                  <div className="rounded bg-slate-900 p-2"><span className="text-slate-500">Policy</span><br />{compact(selectedEvidence?.policy_refs, 1)}</div>
                </div>
                <div className="mt-2 text-[10px] font-bold leading-relaxed text-slate-500">
                  {selectedEvidence?.relationship_contract?.semantic_threshold ?? "Direct case IDs are preferred; inferred links require stronger evidence overlap."}
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-5 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <div className="min-w-0 rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <div className="text-[10px] font-black uppercase tracking-widest text-violet-300">Trace records</div>
                <h2 className="mt-1 text-xl font-black text-slate-100">Related receipts and tool traces</h2>
              </div>
              <StatusPill value={agentOps?.status} />
            </div>
            <div className="mt-4 grid max-h-[430px] min-w-0 gap-2 overflow-y-auto overflow-x-hidden">
              {orderedReceipts.slice(0, 18).map(({ item, relationScore }) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setSelectedReceiptId(item.id ?? "")}
                  className={`min-w-0 max-w-full rounded border p-3 text-left transition hover:border-violet-300 ${
                    selectedReceipt?.id === item.id ? "border-violet-300 bg-violet-950/30" : "border-slate-800 bg-slate-950"
                  }`}
                >
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                    <div className="truncate text-sm font-black text-slate-100">{item.summary ?? item.scenarioName ?? item.id}</div>
                    <div className="flex flex-wrap items-center gap-1 sm:shrink-0">
                      {relationScore > 0 ? <span className="rounded border border-violet-300/40 bg-violet-950/30 px-2 py-1 text-[9px] font-black uppercase tracking-normal text-violet-100">linked {relationScore}</span> : null}
                      <StatusPill value={item.gate ?? item.status} />
                    </div>
                  </div>
                  <div className="mt-2 grid grid-cols-2 gap-2 text-[10px] font-bold text-slate-500 sm:grid-cols-4">
                    <div>{score(item.evalScore)}</div>
                    <div>{fmt(item.mode)}</div>
                    <div>{item.toolCalls?.length ?? 0} tools</div>
                    <div>{item.caseId === selectedCase?.id || graphReceiptIds.has(item.id ?? "") ? "case id" : `${item.dispatchCount ?? 0} dispatches`}</div>
                  </div>
                </button>
              ))}
              {!receipts.length ? <div className="rounded border border-slate-800 bg-slate-950 p-3 text-sm text-slate-500">No trace receipts returned.</div> : null}
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-violet-300">Selected trace</div>
                <h2 className="mt-1 text-xl font-black text-slate-100">{selectedReceipt?.summary ?? selectedReceipt?.id ?? "No receipt selected"}</h2>
              </div>
              <div className="text-right text-[10px] font-bold text-slate-500">{selectedReceipt?.timestamp ?? monitor?.created_at ?? "--"}</div>
            </div>
            <div className="mt-4 grid gap-2 md:grid-cols-5">
              {[
                ["Eval", score(selectedReceipt?.evalScore ?? monitor?.summary?.overall_eval_score)],
                ["Gate", fmt(selectedReceipt?.gate ?? monitor?.overall_status)],
                ["Trace", selectedReceipt?.traceId ?? selectedReceipt?.signature ?? monitor?.gcp_trace_eval?.trace_lookup_query ?? "--"],
                ["GCP", fmt(monitor?.gcp_trace_eval?.status)],
                ["Case link", selectedGraphTrace ? fmt(selectedGraphTrace.relation_confidence ?? selectedGraphTrace.relation_type) : selectedReceipt ? (graphReceiptIds.has(selectedReceipt.id ?? "") || selectedReceipt.caseId === selectedCase?.id ? "explicit" : fmt(receiptRelationScore(selectedReceipt, selectedCaseTerms))) : "--"],
                ["Policy link", compact(selectedGraphTrace?.policy_refs ?? selectedReceipt?.policyRefs, 2)],
              ].map(([label, value]) => (
                <div key={label} className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="text-[9px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                  <div className="mt-1 truncate text-xs font-black text-slate-100">{value}</div>
                </div>
              ))}
            </div>
            <div className="mt-4 grid gap-3 lg:grid-cols-2">
              <div className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Tool calls</div>
                <div className="mt-2 grid gap-1">
                  {(selectedReceipt?.toolCalls ?? []).slice(0, 9).map((call, index) => (
                    <div key={`${call.tool}-${index}`} className="grid grid-cols-[1fr_auto] gap-2 rounded bg-slate-900 px-2 py-1 text-xs">
                      <span className="truncate font-bold text-slate-200">{fmt(call.tool)}</span>
                      <span className="text-slate-500">{fmt(call.status)}</span>
                    </div>
                  ))}
                  {!(selectedReceipt?.toolCalls ?? []).length ? <div className="text-xs text-slate-500">No tool trace attached.</div> : null}
                </div>
              </div>
              <div className="rounded border border-slate-800 bg-slate-950 p-3">
                <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Trace links</div>
                <div className="mt-2 space-y-2 text-xs">
                  {monitor?.gcp_trace_eval?.trace_url ? <a className="block truncate font-bold text-cyan-200 hover:text-cyan-100" href={monitor.gcp_trace_eval.trace_url}>GCP trace: {monitor.gcp_trace_eval.project}</a> : <div className="text-slate-500">GCP trace link not loaded.</div>}
                  {monitor?.arize_monitor?.trace_url ? <a className="block truncate font-bold text-cyan-200 hover:text-cyan-100" href={monitor.arize_monitor.trace_url}>Arize trace: {monitor.arize_monitor.project_name}</a> : <div className="text-slate-500">Arize trace link not loaded.</div>}
                  {monitor?.deep_monitoring?.status === "unavailable" ? <div className="rounded border border-amber-400/30 bg-amber-950/20 p-2 font-bold text-amber-100">{monitor.deep_monitoring.error}</div> : null}
                </div>
              </div>
              <div className="rounded border border-slate-800 bg-slate-950 p-3 lg:col-span-2">
                <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                  <div className="text-[10px] font-black uppercase tracking-widest text-slate-500">Trace to case to policy graph</div>
                  <div className="flex flex-wrap gap-1">
                    {([
                      ["all", "All"],
                      ["direct", "Direct"],
                      ["inferred", "Inferred"],
                      ["review", "Review"],
                      ["blocked", "Blocked"],
                    ] as Array<[TraceFilter, string]>).map(([value, label]) => (
                      <button
                        key={value}
                        type="button"
                        onClick={() => setTraceFilter(value)}
                        className={`rounded border px-2 py-1 text-[9px] font-black uppercase tracking-normal transition ${
                          traceFilter === value ? "border-violet-300 bg-violet-300 text-slate-950" : "border-slate-700 bg-slate-900 text-slate-300 hover:border-violet-300"
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="mt-2 grid gap-1">
                  {visibleTraceRecords.slice(0, 8).map((item) => (
                    <div key={item.receipt_id ?? item.signature} className="grid gap-2 rounded bg-slate-900 px-2 py-2 text-xs md:grid-cols-[minmax(0,1fr)_minmax(8rem,0.8fr)_minmax(10rem,1fr)_auto]">
                      <div className="min-w-0">
                        {item.trace_url ? (
                          <a className="truncate font-bold text-cyan-200 hover:text-cyan-100" href={item.trace_url} target="_blank" rel="noreferrer">
                            {item.trace_id ?? item.signature ?? item.receipt_id}
                          </a>
                        ) : (
                          <span className="block truncate font-bold text-slate-200">{item.trace_id ?? item.signature ?? item.receipt_id}</span>
                        )}
                        <div className="mt-1 truncate text-[10px] font-bold text-slate-500">{fmt(item.policy_link_source)}</div>
                      </div>
                      <div className="min-w-0">
                        <div className="text-[9px] font-black uppercase tracking-widest text-slate-600">Case</div>
                        <div className="mt-1 truncate font-bold text-slate-300">{item.case_id ?? selectedEvidence?.case_id ?? selectedCase?.id ?? "--"}</div>
                      </div>
                      <div className="min-w-0">
                        <div className="text-[9px] font-black uppercase tracking-widest text-slate-600">Policy refs</div>
                        <div className="mt-1 flex flex-wrap gap-1">
                          {(item.policy_refs ?? []).slice(0, 4).map((ref) => (
                            <button
                              key={`${item.receipt_id}-${ref}`}
                              type="button"
                              onClick={() => void loadPolicyRef(ref)}
                              className="rounded border border-lime-300/30 bg-lime-950/20 px-1.5 py-0.5 text-[9px] font-black uppercase tracking-normal text-lime-100 transition hover:border-lime-300"
                            >
                              {ref}
                            </button>
                          ))}
                          {!(item.policy_refs ?? []).length ? <span className="text-slate-500">--</span> : null}
                        </div>
                        <div className="mt-2 grid gap-1">
                          {(item.policy_ref_rows ?? []).slice(0, 2).map((refRow) => (
                            <button
                              key={`${item.receipt_id}-${refRow.policy_ref}-rule`}
                              type="button"
                              onClick={() => refRow.policy_ref && void loadPolicyRef(refRow.policy_ref)}
                              className="rounded border border-slate-800 bg-slate-950 p-2 text-left transition hover:border-lime-300/60"
                            >
                              <div className="truncate text-[10px] font-black text-lime-100">{refRow.title ?? refRow.policy_ref}</div>
                              <div className="mt-1 line-clamp-2 text-[10px] leading-relaxed text-slate-500">{refRow.condition ?? refRow.summary ?? "--"}</div>
                            </button>
                          ))}
                        </div>
                      </div>
                      <div className="flex items-center justify-end gap-2">
                        <span className="text-slate-500">{fmt(item.case_link_source ?? item.relation_confidence ?? item.relation_type)}</span>
                        <span className="text-cyan-100">{score(item.eval_score)}</span>
                      </div>
                    </div>
                  ))}
                  {!(selectedEvidence?.trace_records ?? []).length ? <div className="text-xs text-slate-500">No graph trace records linked to this case.</div> : null}
                  {(selectedEvidence?.trace_records ?? []).length && !visibleTraceRecords.length ? <div className="text-xs text-slate-500">No trace records match this filter.</div> : null}
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-5 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <div className="min-w-0 rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <div className="text-[10px] font-black uppercase tracking-widest text-amber-300">Human review</div>
                <h2 className="mt-1 text-xl font-black text-slate-100">Review state for selected case</h2>
              </div>
              <StatusPill value={reviewLedger?.status ?? monitor?.overall_status} />
            </div>
            <div className="mt-3 grid gap-2 md:grid-cols-3">
              {[
                ["Direct review links", fmt(directReviewLinkCount)],
                ["Inferred review links", fmt(inferredReviewLinkCount)],
                ["Review source", directReviewLinkCount ? "case id" : inferredReviewLinkCount ? "semantic policy gate" : "none"],
              ].map(([label, value]) => (
                <div key={label} className="rounded border border-slate-800 bg-slate-950 p-2">
                  <div className="text-[9px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                  <div className="mt-1 truncate text-xs font-black text-amber-100">{value}</div>
                </div>
              ))}
            </div>
            {reviewLedger?.readiness_issues?.length ? (
              <div className="mt-3 rounded border border-amber-400/30 bg-amber-950/15 p-3 text-xs font-bold text-amber-100">
                {reviewLedger.authorization?.reason ?? reviewLedger.readiness_issues[0]}
              </div>
            ) : null}
            <div className="mt-4 grid min-w-0 gap-2">
              {selectedReviewRows.slice(0, 8).map((item) => (
                <div key={item?.id} className="min-w-0 overflow-hidden rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                    <div className="min-w-0 truncate text-sm font-black text-slate-100">{item?.reason ?? item?.id}</div>
                    <StatusPill value={item?.status ?? item?.disposition?.decision} />
                  </div>
                  <div className="mt-1 break-words text-xs text-slate-500">{item?.owner ?? "--"} / {item?.priority ?? "--"} / {item?.event?.source ?? "--"}</div>
                </div>
              ))}
              {!selectedReviewRows.length ? (
                <div className="rounded border border-slate-800 bg-slate-950 p-3 text-sm text-slate-500">
                  {reviewAccessBlocked ? "Signed review ledger is auth gated. Governance review evidence is shown on the right." : "No active human review sessions returned."}
                </div>
              ) : null}
            </div>
          </div>

          <div className="min-w-0 rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="text-[10px] font-black uppercase tracking-widest text-amber-300">Related governance queue</div>
            <div className="mt-3 grid gap-2 md:grid-cols-2">
              {visibleGovernanceReviews.slice(0, 10).map((item) => (
                <div key={item.id} className="min-w-0 overflow-hidden rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                    <div className="min-w-0 truncate text-sm font-black text-slate-100">{item.title}</div>
                    <StatusPill value={item.status} />
                  </div>
                  <div className="mt-2 line-clamp-2 text-xs leading-relaxed text-slate-500">{item.owner ?? "--"} / {item.detail ?? "--"}</div>
                </div>
              ))}
              {!visibleGovernanceReviews.length ? <div className="rounded border border-slate-800 bg-slate-950 p-3 text-sm text-slate-500 md:col-span-2">No governance review evidence returned for this case.</div> : null}
            </div>
          </div>
        </section>

        <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <div className="text-[10px] font-black uppercase tracking-widest text-lime-300">Policy lookup</div>
              <h2 className="mt-1 text-xl font-black text-slate-100">Doctrine, refs, blocked actions</h2>
            </div>
            <input
              value={policyQuery}
              onChange={(event) => setPolicyQuery(event.target.value)}
              placeholder="Search policy refs, cases, triggers"
              className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm font-bold text-slate-100 outline-none transition placeholder:text-slate-600 focus:border-lime-300 lg:w-96"
            />
          </div>
          <div className="mt-4 grid gap-5 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
            <div className="grid max-h-[460px] gap-2 overflow-auto">
              {filteredPolicyCases.slice(0, 18).map((item) => (
                <div key={item.id} className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="truncate text-sm font-black text-slate-100">{item.title ?? item.id}</div>
                    <div className="flex shrink-0 flex-wrap justify-end gap-1">
                      {(item.policy_refs ?? []).slice(0, 3).map((ref) => (
                        <button
                          key={ref}
                          type="button"
                          onClick={() => void loadPolicyRef(ref)}
                          className={`rounded border px-2 py-1 text-[9px] font-black uppercase tracking-normal transition ${
                            selectedPolicyRef === ref ? "border-lime-300 bg-lime-300 text-slate-950" : "border-lime-300/30 bg-lime-950/20 text-lime-100 hover:border-lime-300"
                          }`}
                        >
                          {ref}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="mt-2 text-xs leading-relaxed text-slate-500">Triggers: {compact(item.triggers, 4)}</div>
                  <div className="mt-2 grid gap-2 md:grid-cols-2">
                    <div className="rounded bg-slate-900 p-2 text-xs text-slate-300">Plan: {compact(item.action_plan, 2)}</div>
                    <div className="rounded bg-slate-900 p-2 text-xs text-amber-100">Blocked: {compact(item.blocked_actions, 2)}</div>
                  </div>
                </div>
              ))}
              {!filteredPolicyCases.length ? <div className="rounded border border-slate-800 bg-slate-950 p-3 text-sm text-slate-500">No policy cases match.</div> : null}
            </div>
            <div className="rounded border border-slate-800 bg-slate-950 p-3">
              <div className="grid gap-2 md:grid-cols-3">
                {[
                  ["Books", fmt(doctrine?.policy_book_count ?? monitor?.summary?.policy_book_count)],
                  ["Cases", fmt(doctrine?.action_case_count ?? policyCases.length)],
                  ["Refs", fmt(monitor?.policy_integrity?.policy_ref_count ?? policyRefs.length)],
                ].map(([label, value]) => (
                  <div key={label} className="rounded bg-slate-900 p-2">
                    <div className="text-[9px] font-black uppercase tracking-widest text-slate-500">{label}</div>
                    <div className="mt-1 text-sm font-black text-slate-100">{value}</div>
                  </div>
                ))}
              </div>
              <div className="mt-3 text-xs leading-relaxed text-slate-400">
                Integrity: <span className="font-black text-slate-200">{fmt(monitor?.policy_integrity?.status)}</span>
              </div>
              <div className="mt-3 grid gap-2">
                {(filteredPolicyRefs.length ? filteredPolicyRefs : (monitor?.policy_index?.absolute_prohibitions ?? []).map<PolicyRefRow>((item) => ({ policy_ref: item, summary: "Absolute prohibition" }))).slice(0, 12).map((item) => (
                  <button
                    key={`${item.policy_ref}-${item.title}`}
                    type="button"
                    onClick={() => item.policy_ref && void loadPolicyRef(item.policy_ref)}
                    className={`rounded border p-2 text-left text-xs transition ${
                      selectedPolicyRef === item.policy_ref ? "border-lime-300 bg-lime-950/30" : "border-slate-800 bg-slate-900 hover:border-lime-300/60"
                    }`}
                  >
                    <div className="font-black text-lime-100">{item.policy_ref ?? item.policy_book_id ?? item.title}</div>
                    <div className="mt-1 line-clamp-2 text-slate-500">{item.summary ?? item.title ?? "--"}</div>
                  </button>
                ))}
                {monitor?.policy_integrity?.issues?.slice(0, 3).map((item) => (
                  <div key={item} className="rounded border border-amber-400/30 bg-amber-950/15 p-2 text-xs font-bold text-amber-100">{item}</div>
                ))}
              </div>
              <div className="mt-4 rounded border border-slate-800 bg-slate-900 p-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-[10px] font-black uppercase tracking-widest text-lime-300">Selected rule text</div>
                  <StatusPill value={activePolicyRefDetail?.status ?? (activePolicyRef ? "from graph" : "not loaded")} />
                </div>
                <div className="mt-2 text-sm font-black text-slate-100">{activePolicyRefDetail?.policy_ref ?? (activePolicyRef || "No policy ref selected")}</div>
                {(activePolicyRefDetail?.matches ?? []).slice(0, 2).map((item, index) => (
                  <div key={`${item.policy_book_id}-${item.title}-${index}`} className="mt-3 rounded bg-slate-950 p-3 text-xs">
                    <div className="font-black text-lime-100">{item.title ?? item.kind}</div>
                    <div className="mt-2 leading-relaxed text-slate-400">Condition: {item.condition ?? item.summary ?? "--"}</div>
                    <div className="mt-2 leading-relaxed text-emerald-100">Allowed: {item.allowed_action ?? "--"}</div>
                    <div className="mt-2 leading-relaxed text-amber-100">Blocked: {item.blocked_action ?? "--"}</div>
                    <div className="mt-2 leading-relaxed text-slate-500">Evidence: {compact(item.required_evidence, 5)}</div>
                    <div className="mt-1 leading-relaxed text-slate-500">Human review: {compact(item.human_review_if, 3)}</div>
                  </div>
                ))}
                <div className="mt-3 grid gap-2">
                  {(activePolicyRefDetail?.related_cases ?? []).slice(0, 4).map((item) => (
                    <div key={item.id} className="rounded bg-slate-950 p-2 text-xs">
                      <div className="font-black text-slate-100">{item.title ?? item.id}</div>
                      <div className="mt-1 line-clamp-2 text-slate-500">Blocked: {compact(item.blocked_actions, 3)} / Success: {item.success_metric ?? "--"}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
