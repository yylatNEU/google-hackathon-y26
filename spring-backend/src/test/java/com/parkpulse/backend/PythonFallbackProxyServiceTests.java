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
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/park/product-learning/loop");

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
    }
}
