export type EvalScore = {
  label: string;
  score: number;
  detail: string;
};

export type AgentBrief = {
  name: string;
  department?: string;
  departmentLabel?: string;
  departmentAgent?: string;
  signal: string;
  finding: string;
  recommendation?: string;
  role?: string;
  confidence?: number;
  policyRefs?: string[];
  traceSpan?: string;
  source?: "runtime" | "scenario" | "live";
  tone: "risk" | "watch" | "ok";
};

export type RuntimeAgentFinding = {
  agent?: string;
  agent_id?: string;
  name?: string;
  department?: string;
  department_label?: string;
  department_agent?: string;
  loop?: string[];
  role?: string;
  mode?: string;
  input_signals?: string[];
  finding?: string;
  recommendation?: string;
  urgency?: "risk" | "watch" | "ok";
  confidence?: number;
  policy_refs?: string[];
  trace_span?: string;
};

export type AgentTopology = {
  name?: string;
  pattern?: string;
  lifecycle_pattern?: string;
  department_system?: {
    loop?: string[];
    active_departments?: string[];
    active_department_count?: number;
    conflict_resolver?: string;
    policy_judge?: string;
    eval_judge?: string;
    tool_contract_required_fields?: string[];
    departments?: Array<{
      department?: string;
      label?: string;
      canonical_agent?: string;
      implementation_agents?: string[];
      main_job?: string;
      tool_families?: string[];
      read_tools?: string[];
      write_action_tools?: string[];
    }>;
    layers?: string[];
    conflict_resolution?: string[];
  };
  groups?: unknown[];
  specialists?: unknown[];
  agent_groups?: Array<{
    id?: string;
    label?: string;
    purpose?: string;
    operating_question?: string;
    modes?: string[];
    agents?: string[];
    active_agents?: string[];
    active_agent_count?: number;
    primary_outputs?: string[];
    activation?: string;
    success_metrics?: string[];
    status?: string;
  }>;
  lifecycle_artifact?: Array<{
    group_id?: string;
    label?: string;
    inputs?: string[];
    decision?: string;
    output?: string;
    measured_result?: string;
    status?: string;
    active_agent_count?: number;
  }>;
  phases?: Array<{
    id?: string;
    label?: string;
    purpose?: string;
    agents?: string[];
    active_agents?: string[];
    outputs?: string[];
    status?: string;
    evidence_count?: number;
  }>;
  handoffs?: Array<{ from?: string; to?: string; artifact?: string; status?: string }>;
  conflicts?: Array<{ conflict?: string; agents?: string[]; resolution?: string; status?: string }>;
  gates?: Array<{ gate?: string; owner?: string; status?: string; rule?: string }>;
  logic_graph?: {
    id?: string;
    label?: string;
    purpose?: string;
    decision_layers?: Array<{
      id?: string;
      label?: string;
      question?: string;
      agents?: string[];
      evidence?: string[];
      updates?: string[];
      status?: string;
      evidence_count?: number;
    }>;
    audit_agent?: {
      agent_id?: string;
      checks?: string[];
      update_rule?: string;
      status?: string;
      last_update?: string;
    };
    animation_path?: Array<{ from?: string; to?: string; reaction?: string }>;
  };
  eval_dimensions?: string[];
};

export type AgentRoleSkill = {
  id?: string;
  name?: string;
  skill?: string;
  mode?: "scan" | "react" | "proact" | string;
  purpose?: string;
  trigger_examples?: string[];
  mcp_tools?: string[];
  api_surfaces?: string[];
  output_artifacts?: string[];
  permissions?: Record<string, unknown>;
  policy_gates?: string[];
};

export type AgentRoleRoute = {
  selected_role?: "scan" | "react" | "proact" | string;
  skill?: string;
  why?: string;
  required_tools?: string[];
  policy_gates?: string[];
  expected_receipt?: string[];
};

export type AgentRoleSkillsRegistry = {
  server?: string;
  style?: string;
  principle?: string;
  roles?: AgentRoleSkill[];
  route?: AgentRoleRoute;
  routing_order?: string[];
  proof?: {
    skill_paths?: string[];
    digital_twin_tool_registry?: string;
  };
};

export type IntegrationStatus = {
  gemini?: { ready?: boolean; platform?: string; model?: string; provider?: string };
  gcp_trace_eval?: {
    ready?: boolean;
    platform?: string;
    project?: string;
    dataset?: string;
    mode?: string;
    primary_path?: string;
    trace?: {
      runtime?: string;
      sink?: string;
      url_template?: string;
      export_configured?: boolean;
    };
    evaluation?: {
      local_scorecards_enabled?: boolean;
      hosted_judge_configured?: boolean;
      hosted_judge_status?: string;
      hosted_evaluator_id?: string | null;
      judge_runtime?: string;
      note?: string;
      continuous_monitoring?: {
        configured?: boolean;
        sampling_rate?: string;
        status?: string;
      };
    };
  };
  arize?: {
    ready?: boolean;
    project_name?: string;
    platform?: string;
    evaluation?: {
      local_scorecards_enabled?: boolean;
      hosted_judge_configured?: boolean;
      hosted_judge_status?: string;
      hosted_evaluator_id?: string | null;
      judge_runtime?: string;
      note?: string;
    };
  };
  gcp_operations?: GcpOperationsStatus;
  mongo?: { connected?: boolean; mode?: string; database?: string };
  bigquery?: BigQueryIntegrationStatus;
  agent_roles?: Array<{ agent_id?: string; name?: string; mode?: string[] }>;
  agent_topology?: AgentTopology;
  role_alignment?: { status?: string; agent_count?: number; phase_count?: number; handoff_count?: number; runtime_contract?: string };
  latest_decision_id?: string;
  latest_eval_id?: string;
  latest_outcome_id?: string;
};

export type GcpLiveReadinessStatus = {
  status?: "live_ready" | "wired_not_live" | string;
  checked_at?: string;
  summary?: {
    live?: number;
    mocked?: number;
    skipped?: number;
    required_live_ready?: boolean;
    required_live_checks?: string[];
  };
  judge_agent?: {
    agent_id?: string;
    department?: string;
    exclusive_tools?: string[];
    routing_rule?: string;
  };
  checks?: Record<
    string,
    {
      name?: string;
      ready?: boolean;
      proof_mode?: "live" | "mocked" | "skipped" | string;
      details?: Record<string, unknown>;
      readiness_issues?: string[];
    }
  >;
  readiness_issues?: string[];
  env_gates?: Record<string, boolean>;
};

export type OperatingLoopResilienceStatus = {
  status?: "passed" | "passed_with_conditions" | "failed" | string;
  mode?: string;
  generated_at?: string;
  decision?: "allow_loop_claim" | "allow_with_conditions" | "block_loop_claim" | string;
  summary?: {
    status?: string;
    score?: number;
    check_count?: number;
    failed_count?: number;
    critical_failed_count?: number;
    critical_failures?: string[];
    conditions?: string[];
  };
  artifact?: {
    status?: string;
    path?: string;
    reason?: string;
  };
  sections?: Record<
    string,
    Array<{
      name?: string;
      status?: string;
      passed?: boolean;
      critical?: boolean;
      issue?: string;
      evidence?: Record<string, unknown>;
    }>
  >;
  principles?: Record<string, string>;
};

export type GcpOperationsStatus = {
  platform?: string;
  project?: string | null;
  pubsub?: { enabled?: boolean; ready?: boolean; topic?: string | null; eventarc_endpoint?: string };
  workflows?: { enabled?: boolean; ready?: boolean; workflow_id?: string | null; location?: string };
  fcm?: { enabled?: boolean; ready?: boolean; guest_topic?: string; worker_topic?: string };
  firestore?: {
    enabled?: boolean;
    ready?: boolean;
    project?: string | null;
    collections?: { dispatches?: string; approvals?: string; events?: string };
    mirror?: { ready?: boolean; path?: string; count?: number; error?: string | null };
    error?: string | null;
  };
  agent_builder?: {
    enabled?: boolean;
    ready?: boolean;
    project?: string | null;
    location?: string;
    resource?: string | null;
    registry_status?: string;
    agent_count?: number;
    tool_count?: number;
    runtime?: string;
  };
  dataflow?: {
    enabled?: boolean;
    ready?: boolean;
    project?: string | null;
    location?: string;
    job_name?: string;
    template?: string | null;
    source_topic?: string;
    sinks?: { bigquery?: string; firestore?: string };
    mirror?: { ready?: boolean; path?: string; count?: number; error?: string | null };
  };
};

export type VertexAgentBuilderRegistryResponse = {
  status?: string;
  platform?: string;
  resource?: string | null;
  location?: string;
  principle?: string;
  agents?: Array<{
    id?: string;
    name?: string;
    mode?: string[];
    role?: string;
    tools?: string[];
    allowed_tools?: string[];
    blocked_tools?: string[];
    responsibilities?: string[];
    decision_rights?: string[];
    policy_refs?: string[];
    handoff_to?: string;
    execution_boundary?: string;
    requires_human_approval_when?: string[];
    agent_builder_fit?: string;
  }>;
  tool_registry?: string[];
  blocked_tool_registry?: string[];
  handoff_rules?: string[];
  runtime_enforcement?: {
    pre_tool_call?: string;
    pre_dispatch?: string;
    post_dispatch?: string;
  };
  governance?: {
    agent_identity?: string;
    observability?: string;
    registry?: string;
    runtime_protection?: string;
  };
};

export type DataflowStreamContract = {
  name?: string;
  platform?: string;
  sources?: string[];
  transforms?: string[];
  sinks?: string[];
  template_type?: string;
};

