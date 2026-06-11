package com.parkpulse.backend;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import org.springframework.stereotype.Service;

@Service
public class AccessibilityJourneyService {
    private static final String VERSION = "2026-06-01.mvp1";
    private static final List<Map<String, Object>> SUPPORTED_NEEDS = List.of(
        need("low_sensory", "Low sensory", "Reduce loud shows, dense paths, long queues, and bright/high-stimulation venues.", List.of("sensory", "autism", "autistic", "quiet", "low sensory", "noise", "loud", "overstimulated", "calm")),
        need("mobility", "Mobility aware", "Prefer step-free paths, shorter walks, rest points, ramps, elevators, and nearby restrooms.", List.of("wheelchair", "mobility", "walker", "stairs", "step free", "elevator", "scooter", "elderly", "cane")),
        need("allergy", "Allergy aware dining", "Show only dining options with explicit allergy-handling metadata and staff confirmation steps.", List.of("allergy", "allergic", "peanut", "tree nut", "dairy", "gluten", "soy", "egg", "shellfish")),
        need("family_care", "Family and elder care", "Prioritize restrooms, water, shade, indoor breaks, stroller-friendly paths, and slower pacing.", List.of("child", "children", "kid", "stroller", "baby", "elderly", "grandparent", "bathroom", "restroom")),
        need("language", "Language support", "Keep instructions simple and provide staffed handoff points for translation help.", List.of("language", "translate", "translation", "spanish", "mandarin", "chinese", "visitor", "english")),
        need("medical", "Medical constraint", "Prioritize first aid proximity, heat breaks, hydration, and staff handoff for uncertain needs.", List.of("medical", "medicine", "medication", "heat", "asthma", "diabetes", "first aid", "pregnant"))
    );
    private static final List<String> PROHIBITED_CLAIMS = List.of(
        "guarantee_allergen_free_food",
        "diagnose_medical_condition",
        "declare_route_ada_compliant",
        "promise_staff_or_equipment_availability_without_confirmation",
        "override_ride_safety_or_height_rules",
        "collect_sensitive_medical_identity_details"
    );
    private static final List<String> COPY_RULES = List.of(
        "Separate verified park facts from recommendations.",
        "For allergies, tell the guest to confirm with trained restaurant staff before ordering.",
        "For medical uncertainty or immediate danger, hand off to staff or emergency services instead of giving medical advice.",
        "Prefer short steps with named landmarks, nearby restrooms, and backup options.",
        "Do not expose internal operator, staffing, policy, or private guest data."
    );

    private final VenueProfileService venueProfileService;
    private final ParkStateProjectionService parkStateProjectionService;
    private final AccessibilityJourneyMemoryService accessibilityJourneyMemoryService;
    private final AccessibilityJourneyCopyService accessibilityJourneyCopyService;

    public AccessibilityJourneyService(
        VenueProfileService venueProfileService,
        ParkStateProjectionService parkStateProjectionService,
        AccessibilityJourneyMemoryService accessibilityJourneyMemoryService,
        AccessibilityJourneyCopyService accessibilityJourneyCopyService
    ) {
        this.venueProfileService = venueProfileService;
        this.parkStateProjectionService = parkStateProjectionService;
        this.accessibilityJourneyMemoryService = accessibilityJourneyMemoryService;
        this.accessibilityJourneyCopyService = accessibilityJourneyCopyService;
    }

    public Map<String, Object> scope() {
        Map<String, Object> venueProfile = venueProfileService.profile();
        Map<String, Object> payload = orderedMap();
        payload.put("status", "ready");
        payload.put("mode", "accessibility_scope_spring");
        payload.put("runtime", "java_spring");
        payload.put("version", VERSION);
        payload.put("domain", "amusement_park_accessible_journey_builder");
        payload.put("purpose", "Customer-facing accessible journey planning from public park state, explicit accessibility metadata, and conservative safety boundaries.");
        payload.put("customer_bot_role", "preference_intake_and_plain_language_explanation");
        payload.put("planner_role", "deterministic_constraint_filtering_and_live_state_scoring");
        payload.put("human_authority", List.of(
            "allergy ingredient confirmation",
            "medical advice or emergency response",
            "ride transfer assistance and safety rules",
            "accessibility equipment availability",
            "private accommodation decisions"
        ));
        payload.put("supported_needs", SUPPORTED_NEEDS);
        payload.put("minimum_intake_fields", List.of(
            Map.of("id", "request", "label", "What kind of help or route is needed", "required", true),
            Map.of("id", "duration_minutes", "label", "Available time", "required", false),
            Map.of("id", "party", "label", "Party needs such as wheelchair, stroller, child, elderly guest, allergy, or language", "required", false),
            Map.of("id", "current_location", "label", "Current location or nearest landmark", "required", false),
            Map.of("id", "allergies", "label", "Allergies or dietary constraints", "required", false)
        ));
        payload.put("prohibited_claims", PROHIBITED_CLAIMS);
        payload.put("customer_copy_rules", COPY_RULES);
        payload.put("default_safety_banner", "Plans use live park conditions and accessibility metadata, but allergies, medical needs, ride transfer help, and equipment availability must be confirmed with trained park staff.");
        payload.put("venueProfile", venueProfileSummary(venueProfile));
        payload.put("startLocationOptions", startLocationOptions(venueProfile));
        payload.put("llmTools", llmToolManifest());
        return payload;
    }

    public Map<String, Object> journey(Map<String, Object> body) {
        Map<String, Object> requestBody = body == null ? Map.of() : body;
        Map<String, Object> profile = profileFromPayload(requestBody);
        Map<String, Object> venueProfile = venueProfileService.profile();
        Map<String, Object> parkState = currentParkState(requestBody);
        Map<String, Object> readiness = mapValue(venueProfile.get("readiness"));
        if (!Boolean.TRUE.equals(readiness.get("autofillAllowed"))) {
            return blockedJourney(profile, venueProfile);
        }

        List<Map<String, Object>> locations = catalogLocations(venueProfile);
        List<Map<String, Object>> certifiedPaths = certifiedPaths(venueProfile);
        List<Map<String, Object>> scored = scoreLocations(profile, locations, parkState);
        List<Map<String, Object>> dining = diningOptions(profile, scored, parkState);
        List<Map<String, Object>> attractions = attractionOptions(profile, scored, parkState);
        List<Map<String, Object>> steps = planSteps(profile, scored, dining, attractions, certifiedPaths, parkState);
        boolean review = requiresHumanReview(profile, parkState);
        Map<String, Object> payload = orderedMap();
        payload.put("status", "ok");
        payload.put("mode", "accessible_journey_builder_spring");
        payload.put("version", VERSION);
        payload.put("springRuntime", "java_spring");
        Map<String, Object> summary = orderedMap();
        summary.put("headline", headline(profile, dining));
        summary.put("durationMinutes", profile.get("durationMinutes"));
        summary.put("needs", profile.get("needs"));
        summary.put("confidence", confidence(profile, steps, dining));
        summary.put("requiresHumanReview", review);
        summary.put("reviewReason", review ? reviewReason(profile, parkState) : null);
        payload.put("summary", summary);
        payload.put("profile", profile);
        payload.put("planSteps", steps);
        payload.put("diningOptions", dining);
        payload.put("attractionOptions", attractions);
        payload.put("breakPlan", breakPlan(profile, steps));
        payload.put("staffHandoff", staffHandoff(profile, review));
        payload.put("guardrails", guardrails(profile, parkState));
        payload.put("evidence", evidence(venueProfile, locations, dining, attractions, parkState));
        payload.put("profileIntelligence", intelligenceReceipt(profile, venueProfile, steps, certifiedPaths));
        payload.put("learningReceipt", learningReceipt(profile, steps, review, parkState));
        Map<String, Object> liveState = liveStateReceipt(parkState);
        payload.put("liveState", liveState);
        payload.put("llmContract", llmContract());
        Map<String, Object> guestCopy = accessibilityJourneyCopyService.guestCopy(profile, steps, summary, liveState);
        payload.put("guestCopy", guestCopy);
        payload.put("clientPackage", clientPackage(summary, profile, steps, dining, liveState, guestCopy, review));
        payload.put("memoryPersistence", accessibilityJourneyMemoryService.persistJourney(payload));
        payload.put("venueProfile", venueProfileSummary(venueProfile));
        payload.put("runtime", Map.of("provider", "deterministic_accessibility_planner_spring", "backend", "java_spring", "liveParkState", true, "llmControlAuthority", false));
        return payload;
    }

