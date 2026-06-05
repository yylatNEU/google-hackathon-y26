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
public class LiveFeedLedgerService {
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

    private final Environment environment;
    private final ObjectMapper objectMapper;
    private final Map<Path, CountSnapshot> lineCountCache = new ConcurrentHashMap<>();
    private final Map<Path, RecentRowsSnapshot> recentRowsCache = new ConcurrentHashMap<>();

    public LiveFeedLedgerService(Environment environment, ObjectMapper objectMapper) {
        this.environment = environment;
        this.objectMapper = objectMapper;
    }

    public Map<String, Object> recordLiveFeedEvents(Map<String, Object> body) {
        List<Map<String, Object>> records = normalizeLiveFeedRecords(body);
        records.forEach(this::appendLiveFeedRecord);
        Map<String, Object> payload = orderedMap();
        payload.put("status", "recorded");
        payload.put("mode", "normalized_live_feed_ingest_spring");
        payload.put("runtime", "java_spring");
        payload.put("event_count", records.size());
        payload.put("stored", true);
        payload.put("authority", "spring_live_feed_jsonl_ledger");
        payload.put("events", records);
        payload.put("ledger", liveFeedLedgerStatus());
        payload.put("readiness_issues", List.of());
        return payload;
    }

    public Map<String, Object> recordFeedLoad(String source, Map<String, Object> request, int eventCount, Map<String, Object> config) {
        Map<String, Object> body = orderedMap();
        body.put("source", source);
        body.put("signal_type", "feed_load");
        body.put("event_count", eventCount);
        body.put("request", request == null ? Map.of() : request);
        body.put("config", config);
        body.put("provider", "spring_projection");
        Map<String, Object> record = liveFeedRecord(source, body);
        appendLiveFeedRecord(record);
        Map<String, Object> payload = orderedMap();
        payload.put("stored", true);
        payload.put("event", record);
        payload.put("ledger", liveFeedLedgerStatus());
        return payload;
    }

    public Map<String, Object> recordRefreshSupervisor(Map<String, Object> refresh) {
        Map<String, Object> record = liveFeedRecord("refresh-supervisor", refresh);
        appendLiveFeedRecord(record);
        Map<String, Object> payload = orderedMap();
        payload.put("stored", true);
        payload.put("event", record);
        payload.put("ledger", liveFeedLedgerStatus());
        return payload;
    }

    public Map<String, Object> recordReviewDecision(Map<String, Object> decision) {
        Map<String, Object> safeDecision = decision == null ? orderedMap() : mutableMap(decision);
        String reviewId = string(safeDecision.get("review_session_id"), "spring-review-decision");
        Map<String, Object> record = orderedMap();
        record.put("review_session_id", reviewId);
        record.put("case_id", string(safeDecision.get("case_id"), string(safeDecision.get("caseId"), "spring_queue_pressure")));
        record.put("status", string(safeDecision.get("status"), "closed"));
        record.put("owner", string(safeDecision.get("owner"), "ops_team"));
        record.put("training_candidate", true);
        record.put("decision", safeDecision);
        record.put("reason", string(safeDecision.get("reason"), "Spring recorded human review decision for supervised training ledger."));
        record.put("recorded_at", now());
        record.put("updated_at", record.get("recorded_at"));
        record.put("runtime", "java_spring");
        appendReviewRecord(record);

        Map<String, Object> payload = orderedMap();
        payload.put("status", "recorded");
        payload.put("mode", "review_training_ledger_decision_spring");
        payload.put("runtime", "java_spring");
        payload.put("stored", true);
        payload.put("decision", safeDecision);
        payload.put("review", record);
        payload.put("ledger", reviewLedgerStatus());
        payload.put("readiness_issues", List.of());
        return payload;
    }

    public List<Map<String, Object>> recentLiveFeedEvents(int limit) {
        return recentRows(liveFeedPath(), limit);
    }

    public List<Map<String, Object>> reviewRows(int limit) {
        return recentRows(reviewLedgerPath(), limit);
    }

    public Map<String, Object> liveFeedLedgerStatus() {
        return ledgerStatus("spring_live_feed_jsonl_ledger", liveFeedPath());
    }

    public Map<String, Object> reviewLedgerStatus() {
        return ledgerStatus("spring_review_training_jsonl_ledger", reviewLedgerPath());
    }

    private List<Map<String, Object>> normalizeLiveFeedRecords(Map<String, Object> body) {
        if (body == null || body.isEmpty()) {
            return List.of();
        }
        Object events = body.get("events");
        if (events instanceof List<?> list) {
            List<Map<String, Object>> records = new ArrayList<>();
            for (Object item : list) {
                if (item instanceof Map<?, ?> eventMap) {
                    Map<String, Object> event = mutableMap(eventMap);
                    records.add(liveFeedRecord(string(event.get("source"), "operator-signal"), event));
                }
            }
            return records;
        }
        return List.of(liveFeedRecord(string(body.get("source"), "operator-signal"), body));
    }

    private Map<String, Object> liveFeedRecord(String source, Map<String, Object> payload) {
        Map<String, Object> safePayload = payload == null ? orderedMap() : mutableMap(payload);
        Map<String, Object> record = orderedMap();
        record.put("event_id", "lf_" + sha1(source + ":" + now() + ":" + toJson(safePayload), 16));
        record.put("event_type", "parkpulse.live_feed.signal");
        record.put("schema_version", "parkpulse.live_feed.v1");
        record.put("occurred_at", now());
        record.put("source", source);
        record.put("signal_type", string(safePayload.get("signal_type"), string(safePayload.get("type"), "operator_signal")));
        record.put("payload", safePayload);
        record.put("runtime", "java_spring");
        return record;
    }

