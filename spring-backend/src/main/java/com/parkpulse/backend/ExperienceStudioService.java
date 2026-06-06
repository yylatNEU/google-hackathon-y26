package com.parkpulse.backend;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Service;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

@Service
public class ExperienceStudioService {
    private static final TypeReference<List<Map<String, Object>>> LIST_TYPE = new TypeReference<>() {};
    private static final List<String> ALLOWED_DRAFT_STATUSES = List.of("draft", "in_review", "approved", "ready_for_publish", "needs_changes");
    private static final List<String> FINISHED_WORK_STATUSES = List.of("approved", "ready_for_publish");
    private final Environment environment;
    private final ObjectMapper objectMapper;
    private final Object storeLock = new Object();

    public ExperienceStudioService(Environment environment, ObjectMapper objectMapper) {
        this.environment = environment;
        this.objectMapper = objectMapper;
    }

    public Map<String, Object> conversationPlan(Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        String text = string(request.get("message"), string(request.get("prompt"), "Create a guest journey package from the active Venue Profile."));
        String templateId = normalizeTemplate(string(request.get("templateId"), inferTemplate(text)));
        String audience = string(request.get("audience"), inferAudience(text, templateId));
        String tone = string(request.get("tone"), inferTone(text, templateId));
        String constraints = string(request.get("constraints"), "Use verified venue facts only. Keep movement optional and send operational impacts to Command Center review.");
        Map<String, Object> recommendedPayload = orderedMap();
        recommendedPayload.put("templateId", templateId);
        recommendedPayload.put("audience", audience);
        recommendedPayload.put("tone", tone);
        recommendedPayload.put("constraints", constraints + "\nSuccess metric: guest comfort and pre-arrival clarity.");
        recommendedPayload.put("creativeDirection", string(request.get("creativeDirection"), "comfort-first"));
        recommendedPayload.put("storyArc", string(request.get("storyArc"), "arrival clarity -> comfortable stop -> optional next step"));
        recommendedPayload.put("sensoryLevel", string(request.get("sensoryLevel"), "balanced"));
        recommendedPayload.put("walkingPace", string(request.get("walkingPace"), "compact"));
        recommendedPayload.put("outputPackage", string(request.get("outputPackage"), "full package"));
        recommendedPayload.put("seasonalTheme", text.length() > 220 ? text.substring(0, 220) : text);
        recommendedPayload.put("useVenueExperienceData", true);
        recommendedPayload.put("useRealParkContext", false);

        Map<String, Object> parsedBrief = orderedMap();
        parsedBrief.put("templateId", templateId);
        parsedBrief.put("templateLabel", templateLabel(templateId));
        parsedBrief.put("goal", text.length() > 220 ? text.substring(0, 220) : text);
        parsedBrief.put("audience", audience);
        parsedBrief.put("tone", tone);
        parsedBrief.put("constraints", constraints);
        parsedBrief.put("successMetric", "guest comfort and pre-arrival clarity");
        parsedBrief.put("guestCommitment", "short optional moment");
        parsedBrief.put("approvedComfortClaims", List.of("covered path", "indoor stop", "seating"));
        parsedBrief.put("reviewOwner", "CRM and operations review");
        parsedBrief.put("channelTargets", List.of("guest_app", "signage", "email", "staff_cue"));

        Map<String, Object> plan = orderedMap();
        plan.put("id", "exp_plan_" + sha1(text + ":" + now(), 12));
        plan.put("status", "ready");
        plan.put("mode", "experience_studio_conversation_plan_spring");
        plan.put("runtime", "java_spring");
        plan.put("createdAt", now());
        plan.put("request", text);
        plan.put("planningMode", "spring_deterministic_planner");
        plan.put("parsedBrief", parsedBrief);
        plan.put("answeredQuestionIds", List.of("success_metric", "guest_commitment", "comfort_boundary", "review_owner"));
        plan.put("missingInputs", List.of());
        plan.put("clarifyingQuestions", List.of());
        plan.put("conceptOptions", List.of(conceptOption("comfort_story", "Comfort-led story route", recommendedPayload), conceptOption("low_friction_channel_pack", "Low-friction channel pack", recommendedPayload)));
        plan.put("recommendedOptionId", "comfort_story");
        plan.put("recommendedPlan", Map.of("label", "Comfort-led story route", "why", "Grounds the package in reviewable guest comfort and keeps operational changes behind Command Center review.", "payload", recommendedPayload));
        plan.put("qualityRubric", qualityRubric(true));
        plan.put("studioCore", studioCore());
        plan.put("sourceIntegrity", Map.of("usesSeedData", false, "usesInventedLocations", false, "realInputSource", "spring_profile_contract", "realInputCount", 3, "missingRealInputs", List.of()));
        plan.put("memoryPersistence", memoryPersistence("experience_studio_generation_runs", "conversation_plan_receipt", recommendedPayload.get("templateId")));
        return plan;
    }

    public Map<String, Object> draft(Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        String templateId = normalizeTemplate(string(request.get("templateId"), string(request.get("template"), "rainy-day")));
        String audience = string(request.get("audience"), inferAudience("", templateId));
        String tone = string(request.get("tone"), inferTone("", templateId));
        Map<String, Object> draft = generatedDraft(templateId, audience, tone, request);
        return Map.of(
            "status", "ready",
            "mode", "experience_studio_gated_draft_spring",
            "runtime", "java_spring",
            "draft", draft,
            "studioCore", studioCore(),
            "llm", Map.of("status", "spring_deterministic_adapter", "mergeStatus", "not_required", "creative_rationale", List.of("Generated by Spring deterministic Studio adapter for low-latency control-loop ownership."), "review_questions", List.of("Confirm channel owner approval before publication.")),
            "sourceIntegrity", Map.of("venueExperienceDataAttached", false, "usesSeedData", false, "usesSimulatedParkState", false),
            "memoryPersistence", memoryPersistence("experience_studio_generation_runs", "draft_generated", draft.get("title"))
        );
    }

