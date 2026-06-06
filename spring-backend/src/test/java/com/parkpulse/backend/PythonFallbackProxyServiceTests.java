package com.parkpulse.backend;

import static org.assertj.core.api.Assertions.assertThat;

import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.Executors;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.mock.web.MockHttpServletRequest;

class PythonFallbackProxyServiceTests {
    private HttpServer server;

    @AfterEach
    void stopServer() {
        if (server != null) {
            server.stop(0);
        }
    }

    @Test
    void forwardsUnmigratedRequestsToPythonBackend() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/api/park/state", exchange -> {
            byte[] requestBody = exchange.getRequestBody().readAllBytes();
            String escapedBody = new String(requestBody, StandardCharsets.UTF_8).replace("\"", "\\\"");
            String response = """
                {"method":"%s","path":"%s","body":"%s","gateway":"%s"}
                """.formatted(
                    exchange.getRequestMethod(),
                    exchange.getRequestURI().toString(),
                    escapedBody,
                    exchange.getRequestHeaders().getFirst("x-parkpulse-spring-gateway")
                );
            byte[] bytes = response.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("content-type", "application/json");
            exchange.sendResponseHeaders(202, bytes.length);
            exchange.getResponseBody().write(bytes);
            exchange.close();
        });
        server.setExecutor(Executors.newSingleThreadExecutor());
        server.start();

        MockEnvironment environment = new MockEnvironment()
            .withProperty("parkpulse.python-backend-url", "http://127.0.0.1:" + server.getAddress().getPort())
            .withProperty("parkpulse.python-backend-timeout-ms", "2000");
        PythonFallbackProxyService service = new PythonFallbackProxyService(environment);

        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/api/park/state");
        request.setQueryString("detail=full");
        request.addHeader("content-type", "application/json");
        request.addHeader("x-parkpulse-spring-gateway", "spoofed-client-value");
        byte[] body = "{\"ok\":true}".getBytes(StandardCharsets.UTF_8);

        ResponseEntity<byte[]> response = service.forward(request, body);

        assertThat(response.getStatusCode().value()).isEqualTo(202);
        assertThat(response.getHeaders().getFirst("x-parkpulse-spring-gateway")).isEqualTo("python-fallback");
        assertThat(new String(response.getBody(), StandardCharsets.UTF_8))
            .contains("\"method\":\"POST\"")
            .contains("\"path\":\"/api/park/state?detail=full\"")
            .contains("\"body\":\"{\\\"ok\\\":true}\"")
            .contains("\"gateway\":\"python-fallback\"");
    }

    @Test
    void reportsUnavailableWhenPythonBackendCannotBeReached() {
        MockEnvironment environment = new MockEnvironment()
            .withProperty("parkpulse.python-backend-url", "http://127.0.0.1:9")
            .withProperty("parkpulse.python-backend-timeout-ms", "500");
        PythonFallbackProxyService service = new PythonFallbackProxyService(environment);
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/park/unmigrated-test-route");

        ResponseEntity<byte[]> response = service.forward(request, new byte[0]);

        assertThat(response.getStatusCode().value()).isEqualTo(502);
        assertThat(new String(response.getBody(), StandardCharsets.UTF_8)).contains("spring_python_fallback_gateway");
    }

    @Test
    void blocksOversizedFallbackRequestBodiesBeforeForwarding() {
        MockEnvironment environment = new MockEnvironment()
            .withProperty("parkpulse.python-backend-url", "http://127.0.0.1:8000")
            .withProperty("parkpulse.python-backend-max-body-bytes", "1024");
        PythonFallbackProxyService service = new PythonFallbackProxyService(environment);
        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/api/park/state");

        ResponseEntity<byte[]> response = service.forward(request, new byte[1025]);

        assertThat(response.getStatusCode().value()).isEqualTo(413);
        assertThat(new String(response.getBody(), StandardCharsets.UTF_8)).contains("request body exceeds fallback gateway limit");
    }

    @Test
    void blocksSpringOwnedRoutesBeforeFallbackForwarding() {
        MockEnvironment environment = new MockEnvironment()
            .withProperty("parkpulse.python-backend-url", "http://127.0.0.1:8000");
        PythonFallbackProxyService service = new PythonFallbackProxyService(environment);
        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/api/park/agent-onboarding/spring_certified_agent/certify");

        ResponseEntity<byte[]> response = service.forward(request, "{}".getBytes(StandardCharsets.UTF_8));

        String payload = new String(response.getBody(), StandardCharsets.UTF_8);
        assertThat(response.getStatusCode().value()).isEqualTo(409);
        assertThat(response.getHeaders().getFirst("x-parkpulse-spring-gateway")).isEqualTo("spring-owned-route-blocked");
        assertThat(payload)
            .contains("spring_owned_route_fallback_gate")
            .contains("POST /api/park/agent-onboarding/{agent_id}/certify")
            .contains("cannot fall back to Python");

        MockHttpServletRequest deliveryRequest = new MockHttpServletRequest("POST", "/api/park/delivery/guest-promotion");
        ResponseEntity<byte[]> deliveryResponse = service.forward(deliveryRequest, "{}".getBytes(StandardCharsets.UTF_8));

        String deliveryPayload = new String(deliveryResponse.getBody(), StandardCharsets.UTF_8);
        assertThat(deliveryResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(deliveryPayload)
            .contains("spring_owned_route_fallback_gate")
            .contains("POST /api/park/delivery/guest-promotion");

        MockHttpServletRequest adapterStatusRequest = new MockHttpServletRequest("GET", "/api/park/delivery/gcp-adapters/status");
        ResponseEntity<byte[]> adapterStatusResponse = service.forward(adapterStatusRequest, new byte[0]);

        assertThat(adapterStatusResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(adapterStatusResponse.getBody(), StandardCharsets.UTF_8))
            .contains("GET /api/park/delivery/gcp-adapters/status");

        MockHttpServletRequest stateLiteRequest = new MockHttpServletRequest("GET", "/api/park/state-lite");
        ResponseEntity<byte[]> stateLiteResponse = service.forward(stateLiteRequest, new byte[0]);

        assertThat(stateLiteResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(stateLiteResponse.getBody(), StandardCharsets.UTF_8))
            .contains("GET /api/park/state-lite");

        MockHttpServletRequest stateRequest = new MockHttpServletRequest("GET", "/api/park/state");
        ResponseEntity<byte[]> stateResponse = service.forward(stateRequest, new byte[0]);

        assertThat(stateResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(stateResponse.getBody(), StandardCharsets.UTF_8))
            .contains("GET /api/park/state");

        MockHttpServletRequest liveSummaryRequest = new MockHttpServletRequest("GET", "/api/park/live-summary");
        ResponseEntity<byte[]> liveSummaryResponse = service.forward(liveSummaryRequest, new byte[0]);

        assertThat(liveSummaryResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(liveSummaryResponse.getBody(), StandardCharsets.UTF_8))
            .contains("GET /api/park/live-summary");

        MockHttpServletRequest casesRequest = new MockHttpServletRequest("GET", "/api/park/cases");
        ResponseEntity<byte[]> casesResponse = service.forward(casesRequest, new byte[0]);

        assertThat(casesResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(casesResponse.getBody(), StandardCharsets.UTF_8))
            .contains("GET /api/park/cases");

        MockHttpServletRequest caseBriefRequest = new MockHttpServletRequest("GET", "/api/park/cases/spring_queue_pressure/brief");
        ResponseEntity<byte[]> caseBriefResponse = service.forward(caseBriefRequest, new byte[0]);

        assertThat(caseBriefResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(caseBriefResponse.getBody(), StandardCharsets.UTF_8))
            .contains("GET /api/park/cases/{case_id}/brief");

        MockHttpServletRequest monitorEvidenceRequest = new MockHttpServletRequest("GET", "/api/park/monitor-evidence");
        ResponseEntity<byte[]> monitorEvidenceResponse = service.forward(monitorEvidenceRequest, new byte[0]);

        assertThat(monitorEvidenceResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(monitorEvidenceResponse.getBody(), StandardCharsets.UTF_8))
            .contains("GET /api/park/monitor-evidence");

        MockHttpServletRequest doctrineRequest = new MockHttpServletRequest("GET", "/api/park/policy-doctrine/PARK-OPS-001");
        ResponseEntity<byte[]> doctrineResponse = service.forward(doctrineRequest, new byte[0]);

        assertThat(doctrineResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(doctrineResponse.getBody(), StandardCharsets.UTF_8))
            .contains("GET /api/park/policy-doctrine/{policy_ref}");

        MockHttpServletRequest monitoringRequest = new MockHttpServletRequest("GET", "/api/park/agent-monitoring");
        ResponseEntity<byte[]> monitoringResponse = service.forward(monitoringRequest, new byte[0]);

        assertThat(monitoringResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(monitoringResponse.getBody(), StandardCharsets.UTF_8))
            .contains("GET /api/park/agent-monitoring");

        MockHttpServletRequest partnerRetryRequest = new MockHttpServletRequest("POST", "/api/park/delivery/partner-retries/run");
        ResponseEntity<byte[]> partnerRetryResponse = service.forward(partnerRetryRequest, "{}".getBytes(StandardCharsets.UTF_8));

        assertThat(partnerRetryResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(partnerRetryResponse.getBody(), StandardCharsets.UTF_8))
            .contains("POST /api/park/delivery/partner-retries/run");

        MockHttpServletRequest eventContractRequest = new MockHttpServletRequest("GET", "/api/park/events/contract");
        ResponseEntity<byte[]> eventContractResponse = service.forward(eventContractRequest, new byte[0]);

        assertThat(eventContractResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(eventContractResponse.getBody(), StandardCharsets.UTF_8))
            .contains("GET /api/park/events/contract");

        MockHttpServletRequest liveFeedHealthRequest = new MockHttpServletRequest("GET", "/api/park/live-feed-health");
        ResponseEntity<byte[]> liveFeedHealthResponse = service.forward(liveFeedHealthRequest, new byte[0]);

        assertThat(liveFeedHealthResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(liveFeedHealthResponse.getBody(), StandardCharsets.UTF_8))
            .contains("GET /api/park/live-feed-health");

        MockHttpServletRequest liveFeedConfigRequest = new MockHttpServletRequest("GET", "/api/park/live-feeds/weather");
        ResponseEntity<byte[]> liveFeedConfigResponse = service.forward(liveFeedConfigRequest, new byte[0]);

        assertThat(liveFeedConfigResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(liveFeedConfigResponse.getBody(), StandardCharsets.UTF_8))
            .contains("GET /api/park/live-feeds/{source}");

        MockHttpServletRequest liveFeedLoadRequest = new MockHttpServletRequest("POST", "/api/park/live-feeds/ride-ops/load");
        ResponseEntity<byte[]> liveFeedLoadResponse = service.forward(liveFeedLoadRequest, "{}".getBytes(StandardCharsets.UTF_8));

        assertThat(liveFeedLoadResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(liveFeedLoadResponse.getBody(), StandardCharsets.UTF_8))
            .contains("POST /api/park/live-feeds/{source}/load");

        MockHttpServletRequest liveFeedRefreshRequest = new MockHttpServletRequest("POST", "/api/park/live-feeds/refresh-stale");
        ResponseEntity<byte[]> liveFeedRefreshResponse = service.forward(liveFeedRefreshRequest, "{}".getBytes(StandardCharsets.UTF_8));

        assertThat(liveFeedRefreshResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(liveFeedRefreshResponse.getBody(), StandardCharsets.UTF_8))
            .contains("POST /api/park/live-feeds/refresh-stale");

        MockHttpServletRequest reviewLedgerRequest = new MockHttpServletRequest("GET", "/api/park/review-training-ledger");
        ResponseEntity<byte[]> reviewLedgerResponse = service.forward(reviewLedgerRequest, new byte[0]);

        assertThat(reviewLedgerResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(reviewLedgerResponse.getBody(), StandardCharsets.UTF_8))
            .contains("GET /api/park/review-training-ledger");

        MockHttpServletRequest productLoopRequest = new MockHttpServletRequest("GET", "/api/park/product-learning/loop");
        ResponseEntity<byte[]> productLoopResponse = service.forward(productLoopRequest, new byte[0]);

        assertThat(productLoopResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(productLoopResponse.getBody(), StandardCharsets.UTF_8))
            .contains("GET /api/park/product-learning/loop");

        MockHttpServletRequest productIssueRequest = new MockHttpServletRequest("POST", "/api/park/product-learning/issue-ticket");
        ResponseEntity<byte[]> productIssueResponse = service.forward(productIssueRequest, "{}".getBytes(StandardCharsets.UTF_8));

        assertThat(productIssueResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(productIssueResponse.getBody(), StandardCharsets.UTF_8))
            .contains("POST /api/park/product-learning/issue-ticket");

        MockHttpServletRequest productGapRequest = new MockHttpServletRequest("POST", "/api/park/product-learning/training-gap-ticket");
        ResponseEntity<byte[]> productGapResponse = service.forward(productGapRequest, "{}".getBytes(StandardCharsets.UTF_8));

        assertThat(productGapResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(productGapResponse.getBody(), StandardCharsets.UTF_8))
            .contains("POST /api/park/product-learning/training-gap-ticket");

        MockHttpServletRequest productPromoteRequest = new MockHttpServletRequest("POST", "/api/park/product-learning/promote-version");
        ResponseEntity<byte[]> productPromoteResponse = service.forward(productPromoteRequest, "{}".getBytes(StandardCharsets.UTF_8));

        assertThat(productPromoteResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(productPromoteResponse.getBody(), StandardCharsets.UTF_8))
            .contains("POST /api/park/product-learning/promote-version");

        MockHttpServletRequest productRollbackRequest = new MockHttpServletRequest("POST", "/api/park/product-learning/rollback-version");
        ResponseEntity<byte[]> productRollbackResponse = service.forward(productRollbackRequest, "{}".getBytes(StandardCharsets.UTF_8));

        assertThat(productRollbackResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(productRollbackResponse.getBody(), StandardCharsets.UTF_8))
            .contains("POST /api/park/product-learning/rollback-version");

        MockHttpServletRequest productReviewPlaceRequest = new MockHttpServletRequest("POST", "/api/park/product-learning/review-place-resolution");
        ResponseEntity<byte[]> productReviewPlaceResponse = service.forward(productReviewPlaceRequest, "{}".getBytes(StandardCharsets.UTF_8));

        assertThat(productReviewPlaceResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(productReviewPlaceResponse.getBody(), StandardCharsets.UTF_8))
            .contains("POST /api/park/product-learning/review-place-resolution");

        MockHttpServletRequest staffScenariosRequest = new MockHttpServletRequest("GET", "/api/park/staff-training/scenarios");
        ResponseEntity<byte[]> staffScenariosResponse = service.forward(staffScenariosRequest, new byte[0]);

        assertThat(staffScenariosResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(staffScenariosResponse.getBody(), StandardCharsets.UTF_8))
            .contains("GET /api/park/staff-training/scenarios");

        MockHttpServletRequest staffSessionRequest = new MockHttpServletRequest("POST", "/api/park/staff-training/sessions");
        ResponseEntity<byte[]> staffSessionResponse = service.forward(staffSessionRequest, "{}".getBytes(StandardCharsets.UTF_8));

        assertThat(staffSessionResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(staffSessionResponse.getBody(), StandardCharsets.UTF_8))
            .contains("POST /api/park/staff-training/sessions");

        MockHttpServletRequest staffFinishRequest = new MockHttpServletRequest("POST", "/api/park/staff-training/finish");
        ResponseEntity<byte[]> staffFinishResponse = service.forward(staffFinishRequest, "{}".getBytes(StandardCharsets.UTF_8));

        assertThat(staffFinishResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(staffFinishResponse.getBody(), StandardCharsets.UTF_8))
            .contains("POST /api/park/staff-training/finish");

        MockHttpServletRequest staffAnalyticsRequest = new MockHttpServletRequest("GET", "/api/park/staff-training/analytics");
        ResponseEntity<byte[]> staffAnalyticsResponse = service.forward(staffAnalyticsRequest, new byte[0]);

        assertThat(staffAnalyticsResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(staffAnalyticsResponse.getBody(), StandardCharsets.UTF_8))
            .contains("GET /api/park/staff-training/analytics");

        assertSpringOwnedRouteBlocked(service, "GET", "/api/park/venue-profile", new byte[0], "GET /api/park/venue-profile");
        assertSpringOwnedRouteBlocked(service, "POST", "/api/park/venue-profile/validate", "{}".getBytes(StandardCharsets.UTF_8), "POST /api/park/venue-profile/validate");
        assertSpringOwnedRouteBlocked(service, "POST", "/api/park/venue-profile/import/preview", "{}".getBytes(StandardCharsets.UTF_8), "POST /api/park/venue-profile/import/preview");
        assertSpringOwnedRouteBlocked(service, "POST", "/api/park/venue-profile/import", "{}".getBytes(StandardCharsets.UTF_8), "POST /api/park/venue-profile/import");
        assertSpringOwnedRouteBlocked(service, "GET", "/api/park/venue-profile/synthetic/export", new byte[0], "GET /api/park/venue-profile/synthetic/export");
        assertSpringOwnedRouteBlocked(service, "POST", "/api/park/venue-profile/synthetic/activate", "{}".getBytes(StandardCharsets.UTF_8), "POST /api/park/venue-profile/synthetic/activate");
        assertSpringOwnedRouteBlocked(service, "GET", "/api/park/accessibility/scope", new byte[0], "GET /api/park/accessibility/scope");
        assertSpringOwnedRouteBlocked(service, "POST", "/api/park/accessibility/journey", "{}".getBytes(StandardCharsets.UTF_8), "POST /api/park/accessibility/journey");
        assertSpringOwnedRouteBlocked(service, "GET", "/api/park/review-label-pipeline", new byte[0], "GET /api/park/review-label-pipeline");
        assertSpringOwnedRouteBlocked(service, "POST", "/api/park/review-label-pipeline/decision", "{}".getBytes(StandardCharsets.UTF_8), "POST /api/park/review-label-pipeline/decision");
        assertSpringOwnedRouteBlocked(service, "POST", "/api/park/review-label-pipeline/auto-label", "{}".getBytes(StandardCharsets.UTF_8), "POST /api/park/review-label-pipeline/auto-label");
        assertSpringOwnedRouteBlocked(service, "GET", "/api/park/review-label-pipeline/decisions", new byte[0], "GET /api/park/review-label-pipeline/decisions");

        MockHttpServletRequest studioDraftsRequest = new MockHttpServletRequest("GET", "/api/park/experience-studio/drafts");
        ResponseEntity<byte[]> studioDraftsResponse = service.forward(studioDraftsRequest, new byte[0]);

        assertThat(studioDraftsResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(studioDraftsResponse.getBody(), StandardCharsets.UTF_8))
            .contains("GET /api/park/experience-studio/drafts");

        MockHttpServletRequest studioSaveRequest = new MockHttpServletRequest("POST", "/api/park/experience-studio/drafts");
        ResponseEntity<byte[]> studioSaveResponse = service.forward(studioSaveRequest, "{}".getBytes(StandardCharsets.UTF_8));

        assertThat(studioSaveResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(studioSaveResponse.getBody(), StandardCharsets.UTF_8))
            .contains("POST /api/park/experience-studio/drafts");

        MockHttpServletRequest studioPlanRequest = new MockHttpServletRequest("POST", "/api/park/experience-studio/conversation-plan");
        ResponseEntity<byte[]> studioPlanResponse = service.forward(studioPlanRequest, "{}".getBytes(StandardCharsets.UTF_8));

        assertThat(studioPlanResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(studioPlanResponse.getBody(), StandardCharsets.UTF_8))
            .contains("POST /api/park/experience-studio/conversation-plan");

        MockHttpServletRequest studioGenerateRequest = new MockHttpServletRequest("POST", "/api/park/experience-studio/draft");
        ResponseEntity<byte[]> studioGenerateResponse = service.forward(studioGenerateRequest, "{}".getBytes(StandardCharsets.UTF_8));

        assertThat(studioGenerateResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(studioGenerateResponse.getBody(), StandardCharsets.UTF_8))
            .contains("POST /api/park/experience-studio/draft");

        MockHttpServletRequest studioRevisionRequest = new MockHttpServletRequest("POST", "/api/park/experience-studio/section-revision");
        ResponseEntity<byte[]> studioRevisionResponse = service.forward(studioRevisionRequest, "{}".getBytes(StandardCharsets.UTF_8));

        assertThat(studioRevisionResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(studioRevisionResponse.getBody(), StandardCharsets.UTF_8))
            .contains("POST /api/park/experience-studio/section-revision");

        MockHttpServletRequest studioDraftRequest = new MockHttpServletRequest("GET", "/api/park/experience-studio/drafts/exp_spring");
        ResponseEntity<byte[]> studioDraftResponse = service.forward(studioDraftRequest, new byte[0]);

        assertThat(studioDraftResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(studioDraftResponse.getBody(), StandardCharsets.UTF_8))
            .contains("GET /api/park/experience-studio/drafts/{draft_id}");

        MockHttpServletRequest studioStatusRequest = new MockHttpServletRequest("POST", "/api/park/experience-studio/drafts/exp_spring/status");
        ResponseEntity<byte[]> studioStatusResponse = service.forward(studioStatusRequest, "{}".getBytes(StandardCharsets.UTF_8));

        assertThat(studioStatusResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(studioStatusResponse.getBody(), StandardCharsets.UTF_8))
            .contains("POST /api/park/experience-studio/drafts/{draft_id}/status");

        MockHttpServletRequest studioHandoffRequest = new MockHttpServletRequest("POST", "/api/park/experience-studio/drafts/exp_spring/handoff");
        ResponseEntity<byte[]> studioHandoffResponse = service.forward(studioHandoffRequest, "{}".getBytes(StandardCharsets.UTF_8));

        assertThat(studioHandoffResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(studioHandoffResponse.getBody(), StandardCharsets.UTF_8))
            .contains("POST /api/park/experience-studio/drafts/{draft_id}/handoff");

        MockHttpServletRequest studioMemoryRequest = new MockHttpServletRequest("GET", "/api/park/experience-studio/memory");
        ResponseEntity<byte[]> studioMemoryResponse = service.forward(studioMemoryRequest, new byte[0]);

        assertThat(studioMemoryResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(studioMemoryResponse.getBody(), StandardCharsets.UTF_8))
            .contains("GET /api/park/experience-studio/memory");

        MockHttpServletRequest studioRulesRequest = new MockHttpServletRequest("GET", "/api/park/experience-studio/learning-rules");
        ResponseEntity<byte[]> studioRulesResponse = service.forward(studioRulesRequest, new byte[0]);

        assertThat(studioRulesResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(studioRulesResponse.getBody(), StandardCharsets.UTF_8))
            .contains("GET /api/park/experience-studio/learning-rules");

        MockHttpServletRequest studioPromoteRequest = new MockHttpServletRequest("POST", "/api/park/experience-studio/drafts/exp_spring/promote-rule");
        ResponseEntity<byte[]> studioPromoteResponse = service.forward(studioPromoteRequest, "{}".getBytes(StandardCharsets.UTF_8));

        assertThat(studioPromoteResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(studioPromoteResponse.getBody(), StandardCharsets.UTF_8))
            .contains("POST /api/park/experience-studio/drafts/{draft_id}/promote-rule");

        MockHttpServletRequest studioRuleStatusRequest = new MockHttpServletRequest("POST", "/api/park/experience-studio/learning-rules/rule_spring/status");
        ResponseEntity<byte[]> studioRuleStatusResponse = service.forward(studioRuleStatusRequest, "{}".getBytes(StandardCharsets.UTF_8));

        assertThat(studioRuleStatusResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(studioRuleStatusResponse.getBody(), StandardCharsets.UTF_8))
            .contains("POST /api/park/experience-studio/learning-rules/{rule_id}/status");

        MockHttpServletRequest agentRunRequest = new MockHttpServletRequest("POST", "/api/park/agent-run");
        ResponseEntity<byte[]> agentRunResponse = service.forward(agentRunRequest, "{}".getBytes(StandardCharsets.UTF_8));

        assertThat(agentRunResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(agentRunResponse.getBody(), StandardCharsets.UTF_8))
            .contains("POST /api/park/agent-run");

        MockHttpServletRequest roleRunRequest = new MockHttpServletRequest("POST", "/api/park/agent-role-run");
        ResponseEntity<byte[]> roleRunResponse = service.forward(roleRunRequest, "{}".getBytes(StandardCharsets.UTF_8));

        assertThat(roleRunResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(roleRunResponse.getBody(), StandardCharsets.UTF_8))
            .contains("POST /api/park/agent-role-run");

        MockHttpServletRequest liveFeedRunRequest = new MockHttpServletRequest("POST", "/api/park/live-feed-agent-run");
        ResponseEntity<byte[]> liveFeedRunResponse = service.forward(liveFeedRunRequest, "{}".getBytes(StandardCharsets.UTF_8));

        assertThat(liveFeedRunResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(liveFeedRunResponse.getBody(), StandardCharsets.UTF_8))
            .contains("POST /api/park/live-feed-agent-run");

        MockHttpServletRequest actionRequest = new MockHttpServletRequest("POST", "/api/park/action");
        ResponseEntity<byte[]> actionResponse = service.forward(actionRequest, "{}".getBytes(StandardCharsets.UTF_8));

        assertThat(actionResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(actionResponse.getBody(), StandardCharsets.UTF_8))
            .contains("POST /api/park/action");

        MockHttpServletRequest signalIntakeRequest = new MockHttpServletRequest("POST", "/api/park/signals/intake");
        ResponseEntity<byte[]> signalIntakeResponse = service.forward(signalIntakeRequest, "{}".getBytes(StandardCharsets.UTF_8));

        assertThat(signalIntakeResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(signalIntakeResponse.getBody(), StandardCharsets.UTF_8))
            .contains("POST /api/park/signals/intake");

        MockHttpServletRequest copilotChatRequest = new MockHttpServletRequest("POST", "/api/park/copilot-chat");
        ResponseEntity<byte[]> copilotChatResponse = service.forward(copilotChatRequest, "{}".getBytes(StandardCharsets.UTF_8));

        assertThat(copilotChatResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(copilotChatResponse.getBody(), StandardCharsets.UTF_8))
            .contains("POST /api/park/copilot-chat");

        MockHttpServletRequest refineRequest = new MockHttpServletRequest("POST", "/api/park/agent-role-refine");
        ResponseEntity<byte[]> refineResponse = service.forward(refineRequest, "{}".getBytes(StandardCharsets.UTF_8));

        assertThat(refineResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(refineResponse.getBody(), StandardCharsets.UTF_8))
            .contains("POST /api/park/agent-role-refine");

        MockHttpServletRequest runtimeStatusRequest = new MockHttpServletRequest("GET", "/api/park/full-runtime-status");
        ResponseEntity<byte[]> runtimeStatusResponse = service.forward(runtimeStatusRequest, new byte[0]);

        assertThat(runtimeStatusResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(runtimeStatusResponse.getBody(), StandardCharsets.UTF_8))
            .contains("GET /api/park/full-runtime-status");

        MockHttpServletRequest runtimeWarmupRequest = new MockHttpServletRequest("POST", "/api/park/full-runtime-warmup");
        ResponseEntity<byte[]> runtimeWarmupResponse = service.forward(runtimeWarmupRequest, "{}".getBytes(StandardCharsets.UTF_8));

        assertThat(runtimeWarmupResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(runtimeWarmupResponse.getBody(), StandardCharsets.UTF_8))
            .contains("POST /api/park/full-runtime-warmup");

        MockHttpServletRequest warmupStatusRequest = new MockHttpServletRequest("GET", "/api/park/warmup-status");
        ResponseEntity<byte[]> warmupStatusResponse = service.forward(warmupStatusRequest, new byte[0]);

        assertThat(warmupStatusResponse.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(warmupStatusResponse.getBody(), StandardCharsets.UTF_8))
            .contains("GET /api/park/warmup-status");
    }

    private void assertSpringOwnedRouteBlocked(PythonFallbackProxyService service, String method, String path, byte[] body, String expectedRoute) {
        MockHttpServletRequest request = new MockHttpServletRequest(method, path);
        ResponseEntity<byte[]> response = service.forward(request, body);

        assertThat(response.getStatusCode().value()).isEqualTo(409);
        assertThat(new String(response.getBody(), StandardCharsets.UTF_8))
            .contains("spring_owned_route_fallback_gate")
            .contains(expectedRoute);
    }
}
