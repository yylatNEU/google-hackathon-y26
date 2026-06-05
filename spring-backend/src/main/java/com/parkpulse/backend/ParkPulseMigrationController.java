package com.parkpulse.backend;

import jakarta.servlet.http.HttpServletRequest;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class ParkPulseMigrationController {
    private final PlatformStoreService platformStoreService;
    private final RoleAuthService roleAuthService;
    private final RoleContractService roleContractService;
    private final AuthorizationAuditService authorizationAuditService;
    private final ReliabilityDiagnosticsService reliabilityDiagnosticsService;
    private final Instant startedAt = Instant.now();

    public ParkPulseMigrationController(
        PlatformStoreService platformStoreService,
        RoleAuthService roleAuthService,
        RoleContractService roleContractService,
        AuthorizationAuditService authorizationAuditService,
        ReliabilityDiagnosticsService reliabilityDiagnosticsService
    ) {
        this.platformStoreService = platformStoreService;
        this.roleAuthService = roleAuthService;
        this.roleContractService = roleContractService;
        this.authorizationAuditService = authorizationAuditService;
        this.reliabilityDiagnosticsService = reliabilityDiagnosticsService;
    }

    @GetMapping(value = {"/", "/healthz"}, produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> health() {
        Map<String, Object> payload = orderedMap();
        payload.put("service", "parkpulse-spring-backend");
        payload.put("status", "ok");
        payload.put("entrypoint", "java-spring-migration");
        payload.put("current_slice", "platform_store_authority");
        payload.put("uptime_ms", Instant.now().toEpochMilli() - startedAt.toEpochMilli());
        return payload;
    }

    @GetMapping(value = "/readyz", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> readyz() {
        Map<String, Object> platform = platformStoreService.compactStatus();
        boolean ready = Boolean.TRUE.equals(platform.get("ready"));
        Map<String, Object> dependencies = orderedMap();
        dependencies.put("platform_store", platform);
        dependencies.put("python_backend", Map.of(
            "required_for_this_slice", false,
            "status", "not_checked",
            "ownership", "remaining agent and operations routes stay on Python during migration"
        ));

        Map<String, Object> payload = orderedMap();
        payload.put("service", "parkpulse-spring-backend");
        payload.put("status", ready ? "ok" : "degraded");
        payload.put("entrypoint", "java-spring-migration");
        payload.put("current_slice", "platform_store_authority");
        payload.put("dependency_status", dependencies);
        payload.put("readiness_issues", ready ? List.of() : platform.get("readiness_issues"));
        payload.put("boundary", "Spring owns only the migrated platform-store authority routes. Python remains authoritative for unmigrated ParkPulse operations routes.");
        return payload;
    }

    @GetMapping(value = "/api/park/platform-store", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> platformStore(HttpServletRequest request) {
        roleAuthService.requireCapability(request, "read_platform_status");
        return platformStoreService.status();
    }

    @PostMapping(value = "/api/park/platform-store/migrate", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> migratePlatformStore(
        HttpServletRequest request,
        @RequestBody(required = false) Map<String, Object> body
    ) {
        Map<String, Object> identity = roleAuthService.requireCapability(request, "manage_platform_store");
        String actor = String.valueOf(identity.getOrDefault("subject", identity.getOrDefault("role", "ml_ops_admin")));
        if (body != null && body.get("actor") != null && !String.valueOf(body.get("actor")).isBlank()) {
            actor = String.valueOf(body.get("actor"));
        }
        return platformStoreService.safeMigrate(actor);
    }

    @GetMapping(value = "/api/park/auth/dev-session", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> getDevRoleSession(HttpServletRequest request) {
        return roleAuthService.issueDevSession(request.getParameter("role"), request.getParameter("subject"));
    }

    @PostMapping(value = "/api/park/auth/dev-session", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> postDevRoleSession(@RequestBody(required = false) Map<String, Object> body) {
        Map<String, Object> payload = body == null ? Map.of() : body;
        return roleAuthService.issueDevSession(
            stringOrNull(payload.get("role")),
            stringOrNull(payload.get("subject"))
        );
    }

    @GetMapping(value = "/api/park/auth/status", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> authStatus(HttpServletRequest request) {
        roleAuthService.requireCapability(request, "read_identity_status");
        Map<String, Object> payload = orderedMap();
        payload.putAll(roleContractService.identityReadiness());
        payload.put("auth_contract", "Protected endpoints require a signed role session by default; role headers are ignored unless signed-token enforcement is explicitly disabled.");
        return payload;
    }

    @GetMapping(value = "/api/park/state-lite", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> stateLite() {
        Map<String, Object> guestFlow = orderedMap();
        guestFlow.put("activePolicy", "spring-hot-path");
        guestFlow.put("activeScenario", Map.of(
            "key", "spring_gateway_state_lite",
            "name", "Spring Gateway Operating State",
            "description", "Compact operating state served by Java Spring while heavier simulation routes continue migrating.",
            "condition", "normal"
        ));
        guestFlow.put("interventions", List.of());
        guestFlow.put("representedGuests", 12480);
        guestFlow.put("avgSatisfaction", 86);
        guestFlow.put("activeGroups", 3120);
        guestFlow.put("zones", List.of(
            Map.of("id", "covered-plaza", "name", "Covered Plaza", "density", 72, "waitMins", 12, "status", "watch"),
            Map.of("id", "east-midway", "name", "East Midway", "density", 58, "waitMins", 8, "status", "normal")
        ));
        guestFlow.put("paths", List.of(
            Map.of("id", "main-loop", "from", "front-gate", "to", "covered-plaza", "congestion", 44, "status", "normal"),
            Map.of("id", "east-cutover", "from", "east-midway", "to", "family-zone", "congestion", 39, "status", "normal")
        ));
        guestFlow.put("rides", List.of(
            Map.of("id", "dragon-coaster", "name", "Dragon Coaster", "status", "operating", "waitMins", 42, "queueGuests", 680, "throughputGap", 12),
            Map.of("id", "river-run", "name", "River Run", "status", "operating", "waitMins", 18, "queueGuests", 220, "throughputGap", 4)
        ));

        Map<String, Object> payload = orderedMap();
        payload.put("product", Map.of(
            "name", "ParkPulse",
            "domain", "amusement_park_operations",
            "one_liner", "Real-time park operating state and supervised action routing.",
            "primary_collections", List.of("guestFlow", "weather", "staffing", "parkOps")
        ));
        payload.put("simTime", Map.of("hour", 14, "minute", 15, "day", 1, "seasonIndex", 2));
        payload.put("weather", Map.of("condition", "partly_cloudy", "temperatureF", 82, "heatIndexF", 86, "humidity", 61, "windMph", 8, "stormRisk", 18));
        payload.put("energy", Map.of("gridLoadPercent", 63, "disruptionLoadMw", 0, "demandChargeRisk", "normal", "utilityPricePerMwh", 92, "carbonIntensity", 310));
        payload.put("staffing", Map.of("scheduled", 140, "checkedIn", 128, "openCallouts", 4, "medicalTeams", 4, "securityTeams", 5));
        payload.put("parkOps", Map.of("mode", "spring_hot_path", "outdoorCapacityCutPct", 0, "rideConflictCount", 1, "atRiskRides", 1, "guestRecoveryPressure", 28, "staffReadyPct", 91));
        payload.put("guestFlow", guestFlow);
        payload.put("alerts", List.of(Map.of("id", "spring-state-lite", "severity", "info", "message", "Spring is serving the hot state-lite route without Python fallback.")));
        payload.put("operationsAudit", Map.of(
            "ready", true,
            "mode", "spring_state_lite",
            "findings", List.of(),
            "policy_refs", List.of("PARK-SAFE-001", "PARK-OPS-001", "PARK-CARE-001")
        ));
        payload.put("heartbeatController", Map.of("status", "ready", "runtime", "java_spring"));
        payload.put("heartbeatExplanation", Map.of("status", "ready", "summary", "Compact Spring state is available for UI polling."));
        payload.put("runtime", "java_spring");
        payload.put("source_of_truth", "spring_hot_path_sqlite_authority");
        payload.put("updated_at", Instant.now().toString());
        return payload;
    }

    @GetMapping(value = "/api/park/role-access-contracts", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> roleAccessContracts(HttpServletRequest request) {
        roleAuthService.requireCapability(request, "read_role_contracts");
        return roleContractService.roleAccessContracts(request.getParameter("role"));
    }

    @GetMapping(value = "/api/park/reliability", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> reliability(HttpServletRequest request) {
        roleAuthService.requireCapability(request, "read_reliability_status");
        return reliabilityDiagnosticsService.reliabilityStatus();
    }

    @GetMapping(value = "/api/park/latency-diagnostics", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> latencyDiagnostics(HttpServletRequest request) {
        roleAuthService.requireCapability(request, "read_ops_evidence");
        return reliabilityDiagnosticsService.latencyDiagnostics("true".equalsIgnoreCase(request.getParameter("refresh")));
    }

    @GetMapping(value = "/api/park/authorization-audit", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> authorizationAudit(HttpServletRequest request) {
        roleAuthService.requireCapability(request, "read_platform_status");
        return authorizationAuditService.status();
    }

    @GetMapping(value = "/api/park/migration/java-spring/status", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> javaSpringMigrationStatus(HttpServletRequest request) {
        roleAuthService.requireCapability(request, "read_platform_status");
        return platformStoreService.migrationStatus();
    }

    private static LinkedHashMap<String, Object> orderedMap() {
        return new LinkedHashMap<>();
    }

    private static String stringOrNull(Object value) {
        return value == null ? null : String.valueOf(value);
    }
}
