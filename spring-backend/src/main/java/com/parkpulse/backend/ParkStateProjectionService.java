package com.parkpulse.backend;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Service;

@Service
public class ParkStateProjectionService {
    private final LiveFeedLedgerService liveFeedLedgerService;

    public ParkStateProjectionService(LiveFeedLedgerService liveFeedLedgerService) {
        this.liveFeedLedgerService = liveFeedLedgerService;
    }

    public Map<String, Object> state(String auditMode) {
        Map<String, Object> guestFlow = orderedMap();
        guestFlow.put("activePolicy", "spring-hot-path");
        guestFlow.put("activeScenario", Map.of(
            "key", "spring_gateway_state_lite",
            "name", "Spring Gateway Operating State",
            "description", "Compact operating state served by Java Spring while heavier simulation routes continue migrating.",
            "condition", "normal"
        ));
        guestFlow.put("interventions", List.of());
        guestFlow.put("representedGuests", 12480);
        guestFlow.put("avgSatisfaction", 86);
        guestFlow.put("activeGroups", 3120);
        guestFlow.put("zones", List.of(
            Map.of("id", "coveredPlaza", "name", "Covered Plaza", "density", 72, "waitMins", 12, "comfortScore", 78, "status", "watch", "flowType", "covered"),
            Map.of("id", "indoorHub", "name", "Indoor Hub", "density", 64, "waitMins", 10, "comfortScore", 84, "status", "normal", "flowType", "indoor"),
            Map.of("id", "foodCourt1", "name", "Food Court A District", "density", 69, "waitMins", 16, "comfortScore", 73, "status", "watch", "flowType", "dining"),
            Map.of("id", "careLagoon", "name", "Care Lagoon", "density", 41, "waitMins", 5, "comfortScore", 88, "status", "normal", "flowType", "care"),
            Map.of("id", "eastMidway", "name", "East Midway", "density", 58, "waitMins", 8, "comfortScore", 80, "status", "normal", "flowType", "outdoor")
        ));
        guestFlow.put("paths", List.of(
            Map.of("id", "main-loop", "from", "entrancePlaza", "to", "coveredPlaza", "congestion", 44, "status", "normal"),
            Map.of("id", "covered-to-indoor", "from", "coveredPlaza", "to", "indoorHub", "congestion", 51, "status", "normal"),
            Map.of("id", "indoor-to-care", "from", "indoorHub", "to", "careLagoon", "congestion", 35, "status", "normal"),
            Map.of("id", "food-loop", "from", "foodCourt1", "to", "coveredPlaza", "congestion", 62, "status", "watch")
        ));
        guestFlow.put("rides", List.of(
            Map.of("id", "dragonCoaster", "name", "Dragon Coaster", "zoneId", "coasterPlaza", "status", "operating", "waitMins", 42, "queueGuests", 680, "throughputGap", 12),
            Map.of("id", "indoorLaunch", "name", "Indoor Launch", "zoneId", "indoorHub", "status", "operating", "waitMins", 24, "queueGuests", 210, "throughputGap", 5),
            Map.of("id", "theaterB", "name", "Theater B", "zoneId", "indoorHub", "status", "operating", "waitMins", 8, "queueGuests", 80, "throughputGap", 0),
            Map.of("id", "riverRun", "name", "River Run", "zoneId", "eastMidway", "status", "operating", "waitMins", 18, "queueGuests", 220, "throughputGap", 4)
        ));

        Map<String, Object> payload = orderedMap();
        payload.put("product", Map.of(
            "name", "ParkPulse",
            "domain", "amusement_park_operations",
            "one_liner", "Real-time park operating state and supervised action routing.",
            "primary_collections", List.of("guestFlow", "weather", "staffing", "parkOps", "foodInventory")
        ));
        payload.put("simTime", Map.of("hour", 14, "minute", 15, "day", 1, "seasonIndex", 2));
        payload.put("weather", Map.of("condition", "partly_cloudy", "temperatureF", 82, "heatIndexF", 86, "humidity", 61, "windMph", 8, "stormRisk", 18));
        payload.put("energy", Map.of("gridLoadPercent", 63, "disruptionLoadMw", 0, "demandChargeRisk", "normal", "utilityPricePerMwh", 92, "carbonIntensity", 310));
        payload.put("staffing", Map.of("scheduled", 140, "checkedIn", 128, "openCallouts", 4, "medicalTeams", 4, "securityTeams", 5));
        payload.put("parkOps", Map.of("mode", "spring_hot_path", "outdoorCapacityCutPct", 0, "rideConflictCount", 1, "atRiskRides", 1, "guestRecoveryPressure", 28, "staffReadyPct", 91));
        payload.put("incidentReadiness", Map.of("accessibilityRoutesOpen", true, "shelterMode", false, "operatorEscalation", "normal", "firstAidReady", true));
        payload.put("foodInventory", Map.of(
            "locations", List.of(
                Map.of("id", "harborTreats", "name", "Harbor Treats", "zoneId", "foodCourt1", "pickupEtaMinutes", 14, "mobileOrderBacklog", 22, "availableItems", List.of("nut-free snack pack", "fruit cup"), "allergenProtocols", List.of("ingredient binder", "cross-contact check")),
                Map.of("id", "mainStreetBowls", "name", "Main Street Bowls", "zoneId", "foodCourt2", "pickupEtaMinutes", 19, "mobileOrderBacklog", 31, "availableItems", List.of("gluten-free bowl", "dairy-free bowl"), "allergenProtocols", List.of("manager confirmation"))
            )
        ));
        payload.put("guestFlow", guestFlow);
        payload.put("alerts", List.of(Map.of("id", "spring-state-lite", "severity", "info", "message", "Spring is serving the hot state-lite route without Python fallback.")));
        payload.put("operationsAudit", Map.of(
            "ready", true,
            "mode", auditMode,
            "findings", List.of(),
            "policy_refs", List.of("PARK-SAFE-001", "PARK-OPS-001", "PARK-CARE-001")
        ));
        payload.put("heartbeatController", Map.of("status", "ready", "runtime", "java_spring"));
        payload.put("heartbeatExplanation", Map.of("status", "ready", "summary", "Compact Spring state is available for UI polling."));
        payload.put("runtime", "java_spring");
        payload.put("source_of_truth", "spring_hot_path_sqlite_authority");
        payload.put("updated_at", Instant.now().toString());
        applyLiveFeedOverrides(payload);
        return payload;
    }

