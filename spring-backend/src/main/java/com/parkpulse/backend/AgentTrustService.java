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
import java.util.NoSuchElementException;
import java.util.UUID;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Service;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

@Service
public class AgentTrustService {
    private static final TypeReference<List<String>> STRING_LIST_TYPE = new TypeReference<>() {};
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};
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
    private static final List<String> CLIENT_BLOCKED_ACTIONS = List.of("accept_refund_without_user", "auto_purchase", "share_health_data");

    private final Environment environment;
    private final ObjectMapper objectMapper;
    private final AgentTrustCredentialCodec credentialCodec;

    public AgentTrustService(Environment environment, ObjectMapper objectMapper, AgentTrustCredentialCodec credentialCodec) {
        this.environment = environment;
        this.objectMapper = objectMapper;
        this.credentialCodec = credentialCodec;
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
        store.put("onboardings", count("agent_onboardings"));

        Map<String, Object> payload = orderedMap();
        payload.put("status", "ready");
        payload.put("mode", "durable_agent_trust_registry");
        payload.put("runtime", "java_spring");
        payload.put("store", store);
        payload.put("active_key", activeKey());
        payload.put("partner_registry_size", store.get("partners"));
        payload.put("revocation_registry_size", store.get("revocations"));
        payload.put("onboarding_registry_size", store.get("onboardings"));
        payload.put("routes", List.of(
            "POST /api/park/delegation-token",
            "POST /api/park/agent-onboarding/register",
            "POST /api/park/agent-onboarding/{agent_id}/certify",
            "POST /api/park/agent-onboarding/verify-credential",
            "GET /api/park/agent-onboarding/{agent_id}",
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
        payload.put("jwks", Map.of("keys", credentialCodec.jwks(keys)));
        payload.put("runtime", "java_spring");
        return payload;
    }

    public Map<String, Object> rotateKey(Map<String, Object> payload) {
        init();
        String actor = stringOrDefault(payload.get("actor"), payload.get("rotated_by"), payload.get("rotatedBy"), "parkpulse_trust_admin");
        String version = sanitizeVersion(stringOrDefault(payload.get("version"), payload.get("key_version"), payload.get("keyVersion"), "v" + Instant.now().getEpochSecond()));
        AgentTrustCredentialCodec.CertificationMaterial material = credentialCodec.certificationMaterial(version);
        String kid = material.kid();
        String now = now();
        Map<String, Object> metadata = Map.of("rotated_by", actor, "protocol_version", "parkpulse-ahp-0.1", "runtime", "java_spring", "signing_boundary", "java_spring_verifier_ready");
        Map<String, Object> record = orderedMap();
        record.put("kid", kid);
        record.put("version", version);
        record.put("alg", material.alg());
        record.put("mode", material.mode());
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
                statement.setString(3, material.alg());
                statement.setString(4, material.mode());
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
        return Map.of("status", "rotated", "active_key", record, "signing", Map.of("kid", kid, "alg", material.alg(), "version", version), "jwks", Map.of("keys", credentialCodec.jwks(List.of(record))), "runtime", "java_spring");
    }

    public Map<String, Object> revocations(int limit) {
        List<Map<String, Object>> revocations = listRevocations(limit);
        return Map.of("status", "ready", "revocations", revocations, "count", revocations.size(), "runtime", "java_spring");
    }

    public Map<String, Object> audit(int limit) {
        List<Map<String, Object>> events = listAudit(limit);
        return Map.of("status", "ready", "events", events, "count", events.size(), "runtime", "java_spring");
    }

    public Map<String, Object> issuerMetadata() {
        Map<String, Object> active = ensureActiveCertificationKey();
        Map<String, Object> signing = orderedMap();
        signing.put("alg", active == null ? "EdDSA" : active.get("alg"));
        signing.put("kid", active == null ? null : active.get("kid"));
        signing.put("mode", active == null ? "not_configured" : active.get("mode"));
        signing.put("version", active == null ? null : active.get("version"));
        signing.put("production_next", "Set PARKPULSE_AGENT_CERT_ED25519_PRIVATE_KEY_B64 from managed KMS or secret storage before third-party production use.");

        Map<String, Object> payload = orderedMap();
        payload.put("status", "ready");
        payload.put("issuer", "parkpulse_agent_onboarding_authority");
        payload.put("protocol_version", "parkpulse-ahp-0.1");
        payload.put("signing", signing);
        payload.put("active_key", active);
        payload.put("jwks", Map.of("keys", credentialCodec.jwks(listKeys())));
        payload.put("verification_endpoint", "/api/park/agent-onboarding/verify-credential");
        payload.put("verification_runtime", "java_spring");
        payload.put("revocation_endpoint", "/api/park/agent-onboarding/revoke-credential");
        payload.put("revocation_runtime", "java_spring");
        payload.put("trust_admin_endpoints", List.of(
            "/api/park/agent-trust/status",
            "/api/park/agent-trust/partners",
            "/api/park/agent-trust/keys",
            "/api/park/agent-trust/keys/rotate",
            "/api/park/agent-trust/revocations",
            "/api/park/agent-trust/audit"
        ));
        payload.put("revocation_registry_size", count("credential_revocations"));
        payload.put("partner_registry_size", count("agent_partners"));
        payload.put("trust_store", status().get("store"));
        payload.put("runtime", "java_spring");
        return payload;
    }

    public Map<String, Object> verifyCertificationCredential(Map<String, Object> payload) {
        init();
        Map<String, Object> credential = mutableMap(payload.get("credential"));
        if (credential.isEmpty()) {
            credential = mutableMap(payload);
        }
        if (credential.isEmpty()) {
            return Map.of("status", "rejected", "signature_status", "missing", "reason", "Certification credential is required.", "runtime", "java_spring");
        }
        String providedSig = stringOrDefault(credential.get("sig"), "");
        Map<String, Object> claims = orderedMap();
        credential.forEach((key, value) -> {
            if (!"sig".equals(key)) {
                claims.put(key, value);
            }
        });
        if (providedSig.isBlank() || !verifyCertificationClaims(claims, providedSig)) {
            return Map.of(
                "status", "rejected",
                "signature_status", "invalid",
                "reason", "Certification credential signature is invalid.",
                "claims", claims,
                "runtime", "java_spring"
            );
        }
        long now = Instant.now().getEpochSecond();
        long exp = longParam(claims.get("exp"), null, 0);
        String certificationId = stringOrDefault(claims.get("certification_id"), claims.get("jti"), "");
        if (!"parkpulse_agent_certification".equals(stringOrDefault(claims.get("token_type"), ""))) {
            return Map.of(
                "status", "rejected",
                "signature_status", "valid",
                "reason", "Credential token_type is not a ParkPulse agent certification.",
                "claims", claims,
                "runtime", "java_spring"
            );
        }
        if (!"parkpulse_agent_onboarding_authority".equals(stringOrDefault(claims.get("issuer"), claims.get("iss"), ""))) {
            return Map.of(
                "status", "rejected",
                "signature_status", "valid",
                "reason", "Certification credential issuer is not trusted.",
                "claims", claims,
                "runtime", "java_spring"
            );
        }
        Map<String, Object> revocation = revocationById(certificationId);
        if (!revocation.isEmpty()) {
            return Map.of(
                "status", "rejected",
                "signature_status", "valid",
                "reason", "Certification credential has been revoked.",
                "claims", claims,
                "revocation", revocation,
                "runtime", "java_spring"
            );
        }
        if (exp <= now) {
            return Map.of(
                "status", "rejected",
                "signature_status", "valid",
                "reason", "Certification credential is expired.",
                "claims", claims,
                "expires_at", exp,
                "runtime", "java_spring"
            );
        }
        if (!"approved_for_guest_route_planning".equals(stringOrDefault(claims.get("approval"), ""))) {
            return Map.of(
                "status", "rejected",
                "signature_status", "valid",
                "reason", "Certification credential does not grant guest route planning approval.",
                "claims", claims,
                "runtime", "java_spring"
            );
        }
        Map<String, Object> result = orderedMap();
        result.put("status", "verified");
        result.put("signature_status", "valid");
        result.put("reason", "Certification credential signature, expiry, and approval are valid.");
        result.put("claims", claims);
        result.put("agent_id", claims.get("agent_id"));
        result.put("certification_id", certificationId);
        result.put("approval", claims.get("approval"));
        result.put("scope", normalizedScopes(claims.get("scope")));
        result.put("expires_at", exp);
        result.put("kid", claims.get("kid"));
        result.put("runtime", "java_spring");
        return result;
    }

    public Map<String, Object> revokeCredential(Map<String, Object> payload) {
        init();
        Map<String, Object> credential = mutableMap(payload.get("credential"));
        String certificationId = stringOrDefault(
            payload.get("certification_id"),
            payload.get("certificationId"),
            credential.get("certification_id"),
            credential.get("jti"),
            ""
        );
        if (certificationId.isBlank()) {
            return Map.of("status", "rejected", "reason", "certification_id or credential is required.", "runtime", "java_spring");
        }
        String actor = stringOrDefault(payload.get("revoked_by"), payload.get("revokedBy"), "parkpulse_agent_onboarding_authority");
        Map<String, Object> record = orderedMap();
        record.put("certification_id", certificationId);
        record.put("agent_id", stringOrDefault(payload.get("agent_id"), credential.get("agent_id"), ""));
        record.put("reason", stringOrDefault(payload.get("reason"), "revoked_by_parkpulse"));
        record.put("revoked_at", now());
        record.put("revoked_by", actor);

        try (Connection connection = connection()) {
            connection.setAutoCommit(false);
            try (var statement = connection.prepareStatement(
                """
                INSERT INTO credential_revocations (certification_id, agent_id, reason, revoked_by, revoked_at, record_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(certification_id) DO UPDATE SET
                    agent_id = excluded.agent_id,
                    reason = excluded.reason,
                    revoked_by = excluded.revoked_by,
                    revoked_at = excluded.revoked_at,
                    record_json = excluded.record_json
                """
            )) {
                statement.setString(1, certificationId);
                statement.setString(2, String.valueOf(record.get("agent_id")));
                statement.setString(3, String.valueOf(record.get("reason")));
                statement.setString(4, actor);
                statement.setString(5, String.valueOf(record.get("revoked_at")));
                statement.setString(6, json(record));
                statement.executeUpdate();
            }
            recordAudit(connection, "credential_revoke", certificationId, record, actor);
            connection.commit();
        } catch (Exception error) {
            throw new IllegalStateException("Unable to revoke agent credential.", error);
        }
        return Map.of("status", "revoked", "revocation", record, "runtime", "java_spring");
    }

    public Map<String, Object> registerOnboarding(Map<String, Object> payload) {
        init();
        String agentId = agentOnboardingId(payload);
        List<String> requestedScopes = withDefault(
            normalizedScopes(payload.get("requested_scopes"), payload.get("requestedScopes"), payload.get("scope")),
            DEFAULT_DELEGATION_SCOPES
        );
        List<String> cannotDo = withDefault(
            normalizedScopes(payload.get("cannot_do"), payload.get("cannotDo")),
            CLIENT_BLOCKED_ACTIONS
        );
        String partnerId = stringOrDefault(payload.get("partner_id"), payload.get("partnerId"), "demo_external_partner");
        Map<String, Object> existingPartner = partnerById(partnerId);
        List<String> partnerAllowedScopes = withDefault(
            normalizedScopes(payload.get("partner_allowed_scopes"), payload.get("partnerAllowedScopes"), existingPartner.get("allowed_scopes")),
            DEFAULT_DELEGATION_SCOPES
        );
        List<String> disallowedScopes = requestedScopes.stream().filter(scope -> !partnerAllowedScopes.contains(scope)).sorted().toList();
        String now = now();

        Map<String, Object> partner = orderedMap();
        partner.put("partner_id", partnerId);
        partner.put("partner_name", stringOrDefault(payload.get("partner_name"), payload.get("partnerName"), existingPartner.get("partner_name"), "Demo External Partner"));
        partner.put("contact", stringOrDefault(payload.get("partner_contact"), payload.get("partnerContact"), existingPartner.get("contact"), ""));
        partner.put("trust_tier", stringOrDefault(payload.get("trust_tier"), payload.get("trustTier"), existingPartner.get("trust_tier"), "sandbox"));
        partner.put("status", stringOrDefault(payload.get("partner_status"), payload.get("partnerStatus"), existingPartner.get("status"), "active"));
        partner.put("allowed_scopes", partnerAllowedScopes);

        Map<String, Object> record = orderedMap();
        record.put("agent_id", agentId);
        record.put("display_name", stringOrDefault(payload.get("display_name"), payload.get("displayName"), agentId));
        record.put("partner", partner);
        record.put("status", "registered");
        record.put("approval", "pending_certification");
        record.put("scope_request_status", disallowedScopes.isEmpty() ? "accepted" : "rejected");
        record.put("disallowed_scopes", disallowedScopes);
        record.put("requested_scopes", requestedScopes);
        record.put("allowed_scopes", List.of());
        record.put("cannot_do", cannotDo);
        record.put("represents", stringOrDefault(payload.get("represents"), "guest_user_123"));
        record.put("use_case", stringOrDefault(payload.get("use_case"), payload.get("useCase"), "guest_route_planning"));
        record.put("registered_at", now);
        record.put("updated_at", now);
        record.put("certification", null);

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
                statement.setString(6, json(partnerAllowedScopes));
                statement.setString(7, createdAt);
                statement.setString(8, now);
                statement.executeUpdate();
            }
            try (var statement = connection.prepareStatement(
                """
                INSERT INTO agent_onboardings (agent_id, partner_id, status, approval, updated_at, record_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    partner_id = excluded.partner_id,
                    status = excluded.status,
                    approval = excluded.approval,
                    updated_at = excluded.updated_at,
                    record_json = excluded.record_json
                """
            )) {
                statement.setString(1, agentId);
                statement.setString(2, partnerId);
                statement.setString(3, "registered");
                statement.setString(4, "pending_certification");
                statement.setString(5, now);
                statement.setString(6, json(record));
                statement.executeUpdate();
            }
            recordAudit(connection, "partner_upsert", partnerId, partner, "agent_onboarding_register");
            recordAudit(connection, "agent_onboarding_register", agentId, record, "agent_onboarding_register");
            connection.commit();
        } catch (Exception error) {
            throw new IllegalStateException("Unable to register agent onboarding.", error);
        }
        return Map.of("status", "registered", "agent", record, "next", "/api/park/agent-onboarding/" + agentId + "/certify", "runtime", "java_spring");
    }

    public Map<String, Object> getOnboarding(String agentId) {
        init();
        try (Connection connection = connection();
             var statement = connection.prepareStatement("SELECT record_json FROM agent_onboardings WHERE agent_id = ?")) {
            statement.setString(1, agentId);
            try (ResultSet rows = statement.executeQuery()) {
                if (rows.next()) {
                    return Map.of("status", "found", "agent", objectMapper.readValue(rows.getString("record_json"), MAP_TYPE), "runtime", "java_spring");
                }
            }
        } catch (Exception error) {
            throw new IllegalStateException("Unable to read agent onboarding.", error);
        }
        throw new NoSuchElementException("Unknown onboarded agent: " + agentId);
    }

    public Map<String, Object> updateOnboardingRecord(String agentId, Map<String, Object> record, String actor) {
        init();
        String partnerId = stringOrDefault(mutableMap(record.get("partner")).get("partner_id"), "");
        String status = stringOrDefault(record.get("status"), "registered");
        String approval = stringOrDefault(record.get("approval"), "pending_certification");
        String now = now();
        record.put("updated_at", now);
        try (Connection connection = connection()) {
            connection.setAutoCommit(false);
            try (var statement = connection.prepareStatement(
                """
                UPDATE agent_onboardings
                SET partner_id = ?, status = ?, approval = ?, updated_at = ?, record_json = ?
                WHERE agent_id = ?
                """
            )) {
                statement.setString(1, partnerId);
                statement.setString(2, status);
                statement.setString(3, approval);
                statement.setString(4, now);
                statement.setString(5, json(record));
                statement.setString(6, agentId);
                if (statement.executeUpdate() == 0) {
                    throw new NoSuchElementException("Unknown onboarded agent: " + agentId);
                }
            }
            recordAudit(connection, "agent_onboarding_certify", agentId, record, actor);
            connection.commit();
            return Map.of("status", "updated", "agent", record, "runtime", "java_spring");
        } catch (NoSuchElementException error) {
            throw error;
        } catch (Exception error) {
            throw new IllegalStateException("Unable to update agent onboarding certification.", error);
        }
    }

    public Map<String, Object> issueDelegationToken(Map<String, Object> payload) {
        long now = Instant.now().getEpochSecond();
        long ttlSeconds = longParam(payload.get("ttl_seconds"), payload.get("ttlSeconds"), 3 * 60 * 60);
        String subject = stringOrDefault(payload.get("sub"), payload.get("subject"), payload.get("represents"), "guest_user_123");
        String agentId = stringOrDefault(payload.get("agent_id"), payload.get("agentId"), "john_personal_agent");
        List<String> scope = withDefault(normalizedScopes(payload.get("scope")), DEFAULT_DELEGATION_SCOPES);
        List<String> cannotDo = withDefault(normalizedScopes(payload.get("cannot_do"), payload.get("cannotDo")), CLIENT_BLOCKED_ACTIONS);

        Map<String, Object> claims = orderedMap();
        claims.put("sub", subject);
        claims.put("agent_id", agentId);
        claims.put("scope", scope);
        claims.put("cannot_do", cannotDo);
        claims.put("iat", now);
        claims.put("exp", now + Math.max(60, Math.min(ttlSeconds, 24 * 60 * 60)));
        claims.put("issuer", "parkpulse_demo_delegation_authority");
        claims.put("token_type", "parkpulse_agent_delegation");
        claims.put("token_id", "deleg_" + sha1(subject + ":" + agentId + ":" + now + ":" + scope).substring(0, 10));

        Map<String, Object> token = orderedMap();
        token.putAll(claims);
        token.put("sig", credentialCodec.signDelegationClaims(claims));
        return Map.of("status", "issued", "token", token, "proof", verifyDelegationToken(token), "runtime", "java_spring");
    }

    public Map<String, Object> issueCertificationCredential(String agentId, Map<String, Object> certification, List<String> allowedScopes) {
        Map<String, Object> active = ensureActiveCertificationKey();
        AgentTrustCredentialCodec.CertificationMaterial material = credentialCodec.materialForKey(active);
        long issuedAt = Instant.now().getEpochSecond();
        long expiresAt = issuedAt + 90L * 24L * 60L * 60L;
        int scoreBasisPoints = (int) Math.round(doubleParam(certification.get("score"), 0.0) * 10000);

        Map<String, Object> claims = orderedMap();
        claims.put("agent_id", agentId);
        claims.put("certification_id", certification.get("certification_id"));
        claims.put("jti", certification.get("certification_id"));
        claims.put("approval", certification.get("approval"));
        claims.put("scope", allowedScopes);
        claims.put("score_basis_points", scoreBasisPoints);
        claims.put("required_cases", requiredCaseNames(certification.get("required_cases")));
        claims.put("iat", issuedAt);
        claims.put("exp", expiresAt);
        claims.put("alg", material.alg());
        claims.put("issuer", "parkpulse_agent_onboarding_authority");
        claims.put("iss", "parkpulse_agent_onboarding_authority");
        claims.put("kid", material.kid());
        claims.put("token_type", "parkpulse_agent_certification");

        Map<String, Object> credential = orderedMap();
        credential.putAll(claims);
        credential.put("sig", credentialCodec.signCertificationClaims(claims, material));
        return credential;
    }

    Map<String, Object> verifyDelegationToken(Map<String, Object> token) {
        if (token == null || token.isEmpty()) {
            return Map.of("status", "rejected", "signature_status", "missing", "reason", "Delegation token is required.", "runtime", "java_spring");
        }
        String providedSig = stringOrDefault(token.get("sig"), "");
        Map<String, Object> claims = orderedMap();
        token.forEach((key, value) -> {
            if (!"sig".equals(key)) {
                claims.put(key, value);
            }
        });
        String expectedSig = credentialCodec.signDelegationClaims(claims);
        if (providedSig.isBlank() || !credentialCodec.constantTimeEquals(providedSig, expectedSig)) {
            return Map.of(
                "status", "rejected",
                "signature_status", "invalid",
                "reason", "Delegation token signature is invalid.",
                "claims", claims,
                "runtime", "java_spring"
            );
        }
        long now = Instant.now().getEpochSecond();
        long exp = longParam(claims.get("exp"), null, 0);
        if (exp <= now) {
            return Map.of(
                "status", "rejected",
                "signature_status", "valid",
                "reason", "Delegation token is expired.",
                "claims", claims,
                "expires_at", exp,
                "runtime", "java_spring"
            );
        }
        Map<String, Object> proof = orderedMap();
        proof.put("status", "verified");
        proof.put("signature_status", "valid");
        proof.put("reason", "Delegation token signature, expiry, and claims are valid.");
        proof.put("claims", claims);
        proof.put("subject", claims.get("sub"));
        proof.put("agent_id", claims.get("agent_id"));
        proof.put("scope", normalizedScopes(claims.get("scope")));
        proof.put("cannot_do", normalizedScopes(claims.get("cannot_do")));
        proof.put("expires_at", exp);
        proof.put("runtime", "java_spring");
        return proof;
    }

    private boolean verifyCertificationClaims(Map<String, Object> claims, String providedSig) {
        String kid = stringOrDefault(claims.get("kid"), "");
        Map<String, Object> key = keyRecord(kid);
        if (key.isEmpty()) {
            return false;
        }
        if (!List.of("active", "retired").contains(stringOrDefault(key.get("status"), ""))) {
            return false;
        }
        return credentialCodec.verifyCertificationClaims(claims, providedSig, key);
    }

    private Map<String, Object> ensureActiveCertificationKey() {
        Map<String, Object> active = activeKey();
        if (active != null) {
            return active;
        }
        AgentTrustCredentialCodec.CertificationMaterial material = credentialCodec.certificationMaterial("v1");
        String now = now();
        Map<String, Object> metadata = Map.of("source", "default_local_key", "protocol_version", "parkpulse-ahp-0.1", "runtime", "java_spring");
        Map<String, Object> record = orderedMap();
        record.put("kid", material.kid());
        record.put("version", material.version());
        record.put("alg", material.alg());
        record.put("mode", material.mode());
        record.put("status", "active");
        record.put("created_at", now);
        record.put("activated_at", now);
        record.put("retired_at", null);
        record.put("metadata", metadata);
        try (Connection connection = connection()) {
            connection.setAutoCommit(false);
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
                statement.setString(1, material.kid());
                statement.setString(2, material.version());
                statement.setString(3, material.alg());
                statement.setString(4, material.mode());
                statement.setString(5, "active");
                statement.setString(6, now);
                statement.setString(7, now);
                statement.setObject(8, null);
                statement.setString(9, json(metadata));
                statement.executeUpdate();
            }
            recordAudit(connection, "key_record", material.kid(), record, "system_default");
            connection.commit();
        } catch (Exception error) {
            throw new IllegalStateException("Unable to initialize default certification key.", error);
        }
        return record;
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
            statement.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_onboardings (
                    agent_id TEXT PRIMARY KEY,
                    partner_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    approval TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    record_json TEXT NOT NULL
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

    private Map<String, Object> partnerById(String partnerId) {
        init();
        try (Connection connection = connection();
             var statement = connection.prepareStatement("SELECT * FROM agent_partners WHERE partner_id = ?")) {
            statement.setString(1, partnerId);
            try (ResultSet rows = statement.executeQuery()) {
                if (rows.next()) {
                    return partnerFromRow(rows);
                }
            }
            return orderedMap();
        } catch (Exception error) {
            throw new IllegalStateException("Unable to read agent-trust partner.", error);
        }
    }

    private Map<String, Object> partnerFromRow(ResultSet rows) throws Exception {
        Map<String, Object> partner = orderedMap();
        partner.put("partner_id", rows.getString("partner_id"));
        partner.put("partner_name", rows.getString("partner_name"));
        partner.put("contact", rows.getString("contact"));
        partner.put("trust_tier", rows.getString("trust_tier"));
        partner.put("status", rows.getString("status"));
        partner.put("allowed_scopes", objectMapper.readValue(rows.getString("allowed_scopes_json"), STRING_LIST_TYPE));
        partner.put("created_at", rows.getString("created_at"));
        partner.put("updated_at", rows.getString("updated_at"));
        return partner;
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

    private Map<String, Object> keyRecord(String kid) {
        init();
        if (kid.isBlank()) {
            return orderedMap();
        }
        try (Connection connection = connection();
             var statement = connection.prepareStatement("SELECT * FROM certification_keys WHERE kid = ?")) {
            statement.setString(1, kid);
            try (ResultSet rows = statement.executeQuery()) {
                if (rows.next()) {
                    return keyFromRow(rows);
                }
            }
            return orderedMap();
        } catch (Exception error) {
            throw new IllegalStateException("Unable to read certification key.", error);
        }
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

    private Map<String, Object> revocationById(String certificationId) {
        init();
        if (certificationId.isBlank()) {
            return orderedMap();
        }
        try (Connection connection = connection();
             var statement = connection.prepareStatement("SELECT record_json FROM credential_revocations WHERE certification_id = ?")) {
            statement.setString(1, certificationId);
            try (ResultSet rows = statement.executeQuery()) {
                if (rows.next()) {
                    return objectMapper.readValue(rows.getString("record_json"), MAP_TYPE);
                }
            }
            return orderedMap();
        } catch (Exception error) {
            throw new IllegalStateException("Unable to read credential revocation.", error);
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

    private List<String> requiredCaseNames(Object value) {
        if (value instanceof Map<?, ?> source) {
            return source.keySet().stream().map(String::valueOf).filter(item -> !item.isBlank()).distinct().sorted().toList();
        }
        return normalizedScopes(value);
    }

    private String agentOnboardingId(Map<String, Object> payload) {
        String raw = stringOrDefault(payload.get("agent_id"), payload.get("agentId"), payload.get("display_name"), payload.get("displayName"), "external_guest_agent");
        String normalized = raw.toLowerCase().replaceAll("[^a-z0-9_]+", "_").replaceAll("^_+|_+$", "");
        return normalized.isBlank() ? "external_guest_agent" : normalized;
    }

    private Map<String, Object> mutableMap(Object value) {
        Map<String, Object> result = orderedMap();
        if (value instanceof Map<?, ?> source) {
            source.forEach((key, item) -> result.put(String.valueOf(key), item));
        }
        return result;
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

    private String sha1(String value) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-1").digest(value.getBytes(java.nio.charset.StandardCharsets.UTF_8)));
        } catch (Exception error) {
            throw new IllegalStateException("Unable to hash delegation token id.", error);
        }
    }

    private double doubleParam(Object value, double defaultValue) {
        if (value instanceof Number number) {
            return number.doubleValue();
        }
        if (value != null && !String.valueOf(value).isBlank()) {
            try {
                return Double.parseDouble(String.valueOf(value));
            } catch (NumberFormatException ignored) {
                return defaultValue;
            }
        }
        return defaultValue;
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

    private String stringOrDefault(Object first, Object second, Object third, Object fourth, String defaultValue) {
        return stringOrDefault(new Object[] {first, second, third, fourth}, defaultValue);
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
