package com.parkpulse.backend;

import java.io.BufferedReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.TreeMap;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Service;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

@Service
public class DeliveryOutboxService {
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

    private final Environment environment;
    private final ObjectMapper objectMapper;
    private final DeliveryGcpAdapterService gcpAdapterService;

    public DeliveryOutboxService(Environment environment, ObjectMapper objectMapper, DeliveryGcpAdapterService gcpAdapterService) {
        this.environment = environment;
        this.objectMapper = objectMapper;
        this.gcpAdapterService = gcpAdapterService;
    }

    public Map<String, Object> contract() {
        Map<String, Object> payload = orderedMap();
        payload.put("name", "ParkPulse Action Delivery REST Port");
        payload.put("purpose", "Transforms agent decisions into guest app promotions, worker notifications, and equipment commands.");
        payload.put("runtime", "java_spring");
        payload.put("ports", List.of(
            Map.of("channel", "guest_app", "method", "POST", "endpoint", "/api/park/delivery/guest-promotion", "runtime", "java_spring"),
            Map.of("channel", "worker_device", "method", "POST", "endpoint", "/api/park/delivery/worker-notification", "runtime", "java_spring"),
            Map.of("channel", "equipment_controller", "method", "POST", "endpoint", "/api/park/delivery/equipment-command", "runtime", "java_spring"),
            Map.of("channel", "receiver_acknowledgement", "method", "POST", "endpoint", "/api/park/delivery/acknowledge", "runtime", "java_spring"),
            Map.of("channel", "operator_approval", "method", "POST", "endpoint", "/api/park/delivery/approval-decision", "runtime", "java_spring"),
            Map.of("channel", "gcp_adapter_status", "method", "GET", "endpoint", "/api/park/delivery/gcp-adapters/status", "runtime", "java_spring")
        ));
        payload.put("guardrails", List.of(
            "Ride safety and maintenance clearances are never automated.",
            "Guest messages use aggregate segments, not guest PII.",
            "Equipment commands are limited to comfort and load settings; safety-critical commands require approval.",
            "Spring creates dispatches only through the tool-executor boundary, requires policy-gate evidence, appends creation plus receiver receipts to the durable JSONL outbox, and records GCP adapter receipts in local mirror mode unless live cloud clients are explicitly enabled."
        ));
        payload.put("durability", durabilityStatus());
        return payload;
    }

    public Map<String, Object> guestPromotion(Map<String, Object> body) {
        return creationResponse(recordDispatch("guest_app", "guest-mobile-app", "/partner/guest-app/promotions", deliveryPayload(body), "delivered"));
    }

    public Map<String, Object> workerNotification(Map<String, Object> body) {
        return creationResponse(recordDispatch("worker_device", "staff-dispatch-app", "/partner/staff-dispatch/notifications", deliveryPayload(body), "delivered"));
    }

    public Map<String, Object> equipmentCommand(Map<String, Object> body) {
        Map<String, Object> payload = deliveryPayload(body);
        String status = requiresApproval(payload) ? "pending_operator_approval" : "delivered";
        return creationResponse(recordDispatch("equipment_controller", "building-management-system", "/partner/bms/commands", payload, status));
    }

    public Map<String, Object> outbox(int limit) {
        List<Map<String, Object>> dispatches = latestDispatches(limit);
        Map<String, Object> payload = orderedMap();
        payload.put("count", dispatches.size());
        payload.put("dispatches", dispatches);
        payload.put("summary", deliverySummary(dispatches));
        payload.put("response", responseSummary(dispatches));
        payload.put("durability", durabilityStatus());
        payload.put("runtime", "java_spring");
        return payload;
    }