    public Map<String, Object> tools() {
        Map<String, Object> payload = orderedMap();
        payload.put("status", "ready");
        payload.put("mode", "accessibility_journey_llm_tools_spring");
        payload.put("runtime", "java_spring");
        payload.put("plannerAuthority", "deterministic_spring_constraint_filter");
        payload.put("llmControlAuthority", false);
        payload.put("tools", llmToolManifest());
        return payload;
    }

    public Map<String, Object> tool(Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mapValue(body);
        String name = string(firstNonBlank(request.get("toolName"), request.get("name")), "");
        Map<String, Object> arguments = mapValue(firstNonBlank(request.get("arguments"), request.get("input")));
        return switch (name) {
            case "accessibility.normalize_intake" -> Map.of(
                "status", "ok",
                "toolName", name,
                "result", profileFromPayload(arguments),
                "llmControlsRoute", false
            );
            case "accessibility.list_start_locations" -> Map.of(
                "status", "ok",
                "toolName", name,
                "result", startLocationOptions(venueProfileService.profile()),
                "llmControlsRoute", false
            );
            case "accessibility.build_journey" -> Map.of(
                "status", "ok",
                "toolName", name,
                "result", journey(arguments),
                "llmControlsRoute", false
            );
            case "accessibility.record_feedback" -> Map.of(
                "status", "ok",
                "toolName", name,
                "result", recordFeedback(arguments),
                "llmControlsRoute", false
            );
            default -> Map.of(
                "status", "invalid",
                "mode", "accessibility_journey_llm_tool_spring",
                "runtime", "java_spring",
                "toolName", name,
                "readiness_issues", List.of("Unknown Accessibility Journey tool."),
                "allowedTools", llmToolManifest().stream().map(tool -> tool.get("name")).toList()
            );
        };
    }

    public Map<String, Object> memory(int limit) {
        return accessibilityJourneyMemoryService.memory(limit);
    }

    public Map<String, Object> recordFeedback(Map<String, Object> body) {
        return accessibilityJourneyMemoryService.recordFeedback(body);
    }

    private Map<String, Object> blockedJourney(Map<String, Object> profile, Map<String, Object> venueProfile) {
        Map<String, Object> payload = orderedMap();
        payload.put("status", "blocked");
        payload.put("mode", "accessible_journey_builder_spring");
        payload.put("version", VERSION);
        payload.put("springRuntime", "java_spring");
        payload.put("summary", Map.of(
            "headline", "Accessibility Journey needs an active Venue Profile before it can build guest routes.",
            "durationMinutes", profile.get("durationMinutes"),
            "needs", profile.get("needs"),
            "confidence", 0,
            "requiresHumanReview", true,
            "reviewReason", "Venue Profile is not ready."
        ));
        payload.put("profile", profile);
        payload.put("planSteps", List.of());
        payload.put("diningOptions", List.of());
        payload.put("attractionOptions", List.of());
        payload.put("breakPlan", Map.of("cadenceMinutes", 0, "plannedBreakCount", 0, "preferredBreaks", List.of()));
        payload.put("staffHandoff", Map.of("recommended", true, "owner", "Venue Profile owner", "message", "Connect a studio-ready Venue Profile with accessibility, safety, location, and channel-owner data."));
        payload.put("guardrails", COPY_RULES);
        payload.put("evidence", List.of(Map.of("id", "venue_profile_blocked", "source", "venue_profile", "label", "Venue Profile readiness", "detail", "Accessibility Journey does not use local seed accessibility facts.")));
        payload.put("venueProfile", venueProfileSummary(venueProfile));
        payload.put("readinessIssues", listValue(mapValue(venueProfile.get("readiness")).get("issues")));
        payload.put("runtime", Map.of("provider", "deterministic_accessibility_planner_spring", "backend", "java_spring", "liveParkState", false, "llmControlAuthority", false));
        return payload;
    }

    private Map<String, Object> currentParkState(Map<String, Object> requestBody) {
        Map<String, Object> supplied = mapValue(firstNonBlank(requestBody.get("parkState"), requestBody.get("state")));
        if (!supplied.isEmpty()) {
            return supplied;
        }
        return parkStateProjectionService.state("accessibility_journey_live_state");
    }

    private Map<String, Object> profileFromPayload(Map<String, Object> payload) {
        String request = String.join(" ", List.of(
            string(payload.get("request"), ""),
            string(payload.get("prompt"), ""),
            string(payload.get("party"), ""),
            string(payload.get("notes"), ""),
            listValue(payload.get("needs")).stream().map(String::valueOf).reduce("", (left, right) -> left + " " + right),
            allergiesText(payload.get("allergies"))
        )).trim();
        String lowered = request.toLowerCase(Locale.ROOT);
        LinkedHashSet<String> needs = new LinkedHashSet<>();
        for (Object need : listValue(payload.get("needs"))) {
            if (hasText(need)) {
                needs.add(string(need, ""));
            }
        }
        for (Map<String, Object> supported : SUPPORTED_NEEDS) {
            String id = string(supported.get("id"), "");
            for (Object keyword : listValue(supported.get("keywords"))) {
                if (lowered.contains(string(keyword, "").toLowerCase(Locale.ROOT))) {
                    needs.add(id);
                    break;
                }
            }
        }
        List<String> allergies = allergens(payload.get("allergies"), lowered);
        if (!allergies.isEmpty()) {
            needs.add("allergy");
        }
        if (needs.isEmpty()) {
            needs.add("family_care");
        }
        Map<String, Object> profile = orderedMap();
        profile.put("request", request.isBlank() ? "Create an accessible park route." : request);
        profile.put("needs", needs.stream().sorted().toList());
        profile.put("guestSegmentId", guestSegmentId(needs, allergies, lowered));
        profile.put("allergies", allergies);
        profile.put("durationMinutes", Math.max(45, Math.min(360, intValue(firstNonBlank(payload.get("durationMinutes"), payload.get("duration_minutes")), 180))));
        profile.put("currentLocation", string(firstNonBlank(payload.get("currentLocation"), payload.get("current_location")), "Entrance Plaza"));
        profile.put("avoidStairs", truthy(payload.get("avoidStairs")) || lowered.contains("stairs") || lowered.contains("step free") || lowered.contains("wheelchair"));
        profile.put("needsIndoorBreaks", truthy(payload.get("indoorBreaks")) || lowered.contains("indoor") || lowered.contains("heat") || lowered.contains("break"));
        profile.put("nearRestrooms", truthy(payload.get("nearRestrooms")) || lowered.contains("restroom") || lowered.contains("bathroom"));
        profile.put("avoidLoudShows", truthy(payload.get("avoidLoudShows")) || lowered.contains("no loud") || lowered.contains("loud shows") || lowered.contains("low sensory"));
        profile.put("minimalWalking", truthy(payload.get("minimalWalking")) || lowered.contains("minimal walking") || lowered.contains("short walk") || lowered.contains("elderly"));
        return profile;
    }

    private List<Map<String, Object>> catalogLocations(Map<String, Object> venueProfile) {
        Map<String, Object> realInputs = mapValue(venueProfile.get("realInputs"));
        Map<String, Object> details = mapValue(realInputs.get("locationDetails"));
        List<Map<String, Object>> locations = new ArrayList<>();
        for (Object value : details.values()) {
            Map<String, Object> row = mapValue(value);
            if (!hasText(row.get("name"))) {
                continue;
            }
            boolean indoor = truthy(row.get("indoor"));
            boolean covered = truthy(row.get("covered")) || string(row.get("seating"), "").toLowerCase(Locale.ROOT).contains("covered");
            String kind = string(row.get("kind"), "location");
            String sensory = string(row.get("sensoryNote"), "");
            String accessibility = string(row.get("accessibilityNote"), "");
            int quietScore = 58 + (indoor ? 12 : 0) + (covered ? 8 : 0) + (kind.contains("family") ? 12 : 0) + (accessibility.isBlank() ? 0 : 8);
            if ((sensory + " " + row.getOrDefault("category", "") + " " + row.getOrDefault("thrillLevel", "")).toLowerCase(Locale.ROOT).matches(".*(loud|launch|drop|thrill|flashing|heights).*")) {
                quietScore -= 24;
            }
            Map<String, Object> location = orderedMap();
            location.put("id", locationId(string(row.get("name"), "")));
            location.put("name", row.get("name"));
            location.put("kind", kind);
            location.put("zoneId", string(row.get("zoneId"), locationId(string(row.get("name"), ""))));
            location.put("indoor", indoor);
            location.put("covered", covered);
            location.put("quietScore", Math.max(20, Math.min(95, quietScore)));
            location.put("stepFree", !accessibility.isBlank() || !Set.of("attraction", "show").contains(kind));
            location.put("strollerFriendly", !Set.of("thrill_zone").contains(kind));
            location.put("accessibilityNote", accessibility);
            location.put("sensoryNote", sensory);
            location.put("dietaryTags", listValue(row.get("dietaryTags")));
            location.put("cuisine", row.get("cuisine"));
            location.put("seating", row.get("seating"));
            location.put("durationMinutes", row.get("durationMinutes"));
            location.put("heightRequirementInches", row.get("heightRequirementInches"));
            location.put("category", row.get("category"));
            location.put("thrillLevel", row.get("thrillLevel"));
            location.put("restrooms", List.of());
            location.put("breakFeatures", breakFeatures(kind, indoor, covered, Boolean.TRUE.equals(location.get("stepFree"))));
            locations.add(location);
        }
        return locations;
    }

