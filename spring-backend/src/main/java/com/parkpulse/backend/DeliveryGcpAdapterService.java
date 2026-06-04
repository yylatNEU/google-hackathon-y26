package com.parkpulse.backend;

import com.google.auth.oauth2.AccessToken;
import com.google.auth.oauth2.GoogleCredentials;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.Base64;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;

@Service
public class DeliveryGcpAdapterService {
    private static final List<String> CLOUD_PLATFORM_SCOPE = List.of("https://www.googleapis.com/auth/cloud-platform");
    private static final List<String> FCM_SCOPE = List.of("https://www.googleapis.com/auth/firebase.messaging");

    private final Environment environment;
    private final ObjectMapper objectMapper;
    private final HttpClient httpClient;

    public DeliveryGcpAdapterService(Environment environment, ObjectMapper objectMapper) {
        this.environment = environment;
        this.objectMapper = objectMapper;
        this.httpClient = HttpClient.newBuilder()
            .connectTimeout(java.time.Duration.ofMillis(intEnv("PARKPULSE_GCP_HTTP_TIMEOUT_MS", 8000)))
            .followRedirects(HttpClient.Redirect.NEVER)
            .build();
    }

    public Map<String, Object> status() {
        String project = projectId();
        String topic = env("PARKPULSE_PUBSUB_TOPIC", "");
        Map<String, Object> payload = orderedMap();
        payload.put("platform", "Spring GCP delivery adapters");
        payload.put("runtime", "java_spring");
        payload.put("project", project.isBlank() ? null : project);
        Map<String, Object> pubsub = orderedMap();
        pubsub.put("enabled", envBool("ENABLE_PARKPULSE_PUBSUB"));
        pubsub.put("topic", topic.isBlank() ? null : topicPath(topic));
        pubsub.put("eventarc_endpoint", "/api/gcp/eventarc/park-signal");
        pubsub.put("ready", !project.isBlank() && !topic.isBlank() && envBool("ENABLE_PARKPULSE_PUBSUB"));
        pubsub.put("mode", envBool("PARKPULSE_ENABLE_SPRING_LIVE_GCP_PUBLISH") ? "live_publish_enabled" : "spring_queue_only");
        payload.put("pubsub", pubsub);
        payload.put("fcm", Map.of(
            "enabled", envBool("ENABLE_PARKPULSE_FCM"),
            "pseudo_enabled", envBool("ENABLE_PARKPULSE_PSEUDO_FCM"),
            "mode", envBool("ENABLE_PARKPULSE_FCM") ? "firebase_cloud_messaging_configured" : envBool("ENABLE_PARKPULSE_PSEUDO_FCM") ? "pseudo_firebase" : "disabled",
            "guest_topic", env("PARKPULSE_FCM_GUEST_TOPIC", "parkpulse-guest-app"),
            "worker_topic", env("PARKPULSE_FCM_WORKER_TOPIC", "parkpulse-worker-device"),
            "ready", envBool("ENABLE_PARKPULSE_FCM") || envBool("ENABLE_PARKPULSE_PSEUDO_FCM"),
            "pseudo", pseudoFirebaseStatus()
        ));
        payload.put("firestore", firestoreStatus());
        payload.put("dataflow", dataflowStatus());
        return payload;
    }