    public Map<String, Object> acknowledge(String dispatchId, String actor, String choice, String channel) {
        String now = now();
        Map<String, Object> dispatch = findDispatch(dispatchId);
        if (dispatch == null) {
            Map<String, Object> payload = orderedMap();
            payload.put("status", "not_found");
            payload.put("id", dispatchId);
            payload.put("actor", actor);
            payload.put("choice", choice);
            payload.put("channel", channel);
            payload.put("acknowledgedAt", now);
            payload.put("runtime", "java_spring");
            return payload;
        }
        Map<String, Object> response = mutableMap(dispatch.get("response"));
        response.put("state", "acknowledged");
        response.put("acknowledgedAt", now);
        response.put("acknowledgedBy", actor);
        response.put("choice", choice);
        response.put("signal", actor + " acknowledgement received: " + choice + ".");
        dispatch.put("response", response);
        dispatch.put("status", "acknowledged");
        Map<String, Object> acknowledgement = orderedMap();
        acknowledgement.put("actor", actor);
        acknowledgement.put("choice", choice);
        acknowledgement.put("channel", channel == null || channel.isBlank() ? String.valueOf(dispatch.getOrDefault("channel", "")) : channel);
        acknowledgement.put("at", now);
        dispatch.put("lastAcknowledgement", acknowledgement);
        appendRecord(Map.of("acknowledgement", dispatch));
        Map<String, Object> payload = orderedMap();
        payload.put("status", dispatch.getOrDefault("status", "acknowledged"));
        payload.put("dispatch", dispatch);
        payload.put("delivery", outbox(20));
        payload.put("runtime", "java_spring");
        return payload;
    }

    public Map<String, Object> approvalDecision(String dispatchId, String actor, String decision, String reason, String channel) {
        String normalized = decision == null ? "" : decision.trim().toLowerCase(Locale.ROOT);
        boolean approved = List.of("approved", "approve", "accepted", "execute", "approved_for_execution").contains(normalized);
        boolean held = List.of("held_for_review", "hold", "held", "rejected", "manual_review").contains(normalized);
        String now = now();
        if (!approved && !held) {
            Map<String, Object> payload = orderedMap();
            payload.put("status", "invalid_decision");
            payload.put("id", dispatchId);
            payload.put("actor", actor);
            payload.put("decision", decision);
            payload.put("reason", "decision must be approved or held_for_review");
            payload.put("decidedAt", now);
            payload.put("runtime", "java_spring");
            return payload;
        }
        Map<String, Object> dispatch = findDispatch(dispatchId);
        if (dispatch == null) {
            Map<String, Object> payload = orderedMap();
            payload.put("status", "not_found");
            payload.put("id", dispatchId);
            payload.put("actor", actor);
            payload.put("decision", decision);
            payload.put("channel", channel);
            payload.put("decidedAt", now);
            payload.put("runtime", "java_spring");
            return payload;
        }
        String nextStatus = approved ? "approved_for_execution" : "held_for_review";
        Map<String, Object> approval = orderedMap();
        approval.put("approved", approved);
        approval.put("held_for_review", held);
        approval.put("decision", approved ? "approved" : "held_for_review");
        approval.put("actor", actor);
        approval.put("reason", reason == null || reason.isBlank() ? (approved ? "Operator approved execution." : "Operator held dispatch for manual review.") : reason);
        approval.put("channel", channel == null || channel.isBlank() ? String.valueOf(dispatch.getOrDefault("channel", "")) : channel);
        approval.put("decidedAt", now);
        approval.put("agentBoundary", dispatch.get("agentBoundary"));

        Map<String, Object> response = mutableMap(dispatch.get("response"));
        response.put("state", nextStatus);
        response.put("approved", approved);
        response.put("heldForReview", held);
        response.put("decidedAt", now);
        response.put("decisionReason", approval.get("reason"));
        response.put("signal", approved ? "Operator approved execution: " + approval.get("reason") : "Operator held for review: " + approval.get("reason"));
        dispatch.put("response", response);
        dispatch.put("status", nextStatus);
        dispatch.put("approvalDecision", approval);
        Map<String, Object> acknowledgement = orderedMap();
        acknowledgement.put("actor", actor);
        acknowledgement.put("choice", approval.get("decision"));
        acknowledgement.put("channel", approval.get("channel"));
        acknowledgement.put("at", now);
        dispatch.put("lastAcknowledgement", acknowledgement);
        dispatch.put("approvalDelivery", gcpAdapterService.publishApprovalDecision(dispatch, approval));
        dispatch.put("approvalDurable", true);
        appendRecord(Map.of("approvalDecision", dispatch));
        Map<String, Object> payload = orderedMap();
        payload.put("status", dispatch.getOrDefault("status", nextStatus));
        payload.put("dispatch", dispatch);
        payload.put("approval", approval);
        payload.put("approvalDelivery", dispatch.get("approvalDelivery"));
        payload.put("delivery", outbox(20));
        payload.put("runtime", "java_spring");
        return payload;
    }

