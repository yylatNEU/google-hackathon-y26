package com.parkpulse.backend;

import jakarta.servlet.http.HttpServletRequest;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.Base64;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.core.env.Environment;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

@Service
public class RoleAuthService {
    private static final String DEFAULT_SECRET = "parkpulse-local-dev-secret-change-before-production";
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

    private final Environment environment;
    private final ObjectMapper objectMapper;

    public RoleAuthService(Environment environment, ObjectMapper objectMapper) {
        this.environment = environment;
        this.objectMapper = objectMapper;
    }

    public Map<String, Object> requireCapability(HttpServletRequest request, String capability) {
        Map<String, Object> identity = verify(request);
        if (!Boolean.TRUE.equals(identity.get("authenticated"))) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, String.valueOf(identity.getOrDefault("reason", "Signed role session token is required.")));
        }
        String role = String.valueOf(identity.getOrDefault("role", ""));
        if (!isAllowed(role, capability)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Role " + role + " is not authorized for " + capability + ".");
        }
        return identity;
    }

    private Map<String, Object> verify(HttpServletRequest request) {
        String token = extractToken(request);
        if (token == null || token.isBlank()) {
            return Map.of("status", "missing", "authenticated", false, "reason", "Missing signed role session token.");
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
        if (!List.of("customer", "onsite_worker", "ops_team", "ml_ops_admin").contains(role)) {
            return Map.of("status", "invalid", "authenticated", false, "reason", "Role session contains an unknown role.", "claims", claims);
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
        if ("read_platform_status".equals(capability) || "manage_platform_store".equals(capability)) {
            return "ml_ops_admin".equals(role);
        }
        return false;
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
}