    public Map<String, Object> enrichDeliveryDispatch(Map<String, Object> dispatch) {
        Map<String, Object> payload = mutableMap(dispatch.get("payload"));
        Object agentBoundary = dispatch.get("agentBoundary");
        Map<String, Object> eventPayload = orderedMap();
        eventPayload.put("dispatchId", dispatch.get("id"));
        eventPayload.put("channel", dispatch.get("channel"));
        eventPayload.put("targetSystem", dispatch.get("targetSystem"));
        eventPayload.put("status", dispatch.get("status"));
        eventPayload.put("agentBoundary", agentBoundary);
        eventPayload.put("payload", payload);

        Map<String, Object> pubsub = publishParkEvent(
            "parkpulse.delivery.dispatch",
            eventPayload,
            Map.of("channel", string(dispatch.get("channel")), "status", string(dispatch.get("status")))
        );
        Map<String, Object> result = orderedMap();
        result.put("pubsub", pubsub);
        result.put("fcm", fcmDispatchForDelivery(dispatch));
        Map<String, Object> firestorePayload = orderedMap();
        firestorePayload.put("type", "parkpulse.delivery.dispatch");
        firestorePayload.put("agentBoundary", agentBoundary);
        firestorePayload.put("dispatch", dispatch);
        result.put("firestore", writeFirestoreOperation("dispatches", string(dispatch.get("id")), firestorePayload));
        result.put("dataflow", pubsub.get("dataflow"));
        result.put("agentBoundary", agentBoundary);
        if ("pending_operator_approval".equals(dispatch.get("status"))) {
            result.put("workflow", operatorWorkflow(dispatch, payload));
        }
        return result;
    }

    public Map<String, Object> publishApprovalDecision(Map<String, Object> dispatch, Map<String, Object> decision) {
        Map<String, Object> payload = mutableMap(dispatch.get("payload"));
        Object agentBoundary = dispatch.get("agentBoundary") instanceof Map<?, ?> ? dispatch.get("agentBoundary") : decision.get("agentBoundary");
        Map<String, Object> eventPayload = orderedMap();
        eventPayload.put("dispatchId", dispatch.get("id"));
        eventPayload.put("channel", dispatch.get("channel"));
        eventPayload.put("targetSystem", dispatch.get("targetSystem"));
        eventPayload.put("status", dispatch.get("status"));
        eventPayload.put("decision", decision);
        eventPayload.put("agentBoundary", agentBoundary);
        eventPayload.put("payload", payload);

        Map<String, Object> pubsub = publishParkEvent(
            "parkpulse.delivery.approval_decision",
            eventPayload,
            Map.of("channel", string(dispatch.get("channel")), "status", string(dispatch.get("status")), "decision", string(decision.get("decision")))
        );
        Map<String, Object> result = orderedMap();
        result.put("pubsub", pubsub);
        result.put("pseudoFirebase", pseudoFirebaseApproval(dispatch, decision, payload));
        result.put("firestore", writeFirestoreOperation("approvals", string(dispatch.get("id")), Map.of("type", "parkpulse.delivery.approval_decision", "event", eventPayload)));
        result.put("dataflow", pubsub.get("dataflow"));
        result.put("agentBoundary", agentBoundary);
        return result;
    }

    private Map<String, Object> publishParkEvent(String eventType, Map<String, Object> payload, Map<String, String> attributes) {
        Map<String, Object> dataflow = writeDataflowStreamEvent(eventType, payload, attributes);
        if (!envBool("ENABLE_PARKPULSE_PUBSUB")) {
            return Map.of("status", "skipped", "reason", "ENABLE_PARKPULSE_PUBSUB is false", "event_type", eventType, "dataflow", dataflow);
        }
        String topic = env("PARKPULSE_PUBSUB_TOPIC", "");
        if (topic.isBlank()) {
            return Map.of("status", "skipped", "reason", "PARKPULSE_PUBSUB_TOPIC is not set", "event_type", eventType, "dataflow", dataflow);
        }
        if (projectId().isBlank()) {
            return Map.of("status", "configured_incomplete", "reason", "GOOGLE_CLOUD_PROJECT is not set", "event_type", eventType, "dataflow", dataflow);
        }
        if (!envBool("PARKPULSE_ENABLE_SPRING_LIVE_GCP_PUBLISH")) {
            return Map.of("status", "queued_for_pubsub", "provider", "spring_gcp_adapter", "reason", "Spring live Pub/Sub publish is disabled", "event_type", eventType, "topic", topicPath(topic), "dataflow", dataflow);
        }
        try {
            String resolvedTopic = topicPath(topic);
            Map<String, Object> envelope = orderedMap();
            envelope.put("eventType", eventType);
            envelope.put("publishedAt", now());
            envelope.put("source", "parkpulse");
            envelope.put("payload", payload);
            Map<String, Object> message = orderedMap();
            message.put("data", Base64.getEncoder().encodeToString(toJson(envelope).getBytes(StandardCharsets.UTF_8)));
            message.put("attributes", attributes);
            Map<String, Object> requestPayload = Map.of("messages", List.of(message));
            HttpResponse<String> response = postJson(pubsubBaseUrl() + "/" + resolvedTopic + ":publish", requestPayload, CLOUD_PLATFORM_SCOPE);
            if (response.statusCode() < 200 || response.statusCode() >= 300) {
                return Map.of("status", "failed", "provider", "pubsub_rest", "http_status", response.statusCode(), "reason", truncate(response.body(), 300), "event_type", eventType, "topic", resolvedTopic, "dataflow", dataflow);
            }
            Map<String, Object> body = parseMap(response.body());
            Object messageIds = body.get("messageIds");
            return Map.of("status", "published", "provider", "pubsub_rest", "event_type", eventType, "topic", resolvedTopic, "message_ids", messageIds == null ? List.of() : messageIds, "dataflow", dataflow);
        } catch (Exception error) {
            return Map.of("status", "failed", "provider", "pubsub_rest", "reason", truncate(error.getMessage(), 300), "event_type", eventType, "topic", topicPath(topic), "dataflow", dataflow);
        }
    }

