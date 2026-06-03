package com.parkpulse.backend;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Service;

@Service
public class RoleContractService {
    private static final String DEFAULT_SECRET = "parkpulse-local-dev-secret-change-before-production";

    private final Environment environment;

    public RoleContractService(Environment environment) {
        this.environment = environment;
    }

    public Map<String, Object> identityReadiness() {
        Map<String, Object> providerReadiness = identityProviderReadiness();
        boolean externalReady = Boolean.TRUE.equals(providerReadiness.get("external_identity_ready"));
        boolean defaultSecret = DEFAULT_SECRET.equals(roleSecret());

        Map<String, Object> payload = orderedMap();
        payload.put("status", externalReady && !defaultSecret ? "production_ready" : "dev_signed_sessions");
        payload.put("mode", "identity_readiness");
        payload.put("signed_role_required", envBool("PARKPULSE_REQUIRE_SIGNED_ROLE_TOKEN", true));
        payload.put("dev_role_issuer_enabled", devRoleIssuerEnabled());
        payload.put("token_ttl_seconds", roleSessionTtlSeconds());
        payload.putAll(providerReadiness);
        payload.put("production_ready", externalReady && !defaultSecret);
        payload.put(
            "remaining_gap",
            externalReady && !defaultSecret
                ? null
                : "Replace the local dev issuer with Google IAP/OIDC/Firebase and set PARKPULSE_ROLE_AUTH_SECRET before production."
        );
        payload.put("uses_seed_data", false);
        payload.put("loads_bigquery_per_tick", false);
        payload.put("llm_control_authority", false);
        payload.put("runtime", "java_spring");
        return payload;
    }

    public Map<String, Object> roleAccessContracts(String requestedRole) {
        List<Map<String, Object>> roles = roles();
        if (requestedRole != null && !requestedRole.isBlank()) {
            String role = normalizeRole(requestedRole);
            roles = roles.stream().filter(item -> role.equals(item.get("id"))).toList();
        }

        Map<String, Object> payload = orderedMap();
        payload.put("status", roles.isEmpty() ? "not_found" : "ready");
        payload.put("mode", "role_access_contracts");
        payload.put("principle", "Rigid authority boundaries with natural role-specific experiences.");
        payload.put("roles", roles);
        payload.put("role_count", roles.size());
        payload.put("global_boundaries", List.of(
            "No role can bypass policy gates.",
            "Chat/LLM cannot dispatch, set rewards, write labels, promote models, roll back policies, or run arbitrary BigQuery SQL.",
            "BigQuery is batch/offline evidence; it is not loaded every heartbeat tick.",
            "Guest and worker surfaces receive scoped summaries, not internal model or warehouse details."
        ));
        payload.put("route_matrix", Map.of(
            "/customer-emergency", "customer",
            "/human", "onsite_worker",
            "/staff-training", "onsite_worker",
            "/", "ops_team",
            "/monitor", "ops_team",
            "/executive", "ml_ops_admin",
            "/labs", "ml_ops_admin"
        ));
        payload.put("data_products", List.of(
            "live_state",
            "policy_receipt",
            "dispatch_receipt",
            "outcome_ledger",
            "memory_summary",
            "training_summary",
            "bigquery_governed_summary"
        ));
        payload.put("uses_seed_data", false);
        payload.put("loads_bigquery_per_tick", false);
        payload.put("llm_control_authority", false);
        payload.put("runtime", "java_spring");
        return payload;
    }

