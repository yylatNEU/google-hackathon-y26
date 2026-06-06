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
public class StaffTrainingService {
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

    private final Environment environment;
    private final ObjectMapper objectMapper;
    private final ProductLearningService productLearningService;
    private final Map<String, Map<String, Object>> sessions = new ConcurrentHashMap<>();

    public StaffTrainingService(Environment environment, ObjectMapper objectMapper, ProductLearningService productLearningService) {
        this.environment = environment;
        this.objectMapper = objectMapper;
        this.productLearningService = productLearningService;
    }

    public Map<String, Object> scenarios() {
        return Map.of("status", "ready", "mode", "staff_roleplay_scenarios_spring", "runtime", "java_spring", "scenarios", scenarioRows());
    }

    public Map<String, Object> policyPack() {
        return Map.of(
            "status", "ready",
            "mode", "staff_roleplay_policy_pack_spring",
            "runtime", "java_spring",
            "policy_refs", List.of("PARK-SAFE-001", "PARK-CARE-001"),
            "golden_eval_route", "/api/park/staff-training/golden-eval",
            "boundary", "Spring roleplay scoring is deterministic; LLM guest generation can be restored behind a later provider adapter."
        );
    }

    public Map<String, Object> createAssignment(Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        List<String> scenarioIds = stringList(request.get("scenario_ids"), request.get("scenarioIds"));
        if (scenarioIds.isEmpty()) {
            scenarioIds = scenarioRows().stream().map(row -> String.valueOf(row.get("id"))).toList();
        }
        Map<String, Object> assignment = orderedMap();
        assignment.put("event", "staff_training_assignment_created");
        assignment.put("id", "assign-" + sha1(firstString(request.get("trainee_name"), request.get("traineeName"), "team-member") + ":" + now(), 10));
        assignment.put("trainee_name", firstString(request.get("trainee_name"), request.get("traineeName"), "Team Member"));
        assignment.put("staff_role", firstString(request.get("staff_role"), request.get("staffRole"), "guest_care"));
        assignment.put("scenario_ids", scenarioIds);
        assignment.put("scenarios", scenariosForIds(scenarioIds));
        assignment.put("status", "assigned");
        assignment.put("completed_count", 0);
        assignment.put("required_count", scenarioIds.size());
        assignment.put("last_score", null);
        assignment.put("critical_miss_count", 0);
        assignment.put("created_at", now());
        assignment.put("runtime", "java_spring");
        appendEvent(assignment);
        return Map.of("status", "created", "mode", "staff_roleplay_assignment_spring", "runtime", "java_spring", "assignment", assignment, "ledger", ledgerStatus());
    }

    public Map<String, Object> assignments(int limit) {
        List<Map<String, Object>> rows = assignmentRows(limit);
        return Map.of("status", "ready", "mode", "staff_roleplay_assignments_spring", "runtime", "java_spring", "assignments", rows, "ledger", ledgerStatus());
    }

    public Map<String, Object> readiness(int limit) {
        List<Map<String, Object>> rows = assignmentRows(limit).stream().map(this::readinessRow).toList();
        return Map.of("status", "ready", "mode", "staff_roleplay_readiness_spring", "runtime", "java_spring", "readiness", rows, "ledger", ledgerStatus());
    }

    public Map<String, Object> receipts(int limit) {
        List<Map<String, Object>> rows = receiptRows(limit);
        return Map.of("status", "ready", "mode", "staff_roleplay_receipts_spring", "runtime", "java_spring", "receipts", rows, "ledger", ledgerStatus());
    }