    private Map<String, Object> fcmDispatchForDelivery(Map<String, Object> dispatch) {
        String channel = string(dispatch.get("channel"));
        String topic;
        String title;
        if ("guest_app".equals(channel)) {
            topic = env("PARKPULSE_FCM_GUEST_TOPIC", "parkpulse-guest-app");
            title = "ParkPulse update";
        } else if ("worker_device".equals(channel)) {
            topic = env("PARKPULSE_FCM_WORKER_TOPIC", "parkpulse-worker-device");
            title = "ParkPulse task";
        } else {
            return Map.of("status", "skipped", "reason", "FCM is not configured for channel " + channel);
        }
        if (topic.isBlank()) {
            return Map.of("status", "skipped", "reason", "FCM topic is not set");
        }
        Map<String, Object> payload = mutableMap(dispatch.get("payload"));
        String body = firstString(payload.get("message"), payload.get("task"), dispatch.get("targetSystem"), "ParkPulse action");
        Map<String, Object> dataPayload = orderedMap();
        dataPayload.put("dispatchId", dispatch.get("id"));
        dataPayload.put("channel", channel);
        dataPayload.put("status", dispatch.get("status"));
        dataPayload.put("decisionId", payload.get("decisionId"));
        dataPayload.put("scenarioKey", payload.get("scenarioKey"));
        dataPayload.put("payload", payload);
        Map<String, String> data = stringData(dataPayload);
        if (envBool("ENABLE_PARKPULSE_PSEUDO_FCM")) {
            return sendPseudoFirebaseMessage(topic, title, truncate(body, 240), data, dispatch, payload);
        }
        if (!envBool("ENABLE_PARKPULSE_FCM")) {
            return Map.of("status", "skipped", "reason", "ENABLE_PARKPULSE_FCM is false");
        }
        if (projectId().isBlank()) {
            return Map.of("status", "skipped", "reason", "GOOGLE_CLOUD_PROJECT is not set");
        }
        try {
            Map<String, Object> message = Map.of(
                "message", Map.of(
                    "topic", topic,
                    "notification", Map.of("title", title, "body", truncate(body, 240)),
                    "data", data
                )
            );
            HttpResponse<String> response = postJson(fcmBaseUrl() + "/projects/" + projectId() + "/messages:send", message, FCM_SCOPE);
            if (response.statusCode() < 200 || response.statusCode() >= 300) {
                return Map.of("status", "failed", "provider", "fcm_http_v1", "http_status", response.statusCode(), "reason", truncate(response.body(), 300), "topic", topic);
            }
            Map<String, Object> responseBody = parseMap(response.body());
            return Map.of("status", "sent", "provider", "fcm_http_v1", "topic", topic, "name", string(responseBody.get("name")));
        } catch (Exception error) {
            return Map.of("status", "failed", "provider", "fcm_http_v1", "reason", truncate(error.getMessage(), 300), "topic", topic);
        }
    }