    private List<Map<String, Object>> scoreLocations(Map<String, Object> profile, List<Map<String, Object>> locations, Map<String, Object> parkState) {
        Map<String, Map<String, Object>> liveZones = liveIndex(listValue(mapValue(parkState.get("guestFlow")).get("zones")));
        Map<String, Object> weather = mapValue(parkState.get("weather"));
        Map<String, Object> readiness = mapValue(parkState.get("incidentReadiness"));
        int stormRisk = intValue(weather.get("stormRisk"), 0);
        int heatIndex = intValue(weather.get("heatIndexF"), intValue(weather.get("temperatureF"), 80));
        boolean routesOpen = !Boolean.FALSE.equals(readiness.get("accessibilityRoutesOpen"));
        List<Map<String, Object>> scored = new ArrayList<>();
        for (Map<String, Object> location : locations) {
            Map<String, Object> liveZone = liveZones.getOrDefault(normalizeKey(location.get("zoneId")), orderedMap());
            int density = intValue(liveZone.get("density"), 50);
            int waitMins = intValue(liveZone.get("waitMins"), 10);
            int comfortScore = intValue(liveZone.get("comfortScore"), 75);
            int score = intValue(location.get("quietScore"), 55)
                + (Boolean.TRUE.equals(location.get("indoor")) ? 18 : 0)
                + (Boolean.TRUE.equals(location.get("covered")) ? 10 : 0)
                + Math.max(-30, Math.min(18, comfortScore - 70))
                - Math.max(0, density - 55) / 2
                - Math.max(0, waitMins - 12) / 2;
            if (listValue(profile.get("needs")).contains("low_sensory")) {
                score += intValue(location.get("quietScore"), 55) / 3;
            }
            if (Boolean.TRUE.equals(profile.get("avoidStairs")) && !Boolean.TRUE.equals(location.get("stepFree"))) {
                score -= 80;
            }
            if (!routesOpen && Boolean.TRUE.equals(profile.get("avoidStairs"))) {
                score -= 18;
            }
            if ((stormRisk >= 55 || heatIndex >= 95) && !Boolean.TRUE.equals(location.get("indoor")) && !Boolean.TRUE.equals(location.get("covered"))) {
                score -= 32;
            }
            if (Boolean.TRUE.equals(profile.get("nearRestrooms"))) {
                score += listValue(location.get("restrooms")).isEmpty() ? -8 : 12;
            }
            Map<String, Object> row = orderedMap();
            row.putAll(location);
            row.put("score", score);
            row.put("density", density);
            row.put("waitMins", waitMins);
            row.put("comfortScore", comfortScore);
            row.put("liveStatus", string(liveZone.get("status"), "unknown"));
            row.put("sensoryNotes", sensoryNotes(location));
            scored.add(row);
        }
        scored.sort((left, right) -> Integer.compare(intValue(right.get("score"), 0), intValue(left.get("score"), 0)));
        return scored;
    }

    private List<Map<String, Object>> diningOptions(Map<String, Object> profile, List<Map<String, Object>> scored, Map<String, Object> parkState) {
        List<String> allergies = listValue(profile.get("allergies")).stream().map(String::valueOf).toList();
        Map<String, Map<String, Object>> liveFood = liveFoodIndex(parkState);
        List<Map<String, Object>> options = new ArrayList<>();
        for (Map<String, Object> row : scored) {
            if (!"food".equals(row.get("kind"))) {
                continue;
            }
            Map<String, Object> foodState = firstNonEmpty(
                liveFood.get(normalizeKey(row.get("name"))),
                liveFood.get(normalizeKey(row.get("zoneId")))
            );
            List<String> handled = listValue(row.get("dietaryTags")).stream().map(value -> string(value, "").toLowerCase(Locale.ROOT).replace(" option", "").replace(" available", "")).toList();
            if (!allergies.isEmpty() && !handled.isEmpty() && !new LinkedHashSet<>(handled).containsAll(allergies)) {
                continue;
            }
            int pickupEta = intValue(foodState.get("pickupEtaMinutes"), 15);
            int backlog = intValue(foodState.get("mobileOrderBacklog"), 30);
            Map<String, Object> option = orderedMap();
            option.put("id", string(row.get("id"), "dining"));
            option.put("name", row.get("name"));
            option.put("zoneId", row.get("zoneId"));
            option.put("score", intValue(row.get("score"), 60) - 15 - Math.max(0, pickupEta - 15) - Math.max(0, backlog - 25) / 3);
            option.put("pickupEtaMinutes", pickupEta);
            option.put("mobileOrderBacklog", backlog);
            option.put("availableItems", listValue(foodState.get("availableItems")));
            option.put("allergyProtocols", listValue(foodState.get("allergenProtocols")).isEmpty() ? List.of("trained staff confirmation", "ingredient and cross-contact check") : listValue(foodState.get("allergenProtocols")));
            option.put("allergensHandled", handled);
            option.put("lowCrowdSeating", string(row.get("seating"), "").toLowerCase(Locale.ROOT).contains("covered") || string(row.get("seating"), "").toLowerCase(Locale.ROOT).contains("side"));
            option.put("nearbyRestrooms", row.get("restrooms"));
            option.put("cautions", List.of("Confirm ingredients and cross-contact process with trained restaurant staff before ordering."));
            option.put("staffConfirmationRequired", !allergies.isEmpty());
            options.add(option);
        }
        options.sort((left, right) -> Integer.compare(intValue(right.get("score"), 0), intValue(left.get("score"), 0)));
        return options.stream().limit(4).toList();
    }

    private List<Map<String, Object>> attractionOptions(Map<String, Object> profile, List<Map<String, Object>> scored, Map<String, Object> parkState) {
        Map<String, Map<String, Object>> liveRides = liveIndex(listValue(mapValue(parkState.get("guestFlow")).get("rides")));
        List<Map<String, Object>> options = new ArrayList<>();
        for (Map<String, Object> row : scored) {
            if (!Set.of("attraction", "show").contains(string(row.get("kind"), ""))) {
                continue;
            }
            Map<String, Object> rideState = firstNonEmpty(
                liveRides.get(normalizeKey(row.get("name"))),
                liveRides.get(normalizeKey(row.get("id")))
            );
            String status = string(rideState.get("status"), "profile_only");
            if (Set.of("closed", "down", "paused", "unavailable").contains(status.toLowerCase(Locale.ROOT))) {
                continue;
            }
            String sensoryLoad = sensoryLoad(row);
            if (Boolean.TRUE.equals(profile.get("avoidLoudShows")) && "high".equals(sensoryLoad)) {
                continue;
            }
            if (Boolean.TRUE.equals(profile.get("avoidStairs")) && !Boolean.TRUE.equals(row.get("stepFree"))) {
                continue;
            }
            Map<String, Object> option = orderedMap();
            option.put("id", string(row.get("id"), "activity"));
            option.put("name", row.get("name"));
            option.put("zoneId", row.get("zoneId"));
            option.put("zoneName", row.get("name"));
            option.put("score", intValue(row.get("score"), 50) - 10 - Math.max(0, intValue(rideState.get("waitMins"), 20) - 20) / 2);
            option.put("waitMins", intValue(rideState.get("waitMins"), 20));
            option.put("status", status);
            option.put("sensoryLoad", sensoryLoad);
            option.put("stepFreeQueue", row.get("stepFree"));
            option.put("transferRequired", hasText(row.get("heightRequirementInches")) || string(row.get("accessibilityNote"), "").toLowerCase(Locale.ROOT).contains("transfer"));
            option.put("indoor", row.get("indoor"));
            option.put("cautions", sensoryNotes(row));
            options.add(option);
        }
        if (listValue(profile.get("needs")).contains("low_sensory") && !scored.isEmpty()) {
            Map<String, Object> quiet = scored.get(0);
            Map<String, Object> quietActivity = orderedMap();
            quietActivity.put("id", "profile_quiet_activity");
            quietActivity.put("name", string(quiet.get("name"), "Quiet area") + " reset activity");
            quietActivity.put("zoneId", quiet.get("zoneId"));
            quietActivity.put("zoneName", quiet.get("name"));
            quietActivity.put("score", intValue(quiet.get("score"), 70) + 10);
            quietActivity.put("waitMins", intValue(quiet.get("waitMins"), 10));
            quietActivity.put("status", quiet.get("liveStatus"));
            quietActivity.put("sensoryLoad", "low");
            quietActivity.put("stepFreeQueue", true);
            quietActivity.put("transferRequired", false);
            quietActivity.put("indoor", quiet.get("indoor"));
            quietActivity.put("cautions", sensoryNotes(quiet));
            options.add(quietActivity);
        }
        options.sort((left, right) -> Integer.compare(intValue(right.get("score"), 0), intValue(left.get("score"), 0)));
        return options.stream().limit(4).toList();
    }

