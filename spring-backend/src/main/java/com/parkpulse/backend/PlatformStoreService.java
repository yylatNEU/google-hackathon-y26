package com.parkpulse.backend;

import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import javax.sql.DataSource;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Service;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

@Service
public class PlatformStoreService {
    private static final int SCHEMA_VERSION = 2;
    private static final String MIGRATION_ID = "20260605_0002_platform_store_data_boundaries";
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

    private final DataSource dataSource;
    private final Environment environment;
    private final ObjectMapper objectMapper;

    public PlatformStoreService(DataSource dataSource, Environment environment, ObjectMapper objectMapper) {
        this.dataSource = dataSource;
        this.environment = environment;
        this.objectMapper = objectMapper;
    }

    @EventListener(ApplicationReadyEvent.class)
    public void migrateOnStartup() {
        if (envBool("PARKPULSE_SPRING_AUTO_MIGRATE", true)) {
            safeMigrate("spring-startup");
        }
    }

    public Map<String, Object> safeMigrate(String actor) {
        initPlatformStore();
        List<Map<String, Object>> records = observedStoreRecords();
        Map<String, Object> event = orderedMap();
        event.put("event_id", "platform_migration_" + UUID.randomUUID().toString().replace("-", "").substring(0, 12));
        event.put("at", now());
        event.put("event_type", "safe_platform_store_registry_sync");
        event.put("status", "applied");
        event.put("actor", actor == null || actor.isBlank() ? "spring-backend" : actor);
        event.put("non_destructive", true);
        event.put("store_count", records.size());

        try (Connection connection = connection()) {
            connection.setAutoCommit(false);
            for (Map<String, Object> record : records) {
                upsertStoreRecord(connection, record);
            }
            try (var statement = connection.prepareStatement(
                """
                INSERT INTO platform_migration_events (event_id, at, event_type, status, detail_json)
                VALUES (?, ?, ?, ?, ?)
                """
            )) {
                statement.setString(1, event.get("event_id").toString());
                statement.setString(2, event.get("at").toString());
                statement.setString(3, event.get("event_type").toString());
                statement.setString(4, event.get("status").toString());
                statement.setString(5, json(event));
                statement.executeUpdate();
            }
            connection.commit();
        } catch (SQLException error) {
            throw new IllegalStateException("Unable to apply platform-store migration.", error);
        }

        Map<String, Object> status = status();
        status.put("migration", event);
        return status;
    }

    public Map<String, Object> status() {
        try {
            initPlatformStore();
            List<Map<String, Object>> registered = registryRows();
            List<Map<String, Object>> observed = observedStoreRecords();
            List<String> readinessIssues = observed.stream()
                .filter(record -> Boolean.TRUE.equals(record.get("required_for_core")))
                .filter(record -> "directory_missing".equals(record.get("status")))
                .map(record -> record.get("store_key") + " status is " + record.get("status"))
                .toList();

            Map<String, Object> result = orderedMap();
            result.put("status", readinessIssues.isEmpty() ? "ok" : "degraded");
            result.put("mode", "sqlite_platform_registry");
            result.put("source_of_truth", "local_sqlite_wal");
            result.put("path", platformDbPath().toString());
            result.put("schema_version", SCHEMA_VERSION);
            result.put("ready", readinessIssues.isEmpty());
            result.put("non_destructive", true);
            result.put("authority_boundary", "SQLite owns local transactional app authority. MongoDB/GCP remain optional operational memory and analytics integrations.");
            result.put("registered_store_count", registered.size());
            result.put("observed_store_count", observed.size());
            result.put("registered_stores", registered);
            result.put("observed_stores", observed);
            result.put("readiness_issues", readinessIssues);
            result.put("runtime", "java_spring_migration_slice");
            return result;
        } catch (RuntimeException error) {
            Map<String, Object> result = orderedMap();
            result.put("status", "error");
            result.put("mode", "sqlite_platform_registry");
            result.put("source_of_truth", "local_sqlite_wal");
            result.put("path", platformDbPath().toString());
            result.put("ready", false);
            result.put("non_destructive", true);
            result.put("readiness_issues", List.of(error.getMessage()));
            result.put("runtime", "java_spring_migration_slice");
            return result;
        }
    }

