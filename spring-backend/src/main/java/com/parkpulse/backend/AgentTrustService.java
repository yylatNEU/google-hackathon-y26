package com.parkpulse.backend;

import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Service;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

@Service
public class AgentTrustService {
    private static final TypeReference<List<String>> STRING_LIST_TYPE = new TypeReference<>() {};
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

    private final Environment environment;
    private final ObjectMapper objectMapper;

    public AgentTrustService(Environment environment, ObjectMapper objectMapper) {
        this.environment = environment;
        this.objectMapper = objectMapper;
    }

    public Map<String, Object> status() {
        init();
        Path path = dbPath();
        Map<String, Object> store = orderedMap();
        store.put("ready", true);
        store.put("mode", "sqlite_wal");
        store.put("path", path.toString());
        store.put("exists", Files.exists(path));
        store.put("bytes", size(path));
        store.put("partners", count("agent_partners"));
        store.put("revocations", count("credential_revocations"));
        store.put("keys", count("certification_keys"));
        store.put("audit_events", count("trust_audit_events"));

        Map<String, Object> payload = orderedMap();
        payload.put("status", "ready");
        payload.put("mode", "durable_agent_trust_registry");
        payload.put("runtime", "java_spring");
        payload.put("store", store);
        payload.put("active_key", activeKey());
        payload.put("partner_registry_size", store.get("partners"));
        payload.put("revocation_registry_size", store.get("revocations"));
        payload.put("routes", List.of(
            "GET /api/park/agent-trust/status",
            "GET /api/park/agent-trust/partners",
            "POST /api/park/agent-trust/partners",
            "GET /api/park/agent-trust/keys",
            "POST /api/park/agent-trust/keys/rotate",
            "GET /api/park/agent-trust/revocations",
            "GET /api/park/agent-trust/audit"
        ));
        return payload;
    }

    public Map<String, Object> partners() {
        List<Map<String, Object>> partners = listPartners();
        return Map.of("status", "ready", "partners", partners, "count", partners.size(), "runtime", "java_spring");
    }

    public Map<String, Object> upsertPartner(Map<String, Object> payload) {
        init();
        String actor = stringOrDefault(payload.get("actor"), payload.get("approved_by"), payload.get("approvedBy"), "parkpulse_trust_admin");
        String partnerId = stringOrDefault(payload.get("partner_id"), payload.get("partnerId"), "");
        if (partnerId.isBlank()) {
            return Map.of("status", "rejected", "reason", "partner_id is required.", "runtime", "java_spring");
        }
        String now = now();
        try (Connection connection = connection()) {
            connection.setAutoCommit(false);
            String createdAt = now;
            try (var existing = connection.prepareStatement("SELECT created_at FROM agent_partners WHERE partner_id = ?")) {
                existing.setString(1, partnerId);
                try (ResultSet rows = existing.executeQuery()) {
                    if (rows.next()) {
                        createdAt = rows.getString("created_at");
                    }
                }
            }
            Map<String, Object> partner = orderedMap();
            partner.put("partner_id", partnerId);
            partner.put("partner_name", stringOrDefault(payload.get("partner_name"), payload.get("partnerName"), partnerId));
            partner.put("contact", stringOrDefault(payload.get("contact"), payload.get("partner_contact"), payload.get("partnerContact"), ""));
            partner.put("trust_tier", stringOrDefault(payload.get("trust_tier"), payload.get("trustTier"), "sandbox"));
            partner.put("status", stringOrDefault(payload.get("status"), "active"));
            partner.put("allowed_scopes", scopes(payload.get("allowed_scopes"), payload.get("allowedScopes"), payload.get("scope")));
            partner.put("created_at", createdAt);
            partner.put("updated_at", now);
            try (var statement = connection.prepareStatement(
                """
                INSERT INTO agent_partners (partner_id, partner_name, contact, trust_tier, status, allowed_scopes_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(partner_id) DO UPDATE SET
                    partner_name = excluded.partner_name,
                    contact = excluded.contact,
                    trust_tier = excluded.trust_tier,
                    status = excluded.status,
                    allowed_scopes_json = excluded.allowed_scopes_json,
                    updated_at = excluded.updated_at
                """
            )) {
                statement.setString(1, partnerId);
                statement.setString(2, String.valueOf(partner.get("partner_name")));
                statement.setString(3, String.valueOf(partner.get("contact")));
                statement.setString(4, String.valueOf(partner.get("trust_tier")));
                statement.setString(5, String.valueOf(partner.get("status")));
                statement.setString(6, json(partner.get("allowed_scopes")));
                statement.setString(7, createdAt);
                statement.setString(8, now);
                statement.executeUpdate();
            }
            recordAudit(connection, "partner_upsert", partnerId, partner, actor);
            connection.commit();
            return Map.of("status", "upserted", "partner", partner, "actor", actor, "runtime", "java_spring");
        } catch (Exception error) {
            throw new IllegalStateException("Unable to upsert agent-trust partner.", error);
        }
    }

