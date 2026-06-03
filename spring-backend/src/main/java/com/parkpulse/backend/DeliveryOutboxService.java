package com.parkpulse.backend;

import java.io.BufferedReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Service;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

@Service
public class DeliveryOutboxService {
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

    private final Environment environment;
    private final ObjectMapper objectMapper;

    public DeliveryOutboxService(Environment environment, ObjectMapper objectMapper) {
        this.environment = environment;
        this.objectMapper = objectMapper;
    }

    public Map<String, Object> contract() {
        Map<String, Object> payload = orderedMap();
        payload.put("name", "ParkPulse Action Delivery REST Port");
        payload.put("purpose", "Transforms agent decisions into guest app promotions, worker notifications, and equipment commands.");
        payload.put("runtime", "java_spring");
        payload.put("ports", List.of(
            Map.of("channel", "guest_app", "method", "POST", "endpoint", "/api/park/delivery/guest-promotion", "runtime", "python_fallback_until_agent_boundary_migrates"),
            Map.of("channel", "worker_device", "method", "POST", "endpoint", "/api/park/delivery/worker-notification", "runtime", "python_fallback_until_agent_boundary_migrates"),
            Map.of("channel", "equipment_controller", "method", "POST", "endpoint", "/api/park/delivery/equipment-command", "runtime", "python_fallback_until_agent_boundary_migrates"),
            Map.of("channel", "receiver_acknowledgement", "method", "POST", "endpoint", "/api/park/delivery/acknowledge", "runtime", "java_spring"),
            Map.of("channel", "operator_approval", "method", "POST", "endpoint", "/api/park/delivery/approval-decision", "runtime", "java_spring")
        ));
        payload.put("guardrails", List.of(
            "Ride safety and maintenance clearances are never automated.",
            "Guest messages use aggregate segments, not guest PII.",
            "Equipment commands are limited to comfort and load settings; safety-critical commands require approval.",
            "Spring reads and appends receiver receipts to the durable JSONL outbox; new dispatch creation remains behind Python until the agent-boundary executor is migrated."
        ));
        payload.put("durability", durabilityStatus());
        return payload;
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
        dispatch.put("approvalDelivery", localApprovalDelivery(approval));
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

    private Map<String, Object> localApprovalDelivery(Map<String, Object> decision) {
        Map<String, Object> payload = orderedMap();
        payload.put("mode", "local_delivery_envelope");
        payload.put("agentBoundary", decision.get("agentBoundary"));
        payload.put("pubsub", Map.of("status", "skipped", "reason", "live GCP delivery adapter disabled", "event_type", "parkpulse.delivery.approval_decision"));
        payload.put("pseudoFirebase", Map.of("status", "skipped", "reason", "live GCP delivery adapter disabled", "decision", String.valueOf(decision.getOrDefault("decision", ""))));
        payload.put("firestore", Map.of("status", "skipped", "reason", "Firestore adapter disabled"));
        payload.put("dataflow", Map.of("status", "skipped", "reason", "Dataflow adapter disabled"));
        return payload;
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
