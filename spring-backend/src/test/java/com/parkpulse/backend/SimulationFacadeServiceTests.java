package com.parkpulse.backend;

import static org.assertj.core.api.Assertions.assertThat;

import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.mock.web.MockHttpServletRequest;
import tools.jackson.databind.ObjectMapper;

class SimulationFacadeServiceTests {
    private HttpServer server;

    @AfterEach
    void stopServer() {
        if (server != null) {
            server.stop(0);
        }
    }

    @Test
    void delegatesSimulationTickThroughSpringAuthorityAndStoresSqliteReceipt() throws Exception {
        AtomicReference<String> receivedBody = new AtomicReference<>("");
        AtomicReference<String> receivedRole = new AtomicReference<>("");
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/api/park/tick", exchange -> {
            receivedBody.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            receivedRole.set(exchange.getRequestHeaders().getFirst("x-parkpulse-spring-authorized-role"));
            String response = """
                {
                  "status":"advanced",
                  "mode":"live_park_day_tick",
                  "minutes":30,
                  "simTime":{"hour":11,"minute":15},
                  "state":{"simTime":{"hour":11,"minute":15},"guestFlow":{"activeScenario":{"key":"ride_down"}}}
                }
                """;
            byte[] bytes = response.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("content-type", "application/json");
            exchange.sendResponseHeaders(200, bytes.length);
            exchange.getResponseBody().write(bytes);
            exchange.close();
        });
        server.setExecutor(Executors.newSingleThreadExecutor());
        server.start();

        Path dbPath = Path.of("target/test-parkpulse-runtime/simulation-facade-service-test.db");
        Files.createDirectories(dbPath.getParent());
        Files.deleteIfExists(dbPath);
        DriverManagerDataSource dataSource = new DriverManagerDataSource("jdbc:sqlite:" + dbPath);
        SimulationFacadeService service = new SimulationFacadeService(
            dataSource,
            new MockEnvironment()
                .withProperty("parkpulse.python-backend-url", "http://127.0.0.1:" + server.getAddress().getPort())
                .withProperty("parkpulse.simulation-adapter-timeout-ms", "2000"),
            new ObjectMapper()
        );
        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/api/park/tick");
        request.addHeader("authorization", "Bearer local-test-token");

        Map<String, Object> response = service.tick(
            request,
            Map.of("minutes", 999, "controller", false),
            Map.of("role", "ops_team", "subject", "simulation-test")
        );
        Map<String, Object> facade = map(response.get("simulationFacade"));
        Map<String, Object> ledger = service.ledger(5);
        Map<String, Object> receipt = map(list(ledger.get("receipts")).get(0));

        assertThat(response)
            .containsEntry("status", "advanced")
            .containsEntry("mode", "live_park_day_tick")
            .containsEntry("springRuntime", "java_spring")
            .containsEntry("simulationAuthority", "spring_control_plane_python_compute_adapter");
        assertThat(facade)
            .containsEntry("mode", "simulation_facade_spring")
            .containsEntry("operation", "simulation_tick")
            .containsEntry("route", "POST /api/park/tick")
            .containsEntry("mutates_state", true);
        assertThat(receivedRole.get()).isEqualTo("ops_team");
        assertThat(receivedBody.get()).contains("\"minutes\":30");
        assertThat(ledger).containsEntry("mode", "simulation_facade_ledger_spring");
        assertThat(map(ledger.get("summary"))).containsEntry("receipt_count", 1);
        assertThat(receipt)
            .containsEntry("operation", "simulation_tick")
            .containsEntry("route", "/api/park/tick")
            .containsEntry("actor_role", "ops_team")
            .containsEntry("mutates_state", true)
            .containsEntry("upstream_status", 200);
        assertThat(map(receipt.get("request"))).containsEntry("minutes", 30);
        assertThat(map(receipt.get("response_summary"))).containsEntry("status", "advanced");
    }

    @Test
    void replaysMutatingSimulationRequestWithSameIdempotencyKey() throws Exception {
        AtomicInteger adapterCalls = new AtomicInteger();
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/api/park/tick", exchange -> {
            int call = adapterCalls.incrementAndGet();
            String response = """
                {
                  "status":"advanced",
                  "mode":"live_park_day_tick",
                  "minutes":2,
                  "adapterCall":%d,
                  "state":{"simTime":{"hour":12,"minute":2},"guestFlow":{"activeScenario":{"key":"parade_pressure"}}}
                }
                """.formatted(call);
            byte[] bytes = response.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("content-type", "application/json");
            exchange.sendResponseHeaders(200, bytes.length);
            exchange.getResponseBody().write(bytes);
            exchange.close();
        });
        server.setExecutor(Executors.newSingleThreadExecutor());
        server.start();

        Path dbPath = Path.of("target/test-parkpulse-runtime/simulation-facade-idempotency-test.db");
        Files.createDirectories(dbPath.getParent());
        Files.deleteIfExists(dbPath);
        DriverManagerDataSource dataSource = new DriverManagerDataSource("jdbc:sqlite:" + dbPath);
        SimulationFacadeService service = new SimulationFacadeService(
            dataSource,
            new MockEnvironment()
                .withProperty("parkpulse.python-backend-url", "http://127.0.0.1:" + server.getAddress().getPort())
                .withProperty("parkpulse.simulation-adapter-timeout-ms", "2000"),
            new ObjectMapper()
        );

        MockHttpServletRequest firstRequest = new MockHttpServletRequest("POST", "/api/park/tick");
        firstRequest.addHeader("idempotency-key", "tick-key-1");
        Map<String, Object> identity = Map.of("role", "ops_team", "subject", "simulation-test");
        Map<String, Object> first = service.tick(firstRequest, Map.of("minutes", 2, "controller", false), identity);

        MockHttpServletRequest replayRequest = new MockHttpServletRequest("POST", "/api/park/tick");
        replayRequest.addHeader("idempotency-key", "tick-key-1");
        Map<String, Object> replayed = service.tick(replayRequest, Map.of("minutes", 2, "controller", false), identity);

        assertThat(adapterCalls.get()).isEqualTo(1);
        assertThat(first).containsEntry("adapterCall", 1);
        assertThat(replayed).containsEntry("adapterCall", 1);
        assertThat(map(replayed.get("simulationFacade")))
            .containsEntry("idempotency_key", "tick-key-1")
            .containsEntry("idempotency_replayed", true);
        assertThat(map(replayed.get("idempotency"))).containsEntry("status", "replayed");

        Map<String, Object> ledger = service.ledger(5);
        Map<String, Object> receipt = map(list(ledger.get("receipts")).get(0));
        assertThat(map(ledger.get("summary"))).containsEntry("receipt_count", 1);
        assertThat(receipt)
            .containsEntry("idempotency_key", "tick-key-1")
            .containsEntry("response_status", "advanced");
    }

    @Test
    void reportsSimulationAuthorityHealthFromAdapterAndLedger() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/api/park/state-lite", exchange -> {
            String response = """
                {
                  "status":"ready",
                  "mode":"park_state_lite",
                  "simTime":{"hour":13,"minute":0}
                }
                """;
            byte[] bytes = response.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("content-type", "application/json");
            exchange.sendResponseHeaders(200, bytes.length);
            exchange.getResponseBody().write(bytes);
            exchange.close();
        });
        server.createContext("/api/park/tick", exchange -> {
            String response = """
                {
                  "status":"advanced",
                  "mode":"live_park_day_tick",
                  "minutes":1,
                  "state":{"simTime":{"hour":13,"minute":1},"guestFlow":{"activeScenario":{"key":"food_spike"}}}
                }
                """;
            byte[] bytes = response.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("content-type", "application/json");
            exchange.sendResponseHeaders(200, bytes.length);
            exchange.getResponseBody().write(bytes);
            exchange.close();
        });
        server.setExecutor(Executors.newSingleThreadExecutor());
        server.start();

        Path dbPath = Path.of("target/test-parkpulse-runtime/simulation-facade-health-test.db");
        Files.createDirectories(dbPath.getParent());
        Files.deleteIfExists(dbPath);
        DriverManagerDataSource dataSource = new DriverManagerDataSource("jdbc:sqlite:" + dbPath);
        SimulationFacadeService service = new SimulationFacadeService(
            dataSource,
            new MockEnvironment()
                .withProperty("parkpulse.python-backend-url", "http://127.0.0.1:" + server.getAddress().getPort())
                .withProperty("parkpulse.simulation-adapter-timeout-ms", "2000"),
            new ObjectMapper()
        );

        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/api/park/tick");
        request.addHeader("idempotency-key", "health-tick");
        service.tick(request, Map.of("minutes", 1, "controller", false), Map.of("role", "ops_team", "subject", "health-test"));

        Map<String, Object> health = service.health();
        Map<String, Object> adapter = map(health.get("adapter"));
        Map<String, Object> ledger = map(health.get("ledger"));
        Map<String, Object> lastReceipt = map(ledger.get("last_finalized_mutation_receipt"));

        assertThat(health)
            .containsEntry("status", "ready")
            .containsEntry("mode", "simulation_authority_health_spring")
            .containsEntry("authority", "spring_control_plane_python_compute_adapter");
        assertThat(adapter)
            .containsEntry("reachable", true)
            .containsEntry("http_status", 200)
            .containsEntry("adapter_status", "ready")
            .containsEntry("adapter_mode", "park_state_lite");
        assertThat(ledger)
            .containsEntry("writable", true)
            .containsEntry("pending_receipt_count", 0)
            .containsEntry("source_of_truth", "local_sqlite_wal");
        assertThat(lastReceipt)
            .containsEntry("operation", "simulation_tick")
            .containsEntry("idempotency_key", "health-tick")
            .containsEntry("response_status", "advanced");
        assertThat(list(health.get("readiness_issues"))).isEmpty();
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> map(Object value) {
        return (Map<String, Object>) value;
    }

    @SuppressWarnings("unchecked")
    private java.util.List<Object> list(Object value) {
        return (java.util.List<Object>) value;
    }
}
