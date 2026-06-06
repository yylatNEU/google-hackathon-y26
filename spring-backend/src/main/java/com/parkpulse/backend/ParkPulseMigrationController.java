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
    private final LiveFeedLedgerService liveFeedLedgerService;
    private final ProductLearningService productLearningService;
    private final StaffTrainingService staffTrainingService;
    private final Instant startedAt = Instant.now();

    public ParkPulseMigrationController(
        PlatformStoreService platformStoreService,
        RoleAuthService roleAuthService,
        RoleContractService roleContractService,
        AuthorizationAuditService authorizationAuditService,
        ReliabilityDiagnosticsService reliabilityDiagnosticsService,
        LiveFeedLedgerService liveFeedLedgerService,
        ProductLearningService productLearningService,
        StaffTrainingService staffTrainingService
    ) {
        this.platformStoreService = platformStoreService;
        this.roleAuthService = roleAuthService;
        this.roleContractService = roleContractService;
        this.authorizationAuditService = authorizationAuditService;
        this.reliabilityDiagnosticsService = reliabilityDiagnosticsService;
        this.liveFeedLedgerService = liveFeedLedgerService;
        this.productLearningService = productLearningService;
        this.staffTrainingService = staffTrainingService;
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
        Map<String, Object> rule = orderedMap();
        rule.put("kind", "decision_rule");
        rule.put("policy_ref", policyRef);
        rule.put("policy_book_id", "PARKPULSE-SPRING-OPS");
        rule.put("title", String.valueOf(match.getOrDefault("title", policyRef)));
        rule.put("condition", String.valueOf(match.getOrDefault("condition", "Spring policy reference is registered for monitor evidence.")));
        rule.put("allowed_action", String.valueOf(match.getOrDefault("allowed_action", "Human-reviewed operating action with linked evidence.")));
        rule.put("blocked_action", String.valueOf(match.getOrDefault("blocked_action", "Action without linked evidence.")));
        rule.put("required_evidence", List.of("state snapshot", "policy gate", "receipt id"));
        rule.put("human_review_if", List.of("safety-sensitive action", "low-confidence trace", "guest-care escalation"));
        payload.put("matches", List.of(rule));
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

    @GetMapping(value = "/api/park/live-feed-health", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> liveFeedHealth(HttpServletRequest request, @RequestParam(name = "limit", required = false) Integer limit) {
        roleAuthService.requireCapability(request, "read_ops_evidence");
        List<Map<String, Object>> feeds = springLiveFeedRows();
        List<Map<String, Object>> openReviews = springReviewRows().stream()
            .filter(item -> "open".equals(String.valueOf(item.get("status"))))
            .toList();

        Map<String, Object> payload = orderedMap();
        payload.put("status", "ready");
        payload.put("mode", "live_feed_health_and_review_contract_spring");
        payload.put("runtime", "java_spring");
        payload.put("summary", liveFeedSummary(feeds, openReviews.size()));
        payload.put("feeds", feeds.stream().limit(limit == null ? feeds.size() : Math.max(1, Math.min(limit, feeds.size()))).toList());
        payload.put("open_reviews", openReviews);
        payload.put("growth_loop", Map.of(
            "status", "supervised",
            "candidate_count", 1,
            "training_gate", "human-reviewed labels only",
            "runtime", "java_spring"
        ));
        payload.put("cache", Map.of(
            "status", "fresh",
            "source", "spring_live_feed_jsonl_ledger",
            "generated_at", Instant.now().toString()
        ));
        payload.put("ledger", liveFeedLedgerService.liveFeedLedgerStatus());
        payload.put("review_ledger", liveFeedLedgerService.reviewLedgerStatus());
        payload.put("recent_events", liveFeedLedgerService.recentLiveFeedEvents(5));
        payload.put("readiness_issues", List.of());
        return payload;
    }

    @GetMapping(value = "/api/park/live-feeds/refresh-worker", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> liveFeedRefreshWorker(HttpServletRequest request) {
        roleAuthService.requireCapability(request, "read_ops_evidence");
        Map<String, Object> payload = orderedMap();
        payload.put("status", "ready");
        payload.put("mode", "live_feed_refresh_worker_spring");
        payload.put("runtime", "java_spring");
        payload.put("enabled", false);
        payload.put("worker_runtime", "spring_projection_only");
        payload.put("last_run_at", null);
        payload.put("next_run_at", null);
        payload.put("readiness_issues", List.of("Automatic external feed refresh remains disabled until provider credentials are configured for Spring."));
        return payload;
    }

    @PostMapping(value = "/api/park/live-feeds/refresh-stale", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> refreshStaleLiveFeeds(HttpServletRequest request, @RequestBody(required = false) Map<String, Object> body) {
        roleAuthService.requireCapability(request, "run_live_outcome_cycle");
        List<Map<String, Object>> feeds = springLiveFeedRows();
        Map<String, Object> before = liveFeedSummary(feeds, 1);
        List<Map<String, Object>> afterFeeds = feeds.stream()
            .map(feed -> {
                Map<String, Object> updated = orderedMap();
                updated.putAll(feed);
                updated.put("age_seconds", Math.min(30, intValue(feed.get("age_seconds"))));
                updated.put("status", "ready");
                return updated;
            })
            .toList();

        Map<String, Object> payload = orderedMap();
        payload.put("status", "ready");
        payload.put("mode", "live_feed_refresh_supervisor_spring");
        payload.put("runtime", "java_spring");
        payload.put("requested_sources", body == null ? List.of() : body.getOrDefault("sources", List.of()));
        payload.put("refreshed_sources", List.of("weather", "ride-ops", "guest-flow"));
        payload.put("queued_sources", List.of("staffing", "food-ops", "operator-signal"));
        payload.put("readiness_issues", List.of());
        payload.put("remaining_issues", List.of("External provider writes are still projected until live provider clients move into Spring."));
        payload.put("before", before);
        payload.put("after", liveFeedSummary(afterFeeds, 1));
        payload.put("after_feeds", afterFeeds);
        payload.put("durability", liveFeedLedgerService.recordRefreshSupervisor(payload));
        return payload;
    }

    @GetMapping(value = "/api/park/live-feeds/{source}", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> liveFeedConfig(HttpServletRequest request, @PathVariable String source) {
        roleAuthService.requireCapability(request, "read_ops_evidence");
        String normalizedSource = normalizeFeedSource(source);
        Map<String, Object> payload = orderedMap();
        payload.put("status", "ready");
        payload.put("mode", "live_" + normalizedSource.replace("-", "_") + "_feed_config_spring");
        payload.put("runtime", "java_spring");
        payload.put("config", springFeedConfig(normalizedSource));
        return payload;
    }

    @PostMapping(value = "/api/park/live-feeds/{source}/load", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> loadLiveFeed(
        HttpServletRequest request,
        @PathVariable String source,
        @RequestBody(required = false) Map<String, Object> body
    ) {
        roleAuthService.requireCapability(request, "run_live_outcome_cycle");
        String normalizedSource = normalizeFeedSource(source);
        Map<String, Object> payload = orderedMap();
        payload.put("status", "loaded");
        payload.put("mode", "live_" + normalizedSource.replace("-", "_") + "_feed_load_spring");
        payload.put("runtime", "java_spring");
        payload.put("provider", "spring_projection");
        payload.put("source", normalizedSource);
        payload.put("event_count", eventCountForFeed(normalizedSource));
        payload.put("loaded_at", Instant.now().toString());
        Map<String, Object> config = springFeedConfig(normalizedSource);
        payload.put("fetch", Map.of(
            "fetched_at", Instant.now().toString(),
            "config", config,
            "request", body == null ? Map.of() : body
        ));
        payload.put("durability", liveFeedLedgerService.recordFeedLoad(normalizedSource, body, eventCountForFeed(normalizedSource), config));
        payload.put("readiness_issues", List.of());
        return payload;
    }

    @PostMapping(value = "/api/park/live-feed-events", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> recordLiveFeedEvents(HttpServletRequest request, @RequestBody(required = false) Map<String, Object> body) {
        roleAuthService.requireCapability(request, "run_live_outcome_cycle");
        return liveFeedLedgerService.recordLiveFeedEvents(body);
    }

    @GetMapping(value = "/api/park/review-training-ledger", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> reviewTrainingLedger(HttpServletRequest request, @RequestParam(name = "limit", required = false) Integer limit) {
        roleAuthService.requireCapability(request, "read_ops_evidence");
        List<Map<String, Object>> rows = new java.util.ArrayList<>(springReviewRows());
        rows.addAll(liveFeedLedgerService.reviewRows(100));
        List<Map<String, Object>> limitedRows = rows.stream()
            .limit(limit == null ? rows.size() : Math.max(1, Math.min(limit, rows.size())))
            .toList();
        Map<String, Object> payload = orderedMap();
        payload.put("status", "ready");
        payload.put("mode", "review_training_ledger_spring");
        payload.put("runtime", "java_spring");
        payload.put("summary", Map.of(
            "open_count", rows.stream().filter(item -> "open".equals(String.valueOf(item.get("status")))).count(),
            "closed_count", rows.stream().filter(item -> !"open".equals(String.valueOf(item.get("status")))).count(),
            "training_candidate_count", rows.stream().filter(item -> Boolean.TRUE.equals(item.get("training_candidate"))).count()
        ));
        payload.put("rows", limitedRows);
        payload.put("open_reviews", rows.stream().filter(item -> "open".equals(String.valueOf(item.get("status")))).toList());
        payload.put("closed_reviews", rows.stream().filter(item -> !"open".equals(String.valueOf(item.get("status")))).toList());
        payload.put("training_rule", Map.of(
            "eligible_after", "closed_human_review",
            "blocked_if", List.of("safety_sensitive_without_approval", "missing_policy_reference"),
            "runtime", "java_spring"
        ));
        payload.put("ledger", liveFeedLedgerService.reviewLedgerStatus());
        payload.put("readiness_issues", List.of());
        return payload;
    }

    @PostMapping(value = "/api/park/review-training-ledger", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> recordReviewTrainingDecision(HttpServletRequest request, @RequestBody(required = false) Map<String, Object> body) {
        roleAuthService.requireCapability(request, "run_live_outcome_cycle");
        return liveFeedLedgerService.recordReviewDecision(body);
    }

    @GetMapping(value = "/api/park/product-learning/loop", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> productLearningLoop(HttpServletRequest request, @RequestParam(name = "limit", required = false) Integer limit) {
        roleAuthService.requireCapability(request, "read_product_learning");
        return productLearningService.loopStatus(limit == null ? 500 : limit);
    }

    @PostMapping(value = "/api/park/product-learning/issue-ticket", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> createProductLearningIssueTicket(HttpServletRequest request, @RequestBody(required = false) Map<String, Object> body) {
        roleAuthService.requireCapability(request, "create_park_issue_ticket");
        return productLearningService.createParkIssueTicket(body);
    }

    @PostMapping(value = "/api/park/product-learning/training-gap-ticket", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> createProductLearningTrainingGapTicket(HttpServletRequest request, @RequestBody(required = false) Map<String, Object> body) {
        roleAuthService.requireCapability(request, "create_training_gap_ticket");
        return productLearningService.createTrainingGapTicket(body);
    }

    @GetMapping(value = "/api/park/staff-training/scenarios", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> staffTrainingScenarios(HttpServletRequest request) {
        roleAuthService.requireCapability(request, "read_staff_training");
        return staffTrainingService.scenarios();
    }

    @GetMapping(value = "/api/park/staff-training/policy-pack", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> staffTrainingPolicyPack(HttpServletRequest request) {
        roleAuthService.requireCapability(request, "read_staff_training_analytics");
        return staffTrainingService.policyPack();
    }

    @GetMapping(value = "/api/park/staff-training/assignments", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> staffTrainingAssignments(HttpServletRequest request, @RequestParam(name = "limit", required = false) Integer limit) {
        roleAuthService.requireCapability(request, "read_staff_training_analytics");
        return staffTrainingService.assignments(limit == null ? 200 : limit);
    }

    @PostMapping(value = "/api/park/staff-training/assignments", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> createStaffTrainingAssignment(HttpServletRequest request, @RequestBody(required = false) Map<String, Object> body) {
        roleAuthService.requireCapability(request, "read_staff_training_analytics");
        return staffTrainingService.createAssignment(body);
    }

    @GetMapping(value = "/api/park/staff-training/readiness", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> staffTrainingReadiness(HttpServletRequest request, @RequestParam(name = "limit", required = false) Integer limit) {
        roleAuthService.requireCapability(request, "read_staff_training_analytics");
        return staffTrainingService.readiness(limit == null ? 500 : limit);
    }

    @GetMapping(value = "/api/park/staff-training/receipts", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> staffTrainingReceipts(HttpServletRequest request, @RequestParam(name = "limit", required = false) Integer limit) {
        roleAuthService.requireCapability(request, "read_staff_training_analytics");
        return staffTrainingService.receipts(limit == null ? 80 : limit);
    }

    @GetMapping(value = "/api/park/staff-training/certification-packet", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> staffTrainingCertificationPacket(
        HttpServletRequest request,
        @RequestParam(name = "assignment_id", required = false) String assignmentId,
        @RequestParam(name = "assignmentId", required = false) String assignmentIdCamel,
        @RequestParam(name = "trainee_name", required = false) String traineeName,
        @RequestParam(name = "traineeName", required = false) String traineeNameCamel
    ) {
        roleAuthService.requireCapability(request, "read_staff_training_analytics");
        return staffTrainingService.certificationPacket(firstNonBlank(assignmentId, assignmentIdCamel), firstNonBlank(traineeName, traineeNameCamel));
    }

    @PostMapping(value = "/api/park/staff-training/receipt-review", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> reviewStaffTrainingReceipt(HttpServletRequest request, @RequestBody(required = false) Map<String, Object> body) {
        roleAuthService.requireCapability(request, "read_staff_training_analytics");
        return staffTrainingService.reviewReceipt(body);
    }

    @PostMapping(value = "/api/park/staff-training/demo-seed", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> seedStaffTrainingDemo(HttpServletRequest request) {
        roleAuthService.requireCapability(request, "read_staff_training_analytics");
        return staffTrainingService.seedDemoData();
    }

    @GetMapping(value = "/api/park/staff-training/golden-eval", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> staffTrainingGoldenEval(HttpServletRequest request) {
        roleAuthService.requireCapability(request, "read_staff_training_analytics");
        return staffTrainingService.goldenEval();
    }

    @PostMapping(value = "/api/park/staff-training/sessions", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> startStaffTrainingSession(HttpServletRequest request, @RequestBody(required = false) Map<String, Object> body) {
        roleAuthService.requireCapability(request, "use_staff_training");
        return staffTrainingService.startSession(body);
    }

    @PostMapping(value = "/api/park/staff-training/turn", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> advanceStaffTrainingTurn(HttpServletRequest request, @RequestBody(required = false) Map<String, Object> body) {
        roleAuthService.requireCapability(request, "use_staff_training");
        return staffTrainingService.advanceTurn(body);
    }

    @PostMapping(value = "/api/park/staff-training/finish", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> finishStaffTrainingSession(HttpServletRequest request, @RequestBody(required = false) Map<String, Object> body) {
        roleAuthService.requireCapability(request, "use_staff_training");
        return staffTrainingService.finishSession(body);
    }

    @GetMapping(value = "/api/park/staff-training/analytics", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> staffTrainingAnalytics(HttpServletRequest request, @RequestParam(name = "limit", required = false) Integer limit) {
        roleAuthService.requireCapability(request, "read_staff_training_analytics");
        return staffTrainingService.analytics(limit == null ? 200 : limit);
    }

    private Map<String, Object> liveFeedSummary(List<Map<String, Object>> feeds, int openReviewCount) {
        long readyCount = feeds.stream().filter(item -> "ready".equals(String.valueOf(item.get("status")))).count();
        Map<String, Object> payload = orderedMap();
        payload.put("required_feed_count", feeds.size());
        payload.put("ready_feed_count", readyCount);
        payload.put("missing_or_weak_feed_count", feeds.size() - readyCount);
        payload.put("open_review_count", openReviewCount);
        return payload;
    }

    private List<Map<String, Object>> springLiveFeedRows() {
        return List.of(
            liveFeedRow("weather", "Weather", "ops_team", "ready", 24, 300, 0.94, "weather_observation", Map.of("temperatureF", 82, "stormRisk", 18)),
            liveFeedRow("ride-ops", "Ride operations", "ops_team", "ready", 18, 120, 0.91, "ride_wait_snapshot", Map.of("rideId", "dragon-coaster", "waitMins", 42)),
            liveFeedRow("guest-flow", "Guest flow", "ops_team", "ready", 21, 120, 0.88, "zone_density_snapshot", Map.of("zoneId", "covered-plaza", "density", 72)),
            liveFeedRow("staffing", "Staffing", "ops_team", "ready", 52, 300, 0.87, "coverage_snapshot", Map.of("checkedIn", 128, "openCallouts", 4)),
            liveFeedRow("food-ops", "Food operations", "ops_team", "ready", 66, 300, 0.82, "venue_queue_snapshot", Map.of("venueId", "north-market", "waitMins", 11)),
            liveFeedRow("operator-signal", "Operator signal", "ops_team", "ready", 12, 180, 0.9, "operator_note", Map.of("priority", "watch", "caseId", "spring_queue_pressure"))
        );
    }

    private Map<String, Object> liveFeedRow(
        String source,
        String label,
        String owner,
        String status,
        int ageSeconds,
        int maxStaleSeconds,
        double confidence,
        String latestSignalType,
        Map<String, Object> value
    ) {
        Map<String, Object> payload = orderedMap();
        payload.put("source", source);
        payload.put("label", label);
        payload.put("owner", owner);
        payload.put("status", status);
        payload.put("age_seconds", ageSeconds);
        payload.put("max_stale_seconds", maxStaleSeconds);
        payload.put("confidence", confidence);
        payload.put("latest_signal_type", latestSignalType);
        payload.put("readiness_issues", List.of());
        payload.put("value", value);
        return payload;
    }

    private List<Map<String, Object>> springReviewRows() {
        return List.of(
            reviewRow("review-spring-queue", "spring_queue_pressure", "open", "ops_team", false, "Queue split-flow action needs operator approval before dispatch."),
            reviewRow("review-spring-weather", "spring_weather_watch", "closed", "ops_team", true, "Weather signal accepted for supervised training candidate.")
        );
    }

    private Map<String, Object> reviewRow(String reviewId, String caseId, String status, String owner, boolean trainingCandidate, String reason) {
        Map<String, Object> payload = orderedMap();
        payload.put("review_session_id", reviewId);
        payload.put("case_id", caseId);
        payload.put("status", status);
        payload.put("owner", owner);
        payload.put("training_candidate", trainingCandidate);
        payload.put("reason", reason);
        payload.put("updated_at", Instant.now().toString());
        return payload;
    }

    private Map<String, Object> springFeedConfig(String source) {
        Map<String, Object> payload = orderedMap();
        payload.put("source", source);
        payload.put("location_label", "ParkPulse Demo Park");
        payload.put("provider", "spring_projection");
        payload.put("owner", "ops_team");
        payload.put("max_stale_seconds", maxStaleSecondsForFeed(source));
        payload.put("refresh_policy", "operator_triggered_until_provider_credentials_are_configured");
        payload.put("schema_version", "live-feed.v1");
        return payload;
    }

    private String normalizeFeedSource(String source) {
        if (source == null || source.isBlank()) {
            return "weather";
        }
        return switch (source) {
            case "ride-ops", "guest-flow", "staffing", "food-ops", "operator-signal", "weather" -> source;
            default -> source.toLowerCase().replace('_', '-');
        };
    }

    private int maxStaleSecondsForFeed(String source) {
        return switch (source) {
            case "ride-ops", "guest-flow" -> 120;
            case "operator-signal" -> 180;
            default -> 300;
        };
    }

    private int eventCountForFeed(String source) {
        return switch (source) {
            case "weather" -> 3;
            case "ride-ops", "guest-flow" -> 5;
            default -> 4;
        };
    }

    private List<Map<String, Object>> springCaseRows() {
        return List.of(
            caseRow(
                "spring_queue_pressure",
                "Dragon Coaster queue pressure",
                "guest_flow",
                "watch",
                0.86,
                1,
                72,
                "Dragon Coaster wait is materially above adjacent ride waits while Covered Plaza density is rising.",
                "operator_review",
                "Review split-flow and staff positioning before dispatch.",
                "spring_packet_queue_001"
            ),
            caseRow(
                "spring_staff_readiness",
                "Staff callout coverage watch",
                "staffing",
                "normal",
                0.78,
                2,
                61,
                "Open callouts are still inside operating tolerance but should be watched before the next demand peak.",
                "observe",
                "Confirm ride ops and guest-care coverage at the next operating check.",
                "spring_packet_staff_001"
            )
        );
    }

    private Map<String, Object> caseRow(
        String id,
        String title,
        String domain,
        String severity,
        double qualityScore,
        int rank,
        int priorityScore,
        String rationale,
        String allowedSurface,
        String nextOwnerAction,
        String packetHash
    ) {
        Map<String, Object> payload = orderedMap();
        payload.put("id", id);
        payload.put("title", title);
        payload.put("domain", domain);
        payload.put("severity", severity);
        payload.put("quality", Map.of("status", "measured", "score", qualityScore));
        payload.put("priority", Map.of("rank", rank, "score", priorityScore, "rationale", rationale));
        payload.put("governance", Map.of(
            "allowedSurface", allowedSurface,
            "blockerClasses", List.of("human_approval_required_for_dispatch"),
            "nextOwnerAction", nextOwnerAction
        ));
        payload.put("productionEvidence", Map.of(
            "state", "spring_state_projection",
            "feedCount", 4,
            "packetHash", packetHash
        ));
        return payload;
    }

    private List<Map<String, Object>> springPolicyRefs() {
        return List.of(
            policyRef("PARK-SAFE-001", "Safety-sensitive dispatch boundary", "Human approval is required before safety-sensitive guest, worker, equipment, medical, security, or evacuation action.", "No autonomous safety dispatch", "critical"),
            policyRef("PARK-OPS-001", "Guest-flow operating action", "Queue balancing is allowed only with current state, staff coverage, and rollback observation.", "Split-flow or staff review after evidence check", "review"),
            policyRef("PARK-CARE-001", "Guest-care traceability", "Guest-facing recovery requires receipt, owner, and outcome evidence.", "Guest-care review with linked receipt", "review")
        );
    }

    private Map<String, Object> policyRef(String ref, String title, String condition, String allowedAction, String severity) {
        Map<String, Object> payload = orderedMap();
        payload.put("policy_ref", ref);
        payload.put("policy_book_id", "PARKPULSE-SPRING-OPS");
        payload.put("title", title);
        payload.put("summary", allowedAction);
        payload.put("severity", severity);
        payload.put("condition", condition);
        payload.put("allowed_action", allowedAction);
        payload.put("blocked_action", severity.equals("critical") ? "Automated dispatch without human approval" : "Action without linked evidence");
        return payload;
    }

    private List<Map<String, Object>> springPolicyCases() {
        return List.of(
            policyCase(
                "spring_queue_pressure",
                "Dragon Coaster queue pressure",
                List.of("wait above adjacent rides", "covered plaza density rising"),
                List.of("dragon-coaster wait", "covered-plaza density", "staff readiness"),
                List.of("PARK-OPS-001", "PARK-CARE-001"),
                List.of("split_flow_review", "staff_position_review"),
                "Queue wait reduces without creating unsafe density in adjacent zones.",
                "Queue or plaza density worsens after 5 minutes."
            ),
            policyCase(
                "spring_staff_readiness",
                "Staff callout coverage watch",
                List.of("open staff callouts", "next peak approaching"),
                List.of("checked in staff", "open callouts", "coverage ratio"),
                List.of("PARK-SAFE-001", "PARK-OPS-001"),
                List.of("coverage_observe", "manager_review"),
                "Coverage remains above operating threshold.",
                "Callouts exceed threshold or safety-sensitive post becomes uncovered."
            )
        );
    }

    private Map<String, Object> policyCase(
        String id,
        String title,
        List<String> triggers,
        List<String> stateSignals,
        List<String> policyRefs,
        List<String> recommendedPrimitives,
        String successMetric,
        String rollbackCondition
    ) {
        Map<String, Object> payload = orderedMap();
        payload.put("id", id);
        payload.put("title", title);
        payload.put("triggers", triggers);
        payload.put("state_signals", stateSignals);
        payload.put("policy_refs", policyRefs);
        payload.put("recommended_primitives", recommendedPrimitives);
        payload.put("action_plan", List.of("read state", "check policy", "require human review before dispatch", "record receipt"));
        payload.put("blocked_actions", List.of("safety-sensitive automation without approval", "dispatch without receipt"));
        payload.put("success_metric", successMetric);
        payload.put("rollback_condition", rollbackCondition);
        return payload;
    }

    private List<Map<String, Object>> springMonitorEvidenceCases(String caseId) {
        return springCaseRows().stream()
            .filter(item -> caseId == null || caseId.isBlank() || caseId.equals(String.valueOf(item.get("id"))))
            .map(this::springMonitorEvidenceCase)
            .toList();
    }

    private Map<String, Object> springMonitorEvidenceCase(Map<String, Object> caseRow) {
        String caseId = String.valueOf(caseRow.get("id"));
        boolean queueCase = "spring_queue_pressure".equals(caseId);
        List<String> policyRefs = queueCase ? List.of("PARK-OPS-001", "PARK-CARE-001") : List.of("PARK-SAFE-001", "PARK-OPS-001");
        String receiptId = queueCase ? "receipt-spring-queue" : "receipt-spring-staff";
        String traceId = queueCase ? "trace-spring-queue" : "trace-spring-staff";
        String reviewId = queueCase ? "review-spring-queue" : "review-spring-staff";

        Map<String, Object> payload = orderedMap();
        payload.put("case_id", caseId);
        payload.put("caseId", caseId);
        payload.put("policy_case_id", caseId);
        payload.put("policy_refs", policyRefs);
        payload.put("policy_ref_rows", springPolicyRefs().stream().filter(item -> policyRefs.contains(String.valueOf(item.get("policy_ref")))).toList());
        payload.put("receipt_ids", List.of(receiptId));
        payload.put("trace_ids", List.of(traceId));
        payload.put("review_session_ids", List.of(reviewId));
        payload.put("trace_records", List.of(traceRecord(caseId, receiptId, traceId, policyRefs, queueCase)));
        payload.put("review_sessions", List.of(reviewSession(caseId, reviewId, queueCase)));
        payload.put("eval_dimensions", List.of(
            Map.of("id", "safety_policy", "label", "Safety and policy", "score", queueCase ? 86 : 82, "status", "linked", "detail", "Spring policy doctrine is linked to this case."),
            Map.of("id", "trace_completeness", "label", "Trace completeness", "score", 78, "status", "spring_projection", "detail", "Case, trace, review, and policy references are linked in Spring.")
        ));
        payload.put("outcome_evidence", Map.of(
            "status", "dispatch_contract_only",
            "dispatch_count", queueCase ? 1 : 0,
            "receiver_actions", queueCase ? List.of("split_flow_review", "staff_position_review") : List.of("coverage_observe"),
            "latest", Map.of("dispatchStatus", "review_required", "receiverAckCount", 0)
        ));
        payload.put("relationship_contract", Map.of(
            "case_id", caseId,
            "trace_id_source", "spring trace projection",
            "review_session_id_source", "spring review projection",
            "policy_ref_source", "spring policy doctrine",
            "explicit_receipt_links", 1,
            "explicit_review_links", 1,
            "inferred_receipt_links", 0,
            "inferred_review_links", 0,
            "semantic_threshold", "Spring emits explicit case IDs for monitor evidence links."
        ));
        return payload;
    }

    private Map<String, Object> traceRecord(String caseId, String receiptId, String traceId, List<String> policyRefs, boolean queueCase) {
        Map<String, Object> payload = orderedMap();
        payload.put("receipt_id", receiptId);
        payload.put("case_id", caseId);
        payload.put("policy_case_id", caseId);
        payload.put("policy_refs", policyRefs);
        payload.put("receipt_policy_refs", policyRefs);
        payload.put("case_policy_refs", policyRefs);
        payload.put("policy_ref_rows", springPolicyRefs().stream().filter(item -> policyRefs.contains(String.valueOf(item.get("policy_ref")))).toList());
        payload.put("policy_link_source", "spring explicit policy refs");
        payload.put("trace_id", traceId);
        payload.put("trace_url", null);
        payload.put("signature", "spring-signature-" + caseId);
        payload.put("relation_type", "explicit_case_id");
        payload.put("relation_confidence", "direct");
        payload.put("hard_match", true);
        payload.put("relation_score", 100);
        payload.put("case_link_source", "spring_case_projection");
        payload.put("case_link_confidence", 1.0);
        payload.put("eval_score", queueCase ? 86 : 78);
        payload.put("gate", queueCase ? "review" : "clear");
        payload.put("tool_count", 3);
        payload.put("summary", queueCase ? "Spring linked queue-pressure case to policy and review evidence." : "Spring linked staffing readiness case to policy and review evidence.");
        return payload;
    }

    private Map<String, Object> reviewSession(String caseId, String reviewId, boolean queueCase) {
        Map<String, Object> payload = orderedMap();
        payload.put("review_session_id", reviewId);
        payload.put("case_id", caseId);
        payload.put("status", queueCase ? "open" : "watch");
        payload.put("priority", queueCase ? "medium" : "low");
        payload.put("owner", "ops_team");
        payload.put("reason", queueCase ? "Operator review is required before split-flow dispatch." : "Coverage remains inside threshold but should be checked.");
        payload.put("relation_type", "explicit_case_id");
        payload.put("relation_confidence", "direct");
        payload.put("hard_match", true);
        payload.put("relation_score", 100);
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

    private static String firstNonBlank(String... values) {
        for (String value : values) {
            if (value != null && !value.isBlank()) {
                return value;
            }
        }
        return null;
    }
}