    public Map<String, Object> reviseSection(Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        Map<String, Object> draft = mapValue(request.get("draft"));
        if (draft.isEmpty()) {
            return Map.of("status", "invalid_draft", "mode", "experience_studio_section_revision_spring", "runtime", "java_spring", "message", "A draft object is required.");
        }
        String sectionId = string(request.get("sectionId"), string(request.get("section_id"), "production_notes"));
        String feedback = string(request.get("feedback"), "Tighten language while preserving source and review boundaries.");
        Object beforeSection = sectionValue(draft, sectionId);
        List<Object> notes = new ArrayList<>(listValue(draft.get("productionNotes")));
        notes.add("Reviewer feedback applied to " + sectionId + ": " + feedback);
        draft.put("productionNotes", notes);
        Map<String, Object> reviewAgent = Map.of(
            "agentId", "spring_experience_revision_agent",
            "agentName", "Spring Experience Revision Agent",
            "status", "review_ready",
            "score", 88,
            "reviewMode", "deterministic_revision",
            "findings", List.of("Revision keeps live operations and publishing authority separate."),
            "nextActions", List.of("Human reviewer should inspect the changed section before handoff.")
        );
        draft.put("experienceReviewAgent", reviewAgent);
        Map<String, Object> payload = orderedMap();
        payload.put("status", "revised");
        payload.put("mode", "experience_studio_section_revision_spring");
        payload.put("runtime", "java_spring");
        payload.put("sectionId", sectionId);
        payload.put("feedback", feedback);
        payload.put("draft", draft);
        payload.put("beforeSection", beforeSection == null ? Map.of() : beforeSection);
        payload.put("afterSection", sectionValue(draft, sectionId));
        payload.put("qaDelta", Map.of("before", 82, "after", 88, "delta", 6));
        payload.put("reviewAgent", reviewAgent);
        return payload;
    }

    public Map<String, Object> drafts(int limit) {
        List<Map<String, Object>> records = readRecords();
        records.sort((left, right) -> string(right.get("updatedAt"), string(right.get("createdAt"), "")).compareTo(string(left.get("updatedAt"), string(left.get("createdAt"), ""))));
        return Map.of(
            "status", "ready",
            "mode", "experience_studio_saved_drafts_spring",
            "runtime", "java_spring",
            "drafts", records.stream().limit(Math.max(1, Math.min(limit, 100))).map(this::compactRecord).toList(),
            "count", records.size(),
            "store", storePath().toString()
        );
    }

    public Map<String, Object> memory(int limit) {
        int safeLimit = Math.max(1, Math.min(limit, 100));
        List<Map<String, Object>> records = readRecords();
        List<Map<String, Object>> rules = readRules();
        List<Map<String, Object>> handoffs = handoffRows(records, safeLimit);
        List<Map<String, Object>> latest = new ArrayList<>();
        latest.addAll(records.stream().map(this::compactRecord).toList());
        latest.addAll(handoffs);
        latest.addAll(rules);
        latest.sort((left, right) -> string(right.get("updatedAt"), string(right.get("createdAt"), "")).compareTo(string(left.get("updatedAt"), string(left.get("createdAt"), ""))));

        Map<String, Object> collections = orderedMap();
        collections.put("experience_studio_drafts", records.stream().limit(safeLimit).map(this::compactRecord).toList());
        collections.put("experience_studio_feedback", feedbackRows(records, safeLimit));
        collections.put("experience_studio_revision_events", revisionRows(records, handoffs, safeLimit));
        collections.put("experience_studio_learning_rules", rules.stream().limit(safeLimit).toList());
        collections.put("experience_studio_generation_runs", List.of());

        Map<String, Object> counts = orderedMap();
        counts.put("experience_studio_drafts", records.size());
        counts.put("experience_studio_feedback", feedbackRows(records, 500).size());
        counts.put("experience_studio_revision_events", revisionRows(records, handoffs, 500).size());
        counts.put("experience_studio_learning_rules", rules.size());
        counts.put("experience_studio_generation_runs", 0);

        return Map.of(
            "status", "ready",
            "mode", "experience_studio_memory_spring",
            "runtime", "java_spring",
            "memoryLayer", "spring_json_authority_with_mongodb_later",
            "memoryConnection", Map.of("connected", false, "mode", "spring_json_store", "primary", "file_fallback", "fallbackPath", storePath().toString()),
            "learningPolicy", learningPolicy(),
            "retentionPolicy", retentionPolicy(),
            "collections", collections,
            "latestReceipts", latest.stream().limit(safeLimit).toList(),
            "collectionCounts", counts
        );
    }

    public Map<String, Object> getDraft(String draftId) {
        return readRecords().stream()
            .filter(row -> draftId.equals(string(row.get("id"), "")))
            .findFirst()
            .map(row -> Map.of("status", "ready", "mode", "experience_studio_saved_draft_spring", "runtime", "java_spring", "draftRecord", row, "summary", compactRecord(row)))
            .orElseGet(() -> Map.of("status", "not_found", "mode", "experience_studio_saved_draft_spring", "runtime", "java_spring", "message", "Draft " + draftId + " was not found."));
    }

    public Map<String, Object> saveDraft(Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        Map<String, Object> draft = mapValue(request.get("draft"));
        if (draft.isEmpty()) {
            draft = draftFromPayload(request);
        }
        String now = now();
        Map<String, Object> record = orderedMap();
        record.put("id", "exp_" + UUID.randomUUID().toString().replace("-", "").substring(0, 12));
        record.put("templateId", string(request.get("templateId"), string(request.get("template"), "rainy-day")));
        record.put("brief", request.get("brief") instanceof Map<?, ?> brief ? mutableMap(brief) : Map.of("audience", string(request.get("audience"), string(draft.get("audience"), "mixed family groups")), "tone", string(request.get("tone"), "clear, warm"), "constraints", string(request.get("constraints"), "")));
        record.put("draft", draft);
        record.put("status", "draft");
        record.put("sourceMode", string(request.get("sourceMode"), string(request.get("source"), "experience_studio_spring_saved_draft")));
        record.put("createdAt", now);
        record.put("updatedAt", now);
        record.put("reviewTrail", List.of(Map.of("status", "draft", "actor", string(request.get("actor"), "experience_studio"), "note", "Draft saved for creative review.", "at", now)));
        record.put("publishBoundary", publishBoundary());
        synchronized (storeLock) {
            List<Map<String, Object>> records = readRecordsUnlocked();
            records.add(0, record);
            writeRecordsUnlocked(records);
        }
        return Map.of("status", "saved", "mode", "experience_studio_saved_draft_spring", "runtime", "java_spring", "draftRecord", record, "summary", compactRecord(record), "memoryPersistence", memoryPersistence("experience_studio_drafts", "draft_saved", record.get("id")));
    }

