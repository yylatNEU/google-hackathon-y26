package com.parkpulse.backend;

import jakarta.servlet.http.HttpServletRequest;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Enumeration;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import org.springframework.core.env.Environment;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;

@Service
public class PythonFallbackProxyService {
    private static final Set<String> NO_BODY_METHODS = Set.of("GET", "HEAD", "DELETE", "OPTIONS");
    private static final Set<OwnedRoute> SPRING_OWNED_ROUTES = Set.of(
        new OwnedRoute("POST", "/api/park/auth/dev-session"),
        new OwnedRoute("GET", "/api/park/auth/status"),
        new OwnedRoute("GET", "/api/park/state"),
        new OwnedRoute("GET", "/api/park/state-lite"),
        new OwnedRoute("GET", "/api/park/live-summary"),
        new OwnedRoute("GET", "/api/park/cases"),
        new OwnedRoute("GET", "/api/park/cases/{case_id}/brief"),
        new OwnedRoute("POST", "/api/park/signals/intake"),
        new OwnedRoute("POST", "/api/park/agent-role-run"),
        new OwnedRoute("POST", "/api/park/agent-run"),
        new OwnedRoute("POST", "/api/park/live-feed-agent-run"),
        new OwnedRoute("POST", "/api/park/operator-command"),
        new OwnedRoute("POST", "/api/park/action"),
        new OwnedRoute("POST", "/api/park/ops-chat"),
        new OwnedRoute("POST", "/api/park/copilot-chat"),
        new OwnedRoute("POST", "/api/park/agent-role-refine"),
        new OwnedRoute("GET", "/api/park/full-runtime-status"),
        new OwnedRoute("POST", "/api/park/full-runtime-warmup"),
        new OwnedRoute("GET", "/api/park/warmup-status"),
        new OwnedRoute("GET", "/api/park/agent-ops-ledger"),
        new OwnedRoute("GET", "/api/park/monitor-evidence"),
        new OwnedRoute("GET", "/api/park/policy-doctrine"),
        new OwnedRoute("GET", "/api/park/policy-doctrine/{policy_ref}"),
        new OwnedRoute("GET", "/api/park/agent-monitoring"),
        new OwnedRoute("GET", "/api/park/agent-monitoring/deep"),
        new OwnedRoute("GET", "/api/park/live-feed-health"),
        new OwnedRoute("GET", "/api/park/live-feed-health/summary"),
        new OwnedRoute("POST", "/api/park/live-feed-events"),
        new OwnedRoute("GET", "/api/park/live-feeds/refresh-worker"),
        new OwnedRoute("POST", "/api/park/live-feeds/refresh-stale"),
        new OwnedRoute("GET", "/api/park/live-feeds/{source}"),
        new OwnedRoute("POST", "/api/park/live-feeds/{source}/load"),
        new OwnedRoute("GET", "/api/park/review-training-ledger"),
        new OwnedRoute("POST", "/api/park/review-training-ledger"),
        new OwnedRoute("GET", "/api/park/product-learning/loop"),
        new OwnedRoute("POST", "/api/park/product-learning/issue-ticket"),
        new OwnedRoute("POST", "/api/park/product-learning/training-gap-ticket"),
        new OwnedRoute("POST", "/api/park/product-learning/promote-version"),
        new OwnedRoute("POST", "/api/park/product-learning/rollback-version"),
        new OwnedRoute("POST", "/api/park/product-learning/review-place-resolution"),
        new OwnedRoute("GET", "/api/park/staff-training/scenarios"),
        new OwnedRoute("GET", "/api/park/staff-training/policy-pack"),
        new OwnedRoute("GET", "/api/park/staff-training/agent-context"),
        new OwnedRoute("GET", "/api/park/staff-training/assignments"),
        new OwnedRoute("POST", "/api/park/staff-training/assignments"),
        new OwnedRoute("GET", "/api/park/staff-training/readiness"),
        new OwnedRoute("GET", "/api/park/staff-training/receipts"),
        new OwnedRoute("GET", "/api/park/staff-training/certification-packet"),
        new OwnedRoute("POST", "/api/park/staff-training/receipt-review"),
        new OwnedRoute("POST", "/api/park/staff-training/demo-seed"),
        new OwnedRoute("GET", "/api/park/staff-training/golden-eval"),
        new OwnedRoute("POST", "/api/park/staff-training/sessions"),
        new OwnedRoute("POST", "/api/park/staff-training/turn"),
        new OwnedRoute("POST", "/api/park/staff-training/finish"),
        new OwnedRoute("GET", "/api/park/staff-training/analytics"),
        new OwnedRoute("GET", "/api/park/venue-profile"),
        new OwnedRoute("POST", "/api/park/venue-profile/validate"),
        new OwnedRoute("POST", "/api/park/venue-profile/import/preview"),
        new OwnedRoute("POST", "/api/park/venue-profile/import"),
        new OwnedRoute("GET", "/api/park/venue-profile/synthetic/export"),
        new OwnedRoute("POST", "/api/park/venue-profile/synthetic/activate"),
        new OwnedRoute("GET", "/api/park/accessibility/scope"),
        new OwnedRoute("POST", "/api/park/accessibility/journey"),
        new OwnedRoute("GET", "/api/park/accessibility/memory"),
        new OwnedRoute("POST", "/api/park/accessibility/feedback"),
        new OwnedRoute("GET", "/api/park/accessibility/tools"),
        new OwnedRoute("POST", "/api/park/accessibility/tool"),
        new OwnedRoute("GET", "/api/park/review-label-pipeline"),
        new OwnedRoute("POST", "/api/park/review-label-pipeline/decision"),
        new OwnedRoute("POST", "/api/park/review-label-pipeline/auto-label"),
        new OwnedRoute("GET", "/api/park/review-label-pipeline/decisions"),
        new OwnedRoute("POST", "/api/park/tick"),
        new OwnedRoute("POST", "/api/park/time"),
        new OwnedRoute("POST", "/api/park/causal-impact-demo"),
        new OwnedRoute("GET", "/api/park/episode-fitness"),
        new OwnedRoute("GET", "/api/park/digital-twin-war-room"),
        new OwnedRoute("POST", "/api/park/digital-twin-war-room"),
        new OwnedRoute("POST", "/api/park/digital-twin-war-room/run"),
        new OwnedRoute("POST", "/api/park/digital-twin-war-room/remediate"),
        new OwnedRoute("GET", "/api/park/simulation-facade/ledger"),
        new OwnedRoute("GET", "/api/park/simulation-facade/health"),
        new OwnedRoute("POST", "/api/park/experience-studio/conversation-plan"),
        new OwnedRoute("POST", "/api/park/experience-studio/draft"),
        new OwnedRoute("POST", "/api/park/experience-studio/section-revision"),
        new OwnedRoute("GET", "/api/park/experience-studio/layer-contract"),
        new OwnedRoute("GET", "/api/park/experience-studio/readiness"),
        new OwnedRoute("GET", "/api/park/experience-studio/memory"),
        new OwnedRoute("GET", "/api/park/experience-studio/drafts"),
        new OwnedRoute("POST", "/api/park/experience-studio/drafts"),
        new OwnedRoute("GET", "/api/park/experience-studio/drafts/{draft_id}"),
        new OwnedRoute("POST", "/api/park/experience-studio/drafts/{draft_id}"),
        new OwnedRoute("POST", "/api/park/experience-studio/drafts/{draft_id}/status"),
        new OwnedRoute("GET", "/api/park/experience-studio/handoffs"),
        new OwnedRoute("POST", "/api/park/experience-studio/drafts/{draft_id}/handoff"),
        new OwnedRoute("GET", "/api/park/experience-studio/learning-rules"),
        new OwnedRoute("POST", "/api/park/experience-studio/drafts/{draft_id}/promote-rule"),
        new OwnedRoute("POST", "/api/park/experience-studio/learning-rules/{rule_id}/status"),
        new OwnedRoute("GET", "/api/park/role-access-contracts"),
        new OwnedRoute("GET", "/api/park/reliability"),
        new OwnedRoute("GET", "/api/park/latency-diagnostics"),
        new OwnedRoute("GET", "/api/park/authorization-audit"),
        new OwnedRoute("GET", "/api/park/delivery/contract"),
        new OwnedRoute("GET", "/api/park/delivery/outbox"),
        new OwnedRoute("GET", "/api/park/delivery/gcp-adapters/status"),
        new OwnedRoute("GET", "/api/park/delivery/partner-retries/status"),
        new OwnedRoute("POST", "/api/park/delivery/partner-retries/run"),
        new OwnedRoute("POST", "/api/park/delivery/guest-promotion"),
        new OwnedRoute("POST", "/api/park/delivery/worker-notification"),
        new OwnedRoute("POST", "/api/park/delivery/equipment-command"),
        new OwnedRoute("POST", "/api/park/delivery/acknowledge"),
        new OwnedRoute("POST", "/api/park/delivery/approval-decision"),
        new OwnedRoute("GET", "/api/park/events/contract"),
        new OwnedRoute("GET", "/api/park/events/status"),
        new OwnedRoute("GET", "/api/park/events/ledger"),
        new OwnedRoute("POST", "/api/park/events/receiver/guest-response"),
        new OwnedRoute("POST", "/api/park/events/receiver/worker-acknowledgement"),
        new OwnedRoute("POST", "/api/park/events/receiver/equipment-result"),
        new OwnedRoute("POST", "/api/park/events/eventarc/park-signal"),
        new OwnedRoute("POST", "/api/park/delegation-token"),
        new OwnedRoute("GET", "/api/park/agent-onboarding/issuer"),
        new OwnedRoute("POST", "/api/park/agent-onboarding/register"),
        new OwnedRoute("POST", "/api/park/agent-onboarding/{agent_id}/certify"),
        new OwnedRoute("POST", "/api/park/agent-onboarding/verify-credential"),
        new OwnedRoute("GET", "/api/park/agent-onboarding/{agent_id}"),
        new OwnedRoute("POST", "/api/park/agent-onboarding/revoke-credential"),
        new OwnedRoute("GET", "/api/park/agent-trust/status"),
        new OwnedRoute("GET", "/api/park/agent-trust/partners"),
        new OwnedRoute("POST", "/api/park/agent-trust/partners"),
        new OwnedRoute("GET", "/api/park/agent-trust/keys"),
        new OwnedRoute("POST", "/api/park/agent-trust/keys/rotate"),
        new OwnedRoute("GET", "/api/park/agent-trust/revocations"),
        new OwnedRoute("GET", "/api/park/agent-trust/audit"),
        new OwnedRoute("POST", "/api/park/handshake"),
        new OwnedRoute("GET", "/api/park/session/{session_id}"),
        new OwnedRoute("POST", "/api/park/session/{session_id}/capabilities"),
        new OwnedRoute("POST", "/api/park/session/{session_id}/intent"),
        new OwnedRoute("POST", "/api/park/session/{session_id}/propose"),
        new OwnedRoute("POST", "/api/park/session/{session_id}/counter"),
        new OwnedRoute("POST", "/api/park/session/{session_id}/commit"),
        new OwnedRoute("GET", "/api/park/session/{session_id}/monitor"),
        new OwnedRoute("POST", "/api/park/session/{session_id}/monitor"),
        new OwnedRoute("GET", "/api/park/session/{session_id}/receipt"),
        new OwnedRoute("POST", "/api/park/session/{session_id}/receipt"),
        new OwnedRoute("POST", "/api/park/internal-agents/commerce/evaluate"),
        new OwnedRoute("POST", "/api/park/internal-agents/queue/reroute"),
        new OwnedRoute("GET", "/api/park/platform-store"),
        new OwnedRoute("POST", "/api/park/platform-store/migrate"),
        new OwnedRoute("GET", "/api/park/migration/java-spring/status"),
        new OwnedRoute("GET", "/api/park/backend-gateway/status")
    );
    private static final Set<String> HOP_BY_HOP_HEADERS = Set.of(
        "connection",
        "content-length",
        "expect",
        "host",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "x-parkpulse-spring-gateway",
        "upgrade"
    );