export type DataflowStreamEvent = {
  id?: string;
  createdAt?: string;
  eventType?: string;
  attributes?: Record<string, string>;
  payload?: Record<string, unknown>;
  pipeline?: string;
};

export type DataflowStatusResponse = NonNullable<GcpOperationsStatus["dataflow"]> & {
  contract?: DataflowStreamContract;
};

export type DataflowEventsResponse = {
  status?: string;
  count?: number;
  event_type?: string | null;
  events?: DataflowStreamEvent[];
  contract?: DataflowStatusResponse;
};

export type GcpDeliveryResult = {
  status?: string;
  provider?: string;
  reason?: string;
  event_type?: string;
  topic?: string;
  message_id?: string;
  name?: string;
  workflow?: string;
  execution?: string;
  durable?: boolean;
  endpoint?: string;
  durabilityError?: string;
  http_status?: number;
};

export type PseudoFirebaseMessage = {
  id?: string;
  createdAt?: string;
  provider?: "pseudo_firebase" | string;
  topic?: string;
  notification?: { title?: string; body?: string };
  data?: Record<string, string>;
  dispatchId?: string;
  channel?: "guest_app" | "worker_device" | string;
  targetSystem?: string;
  payload?: Record<string, unknown>;
  status?: string;
};

export type PseudoFirebaseMessagesResponse = {
  status?: string;
  count?: number;
  topic?: string | null;
  messages?: PseudoFirebaseMessage[];
  contract?: {
    provider?: string;
    guest_topic?: string;
    worker_topic?: string;
  };
};

export type GcpParkEventPublishResult = {
  status?: string;
  reason?: string;
  event_type?: string;
  topic?: string;
  message_id?: string;
};

export type GcpSignalProofReceipt = {
  status?: "running" | "complete" | "partial" | "failed";
  startedAt?: string;
  marker?: string;
  publish?: GcpParkEventPublishResult;
  newMessages?: PseudoFirebaseMessage[];
  stages?: Array<{
    id?: "pubsub" | "eventarc" | "agent" | "pseudo_firebase" | string;
    label?: string;
    status?: "pending" | "running" | "confirmed" | "failed" | "skipped" | string;
    detail?: string;
    artifact?: string;
  }>;
};

export type DeliveryOutboxResponse = {
  count?: number;
  dispatches?: DeliveryDispatch[];
  summary?: DeliveryTelemetry["summary"];
  response?: DeliveryTelemetry["response"];
  durability?: {
    mode?: string;
    memory_depth?: number;
    durable_count?: number;
    path?: string;
    ready?: boolean;
    error?: string | null;
  };
};

export type WorkflowApprovalStatus = {
  status?: "idle" | "created" | "approved" | "held" | "failed" | string;
  message?: string;
  dispatch?: DeliveryDispatch;
};

export type BigQueryIntegrationStatus = {
  ready?: boolean;
  enabled?: boolean;
  mode?: string;
  project?: string;
  dataset?: string;
  role?: string;
  readiness_issues?: string[];
  tables?: Array<{ name?: string; purpose?: string; agent_use?: string }>;
  agent_operation_fit?: string[];
};

export type ScenarioKey = "ride_down" | "staff_shortage" | "food_spike" | "storm_response";
export type SimulationKind = "ride_failure" | "demand_spike" | "food_spike" | "food_demand_surge" | "staff_callout" | "energy_spike" | "storm_risk" | "weather_alert";
export type PolicyArea = "Safety" | "Operations" | "Experience" | "Customer Care";

export type DeliveryResponse = {
  state?: string;
  choice?: string;
  takeRate?: number;
  positiveResponseRate?: number;
  reactiveFollowThroughRate?: number;
  sampleSize?: number;
  acceptedCount?: number;
  followThroughCount?: number;
  acknowledgedCount?: number;
  medianAckSeconds?: number;
  applied?: boolean;
  signal?: string;
};

export type DeliveryDispatch = {
  id?: string;
  revision?: boolean;
  channel?: "guest_app" | "worker_device" | "equipment_controller" | string;
  targetSystem?: string;
  endpoint?: string;
  status?: string;
  payload?: {
    message?: string;
    task?: string;
    command?: string;
    targetZone?: string;
    routingTargets?: string[];
    zones?: string[];
    promotion?: { offer?: string; type?: string };
    targetMix?: Array<{ destination?: string; destinationId?: string; share?: number; currentWaitMins?: number }>;
    holdShare?: number;
    estimatedMovedGuests?: number;
  };
  response?: DeliveryResponse;
  gcpDelivery?: {
    pubsub?: GcpDeliveryResult;
    fcm?: GcpDeliveryResult;
    workflow?: GcpDeliveryResult;
    firestore?: GcpDeliveryResult;
    dataflow?: GcpDeliveryResult;
    status?: string;
    reason?: string;
  };
  approvalDecision?: {
    approved?: boolean;
    held_for_review?: boolean;
    decision?: "approved" | "held_for_review" | string;
    actor?: string;
    reason?: string;
    channel?: string;
    decidedAt?: string;
  };
  approvalDelivery?: {
    pubsub?: GcpDeliveryResult;
    pseudoFirebase?: GcpDeliveryResult;
    firestore?: GcpDeliveryResult;
    dataflow?: GcpDeliveryResult;
    status?: string;
    reason?: string;
  };
  lastAcknowledgement?: {
    actor?: string;
    choice?: string;
    channel?: string;
    at?: string;
    acknowledgedAt?: string;
  };
};

export type BigQueryAgentPrior = {
  cohort?: string;
  prior_take_rate?: number;
  prior_follow_through?: number;
  recommended_adjustment?: string;
};

export type BigQueryAgentPriors = {
  source?: string;
  scenario_key?: string;
  ready?: boolean;
  dataset?: string;
  query_name?: string;
  rows_available?: number;
  priors?: BigQueryAgentPrior[];
  best_prior?: BigQueryAgentPrior;
  weakest_prior?: BigQueryAgentPrior;
  agent_context?: string[];
  memory_influence?: string[];
  sql_preview?: string;
};

export type DeliveryTelemetry = {
  summary?: { total?: number; guest_app?: number; worker_device?: number; equipment_controller?: number };
  response?: { takeRate?: number; positiveResponseRate?: number; reactiveFollowThroughRate?: number; score?: number; status?: string; sampleSize?: number };
  dispatches?: DeliveryDispatch[];
  contract?: unknown;
};

export type RunTraceContract = {
  run_id?: string;
  source?: string;
  scenario_key?: string;
  trace?: {
    trace_id?: string;
    span_id?: string;
    trace_lookup_query?: string;
    trace_url?: string;
    digital_twin_trace_id?: string;
    digital_twin_span_id?: string;
    eval_trace_id?: string;
    eval_span_id?: string;
    eval_trace_state?: string;
    eval_trace_url?: string;
  };
  phases?: Array<{
    id?: "predict" | "decide" | "govern" | "emit" | "observe" | "learn" | string;
    label?: string;
    status?: string;
    artifact?: string;
    evidence?: string;
    selected?: string;
    rejected?: unknown[];
    gate_status?: string;
    allowed?: boolean;
    findings?: string[];
    dispatch_count?: number;
    take_rate?: number;
    follow_through?: number;
    sample_size?: number;
    outcome_id?: string;
    learning_rule?: string;
  }>;
  trace_table?: Array<{
    step?: string;
    phase?: string;
    evidence?: string;
    artifact_id?: string | null;
    source?: string;
    score?: number;
    why?: string;
    gate_status?: string;
    allowed?: boolean;
    status?: string;
    approval_owner?: string | null;
    conflict_count?: number;
    dispatch_count?: number;
    mode?: string;
    connected?: boolean;
  }>;
  policy_rules?: Array<{
    policy_book_id?: string;
    policy_ref?: string;
    gate_status?: string;
    finding?: string;
  }>;
  candidate_actions?: Array<{
    id?: string;
    label?: string;
    status?: string;
    reason?: string;
    scorecard?: Record<string, unknown>;
    projected_impact?: Record<string, unknown>;
  }>;
  selected_action?: { label?: string; target?: string; action?: string; owner?: string; expected_effect?: string };
  policy_gate?: {
    allowed?: boolean;
    gate_status?: string;
    policy_refs?: string[];
    findings?: string[];
    remediation_task?: unknown;
    customer_care_case?: unknown;
    ledger_entry?: unknown;
  };
  policy_regulation_judgment?: PolicyRegulationJudgment;
  negotiation_trace?: NegotiationTrace;
  dispatches?: Array<{
    dispatch_id?: string;
    channel?: string;
    target_system?: string;
    status?: string;
    payload_summary?: string;
    payload?: unknown;
    response?: unknown;
  }>;
  receiver_acks?: Array<{
    dispatch_id?: string;
    channel?: string;
    status?: string;
    acknowledged?: boolean;
    response?: unknown;
  }>;
  outcome?: Record<string, unknown>;
  memory_write?: {
    decision_id?: string;
    outcome_id?: string;
    connected?: boolean;
    mode?: string;
    retrieved_learning_ids?: string[];
    learning_rule?: string;
    bigquery_query?: string;
  };
  eval?: Record<string, unknown>;
  ui_summary?: {
    input?: string;
    selected?: string;
    gate?: string;
    dispatches?: number;
    take_rate?: number;
    outcome_id?: string;
  };
};