    public Map<String, Object> keys() {
        List<Map<String, Object>> keys = listKeys();
        Map<String, Object> payload = orderedMap();
        payload.put("status", "ready");
        payload.put("active_key", activeKey());
        payload.put("keys", keys);
        payload.put("count", keys.size());
        payload.put("jwks", Map.of("keys", jwks(keys)));
        payload.put("runtime", "java_spring");
        return payload;
    }

    public Map<String, Object> rotateKey(Map<String, Object> payload) {
        init();
        String actor = stringOrDefault(payload.get("actor"), payload.get("rotated_by"), payload.get("rotatedBy"), "parkpulse_trust_admin");
        String version = sanitizeVersion(stringOrDefault(payload.get("version"), payload.get("key_version"), payload.get("keyVersion"), "v" + Instant.now().getEpochSecond()));
        String kid = "spring-cert-" + sha256(version).substring(0, 16);
        String now = now();
        Map<String, Object> metadata = Map.of("rotated_by", actor, "protocol_version", "parkpulse-ahp-0.1", "runtime", "java_spring", "signing_boundary", "metadata_only_until_credential_signing_migrates");
        Map<String, Object> record = orderedMap();
        record.put("kid", kid);
        record.put("version", version);
        record.put("alg", "EdDSA");
        record.put("mode", "spring_metadata_record");
        record.put("status", "active");
        record.put("created_at", now);
        record.put("activated_at", now);
        record.put("retired_at", null);
        record.put("metadata", metadata);
        try (Connection connection = connection()) {
            connection.setAutoCommit(false);
            try (var retire = connection.prepareStatement("UPDATE certification_keys SET status = 'retired', retired_at = COALESCE(retired_at, ?) WHERE status = 'active'")) {
                retire.setString(1, now);
                retire.executeUpdate();
            }
            try (var statement = connection.prepareStatement(
                """
                INSERT INTO certification_keys (kid, version, alg, mode, status, created_at, activated_at, retired_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(kid) DO UPDATE SET
                    version = excluded.version,
                    alg = excluded.alg,
                    mode = excluded.mode,
                    status = excluded.status,
                    activated_at = excluded.activated_at,
                    retired_at = excluded.retired_at,
                    metadata_json = excluded.metadata_json
                """
            )) {
                statement.setString(1, kid);
                statement.setString(2, version);
                statement.setString(3, "EdDSA");
                statement.setString(4, "spring_metadata_record");
                statement.setString(5, "active");
                statement.setString(6, now);
                statement.setString(7, now);
                statement.setObject(8, null);
                statement.setString(9, json(metadata));
                statement.executeUpdate();
            }
            recordAudit(connection, "key_record", kid, record, actor);
            connection.commit();
        } catch (Exception error) {
            throw new IllegalStateException("Unable to rotate agent-trust key metadata.", error);
        }
        return Map.of("status", "rotated", "active_key", record, "signing", Map.of("kid", kid, "alg", "EdDSA", "version", version), "jwks", Map.of("keys", jwks(List.of(record))), "runtime", "java_spring");
    }

    public Map<String, Object> revocations(int limit) {
        List<Map<String, Object>> revocations = listRevocations(limit);
        return Map.of("status", "ready", "revocations", revocations, "count", revocations.size(), "runtime", "java_spring");
    }

    public Map<String, Object> audit(int limit) {
        List<Map<String, Object>> events = listAudit(limit);
        return Map.of("status", "ready", "events", events, "count", events.size(), "runtime", "java_spring");
    }

