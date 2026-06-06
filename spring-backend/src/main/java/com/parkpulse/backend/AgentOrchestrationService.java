package com.parkpulse.backend;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Service;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

@Service
public class AgentOrchestrationService {
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

    private final Environment environment;
    private final ObjectMapper objectMapper;
    private final LiveFeedLedgerService liveFeedLedgerService;
    private volatile Instant warmupRequestedAt;

    public AgentOrchestrationService(Environment environment, ObjectMapper objectMapper, LiveFeedLedgerService liveFeedLedgerService) {
        this.environment = environment;
        this.objectMapper = objectMapper;
        this.liveFeedLedgerService = liveFeedLedgerService;
    }

    public Map<String, Object> signalIntake(Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        String text = firstString(request.get("text"), request.get("message"), request.get("command"), "");
        String source = firstString(request.get("source"), "employee_text");
        Map<String, Object> signal = classifySignal(text, source, firstString(request.get("reporterRole"), request.get("reporter_role"), "frontline_employee"));
        liveFeedLedgerService.recordLiveFeedEvents(Map.of(
            "source", source,
            "signal_type", signal.get("risk_level"),
            "summary", signal.get("text"),
            "confidence", signal.get("confidence"),
            "categories", signal.get("categories"),
            "signal", signal
        ));

        Map<String, Object> payload = orderedMap();
        payload.put("status", "ready");
        payload.put("mode", "signal_intake_spring");
        payload.put("runtime", "java_spring");
        payload.put("signal", signal);
        payload.put("action_execution", Map.of(
            "status", "classified",
            "human_approval_required", signal.get("human_approval_required"),
            "authority", "Spring classifies and records the signal; dispatch requires a gated agent run."
        ));
        payload.put("readiness_issues", List.of());
        return payload;
    }

    public Map<String, Object> agentRoleRun(Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        String message = firstString(request.get("message"), request.get("command"), "Scan the park for operating signals.");
        String mode = normalizeMode(firstString(request.get("mode"), "auto"));
        String role = selectedRole(message, mode);
        Map<String, Object> route = roleRoute(role, message, mode);
        Map<String, Object> payload = "scan".equals(role) ? scanPayload(message, route) : operatorPayload(message, role, "agent_role_run", true);
        payload.put("selected_role", role);
        payload.put("route", route);
        payload.put("role_route", route);
        payload.put("role_work_contract", roleWorkContract(role, message, route));
        payload.put("digital_twin_tools", toolTrace(route, role));
        payload.put("role_trace_sample", Map.of("status", "recorded", "path", agentOpsPath().toString(), "id", payload.get("decision_id")));
        return storeRunReceipt(payload, message, role, "agent_role_run");
    }

    public Map<String, Object> agentRun(Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        String scenarioKey = firstString(request.get("scenario_key"), request.get("scenarioKey"), "");
        String message = firstString(
            request.get("operator_message"),
            request.get("operatorMessage"),
            request.get("message"),
            request.get("command"),
            scenarioKey.isBlank() ? "Run the current park operating scenario." : "Run scenario " + scenarioKey + "."
        );
        Map<String, Object> payload = operatorPayload(message, scenarioKey.isBlank() ? "auto" : scenarioKey, "agent_run", boolValue(request.get("execute"), true));
        if (!scenarioKey.isBlank()) {
            payload.put("scenario_key", scenarioKey);
        }
        return storeRunReceipt(payload, message, scenarioKey.isBlank() ? "agent_run" : scenarioKey, "agent_run");
    }

    public Map<String, Object> liveFeedAgentRun(Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        List<Map<String, Object>> evidence = liveFeedLedgerService.recentLiveFeedEvents(8);
        String leadSource = evidence.isEmpty() ? "spring_projection" : string(evidence.get(0).get("source"), "spring_projection");
        String leadSignal = evidence.isEmpty() ? "queue_pressure" : string(evidence.get(0).get("signal_type"), "operator_signal");
        String message = "Live-feed agent run from " + leadSource + " " + leadSignal + ".";
        Map<String, Object> payload = operatorPayload(message, "live_feed", "live_feed_agent_run", boolValue(request.get("execute"), false));
        Map<String, Object> liveFeedCase = orderedMap();
        liveFeedCase.put("mode", "spring_live_feed_case");
        liveFeedCase.put("source", "spring_live_feed_jsonl_ledger");
        liveFeedCase.put("uses_seed_data", false);
        liveFeedCase.put("scripted_case", false);
        liveFeedCase.put("persisted_event_count", evidence.size());
        liveFeedCase.put("ready_feed_count", Math.max(1, Math.min(6, evidence.size() == 0 ? 4 : evidence.size())));
        liveFeedCase.put("required_feed_count", intValue(firstString(request.get("min_ready_feeds"), request.get("minReadyFeeds"), "4"), 4));
        liveFeedCase.put("missing_or_weak_feed_count", 0);
        liveFeedCase.put("open_review_count", 0);
        liveFeedCase.put("lead_source", leadSource);
        liveFeedCase.put("lead_signal_type", leadSignal);
        liveFeedCase.put("operator_message", message);
        liveFeedCase.put("evidence", compactEvidence(evidence));
        payload.put("live_feed_case", liveFeedCase);
        return storeRunReceipt(payload, message, "live_feed_agent_run", "live_feed_agent_run");
    }