    public Map<String, Object> certificationPacket(String assignmentId, String traineeName) {
        Map<String, Object> assignment = assignmentRows(200).stream()
            .filter(row -> matches(row, assignmentId, traineeName))
            .findFirst()
            .orElseGet(() -> assignmentRows(1).stream().findFirst().orElse(defaultAssignment()));
        List<Map<String, Object>> receipts = receiptRows(100).stream()
            .filter(row -> String.valueOf(assignment.get("id")).equals(String.valueOf(row.get("assignment_id"))))
            .toList();
        Map<String, Object> payload = orderedMap();
        payload.put("status", "ready");
        payload.put("mode", "staff_roleplay_certification_packet_spring");
        payload.put("runtime", "java_spring");
        payload.put("id", "packet-" + assignment.get("id"));
        payload.put("packet_status", receipts.isEmpty() ? "in_progress" : "manager_review_ready");
        payload.put("assignment", assignment);
        payload.put("receipts", receipts);
        payload.put("readiness", readinessRow(assignment));
        payload.put("gate_contract", Map.of("minimum_live_shadowing_gate", "manager_approved_receipt", "manager_review_can_override_score", true, "manager_review_can_hold_or_require_retry", true));
        payload.put("boundary", "Certification packet summarizes Spring receipts only; live shadowing still requires manager approval.");
        return payload;
    }

    public Map<String, Object> reviewReceipt(Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        Map<String, Object> review = orderedMap();
        review.put("event", "staff_training_receipt_reviewed");
        review.put("id", "review-" + sha1(firstString(request.get("session_id"), request.get("sessionId"), request.get("receipt_id"), request.get("receiptId"), now()), 10));
        review.put("session_id", firstString(request.get("session_id"), request.get("sessionId"), ""));
        review.put("receipt_id", firstString(request.get("receipt_id"), request.get("receiptId"), ""));
        review.put("decision", firstString(request.get("decision"), "hold"));
        review.put("reviewer", firstString(request.get("reviewer"), "Training manager"));
        review.put("notes", firstString(request.get("notes"), ""));
        review.put("recorded_at", now());
        review.put("runtime", "java_spring");
        appendEvent(review);
        return Map.of("status", "recorded", "mode", "staff_roleplay_receipt_review_spring", "runtime", "java_spring", "review", review, "ledger", ledgerStatus());
    }

    public Map<String, Object> seedDemoData() {
        Map<String, Object> assignment = mutableMap(defaultAssignment());
        assignment.put("event", "staff_training_assignment_created");
        appendEvent(assignment);
        Map<String, Object> receipt = demoReceipt(String.valueOf(assignment.get("id")), String.valueOf(assignment.get("trainee_name")));
        appendEvent(receipt);
        return Map.of("status", "seeded", "mode", "staff_roleplay_demo_seed_spring", "runtime", "java_spring", "assignment", assignment, "receipt", receipt, "ledger", ledgerStatus());
    }

    public Map<String, Object> goldenEval() {
        return Map.of(
            "status", "ready",
            "mode", "staff_roleplay_golden_eval_spring",
            "runtime", "java_spring",
            "case_count", 2,
            "cases", List.of(
                Map.of("scenario_id", "angry_parent", "expected", "acknowledge emotion, explain policy, escalate when threshold is met"),
                Map.of("scenario_id", "lost_child", "expected", "prioritize safety, notify security, stay with guest")
            )
        );
    }

    public Map<String, Object> startSession(Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        String scenarioId = firstString(request.get("scenario_id"), request.get("scenarioId"), request.get("scenario_key"), request.get("scenarioKey"), "angry_parent");
        Map<String, Object> scenario = scenarioById(scenarioId);
        String sessionId = "staff-session-" + sha1(firstString(request.get("trainee_name"), request.get("traineeName"), "Team Member") + ":" + scenarioId + ":" + now(), 12);
        Map<String, Object> session = orderedMap();
        session.put("id", sessionId);
        session.put("assignment_id", firstString(request.get("assignment_id"), request.get("assignmentId"), ""));
        session.put("retry_of_session_id", firstString(request.get("retry_of_session_id"), request.get("retryOfSessionId"), ""));
        session.put("status", "active");
        session.put("scenario", scenario);
        session.put("trainee_name", firstString(request.get("trainee_name"), request.get("traineeName"), "Team Member"));
        session.put("turn_count", 0);
        session.put("transcript", List.of(Map.of("speaker", "guest", "message", scenario.get("opening_message"), "source", "deterministic_guest")));
        session.put("scorecard", scorecard(0, false));
        session.put("critical_miss", false);
        session.put("completed_objectives", List.of());
        session.put("missing_objectives", scenario.get("objectives"));
        session.put("guest_simulator", guestSimulator(Boolean.TRUE.equals(request.get("useLlmGuest"))));
        session.put("mastery_tracker", masteryTracker(false, 0));
        sessions.put(sessionId, session);
        return session;
    }

