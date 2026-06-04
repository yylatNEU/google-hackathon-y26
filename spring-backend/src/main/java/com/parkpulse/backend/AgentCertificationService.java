package com.parkpulse.backend;

import java.security.MessageDigest;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;
import org.springframework.stereotype.Service;

@Service
public class AgentCertificationService {
    private static final List<String> CERTIFICATION_REQUIRED_CASES = List.of("identity_trust", "capability_scope", "commerce_payment_probe", "queue_reroute");
    private static final List<String> CLIENT_ALLOWED_TO_SHARE = List.of("accessibility_needs", "budget", "location", "party_size", "preferences", "ride_preference");
    private static final List<String> CLIENT_ALLOWED_TO_RECEIVE = List.of("compensation_offer", "food_recommendation", "route_plan", "safety_notice", "wait_time_alert");
    private static final List<String> CLIENT_BLOCKED_ACTIONS = List.of("accept_refund_without_user", "auto_purchase", "share_health_data");

    private final AgentTrustService agentTrustService;
    private final AgentHandshakeService agentHandshakeService;

    public AgentCertificationService(AgentTrustService agentTrustService, AgentHandshakeService agentHandshakeService) {
        this.agentTrustService = agentTrustService;
        this.agentHandshakeService = agentHandshakeService;
    }

    public Map<String, Object> certify(String agentId, Map<String, Object> payload) {
        Map<String, Object> record = mapValue(agentTrustService.getOnboarding(agentId).get("agent"));
        if (record.isEmpty()) {
            throw new NoSuchElementException("Unknown onboarded agent: " + agentId);
        }

        List<String> requestedScopes = withDefault(
            normalizedScopes(payload.get("requested_scopes"), payload.get("requestedScopes"), payload.get("scope")),
            normalizedScopes(record.get("requested_scopes"))
        );
        List<String> cannotDo = withDefault(
            normalizedScopes(payload.get("cannot_do"), payload.get("cannotDo")),
            withDefault(normalizedScopes(record.get("cannot_do")), CLIENT_BLOCKED_ACTIONS)
        );
        String representedGuest = stringOrDefault(payload.get("represents"), record.get("represents"), "guest_user_123");
        Map<String, Object> partner = mapValue(record.get("partner"));
        List<String> partnerAllowedScopes = withDefault(normalizedScopes(partner.get("allowed_scopes")), requestedScopes);
        List<String> partnerDisallowedScopes = requestedScopes.stream().filter(scope -> !partnerAllowedScopes.contains(scope)).sorted().toList();
        String certificationId = "cert_" + sha1(agentId + ":" + System.nanoTime()).substring(0, 12);
        List<String> readinessIssues = new ArrayList<>();
        Map<String, Object> session = null;

        if (partnerDisallowedScopes.isEmpty()) {
            try {
                Map<String, Object> token = mapValue(agentTrustService.issueDelegationToken(Map.of(
                    "subject", representedGuest,
                    "agent_id", agentId,
                    "scope", requestedScopes,
                    "cannot_do", cannotDo,
                    "ttl_seconds", longParam(payload.get("ttl_seconds"), payload.get("ttlSeconds"), 600)
                )).get("token"));
                Map<String, Object> identity = agentHandshakeService.identityHandshake(Map.of(
                    "agent_id", agentId,
                    "represents", representedGuest,
                    "proof", "signed_token",
                    "requested_session", certificationId,
                    "delegation_token", token
                ));
                session = mapValue(identity.get("session"));
                String sessionId = stringOrDefault(session.get("session_id"), "");

                agentHandshakeService.capabilityHandshake(sessionId, Map.of(
                    "can_share", requestedScopes.stream().filter(CLIENT_ALLOWED_TO_SHARE::contains).sorted().toList(),
                    "can_receive", requestedScopes.stream().filter(CLIENT_ALLOWED_TO_RECEIVE::contains).sorted().toList(),
                    "cannot_do", cannotDo,
                    "delegation_token", token
                ));
                agentHandshakeService.intentHandshake(sessionId, Map.of(
                    "goal", "maximize_family_satisfaction",
                    "time_window", "3_hours",
                    "constraints", Map.of("children", 2, "avoid_wait_over_minutes", 35, "avoid_thrill_rides", true, "food_allergy", "peanut"),
                    "delegation_token", token
                ));
                agentHandshakeService.proposePlan(sessionId, Map.of("planner", "agent_onboarding_certification", "delegation_token", token));
                agentHandshakeService.queueAgentReroute(Map.of(
                    "session_id", sessionId,
                    "walking_priority", "highest",
                    "reason", "Certification reroute proof.",
                    "delegation_token", token
                ));
                agentHandshakeService.commerceAgentEvaluate(Map.of(
                    "session_id", sessionId,
                    "action", "payment",
                    "amount", 1,
                    "reason", "Certification payment boundary proof.",
                    "delegation_token", token
                ));
                session = mapValue(agentHandshakeService.getSession(sessionId).get("session"));
            } catch (RuntimeException error) {
                readinessIssues.add(error.getMessage() == null ? error.getClass().getSimpleName() : error.getMessage());
            }
        } else {
            readinessIssues.add("Partner allowlist does not permit requested scope: " + String.join(", ", partnerDisallowedScopes) + ".");
        }

        Map<String, Object> summary = certificationSummary(session);
        boolean approved = "passed".equals(summary.get("status"));
        Map<String, Object> certification = orderedMap();
        certification.put("certification_id", certificationId);
        certification.put("status", approved ? "approved" : "blocked");
        certification.put("approval", approved ? "approved_for_guest_route_planning" : "blocked_until_scope_fixed");
        certification.put("score", summary.get("score"));
        certification.put("required_cases", summary.get("required_cases"));
        certification.put("passed_cases", summary.get("passed_cases"));
        certification.put("allowed_scopes", approved ? requestedScopes : List.of());
        certification.put("partner_allowed_scopes", partnerAllowedScopes);
        certification.put("partner_disallowed_scopes", partnerDisallowedScopes);
        certification.put("readiness_issues", readinessIssues);
        certification.put("session_id", session == null ? null : session.get("session_id"));
        certification.put("certified_at", Instant.now().toString());
        certification.put("credential", approved ? agentTrustService.issueCertificationCredential(agentId, certification, requestedScopes) : null);

        record.put("status", certification.get("status"));
        record.put("approval", certification.get("approval"));
        record.put("requested_scopes", requestedScopes);
        record.put("allowed_scopes", certification.get("allowed_scopes"));
        record.put("cannot_do", cannotDo);
        record.put("certification", certification);
        agentTrustService.updateOnboardingRecord(agentId, record, "agent_onboarding_certify");

        Map<String, Object> result = orderedMap();
        result.put("status", certification.get("status"));
        result.put("agent", record);
        result.put("certification", certification);
        result.put("session", session);
        result.put("runtime", "java_spring");
        return result;
    }