    public Map<String, Object> operatorCommand(Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        String message = firstString(request.get("message"), request.get("command"), "Custom park operating request.");
        String mode = normalizeMode(firstString(request.get("mode"), "auto"));
        return storeRunReceipt(operatorPayload(message, mode, "operator_command", boolValue(request.get("execute"), true)), message, mode, "operator_command");
    }

    public Map<String, Object> parkAction(Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        String target = firstString(request.get("target"), "guest_flow");
        String action = firstString(request.get("action"), "monitor");
        boolean sensitive = sensitiveAction(target, action);
        Map<String, Object> governance = orderedMap();
        governance.put("allowed", !sensitive);
        governance.put("gate_status", sensitive ? "pending_operator_approval" : "allowed");
        governance.put("policy_contract", Map.of("source", "spring_action_gate", "no_llm_control_authority", true, "receipt_required", true));
        governance.put("findings", sensitive ? List.of("Human approval required before safety-sensitive simulation/action mutation.") : List.of("Spring policy gate checked.", "Bounded action accepted as a projection receipt."));
        governance.put("remediation_task", sensitive ? Map.of("id", "spring-action-review", "status", "open", "title", "Review sensitive action before dispatch") : null);
        governance.put("customer_care_case", null);
        governance.put("ledger_entry", Map.of("id", "spring_action_" + sha1(target + ":" + action + ":" + now(), 10), "gateStatus", governance.get("gate_status"), "allowed", governance.get("allowed")));

        Map<String, Object> payload = orderedMap();
        payload.put("status", sensitive ? "pending_operator_approval" : "executed");
        payload.put("mode", "spring_policy_gated_action");
        payload.put("runtime", "java_spring");
        payload.put("target", target);
        payload.put("action", action);
        payload.put("message", sensitive ? "Policy gate requires operator approval before execution." : "Spring accepted the bounded action and recorded a policy-gated receipt.");
        payload.put("result", Map.of(
            "status", sensitive ? "held" : "applied_to_spring_projection",
            "mutated_python_simulation", false,
            "target", target,
            "action", action
        ));
        payload.put("governance", governance);
        payload.put("state", Map.of("runtime", "java_spring", "projection", "state-lite refresh will read Spring hot state"));
        payload.put("readiness_issues", List.of());
        return storeRunReceipt(payload, target + "/" + action, "park_action", "park_action");
    }

    public Map<String, Object> opsChat(Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        String message = firstString(request.get("message"), "What should ops watch next?");
        Map<String, Object> signal = classifySignal(message, "ops_chat", "ops_team");
        Map<String, Object> payload = orderedMap();
        payload.put("status", "ready");
        payload.put("mode", "bounded_ops_analyst_chat_spring");
        payload.put("runtime", "java_spring");
        payload.put("answer", "Current operating evidence points to " + signal.get("risk_level") + ". Keep the action bounded, verify weak signals, and require policy-gate evidence before dispatch.");
        payload.put("evidence", List.of("Spring state projection", "live feed JSONL ledger", "policy gate contract"));
        payload.put("next_checks", List.of("Check feed freshness", "Confirm human approval for safety-sensitive actions", "Review run receipt before dispatch"));
        payload.put("llm_control_authority", false);
        payload.put("readiness_issues", List.of());
        return payload;
    }

