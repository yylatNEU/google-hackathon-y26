package com.parkpulse.backend;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Service;

@Service
public class ReliabilityDiagnosticsService {
    private final Environment environment;
    private final PlatformStoreService platformStoreService;
    private final AuthorizationAuditService authorizationAuditService;
    private final PythonFallbackProxyService pythonFallbackProxyService;

    public ReliabilityDiagnosticsService(
        Environment environment,
        PlatformStoreService platformStoreService,
        AuthorizationAuditService authorizationAuditService,
        PythonFallbackProxyService pythonFallbackProxyService
    ) {
        this.environment = environment;
        this.platformStoreService = platformStoreService;
        this.authorizationAuditService = authorizationAuditService;
        this.pythonFallbackProxyService = pythonFallbackProxyService;
    }

    public Map<String, Object> reliabilityStatus() {
        Map<String, Object> payload = orderedMap();
        payload.put("status", "ok");
        payload.put("mode", "spring_reliability_diagnostics");
        payload.put("runtime", "java_spring");
        payload.put("checked_at", Instant.now().toString());
        payload.put("retries_timeouts_circuit_breakers", retryAndCircuitStatus());
        payload.put("platform_store", platformStoreService.compactStatus());
        payload.put("authorization_audit", authorizationAuditService.status());
        payload.put("backend_gateway", pythonFallbackProxyService.status());
        payload.put("backup_systems", backupSystems());
        payload.put("graceful_failure", Map.of(
            "spring_gateway", "returns controlled 502 JSON when the Python fallback is unavailable",
            "sqlite", "uses WAL-backed local authority and non-destructive schema creation",
            "auth", "blocks invalid tokens before capability checks and records decisions to SQLite"
        ));
        return payload;
    }

    public Map<String, Object> latencyDiagnostics(boolean refresh) {
        Map<String, Object> payload = orderedMap();
        payload.put("status", "ready");
        payload.put("mode", "spring_lightweight_latency_diagnostics");
        payload.put("runtime", "java_spring");
        payload.put("checked_at", Instant.now().toString());
        payload.put("refresh", refresh);
        payload.put("hot_path", Map.of(
            "native_spring", List.of("/health", "/readyz", "/api/park/auth/status", "/api/park/reliability", "/api/park/latency-diagnostics"),
            "fallback_gateway", "/api/** and /readyz/deep for unmigrated route groups",
            "sqlite_authority", "local_sqlite_wal"
        ));
        payload.put("backend_gateway", pythonFallbackProxyService.status());
        payload.put("platform_store", platformStoreService.compactStatus());
        payload.put("authorization_audit", authorizationAuditService.status());
        payload.put("probe_trigger", refresh
            ? Map.of("started", List.of(), "skipped", Map.of("spring_native", "live dependency probes remain on Python until migrated"))
            : Map.of("started", List.of(), "skipped", Map.of("all", "refresh_not_requested")));
        payload.put("persistence", Map.of(
            "status", "native_summary_only",
            "reason", "Spring avoids importing Python runtime for latency diagnostics; deep probes remain behind fallback until migrated."
        ));
        return payload;
    }

    private Map<String, Object> retryAndCircuitStatus() {
        Map<String, Object> payload = orderedMap();
        payload.put("enabled", !envBool("PARKPULSE_DISABLE_RELIABILITY", false));
        payload.put("retry_attempts", envInt("PARKPULSE_RETRY_ATTEMPTS", 2, 1));
        payload.put("retry_base_delay_seconds", envDouble("PARKPULSE_RETRY_BASE_DELAY_SECONDS", 0.2, 0.0));
        payload.put("retry_max_delay_seconds", envDouble("PARKPULSE_RETRY_MAX_DELAY_SECONDS", 2.0, 0.0));
        payload.put("circuit_failure_threshold", envInt("PARKPULSE_CIRCUIT_FAILURE_THRESHOLD", 3, 1));
        payload.put("circuit_recovery_seconds", envDouble("PARKPULSE_CIRCUIT_RECOVERY_SECONDS", 30.0, 0.0));
        payload.put("circuit_breakers", Map.of(
            "spring_python_fallback_gateway", Map.of(
                "state", "request_scoped",
                "timeout_ms", pythonFallbackProxyService.status().get("timeout_ms"),
                "failure_behavior", "controlled_502"
            )
        ));
        return payload;
    }

    private Map<String, Object> backupSystems() {
        Path runtimeDir = pathFromEnv("PARKPULSE_RUNTIME_DIR", Path.of("/tmp/parkpulse"));
        Path replayBackupDir = pathFromEnv("PARKPULSE_REPLAY_BACKUP_DIR", runtimeDir.resolve("replay_backups"));
        long backupCount = 0;
        if (Files.isDirectory(replayBackupDir)) {
            try (var stream = Files.list(replayBackupDir)) {
                backupCount = stream.filter(Files::isRegularFile).count();
            } catch (Exception ignored) {
                backupCount = 0;
            }
        }
        Map<String, Object> payload = orderedMap();
        payload.put("sqlite_replay_backups", backupCount);
        payload.put("replay_backup_dir", replayBackupDir.toString());
        payload.put("manual_backup_endpoint", "/api/park/replay/backup");
        payload.put("manual_backup_endpoint_runtime", "python_fallback_until_replay_slice_migrates");
        return payload;
    }

    private Path pathFromEnv(String name, Path defaultPath) {
        String value = environment.getProperty(name);
        if (value == null || value.isBlank()) {
            return defaultPath;
        }
        return Path.of(value);
    }

    private int envInt(String name, int defaultValue, int minimum) {
        String value = environment.getProperty(name);
        try {
            return Math.max(minimum, Integer.parseInt(value == null || value.isBlank() ? String.valueOf(defaultValue) : value));
        } catch (NumberFormatException error) {
            return defaultValue;
        }
    }

    private double envDouble(String name, double defaultValue, double minimum) {
        String value = environment.getProperty(name);
        try {
            return Math.max(minimum, Double.parseDouble(value == null || value.isBlank() ? String.valueOf(defaultValue) : value));
        } catch (NumberFormatException error) {
            return defaultValue;
        }
    }

    private boolean envBool(String name, boolean defaultValue) {
        String value = environment.getProperty(name);
        if (value == null || value.isBlank()) {
            return defaultValue;
        }
        return List.of("1", "true", "yes", "on").contains(value.trim().toLowerCase());
    }

    private static LinkedHashMap<String, Object> orderedMap() {
        return new LinkedHashMap<>();
    }
}
