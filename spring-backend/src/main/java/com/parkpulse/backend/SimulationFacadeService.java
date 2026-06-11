package com.parkpulse.backend;

import jakarta.servlet.http.HttpServletRequest;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.Connection;
import java.sql.SQLException;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import javax.sql.DataSource;
import org.springframework.core.env.Environment;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

@Service
public class SimulationFacadeService {
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};
    private static final Set<String> MUTATING_PATHS = Set.of(
        "/api/park/tick",
        "/api/park/time",
        "/api/park/causal-impact-demo",
        "/api/park/digital-twin-war-room",
        "/api/park/digital-twin-war-room/run",
        "/api/park/digital-twin-war-room/remediate"
    );

    private final DataSource dataSource;
    private final Environment environment;
    private final ObjectMapper objectMapper;
    private final HttpClient httpClient;
    private final String pythonBackendUrl;
    private final int timeoutMs;
    private final int maxRequestBodyBytes;

    public SimulationFacadeService(DataSource dataSource, Environment environment, ObjectMapper objectMapper) {
        this.dataSource = dataSource;
        this.environment = environment;
        this.objectMapper = objectMapper;
        this.timeoutMs = intProperty("PARKPULSE_SIMULATION_ADAPTER_TIMEOUT_MS", "parkpulse.simulation-adapter-timeout-ms", 5000, 750, 60000);
        this.maxRequestBodyBytes = intProperty("PARKPULSE_SIMULATION_MAX_BODY_BYTES", "parkpulse.simulation-max-body-bytes", 1048576, 1024, 4194304);
        this.pythonBackendUrl = resolvePythonBackendUrl();
        this.httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofMillis(timeoutMs))
            .followRedirects(HttpClient.Redirect.NEVER)
            .build();
    }

    public Map<String, Object> tick(HttpServletRequest request, Map<String, Object> body, Map<String, Object> identity) {
        Map<String, Object> safeBody = body == null ? orderedMap() : mutableMap(body);
        int minutes = boundedInt(safeBody.get("minutes"), 1, 1, 30);
        safeBody.put("minutes", minutes);
        return delegate(request, "POST", "/api/park/tick", null, safeBody, identity, "simulation_tick", true);
    }

    public Map<String, Object> setTime(HttpServletRequest request, Map<String, Object> body, Map<String, Object> identity) {
        Map<String, Object> safeBody = body == null ? orderedMap() : mutableMap(body);
        safeBody.put("hour", boundedInt(safeBody.get("hour"), 9, 0, 23));
        safeBody.put("minute", boundedInt(safeBody.get("minute"), 0, 0, 59));
        return delegate(request, "POST", "/api/park/time", null, safeBody, identity, "simulation_time_control", true);
    }

    public Map<String, Object> causalImpactDemo(HttpServletRequest request, Map<String, Object> body, Map<String, Object> identity) {
        Map<String, Object> safeBody = body == null ? orderedMap() : mutableMap(body);
        safeBody.put("horizon_minutes", boundedInt(firstPresent(safeBody.get("horizon_minutes"), safeBody.get("horizonMinutes")), 20, 1, 120));
        return delegate(request, "POST", "/api/park/causal-impact-demo", null, safeBody, identity, "simulation_causal_impact_demo", true);
    }

    public Map<String, Object> episodeFitness(HttpServletRequest request, Integer limit, Map<String, Object> identity) {
        String query = "limit=" + boundedInt(limit, 20, 1, 200);
        return delegate(request, "GET", "/api/park/episode-fitness", query, null, identity, "simulation_episode_fitness", false);
    }

    public Map<String, Object> warRoom(HttpServletRequest request, String path, Map<String, Object> body, Map<String, Object> identity) {
        String method = request.getMethod() == null ? "GET" : request.getMethod().toUpperCase(Locale.ROOT);
        Map<String, Object> safeBody = body == null ? orderedMap() : mutableMap(body);
        boolean mutates = "POST".equals(method) && MUTATING_PATHS.contains(path);
        return delegate(request, method, path, request.getQueryString(), "POST".equals(method) ? safeBody : null, identity, "digital_twin_war_room", mutates);
    }

    public Map<String, Object> ledger(int limit) {
        initLedger();
        List<Map<String, Object>> rows = new ArrayList<>();
        try (Connection connection = dataSource.getConnection();
             var statement = connection.prepareStatement(
                 """
                 SELECT receipt_id, created_at, operation, method, route, actor_role, actor_subject, upstream_status,
                        response_status, mutates_state, idempotency_key, response_summary_json, request_json
                 FROM simulation_facade_receipts
                 ORDER BY created_at DESC
                 LIMIT ?
                 """
             )) {
            statement.setInt(1, Math.max(1, Math.min(limit, 500)));
            try (var result = statement.executeQuery()) {
                while (result.next()) {
                    Map<String, Object> row = orderedMap();
                    row.put("receipt_id", result.getString("receipt_id"));
                    row.put("created_at", result.getString("created_at"));
                    row.put("operation", result.getString("operation"));
                    row.put("method", result.getString("method"));
                    row.put("route", result.getString("route"));
                    row.put("actor_role", result.getString("actor_role"));
                    row.put("actor_subject", result.getString("actor_subject"));
                    row.put("upstream_status", result.getInt("upstream_status"));
                    row.put("response_status", result.getString("response_status"));
                    row.put("mutates_state", result.getInt("mutates_state") == 1);
                    row.put("idempotency_key", result.getString("idempotency_key"));
                    row.put("response_summary", readJson(result.getString("response_summary_json")));
                    row.put("request", readJson(result.getString("request_json")));
                    rows.add(row);
                }
            }
        } catch (SQLException error) {
            throw new IllegalStateException("Unable to read simulation facade ledger.", error);
        }

        Map<String, Object> payload = orderedMap();
        payload.put("status", rows.isEmpty() ? "empty" : "ready");
        payload.put("mode", "simulation_facade_ledger_spring");
        payload.put("runtime", "java_spring");
        payload.put("source_of_truth", "local_sqlite_wal");
        payload.put("summary", Map.of(
            "receipt_count", rows.size(),
            "mutating_receipt_count", rows.stream().filter(row -> Boolean.TRUE.equals(row.get("mutates_state"))).count()
        ));
        payload.put("receipts", rows);
        payload.put("boundary", "Spring owns simulation authority receipts; Python remains the compute adapter for simulation physics.");
        return payload;
    }

    public Map<String, Object> health() {
        Map<String, Object> ledgerHealth = ledgerHealth();
        Map<String, Object> adapterHealth = adapterHealth();
        boolean ledgerReady = Boolean.TRUE.equals(ledgerHealth.get("writable"));
        boolean adapterReady = Boolean.TRUE.equals(adapterHealth.get("reachable"));
        int pendingReceipts = boundedInt(ledgerHealth.get("pending_receipt_count"), 0, 0, Integer.MAX_VALUE);

        Map<String, Object> payload = orderedMap();
        payload.put("status", ledgerReady && adapterReady && pendingReceipts == 0 ? "ready" : "degraded");
        payload.put("mode", "simulation_authority_health_spring");
        payload.put("runtime", "java_spring");
        payload.put("authority", "spring_control_plane_python_compute_adapter");
        payload.put("adapter", adapterHealth);
        payload.put("ledger", ledgerHealth);
        payload.put("gates", Map.of(
            "spring_role_auth_required", true,
            "direct_python_simulation_routes_gated", true,
            "idempotency_supported", true,
            "preflight_receipts_required_for_mutations", true
        ));
        payload.put("readiness_issues", readinessIssues(adapterReady, ledgerReady, pendingReceipts));
        return payload;
    }

    private Map<String, Object> delegate(
        HttpServletRequest inbound,
        String method,
        String path,
        String query,
        Map<String, Object> body,
        Map<String, Object> identity,
        String operation,
        boolean mutatesState
    ) {
        byte[] requestBytes = body == null ? new byte[0] : jsonBytes(body);
        if (requestBytes.length > maxRequestBodyBytes) {
            throw new ResponseStatusException(HttpStatus.PAYLOAD_TOO_LARGE, "Simulation request body exceeds Spring facade limit.");
        }

        URI target = targetUri(path, query);
        int upstreamStatus = 0;
        String receiptId = "";
        boolean receiptFinalized = false;
        String idempotencyKey = mutatesState ? idempotencyKey(inbound, body) : "";
        if (mutatesState && hasText(idempotencyKey)) {
            Map<String, Object> replayed = replayIdempotentReceipt(method, path, identity, idempotencyKey);
            if (!replayed.isEmpty()) {
                return replayed;
            }
        }
        if (mutatesState) {
            receiptId = recordReceipt(
                operation,
                method,
                path,
                identity,
                0,
                "pending_adapter_call",
                true,
                idempotencyKey,
                body,
                Map.of("status", "pending_adapter_call")
            );
        }
        Map<String, Object> payload;
        try {
            HttpRequest outbound = buildRequest(inbound, method, target, requestBytes, identity);
            HttpResponse<byte[]> response = httpClient.send(outbound, HttpResponse.BodyHandlers.ofByteArray());
            upstreamStatus = response.statusCode();
            payload = parsePayload(response.body());
            if (upstreamStatus < 200 || upstreamStatus >= 300) {
                if (mutatesState) {
                    receiptFinalized = completeReceipt(receiptId, upstreamStatus, "upstream_error", payload);
                } else {
                    receiptId = recordReceipt(operation, method, path, identity, upstreamStatus, "upstream_error", false, "", body, payload);
                    receiptFinalized = true;
                }
                throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Python simulation adapter returned " + upstreamStatus + ".");
            }
        } catch (IOException error) {
            Map<String, Object> errorPayload = Map.of("status", "unavailable", "readiness_issues", List.of(sanitize(error.getMessage())));
            if (mutatesState) {
                completeReceipt(receiptId, upstreamStatus, "unavailable", errorPayload);
            } else {
                recordReceipt(operation, method, path, identity, upstreamStatus, "unavailable", false, "", body, errorPayload);
            }
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Python simulation adapter is unavailable.", error);
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            Map<String, Object> errorPayload = Map.of("status", "interrupted", "readiness_issues", List.of("Simulation adapter request interrupted."));
            if (mutatesState) {
                completeReceipt(receiptId, upstreamStatus, "interrupted", errorPayload);
            } else {
                recordReceipt(operation, method, path, identity, upstreamStatus, "interrupted", false, "", body, errorPayload);
            }
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Python simulation adapter request was interrupted.", error);
        }

        if (mutatesState) {
            receiptFinalized = completeReceipt(receiptId, upstreamStatus, string(payload.get("status"), "ok"), payload);
        } else {
            receiptId = recordReceipt(operation, method, path, identity, upstreamStatus, string(payload.get("status"), "ok"), false, "", body, payload);
            receiptFinalized = true;
        }
        payload.put("springRuntime", "java_spring");
        payload.put("simulationAuthority", "spring_control_plane_python_compute_adapter");
        Map<String, Object> facade = orderedMap();
        facade.put("mode", "simulation_facade_spring");
        facade.put("runtime", "java_spring");
        facade.put("receipt_id", receiptId);
        facade.put("operation", operation);
        facade.put("route", method + " " + path);
        facade.put("mutates_state", mutatesState);
        facade.put("python_adapter", "bounded_compute_only");
        facade.put("upstream_status", upstreamStatus);
        facade.put("receipt_finalized", receiptFinalized);
        if (hasText(idempotencyKey)) {
            facade.put("idempotency_key", idempotencyKey);
            facade.put("idempotency_replayed", false);
        }
        if (mutatesState && !receiptFinalized) {
            facade.put("receipt_update_status", "update_failed_pending_receipt_exists");
        }
        payload.put("simulationFacade", facade);
        return payload;
    }

    private HttpRequest buildRequest(HttpServletRequest inbound, String method, URI target, byte[] requestBytes, Map<String, Object> identity) {
        HttpRequest.Builder builder = HttpRequest.newBuilder(target)
            .timeout(Duration.ofMillis(timeoutMs))
            .header("content-type", "application/json")
            .header("x-parkpulse-spring-gateway", "simulation-facade")
            .header("x-parkpulse-spring-authorized-role", string(identity.get("role"), ""))
            .header("x-parkpulse-simulation-authority", "spring_control_plane");
        String authorization = inbound == null ? null : inbound.getHeader("authorization");
        if (authorization != null && !authorization.isBlank()) {
            builder.header("authorization", authorization);
        }
        String roleToken = inbound == null ? null : inbound.getHeader("x-parkpulse-role-token");
        if (roleToken != null && !roleToken.isBlank()) {
            builder.header("x-parkpulse-role-token", roleToken);
        }
        builder.header("x-parkpulse-role", string(identity.get("role"), "ops_team"));
        if (requestBytes.length == 0 && !"POST".equals(method)) {
            return builder.method(method, HttpRequest.BodyPublishers.noBody()).build();
        }
        return builder.method(method, HttpRequest.BodyPublishers.ofByteArray(requestBytes)).build();
    }

    private Map<String, Object> adapterHealth() {
        Map<String, Object> health = orderedMap();
        health.put("python_backend_url", pythonBackendUrl);
        health.put("probe_path", "/api/park/state-lite");
        try {
            HttpRequest request = HttpRequest.newBuilder(targetUri("/api/park/state-lite", null))
                .timeout(Duration.ofMillis(Math.max(750, Math.min(timeoutMs, 2500))))
                .header("accept", "application/json")
                .header("x-parkpulse-spring-gateway", "simulation-facade-health")
                .GET()
                .build();
            HttpResponse<byte[]> response = httpClient.send(request, HttpResponse.BodyHandlers.ofByteArray());
            Map<String, Object> body = parsePayload(response.body());
            health.put("reachable", response.statusCode() >= 200 && response.statusCode() < 300);
            health.put("http_status", response.statusCode());
            health.put("adapter_status", string(body.get("status"), "unknown"));
            health.put("adapter_mode", string(body.get("mode"), "unknown"));
        } catch (IOException error) {
            health.put("reachable", false);
            health.put("http_status", 0);
            health.put("adapter_status", "unavailable");
            health.put("error", sanitize(error.getMessage()));
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            health.put("reachable", false);
            health.put("http_status", 0);
            health.put("adapter_status", "interrupted");
            health.put("error", "Simulation adapter health probe interrupted.");
        }
        return health;
    }

    private Map<String, Object> ledgerHealth() {
        Map<String, Object> health = orderedMap();
        try {
            initLedger();
            health.put("writable", true);
            health.put("source_of_truth", "local_sqlite_wal");
            try (Connection connection = dataSource.getConnection()) {
                try (var statement = connection.prepareStatement(
                    """
                    SELECT COUNT(*) AS pending_count
                    FROM simulation_facade_receipts
                    WHERE response_status = 'pending_adapter_call'
                    """
                );
                     var result = statement.executeQuery()) {
                    health.put("pending_receipt_count", result.next() ? result.getInt("pending_count") : 0);
                }
                try (var statement = connection.prepareStatement(
                    """
                    SELECT receipt_id, created_at, operation, method, route, actor_role, actor_subject, upstream_status,
                           response_status, idempotency_key
                    FROM simulation_facade_receipts
                    WHERE mutates_state = 1 AND response_status <> 'pending_adapter_call'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                );
                     var result = statement.executeQuery()) {
                    health.put("last_finalized_mutation_receipt", result.next() ? receiptRow(result) : Map.of());
                }
            }
        } catch (SQLException | IllegalStateException error) {
            health.put("writable", false);
            health.put("source_of_truth", "local_sqlite_wal");
            health.put("pending_receipt_count", -1);
            health.put("last_finalized_mutation_receipt", Map.of());
            health.put("error", sanitize(error.getMessage()));
        }
        return health;
    }

    private Map<String, Object> receiptRow(java.sql.ResultSet result) throws SQLException {
        Map<String, Object> row = orderedMap();
        row.put("receipt_id", result.getString("receipt_id"));
        row.put("created_at", result.getString("created_at"));
        row.put("operation", result.getString("operation"));
        row.put("method", result.getString("method"));
        row.put("route", result.getString("route"));
        row.put("actor_role", result.getString("actor_role"));
        row.put("actor_subject", result.getString("actor_subject"));
        row.put("upstream_status", result.getInt("upstream_status"));
        row.put("response_status", result.getString("response_status"));
        row.put("idempotency_key", result.getString("idempotency_key"));
        return row;
    }

    private List<String> readinessIssues(boolean adapterReady, boolean ledgerReady, int pendingReceipts) {
        List<String> issues = new ArrayList<>();
        if (!adapterReady) {
            issues.add("Python simulation compute adapter is not reachable from Spring.");
        }
        if (!ledgerReady) {
            issues.add("Spring simulation authority ledger is not writable.");
        }
        if (pendingReceipts > 0) {
            issues.add(pendingReceipts + " simulation mutation receipt(s) are still pending adapter finalization.");
        }
        return issues;
    }

    private String recordReceipt(
        String operation,
        String method,
        String route,
        Map<String, Object> identity,
        int upstreamStatus,
        String responseStatus,
        boolean mutatesState,
        String idempotencyKey,
        Map<String, Object> request,
        Map<String, Object> response
    ) {
        initLedger();
        String createdAt = now();
        String receiptId = "simfacade_" + sha1(operation + ":" + route + ":" + createdAt + ":" + System.nanoTime(), 16);
        try (Connection connection = dataSource.getConnection();
             var statement = connection.prepareStatement(
                 """
                 INSERT INTO simulation_facade_receipts
                   (receipt_id, created_at, operation, method, route, actor_role, actor_subject, upstream_status,
                    response_status, mutates_state, idempotency_key, request_json, response_summary_json, response_json, python_backend_url, runtime)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                 """
             )) {
            statement.setString(1, receiptId);
            statement.setString(2, createdAt);
            statement.setString(3, operation);
            statement.setString(4, method);
            statement.setString(5, route);
            statement.setString(6, string(identity.get("role"), "unknown"));
            statement.setString(7, string(identity.get("subject"), "unknown"));
            statement.setInt(8, upstreamStatus);
            statement.setString(9, responseStatus);
            statement.setInt(10, mutatesState ? 1 : 0);
            statement.setString(11, string(idempotencyKey, ""));
            statement.setString(12, json(request == null ? Map.of() : request));
            statement.setString(13, json(responseSummary(response)));
            statement.setString(14, json(response == null ? Map.of() : response));
            statement.setString(15, pythonBackendUrl);
            statement.setString(16, "java_spring");
            statement.executeUpdate();
        } catch (SQLException error) {
            throw new IllegalStateException("Unable to record simulation facade receipt.", error);
        }
        return receiptId;
    }

    private boolean completeReceipt(String receiptId, int upstreamStatus, String responseStatus, Map<String, Object> response) {
        if (receiptId == null || receiptId.isBlank()) {
            return false;
        }
        initLedger();
        try (Connection connection = dataSource.getConnection();
             var statement = connection.prepareStatement(
                 """
                 UPDATE simulation_facade_receipts
                 SET upstream_status = ?, response_status = ?, response_summary_json = ?, response_json = ?
                 WHERE receipt_id = ?
                 """
             )) {
            statement.setInt(1, upstreamStatus);
            statement.setString(2, responseStatus);
            statement.setString(3, json(responseSummary(response)));
            statement.setString(4, json(response == null ? Map.of() : response));
            statement.setString(5, receiptId);
            return statement.executeUpdate() == 1;
        } catch (SQLException error) {
            return false;
        }
    }

    private Map<String, Object> replayIdempotentReceipt(String method, String route, Map<String, Object> identity, String idempotencyKey) {
        initLedger();
        try (Connection connection = dataSource.getConnection();
             var statement = connection.prepareStatement(
                 """
                 SELECT receipt_id, operation, upstream_status, response_status, response_json
                 FROM simulation_facade_receipts
                 WHERE method = ? AND route = ? AND actor_subject = ? AND idempotency_key = ?
                 ORDER BY created_at DESC
                 LIMIT 1
                 """
             )) {
            statement.setString(1, method);
            statement.setString(2, route);
            statement.setString(3, string(identity.get("subject"), "unknown"));
            statement.setString(4, idempotencyKey);
            try (var result = statement.executeQuery()) {
                if (!result.next()) {
                    return orderedMap();
                }
                String responseStatus = result.getString("response_status");
                String receiptId = result.getString("receipt_id");
                if ("pending_adapter_call".equals(responseStatus)) {
                    throw new ResponseStatusException(HttpStatus.CONFLICT, "Simulation idempotent request is still in progress.");
                }

                Map<String, Object> payload = readJson(result.getString("response_json"));
                if (payload.isEmpty()) {
                    payload.put("status", responseStatus);
                }
                payload.put("springRuntime", "java_spring");
                payload.put("simulationAuthority", "spring_control_plane_python_compute_adapter");

                Map<String, Object> facade = mapValue(payload.get("simulationFacade"));
                facade.put("mode", "simulation_facade_spring");
                facade.put("runtime", "java_spring");
                facade.put("receipt_id", receiptId);
                facade.put("operation", result.getString("operation"));
                facade.put("route", method + " " + route);
                facade.put("mutates_state", true);
                facade.put("python_adapter", "bounded_compute_only");
                facade.put("upstream_status", result.getInt("upstream_status"));
                facade.put("receipt_finalized", true);
                facade.put("idempotency_key", idempotencyKey);
                facade.put("idempotency_replayed", true);
                payload.put("simulationFacade", facade);
                payload.put("idempotency", Map.of(
                    "status", "replayed",
                    "key", idempotencyKey,
                    "receipt_id", receiptId
                ));
                return payload;
            }
        } catch (SQLException error) {
            throw new IllegalStateException("Unable to read simulation facade idempotency receipt.", error);
        }
    }

    private Map<String, Object> responseSummary(Map<String, Object> response) {
        Map<String, Object> summary = orderedMap();
        for (String key : List.of("status", "mode", "minutes", "simTime", "exerciseId", "summary", "readiness", "heartbeat_controller", "episode_fitness")) {
            if (response.containsKey(key)) {
                summary.put(key, response.get(key));
            }
        }
        if (response.containsKey("state")) {
            Map<String, Object> state = mapValue(response.get("state"));
            summary.put("state", Map.of(
                "has_state", true,
                "simTime", state.get("simTime"),
                "activeScenario", mapValue(mapValue(state.get("guestFlow")).get("activeScenario")).get("key")
            ));
        }
        return summary;
    }

    private void initLedger() {
        try (Connection connection = dataSource.getConnection();
             var statement = connection.createStatement()) {
            statement.executeUpdate("PRAGMA journal_mode=WAL");
            statement.executeUpdate(
                """
                CREATE TABLE IF NOT EXISTS simulation_facade_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    method TEXT NOT NULL,
                    route TEXT NOT NULL,
                    actor_role TEXT NOT NULL,
                    actor_subject TEXT NOT NULL,
                    upstream_status INTEGER NOT NULL,
                    response_status TEXT NOT NULL,
                    mutates_state INTEGER NOT NULL,
                    idempotency_key TEXT NOT NULL DEFAULT '',
                    request_json TEXT NOT NULL,
                    response_summary_json TEXT NOT NULL,
                    response_json TEXT NOT NULL DEFAULT '{}',
                    python_backend_url TEXT NOT NULL,
                    runtime TEXT NOT NULL
                )
                """
            );
            ensureColumn(connection, "idempotency_key", "TEXT NOT NULL DEFAULT ''");
            ensureColumn(connection, "response_json", "TEXT NOT NULL DEFAULT '{}'");
            statement.executeUpdate("CREATE INDEX IF NOT EXISTS idx_simulation_facade_receipts_created_at ON simulation_facade_receipts(created_at DESC)");
            statement.executeUpdate("CREATE INDEX IF NOT EXISTS idx_simulation_facade_receipts_operation ON simulation_facade_receipts(operation)");
            statement.executeUpdate(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_simulation_facade_receipts_idempotency
                ON simulation_facade_receipts(method, route, actor_subject, idempotency_key)
                WHERE idempotency_key <> ''
                """
            );
        } catch (SQLException error) {
            throw new IllegalStateException("Unable to initialize simulation facade ledger.", error);
        }
    }

    private void ensureColumn(Connection connection, String column, String definition) throws SQLException {
        boolean exists = false;
        try (var statement = connection.createStatement();
             var result = statement.executeQuery("PRAGMA table_info(simulation_facade_receipts)")) {
            while (result.next()) {
                if (column.equals(result.getString("name"))) {
                    exists = true;
                    break;
                }
            }
        }
        if (!exists) {
            try (var statement = connection.createStatement()) {
                statement.executeUpdate("ALTER TABLE simulation_facade_receipts ADD COLUMN " + column + " " + definition);
            }
        }
    }

    private URI targetUri(String path, String query) {
        StringBuilder uri = new StringBuilder(stripTrailingSlash(pythonBackendUrl)).append(path);
        if (query != null && !query.isBlank()) {
            uri.append("?").append(query);
        }
        return URI.create(uri.toString());
    }

    private Map<String, Object> parsePayload(byte[] bytes) {
        try {
            return mutableMap(objectMapper.readValue(bytes, MAP_TYPE));
        } catch (Exception error) {
            Map<String, Object> payload = orderedMap();
            payload.put("status", "non_json_response");
            payload.put("body", new String(bytes, StandardCharsets.UTF_8));
            return payload;
        }
    }

    private Map<String, Object> readJson(String value) {
        if (value == null || value.isBlank()) {
            return orderedMap();
        }
        try {
            return mutableMap(objectMapper.readValue(value, MAP_TYPE));
        } catch (Exception error) {
            Map<String, Object> payload = orderedMap();
            payload.put("raw", value);
            return payload;
        }
    }

    private byte[] jsonBytes(Map<String, Object> payload) {
        return json(payload).getBytes(StandardCharsets.UTF_8);
    }

    private String json(Map<String, Object> payload) {
        try {
            return objectMapper.writeValueAsString(payload == null ? Map.of() : payload);
        } catch (Exception error) {
            return "{}";
        }
    }

    private String resolvePythonBackendUrl() {
        String value = environment.getProperty("PARKPULSE_PYTHON_BACKEND_URL");
        if (value == null || value.isBlank()) {
            value = environment.getProperty("parkpulse.python-backend-url");
        }
        String resolved = value == null || value.isBlank() ? "http://127.0.0.1:8000" : stripTrailingSlash(value);
        String scheme = URI.create(resolved).getScheme();
        if (scheme == null || !Set.of("http", "https").contains(scheme.toLowerCase(Locale.ROOT))) {
            throw new IllegalArgumentException("PARKPULSE_PYTHON_BACKEND_URL must use http or https.");
        }
        return resolved;
    }

    private int intProperty(String envName, String propertyName, int defaultValue, int min, int max) {
        String raw = environment.getProperty(envName);
        if (raw == null || raw.isBlank()) {
            raw = environment.getProperty(propertyName, String.valueOf(defaultValue));
        }
        try {
            return Math.max(min, Math.min(max, Integer.parseInt(raw)));
        } catch (NumberFormatException error) {
            return defaultValue;
        }
    }

    private int boundedInt(Object value, int defaultValue, int min, int max) {
        try {
            return Math.max(min, Math.min(max, Integer.parseInt(String.valueOf(value))));
        } catch (Exception error) {
            return defaultValue;
        }
    }

    private Object firstPresent(Object left, Object right) {
        return left != null ? left : right;
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
        if (value == null) {
            return defaultValue;
        }
        String text = String.valueOf(value).trim();
        return text.isBlank() ? defaultValue : text;
    }

    private String sanitize(String value) {
        return value == null ? "upstream request failed" : value.replace("\"", "'");
    }

    private String idempotencyKey(HttpServletRequest request, Map<String, Object> body) {
        String header = request == null ? "" : string(firstPresent(request.getHeader("idempotency-key"), request.getHeader("x-idempotency-key")), "");
        if (hasText(header)) {
            return header;
        }
        return string(firstPresent(body == null ? null : body.get("idempotencyKey"), body == null ? null : body.get("idempotency_key")), "");
    }

    private boolean hasText(String value) {
        return value != null && !value.trim().isBlank();
    }

    private String stripTrailingSlash(String value) {
        return value.endsWith("/") ? value.substring(0, value.length() - 1) : value;
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
