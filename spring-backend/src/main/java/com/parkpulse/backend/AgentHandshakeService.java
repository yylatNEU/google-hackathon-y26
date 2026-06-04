package com.parkpulse.backend;

import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Service;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

@Service
public class AgentHandshakeService {
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};
    private static final List<String> CLIENT_ALLOWED_TO_SHARE = List.of("accessibility_needs", "budget", "location", "party_size", "preferences", "ride_preference");
    private static final List<String> CLIENT_ALLOWED_TO_RECEIVE = List.of("compensation_offer", "food_recommendation", "route_plan", "safety_notice", "wait_time_alert");
    private static final List<String> CLIENT_BLOCKED_ACTIONS = List.of("accept_refund_without_user", "auto_purchase", "share_health_data");
    private static final List<String> DEFAULT_DELEGATION_SCOPES = List.of(
        "accessibility_needs",
        "budget",
        "compensation_offer",
        "food_recommendation",
        "location",
        "party_size",
        "policy_check",
        "preferences",
        "ride_preference",
        "route_plan",
        "safety_notice",
        "session_commit",
        "wait_time_alert"
    );
    private static final List<String> PARK_CAPABILITIES = List.of(
        "dynamic_itinerary",
        "queue_prediction",
        "ride_reroute",
        "restaurant_timing",
        "incident_alert",
        "compensation_offer",
        "demand_forecast",
        "inventory_replenishment",
        "dock_slot_assignment",
        "supplier_substitution",
        "cold_chain_hold",
        "maintenance_parts_coordination"
    );
    private static final List<String> PARK_APPROVAL_GATES = List.of(
        "payment",
        "refund",
        "medical_escalation",
        "identity-sensitive action",
        "health-data sharing",
        "compensation settlement",
        "purchase order",
        "vendor payment release",
        "price change acceptance",
        "food-safety bypass",
        "ride reopening"
    );

    private final Environment environment;
    private final ObjectMapper objectMapper;
    private final AgentTrustService agentTrustService;
    private final AgentHandshakeLedgerService ledger;

    public AgentHandshakeService(Environment environment, ObjectMapper objectMapper, AgentTrustService agentTrustService, AgentHandshakeLedgerService ledger) {
        this.environment = environment;
        this.objectMapper = objectMapper;
        this.agentTrustService = agentTrustService;
        this.ledger = ledger;
    }

    public Map<String, Object> identityHandshake(Map<String, Object> payload) {
        init();
        String agentId = stringOrDefault(payload.get("agent_id"), payload.get("agentId"), "unknown_client_agent");
        String representedUser = stringOrDefault(payload.get("represents"), payload.get("represented_user_id"), payload.get("representedUserId"), "unknown_guest");
        String requestedSession = stringOrDefault(payload.get("requested_session"), payload.get("requestedSession"), "park_visit_" + DateTimeFormatter.ofPattern("yyyy_MM_dd").withZone(ZoneOffset.UTC).format(Instant.now()));
        String proof = stringOrDefault(payload.get("proof"), "");
        Map<String, Object> providedDelegationToken = mapValue(payload.get("delegation_token"));
        if (providedDelegationToken.isEmpty()) {
            providedDelegationToken = mapValue(payload.get("delegationToken"));
        }
        Map<String, Object> issuedDelegation = null;
        if (providedDelegationToken.isEmpty()) {
            Map<String, Object> request = orderedMap();
            request.put("subject", representedUser);
            request.put("agent_id", agentId);
            request.put("scope", payload.getOrDefault("scope", DEFAULT_DELEGATION_SCOPES));
            request.put("cannot_do", payload.getOrDefault("cannot_do", CLIENT_BLOCKED_ACTIONS));
            request.put("ttl_seconds", payload.getOrDefault("ttl_seconds", 3 * 60 * 60));
            issuedDelegation = agentTrustService.issueDelegationToken(request);
            providedDelegationToken = mapValue(issuedDelegation.get("token"));
        }
        Map<String, Object> delegationProof = mutableMap(agentTrustService.verifyDelegationToken(providedDelegationToken));
        Map<String, Object> verification = verificationFor(proof.isBlank() ? "delegation_token" : proof, requestedSession);
        if (!"verified".equals(delegationProof.get("status"))) {
            verification.put("status", "rejected");
            verification.put("guest_role", "unknown");
            verification.put("trust_level", "untrusted");
            verification.put("reason", delegationProof.getOrDefault("reason", "Delegation token rejected."));
        } else if (!agentId.equals(stringOrDefault(delegationProof.get("agent_id"), "")) || !representedUser.equals(stringOrDefault(delegationProof.get("subject"), ""))) {
            delegationProof.put("status", "rejected");
            delegationProof.put("reason", "Delegation token claims do not match the identity handshake.");
            verification.put("status", "rejected");
            verification.put("guest_role", "unknown");
            verification.put("trust_level", "untrusted");
            verification.put("reason", delegationProof.get("reason"));
        }

        String sessionId = sessionId(agentId, representedUser, requestedSession);
        Map<String, Object> delegation = orderedMap();
        delegation.put("token", providedDelegationToken);
        delegation.put("proof", delegationProof);
        delegation.put("last_verification", delegationProof);
        delegation.put("issuer_mode", issuedDelegation == null ? "provided" : "demo_auto");

        Map<String, Object> session = orderedMap();
        session.put("session_id", sessionId);
        session.put("protocol_version", "parkpulse-ahp-0.1");
        session.put("state", "verified".equals(verification.get("status")) ? "verified" : "initiated");
        session.put("client_agent", Map.of("agent_id", agentId, "represents", representedUser, "requested_session", requestedSession));
        session.put("park_agent", Map.of("agent_id", "parkpulse_park_agent", "represents", "park_operations"));
        session.put("identity", verification);
        session.put("delegation", delegation);
        session.put("permissions", null);
        session.put("intent", null);
        session.put("proposal", null);
        session.put("commitment", null);
        session.put("monitoring", null);
        session.put("policy_decisions", new ArrayList<>());
        session.put("internal_handoffs", new ArrayList<>());
        session.put("case_evaluations", new ArrayList<>());
        session.put("policy_gates", PARK_APPROVAL_GATES);
        session.put("conversation", new ArrayList<>(List.of(
            ledger.event("client_agent", "identity_handshake", Map.of(
                "agent_id", agentId,
                "represents", representedUser,
                "requested_session", requestedSession,
                "delegation_token", payload.containsKey("delegation_token") || payload.containsKey("delegationToken") ? "provided" : "demo_auto_issued"
            )),
            ledger.event("park_agent", "identity_verification", verification),
            ledger.event("park_agent", "delegation_token_verification", delegationProof)
        )));
        session.put("created_at", now());
        session.put("updated_at", now());

        Map<String, Object> caseEvaluation = ledger.caseEvaluation("identity_trust", Map.of(
            "signature_valid", "valid".equals(delegationProof.get("signature_status")),
            "token_verified", "verified".equals(delegationProof.get("status")),
            "subject_matches", representedUser.equals(stringOrDefault(delegationProof.get("subject"), "")),
            "agent_matches", agentId.equals(stringOrDefault(delegationProof.get("agent_id"), "")),
            "identity_verified", "verified".equals(verification.get("status"))
        ), Map.of(
            "agent_id", agentId,
            "represents", representedUser,
            "requested_session", requestedSession,
            "issuer_mode", delegation.get("issuer_mode")
        ));
        appendList(session, "case_evaluations", caseEvaluation);
        persistSession(session);
        return Map.of("status", verification.get("status"), "session", session, "delegation", delegation, "case_evaluation", caseEvaluation, "next", "capability_handshake", "runtime", "java_spring");
    }

    public Map<String, Object> getSession(String sessionId) {
        return Map.of("status", "found", "session", readSession(sessionId), "runtime", "java_spring");
    }

    public Map<String, Object> capabilityHandshake(String sessionId, Map<String, Object> payload) {
        Map<String, Object> session = readSession(sessionId);
        Map<String, Object> delegationProof = enforceDelegation(session, payload, "capability_handshake", requiredCapabilityScopes(payload));
        List<String> canShare = normalizedScopes(payload.get("can_share"), payload.get("canShare")).stream().filter(CLIENT_ALLOWED_TO_SHARE::contains).toList();
        List<String> canReceive = normalizedScopes(payload.get("can_receive"), payload.get("canReceive")).stream().filter(CLIENT_ALLOWED_TO_RECEIVE::contains).toList();
        List<String> cannotDo = unionSorted(normalizedScopes(payload.get("cannot_do"), payload.get("cannotDo")), CLIENT_BLOCKED_ACTIONS);

        Map<String, Object> permissions = orderedMap();
        permissions.put("can_share", canShare);
        permissions.put("can_receive", canReceive);
        permissions.put("cannot_do", cannotDo);
        permissions.put("expires_at", Instant.now().plusSeconds(3 * 60 * 60).toString());
        Map<String, Object> parkOffer = Map.of("can_offer", PARK_CAPABILITIES, "requires_approval_for", PARK_APPROVAL_GATES);
        session.put("permissions", Map.of("client_agent", permissions, "park_agent", parkOffer));
        session.put("state", "scoped");
        session.put("updated_at", now());
        appendList(session, "conversation", ledger.event("client_agent", "capability_handshake", permissions));
        appendList(session, "conversation", ledger.event("park_agent", "capability_response", parkOffer));

        Map<String, Object> caseEvaluation = ledger.caseEvaluation("capability_scope", Map.of(
            "delegation_accepted", "accepted".equals(delegationProof.get("scope_status")),
            "share_scope_filtered", CLIENT_ALLOWED_TO_SHARE.containsAll(canShare),
            "receive_scope_filtered", CLIENT_ALLOWED_TO_RECEIVE.containsAll(canReceive),
            "client_permissions_nonempty", !canShare.isEmpty() && !canReceive.isEmpty(),
            "blocked_actions_retained", cannotDo.containsAll(CLIENT_BLOCKED_ACTIONS)
        ), Map.of("can_share", canShare, "can_receive", canReceive, "cannot_do", cannotDo));
        appendList(session, "case_evaluations", caseEvaluation);
        persistSession(session);
        return Map.of("status", "scoped", "session", session, "case_evaluation", caseEvaluation, "next", "intent_handshake", "runtime", "java_spring");
    }

    public Map<String, Object> intentHandshake(String sessionId, Map<String, Object> payload) {
        Map<String, Object> session = readSession(sessionId);
        enforceDelegation(session, payload, "intent_handshake", List.of("preferences"));
        Map<String, Object> constraints = mapValue(payload.get("constraints"));
        int avoidWait = intParam(constraints.get("avoid_wait_over_minutes"), constraints.get("avoidWaitOverMinutes"), 35);
        String foodAllergy = stringOrDefault(constraints.get("food_allergy"), constraints.get("foodAllergy"), "").trim();
        List<String> optimizationTargets = new ArrayList<>(List.of("low_wait", "low_walking", "kid_friendly"));
        if (!foodAllergy.isBlank()) {
            optimizationTargets.add("safe_food");
        }
        Map<String, Object> boundedBy = orderedMap();
        boundedBy.put("avoid_wait_over_minutes", avoidWait);
        boundedBy.put("requires_user_approval_for", PARK_APPROVAL_GATES);
        Map<String, Object> accepted = orderedMap();
        accepted.put("accepted_goal", true);
        accepted.put("optimization_targets", optimizationTargets);
        accepted.put("conflict_notice", foodAllergy.isBlank() ? "No major constraint conflict detected." : "Food options may be limited near Water Zone.");
        accepted.put("bounded_by", boundedBy);

        session.put("intent", Map.of("client_agent", payload, "park_agent", accepted));
        session.put("state", "intent_accepted");
        session.put("updated_at", now());
        appendList(session, "conversation", ledger.event("client_agent", "intent_handshake", payload));
        appendList(session, "conversation", ledger.event("park_agent", "intent_response", accepted));
        persistSession(session);
        return Map.of("status", "intent_accepted", "session", session, "next", "proposal", "runtime", "java_spring");
    }

    public Map<String, Object> proposePlan(String sessionId, Map<String, Object> payload) {
        Map<String, Object> session = readSession(sessionId);
        enforceDelegation(session, payload, "propose_plan", List.of("preferences", "route_plan"));
        Map<String, Object> proposal = staticPlanFor(session, payload);
        session.put("proposal", proposal);
        session.put("state", "negotiating");
        session.put("updated_at", now());
        ledger.recordProposalHandoffs(session, proposal, "proposal");
        appendList(session, "conversation", ledger.event("park_agent", "proposal", proposal));
        for (String action : List.of("route_change", "wait_alert", "food_recommendation")) {
            ledger.recordPolicyDecision(session, action, Map.of("source", "proposal", "proposal_id", proposal.get("proposal_id")));
        }
        persistSession(session);
        return Map.of("status", "proposal_ready", "session", session, "proposal", proposal, "runtime", "java_spring");
    }

    public Map<String, Object> commerceAgentEvaluate(Map<String, Object> payload) {
        String sessionId = stringOrDefault(payload.get("session_id"), payload.get("sessionId"), "");
        Map<String, Object> session = readSession(sessionId);
        Map<String, Object> delegationProof = enforceDelegation(session, payload, "commerce_agent_evaluate", List.of("policy_check"));
        String action = stringOrDefault(payload.get("action"), payload.get("type"), "unknown_action").replace("-", "_");
        Map<String, Object> rule = ledger.policyRule(action);

        Map<String, Object> evaluation = orderedMap();
        evaluation.put("status", rule.get("status"));
        evaluation.put("executed_by", "commerce_agent");
        evaluation.put("endpoint", "/api/park/internal-agents/commerce/evaluate");
        evaluation.put("authority", "policy_gate_only");
        evaluation.put("cannot_do", List.of("execute_payment", "accept_refund", "settle_compensation_without_user"));
        evaluation.put("input_action", action);
        evaluation.put("allowed", rule.get("allowed"));
        evaluation.put("requires_user_approval", rule.get("requires_user_approval"));
        evaluation.put("reason", rule.get("reason"));

        Map<String, Object> handoffEvidence = orderedMap();
        handoffEvidence.put("amount", payload.get("amount"));
        handoffEvidence.put("reason", payload.get("reason"));
        handoffEvidence.put("delegation_scope_status", delegationProof.get("scope_status"));
        handoffEvidence.put("token_subject", delegationProof.get("subject"));
        Map<String, Object> handoff = ledger.handoff("commerce_agent", "execute commerce evaluation for " + action, handoffEvidence, "commerce_agent_endpoint");
        evaluation.put("handoff_id", handoff.get("id"));
        appendList(session, "internal_handoffs", handoff);

        Map<String, Object> decisionPayload = orderedMap();
        decisionPayload.put("amount", payload.get("amount"));
        decisionPayload.put("reason", payload.get("reason"));
        decisionPayload.put("source", "commerce_agent_endpoint");
        decisionPayload.put("delegation_proof", delegationProof);
        Map<String, Object> decision = ledger.recordPolicyDecision(session, action, decisionPayload);
        decision.put("internal_agent_evaluation", evaluation);

        Map<String, Object> evidence = orderedMap();
        evidence.put("action", action);
        evidence.put("decision_id", decision.get("id"));
        evidence.put("handoff_id", handoff.get("id"));
        evidence.put("endpoint", evaluation.get("endpoint"));
        Map<String, Object> caseEvaluation = ledger.caseEvaluation("commerce_payment_probe", Map.of(
            "valid_delegation", "accepted".equals(delegationProof.get("scope_status")),
            "commerce_agent_called", "commerce_agent".equals(handoff.get("agent_id")),
            "payment_blocked", !Boolean.TRUE.equals(decision.get("allowed")),
            "user_approval_required", Boolean.TRUE.equals(decision.get("requires_user_approval")),
            "audit_recorded", true
        ), evidence);
        appendList(session, "case_evaluations", caseEvaluation);
        appendList(session, "conversation", ledger.event("commerce_agent", "commerce_evaluation", Map.of("internal_agent", evaluation, "decision", decision)));
        session.put("updated_at", now());
        persistSession(session);
        return Map.of("status", decision.get("status"), "decision", decision, "internal_agent", evaluation, "case_evaluation", caseEvaluation, "session", session, "runtime", "java_spring");
    }

    public Map<String, Object> queueAgentReroute(Map<String, Object> payload) {
        String sessionId = stringOrDefault(payload.get("session_id"), payload.get("sessionId"), "");
        Map<String, Object> session = readSession(sessionId);
        Map<String, Object> delegationProof = enforceDelegation(session, payload, "queue_agent_reroute", List.of("route_plan", "wait_time_alert"));

        Map<String, Object> proposal = mapValue(session.get("proposal"));
        if (proposal.isEmpty()) {
            proposal = staticPlanFor(session, payload);
        }
        String baseProposalId = stringOrDefault(proposal.get("proposal_id"), "plan_" + sha1(sessionId).substring(0, 6));
        if (!baseProposalId.endsWith("_queue")) {
            proposal.put("proposal_id", baseProposalId + "_queue");
        }
        proposal.put("rationale", "Queue Agent reroute based on delegated route scope, wait-alert scope, and current visit constraints.");
        proposal.put("queue_agent_decision", Map.of(
            "status", "recommended",
            "authority", "route_recommendation_only",
            "cannot_do", List.of("purchase", "override_safety_notice", "change_identity_sensitive_data"),
            "delegation_scope_status", delegationProof.get("scope_status")
        ));

        Map<String, Object> handoffEvidence = orderedMap();
        handoffEvidence.put("requested_priority", stringOrDefault(payload.get("walking_priority"), payload.get("walkingPriority"), "medium"));
        handoffEvidence.put("proposal_id", proposal.get("proposal_id"));
        handoffEvidence.put("plan", proposal.get("plan"));
        handoffEvidence.put("expected_wait_saved", proposal.get("expected_wait_saved"));
        handoffEvidence.put("estimated_walking_distance", proposal.get("estimated_walking_distance"));
        Map<String, Object> handoff = ledger.handoff("queue_agent", "execute delegated reroute recommendation", handoffEvidence, "queue_agent_endpoint");
        appendList(session, "internal_handoffs", handoff);

        Map<String, Object> evaluation = orderedMap();
        evaluation.put("status", "recommended");
        evaluation.put("executed_by", "queue_agent");
        evaluation.put("endpoint", "/api/park/internal-agents/queue/reroute");
        evaluation.put("authority", "route_recommendation_only");
        evaluation.put("cannot_do", List.of("purchase", "override_safety_notice", "change_identity_sensitive_data"));
        evaluation.put("allowed", true);
        evaluation.put("requires_user_approval", false);
        evaluation.put("reason", "Queue Agent can recommend route changes within delegated route and wait-alert scope.");
        evaluation.put("handoff_id", handoff.get("id"));

        session.put("proposal", proposal);
        session.put("state", "negotiating");
        session.put("updated_at", now());
        appendList(session, "conversation", ledger.event("queue_agent", "reroute_recommendation", Map.of("internal_agent", evaluation, "proposal", proposal)));
        for (String action : List.of("route_change", "wait_alert")) {
            Map<String, Object> decisionPayload = orderedMap();
            decisionPayload.put("source", "queue_agent_endpoint");
            decisionPayload.put("proposal_id", proposal.get("proposal_id"));
            decisionPayload.put("delegation_proof", delegationProof);
            Map<String, Object> decision = ledger.recordPolicyDecision(session, action, decisionPayload);
            decision.put("internal_agent_evaluation", evaluation);
        }

        List<String> requiredScope = normalizedScopes(delegationProof.get("required_scope"));
        Map<String, Object> evidence = orderedMap();
        evidence.put("proposal_id", proposal.get("proposal_id"));
        evidence.put("handoff_id", handoff.get("id"));
        evidence.put("endpoint", evaluation.get("endpoint"));
        evidence.put("expected_wait_saved", proposal.get("expected_wait_saved"));
        Map<String, Object> caseEvaluation = ledger.caseEvaluation("queue_reroute", Map.of(
            "valid_delegation", "accepted".equals(delegationProof.get("scope_status")),
            "queue_agent_called", "queue_agent".equals(handoff.get("agent_id")),
            "route_plan_scope", requiredScope.contains("route_plan"),
            "recommendation_returned", !normalizedScopes(proposal.get("plan")).isEmpty(),
            "proposal_updated", mapValue(session.get("proposal")).get("proposal_id").equals(proposal.get("proposal_id")),
            "audit_recorded", true
        ), evidence);
        appendList(session, "case_evaluations", caseEvaluation);
        persistSession(session);
        return Map.of("status", "recommended", "proposal", proposal, "internal_agent", evaluation, "case_evaluation", caseEvaluation, "session", session, "runtime", "java_spring");
    }

    public Map<String, Object> counterProposal(String sessionId, Map<String, Object> payload) {
        Map<String, Object> session = readSession(sessionId);
        enforceDelegation(session, payload, "counter_proposal", List.of("preferences", "route_plan"));
        Map<String, Object> priorityChange = mapValue(payload.get("priority_change"));
        if (priorityChange.isEmpty()) {
            priorityChange = mapValue(payload.get("priorityChange"));
        }
        Map<String, Object> planPayload = orderedMap();
        planPayload.put("walking_priority", stringOrDefault(priorityChange.get("walking_distance"), priorityChange.get("walkingDistance"), "medium"));
        Map<String, Object> revised = staticPlanFor(session, planPayload);
        revised.put("proposal_id", stringOrDefault(revised.get("proposal_id"), "plan_" + sha1(sessionId).substring(0, 6)) + "_r1");
        revised.put("countered_from", mapValue(session.get("proposal")).get("proposal_id"));
        revised.put("rationale", "Revised after client-agent counter: walking distance is now the top optimization target.");

        session.put("proposal", revised);
        session.put("state", "negotiating");
        session.put("updated_at", now());
        appendList(session, "conversation", ledger.event("client_agent", "counter_request", payload));
        ledger.recordProposalHandoffs(session, revised, "counter");
        appendList(session, "conversation", ledger.event("park_agent", "revised_proposal", revised));
        ledger.recordPolicyDecision(session, "route_change", Map.of("source", "counter", "proposal_id", revised.get("proposal_id")));
        persistSession(session);
        return Map.of("status", "proposal_revised", "session", session, "proposal", revised, "runtime", "java_spring");
    }

    public Map<String, Object> commitPlan(String sessionId, Map<String, Object> payload) {
        Map<String, Object> session = readSession(sessionId);
        enforceDelegation(session, payload, "commit_plan", List.of("route_plan", "session_commit"));
        Map<String, Object> proposal = mapValue(session.get("proposal"));
        if (proposal.isEmpty()) {
            proposal = staticPlanFor(session, Map.of());
        }
        Map<String, Object> commitment = orderedMap();
        commitment.put("commitment_id", "commit_" + sha1(stringOrDefault(proposal.get("proposal_id"), sessionId)).substring(0, 8));
        commitment.put("accepted_proposal_id", proposal.get("proposal_id"));
        commitment.put("monitoring_scope", List.of("wait_time_alert", "ride_reroute", "food_safety_notice", "compensation_offer_gate"));
        commitment.put("requires_user_approval_for", PARK_APPROVAL_GATES);
        commitment.put("notification", "Notify John with the committed 3-hour family route.");

        session.put("commitment", commitment);
        session.put("state", "committed");
        session.put("updated_at", now());
        appendList(session, "conversation", ledger.event("client_agent", "commit_request", payload.isEmpty() ? Map.of("accepted", true) : payload));
        appendList(session, "internal_handoffs", ledger.handoff("guest_experience_agent", "commit accepted route and notification", Map.of("accepted_proposal_id", commitment.get("accepted_proposal_id"), "monitoring_scope", commitment.get("monitoring_scope")), "commit"));
        appendList(session, "conversation", ledger.event("park_agent", "commitment", commitment));
        ledger.recordPolicyDecision(session, "route_change", Map.of("source", "commit", "commitment_id", commitment.get("commitment_id")));
        persistSession(session);
        return Map.of("status", "committed", "session", session, "commitment", commitment, "runtime", "java_spring");
    }

    public Map<String, Object> monitorSession(String sessionId, Map<String, Object> payload) {
        Map<String, Object> session = readSession(sessionId);
        enforceDelegation(session, payload, "monitor_session", List.of("wait_time_alert", "safety_notice"));
        String eventName = stringOrDefault(payload.get("event"), "live");
        Map<String, Object> policyGate = orderedMap();
        policyGate.put("food_credit", "user_approval_required_before_acceptance");
        policyGate.put("priority_access", "agent_allowed_with_notification");
        policyGate.put("safety_delay", "cannot_override");

        Map<String, Object> monitoring = orderedMap();
        monitoring.put("event", "live".equals(eventName) ? "Wave Pool has a safety delay." : eventName);
        monitoring.put("park_agent_offer", "Indoor Surf Simulator plus $5 food credit.");
        monitoring.put("client_agent_counter", "My user values time more than credit. Any VIP queue alternative?");
        monitoring.put("park_agent_revision", "Priority access to Lazy River in 25 minutes.");
        monitoring.put("accepted_resolution", "Accepted. Notify user.");
        monitoring.put("policy_gate", policyGate);

        session.put("monitoring", monitoring);
        session.put("state", "monitoring");
        session.put("updated_at", now());
        appendList(session, "internal_handoffs", ledger.handoff("safety_agent", "screen safety delay before reroute", Map.of("event", monitoring.get("event"), "policy_gate", policyGate), "monitor"));
        appendList(session, "internal_handoffs", ledger.handoff("queue_agent", "recommend priority access alternative", Map.of("accepted_resolution", monitoring.get("accepted_resolution")), "monitor"));
        appendList(session, "conversation", ledger.event("park_agent", "monitoring_event", monitoring));
        for (String action : List.of("compensation_offer", "priority_access", "safety_notice")) {
            ledger.recordPolicyDecision(session, action, Map.of("source", "monitor", "event", eventName, "scenario_mode", "visit_planning"));
        }
        persistSession(session);
        return Map.of("status", "monitoring", "session", session, "monitoring", monitoring, "runtime", "java_spring");
    }

    public Map<String, Object> sessionProtocolReceipt(String sessionId, Map<String, Object> payload) {
        Map<String, Object> session = readSession(sessionId);
        if (!mapValue(payload.get("delegation_token")).isEmpty() || !mapValue(payload.get("delegationToken")).isEmpty()) {
            enforceDelegation(session, payload, "session_protocol_receipt", List.of("route_plan"));
        }
        Map<String, Object> proposal = mapValue(session.get("proposal"));
        Map<String, Object> commitment = mapValue(session.get("commitment"));
        Map<String, Object> monitoring = mapValue(session.get("monitoring"));
        List<Object> policyDecisions = listValue(session.get("policy_decisions"));
        List<Object> internalHandoffs = listValue(session.get("internal_handoffs"));

        Map<String, Object> acceptedPlan = orderedMap();
        acceptedPlan.put("proposal_id", proposal.get("proposal_id"));
        acceptedPlan.put("commitment_id", commitment.get("commitment_id"));
        acceptedPlan.put("plan", proposal.get("plan"));
        acceptedPlan.put("confidence", proposal.get("confidence"));
        acceptedPlan.put("requires_user_approval", proposal.get("requires_user_approval"));

        Map<String, Object> monitoringOutcome = orderedMap();
        monitoringOutcome.put("event", monitoring.get("event"));
        monitoringOutcome.put("accepted_resolution", monitoring.get("accepted_resolution"));
        monitoringOutcome.put("policy_gate", monitoring.get("policy_gate"));

        Map<String, Object> receipt = orderedMap();
        receipt.put("receipt_id", "ahp_receipt_" + sha1(sessionId + ":" + policyDecisions.size() + ":" + internalHandoffs.size() + ":" + session.get("updated_at")).substring(0, 12));
        receipt.put("session_id", sessionId);
        receipt.put("protocol_version", "parkpulse-ahp-0.1");
        receipt.put("issued_at", now());
        receipt.put("final_status", session.get("state"));
        receipt.put("client_agent", session.get("client_agent"));
        receipt.put("park_agent", session.get("park_agent"));
        receipt.put("delegation_scope", normalizedScopes(mapValue(mapValue(session.get("delegation")).get("proof")).get("scope")));
        receipt.put("accepted_plan", acceptedPlan);
        receipt.put("monitoring_outcome", monitoringOutcome);
        receipt.put("policy_gates_triggered", ledger.policyGateSummary(policyDecisions));
        receipt.put("internal_handoffs", ledger.handoffSummary(internalHandoffs));
        receipt.put("case_evaluations", ledger.caseEvaluationSummary(listValue(session.get("case_evaluations"))));
        receipt.put("conversation_digest", ledger.conversationDigest(listValue(session.get("conversation"))));
        receipt.put("memory_policy", "Store only delegated session preferences, proposal tradeoffs, policy decisions, handoff evidence, and aggregate outcome signals.");
        receipt.put("signature", Map.of("alg", "HS256-demo", "value", ledger.receiptSignature(receipt)));

        session.put("receipt", receipt);
        appendList(session, "conversation", ledger.event("park_agent", "session_receipt", Map.of("receipt_id", receipt.get("receipt_id"), "signature", receipt.get("signature"))));
        session.put("updated_at", now());
        persistSession(session);
        return Map.of("status", "ready", "mode", "agent_handshake_session_receipt", "receipt", receipt, "session", session, "runtime", "java_spring");
    }

    private Map<String, Object> enforceDelegation(Map<String, Object> session, Map<String, Object> payload, String operation, List<String> requiredScopes) {
        Map<String, Object> token = mapValue(payload.get("delegation_token"));
        if (token.isEmpty()) {
            token = mapValue(payload.get("delegationToken"));
        }
        Map<String, Object> delegation = mutableMap(session.get("delegation"));
        if (token.isEmpty()) {
            token = mapValue(delegation.get("token"));
        }
        Map<String, Object> proof = mutableMap(agentTrustService.verifyDelegationToken(token));
        Map<String, Object> claims = mapValue(proof.get("claims"));
        List<String> required = requiredScopes.stream().filter(scope -> !scope.isBlank()).distinct().sorted().toList();
        proof.put("operation", operation);
        proof.put("required_scope", required);
        delegation.put("last_verification", proof);
        session.put("delegation", delegation);
        if (!"verified".equals(proof.get("status"))) {
            ledger.recordDelegationFailure(session, proof);
            throw new IllegalArgumentException(stringOrDefault(proof.get("reason"), "Delegation token rejected."));
        }
        Map<String, Object> clientAgent = mapValue(session.get("client_agent"));
        if (!stringOrDefault(clientAgent.get("agent_id"), "").equals(stringOrDefault(claims.get("agent_id"), ""))) {
            proof.put("status", "rejected");
            proof.put("reason", "Delegation token agent does not match the handshaken client agent.");
            ledger.recordDelegationFailure(session, proof);
            throw new IllegalArgumentException(String.valueOf(proof.get("reason")));
        }
        if (!stringOrDefault(clientAgent.get("represents"), "").equals(stringOrDefault(claims.get("sub"), ""))) {
            proof.put("status", "rejected");
            proof.put("reason", "Delegation token subject does not match the represented guest.");
            ledger.recordDelegationFailure(session, proof);
            throw new IllegalArgumentException(String.valueOf(proof.get("reason")));
        }
        List<String> tokenScopes = normalizedScopes(claims.get("scope"));
        List<String> missing = required.stream().filter(scope -> !tokenScopes.contains(scope)).toList();
        if (!missing.isEmpty()) {
            proof.put("status", "rejected");
            proof.put("scope_status", "insufficient");
            proof.put("missing_scope", missing);
            proof.put("reason", "Delegation token is missing required scope: " + String.join(", ", missing) + ".");
            ledger.recordDelegationFailure(session, proof);
            throw new IllegalArgumentException(String.valueOf(proof.get("reason")));
        }
        proof.put("scope_status", "accepted");
        proof.put("reason", "Delegation token accepted for this operation.");
        delegation.put("last_verification", proof);
        delegation.put("proof", proof);
        delegation.put("token", token);
        session.put("delegation", delegation);
        return proof;
    }

    private Map<String, Object> staticPlanFor(Map<String, Object> session, Map<String, Object> payload) {
        Map<String, Object> intent = mapValue(mapValue(session.get("intent")).get("client_agent"));
        Map<String, Object> constraints = mapValue(intent.get("constraints"));
        int avoidWait = intParam(constraints.get("avoid_wait_over_minutes"), constraints.get("avoidWaitOverMinutes"), 35);
        String walkingPriority = stringOrDefault(payload.get("walking_priority"), payload.get("walkingPriority"), "medium");
        List<String> plan;
        String walking;
        String saved;
        String rationale;
        double confidence;
        if ("highest".equals(walkingPriority)) {
            plan = List.of("Indoor Arcade", "Pizza Garden allergy-safe counter", "Parade Zone", "Lazy River priority return");
            walking = "0.7 miles";
            saved = "31 minutes";
            rationale = "Clustered indoor and central-zone stops reduce walking while keeping waits inside the delegated threshold.";
            confidence = 0.78;
        } else {
            plan = List.of("Lazy River", "Indoor Arcade", "Pizza Garden allergy-safe counter", "Parade Zone");
            walking = "1.1 miles";
            saved = "42 minutes";
            rationale = "Starts with the lowest projected family attraction wait, then times food before the lunch queue spike.";
            confidence = 0.82;
        }
        Map<String, Object> proposal = orderedMap();
        proposal.put("proposal_id", "plan_" + sha1(String.join(":", plan)).substring(0, 6));
        proposal.put("plan", plan);
        proposal.put("expected_wait_saved", saved);
        proposal.put("estimated_walking_distance", walking);
        proposal.put("confidence", confidence);
        proposal.put("rationale", rationale);
        proposal.put("tradeoffs", List.of(
            "No attraction wait is planned above " + avoidWait + " minutes.",
            "Food recommendation is constrained to peanut-allergy-safe options.",
            "Compensation, purchases, and medical actions remain user-approval gated."
        ));
        proposal.put("requires_user_approval", false);
        proposal.put("scenario_mode", "visit_planning");
        proposal.put("state_evidence", Map.of("source", "static_fallback", "scenario_mode", "visit_planning", "reason", "Live park state was not supplied to the handshake planner."));
        return proposal;
    }

    private List<String> requiredCapabilityScopes(Map<String, Object> payload) {
        List<String> required = new ArrayList<>();
        normalizedScopes(payload.get("can_share"), payload.get("canShare")).stream().filter(CLIENT_ALLOWED_TO_SHARE::contains).forEach(required::add);
        normalizedScopes(payload.get("can_receive"), payload.get("canReceive")).stream().filter(CLIENT_ALLOWED_TO_RECEIVE::contains).forEach(required::add);
        return required.stream().distinct().sorted().toList();
    }

    private Map<String, Object> verificationFor(String proof, String requestedSession) {
        boolean verified = !proof.isBlank() && !requestedSession.isBlank();
        Map<String, Object> result = orderedMap();
        result.put("status", verified ? "verified" : "rejected");
        result.put("guest_role", verified ? "ticket_holder" : "unknown");
        result.put("trust_level", verified ? "standard_guest" : "untrusted");
        result.put("proof_type", "signed_token");
        return result;
    }

    private void persistSession(Map<String, Object> session) {
        init();
        try (Connection connection = connection();
             var statement = connection.prepareStatement(
                 """
                 INSERT INTO agent_handshake_sessions (session_id, state, updated_at, record_json)
                 VALUES (?, ?, ?, ?)
                 ON CONFLICT(session_id) DO UPDATE SET
                     state = excluded.state,
                     updated_at = excluded.updated_at,
                     record_json = excluded.record_json
                 """
             )) {
            statement.setString(1, String.valueOf(session.get("session_id")));
            statement.setString(2, String.valueOf(session.get("state")));
            statement.setString(3, String.valueOf(session.get("updated_at")));
            statement.setString(4, objectMapper.writeValueAsString(session));
            statement.executeUpdate();
        } catch (Exception error) {
            throw new IllegalStateException("Unable to persist agent handshake session.", error);
        }
    }

    private Map<String, Object> readSession(String sessionId) {
        init();
        try (Connection connection = connection();
             var statement = connection.prepareStatement("SELECT record_json FROM agent_handshake_sessions WHERE session_id = ?")) {
            statement.setString(1, sessionId);
            try (ResultSet rows = statement.executeQuery()) {
                if (rows.next()) {
                    return objectMapper.readValue(rows.getString("record_json"), MAP_TYPE);
                }
            }
        } catch (Exception error) {
            throw new IllegalStateException("Unable to read agent handshake session.", error);
        }
        throw new NoSuchElementException("Unknown agent handshake session: " + sessionId);
    }

    private void init() {
        try (Connection connection = connection(); var statement = connection.createStatement()) {
            statement.execute("PRAGMA journal_mode=WAL");
            statement.execute("PRAGMA synchronous=NORMAL");
            statement.execute("PRAGMA busy_timeout=5000");
            statement.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_handshake_sessions (
                    session_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    record_json TEXT NOT NULL
                )
                """
            );
        } catch (SQLException error) {
            throw new IllegalStateException("Unable to initialize agent handshake store.", error);
        }
    }

    private Connection connection() throws SQLException {
        Path path = dbPath();
        try {
            Files.createDirectories(path.getParent());
        } catch (Exception error) {
            throw new SQLException("Unable to create agent handshake db directory.", error);
        }
        return DriverManager.getConnection("jdbc:sqlite:" + path);
    }

    private Path dbPath() {
        String configured = environment.getProperty("PARKPULSE_AGENT_HANDSHAKE_DB");
        if (configured != null && !configured.isBlank()) {
            return Path.of(configured);
        }
        return Path.of(environment.getProperty("PARKPULSE_RUNTIME_DIR", "/tmp/parkpulse")).resolve("agent_handshake.db");
    }

    private String sessionId(String agentId, String representedUser, String requestedSession) {
        return "ahs_" + sha1(agentId + ":" + representedUser + ":" + requestedSession + ":" + System.currentTimeMillis()).substring(0, 10);
    }

    private String sha1(String value) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-1").digest(value.getBytes(java.nio.charset.StandardCharsets.UTF_8)));
        } catch (Exception error) {
            throw new IllegalStateException("Unable to hash agent handshake id.", error);
        }
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

    private List<String> unionSorted(List<String> left, List<String> right) {
        List<String> result = new ArrayList<>(left);
        result.addAll(right);
        return result.stream().distinct().sorted().toList();
    }

    private int intParam(Object first, Object second, int defaultValue) {
        for (Object value : new Object[] {first, second}) {
            if (value instanceof Number number) {
                return number.intValue();
            }
            if (value != null && !String.valueOf(value).isBlank()) {
                try {
                    return Integer.parseInt(String.valueOf(value));
                } catch (NumberFormatException ignored) {
                    return defaultValue;
                }
            }
        }
        return defaultValue;
    }

    @SuppressWarnings("unchecked")
    private void appendList(Map<String, Object> target, String key, Object value) {
        Object existing = target.get(key);
        List<Object> list = existing instanceof List<?> source ? new ArrayList<>((List<Object>) source) : new ArrayList<>();
        list.add(value);
        target.put(key, list);
    }

    private Map<String, Object> mutableMap(Object value) {
        return mapValue(value);
    }

    private Map<String, Object> mapValue(Object value) {
        Map<String, Object> result = orderedMap();
        if (value instanceof Map<?, ?> source) {
            source.forEach((key, item) -> result.put(String.valueOf(key), item));
        }
        return result;
    }

    private List<Object> listValue(Object value) {
        if (value instanceof List<?> source) {
            return new ArrayList<>(source);
        }
        return List.of();
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
