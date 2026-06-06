package com.parkpulse.backend;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Service;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

@Service
public class ReviewLabelPipelineService {
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};
    private static final List<String> LABEL_DECISIONS = List.of("approve_label", "edit_label", "reject_label", "needs_more_evidence");
    private static final double DEFAULT_AUTO_LABEL_CONFIDENCE_THRESHOLD = 0.70;

    private final Environment environment;
    private final ObjectMapper objectMapper;
    private final LiveFeedLedgerService liveFeedLedgerService;
    private final VenueProfileService venueProfileService;

    public ReviewLabelPipelineService(
        Environment environment,
        ObjectMapper objectMapper,
        LiveFeedLedgerService liveFeedLedgerService,
        VenueProfileService venueProfileService
    ) {
        this.environment = environment;
        this.objectMapper = objectMapper;
        this.liveFeedLedgerService = liveFeedLedgerService;
        this.venueProfileService = venueProfileService;
    }

    public Map<String, Object> pipeline(int limit) {
        return pipeline(limit, DEFAULT_AUTO_LABEL_CONFIDENCE_THRESHOLD);
    }

    public Map<String, Object> pipeline(int limit, double autoLabelThreshold) {
        List<Map<String, Object>> candidates = candidateRows();
        Map<String, Map<String, Object>> decisions = latestDecisions();
        List<Map<String, Object>> attached = candidates.stream().map(candidate -> attachDecision(candidate, decisions)).toList();
        List<Map<String, Object>> open = attached.stream().filter(row -> "pending_review".equals(row.get("review_status"))).toList();
        List<Map<String, Object>> decided = attached.stream().filter(row -> !"pending_review".equals(row.get("review_status"))).toList();
        long approved = decided.stream().filter(row -> {
            String decision = string(mapValue(row.get("decision")).get("decision"), "");
            return List.of("approve_label", "edit_label").contains(decision);
        }).count();

        Map<String, Object> summary = orderedMap();
        summary.put("candidate_count", attached.size());
        summary.put("open_count", open.size());
        summary.put("decided_count", decided.size());
        summary.put("approved_label_count", approved);
        summary.put("training_candidate_count", approved);

        Map<String, Object> autoLabelRule = orderedMap();
        autoLabelRule.put("enabled", true);
        autoLabelRule.put("confidence_threshold", clamp(autoLabelThreshold));
        autoLabelRule.put("decision", "approve_label");
        autoLabelRule.put("low_confidence_action", "leave_pending_for_human_review");

        Map<String, Object> payload = orderedMap();
        payload.put("status", "ready");
        payload.put("mode", "review_label_pipeline_spring");
        payload.put("runtime", "java_spring");
        payload.put("created_at", now());
        payload.put("summary", summary);
        payload.put("candidates", open.stream().limit(Math.max(1, Math.min(limit, 200))).toList());
        payload.put("decided", decided.stream().limit(20).toList());
        payload.put("label_options", LABEL_DECISIONS);
        payload.put("auto_label_rule", autoLabelRule);
        payload.put("training_rule", trainingRule());
        payload.put("boundary", "Review labels are role-scoped, human-reviewed, and stored separately from RL reward/outcome attribution.");
        payload.put("uses_seed_data", false);
        payload.put("labels_or_reward_changed", false);
        payload.put("llm_used_for_reward_or_label", false);
        payload.put("decision_ledger", ledgerSummary(120));
        return payload;
    }

    public Map<String, Object> recordDecision(Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        Map<String, Object> candidate = mapValue(request.get("candidate"));
        String candidateId = firstString(request.get("candidate_id"), request.get("candidateId"), candidate.get("id"), "");
        String decision = firstString(request.get("decision"), "");
        if (candidateId.isBlank()) {
            return Map.of("status", "error", "mode", "review_label_decision_spring", "runtime", "java_spring", "readiness_issues", List.of("candidate_id is required."));
        }
        if (!LABEL_DECISIONS.contains(decision)) {
            return Map.of("status", "error", "mode", "review_label_decision_spring", "runtime", "java_spring", "readiness_issues", List.of("decision must be one of " + LABEL_DECISIONS + "."));
        }
        String finalLabel = firstString(request.get("final_label"), request.get("finalLabel"), candidate.get("proposed_label"), "");
        if (List.of("approve_label", "edit_label").contains(decision) && finalLabel.isBlank()) {
            return Map.of("status", "error", "mode", "review_label_decision_spring", "runtime", "java_spring", "readiness_issues", List.of("final_label is required for approved or edited labels."));
        }

        Map<String, Object> row = orderedMap();
        row.put("id", "review_label_" + sha1(candidateId + ":" + decision + ":" + System.nanoTime(), 12));
        row.put("created_at", now());
        row.put("candidate_id", candidateId);
        row.put("decision", decision);
        row.put("reviewer", truncate(firstString(request.get("reviewer"), "parkpulse-reviewer"), 120));
        row.put("reason", truncate(firstString(request.get("reason"), request.get("note"), ""), 500));
        row.put("final_label", finalLabel);
        row.put("training_scope", truncate(firstString(request.get("training_scope"), request.get("trainingScope"), candidate.get("training_scope"), "unknown"), 120));
        row.put("agent_id", truncate(firstString(request.get("agent_id"), request.get("agentId"), candidate.get("agent_id"), "unknown"), 120));
        row.put("candidate_snapshot", candidateSnapshot(candidate));
        row.put("eligible_for_supervised_training", List.of("approve_label", "edit_label").contains(decision));
        row.put("eligible_for_reward", false);
        row.put("labels_or_reward_changed", false);
        row.put("llm_used_for_reward_or_label", false);
        row.put("boundary", "This records a human supervised-label disposition only. Reward still requires measured outcome attribution.");
        appendDecision(row);
        return Map.of("status", "recorded", "mode", "review_label_decision_spring", "runtime", "java_spring", "decision", row);
    }

    public Map<String, Object> autoLabel(Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        double threshold = clamp(doubleValue(firstPresent(request.get("confidence_threshold"), request.get("confidenceThreshold")), DEFAULT_AUTO_LABEL_CONFIDENCE_THRESHOLD));
        String reviewer = firstString(request.get("reviewer"), "parkpulse-auto-labeler");
        Map<String, Object> before = pipeline(200, threshold);
        List<Map<String, Object>> candidates = listOfMaps(before.get("candidates"));
        List<Map<String, Object>> recorded = new ArrayList<>();
        List<Map<String, Object>> skipped = new ArrayList<>();
        for (Map<String, Object> candidate : candidates) {
            double confidence = doubleValue(mapValue(candidate.get("recommendation")).get("confidence"), 0);
            if (confidence < threshold) {
                skipped.add(Map.of(
                    "candidate_id", candidate.get("id"),
                    "proposed_label", candidate.get("proposed_label"),
                    "recommendation_confidence", confidence,
                    "reason", "Recommendation confidence is below the auto-label threshold."
                ));
                continue;
            }
            Map<String, Object> result = recordDecision(Map.of(
                "candidate_id", candidate.get("id"),
                "candidate", candidate,
                "decision", "approve_label",
                "final_label", candidate.get("proposed_label"),
                "reviewer", reviewer,
                "reason", "Auto-labeled recommended supervised label because recommendation confidence " + confidence + " >= threshold " + threshold + "."
            ));
            if ("recorded".equals(result.get("status"))) {
                recorded.add(mapValue(result.get("decision")));
            } else {
                skipped.add(Map.of(
                    "candidate_id", candidate.get("id"),
                    "proposed_label", candidate.get("proposed_label"),
                    "recommendation_confidence", confidence,
                    "reason", listValue(result.get("readiness_issues")).isEmpty() ? "Unable to record label decision." : listValue(result.get("readiness_issues")).get(0)
                ));
            }
        }

        Map<String, Object> payload = orderedMap();
        payload.put("status", recorded.isEmpty() ? "no_high_confidence_candidates" : "recorded");
        payload.put("mode", "review_label_auto_label_spring");
        payload.put("runtime", "java_spring");
        payload.put("created_at", now());
        payload.put("confidence_threshold", threshold);
        payload.put("recorded_count", recorded.size());
        payload.put("skipped_count", skipped.size());
        payload.put("recorded", recorded);
        payload.put("skipped", skipped);
        payload.put("pipeline_before", before.get("summary"));
        payload.put("training_rule", "Auto-label only approves the proposed supervised label when recommendation confidence meets threshold. It never sets reward or promotes policies.");
        payload.put("uses_seed_data", false);
        payload.put("labels_or_reward_changed", false);
        payload.put("llm_used_for_reward_or_label", false);
        return payload;
    }

    public Map<String, Object> decisionLedger(int limit) {
        List<Map<String, Object>> rows = readDecisionRows(Math.max(1, Math.min(limit, 1000)));
        long approved = rows.stream().filter(row -> Boolean.TRUE.equals(row.get("eligible_for_supervised_training"))).count();
        Map<String, Object> summary = orderedMap();
        summary.put("row_count", rows.size());
        summary.put("approved_label_count", approved);
        summary.put("rejected_or_needs_evidence_count", rows.size() - approved);
        Map<String, Object> payload = orderedMap();
        payload.put("status", rows.isEmpty() ? "empty" : "ready");
        payload.put("mode", "review_label_decision_ledger_spring");
        payload.put("runtime", "java_spring");
        payload.put("created_at", now());
        payload.put("summary", summary);
        payload.put("rows", rows.stream().limit(Math.max(1, Math.min(limit, 1000))).toList());
        payload.put("training_rule", "Only approved/edit decisions are supervised-label evidence; none are reward.");
        payload.put("uses_seed_data", false);
        payload.put("labels_or_reward_changed", false);
        payload.put("llm_used_for_reward_or_label", false);
        return payload;
    }

    private List<Map<String, Object>> candidateRows() {
        List<Map<String, Object>> rows = new ArrayList<>();
        rows.add(venueProfileCandidate());
        rows.addAll(trainingCandidates());
        rows.addAll(liveFeedCandidates());
        Map<String, Map<String, Object>> deduped = new LinkedHashMap<>();
        for (Map<String, Object> row : rows) {
            deduped.put(string(row.get("id"), ""), row);
        }
        return new ArrayList<>(deduped.values());
    }

    private Map<String, Object> venueProfileCandidate() {
        Map<String, Object> profile = venueProfileService.profile();
        Map<String, Object> readiness = mapValue(profile.get("readiness"));
        Map<String, Object> counts = mapValue(readiness.get("counts"));
        boolean ready = "studio_ready".equals(readiness.get("status"));
        Map<String, Object> evidence = orderedMap();
        evidence.put("readiness_status", readiness.get("status"));
        evidence.put("venue_name", mapValue(profile.get("venueIdentity")).get("name"));
        evidence.put("locations", counts.get("locations"));
        evidence.put("safety_instructions", counts.get("safetyInstructions"));
        evidence.put("approved_synthetic", mapValue(profile.get("sourceIntegrity")).get("usesApprovedSyntheticProfile"));
        return candidate(
            "customer_agent",
            "customer_llm_supervised",
            "venue_profile_readiness",
            ready ? "medium" : "high",
            "Venue Profile readiness " + readiness.getOrDefault("status", "unknown") + " with " + counts.getOrDefault("locations", 0) + " verified locations.",
            ready ? "customer_recommendation_grounded" : "customer_feed_not_training_ready",
            List.of("customer_recommendation_grounded", "customer_feed_not_training_ready", "needs_reviewer_edit"),
            evidence,
            ready ? 0.91 : 0.58,
            List.of("Customer labels must not include private guest data or internal ops policy.")
        );
    }

    private List<Map<String, Object>> trainingCandidates() {
        return List.of(
            candidate(
                "scan_agent",
                "role_scoped_training",
                "spring_training_readiness",
                "medium",
                "scan_agent: Spring live-feed review labels require supervised disposition before model training.",
                "blocked_needs_more_evidence",
                List.of("training_ready", "eval_generation_ready", "blocked_needs_more_evidence", "reject_training_candidate"),
                Map.of("status", "needs_supervised_labels", "model_training_ready", false, "eval_generation_ready", true),
                0.82,
                List.of("Training readiness labels do not override source quality, review gates, or measured outcome requirements.")
            ),
            candidate(
                "ops_chat",
                "ops_chat_supervised",
                "spring_training_readiness",
                "medium",
                "ops_chat: review decisions can train explanation quality but cannot dispatch or set reward.",
                "eval_generation_ready",
                List.of("training_ready", "eval_generation_ready", "blocked_needs_more_evidence", "reject_training_candidate"),
                Map.of("status", "eval_ready", "model_training_ready", false, "eval_generation_ready", true),
                0.76,
                List.of("Ops-chat labels remain supervised evidence only.")
            )
        );
    }

    private List<Map<String, Object>> liveFeedCandidates() {
        Map<String, Object> liveLedger = liveFeedLedgerService.liveFeedLedgerStatus();
        Map<String, Object> reviewLedger = liveFeedLedgerService.reviewLedgerStatus();
        List<Map<String, Object>> rows = new ArrayList<>();
        rows.add(candidate(
            "scan_agent",
            "live_feed_quality_supervised",
            "live_feed_health",
            "medium",
            "Spring live-feed ledger contains " + liveLedger.getOrDefault("row_count", 0) + " events; review ledger contains " + reviewLedger.getOrDefault("row_count", 0) + " rows.",
            "weak_or_stale_feed",
            List.of("weak_or_stale_feed", "acceptable_feed", "needs_source_fix"),
            Map.of("live_feed_ledger", liveLedger, "review_ledger", reviewLedger),
            0.73,
            List.of("Feed quality labels should not mark generated data as real observation.")
        ));
        rows.add(candidate(
            "scan_agent",
            "live_feed_review_supervised",
            "review_training_ledger",
            "high",
            "Spring review queue pressure case needs corroboration before supervised training.",
            "needs_corroboration",
            List.of("trusted_signal", "needs_corroboration", "false_positive", "escalate_to_owner"),
            Map.of("case_id", "spring_queue_pressure", "reason", "Review required before label enters supervised training."),
            0.66,
            List.of("Live-feed review labels become supervised evidence only after human disposition.")
        ));
        return rows;
    }

    private Map<String, Object> candidate(
        String agentId,
        String trainingScope,
        String source,
        String priority,
        String inputSummary,
        String proposedLabel,
        List<String> labelOptions,
        Map<String, Object> evidence,
        double confidence,
        List<String> safetyNotes
    ) {
        Map<String, Object> basis = orderedMap();
        basis.put("agent_id", agentId);
        basis.put("training_scope", trainingScope);
        basis.put("source", source);
        basis.put("input_summary", inputSummary);
        basis.put("proposed_label", proposedLabel);
        basis.put("evidence_key", source + ":" + evidenceKey(evidence));

        Map<String, Object> row = orderedMap();
        row.put("id", "label_candidate_" + sha1(basis.toString(), 12));
        row.put("created_at", now());
        row.putAll(basis);
        row.put("priority", priority);
        row.put("label_options", labelOptions);
        row.put("evidence", evidence);
        row.put("recommendation", recommendation(confidence, proposedLabel));
        row.put("safety_notes", safetyNotes);
        row.put("review_status", "pending_review");
        row.put("eligible_for_supervised_training_if_approved", true);
        row.put("eligible_for_reward", false);
        row.put("boundary", "Auto-label is allowed only when recommendation confidence meets threshold; low-confidence candidates stay pending for human review.");
        return row;
    }

    private Map<String, Object> attachDecision(Map<String, Object> candidate, Map<String, Map<String, Object>> decisions) {
        Map<String, Object> row = mutableMap(candidate);
        Map<String, Object> decision = decisions.get(string(candidate.get("id"), ""));
        if (decision != null) {
            row.put("review_status", Boolean.TRUE.equals(decision.get("eligible_for_supervised_training")) ? "approved_for_supervised_training" : "closed_not_training");
            row.put("decision", decision);
        }
        return row;
    }

    private Map<String, Object> recommendation(double confidence, String proposedLabel) {
        double score = clamp(confidence);
        Map<String, Object> recommendation = orderedMap();
        recommendation.put("proposed_label", proposedLabel);
        recommendation.put("confidence", score);
        recommendation.put("confidence_status", score >= DEFAULT_AUTO_LABEL_CONFIDENCE_THRESHOLD ? "high" : score >= 0.55 ? "medium" : "low");
        recommendation.put("auto_label_eligible", score >= DEFAULT_AUTO_LABEL_CONFIDENCE_THRESHOLD);
        recommendation.put("auto_label_decision", score >= DEFAULT_AUTO_LABEL_CONFIDENCE_THRESHOLD ? "approve_label" : null);
        recommendation.put("low_confidence_action", score < DEFAULT_AUTO_LABEL_CONFIDENCE_THRESHOLD ? "human_review_required" : null);
        return recommendation;
    }

    private Map<String, Object> candidateSnapshot(Map<String, Object> candidate) {
        Map<String, Object> snapshot = orderedMap();
        for (String key : List.of("id", "agent_id", "training_scope", "source", "evidence_key", "input_summary", "proposed_label", "priority")) {
            snapshot.put(key, candidate.get(key));
        }
        return snapshot;
    }

    private Map<String, Map<String, Object>> latestDecisions() {
        Map<String, Map<String, Object>> decisions = new LinkedHashMap<>();
        for (Map<String, Object> row : readDecisionRows(1000)) {
            String candidateId = string(row.get("candidate_id"), "");
            if (!candidateId.isBlank() && !decisions.containsKey(candidateId)) {
                decisions.put(candidateId, row);
            }
        }
        return decisions;
    }

    private Map<String, Object> ledgerSummary(int limit) {
        return mapValue(decisionLedger(limit).get("summary"));
    }

    private void appendDecision(Map<String, Object> row) {
        Path path = decisionLogPath();
        try {
            Files.createDirectories(path.getParent());
            Files.writeString(
                path,
                objectMapper.writeValueAsString(row) + "\n",
                StandardCharsets.UTF_8,
                Files.exists(path) ? java.nio.file.StandardOpenOption.APPEND : java.nio.file.StandardOpenOption.CREATE
            );
        } catch (Exception error) {
            throw new IllegalStateException("Unable to append Spring review label decision.", error);
        }
    }

    private List<Map<String, Object>> readDecisionRows(int limit) {
        Path path = decisionLogPath();
        if (!Files.exists(path)) {
            return new ArrayList<>();
        }
        List<Map<String, Object>> rows = new ArrayList<>();
        try (var reader = Files.newBufferedReader(path, StandardCharsets.UTF_8)) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (!line.isBlank()) {
                    rows.add(objectMapper.readValue(line, MAP_TYPE));
                }
            }
        } catch (Exception ignored) {
            return rows;
        }
        rows.sort((left, right) -> string(right.get("created_at"), "").compareTo(string(left.get("created_at"), "")));
        return rows.stream().limit(limit).toList();
    }

    private Path decisionLogPath() {
        String configured = environment.getProperty("PARKPULSE_REVIEW_LABEL_DECISION_LOG_PATH", "");
        if (!configured.isBlank()) {
            return Path.of(configured);
        }
        return Path.of(environment.getProperty("PARKPULSE_RUNTIME_DIR", "/tmp/parkpulse")).resolve("review_label_decisions.jsonl");
    }

    private String evidenceKey(Map<String, Object> evidence) {
        LinkedHashSet<String> parts = new LinkedHashSet<>();
        for (String key : List.of("review_id", "case_id", "source", "status", "venue_name", "readiness_status", "reason")) {
            if (evidence.containsKey(key)) {
                parts.add(key + "=" + evidence.get(key));
            }
        }
        return parts.isEmpty() ? "role_scope" : String.join(":", parts);
    }

    private String trainingRule() {
        return "Approved review labels become supervised label evidence only. They do not set reward, promote policies, dispatch actions, or override measured outcomes.";
    }

    private Object firstPresent(Object left, Object right) {
        return left != null ? left : right;
    }

    private String firstString(Object... values) {
        for (Object value : values) {
            if (value != null && !String.valueOf(value).trim().isBlank()) {
                return String.valueOf(value).trim();
            }
        }
        return "";
    }

    private String truncate(String value, int maxLength) {
        return value.length() <= maxLength ? value : value.substring(0, maxLength);
    }

    private Map<String, Object> mapValue(Object value) {
        if (value instanceof Map<?, ?> map) {
            Map<String, Object> result = orderedMap();
            for (Map.Entry<?, ?> entry : map.entrySet()) {
                result.put(String.valueOf(entry.getKey()), entry.getValue());
            }
            return result;
        }
        return orderedMap();
    }

    private List<Object> listValue(Object value) {
        if (value instanceof List<?> list) {
            return new ArrayList<>(list);
        }
        return List.of();
    }

    private List<Map<String, Object>> listOfMaps(Object value) {
        List<Map<String, Object>> rows = new ArrayList<>();
        for (Object item : listValue(value)) {
            if (item instanceof Map<?, ?>) {
                rows.add(mapValue(item));
            }
        }
        return rows;
    }

    private Map<String, Object> mutableMap(Map<?, ?> map) {
        Map<String, Object> result = orderedMap();
        for (Map.Entry<?, ?> entry : map.entrySet()) {
            result.put(String.valueOf(entry.getKey()), entry.getValue());
        }
        return result;
    }

    private String string(Object value, String defaultValue) {
        if (value == null) {
            return defaultValue;
        }
        String text = String.valueOf(value).trim();
        return text.isBlank() ? defaultValue : text;
    }

    private double doubleValue(Object value, double defaultValue) {
        if (value instanceof Number number) {
            return number.doubleValue();
        }
        try {
            return Double.parseDouble(String.valueOf(value));
        } catch (Exception error) {
            return defaultValue;
        }
    }

    private double clamp(double value) {
        return Math.round(Math.max(0, Math.min(1, value)) * 1000.0) / 1000.0;
    }

    private String now() {
        return Instant.now().toString();
    }

    private String sha1(String value, int length) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-1");
            return HexFormat.of().formatHex(digest.digest(value.getBytes(StandardCharsets.UTF_8))).substring(0, Math.max(1, Math.min(length, 40)));
        } catch (Exception error) {
            return Long.toHexString(value.hashCode());
        }
    }

    private static LinkedHashMap<String, Object> orderedMap() {
        return new LinkedHashMap<>();
    }
}