    public Map<String, Object> advanceTurn(Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        String sessionId = firstString(request.get("session_id"), request.get("sessionId"), "");
        Map<String, Object> session = sessions.getOrDefault(sessionId, startSession(Map.of("scenario_id", "angry_parent")));
        String message = firstString(request.get("employee_message"), request.get("employeeMessage"), request.get("message"), "");
        int nextTurn = intValue(session.get("turn_count")) + 1;
        boolean strong = message.toLowerCase().contains("sorry") || message.toLowerCase().contains("help") || message.toLowerCase().contains("manager") || message.toLowerCase().contains("policy");
        Map<String, Object> turnScore = turnScore(strong, nextTurn);
        List<Object> transcript = new ArrayList<>(listValue(session.get("transcript")));
        transcript.add(Map.of("speaker", "employee", "message", message, "source", "employee"));
        transcript.add(Map.of("speaker", "guest", "message", strong ? "Thanks for explaining the next step." : "I still need a clearer answer.", "source", "deterministic_guest"));
        session.put("transcript", transcript);
        session.put("turn_count", nextTurn);
        session.put("scorecard", scorecard(intValue(turnScore.get("overall")), !strong));
        session.put("critical_miss", !strong);
        session.put("completed_objectives", strong ? listValue(mapValue(session.get("scenario")).get("objectives")) : List.of());
        session.put("missing_objectives", strong ? List.of() : mapValue(session.get("scenario")).get("objectives"));
        session.put("mastery_tracker", masteryTracker(strong, nextTurn));
        sessions.put(String.valueOf(session.get("id")), session);
        Map<String, Object> payload = orderedMap();
        payload.put("status", "scored");
        payload.put("mode", "staff_roleplay_turn_spring");
        payload.put("runtime", "java_spring");
        payload.put("session", session);
        payload.put("turn_score", turnScore);
        payload.put("coaching_notes", turnScore.get("coaching_notes"));
        payload.put("shadow_evaluator", shadowEvaluator(Boolean.TRUE.equals(request.get("useShadowEval")), strong));
        payload.put("readiness_issues", List.of());
        return payload;
    }

    public Map<String, Object> finishSession(Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        String sessionId = firstString(request.get("session_id"), request.get("sessionId"), "");
        Map<String, Object> session = sessions.getOrDefault(sessionId, startSession(Map.of("scenario_id", "angry_parent")));
        boolean passed = intValue(mapValue(session.get("scorecard")).get("overall")) >= 80 && !Boolean.TRUE.equals(session.get("critical_miss"));
        session.put("status", "finished");
        Map<String, Object> debrief = orderedMap();
        debrief.put("result", passed ? "pass" : "retry");
        debrief.put("summary", passed ? "Ready for manager review." : "Retry required before live shadowing.");
        debrief.put("overall", mapValue(session.get("scorecard")).get("overall"));
        debrief.put("critical_miss", !passed);
        debrief.put("recommended_retry", passed ? null : mapValue(session.get("scenario")).get("id"));
        session.put("debrief", debrief);
        Map<String, Object> receipt = receiptFromSession(session, passed);
        appendEvent(receipt);
        if (!passed) {
            Map<String, Object> gapRequest = Map.of("scenarioId", mapValue(session.get("scenario")).get("id"), "gapType", "policy_correctness", "severity", "critical_training_gap", "evidence", Map.of("summary", "Spring staff roleplay retry required."), "sessionId", session.get("id"), "traineeName", session.get("trainee_name"));
            session.put("training_gap_ticket", productLearningService.createTrainingGapTicket(gapRequest));
        }
        sessions.put(String.valueOf(session.get("id")), session);
        return Map.of("status", "finished", "mode", "staff_roleplay_finish_spring", "runtime", "java_spring", "session", session, "receipt", receipt, "ledger", ledgerStatus(), "readiness_issues", List.of());
    }