    private List<Map<String, Object>> planSteps(Map<String, Object> profile, List<Map<String, Object>> scored, List<Map<String, Object>> dining, List<Map<String, Object>> attractions, List<Map<String, Object>> certifiedPaths, Map<String, Object> parkState) {
        if (scored.isEmpty()) {
            return List.of();
        }
        List<Map<String, Object>> steps = new ArrayList<>();
        Map<String, Object> start = resolveStartLocation(profile, scored);
        String startZoneId = string(start.get("zoneId"), "");
        List<Map<String, Object>> routeScored = routeFitRows(scored, startZoneId, certifiedPaths);
        List<Map<String, Object>> routeAttractions = routeFitRows(attractions, startZoneId, certifiedPaths);
        List<Map<String, Object>> routeDining = routeFitRows(dining, startZoneId, certifiedPaths);
        Map<String, Object> firstBreak = firstIndoor(routeScored);
        steps.add(startStep(start, parkState));
        if (!routeAttractions.isEmpty()) {
            Map<String, Object> activity = routeAttractions.get(0);
            steps.add(activityStep(activity, string(steps.get(steps.size() - 1).get("zoneId"), ""), certifiedPaths, parkState));
        }
        if (Boolean.TRUE.equals(profile.get("needsIndoorBreaks")) || listValue(profile.get("needs")).contains("low_sensory") || intValue(profile.get("durationMinutes"), 180) >= 120) {
            steps.add(zoneStep("break_1", "Indoor decompression break", firstBreak, 25, "Adds a planned reset before fatigue, heat, or sensory load accumulates.", string(steps.get(steps.size() - 1).get("zoneId"), ""), certifiedPaths, parkState));
        }
        if (!routeDining.isEmpty() && (listValue(profile.get("needs")).contains("allergy") || intValue(profile.get("durationMinutes"), 180) >= 150)) {
            steps.add(diningStep(routeDining.get(0), string(steps.get(steps.size() - 1).get("zoneId"), ""), certifiedPaths, parkState));
        }
        steps.add(zoneStep("finish", "Finish near a flexible exit point", routeScored.get(0), 20, "Ends near a calmer stop and easier staff handoff if the group needs to change plans.", string(steps.get(steps.size() - 1).get("zoneId"), ""), certifiedPaths, parkState));
        return steps.stream().limit(5).toList();
    }

    private Map<String, Object> startStep(Map<String, Object> start, Map<String, Object> parkState) {
        Map<String, Object> step = orderedMap();
        step.put("id", "step_start");
        step.put("type", "start_location");
        step.put("title", "Start from selected location");
        step.put("location", start.get("name"));
        step.put("zoneId", start.get("zoneId"));
        step.put("durationMinutes", 8);
        step.put("walkMinutes", 0);
        step.put("why", "Anchors the route to the selected guest start point before scoring nearby low-risk stops.");
        step.put("accessibility", List.of(Boolean.TRUE.equals(start.get("stepFree")) ? "step-free start" : "staff confirmation needed for start access", Boolean.TRUE.equals(start.get("indoor")) ? "indoor" : "covered/outdoor"));
        step.put("nearby", listValue(start.get("breakFeatures")));
        step.put("risks", routeRisks("", string(start.get("zoneId"), ""), List.of(), parkState, sensoryNotes(start)));
        step.put("evidenceIds", List.of("selected_start_location", "venue_profile_accessibility_metadata"));
        return step;
    }

    private Map<String, Object> zoneStep(String id, String title, Map<String, Object> zone, int duration, String why, String previousZoneId, List<Map<String, Object>> certifiedPaths, Map<String, Object> parkState) {
        String zoneId = string(zone.get("zoneId"), "");
        int walk = walkMinutes(previousZoneId, zoneId, certifiedPaths, intValue(zone.get("score"), 0) >= 100 ? 4 : 7);
        Map<String, Object> step = orderedMap();
        step.put("id", "step_" + id);
        step.put("type", "break_or_route");
        step.put("title", title);
        step.put("location", zone.get("name"));
        step.put("zoneId", zoneId);
        step.put("durationMinutes", duration);
        step.put("walkMinutes", walk);
        step.put("why", why);
        step.put("accessibility", List.of(Boolean.TRUE.equals(zone.get("stepFree")) ? "step-free route" : "staff confirmation needed for route", Boolean.TRUE.equals(zone.get("indoor")) ? "indoor" : "covered/outdoor", Boolean.TRUE.equals(zone.get("strollerFriendly")) ? "stroller-friendly" : "stroller caution"));
        step.put("nearby", listValue(zone.get("breakFeatures")));
        step.put("risks", routeRisks(previousZoneId, zoneId, certifiedPaths, parkState, sensoryNotes(zone)));
        step.put("evidenceIds", List.of("venue_profile_accessibility_metadata", "profile_intelligence_route_policy"));
        return step;
    }

    private Map<String, Object> activityStep(Map<String, Object> attraction, String previousZoneId, List<Map<String, Object>> certifiedPaths, Map<String, Object> parkState) {
        String zoneId = string(attraction.get("zoneId"), "");
        Map<String, Object> step = orderedMap();
        step.put("id", "step_attraction_1");
        step.put("type", "attraction_or_activity");
        step.put("title", attraction.get("name"));
        step.put("location", string(attraction.get("zoneName"), string(attraction.get("name"), "")));
        step.put("zoneId", zoneId);
        step.put("durationMinutes", Math.max(20, Math.min(45, intValue(attraction.get("waitMins"), 20) + 15)));
        step.put("walkMinutes", walkMinutes(previousZoneId, zoneId, certifiedPaths, 7));
        step.put("why", "Selected after filtering loud/high-stimulation options, stairs, and profile risk.");
        step.put("accessibility", List.of(Boolean.TRUE.equals(attraction.get("stepFreeQueue")) ? "step-free queue" : "staff confirmation needed for queue access", Boolean.TRUE.equals(attraction.get("transferRequired")) ? "transfer required" : "no ride transfer expected for this activity", "sensory load: " + attraction.get("sensoryLoad")));
        step.put("nearby", List.of());
        step.put("risks", routeRisks(previousZoneId, zoneId, certifiedPaths, parkState, listValue(attraction.get("cautions"))));
        step.put("evidenceIds", List.of("venue_profile_accessibility_metadata", "profile_intelligence_route_policy"));
        return step;
    }