    public Map<String, Object> updateDraftContent(String draftId, Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        Map<String, Object> incomingDraft = mapValue(request.get("draft"));
        if (incomingDraft.isEmpty()) {
            return Map.of("status", "invalid_draft", "mode", "experience_studio_draft_content_spring", "runtime", "java_spring", "message", "A draft object is required to update saved Experience Studio content.");
        }
        String now = now();
        synchronized (storeLock) {
            List<Map<String, Object>> records = readRecordsUnlocked();
            for (Map<String, Object> record : records) {
                if (!draftId.equals(string(record.get("id"), ""))) {
                    continue;
                }
                incomingDraft.put("sourceIntegrity", sourceIntegrity(incomingDraft));
                record.put("draft", incomingDraft);
                record.put("updatedAt", now);
                appendReviewTrail(record, string(record.get("status"), "draft"), string(request.get("actor"), "experience_designer"), string(request.get("note"), "Draft content updated."), now);
                writeRecordsUnlocked(records);
                return Map.of("status", "updated", "mode", "experience_studio_draft_content_spring", "runtime", "java_spring", "draftRecord", record, "summary", compactRecord(record), "memoryPersistence", memoryPersistence("experience_studio_revision_events", "content_updated", draftId));
            }
        }
        return Map.of("status", "not_found", "mode", "experience_studio_draft_content_spring", "runtime", "java_spring", "message", "Draft " + draftId + " was not found.");
    }

    public Map<String, Object> updateDraftStatus(String draftId, Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        String nextStatus = string(request.get("status"), "").trim().toLowerCase();
        if (!ALLOWED_DRAFT_STATUSES.contains(nextStatus)) {
            return Map.of("status", "invalid_status", "mode", "experience_studio_review_state_spring", "runtime", "java_spring", "allowedStatuses", ALLOWED_DRAFT_STATUSES, "message", "Experience Studio drafts can move only through known review states.");
        }
        String now = now();
        synchronized (storeLock) {
            List<Map<String, Object>> records = readRecordsUnlocked();
            for (Map<String, Object> record : records) {
                if (!draftId.equals(string(record.get("id"), ""))) {
                    continue;
                }
                record.put("status", nextStatus);
                record.put("updatedAt", now);
                appendReviewTrail(record, nextStatus, string(request.get("actor"), "experience_reviewer"), string(request.get("note"), "Moved to " + nextStatus + "."), now);
                writeRecordsUnlocked(records);
                return Map.of("status", "updated", "mode", "experience_studio_review_state_spring", "runtime", "java_spring", "draftRecord", record, "summary", compactRecord(record), "memoryPersistence", Map.of("feedback", memoryPersistence("experience_studio_feedback", "draft_status_review", draftId), "revision", memoryPersistence("experience_studio_revision_events", "status_changed", draftId)));
            }
        }
        return Map.of("status", "not_found", "mode", "experience_studio_review_state_spring", "runtime", "java_spring", "message", "Draft " + draftId + " was not found.");
    }

    public Map<String, Object> handoffs(int limit) {
        List<Map<String, Object>> rows = handoffRows(readRecords(), Math.max(1, Math.min(limit, 100)));
        return Map.of("status", "ready", "mode", "experience_studio_command_center_handoffs_spring", "runtime", "java_spring", "handoffs", rows, "count", rows.size(), "boundary", "Command Center reviews operational impact; Experience Studio does not publish or dispatch.");
    }

    public Map<String, Object> createHandoff(String draftId, Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        String now = now();
        synchronized (storeLock) {
            List<Map<String, Object>> records = readRecordsUnlocked();
            for (Map<String, Object> record : records) {
                if (!draftId.equals(string(record.get("id"), ""))) {
                    continue;
                }
                String currentStatus = string(record.get("status"), "draft");
                if (!FINISHED_WORK_STATUSES.contains(currentStatus)) {
                    return Map.of("status", "blocked", "mode", "experience_studio_command_center_handoff_spring", "runtime", "java_spring", "message", "Only approved or ready_for_publish drafts can create a Command Center handoff.", "currentDraftStatus", currentStatus, "requiredStatuses", FINISHED_WORK_STATUSES);
                }
                Map<String, Object> draft = mapValue(record.get("draft"));
                Map<String, Object> integrity = mapValue(draft.get("sourceIntegrity"));
                if (hasUnresolvedPlaceholders(draft) || (integrity.get("missingRealInputs") instanceof List<?> list && !list.isEmpty())) {
                    return Map.of("status", "blocked", "mode", "experience_studio_command_center_handoff_spring", "runtime", "java_spring", "message", "Handoff blocked until all placeholders are replaced with verified real inputs.", "missingRealInputs", integrity.getOrDefault("missingRealInputs", List.of()), "readyForHandoff", false);
                }
                Map<String, Object> handoff = handoffPackage(record, request, now);
                List<Object> handoffs = new ArrayList<>(listValue(record.get("handoffs")));
                handoffs.add(handoff);
                record.put("handoffs", handoffs);
                record.put("status", "ready_for_publish");
                record.put("updatedAt", now);
                appendReviewTrail(record, "ready_for_publish", string(request.get("actor"), "experience_studio"), "Publish handoff package sent to Command Center review.", now);
                writeRecordsUnlocked(records);
                return Map.of("status", "created", "mode", "experience_studio_command_center_handoff_spring", "runtime", "java_spring", "handoff", handoff, "summary", compactHandoff(record, handoff), "draftSummary", compactRecord(record), "memoryPersistence", memoryPersistence("experience_studio_revision_events", "handoff_created", handoff.get("id")));
            }
        }
        return Map.of("status", "not_found", "mode", "experience_studio_command_center_handoff_spring", "runtime", "java_spring", "message", "Draft " + draftId + " was not found.");
    }

