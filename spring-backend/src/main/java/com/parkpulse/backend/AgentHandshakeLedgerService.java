package com.parkpulse.backend;

import java.security.MessageDigest;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;

@Service
public class AgentHandshakeLedgerService {
    private final ObjectMapper objectMapper;

    public AgentHandshakeLedgerService(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    Map<String, Object> event(String actor, String action, Map<String, Object> payload) {
        return Map.of("at", now(), "actor", actor, "action", action, "payload", payload);
    }

    Map<String, Object> caseEvaluation(String caseName, Map<String, Object> criteria, Map<String, Object> evidence) {
        long passed = criteria.values().stream().filter(Boolean.TRUE::equals).count();
        Map<String, Object> result = orderedMap();
        result.put("case", caseName);
        result.put("status", passed == criteria.size() ? "passed" : "failed");
        result.put("score", criteria.isEmpty() ? 0.0 : Math.round((passed / (double) criteria.size()) * 100.0) / 100.0);
        result.put("criteria", criteria);
        result.put("evidence", evidence);
        result.put("evaluated_at", now());
        return result;
    }

    Map<String, Object> handoff(String agentId, String task, Map<String, Object> evidence, String source) {
        Map<String, Object> handoff = orderedMap();
        handoff.put("id", "handoff_" + sha1(agentId + ":" + task + ":" + System.nanoTime()).substring(0, 10));
        handoff.put("agent_id", agentId);
        handoff.put("task", task);
        handoff.put("evidence", evidence);
        handoff.put("status", "recommended");
        handoff.put("source", source);
        handoff.put("created_at", now());
        return handoff;
    }

    void recordProposalHandoffs(Map<String, Object> session, Map<String, Object> proposal, String source) {
        appendList(session, "internal_handoffs", handoff("queue_agent", "rank route by waits, downtime risk, and walking cost", Map.of("expected_wait_saved", proposal.get("expected_wait_saved"), "estimated_walking_distance", proposal.get("estimated_walking_distance")), source));
        appendList(session, "internal_handoffs", handoff("food_agent", "validate food timing and allergy-safe stop", Map.of("constraint", mapValue(mapValue(session.get("intent")).get("client_agent")).getOrDefault("constraints", Map.of())), source));
        appendList(session, "internal_handoffs", handoff("guest_experience_agent", "assemble family itinerary tradeoff", Map.of("plan", proposal.get("plan"), "confidence", proposal.get("confidence"), "tradeoffs", proposal.get("tradeoffs")), source));
    }

    Map<String, Object> recordPolicyDecision(Map<String, Object> session, String action, Map<String, Object> payload) {
        Map<String, Object> rule = policyRule(action);
        Map<String, Object> decision = orderedMap();
        decision.put("id", "ahp_policy_" + sha1(stringOrDefault(session.get("session_id"), "") + ":" + action + ":" + System.nanoTime()).substring(0, 12));
        decision.put("session_id", session.get("session_id"));
        decision.put("action", action);
        decision.put("status", rule.get("status"));
        decision.put("allowed", rule.get("allowed"));
        decision.put("requires_user_approval", rule.get("requires_user_approval"));
        decision.put("reason", rule.get("reason"));
        decision.put("created_at", now());
        decision.put("payload", payload);
        appendList(session, "policy_decisions", decision);
        appendList(session, "conversation", event("park_agent", "policy_enforcement", decision));
        return decision;
    }

    void recordDelegationFailure(Map<String, Object> session, Map<String, Object> proof) {
        Map<String, Object> decision = orderedMap();
        decision.put("id", "ahp_policy_" + sha1(stringOrDefault(session.get("session_id"), "") + ":delegation:" + System.nanoTime()).substring(0, 12));
        decision.put("session_id", session.get("session_id"));
        decision.put("action", "delegation_" + stringOrDefault(proof.get("operation"), "session"));
        decision.put("status", "blocked");
        decision.put("allowed", false);
        decision.put("requires_user_approval", true);
        decision.put("reason", stringOrDefault(proof.get("reason"), "Delegation token check failed."));
        decision.put("created_at", now());
        decision.put("payload", Map.of("delegation_proof", proof));
        appendList(session, "policy_decisions", decision);
    }

    List<Map<String, Object>> policyGateSummary(List<Object> decisions) {
        return decisions.stream().filter(Map.class::isInstance).map(this::mapValue).map(decision -> {
            Map<String, Object> summary = orderedMap();
            summary.put("action", decision.get("action"));
            summary.put("status", decision.get("status"));
            summary.put("allowed", decision.get("allowed"));
            summary.put("requires_user_approval", decision.get("requires_user_approval"));
            summary.put("reason", decision.get("reason"));
            return summary;
        }).toList();
    }

    List<Map<String, Object>> handoffSummary(List<Object> handoffs) {
        return handoffs.stream().filter(Map.class::isInstance).map(this::mapValue).map(handoff -> {
            Map<String, Object> summary = orderedMap();
            summary.put("internal_agent_id", stringOrDefault(handoff.get("internal_agent_id"), handoff.get("agent_id"), ""));
            summary.put("internal_agent", stringOrDefault(handoff.get("internal_agent"), handoff.get("agent_id"), ""));
            summary.put("trigger", stringOrDefault(handoff.get("trigger"), handoff.get("task"), ""));
            summary.put("decision", stringOrDefault(handoff.get("decision"), handoff.get("status"), ""));
            summary.put("source", handoff.get("source"));
            return summary;
        }).toList();
    }

    List<Map<String, Object>> caseEvaluationSummary(List<Object> evaluations) {
        return evaluations.stream().filter(Map.class::isInstance).map(this::mapValue).map(evaluation -> {
            Map<String, Object> summary = orderedMap();
            summary.put("case", evaluation.get("case"));
            summary.put("status", evaluation.get("status"));
            summary.put("score", evaluation.get("score"));
            return summary;
        }).toList();
    }

    String conversationDigest(List<Object> conversation) {
        return digest("SHA-256", canonicalJson(Map.of("conversation", conversation)));
    }

    String receiptSignature(Map<String, Object> receipt) {
        return "sig_" + sha1(canonicalJson(receipt)).substring(0, 24);
    }

    Map<String, Object> policyRule(String action) {
        return switch (action) {
            case "route_change" -> Map.of("status", "allowed", "allowed", true, "requires_user_approval", false, "reason", "Route changes are delegated when they do not include payment, health data, or identity-sensitive action.");
            case "wait_alert" -> Map.of("status", "allowed", "allowed", true, "requires_user_approval", false, "reason", "Wait alerts are informational updates within the client's receive scope.");
            case "food_recommendation" -> Map.of("status", "allowed", "allowed", true, "requires_user_approval", false, "reason", "Food recommendations are allowed when constrained to declared allergy preferences and public menu safety data.");
            case "safety_notice" -> Map.of("status", "allowed", "allowed", true, "requires_user_approval", false, "reason", "Safety notices are informational updates and cannot override safety controls.");
            case "priority_access" -> Map.of("status", "allowed", "allowed", true, "requires_user_approval", false, "reason", "Priority access recommendations are allowed when they only notify the user and do not bypass safety gates.");
            case "compensation_offer" -> Map.of("status", "requires_user_approval", "allowed", false, "requires_user_approval", true, "reason", "Compensation offers require user approval before acceptance.");
            case "payment", "refund", "auto_purchase", "accept_refund_without_user", "compensation_settlement" -> Map.of("status", "blocked", "allowed", false, "requires_user_approval", true, "reason", "Commerce actions require explicit user approval and cannot be executed by delegated agents.");
            default -> Map.of("status", "requires_user_approval", "allowed", false, "requires_user_approval", true, "reason", "Unknown agent action is not in the delegated handshake contract.");
        };
    }

    @SuppressWarnings("unchecked")
    private void appendList(Map<String, Object> target, String key, Object value) {
        Object existing = target.get(key);
        List<Object> list = existing instanceof List<?> source ? new ArrayList<>((List<Object>) source) : new ArrayList<>();
        list.add(value);
        target.put(key, list);
    }

    private Map<String, Object> mapValue(Object value) {
        Map<String, Object> result = orderedMap();
        if (value instanceof Map<?, ?> source) {
            source.forEach((key, item) -> result.put(String.valueOf(key), item));
        }
        return result;
    }

    private String canonicalJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception error) {
            throw new IllegalStateException("Unable to serialize agent handshake ledger.", error);
        }
    }

    private String digest(String algorithm, String value) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance(algorithm).digest(value.getBytes(java.nio.charset.StandardCharsets.UTF_8)));
        } catch (Exception error) {
            throw new IllegalStateException("Unable to hash agent handshake payload.", error);
        }
    }

    private String sha1(String value) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-1").digest(value.getBytes(java.nio.charset.StandardCharsets.UTF_8)));
        } catch (Exception error) {
            throw new IllegalStateException("Unable to hash agent handshake ledger id.", error);
        }
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

    private static String now() {
        return Instant.now().toString();
    }

    private static LinkedHashMap<String, Object> orderedMap() {
        return new LinkedHashMap<>();
    }
}