    private Map<String, Object> pseudoFirebaseApproval(Map<String, Object> dispatch, Map<String, Object> decision, Map<String, Object> payload) {
        String topic = env("PARKPULSE_FCM_WORKER_TOPIC", "parkpulse-worker-device");
        if (topic.isBlank()) {
            return Map.of("status", "skipped", "reason", "worker topic is not set");
        }
        return sendPseudoFirebaseMessage(
            topic,
            "ParkPulse approval decision",
            truncate(string(decision.getOrDefault("decision", "decision")) + " for " + firstString(payload.get("command"), dispatch.get("targetSystem"), dispatch.get("id")), 240),
            stringData(approvalDataPayload(dispatch, decision)),
            dispatch,
            Map.of("approvalDecision", decision, "payload", payload)
        );
    }

    private Map<String, Object> approvalDataPayload(Map<String, Object> dispatch, Map<String, Object> decision) {
        Map<String, Object> payload = orderedMap();
        payload.put("dispatchId", dispatch.get("id"));
        payload.put("channel", dispatch.get("channel"));
        payload.put("status", dispatch.get("status"));
        payload.put("decision", decision);
        return payload;
    }

    private Map<String, Object> sendPseudoFirebaseMessage(String topic, String title, String body, Map<String, String> data, Map<String, Object> dispatch, Map<String, Object> payload) {
        Map<String, Object> document = orderedMap();
        document.put("id", "pseudo_fcm_" + sha1(topic + ":" + dispatch.get("id") + ":" + body + ":" + now(), 14));
        document.put("createdAt", now());
        document.put("provider", "pseudo_firebase");
        document.put("topic", topic);
        document.put("notification", Map.of("title", title, "body", body));
        document.put("data", data);
        document.put("dispatchId", dispatch.get("id"));
        document.put("channel", dispatch.get("channel"));
        document.put("targetSystem", dispatch.get("targetSystem"));
        document.put("payload", payload);
        document.put("status", "sent");
        Map<String, Object> mirror = appendJsonl(pseudoFcmPath(), document);
        Map<String, Object> result = orderedMap();
        result.put("status", "sent");
        result.put("provider", "pseudo_firebase");
        result.put("topic", topic);
        result.put("name", document.get("id"));
        result.put("durable", mirror.get("durable"));
        result.put("endpoint", "/api/gcp/pseudo-firebase/messages");
        if (mirror.get("durabilityError") != null) {
            result.put("durabilityError", mirror.get("durabilityError"));
        }
        return result;
    }

    private Map<String, Object> writeFirestoreOperation(String kind, String documentId, Map<String, Object> payload) {
        String collection = firestoreCollection(kind);
        Map<String, Object> document = orderedMap();
        document.put("id", documentId.isBlank() ? "dispatch_" + sha1(toJson(payload), 12) : documentId);
        document.put("collection", collection);
        document.put("kind", kind);
        document.put("createdAt", now());
        document.put("payload", payload);
        Map<String, Object> mirror = appendJsonl(firestoreMirrorPath(), document);
        if (!envBool("ENABLE_PARKPULSE_FIRESTORE")) {
            return Map.of("status", "mirrored", "provider", "local_firestore_mirror", "reason", "ENABLE_PARKPULSE_FIRESTORE is false", "collection", collection, "document", document.get("id"), "mirror", mirror);
        }
        if (projectId().isBlank()) {
            return Map.of("status", "skipped", "reason", "GOOGLE_CLOUD_PROJECT is not set", "collection", collection, "document", document.get("id"), "mirror", mirror);
        }
        try {
            String url = firestoreBaseUrl()
                + "/projects/" + projectId()
                + "/databases/(default)/documents/" + collection
                + "/" + document.get("id");
            HttpResponse<String> response = patchJson(url, firestoreDocumentFields(document), CLOUD_PLATFORM_SCOPE);
            if (response.statusCode() < 200 || response.statusCode() >= 300) {
                return Map.of("status", "failed", "provider", "firestore_rest", "http_status", response.statusCode(), "reason", truncate(response.body(), 300), "collection", collection, "document", document.get("id"), "mirror", mirror);
            }
            return Map.of("status", "written", "provider", "firestore_rest", "collection", collection, "document", document.get("id"), "mirror", mirror);
        } catch (Exception error) {
            return Map.of("status", "failed", "provider", "firestore_rest", "reason", truncate(error.getMessage(), 300), "collection", collection, "document", document.get("id"), "mirror", mirror);
        }
    }