export type PolicyRegulationJudgment = {
  status?: "allowed" | "review_required" | "blocked" | string;
  source?: string;
  hard_gate_status?: string;
  allowed_by_legacy_gate?: boolean;
  human_review_required?: boolean;
  approval_owner?: string | null;
  policy_refs?: string[];
  findings?: string[];
  human_review_reasons?: string[];
  required_evidence?: string[];
  blocked_authorities?: string[];
  interpreted_policy?: {
    status?: string;
    primary_case_id?: string | null;
    primary_case_title?: string | null;
    approval_required?: boolean;
    conflict_analysis?: Record<string, unknown>;
  };
  alignment_rule?: string;
};

export type NegotiationTrace = {
  mode?: string;
  source?: string;
  scenario_key?: string;
  proposal_count?: number;
  active_roles?: string[];
  rounds?: Array<Record<string, unknown>>;
  turns?: Array<Record<string, unknown>>;
  conflicts?: Array<Record<string, unknown>>;
  tradeoff_matrix?: Array<Record<string, unknown>>;
  executive_tradeoff?: Record<string, unknown>;
  selected_action?: { label?: string; target?: string; action?: string; owner?: string; expected_effect?: string };
  accepted_role_proposal?: Record<string, unknown>;
  selected_plan_id?: string;
  policy_regulation_judgment?: PolicyRegulationJudgment;
  final_executive_decision?: {
    status?: string;
    approval_owner?: string | null;
    reason?: string;
  };
};

export type AnalyticsTelemetry = {
  status?: string;
  mode?: string;
  row_counts?: Record<string, number>;
  inserted?: Record<string, number>;
  readiness_issues?: string[];
  priors?: BigQueryAgentPriors;
};

export type DigitalTwinToolTrace = {
  mode?: string;
  server?: string;
  tool_count?: number;
  span_kind?: string;
  trace?: {
    trace_id?: string;
    span_id?: string;
    trace_lookup_query?: string;
    trace_url?: string;
  };
  summary?: {
    scenario_key?: string;
    selected_ride?: string;
    selected_zone?: string;
    policy_gate?: string;
    quality_score?: number;
    boundary?: string;
  };
  agent_boundary?: {
    ml_prediction?: string;
    agent_action?: string;
    human_authority?: string;
    automation?: string;
  };
  tool_calls?: Array<{
    tool?: string;
    server?: string;
    capability?: string;
    status?: string;
    called_at?: string;
    arguments?: Record<string, unknown>;
    output?: Record<string, unknown>;
    span_kind?: string;
    trace?: {
      trace_id?: string;
      span_id?: string;
      trace_lookup_query?: string;
      trace_url?: string;
    };
  }>;
};

export type HostedEvaluatorLoop = {
  status?: string;
  provider?: string;
  evaluator_id?: string | null;
  location?: string;
  runtime?: string;
  checked_at?: string;
  trigger?: {
    enabled?: boolean;
    status?: string;
    reason?: string | null;
  };
  continuous_monitoring?: {
    configured?: boolean;
    sampling_rate?: string;
  };
  dimensions?: Array<{
    id?: string;
    label?: string;
    question?: string;
    required_fields?: string[];
    span_attributes?: string[];
  }>;
  column_mapping?: Record<string, string>;
  payload_preview?: {
    scenario_key?: string;
    decision_id?: string | null;
    outcome_id?: string | null;
    overall?: number;
    scorecard_status?: string;
    response_score?: number;
    response_status?: string;
    trace_id?: string | null;
    span_id?: string | null;
    trace_url?: string | null;
    dimension_scores?: Record<string, number>;
    dimension_explanations?: Record<string, string>;
    failure_reasons?: Array<{ dimension?: string; score?: number; reason?: string }>;
    selected_action?: Record<string, unknown>;
    governance?: Record<string, unknown>;
    response_metrics?: DeliveryTelemetry["response"];
    dispatches?: Array<Record<string, unknown>>;
    state_digest?: Record<string, unknown>;
    outcome?: Record<string, unknown>;
  };
  vertex_result?: {
    status?: string;
    provider?: string;
    project?: string;
    location?: string;
    evaluator_id?: string;
    transport?: string;
    metrics?: string[];
    result?: { score?: number; explanation?: string; [key: string]: unknown };
    reason?: string;
  } | null;
  readiness_issues?: string[];
};

export type EvalTraceTelemetry = {
  scorecard?: {
    overall?: number;
    status?: string;
    response_score?: number;
    response_status?: string;
    policy_guidance_score?: number;
    policy_gate_status?: string;
    policy_violation?: boolean;
    needs_human_approval?: boolean;
    failure_reasons?: Array<{ dimension?: string; score?: number; reason?: string }>;
  };
  hosted_eval?: HostedEvaluatorLoop;
  gcp_trace_eval?: {
    trace_id?: string | null;
    span_id?: string | null;
    trace_url?: string | null;
    trace_state?: string;
    evidence_depth?: string;
    evaluation_status?: string;
    ready?: boolean;
    vertex_genai_evaluation?: Record<string, unknown>;
  };
  dimension_scores?: Record<string, number>;
  dimension_explanations?: Record<string, string>;
  failure_reasons?: Array<{ dimension?: string; score?: number; reason?: string }>;
};

export type VertexScenarioSweepRow = {
  scenario_key?: string;
  status?: string;
  elapsed_ms?: number;
  decision_id?: string;
  outcome_id?: string | null;
  selected_action?: {
    label?: string;
    target?: string;
    action?: string;
    owner?: string;
  };
  internal?: {
    overall?: number;
    plan_quality_score?: number;
    outcome_effectiveness_score?: number;
    score_method?: string;
    status?: string;
    response_score?: number;
    policy_gate_status?: string | null;
    needs_human_approval?: boolean;
    failure_count?: number;
    low_dimensions?: Array<{ dimension?: string; score?: number }>;
  };
  response?: {
    status?: string;
    score?: number;
    take_rate?: number;
    positive_response_rate?: number;
    follow_through_rate?: number;
  };
  vertex?: {
    status?: string;
    transport?: string;
    score?: number;
    score_100?: number;
    explanation?: string;
    evaluator_id?: string;
    location?: string;
  };
  comparison?: {
    delta_vertex_minus_internal?: number | null;
    aligned?: boolean;
    needs_review?: boolean;
  };
  error?: string;
};

export type VertexScenarioSweepResponse = {
  sweep_id?: string;
  status?: string;
  source?: string;
  execute?: boolean;
  checked_at?: string;
  summary?: {
    scenario_count?: number;
    completed_count?: number;
    vertex_completed_count?: number;
    aligned_count?: number;
    avg_internal_score?: number | null;
    avg_vertex_score_100?: number | null;
    avg_abs_delta?: number | null;
  };
  recommendation?: {
    decision?: "GO" | "GO WITH CONDITIONS" | "NO-GO" | string;
    reason?: string;
    conditions?: string[];
  };
  scenarios?: VertexScenarioSweepRow[];
  persistence?: {
    mongo_eval_document_id?: string;
    analytics?: {
      status?: string;
      mode?: string;
      row_counts?: Record<string, number>;
      inserted?: Record<string, number>;
      readiness_issues?: string[];
      errors?: Record<string, unknown>;
    };
  };
  freshness?: {
    status?: string;
    stale?: boolean;
    age_hours?: number | null;
    max_age_hours?: number;
  };
  readiness_issues?: string[];
};

export type LatencyDiagnosticsResponse = {
  status?: string;
  checked_at?: string;
  summary?: {
    top_cause?: {
      id?: string;
      label?: string;
      status?: string;
      severity?: string;
      evidence?: string[];
      next_action?: string;
    };
    full_runtime_status?: string;
    slow_workflow_stage_count?: number;
    vertex_sweep_timing_count?: number;
  };
  causes?: Array<{
    id?: string;
    label?: string;
    status?: string;
    severity?: string;
    evidence?: string[];
    next_action?: string;
  }>;
  timings?: {
    full_runtime?: Record<string, unknown> & {
      import_profile?: Array<{
        phase?: string;
        epoch?: number;
        elapsed_ms?: number;
        duration_ms?: number | null;
        error?: string;
        module?: string;
        app_type?: string;
      }>;
    };
    slowest_workflow_stages?: Array<Record<string, unknown>>;
    vertex_sweep_scenarios?: Array<Record<string, unknown>>;
    dependency_probes?: Record<string, Record<string, unknown>>;
    import_profile_detail?: {
      status?: string;
      module?: string;
      duration_ms?: number;
      fresh?: boolean;
      top_self?: Array<{ module?: string; self_ms?: number; cumulative_ms?: number }>;
      top_cumulative?: Array<{ module?: string; self_ms?: number; cumulative_ms?: number }>;
      module_count?: number;
      stderr_tail?: string[];
      error?: string;
    };
  };
  thresholds?: Record<string, number>;
  env_flags?: Record<string, unknown>;
  probe_trigger?: {
    started?: string[];
    skipped?: Record<string, string>;
  };
  import_profile_trigger?: {
    started?: boolean;
    skipped?: string;
    module?: string;
  };
  gate?: {
    status?: string;
    mode?: string;
    fail_on_warning?: boolean;
    blockers?: string[];
    warnings?: string[];
    budgets?: Record<string, unknown>;
  };
  history?: {
    status?: string;
    sample_count?: number;
    summary?: {
      latest_status?: string | null;
      latest_top_cause_id?: string | null;
      recurring_top_cause_id?: string | null;
      recurring_top_cause_count?: number;
      max_probe_name?: string | null;
      max_probe_duration_ms?: number | null;
    };
    rows?: Array<{
      id?: string;
      created_at?: string;
      status?: string;
      top_cause_id?: string;
      top_cause?: string;
      severity?: string;
      full_runtime_status?: string;
      probe_durations_ms?: Record<string, number>;
      probe_statuses?: Record<string, string>;
    }>;
  };
  persistence?: {
    status?: string;
    eval_document_id?: string;
    collection?: string;
    queued_at?: string;
    stored_at?: string;
    reason?: string;
    error?: string;
    last?: Record<string, unknown>;
  };
  readiness_issues?: string[];
};