    private void appendLiveFeedRecord(Map<String, Object> record) {
        appendRecord(liveFeedPath(), record, "Unable to append Spring live-feed event.");
    }

    private void appendReviewRecord(Map<String, Object> record) {
        appendRecord(reviewLedgerPath(), record, "Unable to append Spring review training decision.");
    }

    private void appendRecord(Path path, Map<String, Object> record, String errorMessage) {
        try {
            Files.createDirectories(path.getParent());
            Files.writeString(
                path,
                objectMapper.writeValueAsString(record) + "\n",
                StandardCharsets.UTF_8,
                Files.exists(path) ? java.nio.file.StandardOpenOption.APPEND : java.nio.file.StandardOpenOption.CREATE
            );
            incrementCachedLineCount(path);
            prependCachedRecentRow(path, record);
        } catch (Exception error) {
            throw new IllegalStateException(errorMessage, error);
        }
    }

    private List<Map<String, Object>> readRows(Path path) {
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
        return rows;
    }

    private List<Map<String, Object>> recentRows(Path path, int limit) {
        if (!Files.exists(path)) {
            return new ArrayList<>();
        }
        int cappedLimit = Math.max(1, Math.min(limit, 100));
        try {
            long size = Files.size(path);
            long modifiedAt = Files.getLastModifiedTime(path).toMillis();
            RecentRowsSnapshot cached = recentRowsCache.get(path);
            if (cached != null && cached.size() == size && cached.modifiedAt() == modifiedAt && cached.rows().size() >= cappedLimit) {
                return new ArrayList<>(cached.rows().subList(0, cappedLimit));
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
            String line = tail.removeLast();
            try {
                rows.add(objectMapper.readValue(line, MAP_TYPE));
            } catch (Exception ignored) {
                // Skip malformed historical rows without blocking hot health reads.
            }
        }
        cacheRecentRows(path, rows);
        return rows;
    }

    private Map<String, Object> ledgerStatus(String mode, Path path) {
        Map<String, Object> payload = orderedMap();
        payload.put("mode", mode);
        payload.put("path", path.toString());
        payload.put("count", lineCount(path));
        payload.put("ready", true);
        payload.put("runtime", "java_spring");
        return payload;
    }

    private long lineCount(Path path) {
        if (!Files.exists(path)) {
            return 0;
        }
        try {
            long size = Files.size(path);
            long modifiedAt = Files.getLastModifiedTime(path).toMillis();
            CountSnapshot cached = lineCountCache.get(path);
            if (cached != null && cached.size() == size && cached.modifiedAt() == modifiedAt) {
                return cached.count();
            }
            long count = slowLineCount(path);
            lineCountCache.put(path, new CountSnapshot(size, modifiedAt, count));
            return count;
        } catch (Exception ignored) {
            return 0;
        }
    }

    private long slowLineCount(Path path) {
        try (var lines = Files.lines(path, StandardCharsets.UTF_8)) {
            return lines.filter(line -> !line.isBlank()).count();
        } catch (Exception ignored) {
            return 0;
        }
    }

    private void incrementCachedLineCount(Path path) {
        try {
            CountSnapshot cached = lineCountCache.get(path);
            if (cached == null) {
                return;
            }
            lineCountCache.put(path, new CountSnapshot(
                Files.size(path),
                Files.getLastModifiedTime(path).toMillis(),
                cached.count() + 1
            ));
        } catch (Exception ignored) {
            lineCountCache.remove(path);
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
            recentRowsCache.put(path, new RecentRowsSnapshot(
                Files.size(path),
                Files.getLastModifiedTime(path).toMillis(),
                rows
            ));
        } catch (Exception ignored) {
            recentRowsCache.remove(path);
        }
    }

    private void cacheRecentRows(Path path, List<Map<String, Object>> rows) {
        try {
            recentRowsCache.put(path, new RecentRowsSnapshot(
                Files.size(path),
                Files.getLastModifiedTime(path).toMillis(),
                new ArrayList<>(rows)
            ));
        } catch (Exception ignored) {
            recentRowsCache.remove(path);
        }
    }

    private Path liveFeedPath() {
        String configured = env("PARKPULSE_LIVE_FEED_PATH", "");
        if (!configured.isBlank()) {
            return Path.of(configured);
        }
        return runtimeDir().resolve("live_feed_events.jsonl");
    }

    private Path reviewLedgerPath() {
        String configured = env("PARKPULSE_REVIEW_LEDGER_LOG_PATH", "");
        if (!configured.isBlank()) {
            return Path.of(configured);
        }
        return runtimeDir().resolve("review_ledger.jsonl");
    }

    private Path runtimeDir() {
        return Path.of(env("PARKPULSE_RUNTIME_DIR", "/tmp/parkpulse"));
    }

    private String env(String key, String defaultValue) {
        String value = environment.getProperty(key);
        return value == null || value.isBlank() ? defaultValue : value;
    }

    private String toJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception error) {
            return String.valueOf(value);
        }
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

    private static LinkedHashMap<String, Object> orderedMap() {
        return new LinkedHashMap<>();
    }

    private static String string(Object value, String defaultValue) {
        return value == null || String.valueOf(value).isBlank() ? defaultValue : String.valueOf(value);
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> mutableMap(Object value) {
        return value instanceof Map<?, ?> ? new LinkedHashMap<>((Map<String, Object>) value) : orderedMap();
    }

    private record CountSnapshot(long size, long modifiedAt, long count) {
    }

    private record RecentRowsSnapshot(long size, long modifiedAt, List<Map<String, Object>> rows) {
    }
}
