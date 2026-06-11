package com.parkpulse.backend;

import com.mongodb.ConnectionString;
import com.mongodb.MongoClientSettings;
import com.mongodb.client.MongoClient;
import com.mongodb.client.MongoClients;
import com.mongodb.client.MongoCollection;
import com.mongodb.client.MongoDatabase;
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
import java.util.concurrent.TimeUnit;
import org.bson.Document;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Service;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

@Service
public class AccessibilityJourneyMemoryService {
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};
    private static final List<String> FEEDBACK_LABELS = List.of(
        "guest_completed_route",
        "edited_route",
        "rerouted_for_accessibility",
        "allergy_staff_confirmed",
        "blocked_by_missing_profile_fact",
        "guest_reported_confusion"
    );

    private final Environment environment;
    private final ObjectMapper objectMapper;

    public AccessibilityJourneyMemoryService(Environment environment, ObjectMapper objectMapper) {
        this.environment = environment;
        this.objectMapper = objectMapper;
    }

    public Map<String, Object> persistJourney(Map<String, Object> journey) {
        Map<String, Object> summary = mapValue(journey.get("summary"));
        Map<String, Object> learning = mapValue(journey.get("learningReceipt"));
        String memoryId = "accessibility-journey-" + sha1(toJson(Map.of(
            "headline", string(summary.get("headline"), ""),
            "observation", mapValue(learning.get("observation")),
            "createdAt", Instant.now().toString()
        )), 16);

        Map<String, Object> record = orderedMap();
        record.put("event", "accessibility_journey_receipt_created");
        record.put("memory_id", memoryId);
        record.put("target_collection", "accessibility_journey_receipts");
        record.put("created_at", Instant.now().toString());
        record.put("runtime", "java_spring");
        record.put("summary", summary);
        record.put("profile", journey.get("profile"));
        record.put("live_state", journey.get("liveState"));
        record.put("learning_receipt", learning);
        record.put("llm_copy", journey.get("guestCopy"));
        record.put("review_required", mapValue(journey.get("summary")).get("requiresHumanReview"));
        record.put("privacy_boundary", "No private guest identity, medical diagnosis, disability identity, or protected class is stored.");
        append(receiptsPath(), record);
        Map<String, Object> mongoWrite = writeMongo("accessibility_journey_receipts", record);

        Map<String, Object> persistence = orderedMap();
        persistence.put("status", "stored");
        persistence.put("mode", "spring_accessibility_journey_jsonl_store");
        persistence.put("targetCollection", "accessibility_journey_receipts");
        persistence.put("memoryId", memoryId);
        persistence.put("mongoWritePerformedBySpring", Boolean.TRUE.equals(mongoWrite.get("written")));
        persistence.put("mongoBoundary", Boolean.TRUE.equals(mongoWrite.get("written"))
            ? "Spring wrote the aggregate accessibility receipt to MongoDB and kept a local JSONL receipt."
            : "Spring stores a durable JSONL receipt and emits the Mongo collection contract; configure MongoDB for native Spring writes.");
        persistence.put("mongoWrite", mongoWrite);
        persistence.put("durablePath", receiptsPath().toString());
        persistence.put("writePolicy", "store aggregate segment, route zones, source versions, feedback labels, and review outcome only");
        persistence.put("excludedFields", List.of("private guest identity", "medical diagnosis", "disability identity", "protected class"));
        persistence.put("requiresHumanReviewBeforeLearning", Boolean.TRUE.equals(mapValue(journey.get("summary")).get("requiresHumanReview")));
        persistence.put("runtime", "java_spring");
        return persistence;
    }

    public Map<String, Object> recordFeedback(Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        String memoryId = string(firstPresent(request.get("memoryId"), request.get("memory_id")), "");
        if (memoryId.isBlank()) {
            return Map.of("status", "invalid", "mode", "accessibility_journey_feedback_spring", "runtime", "java_spring", "readiness_issues", List.of("memoryId is required."));
        }
        String label = normalizeKey(string(firstPresent(request.get("feedbackLabel"), request.get("feedback_label")), ""));
        if (!FEEDBACK_LABELS.contains(label)) {
            return Map.of("status", "invalid", "mode", "accessibility_journey_feedback_spring", "runtime", "java_spring", "allowedLabels", FEEDBACK_LABELS, "readiness_issues", List.of("feedbackLabel is not allowed."));
        }
        boolean reviewed = truthy(firstPresent(request.get("humanReviewed"), request.get("human_reviewed")));
        Map<String, Object> feedback = orderedMap();
        feedback.put("event", "accessibility_journey_feedback_recorded");
        feedback.put("feedback_id", "aj-feedback-" + sha1(memoryId + ":" + label + ":" + Instant.now(), 12));
        feedback.put("memory_id", memoryId);
        feedback.put("feedback_label", label);
        feedback.put("human_reviewed", reviewed);
        feedback.put("reviewer", string(request.get("reviewer"), reviewed ? "ops_team" : "unreviewed"));
        feedback.put("notes", string(request.get("notes"), ""));
        feedback.put("created_at", Instant.now().toString());
        feedback.put("runtime", "java_spring");
        feedback.put("learning_eligible", reviewed && List.of("guest_completed_route", "rerouted_for_accessibility", "allergy_staff_confirmed").contains(label));
        feedback.put("mongo_target_collection", "accessibility_journey_feedback");
        feedback.put("privacy_boundary", "Feedback label stores aggregate route outcome only.");
        append(feedbackPath(), feedback);
        Map<String, Object> mongoWrite = writeMongo("accessibility_journey_feedback", feedback);

        return Map.of(
            "status", "recorded",
            "mode", "accessibility_journey_feedback_spring",
            "runtime", "java_spring",
            "feedback", feedback,
            "memoryPersistence", Map.of(
                "status", "stored",
                "targetCollection", "accessibility_journey_feedback",
                "mongoWritePerformedBySpring", Boolean.TRUE.equals(mongoWrite.get("written")),
                "mongoWrite", mongoWrite,
                "durablePath", feedbackPath().toString()
            )
        );
    }

    public Map<String, Object> memory(int limit) {
        int capped = Math.max(1, Math.min(limit, 100));
        List<Map<String, Object>> receipts = recent(receiptsPath(), capped);
        List<Map<String, Object>> feedback = recent(feedbackPath(), capped);
        return Map.of(
            "status", "ready",
            "mode", "accessibility_journey_memory_spring",
            "runtime", "java_spring",
            "memoryLayer", "spring_jsonl_authority_mongo_contract",
            "mongoConnection", mongoConnectionStatus(),
            "collections", Map.of(
                "accessibility_journey_receipts", receipts,
                "accessibility_journey_feedback", feedback
            ),
            "counts", Map.of("receipts", lineCount(receiptsPath()), "feedback", lineCount(feedbackPath())),
            "feedbackLabels", FEEDBACK_LABELS
        );
    }

    private void append(Path path, Map<String, Object> record) {
        try {
            Files.createDirectories(path.getParent());
            Files.writeString(path, objectMapper.writeValueAsString(record) + "\n", StandardCharsets.UTF_8, Files.exists(path) ? java.nio.file.StandardOpenOption.APPEND : java.nio.file.StandardOpenOption.CREATE);
        } catch (Exception error) {
            throw new IllegalStateException("Unable to append Accessibility Journey memory record.", error);
        }
    }

    private List<Map<String, Object>> recent(Path path, int limit) {
        if (!Files.exists(path)) {
            return List.of();
        }
        Deque<String> tail = new ArrayDeque<>(limit);
        try (var reader = Files.newBufferedReader(path, StandardCharsets.UTF_8)) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.isBlank()) continue;
                if (tail.size() == limit) tail.removeFirst();
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

    private long lineCount(Path path) {
        if (!Files.exists(path)) return 0;
        try (var lines = Files.lines(path, StandardCharsets.UTF_8)) {
            return lines.filter(line -> !line.isBlank()).count();
        } catch (Exception ignored) {
            return 0;
        }
    }

    private Map<String, Object> writeMongo(String collectionName, Map<String, Object> record) {
        String uri = firstPresentEnv("MONGODB_DIRECT_URI", "MONGODB_URI", "MONGO_URI", "PARKPULSE_MONGODB_URI");
        if (uri.isBlank()) {
            return Map.of("configured", false, "written", false, "collection", collectionName, "reason", "Mongo URI is not configured.");
        }
        try (MongoClient client = MongoClients.create(mongoSettings(uri))) {
            MongoDatabase database = client.getDatabase(mongoDatabase());
            MongoCollection<Document> collection = database.getCollection(collectionName);
            collection.insertOne(Document.parse(toJson(record)));
            return Map.of(
                "configured", true,
                "written", true,
                "database", mongoDatabase(),
                "collection", collectionName,
                "mode", "mongodb"
            );
        } catch (Exception error) {
            return Map.of(
                "configured", true,
                "written", false,
                "database", mongoDatabase(),
                "collection", collectionName,
                "mode", "mongodb",
                "reason", truncate(error.getMessage(), 220)
            );
        }
    }

    private MongoClientSettings mongoSettings(String uri) {
        int timeoutMs = Math.max(250, Math.min(intEnv("MONGODB_OPERATION_TIMEOUT_MS", 2500), 15000));
        return MongoClientSettings.builder()
            .applyConnectionString(new ConnectionString(uri))
            .applyToClusterSettings(builder -> builder.serverSelectionTimeout(timeoutMs, TimeUnit.MILLISECONDS))
            .applyToSocketSettings(builder -> builder.connectTimeout(timeoutMs, TimeUnit.MILLISECONDS).readTimeout(timeoutMs, TimeUnit.MILLISECONDS))
            .build();
    }

    private Map<String, Object> mongoConnectionStatus() {
        String uri = firstPresentEnv("MONGODB_DIRECT_URI", "MONGODB_URI", "MONGO_URI", "PARKPULSE_MONGODB_URI");
        return Map.of(
            "configured", !uri.isBlank(),
            "connected", false,
            "database", mongoDatabase(),
            "collections", List.of("accessibility_journey_receipts", "accessibility_journey_feedback"),
            "reason", uri.isBlank() ? "Mongo URI is not configured." : "Connection is checked during writes and reported per receipt."
        );
    }

    private Path receiptsPath() {
        String configured = env("PARKPULSE_ACCESSIBILITY_JOURNEY_RECEIPTS_PATH", "");
        return configured.isBlank() ? runtimeDir().resolve("accessibility_journey_receipts.jsonl") : Path.of(configured);
    }

    private Path feedbackPath() {
        String configured = env("PARKPULSE_ACCESSIBILITY_JOURNEY_FEEDBACK_PATH", "");
        return configured.isBlank() ? runtimeDir().resolve("accessibility_journey_feedback.jsonl") : Path.of(configured);
    }

    private Path runtimeDir() {
        return Path.of(env("PARKPULSE_RUNTIME_DIR", "/tmp/parkpulse"));
    }

    private String env(String key, String defaultValue) {
        String value = environment.getProperty(key);
        return value == null || value.isBlank() ? defaultValue : value;
    }

    private String firstPresentEnv(String... keys) {
        for (String key : keys) {
            String value = env(key, "");
            if (!value.isBlank()) return value;
        }
        return "";
    }

    private String mongoDatabase() {
        String specific = firstPresentEnv("PARKPULSE_ACCESSIBILITY_MONGO_DATABASE", "MONGODB_DATABASE");
        return specific.isBlank() ? "parkpulse_ops" : specific;
    }

    private int intEnv(String key, int defaultValue) {
        try {
            return Integer.parseInt(env(key, String.valueOf(defaultValue)));
        } catch (Exception error) {
            return defaultValue;
        }
    }

    private Object firstPresent(Object left, Object right) {
        return left == null ? right : left;
    }

    private Map<String, Object> mapValue(Object value) {
        if (value instanceof Map<?, ?> map) {
            return mutableMap(map);
        }
        return orderedMap();
    }

    private Map<String, Object> mutableMap(Map<?, ?> source) {
        Map<String, Object> result = orderedMap();
        for (Map.Entry<?, ?> entry : source.entrySet()) {
            result.put(String.valueOf(entry.getKey()), entry.getValue());
        }
        return result;
    }

    private String string(Object value, String defaultValue) {
        if (value == null) return defaultValue;
        String text = String.valueOf(value).trim();
        return text.isBlank() ? defaultValue : text;
    }

    private String truncate(String value, int length) {
        String text = value == null ? "" : value;
        return text.length() <= length ? text : text.substring(0, length);
    }

    private boolean truthy(Object value) {
        if (value instanceof Boolean bool) return bool;
        if (value instanceof Number number) return number.doubleValue() != 0;
        return List.of("1", "true", "yes", "on").contains(string(value, "").toLowerCase());
    }

    private String normalizeKey(String value) {
        return value == null || value.isBlank() ? "" : value.trim().toLowerCase().replace('-', '_').replace(' ', '_');
    }

    private String toJson(Object payload) {
        try {
            return objectMapper.writeValueAsString(payload);
        } catch (Exception error) {
            return "{}";
        }
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
