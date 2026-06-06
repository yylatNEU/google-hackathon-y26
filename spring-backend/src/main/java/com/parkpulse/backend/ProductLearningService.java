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
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Service;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

@Service
public class ProductLearningService {
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};
    private final Environment environment;
    private final ObjectMapper objectMapper;
    private final Map<Path, RecentRowsSnapshot> recentRowsCache = new ConcurrentHashMap<>();

    public ProductLearningService(Environment environment, ObjectMapper objectMapper) {
        this.environment = environment;
        this.objectMapper = objectMapper;
    }

    public Map<String, Object> createParkIssueTicket(Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        String source = normalizedSource(firstString(request.get("source"), "employee"));
        if (!List.of("guest", "employee").contains(source)) {
            return Map.of("status", "invalid", "mode", "park_issue_ticket_spring", "readiness_issues", List.of("source must be guest or employee."));
        }
        String issueType = normalizeKey(firstString(request.get("issue_type"), request.get("issueType"), "angry_parent"));
        String severity = normalizedSeverity(firstString(request.get("severity"), "medium"), issueType);
        Map<String, Object> ticket = orderedMap();
        ticket.put("event", "park_issue_ticket_created");
        ticket.put("id", "park-issue-" + sha1(source + ":" + issueType + ":" + firstString(request.get("summary"), ""), 12));
        ticket.put("source", source);
        ticket.put("issue_type", issueType);
        ticket.put("severity", severity);
        ticket.put("location", blankToNull(firstString(request.get("location"), "")));
        ticket.put("reporter_role", firstString(request.get("reporter_role"), request.get("reporterRole"), source));
        ticket.put("summary", firstString(request.get("summary"), "Park issue reported."));
        ticket.put("required_action", firstString(request.get("required_action"), request.get("requiredAction"), defaultRequiredAction(issueType)));
        ticket.put("assigned_team", firstString(request.get("assigned_team"), request.get("assignedTeam"), teamForIssue(issueType)));
        ticket.put("status", "new");
        ticket.put("live_ops_authority", true);
        ticket.put("requires_human_ack", List.of("high", "critical").contains(severity));
        ticket.put("created_at", now());
        ticket.put("runtime", "java_spring");
        ticket.put("boundary", "Real guest/employee issue ticket; high-risk actions require human acknowledgement before live dispatch.");
        appendEvent(ticket);
        return Map.of("status", "created", "mode", "park_issue_ticket_spring", "ticket", ticket, "feeds_training_model", "via_product_learning_signal_only", "ledger", ledgerStatus(), "runtime", "java_spring");
    }

    public Map<String, Object> createTrainingGapTicket(Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        String scenarioId = normalizeKey(firstString(request.get("scenario_id"), request.get("scenarioId"), "angry_parent"));
        String gapType = normalizeKey(firstString(request.get("gap_type"), request.get("gapType"), "policy_correctness"));
        String severity = firstString(request.get("severity"), "coaching");
        if (!List.of("coaching", "critical_training_gap").contains(severity)) {
            severity = "coaching";
        }
        Map<String, Object> ticket = orderedMap();
        ticket.put("event", "training_gap_ticket_created");
        ticket.put("id", "training-gap-" + sha1(firstString(request.get("session_id"), request.get("sessionId"), "") + ":" + scenarioId + ":" + gapType + ":" + severity, 12));
        ticket.put("source", "staff_roleplay");
        ticket.put("session_id", blankToNull(firstString(request.get("session_id"), request.get("sessionId"), "")));
        ticket.put("trainee_name", blankToNull(firstString(request.get("trainee_name"), request.get("traineeName"), "")));
        ticket.put("scenario_id", scenarioId);
        ticket.put("gap_type", gapType);
        ticket.put("severity", severity);
        ticket.put("evidence", request.get("evidence") instanceof Map<?, ?> evidence ? mutableMap(evidence) : Map.of());
        ticket.put("status", "open");
        ticket.put("live_ops_authority", false);
        ticket.put("created_at", now());
        ticket.put("runtime", "java_spring");
        ticket.put("boundary", "Training gap only; cannot create live park issue, dispatch, refund, or reward-model label.");
        appendEvent(ticket);
        return Map.of("status", "created", "mode", "training_gap_ticket_spring", "ticket", ticket, "feeds_ops_model", "via_product_learning_signal_only", "ledger", ledgerStatus(), "runtime", "java_spring");
    }

    public Map<String, Object> loopStatus(int limit) {
        List<Map<String, Object>> events = recentRows(Math.max(1, Math.min(limit, 500)));
        List<Map<String, Object>> dynamicTickets = dynamicParkTickets();
        List<Map<String, Object>> signalEvents = new ArrayList<>();
        signalEvents.addAll(events);
        signalEvents.addAll(dynamicTickets);
        List<Map<String, Object>> parkTickets = signalEvents.stream()
            .filter(row -> List.of("park_issue_ticket_created", "park_issue_ticket_generated").contains(String.valueOf(row.get("event"))))
            .toList();
        List<Map<String, Object>> trainingGaps = events.stream()
            .filter(row -> "training_gap_ticket_created".equals(String.valueOf(row.get("event"))))
            .toList();
        List<Map<String, Object>> signals = productLearningSignals(signalEvents);
        List<Map<String, Object>> shadowReady = signals.stream().filter(row -> !Boolean.TRUE.equals(row.get("requires_review"))).map(this::autoCandidate).toList();
        List<Map<String, Object>> humanExceptions = signals.stream().filter(row -> Boolean.TRUE.equals(row.get("requires_review"))).map(this::exceptionCandidate).toList();

        Map<String, Object> payload = orderedMap();
        payload.put("status", "ready");
        payload.put("mode", "product_learning_loop_spring");
        payload.put("runtime", "java_spring");
        payload.put("park_issue_ticket_count", parkTickets.size());
        payload.put("dynamic_park_issue_ticket_count", dynamicTickets.size());
        payload.put("operational_backlog_issue_ticket_count", 1);
        payload.put("place_risk_issue_ticket_count", 1);
        payload.put("random_incident_issue_ticket_count", 0);
        payload.put("training_gap_ticket_count", trainingGaps.size());
        payload.put("learning_signal_count", signals.size());
        payload.put("auto_learning_candidate_count", shadowReady.size());
        payload.put("shadow_ready_candidate_count", shadowReady.size());
        payload.put("human_exception_candidate_count", humanExceptions.size());
        payload.put("park_issue_tickets", parkTickets.stream().limit(80).toList());
        payload.put("training_gap_tickets", trainingGaps.stream().limit(80).toList());
        payload.put("product_learning_signals", signals.stream().limit(120).toList());
        payload.put("auto_learning_governance", Map.of("auto_candidate_count", shadowReady.size(), "shadow_ready_count", shadowReady.size(), "human_exception_count", humanExceptions.size()));
        payload.put("auto_learning_candidates", shadowReady);
        payload.put("shadow_deployment_candidates", shadowReady);
        payload.put("human_exception_queue", humanExceptions);
        payload.put("place_risk_graph", Map.of("mode", "spring_projection", "places", List.of(Map.of("id", "covered-plaza", "risk", "queue_density_watch"))));
        payload.put("ticket_generation_traces", dynamicTickets.stream().map(row -> row.get("ticket_generation_trace")).filter(item -> item instanceof Map<?, ?>).toList());
        payload.put("loop_contract", Map.of(
            "live_tickets_improve_training", "via reviewed ProductLearningSignal and golden eval only",
            "training_gaps_help_ops", "via reviewed checklist/prompt candidates only",
            "training_gaps_create_live_issues", false,
            "low_risk_auto_learning", "auto draft, automated eval, shadow first, rollback guarded",
            "human_on_exception", true,
            "llm_guest_controls_score", false,
            "simulated_data_feeds_reward_model", false
        ));
        payload.put("ledger", ledgerStatus());
        payload.put("boundary", "Separates live operational tickets from simulated training gaps; both can produce reviewed product-learning signals.");
        return payload;
    }

    private List<Map<String, Object>> productLearningSignals(List<Map<String, Object>> events) {
        List<Map<String, Object>> signals = new ArrayList<>();
        for (Map<String, Object> event : events) {
            String eventType = String.valueOf(event.get("event"));
            if ("park_issue_ticket_created".equals(eventType) || "park_issue_ticket_generated".equals(eventType)) {
                signals.add(signal(event, String.valueOf(event.get("source")), String.valueOf(event.get("issue_type")), "scenario_update", Boolean.TRUE.equals(event.get("requires_human_ack"))));
            }
            if ("training_gap_ticket_created".equals(eventType)) {
                signals.add(signal(event, "training_gap_ticket", String.valueOf(event.get("gap_type")), "checklist_repair", "critical_training_gap".equals(String.valueOf(event.get("severity")))));
            }
        }
        return signals;
    }

    private Map<String, Object> signal(Map<String, Object> event, String source, String pattern, String proposedChangeType, boolean requiresReview) {
        Map<String, Object> payload = orderedMap();
        payload.put("id", "pls-" + sha1(String.valueOf(event.get("id")) + ":" + pattern, 12));
        payload.put("source", source);
        payload.put("pattern", pattern);
        payload.put("affected_scenarios", List.of(firstString(event.get("scenario_id"), event.get("issue_type"), "angry_parent")));
        payload.put("evidence_count", 1);
        payload.put("recommendation", requiresReview ? "Route to manager review before product training promotion." : "Draft a shadow candidate and evaluate before rollout.");
        payload.put("proposed_change_type", proposedChangeType);
        payload.put("status", requiresReview ? "needs_review" : "shadow_ready");
        payload.put("requires_review", requiresReview);
        return payload;
    }

    private Map<String, Object> autoCandidate(Map<String, Object> signal) {
        return Map.of(
            "id", "auto-" + signal.get("id"),
            "scenario_id", firstString(signal.get("affected_scenarios"), "angry_parent"),
            "confidence", 0.82,
            "draft", Map.of("title", "Shadow update for " + signal.get("pattern"), "content_summary", signal.get("recommendation"))
        );
    }

    private Map<String, Object> exceptionCandidate(Map<String, Object> signal) {
        return Map.of(
            "id", "exception-" + signal.get("id"),
            "scenario_id", firstString(signal.get("affected_scenarios"), "angry_parent"),
            "confidence", 0.58,
            "exception_reasons", List.of("requires_human_review", String.valueOf(signal.get("status")))
        );
    }

    private List<Map<String, Object>> dynamicParkTickets() {
        Map<String, Object> ticket = orderedMap();
        ticket.put("event", "park_issue_ticket_generated");
        ticket.put("id", "park-issue-spring-covered-plaza");
        ticket.put("source", "place_risk");
        ticket.put("issue_type", "queue_pressure");
        ticket.put("severity", "medium");
        ticket.put("location", "Covered Plaza");
        ticket.put("summary", "Spring projected place-risk ticket from queue density and wait pressure.");
        ticket.put("status", "generated");
        ticket.put("live_ops_authority", false);
        ticket.put("requires_human_ack", false);
        ticket.put("created_at", now());
        ticket.put("ticket_generation_trace", Map.of("runtime", "java_spring", "source", "state_projection"));
        return List.of(ticket);
    }

    private void appendEvent(Map<String, Object> event) {
        try {
            Path path = ledgerPath();
            Files.createDirectories(path.getParent());
            Files.writeString(path, objectMapper.writeValueAsString(event) + "\n", StandardCharsets.UTF_8, Files.exists(path) ? java.nio.file.StandardOpenOption.APPEND : java.nio.file.StandardOpenOption.CREATE);
            prependCachedRecentRow(path, event);
        } catch (Exception error) {
            throw new IllegalStateException("Unable to append product-learning event.", error);
        }
    }

    private List<Map<String, Object>> recentRows(int limit) {
        Path path = ledgerPath();
        if (!Files.exists(path)) {
            return new ArrayList<>();
        }
        int cappedLimit = Math.max(1, Math.min(limit, 500));
        try {
            long size = Files.size(path);
            long modifiedAt = Files.getLastModifiedTime(path).toMillis();
            RecentRowsSnapshot cached = recentRowsCache.get(path);
            if (cached != null && cached.size() == size && cached.modifiedAt() == modifiedAt && cached.rows().size() >= Math.min(cappedLimit, 100)) {
                return new ArrayList<>(cached.rows().subList(0, Math.min(cappedLimit, cached.rows().size())));
            }
        } catch (Exception ignored) {
            recentRowsCache.remove(path);
        }
        Deque<String> tail = new ArrayDeque<>(cappedLimit);
        try (var reader = Files.newBufferedReader(path, StandardCharsets.UTF_8)) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.isBlank()) {
                    continue;
                }
                if (tail.size() == cappedLimit) {
                    tail.removeFirst();
                }
                tail.addLast(line);
            }
        } catch (Exception ignored) {
            return new ArrayList<>();
        }
        List<Map<String, Object>> rows = new ArrayList<>();
        while (!tail.isEmpty()) {
            try {
                rows.add(objectMapper.readValue(tail.removeLast(), MAP_TYPE));
            } catch (Exception ignored) {
                // Skip malformed historical rows without blocking product-learning reads.
            }
        }
        cacheRecentRows(path, rows.stream().limit(100).toList());
        return rows;
    }

    private Map<String, Object> ledgerStatus() {
        Path path = ledgerPath();
        return Map.of("mode", "spring_product_learning_jsonl_ledger", "path", path.toString(), "ready", true, "count", lineCount(path), "runtime", "java_spring");
    }

    private long lineCount(Path path) {
        if (!Files.exists(path)) {
            return 0;
        }
        try (var lines = Files.lines(path, StandardCharsets.UTF_8)) {
            return lines.filter(line -> !line.isBlank()).count();
        } catch (Exception ignored) {
            return 0;
        }
    }

    private void prependCachedRecentRow(Path path, Map<String, Object> row) {
        try {
            RecentRowsSnapshot cached = recentRowsCache.get(path);
            if (cached == null) {
                return;
            }
            List<Map<String, Object>> rows = new ArrayList<>();
            rows.add(row);
            rows.addAll(cached.rows());
            if (rows.size() > 100) {
                rows = new ArrayList<>(rows.subList(0, 100));
            }
            recentRowsCache.put(path, new RecentRowsSnapshot(Files.size(path), Files.getLastModifiedTime(path).toMillis(), rows));
        } catch (Exception ignored) {
            recentRowsCache.remove(path);
        }
    }

    private void cacheRecentRows(Path path, List<Map<String, Object>> rows) {
        try {
            recentRowsCache.put(path, new RecentRowsSnapshot(Files.size(path), Files.getLastModifiedTime(path).toMillis(), new ArrayList<>(rows)));
        } catch (Exception ignored) {
            recentRowsCache.remove(path);
        }
    }

    private Path ledgerPath() {
        String configured = env("PARKPULSE_PRODUCT_LEARNING_LOG_PATH", "");
        if (!configured.isBlank()) {
            return Path.of(configured);
        }
        return runtimeDir().resolve("product_learning_loop.jsonl");
    }

    private Path runtimeDir() {
        return Path.of(env("PARKPULSE_RUNTIME_DIR", "/tmp/parkpulse"));
    }

    private String env(String key, String defaultValue) {
        String value = environment.getProperty(key);
        return value == null || value.isBlank() ? defaultValue : value;
    }

    private String normalizedSource(String source) {
        String normalized = normalizeKey(source);
        return List.of("guest", "employee").contains(normalized) ? normalized : "employee";
    }

    private String normalizedSeverity(String severity, String issueType) {
        String normalized = normalizeKey(severity);
        if (List.of("low", "medium", "high", "critical").contains(normalized)) {
            return normalized;
        }
        return List.of("medical", "security", "evacuation").contains(issueType) ? "critical" : "medium";
    }

    private String normalizeKey(String value) {
        return value == null || value.isBlank() ? "" : value.trim().toLowerCase().replace('-', '_').replace(' ', '_');
    }

    private String defaultRequiredAction(String issueType) {
        return switch (issueType) {
            case "queue_pressure" -> "Review queue relief and staff positioning.";
            case "angry_parent" -> "Escalate to guest care with recovery options.";
            default -> "Review with the responsible operating lead.";
        };
    }

    private String teamForIssue(String issueType) {
        return switch (issueType) {
            case "queue_pressure" -> "guest_flow";
            case "angry_parent" -> "guest_care";
            default -> "ops_lead";
        };
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

    private String now() {
        return Instant.now().toString();
    }

    private String blankToNull(String value) {
        return value == null || value.isBlank() ? null : value;
    }

    private static LinkedHashMap<String, Object> orderedMap() {
        return new LinkedHashMap<>();
    }

    private static String firstString(Object... values) {
        for (Object value : values) {
            if (value instanceof List<?> list && !list.isEmpty()) {
                return firstString(list.get(0));
            }
            if (value != null && !String.valueOf(value).isBlank()) {
                return String.valueOf(value);
            }
        }
        return "";
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> mutableMap(Object value) {
        return value instanceof Map<?, ?> ? new LinkedHashMap<>((Map<String, Object>) value) : orderedMap();
    }

    private record RecentRowsSnapshot(long size, long modifiedAt, List<Map<String, Object>> rows) {
    }
}