    private Map<String, Object> writeDataflowStreamEvent(String eventType, Map<String, Object> payload, Map<String, String> attributes) {
        Map<String, Object> document = orderedMap();
        document.put("id", "dataflow_evt_" + sha1(eventType + ":" + toJson(payload) + ":" + now(), 14));
        document.put("createdAt", now());
        document.put("eventType", eventType);
        document.put("attributes", attributes);
        document.put("payload", payload);
        document.put("pipeline", "parkpulse-telemetry-stream");
        Map<String, Object> mirror = appendJsonl(dataflowMirrorPath(), document);
        if (!envBool("ENABLE_PARKPULSE_DATAFLOW")) {
            return Map.of("status", "mirrored", "provider", "local_dataflow_mirror", "reason", "ENABLE_PARKPULSE_DATAFLOW is false", "event_type", eventType, "mirror", mirror);
        }
        if (!Boolean.TRUE.equals(dataflowStatus().get("ready"))) {
            return Map.of("status", "configured_incomplete", "event_type", eventType, "mirror", mirror, "reason", "Dataflow template, project, or location is missing");
        }
        return Map.of("status", "queued_for_dataflow", "provider", "dataflow", "event_type", eventType, "job_name", env("PARKPULSE_DATAFLOW_JOB_NAME", "parkpulse-telemetry-stream"), "mirror", mirror);
    }

    private Map<String, Object> firestoreStatus() {
        return Map.of(
            "enabled", envBool("ENABLE_PARKPULSE_FIRESTORE"),
            "ready", envBool("ENABLE_PARKPULSE_FIRESTORE") && !projectId().isBlank(),
            "project", projectId().isBlank() ? "" : projectId(),
            "collections", Map.of("dispatches", firestoreCollection("dispatches"), "approvals", firestoreCollection("approvals"), "events", firestoreCollection("events")),
            "mirror", mirrorStatus(firestoreMirrorPath())
        );
    }

    private Map<String, Object> dataflowStatus() {
        String template = env("PARKPULSE_DATAFLOW_TEMPLATE", "");
        return Map.of(
            "enabled", envBool("ENABLE_PARKPULSE_DATAFLOW"),
            "ready", envBool("ENABLE_PARKPULSE_DATAFLOW") && !projectId().isBlank() && !template.isBlank(),
            "project", projectId().isBlank() ? "" : projectId(),
            "location", env("PARKPULSE_DATAFLOW_LOCATION", env("GOOGLE_CLOUD_LOCATION", "us-central1")),
            "job_name", env("PARKPULSE_DATAFLOW_JOB_NAME", "parkpulse-telemetry-stream"),
            "template", template.isBlank() ? "" : template,
            "source_topic", topicPath(env("PARKPULSE_PUBSUB_TOPIC", "parkpulse-ops-events")),
            "mirror", mirrorStatus(dataflowMirrorPath()),
            "contract", dataflowContract()
        );
    }