    public Map<String, Object> analytics(int limit) {
        List<Map<String, Object>> receipts = receiptRows(limit);
        double average = receipts.stream().mapToInt(row -> intValue(row.get("overall"))).average().orElse(0);
        return Map.of(
            "status", "ready",
            "mode", "staff_roleplay_analytics_spring",
            "runtime", "java_spring",
            "session_count", receipts.size(),
            "average_score", Math.round(average),
            "scenario_summary", List.of(Map.of("scenario_id", "angry_parent", "title", "Angry parent at queue merge", "session_count", receipts.size(), "average_overall", Math.round(average), "critical_miss_count", receipts.stream().filter(row -> Boolean.TRUE.equals(row.get("critical_miss"))).count())),
            "weakest_dimensions", List.of(Map.of("dimension", "policy_correctness", "average", receipts.isEmpty() ? 0 : 3.8)),
            "ledger", ledgerStatus()
        );
    }

    private List<Map<String, Object>> scenarioRows() {
        return List.of(
            scenario("angry_parent", "Angry parent at queue merge", "guest_care", "medium", "frustrated_parent", "My child has been waiting forever and nobody is helping us.", "Queue pressure after a ride merge is creating guest-care risk.", List.of("acknowledge emotion", "explain policy", "offer escalation")),
            scenario("lost_child", "Lost child report", "safety", "high", "worried_guardian", "I cannot find my child near the plaza.", "Safety-sensitive missing child report near a dense area.", List.of("stay with guest", "notify security", "avoid unsupported claims"))
        );
    }

    private Map<String, Object> scenario(String id, String title, String category, String difficulty, String guestRole, String opening, String context, List<String> objectives) {
        Map<String, Object> row = orderedMap();
        row.put("id", id);
        row.put("title", title);
        row.put("category", category);
        row.put("difficulty", difficulty);
        row.put("guest_role", guestRole);
        row.put("opening_message", opening);
        row.put("context", context);
        row.put("objectives", objectives);
        return row;
    }

    private List<Map<String, Object>> assignmentRows(int limit) {
        List<Map<String, Object>> rows = recentRows(limit).stream().filter(row -> "staff_training_assignment_created".equals(String.valueOf(row.get("event")))).toList();
        return rows.isEmpty() ? List.of(defaultAssignment()) : rows;
    }

    private List<Map<String, Object>> receiptRows(int limit) {
        return recentRows(limit).stream().filter(row -> "staff_training_receipt_created".equals(String.valueOf(row.get("event")))).toList();
    }

    private Map<String, Object> defaultAssignment() {
        Map<String, Object> row = orderedMap();
        row.put("id", "assign-spring-demo");
        row.put("trainee_name", "Demo Team Member");
        row.put("staff_role", "guest_care");
        row.put("scenario_ids", List.of("angry_parent", "lost_child"));
        row.put("scenarios", scenarioRows());
        row.put("status", "assigned");
        row.put("completed_count", 0);
        row.put("required_count", 2);
        row.put("last_score", null);
        row.put("critical_miss_count", 0);
        return row;
    }

    private Map<String, Object> readinessRow(Map<String, Object> assignment) {
        List<String> scenarioIds = stringList(assignment.get("scenario_ids"));
        Map<String, Object> row = orderedMap();
        row.put("assignment_id", assignment.get("id"));
        row.put("trainee_name", assignment.get("trainee_name"));
        row.put("staff_role", assignment.get("staff_role"));
        row.put("status", assignment.get("status"));
        row.put("required_count", assignment.get("required_count"));
        row.put("completed_count", assignment.get("completed_count"));
        row.put("required_scenarios", scenarioIds);
        row.put("completed_scenarios", List.of());
        row.put("needs_retry_scenarios", List.of());
        row.put("last_score", assignment.get("last_score"));
        row.put("average_score", assignment.get("last_score"));
        row.put("critical_miss_count", assignment.get("critical_miss_count"));
        row.put("review_hold_count", 0);
        row.put("live_shadowing_gate", "manager_review_required");
        return row;
    }

