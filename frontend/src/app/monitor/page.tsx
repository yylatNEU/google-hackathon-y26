"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchParkPulseApi, getApiUrls } from "@/lib/api";

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

async function readJson<T>(path: string, init?: ApiRequestInit): Promise<T | null> {
  try {
    const response = await fetchParkPulseApi(path, init);
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

export default function MonitorPage() {
  const [monitor, setMonitor] = useState<MonitorData | null>(null);
  const [cases, setCases] = useState<CaseIndex | null>(null);
  const [agentOps, setAgentOps] = useState<AgentOpsLedger | null>(null);
  const [reviewLedger, setReviewLedger] = useState<ReviewLedger | null>(null);
  const [policyDoctrine, setPolicyDoctrine] = useState<PolicyDoctrine | null>(null);
  const [monitorEvidence, setMonitorEvidence] = useState<MonitorEvidenceGraph | null>(null);
  const [selectedPolicyRef, setSelectedPolicyRef] = useState("");
  const [policyRefDetail, setPolicyRefDetail] = useState<PolicyRefDetail | null>(null);
  const [selectedCaseId, setSelectedCaseId] = useState("");
  const [selectedReceiptId, setSelectedReceiptId] = useState("");
  const [traceFilter, setTraceFilter] = useState<TraceFilter>("all");
  const [policyQuery, setPolicyQuery] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isDeepLoading, setIsDeepLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const workspaceRequestRef = useRef(0);
  const secondaryRequestRef = useRef(0);
  const policyDetailRequestRef = useRef(0);

  const loadSecondaryEvidence = useCallback(async () => {
    const requestId = secondaryRequestRef.current + 1;
    secondaryRequestRef.current = requestId;
    const nextAgentOps = await readJson<AgentOpsLedger>("/api/park/agent-ops-ledger?limit=30", { timeoutMs: 5000 });
    if (secondaryRequestRef.current !== requestId) return;
    if (nextAgentOps) setAgentOps(nextAgentOps);
  }, []);

  const loadWorkspace = useCallback(async (depth: "summary" | "deep" = "summary") => {
    const requestId = workspaceRequestRef.current + 1;
    workspaceRequestRef.current = requestId;
    setIsLoading(true);
    setError(null);
    const monitorPath = depth === "deep" ? "/api/park/agent-monitoring/deep" : "/api/park/agent-monitoring";
    try {
      const [nextMonitor, nextCases, nextPolicyDoctrine, nextMonitorEvidence] = await Promise.all([
        readJson<MonitorData>(monitorPath, { timeoutMs: depth === "deep" ? 15000 : 8000 }),
        readJson<CaseIndex>("/api/park/cases", { timeoutMs: 8000 }),
        readJson<PolicyDoctrine>("/api/park/policy-doctrine", { timeoutMs: 5000 }),
        readJson<MonitorEvidenceGraph>("/api/park/monitor-evidence?limit=40", { timeoutMs: 8000 }),
      ]);
      if (workspaceRequestRef.current !== requestId) return;
      if (nextMonitor) setMonitor(nextMonitor);
      if (nextCases) setCases(nextCases);
      if (nextPolicyDoctrine) setPolicyDoctrine(nextPolicyDoctrine);
      if (nextMonitorEvidence) setMonitorEvidence(nextMonitorEvidence);
      if (!nextMonitor && !nextCases && !nextPolicyDoctrine && !nextMonitorEvidence) setError("Monitor evidence APIs did not return usable payloads.");
      void loadSecondaryEvidence();
    } finally {
      if (workspaceRequestRef.current === requestId) setIsLoading(false);
    }
  }, [loadSecondaryEvidence]);

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
                onClick={() => void loadDeepMonitor()}
                disabled={isDeepLoading}
                className="rounded border border-cyan-300 bg-cyan-300 px-3 py-2 text-xs font-black text-slate-950 transition hover:bg-cyan-200 disabled:opacity-50"
              >
                {isDeepLoading ? "Loading trace" : "Load trace links"}
              </button>
              <a href="/" className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-black text-slate-200 transition hover:border-cyan-400 hover:text-cyan-100">
                Operating loop
              </a>
            </div>
          </div>
        </header>

        {error ? <section className="rounded border border-amber-400/30 bg-amber-950/15 p-3 text-sm font-bold text-amber-100">Runtime debug: {error}</section> : null}

        <section className="grid gap-2 md:grid-cols-6">
          {[
            ["Cases", String((cases?.summary?.caseCount ?? caseRows.length) || "--")],
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

        <section className="grid gap-5 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
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

        <section className="grid gap-5 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[10px] font-black uppercase tracking-widest text-violet-300">Trace records</div>
                <h2 className="mt-1 text-xl font-black text-slate-100">Related receipts and tool traces</h2>
              </div>
              <StatusPill value={agentOps?.status} />
            </div>
            <div className="mt-4 grid max-h-[430px] gap-2 overflow-auto">
              {orderedReceipts.slice(0, 18).map(({ item, relationScore }) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setSelectedReceiptId(item.id ?? "")}
                  className={`rounded border p-3 text-left transition hover:border-violet-300 ${
                    selectedReceipt?.id === item.id ? "border-violet-300 bg-violet-950/30" : "border-slate-800 bg-slate-950"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="truncate text-sm font-black text-slate-100">{item.summary ?? item.scenarioName ?? item.id}</div>
                    <div className="flex shrink-0 items-center gap-1">
                      {relationScore > 0 ? <span className="rounded border border-violet-300/40 bg-violet-950/30 px-2 py-1 text-[9px] font-black uppercase tracking-normal text-violet-100">linked {relationScore}</span> : null}
                      <StatusPill value={item.gate ?? item.status} />
                    </div>
                  </div>
                  <div className="mt-2 grid grid-cols-4 gap-2 text-[10px] font-bold text-slate-500">
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

        <section className="grid gap-5 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
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
            <div className="mt-4 grid gap-2">
              {selectedReviewRows.slice(0, 8).map((item) => (
                <div key={item?.id} className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="truncate text-sm font-black text-slate-100">{item?.reason ?? item?.id}</div>
                    <StatusPill value={item?.status ?? item?.disposition?.decision} />
                  </div>
                  <div className="mt-1 text-xs text-slate-500">{item?.owner ?? "--"} / {item?.priority ?? "--"} / {item?.event?.source ?? "--"}</div>
                </div>
              ))}
              {!selectedReviewRows.length ? (
                <div className="rounded border border-slate-800 bg-slate-950 p-3 text-sm text-slate-500">
                  {reviewAccessBlocked ? "Signed review ledger is auth gated. Governance review evidence is shown on the right." : "No active human review sessions returned."}
                </div>
              ) : null}
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <div className="text-[10px] font-black uppercase tracking-widest text-amber-300">Related governance queue</div>
            <div className="mt-3 grid gap-2 md:grid-cols-2">
              {visibleGovernanceReviews.slice(0, 10).map((item) => (
                <div key={item.id} className="rounded border border-slate-800 bg-slate-950 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="truncate text-sm font-black text-slate-100">{item.title}</div>
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