export type DigitalTwinBenchmarkScenario = {
  id?: string;
  name?: string;
  description?: string;
  success_threshold?: number;
  candidate_count?: number;
};

export type DigitalTwinBenchmarkRegistry = {
  mode?: string;
  scenario_count?: number;
  scenarios?: DigitalTwinBenchmarkScenario[];
};

export type DigitalTwinBenchmarkEpisode = {
  scenario?: {
    id?: string;
    name?: string;
    description?: string;
    hidden_twist?: string;
    success_threshold?: number;
  };
  passed?: boolean;
  scorecard?: {
    overall?: number;
    baseline_overall?: number;
    outcome_overall?: number;
    pressure_reduced?: number;
    policy_violations_avoided?: boolean;
    secondary_risk_score?: number;
    noisy_signal_recovery?: number;
    decision_latency_seconds?: number;
    threshold?: number;
    benchmark_selector_score?: number;
    agent_selection_score?: number;
    regret_vs_benchmark_selector?: number;
    planner_confidence?: number;
  };
  observation?: {
    mode?: string;
    observed?: {
      busiest_zone?: { id?: string; name?: string; density?: number };
      slowest_ride?: { id?: string; name?: string; status?: string; waitMins?: number; queueGuests?: number };
      food_backlog?: number;
      storm_risk?: number;
    };
    observation?: {
      busiest_zone?: { id?: string; name?: string; density?: number };
      slowest_ride?: { id?: string; name?: string; status?: string; waitMins?: number; queueGuests?: number };
      food_backlog?: number;
      storm_risk?: number;
    };
    staleness_seconds?: Record<string, number>;
  };
  hidden_ground_truth?: {
    available_to?: string;
    digest?: {
      busiest_zone?: { id?: string; name?: string; density?: number };
      slowest_ride?: { id?: string; name?: string; status?: string; waitMins?: number; queueGuests?: number };
      food_backlog?: number;
      storm_risk?: number;
      avg_satisfaction?: number;
    };
  };
  agent_input?: { mode?: string; scenario_key_given_to_agent?: string; context_mode?: string };
  planner?: { runtime?: string; recommended_action?: string; selected_action?: Record<string, string | number | boolean | undefined> };
  optimizer?: { mode?: string; selected_plan_id?: string; candidate_source?: string };
  selected_action?: { id?: string; label?: string; target?: string; action?: string; policy_gate?: string; selection_reason?: string };
  benchmark_selector_action?: { id?: string; label?: string; policy_gate?: string; selection_score?: number };
  failure_modes?: string[];
  failure_trace?: Array<{
    stage?: string;
    status?: string;
    detail?: string;
    evidence?: Record<string, unknown>;
  }>;
  candidate_results?: Array<{
    id?: string;
    label?: string;
    policy_gate?: string;
    selection_score?: number;
    projected_overall?: number;
    secondary_risks?: string[];
  }>;
  tool_trace?: { tools_used?: string[]; candidate_count?: number; decision_latency_seconds?: number };
};

export type DigitalTwinLearnedRerun = {
  mode?: string;
  remediations_generated?: number;
  memory_write?: {
    status?: string;
    target?: string;
    learning_ids?: string[];
    remediations?: Array<{
      _id?: string;
      scenarioKey?: string;
      lesson?: string;
      rule?: string;
      recommendedAction?: string;
      guardrailAdjustment?: string;
      confidence?: number;
      failureModes?: string[];
    }>;
  };
  comparison?: {
    score_delta?: number | null;
    pass_delta?: number | null;
    failed_delta?: number | null;
    regret_delta?: number | null;
  };
  resolved_failure_modes?: string[];
  new_failure_modes?: string[];
};

export type DigitalTwinBenchmarkResult = {
  status?: string;
  mode?: string;
  policy_under_test?: string;
  horizon_minutes?: number;
  summary?: {
    episodes?: number;
    passed?: number;
    failed?: number;
    average_score?: number;
    average_regret_vs_benchmark_selector?: number;
    hardest_episode?: string;
  };
  regression?: {
    mode?: string;
    current?: DigitalTwinBenchmarkHistoryRun;
    previous?: DigitalTwinBenchmarkHistoryRun | null;
    delta?: {
      average_score?: number | null;
      pass_rate?: number | null;
      failed?: number | null;
      average_regret_vs_benchmark_selector?: number | null;
    } | null;
    trend?: DigitalTwinBenchmarkHistoryRun[];
    stored_runs?: number;
  };
  learned_rerun?: DigitalTwinLearnedRerun;
  episodes?: DigitalTwinBenchmarkEpisode[];
};

export type DigitalTwinBenchmarkHistoryRun = {
  run_id?: string;
  created_at?: string;
  mode?: string;
  policy_under_test?: string;
  horizon_minutes?: number;
  scenario_ids?: string[];
  episodes?: number;
  passed?: number;
  failed?: number;
  pass_rate?: number;
  average_score?: number;
  average_regret_vs_benchmark_selector?: number;
  hardest_episode?: string;
  failure_modes?: Array<{ mode?: string; count?: number }>;
};

export type DigitalTwinBenchmarkReport = {
  status?: string;
  mode?: string;
  run_id?: string;
  created_at?: string;
  source_mode?: string;
  policy_under_test?: string;
  horizon_minutes?: number;
  summary?: {
    episodes?: number;
    passed?: number;
    failed?: number;
    average_score?: number;
    average_regret_vs_benchmark_selector?: number;
    hardest_episode?: string;
  };
  readiness?: {
    label?: string;
    score?: number;
    unresolved_failure_modes?: Array<{ mode?: string; count?: number }>;
    policy_gate_violations?: Array<{ scenario_id?: string; action?: string; policy_gate?: string }>;
  };
  learned_rerun?: DigitalTwinLearnedRerun | null;
  remediation_lessons?: Array<{ lesson?: string; rule?: string; recommendedAction?: string; confidence?: number }>;
  regression?: DigitalTwinBenchmarkResult["regression"] & {
    history_pointer?: { path?: string; stored_runs?: number };
  };
  gate?: {
    passed?: boolean;
    reasons?: string[];
    thresholds?: Record<string, unknown>;
  };
};

export type WorldStateReconciliation = {
  status?: string;
  mode?: string;
  reconciliation_id?: string;
  created_at?: string;
  source_count?: number;
  claim_count?: number;
  beliefs?: Array<{
    domain?: string;
    zone_id?: string;
    claim?: string;
    risk_level?: string;
    confidence?: number;
    uncertainty?: number;
    source_count?: number;
    evidence_count?: number;
    agent_read?: string;
  }>;
  conflicts?: Array<{
    domain?: string;
    zone_id?: string;
    assumption?: string;
    status?: string;
    sources?: string[];
    resolution?: string;
  }>;
  uncertainty?: {
    level?: string;
    score?: number;
    drivers?: string[];
  };
  action_receipts?: Array<{
    belief?: string;
    evidence?: string[];
    uncertainty?: number;
    policy?: string;
    allowed_action?: string;
    blocked_action?: string | null;
  }>;
  agent_input?: {
    requires_operator_review?: boolean;
    blocked_assumptions?: string[];
    belief_state?: {
      top_beliefs?: Array<{
        domain?: string;
        zone_id?: string;
        risk_level?: string;
        confidence?: number;
        uncertainty?: number;
        agent_read?: string;
      }>;
    };
  };
};

export type ClosedLoopOutcome = {
  loop_id?: string;
  mode?: string;
  phases?: Array<{ name?: string; status?: string; detail?: string }>;
  response_metrics?: { takeRate?: number; positiveResponseRate?: number; reactiveFollowThroughRate?: number; score?: number; status?: string; sampleSize?: number };
  channel_metrics?: {
    guest?: { dispatches?: number; accepted?: number; followed?: number; sample_size?: number };
    workers?: { dispatches?: number; acknowledged?: number; median_ack_seconds?: number };
    equipment?: { dispatches?: number; applied?: number };
  };
  state_impact?: {
    domain?: string;
    headline?: string;
    before_after_line?: string;
    density_delta?: number;
    congestion_delta?: number;
    comfort_delta?: number;
    queued_guest_delta?: number;
    before?: Record<string, number | string>;
    after?: Record<string, number | string>;
  };
  scorecard?: { overall?: number; response_score?: number; state_movement_score?: number; prevention_score?: number; status?: string };
  learning?: {
    should_update_plan?: boolean;
    should_adjust_policy?: boolean;
    take_rate_signal?: string;
    next_prompt?: string;
    next_plan_bias?: string;
    lesson?: string;
    validity?: string;
    outcome_id?: string;
    loop_id?: string;
    mongodb_rule?: string;
    revision_prompt?: string;
    retrieval_value?: string;
  };
  application?: { status?: string; message?: string; movedGuests?: number; workerAcknowledgments?: number; equipmentCommandsApplied?: number };
};

