package com.parkpulse.backend;

import jakarta.servlet.http.HttpServletRequest;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.env.Environment;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

@Service
public class RoleAuthService {
    private static final String DEFAULT_SECRET = "parkpulse-local-dev-secret-change-before-production";
    private static final String DEFAULT_ISSUER = "parkpulse-local-dev";
    private static final String DEFAULT_AUDIENCE = "parkpulse-role-access";
    private static final Set<String> KNOWN_ROLES = Set.of("customer", "onsite_worker", "ops_team", "ml_ops_admin");
    private static final Set<String> IDENTITY_READ_ROLES = Set.of("ops_team", "ml_ops_admin");
    private static final Set<String> OPS_EVIDENCE_ROLES = Set.of("ops_team", "ml_ops_admin");
    private static final Set<String> WORKER_TASK_ROLES = Set.of("onsite_worker", "ops_team");
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

    private final Environment environment;
    private final ObjectMapper objectMapper;
    private final AuthorizationAuditService authorizationAuditService;

    @Autowired
    public RoleAuthService(Environment environment, ObjectMapper objectMapper, AuthorizationAuditService authorizationAuditService) {
        this.environment = environment;
        this.objectMapper = objectMapper;
        this.authorizationAuditService = authorizationAuditService;
    }

    public RoleAuthService(Environment environment, ObjectMapper objectMapper) {
        this.environment = environment;
        this.objectMapper = objectMapper;
        this.authorizationAuditService = null;
    }