    private Map<String, Object> diningStep(Map<String, Object> dining, String previousZoneId, List<Map<String, Object>> certifiedPaths, Map<String, Object> parkState) {
        String zoneId = string(dining.get("zoneId"), "");
        Map<String, Object> step = orderedMap();
        step.put("id", "step_food_1");
        step.put("type", "dining");
        step.put("title", dining.get("name"));
        step.put("location", dining.get("name"));
        step.put("zoneId", zoneId);
        step.put("durationMinutes", Math.max(25, Math.min(50, intValue(dining.get("pickupEtaMinutes"), 15) + 18)));
        step.put("walkMinutes", walkMinutes(previousZoneId, zoneId, certifiedPaths, 6));
        step.put("why", "Best available dining match for allergy metadata, calmer seating, and route fit.");
        step.put("accessibility", List.of(Boolean.TRUE.equals(dining.get("staffConfirmationRequired")) ? "staff allergy confirmation required" : "standard dining confirmation", Boolean.TRUE.equals(dining.get("lowCrowdSeating")) ? "low-crowd seating nearby" : "seating may be crowded", "pickup estimate: " + dining.get("pickupEtaMinutes") + " minutes"));
        step.put("nearby", listValue(dining.get("nearbyRestrooms")));
        step.put("risks", routeRisks(previousZoneId, zoneId, certifiedPaths, parkState, listValue(dining.get("cautions"))));
        step.put("evidenceIds", List.of("food_live", "venue_profile_accessibility_metadata", "profile_intelligence_module_policy"));
        return step;
    }

    private Map<String, Object> breakPlan(Map<String, Object> profile, List<Map<String, Object>> steps) {
        int cadence = listValue(profile.get("needs")).contains("low_sensory") ? 35 : Boolean.TRUE.equals(profile.get("needsIndoorBreaks")) ? 45 : 60;
        List<Map<String, Object>> breaks = steps.stream()
            .filter(step -> "break_or_route".equals(step.get("type")))
            .map(step -> Map.of("title", step.get("title"), "location", step.get("location"), "durationMinutes", step.get("durationMinutes")))
            .toList();
        return Map.of("cadenceMinutes", cadence, "plannedBreakCount", breaks.size(), "preferredBreaks", breaks);
    }

    private Map<String, Object> clientPackage(
        Map<String, Object> summary,
        Map<String, Object> profile,
        List<Map<String, Object>> steps,
        List<Map<String, Object>> dining,
        Map<String, Object> liveState,
        Map<String, Object> guestCopy,
        boolean review
    ) {
        Map<String, Object> packagePayload = orderedMap();
        packagePayload.put("status", "client_ready");
        packagePayload.put("audience", "guest_care_or_client_demo");
        packagePayload.put("title", summary.get("headline"));
        packagePayload.put("subtitle", "A staff-gated accessible route plan built from the active Venue Profile and current park state.");
        packagePayload.put("routeSummary", string(guestCopy.get("message"), string(summary.get("headline"), "Accessible route plan.")));
        packagePayload.put("startLocation", profile.get("currentLocation"));
        packagePayload.put("durationMinutes", summary.get("durationMinutes"));
        packagePayload.put("confidenceLabel", intValue(summary.get("confidence"), 0) >= 75 ? "High" : intValue(summary.get("confidence"), 0) >= 55 ? "Medium" : "Needs review");
        packagePayload.put("requiresStaffReview", review);
        packagePayload.put("reviewReason", summary.get("reviewReason"));
        packagePayload.put("itinerary", clientItinerary(steps));
        packagePayload.put("confirmationChecklist", clientConfirmationChecklist(profile, liveState, dining));
        packagePayload.put("liveContext", clientLiveContext(liveState));
        packagePayload.put("safeLanguage", guestCopy.get("safetyNote"));
        packagePayload.put("technicalProof", Map.of(
            "planner", "deterministic_spring_constraint_filter",
            "llmRole", "copy_and_intake_tools_only",
            "llmControlsRoute", false,
            "memoryTarget", "accessibility_journey_receipts"
        ));
        return packagePayload;
    }

    private List<Map<String, Object>> clientItinerary(List<Map<String, Object>> steps) {
        List<Map<String, Object>> itinerary = new ArrayList<>();
        for (int index = 0; index < steps.size(); index++) {
            Map<String, Object> step = steps.get(index);
            Map<String, Object> row = orderedMap();
            row.put("label", "Stop " + (index + 1));
            row.put("title", step.get("title"));
            row.put("location", step.get("location"));
            row.put("time", intValue(step.get("durationMinutes"), 0) + " min");
            row.put("walk", intValue(step.get("walkMinutes"), 0) + " min walk");
            row.put("reason", step.get("why"));
            row.put("accessibilitySummary", listValue(step.get("accessibility")).stream().map(String::valueOf).limit(3).toList());
            row.put("needsStaffConfirmation", !listValue(step.get("risks")).isEmpty());
            itinerary.add(row);
        }
        return itinerary;
    }

    private List<Map<String, Object>> clientConfirmationChecklist(Map<String, Object> profile, Map<String, Object> liveState, List<Map<String, Object>> dining) {
        List<Map<String, Object>> rows = new ArrayList<>();
        rows.add(clientChecklistRow("Route status", Boolean.TRUE.equals(mapValue(liveState.get("readiness")).get("accessibilityRoutesOpen")) ? "Ready" : "Confirm with staff", "Guest Services"));
        if (!listValue(profile.get("allergies")).isEmpty()) {
            rows.add(clientChecklistRow("Allergy handling", dining.isEmpty() ? "Staff confirmation required before ordering" : "Confirm ingredients and cross-contact", "Dining manager"));
        }
        if (listValue(profile.get("needs")).contains("medical")) {
            rows.add(clientChecklistRow("Medical support", "First Aid review recommended", "First Aid"));
        }
        rows.add(clientChecklistRow("Ride transfer or equipment", "Confirm before joining any queue", "Attraction team"));
        return rows;
    }

    private Map<String, Object> clientChecklistRow(String label, String status, String owner) {
        Map<String, Object> row = orderedMap();
        row.put("label", label);
        row.put("status", status);
        row.put("owner", owner);
        return row;
    }

    private Map<String, Object> clientLiveContext(Map<String, Object> liveState) {
        Map<String, Object> weather = mapValue(liveState.get("weather"));
        Map<String, Object> readiness = mapValue(liveState.get("readiness"));
        Map<String, Object> context = orderedMap();
        context.put("weather", string(weather.get("condition"), "unknown") + ", storm risk " + intValue(weather.get("stormRisk"), 0) + "%");
        context.put("heatIndexF", intValue(weather.get("heatIndexF"), 0));
        context.put("routesOpen", !Boolean.FALSE.equals(readiness.get("accessibilityRoutesOpen")));
        context.put("foodLocations", liveState.get("foodLocationCount"));
        return context;
    }

    private List<String> guardrails(Map<String, Object> profile, Map<String, Object> parkState) {
        List<String> rows = new ArrayList<>(COPY_RULES);
        Map<String, Object> weather = mapValue(parkState.get("weather"));
        Map<String, Object> readiness = mapValue(parkState.get("incidentReadiness"));
        if (!listValue(profile.get("allergies")).isEmpty()) {
            rows.add("Allergy result is a dining shortlist, not an allergen-free guarantee.");
        }
        if (listValue(profile.get("needs")).contains("medical")) {
            rows.add("Medical constraints should be handled by First Aid or trained staff if symptoms, medication, or urgent uncertainty are involved.");
        }
        if (intValue(weather.get("stormRisk"), 0) >= 55 || intValue(weather.get("heatIndexF"), 0) >= 95) {
            rows.add("Weather pressure is elevated; outdoor movement, shelter, and cooling claims require staff confirmation.");
        }
        if (Boolean.FALSE.equals(readiness.get("accessibilityRoutesOpen"))) {
            rows.add("Live accessibility route status is degraded; confirm route with staff before moving.");
        }
        return rows;
    }

    private Map<String, Object> staffHandoff(Map<String, Object> profile, boolean review) {
        if (!review) {
            return Map.of("recommended", false, "owner", "Guest Services", "message", "No immediate staff handoff required for this plan, but Guest Services can adjust it.");
        }
        if (!listValue(profile.get("allergies")).isEmpty()) {
            return Map.of("recommended", true, "owner", "Dining manager or allergy-trained staff", "message", "Ask staff to confirm ingredients, cross-contact process, and safe ordering before purchasing food.");
        }
        if (listValue(profile.get("needs")).contains("medical")) {
            return Map.of("recommended", true, "owner", "First Aid", "message", "Use First Aid or trained staff for medical constraints, symptoms, medication storage, or urgent uncertainty.");
        }
        return Map.of("recommended", true, "owner", "Accessibility Lead", "message", "Confirm route availability and any equipment or assistance needs before starting.");
    }

