package com.parkpulse.backend;

import static org.hamcrest.Matchers.equalTo;
import static org.hamcrest.Matchers.notNullValue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

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
import org.springframework.test.web.servlet.MockMvc;

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

	private String signedRoleToken(String role) throws Exception {
		long now = Instant.now().getEpochSecond();
		String payload = String.format(
			"{\"aud\":\"parkpulse-role-access\",\"exp\":%d,\"iat\":%d,\"iss\":\"parkpulse-local-dev\",\"role\":\"%s\",\"sub\":\"spring-test\"}",
			now + 3600,
			now,
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