    private Map<String, Object> receiptFromSession(Map<String, Object> session, boolean passed) {
        Map<String, Object> scenario = mapValue(session.get("scenario"));
        Map<String, Object> receipt = orderedMap();
        receipt.put("event", "staff_training_receipt_created");
        receipt.put("id", "receipt-" + session.get("id"));
        receipt.put("session_id", session.get("id"));
        receipt.put("assignment_id", session.get("assignment_id"));
        receipt.put("trainee_name", session.get("trainee_name"));
        receipt.put("scenario_title", scenario.get("title"));
        receipt.put("overall", mapValue(session.get("scorecard")).get("overall"));
        receipt.put("critical_miss", !passed);
        receipt.put("result", passed ? "pass" : "retry");
        receipt.put("manager_review_required", true);
        receipt.put("review_status", "pending_manager_review");
        receipt.put("manager_review", null);
        receipt.put("created_at", now());
        receipt.put("runtime", "java_spring");
        return receipt;
    }

    private Map<String, Object> demoReceipt(String assignmentId, String trainee) {
        Map<String, Object> session = startSession(Map.of("scenario_id", "angry_parent", "traineeName", trainee, "assignmentId", assignmentId));
        session.put("scorecard", scorecard(84, false));
        session.put("critical_miss", false);
        return receiptFromSession(session, true);
    }

    private Map<String, Object> turnScore(boolean strong, int turn) {
        Map<String, Object> score = orderedMap();
        score.put("overall", strong ? 84 : 58);
        score.put("dimensions", Map.of("empathy", strong ? 4 : 2, "policy_correctness", strong ? 4 : 2, "escalation_decision", strong ? 4 : 2, "clarity", strong ? 4 : 3, "safety_awareness", strong ? 4 : 2));
        score.put("coaching_notes", strong ? List.of("Clear acknowledgement and policy-grounded next step.") : List.of("Acknowledge the guest first and name the escalation path."));
        score.put("critical_miss", !strong);
        score.put("turn_coaching", Map.of(
            "verdict", strong ? "good" : "needs_repair",
            "headline", strong ? "Good recovery path" : "Repair the policy response",
            "priority", strong ? "Keep the explanation concise." : "Name the next safe action and escalation.",
            "strengths", strong ? List.of("Empathy", "Policy explanation") : List.of("Responded promptly"),
            "misses", strong ? List.of() : List.of(Map.of("type", "policy_correctness", "label", "Missing clear policy or manager escalation.")),
            "weak_dimensions", List.of(Map.of("dimension", "policy_correctness", "label", "Policy", "score", strong ? 4 : 2)),
            "next_response", strong ? "I will stay with you while we get this handled." : "Start with: I am sorry this has been frustrating; here is what I can do next."
        ));
        return score;
    }

    private Map<String, Object> scorecard(int overall, boolean criticalMiss) {
        return Map.of("overall", overall == 0 ? 72 : overall, "turn_count", overall == 0 ? 0 : 1, "dimensions", Map.of("empathy", criticalMiss ? 2 : 4, "policy_correctness", criticalMiss ? 2 : 4, "escalation_decision", criticalMiss ? 2 : 4, "clarity", criticalMiss ? 3 : 4, "safety_awareness", criticalMiss ? 2 : 4));
    }

    private Map<String, Object> guestSimulator(boolean requested) {
        return Map.of("mode", "deterministic_spring_guest", "llm_requested", requested, "llm_status", requested ? "provider_not_used_in_spring_slice" : "not_requested", "llm_controls_score", false, "source", "spring");
    }

    private Map<String, Object> masteryTracker(boolean strong, int turn) {
        return Map.of("status", "ready", "mastery_level", strong ? "ready_for_review" : "needs_repair", "turn_count", turn, "open_gaps", strong ? List.of() : List.of(Map.of("key", "policy_correctness", "type", "policy_correctness", "label", "Explain the policy and escalation.", "severity", "critical", "first_seen_turn", turn, "last_seen_turn", turn)), "repaired_gaps", List.of(), "latest_repairs", List.of(), "repair_count", 0, "unrepaired_critical_count", strong ? 0 : 1, "summary", strong ? "No open critical gaps." : "One critical gap remains open.");
    }