    private List<Map<String, Object>> evidence(Map<String, Object> venueProfile, List<Map<String, Object>> locations, List<Map<String, Object>> dining, List<Map<String, Object>> attractions, Map<String, Object> parkState) {
        Map<String, Object> identity = mapValue(venueProfile.get("venueIdentity"));
        return List.of(
            Map.of("id", "venue_profile_accessibility_metadata", "source", "venue_profile.realInputs.locationDetails", "label", "Venue Profile accessibility metadata", "detail", string(identity.get("name"), "Active venue") + " supplied " + locations.size() + " profile locations and " + dining.size() + " dining candidates."),
            Map.of("id", "profile_intelligence_route_policy", "source", "venue_profile.realInputs.profileIntelligence", "label", "Profile intelligence route policy", "detail", "Route, allergy, medical, transfer, and accommodation claims are bounded by module-specific review rules."),
            Map.of("id", "live_park_state", "source", "spring_state_projection.guestFlow/weather/foodInventory/incidentReadiness", "label", "Live park state", "detail", liveEvidenceDetail(parkState)),
            Map.of("id", "activity_filter", "source", "venue_profile.locationDetails + guestFlow.rides", "label", "Activity filtering", "detail", attractions.size() + " activity options remained after mobility, sensory, wait, and availability filtering.")
        );
    }

    private Map<String, Object> intelligenceReceipt(Map<String, Object> profile, Map<String, Object> venueProfile, List<Map<String, Object>> steps, List<Map<String, Object>> certifiedPaths) {
        Map<String, Object> intelligence = mapValue(mapValue(venueProfile.get("realInputs")).get("profileIntelligence"));
        Map<String, Object> policy = mapValue(mapValue(intelligence.get("modulePolicy")).get("accessibility_journey"));
        return Map.of(
            "source", string(intelligence.get("source"), "venue_profile_spring"),
            "guestSegmentId", profile.get("guestSegmentId"),
            "segmentNeeds", Map.of("preferredPace", "slow", "avoid", List.of("dense queues", "long exposed walks"), "requiredHandoff", listValue(profile.get("allergies")).isEmpty() ? List.of() : List.of("dining_staff_confirmation")),
            "usedPathRecords", usedPathRecords(steps, certifiedPaths),
            "qualityGaps", listValue(intelligence.get("qualityGaps")),
            "modulePolicy", Map.of(
                "mayRecommend", listValue(policy.get("mayRecommend")),
                "mustReview", listValue(policy.get("mustReview")),
                "neverClaim", policy.isEmpty() ? List.of("ADA certification", "allergen-free food") : listValue(policy.get("neverClaim"))
            )
        );
    }

    private Map<String, Object> learningReceipt(Map<String, Object> profile, List<Map<String, Object>> steps, boolean review, Map<String, Object> parkState) {
        Map<String, Object> weather = mapValue(parkState.get("weather"));
        return Map.of(
            "schemaVersion", "venue_profile_learning_schema_v1",
            "scenarioTaxonomy", "accessibility_journey",
            "observation", Map.of(
                "guestSegmentId", profile.get("guestSegmentId"),
                "startLocation", profile.get("currentLocation"),
                "startZoneId", steps.isEmpty() ? "" : steps.get(0).get("zoneId"),
                "needs", profile.get("needs"),
                "routeZoneIds", steps.stream().map(step -> step.get("zoneId")).filter(this::hasText).toList(),
                "staffHandoffRecommended", review,
                "qualityGapCount", 0,
                "weatherCondition", string(weather.get("condition"), "unknown"),
                "stormRisk", intValue(weather.get("stormRisk"), 0)
            ),
            "eligibleFeedbackLabels", List.of("guest_completed_route", "edited_route", "rerouted_for_accessibility", "allergy_staff_confirmed"),
            "privacyBoundary", "No medical diagnosis, disability identity, protected class, or private guest identifier is captured."
        );
    }

    private Map<String, Object> venueProfileSummary(Map<String, Object> venueProfile) {
        Map<String, Object> readiness = mapValue(venueProfile.get("readiness"));
        Map<String, Object> summary = orderedMap();
        summary.put("venueIdentity", venueProfile.get("venueIdentity"));
        summary.put("status", readiness.get("status"));
        summary.put("counts", mapValue(readiness.get("counts")));
        summary.put("issues", listValue(readiness.get("issues")));
        Map<String, Object> readinessSummary = orderedMap();
        readinessSummary.put("status", readiness.get("status"));
        readinessSummary.put("autofillAllowed", readiness.get("autofillAllowed"));
        readinessSummary.put("counts", mapValue(readiness.get("counts")));
        readinessSummary.put("issues", listValue(readiness.get("issues")));
        readinessSummary.put("loadedFrom", readiness.get("loadedFrom"));
        summary.put("readiness", readinessSummary);
        summary.put("sourceIntegrity", mapValue(venueProfile.get("sourceIntegrity")));
        summary.put("source", mapValue(venueProfile.get("realInputs")).get("source"));
        return summary;
    }

    private List<Map<String, Object>> startLocationOptions(Map<String, Object> venueProfile) {
        List<Map<String, Object>> options = new ArrayList<>();
        for (Map<String, Object> location : catalogLocations(venueProfile)) {
            Map<String, Object> option = orderedMap();
            option.put("id", location.get("id"));
            option.put("name", location.get("name"));
            option.put("zoneId", location.get("zoneId"));
            option.put("kind", location.get("kind"));
            option.put("indoor", location.get("indoor"));
            option.put("covered", location.get("covered"));
            option.put("stepFree", location.get("stepFree"));
            options.add(option);
        }
        boolean hasEntrance = options.stream().anyMatch(option -> string(option.get("name"), "").equalsIgnoreCase("Entrance Plaza"));
        if (!hasEntrance) {
            Map<String, Object> entrance = orderedMap();
            entrance.put("id", "entrance-plaza");
            entrance.put("name", "Entrance Plaza");
            entrance.put("zoneId", "entrancePlaza");
            entrance.put("kind", "arrival");
            entrance.put("indoor", false);
            entrance.put("covered", true);
            entrance.put("stepFree", true);
            options.add(0, entrance);
        }
        return options.stream()
            .filter(option -> hasText(option.get("name")))
            .sorted((left, right) -> string(left.get("name"), "").compareToIgnoreCase(string(right.get("name"), "")))
            .limit(40)
            .toList();
    }

    private String headline(Map<String, Object> profile, List<Map<String, Object>> dining) {
        List<Object> needs = listValue(profile.get("needs"));
        int duration = intValue(profile.get("durationMinutes"), 180);
        if (needs.contains("allergy") && !dining.isEmpty()) {
            return duration + "-minute accessible route with allergy-aware dining at " + dining.get(0).get("name") + " and planned breaks.";
        }
        if (needs.contains("low_sensory")) {
            return duration + "-minute low-sensory route with indoor breaks, restroom proximity, and loud-show filtering.";
        }
        if (needs.contains("mobility")) {
            return duration + "-minute mobility-aware route using step-free stops and shorter walking segments.";
        }
        return duration + "-minute accessible family route with breaks, restrooms, and flexible exits.";
    }

    private int confidence(Map<String, Object> profile, List<Map<String, Object>> steps, List<Map<String, Object>> dining) {
        int confidence = steps.isEmpty() ? 55 : 82;
        if (listValue(profile.get("needs")).contains("allergy") && dining.isEmpty()) confidence -= 25;
        if (!listValue(profile.get("allergies")).isEmpty()) confidence -= 8;
        if (listValue(profile.get("needs")).contains("medical")) confidence -= 10;
        return Math.max(35, Math.min(92, confidence));
    }

    private boolean requiresHumanReview(Map<String, Object> profile, Map<String, Object> parkState) {
        Map<String, Object> readiness = mapValue(parkState.get("incidentReadiness"));
        return !listValue(profile.get("allergies")).isEmpty() || listValue(profile.get("needs")).contains("medical") || Boolean.FALSE.equals(readiness.get("accessibilityRoutesOpen"));
    }

    private String reviewReason(Map<String, Object> profile, Map<String, Object> parkState) {
        if (Boolean.FALSE.equals(mapValue(parkState.get("incidentReadiness")).get("accessibilityRoutesOpen"))) return "Accessibility route status needs staff confirmation.";
        if (!listValue(profile.get("allergies")).isEmpty()) return "Allergy handling must be confirmed by trained dining staff.";
        if (listValue(profile.get("needs")).contains("medical")) return "Medical constraints should be reviewed by First Aid or trained staff.";
        return "Staff review recommended.";
    }