    private void applyLiveFeedOverrides(Map<String, Object> state) {
        List<Map<String, Object>> events = liveFeedLedgerService.recentLiveFeedEvents(80);
        if (events.isEmpty()) {
            return;
        }
        Map<String, Object> evidence = orderedMap();
        for (Map<String, Object> record : events) {
            Map<String, Object> payload = mapValue(record.get("payload"));
            String source = string(record.get("source"), string(payload.get("source"), ""));
            String signalType = string(record.get("signal_type"), string(payload.get("signal_type"), ""));
            Map<String, Object> value = mapValue(payload.get("value"));
            if (payload.get("statePatch") instanceof Map<?, ?> patch) {
                mergeStatePatch(state, mapValue(patch));
            }
            if (payload.get("guestFlow") instanceof Map<?, ?> guestFlow) {
                Map<String, Object> merged = mapValue(state.get("guestFlow"));
                merged.putAll(mapValue(guestFlow));
                state.put("guestFlow", merged);
            }
            if (payload.get("weather") instanceof Map<?, ?> weather) {
                Map<String, Object> merged = mapValue(state.get("weather"));
                merged.putAll(mapValue(weather));
                state.put("weather", merged);
            }
            if (payload.get("foodInventory") instanceof Map<?, ?> food) {
                state.put("foodInventory", mapValue(food));
            }
            if (payload.get("incidentReadiness") instanceof Map<?, ?> readiness) {
                Map<String, Object> merged = mapValue(state.get("incidentReadiness"));
                merged.putAll(mapValue(readiness));
                state.put("incidentReadiness", merged);
            }
            if ("weather".equals(source) && ("weather_state".equals(signalType) || !value.isEmpty())) {
                applyWeatherValue(state, value);
                evidence.put("weather", "trusted_live_feed");
            }
            if (List.of("food", "food_ops").contains(source) || List.of("inventory", "mobile_backlog", "prep_eta", "kitchen_load").contains(signalType)) {
                applyFoodValue(state, payload, value);
                evidence.put("food_ops", "trusted_live_feed");
            }
            if ("accessibility".equals(source) || "accessibility_route_status".equals(signalType)) {
                Map<String, Object> readiness = mapValue(state.get("incidentReadiness"));
                readiness.put("accessibilityRoutesOpen", !Boolean.FALSE.equals(value.get("accessibility_routes_open")));
                state.put("incidentReadiness", readiness);
                evidence.put("accessibility", "trusted_live_feed");
            }
        }
        if (!evidence.isEmpty()) {
            state.put("liveFeedEvidence", evidence);
            state.put("source_of_truth", "spring_hot_path_sqlite_authority+live_feed_ledger");
        }
    }

