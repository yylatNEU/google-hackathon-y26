package com.parkpulse.backend;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Service;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

@Service
public class VenueProfileService {
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};
    private static final List<String> REQUIRED_CHANNEL_OWNERS = List.of("guest_app", "signage", "email", "staff_cue");
    private final Environment environment;
    private final ObjectMapper objectMapper;

    public VenueProfileService(Environment environment, ObjectMapper objectMapper) {
        this.environment = environment;
        this.objectMapper = objectMapper;
    }

    public Map<String, Object> profile() {
        LoadedExport loaded = activeExport();
        return withGlobalProfile(profileFromExport(loaded.export(), loaded.loadedFrom()));
    }

    public Map<String, Object> syntheticExport() {
        Map<String, Object> export = approvedSyntheticExport();
        Map<String, Object> candidate = mutableMap(export);
        candidate.put("loaded_from", "parkpulse_synthetic_venue_export.approved.json");
        Map<String, Object> payload = orderedMap();
        payload.put("status", "ready");
        payload.put("mode", "venue_profile_synthetic_export_spring");
        payload.put("runtime", "java_spring");
        payload.put("sourceName", "parkpulse_synthetic_venue_export.approved.json");
        payload.put("export", export);
        payload.put("validation", validate(candidate));
        payload.put("message", "Approved synthetic venue export loaded for preview only. It has not been activated.");
        return payload;
    }

    public Map<String, Object> validateExport(Map<String, Object> body) {
        Map<String, Object> payload = body == null ? orderedMap() : mutableMap(body);
        Map<String, Object> export = mapValue(payload.get("export")).isEmpty() ? payload : mapValue(payload.get("export"));
        String sourceName = string(payload.get("sourceName"), string(payload.get("source_name"), ""));
        if (!sourceName.isBlank()) {
            export = mutableMap(export);
            export.put("loaded_from", sourceName);
        }
        return Map.of(
            "status", "ready",
            "mode", "venue_profile_validation_spring",
            "runtime", "java_spring",
            "validation", validate(export)
        );
    }

    public Map<String, Object> previewImport(Map<String, Object> body) {
        Map<String, Object> payload = body == null ? orderedMap() : mutableMap(body);
        Map<String, Object> export = mapValue(payload.get("export"));
        String sourceName = string(payload.get("sourceName"), string(payload.get("source_name"), ""));
        if (export.isEmpty()) {
            return Map.of(
                "status", "blocked",
                "mode", "venue_profile_import_preview_spring",
                "runtime", "java_spring",
                "message", "Preview requires an export JSON object.",
                "validation", validate(Map.of()),
                "canActivate", false
            );
        }
        Map<String, Object> candidate = mutableMap(export);
        if (!sourceName.isBlank()) {
            candidate.put("loaded_from", sourceName);
        }
        Map<String, Object> validation = validate(candidate);
        Map<String, Object> currentProfile = profile();
        Map<String, Object> candidateProfile = profileFromExport(candidate, string(candidate.get("loaded_from"), sourceName));
        Map<String, Object> response = orderedMap();
        response.put("status", "ready");
        response.put("mode", "venue_profile_import_preview_spring");
        response.put("runtime", "java_spring");
        response.put("sourceName", sourceName);
        response.put("validation", validation);
        response.put("canActivate", "studio_ready".equals(validation.get("status")));
        response.put("diff", profileDiff(currentProfile, candidateProfile));
        response.put("currentSummary", profileSummary(currentProfile));
        response.put("candidateSummary", profileSummary(candidateProfile));
        return response;
    }

    public Map<String, Object> importExport(Map<String, Object> body) {
        Map<String, Object> payload = body == null ? orderedMap() : mutableMap(body);
        Map<String, Object> export = mapValue(payload.get("export"));
        String sourceName = string(payload.get("sourceName"), string(payload.get("source_name"), ""));
        String actor = string(payload.get("actor"), "venue_data_admin");
        if (export.isEmpty()) {
            return Map.of(
                "status", "blocked",
                "mode", "venue_profile_import_spring",
                "runtime", "java_spring",
                "message", "Import requires an export JSON object.",
                "validation", validate(Map.of())
            );
        }
        if (sourceName.isBlank()) {
            return Map.of(
                "status", "blocked",
                "mode", "venue_profile_import_spring",
                "runtime", "java_spring",
                "message", "Import requires a real source name, such as a venue CMS export path or approved data package name.",
                "validation", validate(export)
            );
        }
        Map<String, Object> candidate = mutableMap(export);
        candidate.put("loaded_from", sourceName);
        Map<String, Object> validation = validate(candidate);
        if (!"studio_ready".equals(validation.get("status"))) {
            return Map.of(
                "status", "blocked",
                "mode", "venue_profile_import_spring",
                "runtime", "java_spring",
                "message", "Venue export did not pass Experience Studio readiness checks.",
                "validation", validation
            );
        }

        Map<String, Object> saved = mutableMap(export);
        saved.put("imported_by", actor);
        saved.put("imported_source_name", sourceName);
        saved.put("loaded_from", sourceName);
        Path target = runtimeExportPath();
        try {
            Files.createDirectories(target.getParent());
            Path temp = target.resolveSibling(target.getFileName() + ".tmp");
            Files.writeString(temp, objectMapper.writerWithDefaultPrettyPrinter().writeValueAsString(saved));
            Files.move(temp, target, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
        } catch (Exception error) {
            return Map.of(
                "status", "blocked",
                "mode", "venue_profile_import_spring",
                "runtime", "java_spring",
                "message", "Venue export could not be written: " + error.getMessage(),
                "validation", validation
            );
        }

        Map<String, Object> response = orderedMap();
        response.put("status", "imported");
        response.put("mode", "venue_profile_import_spring");
        response.put("runtime", "java_spring");
        response.put("message", "Venue export imported and activated for Experience Studio.");
        response.put("savedTo", target.toString());
        response.put("sourceName", sourceName);
        response.put("validation", validate(activeExport().export()));
        response.put("venueProfile", profile());
        return response;
    }

    public Map<String, Object> activateSynthetic(Map<String, Object> body) {
        Map<String, Object> payload = body == null ? orderedMap() : body;
        Map<String, Object> imported = importExport(Map.of(
            "sourceName", "parkpulse_synthetic_venue_export.approved.json",
            "export", approvedSyntheticExport(),
            "actor", string(payload.get("actor"), "experience_studio")
        ));
        Map<String, Object> response = orderedMap();
        response.putAll(imported);
        response.put("mode", "venue_profile_synthetic_activation_spring");
        return response;
    }

    private Map<String, Object> profileFromExport(Map<String, Object> export, String loadedFrom) {
        Map<String, Object> validation = validate(export);
        boolean autofill = Boolean.TRUE.equals(validation.get("autofillAllowed"));
        Map<String, Object> identity = export.isEmpty() ? null : venueIdentity(export);
        Map<String, Object> locationDetails = autofill ? locationDetails(export) : Map.of();
        Map<String, Object> zoneDetails = autofill ? zoneDetails(export, locationDetails) : Map.of();
        Map<String, Object> spatialModel = autofill ? spatialModel(export, zoneDetails) : Map.of("zones", Map.of(), "paths", List.of());
        List<Object> guestSegments = autofill ? listValue(export.get("guest_segments")) : List.of();
        Map<String, Object> operatingContext = autofill ? mapValue(export.get("experience_operations")) : Map.of();
        Map<String, Object> profileIntelligence = autofill ? profileIntelligence(export, locationDetails, zoneDetails, spatialModel) : Map.of();
        Map<String, Object> learningContext = autofill ? learningContext(export, zoneDetails) : Map.of();
        Map<String, Object> agentContext = autofill ? agentContext(export) : Map.of();

        Map<String, Object> realInputs = orderedMap();
        realInputs.put("source", "venue_experience_data:" + string(loadedFrom, string(validation.get("loadedFrom"), "not_connected")));
        realInputs.put("venueIdentity", identity);
        realInputs.put("locations", autofill ? venueLocationNames(export) : List.of());
        realInputs.put("indoorLocations", autofill ? indoorOrSheltered(export) : List.of());
        realInputs.put("quietLocations", autofill ? quietOrCooling(export) : List.of());
        realInputs.put("attractionLocations", autofill ? attractionNames(export) : List.of());
        realInputs.put("accessibleRoutes", autofill ? accessibilityNotes(export) : List.of());
        realInputs.put("safetyInstructions", autofill ? safetyInstructions(export) : List.of());
        realInputs.put("channelOwners", autofill ? channelOwners(export) : Map.of());
        realInputs.put("locationDetails", locationDetails);
        realInputs.put("zoneDetails", zoneDetails);
        realInputs.put("spatialModel", spatialModel);
        realInputs.put("guestSegments", guestSegments);
        realInputs.put("operatingPriors", autofill ? operatingPriors(export, zoneDetails) : Map.of());
        realInputs.put("operatingContext", operatingContext);
        realInputs.put("currentStatus", mapValue(operatingContext.get("current_status")));
        realInputs.put("pathStatus", mapValue(operatingContext.get("path_status")));
        realInputs.put("signageInventory", mapValue(operatingContext.get("signage_inventory")));
        realInputs.put("channelTemplates", mapValue(operatingContext.get("channel_templates")));
        realInputs.put("operatingCalendar", mapValue(operatingContext.get("operating_calendar")));
        realInputs.put("weatherPolicy", mapValue(operatingContext.get("weather_policy")));
        realInputs.put("learningContext", learningContext);
        realInputs.put("agentContext", agentContext);
        realInputs.put("profileIntelligence", profileIntelligence);

        Map<String, Object> counts = counts(realInputs, zoneDetails, spatialModel, profileIntelligence, operatingContext);
        Map<String, Object> readiness = orderedMap();
        readiness.put("status", validation.get("status"));
        readiness.put("autofillAllowed", validation.get("autofillAllowed"));
        readiness.put("handoffReady", validation.get("handoffReady"));
        readiness.put("loadedFrom", loadedFrom == null || loadedFrom.isBlank() ? validation.get("loadedFrom") : loadedFrom);
        readiness.put("counts", counts);
        readiness.put("issues", validation.get("issues"));
        readiness.put("profileIntelligence", mapValue(profileIntelligence.get("readiness")).isEmpty() ? validation.get("profileIntelligence") : profileIntelligence.get("readiness"));
        readiness.put("realVenueReady", validation.get("realVenueReady"));

        String profileType = identity == null ? "not_connected" : string(identity.get("profileType"), "venue_export");
        boolean synthetic = isSyntheticSource(export) || "synthetic_approved".equals(profileType);
        Map<String, Object> sourceIntegrity = orderedMap();
        sourceIntegrity.put("usesSeedData", false);
        sourceIntegrity.put("usesSampleData", isSampleExport(export));
        sourceIntegrity.put("usesApprovedSyntheticProfile", synthetic);
        sourceIntegrity.put("realVenueFeedConnected", !export.isEmpty() && !synthetic);
        sourceIntegrity.put("realVenueReady", Boolean.TRUE.equals(validation.get("realVenueReady")));
        sourceIntegrity.put("profileType", profileType);
        sourceIntegrity.put("customerValidationStatus", mapValue(validation.get("customerValidation")).get("status"));
        sourceIntegrity.put("profileIntelligenceStatus", mapValue(validation.get("profileIntelligence")).get("status"));

        Map<String, Object> result = orderedMap();
        result.put("status", "ready");
        result.put("mode", "venue_profile_spring");
        result.put("runtime", "java_spring");
        result.put("venueIdentity", identity);
        result.put("readiness", readiness);
        result.put("realInputs", realInputs);
        result.put("sourceIntegrity", sourceIntegrity);
        result.put("validation", validation);
        result.put("contract", contract());
        return result;
    }

    private Map<String, Object> validate(Map<String, Object> export) {
        Map<String, Object> payload = export == null ? Map.of() : export;
        Map<String, Object> customerValidation = customerValidation(payload);
        List<Map<String, Object>> issues = experienceIssues(payload);
        boolean customerReady = "production_ready".equals(customerValidation.get("status"));
        boolean studioReady = customerReady && issues.isEmpty();
        Map<String, Object> profileReadiness = profileIntelligenceReadiness(payload);
        String profileType = payload.isEmpty() ? "not_connected" : string(venueIdentity(payload).get("profileType"), "venue_export");
        boolean synthetic = isSyntheticSource(payload) || "synthetic_approved".equals(profileType);
        Map<String, Object> result = orderedMap();
        result.put("status", studioReady ? "studio_ready" : "blocked");
        result.put("customerValidation", customerValidation);
        result.put("experienceIssueCount", issues.size());
        result.put("criticalCount", issues.stream().filter(issue -> "critical".equals(issue.get("severity"))).count());
        result.put("highCount", issues.stream().filter(issue -> "high".equals(issue.get("severity"))).count());
        result.put("issues", issues);
        result.put("autofillAllowed", !payload.isEmpty() && customerReady && !isSampleExport(payload));
        result.put("handoffReady", studioReady);
        result.put("profileIntelligence", profileReadiness);
        result.put("realVenueReady", studioReady && !synthetic && Boolean.TRUE.equals(profileReadiness.get("realVenueReady")));
        result.put("loadedFrom", payload.get("loaded_from"));
        return result;
    }

    private Map<String, Object> customerValidation(Map<String, Object> export) {
        List<Map<String, Object>> checks = new ArrayList<>();
        List<Map<String, Object>> issues = new ArrayList<>();
        addCheck(checks, issues, "json_object", export != null, "critical", "Venue export must be a JSON object.", null);
        Map<String, Object> payload = export == null ? Map.of() : export;
        addCheck(checks, issues, "approved_for_production", truthy(payload.get("approved_for_production")), "critical", "Venue export must be explicitly approved for production.", "approved_for_production");
        addCheck(checks, issues, "approved_metadata", hasText(payload.get("approved_by")) && hasText(payload.get("approved_at")), "high", "Venue export must include approved_by and approved_at.", "approved_by");
        Map<String, Object> sourceCatalog = mapValue(payload.get("source_catalog"));
        Map<String, Object> sources = mapValue(sourceCatalog.get("sources"));
        Map<String, Object> fieldSources = mapValue(sourceCatalog.get("field_sources"));
        addCheck(checks, issues, "source_catalog_present", !sourceCatalog.isEmpty(), "critical", "source_catalog is required.", "source_catalog");
        addCheck(checks, issues, "real_venue_feed_connected", truthy(sourceCatalog.get("real_venue_feed_connected")), "critical", "source_catalog.real_venue_feed_connected must be true.", "source_catalog.real_venue_feed_connected");
        addCheck(checks, issues, "review_queue_empty", listValue(sourceCatalog.get("review_queue")).isEmpty(), "critical", "source_catalog.review_queue must be empty.", "source_catalog.review_queue");
        addCheck(checks, issues, "no_seed_source_types", sources.values().stream().noneMatch(source -> "seed_catalog".equals(mapValue(source).get("source_type"))), "critical", "Seed source types are not production-approved.", "source_catalog.sources");
        for (String field : List.of("rides", "food", "venue_map", "event_schedule", "landmarks", "shows", "family_services", "copy_variants")) {
            List<Object> ids = listValue(fieldSources.get(field));
            addCheck(checks, issues, "field_sources_" + field, !ids.isEmpty(), "critical", field + " must list source ids.", "source_catalog.field_sources." + field);
            addCheck(checks, issues, "field_sources_known_" + field, ids.stream().allMatch(id -> sources.containsKey(String.valueOf(id))), "critical", field + " source ids must exist in source_catalog.sources.", "source_catalog.field_sources." + field);
        }
        for (Map.Entry<String, Object> entry : sources.entrySet()) {
            Map<String, Object> source = mapValue(entry.getValue());
            String sourceId = entry.getKey();
            addCheck(checks, issues, "source_confidence_" + sourceId, number(source.get("confidence")) >= 0.74, "high", sourceId + " confidence must be >= 0.74.", "source_catalog.sources." + sourceId + ".confidence");
            addCheck(checks, issues, "source_review_" + sourceId, "venue_approved".equals(source.get("review_status")), "critical", sourceId + " must be venue_approved.", "source_catalog.sources." + sourceId + ".review_status");
            addCheck(checks, issues, "source_verified_at_" + sourceId, hasText(source.get("last_verified_at")), "high", sourceId + " must include last_verified_at.", "source_catalog.sources." + sourceId + ".last_verified_at");
            addCheck(checks, issues, "source_freshness_" + sourceId, source.get("max_age_seconds") instanceof Number, "high", sourceId + " must include max_age_seconds.", "source_catalog.sources." + sourceId + ".max_age_seconds");
        }
        addCheck(checks, issues, "attractions_present", !listValue(payload.get("attractions")).isEmpty(), "critical", "attractions must be populated.", "attractions");
        addCheck(checks, issues, "food_present", !listValue(payload.get("food")).isEmpty(), "critical", "food must be populated.", "food");
        addCheck(checks, issues, "menus_present", !mapValue(payload.get("menus")).isEmpty(), "critical", "menus must be populated.", "menus");
        addCheck(checks, issues, "venue_map_nodes_present", !listValue(mapValue(payload.get("venue_map")).get("nodes")).isEmpty(), "critical", "venue_map.nodes must be populated.", "venue_map.nodes");
        Map<String, Object> landmarks = mapValue(payload.get("landmarks"));
        addCheck(checks, issues, "landmark_services_present", !listValue(landmarks.get("restrooms")).isEmpty() && !listValue(landmarks.get("first_aid")).isEmpty(), "critical", "landmarks must include restrooms and first_aid.", "landmarks");
        addCheck(checks, issues, "english_copy_present", mapValue(payload.get("copy_variants")).containsKey("en"), "critical", "copy_variants.en is required.", "copy_variants.en");
        long critical = issues.stream().filter(issue -> "critical".equals(issue.get("severity"))).count();
        long high = issues.stream().filter(issue -> "high".equals(issue.get("severity"))).count();
        return Map.of(
            "status", critical == 0 && high == 0 ? "production_ready" : "blocked",
            "check_count", checks.size(),
            "critical_count", critical,
            "high_count", high,
            "checks", checks,
            "issues", issues
        );
    }

    private void addCheck(List<Map<String, Object>> checks, List<Map<String, Object>> issues, String id, boolean passed, String severity, String detail, String field) {
        Map<String, Object> row = orderedMap();
        row.put("id", id);
        row.put("passed", passed);
        row.put("severity", severity);
        row.put("detail", detail);
        if (field != null) {
            row.put("field", field);
        }
        checks.add(row);
        if (!passed) {
            Map<String, Object> issue = orderedMap();
            issue.put("id", id);
            issue.put("severity", severity);
            issue.put("field", field);
            issue.put("detail", detail);
            issues.add(issue);
        }
    }

    private List<Map<String, Object>> experienceIssues(Map<String, Object> export) {
        List<Map<String, Object>> issues = new ArrayList<>();
        if (export == null || export.isEmpty()) {
            issues.add(issue("venue_export_not_connected", "critical", "PARKPULSE_CUSTOMER_VENUE_EXPORT_PATH", "No real venue export is configured."));
            return issues;
        }
        if (isSampleExport(export)) {
            issues.add(issue("sample_export_not_allowed", "critical", "loaded_from", "Sample venue exports cannot be used for Experience Studio autofill."));
        }
        if (venueLocationNames(export).size() < 3) {
            issues.add(issue("verified_locations", "critical", "locations", "At least three venue-approved public locations are required."));
        }
        if (indoorOrSheltered(export).isEmpty()) {
            issues.add(issue("indoor_or_sheltered_locations", "high", "indoorLocations", "At least one venue-approved indoor or sheltered location is required."));
        }
        if (accessibilityNotes(export).isEmpty()) {
            issues.add(issue("accessibility_notes", "critical", "accessibleRoutes", "Venue-approved accessibility notes or map facts are required."));
        }
        if (safetyInstructions(export).isEmpty()) {
            issues.add(issue("safety_instructions", "critical", "safetyInstructions", "Venue-approved safety or first-aid guest instructions are required."));
        }
        Map<String, Object> owners = channelOwners(export);
        if (!owners.keySet().containsAll(REQUIRED_CHANNEL_OWNERS)) {
            issues.add(issue("channel_owners", "critical", "channel_owners", "Guest app, signage, email, and staff cue owners are required."));
        }
        return issues;
    }

    private Map<String, Object> issue(String id, String severity, String field, String detail) {
        return Map.of("id", id, "severity", severity, "field", field, "detail", detail);
    }

    private Map<String, Object> venueIdentity(Map<String, Object> export) {
        Map<String, Object> identity = mapValue(export.get("venue_identity"));
        Map<String, Object> sourceCatalog = mapValue(export.get("source_catalog"));
        Map<String, Object> result = orderedMap();
        result.put("venueId", string(identity.get("venue_id"), ""));
        result.put("name", string(identity.get("name"), "Unspecified venue"));
        result.put("profileType", string(identity.get("profile_type"), string(sourceCatalog.get("profile_type"), "venue_export")));
        result.put("description", string(identity.get("description"), ""));
        result.put("primaryAudiences", listValue(identity.get("primary_audiences")).stream().filter(this::hasText).toList());
        result.put("publicZones", listValue(identity.get("public_zones")).stream().filter(item -> item instanceof Map<?, ?>).toList());
        return result;
    }

    private List<String> venueLocationNames(Map<String, Object> export) {
        LinkedHashSet<String> names = new LinkedHashSet<>();
        for (String collection : List.of("attractions", "shows", "food", "family_services")) {
            for (Object item : listValue(export.get(collection))) {
                if (item instanceof Map<?, ?> row && knownApprovedSources(export, mapValue(row))) {
                    addName(names, mapValue(row).get("name"));
                }
            }
        }
        for (Object rows : mapValue(export.get("landmarks")).values()) {
            for (Object item : listValue(rows)) {
                if (item instanceof Map<?, ?> row && knownApprovedSources(export, mapValue(row))) {
                    addName(names, mapValue(row).get("name"));
                }
            }
        }
        for (Object item : listValue(mapValue(export.get("venue_map")).get("nodes"))) {
            if (item instanceof Map<?, ?> row && knownApprovedSources(export, mapValue(row))) {
                addName(names, mapValue(row).get("name"));
            }
        }
        return new ArrayList<>(names);
    }

    private List<String> indoorOrSheltered(Map<String, Object> export) {
        LinkedHashSet<String> names = new LinkedHashSet<>();
        for (Object item : listValue(export.get("attractions"))) {
            Map<String, Object> row = mapValue(item);
            if (knownApprovedSources(export, row) && (truthy(row.get("indoor")) || truthy(row.get("covered")))) {
                addName(names, row.get("name"));
            }
        }
        for (Object item : listValue(export.get("food"))) {
            Map<String, Object> row = mapValue(item);
            String seating = string(row.get("seating"), "").toLowerCase(Locale.ROOT);
            if (knownApprovedSources(export, row) && (truthy(row.get("covered")) || seating.contains("covered") || seating.contains("indoor"))) {
                addName(names, row.get("name"));
            }
        }
        for (Object item : listValue(mapValue(export.get("landmarks")).get("quiet_or_cooling"))) {
            Map<String, Object> row = mapValue(item);
            if (knownApprovedSources(export, row)) {
                addName(names, row.get("name"));
            }
        }
        return new ArrayList<>(names);
    }

    private List<String> quietOrCooling(Map<String, Object> export) {
        LinkedHashSet<String> names = new LinkedHashSet<>();
        for (Object item : listValue(mapValue(export.get("landmarks")).get("quiet_or_cooling"))) {
            Map<String, Object> row = mapValue(item);
            if (knownApprovedSources(export, row)) {
                addName(names, row.get("name"));
            }
        }
        for (Object item : listValue(export.get("family_services"))) {
            Map<String, Object> row = mapValue(item);
            if (knownApprovedSources(export, row) && string(row.get("name"), "").toLowerCase(Locale.ROOT).contains("stimulus")) {
                addName(names, row.get("name"));
            }
        }
        return new ArrayList<>(names);
    }

    private List<String> attractionNames(Map<String, Object> export) {
        LinkedHashSet<String> names = new LinkedHashSet<>();
        for (Object item : listValue(export.get("attractions"))) {
            Map<String, Object> row = mapValue(item);
            if (knownApprovedSources(export, row)) {
                addName(names, row.get("name"));
            }
        }
        return new ArrayList<>(names);
    }

    private List<String> accessibilityNotes(Map<String, Object> export) {
        LinkedHashSet<String> notes = new LinkedHashSet<>();
        for (String collection : List.of("attractions", "food", "family_services")) {
            for (Object item : listValue(export.get(collection))) {
                Map<String, Object> row = mapValue(item);
                if (knownApprovedSources(export, row)) {
                    addName(notes, row.get("accessibility_note"));
                }
            }
        }
        for (Object item : listValue(mapValue(export.get("venue_map")).get("paths"))) {
            Map<String, Object> row = mapValue(item);
            if (knownApprovedSources(export, row)) {
                addName(notes, row.get("accessibility_note"));
            }
        }
        for (Object item : listValue(mapValue(export.get("landmarks")).get("first_aid"))) {
            Map<String, Object> row = mapValue(item);
            if (knownApprovedSources(export, row)) {
                addName(notes, row.get("accessibility_note"));
            }
        }
        return new ArrayList<>(notes);
    }

    private List<String> safetyInstructions(Map<String, Object> export) {
        LinkedHashSet<String> rows = new LinkedHashSet<>();
        for (Object item : listValue(export.get("safety_instructions"))) {
            if (item instanceof String value) {
                addName(rows, value);
            } else {
                Map<String, Object> row = mapValue(item);
                if (knownApprovedSources(export, row)) {
                    addName(rows, row.get("instruction"));
                    addName(rows, row.get("text"));
                }
            }
        }
        for (Object item : listValue(mapValue(export.get("landmarks")).get("first_aid"))) {
            Map<String, Object> row = mapValue(item);
            if (knownApprovedSources(export, row)) {
                addName(rows, "First aid available at " + string(row.get("name"), "guest services"));
            }
        }
        return new ArrayList<>(rows);
    }

    private Map<String, Object> channelOwners(Map<String, Object> export) {
        Map<String, Object> owners = mapValue(export.get("channel_owners"));
        Map<String, Object> result = orderedMap();
        for (String owner : REQUIRED_CHANNEL_OWNERS) {
            if (hasText(owners.get(owner))) {
                result.put(owner, string(owners.get(owner), ""));
            }
        }
        return result;
    }

    private Map<String, Object> locationDetails(Map<String, Object> export) {
        Map<String, Object> details = orderedMap();
        for (Object item : listValue(export.get("attractions"))) {
            Map<String, Object> row = mapValue(item);
            if (knownApprovedSources(export, row)) {
                addLocation(details, row, "attraction", List.of("zone_id", "category", "thrill_level", "duration_minutes", "height_requirement_inches", "indoor", "covered", "family_fit", "accessibility_note", "sensory_note", "source_ids"));
            }
        }
        for (Object item : listValue(export.get("food"))) {
            Map<String, Object> row = mapValue(item);
            if (knownApprovedSources(export, row)) {
                addLocation(details, row, "food", List.of("zone_id", "cuisine", "dietary_tags", "mobile_order", "seating", "covered", "accessibility_note", "source_ids"));
            }
        }
        for (Object item : listValue(export.get("shows"))) {
            Map<String, Object> row = mapValue(item);
            if (knownApprovedSources(export, row)) {
                addLocation(details, row, "show", List.of("zone_id", "duration_minutes", "showtimes", "covered", "accessibility_note", "source_ids"));
            }
        }
        for (Object item : listValue(export.get("family_services"))) {
            Map<String, Object> row = mapValue(item);
            if (knownApprovedSources(export, row)) {
                addLocation(details, row, "family_service", List.of("zone_id", "category", "accessibility_note", "source_ids"));
            }
        }
        for (Object rows : mapValue(export.get("landmarks")).values()) {
            for (Object item : listValue(rows)) {
                Map<String, Object> row = mapValue(item);
                if (knownApprovedSources(export, row)) {
                    addLocation(details, row, "landmark", List.of("zone_id", "type", "accessibility_note", "source_ids"));
                }
            }
        }
        return details;
    }

    private void addLocation(Map<String, Object> details, Map<String, Object> row, String kind, List<String> fields) {
        String name = string(row.get("name"), "");
        if (name.isBlank()) {
            return;
        }
        Map<String, Object> detail = orderedMap();
        detail.put("name", name);
        detail.put("kind", kind);
        for (String field : fields) {
            Object value = row.get(field);
            if (value != null && !String.valueOf(value).isBlank()) {
                detail.put(camel(field), value);
            }
        }
        details.put(name, detail);
    }

    private Map<String, Object> zoneDetails(Map<String, Object> export, Map<String, Object> locations) {
        Map<String, Object> zones = orderedMap();
        for (Object zoneObj : listValue(mapValue(export.get("venue_identity")).get("public_zones"))) {
            Map<String, Object> zone = mapValue(zoneObj);
            String id = string(zone.get("id"), string(zone.get("name"), ""));
            if (id.isBlank()) {
                continue;
            }
            List<String> locationNames = locations.values().stream()
                .map(this::mapValue)
                .filter(row -> id.equals(row.get("zoneId")))
                .map(row -> string(row.get("name"), ""))
                .filter(name -> !name.isBlank())
                .toList();
            Map<String, Object> detail = orderedMap();
            detail.put("id", id);
            detail.put("name", string(zone.get("name"), id));
            detail.put("position", string(zone.get("position"), ""));
            detail.put("locationNames", locationNames);
            detail.put("source", "venue_profile.public_zones + approved public location records");
            zones.put(id, detail);
        }
        return zones;
    }

    private Map<String, Object> spatialModel(Map<String, Object> export, Map<String, Object> zones) {
        Map<String, Object> venueMap = mapValue(export.get("venue_map"));
        Map<String, Object> result = orderedMap();
        result.put("source", "venue_profile.venue_map");
        result.put("zones", zones);
        result.put("nodes", approvedMapNodes(export));
        result.put("paths", listValue(venueMap.get("paths")).stream().filter(item -> knownApprovedSources(export, mapValue(item))).toList());
        result.put("derivationNotes", List.of("Use explicit venue_map.paths when supplied; otherwise consumers must treat geometry as coarse wayfinding context."));
        return result;
    }

    private List<Object> approvedMapNodes(Map<String, Object> export) {
        return listValue(mapValue(export.get("venue_map")).get("nodes")).stream()
            .filter(item -> knownApprovedSources(export, mapValue(item)))
            .toList();
    }

    private Map<String, Object> operatingPriors(Map<String, Object> export, Map<String, Object> zones) {
        return Map.of(
            "source", "venue_profile_spring",
            "zoneCount", zones.size(),
            "primaryAudiences", listValue(mapValue(export.get("venue_identity")).get("primary_audiences")),
            "reviewRequired", true
        );
    }

    private Map<String, Object> learningContext(Map<String, Object> export, Map<String, Object> zones) {
        return Map.of(
            "source", "venue_profile_spring",
            "feedbackLabels", List.of("guest_comfort", "handoff_quality", "route_clarity", "channel_owner_review"),
            "learningBoundary", "Aggregate outcomes and reviewer labels only; no private guest identity or medical/disability status.",
            "zoneIds", zones.keySet().stream().toList()
        );
    }

    private Map<String, Object> agentContext(Map<String, Object> export) {
        return Map.of(
            "source", "venue_profile_spring",
            "groundingFields", List.of("venueIdentity", "locationDetails", "guestSegments", "copyVariants", "channelOwners", "currentStatus", "pathStatus", "signageInventory", "channelTemplates", "weatherPolicy"),
            "authorityBoundary", "Agents can draft and review. They cannot dispatch staff, alter live operations, or publish without human approval."
        );
    }

    private Map<String, Object> profileIntelligence(Map<String, Object> export, Map<String, Object> locations, Map<String, Object> zones, Map<String, Object> spatialModel) {
        Map<String, Object> supplied = mapValue(export.get("profile_intelligence"));
        Map<String, Object> intelligence = orderedMap();
        intelligence.put("version", "profile_intelligence_v1");
        intelligence.put("readiness", profileIntelligenceReadiness(export));
        intelligence.put("certifiedPaths", listValue(supplied.get("certified_paths")));
        intelligence.put("capacityModel", mapValue(supplied.get("capacity_model")));
        intelligence.put("timingModel", mapValue(supplied.get("timing_model")));
        intelligence.put("experienceRules", mapValue(supplied.get("experience_rules")));
        intelligence.put("brandBible", mapValue(supplied.get("brand_bible")));
        intelligence.put("reviewOwners", mapValue(supplied.get("review_owners")));
        intelligence.put("fieldSourceLedger", Map.of("rows", fieldSourceRows(export)));
        Map<String, Object> modulePolicy = orderedMap();
        modulePolicy.putAll(mapValue(supplied.get("module_policy")));
        modulePolicy.putIfAbsent("experience_studio", "draft_only_human_review_required");
        modulePolicy.putIfAbsent("command_center", "review_and_dispatch_authority");
        intelligence.put("modulePolicy", modulePolicy);
        intelligence.put("liveFeedBindings", Map.of("locations", locations.keySet(), "zones", zones.keySet(), "paths", listValue(spatialModel.get("paths")).size()));
        return intelligence;
    }

    private Map<String, Object> profileIntelligenceReadiness(Map<String, Object> export) {
        Map<String, Object> supplied = mapValue(export.get("profile_intelligence"));
        boolean certifiedPaths = !listValue(supplied.get("certified_paths")).isEmpty();
        boolean capacity = "venue_certified".equals(mapValue(supplied.get("capacity_model")).get("status"));
        boolean timing = "venue_scheduled".equals(mapValue(supplied.get("timing_model")).get("status"));
        int ready = (certifiedPaths ? 1 : 0) + (capacity ? 1 : 0) + (timing ? 1 : 0);
        String status = ready == 3 ? "certified" : ready > 0 ? "partial" : "not_supplied";
        return Map.of(
            "status", status,
            "readyComponentCount", ready,
            "requiredComponentCount", 3,
            "realVenueReady", ready == 3,
            "missingComponents", missingComponents(certifiedPaths, capacity, timing)
        );
    }

    private List<String> missingComponents(boolean certifiedPaths, boolean capacity, boolean timing) {
        List<String> missing = new ArrayList<>();
        if (!certifiedPaths) missing.add("certifiedPaths");
        if (!capacity) missing.add("capacityModel");
        if (!timing) missing.add("timingModel");
        return missing;
    }

    private List<Map<String, Object>> fieldSourceRows(Map<String, Object> export) {
        Map<String, Object> sources = sources(export);
        List<Map<String, Object>> rows = new ArrayList<>();
        for (Map.Entry<String, Object> entry : sources.entrySet()) {
            Map<String, Object> source = mapValue(entry.getValue());
            rows.add(Map.of(
                "sourceId", entry.getKey(),
                "sourceType", source.getOrDefault("source_type", ""),
                "reviewStatus", source.getOrDefault("review_status", ""),
                "lastVerifiedAt", source.getOrDefault("last_verified_at", ""),
                "staleBehavior", "require_review"
            ));
        }
        return rows;
    }

    private Map<String, Object> counts(Map<String, Object> realInputs, Map<String, Object> zoneDetails, Map<String, Object> spatialModel, Map<String, Object> profileIntelligence, Map<String, Object> operatingContext) {
        Map<String, Object> counts = orderedMap();
        counts.put("locations", listValue(realInputs.get("locations")).size());
        counts.put("indoorLocations", listValue(realInputs.get("indoorLocations")).size());
        counts.put("accessibleRoutes", listValue(realInputs.get("accessibleRoutes")).size());
        counts.put("safetyInstructions", listValue(realInputs.get("safetyInstructions")).size());
        counts.put("channelOwners", mapValue(realInputs.get("channelOwners")).size());
        counts.put("zones", zoneDetails.size());
        counts.put("paths", listValue(spatialModel.get("paths")).size());
        counts.put("guestSegments", listValue(realInputs.get("guestSegments")).size());
        counts.put("agentGroundingFields", listValue(mapValue(realInputs.get("agentContext")).get("groundingFields")).size());
        counts.put("learningSignals", listValue(mapValue(realInputs.get("learningContext")).get("feedbackLabels")).size());
        counts.put("certifiedPaths", listValue(profileIntelligence.get("certifiedPaths")).size());
        counts.put("capacityZones", listValue(mapValue(profileIntelligence.get("capacityModel")).get("zone_comfort")).size());
        counts.put("fieldSourceRows", listValue(mapValue(profileIntelligence.get("fieldSourceLedger")).get("rows")).size());
        counts.put("modulePolicies", mapValue(profileIntelligence.get("modulePolicy")).size());
        counts.put("liveFeedBindingGroups", mapValue(profileIntelligence.get("liveFeedBindings")).size());
        counts.put("currentOptions", listValue(mapValue(operatingContext.get("current_status")).get("attractions")).size());
        counts.put("pathStatusSegments", listValue(mapValue(operatingContext.get("path_status")).get("route_segments")).size());
        counts.put("signagePlacements", listValue(mapValue(operatingContext.get("signage_inventory")).get("placements")).size());
        counts.put("channelTemplates", mapValue(mapValue(operatingContext.get("channel_templates")).get("templates")).size());
        counts.put("operatingEventWindows", listValue(mapValue(operatingContext.get("operating_calendar")).get("event_windows")).size());
        return counts;
    }

    private Map<String, Object> profileDiff(Map<String, Object> current, Map<String, Object> candidate) {
        Map<String, Object> currentInputs = mapValue(current.get("realInputs"));
        Map<String, Object> candidateInputs = mapValue(candidate.get("realInputs"));
        Map<String, Object> beforeCounts = mapValue(mapValue(current.get("readiness")).get("counts"));
        Map<String, Object> afterCounts = mapValue(mapValue(candidate.get("readiness")).get("counts"));
        Map<String, Object> countDelta = orderedMap();
        LinkedHashSet<String> keys = new LinkedHashSet<>();
        keys.addAll(beforeCounts.keySet());
        keys.addAll(afterCounts.keySet());
        for (String key : keys) {
            countDelta.put(key, (int) number(afterCounts.get(key)) - (int) number(beforeCounts.get(key)));
        }
        Set<String> beforeLocations = stableSet(mapValue(currentInputs.get("locationDetails")).keySet());
        Set<String> afterLocations = stableSet(mapValue(candidateInputs.get("locationDetails")).keySet());
        List<String> added = afterLocations.stream().filter(item -> !beforeLocations.contains(item)).toList();
        List<String> removed = beforeLocations.stream().filter(item -> !afterLocations.contains(item)).toList();
        Map<String, Object> ownersBefore = mapValue(currentInputs.get("channelOwners"));
        Map<String, Object> ownersAfter = mapValue(candidateInputs.get("channelOwners"));
        List<Map<String, Object>> ownerChanges = new ArrayList<>();
        LinkedHashSet<String> ownerKeys = new LinkedHashSet<>();
        ownerKeys.addAll(ownersBefore.keySet());
        ownerKeys.addAll(ownersAfter.keySet());
        for (String key : ownerKeys) {
            if (!String.valueOf(ownersBefore.get(key)).equals(String.valueOf(ownersAfter.get(key)))) {
                Map<String, Object> change = orderedMap();
                change.put("channel", key);
                change.put("before", ownersBefore.get(key));
                change.put("after", ownersAfter.get(key));
                ownerChanges.add(change);
            }
        }
        int total = added.size() + removed.size() + ownerChanges.size() + identityChanges(current, candidate).size();
        return Map.of(
            "summary", Map.of(
                "totalChanges", total,
                "addedLocations", added.size(),
                "removedLocations", removed.size(),
                "ownerChanges", ownerChanges.size(),
                "identityChanges", identityChanges(current, candidate).size(),
                "replacementRisk", !removed.isEmpty() || !identityChanges(current, candidate).isEmpty() ? "high" : total > 0 ? "medium" : "low"
            ),
            "countsBefore", beforeCounts,
            "countsAfter", afterCounts,
            "countDelta", countDelta,
            "locations", Map.of("added", added, "removed", removed, "changed", List.of()),
            "channelOwners", Map.of("changed", ownerChanges),
            "identity", Map.of("changed", identityChanges(current, candidate))
        );
    }

    private List<Map<String, Object>> identityChanges(Map<String, Object> current, Map<String, Object> candidate) {
        Map<String, Object> before = mapValue(current.get("venueIdentity"));
        Map<String, Object> after = mapValue(candidate.get("venueIdentity"));
        List<Map<String, Object>> changes = new ArrayList<>();
        for (String field : List.of("venueId", "name", "profileType", "description", "primaryAudiences")) {
            if (!String.valueOf(before.get(field)).equals(String.valueOf(after.get(field)))) {
                Map<String, Object> change = orderedMap();
                change.put("field", field);
                change.put("before", before.get(field));
                change.put("after", after.get(field));
                changes.add(change);
            }
        }
        return changes;
    }

    private Map<String, Object> profileSummary(Map<String, Object> profile) {
        Map<String, Object> summary = orderedMap();
        summary.put("venueIdentity", profile.get("venueIdentity"));
        summary.put("readiness", profile.get("readiness"));
        summary.put("sourceIntegrity", profile.get("sourceIntegrity"));
        return summary;
    }

    private Map<String, Object> withGlobalProfile(Map<String, Object> profile) {
        Map<String, Object> result = mutableMap(profile);
        Map<String, Object> identity = mapValue(result.get("venueIdentity"));
        Map<String, Object> reasoningContract = orderedMap();
        reasoningContract.put("profileFacts", "venue-approved public facts and derived public-map intelligence");
        reasoningContract.put("liveFacts", "waits, crowd, weather, inventory, staffing, incidents, and closures remain live-state inputs");
        reasoningContract.put("learningBoundary", "learn from aggregate outcomes, reviewer labels, source version, and public zone context; do not learn private guest identity or medical/disability status");
        reasoningContract.put("humanAuthority", List.of("medical, allergy, accessibility accommodation, ride safety, emergency routing, staffing, compensation, and backstage decisions"));
        Map<String, Object> globalProfile = orderedMap();
        globalProfile.put("scope", "tenant_venue");
        globalProfile.put("tenantId", "default");
        globalProfile.put("venueId", identity.get("venueId"));
        globalProfile.put("profileType", identity.get("profileType"));
        globalProfile.put("consumers", List.of("experience_studio", "accessibility_journey", "guest_recommendations", "signage_copy", "vip_tours", "command_center_review", "scan_agent", "react_agent", "proact_agent", "learning_evaluation"));
        globalProfile.put("ownership", "Venue Profile layer owns source integrity; consumers use allowed public fields only.");
        globalProfile.put("reasoningContract", reasoningContract);
        result.put("globalProfile", globalProfile);
        return result;
    }

    private Map<String, Object> contract() {
        return Map.of(
            "requiredFields", List.of("verified public locations", "indoor or sheltered locations", "accessibility map facts", "safety instructions", "channel owners", "agent grounding fields", "learning outcome labels", "profile intelligence contract"),
            "blockedSources", List.of("seed_catalog", "sample venue exports", "simulated park state"),
            "agentUse", "Agents may reason from Venue Profile facts and derived public-map intelligence, but must separate profile priors from live state and human-authorized actions."
        );
    }

    private boolean knownApprovedSources(Map<String, Object> export, Map<String, Object> item) {
        List<Object> sourceIds = listValue(item.get("source_ids"));
        if (sourceIds.isEmpty()) {
            return false;
        }
        Map<String, Object> sources = sources(export);
        for (Object id : sourceIds) {
            Map<String, Object> source = mapValue(sources.get(String.valueOf(id)));
            if ("seed_catalog".equals(source.get("source_type"))) {
                return false;
            }
            if (!"venue_approved".equals(source.get("review_status")) || !hasText(source.get("last_verified_at"))) {
                return false;
            }
        }
        return true;
    }

    private Map<String, Object> sources(Map<String, Object> export) {
        return mapValue(mapValue(export.get("source_catalog")).get("sources"));
    }

    private boolean isSyntheticSource(Map<String, Object> export) {
        for (Map.Entry<String, Object> entry : sources(export).entrySet()) {
            String id = entry.getKey().toLowerCase(Locale.ROOT);
            String type = string(mapValue(entry.getValue()).get("source_type"), "").toLowerCase(Locale.ROOT);
            if (id.contains("synthetic") || type.contains("synthetic")) {
                return true;
            }
        }
        return false;
    }

    private boolean isSampleExport(Map<String, Object> export) {
        String loadedFrom = string(export.get("loaded_from"), "");
        if (loadedFrom.isBlank()) {
            return false;
        }
        String name = Path.of(loadedFrom).getFileName().toString().toLowerCase(Locale.ROOT);
        return List.of("sample", ".example", "demo", "seed", "test", "fake").stream().anyMatch(name::contains);
    }

    private LoadedExport activeExport() {
        String configured = environment.getProperty("PARKPULSE_CUSTOMER_VENUE_EXPORT_PATH", "");
        if (!configured.isBlank()) {
            Map<String, Object> export = readJson(Path.of(configured));
            if (!export.isEmpty()) {
                export.put("loaded_from", configured);
                return new LoadedExport(export, configured);
            }
        }
        Path runtime = runtimeExportPath();
        if (Files.exists(runtime)) {
            Map<String, Object> export = readJson(runtime);
            if (!export.isEmpty()) {
                export.put("loaded_from", runtime.toString());
                return new LoadedExport(export, runtime.toString());
            }
        }
        return new LoadedExport(Map.of(), "");
    }

    private Map<String, Object> approvedSyntheticExport() {
        Path path = syntheticExportPath();
        Map<String, Object> export = readJson(path);
        if (export.isEmpty()) {
            throw new IllegalStateException("Approved synthetic venue export is unavailable at " + path);
        }
        return export;
    }

    private Path runtimeExportPath() {
        String configured = environment.getProperty("PARKPULSE_CUSTOMER_VENUE_EXPORT_RUNTIME_PATH", "");
        if (!configured.isBlank()) {
            return Path.of(configured);
        }
        return Path.of(environment.getProperty("PARKPULSE_RUNTIME_DIR", "/tmp/parkpulse")).resolve("customer_venue_export.json");
    }

    private Path syntheticExportPath() {
        String configured = environment.getProperty("PARKPULSE_APPROVED_SYNTHETIC_VENUE_EXPORT_PATH", "");
        if (!configured.isBlank()) {
            return Path.of(configured);
        }
        for (Path path : List.of(
            Path.of("../backend/data/parkpulse_synthetic_venue_export.approved.json"),
            Path.of("backend/data/parkpulse_synthetic_venue_export.approved.json"),
            Path.of("data/parkpulse_synthetic_venue_export.approved.json")
        )) {
            if (Files.exists(path)) {
                return path;
            }
        }
        return Path.of("../backend/data/parkpulse_synthetic_venue_export.approved.json");
    }

    private Map<String, Object> readJson(Path path) {
        try {
            if (!Files.exists(path)) {
                return orderedMap();
            }
            return objectMapper.readValue(Files.readString(path), MAP_TYPE);
        } catch (IOException error) {
            return orderedMap();
        }
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
        if (value instanceof List<?> list) {
            return new ArrayList<>(list);
        }
        return List.of();
    }

    private Map<String, Object> mutableMap(Map<?, ?> map) {
        Map<String, Object> result = orderedMap();
        for (Map.Entry<?, ?> entry : map.entrySet()) {
            result.put(String.valueOf(entry.getKey()), entry.getValue());
        }
        return result;
    }

    private void addName(LinkedHashSet<String> rows, Object value) {
        String clean = string(value, "");
        if (!clean.isBlank()) {
            rows.add(clean);
        }
    }

    private Set<String> stableSet(Set<String> values) {
        LinkedHashSet<String> result = new LinkedHashSet<>();
        for (String value : values) {
            result.add(value.toLowerCase(Locale.ROOT));
        }
        return result;
    }

    private String string(Object value, String defaultValue) {
        if (value == null) {
            return defaultValue;
        }
        String text = String.valueOf(value).trim();
        return text.isBlank() ? defaultValue : text;
    }

    private boolean hasText(Object value) {
        return value != null && !String.valueOf(value).trim().isBlank();
    }

    private boolean truthy(Object value) {
        if (value instanceof Boolean bool) {
            return bool;
        }
        if (value instanceof Number number) {
            return number.doubleValue() != 0;
        }
        return List.of("1", "true", "yes", "on").contains(string(value, "").toLowerCase(Locale.ROOT));
    }

    private double number(Object value) {
        if (value instanceof Number number) {
            return number.doubleValue();
        }
        try {
            return Double.parseDouble(String.valueOf(value));
        } catch (Exception error) {
            return 0;
        }
    }

    private String camel(String snake) {
        StringBuilder builder = new StringBuilder();
        boolean upper = false;
        for (char ch : snake.toCharArray()) {
            if (ch == '_') {
                upper = true;
            } else if (upper) {
                builder.append(Character.toUpperCase(ch));
                upper = false;
            } else {
                builder.append(ch);
            }
        }
        return builder.toString();
    }

    private static LinkedHashMap<String, Object> orderedMap() {
        return new LinkedHashMap<>();
    }

    private record LoadedExport(Map<String, Object> export, String loadedFrom) {}
}