export type OptimizationTelemetry = {
  mode?: string;
  tool_calls?: DigitalTwinToolTrace["tool_calls"];
  candidate_source?: string;
  gemini_custom_mix_count?: number;
  role_proposal_candidate_count?: number;
  selected_plan_id?: string;
  decision_summary?: string;
  selected_plan?: OptimizationCandidate;
  candidates?: OptimizationCandidate[];
  decision_bridge_resolution?: DecisionBridgeResolution;
  operator_constraints?: OperatorConstraints;
  operator_candidate_frame?: {
    mode?: string;
    selected_candidate_id?: string;
    rejected_options?: Array<{ candidate?: string; removed_targets?: string[]; reason?: string }>;
    constraint_effects?: string[];
    decision_rules?: string[];
    request_objective_weights?: Record<string, number>;
    primary_action?: { target?: string; action?: string; label?: string };
  };
  memory_used?: {
    learnings?: string[];
    learning_rules?: Array<{ _id?: string; lesson?: string; rule?: string; confidence?: number; useCount?: number }>;
    learning_effect?: {
      take_rate_multiplier?: number;
      promotion_bias?: string;
      prefer_comfort_protection?: boolean;
      require_equipment_or_staff_action?: boolean;
    };
    role_quality_priors?: RoleQualityPriors;
  };
};

export type OperatorConstraints = {
  source?: string;
  command?: string;
  intent_summary?: string;
  inferred_incident_type?: string;
  rejected_option?: string;
  missing_facts?: string[];
  requires_human_review?: boolean;
  avoid_zones?: Array<{ id?: string; name?: string; kind?: string; reason?: string }>;
  preferred_destinations?: Array<{ id?: string; name?: string; kind?: string; reason?: string }>;
  required_staff_moves?: Array<{ role?: string; count?: number; from?: string; to?: string; reason?: string; deadlineMinutes?: number }>;
  equipment_controls?: Array<{ equipmentType?: string; zones?: string[]; settings?: Record<string, unknown>; reason?: string }>;
  guest_segments?: Array<{ segment?: string; constraint?: string }>;
  safety_escalations?: Array<{ type?: string; severity?: string; target?: string; requires_human_review?: boolean }>;
  decision_rules?: string[];
};

export type SignalTriageResult = {
  status?: string;
  signal?: {
    id?: string;
    text?: string;
    source?: string;
    categories?: string[];
    risk_level?: "CRITICAL" | "HIGH" | "MEDIUM" | "WATCH" | string;
    escalation_level?: number;
    confidence?: number;
    zone?: { id?: string; name?: string; density?: number; currentGuests?: number };
    missing_info?: string[];
    human_approval_required?: boolean;
    triage_explanation?: string;
    map_overlay?: { zoneId?: string; tone?: "risk" | "watch" | "ok" | string; pulse?: boolean; label?: string };
    source_signals?: Array<{
      id?: string;
      source?: string;
      source_label?: string;
      signal_quality?: string;
      risk_level?: string;
      categories?: string[];
      zone?: { id?: string; name?: string };
      text?: string;
    }>;
    fusion?: {
      source_count?: number;
      corroboration_count?: number;
      dominant_zone?: string;
      disagreement?: boolean;
      agent_read?: string;
      zone_votes?: Record<string, number>;
      category_votes?: Record<string, number>;
    };
    recommended_actions?: Array<{
      action?: string;
      owner?: string;
      deadline_minutes?: number;
      expected_impact?: string;
      target?: string;
      operation?: string;
    }>;
  };
  governance?: {
    summary?: { allowed?: number; review?: number; blocked?: number };
    actions?: Array<{ gate_status?: string; allowed?: boolean; findings?: string[] }>;
  };
  delivery?: {
    summary?: { total?: number; guest_app?: number; worker_device?: number; equipment_controller?: number; pending_operator_approval?: number };
    response?: { takeRate?: number; positiveResponseRate?: number; reactiveFollowThroughRate?: number; score?: number; status?: string; sampleSize?: number };
    dispatches?: DeliveryDispatch[];
  };
  customer_care_case?: { id?: string; status?: string; severity?: string; reason?: string };
  pipeline?: { name?: string; sources?: string[]; principle?: string };
  world_state?: WorldStateReconciliation;
  learning?: {
    mode?: string;
    dataset?: string;
    similar_episodes?: Array<{
      episode_id?: string;
      incident_type?: string;
      zone?: string;
      match?: number;
      why_match?: string[];
      best_action?: string;
      actions_taken?: string[];
      outcome?: Record<string, unknown>;
      labels?: { false_alarm?: boolean; escalation_correct?: boolean; response_quality?: string; policy_safe?: boolean };
      memory_source?: string;
      lesson?: string;
    }>;
    current_training_episode?: {
      episode_id?: string;
      incident_type?: string;
      zone?: string;
      signals?: unknown[];
      training_labels?: Record<string, unknown>;
      outcome_proxy?: Record<string, unknown>;
    };
    priors?: {
      similar_count?: number;
      confirmed_incident_count?: number;
      false_alarm_count?: number;
      best_action?: string;
      expected_response?: { median_ack_seconds?: number | null; typical_density_delta_10min?: number | null; confidence_note?: string };
    };
    persistence?: { status?: string; mode?: string; episode_id?: string; stored_episode_count?: number; bigquery_ready?: boolean };
    retrieval_quality?: { status?: string; top_match?: number; used_prior_correctly?: boolean; judge_note?: string };
    operational_timeline?: Array<{ step?: string; label?: string; detail?: string; status?: string }>;
    learning_loop?: string[];
  };
};

export type ReviewSnapshotScore = {
  key?: string;
  label?: string;
  score?: number;
  status?: "ready" | "review" | "gap" | string;
  evidence?: string[];
  missing?: string[];
};

export type ReviewSnapshot = {
  review_id?: string;
  created_at?: string;
  domain?: string;
  status?: "reviewable" | "prototype_review" | "not_ready" | string;
  overall_score?: number;
  scenario?: {
    key?: string;
    name?: string;
    description?: string;
    condition?: string;
    active_policy?: string;
  };
  state_digest?: {
    counts?: Record<string, number>;
    represented_guests?: number;
    avg_satisfaction?: number;
    busiest_zone?: { name?: string; density?: number; currentGuests?: number; waitMins?: number };
    highest_wait_ride?: { name?: string; waitMins?: number; queueGuests?: number; status?: string };
    top_queue?: { name?: string; waitMins?: number; guests?: number; spillbackRisk?: string };
  };
  observation_surface?: { frontend?: string[]; api?: string[] };
  scorecard?: ReviewSnapshotScore[];
  timeline?: Array<{
    at?: string;
    kind?: string;
    label?: string;
    detail?: string;
    source?: string;
    delta?: Record<string, number | boolean>;
    before?: Record<string, unknown>;
    after?: Record<string, unknown>;
  }>;
  replay?: {
    mode?: string;
    run_id?: string;
    run?: {
      run_id?: string;
      scenario_key?: string;
      created_at?: string;
      updated_at?: string;
      status?: string;
      persistent?: boolean;
    };
    event_count?: number;
    latest_event?: {
      kind?: string;
      label?: string;
      narrative?: string;
      delta?: Record<string, number | boolean>;
    } | null;
    events?: Array<{
      id?: string;
      at?: string;
      kind?: string;
      label?: string;
      narrative?: string;
      delta?: Record<string, number | boolean>;
    }>;
  };
  realism_notes?: string[];
  missing_capabilities?: string[];
  recommended_next_fixes?: string[];
  codex_review_prompt?: string;
};

export type OptimizationCandidate = {
  id?: string;
  name?: string;
  label?: string;
  source?: string;
  selected_action?: { label?: string; target?: string; action?: string; owner?: string; expected_effect?: string };
  scorecard?: {
    overall?: number;
    capacity_fit?: number;
    take_rate_likelihood?: number;
    staff_burden?: number;
    safety?: number;
    energy_comfort_balance?: number;
    overcorrection_risk?: number;
    role_alignment_bonus?: number;
    role_memory_prior_adjustment?: number;
  };
  projected_impact?: {
    fromZone?: string;
    movedGuests?: number;
    densityDeltaPct?: number;
    avgWaitDeltaMinutes?: number;
    staffStressDelta?: number;
    energyCostDeltaPct?: number;
    guestSatisfactionDelta?: number;
  };
  rejected_reasons?: string[];
  action_mix?: {
    guest_reroute?: {
      target_mix?: Array<{ destination?: string; destinationId?: string; share?: number; currentWaitMins?: number }>;
      holdShare?: number;
      promotionStrength?: string;
      offer?: string;
      estimatedMovedGuests?: number;
      expectedTakeRate?: number;
    };
  };
  role_proposal?: RoleAgentProposal & { memory_prior?: RoleQualityPrior };
};

export type RoleQualityPrior = {
  agent_id?: string;
  sample_count?: number;
  accepted_count?: number;
  rejected_count?: number;
  positive_count?: number;
  needs_adjustment_count?: number;
  accepted_rate?: number;
  positive_rate?: number;
  avg_response_score?: number;
  avg_take_rate?: number;
  prior_adjustment?: number;
  confidence?: string;
  rationale?: string;
};

export type RoleQualityPriors = {
  mode?: string;
  scenario_key?: string;
  sample_count?: number;
  priors?: RoleQualityPrior[];
  by_agent?: Record<string, RoleQualityPrior>;
};

