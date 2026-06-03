package com.parkpulse.backend;

import static org.hamcrest.Matchers.equalTo;
import static org.hamcrest.Matchers.notNullValue;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Base64;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.ObjectMapper;

@SpringBootTest(
	properties = {
		"PARKPULSE_RUNTIME_DIR=target/test-parkpulse-runtime",
		"PARKPULSE_PLATFORM_DB=target/test-parkpulse-runtime/park_data.db",
		"PARKPULSE_LEGACY_PLATFORM_DB=target/test-parkpulse-runtime/legacy_park_data.db",
		"PARKPULSE_ROLE_AUTH_SECRET=parkpulse-local-dev-secret-change-before-production"
	}
)
@AutoConfigureMockMvc
class ParkPulseSpringBackendApplicationTests {
	@Autowired
	private MockMvc mockMvc;

	@Autowired
	private ObjectMapper objectMapper;

	@Test
	void contextLoads() {
	}

	@Test
	void readyzReportsSpringMigrationSlice() throws Exception {
		mockMvc.perform(get("/readyz"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.entrypoint", equalTo("java-spring-migration")))
			.andExpect(jsonPath("$.dependency_status.platform_store.source_of_truth", equalTo("local_sqlite_wal")));
	}

	@Test
	void platformStoreRequiresAdminRoleToken() throws Exception {
		mockMvc.perform(get("/api/park/platform-store"))
			.andExpect(status().isUnauthorized());

		mockMvc.perform(get("/api/park/platform-store").header("authorization", "Bearer " + signedRoleToken("ops_team")))
			.andExpect(status().isForbidden());

		mockMvc.perform(get("/api/park/platform-store").header("authorization", "Bearer " + signedRoleToken("ml_ops_admin")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("ok")))
			.andExpect(jsonPath("$.registered_stores", notNullValue()));
	}

	@Test
	void migrateRouteAppliesNonDestructiveRegistrySync() throws Exception {
		mockMvc.perform(
				post("/api/park/platform-store/migrate")
					.header("authorization", "Bearer " + signedRoleToken("ml_ops_admin"))
					.contentType(MediaType.APPLICATION_JSON)
					.content("{\"actor\":\"spring-test\"}")
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.migration.status", equalTo("applied")))
			.andExpect(jsonPath("$.migration.non_destructive", equalTo(true)))
				.andExpect(jsonPath("$.source_of_truth", equalTo("local_sqlite_wal")));
	}

	@Test
	void devSessionIssuerMintsTokenAcceptedBySpringAdminRoutes() throws Exception {
		MvcResult issued = mockMvc.perform(
				post("/api/park/auth/dev-session")
					.contentType(MediaType.APPLICATION_JSON)
					.content("{\"role\":\"ml_ops_admin\",\"subject\":\"spring-issued-admin\"}")
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("issued")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andReturn();

		String token = objectMapper.readTree(issued.getResponse().getContentAsByteArray()).get("token").asText();
		mockMvc.perform(get("/api/park/backend-gateway/status").header("authorization", "Bearer " + token))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.mode", equalTo("spring_gateway_for_unmigrated_routes")));
	}

	@Test
	void authAndRoleContractRoutesRunNativelyInSpring() throws Exception {
		mockMvc.perform(get("/api/park/auth/status").header("authorization", "Bearer " + signedRoleToken("customer")))
			.andExpect(status().isForbidden());

		mockMvc.perform(get("/api/park/auth/status").header("authorization", "Bearer " + signedRoleToken("ops_team")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.mode", equalTo("identity_readiness")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(get("/api/park/role-access-contracts?role=customer").header("authorization", "Bearer " + signedRoleToken("customer")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.mode", equalTo("role_access_contracts")))
			.andExpect(jsonPath("$.role_count", equalTo(1)))
			.andExpect(jsonPath("$.roles[0].id", equalTo("customer")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));
	}

	@Test
	void reliabilityDiagnosticsAndAuthorizationAuditRunNativelyInSpring() throws Exception {
		mockMvc.perform(get("/api/park/reliability").header("authorization", "Bearer " + signedRoleToken("customer")))
			.andExpect(status().isForbidden());

		mockMvc.perform(get("/api/park/reliability").header("authorization", "Bearer " + signedRoleToken("ops_team")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.mode", equalTo("spring_reliability_diagnostics")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.authorization_audit.mode", equalTo("spring_authorization_audit")));

		mockMvc.perform(get("/api/park/latency-diagnostics").header("authorization", "Bearer " + signedRoleToken("ops_team")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.mode", equalTo("spring_lightweight_latency_diagnostics")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(get("/api/park/authorization-audit").header("authorization", "Bearer " + signedRoleToken("ml_ops_admin")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.mode", equalTo("spring_authorization_audit")))
			.andExpect(jsonPath("$.recent", notNullValue()));
	}

	@Test
	void deliveryOutboxReceiptsRunNativelyInSpringWithRoleGates() throws Exception {
		Path outbox = Path.of("target/test-parkpulse-runtime/delivery_outbox.jsonl");
		Files.createDirectories(outbox.getParent());
		Files.writeString(
			outbox,
			"{\"id\":\"dispatch-1\",\"createdAt\":\"2026-06-03T00:00:00Z\",\"channel\":\"worker_device\",\"targetSystem\":\"staff-dispatch-app\",\"status\":\"pending_operator_approval\",\"response\":{\"state\":\"pending\"}}\n",
			StandardCharsets.UTF_8
		);

		mockMvc.perform(get("/api/park/delivery/contract"))
			.andExpect(status().isUnauthorized());

		mockMvc.perform(get("/api/park/delivery/contract").header("authorization", "Bearer " + signedRoleToken("ops_team")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(get("/api/park/delivery/outbox?limit=5").header("authorization", "Bearer " + signedRoleToken("ops_team")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.count", equalTo(1)))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(
				post("/api/park/delivery/acknowledge")
					.header("authorization", "Bearer " + signedRoleToken("onsite_worker"))
					.contentType(MediaType.APPLICATION_JSON)
					.content("{\"dispatch_id\":\"dispatch-1\",\"actor\":\"lead\",\"choice\":\"accepted\",\"channel\":\"worker_device\"}")
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("acknowledged")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(
				post("/api/park/delivery/approval-decision")
					.header("authorization", "Bearer " + signedRoleToken("ml_ops_admin"))
					.contentType(MediaType.APPLICATION_JSON)
					.content("{\"dispatch_id\":\"dispatch-1\",\"decision\":\"approved\"}")
			)
			.andExpect(status().isForbidden());

		mockMvc.perform(
				post("/api/park/delivery/approval-decision")
					.header("authorization", "Bearer " + signedRoleToken("ops_team"))
					.contentType(MediaType.APPLICATION_JSON)
					.content("{\"dispatch_id\":\"dispatch-1\",\"actor\":\"ops-lead\",\"decision\":\"approved\",\"reason\":\"ok\"}")
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("approved_for_execution")))
			.andExpect(jsonPath("$.approval.decision", equalTo("approved")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));
	}

	@Test
	void rejectsRoleTokensWithWrongAudience() throws Exception {
		mockMvc.perform(get("/api/park/platform-store").header("authorization", "Bearer " + signedRoleToken("ml_ops_admin", "wrong-audience", "parkpulse-local-dev", 0)))
			.andExpect(status().isUnauthorized());
	}

	@Test
	void productionGateDisablesLocalDevIssuerAndDefaultSecret() throws Exception {
		RoleAuthService service = new RoleAuthService(
			new MockEnvironment()
				.withProperty("PARKPULSE_ENV", "production")
				.withProperty("PARKPULSE_ENABLE_DEV_ROLE_ISSUER", "true")
				.withProperty("PARKPULSE_ROLE_AUTH_SECRET", "parkpulse-local-dev-secret-change-before-production"),
			objectMapper
		);

		ResponseStatusException devIssuerError = assertThrows(
			ResponseStatusException.class,
			() -> service.issueDevSession("ml_ops_admin", "prod-admin")
		);
		org.assertj.core.api.Assertions.assertThat(devIssuerError.getStatusCode().value()).isEqualTo(403);

		MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/park/platform-store");
		request.addHeader("authorization", "Bearer " + signedRoleToken("ml_ops_admin"));
		ResponseStatusException authError = assertThrows(
			ResponseStatusException.class,
			() -> service.requireCapability(request, "read_platform_status")
		);
		org.assertj.core.api.Assertions.assertThat(authError.getStatusCode().value()).isEqualTo(401);
	}

	private String signedRoleToken(String role) throws Exception {
		return signedRoleToken(role, "parkpulse-role-access", "parkpulse-local-dev", 0);
	}

	private String signedRoleToken(String role, String audience, String issuer, long issuedAtOffsetSeconds) throws Exception {
		long now = Instant.now().getEpochSecond();
		String payload = String.format(
			"{\"aud\":\"%s\",\"exp\":%d,\"iat\":%d,\"iss\":\"%s\",\"role\":\"%s\",\"sub\":\"spring-test\"}",
			audience,
			now + 3600,
			now + issuedAtOffsetSeconds,
			issuer,
			role
		);
		String payloadPart = base64Url(payload.getBytes(StandardCharsets.UTF_8));
		Mac mac = Mac.getInstance("HmacSHA256");
		mac.init(new SecretKeySpec("parkpulse-local-dev-secret-change-before-production".getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
		return "pprole." + payloadPart + "." + base64Url(mac.doFinal(payloadPart.getBytes(StandardCharsets.US_ASCII)));
	}

	private String base64Url(byte[] value) {
		return Base64.getUrlEncoder().withoutPadding().encodeToString(value);
	}

}