    private Map<String, Object> firstIndoor(List<Map<String, Object>> scored) {
        return scored.stream().filter(row -> Boolean.TRUE.equals(row.get("indoor"))).findFirst().orElse(scored.get(0));
    }

    private Map<String, Object> resolveStartLocation(Map<String, Object> profile, List<Map<String, Object>> scored) {
        String requested = normalizeKey(profile.get("currentLocation"));
        if (!requested.isBlank()) {
            for (Map<String, Object> row : scored) {
                if (requested.equals(normalizeKey(row.get("name"))) || requested.equals(normalizeKey(row.get("id")))) {
                    return row;
                }
            }
            for (Map<String, Object> row : scored) {
                if (requested.equals(normalizeKey(row.get("zoneId")))) {
                    Map<String, Object> zoneStart = orderedMap();
                    zoneStart.putAll(row);
                    zoneStart.put("name", profile.get("currentLocation"));
                    zoneStart.put("kind", "selected_zone");
                    return zoneStart;
                }
            }
            for (Map<String, Object> row : scored) {
                String haystack = normalizeKey(string(row.get("name"), "") + " " + string(row.get("id"), "") + " " + string(row.get("zoneId"), ""));
                if (haystack.contains(requested) || requested.contains(normalizeKey(row.get("name")))) {
                    Map<String, Object> fuzzyStart = orderedMap();
                    fuzzyStart.putAll(row);
                    fuzzyStart.put("name", profile.get("currentLocation"));
                    fuzzyStart.put("kind", "selected_area");
                    return fuzzyStart;
                }
            }
        }
        Map<String, Object> fallback = orderedMap();
        fallback.put("id", "entrance-plaza");
        fallback.put("name", string(profile.get("currentLocation"), "Entrance Plaza"));
        fallback.put("zoneId", normalizeKey(profile.get("currentLocation")).isBlank() ? "entrancePlaza" : locationId(string(profile.get("currentLocation"), "Entrance Plaza")));
        fallback.put("kind", "arrival");
        fallback.put("indoor", false);
        fallback.put("covered", true);
        fallback.put("stepFree", true);
        fallback.put("strollerFriendly", true);
        fallback.put("breakFeatures", List.of("arrival", "staff handoff"));
        fallback.put("score", 70);
        fallback.put("sensoryNotes", List.of());
        return fallback;
    }

    private List<Map<String, Object>> routeFitRows(List<Map<String, Object>> rows, String anchorZoneId, List<Map<String, Object>> certifiedPaths) {
        List<Map<String, Object>> ranked = new ArrayList<>();
        for (Map<String, Object> row : rows) {
            Map<String, Object> copy = orderedMap();
            copy.putAll(row);
            int walk = walkMinutes(anchorZoneId, string(row.get("zoneId"), ""), certifiedPaths, 8);
            int baseScore = intValue(row.get("score"), intValue(row.get("quietScore"), 60));
            int routeFitScore = baseScore - Math.max(0, walk - 6) * 3;
            copy.put("routeFitScore", routeFitScore);
            copy.put("walkMinutesFromStart", walk);
            ranked.add(copy);
        }
        ranked.sort((left, right) -> Integer.compare(intValue(right.get("routeFitScore"), 0), intValue(left.get("routeFitScore"), 0)));
        return ranked;
    }

    private List<Map<String, Object>> certifiedPaths(Map<String, Object> venueProfile) {
        return listValue(mapValue(mapValue(venueProfile.get("realInputs")).get("profileIntelligence")).get("certifiedPaths")).stream()
            .map(this::mapValue)
            .filter(path -> hasText(path.get("fromZoneId")) && hasText(path.get("toZoneId")))
            .toList();
    }

    private int walkMinutes(String fromZoneId, String toZoneId, List<Map<String, Object>> certifiedPaths, int fallback) {
        if (!hasText(fromZoneId) || !hasText(toZoneId) || fromZoneId.equals(toZoneId)) {
            return Math.max(2, Math.min(12, fallback));
        }
        Map<String, Object> path = certifiedPath(fromZoneId, toZoneId, certifiedPaths);
        if (!path.isEmpty()) {
            return Math.max(2, Math.min(25, intValue(path.get("estimatedWalkMinutes"), fallback)));
        }
        return Math.max(2, Math.min(20, fallback));
    }

    private Map<String, Object> certifiedPath(String fromZoneId, String toZoneId, List<Map<String, Object>> certifiedPaths) {
        String from = normalizeKey(fromZoneId);
        String to = normalizeKey(toZoneId);
        for (Map<String, Object> path : certifiedPaths) {
            String pathFrom = normalizeKey(path.get("fromZoneId"));
            String pathTo = normalizeKey(path.get("toZoneId"));
            if ((from.equals(pathFrom) && to.equals(pathTo)) || (from.equals(pathTo) && to.equals(pathFrom))) {
                return path;
            }
        }
        return orderedMap();
    }

    private List<Object> routeRisks(String fromZoneId, String toZoneId, List<Map<String, Object>> certifiedPaths, Map<String, Object> parkState, List<Object> baseRisks) {
        List<Object> risks = new ArrayList<>(baseRisks);
        if (hasText(fromZoneId) && hasText(toZoneId) && !fromZoneId.equals(toZoneId) && certifiedPath(fromZoneId, toZoneId, certifiedPaths).isEmpty()) {
            risks.add("Walk segment is a planning estimate; no certified path record matched this pair.");
        }
        if (Boolean.FALSE.equals(mapValue(parkState.get("incidentReadiness")).get("accessibilityRoutesOpen"))) {
            risks.add("Accessibility route status needs staff confirmation.");
        }
        Map<String, Object> weather = mapValue(parkState.get("weather"));
        if (intValue(weather.get("stormRisk"), 0) >= 55) {
            risks.add("Storm risk may change covered-route availability.");
        }
        if (intValue(weather.get("heatIndexF"), 0) >= 95) {
            risks.add("Heat index requires cooling and hydration checks.");
        }
        return risks;
    }

    private List<Map<String, Object>> usedPathRecords(List<Map<String, Object>> steps, List<Map<String, Object>> certifiedPaths) {
        List<Map<String, Object>> records = new ArrayList<>();
        String previous = "";
        for (Map<String, Object> step : steps) {
            String zoneId = string(step.get("zoneId"), "");
            Map<String, Object> path = certifiedPath(previous, zoneId, certifiedPaths);
            if (!path.isEmpty()) {
                records.add(path);
            }
            previous = zoneId;
        }
        return records;
    }

    private Map<String, Object> liveStateReceipt(Map<String, Object> parkState) {
        Map<String, Object> guestFlow = mapValue(parkState.get("guestFlow"));
        Map<String, Object> weather = mapValue(parkState.get("weather"));
        Map<String, Object> readiness = mapValue(parkState.get("incidentReadiness"));
        return Map.of(
            "source", string(parkState.get("source_of_truth"), "spring_state_projection"),
            "updatedAt", string(parkState.get("updated_at"), "unknown"),
            "zoneCount", listValue(guestFlow.get("zones")).size(),
            "rideCount", listValue(guestFlow.get("rides")).size(),
            "foodLocationCount", listValue(mapValue(parkState.get("foodInventory")).get("locations")).size(),
            "weather", Map.of("condition", string(weather.get("condition"), "unknown"), "stormRisk", intValue(weather.get("stormRisk"), 0), "heatIndexF", intValue(weather.get("heatIndexF"), 0)),
            "readiness", Map.of("accessibilityRoutesOpen", !Boolean.FALSE.equals(readiness.get("accessibilityRoutesOpen")), "firstAidReady", !Boolean.FALSE.equals(readiness.get("firstAidReady")))
        );
    }

    private Map<String, Object> llmContract() {
        return Map.of(
            "llmRole", "plain_language_intake_and_explanation_only",
            "plannerAuthority", "deterministic_spring_constraint_filter",
            "allowedInputs", List.of("guest request text", "explicit needs", "Venue Profile public accessibility metadata", "live public park state"),
            "blockedInputs", List.of("diagnosis", "private disability identity", "private medical details", "unreviewed staff availability"),
            "mayGenerate", List.of("guest-facing explanation", "question prompts", "route summary copy"),
            "mustNotGenerate", PROHIBITED_CLAIMS,
            "availableTools", llmToolManifest().stream().map(tool -> tool.get("name")).toList(),
            "llmControlsRoute", false
        );
    }