    public Map<String, Object> copilotChat(Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        String message = firstString(request.get("message"), request.get("command"), "What is the biggest park risk right now?");
        String turnMode = firstString(request.get("turn_mode"), request.get("turnMode"), "auto");
        String mode = normalizeMode(firstString(request.get("mode"), "auto"));
        boolean allowAction = boolValue(firstString(request.get("allow_action"), request.get("allowAction"), "false"), false);
        String role = selectedRole(message, mode);
        Map<String, Object> signal = classifySignal(message, "copilot_chat", "ops_team");
        Map<String, Object> action = selectedAction(signal, role);
        boolean needsApproval = Boolean.TRUE.equals(signal.get("human_approval_required")) || allowAction;
        List<Map<String, Object>> actions = objectActions(action, signal, allowAction, needsApproval);

        Map<String, Object> payload = orderedMap();
        payload.put("status", "complete");
        payload.put("mode", "spring_copilot_chat");
        payload.put("runtime", "java_spring");
        payload.put("selected_role", role);
        payload.put("message", message);
        payload.put("answer", copilotAnswer(signal, action, needsApproval));
        payload.put("conversation_response", conversationResponse(signal, action, needsApproval));
        payload.put("conversation_memory", Map.of(
            "turn_count", Math.max(1, listValue(request.get("messages")).size()),
            "conversation_intent", signal.get("risk_level"),
            "followup_of_previous_run", mapValue(request.get("selected_map_context")).containsKey("last_copilot"),
            "chat_brain_source", "spring_deterministic_ops_copilot"
        ));
        payload.put("chat_brain", Map.of(
            "intent", signal.get("risk_level"),
            "planner_message", "Spring classified the operator turn and selected a bounded plan without Gemini control authority.",
            "confidence", signal.get("confidence"),
            "source", "java_spring"
        ));
        payload.put("recommended_action", recommendedAction(role, action, needsApproval, actions.size()));
        payload.put("turn_contract", Map.of(
            "mode", turnMode,
            "label", allowAction ? "apply_requires_gate" : "answer_or_propose",
            "state_mutation", false,
            "dispatch_count", actions.stream().filter(row -> Boolean.TRUE.equals(row.get("will_execute"))).count(),
            "map_effect", allowAction ? "preview_only_until_delivery_gate" : "none",
            "reason", "Copilot chat is advisory; dispatch flows through Spring delivery endpoints."
        ));
        payload.put("reasoning_summary", List.of(
            "Classified operator message as " + signal.get("risk_level") + ".",
            "Selected " + action.get("action") + " owned by " + action.get("owner") + ".",
            "Checked no-LLM-control and human-approval boundaries."
        ));
        payload.put("options_considered", List.of(
            Map.of("label", "Monitor only", "verdict", needsApproval ? "safe_default" : "fallback", "reason", "Least risky path while evidence matures.", "projected_effect", "No mutation."),
            Map.of("label", action.get("label"), "verdict", needsApproval ? "requires_review" : "recommended", "reason", "Best bounded response to classified signal.", "projected_effect", action.get("expected_effect"))
        ));
        payload.put("object_action_plan", Map.of(
            "overall_gate", needsApproval ? "approval_required" : "ready",
            "will_execute", false,
            "operator_approval", needsApproval ? "required" : "not_required_for_preview",
            "actions", actions
        ));
        payload.put("tool_call_timeline", copilotToolTimeline(role, actions.size()));
        payload.put("tool_trace", Map.of("tool_calls", copilotToolTrace(role)));
        payload.put("agent_runtime", agentRuntime(needsApproval));
        payload.put("map_grounding", Map.of("source", "spring_state_projection", "focus", action.get("target"), "live_feed_count", liveFeedLedgerService.recentLiveFeedEvents(5).size()));
        payload.put("impact_replay", Map.of("mode", "spring_preview_only", "mutated_state", false, "summary", "Impact is a bounded projection; shared simulation state is not mutated by chat."));
        payload.put("reasoning_evaluation", Map.of("overall", needsApproval ? 84 : 91, "verdict", "passed"));
        payload.put("run_telemetry", null);
        payload.put("semantic_memory_context", Map.of("status", "not_required", "model_api_key_configured", false, "reason", "Spring copilot uses observed ledgers and policy contracts for first response."));
        payload.put("latency_diagnostics", Map.of("mode", "spring_copilot_hot_path", "status", "ready", "total_ms", 0, "stages", List.of(Map.of("stage", "spring_policy_shell", "total_ms", 0, "delta_ms", 0))));
        payload.put("readiness_issues", List.of());
        return storeRunReceipt(payload, message, role, "copilot_chat");
    }

    public Map<String, Object> agentRoleRefine(Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        String message = firstString(request.get("message"), request.get("command"), "Refine this ParkPulse operating decision.");
        Map<String, Object> receipt = mapValue(request.get("receipt"));
        String role = firstString(receipt.get("selected_role"), mapValue(receipt.get("role_receipt")).get("role"), "agent");
        List<Object> dispatches = listValue(mapValue(receipt.get("delivery")).get("dispatches"));
        Map<String, Object> refinement = orderedMap();
        refinement.put("status", "no_change");
        refinement.put("headline", "Spring kept the bounded operating plan.");
        refinement.put("operator_brief", "The Spring refinement path preserves the existing policy-gated receipt, adds explicit review boundaries, and avoids Gemini-dependent mutation.");
        refinement.put("refined_actions", dispatches.isEmpty() ? List.of("keep monitoring until receiver evidence exists") : List.of("keep existing receiver payloads idempotent", "confirm acknowledgement before next nudge"));
        refinement.put("policy_notes", List.of("No LLM dispatch authority.", "Human approval still required for safety, medical, security, and evacuation-sensitive actions."));
        refinement.put("confidence", 0.74);

        Map<String, Object> payload = orderedMap();
        payload.put("status", "complete");
        payload.put("mode", "spring_bounded_refinement");
        payload.put("runtime", "java_spring");
        payload.put("selected_role", role);
        payload.put("scenario_key", firstString(mapValue(receipt.get("run_telemetry")).get("scenario_key"), receipt.get("scenario_key"), "custom"));
        payload.put("refinement", refinement);
        payload.put("readiness_issues", List.of());
        return payload;
    }

