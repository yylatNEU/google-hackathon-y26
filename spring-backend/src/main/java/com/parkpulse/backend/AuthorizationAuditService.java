package com.parkpulse.backend;

import jakarta.servlet.http.HttpServletRequest;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import javax.sql.DataSource;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;

@Service
public class AuthorizationAuditService {
    private final DataSource dataSource;
    private final ObjectMapper objectMapper;

    public AuthorizationAuditService(DataSource dataSource, ObjectMapper objectMapper) {
        this.dataSource = dataSource;
        this.objectMapper = objectMapper;
    }

    public void record(HttpServletRequest request, String capability, Map<String, Object> identity, boolean allowed, String reason) {
        try {
            init();
            Map<String, Object> detail = orderedMap();
            detail.put("method", request.getMethod());
            detail.put("path", request.getRequestURI());
            detail.put("query", request.getQueryString());
            detail.put("capability", capability);
            detail.put("identity_status", identity.getOrDefault("status", "unknown"));
            detail.put("issuer", identity.getOrDefault("issuer", ""));
            detail.put("reason", reason);
            try (Connection connection = dataSource.getConnection();
                 var statement = connection.prepareStatement(
                     """
                     INSERT INTO spring_authorization_audit_events (
                         event_id, at, decision, capability, method, path, role, subject, reason, detail_json
                     )
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                     """
                 )) {
                statement.setString(1, "spring_auth_" + UUID.randomUUID().toString().replace("-", "").substring(0, 16));
                statement.setString(2, now());
                statement.setString(3, allowed ? "allowed" : "blocked");
                statement.setString(4, capability);
                statement.setString(5, request.getMethod());
                statement.setString(6, request.getRequestURI());
                statement.setString(7, String.valueOf(identity.getOrDefault("role", "")));
                statement.setString(8, String.valueOf(identity.getOrDefault("subject", "")));
                statement.setString(9, reason == null ? "" : reason);
                statement.setString(10, objectMapper.writeValueAsString(detail));
                statement.executeUpdate();
            }
        } catch (Exception ignored) {
            // Authorization must not fail open or fail closed because audit persistence is unavailable.
        }
    }

    public Map<String, Object> status() {
        try {
            init();
            Map<String, Object> counts = orderedMap();
            List<Map<String, Object>> recent = new ArrayList<>();
            try (Connection connection = dataSource.getConnection();
                 var countStatement = connection.prepareStatement(
                     """
                     SELECT decision, COUNT(*) AS event_count
                     FROM spring_authorization_audit_events
                     GROUP BY decision
                     ORDER BY decision
                     """
                 );
                 ResultSet countRows = countStatement.executeQuery()) {
                while (countRows.next()) {
                    counts.put(countRows.getString("decision"), countRows.getInt("event_count"));
                }
            }
            try (Connection connection = dataSource.getConnection();
                 var recentStatement = connection.prepareStatement(
                     """
                     SELECT event_id, at, decision, capability, method, path, role, subject, reason
                     FROM spring_authorization_audit_events
                     ORDER BY at DESC
                     LIMIT 12
                     """
                 );
                 ResultSet rows = recentStatement.executeQuery()) {
                while (rows.next()) {
                    Map<String, Object> event = orderedMap();
                    event.put("event_id", rows.getString("event_id"));
                    event.put("at", rows.getString("at"));
                    event.put("decision", rows.getString("decision"));
                    event.put("capability", rows.getString("capability"));
                    event.put("method", rows.getString("method"));
                    event.put("path", rows.getString("path"));
                    event.put("role", rows.getString("role"));
                    event.put("subject", rows.getString("subject"));
                    event.put("reason", rows.getString("reason"));
                    recent.add(event);
                }
            }
            Map<String, Object> payload = orderedMap();
            payload.put("status", "ok");
            payload.put("mode", "spring_authorization_audit");
            payload.put("source_of_truth", "local_sqlite_wal");
            payload.put("counts", counts);
            payload.put("recent", recent);
            payload.put("runtime", "java_spring");
            return payload;
        } catch (Exception error) {
            Map<String, Object> payload = orderedMap();
            payload.put("status", "degraded");
            payload.put("mode", "spring_authorization_audit");
            payload.put("readiness_issues", List.of(error.getMessage()));
            payload.put("runtime", "java_spring");
            return payload;
        }
    }

    private void init() throws SQLException {
        try (Connection connection = dataSource.getConnection(); var statement = connection.createStatement()) {
            statement.execute("PRAGMA journal_mode=WAL");
            statement.execute(
                """
                CREATE TABLE IF NOT EXISTS spring_authorization_audit_events (
                    event_id TEXT PRIMARY KEY,
                    at TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    method TEXT NOT NULL,
                    path TEXT NOT NULL,
                    role TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    detail_json TEXT NOT NULL
                )
                """
            );
            statement.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_spring_authorization_audit_events_at
                ON spring_authorization_audit_events(at DESC)
                """
            );
            statement.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_spring_authorization_audit_events_decision
                ON spring_authorization_audit_events(decision, capability)
                """
            );
        }
    }

    private static String now() {
        return Instant.now().toString();
    }

    private static LinkedHashMap<String, Object> orderedMap() {
        return new LinkedHashMap<>();
    }
}