    private List<Map<String, Object>> llmToolManifest() {
        return List.of(
            llmTool(
                "accessibility.normalize_intake",
                "Convert guest text and selected controls into a structured profile. Does not create a route.",
                List.of("request", "needs", "allergies", "durationMinutes", "currentLocation"),
                List.of("No diagnosis extraction", "No private identity capture")
            ),
            llmTool(
                "accessibility.list_start_locations",
                "Return venue-backed selectable start locations from the active Venue Profile.",
                List.of(),
                List.of("Public venue metadata only")
            ),
            llmTool(
                "accessibility.build_journey",
                "Build the deterministic accessibility route from structured input, Venue Profile facts, and live state.",
                List.of("request", "needs", "allergies", "durationMinutes", "currentLocation"),
                List.of("LLM cannot override safety guardrails", "Allergy and medical claims remain staff-gated")
            ),
            llmTool(
                "accessibility.record_feedback",
                "Record human-reviewed route outcome feedback for later aggregate learning.",
                List.of("memoryId", "feedbackLabel", "humanReviewed", "reviewer"),
                List.of("Aggregate route outcomes only", "No protected class or medical diagnosis")
            )
        );
    }

    private Map<String, Object> llmTool(String name, String description, List<String> requiredInputs, List<String> guardrails) {
        return Map.of(
            "name", name,
            "description", description,
            "requiredInputs", requiredInputs,
            "guardrails", guardrails,
            "plannerAuthority", "deterministic_spring_constraint_filter",
            "llmControlAuthority", false
        );
    }

    private List<String> breakFeatures(String kind, boolean indoor, boolean covered, boolean stepFree) {
        List<String> rows = new ArrayList<>();
        if (indoor) rows.add("indoor");
        if (covered) rows.add("covered");
        if (stepFree) rows.add("accessible public location");
        if (kind.contains("family")) rows.add("family care");
        if (kind.contains("food")) rows.add("seating");
        return rows;
    }

    private Map<String, Map<String, Object>> liveIndex(List<Object> rows) {
        Map<String, Map<String, Object>> index = new LinkedHashMap<>();
        for (Object item : rows) {
            Map<String, Object> row = mapValue(item);
            for (Object key : new Object[] { row.get("id"), row.get("name"), row.get("zoneId") }) {
                String normalized = normalizeKey(key);
                if (!normalized.isBlank()) {
                    index.put(normalized, row);
                }
            }
        }
        return index;
    }

    private Map<String, Map<String, Object>> liveFoodIndex(Map<String, Object> parkState) {
        Map<String, Map<String, Object>> index = new LinkedHashMap<>();
        for (Object item : listValue(mapValue(parkState.get("foodInventory")).get("locations"))) {
            Map<String, Object> row = mapValue(item);
            for (Object key : new Object[] { row.get("id"), row.get("name"), row.get("zoneId") }) {
                String normalized = normalizeKey(key);
                if (!normalized.isBlank()) {
                    index.put(normalized, row);
                }
            }
        }
        return index;
    }

    private Map<String, Object> firstNonEmpty(Map<String, Object> left, Map<String, Object> right) {
        return left != null && !left.isEmpty() ? left : right == null ? orderedMap() : right;
    }

    private String liveEvidenceDetail(Map<String, Object> parkState) {
        Map<String, Object> guestFlow = mapValue(parkState.get("guestFlow"));
        Map<String, Object> weather = mapValue(parkState.get("weather"));
        Map<String, Object> readiness = mapValue(parkState.get("incidentReadiness"));
        return listValue(guestFlow.get("zones")).size() + " live zones, "
            + listValue(guestFlow.get("rides")).size() + " ride rows, "
            + listValue(mapValue(parkState.get("foodInventory")).get("locations")).size() + " food rows, storm risk "
            + intValue(weather.get("stormRisk"), 0) + "%, accessibility routes open "
            + (!Boolean.FALSE.equals(readiness.get("accessibilityRoutesOpen"))) + ".";
    }

    private List<Object> sensoryNotes(Map<String, Object> location) {
        List<Object> notes = new ArrayList<>();
        if (hasText(location.get("sensoryNote"))) notes.add(location.get("sensoryNote"));
        if (hasText(location.get("accessibilityNote"))) notes.add(location.get("accessibilityNote"));
        return notes;
    }

    private String sensoryLoad(Map<String, Object> location) {
        String text = (string(location.get("sensoryNote"), "") + " " + string(location.get("category"), "") + " " + string(location.get("thrillLevel"), "")).toLowerCase(Locale.ROOT);
        if (text.matches(".*(loud|launch|drop|thrill|flashing|heights).*")) {
            return "high";
        }
        return Boolean.TRUE.equals(location.get("indoor")) || Boolean.TRUE.equals(location.get("covered")) ? "medium" : "medium";
    }

    private String locationId(String name) {
        String[] parts = name.replaceAll("[^A-Za-z0-9]", " ").trim().split("\\s+");
        if (parts.length == 0 || parts[0].isBlank()) return "venueLocation";
        StringBuilder builder = new StringBuilder(parts[0].substring(0, 1).toLowerCase(Locale.ROOT) + parts[0].substring(1));
        for (int index = 1; index < parts.length; index++) {
            builder.append(parts[index].substring(0, 1).toUpperCase(Locale.ROOT)).append(parts[index].substring(1));
        }
        return builder.toString();
    }

    private List<String> allergens(Object raw, String lowered) {
        LinkedHashSet<String> tokens = new LinkedHashSet<>();
        if (raw instanceof List<?> list) {
            for (Object item : list) if (hasText(item)) tokens.add(string(item, "").toLowerCase(Locale.ROOT));
        } else if (hasText(raw)) {
            for (String part : string(raw, "").replace("/", ",").split(",")) if (!part.isBlank()) tokens.add(part.trim().toLowerCase(Locale.ROOT));
        }
        for (String known : List.of("peanut", "tree nut", "dairy", "gluten", "soy", "egg", "shellfish")) {
            if (lowered.contains(known)) tokens.add(known);
        }
        if (lowered.contains("nut")) tokens.add("tree nut");
        return tokens.stream().sorted().toList();
    }

    private String allergiesText(Object value) {
        if (value instanceof List<?> list) {
            return list.stream().map(String::valueOf).reduce("", (left, right) -> left + " " + right);
        }
        return string(value, "");
    }

    private String guestSegmentId(LinkedHashSet<String> needs, List<String> allergies, String lowered) {
        if (!allergies.isEmpty() || needs.contains("allergy")) return "allergy_or_dietary_guests";
        if (needs.contains("low_sensory")) return "low_sensory_guests";
        if (lowered.contains("child") || lowered.contains("kid") || lowered.contains("stroller") || needs.contains("family_care")) return "families_with_strollers";
        if (lowered.contains("rain") || lowered.contains("storm")) return "rainy_day_parties";
        if (lowered.contains("thrill") || lowered.contains("coaster")) return "thrill_seekers";
        return "families_with_strollers";
    }

    private String normalizeKey(Object value) {
        return string(value, "").toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9]", "");
    }

    private Object firstNonBlank(Object left, Object right) {
        return hasText(left) ? left : right;
    }

    private static Map<String, Object> need(String id, String label, String description, List<String> keywords) {
        return Map.of("id", id, "label", label, "description", description, "keywords", keywords);
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
        if (value instanceof List<?> list) return new ArrayList<>(list);
        return List.of();
    }

    private String string(Object value, String defaultValue) {
        if (value == null) return defaultValue;
        String text = String.valueOf(value).trim();
        return text.isBlank() ? defaultValue : text;
    }

    private boolean hasText(Object value) {
        return value != null && !String.valueOf(value).trim().isBlank();
    }

    private boolean truthy(Object value) {
        if (value instanceof Boolean bool) return bool;
        if (value instanceof Number number) return number.doubleValue() != 0;
        return List.of("1", "true", "yes", "on").contains(string(value, "").toLowerCase(Locale.ROOT));
    }

    private int intValue(Object value, int defaultValue) {
        if (value instanceof Number number) return number.intValue();
        try {
            return (int) Double.parseDouble(String.valueOf(value));
        } catch (Exception error) {
            return defaultValue;
        }
    }

    private static LinkedHashMap<String, Object> orderedMap() {
        return new LinkedHashMap<>();
    }
}