    private Map<String, Object> certificationSummary(Map<String, Object> session) {
        Map<String, Object> required = orderedMap();
        Map<String, Object> latestByCase = orderedMap();
        for (Object item : listValue(session == null ? null : session.get("case_evaluations"))) {
            Map<String, Object> evaluation = mapValue(item);
            String caseName = stringOrDefault(evaluation.get("case"), "");
            if (!caseName.isBlank()) {
                latestByCase.put(caseName, evaluation);
            }
        }
        List<String> passedCases = new ArrayList<>();
        for (String caseName : CERTIFICATION_REQUIRED_CASES) {
            Map<String, Object> evaluation = mapValue(latestByCase.get(caseName));
            Map<String, Object> caseSummary = orderedMap();
            caseSummary.put("status", stringOrDefault(evaluation.get("status"), "missing"));
            caseSummary.put("score", evaluation.getOrDefault("score", 0));
            caseSummary.put("criteria", evaluation.get("criteria"));
            required.put(caseName, caseSummary);
            if ("passed".equals(caseSummary.get("status"))) {
                passedCases.add(caseName);
            }
        }
        Map<String, Object> summary = orderedMap();
        summary.put("required_cases", required);
        summary.put("passed_cases", passedCases);
        summary.put("score", Math.round((passedCases.size() / (double) CERTIFICATION_REQUIRED_CASES.size()) * 100.0) / 100.0);
        summary.put("status", passedCases.size() == CERTIFICATION_REQUIRED_CASES.size() ? "passed" : "failed");
        return summary;
    }

    private List<String> normalizedScopes(Object... candidates) {
        for (Object candidate : candidates) {
            if (candidate instanceof List<?> list) {
                return list.stream().map(String::valueOf).map(String::trim).filter(item -> !item.isBlank()).distinct().sorted().toList();
            }
            if (candidate instanceof String value && !value.isBlank()) {
                return List.of(value.split(",")).stream().map(String::trim).filter(item -> !item.isBlank()).distinct().sorted().toList();
            }
        }
        return List.of();
    }

    private List<String> withDefault(List<String> values, List<String> fallback) {
        return values.isEmpty() ? fallback : values;
    }

    @SuppressWarnings("unchecked")
    private List<Object> listValue(Object value) {
        if (value instanceof List<?> list) {
            return new ArrayList<>((List<Object>) list);
        }
        return List.of();
    }

    private Map<String, Object> mapValue(Object value) {
        Map<String, Object> result = orderedMap();
        if (value instanceof Map<?, ?> source) {
            source.forEach((key, item) -> result.put(String.valueOf(key), item));
        }
        return result;
    }

    private long longParam(Object first, Object second, long defaultValue) {
        for (Object value : new Object[] {first, second}) {
            if (value instanceof Number number) {
                return number.longValue();
            }
            if (value != null && !String.valueOf(value).isBlank()) {
                try {
                    return Long.parseLong(String.valueOf(value));
                } catch (NumberFormatException ignored) {
                    return defaultValue;
                }
            }
        }
        return defaultValue;
    }

    private String stringOrDefault(Object first, Object second, String defaultValue) {
        for (Object value : new Object[] {first, second}) {
            if (value != null && !String.valueOf(value).isBlank()) {
                return String.valueOf(value);
            }
        }
        return defaultValue;
    }

    private String stringOrDefault(Object first, String defaultValue) {
        return stringOrDefault(first, null, defaultValue);
    }

    private String sha1(String value) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-1").digest(value.getBytes(java.nio.charset.StandardCharsets.UTF_8)));
        } catch (Exception error) {
            throw new IllegalStateException("Unable to hash certification id.", error);
        }
    }

    private static LinkedHashMap<String, Object> orderedMap() {
        return new LinkedHashMap<>();
    }
}