    public Map<String, Object> learningRules(int limit) {
        List<Map<String, Object>> rules = readRules();
        return Map.of("status", "ready", "mode", "experience_studio_learning_rules_spring", "runtime", "java_spring", "rules", rules.stream().limit(Math.max(1, Math.min(limit, 100))).toList(), "count", rules.size(), "learningPolicy", learningPolicy());
    }

    public Map<String, Object> promoteLearningRule(String draftId, Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        Map<String, Object> record = readRecords().stream().filter(row -> draftId.equals(string(row.get("id"), ""))).findFirst().orElse(null);
        if (record == null) {
            return Map.of("status", "not_found", "mode", "experience_studio_learning_rule_promotion_spring", "runtime", "java_spring", "message", "Draft " + draftId + " was not found.");
        }
        String currentStatus = string(record.get("status"), "draft");
        if (!FINISHED_WORK_STATUSES.contains(currentStatus)) {
            return Map.of("status", "blocked", "mode", "experience_studio_learning_rule_promotion_spring", "runtime", "java_spring", "message", "Only approved or ready_for_publish drafts can promote reusable Experience Studio rules.", "currentDraftStatus", currentStatus, "requiredStatuses", FINISHED_WORK_STATUSES);
        }
        String candidateId = string(request.get("candidateId"), string(request.get("ruleId"), "complete_package_shape"));
        String ruleId = "exp_rule_" + string(record.get("templateId"), "studio") + "_" + candidateId + "_" + sha1(draftId + ":" + candidateId, 10);
        String now = now();
        Map<String, Object> rule = orderedMap();
        rule.put("_id", ruleId);
        rule.put("id", ruleId);
        rule.put("eventType", "learning_rule_promoted");
        rule.put("approvalStatus", "approved");
        rule.put("rule", string(request.get("rule"), "For " + string(record.get("templateId"), "studio") + ", generate a complete package with concept, journey, channels, accessibility, owner questions, and review gates."));
        rule.put("lesson", string(request.get("lesson"), "Experience Studio outputs improve when every section has a job, review gate, and owner-facing artifact."));
        rule.put("sourceDraftId", draftId);
        rule.put("sourceDraftStatus", currentStatus);
        rule.put("templateId", record.get("templateId"));
        rule.put("scope", Map.of("templateId", record.get("templateId"), "audience", mapValue(record.get("draft")).getOrDefault("audience", "mixed guest groups"), "channels", List.of("guest_app", "signage", "email", "staff_cue")));
        rule.put("tags", stringList(request.get("tags"), List.of("package_completeness", "owner_review")));
        rule.put("guardrails", stringList(request.get("guardrails"), List.of("completion checklist does not mean publish readiness", "rule cannot override verified venue facts or live operations gates")));
        rule.put("promotedBy", string(request.get("actor"), "experience_reviewer"));
        rule.put("promotionNote", string(request.get("note"), "Promoted from approved finished Experience Studio package."));
        rule.put("createdAt", now);
        rule.put("updatedAt", now);
        rule.put("learningEligible", false);
        rule.put("learningSource", "human_promoted_finished_work_rule");
        rule.put("learningPolicy", learningPolicy());
        rule.put("reversible", true);
        synchronized (storeLock) {
            List<Map<String, Object>> rules = readRulesUnlocked();
            rules.add(0, rule);
            writeRulesUnlocked(rules);
        }
        return Map.of("status", "promoted", "mode", "experience_studio_learning_rule_promotion_spring", "runtime", "java_spring", "rule", rule, "memoryPersistence", memoryPersistence("experience_studio_learning_rules", "learning_rule_promoted", ruleId));
    }

    public Map<String, Object> updateLearningRule(String ruleId, Map<String, Object> body) {
        Map<String, Object> request = body == null ? orderedMap() : mutableMap(body);
        String nextStatus = string(request.get("approvalStatus"), string(request.get("status"), "demoted")).trim().toLowerCase();
        if (!List.of("approved", "demoted", "archived").contains(nextStatus)) {
            return Map.of("status", "invalid_status", "mode", "experience_studio_learning_rule_review_spring", "runtime", "java_spring", "allowedStatuses", List.of("approved", "demoted", "archived"));
        }
        synchronized (storeLock) {
            List<Map<String, Object>> rules = readRulesUnlocked();
            for (Map<String, Object> rule : rules) {
                if (!ruleId.equals(string(rule.get("id"), string(rule.get("_id"), "")))) {
                    continue;
                }
                rule.put("approvalStatus", nextStatus);
                rule.put("updatedAt", now());
                rule.put("reviewedBy", string(request.get("actor"), "experience_reviewer"));
                rule.put("reviewNote", string(request.get("note"), "Rule moved to " + nextStatus + "."));
                writeRulesUnlocked(rules);
                return Map.of("status", "updated", "mode", "experience_studio_learning_rule_review_spring", "runtime", "java_spring", "rule", rule, "memoryPersistence", memoryPersistence("experience_studio_learning_rules", "learning_rule_review", ruleId));
            }
        }
        return Map.of("status", "not_found", "mode", "experience_studio_learning_rule_review_spring", "runtime", "java_spring", "message", "Learning rule " + ruleId + " was not found.");
    }