    private Map<String, Object> pseudoFirebaseStatus() {
        return Map.of(
            "enabled", envBool("ENABLE_PARKPULSE_PSEUDO_FCM"),
            "ready", envBool("ENABLE_PARKPULSE_PSEUDO_FCM"),
            "message_count", countJsonl(pseudoFcmPath()),
            "path", pseudoFcmPath().toString(),
            "topics", Map.of("guest", env("PARKPULSE_FCM_GUEST_TOPIC", "parkpulse-guest-app"), "worker", env("PARKPULSE_FCM_WORKER_TOPIC", "parkpulse-worker-device"))
        );
    }

    private Map<String, Object> operatorWorkflow(Map<String, Object> dispatch, Map<String, Object> payload) {
        if (!envBool("ENABLE_PARKPULSE_WORKFLOWS")) {
            return Map.of("status", "skipped", "reason", "ENABLE_PARKPULSE_WORKFLOWS is false");
        }
        String project = projectId();
        String workflowId = env("PARKPULSE_WORKFLOW_ID", "");
        String location = env("PARKPULSE_WORKFLOW_LOCATION", env("GOOGLE_CLOUD_LOCATION", "us-central1"));
        if (project.isBlank() || workflowId.isBlank()) {
            return Map.of("status", "configured_incomplete", "reason", "GOOGLE_CLOUD_PROJECT or PARKPULSE_WORKFLOW_ID is missing", "dispatchId", dispatch.get("id"));
        }
        Map<String, Object> workflowPayload = orderedMap();
        workflowPayload.put("type", "parkpulse.delivery.approval");
        workflowPayload.put("dispatchId", dispatch.get("id"));
        workflowPayload.put("channel", dispatch.get("channel"));
        workflowPayload.put("targetSystem", dispatch.get("targetSystem"));
        workflowPayload.put("payload", payload);
        workflowPayload.put("callbackUrl", env("PARKPULSE_WORKFLOW_CALLBACK_URL", ""));
        workflowPayload.put("autoApprove", envBool("PARKPULSE_WORKFLOW_AUTO_APPROVE"));
        try {
            String url = workflowsBaseUrl()
                + "/projects/" + project
                + "/locations/" + location
                + "/workflows/" + workflowId
                + "/executions";
            HttpResponse<String> response = postJson(url, Map.of("argument", toJson(workflowPayload)), CLOUD_PLATFORM_SCOPE);
            if (response.statusCode() < 200 || response.statusCode() >= 300) {
                return Map.of("status", "failed", "provider", "workflows_rest", "http_status", response.statusCode(), "reason", truncate(response.body(), 300), "dispatchId", dispatch.get("id"));
            }
            Map<String, Object> responseBody = parseMap(response.body());
            return Map.of("status", "started", "provider", "workflows_rest", "dispatchId", dispatch.get("id"), "name", string(responseBody.get("name")));
        } catch (Exception error) {
            return Map.of("status", "failed", "provider", "workflows_rest", "reason", truncate(error.getMessage(), 300), "dispatchId", dispatch.get("id"));
        }
    }

    private Map<String, Object> dataflowContract() {
        return Map.of(
            "name", "ParkPulse real-time telemetry stream",
            "platform", "Google Cloud Dataflow",
            "sources", List.of("Pub/Sub park events", "queue telemetry", "worker acknowledgements", "guest app responses", "equipment command results", "operator approvals"),
            "transforms", List.of("normalize event envelope", "window by zone and scenario", "derive risk and response metrics", "route high-risk signals to Eventarc/Workflows", "write analytics-ready rows"),
            "sinks", List.of("BigQuery", "Firestore operations state", "Cloud Monitoring custom metrics"),
            "template_type", "Flex template recommended for a new Beam pipeline"
        );
    }

    private Map<String, Object> appendJsonl(Path path, Map<String, Object> document) {
        try {
            Files.createDirectories(path.getParent());
            Files.writeString(path, toJson(document) + "\n", StandardCharsets.UTF_8, Files.exists(path) ? java.nio.file.StandardOpenOption.APPEND : java.nio.file.StandardOpenOption.CREATE);
            return Map.of("durable", true, "path", path.toString(), "durabilityError", "");
        } catch (Exception error) {
            return Map.of("durable", false, "path", path.toString(), "durabilityError", truncate(error.getMessage(), 300));
        }
    }