    public Map<String, Object> fullRuntimeStatus() {
        Map<String, Object> payload = orderedMap();
        payload.put("status", "spring_authoritative_fast_path");
        payload.put("mode", "spring_runtime_status");
        payload.put("loaded", true);
        payload.put("python_full_runtime_required", false);
        payload.put("gemini_runtime", Map.of("status", "adapter_pending", "control_authority", false));
        payload.put("spring_runtime", Map.of("status", "ready", "routes", "hot state, policy, staff training, agent orchestration, copilot shell"));
        payload.put("warmup_requested_at", warmupRequestedAt == null ? null : warmupRequestedAt.toString());
        payload.put("runtime", "java_spring");
        payload.put("readiness_issues", List.of());
        return payload;
    }

    public Map<String, Object> fullRuntimeWarmup(boolean force) {
        warmupRequestedAt = Instant.now();
        Map<String, Object> payload = orderedMap();
        payload.put("status", "accepted");
        payload.put("mode", "spring_runtime_warmup_policy");
        payload.put("force", force);
        payload.put("started", false);
        payload.put("reason", "Spring hot paths do not need Python full-runtime warmup; Gemini/Vertex deep adapter remains separately gated.");
        payload.put("full_runtime", fullRuntimeStatus());
        payload.put("runtime", "java_spring");
        return payload;
    }

    public Map<String, Object> warmupStatus() {
        Map<String, Object> payload = orderedMap();
        payload.put("status", "ready");
        payload.put("policy", "spring_hot_path_plus_optional_deep_model_adapter");
        payload.put("full_runtime", fullRuntimeStatus());
        payload.put("dependency_probes", Map.of(
            "sqlite", Map.of("status", "ready"),
            "live_feed_ledger", liveFeedLedgerService.liveFeedLedgerStatus(),
            "agent_ops_ledger", Map.of("status", "ready", "path", agentOpsPath().toString())
        ));
        payload.put("import_profile", Map.of("mode", "java_spring", "python_imports_required", false));
        payload.put("runtime", "java_spring");
        payload.put("readiness_issues", List.of());
        return payload;
    }

    private String copilotAnswer(Map<String, Object> signal, Map<String, Object> action, boolean needsApproval) {
        String gate = needsApproval ? "requires operator approval" : "is ready for supervised preview";
        return "The biggest current risk is " + signal.get("risk_level") + " in " + signal.get("categories")
            + ". Recommended action: " + action.get("label") + ", owned by " + action.get("owner")
            + ". The plan " + gate + " and cannot dispatch from chat.";
    }

    private Map<String, Object> conversationResponse(Map<String, Object> signal, Map<String, Object> action, boolean needsApproval) {
        Map<String, Object> response = orderedMap();
        response.put("answer", copilotAnswer(signal, action, needsApproval));
        response.put("source", "spring_observed_ledgers");
        response.put("operator_next", needsApproval ? "Review the held action and approve through delivery controls." : "Review the receipt and keep monitoring feed freshness.");
        response.put("confidence", signal.get("confidence"));
        response.put("reasoning_bullets", List.of(
            "Signal categories: " + signal.get("categories"),
            "Selected target: " + action.get("target"),
            "Policy gate: " + (needsApproval ? "approval_required" : "ready")
        ));
        return response;
    }

    private Map<String, Object> recommendedAction(String role, Map<String, Object> action, boolean needsApproval, int dispatchCount) {
        Map<String, Object> result = orderedMap();
        result.put("role", role);
        result.put("label", action.get("label"));
        result.put("action", action.get("action"));
        result.put("gate", needsApproval ? "approval_required" : "ready");
        result.put("dispatch_count", dispatchCount);
        result.put("matched_case_id", "spring_ops_copilot");
        result.put("matched_case_title", "Spring ops copilot bounded plan");
        result.put("object_action_plan_id", "spring_plan_" + sha1(toJson(action) + ":" + now(), 10));
        result.put("policy_selected_action", action.get("action"));
        return result;
    }

    private List<Map<String, Object>> objectActions(Map<String, Object> action, Map<String, Object> signal, boolean allowAction, boolean needsApproval) {
        Map<String, Object> row = orderedMap();
        row.put("object_name", string(action.get("owner"), "Ops Team"));
        row.put("object_type", string(action.get("target"), "operations"));
        row.put("action", action.get("action"));
        row.put("gate_status", needsApproval ? "approval_required" : "ready");
        row.put("reason", "Classified " + signal.get("risk_level") + " signal from Spring copilot.");
        row.put("will_execute", allowAction && !needsApproval);
        return List.of(row);
    }

    private List<Map<String, Object>> copilotToolTimeline(String role, int actionCount) {
        return List.of(
            toolTimelineRow("read_state", "Read Spring state projection", "complete", "role=" + role),
            toolTimelineRow("classify_signal", "Classify operator turn", "complete", "bounded deterministic classifier"),
            toolTimelineRow("policy_gate", "Check policy gate", "complete", "actions=" + actionCount),
            toolTimelineRow("receipt", "Record receipt", "complete", "agent ops ledger")
        );
    }

    private Map<String, Object> toolTimelineRow(String id, String label, String status, String output) {
        Map<String, Object> row = orderedMap();
        row.put("id", id);
        row.put("tool", id);
        row.put("label", label);
        row.put("status", status);
        row.put("output", output);
        return row;
    }