    public Map<String, Object> migrationStatus() {
        Map<String, Object> result = orderedMap();
        result.put("status", "active");
        result.put("mode", "continuous_java_spring_migration");
        result.put("current_slice", "spring_backend_gateway_plus_experience_studio_and_venue_profile_control_loop");
        result.put("spring_owned_routes", List.of(
            "/",
            "/health",
            "/healthz",
            "/readyz",
            "/api/park/auth/dev-session",
            "/api/park/auth/status",
            "/api/park/state",
            "/api/park/state-lite",
            "/api/park/live-summary",
            "/api/park/cases",
            "/api/park/cases/{case_id}/brief",
            "/api/park/signals/intake",
            "/api/park/agent-role-run",
            "/api/park/agent-run",
            "/api/park/live-feed-agent-run",
            "/api/park/operator-command",
            "/api/park/action",
            "/api/park/ops-chat",
            "/api/park/copilot-chat",
            "/api/park/agent-role-refine",
            "/api/park/full-runtime-status",
            "/api/park/full-runtime-warmup",
            "/api/park/warmup-status",
            "/api/park/agent-ops-ledger",
            "/api/park/monitor-evidence",
            "/api/park/policy-doctrine",
            "/api/park/policy-doctrine/{policy_ref}",
            "/api/park/agent-monitoring",
            "/api/park/agent-monitoring/deep",
            "/api/park/live-feed-health",
            "/api/park/live-feed-health/summary",
            "/api/park/live-feed-events",
            "/api/park/live-feeds/refresh-worker",
            "/api/park/live-feeds/refresh-stale",
            "/api/park/live-feeds/{source}",
            "/api/park/live-feeds/{source}/load",
            "/api/park/review-training-ledger",
            "/api/park/product-learning/loop",
            "/api/park/product-learning/issue-ticket",
            "/api/park/product-learning/training-gap-ticket",
            "/api/park/product-learning/promote-version",
            "/api/park/product-learning/rollback-version",
            "/api/park/product-learning/review-place-resolution",
            "/api/park/staff-training/scenarios",
            "/api/park/staff-training/policy-pack",
            "/api/park/staff-training/agent-context",
            "/api/park/staff-training/assignments",
            "/api/park/staff-training/readiness",
            "/api/park/staff-training/receipts",
            "/api/park/staff-training/certification-packet",
            "/api/park/staff-training/receipt-review",
            "/api/park/staff-training/demo-seed",
            "/api/park/staff-training/golden-eval",
            "/api/park/staff-training/sessions",
            "/api/park/staff-training/turn",
            "/api/park/staff-training/finish",
            "/api/park/staff-training/analytics",
            "/api/park/venue-profile",
            "/api/park/venue-profile/validate",
            "/api/park/venue-profile/import/preview",
            "/api/park/venue-profile/import",
            "/api/park/venue-profile/synthetic/export",
            "/api/park/venue-profile/synthetic/activate",
            "/api/park/accessibility/scope",
            "/api/park/accessibility/journey",
            "/api/park/accessibility/memory",
            "/api/park/accessibility/feedback",
            "/api/park/accessibility/tools",
            "/api/park/accessibility/tool",
            "/api/park/review-label-pipeline",
            "/api/park/review-label-pipeline/decision",
            "/api/park/review-label-pipeline/auto-label",
            "/api/park/review-label-pipeline/decisions",
            "/api/park/tick",
            "/api/park/time",
            "/api/park/causal-impact-demo",
            "/api/park/episode-fitness",
            "/api/park/digital-twin-war-room",
            "/api/park/digital-twin-war-room/run",
            "/api/park/digital-twin-war-room/remediate",
            "/api/park/simulation-facade/ledger",
            "/api/park/simulation-facade/health",
            "/api/park/experience-studio/conversation-plan",
            "/api/park/experience-studio/draft",
            "/api/park/experience-studio/section-revision",
            "/api/park/experience-studio/layer-contract",
            "/api/park/experience-studio/readiness",
            "/api/park/experience-studio/memory",
            "/api/park/experience-studio/drafts",
            "/api/park/experience-studio/drafts/{draft_id}",
            "/api/park/experience-studio/drafts/{draft_id}/status",
            "/api/park/experience-studio/handoffs",
            "/api/park/experience-studio/drafts/{draft_id}/handoff",
            "/api/park/experience-studio/learning-rules",
            "/api/park/experience-studio/drafts/{draft_id}/promote-rule",
            "/api/park/experience-studio/learning-rules/{rule_id}/status",
            "/api/park/role-access-contracts",
            "/api/park/reliability",
            "/api/park/latency-diagnostics",
            "/api/park/authorization-audit",
            "/api/park/delivery/contract",
            "/api/park/delivery/outbox",
            "/api/park/delivery/gcp-adapters/status",
            "/api/park/delivery/partner-retries/status",
            "/api/park/delivery/partner-retries/run",
            "/api/park/delivery/guest-promotion",
            "/api/park/delivery/worker-notification",
            "/api/park/delivery/equipment-command",
            "/api/park/delivery/acknowledge",
            "/api/park/delivery/approval-decision",
            "/api/park/events/contract",
            "/api/park/events/status",
            "/api/park/events/ledger",
            "/api/park/events/receiver/guest-response",
            "/api/park/events/receiver/worker-acknowledgement",
            "/api/park/events/receiver/equipment-result",
            "/api/park/events/eventarc/park-signal",
            "/api/park/delegation-token",
            "/api/park/agent-onboarding/issuer",
            "/api/park/agent-onboarding/register",
            "/api/park/agent-onboarding/{agent_id}/certify",
            "/api/park/agent-onboarding/verify-credential",
            "/api/park/agent-onboarding/{agent_id}",
            "/api/park/agent-onboarding/revoke-credential",
            "/api/park/agent-trust/status",
            "/api/park/agent-trust/partners",
            "/api/park/agent-trust/keys",
            "/api/park/agent-trust/keys/rotate",
            "/api/park/agent-trust/revocations",
            "/api/park/agent-trust/audit",
            "/api/park/handshake",
            "/api/park/session/{session_id}",
            "/api/park/session/{session_id}/capabilities",
            "/api/park/session/{session_id}/intent",
            "/api/park/session/{session_id}/propose",
            "/api/park/session/{session_id}/counter",
            "/api/park/session/{session_id}/commit",
            "/api/park/session/{session_id}/monitor",
            "/api/park/session/{session_id}/receipt",
            "/api/park/internal-agents/commerce/evaluate",
            "/api/park/internal-agents/queue/reroute",
            "/api/park/platform-store",
            "/api/park/platform-store/migrate",
            "/api/park/migration/java-spring/status",
            "/api/park/backend-gateway/status"
        ));
        result.put("spring_gateway_routes", List.of("/api/**", "/readyz/deep"));
        result.put("python_owned_routes", "Gemini/Vertex deep adapter execution, heavy creative generation, remaining simulation surfaces, Mongo-only memory enrichers, and live GCP delivery adapters are reached through the Spring gateway until each route group is migrated natively.");
        result.put("handoff_rule", "Move one bounded route group at a time only after parity tests and SQLite authority checks pass.");
        result.put("rollback", "Stop the Spring service and keep Python serving the same SQLite-backed authority.");
        result.put("platform_store", compactStatus());
        return result;
    }