    private void mergeStatePatch(Map<String, Object> state, Map<String, Object> patch) {
        for (Map.Entry<String, Object> entry : patch.entrySet()) {
            if (entry.getValue() instanceof Map<?, ?> patchMap && state.get(entry.getKey()) instanceof Map<?, ?> stateMap) {
                Map<String, Object> merged = mapValue(stateMap);
                merged.putAll(mapValue(patchMap));
                state.put(entry.getKey(), merged);
            } else {
                state.put(entry.getKey(), entry.getValue());
            }
        }
    }

    private void applyWeatherValue(Map<String, Object> state, Map<String, Object> value) {
        if (value.isEmpty()) return;
        Map<String, Object> weather = mapValue(state.get("weather"));
        weather.put("source", "live_feed");
        if (value.get("weather_label") != null) weather.put("condition", value.get("weather_label"));
        if (value.get("temperature_f") != null) weather.put("temperatureF", value.get("temperature_f"));
        if (value.get("heat_index_f") != null) weather.put("heatIndexF", value.get("heat_index_f"));
        if (value.get("humidity_pct") != null) weather.put("humidity", value.get("humidity_pct"));
        if (value.get("wind_speed_mph") != null) weather.put("windMph", value.get("wind_speed_mph"));
        if (value.get("storm_risk_pct") != null) weather.put("stormRisk", value.get("storm_risk_pct"));
        state.put("weather", weather);
        if (truthy(value.get("lightning_window")) || intValue(value.get("storm_risk_pct"), 0) >= 55) {
            Map<String, Object> readiness = mapValue(state.get("incidentReadiness"));
            readiness.put("shelterMode", true);
            state.put("incidentReadiness", readiness);
        }
    }

    private void applyFoodValue(Map<String, Object> state, Map<String, Object> payload, Map<String, Object> value) {
        Map<String, Object> foodInventory = mapValue(state.get("foodInventory"));
        List<Object> locations = new java.util.ArrayList<>(listValue(foodInventory.get("locations")));
        Map<String, Object> update = value.isEmpty() ? payload : value;
        String id = string(firstPresent(update.get("location_id"), firstPresent(update.get("id"), payload.get("entity_id"))), "");
        if (id.isBlank() && update.get("location") instanceof Map<?, ?> location) {
            update = mapValue(location);
            id = string(update.get("id"), "");
        }
        if (id.isBlank()) return;
        Map<String, Object> merged = orderedMap();
        merged.put("id", id);
        for (Object item : locations) {
            Map<String, Object> row = mapValue(item);
            if (id.equals(string(row.get("id"), ""))) {
                merged.putAll(row);
            }
        }
        if (update.get("name") != null) merged.put("name", update.get("name"));
        if (update.get("zone_id") != null) merged.put("zoneId", update.get("zone_id"));
        if (update.get("zoneId") != null) merged.put("zoneId", update.get("zoneId"));
        if (update.get("pickup_eta_minutes") != null) merged.put("pickupEtaMinutes", update.get("pickup_eta_minutes"));
        if (update.get("pickupEtaMinutes") != null) merged.put("pickupEtaMinutes", update.get("pickupEtaMinutes"));
        if (update.get("mobile_order_backlog") != null) merged.put("mobileOrderBacklog", update.get("mobile_order_backlog"));
        if (update.get("mobileOrderBacklog") != null) merged.put("mobileOrderBacklog", update.get("mobileOrderBacklog"));
        if (update.get("available_items") != null) merged.put("availableItems", update.get("available_items"));
        if (update.get("availableItems") != null) merged.put("availableItems", update.get("availableItems"));
        String targetId = id;
        locations.removeIf(item -> targetId.equals(string(mapValue(item).get("id"), "")));
        locations.add(merged);
        foodInventory.put("locations", locations);
        state.put("foodInventory", foodInventory);
    }

    private Object firstPresent(Object left, Object right) {
        return left == null ? right : left;
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

    private List<Object> listValue(Object value) {
        if (value instanceof List<?> list) return new java.util.ArrayList<>(list);
        return List.of();
    }

    private String string(Object value, String defaultValue) {
        if (value == null) return defaultValue;
        String text = String.valueOf(value).trim();
        return text.isBlank() ? defaultValue : text;
    }

    private boolean truthy(Object value) {
        if (value instanceof Boolean bool) return bool;
        if (value instanceof Number number) return number.doubleValue() != 0;
        return List.of("1", "true", "yes", "on").contains(string(value, "").toLowerCase());
    }

    private int intValue(Object value, int defaultValue) {
        if (value instanceof Number number) return number.intValue();
        try {
            return value == null ? defaultValue : Integer.parseInt(String.valueOf(value));
        } catch (Exception error) {
            return defaultValue;
        }
    }

    private static LinkedHashMap<String, Object> orderedMap() {
        return new LinkedHashMap<>();
    }
}
