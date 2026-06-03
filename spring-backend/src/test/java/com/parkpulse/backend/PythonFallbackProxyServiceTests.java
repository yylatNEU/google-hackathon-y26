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
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/park/state");

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
}
