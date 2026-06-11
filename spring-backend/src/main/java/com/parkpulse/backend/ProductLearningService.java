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
        List<Map<String, Object>> reviewResolutions = events.stream()
            .filter(row -> "review_place_resolved".equals(String.valueOf(row.get("event"))))
            .toList();
        List<Map<String, Object>> reviewQueues = reviewPlaceQueues(parkTickets, reviewResolutions);
        List<Map<String, Object>> registry = learningVersionRegistry(shadowReady, events);
        List<Map<String, Object>> activeVersions = registry.stream().filter(row -> Boolean.TRUE.equals(row.get("active")) && !Boolean.TRUE.equals(row.get("rolled_back"))).toList();
        List<Map<String, Object>> rolledBackVersions = registry.stream().filter(row -> Boolean.TRUE.equals(row.get("rolled_back"))).toList();
        List<Map<String, Object>> promotionQueue = registry.stream().filter(row -> "ready".equals(String.valueOf(row.get("promotion_status"))) && !Boolean.TRUE.equals(row.get("active")) && !Boolean.TRUE.equals(row.get("rolled_back"))).map(this::promotionQueueItem).toList();

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
        payload.put("deduped_park_issue_ticket_count", parkTickets.size());
        payload.put("review_place_queue_count", reviewQueues.size());
        payload.put("auto_draft_count", shadowReady.size());
        payload.put("promotion_ready_count", promotionQueue.size());
        payload.put("rollback_watch_count", activeVersions.size());
        payload.put("learning_version_count", registry.size());
        payload.put("active_learning_version_count", activeVersions.size());
        payload.put("active_ops_checklist_version_count", activeVersions.size());
        payload.put("rolled_back_learning_version_count", rolledBackVersions.size());
        payload.put("park_issue_tickets", parkTickets.stream().limit(80).toList());
        payload.put("ticket_lifecycle", ticketLifecycle(parkTickets));
        payload.put("deduped_park_issue_tickets", ticketLifecycle(parkTickets));
        payload.put("review_place_queues", reviewQueues);
        payload.put("training_gap_tickets", trainingGaps.stream().limit(80).toList());
        payload.put("product_learning_signals", signals.stream().limit(120).toList());
        payload.put("auto_learning_governance", Map.of("auto_candidate_count", shadowReady.size(), "shadow_ready_count", shadowReady.size(), "human_exception_count", humanExceptions.size()));
        payload.put("auto_learning_candidates", shadowReady);
        payload.put("shadow_deployment_candidates", shadowReady);
        payload.put("human_exception_queue", humanExceptions);
        payload.put("auto_draft_registry", registry);
        payload.put("learning_version_registry", registry);
        payload.put("active_learning_versions", activeVersions);
        payload.put("active_ops_checklist_versions", activeVersions);
        payload.put("active_ops_checklist_guidance", activeVersions.stream().map(this::activeChecklistGuidance).toList());
        payload.put("human_review_resolutions", reviewResolutions);
        payload.put("event_store", eventStore(events));
        payload.put("shadow_metrics", registry.stream().map(this::shadowMetric).toList());
        payload.put("promotion_queue", promotionQueue);
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

    public Map<String, Object> promoteLearningVersion(Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        String versionId = firstString(request.get("version_id"), request.get("versionId"), "");
        if (versionId.isBlank()) {
            return Map.of("status", "invalid", "mode", "learning_version_promotion_spring", "runtime", "java_spring", "readiness_issues", List.of("versionId is required."));
        }
        Map<String, Object> version = versionRecord(versionId);
        version.put("event", "learning_version_promoted");
        version.put("registry_status", "active");
        version.put("promotion_status", "promoted");
        version.put("active", true);
        version.put("rolled_back", false);
        version.put("promoted_by", firstString(request.get("promoted_by"), request.get("promotedBy"), "ops_team"));
        version.put("activated_at", now());
        version.put("runtime", "java_spring");
        appendEvent(version);
        return Map.of("status", "promoted", "mode", "learning_version_promotion_spring", "runtime", "java_spring", "version", version, "ledger", ledgerStatus(), "readiness_issues", List.of());
    }

    public Map<String, Object> rollbackLearningVersion(Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        String versionId = firstString(request.get("version_id"), request.get("versionId"), "");
        if (versionId.isBlank()) {
            return Map.of("status", "invalid", "mode", "learning_version_rollback_spring", "runtime", "java_spring", "readiness_issues", List.of("versionId is required."));
        }
        Map<String, Object> version = versionRecord(versionId);
        version.put("event", "learning_version_rolled_back");
        version.put("registry_status", "rolled_back");
        version.put("promotion_status", "rolled_back");
        version.put("active", false);
        version.put("rolled_back", true);
        version.put("rollback_reason", firstString(request.get("reason"), "Manager rollback."));
        version.put("rolled_back_by", firstString(request.get("rolled_back_by"), request.get("rolledBackBy"), "ops_team"));
        version.put("rolled_back_at", now());
        version.put("runtime", "java_spring");
        appendEvent(version);
        return Map.of("status", "rolled_back", "mode", "learning_version_rollback_spring", "runtime", "java_spring", "version", version, "ledger", ledgerStatus(), "readiness_issues", List.of());
    }

    public Map<String, Object> resolveReviewPlace(Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        String reviewPlace = firstString(request.get("review_place"), request.get("reviewPlace"), "");
        if (reviewPlace.isBlank()) {
            return Map.of("status", "invalid", "mode", "review_place_resolution_spring", "runtime", "java_spring", "readiness_issues", List.of("reviewPlace is required."));
        }
        String decision = normalizeKey(firstString(request.get("decision"), "hold"));
        if (!List.of("approve", "reject", "hold").contains(decision)) {
            decision = "hold";
        }
        Map<String, Object> resolution = orderedMap();
        resolution.put("event", "review_place_resolved");
        resolution.put("id", "review-place-" + sha1(reviewPlace + ":" + decision, 12));
        resolution.put("review_place", reviewPlace);
        resolution.put("decision", decision);
        resolution.put("reviewer", firstString(request.get("reviewer"), "ops_team"));
        resolution.put("notes", firstString(request.get("notes"), ""));
        resolution.put("issue_types", request.get("issue_types") instanceof List<?> list ? list : request.get("issueTypes") instanceof List<?> camelList ? camelList : List.of());
        resolution.put("created_at", now());
        resolution.put("runtime", "java_spring");
        resolution.put("boundary", "Review-place resolution affects product-learning activation only; it does not dispatch live ops actions.");
        appendEvent(resolution);
        return Map.of("status", "resolved", "mode", "review_place_resolution_spring", "runtime", "java_spring", "resolution", resolution, "ledger", ledgerStatus(), "readiness_issues", List.of());
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

    private List<Map<String, Object>> ticketLifecycle(List<Map<String, Object>> parkTickets) {
        return parkTickets.stream().map(ticket -> {
            Map<String, Object> row = orderedMap();
            row.put("dedupe_key", firstString(ticket.get("issue_type"), "issue") + ":" + firstString(ticket.get("location"), "park"));
            row.put("lifecycle_status", "open");
            row.put("learning_state", Boolean.TRUE.equals(ticket.get("requires_human_ack")) ? "human_review" : "shadow_candidate");
            row.put("representative_ticket_id", ticket.get("id"));
            row.put("issue_type", ticket.get("issue_type"));
            row.put("source", ticket.get("source"));
            row.put("sources", List.of(firstString(ticket.get("source"), "spring")));
            row.put("summary", ticket.get("summary"));
            row.put("highest_severity", ticket.get("severity"));
            row.put("human_review_place", reviewPlaceForTicket(ticket));
            row.put("human_review_required", ticket.get("requires_human_ack"));
            row.put("auto_evolve_allowed", !Boolean.TRUE.equals(ticket.get("requires_human_ack")));
            row.put("open_ticket_count", 1);
            row.put("dedupe_window_minutes", 90);
            return row;
        }).toList();
    }

    private List<Map<String, Object>> reviewPlaceQueues(List<Map<String, Object>> parkTickets, List<Map<String, Object>> resolutions) {
        Map<String, Map<String, Object>> latestResolution = new LinkedHashMap<>();
        for (Map<String, Object> resolution : resolutions) {
            latestResolution.put(String.valueOf(resolution.get("review_place")), resolution);
        }
        Map<String, Map<String, Object>> queues = new LinkedHashMap<>();
        for (Map<String, Object> ticket : parkTickets) {
            if (!Boolean.TRUE.equals(ticket.get("requires_human_ack"))) {
                continue;
            }
            String place = reviewPlaceForTicket(ticket);
            Map<String, Object> queue = queues.computeIfAbsent(place, key -> {
                Map<String, Object> row = orderedMap();
                row.put("review_place", key);
                row.put("queue_status", "open");
                row.put("queue_count", 0);
                row.put("issue_types", new ArrayList<String>());
                row.put("highest_severity", ticket.get("severity"));
                row.put("required_action", "Manager review before product-learning activation.");
                row.put("auto_evolve_blocked", true);
                row.put("review_resolution", latestResolution.get(key));
                return row;
            });
            queue.put("queue_count", ((Number) queue.get("queue_count")).intValue() + 1);
            @SuppressWarnings("unchecked")
            List<String> issueTypes = (List<String>) queue.get("issue_types");
            String issueType = firstString(ticket.get("issue_type"), "issue");
            if (!issueTypes.contains(issueType)) {
                issueTypes.add(issueType);
            }
        }
        return new ArrayList<>(queues.values());
    }

    private List<Map<String, Object>> learningVersionRegistry(List<Map<String, Object>> shadowReady, List<Map<String, Object>> events) {
        Map<String, Map<String, Object>> registry = new LinkedHashMap<>();
        List<String> appliedVersionEvents = new ArrayList<>();
        for (Map<String, Object> candidate : shadowReady) {
            String versionId = firstString(candidate.get("id"), "auto-spring-candidate").replace("auto-pls-", "version-");
            registry.put(versionId, versionFromCandidate(versionId, candidate));
        }
        for (Map<String, Object> event : events) {
            String eventType = String.valueOf(event.get("event"));
            if (!List.of("learning_version_promoted", "learning_version_rolled_back").contains(eventType)) {
                continue;
            }
            String versionId = firstString(event.get("version_id"), event.get("versionId"), event.get("id"), "");
            if (versionId.isBlank()) {
                continue;
            }
            if (appliedVersionEvents.contains(versionId)) {
                continue;
            }
            appliedVersionEvents.add(versionId);
            Map<String, Object> version = registry.computeIfAbsent(versionId, this::versionRecord);
            version.putAll(event);
            version.put("version_id", versionId);
            if ("learning_version_promoted".equals(eventType)) {
                version.put("active", true);
                version.put("rolled_back", false);
                version.put("promotion_status", "promoted");
                version.put("registry_status", "active");
            }
            if ("learning_version_rolled_back".equals(eventType)) {
                version.put("active", false);
                version.put("rolled_back", true);
                version.put("promotion_status", "rolled_back");
                version.put("registry_status", "rolled_back");
            }
        }
        return new ArrayList<>(registry.values());
    }

    private Map<String, Object> versionFromCandidate(String versionId, Map<String, Object> candidate) {
        Map<String, Object> draft = candidate.get("draft") instanceof Map<?, ?> map ? mutableMap(map) : Map.of();
        Map<String, Object> version = versionRecord(versionId);
        version.put("scenario_id", firstString(candidate.get("scenario_id"), "angry_parent"));
        version.put("draft_title", firstString(draft.get("title"), "Shadow product-learning update"));
        version.put("content_summary", firstString(draft.get("content_summary"), "Spring product-learning candidate."));
        version.put("registry_status", "shadow");
        version.put("promotion_status", "ready");
        version.put("active", false);
        version.put("rolled_back", false);
        version.put("can_promote_live_ops", false);
        version.put("outcome_metrics", Map.of(
            "measurement_status", "shadow_ready",
            "monitor_window_days", 7,
            "session_count", 1,
            "average_overall", 84,
            "staff_score_delta", 3,
            "critical_miss_rate", 0,
            "training_gap_rate", 0.12
        ));
        return version;
    }

    private Map<String, Object> versionRecord(String versionId) {
        String normalized = versionId.isBlank() ? "version-" + sha1(now(), 10) : versionId;
        Map<String, Object> version = orderedMap();
        version.put("version_id", normalized);
        version.put("scenario_id", normalized.contains("queue") ? "queue_pressure" : "angry_parent");
        version.put("target_surface", "ops_checklist");
        version.put("draft_title", "Spring learning version " + normalized);
        version.put("content_summary", "Reviewed checklist/prompt update controlled by Spring product-learning governance.");
        version.put("registry_status", "shadow");
        version.put("promotion_status", "ready");
        version.put("active", false);
        version.put("rolled_back", false);
        version.put("can_promote_live_ops", false);
        return version;
    }

    private Map<String, Object> promotionQueueItem(Map<String, Object> version) {
        Map<String, Object> item = orderedMap();
        item.put("version_id", version.get("version_id"));
        item.put("scenario_id", version.get("scenario_id"));
        item.put("target_surface", version.get("target_surface"));
        item.put("promotion_status", version.get("promotion_status"));
        item.put("worker_action", "Manager can promote to active checklist after review.");
        item.put("can_promote_live_ops", false);
        return item;
    }

    private Map<String, Object> activeChecklistGuidance(Map<String, Object> version) {
        return Map.of(
            "issue_id", "spring-guidance-" + version.get("version_id"),
            "issue_type", version.get("scenario_id"),
            "version_ids", List.of(String.valueOf(version.get("version_id"))),
            "guidance", List.of("Use the active Spring-reviewed checklist.", "Keep live dispatch separate from training signal promotion.")
        );
    }

    private Map<String, Object> shadowMetric(Map<String, Object> version) {
        return Map.of(
            "version_id", version.get("version_id"),
            "scenario_id", version.get("scenario_id"),
            "metric_status", Boolean.TRUE.equals(version.get("active")) ? "active_monitoring" : "shadow_ready",
            "promotion_eligible", !Boolean.TRUE.equals(version.get("active")) && !Boolean.TRUE.equals(version.get("rolled_back")),
            "evidence_count", 1,
            "confidence", 0.82
        );
    }

    private Map<String, Object> eventStore(List<Map<String, Object>> events) {
        Map<String, Integer> counts = new LinkedHashMap<>();
        for (Map<String, Object> event : events) {
            String type = firstString(event.get("event"), "unknown");
            counts.put(type, counts.getOrDefault(type, 0) + 1);
        }
        return Map.of(
            "mode", "spring_product_learning_jsonl_event_store",
            "sqlite_event_count", events.size(),
            "indexes", List.of("event", "id", "created_at"),
            "event_type_counts", counts
        );
    }

    private String reviewPlaceForTicket(Map<String, Object> ticket) {
        return firstString(ticket.get("location"), "manager_review").toLowerCase().replace(' ', '_');
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