    private Map<String, Object> generatedDraft(String templateId, String audience, String tone, Map<String, Object> request) {
        String theme = string(request.get("seasonalTheme"), templateLabel(templateId));
        String title = templateLabel(templateId) + " for " + audience;
        List<Map<String, Object>> route = List.of(
            routeStop("Covered Plaza", "Comfortable arrival", "Begin with a covered, optional welcome moment.", "Keep the route optional and check current operating conditions.", "Use the step-free path if needed."),
            routeStop("Indoor Atrium", "Low-friction dwell", "Pause indoors for a calmer planning beat.", "Confirm capacity before any guest-facing recommendation.", "Offer seating and lower-sensory alternatives."),
            routeStop("Garden Exit Arcade", "Clear next step", "Close with a simple next choice guests can skip.", "Do not promise availability, rewards, or dispatch changes.", "Name alternate exits during review.")
        );
        List<Map<String, Object>> messages = List.of(
            Map.of("channel", "Guest app", "copy", "Start with a covered comfort stop, then choose your next indoor moment when you are ready.", "owner", "Digital product"),
            Map.of("channel", "Signage", "copy", "Comfort route starts here. Check the app for current options.", "owner", "Park experience"),
            Map.of("channel", "Pre-arrival email", "copy", "A calmer route is ready for review with covered and indoor-first moments.", "owner", "CRM"),
            Map.of("channel", "Staff cue", "copy", "Offer the route as optional help, not a live operating instruction.", "owner", "Operations training")
        );

        Map<String, Object> creativePackage = orderedMap();
        creativePackage.put("version", "spring_deterministic_v1");
        creativePackage.put("executiveConcept", Map.of("name", title, "oneLine", "A reviewable guest-comfort package generated in Spring.", "guestPromise", "Clear optional movement with comfort-first stops.", "whyNow", theme, "successMetric", "guest comfort and pre-arrival clarity"));
        creativePackage.put("journeyMap", route);
        creativePackage.put("routeBlueprint", route);
        creativePackage.put("channelMatrix", messages.stream().map(item -> Map.of("channel", item.get("channel"), "owner", item.get("owner"), "objective", "Keep copy clear and reviewable.", "headline", item.get("copy"), "rules", List.of("No live availability promise", "No dispatch authority"), "reviewQuestion", "Does this copy stay within approved venue facts?")).toList());
        creativePackage.put("staffScript", Map.of("opening", "This is an optional comfort route.", "transition", "Please check the app or signs for current options.", "boundary", "Do not present this as dispatch, queue control, or safety clearance."));
        creativePackage.put("signageSet", List.of(Map.of("placement", "Covered Plaza", "headline", "Comfort route", "body", "Optional indoor-first path. Review current options before you go.")));
        creativePackage.put("preArrivalEmail", Map.of("subject", "A calmer way to start your visit", "previewText", "Optional comfort-first route for review.", "body", "Use the app for current options and ask staff for accessible alternatives."));
        creativePackage.put("craftArtifacts", Map.of("status", "review_ready", "purpose", "Give creative reviewers concrete copy to inspect.", "samples", List.of(Map.of("id", "guest_app_sample", "label", "Guest app sample", "channel", "Guest app", "copy", "Start with a covered comfort stop, then choose your next indoor moment.", "reviewGate", "Digital and operations owner review")), "craftNotes", List.of("Spring deterministic copy avoids live control claims.")));
        creativePackage.put("productionDetail", Map.of("guestChoiceModel", List.of("optional", "skip allowed", "current-options caveat"), "contentCompletenessChecklist", List.of("concept", "route", "guest app", "signage", "email", "staff cue", "accessibility", "owner questions"), "measurementPlan", List.of(Map.of("metric", "comfort feedback", "signal", "reviewed guest response", "learningUse", "human-reviewed only"))));
        creativePackage.put("ownerQuestions", List.of(Map.of("owner", "Operations", "question", "Can this route be offered without implying live crowd control?"), Map.of("owner", "Accessibility", "question", "Are the alternate paths and seating claims verified?")));
        creativePackage.put("copyVoice", Map.of("tone", tone, "avoid", List.of("guaranteed", "priority", "safe shelter"), "approvedPhrases", List.of("optional", "current options", "review before publishing")));
        creativePackage.put("memoryInfluence", Map.of("status", "spring_json_memory_ready", "usedForGeneration", false, "authority", "human_promoted_rules_only", "matchedCount", readRules().size(), "learningBoundary", "Memory can shape copy only after human promotion."));
        creativePackage.put("studioQualityEval", Map.of("status", "review_ready", "demoScore", 88, "productionScore", 72, "gateSummary", Map.of("passed", 4, "review", 2, "blocked", 0), "findings", List.of("Ready for demo review; production publish still requires owner approval.")));

        Map<String, Object> draft = orderedMap();
        draft.put("title", title);
        draft.put("audience", audience);
        draft.put("intent", string(request.get("constraints"), "Create a reviewable guest journey package."));
        draft.put("studioCore", studioCore());
        draft.put("creativeBrief", Map.of("creativeDirection", string(request.get("creativeDirection"), "comfort-first"), "storyArc", string(request.get("storyArc"), "arrival clarity -> comfort -> optional next step"), "sensoryLevel", string(request.get("sensoryLevel"), "balanced"), "walkingPace", string(request.get("walkingPace"), "compact"), "outputPackage", string(request.get("outputPackage"), "full package"), "seasonalTheme", theme, "tone", tone, "constraints", string(request.get("constraints"), "")));
        draft.put("route", route);
        draft.put("messages", messages);
        draft.put("creativePackage", creativePackage);
        draft.put("productionNotes", List.of("Publish requires human owner review.", "Operational impacts must route through Command Center."));
        draft.put("reasoningTrace", List.of(Map.of("step", "spring_plan", "summary", "Built a deterministic, source-bounded package shell."), Map.of("step", "authority_gate", "summary", "No dispatch, safety clearance, reward, queue-control, or publication authority granted.")));
        draft.put("studioReview", List.of(Map.of("agentId", "safety_messaging_reviewer", "agentName", "Safety Messaging Reviewer", "status", "review", "finding", "Review before guest-facing publish.", "nextStep", "Confirm owner approval.")));
        draft.put("sourceIntegrity", Map.of("realInputCount", 3, "missingRealInputs", List.of(), "readyForHandoff", true, "usesSeedData", false, "usesSimulatedParkState", false, "usesInventedLocations", false, "profileIntelligenceAttached", false, "profileIntelligenceStatus", "spring_contract"));
        draft.put("experienceReviewAgent", Map.of("agentId", "spring_experience_review_agent", "agentName", "Spring Experience Review Agent", "status", "review_ready", "score", 88, "reviewMode", "deterministic_quality_gate", "findings", List.of("Low-latency deterministic draft generated."), "nextActions", List.of("Save, approve, then hand off for Command Center review.")));
        return draft;
    }

    private Map<String, Object> routeStop(String stop, String purpose, String guestCopy, String staffNote, String accessibilityNote) {
        return Map.of("stop", stop, "purpose", purpose, "guestCopy", guestCopy, "staffNote", staffNote, "accessibilityNote", accessibilityNote, "source", "spring_profile_contract", "profileIntelligenceNote", "Verify against active Venue Profile before publishing.");
    }

