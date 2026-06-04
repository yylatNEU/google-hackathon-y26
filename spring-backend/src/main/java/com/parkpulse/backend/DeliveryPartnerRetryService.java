package com.parkpulse.backend;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Service;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

@Service
public class DeliveryPartnerRetryService {
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

    private final Environment environment;
    private final ObjectMapper objectMapper;
    private final DeliveryOutboxService deliveryOutboxService;
    private final HttpClient httpClient;

    public DeliveryPartnerRetryService(Environment environment, ObjectMapper objectMapper, DeliveryOutboxService deliveryOutboxService) {
        this.environment = environment;
        this.objectMapper = objectMapper;
        this.deliveryOutboxService = deliveryOutboxService;
        this.httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofMillis(intEnv("PARKPULSE_PARTNER_RECEIVER_TIMEOUT_MS", 5000)))
            .followRedirects(HttpClient.Redirect.NEVER)
            .build();
    }

    public Map<String, Object> status() {
        Map<String, Object> payload = orderedMap();
        payload.put("mode", "spring_partner_receiver_retry_worker");
        payload.put("runtime", "java_spring");
        payload.put("enabled", envBool("PARKPULSE_ENABLE_PARTNER_RECEIVER_RETRY"));
        payload.put("default_behavior", "dry_run_until_PARKPULSE_ENABLE_PARTNER_RECEIVER_RETRY_true");
        payload.put("max_attempts", maxAttempts());
        payload.put("timeout_ms", intEnv("PARKPULSE_PARTNER_RECEIVER_TIMEOUT_MS", 5000));
        payload.put("ledger", ledgerStatus());
        payload.put("receivers", Map.of(
            "guest_app", receiverUrl("guest_app", "/partner/guest-app/promotions"),
            "worker_device", receiverUrl("worker_device", "/partner/staff-dispatch/notifications"),
            "equipment_controller", receiverUrl("equipment_controller", "/partner/bms/commands")
        ));
        return payload;
    }

    public Map<String, Object> run(Map<String, Object> body) {
        Map<String, Object> request = body == null ? Map.of() : body;
        int limit = intValue(request.get("limit"), 20, 1, 100);
        String onlyDispatchId = string(request.get("dispatch_id"), request.get("dispatchId"));
        boolean dryRun = request.containsKey("dry_run")
            ? truthy(request.get("dry_run"))
            : request.containsKey("dryRun")
                ? truthy(request.get("dryRun"))
                : !envBool("PARKPULSE_ENABLE_PARTNER_RECEIVER_RETRY");
        String actor = stringOrDefault(request.get("actor"), "spring-partner-retry-worker");
        List<Map<String, Object>> attempts = new ArrayList<>();
        for (Map<String, Object> dispatch : deliveryOutboxService.dispatchesForRetry(limit)) {
            if (!onlyDispatchId.isBlank() && !onlyDispatchId.equals(string(dispatch.get("id")))) {
                continue;
            }
            Map<String, Object> attempt = attemptDispatch(dispatch, dryRun, actor);
            attempts.add(attempt);
            appendReceipt(attempt);
        }
        Map<String, Object> payload = orderedMap();
        payload.put("status", attempts.stream().anyMatch(row -> "retry_failed".equals(row.get("status"))) ? "completed_with_failures" : "completed");
        payload.put("dry_run", dryRun);
        payload.put("attempt_count", attempts.size());
        payload.put("attempts", attempts);
        payload.put("ledger", ledgerStatus());
        payload.put("runtime", "java_spring");
        return payload;
    }

    private Map<String, Object> attemptDispatch(Map<String, Object> dispatch, boolean dryRun, String actor) {
        String dispatchId = string(dispatch.get("id"));
        String channel = string(dispatch.get("channel"));
        String endpoint = string(dispatch.get("endpoint"));
        String targetUrl = receiverUrl(channel, endpoint);
        Map<String, Object> attempt = orderedMap();
        attempt.put("id", "partner_retry_" + dispatchId + "_" + Instant.now().toEpochMilli());
        attempt.put("dispatchId", dispatchId);
        attempt.put("channel", channel);
        attempt.put("targetSystem", dispatch.get("targetSystem"));
        attempt.put("endpoint", endpoint);
        attempt.put("targetUrl", targetUrl);
        attempt.put("actor", actor);
        attempt.put("attemptedAt", now());
        attempt.put("dry_run", dryRun);
        attempt.put("idempotencyKey", string(dispatch.get("idempotencyKey"), dispatchId));
        attempt.put("runtime", "java_spring");

        if (!eligibleStatus(string(dispatch.get("status")))) {
            attempt.put("status", "skipped");
            attempt.put("reason", "dispatch status is not eligible for partner retry");
            return attempt;
        }
        if (targetUrl.isBlank()) {
            attempt.put("status", "receiver_not_configured");
            attempt.put("reason", "No receiver URL is configured for channel " + channel);
            return attempt;
        }
        List<Map<String, Object>> receipts = receiptRows();
        if (hasSuccessfulPartnerDelivery(dispatchId, receipts)) {
            attempt.put("status", "skipped");
            attempt.put("reason", "Partner receiver already accepted this dispatch.");
            return attempt;
        }
        long priorAttempts = receipts.stream().filter(row -> dispatchId.equals(string(row.get("dispatchId"))) && liveAttempt(row)).count();
        attempt.put("attemptNumber", priorAttempts + 1);
        if (priorAttempts >= maxAttempts()) {
            attempt.put("status", "max_attempts_exceeded");
            attempt.put("reason", "Partner retry max attempts reached.");
            return attempt;
        }
        if (dryRun) {
            attempt.put("status", "dry_run");
            attempt.put("reason", "PARKPULSE_ENABLE_PARTNER_RECEIVER_RETRY is false or dry_run was requested.");
            return attempt;
        }
        try {
            HttpResponse<String> response = httpClient.send(partnerRequest(targetUrl, dispatch, priorAttempts + 1), HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            attempt.put("http_status", response.statusCode());
            attempt.put("response_body", truncate(response.body(), 500));
            if (response.statusCode() >= 200 && response.statusCode() < 300) {
                attempt.put("status", "delivered_to_partner");
                attempt.put("reason", "Partner receiver accepted retry.");
            } else {
                attempt.put("status", "retry_failed");
                attempt.put("reason", "Partner receiver returned non-2xx status.");
            }
        } catch (Exception error) {
            attempt.put("status", "retry_failed");
            attempt.put("reason", truncate(error.getMessage(), 500));
        }
        return attempt;
    }

    private HttpRequest partnerRequest(String targetUrl, Map<String, Object> dispatch, long attemptNumber) throws Exception {
        Map<String, Object> payload = orderedMap();
        payload.put("dispatchId", dispatch.get("id"));
        payload.put("channel", dispatch.get("channel"));
        payload.put("targetSystem", dispatch.get("targetSystem"));
        payload.put("status", dispatch.get("status"));
        payload.put("payload", dispatch.get("payload"));
        payload.put("response", dispatch.get("response"));
        payload.put("agentBoundary", dispatch.get("agentBoundary"));
        payload.put("retryAttempt", attemptNumber);
        return HttpRequest.newBuilder(URI.create(targetUrl))
            .timeout(Duration.ofMillis(intEnv("PARKPULSE_PARTNER_RECEIVER_TIMEOUT_MS", 5000)))
            .header("content-type", "application/json")
            .header("x-parkpulse-dispatch-id", string(dispatch.get("id")))
            .header("idempotency-key", string(dispatch.get("idempotencyKey"), dispatch.get("id")))
            .header("x-parkpulse-retry-attempt", String.valueOf(attemptNumber))
            .POST(HttpRequest.BodyPublishers.ofString(toJson(payload), StandardCharsets.UTF_8))
            .build();
    }

    private String receiverUrl(String channel, String endpoint) {
        String explicit = switch (channel) {
            case "guest_app" -> env("PARKPULSE_GUEST_APP_RECEIVER_URL", "");
            case "worker_device" -> env("PARKPULSE_WORKER_DEVICE_RECEIVER_URL", "");
            case "equipment_controller" -> env("PARKPULSE_EQUIPMENT_CONTROLLER_RECEIVER_URL", "");
            default -> "";
        };
        if (!explicit.isBlank()) {
            return explicit;
        }
        String base = env("PARKPULSE_PARTNER_RECEIVER_BASE_URL", "");
        if (base.isBlank() || endpoint == null || endpoint.isBlank()) {
            return "";
        }
        return stripTrailingSlash(base) + (endpoint.startsWith("/") ? endpoint : "/" + endpoint);
    }

    private boolean eligibleStatus(String status) {
        return List.of("delivered", "approved_for_execution").contains(status);
    }

    private boolean liveAttempt(Map<String, Object> row) {
        return !truthy(row.get("dry_run")) && !"receiver_not_configured".equals(row.get("status")) && !"skipped".equals(row.get("status"));
    }

    private boolean hasSuccessfulPartnerDelivery(String dispatchId, List<Map<String, Object>> receipts) {
        return receipts.stream().anyMatch(row -> dispatchId.equals(string(row.get("dispatchId"))) && "delivered_to_partner".equals(row.get("status")));
    }

    private void appendReceipt(Map<String, Object> receipt) {
        try {
            Path path = ledgerPath();
            Files.createDirectories(path.getParent());
            Files.writeString(path, toJson(receipt) + "\n", StandardCharsets.UTF_8, Files.exists(path) ? java.nio.file.StandardOpenOption.APPEND : java.nio.file.StandardOpenOption.CREATE);
        } catch (Exception ignored) {
            // Retry delivery should not mask the dispatch result; ledger health is visible via status().
        }
    }

    private List<Map<String, Object>> receiptRows() {
        Path path = ledgerPath();
        if (!Files.exists(path)) {
            return List.of();
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
        payload.put("mode", "partner_retry_jsonl_ledger");
        payload.put("path", ledgerPath().toString());
        payload.put("count", receiptRows().size());
        payload.put("ready", true);
        return payload;
    }

    private Path ledgerPath() {
        String configured = env("PARKPULSE_PARTNER_RETRY_LEDGER", "");
        if (!configured.isBlank()) {
            return Path.of(configured);
        }
        return Path.of(env("PARKPULSE_RUNTIME_DIR", "/tmp/parkpulse")).resolve("partner_retry_receipts.jsonl");
    }

    private int maxAttempts() {
        return intEnv("PARKPULSE_PARTNER_RECEIVER_MAX_ATTEMPTS", 3);
    }

    private int intEnv(String name, int fallback) {
        return intValue(env(name, String.valueOf(fallback)), fallback, 1, 1000);
    }

    private int intValue(Object value, int fallback, int min, int max) {
        try {
            return Math.max(min, Math.min(max, Integer.parseInt(String.valueOf(value))));
        } catch (Exception ignored) {
            return fallback;
        }
    }

    private boolean envBool(String name) {
        String raw = env(name, "").toLowerCase(Locale.ROOT);
        return List.of("1", "true", "yes", "on").contains(raw);
    }

    private String env(String name, String fallback) {
        String value = environment.getProperty(name);
        return value == null || value.isBlank() ? fallback : value.trim();
    }

    private String toJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception error) {
            return String.valueOf(value);
        }
    }

    private static boolean truthy(Object value) {
        if (value instanceof Boolean bool) {
            return bool;
        }
        String raw = String.valueOf(value == null ? "" : value).toLowerCase(Locale.ROOT);
        return List.of("1", "true", "yes", "on").contains(raw);
    }

    private static String string(Object... values) {
        for (Object value : values) {
            if (value != null && !String.valueOf(value).isBlank()) {
                return String.valueOf(value);
            }
        }
        return "";
    }

    private static String stringOrDefault(Object value, String fallback) {
        return value == null || String.valueOf(value).isBlank() ? fallback : String.valueOf(value);
    }

    private static String stripTrailingSlash(String value) {
        String raw = value == null ? "" : value.trim();
        while (raw.endsWith("/")) {
            raw = raw.substring(0, raw.length() - 1);
        }
        return raw;
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
