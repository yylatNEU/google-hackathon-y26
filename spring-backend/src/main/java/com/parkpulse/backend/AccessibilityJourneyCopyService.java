package com.parkpulse.backend;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Service;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

@Service
public class AccessibilityJourneyCopyService {
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

    private final Environment environment;
    private final ObjectMapper objectMapper;
    private final HttpClient httpClient = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(3)).build();

    public AccessibilityJourneyCopyService(Environment environment, ObjectMapper objectMapper) {
        this.environment = environment;
        this.objectMapper = objectMapper;
    }

    public Map<String, Object> guestCopy(Map<String, Object> profile, List<Map<String, Object>> steps, Map<String, Object> summary, Map<String, Object> liveState) {
        Map<String, Object> fallback = deterministicCopy(profile, steps, summary, liveState);
        if (!truthy(env("PARKPULSE_ACCESSIBILITY_LLM_COPY", "false"))) {
            return fallback;
        }
        String apiKey = env("GEMINI_API_KEY", env("GOOGLE_API_KEY", ""));
        if (apiKey.isBlank()) {
            fallback.put("llmStatus", "not_configured");
            fallback.put("provider", "spring_deterministic_copy_adapter");
            return fallback;
        }
        try {
            Map<String, Object> response = callGemini(apiKey, profile, steps, summary, liveState);
            String text = extractText(response);
            if (text.isBlank()) {
                fallback.put("llmStatus", "empty_response_fallback");
                return fallback;
            }
            Map<String, Object> payload = orderedMap();
            payload.put("status", "generated");
            payload.put("mode", "accessibility_journey_guest_copy");
            payload.put("provider", "gemini_generate_content");
            payload.put("model", geminiModel());
            payload.put("llmStatus", "used_for_copy_only");
            payload.put("llmControlsRoute", false);
            payload.put("headline", string(summary.get("headline"), "Accessible route"));
            payload.put("message", truncate(text, 900));
            payload.put("safetyNote", "Confirm allergies, medical needs, ride transfer help, equipment availability, and route blockages with trained park staff.");
            payload.put("fallbackAvailable", fallback);
            return payload;
        } catch (Exception error) {
            fallback.put("llmStatus", "provider_failed_fallback");
            fallback.put("providerError", truncate(error.getMessage(), 180));
            return fallback;
        }
    }

    private Map<String, Object> deterministicCopy(Map<String, Object> profile, List<Map<String, Object>> steps, Map<String, Object> summary, Map<String, Object> liveState) {
        String firstStop = steps.isEmpty() ? "Guest Services" : string(steps.get(0).get("location"), "Guest Services");
        String finalStop = steps.isEmpty() ? "a flexible exit point" : string(steps.get(steps.size() - 1).get("location"), "a flexible exit point");
        Map<String, Object> weather = mapValue(liveState.get("weather"));
        Map<String, Object> readiness = mapValue(liveState.get("readiness"));
        Map<String, Object> payload = orderedMap();
        payload.put("status", "generated");
        payload.put("mode", "accessibility_journey_guest_copy");
        payload.put("provider", "spring_deterministic_copy_adapter");
        payload.put("model", "deterministic_template");
        payload.put("llmStatus", "not_requested");
        payload.put("llmControlsRoute", false);
        payload.put("headline", string(summary.get("headline"), "Accessible route"));
        payload.put("message", "Start at " + firstStop + ", keep the pace slow, use planned breaks, and end near " + finalStop + ". The route uses current public park state where available and avoids unsupported accessibility or allergy promises.");
        payload.put("safetyNote", "Confirm allergies, medical needs, ride transfer help, equipment availability, and route blockages with trained park staff.");
        payload.put("liveContext", Map.of(
            "stormRisk", weather.getOrDefault("stormRisk", 0),
            "accessibilityRoutesOpen", readiness.getOrDefault("accessibilityRoutesOpen", true)
        ));
        return payload;
    }

    private Map<String, Object> callGemini(String apiKey, Map<String, Object> profile, List<Map<String, Object>> steps, Map<String, Object> summary, Map<String, Object> liveState) throws Exception {
        String prompt = """
            Write concise guest-facing accessibility route copy.
            Rules: do not claim ADA compliance, do not promise allergen-free food, do not provide medical advice, and do not change the route.
            Mention staff confirmation for allergies, medical needs, transfers, equipment, and route blockages.
            Return only the guest-facing copy.
            """;
        Map<String, Object> body = Map.of(
            "contents", List.of(Map.of("parts", List.of(Map.of("text", prompt + "\nRoute summary: " + toJson(summary) + "\nProfile: " + toJson(profile) + "\nSteps: " + toJson(steps) + "\nLive state: " + toJson(liveState))))),
            "generationConfig", Map.of("temperature", 0.2, "maxOutputTokens", 220)
        );
        HttpRequest request = HttpRequest.newBuilder()
            .uri(URI.create("https://generativelanguage.googleapis.com/v1beta/models/" + geminiModel() + ":generateContent"))
            .timeout(Duration.ofSeconds(8))
            .header("content-type", "application/json")
            .header("x-goog-api-key", apiKey)
            .POST(HttpRequest.BodyPublishers.ofString(toJson(body), StandardCharsets.UTF_8))
            .build();
        HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            throw new IllegalStateException("Gemini copy adapter returned HTTP " + response.statusCode());
        }
        return objectMapper.readValue(response.body(), MAP_TYPE);
    }

    private String extractText(Map<String, Object> response) {
        for (Object candidate : listValue(response.get("candidates"))) {
            Map<String, Object> row = mapValue(candidate);
            Map<String, Object> content = mapValue(row.get("content"));
            StringBuilder text = new StringBuilder();
            for (Object partObj : listValue(content.get("parts"))) {
                Map<String, Object> part = mapValue(partObj);
                if (part.get("text") != null) {
                    text.append(part.get("text")).append("\n");
                }
            }
            if (!text.isEmpty()) {
                return text.toString().trim();
            }
        }
        return "";
    }

    private String geminiModel() {
        return env("GEMINI_MODEL", env("GOOGLE_GENAI_MODEL", "gemini-2.5-flash"));
    }

    private String env(String key, String defaultValue) {
        String value = environment.getProperty(key);
        return value == null || value.isBlank() ? defaultValue : value;
    }

    private boolean truthy(String value) {
        return List.of("1", "true", "yes", "on").contains(value == null ? "" : value.trim().toLowerCase(Locale.ROOT));
    }

    private List<Object> listValue(Object value) {
        if (value instanceof List<?> list) return new java.util.ArrayList<>(list);
        return List.of();
    }

    private Map<String, Object> mapValue(Object value) {
        if (value instanceof Map<?, ?> map) {
            Map<String, Object> result = orderedMap();
            for (Map.Entry<?, ?> entry : map.entrySet()) {
                result.put(String.valueOf(entry.getKey()), entry.getValue());
            }
            return result;
        }
        return orderedMap();
    }

    private String string(Object value, String defaultValue) {
        if (value == null) return defaultValue;
        String text = String.valueOf(value).trim();
        return text.isBlank() ? defaultValue : text;
    }

    private String truncate(String value, int length) {
        String text = value == null ? "" : value;
        return text.length() <= length ? text : text.substring(0, length);
    }

    private String toJson(Object payload) {
        try {
            return objectMapper.writeValueAsString(payload);
        } catch (Exception error) {
            return "{}";
        }
    }

    private static LinkedHashMap<String, Object> orderedMap() {
        return new LinkedHashMap<>();
    }
}