    private Map<String, Object> mirrorStatus(Path path) {
        return Map.of("ready", true, "path", path.toString(), "count", countJsonl(path), "error", "");
    }

    private long countJsonl(Path path) {
        try {
            if (!Files.exists(path)) {
                return 0;
            }
            try (var lines = Files.lines(path, StandardCharsets.UTF_8)) {
                return lines.filter(line -> !line.isBlank()).count();
            }
        } catch (Exception ignored) {
            return 0;
        }
    }

    private Path runtimePath(String configuredProperty, String defaultName) {
        String configured = env(configuredProperty, "");
        if (!configured.isBlank()) {
            return Path.of(configured);
        }
        return Path.of(env("PARKPULSE_RUNTIME_DIR", "/tmp/parkpulse")).resolve(defaultName);
    }

    private HttpResponse<String> postJson(String url, Object payload, List<String> scopes) throws Exception {
        HttpRequest request = HttpRequest.newBuilder(URI.create(url))
            .timeout(java.time.Duration.ofMillis(intEnv("PARKPULSE_GCP_HTTP_TIMEOUT_MS", 8000)))
            .header("authorization", "Bearer " + accessToken(scopes))
            .header("content-type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(toJson(payload), StandardCharsets.UTF_8))
            .build();
        return httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
    }

    private HttpResponse<String> patchJson(String url, Object payload, List<String> scopes) throws Exception {
        HttpRequest request = HttpRequest.newBuilder(URI.create(url))
            .timeout(java.time.Duration.ofMillis(intEnv("PARKPULSE_GCP_HTTP_TIMEOUT_MS", 8000)))
            .header("authorization", "Bearer " + accessToken(scopes))
            .header("content-type", "application/json")
            .method("PATCH", HttpRequest.BodyPublishers.ofString(toJson(payload), StandardCharsets.UTF_8))
            .build();
        return httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
    }

    private String accessToken(List<String> scopes) throws Exception {
        String explicit = env("PARKPULSE_GCP_ACCESS_TOKEN", "");
        if (!explicit.isBlank()) {
            return explicit;
        }
        GoogleCredentials credentials = GoogleCredentials.getApplicationDefault().createScoped(scopes);
        credentials.refreshIfExpired();
        AccessToken token = credentials.getAccessToken();
        if (token == null || token.getTokenValue() == null || token.getTokenValue().isBlank()) {
            credentials.refresh();
            token = credentials.getAccessToken();
        }
        return token == null ? "" : token.getTokenValue();
    }

    private Map<String, Object> firestoreDocumentFields(Map<String, Object> document) {
        Map<String, Object> fields = orderedMap();
        fields.put("id", Map.of("stringValue", string(document.get("id"))));
        fields.put("collection", Map.of("stringValue", string(document.get("collection"))));
        fields.put("kind", Map.of("stringValue", string(document.get("kind"))));
        fields.put("createdAt", Map.of("timestampValue", string(document.get("createdAt"))));
        fields.put("payloadJson", Map.of("stringValue", truncate(toJson(document.get("payload")), 100_000)));
        Map<String, Object> root = orderedMap();
        root.put("fields", fields);
        return root;
    }

    private Map<String, Object> parseMap(String raw) {
        if (raw == null || raw.isBlank()) {
            return orderedMap();
        }
        try {
            Object parsed = objectMapper.readValue(raw, Object.class);
            return mutableMap(parsed);
        } catch (Exception ignored) {
            return orderedMap();
        }
    }

    private Path pseudoFcmPath() {
        return runtimePath("PARKPULSE_PSEUDO_FCM_OUTBOX", "pseudo_fcm_messages.jsonl");
    }

    private Path firestoreMirrorPath() {
        return runtimePath("PARKPULSE_FIRESTORE_MIRROR", "firestore_operations.jsonl");
    }

    private Path dataflowMirrorPath() {
        return runtimePath("PARKPULSE_DATAFLOW_MIRROR", "dataflow_stream_events.jsonl");
    }

    private String firestoreCollection(String kind) {
        String specific = env("PARKPULSE_FIRESTORE_" + kind.toUpperCase(Locale.ROOT) + "_COLLECTION", "");
        if (!specific.isBlank()) {
            return specific;
        }
        String root = env("PARKPULSE_FIRESTORE_COLLECTION", "parkpulse_operations");
        return root + "_" + kind;
    }

    private String topicPath(String topic) {
        if (topic.startsWith("projects/")) {
            return topic;
        }
        String project = projectId();
        return project.isBlank() ? topic : "projects/" + project + "/topics/" + topic;
    }

    private String projectId() {
        return firstString(env("GOOGLE_CLOUD_PROJECT", ""), env("GCP_PROJECT", ""), env("GCLOUD_PROJECT", ""));
    }

    private boolean envBool(String name) {
        String raw = env(name, "").trim().toLowerCase(Locale.ROOT);
        return List.of("1", "true", "yes", "on").contains(raw);
    }

    private int intEnv(String name, int fallback) {
        try {
            return Integer.parseInt(env(name, String.valueOf(fallback)));
        } catch (NumberFormatException ignored) {
            return fallback;
        }
    }

    private String env(String name, String fallback) {
        String value = environment.getProperty(name);
        return value == null || value.isBlank() ? fallback : value.trim();
    }

    private String pubsubBaseUrl() {
        return stripTrailingSlash(env("PARKPULSE_PUBSUB_API_BASE_URL", "https://pubsub.googleapis.com/v1"));
    }

    private String fcmBaseUrl() {
        return stripTrailingSlash(env("PARKPULSE_FCM_API_BASE_URL", "https://fcm.googleapis.com/v1"));
    }

    private String firestoreBaseUrl() {
        return stripTrailingSlash(env("PARKPULSE_FIRESTORE_API_BASE_URL", "https://firestore.googleapis.com/v1"));
    }

    private String workflowsBaseUrl() {
        return stripTrailingSlash(env("PARKPULSE_WORKFLOWS_API_BASE_URL", "https://workflowexecutions.googleapis.com/v1"));
    }

    private String stripTrailingSlash(String value) {
        String raw = value == null ? "" : value.trim();
        while (raw.endsWith("/")) {
            raw = raw.substring(0, raw.length() - 1);
        }
        return raw;
    }

    private Map<String, Object> mutableMap(Object value) {
        Map<String, Object> result = orderedMap();
        if (value instanceof Map<?, ?> source) {
            source.forEach((key, item) -> result.put(String.valueOf(key), item));
        }
        return result;
    }

    private Map<String, String> stringData(Map<String, Object> values) {
        Map<String, String> result = new LinkedHashMap<>();
        values.forEach((key, value) -> {
            if (value != null) {
                result.put(key, value instanceof String ? truncate((String) value, 900) : truncate(toJson(value), 900));
            }
        });
        return result;
    }

    private String toJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception error) {
            return String.valueOf(value);
        }
    }

    private String sha1(String value, int chars) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-1").digest(value.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(digest).substring(0, chars);
        } catch (Exception error) {
            throw new IllegalStateException("Unable to hash delivery adapter payload.", error);
        }
    }

    private static String firstString(Object... values) {
        for (Object value : values) {
            if (value != null && !String.valueOf(value).isBlank()) {
                return String.valueOf(value);
            }
        }
        return "";
    }

    private static String string(Object value) {
        return value == null ? "" : String.valueOf(value);
    }

    private static String truncate(String value, int maxChars) {
        String raw = value == null ? "" : value;
        return raw.length() <= maxChars ? raw : raw.substring(0, maxChars);
    }

    private static String now() {
        return Instant.now().toString();
    }

    private static LinkedHashMap<String, Object> orderedMap() {
        return new LinkedHashMap<>();
    }
}