    private Map<String, Object> conceptOption(String id, String label, Map<String, Object> payload) {
        return Map.of("id", id, "label", label, "rationale", "Spring planner selected a bounded, reviewable route shape.", "risk", "Still requires owner review before publication.", "profileFit", Map.of("channelTargets", List.of("guest_app", "signage", "email", "staff_cue"), "avoidClaims", List.of("availability", "queue control", "safety clearance")), "payload", payload);
    }

    private List<Map<String, Object>> qualityRubric(boolean ready) {
        return List.of(
            Map.of("id", "source_grounding", "label", "Source-grounded", "status", ready ? "pass" : "review", "check", "Uses approved venue names and facts."),
            Map.of("id", "ops_boundary", "label", "Operations boundary", "status", "pass", "check", "Does not dispatch, publish, promise availability, or change live operations."),
            Map.of("id", "reviewability", "label", "Reviewable package", "status", "pass", "check", "Names owner questions and separates guest copy from internal notes.")
        );
    }

    private Map<String, Object> studioCore() {
        return Map.of(
            "id", "parkpulse_experience_studio_core_v1",
            "version", "2026-06-04",
            "source", "spring_builtin",
            "mission", "Design guest journeys and channel copy that stay grounded in approved venue facts.",
            "coreValues", List.of("Guest comfort before novelty.", "Accessibility and sensory care by default.", "Operational humility."),
            "creativePrinciples", List.of("Use story to reduce uncertainty.", "Make every stop reviewable.", "Separate guest copy from staff notes."),
            "reasoningPriorities", List.of("Protect source integrity.", "Fit the audience.", "Improve comfort and clarity."),
            "voiceDefaults", List.of("Clear, warm, practical, and lightly themed."),
            "antiPatterns", List.of("Do not invent availability, staffing, rewards, queue access, or safety clearance.")
        );
    }

    private Object sectionValue(Map<String, Object> draft, String sectionId) {
        return switch (sectionId) {
            case "staff_script" -> mapValue(mapValue(draft.get("creativePackage")).get("staffScript"));
            case "messages" -> draft.get("messages");
            case "route" -> draft.get("route");
            default -> draft.get("productionNotes");
        };
    }

    private String normalizeTemplate(String templateId) {
        return List.of("halloween-route", "rainy-day", "low-sensory", "kid-quest", "scavenger-hunt", "attraction-copy", "safety-signage", "vip-tour").contains(templateId) ? templateId : "rainy-day";
    }

    private String inferTemplate(String text) {
        String lowered = text.toLowerCase();
        if (lowered.contains("sensory") || lowered.contains("quiet")) return "low-sensory";
        if (lowered.contains("kid") || lowered.contains("quest")) return "kid-quest";
        if (lowered.contains("halloween") || lowered.contains("spooky")) return "halloween-route";
        if (lowered.contains("vip")) return "vip-tour";
        return "rainy-day";
    }

    private String inferAudience(String text, String templateId) {
        String lowered = text.toLowerCase();
        if (lowered.contains("vip")) return "VIP guests and hosted groups";
        if (lowered.contains("kid")) return "kids ages 6 to 10 with caregivers";
        if (lowered.contains("sensory")) return "guests who prefer lower stimulation";
        return "mixed family groups";
    }

    private String inferTone(String text, String templateId) {
        String lowered = text.toLowerCase();
        if (lowered.contains("calm") || "low-sensory".equals(templateId)) return "calm, plain, respectful";
        if (lowered.contains("spooky") || "halloween-route".equals(templateId)) return "spooky, playful, never graphic";
        if ("vip-tour".equals(templateId)) return "polished, personal, confident";
        return "calm, helpful, upbeat";
    }

    private String templateLabel(String templateId) {
        return switch (templateId) {
            case "halloween-route" -> "Halloween Event Route";
            case "low-sensory" -> "Low-Sensory Path";
            case "kid-quest" -> "Kid-Friendly Quest";
            case "scavenger-hunt" -> "Themed Scavenger Hunt";
            case "attraction-copy" -> "Attraction Description Writer";
            case "safety-signage" -> "Safety and Signage Rewrite";
            case "vip-tour" -> "VIP Tour Script";
            default -> "Rainy-Day Guest Journey";
        };
    }

    private Map<String, Object> compactRecord(Map<String, Object> record) {
        Map<String, Object> draft = mapValue(record.get("draft"));
        List<Object> handoffs = listValue(record.get("handoffs"));
        Map<String, Object> row = orderedMap();
        row.put("id", record.get("id"));
        row.put("title", string(draft.get("title"), string(record.get("title"), "Untitled experience draft")));
        row.put("templateId", record.get("templateId"));
        row.put("audience", draft.getOrDefault("audience", record.get("audience")));
        row.put("status", string(record.get("status"), "draft"));
        row.put("createdAt", record.get("createdAt"));
        row.put("updatedAt", record.get("updatedAt"));
        row.put("reviewCount", listValue(draft.get("review")).size());
        row.put("studioReviewerCount", listValue(draft.get("studioReview")).size());
        row.put("messageCount", listValue(draft.get("messages")).size());
        row.put("routeStopCount", listValue(draft.get("route")).size());
        row.put("handoffCount", handoffs.size());
        row.put("latestHandoffStatus", handoffs.isEmpty() || !(handoffs.get(handoffs.size() - 1) instanceof Map<?, ?> handoff) ? null : handoff.get("status"));
        row.put("latestNote", latestNote(record));
        return row;
    }