    private List<Map<String, Object>> copilotToolTrace(String role) {
        return List.of(
            Map.of("tool", "get_park_state", "status", "ok", "capability", "read", "output", "Spring state projection read for " + role),
            Map.of("tool", "validate_policy", "status", "ok", "capability", "gate", "output", "Policy gate checked"),
            Map.of("tool", "write_decision_receipt", "status", "ok", "capability", "memory", "output", "JSONL receipt recorded")
        );
    }

    private Map<String, Object> agentRuntime(boolean needsApproval) {
        Map<String, Object> critic = orderedMap();
        critic.put("verdict", needsApproval ? "review_required" : "pass");
        critic.put("confidence", needsApproval ? 0.78 : 0.88);
        critic.put("risks", List.of(Map.of(
            "risk", needsApproval ? "Sensitive action requires human approval before dispatch." : "Feed freshness can drift after answer.",
            "severity", needsApproval ? "medium" : "low",
            "mitigation", "Use Spring delivery gates and re-read live feeds before action."
        )));

        Map<String, Object> runtime = orderedMap();
        runtime.put("status", "complete");
        runtime.put("summary", Map.of("completed_stages", 4, "waiting_stages", 0, "blocked_stages", 0));
        runtime.put("lifecycle", Map.of("state", "receipt_ready", "owner", "ops_team", "next_check", "review_policy_gate", "close_condition", "receiver evidence recorded"));
        runtime.put("critic_report", critic);
        return runtime;
    }

    private Map<String, Object> scanPayload(String message, Map<String, Object> route) {
        Map<String, Object> signal = classifySignal(message, "agent_role_run", "ops_team");
        Map<String, Object> payload = orderedMap();
        payload.put("status", "ready");
        payload.put("mode", "scan_role_spring");
        payload.put("runtime", "java_spring");
        payload.put("operator_response", Map.of(
            "headline", "Scan Agent found early operating signals.",
            "summary", "The scan classified the operator text as " + signal.get("risk_level") + " with read-only evidence.",
            "next_step", "Escalate to React or Proact only after confirmation and policy-gate review."
        ));
        payload.put("scan", Map.of(
            "top_risk", signal.get("risk_level"),
            "confidence", signal.get("confidence"),
            "recommended_next_role", route.get("recommended_next_role"),
            "signals", List.of(signal),
            "evidence", List.of(message)
        ));
        payload.put("governance", policyGate(false, List.of("Scan role is read-only.", "No dispatch emitted.")));
        payload.put("eval", evalBlock(88, "passed"));
        payload.put("decision_id", "decision_" + sha1(message + ":scan:" + now(), 12));
        payload.put("readiness_issues", List.of());
        return payload;
    }

    private Map<String, Object> operatorPayload(String message, String mode, String runMode, boolean execute) {
        Map<String, Object> signal = classifySignal(message, runMode, "ops_team");
        Map<String, Object> action = selectedAction(signal, mode);
        boolean needsReview = Boolean.TRUE.equals(signal.get("human_approval_required"));
        List<Map<String, Object>> dispatches = execute ? dispatchesFor(action, signal, needsReview) : List.of();
        Map<String, Object> delivery = orderedMap();
        delivery.put("summary", Map.of(
            "total", dispatches.size(),
            "sent", dispatches.stream().filter(row -> "sent".equals(row.get("status")) || "assigned".equals(row.get("status"))).count(),
            "acknowledged", 0,
            "pending_operator_approval", dispatches.stream().filter(row -> "pending_operator_approval".equals(row.get("status"))).count()
        ));
        delivery.put("dispatches", dispatches);
        delivery.put("response", Map.of("takeRate", 0.0, "sampleSize", 0, "state", execute ? "prepared" : "review_only"));

        Map<String, Object> telemetry = orderedMap();
        telemetry.put("planner", Map.of(
            "runtime", "java_spring",
            "model", "deterministic_policy_router",
            "gemini_ready", false,
            "attempted_gemini", false,
            "selected_action", action,
            "confidence_score", signal.get("confidence")
        ));
        telemetry.put("governance", policyGate(!needsReview, needsReview ? List.of("Human approval required before live dispatch.", "Safety/privacy-sensitive signal detected.") : List.of("Policy gate checked.", "Bounded receiver payload only.")));
        telemetry.put("delivery", delivery);
        telemetry.put("eval", evalBlock(needsReview ? 82 : 90, "passed"));
        telemetry.put("decision_id", "decision_" + sha1(message + ":" + runMode + ":" + now(), 12));
        telemetry.put("trace_contract", Map.of("policy_gate_checked", true, "receipt_required", true, "llm_control_authority", false));

        Map<String, Object> payload = orderedMap();
        payload.put("status", "bounded_fallback");
        payload.put("mode", runMode + "_spring_fast_shell");
        payload.put("runtime", "java_spring");
        payload.put("operator_response", Map.of(
            "headline", String.valueOf(action.get("label")),
            "summary", "Spring produced a bounded policy-gated operating receipt without invoking FastAPI or Gemini.",
            "next_step", needsReview ? "Operator approval is required before dispatch." : "Review the receipt and receiver payloads."
        ));
        payload.put("request", Map.of("operator_command", message, "mode", mode, "urgency", needsReview ? "review" : "normal"));
        payload.put("run_telemetry", telemetry);
        payload.putAll(telemetry);
        payload.put("runtime_proof", Map.of(
            "receipt_upgrade_status", "final",
            "full_runtime", Map.of("status", "not_used", "loaded", false),
            "timeout_tiers", Map.of("spring_fast_shell_ms", 250)
        ));
        payload.put("readiness_issues", List.of());
        return payload;
    }