export type RoleAgentProposal = {
  agent_id?: string;
  role?: string;
  department?: string;
  department_label?: string;
  department_agent?: string;
  requested_tool?: string;
  requires_compliance?: boolean;
  requires_executive?: boolean;
  executor_status?: string;
  proposal_envelope?: {
    proposal_status?: string;
    proposed_by?: string;
    department?: string;
    department_label?: string;
    department_agent?: string;
    requested_tool?: string;
    intent?: string;
    evidence?: string[];
    risk_level?: string;
    requires_compliance?: boolean;
    requires_executive?: boolean;
    approval_status?: string;
    executor_agent?: string;
    executor_status?: string;
    expected_outcome?: string;
    rollback?: string;
    boundary?: Record<string, unknown>;
  };
  proposal_type?: string;
  recommendation?: string;
  proposed_action?: { target?: string; action?: string; [key: string]: unknown };
  evidence?: string[];
  constraints?: string[];
  confidence?: number;
  policy_refs?: string[];
  handoff_to?: string;
  action_disposition?: {
    decision?: string;
    executor_status?: string;
    policy_status?: string;
    reason?: string;
    next_owner?: string;
    exit_condition?: string;
  };
  live_feed_grounding?: {
    event_ids?: string[];
    evidence_count?: number;
    source_count?: number;
    grounding_status?: string;
  };
  memory_decision_delta?: {
    status?: string;
    usage_scope?: string;
    requested_tool?: string;
    prior_outcome_id?: string;
    decision_delta?: {
      before?: string;
      after?: string;
      effect?: string;
      score_adjustment?: number;
      decision_boundary?: string;
    };
  };
  department_reasoning?: {
    diagnosis?: string;
    forecast?: string;
    selected_rationale?: string;
    candidate_actions?: Array<{
      action?: string;
      rank?: number;
      score?: number;
      risk?: string;
      selected?: boolean;
      expected_effect?: string;
      profile_adjusted_score?: number;
      profile_score_delta?: number;
      profile_counterfactual?: {
        score?: number;
        profile_effect?: string;
        precedence?: string;
        reasons?: string[];
        constraint_count?: number;
        relevant_zone_count?: number;
        sheltered_zone_count?: number;
        quiet_zone_count?: number;
        high_spillback_zone_count?: number;
      };
    }>;
    profile_counterfactual_summary?: {
      candidate_count?: number;
      best_profile_adjusted_action?: string;
      best_profile_adjusted_score?: number;
      precedence?: string;
      rule?: string;
    };
    failure_modes?: Array<{ mode?: string; mitigation?: string; owner?: string } | string>;
    memory_carry_forward?: string[];
    park_profile_context?: Record<string, unknown>;
  };
  park_profile_context?: {
    status?: string;
    department?: string;
    relevant_zones?: Array<{ id?: string; name?: string; role?: string; crowdPattern?: string; comfortCapacity?: number; spillbackRisk?: string }>;
    relevant_locations?: Array<{ id?: string; name?: string; type?: string; zoneId?: string; indoor?: boolean }>;
    profile_constraints?: Array<string | { policy?: string; rule?: string; summary?: string; constraint?: string }>;
    reasoning_effect?: string[];
    profile_version?: string;
    precedence?: string;
  };
  profile_precedence?: string;
  boundary?: {
    allowed_tools?: string[];
    decision_rights?: string[];
    blocked_actions?: string[];
    execution_scope?: string;
    can_dispatch?: boolean;
  };
};

export type RoleAgentProposalConflict = {
  kind?: string;
  severity?: string;
  agents?: string[];
  summary?: string;
  resolution?: string;
};

export type RoleAgentProposalArtifact = {
  mode?: string;
  route?: Record<string, unknown>;
  scenario_key?: string;
  execution_model?: string;
  active_roles?: string[];
  proposal_count?: number;
  proposal_envelope_summary?: {
    total?: number;
    proposed?: number;
    blocked?: number;
    requires_compliance?: number;
    requires_executive?: number;
    ready_for_executor?: number;
    awaiting_compliance?: number;
    awaiting_executive?: number;
  };
  park_profile_summary?: {
    status?: string;
    venue_id?: string;
    venue_name?: string;
    profile_type?: string;
    profile_version?: string;
    readiness_status?: string;
    precedence?: string;
    contract?: string;
    counts?: Record<string, number>;
    source_integrity?: Record<string, unknown>;
  };
  park_profile_context_status?: string;
  profile_context_proposal_count?: number;
  profile_counterfactual_candidate_count?: number;
  profile_precedence_count?: number;
  profile_version?: string;
  precedence?: string;
  tradeoff_matrix?: Array<{
    agent?: string;
    department?: string;
    requested_tool?: string;
    decision?: string;
    verdict?: string;
    rationale?: string;
    confidence?: number;
    safety_risk_weight?: number;
    guest_value?: number;
    revenue_value?: number;
    labor_value?: number;
    policy_status?: string;
    profile_constraint_count?: number;
    profile_counterfactual_action?: string;
    profile_counterfactual_score?: number;
    profile_precedence?: string;
  }>;
  negotiation_rounds?: Array<{
    round?: number;
    name?: string;
    claims?: Array<{ agent?: string; department?: string; tool?: string; disposition?: string; wants?: string }>;
    challenges?: Array<{ from?: string; to?: string; issue?: string; resolution?: string; status?: string }>;
    tradeoff_matrix?: RoleAgentProposalArtifact["tradeoff_matrix"];
    decision?: string;
    rationale?: string;
  }>;
  memory_decision_deltas?: NonNullable<RoleAgentProposal["memory_decision_delta"]>[];
  executive_tradeoff?: {
    decision?: string;
    rationale?: string;
    tradeoff_matrix?: RoleAgentProposalArtifact["tradeoff_matrix"];
    approved_departments?: string[];
    held_departments?: string[];
  };
  proposals?: RoleAgentProposal[];
  conflicts?: RoleAgentProposalConflict[];
  mediator_summary?: string;
};

export type DecisionBridgeResolution = {
  mode?: string;
  selected_candidate_id?: string;
  selected_source?: string;
  accepted_role_proposal?: RoleAgentProposal | null;
  rejected_role_proposals?: Array<{
    candidate_id?: string;
    agent_id?: string;
    role?: string;
    recommendation?: string;
    score?: number;
    reason?: string;
  }>;
  conflicts?: RoleAgentProposalConflict[];
  summary?: string;
};

export type RoleOutcomeAttribution = {
  mode?: string;
  scenario_key?: string;
  selected_action?: Record<string, unknown>;
  decision_bridge_resolution?: DecisionBridgeResolution;
  summary?: {
    proposal_count?: number;
    accepted_count?: number;
    rejected_count?: number;
    context_only_count?: number;
    winner_agent_id?: string;
  };
  role_outcomes?: Array<{
    agent_id?: string;
    role?: string;
    proposal_type?: string;
    status?: string;
    candidate_id?: string;
    candidate_score?: number;
    rejection_reason?: string;
    outcome_metrics?: { response_score?: number; take_rate?: number; follow_through?: number; eval_score?: number };
    learning_signal?: { status?: string; reason?: string };
    proposed_action?: Record<string, unknown>;
  }>;
};