    public Map<String, Object> compactStatus() {
        Map<String, Object> status = status();
        Map<String, Object> compact = orderedMap();
        compact.put("ready", status.get("ready"));
        compact.put("mode", status.get("mode"));
        compact.put("source_of_truth", status.get("source_of_truth"));
        compact.put("path", status.get("path"));
        compact.put("schema_version", status.get("schema_version"));
        compact.put("registered_store_count", status.get("registered_store_count"));
        compact.put("observed_store_count", status.get("observed_store_count"));
        compact.put("authority_boundary", status.get("authority_boundary"));
        compact.put("readiness_issues", status.get("readiness_issues"));
        compact.put("runtime", "java_spring_migration_slice");
        return compact;
    }

    private void initPlatformStore() {
        ensureParent(platformDbPath());
        try (Connection connection = connection(); var statement = connection.createStatement()) {
            statement.execute(
                """
                CREATE TABLE IF NOT EXISTS platform_schema_migrations (
                    migration_id TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    description TEXT NOT NULL
                )
                """
            );
            statement.execute(
                """
                CREATE TABLE IF NOT EXISTS platform_store_registry (
                    store_key TEXT PRIMARY KEY,
                    authority TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    path TEXT NOT NULL,
                    data_classification TEXT NOT NULL,
                    data_model TEXT NOT NULL DEFAULT 'unspecified',
                    source_of_truth INTEGER NOT NULL DEFAULT 0,
                    shared_across_instances INTEGER NOT NULL,
                    required_for_core INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    record_count INTEGER,
                    metadata_json TEXT NOT NULL,
                    migrated_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            );
            statement.execute(
                """
                CREATE TABLE IF NOT EXISTS platform_migration_events (
                    event_id TEXT PRIMARY KEY,
                    at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail_json TEXT NOT NULL
                )
                """
            );
            if (!columnExists(connection, "platform_store_registry", "data_model")) {
                statement.execute("ALTER TABLE platform_store_registry ADD COLUMN data_model TEXT NOT NULL DEFAULT 'unspecified'");
            }
            if (!columnExists(connection, "platform_store_registry", "source_of_truth")) {
                statement.execute("ALTER TABLE platform_store_registry ADD COLUMN source_of_truth INTEGER NOT NULL DEFAULT 0");
            }
            try (var migration = connection.prepareStatement(
                """
                INSERT OR IGNORE INTO platform_schema_migrations (migration_id, applied_at, checksum, description)
                VALUES (?, ?, ?, ?)
                """
            )) {
                migration.setString(1, MIGRATION_ID);
                migration.setString(2, now());
                migration.setString(3, "platform_store_registry:v2:data_boundaries");
                migration.setString(4, "Add explicit data model and source-of-truth boundaries to the platform store registry.");
                migration.executeUpdate();
            }
            statement.execute("PRAGMA user_version = " + SCHEMA_VERSION);
        } catch (SQLException error) {
            throw new IllegalStateException("Unable to initialize platform store.", error);
        }
    }

    private List<Map<String, Object>> observedStoreRecords() {
        Path runtimeDir = runtimeDir();
        Path replayPath = envPath("PARKPULSE_REPLAY_DB", runtimeDir.resolve("park_replay.db"));
        Path auditPath = envPath("PARKPULSE_AUDIT_DB", runtimeDir.resolve("park_audit.db"));
        Path trustPath = envPath("PARKPULSE_AGENT_TRUST_DB", runtimeDir.resolve("agent_trust.db"));
        Path handshakePath = envPath("PARKPULSE_AGENT_HANDSHAKE_DB", runtimeDir.resolve("agent_handshake.db"));
        Path deliveryPath = envPath("PARKPULSE_DELIVERY_OUTBOX", runtimeDir.resolve("delivery_outbox.jsonl"));
        Path liveFeedPath = envPath("PARKPULSE_LIVE_FEED_PATH", runtimeDir.resolve("live_feed_events.jsonl"));
        Path agentOpsPath = envPath("PARKPULSE_AGENT_OPS_LEDGER", runtimeDir.resolve("agent_ops_ledger.jsonl"));
        Path reviewPath = envPath("PARKPULSE_REVIEW_LEDGER_LOG_PATH", runtimeDir.resolve("review_ledger.jsonl"));
        Path monitorEvidencePath = envPath("PARKPULSE_MONITOR_EVIDENCE_SNAPSHOT_PATH", Path.of(System.getProperty("user.dir")).getParent().resolve("output").resolve("monitor-evidence-limit-40.json"));
        Map<String, Object> monitorSnapshotStore = monitorEvidenceSnapshotStore(monitorEvidencePath);
        Path policyBooksPath = Path.of(System.getProperty("user.dir")).getParent().resolve("backend").resolve("policy_books");
        Path legacyPath = legacyPlatformDbPath();
        List<String> legacyTables = sqliteTables(legacyPath);
        boolean liveFeedMongo = env("PARKPULSE_LIVE_FEED_STORAGE", "").toLowerCase(Locale.ROOT).matches("mongo|mongodb");

        List<Map<String, Object>> records = new ArrayList<>();
        records.add(storeRecord("platform_registry", "core_sqlite_store_registry", "sqlite_wal", platformDbPath(), "platform_metadata", false, true, "ready", null, Map.of("schema_version", SCHEMA_VERSION, "migration_id", MIGRATION_ID)));
        records.add(storeRecord("replay_store", "transactional_replay_and_action_audit", "sqlite_wal", replayPath, "operator_action_replay", false, true, Files.exists(replayPath) ? "ready" : "will_initialize_on_first_write", sqliteCount(replayPath, List.of("replay_runs", "replay_events")), Map.of("override_env", "PARKPULSE_REPLAY_DB")));
        records.add(storeRecord("audit_store", "policy_audit_findings", "sqlite_wal", auditPath, "operational_audit", false, true, Files.exists(auditPath) ? "ready" : "will_initialize_on_first_write", sqliteCount(auditPath, List.of("audit_events", "audit_findings")), Map.of("override_env", "PARKPULSE_AUDIT_DB")));
        records.add(storeRecord("agent_trust_store", "agent_partner_trust_and_revocation_registry", "sqlite_wal", trustPath, "identity_authority_metadata", false, true, Files.exists(trustPath) ? "ready" : "will_initialize_on_first_write", sqliteCount(trustPath, List.of("agent_partners", "credential_revocations", "certification_keys", "trust_audit_events", "agent_onboardings")), Map.of("override_env", "PARKPULSE_AGENT_TRUST_DB")));
        records.add(storeRecord("agent_handshake_store", "agent_handshake_session_registry", "sqlite_wal", handshakePath, "agent_session_authority", false, true, Files.exists(handshakePath) ? "ready" : "will_initialize_on_first_write", sqliteCount(handshakePath, List.of("agent_handshake_sessions")), Map.of("override_env", "PARKPULSE_AGENT_HANDSHAKE_DB")));
        records.add(storeRecord("delivery_outbox", "append_first_receiver_dispatch_outbox", "jsonl_durable_outbox", deliveryPath, "receiver_dispatch_receipts", false, true, Files.exists(deliveryPath.getParent()) ? "ready" : "directory_missing", jsonlCount(deliveryPath), Map.of("override_env", "PARKPULSE_DELIVERY_OUTBOX")));
        records.add(storeRecord("live_feed_events", "local_live_feed_event_buffer", "jsonl_or_mongodb", liveFeedPath, "observed_operational_signals", liveFeedMongo, false, liveFeedMongo ? "mongodb_configured" : "local_jsonl", jsonlCount(liveFeedPath), Map.of("override_env", "PARKPULSE_LIVE_FEED_STORAGE")));
        records.add(storeRecord("agent_ops_ledger", "agent_run_receipt_and_eval_ledger", "jsonl_receipt_ledger", agentOpsPath, "agent_decision_trace_receipts", false, false, Files.exists(agentOpsPath) ? "ready" : "will_initialize_on_first_write", jsonlCount(agentOpsPath), Map.of("override_env", "PARKPULSE_AGENT_OPS_LEDGER")));
        records.add(storeRecord("review_ledger", "human_review_training_ledger", "jsonl_or_mongodb", reviewPath, "human_review_sessions_and_dispositions", liveFeedMongo, false, liveFeedMongo ? "mongodb_configured" : "local_jsonl", jsonlCount(reviewPath), Map.of("override_env", "PARKPULSE_REVIEW_LEDGER_LOG_PATH")));
        records.add(storeRecord("policy_books", "policy_doctrine_source_files", "versioned_json_documents", policyBooksPath, "policy_doctrine", true, true, Files.exists(policyBooksPath) ? "ready" : "missing", Files.exists(policyBooksPath) ? jsonFileCount(policyBooksPath) : 0, Map.of("legacy_policy_book", policyBooksPath.getParent().resolve("policy_book.json").toString())));
        records.add(storeRecord("monitor_evidence_snapshot", "derived_monitor_evidence_graph_cache", monitorSnapshotStore.get("mode").toString(), Path.of(monitorSnapshotStore.get("path").toString()), "derived_case_trace_review_policy_graph", Boolean.TRUE.equals(monitorSnapshotStore.get("shared")), false, monitorSnapshotStore.get("status").toString(), null, castMap(monitorSnapshotStore.get("metadata"))));
        String legacyStatus = !Files.exists(legacyPath) ? "not_present" : legacyTables.isEmpty() ? "legacy_empty" : "legacy_non_empty_preserved";
        records.add(storeRecord("legacy_repo_park_data_db", "legacy_artifact_not_current_source_of_truth", "sqlite_legacy", legacyPath, "legacy_platform_database", false, false, legacyStatus, sqliteCount(legacyPath, legacyTables), Map.of("tables", legacyTables, "safe_migration_action", "preserved_without_copy_or_delete")));
        return records;
    }

    private Map<String, Object> storeRecord(String key, String authority, String mode, Path path, String classification, boolean shared, boolean required, String status, Integer count, Map<String, Object> metadata) {
        Map<String, Object> record = orderedMap();
        String now = now();
        record.put("store_key", key);
        record.put("authority", authority);
        record.put("mode", mode);
        record.put("path", path.toString());
        record.put("data_classification", classification);
        record.put("data_model", dataModelFor(key));
        record.put("source_of_truth", sourceOfTruthFor(key));
        record.put("shared_across_instances", shared);
        record.put("required_for_core", required);
        record.put("status", status);
        record.put("record_count", count);
        record.put("metadata", metadata);
        record.put("migrated_at", now);
        record.put("updated_at", now);
        return record;
    }

    private void upsertStoreRecord(Connection connection, Map<String, Object> record) throws SQLException {
        try (var statement = connection.prepareStatement(
            """
            INSERT INTO platform_store_registry (
                store_key, authority, mode, path, data_classification, data_model, source_of_truth, shared_across_instances,
                required_for_core, status, record_count, metadata_json, migrated_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(store_key) DO UPDATE SET
                authority = excluded.authority,
                mode = excluded.mode,
                path = excluded.path,
                data_classification = excluded.data_classification,
                data_model = excluded.data_model,
                source_of_truth = excluded.source_of_truth,
                shared_across_instances = excluded.shared_across_instances,
                required_for_core = excluded.required_for_core,
                status = excluded.status,
                record_count = excluded.record_count,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """
        )) {
            statement.setString(1, record.get("store_key").toString());
            statement.setString(2, record.get("authority").toString());
            statement.setString(3, record.get("mode").toString());
            statement.setString(4, record.get("path").toString());
            statement.setString(5, record.get("data_classification").toString());
            statement.setString(6, record.get("data_model").toString());
            statement.setInt(7, Boolean.TRUE.equals(record.get("source_of_truth")) ? 1 : 0);
            statement.setInt(8, Boolean.TRUE.equals(record.get("shared_across_instances")) ? 1 : 0);
            statement.setInt(9, Boolean.TRUE.equals(record.get("required_for_core")) ? 1 : 0);
            statement.setString(10, record.get("status").toString());
            if (record.get("record_count") instanceof Integer count) {
                statement.setInt(11, count);
            } else {
                statement.setObject(11, null);
            }
            statement.setString(12, json(record.get("metadata")));
            statement.setString(13, record.get("migrated_at").toString());
            statement.setString(14, record.get("updated_at").toString());
            statement.executeUpdate();
        }
    }

    private List<Map<String, Object>> registryRows() {
        try (Connection connection = connection();
             var statement = connection.prepareStatement("SELECT * FROM platform_store_registry ORDER BY required_for_core DESC, store_key");
             ResultSet rows = statement.executeQuery()) {
            List<Map<String, Object>> records = new ArrayList<>();
            while (rows.next()) {
                Map<String, Object> record = orderedMap();
                record.put("store_key", rows.getString("store_key"));
                record.put("authority", rows.getString("authority"));
                record.put("mode", rows.getString("mode"));
                record.put("path", rows.getString("path"));
                record.put("data_classification", rows.getString("data_classification"));
                record.put("data_model", rows.getString("data_model"));
                record.put("source_of_truth", rows.getInt("source_of_truth") == 1);
                record.put("shared_across_instances", rows.getInt("shared_across_instances") == 1);
                record.put("required_for_core", rows.getInt("required_for_core") == 1);
                record.put("status", rows.getString("status"));
                Object count = rows.getObject("record_count");
                record.put("record_count", count instanceof Number number ? number.intValue() : null);
                record.put("metadata", objectMapper.readValue(rows.getString("metadata_json"), MAP_TYPE));
                record.put("migrated_at", rows.getString("migrated_at"));
                record.put("updated_at", rows.getString("updated_at"));
                records.add(record);
            }
            return records;
        } catch (Exception error) {
            throw new IllegalStateException("Unable to read platform store registry.", error);
        }
    }

    private List<String> sqliteTables(Path path) {
        if (!Files.exists(path)) {
            return List.of();
        }
        try (Connection connection = DriverManager.getConnection("jdbc:sqlite:" + path);
             var statement = connection.prepareStatement("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name");
             ResultSet rows = statement.executeQuery()) {
            List<String> tables = new ArrayList<>();
            while (rows.next()) {
                tables.add(rows.getString(1));
            }
            return tables;
        } catch (SQLException error) {
            return List.of();
        }
    }

    private Integer sqliteCount(Path path, List<String> tableNames) {
        if (!Files.exists(path)) {
            return 0;
        }
        List<String> tables = sqliteTables(path);
        int total = 0;
        try (Connection connection = DriverManager.getConnection("jdbc:sqlite:" + path)) {
            for (String tableName : tableNames) {
                if (!tables.contains(tableName)) {
                    continue;
                }
                try (var statement = connection.prepareStatement("SELECT COUNT(*) FROM " + quoteIdentifier(tableName));
                     ResultSet row = statement.executeQuery()) {
                    if (row.next()) {
                        total += row.getInt(1);
                    }
                }
            }
            return total;
        } catch (SQLException error) {
            return null;
        }
    }

    private Integer jsonlCount(Path path) {
        if (!Files.exists(path)) {
            return 0;
        }
        if (!envBool("PARKPULSE_PLATFORM_STATUS_COUNT_JSONL", false)) {
            return null;
        }
        try (var lines = Files.lines(path)) {
            return (int) lines.filter(line -> !line.isBlank()).count();
        } catch (Exception error) {
            return null;
        }
    }

    private Integer jsonFileCount(Path path) {
        if (!Files.isDirectory(path)) {
            return 0;
        }
        try (var files = Files.list(path)) {
            return (int) files.filter(file -> file.getFileName().toString().endsWith(".json")).count();
        } catch (Exception error) {
            return null;
        }
    }

    private Map<String, Object> monitorEvidenceSnapshotStore(Path localPath) {
        String requested = env("PARKPULSE_MONITOR_EVIDENCE_STORAGE", "local").toLowerCase(Locale.ROOT).trim();
        Map<String, Object> baseMetadata = Map.of(
            "override_env", "PARKPULSE_MONITOR_EVIDENCE_STORAGE",
            "path_override_env", "PARKPULSE_MONITOR_EVIDENCE_SNAPSHOT_PATH",
            "derived_from", List.of("agent_ops_ledger", "review_ledger", "live_feed_events", "policy_books", "case_index"),
            "cache_invalidation", "source_watermark_fingerprint"
        );
        if (List.of("redis", "upstash").contains(requested)) {
            String redisUrl = firstPresent("PARKPULSE_MONITOR_EVIDENCE_REDIS_URL", "REDIS_URL", "UPSTASH_REDIS_REST_URL");
            Map<String, Object> metadata = orderedMap();
            metadata.putAll(baseMetadata);
            metadata.put("backend", "redis");
            metadata.put("connection_env", "PARKPULSE_MONITOR_EVIDENCE_REDIS_URL");
            metadata.put("local_fallback_path", localPath.toString());
            return Map.of("mode", "redis_snapshot_cache", "path", "redis/monitor-evidence", "shared", true, "status", redisUrl.isBlank() ? "redis_unconfigured" : "redis_configured", "metadata", metadata);
        }
        if (List.of("mongo", "mongodb").contains(requested)) {
            String mongoUri = firstPresent("MONGODB_DIRECT_URI", "MONGODB_URI", "MONGO_URI", "PARKPULSE_MONGODB_URI");
            Map<String, Object> metadata = orderedMap();
            metadata.putAll(baseMetadata);
            metadata.put("backend", "mongodb");
            metadata.put("connection_env", "MONGODB_DIRECT_URI|MONGODB_URI|MONGO_URI");
            metadata.put("database", env("PARKPULSE_MONITOR_EVIDENCE_MONGO_DATABASE", env("MONGODB_DATABASE", "parkpulse")));
            metadata.put("collection", env("PARKPULSE_MONITOR_EVIDENCE_MONGO_COLLECTION", "monitor_evidence_snapshots"));
            metadata.put("local_fallback_path", localPath.toString());
            return Map.of("mode", "mongodb_snapshot_cache", "path", "mongodb/monitor_evidence_snapshots", "shared", true, "status", mongoUri.isBlank() ? "mongodb_unconfigured" : "mongodb_configured", "metadata", metadata);
        }
        Map<String, Object> metadata = orderedMap();
        metadata.putAll(baseMetadata);
        metadata.put("backend", "local_json");
        metadata.put("production_target", "redis_or_mongodb_snapshot_cache");
        return Map.of("mode", "json_snapshot_cache", "path", localPath.toString(), "shared", false, "status", Files.exists(localPath) ? "ready" : "will_initialize_on_first_read", "metadata", metadata);
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> castMap(Object value) {
        return value instanceof Map<?, ?> ? (Map<String, Object>) value : Map.of();
    }

    private String firstPresent(String... keys) {
        for (String key : keys) {
            String value = env(key, "");
            if (!value.isBlank()) {
                return value;
            }
        }
        return "";
    }

    private boolean columnExists(Connection connection, String tableName, String columnName) throws SQLException {
        try (var statement = connection.prepareStatement("PRAGMA table_info(" + quoteIdentifier(tableName) + ")");
             ResultSet rows = statement.executeQuery()) {
            while (rows.next()) {
                if (columnName.equals(rows.getString("name"))) {
                    return true;
                }
            }
        }
        return false;
    }

    private String dataModelFor(String key) {
        return switch (key) {
            case "platform_registry" -> "relational_registry";
            case "replay_store" -> "relational_event_index";
            case "audit_store" -> "relational_audit_log";
            case "agent_trust_store" -> "relational_identity_registry";
            case "agent_handshake_store" -> "relational_session_registry";
            case "delivery_outbox", "agent_ops_ledger" -> "append_event_log";
            case "live_feed_events", "review_ledger" -> "event_log";
            case "policy_books" -> "document_store";
            case "monitor_evidence_snapshot" -> "derived_snapshot";
            case "legacy_repo_park_data_db" -> "legacy_relational_database";
            default -> "unspecified";
        };
    }

    private boolean sourceOfTruthFor(String key) {
        return !List.of("monitor_evidence_snapshot", "legacy_repo_park_data_db").contains(key);
    }

    private Connection connection() throws SQLException {
        ensureParent(platformDbPath());
        Connection connection = dataSource.getConnection();
        try (var statement = connection.createStatement()) {
            statement.execute("PRAGMA journal_mode=WAL");
            statement.execute("PRAGMA synchronous=NORMAL");
            statement.execute("PRAGMA busy_timeout=5000");
        }
        return connection;
    }

    private Path runtimeDir() {
        return envPath("PARKPULSE_RUNTIME_DIR", Path.of("/tmp/parkpulse"));
    }

    private Path platformDbPath() {
        return envPath("PARKPULSE_PLATFORM_DB", runtimeDir().resolve("park_data.db"));
    }

    private Path legacyPlatformDbPath() {
        return envPath("PARKPULSE_LEGACY_PLATFORM_DB", Path.of(System.getProperty("user.dir")).getParent().resolve("backend").resolve("park_data.db"));
    }

    private Path envPath(String name, Path fallback) {
        String value = env(name, "");
        return value.isBlank() ? fallback : Path.of(value).toAbsolutePath().normalize();
    }

    private String env(String name, String fallback) {
        String value = environment.getProperty(name);
        return value == null || value.isBlank() ? fallback : value;
    }

    private boolean envBool(String name, boolean fallback) {
        String value = environment.getProperty(name);
        if (value == null || value.isBlank()) {
            return fallback;
        }
        return List.of("1", "true", "yes", "on").contains(value.toLowerCase(Locale.ROOT));
    }

    private void ensureParent(Path path) {
        try {
            if (path.getParent() != null) {
                Files.createDirectories(path.getParent());
            }
        } catch (Exception error) {
            throw new IllegalStateException("Unable to create directory for " + path, error);
        }
    }

    private String quoteIdentifier(String tableName) {
        return "\"" + tableName.replace("\"", "\"\"") + "\"";
    }

    private String json(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception error) {
            throw new IllegalStateException("Unable to serialize platform store payload.", error);
        }
    }

    private static String now() {
        return Instant.now().truncatedTo(ChronoUnit.SECONDS).toString();
    }

    private static LinkedHashMap<String, Object> orderedMap() {
        return new LinkedHashMap<>();
    }
}