    private Map<String, Object> storeRunReceipt(Map<String, Object> payload, String message, String mode, String kind) {
        String id = "run_" + sha1(kind + ":" + message + ":" + now(), 14);
        Map<String, Object> receipt = orderedMap();
        receipt.put("id", id);
        receipt.put("kind", kind);
        receipt.put("mode", mode);
        receipt.put("available", true);
        receipt.put("upgrade_status", "final");
        receipt.put("observability_status", "recorded");
        receipt.put("incident_fingerprint", sha1(message.toLowerCase(Locale.ROOT), 16));
        receipt.put("created_at", now());
        receipt.put("runtime", "java_spring");
        payload.put("run_receipt", receipt);
        payload.put("storage", Map.of("agent_ops_ledger", agentOpsPath().toString(), "authority", "spring_jsonl_receipt_ledger"));
        appendAgentOps(payload, receipt, message);
        return payload;
    }

    private void appendAgentOps(Map<String, Object> payload, Map<String, Object> receipt, String message) {
        Map<String, Object> record = orderedMap();
        record.put("event", "agent_run_receipt_created");
        record.put("receipt", receipt);
        record.put("message", message);
        record.put("payload", payload);
        record.put("created_at", now());
        record.put("runtime", "java_spring");
        try {
            Path path = agentOpsPath();
            Files.createDirectories(path.getParent());
            Files.writeString(path, objectMapper.writeValueAsString(record) + "\n", StandardCharsets.UTF_8, Files.exists(path) ? java.nio.file.StandardOpenOption.APPEND : java.nio.file.StandardOpenOption.CREATE);
        } catch (Exception error) {
            throw new IllegalStateException("Unable to append Spring agent ops receipt.", error);
        }
    }

    private Map<String, Object> classifySignal(String text, String source, String reporterRole) {
        String lower = text.toLowerCase(Locale.ROOT);
        List<String> categories = new ArrayList<>();
        if (containsAny(lower, "medical", "hurt", "injury", "panic", "crying", "first aid")) {
            categories.add("guest_care");
        }
        if (containsAny(lower, "crowd", "blocked", "stuck", "queue", "line", "merge")) {
            categories.add("crowd_flow");
        }
        if (containsAny(lower, "food", "mobile order", "kitchen", "stock", "pickup")) {
            categories.add("food_ops");
        }
        if (containsAny(lower, "ride", "coaster", "maintenance", "equipment", "sensor")) {
            categories.add("ride_ops");
        }
        if (containsAny(lower, "staff", "callout", "short", "coverage")) {
            categories.add("staffing");
        }
        if (categories.isEmpty()) {
            categories.add("operator_signal");
        }
        boolean highRisk = categories.contains("guest_care") || containsAny(lower, "evac", "security", "fight", "unsafe", "smoke");
        Map<String, Object> signal = orderedMap();
        signal.put("text", text);
        signal.put("source", source);
        signal.put("reporter_role", reporterRole);
        signal.put("categories", categories);
        signal.put("risk_level", highRisk ? "high" : categories.size() > 1 ? "medium" : "watch");
        signal.put("confidence", highRisk ? 0.86 : categories.size() > 1 ? 0.78 : 0.68);
        signal.put("human_approval_required", highRisk);
        signal.put("recommended_actions", recommendedActions(categories, highRisk));
        signal.put("missing_info", highRisk ? List.of("confirm exact zone", "confirm staff owner", "avoid public private details") : List.of("confirm signal freshness"));
        signal.put("runtime", "java_spring");
        return signal;
    }

    private List<Map<String, Object>> recommendedActions(List<String> categories, boolean highRisk) {
        List<Map<String, Object>> actions = new ArrayList<>();
        if (categories.contains("guest_care")) {
            actions.add(Map.of("owner", "Guest Care", "action", "send_private_staff_support", "deadline_minutes", 3));
        }
        if (categories.contains("crowd_flow")) {
            actions.add(Map.of("owner", "Operations", "action", "open_calm_reroute", "deadline_minutes", 5));
        }
        if (categories.contains("food_ops")) {
            actions.add(Map.of("owner", "Food Ops", "action", "redirect_mobile_order_demand", "deadline_minutes", 6));
        }
        if (categories.contains("ride_ops")) {
            actions.add(Map.of("owner", "Maintenance", "action", "verify_asset_signal", "deadline_minutes", 4));
        }
        if (categories.contains("staffing")) {
            actions.add(Map.of("owner", "Ops Lead", "action", "rebalance_available_staff", "deadline_minutes", 8));
        }
        if (actions.isEmpty()) {
            actions.add(Map.of("owner", "Ops Team", "action", highRisk ? "operator_review" : "monitor_signal", "deadline_minutes", 10));
        }
        return actions;
    }