    private final HttpClient httpClient;
    private final Instant startedAt = Instant.now();
    private final int maxRequestBodyBytes;
    private final String pythonBackendUrl;
    private final int timeoutMs;

    public PythonFallbackProxyService(Environment environment) {
        this.pythonBackendUrl = resolvePythonBackendUrl(environment);
        this.timeoutMs = resolveTimeoutMs(environment);
        this.maxRequestBodyBytes = resolveMaxRequestBodyBytes(environment);
        this.httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofMillis(timeoutMs))
            .followRedirects(HttpClient.Redirect.NEVER)
            .build();
    }

    public ResponseEntity<byte[]> forward(HttpServletRequest request, byte[] body) {
        if ("OPTIONS".equalsIgnoreCase(request.getMethod())) {
            HttpHeaders headers = corsHeaders();
            return ResponseEntity.status(HttpStatus.NO_CONTENT).headers(headers).body(new byte[0]);
        }
        OwnedRoute ownedRoute = springOwnedRoute(request);
        if (ownedRoute != null) {
            return blockedSpringOwnedRoute(request, ownedRoute);
        }
        byte[] requestBody = body == null ? new byte[0] : body;
        if (requestBody.length > maxRequestBodyBytes) {
            return payloadTooLarge(requestBody.length);
        }

        URI target = targetUri(request);
        try {
            HttpRequest outbound = buildRequest(request, target, requestBody);
            HttpResponse<byte[]> upstream = httpClient.send(outbound, HttpResponse.BodyHandlers.ofByteArray());
            HttpHeaders headers = responseHeaders(upstream);
            headers.add("x-parkpulse-spring-gateway", "python-fallback");
            return ResponseEntity.status(upstream.statusCode()).headers(headers).body(upstream.body());
        } catch (IOException error) {
            return unavailable(target, error);
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            return unavailable(target, error);
        } catch (IllegalArgumentException error) {
            return unavailable(target, error);
        }
    }

    public Map<String, Object> status() {
        Map<String, Object> payload = orderedMap();
        payload.put("status", "active");
        payload.put("mode", "spring_gateway_for_unmigrated_routes");
        payload.put("python_backend_url", pythonBackendUrl);
        payload.put("timeout_ms", timeoutMs);
        payload.put("max_request_body_bytes", maxRequestBodyBytes);
        payload.put("native_spring_routes", "health/readiness/platform-store authority routes");
        payload.put("fallback_routes", "/api/** and /readyz/deep while route groups migrate one at a time");
        payload.put("spring_owned_route_gate", Map.of("status", "enforced", "route_count", SPRING_OWNED_ROUTES.size(), "behavior", "Spring-owned routes are blocked from Python fallback."));
        payload.put("uptime_ms", Instant.now().toEpochMilli() - startedAt.toEpochMilli());
        payload.put("rollback", "Point clients back at Python directly or stop Spring; no data copy is required.");
        return payload;
    }

    private HttpRequest buildRequest(HttpServletRequest request, URI target, byte[] body) {
        HttpRequest.Builder builder = HttpRequest.newBuilder(target)
            .timeout(Duration.ofMillis(timeoutMs))
            .method(request.getMethod(), requestBodyPublisher(request.getMethod(), body));

        Enumeration<String> names = request.getHeaderNames();
        while (names != null && names.hasMoreElements()) {
            String name = names.nextElement();
            if (isHopByHop(name)) {
                continue;
            }
            Enumeration<String> values = request.getHeaders(name);
            while (values != null && values.hasMoreElements()) {
                builder.header(name, values.nextElement());
            }
        }
        builder.header("x-parkpulse-spring-gateway", "python-fallback");
        return builder.build();
    }

    private HttpRequest.BodyPublisher requestBodyPublisher(String method, byte[] body) {
        if (body.length == 0 && NO_BODY_METHODS.contains(method.toUpperCase(Locale.ROOT))) {
            return HttpRequest.BodyPublishers.noBody();
        }
        return HttpRequest.BodyPublishers.ofByteArray(body);
    }

    private URI targetUri(HttpServletRequest request) {
        StringBuilder uri = new StringBuilder(stripTrailingSlash(pythonBackendUrl));
        uri.append(request.getRequestURI());
        if (request.getQueryString() != null && !request.getQueryString().isBlank()) {
            uri.append('?').append(request.getQueryString());
        }
        return URI.create(uri.toString());
    }

    private HttpHeaders responseHeaders(HttpResponse<byte[]> upstream) {
        HttpHeaders headers = new HttpHeaders();
        upstream.headers().map().forEach((name, values) -> {
            if (!isHopByHop(name)) {
                headers.put(name, new ArrayList<>(values));
            }
        });
        corsHeaders().forEach((name, values) -> {
            if (!headers.containsHeader(name)) {
                headers.put(name, new ArrayList<>(values));
            }
        });
        return headers;
    }

    private ResponseEntity<byte[]> unavailable(URI target, Exception error) {
        String payload = """
            {"status":"unavailable","mode":"spring_python_fallback_gateway","upstream":"%s","readiness_issues":["%s"]}
            """.formatted(target, sanitize(error.getMessage()));
        HttpHeaders headers = corsHeaders();
        headers.add(HttpHeaders.CONTENT_TYPE, "application/json");
        headers.add("x-parkpulse-spring-gateway", "python-fallback");
        return ResponseEntity.status(HttpStatus.BAD_GATEWAY)
            .headers(headers)
            .body(payload.getBytes(java.nio.charset.StandardCharsets.UTF_8));
    }

    private ResponseEntity<byte[]> payloadTooLarge(int bodyBytes) {
        String payload = """
            {"status":"blocked","mode":"spring_python_fallback_gateway","readiness_issues":["request body exceeds fallback gateway limit"],"body_bytes":%d,"max_request_body_bytes":%d}
            """.formatted(bodyBytes, maxRequestBodyBytes);
        HttpHeaders headers = corsHeaders();
        headers.add(HttpHeaders.CONTENT_TYPE, "application/json");
        headers.add("x-parkpulse-spring-gateway", "python-fallback");
        return ResponseEntity.status(HttpStatus.PAYLOAD_TOO_LARGE)
            .headers(headers)
            .body(payload.getBytes(java.nio.charset.StandardCharsets.UTF_8));
    }

    private ResponseEntity<byte[]> blockedSpringOwnedRoute(HttpServletRequest request, OwnedRoute ownedRoute) {
        String payload = """
            {"status":"blocked","mode":"spring_owned_route_fallback_gate","route":"%s %s","matched_owned_route":"%s %s","reason":"Spring-owned routes must be served by native Spring handlers and cannot fall back to Python."}
            """.formatted(
                sanitize(request.getMethod()),
                sanitize(request.getRequestURI()),
                ownedRoute.method(),
                ownedRoute.pattern()
            );
        HttpHeaders headers = corsHeaders();
        headers.add(HttpHeaders.CONTENT_TYPE, "application/json");
        headers.add("x-parkpulse-spring-gateway", "spring-owned-route-blocked");
        return ResponseEntity.status(HttpStatus.CONFLICT)
            .headers(headers)
            .body(payload.getBytes(java.nio.charset.StandardCharsets.UTF_8));
    }

    private OwnedRoute springOwnedRoute(HttpServletRequest request) {
        String method = request.getMethod() == null ? "" : request.getMethod().toUpperCase(Locale.ROOT);
        String path = request.getRequestURI();
        return SPRING_OWNED_ROUTES.stream()
            .filter(route -> route.method().equals(method))
            .filter(route -> pathMatches(route.pattern(), path))
            .findFirst()
            .orElse(null);
    }

    private boolean pathMatches(String pattern, String path) {
        String[] patternSegments = trimSlashes(pattern).split("/");
        String[] pathSegments = trimSlashes(path).split("/");
        if (patternSegments.length != pathSegments.length) {
            return false;
        }
        for (int index = 0; index < patternSegments.length; index++) {
            String patternSegment = patternSegments[index];
            if (patternSegment.startsWith("{") && patternSegment.endsWith("}")) {
                if (pathSegments[index].isBlank()) {
                    return false;
                }
                continue;
            }
            if (!patternSegment.equals(pathSegments[index])) {
                return false;
            }
        }
        return true;
    }

    private HttpHeaders corsHeaders() {
        HttpHeaders headers = new HttpHeaders();
        headers.add("access-control-allow-origin", "*");
        headers.add("access-control-allow-methods", "*");
        headers.add("access-control-allow-headers", "*");
        return headers;
    }

    private boolean isHopByHop(String name) {
        return HOP_BY_HOP_HEADERS.contains(name.toLowerCase(Locale.ROOT));
    }

    private String resolvePythonBackendUrl(Environment environment) {
        String value = environment.getProperty("PARKPULSE_PYTHON_BACKEND_URL");
        if (value == null || value.isBlank()) {
            value = environment.getProperty("parkpulse.python-backend-url");
        }
        String resolved = value == null || value.isBlank() ? "http://127.0.0.1:8000" : stripTrailingSlash(value);
        URI uri = URI.create(resolved);
        String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase(Locale.ROOT);
        if (!Set.of("http", "https").contains(scheme)) {
            throw new IllegalArgumentException("PARKPULSE_PYTHON_BACKEND_URL must use http or https.");
        }
        return resolved;
    }

    private int resolveTimeoutMs(Environment environment) {
        String raw = environment.getProperty("PARKPULSE_PYTHON_BACKEND_TIMEOUT_MS");
        if (raw == null || raw.isBlank()) {
            raw = environment.getProperty("parkpulse.python-backend-timeout-ms", "2500");
        }
        try {
            return Math.max(500, Integer.parseInt(raw));
        } catch (NumberFormatException error) {
            return 2500;
        }
    }

    private int resolveMaxRequestBodyBytes(Environment environment) {
        String raw = environment.getProperty("PARKPULSE_PYTHON_BACKEND_MAX_BODY_BYTES");
        if (raw == null || raw.isBlank()) {
            raw = environment.getProperty("parkpulse.python-backend-max-body-bytes", "2097152");
        }
        try {
            return Math.max(1024, Integer.parseInt(raw));
        } catch (NumberFormatException error) {
            return 2097152;
        }
    }

    private String stripTrailingSlash(String value) {
        return value.endsWith("/") ? value.substring(0, value.length() - 1) : value;
    }

    private String trimSlashes(String value) {
        return value.replaceAll("^/+|/+$", "");
    }

    private String sanitize(String value) {
        return value == null ? "upstream request failed" : value.replace("\"", "'");
    }

    private static LinkedHashMap<String, Object> orderedMap() {
        return new LinkedHashMap<>();
    }

    private record OwnedRoute(String method, String pattern) {}
}