    private Map<String, Object> identityProviderReadiness() {
        Map<String, Object> providers = orderedMap();
        providers.put("google_iap", envBool("PARKPULSE_TRUST_GOOGLE_IAP", false) || hasText("GOOGLE_IAP_AUDIENCE"));
        providers.put("oidc_proxy", envBool("PARKPULSE_TRUST_OIDC_HEADERS", false) || (hasText("PARKPULSE_OIDC_ISSUER") && hasText("PARKPULSE_OIDC_AUDIENCE")));
        providers.put("firebase_auth", envBool("PARKPULSE_TRUST_FIREBASE_HEADERS", false) || hasText("FIREBASE_PROJECT_ID") || hasText("PARKPULSE_FIREBASE_PROJECT_ID"));

        Map<String, Object> roleMapping = orderedMap();
        roleMapping.put("admin_emails", csvCount("PARKPULSE_ADMIN_EMAILS"));
        roleMapping.put("admin_groups", csvCount("PARKPULSE_ADMIN_GROUPS"));
        roleMapping.put("ops_emails", csvCount("PARKPULSE_OPS_EMAILS"));
        roleMapping.put("ops_groups", csvCount("PARKPULSE_OPS_GROUPS"));
        roleMapping.put("trusted_role_header_enabled", envBool("PARKPULSE_ALLOW_TRUSTED_ROLE_HEADER", false));

        boolean providerConfigured = providers.values().stream().anyMatch(Boolean.TRUE::equals);
        boolean mappingConfigured = roleMapping.entrySet().stream()
            .filter(entry -> !"trusted_role_header_enabled".equals(entry.getKey()))
            .map(Map.Entry::getValue)
            .anyMatch(value -> value instanceof Number number && number.intValue() > 0);

        Map<String, Object> payload = orderedMap();
        payload.put("external_identity_providers", providers);
        payload.put("role_mapping", roleMapping);
        payload.put("external_identity_ready", providerConfigured && mappingConfigured);
        payload.put("required_headers", Map.of(
            "google_iap", List.of("x-goog-authenticated-user-email"),
            "oidc_proxy", List.of("x-parkpulse-verified-email", "x-parkpulse-verified-groups"),
            "firebase_auth", List.of("x-firebase-auth-user-email")
        ));
        payload.put("boundary", "External identity headers are trusted only when the corresponding provider flag is enabled behind a verifying proxy or middleware.");
        return payload;
    }

    private List<Map<String, Object>> roles() {
        return List.of(
            role("customer", "Customer / Guest", "guest_assistance", List.of("read_guest_guidance", "use_guest_chat")),
            role("onsite_worker", "Onsite Worker", "task_execution", List.of("read_worker_tasks", "read_staff_training", "use_staff_training", "acknowledge_dispatch")),
            role("ops_team", "Ops Team", "command_center", List.of("read_identity_status", "read_ops_evidence", "read_staff_training_analytics", "use_ops_chat", "dispatch_live_action", "run_live_outcome_cycle")),
            role("ml_ops_admin", "ML / Ops Admin", "learning_governance", List.of("read_identity_status", "read_platform_status", "manage_platform_store", "read_executive_intelligence", "read_ml_training", "start_offline_training", "manage_agent_trust"))
        );
    }

    private Map<String, Object> role(String id, String label, String surface, List<String> capabilities) {
        Map<String, Object> role = orderedMap();
        role.put("id", id);
        role.put("label", label);
        role.put("surface", surface);
        role.put("capabilities", capabilities);
        role.put("ui_contract", id.equals("ml_ops_admin") ? "Learning-governance surface for offline training and release evidence." : "Role-scoped operational surface with explicit authority limits.");
        role.put("llm_contract", "The LLM may summarize scoped evidence only; governed actions remain outside chat authority.");
        return role;
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

    private String roleSecret() {
        String secret = environment.getProperty("PARKPULSE_ROLE_AUTH_SECRET");
        return secret == null || secret.isBlank() ? DEFAULT_SECRET : secret;
    }

    private boolean hasText(String name) {
        String value = environment.getProperty(name);
        return value != null && !value.isBlank();
    }

    private int csvCount(String name) {
        String value = environment.getProperty(name, "");
        if (value.isBlank()) {
            return 0;
        }
        return (int) List.of(value.split(",")).stream().filter(item -> !item.trim().isBlank()).count();
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

    private static LinkedHashMap<String, Object> orderedMap() {
        return new LinkedHashMap<>();
    }
}