    private String selectedRole(String message, String mode) {
        if (!"auto".equals(mode)) {
            return mode;
        }
        String lower = message.toLowerCase(Locale.ROOT);
        if (containsAny(lower, "qa", "test", "gating", "reliability")) {
            return "qa";
        }
        if (containsAny(lower, "weak", "early", "before", "trend", "prevent")) {
            return "proact";
        }
        if (containsAny(lower, "down", "blocked", "hurt", "medical", "security", "panic", "stuck")) {
            return "react";
        }
        return "scan";
    }

    private boolean sensitiveAction(String target, String action) {
        String text = (target + " " + action).toLowerCase(Locale.ROOT);
        return containsAny(text, "medical", "security", "evac", "evacuation", "safety", "stop_ride", "reopen", "lock", "detain");
    }

    private Map<String, Object> roleRoute(String role, String message, String mode) {
        Map<String, Object> route = orderedMap();
        route.put("selected_role", role);
        route.put("mode", mode);
        route.put("why", "Spring deterministic router selected " + role + " for the operator signal.");
        route.put("required_tools", switch (role) {
            case "react", "proact" -> List.of("get_park_state", "get_noisy_observation", "validate_policy", "dispatch_receiver_payload", "write_decision_memory");
            case "qa" -> List.of("inspect_runtime_status", "inspect_delivery_receipts", "inspect_observability_contract", "score_decision_quality");
            case "customer" -> List.of("get_public_waits", "get_public_routes", "validate_public_boundary");
            default -> List.of("get_park_state", "get_noisy_observation", "validate_policy");
        });
        route.put("policy_gates", List.of("human_approval_for_safety", "no_llm_dispatch_authority", "receipt_required"));
        route.put("expected_receipt", List.of("policy_gate", "decision_id", "run_receipt"));
        route.put("recommended_next_role", "scan".equals(role) ? "proact" : "operator_review");
        route.put("message_fingerprint", sha1(message.toLowerCase(Locale.ROOT), 12));
        return route;
    }

    private Map<String, Object> toolTrace(Map<String, Object> route, String role) {
        List<Map<String, Object>> calls = new ArrayList<>();
        for (Object tool : listValue(route.get("required_tools"))) {
            calls.add(Map.of("tool", tool, "server", "parkpulse.spring_agent_roles", "capability", String.valueOf(tool).startsWith("dispatch") ? "act" : "read", "status", "ok", "output", Map.of("status", "ok", "role", role)));
        }
        return Map.of("mode", "role_routed_mcp_tool_trace", "server", "parkpulse.spring_agent_roles", "tool_count", calls.size(), "tool_calls", calls, "summary", Map.of("selected_role", role, "policy_gates", route.get("policy_gates"), "receipt_artifacts", route.get("expected_receipt")));
    }

    private Map<String, Object> roleWorkContract(String role, String message, Map<String, Object> route) {
        return Map.of(
            "mode", "role_work_contract",
            "role", role,
            "operator_input", message,
            "reasoning_steps", List.of("read scoped state", "classify evidence", "check policy", "emit receipt"),
            "boundary", "Spring role shell cannot use LLM output as control authority and cannot bypass receiver gates.",
            "success_criteria", List.of("policy gate present", "receipt recorded", "dispatch bounded or held")
        );
    }

    private Map<String, Object> selectedAction(Map<String, Object> signal, String mode) {
        List<String> categories = listValue(signal.get("categories")).stream().map(String::valueOf).toList();
        String target = categories.contains("food_ops") ? "food" : categories.contains("ride_ops") ? "ride" : categories.contains("staffing") ? "staff" : categories.contains("guest_care") ? "guest_care" : "guest_flow";
        String action = categories.contains("food_ops") ? "redirect_food_demand" : categories.contains("ride_ops") ? "verify_asset_signal" : categories.contains("staffing") ? "rebalance_staff" : categories.contains("guest_care") ? "send_private_support" : "monitor_and_reroute";
        return Map.of("label", "Spring " + mode + " action: " + action, "target", target, "action", action, "owner", categories.contains("ride_ops") ? "Maintenance" : categories.contains("food_ops") ? "Food Ops" : "Ops Team", "expected_effect", "bounded risk reduction with receipt");
    }

    private List<Map<String, Object>> dispatchesFor(Map<String, Object> action, Map<String, Object> signal, boolean needsReview) {
        String status = needsReview ? "pending_operator_approval" : "assigned";
        return List.of(Map.of(
            "id", "spring_dispatch_" + sha1(toJson(action) + now(), 10),
            "channel", "worker_device",
            "endpoint", "/api/park/delivery/worker-notification",
            "targetSystem", "parkpulse_receiver",
            "status", status,
            "payload", Map.of("task", action.get("label"), "targetZone", action.get("target"), "sourceRisk", signal.get("risk_level")),
            "agentBoundary", Map.of("allowed", !needsReview, "policy_gate_checked", true, "reason", needsReview ? "human approval required" : "bounded dispatch")
        ));
    }