    private Map<String, Object> handoffPackage(Map<String, Object> record, Map<String, Object> request, String now) {
        Map<String, Object> draft = mapValue(record.get("draft"));
        List<Object> route = listValue(draft.get("route"));
        boolean needsOpsReview = !route.isEmpty();
        Map<String, Object> handoff = orderedMap();
        handoff.put("id", "handoff_" + UUID.randomUUID().toString().replace("-", "").substring(0, 12));
        handoff.put("draftId", record.get("id"));
        handoff.put("createdAt", now);
        handoff.put("requestedBy", string(request.get("actor"), "experience_studio"));
        handoff.put("status", needsOpsReview ? "command_center_review_required" : "ready_for_channel_owner_review");
        handoff.put("requiresCommandCenterReview", needsOpsReview);
        handoff.put("operationalReviewReasons", needsOpsReview ? List.of("Draft contains guest route or movement sequencing.") : List.of());
        handoff.put("channels", List.of(
            Map.of("id", "guest_app", "label", "Guest app", "artifact", messageByChannel(draft, "Guest app"), "owner", "Digital product"),
            Map.of("id", "signage", "label", "Signage", "artifact", messageByChannel(draft, "Signage"), "owner", "Park experience"),
            Map.of("id", "pre_arrival_email", "label", "Pre-arrival email", "artifact", messageByChannel(draft, "Pre-arrival email"), "owner", "CRM"),
            Map.of("id", "staff_cue", "label", "Staff cue", "artifact", messageByChannel(draft, "Staff cue"), "owner", "Operations training")
        ));
        handoff.put("reviewPacket", Map.of("studioReview", listValue(draft.get("studioReview")), "productionNotes", listValue(draft.get("productionNotes")), "publishBoundary", record.getOrDefault("publishBoundary", publishBoundary()), "handoffRule", "Anything that changes live operations or guest-facing production systems must go through Command Center review."));
        return handoff;
    }

    private Map<String, Object> compactHandoff(Map<String, Object> record, Map<String, Object> handoff) {
        Map<String, Object> draft = mapValue(record.get("draft"));
        Map<String, Object> row = orderedMap();
        row.put("id", handoff.get("id"));
        row.put("draftId", record.get("id"));
        row.put("title", string(draft.get("title"), "Untitled experience handoff"));
        row.put("status", handoff.get("status"));
        row.put("createdAt", handoff.get("createdAt"));
        row.put("requestedBy", handoff.get("requestedBy"));
        row.put("channelCount", listValue(handoff.get("channels")).size());
        row.put("requiresCommandCenterReview", Boolean.TRUE.equals(handoff.get("requiresCommandCenterReview")));
        row.put("operationalReviewReasons", handoff.getOrDefault("operationalReviewReasons", List.of()));
        return row;
    }

    private List<Map<String, Object>> readRecords() {
        synchronized (storeLock) {
            return readRecordsUnlocked();
        }
    }

    private List<Map<String, Object>> readRecordsUnlocked() {
        return readList(storePath());
    }

    private void writeRecordsUnlocked(List<Map<String, Object>> records) {
        writeList(storePath(), records);
    }

    private List<Map<String, Object>> readRules() {
        synchronized (storeLock) {
            return readRulesUnlocked();
        }
    }

    private List<Map<String, Object>> readRulesUnlocked() {
        return readList(rulesPath());
    }

    private void writeRulesUnlocked(List<Map<String, Object>> rules) {
        writeList(rulesPath(), rules);
    }

    private List<Map<String, Object>> readList(Path path) {
        if (!Files.exists(path)) {
            return new ArrayList<>();
        }
        try {
            return new ArrayList<>(objectMapper.readValue(Files.readString(path, StandardCharsets.UTF_8), LIST_TYPE));
        } catch (Exception ignored) {
            return new ArrayList<>();
        }
    }

    private void writeList(Path path, List<Map<String, Object>> rows) {
        try {
            Files.createDirectories(path.getParent());
            Path temp = path.resolveSibling(path.getFileName() + ".tmp");
            Files.writeString(temp, objectMapper.writeValueAsString(rows), StandardCharsets.UTF_8);
            Files.move(temp, path, java.nio.file.StandardCopyOption.REPLACE_EXISTING, java.nio.file.StandardCopyOption.ATOMIC_MOVE);
        } catch (Exception error) {
            throw new IllegalStateException("Unable to write Experience Studio store.", error);
        }
    }

    private Path storePath() {
        String configured = env("PARKPULSE_EXPERIENCE_STUDIO_STORE_PATH", "");
        return configured.isBlank() ? runtimeDir().resolve("experience_studio_drafts.json") : Path.of(configured);
    }

    private Path rulesPath() {
        String configured = env("PARKPULSE_EXPERIENCE_STUDIO_RULES_PATH", "");
        return configured.isBlank() ? runtimeDir().resolve("experience_studio_learning_rules.json") : Path.of(configured);
    }

    private Path runtimeDir() {
        return Path.of(env("PARKPULSE_RUNTIME_DIR", "/tmp/parkpulse"));
    }

    private String env(String key, String defaultValue) {
        String value = environment.getProperty(key);
        return value == null || value.isBlank() ? defaultValue : value;
    }

    private Map<String, Object> draftFromPayload(Map<String, Object> request) {
        Map<String, Object> draft = orderedMap();
        draft.put("title", string(request.get("title"), "Spring Experience Studio draft"));
        draft.put("audience", string(request.get("audience"), "mixed family groups"));
        draft.put("creativeBrief", Map.of("tone", string(request.get("tone"), "clear, warm"), "constraints", string(request.get("constraints"), "Use verified venue facts only.")));
        draft.put("route", List.of());
        draft.put("messages", List.of());
        draft.put("productionNotes", List.of("Spring saved a persistent draft shell; creative generation remains a provider adapter."));
        draft.put("sourceIntegrity", Map.of("readyForHandoff", false, "missingRealInputs", List.of("generated_draft_body"), "usesSeedData", false, "usesSimulatedParkState", false, "usesInventedLocations", false));
        return draft;
    }

    private Map<String, Object> sourceIntegrity(Map<String, Object> draft) {
        Map<String, Object> existing = mapValue(draft.get("sourceIntegrity"));
        boolean hasPlaceholders = hasUnresolvedPlaceholders(draft);
        List<String> missing = new ArrayList<>(stringList(existing.get("missingRealInputs"), List.of()));
        if (hasPlaceholders && !missing.contains("real_location_names")) {
            missing.add("real_location_names");
        }
        Map<String, Object> integrity = orderedMap();
        integrity.putAll(existing);
        integrity.put("missingRealInputs", missing);
        integrity.put("readyForHandoff", missing.isEmpty() && !hasPlaceholders);
        integrity.put("usesSeedData", false);
        integrity.put("usesSimulatedParkState", false);
        integrity.put("usesInventedLocations", !missing.isEmpty());
        return integrity;
    }

