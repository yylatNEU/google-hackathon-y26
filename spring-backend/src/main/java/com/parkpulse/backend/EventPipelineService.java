package com.parkpulse.backend;

import com.google.auth.oauth2.AccessToken;
import com.google.auth.oauth2.GoogleCredentials;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Collections;
import java.util.HexFormat;
import java.util.IdentityHashMap;
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
public class EventPipelineService {
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};
    private static final List<String> CLOUD_PLATFORM_SCOPE = List.of("https://www.googleapis.com/auth/cloud-platform");

    private final Environment environment;
    private final ObjectMapper objectMapper;
    private final HttpClient httpClient;

    public EventPipelineService(Environment environment, ObjectMapper objectMapper) {
        this.environment = environment;
        this.objectMapper = objectMapper;
        this.httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofMillis(intEnv("PARKPULSE_BIGQUERY_HTTP_TIMEOUT_MS", 8000)))
            .followRedirects(HttpClient.Redirect.NEVER)
            .build();
    }

    public Map<String, Object> contract() {
        Map<String, Object> payload = orderedMap();
        payload.put("name", "ParkPulse Canonical Event Pipeline");
        payload.put("runtime", "java_spring");
        payload.put("schema_version", "parkpulse.event.v1");
        payload.put("required_fields", List.of("event_id", "event_type", "occurred_at", "source", "subject", "payload", "trace", "policy", "dataflow"));
        payload.put("event_types", List.of(
            "parkpulse.delivery.dispatch",
            "parkpulse.delivery.acknowledgement",
            "parkpulse.delivery.approval_decision",
            "parkpulse.delivery.partner_retry",
            "parkpulse.receiver.guest_response",
            "parkpulse.receiver.worker_acknowledgement",
            "parkpulse.receiver.equipment_result",
            "parkpulse.gcp.eventarc.signal"
        ));
        payload.put("sinks", List.of("durable_jsonl_event_ledger", "Pub/Sub/Dataflow adapter mirror", "future BigQuery analytics sink"));
        payload.put("ledger", ledgerStatus());
        return payload;
    }

    public Map<String, Object> status() {
        Map<String, Object> payload = orderedMap();
        payload.put("mode", "spring_canonical_event_pipeline");
        payload.put("runtime", "java_spring");
        payload.put("schema_version", "parkpulse.event.v1");
        payload.put("ledger", ledgerStatus());
        payload.put("receiver_auth", receiverAuthStatus());
        payload.put("bigquery_sink", bigQuerySinkStatus());
        return payload;
    }

    public Map<String, Object> recent(int limit, String eventType) {
        List<Map<String, Object>> rows = ledgerRows();
        Collections.reverse(rows);
        List<Map<String, Object>> filtered = rows.stream()
            .filter(row -> eventType == null || eventType.isBlank() || eventType.equals(row.get("event_type")))
            .limit(Math.max(1, Math.min(limit, 100)))
            .toList();
        Map<String, Object> payload = orderedMap();
        payload.put("count", filtered.size());
        payload.put("events", filtered);
        payload.put("ledger", ledgerStatus());
        payload.put("runtime", "java_spring");
        return payload;
    }

    public Map<String, Object> recordDeliveryDispatch(Map<String, Object> dispatch) {
        return record("parkpulse.delivery.dispatch", "spring.delivery", subjectFor(dispatch), string(dispatch.get("channel")), snapshot(dispatch), deliveryPolicy(dispatch), dispatchTrace(dispatch));
    }

    public Map<String, Object> recordAcknowledgement(Map<String, Object> dispatch, Map<String, Object> acknowledgement) {
        Map<String, Object> payload = orderedMap();
        payload.put("dispatch", snapshot(dispatch));
        payload.put("acknowledgement", snapshot(acknowledgement));
        return record("parkpulse.delivery.acknowledgement", "spring.delivery", subjectFor(dispatch), string(dispatch.get("channel")), payload, deliveryPolicy(dispatch), dispatchTrace(dispatch));
    }

    public Map<String, Object> recordApprovalDecision(Map<String, Object> dispatch, Map<String, Object> approval) {
        Map<String, Object> payload = orderedMap();
        payload.put("dispatch", snapshot(dispatch));
        payload.put("approval", snapshot(approval));
        return record("parkpulse.delivery.approval_decision", "spring.delivery", subjectFor(dispatch), string(dispatch.get("channel")), payload, deliveryPolicy(dispatch), dispatchTrace(dispatch));
    }

    public Map<String, Object> recordPartnerRetry(Map<String, Object> attempt) {
        return record("parkpulse.delivery.partner_retry", "spring.partner_retry", string(attempt.get("dispatchId")), string(attempt.get("channel")), snapshot(attempt), Map.of("retry_status", string(attempt.get("status"))), Map.of("idempotency_key", string(attempt.get("idempotencyKey"))));
    }

    public Map<String, Object> recordReceiverEvent(String eventType, Map<String, Object> body) {
        Map<String, Object> payload = body == null ? orderedMap() : mutableMap(body);
        String dispatchId = firstString(payload.get("dispatch_id"), payload.get("dispatchId"), payload.get("id"), "receiver_event");
        String channel = firstString(payload.get("channel"), channelFromEventType(eventType));
        return record(eventType, "receiver.callback", dispatchId, channel, payload, Map.of("receiver_callback", true), Map.of("receiver", firstString(payload.get("receiver"), payload.get("targetSystem"), channel)));
    }

    public Map<String, Object> recordEventarcSignal(Map<String, Object> body) {
        Map<String, Object> decoded = decodeEventarcSignal(body == null ? Map.of() : body);
        return record("parkpulse.gcp.eventarc.signal", "gcp.eventarc", firstString(decoded.get("messageId"), decoded.get("eventId"), "eventarc_signal"), firstString(decoded.get("channel"), decoded.get("source"), "gcp"), decoded, Map.of("external_event", true), Map.of("source", decoded.getOrDefault("source", "gcp_pubsub")));
    }

    private Map<String, Object> record(String eventType, String source, String subject, String channel, Map<String, Object> payload, Map<String, Object> policy, Map<String, Object> trace) {
        Map<String, Object> safePayload = safePayload(payload);
        Map<String, Object> envelope = orderedMap();
        envelope.put("event_id", eventId(eventType, subject, safePayload));
        envelope.put("event_type", eventType);
        envelope.put("schema_version", "parkpulse.event.v1");
        envelope.put("occurred_at", now());
        envelope.put("source", source);
        envelope.put("subject", subject);
        envelope.put("channel", channel);
        envelope.put("payload", safePayload);
        envelope.put("policy", policy == null ? Map.of() : policy);
        envelope.put("trace", trace == null ? Map.of() : trace);
        envelope.put("dataflow", Map.of("sink", "jsonl_first", "event_time_field", "occurred_at", "bigquery_ready", envBool("ENABLE_PARKPULSE_BIGQUERY_EVENT_EXPORT")));
        appendEnvelope(envelope);
        Map<String, Object> bigQuery = exportToBigQuery(envelope);
        Map<String, Object> result = orderedMap();
        result.put("status", "recorded");
        result.put("event", envelope);
        result.put("bigquery", bigQuery);
        result.put("ledger", ledgerStatus());
        result.put("runtime", "java_spring");
        return result;
    }

    private Map<String, Object> exportToBigQuery(Map<String, Object> envelope) {
        if (!envBool("ENABLE_PARKPULSE_BIGQUERY_EVENT_EXPORT")) {
            return Map.of("status", "skipped", "reason", "ENABLE_PARKPULSE_BIGQUERY_EVENT_EXPORT is false");
        }
        Map<String, String> table = bigQueryTable();
        if (table.get("project").isBlank() || table.get("dataset").isBlank() || table.get("table").isBlank()) {
            return Map.of("status", "configured_incomplete", "reason", "BigQuery project, dataset, or table is missing", "table", table);
        }
        try {
            Map<String, Object> row = orderedMap();
            row.put("insertId", string(envelope.get("event_id")));
            row.put("json", bigQueryEventRow(envelope));
            Map<String, Object> body = orderedMap();
            body.put("kind", "bigquery#tableDataInsertAllRequest");
            body.put("skipInvalidRows", false);
            body.put("ignoreUnknownValues", true);
            body.put("rows", List.of(row));
            HttpResponse<String> response = postJson(bigQueryInsertAllUrl(table), body);
            if (response.statusCode() < 200 || response.statusCode() >= 300) {
                return Map.of("status", "failed", "provider", "bigquery_insert_all", "http_status", response.statusCode(), "reason", truncate(response.body(), 500), "table", table);
            }
            Map<String, Object> parsed = parseMap(response.body());
            if (parsed.get("insertErrors") instanceof List<?> errors && !errors.isEmpty()) {
                return Map.of("status", "failed", "provider", "bigquery_insert_all", "reason", "BigQuery insertErrors returned", "insertErrors", errors, "table", table);
            }
            return Map.of("status", "inserted", "provider", "bigquery_insert_all", "table", table, "insertId", envelope.get("event_id"));
        } catch (Exception error) {
            return Map.of("status", "failed", "provider", "bigquery_insert_all", "reason", truncate(error.getMessage(), 500), "table", table);
        }
    }

    private Map<String, Object> bigQueryEventRow(Map<String, Object> envelope) {
        Map<String, Object> row = orderedMap();
        row.put("event_id", envelope.get("event_id"));
        row.put("event_type", envelope.get("event_type"));
        row.put("schema_version", envelope.get("schema_version"));
        row.put("occurred_at", envelope.get("occurred_at"));
        row.put("source", envelope.get("source"));
        row.put("subject", envelope.get("subject"));
        row.put("channel", envelope.get("channel"));
        row.put("payload_json", truncate(toJson(envelope.get("payload")), 100_000));
        row.put("policy_json", truncate(toJson(envelope.get("policy")), 32_000));
        row.put("trace_json", truncate(toJson(envelope.get("trace")), 32_000));
        row.put("dataflow_json", truncate(toJson(envelope.get("dataflow")), 32_000));
        return row;
    }

    private Map<String, Object> decodeEventarcSignal(Map<String, Object> body) {
        Map<String, Object> result = orderedMap();
        Object messageObject = body.get("message");
        if (messageObject instanceof Map<?, ?> message) {
            Map<String, Object> attributes = mutableMap(message.get("attributes"));
            result.putAll(attributes);
            result.put("messageId", message.get("messageId"));
            Object data = message.get("data");
            if (data != null && !String.valueOf(data).isBlank()) {
                try {
                    String decoded = new String(Base64.getDecoder().decode(String.valueOf(data)), StandardCharsets.UTF_8);
                    Object parsed = objectMapper.readValue(decoded, Object.class);
                    result.put("event", parsed);
                    if (parsed instanceof Map<?, ?> parsedMap) {
                        mutableMap(parsedMap).forEach(result::putIfAbsent);
                    }
                } catch (Exception error) {
                    result.put("decode_error", truncate(error.getMessage(), 300));
                    result.put("raw_data", String.valueOf(data));
                }
            }
        } else {
            result.putAll(body);
        }
        result.putIfAbsent("source", firstString(result.get("source"), "gcp_pubsub"));
        return result;
    }

    private void appendEnvelope(Map<String, Object> envelope) {
        try {
            Path path = ledgerPath();
            Files.createDirectories(path.getParent());
            Files.writeString(path, toJson(envelope) + "\n", StandardCharsets.UTF_8, Files.exists(path) ? java.nio.file.StandardOpenOption.APPEND : java.nio.file.StandardOpenOption.CREATE);
        } catch (Exception error) {
            throw new IllegalStateException("Unable to append canonical event envelope.", error);
        }
    }

    private List<Map<String, Object>> ledgerRows() {
        Path path = ledgerPath();
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

    private Map<String, Object> ledgerStatus() {
        Map<String, Object> payload = orderedMap();
        payload.put("mode", "canonical_event_jsonl_ledger");
        payload.put("path", ledgerPath().toString());
        payload.put("count", ledgerRows().size());
        payload.put("ready", true);
        return payload;
    }

    private Map<String, Object> receiverAuthStatus() {
        boolean tokenConfigured = !env("PARKPULSE_RECEIVER_EVENT_TOKEN", "").isBlank();
        return Map.of(
            "token_configured", tokenConfigured,
            "production_requires_token", isProductionEnvironment(),
            "mode", tokenConfigured ? "shared_receiver_token" : isProductionEnvironment() ? "blocked_until_token_configured" : "local_dev_open"
        );
    }

    private Map<String, Object> bigQuerySinkStatus() {
        Map<String, String> table = bigQueryTable();
        Map<String, Object> payload = orderedMap();
        payload.put("enabled", envBool("ENABLE_PARKPULSE_BIGQUERY_EVENT_EXPORT"));
        payload.put("table", table);
        payload.put("ready", envBool("ENABLE_PARKPULSE_BIGQUERY_EVENT_EXPORT") && !table.get("project").isBlank() && !table.get("dataset").isBlank() && !table.get("table").isBlank());
        payload.put("mode", envBool("ENABLE_PARKPULSE_BIGQUERY_EVENT_EXPORT") ? "live_insert_all_enabled" : "disabled");
        payload.put("hot_path", false);
        return payload;
    }

    public boolean receiverAuthorized(String token) {
        String configured = env("PARKPULSE_RECEIVER_EVENT_TOKEN", "");
        if (!configured.isBlank()) {
            return configured.equals(token);
        }
        return !isProductionEnvironment();
    }

    private Map<String, Object> deliveryPolicy(Map<String, Object> dispatch) {
        Map<String, Object> boundary = mutableMap(dispatch.get("agentBoundary"));
        Map<String, Object> policy = orderedMap();
        policy.put("agent_boundary_allowed", boundary.get("allowed"));
        policy.put("policy_gate_checked", boundary.get("policy_gate_checked"));
        policy.put("dispatch_status", dispatch.get("status"));
        return policy;
    }

    private Map<String, Object> dispatchTrace(Map<String, Object> dispatch) {
        return Map.of(
            "dispatch_id", string(dispatch.get("id")),
            "idempotency_key", string(dispatch.get("idempotencyKey")),
            "target_system", string(dispatch.get("targetSystem"))
        );
    }

    private String subjectFor(Map<String, Object> dispatch) {
        return firstString(dispatch.get("id"), dispatch.get("dispatchId"), "delivery_dispatch");
    }

    private String channelFromEventType(String eventType) {
        if (eventType.contains("guest")) {
            return "guest_app";
        }
        if (eventType.contains("worker")) {
            return "worker_device";
        }
        if (eventType.contains("equipment")) {
            return "equipment_controller";
        }
        return "receiver";
    }

    private String eventId(String eventType, String subject, Map<String, Object> payload) {
        return "evt_" + sha1(eventType + ":" + subject + ":" + now() + ":" + toJson(payload), 16);
    }

    private Path ledgerPath() {
        String configured = env("PARKPULSE_EVENT_LEDGER", "");
        if (!configured.isBlank()) {
            return Path.of(configured);
        }
        return Path.of(env("PARKPULSE_RUNTIME_DIR", "/tmp/parkpulse")).resolve("canonical_events.jsonl");
    }

    private Map<String, String> bigQueryTable() {
        String configured = env("PARKPULSE_BIGQUERY_EVENT_TABLE", "");
        String project = projectId();
        String dataset = env("PARKPULSE_BIGQUERY_EVENT_DATASET", "");
        String table = env("PARKPULSE_BIGQUERY_EVENT_TABLE_NAME", "");
        if (!configured.isBlank()) {
            String[] parts = configured.split("\\.");
            if (parts.length == 3) {
                project = parts[0];
                dataset = parts[1];
                table = parts[2];
            } else if (parts.length == 2) {
                dataset = parts[0];
                table = parts[1];
            }
        }
        Map<String, String> result = new LinkedHashMap<>();
        result.put("project", project);
        result.put("dataset", dataset);
        result.put("table", table);
        return result;
    }

    private String bigQueryInsertAllUrl(Map<String, String> table) {
        return stripTrailingSlash(env("PARKPULSE_BIGQUERY_API_BASE_URL", "https://bigquery.googleapis.com/bigquery/v2"))
            + "/projects/" + table.get("project")
            + "/datasets/" + table.get("dataset")
            + "/tables/" + table.get("table")
            + "/insertAll";
    }

    private HttpResponse<String> postJson(String url, Object payload) throws Exception {
        HttpRequest request = HttpRequest.newBuilder(URI.create(url))
            .timeout(Duration.ofMillis(intEnv("PARKPULSE_BIGQUERY_HTTP_TIMEOUT_MS", 8000)))
            .header("authorization", "Bearer " + accessToken())
            .header("content-type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(toJson(payload), StandardCharsets.UTF_8))
            .build();
        return httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
    }

    private String accessToken() throws Exception {
        String explicit = env("PARKPULSE_GCP_ACCESS_TOKEN", "");
        if (!explicit.isBlank()) {
            return explicit;
        }
        GoogleCredentials credentials = GoogleCredentials.getApplicationDefault().createScoped(CLOUD_PLATFORM_SCOPE);
        credentials.refreshIfExpired();
        AccessToken token = credentials.getAccessToken();
        if (token == null || token.getTokenValue() == null || token.getTokenValue().isBlank()) {
            credentials.refresh();
            token = credentials.getAccessToken();
        }
        return token == null ? "" : token.getTokenValue();
    }

    private Map<String, Object> parseMap(String raw) {
        if (raw == null || raw.isBlank()) {
            return orderedMap();
        }
        try {
            Object parsed = objectMapper.readValue(raw, Object.class);
            return mutableMap(parsed);
        } catch (Exception ignored) {
            return orderedMap();
        }
    }

    private String env(String name, String fallback) {
        String value = environment.getProperty(name);
        return value == null || value.isBlank() ? fallback : value.trim();
    }

    private boolean envBool(String name) {
        String raw = env(name, "").toLowerCase(Locale.ROOT);
        return List.of("1", "true", "yes", "on").contains(raw);
    }

    private int intEnv(String name, int fallback) {
        try {
            return Integer.parseInt(env(name, String.valueOf(fallback)));
        } catch (NumberFormatException ignored) {
            return fallback;
        }
    }

    private String projectId() {
        return firstString(environment.getProperty("GOOGLE_CLOUD_PROJECT"), environment.getProperty("GCP_PROJECT"), environment.getProperty("GCLOUD_PROJECT"));
    }

    private String stripTrailingSlash(String value) {
        String raw = value == null ? "" : value.trim();
        while (raw.endsWith("/")) {
            raw = raw.substring(0, raw.length() - 1);
        }
        return raw;
    }

    private boolean isProductionEnvironment() {
        String env = firstString(environment.getProperty("PARKPULSE_ENV"), environment.getProperty("ENVIRONMENT")).toLowerCase(Locale.ROOT);
        return List.of("prod", "production").contains(env);
    }

    private Map<String, Object> mutableMap(Object value) {
        Map<String, Object> result = orderedMap();
        if (value instanceof Map<?, ?> source) {
            source.forEach((key, item) -> result.put(String.valueOf(key), item));
        }
        return result;
    }

    private Map<String, Object> snapshot(Object value) {
        try {
            Map<String, Object> result = mutableMap(objectMapper.readValue(toJson(value), Object.class));
            result.remove("eventPipeline");
            return result;
        } catch (Exception ignored) {
            Map<String, Object> result = orderedMap();
            result.put("value", String.valueOf(value));
            return result;
        }
    }

    private Map<String, Object> safePayload(Map<String, Object> payload) {
        Object cleaned = cleanEventValue(payload == null ? Map.of() : payload, Collections.newSetFromMap(new IdentityHashMap<>()), 0);
        return cleaned instanceof Map<?, ?> map ? mutableMap(map) : orderedMap();
    }

    private Object cleanEventValue(Object value, Set<Object> seen, int depth) {
        if (value == null || value instanceof String || value instanceof Number || value instanceof Boolean) {
            return value;
        }
        if (depth >= 16) {
            return String.valueOf(value);
        }
        if (value instanceof Map<?, ?> source) {
            if (!seen.add(source)) {
                return "[circular]";
            }
            Map<String, Object> result = orderedMap();
            source.forEach((key, item) -> {
                String name = String.valueOf(key);
                if (!"eventPipeline".equals(name)) {
                    result.put(name, cleanEventValue(item, seen, depth + 1));
                }
            });
            seen.remove(source);
            return result;
        }
        if (value instanceof List<?> source) {
            if (!seen.add(source)) {
                return List.of("[circular]");
            }
            List<Object> result = source.stream()
                .map(item -> cleanEventValue(item, seen, depth + 1))
                .toList();
            seen.remove(source);
            return result;
        }
        return String.valueOf(value);
    }

    private String toJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception error) {
            return String.valueOf(value);
        }
    }

    private String sha1(String value, int chars) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-1").digest(value.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(digest).substring(0, chars);
        } catch (Exception error) {
            throw new IllegalStateException("Unable to hash event payload.", error);
        }
    }

    private static String firstString(Object... values) {
        for (Object value : values) {
            if (value != null && !String.valueOf(value).isBlank()) {
                return String.valueOf(value);
            }
        }
        return "";
    }

    private static String string(Object value) {
        return value == null ? "" : String.valueOf(value);
    }

    private static String truncate(String value, int maxChars) {
        String raw = value == null ? "" : value;
        return raw.length() <= maxChars ? raw : raw.substring(0, maxChars);
    }

    private static String now() {
        return Instant.now().toString();
    }

    private static LinkedHashMap<String, Object> orderedMap() {
        return new LinkedHashMap<>();
    }
}