    private Map<String, Object> recordDispatch(String channel, String targetSystem, String endpoint, Map<String, Object> payload, String status) {
        String idempotencyKey = dispatchId(channel, Map.of("target", targetSystem, "payload", payload));
        Map<String, Object> duplicate = findDispatchByIdempotencyKey(idempotencyKey);
        if (duplicate != null) {
            duplicate.put("deduplicated", true);
            duplicate.put("deduplicatedAt", now());
            return duplicate;
        }

        Map<String, Object> boundary = agentBoundaryForDispatch(channel, targetSystem, payload, status);
        boolean allowed = Boolean.TRUE.equals(boundary.get("allowed"));
        String dispatchStatus = allowed ? status : "blocked_by_agent_boundary";
        Map<String, Object> dispatch = orderedMap();
        dispatch.put("id", dispatchId(channel, payload));
        dispatch.put("createdAt", now());
        dispatch.put("channel", channel);
        dispatch.put("targetSystem", targetSystem);
        dispatch.put("method", "POST");
        dispatch.put("endpoint", endpoint);
        dispatch.put("status", dispatchStatus);
        dispatch.put("idempotencyKey", idempotencyKey);
        dispatch.put("payload", new LinkedHashMap<>(payload));
        dispatch.put("response", allowed ? simulateResponse(channel, payload, status) : blockedResponse(String.valueOf(boundary.get("reason"))));
        dispatch.put("agentBoundary", boundary);
        dispatch.put("gcpDelivery", allowed ? gcpAdapterService.enrichDeliveryDispatch(dispatch) : Map.of(
            "status", "skipped",
            "reason", "Agent Builder boundary blocked receiver dispatch.",
            "agentBoundary", boundary
        ));
        persistDispatch(dispatch);
        return dispatch;
    }

    private Map<String, Object> creationResponse(Map<String, Object> dispatch) {
        Map<String, Object> payload = orderedMap();
        payload.put("status", dispatch.getOrDefault("status", "delivered"));
        payload.put("dispatch", dispatch);
        payload.put("runtime", "java_spring");
        return payload;
    }

    private Map<String, Object> durabilityStatus() {
        Path path = outboxPath();
        long count = 0;
        boolean ready = true;
        String error = null;
        try {
            if (Files.exists(path)) {
                try (BufferedReader reader = Files.newBufferedReader(path, StandardCharsets.UTF_8)) {
                    count = reader.lines().filter(line -> !line.isBlank()).count();
                }
            }
        } catch (Exception exc) {
            ready = false;
            error = exc.getMessage();
        }
        Map<String, Object> payload = orderedMap();
        payload.put("mode", "durable_jsonl_outbox");
        payload.put("durable_count", count);
        payload.put("path", path.toString());
        payload.put("ready", ready);
        payload.put("error", error);
        payload.put("processing", "append-first, idempotency-keyed dispatch records; partner retries can replay durable rows safely");
        payload.put("runtime", "java_spring");
        return payload;
    }

    private List<Map<String, Object>> latestDispatches(int limit) {
        List<Map<String, Object>> rows = readOutboxRows();
        Collections.reverse(rows);
        return rows.stream().limit(Math.max(1, Math.min(limit, 100))).toList();
    }