export type RunTelemetry = {
  status?: string;
  readiness_issues?: string[];
  scenario_key?: string;
  run_receipt?: {
    id?: string;
    kind?: string;
    available?: boolean;
    upgrade_status?: "pending" | "running" | "upgraded" | "failed" | "final" | string;
    observability_status?: string;
    incident_fingerprint?: string;
    upgrade_detail?: Record<string, unknown>;
  };
  runtime_proof?: {
    receipt_upgrade_status?: string;
    full_runtime?: {
      status?: string;
      loaded?: boolean;
      load_elapsed_ms?: number | null;
      load_duration_ms?: number | null;
      metrics?: Record<string, number>;
    };
    timeout_tiers?: Record<string, number>;
    refinement_elapsed_ms?: number;
    upgraded_at?: string;
  };
  operator_response?: {
    headline?: string;
    summary?: string;
    next_step?: string;
  };
  request?: {
    operator_command?: string;
    mode?: string;
    scenario_key?: ScenarioKey | string;
    urgency?: string;
  };
  operation_mode?: boolean;
  operation_event?: {
    status?: string;
    message?: string;
    event?: {
      kind?: SimulationKind | string;
      targetId?: string;
      intensity?: number;
      createdAt?: string;
      unexpected?: boolean;
      source?: string;
      reason?: string;
    };
  };
  agent_findings?: RuntimeAgentFinding[];
  orchestration?: AgentTopology;
  planner?: {
    runtime?: string;
    model?: string;
    gemini_ready?: boolean;
    attempted_gemini?: boolean;
    selected_action?: { label?: string; target?: string; action?: string; owner?: string; expected_effect?: string };
    confidence_score?: number;
  };
  role_agent_proposals?: RoleAgentProposalArtifact;
  negotiation_trace?: NegotiationTrace;
  policy_regulation_judgment?: PolicyRegulationJudgment;
  role_outcome_attribution?: RoleOutcomeAttribution;
  role_proposal_memory?: { mode?: string; status?: string; stored_count?: number; connected?: boolean; error?: string };
  execution?: { status?: string; message?: string };
  governance?: {
    allowed?: boolean;
    gate_status?: string;
    findings?: string[];
    ledger_entry?: { id?: string; gateStatus?: string; allowed?: boolean };
    remediation_task?: { id?: string; status?: string; title?: string };
    customer_care_case?: { id?: string; status?: string; reason?: string };
  };
  eval?: EvalTraceTelemetry;
  decision_id?: string;
  trace_contract?: RunTraceContract;
  delivery?: DeliveryTelemetry;
  optimization?: OptimizationTelemetry;
  operator_constraints?: OperatorConstraints;
  digital_twin_tools?: DigitalTwinToolTrace;
  outcome_id?: string;
  outcome?: ClosedLoopOutcome;
  analytics?: AnalyticsTelemetry;
  memory?: { mode?: string; connected?: boolean; retrieved_playbooks?: string[]; retrieved_incidents?: string[]; retrieved_learnings?: unknown[] };
  live_feed_case?: {
    mode?: string;
    source?: string;
    uses_seed_data?: boolean;
    scripted_case?: boolean;
    persisted_event_count?: number;
    ready_feed_count?: number;
    required_feed_count?: number;
    missing_or_weak_feed_count?: number;
    open_review_count?: number;
    lead_source?: string;
    lead_signal_type?: string;
    operator_message?: string;
    evidence?: Array<{
      source?: string;
      label?: string;
      owner?: string;
      status?: string;
      signal_type?: string;
      confidence?: number;
      age_seconds?: number | null;
      event_id?: string;
      summary?: string;
    }>;
    feed_issues?: Array<{ source?: string; status?: string; readiness_issues?: string[] }>;
    reasoning?: string[];
  };
  park_profile_summary?: NonNullable<RoleAgentProposalArtifact["park_profile_summary"]>;
  tool_executor_live_test?: {
    status?: string;
    receipt_count?: number;
    executed_count?: number;
    held_count?: number;
    held_disposition_count?: number;
    receipts?: Array<{
      department?: string;
      agent?: string;
      tool?: string;
      status?: string;
      executor_status?: string;
      policy_check?: string;
      disposition?: string;
      reason?: string;
    }>;
  };
  live_feed_receiver_delivery?: {
    status?: string;
    proof_id?: string;
    delivered_count?: number;
    acknowledged_count?: number;
    executed_count?: number;
    material_state_mutation?: boolean;
    public_guest_messages_sent?: number;
  };
  risk_escalation_approval?: {
    status?: string;
    stage?: string;
    requested_count?: number;
    approved_count?: number;
    blocked_count?: number;
    required_approvers?: string[];
    policy?: string;
    approvals?: Array<{
      approval_id?: string;
      status?: string;
      stage?: string;
      department?: string;
      source_tool?: string;
      lifted_scope?: string;
      receiver?: string;
      limits?: string[];
      missing_controls?: string[];
      boundary?: string;
      approvers?: Array<{ agent?: string; status?: string; basis?: string }>;
    }>;
  };
  risk_escalated_tool_executor?: {
    status?: string;
    executed_count?: number;
    preview_count?: number;
    receipt_count?: number;
  };
  risk_escalation_receiver_delivery?: {
    status?: string;
    delivered_count?: number;
    acknowledged_count?: number;
    executed_count?: number;
    material_state_mutation?: boolean;
    public_guest_messages_sent?: number;
  };
  risk_escalation_simulated_ops_impact?: {
    status?: string;
    material_state_mutation?: boolean;
    dispatch_count?: number;
    boundary?: string;
    state_impact?: {
      domain?: string;
      headline?: string;
      before_after_line?: string;
      congestion_delta?: number;
      queued_guest_delta?: number;
    };
    episode_fitness?: {
      fitness?: number;
      scores?: {
        fitness?: number;
      };
    };
  };
  live_feed_simulated_ops_impact?: {
    status?: string;
    mode?: string;
    issue_kind?: string;
    target_id?: string;
    material_state_mutation?: boolean;
    receiver_rows?: number;
    dispatch_count?: number;
    message?: string;
    boundary?: string;
    state_impact?: {
      domain?: string;
      headline?: string;
      before_after_line?: string;
      density_delta?: number;
      congestion_delta?: number;
      comfort_delta?: number;
      queued_guest_delta?: number;
      before?: Record<string, unknown>;
      after?: Record<string, unknown>;
    };
    episode_fitness?: {
      id?: string;
      fitness?: number;
      rewardDelta?: number;
      pressureReduction?: number;
      scores?: {
        fitness?: number;
        reward_delta?: number;
      };
      pressure?: {
        reduction_vs_baseline?: number;
      };
    };
  };
  hard_decision_follow_through?: {
    status?: string;
    mode?: string;
    contract?: string;
    task_count?: number;
    active_follow_up_count?: number;
    closed_non_executable_count?: number;
    owner_count?: number;
    unresolved_without_owner_count?: number;
    tasks?: Array<{
      task_id?: string;
      department?: string;
      agent?: string;
      source_tool?: string;
      status?: string;
      next_owner?: string;
      exit_condition?: string;
      fallback?: string;
      why_not_undecided?: string;
      policy_status?: string;
      follow_up_decision?: string;
      active_follow_up_required?: boolean;
    }>;
  };
  live_feed_outcome_measurement?: {
    status?: string;
    measurement_id?: string;
    measured_outcome_available?: boolean;
    measured_source_count?: number;
    attribution_confidence?: number;
    reward_value?: number;
    eligible_for_reward?: boolean;
  };
  live_feed_outcome_memory?: {
    status?: string;
    mongo_collection?: string;
    decision_id?: string;
    outcome_id?: string;
  };
  live_feed_memory_priors?: {
    status?: string;
    prior_count?: number;
    applied_count?: number;
    blocked_count?: number;
    rejected_count?: number;
    weak_context_count?: number;
    accepted_departments?: string[];
    blocked_departments?: string[];
    latest_outcome_ids?: string[];
    applied_prior_outcome_ids?: string[];
  };
  tool_use_clarity?: {
    mode?: string;
    proposal_count?: number;
    tools?: Array<{
      department?: string;
      agent?: string;
      tool?: string;
      intent?: string;
      evidence?: unknown[];
      risk_level?: string;
      policy_check?: string;
      expected_outcome?: string;
      rollback?: string;
      executor_agent?: string;
      executor_status?: string;
    }>;
    trace_steps?: Array<{ step?: string; phase?: string; evidence?: string; artifact_id?: string }>;
    judge?: { eval_status?: string; policy_gate?: string; trace_contract_present?: boolean };
  };
  unified_receipt?: UnifiedOperatingReceipt;
  revision?: OptimizationCandidate & { revision_reason?: string };
};

export type EventOpsPlan = {
  status?: string;
  decision_id?: string;
  event_plan_id?: string;
  event_scope?: {
    theme?: string;
    event_type?: string;
    locked?: boolean;
  };
  planner?: {
    runtime?: string;
    event_id?: string;
    event_name?: string;
    errors?: string[];
  };
  orchestration?: AgentTopology;
  memory?: { mode?: string; connected?: boolean; retrieved_playbooks?: string[]; retrieved_incidents?: string[] };
  plan?: {
    event_id?: string;
    event_name?: string;
    runtime?: string;
    selected_concept?: string;
    operator_summary?: string;
    revision_summary?: string;
    park_understanding?: Array<{
      name?: string;
      role?: string;
      congestion_risk?: string;
      best_for?: string[];
      avoid?: string[];
      reasoning?: string;
    }>;
    concepts?: Array<{
      name?: string;
      style?: string;
      target_guest_segments?: string[];
      risk?: string;
      revenue_potential?: string;
      operations_notes?: string;
    }>;
    temporal_flow_plan?: Array<{
      time?: string;
      expected_behavior?: string;
      operational_risk?: string;
      actions?: string[];
    }>;
    temporary_experiences?: Array<{
      name?: string;
      experience_type?: string;
      location?: string;
      scare_level?: string;
      rationale?: string;
      capacity_notes?: string;
    }>;
    equipment_moves?: Array<{
      equipment?: string;
      quantity?: number;
      from_location?: string;
      to_location?: string;
      setup_window?: string;
      dependency?: string;
    }>;
    staffing_plan?: Array<{
      role?: string;
      estimated_count?: number;
      placement?: string;
      time_focus?: string;
      reason?: string;
    }>;
    risk_findings?: Array<{
      risk?: string;
      severity?: string;
      evidence?: string;
      mitigation?: string;
    }>;
    traffic_forecast?: Array<{
      window?: string;
      hotspot?: string;
      expected_traffic?: string;
      risk_level?: string;
      operating_move?: string;
    }>;
    deployment_suggestions?: Array<{
      priority?: string;
      owner?: string;
      suggestion?: string;
      deployment_window?: string;
      success_metric?: string;
    }>;
    judge_scorecard?: {
      constraint_following?: number;
      groundedness?: number;
      completeness?: number;
      crowd_flow?: number;
      staff_feasibility?: number;
      equipment_feasibility?: number;
      guest_experience?: number;
      revision_quality?: number;
      overall?: number;
      critique?: string[];
    };
    quality?: {
      overall?: number;
      status?: string;
      total_event_staff?: number;
      available_staff_pool?: number;
      gcp_eval?: Record<string, number>;
      arize_eval?: Record<string, number>;
    };
    errors?: string[];
  };
};

export type ProactiveInsight = {
  id?: string;
  agent?: string;
  kind?: string;
  urgency?: "risk" | "watch" | "ok" | string;
  trigger?: string;
  why_now?: string;
  recommendation?: string;
  deadline_minutes?: number;
  evidence?: string[];
  proactive_not_reactive?: string;
  confidence?: number;
};

export type ProactiveInsights = {
  proactive_id?: string;
  created_at?: string;
  mode?: string;
  lookahead_minutes?: number;
  summary?: {
    insight_count?: number;
    risk_count?: number;
    watch_count?: number;
    minutes_to_event?: number;
    busiest_zone?: string;
    busiest_path?: string;
    dominant_risk?: string;
  };
  forecast?: Array<{
    time?: string;
    baseline_risk?: number;
    with_proactive_actions?: number;
    expected_change?: string;
    reason?: string;
  }>;
  insights?: ProactiveInsight[];
};