    private Map<String, Object> shadowEvaluator(boolean requested, boolean strong) {
        return Map.of("status", requested ? "complete" : "not_requested", "alignment", strong ? "aligned" : "needs_review", "summary", requested ? "Spring deterministic shadow evaluator completed." : "Shadow evaluator was not requested.", "coaching_focus", strong ? List.of("reinforce concise policy explanation") : List.of("repair escalation decision"), "suggested_human_review", !strong, "score_authority", false, "provider", "spring_deterministic", "llm_controls_score", false);
    }

    private Map<String, Object> scenarioById(String id) {
        return scenarioRows().stream().filter(row -> id.equals(String.valueOf(row.get("id")))).findFirst().orElseGet(() -> scenarioRows().get(0));
    }

    private List<Map<String, Object>> scenariosForIds(List<String> ids) {
        return ids.stream().map(this::scenarioById).toList();
    }

    private boolean matches(Map<String, Object> assignment, String assignmentId, String traineeName) {
        return (assignmentId != null && !assignmentId.isBlank() && assignmentId.equals(String.valueOf(assignment.get("id"))))
            || (traineeName != null && !traineeName.isBlank() && traineeName.equals(String.valueOf(assignment.get("trainee_name"))));
    }

    private void appendEvent(Map<String, Object> event) {
        try {
            Path path = ledgerPath();
            Files.createDirectories(path.getParent());
            Files.writeString(path, objectMapper.writeValueAsString(event) + "\n", StandardCharsets.UTF_8, Files.exists(path) ? java.nio.file.StandardOpenOption.APPEND : java.nio.file.StandardOpenOption.CREATE);
        } catch (Exception error) {
            throw new IllegalStateException("Unable to append staff-training event.", error);
        }
    }

    private List<Map<String, Object>> recentRows(int limit) {
        Path path = ledgerPath();
        if (!Files.exists(path)) {
            return new ArrayList<>();
        }
        int cappedLimit = Math.max(1, Math.min(limit, 500));
        Deque<String> tail = new ArrayDeque<>(cappedLimit);
        try (var reader = Files.newBufferedReader(path, StandardCharsets.UTF_8)) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (!line.isBlank()) {
                    if (tail.size() == cappedLimit) {
                        tail.removeFirst();
                    }
                    tail.addLast(line);
                }
            }
        } catch (Exception ignored) {
            return new ArrayList<>();
        }
        List<Map<String, Object>> rows = new ArrayList<>();
        while (!tail.isEmpty()) {
            try {
                rows.add(objectMapper.readValue(tail.removeLast(), MAP_TYPE));
            } catch (Exception ignored) {
                // Ignore malformed historical rows.
            }
        }
        return rows;
    }

    private Map<String, Object> ledgerStatus() {
        Path path = ledgerPath();
        return Map.of("mode", "spring_staff_training_jsonl_ledger", "path", path.toString(), "ready", true, "count", lineCount(path), "runtime", "java_spring");
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

    private Path ledgerPath() {
        String configured = env("PARKPULSE_STAFF_TRAINING_LEDGER", "");
        if (!configured.isBlank()) {
            return Path.of(configured);
        }
        return Path.of(env("PARKPULSE_RUNTIME_DIR", "/tmp/parkpulse")).resolve("staff_training_ledger.jsonl");
    }

    private String env(String key, String defaultValue) {
        String value = environment.getProperty(key);
        return value == null || value.isBlank() ? defaultValue : value;
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

    private static int intValue(Object value) {
        if (value instanceof Number number) {
            return number.intValue();
        }
        try {
            return value == null ? 0 : Integer.parseInt(String.valueOf(value));
        } catch (Exception ignored) {
            return 0;
        }
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

    private static List<String> stringList(Object... values) {
        for (Object value : values) {
            if (value instanceof List<?> list) {
                return list.stream().map(String::valueOf).filter(item -> !item.isBlank()).toList();
            }
        }
        return List.of();
    }
}