    public Map<String, Object> requireCapability(HttpServletRequest request, String capability) {
        Map<String, Object> identity = verify(request);
        if (!Boolean.TRUE.equals(identity.get("authenticated"))) {
            audit(request, capability, identity, false, String.valueOf(identity.getOrDefault("reason", "unauthenticated")));
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, String.valueOf(identity.getOrDefault("reason", "Signed role session token is required.")));
        }
        String role = String.valueOf(identity.getOrDefault("role", ""));
        if (!isAllowed(role, capability)) {
            audit(request, capability, identity, false, "role_not_authorized");
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Role " + role + " is not authorized for " + capability + ".");
        }
        audit(request, capability, identity, true, "role_allowed");
        return identity;
    }

    public Map<String, Object> issueDevSession(String requestedRole, String requestedSubject) {
        if (!devRoleIssuerEnabled()) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Local dev role session issuer is disabled.");
        }
        String role = normalizeRole(requestedRole == null || requestedRole.isBlank() ? "ops_team" : requestedRole);
        if (!knownRole(role)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Unknown ParkPulse role: " + role);
        }
        String subject = requestedSubject == null || requestedSubject.isBlank() ? "local-dev-operator" : requestedSubject;
        long issuedAt = Instant.now().getEpochSecond();
        long expiresAt = issuedAt + roleSessionTtlSeconds();

        Map<String, Object> claims = new TreeMap<>();
        claims.put("aud", expectedAudience());
        claims.put("exp", expiresAt);
        claims.put("iat", issuedAt);
        claims.put("iss", expectedIssuer());
        claims.put("role", role);
        claims.put("sub", subject);

        String payloadPart = base64Url(jsonBytes(claims));
        String token = "pprole." + payloadPart + "." + base64Url(hmac(payloadPart, roleSecret()));

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("status", "issued");
        response.put("mode", "signed_role_session_issuer");
        response.put("role", role);
        response.put("subject", subject);
        response.put("token", token);
        response.put("token_type", "Bearer");
        response.put("expires_at", expiresAt);
        response.put("signed_role_required", signedRoleRequired());
        response.put("dev_issuer", true);
        response.put("runtime", "java_spring");
        response.put("boundary", "Local dev issuer only. Production should replace this with Google IAP, OIDC, or another server-verified identity provider.");
        return response;
    }

    private Map<String, Object> verify(HttpServletRequest request) {
        String token = extractToken(request);
        if (token == null || token.isBlank()) {
            return Map.of("status", "missing", "authenticated", false, "reason", "Missing signed role session token.");
        }
        if (isProductionEnvironment() && DEFAULT_SECRET.equals(roleSecret())) {
            return Map.of("status", "invalid", "authenticated", false, "reason", "Default local role session secret is not accepted in production.");
        }
        String[] parts = token.trim().split("\\.");
        if (parts.length != 3 || !"pprole".equals(parts[0])) {
            return Map.of("status", "invalid", "authenticated", false, "reason", "Role session token has an invalid format.");
        }
        byte[] expected = hmac(parts[1], roleSecret());
        byte[] supplied;
        try {
            supplied = base64UrlDecode(parts[2]);
        } catch (IllegalArgumentException error) {
            return Map.of("status", "invalid", "authenticated", false, "reason", "Role session signature is not decodable.");
        }
        if (!MessageDigest.isEqual(expected, supplied)) {
            return Map.of("status", "invalid", "authenticated", false, "reason", "Role session signature does not match.");
        }
        Map<String, Object> claims;
        try {
            claims = objectMapper.readValue(base64UrlDecode(parts[1]), MAP_TYPE);
        } catch (Exception error) {
            return Map.of("status", "invalid", "authenticated", false, "reason", "Role session payload is not decodable.");
        }
        String role = normalizeRole(String.valueOf(claims.getOrDefault("role", "")));
        if (!knownRole(role)) {
            return Map.of("status", "invalid", "authenticated", false, "reason", "Role session contains an unknown role.", "claims", claims);
        }
        String audience = String.valueOf(claims.getOrDefault("aud", ""));
        if (!expectedAudience().equals(audience)) {
            return Map.of("status", "invalid", "authenticated", false, "reason", "Role session audience does not match.", "role", role);
        }
        String issuer = String.valueOf(claims.getOrDefault("iss", ""));
        if (!expectedIssuer().equals(issuer)) {
            return Map.of("status", "invalid", "authenticated", false, "reason", "Role session issuer does not match.", "role", role);
        }
        long issuedAt = toLong(claims.get("iat"));
        if (issuedAt > Instant.now().plusSeconds(60).getEpochSecond()) {
            return Map.of("status", "invalid", "authenticated", false, "reason", "Role session token was issued in the future.", "role", role);
        }
        long expiresAt = toLong(claims.get("exp"));
        if (expiresAt <= Instant.now().getEpochSecond()) {
            return Map.of("status", "expired", "authenticated", false, "reason", "Role session token is expired.", "role", role, "claims", claims);
        }
        return Map.of(
            "status", "authenticated",
            "authenticated", true,
            "role", role,
            "subject", String.valueOf(claims.getOrDefault("sub", "")),
            "issuer", String.valueOf(claims.getOrDefault("iss", "")),
            "expires_at", expiresAt,
            "claims", claims
        );
    }

    private boolean isAllowed(String role, String capability) {
        if ("read_role_contracts".equals(capability)) {
            return knownRole(role);
        }
        if ("read_identity_status".equals(capability)) {
            return IDENTITY_READ_ROLES.contains(role);
        }
        if ("read_reliability_status".equals(capability) || "read_ops_evidence".equals(capability)) {
            return OPS_EVIDENCE_ROLES.contains(role);
        }
        if ("read_worker_tasks".equals(capability) || "acknowledge_dispatch".equals(capability)) {
            return WORKER_TASK_ROLES.contains(role);
        }
        if ("read_staff_training".equals(capability) || "use_staff_training".equals(capability)) {
            return "onsite_worker".equals(role) || "ops_team".equals(role) || "ml_ops_admin".equals(role);
        }
        if ("read_staff_training_analytics".equals(capability)) {
            return "ops_team".equals(role) || "ml_ops_admin".equals(role);
        }
        if ("create_park_issue_ticket".equals(capability)) {
            return "customer".equals(role) || "onsite_worker".equals(role) || "ops_team".equals(role);
        }
        if ("create_training_gap_ticket".equals(capability) || "read_product_learning".equals(capability)) {
            return "ops_team".equals(role) || "ml_ops_admin".equals(role);
        }
        if ("manage_product_learning".equals(capability)) {
            return "ops_team".equals(role) || "ml_ops_admin".equals(role);
        }
        if ("read_experience_studio".equals(capability) || "use_experience_studio".equals(capability) || "review_experience_studio".equals(capability)) {
            return "ops_team".equals(role) || "ml_ops_admin".equals(role);
        }
        if ("read_venue_profile".equals(capability)) {
            return "ops_team".equals(role) || "ml_ops_admin".equals(role);
        }
        if ("manage_venue_profile".equals(capability)) {
            return "ml_ops_admin".equals(role);
        }
        if ("use_accessibility_journey".equals(capability)) {
            return "customer".equals(role) || "onsite_worker".equals(role) || "ops_team".equals(role) || "ml_ops_admin".equals(role);
        }
        if ("read_review_label_pipeline".equals(capability) || "record_review_label".equals(capability)) {
            return "ops_team".equals(role) || "ml_ops_admin".equals(role);
        }
        if ("read_simulation_evidence".equals(capability) || "mutate_simulation_state".equals(capability) || "run_simulation_exercise".equals(capability)) {
            return "ops_team".equals(role) || "ml_ops_admin".equals(role);
        }
        if ("run_agent_orchestration".equals(capability) || "use_ops_chat".equals(capability)) {
            return "ops_team".equals(role) || "ml_ops_admin".equals(role);
        }
        if ("dispatch_live_action".equals(capability)) {
            return "ops_team".equals(role);
        }
        if ("run_live_outcome_cycle".equals(capability)) {
            return "ops_team".equals(role) || "ml_ops_admin".equals(role);
        }
        if ("read_platform_status".equals(capability) || "manage_platform_store".equals(capability) || "manage_agent_trust".equals(capability)) {
            return "ml_ops_admin".equals(role);
        }
        return false;
    }

    private void audit(HttpServletRequest request, String capability, Map<String, Object> identity, boolean allowed, String reason) {
        if (authorizationAuditService != null) {
            authorizationAuditService.record(request, capability, identity, allowed, reason);
        }
    }

    private String extractToken(HttpServletRequest request) {
        String explicit = request.getHeader("x-parkpulse-role-token");
        if (explicit != null && !explicit.isBlank()) {
            return explicit;
        }
        String authorization = request.getHeader("authorization");
        if (authorization != null && authorization.toLowerCase(Locale.ROOT).startsWith("bearer ")) {
            return authorization.substring("bearer ".length()).trim();
        }
        return null;
    }

    private String roleSecret() {
        String secret = environment.getProperty("PARKPULSE_ROLE_AUTH_SECRET");
        return secret == null || secret.isBlank() ? DEFAULT_SECRET : secret;
    }

    private String expectedIssuer() {
        String issuer = environment.getProperty("PARKPULSE_ROLE_TOKEN_ISSUER");
        return issuer == null || issuer.isBlank() ? DEFAULT_ISSUER : issuer;
    }

    private String expectedAudience() {
        String audience = environment.getProperty("PARKPULSE_ROLE_TOKEN_AUDIENCE");
        return audience == null || audience.isBlank() ? DEFAULT_AUDIENCE : audience;
    }

    private boolean signedRoleRequired() {
        return envBool("PARKPULSE_REQUIRE_SIGNED_ROLE_TOKEN", true);
    }

    private boolean devRoleIssuerEnabled() {
        String configured = environment.getProperty("PARKPULSE_ENABLE_DEV_ROLE_ISSUER");
        if (isProductionEnvironment() && !envBool("PARKPULSE_ALLOW_PRODUCTION_DEV_ROLE_ISSUER", false)) {
            return false;
        }
        if (configured != null) {
            return truthy(configured, true);
        }
        return !isProductionEnvironment();
    }

    private long roleSessionTtlSeconds() {
        String raw = environment.getProperty("PARKPULSE_ROLE_SESSION_TTL_SECONDS", "3600");
        try {
            return Math.max(300, Long.parseLong(raw));
        } catch (NumberFormatException error) {
            return 3600;
        }
    }

    private byte[] hmac(String payload, String secret) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            return mac.doFinal(payload.getBytes(StandardCharsets.US_ASCII));
        } catch (Exception error) {
            throw new IllegalStateException("Unable to verify role session token.", error);
        }
    }

    private byte[] base64UrlDecode(String value) {
        return Base64.getUrlDecoder().decode(value);
    }

    private String base64Url(byte[] value) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(value);
    }

    private byte[] jsonBytes(Map<String, Object> payload) {
        try {
            return objectMapper.writeValueAsBytes(payload);
        } catch (Exception error) {
            throw new IllegalStateException("Unable to encode role session payload.", error);
        }
    }

    private long toLong(Object value) {
        if (value instanceof Number number) {
            return number.longValue();
        }
        try {
            return Long.parseLong(String.valueOf(value));
        } catch (NumberFormatException error) {
            return 0;
        }
    }

    private String normalizeRole(String role) {
        String normalized = role == null ? "" : role.trim().toLowerCase(Locale.ROOT).replace("-", "_");
        return switch (normalized) {
            case "guest" -> "customer";
            case "worker", "onsite" -> "onsite_worker";
            case "ops" -> "ops_team";
            case "admin", "ml_admin" -> "ml_ops_admin";
            default -> normalized;
        };
    }

    private boolean knownRole(String role) {
        return KNOWN_ROLES.contains(role);
    }

    private boolean envBool(String name, boolean defaultValue) {
        return truthy(environment.getProperty(name), defaultValue);
    }

    private boolean truthy(String value, boolean defaultValue) {
        if (value == null) {
            return defaultValue;
        }
        return List.of("1", "true", "yes", "on").contains(value.trim().toLowerCase(Locale.ROOT));
    }

    private boolean isProductionEnvironment() {
        String appEnv = environment.getProperty("PARKPULSE_ENV");
        if (appEnv == null || appEnv.isBlank()) {
            appEnv = environment.getProperty("ENVIRONMENT", "local");
        }
        return Set.of("prod", "production").contains(appEnv.trim().toLowerCase(Locale.ROOT));
    }
}