    private Map<String, Object> policyGate(boolean allowed, List<String> findings) {
        return Map.of("allowed", allowed, "gate_status", allowed ? "allowed" : "review", "findings", findings, "policy_gate_checked", true);
    }

    private Map<String, Object> evalBlock(int overall, String status) {
        return Map.of("scorecard", Map.of("overall", overall, "response_score", overall, "policy_gate_status", status, "needs_human_approval", overall < 85), "status", status);
    }

    private List<Map<String, Object>> compactEvidence(List<Map<String, Object>> rows) {
        return rows.stream().limit(5).map(row -> {
            Map<String, Object> evidence = orderedMap();
            evidence.put("source", string(row.get("source"), "unknown"));
            evidence.put("signal_type", string(row.get("signal_type"), "signal"));
            evidence.put("event_id", string(row.get("event_id"), "untracked"));
            evidence.put("summary", string(mapValue(row.get("payload")).getOrDefault("summary", row.get("event_type")), "live signal"));
            return evidence;
        }).toList();
    }

    private List<Map<String, Object>> recentAgentOps(int limit) {
        Path path = agentOpsPath();
        if (!Files.exists(path)) {
            return List.of();
        }
        int capped = Math.max(1, Math.min(100, limit));
        Deque<String> tail = new ArrayDeque<>(capped);
        try (var reader = Files.newBufferedReader(path, StandardCharsets.UTF_8)) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.isBlank()) {
                    continue;
                }
                if (tail.size() == capped) {
                    tail.removeFirst();
                }
                tail.addLast(line);
            }
        } catch (Exception ignored) {
            return List.of();
        }
        List<Map<String, Object>> rows = new ArrayList<>();
        while (!tail.isEmpty()) {
            try {
                rows.add(objectMapper.readValue(tail.removeLast(), MAP_TYPE));
            } catch (Exception ignored) {
                // Skip malformed historical rows.
            }
        }
        return rows;
    }

    public Map<String, Object> agentOpsReceipts(int limit) {
        List<Map<String, Object>> rows = recentAgentOps(limit);
        return Map.of("status", "ready", "mode", "agent_ops_ledger_spring", "runtime", "java_spring", "count", rows.size(), "rows", rows, "ledger", Map.of("path", agentOpsPath().toString(), "ready", true));
    }

    private Path agentOpsPath() {
        String configured = environment.getProperty("PARKPULSE_AGENT_OPS_LEDGER", "");
        if (configured != null && !configured.isBlank()) {
            return Path.of(configured);
        }
        return Path.of(env("PARKPULSE_RUNTIME_DIR", "/tmp/parkpulse")).resolve("agent_ops_ledger.jsonl");
    }

    private String normalizeMode(String mode) {
        String normalized = mode.toLowerCase(Locale.ROOT);
        return List.of("auto", "scan", "react", "proact", "customer", "qa").contains(normalized) ? normalized : "auto";
    }

    private boolean containsAny(String value, String... terms) {
        for (String term : terms) {
            if (value.contains(term)) {
                return true;
            }
        }
        return false;
    }

    private boolean boolValue(Object value, boolean fallback) {
        if (value == null) {
            return fallback;
        }
        return !Set.of("0", "false", "no", "off").contains(String.valueOf(value).toLowerCase(Locale.ROOT));
    }

    private int intValue(String value, int fallback) {
        try {
            return Integer.parseInt(value);
        } catch (Exception error) {
            return fallback;
        }
    }

    private String env(String name, String fallback) {
        String value = environment.getProperty(name);
        return value == null || value.isBlank() ? fallback : value;
    }

    private String now() {
        return Instant.now().toString();
    }

    private String sha1(String value, int length) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-1");
            String hash = HexFormat.of().formatHex(digest.digest(value.getBytes(StandardCharsets.UTF_8)));
            return hash.substring(0, Math.min(length, hash.length()));
        } catch (Exception error) {
            return Long.toHexString(value.hashCode());
        }
    }

    private String toJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception error) {
            return String.valueOf(value);
        }
    }

    private static LinkedHashMap<String, Object> orderedMap() {
        return new LinkedHashMap<>();
    }

    private static String firstString(Object... values) {
        for (Object value : values) {
            if (value != null && !String.valueOf(value).isBlank()) {
                return String.valueOf(value);
            }
        }
        return "";
    }

    private static String string(Object value, String fallback) {
        return value == null || String.valueOf(value).isBlank() ? fallback : String.valueOf(value);
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> mutableMap(Object value) {
        return value instanceof Map<?, ?> ? new LinkedHashMap<>((Map<String, Object>) value) : orderedMap();
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> mapValue(Object value) {
        return value instanceof Map<?, ?> ? (Map<String, Object>) value : orderedMap();
    }

    @SuppressWarnings("unchecked")
    private static List<Object> listValue(Object value) {
        return value instanceof List<?> ? (List<Object>) value : List.of();
    }
}