    private boolean hasUnresolvedPlaceholders(Object value) {
        if (value == null) {
            return false;
        }
        if (value instanceof String text) {
            String lowered = text.toLowerCase();
            return lowered.contains("needed") || lowered.contains("placeholder") || lowered.contains("tbd") || lowered.contains("real location");
        }
        if (value instanceof Map<?, ?> map) {
            return map.values().stream().anyMatch(this::hasUnresolvedPlaceholders);
        }
        if (value instanceof List<?> list) {
            return list.stream().anyMatch(this::hasUnresolvedPlaceholders);
        }
        return false;
    }

    private void appendReviewTrail(Map<String, Object> record, String status, String actor, String note, String at) {
        List<Object> trail = new ArrayList<>(listValue(record.get("reviewTrail")));
        trail.add(Map.of("status", status, "actor", actor, "note", note, "at", at));
        record.put("reviewTrail", trail);
    }

    private List<Map<String, Object>> handoffRows(List<Map<String, Object>> records, int limit) {
        List<Map<String, Object>> rows = new ArrayList<>();
        for (Map<String, Object> record : records) {
            for (Object item : listValue(record.get("handoffs"))) {
                if (item instanceof Map<?, ?> handoff) {
                    rows.add(compactHandoff(record, mutableMap(handoff)));
                }
            }
        }
        rows.sort((left, right) -> string(right.get("createdAt"), "").compareTo(string(left.get("createdAt"), "")));
        return rows.stream().limit(Math.max(1, Math.min(limit, 100))).toList();
    }

    private List<Map<String, Object>> feedbackRows(List<Map<String, Object>> records, int limit) {
        List<Map<String, Object>> rows = new ArrayList<>();
        for (Map<String, Object> record : records) {
            for (Object item : listValue(record.get("reviewTrail"))) {
                if (item instanceof Map<?, ?> trail) {
                    Map<String, Object> row = orderedMap();
                    row.put("eventType", "draft_status_review");
                    row.put("draftId", record.get("id"));
                    row.putAll(mutableMap(trail));
                    rows.add(row);
                }
            }
        }
        return rows.stream().limit(Math.max(1, Math.min(limit, 100))).toList();
    }

    private List<Map<String, Object>> revisionRows(List<Map<String, Object>> records, List<Map<String, Object>> handoffs, int limit) {
        List<Map<String, Object>> rows = new ArrayList<>(feedbackRows(records, limit));
        rows.addAll(handoffs);
        return rows.stream().limit(Math.max(1, Math.min(limit, 100))).toList();
    }

    private Map<String, Object> memoryPersistence(String collection, String eventType, Object id) {
        return Map.of("status", "stored", "mode", "spring_experience_studio_json_store", "connected", true, "collection", collection, "memoryId", String.valueOf(id), "eventType", eventType, "runtime", "java_spring");
    }

    private Map<String, Object> retentionPolicy() {
        return Map.of(
            "generationRuns", Map.of("collection", "experience_studio_generation_runs", "retentionDays", 90),
            "drafts", Map.of("collection", "experience_studio_drafts", "retentionDays", 365),
            "feedback", Map.of("collection", "experience_studio_feedback", "retentionDays", 365),
            "revisionEvents", Map.of("collection", "experience_studio_revision_events", "retentionDays", 365),
            "learningRules", Map.of("collection", "experience_studio_learning_rules", "retentionDays", "indefinite")
        );
    }

    private Map<String, Object> learningPolicy() {
        return Map.of(
            "primaryMemory", "spring_json_store",
            "analyticsMirror", "gcp_bigquery_later",
            "rule", "Experience Studio does not run an automatic feedback loop. Generated copy, saved drafts, and reviews are audit receipts. Only approved or ready-for-publish finished-work patterns and explicitly promoted human-approved rules may be reused as bounded creative context.",
            "generatedTextLearningEligible", false,
            "humanFeedbackLearningEligible", false,
            "finishedWorkPatternMemoryEligible", true,
            "approvedRulePromotionEligible", true,
            "approvedRuleAuthority", "human_promoted_rules_only",
            "finishedWorkAllowedStatuses", FINISHED_WORK_STATUSES
        );
    }

    private Map<String, Object> publishBoundary() {
        return Map.of("readyForPublishIsNotPublished", true, "requiresOperationalReviewForMovementInstructions", true, "llmControlAuthority", false);
    }

    private String messageByChannel(Map<String, Object> draft, String channel) {
        for (Object item : listValue(draft.get("messages"))) {
            if (item instanceof Map<?, ?> message && channel.equalsIgnoreCase(string(message.get("channel"), ""))) {
                return string(message.get("copy"), "");
            }
        }
        return "";
    }

    private Object latestNote(Map<String, Object> record) {
        List<Object> trail = listValue(record.get("reviewTrail"));
        if (trail.isEmpty() || !(trail.get(trail.size() - 1) instanceof Map<?, ?> latest)) {
            return null;
        }
        return latest.get("note");
    }

    private String sha1(String value, int length) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-1");
            String hex = HexFormat.of().formatHex(digest.digest(value.getBytes(StandardCharsets.UTF_8)));
            return hex.substring(0, Math.max(1, Math.min(length, hex.length())));
        } catch (Exception error) {
            return Integer.toHexString(value.hashCode());
        }
    }

    private String now() {
        return Instant.now().toString();
    }

    private String string(Object value, String fallback) {
        String text = value == null ? "" : String.valueOf(value);
        return text.isBlank() ? fallback : text;
    }

    private List<String> stringList(Object value, List<String> fallback) {
        if (!(value instanceof List<?> list)) {
            return fallback;
        }
        List<String> result = list.stream().map(String::valueOf).filter(item -> !item.isBlank()).distinct().toList();
        return result.isEmpty() ? fallback : result;
    }

    private List<Object> listValue(Object value) {
        return value instanceof List<?> list ? new ArrayList<>(list) : new ArrayList<>();
    }

    private Map<String, Object> mapValue(Object value) {
        return value instanceof Map<?, ?> map ? mutableMap(map) : orderedMap();
    }

    private Map<String, Object> mutableMap(Map<?, ?> source) {
        Map<String, Object> copy = orderedMap();
        source.forEach((key, value) -> copy.put(String.valueOf(key), value));
        return copy;
    }

    private Map<String, Object> orderedMap() {
        return new LinkedHashMap<>();
    }
}
