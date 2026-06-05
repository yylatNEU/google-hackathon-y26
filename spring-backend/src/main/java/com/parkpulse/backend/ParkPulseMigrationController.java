package com.parkpulse.backend;

import jakarta.servlet.http.HttpServletRequest;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
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
        return springState("spring_state_lite");
    }

    @GetMapping(value = "/api/park/state", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> state() {
        Map<String, Object> payload = springState("spring_state");
        payload.put("operatingClock", Map.of(
            "phase", Map.of("label", "Afternoon peak", "demandPressurePct", 68),
            "source", "java_spring_hot_path"
        ));
        payload.put("maintenance", Map.of("openWorkOrders", 3, "criticalAssets", 1, "mode", "spring_state"));
        payload.put("guestCare", Map.of("openCases", 6, "recoveryPressure", 28, "mode", "spring_state"));
        payload.put("externalSystems", Map.of(
            "pythonFallback", "optional",
            "sqliteAuthority", "ready",
            "springGateway", "primary"
        ));
        return payload;
    }

    @GetMapping(value = "/api/park/live-summary", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> liveSummary() {
        Map<String, Object> state = springState("spring_live_summary_state");
        Map<String, Object> guestFlow = mapValue(state.get("guestFlow"));
        Map<String, Object> topRide = highestWaitRow(listValue(guestFlow.get("rides")));
        Map<String, Object> topZone = highestWaitRow(listValue(guestFlow.get("zones")));
        Map<String, Object> simTime = mapValue(state.get("simTime"));

        Map<String, Object> payload = orderedMap();
        payload.put("status", "ready");
        payload.put("mode", "compact_live_operating_summary_spring");
        payload.put("entrypoint", "java-spring-migration");
        payload.put("runtime", "java_spring");
        payload.put("dataPlane", Map.of(
            "hotState", "java spring state projection",
            "auditPackets", "python fallback or future spring case service",
            "warehouse", "BigQuery export contract",
            "retrieval", "policy and memory retrieval contract",
            "asyncWork", "receiver dispatch contract"
        ));
        payload.put("simulationClock", Map.of(
            "hour", simTime.get("hour"),
            "minute", simTime.get("minute"),
            "phase", "Afternoon peak",
            "demandPressurePct", 68
        ));
        payload.put("operatingSummary", Map.of(
            "caseCount", 2,
            "domainCoverageCount", 3,
            "productionReady", false,
            "topPriorityCaseId", "spring_queue_pressure",
            "topPriorityTitle", "Dragon Coaster queue pressure",
            "highestQueue", Map.of(
                "id", topRide.get("id"),
                "name", topRide.get("name"),
                "waitMins", topRide.get("waitMins"),
                "densityPct", topZone.get("density")
            )
        ));
        payload.put("activeCase", Map.of(
            "caseId", "spring_queue_pressure",
            "rank", 1,
            "domain", "guest_flow",
            "severity", "watch",
            "score", 72,
            "mapFocus", List.of(topRide.get("id"), topZone.get("id")),
            "acceptance", Map.of(
                "allowedSurface", "operator_review",
                "blockerClasses", List.of("human_approval_required_for_dispatch"),
                "nextOwnerAction", "Review queue split and staff positioning before dispatch."
            ),
            "productionEvidence", Map.of(
                "state", "spring_state_projection",
                "feedCount", 4,
                "blockedStages", List.of()
            )
        ));
        payload.put("caseIndexEndpoint", "/api/park/cases");
        payload.put("caseBriefEndpoint", "/api/park/cases/{case_id}/brief");
        payload.put("fullAuditPacketEndpoint", "/api/park/industrial-dossiers/{case_id}/packet");
        payload.put("operatingQueue", List.of(
            Map.of("id", "spring_queue_pressure", "title", "Dragon Coaster queue pressure", "domain", "guest_flow", "severity", "watch"),
            Map.of("id", "spring_staff_readiness", "title", "Staff callout coverage watch", "domain", "staffing", "severity", "normal")
        ));
        return payload;
    }

    @GetMapping(value = "/api/park/cases", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> cases() {
        List<Map<String, Object>> rows = springCaseRows();
        Map<String, Object> payload = orderedMap();
        payload.put("status", "ready");
        payload.put("mode", "compact_case_index_spring");
        payload.put("standard", "ParkPulse Spring operating case index");
        payload.put("runtime", "java_spring");
        payload.put("simulationClock", Map.of("hour", 14, "minute", 15, "phase", "Afternoon peak", "demandPressurePct", 68));
        payload.put("summary", Map.of(
            "caseCount", rows.size(),
            "domainCoverageCount", 3,
            "productionReady", false
        ));
        payload.put("rows", rows);
        payload.put("storagePlan", Map.of(
            "hotIndex", "java spring case projection",
            "auditPacketObject", "spring evidence summary plus future warehouse packet",
            "warehouseTables", List.of("case_ledgers", "case_events", "case_evaluations"),
            "retrievalIndex", "policy and evidence chunks"
        ));
        return payload;
    }

    @GetMapping(value = "/api/park/cases/{caseId}/brief", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> caseBrief(@PathVariable String caseId) {
        Map<String, Object> row = springCaseRows().stream()
            .filter(item -> caseId.equals(String.valueOf(item.get("id"))))
            .findFirst()
            .orElseGet(() -> springCaseRows().get(0));
        Map<String, Object> governance = mapValue(row.get("governance"));
        Map<String, Object> payload = orderedMap();
        payload.put("status", "ready");
        payload.put("mode", "case_operating_brief_spring");
        payload.put("runtime", "java_spring");
        payload.put("caseHeader", Map.of(
            "id", row.get("id"),
            "sourceConflictId", "spring_case_projection",
            "title", row.get("title"),
            "domain", row.get("domain"),
            "severity", row.get("severity"),
            "mapFocus", List.of("dragon-coaster", "covered-plaza")
        ));
        payload.put("operatingThesis", mapValue(row.get("priority")).get("rationale"));
        payload.put("physicalMechanism", "Guest flow, queue pressure, staff coverage, and receiver dispatch are connected into one auditable loop.");
        payload.put("recommendedAction", governance.get("nextOwnerAction"));
        payload.put("policyReasoning", Map.of(
            "applies", List.of("PARK-SAFE-001", "PARK-OPS-001", "PARK-CARE-001"),
            "decision", governance.get("allowedSurface"),
            "blockedActions", governance.get("blockerClasses")
        ));
        payload.put("governance", Map.of("acceptance", governance));
        payload.put("branchComparison", List.of());
        payload.put("closedLoopVerification", Map.of(
            "observationWindows", List.of("5 minutes", "15 minutes"),
            "projectedVsObservedChecks", List.of("queue wait", "receiver acknowledgement", "guest-care cases")
        ));
        return payload;
    }

    @GetMapping(value = "/api/park/monitor-evidence", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> monitorEvidence(@RequestParam(name = "case_id", required = false) String caseId) {
        List<Map<String, Object>> graphCases = springMonitorEvidenceCases(caseId);
        Map<String, Object> payload = orderedMap();
        payload.put("status", "ready");
        payload.put("mode", "monitor_evidence_graph_spring");
        payload.put("runtime", "java_spring");
        payload.put("case_count", graphCases.size());
        payload.put("summary", Map.of(
            "receipt_count", 2,
            "trace_record_count", graphCases.stream().mapToInt(item -> listValue(item.get("trace_records")).size()).sum(),
            "distinct_trace_id_count", 2,
            "review_session_count", 2,
            "linked_review_session_count", 2,
            "policy_ref_count", springPolicyRefs().size(),
            "cases_with_trace_records", graphCases.size(),
            "cases_with_review_sessions", graphCases.size(),
            "cases_with_policy_refs", graphCases.size()
        ));
        payload.put("cases", graphCases);
        payload.put("source_status", Map.of(
            "case_index", "ready",
            "agent_ops_ledger", "spring_projection",
            "review_ledger", "spring_projection",
            "policy_doctrine", "ready"
        ));
        return payload;
    }

    @GetMapping(value = "/api/park/policy-doctrine", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> policyDoctrine() {
        Map<String, Object> payload = orderedMap();
        payload.put("status", "ready");
        payload.put("mode", "policy_doctrine_index_spring");
        payload.put("runtime", "java_spring");
        payload.put("policy_book_count", 1);
        payload.put("action_case_count", springPolicyCases().size());
        payload.put("action_primitive_count", 4);
        payload.put("policy_refs", springPolicyRefs());
        payload.put("action_cases", springPolicyCases());
        payload.put("absolute_prohibitions", List.of("No automated dispatch for medical, security, evacuation, accessibility, or staff-certification actions without human approval."));
        return payload;
    }

    @GetMapping(value = "/api/park/policy-doctrine/{policyRef}", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> policyDoctrineDetail(@PathVariable String policyRef) {
        Map<String, Object> match = springPolicyRefs().stream()
            .filter(item -> policyRef.equals(String.valueOf(item.get("policy_ref"))))
            .findFirst()
            .orElse(Map.of("policy_ref", policyRef, "title", policyRef));
        Map<String, Object> payload = orderedMap();
        payload.put("status", "found");
        payload.put("mode", "policy_ref_detail_spring");
        payload.put("runtime", "java_spring");
        payload.put("policy_ref", policyRef);
        payload.put("match_count", 1);
        payload.put("matches", List.of(Map.of(
            "kind", "decision_rule",
            "policy_ref", policyRef,
            "policy_book_id", "PARKPULSE-SPRING-OPS",
            "title", match.get("title"),
            "condition", match.get("condition"),
            "allowed_action", match.get("allowed_action"),
            "blocked_action", match.get("blocked_action"),
            "required_evidence", List.of("state snapshot", "policy gate", "receipt id"),
            "human_review_if", List.of("safety-sensitive action", "low-confidence trace", "guest-care escalation")
        )));
        payload.put("related_cases", springPolicyCases());
        return payload;
    }

    @GetMapping(value = {"/api/park/agent-monitoring", "/api/park/agent-monitoring/deep"}, produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> agentMonitoring() {
        Map<String, Object> payload = orderedMap();
        payload.put("monitoring_id", "PP-MON-SPRING-" + Instant.now().toEpochMilli());
        payload.put("created_at", Instant.now().toString());
        payload.put("domain", "amusement_park_operations");
        payload.put("entrypoint", "java-spring-migration");
        payload.put("mode", "spring_monitoring_summary");
        payload.put("status", "ready");
        payload.put("overall_status", "review");
        payload.put("runtime", "java_spring");
        payload.put("summary", Map.of(
            "action_count", 2,
            "clear_count", 1,
            "review_count", 1,
            "blocked_count", 0,
            "open_signal_count", 2,
            "ride_count", 2,
            "queue_count", 2,
            "policy_book_count", 1,
            "overall_eval_score", 84,
            "needs_human_approval", true
        ));
        payload.put("policy_index", Map.of(
            "policy_book_id", "PARKPULSE-SPRING-OPS",
            "version", "2026-06-05",
            "active_policy_books", List.of("PARKPULSE-SPRING-OPS"),
            "absolute_prohibitions", List.of("No automated safety-sensitive dispatch without human approval.")
        ));
        payload.put("policy_integrity", Map.of("status", "ready", "issues", List.of(), "policy_ref_count", springPolicyRefs().size()));
        payload.put("supervised_actions", List.of(
            Map.of("action_id", "spring_queue_split_review", "title", "Review Dragon Coaster split-flow plan", "owner", "ops_team", "policy_status", "review", "park_action", Map.of("target", "dragon-coaster", "action", "split_flow")),
            Map.of("action_id", "spring_staff_watch", "title", "Confirm staff callout coverage", "owner", "ops_team", "policy_status", "clear", "park_action", Map.of("target", "staffing", "action", "observe"))
        ));
        payload.put("runtime_governance", Map.of(
            "decision_ledger", List.of(Map.of("id", "decision-spring-queue", "title", "Queue split requires operator review", "gateStatus", "review", "policyFindings", List.of("PARK-OPS-001"))),
            "remediation_tasks", List.of(Map.of("id", "task-spring-trace", "status", "open", "severity", "medium", "owner", "ops_team", "title", "Attach live trace receipt when dispatch executes", "requiredAction", "Keep case linked to receipt id", "policyFindings", List.of("PARK-CARE-001"))),
            "customer_care_cases", List.of()
        ));
        payload.put("deep_monitoring", Map.of("status", "spring_summary", "error", ""));
        return payload;
    }

    private Map<String, Object> springState(String auditMode) {
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
            "mode", auditMode,
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

    private static Map<String, Object> highestWaitRow(List<Object> rows) {
        Map<String, Object> best = orderedMap();
        int bestWait = -1;
        for (Object row : rows) {
            Map<String, Object> candidate = mapValue(row);
            int wait = intValue(candidate.get("waitMins"));
            if (wait > bestWait) {
                best = candidate;
                bestWait = wait;
            }
        }
        return best;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> mapValue(Object value) {
        return value instanceof Map<?, ?> ? (Map<String, Object>) value : orderedMap();
    }

    @SuppressWarnings("unchecked")
    private static List<Object> listValue(Object value) {
        return value instanceof List<?> ? (List<Object>) value : List.of();
    }

    private static int intValue(Object value) {
        if (value instanceof Number number) {
            return number.intValue();
        }
        try {
            return value == null ? 0 : Integer.parseInt(String.valueOf(value));
        } catch (NumberFormatException error) {
            return 0;
        }
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