export type EventOpsLifecycle = {
  headline?: string;
  current_stage?: string;
  stage_count?: number;
  completed_count?: number;
  plan_mode?: string;
  ids?: {
    decision_id?: string;
    outcome_id?: string;
    revision_decision_id?: string;
    revision_event_plan_id?: string;
  };
  metrics?: {
    take_rate?: number;
    positive_response_rate?: number;
    follow_through_rate?: number;
    response_score?: number;
    sample_size?: number;
    dispatch_total?: number;
    guest_dispatches?: number;
    worker_dispatches?: number;
    equipment_dispatches?: number;
  };
  early_detection?: {
    top_signal?: ProactiveInsight;
    forecast?: { time?: string; baseline_risk?: number; with_proactive_actions?: number; expected_change?: string; reason?: string };
    busiest_zone?: string;
    busiest_path?: string;
  };
  action_effects?: Array<{
    channel?: string;
    label?: string;
    body?: string;
    status?: string;
    response?: DeliveryResponse;
  }>;
  state_impact?: {
    domain?: string;
    headline?: string;
    before_after_line?: string;
    density_delta?: number;
    congestion_delta?: number;
    comfort_delta?: number;
    queued_guest_delta?: number;
    before?: Record<string, number | string>;
    after?: Record<string, number | string>;
  };
  learning?: {
    should_update_plan?: boolean;
    should_adjust_policy?: boolean;
    take_rate_signal?: string;
    next_prompt?: string;
    mongodb_rule?: string;
    outcome_id?: string;
    loop_id?: string;
    revision_prompt?: string;
    retrieval_value?: string;
  };
  agent_trace?: Array<{ agent?: string; span?: string; confidence?: number; policy_refs?: string[] }>;
  orchestration?: AgentTopology;
  intelligence_comparison?: IntelligenceComparison;
  learning_proof?: LearningProof;
  bigquery_priors?: BigQueryAgentPriors;
  stages?: Array<{
    id?: string;
    label?: string;
    actor?: string;
    status?: "done" | "active" | "pending" | "watch" | "complete";
    metric?: string | number;
    detail?: string;
    artifact?: string;
  }>;
};

export type LearningProof = {
  mode?: string;
  headline?: string;
  next_plan_bias?: string;
  after?: {
    label?: string;
    strategy?: string;
    retrieval_value?: string;
    expected_take_rate?: number;
    expected_follow_through_rate?: number;
  };
  run_1?: {
    decision_id?: string;
    outcome_id?: string;
    route_mix?: Array<{ destination?: string; destinationId?: string; share?: number; currentWaitMins?: number }>;
    take_rate?: number;
    follow_through_rate?: number;
    state_impact?: Record<string, unknown>;
    receiver_ids?: string[];
  };
  memory_write?: {
    outcome_id?: string;
    learning_rule?: string;
    retrieved_learning_ids?: string[];
    mongo_collection?: string;
    bigquery_dataset?: string;
    bigquery_query?: string;
  };
  run_2?: {
    change_reason?: string;
    route_mix?: Array<{ destination?: string; destinationId?: string; share?: number; currentWaitMins?: number }>;
    expected_take_rate?: number;
    expected_follow_through_rate?: number;
    revision_event_plan_id?: string;
    weak_prior_avoided?: BigQueryAgentPrior;
    best_prior_used?: BigQueryAgentPrior;
  };
};

export type IntelligenceComparison = {
  mode?: string;
  headline?: string;
  trigger?: {
    signal?: string;
    judge_gate?: string;
    memory_signal?: string;
  };
  before?: {
    label?: string;
    decision_id?: string;
    strategy?: string;
    take_rate?: number;
    positive_response_rate?: number;
    follow_through_rate?: number;
    gcp_eval_response_score?: number;
    arize_response_score?: number;
    state_impact?: string;
    weakness?: string;
  };
  learning?: {
    outcome_id?: string;
    loop_id?: string;
    mongodb_rule?: string;
    revision_prompt?: string;
    retrieval_value?: string;
    should_update_plan?: boolean;
    should_adjust_policy?: boolean;
    take_rate_signal?: string;
    next_prompt?: string;
    next_plan_bias?: string;
    lesson?: string;
    validity?: string;
  };
  after?: {
    label?: string;
    revision_event_plan_id?: string;
    strategy?: string;
    expected_take_rate?: number;
    expected_positive_response_rate?: number;
    expected_follow_through_rate?: number;
    expected_gcp_eval_response_score?: number;
    expected_arize_response_score?: number;
    expected_score_delta?: number;
    revision_created?: boolean;
  };
  changed_assumptions?: Array<{ assumption?: string; before?: string; after?: string; evidence?: string }>;
  gcp_eval_findings?: Array<{ check?: string; before?: number; after?: number; delta?: number; finding?: string }>;
  arize_findings?: Array<{ check?: string; before?: number; after?: number; delta?: number; finding?: string }>;
  proof_points?: string[];
};

export type ProactiveRunTelemetry = {
  status?: string;
  scenario_key?: string;
  decision_id?: string;
  outcome_id?: string;
  runtime_proof?: {
    mode?: string;
    source?: string;
    runtime?: string;
    provider?: string;
    platform?: string;
    model?: string;
    gemini_ready?: boolean;
    elapsed_ms?: number;
  };
  trace_contract?: RunTraceContract;
  lifecycle?: EventOpsLifecycle;
  intelligence_comparison?: IntelligenceComparison;
  learning_proof?: LearningProof;
  learned_run?: {
    status?: string;
    source?: string;
    applied_from?: string;
    best_prior?: BigQueryAgentPrior;
    weak_prior_avoided?: BigQueryAgentPrior;
    route_mix?: Array<{ destination?: string; destinationId?: string; zoneId?: string; share?: number; currentWaitMins?: number }>;
  };
  agent_findings?: RuntimeAgentFinding[];
  orchestration?: AgentTopology;
  role_agent_proposals?: RoleAgentProposalArtifact;
  negotiation_trace?: NegotiationTrace;
  policy_regulation_judgment?: PolicyRegulationJudgment;
  role_outcome_attribution?: RoleOutcomeAttribution;
  planner?: RunTelemetry["planner"];
  governance?: RunTelemetry["governance"];
  optimization?: OptimizationTelemetry;
  operator_constraints?: OperatorConstraints;
  proactive?: ProactiveInsights;
  brief?: {
    runtime?: string;
    operator_brief?: string;
    why_now?: string;
    recommended_commitments?: string[];
    should_revise_event_plan?: boolean;
    plan_revision_prompt?: string;
    errors?: string[];
  };
  eval?: EvalTraceTelemetry & {
    overall?: number;
    status?: string;
    proactive_timeliness?: number;
    actionability?: number;
    expected_prevention?: number;
    false_alarm_risk?: number;
    reasoning?: string;
  };
  delivery?: DeliveryTelemetry;
  digital_twin_tools?: DigitalTwinToolTrace;
  outcome?: ClosedLoopOutcome;
  event_revision?: EventOpsPlan | null;
  memory?: { mode?: string; connected?: boolean; retrieved_playbooks?: string[]; retrieved_incidents?: string[]; retrieved_learnings?: string[] };
  analytics?: AnalyticsTelemetry;
  unified_receipt?: UnifiedOperatingReceipt;
};

export type OperatorCommandResponse = {
  status?: string;
  command?: string;
  mode?: "operations" | "event_plan" | "signal_triage" | string;
  route?: {
    route?: string;
    scenario_key?: ScenarioKey | string;
    urgency?: string;
    requires_human_review?: boolean;
    interpreted_intent?: string;
  };
  operator_constraints?: OperatorConstraints;
  role_route?: AgentRoleRoute;
  operator_response?: {
    headline?: string;
    summary?: string;
    next_step?: string;
    tradeoffs?: Record<string, string>;
  };
  agent_workflow?: Record<string, unknown>;
  role_agent_proposals?: RoleAgentProposalArtifact;
  run_telemetry?: RunTelemetry;
  event_plan?: EventOpsPlan;
  signal_triage?: SignalTriageResult;
  unified_receipt?: UnifiedOperatingReceipt;
  role_receipt?: {
    chain?: string[];
    role?: string;
    skill?: string;
    scenario_key?: string;
    decision_id?: string;
    outcome_id?: string;
    dispatch_ids?: string[];
    mongo?: { mode?: string; decision_id?: string; outcome_id?: string; learning_id?: string; connected?: boolean };
    bigquery?: { status?: string; mode?: string; inserted?: Record<string, number>; row_counts?: Record<string, number> };
    learning_update?: {
      status?: string;
      take_rate?: number;
      follow_through_rate?: number;
      lesson?: string;
      next_plan_bias?: string;
      validity?: string;
    };
  };
  learning_proof?: {
    mode?: string;
    next_plan_bias?: string;
    observed?: { take_rate?: number; positive_response_rate?: number; follow_through_rate?: number };
  };
  gemini_refinement?: {
    status?: string;
    mode?: string;
    runtime?: string;
    elapsed_ms?: number;
    headline?: string;
    operator_brief?: string;
    refined_actions?: string[];
    policy_notes?: string[];
    confidence?: number;
    error?: string;
  };
  memory?: Record<string, unknown>;
  analytics?: Record<string, unknown>;
  outcome?: ClosedLoopOutcome;
};

export type UnifiedOperatingReceipt = {
  contract?: string;
  role?: "scan" | "react" | "proact" | string;
  domain?: string;
  scenario_key?: string;
  confidence?: number | null;
  constraints?: {
    summary?: string;
    requires_human_review?: boolean;
    policy_gates?: string[];
  };
  tools?: string[];
  selected_action?: { label?: string; target?: string; action?: string; owner?: string; expected_effect?: string };
  policy_result?: { allowed?: boolean; gate_status?: string; findings?: string[] };
  policy_regulation_judgment?: PolicyRegulationJudgment;
  negotiation_trace?: NegotiationTrace;
  dispatches?: { count?: number; channels?: string[]; ids?: string[] };
  state_impact?: ClosedLoopOutcome["state_impact"];
  learning_update?: Record<string, unknown>;
  memory?: Record<string, unknown>;
  analytics?: Record<string, unknown>;
};
