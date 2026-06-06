package com.parkpulse.backend;

import static org.hamcrest.Matchers.equalTo;
import static org.hamcrest.Matchers.endsWith;
import static org.hamcrest.Matchers.containsString;
import static org.hamcrest.Matchers.notNullValue;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.bouncycastle.crypto.params.Ed25519PrivateKeyParameters;
import org.bouncycastle.crypto.signers.Ed25519Signer;
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
import tools.jackson.core.json.JsonWriteFeature;
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
			.andExpect(jsonPath("$.registered_stores", notNullValue()))
			.andExpect(content().string(containsString("\"store_key\":\"monitor_evidence_snapshot\"")))
			.andExpect(content().string(containsString("\"data_model\":\"derived_snapshot\"")))
			.andExpect(content().string(containsString("\"source_of_truth\":false")));
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
	void stateLiteRunsNativelyInSpringForHotUiPolling() throws Exception {
		mockMvc.perform(get("/api/park/state-lite"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.guestFlow.rides[0].waitMins", notNullValue()))
			.andExpect(jsonPath("$.operationsAudit.mode", equalTo("spring_state_lite")));

		mockMvc.perform(get("/api/park/state"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.operatingClock.source", equalTo("java_spring_hot_path")))
			.andExpect(jsonPath("$.operationsAudit.mode", equalTo("spring_state")));

		mockMvc.perform(get("/api/park/live-summary"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.mode", equalTo("compact_live_operating_summary_spring")))
			.andExpect(jsonPath("$.operatingSummary.highestQueue.waitMins", notNullValue()));
	}

	@Test
	void monitorWorkspaceRoutesRunNativelyInSpring() throws Exception {
		mockMvc.perform(get("/api/park/cases"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.rows[0].id", equalTo("spring_queue_pressure")));

		mockMvc.perform(get("/api/park/cases/spring_queue_pressure/brief"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.mode", equalTo("case_operating_brief_spring")));

		mockMvc.perform(get("/api/park/monitor-evidence?case_id=spring_queue_pressure"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.cases[0].trace_records[0].relation_type", equalTo("explicit_case_id")));

		mockMvc.perform(get("/api/park/policy-doctrine"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.policy_refs[0].policy_book_id", equalTo("PARKPULSE-SPRING-OPS")));

		mockMvc.perform(get("/api/park/policy-doctrine/PARK-OPS-001"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.matches[0].policy_ref", equalTo("PARK-OPS-001")));

		mockMvc.perform(get("/api/park/agent-monitoring"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.summary.policy_book_count", equalTo(1)));
	}

	@Test
	void liveFeedRoutesRunNativelyInSpringWithRoleGates() throws Exception {
		Path runtime = Path.of("target/test-parkpulse-runtime");
		Files.deleteIfExists(runtime.resolve("live_feed_events.jsonl"));
		Files.deleteIfExists(runtime.resolve("review_ledger.jsonl"));

		mockMvc.perform(get("/api/park/live-feed-health"))
			.andExpect(status().isUnauthorized());

		mockMvc.perform(get("/api/park/live-feed-health").header("authorization", "Bearer " + signedRoleToken("customer")))
			.andExpect(status().isForbidden());

		mockMvc.perform(get("/api/park/live-feed-health?limit=3").header("authorization", "Bearer " + signedRoleToken("ops_team")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.mode", equalTo("live_feed_health_and_review_contract_spring")))
			.andExpect(jsonPath("$.summary.required_feed_count", equalTo(6)))
			.andExpect(jsonPath("$.feeds[0].source", equalTo("weather")));

		mockMvc.perform(get("/api/park/live-feeds/weather").header("authorization", "Bearer " + signedRoleToken("ops_team")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.config.source", equalTo("weather")));

		mockMvc.perform(
				post("/api/park/live-feeds/weather/load")
					.header("authorization", "Bearer " + signedRoleToken("ops_team"))
					.contentType(MediaType.APPLICATION_JSON)
					.content("{}")
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.mode", equalTo("live_weather_feed_load_spring")))
			.andExpect(jsonPath("$.event_count", equalTo(3)))
			.andExpect(jsonPath("$.durability.stored", equalTo(true)))
			.andExpect(jsonPath("$.durability.ledger.mode", equalTo("spring_live_feed_jsonl_ledger")));

		mockMvc.perform(
				post("/api/park/live-feeds/refresh-stale")
					.header("authorization", "Bearer " + signedRoleToken("ops_team"))
					.contentType(MediaType.APPLICATION_JSON)
					.content("{\"sources\":[\"weather\"]}")
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.mode", equalTo("live_feed_refresh_supervisor_spring")))
			.andExpect(jsonPath("$.after_feeds[0].status", equalTo("ready")))
			.andExpect(jsonPath("$.durability.stored", equalTo(true)));

		mockMvc.perform(get("/api/park/review-training-ledger?limit=1").header("authorization", "Bearer " + signedRoleToken("ops_team")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.mode", equalTo("review_training_ledger_spring")))
			.andExpect(jsonPath("$.rows[0].review_session_id", equalTo("review-spring-queue")));

		mockMvc.perform(
				post("/api/park/review-training-ledger")
					.header("authorization", "Bearer " + signedRoleToken("ops_team"))
					.contentType(MediaType.APPLICATION_JSON)
					.content("{\"review_session_id\":\"review-spring-queue\",\"decision\":\"approve\"}")
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("recorded")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.stored", equalTo(true)))
			.andExpect(jsonPath("$.ledger.mode", equalTo("spring_review_training_jsonl_ledger")));

		mockMvc.perform(
				post("/api/park/live-feed-events")
					.header("authorization", "Bearer " + signedRoleToken("ops_team"))
					.contentType(MediaType.APPLICATION_JSON)
					.content("{\"events\":[{\"source\":\"weather\"},{\"source\":\"ride-ops\"}]}")
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.mode", equalTo("normalized_live_feed_ingest_spring")))
			.andExpect(jsonPath("$.event_count", equalTo(2)))
			.andExpect(jsonPath("$.stored", equalTo(true)))
			.andExpect(jsonPath("$.ledger.mode", equalTo("spring_live_feed_jsonl_ledger")));

		org.assertj.core.api.Assertions.assertThat(Files.readString(runtime.resolve("live_feed_events.jsonl")))
			.contains("parkpulse.live_feed.signal")
			.contains("ride-ops");
		org.assertj.core.api.Assertions.assertThat(Files.readString(runtime.resolve("review_ledger.jsonl")))
			.contains("review-spring-queue")
			.contains("java_spring");
	}

	@Test
	void productLearningRoutesRunNativelyInSpringWithDurableLedgerAndRoleGates() throws Exception {
		Path runtime = Path.of("target/test-parkpulse-runtime");
		Files.deleteIfExists(runtime.resolve("product_learning_loop.jsonl"));

		mockMvc.perform(get("/api/park/product-learning/loop"))
			.andExpect(status().isUnauthorized());

		mockMvc.perform(get("/api/park/product-learning/loop").header("authorization", "Bearer " + signedRoleToken("customer")))
			.andExpect(status().isForbidden());

		mockMvc.perform(
				post("/api/park/product-learning/issue-ticket")
					.header("authorization", "Bearer " + signedRoleToken("customer"))
					.contentType(MediaType.APPLICATION_JSON)
					.content("{\"source\":\"guest\",\"issueType\":\"angry_parent\",\"summary\":\"Guest needs recovery after long queue\",\"severity\":\"high\",\"location\":\"Covered Plaza\"}")
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("created")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.ticket.source", equalTo("guest")))
			.andExpect(jsonPath("$.ticket.requires_human_ack", equalTo(true)))
			.andExpect(jsonPath("$.ledger.mode", equalTo("spring_product_learning_jsonl_ledger")));

		mockMvc.perform(
				post("/api/park/product-learning/training-gap-ticket")
					.header("authorization", "Bearer " + signedRoleToken("onsite_worker"))
					.contentType(MediaType.APPLICATION_JSON)
					.content("{\"scenarioId\":\"angry_parent\",\"gapType\":\"policy_correctness\"}")
			)
			.andExpect(status().isForbidden());

		mockMvc.perform(
				post("/api/park/product-learning/training-gap-ticket")
					.header("authorization", "Bearer " + signedRoleToken("ops_team"))
					.contentType(MediaType.APPLICATION_JSON)
					.content("{\"scenarioId\":\"angry_parent\",\"gapType\":\"policy_correctness\",\"severity\":\"critical_training_gap\",\"evidence\":{\"summary\":\"Missed escalation threshold\"}}")
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("created")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.ticket.live_ops_authority", equalTo(false)))
			.andExpect(jsonPath("$.ledger.mode", equalTo("spring_product_learning_jsonl_ledger")));

		mockMvc.perform(get("/api/park/product-learning/loop?limit=20").header("authorization", "Bearer " + signedRoleToken("ops_team")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.mode", equalTo("product_learning_loop_spring")))
			.andExpect(jsonPath("$.park_issue_ticket_count", equalTo(2)))
			.andExpect(jsonPath("$.training_gap_ticket_count", equalTo(1)))
			.andExpect(jsonPath("$.product_learning_signals[0].id", notNullValue()))
			.andExpect(jsonPath("$.loop_contract.human_on_exception", equalTo(true)));

		org.assertj.core.api.Assertions.assertThat(Files.readString(runtime.resolve("product_learning_loop.jsonl")))
			.contains("park_issue_ticket_created")
			.contains("training_gap_ticket_created")
			.contains("java_spring");
	}

	@Test
	void staffTrainingRoutesRunNativelyInSpringWithSessionAndReceiptFlow() throws Exception {
		Path runtime = Path.of("target/test-parkpulse-runtime");
		Files.deleteIfExists(runtime.resolve("staff_training_ledger.jsonl"));

		mockMvc.perform(get("/api/park/staff-training/scenarios"))
			.andExpect(status().isUnauthorized());

		mockMvc.perform(get("/api/park/staff-training/scenarios").header("authorization", "Bearer " + signedRoleToken("customer")))
			.andExpect(status().isForbidden());

		mockMvc.perform(get("/api/park/staff-training/scenarios").header("authorization", "Bearer " + signedRoleToken("onsite_worker")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.scenarios[0].id", equalTo("angry_parent")));

		mockMvc.perform(get("/api/park/staff-training/assignments").header("authorization", "Bearer " + signedRoleToken("onsite_worker")))
			.andExpect(status().isForbidden());

		MvcResult assignmentResult = mockMvc.perform(
				post("/api/park/staff-training/assignments")
					.header("authorization", "Bearer " + signedRoleToken("ops_team"))
					.contentType(MediaType.APPLICATION_JSON)
					.content("{\"traineeName\":\"Spring Trainee\",\"staffRole\":\"guest_care\",\"scenarioIds\":[\"angry_parent\"]}")
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.assignment.id", notNullValue()))
			.andReturn();

		String assignmentId = objectMapper.readTree(assignmentResult.getResponse().getContentAsByteArray()).get("assignment").get("id").asText();
		MvcResult sessionResult = mockMvc.perform(
				post("/api/park/staff-training/sessions")
					.header("authorization", "Bearer " + signedRoleToken("onsite_worker"))
					.contentType(MediaType.APPLICATION_JSON)
					.content("{\"scenarioId\":\"angry_parent\",\"traineeName\":\"Spring Trainee\",\"assignmentId\":\"" + assignmentId + "\"}")
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("active")))
			.andExpect(jsonPath("$.scenario.id", equalTo("angry_parent")))
			.andReturn();

		String sessionId = objectMapper.readTree(sessionResult.getResponse().getContentAsByteArray()).get("id").asText();
		mockMvc.perform(
				post("/api/park/staff-training/turn")
					.header("authorization", "Bearer " + signedRoleToken("onsite_worker"))
					.contentType(MediaType.APPLICATION_JSON)
					.content("{\"sessionId\":\"" + sessionId + "\",\"employeeMessage\":\"I am sorry this happened. I can help and bring a manager into the policy step.\",\"useShadowEval\":true}")
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.turn_score.overall", equalTo(84)))
			.andExpect(jsonPath("$.shadow_evaluator.status", equalTo("complete")));

		mockMvc.perform(
				post("/api/park/staff-training/finish")
					.header("authorization", "Bearer " + signedRoleToken("onsite_worker"))
					.contentType(MediaType.APPLICATION_JSON)
					.content("{\"sessionId\":\"" + sessionId + "\"}")
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("finished")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.receipt.manager_review_required", equalTo(true)));

		mockMvc.perform(get("/api/park/staff-training/receipts?limit=10").header("authorization", "Bearer " + signedRoleToken("ops_team")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.receipts[0].session_id", equalTo(sessionId)));

		mockMvc.perform(get("/api/park/staff-training/analytics?limit=10").header("authorization", "Bearer " + signedRoleToken("ops_team")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.session_count", equalTo(1)));

		mockMvc.perform(get("/api/park/staff-training/certification-packet?assignment_id=" + assignmentId).header("authorization", "Bearer " + signedRoleToken("ops_team")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.assignment.id", equalTo(assignmentId)));

		mockMvc.perform(
				post("/api/park/staff-training/receipt-review")
					.header("authorization", "Bearer " + signedRoleToken("ops_team"))
					.contentType(MediaType.APPLICATION_JSON)
					.content("{\"sessionId\":\"" + sessionId + "\",\"decision\":\"approve_shadowing\",\"reviewer\":\"Spring Manager\"}")
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("recorded")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(get("/api/park/staff-training/golden-eval").header("authorization", "Bearer " + signedRoleToken("ops_team")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.case_count", equalTo(2)));

		org.assertj.core.api.Assertions.assertThat(Files.readString(runtime.resolve("staff_training_ledger.jsonl")))
			.contains("staff_training_assignment_created")
			.contains("staff_training_receipt_created")
			.contains("staff_training_receipt_reviewed");
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
		Files.deleteIfExists(Path.of("target/test-parkpulse-runtime/canonical_events.jsonl"));
		Files.writeString(
			outbox,
			"{\"id\":\"dispatch-1\",\"createdAt\":\"2026-06-03T00:00:00Z\",\"channel\":\"worker_device\",\"targetSystem\":\"staff-dispatch-app\",\"status\":\"pending_operator_approval\",\"response\":{\"state\":\"pending\"}}\n",
			StandardCharsets.UTF_8
		);

		mockMvc.perform(get("/api/park/delivery/contract"))
			.andExpect(status().isUnauthorized());

		mockMvc.perform(get("/api/park/delivery/contract").header("authorization", "Bearer " + signedRoleToken("ops_team")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.ports[0].runtime", equalTo("java_spring")));

		mockMvc.perform(get("/api/park/delivery/outbox?limit=5").header("authorization", "Bearer " + signedRoleToken("ops_team")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.count", equalTo(1)))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(get("/api/park/delivery/gcp-adapters/status").header("authorization", "Bearer " + signedRoleToken("ops_team")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.pubsub.mode", equalTo("spring_queue_only")))
			.andExpect(jsonPath("$.firestore.mirror.ready", equalTo(true)))
			.andExpect(jsonPath("$.dataflow.contract.platform", equalTo("Google Cloud Dataflow")));

		mockMvc.perform(get("/api/park/delivery/partner-retries/status").header("authorization", "Bearer " + signedRoleToken("ops_team")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.mode", equalTo("spring_partner_receiver_retry_worker")))
			.andExpect(jsonPath("$.enabled", equalTo(false)));

		mockMvc.perform(get("/api/park/events/contract").header("authorization", "Bearer " + signedRoleToken("ops_team")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.schema_version", equalTo("parkpulse.event.v1")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(
				post("/api/park/delivery/guest-promotion")
					.header("authorization", "Bearer " + signedRoleToken("ml_ops_admin"))
					.contentType(MediaType.APPLICATION_JSON)
					.content("{\"payload\":{\"scenarioKey\":\"ride_down\",\"policyGateChecked\":true}}")
			)
			.andExpect(status().isForbidden());

		mockMvc.perform(
				post("/api/park/delivery/guest-promotion")
					.header("authorization", "Bearer " + signedRoleToken("ops_team"))
					.contentType(MediaType.APPLICATION_JSON)
					.content("{\"payload\":{\"scenarioKey\":\"ride_down\",\"expectedTakeRate\":0.31,\"estimatedMovedGuests\":100,\"policyGateChecked\":true}}")
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("delivered")))
			.andExpect(jsonPath("$.dispatch.channel", equalTo("guest_app")))
			.andExpect(jsonPath("$.dispatch.targetSystem", equalTo("guest-mobile-app")))
			.andExpect(jsonPath("$.dispatch.agentBoundary.allowed", equalTo(true)))
			.andExpect(jsonPath("$.dispatch.agentBoundary.policy_gate_checked", equalTo(true)))
			.andExpect(jsonPath("$.dispatch.gcpDelivery.pubsub.status", equalTo("skipped")))
			.andExpect(jsonPath("$.dispatch.gcpDelivery.firestore.status", equalTo("mirrored")))
			.andExpect(jsonPath("$.dispatch.gcpDelivery.dataflow.status", equalTo("mirrored")))
			.andExpect(jsonPath("$.dispatch.eventPipeline.status", equalTo("recorded")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(get("/api/park/events/ledger?event_type=parkpulse.delivery.dispatch").header("authorization", "Bearer " + signedRoleToken("ops_team")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.count", equalTo(1)))
			.andExpect(jsonPath("$.events[0].event_type", equalTo("parkpulse.delivery.dispatch")))
			.andExpect(jsonPath("$.events[0].schema_version", equalTo("parkpulse.event.v1")));

		mockMvc.perform(
				post("/api/park/events/receiver/worker-acknowledgement")
					.contentType(MediaType.APPLICATION_JSON)
					.content("{\"dispatchId\":\"dispatch-worker-1\",\"channel\":\"worker_device\",\"receiver\":\"staff-dispatch-app\",\"acknowledged\":true}")
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("recorded")))
			.andExpect(jsonPath("$.event.event_type", equalTo("parkpulse.receiver.worker_acknowledgement")));

		mockMvc.perform(
				post("/api/park/delivery/guest-promotion")
					.header("authorization", "Bearer " + signedRoleToken("ops_team"))
					.contentType(MediaType.APPLICATION_JSON)
					.content("{\"payload\":{\"scenarioKey\":\"ride_down\",\"expectedTakeRate\":0.31,\"estimatedMovedGuests\":100,\"policyGateChecked\":true}}")
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("delivered")))
			.andExpect(jsonPath("$.dispatch.deduplicated", equalTo(true)));

		mockMvc.perform(
				post("/api/park/delivery/partner-retries/run")
					.header("authorization", "Bearer " + signedRoleToken("ops_team"))
					.contentType(MediaType.APPLICATION_JSON)
					.content("{\"limit\":20,\"dry_run\":true}")
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("completed")))
			.andExpect(jsonPath("$.dry_run", equalTo(true)))
			.andExpect(jsonPath("$.attempts[0].status", equalTo("receiver_not_configured")));

		mockMvc.perform(
				post("/api/park/delivery/worker-notification")
					.header("authorization", "Bearer " + signedRoleToken("ops_team"))
					.contentType(MediaType.APPLICATION_JSON)
					.content("{\"payload\":{\"role\":\"crowd_control\",\"priority\":\"high\",\"policyGateStatus\":\"passed\"}}")
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("delivered")))
			.andExpect(jsonPath("$.dispatch.channel", equalTo("worker_device")))
			.andExpect(jsonPath("$.dispatch.response.acknowledgedCount", equalTo(4)));

		mockMvc.perform(
				post("/api/park/delivery/equipment-command")
					.header("authorization", "Bearer " + signedRoleToken("ops_team"))
					.contentType(MediaType.APPLICATION_JSON)
					.content("{\"payload\":{\"command\":\"adjust_hvac\",\"targetZone\":\"arcade\",\"requiresHumanApproval\":true}}")
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("pending_operator_approval")))
			.andExpect(jsonPath("$.dispatch.channel", equalTo("equipment_controller")))
			.andExpect(jsonPath("$.dispatch.response.state", equalTo("pending")))
			.andExpect(jsonPath("$.dispatch.gcpDelivery.workflow.status", equalTo("skipped")));

		mockMvc.perform(
				post("/api/park/delivery/equipment-command")
					.header("authorization", "Bearer " + signedRoleToken("ops_team"))
					.contentType(MediaType.APPLICATION_JSON)
					.content("{\"payload\":{\"command\":\"adjust_hvac\",\"targetZone\":\"arcade\"}}")
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("blocked_by_agent_boundary")))
			.andExpect(jsonPath("$.dispatch.response.state", equalTo("blocked")))
			.andExpect(jsonPath("$.dispatch.gcpDelivery.reason", equalTo("Agent Builder boundary blocked receiver dispatch.")));

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
			.andExpect(jsonPath("$.approvalDelivery.firestore.status", equalTo("mirrored")))
			.andExpect(jsonPath("$.approvalDelivery.dataflow.status", equalTo("mirrored")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));
	}

	@Test
	void deliveryGcpAdapterUsesLiveHttpBindingsOnlyWhenExplicitlyEnabled() throws Exception {
		HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
		AtomicInteger pubsubCalls = new AtomicInteger();
		AtomicInteger fcmCalls = new AtomicInteger();
		AtomicInteger firestoreCalls = new AtomicInteger();
		server.createContext("/", exchange -> {
			String path = exchange.getRequestURI().getPath();
			String authorization = exchange.getRequestHeaders().getFirst("authorization");
			String body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
			String response;
			if (!"Bearer test-token".equals(authorization)) {
				exchange.sendResponseHeaders(401, 0);
				exchange.close();
				return;
			}
			if (path.endsWith(":publish")) {
				pubsubCalls.incrementAndGet();
				org.assertj.core.api.Assertions.assertThat(body).contains("messages");
				response = "{\"messageIds\":[\"pubsub-1\"]}";
			} else if (path.endsWith("/messages:send")) {
				fcmCalls.incrementAndGet();
				org.assertj.core.api.Assertions.assertThat(body).contains("ParkPulse update");
				response = "{\"name\":\"projects/demo/messages/fcm-1\"}";
			} else if (path.contains("/documents/")) {
				firestoreCalls.incrementAndGet();
				org.assertj.core.api.Assertions.assertThat(exchange.getRequestMethod()).isEqualTo("PATCH");
				org.assertj.core.api.Assertions.assertThat(body).contains("payloadJson");
				response = "{\"name\":\"firestore/doc\"}";
			} else {
				exchange.sendResponseHeaders(404, 0);
				exchange.close();
				return;
			}
			byte[] bytes = response.getBytes(StandardCharsets.UTF_8);
			exchange.getResponseHeaders().add("content-type", "application/json");
			exchange.sendResponseHeaders(200, bytes.length);
			exchange.getResponseBody().write(bytes);
			exchange.close();
		});
		server.start();
		try {
			String baseUrl = "http://127.0.0.1:" + server.getAddress().getPort();
			DeliveryGcpAdapterService service = new DeliveryGcpAdapterService(
				new MockEnvironment()
					.withProperty("PARKPULSE_RUNTIME_DIR", "target/test-parkpulse-live-adapter")
					.withProperty("GOOGLE_CLOUD_PROJECT", "demo-project")
					.withProperty("PARKPULSE_PUBSUB_TOPIC", "parkpulse-ops")
					.withProperty("ENABLE_PARKPULSE_PUBSUB", "true")
					.withProperty("PARKPULSE_ENABLE_SPRING_LIVE_GCP_PUBLISH", "true")
					.withProperty("ENABLE_PARKPULSE_FCM", "true")
					.withProperty("ENABLE_PARKPULSE_FIRESTORE", "true")
					.withProperty("PARKPULSE_GCP_ACCESS_TOKEN", "test-token")
					.withProperty("PARKPULSE_PUBSUB_API_BASE_URL", baseUrl)
					.withProperty("PARKPULSE_FCM_API_BASE_URL", baseUrl)
					.withProperty("PARKPULSE_FIRESTORE_API_BASE_URL", baseUrl),
				objectMapper
			);

			Map<String, Object> dispatch = new LinkedHashMap<>();
			dispatch.put("id", "dispatch-live-1");
			dispatch.put("channel", "guest_app");
			dispatch.put("targetSystem", "guest-mobile-app");
			dispatch.put("status", "delivered");
			dispatch.put("payload", Map.of("message", "Move to north gate", "scenarioKey", "ride_down"));
			dispatch.put("agentBoundary", Map.of("allowed", true));

			Map<String, Object> result = service.enrichDeliveryDispatch(dispatch);

			org.assertj.core.api.Assertions.assertThat(((Map<?, ?>) result.get("pubsub")).get("status")).isEqualTo("published");
			org.assertj.core.api.Assertions.assertThat(((Map<?, ?>) result.get("fcm")).get("status")).isEqualTo("sent");
			org.assertj.core.api.Assertions.assertThat(((Map<?, ?>) result.get("firestore")).get("status")).isEqualTo("written");
			org.assertj.core.api.Assertions.assertThat(pubsubCalls.get()).isEqualTo(1);
			org.assertj.core.api.Assertions.assertThat(fcmCalls.get()).isEqualTo(1);
			org.assertj.core.api.Assertions.assertThat(firestoreCalls.get()).isEqualTo(1);
		} finally {
			server.stop(0);
		}
	}

	@Test
	void deliveryPartnerRetryWorkerReplaysEligibleDispatchesWithIdempotencyHeaders() throws Exception {
		Path runtime = Path.of("target/test-parkpulse-partner-retry");
		Files.createDirectories(runtime);
		Files.deleteIfExists(runtime.resolve("partner_retry_receipts.jsonl"));
		Files.writeString(
			runtime.resolve("delivery_outbox.jsonl"),
			"{\"id\":\"dispatch-retry-1\",\"createdAt\":\"2026-06-03T00:00:00Z\",\"channel\":\"guest_app\",\"targetSystem\":\"guest-mobile-app\",\"method\":\"POST\",\"endpoint\":\"/partner/guest-app/promotions\",\"status\":\"delivered\",\"idempotencyKey\":\"retry-key-1\",\"payload\":{\"message\":\"hello\"},\"response\":{\"state\":\"observed\"},\"agentBoundary\":{\"allowed\":true}}\n",
			StandardCharsets.UTF_8
		);
		HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
		AtomicInteger partnerCalls = new AtomicInteger();
		server.createContext("/partner/guest-app/promotions", exchange -> {
			partnerCalls.incrementAndGet();
			org.assertj.core.api.Assertions.assertThat(exchange.getRequestHeaders().getFirst("idempotency-key")).isEqualTo("retry-key-1");
			org.assertj.core.api.Assertions.assertThat(exchange.getRequestHeaders().getFirst("x-parkpulse-dispatch-id")).isEqualTo("dispatch-retry-1");
			String body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
			org.assertj.core.api.Assertions.assertThat(body).contains("dispatch-retry-1");
			byte[] bytes = "{\"accepted\":true}".getBytes(StandardCharsets.UTF_8);
			exchange.getResponseHeaders().add("content-type", "application/json");
			exchange.sendResponseHeaders(202, bytes.length);
			exchange.getResponseBody().write(bytes);
			exchange.close();
		});
		server.start();
		try {
			MockEnvironment baseEnvironment = new MockEnvironment().withProperty("PARKPULSE_RUNTIME_DIR", runtime.toString());
			EventPipelineService events = new EventPipelineService(baseEnvironment, objectMapper);
			DeliveryGcpAdapterService gcp = new DeliveryGcpAdapterService(baseEnvironment, objectMapper);
			DeliveryOutboxService outbox = new DeliveryOutboxService(baseEnvironment, objectMapper, gcp, events);
			DeliveryPartnerRetryService retry = new DeliveryPartnerRetryService(
				new MockEnvironment()
					.withProperty("PARKPULSE_RUNTIME_DIR", runtime.toString())
					.withProperty("PARKPULSE_ENABLE_PARTNER_RECEIVER_RETRY", "true")
					.withProperty("PARKPULSE_PARTNER_RECEIVER_BASE_URL", "http://127.0.0.1:" + server.getAddress().getPort()),
				objectMapper,
				outbox,
				events
			);

			Map<String, Object> result = retry.run(Map.of("limit", 5, "dry_run", false));

			org.assertj.core.api.Assertions.assertThat(result.get("status")).isEqualTo("completed");
			org.assertj.core.api.Assertions.assertThat(partnerCalls.get()).isEqualTo(1);
			List<?> attempts = (List<?>) result.get("attempts");
			org.assertj.core.api.Assertions.assertThat(((Map<?, ?>) attempts.get(0)).get("status")).isEqualTo("delivered_to_partner");
			org.assertj.core.api.Assertions.assertThat(Files.readString(runtime.resolve("partner_retry_receipts.jsonl"))).contains("delivered_to_partner");

			Map<String, Object> secondRun = retry.run(Map.of("limit", 5, "dry_run", false));
			List<?> secondAttempts = (List<?>) secondRun.get("attempts");
			org.assertj.core.api.Assertions.assertThat(partnerCalls.get()).isEqualTo(1);
			org.assertj.core.api.Assertions.assertThat(((Map<?, ?>) secondAttempts.get(0)).get("status")).isEqualTo("skipped");
			org.assertj.core.api.Assertions.assertThat(((Map<?, ?>) secondAttempts.get(0)).get("reason")).isEqualTo("Partner receiver already accepted this dispatch.");
		} finally {
			server.stop(0);
		}
	}

	@Test
	void eventPipelineExportsCanonicalRowsToBigQueryWhenExplicitlyEnabled() throws Exception {
		Path runtime = Path.of("target/test-parkpulse-bigquery-events");
		Files.createDirectories(runtime);
		Files.deleteIfExists(runtime.resolve("canonical_events.jsonl"));
		HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
		AtomicInteger bigQueryCalls = new AtomicInteger();
		server.createContext("/bigquery/v2/projects/demo-project/datasets/parkpulse/tables/events/insertAll", exchange -> {
			bigQueryCalls.incrementAndGet();
			org.assertj.core.api.Assertions.assertThat(exchange.getRequestHeaders().getFirst("authorization")).isEqualTo("Bearer test-token");
			String body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
			org.assertj.core.api.Assertions.assertThat(body)
				.contains("insertId")
				.contains("parkpulse.receiver.guest_response")
				.contains("payload_json");
			byte[] bytes = "{}".getBytes(StandardCharsets.UTF_8);
			exchange.getResponseHeaders().add("content-type", "application/json");
			exchange.sendResponseHeaders(200, bytes.length);
			exchange.getResponseBody().write(bytes);
			exchange.close();
		});
		server.start();
		try {
			EventPipelineService events = new EventPipelineService(
				new MockEnvironment()
					.withProperty("PARKPULSE_RUNTIME_DIR", runtime.toString())
					.withProperty("ENABLE_PARKPULSE_BIGQUERY_EVENT_EXPORT", "true")
					.withProperty("PARKPULSE_BIGQUERY_EVENT_TABLE", "demo-project.parkpulse.events")
					.withProperty("PARKPULSE_BIGQUERY_API_BASE_URL", "http://127.0.0.1:" + server.getAddress().getPort() + "/bigquery/v2")
					.withProperty("PARKPULSE_GCP_ACCESS_TOKEN", "test-token"),
				objectMapper
			);

			Map<String, Object> result = events.recordReceiverEvent(
				"parkpulse.receiver.guest_response",
				Map.of("dispatchId", "dispatch-bq-1", "channel", "guest_app", "accepted", true)
			);

			org.assertj.core.api.Assertions.assertThat(result.get("status")).isEqualTo("recorded");
			org.assertj.core.api.Assertions.assertThat(((Map<?, ?>) result.get("bigquery")).get("status")).isEqualTo("inserted");
			org.assertj.core.api.Assertions.assertThat(bigQueryCalls.get()).isEqualTo(1);
			org.assertj.core.api.Assertions.assertThat(Files.readString(runtime.resolve("canonical_events.jsonl"))).contains("parkpulse.receiver.guest_response");
		} finally {
			server.stop(0);
		}
	}

	@Test
	void agentTrustRegistryRunsNativelyInSpringWithAdminGate() throws Exception {
		mockMvc.perform(get("/api/park/agent-trust/status").header("authorization", "Bearer " + signedRoleToken("ops_team")))
			.andExpect(status().isForbidden());

		mockMvc.perform(get("/api/park/agent-trust/status").header("authorization", "Bearer " + signedRoleToken("ml_ops_admin")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.mode", equalTo("durable_agent_trust_registry")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(
				post("/api/park/agent-trust/partners")
					.header("authorization", "Bearer " + signedRoleToken("ml_ops_admin"))
					.contentType(MediaType.APPLICATION_JSON)
					.content("{\"partner_id\":\"spring_partner\",\"partner_name\":\"Spring Partner\",\"allowed_scopes\":[\"location\",\"route_plan\"],\"actor\":\"spring-admin\"}")
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("upserted")))
			.andExpect(jsonPath("$.partner.partner_id", equalTo("spring_partner")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(get("/api/park/agent-trust/partners").header("authorization", "Bearer " + signedRoleToken("ml_ops_admin")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.count", notNullValue()))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(
				post("/api/park/agent-trust/keys/rotate")
					.header("authorization", "Bearer " + signedRoleToken("ml_ops_admin"))
					.contentType(MediaType.APPLICATION_JSON)
					.content("{\"version\":\"spring-test-key\",\"actor\":\"spring-admin\"}")
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("rotated")))
			.andExpect(jsonPath("$.signing.version", equalTo("spring-test-key")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(get("/api/park/agent-trust/keys").header("authorization", "Bearer " + signedRoleToken("ml_ops_admin")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.active_key.version", equalTo("spring-test-key")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(get("/api/park/agent-trust/audit?limit=5").header("authorization", "Bearer " + signedRoleToken("ml_ops_admin")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.count", notNullValue()))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));
	}

	@Test
	void agentOnboardingIssuerAndRevocationUseSpringTrustAuthority() throws Exception {
		mockMvc.perform(get("/api/park/agent-onboarding/issuer"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.issuer", equalTo("parkpulse_agent_onboarding_authority")))
			.andExpect(jsonPath("$.revocation_runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.verification_runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		MvcResult issuer = mockMvc.perform(get("/api/park/agent-onboarding/issuer")).andReturn();
		String keyVersion = objectMapper.readTree(issuer.getResponse().getContentAsByteArray()).get("active_key").get("version").asText();
		String keyId = objectMapper.readTree(issuer.getResponse().getContentAsByteArray()).get("active_key").get("kid").asText();
		String certificationId = "cert-spring-verify-" + Instant.now().toEpochMilli();
		Map<String, Object> credential = signedCertificationCredential(keyId, keyVersion, certificationId, Instant.now().getEpochSecond() + 3600);
		mockMvc.perform(
				post("/api/park/agent-onboarding/verify-credential")
					.contentType(MediaType.APPLICATION_JSON)
					.content(objectMapper.writeValueAsString(Map.of("credential", credential)))
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("verified")))
			.andExpect(jsonPath("$.signature_status", equalTo("valid")))
			.andExpect(jsonPath("$.certification_id", equalTo(certificationId)))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		Map<String, Object> tamperedCredential = new LinkedHashMap<>(credential);
		tamperedCredential.put("approval", "pending_certification");
		mockMvc.perform(
				post("/api/park/agent-onboarding/verify-credential")
					.contentType(MediaType.APPLICATION_JSON)
					.content(objectMapper.writeValueAsString(Map.of("credential", tamperedCredential)))
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("rejected")))
			.andExpect(jsonPath("$.signature_status", equalTo("invalid")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		MvcResult delegation = mockMvc.perform(
				post("/api/park/delegation-token")
					.contentType(MediaType.APPLICATION_JSON)
					.content("{\"subject\":\"guest-42\",\"agent_id\":\"spring_guest_agent\",\"scope\":[\"route_plan\"],\"ttl_seconds\":10}")
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("issued")))
			.andExpect(jsonPath("$.proof.status", equalTo("verified")))
			.andExpect(jsonPath("$.proof.signature_status", equalTo("valid")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andReturn();
		var delegationToken = objectMapper.readTree(delegation.getResponse().getContentAsByteArray()).get("token");
		org.assertj.core.api.Assertions.assertThat(delegationToken.get("exp").asLong() - delegationToken.get("iat").asLong()).isEqualTo(60);

		MvcResult scopedDelegation = mockMvc.perform(
				post("/api/park/delegation-token")
					.contentType(MediaType.APPLICATION_JSON)
					.content("{\"subject\":\"guest-42\",\"agent_id\":\"spring_guest_agent\",\"scope\":[\"location\",\"policy_check\",\"preferences\",\"route_plan\",\"safety_notice\",\"session_commit\",\"wait_time_alert\"],\"ttl_seconds\":600}")
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.proof.status", equalTo("verified")))
			.andReturn();
		var scopedDelegationToken = objectMapper.readTree(scopedDelegation.getResponse().getContentAsByteArray()).get("token");
		MvcResult handshake = mockMvc.perform(
				post("/api/park/handshake")
					.contentType(MediaType.APPLICATION_JSON)
					.content(objectMapper.writeValueAsString(Map.of(
						"agent_id", "spring_guest_agent",
						"represents", "guest-42",
						"requested_session", "spring_session",
						"delegation_token", objectMapper.convertValue(scopedDelegationToken, Map.class)
					)))
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("verified")))
			.andExpect(jsonPath("$.session.state", equalTo("verified")))
			.andExpect(jsonPath("$.case_evaluation.case", equalTo("identity_trust")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andReturn();
		String sessionId = objectMapper.readTree(handshake.getResponse().getContentAsByteArray()).get("session").get("session_id").asText();

		mockMvc.perform(get("/api/park/session/" + sessionId))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.session.session_id", equalTo(sessionId)))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(
				post("/api/park/session/" + sessionId + "/capabilities")
					.contentType(MediaType.APPLICATION_JSON)
					.content(objectMapper.writeValueAsString(Map.of(
						"can_share", List.of("budget"),
						"can_receive", List.of("route_plan"),
						"delegation_token", objectMapper.convertValue(scopedDelegationToken, Map.class)
					)))
			)
			.andExpect(status().isForbidden());

		mockMvc.perform(
				post("/api/park/session/" + sessionId + "/capabilities")
					.contentType(MediaType.APPLICATION_JSON)
					.content(objectMapper.writeValueAsString(Map.of(
						"can_share", List.of("location"),
						"can_receive", List.of("route_plan", "wait_time_alert"),
						"cannot_do", List.of("auto_purchase"),
						"delegation_token", objectMapper.convertValue(scopedDelegationToken, Map.class)
					)))
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("scoped")))
			.andExpect(jsonPath("$.session.state", equalTo("scoped")))
			.andExpect(jsonPath("$.case_evaluation.case", equalTo("capability_scope")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(
				post("/api/park/session/" + sessionId + "/intent")
					.contentType(MediaType.APPLICATION_JSON)
					.content(objectMapper.writeValueAsString(Map.of(
						"goal", "maximize_family_satisfaction",
						"constraints", Map.of("avoid_wait_over_minutes", 35, "food_allergy", "peanut"),
						"delegation_token", objectMapper.convertValue(scopedDelegationToken, Map.class)
					)))
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("intent_accepted")))
			.andExpect(jsonPath("$.session.state", equalTo("intent_accepted")))
			.andExpect(jsonPath("$.session.intent.park_agent.optimization_targets[3]", equalTo("safe_food")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(
				post("/api/park/session/" + sessionId + "/propose")
					.contentType(MediaType.APPLICATION_JSON)
					.content(objectMapper.writeValueAsString(Map.of(
						"walking_priority", "highest",
						"delegation_token", objectMapper.convertValue(scopedDelegationToken, Map.class)
					)))
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("proposal_ready")))
			.andExpect(jsonPath("$.session.state", equalTo("negotiating")))
			.andExpect(jsonPath("$.proposal.proposal_id", notNullValue()))
			.andExpect(jsonPath("$.session.policy_decisions[0].action", equalTo("route_change")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(
				post("/api/park/session/" + sessionId + "/counter")
					.contentType(MediaType.APPLICATION_JSON)
					.content(objectMapper.writeValueAsString(Map.of(
						"priority_change", Map.of("walking_distance", "highest"),
						"delegation_token", objectMapper.convertValue(scopedDelegationToken, Map.class)
					)))
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("proposal_revised")))
			.andExpect(jsonPath("$.proposal.proposal_id", endsWith("_r1")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(
				post("/api/park/session/" + sessionId + "/commit")
					.contentType(MediaType.APPLICATION_JSON)
					.content(objectMapper.writeValueAsString(Map.of(
						"accepted", true,
						"notify_user", true,
						"delegation_token", objectMapper.convertValue(scopedDelegationToken, Map.class)
					)))
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("committed")))
			.andExpect(jsonPath("$.commitment.accepted_proposal_id", endsWith("_r1")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(
				post("/api/park/session/" + sessionId + "/monitor")
					.contentType(MediaType.APPLICATION_JSON)
					.content(objectMapper.writeValueAsString(Map.of(
						"event", "wave_pool_safety_delay",
						"delegation_token", objectMapper.convertValue(scopedDelegationToken, Map.class)
					)))
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("monitoring")))
			.andExpect(jsonPath("$.monitoring.policy_gate.safety_delay", equalTo("cannot_override")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(
				post("/api/park/internal-agents/commerce/evaluate")
					.contentType(MediaType.APPLICATION_JSON)
					.content(objectMapper.writeValueAsString(Map.of(
						"session_id", sessionId,
						"action", "payment",
						"amount", 1,
						"reason", "certification payment boundary probe",
						"delegation_token", objectMapper.convertValue(scopedDelegationToken, Map.class)
					)))
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("blocked")))
			.andExpect(jsonPath("$.decision.action", equalTo("payment")))
			.andExpect(jsonPath("$.decision.allowed", equalTo(false)))
			.andExpect(jsonPath("$.case_evaluation.case", equalTo("commerce_payment_probe")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(
				post("/api/park/internal-agents/queue/reroute")
					.contentType(MediaType.APPLICATION_JSON)
					.content(objectMapper.writeValueAsString(Map.of(
						"session_id", sessionId,
						"walking_priority", "highest",
						"reason", "certification route boundary probe",
						"delegation_token", objectMapper.convertValue(scopedDelegationToken, Map.class)
					)))
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("recommended")))
			.andExpect(jsonPath("$.proposal.proposal_id", endsWith("_queue")))
			.andExpect(jsonPath("$.case_evaluation.case", equalTo("queue_reroute")))
			.andExpect(jsonPath("$.session.proposal.proposal_id", endsWith("_queue")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(
				post("/api/park/session/" + sessionId + "/receipt")
					.contentType(MediaType.APPLICATION_JSON)
					.content(objectMapper.writeValueAsString(Map.of(
						"outcome", "spring lifecycle proof",
						"delegation_token", objectMapper.convertValue(scopedDelegationToken, Map.class)
					)))
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("ready")))
			.andExpect(jsonPath("$.receipt.receipt_id", notNullValue()))
			.andExpect(jsonPath("$.receipt.policy_gates_triggered", notNullValue()))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(
				post("/api/park/agent-onboarding/register")
					.contentType(MediaType.APPLICATION_JSON)
					.content("""
						{
							"agent_id":"Spring Guest Agent",
							"display_name":"Spring Guest Agent",
							"partner_id":"spring_onboarding_partner",
							"partner_name":"Spring Onboarding Partner",
							"requested_scopes":["location","route_plan","payment"],
							"partner_allowed_scopes":["location","route_plan"],
							"cannot_do":["auto_purchase"],
							"represents":"guest-42"
						}
						""")
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("registered")))
			.andExpect(jsonPath("$.agent.agent_id", equalTo("spring_guest_agent")))
			.andExpect(jsonPath("$.agent.scope_request_status", equalTo("rejected")))
			.andExpect(jsonPath("$.agent.disallowed_scopes[0]", equalTo("payment")))
			.andExpect(jsonPath("$.next", equalTo("/api/park/agent-onboarding/spring_guest_agent/certify")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(get("/api/park/agent-onboarding/spring_guest_agent"))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("found")))
			.andExpect(jsonPath("$.agent.partner.partner_id", equalTo("spring_onboarding_partner")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(
				post("/api/park/agent-onboarding/spring_guest_agent/certify")
					.contentType(MediaType.APPLICATION_JSON)
					.content(objectMapper.writeValueAsString(Map.of("requested_scopes", List.of("location", "route_plan", "payment"))))
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("blocked")))
			.andExpect(jsonPath("$.certification.partner_disallowed_scopes[0]", equalTo("payment")))
			.andExpect(jsonPath("$.certification.credential").doesNotExist())
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(
				post("/api/park/agent-onboarding/register")
					.contentType(MediaType.APPLICATION_JSON)
					.content("""
						{
							"agent_id":"Spring Certified Agent",
							"display_name":"Spring Certified Agent",
							"partner_id":"spring_certified_partner",
							"partner_name":"Spring Certified Partner",
							"requested_scopes":["location","policy_check","preferences","route_plan","wait_time_alert"],
							"partner_allowed_scopes":["location","policy_check","preferences","route_plan","wait_time_alert"],
							"cannot_do":["auto_purchase","share_health_data","accept_refund_without_user"],
							"represents":"guest-42"
						}
						""")
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("registered")))
			.andExpect(jsonPath("$.agent.scope_request_status", equalTo("accepted")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		MvcResult issuedCertification = mockMvc.perform(
				post("/api/park/agent-onboarding/spring_certified_agent/certify")
					.contentType(MediaType.APPLICATION_JSON)
					.content(objectMapper.writeValueAsString(Map.of(
						"requested_scopes", List.of("location", "policy_check", "preferences", "route_plan", "wait_time_alert"),
						"represents", "guest-42"
					)))
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("approved")))
			.andExpect(jsonPath("$.certification.approval", equalTo("approved_for_guest_route_planning")))
			.andExpect(jsonPath("$.certification.score", equalTo(1.0)))
			.andExpect(jsonPath("$.certification.credential.alg", equalTo("EdDSA")))
			.andExpect(jsonPath("$.session.case_evaluations", notNullValue()))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andReturn();
		var issuedCredential = objectMapper.readTree(issuedCertification.getResponse().getContentAsByteArray()).get("certification").get("credential");

		mockMvc.perform(
				post("/api/park/agent-onboarding/verify-credential")
					.contentType(MediaType.APPLICATION_JSON)
					.content(objectMapper.writeValueAsString(Map.of("credential", objectMapper.convertValue(issuedCredential, Map.class))))
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("verified")))
			.andExpect(jsonPath("$.agent_id", equalTo("spring_certified_agent")))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(get("/api/park/agent-onboarding/missing_agent"))
			.andExpect(status().isNotFound());

		mockMvc.perform(
				post("/api/park/agent-onboarding/revoke-credential")
					.header("authorization", "Bearer " + signedRoleToken("ops_team"))
					.contentType(MediaType.APPLICATION_JSON)
					.content("{\"certification_id\":\"cert-spring-revoke\"}")
			)
			.andExpect(status().isForbidden());

		mockMvc.perform(
					post("/api/park/agent-onboarding/revoke-credential")
						.header("authorization", "Bearer " + signedRoleToken("ml_ops_admin"))
						.contentType(MediaType.APPLICATION_JSON)
						.content(objectMapper.writeValueAsString(Map.of("certification_id", certificationId, "agent_id", "agent-spring", "reason", "test", "revoked_by", "spring-admin")))
				)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("revoked")))
			.andExpect(jsonPath("$.revocation.certification_id", equalTo(certificationId)))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(
				post("/api/park/agent-onboarding/verify-credential")
					.contentType(MediaType.APPLICATION_JSON)
					.content(objectMapper.writeValueAsString(Map.of("credential", credential)))
			)
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.status", equalTo("rejected")))
			.andExpect(jsonPath("$.signature_status", equalTo("valid")))
			.andExpect(jsonPath("$.revocation.certification_id", equalTo(certificationId)))
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")));

		mockMvc.perform(get("/api/park/agent-trust/revocations?limit=10").header("authorization", "Bearer " + signedRoleToken("ml_ops_admin")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.runtime", equalTo("java_spring")))
			.andExpect(jsonPath("$.revocations", notNullValue()));

		mockMvc.perform(get("/api/park/migration/java-spring/status").header("authorization", "Bearer " + signedRoleToken("ml_ops_admin")))
			.andExpect(status().isOk())
			.andExpect(jsonPath("$.spring_owned_routes", notNullValue()));
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

	private Map<String, Object> signedCertificationCredential(String keyId, String version, String certificationId, long expiresAt) throws Exception {
		long issuedAt = Instant.now().getEpochSecond();
		Map<String, Object> claims = new LinkedHashMap<>();
		claims.put("agent_id", "spring_guest_agent");
		claims.put("certification_id", certificationId);
		claims.put("jti", certificationId);
		claims.put("approval", "approved_for_guest_route_planning");
		claims.put("scope", List.of("route_plan", "wait_time_alert"));
		claims.put("score_basis_points", 10000);
		claims.put("required_cases", List.of("capability_scope", "commerce_payment_probe", "identity_trust", "queue_reroute"));
		claims.put("iat", issuedAt);
		claims.put("exp", expiresAt);
		claims.put("alg", "EdDSA");
		claims.put("issuer", "parkpulse_agent_onboarding_authority");
		claims.put("iss", "parkpulse_agent_onboarding_authority");
		claims.put("kid", keyId);
		claims.put("token_type", "parkpulse_agent_certification");
		Map<String, Object> credential = new LinkedHashMap<>(claims);
		credential.put("sig", signCertificationClaims(claims, version));
		return credential;
	}

	private String signCertificationClaims(Map<String, Object> claims, String version) throws Exception {
		byte[] seed = certificationPrivateSeed(version);
		Ed25519Signer signer = new Ed25519Signer();
		signer.init(true, new Ed25519PrivateKeyParameters(seed, 0));
		byte[] message = objectMapper.writer().with(JsonWriteFeature.ESCAPE_NON_ASCII).writeValueAsString(new java.util.TreeMap<>(claims)).getBytes(StandardCharsets.UTF_8);
		signer.update(message, 0, message.length);
		return base64Url(signer.generateSignature());
	}

	private byte[] certificationPrivateSeed(String version) throws Exception {
		byte[] secret = "parkpulse-local-agent-handshake-demo-secret".getBytes(StandardCharsets.UTF_8);
		byte[] suffix = "v1".equals(version)
			? ":parkpulse-agent-cert-ed25519".getBytes(StandardCharsets.UTF_8)
			: (":parkpulse-agent-cert-ed25519:" + version).getBytes(StandardCharsets.UTF_8);
		MessageDigest digest = MessageDigest.getInstance("SHA-256");
		digest.update(secret);
		digest.update(suffix);
		return digest.digest();
	}

}