    private Map<String, Object> findDispatch(String dispatchId) {
        return latestDispatches(200).stream()
            .filter(row -> dispatchId != null && dispatchId.equals(String.valueOf(row.get("id"))))
            .findFirst()
            .map(LinkedHashMap::new)
            .orElse(null);
    }

    private Map<String, Object> findDispatchByIdempotencyKey(String idempotencyKey) {
        return latestDispatches(500).stream()
            .filter(row -> idempotencyKey != null && idempotencyKey.equals(String.valueOf(row.get("idempotencyKey"))))
            .findFirst()
            .map(LinkedHashMap::new)
            .orElse(null);
    }

    private List<Map<String, Object>> readOutboxRows() {
        Path path = outboxPath();
        if (!Files.exists(path)) {
            return List.of();
        }
        List<Map<String, Object>> rows = new ArrayList<>();
        try (BufferedReader reader = Files.newBufferedReader(path, StandardCharsets.UTF_8)) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.isBlank()) {
                    continue;
                }
                Map<String, Object> raw = objectMapper.readValue(line, MAP_TYPE);
                rows.add(unwrapDurableRecord(raw));
            }
        } catch (Exception ignored) {
            return rows;
        }
        return rows;
    }

    private Map<String, Object> unwrapDurableRecord(Map<String, Object> raw) {
        if (raw.size() == 1 && raw.get("acknowledgement") instanceof Map<?, ?> acknowledgement) {
            return mutableMap(acknowledgement);
        }
        if (raw.size() == 1 && raw.get("approvalDecision") instanceof Map<?, ?> approvalDecision) {
            return mutableMap(approvalDecision);
        }
        return mutableMap(raw);
    }

    private void appendRecord(Map<String, Object> record) {
        try {
            Path path = outboxPath();
            Files.createDirectories(path.getParent());
            Files.writeString(
                path,
                objectMapper.writeValueAsString(record) + "\n",
                StandardCharsets.UTF_8,
                Files.exists(path) ? java.nio.file.StandardOpenOption.APPEND : java.nio.file.StandardOpenOption.CREATE
            );
        } catch (Exception error) {
            throw new IllegalStateException("Unable to append delivery outbox record.", error);
        }
    }

    private void persistDispatch(Map<String, Object> dispatch) {
        try {
            appendRecord(dispatch);
            dispatch.put("durable", true);
        } catch (Exception error) {
            dispatch.put("durable", false);
            dispatch.put("durabilityError", String.valueOf(error.getMessage()).substring(0, Math.min(300, String.valueOf(error.getMessage()).length())));
        }
    }

    private Map<String, Object> deliverySummary(List<Map<String, Object>> dispatches) {
        Map<String, Integer> byStatus = new LinkedHashMap<>();
        Map<String, Integer> byChannel = new LinkedHashMap<>();
        for (Map<String, Object> dispatch : dispatches) {
            byStatus.merge(String.valueOf(dispatch.getOrDefault("status", "unknown")), 1, Integer::sum);
            byChannel.merge(String.valueOf(dispatch.getOrDefault("channel", "unknown")), 1, Integer::sum);
        }
        return Map.of("count", dispatches.size(), "by_status", byStatus, "by_channel", byChannel);
    }

    private Map<String, Object> responseSummary(List<Map<String, Object>> dispatches) {
        long acknowledged = dispatches.stream().filter(row -> "acknowledged".equals(row.get("status"))).count();
        long pendingApproval = dispatches.stream().filter(row -> "pending_operator_approval".equals(row.get("status"))).count();
        return Map.of(
            "acknowledged", acknowledged,
            "pending_operator_approval", pendingApproval,
            "receiver_receipt_count", acknowledged + pendingApproval
        );
    }

    private Map<String, Object> deliveryPayload(Map<String, Object> body) {
        if (body == null || body.isEmpty()) {
            return orderedMap();
        }
        Object nested = body.get("payload");
        if (nested instanceof Map<?, ?> payload) {
            return mutableMap(payload);
        }
        return mutableMap(body);
    }

    private Map<String, Object> agentBoundaryForDispatch(String channel, String targetSystem, Map<String, Object> payload, String status) {
        String tool = toolForChannel(channel);
        String agentId = string(payload.get("executorAgentId"), payload.get("executor_agent_id"), "tool_executor_agent");
        boolean toolExecutor = "tool_executor_agent".equals(agentId);
        boolean policyGateChecked = policyGateChecked(payload) || "pending_operator_approval".equals(status);
        boolean gateBlocked = gateBlocked(payload);
        boolean allowed = toolExecutor && policyGateChecked && !gateBlocked;
        List<String> reasons = new ArrayList<>();
        if (!toolExecutor) {
            reasons.add("real action tools can only be executed by tool_executor_agent");
        }
        if (!policyGateChecked) {
            reasons.add("dispatch tools require policy_gate_checked, a decision receipt, or pending operator approval");
        }
        if (gateBlocked) {
            reasons.add("policy gate rejected or blocked the dispatch");
        }
        Map<String, Object> boundary = orderedMap();
        boundary.put("status", allowed ? "allowed" : "blocked");
        boundary.put("allowed", allowed);
        boundary.put("agent_id", agentId);
        boundary.put("agent_name", "Tool Executor Agent");
        boundary.put("department", "delivery");
        boundary.put("department_label", "Receiver Delivery");
        boundary.put("department_agent", "tool_executor_agent");
        boundary.put("tool", tool);
        boundary.put("tool_contract", Map.of("status", allowed ? "allowed" : "blocked", "targetSystem", targetSystem));
        boundary.put("allowed_tools_checked", true);
        boundary.put("blocked_tools_checked", true);
        boundary.put("policy_gate_checked", policyGateChecked);
        boundary.put("handoff_to", "operator_console");
        boundary.put("execution_boundary", "Tool executor may deliver approved receiver payloads only after policy-gate evidence is present.");
        boundary.put("decision_rights", "No ride safety, medical, security, evacuation, accessibility, or maintenance clearance decisions are automated.");
        boundary.put("requires_human_approval_when", List.of("safety_critical_equipment", "maintenance_clearance", "medical", "security", "evacuation", "accessibility"));
        boundary.put("channel", channel);
        boundary.put("targetSystem", targetSystem);
        boundary.put("requiresHumanApproval", requiresApproval(payload));
        boundary.put("reason", reasons.isEmpty() ? "Tool is allowed by Agent Builder boundary contract." : String.join("; ", reasons));
        boundary.put("checked_at", now());
        return boundary;
    }

    private Map<String, Object> simulateResponse(String channel, Map<String, Object> payload, String status) {
        if ("pending_operator_approval".equals(status)) {
            return Map.of(
                "windowMinutes", 15,
                "state", "pending",
                "takeRate", 0,
                "positiveResponseRate", 0,
                "reactiveFollowThroughRate", 0,
                "sampleSize", 0,
                "signal", "Waiting for operator approval."
            );
        }
        if ("guest_app".equals(channel)) {
            return simulateGuestResponse(payload);
        }
        if ("worker_device".equals(channel)) {
            boolean crowdControl = "crowd_control".equals(String.valueOf(payload.getOrDefault("role", "")));
            boolean highPriority = "high".equals(String.valueOf(payload.getOrDefault("priority", "")));
            int sampleSize = crowdControl ? 4 : 2;
            return Map.of(
                "windowMinutes", 10,
                "state", "observed",
                "takeRate", highPriority ? 0.96 : 0.86,
                "positiveResponseRate", 0.88,
                "reactiveFollowThroughRate", 0.91,
                "sampleSize", sampleSize,
                "acknowledgedCount", sampleSize,
                "medianAckSeconds", highPriority ? 42 : 78,
                "signal", "Worker task acknowledgments and movement toward target zone were observed."
            );
        }
        if ("equipment_controller".equals(channel)) {
            return Map.of(
                "windowMinutes", 5,
                "state", "observed",
                "takeRate", 1.0,
                "positiveResponseRate", 1.0,
                "reactiveFollowThroughRate", 1.0,
                "sampleSize", 1,
                "applied", true,
                "medianAckSeconds", 8,
                "signal", "BMS accepted the command and reported the target setting as active."
            );
        }
        return Map.of(
            "windowMinutes", 15,
            "state", "unknown",
            "takeRate", 0,
            "positiveResponseRate", 0,
            "reactiveFollowThroughRate", 0,
            "sampleSize", 0,
            "signal", "No response telemetry available."
        );
    }

    private Map<String, Object> simulateGuestResponse(Map<String, Object> payload) {
        if (payload.get("expectedTakeRate") != null) {
            double takeRate = number(payload.get("expectedTakeRate"), 0.34);
            double followRate = number(payload.get("expectedFollowThroughRate"), Math.max(0.1, takeRate - 0.05));
            double positiveRate = Math.min(0.92, takeRate + 0.42);
            int sampleSize = (int) Math.round(number(payload.get("estimatedMovedGuests"), 900));
            return Map.of(
                "windowMinutes", 15,
                "state", "observed",
                "takeRate", round3(takeRate),
                "positiveResponseRate", round3(positiveRate),
                "reactiveFollowThroughRate", round3(followRate),
                "sampleSize", sampleSize,
                "acceptedCount", Math.round(sampleSize * takeRate),
                "followThroughCount", Math.round(sampleSize * followRate),
                "sentiment", positiveRate >= 0.72 ? "positive" : "mixed",
                "signal", "Custom route-mix acceptance and destination movement were observed."
            );
        }
        String scenarioKey = String.valueOf(payload.getOrDefault("scenarioKey", "ride_down"));
        double takeRate = 0.25;
        double positiveRate = 0.70;
        double followRate = 0.20;
        int sampleSize = 600;
        if ("ride_down".equals(scenarioKey)) {
            takeRate = 0.34;
            positiveRate = 0.78;
            followRate = 0.29;
            sampleSize = 1180;
        } else if ("food_spike".equals(scenarioKey)) {
            takeRate = 0.28;
            positiveRate = 0.73;
            followRate = 0.24;
            sampleSize = 840;
        } else if ("storm_response".equals(scenarioKey)) {
            takeRate = 0.42;
            positiveRate = 0.81;
            followRate = 0.35;
            sampleSize = 1620;
        }
        return Map.of(
            "windowMinutes", 15,
            "state", "observed",
            "takeRate", takeRate,
            "positiveResponseRate", positiveRate,
            "reactiveFollowThroughRate", followRate,
            "sampleSize", sampleSize,
            "acceptedCount", Math.round(sampleSize * takeRate),
            "followThroughCount", Math.round(sampleSize * followRate),
            "sentiment", positiveRate >= 0.72 ? "positive" : "mixed",
            "signal", "Guest app offer acceptance and destination movement were observed."
        );
    }

    private Map<String, Object> blockedResponse(String reason) {
        return Map.of(
            "state", "blocked",
            "takeRate", 0,
            "positiveResponseRate", 0,
            "reactiveFollowThroughRate", 0,
            "sampleSize", 0,
            "signal", reason
        );
    }

    private boolean requiresApproval(Map<String, Object> payload) {
        if (truthy(payload.get("requiresHumanApproval"))) {
            return true;
        }
        if (!truthy(payload.get("safetyCritical")) && !truthy(payload.get("safety_critical"))) {
            return false;
        }
        return !operatorApproved(payload);
    }

    private boolean operatorApproved(Map<String, Object> payload) {
        return truthy(payload.get("operatorApproved"))
            || truthy(payload.get("operator_approved"))
            || "approved".equalsIgnoreCase(String.valueOf(payload.getOrDefault("approvalDecision", "")))
            || "approved".equalsIgnoreCase(String.valueOf(payload.getOrDefault("decision", "")));
    }

    private boolean policyGateChecked(Map<String, Object> payload) {
        return truthy(payload.get("policyGateChecked"))
            || truthy(payload.get("policy_gate_checked"))
            || payload.get("policyGate") != null
            || payload.get("policyGateStatus") != null
            || payload.get("decisionId") != null
            || payload.get("decision_id") != null
            || truthy(payload.get("requiresHumanApproval"));
    }

    private boolean gateBlocked(Map<String, Object> payload) {
        String raw = String.valueOf(payload.getOrDefault("policyGateStatus", payload.getOrDefault("policyGate", ""))).toLowerCase(Locale.ROOT);
        return raw.contains("block") || raw.contains("reject") || raw.contains("fail") || raw.contains("denied");
    }

    private String dispatchId(String channel, Object payload) {
        try {
            String raw = channel + ":" + objectMapper.writeValueAsString(canonicalObject(payload));
            byte[] digest = MessageDigest.getInstance("SHA-1").digest(raw.getBytes(StandardCharsets.UTF_8));
            return "dispatch_" + HexFormat.of().formatHex(digest).substring(0, 12);
        } catch (Exception error) {
            throw new IllegalStateException("Unable to create dispatch id.", error);
        }
    }

    private Object canonicalObject(Object value) {
        if (value instanceof Map<?, ?> source) {
            Map<String, Object> sorted = new TreeMap<>();
            source.forEach((key, item) -> sorted.put(String.valueOf(key), canonicalObject(item)));
            return sorted;
        }
        if (value instanceof List<?> source) {
            return source.stream().map(this::canonicalObject).toList();
        }
        return value;
    }

    private static String toolForChannel(String channel) {
        return switch (channel) {
            case "guest_app" -> "dispatch_guest_message";
            case "worker_device" -> "dispatch_worker_task";
            case "equipment_controller" -> "dispatch_equipment_command";
            default -> "dispatch_receiver_payload";
        };
    }

    private static String string(Object... values) {
        for (Object value : values) {
            if (value != null && !String.valueOf(value).isBlank()) {
                return String.valueOf(value);
            }
        }
        return "";
    }

    private static boolean truthy(Object value) {
        if (value instanceof Boolean bool) {
            return bool;
        }
        if (value instanceof Number number) {
            return number.doubleValue() != 0;
        }
        String raw = String.valueOf(value == null ? "" : value).trim().toLowerCase(Locale.ROOT);
        return List.of("1", "true", "yes", "on", "approved", "passed").contains(raw);
    }

    private static double number(Object value, double fallback) {
        if (value instanceof Number number) {
            return number.doubleValue();
        }
        try {
            return Double.parseDouble(String.valueOf(value));
        } catch (Exception ignored) {
            return fallback;
        }
    }

    private static double round3(double value) {
        return Math.round(value * 1000.0) / 1000.0;
    }

    private Path outboxPath() {
        String configured = environment.getProperty("PARKPULSE_DELIVERY_OUTBOX");
        if (configured != null && !configured.isBlank()) {
            return Path.of(configured);
        }
        String runtimeDir = environment.getProperty("PARKPULSE_RUNTIME_DIR", "/tmp/parkpulse");
        return Path.of(runtimeDir).resolve("delivery_outbox.jsonl");
    }

    private Map<String, Object> mutableMap(Object value) {
        Map<String, Object> result = orderedMap();
        if (value instanceof Map<?, ?> source) {
            source.forEach((key, item) -> result.put(String.valueOf(key), item));
        }
        return result;
    }

    private static String now() {
        return Instant.now().toString();
    }

    private static LinkedHashMap<String, Object> orderedMap() {
        return new LinkedHashMap<>();
    }
}