    private void init() {
        try (Connection connection = connection(); var statement = connection.createStatement()) {
            statement.execute("PRAGMA journal_mode=WAL");
            statement.execute("PRAGMA synchronous=NORMAL");
            statement.execute("PRAGMA busy_timeout=5000");
            statement.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_partners (
                    partner_id TEXT PRIMARY KEY,
                    partner_name TEXT NOT NULL,
                    contact TEXT NOT NULL DEFAULT '',
                    trust_tier TEXT NOT NULL,
                    status TEXT NOT NULL,
                    allowed_scopes_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            );
            statement.execute(
                """
                CREATE TABLE IF NOT EXISTS credential_revocations (
                    certification_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL,
                    revoked_by TEXT NOT NULL,
                    revoked_at TEXT NOT NULL,
                    record_json TEXT NOT NULL
                )
                """
            );
            statement.execute(
                """
                CREATE TABLE IF NOT EXISTS certification_keys (
                    kid TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    alg TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    activated_at TEXT,
                    retired_at TEXT,
                    metadata_json TEXT NOT NULL
                )
                """
            );
            statement.execute(
                """
                CREATE TABLE IF NOT EXISTS trust_audit_events (
                    event_id TEXT PRIMARY KEY,
                    at TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            );
        } catch (SQLException error) {
            throw new IllegalStateException("Unable to initialize agent-trust store.", error);
        }
    }

    private List<Map<String, Object>> listPartners() {
        init();
        try (Connection connection = connection();
             var statement = connection.prepareStatement("SELECT * FROM agent_partners ORDER BY partner_id");
             ResultSet rows = statement.executeQuery()) {
            List<Map<String, Object>> partners = new ArrayList<>();
            while (rows.next()) {
                Map<String, Object> partner = orderedMap();
                partner.put("partner_id", rows.getString("partner_id"));
                partner.put("partner_name", rows.getString("partner_name"));
                partner.put("contact", rows.getString("contact"));
                partner.put("trust_tier", rows.getString("trust_tier"));
                partner.put("status", rows.getString("status"));
                partner.put("allowed_scopes", objectMapper.readValue(rows.getString("allowed_scopes_json"), STRING_LIST_TYPE));
                partner.put("created_at", rows.getString("created_at"));
                partner.put("updated_at", rows.getString("updated_at"));
                partners.add(partner);
            }
            return partners;
        } catch (Exception error) {
            throw new IllegalStateException("Unable to list agent-trust partners.", error);
        }
    }

    private List<Map<String, Object>> listKeys() {
        init();
        try (Connection connection = connection();
             var statement = connection.prepareStatement("SELECT * FROM certification_keys ORDER BY created_at DESC");
             ResultSet rows = statement.executeQuery()) {
            List<Map<String, Object>> keys = new ArrayList<>();
            while (rows.next()) {
                keys.add(keyFromRow(rows));
            }
            return keys;
        } catch (Exception error) {
            throw new IllegalStateException("Unable to list agent-trust keys.", error);
        }
    }

    private Map<String, Object> activeKey() {
        return listKeys().stream()
            .filter(key -> "active".equals(key.get("status")))
            .max(Comparator.comparing(key -> String.valueOf(key.getOrDefault("activated_at", ""))))
            .orElse(null);
    }

    private List<Map<String, Object>> listRevocations(int limit) {
        init();
        try (Connection connection = connection();
             var statement = connection.prepareStatement("SELECT record_json FROM credential_revocations ORDER BY revoked_at DESC LIMIT ?")) {
            statement.setInt(1, Math.max(1, Math.min(limit, 500)));
            try (ResultSet rows = statement.executeQuery()) {
                List<Map<String, Object>> revocations = new ArrayList<>();
                while (rows.next()) {
                    revocations.add(objectMapper.readValue(rows.getString("record_json"), MAP_TYPE));
                }
                return revocations;
            }
        } catch (Exception error) {
            throw new IllegalStateException("Unable to list credential revocations.", error);
        }
    }

    private List<Map<String, Object>> listAudit(int limit) {
        init();
        try (Connection connection = connection();
             var statement = connection.prepareStatement("SELECT * FROM trust_audit_events ORDER BY at DESC LIMIT ?")) {
            statement.setInt(1, Math.max(1, Math.min(limit, 500)));
            try (ResultSet rows = statement.executeQuery()) {
                List<Map<String, Object>> events = new ArrayList<>();
                while (rows.next()) {
                    Map<String, Object> event = orderedMap();
                    event.put("event_id", rows.getString("event_id"));
                    event.put("at", rows.getString("at"));
                    event.put("actor", rows.getString("actor"));
                    event.put("action", rows.getString("action"));
                    event.put("target_id", rows.getString("target_id"));
                    event.put("payload", objectMapper.readValue(rows.getString("payload_json"), MAP_TYPE));
                    events.add(event);
                }
                return events;
            }
        } catch (Exception error) {
            throw new IllegalStateException("Unable to list agent-trust audit events.", error);
        }
    }

    private Map<String, Object> keyFromRow(ResultSet row) throws Exception {
        Map<String, Object> key = orderedMap();
        key.put("kid", row.getString("kid"));
        key.put("version", row.getString("version"));
        key.put("alg", row.getString("alg"));
        key.put("mode", row.getString("mode"));
        key.put("status", row.getString("status"));
        key.put("created_at", row.getString("created_at"));
        key.put("activated_at", row.getString("activated_at"));
        key.put("retired_at", row.getString("retired_at"));
        key.put("metadata", objectMapper.readValue(row.getString("metadata_json"), MAP_TYPE));
        return key;
    }

    private void recordAudit(Connection connection, String action, String targetId, Map<String, Object> payload, String actor) throws Exception {
        try (var statement = connection.prepareStatement(
            "INSERT INTO trust_audit_events (event_id, at, actor, action, target_id, payload_json) VALUES (?, ?, ?, ?, ?, ?)"
        )) {
            statement.setString(1, "trust_evt_" + UUID.randomUUID().toString().replace("-", "").substring(0, 12));
            statement.setString(2, now());
            statement.setString(3, actor);
            statement.setString(4, action);
            statement.setString(5, targetId);
            statement.setString(6, json(payload));
            statement.executeUpdate();
        }
    }

    private int count(String table) {
        init();
        try (Connection connection = connection();
             var statement = connection.prepareStatement("SELECT COUNT(*) AS count FROM " + table);
             ResultSet rows = statement.executeQuery()) {
            return rows.next() ? rows.getInt("count") : 0;
        } catch (SQLException error) {
            return 0;
        }
    }

    private List<String> scopes(Object... candidates) {
        for (Object candidate : candidates) {
            if (candidate instanceof List<?> list) {
                return list.stream().map(String::valueOf).filter(item -> !item.isBlank()).distinct().sorted().toList();
            }
            if (candidate instanceof String value && !value.isBlank()) {
                return List.of(value.split(",")).stream().map(String::trim).filter(item -> !item.isBlank()).distinct().sorted().toList();
            }
        }
        return List.of("location", "party_size", "preferences", "route_plan", "accessibility", "notifications");
    }

    private List<Map<String, Object>> jwks(List<Map<String, Object>> keys) {
        return keys.stream().map(key -> Map.of(
            "kid", key.get("kid"),
            "alg", key.get("alg"),
            "kty", "OKP",
            "use", "sig",
            "status", key.get("status"),
            "mode", key.get("mode")
        )).toList();
    }

    private Connection connection() throws SQLException {
        Path path = dbPath();
        try {
            Files.createDirectories(path.getParent());
        } catch (Exception error) {
            throw new SQLException("Unable to create agent-trust db directory.", error);
        }
        return DriverManager.getConnection("jdbc:sqlite:" + path);
    }

    private Path dbPath() {
        String configured = environment.getProperty("PARKPULSE_AGENT_TRUST_DB");
        if (configured != null && !configured.isBlank()) {
            return Path.of(configured);
        }
        return Path.of(environment.getProperty("PARKPULSE_RUNTIME_DIR", "/tmp/parkpulse")).resolve("agent_trust.db");
    }

    private String json(Object value) throws Exception {
        return objectMapper.writeValueAsString(value);
    }

    private String sha256(String value) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(java.nio.charset.StandardCharsets.UTF_8)));
        } catch (Exception error) {
            throw new IllegalStateException("Unable to hash key version.", error);
        }
    }

    private String sanitizeVersion(String value) {
        String sanitized = value.replaceAll("[^A-Za-z0-9_.-]+", "_").replaceAll("^_+|_+$", "");
        return sanitized.isBlank() ? "v" + Instant.now().getEpochSecond() : sanitized;
    }

    private long size(Path path) {
        try {
            return Files.exists(path) ? Files.size(path) : 0L;
        } catch (Exception error) {
            return 0L;
        }
    }

    private String stringOrDefault(Object first, Object second, Object third, String defaultValue) {
        return stringOrDefault(new Object[] {first, second, third}, defaultValue);
    }

    private String stringOrDefault(Object first, Object second, String defaultValue) {
        return stringOrDefault(new Object[] {first, second}, defaultValue);
    }

    private String stringOrDefault(Object first, String defaultValue) {
        return stringOrDefault(new Object[] {first}, defaultValue);
    }

    private String stringOrDefault(Object[] values, String defaultValue) {
        for (Object value : values) {
            if (value != null && !String.valueOf(value).isBlank()) {
                return String.valueOf(value);
            }
        }
        return defaultValue;
    }

    private static String now() {
        return Instant.now().toString();
    }

    private static LinkedHashMap<String, Object> orderedMap() {
        return new LinkedHashMap<>();
    }
}
